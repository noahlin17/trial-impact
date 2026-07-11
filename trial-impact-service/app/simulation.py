"""Real biophysical simulation pipeline: docking (AutoDock Vina) + PK/PD.

This is the canonical, runnable implementation of the "tissue/protein simulation"
that a **Devin session executes** for each clinical-trial event. It is deliberately
self-contained and CLI-driven so Devin can clone the repo, install the heavy
scientific stack, and run it:

    python -m app.simulation \
        --target PCSK9 --drug evolocumab --tissue hepatic --dose 140 --json-only

Pipeline
--------
1. **Resolve target → UniProt** (UniProt REST search).
2. **Fetch a real structure** — best experimental PDB via PDBe/SIFTS, else the
   AlphaFold DB predicted model.
3. **Fetch the ligand** — PubChem PUG-REST name→SMILES, then RDKit 3D embedding.
4. **Prepare receptor + ligand** to PDBQT (Meeko for the ligand, OpenBabel for the
   receptor).
5. **Dock** with AutoDock Vina → best binding free energy ΔG (kcal/mol); derive the
   dissociation constant ``Kd`` from ΔG = RT·ln(Kd).
6. **PK/PD** — a first-order-absorption one-compartment ODE (SciPy ``solve_ivp``)
   for plasma/tissue exposure, coupled to a receptor-occupancy model driven by the
   docked ``Kd`` → ``cmax``, ``auc``, ``target_occupancy_pct``.

The heavy dependencies (``rdkit``, ``meeko``, ``vina``, ``scipy``, ``numpy``,
``openbabel``) are imported **lazily inside the functions that need them** so this
module imports cleanly in the web service and the test suite, which never run the
physics — they fake Devin. Those deps live in ``requirements-sim.txt`` and are
installed by Devin, not by the Flask service.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from typing import Any

import requests

# Gas constant in kcal/(mol·K); body temperature in Kelvin (37 °C).
_R_KCAL = 1.987204259e-3
_BODY_TEMP_K = 310.15

_HTTP_TIMEOUT = 30


def _log(msg: str) -> None:
    """Human-readable progress goes to stderr; stdout is reserved for the result."""
    print(f"[sim] {msg}", file=sys.stderr, flush=True)


@dataclass
class SimResult:
    """Structured output of one simulation run (serialised to SIM_RESULT_JSON)."""

    target: str
    drug: str
    tissue: str
    dose_mg: float
    binding_affinity_kcal_mol: float | None = None
    kd_nM: float | None = None
    cmax_ng_ml: float | None = None
    auc_ng_h_ml: float | None = None
    target_occupancy_pct: float | None = None
    tox_flag: bool | None = None
    confidence: float | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Step 1 — target → UniProt accession
# --------------------------------------------------------------------------- #
def resolve_uniprot(target: str, uniprot_hint: str | None = None) -> str:
    """Resolve a gene/protein name (or accession) to a human UniProt accession."""
    if uniprot_hint:
        return uniprot_hint
    # A 6/10-char accession pattern — accept it directly.
    if len(target) in (6, 10) and target[0].isalpha() and target[1:].isalnum():
        return target.upper()

    url = "https://rest.uniprot.org/uniprotkb/search"
    params = {
        "query": f"(gene:{target} OR protein_name:{target}) AND organism_id:9606 "
        "AND reviewed:true",
        "format": "json",
        "size": "1",
        "fields": "accession",
    }
    resp = requests.get(url, params=params, timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        raise RuntimeError(f"no reviewed human UniProt entry for target '{target}'")
    return results[0]["primaryAccession"]


# --------------------------------------------------------------------------- #
# Step 2 — UniProt → structure (experimental PDB, else AlphaFold model)
# --------------------------------------------------------------------------- #
def fetch_structure(uniprot: str, workdir: str) -> tuple[str, dict[str, Any]]:
    """Download a structure for ``uniprot``; return (pdb_path, provenance)."""
    # Prefer an experimental structure ranked by PDBe/SIFTS "best_structures".
    try:
        url = f"https://www.ebi.ac.uk/pdbe/api/mappings/best_structures/{uniprot}"
        resp = requests.get(url, timeout=_HTTP_TIMEOUT)
        if resp.ok and resp.json().get(uniprot):
            pdb_id = resp.json()[uniprot][0]["pdb_id"].upper()
            pdb_path = os.path.join(workdir, f"{pdb_id}.pdb")
            _download(f"https://files.rcsb.org/download/{pdb_id}.pdb", pdb_path)
            _log(f"using experimental structure {pdb_id}")
            return pdb_path, {"structure_source": "RCSB", "pdb_id": pdb_id}
    except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
        _log(f"experimental structure lookup failed ({exc}); trying AlphaFold")

    # Fall back to the AlphaFold DB predicted model.
    af_path = os.path.join(workdir, f"AF-{uniprot}.pdb")
    _download(
        f"https://alphafold.ebi.ac.uk/files/AF-{uniprot}-F1-model_v4.pdb", af_path
    )
    _log(f"using AlphaFold model AF-{uniprot}-F1")
    return af_path, {"structure_source": "AlphaFold", "pdb_id": f"AF-{uniprot}-F1"}


def _download(url: str, dest: str) -> None:
    resp = requests.get(url, timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    with open(dest, "wb") as fh:
        fh.write(resp.content)


# --------------------------------------------------------------------------- #
# Step 3 — drug → SMILES → RDKit 3D molecule
# --------------------------------------------------------------------------- #
def fetch_ligand_smiles(drug: str) -> str:
    """Look up a canonical SMILES for ``drug`` via PubChem PUG-REST."""
    url = (
        "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
        f"{requests.utils.quote(drug)}/property/CanonicalSMILES/JSON"
    )
    resp = requests.get(url, timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    props = resp.json()["PropertyTable"]["Properties"]
    if not props or "CanonicalSMILES" not in props[0]:
        raise RuntimeError(f"no SMILES found for drug '{drug}'")
    return props[0]["CanonicalSMILES"]


def embed_ligand(smiles: str):
    """SMILES → RDKit Mol with hydrogens and an embedded, MMFF-optimised 3D pose."""
    from rdkit import Chem  # lazy
    from rdkit.Chem import AllChem

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise RuntimeError(f"RDKit could not parse SMILES: {smiles}")
    mol = Chem.AddHs(mol)
    if AllChem.EmbedMolecule(mol, randomSeed=0xC0FFEE) != 0:
        raise RuntimeError("RDKit 3D embedding failed")
    AllChem.MMFFOptimizeMolecule(mol)
    return mol


def ligand_descriptors(mol) -> dict[str, float]:
    """Physicochemical descriptors used for the crude tox / drug-likeness signal."""
    from rdkit.Chem import Crippen, Descriptors, Lipinski

    return {
        "mw": Descriptors.MolWt(mol),
        "logp": Crippen.MolLogP(mol),
        "hbd": Lipinski.NumHDonors(mol),
        "hba": Lipinski.NumHAcceptors(mol),
        "tpsa": Descriptors.TPSA(mol),
    }


# --------------------------------------------------------------------------- #
# Step 4 — PDBQT preparation
# --------------------------------------------------------------------------- #
def prepare_ligand_pdbqt(mol, workdir: str) -> str:
    """Write the embedded ligand to PDBQT (Meeko preferred, OpenBabel fallback)."""
    out = os.path.join(workdir, "ligand.pdbqt")
    try:
        from meeko import MoleculePreparation, PDBQTWriterLegacy  # lazy

        prep = MoleculePreparation()
        setups = prep.prepare(mol)
        pdbqt_string = PDBQTWriterLegacy.write_string(setups[0])[0]
        with open(out, "w") as fh:
            fh.write(pdbqt_string)
        return out
    except Exception as exc:  # noqa: BLE001 — Meeko API varies across versions
        _log(f"Meeko ligand prep failed ({exc}); using OpenBabel")
        from rdkit import Chem

        pdb = os.path.join(workdir, "ligand.pdb")
        Chem.MolToPDBFile(mol, pdb)
        _obabel(pdb, out, extra=["--partialcharge", "gasteiger"])
        return out


def prepare_receptor_pdbqt(pdb_path: str, workdir: str) -> str:
    """Clean the receptor (drop waters/hetero atoms) and convert to rigid PDBQT."""
    clean = os.path.join(workdir, "receptor_clean.pdb")
    with open(pdb_path) as src, open(clean, "w") as dst:
        for line in src:
            if line.startswith("ENDMDL"):  # keep only the first model
                break
            if line.startswith("ATOM"):
                dst.write(line)
    out = os.path.join(workdir, "receptor.pdbqt")
    # -xr => rigid receptor; add hydrogens and Gasteiger charges.
    _obabel(clean, out, extra=["-xr", "-p", "7.4", "--partialcharge", "gasteiger"])
    return out


def _obabel(src: str, dst: str, extra: list[str] | None = None) -> None:
    """Convert ``src`` → ``dst`` with OpenBabel's Python API (pybel)."""
    from openbabel import pybel  # lazy

    in_fmt = os.path.splitext(src)[1].lstrip(".")
    out_fmt = os.path.splitext(dst)[1].lstrip(".")
    mol = next(pybel.readfile(in_fmt, src))
    mol.addh()
    mol.write(out_fmt, dst, overwrite=True, opt={"r": None} if "-xr" in (extra or []) else {})


# --------------------------------------------------------------------------- #
# Step 5 — docking
# --------------------------------------------------------------------------- #
def compute_docking_box(pdb_path: str) -> tuple[list[float], list[float]]:
    """Blind-docking box: receptor centroid + padded bounding box (capped)."""
    import numpy as np  # lazy

    coords = []
    with open(pdb_path) as fh:
        for line in fh:
            if line.startswith(("ATOM", "HETATM")):
                coords.append(
                    (float(line[30:38]), float(line[38:46]), float(line[46:54]))
                )
            elif line.startswith("ENDMDL"):
                break
    if not coords:
        raise RuntimeError("no atom coordinates found for docking box")
    arr = np.array(coords)
    center = arr.mean(axis=0)
    extent = arr.max(axis=0) - arr.min(axis=0) + 8.0  # 8 Å padding
    size = np.minimum(extent, 40.0)  # cap for tractable blind docking
    return center.tolist(), size.tolist()


def run_vina(receptor_pdbqt: str, ligand_pdbqt: str, box) -> float:
    """Dock and return the best pose's binding free energy ΔG (kcal/mol)."""
    from vina import Vina  # lazy

    center, size = box
    v = Vina(sf_name="vina", cpu=os.cpu_count() or 1, seed=0)
    v.set_receptor(receptor_pdbqt)
    v.set_ligand_from_file(ligand_pdbqt)
    v.compute_vina_maps(center=center, box_size=size)
    v.dock(exhaustiveness=8, n_poses=5)
    return float(v.energies(n_poses=1)[0][0])


def kd_from_dg(dg_kcal_mol: float) -> float:
    """Convert ΔG (kcal/mol) to a dissociation constant Kd in **nanomolar**.

    ΔG = R·T·ln(Kd)  ⇒  Kd = exp(ΔG / (R·T)).  (Molar → nM via ×1e9.)
    """
    kd_molar = math.exp(dg_kcal_mol / (_R_KCAL * _BODY_TEMP_K))
    return kd_molar * 1e9


# --------------------------------------------------------------------------- #
# Step 6 — PK/PD (one-compartment, first-order absorption) + occupancy
# --------------------------------------------------------------------------- #
# Physiologically plausible PK defaults for a small-molecule oral drug. Shared by
# run_pkpd (scalar summary) and pkpd_curve (time series for the dashboard) so the two
# can never disagree.
_PK_KA = 1.0   # 1/h  first-order absorption
_PK_VD = 50.0  # L    apparent volume of distribution
_PK_CL = 10.0  # L/h  clearance


def run_pkpd(
    *, dose_mg: float, mol_weight: float, kd_nM: float, tissue: str
) -> dict[str, float]:
    """Summarise exposure + occupancy for a 1-compartment first-order-absorption model.

    The model has a closed-form (Bateman) solution, so no ODE solver is needed:
        C(t) = F·Dose·ka / (Vd·(ka−ke)) · (e^{−ke·t} − e^{−ka·t})   [µg/mL]
    A tissue partition coefficient Kp scales the concentration reaching the target,
    and occupancy uses the docked Kd:  occ(t) = C_nM / (C_nM + Kd).
    """
    s = _pkpd_series(dose_mg=dose_mg, mol_weight=mol_weight, kd_nM=kd_nM, tissue=tissue)
    return {
        "cmax_ng_ml": max(s["conc_ng_ml"]),
        "auc_ng_h_ml": _trapz(s["t_h"], s["conc_ng_ml"]),
        "target_occupancy_pct": max(s["occupancy_pct"]),
    }


def _pkpd_series(
    *, dose_mg: float, mol_weight: float, kd_nM: float, tissue: str,
    t_end: float = 48.0, n: int = 97,
) -> dict[str, list[float]]:
    """Evaluate the Bateman exposure curve + occupancy on a time grid (stdlib only)."""
    ka, vd, ke = _PK_KA, _PK_VD, _PK_CL / _PK_VD
    kp = _TISSUE_PARTITION.get((tissue or "plasma").lower(), 1.0)  # tissue:plasma ratio
    coef = dose_mg * ka / (vd * (ka - ke))  # µg/mL scale (ka != ke by construction)

    t_h, conc_ng_ml, occ_pct = [], [], []
    for i in range(n):
        t = t_end * i / (n - 1)
        c_plasma = coef * (math.exp(-ke * t) - math.exp(-ka * t))  # µg/mL
        c_tissue = max(c_plasma, 0.0) * kp
        c_nM = (c_tissue / mol_weight) * 1e6
        t_h.append(round(t, 3))
        conc_ng_ml.append(round(c_tissue * 1000.0, 4))  # µg/mL → ng/mL
        occ_pct.append(round(100.0 * c_nM / (c_nM + kd_nM), 3))
    return {"t_h": t_h, "conc_ng_ml": conc_ng_ml, "occupancy_pct": occ_pct}


def _trapz(xs: list[float], ys: list[float]) -> float:
    """Trapezoidal integral of ys over xs (stdlib)."""
    return sum(
        (xs[i + 1] - xs[i]) * (ys[i + 1] + ys[i]) / 2.0 for i in range(len(xs) - 1)
    )


def pkpd_curve(sim_result: dict[str, Any], t_end: float = 48.0, n: int = 97):
    """Reconstruct the PK/PD exposure curve for a stored run (for the dashboard).

    Pulls dose / MW / Kd / tissue out of a persisted ``sim_result`` and re-evaluates
    the same Bateman model. Returns ``None`` when a required field is missing.
    """
    kd = sim_result.get("kd_nM")
    dose = sim_result.get("dose_mg")
    mw = ((sim_result.get("provenance") or {}).get("descriptors") or {}).get("mw")
    if not kd or not dose or not mw:
        return None
    return _pkpd_series(
        dose_mg=dose, mol_weight=mw, kd_nM=kd,
        tissue=sim_result.get("tissue") or "plasma", t_end=t_end, n=n,
    )


# Rough tissue:plasma partition coefficients (Kp). Real QSP models fit these; the
# values here are order-of-magnitude literature ranges sufficient for a directional
# exposure signal.
_TISSUE_PARTITION = {
    "hepatic": 3.0,
    "liver": 3.0,
    "renal": 2.0,
    "kidney": 2.0,
    "cns": 0.3,
    "brain": 0.3,
    "cardiac": 1.2,
    "heart": 1.2,
    "muscle": 0.8,
    "adipose": 5.0,
    "lung": 2.5,
    "tumor": 1.5,
}


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run_simulation(
    *,
    target: str,
    drug: str,
    tissue: str = "plasma",
    dose_mg: float = 100.0,
    uniprot: str | None = None,
) -> SimResult:
    """Run the full docking + PK/PD pipeline and return a :class:`SimResult`."""
    result = SimResult(target=target, drug=drug, tissue=tissue, dose_mg=dose_mg)
    try:
        with tempfile.TemporaryDirectory() as workdir:
            accession = resolve_uniprot(target, uniprot)
            result.provenance["uniprot"] = accession

            pdb_path, prov = fetch_structure(accession, workdir)
            result.provenance.update(prov)

            smiles = fetch_ligand_smiles(drug)
            result.provenance["smiles"] = smiles
            mol = embed_ligand(smiles)
            desc = ligand_descriptors(mol)
            result.provenance["descriptors"] = {k: round(v, 3) for k, v in desc.items()}

            ligand_pdbqt = prepare_ligand_pdbqt(mol, workdir)
            receptor_pdbqt = prepare_receptor_pdbqt(pdb_path, workdir)
            box = compute_docking_box(pdb_path)

            dg = run_vina(receptor_pdbqt, ligand_pdbqt, box)
            result.binding_affinity_kcal_mol = round(dg, 3)
            result.kd_nM = round(kd_from_dg(dg), 3)
            _log(f"ΔG = {dg:.2f} kcal/mol  →  Kd = {result.kd_nM:.1f} nM")

            pkpd = run_pkpd(
                dose_mg=dose_mg, mol_weight=desc["mw"], kd_nM=result.kd_nM, tissue=tissue
            )
            result.cmax_ng_ml = round(pkpd["cmax_ng_ml"], 3)
            result.auc_ng_h_ml = round(pkpd["auc_ng_h_ml"], 3)
            result.target_occupancy_pct = round(pkpd["target_occupancy_pct"], 2)

            # Crude drug-likeness/tox signal: ≥2 Lipinski violations flags risk.
            violations = sum(
                [desc["mw"] > 500, desc["logp"] > 5, desc["hbd"] > 5, desc["hba"] > 10]
            )
            result.tox_flag = violations >= 2

            # Confidence: experimental structure > predicted; full run > fallbacks.
            base = 0.9 if prov["structure_source"] == "RCSB" else 0.7
            result.confidence = round(max(0.3, base - 0.05 * len(result.warnings)), 3)
    except Exception as exc:  # noqa: BLE001 — surface any pipeline failure as data
        result.error = f"{type(exc).__name__}: {exc}"
        _log(f"simulation failed: {result.error}")
    return result


# Marker the service's devin_client scans for in the session transcript.
RESULT_MARKER = "SIM_RESULT_JSON:"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Target protein / gene name")
    parser.add_argument("--drug", required=True, help="Drug / compound name")
    parser.add_argument("--tissue", default="plasma", help="Tissue of interest")
    parser.add_argument("--dose", type=float, default=100.0, help="Dose in mg")
    parser.add_argument("--uniprot", default=None, help="UniProt accession (skips lookup)")
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Print only the SIM_RESULT_JSON line on stdout",
    )
    args = parser.parse_args(argv)

    result = run_simulation(
        target=args.target,
        drug=args.drug,
        tissue=args.tissue,
        dose_mg=args.dose,
        uniprot=args.uniprot,
    )
    # The service parses this exact line out of the Devin session transcript.
    print(f"{RESULT_MARKER} {json.dumps(result.to_dict())}")
    return 0 if result.error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())

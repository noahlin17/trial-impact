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
   dissociation constant ``Kd`` from ΔG = RT·ln(Kd). Only the scalar ΔG comes back —
   the pose is too large for the result contract (see the README).
6. **PK/PD** — a first-order-absorption one-compartment model solved in **closed form**
   (Bateman), coupled to a receptor-occupancy model driven by the docked ``Kd`` →
   ``cmax``, ``auc``, ``target_occupancy_pct``. No ODE solver (and so no SciPy) needed.

The heavy dependencies (``rdkit``, ``meeko``, ``vina``, ``numpy``,
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
    covalent_flag: bool | None = None
    confidence: float | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    docking_box: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    # Set by the *session*, not by this code: true if the agent had to modify this
    # script to get the run to complete. A patched run's numbers did not come from the
    # code in this repo, so it is not reproducible from source and must say so — see
    # "Result contract" in the README. Silent divergence has bitten us twice (a
    # PubChem schema change and an mmCIF-only structure), which is why it is a field
    # and not a convention.
    code_patched: bool = False
    patch_summary: str | None = None

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
    _download(_alphafold_pdb_url(uniprot), af_path)
    _log(f"using AlphaFold model AF-{uniprot}-F1")
    return af_path, {"structure_source": "AlphaFold", "pdb_id": f"AF-{uniprot}-F1"}


# AlphaFold DB stamps a model version into the filename (…-F1-model_v6.pdb) and bumps
# it over time. Hardcoding one silently 404s for *every* target the day AFDB rolls
# forward — which is exactly what happened: the pinned `v4` URL broke the entire
# fallback, so any target without a legacy experimental .pdb failed outright instead
# of degrading to a predicted model. Resolve the version instead of assuming it.
_AF_API = "https://alphafold.ebi.ac.uk/api/prediction"
_AF_KNOWN_VERSIONS = ("v6", "v5", "v4")


def _alphafold_pdb_url(uniprot: str) -> str:
    """Current AlphaFold DB .pdb URL for ``uniprot`` (API first, then known versions)."""
    try:
        resp = requests.get(f"{_AF_API}/{uniprot}", timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
        entries = resp.json()
        if entries and entries[0].get("pdbUrl"):
            return entries[0]["pdbUrl"]
    except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
        _log(f"AlphaFold API lookup failed ({exc}); probing known model versions")

    for version in _AF_KNOWN_VERSIONS:  # newest first
        url = f"https://alphafold.ebi.ac.uk/files/AF-{uniprot}-F1-model_{version}.pdb"
        try:
            if requests.head(url, timeout=_HTTP_TIMEOUT, allow_redirects=True).ok:
                return url
        except requests.RequestException:
            continue
    raise RuntimeError(f"no AlphaFold model available for {uniprot}")


def _download(url: str, dest: str) -> None:
    resp = requests.get(url, timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    with open(dest, "wb") as fh:
        fh.write(resp.content)


# --------------------------------------------------------------------------- #
# Step 3 — drug → SMILES → RDKit 3D molecule
# --------------------------------------------------------------------------- #
# PubChem's PUG-REST property schema drifted: a request for `CanonicalSMILES` now comes
# back keyed as `ConnectivitySMILES`, so the old lookup raised "no SMILES found" for
# *every* drug — the pipeline could not fetch a ligand at all. Request `SMILES` (the
# isomeric form, which keeps stereochemistry — e.g. sotorasib's chiral centre; the
# connectivity form would silently drop it and change the docked geometry) and accept
# whichever SMILES-bearing key comes back, so the lookup survives either schema.
_SMILES_KEYS = ("SMILES", "IsomericSMILES", "CanonicalSMILES", "ConnectivitySMILES")


def fetch_ligand_smiles(drug: str) -> str:
    """Look up a SMILES string for ``drug`` via PubChem PUG-REST."""
    url = (
        "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
        f"{requests.utils.quote(drug)}/property/SMILES/JSON"
    )
    resp = requests.get(url, timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    props = resp.json().get("PropertyTable", {}).get("Properties", [])
    if props:
        for key in _SMILES_KEYS:
            if props[0].get(key):
                return props[0][key]
    raise RuntimeError(f"no SMILES found for drug '{drug}'")


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


# SMARTS for common covalent-inhibitor warheads. This is a heuristic *flag* only:
# Vina still scores such ligands reversibly, so it under-represents their potency.
#
# The Michael-acceptor patterns require an **acyclic** C=C (`;!R`). A real warhead is an
# exocyclic vinyl (an acrylamide, `N-C(=O)-CH=CH2`); an α,β-unsaturated amide *inside* a
# ring is just a conjugated heterocycle and is not electrophilic in the same way. Without
# `;!R` this flagged **ivacaftor** — a reversible CFTR potentiator — as covalent, because
# `embed_ligand` kekulizes its 4-oxoquinoline ring and the ring's C=C then matched a bare
# `C=CC(=O)N`. Validated against 4 known covalent drugs (sotorasib, osimertinib,
# ibrutinib, afatinib) and 4 reversible ones (ivacaftor, ibuprofen, imatinib,
# atorvastatin) — see tests.
_COVALENT_WARHEADS = (
    "[CX3;!R]=[CX3;!R][CX3](=O)[NX3,OX2]",  # acrylamide / acrylate (Michael acceptor)
    "[Cl,Br,I]-[CH2]-[CX3](=O)[NX3]",       # halo-acetamide
    "[CX3;!R]=[CX3;!R][SX4](=O)(=O)",       # vinyl sulfone / sulfonamide
    "B([OX2])[OX2]",                        # boronic acid / ester
    "C1OC1",                                # epoxide
)


def detect_covalent(mol) -> bool:
    """True if the ligand contains a recognised covalent warhead (heuristic)."""
    from rdkit import Chem

    for smarts in _COVALENT_WARHEADS:
        patt = Chem.MolFromSmarts(smarts)
        if patt is not None and mol.HasSubstructMatch(patt):
            return True
    return False


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
    """A centroid-centered box, padded 8 Å and capped at 40 Å (center + size, in Å).

    Blind: we do not know which pocket the drug binds. Centering on the largest
    co-crystal ligand was tried and reverted (KRAS 7VVB carries only the nucleotide
    GNP, so it boxed the wrong pocket).

    KNOWN ISSUE — the 40 Å cap keeps the volume tractable for Vina, but the box stays
    on the centroid, so on a receptor larger than ~40 Å this searches a central slab,
    not the protein. Measured (`python verify_docking_box.py`): KRAS 7VVB (56x55x44 Å)
    ~80% of atoms in the box; CFTR AF-P13569-F1 (139x117x147 Å) ~19%. "Blind" is not
    "exhaustive" — on a large target this silently docks an arbitrary sub-volume. A fix
    needs pocket detection (fpocket / P2Rank) or a drug-bound structure pinned per
    trial. See "Docking box" under Limitations in the README.
    """
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
    if float(extent.max()) > 40.0:
        _log(
            "WARNING: receptor is larger than the 40 A box cap - docking a central "
            "slab, not the whole receptor (see compute_docking_box)"
        )
    _log("using blind docking box (centroid-centered, 40 A cap)")
    return center.tolist(), size.tolist()


# Vina treats seed=0 as "pick a random seed", so the previous `seed=0` made every run
# non-deterministic — repeat runs of the same drug/target drifted (ΔG -8.42 / -8.59 /
# -8.59 for sotorasib/KRAS). A fixed non-zero seed makes a run reproducible, which the
# whole result contract depends on: you cannot call a number reproducible-from-source
# if the source rolls a new seed each time.
_VINA_SEED = 42


def run_vina(receptor_pdbqt: str, ligand_pdbqt: str, box) -> float:
    """Dock and return the best pose's binding free energy ΔG (kcal/mol).

    Only the scalar ΔG is returned. The top pose is *not* transported back: it is ~8 KB
    of PDB text, and embedding it in the single-line SIM_RESULT_JSON contract made the
    agent truncate that line — silently turning a good run into an unparseable one. See
    "Docked pose" under Limitations in the README.
    """
    from vina import Vina  # lazy

    center, size = box
    v = Vina(sf_name="vina", cpu=os.cpu_count() or 1, seed=_VINA_SEED)
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

            # Covalent-warhead flag (heuristic; non-fatal). Vina scores reversibly,
            # so a covalent binder's ΔG under-represents its true potency.
            try:
                result.covalent_flag = detect_covalent(mol)
            except Exception as exc:  # noqa: BLE001 — flag is best-effort
                result.warnings.append(f"covalent detection skipped: {exc}")

            ligand_pdbqt = prepare_ligand_pdbqt(mol, workdir)
            receptor_pdbqt = prepare_receptor_pdbqt(pdb_path, workdir)
            box = compute_docking_box(pdb_path)
            # Record the box as provenance so a reader can see exactly what volume was
            # searched (and that it was a blind box, not a pocket-focused one).
            result.docking_box = {
                "center": [round(c, 3) for c in box[0]],
                "size": [round(s, 3) for s in box[1]],
                "mode": "blind",
            }

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

"""Binding-site selection — route each ``(target, drug)`` to the most accurate box.

The blind centroid box (:func:`app.simulation.compute_docking_box`) searches only a
central slab of a large receptor (~19-26% of CFTR), so its ΔG on a big target reflects an
arbitrary sub-volume, not the binding site. Enlarging the box does not fix this — an
uncapped CFTR box is ~2.4 M Å³, past where Vina's sampling means anything. This module
instead picks the box by **chemistry and target class**, and records which tier it used in
``docking_box["mode"]`` so every result declares how its pocket was chosen:

  ``covalent-tethered``  a covalent warhead + a curated covalent target class: the free
      drug is tethered to the class's reactive cysteine (auto-detected from the curated
      drug-bound holo structure) and docked in a box centred on that residue. Once the
      curated holo + reactive residue resolve, the router **commits to that structure**: if
      only the tether *preparation* fails (e.g. Meeko missing in an environment), it degrades
      to ``covalent-residue`` on the *same* structure/box rather than re-resolving a
      different PDB, so a toolchain hiccup never silently changes the structure or its ΔG.
  ``covalent-residue``   the curated covalent holo resolved but the warhead is not tetherable
      (or tether prep failed): reversible docking in the reactive-residue box of that same
      curated structure (recorded, and its ``ligand_pdbqt`` is ``None``).
  ``holo (curated)``     a curated drug-bound structure for the target class: box on the
      co-crystallised ligand.
  ``holo (discovered)``  no curated entry, but a PDB of this target co-crystallises this
      drug (matched by chemical graph via the RCSB search API): box on that ligand. Among
      the drug-bound hits the router picks the one that best resolves the pocket (sharpest
      experimental method, then best resolution, then a deterministic id tiebreak), so the
      choice is both reproducible and scientifically principled.
  ``fpocket``            no co-crystal: the top geometric pocket from fpocket. Geometry
      ranks pockets, not biology — it can miss the real site (fpocket's top CFTR pocket is
      ~79 Å from the ivacaftor site), so this is a **caveated** fallback.
  ``blind``              last resort: the legacy centroid box (unchanged), so any target
      that used to run still runs.

The routing is **generalizable, not per-drug**: reversible drugs with any co-crystal are
found automatically (Tier B), and covalent drugs route by *target class* (a curated
reactive-residue map), so a net-new inhibitor of a mapped class routes itself.

Honesty limits (documented in the README):
  * A curated/discovered holo box is derived from a *bound* ligand, so re-docking a ligand
    into its own co-crystal pocket is partly cognate/circular and flatters accuracy.
  * Covalent tethered docking fixes the *pocket* and covalent *pose*, but Vina still
    scores non-covalently — the covalent bond energy is not added, so covalent potency
    remains a reversible-scoring estimate (now pocket-correct rather than blind).
  * A covalent co-crystal's ligand is the reacted *adduct*, chemically ≠ the free drug, so
    covalent classes cannot be auto-discovered by graph match; they are curated.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

import requests

from .simulation import (
    _HTTP_TIMEOUT,
    _fetch_experimental_pdb,
    _log,
    compute_docking_box,
    fetch_structure,
    structure_checksum,
)

# Covalent-bond distance: a Cys Sγ within this of a bound hetero atom *is* the covalent
# linkage in a holo structure (validated: 1.8-1.9 Å for sotorasib/afatinib/ibrutinib).
_COVALENT_BOND_MAX_A = 2.5
# Box centred on a reactive residue: large enough to sample the pocket, small enough that
# Vina's search stays meaningful.
_RESIDUE_BOX_A = 22.0
# Co-crystal ligand box padding / per-dimension cap (Å).
_LIGAND_BOX_PAD_A = 8.0
_LIGAND_BOX_CAP_A = 30.0

_RCSB_SEARCH = "https://search.rcsb.org/rcsbsearch/v2/query"
_RCSB_ENTRY = "https://data.rcsb.org/rest/v1/core/entry/"

# How faithfully a method resolves a small-molecule pocket, best first. High-resolution
# X-ray gives the sharpest side-chain/ligand coordinates that define a docking box; cryo-EM
# is usually lower-resolution for small molecules; a solution-NMR ensemble has no single
# well-defined pocket. This orders *which drug-bound structure best represents the geometry
# binding actually occurs in* — not an arbitrary id order.
_METHOD_RANK: dict[str, int] = {
    "X-RAY DIFFRACTION": 0,
    "ELECTRON MICROSCOPY": 1,
    "ELECTRON CRYSTALLOGRAPHY": 1,
    "SOLUTION NMR": 2,
    "SOLID-STATE NMR": 2,
}


# --------------------------------------------------------------------------- #
# Target-class registry — keyed by gene/target symbol (a *class*, never a drug)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TargetClass:
    """A curated target class: a drug-bound structure + whether the site is covalent.

    ``covalent`` classes carry a curated open-pocket holo whose bound inhibitor pins the
    reactive cysteine (auto-detected from the structure — no residue number is hardcoded).
    Reversible classes carry the co-crystal ``holo_ligand`` code used to place the box.
    """

    label: str
    holo_pdb: str
    holo_ligand: str | None = None
    covalent: bool = False


# The curated "high-accuracy universe". Each entry is a target *class*; adding a class is a
# one-line registry change, not new code. Every holo below is a real, experimental,
# drug-bound structure verified to pin its site (covalent Sγ distances 1.8-1.9 Å).
_TARGET_CLASSES: dict[str, TargetClass] = {
    "KRAS": TargetClass("KRAS G12C (covalent, switch-II pocket)", "6OIM", covalent=True),
    "EGFR": TargetClass("EGFR (covalent, Cys797)", "4G5J", covalent=True),
    "BTK": TargetClass("BTK (covalent, Cys481)", "5P9J", covalent=True),
    "CFTR": TargetClass("CFTR potentiator site", "6O2P", holo_ligand="VX7"),
}

# Tetherable covalent warheads: (family, detection SMARTS, tether SMARTS, tether indices).
# The tether SMARTS names the two ligand atoms overlaid onto the reactive residue's CA/CB
# by Meeko's CovalentBuilder; only Michael-acceptor (acrylamide-type) warheads are
# configured today — they cover the marketed covalent oncology drugs (sotorasib, afatinib,
# ibrutinib, osimertinib). Other warheads (boronates, epoxides) are flagged but dock
# reversibly until a tether geometry is curated for them.
_TETHERABLE_WARHEADS = (
    ("acrylamide/Michael acceptor", "[CX3;!R]=[CX3;!R][CX3](=O)[NX3]", "C=CC(=O)N", (1, 2)),
)


def resolve_target_class(target: str) -> TargetClass | None:
    """Match a trial's target name to a curated :class:`TargetClass` (by gene symbol)."""
    tokens = {t for t in (target or "").upper().replace("-", " ").split()}
    tokens.add((target or "").upper())
    for key, entry in _TARGET_CLASSES.items():
        if key in tokens:
            return entry
    return None


def covalent_tether(mol) -> tuple[str, str, tuple[int, int]] | None:
    """Return (family, tether_smarts, indices) if ``mol`` bears a tetherable warhead."""
    from rdkit import Chem

    for family, detect, tether_smarts, indices in _TETHERABLE_WARHEADS:
        patt = Chem.MolFromSmarts(detect)
        if patt is not None and mol.HasSubstructMatch(patt):
            return family, tether_smarts, indices
    return None


# --------------------------------------------------------------------------- #
# Geometry helpers (pure PDB parsing)
# --------------------------------------------------------------------------- #
def _first_model_atoms(pdb_path: str):
    """Yield (record, chain, resnum, resname, atom_name, x, y, z) for the first model."""
    with open(pdb_path) as fh:
        for ln in fh:
            if ln.startswith("ENDMDL"):
                break
            if ln.startswith(("ATOM", "HETATM")):
                try:
                    yield (
                        ln[:6].strip(), ln[21], int(ln[22:26]), ln[17:20].strip(),
                        ln[12:16].strip(),
                        float(ln[30:38]), float(ln[38:46]), float(ln[46:54]),
                    )
                except ValueError:
                    continue


def detect_reactive_cys(pdb_path: str) -> tuple[str, int] | None:
    """The cysteine whose Sγ sits within covalent-bond distance of a bound hetero atom.

    This *is* the covalent linkage in a drug-bound holo structure, so it identifies the
    reactive residue directly from geometry — no residue number is hardcoded, which is why
    the covalent route generalises to any curated covalent class.
    """
    import numpy as np

    sg: dict[tuple[str, int], Any] = {}
    het = []
    for rec, chain, num, resname, atom, x, y, z in _first_model_atoms(pdb_path):
        if rec == "ATOM" and resname == "CYS" and atom == "SG":
            sg[(chain, num)] = np.array([x, y, z])
        elif rec == "HETATM" and resname not in ("HOH", "WAT"):
            het.append([x, y, z])
    if not sg or not het:
        return None
    het_arr = np.array(het)
    best = min(sg, key=lambda k: float(np.linalg.norm(het_arr - sg[k], axis=1).min()))
    dist = float(np.linalg.norm(het_arr - sg[best], axis=1).min())
    if dist > _COVALENT_BOND_MAX_A:
        return None
    _log(f"reactive cysteine {best[0]}:{best[1]} (Sγ {dist:.2f} Å from bound ligand)")
    return best


def residue_box(pdb_path: str, chain: str, resnum: int) -> tuple[list[float], list[float]]:
    """A cubic box centred on the residue's CB (CA if CB is absent, e.g. glycine)."""
    cb = ca = None
    for rec, ch, num, _resname, atom, x, y, z in _first_model_atoms(pdb_path):
        if rec == "ATOM" and ch == chain and num == resnum:
            if atom == "CB":
                cb = [x, y, z]
            elif atom == "CA":
                ca = [x, y, z]
    center = cb or ca
    if center is None:
        raise RuntimeError(f"residue {chain}:{resnum} not found for box center")
    return [round(c, 3) for c in center], [_RESIDUE_BOX_A] * 3


def ligand_box(pdb_path: str, ligand_codes) -> tuple[list[float], list[float], str]:
    """Box on the first ``ligand_codes`` entry present as HETATM; returns (center, size, code)."""
    import numpy as np

    if isinstance(ligand_codes, str):
        ligand_codes = [ligand_codes]
    coords_by_code: dict[str, list] = {}
    for rec, _ch, _num, resname, _atom, x, y, z in _first_model_atoms(pdb_path):
        if rec == "HETATM" and resname in ligand_codes:
            coords_by_code.setdefault(resname, []).append([x, y, z])
    for code in ligand_codes:
        if coords_by_code.get(code):
            a = np.array(coords_by_code[code])
            center = a.mean(axis=0)
            size = np.minimum(a.max(axis=0) - a.min(axis=0) + _LIGAND_BOX_PAD_A, _LIGAND_BOX_CAP_A)
            return (
                [round(c, 3) for c in center.tolist()],
                [round(s, 3) for s in size.tolist()],
                code,
            )
    raise RuntimeError(f"none of ligands {ligand_codes} found in {os.path.basename(pdb_path)}")


# --------------------------------------------------------------------------- #
# fpocket (Tier C) — geometric pocket detection
# --------------------------------------------------------------------------- #
def _write_clean_receptor(pdb_path: str, dest: str) -> str:
    """Protein ATOM records of the first model only (drop waters/hetero/ligands)."""
    with open(pdb_path) as src, open(dest, "w") as out:
        for ln in src:
            if ln.startswith("ENDMDL"):
                break
            if ln.startswith(("ATOM", "TER")):
                out.write(ln)
    return dest


def fpocket_box(pdb_path: str, workdir: str) -> tuple[list[float], list[float]] | None:
    """Box on fpocket's top-ranked pocket, or ``None`` if fpocket is unavailable/empty.

    Geometric only: fpocket ranks pockets by druggability score, which does not establish
    biological relevance — hence a caveated fallback, not a preferred tier.
    """
    if not shutil.which("fpocket"):
        _log("fpocket not on PATH; skipping geometric-pocket tier")
        return None
    import numpy as np

    clean = _write_clean_receptor(pdb_path, os.path.join(workdir, "fpocket_in.pdb"))
    proc = subprocess.run(["fpocket", "-f", clean], capture_output=True, text=True)
    if proc.returncode != 0:
        _log(f"fpocket failed (rc={proc.returncode}); skipping")
        return None
    pqr = os.path.join(clean[:-4] + "_out", "pockets", "pocket1_vert.pqr")
    if not os.path.exists(pqr):
        _log("fpocket produced no pocket1; skipping")
        return None
    verts = [
        [float(ln[30:38]), float(ln[38:46]), float(ln[46:54])]
        for ln in open(pqr)
        if ln.startswith(("ATOM", "HETATM"))
    ]
    if not verts:
        return None
    a = np.array(verts)
    center = a.mean(axis=0)
    size = np.minimum(a.max(axis=0) - a.min(axis=0) + _LIGAND_BOX_PAD_A, _LIGAND_BOX_CAP_A)
    _log("using fpocket top pocket (geometric ranking, not proven biological site)")
    return [round(c, 3) for c in center.tolist()], [round(s, 3) for s in size.tolist()]


# --------------------------------------------------------------------------- #
# Tier B — auto-discover a holo (drug-bound) structure for a reversible drug
# --------------------------------------------------------------------------- #
def discover_holo(uniprot: str, smiles: str) -> tuple[str, list[str]] | None:
    """Find a PDB of ``uniprot`` co-crystallising the drug; return (pdb_id, ligand_codes).

    Uses the RCSB search API's chemical service with ``graph-relaxed`` matching so a
    difference in stereo/protonation between the free drug and the bound ligand does not
    prevent a hit. ``None`` when nothing matches (→ fall through to fpocket/blind).
    """
    from rdkit import Chem

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    inchi = Chem.MolToInchi(mol)
    if not inchi:
        return None
    chem_node = {
        "type": "terminal", "service": "chemical",
        "parameters": {
            "value": inchi, "type": "descriptor", "descriptor_type": "InChI",
            "match_type": "graph-relaxed",
        },
    }
    entry_q = {
        "query": {"type": "group", "logical_operator": "and", "nodes": [
            {"type": "terminal", "service": "text", "parameters": {
                "attribute": "rcsb_polymer_entity_container_identifiers."
                "reference_sequence_identifiers.database_accession",
                "operator": "exact_match", "value": uniprot}},
            {"type": "terminal", "service": "text", "parameters": {
                "attribute": "rcsb_polymer_entity_container_identifiers."
                "reference_sequence_identifiers.database_name",
                "operator": "exact_match", "value": "UniProt"}},
            chem_node,
        ]},
        "return_type": "entry",
        "request_options": {"paginate": {"start": 0, "rows": 5}},
    }
    comp_q = {
        "query": chem_node,
        "return_type": "mol_definition",
        "request_options": {"paginate": {"start": 0, "rows": 10}},
    }
    try:
        entries = _rcsb_ids(entry_q)
        if not entries:
            return None
        comps = _rcsb_ids(comp_q)
    except requests.RequestException as exc:
        _log(f"holo discovery query failed ({exc}); skipping")
        return None
    if not comps:
        return None
    # Every hit already co-crystallises the drug (chem + UniProt filter), so choose the one
    # that best captures the drug-bound pocket geometry: sharpest experimental method, then
    # best (lowest) resolution, with the PDB id as a final deterministic tiebreak. This is
    # both reproducible (RCSB's own relevance order drifts) and scientifically principled —
    # the box is only as good as the structure that resolves the binding site.
    ranked = sorted(entries, key=lambda pid: (*_entry_quality(pid), pid))
    pdb_id = ranked[0]
    comps = sorted(comps)
    _log(f"discovered holo {pdb_id} for drug (ranked {ranked}; ligand candidates {comps})")
    return pdb_id, comps


def _entry_quality(pdb_id: str) -> tuple[int, float]:
    """``(method_rank, resolution_Å)`` for ranking drug-bound holo candidates.

    Fetches the RCSB entry metadata and scores it by how faithfully it resolves a
    small-molecule pocket (see :data:`_METHOD_RANK`): experimental method first, then
    resolution ascending. A fetch/parse failure or a resolution-less method sorts last
    (``inf``) so a well-characterised structure always wins, and the caller still applies a
    deterministic PDB-id tiebreak — so ranking degrades gracefully, never crashes.
    """
    try:
        resp = requests.get(_RCSB_ENTRY + pdb_id, timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
        info = resp.json().get("rcsb_entry_info", {})
    except (requests.RequestException, ValueError):
        return (99, float("inf"))
    method = (info.get("experimental_method") or "").upper()
    res_list = info.get("resolution_combined") or []
    resolution = float(res_list[0]) if res_list else float("inf")
    return (_METHOD_RANK.get(method, 50), resolution)


def _rcsb_ids(query: dict) -> list[str]:
    resp = requests.post(_RCSB_SEARCH, json=query, timeout=_HTTP_TIMEOUT)
    if resp.status_code == 204:  # no content = no match
        return []
    resp.raise_for_status()
    return [hit["identifier"] for hit in resp.json().get("result_set", [])]


# --------------------------------------------------------------------------- #
# Covalent tethered-ligand preparation (Meeko CovalentBuilder via mk_prepare_ligand)
# --------------------------------------------------------------------------- #
def prepare_covalent_ligand(
    mol, receptor_pdb: str, chain: str, resnum: int,
    tether_smarts: str, tether_indices: tuple[int, int], workdir: str,
) -> str:
    """Tether ``mol``'s warhead to the reactive residue and write a Vina-ready PDBQT.

    Meeko's ``CovalentBuilder`` aligns the two tether atoms onto the residue CA/CB, giving
    a ligand pre-positioned in the covalent binding geometry. Its output is a flexible-
    residue block (``BEGIN_RES``/``END_RES`` and no ``TORSDOF``), which the Python Vina
    bindings reject — true fixed-tether covalent docking needs AutoDock4/GPU, which is not
    in the toolchain — so the wrapper is stripped and ``TORSDOF`` added, leaving a standard
    ligand PDBQT that docks (in the reactive-residue box) from the covalent pose.
    """
    from rdkit import Chem

    mk = shutil.which("mk_prepare_ligand.py")
    if not mk:
        raise RuntimeError("mk_prepare_ligand.py not on PATH (meeko not installed)")

    sdf = os.path.join(workdir, "ligand_cov.sdf")
    writer = Chem.SDWriter(sdf)
    writer.write(mol)
    writer.close()
    raw = os.path.join(workdir, "ligand_cov_tethered.pdbqt")
    proc = subprocess.run(
        [mk, "-i", sdf, "-o", raw, "--receptor", receptor_pdb,
         "--rec_residue", f"{chain}:CYS:{resnum}",
         "--tether_smarts", tether_smarts,
         "--tether_smarts_indices", str(tether_indices[0]), str(tether_indices[1])],
        capture_output=True, text=True,
    )
    if not os.path.exists(raw):
        raise RuntimeError(f"covalent ligand prep failed: {proc.stderr.strip()[-300:]}")

    body = [ln for ln in open(raw) if not ln.startswith(("BEGIN_RES", "END_RES"))]
    if not any(ln.startswith("TORSDOF") for ln in body):
        body.append(f"TORSDOF {sum(1 for ln in body if ln.startswith('BRANCH'))}\n")
    out = os.path.join(workdir, "ligand_cov.pdbqt")
    with open(out, "w") as fh:
        fh.writelines(body)
    return out


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
@dataclass
class DockingSite:
    """The chosen structure + box + (optional pre-prepared covalent) ligand for a run."""

    pdb_path: str
    structure_prov: dict[str, Any]
    center: list[float]
    size: list[float]
    mode: str
    ligand_pdbqt: str | None = None
    box_provenance: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def select_binding_site(
    *, target: str, uniprot: str, smiles: str, mol, covalent: bool, workdir: str,
) -> DockingSite:
    """Pick structure + docking box by chemistry/target class (see module docstring)."""
    warnings: list[str] = []
    entry = resolve_target_class(target)
    # When a *curated* route fails at the structure level and we fall through to a
    # different structure, this records what we intended so the degradation is queryable
    # in provenance (``curated_route_degraded``), not just a warning string (issue #10).
    intended_route: str | None = None

    # Tier A/covalent — curated covalent class + a tetherable warhead. Once the curated
    # holo resolves and its reactive residue is located, the router *commits to that
    # structure*: only a structure-level failure (can't fetch it / no reactive Cys) falls
    # through to a different PDB. A failure in the tether *preparation* (e.g. Meeko absent
    # in a given environment) degrades to reversible scoring in the **same** reactive-
    # residue box — so a toolchain hiccup can change the pose method but never silently
    # swap the structure and its ΔG provenance (the non-determinism behind issue #10).
    if covalent and entry and entry.covalent:
        tether = covalent_tether(mol)
        if tether is None:
            warnings.append(
                "covalent warhead is not a tetherable family (only Michael acceptors are "
                "configured); docking reversibly in the reactive pocket"
            )
        try:
            pdb_path, fmt = _fetch_experimental_pdb(entry.holo_pdb, workdir)
            reactive = detect_reactive_cys(pdb_path)
            if reactive is None:
                raise RuntimeError("no reactive cysteine found in curated holo")
            chain, resnum = reactive
            center, size = residue_box(pdb_path, chain, resnum)
        except Exception as exc:  # noqa: BLE001 — structure unusable: this is the ONLY
            # covalent failure allowed to change the structure, and it is recorded loudly.
            intended_route = f"covalent-tethered (curated holo {entry.holo_pdb})"
            warnings.append(
                f"curated covalent holo {entry.holo_pdb} is unusable ({exc}); falling "
                "through to a different structure — result is NOT the curated covalent route"
            )
        else:
            prov = {"structure_source": "RCSB", "pdb_id": entry.holo_pdb,
                    "structure_format": fmt,
                    "structure_sha256": structure_checksum(pdb_path)}
            box_prov: dict[str, Any] = {"target_class": entry.label,
                                        "reactive_residue": f"{chain}:CYS:{resnum}"}
            ligand_pdbqt = None
            mode = "covalent-residue (curated holo, reversible fallback)"
            if tether is not None:
                family, tether_smarts, indices = tether
                try:
                    # Meeko's tether prep parses the receptor with ProDy for the residue
                    # geometry; give it a protein-only PDB so bound hetero groups (GDP/MOV)
                    # do not trip its residue-template generation.
                    clean = _write_clean_receptor(
                        pdb_path, os.path.join(workdir, "cov_rec.pdb")
                    )
                    ligand_pdbqt = prepare_covalent_ligand(
                        mol, clean, chain, resnum, tether_smarts, indices, workdir
                    )
                    box_prov["tether"] = {"warhead": family, "smarts": tether_smarts}
                    mode = "covalent-tethered (curated holo)"
                except Exception as exc:  # noqa: BLE001 — degrade WITHIN this structure
                    warnings.append(
                        f"covalent tether prep failed ({exc}); docking reversibly in the "
                        f"same {entry.holo_pdb} reactive-residue box (structure unchanged)"
                    )
                    box_prov["tether_failed"] = str(exc)
            return DockingSite(pdb_path, prov, center, size, mode,
                               ligand_pdbqt=ligand_pdbqt, box_provenance=box_prov,
                               warnings=warnings)

    # Tier A (reversible) — curated co-crystal ligand box.
    if entry and entry.holo_ligand:
        try:
            pdb_path, fmt = _fetch_experimental_pdb(entry.holo_pdb, workdir)
            center, size, code = ligand_box(pdb_path, entry.holo_ligand)
            return DockingSite(
                pdb_path,
                {"structure_source": "RCSB", "pdb_id": entry.holo_pdb, "structure_format": fmt,
                 "structure_sha256": structure_checksum(pdb_path)},
                center, size, "holo-ligand (curated)",
                box_provenance={"target_class": entry.label, "co_crystal_ligand": code},
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            intended_route = f"holo-ligand (curated {entry.holo_pdb})"
            warnings.append(f"curated holo box unavailable ({exc}); trying discovery")

    # Tier B — auto-discovered co-crystal (reversible drugs only; adducts won't match).
    if not covalent:
        try:
            found = discover_holo(uniprot, smiles)
        except Exception as exc:  # noqa: BLE001
            found = None
            warnings.append(f"holo discovery failed ({exc})")
        if found:
            pdb_id, comps = found
            try:
                pdb_path, fmt = _fetch_experimental_pdb(pdb_id, workdir)
                center, size, code = ligand_box(pdb_path, comps)
                return DockingSite(
                    pdb_path,
                    {"structure_source": "RCSB", "pdb_id": pdb_id, "structure_format": fmt,
                     "structure_sha256": structure_checksum(pdb_path)},
                    center, size, "holo-ligand (discovered)",
                    box_provenance={"co_crystal_ligand": code, "discovered": True,
                                    **_degraded(intended_route)},
                    warnings=warnings,
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"discovered holo box unavailable ({exc})")

    # Tier C/D — no co-crystal: best experimental/predicted structure, then fpocket → blind.
    pdb_path, prov = fetch_structure(uniprot, workdir)
    pocket = fpocket_box(pdb_path, workdir)
    if pocket is not None:
        center, size = pocket
        return DockingSite(pdb_path, prov, center, size, "fpocket",
                           box_provenance={"pocket_source": "fpocket",
                                           "caveat": "geometric ranking, not proven site",
                                           **_degraded(intended_route)},
                           warnings=warnings)
    center, size = compute_docking_box(pdb_path)
    return DockingSite(
        pdb_path, prov, [round(c, 3) for c in center], [round(s, 3) for s in size],
        "blind", box_provenance={"caveat": "centroid box; searches a central slab of a "
                                 "large receptor, not a resolved pocket",
                                 **_degraded(intended_route)},
        warnings=warnings,
    )


def _degraded(intended_route: str | None) -> dict[str, Any]:
    """Provenance marking a curated route that fell through to a *different* structure.

    Empty when nothing degraded, so the fields only appear when a curated covalent/holo
    route failed at the structure level and a lower tier picked a different PDB — making
    the degradation queryable (``curated_route_degraded``), not just a warning string.
    """
    if intended_route is None:
        return {}
    return {"curated_route_degraded": True, "intended_route": intended_route}

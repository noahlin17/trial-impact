"""Build the pose-fidelity (Option C) benchmark manifest: for a curated list of
high-resolution protein-ligand co-crystals, resolve the co-crystallised drug-like
ligand (HET code + name + formula weight) from the RCSB REST API and write a
self-contained, committed ``complexes.json`` that the self-docking harness consumes.

Option C asks a pose question, not an affinity one: redock each native ligand into its
own crystal receptor and measure how close the top pose lands to the deposited
crystallographic pose (RMSD), plus whether multi-seed agreement predicts correctness.
That validates the *geometric-engagement* claim the product actually makes.

Only real PDB entries survive: any candidate that fails validation (missing, no
drug-like ligand) is dropped and reported -- nothing is invented. Re-run to refresh or
extend the manifest; it is not on the ``make`` reproduce path.

    python validation/pose_fidelity/fetch_structures.py
"""
import json
import os
import urllib.request

HERE = os.path.dirname(__file__)
RCSB = "https://data.rcsb.org/rest/v1/core"

# Curated candidates: high-resolution co-crystals spanning this project's regime
# (the two FEP-series reference structures + classic kinase / serine-protease drug
# complexes). The script validates each and keeps only those with a drug-like ligand.
CANDIDATES = [
    ("4GIH", "TYK2 (FEP-series reference structure)"),
    ("2ZFF", "Thrombin (FEP-series reference structure)"),
    ("1IEP", "ABL1 + imatinib"),
    ("1M17", "EGFR + erlotinib"),
    ("1UWH", "BRAF + inhibitor"),
    ("3PP0", "HER2/EGFR-family + inhibitor"),
    ("1STP", "Streptavidin + biotin (well-defined control)"),
]

# HET codes that are never the ligand of interest (ions, buffers, cryoprotectants).
_EXCLUDE = {"CL", "NA", "K", "MG", "CA", "ZN", "SO4", "PO4", "GOL", "EDO", "ACT",
            "HOH", "DMS", "MES", "TRS", "PEG", "BME", "IOD", "BR", "FMT", "NO3"}
MIN_FW = 200.0  # drug-like ligand formula-weight floor (Da)


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as fh:  # noqa: S310 (pinned host)
        return json.loads(fh.read().decode())


def resolve(pdb_id: str) -> dict | None:
    pdb = pdb_id.upper()
    try:
        entry = _get_json(f"{RCSB}/entry/{pdb}")
    except Exception as exc:  # noqa: BLE001
        print(f"  DROP {pdb}: entry lookup failed ({type(exc).__name__})", flush=True)
        return None
    info = entry.get("rcsb_entry_info", {})
    resolution = info.get("resolution_combined")
    ids = entry.get("rcsb_entry_container_identifiers", {})
    ligands = []
    for eid in ids.get("non_polymer_entity_ids", []) or []:
        ent = _get_json(f"{RCSB}/nonpolymer_entity/{pdb}/{eid}")
        comp = (ent.get("pdbx_entity_nonpoly", {}) or {}).get("comp_id")
        name = (ent.get("pdbx_entity_nonpoly", {}) or {}).get("name")
        fw = (ent.get("rcsb_nonpolymer_entity", {}) or {}).get("formula_weight")
        fw = float(fw) * 1000.0 if fw and fw < 10 else (float(fw) if fw else 0.0)
        if comp and comp.upper() not in _EXCLUDE and fw >= MIN_FW:
            ligands.append({"het_code": comp, "name": name, "formula_weight": round(fw, 1)})
    if not ligands:
        print(f"  DROP {pdb}: no drug-like ligand found", flush=True)
        return None
    ligands.sort(key=lambda x: -x["formula_weight"])
    lig = ligands[0]  # largest drug-like ligand = the ligand of interest
    print(f"  keep {pdb}: {lig['het_code']} ({lig['name']}) "
          f"res {resolution} fw {lig['formula_weight']}", flush=True)
    return {
        "pdb_id": pdb,
        "resolution_A": resolution[0] if isinstance(resolution, list) else resolution,
        "ligand_het_code": lig["het_code"],
        "ligand_name": lig["name"],
        "ligand_formula_weight": lig["formula_weight"],
    }


def main() -> int:
    complexes = []
    for pdb, note in CANDIDATES:
        rec = resolve(pdb)
        if rec is not None:
            rec["note"] = note
            complexes.append(rec)
    out = {
        "n": len(complexes),
        "source": {
            "metadata": "RCSB REST API (https://data.rcsb.org)",
            "note": ("Self-docking (redock native ligand into own crystal receptor); "
                     "reference pose = deposited crystallographic coordinates. All PDB "
                     "IDs are real, validated entries; none invented."),
        },
        "complexes": complexes,
    }
    path = os.path.join(HERE, "complexes.json")
    with open(path, "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"wrote {path}: {len(complexes)} complexes", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

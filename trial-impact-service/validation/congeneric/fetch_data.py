"""Fetch a congeneric same-target ligand series (SMILES + measured affinity + full
provenance) from the OpenFF Protein-Ligand Benchmark, and write a self-contained,
committed ``<target>/ligands.json`` that the Option-A harness consumes.

Why this source: PLBenchmark curates the Schrodinger JACS ("Wang 2015") FEP series --
congeneric analogs on a single scaffold, one target, one assay, with a measurement DOI
per ligand. That is exactly the regime the cross-target anchor experiment could NOT
test. Every affinity here is a real, citable number; NONE are invented or interpolated.

The download is pinned to a fixed commit for reproducibility. The committed
``ligands.json`` is the artifact the rest of the pipeline reads, so this fetch only has
to be re-run to refresh/extend the set -- it is not on the ``make`` reproduce path.

    # run in an env with rdkit + pyyaml (e.g. .venv)
    python validation/congeneric/fetch_data.py tyk2
    python validation/congeneric/fetch_data.py thrombin
"""
import json
import math
import os
import sys
import urllib.request

import yaml
from rdkit import Chem

HERE = os.path.dirname(__file__)

# Pinned commit of openforcefield/protein-ligand-benchmark (default branch @ 2024).
PIN = "fd88824f9114244f95a14b485e6d6c96c1de716d"
BASE = ("https://raw.githubusercontent.com/openforcefield/"
        f"protein-ligand-benchmark/{PIN}/data")

# uM-referenced affinity -> molar for the pAffinity = -log10(M) conversion.
_UNIT_TO_M = {"m": 1.0, "mm": 1e-3, "um": 1e-6, "nm": 1e-9, "pm": 1e-12}


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as fh:  # noqa: S310 (pinned host)
        return fh.read().decode()


def _to_paffinity(value: float, unit: str) -> float:
    molar = value * _UNIT_TO_M[unit.lower()]
    return round(-math.log10(molar), 3)


def fetch(target: str) -> dict:
    ligs = yaml.safe_load(_get(f"{BASE}/{target}/00_data/ligands.yml"))
    tgt = yaml.safe_load(_get(f"{BASE}/{target}/00_data/target.yml"))
    pdb = tgt.get("pdb")  # top-level crystal structure (not the 'alternate' block)

    ligands = []
    for lig_id, e in ligs.items():
        m = e.get("measurement", {})
        atype = str(m.get("type", "")).lower()
        if atype not in {"ki", "kd", "ic50"} or m.get("unit", "").lower() not in _UNIT_TO_M:
            print(f"  WARN {lig_id}: no ki/kd/ic50 in molar-convertible unit, skipping",
                  flush=True)
            continue
        smiles = e.get("smiles", "")
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            print(f"  WARN unparseable SMILES for {lig_id}, skipping", flush=True)
            continue
        canon = Chem.MolToSmiles(mol)
        value, unit = float(m["value"]), m["unit"]
        ligands.append({
            "id": lig_id,
            "smiles": canon,
            "heavy_atoms": mol.GetNumHeavyAtoms(),
            "affinity_type": atype,
            "affinity_value": value,
            "affinity_unit": unit,
            "affinity_error": float(m["error"]) if m.get("error") is not None else None,
            "paffinity": _to_paffinity(value, unit),
            "measurement_doi": m.get("doi"),
        })
    ligands.sort(key=lambda x: -x["paffinity"])
    return {
        "target": target,
        "structure_pdb_id": pdb,
        "n": len(ligands),
        "source": {
            "dataset": "OpenFF Protein-Ligand Benchmark (Schrodinger JACS / Wang 2015)",
            "repo": "https://github.com/openforcefield/protein-ligand-benchmark",
            "pinned_commit": PIN,
            "note": ("Congeneric same-target series on a single scaffold with a "
                     "measurement DOI per ligand. Affinities are real; none invented. "
                     "paffinity = -log10(value in molar); higher = tighter."),
        },
        "ligands": ligands,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: fetch_data.py <target>  (e.g. tyk2, thrombin)")
        return 2
    target = sys.argv[1].lower()
    data = fetch(target)
    out_dir = os.path.join(HERE, target)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "ligands.json")
    with open(out, "w") as fh:
        json.dump(data, fh, indent=2)
    span = (max(x["paffinity"] for x in data["ligands"])
            - min(x["paffinity"] for x in data["ligands"]))
    print(f"wrote {out}: {data['n']} ligands, pAffinity span {span:.2f} log units, "
          f"structure {data['structure_pdb_id']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

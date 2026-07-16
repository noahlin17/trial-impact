"""Join the MM-GBSA output (work/<target>/scores_raw.json) into a self-contained,
committed results/<target>_scores.json that analyze.py and figure.py consume. Failed
ligands are dropped and reported (nothing fabricated). Optional argv = target name.

    python validation/congeneric/build_results.py tyk2
"""
import json
import os
import sys

HERE = os.path.dirname(__file__)
WORK = os.path.join(HERE, "work")


def build(target: str) -> None:
    raw = json.load(open(os.path.join(WORK, target, "scores_raw.json")))
    manifest = json.load(open(os.path.join(HERE, target, "ligands.json")))
    rows = []
    for r in raw:
        if "error" in r:
            print("skipping failed:", r.get("drug"), r["error"])
            continue
        rows.append({
            "id": r["drug"], "heavy_atoms": r["heavy_atoms"],
            "affinity_type": r["affinity_type"], "paffinity": r["paffinity"],
            "vina_dg": r["vina_dg"], "dg_mmgbsa": r["dg_mmgbsa"],
        })
    expected = {lig["id"] for lig in manifest["ligands"]}
    actual = [r["id"] for r in rows]
    missing = expected - set(actual)
    unexpected = set(actual) - expected
    duplicates = {lig_id for lig_id in actual if actual.count(lig_id) > 1}
    if missing or unexpected or duplicates:
        raise RuntimeError(
            f"{target} result coverage mismatch: missing={sorted(missing)}, "
            f"unexpected={sorted(unexpected)}, duplicates={sorted(duplicates)}"
        )
    rows.sort(key=lambda x: -x["paffinity"])
    out_dir = os.path.join(HERE, "results")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{target}_scores.json")
    json.dump({
        "target": target, "structure_pdb_id": manifest["structure_pdb_id"],
        "n": len(rows), "source": manifest["source"], "rows": rows,
    }, open(out, "w"), indent=2)
    print("wrote", out, "with", len(rows), "rows")


def main() -> int:
    for t in sys.argv[1:] or ["tyk2"]:
        build(t)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

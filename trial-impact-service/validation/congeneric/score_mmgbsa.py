"""Stage B of Experiment A (run in the mmgbsa conda env): cheap single-snapshot MM-GBSA
rescore of each congeneric pose prepped by prep_poses.py. Reuses the SAME validated
protocol as the anchor experiment (validation/score_mmgbsa.score_one: PDBFixer-clean
receptor, ff14SB + GAFF-2.11, implicit OBC2, ligand-only minimization in a rigid
receptor, dG = E_complex - E_receptor - E_ligand, no entropy) so the two experiments are
directly comparable and there is one MM-GBSA implementation, not two.

Scans validation/congeneric/work/<target>/<ligand_id>/ and writes
validation/congeneric/work/<target>/scores_raw.json. Optional argv = target name.

    micromamba run -n mmgbsa python validation/congeneric/score_mmgbsa.py tyk2
"""
import glob
import json
import os
import sys

from validation.score_mmgbsa import score_one

HERE = os.path.dirname(__file__)
WORK = os.path.join(HERE, "work")


def score_target(target: str) -> None:
    out = []
    dirs = sorted(glob.glob(os.path.join(WORK, target, "*", "meta.json")))
    for meta_path in dirs:
        d = os.path.dirname(meta_path)
        if os.path.basename(d) == "_shared":
            continue
        meta = json.load(open(meta_path))
        try:
            row = score_one(d)
            row["paffinity"] = meta["paffinity"]
            row["heavy_atoms"] = meta["heavy_atoms"]
            row["affinity_type"] = meta["affinity_type"]
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            row = {"drug": meta.get("drug"), "error": f"{type(exc).__name__}: {exc}"}
        out.append(row)
        print(json.dumps({k: row.get(k) for k in
                          ("drug", "vina_dg", "dg_mmgbsa", "paffinity", "error")}),
              flush=True)
    json.dump(out, open(os.path.join(WORK, target, "scores_raw.json"), "w"), indent=2)
    print("wrote", os.path.join(WORK, target, "scores_raw.json"), flush=True)


def main() -> int:
    for t in sys.argv[1:] or ["tyk2"]:
        print(f"=== MM-GBSA congeneric {t} ===", flush=True)
        score_target(t)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

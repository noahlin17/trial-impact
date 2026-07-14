"""Join the raw MM-GBSA output (work/scores_raw.json) with the measured affinities
(anchors.json) and each ligand's heavy-atom count into the self-contained, committed
results/scores.json that analyze.py and figure.py consume. Run in an env with rdkit
(e.g. the mmgbsa conda env) after prep_poses.py + score_mmgbsa.py.
"""
import json
import os

from rdkit import Chem

HERE = os.path.dirname(__file__)
WORK = os.path.join(HERE, "work")


def main() -> int:
    anchors = json.load(open(os.path.join(HERE, "anchors.json")))["anchors"]
    aff = {a["drug"]: a for a in anchors}
    raw = json.load(open(os.path.join(WORK, "scores_raw.json")))
    rows = []
    for r in raw:
        if "error" in r:
            print("skipping failed:", r)
            continue
        drug = r["drug"]
        smiles = json.load(open(os.path.join(WORK, f"{r['target']}_{drug}",
                                              "meta.json")))["smiles"]
        heavy = Chem.MolFromSmiles(smiles).GetNumHeavyAtoms()
        rows.append({
            "target": r["target"], "drug": drug, "pdb_id": r["pdb_id"],
            "mode": r["mode"], "heavy_atoms": heavy,
            "vina_dg": round(r["vina_dg"], 3), "mmgbsa_dg": round(r["dg_mmgbsa"], 3),
            "measured_kd_nM": aff[drug]["kd_nM"], "measured_pkd": aff[drug]["pkd"],
        })
    rows.sort(key=lambda x: -x["measured_pkd"])
    out = os.path.join(HERE, "results", "scores.json")
    json.dump({"n": len(rows), "rows": rows}, open(out, "w"), indent=2)
    print("wrote", out, "with", len(rows), "rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

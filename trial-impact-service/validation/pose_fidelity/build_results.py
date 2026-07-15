"""Join the self-docking output (work/selfdock_raw.json) into the self-contained,
committed results/selfdock.json that analyze.py and figure.py consume. Failed complexes
are dropped and reported (nothing fabricated). Run in the trialsim env after selfdock.py.
"""
import json
import os

HERE = os.path.dirname(__file__)
WORK = os.path.join(HERE, "work")


def main() -> int:
    raw = json.load(open(os.path.join(WORK, "selfdock_raw.json")))
    manifest = {c["pdb_id"]: c for c in
                json.load(open(os.path.join(HERE, "complexes.json")))["complexes"]}
    rows = []
    for r in raw:
        if "error" in r:
            print("skipping failed:", r["pdb_id"], r["error"])
            continue
        m = manifest.get(r["pdb_id"], {})
        rows.append({
            "pdb_id": r["pdb_id"], "het": r["het"], "ligand_name": m.get("ligand_name"),
            "note": m.get("note"), "resolution_A": m.get("resolution_A"),
            "n_ref_heavy": r["n_ref_heavy"], "seeds": r["seeds"],
            "rmsd_per_seed": r["rmsd_per_seed"], "rmsd_top": r["rmsd_top"],
            "rmsd_best": r["rmsd_best"], "rmsd_median": r["rmsd_median"],
            "rmsd_seed_spread": r["rmsd_seed_spread"],
            "dg_per_seed": r["dg_per_seed"], "success_2A": r["success_2A"],
        })
    rows.sort(key=lambda x: x["rmsd_top"])
    out_dir = os.path.join(HERE, "results")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "selfdock.json")
    json.dump({"n": len(rows), "rows": rows}, open(out, "w"), indent=2)
    print("wrote", out, "with", len(rows), "rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Congeneric within-target ranking analysis (Experiment A; self-contained: reads only
the committed results/<target>_scores.json). Within ONE target + scaffold, does a
predictor recover the RELATIVE affinity ordering? Reports, per target (never pooled):

  * Spearman rho + bootstrap 95% CI and Kendall tau (pairwise ranking) vs measured
    pAffinity, for four predictors of tighter binding:
      - heavy-atom size baseline (should be WEAK here: size ~ constant in a series),
      - Vina ligand efficiency (-dG / heavy atoms),
      - raw Vina (-dG)  -- the score MM-GBSA must beat,
      - cheap single-snapshot MM-GBSA (-dG).

Pre-registered POSITIVE (see ../PREREGISTRATION.md): MM-GBSA rho >= +0.5 AND its 95% CI
excludes 0 AND it beats both the size baseline and raw Vina. Run: python analyze.py tyk2
(numpy + scipy).
"""
import json
import math
import os
import sys

import numpy as np
from scipy.stats import spearmanr

HERE = os.path.dirname(__file__)
RHO_THRESHOLD = 0.5


def spearman(x, y) -> float:
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3 or x.std() == 0 or y.std() == 0:
        return float("nan")
    return float(spearmanr(x, y).statistic)


def kendall_tau(x, y) -> float:
    """Pairwise ranking agreement in [-1, 1] (fraction concordant - discordant)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    c = d = 0
    for i in range(n):
        for j in range(i + 1, n):
            s = np.sign(x[i] - x[j]) * np.sign(y[i] - y[j])
            if s > 0:
                c += 1
            elif s < 0:
                d += 1
    tot = c + d
    return float("nan") if tot == 0 else (c - d) / tot


def boot_ci(x, y, n_boot=5000, seed=0):
    rng = np.random.default_rng(seed)
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    vals = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        if len(set(idx.tolist())) < 3:
            continue
        v = spearman(x[idx], y[idx])
        if not math.isnan(v):
            vals.append(v)
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return round(float(lo), 2), round(float(hi), 2)


def analyze(target: str) -> dict:
    data = json.load(open(os.path.join(HERE, "results", f"{target}_scores.json")))
    rows = data["rows"]
    pa = [r["paffinity"] for r in rows]
    heavy = [r["heavy_atoms"] for r in rows]
    preds = {
        "heavy-atoms (size baseline)": heavy,
        "Vina ligand efficiency": [-r["vina_dg"] / r["heavy_atoms"] for r in rows],
        "Vina (-dG)": [-r["vina_dg"] for r in rows],
        "MM-GBSA (-dG)": [-r["dg_mmgbsa"] for r in rows],
    }

    print(f"=== {target} (structure {data['structure_pdb_id']}, n = {len(rows)}) ===\n")
    print(f"{'id':12s} {'pAff':>6s} {'heavy':>6s} {'vina_dG':>9s} {'mmgbsa_dG':>10s}")
    for r in rows:
        print(f"{r['id']:12s} {r['paffinity']:6.2f} {r['heavy_atoms']:6d} "
              f"{r['vina_dg']:9.3f} {r['dg_mmgbsa']:10.2f}")

    print("\n--- Spearman rho / Kendall tau vs measured pAffinity (want POSITIVE) ---")
    summary = {}
    for name, xs in preds.items():
        rho = spearman(xs, pa)
        lo, hi = boot_ci(xs, pa)
        tau = kendall_tau(xs, pa)
        print(f"  {name:28s} rho = {rho:+.2f}  95% CI [{lo:+.2f}, {hi:+.2f}]  "
              f"tau = {tau:+.2f}")
        summary[name] = {"rho": round(rho, 3), "ci95": [lo, hi],
                         "kendall_tau": round(tau, 3)}

    mm = summary["MM-GBSA (-dG)"]
    size_rho = summary["heavy-atoms (size baseline)"]["rho"]
    vina_rho = summary["Vina (-dG)"]["rho"]
    ci_excludes_0 = mm["ci95"][0] > 0
    beats = mm["rho"] > size_rho and mm["rho"] > vina_rho
    positive = mm["rho"] >= RHO_THRESHOLD and ci_excludes_0 and beats
    if positive:
        verdict = (f"POSITIVE for {target}: cheap MM-GBSA recovers relative affinity "
                   f"(rho = {mm['rho']:+.2f} >= {RHO_THRESHOLD}, CI excludes 0, beats "
                   "size + Vina) within this congeneric series -- where the method is "
                   "valid. No absolute Kd / occupancy / cross-target claim follows.")
    else:
        reasons = []
        if mm["rho"] < RHO_THRESHOLD:
            reasons.append(f"rho {mm['rho']:+.2f} < {RHO_THRESHOLD}")
        if not ci_excludes_0:
            reasons.append("95% CI includes 0")
        if not beats:
            reasons.append("does not beat size + Vina")
        verdict = (f"NEGATIVE for {target}: cheap single-snapshot MM-GBSA does not clear "
                   f"the pre-registered bar ({'; '.join(reasons)}). Honest evidence that "
                   "the cheap protocol is insufficient even in the favorable regime.")
    print("\nVERDICT:", verdict)

    result = {"target": target, "structure_pdb_id": data["structure_pdb_id"],
              "n": len(rows), "predictors": summary, "positive": positive,
              "verdict": verdict}
    json.dump(result, open(os.path.join(HERE, "results", f"{target}_summary.json"), "w"),
              indent=2)
    return result


def main() -> int:
    for t in sys.argv[1:] or ["tyk2"]:
        analyze(t)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

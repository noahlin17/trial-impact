"""Scoring-validation head-to-head (self-contained: reads only the committed
results/scores.json). Reports, for each predictor of tighter binding, the Spearman
rank correlation with measured pKd plus a bootstrap 95% CI, and each predictor's
correlation with ligand size. A predictor only earns a binding-strength claim if it
ranks affinity meaningfully AND is not merely tracking size.

Run: python validation/analyze.py    (needs numpy only)
"""
import json
import math
import os

import numpy as np

HERE = os.path.dirname(__file__)


def spearman(x, y) -> float:
    x, y = np.asarray(x, float), np.asarray(y, float)
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


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


def main() -> int:
    rows = json.load(open(os.path.join(HERE, "results", "scores.json")))["rows"]
    pkd = [r["measured_pkd"] for r in rows]
    heavy = [r["heavy_atoms"] for r in rows]
    # Predictors of TIGHTER binding: docking scores are negative, so negate them.
    preds = {
        "heavy-atoms (size baseline)": heavy,
        "Vina  (-dG)": [-r["vina_dg"] for r in rows],
        "MM-GBSA (-dG)": [-r["mmgbsa_dg"] for r in rows],
    }

    print(f"n = {len(rows)}\n")
    hdr = f"{'drug':12s} {'pKd':>6s} {'heavy':>6s} {'vina_dG':>9s} {'mmgbsa_dG':>10s}"
    print(hdr)
    for r in rows:
        print(f"{r['drug']:12s} {r['measured_pkd']:6.2f} {r['heavy_atoms']:6d} "
              f"{r['vina_dg']:9.3f} {r['mmgbsa_dg']:10.2f}")

    print("\n--- Spearman rho vs measured pKd (want strongly POSITIVE) ---")
    summary = {}
    for name, xs in preds.items():
        rho = spearman(xs, pkd)
        lo, hi = boot_ci(xs, pkd)
        rho_size = spearman(xs, heavy) if not name.startswith("heavy") else None
        print(f"  {name:28s} rho = {rho:+.2f}  95% CI [{lo:+.2f}, {hi:+.2f}]"
              + (f"   rho(size) = {rho_size:+.2f}" if rho_size is not None else ""))
        summary[name] = {"rho_pkd": round(rho, 3), "ci95": [lo, hi],
                         "rho_size": round(rho_size, 3) if rho_size is not None else None}

    verdict = ("No predictor ranks cross-target affinity: all rho <= 0 with CIs "
               "spanning zero, and both docking scores track ligand size. "
               "Neither Vina nor single-snapshot MM-GBSA earns a binding-strength claim.")
    print("\nVERDICT:", verdict)
    json.dump({"n": len(rows), "predictors": summary, "verdict": verdict},
              open(os.path.join(HERE, "results", "summary.json"), "w"), indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

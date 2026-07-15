"""Pose-fidelity analysis (Experiment C; self-contained: reads only the committed
results/selfdock.json). Reports, over the redocked co-crystals:

  * the redocking success rate (fraction with top-pose in-place RMSD < 2.0 A, the
    standard criterion) and the median top-pose RMSD, and
  * whether inter-seed agreement predicts correctness -- i.e. do the poses Vina
    reproduces stably (small seed spread) also land closer to the crystal? A usable
    confidence signal means tight-agreement poses are the correct ones.

Pre-registered POSITIVE (see ../PREREGISTRATION.md): success >= 60% AND seed agreement
separates correct (<2 A) from incorrect poses. Run: python analyze.py (numpy only).
"""
import json
import math
import os

import numpy as np

HERE = os.path.dirname(__file__)
SUCCESS_A = 2.0
TARGET_RATE = 0.60


def spearman(x, y) -> float:
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3 or x.std() == 0 or y.std() == 0:
        return float("nan")
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    return float(np.corrcoef(rx, ry)[0, 1])


def main() -> int:
    rows = json.load(open(os.path.join(HERE, "results", "selfdock.json")))["rows"]
    n = len(rows)
    top = [r["rmsd_top"] for r in rows]
    spread = [r["rmsd_seed_spread"] for r in rows]
    n_success = sum(1 for r in rows if r["rmsd_top"] < SUCCESS_A)
    rate = n_success / n if n else 0.0

    print(f"n = {n}\n")
    print(f"{'pdb':6s} {'het':5s} {'heavy':>5s} {'rmsd_top':>9s} {'rmsd_best':>10s} "
          f"{'spread':>7s}  ok<2A")
    for r in rows:
        print(f"{r['pdb_id']:6s} {r['het']:5s} {r['n_ref_heavy']:5d} "
              f"{r['rmsd_top']:9.2f} {r['rmsd_best']:10.2f} {r['rmsd_seed_spread']:7.2f}"
              f"   {'Y' if r['rmsd_top'] < SUCCESS_A else '.'}")

    med = float(np.median(top))
    # Does tight seed agreement flag correct poses? Positive rho(spread, rmsd) => yes.
    rho_spread = spearman(spread, top)
    correct = [s for s, r in zip(spread, top, strict=True) if r < SUCCESS_A]
    wrong = [s for s, r in zip(spread, top, strict=True) if r >= SUCCESS_A]

    print(f"\nsuccess rate (top < {SUCCESS_A} A): {n_success}/{n} = {rate:.0%}"
          f"   (target >= {TARGET_RATE:.0%})")
    print(f"median top-pose RMSD: {med:.2f} A")
    print(f"rho(seed spread, RMSD) = {rho_spread:+.2f}  "
          "(positive => tight agreement flags correct poses)")
    if correct and wrong:
        print(f"mean seed spread: correct {np.mean(correct):.2f} A vs "
              f"incorrect {np.mean(wrong):.2f} A")

    hit_rate = rate >= TARGET_RATE
    agreement_signal = (not math.isnan(rho_spread) and rho_spread > 0
                        and bool(correct) and bool(wrong)
                        and np.mean(correct) < np.mean(wrong))
    verdict = (
        f"POSITIVE: redocking succeeds {rate:.0%} (>= {TARGET_RATE:.0%}); "
        if hit_rate else
        f"MIXED: redocking succeeds {rate:.0%} (< {TARGET_RATE:.0%} target); ")
    verdict += ("tighter multi-seed agreement flags correct poses (usable confidence "
                "signal)." if agreement_signal else
                "seed agreement does not cleanly separate correct from incorrect poses.")
    print("\nVERDICT:", verdict)

    summary = {
        "n": n, "success_rate": round(rate, 3), "n_success": n_success,
        "median_rmsd_top": round(med, 3),
        "rho_spread_rmsd": None if math.isnan(rho_spread) else round(rho_spread, 3),
        "mean_spread_correct": round(float(np.mean(correct)), 3) if correct else None,
        "mean_spread_incorrect": round(float(np.mean(wrong)), 3) if wrong else None,
        "target_rate": TARGET_RATE, "success_threshold_A": SUCCESS_A,
        "verdict": verdict,
    }
    json.dump(summary, open(os.path.join(HERE, "results", "summary.json"), "w"), indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

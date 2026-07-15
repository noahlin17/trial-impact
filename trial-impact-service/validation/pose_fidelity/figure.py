"""Render the pose-fidelity figure from the committed results/selfdock.json:
(left) top-pose in-place RMSD per co-crystal with the 2 A success line; (right) does
inter-seed agreement predict correctness -- seed spread vs top-pose RMSD.

Run: python validation/pose_fidelity/figure.py    (needs numpy + matplotlib)
"""
import json
import os

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(__file__)
SUCCESS_A = 2.0


def main() -> int:
    rows = json.load(open(os.path.join(HERE, "results", "selfdock.json")))["rows"]
    labels = [f"{r['pdb_id']} ({r['het']})" for r in rows]
    top = [r["rmsd_top"] for r in rows]
    spread = [r["rmsd_seed_spread"] for r in rows]
    colors = ["#2a9d8f" if t < SUCCESS_A else "#e76f51" for t in top]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    y = np.arange(len(rows))
    ax1.barh(y, top, color=colors, edgecolor="k")
    ax1.set_yticks(y)
    ax1.set_yticklabels(labels, fontsize=8)
    ax1.invert_yaxis()
    ax1.axvline(SUCCESS_A, ls="--", c="k", lw=1)
    ax1.text(SUCCESS_A, len(rows) - 0.4, "  2 A success", fontsize=8, va="top")
    ax1.set_xlabel("top-pose in-place heavy-atom RMSD to crystal (\u00c5)")
    n_ok = sum(1 for t in top if t < SUCCESS_A)
    ax1.set_title(f"Self-docking pose fidelity\n{n_ok}/{len(rows)} within 2 \u00c5")
    ax1.grid(axis="x", alpha=0.3)

    ax2.scatter(spread, top, c=colors, s=90, edgecolor="k")
    for sp, t, lab in zip(spread, top, labels, strict=True):
        ax2.annotate(lab.split()[0], (sp, t), fontsize=7, xytext=(4, 3),
                     textcoords="offset points")
    ax2.axhline(SUCCESS_A, ls="--", c="k", lw=1)
    ax2.set_xlabel("inter-seed RMSD spread (\u00c5)")
    ax2.set_ylabel("top-pose RMSD to crystal (\u00c5)")
    ax2.set_title("Does seed agreement flag correct poses?")
    ax2.grid(alpha=0.3)

    out = os.path.join(HERE, "results", "posefidelity.png")
    fig.savefig(out, dpi=130, bbox_inches="tight")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

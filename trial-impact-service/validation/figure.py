"""Render the head-to-head figure from the committed results/scores.json:
three panels (size baseline, Vina, MM-GBSA) of predictor vs measured pKd, coloured
by ligand size, each annotated with its Spearman rho.

Run: python validation/figure.py    (needs numpy + matplotlib)
"""
import json
import os

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(__file__)


def spearman(x, y) -> float:
    rx = np.argsort(np.argsort(np.asarray(x, float)))
    ry = np.argsort(np.argsort(np.asarray(y, float)))
    return float(np.corrcoef(rx, ry)[0, 1])


def main() -> int:
    rows = json.load(open(os.path.join(HERE, "results", "scores.json")))["rows"]
    pkd = [r["measured_pkd"] for r in rows]
    heavy = [r["heavy_atoms"] for r in rows]
    names = [r["drug"] for r in rows]

    panels = [
        ("Size baseline", heavy, "heavy atoms"),
        ("Vina score", [-r["vina_dg"] for r in rows], "\u2212\u0394G Vina (kcal/mol)"),
        ("MM-GBSA rescore", [-r["mmgbsa_dg"] for r in rows],
         "\u2212\u0394G MM-GBSA (kcal/mol)"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    sc = None
    for ax, (title, xs, xl) in zip(axes, panels, strict=True):
        sc = ax.scatter(xs, pkd, c=heavy, cmap="viridis", s=90, edgecolor="k")
        for x, y, lab in zip(xs, pkd, names, strict=True):
            ax.annotate(lab, (x, y), fontsize=7, xytext=(4, 3),
                        textcoords="offset points")
        ax.set_title(f"{title}\nSpearman \u03c1 vs pKd = {spearman(xs, pkd):+.2f}")
        ax.set_xlabel(xl)
        ax.set_ylabel("measured pKd")
        ax.grid(alpha=0.3)
    cb = fig.colorbar(sc, ax=axes, fraction=0.025, pad=0.02)
    cb.set_label("ligand heavy atoms (size)")
    fig.suptitle("Cross-target affinity ranking: neither Vina nor single-snapshot "
                 "MM-GBSA recovers pKd (n=8 approved-drug anchors)", fontsize=12)
    out = os.path.join(HERE, "results", "headtohead.png")
    fig.savefig(out, dpi=130, bbox_inches="tight")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

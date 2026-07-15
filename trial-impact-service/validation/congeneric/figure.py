"""Render the congeneric ranking figure from the committed results/<target>_scores.json:
four panels (size baseline, Vina ligand efficiency, raw Vina, MM-GBSA) of predictor vs
measured pAffinity, coloured by ligand size, each annotated with its Spearman rho.

Run: python validation/congeneric/figure.py tyk2   (needs numpy + matplotlib)
"""
import json
import os
import sys

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(__file__)


def spearman(x, y) -> float:
    rx = np.argsort(np.argsort(np.asarray(x, float)))
    ry = np.argsort(np.argsort(np.asarray(y, float)))
    return float(np.corrcoef(rx, ry)[0, 1])


def render(target: str) -> None:
    data = json.load(open(os.path.join(HERE, "results", f"{target}_scores.json")))
    rows = data["rows"]
    pa = [r["paffinity"] for r in rows]
    heavy = [r["heavy_atoms"] for r in rows]
    panels = [
        ("Size baseline", heavy, "heavy atoms"),
        ("Vina ligand efficiency", [-r["vina_dg"] / r["heavy_atoms"] for r in rows],
         "\u2212\u0394G / heavy atom"),
        ("Vina score", [-r["vina_dg"] for r in rows], "\u2212\u0394G Vina (kcal/mol)"),
        ("MM-GBSA rescore", [-r["dg_mmgbsa"] for r in rows],
         "\u2212\u0394G MM-GBSA (kcal/mol)"),
    ]
    fig, axes = plt.subplots(1, 4, figsize=(19, 5))
    sc = None
    for ax, (title, xs, xl) in zip(axes, panels, strict=True):
        sc = ax.scatter(xs, pa, c=heavy, cmap="viridis", s=90, edgecolor="k")
        ax.set_title(f"{title}\nSpearman \u03c1 vs pAffinity = {spearman(xs, pa):+.2f}")
        ax.set_xlabel(xl)
        ax.set_ylabel("measured pAffinity")
        ax.grid(alpha=0.3)
    cb = fig.colorbar(sc, ax=axes, fraction=0.02, pad=0.02)
    cb.set_label("ligand heavy atoms (size)")
    fig.suptitle(f"Within-target congeneric ranking: {target} "
                 f"(structure {data['structure_pdb_id']}, n = {len(rows)})", fontsize=12)
    out = os.path.join(HERE, "results", f"{target}_ranking.png")
    fig.savefig(out, dpi=130, bbox_inches="tight")
    print("wrote", out)


def main() -> int:
    for t in sys.argv[1:] or ["tyk2"]:
        render(t)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

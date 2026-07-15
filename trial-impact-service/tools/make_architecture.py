"""Generate the README architecture diagram (docs/architecture.png)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "architecture.png"

BLUE = "#2a6df4"
DARK = "#1f2d3d"
GREY = "#5b6b7b"
GREEN = "#1c7a3e"
RED = "#b3261e"
LGREY = "#eef2f7"
AMBER = "#f4f0e6"

fig, ax = plt.subplots(figsize=(13.5, 7.4))
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.axis("off")


def box(x, y, w, h, title, lines, fc=LGREY, ec=BLUE, tc=DARK, title_size=11, body_size=8.5):
    ax.add_patch(
        FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.6,rounding_size=2.2",
            linewidth=1.6, edgecolor=ec, facecolor=fc, mutation_aspect=1.0,
        )
    )
    ax.text(x + w / 2, y + h - 4.0, title, ha="center", va="top",
            fontsize=title_size, fontweight="bold", color=tc)
    ax.text(x + w / 2, y + h - 9.6, "\n".join(lines), ha="center", va="top",
            fontsize=body_size, color=GREY, linespacing=1.35)


def arrow(x1, y1, x2, y2, color=BLUE, style="-|>", lw=1.8, ls="-"):
    ax.add_patch(
        FancyArrowPatch(
            (x1, y1), (x2, y2), arrowstyle=style, mutation_scale=16,
            linewidth=lw, color=color, linestyle=ls,
            connectionstyle="arc3,rad=0.0", shrinkA=2, shrinkB=2,
        )
    )


# Title
ax.text(1, 98, "Trial Impact — structure-based target-engagement pipeline",
        ha="left", va="top", fontsize=15, fontweight="bold", color=DARK)
ax.text(1, 93.2,
        "Every quantity is capped at what its step can support: docking yields geometric "
        "engagement, not affinity.",
        ha="left", va="top", fontsize=9.5, color=GREY, style="italic")

# Row 1 — main pipeline (left to right)
y1 = 62
h1 = 24
box(1, y1, 17, h1, "1 · Trial event",
    ["ctgov-watcher polls", "ClinicalTrials.gov;", "HMAC-signed webhook", "→ isolated session"])
box(21, y1, 18, h1, "2 · Structure route",
    ["UniProt / PDB lookup;", "covalent-tether →", "co-crystal → fpocket", "→ blind (tier logged)"])
box(42, y1, 17, h1, "3 · Docking",
    ["AutoDock Vina,", "multi-seed poses;", "pose persisted", "(ΔG ± sd)"])
box(62, y1, 17, h1, "4 · Engagement",
    ["geometric class:", "experimental-site /", "pocket / blind", "— NOT a Kd"], ec=GREEN)
box(82, y1, 17, h1, "5 · PK/PD",
    ["Bateman 1-cmpt", "exposure (Cmax/AUC);", "occupancy only if a", "calibrated Kd exists"])

for x1, x2 in [(18, 21), (39, 42), (59, 62), (79, 82)]:
    arrow(x1, y1 + h1 / 2, x2, y1 + h1 / 2)

# Row 2 — estimator head-to-head + market (center-bottom)
y2 = 20
box(30, y2, 24, 26, "6 · Estimator head-to-head",
    ["vina-docking-pkpd  vs", "ligand-efficiency baseline", "(the size-only control).", "",
     "The comparison is the", "product — not any one", "model's number."], ec=DARK)
box(62, y2, 24, 26, "7 · Market model  (demo)",
    ["endpoint + capped", "geometric corroborator", "→ PoS Δ + price call.", "",
     "Illustrative, rules-based,", "NOT backtested —", "not a tradeable claim."], fc=AMBER, ec=GREY)

# down-arrows into head-to-head and market
arrow(50, y1, 46, y2 + 26, color=DARK)        # docking/engagement -> head-to-head
arrow(70, y1, 70, y2 + 26, color=GREY)        # PK/PD -> market
arrow(54, y2 + 13, 62, y2 + 13, color=GREY)   # head-to-head -> market

# Validation callout (left-bottom)
box(1, y2, 26, 26, "Validation  (the finding)",
    ["8 approved drugs, measured", "ChEMBL affinity, docked", "through this pipeline:", "",
     "ρ(Vina −ΔG, pKd) = −0.24", "ρ(MM-GBSA −ΔG, pKd) = −0.24", "both track size, not affinity",
     "→ no evidence of affinity ranking"], fc="#fdECEC", ec=RED, tc=RED)
# dashed link: docking/scoring tested by validation
arrow(42, y1 + 4, 27, y2 + 22, color=RED, style="-|>", lw=1.6, ls=(0, (4, 3)))
ax.text(30.5, 50.5, "tested by", fontsize=8, color=RED, style="italic", rotation=17)

fig.tight_layout()
fig.savefig(OUTPUT, dpi=150, bbox_inches="tight")
print(f"wrote {OUTPUT}")

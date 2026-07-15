# Scoring validation: can we make a binding-*strength* claim?

The pipeline routes a ligand into the right pocket and produces a reproducible docked
pose. A natural next question is whether the docking **score** also tells us *how
strongly* the ligand binds. This experiment answers that empirically instead of
assuming it — and the honest answer here is **no** (for the cheap scorers we can run),
which is why the product makes only a **geometric-engagement** claim, not an affinity
claim.

## The experiment

Eight approved drugs with real, citable ChEMBL affinities (`anchors.json`), spanning
pKd 7.36–10.09, all reversible, drug-like, single-pocket binders in one well-behaved
docking regime (ATP-competitive kinase hinge binders + one clean soluble-enzyme
inhibitor — matching the oncology domain). Each is docked through the **production
pipeline** (so the pose and ΔG are on our scale), then rescored with a single-snapshot
MM-GBSA. We ask: does either score rank the measured affinity, or just ligand size?

## Result (`results/headtohead.png`, `results/summary.json`)

| predictor | Spearman ρ vs measured pKd | 95% CI | ρ vs ligand size |
|---|---|---|---|
| heavy atoms (size baseline) | −0.52 | [−0.81, +0.43] | — |
| Vina −ΔG | −0.24 | [−0.83, +0.62] | +0.45 |
| MM-GBSA −ΔG | −0.24 | [−0.93, +0.62] | +0.40 |

**Neither Vina nor single-snapshot MM-GBSA recovers cross-target affinity.** Both
correlations are non-positive with CIs spanning zero, and both scores track ligand
**size** (ρ ≈ +0.4). The tell: the two largest ligands (nilotinib, lapatinib) score
most "favorably" in both methods yet are among the *weaker* anchors, while dasatinib —
the tightest binder — lands mid-pack. MM-GBSA does **not** beat Vina, and neither beats
"just count the atoms."

## Why (and the correct scope)

Fast docking scores are dominated by van-der-Waals contact area (≈ size); a
single-pose, rigid-receptor, no-entropy MM-GBSA is still dominated by the same
size-scaling interaction energy. On a set whose affinity range (~2.7 log units) is
smaller than its size range, size drowns out the affinity signal. The
[congeneric same-target test](congeneric/README.md) has now also been run: cheap
single-snapshot MM-GBSA on 13 Tyk2 ligands was negative (ρ = −0.54, 95% CI [−0.86, +0.08]).
More expensive sampling (**explicit-solvent MM-GBSA ensembles / FEP**) remains untested.

Consequently the pipeline makes **no absolute-affinity or binding-strength claim**. The
docked pose is used only as a *geometric engagement* signal (does the ligand dock into
the experimentally-known pocket with a reproducible pose), which is what these methods
can honestly support.

## Reproduce

`results/scores.json` is committed and self-contained, so the analysis + figure
regenerate cheaply (numpy + matplotlib):

```bash
make validate        # from trial-impact-service/ — runs analyze.py + figure.py
```

Regenerating the scores from scratch is the expensive path and needs **both** conda
environments (docking in `trialsim`, rescoring in `mmgbsa`):

```bash
# Stage A — dock + persist poses (trialsim env; ~2 min/anchor)
PYTHONPATH=. micromamba run -n trialsim python validation/prep_poses.py
# Stage B — MM-GBSA rescore (mmgbsa env; ~8-10 min/anchor on CPU)
micromamba run -n mmgbsa python validation/score_mmgbsa.py
# Join -> committed results/scores.json (needs rdkit)
micromamba run -n mmgbsa python validation/build_scores.py
```

`validation/work/` (receptor PDBs, PDBQT, docked poses) is intermediate and gitignored.

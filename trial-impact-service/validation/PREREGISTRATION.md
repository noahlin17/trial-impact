# Pre-registration — A + C "positive takeaway" experiments

This file fixes the metrics, controls, and **pass/fail thresholds before any scores are
computed**, so a positive result cannot be back-fit. It is committed in the scaffolding
PR (no scores yet). Results ship honestly whether positive or negative — a negative
result is recorded, not buried, exactly as the cross-target anchor experiment was.

Scope discipline (unchanged from the shipped project): no absolute Kd, no occupancy, no
market-validation claim follows from any outcome here. The most any positive result can
support is a **relative** claim within its regime.

---

## Context: why these experiments exist

The shipped cross-target experiment (8 approved drugs, different targets) is negative:
Vina ρ = −0.24 and cheap MM-GBSA ρ = −0.24 vs measured pKd, both tracking ligand size
(ρ ≈ +0.45). That is the expected regime failure — size dominates when the affinity
range is small relative to the size range and receptor prep differs per target.

A and C test the two regimes where structure-based scoring is *supposed* to work, so a
positive result would **map the boundary** of the method rather than overturn the
negative finding.

---

## Experiment A — congeneric within-target relative ranking

**Question.** Within one target + one scaffold (size/pocket ~constant), does cheap
single-snapshot MM-GBSA rank *relative* affinity, and does it beat the size baseline and
raw Vina?

**Data (committed, real, pinned).**
- `congeneric/tyk2/ligands.json` — 13 ligands, pAffinity span 2.53 log units.
- `congeneric/thrombin/ligands.json` — 23 ligands, pAffinity span 4.28 log units.
- Source: OpenFF Protein-Ligand Benchmark (Schrodinger JACS / Wang 2015), pinned commit,
  measurement DOI per ligand. No affinity invented or interpolated.
- **Primary target = Tyk2** (single scaffold, near-neutral, clean pocket). Thrombin is a
  replication target and carries a known charge/protonation caveat (documented in its
  `target.yml`), so it is analyzed **separately, never pooled** with Tyk2.

**Method.** Dock every analog into the *same* receptor + pocket (fixed structure,
protonation, box, routing), multi-seed, persist poses; score each pose with Vina ΔG and
the existing cheap MM-GBSA protocol (rigid receptor, ligand-only minimization, no
entropy). Readout is **relative to the series median** (ΔΔ), because the claim is
*ranking within the series*, not absolute energies.

**Predictors compared (all vs measured pAffinity):**
1. heavy-atom / MW size baseline (expected *weak* here — size barely varies);
2. ligand efficiency;
3. Vina −ΔG (incumbent to beat);
4. MM-GBSA −ΔG (the candidate).

**Metrics (per target, never cross-target pooled):**
- primary: Spearman ρ(predictor, pAffinity) with a bootstrap 95% CI (same estimator as
  `analyze.py`);
- secondary: Kendall τ / pairwise-ranking accuracy (% correctly ordered pairs);
- reported-only: RMSE/MUE in kcal/mol (absolutes are not over-read).

**Pre-registered "POSITIVE" (all must hold, on ≥1 target — ideally both):**
1. MM-GBSA Spearman ρ ≥ **+0.5** vs measured pAffinity;
2. its bootstrap 95% CI **excludes 0**;
3. MM-GBSA **beats both** the size baseline and raw Vina on ρ;
4. it **survives a seed/pose-sensitivity check** — re-scoring the top-N docked seeds
   (not just the top pose) leaves the ranking and the ρ ≥ +0.5 conclusion intact.

**Interpretation guard.**
- POSITIVE ⇒ *"cheap physics rescoring recovers relative affinity ordering within a
  congeneric series, where it is methodologically valid; cross-target it does not (prior
  result). Here is the boundary."* It does **not** imply absolute Kd, cross-target
  transfer, occupancy, or a market claim.
- NEGATIVE ⇒ *"even in the easy congeneric regime, cheap single-snapshot MM-GBSA does
  not beat size/Vina — relative ranking here needs FEP/TI or explicit-solvent
  ensembles."* Narrows scope further; still shipped.

---

## Experiment C — pose fidelity / self-docking

**Question.** Does the multi-seed protocol reproduce crystallographic poses, and does
inter-seed agreement predict pose correctness?

**Data (committed, real).** `pose_fidelity/complexes.json` — validated RCSB co-crystals
(FEP reference structures + classic kinase / serine-protease drug complexes + a
well-defined biotin control), each with its deposited ligand HET code as the reference.

**Method.** Redock each native ligand into its own crystal receptor (multi-seed);
reference pose = deposited crystallographic coordinates. Compute symmetry-corrected
heavy-atom RMSD of the top pose to the crystal, and the inter-seed RMSD spread.

**Metrics.**
- fraction of complexes with top-pose RMSD **< 2.0 Å** (the standard redocking success
  criterion);
- median top-pose RMSD;
- correlation between inter-seed agreement and pose correctness (does tight seed
  agreement flag correct poses?).

**Pre-registered "POSITIVE":**
1. top pose < 2.0 Å in **≥ 60%** of complexes;
2. seed agreement separates correct (< 2 Å) from incorrect poses (a usable confidence
   signal).

**Interpretation guard.** POSITIVE validates the *geometric-engagement* claim the
product already makes and turns the multi-seed number into a validated confidence
metric. It says **nothing** about affinity.

---

## Ordering & compute discipline (per user constraint)

Runs are backgrounded and each route is abandoned/edited if it proves faulty or too
CPU-intensive. On this 2-core, no-GPU box only the *cheap* protocols are used:

1. **C first** (self-dock only, no MM-GBSA; ~30 min for the manifest) — cheapest, and
   it de-risks A's poses.
2. **A on Tyk2, single top pose** (~3 hr of MM-GBSA at ~10 min/pose) — the headline.
3. Only if A/Tyk2 looks promising: spend the seed-sensitivity multiple and add thrombin.

Explicitly **out of scope** (needs GPU/cluster): full-complex minimization,
explicit-solvent MD, multi-snapshot ensemble MM-GBSA, FEP/TI, gnina CNN.

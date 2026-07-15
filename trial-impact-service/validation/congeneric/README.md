# Congeneric within-target ranking (Experiment A)

Tests whether cheap single-snapshot MM-GBSA ranks **relative** affinity within a
single-target, single-scaffold congeneric series — the regime the shipped cross-target
experiment could not test, and where structure-based scoring is supposed to work.

Metrics, controls, and pre-registered pass/fail thresholds: see
[`../PREREGISTRATION.md`](../PREREGISTRATION.md).

## Data (committed, real, pinned — nothing invented)

- `tyk2/ligands.json` — 13 ligands, pAffinity span 2.53 log units (primary target).
- `thrombin/ligands.json` — 23 ligands, pAffinity span 4.28 log units (replication;
  known charge/protonation caveat, analyzed separately).

Regenerate / extend from the pinned OpenFF Protein-Ligand Benchmark
(Schrodinger JACS / Wang 2015; measurement DOI per ligand):

```bash
python validation/congeneric/fetch_data.py tyk2
python validation/congeneric/fetch_data.py thrombin
```

`fetch_data.py` needs `rdkit` + `pyyaml`. The committed `ligands.json` is the artifact
the harness reads, so the fetch is not on the `make` reproduce path.

## Result — Tyk2 (`results/tyk2_scores.json`, `results/tyk2_summary.json`, `results/tyk2_ranking.png`)

All 13 analogs docked into the **same** 4GIH receptor/pocket (fixed prep), then rescored
with the cheap single-snapshot MM-GBSA protocol. Spearman ρ vs measured pAffinity:

| predictor | ρ vs pAffinity | 95% CI | Kendall τ |
|---|--:|--:|--:|
| heavy-atoms (size baseline) | +0.29 | [−0.29, +0.73] | +0.23 |
| Vina ligand efficiency | −0.29 | [−0.66, +0.32] | −0.15 |
| Vina (−ΔG) | +0.08 | [−0.51, +0.68] | +0.05 |
| **MM-GBSA (−ΔG)** | **−0.54** | **[−0.86, +0.08]** | **−0.38** |

**NEGATIVE (pre-registered bar NOT met).** MM-GBSA ρ = −0.54 (target ≥ +0.5), its CI
includes 0, and it beats neither the size baseline nor raw Vina — it is in fact *inversely*
correlated with affinity here. Even in the favorable congeneric regime, the cheap
single-snapshot rigid-receptor protocol (one pose, no entropy, no ensemble, single
protonation) does not recover relative affinity ordering; raw Vina is essentially flat
(ρ ≈ 0), consistent with the ~constant ligand size across the series.

This does **not** say MM-GBSA is fundamentally useless — it says *this cheap CPU-only
variant* is insufficient. Recovering affinity here would need ensemble averaging,
flexible-receptor minimization, careful protonation/tautomer states, and entropy — the
expensive sampling we scoped out. Reported honestly rather than tuned to a positive.

Pairs with the pose-fidelity **positive** (`../pose_fidelity/`): the pipeline reproduces
crystal *geometry* (6/7 < 2 Å) but cheap physics does not rank *affinity* even in-regime —
a sharp, defensible boundary.

## Reproduce

```bash
make validate-congeneric   # analyze.py + figure.py from committed results/tyk2_scores.json
```

Regenerating scores from scratch (downloads + docking + MM-GBSA, ~25 min on 2 CPUs) needs
the trialsim + mmgbsa conda envs:

```bash
PYTHONPATH=. micromamba run -n trialsim python validation/congeneric/prep_poses.py tyk2
PYTHONPATH=. micromamba run -n mmgbsa   python validation/congeneric/score_mmgbsa.py tyk2
micromamba run -n mmgbsa python validation/congeneric/build_results.py tyk2
```

Thrombin (`thrombin/ligands.json`) is committed but **not** run here: the Tyk2 result did
not clear the bar, so per the pre-registration the replication run is not warranted (and
thrombin carries a documented charge/protonation caveat). It stays as documented future
work rather than a padded second negative.

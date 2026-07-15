# Pose fidelity / self-docking (Experiment C)

Tests whether the multi-seed docking protocol reproduces crystallographic poses (top
pose within 2 Å) and whether inter-seed agreement predicts pose correctness. This
validates the **geometric-engagement** claim the product actually makes — it says
nothing about affinity.

Metrics and pre-registered pass/fail thresholds: see
[`../PREREGISTRATION.md`](../PREREGISTRATION.md).

## Data (committed, real — validated RCSB entries, nothing invented)

`complexes.json` — high-resolution co-crystals (the two FEP reference structures +
classic kinase / serine-protease drug complexes + a biotin control), each with its
deposited ligand HET code as the reference pose. Regenerate / extend:

```bash
python validation/pose_fidelity/fetch_structures.py
```

Each candidate is validated against the RCSB REST API; any entry without a drug-like
ligand is dropped and reported.

## Result (`results/selfdock.json`, `results/summary.json`, `results/posefidelity.png`)

Redocking the native ligand into its own crystal receptor (multi-seed, symmetry-corrected
in-place heavy-atom RMSD to the deposited pose):

| pdb | ligand | heavy | top-pose RMSD | < 2 Å |
|---|---|---:|---:|:--:|
| 2ZFF | 53U (thrombin) | 26 | 0.61 | Y |
| 3PP0 | 03Q | 34 | 0.61 | Y |
| 1STP | BTN (biotin) | 16 | 0.62 | Y |
| 1UWH | BAX (sorafenib) | 32 | 0.68 | Y |
| 1IEP | STI (imatinib) | 37 | 1.08 | Y |
| 1M17 | AQ4 (erlotinib) | 29 | 1.46 | Y |
| 4GIH | 0X5 (Tyk2) | 23 | 7.17 | . |

**POSITIVE (pre-registered bar met): 6/7 within 2 Å (86% ≥ 60%), median 0.68 Å.** When
routed to the correct pocket, the multi-seed protocol reproduces the crystallographic
pose — which is exactly the *geometric-engagement* claim the product makes. 4GIH is the
honest miss: Vina finds a rotated in-pocket mode that scores marginally better (the
docked conformer still aligns to the crystal at ~1.3 Å, but is displaced in place).

**Seed agreement is NOT a clean correctness signal.** 4GIH fails *consistently* (tight
seed spread, 0.04 Å) while 1M17 succeeds *despite* a large spread (7.1 Å). So a stable
multi-seed pose is not by itself evidence of a correct pose — a caveat worth stating
rather than the confidence metric we hoped for.

## Interpretation

This validates pose reproduction under pocket-aware routing; it says **nothing** about
affinity. It does not contradict the cross-target negative result — it maps the other
side of the boundary (geometry Vina *can* do; cross-target affinity ranking it cannot).

## Reproduce

```bash
make validate-posefidelity   # analyze.py + figure.py from committed results/selfdock.json
```

Regenerating scores from scratch (downloads + docking) needs the trialsim conda env:

```bash
PYTHONPATH=. micromamba run -n trialsim python validation/pose_fidelity/selfdock.py
micromamba run -n trialsim python validation/pose_fidelity/build_results.py
```

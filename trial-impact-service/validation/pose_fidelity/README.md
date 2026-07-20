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
| 2ZFF | 53U (thrombin) | 26 | 0.62 | Y |
| 3PP0 | 03Q | 34 | 0.60 | Y |
| 1STP | BTN (biotin) | 16 | 0.62 | Y |
| 1UWH | BAX (sorafenib) | 32 | 0.71 | Y |
| 1IEP | STI (imatinib) | 37 | 1.14 | Y |
| 1M17 | AQ4 (erlotinib) | 29 | 5.87 | . |
| 4GIH | 0X5 (Tyk2) | 23 | 7.17 | . |

**POSITIVE on the geometry criterion — criterion 1 met: 5/7 within 2 Å (71% ≥ the
60% bar), median 0.71 Å. Criterion 2, seed agreement as a usable confidence signal,
was NOT met.** When routed to the correct pocket, the multi-seed protocol reproduces 
the crystallographic pose — which is exactly the *geometric-engagement* claim the product makes. 
4GIH and 1M17 are the honest misses: 4GIH fails consistently across all seeds; 1M17's top-ranked 
pose misses (5.87 Å), but at least one alternate seed lands within the 2 Å bar (1.77 Å) 
— a case where the wrong pose was simply ranked first. 4GIH is a confidently converged wrong pose: 
its 0.04 Å spread is inside the 0.02–0.10 Å range of the correct poses, yet its top pose
is 7.17 Å wrong. No seed-spread threshold separates correct from incorrect. Vina finds
a rotated in-pocket mode that scores marginally better (the docked conformer still aligns
to the crystal at ~1.3 Å, but is displaced in place).

The reported Spearman ρ = +0.89 between seed spread and pose error, and mean-spread gap 
(0.04 Å correct versus 2.07 Å incorrect) are driven entirely by the single high-spread 
1M17 outlier. They do not constitute a usable seed-spread threshold or confidence signal.

## Interpretation

This validates pose reproduction under pocket-aware routing; it says **nothing** about
affinity. It does not contradict the cross-target negative result — it maps the other
side of the boundary (geometry Vina *can* do; cross-target affinity ranking it cannot).
Because the native crystal ligand defines the docking box and the receptor is the native
holo structure, this is a geometry/tool-reproduction control, not an independent or
prospective docking test.

## Reproduce

```bash
make validate-posefidelity   # analyze.py + figure.py from committed results/selfdock.json
```

The committed `complexes.json`, archived `structures/*.pdb`, `structures/ligands.json`, and
prepared `structures/receptors/*.pdbqt` are self-contained inputs for full redocking. The
prepared receptor snapshots avoid nondeterministic hydrogen placement during regeneration.
The canonical simulation environment is pinned by `conda-sim.lock.yml`; when the archive is
present, self-docking runs offline from those inputs rather than fetching RCSB structures or
CCD definitions. Docked poses under `work/` remain intermediate and gitignored. The other
validation experiments still use live structure and ligand retrieval, and their MM-GBSA
environment is not represented by a tracked lock, so exact full-redock reproducibility is not
guaranteed there.

For first-time archive population or an explicit live fallback, score regeneration needs the
trialsim conda env:

```bash
PYTHONPATH=. micromamba run -n trialsim python validation/pose_fidelity/selfdock.py
micromamba run -n trialsim python validation/pose_fidelity/build_results.py
```

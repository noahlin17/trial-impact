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

## Status

Scaffold + manifest only. The self-docking harness (redock native ligand, RMSD-to-
crystal, seed-agreement analysis) lands in a follow-up PR against the exploration branch.

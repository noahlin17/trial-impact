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

## Status

Scaffold + data only. Docking harness, MM-GBSA scoring, and the head-to-head analysis
land in follow-up PRs against the exploration branch.

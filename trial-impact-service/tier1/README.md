# Tier-1: the point-in-time backtest harness (scaffold)

This is the skeleton for the **one measured endpoint** the project needs before it can claim
anything predictive (see the peer-review bar in the root README's
[`Next steps`](../../README.md#next-steps) section, and the
"cheap fatal test" — assumption 5). It is a *scaffold*, not a result.

## What is real vs. what is placeholder

| Piece | Status |
|---|---|
| Data contract — [`schema.py`](schema.py) (`TrialRecord`, `Prediction`) | real, tested |
| Leakage rules + time split — [`splits.py`](splits.py) | real, tested |
| Baselines — [`baselines.py`](baselines.py) (`base-rate@1`, `base-rate+genetics@1`) | real, tested |
| Calibration/IC metrics — [`metrics.py`](metrics.py) (Brier, log-loss, Spearman IC, reliability bins) | real, tested |
| Evaluation harness — [`harness.py`](harness.py) | real, tested |
| **Corpus — [`fixtures/corpus.json`](fixtures/corpus.json)** | **SYNTHETIC placeholder — no scientific meaning** |
| Genetics scores (`ot_genetic_score`) | placeholder values; **not** real Open Targets pulls |
| Market-implied probability | **not present** — there is no baseline to beat yet |
| Chemistry feature (docking → probability) | **not wired in** — the point of a future ΔIC test |

**No edge is or can be claimed here.** The harness runs end-to-end on synthetic data purely to
prove the plumbing and enforce the honest-backtest rules. Every number it prints is meaningless
until a real corpus is built.

## The two rules the contract enforces

1. **As-of cutoff (no look-ahead).** Every feature must exist at `feature_as_of`, which must sit on
   or after registration and strictly before the readout. [`assert_no_leakage`](splits.py) rejects
   any row that violates this — so "structure choice is not pinned" becomes a *leakage* check here,
   not a reproducibility nit.
2. **Honest labels + survivorship.** `outcome ∈ {success, failure, unknown}` with an
   `outcome_source`. Unknown/in-flight rows stay in the corpus (survivorship) but are excluded from
   scoring. A registry-only corpus is missing-not-at-random toward winners, so the source is part of
   the record.

## Evaluation

Time-aware split only (random k-fold leaks the future). Judged by **calibration, not accuracy**:
Brier / log-loss and a reliability curve, plus Spearman IC for ranking value. When a chemistry
feature is added it enters as just another `Predictor`, and the same report measures whether it adds
**incremental IC over base-rate + genetics** — the test that decides whether the physics earns its
place.

```bash
python -m tier1.run     # runs on the synthetic fixture; stdlib only
pytest -q tests/test_tier1.py
```

## What real data each piece still needs

- **Corpus** — reconstruct `(trial design, features, outcome, readout_date)` point-in-time over
  history, with outcomes recovered from press releases / 8-Ks (not registry-only), terminated and
  withdrawn trials kept in. This is the laborious, high-value part described in the root README's
  [`Next steps`](../../README.md#next-steps) section.
- **Genetics** — replace placeholder `ot_genetic_score` with real Open Targets genetic-association
  scores per target–indication, pulled as of `feature_as_of`.
- **Market-implied PoS** — recover implied probabilities from the options surface (or an NPV
  decomposition) so the KPI can be measured *against the market*, not in a vacuum.
- **Sponsor→ticker** — real entity resolution to move from a watchlist to a universe; breadth is
  the whole thesis.
- **Chemistry feature** — map the docking pipeline's output to a probability contribution so its
  ΔIC over the baselines can be measured.

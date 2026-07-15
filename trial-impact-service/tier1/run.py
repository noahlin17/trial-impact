"""Tier-1 harness CLI (scaffold).

Loads the synthetic fixture corpus, runs the leakage-safe time split, evaluates the base-rate
and base-rate+genetics baselines, and writes a calibration/IC report. On the synthetic data
the numbers are meaningless by construction — the point is that the harness runs end-to-end
and enforces the honest-backtest rules, so a real corpus drops in unchanged.

Run: python -m tier1.run    (stdlib only)
"""

from __future__ import annotations

import json
import os
from datetime import date

from .baselines import BaseRateBaseline, GeneticsBaseline
from .harness import evaluate
from .schema import load_corpus

HERE = os.path.dirname(__file__)
DEFAULT_CORPUS = os.path.join(HERE, "fixtures", "corpus.json")
DEFAULT_CUTOFF = date(2022, 1, 1)


def main(corpus_path: str = DEFAULT_CORPUS, cutoff: date = DEFAULT_CUTOFF) -> int:
    records = load_corpus(corpus_path)
    report = evaluate([BaseRateBaseline(), GeneticsBaseline()], records, cutoff)

    print("Tier-1 backtest harness — SYNTHETIC SCAFFOLD (numbers are not meaningful)\n")
    print(f"corpus            : {corpus_path}")
    print(f"cutoff            : {report['cutoff']}")
    print(f"train / test rows : {report['n_train']} / {report['n_test']} "
          f"({report['n_test_labelled']} labelled)")
    print(f"test base rate    : {report['test_base_rate']}\n")
    predictors = report["predictors"]
    assert isinstance(predictors, dict)
    for pid, m in predictors.items():
        assert isinstance(m, dict)
        print(f"  {pid:24s} brier={m['brier']}  log_loss={m['log_loss']}  IC={m['spearman_ic']}")

    out = os.path.join(HERE, "fixtures", "report.json")
    with open(out, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nwrote {out}")
    print("\nNOTE: no edge is or can be claimed — the corpus is synthetic. See tier1/README.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

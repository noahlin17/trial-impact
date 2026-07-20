"""Tier-1: the point-in-time backtest harness (scaffold).

This package is the skeleton for the *one measured endpoint* the project needs before it
can claim anything predictive: a calibrated P(success) evaluated against baselines on a
**point-in-time, leakage-safe** trial corpus.

It ships as a *scaffold*, not a result. Concretely:

* the data contract (:mod:`tier1.schema`), leakage rules (:mod:`tier1.splits`),
  baselines (:mod:`tier1.baselines`) and calibration metrics (:mod:`tier1.metrics`) are
  real and tested;
* the corpus it runs on (``tier1/fixtures/corpus.json``) is **synthetic placeholder data**
  with no scientific meaning — it exists only to exercise the harness end-to-end;
* **no edge is claimed and none can be**, because there is no real point-in-time corpus,
  no honest outcome labels, and no market-implied probabilities yet. Producing those is the
  work; see ``tier1/README.md`` for exactly what real data each piece needs.

The design goal is that when a real corpus lands, it drops into this harness unchanged and
the first honest number — a Brier/log-loss/IC of base-rate + genetics vs the market, and
whether chemistry adds ΔIC — falls straight out.
"""

from __future__ import annotations

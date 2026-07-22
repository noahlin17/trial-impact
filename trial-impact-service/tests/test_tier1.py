"""Tier-1 scaffold tests: the honest-backtest rules must actually hold.

These test the harness contract, not any scientific claim — the corpus under test is synthetic.
The point is that leakage is caught, the split respects time, baselines are fit on train only,
and the calibration/ranking metrics are correct on hand-checkable inputs.
"""

from __future__ import annotations

import math
import os
from datetime import date

import pytest

from tier1.baselines import BaseRateBaseline, GeneticsBaseline
from tier1.chemistry import ChemistryAugmentedPredictor, ChemistryPredictor
from tier1.harness import evaluate
from tier1.metrics import brier_score, calibration_bins, incremental_metrics, log_loss, spearman_ic
from tier1.schema import FAILURE, SUCCESS, UNKNOWN, Prediction, TrialRecord, load_corpus
from tier1.splits import LeakageError, assert_no_leakage, time_aware_split

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "tier1", "fixtures", "corpus.json")


def _rec(**kw) -> TrialRecord:
    base = dict(
        trial_id="T", sponsor="S", phase="P2", indication="oncology", drug="d", target="X",
        registered_date=date(2018, 1, 1), feature_as_of=date(2018, 2, 1),
        outcome=SUCCESS, outcome_source="press_release", readout_date=date(2020, 1, 1),
    )
    base.update(kw)
    return TrialRecord(**base)  # type: ignore[arg-type]


# --- schema ---------------------------------------------------------------

def test_label_mapping():
    assert _rec(outcome=SUCCESS).label == 1
    assert _rec(outcome=FAILURE).label == 0
    assert _rec(outcome=UNKNOWN, readout_date=None).label is None


def test_invalid_outcome_rejected():
    with pytest.raises(ValueError):
        _rec(outcome="maybe")


def test_prediction_range_checked():
    Prediction("T", "p@1", 0.5)
    with pytest.raises(ValueError):
        Prediction("T", "p@1", 1.5)


def test_leakage_reason_detects_lookahead_and_pre_registration():
    # features observed after the readout = look-ahead
    assert _rec(feature_as_of=date(2020, 6, 1)).leakage_reason() is not None
    # features observed before registration
    assert _rec(feature_as_of=date(2017, 1, 1)).leakage_reason() is not None
    # clean row
    assert _rec().leakage_reason() is None


# --- corpus + leakage -----------------------------------------------------

def test_fixture_corpus_loads_and_is_leakage_free():
    records = load_corpus(FIXTURE)
    assert len(records) >= 20
    assert_no_leakage(records)  # must not raise


def test_assert_no_leakage_raises_on_dirty_corpus():
    dirty = [_rec(), _rec(trial_id="BAD", feature_as_of=date(2021, 1, 1))]
    with pytest.raises(LeakageError) as exc:
        assert_no_leakage(dirty)
    assert "BAD" in str(exc.value)


# --- time split -----------------------------------------------------------

def test_time_aware_split_respects_cutoff_and_drops_unknowns():
    records = [
        _rec(trial_id="past", readout_date=date(2019, 1, 1)),
        _rec(trial_id="future", readout_date=date(2023, 1, 1)),
        _rec(trial_id="inflight", outcome=UNKNOWN, readout_date=None),
    ]
    train, test = time_aware_split(records, date(2022, 1, 1))
    assert [r.trial_id for r in train] == ["past"]
    assert [r.trial_id for r in test] == ["future"]


# --- baselines ------------------------------------------------------------

def test_base_rate_fit_on_train_only_with_backoff():
    train = [
        _rec(trial_id=f"s{i}", phase="P2", indication="oncology", outcome=SUCCESS)
        for i in range(6)
    ] + [
        _rec(trial_id=f"f{i}", phase="P2", indication="oncology", outcome=FAILURE)
        for i in range(6)
    ]
    b = BaseRateBaseline(min_cell=5)
    assert b.predict(_rec()) == 0.5  # before fit -> global default 0.5
    b.fit(train)
    # cell (P2, oncology) has 12 rows, 6 successes -> 0.5
    assert b.predict(_rec(phase="P2", indication="oncology")) == pytest.approx(0.5)
    # unseen indication backs off to the phase marginal (still 0.5 here), never NaN
    p = b.predict(_rec(phase="P2", indication="neurology"))
    assert 0.0 <= p <= 1.0 and not math.isnan(p)
    # unseen phase backs off to the global rate
    p2 = b.predict(_rec(phase="P9", indication="zzz"))
    assert 0.0 <= p2 <= 1.0


def test_genetics_baseline_monotonic_and_missing_data_safe():
    train = [_rec(trial_id=f"s{i}", outcome=SUCCESS) for i in range(3)] + \
            [_rec(trial_id=f"f{i}", outcome=FAILURE) for i in range(3)]
    g = GeneticsBaseline(strength=1.0)
    g.fit(train)
    lo = g.predict(_rec(features={"ot_genetic_score": 0.1}))
    hi = g.predict(_rec(features={"ot_genetic_score": 0.9}))
    assert hi > lo  # higher genetic support -> higher P(success)
    # missing feature collapses to the base rate (0.5 here), never raises
    assert g.predict(_rec(features={})) == pytest.approx(0.5)


def test_chemistry_predictor_is_train_only_monotonic_and_missing_safe():
    train = [
        _rec(trial_id="f1", outcome=FAILURE, features={"docking_engagement": 0.1}),
        _rec(trial_id="f2", outcome=FAILURE, features={"docking_engagement": 0.4}),
        _rec(trial_id="s1", outcome=SUCCESS, features={"docking_engagement": 0.8}),
        _rec(trial_id="s2", outcome=SUCCESS, features={"docking_engagement": 0.9}),
    ]
    chemistry = ChemistryPredictor()
    chemistry.fit(train)

    predictions = [
        chemistry.predict(_rec(features={"docking_engagement": value}))
        for value in (0.0, 0.1, 0.4, 0.8, 0.9, 1.0)
    ]
    assert predictions == sorted(predictions)
    assert all(0.0 <= probability <= 1.0 for probability in predictions)
    assert chemistry.predict(_rec(features={})) == pytest.approx(0.5)

    # A high-valued test feature cannot alter a model fitted only on failures.
    train_only = ChemistryPredictor()
    train_only.fit([_rec(outcome=FAILURE, features={"docking_engagement": 0.1})])
    assert train_only.predict(_rec(outcome=SUCCESS, features={"docking_engagement": 0.99})) == 0.0


def test_chemistry_augmented_predictor_preserves_prior_when_feature_missing():
    train = [
        _rec(trial_id="f1", outcome=FAILURE, features={"docking_engagement": 0.1}),
        _rec(trial_id="s1", outcome=SUCCESS, features={"docking_engagement": 0.9}),
    ]
    augmented = ChemistryAugmentedPredictor()
    prior = GeneticsBaseline()
    augmented.fit(train)
    prior.fit(train)

    missing = _rec(features={})
    assert augmented.predict(missing) == pytest.approx(prior.predict(missing))
    assert 0.0 <= augmented.predict(_rec(features={"docking_engagement": 0.9})) <= 1.0


def test_incremental_metrics_reports_candidate_minus_baseline():
    result = incremental_metrics([0, 1], [0.4, 0.6], [0.2, 0.8])
    assert result["delta_brier"] < 0.0
    assert result["delta_ic"] == pytest.approx(0.0)


# --- metrics --------------------------------------------------------------

def test_brier_and_log_loss_known_values():
    assert brier_score([1, 0], [1.0, 0.0]) == pytest.approx(0.0)
    assert brier_score([1, 0], [0.0, 1.0]) == pytest.approx(1.0)
    # log loss of a perfect confident prediction ~ 0
    assert log_loss([1, 0], [0.9999999, 0.0000001]) == pytest.approx(0.0, abs=1e-4)


def test_spearman_ic_perfect_and_inverse():
    # distinct targets: perfectly ordered -> +1, reversed -> -1
    assert spearman_ic([0.1, 0.2, 0.3, 0.4], [1.0, 2.0, 3.0, 4.0]) == pytest.approx(1.0)
    assert spearman_ic([0.4, 0.3, 0.2, 0.1], [1.0, 2.0, 3.0, 4.0]) == pytest.approx(-1.0)
    # tied binary labels cap the attainable correlation below 1, but ordering is still positive
    assert spearman_ic([0.1, 0.2, 0.3, 0.4], [0.0, 0.0, 1.0, 1.0]) > 0.8


def test_calibration_bins_partition():
    bins = calibration_bins([1, 0, 1, 0], [0.05, 0.15, 0.95, 0.85], n_bins=10)
    assert sum(b["n"] for b in bins) == 4
    for b in bins:
        assert 0.0 <= b["obs_freq"] <= 1.0


# --- harness --------------------------------------------------------------

def test_evaluate_on_fixture_runs_and_reports():
    records = load_corpus(FIXTURE)
    report = evaluate(
        [BaseRateBaseline(), GeneticsBaseline(), ChemistryAugmentedPredictor()],
        records,
        date(2022, 1, 1),
        comparisons=[("base-rate+genetics@1", "base-rate+genetics+chemistry@1")],
    )
    assert report["n_train"] > 0 and report["n_test"] > 0
    preds = report["predictors"]
    assert "base-rate@1" in preds and "base-rate+genetics@1" in preds
    for m in preds.values():
        assert 0.0 <= m["brier"] <= 1.0
        assert -1.0 <= m["spearman_ic"] <= 1.0
    comparisons = report["comparisons"]
    assert "base-rate+genetics+chemistry@1 vs base-rate+genetics@1" in comparisons

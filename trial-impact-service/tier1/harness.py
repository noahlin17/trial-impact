"""The evaluation harness: fit predictors on train, score them on test.

This is the piece that turns a corpus + a set of predictors into the one number that matters
— a calibration/IC report — with the leakage-safe split enforced up front. It is model-
agnostic: the docking chemistry, once it produces a probability feature, plugs in as just
another :class:`~tier1.baselines.Predictor` and the same report measures whether it adds IC
over the base-rate + genetics priors.
"""

from __future__ import annotations

from datetime import date

from .baselines import Predictor
from .metrics import (
    brier_score,
    calibration_bins,
    incremental_metrics,
    log_loss,
    spearman_ic,
)
from .schema import LABELLED, TrialRecord
from .splits import time_aware_split


def evaluate(
    predictors: list[Predictor],
    records: list[TrialRecord],
    cutoff: date,
    n_calibration_bins: int = 10,
    comparisons: list[tuple[str, str]] | None = None,
) -> dict[str, object]:
    """Fit each predictor on the pre-cutoff split and score it on the post-cutoff split.

    Returns a report dict: the split sizes, and per-predictor Brier / log-loss / Spearman IC
    plus a reliability curve, computed only over test rows with a resolved label.
    """
    train, test = time_aware_split(records, cutoff)
    scored = [r for r in test if r.outcome in LABELLED]
    y = [r.label for r in scored]
    assert all(v is not None for v in y)
    labels: list[int] = [v for v in y if v is not None]

    report: dict[str, object] = {
        "cutoff": cutoff.isoformat(),
        "n_train": len(train),
        "n_test": len(test),
        "n_test_labelled": len(scored),
        "test_base_rate": (sum(labels) / len(labels)) if labels else None,
        "predictors": {},
    }
    if not scored:
        report["note"] = "no resolved test rows — cannot score (expected on the synthetic scaffold)"
        return report

    preds_out: dict[str, object] = {}
    predictions: dict[str, list[float]] = {}
    for predictor in predictors:
        predictor.fit(train)
        p = [predictor.predict(r) for r in scored]
        predictions[predictor.id] = p
        preds_out[predictor.id] = {
            "brier": round(brier_score(labels, p), 4),
            "log_loss": round(log_loss(labels, p), 4),
            "spearman_ic": round(spearman_ic(p, [float(v) for v in labels]), 4),
            "calibration": calibration_bins(labels, p, n_calibration_bins),
        }
    report["predictors"] = preds_out
    if comparisons:
        report["comparisons"] = {}
        for baseline_id, candidate_id in comparisons:
            if baseline_id not in predictions or candidate_id not in predictions:
                raise ValueError(
                    f"comparison requires evaluated predictors: {baseline_id}, {candidate_id}"
                )
            report["comparisons"][f"{candidate_id} vs {baseline_id}"] = incremental_metrics(
                labels,
                predictions[baseline_id],
                predictions[candidate_id],
            )
    return report

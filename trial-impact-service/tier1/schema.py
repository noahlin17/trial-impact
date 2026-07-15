"""The Tier-1 data contract: one point-in-time trial record and one prediction.

The contract encodes the two rules that make a backtest honest (see ``tier1/README.md``):

* **as-of cutoff** — every feature a predictor is allowed to see must have existed at
  ``feature_as_of``. That timestamp must sit on or after the trial registered and strictly
  before the readout; otherwise the "prediction" is using post-hoc information (look-ahead).
* **honest labels** — ``outcome`` is one of :data:`SUCCESS` / :data:`FAILURE` / :data:`UNKNOWN`,
  and ``outcome_source`` records where it came from (press release, 8-K, registry, …). A
  registry-only corpus is missing-not-at-random toward winners, so the source is part of the
  record, not metadata.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

SUCCESS = "success"
FAILURE = "failure"
UNKNOWN = "unknown"
OUTCOMES = frozenset({SUCCESS, FAILURE, UNKNOWN})

# Outcomes that carry a resolved binary label usable for scoring.
LABELLED = frozenset({SUCCESS, FAILURE})


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


@dataclass(frozen=True)
class TrialRecord:
    """A single trial event as it could be reconstructed point-in-time.

    ``features`` holds only quantities knowable at ``feature_as_of`` (base rates are fit on
    the training split, not stored here). ``outcome`` is the resolved label; ``UNKNOWN`` rows
    are kept in the corpus (survivorship) but excluded from scoring.
    """

    trial_id: str
    sponsor: str
    phase: str
    indication: str
    drug: str
    target: str
    registered_date: date
    feature_as_of: date
    outcome: str
    outcome_source: str
    readout_date: date | None = None
    ticker: str | None = None
    features: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise ValueError(f"{self.trial_id}: outcome {self.outcome!r} not in {sorted(OUTCOMES)}")

    @property
    def label(self) -> int | None:
        """1 for success, 0 for failure, ``None`` when unresolved."""
        if self.outcome == SUCCESS:
            return 1
        if self.outcome == FAILURE:
            return 0
        return None

    def leakage_reason(self) -> str | None:
        """Return why this row leaks future information, or ``None`` if it is clean.

        A clean row has ``registered_date <= feature_as_of`` and, when a readout is known,
        ``feature_as_of < readout_date`` (features predate the answer).
        """
        if self.feature_as_of < self.registered_date:
            return "feature_as_of precedes registration"
        if self.readout_date is not None and self.feature_as_of >= self.readout_date:
            return "feature_as_of is on/after the readout (look-ahead)"
        return None

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> TrialRecord:
        reg = _parse_date(raw["registered_date"])  # type: ignore[arg-type]
        asof = _parse_date(raw["feature_as_of"])  # type: ignore[arg-type]
        if reg is None or asof is None:
            raise ValueError(
                f"{raw.get('trial_id')}: registered_date and feature_as_of are required"
            )
        feats_raw = raw.get("features") or {}
        if not isinstance(feats_raw, dict):
            raise ValueError(f"{raw.get('trial_id')}: features must be an object")
        features = {str(k): float(v) for k, v in feats_raw.items()}
        return cls(
            trial_id=str(raw["trial_id"]),
            sponsor=str(raw["sponsor"]),
            phase=str(raw["phase"]),
            indication=str(raw["indication"]),
            drug=str(raw["drug"]),
            target=str(raw["target"]),
            registered_date=reg,
            feature_as_of=asof,
            outcome=str(raw["outcome"]),
            outcome_source=str(raw.get("outcome_source", "")),
            readout_date=_parse_date(raw.get("readout_date")),  # type: ignore[arg-type]
            ticker=(str(raw["ticker"]) if raw.get("ticker") else None),
            features=features,
        )


@dataclass(frozen=True)
class Prediction:
    """A predictor's P(success) for one trial, stamped with the predictor id."""

    trial_id: str
    predictor_id: str
    p_success: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.p_success <= 1.0:
            raise ValueError(
                f"{self.predictor_id}/{self.trial_id}: p_success {self.p_success} out of [0,1]"
            )


def load_corpus(path: str) -> list[TrialRecord]:
    """Load a corpus JSON file (``{"records": [...]}`` or a bare list) into records."""
    with open(path) as fh:
        blob = json.load(fh)
    rows = blob["records"] if isinstance(blob, dict) else blob
    return [TrialRecord.from_dict(r) for r in rows]

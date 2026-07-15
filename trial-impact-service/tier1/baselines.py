"""Baselines a chemistry signal would have to beat.

The cheapest fatal test (THESIS §6, assumption 5) is whether a free prior — historical
phase × indication base rates, plus an Open Targets genetic-association score — is already as
good as anything the physics can add. These are those priors, behind a common
:class:`Predictor` interface so the harness can run them head-to-head and later measure the
*incremental* IC of a chemistry feature over them.

Every fittable predictor is fit **only on the training split** (:meth:`fit`), so no test-set
information reaches a prediction. Predictors that read a feature degrade gracefully when it is
missing, rather than raising.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Protocol, runtime_checkable

from .schema import LABELLED, TrialRecord


@runtime_checkable
class Predictor(Protocol):
    """Turns a :class:`TrialRecord` into a P(success) in [0, 1]."""

    id: str

    def fit(self, train: list[TrialRecord]) -> None:
        """Learn any parameters from the training split (may be a no-op)."""

    def predict(self, record: TrialRecord) -> float:
        ...


class BaseRateBaseline:
    """Historical success frequency by ``phase × indication``, with sensible backoff.

    Fit on the training rows only. At predict time, a cell with too few examples falls back
    to the phase marginal, then to the global base rate — so a novel (phase, indication) pair
    never produces a NaN.
    """

    id = "base-rate@1"

    def __init__(self, min_cell: int = 5) -> None:
        self.min_cell = min_cell
        self._cell: dict[tuple[str, str], float] = {}
        self._phase: dict[str, float] = {}
        self._global = 0.5

    @staticmethod
    def _rate(labels: list[int]) -> float:
        return sum(labels) / len(labels)

    def fit(self, train: list[TrialRecord]) -> None:
        cells: dict[tuple[str, str], list[int]] = defaultdict(list)
        phases: dict[str, list[int]] = defaultdict(list)
        glob: list[int] = []
        for r in train:
            if r.outcome not in LABELLED:
                continue
            y = r.label
            assert y is not None
            cells[(r.phase, r.indication)].append(y)
            phases[r.phase].append(y)
            glob.append(y)
        self._global = self._rate(glob) if glob else 0.5
        self._phase = {p: self._rate(ys) for p, ys in phases.items()}
        self._cell = {
            k: self._rate(ys) for k, ys in cells.items() if len(ys) >= self.min_cell
        }

    def predict(self, record: TrialRecord) -> float:
        key = (record.phase, record.indication)
        if key in self._cell:
            return self._cell[key]
        if record.phase in self._phase:
            return self._phase[record.phase]
        return self._global


class GeneticsBaseline:
    """Base rate tilted by an Open Targets genetic-association score.

    Genetically-supported targets succeed at roughly twice the rate (Nelson et al. 2015), so
    this blends the ``base-rate`` prior with the ``ot_genetic_score`` feature (expected in
    [0, 1]) on the log-odds scale. ``strength`` is the maximum log-odds shift a maximal genetic
    score may apply; it is a documented scaffold constant, **not fit to outcomes** — a real
    build would calibrate it. When the feature is absent the prediction collapses to the base
    rate, so missing genetics never hurts.
    """

    id = "base-rate+genetics@1"
    feature = "ot_genetic_score"

    def __init__(self, strength: float = 1.0, min_cell: int = 5) -> None:
        self.strength = strength
        self._base = BaseRateBaseline(min_cell=min_cell)

    def fit(self, train: list[TrialRecord]) -> None:
        self._base.fit(train)

    def predict(self, record: TrialRecord) -> float:
        base = self._base.predict(record)
        score = record.features.get(self.feature)
        if score is None:
            return base
        score = min(max(score, 0.0), 1.0)
        logit = math.log(base / (1.0 - base)) if 0.0 < base < 1.0 else 0.0
        logit += self.strength * (2.0 * score - 1.0)
        return 1.0 / (1.0 + math.exp(-logit))

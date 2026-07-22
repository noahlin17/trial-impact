"""A deliberately modest chemistry-feature predictor for the Tier-1 scaffold.

The production simulation exposes ``binding_engagement`` as a geometric
classification, not calibrated affinity or occupancy. This scaffold accepts a
pre-mapped scalar named ``docking_engagement``: a real corpus builder must
document how that scalar was derived from the pipeline's geometric output.
Synthetic values in the fixture have no scientific meaning.

The predictor is an isotonic-style one-dimensional calibration fit only on
labelled training rows. It measures whether a chemistry feature adds anything
over the existing prior; it does not assume that it will. The project's
negative affinity-ranking experiments make little-to-no incremental IC the
honest expectation on real data.
"""

from __future__ import annotations

import math

from .baselines import GeneticsBaseline, Predictor
from .schema import LABELLED, TrialRecord


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _logit(probability: float) -> float:
    probability = min(max(probability, 1e-6), 1.0 - 1e-6)
    return math.log(probability / (1.0 - probability))


class ChemistryPredictor:
    """Monotonic one-dimensional calibration of ``docking_engagement``."""

    id = "chemistry-engagement@1"
    feature = "docking_engagement"

    def __init__(self) -> None:
        self._base_rate = 0.5
        self._blocks: list[tuple[float, float, float]] = []

    def fit(self, train: list[TrialRecord]) -> None:
        labelled = [
            (record.features[self.feature], record.label)
            for record in train
            if record.outcome in LABELLED
            and self.feature in record.features
            and record.label is not None
        ]
        self._base_rate = sum(
            1 if record.label == 1 else 0
            for record in train
            if record.outcome in LABELLED and record.label is not None
        ) / max(
            1,
            sum(1 for record in train if record.outcome in LABELLED),
        )
        self._blocks = []
        if not labelled:
            return

        blocks: list[list[float]] = []
        for value, label in sorted(labelled):
            blocks.append([value, value, float(label), 1.0])
            while len(blocks) >= 2:
                previous, current = blocks[-2:]
                if previous[2] / previous[3] <= current[2] / current[3]:
                    break
                merged = [
                    previous[0],
                    current[1],
                    previous[2] + current[2],
                    previous[3] + current[3],
                ]
                blocks[-2:] = [merged]
        self._blocks = [
            (lo, hi, total / weight) for lo, hi, total, weight in blocks
        ]

    def predict(self, record: TrialRecord) -> float:
        value = record.features.get(self.feature)
        if value is None or not self._blocks:
            return self._base_rate
        if value <= self._blocks[0][1]:
            return self._blocks[0][2]
        for _, hi, probability in self._blocks[1:]:
            if value <= hi:
                return probability
        return self._blocks[-1][2]


class ChemistryAugmentedPredictor:
    """Add the calibrated chemistry adjustment to the genetics prior.

    The chemistry probability is centered on its train-only base rate before
    being added on the log-odds scale. Consequently, an absent feature leaves
    the genetics prior unchanged, while the combined score remains a scaffold
    rather than a claim that docking is predictive.
    """

    id = "base-rate+genetics+chemistry@1"

    def __init__(self, strength: float = 1.0) -> None:
        self.strength = strength
        self._prior: Predictor = GeneticsBaseline()
        self._chemistry = ChemistryPredictor()

    def fit(self, train: list[TrialRecord]) -> None:
        self._prior.fit(train)
        self._chemistry.fit(train)

    def predict(self, record: TrialRecord) -> float:
        prior = self._prior.predict(record)
        chemistry = self._chemistry.predict(record)
        adjustment = self.strength * (
            _logit(chemistry) - _logit(self._chemistry._base_rate)
        )
        return _sigmoid(_logit(prior) + adjustment)

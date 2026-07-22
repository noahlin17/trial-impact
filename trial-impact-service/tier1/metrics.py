"""Calibration and ranking metrics — stdlib only, no numpy.

The Tier-1 KPI is **calibration, not accuracy**: a probability is judged by Brier score and
log loss (against the market's implied PoS, once that exists), and its *ordering* value by
the Spearman information coefficient. All functions take aligned sequences of resolved
binary labels ``y`` (0/1) and predicted probabilities ``p``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

_EPS = 1e-12


def _check(y: Sequence[int], p: Sequence[float]) -> None:
    if len(y) != len(p):
        raise ValueError(f"length mismatch: {len(y)} labels vs {len(p)} predictions")
    if not y:
        raise ValueError("no resolved rows to score")


def brier_score(y: Sequence[int], p: Sequence[float]) -> float:
    """Mean squared error between probability and outcome (lower is better)."""
    _check(y, p)
    return sum((pi - yi) ** 2 for yi, pi in zip(y, p, strict=True)) / len(y)


def log_loss(y: Sequence[int], p: Sequence[float]) -> float:
    """Binary cross-entropy (lower is better); probabilities are clipped off {0,1}."""
    _check(y, p)
    total = 0.0
    for yi, pi in zip(y, p, strict=True):
        c = min(max(pi, _EPS), 1.0 - _EPS)
        total += -(yi * math.log(c) + (1 - yi) * math.log(1.0 - c))
    return total / len(y)


def _ranks(xs: Sequence[float]) -> list[float]:
    """Average (fractional) ranks, so ties do not bias the correlation."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(a: Sequence[float], b: Sequence[float]) -> float:
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((ai - ma) * (bi - mb) for ai, bi in zip(a, b, strict=True))
    va = math.sqrt(sum((ai - ma) ** 2 for ai in a))
    vb = math.sqrt(sum((bi - mb) ** 2 for bi in b))
    if va == 0 or vb == 0:
        return float("nan")
    return cov / (va * vb)


def spearman_ic(p: Sequence[float], y: Sequence[float]) -> float:
    """Spearman rank correlation between predictions and outcomes — the information coefficient."""
    _check([int(round(v)) for v in y], p)
    return _pearson(_ranks(p), _ranks(y))


def incremental_metrics(
    y: Sequence[int],
    baseline: Sequence[float],
    candidate: Sequence[float],
) -> dict[str, float]:
    """Return candidate-minus-baseline Brier and Spearman-IC deltas."""
    return {
        "delta_brier": brier_score(y, candidate) - brier_score(y, baseline),
        "delta_ic": spearman_ic(candidate, [float(value) for value in y])
        - spearman_ic(baseline, [float(value) for value in y]),
    }


def calibration_bins(
    y: Sequence[int], p: Sequence[float], n_bins: int = 10
) -> list[dict[str, float]]:
    """Reliability-curve buckets: mean predicted vs observed frequency per probability bin."""
    _check(y, p)
    bins: list[dict[str, float]] = []
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        idx = [i for i, pi in enumerate(p) if (lo <= pi < hi) or (b == n_bins - 1 and pi == 1.0)]
        if not idx:
            continue
        bins.append({
            "lo": lo,
            "hi": hi,
            "n": float(len(idx)),
            "mean_pred": sum(p[i] for i in idx) / len(idx),
            "obs_freq": sum(y[i] for i in idx) / len(idx),
        })
    return bins

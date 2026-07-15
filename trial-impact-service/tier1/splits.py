"""Time-aware splitting and leakage checks.

Drug development is non-stationary, so random k-fold leaks the future. The only honest split
is by time: train on trials whose readout is known before a cutoff, test on those that read
out on or after it. Rows without a readout date (still in flight) are neither trained nor
tested on but are kept in the corpus for survivorship accounting.
"""

from __future__ import annotations

from datetime import date

from .schema import TrialRecord


class LeakageError(ValueError):
    """Raised when a corpus contains a row whose features postdate its readout."""


def assert_no_leakage(records: list[TrialRecord]) -> None:
    """Raise :class:`LeakageError` listing every row that uses future information."""
    bad = [(r.trial_id, reason) for r in records if (reason := r.leakage_reason())]
    if bad:
        detail = "; ".join(f"{tid}: {why}" for tid, why in bad)
        raise LeakageError(f"{len(bad)} leaking row(s): {detail}")


def time_aware_split(
    records: list[TrialRecord], cutoff: date
) -> tuple[list[TrialRecord], list[TrialRecord]]:
    """Split into ``(train, test)`` by readout date around ``cutoff``.

    * train — readout strictly before ``cutoff`` (the past we may learn from);
    * test  — readout on or after ``cutoff`` (the future we score against).

    Rows with no readout date are excluded from both (they cannot be scored yet). Leakage is
    checked first, because a leaking row poisons whichever side it lands on.
    """
    assert_no_leakage(records)
    train, test = [], []
    for r in records:
        if r.readout_date is None:
            continue
        (train if r.readout_date < cutoff else test).append(r)
    return train, test

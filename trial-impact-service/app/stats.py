"""Aggregate statistics computed from the trial-event table.

Separated from the HTTP layer so the same numbers can be reused by the JSON API,
the HTML view, and tests without duplication.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import db


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def compute_stats(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Return aggregate metrics across all tracked events.

    * ``total`` — number of events.
    * counts per status.
    * ``success_rate`` — completed / (completed + failed), over *finished* events
      only, so in-flight work doesn't drag the rate down. ``None`` when nothing
      has finished.
    * ``avg_sim_seconds`` — mean (updated_at - created_at) over completed sims;
      ``None`` when none have completed.
    * ``market_moving`` — number of completed events whose modelled call cleared
      the alert threshold (approximated by ``alert_sent``).
    """
    total = len(events)
    counts = {s: 0 for s in db.ALL_STATUSES}
    for e in events:
        counts[e["status"]] = counts.get(e["status"], 0) + 1

    completed = counts.get(db.STATUS_COMPLETED, 0)
    failed = counts.get(db.STATUS_FAILED, 0)
    finished = completed + failed
    success_rate = (completed / finished) if finished else None

    durations: list[float] = []
    for e in events:
        if e["status"] != db.STATUS_COMPLETED:
            continue
        start, end = _parse(e.get("created_at")), _parse(e.get("updated_at"))
        if start and end:
            durations.append((end - start).total_seconds())
    avg_sim = (sum(durations) / len(durations)) if durations else None

    market_moving = sum(1 for e in events if e.get("alert_sent"))

    return {
        "total": total,
        "counts": counts,
        "success_rate": success_rate,
        "avg_sim_seconds": avg_sim,
        "market_moving": market_moving,
    }

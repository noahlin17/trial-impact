"""SQLite data access layer.

A deliberately tiny, dependency-free persistence layer (standard-library
``sqlite3``, no ORM). One row per **trial event**, keyed by a synthetic
``event_id`` (``<nct_id>:<event_type>``). Re-firing the same event performs an
UPSERT rather than duplicating, which keeps the webhook safely idempotent.

JSON-valued columns (``competitor_tickers``, ``sim_result``, ``price_calls``) are
stored as TEXT and parsed back into Python objects on read, so callers and the
dashboard template never touch raw JSON strings.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Status values an event can move through. Kept as plain strings (not an enum) so
# they serialise directly to JSON, but centralised here so the rest of the code
# never types a raw status literal.
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_NEEDS_ATTENTION = "needs_attention"

ALL_STATUSES = (
    STATUS_QUEUED, STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED, STATUS_NEEDS_ATTENTION
)

# Columns holding JSON-encoded values, parsed on read.
_JSON_COLUMNS = ("competitor_tickers", "sim_result", "price_calls")


def _utcnow_iso() -> str:
    """Current UTC time as an ISO-8601 string (second precision)."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def make_event_id(nct_id: str, event_type: str) -> str:
    """Deterministic primary key for a (trial, event-kind) pair."""
    return f"{nct_id}:{event_type}"


class Database:
    """Thin wrapper around a SQLite file holding trial-impact events."""

    def __init__(self, path: str) -> None:
        self.path = path
        parent = Path(path).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a short-lived connection with row access by column name."""
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        """Create the single tracking table if it does not already exist."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trial_events (
                    event_id           TEXT PRIMARY KEY,
                    nct_id             TEXT NOT NULL,
                    sponsor            TEXT NOT NULL DEFAULT '',
                    drug               TEXT,
                    target             TEXT,
                    tissue             TEXT,
                    phase              TEXT,
                    event_type         TEXT NOT NULL,
                    endpoint_outcome   TEXT,
                    sponsor_ticker     TEXT,
                    competitor_tickers TEXT,          -- JSON list
                    devin_session_id   TEXT,
                    session_url        TEXT,
                    status             TEXT NOT NULL,
                    sim_result         TEXT,          -- JSON object
                    commentary         TEXT,
                    price_calls        TEXT,          -- JSON list
                    created_at         TEXT NOT NULL,
                    updated_at         TEXT NOT NULL,
                    error_message      TEXT,
                    -- Bookkeeping so /poll fires the market alert at most once.
                    alert_sent         INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    # --- Writes ---------------------------------------------------------------

    def upsert_new_event(
        self,
        *,
        event_id: str,
        nct_id: str,
        sponsor: str,
        drug: str | None,
        target: str | None,
        tissue: str | None,
        phase: str | None,
        event_type: str,
        endpoint_outcome: str | None,
        sponsor_ticker: str | None,
        competitor_tickers: list[dict[str, Any]] | None,
        devin_session_id: str | None,
        session_url: str | None,
        status: str,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        """Insert an event (or replace an existing one), resetting derived fields.

        Re-triggering the same event starts a fresh attempt: sim_result,
        commentary, price_calls and the alert flag are cleared.
        """
        now = _utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trial_events (
                    event_id, nct_id, sponsor, drug, target, tissue, phase,
                    event_type, endpoint_outcome, sponsor_ticker, competitor_tickers,
                    devin_session_id, session_url, status, sim_result, commentary,
                    price_calls, created_at, updated_at, error_message, alert_sent
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, 0
                )
                ON CONFLICT(event_id) DO UPDATE SET
                    sponsor            = excluded.sponsor,
                    drug               = excluded.drug,
                    target             = excluded.target,
                    tissue             = excluded.tissue,
                    phase              = excluded.phase,
                    endpoint_outcome   = excluded.endpoint_outcome,
                    sponsor_ticker     = excluded.sponsor_ticker,
                    competitor_tickers = excluded.competitor_tickers,
                    devin_session_id   = excluded.devin_session_id,
                    session_url        = excluded.session_url,
                    status             = excluded.status,
                    sim_result         = NULL,
                    commentary         = NULL,
                    price_calls        = NULL,
                    updated_at         = excluded.updated_at,
                    error_message      = excluded.error_message,
                    alert_sent         = 0
                """,
                (
                    event_id, nct_id, sponsor, drug, target, tissue, phase,
                    event_type, endpoint_outcome, sponsor_ticker,
                    json.dumps(competitor_tickers or []),
                    devin_session_id, session_url, status, now, now, error_message,
                ),
            )
        event = self.get_event(event_id)
        assert event is not None  # we just wrote it
        return event

    def update_event_status(
        self,
        *,
        event_id: str,
        status: str,
        sim_result: dict[str, Any] | None = None,
        commentary: str | None = None,
        price_calls: list[dict[str, Any]] | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update mutable fields for an event during polling."""
        now = _utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE trial_events
                   SET status        = ?,
                       sim_result    = COALESCE(?, sim_result),
                       commentary    = COALESCE(?, commentary),
                       price_calls   = COALESCE(?, price_calls),
                       error_message = ?,
                       updated_at    = ?
                 WHERE event_id       = ?
                """,
                (
                    status,
                    json.dumps(sim_result) if sim_result is not None else None,
                    commentary,
                    json.dumps(price_calls) if price_calls is not None else None,
                    error_message,
                    now,
                    event_id,
                ),
            )

    def mark_alert_sent(self, event_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE trial_events SET alert_sent = 1 WHERE event_id = ?",
                (event_id,),
            )

    # --- Reads ----------------------------------------------------------------

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM trial_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            return _hydrate(row) if row else None

    def list_events(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trial_events ORDER BY created_at DESC, event_id ASC"
            ).fetchall()
            return [_hydrate(r) for r in rows]

    def list_in_progress(self) -> list[dict[str, Any]]:
        """Events still worth polling (queued/running/needs_attention).

        A blocked session can un-block and complete, so needs_attention stays in
        the polling set.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trial_events WHERE status IN (?, ?, ?)",
                (STATUS_QUEUED, STATUS_RUNNING, STATUS_NEEDS_ATTENTION),
            ).fetchall()
            return [_hydrate(r) for r in rows]


def _hydrate(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a row to a dict, decoding the JSON-valued columns."""
    data = dict(row)
    for col in _JSON_COLUMNS:
        raw = data.get(col)
        data[col] = json.loads(raw) if raw else None
    return data

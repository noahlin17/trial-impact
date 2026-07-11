#!/usr/bin/env python3
"""ClinicalTrials.gov watcher — polls, diffs, and emits signed webhooks.

ClinicalTrials.gov has no push/webhook mechanism, so this small service provides
one. On each cycle it:

1. **Polls** the ClinicalTrials.gov API v2 for every trial in ``watchlist.json``.
2. **Diffs** the live record against the last-seen state in a tiny SQLite store.
3. On a **material change** — results posted, overall-status change, or phase
   change — **emits** an HMAC-signed ``POST /webhook/trial-update`` to the
   trial-impact service.

Static per-trial metadata that ClinicalTrials.gov does not expose in a
machine-readable way (the molecular ``target``, the ``tissue`` of interest, dose,
and — for a demo — the ``endpoint_outcome``) is supplied by ``watchlist.json`` and
merged into the emitted payload.

Usage:
    python watcher.py --once            # single cycle (CI / cron)
    python watcher.py                    # loop forever every POLL_INTERVAL_SECONDS
    python watcher.py --once --emit-initial   # also emit on first sighting
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time

import requests
from signing import SIGNATURE_HEADER, sign

CTGOV_API = "https://clinicaltrials.gov/api/v2/studies"
_HTTP_TIMEOUT = 30


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
class Config:
    def __init__(self) -> None:
        self.main_service_url = os.environ.get(
            "MAIN_SERVICE_URL", "http://localhost:8000"
        ).rstrip("/")
        self.shared_secret = os.environ.get("WATCHER_SHARED_SECRET", "")
        self.watchlist_path = os.environ.get("WATCHLIST_PATH", "watchlist.json")
        self.state_path = os.environ.get("STATE_PATH", "watcher_state.db")
        self.poll_interval = int(os.environ.get("POLL_INTERVAL_SECONDS", "3600"))


# --------------------------------------------------------------------------- #
# State store
# --------------------------------------------------------------------------- #
class StateStore:
    """Last-seen snapshot per NCT, so we can detect changes between cycles."""

    def __init__(self, path: str) -> None:
        self.path = path
        with self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS study_state (
                    nct_id         TEXT PRIMARY KEY,
                    overall_status TEXT,
                    phase          TEXT,
                    has_results    INTEGER,
                    last_update    TEXT
                )
                """
            )

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def get(self, nct_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM study_state WHERE nct_id = ?", (nct_id,)
            ).fetchone()
            return dict(row) if row else None

    def put(self, nct_id: str, snap: dict) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO study_state (nct_id, overall_status, phase, has_results, last_update)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(nct_id) DO UPDATE SET
                    overall_status = excluded.overall_status,
                    phase          = excluded.phase,
                    has_results    = excluded.has_results,
                    last_update    = excluded.last_update
                """,
                (
                    nct_id,
                    snap["overall_status"],
                    snap["phase"],
                    int(snap["has_results"]),
                    snap["last_update"],
                ),
            )


# --------------------------------------------------------------------------- #
# ClinicalTrials.gov fetch + parse
# --------------------------------------------------------------------------- #
def fetch_study(nct_id: str) -> dict:
    """Fetch one study record from the CT.gov v2 API."""
    resp = requests.get(f"{CTGOV_API}/{nct_id}", timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def parse_snapshot(study: dict) -> dict:
    """Extract the fields we diff + report from a CT.gov v2 study record."""
    proto = study.get("protocolSection", {})
    status = proto.get("statusModule", {})
    design = proto.get("designModule", {})
    sponsor_mod = proto.get("sponsorCollaboratorsModule", {})
    arms = proto.get("armsInterventionsModule", {})

    interventions = arms.get("interventions", []) or []
    drug = next(
        (i.get("name") for i in interventions if i.get("type", "").upper() == "DRUG"),
        interventions[0].get("name") if interventions else None,
    )

    return {
        "overall_status": status.get("overallStatus"),
        "phase": ",".join(design.get("phases", []) or []) or None,
        "has_results": bool(study.get("hasResults")),
        "last_update": (status.get("lastUpdatePostDateStruct", {}) or {}).get("date"),
        "sponsor": (sponsor_mod.get("leadSponsor", {}) or {}).get("name"),
        "drug": drug,
    }


# --------------------------------------------------------------------------- #
# Diff → event
# --------------------------------------------------------------------------- #
def detect_event(prev: dict | None, curr: dict, emit_initial: bool) -> str | None:
    """Return an event_type for a material change, or None if nothing changed."""
    if prev is None:
        return "initial_snapshot" if emit_initial else None
    if not prev["has_results"] and curr["has_results"]:
        return "results_posted"
    if prev["overall_status"] != curr["overall_status"]:
        return "status_change"
    if prev["phase"] != curr["phase"]:
        return "phase_change"
    return None


def build_payload(nct_id: str, event_type: str, snap: dict, meta: dict) -> dict:
    """Merge live CT.gov data with static watchlist metadata into a webhook body."""
    return {
        "event_type": event_type,
        "nct_id": nct_id,
        "sponsor": meta.get("sponsor") or snap.get("sponsor") or "",
        "drug": meta.get("drug") or snap.get("drug"),
        "target": meta.get("target"),
        "tissue": meta.get("tissue"),
        "phase": snap.get("phase"),
        "overall_status": snap.get("overall_status"),
        # CT.gov does not expose a machine-readable pass/fail; enrichment supplies
        # it for the demo, otherwise it is 'unknown'.
        "endpoint_outcome": meta.get("endpoint_outcome", "unknown"),
        "dose_mg": meta.get("dose_mg"),
        "raw": snap,
    }


def emit(cfg: Config, payload: dict) -> int:
    """POST a signed payload to the trial-impact service; return the status code."""
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if cfg.shared_secret:
        headers[SIGNATURE_HEADER] = sign(cfg.shared_secret, body)
    resp = requests.post(
        f"{cfg.main_service_url}/webhook/trial-update",
        data=body,
        headers=headers,
        timeout=_HTTP_TIMEOUT,
    )
    return resp.status_code


# --------------------------------------------------------------------------- #
# Cycle
# --------------------------------------------------------------------------- #
def run_once(cfg: Config, store: StateStore, emit_initial: bool = False) -> list[dict]:
    """One poll/diff/emit cycle across the whole watchlist."""
    with open(cfg.watchlist_path) as fh:
        watchlist = json.load(fh)

    results: list[dict] = []
    for entry in watchlist:
        nct_id = entry["nct_id"]
        try:
            snap = parse_snapshot(fetch_study(nct_id))
        except requests.RequestException as exc:
            results.append({"nct_id": nct_id, "error": str(exc)})
            continue

        prev = store.get(nct_id)
        event_type = detect_event(prev, snap, emit_initial)
        if event_type and event_type != "initial_snapshot":
            code = emit(cfg, build_payload(nct_id, event_type, snap, entry))
            results.append({"nct_id": nct_id, "event": event_type, "http": code})
        elif event_type == "initial_snapshot":
            code = emit(cfg, build_payload(nct_id, "results_posted", snap, entry))
            results.append({"nct_id": nct_id, "event": "initial", "http": code})
        else:
            results.append({"nct_id": nct_id, "event": None})

        store.put(nct_id, snap)  # always advance the baseline

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    parser.add_argument(
        "--emit-initial",
        action="store_true",
        help="Emit an event the first time a trial is seen (default: just baseline)",
    )
    args = parser.parse_args(argv)

    cfg = Config()
    store = StateStore(cfg.state_path)

    def cycle():
        for r in run_once(cfg, store, emit_initial=args.emit_initial):
            print(json.dumps(r), flush=True)

    if args.once:
        cycle()
        return 0

    print(f"[watcher] polling every {cfg.poll_interval}s → {cfg.main_service_url}")
    while True:
        try:
            cycle()
        except Exception as exc:  # noqa: BLE001 — keep the loop alive
            print(json.dumps({"error": str(exc)}), file=sys.stderr, flush=True)
        time.sleep(cfg.poll_interval)


if __name__ == "__main__":
    raise SystemExit(main())

"""End-to-end tests: webhook -> poll -> score -> alert, with in-memory fakes.

The Devin client and the alerter are replaced with fakes so the tests run offline
and deterministically — no network, no real API keys, and no biophysics (the real
simulation runs inside a Devin session, which these tests stand in for).
"""

from __future__ import annotations

import json

import pytest

from app import create_app, market_model
from app.config import Config
from app.db import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_NEEDS_ATTENTION,
    STATUS_QUEUED,
    STATUS_RUNNING,
    Database,
    make_event_id,
)
from app.devin_client import SessionStatus, extract_sim_result
from app.signing import SIGNATURE_HEADER, sign, verify

SECRET = "topsecret"

TICKERS = {
    "amgen": {
        "ticker": "AMGN",
        "name": "Amgen",
        "competitors": [{"ticker": "REGN", "name": "Regeneron"}],
    }
}

STRONG_WIN = {
    "target": "KRAS",
    "drug": "sotorasib",
    "binding_affinity_kcal_mol": -9.5,
    "kd_nM": 90.0,
    "target_occupancy_pct": 80.0,
    "tox_flag": False,
    "confidence": 0.9,
}


class FakeDevin:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self._next: dict[str, SessionStatus] = {}
        self._counter = 0

    def create_session(self, *, prompt, title, tags=None):
        self._counter += 1
        sid = f"devin-{self._counter}"
        self.created.append({"prompt": prompt, "title": title, "tags": tags, "id": sid})

        class _Created:
            session_id = sid
            url = f"https://app.devin.ai/sessions/{sid}"

        return _Created()

    def script(self, session_id: str, status: SessionStatus) -> None:
        self._next[session_id] = status

    def get_session(self, session_id: str) -> SessionStatus:
        return self._next[session_id]


class FakeAlerter:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def notify(self, event, assessment):
        self.sent.append({"event": event, "assessment": assessment})
        return ["slack"]


@pytest.fixture
def ctx(tmp_path):
    cfg = Config(
        devin_api_key="test-devin",
        devin_api_base="http://devin.test",
        sim_repo_url="https://example.test/repo",
        watcher_shared_secret=SECRET,
        slack_webhook_url="",
        smtp_host="", smtp_port=587, smtp_user="", smtp_password="",
        email_from="", email_to="",
        tickers_path="tickers.json",
        market_moving_threshold=0.10,
        database_path=str(tmp_path / "test.db"),
    )
    devin, alerter = FakeDevin(), FakeAlerter()
    db = Database(cfg.database_path)
    app = create_app(cfg, db=db, devin=devin, alerter=alerter, tickers=TICKERS)
    app.testing = True
    return app.test_client(), devin, alerter, db


def _payload(nct: str = "NCT001", outcome: str = "met", **over) -> dict:
    base = {
        "event_type": "results_posted",
        "nct_id": nct,
        "sponsor": "Amgen",
        "drug": "sotorasib",
        "target": "KRAS",
        "tissue": "tumor",
        "phase": "PHASE3",
        "endpoint_outcome": outcome,
        "dose_mg": 960,
    }
    base.update(over)
    return base


def _post(client, payload: dict, sign_it: bool = True):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if sign_it:
        headers[SIGNATURE_HEADER] = sign(SECRET, body)
    return client.post("/webhook/trial-update", data=body, headers=headers)


# --- signing ---------------------------------------------------------------- #
def test_signing_roundtrip():
    body = b'{"a":1}'
    assert verify(SECRET, body, sign(SECRET, body))
    assert not verify(SECRET, body, "sha256=deadbeef")
    assert not verify(SECRET, body, None)


# --- webhook ---------------------------------------------------------------- #
def test_webhook_creates_session_and_persists(ctx):
    client, devin, _alerter, _db = ctx
    resp = _post(client, _payload())
    assert resp.status_code == 201
    event = resp.get_json()["event"]
    assert event["nct_id"] == "NCT001"
    assert event["status"] == STATUS_QUEUED
    assert event["devin_session_id"] == "devin-1"
    assert event["sponsor_ticker"] == "AMGN"
    # Prompt should reference the target + drug so the sim is well-specified.
    assert "KRAS" in devin.created[0]["prompt"]
    assert "sotorasib" in devin.created[0]["prompt"]


def test_webhook_rejects_bad_signature(ctx):
    client, _devin, _alerter, _db = ctx
    body = json.dumps(_payload()).encode()
    resp = client.post(
        "/webhook/trial-update",
        data=body,
        headers={"Content-Type": "application/json", SIGNATURE_HEADER: "sha256=bad"},
    )
    assert resp.status_code == 401


def test_webhook_rejects_missing_nct(ctx):
    client, _devin, _alerter, _db = ctx
    resp = _post(client, {"event_type": "results_posted", "sponsor": "Amgen"})
    assert resp.status_code == 400


def test_webhook_idempotent_per_event(ctx):
    client, devin, _alerter, _db = ctx
    _post(client, _payload("NCT777"))
    _post(client, _payload("NCT777"))
    events = client.get("/status?format=json").get_json()["events"]
    match = [e for e in events if e["nct_id"] == "NCT777"]
    assert len(match) == 1  # one row
    assert len(devin.created) == 2  # fresh session each time


# --- poll: completion, scoring, alerting ------------------------------------ #
def test_poll_scores_and_alerts_once(ctx):
    client, devin, alerter, db = ctx
    _post(client, _payload("NCT001", "met"))

    devin.script(
        "devin-1",
        SessionStatus("finished", STATUS_COMPLETED, dict(STRONG_WIN), None),
    )
    resp = client.post("/poll")
    assert resp.status_code == 200

    event = db.get_event(make_event_id("NCT001", "results_posted"))
    assert event["status"] == STATUS_COMPLETED
    # Sponsor up, competitor down.
    calls = {c["ticker"]: c for c in event["price_calls"]}
    assert calls["AMGN"]["direction"] == "up"
    assert calls["REGN"]["direction"] == "down"
    assert event["sim_result"]["kd_nM"] == 90.0
    # One alert fired.
    assert len(alerter.sent) == 1

    # Re-poll must NOT double-alert (idempotent reconcile).
    devin.script(
        "devin-1",
        SessionStatus("finished", STATUS_COMPLETED, dict(STRONG_WIN), None),
    )
    client.post("/poll")
    assert len(alerter.sent) == 1


def test_poll_running_then_failed(ctx):
    client, devin, _alerter, db = ctx
    _post(client, _payload("NCT002"))
    eid = make_event_id("NCT002", "results_posted")

    devin.script("devin-1", SessionStatus("working", STATUS_RUNNING, None, None))
    client.post("/poll")
    assert db.get_event(eid)["status"] == STATUS_RUNNING

    devin.script(
        "devin-1",
        SessionStatus("expired", STATUS_FAILED, None, "Devin session ended in status 'expired'"),
    )
    client.post("/poll")
    ev = db.get_event(eid)
    assert ev["status"] == STATUS_FAILED
    assert "expired" in ev["error_message"]


def test_blocked_without_result_is_needs_attention_then_completes(ctx):
    client, devin, alerter, db = ctx
    _post(client, _payload("NCT003"))
    eid = make_event_id("NCT003", "results_posted")

    devin.script("devin-1", SessionStatus("blocked", STATUS_NEEDS_ATTENTION, None, None))
    client.post("/poll")
    assert db.get_event(eid)["status"] == STATUS_NEEDS_ATTENTION
    assert alerter.sent == []
    # Still pollable so a later unblock is picked up.
    assert any(e["event_id"] == eid for e in db.list_in_progress())

    devin.script(
        "devin-1",
        SessionStatus("finished", STATUS_COMPLETED, dict(STRONG_WIN), None),
    )
    client.post("/poll")
    assert db.get_event(eid)["status"] == STATUS_COMPLETED
    assert len(alerter.sent) == 1


def test_status_stats(ctx):
    client, devin, _alerter, _db = ctx
    _post(client, _payload("NCT010"))
    _post(client, _payload("NCT011"))

    devin.script("devin-1", SessionStatus("finished", STATUS_COMPLETED, dict(STRONG_WIN), None))
    devin.script("devin-2", SessionStatus("expired", STATUS_FAILED, None, "failed"))
    client.post("/poll")

    stats = client.get("/status?format=json").get_json()["stats"]
    assert stats["total"] == 2
    assert stats["counts"]["completed"] == 1
    assert stats["counts"]["failed"] == 1
    assert stats["success_rate"] == 0.5
    assert stats["market_moving"] == 1


# --- market model unit ------------------------------------------------------ #
def test_market_model_met_vs_missed():
    ev_met = {"nct_id": "N", "endpoint_outcome": "met", "target": "KRAS", "sponsor": "Amgen"}
    ev_miss = {"nct_id": "N", "endpoint_outcome": "missed", "target": "KRAS", "sponsor": "Amgen"}
    assert market_model.pos_delta(ev_met, STRONG_WIN) > 0.3
    assert market_model.pos_delta(ev_miss, STRONG_WIN) < 0

    a = market_model.assess(ev_met, STRONG_WIN, "AMGN", "Amgen",
                            [{"ticker": "REGN", "name": "Regeneron"}])
    sponsor = next(c for c in a["price_calls"] if c["role"] == "sponsor")
    comp = next(c for c in a["price_calls"] if c["role"] == "competitor")
    assert sponsor["direction"] == "up"
    assert comp["direction"] == "down"
    assert a["market_moving"] is True
    assert "NOT investment advice" in a["commentary"]


def test_extract_ignores_prompt_echo_and_takes_last_result():
    """Regression: the transcript includes our prompt (which embeds an EXAMPLE
    SIM_RESULT_JSON). The extractor must skip that echo and return Devin's real,
    final result — the exact bug seen in the first live Devin run."""
    example = '{"binding_affinity_kcal_mol": -9.2, "kd_nM": 180.4}'  # from the prompt
    real = '{"binding_affinity_kcal_mol": -8.585, "kd_nM": 892.54, "tox_flag": true}'
    data = {
        "status_enum": "blocked",
        "structured_output": None,
        "messages": [
            {"type": "initial_user_message", "message": f"...prompt... SIM_RESULT_JSON: {example}"},
            {"type": "devin_message", "message": "Starting the run..."},
            {"type": "devin_message", "message": f"Done for real.\nSIM_RESULT_JSON: {real}"},
        ],
    }
    out = extract_sim_result(data)
    assert out["kd_nM"] == 892.54  # Devin's real value, NOT the prompt example 180.4
    assert out["tox_flag"] is True


def test_market_model_handles_missing_sim():
    ev = {"nct_id": "N", "endpoint_outcome": "met", "target": "X", "sponsor": "Amgen"}
    # No physics available — still directional, at reduced conviction.
    d = market_model.pos_delta(ev, None)
    assert 0 < d < market_model.pos_delta(ev, STRONG_WIN)

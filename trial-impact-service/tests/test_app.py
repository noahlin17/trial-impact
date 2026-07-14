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

# A full sim_result (with the fields pkpd_curve + the dashboard need).
RICH_SIM = {
    "target": "KRAS", "drug": "sotorasib", "tissue": "tumor", "dose_mg": 960.0,
    "binding_affinity_kcal_mol": -8.585, "kd_nM": 892.54,
    "cmax_ng_ml": 19259.45, "auc_ng_h_ml": 143963.8,
    "target_occupancy_pct": 97.47, "tox_flag": True, "confidence": 0.9,
    "provenance": {
        "uniprot": "P01116", "structure_source": "RCSB", "pdb_id": "7VVB",
        "smiles": "C[C@H]1CN(...)C(=O)C=C",
        "descriptors": {"mw": 560.6, "logp": 5.3, "hbd": 1, "hba": 6, "tpsa": 102.2},
    },
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
        sim_repo_commit="a" * 40,
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


def test_missed_trial_tox_increases_downside():
    """A tox flag must make a *failed* trial worse, never better — and molecular
    potency must not rescue a miss (efficacy modifiers drop out for a miss)."""
    ev_miss = {"nct_id": "N", "endpoint_outcome": "missed", "target": "KRAS", "sponsor": "Amgen"}
    tox_sim = dict(RICH_SIM)                      # tox_flag True, potent binder
    clean_sim = {**RICH_SIM, "tox_flag": False}
    d_tox = market_model.pos_delta(ev_miss, tox_sim)
    d_clean = market_model.pos_delta(ev_miss, clean_sim)
    assert d_tox < d_clean < 0                    # tox deepens the downside
    b = market_model.pos_breakdown(ev_miss, clean_sim)
    assert b["binding_modifier"] == 0.0 and b["occupancy_modifier"] == 0.0


def test_met_trial_unchanged_by_fix():
    """Regression guard: the fix must not move the met-trial numbers (the demo runs
    are both 'met')."""
    ev_met = {"nct_id": "N", "endpoint_outcome": "met", "target": "KRAS", "sponsor": "Amgen"}
    b = market_model.pos_breakdown(ev_met, RICH_SIM)
    # met: base .5, binding 0 (dg -8.585, kd 892 -> neither potent nor weak),
    # occ +.15 (97%), tox -.15 (flag) -> subtotal .5 ; scale .95 -> .475
    assert round(b["subtotal"], 3) == 0.5
    assert abs(b["final"] - 0.475) < 1e-9


def test_unknown_outcome_does_not_emit_a_call_on_chemistry_alone():
    """No readout means no call.

    `unknown` is the default for every trial the watchlist has not enriched, so this
    is the *common* path in production. A tox flag alone used to score
    -0.15 × 0.95 = -0.1425, clear the 0.10 market-moving threshold, and emit a "down"
    call on a trial that had reported nothing — a spurious alert on the majority path.
    """
    ev = {"nct_id": "N", "endpoint_outcome": "unknown", "target": "KRAS", "sponsor": "Amgen"}
    b = market_model.pos_breakdown(ev, RICH_SIM)   # RICH_SIM carries tox_flag=True

    assert b["outcome_base"] == 0.0
    assert b["tox_penalty"] == 0.0                 # was -0.15
    assert b["final"] == 0.0                       # was -0.1425
    assert abs(market_model.pos_delta(ev, RICH_SIM)) < 0.10   # below the threshold

    out = market_model.assess(ev, RICH_SIM, "AMGN", "Amgen", [], threshold=0.10)
    assert out["price_calls"] == [] or all(
        c["direction"] == "flat" for c in out["price_calls"]
    )


def test_market_model_handles_missing_sim():
    ev = {"nct_id": "N", "endpoint_outcome": "met", "target": "X", "sponsor": "Amgen"}
    # No physics available — still directional, at reduced conviction.
    d = market_model.pos_delta(ev, None)
    assert 0 < d < market_model.pos_delta(ev, STRONG_WIN)


# --- reasoning trace: breakdown must reduce exactly to the delta ------------- #
def test_pos_breakdown_reduces_to_delta():
    for outcome in ("met", "missed", "unknown"):
        ev = {"nct_id": "N", "endpoint_outcome": outcome, "target": "KRAS", "sponsor": "Amgen"}
        for sim in (RICH_SIM, STRONG_WIN, {"error": "boom"}, None):
            b = market_model.pos_breakdown(ev, sim)
            # exact invariants on the raw components
            assert abs(
                b["outcome_base"] + b["binding_modifier"]
                + b["occupancy_modifier"] + b["tox_penalty"] - b["subtotal"]
            ) < 1e-12
            assert abs(b["final"] - market_model.pos_delta(ev, sim)) < 1e-12
            # display components sum to the final (within rounding)
            assert abs(sum(c["value"] for c in b["components"]) - b["final"]) < 5e-3


# --- PK/PD curve reconstruction (stdlib Bateman) ---------------------------- #
def test_pkpd_curve_shape():
    from app.simulation import pkpd_curve

    c = pkpd_curve(RICH_SIM)
    assert set(c) == {"t_h", "conc_ng_ml", "occupancy_pct"}
    assert len(c["t_h"]) == 97
    assert c["t_h"][0] == 0.0 and c["conc_ng_ml"][0] == 0.0  # nothing absorbed at t=0
    assert all(0.0 <= o <= 100.0 for o in c["occupancy_pct"])
    peak = c["conc_ng_ml"].index(max(c["conc_ng_ml"]))
    assert 0 < peak < 96  # rise then decay, not monotonic to an endpoint
    assert pkpd_curve({"kd_nM": 1}) is None  # missing dose / MW -> no curve


# --- covalent-warhead detection ---------------------------------------------- #
# SMILES inlined (no network). Skipped unless RDKit is present — it ships in
# requirements-sim.txt and normally runs inside the Devin sandbox, not the web tier.
_COVALENT_CASES = [
    # (name, SMILES, is_covalent)
    ("sotorasib", "C[C@H]1CN(CCN1C2=NC(=O)N(C3=NC(=C(C=C32)F)C4=C(C=CC=C4F)O)"
                  "C5=C(C=CN=C5C(C)C)C)C(=O)C=C", True),   # acrylamide warhead
    ("osimertinib", "CN(C)CCN(C)C1=C(C=CC(=C1)NC(=O)C=C)NC2=NC=CC(=N2)C3=CN(C4=CC=CC=C43)C",
     True),                                                 # acrylamide warhead
    ("ivacaftor", "CC(C)(C)C1=CC(=C(C=C1NC(=O)C2=CNC3=CC=CC=C3C2=O)O)C(C)(C)C",
     False),                                                # reversible potentiator
    ("imatinib", "CC1=C(C=C(C=C1)NC(=O)C2=CC=C(C=C2)CN3CCN(CC3)C)NC4=NC=CC(=N4)C5=CN=CC=C5",
     False),                                                # reversible
]


@pytest.mark.parametrize("name,smiles,expected", _COVALENT_CASES)
def test_detect_covalent(name, smiles, expected):
    """The warhead SMARTS must require an *acyclic* Michael acceptor.

    Regression: a bare `C=CC(=O)N` flagged ivacaftor (reversible) as covalent, because
    embed_ligand kekulizes its 4-oxoquinoline ring and the ring's own C=C then matched.
    This runs the real path (embed_ligand -> detect_covalent), since the bug only
    appears after embedding.
    """
    pytest.importorskip("rdkit")
    from app.simulation import detect_covalent, embed_ligand

    assert detect_covalent(embed_ligand(smiles)) is expected, name


# --- prompt: pinned commit, no embedded source ------------------------------- #
def _build_prompt(**over):
    from app.prompts import build_simulation_prompt

    kwargs = {
        "event": {"nct_id": "NCT1", "target": "KRAS", "drug": "sotorasib",
                  "tissue": "tumor", "dose_mg": 960, "sponsor": "Amgen"},
        "sim_repo_url": "https://github.com/noahlin17/trial-impact",
        "sim_repo_commit": "c0ffee1234567890c0ffee1234567890c0ffee12",
        "estimator": "vina-docking-pkpd@1",
    }
    kwargs.update(over)
    return build_simulation_prompt(**kwargs)


def test_prompt_clones_pinned_commit_not_embedded_source():
    """The pipeline is now *cloned at a pinned commit*, not embedded, so the prompt
    stays small and reproducibility is verifiable against the commit."""
    from app.prompts import MAX_PROMPT_CHARS

    commit = "c0ffee1234567890c0ffee1234567890c0ffee12"
    prompt = _build_prompt(sim_repo_commit=commit)

    assert len(prompt) <= MAX_PROMPT_CHARS
    # Clones + checks out the pinned commit...
    assert "git clone" in prompt and f"git checkout {commit}" in prompt
    # ...runs the selected estimator...
    assert '--estimator "vina-docking-pkpd@1"' in prompt
    # ...must disclose any in-sandbox patch...
    assert "code_patched" in prompt
    # ...and does NOT embed the pipeline source any more (that was the 30k ceiling).
    assert "def run_simulation(" not in prompt


def test_prompt_requires_a_pinned_commit():
    """A blank commit is an unreproducible run — building the prompt must refuse."""
    with pytest.raises(ValueError, match="sim_repo_commit is required"):
        _build_prompt(sim_repo_commit="")


# --- estimators: the harness/estimator boundary ------------------------------ #
def test_estimator_registry_and_default():
    from app.estimators import (
        DEFAULT_ESTIMATOR_ID,
        get_estimator,
        list_estimators,
    )
    from app.simulation import VINA_ESTIMATOR_ID

    ids = list_estimators()
    # Two implementations ship: the real docking pipeline + a labelled control.
    assert VINA_ESTIMATOR_ID in ids
    assert "ligand-efficiency-baseline@1" in ids
    # The default is the real pipeline (so existing behaviour is unchanged).
    assert DEFAULT_ESTIMATOR_ID == VINA_ESTIMATOR_ID
    # Every registered estimator stamps its own id onto results it makes, and
    # the lookup round-trips.
    for est_id in ids:
        assert get_estimator(est_id).id == est_id
    with pytest.raises(KeyError, match="unknown estimator"):
        get_estimator("does-not-exist@9")


def test_webhook_rejects_unknown_estimator(ctx):
    client, _devin, _alerter, _db = ctx
    resp = _post(client, _payload("NCT-EST", estimator="nope@1"))
    assert resp.status_code == 400
    assert "unknown estimator" in resp.get_json()["error"]


def test_webhook_estimator_selects_and_keys_the_event(ctx):
    client, devin, _alerter, db = ctx
    est = "ligand-efficiency-baseline@1"
    resp = _post(client, _payload("NCT-EST2", estimator=est))
    assert resp.status_code == 201
    event = resp.get_json()["event"]
    # An explicit estimator suffixes the key so it can coexist with the default run.
    assert event["event_id"] == make_event_id("NCT-EST2", "results_posted", est)
    assert db.get_event(event["event_id"]) is not None
    # The prompt tells the session to run that estimator, and to clone the pinned commit.
    prompt = devin.created[0]["prompt"]
    assert f'--estimator "{est}"' in prompt
    assert "git checkout" in prompt


def test_webhook_refuses_unpinned_run(tmp_path):
    """No SIM_REPO_COMMIT -> the run is not reproducible; refuse it, visibly."""
    cfg = Config(
        devin_api_key="test-devin", devin_api_base="http://devin.test",
        sim_repo_url="https://example.test/repo", sim_repo_commit="",
        watcher_shared_secret=SECRET,
        slack_webhook_url="", smtp_host="", smtp_port=587, smtp_user="",
        smtp_password="", email_from="", email_to="",
        tickers_path="tickers.json", market_moving_threshold=0.10,
        database_path=str(tmp_path / "unpinned.db"),
    )
    devin, alerter = FakeDevin(), FakeAlerter()
    app = create_app(cfg, db=Database(cfg.database_path), devin=devin,
                     alerter=alerter, tickers=TICKERS)
    app.testing = True
    resp = _post(app.test_client(), _payload("NCT-UNPINNED"))
    assert resp.status_code == 503
    assert "SIM_REPO_COMMIT" in resp.get_json()["error"]
    # Nothing was launched, and the failure is recorded (not silently dropped).
    assert devin.created == []
    assert resp.get_json()["event"]["status"] == STATUS_FAILED


def test_cli_dispatches_through_the_estimator_registry(monkeypatch):
    """`python -m app.simulation --estimator X` must route to estimator X."""
    import app.estimators as estimators
    from app.simulation import SimResult, main

    seen = {}

    class _Spy:
        id = "spy@1"

        def run(self, *, target, drug, tissue, dose_mg, uniprot=None):
            seen.update(target=target, drug=drug, estimator=self.id)
            return SimResult(target=target, drug=drug, tissue=tissue,
                             dose_mg=dose_mg, estimator=self.id)

    monkeypatch.setitem(estimators.REGISTRY, "spy@1", _Spy())
    rc = main(["--target", "KRAS", "--drug", "sotorasib", "--estimator", "spy@1"])
    assert rc == 0
    assert seen == {"target": "KRAS", "drug": "sotorasib", "estimator": "spy@1"}


def test_analysis_estimator_head_to_head(ctx):
    """Two estimators on one trial produce a side-by-side comparison entry."""
    from app import analysis

    _client, _devin, _alerter, db = ctx

    def _row(nct, est, dg, occ):
        sim = {**RICH_SIM, "binding_affinity_kcal_mol": dg,
               "target_occupancy_pct": occ, "estimator": est}
        eid = make_event_id(nct, "results_posted", est)
        db.upsert_new_event(
            event_id=eid, nct_id=nct, sponsor="Amgen", drug="sotorasib",
            target="KRAS", tissue="tumor", phase="PHASE3", event_type="results_posted",
            endpoint_outcome="met", sponsor_ticker="AMGN", competitor_tickers=[],
            devin_session_id=None, session_url=None, status=STATUS_QUEUED,
        )
        db.update_event_status(event_id=eid, status=STATUS_COMPLETED, sim_result=sim)

    _row("NCT-H2H", "vina-docking-pkpd@1", -8.6, 97.5)
    _row("NCT-H2H", "ligand-efficiency-baseline@1", -7.5, 88.0)
    _row("NCT-SOLO", "vina-docking-pkpd@1", -9.1, 80.0)

    payload = analysis.build_payload(db.list_events())
    trials = payload["comparison"]["trials"]
    # Only the trial with two estimators is a head-to-head; the solo one is omitted.
    assert len(trials) == 1
    t = trials[0]
    assert t["nct_id"] == "NCT-H2H"
    assert [a["estimator"] for a in t["arms"]] == [
        "ligand-efficiency-baseline@1", "vina-docking-pkpd@1"
    ]
    assert t["dg_spread"] == pytest.approx(1.1, abs=1e-6)


# --- docking box + pose capture (pure parsing; no RDKit/Vina needed) --------- #
def _pdb_line(rec, serial, name, resn, x, y, z, elem):
    """Build one fixed-column PDB record (the parsers read by column offset)."""
    return (
        f"{rec:<6}{serial:>5} {name:^4}{'':1}{resn:>3} A{1:>4}{'':4}"
        f"{x:>8.3f}{y:>8.3f}{z:>8.3f}{1.0:>6.2f}{0.0:>6.2f}{'':10}{elem:>2}\n"
    )


def _holo_pdb(n_ligand_atoms=8):
    """A receptor with waters, an ion, and one drug-like co-crystal ligand at x≈10."""
    out = [_pdb_line("ATOM", i, "CA", "ALA", 0.0, 0.0, float(i), "C") for i in range(5)]
    out.append(_pdb_line("HETATM", 90, "O", "HOH", 5.0, 5.0, 5.0, "O"))
    out.append(_pdb_line("HETATM", 91, "ZN", "ZN", 6.0, 6.0, 6.0, "ZN"))
    out += [
        _pdb_line("HETATM", 100 + i, "C1", "LIG", 10.0, 2.0, 3.0, "C")
        for i in range(n_ligand_atoms)
    ]
    return "".join(out)


def test_docking_box_is_blind_not_ligand_centered(tmp_path):
    """The box is deliberately blind (see README: pocket-focused boxing was reverted
    because the largest co-crystal ligand is not necessarily the drug's pocket).

    On a receptor small enough that the 40 Å cap does not bind, the box encloses
    every atom rather than parking on the co-crystal ligand (x≈10) and excluding the
    rest of the receptor (x≈0).
    """
    pytest.importorskip("numpy")
    from app.simulation import compute_docking_box

    p = tmp_path / "holo.pdb"
    p.write_text(_holo_pdb())
    center, size = compute_docking_box(str(p))

    lo, hi = center[0] - size[0] / 2, center[0] + size[0] / 2
    assert lo <= 0.0 and hi >= 10.0     # spans protein (x=0) *and* ligand (x=10)
    assert size != [22.5, 22.5, 22.5]   # not the reverted ligand-centered box
    assert max(size) < 40.0             # the cap is NOT what produced this coverage


def test_docking_box_stops_covering_the_receptor_once_the_40A_cap_binds(tmp_path):
    """KNOWN ISSUE (README → Limitations → "Docking box"): the box is capped at 40 Å
    but stays centered on the centroid, so on any receptor larger than ~40 Å it
    silently searches a central slab instead of the protein.

    This is a characterization test: it pins the *current, wrong* behaviour so that a
    future fix has to delete it deliberately rather than a "coverage" test passing by
    accident. The old test asserted coverage on a ~10 Å toy receptor — the one input
    where the cap can never trigger — so it could never have caught this.

    Real measurements from the two published runs (reproduce with
    ``python verify_docking_box.py``):

        KRAS 7VVB          extent  56 x  55 x  44 Å  ->  ~80% of atoms in the box
        CFTR AF-P13569-F1  extent 139 x 117 x 147 Å  ->  ~19% of atoms in the box
    """
    pytest.importorskip("numpy")
    from app.simulation import compute_docking_box

    # A 100 Å extended receptor — the scale of a real multi-domain membrane protein.
    atoms = [
        _pdb_line("ATOM", i, "CA", "ALA", float(i), 0.0, 0.0, "C") for i in range(101)
    ]
    p = tmp_path / "big.pdb"
    p.write_text("".join(atoms))

    center, size = compute_docking_box(str(p))

    assert size[0] == 40.0              # the cap is binding, not the 108 Å true extent
    lo, hi = center[0] - size[0] / 2, center[0] + size[0] / 2
    inside = sum(1 for i in range(101) if lo <= float(i) <= hi)

    # The receptor is NOT covered: the box holds a ~40% central slab and Vina never
    # sees the other 60% — including, on a real target, the actual binding pocket.
    assert inside < 101
    assert inside / 101 < 0.5


# --- analysis payload + route ----------------------------------------------- #
def test_analysis_payload_and_route(ctx):
    client, devin, _alerter, _db = ctx
    for nct in ("NCTA", "NCTB"):
        _post(client, _payload(nct))
    devin.script("devin-1", SessionStatus("finished", STATUS_COMPLETED, dict(RICH_SIM), None))
    devin.script("devin-2", SessionStatus("finished", STATUS_COMPLETED, dict(RICH_SIM), None))
    client.post("/poll")

    payload = client.get("/analysis.json").get_json()
    assert payload["summary"]["analyzed"] == 2
    assert payload["summary"]["tox_rate"] == 1.0
    assert len(payload["relationships"]["points"]) == 2
    run = payload["runs"][0]
    assert run["detail"]["pkpd_curve"] is not None
    assert "components" in run["detail"]["pos_breakdown"]

    html = client.get("/analysis", headers={"Accept": "text/html"}).data.decode()
    assert "Results Analysis" in html and "detail-waterfall" in html

#!/usr/bin/env python3
"""Regenerate the committed results/ artifacts from the real pipeline.

Runs the *actual* committed estimator (real structure fetch, real AutoDock Vina
docking across the pinned seed set, real PK/PD) for the two published trials, then
drives each real ``sim_result`` through the real service path (market model, tickers,
commentary, dashboards) via a scripted Devin transport. The physics is real and
``code_patched: false``; only the Devin *transport* is stubbed, since this runs the
committed source directly against the pinned requirements-sim.txt stack rather than in
a hosted session. That is what makes the numbers reproducible-from-source verifiable.

    python regen_artifacts.py
"""

from __future__ import annotations

import json
from pathlib import Path

from app import create_app
from app.config import Config
from app.db import Database, make_event_id
from app.devin_client import SessionStatus
from app.estimators import get_estimator
from app.signing import SIGNATURE_HEADER, sign

SECRET = "regen-secret"
RESULTS = Path(__file__).resolve().parent.parent / "results"
TICKERS = json.loads((Path(__file__).resolve().parent / "tickers.json").read_text())

TRIALS = [
    {
        "name": "kras_sotorasib", "nct": "NCT-REAL-0001", "sponsor": "Amgen",
        "drug": "sotorasib", "target": "KRAS", "tissue": "tumor",
        "phase": "PHASE1", "dose": 960.0, "outcome": "met",
    },
    {
        "name": "cftr_ivacaftor", "nct": "NCT-VERIFY-002",
        "sponsor": "Vertex Pharmaceuticals", "drug": "ivacaftor", "target": "CFTR",
        "tissue": "lung", "phase": "PHASE3", "dose": 150.0, "outcome": "met",
    },
]


class ScriptedDevin:
    """Transport stub: 'working' on the first poll, returns the real result on the next."""

    def __init__(self, sim_result: dict) -> None:
        self._polls = 0
        self._sim = sim_result

    def create_session(self, *, prompt, title, tags=None):
        class _Created:
            session_id = "local-pinned-stack-regen"
            url = ""

        return _Created()

    def get_session(self, session_id):
        self._polls += 1
        if self._polls == 1:
            return SessionStatus("working", "running", None, None)
        return SessionStatus("finished", "completed", dict(self._sim), None)


class NullAlerter:
    def notify(self, event, assessment):
        return []


def _cfg(db_path: str) -> Config:
    return Config(
        devin_api_key="regen", devin_api_base="http://local",
        sim_repo_url="https://github.com/noahlin17/trial-impact",
        sim_repo_commit="0" * 40,
        watcher_shared_secret=SECRET,
        slack_webhook_url="", smtp_host="", smtp_port=587, smtp_user="",
        smtp_password="", email_from="", email_to="",
        tickers_path="tickers.json", market_moving_threshold=0.10,
        database_path=db_path,
    )


def _run_event(app, trial: dict) -> dict:
    client = app.test_client()
    payload = {
        "event_type": "results_posted", "nct_id": trial["nct"],
        "sponsor": trial["sponsor"], "drug": trial["drug"], "target": trial["target"],
        "tissue": trial["tissue"], "phase": trial["phase"],
        "overall_status": "COMPLETED", "endpoint_outcome": trial["outcome"],
        "dose_mg": trial["dose"],
    }
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", SIGNATURE_HEADER: sign(SECRET, body)}
    assert client.post("/webhook/trial-update", data=body, headers=headers).status_code == 201
    client.post("/poll")  # working
    client.post("/poll")  # finished -> reconcile + market model
    eid = make_event_id(trial["nct"], "results_posted")
    return app.extensions["trial_impact"]["db"].get_event(eid)


def main() -> int:
    estimator = get_estimator("vina-docking-pkpd@1")
    sim_results: dict[str, dict] = {}
    for t in TRIALS:
        print(f"── docking {t['target']} × {t['drug']} (real Vina, pinned seeds) ──")
        res = estimator.run(
            target=t["target"], drug=t["drug"], tissue=t["tissue"], dose_mg=t["dose"],
        )
        if res.error:
            print(f"  FAILED: {res.error}")
            return 1
        sim_results[t["name"]] = res.to_dict()
        print(f"  ΔG={res.binding_affinity_kcal_mol}±{res.binding_affinity_sd_kcal_mol}"
              f"  Kd={res.kd_nM}  occ={res.target_occupancy_pct}%"
              f"  {res.provenance['pdb_id']} ({res.provenance['structure_format']})"
              f"  conf={res.confidence}")

    # Per-trial: isolated DB so /status renders exactly one run per dashboard.
    for t in TRIALS:
        app = create_app(
            _cfg(f"/tmp/regen_{t['name']}.db"), db=Database(f"/tmp/regen_{t['name']}.db"),
            devin=ScriptedDevin(sim_results[t["name"]]), alerter=NullAlerter(),
            tickers=TICKERS,
        )
        app.testing = True
        event = _run_event(app, t)
        (RESULTS / f"sim_{t['name']}.json").write_text(json.dumps(event, indent=2) + "\n")
        pdb = event["sim_result"]["provenance"]["pdb_id"]
        html = app.test_client().get("/status", headers={"Accept": "text/html"}).data
        (RESULTS / f"dashboard_{t['target'].lower()}_{pdb}.html").write_bytes(html)
        print(f"  wrote sim_{t['name']}.json + dashboard_{t['target'].lower()}_{pdb}.html")

    # Combined: both runs in one DB so /analysis has a corpus to aggregate.
    combo = create_app(
        _cfg("/tmp/regen_combo.db"), db=Database("/tmp/regen_combo.db"),
        devin=ScriptedDevin(sim_results[TRIALS[0]["name"]]), alerter=NullAlerter(),
        tickers=TICKERS,
    )
    combo.testing = True
    # Rewire the transport per trial (each event polls its own scripted result).
    ext = combo.extensions["trial_impact"]
    for t in TRIALS:
        ext["devin"] = ScriptedDevin(sim_results[t["name"]])
        _run_event(combo, t)
    analysis_html = combo.test_client().get("/analysis", headers={"Accept": "text/html"}).data
    (RESULTS / "analysis_dashboard.html").write_bytes(analysis_html)
    print("  wrote analysis_dashboard.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

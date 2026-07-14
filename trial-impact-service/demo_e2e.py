#!/usr/bin/env python3
"""End-to-end demo: a fake protein passing Phase 1, driven through the whole system.

Real Devin sessions dock a *real* structure fetched from UniProt/PDB, so a made-up
protein can't run the live physics. This harness instead injects a **scripted fake
Devin** that returns a realistic ``SIM_RESULT_JSON`` — everything else is the real
system: the signed webhook, the routes, the SQLite store, the market model, the
alert fan-out, and the dashboard template.

Run:
    python demo_e2e.py           # prints a narrated trace + opens the dashboard
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile

from app import create_app
from app.config import Config
from app.db import Database, make_event_id
from app.devin_client import SessionStatus
from app.signing import SIGNATURE_HEADER, sign
from app.simulation import RESULT_MARKER, kd_from_dg

SECRET = "demo-secret"

# A fully fabricated sponsor + competitors so the demo is self-contained.
FAKE_TICKERS = {
    "zephyr therapeutics": {
        "ticker": "ZPHR",
        "name": "Zephyr Therapeutics",
        "competitors": [
            {"ticker": "HELX", "name": "Helix Bio"},
            {"ticker": "NOVA", "name": "Nova Pharma"},
        ],
    }
}

# The fake Phase-1 readout event (structurally identical to what ctgov-watcher emits).
EVENT = {
    "event_type": "results_posted",
    "nct_id": "NCT09990001",
    "sponsor": "Zephyr Therapeutics",
    "drug": "zorbanib",
    "target": "ZORB1",            # a made-up target protein
    "tissue": "hepatic",
    "phase": "PHASE1",
    "overall_status": "COMPLETED",
    "endpoint_outcome": "met",     # passed Phase 1
    "dose_mg": 50,
}

# What the (faked) Devin simulation session "returns" — a decent binder, drug-like.
DELTA_G = -8.8
SIM_RESULT = {
    "target": "ZORB1",
    "drug": "zorbanib",
    "tissue": "hepatic",
    "dose_mg": 50,
    "binding_affinity_kcal_mol": DELTA_G,
    "kd_nM": round(kd_from_dg(DELTA_G), 2),
    "cmax_ng_ml": 318.5,
    "auc_ng_h_ml": 4120.0,
    "target_occupancy_pct": 71.5,
    "druglikeness_flag": False,
    "confidence": 0.82,
    "provenance": {
        "uniprot": "Q9FAKE1",
        "structure_source": "AlphaFold",
        "pdb_id": "AF-Q9FAKE1-F1",
        "smiles": "CC(=O)Nc1ccc(cc1)S(=O)(=O)N",
    },
}


class ScriptedDevin:
    """Stands in for a Devin session: 'running' on the first poll, done on the next."""

    def __init__(self) -> None:
        self._polls = 0

    def create_session(self, *, prompt, title, tags=None):
        class _Created:
            session_id = "devin-demo-001"
            url = "https://app.devin.ai/sessions/devin-demo-001"

        self.prompt = prompt
        return _Created()

    def get_session(self, session_id):
        self._polls += 1
        if self._polls == 1:  # first poll: still working
            return SessionStatus("working", "running", None, None)
        return SessionStatus("finished", "completed", dict(SIM_RESULT), None)


class CapturingAlerter:
    def __init__(self):
        self.sent = []

    def notify(self, event, assessment):
        self.sent.append(assessment)
        return ["slack (captured)"]


def banner(n, title):
    print(f"\n{'═' * 78}\n  STAGE {n} · {title}\n{'═' * 78}")


def main() -> int:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    cfg = Config(
        devin_api_key="demo", devin_api_base="http://devin.demo",
        sim_repo_url="https://github.com/noahlin17/trial-impact-service",
        # A placeholder commit so the (scripted) session can be launched; a real run
        # sets SIM_REPO_COMMIT to an actual commit so the checkout is reproducible.
        sim_repo_commit="0000000000000000000000000000000000000000",
        watcher_shared_secret=SECRET,
        slack_webhook_url="", smtp_host="", smtp_port=587, smtp_user="",
        smtp_password="", email_from="", email_to="",
        tickers_path="tickers.json", market_moving_threshold=0.10,
        database_path=tmp.name,
    )
    devin, alerter = ScriptedDevin(), CapturingAlerter()
    app = create_app(cfg, db=Database(cfg.database_path), devin=devin,
                     alerter=alerter, tickers=FAKE_TICKERS)
    app.testing = True
    client = app.test_client()

    # ---- STAGE 1: the watcher fires a signed webhook -----------------------
    banner(1, "ctgov-watcher emits a signed webhook (fake protein, Phase 1 PASS)")
    body = json.dumps(EVENT).encode()
    sig = sign(SECRET, body)
    print("POST /webhook/trial-update")
    print("  " + SIGNATURE_HEADER + ": " + sig)
    print(json.dumps(EVENT, indent=2))

    resp = client.post("/webhook/trial-update", data=body,
                       headers={"Content-Type": "application/json", SIGNATURE_HEADER: sig})
    event = resp.get_json()["event"]
    print(f"\n→ {resp.status_code} — event stored as '{event['event_id']}'")
    print(f"  status = {event['status']}   session = {event['devin_session_id']}")
    print(f"  sponsor ticker = {event['sponsor_ticker']}   "
          f"competitors = {[c['ticker'] for c in event['competitor_tickers']]}")

    # ---- STAGE 2: Devin runs the biophysical simulation --------------------
    banner(2, "Devin session runs the docking + PK/PD pipeline")
    print("Prompt handed to Devin (excerpt):")
    print("  " + "\n  ".join(devin.prompt.splitlines()[:6]) + "\n  ...")
    print("\nFirst poll — session still working:")
    r1 = client.post("/poll").get_json()
    print("  " + json.dumps(r1["results"][0]))

    print("\nSecond poll — session finished; Devin returns:")
    print(f"  {RESULT_MARKER} {json.dumps(SIM_RESULT)}")

    # ---- STAGE 3: score + alert -------------------------------------------
    banner(3, "Market model scores the readout and fires an alert")
    r2 = client.post("/poll").get_json()
    print("Poll result: " + json.dumps(r2["results"][0]))

    stored = app.extensions["trial_impact"]["db"].get_event(
        make_event_id(EVENT["nct_id"], EVENT["event_type"]))
    print("\nStored simulation result:")
    for k in ("binding_affinity_kcal_mol", "kd_nM", "cmax_ng_ml",
              "target_occupancy_pct", "druglikeness_flag", "confidence"):
        print(f"  {k:26s} = {stored['sim_result'][k]}")

    print("\nShare-price calls:")
    for c in stored["price_calls"]:
        arrow = {"up": "▲", "down": "▼", "flat": "▬"}[c["direction"]]
        print(f"  {arrow} {c['ticker']:5s} ({c['name']}, {c['role']}): "
              f"{c['direction']}/{c['magnitude']}")

    print("\nCommentary:\n" + "\n".join("  " + ln for ln in stored["commentary"].splitlines()))
    print(f"\nAlert fired via: {alerter.sent and ['slack (captured)'] or 'none'}")

    # ---- STAGE 4: dashboard ------------------------------------------------
    banner(4, "Dashboard (the read model)")
    html = client.get("/status", headers={"Accept": "text/html"}).data.decode()
    out = "/tmp/trial_impact_dashboard.html"
    with open(out, "w") as fh:
        fh.write(html)
    print(f"Rendered dashboard written to {out}")
    api = client.get("/status?format=json").get_json()
    print("Aggregate stats: " + json.dumps(api["stats"]))
    try:
        subprocess.run(["open", out], check=False)  # macOS: open in browser
        print("Opened in your browser ✔")
    except FileNotFoundError:
        print(f"Open it manually: file://{out}")

    print("\nDone — signed webhook → Devin sim → market model → alert → dashboard.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

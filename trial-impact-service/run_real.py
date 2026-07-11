#!/usr/bin/env python3
"""Drive the system against the REAL Devin API — no fakes.

Loads secrets from .env, builds the app with the real DevinClient, fires a signed
webhook for a REAL drug/target (so Devin can actually fetch a structure and dock),
and polls the live session until it reaches a terminal state.

    python run_real.py                       # KRAS + sotorasib, Phase-1 framing
    python run_real.py --target CFTR --drug ivacaftor --tissue lung --dose 150
    python run_real.py --watch               # keep polling until the session ends
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from app import create_app
from app.config import Config
from app.db import Database, make_event_id


def load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="KRAS")
    ap.add_argument("--drug", default="sotorasib")
    ap.add_argument("--tissue", default="tumor")
    ap.add_argument("--dose", type=float, default=960)
    ap.add_argument("--nct", default="NCT-REAL-0001")
    ap.add_argument("--phase", default="PHASE1")
    ap.add_argument("--outcome", default="met")
    ap.add_argument("--sponsor", default="Amgen")
    ap.add_argument("--watch", action="store_true", help="Poll until terminal")
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--max-min", type=int, default=40)
    args = ap.parse_args()

    load_dotenv()
    os.environ["DATABASE_PATH"] = os.environ.get("DEMO_DB", "./real_run.db")
    cfg = Config.from_env()
    print(f"Devin key configured: {cfg.devin_configured} "
          f"(base {cfg.devin_api_base})")
    if not cfg.devin_configured:
        print("→ No DEVIN_API_KEY — set it in .env; a real session cannot start.")
        return 2

    app = create_app(cfg, db=Database(cfg.database_path))
    client = app.test_client()

    payload = {
        "event_type": "results_posted",
        "nct_id": args.nct, "sponsor": args.sponsor,
        "drug": args.drug, "target": args.target, "tissue": args.tissue,
        "phase": args.phase, "overall_status": "COMPLETED",
        "endpoint_outcome": args.outcome, "dose_mg": args.dose,
    }
    print("\n── Firing webhook (REAL Devin session will be created) ──")
    print(json.dumps(payload, indent=2))
    resp = client.post("/webhook/trial-update", json=payload)
    print(f"\n→ {resp.status_code}")
    body = resp.get_json()
    print(json.dumps(body, indent=2)[:1500])
    if resp.status_code != 201:
        print("\nSession NOT created — see error above.")
        return 1

    event = body["event"]
    print(f"\n✔ REAL Devin session: {event['session_url']}")
    eid = make_event_id(args.nct, "results_posted")

    if not args.watch:
        print("\nRun with --watch to poll until it finishes, or hit POST /poll.")
        return 0

    deadline = time.time() + args.max_min * 60
    while time.time() < deadline:
        time.sleep(args.interval)
        r = client.post("/poll").get_json()
        row = app.extensions["trial_impact"]["db"].get_event(eid)
        print(f"[{time.strftime('%H:%M:%S')}] status={row['status']}  "
              f"{json.dumps(r['results'][0])}")
        if row["status"] in ("completed", "failed"):
            print("\n── FINAL ──")
            print("sim_result:", json.dumps(row["sim_result"], indent=2))
            print("price_calls:", json.dumps(row["price_calls"], indent=2))
            if row["commentary"]:
                print("\n" + row["commentary"])
            return 0
    print("\nTimed out waiting; check the session URL above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

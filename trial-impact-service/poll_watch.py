#!/usr/bin/env python3
"""Poll the already-created REAL Devin session until it reaches a terminal state.

Reuses the event persisted by run_real.py in ./real_run.db (does NOT create a new
session). Prints every status transition and the final real result.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from app import create_app
from app.config import Config
from app.db import Database


def load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    load_dotenv()
    os.environ["DATABASE_PATH"] = "./real_run.db"
    cfg = Config.from_env()
    app = create_app(cfg, db=Database(cfg.database_path))
    client = app.test_client()
    db = app.extensions["trial_impact"]["db"]

    events = db.list_events()
    if not events:
        print("No event in ./real_run.db — run run_real.py first.")
        return 1
    eid = events[0]["event_id"]
    print(f"Watching {eid}  session={events[0]['devin_session_id']}")
    print(f"Session URL: {events[0]['session_url']}")

    last = None
    deadline = time.time() + 45 * 60
    while time.time() < deadline:
        r = client.post("/poll").get_json()
        row = db.get_event(eid)
        if row["status"] != last:
            print(f"[{time.strftime('%H:%M:%S')}] {last} → {row['status']}  "
                  f"{json.dumps(r['results'][0]) if r['results'] else ''}", flush=True)
            last = row["status"]
        if row["status"] in ("completed", "failed"):
            print("\n════════ FINAL (REAL) ════════", flush=True)
            print("sim_result:\n" + json.dumps(row["sim_result"], indent=2), flush=True)
            if row["price_calls"]:
                print("\nprice_calls:\n" + json.dumps(row["price_calls"], indent=2), flush=True)
            if row["commentary"]:
                print("\n" + row["commentary"], flush=True)
            return 0
        time.sleep(30)
    print("Timed out after 45 min; session still running — check the URL above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

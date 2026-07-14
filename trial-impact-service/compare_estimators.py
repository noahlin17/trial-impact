#!/usr/bin/env python3
"""Run one trial through TWO estimators head-to-head against the REAL Devin API.

The comparison is the product, not any single model's number (see the estimator
interface in ``app/estimators.py`` and the thesis: the physics has no moat, so what
matters is whether it beats a cheap baseline). This fires the *same* trial once per
estimator, polls every session to a terminal state, and prints the results side by
side plus the spread between them.

    python compare_estimators.py                       # KRAS x sotorasib, both estimators
    python compare_estimators.py --target CFTR --drug ivacaftor --tissue lung --dose 150
    python compare_estimators.py --estimators vina-docking-pkpd@1 ligand-efficiency-baseline@1
"""

from __future__ import annotations

import argparse
import json
import time

from app import create_app
from app.analysis import estimator_comparison
from app.config import Config
from app.db import Database, make_event_id
from app.estimators import list_estimators
from app.signing import SIGNATURE_HEADER, sign
from run_real import load_dotenv, resolve_commit


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", default="KRAS")
    ap.add_argument("--drug", default="sotorasib")
    ap.add_argument("--tissue", default="tumor")
    ap.add_argument("--dose", type=float, default=960)
    ap.add_argument("--nct", default="NCT-COMPARE-0001")
    ap.add_argument("--phase", default="PHASE1")
    ap.add_argument("--outcome", default="met")
    ap.add_argument("--sponsor", default="Amgen")
    ap.add_argument(
        "--estimators", nargs="+", default=list_estimators(),
        help="Estimator ids to race (default: all registered)",
    )
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--max-min", type=int, default=45)
    args = ap.parse_args()

    load_dotenv()
    import os

    os.environ["DATABASE_PATH"] = os.environ.get("DEMO_DB", "./compare_run.db")
    os.environ.setdefault("SIM_REPO_COMMIT", resolve_commit())
    cfg = Config.from_env()
    if not cfg.devin_configured:
        print("→ No DEVIN_API_KEY — set it in .env; real sessions cannot start.")
        return 2
    if not cfg.sim_pinned:
        print("→ Could not pin a commit (set SIM_REPO_COMMIT or run inside the repo).")
        return 2

    app = create_app(cfg, db=Database(cfg.database_path))
    client = app.test_client()
    db = app.extensions["trial_impact"]["db"]

    print(f"Racing {len(args.estimators)} estimators on {args.target} x {args.drug} "
          f"(pinned {cfg.sim_repo_commit[:12]}):")
    event_ids = []
    for est in args.estimators:
        payload = {
            "event_type": "results_posted", "nct_id": args.nct,
            "sponsor": args.sponsor, "drug": args.drug, "target": args.target,
            "tissue": args.tissue, "phase": args.phase, "overall_status": "COMPLETED",
            "endpoint_outcome": args.outcome, "dose_mg": args.dose, "estimator": est,
        }
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if cfg.watcher_shared_secret:
            headers[SIGNATURE_HEADER] = sign(cfg.watcher_shared_secret, body)
        resp = client.post("/webhook/trial-update", data=body, headers=headers)
        if resp.status_code != 201:
            print(f"  ! {est}: webhook failed ({resp.status_code}) {resp.get_json()}")
            continue
        eid = make_event_id(args.nct, "results_posted", est)
        event_ids.append(eid)
        print(f"  ✔ {est}: {resp.get_json()['event']['session_url']}")

    if not event_ids:
        return 1

    deadline = time.time() + args.max_min * 60
    while time.time() < deadline:
        time.sleep(args.interval)
        client.post("/poll")
        rows = [db.get_event(eid) for eid in event_ids]
        done = [r for r in rows if r and r["status"] in ("completed", "failed")]
        print(f"[{time.strftime('%H:%M:%S')}] "
              + "  ".join(f"{r['event_id'].split(':')[-1]}={r['status']}" for r in rows if r))
        if len(done) == len(event_ids):
            break

    comparison = estimator_comparison(db.list_events())
    print("\n════════ HEAD-TO-HEAD ════════")
    print(json.dumps(comparison, indent=2))
    print("\nOpen /analysis for the rendered side-by-side (Estimator head-to-head).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

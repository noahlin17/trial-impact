#!/usr/bin/env python3
"""Fire example clinical-trial-event webhooks at the running service.

This stands in for the ctgov-watcher. It POSTs payloads that are structurally
identical to what the watcher emits, to ``/webhook/trial-update`` — hitting the
exact same code path (including HMAC verification) a live watcher would. See the
README for why a simulator is used alongside the real watcher.

If ``WATCHER_SHARED_SECRET`` is set in the environment, payloads are signed the
same way the watcher signs them.

Usage:
    python simulate_trial.py
    python simulate_trial.py --base-url http://localhost:8000
    python simulate_trial.py --events 1 3
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import requests

from app.signing import SIGNATURE_HEADER, sign

# Realistic small-molecule readouts whose sponsors appear in tickers.json and
# whose targets have real UniProt entries / structures (so app/simulation.py can
# actually run them). Outcomes are a mix of met / missed.
EVENTS: dict[int, dict] = {
    1: {
        "event_type": "results_posted",
        "nct_id": "NCT04303780",
        "sponsor": "Amgen",
        "drug": "sotorasib",
        "target": "KRAS",
        "tissue": "tumor",
        "phase": "PHASE3",
        "overall_status": "COMPLETED",
        "endpoint_outcome": "met",
        "dose_mg": 960,
    },
    2: {
        "event_type": "results_posted",
        "nct_id": "NCT01614470",
        "sponsor": "Vertex Pharmaceuticals",
        "drug": "ivacaftor",
        "target": "CFTR",
        "tissue": "lung",
        "phase": "PHASE3",
        "overall_status": "COMPLETED",
        "endpoint_outcome": "met",
        "dose_mg": 150,
    },
    3: {
        "event_type": "status_change",
        "nct_id": "NCT03887455",
        "sponsor": "Biogen",
        "drug": "vixotrigine",
        "target": "SCN9A",
        "tissue": "cns",
        "phase": "PHASE2",
        "overall_status": "TERMINATED",
        "endpoint_outcome": "missed",
        "dose_mg": 200,
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--events", type=int, nargs="*", default=sorted(EVENTS),
        help="Event numbers to fire (default: all)",
    )
    args = parser.parse_args()

    secret = os.environ.get("WATCHER_SHARED_SECRET", "")
    endpoint = f"{args.base_url.rstrip('/')}/webhook/trial-update"
    exit_code = 0

    for number in args.events:
        if number not in EVENTS:
            print(f"! skipping unknown event #{number}")
            continue
        payload = EVENTS[number]
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if secret:
            headers[SIGNATURE_HEADER] = sign(secret, body)

        print(f"-> POST {endpoint}  ({payload['nct_id']}: {payload['sponsor']} "
              f"{payload['drug']} — {payload['endpoint_outcome']})")
        try:
            resp = requests.post(endpoint, data=body, headers=headers, timeout=60)
        except requests.RequestException as exc:
            print(f"   request failed: {exc}")
            exit_code = 1
            continue

        print(f"   {resp.status_code} {resp.reason}")
        try:
            print("   " + json.dumps(resp.json(), indent=2).replace("\n", "\n   "))
        except ValueError:
            print("   " + resp.text)
        if resp.status_code >= 400:
            exit_code = 1

    print("\nDone. View progress at", f"{args.base_url.rstrip('/')}/status")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

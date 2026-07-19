# ctgov-watcher

A tiny service that gives [ClinicalTrials.gov](https://clinicaltrials.gov) the
webhook it doesn't have. It polls the CT.gov **API v2** for a configured watchlist
of trials, diffs each record against the last-seen state, and — when something
material changes (results posted, overall-status change, phase change) — emits an
**HMAC-signed** `POST /webhook/trial-update` to the [trial-impact
service](../trial-impact-service).

```
CT.gov API v2 ──poll──▶ diff vs SQLite state ──change?──▶ signed POST /webhook/trial-update
```

## Why a separate service

CT.gov is pull-only. Isolating the polling/diffing here keeps the analysis service
event-driven and lets the two scale and deploy independently. The watcher holds no
secrets beyond the shared HMAC key and can run as a cron job (`--once`) or a
long-lived loop.

## Configure

```bash
cp .env.example .env       # set MAIN_SERVICE_URL + WATCHER_SHARED_SECRET
```

`watchlist.json` lists the trials to watch and supplies the static metadata CT.gov
doesn't expose machine-readably (molecular `target`, `tissue`, `dose_mg`, and — for
the demo — `endpoint_outcome`):

```json
[{ "nct_id": "NCT04303780", "sponsor": "Amgen", "drug": "sotorasib",
   "target": "KRAS", "tissue": "tumor", "dose_mg": 960, "endpoint_outcome": "met" }]
```

## Run

```bash
pip install -r requirements.txt

python watcher.py --once                 # single cycle (cron / CI)
python watcher.py --once --emit-initial  # also emit on first sighting (good for demos)
python watcher.py                        # loop every POLL_INTERVAL_SECONDS
```

Or with Docker: `docker build -t ctgov-watcher . && docker run --env-file .env ctgov-watcher`.

## How it decides to emit

`detect_event(prev, curr)`:

| Condition | Emitted `event_type` |
|-----------|----------------------|
| `hasResults` flips false→true | `results_posted` |
| `overallStatus` changed | `status_change` |
| `phase` changed | `phase_change` |
| first sighting | nothing (baseline only) unless `--emit-initial` |

The baseline is always advanced after a cycle, so each change fires exactly once.
The signature (`X-CTGov-Signature: sha256=…`) is computed with the same
`signing.py` the trial-impact service verifies with.

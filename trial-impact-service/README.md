# Trial Impact Service

An event-driven system that turns a **clinical-trial readout** into a
**share-price impact commentary**. When a trial event arrives, the service spins
up an isolated **[Devin](https://docs.devin.ai/api-reference/v1/overview)** session
that runs a real **biophysical simulation** (protein–ligand docking + PK/PD),
scores the result with a transparent market model, and — on a market-moving
readout — alerts to Slack/email while surfacing everything on a dashboard.

> **Not investment advice.** Output is an automated research signal for
> informational purposes only. A disclaimer is attached to every assessment.

> The directory is still named `devin-remediation-bot` for historical reasons; the
> service inside it is the trial-impact service.

---

## Architecture

```
ClinicalTrials.gov API v2 ──poll──▶  ctgov-watcher (../ctgov-watcher)
                                       │  diff records, detect material change
                                       ▼  POST /webhook/trial-update  (HMAC-signed)
┌──────────────────────────────────────────────────────────────────────────┐
│                         Trial Impact service (Flask)                       │
│  TRIGGER   POST /webhook/trial-update                                       │
│     verify HMAC → resolve tickers (sponsor + competitors)                  │
│                 → build sim prompt → Devin: POST /sessions ────────────────┼─▶ Devin session
│                 → SQLite: insert event (queued)                            │   runs app/simulation.py
│  RECONCILE POST /poll                                                      │   (docking + PK/PD)
│     GET Devin session → extract SIM_RESULT_JSON ◀──────────────────────────┼── ΔG, Kd, occupancy
│     → market_model.assess → price calls + commentary                       │
│     → SQLite update → Slack/email alert (once) on market-movers            │
│  OBSERVE   GET /status  → dashboard + JSON                                  │
└──────────────────────────────────────────────────────────────────────────┘
```

The pipeline has four stages, each isolated into its own module:

| Stage | Endpoint | Module | Responsibility |
|-------|----------|--------|----------------|
| **Trigger** | `POST /webhook/trial-update` | `app/routes.py`, `app/signing.py` | Verify the signed webhook, resolve tickers, spawn a Devin simulation session, persist the event. |
| **Orchestrate** | — | `app/devin_client.py`, `app/prompts.py`, `app/simulation.py` | Tell Devin to run the docking + PK/PD pipeline; parse the structured result back. |
| **Observe** | `GET /status` | `app/routes.py`, `app/stats.py` | Read model: every event, its sim result, tickers, price calls, and aggregates (JSON or HTML). |
| **Reconcile** | `POST /poll` | `app/routes.py`, `app/market_model.py`, `app/alerts.py` | Poll in-flight sessions, score completed sims, and alert once on market-movers. |

### Why Devin runs the simulation

The tissue/protein simulation is **real biophysics**, not a stub: fetch the target
structure (UniProt → experimental PDB, else AlphaFold), fetch the ligand
(PubChem → SMILES → RDKit 3D), dock with **AutoDock Vina** for a real binding free
energy ΔG, then solve a **SciPy** PK/PD ODE for tissue exposure and target
occupancy. That needs a full sandbox that can `pip install` a heavy scientific
stack, pull structures, and iterate on failures — exactly what a Devin session is.
One session per event keeps runs isolated, independently retryable, and observable
(the same design the pipeline uses throughout).

`app/simulation.py` is the canonical, CLI-runnable pipeline; Devin clones the repo
(`SIM_REPO_URL`), installs `requirements-sim.txt`, runs it, and reports back a
single `SIM_RESULT_JSON:` line the service parses.

---

## Module map

```
app/
  __init__.py       # application factory — wires config + db + devin + alerter + tickers
  config.py         # 12-factor config from environment variables
  db.py             # SQLite data-access layer (single `trial_events` table, no ORM)
  signing.py        # HMAC-SHA256 sign/verify (shared with the watcher)
  prompts.py        # builds the simulation task each Devin session receives
  simulation.py     # REAL physics: docking (Vina) + PK/PD (SciPy). Runs in Devin.
  devin_client.py   # Devin API client + SIM_RESULT_JSON extraction + status mapping
  market_model.py   # PoS delta → directional price calls + commentary (the "model")
  alerts.py         # Slack + email fan-out for market-moving readouts
  routes.py         # the four HTTP endpoints
  stats.py          # aggregate metrics
  templates/status.html   # dashboard
tickers.json        # sponsor → ticker + competitor map
requirements.txt    # web-service deps (Flask, requests, gunicorn)
requirements-sim.txt# heavy sim deps (rdkit, meeko, vina, openbabel, scipy) — installed by Devin
simulate_trial.py   # fires signed trial-event payloads (stand-in for the watcher)
wsgi.py             # gunicorn / dev-server entrypoint
tests/test_app.py   # end-to-end flow with in-memory fakes (offline)
```

---

## Running the demo end to end

### Prerequisites
- Docker + Docker Compose, **or** Python 3.12+.
- A **Devin API key** — <https://app.devin.ai/settings/api-keys>.
- (Optional) a Slack incoming-webhook URL and/or SMTP creds for alerts.

### 1. Configure secrets
```bash
cp .env.example .env
# set DEVIN_API_KEY, WATCHER_SHARED_SECRET (and optionally SLACK_WEBHOOK_URL / SMTP_*)
```

### 2. Start the service
```bash
docker compose up --build
```
Dashboard: <http://localhost:8000/status>.

### 3. Fire some trial events
```bash
export WATCHER_SHARED_SECRET=...   # same value as .env, so payloads are signed
python simulate_trial.py           # POSTs three realistic readouts at the webhook
```
Each creates a Devin session and a `queued` event. (Or run the real
[`ctgov-watcher`](../ctgov-watcher) against live trials.)

### 4. Poll for progress
```bash
curl -X POST http://localhost:8000/poll
```
When a session finishes with a parseable result, the event flips to `completed`,
the sim metrics + price calls appear on `/status`, and a Slack/email alert fires
for any market-moving readout.

### 5. Observe
- Dashboard: <http://localhost:8000/status>
- JSON: `curl -s http://localhost:8000/status?format=json | jq`

### Run the real physics locally (optional)
```bash
pip install -r requirements-sim.txt
python -m app.simulation --target KRAS --drug sotorasib --tissue tumor --dose 960 --json-only
```

---

## API reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhook/trial-update` | Verify signature, spawn a Devin sim session, store the event. `201`. |
| `GET`  | `/status` | All events + aggregate stats. HTML for browsers, JSON otherwise (or `?format=json`). |
| `POST` | `/poll` | Poll in-flight sessions, score completed sims, alert once. Idempotent. |
| `GET`  | `/health` | Liveness probe. |

### Webhook payload shape
```json
{
  "event_type": "results_posted",
  "nct_id": "NCT04303780",
  "sponsor": "Amgen",
  "drug": "sotorasib", "target": "KRAS", "tissue": "tumor",
  "phase": "PHASE3", "overall_status": "COMPLETED",
  "endpoint_outcome": "met", "dose_mg": 960
}
```
Signed with `X-CTGov-Signature: sha256=<hmac>` when `WATCHER_SHARED_SECRET` is set.

---

## Configuration

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `DEVIN_API_KEY` | yes | — | Authenticates Devin API calls. |
| `WATCHER_SHARED_SECRET` | recommended | — | HMAC secret; when set, webhook signatures are enforced. |
| `SIM_REPO_URL` | no | `…/trial-impact-service` | Repo Devin clones to run the simulation. |
| `SLACK_WEBHOOK_URL` | no | — | Slack alerts on market-movers. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `EMAIL_FROM` / `EMAIL_TO` | no | — | Email alerts. |
| `TICKERS_PATH` | no | `tickers.json` | Sponsor→ticker/competitor map. |
| `MARKET_MOVING_THRESHOLD` | no | `0.10` | `|PoS delta|` at/above which an alert fires. |
| `DEVIN_API_BASE` | no | `https://api.devin.ai/v1` | Override for testing. |
| `DATABASE_PATH` | no | `/data/trial_impact.db` | SQLite file location. |

---

## Local development (without Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export DEVIN_API_KEY=... WATCHER_SHARED_SECRET=... DATABASE_PATH=./trial_impact.db
python wsgi.py                       # dev server on :8000
python simulate_trial.py             # in another shell
```

### Tests & lint
```bash
ruff check .
pytest -q
```
The test suite exercises the full webhook → poll → alert flow with in-memory fakes
for Devin and the alerter, so it runs offline and deterministically. The real
biophysics runs only inside a Devin session and is therefore not part of the
offline suite.

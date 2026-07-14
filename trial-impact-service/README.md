# Trial Impact Service

An event-driven system that turns a **clinical-trial readout** into a
**share-price impact commentary**. When a trial event arrives, the service spins
up an isolated **[Devin](https://docs.devin.ai/api-reference/v1/overview)** session
that runs a real **biophysical simulation** (protein–ligand docking + PK/PD),
scores the result with a transparent market model, and — on a market-moving
readout — alerts to Slack/email while surfacing everything on a dashboard.

> **Not investment advice.** Output is an automated research signal for
> informational purposes only. A disclaimer is attached to every assessment.

---

## Architecture

```
ClinicalTrials.gov API v2 ──poll──▶  ctgov-watcher (../ctgov-watcher)
                                       │  diff records, detect material change
                                       ▼  POST /webhook/trial-update  (HMAC-signed)
┌──────────────────────────────────────────────────────────────────────────┐
│                         Trial Impact service (Flask)                     │
│  TRIGGER   POST /webhook/trial-update                                    │
│     verify HMAC → resolve tickers (sponsor + competitors)                │
│                 → build sim prompt → Devin: POST /sessions ──────────────┼─▶ Devin session
│                 → SQLite: insert event (queued)                          │   runs app/simulation.py
│  RECONCILE POST /poll                                                    │   (docking + PK/PD)
│     GET Devin session → extract SIM_RESULT_JSON ◀────────────────────────┼── ΔG, Kd, occupancy
│     → market_model.assess → price calls + commentary                     │
│     → SQLite update → Slack/email alert (once) on market-movers          │
│  OBSERVE   GET /status  → dashboard + JSON                               │
└──────────────────────────────────────────────────────────────────────────┘
```

The pipeline has four stages, each isolated into its own module:

| Stage | Endpoint | Module | Responsibility |
|-------|----------|--------|----------------|
| **Trigger** | `POST /webhook/trial-update` | `app/routes.py`, `app/signing.py` | Verify the signed webhook, resolve tickers, spawn a Devin simulation session, persist the event. |
| **Orchestrate** | — | `app/devin_client.py`, `app/prompts.py`, `app/simulation.py` | Tell Devin to run the docking + PK/PD pipeline; parse the structured result back. |
| **Observe** | `GET /status` · `GET /analysis` | `app/routes.py`, `app/stats.py`, `app/analysis.py` | Read model: every event, its sim result, tickers, price calls and aggregates (`/status`); plus a corpus view to *learn from* the runs — physics→price relationships and a per-run drill-down (`/analysis`). |
| **Reconcile** | `POST /poll` | `app/routes.py`, `app/market_model.py`, `app/alerts.py` | Poll in-flight sessions, score completed sims, and alert once on market-movers. |

### Why Devin runs the simulation

The tissue/protein simulation is **real biophysics**, not a stub: fetch the target
structure (UniProt → experimental PDB, else AlphaFold), fetch the ligand
(PubChem → SMILES → RDKit 3D), dock with **AutoDock Vina** for a real binding free
energy ΔG (returning the top pose), then solve the PK/PD model in **closed form**
(Bateman) for tissue exposure and target occupancy. That needs a full sandbox that
can `pip install` a heavy scientific
stack, pull structures, and iterate on failures — exactly what a Devin session is.
One session per event keeps runs isolated, independently retryable, and observable
(the same design the pipeline uses throughout).

`app/simulation.py` is the canonical, CLI-runnable pipeline; Devin clones the repo
(`SIM_REPO_URL`), installs `requirements-sim.txt`, runs it, and reports back a
single `SIM_RESULT_JSON:` line the service parses.

### The result contract (and why it has a `code_patched` field)

A Devin session is an *agent*, not a runner: when a step fails it will fix it and
carry on. That is exactly what you want for `pip install` problems — and exactly what
you do **not** want for the science, because a session that quietly edits
`simulation.py` reports numbers that did not come from the code in this repo. Two real
cases bit us: PubChem renamed the SMILES property (`CanonicalSMILES` →
`ConnectivitySMILES`/`SMILES`), and a cryo-EM structure was mmCIF-only. Both times the
run "succeeded" with plausible values, and both times the committed code could not
have produced them.

So the contract makes divergence *loud*: the session must set `code_patched: true` and
`patch_summary` if it modified the script, and a patched run is surfaced on `/status`
as **not reproducible from source**. A plausible number is not a correct number, and a
number you cannot regenerate is not a result.

---

## Module map

```
app/
  __init__.py       # application factory — wires config + db + devin + alerter + tickers
  config.py         # 12-factor config from environment variables
  db.py             # SQLite data-access layer (single `trial_events` table, no ORM)
  signing.py        # HMAC-SHA256 sign/verify (shared with the watcher)
  prompts.py        # builds the simulation task each Devin session receives
  simulation.py     # REAL physics: docking (Vina) + closed-form PK/PD. Runs in Devin.
  devin_client.py   # Devin API client + SIM_RESULT_JSON extraction + status mapping
  market_model.py   # PoS delta → directional price calls + commentary (the "model")
  alerts.py         # Slack + email fan-out for market-moving readouts
  routes.py         # the HTTP endpoints
  stats.py          # aggregate metrics for /status
  analysis.py       # cross-run corpus: physics→price relationships + per-run drill-down
  templates/status.html     # live dashboard (events, price calls, 3D structures)
  templates/analysis.html   # /analysis — learn from the corpus (Plotly)
  templates/_viewer3d.html  # shared 3Dmol viewer partial, reused by both dashboards
tickers.json        # sponsor → ticker + competitor map
requirements.txt    # web-service deps (Flask, requests, gunicorn)
requirements-sim.txt# heavy sim deps (rdkit, meeko, vina, openbabel, numpy) — installed by Devin
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
| `GET`  | `/analysis` | Corpus view: physics→price scatter, sortable run table, and a per-run drill-down (3D structure + PK/PD curve + PoS reasoning waterfall). |
| `GET`  | `/analysis.json` | The same payload as JSON (`app/analysis.py::build_payload`). |
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

## Limitations & modeling caveats

This is a research prototype. The modeling choices are deliberately transparent and
approximate; the known limitations below are on record so results are read with the
right caveats. **Nothing here is investment advice.** (✅ = addressed; ◑ = partially
addressed; ○ = documented, future work.)

### Scope & chemistry
- **Small molecules only** ○ — the docking path models small-molecule drugs;
  biologics/antibodies can't be docked and are out of scope.
- **Docking is fast & approximate** ○ — AutoDock Vina is an empirical scoring
  function, not a rigorous binding free-energy method. FEP / MM-GBSA are more
  accurate but far heavier; ΔG here is a *relative* signal, not a measured affinity.
- **Generic PK constants** ○ — `ka`, `Vd`, `CL` are fixed physiological placeholders
  and `Kp` is order-of-magnitude, not drug-specific. There's no clean API for human
  PK params; allometric scaling needs animal data and structure→PK ML (ADMET-AI /
  pkCSM) is only ~±80%. The pragmatic path is per-drug **enrichment overrides**
  (same mechanism as `endpoint_outcome`); mechanistic `Kp` (Rodgers–Rowland) needs
  pKa + fu on top of the logP we already compute.
- **Covalent binders** ◑ — now **flagged** via RDKit substructure match, but still
  *scored as reversible*, so their potency is under-represented. Proper covalent
  scoring needs the Meeko/AutoDock reactive-docking protocol (reactive atom typing +
  flexible target Cys) — deferred.
  **The flag is recorded, not acted on:** `covalent_flag` is stored and surfaced, but
  the market model does not read it, so a covalent binder's understated ΔG is not
  compensated anywhere downstream. It is provenance for a human reading the run, not
  an input to the score. (Sotorasib trips it, as expected.)
- **Single structure, rigid receptor** ○ — one experimental (or AlphaFold) structure
  per target, no ensemble or flexible-side-chain docking. Vina supports both
  (ensemble = dock the ranked PDBe structure list; flex = split rigid/flex PDBQT);
  deferred because they change every run's numbers.
- **Structure choice is not pinned** ○ — the target structure is whatever PDBe/SIFTS
  `best_structures` ranks first *at run time*, and the PDB id is recorded but never
  fixed. That ranking can change as new structures are deposited, so a future re-run
  of the same trial could silently dock a **different structure** and return a
  different ΔG — the runs on record are not reproducible by construction. (Not
  observed so far: the KRAS runs have consistently resolved to `7VVB`.) The fix is to
  pin the resolved `pdb_id` per trial in the enrichment file and reuse it on re-runs.
  Ranking by resolution/coverage also means the chosen structure **need not contain
  the drug** — see the docking-box entry above.
- **`fetch_structure` cannot read mmCIF** ○ — it downloads `…/{pdb_id}.pdb` only. Many
  modern cryo-EM structures are **mmCIF-only** and 404 on the legacy `.pdb` endpoint
  (typically *because* they are too large for the legacy format), so the experimental
  path is simply unavailable for them and the run degrades to a predicted model. The
  `pdb → cif` fallback that exists today is in the **3D viewer only**. A proper fix
  wants a native mmCIF parser (gemmi) rather than a cif→pdb conversion, since
  converting an oversized structure back into PDB columns risks silently truncating
  it; `prepare_receptor_pdbqt` and `compute_docking_box` also both assume fixed-column
  PDB text. Deferred for that reason.
  **Consequence for the recorded CFTR run:** `9MXL` / `structure_source: RCSB` /
  confidence 0.9 is **not reproducible from this source tree** — `9MXL.pdb` 404s, so
  the Devin session must have worked around it inside its sandbox. That is a failed
  result contract (the stored number did not come from this code), and it is the
  strongest argument for pinning the sim to a hash of `simulation.py`.
- **AlphaFold fallback URL was pinned to a stale version** ✅ — AFDB stamps a model
  version into the filename (`…-F1-model_v6.pdb`) and bumps it over time. The code
  hardcoded `v4`, which AFDB has since rolled past, so **every** AlphaFold fallback
  404'd — the safety net for targets with no experimental structure was silently dead,
  turning a graceful degradation into a hard failure. Now resolved via the AFDB API
  (`/api/prediction/{acc}`) with a newest-first version probe as backup; the 3D viewer
  chains `v6 → v5 → v4` for the same reason.
- **Docking box does not cover the receptor** ○ — **the most serious open defect in the
  physics; [issue #1](../README.md#known-issues).** Two boxing strategies have now failed
  for the same underlying reason: neither one knows where the pocket is.
  Pocket-focused boxing was **implemented and then deliberately reverted**. Centering on
  the largest co-crystallized ligand is the standard trick, but it silently picks the
  *wrong* pocket when the structure's ligand is a cofactor: the KRAS structure our own
  pipeline selects (**7VVB**) contains only **GNP**, a GTP analog, so that heuristic
  centered the box on the **nucleotide pocket**, while sotorasib binds the **switch-II
  pocket**. It still returned a plausible-looking ΔG (−8.64).
  The blind box that replaced it has a subtler version of the same bug, which I only
  found by measuring it. `compute_docking_box` sizes the box `min(extent + 8 Å, 40 Å)`
  but keeps it **centered on the centroid**, so once a receptor exceeds ~40 Å the box
  stops covering it and Vina searches a central *slab*. The cap is binding in both
  published runs — both artifacts record `size: [40, 40, 40]`. Measured with
  `python verify_docking_box.py`:

  | Structure | Real extent | Atoms inside the 40 Å box |
  |---|---|---|
  | KRAS `7VVB` | 56 × 55 × 44 Å | **80%** |
  | CFTR `AF-P13569-F1` | 139 × 117 × 147 Å | **19%** |

  CFTR is a 1480-residue membrane protein and ivacaftor binds at the TM1/TM6 interface,
  not the centroid — so **that ΔG is a dock into an arbitrary sub-volume**, and the
  earlier claim in this file that blind docking "does not quietly dock into the wrong
  site" was simply false. It does. It just does it less obviously than the ligand-centered
  box did, which is worse, not better.
  **Mitigated, not fixed:** the code now logs a warning when the cap binds, and
  `test_docking_box_stops_covering_the_receptor_once_the_40A_cap_binds` pins the
  behaviour. (The test it replaced asserted coverage on a ~10 Å toy receptor — the one
  input where the cap can never trigger — so it passed while the property it named was
  false in production. A test that can only pass is not a test.)
  **The real fix** is cavity detection (fpocket / P2Rank) or a **drug-bound** structure
  (6OIM for KRAS/sotorasib) pinned per trial. Simply enlarging the box is *not* a fix: an
  uncapped CFTR box is ~2.4 M Å³, far past the volume where Vina's sampling is meaningful,
  so it would trade a wrong answer for a useless one.
- **The box is computed over atoms that aren't docked** ○ — `compute_docking_box` reads
  `ATOM` *and* `HETATM`, but `prepare_receptor_pdbqt` strips waters/heteroatoms and docks
  `ATOM` only, so the box is centered on a different atom set than Vina searches. Visible
  in the KRAS artifact: stored center `-19.192, 40.956, -3.009` vs an ATOM-only centroid
  of `-19.17, 40.88, -2.90`. Small in practice, wrong in principle. Deliberately **not**
  fixed in isolation: moving the box changes ΔG, which would invalidate both published
  artifacts and the `code_patched: false` claim that depends on them reproducing from
  source. It gets fixed alongside the box rework above, in a single re-run.
- **Docked pose is not returned** ○ — only the scalar ΔG comes back, so the 3D view
  shows the **reference structure** the run docked against (with its own crystal
  ligand), *not* the geometry Vina computed. Returning the pose was **implemented and
  then reverted**, and the reason is the interesting part: the pose is ~8 KB of PDB
  text, and the result contract is a *single `SIM_RESULT_JSON:` line echoed back
  through an agent transcript*. At that size the agent stopped reproducing the line
  verbatim — it truncated the JSON with `...` and moved the full payload into a file
  attachment — so the line no longer parsed and a **successful run was recorded as
  `needs_attention` with no result**. Worse, it was *intermittent*: a 7.5 KB pose came
  through intact on an earlier run, an 8.4 KB one did not. A contract that works right
  up until the payload grows is a trap, so the pose stays out of it.
  **Fix:** don't ship bulk data through the transcript. Either compress it
  (gzip + base64 takes ~8 KB of PDB to ~2.4 KB) or, better, give the session a real
  side channel — write the pose to object storage and return a URL, keeping the line
  small and fixed-size no matter what the physics produces.
- **Docking runs were non-deterministic** ✅ — `run_vina` passed `seed=0`, which Vina
  interprets as *"choose a random seed"*, so repeat runs of the same drug/target drifted
  (ΔG −8.42 / −8.59 / −8.59 for sotorasib–KRAS). Now pinned to a fixed seed. Reproducible
  numbers are a precondition for the result contract meaning anything.

### Market model
- **Uncalibrated, hand-tuned** ○ — deterministic and fully inspectable: the PoS
  delta is built additively (`pos_breakdown`) and the headline number derives from
  that breakdown, so they can never disagree. But the weights (0.5 / 0.2 / 0.15…)
  and thresholds are magic numbers. The real fix is **backtesting** against
  historical biotech readouts and actual next-day price moves to fit them.
- **Missed-trial asymmetry** ✅ — fixed. Modifiers are now applied by meaning
  (efficacy corroboration only strengthens a win; tox is always a downside risk)
  rather than mirrored by the readout sign, which previously let a tox flag reduce
  the downside of a *failed* trial. The met-trial path is unchanged.
- **Spurious alerts on `unknown` outcomes** ✅ — fixed, and this one was live on the
  *common* path. Every term in `pos_breakdown` is a modifier on a clinical readout, but
  they were applied even when there was no readout: an `unknown` outcome (base `0.0`)
  plus a tox flag scored `-0.15 × 0.95 = -0.1425`, which clears the `0.10`
  market-moving threshold and emits a **"down" call on a trial that has reported
  nothing** — a directional signal derived purely from the drug's Lipinski violations.
  And `unknown` is the *default* for every trial the watchlist has not enriched, so this
  was the majority path in production, not an edge case. The modifiers are now gated on
  `has_readout`, so no readout means no call. Both published runs are `met`, so their
  numbers are byte-identical — a regression test asserts exactly that.
- **No phase weighting** ○ — a Phase 1 pass shouldn't move a stock like a Phase 3;
  the base should scale by phase (`{P1:0.4, P2:0.7, P3:1.0}` ≈ 1 line). Deliberately
  left out this round to avoid changing the demo's numbers.
- **Naive competitor read-through** ○ — competitors are assumed to move opposite the
  sponsor, one magnitude bucket softer. Real read-through depends on mechanism /
  target overlap and modality, not just "is a competitor."
- **`endpoint_outcome` not auto-derived** ○ — met/missed is supplied via enrichment
  (`watchlist.json`), not parsed from CT.gov. An LLM classifier over the results
  section / press releases would close the loop.

### Security & operations
- **Webhook signature verification fails open** ◑ — `signature_required` is
  `bool(WATCHER_SHARED_SECRET)`, so if the secret is unset the service accepts **any**
  caller's trial event, and each accepted event spends a real Devin session. The
  fail-open default is deliberate (the demos and local runs post unsigned), but it used
  to be *silent*, which is the actual problem: an operator who forgot the secret in
  production would get an open, billable endpoint with no indication of it. `create_app`
  now logs a loud warning at startup when verification is disabled. It still fails open —
  a production deployment should make the secret mandatory and refuse to boot without it.
- **No retries or timeouts on hung sessions** ○ — a Devin session that goes `blocked` or
  hangs is left for a human; `blocked` is deliberately non-terminal so `/poll` can pick it
  up again, but nothing escalates it.
- **SQLite, single process** ○ — fine for a prototype, wrong for concurrent writers.
  Postgres is the obvious swap; the repository interface is already narrow enough for it.

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

# Trial Impact Service

An event-driven system that turns a **clinical-trial readout** into a
**share-price impact commentary**. When a trial event arrives, the service spins
up an isolated **[Devin](https://docs.devin.ai/api-reference/v1/overview)** session
that runs a real **biophysical simulation** (protein–ligand docking + PK/PD),
scores the result with a transparent market model, and — on a market-moving
readout — alerts to Slack/email while surfacing everything on a dashboard.

Scope: a preclinical / Phase 1 engagement instrument. 

> **Not investment advice.** Output is an automated research signal for informational purposes only,
> built on an illustrative, un-backtested market model. A disclaimer is attached to every assessment.

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
│     GET Devin session → extract SIM_RESULT_JSON ◀────────────────────────┼── ΔG (diagnostic), engagement
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
| **Reconcile** | `POST /poll` | `app/routes.py`, `app/market_model.py`, `app/alerts.py` | Poll in-flight sessions, score completed sims, and alert once on market-movers. |
| **Observe** | `GET /status` · `GET /analysis` | `app/routes.py`, `app/stats.py`, `app/analysis.py` | Read model: every event, its sim result, tickers, price calls and aggregates (`/status`); plus a corpus view to *learn from* the runs — physics→price relationships and a per-run drill-down (`/analysis`). |

### Why Devin runs the simulation

The tissue/protein simulation is **real biophysics**, not a stub: fetch the target
structure (UniProt → experimental PDB or mmCIF, else AlphaFold), fetch the ligand
(PubChem → SMILES → RDKit 3D), dock with **AutoDock Vina** across a fixed seed set for a real
binding free energy ΔG reported as mean ± sd (the scalar only — the pose is *not* returned; see
Limitations), then solve the PK/PD model in **closed form**
(Bateman) for tissue exposure (Cmax/AUC). The ΔG is reported as a geometric target-engagement
classification, **not** a calibrated affinity — no absolute Kd or occupancy. Running this pipeline 
needs a full sandbox that can build a heavy native scientific stack (the canonical conda-lock 
`trialsim` env — see Simulation environment), pull structures, and iterate on failures — exactly 
what a Devin session is. One session per event keeps runs isolated, independently retryable, 
and observable (the same design the pipeline uses throughout).

`app/simulation.py` is the canonical, CLI-runnable pipeline. Devin **clones a pinned
commit** (`SIM_REPO_URL` @ `SIM_REPO_COMMIT`), builds the canonical conda-lock `trialsim`
env (`conda-sim.lock.yml` + `scripts/install_fpocket.sh`; `requirements-sim.txt` is only a
pip fallback that lacks ProDy/fpocket, so it cannot run the covalent/pocket routes), runs
the selected estimator (`python -m app.simulation --estimator <id>`), and reports back
a single `SIM_RESULT_JSON:` line the service parses. The source is **cloned, not
embedded** in the prompt — so the prompt no longer grows with the pipeline (the old
30k-character ceiling is gone) and every run names the exact commit it came from.

### Estimators: one interface, many models (Vina is not the architecture)

The docking + PK/PD pipeline is *one* estimator, not the system. An **`Estimator`**
(`app/estimators.py`) is anything that turns `(target, drug, tissue, dose)` into a
`SimResult` and carries a stable `id` (`name@version`); the harness — trigger, sandbox,
result contract, reproducibility, corpus — is model-agnostic. Two ship today:

| Estimator id | What it is |
|---|---|
| `vina-docking-pkpd@3` | The real structure-based docking + PK/PD pipeline (the default). Bumped `@1→@2` when pocket-aware routing changed the ΔG numbers, then `@2→@3` when result semantics changed (no Kd, no Kd-derived occupancy, a geometric `binding_engagement` classification). |
| `ligand-efficiency-baseline@2` | A deliberately naive, **structure-free control**: ΔG ≈ 0.3 kcal/mol × heavy-atom count, run through the same PK/PD model. Not a physical model — a floor the docking must beat to justify its cost. Reported at low confidence and flagged in `warnings`; `binding_engagement` is `no-structure`. Bumped `@1→@2` with the semantics change. |

This baseline isn't a strawman: it's capturing the same confound (ligand size) that the 8-anchor 
validation found dominates both Vina and MM-GBSA (ρ ≈ +0.4–0.45 vs. heavy-atom count) — so a real 
estimator has to add signal beyond size to clear it, which is a meaningfully harder bar than 
"beat a naive baseline" usually implies.

The **comparison is the product**, not any single model's number: `/analysis` shows an
estimator head-to-head for any trial scored by more than one estimator (and
`compare_estimators.py` runs a trial through several at once). Two estimators agreeing
is *not* evidence the science is right — the baseline is a control, not a second opinion.

### The result contract (and why it has `estimator` + `code_patched` fields)

Every result names the model that produced it (`estimator`) — a corpus that mixes model
versions without recording which one made each number is uninterpretable, and a
head-to-head is impossible without it. So `estimator` is part of the contract, not
metadata.

A Devin session is an *agent*, not a runner: when a step fails it will fix it and
carry on. That is exactly what you want for `pip install` problems — and exactly what
you do **not** want for the science, because a session that quietly edits
`simulation.py` reports numbers that did not come from the code in this repo. Two real
cases bit us: PubChem renamed the SMILES property (`CanonicalSMILES` →
`ConnectivitySMILES`/`SMILES`), and a cryo-EM structure was mmCIF-only (that mmCIF gap is
now fixed natively — see Limitations). Both times the run "succeeded" with plausible values,
and both times the committed code could not have produced them.

So the contract makes divergence *loud*: the session must set `code_patched: true` and 
`patch_summary` if it modified the script. Because the run is pinned to `SIM_REPO_COMMIT`, 
this isn't just a self-report to trust — a reviewer can diff the session's actual code against 
the exact pinned commit, so even an unreported patch is independently detectable, not just an 
honestly-flagged one.

---

## Module map

```
app/
  __init__.py       # application factory — wires config + db + devin + alerter + tickers
  binding_site.py   # pocket-aware routing: covalent-tethered → curated/discovered holo → fpocket → blind
  config.py         # 12-factor config from environment variables
  db.py             # SQLite data-access layer (single `trial_events` table, no ORM)
  signing.py        # HMAC-SHA256 sign/verify (shared with the watcher)
  prompts.py        # builds the simulation task each Devin session receives (clone pinned commit)
  simulation.py     # REAL physics: docking (Vina) + closed-form PK/PD. Runs in Devin.
  estimators.py     # Estimator interface + registry: Vina pipeline + labelled baseline control
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
requirements-sim.txt# pip fallback for sim deps (no ProDy/fpocket); canonical is conda-sim.lock.yml
simulate_trial.py   # fires signed trial-event payloads (stand-in for the watcher)
run_real.py         # fire ONE real trial event end to end (creates a real Devin session)
compare_estimators.py  # race one trial through 2+ estimators head-to-head (real sessions)
demo_e2e.py         # offline walkthrough of the whole pipeline (fakes Devin; no API key)
poll_watch.py       # poll in-flight sessions until they settle
verify_docking_box.py  # measures what fraction of the receptor the docking box contains
                       # — reproduces the coverage figures behind the blind-box fallback
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
# canonical env (needed for the covalent/pocket routes below — see Simulation environment):
conda-lock install --conda "$(command -v micromamba)" --name trialsim conda-sim.lock.yml
bash scripts/install_fpocket.sh
# default docking estimator:
python -m app.simulation --target KRAS --drug sotorasib --tissue tumor --dose 960 --json-only
# pick an estimator explicitly (see `app/estimators.py` for ids):
python -m app.simulation --target KRAS --drug sotorasib --estimator ligand-efficiency-baseline@2 --json-only
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
Signed with `X-CTGov-Signature: sha256=<hmac>`. **The endpoint fails closed:** with no
`WATCHER_SHARED_SECRET` configured it rejects *every* request (`503`); with the secret set, a
missing or bad signature is a `401`.
An optional `"estimator": "<id>"` selects which estimator runs (default: the docking
pipeline); an explicit id also lets the same trial be stored under two estimators for
a head-to-head. An unknown id is a `400`.

---

## Configuration

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `DEVIN_API_KEY` | yes | — | Authenticates Devin API calls. |
| `WATCHER_SHARED_SECRET` | **yes (webhook)** | — | HMAC secret. The webhook **fails closed**: unset ⇒ every request is rejected (`503`); set ⇒ signatures are enforced (bad/missing ⇒ `401`). |
| `SIM_REPO_URL` | no | `…/trial-impact` | Repo Devin clones to run the simulation. |
| `SIM_REPO_COMMIT` | **yes (real runs)** | — | Exact commit Devin checks out. Empty = *not configured*: the webhook refuses to launch an unpinned (unverifiable) session. `run_real.py`/`compare_estimators.py` fall back to local `git HEAD`. |
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
  function, not a rigorous binding free-energy method; ΔG here is retained as a
  diagnostic, not a measured affinity. See [`validation/README.md`](validation/README.md)
  for the calibration result.
- **Generic PK constants** ○ — `ka`, `Vd`, `CL` are fixed physiological placeholders
  and `Kp` is order-of-magnitude, not drug-specific. There is also **no bioavailability
  term** (`F` is implicitly 1), which flatters oral exposure, and `cmax_ng_ml` is a
  **tissue** concentration (`Kp`-scaled), not the plasma Cmax the name implies; AUC is
  AUC(0–48h), not AUC(0–∞). There's no clean API for human
  PK params; allometric scaling needs animal data and structure→PK ML (ADMET-AI /
  pkCSM) is only ~±80%. The pragmatic path is per-drug **enrichment overrides**
  (same mechanism as `endpoint_outcome`); mechanistic `Kp` (Rodgers–Rowland) needs
  pKa + fu on top of the logP we already compute.
- **Single structure, rigid receptor** ○ — one experimental (or AlphaFold) structure
  per target, no ensemble or flexible-side-chain docking. Vina supports both
  (ensemble = dock the ranked PDBe structure list; flex = split rigid/flex PDBQT);
  deferred because they change every run's numbers.
- **Structure is pinned for curated classes / discovered holo, else run-time-ranked** ◑ —
  curated target classes pin a drug-bound holo structure (KRAS G12C → `6OIM`, CFTR potentiator →
  `6O2P`), and reversible drugs can auto-discover a co-crystal by RCSB graph-relaxed chemical
  search, so those runs dock a fixed, drug-relevant structure and are reproducible by
  construction. Uncurated/undiscovered targets still fall back to PDBe/SIFTS `best_structures`
  ranked *at run time* (recorded, not fixed), so a future re-run could dock a different structure
  and return a different ΔG. **Discovery caveat:** it currently takes the first chemical-search
  hit rather than ranking candidates by resolution/method/coverage; provenance records the chosen
  entry so the choice is auditable.
- **`fetch_structure` reads mmCIF natively** ✅ — it downloads `…/{pdb_id}.pdb` first and, on a
  404, **falls back to `…/{pdb_id}.cif` and converts it with `gemmi`** (`_cif_to_pdb`:
  `read_structure` → `setup_entities` → `write_pdb`) *before* degrading to AlphaFold. Many modern
  cryo-EM structures are **mmCIF-only** and 404 on the legacy `.pdb` endpoint (typically *because*
  they are too large for the legacy format); they now dock as real experimental structures.
  `provenance.structure_format` records `"pdb"` vs `"mmCIF"`. Experimental structures are still
  preferred over AlphaFold; AlphaFold remains the fallback only when RCSB has neither a PDB nor an
  mmCIF file.
  **Consequence for the recorded runs:** the native-mmCIF path stays available for any target
  whose only structure is mmCIF-only, but the two published runs no longer exercise it — both now
  pin a curated drug-bound holo (`6OIM`, `6O2P`) fetched as legacy `.pdb`. (The previous CFTR pin
  `9MXL` actually contained **(R)-BPO-27, not ivacaftor**, so its box was never near the ivacaftor
  site; `6O2P` is the real ivacaftor–CFTR complex, ligand code `VX7`.) `gemmi.write_pdb` re-emits
  fixed-column PDB text; a very large complex that overflows PDB columns would still need a
  mmCIF-native receptor path, which is future work.
- **AlphaFold fallback URL was pinned to a stale version** ✅ — AFDB stamps a model
  version into the filename (`…-F1-model_v6.pdb`) and bumps it over time. The code
  hardcoded `v4`, which AFDB has since rolled past, so **every** AlphaFold fallback
  404'd — the safety net for targets with no experimental structure was silently dead,
  turning a graceful degradation into a hard failure. Now resolved via the AFDB API
  (`/api/prediction/{acc}`) with a newest-first version probe as backup; the 3D viewer
  chains `v6 → v5 → v4` for the same reason.
- **Docking box is routed to the pocket, with a disclosed fallback ladder** ◑ —
  The blind, centroid-centered box (which covered only
  ~26% of CFTR and, once a receptor exceeded the 40 Å cap, silently searched a central *slab*)
  is **no longer the default**. `app/binding_site.select_binding_site` routes every run through
  an explicit ladder and records the tier in `docking_box.mode`:

  | Tier | `mode` | Box comes from |
  |---|---|---|
  | 1 | `covalent-tethered (curated holo)` | reactive Cys of a curated covalent class (see covalent entry) |
  | 2 | `holo-ligand (curated)` | bound co-crystal ligand in a curated drug-bound structure |
  | 3 | `holo-ligand (discovered)` | co-crystal ligand in an RCSB graph-relaxed chemical-search hit |
  | 4 | `fpocket` | top-ranked geometric pocket (fpocket) |
  | 5 | `blind` | legacy centroid box — last resort |

  The two published runs now box the correct pockets: **KRAS** docks the switch-II pocket of
  `6OIM` (`covalent-tethered`, box `[22,22,22]` on Cys A:12), **CFTR** the ivacaftor site of
  `6O2P` (`holo-ligand (curated)`, box centered on VX7). This replaces the old blind slab that
  put CFTR's ΔG in an arbitrary sub-volume.
  **Remaining caveats (documented, not fixed):**
    * **Cognate/holo docking is partly circular** — redocking a drug into its own bound pocket
      inflates apparent accuracy; the ΔG is pocket-correct but is not an independent prediction
      of *where* the drug binds.
    * **fpocket is geometric, not biological** — it ranks cavities by shape, not function. On
      `6O2P` its top pocket sat **~79 Å** from the real ivacaftor site, which is exactly why it
      is a low-priority *fallback*, not a pocket oracle.
    * **The blind box is still wrong where it fires** — the Tier-D fallback keeps the 40 Å-cap
      slab behaviour that
      `test_docking_box_stops_covering_the_receptor_once_the_40A_cap_binds` pins. It is now the
      last resort rather than the default, but any target with no co-crystal and no fpocket still
      hits it. Simply enlarging it is not a fix (an uncapped CFTR box is ~2.4 M Å³, past where
      Vina's sampling is meaningful).
- **The blind fallback box is computed over atoms that aren't docked** ○ — `compute_docking_box`
  (**Tier-D only**) reads `ATOM` *and* `HETATM`, while `prepare_receptor_pdbqt` docks `ATOM` only,
  so the fallback box centers on a slightly different atom set than Vina searches. The pocket-aware
  tiers are unaffected — they box the co-crystal ligand or the reactive residue directly. Small in
  practice, wrong in principle; now scoped to the last-resort fallback.
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
- **Docking runs were non-deterministic, and single-seed precision was overstated** ✅
  — `run_vina` passed `seed=0`, which Vina interprets as *"choose a random seed"*, so repeat
  runs of the same drug/target drifted (ΔG −8.42 / −8.59 / −8.59 for sotorasib–KRAS). Pinning a
  single seed fixed reproducibility but concealed sampling variance while still reporting ΔG to
  three decimals. `run_vina(seed=…)` now docks across a **deterministic seed set** (`_derive_seeds`
  → 42, 43, 44 — the set is fixed, so runs stay bit-reproducible), and `dock_replicates` → `summarize_dg`
  returns mean ΔG, sample sd and n. **No absolute Kd is derived** from the mean ΔG; the sd feeds
  `_dg_noise_penalty` (0.5·sd, capped at 0.2) into `confidence` and gates the `binding_engagement`
  classification (an experimentally-resolved site with sd ≤ 0.75 is a *reproducible* experimental-site),
  so docking noise propagates into the PoS delta and the engagement label instead of being hidden.
  The observed spread here is small (0.187 / 0.007 kcal/mol for the KRAS / CFTR published runs).
  **Caveats**: this measures **sampling noise only** — not model bias, box placement, or scoring-function error,
  which dominate and re-seeding cannot see; cost is linear in seed count (3× docking time). The
  structure-free baseline does **not** get replicate semantics — it's deterministic, so its sd is `None`.

### Market model
- **Uncalibrated, hand-tuned** ○ — the PoS delta is deterministic and additive (`pos_breakdown`), so the
  headline number can never disagree with its own breakdown, but the weights and thresholds are magic
  numbers. Needs backtesting against historical biotech readouts and actual next-day price moves to fit them.
- **No phase weighting — by design** — the chemistry answers one phase-invariant, preclinical/discovery-stage
  question, so there's nothing to weight; a Phase 2/3 run is a retrospective pipeline benchmark, not a
  tradeable signal.
- **Naive competitor read-through** ○ — competitors are assumed to move opposite the sponsor, one magnitude
  bucket softer. Real read-through depends on mechanism/target overlap and modality, not just "is a competitor."
- **`endpoint_outcome` not auto-derived** ○ — met/missed comes from manual enrichment (`watchlist.json`),
  not parsed from CT.gov. An LLM classifier over the results section / press releases would close the loop.

### Architecture & operations
- **The shipped second estimator is a control, not a rival model** ○ —
  `ligand-efficiency-baseline@2` is deliberately naive (a heavy-atom size proxy), not a validated affinity method.
  Two estimators agreeing is not evidence the physics is right — a real head-to-head still needs a second physical
  estimator (co-folding / FEP / QSAR).
- **Pinning buys reproducibility, not validity** ○ — `SIM_REPO_COMMIT` makes a run reproducible and `code_patched`
  verifiable but does nothing for the scientific caveats above, and is distinct from **structure** pinning
  — the resolved `pdb_id` is still chosen at run time.
- **One Devin session per estimator** ○ — a head-to-head launches an independent real session per estimator,
  so cost and failure modes scale with the count.

### Security & operations
- **No retries or timeouts on hung sessions** ○ — a `blocked` or hung session is left for a human; nothing escalates it.
- **SQLite, single process** ○ — fine for a prototype, wrong for concurrent writers; Postgres is the obvious swap.

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

### Simulation environment (the heavy docking stack)

The docking/PK-PD physics needs RDKit, AutoDock Vina, Meeko, Open Babel, Gemmi and ProDy
on a mutually-compatible libboost. The **canonical, reproducible** install is the conda
lock; `requirements-sim.txt` is a best-effort pip fallback that cannot pin the native
stack (and lacks ProDy, so it can't run the covalent-tethered route):

```bash
# canonical: exact linux-64 solve of environment-sim.yml
conda-lock install --name trialsim conda-sim.lock.yml     # or micromamba create -n trialsim -f conda-sim.lock.yml
bash scripts/install_fpocket.sh                            # fpocket: source-built, not on conda channels
python regen_artifacts.py                                  # real docking → results/ artifacts
```

Documented version drift from the original pip pins (see `environment-sim.yml`): RDKit
`2024.03.5 → 2025.09.5` and Vina `1.2.5 → 1.2.7` (the old RDKit needs libboost 1.84 while
Vina 1.2.7 needs 1.86, so they cannot co-resolve; the newer RDKit shares Vina's 1.86),
and Meeko `0.6.0 → 0.7.1` (0.6.0 was withdrawn from PyPI). fpocket is built from a pinned
source tag because it is not distributed on conda-forge/bioconda; a run works without it
by degrading to the blind box.

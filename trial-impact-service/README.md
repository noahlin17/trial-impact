# Trial Impact Service

An event-driven system that turns a **clinical-trial readout** into a
**share-price impact commentary**. When a trial event arrives, the service spins
up an isolated **[Devin](https://docs.devin.ai/api-reference/v1/overview)** session
that runs a real **biophysical simulation** (protein–ligand docking + PK/PD),
scores the result with a transparent market model, and — on a market-moving
readout — alerts to Slack/email while surfacing everything on a dashboard.

> **Not investment advice.** Output is an automated research signal for
> informational purposes only. A disclaimer is attached to every assessment.

> **Scope — preclinical / Phase 1 is the forward-looking tier.** The physics answers whether a
> molecule *engages its target* — a fixed molecular property largely proven out by end of Phase 1 —
> so Phase 1 is the only tier where the chemistry carries new information. A Phase 2/3 run is not a
> tradeable signal but a **retrospective re-simulation**: the drug already cleared Phase 1 and
> (often) has a public outcome, so re-running the fixed chemistry on it benchmarks the pipeline
> against a known readout rather than predicting one — the open Phase 2/3 questions (efficacy,
> statistics, safety at scale) are ones the pipeline does not model. See the root
> [README](../README.md#trial-phase--the-preclinical--phase-1-scope) and
> [THESIS.md §3.3](../THESIS.md).

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
structure (UniProt → experimental PDB or mmCIF, else AlphaFold), fetch the ligand
(PubChem → SMILES → RDKit 3D), dock with **AutoDock Vina** across a fixed seed set for a real
binding free energy ΔG reported as mean ± sd (the scalar only — the pose is *not* returned; see
Limitations), then solve the PK/PD model in **closed form**
(Bateman) for tissue exposure (Cmax/AUC). The ΔG is reported as a geometric target-engagement
classification, **not** a calibrated affinity — no absolute Kd or occupancy (issue #4). That needs a full sandbox that
can build a heavy native scientific
stack (the canonical conda-lock `trialsim` env — see Simulation environment), pull structures, and iterate on failures — exactly what a Devin session is.
One session per event keeps runs isolated, independently retryable, and observable
(the same design the pipeline uses throughout).

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
| `vina-docking-pkpd@3` | The real structure-based docking + PK/PD pipeline (the default). Bumped `@1→@2` when pocket-aware routing changed the ΔG numbers, then `@2→@3` when issue #4 changed the result semantics (no Kd, no Kd-derived occupancy, a geometric `binding_engagement` classification). |
| `ligand-efficiency-baseline@2` | A deliberately naive, **structure-free control**: ΔG ≈ 0.3 kcal/mol × heavy-atom count, run through the same PK/PD model. Not a physical model — a floor the docking must beat to justify its cost. Reported at low confidence and flagged in `warnings`; `binding_engagement` is `no-structure`. Bumped `@1→@2` with the #4 semantics change. |

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
`patch_summary` if it modified the script, and a patched run is surfaced on `/status`
as **not reproducible from source**. Because the run is now pinned to `SIM_REPO_COMMIT`,
that self-report is also **independently verifiable** — a reviewer can diff the session
against the exact commit — rather than trusted on the agent's word. A plausible number
is not a correct number, and a number you cannot regenerate is not a result.

---

## Module map

```
app/
  __init__.py       # application factory — wires config + db + devin + alerter + tickers
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
                       # — reproduces the coverage figures behind open issue #2
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
- **The "high-accuracy universe" is routed by chemistry/target class, not drug name** ◑ —
  `app/binding_site.select_binding_site` classifies each run and boxes it accordingly, with no
  per-drug branching, so **net-new drugs route themselves**. The universe we now dock *more
  accurately than the old blind box* is: (a) **reversible** drugs with any experimental
  co-crystal — curated per target class or auto-discovered by RCSB graph-relaxed chemical search
  (ranked by which structure best resolves the pocket: sharpest method, then best resolution,
  then a deterministic id tiebreak) — boxed on the real bound ligand; and (b) **covalent** drugs
  whose warhead is a tetherable
  Michael acceptor **and** whose target is a curated covalent class (KRAS G12C, EGFR, BTK),
  tethered to the geometrically-detected reactive cysteine. Everything else degrades to fpocket
  then the blind centroid box and **says which tier it took** in `docking_box.mode`. The routing
  ladder, the covalent lower-bound caveat, and the fallback limitations are detailed under the
  **Docking box** and **Covalent binders** entries below. A key structural constraint: a covalent
  co-crystal ligand is the *reacted adduct*, so its chemical identity ≠ the free drug's — covalent
  targets therefore key off the curated class + structure-derived reactive residue, not ligand
  matching.
- **Small molecules only** ○ — the docking path models small-molecule drugs;
  biologics/antibodies can't be docked and are out of scope.
- **Docking is fast & approximate** ○ — AutoDock Vina is an empirical scoring
  function, not a rigorous binding free-energy method. FEP / MM-GBSA are more
  accurate but far heavier; ΔG here is a *relative* signal, not a measured affinity.
- **Free-drug occupancy machinery landed (issue #1), now dormant for docking (issue #4)** ◑ —
  `_pkpd_series` can evaluate `occ = C_free / (C_free + Kd)` with `C_free = fu · C` (only
  **unbound** drug engages a target), and `resolve_fu(drug, fu_hint)` resolves `fu` from an
  explicit hint > a small curated plasma-protein-binding table > unknown (`fu = 1.0` with a
  warning). But occupancy requires a Kd, and issue #4's 8-anchor calibration showed the Vina
  score cannot supply one — so **the docking estimator now reports `target_occupancy_pct = None`**
  and never enters the occupancy branch. The machinery is kept intact for any future estimator
  that produces a calibrated Kd; a legacy artifact that *does* carry a stored Kd still
  reconstructs its occupancy curve. Exposure (Cmax, AUC) is Kd-independent and is retained. This
  is why the market model below has **no occupancy term** any more.
- **`druglikeness_flag` is a drug-likeness heuristic, and is no longer priced** ✅ —
  [issue #3](../README.md#known-issues), fixed. It is `≥2 Lipinski Rule-of-5 violations`
  (`mw>500, logp>5, hbd>5, hba>10`). Ro5 predicts **oral absorption and permeability**; it
  says nothing about safety. Sotorasib trips it on MW 560.6 + logP 5.30 — and sotorasib is
  an **approved, orally dosed drug** — so pricing it as a safety event was a category error.
  The market model previously charged **−0.15 PoS as if it were a safety finding**; that
  penalty is **removed**. The flag is renamed `tox_flag → druglikeness_flag` and surfaced as
  informational provenance only (it appears in the reasoning trace labelled *informational,
  not priced* and contributes `0.0` to the delta). A real safety signal would need a
  structural-alert model (PAINS / Brenk) or a tox QSAR — deliberately **not** faked here.
- **ΔG was consumed as an absolute Kd — resolved by re-scoping docking to geometric engagement** ✅ —
  [issue #4](../README.md#known-issues). The code used to convert the Vina score to an absolute
  `Kd = exp(ΔG/RT)` and branch on hard thresholds (`Kd ≤ 100 nM`, `ΔG ≤ −9.0`). An 8-anchor
  calibration through this exact pipeline showed the raw score does **not** rank measured affinity
  (`r(−ΔG, affinity) ≈ −0.39`) and instead tracks ligand size (`r(−ΔG, heavy-atoms) ≈ +0.64`);
  ligand-efficiency normalization did not rescue it, and `exp()` being monotonic means no
  post-transform can recover affinity the score lacks. **Fix (implemented):** the docking
  estimator no longer emits an absolute Kd or a Kd-derived occupancy (both `None`); the ΔG is kept
  as a clearly-labelled relative *score* and the uncalibrated `exp(ΔG/RT)` value survives only in
  `provenance.vina_pseudo_kd_nM` with a "NOT an affinity" note. `classify_engagement` maps the run
  to a geometric `binding_engagement` (`experimental-site` / `experimental-site-noisy` /
  `predicted-pocket` / `no-site` / `no-structure` / `failed`), gated on a reproducible multi-seed
  pose (sd ≤ 0.75). A cross-target relative binding *band* is deliberately **not** shipped (it
  would be size-in-disguise). Recovering a real strength signal needs a different scorer class
  (gnina CNN rescoring / MM-GBSA / FEP) — added as a new estimator, not faked now.
- **A physics rescorer (MM-GBSA) was tested and also failed — so no strength estimator ships** ✅ —
  the natural next move was to rescore the docked poses with single-snapshot MM-GBSA (OpenMM /
  ff14SB / GAFF-2.11 / OBC2 implicit solvent, ligand minimized in a rigid receptor), which adds the
  electrostatics + desolvation terms Vina omits. Validated on the **same 8 anchors** (see
  [`validation/`](validation/README.md)): MM-GBSA does **not** beat Vina and does **not** rank
  measured affinity — Spearman ρ(MM-GBSA, pKd) = **−0.24** (95% CI [−0.93, +0.62]) vs ρ(Vina) =
  −0.24, and both still track ligand size (ρ ≈ +0.4). Applying the same discipline used on Vina, the
  cheap MM-GBSA is **not shipped as a binding-strength estimator** (that would repeat issue #4's
  overclaim). The honest conclusion: cross-target affinity ranking needs either a congeneric
  same-target series or far more expensive sampling (explicit-solvent MM-GBSA ensembles / FEP) —
  documented, not forced. Regenerate with `make validate`.
- **Generic PK constants** ○ — `ka`, `Vd`, `CL` are fixed physiological placeholders
  and `Kp` is order-of-magnitude, not drug-specific. There is also **no bioavailability
  term** (`F` is implicitly 1), which flatters oral exposure, and `cmax_ng_ml` is a
  **tissue** concentration (`Kp`-scaled), not the plasma Cmax the name implies; AUC is
  AUC(0–48h), not AUC(0–∞). There's no clean API for human
  PK params; allometric scaling needs animal data and structure→PK ML (ADMET-AI /
  pkCSM) is only ~±80%. The pragmatic path is per-drug **enrichment overrides**
  (same mechanism as `endpoint_outcome`); mechanistic `Kp` (Rodgers–Rowland) needs
  pKa + fu on top of the logP we already compute.
- **Covalent binders are tethered to the right pocket, but still scored reversibly** ◑ —
  a flagged covalent warhead (RDKit SMARTS) against a **curated covalent target class**
  (KRAS G12C, EGFR, BTK) is now routed through a covalent-tethered box. `app/binding_site.py`
  finds the class's reactive cysteine **geometrically** — the Cys Sγ within ~2.5 Å of the bound
  ligand in the curated holo structure, *not* a hardcoded residue number — Meeko tethers the
  warhead to it (`mk_prepare_ligand --tether_smarts`), and Vina docks in a tight box centered on
  that residue (`docking_box.mode: "covalent-tethered (curated holo)"`, with the reactive residue
  and warhead in provenance). This fixes the **pocket** (decisive for KRAS's cryptic switch-II
  site) and seeds a covalent-geometry pose.
  **What it is NOT:** the Vina score is still the **reversible** scoring function — no covalent
  bond enthalpy is added — so this is a pocket-correct, geometry-tethered *lower bound*, not true
  reactive scoring. The Python `vina` bindings cannot consume Meeko's flexible-residue covalent
  output (they reject its `BEGIN_RES`/`END_RES` records and expect a `TORSDOF` line, which the
  prep strips/adds), so full reactive/flexible-residue docking needs AutoDock-GPU — not on the
  conda channels, deferred. Only **Michael-acceptor/acrylamide** warheads are tetherable today;
  other detected warheads and non-curated targets fall back to reversible docking **with a
  warning**. `covalent_flag` is still not read by the market model, so KRAS's understated ΔG is
  not compensated downstream.
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
  [issue #2](../README.md#known-issues). The blind, centroid-centered box (which covered only
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
- **Docking runs were non-deterministic** ✅ — `run_vina` passed `seed=0`, which Vina
  interprets as *"choose a random seed"*, so repeat runs of the same drug/target drifted
  (ΔG −8.42 / −8.59 / −8.59 for sotorasib–KRAS). Now pinned to a fixed seed *set* (42, 43, 44)
  and reported as mean ± sd (below). Reproducible numbers are a precondition for the result
  contract meaning anything.
- **Reported precision now reflects seed variability** ✅ — [issue #11](../README.md#known-issues),
  core retired. Pinning a single seed made runs reproducible but concealed the sampling variance
  and still reported ΔG to three decimals. `run_vina(seed=…)` now docks across a **deterministic
  seed set** (`_derive_seeds` → 42, 43, 44; the *set* is fixed, so runs stay bit-reproducible),
  and `dock_replicates` → `summarize_dg` returns mean ΔG, sample sd and n. The result carries
  `binding_affinity_kcal_mol` (mean), `binding_affinity_sd_kcal_mol` and `replicates`; **no
  absolute Kd is derived** from the mean ΔG any more (issue #4); the sd feeds `_dg_noise_penalty`
  (0.5·sd, capped at 0.2) into `confidence` **and** gates the `binding_engagement` classification
  (an experimentally-resolved site with sd ≤ 0.75 is a *reproducible* `experimental-site`), so
  docking noise propagates into the PoS delta and the engagement label instead of being hidden. The observed spread here is small (0.010 / 0.052 kcal/mol).
  **Caveats:** this measures **sampling noise only** — not model bias, box placement, or
  scoring-function error, which dominate and re-seeding cannot see; the cost is linear in seed
  count (3× the docking time); and `cmax_ng_ml` remains a **tissue** concentration (`Kp`-scaled),
  not plasma Cmax, with AUC over 0–48 h. The structure-free baseline does **not** get replicate
  semantics — it is deterministic, so its sd is `None`.

### Market model
- **Uncalibrated, hand-tuned** ○ — deterministic and fully inspectable: the PoS
  delta is built additively (`pos_breakdown`) and the headline number derives from
  that breakdown, so they can never disagree. But the weights (0.5 / 0.2 / 0.15…)
  and thresholds are magic numbers. The real fix is **backtesting** against
  historical biotech readouts and actual next-day price moves to fit them.
- **Docking is priced only as a capped geometric corroborator (issue #4)** ✅ — the market model
  no longer has an affinity-strength term or an occupancy term. Because the Vina score cannot
  rank affinity, `pos_breakdown` prices only a small, capped **+0.05** bonus when
  `binding_engagement == "experimental-site"` (the ligand docked into an experimentally-resolved
  site with a reproducible pose), and applies it **only to a positive readout** — docking can
  never rescue a missed endpoint, and the no-readout gate still yields no call. It never reads
  `kd_nM`, raw-ΔG thresholds, or occupancy. This replaces the former `binding_modifier` /
  `occupancy_modifier` terms with a single `engagement_modifier`.
- **Missed-trial asymmetry** ✅ — fixed. Modifiers are now applied by meaning
  (efficacy corroboration only strengthens a win) rather than mirrored by the readout
  sign, which previously let the drug-likeness flag reduce the downside of a *failed*
  trial. The met-trial path is unchanged. (The flag itself is now unpriced — issue #3 —
  so it can no longer move any call regardless of sign.)
- **Spurious alerts on `unknown` outcomes** ✅ — fixed, and this one was live on the
  *common* path. Every term in `pos_breakdown` is a modifier on a clinical readout, but
  they were applied even when there was no readout: an `unknown` outcome (base `0.0`)
  plus a (then-priced) drug-likeness flag scored `-0.15 × 0.95 = -0.1425`, which clears
  the `0.10` market-moving threshold and emits a **"down" call on a trial that has reported
  nothing** — a directional signal derived purely from the drug's Lipinski violations.
  (That flag is now unpriced entirely — issue #3 — so this path is doubly closed.)
  And `unknown` is the *default* for every trial the watchlist has not enriched, so this
  was the majority path in production, not an edge case. The modifiers are now gated on
  `has_readout`, so no readout means no call. Both published runs are `met`, so their
  numbers are byte-identical — a regression test asserts exactly that.
- **No phase weighting — by design** — the forward-looking scope is **preclinical / Phase 1
  only** (binding is a molecular property established by end of Phase 1; Phase 2/3 test
  efficacy and trial statistics the physics does not model), so there is a *single*
  actionable tier and nothing to weight. A Phase 2/3 run is a **retrospective re-simulation**
  against a known readout — a pipeline benchmark, not a tradeable signal. See
  [the preclinical / Phase 1 scope](../README.md#trial-phase--the-preclinical--phase-1-scope).
- **Naive competitor read-through** ○ — competitors are assumed to move opposite the
  sponsor, one magnitude bucket softer. Real read-through depends on mechanism /
  target overlap and modality, not just "is a competitor."
- **Sponsor→ticker resolution is a hand-maintained 6-entry file** ○ — `tickers.json` maps six
  sponsors (amgen, regeneron, vertex, moderna, biogen, lilly) to a ticker plus a **hardcoded
  competitor list**. Any claim about pointing the watcher at a therapeutic area, or building a
  corpus across the trial universe, runs straight into this file. Real resolution is an
  **entity-resolution problem**, not a lookup: CT.gov sponsor strings are messy and
  inconsistent, sponsors are frequently subsidiaries of a listed parent, **many are private or
  pre-IPO** (no ticker — and therefore no trade), and licensed or partnered assets sit with a
  different economic owner than the sponsor. The competitor map is worse, because "who is a
  competitor" is a modelling judgment rather than a fact. **Fix:** an entity-resolution step
  (sponsor string → legal entity → listed parent → ticker) with explicit handling for private
  sponsors, and competitors derived from target/mechanism overlap rather than hardcoded.
  **Until then the system runs on a watchlist, not a universe** — the demo is honest, the
  scaling claim is not yet earned.
- **`endpoint_outcome` not auto-derived** ○ — met/missed is supplied via enrichment
  (`watchlist.json`), not parsed from CT.gov. An LLM classifier over the results
  section / press releases would close the loop.

### Architecture & operations
> The harness/estimator split and the pinned-commit checkout (former issues #5/#6) are
> **done** — see [Estimators](#estimators-one-interface-many-models-vina-is-not-the-architecture)
> for how they work. The residual open caveats they introduced are below.

- **The shipped second estimator is a control, not a rival model** ○ —
  `ligand-efficiency-baseline@2` is a heavy-atom size proxy (ΔG ≈ 0.3 kcal/mol × atom),
  deliberately naive: a floor for docking to beat, **not** a validated affinity method (its ΔG
  is low-confidence and flagged in `warnings`). So two estimators agreeing is **not** evidence
  the physics is right — a real head-to-head still needs a second *physical* estimator
  (co-folding / FEP / QSAR), and `docking_box` remains a Vina-specific field on the shared
  contract until one exists.
- **Pinning buys reproducibility, not validity** ○ — `SIM_REPO_COMMIT` makes a run
  reproducible-from-source and `code_patched` verifiable, but does nothing for the scientific
  caveats above (docking box, PK constants, cognate circularity all stand; ΔG-as-absolute and
  occupancy are now resolved by the #4 re-scope), and is
  distinct from **structure** pinning — the resolved `pdb_id` is still chosen at run time.
- **One Devin session per estimator** ○ — a head-to-head launches an independent real session
  per estimator, so cost and failure modes scale with the count and arms can fail independently;
  `/analysis` shows a comparison only once **more than one** estimator has completed for a trial.

### Security & operations
- **Webhook signature verification fails closed** ✅ — [issue #8](../README.md#known-issues),
  fixed. `/webhook/trial-update` now rejects *every* request with `503` when
  `WATCHER_SHARED_SECRET` is unset, so a forgotten secret yields a **dark** endpoint, never
  an open, billable one — an unauthenticated caller can no longer spend a real Devin session.
  With the secret set, a missing or bad signature is `401`. `create_app` still logs a loud
  startup warning when the secret is absent so the disabled state is obvious. (Local/demo
  runs sign with the same secret via `WATCHER_SHARED_SECRET`, as the quick-start shows.)
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

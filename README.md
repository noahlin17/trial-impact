# Trial Impact

Turn a **clinical-trial readout** into a **share-price impact call** — by running a
real biophysical simulation of the drug against its target and scoring the result.

When a trial posts results, the system spins up an isolated **[Devin](https://devin.ai)**
session that does genuine **protein–ligand docking (AutoDock Vina) + PK/PD** in a
sandbox, extracts the binding/exposure metrics, and a transparent market model
emits directional calls for the sponsor and its publicly-traded competitors —
surfaced on a dashboard with an interactive **3D view of the docked structure**.

> **Not investment advice.** Every output is an automated research signal for
> informational purposes only; a disclaimer is attached to each assessment.

---

## Architecture

```
ClinicalTrials.gov API v2 ──poll──▶  ctgov-watcher/            (gives CT.gov a webhook)
                                       │ diff records, detect material change
                                       ▼ POST /webhook/trial-update  (HMAC-signed)
┌──────────────────────────────────────────────────────────────────────────┐
│                     trial-impact-service/  (Flask)                       │
│  TRIGGER   verify signature → resolve tickers → create Devin session ────┼─▶ Devin session
│  ORCHESTRATE  Devin runs docking + PK/PD in its sandbox ◀────────────────┼── real ΔG, Kd,
│  RECONCILE /poll → parse SIM_RESULT_JSON → market model → alert          │   occupancy
│  OBSERVE   /status → dashboard (stats, price calls, 3D structure viewer) │
└──────────────────────────────────────────────────────────────────────────┘
```

Two independently-deployable services:

| Directory | What it is |
|-----------|-----------|
| [`trial-impact-service/`](trial-impact-service/) | The Flask analysis service: trigger → orchestrate (Devin) → observe → reconcile, SQLite read model, market model, alerts, 3D dashboard. |
| [`ctgov-watcher/`](ctgov-watcher/) | A tiny poller that diffs ClinicalTrials.gov v2 and emits signed webhooks (CT.gov has no native webhooks). |

Each has its own README with full detail.

### Why Devin
The tissue/protein simulation is **real biophysics**, not a stub: fetch the target
structure (UniProt → experimental PDB, else AlphaFold), fetch the ligand
(PubChem → SMILES → RDKit 3D), dock with **AutoDock Vina** for a real ΔG, then solve
a **SciPy** PK/PD ODE for tissue exposure and target occupancy. That needs a full
sandbox that can `pip install` a heavy scientific stack, pull structures, and
iterate on failures — one isolated Devin session per trial event.

---

## Results from two real Devin runs

These are genuine outputs from live Devin sessions (see [`results/`](results/) for
the raw JSON and the rendered 3D dashboards — open the `.html` files in a browser):

| Trial | Target × Drug | Structure | ΔG (kcal/mol) | Kd | Target occ. | Tox | Model call |
|-------|---------------|-----------|---------------|----|-----------|-----|-----------|
| Phase 1 | KRAS × sotorasib | 7VVB (RCSB) | **−8.585** | 892 nM | 97.5% | ⚠︎ flagged | ▲ AMGN strong · ▼ REGN/NVS |
| Phase 3 | CFTR × ivacaftor | 9MXL (RCSB, cryo-EM) | **−7.997** | 2317 nM | 84.7% | clean | ▲ VRTX strong · ▼ CRSP/BLUE |

The model correctly discriminates: sotorasib's tox flag falls out of its real
descriptors (MW 560 + logP 5.3 = 2 Lipinski violations); ivacaftor (1 violation) is
clean — so the two readouts get different probability-of-success deltas.

A **results-analysis view** (`GET /analysis`, exported to
[`results/analysis_dashboard.html`](results/analysis_dashboard.html)) lets you
inspect the whole corpus and learn from it: cross-run charts (ΔG/Kd/occupancy vs the
market call), a sortable comparison table, and a per-run drill-down with the 3D
docked structure, the reconstructed PK/PD exposure curve, and a step-by-step
**reasoning trace** of how each probability-of-success delta was built.

---

## Catching a bug: when the result was too clean

On the first real run, the stored result matched the example values embedded in my
own prompt — suspiciously exact. I didn't trust it. I pulled the raw Devin session
transcript and found the cause: the transcript includes the full prompt text (which
itself contains an example `SIM_RESULT_JSON` for formatting), and my extractor was
matching that example *before* it ever reached Devin's actual output further down
the transcript.

Fix: skip prompt-echo messages and take the last decodable result marker in the
transcript, plus a regression test that reproduces the exact scenario. The real
result — sotorasib's ΔG of −8.585 and Kd of 892nM, which falls straight out of its
actual molecular weight and logP — then flowed through correctly.

This is the habit behind the validation section below: a plausible number is not
a correct number until it's been checked.

---

## Validating the physics: checking predictions against real data

The two results above aren't just self-consistent outputs — I checked them against
published data on each drug's real binding behavior after the runs completed,
rather than assuming a plausible-looking number was a correct one (see the
prompt-echo bug above for why that habit matters here).

Both predictions come out weaker than real-world affinity — expected, since blind
docking is a coarse approximation. But the *size* of the gap tracks the underlying
chemistry in a way that isn't random: ivacaftor, a genuinely reversible binder, is
off by a margin that's normal for blind docking. Sotorasib is off by a much larger
margin — and sotorasib's real potency comes from forming a permanent covalent bond
to its target, a mechanism AutoDock Vina has no way to model, since Vina only scores
reversible, non-covalent binding.

That structure matters more than either number alone: the model's errors are
mechanistically explicable, not arbitrary. It also points directly at the fix — a
covalent-docking-aware tool for covalent inhibitors, or explicitly scoping v1 to
non-covalent mechanisms and flagging covalent drugs as out-of-scope until that's
added.

I did not adjust the pipeline, prompts, or reported numbers after finding this —
the results table shows the raw model output; this is an honest post-hoc check
against literature, not a correction folded back in.

---

## Quick start

```bash
cd trial-impact-service
cp .env.example .env          # set DEVIN_API_KEY (+ optional WATCHER_SHARED_SECRET, Slack/SMTP)
docker compose up --build     # dashboard at http://localhost:8000/status

# fire a real trial event (creates a real Devin session):
python run_real.py --target KRAS --drug sotorasib --tissue tumor --dose 960 --watch

# or an offline, faked walkthrough of the whole pipeline:
python demo_e2e.py
```

Run the tests / lint:
```bash
cd trial-impact-service && pip install -r requirements-dev.txt && ruff check . && pytest -q
```

---

## Next steps

**Tighten the science**
- Add covalent-docking support (e.g. CovDock) or explicitly flag covalent
  inhibitors as out-of-scope for v1 — Vina's non-covalent scoring systematically
  understates potency for drugs like sotorasib that bind irreversibly, as the
  validation above shows.
- Emit AutoDock Vina's top pose (PDBQT) in `SIM_RESULT_JSON` and render it in the
  binding pocket, so the 3D view shows the *actual* docked geometry — not the
  reference crystal ligand.
- Pocket-aware docking (known site / cavity detection) instead of a blind box, plus
  MM-GBSA rescoring; add a separate affinity path for biologics (antibodies can't
  dock). Pin the sim environment (conda-lock) so every Devin run is reproducible.

**Make the market call credible**
- Weight the probability-of-success delta by trial **phase** (Phase 1 ≪ Phase 3) and
  by whether it's the sponsor's lead asset / its market-cap exposure.
- Wire live quotes + market cap (the `MARKET_DATA_BASE` stub) and **backtest** calls
  against historical biotech readouts to calibrate direction and magnitude.
- Auto-derive `endpoint_outcome` (met/missed) from the CT.gov results section /
  press releases via an LLM classifier, instead of watchlist enrichment.

**Harden & ship**
- Enforce a structured result contract from Devin (require `structured_output`),
  handle `blocked`/hung sessions with retries + timeouts, and alert on sim failures.
- CI (GitHub Actions: ruff + pytest), Postgres instead of SQLite, and a deployed
  service + watcher with a scheduled `/poll`.
- A **results-analysis dashboard** to inspect and learn from accumulated runs
  (cross-run comparison, physics→price relationships, per-run drill-down). See the
  dedicated plan.

---

## Honest caveats
- The 3D viewer shows the **receptor structure the run used** (with its crystal
  ligand), not AutoDock Vina's exact docked pose — `simulation.py` currently returns
  scalar ΔG/Kd, not pose coordinates. Emitting the top pose is a clean next step.
- `endpoint_outcome` (met/missed) is not machine-readable from ClinicalTrials.gov;
  the watcher supplies it via per-trial enrichment (`watchlist.json`) for now.
- The market model is deliberately transparent/rules-based (not a black box) and is
  **not** calibrated to real market data — it's a research signal, not a trade.

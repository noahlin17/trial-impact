# Trial Impact

Turn a **clinical-trial readout** into a **share-price impact call** — by running a
real biophysical simulation of the drug against its target and scoring the result.

When a trial posts results, the system spins up an isolated **[Devin](https://devin.ai)**
session that does genuine **protein–ligand docking (AutoDock Vina) + PK/PD** in a
sandbox, extracts the binding/exposure metrics, and a transparent market model
emits directional calls for the sponsor and its publicly-traded competitors —
surfaced on a dashboard with an interactive **3D view of the structure it docked
against** (the pose itself is not returned — see Honest caveats).

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
the PK/PD model in **closed form** (Bateman) for tissue exposure and target occupancy.
That needs a full sandbox that can `pip install` a heavy scientific stack, pull
structures, and iterate on failures — one isolated Devin session per trial event.

---

## Results from two real Devin runs

Genuine outputs from live Devin sessions (see [`results/`](results/) for the raw JSON
and the rendered dashboards — open the `.html` files in a browser). Docking is
**seed-pinned**, so these reproduce: re-running a trial returns the same ΔG.

| Trial | Target × Drug | Structure | ΔG (kcal/mol) | Kd | Target occ. | Flags | Model call |
|-------|---------------|-----------|---------------|----|-----------|-----|-----------|
| Phase 1 | KRAS × sotorasib | 7VVB (RCSB, exp.) | **−8.606** | 863 nM | 97.6% | ⚠︎ tox · covalent | ▲ AMGN strong · ▼ REGN/NVS |
| Phase 3 | CFTR × ivacaftor | AF-P13569 (AlphaFold) | **−8.702** | 738 nM | 94.5% | clean | ▲ VRTX strong · ▼ CRSP/BLUE |

The model discriminates on real chemistry: sotorasib's tox flag falls out of its actual
descriptors (MW 560 + logP 5.3 = 2 Lipinski violations) and its acrylamide warhead
trips the covalent flag; ivacaftor (1 violation, reversible) is clean — so the two
readouts earn different probability-of-success deltas.

Both runs report **`code_patched: false`** — the numbers came from `simulation.py` *as
committed*, not from a session quietly patching it to get past a broken upstream API.
That field exists because it caught exactly that (see below).

> **Why CFTR uses a predicted structure.** An earlier run used the cryo-EM structure
> 9MXL at confidence 0.9 — but 9MXL is **mmCIF-only** and `fetch_structure` reads
> `.pdb`, so the committed code *cannot* fetch it; that number only existed because a
> Devin session worked around the gap in its sandbox. It has been retired in favour of
> the AlphaFold model at **confidence 0.7**, which is lower but honest and
> reproducible. Reproducible beats impressive.

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
result — sotorasib's ΔG of **−8.606** and Kd of **863 nM**, which falls straight out of
its actual molecular weight and logP — then flowed through correctly. (The prompt's
example result is now a set of typed placeholders that *cannot* parse as JSON, so an
echoed example can never be mistaken for a result in the first place.)

This is the habit behind the validation section below, and behind the `code_patched`
field in the result contract: a plausible number is not a correct number until it's
been checked. The same instinct later caught a run reporting numbers the committed code
could not have produced — because the agent had quietly patched around a broken
upstream API. See the service README.

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
- Add covalent-docking support (the Meeko/AutoDock reactive protocol, or CovDock).
  Covalent inhibitors are now **detected and flagged** (`covalent_flag`, via an RDKit
  warhead match), but they are still *scored* reversibly, so Vina systematically
  understates their potency — exactly the sotorasib gap the validation above found.
  The flag is provenance today, not an input to the score.
- Return the docked pose. Tried and reverted: at ~8 KB of PDB text it made the agent
  truncate the single-line `SIM_RESULT_JSON` contract, turning good runs into
  unparseable ones. The fix is not to shove it through the transcript — compress it
  (gzip+base64 ≈ 2.4 KB) or give the session a side channel (object storage + a URL).
- Pocket-aware docking instead of a blind box. Also tried and reverted, and the failure
  is instructive: centering on the largest co-crystal ligand boxed the **wrong pocket**
  (KRAS 7VVB carries only the nucleotide GNP, not sotorasib) while still returning a
  plausible ΔG. Needs a drug-bound structure pinned per trial, or real cavity detection
  (fpocket / P2Rank) — not "the biggest HETATM".
- Native **mmCIF** support in `fetch_structure` (gemmi), so large cryo-EM structures
  like CFTR's 9MXL stop falling back to a predicted model. Then MM-GBSA rescoring, and
  a separate affinity path for biologics (antibodies can't dock). Pin the sim
  environment (conda-lock); Vina's seed is already pinned, so ΔG now reproduces.

**Make the market call credible**
- Weight the probability-of-success delta by trial **phase** (Phase 1 ≪ Phase 3) and
  by whether it's the sponsor's lead asset / its market-cap exposure.
- Wire live quotes + market cap (no market-data client exists yet) and **backtest** calls
  against historical biotech readouts to calibrate direction and magnitude.
- Auto-derive `endpoint_outcome` (met/missed) from the CT.gov results section /
  press releases via an LLM classifier, instead of watchlist enrichment.

**Harden & ship**
- Stop *embedding* `simulation.py` in the prompt and have the session clone a **pinned
  commit** instead. The prompt currently carries the whole source, so it grows with the
  code and has already hit Devin's 30k-character ceiling (a test now guards it). Pinning
  a commit fixes the size problem *and* makes "which code produced this number?"
  answerable by construction — retiring the `code_patched` self-report in favour of
  something verifiable.
- Handle `blocked`/hung sessions with retries + timeouts, and alert on sim failures.
- CI (GitHub Actions: ruff + pytest), Postgres instead of SQLite, and a deployed
  service + watcher with a scheduled `/poll`.

---

## Honest caveats

The full list, with a fix verdict on each, is in
[`trial-impact-service/README.md`](trial-impact-service/README.md#limitations--modeling-caveats).
The ones that most change how you should read the numbers:

- **Docking is blind.** The box spans the whole receptor rather than a known pocket, so
  ΔG is a coarse, *relative* signal — not a measured affinity. Pocket-focused boxing was
  tried and reverted (it picked the wrong pocket, plausibly).
- **The 3D viewer shows the receptor the run docked against** (with its own crystal
  ligand), **not** Vina's docked pose — the pose is not returned. See Next steps.
- **Covalent binders are flagged but still scored reversibly**, so their potency is
  understated (sotorasib is the clearest case).
- **CFTR resolves to a predicted structure**, not the cryo-EM one: `fetch_structure`
  cannot read mmCIF. Confidence drops to 0.7 accordingly.
- **Generic PK constants.** `ka`/`Vd`/`CL` are fixed physiological placeholders and `Kp`
  is order-of-magnitude, so exposure/occupancy are directional, not drug-specific.
- `endpoint_outcome` (met/missed) is not machine-readable from ClinicalTrials.gov;
  the watcher supplies it via per-trial enrichment (`watchlist.json`) for now.
- The market model is deliberately transparent/rules-based (not a black box) and is
  **not** calibrated to real market data, and it does **not weight by trial phase** —
  it's a research signal, not a trade.

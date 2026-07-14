# Trial Impact

An event-driven system that runs structure-based chemistry on clinical-trial readouts and
produces a quantitative estimate of target engagement, rather than a categorical read on the
result.

When a trial posts results, the service opens an isolated [Devin](https://devin.ai) session
that performs protein–ligand docking (AutoDock Vina) and a PK/PD solve against the drug and
its target, and returns a binding affinity, an implied Kd and a derived target occupancy —
computed from the structure and the chemistry rather than from the sponsor's description of
the result.

> **Not investment advice.** Output is an automated research signal for informational
> purposes only; a disclaimer is attached to each assessment.

---

## Thesis

A desk watching a readout receives a label: the endpoint was met, or it was not. That label is
public within minutes and priced quickly, and it says little about whether the molecule should
have been expected to work. This system produces a second input for the same event — a
continuous estimate of target engagement — which can be scored against realized outcomes,
entered into a probability model as one feature among several, and accumulated into a dataset.

The reason to attempt it now is cost. Structure-based chemistry per trial has historically
required a computational chemist. An agent sandbox does it per event, in minutes, for roughly
the cost of the API calls.

### The chemistry is unlikely to be an edge on its own

That cost argument also cuts against the project. A signal's value tends to decay with the cost
of reproducing it, and the cost here is low: Vina is free and has been available since 2010,
RDKit, the PDB, AlphaFold DB, PubChem and Open Targets are all free, and this pipeline was
assembled in days with agent assistance. If a ΔG is cheaply computable by anyone, it is
reasonable to assume it is largely in the price already.

So the edge, if there is one, is not in the chemistry. It would be in producing a
**better-calibrated estimate of P(success)** than the one implied by the market, and trading the
difference:

> edge = our P(success) − the market's implied P(success)

The chemistry is one input to that estimate. Its job is to add incremental information, not to
carry the argument.

### Why a weak signal might still be usable

Grinold's fundamental law relates the information ratio to skill per decision and the number of
independent decisions: `IR ≈ IC × √breadth`. A specialist analyst has a relatively high
information coefficient across few names; a system of this kind would have a low one across many.

The table below is **illustrative, not measured** — the IC values are assumptions chosen to show
the shape of the relationship, not estimates:

| | IC (assumed) | decisions/yr | IR ≈ IC·√N |
|---|---|---|---|
| Specialist, concentrated coverage | 0.15 | 15 | 0.58 |
| This system, modest edge, broad coverage | 0.05 | 200 | 0.71 |
| …with chemistry adding some IC | 0.07 | 200 | 0.99 |
| …and coverage extended further | 0.07 | 400 | 1.40 |

The implication is that a weak but genuine signal applied to many decisions may be worth more
than a strong one applied to few. A commoditized input does not need to be a good signal — it
needs to be a slightly informative one that can be produced at scale, and scale is what the
sandbox provides. It also suggests where to look: specialist coverage concentrates on a small
number of high-profile catalysts, so the less-covered part of the universe is where a systematic
estimate is more likely to add something. That is a coverage argument rather than an insight
argument.

### What this repository does and does not establish

It establishes that the pipeline runs, that its outputs are **reproducible from source**, and
that its failure modes are visible rather than silent. That is a precondition for testing the
thesis. It is not evidence for it.

Both the chemistry and the market model are placeholders. The docking box does not cover the
receptor; occupancy is computed from total rather than free drug; the market model is
uncalibrated and rules-based. These are set out in [Known issues](#known-issues). The current
numbers are not tradeable, and the pipeline currently implies that ivacaftor — an approved and
effective CF therapy — does not engage its target.

The assumption most likely to be fatal is not "can we compute the chemistry," which works, but
"does the chemistry carry information the market does not already have," which is untested. A
baseline of phase × indication base rates plus a free genetic-association score is probably a
reasonably strong prior on its own, and the physics has to beat it. That experiment is cheap and
should be run before any further work on the physics.

### The wider view

[THESIS.md](THESIS.md) §5 sets out a broader position — held as a hypothesis rather than a
finding, and formed from following the recent wave of AI-for-biology companies rather than from
outcome data. In short: AI tooling is plausibly changing the outcome distribution of drug
development, through patient selection, biomarker stratification and adaptive trial design, while
pricing remains anchored to the historical distribution. If AI-enhanced trials have genuinely
different odds and the market does not separate them from conventional ones, that gap is the
opportunity. The evidence for the underlying claim is currently thin, and §5.2 says where I think
it is most likely to be wrong.

The weak point in that argument is not the economics but the **observability**: sponsors do not
label trials as AI-enhanced, and without a classifier that identifies them from public data there
is no trade, however real the effect. That classifier would be built from **trial protocol
data** — eligibility criteria, stratification, adaptive-design features, endpoint choice — which
ClinicalTrials.gov publishes and which the watcher here already ingests. On that view the more
valuable direction for this project is not better docking but a move from *the molecule* to *the
trial design*.

📄 The full argument — defensibility, the two axes of drug failure, the pre-readout case, what a
credible backtest would require, where the thesis is weakest, and the order in which its
assumptions could be falsified — is in **[THESIS.md](THESIS.md)**.

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
| [`ctgov-watcher/`](ctgov-watcher/) | A poller that diffs ClinicalTrials.gov v2 and emits signed webhooks (CT.gov has no native webhooks). **Scoped by configuration** — point it at a therapeutic area, a sponsor set, or a single competitive mechanism, and it only fires for that universe. This is what makes the feed targetable rather than a firehose. |

Each has its own README with full detail.

### Why Devin

The simulation is a real pipeline rather than a stub: fetch the target structure
(UniProt → experimental PDB, else AlphaFold), fetch the ligand (PubChem → SMILES →
RDKit 3D), dock with AutoDock Vina for a ΔG, then solve a PK/PD model in closed form
(Bateman) for tissue exposure and target occupancy.

The workload is the reason a sandbox is used rather than a fixed container. It has to
`pip install` a heavy and fragile scientific stack (RDKit, Meeko, OpenBabel, Vina), pull
structures from four upstream APIs, and recover when any of them fails — which they do,
in ways that are not predictable in advance (see the API-rot section below). A container
would have to anticipate each failure; a session can respond to one. That adaptability is
what makes per-event chemistry cheap enough to run at scale. One isolated session per
trial event also keeps runs independently retryable and separately auditable.

The tradeoff is that an agent will also fix things it was not asked to fix — including
the science. That is not hypothetical: it has happened twice here, and it is why the
result contract carries a `code_patched` field. See
[the result contract](trial-impact-service/README.md#the-result-contract-and-why-it-has-a-code_patched-field).

### On the label

The framing above assumes each event arrives with a **classification** (endpoint met /
missed) that the physics estimate sits *alongside*. Today that label is supplied by
per-trial enrichment (`watchlist.json`), **not** derived automatically —
ClinicalTrials.gov does not expose met/missed in machine-readable form. An LLM classifier
over the CT.gov results section and the sponsor's press release is the intended path and
is tracked under [Next steps](#next-steps); it does not exist yet. The physics half of the
pipeline is the part that is built.

---

## Results from two real Devin runs

Genuine outputs from live Devin sessions (see [`results/`](results/) for the raw JSON
and the rendered dashboards — open the `.html` files in a browser). Docking is
**seed-pinned**, so these reproduce: re-running a trial returns the same ΔG.

**Read the physics columns as the product and the model call as scaffolding.** ΔG / Kd /
occupancy are the net-new data modality — the quantity a pricing model would eventually
consume as a feature. The `Model call` column is the transparent rules-based placeholder
described above; it shows that the pipeline runs end to end, and it is not a trade.

| Trial | Target × Drug | Structure | ΔG (kcal/mol) | Kd | Target occ. ‡ | Flags | Model call |
|-------|---------------|-----------|---------------|----|-----------|-----|-----------|
| Phase 1 | KRAS × sotorasib | 7VVB (RCSB, exp.) | **−8.606** | 863 nM | 97.6% ‡ | ⚠︎ tox ‡ · covalent | ▲ AMGN strong · ▼ REGN/NVS |
| Phase 3 | CFTR × ivacaftor | AF-P13569 (AlphaFold) | −8.702 † | 738 nM | 94.5% ‡ | clean | ▲ VRTX strong · ▼ CRSP/BLUE |

Every number in both rows has been re-derived from the committed source: Kd, Cmax, occupancy
and both PoS deltas reproduce to the last digit. The `code_patched: false` each run reports is
therefore verified rather than self-reported — the numbers came from `simulation.py` as
committed, not from a session that patched it to work around a broken upstream API. That field
exists because it caught exactly that case (see below).

**‡ Two of these columns should be read with caution**; [Known issues](#known-issues) has the
detail. Occupancy is computed from total rather than free drug — there is no protein-binding
correction — so it is an upper bound rather than an estimate of target engagement. Ivacaftor is
reported in the literature as >99% plasma-protein-bound; corrected for that, its 94.5% would be
closer to 15%, which is enough to change the VRTX call from `strong` to `moderate` (issue #1).
The `tox_flag` is ≥2 Lipinski violations, which is a drug-likeness and oral-absorption
heuristic rather than a toxicity model; it fires on sotorasib, which is an approved drug
(issue #3).

The inputs are drug-specific rather than hardcoded: sotorasib's flags derive from its computed
descriptors (MW 560.6, logP 5.30) and an RDKit substructure match on its acrylamide warhead,
while ivacaftor (one violation, reversible) comes back clean, so the two readouts produce
different PoS deltas. The inputs are real; the interpretation placed on two of them in the
market model is not well founded, and is documented as such.

> **† The CFTR ΔG is not a pocket-resolved affinity, and should not be read as one.**
> The docking box is centroid-centered and capped at 40 Å. CFTR is a 1480-residue
> membrane protein measuring 139 × 117 × 147 Å, so that box holds **19% of the
> receptor's atoms** — and ivacaftor binds at the TM1/TM6 interface, not the centroid.
> The run is a real, reproducible execution of the pipeline, but the ΔG is a dock into
> an arbitrary central slab. KRAS (56 × 55 × 44 Å) fares far better at **80% coverage**,
> which is why it is the headline result. Reproduce both numbers with
> `python verify_docking_box.py`. This is **[open issue #2](#known-issues)** — I found
> it by auditing my own code and chose to document it rather than paper over it.
>
> **Why CFTR also uses a predicted structure.** An earlier run used the cryo-EM
> structure 9MXL at confidence 0.9 — but 9MXL is **mmCIF-only** and `fetch_structure`
> reads `.pdb`, so the committed code *cannot* fetch it; that number only existed
> because a Devin session worked around the gap in its sandbox. It has been retired in
> favour of the AlphaFold model at **confidence 0.7**, which is lower but reproducible.

A **results-analysis view** (`GET /analysis`, exported to
[`results/analysis_dashboard.html`](results/analysis_dashboard.html)) lets you
inspect the whole corpus and learn from it: cross-run charts (ΔG/Kd/occupancy vs the
market call), a sortable comparison table, and a per-run drill-down with the 3D
docked structure, the reconstructed PK/PD exposure curve, and a step-by-step
**reasoning trace** of how each probability-of-success delta was built.

---

## Chemistry & biophysical scope

The physics has a domain of validity, and most of biopharma sits outside it. This is
what the pipeline models today, what it models badly, and what it cannot touch at all.
**✅ supported · ◑ runs but degrades · ○ out of scope, needs a different method.**

### Drug modality

| Modality | | Where it stands |
|---|---|---|
| **Small molecules** (MW ≲ 900, drug-like, PubChem-resolvable) | ✅ | The pipeline is built for these. Both published runs are here. Resolved via PubChem → isomeric SMILES → RDKit ETKDG 3D embed → PDBQT. |
| **Peptides & macrocycles** | ◑ | RDKit will embed them, but Vina's scoring function is parameterized on drug-like ligands and its rigid-ligand sampling degrades badly past ~10 rotatable bonds. Numbers would come back; they would not mean much. Needs macrocycle-aware sampling. |
| **Biologics** — antibodies, proteins, ADCs, oligos/siRNA, cell & gene therapy | ○ | **Cannot be docked at all.** There is no SMILES, and binding is a protein–protein interface, not a ligand in a pocket. This excludes a large fraction of the oncology pipeline. Needs a separate affinity path (PPI scoring / co-folding) or a metadata-only route that skips the physics and scores the readout alone. |
| **PROTACs & molecular glues** | ○ | Require a *ternary* complex (target + ligase + linker). Fundamentally a different modeling problem, not a harder docking run. |

### Target / receptor

| Target class | | Where it stands |
|---|---|---|
| **Single-chain globular soluble proteins** with a legacy-format experimental PDB | ✅ | The good case — KRAS/7VVB. Small enough that the 40 Å box still covers ~80% of the receptor. |
| **AlphaFold-predicted structures** | ◑ | Used as fallback when no experimental structure resolves; run confidence drops 0.9 → 0.7. A predicted backbone is fine; predicted side-chain rotamers in a pocket are the weak point. |
| **Large multi-domain or membrane proteins** | ◑ | **This is where CFTR fails.** The 40 Å box cap means we dock a central slab, not the pocket (19% atom coverage). Runs to completion and returns a plausible number, which is what makes it dangerous. Needs pocket detection (fpocket / P2Rank) or a drug-bound structure pinned per trial — [issue #2](#known-issues). |
| **mmCIF-only structures** (most large modern cryo-EM) | ○ | `fetch_structure` reads `.pdb` only, so these 404 and silently degrade to a predicted model. Needs a native mmCIF parser (gemmi). |
| **Multi-chain complexes, ensembles, flexible side chains** | ○ | One structure, rigid receptor, no ensemble. Vina supports flexible side chains and ensemble docking; both change every run's numbers, so they were deferred. |
| **Nucleic-acid targets** (RNA/DNA) | ○ | Vina's empirical scoring function is parameterized for protein–ligand, not nucleic-acid–ligand. |

### Bond & interaction type

| Interaction | | Where it stands |
|---|---|---|
| **Reversible non-covalent binding** — H-bonds, hydrophobic contact, vdW, electrostatics | ✅ | Exactly what Vina's empirical function scores. This is the only interaction class the ΔG is actually valid for. Ivacaftor is the clean case. |
| **Covalent inhibitors** | ◑ | **Detected and flagged, but still scored reversibly.** An RDKit SMARTS match catches acrylamide/acrylate, halo-acetamide, vinyl sulfone, boronic acid/ester and epoxide warheads. Vina cannot model bond formation, so the irreversible contribution to potency is simply missing and ΔG is systematically understated — which is precisely the sotorasib gap the validation section below found. The flag is provenance for a human reader; the market model does not consume it. Needs the Meeko/AutoDock reactive protocol or CovDock. |
| **Metal coordination** (zinc proteases, metalloenzymes) | ○ | Vina handles metal centers poorly without specific parameterization. A zinc-binding drug's affinity would be badly underestimated. |
| **Allosteric & cryptic pockets** | ○ | A blind box will not reliably find a cryptic pocket that is closed in the apo structure. Needs a holo structure or induced-fit/MD sampling. |
| **Halogen bonding, explicit bridging waters** | ○ | Not modeled. The receptor is stripped of waters before docking. |

### Pharmacology

| Assumption | | Where it stands |
|---|---|---|
| **One-compartment Bateman model, closed form** | ◑ | `ka`/`Vd`/`CL` are fixed physiological placeholders and `Kp` is order-of-magnitude, so exposure is **directional, not drug-specific** — it will tell you a 960 mg dose achieves high exposure, not what sotorasib's real Cmax is. No bioavailability term either (`F` = 1), which flatters oral exposure. |
| **Occupancy from *total* drug** | ○ | **The weakest link in the pharmacology.** `occ = C/(C + Kd)` uses total tissue concentration, with **no fraction-unbound (`fu`) term** — but only *unbound* drug engages a target. For a highly protein-bound drug this inflates occupancy enormously: ivacaftor is >99% bound, so its reported 94.5% is really **~15%**. Treat every occupancy as a **total-drug upper bound**. This is [issue #1](#known-issues), and it changes a published market call. |
| **Single dose, peak occupancy** | ○ | No steady-state accumulation; occupancy is the peak of a single-dose curve, and AUC is AUC(0–48h), not AUC(0–∞). Most of these drugs are dosed chronically. |
| **Kd from an empirical docking score** | ○ | `Kd = exp(ΔG/RT)` treats Vina's empirical score as a rigorous free energy, at body temperature (310.15 K) rather than the 298.15 K its calibration assumes. The Kd inherits every approximation in the ΔG and then gets compared against absolute thresholds — see [issue #4](#known-issues). |

Genuine per-drug pharmacology needs enrichment overrides (`fu`, `Vd`, `CL` per drug — the
same mechanism as `endpoint_outcome`) or a structure→PK model.

**The practical upshot.** The *binding* half of the pipeline is defensible today for a
**reversible, non-covalent small molecule against a small globular protein with an
experimental structure** — and that is the honest boundary. Everything else either degrades
quietly (covalent, membrane proteins, predicted structures) or is out of scope entirely
(biologics). Both published runs sit partly outside even that box: sotorasib is covalent,
CFTR is a membrane protein.

The *pharmacology* half is weaker still, and I would not defend it as more than
directional: with generic PK constants, no bioavailability term, and **no protein-binding
correction**, the exposure and occupancy numbers are order-of-magnitude scene-setting, not
predictions. The ΔG is the number worth arguing about; the occupancy is not, and the
[Known issues](#known-issues) say so rather than letting the dashboard imply otherwise.

---

## Catching a bug: when the result was too clean

On the first real run, the stored result matched the example values embedded in my
own prompt. I pulled the raw Devin session
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
cp .env.example .env          # set DEVIN_API_KEY (Slack/SMTP optional)
                              # .env.example ships a non-empty WATCHER_SHARED_SECRET, so
                              # webhook signature verification is ON by default. Blank it
                              # to disable (dev only — the service warns loudly if you do).
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

Sequenced deliberately. Nothing below step 2 is worth doing until the science above it is
sound — calibrating a pricing model on a biased signal just launders the bias. The full
argument is in [THESIS.md](THESIS.md); the per-issue fixes are in
[Known issues](#known-issues) and [Limitations](trial-impact-service/README.md#limitations--modeling-caveats).

**1 · Separate the harness from the estimator** *(highest leverage — it follows directly from
the physics having no moat)*
Vina should be one implementation, not the architecture. Define the estimator interface, add an
`estimator` field to the result contract (a corpus spanning unattributed model versions is
uninterpretable), and stop shipping `simulation.py` inside the prompt — clone a **pinned
commit** instead, which also removes the 30k ceiling and retires `code_patched`'s self-report
for something verifiable. Then run **two estimators head-to-head on the same trials**. That
comparison, not any single model's output, is the product.

**2 · Fix the science that blocks a forecast**
- **Pocket-aware docking** (fpocket / P2Rank, or a drug-bound structure pinned per trial) — the
  blind box covers 19 % of CFTR. A bigger box is *not* the fix; an uncapped CFTR box is ~2.4 M Å³,
  past where Vina's sampling means anything.
- **A free-drug (`fu`) term**, so occupancy stops being a total-drug upper bound.
- **Covalent scoring** (Meeko/AutoDock reactive, or CovDock) — covalent binders are detected and
  flagged today, but still *scored reversibly*, so their potency is systematically understated.
- **Native mmCIF** (gemmi), so large cryo-EM structures stop degrading to a predicted model.
- Pin the sim environment (conda-lock). Report **mean ± sd across seeds** rather than one draw.

**3 · Add the axis the physics cannot see**
Drugs mostly fail on **target validation**, not chemistry. Pull the **Open Targets**
genetic-association score for the target–indication pair — genetically-supported targets succeed
at roughly twice the rate, making it the strongest known public predictor of clinical success,
and a stronger one than anything docking produces. Add clinical precedent and trial-design
quality (endpoint, powering, biomarker enrichment). Then build the **retrospective panel of
known winners and losers** and make the chemistry clear it — *the current build fails that panel,
predicting that ivacaftor does not engage its target.*

**4 · Build the corpus — point-in-time, with honest labels**
Accumulate `(trial design, physics, genetics, outcome, realized move)` per trial, backfilled over
history (the physics is computable retroactively, which is the only reason a backtest is
feasible). Two rules make or break it: **filter structures by deposition date** (docking a
co-crystal published *after* the trial registered is look-ahead bias), and **reconstruct outcomes
from press releases / 8-Ks, not just CT.gov** (negative trials are systematically under-reported,
so a registry-only corpus is skewed toward winners). Keep terminated and withdrawn trials in.
Close the label loop with an **LLM classifier** over results sections and press releases, instead
of `watchlist.json` enrichment.

**5 · Fit a calibrated P(success) — and respect the small-n trap**
The goal is a **better-calibrated probability than the market's**, with the chemistry as one
feature among many. The intuition "more features, more data" contains the trap: **the binding
constraint is labels, not features.** Filter to *(small molecule, known target, resolvable
structure, listed sponsor, material to market cap, honest outcome)* and you have **hundreds to
low thousands** of clean examples — so expect to support **10–30 features**, with regularized
logistic regression or gradient boosting beating anything deep. Piling on every RDKit descriptor
produces a beautiful backtest and no alpha.
- **Time-series CV, never random k-fold** — random folds leak the future, and drug development is
  non-stationary.
- **Test the cheap baseline first:** historical PoS by phase × indication, plus the Open Targets
  genetic score, is a strong and nearly-free prior. **The chemistry must prove incremental IC over
  it — it may not**, and that is worth knowing *before* building more physics.
- Pre-register hypotheses; test 100 feature sets and one will "work."
- **KPI is calibration, not accuracy** — Brier / log-loss and a calibration curve *against the
  market's implied PoS*. The question is never "were we right?" but *"were we systematically
  right where the market was wrong, by enough to pay the spread?"*

**6 · Then price it — and remember the edge is breadth**
Recover the market's **implied** probability — from options around the catalyst, or by decomposing
market cap against a risk-adjusted NPV — because the edge is `our P(success) − implied P(success)`,
not the level of our own call. Trade the divergence in **options** (a binary catalyst makes the
stock bimodal; convex payoffs pay you for being right about the *probability*, not the sign), and
size by the edge.

By `IR ≈ IC × √breadth`, a modest edge applied 200–400× a year beats a brilliant one applied 15×.
So **do not try to out-analyze a specialist on a marquee Phase 3** — the edge is a **coverage
arbitrage** in the neglected tail of uncovered SMID-cap names. That requires real
**sponsor→ticker entity resolution** (issue #7): breadth is the whole thesis, and a six-entry
`tickers.json` is exactly what breadth is not. Model **slippage honestly** — SMID biotech options
are illiquid and IV crush around a binary event is brutal; an edge that cannot be harvested at
size is not a business.

**Harden & ship**
Retries/timeouts on `blocked` or hung sessions; CI (GitHub Actions: ruff + pytest) plus a nightly
**live-API smoke test** — the only thing that would have caught six months of upstream API rot;
Postgres instead of SQLite; a deployed service + watcher on a scheduled `/poll`.

---

## Known issues

Open defects, ranked. These are errors rather than simplifications; the modelling
simplifications are catalogued separately under
[Limitations](trial-impact-service/README.md#limitations--modeling-caveats), which also carries
the full detail and proposed fix for every row below. The domain of validity is set out in
[Chemistry & biophysical scope](#chemistry--biophysical-scope).

Most of these were found by auditing the code after the runs had been published. The first four
share a structure worth noting: in each case a locally reasonable choice is treated as a
stronger claim further down the pipeline. A relative score is converted into an absolute Kd. A
drug-likeness heuristic is applied as a toxicity penalty. A total concentration is reported as
target engagement. A computationally tractable search box is described as covering the receptor.
None of these raise an error or fail a test — the estimate simply becomes less well-founded than
its downstream use implies.

**Status:** ○ open · ◑ mitigated, not fixed · ✅ fixed

| # | Issue | Impact | |
|---|---|---|---|
| 1 | **Occupancy is computed from *total* drug, not free drug** — no protein-binding (`fu`) term. Ivacaftor is >99 % bound, so its published 94.5 % is really **~15 %** | **Changes a published market call**: the +0.15 engagement bonus becomes −0.10, PoS falls 0.552 → 0.340, and VRTX downgrades `strong` → `moderate`. Read every occupancy as a **total-drug upper bound** | ○ |
| 2 | **The blind docking box does not cover the receptor** — `min(extent + 8 Å, 40 Å)` centred on the centroid; the cap binds in *both* runs. Coverage: **KRAS 80 %, CFTR 19 %** | CFTR's ΔG is a dock into a central slab, **not a pocket-resolved affinity**. Reproduce with `python verify_docking_box.py`. Mitigated: warns when the cap binds; a characterization test pins the behaviour | ◑ |
| 3 | **`tox_flag` is a drug-likeness heuristic priced as a safety signal** — it is ≥2 Lipinski violations, which predicts *oral absorption*, not toxicity | Charges **−0.15 PoS as if a safety finding had occurred**. It fires on sotorasib — an **approved** drug — because it is a large lipophilic oncology molecule | ○ |
| 4 | **ΔG is documented as *relative* but consumed as *absolute*** — converted to `Kd = exp(ΔG/RT)` and branched on hard cutoffs (`Kd ≤ 100 nM`, `ΔG ≤ −9.0`) | The code and the docs disagree about what the number *is*. The conversion also uses 310.15 K where Vina's calibration assumes 298.15 K, making every Kd **~1.75× looser** | ○ |
| 5 | **`simulation.py` is embedded in the prompt, and the budget is exhausted** — 29,950 / 30,000 chars, **50 spare** | The code **cannot afford another comment**. Hit the ceiling three times; a test guards it, so it fails loudly. Fix: clone a **pinned commit** — also retires `code_patched`'s self-report for something verifiable. **The next thing I would build** | ○ |
| 6 | **The harness/estimator boundary is implied, not enforced** — `docking_box` is Vina-specific and there is **no `estimator` field** | A corpus spanning unattributed model versions is uninterpretable and any backtest over it is invalid. Same argument as `code_patched`, one level up | ○ |
| 7 | **Sponsor→ticker resolution is a hand-maintained 6-entry file** with hardcoded competitors | Real resolution is **entity resolution** (messy sponsor strings, listed parents, private/pre-IPO sponsors with no ticker and therefore no trade). **The system runs on a watchlist, not a universe** — the scaling claim is not yet earned | ○ |
| 8 | **Webhook signature verification fails open** when `WATCHER_SHARED_SECRET` is unset | Accepts *any* caller's trial event, each of which spends a Devin session. Mitigated: logs a loud startup warning. Production should require the secret | ◑ |
| 9 | **The box is computed over atoms that are not docked** — spans `ATOM`+`HETATM`, but the receptor is `ATOM`-only | Small in practice, wrong in principle. Not fixed alone: it moves the box, which changes ΔG, which would invalidate both artifacts. Fixed together with #2, in one re-run | ○ |
| 10 | **Structure choice is not pinned** — whatever PDBe/SIFTS ranks first *at run time* | A re-run could dock a **different structure**. Also a **look-ahead leakage vector** for any backtest (see [THESIS.md](THESIS.md)) | ○ |
| 11 | **Reported precision exceeds real precision** — one pinned seed, reported to 3 decimals, when the pre-pin spread was 0.19 kcal/mol (**~36 % in Kd**) | `cmax_ng_ml` is also a *tissue* concentration, not plasma Cmax; AUC is AUC(0–48 h). Fix: N replicates with derived seeds → mean ± sd → feed the sd into `confidence` | ○ |

**Fixed this round, kept on the record:** the AlphaFold fallback URL was stale and *every*
fallback 404'd; Vina ran with `seed=0`, which it reads as *random*, so repeat runs drifted; a
tox flag on an `unknown`-outcome trial scored −0.1425, cleared the 0.10 alert threshold and
emitted a directional call on chemistry with **no clinical readout** behind it (and `unknown`
is the default for un-enriched trials, so that was the *common* path); PubChem schema drift
silently broke ligand fetching; a covalent SMARTS false-positived on ivacaftor; and
`run_real.py` posted unsigned webhooks that would 401 against the shipped `.env.example`.

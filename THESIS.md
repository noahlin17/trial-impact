# Thesis

Why this exists, where the edge could actually be, and what would have to be true for it to
work. The [README](README.md) has the short version; this is the argument in full.

---

## 1. The signal

Every desk watching a clinical-trial readout already gets a **label**: endpoint met or
missed. That label is public within minutes, everyone has it, and it is priced almost
immediately. It carries no independent view of whether the molecule *should* work.

This produces a second, **orthogonal** input for the same event: an independent biophysical
estimate of whether the drug engages its target, derived from the protein structure and the
ligand chemistry rather than from the sponsor's framing. For each readout you get, alongside
the classification, a **ΔG / Kd and a PK/PD-implied efficacy estimate** — a continuous
quantity that can be:

- **backtested** against realized outcomes and realized price moves, which a label cannot be
  scored against in the same way;
- fed into a pricing model as **its own feature**, with errors plausibly uncorrelated with the
  market's priors because it is computed from physics rather than sentiment or consensus;
- accumulated into a **corpus**, so that with enough history the signal supports systematic
  strategies rather than one-off fundamental calls.

The economics are the enabling part. Structure-resolved chemistry per readout has historically
meant a computational chemist on staff. An agent sandbox does it **per event, in minutes, at
API cost**, scoped to whatever universe the watcher is pointed at. That is the difference
between a research project and a **data feed**.

---

## 2. The physics is not the moat

That same sentence cuts the other way, and it is the most important thing on this page.

**A signal's value decays with the cost of reproducing it** — and the cost here is nearly
zero. AutoDock Vina is free and fifteen years old. RDKit, the PDB, AlphaFold DB, PubChem and
Open Targets are all free. An agent wrote this pipeline in days; that is not hypothetical, it
is this repo's git history. If everyone can compute a ΔG for every trial, **ΔG is in the
price.** The cheapness that makes the modality *viable* is the same property that erodes its
*edge*. Running docking and tox simulation ahead of a readout is, on its own, a commodity, and
should be assumed to commoditize further.

So the estimator is not the asset. Three things plausibly are:

| | Why it could be durable |
|---|---|
| **The labeled, point-in-time corpus** | Models commoditize; data does not. `(trial design → physics → genetics → outcome → realized move)`, with failure labels reconstructed from press releases and 8-Ks **because the registry systematically under-reports negatives**. Slow, unglamorous, hard to copy. The difficulty *is* the moat. |
| **The translation to price** | P(success) → the market's *implied* P(success) → sizing. Finance IP, dependent on your own capital and execution; it does not commoditize like an open-source scoring function. |
| **The evaluation harness** | A new bio-AI model lands every quarter. The edge belongs not to whoever *has* a model, but to whoever can evaluate a new one against a labeled financial corpus, point-in-time, in a week. |

**The third row is what this repository is trying to be.** The docking is a *plugin*, and a
deliberately commodity one — the reference implementation and the control, not the source of
edge. The event trigger, the isolated sandbox, the strict result contract, the
reproducible-from-source guarantee, the corpus and the backtest are all **intended to be
model-agnostic**. Swap Vina for a co-folding affinity model, a proprietary QSAR or an internal
fine-tune, and the rest of the system should not change.

**It is not there yet.** `docking_box` is Vina-specific, there is no `estimator` field
recording which model produced a number, and `simulation.py` is a Vina-shaped monolith shipped
inside the prompt. The boundary is *implied* by the design, not *enforced* by it. Closing that
is the top item under [Next steps](README.md#next-steps).

So the honest pitch is **not "docking generates alpha" but "here is the infrastructure to find
out what does."** If proprietary bio-AI models or novel outcome-prediction and pricing
techniques can produce real alpha here — a genuine open question, worth investigating in
earnest rather than asserting — then the first thing you need is a rig that tests them against
realized outcomes *without fooling you*. That rig is the contribution, and it is why the
reproducibility discipline in this repo is load-bearing rather than fussy: **a backtest across
models whose numbers you cannot attribute is worthless.**

One caution applied to our own thesis: *"we will have a proprietary model"* is the **weakest**
of the three rows. You will not out-model the frontier labs; a licensed model is not
proprietary to you; and a model moat depreciates on roughly a twelve-month lag as the open
frontier catches up. The durable version of "proprietary model" is a **fine-tune on
proprietary data** — which routes straight back to the corpus.

---

## 3. The endgame: forecast the readout, don't react to it

Scoring a readout after it lands is the wrong end of the trade. A readout is public within
minutes and priced almost immediately, so reacting to it is a **latency race** — and latency
is not this system's advantage.

The target is the same machinery run **at trial registration**, when the design is first posted
and the readout is one to three years away. At that moment CT.gov gives you the drug, target,
mechanism, dose, phase, endpoints, population and duration — everything the physics needs — and
nothing about the outcome exists yet, *for anyone*. A forecast made there is an **information
edge**, not a speed edge. It is computable across every registered trial at once, and it has a
multi-year window in which to be right.

**Scoring readouts is not the product. It is the training set.**

### 3.1 The seam where it plugs in

The market model gates every physics modifier on `has_readout`: with no clinical result, it
**declines to call**. (This was a bug fix — the model used to emit a directional call on
chemistry alone, which was wrong *because* it was pretending to a forecast it had not earned.)

That gate is exactly the seam. Today, "no readout" correctly means "no call." **The predictive
product is what replaces that refusal with a forecast** — and it is only entitled to do so once
the physics is strong enough to carry the load alone, which today it is not.

### 3.2 Drugs fail on two axes, and this repo computes one

| | Question | What answers it | Status |
|---|---|---|---|
| **Molecule** | Is this a good drug *for that target*? | Binding affinity, selectivity, free exposure vs Kd, ADMET/tox | ◑ What the pipeline computes — coarsely, with known defects |
| **Target** | Does modulating that target *change the disease*? | Human genetic evidence, clinical precedent, pathway biology | ○ **Not modelled at all** |

This asymmetry is the most important thing to understand about the predictive version. Roughly
**90 % of drugs entering clinical trials fail**, and the dominant cause of Phase 2 failure is
**lack of efficacy** — usually a *target* problem, not a *molecule* problem. A drug can bind
beautifully, achieve full target engagement, and still fail because the target was never causal
in the disease.

Docking cannot see that. It answers "does the molecule hit the target," and **the market is
mostly not wrong about that.** So a pre-readout predictor built on binding affinity alone is
answering the wrong half of the question — not because the chemistry is bad, but because the
chemistry is not what kills most drugs.

The remedy is cheap and well-evidenced: **human genetic support for a target is the strongest
known public predictor of clinical success** (genetically-supported targets succeed at roughly
twice the rate). Open Targets exposes a genetic-association score per target–indication pair,
free. *"Is the target right?"* × *"is the molecule right?"* is a defensible model. Either axis
alone is not.

### 3.3 Phase 1 and Phase 2 are different prediction problems

Phase 1 endpoints are overwhelmingly **safety, tolerability, MTD and PK** — not efficacy
(oncology dose-expansion aside). So the physics is *most* predictive in Phase 1, but for a
subtler reason than it first appears: what it can genuinely forecast there is **can you get
free drug above Kd at the target, at a dose that is tolerated?** That is a therapeutic-index
question, and it is squarely a chemistry + PK question. Good fit.

Phase 2 is an **efficacy** question, and efficacy is a target-validation question. The physics
is necessary but nowhere near sufficient, and the genetics axis carries most of the weight.

### 3.4 The acceptance test — which the current build fails

Before any predictive claim, the refined chemistry must clear a retrospective panel of **known
winners and known losers**. That panel is cheap to assemble and brutally diagnostic. Running
the pre-readout question (*is free Cmax above Kd?*) backwards on the two drugs already in this
repo — **both approved**:

| Drug | Docked Kd | Free Cmax | Free Cmax / Kd | Model says | Reality |
|---|---|---|---|---|---|
| sotorasib | 863 nM | 3,779 nM | **4.4×** | engages target | ✅ approved |
| ivacaftor | 738 nM | 128 nM | **0.17×** | **fails to engage** | ✅ **approved, transformative** |

**The pipeline as built predicts that ivacaftor does not engage CFTR.** It is one of the most
clinically successful drugs in cystic fibrosis. The docked Kd is far weaker than ivacaftor's
real potency, which traces straight back to the docking box covering 19 % of CFTR and never
seeing the real binding site, and to occupancy being computed from total rather than free drug.

This is why the chemistry and the market mechanics here are explicitly **placeholders to be
replaced, not foundations to be built on**. It also **re-ranks the issue list**: in the
*reactive* system those two defects are documented caveats, because a known clinical readout
carries the call. In the *predictive* system there is no readout to fall back on — the physics
stands alone — so they stop being caveats and become **blocking defects**.

That re-ranking is the most useful thing this exercise produced: the endgame tells you which of
your known issues actually matter.

### 3.5 What would make the backtest real

The forecast is worth exactly what the validation is worth, and a naive backtest here will
produce a beautiful, false result. Four things will kill it:

- **Look-ahead bias through structures.** PDB entries have **deposition dates**. Docking against
  a co-crystal of the drug bound to its target, deposited *after* the trial was registered, is
  using tomorrow's information to predict today. Structure selection must be **point-in-time**.
  (This turns "structure choice is not pinned" from a reproducibility nit into a **leakage
  vector**.)
- **The labels are biased, in the worst direction.** Negative trials are **systematically
  under-reported** — sponsors publicise wins and quietly discontinue losers, and registry
  results compliance is poor. A corpus built from CT.gov alone is missing-not-at-random and
  skewed toward successes. Outcomes must be reconstructed from press releases, 8-Ks and
  pipeline-discontinuation disclosures.
- **Survivorship.** Terminated and withdrawn trials stay in the sample. They are the signal.
- **Base rates.** ~90 % attrition makes "predict failure" a strong naive baseline. The model
  must beat that *and* beat a free **genetics-only** baseline before anyone should care that it
  uses physics.

### 3.6 Where the alpha actually is

The trade is **not** "our model says the stock goes up." It is:

> **edge = our P(success) − the market's implied P(success)**

which makes the *implied* probability a required input, not an afterthought. It can be recovered
from options around the catalyst (a binary event has a characteristic signature in the vol
surface) or by decomposing the sponsor's market cap against a risk-adjusted NPV of the pipeline.
You trade the **divergence**, not the level.

That formulation also picks the universe for you. A Phase 1 asset is *noise* inside Amgen's
market cap. The signal only appears where the trial is **material to enterprise value** — small-
and mid-cap, single-asset or lead-asset, catalyst-driven biotech, where a readout moves the
stock 50–80 %. This is what the watcher's configurable scoping is for.

**Caveat, and it is a live one:** sponsor→ticker resolution today is a hand-maintained six-entry
`tickers.json`. Until that becomes real entity resolution — including handling the many sponsors
that are private or pre-IPO and therefore untradeable — the system runs on a **watchlist, not a
universe**. The demo is honest; the scaling claim is not yet earned.

# Thesis

The [README](README.md#motivation--unvalidated-market-thesis) has the core argument: a sponsor runs a
trial only once its own never-observed belief `P_science` clears an expected-value bar; neither we nor
the market sees that belief, both infer from the same disclosed science; and the question is whether we
can compute something from that disclosed science the market isn't already pricing. The bar is `P_you`
better-calibrated than `P_market` over realized outcomes: `E[(P_you − y)²] < E[(P_market − y)²]`.

This document covers what the README doesn't: why the chemistry, even if it worked, probably isn't the
edge; where an edge could actually live; and the order in which the remaining assumptions could be
tested.

---

## The chemistry answers the wrong half, at the wrong time

**Two axes of failure, and this project models one.**

| | Question | What bears on it | Status here |
|---|---|---|---|
| Molecule | Is this a good drug for that target? | Binding affinity, selectivity, free exposure vs. Kd, ADMET | Partially — coarsely |
| Target | Does modulating that target change the disease? | Human genetic evidence, clinical precedent, pathway biology | Not modelled |

Roughly 90% of drugs entering trials fail, and the largest share of Phase 2 failures is lack of efficacy
— usually a statement about the *target*, not the molecule. Docking speaks only to whether the molecule
engages the target, and the market is rarely wrong about *that*. Targets with human genetic support
succeed ~2× as often (Nelson et al., *Nature Genetics*, 2015), and Open Targets exposes that score for
free — so a genetics + base-rate baseline is the thing the chemistry has to beat before it adds anything,
and it may not.

**Known going in vs. being tested.** Target engagement is established *preclinically* — it's an entry
criterion, and ΔG doesn't change between phases — so the docking result is confirmatory of an
already-established fact, not information the trial generates. What the trial actually tests (human PK,
tolerability, MTD, sometimes occupancy) is exactly what the pipeline does *not* compute. So the chemistry
surfaces nothing net-new the market doesn't already have; phase governs only whether an outcome is
published yet, never the strength of the call (`market_model.assess` is phase-agnostic by construction).
Engagement is confirmatory today — but it's the first tested primitive a predictive downstream piece
would consume, and the standing conjecture is that the earliest stages, where least is public, leave the
most room to extrapolate an un-priced quantity. Only a backtest settles whether that's true.

---

## Where an edge would actually have to come from

Not the chemistry. If there's one, it's a better-calibrated P(success) than the price implies, traded on
the divergence. This disciplines a tempting but wrong theory of the first unlock: *"the edge is a quantity
that's computable but unpublished."* **Unpublished is not un-priced.** The sponsor runs FEP/MD/PBPK/ADMET
internally and just doesn't publish it — so the unpublished quantity is usually already known to the party
setting the price, leaking in through dose choice and trial design. A deep sim of a heavily-followed drug
is therefore the *worst* case: maximal coverage, sponsor knows everything. The plausible edge is the
inverse — a cheap, calibrated estimate applied at **breadth** across under-covered events where no informed
party has done the work.

The claim isn't that chemistry is unused. It's that AI has lowered the cost of running *more* of it, on
*more* names, past the point where an expert or a full FEP campaign previously justified the per-trial cost
— a near-term edge, explicitly not a moat, since falling cost commoditizes it. The durable position is the
dataset and the harness, not the chemistry.

**Breadth, and why a weak signal can still pay.** Grinold: `IR ≈ IC × √breadth`. A weak edge applied to
many decisions can beat a strong one applied to few — a commoditized input doesn't need to be a good
signal, just a slightly informative one produced at scale. Breadth is also what makes skill *detectable*:
a single binary readout can't score a probability, so calibration only exists across many events. Two
honesty caveats: biotech catalysts cluster (correlated bets cut *effective* breadth below the raw count),
and the fuller `IR ≈ IC · √BR · TC` carries a transfer coefficient well under 1 in illiquid small-cap
options. The breadth argument gives the *shape*, not a reachable number — and breadth is exactly what the
current build lacks (a six-entry `tickers.json`, a watchlist not a universe).

**How it's judged:** calibration against the market's implied probability, not accuracy — whether the
model was systematically right where the market was wrong, by enough to cover costs. Options are the
instrument (convex payoff, bimodal distribution — you can be paid for the probability without the
direction), though I haven't modelled transaction costs, and translating a probability into a sized
position is the part I know least about.

**What a backtest would have to survive:** point-in-time structure selection (docking a co-crystal
deposited *after* the trial registered is look-ahead), honest outcome labels reconstructed from press
releases and 8-Ks (registries under-report failures), terminated/withdrawn trials kept in, and a ~90%-
failure base rate that "predict failure" already beats.

---

## The broader thesis, and where it's most likely wrong

**A thesis, not a finding** — an early-stage generalist technology VC's read of the AI-for-biology wave, 
held with conviction and no proof. The view: the outcome *distribution* of drug development is shifting 
(patient selection, biomarker stratification, adaptive design) while pricing stays anchored to historical 
base rates. If AI-enhanced trials have genuinely different odds and the market doesn't separate them from 
conventional ones, that gap is the opportunity — and the durable position isn't any single edge but the 
**infrastructure that keeps producing them as old ones compress**.

Where I expect it fails:

- **The hinge claim is a belief.** "AI improves success" carries the whole argument and no one
  has demonstrated it. The cited 80–90% Phase 1 figures are a small cohort on a safety gate; Phase 2
  evidence is thin and includes prominent failures (BEN-2293, EXS-21546). My conviction is from watching
  how these companies build, not outcome data.
- **Two mechanisms conflated.** AI-*discovered molecules* and AI-*enhanced trials* are separate claims;
  the second is what this thesis needs and the harder one to observe from outside.
- **No observable classifier for "AI-enhanced" ⇒ no trade.** Sponsors don't label trials this way, so the
  whole thesis depends on identifying, from public data, which side of the distribution a trial is on.
  That classifier is the crux — and it's buildable, because the signal lives in the **protocol**
  (eligibility, stratification, adaptive design, endpoints, partnership history), which CT.gov publishes
  and the watcher already ingests. This is the strongest reason to move the project's centre of gravity
  from the molecule to the trial design.
- **The base rate needs verifying.** I've used ~40% for oncology Phase 2; published figures are closer to
  25–30%, and this number anchors the whole mispricing argument.

Testing any of this is downstream of the pipeline's own next steps below — and even then, three of its own 
preconditions are worth naming honestly: whether "AI-enhanced" is identifiable from public protocol data at 
all (the linchpin — without it, most of this has no trade), whether AI-enhanced trials actually show a different 
outcome distribution once that classifier exists, and whether implied probabilities already differentiate them 
(if so, the gap is already priced). All three are speculative extensions of this project, not part of what's built.

---

## What to test, cheapest-fatal-first

| # | Assumption | If false | Cost |
|---|---|---|---|
| 1 | Partnership → acquisition interval is predictable from filings | The M&A leg fails | **Lowest** — 8-K data, no chemistry, testable in weeks |
| 2 | Outcome labels can be recovered honestly at scale, including failures | Every downstream dataset is biased toward successes. **Fatal** | Moderate — gates everything, built first regardless |
| 3 | A cheap baseline (base rates + genetics) isn't already as good as the physics | The physics is decorative | **Low** — the cheapest test that could kill the chemistry programme |
| 4 | The physics adds incremental information over that baseline | Chemistry unnecessary | Low, once 1+3 exist |
| 5 | Coverage extends to a real universe (entity resolution) | Breadth collapses | Low–moderate; unbuilt |

The sharp point: **the cheapest tests (1 and 3) aren't the ones this repository is built for**, and either
could invalidate a large part of the thesis on its own. The instinct is to improve the chemistry; the
correct first move is finding out whether it needs to exist. Assumption 2 is the one most likely to be
underestimated — slow, unglamorous, and exactly why the resulting dataset would be hard for anyone else to
replicate.

What this repository establishes is narrower than the thesis: the pipeline runs, its outputs are
reproducible from source, and its failure modes are visible rather than silent. That's a precondition for
testing the assumptions above — not evidence for any of them.

# Thesis

This document sets out the thesis behind the project: what would have to be true for it to
generate an edge, which of those conditions are already false, and the order in which the
remaining uncertainties could be tested. The [README](README.md) has the short version.

The structure is deliberate. The most common failure mode in a project like this is to build
the technically interesting component first and discover afterwards that the thesis never
depended on it. I have tried to do the opposite: identify the assumption whose failure would
be fatal, and note how cheaply it could be falsified. On the current evidence, the fatal
assumption is not "can we compute the chemistry" — that part works — but "does the chemistry
carry information the market does not already have," which remains untested.

On the limits of my own evidence: the claims below about development base rates, genetic
validation, market microstructure and portfolio construction are drawn from published
literature and standard results, not from direct experience. Where I am reasoning from
evidence, from first principles, or simply guessing, I have tried to say so.

---

## 1. The signal

A desk watching a clinical-trial readout receives a label: the endpoint was met or it was
not. The label is public within minutes and is priced quickly. It does not, on its own,
say much about whether the molecule should have been expected to work.

The idea here is to produce a second input for the same event: an estimate of whether the
drug engages its target, computed from the protein structure and the ligand chemistry
rather than from the sponsor's description of the result. The output is a continuous
quantity (ΔG, an implied Kd, a PK/PD-derived occupancy) rather than a categorical one,
which has three consequences:

- it can be scored against realized outcomes, so its value can be measured rather than
  argued;
- it can enter a probability model as one feature among others;
- accumulated across many trials, it forms a dataset that can be studied.

The reason this is worth attempting now is cost. Running structure-based chemistry on a
per-trial basis has historically required a computational chemist. An agent sandbox does it
per event, in minutes, for roughly the cost of the API calls. That does not make the
chemistry better, but it does make it cheap enough to run at a scale where it might be
useful.

---

## 2. The chemistry is unlikely to be a source of edge on its own

The same cost argument cuts against the project, and it should be stated plainly.

A signal's value tends to decay with the cost of reproducing it. The cost here is low.
AutoDock Vina is free and has been available since 2010; RDKit, the PDB, AlphaFold DB,
PubChem and Open Targets are all free; and the pipeline in this repository was assembled in
days with agent assistance. If a ΔG for a given trial is cheaply computable by anyone, it is
reasonable to assume it is already reflected in the price, or will be shortly.

So I do not think the docking is where an edge would come from. Candidates that seem more
durable to me, in rough order of how much I believe them:

| | Reasoning |
|---|---|
| The labeled, point-in-time dataset | Models tend to commoditize faster than data. Reconstructing honest outcome labels is genuinely laborious, in part because the registry under-reports negative results (see §3.5), and laborious things are harder to replicate. |
| The mapping from probability to price | Converting an estimated P(success) into a position depends on your own capital, execution and risk model. It is less exposed to open-source substitution than a scoring function. |
| The evaluation harness | New structure and affinity models appear frequently. The useful capability may be less "having a model" than "being able to test one against realized financial outcomes, point-in-time, quickly." |

The third is what this repository is oriented toward. The docking is intended as a
reference implementation and a control — a first estimator plugged into a harness — rather
than as the product. The event trigger, the sandbox, the result contract, the
reproducible-from-source guarantee and the (not yet built) backtest are meant to be
independent of which model produces the numbers.

That separation is currently aspirational rather than real. `docking_box` is specific to
Vina, there is no `estimator` field recording which model produced a number, and
`simulation.py` is a Vina-shaped module embedded in the prompt. Closing that gap is the
first item in [Next steps](README.md#next-steps).

The claim, then, is not that docking generates alpha. It is that this is a plausible
substrate for finding out what might. That framing is also why the reproducibility work in
this repo matters: a comparison across models whose outputs cannot be attributed to
specific code is not a valid comparison.

One caveat I would apply to my own reasoning: "we would license or build a proprietary
model" is the weakest of the three rows. Frontier labs are unlikely to be out-modelled by a
small team, a licensed model is not exclusive, and any model advantage appears to depreciate
quickly as open alternatives catch up. The version of that argument I find defensible is a
fine-tune on proprietary data — which returns to the first row.

---

## 3. Applying it before the readout

Scoring a readout after it has landed is the less interesting case. The result is public
within minutes and priced quickly, so a system that reacts to it is competing on latency,
which is not this system's advantage.

The case I find more compelling is running the same pipeline at **trial registration**, when
the design is first posted and the readout is one to three years away. At that point the
registry supplies the drug, target, mechanism, dose, phase, endpoints, population and
duration. The outcome does not yet exist for anyone. A forecast made there competes on
information rather than speed, can be computed across all registered trials, and has a long
window in which to be evaluated.

On that view, scoring readouts is not the product. It is how the training set gets built.

### 3.1 The seam

The market model currently gates every physics modifier on `has_readout`: with no clinical
result, it returns no call. This was a bug fix — the earlier version emitted a directional
call from chemistry alone, on trials that had reported nothing.

That gate is where a predictive model would attach. At present, "no readout" correctly means
"no call." A predictive version would replace that refusal with a forecast, and would only be
entitled to do so once the underlying estimates are good enough to stand without a clinical
result behind them. They are not currently.

### 3.2 Two axes of failure, of which this repo models one

| | Question | What bears on it | Status here |
|---|---|---|---|
| Molecule | Is this a good drug for that target? | Binding affinity, selectivity, free exposure relative to Kd, ADMET | Partially — coarsely, with known defects |
| Target | Does modulating that target change the disease? | Human genetic evidence, clinical precedent, pathway biology | Not modelled |

This asymmetry seems to me the most important thing about the predictive version. The
commonly cited figure is that roughly 90% of drugs entering clinical trials do not reach
approval, and published analyses attribute the largest share of Phase 2 failures to lack of
efficacy rather than to safety or pharmacokinetics. Lack of efficacy is frequently a
statement about the target rather than about the molecule: a compound can bind well, engage
its target, and still fail because modulating that target does not alter the disease.

Docking does not address that question. It addresses whether the molecule binds — and my
assumption is that the market is not usually wrong about *that*. So a pre-readout model built
on binding affinity alone would be answering the less decisive half of the question.

The literature I am aware of (e.g. Nelson et al., *Nature Genetics*, 2015, and subsequent
replications) reports that targets with human genetic support succeed at roughly twice the
rate of those without, which would make genetic evidence a stronger single predictor than
anything the docking produces. Open Targets exposes a genetic-association score per
target–indication pair at no cost. Combining a target-validation axis with a molecule axis
seems defensible; either alone does not.

### 3.3 Phase 1 and Phase 2 are different problems

Phase 1 endpoints are predominantly safety, tolerability, maximum tolerated dose and
pharmacokinetics rather than efficacy, with oncology dose-expansion cohorts a partial
exception. If the physics is more useful in Phase 1, it is for a narrower reason than it
first appears: what it can speak to is whether free drug concentration can plausibly exceed
Kd at the target at a tolerated dose. That is a therapeutic-index question, and it is within
the reach of chemistry and PK.

Phase 2 is an efficacy question, and therefore largely a target-validation question. The
physics is necessary but not close to sufficient, and the genetics axis would carry most of
the weight.

### 3.4 A retrospective check the current build does not pass

Before making any predictive claim, the chemistry should be run against a panel of drugs with
known outcomes. Applying the pre-readout question — is free Cmax above Kd? — to the two drugs
already in this repository, both of which are approved:

| Drug | Docked Kd | Free Cmax | Free Cmax / Kd | Model implies | Actual |
|---|---|---|---|---|---|
| sotorasib | 863 nM | 3,779 nM | 4.4× | engages target | approved |
| ivacaftor | 738 nM | 128 nM | 0.17× | does not engage | approved |

The pipeline as built implies that ivacaftor does not engage CFTR. Ivacaftor is an effective,
approved CF therapy. The docked Kd is far weaker than the drug's reported potency, which
traces back to the docking box covering about 19% of CFTR and not containing the binding
site, and to occupancy being computed from total rather than free drug.

(The free-fraction values used above are literature figures for plasma protein binding that I
applied by hand; I have not pulled them from a source in the pipeline. The direction of the
effect is not in doubt, but the exact ratios should be treated as approximate.)

This is the clearest reason to treat the chemistry and the market model here as placeholders.
It also reorders the issue list: in the reactive system, those two defects are documented
caveats, because a known clinical readout carries the call. In a predictive system there is
no readout to fall back on, so they become blocking.

### 3.5 What a credible backtest would require

The forecast is worth what the validation is worth, and I think a naive backtest here would
produce an encouraging and false result. Four problems seem material:

- **Look-ahead through structures.** PDB entries carry deposition dates. Docking against a
  co-crystal of the drug bound to its target that was deposited *after* the trial registered
  uses information that did not exist at prediction time. Structure selection has to be
  point-in-time. This makes "structure choice is not pinned" a leakage vector rather than a
  reproducibility nit.
- **Label bias.** Negative trials appear to be under-reported: sponsors publicise successes
  and discontinue quietly, and registry results compliance is incomplete. A dataset built from
  the registry alone would be missing-not-at-random in the direction that flatters the model.
  Outcomes would need to be reconstructed from press releases, 8-K filings and pipeline
  disclosures.
- **Survivorship.** Terminated and withdrawn trials have to remain in the sample.
- **Base rates.** With attrition around 90%, "predict failure" is already a strong naive
  baseline, and any model has to beat it — as well as beating a genetics-only baseline — before
  the physics can be said to add anything.

---

## 4. Where an edge would have to come from

I do not think the edge is in the chemistry. If there is one, it is in producing a
better-calibrated estimate of P(success) — and therefore of expected value — than the one
implied by the market, and in trading the difference. The chemistry is one input to that
estimate, and its job is to add incremental information rather than to carry the argument.

That reframing also disposes of the commoditization problem in §2. It does not matter much
whether a ΔG is cheap to compute. It matters whether the resulting probability estimate is
better than the one already in the price.

### 4.1 The position

> edge = our P(success) − the market's implied P(success)

which makes the implied probability a required input rather than an afterthought. It can in
principle be recovered from options around the catalyst, since a binary event leaves a
signature in the volatility surface, or by decomposing market capitalisation against a
risk-adjusted NPV of the pipeline. The position is taken on the divergence, not on the level.

Options are the natural instrument because the payoff is convex and the underlying
distribution around a binary catalyst is bimodal: it is possible to be paid for being right
about the probability without being confident about the direction. I should be clear that I
have not implemented any of this, and that translating an estimated probability into a sized
position is the part of the problem I know least about.

### 4.2 Breadth, and why a weak signal may still be usable

The standard result here is Grinold's fundamental law of active management, which relates the
information ratio to skill per decision and the number of independent decisions:

> IR ≈ IC × √breadth

A specialist analyst has a relatively high information coefficient across a small number of
names. A system of this kind would have a low information coefficient across a large number.
The following table is **illustrative, not measured** — the IC values are assumptions chosen to
show the shape of the relationship, and I have no empirical estimate of what the real ones
would be:

| | IC (assumed) | decisions/yr | IR ≈ IC·√N |
|---|---|---|---|
| Specialist, concentrated coverage | 0.15 | 15 | 0.58 |
| This system, modest edge, broad coverage | 0.05 | 200 | 0.71 |
| …with chemistry adding some IC | 0.07 | 200 | 0.99 |
| …and coverage extended further | 0.07 | 400 | 1.40 |

The implication is that a weak but genuine edge applied to many decisions can be worth more
than a strong edge applied to few. That is the argument for why a commoditized input might
still be useful: it does not need to be a good signal, it needs to be a slightly informative
one that can be produced at scale. Scale is what the agent sandbox provides.

It also suggests where to look. Sell-side and specialist coverage concentrates on a relatively
small number of high-profile catalysts, and the implied probabilities on those are likely to be
well-informed. The less-covered part of the universe is where a systematic estimate seems more
likely to add something. That is a coverage argument rather than an insight argument, and it is
the version of the thesis I find most plausible.

The corresponding universe constraint is that the trial has to be material to the sponsor's
enterprise value. A Phase 1 asset inside a large-cap pharmaceutical company is not going to move
the stock; the relevant names are smaller, single- or lead-asset companies.

### 4.3 The constraint that would most likely break this

The instinct to add more features is the wrong one here, because the binding constraint is
labels, not features.

Filtering to trials that are usable — small molecule, known target, resolvable structure, listed
sponsor, material to market capitalisation, recoverable outcome — plausibly leaves hundreds to
low thousands of clean examples, and the ~90% attrition rate makes the positive class smaller
still. On a sample of that size:

- the number of features that can be supported is on the order of tens, not hundreds;
- regularized linear models or gradient boosting are more likely to be appropriate than deep
  learning;
- cross-validation has to respect time ordering, since random folds leak future information and
  drug development is not stationary;
- and testing many feature sets against the same small sample will produce apparent results by
  chance, so hypotheses should be fixed in advance.

The most uncomfortable version of this: a baseline of historical PoS by phase and indication,
plus a free genetic-association score, is likely to be a reasonably strong prior on its own. The
chemistry has to demonstrate incremental value *over that baseline*, and it may not. That test
is cheap and should be run before any further investment in the physics. If the physics adds
nothing, that is a finding worth having early.

Finally, capacity. Options on small- and mid-cap biotechs are illiquid, spreads are wide, and
implied volatility collapses after a binary event. An edge that does not survive realistic
transaction costs is not usable, and I have not modelled them.

### 4.4 How this would be judged

Not by accuracy. By calibration, measured against the market's implied probability — Brier score
or log loss versus implied PoS, and a calibration curve. The question is not whether the model was
right, but whether it was systematically right in the cases where the market was wrong, by a margin
large enough to cover costs.

### 4.5 A gap that undercuts the argument above

Breadth is the core of §4.2, and breadth is precisely what the current implementation lacks.
Sponsor-to-ticker resolution is a hand-maintained six-entry `tickers.json`. Real resolution is an
entity-resolution problem — registry sponsor strings are inconsistent, sponsors are often
subsidiaries of listed parents, and many are private or pre-IPO and therefore not tradeable at all.
Until that is addressed, the system operates on a watchlist rather than a universe. The
demonstration is honest about what it does; the scaling claim is not yet supported by the code.

---

## 5. The broader thesis: AI is changing the outcome distribution, and pricing has not adjusted

**This section is a thesis, not a finding.** It reflects my own view, formed from following the
recent wave of AI-for-biology and life-sciences companies as an investor. It is a position I hold
with some conviction and no proof. None of what follows is established from data I have gathered,
and §5.2 sets out where I think it is most likely to be wrong. I state it as a hypothesis because
that is what it is, and because the value of writing it down is that it can then be tested.

Everything above treats the estimate of P(success) as the object of interest. The wider view is
that **the underlying probability distribution of drug development is shifting, and that market
pricing remains anchored to the historical one.**

The observations behind it — again, observations rather than measurements:

- **Trial-execution tooling is plausibly raising success rates, unevenly.** Patient selection
  algorithms, biomarker stratification, adaptive designs and cloud-lab automation should improve
  the odds for the trials that use them. The improvement is heterogeneous — it does not apply to
  every trial — and the market does not appear to distinguish between trials that have these
  advantages and trials that do not.
- **Large pharma has moved from building to buying.** Internal discovery capability has eroded,
  decision-making is diffuse, and the sector struggles to retain frontier research talent.
  Willingness to pay for external assets and tooling is high, and acquisition premiums look more
  like strategic anxiety than financial optimisation.
- **Data exclusivity is a depreciating moat.** Synthetic data generation and increasingly capable
  multimodal models will erode the value of proprietary clinical datasets on a horizon I would
  guess at 6–24 months. Companies valued primarily on data exclusivity face structural multiple
  compression.
- **The binding constraint has shifted from selection to speed.** The question is less "which
  drug works" than "how quickly can this move from discovery to commercialisation." Phase
  transition *speed*, not only phase transition *probability*, is the value driver — which makes
  trial design, patient selection and manufacturing automation the infrastructure layer that
  matters.

### 5.1 The implications, if the above is right

- **The central mispricing.** Options on Phase 2 catalysts are priced against a distribution
  informed by historical base rates. If AI-enhanced trials have a genuinely different
  distribution, and the market does not separate them from conventional ones, the gap between
  the two is the opportunity.
- **M&A is structural rather than cyclical.** If the buy-versus-build posture is durable, then
  partnership announcements in 8-K filings function as pre-acquisition signals, and the interval
  between partnership and acquisition may be predictable.
- **Data-moat compression is a specific short.** Companies whose valuations rest on proprietary
  clinical data should compress on a 12–24 month horizon. The trade depends entirely on whether
  current prices already discount this.
- **Early-stage assets are undervalued if timeline compression is real.** Risk-adjusted NPV is
  highly sensitive to time-to-market. If AI genuinely compresses timelines, the heavy discount
  applied to preclinical and Phase 1 assets for timeline uncertainty should narrow.
- **Edges normalise and migrate.** When a PoS mispricing is arbitraged away, the edge moves to
  second-order discrimination: which AI tooling produces real improvement, and which is
  marketing. The durable position is therefore not any single edge but **infrastructure that
  keeps producing new ones as old ones compress** — which is the argument for building the
  harness rather than the signal.

### 5.2 Where I think this is most likely to be wrong

A thesis is only useful if it is stated precisely enough to fail. These are the points at which I
expect mine would.

**The hinge claim is a belief, not a result.** "AI improves Phase 2 success rates" carries the
whole argument, and I have not demonstrated it — nor, as far as I know, has anyone. The
widely-cited figures (Phase 1 success rates of 80–90% for AI-discovered molecules) rest on a small
cohort, and Phase 1 is predominantly a *safety* gate, which is the least informative one. Phase 2
evidence is largely absent because the AI-discovered cohort is too young to have read out at scale,
and the Phase 2 results that do exist include prominent failures (BenevolentAI's BEN-2293,
Exscientia's EXS-21546). My conviction here comes from watching how these companies build, not from
outcome data, and I would want it treated accordingly.

**Two mechanisms are being conflated.** AI-*discovered molecules* (better chemistry) and
AI-*enhanced trials* (patient selection, stratification, adaptive design) are separate claims with
separate evidence. The second is the more plausible source of a PoS shift, and it is the one this
thesis actually needs — but it is also far harder to observe from outside the company.

**There is no observable classifier for "AI-enhanced," and without one there is no trade.**
Sponsors do not label trials this way. Three of the four implications above depend on being able
to identify, from public information, which trials sit on which side of the distribution. That
classifier is the crux of the thesis, not a detail of its implementation.

It is also buildable, and it is where this project's centre of gravity should move. The signal
does not live in the molecule; it lives in the **protocol**: biomarker-stratified eligibility
criteria, enrichment strategy, adaptive design features, endpoint selection, sponsor identity and
partnership history. ClinicalTrials.gov publishes those fields, and the watcher in this repository
already ingests and diffs them. The docking pipeline answers "is the molecule good." The thesis
above needs "is this trial better designed than the market assumes," and that is a different — and
more tractable — question.

**"Options price off historical base rates" is too strong.** Options price off whatever the market
believes, which may already embed an AI premium for the obvious names. The defensible version of
the claim is narrower: *implied probabilities may not adequately differentiate AI-enhanced trials
from conventional ones, particularly in names with thin analyst coverage.* That is testable; the
stronger version is a straw man an options desk would dismiss.

**The base rate itself needs verifying.** I have used a figure of roughly 40% for oncology Phase 2
in earlier drafts of this reasoning. Published industry analyses generally place oncology Phase 2
success *below* the cross-sector average, closer to 25–30%. Since this number anchors the entire
mispricing argument, it should be taken from a primary source rather than from recollection.

**The short thesis has a mechanism problem.** Synthetic data may commoditise clinical datasets for
*model training* while leaving their *regulatory* value intact, since regulators do not accept
synthetic evidence for approval. Compression may therefore hit the narrative multiple without
touching the underlying asset. Shorting a structural thesis on a 12–24 month horizon in volatile,
hard-to-borrow names is also expensive and prone to squeezes.

**Timeline compression is not unambiguously good for asset NPV.** Faster development raises NPV
through discounting, but if it is broadly available it also increases competition, brings more
entrants to the same targets, and erodes the effective exclusivity economics. The net effect is
not obviously positive and should be modelled rather than assumed.

---

## 6. What would have to be true, and how to find out cheaply

The thesis rests on a chain of assumptions. They are not equally likely to hold, and they are not
equally expensive to test. The useful discipline is to test the cheapest fatal one first, rather
than the most interesting one.

| # | Assumption | If false | Cost to test |
|---|---|---|---|
| 1 | The partnership → acquisition interval is predictable from public filings | The M&A leg of §5.1 fails | **Lowest.** Pure 8-K and deal data. Requires no chemistry, no options data and none of this repository. Testable in weeks |
| 2 | Outcome labels can be recovered honestly at scale, including failures | Every dataset built downstream is biased toward successes, and every result is unreliable. **Fatal** | Moderate — but it gates everything else, so it is built first regardless |
| 3 | "AI-enhanced" is identifiable from public protocol data | **Three of the four implications in §5.1 have no trade.** The linchpin | Low–moderate. The watcher already ingests the CT.gov protocol fields this would be built from |
| 4 | AI-enhanced trials actually have a different outcome distribution | The central mispricing does not exist | Moderate, and only possible once 2 and 3 exist. Note the cohort may still be too young to answer this |
| 5 | A cheap baseline (phase × indication base rates + genetic support) is not already as good as anything we can add | The project reduces to a free API call and the physics is decorative | **Low.** The cheapest experiment that could invalidate the chemistry programme |
| 6 | The physics adds incremental information over that baseline | The chemistry is unnecessary; the harness may still be useful for other features | Low, once 2 and 5 exist |
| 7 | Implied probabilities do not already differentiate AI-enhanced from conventional trials | The gap is already priced and there is no trade | Moderate — requires recovering implied probabilities from the options surface |
| 8 | The disagreement is large enough, and frequent enough, to survive transaction costs in illiquid names | An edge exists but is not harvestable — a common outcome in small-cap event strategies | Moderate |
| 9 | Coverage can be extended to a real universe (entity resolution; private sponsors excluded) | Breadth collapses, and with it the argument in §4.2 | Low–moderate; currently unbuilt |

Three things are worth drawing out of that table.

**The cheapest tests are not the ones this repository is built for.** Assumptions 1 and 5 require
none of the docking infrastructure, and either could invalidate a large part of the thesis on its
own. The instinct is to improve the chemistry. The correct first move is to find out whether the
chemistry needs to exist — and, separately, whether the M&A leg works, since it is nearly free to
check and independent of everything else.

**Assumption 3 is the linchpin and is currently unbuilt.** If "AI-enhanced" cannot be identified
from public data, most of §5.1 is untradeable regardless of whether the underlying claim is true.
It is also the most natural extension of what already exists here: the watcher fetches full CT.gov
protocol records, and eligibility criteria, stratification, adaptive-design features and endpoint
choice are exactly where such a classifier would look. This is the strongest argument for moving
the project's centre of gravity from the molecule to the trial design.

**Assumption 2 is the one most likely to be underestimated.** Reconstructing honest failure labels
is slow and unglamorous, and it is also the main reason the resulting dataset would be difficult
for anyone else to replicate — simultaneously the least appealing part of the work and the most
defensible.

What this repository establishes is narrower than the thesis: that the pipeline runs, that its
outputs are reproducible from source, and that its failure modes are visible rather than silent.
That is a precondition for testing the assumptions above. It is not evidence for any of them.

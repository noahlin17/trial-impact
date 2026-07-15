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

**Headline empirical result (§3.4, and [`trial-impact-service/validation/`](trial-impact-service/validation/README.md)).**
The central falsifiable claim this project tests — *does the docking score rank binding strength?* —
was tested from two angles: an 8-drug cross-target panel and a 13-ligand within-target Tyk2 series.
Both were negative. The cross-target panel is the *expected* regime failure — raw docking scores are
not calibrated across different receptors, and a narrow affinity range against a wide size range lets
size dominate almost by construction: Spearman ρ(−ΔG Vina, pKd) = −0.24 (it tracks ligand size,
ρ ≈ +0.45), and a CPU MM-GBSA rescore did not improve on it (ρ = −0.24, still size-tracking); at n = 8
the confidence intervals are wide and span zero, so this is **directional, not a powered refutation**.
The discriminating test holds target and scaffold fixed — the regime where structure-based scoring is
*supposed* to work — and it fails there too: in the Tyk2 series, cheap single-snapshot MM-GBSA gave
ρ = −0.54 (95% CI [−0.89, +0.07]) versus measured affinity, failing to beat size or raw Vina; n = 13
is still small and its CI spans zero. The complementary [pose-fidelity control](trial-impact-service/validation/pose_fidelity/README.md)
redocked **5/7 native ligands within 2 Å (71%), median top-pose RMSD 0.71 Å** — positive evidence for
pose geometry only (not affinity or binding strength), and it clears only the **first** of its two
pre-registered criteria: inter-seed agreement does *not* separate correct from incorrect poses, so the
seed spread is a reproducibility diagnostic, not a validated confidence signal. The A+C thresholds were
fixed in the [pre-registration](trial-impact-service/validation/PREREGISTRATION.md) before scores were
computed. Together, the two ranking negatives — one cross-target (expected), one in-regime (the
discriminating one) — and a geometry control that passes only its redock-success criterion define the
boundary; pose fidelity does not rescue affinity.

---

## 1. The signal

A desk watching a clinical-trial readout receives a label: the endpoint was met or it was
not. It does not, on its own, say much about whether the molecule should have been expected
to work.

The idea here is to produce a second input for the same event: an estimate of whether the
drug engages its target, computed from the protein structure and the ligand chemistry
rather than from the sponsor's description of the result. The output is a
geometric target-engagement classification plus a docking ΔG *diagnostic* and PK/PD-derived
exposure — note that the ΔG is *not* turned into an absolute Kd or occupancy, because it cannot
support that claim (§3.4, issue #4). This has three consequences:

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
reasonable to assume it is largely in the price already — though "cheap to compute" is not the same
as "priced in," a distinction §4 returns to.

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

That separation is now largely real. There is an explicit `Estimator` interface + registry
(`app/estimators.py`), every result records the `estimator` that produced it, and the session
**clones a pinned commit** rather than running a Vina-shaped module embedded in the prompt — so
the harness no longer bakes in the model. What remains: `docking_box` is still a Vina-specific
field on the shared contract, and the only estimators shipped are the docking pipeline and a
deliberately naive **control** (a heavy-atom size proxy) — the point of assumptions 5–6 below.
A real head-to-head against a *second physical* model, and the backtest that would make the
comparison meaningful, are still ahead: the pinned commit buys reproducibility, not validity.

The claim, then, is not that docking generates alpha but that this is a plausible substrate for
finding out what might — which is why reproducible-from-source outputs matter here, since a
comparison across models whose numbers cannot be attributed to specific code is not a valid one.

One caveat on the table above: any edge resting on the *model itself* is the weakest case —
frontier labs are unlikely to be out-modelled by a small team and a licensed model is not
exclusive, so the only version I find defensible is a fine-tune on proprietary data, which
returns to the first row (the data, not the model).

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

The market model gates every physics modifier on `has_readout`: with no clinical result it
returns no call. This is a founding contract, not a patch — **the chemistry is an *input* to a
probability estimate, never a standalone directional call.** A ΔG is not evidence that a stock
should move; only a clinical readout (or, later, a calibrated forecast) is entitled to a
directional call, and the physics enters as one term inside it. An early build violated this
invariant — it emitted a directional call from chemistry alone on trials that had reported
nothing — and the fact that that read as a *bug* is the point: the no-call gate is the correct
behaviour falling out of the design, not a special case bolted on.

That gate is also where a predictive model would attach. At present, "no readout" means "no
call." A predictive version would replace that refusal with a forecast, and would only be
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
seems defensible; either alone does not — and a baseline built from that axis is the one the
chemistry has to beat before it can be said to add anything (§4.3, and assumptions 5–6 in §6).

### 3.3 The chemistry is a preclinical / discovery-stage instrument by construction

The right way to place this pipeline is to ask, for a given trial, **what is already known going in
versus what the trial is actually testing** — and then see which side the chemistry sits on.

**Known *going into* Phase 1.** Target engagement / binding is a molecular property established
*preclinically*: a molecule only reaches the clinic after in-vitro potency, selectivity, and often
co-crystal or cell target-engagement data. Engagement is an **entry criterion**, and ΔG does not
change between phases. So the docking result — *does the molecule engage its target?* — is
**confirmatory of an already-established fact**, not information generated at the trial.

**Being *tested* in Phase 1 (unknown going in).** Human safety / tolerability, human PK, and the
tolerated dose — and, in some programmes, early human target-occupancy. These are exactly the
quantities the pipeline does **not** compute: occupancy is unset (it needs a Kd the docking cannot
supply, §3.4), and exposure comes from a *generic* Bateman model (fixed `ka`/`Vd`/`CL`, `F`=1), not a
human-calibrated one. **Phase 2/3** then test efficacy (a target-validation / disease-biology
question, §3.2) and replication at scale — also outside the physics.

So the chemistry answers a question that is **most uncertain in discovery / lead optimisation, before
the clinic**, and is largely settled by the time any trial exists. The system runs on clinical events
only because ClinicalTrials.gov is the available **event feed** — an operational trigger, not a claim
that a trial is where the physics is most informative. Phase therefore governs only *information
timing*: a Phase 1 trial's *outcome* is not yet public while a Phase 2/3 drug's is — but engagement
itself is public in both and routinely priced, so the chemistry surfaces **nothing net-new the market
does not already have** at either. A Phase 2/3 run
is simply an explicit **retrospective known-readout re-simulation** — a benchmark of the pipeline,
not a trade.

**This is a first pass, not a dead end.** Engagement is confirmatory today, but it is the **first
validated primitive** — a reproducible pocket route and docked pose — that every genuinely predictive
downstream piece consumes. The pieces that would actually address the *tested* unknowns (and so could
generate edge) are set out in §4 (and the README's *What it would take to be edge-generating* table).
Phase 1 is the *hypothesised* tier to build toward — a guess to test, not a result — because it is
first-in-human (least public data) *and* because what it validates (human PK, tolerability, tolerated
dose, sometimes human occupancy) is chemistry/pharmacology-grounded and so *might* be estimable from
structure before the readout is public, unlike the disease-biology question Phase 2/3 tests. The real
axis is what is *known* versus what is *being tested*, and the standing conjecture is that the earliest
stages — where least is public — leave the most room for a SIM to extrapolate an un-priced quantity.
Whether any stage actually does is empirical: the current build estimates none of these, any estimate
would be a probabilistic prior rather than a precise prediction, and only the backtest settles it.

Because the chemistry's claim is phase-invariant, **there is no phase weighting anywhere in the
model** — `market_model.assess` is phase-agnostic. Phase decides only *whether* an event's outcome is
still unpublished (Phase 1) or already public (Phase 2/3); it never scales the call. Phase-dependent
coefficients would only make sense across multiple tradeable tiers, and there is only one question
here.

### 3.4 There is no longer an absolute number to check against the literature

An earlier form of the pipeline turned the docking ΔG into an absolute Kd (`Kd = exp(ΔG/RT)`) and a
free-Cmax/Kd occupancy, then checked those against literature potency — and implied that *neither*
of the two approved drugs in this repo engages its target, a clear failure. **That whole check is
now moot, because the pipeline no longer produces any absolute quantity to check.** Once the docking
claim was demoted to geometric engagement (issue #4), there is no docked Kd, no occupancy, and no
binding-strength number — the ΔG that remains is a docking-objective diagnostic, explicitly not an
affinity and not comparable across molecules or targets. So a per-drug "does the model recover the
known potency?" comparison is not a meaningful test of the current build; it can only test a claim
the build deliberately stopped making.

The reason the claim was dropped, rather than recalibrated, is worth stating: 8 potent approved
reversible binders with clean ChEMBL Ki/Kd were docked through this exact pipeline, and the result
showed **no evidence that Vina ranks affinity** across these anchors (mostly ATP-competitive kinase hinge binders plus one soluble-enzyme inhibitor) — reproducing, on our own scale, the size-confounding that fast docking scorers have shown since the mid-2000s, not a new finding. The premise is a
*ranking* claim, so the test is **Spearman ρ** (rank correlation): `ρ(−ΔG, measured pKd) = −0.24`,
while `ρ(−ΔG, heavy-atom count) = +0.45` (the score tracks ligand size, not Kd), and
ligand-efficiency normalization did not rescue it (`ρ ≈ −0.02`). At n = 8 the CIs span zero, so this
is directional rather than definitive, but it is enough to withhold a strength claim. `exp()` is monotonic, so the invalid
transform was not the root cause; the docking/scoring layer itself cannot supply affinity
information. The free-drug (`fu`) occupancy machinery remains in the pipeline for any future
estimator that produces a real Kd, but the docking path leaves occupancy `None`.

This is the clearest reason to treat the chemistry and the market model here as placeholders.
It also reorders the issue list: in the reactive system this is a documented scope limit, because
a known clinical readout carries the call and docking is only a geometric corroborator. In a
predictive system there is no readout to fall back on, so recovering a real *strength* signal
(gnina CNN rescoring / MM-GBSA / FEP — §future work) becomes blocking.

The obvious next candidate, a single-snapshot **MM-GBSA rescore** of the docked poses (which adds
the electrostatics and desolvation terms Vina omits), was subsequently built CPU-only and evaluated
on the same eight anchors (`trial-impact-service/validation/`). It **also failed**: Spearman
ρ(MM-GBSA, pKd) = −0.24 (95% CI [−0.93, +0.62]), no better than Vina's −0.24, and it still tracks
ligand size (ρ ≈ +0.4). Applying the same discipline used on Vina, the cheap MM-GBSA is *not*
shipped as a strength estimator — the negative result is itself the finding, and it sharpens the
scope: recovering cross-target affinity needs a congeneric same-target series or far more expensive
sampling (explicit-solvent MM-GBSA ensembles / FEP), not a cheaper single-point.

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
  baseline that any model has to beat (the incremental-value test is §4.3).

---

## 4. Where an edge would have to come from

**North Star.** Intake a Phase 1 trial's design plus *all* public information — structure, target,
indication, planned dose, and any published in-vitro, PK, or prior computational results — and
estimate a quantity the trial is *testing but has not yet read out* (human PK, tolerability, human
occupancy) *before* it is published. The estimate only counts if it makes our probability **more
accurate than the one already in the price**: recreating a disclosed in-vitro potency, a reported PK
value, or a prior docking result adds nothing (those are public and, as a rule, already priced), so
the bar is *price, not publication* — the harder and more valuable case is resolving genuine
uncertainty on a quantity the market has *not* confidently priced, whether or not its raw inputs are
public. This is not built
today — the current output is confirmatory engagement — and the eventual output is a probabilistic
prior, not a precise prediction; the two constraints below (§4.1 beating the implied probability, and
the point-in-time backtest of §3.5) are what would turn such a prior into an actual edge.

I do not think the edge is in the chemistry. If there is one, it is in producing a
better-calibrated estimate of P(success) — and therefore of expected value — than the one
implied by the market, and in trading the difference. The chemistry is one input to that
estimate, and its job is to add incremental information rather than to carry the argument.

That reframing also disposes of the commoditization problem in §2. It does not matter much
whether a ΔG is cheap to compute. It matters whether the resulting probability estimate is
better than the one already in the price.

It also disciplines a tempting but flawed theory of the first unlock: *"the edge is a quantity that
could be computed by intense simulation or a computational chemist but has not been published."* That
is the right hunting ground and the wrong stopping condition. **Unpublished is not un-priced.** The
sponsor running the trial employs computational chemists and runs FEP / MD / PBPK / ADMET internally
and simply does not publish it, so the unpublished quantity is usually *already known to the party
that sets the price* and leaks into it through their actions (dose choice, trial design, guidance).
Computability guarantees neither materiality to the readout nor a mispriced consensus. And depth
compounds the problem: a deep sim of a heavily-followed drug is the worst case, because coverage is
maximal and the sponsor knows everything. The plausible edge is the inverse — a cheap, calibrated
estimate applied at **breadth** across many under-covered events (§4.2), where no informed party has
done the work — and whether any specific quantity is un-priced is an empirical question the
point-in-time backtest (§3.5) settles, not one that can be reasoned into existence.

This cuts less deeply than it first appears. Chemistry is almost certainly priced to *some* degree
already — sophisticated players use it explicitly, and it is baked in implicitly through the
sponsor's own dose and design choices. The claim is not that chemistry is unused; it is that AI has
lowered the cost of running *more* of it, on *more* names, to the point where applying it more fully
— where the ROI of an expert, a wet-lab assay, or a full FEP / MD campaign did not previously
justify the cost per trial — is plausibly an edge *right now*, simply from using more relevant
chemistry at all. That edge is explicitly not a long-term moat: as the cost keeps falling it
commoditises, and the durable position is the labeled point-in-time dataset and a *combination* of
factors, not the chemistry in isolation (§2 durability table; §5.1).

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

Two caveats keep this from reading as a free lunch. The law assumes **independent** decisions,
and biotech catalysts are not: outcomes cluster by mechanism, indication and macro regime, so
correlated bets push *effective* breadth well below the raw event count. And a signal is never
expressed frictionlessly — the fuller form `IR ≈ IC · √BR · TC` carries a transfer coefficient
`TC < 1` for position limits, sizing error and illiquidity, which in small-cap options (§4.3) is
well under 1. Both pull the achievable IR below the table's arithmetic; the table shows the
*shape* of the breadth argument, not a reachable number.

The converse is an equally valid strategy: a small number of very high-conviction positions,
sized heavily, where the edge per name is large rather than broad. That route is legitimate but
demanding — the conviction has to be genuinely earned, because even a correct read on the
chemistry leaves irreducible risk. Trial design, dose selection, execution, and ordinary clinical
and lab variability introduce failure modes the molecule axis does not touch (§3.2), so the gap
between "the molecule should work" and "this trial will read out positive" never closes to zero.
Breadth and conviction are two ways to convert the same estimate into return; which one applies is
a function of how sure the estimate actually is.

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

**This section is a thesis, not a finding.** It reflects my own view, formed from watching how this
recent wave of AI-for-biology and life-sciences companies is built and financed — not from a
bench-science or public-markets seat. It is a position I hold with some conviction and no proof. None of what follows is established from data I have gathered,
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
  guess at 12–24 months. Companies valued primarily on data exclusivity face structural multiple
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

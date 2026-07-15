# Trial Impact

**A structure-based drug–target *engagement* pipeline that stress-tested its own central premise —
and re-scoped the claim when the premise failed.**

Given a clinical-trial event, the service routes the drug and its target to the right experimental
structure and binding pocket, docks the ligand (AutoDock Vina) into that pocket, and reports whether
the molecule makes a **reproducible, geometrically sound engagement** — computed from the structure
and the chemistry, not from the sponsor's description of the result. A closed-form PK/PD solve adds
tissue exposure (Cmax/AUC).

What makes this more than "a pipeline that runs" is the validation below: the tempting claim — that a
docking score measures *how strongly* a drug binds — was tested against measured affinities and **did
not hold** (nor did a physics-based rescore), so the shipped claim is the narrower one the method can
actually support. The test is small (n = 8) and **directional, not definitive** — but it points the
same way as two decades of docking literature, and the point is that the project tested its own
premise and shipped the narrower claim rather than the flattering one.

## Headline result — a docking score is not binding strength (and a physics rescore doesn't fix it)

I tested the affinity premise on **8 approved drugs with real, measured affinities** (ChEMBL Ki/Kd,
pKd 7.4–10.1), each docked through this exact pipeline, then rescored with a CPU MM-GBSA:

![Head-to-head: neither Vina nor single-snapshot MM-GBSA recovers measured affinity; both track ligand size](trial-impact-service/validation/results/headtohead.png)

| predictor | Spearman ρ vs measured pKd | ρ vs ligand size |
|---|---|---|
| heavy atoms (size baseline) | −0.52 | — |
| Vina −ΔG | **−0.24** | +0.45 |
| MM-GBSA −ΔG | **−0.24** | +0.40 |

- **The raw Vina score does not rank cross-target affinity** — it tracks ligand **size** (the biggest
  molecules score "best" while being weaker binders).
- **A physics-based MM-GBSA rescore does not rescue it** — same ρ, still size-confounded ([`validation/`](trial-impact-service/validation/README.md), reproduce with `make validate`).

**Read this as directional, not decisive.** At n = 8 the 95% CIs are wide and span zero (Vina ρ
[−0.83, +0.62]), so this does not *prove* Vina is uninformative — it shows **no evidence** of affinity
ranking on this set, exactly as the long-known size confound predicts. A powered refutation would need
a far larger, structurally diverse anchor set; what is defensible today is the negative *direction*
and the discipline of not shipping a strength claim the data cannot support.

So the pipeline makes only the claim the method can back — **geometric target engagement** (did the
molecule dock into the experimentally-resolved site with a reproducible multi-seed pose) — and
deliberately **not** an absolute Kd, occupancy, or binding-strength number.

**What it *can* claim** ✅ reproducible pocket routing (covalent-tether → co-crystal → fpocket → blind
tiers, recorded in `docking_box.mode`); a reproducible docked pose; directional PK/PD exposure; and an
auditable, self-falsifying validation of its own scoring.
**What it *cannot* claim** ❌ absolute affinity / Kd; target occupancy; that docking ranks cross-target
potency; or a validated market prediction — the market/stock layer further down is an **illustrative,
un-backtested downstream demo**, not a result.

Scientifically, this is a **preclinical / discovery-stage engagement instrument**: target engagement
is established *before* the clinic (an entry criterion for Phase 1), so by the time a molecule has a
trial the chemistry is **confirmatory, not predictive** of the trial's real unknowns. It runs on
clinical events only because ClinicalTrials.gov is the available event feed. Because engagement is
public preclinical information, the pipeline as-is surfaces **nothing un-priced** — a later-phase run
is an explicit **retrospective known-readout re-simulation**.

This is deliberately a **first pass**: engagement is not itself net-new information, but it is the
**first validated primitive** — a reproducible pocket route + docked pose — that the genuinely
predictive pieces build on (calibrated affinity, structure-derived human PK, target-validation /
genetics, a calibrated P(success)). Why an event's *phase* is only an information-timing distinction,
why Phase 1 is the *hypothesised* tier to build toward, and what net-new data an edge would actually
require are set out in [Trial phase](#trial-phase--a-preclinical--discovery-stage-instrument) and
[What it would take to be edge-generating](#what-it-would-take-to-be-edge-generating--improve-on-the-markets-estimate-dont-re-derive-the-knowns).

> **North Star.** Take a Phase 1 trial's design plus *all* public information — structure, target,
> indication, planned dose, and any **published in-vitro, PK, or prior computational results** — and
> produce a model estimate of a quantity the trial is *testing but has not yet read out* (human PK,
> tolerability / MTD, human target occupancy). The estimate is useful only if it is **net-new against
> everything already public**: recreating a disclosed in-vitro potency, a reported PK parameter, or a
> prior docking result is by definition already priced and adds nothing. Two honest bounds: **(1)** the
> output is a *probabilistic prior with error bars*, and edge requires it to beat the market's implied
> probability on a point-in-time backtest — the estimate alone is not a trade; **(2)** the idea
> generalises to later phases only in *form* — Phase 2/3 test efficacy / disease biology the chemistry
> does not model, so those need a different input (genetics / target-validation), not more docking.
> **None of this is built today** — the current output is confirmatory geometric engagement; the North
> Star is the direction the roadmap is for.

> **Not investment advice.** Output is an automated research signal for informational
> purposes only; a disclaimer is attached to each assessment.

---

## How it works

![Pipeline architecture](docs/architecture.png)

A trial event is routed to the right structure and pocket, docked, and classified as *geometric
engagement*; a PK/PD solve adds exposure. Each estimator runs head-to-head against a size-only
baseline it must beat — and the validation experiment (bottom-left) is what tests, and falsifies,
the affinity premise. The market layer is an illustrative downstream demo.

---

## Demo — the dashboards

Served locally from the two committed result artifacts (`results/sim_*.json`) into the real Flask
app — no re-dock. Both surfaces report the honest claim only: a **geometric engagement**
classification as the readout, with the docking ΔG kept as a **QC/diagnostic labelled "not an
affinity"** — never an absolute affinity or occupancy.

**`/status`** — one row per trial: the geometric engagement classification, a docking ΔG diagnostic
(not an affinity, not comparable across molecules), and the (illustrative) price calls.

![Status dashboard](docs/dashboard-status.png)

**`/analysis`** — the corpus view leads with the geometric-engagement chart; ΔG is labelled a
*docking-objective diagnostic — not an affinity, not comparable across molecules/targets*; the charts
are engagement-count and PoS, not Kd/occupancy; occupancy is shown only when a calibrated Kd exists
(the docking estimator reports none).

![Analysis dashboard](docs/dashboard-analysis.png)

---

## Motivation & (unvalidated) market thesis

> **Read this section as motivation, not as a result.** The market/stock layer is an
> illustrative downstream demo: a rules-based engine on a small hand-curated watchlist, **not
> backtested against realized price moves**. It exists to show what a validated engagement signal
> *could* eventually feed; nothing here is a tradeable claim. The defensible, tested core of the
> project is the biophysics validation above.

The goal is **predictive intelligence in the window between a trial's design becoming public and
its readout** — using computational chemistry (and, over time, the other structure-derived axes
below) to estimate a quantity the trial is *testing but has not yet reported*, before the outcome
is known. That estimate is scored against the realized outcome, entered into a probability model as
one feature among several, and accumulated into a dataset. Reacting to a readout *after* it prints
is a possible secondary use — the label is public within minutes and priced quickly, and says
little about whether the molecule *should* have been expected to work — but it is not the aim; the
value is in the estimate formed *ahead* of the event.

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

By Grinold's fundamental law, `IR ≈ IC × √breadth`: a weak but genuine signal applied to many
decisions can be worth more than a strong one applied to few. A commoditized input does not need to
be a good signal — only a slightly informative one produced at scale, which is what the sandbox
provides. The bar is not a *great* signal but a **good-enough aggregate**: no single input has to be
strong, only the full set of factors has to make our P(success)/EV estimate more accurate than the
market-implied one. It also says where to look: specialist coverage concentrates on a few high-profile
catalysts, so the **less-covered tail** is where a systematic estimate is most likely to add
something — a coverage argument, not an insight one. (The illustrative IR arithmetic is in
[THESIS §4.2](THESIS.md).)

### What this repository does and does not establish

It establishes that the pipeline runs, that its outputs are **reproducible from source**, and that
its failure modes are visible rather than silent — a precondition for testing the thesis, not
evidence for it. Both the chemistry and market model are placeholders: docking is now pocket-routed
(covalent tether → co-crystal → fpocket → blind, per `docking_box.mode`) but reports only *geometric
engagement* (the 8-anchor calibration killed the affinity reading, headline above), the PK model is
generic, and the market model is uncalibrated and rules-based. The current numbers are not tradeable.

The assumption most likely to be fatal is not "can we compute the chemistry," which works, but "does
the chemistry carry information the market does not already have," which is untested. A baseline of
phase × indication base rates plus a free genetic-association score is probably a strong prior on its
own, and the physics must beat it — a cheap experiment that should run before any further physics.

### The wider view

A broader and more speculative hypothesis motivates the longer-term direction: AI tooling may be
shifting the *outcome distribution* of drug development while pricing stays anchored to historical
base rates — which would move the most valuable target from *the molecule* to *the trial design* the
watcher already ingests. It is held as a hypothesis, not a finding. The full argument — the pre-readout
case, what a credible backtest would require, where it is weakest, and the order its assumptions
could be falsified — is in **[THESIS §5–6](THESIS.md)**.

---

## Architecture

```
ClinicalTrials.gov API v2 ──poll──▶  ctgov-watcher/            (gives CT.gov a webhook)
                                       │ diff records, detect material change
                                       ▼ POST /webhook/trial-update  (HMAC-signed)
┌──────────────────────────────────────────────────────────────────────────┐
│                     trial-impact-service/  (Flask)                       │
│  TRIGGER   verify signature → resolve tickers → create Devin session ────┼─▶ Devin session
│  ORCHESTRATE  Devin runs docking + PK/PD in its sandbox ◀────────────────┼── ΔG (score),
│  RECONCILE /poll → parse SIM_RESULT_JSON → market model → alert          │   engagement
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
(UniProt → experimental PDB or mmCIF, else AlphaFold), fetch the ligand (PubChem → SMILES →
RDKit 3D), dock with AutoDock Vina across a fixed seed set for a mean ΔG ± sd, then solve a
PK/PD model in closed form (Bateman) for tissue exposure (Cmax/AUC). The docking ΔG is reported
as a geometric engagement classification, not a calibrated affinity (issue #4).

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
[the result contract](trial-impact-service/README.md#the-result-contract-and-why-it-has-estimator--code_patched-fields).

### On the label

The framing above assumes each event arrives with a **classification** (endpoint met /
missed) that the physics estimate sits *alongside*. Today that label is supplied by
per-trial enrichment (`watchlist.json`), **not** derived automatically —
ClinicalTrials.gov does not expose met/missed in machine-readable form. An LLM classifier
over the CT.gov results section and the sponsor's press release is the intended path and
is tracked under [Next steps](#next-steps); it does not exist yet. The physics half of the
pipeline is the part that is built.

---

## Results from two real pipeline runs

Genuine outputs from the committed pipeline (raw JSON + rendered dashboards in
[`results/`](results/)). Docking runs a fixed seed set (42, 43, 44) and reports mean ± sd —
deterministic *given the same resolved structure*, but the structure is fetched live and not pinned,
so the ΔG is not point-in-time reproducible (issue #10 — a silent degrade to a different
structure/pocket, e.g. KRAS routing to 7VVB instead of the curated 6OIM, yields a materially
different ΔG).

| Drug (status) | Target × Drug | Structure (route) | Engagement ‡ | ΔG (diagnostic, kcal/mol) | Flags | Model call *(rules-based demo — not a prediction)* |
|-------|---------------|-----------|-----------|---------------|-----|-----------|
| **Approved** (Lumakras, 2021) | KRAS × sotorasib | 6OIM · covalent-tethered (Cys A:12) | experimental-site (reproducible pose) ‡ | **−7.202 ± 0.187** | drug-likeness · covalent | AMGN ↑ · REGN/NVS ↓ *(illustrative)* |
| **Approved** (Kalydeco, 2012) | CFTR × ivacaftor | 6O2P · holo-ligand (VX7) | experimental-site (reproducible pose) ‡ | −7.404 ± 0.007 | clean | VRTX ↑ · CRSP/BLUE ↓ *(illustrative)* |

Both are **approved** drugs, chosen because the answer is known — a **backtest against ground truth,
not a forecast**, carrying no tradeable signal. Read the columns as: engagement + exposure = the
product (confirmatory, not net-new); ΔG = a docking-objective diagnostic, not an affinity and not
comparable across rows (issue #4); `Model call` = the rules-based placeholder. **‡ Engagement is
*geometry, not strength*** — the ligand docked into the experimentally-resolved site with a
reproducible multi-seed pose (sd ≤ 0.75); no Kd or occupancy is surfaced. The ΔGs are cognate/holo
(partly circular) and the covalent KRAS score is Vina's reversible function (a pocket-correct lower
bound, [issue #2](#known-issues)); `code_patched: false` confirms the numbers came from
`simulation.py` unpatched. Routing is class-based, not drug-based, so a net-new drug in either class
routes itself the same way.

The **analysis view** (`GET /analysis`,
[`results/analysis_dashboard.html`](results/analysis_dashboard.html)) inspects the whole corpus:
cross-run charts (ΔG diagnostic vs PoS delta, engagement counts), a sortable table, and a per-run
drill-down with the 3D pose, PK/PD exposure curve, and a reasoning trace for each PoS delta.

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
| **Biologics** — antibodies, proteins, ADCs, oligos/siRNA, cell & gene therapy | ○ | **Cannot be docked** — no SMILES, and binding is a protein–protein interface, not a ligand in a pocket. Excludes a large fraction of the oncology pipeline; needs a separate affinity path (PPI scoring / co-folding). |
| **PROTACs & molecular glues** | ○ | Require a *ternary* complex (target + ligase + linker). Fundamentally a different modeling problem, not a harder docking run. |

### Target / receptor

| Target class | | Where it stands |
|---|---|---|
| **Single-chain globular soluble proteins** with a legacy-format experimental PDB | ✅ | The good case. With a curated or discovered co-crystal the box is centered on the real bound ligand, not the centroid. |
| **AlphaFold-predicted structures** | ◑ | Used as fallback when no experimental structure resolves; run confidence drops 0.9 → 0.7. A predicted backbone is fine; predicted side-chain rotamers in a pocket are the weak point. A predicted model has no co-crystal ligand, so it can only reach the fpocket/blind tiers. |
| **Large multi-domain or membrane proteins** | ◑ | **Much improved for CFTR.** When a drug-bound co-crystal is curated/discovered (CFTR → 6O2P, ivacaftor's VX7 site) the box is on the actual pocket rather than a central slab. Without one, a large receptor still hits fpocket then the blind box — pocket-aware routing helps only where a co-crystal exists — [issue #2](#known-issues). |
| **mmCIF-only structures** (most large modern cryo-EM) | ✅ | `fetch_structure` falls back to the mmCIF file and converts it with `gemmi` before AlphaFold, so these dock as real experimental structures. (Neither published run now exercises this — both pin a curated `.pdb` holo — but the path stays for mmCIF-only targets.) |
| **Multi-chain complexes, ensembles, flexible side chains** | ○ | One structure, rigid receptor, no ensemble. Vina supports flexible side chains and ensemble docking; both change every run's numbers, so they were deferred. |
| **Nucleic-acid targets** (RNA/DNA) | ○ | Vina's empirical scoring function is parameterized for protein–ligand, not nucleic-acid–ligand. |

### Bond & interaction type

| Interaction | | Where it stands |
|---|---|---|
| **Reversible non-covalent binding** — H-bonds, hydrophobic contact, vdW, electrostatics | ✅ | Exactly what Vina's empirical function scores. This is the only interaction class the ΔG is actually valid for. Ivacaftor is the clean case. |
| **Covalent inhibitors** | ◑ | **Tethered to the right pocket, still scored reversibly.** An RDKit SMARTS match catches acrylamide, halo-acetamide, vinyl sulfone, boronic acid/ester and epoxide warheads; when the warhead is a tetherable Michael acceptor **and** the target is a curated covalent class (KRAS G12C, EGFR, BTK), the ligand is Meeko-tethered to the reactive cysteine and docked in a residue-centered box (KRAS/sotorasib). Vina still scores non-covalently — no bond-formation enthalpy — so the ΔG is a pocket-correct **lower bound**, not true reactive scoring (that needs AutoDock-GPU, off conda channels). Non-tetherable warheads / non-curated targets fall back to reversible docking with a warning. |
| **Allosteric & cryptic pockets (curated)** | ◑ | A blind box cannot find a cryptic pocket closed in the apo structure — which is exactly why covalent classes pin an *open* drug-bound holo (KRAS's switch-II pocket in 6OIM). Works where the class/structure is curated; an uncurated cryptic pocket still degrades. |
| **Metal coordination** (zinc proteases, metalloenzymes) | ○ | Vina handles metal centers poorly without specific parameterization. A zinc-binding drug's affinity would be badly underestimated. |
| **Halogen bonding, explicit bridging waters** | ○ | Not modeled. The receptor is stripped of waters before docking. |

### Pharmacology

| Assumption | | Where it stands |
|---|---|---|
| **One-compartment Bateman model, closed form** | ◑ | `ka`/`Vd`/`CL` are fixed physiological placeholders and `Kp` is order-of-magnitude, so exposure is **directional, not drug-specific** — it will tell you a 960 mg dose achieves high exposure, not what sotorasib's real Cmax is. No bioavailability term either (`F` = 1), which flatters oral exposure. |
| **Target occupancy** | ○ | **No longer reported by the docking estimator.** Occupancy is `C_free/(C_free + Kd)`, which depends entirely on a Kd the Vina score cannot support (issue #4). The free-drug (`fu`) machinery and its curated table remain in `run_pkpd` for any estimator that *does* supply a real Kd, but the docking path leaves occupancy `None`. Exposure (Cmax, AUC) is Kd-independent and is retained. |
| **Single dose, exposure only** | ○ | No steady-state accumulation; Cmax is the peak of a single-dose curve and AUC is AUC(0–48h), not AUC(0–∞). Most of these drugs are dosed chronically. |
| **Kd from an empirical docking score** | ○ | **Removed as a headline.** `Kd = exp(ΔG/RT)` treated Vina's empirical score as a rigorous free energy; the 8-anchor calibration showed the raw score does not rank affinity (issue #4), so no Kd is surfaced — the uncalibrated value survives only as a labelled `provenance.vina_pseudo_kd_nM`, never priced. |

Genuine per-drug pharmacology needs enrichment overrides (`fu`, `Vd`, `CL` per drug — the
same mechanism as `endpoint_outcome`) or a structure→PK model.

### Trial phase — a preclinical / discovery-stage instrument

The pipeline answers *does the molecule engage its target at a plausible exposure?* — a
**preclinical / discovery-stage** question. Engagement is an entry criterion proven before Phase 1,
so at any trial the docking is **confirmatory of an already-public fact**, not new information; the
system runs on clinical events only because ClinicalTrials.gov is the available event feed, so phase
governs *information timing*, not what the chemistry computes (a later-phase run is a retrospective
known-readout benchmark). The *hypothesised* payoff is to build toward Phase 1 — first-in-human,
least public data, and what it validates is chemistry-grounded (human PK, tolerability, occupancy),
so those quantities *might* be estimable from structure before the readout, unlike the disease
biology Phase 2/3 tests. That is a hypothesis, not a result — the reproducible pose is the first
validated primitive the predictive pieces consume ([Next steps](#next-steps)), and the rest is
unbuilt.

**The practical upshot.** The *binding* half is defensible today for a reversible small molecule
against a small globular protein with an experimental structure, and — via pocket-aware routing — for
covalent small molecules against a curated class (a reversible-scored lower bound); everything else
degrades to fpocket/blind, and biologics are out of scope. The *pharmacology* half is weaker (generic
PK, no bioavailability term → order-of-magnitude exposure), and occupancy is not reported at all. The
surviving claim is *geometric engagement*.

### What it would take to be edge-generating — improve on the market's estimate, don't re-derive the knowns

Edge does not require secret data. It comes from making our estimate of P(success)/EV **more accurate
than the market-implied one** — either by (i) resolving more certainty on a quantity that is genuinely
*uncertain* (even when its raw inputs are public), or (ii) computing something not yet published, or
published but **not already priced in**. What earns nothing is re-deriving a fact the market already
has and weights correctly: engagement fails on that count — it is known going into Phase 1, public,
and routinely published alongside potency and structures, so re-computing it moves no probability.
The gains therefore live in the quantities a trial is actually **testing** — still uncertain at the
readout — most of which need new chemistry or data the current build lacks (honest that any early
edge would be thin):

| What the trial actually tests (unknown going in) | What it would take to compute it | Chemistry-computable? | Edge realism |
|---|---|---|---|
| **Safety / tolerability, tolerated dose** (Phase 1 core) | Off-target / selectivity docking against a liability panel + ADMET/DMPK models (hERG, metabolic stability, reactive-metabolite risk for covalent warheads) | Partly — builds directly on the docked-pose primitive | Attrition here is large and under-modelled; plausibly the best chemistry-side lever |
| **Does free drug reach & occupy the target at a tolerated dose** (therapeutic index) | Measured / predicted **human** PK (`Vd`, `CL`, `F`, `fu`) to replace the generic Bateman model, **plus** a calibrated affinity to turn exposure into real occupancy | Partly — needs a validated strength estimator first | Turns exposure into the TI question P1 probes; limited until PK is drug-specific |
| **Durability / resistance** (emerges later, unknown early) | Re-dock against clinically-observed resistance mutants (e.g. gatekeeper mutations) | Yes — direct use of the pose primitive | Genuinely forward-looking and structure-computable; narrow applicability |
| **Efficacy — does engaging the target help patients** (Phase 2, the biggest unknown) | Target-validation / human-genetics axis (Open Targets association, Mendelian randomisation) — **not** chemistry | No | Strongest documented predictor of P2/P3 success and plausibly under-priced; the real edge candidate |
| **Whether any of the above is *tradeable*** | A **point-in-time labelled corpus** (as-of features + realised outcomes/returns), sponsor→ticker resolution, and a **calibrated P(success)** fit and backtested against genetics-only and base-rate baselines | N/A (infrastructure) | Prerequisite for *claiming* edge at all — see [THESIS §3.5, §4](THESIS.md) |

The through-line: the docked pose is the **input** these consume, not the signal itself. A calibrated
strength estimator would unlock the occupancy/selectivity rows; the genetics axis + a labelled corpus
are what would let the market model claim anything beyond "it runs." Even assembled, the realistic
first-pass edge is **breadth and speed**, not one decisive number — unproven until the backtest
([THESIS §3.5](THESIS.md)) runs.

**"Unpublished" is not "un-priced."** A tempting theory is that the first unlock is a quantity that
*could* be computed but has not been published. That is the right hunting ground but the wrong
stopping condition: the sponsor usually computed it privately (FEP/MD/PBPK/ADMET) and it leaks into
the price through their actions, and depth-per-name favours them while breadth-across-many-events
favours a cheap systematic pipeline. Whether a quantity is actually un-priced is **empirical** — only
the point-in-time backtest answers it. (Full argument: [THESIS §4](THESIS.md).)

---

## Catching a bug: when the result was too clean

On the first real run, the stored result matched the example values embedded in my own prompt: the
extractor was matching the prompt's example `SIM_RESULT_JSON` *before* Devin's actual output further
down the transcript. Fix: skip prompt-echo messages, take the last decodable result marker, add a
regression test, and make the prompt's example un-parseable so it can never be mistaken for a result.

This is the habit behind the validation section above, and behind the `code_patched`
field in the result contract: a plausible number is not a correct number until it's
been checked. The same instinct later caught a run reporting numbers the committed code
could not have produced — because the agent had quietly patched around a broken
upstream API. See the service README. **No numbers, prompts, or behaviour were tuned to
make any result come out a particular way** — and since the pipeline emits no absolute
Kd/affinity/occupancy (issue #4), there is no per-run number to check against a literature
Kd/IC50 anyway; the one claim that *can* be checked — *does the score rank affinity?* — is
the 8-anchor test in the headline.

---

## Quick start

```bash
cd trial-impact-service
cp .env.example .env          # set DEVIN_API_KEY (Slack/SMTP optional)
                              # .env.example ships a non-empty WATCHER_SHARED_SECRET, so the
                              # webhook is ON by default. The endpoint fails CLOSED: blanking the
                              # secret disables it (503 to every caller) — it never fails open.
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

The **real open work**, sequenced deliberately — each step is worthless until the one above it is
sound, and calibrating a pricing model on a biased signal just launders the bias. The full argument
is in [THESIS.md](THESIS.md). *(The foundational engineering/science steps — the harness/estimator
split, pocket-aware routing, covalent tethering, free-drug PK/PD, multi-seed ΔG, native mmCIF, and
the conda-lock sim env — are **done**; they are logged under
[Addressed issues](#known-issues) rather than repeated here.)*

**1 · Add the axis the physics cannot see.** Drugs mostly fail on **target validation**, not
chemistry. Pull the **Open Targets** genetic-association score (genetically-supported targets succeed
~2× as often — the strongest known public predictor, stronger than anything docking produces), plus
clinical precedent and trial-design quality. Then build the retrospective winners/losers panel — the
place a rescoring estimator (gnina/MM-GBSA) would have to prove it adds IC over a
genetics-plus-base-rate baseline, since docking contributes only *geometric engagement* (issue #4).

**2 · Build the corpus — point-in-time, honest labels.** Accumulate `(trial design, physics,
genetics, outcome, realized move)` per trial, backfilled over history. Two rules make or break it:
**filter structures by deposition date** (a co-crystal published *after* registration is look-ahead
bias) and **reconstruct outcomes from press releases / 8-Ks, not just CT.gov** (negative trials are
under-reported, so a registry-only corpus skews toward winners). Keep terminated/withdrawn trials in;
close the label loop with an **LLM classifier**, not `watchlist.json`.

**3 · Fit a calibrated P(success) — respect the small-n trap.** The goal is a **better-calibrated
probability than the market's**, chemistry as one feature among many. The binding constraint is
**labels, not features**: a clean filter leaves hundreds-to-low-thousands of examples, so support
10–30 features (regularized logistic / gradient boosting, not deep nets).
- **Time-series CV, never random k-fold** — folds leak the future; drug development is non-stationary.
- **Test the cheap baseline first** (PoS by phase × indication + Open Targets); **the chemistry must
  prove incremental IC over it — it may not**, worth knowing before building more physics.
- Pre-register hypotheses. **KPI is calibration, not accuracy** — Brier / log-loss and a curve
  *against the market's implied PoS*: not "were we right?" but *"right where the market was wrong, by
  enough to pay the spread?"*

**4 · Then price it — the edge is breadth.** Recover the market's **implied** probability (options
around the catalyst, or market cap vs risk-adjusted NPV) — the edge is `our P − implied P`, not the
level of our call — and trade the divergence in convex **options**. By `IR ≈ IC × √breadth`, a modest
edge applied 200–400×/yr beats a brilliant one applied 15×, so the edge is **coverage arbitrage** in
the neglected SMID-cap tail, not out-analyzing a specialist on a marquee Phase 3. That needs real
**sponsor→ticker entity resolution** (issue #7) — a six-entry `tickers.json` is not breadth — and
**honest slippage** (illiquid options, brutal IV crush; an edge unharvestable at size is not a
business).

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

Most were found by auditing the code after the runs were published, and several share one structure:
a locally reasonable choice consumed downstream as a stronger claim than it can support — a relative
score read as an absolute Kd (#4), a tractable search box described as covering the receptor (#2), a
total concentration reported as engagement (#1, fixed), a drug-likeness heuristic priced as toxicity
(#3, fixed). None raise an error; the estimate simply becomes less well-founded than its use implies.

**The design invariant.** Naming that species makes it a principle: *no quantity may be consumed
downstream as a stronger claim than the step that produced it can support.* Several of the project's
clearest decisions are that one invariant applied — the **preclinical / discovery-stage scope** (not
consumed as a Phase 2/3 efficacy claim, [Trial phase](#trial-phase--a-preclinical--discovery-stage-instrument)),
the **no-call gate** (a ΔG is an input to a probability, so no readout → no directional call,
[THESIS §3.1](THESIS.md)), the **estimator/harness split** (Vina is one implementation, not "the
model"), and the **drug-likeness flag** (information, never a priced safety event). #4 was the last
open violation; it is resolved by **re-scoping the docking claim**, not by calibrating the number.

**Issue #4 — why docking is now only a geometric claim.** #4 began as "ΔG documented as *relative* but
consumed as *absolute* Kd." The plan was to keep Vina's *ranking* and demote only its magnitude — but
docking the 8 anchors (pKd 7.4–10.1) through this exact pipeline falsified even the ranking (headline:
Spearman ρ(−ΔG, pKd) = −0.24, ρ(−ΔG, size) = +0.45, LE ≈ −0.02). Two faults were separated: (a)
`Kd = exp(ΔG/RT)` is invalid for a relative score, but `exp()` is monotonic so fixing it cannot inject
affinity information; (b) the **scoring layer itself** is the primary cause (vdW-dominated,
uncalibrated across pockets), so no downstream transform recovers absent information — a cross-target
"strength band" would be size-in-disguise, and **is not shipped**. The resolution demotes docking to
what it can defend:
- raw ΔG kept only as a labelled **docking-objective diagnostic** (not an affinity, not cross-comparable);
- **no Kd, no Kd-derived occupancy** (both `None`); the uncalibrated value survives only in
  `provenance.vina_pseudo_kd_nM` with a "NOT an affinity" note;
- docking reported as a geometric **`binding_engagement`** class (`experimental-site` … `no-structure` /
  `failed`), with multi-seed sd as reproducibility, not affinity uncertainty;
- the **market model** drops the affinity/occupancy terms, keeping only a capped **+0.05** geometric
  corroboration of a *positive* readout (never rescues a miss; no-call gate holds with no readout);
- estimator IDs bump (`vina-docking-pkpd@2→@3`, `ligand-efficiency-baseline@1→@2`).

**How a *strength* signal could come back (documented, not built).** The limitation is fundamental to
all fast docking scorers (Glide/GOLD/AutoDock4 alike), so swapping the *engine* would not fix it — the
fix is a different *class* of scorer on the reusable pose/routing/covalent infra: **gnina CNN
rescoring** (drop-in on Vina poses, best accuracy-per-effort, but CUDA-only so not runnable in this CPU
sandbox); **MM-GBSA** — built and tested here and it **did not help** (ρ = −0.24, 95% CI [−0.93, +0.62],
no better than Vina, still size-tracking; committed as a reproducible experiment via `make validate`,
[`validation/`](trial-impact-service/validation/README.md), not shipped); and **FEP/TI** (gold standard
but only within a congeneric series, too expensive per pair for a broad pipeline). The `Estimator`
interface exists so a real one slots in when built.

**Status:** ○ open · ◑ mitigated, not fixed · ✅ fixed

### Open — what still needs doing (or is a known inconsistency)

These are the live items: everything the project still needs, ranked. Each is either an unmet
requirement for a real forecast or a place where the current build overreaches its evidence.

| # | Issue | What is needed | |
|---|---|---|---|
| 4-R | **Docking supplies geometry, not affinity — no strength estimator exists** | The re-scope (below) removed the false Kd, but it left a *gap*: there is no validated binding-strength signal at all. Cross-target Vina and CPU MM-GBSA both failed (they track size), so recovering strength needs a different *class* of scorer — gnina CNN rescoring (needs a GPU), explicit-solvent MM-GBSA ensembles, or FEP. Until one lands and is validated, the pipeline's only chemistry claim is geometric engagement | ○ |
| 2 | **Docking box is pocket-routed, with residual caveats** — `select_binding_site` boxes the covalent reactive Cys / curated or discovered co-crystal ligand / fpocket / blind (`docking_box.mode`) | The blind-slab problem is fixed for routed targets, but **cognate/holo redocking is partly circular**, fpocket is geometric-not-biological (its top 6O2P pocket was ~79 Å off the real site), and the **Tier-D blind box still fires** for any target with no co-crystal and no fpocket | ◑ |
| 10 | **Structure choice is resolved live, not pinned point-in-time** — curated classes *name* a holo (KRAS 6OIM, CFTR 6O2P) but fetch it from live PDBe/SIFTS/RCSB at run time | The silent-swap half is fixed (the router commits to the curated structure, records `structure_sha256`, and flags `curated_route_degraded`), but structures are still only *observed*, not pinned. A live point-in-time backtest would need vendored holo files or an immutable `(pdb_id, checksum)` snapshot — otherwise a post-trial co-crystal is look-ahead bias | ◑ |
| 7 | **Sponsor→ticker resolution is a hand-maintained 6-entry file** with hardcoded competitors | Real resolution is **entity resolution** (messy sponsor strings, listed parents, private/pre-IPO sponsors with no ticker and therefore no trade). **The system runs on a watchlist, not a universe** — the scaling claim (and the breadth thesis) is not yet earned | ○ |

> **Note on `cmax_ng_ml` / AUC (folded into #11):** `cmax_ng_ml` is a *tissue* concentration, not
> plasma Cmax, and AUC is AUC(0–48 h), not AUC(0–∞). This is a property of the generic PK model and
> is catalogued under [Limitations](trial-impact-service/README.md#limitations--modeling-caveats).

### Addressed — the work done so far (high-level log)

Each row is a defect found (mostly by auditing the code post-publication) and resolved — the common
thread is the design invariant above.

| # | Was | Resolution | PR | |
|---|---|---|---|---|
| 4 | ΔG consumed as an absolute Kd (and Kd-derived occupancy) | Re-scoped docking to a geometric `binding_engagement` classification: no absolute Kd, no occupancy, no strength band. The market model drops the affinity/occupancy pricing terms (keeps only a capped +0.05 geometric corroboration of a *positive* readout). ΔG is now further **demoted in the UI/docs to a labeled QC/diagnostic** — not an affinity, not comparable across molecules/targets | [#7](https://github.com/noahlin17/trial-impact/pull/7) + this PR | ✅ |
| 1 | Total drug concentration reported as target engagement | Free-drug correction (`C_free = fu·C`, curated `fu` table); the occupancy machinery is retained but dormant for the docking estimator (no real Kd to feed it) | [#3](https://github.com/noahlin17/trial-impact/pull/3) | ✅ |
| 3 | Drug-likeness (Ro5) heuristic priced as a toxicity penalty | Renamed `druglikeness_flag`, unpriced (−0.15 removed); surfaced as informational provenance only | [#6](https://github.com/noahlin17/trial-impact/pull/6) | ✅ |
| 5 / 6 | `simulation.py` embedded in the prompt (30k ceiling); harness and estimator entangled | The session clones a pinned commit; Vina is one implementation behind an `Estimator` interface, so runs are head-to-head-able | [#2](https://github.com/noahlin17/trial-impact/pull/2) | ✅ |
| 8 | Webhook signature verification failed open on an unset secret | Fails **closed** — an unset `WATCHER_SHARED_SECRET` makes `/webhook/trial-update` reject every request (`503`); startup warns loudly | [#6](https://github.com/noahlin17/trial-impact/pull/6) | ✅ |
| 9 | Blind fallback box spanned `ATOM`+`HETATM`, parking on stripped waters/ions | Tier-D box now spans docked `ATOM` records only; pocket-aware tiers unaffected; no published number changed | [#4](https://github.com/noahlin17/trial-impact/pull/4) | ✅ |
| 11 | Single-seed ΔG reported precision it did not have | Multi-seed docking (42, 43, 44) reports mean ± sd; sd feeds a confidence penalty and gates the engagement classification | [#3](https://github.com/noahlin17/trial-impact/pull/3) | ✅ |

Pocket-aware routing, covalent tethering (a reversible-scored lower bound), native mmCIF (gemmi),
the corrected CFTR pin (6O2P, not the mislabelled 9MXL), and **conda-lock** as the canonical sim
environment all landed in [#4](https://github.com/noahlin17/trial-impact/pull/4), dropping #2 from a
blind-slab defect to the routed-with-caveats state above. The residual method caveats (control ≠
validated model, reproducibility ≠ validity, seed sd measures sampling noise only, cognate docking
is circular, covalent ΔG is a reversible lower bound) are catalogued under
[Limitations](trial-impact-service/README.md#limitations--modeling-caveats).

**Fixed earlier, kept on the record:** the AlphaFold fallback URL was stale and *every*
fallback 404'd; Vina ran with `seed=0`, which it reads as *random*, so repeat runs drifted; a
drug-likeness (then `tox_flag`) flag on an `unknown`-outcome trial scored −0.1425, cleared the
0.10 alert threshold and emitted a directional call on chemistry with **no clinical readout** behind it (and `unknown`
is the default for un-enriched trials, so that was the *common* path); PubChem schema drift
silently broke ligand fetching; a covalent SMARTS false-positived on ivacaftor; and
`run_real.py` posted unsigned webhooks that would 401 against the shipped `.env.example`.

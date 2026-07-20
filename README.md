# Trial Impact

**A structure-based engagement pipeline built to test one question: can *cheap, computational chemistry* 
help price a clinical trial's stock-moving readout before it occurs (*and where it can't, say so*).**

## Motivation & (unvalidated) market thesis

A rational sponsor advances a compound only when it clears an internal bar for expected value — informally, 
`P_science · V > C`. In practice sponsors don't compute this as a scalar; the decision is made by checking 
whether the compound clears a set of pre-specified thresholds (a target product profile: minimum-acceptable 
efficacy, safety, PK) combined with qualitative portfolio judgment. But the effect is the same as a threshold rule: 
only compounds whose internal, unobserved likelihood of success is judged "good enough" get funded into a trial. 
So every trial that exists has implicitly cleared some bar `P* := C / V`, even though no one at the sponsor wrote 
that bar down as a number. Call the sponsor's true, never-directly-observed internal belief `P_science` — it's a 
useful fiction for what the threshold-crossing behavior reveals, not a number anyone actually calculated.

Two facts make that exploitable:

1. **The threshold-crossing is not certainty.** Clearing "good enough to fund" leaves real residual uncertainty
   in exactly what the trial exists to resolve — human PK, tolerability, target validity. A funded trial is evidence
   of sponsor confidence, not proof of success.
2. **Neither we nor the market observes `P_science` — both infer from the same disclosed subset of it.** The sponsor's
   true belief draws on internal data (failed formulations, unpublished tox signals, whatever didn't make the IND) that
   never becomes public. What's public is a narrower **disclosed science**: structure, chemistry, registered protocol,
   endpoints, filings. `P_market` is the market's estimate computed from that disclosed set, not from `P_science` itself
   — and so is any `P_you` we'd compute. We are not competing with the sponsor's true belief; we were never able to observe
   it. We're competing with the market, over the same disclosed inputs.

That reframes the question precisely: can we compute something from the disclosed science that the market is not 
currently computing — and therefore not pricing? 

### Reconstructing what the sponsor already knows but didn't disclose. 
By the time a trial is registered, the sponsor holds internal ground truth on the exact question the trial tests — target engagement, 
tolerated exposure — and has likely already run some version of this computation (docking, FEP, MM-GBSA) as part of their 
own diligence; that ground truth is unbeatable. What they disclose, though, is the raw material — structure, SMILES, target, 
protocol — not their derived read on it. The market inherits that gap: it sees the same raw inputs we do, but has no access to 
the sponsor's internal derivative, so it falls back to coarse heuristics (phase × indication base rates, analyst priors, sponsor framing) 
— not from laziness, but because the informative number was never released. If we recompute that missing derivative ourselves from 
public raw inputs, we're not competing with the sponsor — we're closing a disclosure gap the market leaves open, not one it's 
structurally barred from closing.

> The assumption most likely to be fatal is not obviously the chemistry's technical feasibility — it's whether the chemistry,
> if it works, would carry information the market doesn't already have. 

The goal is now to compute `P_you` from disclosed science via granular biophysics, and check whether it is better-calibrated than 
`P_market` over realized outcomes — `E[(P_you − y)²] < E[(P_market − y)²]`. If so, we trade the gap. That is where the money is,
if it is anywhere.

The reason to attempt it now is cost. Structure-based chemistry per trial has historically required a computational chemist. 
An agent sandbox does it per event, in minutes, for roughly the cost of the API calls. 

> That cost argument also cuts against the project. A signal's value tends to decay with the cost of reproducing it, and the cost here
> is low: Vina is free and has been available since 2010, RDKit, the PDB, AlphaFold DB, PubChem and Open Targets are all free.
> If this gap is increasingly easier to close, it is reasonable to assume it will be priced in. So the edge, if there is one, is
> **not purely chemistry**. It would be in producing an **overall better-calibrated estimate of P(success)** than the one implied by
> the market, and trading the difference. The chemistry is one input to that estimate. Incorporating more meaningful signal should
> improve the estimate (especially any signal underused by a meaningful share of the market), but its job is to add incremental information,
> not necessarily to carry the argument.

### The wider view

**A broader and more speculative hypothesis** — an early-stage generalist technology VC's read of AI x biology: 
the outcome *distribution* of drug development is shifting (protein structure prediction, patient selection, 
biomarker stratification, adaptive design) while pricing stays anchored to historical base rates. If AI-enhanced 
trials have genuinely different odds and the market doesn't separate them from conventional ones, that gap is the opportunity 
— and the durable position isn't any single edge but the **infrastructure that keeps producing them as old ones compress**.

## Testing AutoDock Vina and MM-GBSA

Our goal for this project was to investigate whether we could (1) cheaply calculate ΔG, and, if so, 
(2) derive any edge from it. We failed to validate (1), and so never got to test (2) — which is where our 
genuine uncertainty actually was.

We started with ΔG instead because it was computable from public pre-trial data alone — no clinical result 
needed — and because it sits on a real causal path to what Phase 1 measures (does the molecule engage its 
target at a tolerated dose). That made it a legitimate engineering target: buildable end-to-end, testable against 
real affinity data, and honest about its own failure modes. 

> Even a perfect ΔG only bears on the PK/engagement slice of Phase 1 attrition — roughly 10–15% by the standard
> literature breakdown — while efficacy (40–50%) and toxicity (~30%) dominate and are untouched by anything docking
> can do. So the *ceiling* on this signal's value was always modest, even before we knew whether we could compute it
> accurately at all. The test was still worth running: it's cheap enough that even a marginal, exploitable signal could
> have justified it — that's the whole logic of testing the lowest rungs first, low cost makes a low-probability
> payoff worth checking, and a clean negative is itself information.

Given a clinical-trial event, the service routes the drug and its target to the right experimental
structure and binding pocket, docks the ligand (AutoDock Vina) into that pocket, and reports whether
the molecule makes a **reproducible, geometrically sound engagement** (computed from the structure
and the chemistry, not from the sponsor's description of the result). A closed-form PK/PD solve adds
tissue exposure (Cmax/AUC).

The **low-lift** methods here **reproduce binding geometry in the native-holo setting**: redock a native ligand
and the pose usually comes back (5/7 within 2 Å) — though 2/7 fail, one confidently (4GIH, 7.17 Å off at 0.04 Å
seed spread), so this clears only the first of the pose-fidelity control's two pre-registered criteria (see the
Headline results below). **Affinity is governed by the free energy of binding (ΔG)** — and the low-lift methods
were **not** sufficient to get it on the cheap.

We never expected the raw AutoDock Vina score to be a binding free energy (literature is clear it's a fast, 
size-correlated heuristic, not a free-energy method). Vina generates the poses MM-GBSA and the engagement classification 
depend on — it's the natural fallback for targets with no co-crystal to dock against at all (not the case for either anchor 
here, both of which redock into their own known pocket) — and running it gave us hands-on fluency with the toolchain, 
so it earned its place regardless. The core test was whether an **MM-GBSA rescore on top of the Vina pose** could recover 
binding strength. Checked against measured affinities two ways (cross-target and within-target), it **failed to rank measured 
affinity** even where the setup favors it.

> MM-GBSA works on some target classes and not others so whether these systems fell in the working regime was an empirical
> question, not one to assume away. We also aimed the test at MM-GBSA's *most* favorable regime (a congeneric, same-target series),
> so its failure there is a **sharp result rather than an expected one**.

That is a verdict on the *low-lift estimator*, not on affinity itself: recovering affinity cleanly *likely* needs 
materially more compute (such as relative free-energy perturbation — the within-target series we used (Tyk2) is in fact 
a standard FEP benchmark), but that hypothesis is untested here. Real impact needs the geometry result pushed prospectively 
(novel ligands, blind/cross-docking) and paired with heavier affinity methods that would have to earn the claim on the 
same pre-registered terms. 

> **Why FEP isn't the obvious fix:** Having spent that cheap test and come up empty, the next rung — relative free-energy perturbation
> — genuinely would move us toward recovering affinity and within-series ranking. But "recovers the chemistry" is not "helps
> us price." FEP is compute-intensive and expert-tuned, which erodes the breadth/cost that motivates this approach; and it still
> only sharpens binding, so we treat heavier affinity methods as a hypothesis to earn their place on the same pre-registered terms
> — a plausible route to affinity, not a plausible source of edge — not as the solution to our overarching goal.

## Headline results — the low-lift pipeline reproduces binding *geometry* but does not recover binding *strength* on the cheap

I tested the affinity premise on **8 approved drugs with real, measured affinities** (ChEMBL Ki/Kd,
pKd 7.4–10.1), each docked through this exact pipeline, then rescored with a CPU MM-GBSA:

![Head-to-head: neither Vina nor single-snapshot MM-GBSA recovers measured affinity; both track ligand size](trial-impact-service/validation/results/headtohead.png)

| predictor | Spearman ρ vs measured pKd | ρ vs ligand size |
|---|---|---|
| heavy atoms (size baseline) | −0.52 | — |
| Vina −ΔG | **−0.24** | +0.45 |
| MM-GBSA −ΔG | **−0.24** | +0.40 |

- **The raw Vina score does not rank cross-target affinity** — it tracks ligand size (the biggest
  molecules score "best" while being weaker binders).
- **A physics-based MM-GBSA rescore does not rescue it** — same ρ, still size-confounded ([`validation/`](trial-impact-service/validation/README.md), reproduce with `make validate`).

The complementary [pose-fidelity control](trial-impact-service/validation/pose_fidelity/README.md) (native-ligand
self-docking into the native holo pocket: a geometry/tool-reproduction control, not a prospective test)
redocked **5/7 native ligands within 2 Å (71%)**, median top-pose RMSD 0.71 Å. This clears the first of
its two pre-registered criteria (redock success ≥ 60%) but not the second (that multi-seed convergence 
predicts pose correctness). Inter-seed agreement does *not* separate correct from incorrect poses (4GIH is 
a confidently-converged *wrong* pose: 0.04 Å seed spread, yet 7.17 Å off), so the multi-seed spread is a 
reproducibility diagnostic, not a validated confidence signal.

**The discriminating affinity test is the within-target one.** The 8-anchor panel above is the *expected*
regime failure: raw docking scores are not calibrated across different receptors, and here a narrow
affinity range (pKd 7.4–10.1) sits against a wide size range, so size dominates almost by construction
(confirmation of the long-known confound but not a demanding test). The sharper test holds target,
scaffold, and pocket fixed: the regime where structure-based scoring is *supposed* to work. That is the
second [pre-registered control](trial-impact-service/validation/PREREGISTRATION.md), [Experiment A
(congeneric ranking)](trial-impact-service/validation/congeneric/README.md), and it is negative too.
On the 13-ligand Tyk2 series, cheap single-snapshot MM-GBSA gives ρ = −0.54 (95% CI [−0.89, +0.07])
versus measured affinity, failing to beat the size baseline or raw Vina even within-target. The A+C
thresholds were fixed before scores were computed: **two affinity negatives** — one cross-target (expected),
one in-regime (the meaningful one) — and a geometry control that passes only its redock-success
criterion.

**What it *can* claim**: reproducible pocket routing (covalent-tether → co-crystal → fpocket → blind tiers, 
recorded in `docking_box.mode`); directional PK/PD exposure; and an auditable, self-falsifying validation 
of its own scoring.

**What it *cannot* claim**: absolute affinity / Kd; target occupancy; that docking ranks cross-target
potency; or a validated market prediction (the market/stock layer further down is an **illustrative,
un-backtested downstream demo**, not a result). 

> The market/stock layer: a rules-based engine on a small hand-curated watchlist, **not backtested against realized
> price moves**. It exists to show what a validated engagement signal *could* eventually feed. Re-deriving a value
> the market already weights correctly would add nothing — the only useful output is one that beats the market's own
> implied estimate. The tested core of these experiments is the biophysics (in)validation.

---

## How it works

![Pipeline architecture](docs/architecture.png)

A trial event is routed to the right structure and pocket, docked, and classified as *geometric engagement*. 
A PK/PD solve adds exposure. Each estimator runs head-to-head against a size-only baseline it must beat. 
The validation suite tests the affinity premise across two ranking regimes — the bottom-left panel shows the 
cross-target test — and both fail against pre-registered thresholds; a complementary control checks pose geometry 
rather than affinity. The market layer is an illustrative downstream demo.

---

## Demo — the dashboards

Served locally from the two committed result artifacts (`results/sim_*.json`) into the real Flask
app — no re-dock. Both dashboards surface engagement, not affinity — ΔG appears only as a labelled diagnostic.

**`/status`** — one row per trial: the geometric engagement classification, the docking ΔG
(diagnostic), and the (illustrative) price calls.

![Status dashboard](docs/dashboard-status.png)

**`/analysis`** — the corpus view leads with the geometric-engagement chart; the charts are 
engagement-count and PoS, not Kd/occupancy; occupancy is shown only when a calibrated Kd exists
(the docking estimator reports none).

![Analysis dashboard](docs/dashboard-analysis.png)

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
| [`trial-impact-service/`](trial-impact-service/) | The Flask analysis service: trigger → orchestrate (Devin) → reconcile → observe, SQLite read model, market model, alerts, 3D dashboard. |
| [`ctgov-watcher/`](ctgov-watcher/) | A poller that diffs ClinicalTrials.gov v2 and emits signed webhooks (CT.gov has no native webhooks). **Scoped by configuration** — point it at a therapeutic area, a sponsor set, or a single competitive mechanism, and it only fires for that universe. This is what makes the feed targetable rather than a firehose. |

Each has its own README with full detail.

### Why Devin

The simulation is a real pipeline rather than a stub: fetch the target structure
(UniProt → experimental PDB or mmCIF, else AlphaFold), fetch the ligand (PubChem → SMILES →
RDKit 3D), dock with AutoDock Vina across a fixed seed set for a mean ΔG ± sd, then solve a
PK/PD model in closed form (Bateman) for tissue exposure (Cmax/AUC). The reported 
docking ΔG is a labelled diagnostic, not a calibrated affinity; engagement is reported separately 
as a geometric classification derived from pocket-routing tier and pose reproducibility.

The workload is the reason a sandbox is used rather than a fixed container. It has to
`pip install` a heavy and fragile scientific stack (RDKit, Meeko, OpenBabel, Vina), pull
structures from four upstream APIs, and recover when any of them fails — which they do,
in ways that are not predictable in advance. A container would have to anticipate each failure; 
a session can respond to one. That adaptability is what makes per-event chemistry cheap enough 
to run at scale. One isolated session per trial event also keeps runs independently retryable and 
separately auditable.

The tradeoff is that an agent will also fix things it was not asked to fix — including
the science. That is not hypothetical: it has happened twice here, and it is why the
result contract carries a `code_patched` field. See
[the result contract](trial-impact-service/README.md#the-result-contract-and-why-it-has-estimator--code_patched-fields).

### On the label

The met/missed label each estimate sits alongside is today supplied manually via watchlist.json 
(CT.gov has no machine-readable met/missed); an LLM classifier is the intended but unbuilt path ([Next steps](#next-steps)). 
Only the physics half is built. 

---

## Results from two real pipeline runs

Genuine outputs from the committed pipeline (raw JSON + rendered dashboards in
[`results/`](results/)). Docking runs a fixed seed set (42, 43, 44) and reports mean ± sd —
deterministic *given the same resolved structure*, but the structure is fetched live and not pinned,
so the ΔG is not point-in-time reproducible.

| Drug (status) | Target × Drug | Structure (route) | Engagement | ΔG (diagnostic, kcal/mol) | Flags | Model call *(rules-based demo — not a prediction)* |
|-------|---------------|-----------|-----------|---------------|-----|-----------|
| **Approved** (Lumakras, 2021) | KRAS × sotorasib | 6OIM · covalent-tethered (Cys A:12) | experimental-site (reproducible pose) | **−7.202 ± 0.187** | drug-likeness · covalent | AMGN ↑ · REGN/NVS ↓ *(illustrative)* |
| **Approved** (Kalydeco, 2012) | CFTR × ivacaftor | 6O2P · holo-ligand (VX7) | experimental-site (reproducible pose) | −7.404 ± 0.007 | clean | VRTX ↑ · CRSP/BLUE ↓ *(illustrative)* |

Both are **approved** drugs, chosen because the answer is already known — this is a backtest against 
ground truth, not a forecast, and carries no tradeable signal. Read the table as: engagement = the geometric 
product, not strength — the ligand docked into the experimentally-resolved site with a reproducible multi-seed 
pose (sd ≤ 0.75) and no Kd or occupancy are surfaced; ΔG = a docking-objective diagnostic, not affinity; Model call 
= the rules-based placeholder. (PK/PD exposure — Cmax/AUC — is computed per run but shown in the drill-down and 
raw JSON, not this summary table.)

The ΔGs are cognate/holo (partly circular) and the covalent KRAS score is Vina's reversible function 
(a pocket-correct lower bound; `code_patched: false` confirms the numbers came 
from `simulation.py` unpatched). Routing is class-based, not drug-based, so a net-new drug in either class
routes itself the same way.

The **analysis view** (`GET /analysis`,
[`results/analysis_dashboard.html`](results/analysis_dashboard.html)) inspects the whole corpus:
cross-run charts (ΔG diagnostic vs PoS delta, engagement counts), a sortable table, and a per-run
drill-down with the 3D pose, PK/PD exposure curve, and a reasoning trace for each PoS delta.

Raw artifacts: [`sim_kras_sotorasib.json`](results/sim_kras_sotorasib.json) and
[`sim_cftr_ivacaftor.json`](results/sim_cftr_ivacaftor.json), plus the
[`KRAS`](results/dashboard_kras_6OIM.html) and [`CFTR`](results/dashboard_cftr_6O2P.html) status
dashboards. Regenerate with the pinned stack:

```bash
cd trial-impact-service
conda-lock install --name trialsim conda-sim.lock.yml
python regen_artifacts.py
# or a live Devin session: python run_real.py --watch
```

---

## Chemistry & biophysical scope

The physics has a domain of validity, and most of biopharma sits outside it. 

The *binding* half is defensible today for a reversible small molecule against a small globular protein 
with an experimental structure, and — via pocket-aware routing — for covalent small molecules against 
a curated class (a reversible-scored lower bound); everything else degrades to fpocket/blind, and biologics 
are out of scope. The *pharmacology* half is weaker (generic PK, no bioavailability term → order-of-magnitude 
exposure), and occupancy is not reported at all. The surviving claim is *geometric engagement*.

This is what the pipeline models today, what it models badly, and what it cannot touch at all.

**✅ supported · ◑ runs but degrades · ○ out of scope, needs a different method — see row notes.**

### Drug modality

| Modality | | Where it stands |
|---|---|---|
| **Small molecules** (MW ≲ 900, drug-like, PubChem-resolvable) | ✅ | The pipeline is built for these. Both published runs are here. Resolved via PubChem → isomeric SMILES → RDKit ETKDG 3D embed → PDBQT. |
| **Peptides & macrocycles** | ◑ | RDKit will embed them, but Vina's function is parameterized on drug-like ligands and its rigid-ligand sampling erodes as rotatable-bond count climbs (≳10 as a rough rule of thumb). Numbers come back; they mean little. Needs macrocycle-aware sampling. |
| **Biologics** — antibodies, proteins, ADCs, oligos/siRNA, cell & gene therapy | ○ | **Cannot be docked** — no SMILES, and binding is a protein–protein interface, not a ligand in a pocket. Excludes a large fraction of the oncology pipeline; needs a separate affinity path (PPI scoring / co-folding). |
| **PROTACs & molecular glues** | ○ | Require a *ternary* complex (target + ligase + linker). Fundamentally a different modeling problem, not a harder docking run. |

### Target / receptor

| Target class | | Where it stands |
|---|---|---|
| **Single-chain globular soluble proteins** with a legacy-format experimental PDB | ✅ | The good case. With a curated or discovered co-crystal the box is centered on the real bound ligand, not the centroid. |
| **AlphaFold-predicted structures** | ◑ | Used as fallback when no experimental structure resolves; run confidence drops 0.9 → 0.7. A predicted backbone is fine; predicted side-chain rotamers in a pocket are the weak point. A predicted model has no co-crystal ligand, so it can only reach the fpocket/blind tiers. |
| **Large multi-domain or membrane proteins** | ◑ | **Much improved for CFTR.** When a drug-bound co-crystal is curated/discovered (CFTR → 6O2P, ivacaftor's VX7 site) the box is on the actual pocket rather than a central slab. Without one, a large receptor still hits fpocket then the blind box — pocket-aware routing helps only where a co-crystal exists. |
| **mmCIF-only structures** (most large modern cryo-EM) | ✅ | `fetch_structure` falls back to the mmCIF file and converts it with `gemmi` before AlphaFold, so these dock as real experimental structures. (Neither published run now exercises this — both pin a curated `.pdb` holo — but the path stays for mmCIF-only targets.) |
| **Multi-chain complexes, ensembles, flexible side chains** | ○ | One structure, rigid receptor, no ensemble. Vina supports flexible side chains natively (ensembles only via repeated docking into multiple conformations); both change every run's numbers, so they were deferred. |
| **Nucleic-acid targets** (RNA/DNA) | ○ | Vina's empirical scoring function is parameterized for protein–ligand, not nucleic-acid–ligand. |

### Bond & interaction type

| Interaction | | Where it stands |
|---|---|---|
| **Reversible non-covalent binding** — H-bonds, hydrophobic contact, vdW, electrostatics | ✅ | Exactly what Vina's empirical function scores. This is the only interaction class the ΔG is actually valid for. Ivacaftor is the clean case. |
| **Covalent inhibitors** | ◑ | **Tethered to the right pocket, still scored reversibly.** An RDKit SMARTS match catches acrylamide, halo-acetamide, vinyl sulfone, boronic acid/ester and epoxide warheads; when the warhead is a tetherable Michael acceptor **and** the target is a curated covalent class (KRAS G12C, EGFR, BTK), the ligand is Meeko-tethered to the reactive cysteine and docked in a residue-centered box (KRAS/sotorasib). Vina still scores non-covalently — no bond-formation enthalpy — so the ΔG is a pocket-correct **lower bound**, not covalent scoring: proper covalent docking (constraining the ligand to the bonded geometry) needs the AutoDock-GPU covalent workflow, off conda channels, and true reaction energetics need QM/MM. Non-tetherable warheads / non-curated targets fall back to reversible docking with a warning. |
| **Allosteric & cryptic pockets (curated)** | ◑ | A blind box cannot find a cryptic pocket closed in the apo structure — which is exactly why covalent classes pin an *open* drug-bound holo (KRAS's switch-II pocket in 6OIM). Works where the class/structure is curated; an uncurated cryptic pocket still degrades. |
| **Metal coordination** (zinc proteases, metalloenzymes) | ○ | Vina handles metal centers poorly without specific parameterization. A zinc-binding drug's affinity would be badly underestimated. |
| **Halogen bonding, explicit bridging waters** | ○ | Not modeled. The receptor is stripped of waters before docking. |

### Pharmacology

| Assumption | | Where it stands |
|---|---|---|
| **One-compartment Bateman model, closed form** | ◑ | `ka`/`Vd`/`CL` are fixed physiological placeholders and `Kp` is order-of-magnitude, so exposure is **directional, not drug-specific** — it will tell you a 960 mg dose achieves high exposure, not what sotorasib's real Cmax is. No bioavailability term either (`F` = 1), which flatters oral exposure. |
| **Target occupancy** | ○ *(disabled, not absent)* | **No longer reported by the docking estimator.** Occupancy is `C_free/(C_free + Kd)`, which depends entirely on a Kd the Vina score cannot support. The free-drug (`fu`) machinery and its curated table remain in `run_pkpd` for any estimator that *does* supply a real Kd, but the docking path leaves occupancy `None`. Exposure (Cmax, AUC) is Kd-independent and is retained. |
| **Single dose, exposure only** | ○ | No steady-state accumulation; Cmax is the peak of a single-dose curve and AUC is AUC(0–48h), not AUC(0–∞). Most of these drugs are dosed chronically. |
| **Kd from an empirical docking score** | ○ *(withheld, not absent)* | **Removed as a headline.** `Kd = exp(ΔG/RT)` treated Vina's empirical score as a rigorous free energy; the 8-anchor calibration showed the raw score does not rank affinity, so no Kd is surfaced — the uncalibrated value survives only as a labelled `provenance.vina_pseudo_kd_nM`, never priced. |

Genuine per-drug pharmacology needs enrichment overrides (`fu`, `Vd`, `CL` per drug — the
same mechanism as `endpoint_outcome`) or a structure→PK model.

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

The real open work, in order - each stage gates the next. Core caution: calibrating a pricing model on a biased signal just 
launders the bias (see step 2), so honest data comes before clever features, and cheap baselines before more science. 

**1 · Add the signals the chemistry can't see.** Drugs mostly fail because the target is wrong, not because the molecule 
doesn't bind. The cheapest, strongest public signal is human genetics: genetically-supported targets succeed ~2× as often 
(Nelson et al., Nature Genetics 2015), and it's a free Open Targets lookup. Add clinical precedent (has this mechanism been 
drugged before?) and target-tissue expression. More chemistry (FEP, ML scoring) only earns its place if it beats this baseline 
— a hypothesis, not a given.

**2 · Build a historical dataset.** One row per past trial: its features as known at the time, and what actually 
happened. Two things make or break it. Don't use any data published after the trial started (a co-crystal, say), and get outcomes 
from press releases, not just ClinicalTrials.gov (failures are under-reported, so a registry-only dataset looks falsely rosy). 
Keep the failures in.

**3 · Fit a P(success) model.** Combine the features into one P(success), chemistry as just one dimension. The scarce resource 
is labelled trials (hundreds, not millions), so keep the model simple and test it on past data in time order, never shuffled. 
Success = a probability that's well-calibrated and beats a cheap base-rate baseline — not raw accuracy.

**4 · Compare to the market, trade the gap.** Back out the market's own implied odds (from options around the readout, or valuation 
vs risk-adjusted NPV). The edge is the difference between our estimate and the market's, not how confident we are — and it 
pays off through breadth: a small edge across hundreds of under-covered small/mid-cap trials a year beats a big edge on a handful.

> Each phase tests a different unknown with different known inputs, so each gets its own feature set and model. Phase 1 (safety /
> tolerability / MTD / PK) leans on ADMET/tox and exposure; the efficacy signals above (genetics, precedent, expression) are most informative
> about whether a drug will clear the Phase 2/3 efficacy bar — but the goal is still to price that risk before it resolves, consistent
> with the pre-readout thesis, not to treat Phase 2/3 itself as newly in scope.

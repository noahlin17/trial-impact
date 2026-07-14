# Trial Impact

**A new data modality for trial-event investing: run real computational chemistry on
every clinical-trial readout, and get back a number instead of a label.**

When a trial posts results, this spins up an isolated **[Devin](https://devin.ai)**
session that does genuine **protein–ligand docking (AutoDock Vina) + PK/PD** against the
drug and its target, and returns an independent, quantitative estimate of **binding
affinity and implied target engagement** — computed from structure and chemistry, not
from the sponsor's press release.

> **Not investment advice.** Every output is an automated research signal for
> informational purposes only; a disclaimer is attached to each assessment.

---

## The thesis

Every desk watching a readout already gets a **label** — endpoint met or missed. It is public
within minutes, everyone has it, and it is priced almost immediately. It says nothing about
whether the molecule *should* work.

This produces a second, **orthogonal** input for the same event: an independent biophysical
estimate of target engagement, computed from the protein structure and the ligand chemistry
rather than from the sponsor's framing. **A number, not a label.** Numbers can be backtested
against realized outcomes, and can enter a pricing model as their own feature — with errors
plausibly uncorrelated with the market's priors, because they come from physics rather than
sentiment or consensus.

The economics are what make it a *feed* rather than a research project: structure-resolved
chemistry per readout used to mean a computational chemist on staff; an agent sandbox does it
**per event, in minutes, at API cost**, scoped to whatever universe the watcher points at.

### But the physics is not the moat

The same sentence cuts the other way, and it should be said before anyone else says it.
**A signal's value decays with the cost of reproducing it** — and the cost here is near zero.
Vina is free and fifteen years old; RDKit, the PDB, AlphaFold DB, PubChem and Open Targets are
all free; an agent wrote this pipeline in days (this repo's git history says so). If everyone
can compute a ΔG for every trial, **ΔG is in the price.** Docking ahead of a readout is a
commodity and should be assumed to commoditize further.

So the estimator is not the asset. Three things plausibly are: **the labeled, point-in-time
corpus** (models commoditize, data does not — and honest failure labels are hard to build
precisely because the registry under-reports negatives); **the translation to price**; and
**the evaluation harness** — because a new bio-AI model lands every quarter, and the edge
belongs not to whoever *has* one but to whoever can test it against a labeled financial corpus,
point-in-time, in a week.

**That last one is what this repo is trying to be.** The docking is a deliberately commodity
*plugin* — the reference implementation and the control, not the source of edge. The honest
pitch is **not "docking generates alpha" but "here is the infrastructure to find out what
does."** It is also why the reproducibility discipline here is load-bearing rather than fussy:
*a backtest across models whose numbers you cannot attribute is worthless.*

**Where this actually stands.** Both the chemistry and the market model are **placeholders
meant to be refined and replaced.** The docking box does not cover the receptor; occupancy is
computed from total rather than free drug; the market model is uncalibrated and rules-based.
All of it is in [Known issues](#known-issues) rather than glossed. **The claim is not that
these numbers are tradeable, or that docking is an edge** — it is that the modality is real,
the plumbing exists and is reproducible from source, and the resulting quantity is the kind of
thing a better model can be validated and priced against.

And scoring readouts is not the destination — it is the **training set**. The destination is
running the same machinery at *trial registration* to forecast outcomes years ahead. Two things
have to be true first, and neither is today: drugs fail mostly on **target validation**, which
docking cannot see (human genetics is the strongest known public predictor — Open Targets gives
it away free), and the chemistry has to clear a retrospective panel of known winners, **which
this build fails**: it predicts that ivacaftor, an approved and transformative CF drug, does not
engage its target.

📄 **The full argument — the moat, the two axes of failure, the phase decomposition, the
acceptance test, what would make a backtest real, and where the alpha actually is — is in
[THESIS.md](THESIS.md).**

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

The simulation is **real biophysics**, not a stub: fetch the target structure
(UniProt → experimental PDB, else AlphaFold), fetch the ligand (PubChem → SMILES →
RDKit 3D), dock with **AutoDock Vina** for a real ΔG, then solve the PK/PD model in
**closed form** (Bateman) for tissue exposure and target occupancy.

That workload is the reason an agent sandbox is the right substrate rather than a
convenience. It needs to `pip install` a heavy, fragile scientific stack (RDKit, Meeko,
OpenBabel, Vina), pull structures from four different upstream APIs, and **iterate when
any of them fails** — which they do, constantly, and in ways that are not knowable in
advance (see the API-rot section below). A fixed container would have to anticipate every
failure; a session can respond to one. That is precisely the "scientist at the desk"
property, and it is what makes per-event structural chemistry cheap enough to run as a
data feed instead of a research project. One isolated session per trial event keeps runs
independently retryable and separately auditable.

The tradeoff is that an agent will *also* fix things you did not want fixed — including
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

Every number in both rows has been **re-derived from the committed source** — Kd, Cmax,
occupancy and both PoS deltas reproduce to the last digit, so the `code_patched: false`
each run reports is verified rather than self-reported. The numbers came from
`simulation.py` *as committed*, not from a session quietly patching it to get past a
broken upstream API. That field exists because it caught exactly that (see below).

**‡ Two of these columns mean less than they appear to, and the [Known issues](#known-issues)
say so in detail.** Occupancy is computed from **total** drug rather than free drug — there
is no protein-binding correction — so it is an *upper bound*, not target engagement.
Ivacaftor is >99% plasma-protein-bound; corrected, its 94.5% is closer to **~15%**, which
would downgrade the VRTX call from `strong` to `moderate` (issue #1). And the "tox" flag is
really **≥2 Lipinski violations** — a drug-likeness/oral-absorption heuristic, not a
toxicity model. It fires on sotorasib because sotorasib is a big lipophilic oncology
molecule; sotorasib is also an *approved drug* (issue #3).

What the model does do honestly is discriminate on **real, drug-specific chemistry** rather
than on anything hardcoded: sotorasib's flags fall out of its actual computed descriptors
(MW 560.6, logP 5.30) and its acrylamide warhead trips a genuine RDKit substructure match,
while ivacaftor (1 violation, reversible) comes back clean — so the two readouts earn
different probability-of-success deltas. The *inputs* are real; it is the *interpretation*
of two of them that is over-claimed, and I would rather say that than let a chemist find it.

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

**5 · Validate before pricing**
Does the estimate carry information about the outcome, *conditional on what was already
knowable?* Score it against realized outcomes and check its **residual signal over two
baselines** — consensus/the label, and a **genetics-only model**. A feature that merely restates
the readout is worth nothing however scientific it looks, and a physics model that cannot beat a
free Open Targets score is not worth running. With ~90 % base-rate attrition, "predict failure"
is itself a strong naive baseline that must be cleared.

**6 · Then price it**
Recover the market's **implied** probability of success — from options around the catalyst, or by
decomposing market cap against a risk-adjusted NPV — because the edge is
`our P(success) − implied P(success)`, not the level of our own call. Trade the divergence. Scope
the universe to where the trial is **material to enterprise value** (SMID-cap, single/lead-asset
biotech); a Phase 1 asset is noise inside a large-cap market cap. This needs real
**sponsor→ticker entity resolution** first (issue #7). Then either productionize an analyst's
existing process with this as a new input, or fit a quantitative model on the corpus.

**Harden & ship**
Retries/timeouts on `blocked` or hung sessions; CI (GitHub Actions: ruff + pytest) plus a nightly
**live-API smoke test** — the only thing that would have caught six months of upstream API rot;
Postgres instead of SQLite; a deployed service + watcher on a scheduled `/poll`.

---

## Known issues

Open defects, ranked. These are things that are **wrong**, not merely simplified — the
modelling simplifications are catalogued separately under
[Limitations](trial-impact-service/README.md#limitations--modeling-caveats), which also carries
the full detail and proposed fix for every row below. The domain of validity is in
[Chemistry & biophysical scope](#chemistry--biophysical-scope).

I found most of these by auditing my own code *after* the runs were published. There is a
pattern in the top four, and it is the real lesson of the project: **each one is a place where
a defensible local choice gets silently promoted into a stronger claim downstream.** A relative
score becomes an absolute Kd. A drug-likeness heuristic becomes a toxicity penalty. A total
concentration becomes target engagement. A tractable box becomes "the whole receptor." Nothing
crashes and no test fails — the claim just quietly inflates as it moves down the pipeline. In a
scientific pipeline, the dangerous failures are not the ones that throw.

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

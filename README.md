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

Every desk watching a readout already gets a **label**: endpoint met or missed, positive
or negative, however it is classified. That label is public within minutes, everyone has
it, and it is priced almost immediately. It carries no independent view of whether the
molecule *should* work.

This produces a second, **orthogonal** input for the same event: an independent
biophysical estimate of whether the drug engages its target, derived from the protein
structure and the ligand chemistry. For each readout you get, *alongside* the
classification, a **ΔG / Kd and a PK/PD-implied efficacy estimate** — a continuous
quantity that can be:

- **backtested** against realized outcomes and realized price moves, which a label cannot
  be scored against in the same way;
- fed into a pricing model as **its own feature**, one whose errors are uncorrelated with
  the market's priors because it is computed from physics rather than from sentiment,
  consensus, or the sponsor's framing;
- accumulated into a **corpus**, so that with enough history the same signal supports
  systematic strategies rather than one-off fundamental calls.

The economics are the enabling part. Running structure-resolved chemistry per readout has
historically meant a computational chemist on staff. An agent sandbox does it **per event,
in minutes, at API cost** — with the customizability of a real scientist at your desk,
scoped to whatever universe you point the watcher at (a therapeutic area, a sponsor set, a
single competitive mechanism). That changes it from a research project into a **data feed**.

**Where this actually stands.** Both halves of the pipeline — the chemistry and the market
model — are real work, and both need substantially more sophistication and research
refinement before this generates true alpha. The docking is blind and coarse; occupancy is
computed from total rather than free drug; the market model is uncalibrated, rules-based,
and not weighted by phase. These are documented in detail under
[Known issues](#known-issues) and [Chemistry & biophysical scope](#chemistry--biophysical-scope)
rather than glossed. **The claim here is not that the current numbers are tradeable.** The
claim is that the *modality* is real, that the plumbing to produce it per event exists and
is reproducible from source, and that the resulting quantity is the kind of thing that can
be validated, calibrated, and priced.

The market model in this repo is deliberately a **transparent, rules-based placeholder** —
a glass box that shows how a physics estimate would flow into a directional view, not a
serious pricing engine. The intended path is to run it long enough to build the corpus,
then either **work with analysts to productionize their existing pricing and evaluation
process** using this as a new input, or **use the accumulated data to fit a quantitative
model outright** on a scientific dimension the market is not currently pricing.

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
- Pocket-aware docking instead of a blind box — the **highest-value fix on this list**,
  and the one that closes [issue #2](#known-issues). Two approaches have now failed for
  the same underlying reason. Centering on the largest co-crystal ligand boxed the
  **wrong pocket** (KRAS 7VVB carries only the nucleotide GNP, not sotorasib); that was
  tried and reverted. The blind box that replaced it doesn't box the wrong pocket so much
  as fail to box *anything* — capped at 40 Å on the centroid, it covers 80% of KRAS but
  only 19% of CFTR. Both return a plausible ΔG regardless, which is what makes them
  dangerous. The real fix is cavity detection (fpocket / P2Rank) or a drug-bound
  structure pinned per trial — not a heuristic over HETATM records, and not a bigger box.
- Native **mmCIF** support in `fetch_structure` (gemmi), so large cryo-EM structures
  like CFTR's 9MXL stop falling back to a predicted model. Then MM-GBSA rescoring, and
  a separate affinity path for biologics (antibodies can't dock). Pin the sim
  environment (conda-lock); Vina's seed is already pinned, so ΔG now reproduces.

**Turn the signal into a priced feature** *(this is the path to alpha, and it is
sequenced deliberately — none of it is worth doing until the science above is sound,
because calibrating a model on a biased signal just launders the bias)*

1. **Close the label loop.** Auto-derive `endpoint_outcome` (met/missed) from the CT.gov
   results section and sponsor press releases with an **LLM classifier**, instead of
   watchlist enrichment. Until this exists, the corpus cannot grow without a human in it,
   which is the binding constraint on everything below.
2. **Build the corpus.** Run the watcher, scoped to a universe, and accumulate
   `(structure, chemistry, ΔG, Kd, occupancy, phase, outcome, realized price move)` per
   readout. Backfill it over historical readouts — the physics is computable retroactively
   for any past trial whose drug and target are known, so **the corpus does not have to be
   accumulated in real time**, which is what makes a backtest feasible at all.
3. **Validate the feature before pricing it.** Ask the only question that matters first:
   *does the physics estimate carry information about the outcome, conditional on what the
   market already knew?* Score ΔG/occupancy against realized outcomes and next-day moves,
   and check its **residual correlation against the label and against consensus** — a
   feature that merely restates the readout is worth nothing, however scientific it looks.
4. **Then price it.** Two paths, and they are not exclusive: work with analysts to
   **productionize their existing pricing and evaluation process** with this as a new
   input, or fit a **quantitative model outright** on the accumulated corpus. Wire live
   quotes and market cap (no market-data client exists yet), and weight the
   probability-of-success delta by trial **phase** (Phase 1 ≪ Phase 3) and by the
   sponsor's exposure to the asset.

The rules-based market model in this repo is a **glass-box placeholder** for step 4 — it
exists to show the shape of the pipeline end to end, not to be traded. Replacing it is the
point, not a concession.

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

## Known issues

Open defects, stated plainly. These are things that are **wrong**, not merely
simplified — the modeling simplifications are separately catalogued under
[Limitations](trial-impact-service/README.md#limitations--modeling-caveats), and the
domain of validity is in [Chemistry & biophysical scope](#chemistry--biophysical-scope)
above. I found #1–#3 by auditing my own code after the runs were already published.

There is a pattern in the first four, and it is worth naming: **each one is a place where a
defensible local choice gets silently promoted into a stronger claim downstream.** A
relative score becomes an absolute Kd. A drug-likeness heuristic becomes a toxicity
penalty. A total concentration becomes target engagement. Nothing crashes — the numbers
just quietly mean less than they claim to. That is the failure mode this project is
actually about.

**1 · Target occupancy is computed from *total* drug, not *free* drug.** `_pkpd_series`
evaluates `occ = C / (C + Kd)` using the total tissue concentration. Only **unbound** drug
can engage a target — the free-drug hypothesis is the basis on which occupancy is
calculated — and there is no fraction-unbound (`fu`) term anywhere in the pipeline.
Ivacaftor is **>99% plasma-protein-bound**, so correcting it:

| Run | Published occupancy | Corrected for protein binding |
|---|---|---|
| KRAS × sotorasib (fu ≈ 0.11) | 97.6% | **~81%** |
| CFTR × ivacaftor (fu ≈ 0.01) | 94.5% | **~15%** |

This is **load-bearing on a published result**, not a footnote. Occupancy feeds the market
model, and at ~15% ivacaftor crosses the `occ < 30` branch: its **+0.15 "high engagement"
bonus becomes a −0.10 penalty**, the PoS delta falls 0.552 → 0.340, and the **VRTX call
downgrades from `strong` to `moderate`**.
**Read every reported occupancy as a total-drug upper bound**, not as target engagement.
*Fix:* an `fu` term supplied per drug via enrichment (the same mechanism as
`endpoint_outcome`), defaulting to 1.0. *Why not yet:* it changes occupancy, PoS and the
market call for both published runs, so both artifacts would have to be re-run to keep
`code_patched: false` meaningful. Documented rather than quietly patched.

**2 · The blind docking box does not cover the receptor.** `compute_docking_box` sizes
the box `min(extent + 8 Å, 40 Å)` but keeps it centered on the centroid. The 40 Å cap is
binding in *both* published runs — both artifacts record `size: [40, 40, 40]` — so the
box is a central slab, not the protein. Measured coverage: **KRAS 7VVB 80%**, **CFTR
AF-P13569-F1 19%**. CFTR's ΔG is therefore not a pocket-resolved affinity and should not
be read as one. Reproduce with `python verify_docking_box.py`.
*Fix:* pocket detection (fpocket / P2Rank), or pin a drug-bound structure per trial.
*Why not yet:* removing the cap makes the search volume intractable for Vina and would
not find the pocket either — "cover the receptor" is not the fix, "find the pocket" is,
and that is a real piece of work rather than a one-line change. Docked and flagged beats
silently wrong, so the code now logs a warning when the cap binds, and a
characterization test pins the behaviour so a future fix has to be deliberate.

**3 · `tox_flag` is a drug-likeness heuristic priced as a safety signal.** It is defined as
**≥2 Lipinski Rule-of-5 violations** (`mw>500, logp>5, hbd>5, hba>10`). The Rule of 5
predicts **oral absorption and permeability** — it is not, and was never intended as, a
toxicity model. Sotorasib trips it on MW 560.6 + logP 5.30, and **sotorasib is an approved,
orally dosed drug**: the flag fires on it precisely *because* it is a large lipophilic
oncology molecule, which is the norm in that class. The market model then charges it
**−0.15 PoS as though it were a safety finding**. The descriptor arithmetic is right; the
interpretation is wrong. *Fix:* rename it to what it is (`drug_likeness_flag`) and either
drop the penalty or replace it with a real structural-alert model (PAINS / Brenk / a
tox QSAR). *Why not yet:* it changes the schema and both published PoS deltas.

**4 · ΔG is documented as a *relative* signal but consumed as an *absolute* one.** The
service README says, correctly, that Vina is an empirical scoring function and its ΔG is
"a relative signal, not a measured affinity." The code then converts that score to an
absolute `Kd = exp(ΔG/RT)`, feeds the Kd into an absolute occupancy calculation, and
branches on **hard absolute thresholds** (`Kd ≤ 100 nM → potent`, `ΔG ≤ −9.0`). Both
positions cannot be true. Related: the conversion uses **T = 310.15 K** (body temperature)
while Vina's scoring function is calibrated against affinities conventionally reported at
**298.15 K**, which makes every Kd systematically **~1.75× looser** — defensible as a
physiological choice, but undocumented until now, and it interacts directly with that
`Kd ≤ 100 nM` threshold. *Fix:* either treat ΔG strictly ordinally (rank/percentile
against a reference set, no absolute cutoffs), or calibrate the score against known
binders for the target and own the absolute claim. The first is honest and cheap; the
second is the real answer.

**5 · The box is computed over atoms that are not docked.** The box spans `ATOM` +
`HETATM` records, while `prepare_receptor_pdbqt` strips waters and heteroatoms and docks
`ATOM` only. So the box is centered on a slightly different atom set than the one Vina
searches — visible in the KRAS artifact as a stored center of `-19.192, 40.956, -3.009`
against an ATOM-only centroid of `-19.17, 40.88, -2.90`. Small in practice, wrong in
principle. *Not fixed:* correcting it moves the box, which changes ΔG, which would
invalidate both published artifacts and the `code_patched: false` claim that rests on
them reproducing from source. It gets fixed together with #2, in one re-run.

**6 · Webhook signature verification fails open.** `signature_required` is
`bool(WATCHER_SHARED_SECRET)`, so an unset secret silently accepts *any* caller's trial
event — each of which spends a Devin session. The default is deliberate (the demos post
unsigned), but it was silent. *Partially fixed:* the app now logs a loud warning at
startup when verification is disabled. It still fails open; a production deployment
should make the secret mandatory.

**7 · Structure choice is not pinned.** The target structure is whatever PDBe/SIFTS
`best_structures` ranks first *at run time*. That ranking shifts as new structures are
deposited, so a future re-run could dock a **different structure** and return a different
ΔG. Not observed so far (KRAS has consistently resolved to 7VVB), but the recorded runs
are not reproducible *by construction*. *Fix:* pin the resolved `pdb_id` per trial.

**8 · `simulation.py` is embedded in the Devin prompt, and the prompt is full.**
The source ships inside the 30,000-character prompt and currently uses **29,950 of it —
50 characters spare**. It has hit the ceiling three times in one session; a test guards it,
so this fails loudly rather than silently, but the budget is now tight enough that *the
code can no longer afford a comment*. The fix is to stop embedding the source and have the
session clone a **pinned commit**, which also makes "which code produced this number?"
answerable by construction and retires the `code_patched` self-report in favour of
something verifiable. **This is the next thing I would build.**

**9 · Reported precision exceeds real precision.** A single pinned Vina seed reports one
draw from a stochastic optimiser to three decimals (`−8.606`), when the pre-pin spread was
0.19 kcal/mol — a ~36% swing in Kd. `cmax_ng_ml` is also a **tissue** concentration
(`Kp`-scaled), not the plasma Cmax the name implies, and AUC is AUC(0–48h), not
AUC(0–∞). *Fix:* run N replicates with derived seeds and report mean ± sd, feeding the sd
into `confidence` (which already scales the PoS delta, so physics uncertainty would
propagate into the market call); and rename the exposure fields to say which compartment
they describe.

**Fixed this round, kept on the record:** the AlphaFold fallback was pinned to a stale
URL version and every fallback 404'd; Vina ran with `seed=0`, which it reads as *random*,
so repeat runs drifted; a tox flag on an `unknown`-outcome trial scored −0.1425, cleared
the 0.10 alert threshold, and emitted a directional call on chemistry with no clinical
readout behind it (and `unknown` is the default for un-enriched trials, so that was the
common path, not an edge case); PubChem's schema drift silently broke ligand fetching;
and a covalent SMARTS pattern false-positived on ivacaftor's aromatic ring.

## Honest caveats

The full list of modeling caveats, with a fix verdict on each, is in
[`trial-impact-service/README.md`](trial-impact-service/README.md#limitations--modeling-caveats).
The ones that most change how you should read the numbers:

- **Docking is blind, and on large targets it is worse than blind** — see issue #2. ΔG is
  a coarse, *relative* signal, not a measured affinity, and for CFTR it is not even that.
- **The 3D viewer shows the receptor the run docked against** (with its own crystal
  ligand), **not** Vina's docked pose — the pose is not returned. See Next steps.
- **Covalent binders are flagged but still scored reversibly**, so their potency is
  understated (sotorasib is the clearest case).
- **CFTR resolves to a predicted structure**, not the cryo-EM one: `fetch_structure`
  cannot read mmCIF. Confidence drops to 0.7 accordingly.
- **Occupancy is a total-drug upper bound, not target engagement** — there is no
  protein-binding correction, and for a >99%-bound drug like ivacaftor that is the
  difference between 94.5% and ~15%. See issue #1.
- **The "tox" flag is a Lipinski drug-likeness heuristic, not a toxicity model**, and it is
  priced as a −0.15 safety penalty anyway. It fires on sotorasib, an approved drug. Issue #3.
- **Generic PK constants.** `ka`/`Vd`/`CL` are fixed physiological placeholders, `Kp`
  is order-of-magnitude, and there is no bioavailability term, so exposure/occupancy are
  directional, not drug-specific.
- `endpoint_outcome` (met/missed) is not machine-readable from ClinicalTrials.gov;
  the watcher supplies it via per-trial enrichment (`watchlist.json`) for now.
- The market model is deliberately transparent/rules-based (not a black box) and is
  **not** calibrated to real market data, and it does **not weight by trial phase** —
  it's a research signal, not a trade.

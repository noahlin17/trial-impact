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
| Phase 3 | CFTR × ivacaftor | AF-P13569 (AlphaFold) | −8.702 † | 738 nM | 94.5% | clean | ▲ VRTX strong · ▼ CRSP/BLUE |

Every number in both rows has been **re-derived from the committed source** — Kd, Cmax,
occupancy and both PoS deltas reproduce to the last digit, so the `code_patched: false`
each run reports is verified rather than self-reported. The numbers came from
`simulation.py` *as committed*, not from a session quietly patching it to get past a
broken upstream API. That field exists because it caught exactly that (see below).

The model also discriminates on real chemistry: sotorasib's tox flag falls out of its
actual descriptors (MW 560 + logP 5.3 = 2 Lipinski violations) and its acrylamide
warhead trips the covalent flag; ivacaftor (1 violation, reversible) is clean — so the
two readouts earn different probability-of-success deltas.

> **† The CFTR ΔG is not a pocket-resolved affinity, and should not be read as one.**
> The docking box is centroid-centered and capped at 40 Å. CFTR is a 1480-residue
> membrane protein measuring 139 × 117 × 147 Å, so that box holds **19% of the
> receptor's atoms** — and ivacaftor binds at the TM1/TM6 interface, not the centroid.
> The run is a real, reproducible execution of the pipeline, but the ΔG is a dock into
> an arbitrary central slab. KRAS (56 × 55 × 44 Å) fares far better at **80% coverage**,
> which is why it is the headline result. Reproduce both numbers with
> `python verify_docking_box.py`. This is **[open issue #1](#known-issues)** — I found
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
| **Large multi-domain or membrane proteins** | ◑ | **This is where CFTR fails.** The 40 Å box cap means we dock a central slab, not the pocket (19% atom coverage). Runs to completion and returns a plausible number, which is what makes it dangerous. Needs pocket detection (fpocket / P2Rank) or a drug-bound structure pinned per trial — [issue #1](#known-issues). |
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

Exposure and occupancy come from a **one-compartment Bateman model solved in closed
form**, with `ka`/`Vd`/`CL` set to fixed physiological placeholders and `Kp` accurate
only to an order of magnitude. Occupancy then follows a simple `C/(C + Kd)` Hill
relation. These are ◑ **directional, not drug-specific** — they will tell you that a
960 mg dose achieves high target engagement, not what sotorasib's real Cmax is. Genuine
per-drug PK needs enrichment overrides or a structure→PK model.

**The practical upshot:** the pipeline is trustworthy today for a *reversible,
non-covalent small molecule against a small globular protein with an experimental
structure*. Everything else either degrades quietly (covalent, membrane proteins,
predicted structures) or is out of scope entirely (biologics). Both published runs sit
partly outside that box — sotorasib is covalent, CFTR is a membrane protein — and the
sections below are about how I found that out rather than assumed otherwise.

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
  and the one that closes [issue #1](#known-issues). Two approaches have now failed for
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

## Known issues

Open defects, stated plainly. These are things that are **wrong**, not merely
simplified — the modeling simplifications are separately catalogued under
[Limitations](trial-impact-service/README.md#limitations--modeling-caveats), and the
domain of validity is in [Chemistry & biophysical scope](#chemistry--biophysical-scope)
above. I found #1–#3 by auditing my own code after the runs were already published.

**1 · The blind docking box does not cover the receptor.** `compute_docking_box` sizes
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

**2 · The box is computed over atoms that are not docked.** The box spans `ATOM` +
`HETATM` records, while `prepare_receptor_pdbqt` strips waters and heteroatoms and docks
`ATOM` only. So the box is centered on a slightly different atom set than the one Vina
searches — visible in the KRAS artifact as a stored center of `-19.192, 40.956, -3.009`
against an ATOM-only centroid of `-19.17, 40.88, -2.90`. Small in practice, wrong in
principle. *Not fixed:* correcting it moves the box, which changes ΔG, which would
invalidate both published artifacts and the `code_patched: false` claim that rests on
them reproducing from source. It gets fixed together with #1, in one re-run.

**3 · Webhook signature verification fails open.** `signature_required` is
`bool(WATCHER_SHARED_SECRET)`, so an unset secret silently accepts *any* caller's trial
event — each of which spends a Devin session. The default is deliberate (the demos post
unsigned), but it was silent. *Partially fixed:* the app now logs a loud warning at
startup when verification is disabled. It still fails open; a production deployment
should make the secret mandatory.

**4 · Structure choice is not pinned.** The target structure is whatever PDBe/SIFTS
`best_structures` ranks first *at run time*. That ranking shifts as new structures are
deposited, so a future re-run could dock a **different structure** and return a different
ΔG. Not observed so far (KRAS has consistently resolved to 7VVB), but the recorded runs
are not reproducible *by construction*. *Fix:* pin the resolved `pdb_id` per trial.

**5 · `simulation.py` is embedded in the Devin prompt, and the prompt is nearly full.**
The source ships inside the 30,000-character prompt and currently uses ~29.9k of it. A
test guards the ceiling, so this fails loudly rather than silently — but the real fix is
to stop embedding the source and have the session clone a **pinned commit**, which also
makes "which code produced this number?" answerable by construction and retires the
`code_patched` self-report in favour of something verifiable.

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

- **Docking is blind, and on large targets it is worse than blind** — see issue #1. ΔG is
  a coarse, *relative* signal, not a measured affinity, and for CFTR it is not even that.
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

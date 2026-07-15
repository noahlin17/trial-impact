# Results

Artifacts from two runs of the committed pipeline. **Read these as a demonstration of what the
chemistry pipeline *does*, not as measured quantities.**

**What the chemistry can actually do** — route a target + ligand to an experimentally-resolved
pocket, dock it (AutoDock Vina, **three seeds**, mean ± sd) into that **pocket-routed** box, classify
the result as **geometric engagement**, and solve a directional PK/PD exposure (Cmax/AUC).

**What it reads out** — a geometric `binding_engagement` label (did the ligand dock into the
experimentally-resolved site with a *reproducible* multi-seed pose), a docking-objective ΔG that is a
**QC/diagnostic only** (not an affinity, not comparable across molecules or targets —
[issue #4](../README.md#known-issues)), and exposure. No Kd, no occupancy, no binding-strength
number.

**Why it breaks moving forward, and why the ΔG carries no real provenance** — the ΔG magnitudes
below are **not measurements you can trust or trace**: (1) they depend on whichever structure the
router resolves from **live** PDBe/RCSB at run time (not pinned point-in-time —
[issue #10](../README.md#known-issues)), so they are not point-in-time reproducible; and (2) even a
stable number is not an affinity — cross-target Vina and CPU MM-GBSA both failed to rank affinity
(they track ligand size), the covalent KRAS score is a reversible lower bound, and both rows are
cognate (self-pocket) docking. So the ΔG is an illustrative pipeline output, not a provenance-grade
result.

The `.json` files are the exact records the service stored; open the `.html` files in a browser for
the interactive 3D structure, the PK/PD curve, and the price calls.

The one thing that *is* verifiable is **integrity, not meaning**: every run reports
**`code_patched: false`**, meaning the numbers came from `app/simulation.py` *as committed* — the run
did not edit the script to make it work. (See "The result contract" in the service README for why
that field exists and what it caught.)

> **How these were regenerated.** They were produced by running the committed pipeline directly
> against the pinned **conda-lock** sim stack (`conda-sim.lock.yml`, via `regen_artifacts.py`), not in
> a hosted Devin session, so `devin_session_id` reads `local-pinned-stack-regen`. Given the *same*
> resolved structures the run is deterministic and reproduces; but because structures are fetched
> live and not pinned (issue #10), a different environment can resolve a different structure and
> return a materially different ΔG — so "reproducible" here means *from the committed code given the
> same inputs*, not that the ΔG is a stable measurement. Reproduce with `python regen_artifacts.py`
> (or `run_real.py` for a live session).

> **Toolchain note (why ΔG shifted from earlier figures).** Two things moved the absolute
> ΔG relative to the PR #3 numbers. (1) **The box is now routed to the pocket**, not a
> blind central slab — KRAS is tethered to the switch-II Cys of 6OIM, CFTR is boxed on the
> co-crystal ivacaftor (VX7) in 6O2P — so these are pocket-correct scores, weaker in
> absolute value but meaningful. (2) The canonical stack is now the conda lock: RDKit
> `2024.03.5 → 2025.09.5` and Vina `1.2.5 → 1.2.7` (they share libboost 1.86; the old
> RDKit needed 1.84 and could not co-resolve with Vina 1.2.7), Meeko `0.6.0 → 0.7.1`
> (0.6.0 was withdrawn from PyPI). This is expected toolchain + methodology drift, not a
> code patch — `code_patched` is `false`.

> **Estimator attribution.** These are the default docking pipeline, `vina-docking-pkpd@3`
> (bumped from `@2` because #4 changed the result semantics — no Kd, no Kd-derived occupancy,
> a new `binding_engagement` classification; stamped onto every result). The head-to-head
> against the `ligand-efficiency-baseline@2` **control** is not shown here — the baseline is a
> naive floor to beat, not a second opinion, and running it does not re-validate these numbers.
> See "Estimators" in the service README.

| File | Trial | Result |
|------|-------|--------|
| `sim_kras_sotorasib.json` | KRAS × sotorasib — Amgen, **Phase 1 (forward-looking scope)**, endpoint met | ΔG **−7.202 ± 0.187** kcal/mol (n=3) — a *docking-objective diagnostic, not a Kd* ‡ — engagement **experimental-site** (reproducible pose), drug-likeness flagged (informational, not priced), **covalent** (acrylamide warhead). Route **covalent-tethered** to Cys A:12 of curated holo **6OIM** (confidence 0.806). PoS **+0.50** → AMGN up/strong · REGN, NVS down/moderate. |
| `sim_cftr_ivacaftor.json` | CFTR × ivacaftor — Vertex, **Phase 3 (retrospective, known readout)**, endpoint met | ΔG −7.404 ± 0.007 kcal/mol † (n=3) — a *docking-objective diagnostic, not a Kd* ‡ — engagement **experimental-site** (reproducible pose), clean, not covalent. Route **holo-ligand** boxed on co-crystal **VX7** in curated **6O2P** (confidence 0.897). PoS **+0.52** → VRTX up/strong · CRSP, BLUE down. A **retrospective re-simulation**: ivacaftor already cleared Phase 1 and its outcome is public, so re-running the fixed chemistry benchmarks the pipeline against a known readout — it is **outside the forward-looking preclinical / Phase 1 scope** (see root README). |
| `dashboard_kras_6OIM.html` | ″ | Rendered `/status` with the 3D viewer; docking ΔG shown as mean ± sd. |
| `dashboard_cftr_6O2P.html` | ″ | Rendered `/status`; the 6O2P cryo-EM structure rendered from RCSB. |
| `analysis_dashboard.html` | both | Rendered `/analysis`: physics→price scatter, an estimator head-to-head (empty here — single-estimator corpus), sortable table (ΔG columns carry ± sd), and a per-run drill-down (3D structure + PK/PD curve + PoS reasoning waterfall). Open it and click a row. |

Each JSON holds the trial event, the resolved sponsor/competitor tickers, the full
`sim_result` (docking ΔG with per-seed replicates and sd, the geometric `binding_engagement`
classification, exposure, druglikeness/covalent flags, **docking box with routing `mode` +
provenance**, provenance: UniProt / PDB id / **structure format** / SMILES / descriptors /
**vina seeds** / a clearly-labelled uncalibrated `vina_pseudo_kd_nM`), and the market model's
`price_calls` + `commentary`. `kd_nM` and `target_occupancy_pct` are `null` (issue #4).

## The docking box is now routed to the pocket

`app/binding_site.select_binding_site` classifies each run and boxes it accordingly,
recording the tier in `docking_box.mode`:

| Tier | `mode` | Box from | Which run |
|---|---|---|---|
| 1 | `covalent-tethered (curated holo)` | reactive Cys of a curated covalent class | **KRAS** (Cys A:12, 6OIM) |
| 2 | `holo-ligand (curated)` | curated drug-bound co-crystal ligand | **CFTR** (VX7, 6O2P) |
| 3 | `holo-ligand (discovered)` | RCSB graph-relaxed chemical-search hit | — |
| 4 | `fpocket` | top geometric pocket | — |
| 5 | `blind` | legacy centroid box (last resort) | — |

This replaces the old blind, centroid-centered, 40 Å-capped slab (which held only ~26% of
CFTR). **Remaining caveats, documented not fixed:** cognate/holo redocking is partly
circular (redocking a drug into its own bound pocket inflates apparent accuracy); fpocket
is geometric, not biological (on 6O2P its top pocket sat ~79 Å from the real ivacaftor
site — which is exactly why it is a low-priority *fallback*); and the Tier-D blind box
still fires for any target with no co-crystal and no fpocket. This is
[issue #2](../README.md#known-issues).

## Docking is three seeds, reported as mean ± sd

`run_vina` docks across a **deterministic seed set** (42, 43, 44) and the result carries
`binding_affinity_kcal_mol` (mean ΔG), `binding_affinity_sd_kcal_mol` (sample sd), and
`replicates` (n). No absolute Kd is derived from the ΔG any more (issue #4); the sd feeds a
small confidence penalty **and** gates the engagement classification — an experimentally-resolved
site with sd ≤ 0.75 kcal/mol is `experimental-site` (a *reproducible* pose), a larger spread is
`experimental-site-noisy`. This retires the old "reported precision exceeds real precision" gap:
a single draw hid the seed-to-seed spread. The spread here is small (0.187 / 0.007 kcal/mol) — but
that measures **sampling/reproducibility noise only**, not model bias, box placement, or
scoring-function error, which dominate and are not captured by re-seeding. Cost scales linearly
with seed count (3× the docking time).

## ‡ How to read the ΔG / engagement and drug-likeness columns

**The ΔG is a docking-objective *diagnostic*, not an affinity — it is not comparable across
molecules or targets, and no Kd or occupancy is derived from it.** An 8-anchor calibration through
this exact pipeline ([issue #4](../README.md#known-issues)) showed the raw Vina score does not rank
measured affinity (r(−ΔG, affinity) ≈ −0.4) and instead tracks ligand size/contact area (r(−ΔG,
heavy-atoms) ≈ +0.6). So the docking result is demoted to a **geometric `binding_engagement`** claim: `experimental-site` means the ligand docked into an
*experimentally-resolved* site (a curated holo / covalent-tethered residue) with a *reproducible*
multi-seed pose (sd ≤ 0.75). Both runs above are `experimental-site`. `kd_nM` and
`target_occupancy_pct` are `null`; the uncalibrated `exp(ΔG/RT)` value survives only as a
clearly-labelled `provenance.vina_pseudo_kd_nM` (never priced). Exposure (Cmax, AUC) is
Kd-independent and is retained.

The **market model** prices only a small, capped (+0.05) geometric corroboration for an
`experimental-site` engagement, and only on a *positive* clinical readout — it never prices ΔG/Kd
magnitude or occupancy, and engagement can never rescue a missed endpoint or manufacture a call
when there is no readout. The free-drug (`fu`) occupancy machinery remains in `run_pkpd` for any
future estimator that supplies a real Kd, but the docking path leaves occupancy `None`.

**The `druglikeness_flag` is a Lipinski drug-likeness heuristic, not a toxicity model, and is
no longer priced** — ≥2 Ro5 violations, which predicts oral absorption, not safety. It fires on
sotorasib because sotorasib is a big lipophilic oncology molecule; sotorasib is also an approved
drug — so charging it as a safety event was a category error. The −0.15 penalty is **removed**;
the flag (renamed from `tox_flag`) is surfaced as informational provenance only and contributes
`0.0` to the PoS delta. This is [issue #3](../README.md#known-issues), **fixed**.

## † How to read the two ΔGs (pocket-resolved, but cognate and reversible-scored)

Both runs now box the **real pocket**, which is the fix for the old blind-slab problem. But
neither ΔG is an absolute affinity, for two reasons:

- **Cognate/holo docking is partly circular.** Redocking a drug into its own bound pocket
  (the switch-II site of 6OIM for sotorasib, the VX7 site of 6O2P for ivacaftor) inflates
  apparent accuracy — the box is correct *because* the structure already contains the
  answer. It is not an independent prediction of where the drug binds.
- **The covalent KRAS score is still Vina's reversible function.** The acrylamide warhead
  is Meeko-tethered to Cys A:12 and docked in a residue-centered box, but **no covalent
  bond enthalpy is added** — Python Vina cannot consume Meeko's flex-residue output, so the
  irreversible contribution is missing and the ΔG is a pocket-correct **lower bound**, not
  true reactive scoring. Full reactive/flexible-residue docking needs AutoDock-GPU, which
  is not on the conda channels.

Reproduce the box geometry against the committed code:

```bash
cd ../trial-impact-service && python verify_docking_box.py
```

See [open issue #2](../README.md#known-issues) and the covalent entry in the service
README's scope table.

## The previous CFTR pin (9MXL) was the wrong structure

PR #3 docked CFTR against `9MXL` via native mmCIF — but **9MXL contains (R)-BPO-27, not
ivacaftor**, so the box was not even near ivacaftor's site. This PR pins **6O2P**, the real
*complex of ivacaftor with CFTR* (ligand code **VX7**), and boxes on the co-crystal ligand.
The native-mmCIF path (`fetch_structure` → `.cif` → gemmi conversion → dock) still exists
for mmCIF-only targets; it is simply not exercised by these two runs, which pin curated
`.pdb` holos.

## Reproducing these

```bash
cd ../trial-impact-service
# canonical, reproducible sim stack:
conda-lock install --name trialsim conda-sim.lock.yml   # or micromamba create -n trialsim -f conda-sim.lock.yml
bash scripts/install_fpocket.sh                          # fpocket: source-built, not on conda channels
python regen_artifacts.py                                # both, committed stack, offline transport
# — or a live Devin session per trial —
python run_real.py --watch                               # KRAS × sotorasib
python run_real.py --watch --target CFTR --drug ivacaftor \
    --tissue lung --dose 150 --phase PHASE3              # CFTR × ivacaftor
```

Docking is **seed-pinned across a fixed set (42, 43, 44)**, so a re-run reproduces the same
mean ΔG and sd rather than drifting. `requirements-sim.txt` remains a best-effort pip
fallback, but it lacks ProDy (so it cannot run the covalent-tethered route) and cannot pin
the native stack — the conda lock is canonical.

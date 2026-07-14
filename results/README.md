# Results

Artifacts from two **real** runs of the committed pipeline — a real structure fetch, a
real AutoDock Vina docking run (**three seeds**, reported as mean ± sd) into a
**pocket-routed** box, a real PK/PD solve with a **free-drug** occupancy correction. The
`.json` files are the exact records the service stored; open the `.html` files in a
browser for the interactive 3D structure, the PK/PD curve, and the price calls.

Every run below satisfies the result contract: **`code_patched: false`**, meaning the
numbers came from `app/simulation.py` *as committed* — the run did not edit the script to
make it work. (See "The result contract" in the service README for why that field exists
and what it caught.)

> **How these were regenerated.** They were produced by running the committed pipeline
> directly against the pinned **conda-lock** sim stack (`conda-sim.lock.yml`, via
> `regen_artifacts.py`), not in a hosted Devin session — so the physics is real and
> verifiable-from-source, and only the Devin *transport* is stubbed. `devin_session_id`
> therefore reads `local-pinned-stack-regen`. Two independent full runs returned
> byte-identical scientific numbers. Reproduce with `python regen_artifacts.py` (or
> `run_real.py` for a live session).

> **Toolchain note (why ΔG shifted from earlier figures).** Two things moved the absolute
> ΔG relative to the PR #3 numbers. (1) **The box is now routed to the pocket**, not a
> blind central slab — KRAS is tethered to the switch-II Cys of 6OIM, CFTR is boxed on the
> co-crystal ivacaftor (VX7) in 6O2P — so these are pocket-correct scores, weaker in
> absolute value but meaningful. (2) The canonical stack is now the conda lock: RDKit
> `2024.03.5 → 2025.09.5` and Vina `1.2.5 → 1.2.7` (they share libboost 1.86; the old
> RDKit needed 1.84 and could not co-resolve with Vina 1.2.7), Meeko `0.6.0 → 0.7.1`
> (0.6.0 was withdrawn from PyPI). This is expected toolchain + methodology drift, not a
> code patch — `code_patched` is `false`.

> **Estimator attribution.** These are the default docking pipeline, `vina-docking-pkpd@2`
> (bumped from `@1` because the routed box changes the ΔG numbers; stamped onto every
> result). The head-to-head against the `ligand-efficiency-baseline@1` **control** is not
> shown here — the baseline is a naive floor to beat, not a second opinion, and running it
> does not re-validate these numbers. See "Estimators" in the service README.

| File | Trial | Result |
|------|-------|--------|
| `sim_kras_sotorasib.json` | KRAS × sotorasib — Amgen, **Phase 1 (in scope)**, endpoint met | ΔG **−7.202 ± 0.187** kcal/mol (n=3), Kd 8412.3 nM, **free-drug** occupancy 31.0% (fu 0.11), tox flagged ‡, **covalent** (acrylamide warhead). Route **covalent-tethered** to Cys A:12 of curated holo **6OIM** (confidence 0.806). PoS **+0.32** → AMGN up/moderate · REGN, NVS down. |
| `sim_cftr_ivacaftor.json` | CFTR × ivacaftor — Vertex, **Phase 3 (educational only)**, endpoint met | ΔG −7.404 ± 0.007 kcal/mol † (n=3), Kd 6061.5 nM, **free-drug** occupancy **2.06%** (fu 0.01), clean, not covalent. Route **holo-ligand** boxed on co-crystal **VX7** in curated **6O2P** (confidence 0.897). PoS **+0.38** → VRTX up/strong · CRSP, BLUE down. Included to illustrate the pipeline on a well-characterized drug — a Phase 3 event is **outside the actionable preclinical / Phase 1 scope** (see root README). |
| `dashboard_kras_6OIM.html` | ″ | Rendered `/status` with the 3D viewer; docking ΔG shown as mean ± sd. |
| `dashboard_cftr_6O2P.html` | ″ | Rendered `/status`; the 6O2P cryo-EM structure rendered from RCSB. |
| `analysis_dashboard.html` | both | Rendered `/analysis`: physics→price scatter, an estimator head-to-head (empty here — single-estimator corpus), sortable table (ΔG columns carry ± sd), and a per-run drill-down (3D structure + PK/PD curve + PoS reasoning waterfall). Open it and click a row. |

Each JSON holds the trial event, the resolved sponsor/competitor tickers, the full
`sim_result` (binding with per-seed replicates and sd, exposure, free-drug occupancy,
tox/covalent flags, **docking box with routing `mode` + provenance**, provenance: UniProt /
PDB id / **structure format** / SMILES / descriptors / **fu + source** / **vina seeds**),
and the market model's `price_calls` + `commentary`.

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
`replicates` (n). Kd is derived from the **mean** ΔG (`Kd = exp(mean(ΔG)/RT)`), and the
sd feeds a small confidence penalty. This retires the old "reported precision exceeds real
precision" gap: a single draw hid the seed-to-seed spread. The spread here is small
(0.187 / 0.007 kcal/mol) — but that measures **sampling noise only**, not model bias, box
placement, or scoring-function error, which dominate and are not captured by re-seeding.
Cost scales linearly with seed count (3× the docking time).

## ‡ How to read the occupancy and tox columns

**Occupancy is a free-drug engagement estimate, not a total-drug upper bound.** Only
**unbound** drug engages a target, so occupancy is evaluated on the free concentration,
`occ = C_free/(C_free + Kd)` with `C_free = fu · C_total`. The fraction-unbound `fu` comes
from a small curated plasma-protein-binding table (source recorded in
`provenance.fu_source`); an unknown drug falls back to `fu = 1.0` **with a warning**, which
reproduces the old total-drug upper bound rather than silently pretending 1.0 is measured.
Exposure metrics (Cmax, AUC) still use total concentration — they are total-drug quantities.

- **Ivacaftor is >99% plasma-protein-bound** (fu 0.01): combined with the pocket-resolved
  Kd (6061 nM) its occupancy is **2.06%**, in the market model's `occ < 30` band
  (occupancy modifier −0.10). The VRTX call still comes back `strong` (+0.38) on the
  endpoint-met and confidence (0.897) terms.
- **Sotorasib is ~89% bound** (fu 0.11): occupancy **31.0%** (Kd 8412 nM). The AMGN call is
  `up / moderate` (+0.32).

**The "tox" flag is a Lipinski drug-likeness heuristic, not a toxicity model** — ≥2 Ro5
violations, which predicts oral absorption, not safety. It fires on sotorasib because
sotorasib is a big lipophilic oncology molecule; sotorasib is also an approved drug. It is
still priced as a −0.15 safety penalty. This is [issue #3](../README.md#known-issues).

Both the tox heuristic and the crude PK are documented rather than patched; the free-drug
correction fixes occupancy specifically, not the generic PK model (single-dose,
one-compartment, F≈1, generic ADME constants), which remains a placeholder.

## † How to read the two ΔGs (pocket-resolved, but cognate and reversible-scored)

Both runs now box the **real pocket**, which is the fix for the old blind-slab problem. But
neither ΔG is a validated absolute affinity, for two reasons:

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

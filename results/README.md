# Results

Artifacts from two **real** runs of the committed pipeline — a real structure fetch, a
real AutoDock Vina docking run (now **three seeds**, reported as mean ± sd), a real
PK/PD solve with a **free-drug** occupancy correction. The `.json` files are the exact
records the service stored; open the `.html` files in a browser for the interactive 3D
structure, the PK/PD curve, and the price calls.

Every run below satisfies the result contract: **`code_patched: false`**, meaning the
numbers came from `app/simulation.py` *as committed* — the run did not edit the script to
make it work. (See "The result contract" in the service README for why that field exists
and what it caught.)

> **How these were regenerated.** They were produced by running the committed pipeline
> directly against the pinned `requirements-sim.txt` stack (`regen_artifacts.py`), not in
> a hosted Devin session — so the physics is real and verifiable-from-source, and only the
> Devin *transport* is stubbed. `devin_session_id` therefore reads `local-pinned-stack-regen`.
> Reproduce with `python regen_artifacts.py` (or `run_real.py` for a live session).

> **Toolchain note (why ΔG shifted from earlier figures).** The historical pin
> `meeko==0.6.0` is no longer published on PyPI, so the ligand-prep step now runs
> `meeko==0.7.1` (+ its `scipy` dependency); `gemmi==0.6.6` was added for mmCIF. Vina,
> RDKit, Open Babel and NumPy are unchanged. Different Meeko releases protonate/prepare
> the ligand slightly differently, so the absolute ΔG here differs from pre-regeneration
> numbers. This is expected toolchain drift, not a code change — the pipeline logic is the
> same, and the new stack is what `requirements-sim.txt` now pins.

> **Estimator attribution.** These are the default docking pipeline, `vina-docking-pkpd@1`
> (stamped onto every result). The head-to-head against the `ligand-efficiency-baseline@1`
> **control** is not shown here — the baseline is a naive floor to beat, not a second
> opinion, and running it does not re-validate these numbers. See "Estimators" in the
> service README.

| File | Trial | Result |
|------|-------|--------|
| `sim_kras_sotorasib.json` | KRAS × sotorasib — Amgen, Phase 1, endpoint met | ΔG **−8.336 ± 0.010** kcal/mol (n=3), Kd 1336.9 nM, **free-drug** occupancy 73.9% (fu 0.11), tox flagged ‡, **covalent** (acrylamide warhead). Experimental structure **7VVB** (confidence 0.895). PoS **+0.47** → AMGN up / REGN, NVS down. |
| `sim_cftr_ivacaftor.json` | CFTR × ivacaftor — Vertex, Phase 3, endpoint met | ΔG −8.161 ± 0.052 kcal/mol † (n=3), Kd 1776.8 nM, **free-drug** occupancy **6.7%** (fu 0.01), clean, not covalent. Experimental cryo-EM structure **9MXL** via native mmCIF (confidence 0.874). PoS **+0.37** → VRTX up / CRSP, BLUE down. |
| `dashboard_kras_7VVB.html` | ″ | Rendered `/status` with the 3D viewer; docking ΔG shown as mean ± sd. |
| `dashboard_cftr_9MXL.html` | ″ | Rendered `/status`; the 9MXL cryo-EM structure rendered from RCSB. |
| `analysis_dashboard.html` | both | Rendered `/analysis`: physics→price scatter, an estimator head-to-head (empty here — single-estimator corpus), sortable table (ΔG columns carry ± sd), and a per-run drill-down (3D structure + PK/PD curve + PoS reasoning waterfall). Open it and click a row. |

Each JSON holds the trial event, the resolved sponsor/competitor tickers, the full
`sim_result` (binding with per-seed replicates and sd, exposure, free-drug occupancy,
tox/covalent flags, docking box, provenance: UniProt / PDB id / **structure format** /
SMILES / descriptors / **fu + source** / **vina seeds**), and the market model's
`price_calls` + `commentary`.

## Docking is now three seeds, reported as mean ± sd

`run_vina` docks across a **deterministic seed set** (42, 43, 44) and the result carries
`binding_affinity_kcal_mol` (mean ΔG), `binding_affinity_sd_kcal_mol` (sample sd), and
`replicates` (n). Kd is derived from the **mean** ΔG (`Kd = exp(mean(ΔG)/RT)`), and the
sd feeds a small confidence penalty. This retires the core of the old "reported precision
exceeds real precision" gap: a single draw hid the seed-to-seed spread. The spread here is
small (0.010 / 0.052 kcal/mol) — but that measures **sampling noise only**, not model
bias, box placement, or scoring-function error, which dominate and are not captured by
re-seeding. Cost scales linearly with seed count (3× the docking time).

## ‡ How to read the occupancy and tox columns

**Occupancy is now a free-drug engagement estimate, not a total-drug upper bound.** Only
**unbound** drug engages a target, so occupancy is evaluated on the free concentration,
`occ = C_free/(C_free + Kd)` with `C_free = fu · C_total`. The fraction-unbound `fu` comes
from a small curated plasma-protein-binding table (source recorded in
`provenance.fu_source`); an unknown drug falls back to `fu = 1.0` **with a warning**, which
reproduces the old total-drug upper bound rather than silently pretending 1.0 is measured.
Exposure metrics (Cmax, AUC) still use total concentration — they are total-drug quantities.

- **Ivacaftor is >99% plasma-protein-bound** (fu 0.01): its occupancy is **6.7%**, not a
  headline number. This flips the market model's occupancy modifier from **+0.15 to −0.10**
  (the `occ < 30` branch), dropping the PoS delta. The VRTX call nonetheless stays
  `strong` (+0.37) — because the mmCIF fix (below) raised confidence from 0.7 to 0.874 and
  0.37 still clears the 0.35 `strong` threshold. So the free-drug correction changed the
  *occupancy contribution's sign*, not the headline magnitude this time.
- **Sotorasib is ~89% bound** (fu 0.11): occupancy **73.9%**, still above the +0.15 band.

**The "tox" flag is a Lipinski drug-likeness heuristic, not a toxicity model** — ≥2 Ro5
violations, which predicts oral absorption, not safety. It fires on sotorasib because
sotorasib is a big lipophilic oncology molecule; sotorasib is also an approved drug. It is
still priced as a −0.15 safety penalty. This is [issue #3](../README.md#known-issues).

Both the tox heuristic and the crude PK are documented rather than patched; the free-drug
correction fixes occupancy specifically, not the generic PK model (single-dose,
one-compartment, F≈1, generic ADME constants), which remains a placeholder.

## † How to read the CFTR ΔG (and why it is not the headline)

**The CFTR binding number is still not a pocket-resolved affinity — even though 9MXL is now
a real experimental structure.** The docking box is centroid-centered and capped at 40 Å
(both artifacts record `size: [40, 40, 40]`, i.e. the cap binds in both runs). CFTR is a
1480-residue membrane protein; the 40 Å box contains only **~26% of 9MXL's atoms**, and
ivacaftor binds at the TM1/TM6 interface rather than the centroid. Native mmCIF support
(below) fixed *which structure* is docked; it did **not** fix *where* the box sits.

KRAS is the better-founded number — at 56 × 55 × 44 Å the same box covers **~80%** of the
receptor — which is why it carries the headline. Reproduce both figures against the
committed code:

```bash
cd ../trial-impact-service && python verify_docking_box.py
```

This is [open issue #2](../README.md#known-issues). It is documented rather than fixed
because "make the box cover the receptor" is not the fix — an uncapped CFTR box is
~2.4 M Å³, far past the volume where Vina's sampling means anything. The fix is pocket
detection (fpocket / P2Rank) or a drug-bound structure pinned per trial, which is a real
piece of work and would change every number on this page.

## Reproducing these

```bash
cd ../trial-impact-service
python regen_artifacts.py                                   # both, committed stack, offline transport
# — or a live Devin session per trial —
python run_real.py --watch                                  # KRAS × sotorasib
python run_real.py --watch --target CFTR --drug ivacaftor \
    --tissue lung --dose 150 --phase PHASE3                 # CFTR × ivacaftor
```

Docking is **seed-pinned across a fixed set (42, 43, 44)**, so a re-run reproduces the same
mean ΔG and sd rather than drifting. Install the simulation stack from
`requirements-sim.txt` first.

## CFTR now uses the 9MXL cryo-EM structure (native mmCIF via gemmi)

Earlier, CFTR degraded to the AlphaFold model AF-P13569-F1 at confidence 0.7 because
`9MXL` is **mmCIF-only** — `files.rcsb.org/download/9MXL.pdb` returns **404** (very large
modern structures often have no legacy PDB file) and `fetch_structure` read `.pdb` only.

`fetch_structure` now **falls back to the mmCIF file and converts it with `gemmi`** before
ever reaching AlphaFold, so it obtains the real experimental structure:

- `9MXL.pdb` → 404 → `9MXL.cif` downloaded → converted to PDB via `gemmi.read_structure`
  → docked. `provenance.structure_format` records `"mmCIF"`; confidence is 0.874
  (experimental base 0.9, less a small docking-noise penalty), not 0.7.
- Experimental structures are still preferred over AlphaFold when available; AlphaFold
  remains the fallback only when RCSB has neither a PDB nor an mmCIF file.

This retires the mmCIF limitation. It does **not** retire the docking-box gap above (the
box still covers only ~26% of 9MXL), and native mmCIF support does not by itself establish
scientific validity — see Limitations in the service README.

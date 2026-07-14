# Results

Artifacts from two **real** Devin simulation sessions — real structures, a real
AutoDock Vina docking run, a real PK/PD solve. The `.json`
files are the exact records the service stored; open the `.html` files in a browser for
the interactive 3D structure, the PK/PD curve, and the price calls.

Every run below satisfies the result contract: **`code_patched: false`**, meaning the
numbers came from `app/simulation.py` *as committed* — the session did not edit the
script to make the run work. (See "The result contract" in the service README for why
that field exists and what it caught.)

| File | Trial | Result |
|------|-------|--------|
| `sim_kras_sotorasib.json` | KRAS × sotorasib — Amgen, Phase 1, endpoint met | ΔG **−8.606** kcal/mol, Kd 862.6 nM, occupancy 97.6%, tox flagged, **covalent** (acrylamide warhead). Experimental structure **7VVB** (confidence 0.9). PoS **+0.475** → AMGN up / REGN, NVS down. |
| `sim_cftr_ivacaftor.json` | CFTR × ivacaftor — Vertex, Phase 3, endpoint met | ΔG **−8.702** kcal/mol, Kd 738.2 nM, occupancy 94.5%, clean, not covalent. **AlphaFold** model AF-P13569-F1 (confidence 0.7 — see below). PoS **+0.552** → VRTX up / CRSP, BLUE down. |
| `dashboard_kras_7VVB.html` | ″ | Rendered `/status` with the 3D viewer. |
| `dashboard_cftr_AF-P13569-F1.html` | ″ | Rendered `/status`; AlphaFold model rendered from AFDB. |
| `analysis_dashboard.html` | both | Rendered `/analysis`: physics→price scatter, sortable table, and a per-run drill-down (3D structure + PK/PD curve + PoS reasoning waterfall). Open it and click a row. |

Each JSON holds the trial event, the resolved sponsor/competitor tickers, the full
`sim_result` (binding, exposure, occupancy, tox/covalent flags, docking box,
provenance: UniProt / PDB id / SMILES / descriptors), and the market model's
`price_calls` + `commentary`.

## Reproducing these

```bash
cd ../trial-impact-service
python run_real.py --watch                                   # KRAS × sotorasib
python run_real.py --watch --target CFTR --drug ivacaftor \
    --tissue lung --dose 150 --phase PHASE3                  # CFTR × ivacaftor
```

Docking is now **seed-pinned**, so a re-run reproduces the same ΔG rather than drifting.
Two independent CFTR sessions returned ΔG −8.702 / Kd 738.217 / occupancy 94.54 —
identical. (Before the seed was pinned, the same input wandered: −8.42 / −8.59 / −8.61.)

## Why CFTR uses an AlphaFold model, not the 9MXL cryo-EM structure

An earlier CFTR run on record used the experimental cryo-EM structure **9MXL** at
confidence 0.9. That result is **not reproducible from this source tree**, so it has
been retired rather than kept for looks:

- `9MXL` is **mmCIF-only** — `files.rcsb.org/download/9MXL.pdb` returns **404** (very
  large modern structures often have no legacy PDB file), and `fetch_structure` reads
  `.pdb` only.
- So the committed pipeline *cannot* obtain 9MXL. The original number came from a Devin
  session working around the gap inside its sandbox — the exact silent divergence the
  `code_patched` field now exists to make visible.

The pipeline therefore falls back to the AlphaFold prediction and reports
**confidence 0.7** instead of 0.9, which is the honest signal: this is a predicted
structure, not an experimental one. Native mmCIF support
is tracked under Limitations in the service README.

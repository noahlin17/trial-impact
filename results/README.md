# Results

Artifacts from two **real** Devin simulation sessions (not mocked). The `.json`
files are the exact records stored by the service; open the `.html` files in a
browser to see the interactive 3D docked structure + price calls.

| File | Trial | Notes |
|------|-------|-------|
| `sim_kras_sotorasib.json` | KRAS × sotorasib (Phase 1, met) | ΔG −8.585 kcal/mol, Kd 892 nM, occ 97.5%, tox flagged. Structure 7VVB. |
| `sim_cftr_ivacaftor.json` | CFTR × ivacaftor (Phase 3, met) | ΔG −7.997 kcal/mol, Kd 2317 nM, occ 84.7%, clean. Structure 9MXL (cryo-EM). |
| `dashboard_kras_7VVB.html` | " | Rendered `/status` with 3D viewer (RCSB PDB). |
| `dashboard_cftr_9MXL.html` | " | Rendered `/status`; 9MXL is CIF-only, so the viewer falls back pdb→cif. |
| `analysis_dashboard.html` | both runs | Rendered `/analysis`: cross-run charts (physics→price), sortable table, and a per-run drill-down (3D structure + PK/PD curve + PoS reasoning waterfall). Open and click a row. |

Each JSON contains the trial event, the resolved sponsor/competitor tickers, the
full `sim_result` (binding, exposure, occupancy, tox, provenance incl. UniProt /
PDB id / SMILES / descriptors), and the market model's `price_calls` + `commentary`.

To regenerate against a live Devin session:
`cd ../trial-impact-service && python run_real.py --watch`.

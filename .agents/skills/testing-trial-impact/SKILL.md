---
name: testing-trial-impact
description: Test the trial-impact estimator comparison and dashboards end-to-end. Use when verifying the /analysis head-to-head, /status dashboard, or estimator-aware storage in trial-impact-service.
---

# Testing trial-impact end-to-end

The product is the **comparison between estimators on the same trial**, so the highest-value
runtime test is proving the `/analysis` "Estimator head-to-head" section actually groups two
estimator arms under one `(nct_id, event_type)` and computes a spread — not just that a page loads.

## Environment
- Needs **Python 3.11+** (imports `datetime.UTC`; system 3.10 fails with
  `ImportError: cannot import name 'UTC'`). A venv exists at
  `trial-impact-service/.venv` (3.12). Activate it and run from `trial-impact-service/`.
- Lint/unit before runtime testing:
  ```bash
  cd trial-impact-service && . .venv/bin/activate && ruff check . && pytest -q
  ```

## What only Devin can't be real
Live docking (AutoDock Vina) needs a real structure/API, so in a sandbox you **fake the Devin
session** and script the `SIM_RESULT`. Everything else (signed webhook, routes, SQLite, market
model, `analysis.build_payload`, Jinja templates) should be the real code. Disclose that the
estimator *numbers* are scripted but the storage/grouping/rendering are under test.

## Seeding harness (serves the live app for the browser)
Build the app via `create_app(cfg, db=..., devin=<fake>, alerter=..., tickers=...)`, seed via
`app.test_client()`, then `app.run(host="127.0.0.1", port=8899)` in the same process so the
browser hits the same temp SQLite DB. Key gotchas:
- Run with `PYTHONPATH=.` from `trial-impact-service/` or `app` won't import.
- `cfg.sim_repo_commit` must be non-empty (e.g. `"a"*40`) or the webhook refuses to launch
  (unpinned = 503).
- The stored estimator comes from **`sim_result["estimator"]`** returned by the fake Devin —
  NOT from the request payload. So the fake must stamp `estimator` in each result. Map it per
  session: `create_session` receives the prompt; parse `--estimator "([^"]+)"` from it.
- To get two arms for one trial, POST the same trial twice with different `payload["estimator"]`
  (the webhook suffixes the event_id only when an estimator is explicitly requested). Add a third
  trial with no estimator as the single-estimator exclusion control.
- Give sponsors that exist in the `tickers` dict so `market_model.assess` produces price calls.
- Pre-check `GET /analysis.json` `["comparison"]` before recording to confirm the head-to-head
  grouped and `dg_spread`/`pos_spread` are non-null.

## Assertions that distinguish working from broken
1. `/analysis` head-to-head shows ONE trial with TWO rows (both estimator ids), differing
   ΔG/Kd/occ/confidence/PoS, and a header ΔG/PoS spread = max−min.
2. A single-estimator trial is EXCLUDED from head-to-head but STILL appears in the Runs table
   (proves the `<2 distinct estimators` rule, not a missing row).
3. Regression: `/status` renders all events; both arms of the two-estimator trial coexist as
   distinct estimator-keyed rows (proves the estimator-suffixed `event_id` didn't break reads).

## Testing pocket-aware / covalent routing (binding_site.py changes)
When the change is docking-box **routing** (not head-to-head), the highest-value proof is that each
run's route + structure + numbers render, and that a **net-new in-scope drug routes itself**.
- **Serve from the committed artifacts, don't re-dock.** `results/sim_*.json` are full stored
  *events*; the nested `event["sim_result"]` is exactly what the fake Devin should replay. Feed each
  via a `ScriptedDevin(sim_result)` (working on poll 1, finished on poll 2) into one combined temp
  DB, then `app.run(port=8899)`. This renders the real published numbers with zero docking cost.
- **Where the route shows up in the UI:** `/status` shows occupancy + a structure card per run
  (`pdb_id (source) · ΔG`); `/analysis` Runs table shows `ΔG±sd` + `Structure` (pdb_id). The
  `docking_box.mode` / `reactive_residue` / `tether` / `co_crystal_ligand` are NOT in a template —
  read them from **`/analysis.json`** (open in-browser + `ctrl+f`, or curl `/status?format=json`).
  Distinguishing assertions: KRAS `covalent-tethered (curated holo)` + `A:CYS:12`; CFTR
  `holo-ligand (curated)` + `VX7`; a single-draw/blind build would show no `±` or the old 9MXL/AF.
- **Run a NEW real docking SIM (proves "expand the universe").** Use the conda-lock env, not the
  pip venv (pip lacks ProDy/fpocket → covalent route can't run):
  `MAMBA_ROOT_PREFIX=<repo>/.tooling/mamba <repo>/.tooling/bin/micromamba run -n trialsim env
  PYTHONPATH=. python -c "from app.estimators import get_estimator; print(get_estimator('vina-docking-pkpd@2').run(target='EGFR', drug='osimertinib', tissue='tumor', dose_mg=80).to_dict())"`.
  Good in-scope covalent combos (net-new, not the committed drugs): **EGFR × osimertinib/afatinib**
  (Cys797, 4G5J), **BTK × ibrutinib/acalabrutinib** (Cys481, 5P9J). Expect `covalent_flag=True`,
  `mode="covalent-tethered (curated holo)"`, the target's real Cys as `reactive_residue`, a sane
  negative ΔG (~−6 to −12) with `replicates=3`. Takes a few min (real UniProt/PubChem + 3-seed Vina).
- To render the new run in the dashboard too, wrap its `sim_result` as a synthetic event and feed
  it through the same harness; if its sponsor isn't in `tickers.json`, add the **real** ticker
  (e.g. AstraZeneca→AZN) to the in-memory tickers dict so price calls render (config only, not
  fabricated science — keep ΔG/route/structure from the real pipeline).

## Browser tips
- Clear the address bar with `ctrl+l` (or `ctrl+a`) before typing a URL; a plain click leaves
  `about:blank` and the URL gets mangled into `chrome://blankhttp//...`.
- The head-to-head + Runs tables live below the charts — scroll down ~6 clicks, then `zoom` the
  region for a legible screenshot.
- **Server restart gotcha:** if you re-run the harness while the old one holds port 8899 you'll hit
  a stale server / `Address already in use`. Kill cleanly first: `pkill -9 -f _seed_serve.py;
  fuser -k 8899/tcp`, wait ~2s, then relaunch (ideally in a dedicated shell session).

## Devin Secrets Needed
None for the offline/faked test — no real Devin API key is required because the Devin session is
scripted. A real end-to-end run of `compare_estimators.py` / `run_real.py` would need
`DEVIN_API_KEY`, `WATCHER_SHARED_SECRET`, and `SIM_REPO_COMMIT` set, plus live docking deps.

"""Builds the natural-language prompt handed to each Devin simulation session.

Keeping prompt construction in its own module means the exact instructions Devin
receives are easy to find, review, and tune — they are the core "spec" each
simulation session works against. Devin's job is to run the *real* biophysical
pipeline in ``app/simulation.py`` (docking + PK/PD) inside its sandbox and report
the structured result back.

The prompt is **self-contained**: it embeds the exact ``simulation.py`` source and
``requirements-sim.txt`` so a session can run the real pipeline even when the repo
at ``SIM_REPO_URL`` is not reachable (e.g. a private/unpushed repo). Cloning the
repo is offered as the preferred path; the embedded copy is the reliable fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .simulation import RESULT_MARKER

_APP_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _APP_DIR.parent


def _read(path: Path) -> str:
    try:
        return path.read_text()
    except OSError:
        return "# (source unavailable at prompt-build time)"


def build_simulation_prompt(*, event: dict[str, Any], sim_repo_url: str) -> str:
    """Compose the task prompt for one clinical-trial event.

    The prompt is explicit about the deliverable (a single ``SIM_RESULT_JSON``
    line) so the session's success can be judged objectively when we poll it, and
    it embeds the concrete, runnable pipeline so the run does not depend on any
    external repository being available.
    """
    nct = event.get("nct_id", "")
    target = event.get("target") or "the trial's molecular target"
    drug = event.get("drug") or "the investigational drug"
    tissue = event.get("tissue") or "plasma"
    dose = event.get("dose_mg") or 100

    sim_source = _read(_APP_DIR / "simulation.py")
    sim_reqs = _read(_REPO_ROOT / "requirements-sim.txt")

    return f"""\
You are running a real biophysical simulation to support analysis of clinical-trial
readout {nct} (sponsor: {event.get('sponsor', 'unknown')}).

## Objective
Quantify how strongly **{drug}** engages its target **{target}** and what tissue
exposure it achieves in **{tissue}**, by running an actual protein–ligand docking +
PK/PD pipeline. Every number you report must come from a real run — do not
fabricate or estimate any value.

## Setup (self-contained — no repo required)
1. Create a working directory with a Python package layout:
   `mkdir -p simrun/app && cd simrun && touch app/__init__.py`
2. Write the file `requirements-sim.txt` with exactly this content:
   ```
{_indent(sim_reqs)}
   ```
3. Write the file `app/simulation.py` with exactly this content:
   ```python
{_indent(sim_source)}
   ```
4. Install the scientific stack: `pip install -r requirements-sim.txt`. AutoDock
   Vina, RDKit, Meeko and OpenBabel may need system libraries or a conda/mamba
   environment — install whatever is required and fix issues until imports work.
   (Preferred alternative if reachable: `git clone {sim_repo_url}` and use its copy
   instead of writing the files by hand — the code is identical.)

## Run
```
python -m app.simulation --target "{target}" --drug "{drug}" \\
    --tissue "{tissue}" --dose {dose} --json-only
```
The pipeline resolves the UniProt accession for the target, fetches a real
structure (experimental PDB via PDBe/SIFTS, else the AlphaFold model), fetches the
ligand SMILES from PubChem and embeds it in 3D with RDKit, prepares receptor +
ligand PDBQT, docks with AutoDock Vina for the binding free energy ΔG (kcal/mol)
and Kd, then solves a 1-compartment PK/PD ODE for Cmax, AUC and target occupancy.

If a step fails (missing dependency, unavailable structure, docking error), debug
and re-run until it produces a result. If the target has no experimental structure,
the AlphaFold fallback is expected and fine.

## Definition of done
Print the final result as a single line beginning with `{RESULT_MARKER}` followed
by the JSON object the pipeline emits, e.g. (wrapped here only for readability):

```
{RESULT_MARKER} {{"target": "{target}", "drug": "{drug}",
  "binding_affinity_kcal_mol": -9.2, "kd_nM": 180.4, "cmax_ng_ml": 412.0,
  "auc_ng_h_ml": 5100.0, "target_occupancy_pct": 78.5, "tox_flag": false,
  "confidence": 0.9, "provenance": {{"uniprot": "P01116", "pdb_id": "6OIM"}}}}
```

Report the `{RESULT_MARKER}` line clearly in your final message, containing the
real values from your run, so it can be parsed automatically.
"""


def _indent(text: str, spaces: int = 3) -> str:
    pad = " " * spaces
    return "\n".join(pad + line for line in text.splitlines())

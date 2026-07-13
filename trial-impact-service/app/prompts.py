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

    prompt = f"""\
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
{sim_reqs}
```

3. Write the file `app/simulation.py` with exactly this content:

```python
{sim_source}
```

4. Install the scientific stack: `pip install -r requirements-sim.txt`. AutoDock
   Vina, RDKit, Meeko and OpenBabel may need system libraries or a conda/mamba
   environment — install whatever is required and fix issues until imports work.

**Run the source given above, not a checkout.** `{sim_repo_url}` may lag behind this
task (it has been stale before, in ways that broke every run), so step 3 is the single
source of truth. Do not clone it and run that instead, and do not push to it or open
PRs against it — this session is compute, not code review.

## Run
```
python -m app.simulation --target "{target}" --drug "{drug}" \\
    --tissue "{tissue}" --dose {dose} --json-only
```
The pipeline resolves the UniProt accession for the target, fetches a real
structure (experimental PDB via PDBe/SIFTS, else the AlphaFold model), fetches the
ligand SMILES from PubChem and embeds it in 3D with RDKit, prepares receptor +
ligand PDBQT, docks with AutoDock Vina for the binding free energy ΔG (kcal/mol),
Kd and the top docked pose, then solves a 1-compartment PK/PD model in closed form
(Bateman) for Cmax, AUC and target occupancy.

If a step fails (missing dependency, unavailable structure, docking error), debug
and re-run until it produces a result. If the target has no experimental structure,
the AlphaFold fallback is expected and fine.

## If you have to change the code, say so
Environment fixes (packages, system libraries, conda) need no disclosure. But if you
**edit `app/simulation.py` itself** to get the run to complete — an upstream API changed
shape, a URL 404s, anything — then your numbers did **not** come from the committed
code, and that must be visible. Set both fields in the result you emit:

- `"code_patched": true`
- `"patch_summary": "<what you changed and why>"`

Silently patching the script and reporting the result as if it came from the committed
code is a **failed run**, however good the physics — it cannot be reproduced from
source. Disclosing the patch is always the right move.

## Definition of done
Print the final result as a single line beginning with `{RESULT_MARKER}` followed by
the JSON object the pipeline emits. The **shape** looks like this (wrapped here only
for readability — every value below is a placeholder):

```
{RESULT_MARKER} {{"target": "{target}", "drug": "{drug}", "tissue": "{tissue}",
  "binding_affinity_kcal_mol": <float>, "kd_nM": <float>, "cmax_ng_ml": <float>,
  "auc_ng_h_ml": <float>, "target_occupancy_pct": <float>, "tox_flag": <bool>,
  "covalent_flag": <bool>, "confidence": <float>,
  "provenance": {{"uniprot": "<accession the script resolved>",
                 "pdb_id": "<structure the script actually used>"}},
  "code_patched": <bool>, "patch_summary": <string or null>}}
```

**Never copy a value from that sketch** — it is a schema, not data. The placeholders are
deliberately not real numbers, so an echoed example can never be mistaken for a result.
The script fills every field in itself: just print what it prints.

Report that `{RESULT_MARKER}` line in your final message **verbatim, on a single line,
exactly as the script printed it**: do not wrap, pretty-print, truncate, or elide any
part of it (no `...`), and do not replace it with an attachment or file link. It is
parsed by machine; an edited line is an unusable result.
"""
    _check_length(prompt)
    return prompt


# Devin rejects prompts over this length with an opaque `400 Bad Request`, which says
# nothing about size. Because the prompt *embeds the whole of simulation.py*, it grows
# every time the pipeline does — so this ceiling is a live constraint, not a
# formality: adding pose capture + the covalent flag + the AlphaFold fix was enough to
# cross it. Fail here, where the message is actionable, instead of at session creation.
# The durable fix is to stop embedding the source and have Devin clone a *pinned
# commit* instead (see "Result contract" in the README) — that also makes the run
# reproducible by construction.
MAX_PROMPT_CHARS = 30_000


def _check_length(prompt: str) -> None:
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(
            f"simulation prompt is {len(prompt)} chars, over Devin's "
            f"{MAX_PROMPT_CHARS} limit by {len(prompt) - MAX_PROMPT_CHARS}. It embeds "
            "app/simulation.py, so the source has outgrown the budget — trim it, or "
            "switch to cloning a pinned commit instead of embedding."
        )

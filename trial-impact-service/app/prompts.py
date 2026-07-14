"""Builds the natural-language prompt handed to each Devin simulation session.

Keeping prompt construction in its own module means the exact instructions Devin
receives are easy to find, review, and tune — they are the core "spec" each
simulation session works against. Devin's job is to run the *real* biophysical
pipeline in ``app/simulation.py`` (docking + PK/PD) inside its sandbox and report
the structured result back.

The prompt tells the session to **clone a pinned commit** of the repo and run the
selected estimator from that checkout. Pinning the commit is deliberate: it is what
makes a run reproducible from source and lets ``code_patched`` be *verified* against a
known tree rather than trusted on self-report. It also keeps the prompt small — the
source is fetched, not embedded, so the prompt no longer grows with the pipeline and
there is no 30k-character ceiling to fight.
"""

from __future__ import annotations

from typing import Any

from .simulation import RESULT_MARKER


def build_simulation_prompt(
    *,
    event: dict[str, Any],
    sim_repo_url: str,
    sim_repo_commit: str,
    estimator: str,
) -> str:
    """Compose the task prompt for one clinical-trial event.

    Parameters
    ----------
    event:
        The trial event (``nct_id``, ``target``, ``drug``, ``tissue``, ``dose_mg`` …).
    sim_repo_url:
        Repository the session clones to get the pipeline.
    sim_repo_commit:
        The exact commit to check out. **Required** — a blank commit is not a
        reproducible run, so the caller must resolve one (the service refuses to
        launch a session without it).
    estimator:
        Which estimator the session should run (``--estimator`` on the CLI).

    The prompt is explicit about the deliverable (a single ``SIM_RESULT_JSON`` line)
    so the session's success can be judged objectively when we poll it.
    """
    if not sim_repo_commit:
        raise ValueError(
            "sim_repo_commit is required: an unpinned checkout is not reproducible "
            "from source, which is the property the pinned commit exists to guarantee. "
            "Set SIM_REPO_COMMIT to the commit the run should execute."
        )

    nct = event.get("nct_id", "")
    target = event.get("target") or "the trial's molecular target"
    drug = event.get("drug") or "the investigational drug"
    tissue = event.get("tissue") or "plasma"
    dose = event.get("dose_mg") or 100

    prompt = f"""\
You are running a real biophysical simulation to support analysis of clinical-trial
readout {nct} (sponsor: {event.get('sponsor', 'unknown')}).

## Objective
Quantify how strongly **{drug}** engages its target **{target}** and what tissue
exposure it achieves in **{tissue}**, by running an actual protein–ligand docking +
PK/PD pipeline. Every number you report must come from a real run — do not
fabricate or estimate any value.

## Setup — clone the PINNED commit
1. Clone the repository and check out the exact commit below. Run from that tree and
   nothing else — do not use `main`/`HEAD`, and do not edit history:

```
git clone {sim_repo_url} simrun
cd simrun/trial-impact-service
git checkout {sim_repo_commit}
git rev-parse HEAD    # must print {sim_repo_commit}
```

2. Install the scientific stack. The **canonical, reproducible** install is the conda
   lock (RDKit, AutoDock Vina, Meeko, OpenBabel, Gemmi, ProDy, NumPy, SciPy on a common
   libboost):

```
conda-lock install --name trialsim conda-sim.lock.yml
# or: micromamba create -n trialsim -f conda-sim.lock.yml
bash scripts/install_fpocket.sh   # fpocket is source-built (not on conda channels)
```

   `requirements-sim.txt` remains a best-effort pip fallback, but it cannot pin the
   full native stack — prefer the lock. fpocket powers the geometric-pocket fallback; a
   run still works without it (it degrades to the blind box).

The commit `{sim_repo_commit}` is the single source of truth for this run. Pinning it
is what makes the result reproducible from source and independently checkable, so run
that tree exactly — do not run a different branch/commit, and do not push to the repo
or open PRs against it. This session is compute, not code review.

## Run
```
python -m app.simulation --estimator "{estimator}" \\
    --target "{target}" --drug "{drug}" \\
    --tissue "{tissue}" --dose {dose} --json-only
```
The selected estimator does the work. The default docking estimator resolves the
UniProt accession for the target, fetches the ligand SMILES from PubChem and embeds it
in 3D with RDKit, then **routes the docking box by chemistry/target class**: a covalent
warhead against a curated covalent class (e.g. KRAS G12C) is tethered to the class's
reactive cysteine; otherwise it uses a curated or auto-discovered drug-bound co-crystal
box, then fpocket, then the blind centroid box — recording the tier in
`docking_box.mode`. It docks with AutoDock Vina across a fixed seed set for the mean ΔG
(kcal/mol) ± sd and Kd, then solves a 1-compartment PK/PD model in closed form (Bateman)
for Cmax, AUC and free-drug target occupancy. The docked pose is NOT returned — only the
scalars above go in the result line.

If a step fails (missing dependency, unavailable structure, docking error), debug
and re-run until it produces a result. If the target has no experimental structure,
the AlphaFold fallback is expected and fine.

## If you have to change the code, say so
Environment fixes (packages, system libraries, conda) need no disclosure. But if you
**edit the checked-out source itself** to get the run to complete — an upstream API
changed shape, a URL 404s, anything — then your numbers did **not** come from the
pinned commit, and that must be visible. Set both fields in the result you emit:

- `"code_patched": true`
- `"patch_summary": "<what you changed and why>"`

Because the commit is pinned, a reviewer can diff your run against `{sim_repo_commit}`
and see any change — so an undisclosed edit is not just dishonest, it is detectable.
Silently patching the source and reporting the result as if it came from the pinned
commit is a **failed run**, however good the physics. Disclosing the patch is always
the right move.

## Definition of done
Print the final result as a single line beginning with `{RESULT_MARKER}` followed by
the JSON object the pipeline emits. The **shape** looks like this (wrapped here only
for readability — every value below is a placeholder):

```
{RESULT_MARKER} {{"target": "{target}", "drug": "{drug}", "tissue": "{tissue}",
  "binding_affinity_kcal_mol": <float>, "kd_nM": <float>, "cmax_ng_ml": <float>,
  "auc_ng_h_ml": <float>, "target_occupancy_pct": <float>, "tox_flag": <bool>,
  "covalent_flag": <bool>, "confidence": <float>, "estimator": "{estimator}",
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


# A sanity ceiling only. Devin rejects very long prompts with an opaque `400 Bad
# Request`; catch that here where the message is actionable. Now that the pipeline
# source is **cloned, not embedded**, the prompt is a few kB and nowhere near this
# limit — the ceiling that used to bind (the whole of simulation.py rode inside the
# prompt) is gone. The check stays as a cheap guard against a future prompt bloating
# back up.
MAX_PROMPT_CHARS = 30_000


def _check_length(prompt: str) -> None:
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(
            f"simulation prompt is {len(prompt)} chars, over Devin's "
            f"{MAX_PROMPT_CHARS} limit by {len(prompt) - MAX_PROMPT_CHARS}."
        )

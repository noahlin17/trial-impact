#!/usr/bin/env python3
"""Regenerate the committed results/ artifacts, then rebuild the dashboards.

Two modes:

* ``--replay`` (default): rebuild each committed ``results/sim_*.json`` under the
  current estimator semantics **without re-docking**. The docking ΔG / pose / box /
  structure are unchanged (they came from the real pinned-seed Vina run); only the
  *post-docking* transform is re-applied — which is exactly what issue #4 changed
  (a Vina score is a relative, size-confounded docking score, so no absolute Kd and no
  Kd-derived occupancy are surfaced; engagement is a geometric classification). This
  avoids re-running Vina (and the structure-routing non-determinism that comes with it)
  for a change that is purely post-docking.
* ``--redock``: run the *actual* committed docking estimator end to end (needs the
  canonical conda-lock ``trialsim`` sim env). Use only when a net-new docking proof is
  required.

Either way, each ``sim_result`` is driven through the real service path (market model,
tickers, commentary, dashboards) via a scripted Devin transport; only the Devin
*transport* is stubbed.

    python regen_artifacts.py            # replay (no docking)
    python regen_artifacts.py --redock   # real Vina (needs the trialsim env)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app import create_app
from app.config import Config
from app.db import Database, make_event_id
from app.devin_client import SessionStatus
from app.estimators import get_estimator
from app.signing import SIGNATURE_HEADER, sign
from app.simulation import (
    VINA_ESTIMATOR_ID,
    classify_engagement,
    kd_from_dg,
    run_pkpd,
)

SECRET = "regen-secret"
RESULTS = Path(__file__).resolve().parent.parent / "results"
TICKERS = json.loads((Path(__file__).resolve().parent / "tickers.json").read_text())

TRIALS = [
    {
        "name": "kras_sotorasib", "nct": "NCT-REAL-0001", "sponsor": "Amgen",
        "drug": "sotorasib", "target": "KRAS", "tissue": "tumor",
        "phase": "PHASE1", "dose": 960.0, "outcome": "met",
    },
    {
        "name": "cftr_ivacaftor", "nct": "NCT-VERIFY-002",
        "sponsor": "Vertex Pharmaceuticals", "drug": "ivacaftor", "target": "CFTR",
        "tissue": "lung", "phase": "PHASE3", "dose": 150.0, "outcome": "met",
    },
]


class ScriptedDevin:
    """Transport stub: 'working' on the first poll, returns the real result on the next."""

    def __init__(self, sim_result: dict) -> None:
        self._polls = 0
        self._sim = sim_result

    def create_session(self, *, prompt, title, tags=None):
        class _Created:
            session_id = "local-pinned-stack-regen"
            url = ""

        return _Created()

    def get_session(self, session_id):
        self._polls += 1
        if self._polls == 1:
            return SessionStatus("working", "running", None, None)
        return SessionStatus("finished", "completed", dict(self._sim), None)


class NullAlerter:
    def notify(self, event, assessment):
        return []


def _cfg(db_path: str) -> Config:
    return Config(
        devin_api_key="regen", devin_api_base="http://local",
        sim_repo_url="https://github.com/noahlin17/trial-impact",
        sim_repo_commit="0" * 40,
        watcher_shared_secret=SECRET,
        slack_webhook_url="", smtp_host="", smtp_port=587, smtp_user="",
        smtp_password="", email_from="", email_to="",
        tickers_path="tickers.json", market_moving_threshold=0.10,
        database_path=db_path,
    )


def _run_event(app, trial: dict) -> dict:
    client = app.test_client()
    payload = {
        "event_type": "results_posted", "nct_id": trial["nct"],
        "sponsor": trial["sponsor"], "drug": trial["drug"], "target": trial["target"],
        "tissue": trial["tissue"], "phase": trial["phase"],
        "overall_status": "COMPLETED", "endpoint_outcome": trial["outcome"],
        "dose_mg": trial["dose"],
    }
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", SIGNATURE_HEADER: sign(SECRET, body)}
    assert client.post("/webhook/trial-update", data=body, headers=headers).status_code == 201
    client.post("/poll")  # working
    client.post("/poll")  # finished -> reconcile + market model
    eid = make_event_id(trial["nct"], "results_posted")
    return app.extensions["trial_impact"]["db"].get_event(eid)


def replay_at_current_semantics(old_sim: dict) -> dict:
    """Rebuild a committed sim_result under the current (issue #4) semantics.

    The docking outputs (ΔG, sd, replicates, seeds, pose box, structure) are copied
    verbatim — NO re-docking. Only the post-docking transform is re-applied: the Vina
    score is no longer turned into an absolute Kd or a Kd-derived occupancy; the
    uncalibrated exp(ΔG/RT) value is kept in provenance for transparency, and a
    geometric ``binding_engagement`` classification is added.
    """
    sim = dict(old_sim)
    prov = dict(sim.get("provenance") or {})
    dg = sim["binding_affinity_kcal_mol"]
    sd = sim.get("binding_affinity_sd_kcal_mol")
    mode = (sim.get("docking_box") or {}).get("mode")

    prov["vina_pseudo_kd_nM"] = round(kd_from_dg(dg), 3)
    prov["vina_pseudo_kd_note"] = (
        "exp(ΔG/RT) of the Vina score; NOT a measured or calibrated affinity — "
        "Vina ranks by size/contact, not Kd (issue #4). Do not read as binding strength."
    )
    engagement, note = classify_engagement(mode, dg, sd)
    prov["engagement_note"] = note
    # Occupancy/free-drug machinery is gone under issue #4; drop its provenance.
    prov.pop("fu", None)
    prov.pop("fu_source", None)
    sim["provenance"] = prov
    sim["kd_nM"] = None
    sim["target_occupancy_pct"] = None
    sim["binding_engagement"] = engagement

    mw = (prov.get("descriptors") or {}).get("mw")
    if mw:  # exposure is Kd-independent; recompute so it matches the current model
        pk = run_pkpd(dose_mg=sim["dose_mg"], mol_weight=mw, tissue=sim["tissue"])
        sim["cmax_ng_ml"] = round(pk["cmax_ng_ml"], 3)
        sim["auc_ng_h_ml"] = round(pk["auc_ng_h_ml"], 3)
    sim["estimator"] = VINA_ESTIMATOR_ID
    return sim


def _load_committed_sim(name: str) -> dict:
    old = json.loads((RESULTS / f"sim_{name}.json").read_text())
    return old["sim_result"]


def build_sim_results(redock: bool) -> dict[str, dict] | None:
    sim_results: dict[str, dict] = {}
    if redock:
        estimator = get_estimator(VINA_ESTIMATOR_ID)
    for t in TRIALS:
        if redock:
            print(f"── docking {t['target']} × {t['drug']} (real Vina, pinned seeds) ──")
            res = estimator.run(
                target=t["target"], drug=t["drug"], tissue=t["tissue"], dose_mg=t["dose"],
            )
            if res.error:
                print(f"  FAILED: {res.error}")
                return None
            sim = res.to_dict()
        else:
            print(f"── replaying {t['target']} × {t['drug']} (committed ΔG, no re-dock) ──")
            sim = replay_at_current_semantics(_load_committed_sim(t["name"]))
        sim_results[t["name"]] = sim
        print(f"  ΔG={sim['binding_affinity_kcal_mol']}±{sim.get('binding_affinity_sd_kcal_mol')}"
              f"  engagement={sim.get('binding_engagement')}"
              f"  {sim['provenance']['pdb_id']}  conf={sim.get('confidence')}"
              f"  estimator={sim['estimator']}")
    return sim_results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redock", action="store_true",
                        help="re-run real Vina (needs the trialsim env); default replays")
    args = parser.parse_args(argv)

    sim_results = build_sim_results(redock=args.redock)
    if sim_results is None:
        return 1

    # Per-trial: isolated DB so /status renders exactly one run per dashboard.
    for t in TRIALS:
        app = create_app(
            _cfg(f"/tmp/regen_{t['name']}.db"), db=Database(f"/tmp/regen_{t['name']}.db"),
            devin=ScriptedDevin(sim_results[t["name"]]), alerter=NullAlerter(),
            tickers=TICKERS,
        )
        app.testing = True
        event = _run_event(app, t)
        (RESULTS / f"sim_{t['name']}.json").write_text(json.dumps(event, indent=2) + "\n")
        pdb = event["sim_result"]["provenance"]["pdb_id"]
        html = app.test_client().get("/status", headers={"Accept": "text/html"}).data
        (RESULTS / f"dashboard_{t['target'].lower()}_{pdb}.html").write_bytes(html)
        print(f"  wrote sim_{t['name']}.json + dashboard_{t['target'].lower()}_{pdb}.html")

    # Combined: both runs in one DB so /analysis has a corpus to aggregate.
    combo = create_app(
        _cfg("/tmp/regen_combo.db"), db=Database("/tmp/regen_combo.db"),
        devin=ScriptedDevin(sim_results[TRIALS[0]["name"]]), alerter=NullAlerter(),
        tickers=TICKERS,
    )
    combo.testing = True
    # Rewire the transport per trial (each event polls its own scripted result).
    ext = combo.extensions["trial_impact"]
    for t in TRIALS:
        ext["devin"] = ScriptedDevin(sim_results[t["name"]])
        _run_event(combo, t)
    analysis_html = combo.test_client().get("/analysis", headers={"Accept": "text/html"}).data
    (RESULTS / "analysis_dashboard.html").write_bytes(analysis_html)
    print("  wrote analysis_dashboard.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

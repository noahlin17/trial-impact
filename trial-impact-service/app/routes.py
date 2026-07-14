"""HTTP routes for the trial-impact service.

Four endpoints mapping to the automation pipeline:

    trial webhook  ->  /webhook/trial-update   (trigger: spawn a Devin sim session)
    observe        ->  /status                 (read model: events + aggregates)
    reconcile      ->  /poll                    (advance state, score, alert)
    liveness       ->  /health

Collaborators (config, db, devin, alerter, tickers) are pulled off
``current_app.extensions["trial_impact"]`` so they can be swapped for fakes in
tests.
"""

from __future__ import annotations

from typing import Any

import requests
from flask import Blueprint, current_app, jsonify, render_template, request

from . import db as db_module
from . import market_model
from .estimators import DEFAULT_ESTIMATOR_ID, REGISTRY
from .prompts import build_simulation_prompt
from .signing import SIGNATURE_HEADER, verify

bp = Blueprint("routes", __name__)


def _ctx() -> dict[str, Any]:
    return current_app.extensions["trial_impact"]


@bp.get("/health")
def health() -> Any:
    return jsonify({"status": "ok"})


@bp.post("/webhook/trial-update")
def webhook_trial_update() -> Any:
    """Accept a clinical-trial event and spawn a Devin simulation session.

    Expected JSON (as emitted by ctgov-watcher):
        {
          "event_type": "results_posted",
          "nct_id": "NCT01234567",
          "sponsor": "Acme Biopharma",
          "drug": "ACM-101", "target": "PCSK9", "tissue": "hepatic",
          "phase": "PHASE3", "overall_status": "COMPLETED",
          "endpoint_outcome": "met", "dose_mg": 140
        }
    """
    ctx = _ctx()
    cfg = ctx["config"]
    db: db_module.Database = ctx["db"]

    raw = request.get_data()
    if cfg.signature_required and not verify(
        cfg.watcher_shared_secret, raw, request.headers.get(SIGNATURE_HEADER)
    ):
        return jsonify({"error": "invalid or missing signature"}), 401

    payload = request.get_json(silent=True) or {}
    nct_id = payload.get("nct_id")
    event_type = payload.get("event_type") or "trial_update"
    if not nct_id:
        return jsonify({"error": "missing 'nct_id'"}), 400

    # Which estimator to run. Optional in the payload; absent means the default
    # docking pipeline (so a plain watcher webhook behaves exactly as before). An
    # explicit, unknown id is a client error, not a silently-swapped default.
    requested_estimator = payload.get("estimator")
    if requested_estimator and requested_estimator not in REGISTRY:
        return jsonify(
            {
                "error": f"unknown estimator '{requested_estimator}'",
                "known": sorted(REGISTRY),
            }
        ), 400
    estimator_id = requested_estimator or DEFAULT_ESTIMATOR_ID

    sponsor = payload.get("sponsor") or ""
    # Suffix the key with the estimator only when one was explicitly requested, so two
    # estimators on the same trial get two rows (a storable head-to-head) while the
    # default single-estimator path keeps the original <nct>:<event> key.
    event_id = db_module.make_event_id(nct_id, event_type, requested_estimator)

    # Resolve the sponsor + competitors to tickers up front so they are visible on
    # the dashboard even before the simulation completes.
    resolved = market_model.resolve_tickers(sponsor, ctx["tickers"])

    common = {
        "event_id": event_id,
        "nct_id": nct_id,
        "sponsor": sponsor,
        "drug": payload.get("drug"),
        "target": payload.get("target"),
        "tissue": payload.get("tissue"),
        "phase": payload.get("phase"),
        "event_type": event_type,
        "endpoint_outcome": payload.get("endpoint_outcome"),
        "sponsor_ticker": resolved["sponsor_ticker"],
        "competitor_tickers": resolved["competitors"],
    }

    # Guard: without an API key we can't create a session. Record the attempt as
    # failed so it is visible on /status rather than silently dropped.
    if not cfg.devin_configured:
        event = db.upsert_new_event(
            **common,
            devin_session_id=None,
            session_url=None,
            status=db_module.STATUS_FAILED,
            error_message="DEVIN_API_KEY not configured",
        )
        return jsonify({"error": "DEVIN_API_KEY not configured", "event": event}), 503

    # Guard: refuse to launch an unpinned session. Without a commit the run is not
    # reproducible from source and code_patched can't be verified — the very
    # properties the pinned checkout exists to provide — so record it as failed and
    # make it visible on /status rather than quietly running against a moving target.
    if not cfg.sim_pinned:
        event = db.upsert_new_event(
            **common,
            devin_session_id=None,
            session_url=None,
            status=db_module.STATUS_FAILED,
            error_message="SIM_REPO_COMMIT not configured (unpinned run is not reproducible)",
        )
        return jsonify({"error": "SIM_REPO_COMMIT not configured", "event": event}), 503

    prompt = build_simulation_prompt(
        event={**payload, "sponsor": sponsor, "dose_mg": payload.get("dose_mg")},
        sim_repo_url=cfg.sim_repo_url,
        sim_repo_commit=cfg.sim_repo_commit,
        estimator=estimator_id,
    )

    try:
        created = ctx["devin"].create_session(
            prompt=prompt,
            title=f"Simulate {sponsor} {nct_id} ({payload.get('drug', '')})"[:200],
            tags=["trial-impact", f"nct-{nct_id}", event_type, f"est-{estimator_id}"],
        )
    except requests.RequestException as exc:
        event = db.upsert_new_event(
            **common,
            devin_session_id=None,
            session_url=None,
            status=db_module.STATUS_FAILED,
            error_message=f"Failed to create Devin session: {exc}",
        )
        return jsonify({"error": str(exc), "event": event}), 502

    event = db.upsert_new_event(
        **common,
        devin_session_id=created.session_id,
        session_url=created.url,
        status=db_module.STATUS_QUEUED,
    )
    return jsonify({"event": event}), 201


@bp.get("/status")
def status() -> Any:
    """Return all tracked events + aggregate stats as JSON or HTML."""
    from .stats import compute_stats

    ctx = _ctx()
    db: db_module.Database = ctx["db"]

    events = db.list_events()
    stats = compute_stats(events)

    wants_json = (
        request.args.get("format") == "json"
        or request.accept_mimetypes.best == "application/json"
        or "text/html" not in request.accept_mimetypes
    )
    if wants_json:
        return jsonify({"events": events, "stats": stats})

    return render_template("status.html", events=events, stats=stats)


@bp.get("/analysis")
def analysis_view() -> Any:
    """Analytical read model: corpus aggregates, physics→price charts, drill-down.

    HTML for browsers; JSON with ``?format=json`` (same payload as /analysis.json).
    """
    from . import analysis

    db: db_module.Database = _ctx()["db"]
    payload = analysis.build_payload(db.list_events())

    wants_json = (
        request.args.get("format") == "json"
        or request.accept_mimetypes.best == "application/json"
        or "text/html" not in request.accept_mimetypes
    )
    if wants_json:
        return jsonify(payload)
    return render_template("analysis.html", payload=payload)


@bp.get("/analysis.json")
def analysis_json() -> Any:
    """Machine-readable analytics payload (drives the charts, export, offline view)."""
    from . import analysis

    db: db_module.Database = _ctx()["db"]
    return jsonify(analysis.build_payload(db.list_events()))


@bp.post("/poll")
def poll() -> Any:
    """Poll in-progress sessions; score completed sims; alert on market-movers.

    Idempotent: safe to call repeatedly (a real deployment puts it on a timer).
    """
    ctx = _ctx()
    cfg = ctx["config"]
    db: db_module.Database = ctx["db"]
    devin = ctx["devin"]
    alerter = ctx["alerter"]

    in_progress = db.list_in_progress()
    results: list[dict[str, Any]] = []

    for event in in_progress:
        event_id = event["event_id"]
        session_id = event.get("devin_session_id")
        if not session_id:
            continue

        try:
            session = devin.get_session(session_id)
        except requests.RequestException as exc:
            results.append({"event_id": event_id, "error": f"poll failed: {exc}"})
            continue

        alerted: list[str] = []
        if session.mapped_status == db_module.STATUS_COMPLETED and session.sim_result:
            assessment = market_model.assess(
                event=event,
                sim=session.sim_result,
                sponsor_ticker=event.get("sponsor_ticker"),
                sponsor_name=event.get("sponsor") or "",
                competitors=event.get("competitor_tickers") or [],
                threshold=cfg.market_moving_threshold,
            )
            db.update_event_status(
                event_id=event_id,
                status=db_module.STATUS_COMPLETED,
                sim_result=session.sim_result,
                commentary=assessment["commentary"],
                price_calls=assessment["price_calls"],
            )
            if assessment["market_moving"] and not event.get("alert_sent"):
                alerted = alerter.notify(event, assessment)
                db.mark_alert_sent(event_id)
        else:
            db.update_event_status(
                event_id=event_id,
                status=session.mapped_status,
                sim_result=session.sim_result,
                error_message=session.error_message,
            )

        results.append(
            {
                "event_id": event_id,
                "status": session.mapped_status,
                "alerted": alerted,
            }
        )

    return jsonify({"polled": len(in_progress), "results": results})

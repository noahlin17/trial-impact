"""Analytics over the corpus of completed simulations (the ``/analysis`` read model).

Everything here is computed **on demand** from the events already in SQLite —
nothing new is stored. It adds domain rollups on top of ``stats.compute_stats``,
extracts scatter series that reveal how the physics maps to the market call, and
assembles a full per-run drill-down (reasoning trace + reconstructed PK/PD curve).
"""

from __future__ import annotations

import statistics
from typing import Any

from . import market_model, stats
from .db import STATUS_COMPLETED
from .simulation import pkpd_curve


def _completed(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        e for e in events
        if e.get("status") == STATUS_COMPLETED and e.get("sim_result")
    ]


def corpus_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate metrics across the corpus (extends ``stats.compute_stats``)."""
    completed = _completed(events)
    base = stats.compute_stats(events)

    dgs, deltas = [], []
    druglike = 0
    engaged = 0  # runs that docked into an experimentally-resolved site
    by_sponsor: dict[str, list[float]] = {}
    by_target: dict[str, list[float]] = {}
    for e in completed:
        s = e["sim_result"]
        d = market_model.pos_delta(e, s)
        deltas.append(d)
        if s.get("binding_affinity_kcal_mol") is not None:
            dgs.append(s["binding_affinity_kcal_mol"])
        if s.get("binding_engagement") == "experimental-site":
            engaged += 1
        if s.get("druglikeness_flag"):
            druglike += 1
        by_sponsor.setdefault(e.get("sponsor") or "?", []).append(d)
        by_target.setdefault(e.get("target") or "?", []).append(d)

    n = len(completed)
    base.update({
        "analyzed": n,
        "druglikeness_rate": round(druglike / n, 3) if n else None,
        "mean_dg": round(statistics.mean(dgs), 3) if dgs else None,
        "median_dg": round(statistics.median(dgs), 3) if dgs else None,
        "engagement_rate": round(engaged / n, 3) if n else None,
        "mean_pos_delta": round(statistics.mean(deltas), 3) if deltas else None,
        "by_sponsor": {
            k: {"n": len(v), "mean_pos": round(statistics.mean(v), 3)}
            for k, v in sorted(by_sponsor.items())
        },
        "by_target": {
            k: {"n": len(v), "mean_pos": round(statistics.mean(v), 3)}
            for k, v in sorted(by_target.items())
        },
    })
    return base


def relationships(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Labelled points for the physics→price scatter charts."""
    points = []
    for e in _completed(events):
        s = e["sim_result"]
        points.append({
            "drug": e.get("drug"), "target": e.get("target"), "nct_id": e.get("nct_id"),
            "dg": s.get("binding_affinity_kcal_mol"),
            "engagement": s.get("binding_engagement"),
            "pos": round(market_model.pos_delta(e, s), 3),
            "druglikeness": bool(s.get("druglikeness_flag")),
            "estimator": s.get("estimator"),
        })
    return {"points": points}


def estimator_comparison(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Head-to-head: trials that ran under more than one estimator.

    The comparison is the point of the estimator interface, not any single model's
    number. This groups completed runs by (trial, event) and, for every trial that was
    scored by two or more estimators, lays their numbers side by side so a reader can
    see where the models agree and — more usefully — where they diverge. A single
    estimator on a trial produces no comparison and is omitted.
    """
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for e in _completed(events):
        s = e["sim_result"]
        key = (e.get("nct_id") or "?", e.get("event_type") or "?")
        grouped.setdefault(key, []).append(
            {
                "estimator": s.get("estimator") or "unknown",
                "drug": e.get("drug"),
                "target": e.get("target"),
                "dg": s.get("binding_affinity_kcal_mol"),
                "dg_sd": s.get("binding_affinity_sd_kcal_mol"),
                "engagement": s.get("binding_engagement"),
                "confidence": s.get("confidence"),
                "pos": round(market_model.pos_delta(e, s), 3),
            }
        )

    trials = []
    for (nct_id, event_type), arms in sorted(grouped.items()):
        distinct = {a["estimator"] for a in arms}
        if len(distinct) < 2:
            continue  # not a head-to-head — nothing to compare
        arms_sorted = sorted(arms, key=lambda a: a["estimator"])
        dgs = [a["dg"] for a in arms_sorted if a["dg"] is not None]
        poss = [a["pos"] for a in arms_sorted if a["pos"] is not None]
        trials.append(
            {
                "nct_id": nct_id,
                "event_type": event_type,
                "drug": arms_sorted[0]["drug"],
                "target": arms_sorted[0]["target"],
                "arms": arms_sorted,
                # Spread across estimators: how much the choice of model moved the number.
                "dg_spread": round(max(dgs) - min(dgs), 3) if len(dgs) > 1 else None,
                "pos_spread": round(max(poss) - min(poss), 3) if len(poss) > 1 else None,
            }
        )
    return {"trials": trials}


def run_detail(e: dict[str, Any]) -> dict[str, Any]:
    """Full drill-down for one run: sim + reasoning trace + reconstructed PK/PD curve."""
    s = e["sim_result"]
    return {
        "event_id": e["event_id"], "nct_id": e.get("nct_id"),
        "sponsor": e.get("sponsor"), "sponsor_ticker": e.get("sponsor_ticker"),
        "drug": e.get("drug"), "target": e.get("target"),
        "tissue": e.get("tissue"), "phase": e.get("phase"),
        "endpoint_outcome": e.get("endpoint_outcome"),
        "sim_result": s,
        "pos_breakdown": market_model.pos_breakdown(e, s),
        "pkpd_curve": pkpd_curve(s),
        "price_calls": e.get("price_calls"),
        "commentary": e.get("commentary"),
    }


def _sponsor_call(e: dict[str, Any]) -> dict[str, Any] | None:
    for c in (e.get("price_calls") or []):
        if c.get("role") == "sponsor":
            return c
    return None


def build_payload(events: list[dict[str, Any]]) -> dict[str, Any]:
    """The full ``/analysis`` payload: summary + scatter series + per-run rows.

    Each row embeds its ``detail`` so the rendered page is self-contained (the
    static export works offline without extra requests).
    """
    rows = []
    for e in _completed(events):
        s = e["sim_result"]
        prov = s.get("provenance") or {}
        call = _sponsor_call(e)
        rows.append({
            "event_id": e["event_id"], "nct_id": e.get("nct_id"),
            "sponsor": e.get("sponsor"), "sponsor_ticker": e.get("sponsor_ticker"),
            "drug": e.get("drug"), "target": e.get("target"),
            "tissue": e.get("tissue"), "phase": e.get("phase"),
            "dg": s.get("binding_affinity_kcal_mol"),
            "dg_sd": s.get("binding_affinity_sd_kcal_mol"),
            "engagement": s.get("binding_engagement"),
            "druglikeness": bool(s.get("druglikeness_flag")),
            "pos_delta": round(market_model.pos_delta(e, s), 3),
            "direction": call["direction"] if call else "flat",
            "magnitude": call["magnitude"] if call else "flat",
            "estimator": s.get("estimator"),
            "pdb_id": prov.get("pdb_id"),
            "structure_source": prov.get("structure_source"),
            "uniprot": prov.get("uniprot"),
            "detail": run_detail(e),
        })
    return {
        "summary": corpus_summary(events),
        "relationships": relationships(events),
        "comparison": estimator_comparison(events),
        "runs": rows,
    }

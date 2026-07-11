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

    dgs, occs, deltas = [], [], []
    tox = 0
    by_sponsor: dict[str, list[float]] = {}
    by_target: dict[str, list[float]] = {}
    for e in completed:
        s = e["sim_result"]
        d = market_model.pos_delta(e, s)
        deltas.append(d)
        if s.get("binding_affinity_kcal_mol") is not None:
            dgs.append(s["binding_affinity_kcal_mol"])
        if s.get("target_occupancy_pct") is not None:
            occs.append(s["target_occupancy_pct"])
        if s.get("tox_flag"):
            tox += 1
        by_sponsor.setdefault(e.get("sponsor") or "?", []).append(d)
        by_target.setdefault(e.get("target") or "?", []).append(d)

    n = len(completed)
    base.update({
        "analyzed": n,
        "tox_rate": round(tox / n, 3) if n else None,
        "mean_dg": round(statistics.mean(dgs), 3) if dgs else None,
        "median_dg": round(statistics.median(dgs), 3) if dgs else None,
        "mean_occupancy": round(statistics.mean(occs), 1) if occs else None,
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
            "kd": s.get("kd_nM"),
            "occ": s.get("target_occupancy_pct"),
            "pos": round(market_model.pos_delta(e, s), 3),
            "tox": bool(s.get("tox_flag")),
        })
    return {"points": points}


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
            "dg": s.get("binding_affinity_kcal_mol"), "kd": s.get("kd_nM"),
            "occupancy": s.get("target_occupancy_pct"), "tox": bool(s.get("tox_flag")),
            "pos_delta": round(market_model.pos_delta(e, s), 3),
            "direction": call["direction"] if call else "flat",
            "magnitude": call["magnitude"] if call else "flat",
            "pdb_id": prov.get("pdb_id"),
            "structure_source": prov.get("structure_source"),
            "uniprot": prov.get("uniprot"),
            "detail": run_detail(e),
        })
    return {
        "summary": corpus_summary(events),
        "relationships": relationships(events),
        "runs": rows,
    }

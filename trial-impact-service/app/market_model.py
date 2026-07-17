"""The market-impact model that runs in-service.

Turns a clinical-trial event plus the biophysical simulation result into a
probability-of-success (PoS) delta, then into directional share-price calls for
the sponsor and its publicly-traded competitors, with a short rationale.

This is intentionally a transparent, rules-based model — every number that moves
the call is inspectable — rather than a black box, because the output is
research/commentary, **not investment advice** (a disclaimer is attached to every
assessment).
"""

from __future__ import annotations

import json
from typing import Any

DISCLAIMER = (
    "Automated research signal derived from a biophysical simulation and trial "
    "metadata. NOT investment advice; for informational purposes only."
)

# Magnitude buckets keyed by |PoS delta|.
_STRONG, _MODERATE, _SLIGHT = 0.35, 0.18, 0.05


def load_tickers(path: str) -> dict[str, dict[str, Any]]:
    """Load the sponsor→ticker/competitor map, keyed by lowercased sponsor name.

    Missing/invalid file yields an empty map (the service still runs; tickers are
    simply reported as unknown).
    """
    try:
        with open(path) as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return {k.lower(): v for k, v in raw.items()}


def resolve_tickers(sponsor: str, tickers_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Resolve a sponsor name to its ticker and competitor list (best effort)."""
    key = sponsor.lower().strip()
    entry = tickers_map.get(key)
    if entry is None:  # fall back to a substring match on known sponsors
        for name, val in tickers_map.items():
            if name in key or key in name:
                entry = val
                break
    if entry is None:
        return {"sponsor_ticker": None, "sponsor_name": sponsor, "competitors": []}
    return {
        "sponsor_ticker": entry.get("ticker"),
        "sponsor_name": entry.get("name", sponsor),
        "competitors": entry.get("competitors", []),
    }


def pos_delta(event: dict[str, Any], sim: dict[str, Any] | None) -> float:
    """Probability-of-success delta in [-1, 1] from the readout + physics.

    The clinical readout dominates; the simulation only *corroborates* it. Docking is a
    **geometric engagement** check, not a binding-strength signal — the Vina score
    ranks by size/contact, not affinity — so no ΔG/Kd magnitude or occupancy
    is priced. A run that docks the molecule into the experimentally-resolved target
    site with a reproducible pose adds a small, capped corroboration to a positive
    readout; nothing else moves the call. The signal is scaled by the simulation's
    confidence. The drug-likeness flag is informational and is *not* priced (it predicts
    oral absorption, not safety — see ``run_simulation``).
    """
    return pos_breakdown(event, sim)["final"]


def pos_breakdown(event: dict[str, Any], sim: dict[str, Any] | None) -> dict[str, Any]:
    """Decompose the PoS delta into its contributions (the reasoning trace).

    Returns the ordered pieces that make up ``pos_delta`` — clinical base, geometric
    engagement, and the confidence scaling — plus a ``components`` list for display.
    ``pos_delta`` is exactly ``breakdown["final"]``, so the headline number and the
    trace shown on the analysis dashboard can never disagree. The drug-likeness flag
    is carried for display but contributes 0.0 — it is not a priced term. Binding is
    represented by a single geometric ``engagement_modifier``: there is no
    separate binding-strength or occupancy term any more.
    """
    outcome = (event.get("endpoint_outcome") or "unknown").lower()
    base = {"met": 0.5, "missed": -0.5}.get(outcome, 0.0)

    if not sim or sim.get("error"):
        # No usable physics — rely on the readout alone at reduced conviction.
        final = _clamp(base * 0.6)
        return {
            "outcome": outcome,
            "sim_available": False,
            "outcome_base": base,
            "engagement_modifier": 0.0,
            "druglikeness_flag": False,
            "subtotal": base,
            "confidence_scale": 0.6,
            "final": final,
            "components": [
                {"label": f"Endpoint {outcome}", "value": round(base, 3)},
                {"label": "No simulation (×0.6 conviction)", "value": round(final - base, 3)},
            ],
        }

    engagement = sim.get("binding_engagement")

    # Docking is a GEOMETRIC engagement corroborator, not a binding-strength signal.
    # The Vina score ranks by ligand size/contact area, not affinity (an
    # 8-anchor calibration found Spearman ρ(−ΔG, pKd) = −0.24 vs ρ(−ΔG, size) = +0.45), so a
    # ΔG/Kd magnitude and a Kd-derived occupancy are NOT priced. The only thing docking
    # can honestly add is confirming the molecule docks into the experimentally-resolved
    # target site with a reproducible pose — a small, capped corroboration of a win.
    engagement_raw = 0.05 if engagement == "experimental-site" else 0.0

    druglike = bool(sim.get("druglikeness_flag"))

    # Apply modifiers by *meaning*, not by mirroring the readout sign.
    #   - Geometric engagement corroboration only strengthens a WIN; docking into the
    #     right pocket doesn't rescue a missed clinical endpoint, so it is dropped for a
    #     miss. It is also small and capped: docking cannot claim strength.
    #   - The drug-likeness flag (≥2 Lipinski violations) is *not priced*: it predicts
    #     oral absorption, not toxicity, and fires on approved drugs (sotorasib). It was
    #     previously charged -0.15 as if a safety finding had occurred; that conflated a
    #     drug-likeness heuristic with a safety event, so it is now surfaced for display
    #     only and contributes nothing to the delta.
    #
    # Every term here is a *modifier on a readout*. With no readout (outcome unknown,
    # base 0.0) there is nothing to modify, so they are all dropped and the model
    # declines to call — the no-call gate falls out of the design, it is not a patch.
    is_win = base > 0
    has_readout = outcome in ("met", "missed")
    engagement_mod = engagement_raw if is_win else 0.0
    subtotal = base + engagement_mod

    confidence = sim.get("confidence") or 0.7
    scale = 0.5 + 0.5 * confidence
    final = _clamp(subtotal * scale)

    if has_readout:
        components = [
            {"label": f"Endpoint {outcome}", "value": round(base, 3)},
            {"label": "Target engagement (geometric; docks in resolved site)",
             "value": round(engagement_mod, 3)},
            {"label": f"× confidence {round(scale, 2)}", "value": round(final - subtotal, 3)},
        ]
        if druglike:
            components.append(
                {"label": "Drug-likeness flag (informational, not priced)", "value": 0.0}
            )
    else:
        components = [
            {"label": f"Endpoint {outcome} — no call", "value": 0.0},
            {
                "label": "Physics is a modifier on a readout, not a signal on its own",
                "value": 0.0,
            },
        ]

    return {
        "outcome": outcome,
        "sim_available": True,
        "outcome_base": base,
        "engagement_modifier": engagement_mod,
        "binding_engagement": engagement,
        "druglikeness_flag": druglike,
        "subtotal": subtotal,
        "confidence_scale": scale,
        "final": final,
        "components": components,
    }


def assess(
    event: dict[str, Any],
    sim: dict[str, Any] | None,
    sponsor_ticker: str | None,
    sponsor_name: str,
    competitors: list[dict[str, Any]],
    *,
    threshold: float = 0.10,
) -> dict[str, Any]:
    """Produce price calls + commentary for the sponsor and competitors."""
    delta = pos_delta(event, sim)
    magnitude = _magnitude(abs(delta))
    direction = _direction(delta)

    price_calls: list[dict[str, Any]] = []
    if sponsor_ticker:
        price_calls.append(
            {
                "ticker": sponsor_ticker,
                "name": sponsor_name,
                "role": "sponsor",
                "direction": direction,
                "magnitude": magnitude,
                "rationale": _sponsor_rationale(event, sim, delta),
            }
        )

    # Competitors typically move opposite the sponsor on a differentiated readout,
    # one magnitude bucket softer (second-order effect).
    comp_direction = _invert(direction)
    comp_magnitude = _soften(magnitude)
    for comp in competitors:
        price_calls.append(
            {
                "ticker": comp.get("ticker"),
                "name": comp.get("name"),
                "role": "competitor",
                "direction": comp_direction,
                "magnitude": comp_magnitude,
                "rationale": (
                    f"Second-order read-through: a {direction} move for "
                    f"{sponsor_name} on {event.get('target', 'the target')} "
                    f"typically implies a {comp_direction} move for rivals."
                ),
            }
        )

    return {
        "pos_delta": round(delta, 3),
        "market_moving": abs(delta) >= threshold,
        "price_calls": price_calls,
        "commentary": _commentary(event, sim, delta, price_calls),
    }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _clamp(x: float) -> float:
    return max(-1.0, min(1.0, x))


def _magnitude(mag: float) -> str:
    if mag >= _STRONG:
        return "strong"
    if mag >= _MODERATE:
        return "moderate"
    if mag >= _SLIGHT:
        return "slight"
    return "flat"


def _direction(delta: float) -> str:
    if delta > _SLIGHT:
        return "up"
    if delta < -_SLIGHT:
        return "down"
    return "flat"


def _invert(direction: str) -> str:
    return {"up": "down", "down": "up"}.get(direction, "flat")


def _soften(magnitude: str) -> str:
    return {"strong": "moderate", "moderate": "slight", "slight": "flat"}.get(
        magnitude, "flat"
    )


def _sponsor_rationale(event: dict[str, Any], sim: dict[str, Any] | None, delta: float) -> str:
    outcome = event.get("endpoint_outcome", "unknown")
    parts = [f"Trial {event.get('nct_id', '')} endpoint {outcome}."]
    if sim and not sim.get("error"):
        dg = sim.get("binding_affinity_kcal_mol")
        engagement = sim.get("binding_engagement")
        if dg is not None:
            sd = sim.get("binding_affinity_sd_kcal_mol")
            n = sim.get("replicates")
            dg_txt = f"{dg}" if sd is None else f"{dg}±{sd} (n={n})"
            parts.append(
                f"Docking score ΔG {dg_txt} kcal/mol (relative, size-confounded — "
                f"not an affinity)."
            )
        if engagement is not None:
            parts.append(f"Target engagement: {engagement} (geometry, not strength).")
        if sim.get("druglikeness_flag"):
            parts.append(
                "Drug-likeness flag (≥2 Lipinski violations) — informational, "
                "predicts oral absorption, not toxicity; not priced into the call."
            )
    else:
        parts.append("Simulation unavailable; call based on the readout alone.")
    parts.append(f"PoS delta {delta:+.2f}.")
    return " ".join(parts)


def _commentary(
    event: dict[str, Any],
    sim: dict[str, Any] | None,
    delta: float,
    price_calls: list[dict[str, Any]],
) -> str:
    arrow = {"up": "▲", "down": "▼", "flat": "▬"}
    lines = [
        f"Trial {event.get('nct_id', '')} — {event.get('sponsor', '')} "
        f"({event.get('drug', '')} / {event.get('target', '')}): "
        f"endpoint {event.get('endpoint_outcome', 'unknown')}.",
        f"Modelled probability-of-success delta: {delta:+.2f}.",
    ]
    for call in price_calls:
        lines.append(
            f"  {arrow.get(call['direction'], '?')} {call['ticker']} "
            f"({call['name']}, {call['role']}): {call['direction']} / "
            f"{call['magnitude']}"
        )
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)

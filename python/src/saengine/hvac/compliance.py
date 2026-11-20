"""Building envelope compliance checks against the code pack limits.

Checks wall U-value, roof U-value, glazing U-value, overall window-to-wall ratio (WWR), and
glazing SHGC (from the pack's ``shgcByWwr`` table, BNBC 2020 Part 8 Table 8.2.9(a) / Part 3
Table 3.4.2, and ASHRAE 90.1 / ECBC prescriptive limits marked 'to be checked').
"""

from __future__ import annotations

from typing import Any

from saengine.hvac import tables as T
from saengine.hvac.constructions import EnvelopeChoice
from saengine.hvac.geometry import ThermalZone


def building_wwr(zones: list[ThermalZone]) -> dict[str, Any]:
    """Gross exterior wall area [m²], total window area [m²], overall WWR (0-1), and per-facade
    breakdown (N, E, S, W) across all thermal zones."""
    wall_area = 0.0
    window_area = 0.0
    by_facade: dict[str, dict[str, float]] = {
        f: {"wallArea": 0.0, "windowArea": 0.0, "wwr": 0.0} for f in ("N", "E", "S", "W")
    }
    for zone in zones:
        for s in zone.surfaces:
            if s.kind != "Wall" or s.boundary != "Outdoors":
                continue
            w_area = sum(w.area for w in s.windows)
            wall_area += s.area
            window_area += w_area
            if s.facade in by_facade:
                by_facade[s.facade]["wallArea"] += s.area
                by_facade[s.facade]["windowArea"] += w_area
    for row in by_facade.values():
        row["wwr"] = row["windowArea"] / row["wallArea"] if row["wallArea"] > 0 else 0.0
    wwr = window_area / wall_area if wall_area > 0 else 0.0
    return {
        "wallArea": wall_area,
        "windowArea": window_area,
        "wwr": wwr,
        "byFacade": by_facade,
    }


def check_envelope_compliance(
    envelope: EnvelopeChoice,
    zones: list[ThermalZone],
    limits: Any = None,
) -> dict[str, Any]:
    """Check envelope U-values, WWR and SHGC against ``limits`` (defaults to
    :func:`saengine.hvac.tables.envelope_limits`). Returns a structured pass/fail report."""
    lim = limits if limits is not None else T.envelope_limits()
    wwr_info = building_wwr(zones)
    wwr = float(wwr_info["wwr"])
    try:
        shgc_max = float(T.shgc_limit(wwr)) if wwr > 0 else float(lim.shgcMaxDefault)
        shgc_ref = T.PAGES.get("8.2.9a", "BNBC 2020 Table 8.2.9(a) / Part 3 Table 3.4.2")
    except Exception:  # noqa: BLE001 - fallback when code context lacks shgcByWwr
        shgc_max = float(lim.shgcMaxDefault)
        shgc_ref = getattr(lim, "reference", "to be checked")
    ref = getattr(lim, "reference", "ASHRAE 90.1 Table 5.5-1 / ECBC (to be checked)")

    checks = [
        {
            "parameter": "uWall",
            "label": "Exterior wall U-value",
            "actual": round(float(envelope.uWall), 3),
            "limit": float(lim.uWallMax),
            "unit": "W/m²K",
            "passed": float(envelope.uWall) <= float(lim.uWallMax) + 1e-9,
            "reference": ref,
        },
        {
            "parameter": "uRoof",
            "label": "Roof U-value",
            "actual": round(float(envelope.uRoof), 3),
            "limit": float(lim.uRoofMax),
            "unit": "W/m²K",
            "passed": float(envelope.uRoof) <= float(lim.uRoofMax) + 1e-9,
            "reference": ref,
        },
        {
            "parameter": "uGlazing",
            "label": "Glazing U-value",
            "actual": round(float(envelope.uGlazing), 3),
            "limit": float(lim.uGlazingMax),
            "unit": "W/m²K",
            "passed": float(envelope.uGlazing) <= float(lim.uGlazingMax) + 1e-9,
            "reference": ref,
        },
        {
            "parameter": "wwr",
            "label": "Window-to-wall ratio (WWR)",
            "actual": round(wwr, 4),
            "limit": float(lim.wwrMax),
            "unit": "ratio",
            "passed": wwr <= float(lim.wwrMax) + 1e-9,
            "reference": ref,
        },
        {
            "parameter": "shgc",
            "label": "Glazing SHGC",
            "actual": round(float(envelope.shgc), 3),
            "limit": shgc_max,
            "unit": "-",
            "passed": float(envelope.shgc) <= shgc_max + 1e-9,
            "reference": shgc_ref,
        },
    ]
    return {
        "passed": all(c["passed"] for c in checks),
        "wwr": round(wwr, 4),
        "wallArea": round(wwr_info["wallArea"], 3),
        "windowArea": round(wwr_info["windowArea"], 3),
        "byFacade": wwr_info["byFacade"],
        "checks": checks,
        "reference": ref,
    }

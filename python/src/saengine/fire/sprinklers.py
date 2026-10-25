"""Sprinklers of a floor: heads, the design area and the pipe schedule (BNBC 2020 Part 4).

Each sprinkler covers at most the ceiling area of Table 4.4.7 (p333) at no more than its spacing;
the heads of a floor are the more of its area over that coverage and a square grid at the
spacing over the floor's plan extent (a layout estimate: the drawings place the heads). The pipe
sizes of the schedule method are those of Tables 4.4.5 (steel) and 4.4.6 (copper) by the heads a
pipe supplies; one riser serves at most 4850 m² of floor (light and ordinary) or 2325 m²
(extra). The design area and density for the hydraulic calculation are NFPA 13's (from memory,
to be checked): BNBC 2020 Part 4 asks for "the hydraulically calculated sprinkler demand"
(Sec 4.2.3.5) but gives no curve.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.fire import tables as T


def schedule_size(heads: int, hazard: str, material: str = "steel") -> int | None:
    """The smallest nominal size [mm] of Table 4.4.5 (steel, GI) or 4.4.6 (copper) that may
    supply ``heads`` sprinklers; None beyond the table."""
    column = {"light": 1, "ordinary": 2, "extra": 3}[T.family(hazard)]
    rows = T.COPPER_SCHEDULE if material == "copper" else T.STEEL_SCHEDULE
    for row in rows:
        limit = row[column]
        if limit is None or heads <= limit:
            return int(row[0])
    return None


def coverage(hazard: str, ceiling: str) -> tuple[float, float]:
    """Table 4.4.7: protected area [m²] and maximum spacing [m] of one sprinkler."""
    return T.COVERAGE.get(ceiling, T.COVERAGE["beams"])[T.family(hazard)]


def floor_sprinklers(
    area: float,
    hazard: str,
    ceiling: str = "beams",
    extent: tuple[float, float] | None = None,
    material: str = "steel",
) -> dict[str, Any]:
    """The sprinklers of a floor of ``area`` m² whose plan extent is ``extent`` (x, y) [m]:
    heads, their spacing, the design area and its heads, the per-head and total design flows,
    the risers the floor needs and the schedule size of the floor main."""
    cover, spacing = coverage(hazard, ceiling)
    side = min(spacing, math.sqrt(cover))
    by_area = math.ceil(area / cover - 1e-9) if area > 0 else 0
    by_grid = 0
    if extent and extent[0] > 0 and extent[1] > 0:
        grid = math.ceil(extent[0] / side - 1e-9) * math.ceil(extent[1] / side - 1e-9)
        # the grid over the extent, in the share of it the floor covers
        by_grid = math.ceil(grid * min(1.0, area / (extent[0] * extent[1])) - 1e-9)
    heads = max(by_area, by_grid)
    per_head = area / heads if heads else cover
    density, design = T.DENSITY_AREA[hazard]
    design_area = min(design, area)
    design_heads = max(1, math.ceil(design_area / per_head - 1e-9)) if heads else 0
    k_min = T.K_FACTOR * math.sqrt(T.MIN_HEAD_PRESSURE / 100.0)
    q_head = max(density * per_head, k_min)
    risers = max(1, math.ceil(area / T.RISER_FLOOR_AREA[T.family(hazard)] - 1e-9))
    main = schedule_size(heads, hazard, material) if heads else None
    length = T.DESIGN_AREA_LENGTH * math.sqrt(design_area) if design_area > 0 else 0.0
    per_branch = max(1, math.ceil(length / side - 1e-9)) if heads else 0
    branches = math.ceil(design_heads / per_branch - 1e-9) if per_branch else 0
    return {
        "hazard": hazard,
        "area": round(area, 1),
        "coverage": cover,
        "maxSpacing": spacing,
        "spacing": round(side, 2),
        "heads": heads,
        "perHead": round(per_head, 2),
        "density": density,
        "designArea": round(design_area, 1),
        "designHeads": design_heads,
        "headFlow": round(q_head, 1),
        "demand": round(density * design_area, 1),
        "risersNeeded": risers,
        "mainSize": main,
        "branches": branches,
        "headsPerBranch": per_branch,
        "notes": [
            (
                f"{heads} heads: {area:.0f} m² at most {cover:g} m² a head, {spacing:g} m apart "
                f"({T.cite('4.4.7')}, {T.HAZARD_LABELS[hazard]}); a layout estimate"
            ),
            (
                f"design area {design_area:.0f} m² at {density:g} mm/min (NFPA 13 density/area, "
                f"{T.MEMORY}): {design_heads} heads of at least {q_head:.0f} l/min (K{T.K_FACTOR:g} "
                f"at {T.MIN_HEAD_PRESSURE / 100:g} bar least, {T.MEMORY})"
            ),
        ],
    }


def hose_allowance(hazard: str) -> tuple[float, int]:
    """NFPA 13 inside and outside hose allowance [l/min] and the duration [min] (from memory)."""
    return T.HOSE_ALLOWANCE[T.family(hazard)]


def hand_demand(hazard: str, design_area: float | None = None) -> dict[str, Any]:
    """The sprinkler demand by hand: density x design area + hose allowance (NFPA 13, from
    memory)."""
    density, area = T.DENSITY_AREA[hazard]
    area = area if design_area is None else design_area
    hose, minutes = hose_allowance(hazard)
    sprinklers = density * area
    return {
        "density": density,
        "area": area,
        "sprinklers": sprinklers,
        "hose": hose,
        "total": sprinklers + hose,
        "duration": minutes,
        "note": (
            f"{density:g} mm/min x {area:g} m² = {sprinklers:.0f} l/min + hose {hose:g} l/min = "
            f"{sprinklers + hose:.0f} l/min for {minutes} min (NFPA 13, {T.MEMORY})"
        ),
    }

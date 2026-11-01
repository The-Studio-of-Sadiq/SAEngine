"""The earth and water pressure on the building's basement walls: load case H of the analysis
model (:mod:`saengine.fem.derive`).

A wall of 6 BIM is loaded when its wall type is a basement wall (``basement`` in 04 Objects)
or a retaining wall of 9 Substructure names it (``wall``), and ``earthPressure.basementWalls``
is on. The pressure is at rest (a wall propped by the floors cannot yield), from the one
earth-pressure engine (:mod:`saengine.substructure.earth_pressure`) on the soil of 1 Soil
Report at the wall's middle: ``K0 (σ'v + q) + u`` below the finished ground (the code pack's
``retainingWall.pressure`` clause). It pushes the wall away from the soil: the soil is on the
side of the wall
away from the building's middle, or on the retaining wall's ``soilSide``.

Units: mm for levels and positions, kPa returned.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from saengine.substructure.earth_pressure import soil_column


@dataclass
class WallPressure:
    """The pressure on one wall of 6 BIM: the plan direction it pushes the wall in (a unit
    3-vector, away from the soil) and the pressure [kPa] at a level [mm]."""

    wall: str
    direction: np.ndarray
    pressure: Callable[[float], float]
    source: str


def basement_pressures(
    building: Any,
    objects: Any,
    settings: Any,
    substructure: Any = None,
    soil_text: str | None = None,
) -> tuple[list[WallPressure], list[str]]:
    """The :class:`WallPressure` of each basement wall of ``building`` and notes."""
    from saengine.library.bim import ColumnElement, WallElement
    from saengine.library.substructure import EarthPressure
    from saengine.substructure.piles import profiles_of

    options = substructure.earthPressure if substructure is not None else EarthPressure()
    if not options.basementWalls:
        return [], []
    types = {o.id: o for o in objects.objects}
    named = {r.wall: r for r in (substructure.retainingWalls if substructure else []) if r.wall}
    walls = [
        e
        for e in building.elements
        if isinstance(e, WallElement)
        and (e.id in named or getattr(types.get(e.type), "basement", False))
    ]
    if not walls:
        return [], []
    ground = settings.foundation.groundLevel
    walls = [w for w in walls if min(w.bottom, w.top) < ground]
    if not walls:
        return [], []
    points = [
        np.array(e.position[:2], float) for e in building.elements if isinstance(e, ColumnElement)
    ]
    points += [(np.array(w.start, float) + np.array(w.end, float)) / 2 for w in walls]
    middle = np.mean(points, axis=0)
    profiles = profiles_of(soil_text)[0]
    found: list[WallPressure] = []
    sources: set[str] = set()
    for wall in walls:
        start, end = np.array(wall.start, float), np.array(wall.end, float)
        along = end - start
        if np.linalg.norm(along) < 1:
            continue
        along /= np.linalg.norm(along)
        left = np.array([-along[1], along[0]])
        own = named.get(wall.id)
        if own is not None:
            path = np.array(own.path, float)
            run = path[-1] - path[0]
            soil_side = np.array([-run[1], run[0]])
            if own.soilSide == "right":
                soil_side = -soil_side
            to_soil = left if float(np.dot(left, soil_side)) >= 0 else -left
        else:
            centre = (start + end) / 2
            to_soil = left if float(np.dot(left, centre - middle)) >= 0 else -left
        x, y = ((start + end) / 2).tolist()
        if own is not None:
            backfill = own.backfill.model_dump() if own.backfill is not None else None
            soil = soil_column(
                profiles, x, y, own.designWaterTable, own.surcharge, options.k0Cohesive, backfill
            )
            level0 = own.retainedLevel if own.retainedLevel is not None else ground
            water = not own.drained
        else:
            soil = soil_column(
                profiles, x, y, options.designWaterTable, options.surcharge, options.k0Cohesive
            )
            level0 = ground
            water = True

        def pressure(
            level: float, soil: Any = soil, level0: float = level0, water: bool = water
        ) -> float:
            depth = (level0 - level) * 1e-3
            return soil.pressure(depth, "atRest", water=water)["total"] if depth > 0 else 0.0

        direction = np.array([-to_soil[0], -to_soil[1], 0.0])
        found.append(WallPressure(wall.id, direction, pressure, soil.source))
        sources.add(soil.source)
    notes = []
    if found:
        notes.append(
            f"H: earth and water pressure at rest on the basement walls "
            f"{', '.join(w.wall for w in found)} ({_pressure_clause()}soil: "
            f"{'; '.join(sorted(sources))})"
        )
    return found, notes


def _pressure_clause() -> str:
    """ "<clause>; " of the pack's earth and water pressure on basement walls ("" if none)."""
    from saengine.substructure.shallow_rules import cite

    clause = cite("retainingWall.pressure")
    return f"{clause}; " if clause else ""


def has_earth_pressure(building: Any, objects: Any, substructure: Any = None) -> bool:
    """Whether the building has a wall the case H loads (for the model's stamps)."""
    from saengine.library.bim import WallElement

    types = {o.id: o for o in objects.objects}
    named = {r.wall for r in (substructure.retainingWalls if substructure else []) if r.wall}
    return any(
        isinstance(e, WallElement)
        and (e.id in named or getattr(types.get(e.type), "basement", False))
        for e in building.elements
    )

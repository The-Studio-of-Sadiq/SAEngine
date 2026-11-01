"""Reduction of live loads by the code pack's rule (``liveReduction``).

**Floors.** Members with an influence area KLL AT of at least ``influenceMin`` may be designed
for the reduced live load L = L0 (a + b / √(KLL AT)), at least ``minOneFloor`` L0 for members
supporting one floor and ``minFloors`` L0 for members supporting two or more. Live loads over
``heavyLive``, and the ``twoFloorsOnly`` uses (passenger car garages), are not reduced, except
to ``heavyFactor`` on members supporting two or more floors; the ``notReduced`` uses (public
assembly) up to ``assemblyMax`` and the buildings of ``notReducedBuildings`` (a project flagged
as a cyclone shelter) are not reduced at all. Uses the pack marks ``reducible: false`` are not
reduced either.

**Roofs.** The ordinary roof live load (case Lr, the pack's ``roof.uses``) is reduced by
Lr = L0 R1 R2 within [``minimum``, ``maximum``]: R1 from the member's tributary area, R2 from the
roof slope (``analysis.roofSlope``, per cent; F = ``slopeF`` × slope). Special purpose roofs
(gardens, assembly) are not in ``roof.uses``: they stay unreduced here.

SAEngine applies the factor to the floor live load cases (L and the pattern arrangements LP1,
LP2, ...) and to the roof live load case Lr of each beam and column, in every combination,
before the checks:

- the tributary area AT of a member is the live load it carries over the live load intensity:
  a column's live axial force at its foot (all the floors above it), a beam's two end shears
  under L (Lr), divided by L0 of the floors (the largest area load in use, so AT is not
  overestimated) or of the roof;
- KLL (the pack's ``liveReduction.kll``): the interior column factor for interior columns (floor
  all round), else the corner column with a cantilever slab (the least, as the model does not
  say whether the edge slab cantilevers); the interior beam factor for beams with slabs on both
  sides, else "other";
- a member's design overwrite ``liveLoadReduction`` gives its factor instead.

The factor is listed on each member as a reported-only check. Every number and the clause text
come from the active code pack.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from saengine.codes import context as code_context

__all__ = [
    "LiveScope",
    "clause",
    "is_live_case",
    "is_roof_case",
    "member_factor",
    "reduced",
    "reduction",
    "roof_clause",
    "roof_member_factor",
    "roof_reduction",
]

#: The roof live load case.
ROOF_CASE = "Lr"


def is_live_case(case: str) -> bool:
    """The floor live load cases: L and the pattern arrangements LP1, LP2, ..."""
    return case == "L" or (case.startswith("LP") and case[2:].isdigit())


def is_roof_case(case: str) -> bool:
    """The roof live load case Lr."""
    return case == ROOF_CASE


def _table() -> Any:
    return code_context.pack_table("liveReduction")


def clause() -> str:
    """The floor reduction's clause, from the code pack."""
    return _table().source


def roof_clause() -> str:
    """The roof reduction's clause, from the code pack."""
    table = _table()
    return table.sources.get("roof", table.source).split(":")[0]


def __getattr__(name: str) -> Any:
    # ``CLAUSE`` (older callers): the pack's clause, read when asked.
    if name == "CLAUSE":
        return clause()
    raise AttributeError(name)


def reduction(kll: float, area: float, floors: int, scope: LiveScope) -> tuple[float, str]:
    """(L / L0, why) of a member with live load element factor ``kll``, tributary area
    ``area`` [m²] and ``floors`` supported, in a building of ``scope``."""
    table = _table()
    where = clause()
    if scope.building:
        return 1.0, f"{scope.building}: not reduced ({where})"
    if scope.assembly:
        return 1.0, f"assembly use: not reduced ({where})"
    if scope.heavy or scope.garage:
        what = f"live load over {table.heavyLive:g} kN/m²" if scope.heavy else "parking"
        share = round(100 * (1 - table.heavyFactor))
        if floors >= 2:
            return table.heavyFactor, (
                f"{what}: {share} % on members of two or more floors ({where})"
            )
        return 1.0, f"{what}: not reduced on members of one floor ({where})"
    influence = kll * area
    if influence < table.influenceMin:
        return 1.0, (
            f"KLL AT = {kll:g} × {area:.1f} = {influence:.1f} m² < {table.influenceMin:g} m²: "
            f"not reduced ({where})"
        )
    least = table.minFloors if floors >= 2 else table.minOneFloor
    factor = table.constant + table.coefficient / math.sqrt(influence)
    factor = min(max(factor, least), 1.0)
    return factor, (
        f"L / L0 = {table.constant:g} + {table.coefficient:g} / √(KLL AT) with KLL = {kll:g}, "
        f"AT = {area:.1f} m², {floors} floor{'s' if floors != 1 else ''}; at least {least:g} "
        f"({where})"
    )


def roof_reduction(
    area: float, live: float, slope: float = 0.0, rise: float | None = None
) -> tuple[float, str] | None:
    """(Lr / L0, why) of a roof member with tributary area ``area`` [m²] under the roof live
    load ``live`` [kN/m²], on a pitched roof of ``slope`` per cent (or an arch or dome of
    ``rise`` / span); None when the pack has no roof rule."""
    rule = getattr(_table(), "roof", None)
    if rule is None or live <= 0:
        return None
    if area <= rule.areaLow:
        r1 = 1.0
    elif area >= rule.areaHigh:
        r1 = rule.r1Min
    else:
        r1 = rule.r1Constant - rule.r1Coefficient * area
    f = rule.archF * rise if rise is not None else rule.slopeF * slope
    if f <= rule.riseLow:
        r2 = 1.0
    elif f >= rule.riseHigh:
        r2 = rule.r2Min
    else:
        r2 = rule.r2Constant - rule.r2Coefficient * f
    reduced_live = min(max(live * r1 * r2, rule.minimum), rule.maximum)
    # A roof load already below the least is not raised by the rule.
    reduced_live = min(reduced_live, live)
    factor = reduced_live / live
    return factor, (
        f"Lr = L0 R1 R2 = {live:g} × {r1:.3f} × {r2:.3f} = {live * r1 * r2:.3f} kN/m², within "
        f"[{rule.minimum:g}, {rule.maximum:g}]: Lr / L0 = {factor:.3f} with AT = {area:.1f} m², "
        f"F = {f:.2f} ({roof_clause()})"
    )


@dataclass
class LiveScope:
    """The building's floor live loads: the largest L0 [kN/m²] in use and whether an assembly,
    heavy or parking area is among them; ``building``: the project flag that forbids any
    reduction (cyclone shelter), empty when none; ``roof``: the roof live load L0 [kN/m²] the
    roof rule reduces (0 when the roof's use is not one it reduces)."""

    live: float
    assembly: bool = False
    heavy: bool = False
    garage: bool = False
    building: str = ""
    roof: float = 0.0

    @classmethod
    def of(cls, settings: Any) -> LiveScope:
        table = _table()
        uses = {}
        if code_context.current().has("areaLoads"):
            uses = code_context.pack_table("areaLoads").uses

        def is_roof(use: str) -> bool:
            row = uses.get(use)
            return bool(row and row.roof) or use in ("roof", "roofGarden")

        loads = [
            a for a in settings.areaLoads if not is_roof(a.use) and a.use not in ("stairs",)
        ] or list(settings.areaLoads)
        live = max((float(a.live) for a in loads), default=0.0)
        assembly_max = table.assemblyMax
        occupancy = getattr(settings, "occupancy", None)
        building = next(
            (flag for flag in table.notReducedBuildings if getattr(occupancy, flag, False)), ""
        )
        roof_rule = getattr(table, "roof", None)
        roof_load = next(
            (a for a in settings.areaLoads if a.id == getattr(settings, "roofLoad", None)), None
        )
        roof = (
            float(roof_load.live)
            if roof_rule is not None and roof_load is not None and roof_load.use in roof_rule.uses
            else 0.0
        )
        return cls(
            live=live,
            assembly=any(
                a.use in table.notReduced
                and (assembly_max is None or float(a.live) <= assembly_max + 1e-9)
                for a in loads
            )
            or any(a.use in uses and not uses[a.use].reducible for a in loads),
            heavy=live > table.heavyLive + 1e-9,
            garage=any(a.use in table.twoFloorsOnly for a in loads),
            building=building,
            roof=roof,
        )


def reduced(pieces: list[Any], factor: float, part: str = "live") -> list[Any]:
    """Copies of a member's pieces with their live load part (``part``: "live" the floor live
    load, "roof" the roof live load) scaled by ``factor``: each combination's forces less
    (1 - factor) times that part."""
    if factor >= 1.0:
        return pieces
    out = []
    for piece in pieces:
        parts = getattr(piece, part, None)
        if parts is None:
            out.append(piece)
            continue
        twin = copy.copy(piece)
        twin.forces = [
            np.asarray(f) - (1.0 - factor) * np.asarray(live) if live is not None else f
            for f, live in zip(piece.forces, parts, strict=False)
        ]
        if piece.sustained is not None:
            twin.sustained = list(piece.sustained)
        out.append(twin)
    return out


def _live_forces(service: dict[str, Any], piece: Any, case: str = "L") -> np.ndarray | None:
    found = (service.get("forces") or {}).get(case) or {}
    rows = found.get(piece.id)
    return None if rows is None else np.asarray(rows, dtype=float)


def _tributary(
    kind: str, pieces: list[Any], service: dict[str, Any], case: str, q: float
) -> float | None:
    """A member's tributary area [m²] under ``case`` of intensity ``q`` [N/m²]: a column's
    axial force at its foot, a beam's two end shears, over q."""
    rows = [(p, _live_forces(service, p, case)) for p in pieces]
    rows = [(p, r) for p, r in rows if r is not None and len(r)]
    if not rows or q <= 0:
        return None
    if kind == "column":
        piece, forces = min(rows, key=lambda pr: min(float(pr[0].start[2]), float(pr[0].end[2])))
        at_start = float(piece.start[2]) <= float(piece.end[2])
        return abs(float(forces[0 if at_start else -1][0])) / q
    first, last = rows[0][1], rows[-1][1]
    return float(np.abs(first[0][1:3]).max() + np.abs(last[-1][1:3]).max()) / q


def roof_member_factor(
    kind: str, pieces: list[Any], service: dict[str, Any], scope: LiveScope, slope: float = 0.0
) -> tuple[float, str] | None:
    """(Lr / L0, why) of a beam or column from its roof live load under the case Lr, or None
    when it cannot be worked out (no Lr case, a roof use the rule does not reduce)."""
    if scope.roof <= 0 or not pieces:
        return None
    if scope.building:
        return 1.0, f"{scope.building}: not reduced ({clause()})"
    area = _tributary(kind, pieces, service, ROOF_CASE, scope.roof * 1e3)
    if area is None:
        return None
    return roof_reduction(area, scope.roof, slope)


def member_factor(
    element: Any,
    kind: str,
    pieces: list[Any],
    service: dict[str, Any],
    building: Any,
    scope: LiveScope,
    framing: Any = None,
    width: float = 0.0,
) -> tuple[float, str] | None:
    """(L / L0, why) of a beam or column from its live load under the case L, or None when it
    cannot be worked out (no L case, no live load)."""
    if scope.live <= 0 or not pieces:
        return None
    table = _table()
    area = _tributary(kind, pieces, service, "L", scope.live * 1e3)
    if area is None:
        return None
    if kind == "column":
        top = float(getattr(element, "top", 0.0))
        floors = sum(1 for s in building.stories if float(s.elevation) >= top - 1.0)
        kll = (
            table.kll.interiorColumn
            if _interior(element, building)
            else (table.kll.cornerColumnCantilever)
        )
        return reduction(kll, area, max(floors, 1), scope)
    sides = framing.slab_beside(element, width)[1] if framing is not None else 0
    kll = table.kll.interiorBeam if sides >= 2 else table.kll.other
    return reduction(kll, area, 1, scope)


def _interior(column: Any, building: Any, reach: float = 1000.0) -> bool:
    """Whether the floor at a column's top lies all round it (±``reach`` mm in x and y)."""
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union

    from saengine.library.bim import SlabElement

    top = float(column.top)
    slabs = [
        Polygon([(float(x), float(y)) for x, y in e.boundary])
        for e in building.elements
        if isinstance(e, SlabElement) and abs(float(e.elevation) - top) <= 1.0
    ]
    slabs = [s for s in slabs if s.is_valid and s.area > 0]
    if not slabs:
        return False
    floor = unary_union(slabs)
    x, y = float(column.position[0]), float(column.position[1])
    return all(
        floor.covers(Point(x + dx, y + dy))
        for dx, dy in ((reach, 0), (-reach, 0), (0, reach), (0, -reach))
    )

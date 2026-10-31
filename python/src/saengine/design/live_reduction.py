"""Reduction of floor live loads (BNBC 2020 Part 6 Sec 2.3.13).

Members with an influence area KLL AT of 37.16 m² or more may be designed for the reduced
live load L = L0 (0.25 + 4.57 / √(KLL AT)), at least 0.5 L0 for members supporting one floor
and 0.4 L0 for members supporting two or more. Live loads over 4.79 kN/m², and passenger car
garages, are not reduced, except by 20 % on members supporting two or more floors; assembly
uses are not reduced. Roof live loads (Lr) are a separate case and never reduced here.

SAEngine applies the factor to the floor live load cases (L and the pattern arrangements LP1,
LP2, ...) of each beam and column, in every combination, before the checks:

- the tributary area AT of a member is the live load it carries over the floor live load
  intensity: a column's live axial force at its foot (all the floors above it), a beam's two
  end shears under L, divided by L0 of the floors (the largest area load in use, so AT is not
  overestimated);
- KLL (the pack's ``liveReduction.kll``): 4 for interior columns (floor all round), else 2 (a
  corner column with a cantilever slab, the least, as the model does not say whether the edge
  slab cantilevers); 2 for beams with slabs on both sides, else 1;
- a member's design overwrite ``liveLoadReduction`` gives its factor instead.

The factor is listed on each member as a reported-only check.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from saengine.codes import context as code_context

__all__ = ["CLAUSE", "LiveScope", "is_live_case", "member_factor", "reduced", "reduction"]

CLAUSE = "BNBC 2020 Part 6 Sec 2.3.13"


def is_live_case(case: str) -> bool:
    """The floor live load cases: L and the pattern arrangements LP1, LP2, ..."""
    return case == "L" or (case.startswith("LP") and case[2:].isdigit())


def _table() -> Any:
    return code_context.pack_table("liveReduction")


def reduction(kll: float, area: float, floors: int, scope: LiveScope) -> tuple[float, str]:
    """(L / L0, why) of a member with live load element factor ``kll``, tributary area
    ``area`` [m²] and ``floors`` supported, in a building of ``scope``."""
    table = _table()
    if scope.assembly:
        return 1.0, f"assembly use: not reduced ({CLAUSE})"
    if scope.heavy or scope.garage:
        what = "live load over 4.79 kN/m²" if scope.heavy else "parking"
        if floors >= 2:
            return table.heavyFactor, f"{what}: 20 % on members of two or more floors ({CLAUSE})"
        return 1.0, f"{what}: not reduced on members of one floor ({CLAUSE})"
    influence = kll * area
    if influence < table.influenceMin:
        return 1.0, (
            f"KLL AT = {kll:g} × {area:.1f} = {influence:.1f} m² < {table.influenceMin:g} m²: "
            f"not reduced ({CLAUSE})"
        )
    least = table.minFloors if floors >= 2 else table.minOneFloor
    factor = table.constant + table.coefficient / math.sqrt(influence)
    factor = min(max(factor, least), 1.0)
    return factor, (
        f"L / L0 = {table.constant:g} + {table.coefficient:g} / √(KLL AT) with KLL = {kll:g}, "
        f"AT = {area:.1f} m², {floors} floor{'s' if floors != 1 else ''}; at least {least:g} "
        f"({CLAUSE})"
    )


@dataclass
class LiveScope:
    """The building's floor live loads: the largest L0 [kN/m²] in use and whether an assembly,
    heavy (over 4.79 kN/m²) or parking area is among them."""

    live: float
    assembly: bool = False
    heavy: bool = False
    garage: bool = False

    @classmethod
    def of(cls, settings: Any) -> LiveScope:
        table = _table()
        loads = [
            a for a in settings.areaLoads if a.use not in ("roof", "roofGarden", "stairs")
        ] or list(settings.areaLoads)
        live = max((float(a.live) for a in loads), default=0.0)
        return cls(
            live=live,
            assembly=any(a.use in table.notReduced for a in loads),
            heavy=live > table.heavyLive,
            garage=any(a.use in table.twoFloorsOnly for a in loads),
        )


def reduced(pieces: list[Any], factor: float) -> list[Any]:
    """Copies of a member's pieces with their live load part scaled by ``factor``: each
    combination's forces less (1 - factor) times its live part."""
    if factor >= 1.0:
        return pieces
    out = []
    for piece in pieces:
        if piece.live is None:
            out.append(piece)
            continue
        twin = copy.copy(piece)
        twin.forces = [
            np.asarray(f) - (1.0 - factor) * np.asarray(live) if live is not None else f
            for f, live in zip(piece.forces, piece.live, strict=False)
        ]
        if piece.sustained is not None:
            twin.sustained = list(piece.sustained)
        out.append(twin)
    return out


def _live_forces(service: dict[str, Any], piece: Any) -> np.ndarray | None:
    found = (service.get("forces") or {}).get("L") or {}
    rows = found.get(piece.id)
    return None if rows is None else np.asarray(rows, dtype=float)


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
    rows = [(p, _live_forces(service, p)) for p in pieces]
    rows = [(p, r) for p, r in rows if r is not None and len(r)]
    if not rows:
        return None
    q = scope.live * 1e3  # N/m²
    if kind == "column":
        foot = min(rows, key=lambda pr: min(float(pr[0].start[2]), float(pr[0].end[2])))
        piece, forces = foot
        at_start = float(piece.start[2]) <= float(piece.end[2])
        axial = abs(float(forces[0 if at_start else -1][0]))
        area = axial / q
        top = float(getattr(element, "top", 0.0))
        floors = sum(1 for s in building.stories if float(s.elevation) >= top - 1.0)
        kll = (
            table.kll.interiorColumn
            if _interior(element, building)
            else (table.kll.cornerColumnCantilever)
        )
        return reduction(kll, area, max(floors, 1), scope)
    first, last = rows[0][1], rows[-1][1]
    shear = float(np.abs(first[0][1:3]).max() + np.abs(last[-1][1:3]).max())
    area = shear / q
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

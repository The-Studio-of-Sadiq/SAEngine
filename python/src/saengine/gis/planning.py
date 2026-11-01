"""Planning compliance of the plot (1 Soil Report, site): FAR, maximum ground coverage (MGC),
setbacks and the area statement.

The rules are the code pack's ``planning`` table: for BNBC 2020 the planning authority's rules
that BNBC Part 3 Chapter 1 defers to, for Dhaka (RAJUK) the Imarat Nirman Bidhimala 2008
(Rule 46 and Table 2: setbacks; Rule 50: ground coverage; Rule 51 and Tables 3(A)-3(F): FAR and
MGC by use, plot size and road width). The table is pack data: another authority's rules are
another pack's table, and a project may edit its copy.

Beside the authority's rules the table's ``buildingCode`` block holds the building code's own
site rules (for BNBC 2020 Part 3 Chapter 1): the plinth and formation levels, the distances to
overhead electric lines, the least open and unpaved area, the fallback open spaces where no
authority's rules apply, the height by road width and construction type (the project setting
``construction.constructionType``), the open spaces of a building of unlimited height or FAR and
the parking floors left out of FAR. Which of them bind also under the authority's rules is pack
data (``withAuthority``); the others are shown as advisory there.

- :func:`permitted`: the FAR and MGC a plot of ``area`` on a road ``road`` wide may have;
- :func:`required_setbacks`: the setbacks Table 2 asks for (and the road-centre rule);
- :func:`code_setbacks`, :func:`height_limit`, :func:`overhead_clearance`,
  :func:`open_area_percent`, :func:`unlimited_open_spaces`: the building code's rules;
- :func:`floor_areas`: the storeys' floor areas and the ground coverage of the building model;
- :func:`check`: the area statement and the checks of the site's plot and building.

Units: areas in m², road widths and heights in m unless named otherwise (the plot is in mm).
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from saengine.codes import context as code_context

if TYPE_CHECKING:
    from saengine.library.soil import Site

#: A FAR "NR" (not restricted) is printed so and compared as infinite.
UNRESTRICTED = math.inf


def rules() -> Any:
    """The planning table of the pack in force (BNBC 2020's when the pack has none)."""
    return code_context.pack_table("planning")


def _clause(key: str) -> str:
    """The clause of the authority's rules the table names for ``key`` (coverage, far,
    envelope); empty when it names none."""
    return rules().clauses.get(key, "")


def band(area: float) -> int:
    """The plot-size row of ``area`` [m²] in the tables (0 for the smallest)."""
    bands = rules().plotBands
    for i, b in enumerate(bands):
        if b.maxArea is None or area <= b.maxArea + 1e-9:
            return i
    return len(bands) - 1


def band_label(index: int) -> str:
    """'up to 134 m² (2 katha)', 'above 134 m² up to 201 m² (2-3 katha)', 'above 1340 m²'."""
    bands = rules().plotBands
    b = bands[index]
    lo = bands[index - 1] if index else None
    if b.maxArea is None:
        return f"above {lo.maxArea:g} m² ({lo.maxKatha:g} katha)"
    if lo is None:
        return f"up to {b.maxArea:g} m² ({b.maxKatha:g} katha)"
    return f"above {lo.maxArea:g} up to {b.maxArea:g} m² ({lo.maxKatha:g}-{b.maxKatha:g} katha)"


def _far_text(far: float | None) -> str:
    return "NR (not restricted)" if far is None or math.isinf(far) else f"{far:.2f}"


def permitted(use: str, area: float, road: float) -> dict[str, Any]:
    """The largest FAR and MGC [%] of a plot of ``area`` m² for ``use`` on a road ``road`` m
    wide: ``{far (inf: not restricted), mgc, allowed, rule, row, notes}``.

    The plot's own row of the use's table applies when the road is at least as wide as the row
    asks; on a narrower road (6 m or more) the largest plot-size row the road qualifies for (a
    SAEngine reading of Rule 51: the table pairs each size with the road it needs); below 6 m
    Rule 51(9) and (10). A wider road gives the rows "any size" of 18 and 24 m roads where they
    are higher, and Rule 51(11) adds 0.05 to the FAR for every 0.30 m of road above the row's
    width (6 to 24 m), up to the next row's FAR."""
    table = rules()
    spec = table.uses.get(use)
    if spec is None:
        return {
            "allowed": False,
            "far": 0.0,
            "mgc": 0.0,
            "rule": "",
            "row": None,
            "notes": [f"Unknown use '{use}': one of {', '.join(table.uses)}."],
        }
    notes: list[str] = []
    here = band(area)
    own = spec.rows[here]
    if own is None:
        smallest = next(i for i, r in enumerate(spec.rows) if r is not None)
        return {
            "allowed": False,
            "far": 0.0,
            "mgc": 0.0,
            "rule": f"{_clause('far')}, {spec.table}",
            "row": band_label(here),
            "notes": [
                (
                    f"{spec.name} is not permitted on a plot {band_label(here)}: from "
                    f"{band_label(smallest)} up ({spec.table})."
                )
            ],
        }
    if road < 6.0 - 1e-9:
        for narrow in table.narrowRoads:
            if narrow.minRoad - 1e-9 <= road <= narrow.maxRoad + 1e-9:
                return {
                    "allowed": True,
                    "far": min(narrow.far, own.far if own.far is not None else UNRESTRICTED),
                    "mgc": narrow.mgc,
                    "rule": narrow.rule,
                    "row": f"road {narrow.minRoad:g}-{narrow.maxRoad:g} m",
                    "notes": [
                        (
                            f"Road {road:g} m: {narrow.rule} (FAR {narrow.far:g}, MGC "
                            f"{narrow.mgc:g} %)."
                        )
                    ],
                }
        return {
            "allowed": False,
            "far": 0.0,
            "mgc": 0.0,
            "rule": table.narrowRoads[-1].rule if table.narrowRoads else _clause("far"),
            "row": None,
            "notes": [
                (
                    f"Road {road:g} m: no FAR is given for a road narrower than "
                    f"{min(n.minRoad for n in table.narrowRoads):g} m."
                )
            ],
        }
    # The rows the plot and the road both qualify for: its own size and smaller ones, and the
    # "any size" rows of the wide roads.
    candidates: list[tuple[float, float, float, str]] = []  # (far, mgc, road, label)
    for i in range(here, -1, -1):
        row = spec.rows[i]
        if row is not None and row.road <= road + 1e-9:
            far = UNRESTRICTED if row.far is None else row.far
            candidates.append((far, row.mgc, row.road, band_label(i)))
            if i != here:
                notes.append(
                    f"The road ({road:g} m) is narrower than the {own.road:g} m a plot "
                    f"{band_label(here)} needs: the row of a plot {band_label(i)} applies "
                    f"(SAEngine reading of {_clause('far')})."
                )
            break
    for wide in spec.wideRoads:
        if wide.road <= road + 1e-9:
            far = UNRESTRICTED if wide.far is None else wide.far
            candidates.append((far, wide.mgc, wide.road, f"any plot size, road {wide.road:g} m"))
    if not candidates:
        return {
            "allowed": False,
            "far": 0.0,
            "mgc": 0.0,
            "rule": f"{_clause('far')}, {spec.table}",
            "row": None,
            "notes": [f"No row of {spec.table} applies to a {road:g} m road."],
        }
    far, mgc, row_road, label = max(candidates, key=lambda c: (c[0], c[2]))
    rule = f"{_clause('far')}, {spec.table}"
    inc = table.roadIncrement
    if not math.isinf(far) and road > row_road + 1e-9 and inc.fromRoad <= row_road < inc.toRoad:
        steps = math.floor((min(road, inc.toRoad) - row_road) / inc.step + 1e-9)
        if steps > 0:
            wider = [
                (UNRESTRICTED if r.far is None else r.far)
                for r in [*(x for x in spec.rows if x is not None), *spec.wideRoads]
                if r.road > row_road + 1e-9 and (r.far is None or r.far > far)
            ]
            cap = min(wider, default=UNRESTRICTED)
            raised = min(far + steps * inc.far, cap)
            if raised > far:
                notes.append(
                    f"{inc.rule}: road {road:g} m is {steps} × {inc.step:g} m above the row's "
                    f"{row_road:g} m: FAR + {steps * inc.far:.2f}"
                    + (f", up to the next row's {cap:.2f}" if raised == cap else "")
                )
                far, rule = raised, f"{rule}, {inc.rule}"
    return {"allowed": True, "far": far, "mgc": mgc, "rule": rule, "row": label, "notes": notes}


def required_setbacks(
    area: float, height: float | None, storeys: int | None, road: float | None
) -> dict[str, Any]:
    """The least setbacks [m] of Table 2 for a plot of ``area`` m² (the high-rise row above
    33 m or 10 storeys), the front at least the road-centre distance of Rule 46(3):
    ``{front, rear, side, rule, notes}``."""
    table = rules().setbacks
    notes: list[str] = []
    high = (height is not None and height > table.highRiseHeight + 1e-9) or (
        storeys is not None and storeys > table.highRiseStoreys
    )
    row = table.highRise if high else table.rows[band(area)]
    if high:
        notes.append(
            f"Above {table.highRiseHeight:g} m or {table.highRiseStoreys} storeys: the "
            "high-rise row of Table 2."
        )
    front = row.front
    centre = rules().roadCentre
    if road is not None and road > 0:
        from_centre = max(centre.distance - road / 2, centre.boundary)
        if from_centre > front + 1e-9:
            notes.append(
                f"{centre.rule}: at least {centre.distance:g} m from the road's centre "
                f"({road:g} m road): {from_centre:.2f} m from the boundary."
            )
            front = from_centre
    return {"front": front, "rear": row.rear, "side": row.side, "rule": table.rule, "notes": notes}


# ─────────────────────────── the building code's own site rules (B23) ───────────────────────────
# The pack's ``planning.buildingCode`` (for BNBC 2020: Part 3 Chapter 1): the plinth and formation
# levels, overhead lines, the open area, the fallback setbacks, the height by road width and
# construction type, and the parking floors left out of FAR.


def code_rules() -> Any:
    """The building code's site rules of the pack in force; None when the pack has none."""
    return rules().buildingCode


def _code_rule(rule: str) -> str:
    code = code_rules()
    return f"{code.name} {rule}".strip() if code is not None and rule else rule


def occupancy(use: str) -> str | None:
    """The building code's occupancy group of the authority's use ``use`` (None: unknown)."""
    code = code_rules()
    return None if code is None else code.occupancies.get(use)


def _tall(setbacks: Any, height: float | None, storeys: int | None) -> bool:
    return (height is not None and height > setbacks.tallHeight + 1e-9) or (
        storeys is not None and storeys > setbacks.tallStoreys
    )


def code_setbacks(
    use: str,
    area: float,
    height: float | None,
    storeys: int | None,
    road: float | None,
    typology: str = "detached",
) -> dict[str, Any]:
    """The building code's least open spaces [m] where no authority's rules apply: the front
    from the street's centre and the property line, the rear and side of the code's table by
    occupancy, typology, height and plot size. ``{front, rear, side (None: not given),
    sides (the table's values, None the pounding gap), row, rule, notes, covered}``."""
    code = code_rules()
    notes: list[str] = []
    out: dict[str, Any] = {
        "front": None,
        "rear": None,
        "side": None,
        "sides": None,
        "row": None,
        "rule": "",
        "notes": notes,
        "covered": False,
    }
    if code is None or code.setbacks is None:
        notes.append("The code pack gives no fallback open spaces.")
        return out
    if code.front is not None:
        front = code.front.fromBoundary
        if road is not None and road > 0:
            front = max(code.front.fromCentre - road / 2, code.front.fromBoundary)
        out["front"] = front
        out["frontRule"] = _code_rule(code.front.rule)
    table = code.setbacks
    out["rule"] = _code_rule(table.rule)
    group = occupancy(use)
    tall = _tall(table, height, storeys)
    for row in table.rows:
        if group not in row.occupancies:
            continue
        if row.typology is not None and row.typology != typology:
            continue
        if row.tall is not None and row.tall != tall:
            continue
        if row.heightMax is not None and height is not None and height > row.heightMax + 1e-9:
            continue
        if row.storeysMax is not None and storeys is not None and storeys > row.storeysMax:
            continue
        if area < row.areaMin - 1e-9 or (row.areaMax is not None and area > row.areaMax + 1e-9):
            continue
        out["row"] = row.label
        if row.note:
            notes.append(f"{row.note} ({out['rule']})")
        if row.rear is None or row.side is None:
            notes.append(f"{row.label}: the open spaces are by the other provisions of the code.")
            return out
        values = [v for v in row.side if v is not None]
        out.update(rear=row.rear, side=max(values, default=0.0), sides=list(row.side))
        out["covered"] = True
        if len(values) > 1:
            notes.append(
                f"{out['rule']}: the two sides need {' and '.join(f'{v:g}' for v in values)} m; "
                f"the plot's side distance is checked against the larger, {max(values):g} m."
            )
        if any(v is None for v in row.side):
            notes.append(
                f"One side is on the property line or at the pounding gap (PG, "
                f"{_code_rule(table.poundingGap)}): the gap is the building's seismic "
                "separation, checked with the analysis results (Project Settings, Seismic: gap "
                "to the property line); the open side is checked here."
            )
        return out
    notes.append(
        f"No row of {out['rule']} fits a {typology} building of this use on a {area:.0f} m² "
        "plot at this height: the open spaces are not checked."
    )
    return out


def open_area_percent(use: str) -> float | None:
    """The least total open area [% of the plot] of the building code for ``use``."""
    code = code_rules()
    if code is None or code.openArea is None:
        return None
    group = occupancy(use)
    return code.openArea.byOccupancy.get(group or "", code.openArea.minPercent)


def overhead_clearance(kind: str, voltage: float | None = None) -> dict[str, Any] | None:
    """The least vertical and horizontal distances [m] to an overhead electric line of class
    ``kind`` at ``voltage`` kV: ``{vertical, horizontal, label, rule}``; None when the pack has
    no such class."""
    code = code_rules()
    if code is None or code.overheadLines is None:
        return None
    spec = next((c for c in code.overheadLines.classes if c.id == kind), None)
    if spec is None:
        return None
    vertical, horizontal = spec.vertical, spec.horizontal
    if spec.upToKv is not None and spec.stepKv and voltage is not None and voltage > spec.upToKv:
        # "for each additional 33 kV or part thereof"
        steps = math.ceil((voltage - spec.upToKv) / spec.stepKv - 1e-9)
        vertical += steps * spec.stepVertical
        horizontal += steps * spec.stepHorizontal
    return {
        "vertical": round(vertical, 3),
        "horizontal": round(horizontal, 3),
        "label": spec.label,
        "rule": _code_rule(code.overheadLines.rule),
    }


def height_limit(construction_type: str, road: float, front: float) -> dict[str, Any] | None:
    """The largest storeys and height [m] of the building code for a building of
    ``construction_type`` on a road ``road`` m wide with a front open space ``front`` m:
    ``{storeys, height, basis, column, rule}``; None when the code's table has no column for
    the type."""
    code = code_rules()
    if code is None or code.height is None:
        return None
    spec = code.height
    column = next((c for c in spec.columns if construction_type in c.types), None)
    if column is None:
        return None
    basis = spec.basis * (road + front)
    index = next((i for i, top in enumerate(spec.bands) if basis < top - 1e-9), None)
    extra = 0
    if index is None:
        index = len(spec.bands) - 1
        extra = math.floor((basis - spec.bands[-1]) / spec.step + 1e-9) + 1
    if len(column.storeys) == 1:
        storeys, height = column.storeys[0], column.heights[0]
    else:
        storeys, height = column.storeys[index], column.heights[index]
    storeys += extra * column.stepStoreys
    height += extra * column.stepHeight
    return {
        "storeys": storeys,
        "height": height,
        "basis": round(basis, 3),
        "column": column.label,
        "rule": _code_rule(spec.rule),
        "source": column.source,
    }


def unlimited_height(use: str, construction_type: str, road: float | None, approved: bool) -> bool:
    """True when the building code sets no height limit: an approved area on a wide road, for
    the uses and construction types it names."""
    code = code_rules()
    if code is None or code.unlimited is None or road is None:
        return False
    spec = code.unlimited
    return (
        approved
        and road >= spec.minRoad - 1e-9
        and occupancy(use) in spec.occupancies
        and construction_type in spec.types
    )


def unlimited_open_spaces(use: str) -> dict[str, Any] | None:
    """The least front, rear and side open spaces [m] of a building of unlimited height or FAR:
    ``{front, rear, side, rule}``; None when the code gives none for the use."""
    code = code_rules()
    if code is None or code.unlimited is None:
        return None
    group = occupancy(use)
    row = next((r for r in code.unlimited.rows if group in r.occupancies), None)
    if row is None:
        return None
    return {
        "front": row.front,
        "rear": row.rear,
        "side": row.side,
        "rule": _code_rule(code.unlimited.openSpaceRule),
    }


def _construction_type(settings_text: str | None) -> str:
    """The construction type of the project settings ('' when not classified or unreadable)."""
    if not settings_text:
        return ""
    import json

    try:
        construction = json.loads(settings_text).get("construction") or {}
    except (ValueError, AttributeError):
        return ""
    value = construction.get("constructionType") if isinstance(construction, dict) else None
    return value if isinstance(value, str) else ""


def floor_areas(bim_text: str | None) -> dict[str, Any] | None:
    """The storeys of the building model with their floor areas [m²] (each storey the slabs at
    the level above it: the area it roofs, from the slab outlines), the ground coverage (the
    slabs' union on plan), the height [m] and the storey count; None without slabs."""
    if not bim_text or not bim_text.strip():
        return None
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    from saengine.library.bim import BuildingModel

    try:
        bim = BuildingModel.model_validate_json(bim_text)
    except ValidationError:
        return None
    slabs: list[tuple[float, Any]] = []
    for e in bim.elements:
        if e.kind == "slab":
            shape = Polygon([(float(p[0]), float(p[1])) for p in e.boundary]).buffer(0)
            if not shape.is_empty:
                slabs.append((float(e.elevation), shape))
    if not slabs:
        return None
    stories = sorted(bim.stories, key=lambda s: s.elevation)
    rows = []
    if len(stories) >= 2:
        for lower, upper in pairwise(stories):
            # The slabs whose top lies within the storey's upper half (sunken and raised
            # slabs included) roof it.
            mid = (lower.elevation + upper.elevation) / 2
            at = [s for z, s in slabs if mid < z <= upper.elevation + 1.0]
            area = unary_union(at).area / 1e6 if at else 0.0
            rows.append(
                {
                    "name": lower.name,
                    "elevation": lower.elevation / 1000,
                    "height": (upper.elevation - lower.elevation) / 1000,
                    "area": round(area, 2),
                }
            )
        height = (stories[-1].elevation - stories[0].elevation) / 1000
    else:
        levels = sorted({z for z, _ in slabs})
        for z in levels:
            area = unary_union([s for zz, s in slabs if zz == z]).area / 1e6
            rows.append(
                {
                    "name": f"slab at {z / 1000:g} m",
                    "elevation": z / 1000,
                    "height": None,
                    "area": round(area, 2),
                }
            )
        height = None
    footprint = unary_union([s for _, s in slabs])
    return {
        "storeys": rows,
        "groundCoverage": round(footprint.area / 1e6, 2),
        "grossFloorArea": round(sum(r["area"] for r in rows), 2),
        "height": height,
        "storeyCount": len(rows) if len(stories) >= 2 else None,
        "footprint": footprint,
    }


def _check(
    label: str,
    provided: float,
    limit: float,
    unit: str,
    rule: str,
    at_least: bool = False,
    advisory: bool = False,
) -> dict[str, Any]:
    ok = provided >= limit - 1e-6 if at_least else provided <= limit + 1e-6
    return {
        "label": label,
        "provided": round(provided, 3),
        "limit": None if math.isinf(limit) else round(limit, 3),
        "sense": "≥" if at_least else "≤",
        "unit": unit,
        "ok": ok,
        "rule": rule,
        # An advisory check (a code rule the authority's rules replace) never fails the plot.
        "advisory": advisory,
    }


def check(
    site: Site | None, bim_text: str | None = None, settings_text: str | None = None
) -> dict[str, Any] | None:
    """The planning compliance of the site's plot: None until the plot has a planning entry
    (``site.plot.planning``). ``{authority, rules, use, useName, plotArea, katha, band, road,
    permitted, setbacks {required, provided}, areas, limits, heightLimit, checks, notes,
    problems}``. ``settings_text`` (the project settings) gives the construction type the
    height limits need."""
    from saengine.gis import plot as plot_geometry

    plan = site.plot.planning if site is not None and site.plot is not None else None
    if plan is None:
        return None
    table = rules()
    code = table.buildingCode
    by_code = plan.rules == "code"
    problems: list[str] = []
    notes: list[str] = []
    ring, problem = plot_geometry.plot_ring(site)
    out: dict[str, Any] = {
        "authority": code.name if by_code and code is not None else table.authority,
        "source": code.source if by_code and code is not None else table.source,
        "rules": plan.rules,
        "codeName": None if code is None else code.name,
        "use": plan.use,
        "useName": table.uses[plan.use].name if plan.use in table.uses else plan.use,
        "uses": [{"id": k, "name": v.name} for k, v in table.uses.items()],
        "lineClasses": []
        if code is None or code.overheadLines is None
        else [{"id": c.id, "label": c.label} for c in code.overheadLines.classes],
        "checks": [],
        "notes": notes,
        "problems": problems,
    }
    if by_code and code is None:
        problems.append(
            "The code pack has no building-code site rules: choose the planning authority's."
        )
        return out
    if ring is None:
        problems.append(problem or "Draw the plot (or type it as a rectangle) to check it.")
        return out
    polygon = plot_geometry._polygon(ring)
    area = abs(polygon.area) / 1e6
    road = plan.roadWidth / 1000 if plan.roadWidth else None
    measured = floor_areas(bim_text)
    height = plan.height / 1000 if plan.height else (measured or {}).get("height")
    storeys = plan.storeys or (measured or {}).get("storeyCount")
    out.update(
        plotArea=round(area, 2),
        katha=round(area / plot_geometry.KATHA, 3),
        band=band_label(band(area)),
        road=road,
        height=height,
        storeys=storeys,
    )

    def binding(key: str) -> bool:
        return by_code or (code is not None and key in code.withAuthority)

    allowed = None
    if road is None:
        problems.append(
            "Enter the width of the road the plot faces: "
            + ("the front open space and height depend on it." if by_code else "FAR and MGC do.")
        )
    elif not by_code:
        allowed = permitted(plan.use, area, road)
        notes += allowed["notes"]
        out["permitted"] = {
            k: (None if isinstance(v, float) and math.isinf(v) else v)
            for k, v in allowed.items()
            if k != "notes"
        }
        out["permitted"]["farText"] = _far_text(allowed["far"])
    own = site.plot
    provided = {"front": own.front / 1000, "rear": own.rear / 1000, "side": own.side / 1000}
    if by_code:
        fallback = code_setbacks(plan.use, area, height, storeys, road, plan.typology)
        notes += fallback["notes"]
        required = {
            "front": fallback["front"],
            "rear": fallback["rear"],
            "side": fallback["side"],
            "rule": fallback["rule"],
            "frontRule": fallback.get("frontRule", fallback["rule"]),
        }
        out["setbacksRow"] = fallback["row"]
    else:
        authority = required_setbacks(area, height, storeys, road)
        notes += authority["notes"]
        required = {**authority, "frontRule": authority["rule"]}
        if road:
            required["frontRule"] += f", {table.roadCentre.rule}"
    out["setbacks"] = {
        "required": {k: required[k] for k in ("front", "rear", "side")},
        "provided": provided,
        "rule": required["rule"],
    }
    coverage = (
        plan.groundCoverage
        if plan.groundCoverage is not None
        else (measured or {}).get("groundCoverage")
    )
    gross = plan.floorArea if plan.floorArea is not None else (measured or {}).get("grossFloorArea")
    parking = plan.parkingArea if code is not None and code.parking is not None else 0.0
    far_area = None if gross is None else max(gross - plan.excludedArea - parking, 0.0)
    open_space = (
        plan.openArea
        if plan.openArea is not None
        else (None if coverage is None else round(area - coverage, 2))
    )
    out["areas"] = {
        "groundCoverage": coverage,
        "coverageSource": "entered"
        if plan.groundCoverage is not None
        else ("building model" if measured else None),
        "grossFloorArea": gross,
        "floorAreaSource": "entered"
        if plan.floorArea is not None
        else ("building model" if measured else None),
        "excluded": plan.excludedArea,
        "parking": parking,
        "farArea": far_area,
        "storeys": (measured or {}).get("storeys", []),
        "openSpace": open_space,
        "unpaved": plan.unpavedArea,
    }
    if parking and code is not None and code.parking is not None:
        notes.append(
            f"{_code_rule(code.parking.rule)}: {parking:g} m² of floors used for car parking "
            f"(at least {code.parking.parkingShare:.0%} of each, the rest accessory) are left "
            "out of the floor area for FAR."
        )
    if allowed and allowed["allowed"]:
        mgc_area = area * allowed["mgc"] / 100
        far_limit = area * allowed["far"]
        out["limits"] = {
            "mgcArea": round(mgc_area, 2),
            "floorArea": None if math.isinf(far_limit) else round(far_limit, 2),
            "openSpace": round(area - mgc_area, 2),
        }
        if coverage is not None:
            out["checks"].append(
                _check(
                    "Ground coverage",
                    coverage / area * 100,
                    allowed["mgc"],
                    "%",
                    f"{_clause('coverage')}, {allowed['rule']}".strip(", "),
                )
            )
        if far_area is not None:
            out["checks"].append(
                _check("FAR", far_area / area, allowed["far"], "", allowed["rule"])
            )
    elif allowed:
        problems.append(" ".join(allowed["notes"]))
    elif by_code and code is not None:
        notes.append(
            f"{code.name}: the floor area is the result of the open spaces and the height; FAR "
            "and ground coverage are set by the planning authority."
        )
    labels = {"front": "Front setback", "rear": "Rear setback", "side": "Side setback"}
    for key, label in labels.items():
        if required[key] is None:
            continue
        out["checks"].append(
            _check(
                label,
                provided[key],
                required[key],
                "m",
                required["frontRule"] if key == "front" else required["rule"],
                at_least=True,
            )
        )
    if measured and own.road is None:
        notes.append("Choose the plot's road side: the setbacks are measured from it.")
    if measured is not None:
        distances = plot_geometry.setbacks(site, ring)
        buildable = plot_geometry.envelope(ring, distances) if polygon.is_valid else None
        outside = measured["footprint"].difference(buildable).area / 1e6 if buildable else None
        if outside is not None:
            out["checks"].append(
                _check(
                    "Building outside the setbacks",
                    outside,
                    0.0,
                    "m²",
                    required["rule"] if by_code else _clause("envelope"),
                )
            )
    elif plan.floorArea is None:
        notes.append(
            "No building model yet: enter the ground coverage and the floor area, or "
            "generate the building model."
        )
    if code is not None:
        _code_checks(out, plan, code, area, road, height, storeys, provided, allowed, binding)
        construction = _construction_type(settings_text)
        _height_checks(out, plan, code, road, height, storeys, provided, construction, binding)
    out["ok"] = all(c["ok"] for c in out["checks"] if not c.get("advisory")) and not problems
    return out


def _code_checks(
    out: dict[str, Any],
    plan: Any,
    code: Any,
    area: float,
    road: float | None,
    height: float | None,
    storeys: int | None,
    provided: dict[str, float],
    allowed: dict[str, Any] | None,
    binding: Any,
) -> None:
    """The building code's levels, overhead line, open area and unpaved area checks."""
    checks, notes, problems = out["checks"], out["notes"], out["problems"]
    levels = code.levels
    if (
        levels is not None
        and plan.floodProne
        and (plan.plinthHeight is not None or plan.formationHeight is not None)
    ):
        notes.append(
            f"{_code_rule(levels.plinthRule)}: in a flood or surge prone area the plinth and "
            "formation levels are the development authority's; they are not checked here."
        )
    elif levels is not None:
        if plan.plinthHeight is not None:
            checks.append(
                _check(
                    "Plinth above the road",
                    plan.plinthHeight / 1000,
                    levels.plinthMin,
                    "m",
                    _code_rule(levels.plinthRule),
                    at_least=True,
                    advisory=not binding("plinth"),
                )
            )
        if plan.formationHeight is not None:
            rule = _code_rule(levels.formationRule)
            formation = plan.formationHeight / 1000
            checks.append(
                _check(
                    "Formation level not below the road",
                    formation,
                    0.0,
                    "m",
                    rule,
                    at_least=True,
                    advisory=not binding("formation"),
                )
            )
            if levels.formationMax is not None:
                checks.append(
                    _check(
                        "Formation level above the road",
                        formation,
                        levels.formationMax,
                        "m",
                        rule,
                        advisory=not binding("formation"),
                    )
                )
    line = plan.overheadLine
    if line is not None:
        need = overhead_clearance(line.kind, line.voltage)
        if need is None:
            problems.append(f"Unknown overhead line class '{line.kind}' in the code pack.")
        else:
            for key, label in (("vertical", "vertically"), ("horizontal", "horizontally")):
                have = getattr(line, key)
                if have is not None:
                    checks.append(
                        _check(
                            f"Overhead line ({need['label']}), {label}",
                            have / 1000,
                            need[key],
                            "m",
                            need["rule"],
                            at_least=True,
                            advisory=not binding("overheadLines"),
                        )
                    )
    spec = code.openArea
    if spec is None:
        return
    percent = open_area_percent(plan.use)
    open_space = out["areas"]["openSpace"]
    if percent is not None and open_space is not None:
        checks.append(
            _check(
                "Open area",
                open_space / area * 100,
                percent,
                "%",
                _code_rule(spec.rule),
                at_least=True,
                advisory=not binding("openArea"),
            )
        )
    if plan.unpavedArea is not None and spec.unpavedPercent:
        # The minimum open space: the code's least open area, or the authority's (the plot less
        # its maximum ground coverage) where that is larger.
        minimum = area * (percent or 0) / 100
        if allowed and allowed.get("allowed"):
            minimum = max(minimum, area * (100 - allowed["mgc"]) / 100)
        checks.append(
            _check(
                "Unpaved open area",
                plan.unpavedArea,
                minimum * spec.unpavedPercent / 100,
                "m²",
                _code_rule(spec.unpavedRule),
                at_least=True,
                advisory=not binding("unpaved"),
            )
        )


def _height_checks(
    out: dict[str, Any],
    plan: Any,
    code: Any,
    road: float | None,
    height: float | None,
    storeys: int | None,
    provided: dict[str, float],
    construction: str,
    binding: Any,
) -> None:
    """The building code's height limit by road width and construction type, and the open
    spaces of a building of unlimited height or FAR."""
    checks, notes = out["checks"], out["notes"]
    out["constructionType"] = construction or None
    unlimited = False
    if code.height is not None and road is not None:
        if not construction:
            notes.append(
                f"{_code_rule(code.height.rule)}: set the construction type (Project Settings, "
                "Construction) to check the building's height."
            )
        elif unlimited_height(plan.use, construction, road, plan.approvedArea):
            unlimited = True
            notes.append(
                f"{_code_rule(code.unlimited.rule)}: an approved area on a road at least "
                f"{code.unlimited.minRoad:g} m wide: no height limit for type {construction}, "
                "with the open spaces of a building of unlimited height."
            )
            out["heightLimit"] = None
        else:
            limit = height_limit(construction, road, provided["front"])
            if limit is None:
                notes.append(
                    f"{_code_rule(code.height.rule)}: no height limit is given for construction "
                    f"type {construction}."
                )
            else:
                out["heightLimit"] = limit
                notes.append(
                    f"{limit['rule']}: {code.height.basis:g} × (road {road:g} m + front open "
                    f"space {provided['front']:g} m) = {limit['basis']:g} m: {limit['column']} up "
                    f"to {limit['storeys']} storeys and {limit['height']:g} m."
                )
                if limit.get("source"):
                    notes.append(limit["source"])
                if height is not None:
                    checks.append(
                        _check(
                            "Building height",
                            height,
                            limit["height"],
                            "m",
                            limit["rule"],
                            advisory=not binding("height"),
                        )
                    )
                if storeys is not None:
                    checks.append(
                        _check(
                            "Storeys",
                            storeys,
                            limit["storeys"],
                            "",
                            limit["rule"],
                            advisory=not binding("height"),
                        )
                    )
                if height is None and storeys is None:
                    notes.append("Enter the building's height or storeys to check them.")
    far_unlimited = (out.get("permitted") or {}).get("allowed") and (
        out["permitted"].get("far") is None
    )
    if unlimited or far_unlimited:
        spaces = unlimited_open_spaces(plan.use)
        if spaces is None:
            notes.append(
                "A building of unlimited height or FAR: the code gives its open spaces for this "
                "use by its other provisions."
            )
            return
        labels = {"front": "Front", "rear": "Rear", "side": "Side"}
        for key, label in labels.items():
            checks.append(
                _check(
                    f"{label} open space (unlimited height or FAR)",
                    provided[key],
                    spaces[key],
                    "m",
                    spaces["rule"],
                    at_least=True,
                    advisory=not binding("unlimited"),
                )
            )

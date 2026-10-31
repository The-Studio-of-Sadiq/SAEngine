"""Planning compliance of the plot (1 Soil Report, site): FAR, maximum ground coverage (MGC),
setbacks and the area statement.

The rules are the code pack's ``planning`` table: for BNBC 2020 the planning authority's rules
that BNBC Part 3 Chapter 1 defers to, for Dhaka (RAJUK) the Imarat Nirman Bidhimala 2008
(Rule 46 and Table 2: setbacks; Rule 50: ground coverage; Rule 51 and Tables 3(A)-3(F): FAR and
MGC by use, plot size and road width). The table is pack data: another authority's rules are
another pack's table, and a project may edit its copy.

- :func:`permitted`: the FAR and MGC a plot of ``area`` on a road ``road`` wide may have;
- :func:`required_setbacks`: the setbacks Table 2 asks for (and the road-centre rule);
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
            "rule": f"Rule 51, {spec.table}",
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
            "rule": "Rule 51(10)",
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
                    "(SAEngine reading of Rule 51)."
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
            "rule": f"Rule 51, {spec.table}",
            "row": None,
            "notes": [f"No row of {spec.table} applies to a {road:g} m road."],
        }
    far, mgc, row_road, label = max(candidates, key=lambda c: (c[0], c[2]))
    rule = f"Rule 51, {spec.table}"
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
    label: str, provided: float, limit: float, unit: str, rule: str, at_least: bool = False
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
    }


def check(site: Site | None, bim_text: str | None = None) -> dict[str, Any] | None:
    """The planning compliance of the site's plot: None until the plot has a planning entry
    (``site.plot.planning``). ``{authority, use, useName, plotArea, katha, band, road,
    permitted, setbacks {required, provided}, areas, limits, checks, notes, problems}``."""
    from saengine.gis import plot as plot_geometry

    plan = site.plot.planning if site is not None and site.plot is not None else None
    if plan is None:
        return None
    table = rules()
    problems: list[str] = []
    notes: list[str] = []
    ring, problem = plot_geometry.plot_ring(site)
    out: dict[str, Any] = {
        "authority": table.authority,
        "source": table.source,
        "use": plan.use,
        "useName": table.uses[plan.use].name if plan.use in table.uses else plan.use,
        "uses": [{"id": k, "name": v.name} for k, v in table.uses.items()],
        "checks": [],
        "notes": notes,
        "problems": problems,
    }
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
    if road is None:
        problems.append("Enter the width of the road the plot faces: FAR and MGC depend on it.")
        allowed = None
    else:
        allowed = permitted(plan.use, area, road)
        notes += allowed["notes"]
        out["permitted"] = {
            k: (None if isinstance(v, float) and math.isinf(v) else v)
            for k, v in allowed.items()
            if k != "notes"
        }
        out["permitted"]["farText"] = _far_text(allowed["far"])
    required = required_setbacks(area, height, storeys, road)
    notes += required["notes"]
    own = site.plot
    provided = {"front": own.front / 1000, "rear": own.rear / 1000, "side": own.side / 1000}
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
    far_area = None if gross is None else max(gross - plan.excludedArea, 0.0)
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
        "farArea": far_area,
        "storeys": (measured or {}).get("storeys", []),
        "openSpace": None if coverage is None else round(area - coverage, 2),
    }
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
                    f"Rule 50, {allowed['rule']}",
                )
            )
        if far_area is not None:
            out["checks"].append(
                _check("FAR", far_area / area, allowed["far"], "", allowed["rule"])
            )
    elif allowed:
        problems.append(" ".join(allowed["notes"]))
    labels = {"front": "Front setback", "rear": "Rear setback", "side": "Side setback"}
    for key, label in labels.items():
        out["checks"].append(
            _check(
                label,
                provided[key],
                required[key],
                "m",
                required["rule"] + (", Rule 46(3)" if key == "front" and road else ""),
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
                _check("Building outside the setbacks", outside, 0.0, "m²", "Rule 46(1)-(2)")
            )
    elif plan.floorArea is None:
        notes.append(
            "No building model yet: enter the ground coverage and the floor area, or "
            "generate the building model."
        )
    out["ok"] = all(c["ok"] for c in out["checks"]) and not problems
    return out

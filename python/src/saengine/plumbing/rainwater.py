"""Rainwater (BNBC 2020 Part 8 Chapter 7): catchments, leaders, gutters, storm drain, harvesting.

- Intensity: the one-hour rainfall of Appendix R (Figure 8.R.1, 25-year return period) for the
  site, as entered; else Dhaka's, about 88 mm (between the 85 and 90 mm isohyets).
- Catchment of a roof drain: as entered, else its share of the roof story's slabs (06 BIM)
  split by the nearest drain (Voronoi cells of the drains clipped to the roof, with shapely).
  The 50 % of adjoining vertical walls Sec 7.8.4 adds is not included (enter the area then).
- Leaders (Table 8.7.2), gutters (Table 8.7.3) and the horizontal storm drain (Table 8.7.4) are
  for 25 mm/h: a size serves the table's area x 25 / intensity. Each rainwater riser (leader)
  of 07 MEP collects the drains nearest to it; without leaders each drain gets its own. At
  least two drains and leaders for an independent roof surface (Sec 7.8.10, 7.21.1). The leader
  inlet is one size bigger (Sec 7.8.11). Storm drains at least 100 mm (Sec 7.10.6.3), 0.6 to
  2.5 m/s (Sec 7.17).
- Harvesting (Sec 7.4.1): required on plots of 300 m² or more. Storage (Sec 7.8.9) =
  D x N x Dp / 1000 + floating [m³], D the rainwater demand [lpcd], N the population, Dp 90
  days for potable uses and 210 for others.
"""

from __future__ import annotations

import math
from typing import Any

import shapely
from shapely.geometry import MultiPoint, Point

from saengine.plumbing import tables as T
from saengine.plumbing.building import Building


def intensity(plumbing: Any) -> tuple[float, str]:
    roof = plumbing.roof
    if roof is not None and roof.rainfallIntensity:
        return float(roof.rainfallIntensity), "rainfall intensity as entered in 07 MEP"
    return T.DHAKA_RAINFALL, (
        f"rainfall intensity {T.DHAKA_RAINFALL:g} mm/h: Dhaka from {T.PAGES['R']} (between the "
        "85 and 90 mm isohyets, interpolated); enter the site's value"
    )


def catchments(plumbing: Any, building: Building) -> list[dict[str, Any]]:
    """Catchment area [m²] of every roof drain and where it comes from."""
    drains = plumbing.roof.drains if plumbing.roof else []
    by_story: dict[str, list[Any]] = {}
    for d in drains:
        by_story.setdefault(d.story, []).append(d)
    result = []
    for story, group in by_story.items():
        roof = building.roof(story)
        cells: dict[str, float] = {}
        if roof is not None and not roof.is_empty:
            if len(group) == 1:
                cells[group[0].id] = roof.area / 1e6
            else:
                points = MultiPoint([(d.x, d.y) for d in group])
                regions = shapely.voronoi_polygons(points, extend_to=roof.envelope.buffer(1.0))
                for d in group:
                    p = Point(d.x, d.y)
                    cell = next((g for g in regions.geoms if g.covers(p)), None)
                    if cell is not None:
                        cells[d.id] = cell.intersection(roof).area / 1e6
        for d in group:
            if d.area is not None:
                result.append({"id": d.id, "story": story, "area": d.area, "source": "entered"})
            elif d.id in cells:
                result.append({
                    "id": d.id, "story": story, "area": cells[d.id],
                    "source": "roof slab split by nearest drain",
                })  # fmt: skip
            else:
                result.append({
                    "id": d.id, "story": story, "area": 0.0,
                    "source": "no area: enter it or the roof slab in 06 BIM",
                })  # fmt: skip
    return result


def scaled(area: float, rain: float) -> float:
    """A table area at 25 mm/h, at ``rain`` mm/h."""
    return area * T.TABLE_RAINFALL / rain


def leader_size(area: float, rain: float) -> int | None:
    """Table 8.7.2: the leader for a projected roof area [m²] at ``rain`` mm/h."""
    for d, table_area, _flow in T.LEADERS:
        if area <= scaled(table_area, rain) + 1e-9:
            return d
    return None


def next_size(diameter: int) -> int | None:
    sizes = [d for d, *_ in T.LEADERS]
    bigger = [s for s in sizes if s > diameter]
    return bigger[0] if bigger else None


def gutter_size(area: float, rain: float, slope: int = 10) -> int | None:
    """Table 8.7.3: the semicircular gutter at a slope [mm/m] (5, 10, 20 or 40)."""
    for d, by_slope in T.GUTTERS:
        if area <= scaled(by_slope[slope][0], rain) + 1e-9:
            return d
    return None


def storm_drain(area: float, rain: float, slope: float) -> tuple[int | None, int | None]:
    """Table 8.7.4: the building storm drain for a catchment [m²]: (diameter, slope column
    mm/m)."""
    per_m = slope * 1000.0
    columns = [c for c in (10, 20, 40) if c <= per_m + 1e-9]
    if not columns:
        return None, None
    column = columns[-1]
    for d, by_slope in T.STORM_DRAINS:
        if d >= T.MIN_STORM_DRAIN and area <= scaled(by_slope[column][0], rain) + 1e-9:
            return d, column
    return None, column


def flow(area: float, rain: float) -> float:
    """Runoff of a roof area [m²] at ``rain`` mm/h [l/min]."""
    return area * rain / 60.0


def leaders(plumbing: Any, areas: list[dict[str, Any]], rain: float) -> list[dict[str, Any]]:
    """Each rainwater riser with the drains nearest to it; sized or checked."""
    risers = [r for r in plumbing.risers if r.system == "rainwater"]
    drains = {d.id: d for d in (plumbing.roof.drains if plumbing.roof else [])}
    assigned: dict[str, list[str]] = {r.id: [] for r in risers}
    for a in areas:
        d = drains[a["id"]]
        if risers:
            nearest = min(risers, key=lambda r: math.hypot(r.x - d.x, r.y - d.y))
            assigned[nearest.id].append(a["id"])
    by_id = {a["id"]: a for a in areas}
    result = []
    for r in risers:
        area = sum(by_id[i]["area"] for i in assigned[r.id])
        required = leader_size(area, rain) if area > 0 else None
        notes = [f"drains {', '.join(assigned[r.id]) or 'none'}: {area:.1f} m²"]
        if r.diameter is not None:
            diameter = r.diameter
            ok = required is not None and r.diameter >= required
            if area > 0 and not ok:
                notes.append(f"Ø{r.diameter:g} is too small: needs Ø{required or '> 200'}")
            ok = ok or area == 0
        else:
            diameter = required
            ok = required is not None or area == 0
        result.append({
            "id": r.id, "system": "rainwater", "units": None, "area": area,
            "flow": flow(area, rain), "diameter": diameter, "required": required, "ok": ok,
            "inlet": next_size(int(diameter)) if diameter else None, "notes": notes,
            "reference": T.PAGES["8.7.2"],
        })  # fmt: skip
    return result


def harvesting(plumbing: Any, building: Building, population: float) -> dict[str, Any]:
    roof = plumbing.roof
    plot = roof.plotArea if roof else None
    footprint = building.footprint()
    notes = []
    if plot is not None:
        required: bool | None = plot >= T.HARVEST_PLOT
        notes.append(
            f"plot {plot:g} m² {'>=' if required else '<'} {T.HARVEST_PLOT:g} m²: harvesting "
            f"{'required' if required else 'not required'} ({T.PAGES['7.4.1']})"
        )
    elif footprint is not None and footprint.area / 1e6 >= T.HARVEST_PLOT:
        required = True
        notes.append(
            f"the building covers {footprint.area / 1e6:.0f} m² >= 300 m² of its plot: "
            f"harvesting required ({T.PAGES['7.4.1']})"
        )
    else:
        required = None
        notes.append(
            f"enter the plot area: harvesting is required from 300 m² ({T.PAGES['7.4.1']})"
        )
    result: dict[str, Any] = {"required": required, "plotArea": plot, "notes": notes}
    harvest = roof.harvest if roof else None
    if harvest is not None:
        n = harvest.population if harvest.population is not None else population
        days = harvest.days or T.HARVEST_DAYS[harvest.purpose]
        volume = harvest.demand * n * days / 1000.0 + harvest.floating
        result.update({"demand": harvest.demand, "population": n, "days": days,
                       "volume": volume, "floating": harvest.floating})  # fmt: skip
        notes.append(
            f"storage = {harvest.demand:g} lpcd x {n:g} x {days:g} days / 1000 + "
            f"{harvest.floating:g} = {volume:.1f} m³ ({T.PAGES['7.8.9']})"
        )
    elif required:
        notes.append("enter the rainwater demand (07 MEP plumbing.roof.harvest) to size its tank")
    return result


def rainwater(plumbing: Any, building: Building, population: float = 0.0) -> dict[str, Any]:
    rain, rain_note = intensity(plumbing)
    areas = catchments(plumbing, building)
    drains = []
    for a in areas:
        size = leader_size(a["area"], rain) if a["area"] > 0 else None
        drains.append({
            **a, "flow": flow(a["area"], rain), "leader": size,
            "gutter": gutter_size(a["area"], rain, 10) if a["area"] > 0 else None,
            "ok": a["area"] == 0 or size is not None,
        })  # fmt: skip
    notes = [rain_note]
    by_story: dict[str, int] = {}
    for a in areas:
        by_story[a["story"]] = by_story.get(a["story"], 0) + 1
    checks = []
    for story, n in by_story.items():
        checks.append({
            "name": f"Roof drains on {story}", "demand": 2, "capacity": n, "unit": "drains",
            "utilisation": 2 / n if n else math.inf, "ok": n >= 2,
            "note": f"at least two drains and leaders per roof surface ({T.PAGES['7.8.10']})",
        })  # fmt: skip
    total = sum(a["area"] for a in areas)
    d, column = storm_drain(total, rain, plumbing.drainSlope) if total > 0 else (None, None)
    storm = {
        "area": total,
        "flow": flow(total, rain),
        "diameter": d,
        "column": column,
        "ok": total == 0 or d is not None,
        "note": f"{total:.1f} m² of roof at {column or '-'} mm/m ({T.PAGES['8.7.4']}); at least "
        f"100 mm ({T.PAGES['7.17']}: 0.6 - 2.5 m/s)",
    }
    return {
        "intensity": rain,
        "drains": drains,
        "leaders": leaders(plumbing, areas, rain),
        "stormDrain": storm,
        "harvesting": harvesting(plumbing, building, population),
        "checks": checks,
        "notes": notes,
        "reference": f"{T.PAGES['8.7.2']}; {T.PAGES['8.7.3']}; {T.PAGES['8.7.4']}; {T.PAGES['R']}",
    }

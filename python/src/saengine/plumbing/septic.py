"""Septic tank and soak well (BNBC 2020 Part 8 Sec 6.9.12-6.9.15, Appendix S).

- Volume (Appendix S Eq 8.S.1): V = P Q t + P S Y [litres]: P persons served, Q waste water
  flow (Appendix S, in the absence of data: 120 lpcd for occupancy groups A, C and D in cities,
  10 lpcd for the other groups), t the retention time (at least 1 day, Sec 6.9.12.11), S the
  sludge and scum (40 l = 0.04 m³ per capita per year, Sec 6.9.12.10), Y the desludging interval
  (1 year; Sec 6.9.12.12: 6 months to a year). The occupancies Table 8.S.1 lists count their
  persons times its reduction factor (SAEngine reads the factor as turning them into
  residential equivalents at the city flow). At least 2000 litres (Sec 6.9.12.8).
- Shape (Sec 6.9.12.8-6.9.12.13): width at least 1 m, liquid depth at least 1 m, length 3 to 4
  widths, 300 mm from the liquid to the cover, two chambers above 3000 litres (the inlet one
  2/3 of the length); at most 300 users for a residential tank (Sec 6.9.12.9): above 300
  residential users an Imhoff tank shall be used (Sec 6.9.13.2), which SAEngine reports as a
  failing check and does not design (no septic tank is proposed). Other occupancies (BNBC sets
  no cap): SAEngine splits the users into tanks of at most 300. SAEngine proportions: liquid depth = width
  = (V/3)^(1/3) within 1 to 2 m, length = 3 widths, rounded up to 50 mm.
- Soak well (seepage pit, Sec 6.9.15): liquid capacity at least twice the septic tank's (Sec
  6.9.15.3), wall area for the daily effluent at the effluent allowance of Table 8.6.10 for the
  percolation rate (tested, Sec 6.9.15.2, at least three holes; else estimated from the top
  layers of 01 Soil Report: SAEngine's first estimate, not a substitute for the tests), the
  bottom at least 1 m above the highest water table (Sec 6.9.15.4). SAEngine: the inlet 1 m
  below ground, 1.5 m diameter unless given, at most 6 m effective depth; more wells when one
  is not enough.
- Separation: Table 8.6.8 (septic tank 1.5 m from the building foundation and from a seepage
  pit; seepage pit 4.5 m from the foundation, 6 m from another) and Table 8.6.9 (treatment
  tank 7.5 m from a reservoir, 1.5 m from a building). Table 8.6.8 lists no reservoir for a
  seepage pit: SAEngine takes the well's 15 m (a source of drinking water).
"""

from __future__ import annotations

import math
from typing import Any

from shapely.geometry import Point, Polygon

from saengine.plumbing import tables as T
from saengine.plumbing.building import Building
from saengine.plumbing.demand import story_population
from saengine.plumbing.storage import ceil_to

INLET_DEPTH = 1000.0  # mm below ground, SAEngine
WELL_DIAMETER = 1500.0  # mm, SAEngine default
WELL_MAX_DEPTH = 6000.0  # mm effective, SAEngine


def users(plumbing: Any, building: Building) -> dict[str, Any]:
    """Equivalent persons (Table 8.S.1) and the daily waste water flow [l/day]."""
    persons = 0.0
    residential = 0.0
    daily = 0.0
    notes = []
    for entry in plumbing.stories:
        population, _ = story_population(entry, building)
        if not population:
            continue
        row = T.OCCUPANCIES[entry.occupancy]
        letter = row.group[:1]
        if entry.occupancy in T.SEPTIC_REDUCTION:
            factor, why = T.SEPTIC_REDUCTION[entry.occupancy]
            q = T.SEPTIC_FLOW_CITY
            notes.append(f"{entry.story}: {population:g} x {factor:g} ({why})")
        elif letter in ("A", "C", "D"):
            factor, q = 1.0, T.SEPTIC_FLOW_CITY
        else:
            factor, q = 1.0, T.SEPTIC_FLOW_OTHER
            notes.append(f"{entry.story}: {row.group}, {T.SEPTIC_FLOW_OTHER:g} lpcd (Appendix S)")
        persons += population * factor
        daily += population * factor * q
        if letter == "A":
            residential += population
    return {"persons": persons, "residential": residential, "daily": daily, "notes": notes}


def volume(persons: float, flow: float, retention: float, desludging: float) -> float:
    """Eq 8.S.1 [litres]: P Q t + P S Y, at least 2000."""
    v = persons * flow * retention + persons * T.SEPTIC_SLUDGE * desludging
    return max(v, T.SEPTIC_MIN_VOLUME)


def shape(v: float, tank: Any = None) -> dict[str, Any]:
    """Liquid dimensions [mm] of a septic tank of ``v`` litres (kept where the tank gives them)."""
    m3 = v / 1000.0
    depth = tank.waterDepth if tank is not None and tank.waterDepth else None
    width = tank.width if tank is not None and tank.width else None
    length = tank.length if tank is not None and tank.length else None
    if depth is None:
        depth = ceil_to(min(max((m3 / 3.0) ** (1 / 3), 1.0), 2.0) * 1000.0)
    if width is None:
        width = ceil_to(max(math.sqrt(m3 * 1e9 / (3.0 * depth)), T.SEPTIC_MIN_WIDTH))
    if length is None:
        length = ceil_to(max(3.0 * width, m3 * 1e9 / (width * depth)))
    chambers = 2 if v > T.SEPTIC_TWO_CHAMBERS else 1
    if tank is not None and tank.compartments:
        chambers = tank.compartments
    provided = length * width * depth / 1e6
    checks = [
        ("Septic tank liquid volume", v, provided, "l", "Appendix S Eq 8.S.1"),
        ("Septic tank width", T.SEPTIC_MIN_WIDTH, width, "mm", "Sec 6.9.12.8 at least 1 m"),
        ("Septic tank liquid depth", T.SEPTIC_MIN_DEPTH, depth, "mm", "Sec 6.9.12.8 at least 1 m"),
        ("Septic tank length", 3 * width, length, "mm", "Sec 6.9.12.8 at least 3 widths"),
    ]
    notes = []
    if length > T.SEPTIC_LENGTH_RATIO[1] * width:
        notes.append("longer than 4 widths (recommended at most, Sec 6.9.12.8)")
    if v > T.SEPTIC_TWO_CHAMBERS and chambers < 2:
        notes.append("two chambers recommended above 3000 litres (Sec 6.9.12.13)")
    return {
        "length": length,
        "width": width,
        "waterDepth": depth,
        "freeboard": T.SEPTIC_CLEARANCE,
        "compartments": chambers,
        "inletLength": length * T.SEPTIC_INLET_FRACTION if chambers >= 2 else None,
        "provided": provided,
        "checks": checks,
        "notes": notes,
    }


def septic_tank(plumbing: Any, building: Building, tank: Any = None) -> dict[str, Any]:
    """The septic tank(s) the building needs: volume, number and shape."""
    load = users(plumbing, building)
    persons = tank.users if tank is not None and tank.users is not None else load["persons"]
    flow = (
        tank.flow
        if tank is not None and tank.flow
        else (load["daily"] / load["persons"] if load["persons"] else T.SEPTIC_FLOW_CITY)
    )
    retention = tank.retention if tank is not None and tank.retention else T.SEPTIC_RETENTION
    desludging = tank.desludging if tank is not None and tank.desludging else T.SEPTIC_DESLUDGING
    notes = list(load["notes"])
    resident = load["residential"]
    if tank is not None and tank.users is not None:
        resident = persons * (resident / load["persons"] if load["persons"] else 1.0)
    # Sec 6.9.13.2: an Imhoff tank shall be used where more than 300 people of residential
    # buildings are served (Sec 6.9.12.9 caps a residential septic tank at 300 users).
    imhoff = resident > T.SEPTIC_MAX_USERS + 1e-9
    count = max(1, math.ceil(persons / T.SEPTIC_MAX_USERS - 1e-9))
    if imhoff:
        notes.append(
            f"{resident:g} residential users > {T.SEPTIC_MAX_USERS}: an Imhoff tank shall be "
            "used (Sec 6.9.13.2 (p1107)), not septic tanks; SAEngine does not design "
            "Imhoff tanks, so no septic tank or soak well is proposed (the figures below are "
            "for information only)"
        )
    elif count > 1:
        notes.append(
            f"{persons:g} equivalent users (of them {resident:g} residential, at most "
            f"{T.SEPTIC_MAX_USERS} a residential tank, Sec 6.9.12.9): {count} tanks proposed "
            "(SAEngine: BNBC sets no cap for other occupancies)"
        )
    each = persons / count
    v = volume(each, flow, retention, desludging)
    dims = shape(v, tank)
    notes.extend(dims.pop("notes"))
    dims["checks"].insert(
        0,
        (
            "Residential users of a septic tank",
            resident,
            float(T.SEPTIC_MAX_USERS),
            "persons",
            "Sec 6.9.12.9; above 300 an Imhoff tank, Sec 6.9.13.2 (p1106-1107)",
        ),
    )
    notes.insert(
        0,
        f"V = {each:g} x {flow:g} x {retention:g} + {each:g} x {T.SEPTIC_SLUDGE:g} x "
        f"{desludging:g} = {v:.0f} l ({T.PAGES['S']})",
    )
    return {
        "persons": persons,
        "flow": flow,
        "retention": retention,
        "desludging": desludging,
        "count": 0 if imhoff else count,
        "imhoff": imhoff,
        "residential": resident,
        "volume": v,
        "daily": each * flow,
        **dims,
        "coverLiveLoad": T.SEPTIC_COVER_LIVE,
        "notes": notes,
        "reference": f"{T.PAGES['S']}; {T.PAGES['6.9.12']}",
    }


# ─────────────────────────────────────── soak well ───────────────────────────────────────


def soil_percolation(soil: Any, x: float = 0.0, y: float = 0.0, depth: float = 3000.0):
    """SAEngine's first estimate of the percolation rate [min/25 mm] from the soil layers
    within ``depth`` of the ground at the borehole nearest to (x, y), the slowest of them; and
    that borehole's water table depth [mm]. (None, None, note) without a soil report."""
    if soil is None or not soil.boreholes:
        return None, None, "no 01 Soil Report"
    hole = min(soil.boreholes, key=lambda b: math.hypot(b.x - x, b.y - y))
    rates = []
    for layer in hole.layers:
        if layer.top >= depth:
            continue
        kind = layer.soilType
        uscs = (layer.uscs or "").upper()
        if kind == "sand" and (uscs.startswith(("SM", "SC")) or (layer.finesContent or 0) > 15):
            kind = "siltySand"
        if kind == "fill":
            continue
        rate = T.PERCOLATION_BY_SOIL.get(kind)
        if rate is not None:
            rates.append((rate, f"{layer.top / 1000:g}-{layer.bottom / 1000:g} m {kind}"))
    if not rates:
        return None, hole.waterTable, f"{hole.id}: no natural soil in the top {depth / 1000:g} m"
    rate, which = max(rates)
    return (
        rate,
        hole.waterTable,
        (
            f"{hole.id}, slowest of the top {depth / 1000:g} m: {which} -> about {rate:g} min/25 mm "
            "(SAEngine estimate; percolation tests in at least three holes, Sec 6.9.15.2)"
        ),
    )


def allowance(rate: float) -> float | None:
    """Table 8.6.10: effluent allowance of a seepage pit's wall [l/m²/day] (None: unsuitable)."""
    for bound, _trench, pit in T.ABSORPTION:
        if rate <= bound:
            return float(pit)
    return None


def soak_well(septic: dict[str, Any], tank: Any = None, soil: Any = None) -> dict[str, Any]:
    """The soak well(s) for one septic tank: diameter, effective depth and number."""
    diameter = tank.diameter if tank is not None and tank.diameter else WELL_DIAMETER
    x = tank.x if tank is not None else 0.0
    y = tank.y if tank is not None else 0.0
    notes = []
    if tank is not None and tank.percolation:
        rate, water_table = tank.percolation, None
        _, water_table, _ = soil_percolation(soil, x, y)
        notes.append(f"percolation {rate:g} min/25 mm as entered")
    else:
        rate, water_table, note = soil_percolation(soil, x, y)
        notes.append(note)
    if rate is None:
        rate = 10.0
        notes.append("percolation unknown: 10 min/25 mm assumed until tested")
    per_m2 = allowance(rate)
    if per_m2 is None:
        return {
            "ok": False, "percolation": rate, "diameter": diameter,
            "notes": [*notes, (f"over 60 min/25 mm: not suitable for a seepage pit "
                      f"({T.PAGES['8.6.10']})")],
            "reference": T.PAGES["8.6.10"],
        }  # fmt: skip
    if rate > 30:
        notes.append(f"{rate:g} min/25 mm: not recommended ({T.PAGES['8.6.10']})")
    daily = septic["daily"]
    area = daily / per_m2  # m² of wall
    capacity = T.SEEPAGE_CAPACITY_FACTOR * septic["volume"] / 1000.0  # m³
    d = diameter / 1000.0
    need = max(area / (math.pi * d), capacity / (math.pi * d * d / 4))  # m of depth
    if water_table is not None:
        available = (water_table - T.SEEPAGE_ABOVE_WATER_TABLE - INLET_DEPTH) / 1000.0
        notes.append(
            f"water table {water_table / 1000:g} m: bottom at most "
            f"{(water_table - T.SEEPAGE_ABOVE_WATER_TABLE) / 1000:g} m deep (Sec 6.9.15.4)"
        )
    else:
        available = WELL_MAX_DEPTH / 1000.0
        notes.append("water table unknown: check the bottom is 1 m above it (Sec 6.9.15.4)")
    available = min(available, WELL_MAX_DEPTH / 1000.0)
    if available <= 0.3:
        return {
            "ok": False, "percolation": rate, "allowance": per_m2, "diameter": diameter,
            "area": area, "capacity": capacity, "waterTable": water_table,
            "notes": [*notes, ("the water table leaves no depth for a soak well: a disposal "
                      "field or another disposal (Sec 6.9.12.1)")],
            "reference": T.PAGES["8.6.10"],
        }  # fmt: skip
    count = max(1, math.ceil(need / available - 1e-9))
    depth = ceil_to(need / count * 1000.0, 100.0)
    notes.insert(
        0,
        f"wall area {daily:.0f} l/day / {per_m2:g} l/m²/day = {area:.1f} m², liquid capacity "
        f"2 x {septic['volume'] / 1000:.2f} = {capacity:.2f} m³ ({T.PAGES['6.9.15']}): "
        f"{count} x Ø{diameter / 1000:g} m, {depth / 1000:g} m effective depth",
    )
    return {
        "ok": True,
        "percolation": rate,
        "allowance": per_m2,
        "area": area,
        "capacity": capacity,
        "diameter": diameter,
        "waterDepth": depth,
        "count": count,
        "waterTable": water_table,
        "notes": notes,
        "reference": f"{T.PAGES['8.6.10']}; {T.PAGES['6.9.15']}",
    }


# ─────────────────────────────────────── separation ───────────────────────────────────────


def outline(tank: Any, dims: dict[str, Any] | None = None) -> Any:
    """Plan outline of a tank (outside, with its walls when given) [mm]."""
    walls = tank.walls or 0.0
    if tank.kind == "soakWell":
        d = tank.diameter or (dims or {}).get("diameter") or WELL_DIAMETER
        return Point(tank.x, tank.y).buffer(d / 2 + walls)
    length = tank.length or (dims or {}).get("length")
    width = tank.width or (dims or {}).get("width")
    if not length or not width:
        return Point(tank.x, tank.y)
    hx, hy = length / 2 + walls, width / 2 + walls
    x, y = tank.x, tank.y
    return Polygon([(x - hx, y - hy), (x + hx, y - hy), (x + hx, y + hy), (x - hx, y + hy)])


def separations(
    plumbing: Any, building: Building, dims: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Distance checks of the septic tanks and soak wells placed in 07 MEP."""
    tanks = plumbing.tanks
    shapes = {t.id: outline(t, dims.get(t.id)) for t in tanks}
    footprint = building.footprint()
    checks = []

    def add(a: Any, b_name: str, b_shape: Any, need: float, why: str) -> None:
        gap = shapes[a.id].distance(b_shape) / 1000.0
        checks.append({
            "name": f"{a.id} to {b_name}", "demand": need, "capacity": gap, "unit": "m",
            "utilisation": need / gap if gap > 0 else math.inf, "ok": gap >= need - 1e-9,
            "note": why,
        })  # fmt: skip

    for t in tanks:
        if t.kind == "septic":
            if footprint is not None:
                # The distance to the footprint polygon: 0 (fails) for a tank under the
                # building, which is not 1.5 m clear of its foundation.
                add(t, "building", footprint, 1.5, f"{T.PAGES['8.6.8']}; {T.PAGES['8.6.9']}")
            for o in tanks:
                if o.kind == "underground":
                    add(t, o.id, shapes[o.id], 7.5, f"reservoir, {T.PAGES['8.6.9']}")
                elif o.kind == "soakWell":
                    add(t, o.id, shapes[o.id], 1.5, f"seepage pit, {T.PAGES['8.6.8']}")
        elif t.kind == "soakWell":
            if footprint is not None:
                add(t, "building", footprint, 4.5, f"building foundation, {T.PAGES['8.6.8']}")
            for o in tanks:
                if o.kind == "underground":
                    add(
                        t,
                        o.id,
                        shapes[o.id],
                        15.0,
                        f"reservoir as a well (SAEngine), {T.PAGES['8.6.8']}",
                    )
                elif o.kind == "soakWell" and o.id > t.id:
                    add(t, o.id, shapes[o.id], 6.0, f"seepage pit, {T.PAGES['8.6.8']}")
    return checks

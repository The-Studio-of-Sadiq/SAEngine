"""Lightning protection and earthing of the building (BNBC 2020 Part 8 Sec 1.3.32-1.3.33) and
what they ask of the structure.

- Need: the risk index, the sum of the indices A to G of Table 8.1.27 (use, construction,
  contents, isolation, terrain, height, thunderstorm days), against the marginal index 40 of
  Sec 1.3.33.5 (the examples of Table 8.1.28); a structure higher than 53 m requires protection
  in all cases (Table 8.1.27(c) note c). Thunderstorm days default to over 21 a year, the index
  BNBC's own examples use.
- Air termination: at least one air spike for every 80 m² of roof to begin with (Sec 1.3.33.7),
  each at least 300 mm above the highest point (Sec 1.3.33.6(a)); roof conductors round the
  roof's periphery and across it so that no part of the roof is more than 9 m from the nearest
  conductor (Sec 1.3.33.8(a)). With an IEC 62305 protection level, its mesh governs where it is
  smaller (from memory, to be checked).
- Down conductors (Sec 1.3.33.8(c)): one for a base area up to 100 m²; for a larger building one
  for the first 80 m² and one for every further 100 m² or part, or one for every 30 m of
  perimeter. SAEngine places them at columns on the perimeter that run without a break from
  the foundation to the roof (corners first, then splitting the longest gap), so that the
  columns' continuous reinforcement serves as the natural down conductor and the footings as the
  earth electrode.
- Earth: at most 10 ohm up to ten storeys and 2 ohm for high rise (Sec 1.3.33.8(b)); the
  electrical system earth around 1 ohm (Sec 1.3.32.7); electrodes at least 1.8 m apart; an earth
  inspection box for each down conductor 1000 mm above the plinth (Sec 1.3.33.6(e)). The
  clearance from a conductor to other metal: D = 0.3 R + H / (15 n) (Eq 8.1.1), else bonding.
- Reinforcement as a down conductor (BNBC says nothing of it): IEC 62305-3, the vertical bars
  made continuous (welded or clamped laps) with an overall resistance of at most 0.2 ohm from
  the top to the ground level (from memory, to be checked).
"""

from __future__ import annotations

import math
from typing import Any

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from saengine.electrical import tables as T
from saengine.plumbing.building import Building

#: A column is on the perimeter when its centre is this close to the footprint's edge [mm].
EDGE = 1000.0
#: Column pieces of one line join when the gap between them is at most this [mm].
JOIN = 50.0
#: A corner of the footprint: its edges turn by more than this [°].
CORNER_ANGLE = 30.0


def _check(name: str, demand: float, cap: float | None, unit: str, ok: bool, note: str):
    util = demand / cap if cap else (0.0 if demand == 0 else math.inf)
    return {"name": name, "demand": demand, "capacity": cap, "unit": unit,
            "utilisation": util, "ok": bool(ok), "note": note}  # fmt: skip


def _outer(shape: Any) -> Polygon | None:
    """The largest polygon of a (multi)polygon."""
    if shape is None or shape.is_empty:
        return None
    if isinstance(shape, Polygon):
        return shape
    return max(shape.geoms, key=lambda p: p.area)


# ─────────────────────────────────────── risk ───────────────────────────────────────


def risk_index(lightning: Any, uses: list[str], height_m: float) -> dict[str, Any]:
    """Table 8.1.27's indices and their sum; ``decision``: 'required', 'recommended' or
    'notRequired'."""
    a = max((T.USES[u].lightning_a for u in uses if u in T.USES), default=7)
    c = (
        T.CONTENTS[lightning.contents][1]
        if lightning.contents
        else max((T.USES[u].lightning_c for u in uses if u in T.USES), default=2)
    )
    b = T.CONSTRUCTION[lightning.construction][1]
    d = T.ISOLATION[lightning.isolation][1]
    e = T.TERRAIN[lightning.terrain][1]
    f = T.height_index(height_m)
    g = (
        T.thunder_index(lightning.thunderstormDays)
        if lightning.thunderstormDays is not None
        else T.THUNDER_DEFAULT
    )
    indices = {"A": a, "B": b, "C": c, "D": d, "E": e, "F": f, "G": g}
    if f is None:
        return {"indices": indices, "total": None, "decision": "required",
                "note": f"higher than {T.ALWAYS_HEIGHT:g} m: protection in all cases "
                f"({T.PAGES['8.1.27']} note c)"}  # fmt: skip
    total = a + b + c + d + e + f + g
    if total >= T.MARGINAL_RISK:
        decision = "recommended"
        note = (f"risk index {total} at or above the marginal {T.MARGINAL_RISK} "
                f"({T.PAGES['8.1.27']}, {T.PAGES['8.1.28']}): protection needed, more so the "
                "more important the building")  # fmt: skip
    else:
        decision = "notRequired"
        note = (f"risk index {total} below the marginal {T.MARGINAL_RISK}: no protection needed "
                f"in general ({T.PAGES['8.1.28']})")  # fmt: skip
    return {"indices": indices, "total": total, "decision": decision, "note": note}


def down_conductors_needed(base_area: float, perimeter_mm: float, rule: str, level: str | None):
    """(count, spacing limit along the perimeter mm, how) of Sec 1.3.33.8(c)."""
    if base_area <= T.DOWN_SINGLE_AREA:
        n, how = 1, f"base area {base_area:.0f} m² up to {T.DOWN_SINGLE_AREA:g} m²: one"
    elif rule == "area":
        n = 1 + math.ceil((base_area - T.DOWN_FIRST_AREA) / T.DOWN_STEP_AREA - 1e-9)
        how = (f"one for the first {T.DOWN_FIRST_AREA:g} m² + one for every "
               f"{T.DOWN_STEP_AREA:g} m² or part of {base_area - T.DOWN_FIRST_AREA:.0f} m²")  # fmt: skip
    else:
        n = max(1, math.ceil(perimeter_mm / T.DOWN_PERIMETER - 1e-9))
        how = (f"one for every {T.DOWN_PERIMETER / 1000:g} m of the "
               f"{perimeter_mm / 1000:.1f} m perimeter")  # fmt: skip
    spacing = T.DOWN_PERIMETER
    if level is not None:
        level_spacing = T.IEC_LEVELS[level][2] * 1000.0
        n_level = max(1, math.ceil(perimeter_mm / level_spacing - 1e-9))
        if n_level > n:
            n, how = n_level, (f"IEC 62305-3 class {level}: every {level_spacing / 1000:g} m "
                               "of perimeter (IEC 62305-3 Table 4)")  # fmt: skip
        spacing = min(spacing, level_spacing)
    return n, spacing, how


# ─────────────────────────────────── columns ───────────────────────────────────


def column_lines(bim: Any, roof_level: float) -> list[dict[str, Any]]:
    """The building model's columns grouped by plan position: ``[{x, y, ids (lowest first),
    bottom, top, continuous}]``, continuous when the pieces join without a break from the
    lowest to the roof level."""
    if bim is None:
        return []
    groups: dict[tuple[int, int], list[Any]] = {}
    for e in bim.elements:
        if e.kind == "column":
            groups.setdefault((round(e.position[0]), round(e.position[1])), []).append(e)
    lines = []
    for (x, y), pieces in groups.items():
        pieces.sort(key=lambda c: c.bottom)
        reach = pieces[0].bottom
        broken = False
        for c in pieces:
            if c.bottom > reach + JOIN:
                broken = True
            reach = max(reach, c.top)
        lines.append({
            "x": float(x), "y": float(y), "ids": [c.id for c in pieces],
            "bottom": pieces[0].bottom, "top": reach,
            "continuous": not broken and reach >= roof_level - JOIN,
        })  # fmt: skip
    return lines


def _corners(ring: Polygon) -> list[tuple[float, float]]:
    pts = list(ring.exterior.coords)[:-1]
    out = []
    for i, p in enumerate(pts):
        a, b = pts[i - 1], pts[(i + 1) % len(pts)]
        u = (p[0] - a[0], p[1] - a[1])
        v = (b[0] - p[0], b[1] - p[1])
        nu, nv = math.hypot(*u), math.hypot(*v)
        if nu == 0 or nv == 0:
            continue
        cos = max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / (nu * nv)))
        if math.degrees(math.acos(cos)) > CORNER_ANGLE:
            out.append(p)
    return out


def choose_down_conductors(
    lines: list[dict[str, Any]], outline: Polygon, n: int, spacing: float
) -> tuple[list[dict[str, Any]], float]:
    """Columns for ``n`` down conductors round ``outline``: corners first, then the column
    nearest the middle of the longest gap, until there are ``n`` and no gap along the perimeter
    exceeds ``spacing``. Returns (chosen, largest gap mm)."""
    ring = outline.exterior
    perimeter = ring.length
    candidates = []
    for line in lines:
        if not line["continuous"]:
            continue
        p = Point(line["x"], line["y"])
        if ring.distance(p) > EDGE:
            continue
        candidates.append({**line, "s": ring.project(p)})
    if not candidates:
        return [], perimeter
    chosen: list[dict[str, Any]] = []
    for corner in _corners(outline):
        best = min(candidates, key=lambda c: math.dist((c["x"], c["y"]), corner))
        if math.dist((best["x"], best["y"]), corner) <= EDGE * 1.5 and best not in chosen:
            chosen.append(best)
    if len(chosen) > n and n < len(_corners(outline)):
        chosen = _spread(chosen, n, perimeter)
    if not chosen:
        chosen = [candidates[0]]

    def gaps() -> list[tuple[float, float, float]]:
        s = sorted(c["s"] for c in chosen)
        out = []
        for i, a in enumerate(s):
            b = s[(i + 1) % len(s)] + (perimeter if i + 1 == len(s) else 0.0)
            out.append((b - a, a, b))
        return out

    while len(chosen) < len(candidates):
        largest = max(gaps())
        if len(chosen) >= n and largest[0] <= spacing + 1e-6:
            break
        middle = ((largest[1] + largest[2]) / 2) % perimeter
        rest = [c for c in candidates if c not in chosen]

        chosen.append(min(rest, key=lambda c, m=middle: _along(c["s"], m, perimeter)))
    chosen.sort(key=lambda c: c["s"])
    return chosen, max(gaps())[0] if len(chosen) > 1 else perimeter


def _along(a: float, b: float, perimeter: float) -> float:
    """Distance between two positions along a closed perimeter."""
    d = abs(a - b) % perimeter
    return min(d, perimeter - d)


def _spread(items: list[dict[str, Any]], n: int, perimeter: float) -> list[dict[str, Any]]:
    items = sorted(items, key=lambda c: c["s"])
    step = perimeter / n
    picked: list[dict[str, Any]] = []
    for k in range(n):
        target = items[0]["s"] + k * step
        best = min((c for c in items if c not in picked),
                   key=lambda c: min(abs(c["s"] - target), perimeter - abs(c["s"] - target)))  # fmt: skip
        picked.append(best)
    return picked


def foundations_of(bim: Any, substructure: Any) -> dict[str, str]:
    """Column id -> the foundation under it: a 09 Substructure foundation that carries it (its
    ``columns``), else a 06 BIM footing at its position."""
    out: dict[str, str] = {}
    for f in (substructure or {}).get("foundations", []) if isinstance(substructure, dict) else []:
        for column in f.get("columns") or []:
            out.setdefault(str(column), str(f.get("id")))
    if bim is not None:
        footings = [e for e in bim.elements if e.kind == "footing"]
        for e in bim.elements:
            if e.kind != "column" or e.id in out:
                continue
            for f in footings:
                if math.dist(f.position, e.position) <= 10.0:
                    out[e.id] = f.id
                    break
    return out


# ─────────────────────────────── air termination ───────────────────────────────


def air_terminals(roof: Polygon, level: float, spacing: float | None = None) -> list[list[float]]:
    """Air spikes on a grid over the roof, at least one for every 80 m² (Sec 1.3.33.7) and
    300 mm above the roof level."""
    minx, miny, maxx, maxy = roof.bounds
    area = roof.area / 1e6
    need = max(1, math.ceil(area / T.SPIKE_AREA - 1e-9))
    step = spacing or math.sqrt(T.SPIKE_AREA) * 1000.0
    nx = max(1, math.ceil((maxx - minx) / step - 1e-9))
    ny = max(1, math.ceil((maxy - miny) / step - 1e-9))
    for _ in range(20):
        dx, dy = (maxx - minx) / nx, (maxy - miny) / ny
        pts = [
            [round(minx + (i + 0.5) * dx), round(miny + (j + 0.5) * dy), level + T.SPIKE_HEIGHT]
            for j in range(ny)
            for i in range(nx)
        ]
        pts = [p for p in pts if roof.covers(Point(p[0], p[1]))]
        if len(pts) >= need:
            return pts
        if dx >= dy:
            nx += 1
        else:
            ny += 1
    return pts


def roof_conductors(roof: Polygon, reach: float) -> tuple[list[list[list[float]]], float]:
    """The roof conductors (the roof's periphery and lines across it at no more than twice the
    reach apart) and the largest distance from the roof to the nearest conductor [mm]."""
    minx, miny, maxx, maxy = roof.bounds
    spacing = 2 * reach
    lines: list[Any] = [roof.exterior]
    nx = max(1, math.ceil((maxx - minx) / spacing - 1e-9))
    ny = max(1, math.ceil((maxy - miny) / spacing - 1e-9))
    for i in range(1, nx):
        x = minx + i * (maxx - minx) / nx
        lines.append(roof.intersection(LineString([(x, miny - 1), (x, maxy + 1)])))
    for j in range(1, ny):
        y = miny + j * (maxy - miny) / ny
        lines.append(roof.intersection(LineString([(minx - 1, y), (maxx + 1, y)])))
    network = unary_union([g for g in lines if not g.is_empty])
    out = []
    for g in getattr(network, "geoms", [network]):
        for part in getattr(g, "geoms", [g]):
            if isinstance(part, LineString):
                out.append([[round(x, 1), round(y, 1)] for x, y in part.coords])
    worst = 0.0
    steps = 24
    for i in range(steps + 1):
        for j in range(steps + 1):
            p = Point(minx + i * (maxx - minx) / steps, miny + j * (maxy - miny) / steps)
            if roof.covers(p):
                worst = max(worst, network.distance(p))
    return out, worst


# ─────────────────────────────────────── the design ───────────────────────────────────────


def lightning_protection(
    lightning: Any,
    building: Building,
    bim: Any,
    uses: list[str],
    storeys: int,
    height_m: float,
    substructure: Any = None,
) -> dict[str, Any]:
    """The lightning protection: need, air terminals, roof conductors, down-conductor columns,
    earth terminals, checks and the notes for the structural drawings."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []
    risk = risk_index(lightning, uses, height_m)
    needed = risk["decision"] != "notRequired"
    checks.append(_check("Lightning protection", 1 if needed else 0, 1 if lightning.enabled else 0,
                         "", lightning.enabled or not needed,
                         risk["note"] + ("" if lightning.enabled else "; 07 MEP disables it")))  # fmt: skip
    # The roof: the slabs of the highest story that has any (a top level without slabs is
    # the column tops of an unfinished model).
    top = next((s for s in reversed(building.ordered()) if building.slabs_at(s)), None)
    roof = _outer(building.roof(top)) if top else None
    footprint = _outer(building.footprint())
    out: dict[str, Any] = {"risk": risk, "required": needed, "enabled": lightning.enabled,
                           "level": lightning.level, "downConductors": [], "airTerminals": [],
                           "roofConductors": [], "earth": None, "checks": checks,
                           "structuralNotes": [], "notes": notes}  # fmt: skip
    if roof is None or footprint is None:
        notes.append("no slabs in 06 BIM: no roof, footprint or down conductors")
        return out
    roof_level = building.stories[top]
    base_area = footprint.area / 1e6
    perimeter = footprint.exterior.length
    n, spacing, how = down_conductors_needed(base_area, perimeter, lightning.rule, lightning.level)
    lines = column_lines(bim, roof_level)
    chosen, gap = choose_down_conductors(lines, footprint, n, spacing)
    bases = foundations_of(bim, substructure)
    rebar = lightning.downConductors == "structuralRebar"
    conductors = []
    for k, line in enumerate(chosen, start=1):
        foundation = next((bases[i] for i in line["ids"] if i in bases), None)
        conductors.append({
            "id": f"DC{k}", "x": line["x"], "y": line["y"], "columns": line["ids"],
            "foundation": foundation, "testBox": T.TEST_BOX_HEIGHT,
            "conductor": "column reinforcement" if rebar else T.LIGHTNING_SIZES["downConductor"],
        })  # fmt: skip
    out["downConductors"] = conductors
    out["downConductorsNeeded"] = n
    out["basis"] = how
    out["baseArea"] = base_area
    out["perimeter"] = perimeter
    checks.append(_check("Down conductors", n, len(conductors), "", len(conductors) >= n,
                         f"{how} ({T.cite('1.3.33.8', '(c)')})"))  # fmt: skip
    if len(conductors) > 1:
        checks.append(_check("Down conductor spacing", gap, spacing, "mm", gap <= spacing + 1e-6,
                             "largest gap along the perimeter"))  # fmt: skip
    if not lines:
        notes.append("no columns in 06 BIM: place the down conductors on the perimeter")
    elif len(conductors) < n:
        notes.append(
            f"only {len(conductors)} perimeter columns run without a break to the roof: add "
            "dedicated down conductors"
        )
    # Air termination.
    mesh = T.ROOF_CONDUCTOR_REACH
    if lightning.level is not None:
        mesh = min(mesh, T.IEC_LEVELS[lightning.level][1] * 1000.0 / 2)
    terminals = (
        [list(p) for p in lightning.airTerminals]
        if lightning.airTerminals
        else air_terminals(roof, roof_level)
    )
    need_spikes = max(1, math.ceil(roof.area / 1e6 / T.SPIKE_AREA - 1e-9))
    out["airTerminals"] = terminals
    out["airTerminalsProposed"] = not lightning.airTerminals
    checks.append(_check("Air terminals", need_spikes, len(terminals), "", len(terminals) >= need_spikes,
                         f"one for every {T.SPIKE_AREA:g} m² of the {roof.area / 1e6:.0f} m² roof "
                         f"to begin with ({T.PAGES['1.3.33.7']})"))  # fmt: skip
    conductors_roof, worst = roof_conductors(roof, mesh)
    out["roofConductors"] = conductors_roof
    checks.append(_check("Roof conductor reach", worst, mesh, "mm", worst <= mesh + 1e-6,
                         f"no part of the roof more than {mesh / 1000:g} m from a conductor "
                         f"({T.cite('1.3.33.8', '(a)')})"))  # fmt: skip
    # Earth.
    limit = T.LIGHTNING_EARTH_OHM["highRise" if storeys > 10 else "upTo10"]
    r = lightning.earthResistance or limit
    clearance = 0.3 * r + height_m / (15 * max(len(conductors), 1))
    out["earth"] = {
        "limit": limit, "systemEarth": T.SYSTEM_EARTH_OHM, "resistance": r,
        "clearance": clearance, "electrodeSpacing": T.ELECTRODE_SPACING,
        "arrangement": lightning.earthing,
    }  # fmt: skip
    if lightning.earthResistance is not None:
        checks.append(_check("Lightning earth resistance", r, limit, "ohm", r <= limit,
                             f"{T.cite('1.3.33.8', '(b)')}"))  # fmt: skip
    notes.append(
        f"clearance from the conductors to other metal D = 0.3 x {r:g} + {height_m:.1f} / (15 x "
        f"{max(len(conductors), 1)}) = {clearance:.2f} m ({T.PAGES['8.1.1']}), else bond them"
    )
    out["structuralNotes"] = structural_notes(lightning, conductors, limit)
    return out


def structural_notes(lightning: Any, conductors: list[dict[str, Any]], limit: float) -> list[str]:
    """The notes the structural drawings carry for the lightning protection and earthing."""
    columns = ", ".join(c["columns"][0] for c in conductors) or "none"
    notes = [f"Down-conductor column lines: {columns}."]
    if lightning.downConductors == "structuralRebar":
        notes += [
            (
                "In each down-conductor column line make at least two vertical bars electrically "
                "continuous from the foundation to the roof: weld or clamp the laps (IEC 62305-3 "
                "4.3, 5.3.5: reinforcement as a natural down conductor); overall resistance from the "
                "roof to the ground at most "
                f"{T.REBAR_OHM:g} ohm, measured before the finishes."
            ),
            (
                "Bring a bonding terminal (steel plate or bar welded to the continuous bars) out at "
                "the roof to connect the roof conductors and air terminals, and at the base for the "
                "earth."
            ),
        ]
    else:
        notes.append(
            f"Dedicated copper down conductors ({T.LIGHTNING_SIZES['downConductor']}, "
            f"{T.PAGES['8.1.29']}) on the down-conductor columns; fixings cast in or drilled."
        )
    notes += [
        (
            f"An earth inspection box for each down conductor {T.TEST_BOX_HEIGHT:g} mm above the "
            f"plinth, concealed in the wall ({T.cite('1.3.33.6', '(e)')}): leave its recess."
        ),
        (
            f"Earth: at most {limit:g} ohm ({T.cite('1.3.33.8', '(b)')}); electrodes at least "
            f"{T.ELECTRODE_SPACING / 1000:g} m apart ({T.PAGES['1.3.32.7']}), each with an earthing "
            f"pit at least {T.EARTH_PIT:g} x {T.EARTH_PIT:g} x {T.EARTH_PIT:g} mm inside "
            f"({T.PAGES['1.3.32.10']})."
        ),
    ]
    if lightning.earthing == "foundation":
        foundations = ", ".join(sorted({c["foundation"] for c in conductors if c["foundation"]}))
        notes.append(
            "Foundation earth electrode: bond the bottom bars of the footings or pile caps"
            + (f" ({foundations})" if foundations else "")
            + " and the tie beams into a continuous ring, with an earth terminal at each "
            "down-conductor column (IEC 62305-3 5.4: foundation earth electrode); keep the bonding "
            "out of the cover zone."
        )
    else:
        notes.append(
            "Earth electrodes (pipes or rods) outside the foundations: keep their pits clear of "
            "the footings and tie beams."
        )
    notes.append(
        "Parapets, roof tanks, plant and other metal on the roof are bonded to the roof "
        f"conductors ({T.cite('1.3.33.8', '(f)')}); air terminals on cast-in bases 152 x 152 x 13 mm."
    )
    return notes

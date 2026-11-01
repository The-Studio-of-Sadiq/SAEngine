"""MEP sheets: the plumbing and drainage, HVAC, electrical and fire protection plans of each
story, the MEP coordination plan (every service with the shafts and the sleeves through the
structure) and the MEP schedules (risers, equipment, tanks, sleeves and openings). Drawn from the
building services model of ``07 MEP/mep.json`` (:mod:`saengine.library.mep`) as it is: the
positions, sizes and stories the engineer entered there or SAEngine's sizing proposed and the
engineer kept. Nothing is sized or routed here; a riser without a diameter shows the sizing's
(:func:`saengine.plumbing.report.plumbing_results`) when it gives one.

Each plan is drawn over the structure (grids, columns and walls as on the framing plans) and the
architectural walls as outlines, so that the services read against the building. The wet rooms
are those of :func:`saengine.mep.rooms.room_inputs` (the rooms of the architecture with the wet
flag, their kind and fixtures), never worked out again here.

Sheet numbers: one prefix per discipline (``P-``, ``M-``, ``E-``, ``FP-``, ``MC-``; the office
standard may name them otherwise, :mod:`.standards`). Layers: docs/drawings-layers.md.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import LineString

from saengine.drawings.sheets.layout import TEXT, View, ViewSpec
from saengine.drawings.sheets.model import Building, Level, Point, Table
from saengine.drawings.sheets.plans import (
    DIM_1,
    DIM_2,
    EPS,
    _bounds,
    _columns,
    _level_points,
    _walls,
    grids,
)

#: (key, sheet title, sheet number prefix): the disciplines in sheet order.
DISCIPLINES: tuple[tuple[str, str, str], ...] = (
    ("plumbing", "Plumbing and drainage plans", "P-"),
    ("mechanical", "HVAC plans", "M-"),
    ("electrical", "Electrical plans", "E-"),
    ("fire", "Fire protection plans", "FP-"),
    ("coordination", "MEP coordination plans", "MC-"),
)
SCHEDULE_PREFIX = "MC-"

PLAN_NOTES = {
    "plumbing": [
        "Risers and stacks are drawn where they rise through the story (07 MEP).",
        (
            "CW cold water, HW hot water, PM pump main, SS soil, WS waste, SWS soil and waste, "
            "VS vent stack, RWP rainwater pipe, RD roof drain."
        ),
        (
            "Wet rooms: their kind and fixtures (WC water closet, UR urinal, WB wash basin, SH "
            "shower, BT bathtub, KS kitchen sink, FD floor drain, WM washing machine, BD bidet)."
        ),
        "Pipe sizes in mm (nominal); sized: by the plumbing sizing of 07 MEP.",
    ],
    "mechanical": [
        (
            "Ducts: width x height (or diameter) in mm and their system: SA supply, RA return, "
            "EA exhaust, FA fresh air, KE kitchen exhaust, SE smoke extract."
        ),
        "Plant: its kind and capacity (kW cooling, m³/s for fans).",
        "Bottom of duct levels as in 07 MEP; coordinate with the beams on the coordination plan.",
    ],
    "electrical": [
        "Equipment with its rating (kVA, kW or A); electrical rooms outlined.",
        (
            "Cable trays: width x side height in mm; risers: busbar trunking, cable tray, cable "
            "ladder or conduit bank."
        ),
        "Lightning protection air terminals (AT) on the roof plan.",
    ],
    "fire": [
        "Risers: SP standpipe, SPR sprinkler, CMB combined; mains in the ceiling space.",
        "Pumps: main, standby and jockey with flow and head; the pump room outlined.",
        "Pipe sizes in mm (nominal).",
    ],
    "coordination": [
        (
            "Every service of 07 MEP on one plan, with the service shafts (phantom) and the "
            "sleeves and openings through beams, slabs and walls."
        ),
        "Sleeve and opening marks refer to the sleeve and opening schedule.",
        "Check clear heights and sleeve positions against the structure before construction.",
    ],
}
SCHEDULE_NOTES = [
    "Sizes and positions as in 07 MEP; sized: by SAEngine's sizing (07 MEP reports).",
    "Weights are operating weights [kN], the loads the structure carries (07 MEP).",
]

RISER_ABBREVIATIONS = {
    "coldWater": "CW",
    "hotWater": "HW",
    "soil": "SS",
    "waste": "WS",
    "soilWaste": "SWS",
    "vent": "VS",
    "rainwater": "RWP",
    "pumpMain": "PM",
}
RISER_LAYERS = {
    "coldWater": "P-DOMW",
    "hotWater": "P-DOMW",
    "pumpMain": "P-DOMW",
    "soil": "P-SANR",
    "waste": "P-SANR",
    "soilWaste": "P-SANR",
    "vent": "P-SANR",
    "rainwater": "P-STRM",
}
DUCT_ABBREVIATIONS = {
    "supply": "SA",
    "return": "RA",
    "exhaust": "EA",
    "freshAir": "FA",
    "kitchenExhaust": "KE",
    "smoke": "SE",
}
FIRE_RISER_ABBREVIATIONS = {"standpipe": "SP", "sprinkler": "SPR", "combined": "CMB"}
FIXTURE_ABBREVIATIONS = {
    "wc": "WC",
    "urinal": "UR",
    "basin": "WB",
    "shower": "SH",
    "bathtub": "BT",
    "kitchenSink": "KS",
    "floorDrain": "FD",
    "washingMachine": "WM",
    "bidet": "BD",
}
EQUIPMENT_LAYERS = {
    "tank": "P-EQPM",
    "pump": "P-EQPM",
    "chiller": "M-EQPM",
    "ahu": "M-EQPM",
    "generator": "E-EQPM",
    "transformer": "E-EQPM",
    "lift": "M-EQPM",
    "other": "M-EQPM",
}
POINT_SIZE = 100.0  # mm, the circle of a riser or drain without a size
RISER_BOX = 300.0  # mm, the square of a riser without a size


# ─────────────────────────────────── what is drawn ───────────────────────────────────


@dataclass
class Item:
    """One thing on an MEP plan: a ``point`` (a circle of ``size``), a ``box`` (``points``:
    its outline), a ``path`` (``points`` a polyline ``size`` wide, 0: a single line) or an
    ``outline`` (a closed polygon); ``mark`` its tag."""

    discipline: str
    shape: str
    layer: str
    mark: str
    points: list[Point]
    size: float = 0.0
    cross: bool = False  # a riser through the floor: a cross in its box


@dataclass
class MepDrawing:
    """The 07 MEP model (:class:`saengine.library.mep.MepModel`) with what the plans need from
    elsewhere: the wet rooms (:class:`saengine.mep.rooms.RoomInputs`) and the sized diameters of
    the risers and stacks (by id) when the sizing gives them."""

    model: Any
    rooms: Any = None
    sized: dict[str, float] = field(default_factory=dict)


def _rect(cx: float, cy: float, lx: float, ly: float, rotation: float = 0.0) -> list[Point]:
    c, s = math.cos(math.radians(rotation)), math.sin(math.radians(rotation))
    out = []
    for u, v in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        du, dv = u * lx / 2, v * ly / 2
        out.append((cx + du * c - dv * s, cy + du * s + dv * c))
    return out


def _mm(value: Any) -> str:
    return f"{float(value):g}"


def _levels(building: Building) -> list[Level]:
    return sorted(building.levels, key=lambda lv: lv.elevation)


def _span(building: Building, start: str | None, end: str | None) -> list[str]:
    """The ids of the stories from ``start`` to ``end`` (by elevation, both included)."""
    by_id = {lv.id: lv for lv in building.levels}
    if start not in by_id or end not in by_id:
        return []
    lo, hi = sorted((by_id[start].elevation, by_id[end].elevation))
    return [lv.id for lv in _levels(building) if lo - EPS <= lv.elevation <= hi + EPS]


def _tank_level(building: Building, tank: Any) -> str | None:
    """The story a tank is drawn on: its own; an overhead tank without one on the top story,
    the others (underground, septic, soak well, rainwater) on the lowest."""
    levels = _levels(building)
    if not levels:
        return None
    if getattr(tank, "story", None) and building.level(tank.story) is not None:
        return tank.story
    return levels[-1].id if tank.kind == "overhead" else levels[0].id


def _tank_item(discipline: str, layer: str, tank: Any, label: str) -> Item:
    if tank.diameter and not (tank.length and tank.width):
        size = f"Ø{_mm(tank.diameter)}"
        return Item(discipline, "point", layer, f"{tank.id} {label}\n{size}",
                    [(tank.x, tank.y)], float(tank.diameter))  # fmt: skip
    length = float(tank.length or 1000.0)
    width = float(tank.width or 1000.0)
    depth = f" x {_mm(tank.waterDepth)} WATER" if tank.waterDepth else ""
    return Item(discipline, "box", layer, f"{tank.id} {label}\n{_mm(length)} x {_mm(width)}{depth}",
                _rect(tank.x, tank.y, length, width))  # fmt: skip


def _box_item(discipline: str, layer: str, thing: Any, mark: str, default: float = 600.0) -> Item:
    length = float(getattr(thing, "length", None) or default)
    width = float(getattr(thing, "width", None) or default)
    rotation = float(getattr(thing, "rotation", 0.0) or 0.0)
    return Item(discipline, "box", layer, mark, _rect(thing.x, thing.y, length, width, rotation))


def items_by_level(drawing: MepDrawing, building: Building) -> dict[str, list[Item]]:
    """Everything the MEP plans draw, by story id."""
    from saengine.library import mep as ml

    mep = drawing.model
    out: dict[str, list[Item]] = {}

    def add(level: str | None, item: Item) -> None:
        if level is not None and building.level(level) is not None:
            out.setdefault(level, []).append(item)

    linked = set()  # 07 MEP equipment drawn as a plant, tank, pump or electrical item
    # plumbing and drainage
    plumbing = mep.plumbing
    if plumbing is not None:
        for r in plumbing.risers:
            dia = r.diameter or drawing.sized.get(r.id)
            size = f" Ø{_mm(dia)}" if dia else ""
            sized = " (SIZED)" if dia and not r.diameter else ""
            material = f" {r.material}" if r.material else ""
            mark = f"{r.id} {RISER_ABBREVIATIONS.get(r.system, r.system)}{size}{material}{sized}"
            layer = RISER_LAYERS.get(r.system, "P-DOMW")
            for level in _span(building, r.fromStory, r.toStory):
                add(level, Item("plumbing", "point", layer, mark, [(r.x, r.y)],
                                float(dia or POINT_SIZE)))  # fmt: skip
        for t in plumbing.tanks:
            if t.equipment:
                linked.add(t.equipment)
            add(_tank_level(building, t),
                _tank_item("plumbing", "P-EQPM", t, ml.TANK_KINDS.get(t.kind, t.kind).upper()))  # fmt: skip
        if plumbing.roof is not None:
            for d in plumbing.roof.drains:
                add(d.story, Item("plumbing", "point", "P-STRM", f"{d.id} RD", [(d.x, d.y)], 150.0))
    rooms = drawing.rooms
    if rooms is not None:
        for story in rooms.stories.values():
            for room in story.wet:
                counts = ", ".join(
                    f"{n} {FIXTURE_ABBREVIATIONS.get(k, k.upper())}"
                    for k, n in (room.fixtures or {}).items()
                    if n
                )
                name = f"{room.number} {room.name}".strip().upper()
                kind = ml.WET_ROOM_KINDS.get(room.kind, room.kind or "")
                ring = [(float(x), float(y)) for x, y, *_ in room.net.exterior.coords[:-1]]
                add(story.story, Item("plumbing", "outline", "P-EQPM",
                                      f"{name} ({kind})\n{counts}".rstrip(), ring))  # fmt: skip
    # HVAC
    hvac = mep.hvac
    if hvac is not None:
        for p in hvac.plant:
            if p.equipment:
                linked.add(p.equipment)
            capacity = ""
            if p.capacity:
                capacity = f" {p.capacity:g} " + ("m³/s" if p.kind == "exhaustFan" else "kW")
            label = ml.HVAC_PLANT_KINDS.get(p.kind, p.kind).upper()
            add(p.story, _box_item("mechanical", "M-EQPM", p, f"{p.id} {label}{capacity}"))
        for d in hvac.ducts:
            if d.shape == "round" and d.diameter:
                size, width = f"Ø{_mm(d.diameter)}", float(d.diameter)
            elif d.width:
                size = f"{_mm(d.width)}x{_mm(d.height)}" if d.height else _mm(d.width)
                width = float(d.width)
            else:
                size, width = "", 0.0
            system = DUCT_ABBREVIATIONS.get(d.system, d.system)
            bottom = f" BOD +{d.bottom / 1000:.3f}" if d.bottom is not None else ""
            mark = f"{d.id} {size} {system}{bottom}".replace("  ", " ")
            path = [(float(x), float(y)) for x, y in d.path]
            if len(path) >= 2:
                add(d.story, Item("mechanical", "path", "M-DUCT", mark, path, width))
            if d.riser is not None:
                side = max(width, RISER_BOX)
                for level in _span(building, d.riser.fromStory, d.riser.toStory):
                    add(level, Item("mechanical", "box", "M-DUCT", f"{d.id} {system} RISER",
                                    _rect(*path[0], side, side), cross=True))  # fmt: skip
    # electrical
    electrical = mep.electrical
    if electrical is not None:
        for e in electrical.equipment:
            if e.equipment:
                linked.add(e.equipment)
            unit = {"lvPanel": "A", "distributionBoard": "A", "solarPv": "kW"}.get(e.kind, "kVA")
            rating = f" {e.rating:g} {unit}" if e.rating else ""
            label = ml.ELECTRICAL_EQUIPMENT_KINDS.get(e.kind, e.kind).upper()
            add(e.story, _box_item("electrical", "E-EQPM", e, f"{e.id} {label}{rating}"))
        for r in electrical.risers:
            w = float(r.width or RISER_BOX)
            d = float(r.depth or RISER_BOX)
            rating = f" {r.rating:g} A" if r.rating else ""
            label = ml.ELECTRICAL_RISER_KINDS.get(r.kind, r.kind).upper()
            for level in _span(building, r.fromStory, r.toStory):
                add(level, Item("electrical", "box", "E-CABL", f"{r.id} {label}{rating}",
                                _rect(r.x, r.y, w, d), cross=True))  # fmt: skip
        for t in electrical.trays:
            path = [(float(x), float(y)) for x, y in t.path]
            mark = f"{t.id} TRAY {_mm(t.width)}x{_mm(t.height)}"
            add(t.story, Item("electrical", "path", "E-CABL", mark, path, float(t.width)))
        for room in electrical.rooms:
            label = ml.ELECTRICAL_ROOM_KINDS.get(room.kind, room.kind).upper()
            add(room.story, Item("electrical", "outline", "E-EQPM", f"{room.id} {label}",
                                 [(float(x), float(y)) for x, y in room.outline]))  # fmt: skip
        lightning = electrical.lightning
        levels = _levels(building)
        if lightning is not None and lightning.enabled and lightning.airTerminals and levels:
            for i, (x, y, _z) in enumerate(lightning.airTerminals, 1):
                add(levels[-1].id, Item("electrical", "point", "E-EQPM", f"AT{i}",
                                        [(float(x), float(y))], 150.0, cross=True))  # fmt: skip
    # fire protection
    fire = mep.fire
    if fire is not None:
        for r in fire.risers:
            size = f" Ø{_mm(r.diameter)}" if r.diameter else ""
            mark = f"{r.id} {FIRE_RISER_ABBREVIATIONS.get(r.system, r.system)}{size}"
            for level in _span(building, r.fromStory, r.toStory):
                add(level, Item("fire", "point", "F-PROT", mark, [(r.x, r.y)],
                                float(r.diameter or POINT_SIZE)))  # fmt: skip
        for m in fire.mains:
            size = f" Ø{_mm(m.diameter)}" if m.diameter else ""
            path = [(float(x), float(y)) for x, y in m.path]
            add(m.story, Item("fire", "path", "F-PROT", f"{m.id} MAIN{size}", path))
        for p in fire.pumps:
            if p.equipment:
                linked.add(p.equipment)
            duty = ml.FIRE_PUMP_DUTIES.get(p.duty, p.duty).upper()
            rating = " ".join(
                part
                for part in (
                    f"{p.flow:g} l/min" if p.flow else "",
                    f"{p.head:g} m" if p.head else "",
                )
                if part
            )
            add(p.story, _box_item("fire", "F-EQPM", p, f"{p.id} {duty}\n{rating}".rstrip(), 800))
        if fire.pumpRoom is not None:
            add(fire.pumpRoom.story, Item("fire", "outline", "F-EQPM", "FIRE PUMP ROOM",
                                          [(float(x), float(y)) for x, y in fire.pumpRoom.outline]))  # fmt: skip
        for t in fire.tanks:
            if t.equipment:
                linked.add(t.equipment)
            add(_tank_level(building, t),
                _tank_item("fire", "F-EQPM", t, "FIRE " + ml.TANK_KINDS.get(t.kind, t.kind).upper()))  # fmt: skip
    # the coordination plan's own: other equipment, shafts, sleeves and openings
    for e in mep.equipment:
        if e.id in linked:
            continue
        label = (e.name or ml.EQUIPMENT_KINDS.get(e.kind, e.kind)).upper()
        add(e.story, _box_item("coordination", EQUIPMENT_LAYERS.get(e.kind, "M-EQPM"), e,
                               f"{e.id} {label}"))  # fmt: skip
    for s in mep.shafts:
        outline = [(float(x), float(y)) for x, y in s.outline]
        mark = f"{s.id} {s.service}".strip().upper()
        for level in _span(building, s.fromStory, s.toStory):
            add(level, Item("shaft", "outline", "M-SHFT", mark, outline))
    for o in mep.openings:
        placed = opening_place(o, building)
        if placed is None:
            continue
        level, centre, direction, across = placed
        if o.shape == "circle":
            size = f"Ø{_mm(o.diameter or 0)}"
            item = Item("coordination", "point", "M-SLEV", f"{o.id} {size}", [centre],
                        float(o.diameter or POINT_SIZE), cross=True)  # fmt: skip
        else:
            w = float(o.width or POINT_SIZE)
            h = float(o.height or POINT_SIZE)
            angle = math.degrees(math.atan2(direction[1], direction[0]))
            item = Item("coordination", "box", "M-SLEV", f"{o.id} {_mm(w)}x{_mm(h)}",
                        _rect(*centre, w, across or h, angle), cross=True)  # fmt: skip
        add(level, item)
    return out


def opening_place(o: Any, building: Building) -> tuple[str, Point, Point, float | None] | None:
    """Where a sleeve or opening of 07 MEP is drawn: ``(story id, plan point, its host's
    direction, the host's width across it)``: in a beam at its distance along the beam (the
    plan of the beam's level), in a slab at its x, y (None: the opening's own height is its
    plan size), in a wall at its distance along the wall (the plan of the wall's base)."""
    levels = _levels(building)

    def level_at(z: float) -> str | None:
        found = [lv for lv in levels if lv.elevation <= z + EPS]
        return found[-1].id if found else (levels[0].id if levels else None)

    p = o.position
    for b in building.beams:
        if b.id == o.host and p.distance is not None:
            length = math.dist(b.start, b.end) or 1.0
            d = ((b.end[0] - b.start[0]) / length, (b.end[1] - b.start[1]) / length)
            point = (b.start[0] + d[0] * p.distance, b.start[1] + d[1] * p.distance)
            level = level_at(b.elevation)
            return (level, point, d, b.width) if level else None
    for s in building.slabs:
        if s.id == o.host and p.x is not None and p.y is not None:
            level = level_at(s.elevation)
            return (level, (p.x, p.y), (1.0, 0.0), None) if level else None
    for w in building.walls:
        if w.id == o.host and p.x is not None:
            length = math.dist(w.start, w.end) or 1.0
            d = ((w.end[0] - w.start[0]) / length, (w.end[1] - w.start[1]) / length)
            point = (w.start[0] + d[0] * p.x, w.start[1] + d[1] * p.x)
            level = level_at(w.bottom)
            return (level, point, d, w.thickness) if level else None
    return None


def _shows(item: Item, discipline: str) -> bool:
    """Whether a plan of ``discipline`` draws ``item`` (shafts on every plan; the
    coordination plan everything)."""
    return discipline == "coordination" or item.discipline in (discipline, "shaft")


def has_plan(items: Iterable[Item], discipline: str) -> bool:
    """Whether a story with ``items`` has a plan of ``discipline`` (more than shafts)."""
    return any(item.discipline != "shaft" and _shows(item, discipline) for item in items)


# ─────────────────────────────────── the plans ───────────────────────────────────


def _offset(path: Sequence[Point], by: float) -> list[Point]:
    """The polyline ``path`` offset ``by`` to its left (mitred)."""
    line = LineString(path).offset_curve(by, join_style="mitre")
    if line.is_empty or line.geom_type != "LineString":
        return list(path)
    return [(x, y) for x, y, *_ in line.coords]


def _draw(view: View, item: Item) -> None:
    if item.shape == "point":
        r = max(item.size / 2, view.real(0.8))
        view.circle(item.points[0], r, item.layer)
        if item.cross:
            c = item.points[0]
            view.line((c[0] - r, c[1] - r), (c[0] + r, c[1] + r), item.layer)
            view.line((c[0] - r, c[1] + r), (c[0] + r, c[1] - r), item.layer)
    elif item.shape in ("box", "outline"):
        view.polyline(item.points, item.layer, close=True)
        if item.cross:
            a, b, c, d = item.points[:4]
            view.line(a, c, item.layer)
            view.line(b, d, item.layer)
    elif item.shape == "path" and len(item.points) >= 2:
        if item.size > view.real(0.6):
            view.polyline(_offset(item.points, item.size / 2), item.layer)
            view.polyline(_offset(item.points, -item.size / 2), item.layer)
        else:
            view.polyline(item.points, item.layer)


def _tag(view: View, item: Item) -> None:
    if item.shape == "path" and len(item.points) >= 2:
        # at the middle of the longest leg
        a, b = max(zip(item.points, item.points[1:]), key=lambda ab: math.dist(*ab))
        anchor = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    elif item.shape == "point":
        anchor = item.points[0]
    else:
        xs, ys = [p[0] for p in item.points], [p[1] for p in item.points]
        anchor = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    half = 3.0
    if item.shape != "path":
        x0, y0, x1, y1 = _bounds(item.points)
        half = max(x1 - x0, y1 - y0) / 2 / view.scale + 1.5
    view.label(
        item.mark,
        anchor,
        [(half, half, "BL"), (-half, half, "BR"), (half, -half, "TL"), (-half, -half, "TR")],
        TEXT,
        leader=item.shape == "point",
        layer="M-ANNO",
    )


def _arch_walls(view: View, drawing_arch: Any, building: Building, level: Level) -> None:
    """The architectural walls of the story as outlines (no hatching, no openings)."""
    if drawing_arch is None:
        return
    from saengine.drawings.sheets import architecture as ar

    for w in ar.on_story(ar.wall_geometry(drawing_arch, building), level):
        ar.draw_outline(view, w.footprint, "A-WALL", lineweight=18)


def mep_plan(
    building: Building,
    items: Sequence[Item],
    level: Level,
    discipline: str,
    title: str,
    scale: float = 100,
    arch: Any = None,
) -> ViewSpec:
    """The ``discipline`` plan of ``level`` (``coordination``: every service)."""
    shown = [i for i in items if _shows(i, discipline)]
    points = _level_points(building, level) + [p for i in shown for p in i.points]
    bbox = _bounds(points)
    pad = (DIM_2 + 6, DIM_2 + 6, DIM_1 + 10, DIM_1 + 10)

    def draw(view: View) -> None:
        z = level.elevation
        grids(view, building, bbox)
        _columns(view, building, z + 1200)
        _walls(view, building, z + 1200, hatch=False)
        for s in (s for s in building.slabs if abs(s.elevation - z) < EPS):
            view.polyline(s.boundary, "S-SLAB", close=True, lineweight=13)
        _arch_walls(view, arch, building, level)
        # the services, then their tags clear of them
        for item in shown:
            _draw(view, item)
        for item in shown:
            _tag(view, item)

    return ViewSpec(
        title=f"{title} - {level.name}",
        scale=scale,
        bbox=bbox,
        draw=draw,
        pad=pad,
        subtitle=f"SCALE 1:{scale:g}   LEVEL +{level.elevation / 1000:.3f}",
        key=f"mep-{discipline}:{level.id}",
    )


# ─────────────────────────────────── the schedules ───────────────────────────────────


def _level_name(building: Building, level: str | None) -> str:
    found = building.level(level) if level else None
    return found.name if found else (level or "-")


def _column(key: str, title: str, width: int, align: str = "left") -> dict[str, Any]:
    return {"key": key, "title": title, "width": width, "align": align}


def riser_table(drawing: MepDrawing, building: Building) -> Table:
    """Every riser, stack and duct riser: mark, service, from and to, size, material, shaft."""
    from saengine.library import mep as ml

    mep = drawing.model
    rows: list[list[str]] = []

    def row(mark, service, start, end, size, material="", shaft=None):
        rows.append([mark, service, _level_name(building, start), _level_name(building, end),
                     size, material or "-", shaft or "-"])  # fmt: skip

    if mep.plumbing is not None:
        for r in mep.plumbing.risers:
            dia = r.diameter or drawing.sized.get(r.id)
            size = f"Ø{_mm(dia)}" + ("" if r.diameter or not dia else " (sized)") if dia else "-"
            row(r.id, ml.PLUMBING_SYSTEMS.get(r.system, r.system), r.fromStory, r.toStory,
                size, r.material or "", r.shaft)  # fmt: skip
    if mep.hvac is not None:
        for d in mep.hvac.ducts:
            if d.riser is None:
                continue
            size = (
                f"Ø{_mm(d.diameter)}"
                if d.shape == "round" and d.diameter
                else (f"{_mm(d.width)}x{_mm(d.height)}" if d.width and d.height else "-")
            )
            row(d.id, f"{ml.DUCT_SYSTEMS.get(d.system, d.system)} duct", d.riser.fromStory,
                d.riser.toStory, size, "", d.shaft)  # fmt: skip
    if mep.electrical is not None:
        for r in mep.electrical.risers:
            size = f"{_mm(r.width)}x{_mm(r.depth)}" if r.width and r.depth else "-"
            if r.rating:
                size += f", {r.rating:g} A"
            row(r.id, ml.ELECTRICAL_RISER_KINDS.get(r.kind, r.kind), r.fromStory, r.toStory,
                size, "", r.shaft)  # fmt: skip
    if mep.fire is not None:
        for r in mep.fire.risers:
            row(r.id, ml.FIRE_RISER_SYSTEMS.get(r.system, r.system), r.fromStory, r.toStory,
                f"Ø{_mm(r.diameter)}" if r.diameter else "-", "", r.shaft)  # fmt: skip
    columns = [
        _column("mark", "Mark", 6),
        _column("service", "Service", 22),
        _column("from", "From", 10),
        _column("to", "To", 10),
        _column("size", "Size\n(mm)", 14),
        _column("material", "Material", 8),
        _column("shaft", "Shaft", 6),
    ]
    return Table("Riser schedule", columns, rows)


def equipment_table(drawing: MepDrawing, building: Building) -> Table:
    """The equipment of every service: mark, item, story, size, rating, operating weight."""
    from saengine.library import mep as ml

    mep = drawing.model
    rows: list[list[str]] = []
    linked: set[str] = set()

    def size_of(thing: Any) -> str:
        dims = [getattr(thing, k, None) for k in ("length", "width", "height")]
        return " x ".join(_mm(d) for d in dims if d) or "-"

    def weight(value: Any) -> str:
        return f"{float(value):.1f}" if value else "-"

    if mep.hvac is not None:
        for p in mep.hvac.plant:
            linked.add(p.equipment or "")
            unit = "m³/s" if p.kind == "exhaustFan" else "kW"
            rating = f"{p.capacity:g} {unit}" if p.capacity else "-"
            if p.power:
                rating += f", {p.power:g} kW input"
            rows.append([p.id, ml.HVAC_PLANT_KINDS.get(p.kind, p.kind),
                         _level_name(building, p.story), size_of(p), rating,
                         weight(p.operatingWeight)])  # fmt: skip
    if mep.electrical is not None:
        for e in mep.electrical.equipment:
            linked.add(e.equipment or "")
            unit = {"lvPanel": "A", "distributionBoard": "A", "solarPv": "kW"}.get(e.kind, "kVA")
            rows.append([e.id, ml.ELECTRICAL_EQUIPMENT_KINDS.get(e.kind, e.kind),
                         _level_name(building, e.story), size_of(e),
                         f"{e.rating:g} {unit}" if e.rating else "-",
                         weight(e.operatingWeight)])  # fmt: skip
    if mep.fire is not None:
        for p in mep.fire.pumps:
            linked.add(p.equipment or "")
            rating = ", ".join(
                part
                for part in (
                    f"{p.flow:g} l/min" if p.flow else "",
                    f"{p.head:g} m" if p.head else "",
                    f"{p.power:g} kW" if p.power else "",
                )
                if part
            )
            rows.append([p.id, ml.FIRE_PUMP_DUTIES.get(p.duty, p.duty),
                         _level_name(building, p.story), size_of(p), rating or "-",
                         weight(p.operatingWeight)])  # fmt: skip
    for e in mep.equipment:
        if e.id in linked:
            continue
        rows.append([e.id, e.name or ml.EQUIPMENT_KINDS.get(e.kind, e.kind),
                     _level_name(building, e.story), size_of(e), "-",
                     weight(e.operatingWeight)])  # fmt: skip
    columns = [
        _column("mark", "Mark", 6),
        _column("item", "Item", 24),
        _column("level", "Level", 10),
        _column("size", "Size L x W x H\n(mm)", 18),
        _column("rating", "Rating", 18),
        _column("weight", "Operating\nweight (kN)", 9, "right"),
    ]
    return Table("Equipment schedule", columns, rows)


def tank_volume(tank: Any) -> float | None:
    """The water a tank holds [m³]: inside length x width (or the area of its diameter) x water
    depth; None without its sizes."""
    if not tank.waterDepth:
        return None
    if tank.length and tank.width:
        area = float(tank.length) * float(tank.width)
    elif tank.diameter:
        area = math.pi * float(tank.diameter) ** 2 / 4
    else:
        return None
    return area * float(tank.waterDepth) / 1e9


def tank_table(drawing: MepDrawing, building: Building) -> Table:
    """The plumbing and fire tanks: mark, kind, story, inside size, water depth, freeboard,
    compartments, construction and the water they hold."""
    from saengine.library import mep as ml

    mep = drawing.model
    tanks = [*(mep.plumbing.tanks if mep.plumbing else []), *(mep.fire.tanks if mep.fire else [])]
    rows = []
    for t in tanks:
        if t.length and t.width:
            size = f"{_mm(t.length)} x {_mm(t.width)}"
        elif t.diameter:
            size = f"Ø{_mm(t.diameter)}"
        else:
            size = "-"
        volume = tank_volume(t)
        rows.append([
            t.id, ml.TANK_KINDS.get(t.kind, t.kind), _level_name(building, _tank_level(building, t)),
            size, _mm(t.waterDepth) if t.waterDepth else "-",
            _mm(t.freeboard) if t.freeboard else "-", str(t.compartments or 1),
            {"rc": "RC", "masonry": "Masonry", "prefab": "Prefabricated"}.get(t.construction, ""),
            f"{volume:.2f}" if volume is not None else "-",
        ])  # fmt: skip
    columns = [
        _column("mark", "Mark", 6),
        _column("kind", "Tank", 22),
        _column("level", "Level", 10),
        _column("size", "Inside\n(mm)", 14),
        _column("depth", "Water\ndepth (mm)", 8, "right"),
        _column("freeboard", "Free-\nboard (mm)", 8, "right"),
        _column("compartments", "Compart-\nments", 7, "right"),
        _column("construction", "Construc-\ntion", 9),
        _column("volume", "Water\n(m³)", 7, "right"),
    ]
    return Table("Tank schedule", columns, rows)


def sleeve_table(drawing: MepDrawing, building: Building) -> Table:
    """The sleeves and openings through the structure: mark, host, kind, size, service, where."""
    rows = []
    for o in drawing.model.openings:
        if o.shape == "circle":
            size = f"Ø{_mm(o.diameter)}" if o.diameter else "-"
        else:
            size = f"{_mm(o.width or 0)} x {_mm(o.height or 0)}"
        p = o.position
        where = []
        if p.distance is not None:
            where.append(f"{_mm(p.distance)} from start")
        if p.elevation is not None:
            where.append(f"{_mm(p.elevation)} up")
        if p.x is not None:
            where.append(f"x {_mm(p.x)}")
        if p.y is not None:
            where.append(f"y {_mm(p.y)}")
        placed = opening_place(o, building)
        rows.append([o.id, o.host, o.kind, size, o.service or "-", ", ".join(where) or "-",
                     _level_name(building, placed[0]) if placed else "-"])  # fmt: skip
    columns = [
        _column("mark", "Mark", 6),
        _column("host", "Host", 8),
        _column("kind", "Kind", 8),
        _column("size", "Size\n(mm)", 12),
        _column("service", "Service", 18),
        _column("where", "Position (mm)", 22),
        _column("level", "Plan", 10),
    ]
    return Table("Sleeve and opening schedule", columns, rows)


def schedule_tables(drawing: MepDrawing, building: Building) -> list[Table]:
    """The MEP schedules that have rows."""
    tables = [
        riser_table(drawing, building),
        equipment_table(drawing, building),
        tank_table(drawing, building),
        sleeve_table(drawing, building),
    ]
    return [t for t in tables if t.rows]


# ─────────────────────────────────── the project's MEP ───────────────────────────────────


def mep_drawing(text: str, bim: Any, arch: Any = None) -> tuple[MepDrawing | None, list[str]]:
    """The 07 MEP model of ``text`` for the sheets with its wet rooms and the sizing's
    diameters; ``(None, problems)`` when it cannot be read or has nothing to draw."""
    from saengine.library import mep as ml

    problems: list[str] = []
    try:
        model = ml.parse(text)
    except ValueError as error:
        return None, [f"07 MEP could not be read, so its sheets are not drawn: {error}"]
    rooms = None
    if arch is not None:
        try:
            from saengine.mep.rooms import room_inputs

            rooms = room_inputs(arch, bim, model.plumbing)
        except Exception as error:  # noqa: BLE001 - the plans still draw without the wet rooms
            problems.append(f"07 MEP sheets: the wet rooms could not be read ({error}).")
    sized: dict[str, float] = {}
    if model.plumbing is not None and any(not r.diameter for r in model.plumbing.risers):
        try:
            from saengine.plumbing.report import plumbing_results

            report = plumbing_results(model, bim, None, None, rooms=rooms)
            for entry in [*(report.get("risers") or []), *(report.get("stacks") or [])]:
                if isinstance(entry, dict) and entry.get("id") and entry.get("diameter"):
                    sized[str(entry["id"])] = float(entry["diameter"])
        except Exception as error:  # noqa: BLE001 - drawn without the sized diameters
            problems.append(f"07 MEP sheets: the plumbing sizing failed ({error}); risers "
                            "without a diameter are drawn without one.")  # fmt: skip
    return MepDrawing(model, rooms, sized), problems

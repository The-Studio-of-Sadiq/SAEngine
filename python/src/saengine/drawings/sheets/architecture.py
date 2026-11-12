"""Architectural sheets (``A-101`` on): the architectural plan of each story with walls, doors,
windows and rooms; the four elevations; one or two building sections; the door and window
schedule and the room finish schedule. Drawn from the architecture of ``05 Floor
Plan/architecture.json`` (:mod:`saengine.library.architecture`, whose geometry this module
uses: centre lines, openings, rooms) over the building of the structural sheets (grids, columns,
beams, slabs, stairs).

Conventions:

- Plans are cut :data:`CUT` above the floor. Walls are drawn by their layers: masonry hatched
  ANSI31, concrete AR-CONC, plaster and finishes plain, with a heavy outline; walls joined in
  plan merge. Doors have their leaf open at right angles and their swing (as the Architecture
  editor draws them); windows their frame and glass, dashed when their sill is above the cut.
  Columns cut are hatched as on the framing plans. Rooms carry their number and name, net floor
  area and finish codes (floor / walls / ceiling). Grid dimensions as on the framing plans, and
  chains of the openings along the outer walls on the top and right.
- Elevations and sections draw what is seen as parallel projections, nearest first: an item is
  drawn only where nothing nearer hides it (walls, columns, beams and slabs as boxes; a window
  hides what is behind it). Sections draw what they cut heavy, walls by their layers and
  concrete solid, and what lies beyond the cut as in an elevation.
- The levels are the stories' (top of slab).

Kept simple: no view templates, no families; a wall is one type over its height.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from shapely import affinity
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from saengine.drawings.sheets.layout import TEXT, TEXT_LARGE, View, ViewSpec, text_width
from saengine.drawings.sheets.model import Building, Level, Point, Table
from saengine.drawings.sheets.plans import (
    BUBBLE,
    DIM_1,
    DIM_2,
    EXTEND,
    _bounds,
    _columns,
    _inside_label,
    _level_points,
    _stair,
    _stair_mark,
    _walls,
    elevation_grids,
    grids,
    level_lines,
)
from saengine.drawings.sheets.steel import natural_key
from saengine.library import architecture as al

PREFIX = "A-"
"""The architectural sheets' numbers: A-101, A-102, ..."""
CUT = 1200.0
"""Height of a plan's cut plane above its floor [mm]."""
EPS = 1.0  # mm
TINY = 2500.0  # mm², visible pieces smaller than this are slivers of round-off

PLAN_NOTES = [
    "Plans are cut 1.2 m above the floor; dashed windows are above the cut.",
    "Hatched: masonry and concrete layers of the walls; plaster and finishes unhatched.",
    (
        "Rooms: number and name, net floor area, finishes floor / walls / ceiling (codes of "
        "the room finish schedule)."
    ),
    "D and W marks are the door and window types (door and window schedule).",
    "Dimensions in millimetres; levels are top of slab.",
]
ELEVATION_NOTES = [
    "Levels are top of slab, in metres.",
    "Walls, columns, beams and slabs are drawn as seen; finishes are not shown.",
]
SECTION_NOTES = [
    "Heavy: cut. Masonry hatched, concrete solid.",
    "Beyond the cut: as seen.",
    "Levels are top of slab, in metres.",
]


# ─────────────────────────────────── geometry ───────────────────────────────────


def pattern_of(material: str) -> str | None:
    """The hatch of a wall layer of ``material`` in plans and sections (None: unhatched)."""
    name = material.lower()
    if any(k in name for k in ("brick", "block", "masonry", "stone")):
        return "ANSI31"
    if "concrete" in name or "rcc" in name:
        return "AR-CONC"
    return None


@dataclass
class Opening:
    """A door or window in its wall, where the drawings need it."""

    kind: str  # door | window
    mark: str  # its type's id
    style: str
    width: float
    height: float
    sill: float  # above the wall's bottom
    frame: float
    centre: Point
    direction: Point  # along the wall
    thickness: float  # of the wall
    flip: bool = False
    segment: int = 0  # the piece of the wall's centre line it is in

    def at(self, u: float, v: float) -> Point:
        """The point ``u`` along the wall from the centre and ``v`` to its left."""
        (cx, cy), (dx, dy) = self.centre, self.direction
        return (cx + dx * u - dy * v, cy + dy * u + dx * v)

    def quad(self, grow: float = 1.0) -> Polygon:
        """The opening through the wall in plan (``grow`` mm past the faces)."""
        h, t = self.width / 2, self.thickness / 2 + grow
        return Polygon([self.at(-h, -t), self.at(h, -t), self.at(h, t), self.at(-h, t)])


@dataclass
class WallGeometry:
    id: str
    base: str  # the story it stands on
    bottom: float
    top: float
    thickness: float
    centre: list[Point]
    footprint: BaseGeometry
    bands: list[tuple[str | None, BaseGeometry]]  # (hatch, the layer's band in plan)
    pieces: list[Polygon]  # the footprint piece by piece of the centre line
    openings: list[Opening] = field(default_factory=list)


def _quads(centre: list[Point], a: float, b: float) -> list[Polygon]:
    """The strip between the offsets ``a`` and ``b`` (to the left) of the polyline, mitred,
    one piece per segment."""
    pa = al.offset_path([list(p) for p in centre], a)
    pb = al.offset_path([list(p) for p in centre], b)
    return [Polygon([pa[i], pa[i + 1], pb[i + 1], pb[i]]).buffer(0) for i in range(len(pa) - 1)]


def _band(centre: list[Point], a: float, b: float) -> BaseGeometry:
    return unary_union(_quads(centre, a, b))


def _segment_at(points: list[Point], offset: float) -> int:
    """The index of the segment of the polyline ``offset`` along it."""
    run = 0.0
    for i, (a, b) in enumerate(itertools.pairwise(points)):
        run += math.dist(a, b)
        if offset <= run + 1e-6:
            return i
    return max(len(points) - 2, 0)


def elevations_of(building: Building) -> dict[str, float]:
    return {lv.id: lv.elevation for lv in building.levels}


def wall_geometry(arch: Any, building: Building) -> list[WallGeometry]:
    """Every wall of ``arch`` whose stories ``building`` has, with its openings."""
    elevations = elevations_of(building)
    types = {t.id: t for t in arch.wallTypes}
    doors = {t.id: t for t in arch.doorTypes}
    windows = {t.id: t for t in arch.windowTypes}
    out: list[WallGeometry] = []
    by_id: dict[str, WallGeometry] = {}
    for wall in arch.walls:
        levels = al.wall_levels(wall, elevations)
        if levels is None:
            continue
        wall_type = types[wall.type]
        centre = al.centre_line(wall, wall_type)
        thickness = wall_type.thickness
        bands = []
        left = thickness / 2
        for layer in wall_type.layers:
            bands.append((pattern_of(layer.material), _band(centre, left, left - layer.thickness)))
            left -= layer.thickness
        pieces = _quads(centre, thickness / 2, -thickness / 2)
        geometry = WallGeometry(
            wall.id,
            wall.base,
            levels[0],
            levels[1],
            thickness,
            centre,
            unary_union(pieces),
            bands,
            pieces,
        )
        out.append(geometry)
        by_id[wall.id] = geometry
    for kind, items in (("door", arch.doors), ("window", arch.windows)):
        for item in items:
            host = by_id.get(item.wall)
            if host is None:
                continue
            width, height, sill = al.opening_size(arch, item)
            t = (doors if kind == "door" else windows)[item.type]
            point, direction = al.point_along(host.centre, item.offset)
            host.openings.append(
                Opening(
                    kind,
                    item.type,
                    t.style,
                    width,
                    height,
                    sill,
                    t.frame,
                    point,
                    direction,
                    host.thickness,
                    bool(getattr(item, "flip", False)),
                    _segment_at(host.centre, item.offset),
                )
            )
    return out


def on_story(walls: Iterable[WallGeometry], level: Level) -> list[WallGeometry]:
    """The walls a plan of ``level`` cuts: those standing on it or rising through it."""
    z = level.elevation + CUT
    return [w for w in walls if w.base == level.id or w.bottom - EPS <= z < w.top - EPS]


def plan_levels(arch: Any, building: Building) -> list[Level]:
    """The stories with an architectural plan: walls or rooms on them."""
    walls = wall_geometry(arch, building)
    rooms = {r.story for r in arch.rooms}
    return [
        lv
        for lv in sorted(building.levels, key=lambda lv: lv.elevation)
        if on_story(walls, lv) or lv.id in rooms
    ]


def polygons(geometry: BaseGeometry) -> list[Polygon]:
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [g for part in geometry.geoms for g in polygons(part)]
    return []


def _ring(coords: Iterable[Sequence[float]]) -> list[Point]:
    pts = [(float(x), float(y)) for x, y, *_ in coords]
    return pts[:-1] if len(pts) > 1 and pts[0] == pts[-1] else pts


def draw_outline(view: View, geometry: BaseGeometry, layer: str, **kw: Any) -> None:
    """The rings of the polygons of ``geometry``, or its lines."""
    if geometry.is_empty:
        return
    if geometry.geom_type in ("LineString", "LinearRing"):
        view.polyline(_ring(geometry.coords) if geometry.is_closed else
                      [(x, y) for x, y, *_ in geometry.coords], layer,
                      close=geometry.is_closed, **kw)  # fmt: skip
        return
    if geometry.geom_type == "Polygon":
        for ring in (geometry.exterior, *geometry.interiors):
            view.polyline(_ring(ring.coords), layer, close=True, **kw)
        return
    for part in getattr(geometry, "geoms", ()):
        draw_outline(view, part, layer, **kw)


def draw_hatch(view: View, geometry: BaseGeometry, pattern: str, layer: str) -> None:
    for poly in polygons(geometry):
        if poly.area < 1.0:
            continue
        view.hatch(
            _ring(poly.exterior.coords),
            pattern,
            layer,
            holes=[_ring(r.coords) for r in poly.interiors],
        )


def _clean(geometry: BaseGeometry) -> BaseGeometry:
    """``geometry`` without the slivers round-off leaves."""
    parts = [p for p in polygons(geometry) if p.area > TINY]
    return unary_union(parts) if parts else Polygon()


# ─────────────────────────────────── plans ───────────────────────────────────


@dataclass
class SectionLine:
    """A building section: ``name`` (X, Y), cut where ``look · p == depth``, seen looking along
    ``look`` (unit, plan)."""

    name: str
    look: Point
    depth: float

    @property
    def title(self) -> str:
        return f"Section {self.name}-{self.name}"


def _crossings(walls: list[WallGeometry], line: LineString) -> float:
    """How much a cut along ``line`` shows: openings it passes through count most."""
    score = 0.0
    for w in walls:
        if w.footprint.intersects(line):
            score += 0.1
        score += sum(1.0 for o in w.openings if o.quad().intersects(line))
    return score


def section_lines(arch: Any, building: Building) -> list[SectionLine]:
    """Section X-X along x (a cut at constant y, looking +y) and Y-Y along y (a cut at
    constant x, looking +x), each through the middle of the grid bay whose cut shows the most
    openings (ties: the bay nearest the middle). A cut that meets no wall is left out."""
    walls = wall_geometry(arch, building)
    if not walls:
        return []
    x0, y0, x1, y1 = unary_union([w.footprint for w in walls]).bounds
    out = []
    for name, look, lo, hi, lines, other in (
        ("X", (0.0, 1.0), y0, y1, building.grids_y, (x0, x1)),
        ("Y", (1.0, 0.0), x0, x1, building.grids_x, (y0, y1)),
    ):
        positions = sorted(g.position for g in lines)
        candidates = [
            (a + b) / 2 for a, b in itertools.pairwise(positions) if lo < (a + b) / 2 < hi
        ]
        candidates = candidates or [(lo + hi) / 2]
        mid = (lo + hi) / 2

        def cut(c: float, look=look, other=other) -> LineString:
            a, b = other[0] - 1000, other[1] + 1000
            return LineString([(a, c), (b, c)] if look[1] else [(c, a), (c, b)])

        best = max(candidates, key=lambda c: (_crossings(walls, cut(c)), -abs(c - mid)))
        if _crossings(walls, cut(best)) > 0:
            out.append(SectionLine(name, look, best))
    return out


def _plan_bbox(building: Building, walls: list[WallGeometry], level: Level):
    pts = _level_points(building, level)
    for w in walls:
        bx0, by0, bx1, by1 = w.footprint.bounds
        pts += [(bx0, by0), (bx1, by1)]
    return _bounds(pts)


def _walls_in_plan(view: View, walls: list[WallGeometry], structure: BaseGeometry) -> None:
    """The cut walls by their layers, the openings cut out (not those above the cut), stopping
    at the ``structure`` cut (columns, concrete walls: drawn as on the framing plans)."""
    holes = unary_union(
        [o.quad() for w in walls for o in w.openings if o.sill < CUT] or [Polygon()]
    ).union(structure)
    done = Polygon()
    for pattern, layer in (("ANSI31", "A-WALL-PATT"), ("AR-CONC", "A-WALL-PATT")):
        region = unary_union([b for w in walls for p, b in w.bands if p == pattern] or [Polygon()])
        region = region.difference(holes).difference(done)
        draw_hatch(view, region, pattern, layer)
        draw_outline(view, region, "A-WALL-PATT")
        done = done.union(region)
    outline = unary_union([w.footprint for w in walls]).difference(holes)
    draw_outline(view, outline, "A-WALL")


def _swing(view: View, o: Opening, hinge: float, length: float, sense: int, side: int) -> None:
    """A leaf open at right angles to the wall at ``hinge`` and its swing back to the jamb (as
    the Architecture editor draws it)."""
    base = side * o.thickness / 2
    a, b = o.at(hinge, base), o.at(hinge, base + side * length)
    view.line(a, b, "A-DOOR")
    to_leaf = (b[0] - a[0], b[1] - a[1])
    jamb = o.at(hinge + sense * length, base)
    to_jamb = (jamb[0] - a[0], jamb[1] - a[1])
    start, end = (to_jamb, to_leaf)
    if to_leaf[0] * to_jamb[1] - to_leaf[1] * to_jamb[0] > 0:  # leaf to jamb is anticlockwise
        start, end = to_leaf, to_jamb
    view.arc(
        a,
        length,
        math.degrees(math.atan2(start[1], start[0])),
        math.degrees(math.atan2(end[1], end[0])),
        "A-DOOR",
    )
    view.reserve([a, b, jamb, (b[0] + jamb[0] - a[0], b[1] + jamb[1] - a[1])])


def _opening_in_plan(view: View, o: Opening) -> None:
    h, t = o.width / 2, o.thickness / 2
    if o.kind == "window":
        above = {"linetype": "HIDDEN"} if o.sill >= CUT else {}
        for v in (-t, 0.0, t):
            view.line(o.at(-h, v), o.at(h, v), "A-GLAZ", **above)
        if not above:
            for u in (-h, h):
                view.line(o.at(u, -t), o.at(u, t), "A-GLAZ")
        view.reserve([o.at(-h, -t), o.at(h, t)])
        return
    for u in (-h, h):
        view.line(o.at(u, -t), o.at(u, t), "A-DOOR")
    side = -1 if o.flip else 1
    if o.style == "double":
        _swing(view, o, -h, h, 1, side)
        _swing(view, o, h, h, -1, side)
    elif o.style == "sliding":
        view.line(o.at(-h, t / 3), o.at(h * 0.1, t / 3), "A-DOOR")
        view.line(o.at(-h * 0.1, -t / 3), o.at(h, -t / 3), "A-DOOR")
        view.reserve([o.at(-h, -t), o.at(h, t)])
    else:
        _swing(view, o, -h, o.width, 1, side)


def _opening_mark(view: View, o: Opening) -> None:
    """The type mark beside the opening, away from a door's swing."""
    away = 1 if o.flip or o.kind == "window" else -1
    candidates = []
    for side in (away, -away):
        for extra in (2.5, 5.0):
            v = side * (o.thickness / 2 / view.scale + extra)
            nx, ny = -o.direction[1] * v, o.direction[0] * v
            candidates.append((nx, ny, "MC"))
    view.label(o.mark, o.centre, candidates, TEXT, rings=True)


def unenclosed_rooms(arch: Any, building: Building) -> list[str]:
    """The rooms the plans leave out: no walls around their points (problems)."""
    elevations = elevations_of(building)
    return [
        f"Room {room.number or room.id}: no walls around its point, not drawn"
        for room in arch.rooms
        if room.story in elevations and al.room_boundary(arch, room, elevations) is None
    ]


def _room_tags(view: View, arch: Any, building: Building, level: Level) -> None:
    """Room tags inside the rooms (number and name, net area, finish codes)."""
    elevations = elevations_of(building)
    for room in (r for r in arch.rooms if r.story == level.id):
        found = al.room_boundary(arch, room, elevations)
        if found is None:
            continue
        net = found[1]
        codes = "/".join(
            getattr(room, f) or "-" for f in ("floorFinish", "wallFinish", "ceilingFinish")
        )
        name = f"{room.number} {room.name}".strip().upper()
        area = f"{net.area / 1e6:.2f} m²"
        boundary = _ring(max(polygons(net), key=lambda p: p.area).exterior.coords)
        # a narrow room: its finishes one under another, else without them (in the schedule)
        stacked = codes.replace("/", "\n")
        shorter = [f"{name}\n{area}\n{stacked}", f"{name}\n{area}"]
        _inside_label(
            view, f"{name}\n{area}\n{codes}", boundary, layer="A-AREA-IDEN", shorter=shorter
        )


def _opening_dims(view: View, walls: list[WallGeometry], bbox) -> None:
    """Chains along the outer walls on the top and the right of the plan: wall ends and the
    openings' jambs, on the outer face."""
    _, _, x1, y1 = bbox
    for horizontal, edge, offset in ((True, y1, DIM_1), (False, x1, -DIM_1)):
        k = 1 if horizontal else 0  # the coordinate across the wall
        stops: list[float] = []
        for w in walls:
            for a, b in zip(w.centre, w.centre[1:]):
                if abs(a[k] - b[k]) > EPS:
                    continue  # not parallel to this edge
                face = a[k] + w.thickness / 2
                if abs(face - edge) > w.thickness + EPS:
                    continue
                stops += [a[1 - k], b[1 - k]]
                for o in w.openings:
                    if (
                        abs(o.centre[k] - a[k]) < EPS
                        and min(a[1 - k], b[1 - k]) - EPS
                        <= (o.centre[1 - k])
                        <= max(a[1 - k], b[1 - k]) + EPS
                    ):
                        stops += [o.centre[1 - k] - o.width / 2, o.centre[1 - k] + o.width / 2]
        if not stops:
            continue
        stops = sorted(stops)
        unique = [stops[0]]
        for s in stops[1:]:
            if s - unique[-1] > EPS:
                unique.append(s)
        if len(unique) < 2:
            continue
        if horizontal:
            view.chain([(s, edge) for s in unique], offset)
        else:
            view.chain([(edge, s) for s in unique], offset, angle=90)


def _section_marks(view: View, cuts: Sequence[SectionLine], bbox) -> None:
    """The section lines across the plan (phantom) with their marks beyond the grid bubbles:
    the letter in a circle and an arrow the way the section looks."""
    x0, y0, x1, y1 = bbox
    e, r = view.real(EXTEND), view.real(BUBBLE)
    for cut in cuts:
        if cut.look[1]:  # constant y
            if not y0 < cut.depth < y1:
                continue
            ends = [(x0 - e - r, cut.depth), (x1 + e + r, cut.depth)]
        else:
            if not x0 < cut.depth < x1:
                continue
            ends = [(cut.depth, y0 - e - r), (cut.depth, y1 + e + r)]
        view.line(ends[0], ends[1], "A-ANNO-SYMB", linetype="PHANTOM")
        lx, ly = cut.look
        for c in ends:
            view.circle(c, r, "A-ANNO-SYMB")
            # the arrow outside the circle, pointing the way the section looks
            foot = (c[0] + lx * r, c[1] + ly * r)
            tip = (foot[0] + lx * view.real(3.0), foot[1] + ly * view.real(3.0))
            side = (-ly * view.real(1.6), lx * view.real(1.6))
            arrow = [
                tip,
                (foot[0] + side[0], foot[1] + side[1]),
                (foot[0] - side[0], foot[1] - side[1]),
            ]
            view.polyline(arrow, "A-ANNO-SYMB", close=True)
            view.hatch(arrow, "SOLID", "A-ANNO-SYMB")
            view.reserve([*arrow, (c[0] - r, c[1] - r), (c[0] + r, c[1] + r)])
            view.text(cut.name, c, TEXT_LARGE, "MC", "A-ANNO-SYMB")


def floor_plan(
    building: Building,
    arch: Any,
    level: Level,
    scale: float = 100,
    cuts: Sequence[SectionLine] = (),
) -> ViewSpec:
    """The architectural plan of ``level``."""
    walls = on_story(wall_geometry(arch, building), level)
    bbox = _plan_bbox(building, walls, level)
    pad = (DIM_2 + 6, DIM_2 + 6, DIM_1 + 10, DIM_1 + 10)

    def draw(view: View) -> None:
        z = level.elevation
        grids(view, building, bbox)
        _columns(view, building, z + CUT)
        _walls(view, building, z + CUT)
        cut = z + CUT
        structure = [Polygon(c.outline()) for c in building.columns if c.bottom < cut < c.top] + [
            LineString([w.start, w.end]).buffer(w.thickness / 2, cap_style="flat")
            for w in building.walls
            if w.bottom < cut < w.top and math.dist(w.start, w.end) > EPS
        ]
        _walls_in_plan(view, walls, unary_union(structure or [Polygon()]))
        for w in walls:
            for o in w.openings:
                _opening_in_plan(view, o)
        stairs = [st for st in building.stairs if abs(st.base - z) < EPS or abs(st.top - z) < EPS]
        for st in stairs:
            _stair(view, st)
        _opening_dims(view, walls, bbox)
        _section_marks(view, cuts, bbox)
        for w in walls:
            for o in w.openings:
                _opening_mark(view, o)
        for st in stairs:
            _stair_mark(view, st, up=abs(st.base - z) < EPS)
        _room_tags(view, arch, building, level)

    return ViewSpec(
        title=f"Architectural plan - {level.name}",
        scale=scale,
        bbox=bbox,
        draw=draw,
        pad=pad,
        subtitle=f"SCALE 1:{scale:g}   LEVEL +{level.elevation / 1000:.3f}",
        key=f"arch-plan:{level.id}",
    )


# ─────────────────────────────────── elevations and sections ───────────────────────────────────


@dataclass
class _Solid:
    footprint: BaseGeometry  # in plan
    bottom: float
    top: float
    wall: WallGeometry | None = None
    segment: int = 0  # of the wall's centre line


def _solids(building: Building, walls: list[WallGeometry]) -> list[_Solid]:
    """What elevations and sections draw: the architecture's walls and the structure."""
    out = [_Solid(piece, w.bottom, w.top, w, i) for w in walls for i, piece in enumerate(w.pieces)]
    for c in building.columns:
        out.append(_Solid(Polygon(c.outline()), c.bottom, c.top))
    for b in building.beams:
        line = LineString([b.start, b.end])
        if line.length > EPS:
            out.append(
                _Solid(line.buffer(b.width / 2, cap_style="flat"), b.elevation - b.depth,
                       b.elevation)
            )  # fmt: skip
    for s in building.slabs:
        if len(s.boundary) >= 3:
            poly = Polygon(s.boundary).buffer(0)
            for hole in s.openings:
                poly = poly.difference(Polygon(hole))
            out.append(_Solid(poly, s.elevation - s.thickness, s.elevation))
    for w in building.walls:
        line = LineString([w.start, w.end])
        if line.length > EPS:
            out.append(_Solid(line.buffer(w.thickness / 2, cap_style="flat"), w.bottom, w.top))
    return out


def _lines_within(view: View, lines: Iterable[LineString], visible: BaseGeometry, layer: str):
    for line in lines:
        draw_outline(view, line.intersection(visible), layer)


def _opening_seen(view: View, o: Opening, u0: float, u1: float, bottom: float, visible) -> None:
    """A door or window seen from the front, between ``u0`` and ``u1``, where visible."""
    z0, z1 = bottom + o.sill, bottom + o.sill + o.height
    rect = box(u0, z0, u1, z1)
    draw_outline(view, rect.intersection(visible), "A-DOOR" if o.kind == "door" else "A-GLAZ")
    f = min(o.frame, (u1 - u0) / 4, (z1 - z0) / 4)
    um = (u0 + u1) / 2
    lines = []
    if o.kind == "window":
        layer = "A-GLAZ"
        lines.append(box(u0 + f, z0 + f, u1 - f, z1 - f).exterior)
        if o.style == "sliding":
            lines.append(LineString([(um, z0 + f), (um, z1 - f)]))
        elif o.style == "casement":  # the opening sign: to the hinge side
            lines.append(LineString([(u1 - f, z0 + f), (u0 + f, (z0 + z1) / 2), (u1 - f, z1 - f)]))
    else:
        layer = "A-DOOR"
        lines.append(LineString([(u0 + f, z0), (u0 + f, z1 - f), (u1 - f, z1 - f), (u1 - f, z0)]))
        if o.style in ("double", "sliding"):
            lines.append(LineString([(um, z0), (um, z1 - f)]))
    _lines_within(view, lines, visible, layer)


def _projection(
    view: View,
    building: Building,
    walls: list[WallGeometry],
    look: Point,
    cut: float | None = None,
) -> None:
    """Draws what is seen looking along ``look``: beyond the plane ``look · p == cut`` and what
    it cuts when ``cut`` is given (a section), else everything (an elevation)."""
    right = (look[1], -look[0])
    matrix = [right[0], right[1], look[0], look[1], 0.0, 0.0]  # plan -> (u, depth)

    def ud(g: BaseGeometry) -> BaseGeometry:
        return affinity.affine_transform(g, matrix)

    solids = _solids(building, walls)
    covered: BaseGeometry = Polygon()
    if cut is not None:
        far = 1e7
        beyond_box = box(-far, cut, far, far)
        plane = LineString([(-far, cut), (far, cut)])

        def intervals(g: BaseGeometry) -> list[tuple[float, float]]:
            hit = ud(g).intersection(plane)
            return [
                (min(p.coords[0][0], p.coords[-1][0]), max(p.coords[0][0], p.coords[-1][0]))
                for p in _segments(hit)
            ]

        cuts = []
        for s in solids:
            spans = intervals(s.footprint)
            if not spans:
                continue
            if s.wall is None:
                region = unary_union([box(a, s.bottom, b, s.top) for a, b in spans])
                draw_hatch(view, region, "SOLID", "S-HATCH")
                cuts.append(region)
                continue
            gaps = []
            for o in (o for o in s.wall.openings if o.segment == s.segment):
                for a, b in intervals(o.quad()):
                    z0 = s.bottom + o.sill
                    gaps.append(box(a, z0, b, z0 + o.height))
            holes = unary_union(gaps or [Polygon()])
            region = unary_union([box(a, s.bottom, b, s.top) for a, b in spans]).difference(holes)
            for pattern, band in s.wall.bands:
                spans = intervals(band.intersection(s.footprint))
                part = unary_union(
                    [box(a, s.bottom, b, s.top) for a, b in spans] or [Polygon()]
                ).difference(holes)
                if pattern is not None:
                    draw_hatch(view, part, pattern, "A-WALL-PATT")
                draw_outline(view, part, "A-WALL-PATT")
            cuts.append(region)
        for region in cuts:
            draw_outline(view, region, "A-SECT")
        covered = unary_union(cuts or [Polygon()])
    items = []
    for s in solids:
        fp = ud(s.footprint)
        if cut is not None:
            fp = fp.intersection(beyond_box)
        if fp.is_empty or fp.area < 1.0:
            continue
        items.append((fp.bounds[1], fp, s))
    items.sort(key=lambda item: item[0])
    for _, fp, s in items:
        u0, _, u1, _ = fp.bounds
        face = box(u0, s.bottom, u1, s.top)
        visible = _clean(face.difference(covered))
        if not visible.is_empty:
            draw_outline(view, visible, "A-ELEV")
            mine = [o for o in s.wall.openings if o.segment == s.segment] if s.wall else []
            for o in mine:
                along = abs(o.direction[0] * look[0] + o.direction[1] * look[1])
                if along > 0.9:
                    continue  # the wall is seen end on
                q = ud(o.quad())
                if cut is not None and q.bounds[3] < cut:
                    continue
                _opening_seen(view, o, q.bounds[0], q.bounds[2], s.bottom, visible)
        covered = covered.union(face)


def _segments(geometry: BaseGeometry) -> list[LineString]:
    if geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry]
    return [g for part in getattr(geometry, "geoms", ()) for g in _segments(part)]


def _compass(building: Building, normal: Point) -> str:
    """North, East, South or West: where the plan direction ``normal`` points."""
    n = math.radians(building.north)
    north = (-math.sin(n), math.cos(n))
    cross = north[0] * normal[1] - north[1] * normal[0]
    dot = north[0] * normal[0] + north[1] * normal[1]
    bearing = (-math.degrees(math.atan2(cross, dot))) % 360  # clockwise from north
    return ("North", "East", "South", "West")[round(bearing / 90) % 4]


SIDES: tuple[tuple[str, Point], ...] = (
    ("front", (0.0, 1.0)),  # seen from -y, looking +y
    ("right", (-1.0, 0.0)),  # from +x
    ("rear", (0.0, -1.0)),  # from +y
    ("left", (1.0, 0.0)),  # from -x
)
"""The four elevations: the side and the direction they are seen looking."""


def _extent(building: Building, walls: list[WallGeometry], look: Point):
    """The u range and z range of what an elevation or section along ``look`` shows."""
    right = (look[1], -look[0])
    us = []
    for w in walls:
        bx0, by0, bx1, by1 = w.footprint.bounds
        us += [x * right[0] + y * right[1] for x in (bx0, bx1) for y in (by0, by1)]
    zs = [lv.elevation for lv in building.levels]
    zs += [w.bottom for w in walls] + [w.top for w in walls]
    return min(us), max(us), min(zs), max(zs)


def _grid_positions(building: Building, look: Point, u0: float, u1: float):
    right = (look[1], -look[0])
    out = []
    if abs(right[0]) > 0.5:
        out += [(g.label, g.position * right[0]) for g in building.grids_x]
    if abs(right[1]) > 0.5:
        out += [(g.label, g.position * right[1]) for g in building.grids_y]
    return [(label, u) for label, u in out if u0 - EPS <= u <= u1 + EPS]


def _side_view(
    building: Building,
    arch: Any,
    look: Point,
    title: str,
    key: str,
    scale: float,
    cut: float | None = None,
) -> ViewSpec:
    walls = wall_geometry(arch, building)
    u0, u1, z0, z1 = _extent(building, walls, look)
    levels = sorted(building.levels, key=lambda lv: lv.elevation)
    margin = 600.0
    bbox = (u0 - margin, z0 - margin, u1 + margin, z1 + margin)
    level_w = max(
        (text_width(f"{lv.name.upper()} {lv.elevation / 1000:+.3f}", TEXT) for lv in levels),
        default=0.0,
    )

    def draw(view: View) -> None:
        _projection(view, building, walls, look, cut)
        view.line((u0 - margin, z0), (u1 + margin, z0), "A-SECT")
        positions = _grid_positions(building, look, u0, u1)
        elevation_grids(view, positions, z0, z1)
        level_lines(view, levels, u0 - margin, u1 + margin)
        heights = sorted({lv.elevation for lv in levels})
        if len(heights) > 1:
            view.chain([(u0 - margin, z) for z in heights], 8, angle=90)
        xs = sorted({u for _, u in positions})
        if len(xs) > 1:
            view.chain([(x, z0) for x in xs], -10)

    return ViewSpec(
        title=title,
        scale=scale,
        bbox=bbox,
        draw=draw,
        pad=(22, 18, level_w + 14, 2 * BUBBLE + EXTEND + 4),
        subtitle=f"SCALE 1:{scale:g}",
        key=key,
    )


def elevation(building: Building, arch: Any, side: str, scale: float = 100) -> ViewSpec:
    """The elevation of ``side`` (front, right, rear, left: :data:`SIDES`), titled by its
    compass direction and the grid line it faces."""
    look = dict(SIDES)[side]
    normal = (-look[0], -look[1])
    if look[1]:
        lines = sorted(building.grids_y, key=lambda g: g.position)
    else:
        lines = sorted(building.grids_x, key=lambda g: g.position)
    face = (lines[0] if (look[0] + look[1]) > 0 else lines[-1]).label if lines else ""
    title = f"{_compass(building, normal)} elevation"
    subtitle = f" (grid {face})" if face else ""
    return _side_view(building, arch, look, title + subtitle, f"arch-elevation:{side}", scale)


def section(building: Building, arch: Any, cut: SectionLine, scale: float = 100) -> ViewSpec:
    return _side_view(
        building, arch, cut.look, cut.title, f"arch-section:{cut.name}", scale, cut.depth
    )


# ─────────────────────────────────── schedules ───────────────────────────────────


def _levels_text(names: list[str]) -> str:
    return ", ".join(dict.fromkeys(names))


def door_window_tables(arch: Any, building: Building) -> list[Table]:
    """The door schedule and the window schedule: each type used, its size and how many."""
    names = {lv.id: lv.name for lv in building.levels}
    walls = {w.id: w for w in arch.walls}
    out = []
    for kind, types, items in (
        ("Door", arch.doorTypes, arch.doors),
        ("Window", arch.windowTypes, arch.windows),
    ):
        rows = []
        for t in sorted(types, key=lambda t: natural_key(t.id)):
            mine = [i for i in items if i.type == t.id]
            if not mine:
                continue
            levels = _levels_text(
                [names.get(walls[i.wall].base, walls[i.wall].base) for i in mine if i.wall in walls]
            )
            row = [t.id, t.name, t.style.capitalize(), f"{t.width:g}", f"{t.height:g}"]
            if kind == "Window":
                sills = sorted({t.sill if i.sill is None else i.sill for i in mine})
                row.append(", ".join(f"{s:g}" for s in sills))
            row += [f"{t.frame:g}", levels, str(len(mine))]
            rows.append(row)
        if not rows:
            continue
        columns = [
            {"key": "mark", "title": "Mark", "width": 5},
            {"key": "name", "title": "Description", "width": 18},
            {"key": "style", "title": "Style", "width": 8},
            {"key": "width", "title": "Width\n(mm)", "align": "right"},
            {"key": "height", "title": "Height\n(mm)", "align": "right"},
        ]
        if kind == "Window":
            columns.append({"key": "sill", "title": "Sill\n(mm)", "align": "right"})
        columns += [
            {"key": "frame", "title": "Frame\n(mm)", "align": "right"},
            {"key": "levels", "title": "Levels", "width": 16},
            {"key": "count", "title": "No.", "align": "right"},
        ]
        out.append(Table(f"{kind} schedule", columns, rows))
    return out


def room_tables(arch: Any, building: Building) -> list[Table]:
    """The room finish schedule (rooms by level and number) and the finishes it refers to."""
    elevations = elevations_of(building)
    levels = {lv.id: lv for lv in building.levels}
    finishes = {t.id: t for t in arch.finishTypes}

    def finish(code: str | None) -> str:
        return f"{code} {finishes[code].name}" if code in finishes else "-"

    rows = []
    rooms = sorted(
        arch.rooms,
        key=lambda r: (
            levels[r.story].elevation if r.story in levels else 0.0,
            natural_key(r.number or r.id),
        ),
    )
    for room in rooms:
        found = al.room_boundary(arch, room, elevations) if room.story in levels else None
        area = f"{found[1].area / 1e6:.2f}" if found is not None else "-"
        level = levels[room.story].name if room.story in levels else room.story
        rows.append(
            [
                room.number or "-",
                room.name,
                level,
                area,
                finish(room.floorFinish),
                finish(room.wallFinish),
                finish(room.ceilingFinish),
                "Yes" if room.wet else "",
            ]
        )
    out = []
    if rows:
        out.append(
            Table(
                "Room finish schedule",
                [
                    {"key": "number", "title": "No.", "width": 5},
                    {"key": "name", "title": "Room", "width": 14},
                    {"key": "level", "title": "Level", "width": 10},
                    {"key": "area", "title": "Area\n(m²)", "align": "right"},
                    {"key": "floor", "title": "Floor", "width": 18},
                    {"key": "walls", "title": "Walls", "width": 18},
                    {"key": "ceiling", "title": "Ceiling", "width": 18},
                    {"key": "wet", "title": "Wet"},
                ],
                rows,
            )
        )
    used = {c for r in arch.rooms for c in (r.floorFinish, r.wallFinish, r.ceilingFinish) if c}
    finish_rows = [
        [t.id, t.name, t.kind.capitalize(), f"{t.thickness:g}"]
        for t in arch.finishTypes
        if t.id in used
    ]
    if finish_rows:
        out.append(
            Table(
                "Finishes",
                [
                    {"key": "code", "title": "Code", "width": 6},
                    {"key": "name", "title": "Finish", "width": 20},
                    {"key": "kind", "title": "Kind", "width": 7},
                    {"key": "thickness", "title": "Thickness\n(mm)", "align": "right"},
                ],
                finish_rows,
            )
        )
    return out


__all__ = [
    "CUT",
    "PLAN_NOTES",
    "PREFIX",
    "SIDES",
    "door_window_tables",
    "elevation",
    "floor_plan",
    "plan_levels",
    "room_tables",
    "section",
    "section_lines",
    "unenclosed_rooms",
    "wall_geometry",
]

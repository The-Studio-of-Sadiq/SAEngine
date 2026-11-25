"""Thermal zones and their surfaces from the building model (``06 BIM``).

One thermal zone per story, from the story's floor up to the story above: its plan is the union
of the story's slabs (or, for a story without slabs, such as a ground floor on grade, the slabs
of the story above). The topmost story of the building model is its roof and has no zone.

- Walls: one exterior wall on every edge of the plan outline (and of a courtyard), from the
  floor to the next story, facing out; its windows a centred strip of the facade's
  window-to-wall ratio (N, E, S, W by the wall's outward normal; plan +Y is north); a ratio
  not given is Part 3 Sec 4.5.1.2's least for a room as deep as the plan behind the facade.
- Floors and ceilings: where two zones overlap in plan, a pair of interzone surfaces (the same
  polygon, facing both ways: heat flows between a conditioned and an unconditioned story);
  where a story is not covered by the one above, a roof; where it overhangs the one below, an
  exposed floor; the lowest zone's floor on the ground is adiabatic (the ground under a building
  is cooler than the air in summer: leaving it out is on the safe side).
- Walls of a zone whose ceiling is below the ground are adiabatic (basements).

Plan coordinates come in mm (the building model's) and leave in m (EnergyPlus's).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any

from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import split, unary_union

from saengine.hvac import tables as T
from saengine.plumbing.building import Building

#: Pieces smaller than this are dropped [m²].
MIN_AREA = 0.05
#: Walls shorter than this have no window [m].
MIN_WINDOW_WALL = 0.5
#: Clearance of a window strip from the wall's ends, sill and head [m].
WINDOW_MARGIN = 0.05

Point3 = tuple[float, float, float]


@dataclass
class Window:
    name: str
    vertices: list[Point3]
    width: float
    height: float

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass
class Surface:
    name: str
    kind: str  # Wall, Floor, Ceiling, Roof
    construction: str  # Wall, Roof, Floor
    boundary: str  # Outdoors, Adiabatic, Surface
    vertices: list[Point3]
    area: float
    other: str | None = None  # the paired surface for "Surface"
    facade: str | None = None  # N, E, S, W for walls
    azimuth: float | None = None
    windows: list[Window] = field(default_factory=list)


@dataclass
class ThermalZone:
    name: str
    story: str
    level: float  # m
    height: float  # m
    plan: Any  # shapely (Multi)Polygon in m
    conditioned: bool
    entry: Any  # the 07 MEP hvac story (None for an unlisted story)
    surfaces: list[Surface] = field(default_factory=list)
    room: str | None = None
    roomLabel: str | None = None

    @property
    def area(self) -> float:
        return float(self.plan.area)

    @property
    def volume(self) -> float:
        return self.area * self.height

    def walls(self) -> list[Surface]:
        return [s for s in self.surfaces if s.kind == "Wall"]

    def by_kind(self, kind: str, boundary: str | None = None) -> list[Surface]:
        return [
            s
            for s in self.surfaces
            if s.kind == kind and (boundary is None or s.boundary == boundary)
        ]


@dataclass
class Zoning:
    zones: list[ThermalZone]
    notes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def facade_of(azimuth: float) -> str:
    """N, E, S or W for an outward normal's azimuth (degrees clockwise from north)."""
    a = azimuth % 360.0
    if a >= 315.0 or a < 45.0:
        return "N"
    if a < 135.0:
        return "E"
    if a < 225.0:
        return "S"
    return "W"


def _polygons(geometry: Any) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    return [g for g in getattr(geometry, "geoms", []) if isinstance(g, Polygon)]


def _clean(geometry: Any) -> Any:
    """A tidy plan: no slivers, no collinear points, outer rings counter-clockwise."""
    parts = []
    for p in _polygons(geometry.buffer(0) if geometry is not None else None):
        p = p.simplify(0.005, preserve_topology=True)
        if p.area >= MIN_AREA:
            parts.append(orient(p, 1.0))
    if not parts:
        return Polygon()
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def _without_holes(polygon: Polygon) -> list[Polygon]:
    """Pieces of a polygon that have no holes (EnergyPlus surfaces cannot have any): split by a
    line in Y through each hole until none is left."""
    pending, done = [polygon], []
    while pending:
        p = pending.pop()
        if not p.interiors:
            done.append(p)
            continue
        x = Polygon(p.interiors[0]).centroid.x
        _, miny, _, maxy = p.bounds
        cut = LineString([(x, miny - 1.0), (x, maxy + 1.0)])
        pieces = [g for g in split(p, cut).geoms if isinstance(g, Polygon)]
        if len(pieces) < 2:  # cannot split: keep the outer ring
            done.append(Polygon(p.exterior))
            continue
        pending.extend(pieces)
    out = []
    for p in done:
        p = p.simplify(0.001, preserve_topology=True)
        if p.area >= MIN_AREA:
            out.append(orient(p, 1.0))
    return out


def pieces(geometry: Any) -> list[Polygon]:
    """Hole-free, counter-clockwise pieces of a plan region (m)."""
    out = []
    for p in _polygons(geometry):
        out.extend(_without_holes(p))
    return out


def _ring(polygon: Polygon) -> list[tuple[float, float]]:
    coords = list(polygon.exterior.coords)[:-1]
    return [(float(x), float(y)) for x, y in coords]


def _horizontal(polygon: Polygon, z: float, up: bool) -> list[Point3]:
    """The vertices of a horizontal surface facing up (counter-clockwise seen from above) or
    down (clockwise)."""
    ring = _ring(polygon)
    if not up:
        ring = ring[::-1]
    return [(x, y, z) for x, y in ring]


def _plan(building: Building, story: str, above: str | None) -> Any:
    """A story's plan in m: its slabs, else the slabs of the story above."""
    polys = [p for _, p in building.slabs_at(story)]
    if not polys and above is not None:
        polys = [p for _, p in building.slabs_at(above)]
    if not polys:
        return Polygon()
    return _clean(affinity.scale(unary_union(polys), 1e-3, 1e-3, origin=(0, 0)))


def plan_depth(plan: Any, facade: str) -> float:
    """The depth of a zone's plan behind a facade [m]: its extent at right angles to the facade
    (N/S facades: along Y; E/W: along X)."""
    if plan.is_empty:
        return 0.0
    x0, y0, x1, y1 = plan.bounds
    return (y1 - y0) if facade in ("N", "S") else (x1 - x0)


def wwr_of(entry: Any, facade: str, depth: float = 0.0) -> float:
    """The window-to-wall ratio of a facade of a zone's story; when not given, Sec 4.5.1.2's
    least window area for a room as deep as the plan behind the facade (``depth``, m: 20 %
    below 8 m, 30 % to 14 m, 35 % beyond)."""
    value = None if entry is None else getattr(entry.glazing, facade, None)
    return T.default_wwr(depth) if value is None else float(value)


def _window(name: str, a, b, z: float, height: float, wwr: float) -> Window | None:
    length = math.dist(a, b)
    if wwr <= 0 or length < MIN_WINDOW_WALL or height <= 4 * WINDOW_MARGIN:
        return None
    width = length - 2 * WINDOW_MARGIN
    h = min(wwr * length * height / width, height - 2 * WINDOW_MARGIN)
    if h <= 0.01:
        return None
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    s = (a[0] + ux * WINDOW_MARGIN, a[1] + uy * WINDOW_MARGIN)
    e = (b[0] - ux * WINDOW_MARGIN, b[1] - uy * WINDOW_MARGIN)
    sill = z + (height - h) / 2
    head = sill + h
    return Window(
        name,
        [(s[0], s[1], head), (s[0], s[1], sill), (e[0], e[1], sill), (e[0], e[1], head)],
        width,
        h,
    )


def _walls(zone: ThermalZone, below_ground: bool) -> list[Surface]:
    walls = []
    z, h = zone.level, zone.height
    k = 0
    depth = {f: plan_depth(zone.plan, f) for f in ("N", "E", "S", "W")}
    for polygon in _polygons(zone.plan):
        rings = [polygon.exterior, *polygon.interiors]
        for ring in rings:
            coords = [(float(x), float(y)) for x, y in list(ring.coords)]
            for a, b in itertools.pairwise(coords):
                length = math.dist(a, b)
                if length < 0.05:
                    continue
                k += 1
                nx, ny = (b[1] - a[1]) / length, -(b[0] - a[0]) / length
                azimuth = math.degrees(math.atan2(nx, ny)) % 360.0
                facade = facade_of(azimuth)
                name = f"{zone.name} wall {k}"
                wall = Surface(
                    name, "Wall", "Wall", "Adiabatic" if below_ground else "Outdoors",
                    [(a[0], a[1], z + h), (a[0], a[1], z), (b[0], b[1], z), (b[0], b[1], z + h)],
                    length * h, facade=facade, azimuth=azimuth,
                )  # fmt: skip
                if not below_ground:
                    window = _window(
                        f"{name} window", a, b, z, h, wwr_of(zone.entry, facade, depth[facade])
                    )
                    if window is not None:
                        wall.windows.append(window)
                walls.append(wall)
    return walls


def _split_segments(
    ring_coords: list[tuple[float, float]], split_points: list[tuple[float, float]]
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Split each edge of ``ring_coords`` at any point in ``split_points`` lying strictly on it."""
    segs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for a, b in itertools.pairwise(ring_coords):
        length = math.dist(a, b)
        if length < 0.05:
            continue
        ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        ts = [0.0, length]
        for vx, vy in split_points:
            t = (vx - a[0]) * ux + (vy - a[1]) * uy
            d = abs((vx - a[0]) * uy - (vy - a[1]) * ux)
            if 1e-3 < t < length - 1e-3 and d < 1e-3:
                ts.append(t)
        ts.sort()
        clean_ts = [ts[0]]
        for t in ts[1:]:
            if t - clean_ts[-1] > 1e-3:
                clean_ts.append(t)
        if clean_ts[-1] < length - 1e-4:
            clean_ts[-1] = length
        for t0, t1 in itertools.pairwise(clean_ts):
            if t1 - t0 < 0.05:
                continue
            p = (a[0] + ux * t0, a[1] + uy * t0)
            q = (a[0] + ux * t1, a[1] + uy * t1)
            segs.append((p, q))
    return segs


def _arch_windows_for_story(
    arch: Any, story: str, elevations: dict[str, float]
) -> list[dict[str, Any]]:
    """Windows of ``arch`` hosted on walls of ``story``, in metres (centre, width, height, sill, tol)."""
    if arch is None or not getattr(arch, "windows", None):
        return []
    from saengine.library import architecture as arch_lib

    walls = {w.id: (w, wt) for w, wt in arch_lib.walls_on_story(arch, story, elevations)}
    out: list[dict[str, Any]] = []
    for win in arch.windows:
        if win.wall not in walls:
            continue
        wall, wall_type = walls[win.wall]
        centre = arch_lib.centre_line(wall, wall_type)
        pt = arch_lib.point_along(centre, win.offset)
        w_mm, h_mm, sill_mm = arch_lib.opening_size(arch, win)
        out.append(
            {
                "id": win.id,
                "cx": pt[0] * 1e-3,
                "cy": pt[1] * 1e-3,
                "width": w_mm * 1e-3,
                "height": h_mm * 1e-3,
                "sill": sill_mm * 1e-3,
                "tol": max(wall_type.thickness * 1e-3, 0.25),
            }
        )
    return out


def _windows_on_segment(
    name: str,
    a: tuple[float, float],
    b: tuple[float, float],
    z: float,
    height: float,
    arch_windows: list[dict[str, Any]],
) -> list[Window]:
    """Architectural windows whose centres lie on exterior wall segment ``a``->``b``."""
    length = math.dist(a, b)
    if length < MIN_WINDOW_WALL or height <= 4 * WINDOW_MARGIN:
        return []
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    found: list[Window] = []
    for k, aw in enumerate(arch_windows, 1):
        dx, dy = aw["cx"] - a[0], aw["cy"] - a[1]
        t = dx * ux + dy * uy
        perp = abs(dx * uy - dy * ux)
        if perp > aw["tol"] or t < -0.05 or t > length + 0.05:
            continue
        half = aw["width"] / 2.0
        s_t = max(WINDOW_MARGIN, t - half)
        e_t = min(length - WINDOW_MARGIN, t + half)
        w = e_t - s_t
        if w <= 0.05:
            continue
        sill = z + max(WINDOW_MARGIN, min(aw["sill"], height - 2 * WINDOW_MARGIN))
        head = min(z + height - WINDOW_MARGIN, sill + aw["height"])
        h = head - sill
        if h <= 0.05:
            continue
        s = (a[0] + ux * s_t, a[1] + uy * s_t)
        e = (a[0] + ux * e_t, a[1] + uy * e_t)
        found.append(
            Window(
                f"{name} window {k}",
                [(s[0], s[1], head), (s[0], s[1], sill), (e[0], e[1], sill), (e[0], e[1], head)],
                w,
                h,
            )
        )
    return found


def _story_room_walls(
    story_zones: list[ThermalZone],
    story_plan: Any,
    below_ground: bool,
    arch: Any = None,
    elevations: dict[str, float] | None = None,
) -> None:
    """Walls for multiple zones on one story: matching ``Surface`` pairs on shared boundaries,
    ``Outdoors`` (or ``Adiabatic``) on exterior walls."""
    all_pts: list[tuple[float, float]] = []
    for z in story_zones:
        for poly in _polygons(z.plan):
            for ring in (poly.exterior, *poly.interiors):
                all_pts.extend((float(x), float(y)) for x, y in ring.coords)
    zone_segs: list[list[tuple[tuple[float, float], tuple[float, float]]]] = []
    for zone in story_zones:
        segs: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for poly in _polygons(zone.plan):
            for ring in (poly.exterior, *poly.interiors):
                coords = [(float(x), float(y)) for x, y in ring.coords]
                segs.extend(_split_segments(coords, all_pts))
        zone_segs.append(segs)
    used: set[tuple[int, int]] = set()
    wall_num = [0] * len(story_zones)
    arch_wins = (
        _arch_windows_for_story(arch, story_zones[0].story, elevations or {})
        if story_zones and arch is not None and elevations
        else []
    )
    use_arch_windows = bool(arch_wins)
    depths = [{f: plan_depth(z.plan, f) for f in ("N", "E", "S", "W")} for z in story_zones]
    for i, zone in enumerate(story_zones):
        z_lvl, h = zone.level, zone.height
        for si, (a, b) in enumerate(zone_segs[i]):
            if (i, si) in used:
                continue
            length = math.dist(a, b)
            mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
            nx, ny = (b[1] - a[1]) / length, -(b[0] - a[0]) / length
            azimuth = math.degrees(math.atan2(nx, ny)) % 360.0
            facade = facade_of(azimuth)
            match: tuple[int, int, tuple[float, float], tuple[float, float]] | None = None
            for j, other in enumerate(story_zones):
                if j <= i:
                    continue
                for sj, (oa, ob) in enumerate(zone_segs[j]):
                    if (j, sj) in used:
                        continue
                    omid = ((oa[0] + ob[0]) / 2.0, (oa[1] + ob[1]) / 2.0)
                    if abs(math.dist(oa, ob) - length) < 0.02 and math.dist(mid, omid) < 0.02:
                        match = (j, sj, oa, ob)
                        break
                if match is not None:
                    break
            if match is not None:
                j, sj, oa, ob = match
                used.add((i, si))
                used.add((j, sj))
                other = story_zones[j]
                wall_num[i] += 1
                wall_num[j] += 1
                n1 = f"{zone.name} wall {wall_num[i]}"
                n2 = f"{other.name} wall {wall_num[j]}"
                o_az = (azimuth + 180.0) % 360.0
                zone.surfaces.append(
                    Surface(
                        n1,
                        "Wall",
                        "Wall",
                        "Surface",
                        [
                            (a[0], a[1], z_lvl + h),
                            (a[0], a[1], z_lvl),
                            (b[0], b[1], z_lvl),
                            (b[0], b[1], z_lvl + h),
                        ],
                        length * h,
                        other=n2,
                        facade=facade,
                        azimuth=azimuth,
                    )
                )
                other.surfaces.append(
                    Surface(
                        n2,
                        "Wall",
                        "Wall",
                        "Surface",
                        [
                            (oa[0], oa[1], z_lvl + h),
                            (oa[0], oa[1], z_lvl),
                            (ob[0], ob[1], z_lvl),
                            (ob[0], ob[1], z_lvl + h),
                        ],
                        length * h,
                        other=n1,
                        facade=facade_of(o_az),
                        azimuth=o_az,
                    )
                )
                continue
            used.add((i, si))
            wall_num[i] += 1
            name = f"{zone.name} wall {wall_num[i]}"
            on_exterior = story_plan.is_empty or not story_plan.buffer(-0.02).contains(Point(mid))
            boundary = "Adiabatic" if (below_ground or not on_exterior) else "Outdoors"
            wall = Surface(
                name,
                "Wall",
                "Wall",
                boundary,
                [
                    (a[0], a[1], z_lvl + h),
                    (a[0], a[1], z_lvl),
                    (b[0], b[1], z_lvl),
                    (b[0], b[1], z_lvl + h),
                ],
                length * h,
                facade=facade,
                azimuth=azimuth,
            )
            if boundary == "Outdoors":
                if use_arch_windows:
                    wall.windows.extend(_windows_on_segment(name, a, b, z_lvl, h, arch_wins))
                else:
                    win = _window(
                        f"{name} window",
                        a,
                        b,
                        z_lvl,
                        h,
                        wwr_of(zone.entry, facade, depths[i][facade]),
                    )
                    if win is not None:
                        wall.windows.append(win)
            zone.surfaces.append(wall)


def _story_room_zones(
    story: str,
    level: float,
    height: float,
    plan: Any,
    conditioned: bool,
    entry: Any,
    story_rooms: Any,
) -> list[ThermalZone]:
    """Split one story into one :class:`ThermalZone` per architecture room (plus any unallocated
    slab remainder >= MIN_AREA)."""
    out: list[ThermalZone] = []
    room_polys: list[Any] = []
    for room in story_rooms.rooms:
        poly = _clean(affinity.scale(room.face, 1e-3, 1e-3, origin=(0, 0)))
        if not plan.is_empty:
            clipped = _clean(poly.intersection(plan.buffer(0.01)))
            if clipped.area >= MIN_AREA:
                poly = clipped
        if poly.is_empty or poly.area < MIN_AREA:
            continue
        room_polys.append(poly)
        room_cond = conditioned and (room.hvacUse is not None)
        out.append(
            ThermalZone(
                f"Z {story} {room.id}",
                story,
                level,
                height,
                poly,
                room_cond,
                entry,
                room=room.id,
                roomLabel=room.label,
            )
        )
    if not out:
        return []
    covered = unary_union(room_polys)
    rem = _clean(plan.difference(covered))
    if not rem.is_empty and rem.area >= MIN_AREA:
        out.append(
            ThermalZone(
                f"Z {story} Remainder",
                story,
                level,
                height,
                rem,
                conditioned,
                entry,
                room=None,
                roomLabel="Unallocated",
            )
        )
    return out


def zones(
    building: Building,
    hvac: Any,
    rooms: Any = None,
    *,
    by_room: bool = True,
    arch: Any = None,
) -> Zoning:
    """The thermal zones of a building model and the 07 MEP ``hvac`` section.

    When ``rooms`` (:class:`~saengine.mep.rooms.RoomInputs`) has rooms on a story and
    ``by_room`` is True (and the story's ``gainsFrom`` is not ``"typed"``), builds one zone per
    room; otherwise builds one zone per story.
    """
    notes: list[str] = []
    problems: list[str] = []
    order = building.ordered()
    if len(order) < 2:
        return Zoning([], [], ["06 BIM needs at least two stories (a floor and its roof)"])
    entries = {e.story: e for e in (hvac.stories if hvac is not None else [])}
    all_conditioned = not entries
    if all_conditioned:
        notes.append(
            "hvac lists no stories: every story below the roof is taken as conditioned office "
            "space (list the stories to set their use)"
        )
    top = order[-1]
    if top in entries:
        problems.append(
            f"Storey {building.names.get(top, top)} is "
            "the roof of 06 BIM (no storey above it), not an air-conditioned floor: set its use "
            "to Roof in 07 MEP's Storey use, or take it out of the HVAC storeys"
        )
    # the highest story with slabs holds the roof: nothing above it is enclosed (a column or
    # an empty story above the roof slab is no room), so no zone is made at or above it
    with_slabs = [i for i, s in enumerate(order) if building.slabs_at(s)]
    roof_index = with_slabs[-1] if with_slabs else len(order) - 1
    if roof_index < len(order) - 1:
        roof_story = order[roof_index]
        above_roof = order[roof_index:]
        notes.append(
            f"the slabs at {roof_story} are the roof of the building model (no slabs above "
            f"them): no zone at {', '.join(above_roof)}"
        )
        for story in above_roof[:-1]:  # the top story is reported above
            entry = entries.get(story)
            if entry is not None and entry.conditioned:
                problems.append(
                    f"hvac: '{story}' is listed as conditioned but stands on the roof slabs at "
                    f"{roof_story} (no slabs above it in 06 BIM): no zone is made for it"
                )
    result: list[ThermalZone] = []
    story_plans: dict[str, Any] = {}
    for i, story in enumerate(order[:roof_index]):
        above = order[i + 1]
        plan = _plan(building, story, above)
        if plan.is_empty:
            problems.append(f"{story}: no slabs at this story or the one above in 06 BIM")
            continue
        story_plans[story] = plan
        level = building.stories[story] / 1000.0
        height = (building.stories[above] - building.stories[story]) / 1000.0
        entry = entries.get(story)
        conditioned = all_conditioned or (entry is not None and entry.conditioned)
        story_rooms = rooms.story(story) if rooms is not None else None
        use_rooms = (
            by_room
            and story_rooms is not None
            and bool(story_rooms.rooms)
            and (entry is None or entry.gainsFrom != "typed")
        )
        if use_rooms:
            room_zones = _story_room_zones(
                story, level, height, plan, conditioned, entry, story_rooms
            )
            if room_zones:
                result.extend(room_zones)
                continue
        result.append(ThermalZone(f"Z {story}", story, level, height, plan, conditioned, entry))
    ground = building.ground / 1000.0
    by_story: dict[str, list[ThermalZone]] = {}
    for z in result:
        by_story.setdefault(z.story, []).append(z)
    elevations = dict(building.stories)
    for story, story_zones in by_story.items():
        below_ground = story_zones[0].level + story_zones[0].height <= ground + 1e-6
        if len(story_zones) == 1 and story_zones[0].room is None:
            zone = story_zones[0]
            zone.surfaces.extend(_walls(zone, below_ground))
        else:
            _story_room_walls(story_zones, story_plans[story], below_ground, arch, elevations)
    problems.extend(_horizontals(result))
    if result and result[0].level + result[0].height <= ground + 1e-6:
        notes.append("walls of stories below the ground are taken as adiabatic")
    if result:
        notes.append(
            f"the floor of the lowest zone ({result[0].story}) is taken as adiabatic (ground)"
        )
    return Zoning(result, notes, problems)


def _touching(lower: ThermalZone, upper: ThermalZone) -> bool:
    """Whether ``upper`` starts where ``lower`` ends (no story without a zone between them)."""
    return abs(lower.level + lower.height - upper.level) < 1e-6


def _horizontals(result: list[ThermalZone]) -> list[str]:
    """Add each zone's floors, ceilings and roofs; the problems of a gap between zones (a story
    skipped for having no slabs): the faces on the gap are taken as outdoors."""
    problems = []
    groups: list[list[ThermalZone]] = []
    for z in result:
        if groups and groups[-1][0].story == z.story:
            groups[-1].append(z)
        else:
            groups.append([z])
    for i, story_zones in enumerate(groups):
        below_zones = groups[i - 1] if i > 0 else None
        above_zones = groups[i + 1] if i + 1 < len(groups) else None
        rep = story_zones[0]
        if above_zones is not None and not _touching(rep, above_zones[0]):
            problems.append(
                f"{rep.story}: no zone between it and {above_zones[0].story} (a story without slabs): "
                f"the ceiling of {rep.story} and the floor of {above_zones[0].story} are taken as "
                "exposed to the outside air"
            )
            above_zones = None
        z_floor, z_ceiling = rep.level, rep.level + rep.height
        below_union = (
            unary_union([b.plan for b in below_zones])
            if below_zones is not None and _touching(below_zones[0], rep)
            else None
        )
        above_union = (
            unary_union([a.plan for a in above_zones]) if above_zones is not None else None
        )
        for zone in story_zones:
            if below_zones is None:
                for k, p in enumerate(pieces(zone.plan), 1):
                    zone.surfaces.append(
                        Surface(f"{zone.name} floor {k}", "Floor", "Floor", "Adiabatic",
                                _horizontal(p, z_floor, up=False), p.area)
                    )  # fmt: skip
            else:
                exposed = (
                    zone.plan.difference(below_union) if below_union is not None else zone.plan
                )
                for k, p in enumerate(pieces(exposed), 1):
                    zone.surfaces.append(
                        Surface(f"{zone.name} exposed floor {k}", "Floor", "Floor", "Outdoors",
                                _horizontal(p, z_floor, up=False), p.area)
                    )  # fmt: skip
            if above_zones is None:
                for k, p in enumerate(pieces(zone.plan), 1):
                    zone.surfaces.append(
                        Surface(f"{zone.name} roof {k}", "Roof", "Roof", "Outdoors",
                                _horizontal(p, z_ceiling, up=True), p.area)
                    )  # fmt: skip
                continue
            exposed = zone.plan.difference(above_union)
            for k, p in enumerate(pieces(exposed), 1):
                zone.surfaces.append(
                    Surface(f"{zone.name} roof {k}", "Roof", "Roof", "Outdoors",
                            _horizontal(p, z_ceiling, up=True), p.area)
                )  # fmt: skip
            k = 0
            for upper in above_zones:
                shared = zone.plan.intersection(upper.plan)
                if shared.is_empty or shared.area < MIN_AREA:
                    continue
                for p in pieces(shared):
                    k += 1
                    ceiling = f"{zone.name} ceiling {k}"
                    floor = f"{upper.name} floor {zone.name} {k}"
                    zone.surfaces.append(
                        Surface(ceiling, "Ceiling", "Floor", "Surface",
                                _horizontal(p, z_ceiling, up=True), p.area, other=floor)
                    )  # fmt: skip
                    upper.surfaces.append(
                        Surface(floor, "Floor", "Floor", "Surface",
                                _horizontal(p, z_ceiling, up=False), p.area, other=ceiling)
                    )  # fmt: skip
    return problems

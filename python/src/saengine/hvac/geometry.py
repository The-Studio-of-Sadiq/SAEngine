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
from shapely.geometry import LineString, MultiPolygon, Polygon
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


def zones(building: Building, hvac: Any) -> Zoning:
    """The thermal zones of a building model and the 07 MEP ``hvac`` section."""
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
    for i, story in enumerate(order[:roof_index]):
        above = order[i + 1]
        plan = _plan(building, story, above)
        if plan.is_empty:
            problems.append(f"{story}: no slabs at this story or the one above in 06 BIM")
            continue
        level = building.stories[story] / 1000.0
        height = (building.stories[above] - building.stories[story]) / 1000.0
        entry = entries.get(story)
        conditioned = all_conditioned or (entry is not None and entry.conditioned)
        result.append(ThermalZone(f"Z {story}", story, level, height, plan, conditioned, entry))
    ground = building.ground / 1000.0
    for i, zone in enumerate(result):
        zone.surfaces.extend(_walls(zone, zone.level + zone.height <= ground + 1e-6))
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
    for i, zone in enumerate(result):
        below = result[i - 1] if i > 0 else None
        above = result[i + 1] if i + 1 < len(result) else None
        if above is not None and not _touching(zone, above):
            problems.append(
                f"{zone.story}: no zone between it and {above.story} (a story without slabs): "
                f"the ceiling of {zone.story} and the floor of {above.story} are taken as "
                "exposed to the outside air"
            )
            above = None
        z_floor, z_ceiling = zone.level, zone.level + zone.height
        # floor: the interface with the zone below is made when that zone's ceiling is
        if below is None:
            for k, p in enumerate(pieces(zone.plan), 1):
                zone.surfaces.append(
                    Surface(f"{zone.name} floor {k}", "Floor", "Floor", "Adiabatic",
                            _horizontal(p, z_floor, up=False), p.area)
                )  # fmt: skip
        else:
            # over a gap (a skipped story) the whole floor is exposed
            exposed = zone.plan.difference(below.plan) if _touching(below, zone) else zone.plan
            for k, p in enumerate(pieces(exposed), 1):
                zone.surfaces.append(
                    Surface(f"{zone.name} exposed floor {k}", "Floor", "Floor", "Outdoors",
                            _horizontal(p, z_floor, up=False), p.area)
                )  # fmt: skip
        if above is None:
            for k, p in enumerate(pieces(zone.plan), 1):
                zone.surfaces.append(
                    Surface(f"{zone.name} roof {k}", "Roof", "Roof", "Outdoors",
                            _horizontal(p, z_ceiling, up=True), p.area)
                )  # fmt: skip
            continue
        exposed = zone.plan.difference(above.plan)
        for k, p in enumerate(pieces(exposed), 1):
            zone.surfaces.append(
                Surface(f"{zone.name} roof {k}", "Roof", "Roof", "Outdoors",
                        _horizontal(p, z_ceiling, up=True), p.area)
            )  # fmt: skip
        shared = zone.plan.intersection(above.plan)
        for k, p in enumerate(pieces(shared), 1):
            ceiling = f"{zone.name} ceiling {k}"
            floor = f"{above.name} floor {k}"
            zone.surfaces.append(
                Surface(ceiling, "Ceiling", "Floor", "Surface",
                        _horizontal(p, z_ceiling, up=True), p.area, other=floor)
            )  # fmt: skip
            above.surfaces.append(
                Surface(floor, "Floor", "Floor", "Surface",
                        _horizontal(p, z_ceiling, up=False), p.area, other=ceiling)
            )  # fmt: skip
    return problems

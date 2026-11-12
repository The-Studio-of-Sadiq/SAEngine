"""The plot of the soil report's site: its shape in the project grid, its sides, the buildable
envelope the setbacks leave, the members of the floor plan that lie outside them, and the grid
frame that lines up with it. The one place of the plot's geometry (shapely); the workbench
shows what these return.

- :func:`plot_ring`: the plot's corners in project mm, from the site boundary (latitude/
  longitude, through the site point) or the plot's own corners (project grid);
- :func:`describe`: area (m², katha, decimal), perimeter, each side's length, bearing and
  setback, the envelope, and the grid frame of the plot (:func:`fit_frame`);
- :func:`envelope`: the buildable envelope, the plot less each side's setback;
- :func:`encroachments`: floor plan members outside the plot or inside the setbacks;
- :func:`aligned_site`: the site with the grid turned along the plot, for a new building.

Units: lengths in mm and areas in m² unless named otherwise. Bearings are clockwise from true
north [°]; the project +Y axis points ``site.rotation``.
"""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry
    from shapely.geometry.polygon import Polygon

    from saengine.library.soil import Site

#: One square foot [m²].
SQ_FT = 0.3048**2
#: 1 katha = 720 sq ft; 1 decimal (shotangsho) = 435.6 sq ft (1/100 acre), as in Bangladesh.
KATHA = 720 * SQ_FT
DECIMAL = 435.6 * SQ_FT

#: Lengths closer than this are the same [mm].
TOLERANCE = 1.0

COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

Point = tuple[float, float]


# ─────────────────────────────── the ring ───────────────────────────────


def plot_ring(site: Site | None) -> tuple[list[Point] | None, str | None]:
    """The plot's corners in project mm (open ring, as given) and why there are none.

    The site boundary (WGS 84) is the plot when given, placed in the project grid by the site
    point; without it, the plot's own corners in project mm."""
    if site is None:
        return None, None
    if len(site.boundary) >= 3:
        if not site.georeferenced:
            return None, (
                "The plot boundary is in latitude/longitude, but the site has no position: set "
                "the site point to place the plot in the project grid."
            )
        from saengine.gis.crs import Grid

        grid = Grid(site)
        return [grid.from_wgs84(lat, lon) for lon, lat in site.boundary], None
    points = site.plot.points if site.plot is not None else []
    if len(points) >= 3:
        return [(float(x), float(y)) for x, y in points], None
    return None, None


def _polygon(ring: list[Point]) -> Polygon:
    from shapely.geometry import Polygon

    return Polygon(ring)


def _orientation(ring: list[Point]) -> float:
    """+1 when the ring runs counter-clockwise, -1 clockwise."""
    area = sum(
        x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True)
    )
    return 1.0 if area >= 0 else -1.0


def counter_clockwise(
    ring: list[list[float]], road: int | None
) -> tuple[list[list[float]], int | None]:
    """``ring`` (open) counter-clockwise, as GIS files write a polygon's exterior, and the index
    of the road side in that order (reversed, side i becomes side n - 1 - i)."""
    if _orientation([(p[0], p[1]) for p in ring]) > 0:
        return ring, road
    reversed_ring = [ring[0], *ring[:0:-1]]
    return reversed_ring, None if road is None else len(ring) - 1 - road


def bearing(dx: float, dy: float, rotation: float) -> float:
    """The bearing of the project direction (dx, dy), clockwise from true north [°, 0-360)."""
    return (rotation + math.degrees(math.atan2(dx, dy))) % 360


def compass(degrees: float) -> str:
    return COMPASS[round(degrees / 45) % 8]


def _outward(ring: list[Point], i: int) -> Point:
    """The unit outward normal of side ``i`` (corner i to i + 1)."""
    (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % len(ring)]
    length = math.hypot(x2 - x1, y2 - y1) or 1.0
    s = _orientation(ring)
    return s * (y2 - y1) / length, -s * (x2 - x1) / length


def side_kinds(ring: list[Point], road: int | None) -> list[str | None]:
    """Each side's kind: "front" (the road side), "rear" (facing away from the road, within
    45°) or "side"; all None without a road side."""
    if road is None or not 0 <= road < len(ring):
        return [None] * len(ring)
    fx, fy = _outward(ring, road)
    kinds: list[str | None] = []
    for i in range(len(ring)):
        if i == road:
            kinds.append("front")
            continue
        nx, ny = _outward(ring, i)
        kinds.append("rear" if nx * fx + ny * fy < -math.cos(math.radians(45)) else "side")
    return kinds


def setbacks(site: Site, ring: list[Point]) -> list[float]:
    """Each side's setback [mm]: front, rear or side by its kind; without a road side every
    side takes the side setback."""
    plot = site.plot
    if plot is None:
        return [0.0] * len(ring)
    by_kind = {"front": plot.front, "rear": plot.rear, "side": plot.side, None: plot.side}
    return [float(by_kind[k]) for k in side_kinds(ring, plot.road)]


def envelope(ring: list[Point], distances: list[float]) -> Polygon | None:
    """The buildable envelope: the points of the plot at least each side's setback from that
    side (the plot less a band along each side); its largest part, or None when nothing is
    left."""
    from shapely.geometry import LineString
    from shapely.ops import unary_union

    polygon = _polygon(ring).buffer(0)
    bands = [
        LineString([ring[i], ring[(i + 1) % len(ring)]]).buffer(d, join_style="mitre")
        for i, d in enumerate(distances)
        if d > 0
    ]
    shape = polygon.difference(unary_union(bands)) if bands else polygon
    parts = [g for g in getattr(shape, "geoms", [shape]) if g.geom_type == "Polygon"]
    parts = [g for g in parts if g.area > TOLERANCE**2]
    if not parts:
        return None
    return max(parts, key=lambda g: g.area).simplify(TOLERANCE / 2)


def _open_ring(polygon: Polygon) -> list[list[float]]:
    coords = list(polygon.exterior.coords)[:-1]
    return [[round(x, 1), round(y, 1)] for x, y in coords]


# ─────────────────────────────── the grid frame ───────────────────────────────


def _rotate(point: Point, degrees: float) -> Point:
    """The coordinates of ``point`` in the grid turned ``degrees`` clockwise about its origin
    (the point turned as much counter-clockwise)."""
    a = math.radians(degrees)
    x, y = point
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


def frame_turn(ring: list[Point], road: int | None) -> float:
    """How far to turn the grid clockwise [°] so the road side runs along X with the plot
    above it (+Y away from the road); without a road side, the longest side."""
    if road is None or not 0 <= road < len(ring):
        lengths = [math.dist(ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring))]
        road = lengths.index(max(lengths))
    nx, ny = _outward(ring, road)
    # The new +Y is the inward normal (-nx, -ny); its angle clockwise from the old +Y.
    turn = math.degrees(math.atan2(-nx, -ny))
    return round(turn, 6) % 360


def inscribed_rectangle(polygon: Polygon) -> tuple[float, float, float, float]:
    """The largest axis-parallel rectangle (x0, y0, x1, y1) inside ``polygon`` with its sides
    on the polygon's corner coordinates (exact for rectangles and L or stepped shapes)."""
    from shapely.geometry import box

    shrunk = polygon.buffer(TOLERANCE / 10)
    xs = sorted({round(x, 3) for x, _ in polygon.exterior.coords})
    ys = sorted({round(y, 3) for _, y in polygon.exterior.coords})
    best = (0.0, (0.0, 0.0, 0.0, 0.0))
    for i, x0 in enumerate(xs):
        for x1 in xs[i + 1 :]:
            for j, y0 in enumerate(ys):
                for y1 in ys[j + 1 :]:
                    area = (x1 - x0) * (y1 - y0)
                    if area > best[0] and shrunk.contains(box(x0, y0, x1, y1)):
                        best = (area, (x0, y0, x1, y1))
    if best[0] == 0:
        x0, y0, x1, y1 = polygon.bounds
        return x0, y0, x1, y1
    return best[1]


#: The grid lines of a building fitted to the envelope keep this far inside it [mm], so the
#: faces of columns up to twice as wide stay in it.
GRID_INSET = 300.0


def fit_frame(site: Site, ring: list[Point], buildable: Polygon) -> dict[str, Any]:
    """The grid frame of the plot: turned ``turn``° clockwise so the road side runs along X,
    with the origin :data:`GRID_INSET` inside the lower-left corner of the largest rectangle in
    the envelope: ``{turn, rotation, origin, width, depth, inset, plot, envelope}`` (``width`` ×
    ``depth`` the room for the grid lines; plot and envelope in that frame [mm])."""
    turn = frame_turn(ring, site.plot.road if site.plot else None)
    turned = [_rotate(p, turn) for p in buildable.exterior.coords]
    x0, y0, x1, y1 = inscribed_rectangle(_polygon(turned))
    inset = min(GRID_INSET, (x1 - x0) / 4, (y1 - y0) / 4)
    x0, y0, x1, y1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
    shift = lambda p: [round(p[0] - x0, 1) + 0.0, round(p[1] - y0, 1) + 0.0]
    return {
        "turn": turn,
        "rotation": round((site.rotation + turn) % 360, 6),
        "origin": [round(x0, 1), round(y0, 1)],
        "width": round(x1 - x0, 1),
        "depth": round(y1 - y0, 1),
        "inset": round(inset, 1),
        "plot": [shift(_rotate(p, turn)) for p in ring],
        "envelope": [shift(p) for p in turned[:-1]],
    }


def aligned_site(site: Site) -> dict[str, Any] | None:
    """The site with the project grid in the plot's frame (:func:`fit_frame`): the same place
    on the earth, the grid turned along the plot and its origin at the envelope's lower-left
    corner. Plot corners given in the project grid are moved with it; a boundary in
    latitude/longitude stays as it is. None without a plot or an envelope."""
    ring, _ = plot_ring(site)
    if ring is None:
        return None
    buildable = envelope(ring, setbacks(site, ring))
    if buildable is None:
        return None
    frame = fit_frame(site, ring, buildable)
    turn = frame["turn"]
    ox, oy = frame["origin"]
    data = site.model_dump(mode="json", exclude_none=True)
    # The site point keeps its place: project (x, y) there becomes the turned point less the origin.
    x, y = _rotate((site.x, site.y), turn)
    data["x"], data["y"] = round(x - ox, 1), round(y - oy, 1)
    data["rotation"] = frame["rotation"] if frame["rotation"] <= 180 else frame["rotation"] - 360
    if not site.boundary and site.plot is not None:
        data["plot"]["points"] = frame["plot"]
    return data


# ─────────────────────────────── describe ───────────────────────────────


def describe(site: Site | None) -> dict[str, Any] | None:
    """The plot as the site map shows it, or None when the site has no plot:

    ``{given ("wgs84"|"project"), ring [[x, y]] mm, lonlat [[lon, lat]] (closed, null without a
    site point), area m², katha, decimal, perimeter mm, sides [{index, length mm, bearing °,
    faces °, facing, kind, setback mm}], road, envelope [[x, y]] | null, envelopeLonlat,
    envelopeArea m², fit (:func:`fit_frame`) | null, problems}``."""
    if site is None:
        return None
    ring, problem = plot_ring(site)
    if ring is None:
        if problem is None:
            return None
        return {
            "given": "wgs84",
            "ring": None,
            "lonlat": [list(p) for p in site.boundary] + [list(site.boundary[0])],
            "problems": [problem],
        }
    problems: list[str] = []
    polygon = _polygon(ring)
    if not polygon.is_valid:
        problems.append("The plot's sides cross each other: move the corners so they do not.")
    area = abs(polygon.area) / 1e6
    kinds = side_kinds(ring, site.plot.road if site.plot else None)
    distances = setbacks(site, ring)
    rotation = site.rotation
    sides = []
    for i in range(len(ring)):
        (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % len(ring)]
        nx, ny = _outward(ring, i)
        faces = bearing(nx, ny, rotation)
        sides.append(
            {
                "index": i,
                "length": round(math.hypot(x2 - x1, y2 - y1), 1),
                "bearing": round(bearing(x2 - x1, y2 - y1, rotation), 2),
                "faces": round(faces, 2),
                "facing": compass(faces),
                "kind": kinds[i],
                "setback": distances[i],
            }
        )
    plot = site.plot
    if plot is not None and plot.road is None and (plot.front or plot.rear):
        problems.append(
            "Choose the side facing the road: until then every side takes the side setback."
        )
    buildable = envelope(ring, distances) if polygon.is_valid else None
    if polygon.is_valid and buildable is None:
        problems.append("The setbacks leave no buildable area on the plot.")
    grid = None
    if site.georeferenced:
        from saengine.gis.crs import Grid

        grid = Grid(site)

    def lonlat(points: list[list[float]]) -> list[list[float]] | None:
        if grid is None:
            return None
        out = [
            [round(lon, 8), round(lat, 8)] for lat, lon in (grid.to_wgs84(x, y) for x, y in points)
        ]
        return out + [list(out[0])]

    ring_out = [[round(x, 1), round(y, 1)] for x, y in ring]
    envelope_out = _open_ring(buildable) if buildable is not None else None
    given = "wgs84" if len(site.boundary) >= 3 else "project"
    return {
        "given": given,
        "ring": ring_out,
        # A boundary given in latitude/longitude stays exactly as given.
        "lonlat": [list(p) for p in site.boundary] + [list(site.boundary[0])]
        if given == "wgs84"
        else lonlat(ring_out),
        "area": round(area, 3),
        "katha": round(area / KATHA, 3),
        "decimal": round(area / DECIMAL, 3),
        "perimeter": round(polygon.length, 1),
        "sides": sides,
        "road": plot.road if plot is not None else None,
        "envelope": envelope_out,
        "envelopeLonlat": lonlat(envelope_out) if envelope_out else None,
        "envelopeArea": round(buildable.area / 1e6, 3) if buildable is not None else None,
        "fit": fit_frame(site, ring, buildable) if buildable is not None else None,
        "problems": problems,
    }


# ─────────────────────────────── encroachments ───────────────────────────────


def _profile_outline(profile: dict[str, Any]) -> BaseGeometry | None:
    """A column section centred on the origin (rectangle or circle), as the floor plan draws it."""
    from shapely.geometry import Point as ShapelyPoint
    from shapely.geometry import box

    shape = profile.get("shape")
    if shape in ("rectangle", "rectangleHollow"):
        w, d = profile.get("xDim"), profile.get("yDim")
        if isinstance(w, int | float) and isinstance(d, int | float) and w > 0 and d > 0:
            return box(-w / 2, -d / 2, w / 2, d / 2)
    if shape in ("circle", "circleHollow"):
        r = profile.get("radius")
        if isinstance(r, int | float) and r > 0:
            return ShapelyPoint(0, 0).buffer(r, 16)
    return None


def _width(type_: dict[str, Any] | None) -> float | None:
    """A beam's width or a wall's thickness [mm]."""
    if not type_:
        return None
    thickness = type_.get("thickness")
    if isinstance(thickness, int | float) and thickness > 0:
        return float(thickness)
    profile = type_.get("profile") or {}
    width = profile.get("xDim") or (2 * profile["radius"] if profile.get("radius") else None)
    return float(width) if isinstance(width, int | float) and width > 0 else None


def _members(plan: Any, types: dict[str, dict[str, Any]]) -> list[tuple[str, str, str, Any]]:
    """(group, id, story, plan shape) of the columns, walls, beams and slabs; columns and
    walls on the plan of the story they rise to, as the floor plan shows them."""
    from shapely import affinity
    from shapely.geometry import LineString, Polygon

    xs = {g.label: g.position for g in plan.grids.x}
    ys = {g.label: g.position for g in plan.grids.y}

    def at(p: Any) -> Point:
        return xs[p.x] + p.dx, ys[p.y] + p.dy

    out: list[tuple[str, str, str, Any]] = []
    for column in plan.columns:
        x, y = at(column.at)
        outline = _profile_outline((types.get(column.type) or {}).get("profile") or {})
        if outline is None:
            from shapely.geometry import Point as ShapelyPoint

            shape = ShapelyPoint(x, y)
        else:
            shape = affinity.translate(affinity.rotate(outline, column.rotation, (0, 0)), x, y)
        out.append(("column", column.id, column.top, shape))
    for group, members in (("wall", plan.walls), ("beam", plan.beams)):
        for member in members:
            line = LineString([at(member.start), at(member.end)])
            width = _width(types.get(member.type))
            shape = line.buffer(width / 2, cap_style="flat") if width and line.length else line
            story = member.top if group == "wall" else member.story
            out.append((group, member.id, story, shape))
    for slab in plan.slabs:
        corners = [at(c) for c in slab.boundary]
        out.append(("slab", slab.id, slab.story, Polygon(corners).exterior))
    return out


def _worst(shape: Any, region: Any) -> tuple[float, Point] | None:
    """How far the farthest part of ``shape`` is outside ``region`` [mm] and where, or None
    when it is inside (within :data:`TOLERANCE`)."""
    from shapely import segmentize
    from shapely.geometry import Point as ShapelyPoint

    boundary = shape.exterior if shape.geom_type == "Polygon" else shape
    worst: tuple[float, Point] | None = None
    for x, y in segmentize(boundary, 100).coords:
        d = region.distance(ShapelyPoint(x, y))
        if d > TOLERANCE and (worst is None or d > worst[0]):
            worst = (d, (x, y))
    return worst


GROUP_NAMES = {"column": "Column", "wall": "Wall", "beam": "Beam", "slab": "Slab"}


def part_check_counts(found: dict[str, Any]) -> dict[str, Any]:
    """The floor plan's checks (``checks.json``, ``saengine.pipeline.status``) from
    :func:`encroachments`: each member outside the plot or in its setbacks fails."""
    warnings = found.get("warnings") or []
    return {
        "problems": 0,
        "failed": len(warnings),
        "items": [
            {"severity": "warning", "message": w["message"], "where": w["id"]} for w in warnings
        ],
    }


def encroachments(
    site: Site | None, floor_plan_text: str | None, objects_text: str | None
) -> dict[str, Any]:
    """The floor plan's columns, walls, beams and slab edges outside the plot or inside the
    setbacks: ``{plot, envelope, warnings [{story, group, id, kind ("outside"|"setback"),
    amount mm, side ("front"|"rear"|"side"|null), message}], problems}``. ``plot`` and
    ``envelope`` are open rings in project mm (null without a plot), for the floor plan's
    underlay."""
    from saengine.library.floorplan import FloorPlan

    ring, problem = plot_ring(site)
    out: dict[str, Any] = {
        "plot": None,
        "envelope": None,
        "warnings": [],
        "problems": [problem] if problem else [],
    }
    if ring is None or site is None:
        return out
    polygon = _polygon(ring)
    if not polygon.is_valid:
        out["problems"].append("The plot's sides cross each other: the members are not checked.")
        return out
    distances = setbacks(site, ring)
    kinds = side_kinds(ring, site.plot.road if site.plot else None)
    buildable = envelope(ring, distances)
    out["plot"] = [[round(x, 1), round(y, 1)] for x, y in ring]
    out["envelope"] = _open_ring(buildable) if buildable is not None else None
    if not floor_plan_text:
        return out
    try:
        plan = FloorPlan.model_validate_json(floor_plan_text)
    except ValidationError:
        out["problems"].append("The floor plan has errors: the members are not checked.")
        return out
    types: dict[str, dict[str, Any]] = {}
    try:
        for entry in (json.loads(objects_text) if objects_text else {}).get("objects", []):
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                types[entry["id"]] = entry
    except (ValueError, AttributeError):
        pass
    from shapely import segmentize
    from shapely.geometry import LineString
    from shapely.geometry import Point as ShapelyPoint

    sides = [LineString([ring[i], ring[(i + 1) % len(ring)]]) for i in range(len(ring))]
    for group, member_id, story, shape in _members(plan, types):
        name = f"{GROUP_NAMES[group]} {member_id}"
        outside = _worst(shape, polygon)
        if outside is not None:
            amount = outside[0]
            out["warnings"].append(
                {
                    "story": story,
                    "group": group,
                    "id": member_id,
                    "kind": "outside",
                    "amount": round(amount, 1),
                    "side": None,
                    "message": f"{name}: {amount / 1e3:.2f} m outside the plot.",
                }
            )
            continue
        # How far into a setback: the most any point of the member is nearer a side than that
        # side's setback.
        depth, nearest = 0.0, 0
        for x, y in segmentize(
            shape.exterior if shape.geom_type == "Polygon" else shape, 100
        ).coords:
            point = ShapelyPoint(x, y)
            for i, side_line in enumerate(sides):
                into = distances[i] - side_line.distance(point)
                if into > depth:
                    depth, nearest = into, i
        if depth <= TOLERANCE:
            continue
        kind = kinds[nearest] or "side"
        out["warnings"].append(
            {
                "story": story,
                "group": group,
                "id": member_id,
                "kind": "setback",
                "amount": round(depth, 1),
                "side": kind,
                "message": f"{name}: {depth / 1e3:.2f} m into the {kind} setback "
                f"({distances[nearest] / 1e3:.2f} m).",
            }
        )
    return out

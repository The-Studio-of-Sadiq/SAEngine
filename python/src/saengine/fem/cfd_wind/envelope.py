"""The building's envelope for the CFD wind tunnel (alpha 9 L3).

Each storey is a prism from the level below (the base for the first) up to its level, with that
level's plan outline, as the code's own wind takes each storey's face from its level's extent
(:func:`saengine.fem.loads.wind_levels`):

- the outline of a level is the union of the BIM slabs at it (adjacent slabs merged across gaps
  up to 50 mm); a level without slabs takes the convex hull of the columns and walls of the
  storey below it, else of the analysis model's nodes at it, else it has no outline (the storey
  takes no wind, with a note);
- a courtyard (a hole in an outline) is filled: the CFD sees its outer faces only (a note);
- storeys of the same outline are joined into one prism (a "tier"), so the surface has fewer
  internal faces; each tier is a closed surface, the tiers overlap slightly so snappyHexMesh
  sees one body, and the first tier reaches below the ground so it cuts the ground cleanly.

Coordinates: the model's, in metres (BIM lengths are mm). The CFD case of wind direction θ (the
direction the wind blows to, counter-clockwise from +X) turns the building by -θ about the
centre of its plan's bounding box, so the wind always blows along the case's +x.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

MM = 0.001
#: Slabs closer than this are one outline [m].
JOIN_GAP = 0.05
#: Outline parts smaller than this are dropped [m²].
MIN_AREA = 1.0
#: How far an upper tier reaches into the one below it [m] (one body for snappyHexMesh).
TIER_OVERLAP = 0.01

Point = tuple[float, float]
Polygon = tuple[Point, ...]


@dataclass(frozen=True)
class Tier:
    """A prism of the envelope: ``outline`` (counter-clockwise, model plan [m]) from ``bottom``
    to ``top`` [m above the base]."""

    bottom: float
    top: float
    outline: Polygon


@dataclass(frozen=True)
class Envelope:
    """The envelope: the ground (``base``, absolute [m]), the levels above it (absolute [m]),
    each level's outline parts (counter-clockwise polygons, model plan [m]) and notes."""

    base: float
    levels: tuple[float, ...]
    outlines: tuple[tuple[Polygon, ...], ...]
    notes: tuple[str, ...] = field(default=())

    @property
    def height(self) -> float:
        """H: the top level above the base [m]."""
        return self.levels[-1] - self.base if self.levels else 0.0

    @property
    def relative_levels(self) -> list[float]:
        """The levels above the base [m]."""
        return [z - self.base for z in self.levels]

    def points(self) -> list[Point]:
        return [p for parts in self.outlines for poly in parts for p in poly]

    @property
    def centre(self) -> Point:
        """The centre of the plan's bounding box (the turning point of the cases) [m]."""
        pts = self.points()
        if not pts:
            return (0.0, 0.0)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)

    def tiers(self) -> list[Tier]:
        """The prisms: consecutive storeys of the same outline part joined."""
        rel = self.relative_levels
        out: list[Tier] = []
        open_: dict[Polygon, float] = {}  # outline part -> bottom of its running tier
        for i, parts in enumerate(self.outlines):
            bottom = 0.0 if i == 0 else rel[i - 1]
            now = set(parts)
            for part in list(open_):
                if part not in now:
                    out.append(Tier(open_.pop(part), bottom, part))
            for part in parts:
                open_.setdefault(part, bottom)
        top = rel[-1] if rel else 0.0
        out += [Tier(bottom, top, part) for part, bottom in open_.items()]
        return sorted(out, key=lambda t: (t.bottom, t.top))

    def stamp(self) -> str:
        """A short hash of the geometry, to tell results of another envelope."""
        data = {
            "base": round(self.base, 3),
            "levels": [round(z, 3) for z in self.levels],
            "outlines": [
                [[(round(x, 3), round(y, 3)) for x, y in poly] for poly in parts]
                for parts in self.outlines
            ],
        }
        text = json.dumps(data, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def to_json(self) -> dict[str, Any]:
        return {
            "base_m": self.base,
            "levels_m": list(self.levels),
            "outlines": [[[list(p) for p in poly] for poly in parts] for parts in self.outlines],
            "notes": list(self.notes),
            "stamp": self.stamp(),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Envelope:
        return cls(
            base=float(data["base_m"]),
            levels=tuple(float(z) for z in data["levels_m"]),
            outlines=tuple(
                tuple(tuple((float(x), float(y)) for x, y in poly) for poly in parts)
                for parts in data["outlines"]
            ),
            notes=tuple(str(n) for n in data.get("notes") or ()),
        )


# ───────────────────────────────────────── outlines ─────────────────────────────────────────


def _ccw(points: Sequence[Point]) -> Polygon:
    """``points`` as a counter-clockwise polygon without its repeated last point, rounded to
    the millimetre."""
    pts = [(round(float(x), 3), round(float(y), 3)) for x, y in points]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    clean: list[Point] = []
    for p in pts:
        if not clean or p != clean[-1]:
            clean.append(p)
    if len(clean) > 1 and clean[0] == clean[-1]:
        clean.pop()
    if signed_area(clean) < 0:
        clean.reverse()
    return tuple(clean)


def signed_area(points: Sequence[Point]) -> float:
    """The shoelace area of ``points`` [m²], positive counter-clockwise."""
    n = len(points)
    return 0.5 * sum(
        points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1]
        for i in range(n)
    )


def union_outline(polygons: Iterable[Sequence[Point]]) -> tuple[tuple[Polygon, ...], bool]:
    """The outline parts of the union of ``polygons`` (gaps up to :data:`JOIN_GAP` closed,
    parts under :data:`MIN_AREA` dropped) and whether a hole was filled."""
    from shapely.geometry import Polygon as ShapelyPolygon
    from shapely.ops import unary_union

    shapes = []
    for poly in polygons:
        if len(poly) < 3:
            continue
        shape = ShapelyPolygon(poly)
        if not shape.is_valid:
            shape = shape.buffer(0)
        if not shape.is_empty and shape.area > 0:
            shapes.append(shape)
    if not shapes:
        return (), False
    merged = (
        unary_union(shapes).buffer(JOIN_GAP / 2, join_style=2).buffer(-JOIN_GAP / 2, join_style=2)
    )
    merged = merged.simplify(0.005)
    geoms = list(getattr(merged, "geoms", [merged]))
    parts: list[Polygon] = []
    holes = False
    for g in geoms:
        if g.is_empty or g.geom_type != "Polygon" or g.area < MIN_AREA:
            continue
        holes = holes or bool(list(g.interiors))
        part = _ccw(list(g.exterior.coords))
        if len(part) >= 3:
            parts.append(part)
    parts.sort(key=lambda p: (min(x for x, _ in p), min(y for _, y in p)))
    return tuple(parts), holes


def convex_hull(points: Iterable[Point]) -> Polygon:
    """The convex hull of ``points`` (counter-clockwise; empty for fewer than three distinct
    points or a line)."""
    pts = sorted({(round(float(x), 3), round(float(y), 3)) for x, y in points})
    if len(pts) < 3:
        return ()

    def cross(o: Point, a: Point, b: Point) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Point] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[Point] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = tuple(lower[:-1] + upper[:-1])
    return hull if len(hull) >= 3 and abs(signed_area(hull)) >= MIN_AREA else ()


def envelope_from_building(
    building: Any, nodes: Sequence[Sequence[float]] | None = None
) -> Envelope:
    """The envelope of a :class:`saengine.library.bim.BuildingModel` (see the module notes);
    ``nodes``: the analysis model's node coordinates [m] for levels with neither slabs nor
    columns and walls. Raises ValueError when the building has no level above its base."""
    elevations = sorted({float(s.elevation) * MM for s in building.stories})
    if len(elevations) < 2:
        raise ValueError("the building model has no story above its base")
    base, levels = elevations[0], elevations[1:]
    slabs: dict[int, list[list[Point]]] = {i: [] for i in range(len(levels))}
    for element in building.elements:
        if getattr(element, "kind", None) != "slab":
            continue
        z = float(element.elevation) * MM
        i = min(range(len(elevations)), key=lambda k: abs(elevations[k] - z))
        if i == 0:  # the slab on the ground
            continue
        slabs[i - 1].append([(float(x) * MM, float(y) * MM) for x, y in element.boundary])
    outlines: list[tuple[Polygon, ...]] = []
    notes: list[str] = []
    filled: list[str] = []
    for i, z in enumerate(levels):
        below = elevations[i]
        parts, holes = union_outline(slabs[i])
        if holes:
            filled.append(f"{z:g} m")
        if not parts:
            hull = convex_hull(_storey_points(building, below, z))
            if not hull and nodes is not None:
                hull = convex_hull((n[0], n[1]) for n in nodes if abs(float(n[2]) - z) < 1e-3)
            if hull:
                parts = (hull,)
                notes.append(
                    f"the level at {z:g} m has no slab: its outline is the convex hull of its "
                    "columns and walls (or of the analysis model's nodes)"
                )
            else:
                notes.append(
                    f"the level at {z:g} m has no slab, column or wall outline: its storey "
                    "takes no wind in the CFD"
                )
        outlines.append(parts)
    if filled:
        notes.append(
            "courtyards are filled (the CFD sees the outer faces only) at the levels "
            + ", ".join(filled)
        )
    if not any(outlines):
        raise ValueError("the building model has no slab, column or wall to make its envelope of")
    return Envelope(base, tuple(levels), tuple(outlines), tuple(notes))


def _storey_points(building: Any, below: float, level: float) -> list[Point]:
    """The plan points of the columns and walls of the storey from ``below`` up to ``level``
    [m]."""
    out: list[Point] = []
    for element in building.elements:
        kind = getattr(element, "kind", None)
        if kind not in ("column", "wall"):
            continue
        bottom, top = float(element.bottom) * MM, float(element.top) * MM
        if top < level - 1e-3 or bottom > below + 1e-3:
            continue
        if kind == "column":
            out.append((float(element.position[0]) * MM, float(element.position[1]) * MM))
        else:
            out.append((float(element.start[0]) * MM, float(element.start[1]) * MM))
            out.append((float(element.end[0]) * MM, float(element.end[1]) * MM))
    return out


# ───────────────────────────────────────── surface (STL) ─────────────────────────────────────────


def to_case(point: Point, centre: Point, angle: float) -> Point:
    """A model plan point in the case of wind direction ``angle`` [°]: about ``centre``,
    turned by -angle."""
    a = math.radians(angle)
    dx, dy = point[0] - centre[0], point[1] - centre[1]
    return (dx * math.cos(a) + dy * math.sin(a), -dx * math.sin(a) + dy * math.cos(a))


def to_model(vector: Sequence[float], angle: float) -> tuple[float, float]:
    """A plan vector of the case of direction ``angle`` [°] in the model's axes (turned by
    +angle)."""
    a = math.radians(angle)
    return (
        vector[0] * math.cos(a) - vector[1] * math.sin(a),
        vector[0] * math.sin(a) + vector[1] * math.cos(a),
    )


def triangulate(polygon: Sequence[Point]) -> list[tuple[int, int, int]]:
    """Ear clipping of a simple counter-clockwise polygon: index triples, counter-clockwise."""
    n = len(polygon)
    if n < 3:
        return []
    index = list(range(n))
    out: list[tuple[int, int, int]] = []

    def cross(a: Point, b: Point, c: Point) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def inside(p: Point, a: Point, b: Point, c: Point) -> bool:
        return cross(a, b, p) >= 0 and cross(b, c, p) >= 0 and cross(c, a, p) >= 0

    guard = 0
    while len(index) > 3 and guard < 10 * n * n:
        guard += 1
        m = len(index)
        clipped = False
        for k in range(m):
            i0, i1, i2 = index[k - 1], index[k], index[(k + 1) % m]
            a, b, c = polygon[i0], polygon[i1], polygon[i2]
            turn = cross(a, b, c)
            if turn <= 1e-12:
                if abs(turn) <= 1e-12:  # collinear: drop the middle point
                    index.pop(k)
                    clipped = True
                    break
                continue
            if any(
                inside(polygon[j], a, b, c)
                for j in index
                if j not in (i0, i1, i2) and polygon[j] not in (a, b, c)
            ):
                continue
            out.append((i0, i1, i2))
            index.pop(k)
            clipped = True
            break
        if not clipped:  # not simple: fan the rest
            break
    if len(index) >= 3:
        out += [(index[0], index[j], index[j + 1]) for j in range(1, len(index) - 1)]
    return out


def _facet(a: Sequence[float], b: Sequence[float], c: Sequence[float]) -> str:
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
    size = math.sqrt(sum(x * x for x in n)) or 1.0
    n = [x / size for x in n]
    return (
        f"  facet normal {n[0]:.6g} {n[1]:.6g} {n[2]:.6g}\n    outer loop\n"
        + "".join(f"      vertex {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n" for p in (a, b, c))
        + "    endloop\n  endfacet\n"
    )


def prism_facets(outline: Sequence[Point], bottom: float, top: float) -> list[str]:
    """The facets of a closed prism, normals outward: the walls, the top and the bottom."""
    out: list[str] = []
    n = len(outline)
    for i in range(n):
        (x0, y0), (x1, y1) = outline[i], outline[(i + 1) % n]
        a, b = (x0, y0, bottom), (x1, y1, bottom)
        c, d = (x1, y1, top), (x0, y0, top)
        out.append(_facet(a, b, c))
        out.append(_facet(a, c, d))
    for i, j, k in triangulate(outline):
        p, q, r = outline[i], outline[j], outline[k]
        out.append(_facet((*p, top), (*q, top), (*r, top)))
        out.append(_facet((*p, bottom), (*r, bottom), (*q, bottom)))
    return out


def stl_text(envelope: Envelope, angle: float, below: float) -> str:
    """The envelope as one ASCII STL solid ``building`` in the case of wind direction ``angle``
    (turned about the plan's centre, z from the base); the first tier reaches ``below`` metres
    under the ground."""
    centre = envelope.centre
    facets: list[str] = []
    for tier in envelope.tiers():
        outline = _ccw([to_case(p, centre, angle) for p in tier.outline])
        bottom = -below if tier.bottom <= 0 else tier.bottom - TIER_OVERLAP
        facets += prism_facets(outline, bottom, tier.top)
    return "solid building\n" + "".join(facets) + "endsolid building\n"


def case_extent(envelope: Envelope, angle: float) -> tuple[float, float, float, float]:
    """(x0, x1, y0, y1): the envelope's plan extent in the case of direction ``angle`` [m]."""
    centre = envelope.centre
    pts = [to_case(p, centre, angle) for p in envelope.points()]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), max(xs), min(ys), max(ys))


def surface_area(envelope: Envelope) -> float:
    """The envelope's walls and roofs [m²] (the mesh estimate)."""
    total = 0.0
    for tier in envelope.tiers():
        n = len(tier.outline)
        perimeter = sum(math.dist(tier.outline[i], tier.outline[(i + 1) % n]) for i in range(n))
        total += perimeter * (tier.top - tier.bottom) + abs(signed_area(tier.outline))
    return total

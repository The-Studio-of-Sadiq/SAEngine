"""Slab loads on their supporting beams: tributary areas and the load shapes they give.

A slab panel that hands its loads to its edges (beams or walls, not a plate in the analysis
model) gives each edge the load of its tributary area, as a distributed load that varies along
the edge: triangles and trapezoids for a rectangle, other linearly varying shapes for other
outlines. The resultant and its position are those of the tributary area, so the beam moments
are those of the real shape: for a short-edge triangle of total W on a simple span the midspan
moment is W·L/6 (W·L/8 for the uniform load of the same total, 25 % low) and the fixed-end
moment of a fixed-fixed span 5·w·L²/96 with w the peak (5·W·L/48, against W·L/12).

Tributary areas (BNBC 2020 Part 6 Sec 6.5.6.8.1 and Figure 6.6.21, p. 955: "tributary areas
which are bounded by 45° lines drawn from the corners of the panels"):

* two-way panels: the bisector (45° for right-angled corners) split of the panel, i.e. its
  straight skeleton: every point goes to the edge its "roof" slopes down to.

  - convex panels (rectangles, trapezoids, triangles, any convex outline): exactly, as the
    intersection of half-planes {d_e(p) <= d_f(p)} (d the distance to an edge's line);
  - orthogonal non-convex panels (L, T, U shapes): the straight skeleton of an orthogonal
    polygon is its L-infinity medial axis, so each point goes to the edge nearest in the
    L-infinity metric (ties at a re-entrant corner to the edge whose line is farther, as the
    wavefront of the re-entrant corner moves along its 45° bisector); evaluated on a fine grid
    of cells clipped to the outline, so the total is exact and the shape is resolved to the
    cell size;
  - other non-convex panels: each point to its nearest edge (Euclidean medial axis, the same
    tie-break), on the same grid; the result says so in its notes.

* one-way panels (``system == "oneWay"``, or a convex panel whose long-to-short ratio exceeds
  the two-way limit): the panel spans its short way; each strip across it gives half to each
  of the two edges it ends on (exact for convex panels). Edges along the span carry nothing. A
  non-convex one-way panel is shared by the two-way rule (noted).

Collinear consecutive edges (an edge split at a column or a beam joint) are one side for the
split; the side's load shape is then cut back into the edges.

A part of a tributary area that lies beyond the end of its edge (beside an obtuse corner) goes
to that end as a point load (``EdgeProfile.end_loads``).

The analysis model applies a shape on a beam split into members by its mesh: each member takes
the mean intensity of the shape over it as a uniform load and a pair of opposite nodal forces at
its ends (:func:`segment_loads`), together statically equivalent to the shape on it (same
resultant and the same moment). OpenSeesPy 3.8 (the bundled analysis) takes ``eleLoad
-beamUniform Wy Wz Wx aL bL`` (a partial uniform load) but ignores the end intensities of the
linearly varying form (``WyB WzB WxB``), checked on ``elasticBeamColumn``; hence the split.

Units: whatever the caller uses (m and N/m² in :mod:`saengine.fem.derive`); intensities come out
as pressure × length.
"""

from __future__ import annotations

import functools
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from saengine.codes import context as code_context
from saengine.fem.end_zones import RIGID_SHARE_LIMIT

#: Relative tolerance of collinearity and of breakpoints.
_EPS = 1e-9
#: Stations of a load shape closer than this fraction of the side are merged.
BREAK_TOL = 1e-6
#: Grid cells across the smaller extent of a non-convex panel (the resolution of its shape).
GRID_CELLS = 40
#: Times a sampling cell on a boundary between tributary areas is split in four.
REFINE = 4
#: Bins of a sampled edge shape, in grid cells (smooths the staircase of the cells).
BIN_CELLS = 2
#: Shift of the sampling grid, in cells (odd fractions: no cell centre on a 45° line).
GRID_SHIFT = (0.3183, 0.1416)


@dataclass(frozen=True)
class Piece:
    """A linearly varying load from station ``s0`` to ``s1`` (along the edge from its start),
    intensity ``q0`` at ``s0`` and ``q1`` at ``s1``."""

    s0: float
    s1: float
    q0: float
    q1: float

    @property
    def length(self) -> float:
        return self.s1 - self.s0

    @property
    def total(self) -> float:
        return (self.q0 + self.q1) / 2 * self.length

    def at(self, s: float) -> float:
        if self.length <= 0:
            return self.q0
        return self.q0 + (self.q1 - self.q0) * (s - self.s0) / self.length

    def clip(self, a: float, b: float) -> Piece | None:
        lo, hi = max(a, self.s0), min(b, self.s1)
        if hi <= lo:
            return None
        return Piece(lo, hi, self.at(lo), self.at(hi))

    def moment(self, about: float) -> float:
        """∫ q(s)·(s - about) ds over the piece."""
        return self.length**2 * (self.q0 + 2 * self.q1) / 6 + self.total * (self.s0 - about)


@dataclass(frozen=True)
class EdgeProfile:
    """The load of slab edge ``index`` (from corner i to i + 1), ``length`` long: distributed
    ``pieces`` and point loads ``end_loads`` at its start and its end."""

    index: int
    length: float
    pieces: tuple[Piece, ...] = ()
    end_loads: tuple[float, float] = (0.0, 0.0)

    @property
    def total(self) -> float:
        return sum(p.total for p in self.pieces) + sum(self.end_loads)

    @property
    def load(self) -> float:
        """The mean intensity of the distributed part (the uniform load of the same total that
        :func:`saengine.fem.loads.slab_edge_loads` used to give)."""
        distributed = sum(p.total for p in self.pieces)
        return distributed / self.length if self.length else 0.0

    def at(self, s: float) -> float:
        """The intensity at station ``s`` (the larger one at a step)."""
        values = [p.at(s) for p in self.pieces if p.s0 - _EPS <= s <= p.s1 + _EPS]
        return max(values) if values else 0.0

    def resultant(self, s0: float, s1: float) -> tuple[float, float]:
        """(total, moment about ``s0``) of the distributed load between stations s0 and s1."""
        total = moment = 0.0
        for piece in self.pieces:
            part = piece.clip(s0, s1)
            if part is not None:
                total += part.total
                moment += part.moment(s0)
        return total, moment

    def reactions(self, s0: float, s1: float) -> tuple[float, float]:
        """The simple-span reactions at s0 and s1 of the distributed load between them."""
        total, moment = self.resultant(s0, s1)
        span = s1 - s0
        if span <= 0:
            return total / 2, total / 2
        return total - moment / span, moment / span


def segment_loads(profile: EdgeProfile, s0: float, s1: float) -> tuple[float, float, float]:
    """The loads of a member from station ``s0`` to ``s1`` of an edge: (uniform intensity w over
    it, nodal force at s0, nodal force at s1), in the sense of the load.

    w is the mean intensity of the shape over the member; the two nodal forces are equal and
    opposite and make up the moment of the shape about the member's middle, so w and the forces
    have the shape's resultant and moment (statically equivalent: the beam's moments at the
    nodes outside the member are those of the shape, and they converge with the mesh inside).
    """
    span = s1 - s0
    r0, r1 = profile.reactions(s0, s1)
    if span <= 0:
        return 0.0, r0, r1
    total = r0 + r1
    return total / span, r0 - total / 2, r1 - total / 2


@dataclass
class SlabLoadShape:
    """The load shapes of a slab's edges (one per edge, in order) and how they were found."""

    edges: list[EdgeProfile]
    method: str
    notes: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(e.total for e in self.edges)


@dataclass(frozen=True)
class _Side:
    """Collinear consecutive edges: start ``a``, unit direction ``u``, ``length`` and the
    (edge index, start station, length) of its edges."""

    a: np.ndarray
    u: np.ndarray
    length: float
    edges: tuple[tuple[int, float, float], ...]

    def normal(self, orientation: float) -> np.ndarray:
        """Unit normal into the panel (``orientation`` +1 counter-clockwise, -1 clockwise)."""
        return orientation * np.array([-self.u[1], self.u[0]])


#: Relative tolerance of the one-way test: a panel drawn at exactly the limit (2 : 1) whose
#: extents carry rounding noise (mm to m, shapely's rotated rectangle) stays two-way.
ASPECT_TOLERANCE = 1e-6


def two_way_limit() -> float:
    """The long-to-short (centre-to-centre) span ratio above which a panel spans one way: the
    code pack's ``slabCoefficients`` ``twoWayLimits.maxSpanRatio``, the table the slab design
    (:mod:`saengine.design.slab`) uses, so loads and design split panels alike.

    BNBC 2020 does not state a one-way threshold as such; its two-way methods are limited to
    ratios of not more than 2: the coefficient method for slabs on beams, Part 6 Sec 6.5.8.2.2
    (p. 961), "a longer to shorter centre to centre support span ratio of not greater than 2"
    (and the Direct Design Method, Sec 6.5.6.1.2, p. 951). Beyond it a panel is taken as one-way,
    the long-standing practice. A pack without that table gives 2 (the rule SAEngine used
    before code packs)."""
    pack = code_context.current()
    if not pack.has("slabCoefficients"):
        return 2.0
    table = pack.table("slabCoefficients")
    if hasattr(table, "model_dump"):
        table = table.model_dump(by_alias=True)
    try:
        return float(table["twoWayLimits"]["maxSpanRatio"])
    except (KeyError, TypeError):
        return 2.0


def spans_one_way(long_side: float, short_side: float, limit: float) -> bool:
    """True when a panel of these extents is longer than ``limit`` : 1, with a relative
    tolerance (:data:`ASPECT_TOLERANCE`): exactly at the limit is two-way."""
    return long_side > limit * short_side * (1.0 + ASPECT_TOLERANCE)


def slab_load_shapes(
    corners: Sequence[Sequence[float]],
    pressure: float,
    system: str = "twoWay",
    aspect_limit: float | None = None,
) -> SlabLoadShape:
    """The load shapes on the edges of a slab outline carrying ``pressure`` on its area.

    ``corners``: the outline (either orientation, not closed); ``system``: the slab type's
    system ("oneWay", "twoWay", "flat"); ``aspect_limit``: the long-to-short ratio above which a
    convex panel spans one way (by default :func:`two_way_limit`). Edge i goes from corner i to
    corner i + 1; the totals add up to the area times the pressure.

    The shapes are linear in the pressure: those of a unit pressure are kept per outline (the
    load cases and the typical floors of a building repeat them) and scaled.
    """
    key = tuple((float(c[0]), float(c[1])) for c in corners)
    limit = two_way_limit() if aspect_limit is None else float(aspect_limit)
    if len(key) < 3 or not pressure:
        return _none(key)
    unit = _unit_shapes(key, system, limit)
    return SlabLoadShape(
        [_scaled(edge, pressure) for edge in unit.edges], unit.method, list(unit.notes)
    )


def _none(corners: tuple[tuple[float, float], ...]) -> SlabLoadShape:
    n = len(corners)
    return SlabLoadShape(
        [EdgeProfile(i, math.dist(corners[i], corners[(i + 1) % n])) for i in range(n)], "none"
    )


def _scaled(edge: EdgeProfile, factor: float) -> EdgeProfile:
    return EdgeProfile(
        edge.index,
        edge.length,
        tuple(Piece(p.s0, p.s1, p.q0 * factor, p.q1 * factor) for p in edge.pieces),
        (edge.end_loads[0] * factor, edge.end_loads[1] * factor),
    )


@functools.lru_cache(maxsize=4096)
def _unit_shapes(
    corners: tuple[tuple[float, float], ...], system: str, limit: float
) -> SlabLoadShape:
    """The load shapes of a unit pressure (see :func:`slab_load_shapes`)."""
    pressure = 1.0
    points = [np.array(c) for c in corners]
    n = len(points)
    lengths = [float(np.linalg.norm(points[(i + 1) % n] - points[i])) for i in range(n)]
    empty = [EdgeProfile(i, lengths[i]) for i in range(n)]
    if n < 3:
        return SlabLoadShape(empty, "none")
    polygon = Polygon([tuple(p) for p in points])
    if not polygon.is_valid or polygon.area <= 0:
        return SlabLoadShape(empty, "none", ["the outline is not a simple polygon; no load"])
    orientation = 1.0 if polygon.exterior.is_ccw else -1.0
    sides = _sides(points, lengths)
    if len(sides) < 3:
        return SlabLoadShape(empty, "none", ["the outline is degenerate; no load"])
    convex = math.isclose(polygon.convex_hull.area, polygon.area, rel_tol=1e-9)
    orthogonal = all(abs(s.u[0]) < 1e-9 or abs(s.u[1]) < 1e-9 for s in sides)
    notes: list[str] = []

    span = _span_direction(polygon)
    long_side, short_side = span[1], span[2]
    one_way = system == "oneWay" or (convex and spans_one_way(long_side, short_side, limit))
    if one_way and not convex:
        notes.append(
            "a one-way panel that is not convex: its load is shared by the two-way (45°) rule"
        )
        one_way = False

    side_loads: list[tuple[list[Piece], tuple[float, float]]]
    if one_way:
        method = "oneWay"
        d = span[0]
        regions = _one_way_regions(polygon, sides, d, orientation)
        side_loads = [
            _profile(region, side, d, pressure) if region is not None else ([], (0.0, 0.0))
            for side, region in zip(sides, regions, strict=True)
        ]
    elif convex:
        method = "twoWay"
        regions = _convex_faces(polygon, sides, orientation)
        side_loads = [
            _profile(region, side, side.normal(orientation), pressure)
            for side, region in zip(sides, regions, strict=True)
        ]
    else:
        method = "skeleton" if orthogonal else "medialAxis"
        if not orthogonal:
            notes.append(
                "a non-convex panel with skewed edges: its load goes to the nearest edge "
                "(medial axis), close to but not exactly the 45° rule"
            )
        side_loads = _sampled(polygon, sides, orientation, pressure, orthogonal)

    edges = list(empty)
    for side, (pieces, (start, end)) in zip(sides, side_loads, strict=True):
        last = len(side.edges) - 1
        for k, (index, offset, length) in enumerate(side.edges):
            own = []
            for piece in pieces:
                part = piece.clip(offset, offset + length)
                if part is not None and part.length > _EPS * side.length:
                    own.append(Piece(part.s0 - offset, part.s1 - offset, part.q0, part.q1))
            edges[index] = EdgeProfile(
                index,
                length,
                tuple(own),
                (start if k == 0 else 0.0, end if k == last else 0.0),
            )
    return SlabLoadShape(edges, method, notes)


# ───────────────────────── geometry ─────────────────────────


def _sides(points: list[np.ndarray], lengths: list[float]) -> list[_Side]:
    """Merge collinear consecutive edges (and drop zero-length ones) into sides."""
    n = len(points)
    scale = max(lengths)
    real = [i for i in range(n) if lengths[i] > _EPS * scale]
    if not real:
        return []

    def direction(i: int) -> np.ndarray:
        return (points[(i + 1) % n] - points[i]) / lengths[i]

    def continues(i: int, j: int) -> bool:
        """Edge j goes straight on from edge i."""
        ui, uj = direction(i), direction(j)
        return abs(ui[0] * uj[1] - ui[1] * uj[0]) < 1e-9 and float(ui @ uj) > 0

    # Start at an edge that does not continue the previous one (so no side wraps round).
    start = 0
    for k, i in enumerate(real):
        if not continues(real[k - 1], i):
            start = k
            break
    order = real[start:] + real[:start]
    groups: list[list[int]] = []
    for i in order:
        if groups and continues(groups[-1][-1], i):
            groups[-1].append(i)
        else:
            groups.append([i])
    sides = []
    for group in groups:
        a = points[group[0]]
        offset = 0.0
        edges = []
        for i in group:
            edges.append((i, offset, lengths[i]))
            offset += lengths[i]
        sides.append(_Side(a, direction(group[0]), offset, tuple(edges)))
    return sides


def _span_direction(polygon: Polygon) -> tuple[np.ndarray, float, float]:
    """(unit direction of the short span, long extent, short extent) of the panel, from its
    minimum rotated rectangle (the panel's own sides for a rectangle)."""
    rectangle = polygon.minimum_rotated_rectangle
    xy = np.array(rectangle.exterior.coords[:4])
    e0, e1 = xy[1] - xy[0], xy[2] - xy[1]
    l0, l1 = float(np.linalg.norm(e0)), float(np.linalg.norm(e1))
    if l0 <= l1:
        return e0 / l0, l1, l0
    return e1 / l1, l0, l1


def _half_plane(origin: np.ndarray, inward: np.ndarray, size: float) -> Polygon:
    """The half-plane {p: (p - origin)·inward >= 0}, cut to a square ``size`` across."""
    along = np.array([-inward[1], inward[0]])
    a, b = origin - along * size, origin + along * size
    return Polygon([tuple(a), tuple(b), tuple(b + inward * size), tuple(a + inward * size)])


def _convex_faces(polygon: Polygon, sides: list[_Side], orientation: float) -> list[BaseGeometry]:
    """The straight-skeleton faces of a convex panel: side e takes the points nearer its line
    than any other side's line (d_e <= d_f: a half-plane through their bisector)."""
    minx, miny, maxx, maxy = polygon.bounds
    size = 4 * max(maxx - minx, maxy - miny)
    centre = np.array(polygon.centroid.coords[0])
    faces = []
    for e, side in enumerate(sides):
        face: BaseGeometry = polygon
        ne = side.normal(orientation)
        for f, other in enumerate(sides):
            if f == e:
                continue
            nf = other.normal(orientation)
            # d_f(p) - d_e(p) = (nf - ne)·p - (nf·af - ne·ae) >= 0
            g = nf - ne
            norm = float(np.linalg.norm(g))
            if norm < 1e-12:
                continue  # parallel and the same way: cannot happen in a convex outline
            c = float(nf @ other.a - ne @ side.a)
            # The bisector g·p = c, from the foot of the panel's centroid on it (not from the
            # coordinate origin: a panel far from it would fall outside the cut square).
            t = (float(g @ centre) - c) / norm**2
            origin = centre - g * t
            reach = size + abs(t) * norm
            face = face.intersection(_half_plane(origin, g / norm, reach))
            if face.is_empty:
                break
        faces.append(face)
    return faces


def _one_way_regions(
    polygon: Polygon, sides: list[_Side], d: np.ndarray, orientation: float
) -> list[BaseGeometry | None]:
    """A convex panel spanning along ``d``: each strip along d gives its half nearer a side to
    that side; sides along d take nothing."""
    # Coordinates: x across the span, y along it.
    across = np.array([-d[1], d[0]])
    xy = np.array(polygon.exterior.coords[:-1])
    xs = sorted({round(float(p @ across), 12) for p in xy})
    minx, miny, maxx, maxy = polygon.bounds
    size = 4 * max(maxx - minx, maxy - miny)
    # Lines along d are drawn about the panel's centroid (not the coordinate origin).
    mid_d = d * float(np.array(polygon.centroid.coords[0]) @ d)

    def chord(x: float) -> tuple[float, float]:
        line = LineString(
            [tuple(across * x + mid_d - d * size), tuple(across * x + mid_d + d * size)]
        )
        part = polygon.intersection(line)
        coords = np.array(part.coords) if not part.is_empty else np.zeros((0, 2))
        if not len(coords):
            return 0.0, 0.0
        ys = coords @ d
        return float(ys.min()), float(ys.max())

    # The mid-line of the strips: a polyline through the chord midpoints at the corners'
    # stations (evaluated just inside each interval, as the ends of a chord are linear in x).
    mids: list[tuple[float, float]] = []
    for x0, x1 in pairwise(xs):
        width = x1 - x0
        if width <= _EPS * size:
            continue
        a, b = x0 + 1e-7 * width, x1 - 1e-7 * width
        mid_a, mid_b = (sum(chord(a)) / 2, sum(chord(b)) / 2)
        slope = (mid_b - mid_a) / (b - a)
        mids.append((x0, mid_a - slope * (a - x0)))
        mids.append((x1, mid_b + slope * (x1 - b)))
    line = [across * x + d * y for x, y in mids]
    below = Polygon(
        [
            tuple(line[0] - across * size),
            *(tuple(p) for p in line),
            tuple(line[-1] + across * size),
            tuple(line[-1] + across * size - d * size),
            tuple(line[0] - across * size - d * size),
        ]
    )
    lower = polygon.intersection(below)
    upper = polygon.difference(below)
    regions: list[BaseGeometry | None] = []
    for side in sides:
        n = side.normal(orientation)
        facing = float(n @ d)
        if abs(facing) < 1e-9:
            regions.append(None)
            continue
        half = lower if facing > 0 else upper
        xa = float(side.a @ across)
        xb = float((side.a + side.u * side.length) @ across)
        lo, hi = min(xa, xb), max(xa, xb)
        strip = Polygon(
            [
                tuple(across * lo + mid_d - d * size),
                tuple(across * hi + mid_d - d * size),
                tuple(across * hi + mid_d + d * size),
                tuple(across * lo + mid_d + d * size),
            ]
        )
        regions.append(half.intersection(strip))
    return regions


def _profile(
    region: BaseGeometry, side: _Side, d: np.ndarray, pressure: float
) -> tuple[list[Piece], tuple[float, float]]:
    """The load shape on ``side`` of a tributary ``region`` brought to it along ``d``.

    The intensity at station s is the pressure times the chord of the region on the line
    through the side's point at s along d, times |sin| of the angle between d and the side
    (the strip ds of the side gathers an area chord·|sin|·ds). The chord of a polygon on
    parallel lines is linear between the stations of its corners, so the shape is exact.
    Parts beyond the side's ends go to the ends.
    """
    if region is None or region.is_empty or region.area <= 0:
        return [], (0.0, 0.0)
    sin = abs(float(side.u[0] * d[1] - side.u[1] * d[0]))
    if sin < 1e-9:
        return [], (0.0, 0.0)

    def station(p: np.ndarray) -> float:
        # p = a + s·u + t·d  ->  s = cross(p - a, d) / cross(u, d)
        r = p - side.a
        return float((r[0] * d[1] - r[1] * d[0]) / (side.u[0] * d[1] - side.u[1] * d[0]))

    coords = shapely.get_coordinates(region)
    stations = sorted({station(p) for p in coords})
    lo, hi = stations[0], stations[-1]
    size = 4 * (region.length + side.length)

    def chord(s: float) -> float:
        base = side.a + side.u * s
        line = LineString([tuple(base - d * size), tuple(base + d * size)])
        return float(region.intersection(line).length)

    def strip(s0: float, s1: float) -> Polygon:
        p0, p1 = side.a + side.u * s0, side.a + side.u * s1
        return Polygon(
            [tuple(p0 - d * size), tuple(p1 - d * size), tuple(p1 + d * size), tuple(p0 + d * size)]
        )

    start = pressure * region.intersection(strip(lo - 1, 0.0)).area if lo < 0 else 0.0
    end = (
        pressure * region.intersection(strip(side.length, hi + 1)).area if hi > side.length else 0.0
    )
    # Corner stations closer than BREAK_TOL × the side are one (round-off of the clipping).
    breaks: list[float] = []
    for s in sorted({min(max(s, 0.0), side.length) for s in stations} | {0.0, side.length}):
        if breaks and s - breaks[-1] <= BREAK_TOL * side.length:
            if s == side.length:
                breaks[-1] = s
            continue
        breaks.append(s)
    pieces = []
    for s0, s1 in pairwise(breaks):
        width = s1 - s0
        a, b = s0 + 1e-7 * width, s1 - 1e-7 * width
        ca, cb = chord(a), chord(b)
        slope = (cb - ca) / (b - a)
        c0, c1 = ca - slope * (a - s0), cb + slope * (s1 - b)
        q0, q1 = pressure * sin * max(c0, 0.0), pressure * sin * max(c1, 0.0)
        if q0 or q1:
            pieces.append(Piece(s0, s1, q0, q1))
    return _merge(pieces), (start, end)


def _merge(pieces: list[Piece]) -> list[Piece]:
    """Join consecutive pieces that lie on one straight line."""
    out: list[Piece] = []
    for piece in pieces:
        if out:
            last = out[-1]
            joined = math.isclose(last.s1, piece.s0, abs_tol=1e-12) and math.isclose(
                last.q1, piece.q0, rel_tol=1e-9, abs_tol=1e-12
            )
            if joined:
                slope0 = (last.q1 - last.q0) / last.length
                slope1 = (piece.q1 - piece.q0) / piece.length
                scale = max(abs(slope0), abs(slope1), 1e-12)
                if abs(slope0 - slope1) <= 1e-7 * scale:
                    out[-1] = Piece(last.s0, piece.s1, last.q0, piece.q1)
                    continue
        out.append(piece)
    return out


def _sampled(
    polygon: Polygon, sides: list[_Side], orientation: float, pressure: float, linf: bool
) -> list[tuple[list[Piece], tuple[float, float]]]:
    """Non-convex panels: grid cells clipped to the outline (exact areas), each to its nearest
    side (L-infinity for an orthogonal outline: its straight skeleton; else Euclidean), binned
    along the side by the cell centroid's station. A cell whose corners and centre do not all
    go to one side is split in four, down to ``REFINE`` times, so the boundaries between the
    tributary areas are resolved to a fraction of a cell."""
    minx, miny, maxx, maxy = polygon.bounds
    h = min(maxx - minx, maxy - miny) / GRID_CELLS
    # The grid is shifted by odd fractions of a cell so that no cell centre lies on a 45°
    # bisector or a ridge through the corners.
    x0, y0 = minx - GRID_SHIFT[0] * h, miny - GRID_SHIFT[1] * h
    nx, ny = math.ceil((maxx - x0) / h), math.ceil((maxy - y0) / h)
    gx, gy = np.meshgrid(x0 + h * np.arange(nx), y0 + h * np.arange(ny))
    xs, ys = gx.ravel(), gy.ravel()
    keep = shapely.intersects(shapely.box(xs, ys, xs + h, ys + h), polygon)
    xs, ys, size = xs[keep], ys[keep], h

    def owner(points: np.ndarray) -> np.ndarray:
        count = len(sides)
        dist = np.empty((len(points), count))
        line = np.empty((len(points), count))
        for k, side in enumerate(sides):
            r = points - side.a
            along = r @ side.u
            perp = np.abs(r @ side.normal(orientation))
            outside = np.maximum(0.0, np.maximum(-along, along - side.length))
            dist[:, k] = np.maximum(perp, outside) if linf else np.hypot(perp, outside)
            line[:, k] = perp
        best = dist.min(axis=1, keepdims=True)
        # A tie (beside a re-entrant corner) goes to the side whose line is farther.
        tied = dist <= best + 1e-9 * h
        return np.where(tied, line, -np.inf).argmax(axis=1)

    done_x: list[np.ndarray] = []
    done_y: list[np.ndarray] = []
    done_size: list[float] = []
    for level in range(REFINE + 1):
        if not len(xs):
            break
        if level == REFINE:
            done_x.append(xs)
            done_y.append(ys)
            done_size.append(size)
            break
        probes = [(0, 0), (1, 0), (0, 1), (1, 1), (0.5, 0.5)]
        owners = np.stack(
            [owner(np.column_stack([xs + fx * size, ys + fy * size])) for fx, fy in probes]
        )
        uniform = (owners == owners[0]).all(axis=0)
        done_x.append(xs[uniform])
        done_y.append(ys[uniform])
        done_size.append(size)
        mixed_x, mixed_y = xs[~uniform], ys[~uniform]
        size /= 2
        xs = np.concatenate([mixed_x, mixed_x + size, mixed_x, mixed_x + size])
        ys = np.concatenate([mixed_y, mixed_y, mixed_y + size, mixed_y + size])
    pieces_of = [
        shapely.intersection(shapely.box(cx, cy, cx + sz, cy + sz), polygon)
        for cx, cy, sz in zip(done_x, done_y, done_size, strict=True)
    ]
    clipped = np.concatenate(pieces_of)
    areas = shapely.area(clipped)
    keep = areas > 0
    clipped, areas = clipped[keep], areas[keep]
    centres = shapely.get_coordinates(shapely.centroid(clipped))
    owners = owner(centres)
    out = []
    for k, side in enumerate(sides):
        mine = owners == k
        if not mine.any():
            out.append(([], (0.0, 0.0)))
            continue
        cells = clipped[mine]
        s = (centres[mine] - side.a) @ side.u
        # The parts beyond the side's ends, cut exactly (not by the cells' centres).
        far = 4 * (maxx - minx + maxy - miny)
        n = side.normal(orientation)
        b0, b1 = side.a, side.a + side.u * side.length
        before = Polygon(
            [
                tuple(b0 + n * far),
                tuple(b0 - n * far),
                tuple(b0 - n * far - side.u * far),
                tuple(b0 + n * far - side.u * far),
            ]
        )
        after = Polygon(
            [
                tuple(b1 + n * far),
                tuple(b1 - n * far),
                tuple(b1 - n * far + side.u * far),
                tuple(b1 + n * far + side.u * far),
            ]
        )
        start_part = shapely.area(shapely.intersection(cells, before))
        end_part = shapely.area(shapely.intersection(cells, after))
        start = float(start_part.sum()) * pressure
        end = float(end_part.sum()) * pressure
        w = (areas[mine] - start_part - end_part) * pressure
        s = np.clip(s, 0.0, side.length)
        inside = w > 0
        bins = max(1, round(side.length / (BIN_CELLS * h)))
        step = side.length / bins
        index = np.minimum((s[inside] / step).astype(int), bins - 1)
        sums = np.bincount(index, weights=w[inside], minlength=bins)
        pieces = [
            Piece(i * step, (i + 1) * step, float(q), float(q))
            for i, q in enumerate(sums / step)
            if q > 0
        ]
        out.append((pieces, (start, end)))
    return out


def division_points(
    start: Sequence[float],
    end: Sequence[float],
    size: float,
    clear: tuple[float, float] = (0.0, 0.0),
) -> list[tuple[float, ...]]:
    """The points inside the line ``start``-``end`` that cut it into members no longer than
    ``size`` (same units): where a beam carrying a slab's load shape needs nodes.

    ``clear``: the least lengths of the first and the last member (the joint zones at the two
    ends, :func:`joint_clearance`): no cut falls inside them, and the part between them is cut
    into equal members of at most ``size``. A line no longer than ``size``, or than the two
    clearances together, is not cut.

    A beam left as one element takes only the shape's mean (its fixed-end moments those of
    the uniform load, 20 % low for a triangle); cut into members, the mean and the nodal pairs
    of :func:`segment_loads` give each member the resultant and the moment of the shape on it,
    so the fixed-end moments of a triangle or a trapezoid are exact whatever the members'
    lengths (tests/test_fem_slab_load_shapes.py).
    """
    a = np.asarray(start, dtype=float)
    c = np.asarray(end, dtype=float)
    length = float(np.linalg.norm(c - a))
    c0, c1 = max(float(clear[0]), 0.0), max(float(clear[1]), 0.0)
    if size <= 0 or length <= size or c0 + c1 >= length - 1e-9:
        return []
    inner = length - c0 - c1
    count = math.ceil(inner / size - 1e-9)
    stations = [c0 + inner * k / count for k in range(count + 1)]
    # The clearances' own stations are cuts unless they fall on (or within 1e-9 of) an end.
    stations = [t for t in stations if 1e-9 * length < t < length * (1 - 1e-9)]
    return [tuple(float(v) for v in a + (c - a) * (t / length)) for t in stations]


def joint_clearance(reach: float, factor: float) -> float:
    """The least length of a beam's end member at a joint whose support face is ``reach`` from
    the joint (same units), so that its rigid zone (``factor`` × ``reach``, the derivation's
    end offsets) is not capped by :data:`saengine.fem.end_zones.RIGID_SHARE_LIMIT` of the
    member's length; with 1 % to spare. 0 without a zone."""
    rigid = max(float(reach), 0.0) * max(float(factor), 0.0)
    return rigid / RIGID_SHARE_LIMIT * 1.01 if rigid > 0 else 0.0


def tributary_regions(
    corners: Sequence[Sequence[float]], system: str = "twoWay", aspect_limit: float | None = None
) -> dict[int, BaseGeometry]:
    """The tributary areas of a convex panel's sides by the first edge of each side (for
    drawings and the report); non-convex panels are sampled, so they give none."""
    points = [np.array([float(c[0]), float(c[1])]) for c in corners]
    n = len(points)
    lengths = [float(np.linalg.norm(points[(i + 1) % n] - points[i])) for i in range(n)]
    polygon = Polygon([tuple(p) for p in points])
    if n < 3 or not polygon.is_valid or polygon.area <= 0:
        return {}
    if not math.isclose(polygon.convex_hull.area, polygon.area, rel_tol=1e-9):
        return {}
    orientation = 1.0 if polygon.exterior.is_ccw else -1.0
    sides = _sides(points, lengths)
    d, long_side, short_side = _span_direction(polygon)
    limit = two_way_limit() if aspect_limit is None else aspect_limit
    if system == "oneWay" or spans_one_way(long_side, short_side, limit):
        regions = _one_way_regions(polygon, sides, d, orientation)
    else:
        regions = list(_convex_faces(polygon, sides, orientation))
    return {
        side.edges[0][0]: region
        for side, region in zip(sides, regions, strict=True)
        if region is not None and not region.is_empty
    }


__all__ = [
    "EdgeProfile",
    "Piece",
    "SlabLoadShape",
    "division_points",
    "joint_clearance",
    "segment_loads",
    "slab_load_shapes",
    "spans_one_way",
    "tributary_regions",
    "two_way_limit",
]

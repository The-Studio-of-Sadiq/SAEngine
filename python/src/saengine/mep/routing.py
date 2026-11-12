"""Where services run across the structure in plan: one helper for the HVAC ducts
(:mod:`saengine.hvac.openings`) and the cable trays (:mod:`saengine.electrical.risers`).

A service's horizontal run is a plan path (a polyline, mm). Where it crosses a beam's axis the
beam may need a web opening; the crossing gives the point, the distance along the beam from its
start (the 07 MEP opening's ``position.distance``), the sine of the angle between the run and
the beam (an opening across a beam at an angle is longer along it: w / sin) and the direction
of the run's segment there.

:class:`RoomGraph` lays the horizontal runs out through the rooms of the architecture (their
outlines from :func:`saengine.library.architecture.room_boundary`, by way of
:mod:`saengine.mep.rooms`): corridors, shafts and wet rooms first. The plumbing's branches from
the risers and stacks to the wet rooms use it (:mod:`saengine.plumbing.branches`).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Any

from shapely.geometry import LineString, Point

#: Two crossings closer than this [mm] are one (a path's vertex on a beam's axis touches it
#: from both of its segments).
SAME_POINT = 1.0


def profile_depth(profile: Any) -> float:
    """Overall depth [mm] of a beam's section: ``yDim`` (rectangles), ``overallDepth`` /
    ``depth`` (steel), the diameter of a circle; 0 when unknown."""
    for attribute in ("yDim", "overallDepth", "depth"):
        value = getattr(profile, attribute, None)
        if value:
            return float(value)
    radius = getattr(profile, "radius", None)
    return 2 * float(radius) if radius else 0.0


@dataclass
class BeamLine:
    """A beam's axis in plan with its top elevation and depth [mm]."""

    id: str
    start: tuple[float, float]
    end: tuple[float, float]
    top: float  # elevation of the top [mm]
    depth: float  # [mm], 0 when unknown


@dataclass
class Crossing:
    """Where a plan path crosses a beam's axis."""

    beam: Any
    point: tuple[float, float]
    #: from the beam's start along its axis [mm]
    distance: float
    #: of the angle between the path's segment and the beam (1: square across)
    sine: float
    #: along the path from its start [mm]
    along: float
    #: of the path's segment through the point (not normalised)
    direction: tuple[float, float]


def path_beam_crossings(path: list[Any], beams: list[Any], min_sine: float = 0.0) -> list[Crossing]:
    """Where a plan path (``[[x, y], ...]`` mm) crosses the axes of ``beams`` (anything with
    ``start`` and ``end`` plan points), in the order along the path. A segment at an angle whose
    sine is below ``min_sine`` runs along the beam, not across it, and is left out; a segment
    lying on a beam's axis never crosses it."""
    out: list[Crossing] = []
    walked = 0.0
    for a, b in itertools.pairwise([tuple(p[:2]) for p in path]):
        run = LineString([a, b])
        length = run.length
        if length <= 0:
            continue
        ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        for beam in beams:
            start, end = tuple(beam.start[:2]), tuple(beam.end[:2])
            axis = LineString([start, end])
            if axis.length <= 0:
                continue
            vx = (end[0] - start[0]) / axis.length
            vy = (end[1] - start[1]) / axis.length
            sine = abs(ux * vy - uy * vx)
            if sine < max(min_sine, 1e-9):
                continue
            hit = run.intersection(axis)
            if hit.is_empty or not isinstance(hit, Point):
                continue
            along = walked + run.project(hit)
            if any(c.beam is beam and math.dist(c.point, (hit.x, hit.y)) < SAME_POINT for c in out):
                continue
            out.append(
                Crossing(
                    beam=beam,
                    point=(hit.x, hit.y),
                    distance=math.dist(start, (hit.x, hit.y)),
                    sine=sine,
                    along=along,
                    direction=(b[0] - a[0], b[1] - a[1]),
                )
            )
        walked += length
    out.sort(key=lambda c: c.along)
    return out


def path_length(path: list[Any]) -> float:
    """Length of a plan path [mm]."""
    return sum(math.dist(a[:2], b[:2]) for a, b in itertools.pairwise(path))


# ─────────────────────────────── runs through the rooms ───────────────────────────────

#: Rooms sharing less wall than this [mm] are not joined (they touch at a corner).
MIN_SHARED = 300.0
#: What a run costs per mm through a room: corridors, lobbies, shafts and wet rooms at their
#: length, other rooms (bedrooms, living rooms, offices) at twice it, so runs keep to the
#: circulation and the wet rooms where they can (SAEngine practice).
DRY_ROOM_FACTOR = 2.0


@dataclass
class RoomPlace:
    """A room as a place a run passes through: its outline (the wall centre lines around it,
    so that next rooms share edges) and whether runs prefer it."""

    id: str
    face: Any  # shapely Polygon
    preferred: bool

    @property
    def centre(self) -> tuple[float, float]:
        point = self.face.centroid
        if not self.face.contains(point):
            point = self.face.representative_point()
        return (point.x, point.y)


class RoomGraph:
    """A plan graph of one story's rooms (networkx): a node at each room's centre and at the
    middle of each wall two rooms share, joined through the rooms. :meth:`route` finds the run
    from a point (a riser) to a room along it."""

    def __init__(self, rooms: list[RoomPlace]):
        import networkx as nx

        self.rooms = {r.id: r for r in rooms}
        self.graph = nx.Graph()
        for room in rooms:
            self.graph.add_node(("room", room.id), point=room.centre)
        for a, b in itertools.combinations(rooms, 2):
            if not a.face.intersects(b.face):
                continue
            shared = a.face.boundary.intersection(b.face.boundary)
            if shared.is_empty or shared.length < MIN_SHARED:
                continue
            piece = max(getattr(shared, "geoms", [shared]), key=lambda g: g.length)
            middle = piece.interpolate(0.5, normalized=True)
            node = ("wall", a.id, b.id)
            self.graph.add_node(node, point=(middle.x, middle.y))
            for room in (a, b):
                self._join(("room", room.id), node, room)

    def _cost(self, room: RoomPlace, a: tuple[float, float], b: tuple[float, float]) -> float:
        return math.dist(a, b) * (1.0 if room.preferred else DRY_ROOM_FACTOR)

    def _join(self, u: Any, v: Any, room: RoomPlace) -> None:
        a, b = self.graph.nodes[u]["point"], self.graph.nodes[v]["point"]
        self.graph.add_edge(u, v, weight=self._cost(room, a, b))

    def entry(self, point: tuple[float, float]) -> tuple[RoomPlace, list[tuple[float, float]]]:
        """The room a point enters the graph through (the one it is in, else the nearest) and
        the points from it to that room's centre."""
        from shapely.geometry import Point
        from shapely.ops import nearest_points

        p = Point(point)
        inside = [r for r in self.rooms.values() if r.face.covers(p)]
        if inside:
            room = min(inside, key=lambda r: r.face.area)
            return room, [point, room.centre]
        room = min(self.rooms.values(), key=lambda r: r.face.distance(p))
        edge = nearest_points(room.face, p)[0]
        return room, [point, (edge.x, edge.y), room.centre]

    def route(self, start: tuple[float, float], room_id: str) -> list[tuple[float, float]] | None:
        """The run from ``start`` to the centre of room ``room_id``: plan points [mm], or None
        when the room cannot be reached through the rooms."""
        import networkx as nx

        if room_id not in self.rooms or not self.rooms:
            return None
        room, lead = self.entry(start)
        try:
            nodes = nx.shortest_path(
                self.graph, ("room", room.id), ("room", room_id), weight="weight"
            )
        except nx.NetworkXNoPath:
            return None
        points = [*lead[:-1], *(self.graph.nodes[n]["point"] for n in nodes)]
        out = [points[0]]
        for point in points[1:]:
            if math.dist(point, out[-1]) > SAME_POINT:
                out.append(point)
        return out

    def cost(self, start: tuple[float, float], room_id: str) -> float | None:
        """What :meth:`route` costs (longer through dry rooms), None when it finds none."""
        import networkx as nx

        if room_id not in self.rooms:
            return None
        room, lead = self.entry(start)
        try:
            inner = nx.shortest_path_length(
                self.graph, ("room", room.id), ("room", room_id), weight="weight"
            )
        except nx.NetworkXNoPath:
            return None
        return inner + sum(self._cost(room, a, b) for a, b in itertools.pairwise(lead))

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
    from a point (a riser) to a room along it.

    Optional ``beams`` and ``beam_penalty`` [mm equivalent per beam crossing] penalise segments
    that cross structural beams. ``spine=True`` adds orthogonal corridor spine nodes along
    preferred rooms so multi-room HVAC duct trees branch cleanly without backtracking."""

    def __init__(
        self,
        rooms: list[RoomPlace],
        beams: list[Any] | None = None,
        beam_penalty: float = 0.0,
        *,
        spine: bool = False,
    ):
        import networkx as nx

        self.rooms = {r.id: r for r in rooms}
        self.beams = list(beams) if beams else []
        self.beam_penalty = float(beam_penalty)
        self.spine = bool(spine)
        self.graph = nx.Graph()
        wall_nodes_by_room: dict[str, list[tuple[Any, tuple[float, float]]]] = {
            r.id: [] for r in rooms
        }
        for room in rooms:
            self.graph.add_node(("room", room.id), point=room.centre, room_id=room.id)
        for a, b in itertools.combinations(rooms, 2):
            if not a.face.intersects(b.face):
                continue
            shared = a.face.boundary.intersection(b.face.boundary)
            if shared.is_empty or shared.length < MIN_SHARED:
                continue
            piece = max(getattr(shared, "geoms", [shared]), key=lambda g: g.length)
            middle = piece.interpolate(0.5, normalized=True)
            pt = (middle.x, middle.y)
            node = ("wall", a.id, b.id)
            self.graph.add_node(node, point=pt)
            for room in (a, b):
                wall_nodes_by_room[room.id].append((node, pt))
                if not (self.spine and room.preferred):
                    self._join(("room", room.id), node, room)
        if self.spine:
            self._build_spines(rooms, wall_nodes_by_room)

    def _build_spines(
        self,
        rooms: list[RoomPlace],
        wall_nodes_by_room: dict[str, list[tuple[Any, tuple[float, float]]]],
    ) -> None:
        """For preferred rooms (corridors/lobbies), build orthogonal spine nodes along the
        room's major axis so trunks run straight and branch at right angles to shared walls."""
        for room in rooms:
            if not room.preferred:
                continue
            walls = wall_nodes_by_room.get(room.id) or []
            if len(walls) < 2:
                for node, _ in walls:
                    self._join(("room", room.id), node, room)
                continue
            minx, miny, maxx, maxy = room.face.bounds
            cx, cy = room.centre
            horizontal = (maxx - minx) >= (maxy - miny)
            spine_pts: list[tuple[tuple[float, float], Any]] = []
            for wall_node, wpt in walls:
                proj = (wpt[0], cy) if horizontal else (cx, wpt[1])
                if not room.face.covers(Point(proj)):
                    proj = room.centre
                spine_pts.append((proj, wall_node))
            # Include room centre on the spine and deduplicate close points.
            spine_pts.append((room.centre, None))
            spine_pts.sort(key=lambda item: item[0][0] if horizontal else item[0][1])
            grouped: list[tuple[tuple[float, float], list[Any]]] = []
            for pt, wnode in spine_pts:
                if grouped and math.dist(pt, grouped[-1][0]) < SAME_POINT:
                    if wnode is not None:
                        grouped[-1][1].append(wnode)
                else:
                    grouped.append((pt, [wnode] if wnode is not None else []))
            prev_node = None
            for k, (pt, wnodes) in enumerate(grouped):
                snode = ("spine", room.id, k)
                self.graph.add_node(snode, point=pt, room_id=room.id)
                if math.dist(pt, room.centre) < SAME_POINT:
                    self._join(("room", room.id), snode, room)
                for wnode in wnodes:
                    self._join(snode, wnode, room)
                if prev_node is not None:
                    self._join(prev_node, snode, room)
                prev_node = snode
            if not self.graph.has_edge(("room", room.id), ("spine", room.id, 0)):
                nearest_s = min(
                    (("spine", room.id, k) for k in range(len(grouped))),
                    key=lambda n: math.dist(self.graph.nodes[n]["point"], room.centre),
                )
                self._join(("room", room.id), nearest_s, room)

    def _cost(self, room: RoomPlace, a: tuple[float, float], b: tuple[float, float]) -> float:
        base = math.dist(a, b) * (1.0 if room.preferred else DRY_ROOM_FACTOR)
        if self.beams and self.beam_penalty > 0 and math.dist(a, b) > SAME_POINT:
            crossings = path_beam_crossings([a, b], self.beams, min_sine=0.17)
            base += len(crossings) * self.beam_penalty
        return base

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

    def _entry_node(
        self, start: tuple[float, float]
    ) -> tuple[RoomPlace, Any, list[tuple[float, float]]]:
        """For spine routing: enter the entry room at an orthogonal projection onto its spine
        (if it has one) or its centre."""
        room, lead = self.entry(start)
        if not self.spine:
            return room, ("room", room.id), lead
        spine_nodes = [
            n for n in self.graph.nodes if isinstance(n, tuple) and n[:2] == ("spine", room.id)
        ]
        if not spine_nodes:
            return room, ("room", room.id), lead
        entry_pt = lead[-2] if len(lead) >= 2 else start
        pts = [self.graph.nodes[n]["point"] for n in spine_nodes]
        minx, miny, maxx, maxy = room.face.bounds
        horizontal = (maxx - minx) >= (maxy - miny)
        cy = pts[0][1] if horizontal else pts[0][0]
        proj = (entry_pt[0], cy) if horizontal else (cy, entry_pt[1])
        if room.face.covers(Point(proj)):
            # Insert a temporary or matching spine entry point along the spine.
            for n in spine_nodes:
                if math.dist(self.graph.nodes[n]["point"], proj) < SAME_POINT:
                    pts_lead = (
                        [*lead[:-1], proj] if math.dist(entry_pt, proj) > SAME_POINT else lead[:-1]
                    )
                    return room, n, pts_lead or [start]
            # Project onto nearest spine edge and attach temporarily to a copy? Simpler: pick nearest spine node
            # or add an entry node on the spine segment!
            snode = ("entry", id(self), round(proj[0], 2), round(proj[1], 2))
            if snode not in self.graph:
                self.graph.add_node(snode, point=proj, room_id=room.id)
                ordered = sorted(
                    spine_nodes, key=lambda n: self.graph.nodes[n]["point"][0 if horizontal else 1]
                )
                key_val = proj[0] if horizontal else proj[1]
                left = [
                    n
                    for n in ordered
                    if self.graph.nodes[n]["point"][0 if horizontal else 1] <= key_val
                ]
                right = [
                    n
                    for n in ordered
                    if self.graph.nodes[n]["point"][0 if horizontal else 1] > key_val
                ]
                if left:
                    self._join(left[-1], snode, room)
                if right:
                    self._join(snode, right[0], room)
            pts_lead = (
                [*lead[:-1], proj] if math.dist(entry_pt, proj) > SAME_POINT else [start, proj]
            )
            if math.dist(pts_lead[0], pts_lead[-1]) <= SAME_POINT:
                pts_lead = [pts_lead[0]]
            return room, snode, pts_lead
        nearest = min(spine_nodes, key=lambda n: math.dist(self.graph.nodes[n]["point"], entry_pt))
        return room, nearest, [*lead[:-1], self.graph.nodes[nearest]["point"]]

    def route(self, start: tuple[float, float], room_id: str) -> list[tuple[float, float]] | None:
        """The run from ``start`` to the centre of room ``room_id``: plan points [mm], or None
        when the room cannot be reached through the rooms."""
        import networkx as nx

        if room_id not in self.rooms or not self.rooms:
            return None
        _, entry_node, lead = self._entry_node(start)
        try:
            nodes = nx.shortest_path(self.graph, entry_node, ("room", room_id), weight="weight")
        except nx.NetworkXNoPath:
            return None
        points = [*lead[:-1], *(self.graph.nodes[n]["point"] for n in nodes)]
        out = [points[0]]
        for point in points[1:]:
            if math.dist(point, out[-1]) > SAME_POINT:
                out.append(point)
        return out

    def route_tree(
        self, start: tuple[float, float], room_ids: list[str]
    ) -> dict[str, list[tuple[float, float]]]:
        """Shortest-path tree from ``start`` to every reachable room in ``room_ids``:
        ``{room_id: path_points_mm}`` sharing a single Dijkstra shortest-path tree."""
        import networkx as nx

        if not self.rooms or not room_ids:
            return {}
        _, entry_node, lead = self._entry_node(start)
        _, paths_by_node = nx.single_source_dijkstra(self.graph, entry_node, weight="weight")
        result: dict[str, list[tuple[float, float]]] = {}
        for rid in room_ids:
            target = ("room", rid)
            if rid not in self.rooms or target not in paths_by_node:
                continue
            nodes = paths_by_node[target]
            points = [*lead[:-1], *(self.graph.nodes[n]["point"] for n in nodes)]
            out = [points[0]]
            for point in points[1:]:
                if math.dist(point, out[-1]) > SAME_POINT:
                    out.append(point)
            result[rid] = out
        return result

    def cost(self, start: tuple[float, float], room_id: str) -> float | None:
        """What :meth:`route` costs (longer through dry rooms), None when it finds none."""
        import networkx as nx

        if room_id not in self.rooms:
            return None
        room, entry_node, lead = self._entry_node(start)
        try:
            inner = nx.shortest_path_length(
                self.graph, entry_node, ("room", room_id), weight="weight"
            )
        except nx.NetworkXNoPath:
            return None
        return inner + sum(self._cost(room, a, b) for a, b in itertools.pairwise(lead))

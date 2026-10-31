"""Line and point loads of ``05 Floor Plan/loads.json`` as loads of the analysis model.

:func:`member_loads` turns the engineer's member loads (:mod:`saengine.library.line_loads`) into
loads in the analysis model's units (m, N) on the building model's members: a line load runs
along its beam at the beam's level (the top of the beam, where the frame line is), a point load
sits on its beam or at a column's joint. Loads entered on a typical floor are repeated on the
beam at the same place on every story of the family (:func:`saengine.library.line_loads.
stories_of`).

The derivation (:func:`saengine.fem.derive.derive_fem`) applies them with its own helpers:

- line loads with its ``line_load`` (the beam elements along the line carry them as uniform
  element loads, and their seismic weight follows the case, as for slab loads);
- point loads with :func:`point_shares`: at the node at the point when there is one (the beams
  are split there by :func:`split_points`), else shared between the two nodes on either side by
  the lever rule (statically exact, local moments approximate), with a note.

:func:`apply` does both given derive's helpers, so the wiring in derive is one call.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.fem.end_zones import profile_depth
from saengine.library import line_loads as ll
from saengine.library.bim import BeamElement, BuildingModel, ColumnElement

MM = 0.001  # m per mm
KN = 1000.0  # N per kN
#: Positions closer than this are the same point [m].
_TOLERANCE = 1e-3


@dataclass(frozen=True)
class MemberLineLoad:
    """A uniform load ``load`` (N/m, down) along ``start``-``end`` (m) of beam ``member``."""

    source: str  # the load's id
    member: str
    story: str
    case: str
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    load: float


@dataclass(frozen=True)
class MemberPointLoad:
    """A concentrated load ``force`` (N, down) at ``at`` (m) on ``member``. ``along``: the
    beam's ends (m) for a load on a beam, none at a column's joint."""

    source: str
    member: str
    story: str
    case: str
    at: tuple[float, float, float]
    force: float
    along: tuple[tuple[float, float, float], tuple[float, float, float]] | None = None


@dataclass
class MemberLoadSet:
    lines: list[MemberLineLoad] = field(default_factory=list)
    points: list[MemberPointLoad] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def totals(self) -> dict[str, float]:
        """Total downward load per case [kN]."""
        totals: dict[str, float] = {}
        for line in self.lines:
            length = float(np.linalg.norm(np.subtract(line.end, line.start)))
            totals[line.case] = totals.get(line.case, 0.0) + line.load * length / KN
        for point in self.points:
            totals[point.case] = totals.get(point.case, 0.0) + point.force / KN
        return totals

    def summary(self) -> list[dict[str, Any]]:
        """Total per story and case [kN], for the run log and the report."""
        rows: dict[tuple[str, str], float] = {}
        for line in self.lines:
            length = float(np.linalg.norm(np.subtract(line.end, line.start)))
            key = (line.story, line.case)
            rows[key] = rows.get(key, 0.0) + line.load * length / KN
        for point in self.points:
            key = (point.story, point.case)
            rows[key] = rows.get(key, 0.0) + point.force / KN
        return [
            {"story": story, "case": case, "total_kN": round(total, 3)}
            for (story, case), total in rows.items()
        ]


def _key(xy: Sequence[float]) -> tuple[int, int]:
    return (round(float(xy[0])), round(float(xy[1])))


def member_loads(
    building: BuildingModel, loads: ll.MemberLoads, types: Mapping[str, Any] | None = None
) -> MemberLoadSet:
    """The loads of ``loads`` on the members of ``building``, repeated over typical floors.

    A wall with ``auto`` height (:func:`saengine.library.line_loads.auto_height`) gets the
    height of each beam and story it lands on: the story height above less the depth of the
    beam above (``types``: object id -> object type, for the depths), a parapet on the top
    story."""
    out = MemberLoadSet()
    elevation = {s.id: s.elevation for s in building.stories}
    beams = {e.id: e for e in building.elements if isinstance(e, BeamElement)}
    columns = {e.id: e for e in building.elements if isinstance(e, ColumnElement)}
    beam_at = {
        (frozenset((_key(e.start), _key(e.end))), round(e.elevation)): e for e in beams.values()
    }
    story_at = {round(z): sid for sid, z in elevation.items()}
    levels = sorted(set(elevation.values()))

    def above(z: float) -> float | None:
        return next((level for level in levels if level > z + 1), None)

    def depth(beam: BeamElement) -> float | None:
        kind = types.get(beam.type) if types else None
        profile = getattr(kind, "profile", None)
        return profile_depth(profile) if profile is not None else None

    def wall_on(beam: BeamElement) -> tuple[float | None, float | None]:
        """The story height above ``beam`` (None on the top story) and the depth under it: of
        the beam above, else of ``beam`` itself."""
        top = above(beam.elevation)
        if top is None:
            return None, None
        upper = beam_at.get((frozenset((_key(beam.start), _key(beam.end))), round(top)))
        return top - beam.elevation, (depth(upper) if upper else None) or depth(beam)

    for load in loads.loads:
        own = beams.get(load.member)
        column = columns.get(load.member) if own is None else None
        if load.story not in elevation:
            out.notes.append(f"{load.id}: no story '{load.story}'; not applied")
            continue
        if own is None and (column is None or not isinstance(load, ll.PointLoad)):
            out.notes.append(f"{load.id}: no beam '{load.member}' in the model; not applied")
            continue
        for story in ll.stories_of(load, building.stories):
            z = elevation.get(story)
            if z is None:
                continue
            if own is not None:
                target = (
                    own
                    if story == load.story
                    else beam_at.get((frozenset((_key(own.start), _key(own.end))), round(z)))
                )
                if target is None:
                    out.notes.append(
                        f"{load.id}: no beam at {load.member}'s place on story {story}; "
                        "not applied there"
                    )
                    continue
                start = np.array([*target.start, target.elevation]) * MM
                end = np.array([*target.end, target.elevation]) * MM
                if isinstance(load, ll.LineLoad):
                    height: float | None = None
                    parapet = False
                    if load.wall is not None and load.wall.auto:
                        story_height, under = wall_on(target)
                        height = ll.auto_height(load.wall, story_height, under, wall_on(own)[0])
                        parapet = story_height is None
                        if height is None:
                            out.notes.append(
                                f"{load.id}: no wall on {target.id}, on the top story (skip the roof)"
                            )
                            continue
                    value = ll.line_value(load, loads, height, parapet=parapet)
                    if value:
                        out.lines.append(
                            MemberLineLoad(
                                load.id,
                                target.id,
                                story_at.get(round(target.elevation), story),
                                load.case,
                                tuple(start),
                                tuple(end),
                                value * KN,
                            )
                        )
                    continue
                # The point at the same plan position as on the beam it was entered on.
                length = float(np.linalg.norm(np.subtract(own.end, own.start)))
                distance = min(max(load.distance or 0.0, 0.0), length)
                if (load.distance or 0.0) > length + 1:
                    out.notes.append(
                        f"{load.id}: {load.distance:g} mm is past the end of {own.id} "
                        f"({length:.0f} mm); applied at its end"
                    )
                along = np.subtract(own.end, own.start) / length if length else np.zeros(2)
                xy = np.array(own.start, dtype=float) + along * distance
                at = np.array([*xy, target.elevation]) * MM
                out.points.append(
                    MemberPointLoad(
                        load.id,
                        target.id,
                        story,
                        load.case,
                        tuple(at),
                        load.value * KN,
                        (tuple(start), tuple(end)),
                    )
                )
                continue
            assert column is not None and isinstance(load, ll.PointLoad)
            target_column = next(
                (
                    c
                    for c in columns.values()
                    if _key(c.position) == _key(column.position) and c.bottom < z <= c.top + 1e-6
                ),
                None,
            )
            if target_column is None:
                out.notes.append(
                    f"{load.id}: no column at {load.member}'s place reaching story {story}; "
                    "not applied there"
                )
                continue
            out.points.append(
                MemberPointLoad(
                    load.id,
                    target_column.id,
                    story,
                    load.case,
                    tuple(np.array([*target_column.position, z]) * MM),
                    load.value * KN,
                )
            )
    return out


def split_points(loads: MemberLoadSet) -> dict[str, list[tuple[float, float, float]]]:
    """Beam id -> the points (mm) inside it where point loads sit: the derivation splits the
    beam's frame line there so each has a node. Points at the ends are left out."""
    points: dict[str, list[tuple[float, float, float]]] = {}
    for point in loads.points:
        if point.along is None:
            continue
        a, b = (np.array(p) for p in point.along)
        at = np.array(point.at)
        if min(np.linalg.norm(at - a), np.linalg.norm(at - b)) < _TOLERANCE:
            continue
        mm = tuple(round(float(v) / MM, 3) for v in at)
        if mm not in points.setdefault(point.member, []):
            points[point.member].append(mm)  # type: ignore[arg-type]
    for member, found in points.items():
        a = np.array(next(p.along[0] for p in loads.points if p.member == member and p.along))
        found.sort(key=lambda p: float(np.linalg.norm(np.array(p) * MM - a)))
    return points


def split_line(
    a: Sequence[float], c: Sequence[float], points: Sequence[Sequence[float]]
) -> list[tuple[tuple[float, ...], tuple[float, ...]]]:
    """The segments of the line ``a``-``c`` (mm) cut at ``points`` (mm, on it), in order."""
    a_, c_ = np.asarray(a, dtype=float), np.asarray(c, dtype=float)
    axis = c_ - a_
    length2 = float(axis @ axis)
    cuts = sorted(
        {
            round(float((np.asarray(p, dtype=float) - a_) @ axis) / length2, 9)
            for p in points
            if length2
        }
    )
    stops = [0.0, *[t for t in cuts if 1e-6 < t < 1 - 1e-6], 1.0]
    corners = [tuple(float(v) for v in a_ + t * axis) for t in stops]
    return list(itertools.pairwise(corners))


def _on_segment(point: np.ndarray, a: np.ndarray, b: np.ndarray) -> float | None:
    """Where ``point`` is along ``a``-``b`` (0..1), or None when it is off the segment."""
    axis = b - a
    length2 = float(axis @ axis)
    if not length2:
        return None
    t = float((point - a) @ axis) / length2
    if t < -1e-9 or t > 1 + 1e-9:
        return None
    if float(np.linalg.norm(a + t * axis - point)) > _TOLERANCE:
        return None
    return t


def point_shares(
    point: MemberPointLoad, coords: Mapping[int, Sequence[float]]
) -> tuple[list[tuple[int, float]], bool]:
    """The nodes that take ``point`` and their shares (summing to 1), and whether it is exact:
    the node at the point, else the nearest nodes on the beam either side of it by the lever
    rule. Empty when no node is on the beam (or at the joint)."""
    at = np.asarray(point.at, dtype=float)
    for node_id, xyz in coords.items():
        if float(np.linalg.norm(np.asarray(xyz, dtype=float) - at)) < _TOLERANCE:
            return [(node_id, 1.0)], True
    if point.along is None:
        return [], False
    a, b = (np.asarray(p, dtype=float) for p in point.along)
    t_at = _on_segment(at, a, b)
    if t_at is None:
        return [], False
    on_line = sorted(
        (t, node_id)
        for node_id, xyz in coords.items()
        if (t := _on_segment(np.asarray(xyz, dtype=float), a, b)) is not None
    )
    before = [(t, n) for t, n in on_line if t <= t_at]
    after = [(t, n) for t, n in on_line if t >= t_at]
    if not before or not after:
        return [], False
    (t0, n0), (t1, n1) = before[-1], after[0]
    share = (t_at - t0) / (t1 - t0)
    return [(n0, 1 - share), (n1, share)], False


def apply(
    loads: MemberLoadSet,
    coords: Mapping[int, Sequence[float]],
    line_load: Callable[[str, str, np.ndarray, np.ndarray, float], bool],
    point_load: Callable[[str, int, float, float], None],
) -> list[str]:
    """Applies ``loads`` through the derivation's helpers and returns its notes.

    ``line_load(source, case, p0, p1, load)``: derive's ``line_load`` (N/m, m).
    ``point_load(case, node, force, z)``: a downward nodal force (N) at ``node``, ``z`` the
    level (m), which derive adds to the case and to the node's seismic weight by the case.
    """
    notes = list(loads.notes)
    for line in loads.lines:
        line_load(line.source, line.case, np.array(line.start), np.array(line.end), line.load)
    for point in loads.points:
        shares, exact = point_shares(point, coords)
        if not shares:
            notes.append(f"{point.source}: no node on {point.member} to take it; not applied")
            continue
        if not exact:
            notes.append(
                f"{point.source}: no node at the point on {point.member}; shared between the "
                "nodes either side (its local moment is approximate)"
            )
        for node_id, share in shares:
            point_load(point.case, node_id, point.force * share, point.at[2])
    return notes

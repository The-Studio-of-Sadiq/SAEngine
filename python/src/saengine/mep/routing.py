"""Where services run across the structure in plan: one helper for the HVAC ducts
(:mod:`saengine.hvac.openings`) and the cable trays (:mod:`saengine.electrical.risers`).

A service's horizontal run is a plan path (a polyline, mm). Where it crosses a beam's axis the
beam may need a web opening; the crossing gives the point, the distance along the beam from its
start (the 07 MEP opening's ``position.distance``), the sine of the angle between the run and
the beam (an opening across a beam at an angle is longer along it: w / sin) and the direction
of the run's segment there.
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

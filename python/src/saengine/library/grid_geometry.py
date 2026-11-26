"""The geometry of the floor plan's grid systems: where grid lines run and where they cross.

Every reader of grid points goes through here (the building model, the drawings, exporters and
the feature panels), so skewed, radial and single angled lines work everywhere the orthogonal
grid does. The workbench has the same rules in ``gridGeometry.ts`` for drawing and snapping.

A grid line is either straight (a point and a unit direction, a radial system's rays starting
at the centre) or a circle (a radial system's rings). A grid point names two lines; it is where
they cross:

* two straight lines: their crossing (an error when parallel, or when a ray would be crossed
  behind its centre);
* a straight line and a ring: on a ray, the ring's radius out along it; any other line, the
  crossing nearer the line's first point;
* two rings: not a grid point (they cross twice or never).

Each line also has an *orientation*: the angle [°] of its system's local x axis. A column
placed on a line turns with it (see :meth:`GridGeometry.orientation`).

Units: mm and degrees, anticlockwise from the plan's X axis.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from saengine.library.floorplan import Grids

EPS = 1e-9
#: How far grid lines run past the last crossing line, as drawn [mm] (the floor plan's overrun).
OVERRUN = 1500.0

Point = tuple[float, float]


class GridError(ValueError):
    """A grid point that names an unknown line or two lines that do not cross."""


@dataclass(frozen=True)
class GridAxis:
    """One grid line of any system."""

    label: str
    system: str  # "" for the main grid
    role: Literal["x", "y", "ray", "ring", "line"]
    origin: Point  # a point on a straight line; a ring's centre
    direction: Point = (0.0, 0.0)  # unit, straight lines only
    radius: float = 0.0  # rings only
    orientation: float = 0.0  # [°] the local x axis of its system
    #: Drawn extent: the parameters along a straight line, or the ring's full circle.
    extent: tuple[float, float] = (0.0, 0.0)
    #: Where the label bubbles go on a ring (an angle [°]).
    bubble_angle: float = 0.0

    @property
    def circle(self) -> bool:
        return self.role == "ring"

    def at(self, t: float) -> Point:
        return (self.origin[0] + t * self.direction[0], self.origin[1] + t * self.direction[1])

    def segment(self) -> tuple[Point, Point]:
        """The drawn straight line (from its start, where the first bubble is, to its end)."""
        return self.at(self.extent[0]), self.at(self.extent[1])


def _unit(angle: float) -> Point:
    """The unit vector at ``angle`` [°], exact at multiples of 90° (so the main grid's points
    are its positions exactly, not 3e-13 off)."""
    quarter = angle / 90
    if quarter == round(quarter):
        return ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[round(quarter) % 4]
    a = math.radians(angle)
    return (math.cos(a), math.sin(a))


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """A field of a pydantic model or of its JSON (the features read the JSON)."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _span(values: Iterable[float], fallback: float = 0.0) -> tuple[float, float]:
    values = list(values)
    if not values:
        return fallback - OVERRUN, fallback + OVERRUN
    return min(values) - OVERRUN, max(values) + OVERRUN


def _orthogonal(
    system: str, origin: Point, angle: float, xs: list[Any], ys: list[Any]
) -> list[GridAxis]:
    ex, ey = _unit(angle), _unit(angle + 90)
    xpos = [float(_get(g, "position")) for g in xs]
    ypos = [float(_get(g, "position")) for g in ys]
    out = []
    for g in xs:
        p = float(_get(g, "position"))
        start = (origin[0] + p * ex[0], origin[1] + p * ex[1])
        out.append(GridAxis(str(_get(g, "label")), system, "x", start, ey, 0.0, angle, _span(ypos)))
    for g in ys:
        p = float(_get(g, "position"))
        start = (origin[0] + p * ey[0], origin[1] + p * ey[1])
        out.append(GridAxis(str(_get(g, "label")), system, "y", start, ex, 0.0, angle, _span(xpos)))
    return out


def _largest_gap(angles: list[float], fallback: float) -> float:
    """The middle of the widest angle between neighbouring rays (where ring labels go)."""
    if not angles:
        return fallback
    ordered = sorted(a % 360 for a in angles)
    gaps = [((ordered[(i + 1) % len(ordered)] - a) % 360 or 360, a) for i, a in enumerate(ordered)]
    gap, start = max(gaps)
    return start + gap / 2


def _radial(system: str, origin: Point, angle: float, rays: list[Any], rings: list[Any]) -> list:
    radii = [float(_get(r, "radius")) for r in rings]
    reach = (max(radii) if radii else 0.0) + OVERRUN
    out: list[GridAxis] = []
    angles = [angle + float(_get(r, "angle")) for r in rays]
    for r, a in zip(rays, angles, strict=True):
        out.append(
            GridAxis(str(_get(r, "label")), system, "ray", origin, _unit(a), 0.0, a, (0.0, reach))
        )
    label_at = _largest_gap(angles, angle - 90)
    for r in rings:
        out.append(
            GridAxis(
                str(_get(r, "label")),
                system,
                "ring",
                origin,
                (0.0, 0.0),
                float(_get(r, "radius")),
                angle,
                (0.0, 0.0),
                label_at,
            )
        )
    return out


def _line_ends(g: Any) -> tuple[float, float, float, float]:
    """A single line's two points: its end point, else ``length`` along ``angle``."""
    x0, y0 = float(_get(g, "x1")), float(_get(g, "y1"))
    x2, y2 = _get(g, "x2"), _get(g, "y2")
    if x2 is not None and y2 is not None:
        return x0, y0, float(x2), float(y2)
    a = math.radians(float(_get(g, "angle") or 0.0))
    length = float(_get(g, "length") or 20000.0)
    return x0, y0, x0 + length * math.cos(a), y0 + length * math.sin(a)


def _free(system: str, lines: list[Any]) -> list[GridAxis]:
    out = []
    for g in lines:
        x0, y0, x1, y1 = _line_ends(g)
        length = math.hypot(x1 - x0, y1 - y0)
        if length <= EPS:
            continue
        d = ((x1 - x0) / length, (y1 - y0) / length)
        # Like an X line, whose direction is the local y axis: the local x axis is 90° before it.
        orientation = math.degrees(math.atan2(d[1], d[0])) - 90
        out.append(
            GridAxis(
                str(_get(g, "label")), system, "line", (x0, y0), d, 0.0, orientation, (0.0, length)
            )
        )
    return out


class GridGeometry:
    """The grid lines of a floor plan's ``grids`` (the model or its JSON), by label."""

    def __init__(self, grids: Grids | dict[str, Any] | None) -> None:
        grids = grids if grids is not None else {}
        axes = _orthogonal(
            "", (0.0, 0.0), 0.0, list(_get(grids, "x") or []), list(_get(grids, "y") or [])
        )
        for s in _get(grids, "systems") or []:
            sid, kind = str(_get(s, "id")), _get(s, "kind")
            origin = (float(_get(s, "originX") or 0.0), float(_get(s, "originY") or 0.0))
            angle = float(_get(s, "angle") or 0.0)
            if kind == "orthogonal":
                axes += _orthogonal(
                    sid, origin, angle, list(_get(s, "x") or []), list(_get(s, "y") or [])
                )
            elif kind == "radial":
                axes += _radial(
                    sid, origin, angle, list(_get(s, "rays") or []), list(_get(s, "rings") or [])
                )
            elif kind == "lines":
                axes += _free(sid, list(_get(s, "lines") or []))
        self.axes: list[GridAxis] = axes
        self.by_label: dict[str, GridAxis] = {a.label: a for a in axes}

    @classmethod
    def of_axes(cls, axes: Iterable[GridAxis]) -> GridGeometry:
        """The geometry of grid lines already laid out (as the drawings keep them)."""
        out = cls(None)
        out.axes = list(axes)
        out.by_label = {a.label: a for a in out.axes}
        return out

    @property
    def orthogonal_only(self) -> bool:
        """Only the main grid (the plan as it was before other grid systems)."""
        return all(a.system == "" for a in self.axes)

    def axis(self, label: str, which: str = "X") -> GridAxis:
        try:
            return self.by_label[label]
        except KeyError:
            raise GridError(f"no {which} grid line '{label}'") from None

    def intersection(self, first: str, second: str) -> Point:
        """Where the lines ``first`` and ``second`` cross (a grid point's x and y)."""
        a, b = self.axis(first, "X"), self.axis(second, "Y")
        if a.circle and b.circle:
            raise GridError(f"grid point {first}-{second}: two rings are not a grid point")
        same = a.system == b.system
        if same and (
            (a.role, b.role) in (("y", "x"), ("ring", "ray")) or a.role == b.role != "line"
        ):
            raise GridError(
                f"grid point {first}-{second}: name the "
                + ("ray then the ring" if a.role in ("ray", "ring") else "X line then the Y line")
            )
        if a.circle or b.circle:
            line, ring = (b, a) if a.circle else (a, b)
            return _line_ring(line, ring, f"{first}-{second}")
        cross = a.direction[0] * b.direction[1] - a.direction[1] * b.direction[0]
        if abs(cross) < 1e-9:
            raise GridError(f"grid lines {first} and {second} are parallel")
        wx, wy = b.origin[0] - a.origin[0], b.origin[1] - a.origin[1]
        t = (wx * b.direction[1] - wy * b.direction[0]) / cross
        s = (wx * a.direction[1] - wy * a.direction[0]) / cross
        if (a.role == "ray" and t < -1e-6) or (b.role == "ray" and s < -1e-6):
            raise GridError(f"grid lines {first} and {second} do not cross (behind a ray's centre)")
        return a.at(t)

    def point(self, p: Any) -> Point:
        """A grid point (``{x, y, dx, dy}``, model or JSON) in plan coordinates [mm]."""
        x, y = self.intersection(str(_get(p, "x")), str(_get(p, "y")))
        return x + float(_get(p, "dx", 0) or 0), y + float(_get(p, "dy", 0) or 0)

    def orientation(self, label: str) -> float:
        """The angle [°] a column on line ``label`` turns by: its system's local x axis (0 on the
        main grid, the system's angle on a rotated one, the ray's angle on a radial one)."""
        axis = self.by_label.get(label)
        return axis.orientation if axis else 0.0

    def intersections(self) -> list[tuple[str, str, Point]]:
        """Every crossing of two grid lines inside their drawn extents (for snapping and
        drawings), each pair once in the order a grid point names them."""
        out = []
        for i, a in enumerate(self.axes):
            for b in self.axes[i + 1 :]:
                first, second = (b, a) if _swap(a, b) else (a, b)
                try:
                    p = self.intersection(first.label, second.label)
                except GridError:
                    continue
                if _within(a, p) and _within(b, p):
                    out.append((first.label, second.label, p))
        return out

    def find(self, x: float, y: float, tolerance: float = 50.0) -> tuple[str, str] | None:
        """The grid point (its two labels) at plan ``(x, y)``, or None off the grids."""
        best = None
        for first, second, (px, py) in self.intersections():
            d = math.hypot(px - x, py - y)
            if d <= tolerance and (best is None or d < best[0]):
                best = (d, first, second)
        return (best[1], best[2]) if best else None


def _swap(a: GridAxis, b: GridAxis) -> bool:
    """Whether a grid point names ``b`` first: Y before X and ring before ray are swapped."""
    return a.system == b.system and (a.role, b.role) in (("y", "x"), ("ring", "ray"))


def _within(axis: GridAxis, p: Point) -> bool:
    if axis.circle:
        return True
    t = (p[0] - axis.origin[0]) * axis.direction[0] + (p[1] - axis.origin[1]) * axis.direction[1]
    return axis.extent[0] - 1e-6 <= t <= axis.extent[1] + 1e-6


def _line_ring(line: GridAxis, ring: GridAxis, name: str) -> Point:
    ox, oy = line.origin[0] - ring.origin[0], line.origin[1] - ring.origin[1]
    dx, dy = line.direction
    b = ox * dx + oy * dy
    c = ox * ox + oy * oy - ring.radius**2
    disc = b * b - c
    if disc < -1e-6:
        raise GridError(f"grid point {name}: the line does not reach the ring")
    root = math.sqrt(max(disc, 0.0))
    roots = (-b - root, -b + root)
    if line.role == "ray":
        ahead = [t for t in roots if t >= -1e-6]
        if not ahead:
            raise GridError(f"grid point {name}: the ray does not reach the ring")
        t = min(ahead)
    else:
        t = min(roots, key=abs)
    return line.at(t)

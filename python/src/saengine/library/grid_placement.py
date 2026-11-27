"""A generated building placed in a rotated orthogonal or a radial grid system (#300).

The generator (:mod:`saengine.library.generator`) lays a building out on an orthogonal grid:
X lines at ``u`` and Y lines at ``v`` [mm]. :func:`place_in_system` moves that grid into one
grid system of the floor plan and puts every absolute coordinate (pads, strips, mat outlines,
braces) in the system's frame:

* ``rotated``: the same X and Y lines in an orthogonal system turned by its angle about its
  origin; a point ``(u, v)`` is the system's local ``(x, y)``.
* ``radial``: the X lines become rings (radius ``innerRadius + u``) and the Y lines rays (at
  the ray angles), so a grid point ``{x: B, y: 2}`` becomes ``{x: 2, y: B}`` (ray then ring),
  and a beam between two grid points on an X line is a ring beam (a chord), on a Y line a beam
  along a ray. Points between the grid lines follow the angle linearly between the rays. When
  the bays add up to 360°, the last Y line is the first ray again: the members that would
  repeat those on the first ray are left out.

Members keep their grid points, so the building model, drawings and analysis place them
through :mod:`saengine.library.grid_geometry` (the one geometry helper, which also turns
columns and pads with their ray or system). Units: mm and degrees.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from saengine.library.grid_geometry import system_point

if TYPE_CHECKING:
    from saengine.library.generator import BuildingSpec

#: The id of the generated grid system.
SYSTEM_ID = "G1"
#: Largest angle between the points of a mat outline drawn along a ring [°].
ARC_STEP = 5.0
_TOL = 1e-6


def radial_spacings(inner: float, rings: list[float], bays: list[float]) -> list[float]:
    """The Y spacings [mm] the generator sizes a radial grid's bays with: each bay's arc
    length at the middle ring (between the first and the last ring)."""
    middle = inner + sum(rings) / 2
    return [round(middle * math.radians(b), 1) for b in bays]


def _cumulative(values: list[float]) -> list[float]:
    out = [0.0]
    for v in values:
        out.append(out[-1] + v)
    return out


class _Frame:
    """The map from the generator's ``(u, v)`` to the plan, and a point's local angle."""

    def __init__(self, s: BuildingSpec, ys: list[float]) -> None:
        self.radial = s.gridKind == "radial"
        self.inner = s.innerRadius
        self.angle = s.gridAngle
        self.ys = ys
        self.rays = _cumulative(list(s.rayAngles or [])) if self.radial else []
        self.closed = self.radial and abs(self.rays[-1] - 360.0) < _TOL
        self.system: dict[str, Any] = {
            "id": SYSTEM_ID,
            "kind": "radial" if self.radial else "orthogonal",
            "originX": s.gridOriginX,
            "originY": s.gridOriginY,
            "angle": s.gridAngle,
        }

    def theta(self, v: float) -> float:
        """The angle [°] from the system's 0° at ``v``: linear between the rays (and beyond
        the end rays at the end bays' rates)."""
        ys, rays = self.ys, self.rays
        i = 0
        while i < len(ys) - 2 and v > ys[i + 1]:
            i += 1
        span = ys[i + 1] - ys[i]
        return rays[i] + (v - ys[i]) / span * (rays[i + 1] - rays[i])

    def point(self, u: float, v: float) -> tuple[float, float]:
        if self.radial:
            return system_point(self.system, max(self.inner + u, 0.0), self.theta(v))
        return system_point(self.system, u, v)

    def turn(self, v: float) -> float:
        """How much a footing at ``v`` turns [°]: the system's angle, or its ray's."""
        return self.angle + (self.theta(v) if self.radial else 0.0)

    def offset(self, dx: float, dy: float, v: float) -> tuple[float, float]:
        """A point's offset (along the generator's X and Y) along the plan's X and Y."""
        a = math.radians(self.turn(v))
        c, s = math.cos(a), math.sin(a)
        return dx * c - dy * s, dx * s + dy * c

    def outline(self, points: list[list[float]], closed: bool = True) -> list[list[float]]:
        """A polygon in the plan; on a radial grid its edges along the rings are split so they
        follow the rings."""
        if not self.radial:
            return [_r2(self.point(u, v)) for u, v in points]
        out: list[list[float]] = []
        pairs = list(zip(points, points[1:] + points[:1] if closed else points[1:], strict=True))
        for (u0, v0), (u1, v1) in pairs:
            sweep = abs(self.theta(v1) - self.theta(v0))
            n = max(1, math.ceil(sweep / ARC_STEP))
            for k in range(n):
                t = k / n
                p = _r2(self.point(u0 + t * (u1 - u0), v0 + t * (v1 - v0)))
                if not out or p != out[-1]:
                    out.append(p)
        if not closed:
            out.append(_r2(self.point(*points[-1])))
        return out


def _r2(p: tuple[float, float]) -> list[float]:
    return [round(p[0], 1), round(p[1], 1)]


def _is_ref(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("x"), str) and "y" in value


def _grid_points(value: Any) -> list[dict[str, Any]]:
    """Every grid point in a member (``at``, ``start``, ``end``, a slab's boundary ...)."""
    if _is_ref(value):
        return [value]
    if isinstance(value, dict):
        return [p for v in value.values() for p in _grid_points(v)]
    if isinstance(value, list):
        return [p for v in value for p in _grid_points(v)]
    return []


def place_in_system(result: dict[str, Any], s: BuildingSpec) -> dict[str, Any]:
    """``result`` of :func:`saengine.library.generator.generate_building` with its grid moved
    into a rotated or radial grid system (see the module), changed in place and returned."""
    plan = result["floorPlan"]
    grids = plan["grids"]
    xs = {g["label"]: float(g["position"]) for g in grids["x"]}
    ys_by = {g["label"]: float(g["position"]) for g in grids["y"]}
    ys = sorted(ys_by.values())
    frame = _Frame(s, ys)
    system = frame.system
    y_labels = [g["label"] for g in sorted(grids["y"], key=lambda g: g["position"])]
    closing = y_labels[-1] if frame.closed else None
    if frame.radial:
        system["rays"] = [
            {"label": label, "angle": round(a, 6)}
            for label, a in zip(y_labels, frame.rays, strict=True)
            if label != closing
        ]
        system["rings"] = [
            {"label": g["label"], "radius": round(s.innerRadius + float(g["position"]), 3)}
            for g in grids["x"]
        ]
        system["name"] = "Radial grid"
    else:
        system["x"], system["y"] = grids["x"], grids["y"]
        system["name"] = "Grid"
    plan["grids"] = {"x": [], "y": [], "systems": [*grids.get("systems", []), system]}

    first = y_labels[0]
    if closing:
        _close_the_ring(plan, result.get("substructure") or {}, first, y_labels[1])
    dropped: set[str] = set()
    for key in ("columns", "beams", "walls", "slabs", "footings"):
        kept = []
        for member in plan.get(key) or []:
            points = _grid_points(member)
            if closing and points and all(p["y"] == closing for p in points):
                dropped.add(member["id"])  # repeats a member on the first ray
                continue
            for p in points:
                v = ys_by.get(p["y"], 0.0)
                dx, dy = float(p.get("dx") or 0.0), float(p.get("dy") or 0.0)
                if dx or dy:
                    p["dx"], p["dy"] = (round(c, 1) for c in frame.offset(dx, dy, v))
                if frame.radial:  # ray then ring
                    ray = first if p["y"] == closing else p["y"]
                    p["x"], p["y"] = ray, p["x"]
            kept.append(member)
        if key in plan:
            plan[key] = kept

    v_end = ys[-1]
    sub = result.get("substructure") or {}
    foundations = []
    for f in sub.get("foundations") or []:
        if dropped & set(f.get("columns") or []):
            continue
        if f.get("center") is not None:
            u, v = f["center"]
            f["center"] = _r2(frame.point(u, v))
            f["rotation"] = round(float(f.get("rotation") or 0.0) + frame.turn(v), 6)
        if f.get("path"):  # a strip runs along its path (its rotation is not used)
            f["path"] = [_r2(frame.point(u, w)) for u, w in f["path"]]
        if f.get("outline"):
            if frame.closed:
                f["outline"] = _circle(frame, s.innerRadius + max(xs.values()) + s.matOverhang)
            else:
                f["outline"] = frame.outline(f["outline"])
        foundations.append(f)
    if "foundations" in sub:
        sub["foundations"] = foundations

    members = []
    for m in result.get("bimMembers") or []:
        if closing and abs(m["y1"] - v_end) < _TOL and abs(m["y2"] - v_end) < _TOL:
            continue
        for a, b in (("x1", "y1"), ("x2", "y2")):
            m[a], m[b] = (round(c, 1) for c in frame.point(m[a], m[b]))
        members.append(m)
    if result.get("bimMembers") is not None:
        result["bimMembers"] = members

    counts = (result.get("summary") or {}).get("counts")
    if counts and dropped:
        for key in ("columns", "beams", "walls", "slabs"):
            if key in counts:
                counts[key] = len(plan.get(key) or [])
        counts["foundations"] = len(foundations)
    summary = result.get("summary") or {}
    if dropped and "footingTypes" in summary:
        from saengine.library.generator import footing_sizes

        summary["footingTypes"] = footing_sizes(foundations)
    kind = "radial" if frame.radial else f"rotated {s.gridAngle:g}°"
    result["notes"] = [
        *result.get("notes", []),
        f"The grid is a {kind} grid system ({SYSTEM_ID}); the members were sized on its "
        + (
            "bays as arc lengths at the middle ring, and the ring beams are straight between "
            "the rays."
            if frame.radial
            else "own axes."
        ),
    ]
    if frame.closed and any(f.get("outline") for f in foundations):
        result["notes"].append("The mat covers the whole circle, the middle too.")
    return result


def _close_the_ring(plan: dict[str, Any], sub: dict[str, Any], first: str, second: str) -> None:
    """In a closed circle the first ray has bays on both sides: its columns and pads take the
    sizes of those on the next ray (the generator sized them as edge columns)."""
    columns = plan.get("columns") or []
    by_place = {(c["at"]["x"], c["at"]["y"], c.get("base"), c.get("top")): c for c in columns}
    twins: dict[str, str] = {}
    for c in columns:
        if c["at"]["y"] == first:
            twin = by_place.get((c["at"]["x"], second, c.get("base"), c.get("top")))
            if twin is not None:
                c["type"] = twin["type"]
                twins[c["id"]] = twin["id"]
    holder = {cid: f for f in sub.get("foundations") or [] for cid in f.get("columns") or []}
    for cid, twin in twins.items():
        f, g = holder.get(cid), holder.get(twin)
        if f is not None and g is not None and f is not g and f.get("type") == g.get("type"):
            for key in ("length", "width", "thickness", "note"):
                if key in g:
                    f[key] = g[key]


def _circle(frame: _Frame, radius: float) -> list[list[float]]:
    n = round(360 / ARC_STEP)
    return [_r2(system_point(frame.system, radius, k * ARC_STEP)) for k in range(n)]


__all__ = ["SYSTEM_ID", "place_in_system", "radial_spacings"]

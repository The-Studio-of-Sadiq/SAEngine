"""The sun over the site, shadows and direct sun hours (alpha 9 L11).

- :func:`sun_position`: the sun's azimuth (from true north, clockwise) and elevation at a site
  and a UTC time, by the NOAA solar calculator's equations (Meeus, "Astronomical Algorithms":
  the geometric mean longitude and anomaly, the equation of centre, the apparent longitude, the
  obliquity, the equation of time); no atmospheric refraction (it lifts the sun by about half a
  degree at the horizon). :func:`sun_path` samples a day.
- :func:`to_grid`: the sun's direction in the project grid, whose +Y points ``rotation`` degrees
  clockwise from true north (as the site point of 01 Soil Report places it).
- :class:`Massing`: the obstructions as vertical prisms (the building's storeys, from the slabs
  of the building model, and the neighbouring buildings given), with exact ray casting
  (:meth:`Massing.blocked`): a ray hits a prism through its top or bottom face (a point in its
  outline at that height) or one of its side faces (Möller-Trumbore on their two triangles).
- :func:`shadow_polygons`: the shadow of the massing on the ground at a time (each prism swept
  along the sun's rays: its base, its top and every side face projected, united).
- :func:`sun_hours`: the direct sun hours of points (ground or facade points with their outward
  normals) over a day: steps when the sun is up, the point faces it and nothing blocks the ray.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import numpy as np

EPS = 1e-6


# ─────────────────────────────────── the sun ───────────────────────────────────


def _julian_day(when: datetime) -> float:
    when = when.astimezone(UTC)
    epoch = datetime(2000, 1, 1, 12, tzinfo=UTC)
    return 2451545.0 + (when - epoch).total_seconds() / 86400.0


def sun_position(latitude: float, longitude: float, when: datetime) -> tuple[float, float]:
    """(azimuth from true north clockwise, elevation) in degrees of the sun at ``when`` (an aware
    datetime) seen from (``latitude``, ``longitude``), NOAA / Meeus."""
    jd = _julian_day(when)
    t = (jd - 2451545.0) / 36525.0
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    mr = math.radians(m)
    c = (
        math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t))
        + math.sin(2 * mr) * (0.019993 - 0.000101 * t)
        + math.sin(3 * mr) * 0.000289
    )
    true_long = l0 + c
    omega = math.radians(125.04 - 1934.136 * t)
    apparent = math.radians(true_long - 0.00569 - 0.00478 * math.sin(omega))
    eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    eps = math.radians(eps0 + 0.00256 * math.cos(omega))
    decl = math.asin(math.sin(eps) * math.sin(apparent))
    y = math.tan(eps / 2) ** 2
    l0r = math.radians(l0)
    eot = 4 * math.degrees(
        y * math.sin(2 * l0r)
        - 2 * e * math.sin(mr)
        + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
        - 0.5 * y * y * math.sin(4 * l0r)
        - 1.25 * e * e * math.sin(2 * mr)
    )
    utc = when.astimezone(UTC)
    minutes = utc.hour * 60 + utc.minute + utc.second / 60
    solar = (minutes + eot + 4 * longitude) % 1440
    hour_angle = math.radians(solar / 4 - 180)
    lat = math.radians(latitude)
    cos_zenith = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(
        hour_angle
    )
    zenith = math.acos(max(-1.0, min(1.0, cos_zenith)))
    azimuth = (
        math.degrees(
            math.atan2(
                math.sin(hour_angle),
                math.cos(hour_angle) * math.sin(lat) - math.tan(decl) * math.cos(lat),
            )
        )
        + 180
    ) % 360
    return azimuth, 90 - math.degrees(zenith)


def to_grid(azimuth: float, elevation: float, rotation: float = 0.0) -> np.ndarray:
    """Unit vector towards the sun in the project grid (x, y, z), the grid's +Y ``rotation``
    degrees clockwise from true north."""
    az, el, th = math.radians(azimuth), math.radians(elevation), math.radians(rotation)
    east, north = math.sin(az) * math.cos(el), math.cos(az) * math.cos(el)
    return np.array(
        [
            east * math.cos(th) - north * math.sin(th),
            east * math.sin(th) + north * math.cos(th),
            math.sin(el),
        ]
    )


def local_time(day: date, hour: float, utc_offset: float) -> datetime:
    zone = timezone(timedelta(hours=utc_offset))
    return datetime(day.year, day.month, day.day, tzinfo=zone) + timedelta(hours=hour)


def sun_path(
    latitude: float,
    longitude: float,
    day: date,
    utc_offset: float,
    step_minutes: float = 30,
    rotation: float = 0.0,
) -> list[dict[str, Any]]:
    """The sun every ``step_minutes`` of a day (local clock time): ``[{time, azimuth, elevation,
    direction}]``, ``direction`` towards the sun in the project grid; above the horizon only."""
    out = []
    steps = round(24 * 60 / step_minutes)
    for k in range(steps + 1):
        hour = k * step_minutes / 60
        az, el = sun_position(latitude, longitude, local_time(day, hour, utc_offset))
        if el <= 0:
            continue
        out.append(
            {
                "time": f"{int(hour):02d}:{round((hour % 1) * 60) % 60:02d}",
                "hour": round(hour, 4),
                "azimuth": round(az, 3),
                "elevation": round(el, 3),
                "direction": [round(float(v), 6) for v in to_grid(az, el, rotation)],
            }
        )
    return out


# ─────────────────────────────────── the massing ───────────────────────────────────


@dataclass
class Prism:
    """A vertical prism: a plan polygon (shapely) from ``bottom`` to ``top`` [mm]."""

    outline: Any
    bottom: float
    top: float
    name: str = ""


@dataclass
class Massing:
    prisms: list[Prism] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._sides: np.ndarray | None = None

    def sides(self) -> np.ndarray:
        """The side faces as triangles (K x 3 x 3)."""
        if self._sides is None:
            tris = []
            for prism in self.prisms:
                rings = [prism.outline.exterior, *prism.outline.interiors]
                for ring in rings:
                    coords = list(ring.coords)
                    for (x1, y1), (x2, y2) in itertools.pairwise(coords):
                        a, b = (x1, y1, prism.bottom), (x2, y2, prism.bottom)
                        c, d = (x2, y2, prism.top), (x1, y1, prism.top)
                        tris += [(a, b, c), (a, c, d)]
            self._sides = np.asarray(tris, dtype=float).reshape(-1, 3, 3)
        return self._sides

    def blocked(
        self,
        points: np.ndarray,
        direction: np.ndarray,
        chunk: int = 4096,
        reach: float = math.inf,
    ) -> np.ndarray:
        """Whether the ray from each point (N x 3) along the unit ``direction`` hits the massing
        (within ``reach`` [mm] of the point)."""
        import shapely

        n = len(points)
        hit = np.zeros(n, dtype=bool)
        dz = float(direction[2])
        for prism in self.prisms:
            for z in (prism.top, prism.bottom):
                if abs(dz) < EPS:
                    continue
                t = (z - points[:, 2]) / dz
                ok = (t > EPS) & (t < reach) & ~hit
                if not ok.any():
                    continue
                qx = points[ok, 0] + t[ok] * direction[0]
                qy = points[ok, 1] + t[ok] * direction[1]
                inside = shapely.contains_xy(prism.outline, qx, qy)
                idx = np.flatnonzero(ok)
                hit[idx[inside]] = True
        tris = self.sides()
        if len(tris):
            v0, e1, e2 = tris[:, 0], tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]
            pvec = np.cross(direction, e2)  # K x 3
            det = np.einsum("ij,ij->i", e1, pvec)
            good = np.abs(det) > EPS
            v0, e1, e2, pvec, det = v0[good], e1[good], e2[good], pvec[good], det[good]
            inv = 1.0 / det
            # About 2 million point-triangle pairs at a time (memory).
            chunk = max(1, min(chunk, 2_000_000 // max(len(det), 1)))
            for start in range(0, n, chunk):
                rows = np.arange(start, min(start + chunk, n))
                rows = rows[~hit[rows]]
                if not len(rows):
                    continue
                tvec = points[rows, None, :] - v0[None, :, :]  # R x K x 3
                u = np.einsum("rkj,kj->rk", tvec, pvec) * inv
                qvec = np.cross(tvec, e1[None, :, :])
                v = np.einsum("j,rkj->rk", direction, qvec) * inv
                t = np.einsum("kj,rkj->rk", e2, qvec) * inv
                inside = (u >= -EPS) & (v >= -EPS) & (u + v <= 1 + EPS) & (t > 1.0) & (t < reach)
                hit[rows[inside.any(axis=1)]] = True
        return hit


def building_massing(building: Any) -> list[Prism]:
    """The building's storeys as prisms: under each level with slabs, from the level below to
    it, the union of the slabs' outlines at that level (the floor plate above the storey)."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    stories = sorted(building.stories, key=lambda s: float(s.elevation))
    by_level: dict[float, list[Any]] = {}
    for e in building.elements:
        if getattr(e, "kind", None) == "slab":
            poly = Polygon([(float(p[0]), float(p[1])) for p in e.boundary]).buffer(0)
            if not poly.is_empty:
                by_level.setdefault(round(float(e.elevation), 1), []).append(poly)
    prisms = []
    elevations = [float(s.elevation) for s in stories]
    for z, polys in sorted(by_level.items()):
        below = [e for e in elevations if e < z - 1.0]
        bottom = max(below) if below else min(elevations + [z]) if elevations else 0.0
        if bottom >= z:
            continue
        union = unary_union(polys)
        for part in getattr(union, "geoms", [union]):
            if part.area > 0:
                prisms.append(Prism(part, bottom, z, f"storey below {z / 1000:g} m"))
    return prisms


# ─────────────────────────────────── shadows ───────────────────────────────────


def shadow_polygons(prisms: list[Prism], direction: np.ndarray, ground: float = 0.0) -> Any:
    """The shadow of ``prisms`` on the plane z = ``ground`` with the sun towards ``direction``
    (a shapely geometry, empty when the sun is down)."""
    from shapely import affinity
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    dx, dy, dz = (float(v) for v in direction)
    if dz <= EPS:
        return Polygon()
    parts = []
    for prism in prisms:
        lo, hi = max(prism.bottom, ground), prism.top
        if hi <= ground:
            continue

        def moved(height: float) -> tuple[float, float]:
            return -(height - ground) * dx / dz, -(height - ground) * dy / dz

        bx, by = moved(lo)
        tx, ty = moved(hi)
        base = affinity.translate(prism.outline, bx, by)
        top = affinity.translate(prism.outline, tx, ty)
        parts += [base, top]
        coords = list(prism.outline.exterior.coords)
        for (x1, y1), (x2, y2) in itertools.pairwise(coords):
            quad = Polygon(
                [(x1 + bx, y1 + by), (x2 + bx, y2 + by), (x2 + tx, y2 + ty), (x1 + tx, y1 + ty)]
            ).buffer(0)
            if quad.area > 0:
                parts.append(quad)
    return unary_union(parts) if parts else Polygon()


def rings(geometry: Any) -> list[list[list[float]]]:
    """Exterior rings of a (multi)polygon as point lists [mm], rounded."""
    out = []
    for part in getattr(geometry, "geoms", [geometry]):
        if part.is_empty or part.geom_type != "Polygon":
            continue
        out.append([[round(x, 1), round(y, 1)] for x, y in part.exterior.coords])
    return out


# ─────────────────────────────────── sample points ───────────────────────────────────


def ground_points(
    extent: Any, spacing: float, level: float, footprints: Any = None
) -> tuple[np.ndarray, np.ndarray]:
    """Points on a grid over ``extent`` (shapely polygon) at ``level`` + 1 mm, outside the
    footprints, with upward normals."""
    import shapely

    x0, y0, x1, y1 = extent.bounds
    xs = np.arange(x0 + spacing / 2, x1, spacing)
    ys = np.arange(y0 + spacing / 2, y1, spacing)
    gx, gy = np.meshgrid(xs, ys)
    gx, gy = gx.ravel(), gy.ravel()
    keep = shapely.contains_xy(extent, gx, gy)
    if footprints is not None and not footprints.is_empty:
        keep &= ~shapely.contains_xy(footprints, gx, gy)
    pts = np.column_stack([gx[keep], gy[keep], np.full(int(keep.sum()), level + 1.0)])
    normals = np.tile([0.0, 0.0, 1.0], (len(pts), 1))
    return pts, normals


def facade_points(
    prisms: list[Prism], spacing: float, offset: float = 50.0
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    """Points on the prisms' side faces (every ``spacing`` along each edge, at mid-height of
    each prism), ``offset`` out from the face, their outward normals and labels."""
    from shapely.geometry.polygon import orient

    pts, normals, labels = [], [], []
    for n, prism in enumerate(prisms):
        ring = list(orient(prism.outline, 1.0).exterior.coords)
        z = (prism.bottom + prism.top) / 2
        for k, ((x1, y1), (x2, y2)) in enumerate(itertools.pairwise(ring)):
            length = math.hypot(x2 - x1, y2 - y1)
            if length < 1.0:
                continue
            nx, ny = (y2 - y1) / length, -(x2 - x1) / length  # outward for a CCW ring
            count = max(1, int(length // spacing))
            for j in range(count):
                s = (j + 0.5) / count
                x, y = x1 + s * (x2 - x1), y1 + s * (y2 - y1)
                pts.append((x + offset * nx, y + offset * ny, z))
                normals.append((nx, ny, 0.0))
                labels.append({"prism": n, "edge": k, "at": round(s * length / 1000, 2)})
    return np.asarray(pts, dtype=float).reshape(-1, 3), np.asarray(normals).reshape(-1, 3), labels


def sun_hours(
    massing: Massing,
    points: np.ndarray,
    normals: np.ndarray,
    path: list[dict[str, Any]],
    step_minutes: float,
) -> np.ndarray:
    """Direct sun hours of each point over the sampled ``path`` (each sample stands for
    ``step_minutes``)."""
    hours = np.zeros(len(points))
    for sample in path:
        d = np.asarray(sample["direction"], dtype=float)
        facing = normals @ d > EPS
        if not facing.any():
            continue
        lit = facing.copy()
        idx = np.flatnonzero(facing)
        lit[idx] = ~massing.blocked(points[idx], d)
        hours += lit * (step_minutes / 60.0)
    return hours

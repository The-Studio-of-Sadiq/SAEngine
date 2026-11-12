"""Small plan-geometry helpers of the MEP coordination: footprints, shape functions."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence

import numpy as np
from shapely.geometry import Point, Polygon

ID_LIMIT = 64
"""The longest id the libraries accept (``Id`` in library/materials.py)."""


def bounded_id(base: str, suffix: str = "") -> str:
    """``base + suffix`` as a valid library id (``^[A-Za-z0-9._-]+$``, at most 64 characters).
    Characters outside the set become "-"; a base too long is cut and given a short hash of
    the whole base, so two long bases stay distinct and the suffix is always kept."""
    clean = re.sub(r"[^A-Za-z0-9._-]", "-", base) or "id"
    suffix = re.sub(r"[^A-Za-z0-9._-]", "-", suffix)
    if len(clean) + len(suffix) <= ID_LIMIT:
        return clean + suffix
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    keep = max(ID_LIMIT - len(suffix) - len(digest) - 1, 1)
    return f"{clean[:keep]}-{digest}{suffix}"[-ID_LIMIT:]


def rotated_rectangle(
    cx: float, cy: float, length: float, width: float, rotation: float
) -> list[tuple[float, float]]:
    """Corners (counter-clockwise) of a ``length`` x ``width`` rectangle centred at (cx, cy)
    with its length along ``rotation`` degrees from X."""
    t = math.radians(rotation)
    u = np.array([math.cos(t), math.sin(t)])
    v = np.array([-math.sin(t), math.cos(t)])
    c = np.array([cx, cy])
    return [
        tuple(c + su * length / 2 * u + sv * width / 2 * v)  # type: ignore[misc]
        for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))
    ]


def local_to_global(
    cx: float, cy: float, rotation: float, points: Sequence[Sequence[float]]
) -> list[tuple[float, float]]:
    t = math.radians(rotation)
    c, s = math.cos(t), math.sin(t)
    return [(cx + c * px - s * py, cy + s * px + c * py) for px, py in points]


def footprint_points(
    cx: float, cy: float, length: float, width: float, rotation: float, spacing: float = 100.0
) -> list[tuple[float, float]]:
    """Cell centres of a grid over the footprint (at most ``spacing`` apart, 2 to 40 a side):
    equal shares of a uniform load on them have the load's total and resultant exactly."""
    nu = min(40, max(2, math.ceil(length / spacing)))
    nv = min(40, max(2, math.ceil(width / spacing)))
    local = [
        (-length / 2 + (i + 0.5) * length / nu, -width / 2 + (j + 0.5) * width / nv)
        for i in range(nu)
        for j in range(nv)
    ]
    return local_to_global(cx, cy, rotation, local)


def inside(point: Sequence[float], polygon: Sequence[Sequence[float]], tol: float = 1.0) -> bool:
    """Whether ``point`` is in ``polygon`` (plan, mm) or within ``tol`` of it."""
    shape = Polygon([(p[0], p[1]) for p in polygon])
    return shape.buffer(tol).contains(Point(point[0], point[1]))


def shape_weights(
    point: Sequence[float], corners: Sequence[Sequence[float]], tol: float = 1e-9
) -> list[float] | None:
    """The shape-function values of a plan triangle (linear) or quadrilateral (bilinear) at
    ``point``, or None when the point is outside it. A point load P on the element is P times
    these at its nodes: statically equivalent, and consistent with the element's
    interpolation."""
    p = np.asarray(point[:2], dtype=float)
    xy = np.array([[c[0], c[1]] for c in corners], dtype=float)
    if len(xy) == 3:
        a, b, c = xy
        matrix = np.column_stack([b - a, c - a])
        if abs(np.linalg.det(matrix)) < 1e-12:
            return None
        s, t = np.linalg.solve(matrix, p - a)
        weights = [1 - s - t, s, t]
        return [float(w) for w in weights] if min(weights) >= -tol else None
    if len(xy) != 4:
        return None
    xi = np.zeros(2)
    signs = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], dtype=float)
    for _ in range(30):
        n = 0.25 * (1 + signs[:, 0] * xi[0]) * (1 + signs[:, 1] * xi[1])
        dn_dxi = 0.25 * signs[:, 0] * (1 + signs[:, 1] * xi[1])
        dn_deta = 0.25 * signs[:, 1] * (1 + signs[:, 0] * xi[0])
        residual = n @ xy - p
        jacobian = np.column_stack([dn_dxi @ xy, dn_deta @ xy])
        if abs(np.linalg.det(jacobian)) < 1e-12:
            return None
        step = np.linalg.solve(jacobian, residual)
        xi -= step
        if np.linalg.norm(step) < 1e-12:
            break
    if np.any(np.abs(xi) > 1 + 1e-7):
        return None
    n = 0.25 * (1 + signs[:, 0] * xi[0]) * (1 + signs[:, 1] * xi[1])
    return [float(w) for w in n]


def is_rectangle(corners: Sequence[Sequence[float]], tol: float = 1e-6) -> bool:
    if len(corners) != 4:
        return False
    pts = [np.asarray(c[:2], dtype=float) for c in corners]
    for k in range(4):
        a = pts[k] - pts[k - 1]
        b = pts[(k + 1) % 4] - pts[k]
        if abs(a @ b) > tol * np.linalg.norm(a) * np.linalg.norm(b):
            return False
    return True

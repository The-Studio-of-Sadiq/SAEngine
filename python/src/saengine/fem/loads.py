"""Loads of the analysis model from the project settings (BNBC 2020 Part 6 Chapter 2).

Pure functions: given the building's levels, weights and plan, they return the equivalent
static seismic and wind forces per level and the beam loads of slab areas. The derivation of the
analysis model (:mod:`saengine.fem.derive`) applies them; every formula names its clause, and
:mod:`saengine.library.bnbc` holds the coefficients.

Units: m, kN, s.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

from saengine.library import bnbc

# ───────────────────────── seismic: equivalent static force method ─────────────────────────


def approximate_period(height: float, system: str) -> float:
    """Fundamental period T = Ct·hn^m [s] for a building ``height`` metres tall."""
    ct, m = bnbc.PERIOD_COEFFICIENTS[bnbc.SYSTEM_PERIOD_FAMILY.get(system, "other")]
    return ct * height**m


def normalized_spectrum(period: float, site_class: str) -> float:
    """Normalized acceleration response spectrum Cs(T) for the site class (5 % damping)."""
    s, tb, tc, td = bnbc.SITE_FACTORS[site_class]
    eta = bnbc.DAMPING_ETA
    if period <= tb:
        return s * (1 + period / tb * (2.5 * eta - 1))
    if period <= tc:
        return 2.5 * s * eta
    if period <= td:
        return 2.5 * s * eta * tc / period
    return 2.5 * s * eta * tc * td / period**2


def design_acceleration(
    period: float, site_class: str, z: float, importance: float, r: float
) -> float:
    """Design spectral acceleration Sa = (2/3)·(Z·I/R)·Cs, as a fraction of g."""
    return 2 / 3 * z * importance / r * normalized_spectrum(period, site_class)


def vertical_distribution(
    levels: list[tuple[float, float]], base_shear: float, period: float
) -> list[float]:
    """Lateral force at each level: Fx = V·wx·hx^k / Σ wi·hi^k for (height, weight) levels.

    k = 1 for T ≤ 0.5 s, 2 for T ≥ 2.5 s, linear in between.
    """
    k = 1.0 if period <= 0.5 else 2.0 if period >= 2.5 else 1 + (period - 0.5) / 2
    weights = [w * h**k for h, w in levels]
    total = sum(weights)
    return [base_shear * w / total if total else 0.0 for w in weights]


# ───────────────────────── wind: main wind-force resisting system ─────────────────────────


def exposure_coefficient(height: float, exposure: str) -> float:
    """Velocity pressure exposure coefficient Kz at ``height`` metres (Table 6.2.11)."""
    alpha, zg = bnbc.EXPOSURE_PROFILES[exposure]
    return 2.01 * (max(height, 4.57) / zg) ** (2 / alpha)


def velocity_pressure(height: float, speed: float, exposure: str, importance: float) -> float:
    """qz = 0.000613·Kz·Kzt·Kd·V²·I [kN/m²], V in m/s."""
    return (
        0.000613
        * exposure_coefficient(height, exposure)
        * bnbc.WIND_KZT
        * bnbc.WIND_KD
        * speed**2
        * importance
    )


def leeward_coefficient(aspect: float) -> float:
    """Leeward wall Cp for a plan aspect L/B (depth along the wind over width across it)."""
    points = bnbc.WIND_CP_LEEWARD
    if aspect <= points[0][0]:
        return points[0][1]
    for (a0, c0), (a1, c1) in pairwise(points):
        if aspect <= a1:
            return c0 + (c1 - c0) * (aspect - a0) / (a1 - a0)
    return points[-1][1]


def wind_level_forces(
    heights: list[float], width: float, depth: float, speed: float, exposure: str, importance: float
) -> list[float]:
    """Wind force at each level [kN] for wind across a building ``width`` wide and ``depth`` deep.

    Windward pressure qz·G·Cp varies with height; leeward suction qh·G·Cp uses the roof height.
    Each level takes the wall area from halfway down to the level below to halfway up to the one
    above (the roof level the half below it).
    """
    if not heights:
        return []
    roof = heights[-1]
    leeward = (
        velocity_pressure(roof, speed, exposure, importance)
        * bnbc.WIND_GUST
        * leeward_coefficient(depth / width)
    )
    forces = []
    for i, z in enumerate(heights):
        below = z - (z - (heights[i - 1] if i else 0.0)) / 2
        above = z + ((heights[i + 1] - z) / 2 if i + 1 < len(heights) else 0.0)
        windward = (
            velocity_pressure(z, speed, exposure, importance)
            * bnbc.WIND_GUST
            * bnbc.WIND_CP_WINDWARD
        )
        forces.append((windward - leeward) * width * (above - below))
    return forces


# ───────────────────────── slab areas to beams ─────────────────────────


@dataclass(frozen=True)
class EdgeLoad:
    """A uniform line load [kN/m] on edge ``index`` of a slab outline (from corner i to i+1)."""

    index: int
    load: float


def slab_edge_loads(
    corners: list[tuple[float, float]], pressure: float, system: str
) -> list[EdgeLoad]:
    """Uniform line loads on a slab's edges carrying ``pressure`` [kN/m²] on its area.

    Rectangles follow the yield-line (45°) rule: two-way slabs give the short edges triangles of
    w·lx²/4 and the long edges trapezoids of w·lx·(2ly - lx)/4; one-way slabs (or two-way with
    ly/lx > 2) carry everything to the long edges. Each is applied as the uniform load of the same
    total. Other outlines share the load among their edges in proportion to their length.
    """
    n = len(corners)
    lengths = [math.dist(corners[i], corners[(i + 1) % n]) for i in range(n)]
    area = (
        abs(
            sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1]))
        )
        / 2
    )
    if n == 4 and _is_rectangle(corners):
        lx, ly = min(lengths[0], lengths[1]), max(lengths[0], lengths[1])
        one_way = system == "oneWay" or ly / lx > 2
        loads = []
        for i, length in enumerate(lengths):
            long_edge = math.isclose(length, ly) and not math.isclose(lx, ly)
            if one_way:
                total = pressure * lx * ly / 2 if long_edge else 0.0
            elif long_edge:
                total = pressure * lx * (2 * ly - lx) / 4
            else:
                total = pressure * lx**2 / 4
            loads.append(EdgeLoad(i, total / length))
        return loads
    perimeter = sum(lengths)
    return [EdgeLoad(i, pressure * area / perimeter) for i in range(n)]


def _is_rectangle(corners: list[tuple[float, float]]) -> bool:
    (ax, ay), (bx, by), (cx, cy), (dx, dy) = corners

    def dot(u: tuple[float, float], v: tuple[float, float]) -> float:
        return u[0] * v[0] + u[1] * v[1]

    edges = [(bx - ax, by - ay), (cx - bx, cy - by), (dx - cx, dy - cy), (ax - dx, ay - dy)]
    scale = max(math.hypot(*e) for e in edges)
    return all(abs(dot(edges[i], edges[(i + 1) % 4])) <= 1e-6 * scale**2 for i in range(4))

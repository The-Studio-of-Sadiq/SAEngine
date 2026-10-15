"""Design checks of isolated and combined spread footings (Part 9 substructure, first subset).

Footings are not part of the analysis model: the columns end at fixed supports. Each footing of
the building model collects the columns whose base lies inside its plan outline and takes their
support reactions, case by case, as the loads its columns put on it (the reactions reversed,
in the footing's local axes ``u`` along its length and ``v`` along its width). A horizontal
reaction acts at the column base, so about the footing's underside it adds a moment of H times
the depth from the column base down to the underside.

Two load levels, as is usual for spread footings (ACI 318-19 13.2.6.1, 13.3.1.1):

- Bearing under the SERVICE (unfactored) allowable-stress combinations of BNBC 2020 Part 6
  2.7.2 (ASCE 7-05 2.4.1), which match this project's nominal (service-level) wind:
  D, D + L + Lr, D + W, D + 0.75L + 0.75Lr + 0.75W, 0.6D + W, D + 0.7E,
  D + 0.75L + 0.75Lr + 0.525E and 0.6D + 0.7E, wind and earthquake in ±X and ±Y, D standing
  for the dead and superimposed dead cases. When the project's strength combinations treat
  wind as strength-level (no wind factor above 1.0), the ASCE 7-16 2.4.1 factors 0.6W and
  0.45W are used instead. The gross pressure includes the footing's weight and the soil above
  it; the net pressure (gross minus the overburden γ Df the excavation removed, Df from the
  ground level to the underside) is compared with the net allowable bearing pressure qa of
  the soil report.
- Strength under the project's FACTORED combinations: the soil pressure under the column
  loads plus the factored weight of the footing and of the soil above it (the dead-load factor
  of the combination), and that weight acting down on the footing. While the whole base is in
  contact, this is the usual net factored pressure; in partial contact, the uplifted part
  hangs from the rest and hogs. Then one-way shear, punching shear and flexure of the footing
  as ACI 318-19 Chapter 13 sends them to Chapters 22 and 7.

Soil pressure is linear (``q = P/A ± M/S``) while the resultant stays inside the kern; beyond
it the base is in partial contact: ``qmax = 2P / (3 B (L/2 - e))`` for an eccentricity in one
direction, and for both directions the exact no-tension plane ``q = max(0, a + b u + c v)`` in
equilibrium with the resultant, solved by Newton's method with the integrals over the
contact polygon computed exactly.

Units: mm, N, N·mm and MPa inside; reported in kN, kN·m/m, kPa, mm²/m.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np

from saengine.design.check import _check
from saengine.design.rc import PHI_SHEAR, STEEL_E, beta1, phi_axial_flexure
from saengine.library.bim import BuildingModel, ColumnElement, FootingElement
from saengine.library.materials import Category, MaterialLibrary
from saengine.library.objects import (
    BarMesh,
    CircleProfile,
    Column,
    Footing,
    ObjectLibrary,
    RectangleProfile,
)
from saengine.library.settings import Foundation, ProjectSettings

G = 9.80665

FOOTING_METHOD = [
    (
        "Footings (isolated and combined): the support reactions of the columns standing on "
        "them, reversed, in the footing's axes; a horizontal reaction adds H times the depth "
        "from the column base to the footing's underside. Columns: rectangles as drawn, "
        "circles as the square of the same area (ACI R13.2.7.1)."
    ),
    (
        "Bearing under the allowable-stress combinations of BNBC 2020 Part 6 2.7.2 "
        "(ASCE 7-05 2.4.1) for nominal wind: D, D + L + Lr, D + W, "
        "D + 0.75L + 0.75Lr + 0.75W, 0.6D + W, D + 0.7E, D + 0.75L + 0.75Lr + 0.525E, "
        "0.6D + 0.7E; W and E in ±X and ±Y (with strength-level wind, ASCE 7-16 2.4.1: "
        "0.6W and 0.45W). Gross pressure q = P/A ± Mx/Sx ± My/Sy with the footing's weight "
        "and the soil above it inside the kern; beyond it partial contact, "
        "qmax = 2P / (3 B (L/2 - e)) for one eccentricity and the exact no-tension plane for "
        "two. The net pressure (gross minus γ Df, Df from the ground level to the underside) "
        "is compared with the net allowable bearing pressure qa. Sliding and overturning are "
        "not checked."
    ),
    (
        "Footing strength under the factored combinations: soil pressure under the column "
        "loads and the factored weight of the footing and the soil above it, that weight "
        "acting down (the net factored pressure while the whole base is in contact). One-way "
        "shear at d from the column faces (ACI 13.2.7.2, Vc = 0.66 λs ρw^(1/3) √f'c b d <= "
        "0.42 √f'c b d, Table 22.5.5.1, ρw of the bottom mesh), punching at d/2 around each "
        "column (ACI 22.6.5.2: least of 0.33, 0.17 (1 + 2/β) and 0.083 (2 + αs d / b0) times "
        "λs √f'c, φ = 0.75) with γv Mu c / Jc for the column base moments about both axes "
        "(ACI 8.4.4.2.3; Jc of the full rectangle also for edge and corner sections), flexure "
        "at the column faces (ACI 13.2.7.1) against the bottom mesh, and top flexure where the "
        "footing hogs (between the columns of a combined footing, or where the weight of the "
        "footing and the soil exceeds the soil pressure) against the top mesh, or as plain "
        "concrete without one (ACI 14.5.2.1, h - 50 mm per 14.5.1.7). The "
        "footing is a beam in each direction under the soil pressure, its weight and the "
        "column loads spread over the column widths; isolated footings over their full width. "
        "Combined footings across their length: a transverse strip of width c + d under each "
        "column carrying that column's load (ACI 336.2R practice), for flexure and one-way "
        "shear. λs (22.5.5.1.3) is applied although ACI 13.2.6.2 permits neglecting it for "
        "footings. d = thickness - cover - bar diameter. Minimum reinforcement 0.0018 Ag "
        "(ACI 7.6.1.1). Development lengths are not checked."
    ),
]


# ─────────────────────────────────────── soil pressure ───────────────────────────────────────


def _clip(
    u0: float, u1: float, v0: float, v1: float, a: float, gu: float, gv: float
) -> list[tuple[float, float]]:
    """The rectangle [u0, u1] x [v0, v1] cut to where ``a + gu u + gv v >= 0``: a convex polygon
    counter-clockwise (Sutherland-Hodgman against one half-plane)."""
    corners = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
    values = [a + gu * u + gv * v for u, v in corners]
    polygon: list[tuple[float, float]] = []
    for k, (p, q) in enumerate(zip(corners, values, strict=True)):
        nxt, qn = corners[(k + 1) % 4], values[(k + 1) % 4]
        if q >= 0:
            polygon.append(p)
        if (q >= 0) != (qn >= 0):
            t = q / (q - qn)
            polygon.append((p[0] + t * (nxt[0] - p[0]), p[1] + t * (nxt[1] - p[1])))
    return polygon


def _polygon_moments(polygon: list[tuple[float, float]]) -> tuple[float, ...]:
    """∫1, ∫u, ∫v, ∫u², ∫uv, ∫v² over a simple counter-clockwise polygon (Green's theorem)."""
    area = su = sv = suu = suv = svv = 0.0
    count = len(polygon)
    if count < 3:
        return (0.0,) * 6
    for k in range(count):
        x0, y0 = polygon[k]
        x1, y1 = polygon[(k + 1) % count]
        cross = x0 * y1 - x1 * y0
        area += cross
        su += (x0 + x1) * cross
        sv += (y0 + y1) * cross
        suu += (x0 * x0 + x0 * x1 + x1 * x1) * cross
        svv += (y0 * y0 + y0 * y1 + y1 * y1) * cross
        suv += (x0 * y1 + 2 * x0 * y0 + 2 * x1 * y1 + x1 * y0) * cross
    return (area / 2, su / 6, sv / 6, suu / 12, suv / 24, svv / 12)


def _plane_integrals(
    a: float, gu: float, gv: float, clip: bool, u0: float, u1: float, v0: float, v1: float
) -> tuple[float, float, float]:
    """∫q, ∫q u, ∫q v over [u0, u1] x [v0, v1] for q = a + gu u + gv v (cut off at zero when
    ``clip``); exact. Computed about the rectangle's centre for accuracy."""
    if u1 <= u0 or v1 <= v0:
        return (0.0, 0.0, 0.0)
    uc, vc = (u0 + u1) / 2, (v0 + v1) / 2
    hu, hv = (u1 - u0) / 2, (v1 - v0) / 2
    local = a + gu * uc + gv * vc
    if clip:
        polygon = _clip(-hu, hu, -hv, hv, local, gu, gv)
    else:
        polygon = [(-hu, -hv), (hu, -hv), (hu, hv), (-hu, hv)]
    area, su, sv, suu, suv, svv = _polygon_moments(polygon)
    force = local * area + gu * su + gv * sv
    fu = local * su + gu * suu + gv * suv
    fv = local * sv + gu * suv + gv * svv
    return (force, fu + uc * force, fv + vc * force)


@dataclass(frozen=True)
class SoilPressure:
    """Soil pressure under a rectangular ``length`` (u) x ``width`` (v) base:
    ``q(u, v) = a + gu u + gv v`` [MPa, u and v in mm from the centroid], cut off at zero
    (``clip``) in partial contact."""

    total: float  # N, the resultant
    eu: float  # mm, eccentricity along u
    ev: float
    a: float
    gu: float
    gv: float
    clip: bool
    state: str  # "kern", "partial" (beyond the kern), "unstable" (outside the base), "uplift"
    qmax: float  # MPa
    qmin: float  # MPa (0 in partial contact)
    contact: float  # share of the base in contact (1 inside the kern)

    def at(self, u: float, v: float) -> float:
        q = self.a + self.gu * u + self.gv * v
        return max(q, 0.0) if self.clip else q

    def integrals(self, u0: float, u1: float, v0: float, v1: float) -> tuple[float, float, float]:
        """The force [N] on the rectangle [u0, u1] x [v0, v1] and its moments ∫q u, ∫q v."""
        return _plane_integrals(self.a, self.gu, self.gv, self.clip, u0, u1, v0, v1)

    def over(self, u0: float, u1: float, v0: float, v1: float) -> float:
        """The force [N] on the rectangle [u0, u1] x [v0, v1]."""
        return self.integrals(u0, u1, v0, v1)[0]


def _no_tension_plane(
    total: float, eu: float, ev: float, length: float, width: float
) -> tuple[float, float, float] | None:
    """The plane (a, gu, gv) of the no-tension contact pressure q = max(0, a + gu u + gv v) in
    equilibrium with ``total`` at (eu, ev): the minimum of the convex potential
    ½ ∫ max(0, q)² dA - (a, gu, gv)·(P, P eu, P ev), by Newton's method with backtracking. Its
    Hessian is the matrix of contact-area moments. None when it does not converge."""
    hu, hv = length / 2, width / 2
    target = np.array([total, total * eu, total * ev])
    scale = np.array([total, total * length, total * width])

    def matrix(x: np.ndarray) -> np.ndarray:
        area, su, sv, suu, suv, svv = _polygon_moments(_clip(-hu, hu, -hv, hv, *x))
        return np.array([[area, su, sv], [su, suu, suv], [sv, suv, svv]])

    def potential(x: np.ndarray, m: np.ndarray) -> float:
        return 0.5 * float(x @ m @ x) - float(x @ target)

    area = length * width
    x = np.array(
        [total / area, 12 * total * eu / (width * length**3), 12 * total * ev / (length * width**3)]
    )
    m = matrix(x)
    for _ in range(200):
        gradient = m @ x - target
        residual = float(np.max(np.abs(gradient) / scale))
        if residual < 1e-9:
            return float(x[0]), float(x[1]), float(x[2])
        try:
            step = np.linalg.solve(m, target) - x
        except np.linalg.LinAlgError:
            return None
        current, slope, lam = potential(x, m), float(gradient @ step), 1.0
        while lam > 1e-8:
            trial = x + lam * step
            m_trial = matrix(trial)
            if m_trial[0, 0] > 0 and potential(trial, m_trial) <= current + 1e-4 * lam * slope:
                break
            lam /= 2
        else:
            # No descent left within rounding: accept a solution already in equilibrium.
            return (float(x[0]), float(x[1]), float(x[2])) if residual < 1e-6 else None
        x, m = trial, m_trial
    return None


def soil_pressure(total: float, eu: float, ev: float, length: float, width: float) -> SoilPressure:
    """The pressure under a ``length`` (along u) x ``width`` base of a vertical resultant
    ``total`` [N] at ``(eu, ev)`` [mm] from the centroid."""
    if total <= 0:
        return SoilPressure(total, eu, ev, 0, 0, 0, False, "uplift", 0, 0, 0)
    area = length * width
    ru, rv = abs(eu) / length, abs(ev) / width
    mean = total / area
    linear = (
        mean,
        12 * total * eu / (width * length**3),
        12 * total * ev / (length * width**3),
    )
    corner_max, corner_min = mean * (1 + 6 * ru + 6 * rv), mean * (1 - 6 * ru - 6 * rv)
    if 6 * (ru + rv) <= 1 + 1e-9:
        return SoilPressure(total, eu, ev, *linear, False, "kern", corner_max, corner_min, 1.0)
    unstable = SoilPressure(total, eu, ev, *linear, False, "unstable", math.inf, -math.inf, 0)
    if ru >= 0.5 - 1e-9 or rv >= 0.5 - 1e-9:
        return unstable
    if min(ru, rv) < 1e-9:
        # One eccentricity: the triangular pressure in closed form.
        along_u = ru >= rv
        e, span, across = (eu, length, width) if along_u else (ev, width, length)
        rest = span / 2 - abs(e)
        qmax = 2 * total / (3 * across * rest)
        reach = 3 * rest
        sign = 1.0 if e > 0 else -1.0
        g = sign * qmax / reach
        a = qmax - g * sign * span / 2
        gu, gv = (g, 0.0) if along_u else (0.0, g)
        return SoilPressure(total, eu, ev, a, gu, gv, True, "partial", qmax, 0.0, reach / span)
    plane = _no_tension_plane(total, eu, ev, length, width)
    if plane is None:
        return unstable
    a, gu, gv = plane
    corners = [a + gu * su * length / 2 + gv * sv * width / 2 for su in (-1, 1) for sv in (-1, 1)]
    contact = _polygon_moments(_clip(-length / 2, length / 2, -width / 2, width / 2, *plane))[0]
    return SoilPressure(
        total, eu, ev, a, gu, gv, True, "partial", max(corners), 0.0, contact / area
    )


# ─────────────────────────────────────── capacities ───────────────────────────────────────


def size_factor(d: float) -> float:
    """λs = √(2 / (1 + 0.004 d)) <= 1 (ACI 22.5.5.1.3)."""
    return min(1.0, math.sqrt(2 / (1 + 0.004 * d)))


def one_way_shear_capacity(b: float, d: float, rho: float, fc: float, lam: float = 1.0) -> float:
    """φVc [N] of a footing strip without shear reinforcement: ACI 318-19 Table 22.5.5.1 (c),
    0.66 λs λ ρw^(1/3) √f'c b d, at most 0.42 λ √f'c b d (√f'c <= 8.3 MPa)."""
    root = min(math.sqrt(fc), 8.3)
    vc = 0.66 * size_factor(d) * lam * max(rho, 0.0) ** (1 / 3) * root * b * d
    return PHI_SHEAR * min(vc, 0.42 * lam * root * b * d)


def punching_stress(
    c1: float, c2: float, d: float, b0: float, alpha_s: float, fc: float, lam: float = 1.0
) -> float:
    """vc [MPa] of two-way shear without shear reinforcement (ACI 318-19 Table 22.6.5.2): the
    least of 0.33, 0.17 (1 + 2/β) and 0.083 (2 + αs d / b0) times λs λ √f'c, β the long over
    the short side of the column."""
    root = min(math.sqrt(fc), 8.3)
    beta = max(c1, c2) / min(c1, c2)
    factor = min(0.33, 0.17 * (1 + 2 / beta), 0.083 * (2 + alpha_s * d / b0))
    return factor * size_factor(d) * lam * root


def gamma_v(b1: float, b2: float) -> float:
    """Share of an unbalanced moment transferred by shear eccentricity (ACI 8.4.2.2.2 /
    8.4.4.2.2): 1 - 1 / (1 + (2/3) √(b1 / b2)), b1 the critical section's side along the span."""
    return 1 - 1 / (1 + (2 / 3) * math.sqrt(b1 / b2))


def polar_j(b1: float, b2: float, d: float) -> float:
    """Jc of an interior rectangular critical section [mm⁴] (ACI R8.4.4.2.3)."""
    return d * b1**3 / 6 + b1 * d**3 / 6 + d * b2 * b1**2 / 2


def min_steel_ratio(fy: float) -> float:
    """As,min / Ag of a slab or footing with deformed bars (ACI 318-19 Table 7.6.1.1)."""
    if fy < 420:
        return 0.0020
    return max(0.0018 * 420 / fy, 0.0014)


def mesh_area(mesh: BarMesh | None) -> float:
    """Bar area per metre width [mm²/m]."""
    if mesh is None:
        return 0.0
    return math.pi * mesh.dia**2 / 4 * 1000 / mesh.spacing


def plain_flexure(h: float, fc: float, lam: float = 1.0) -> float:
    """φMn [N·mm per metre] of plain concrete in flexure: 0.60 x 0.42 λ √f'c Sm (ACI 318-19
    14.5.2.1 (a), φ per 21.2.1), with h less 50 mm for a footing cast against soil
    (14.5.1.7)."""
    depth = max(h - 50.0, 0.0)
    return 0.60 * 0.42 * lam * math.sqrt(fc) * 1000 * depth**2 / 6


@dataclass(frozen=True)
class StripFlexure:
    phi_mn: float  # N·mm per metre
    phi: float
    eps_t: float


def strip_flexure(
    as_per_m: float, d: float, fc: float, fy: float, es: float = STEEL_E
) -> StripFlexure:
    """Design moment of a 1 m strip with ``as_per_m`` tension bars at depth ``d`` (rectangular
    stress block, φ from εt per ACI 21.2.2)."""
    if as_per_m <= 0 or d <= 0:
        return StripFlexure(0.0, 0.9, math.inf)
    a = as_per_m * fy / (0.85 * fc * 1000)
    c = a / beta1(fc)
    eps_t = 0.003 * (d - c) / c
    phi = phi_axial_flexure(eps_t, fy, es)
    return StripFlexure(phi * as_per_m * fy * (d - a / 2), phi, eps_t)


# ─────────────────────────────────────── the footing ───────────────────────────────────────


@dataclass(frozen=True)
class ColumnBase:
    """A column standing on a footing, in the footing's axes [mm]."""

    id: str
    u: float
    v: float
    cu: float  # column side along u
    cv: float  # along v
    arm: float = 0.0  # from the footing's underside up to the column base


@dataclass
class FootingSpec:
    """A footing to design: geometry [mm], materials [MPa], meshes and its columns."""

    id: str
    type: str
    footing_type: str
    length: float  # along u
    width: float  # along v
    thickness: float
    elevation: float  # top [mm]
    cover: float
    fc: float
    fy: float
    columns: list[ColumnBase]
    bottom_x: BarMesh | None = None
    bottom_y: BarMesh | None = None
    top_x: BarMesh | None = None
    top_y: BarMesh | None = None
    es: float = STEEL_E
    unit_weight: float = 2400 * G * 1e-9  # N/mm³
    notes: list[str] = field(default_factory=list)

    @property
    def d(self) -> float:
        bars = [m.dia for m in (self.bottom_x, self.bottom_y) if m]
        return self.thickness - self.cover - (max(bars) if bars else 0.0)

    @property
    def d_top(self) -> float:
        bars = [m.dia for m in (self.top_x, self.top_y) if m]
        return self.thickness - self.cover - (max(bars) if bars else 0.0)


Loads = dict[str, list[np.ndarray]]
"""Per combination, per column of the footing: ``[P, Cu, Cv]``: the downward load [N] and the
moments [N·mm] about the u and v axes at the footing's underside, the column's action on it."""


def _eccentricity(spec: FootingSpec, loads: list[np.ndarray], extra: float = 0.0):
    total = sum(float(f[0]) for f in loads) + extra
    if total <= 0:
        return total, 0.0, 0.0
    mv = sum(float(f[0]) * c.u + float(f[2]) for c, f in zip(spec.columns, loads, strict=True))
    mu = sum(float(f[0]) * c.v - float(f[1]) for c, f in zip(spec.columns, loads, strict=True))
    return total, mv / total, mu / total


def _contact(spec: FootingSpec, loads: list[np.ndarray], weight: float = 0.0) -> SoilPressure:
    """The soil pressure under the column ``loads`` and a uniform ``weight`` [N/mm²] of the
    footing and the soil above it."""
    total, eu, ev = _eccentricity(spec, loads, weight * spec.length * spec.width)
    return soil_pressure(total, eu, ev, spec.length, spec.width)


def _beam(
    spec: FootingSpec,
    pressure: SoilPressure,
    loads: list[np.ndarray],
    axis: str,
    weight: float = 0.0,
):
    """Shear V(s) and sagging-positive moment M(s) [N, N·mm] of the footing as a beam along
    ``axis``, from its left end, under the soil ``pressure``, its uniform ``weight`` [N/mm²]
    acting down and the column ``loads``."""
    span, across = (spec.length, spec.width) if axis == "u" else (spec.width, spec.length)
    start = -span / 2
    point = []
    for c, f in zip(spec.columns, loads, strict=True):
        s, width = (c.u, c.cu) if axis == "u" else (c.v, c.cv)
        couple = float(f[2]) if axis == "u" else -float(f[1])
        point.append((s - width / 2, s + width / 2, float(f[0]), couple))

    def soil(s: float) -> tuple[float, float]:
        """The soil force on the part from the left end to ``s`` and its moment about ``s``."""
        if axis == "u":
            force, first, _ = pressure.integrals(start, s, -spec.width / 2, spec.width / 2)
        else:
            force, _, first = pressure.integrals(-spec.length / 2, spec.length / 2, start, s)
        part = max(s - start, 0.0)
        return (
            force - weight * across * part,
            s * force - first - weight * across * part**2 / 2,
        )

    def shear(s: float) -> float:
        value = soil(s)[0]
        for lo, hi, p, _ in point:
            value -= p * min(max((s - lo) / (hi - lo), 0.0), 1.0)
        return value

    def moment(s: float) -> float:
        value = soil(s)[1]
        for lo, hi, p, couple in point:
            top = min(s, hi)
            if top > lo:
                value -= p / (hi - lo) * ((s - lo) ** 2 - (s - top) ** 2) / 2
            value += couple * min(max((s - lo) / (hi - lo), 0.0), 1.0)
        return value

    return shear, moment, point, span


def _transverse_strip(
    spec: FootingSpec, column: ColumnBase, load: np.ndarray, long_axis: str
) -> tuple[FootingSpec, list[np.ndarray]]:
    """The strip of a combined footing under ``column`` that spans across the footing: width
    c + d along ``long_axis`` (cut at the footing's ends), centred on the column, carrying the
    column's load and its moment across (ACI 336.2R practice)."""
    d = spec.d
    span = spec.length if long_axis == "u" else spec.width
    s, side = (column.u, column.cu) if long_axis == "u" else (column.v, column.cv)
    lo, hi = max(s - side / 2 - d / 2, -span / 2), min(s + side / 2 + d / 2, span / 2)
    if long_axis == "u":
        strip = replace(spec, length=hi - lo, columns=[replace(column, u=0.0)])
        return strip, [np.array([float(load[0]), float(load[1]), 0.0])]
    strip = replace(spec, width=hi - lo, columns=[replace(column, v=0.0)])
    return strip, [np.array([float(load[0]), 0.0, float(load[2])])]


def design_footing(
    spec: FootingSpec,
    service: Loads,
    strength: Loads,
    foundation: Foundation,
    dead: dict[str, float] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The checks of one footing and notes on it. ``dead`` gives, per strength combination,
    the factor on the weight of the footing and the soil above it (its dead-load factor;
    1.0 when not given)."""
    notes: list[str] = []
    checks: list[dict[str, Any]] = []
    length, width, h = spec.length, spec.width, spec.thickness

    # ── bearing (service) ──
    gamma = foundation.soilUnitWeight * 1e-6  # N/mm³
    cover_depth = max(0.0, foundation.groundLevel - spec.elevation)
    founding = max(0.0, foundation.groundLevel - (spec.elevation - h))
    own_weight = spec.unit_weight * h + gamma * cover_depth  # N/mm² of base
    overburden = gamma * founding
    worst: tuple[float, float, str, str] | None = None  # (utilisation, q net, combination, note)
    qa = foundation.allowableBearing / 1e3 if foundation.allowableBearing else None
    # The resultant outside the base or the footing lifted off: reported as their own checks,
    # with the eccentricity against the half side (the bearing check takes the other cases).
    outside: tuple[float, float, float, str, str] | None = None  # (ratio, e, half, name, note)
    uplift: tuple[float, str] | None = None  # (upward force N, name)
    for name, loads in service.items():
        pressure = _contact(spec, loads, own_weight)
        note = f"eu = {pressure.eu:.0f} mm, ev = {pressure.ev:.0f} mm"
        if pressure.state == "uplift":
            if uplift is None or -pressure.total > uplift[0]:
                uplift = (-pressure.total, name)
            continue
        if pressure.state == "unstable":
            ratio_u = abs(pressure.eu) / (length / 2)
            ratio_v = abs(pressure.ev) / (width / 2)
            e, half = (
                (abs(pressure.eu), length / 2)
                if ratio_u >= ratio_v
                else (abs(pressure.ev), width / 2)
            )
            if outside is None or max(ratio_u, ratio_v) > outside[0]:
                outside = (max(ratio_u, ratio_v), e, half, name, note)
            continue
        else:
            net = pressure.qmax - overburden
            utilisation = net / qa if qa else 0.0
            note = f"gross qmax = {pressure.qmax * 1e3:.0f} kPa, " + note
            if pressure.state == "partial":
                note += f"; partial contact over {pressure.contact:.0%} of the base"
        if (
            worst is None
            or utilisation > worst[0]
            or (utilisation == worst[0] and math.isfinite(net) and net > worst[1])
        ):
            worst = (utilisation, net, name, note)
    if outside is not None:
        ratio, e, half, name, note = outside
        checks.append(
            _check(
                "Resultant within the base (service)",
                e,
                half,
                "mm",
                name,
                note + "; the resultant lies outside the base: enlarge the footing or tie it",
                utilisation=ratio,
            )
        )
    if uplift is not None:
        force, name = uplift
        checks.append(
            _check(
                "Uplift (service)",
                force / 1e3,
                0.0,
                "kN",
                name,
                "the column loads lift the footing off, its weight and the soil above included",
            )
        )
    if worst is not None:
        utilisation, net, name, note = worst
        note += f"; net = gross - γ Df = gross - {overburden * 1e3:.0f} kPa"
        if qa:
            checks.append(
                _check(
                    "Bearing (service)",
                    net * 1e3 if math.isfinite(net) else 0.0,
                    qa * 1e3,
                    "kPa",
                    name,
                    note,
                    utilisation=utilisation,
                )
            )
        else:
            shown = f"net pressure {net * 1e3:.0f} kPa" if math.isfinite(net) else "no bearing"
            notes.append(
                f"{spec.id}: bearing not checked: enter the net allowable bearing pressure qa "
                f"from the soil report (Project Settings, Foundation); governing {name}: "
                f"{shown}, {note}"
            )
    elif service == {}:
        notes.append(f"{spec.id}: no service combination could be formed for the bearing check")

    # ── strength ──
    d, fc, fy = spec.d, spec.fc, spec.fy
    meshes = {"u": (spec.bottom_x, spec.top_x), "v": (spec.bottom_y, spec.top_y)}
    labels = {"u": "X", "v": "Y"}
    # per check name: (utilisation, demand, capacity, unit, combination, note)
    governing: dict[str, tuple[float, float, float, str, str, str]] = {}

    unchecked: set[str] = set()
    states: dict[str, list[str]] = {}  # factored combinations by unusual pressure state

    def keep(name: str, utilisation: float, *rest: Any) -> None:
        if name not in governing or utilisation > governing[name][0]:
            governing[name] = (utilisation, *rest)

    spread = {
        axis: max((c.u if axis == "u" else c.v) for c in spec.columns)
        - min((c.u if axis == "u" else c.v) for c in spec.columns)
        for axis in ("u", "v")
    }
    combined = len(spec.columns) > 1
    long_axis = "u" if spread["u"] >= spread["v"] else "v"

    def axis_checks(
        beam_spec: FootingSpec,
        pressure: SoilPressure,
        loads: list[np.ndarray],
        axis: str,
        weight: float,
        name: str,
        strip_of: str | None = None,
    ) -> None:
        """One-way shear and flexure of ``beam_spec`` as a beam along ``axis``; ``strip_of``
        names the column of a transverse strip of a combined footing."""
        label = labels[axis]
        shear, moment, point, span = _beam(beam_spec, pressure, loads, axis, weight)
        across = beam_spec.width if axis == "u" else beam_spec.length
        bottom, top = meshes[axis]
        where = (
            f"transverse strip under {strip_of}, b = c + d = {across:.0f} mm (ACI 336.2R); "
            if strip_of
            else ""
        )

        def inside(s: float) -> bool:
            return any(lo + 1e-6 < s < hi - 1e-6 for lo, hi, _, _ in point)

        # One-way shear at d from the faces (ACI 13.2.7.2).
        sections = [
            s
            for lo, hi, _, _ in point
            for s in (lo - d, hi + d)
            if -span / 2 < s < span / 2 and not inside(s)
        ]
        rho = mesh_area(bottom) / (1000 * d) if d > 0 else 0.0
        capacity = one_way_shear_capacity(across, d, rho, fc)
        if sections:
            vu, at = max((abs(shear(s)), s) for s in sections)
            keep(
                f"One-way shear {label}",
                vu / capacity if capacity > 0 else math.inf,
                vu / 1e3,
                capacity / 1e3,
                "kN",
                name,
                f"{where}at {label.lower()} = {at:.0f} mm, d = {d:.0f} mm, ρw = {rho:.4f}, "
                f"λs = {size_factor(d):.2f}, b = {across:.0f} mm",
            )

        # Flexure at the faces (ACI 13.2.7.1) and along the span.
        faces = [s for lo, hi, _, _ in point for s in (lo, hi) if -span / 2 < s < span / 2]
        samples = [s for s in np.linspace(-span / 2, span / 2, 241)[1:-1] if not inside(float(s))]
        stations = [*faces, *map(float, samples)]
        sag = max(((moment(s), s) for s in stations), default=(0.0, 0.0))
        hog = min(((moment(s), s) for s in stations), default=(0.0, 0.0))
        per_m = 1000 / across
        strip = strip_flexure(mesh_area(bottom), d, fc, fy, spec.es)
        note = f"{where}at {label.lower()} = {sag[1]:.0f} mm, d = {d:.0f} mm"
        if bottom is None:
            note = "no bottom bars in this direction; " + note
        else:
            note = f"Ø{bottom.dia:g} @ {bottom.spacing:g}, φ = {strip.phi:.2f}; " + note
        if not combined and abs(length - width) > 1 and across == max(length, width):
            ratio = max(length, width) / min(length, width)
            note += (
                f"; short-direction bars: {2 / (ratio + 1):.0%} of them within the central "
                f"band {min(length, width):.0f} mm wide (ACI 13.3.3.3)"
            )
        demand = max(sag[0], 0.0) * per_m
        keep(
            f"Flexure {label} (bottom)",
            demand / strip.phi_mn if strip.phi_mn > 0 else (0.0 if demand <= 0 else math.inf),
            demand / 1e6,
            strip.phi_mn / 1e6,
            "kN·m/m",
            name,
            note,
        )
        hogging = max(-hog[0], 0.0) * per_m
        between = combined and axis == long_axis
        if between or hogging > 1e6:  # 1 kN·m/m: a hogging moment worth top bars
            d_top = spec.d_top
            note = f"{where}at {label.lower()} = {hog[1]:.0f} mm"
            if not between:
                note += (
                    "; the weight of the footing and the soil above it exceeds the soil "
                    "pressure there"
                )
            if top is None:
                capacity = plain_flexure(h, fc)
                note = (
                    f"no top bars: plain concrete, φMn = 0.60 x 0.42 √f'c Sm with "
                    f"h - 50 = {h - 50:.0f} mm (ACI 14.5.2.1, 14.5.1.7); " + note
                )
                if hogging > capacity:
                    note = "top reinforcement is needed; " + note
            else:
                strip_top = strip_flexure(mesh_area(top), d_top, fc, fy, spec.es)
                capacity = strip_top.phi_mn
                note = (
                    f"Ø{top.dia:g} @ {top.spacing:g}, d = {d_top:.0f} mm, "
                    f"φ = {strip_top.phi:.2f}; " + note
                )
            keep(
                "Flexure between columns (top)" if between else f"Flexure {label} (top)",
                hogging / capacity if capacity > 0 else (0.0 if hogging <= 0 else math.inf),
                hogging / 1e6,
                capacity / 1e6,
                "kN·m/m",
                name,
                note,
            )

    for name, loads in strength.items():
        weight = (dead or {}).get(name, 1.0) * own_weight
        pressure = _contact(spec, loads, weight)
        if pressure.state != "kern":
            states.setdefault(pressure.state, []).append(name)
        if pressure.state in ("uplift", "unstable"):
            continue
        for axis in ("u", "v"):
            if not combined or axis == long_axis:
                axis_checks(spec, pressure, loads, axis, weight, name)
                continue
            for column, f in zip(spec.columns, loads, strict=True):
                strip_spec, strip_loads = _transverse_strip(spec, column, f, long_axis)
                strip_pressure = _contact(strip_spec, strip_loads, weight)
                if strip_pressure.state not in ("uplift", "unstable"):
                    axis_checks(
                        strip_spec, strip_pressure, strip_loads, axis, weight, name, column.id
                    )

        # Punching at d/2 around each column (ACI 22.6, 8.4.4.2.3).
        for column, f in zip(spec.columns, loads, strict=True):
            pu, cu_moment, cv_moment = float(f[0]), float(f[1]), float(f[2])
            u0, u1 = column.u - column.cu / 2 - d / 2, column.u + column.cu / 2 + d / 2
            v0, v1 = column.v - column.cv / 2 - d / 2, column.v + column.cv / 2 + d / 2
            sides = {
                "u-": u0 > -length / 2,
                "u+": u1 < length / 2,
                "v-": v0 > -width / 2,
                "v+": v1 < width / 2,
            }
            cu0, cu1 = max(u0, -length / 2), min(u1, length / 2)
            cv0, cv1 = max(v0, -width / 2), min(v1, width / 2)
            b0 = (sides["u-"] + sides["u+"]) * (cv1 - cv0) + (sides["v-"] + sides["v+"]) * (
                cu1 - cu0
            )
            count = sum(sides.values())
            check_name = f"Punching at {column.id}"
            if count < 2 or b0 <= 0:
                if column.id not in unchecked:
                    unchecked.add(column.id)
                    notes.append(
                        f"{spec.id}: punching at {column.id} not checked: the critical section "
                        "lies outside the footing"
                    )
                continue
            alpha_s = {4: 40, 3: 30, 2: 20}[count]
            inside = pressure.over(cu0, cu1, cv0, cv1) - weight * (cu1 - cu0) * (cv1 - cv0)
            vu = max(pu - inside, 0.0)
            b1u, b1v = column.cu + d, column.cv + d
            moment_u = gamma_v(b1u, b1v) * abs(cv_moment) * (b1u / 2) / polar_j(b1u, b1v, d)
            moment_v = gamma_v(b1v, b1u) * abs(cu_moment) * (b1v / 2) / polar_j(b1v, b1u, d)
            stress = vu / (b0 * d) + moment_u + moment_v
            vc = punching_stress(column.cu, column.cv, d, b0, alpha_s, fc)
            phi_vc = PHI_SHEAR * vc
            keep(
                check_name,
                stress / phi_vc,
                stress * b0 * d / 1e3,
                phi_vc * b0 * d / 1e3,
                "kN",
                name,
                f"vu = {stress:.2f} MPa (Vu = {vu / 1e3:.0f} kN, moments "
                f"{(moment_u + moment_v):.2f} MPa), φvc = {phi_vc:.2f} MPa, b0 = {b0:.0f} mm, "
                f"d = {d:.0f} mm, αs = {alpha_s}",
            )

    for state, text in (
        ("uplift", "not checked for strength: the footing lifts off"),
        ("unstable", "not checked for strength: the resultant lies outside the base"),
        (
            "partial",
            "the base is in partial contact; the strength checks take the contact pressure",
        ),
    ):
        names = states.get(state, [])
        if names:
            listed = ", ".join(names[:3]) + (
                f" and {len(names) - 3} more" if len(names) > 3 else ""
            )
            notes.append(f"{spec.id}: under {listed}: {text}")

    order = [
        *(f"Punching at {c.id}" for c in spec.columns),
        "One-way shear X",
        "One-way shear Y",
        "Flexure X (bottom)",
        "Flexure Y (bottom)",
        "Flexure between columns (top)",
        "Flexure X (top)",
        "Flexure Y (top)",
    ]
    checks += [_kept(name, governing[name]) for name in order if name in governing]

    # Minimum reinforcement (ACI 7.6.1.1, 13.3.4.1): each bottom direction.
    ratio = min_steel_ratio(fy)
    required = ratio * h * 1000
    limit = min(3 * h, 450.0)
    for label, mesh in (("X", spec.bottom_x), ("Y", spec.bottom_y)):
        provided = mesh_area(mesh)
        note = f"{ratio:.4f} Ag, Ag = {h:.0f} mm x 1 m"
        if mesh is None:
            note = "no bottom bars; " + note
        elif mesh.spacing > limit:
            note += f"; spacing {mesh.spacing:g} mm exceeds {limit:.0f} mm (ACI 7.7.2.3)"
        checks.append(
            _check(
                f"Min. reinforcement {label} (bottom)",
                required,
                provided,
                "mm²/m",
                None,
                note,
            )
        )
    return checks, notes


def _kept(name: str, value: tuple[float, float, float, str, str, str]) -> dict[str, Any]:
    utilisation, demand, capacity, unit, combination, note = value
    return _check(name, demand, capacity, unit, combination, note, utilisation=utilisation)


# ─────────────────────────────────── from the analysed model ───────────────────────────────────


def service_combinations(
    cases: set[str] | list[str], strength_level_wind: bool = False
) -> list[tuple[str, dict[str, float]]]:
    """The allowable-stress combinations the static ``cases`` allow, as (name, {case: factor});
    ``D`` stands for the dead and superimposed dead cases. Wind is nominal (service-level) as
    BNBC 2020 Part 6 defines it, with the 2.7.2 combinations (ASCE 7-05 2.4.1): D + W,
    D + 0.75L + 0.75Lr + 0.75W and 0.6D + W; ``strength_level_wind`` takes the ASCE 7-16 2.4.1
    factors 0.6W and 0.45W instead. Earthquake is strength-level: 0.7E and 0.525E."""
    cases = set(cases)
    dead = [c for c in ("D", "SD") if c in cases]
    if not dead:
        return []
    live = [c for c in ("L", "Lr") if c in cases]

    def terms(*parts: tuple[float, list[str]]) -> tuple[str, dict[str, float]]:
        factors: dict[str, float] = {}
        words: list[str] = []
        for factor, group in parts:
            for case in group:
                factors[case] = factor
            shown = ["D"] if group == dead else group
            for case in shown:
                magnitude = abs(factor)
                text = f"{'' if magnitude == 1 else f'{magnitude:g}'}{case}"
                if words:
                    words.append(("- " if factor < 0 else "+ ") + text)
                else:
                    words.append(("-" if factor < 0 else "") + text)
        return " ".join(words), factors

    result = [terms((1.0, dead))]
    if live:
        result.append(terms((1.0, dead), (1.0, live)))
    wind = (0.6, 0.45, 0.6) if strength_level_wind else (1.0, 0.75, 1.0)
    for lateral, alone, with_live, light in (
        ("W", *wind),
        ("E", 0.7, 0.525, 0.7),
    ):
        for axis in ("X", "Y"):
            case = f"{lateral}{axis}"
            if case not in cases:
                continue
            for sign in (1.0, -1.0):
                result.append(terms((1.0, dead), (sign * alone, [case])))
                if live:
                    result.append(terms((1.0, dead), (0.75, live), (sign * with_live, [case])))
                result.append(terms((0.6, dead), (sign * light, [case])))
    return result


def _case_reactions(out_dir: str | Path) -> dict[str, dict[int, np.ndarray]]:
    from opensees_studio.services.result_store import load_manifest, load_results
    from opensees_studio.services.results import StaticResults

    from saengine.fem.display import _code, _last

    try:
        manifest = load_manifest(out_dir)
    except (OSError, ValueError) as error:
        raise ValueError("there are no results; run the analysis first") from error
    by_case: dict[str, dict[int, np.ndarray]] = {}
    for entry in manifest["cases"]:
        results = load_results(entry, out_dir)
        if not isinstance(results, StaticResults):
            continue
        by_case[_code(entry["case_name"])] = {
            int(n): _last(results.node_reaction, n, 6) for n in results.node_reaction
        }
    return by_case


def column_action(
    reaction: np.ndarray, arm: float, axis_u: np.ndarray, axis_v: np.ndarray
) -> np.ndarray:
    """``[P, Cu, Cv]`` a column puts on its footing (see :data:`Loads`) from its support
    reaction ``[Fx, Fy, Fz, Mx, My, Mz]`` [N, N·m, global axes]; ``arm`` [mm] from the
    footing's underside up to the column base, where the horizontal force acts."""
    force = -np.asarray(reaction[:3], dtype=float)
    moment = -np.asarray(reaction[3:], dtype=float) * 1e3
    fu, fv = float(force @ axis_u), float(force @ axis_v)
    mu, mv = float(moment @ axis_u), float(moment @ axis_v)
    return np.array([-float(force[2]), mu - arm * fv, mv + arm * fu])


def _combine(per_case: dict[str, list[np.ndarray]], factors: dict[str, float]) -> list[np.ndarray]:
    count = len(next(iter(per_case.values()), []))
    return [
        sum((f * per_case[case][k] for case, f in factors.items()), np.zeros(3))
        for k in range(count)
    ]


def footing_checks(
    project: dict[str, Any],
    out_dir: str | Path,
    building: BuildingModel,
    objects: ObjectLibrary,
    materials: MaterialLibrary,
    settings: ProjectSettings,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """The footing checks of an analysed model, in :func:`saengine.design.design_report`'s
    format: ``(elements, skipped, notes)``. Arguments as :func:`saengine.design.check.design`.
    """
    from saengine.fem.combinations import combination_factors

    footings = [e for e in building.elements if isinstance(e, FootingElement)]
    if not footings:
        return [], [], []
    types = {o.id: o for o in objects.objects}
    mats = {m.id: m for m in materials.materials}
    by_case = _case_reactions(out_dir)

    # Restrained nodes of the analysis model, by position [mm].
    supports: dict[tuple[int, int, int], int] = {}
    for node in project.get("nodes", []):
        if any(node.get("restraint") or []):
            key = tuple(round(float(c) * 1000) for c in node["coords"][:3])
            supports[key] = int(node["id"])  # type: ignore[index]
    bases: list[tuple[ColumnElement, int]] = []
    for element in building.elements:
        if isinstance(element, ColumnElement):
            key = (round(element.position[0]), round(element.position[1]), round(element.bottom))
            if key in supports:
                bases.append((element, supports[key]))

    strength: list[tuple[str, dict[str, float]]] = []
    for combination in settings.combinations:
        factors = combination_factors(combination)
        if all(case in by_case for case in factors):
            strength.append((combination.name, factors))
    # Wind is nominal when a strength combination factors it above 1.0 (1.6W, BNBC 2.7.3).
    wind_factors = [abs(f) for _, fs in strength for case, f in fs.items() if case[:1] == "W"]
    strength_level_wind = bool(wind_factors) and max(wind_factors) <= 1.0 + 1e-9
    service = service_combinations(by_case, strength_level_wind)
    dead = {name: factors.get("D", factors.get("SD", 0.0)) for name, factors in strength}

    elements: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    notes: list[str] = []
    placed: set[str] = set()
    for footing in footings:
        object_type = types.get(footing.type)

        def skip(reason: str, footing: FootingElement = footing) -> None:
            skipped.append(
                {"id": footing.id, "kind": "footing", "type": footing.type, "reason": reason}
            )

        if object_type is None:
            skip(f"unknown object type '{footing.type}'")
            continue
        if not isinstance(object_type, Footing):
            skip(f"{object_type.kind} foundations are not designed yet")
            continue
        theta = math.radians(footing.rotation)
        axis_u = np.array([math.cos(theta), math.sin(theta), 0.0])
        axis_v = np.array([-math.sin(theta), math.cos(theta), 0.0])
        bottom = footing.elevation - object_type.thickness
        on: list[tuple[ColumnElement, int, float, float]] = []
        for column, node in bases:
            offset = np.array(
                [
                    column.position[0] - footing.position[0],
                    column.position[1] - footing.position[1],
                    0,
                ]
            )
            u, v = float(offset @ axis_u), float(offset @ axis_v)
            if abs(u) <= object_type.length / 2 + 1 and abs(v) <= object_type.width / 2 + 1:
                if column.id in placed:
                    notes.append(
                        f"{column.id}: stands on more than one footing; taken by the first"
                    )
                    continue
                on.append((column, node, u, v))
        if object_type.footingType == "strip":
            skip("strip footings are not designed yet")
            placed.update(c.id for c, *_ in on)
            continue
        if not on:
            skip("no column base lies within its plan outline")
            continue
        placed.update(c.id for c, *_ in on)
        concrete = mats.get(object_type.material)
        if concrete is None or concrete.category != Category.CONCRETE or not concrete.concrete:
            skip("not a concrete footing")
            continue
        reinforcement = object_type.reinforcement
        if reinforcement is None:
            skip("no reinforcement")
            continue
        bars = mats.get(reinforcement.material)
        if bars is None or bars.steel is None:
            skip(f"unknown reinforcement material '{reinforcement.material}'")
            continue
        if not strength:
            skip("no load combination could be formed")
            continue
        spec_notes: list[str] = []
        columns: list[ColumnBase] = []
        problem = None
        for column, _, u, v in on:
            column_type = types.get(column.type)
            profile = column_type.profile if isinstance(column_type, Column) else None
            if isinstance(profile, RectangleProfile):
                sides = (profile.xDim, profile.yDim)
            elif isinstance(profile, CircleProfile):
                side = profile.radius * math.sqrt(math.pi)
                sides = (side, side)
            else:
                problem = f"{column.id}: only rectangular and circular columns are supported"
                break
            turn = (column.rotation - footing.rotation) / 90
            if abs(turn - round(turn)) > 1e-6 and not isinstance(profile, CircleProfile):
                spec_notes.append(
                    f"{footing.id}: {column.id} is skewed to the footing; taken at the nearest "
                    "quarter turn"
                )
            if round(turn) % 2:
                sides = sides[::-1]
            columns.append(
                ColumnBase(column.id, u, v, sides[0], sides[1], max(column.bottom - bottom, 0.0))
            )
        if problem:
            skip(problem)
            continue
        if object_type.footingType == "isolated" and len(columns) > 1:
            spec_notes.append(
                f"{footing.id}: an isolated footing under {len(columns)} columns is designed as "
                "a combined footing"
            )
        density = concrete.mechanical.density or 2400.0
        spec = FootingSpec(
            id=footing.id,
            type=footing.type,
            footing_type=object_type.footingType,
            length=object_type.length,
            width=object_type.width,
            thickness=object_type.thickness,
            elevation=footing.elevation,
            cover=reinforcement.cover,
            fc=concrete.concrete.fc,
            fy=bars.steel.fy,
            es=bars.mechanical.E or STEEL_E,
            columns=columns,
            bottom_x=reinforcement.bottomX,
            bottom_y=reinforcement.bottomY,
            top_x=reinforcement.topX,
            top_y=reinforcement.topY,
            unit_weight=density * G * 1e-9,
        )
        if spec.d <= 0:
            skip("the cover and bars leave no effective depth")
            continue

        per_case = {
            case: [
                column_action(reactions.get(node, np.zeros(6)), c.arm, axis_u, axis_v)
                for (_, node, _, _), c in zip(on, columns, strict=True)
            ]
            for case, reactions in by_case.items()
        }
        checks, footing_notes = design_footing(
            spec,
            {name: _combine(per_case, factors) for name, factors in service},
            {name: _combine(per_case, factors) for name, factors in strength},
            settings.foundation,
            dead,
        )
        notes += spec_notes + footing_notes
        strength_checks = [c for c in checks if not c["flag"]]
        elements.append(
            {
                "id": footing.id,
                "kind": "footing",
                "type": footing.type,
                "members": [c.id for c in columns],
                "checks": checks,
                "utilisation": max((c["utilisation"] for c in strength_checks), default=0.0),
                "ok": all(c["ok"] for c in strength_checks),
            }
        )
    for column, _ in bases:
        if column.id not in placed:
            notes.append(f"{column.id}: no footing under it")
    return elements, skipped, notes

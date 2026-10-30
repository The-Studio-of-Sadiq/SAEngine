"""Design of the shallow foundations: isolated, combined and strip footings, and tie beams.

Each footing carries the columns (and walls) the substructure lists for it and takes their
support reactions, case by case, as the loads they put on it (the reactions reversed, in the
footing's local axes ``u`` along its length and ``v`` along its width; see
:mod:`saengine.substructure.loads`). A horizontal reaction acts at the column base, so about the
footing's underside it adds a moment of H times the depth from the column base down to the
underside.

Two load levels, as is usual for spread footings (ACI 318-19 13.2.6.1, 13.3.1.1):

- Bearing under the SERVICE (unfactored) allowable-stress combinations
  (:func:`saengine.substructure.loads.service_combinations`). The gross pressure includes the
  footing's weight and the soil above it; the net pressure (gross minus the overburden γ Df the
  excavation removed, Df from the ground level to the underside) is compared with the net
  allowable bearing pressure qa: the foundation's own override, else the project's override,
  else the soil report's at the footing's position, founding level and size.
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

Strip footings under walls are designed per metre of wall across their width; strip footings
under columns (a column line, with or without walls) as a rigid continuous footing, like a
combined footing. Tie beams between footings take the strut-tie force of BNBC 2020 Part 6
Sec 1.8.5.2 (b): 10 % of the larger footing or column load, in tension or compression, and the
moment and shear of a given differential settlement between their ends.

Units: mm, N, N·mm and MPa inside; reported in kN, kN·m/m, kPa, mm²/m.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from saengine.design.check import _check
from saengine.design.rc import PHI_SHEAR, STEEL_E, beta1, phi_axial_flexure
from saengine.library.objects import BarMesh
from saengine.library.settings import Foundation
from saengine.substructure.loads import column_action, combine

G = 9.80665
#: The least share of a footing's base in contact under a service combination before it is
#: reported as a stability failure (close to overturning) rather than as a high bearing
#: pressure: a limit of practice, not a clause of BNBC 2020 or ACI 318.
MIN_CONTACT = 0.25
#: A service combination with wind or earthquake (its name names the case: WX, WTY, EX...).
LATERAL = re.compile(r"\b[\d.]*(W|E)T?[XY]\b")

SHALLOW_METHOD = [
    (
        "Footings (isolated, combined and strip): the support reactions of the columns and "
        "walls they carry, reversed, in the footing's axes; a horizontal reaction adds H times "
        "the depth from the column base to the footing's underside. Columns: rectangles as "
        "drawn, circles as the square of the same area (ACI R13.2.7.1)."
    ),
    (
        "Bearing under the allowable-stress combinations of BNBC 2020 Part 6 2.7.2 "
        "(ASCE 7-05 2.4.1) for nominal wind: D, D + L + Lr (enveloping BNBC D + L, D + Lr and "
        "D + 0.75L + Lr), D + W, "
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
        "qa of each footing: its own override in 9 Substructure, else the override of Project "
        "Settings → Foundation; otherwise, when 1 Soil Report has boreholes, its net allowable "
        "pressure for that footing (saengine.soil.allowable_bearing): the lowest of the "
        "boreholes within 10 m of the footing's centre (else the nearest; none when one of them "
        "gives none), for its B × L at its founding level (Df from the borehole's ground "
        "level); each footing's check says where its qa came from. That qa is net of the "
        "overburden at the founding level below the borehole's ground: the net pressure then "
        "takes off that overburden (or γ Df below the finished ground when it is less), so "
        "fill above the borehole's ground stays a load."
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
        "footings. Effective depths to the centroid of each direction's bars (ACI 2.2), the X "
        "bars the outer layer and the Y bars on them, as in slabs: dX = thickness - cover - "
        "dbX/2, dY = thickness - cover - dbX - dbY/2 (the top mesh likewise from the top "
        "face); flexure and one-way shear in each direction take its own layer's d, punching "
        "and the transverse strips the mean of the two (ACI 22.6.2.1). Minimum reinforcement "
        "0.0018 Ag (ACI 7.6.1.1). Development lengths are not checked."
    ),
    (
        "Strip footings (local x along the path, straight paths only): under walls alone, per "
        "metre of wall: the wall's reactions over its length on the strip (each wall's total "
        "as a uniform line load), its eccentricity from the strip's centre line and its base "
        "moment across; bearing, one-way shear at d from the wall face and flexure at the "
        "wall face across the strip (ACI 13.2.7.1, 13.2.7.2) against the Y bars, minimum steel "
        "both ways. Under columns (with or without walls): a rigid continuous footing designed "
        "like a combined footing, the walls on it as loads spread over their length (no "
        "punching at walls); a long strip on soft soil is better analysed as a beam on an "
        "elastic foundation."
    ),
    (
        "Tie beams: BNBC 2020 Part 6 Sec 1.8.5.2 (seismic zones 2, 3 and 4): the strut ties "
        "between footings resist in tension or compression at least 10 % of the larger "
        "footing or column load (here the largest factored compression of either foundation, "
        "all its columns and walls together, or of any one column on them), unless friction "
        "and passive soil resistance give equivalent "
        "restraint; φPn in tension φ fy As (φ = 0.9) and in compression 0.80 φ P0 (φ = 0.65, "
        "a short member braced by the soil). Sec 8.3.11.3 (b): the smallest cross-section "
        "dimension at least the clear spacing between the connected columns / 20, need not "
        "exceed 450 mm (as in ACI 318-19 18.13.3). A given differential settlement Δ between "
        "the ends adds M = 6 E (0.35 Ig) Δ / L² and V = 2M / L (both ends fixed; 0.35 Ig per "
        "ACI 318-19 Table 6.6.3.1.1), checked with the axial force on the interaction "
        "surface and for shear (ACI Table 22.5.5.1, Vc reduced by Nu / (6 Ag) bw d for the "
        "tie force in tension, not below zero)."
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
    """A column standing on a footing, in the footing's axes [mm]; or a piece of a wall on a
    strip footing (``punching`` False: a load spread over ``cu`` x ``cv``)."""

    id: str
    u: float
    v: float
    cu: float  # column side along u
    cv: float  # along v
    arm: float = 0.0  # from the footing's underside up to the column base
    punching: bool = True


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
    #: Integrator glue: the foundation's punching studs or stirrups
    #: (``objects.PunchingReinforcement``) or None (saengine.design.punching).
    punching_reinforcement: Any = None

    def depths(self, face: str = "bottom") -> dict[str, float]:
        """Effective depth [mm] of each direction's bars of a ``face``, by axis ("u" for the X
        bars, "v" for the Y bars): to the centroid of that layer (ACI 318-19 2.2), the X bars
        the outer layer and the Y bars on them, as in slabs (:func:`saengine.design.slab.
        layers_of`). A direction without bars takes the other layer's depth (the cover depth
        without any bars)."""
        bottom = face == "bottom"
        outer, inner = (self.bottom_x, self.bottom_y) if bottom else (self.top_x, self.top_y)
        base = self.thickness - self.cover
        d_outer = base - outer.dia / 2 if outer else None
        d_inner = base - (outer.dia if outer else 0.0) - inner.dia / 2 if inner else None
        return {
            "u": d_outer if d_outer is not None else (d_inner if d_inner is not None else base),
            "v": d_inner if d_inner is not None else (d_outer if d_outer is not None else base),
        }

    @property
    def d(self) -> float:
        """Effective depth for two-way shear: the mean of the two bottom layers' (ACI
        22.6.2.1)."""
        depths = self.depths("bottom")
        return (depths["u"] + depths["v"]) / 2


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
    column's load and its moment across (ACI 336.2R practice). A piece of a wall (no
    punching) spans across over its own length: per length of wall."""
    d = spec.d if column.punching else 0.0
    span = spec.length if long_axis == "u" else spec.width
    s, side = (column.u, column.cu) if long_axis == "u" else (column.v, column.cv)
    lo, hi = max(s - side / 2 - d / 2, -span / 2), min(s + side / 2 + d / 2, span / 2)
    if long_axis == "u":
        strip = replace(spec, length=hi - lo, columns=[replace(column, u=0.0)])
        return strip, [np.array([float(load[0]), float(load[1]), 0.0])]
    strip = replace(spec, width=hi - lo, columns=[replace(column, v=0.0)])
    return strip, [np.array([float(load[0]), 0.0, float(load[2])])]


@dataclass
class Bearing:
    """The net allowable bearing pressure of one footing and where it came from."""

    qa: float | None  # [kPa]; None: no bearing check
    source: str  # "override", "soilReport", "settings" (no soil report) or "none"
    note: str  # where qa came from (or why there is none), for the check's note
    # From the soil report: the total overburden at the founding level that qa is net of [kPa],
    # the ground level of the borehole it is measured from [mm] and that borehole's id.
    overburden: float | None = None
    ground_level: float | None = None
    borehole: str | None = None


def manual_bearing(foundation: Foundation) -> Bearing:
    """qa from Project Settings → Foundation alone (projects without a soil report)."""
    if foundation.allowableBearing:
        return Bearing(
            foundation.allowableBearing,
            "settings",
            f"qa = {foundation.allowableBearing:g} kPa from Project Settings → Foundation",
        )
    return Bearing(None, "none", "")


def design_footing(
    spec: FootingSpec,
    service: Loads,
    strength: Loads,
    foundation: Foundation,
    dead: dict[str, float] | None = None,
    bearing: Bearing | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The checks of one footing and notes on it. ``dead`` gives, per strength combination,
    the factor on the weight of the footing and the soil above it (its dead-load factor;
    1.0 when not given). ``bearing`` is the footing's qa and its source (see
    :func:`footing_bearing`); without it, the qa of ``foundation`` (:func:`manual_bearing`)."""
    if bearing is None:
        bearing = manual_bearing(foundation)
    notes: list[str] = []
    checks: list[dict[str, Any]] = []
    length, width, h = spec.length, spec.width, spec.thickness

    # ── bearing (service) ──
    gamma = foundation.soilUnitWeight * 1e-6  # N/mm³
    cover_depth = max(0.0, foundation.groundLevel - spec.elevation)
    founding = max(0.0, foundation.groundLevel - (spec.elevation - h))
    own_weight = spec.unit_weight * h + gamma * cover_depth  # N/mm² of base
    overburden = gamma * founding
    overburden_note = f"net = gross - γ Df = gross - {overburden * 1e3:.0f} kPa"
    if bearing.overburden is not None:
        # qa from the soil report is net of the overburden at Df below the borehole's ground:
        # take off no more than that. Fill above the borehole's ground stays a load (it was not
        # there when the soil was tested); a finished ground below it (a cut) removes less.
        soil_overburden = bearing.overburden / 1e3
        overburden = min(overburden, soil_overburden)
        overburden_note = f"net = gross - {overburden * 1e3:.1f} kPa, the overburden " + (
            f"at the founding level below {bearing.borehole}'s ground, which qa is net of"
            if overburden == soil_overburden
            else "γ Df below the finished ground (less than the soil report's "
            f"{soil_overburden * 1e3:.1f} kPa below {bearing.borehole}'s ground)"
        )
        if bearing.ground_level is not None:
            difference = foundation.groundLevel - bearing.ground_level
            if difference > 100:
                notes.append(
                    f"{spec.id}: the finished ground (Project Settings → Foundation, "
                    f"{foundation.groundLevel / 1e3:+.2f} m) is {difference / 1e3:.2f} m above "
                    f"{bearing.borehole}'s ground ({bearing.ground_level / 1e3:+.2f} m): the "
                    "fill above the borehole's ground is taken as a load on the soil"
                )
            elif difference < -100:
                notes.append(
                    f"{spec.id}: the finished ground (Project Settings → Foundation, "
                    f"{foundation.groundLevel / 1e3:+.2f} m) is {-difference / 1e3:.2f} m below "
                    f"{bearing.borehole}'s ground ({bearing.ground_level / 1e3:+.2f} m): qa "
                    "from the soil report assumes the soil removed by the cut is still there; "
                    "check qa at the finished level"
                )
    worst: tuple[float, float, str, str] | None = None  # (utilisation, q net, combination, note)
    qa = bearing.qa / 1e3 if bearing.qa else None
    # The resultant outside the base or the footing lifted off: reported as their own checks,
    # with the eccentricity against the half side (the bearing check takes the other cases).
    outside: tuple[float, float, float, str, str] | None = None  # (ratio, e, half, name, note)
    uplift: tuple[float, str] | None = None  # (upward force N, name)
    least: tuple[float, str, str] | None = None  # (share of the base in contact, name, note)
    lifted: tuple[float, str] | None = None  # gravity only: (share in contact, name)
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
            if pressure.state == "partial" and pressure.contact < 0.995:
                note += f"; partial contact: only {pressure.contact:.0%} of the base"
                if not LATERAL.search(name) and (lifted is None or pressure.contact < lifted[0]):
                    lifted = (pressure.contact, name)
                if least is None or pressure.contact < least[0]:
                    least = (pressure.contact, name, note)
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
    if least is not None and least[0] < MIN_CONTACT:
        share, name, note = least
        checks.append(
            _check(
                "Base in contact (service, stability)",
                share * 100,
                MIN_CONTACT * 100,
                "%",
                name,
                f"{note}: the footing is close to overturning and the bearing pressure on the "
                f"small part in contact is not meaningful; at least {MIN_CONTACT:.0%} of the base "
                "should stay in contact: enlarge the footing, deepen it or tie it",
                utilisation=MIN_CONTACT / max(share, 1e-6),
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
        note += f"; {overburden_note}"
        if qa:
            checks.append(
                _check(
                    "Bearing (service)",
                    net * 1e3 if math.isfinite(net) else 0.0,
                    qa * 1e3,
                    "kPa",
                    name,
                    f"{note}; {bearing.note}" if bearing.note else note,
                    utilisation=utilisation,
                )
            )
        else:
            shown = f"net pressure {net * 1e3:.0f} kPa" if math.isfinite(net) else "no bearing"
            why = (
                bearing.note
                if bearing.note
                else "enter the net allowable bearing pressure qa in 1 Soil Report (boreholes) "
                "or as the override in Project Settings → Foundation"
            )
            notes.append(
                f"{spec.id}: bearing not checked: {why}; governing {name}: {shown}, {note}"
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
    # Integrator glue: per column, every strength combination's punching demand, for the shear
    # reinforcement of saengine.design.punching where the concrete alone is not enough.
    punch_demands: dict[str, list[tuple[str, float, float, float, Any]]] = {}

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
        strip_of: ColumnBase | None = None,
    ) -> None:
        """One-way shear and flexure of ``beam_spec`` as a beam along ``axis``; ``strip_of`` is
        the column (or wall piece) of a transverse strip of a combined footing."""
        label = labels[axis]
        shear, moment, point, span = _beam(beam_spec, pressure, loads, axis, weight)
        across = beam_spec.width if axis == "u" else beam_spec.length
        bottom, top = meshes[axis]
        d = beam_spec.depths("bottom")[axis]  # this direction's own layer
        if strip_of is None:
            where = ""
        elif strip_of.punching:
            where = (
                f"transverse strip under {strip_of.id}, b = c + d = {across:.0f} mm (ACI 336.2R); "
            )
        else:
            where = f"under wall {strip_of.id.split('#')[0]}, per metre of wall; "

        # Sections inside a column's footprint are not critical. A wall piece is a load spread
        # along the strip: along it the sections within the wall stay (its share of the line
        # load is in V(s) and M(s)); across the strip the wall is as solid as a column.
        solid = [
            (lo, hi)
            for (lo, hi, _, _), c in zip(point, beam_spec.columns, strict=True)
            if c.punching or axis != long_axis
        ]

        def inside(s: float) -> bool:
            return any(lo + 1e-6 < s < hi - 1e-6 for lo, hi in solid)

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
            # Under a wall: per metre of wall.
            scale, unit = (
                (1000 / across, "kN/m") if strip_of and not strip_of.punching else (1.0, "kN")
            )
            keep(
                f"One-way shear {label}",
                vu / capacity if capacity > 0 else math.inf,
                vu * scale / 1e3,
                capacity * scale / 1e3,
                unit,
                name,
                f"{where}at {label.lower()} = {at:.0f} mm, d = {d:.0f} mm, ρw = {rho:.4f}, "
                f"λs = {size_factor(d):.2f}, b = {across:.0f} mm",
            )

        # Flexure at the faces (ACI 13.2.7.1) and along the span.
        faces = [s for lo, hi, _, _ in point for s in (lo, hi) if -span / 2 < s < span / 2]
        samples = [s for s in np.linspace(-span / 2, span / 2, 241)[1:-1] if not inside(float(s))]
        stations = [*faces, *map(float, samples)]
        moments = [(moment(s), s) for s in stations]
        sag = max(moments, default=(0.0, 0.0))
        hog = min(moments, default=(0.0, 0.0))
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
            d_top = spec.depths("top")[axis]
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
                    axis_checks(strip_spec, strip_pressure, strip_loads, axis, weight, name, column)

        # Punching at d/2 around each column (ACI 22.6, 8.4.4.2.3).
        for column, f in zip(spec.columns, loads, strict=True):
            if not column.punching:
                continue
            pu, cu_moment, cv_moment = float(f[0]), float(f[1]), float(f[2])
            punch_demands.setdefault(column.id, []).append(
                (
                    name,
                    pu,
                    cu_moment,
                    cv_moment,
                    lambda a0, a1, b0_, b1_, p=pressure, w=weight: (
                        p.over(a0, a1, b0_, b1_) - w * (a1 - a0) * (b1_ - b0_)
                    ),
                )
            )
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
        *(f"Punching at {c.id}" for c in spec.columns if c.punching),
        "One-way shear X",
        "One-way shear Y",
        "Flexure X (bottom)",
        "Flexure Y (bottom)",
        "Flexure between columns (top)",
        "Flexure X (top)",
        "Flexure Y (top)",
    ]
    reinforced = _punching_reinforcement(spec, governing, punch_demands, notes)
    checks += [
        reinforced.get(name) or _kept(name, governing[name]) for name in order if name in governing
    ]

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
    # Reported only, after the checks that count.
    if lifted is not None:
        share, name = lifted
        checks.append(
            _check(
                "Full contact under gravity (service)",
                share * 100,
                100.0,
                "%",
                name,
                f"under gravity alone only {share:.0%} of the base presses on the soil (the "
                "resultant lies outside the kern): the footing tilts under its sustained load. "
                "Reported only; the sizing assistant keeps the whole base in contact under gravity",
                flag=True,
                utilisation=1.0 / max(share, 1e-6),
            )
        )
    return checks, notes


def _punching_reinforcement(
    spec: FootingSpec,
    governing: dict[str, tuple[float, float, float, str, str, str]],
    demands: dict[str, list[tuple[str, float, float, float, Any]]],
    notes: list[str],
) -> dict[str, dict[str, Any]]:
    """Integrator glue: the punching checks of the columns whose concrete alone is not enough
    (or whose foundation gives studs or stirrups) redone with the shear reinforcement of
    :func:`saengine.design.punching.footing_punching`: the given layout checked, else one
    proposed, over every strength combination."""
    from saengine.design import punching

    given = spec.punching_reinforcement
    out: dict[str, dict[str, Any]] = {}
    for column in spec.columns:
        name = f"Punching at {column.id}"
        if name not in governing or not demands.get(column.id):
            continue
        if governing[name][0] <= 1.0 and given is None:
            continue
        kind = given.kind if given is not None else "studs"
        fyt = (given.fyt if given is not None else None) or (
            punching.STUD_FY if kind == "studs" else min(spec.fy, 420.0)
        )
        provided = None
        if given is not None:
            provided = punching.ShearReinforcement(
                kind,
                float(given.dia),
                int(given.perLine),
                int(given.lines),
                float(given.firstLine),
                float(given.spacing),
                float(fyt),
            )
        bars = [m.dia for m in (spec.bottom_x, spec.bottom_y) if m is not None]

        def run(
            layout: Any,
            column: Any = column,
            kind: str = kind,
            fyt: float = fyt,
            bars: list[float] = bars,
        ) -> Any:
            return punching.footing_punching(
                column.u,
                column.v,
                column.cu,
                column.cv,
                spec.length,
                spec.width,
                spec.d,
                spec.fc,
                demands[column.id],
                kind=layout.kind if layout is not None else kind,
                fyt=layout.fyt if layout is not None else fyt,
                thickness=spec.thickness,
                covers=(spec.cover, 50.0),
                flexural_bar=max(bars, default=16.0),
                provided=layout,
            )

        try:
            result = run(provided)
        except (ValueError, ArithmeticError) as error:
            notes.append(f"{spec.id}: punching reinforcement at {column.id} not designed: {error}")
            continue
        if result is not None:
            # Re-checkable with another layout, and a fresh proposal where the given one fails
            # (the design mode's one layout per footing, saengine.design.proposal).
            out[name] = punching.recheckable(result.check(name), name, run, spec.fy, provided)
    return out


def _kept(name: str, value: tuple[float, float, float, str, str, str]) -> dict[str, Any]:
    utilisation, demand, capacity, unit, combination, note = value
    return _check(name, demand, capacity, unit, combination, note, utilisation=utilisation)


# ─────────────────────────────────────── allowable bearing ───────────────────────────────────────


class SoilBearing:
    """qa of each footing from the soil report (``01 Soil Report/soil-report.json``), with the
    override of Project Settings → Foundation (and a foundation's own) taking precedence.
    ``factor_of_safety`` replaces the soil report's factor of safety on the bearing capacity.
    """

    def __init__(
        self,
        soil_text: str | None,
        foundation: Foundation,
        factor_of_safety: float | None = None,
    ) -> None:
        from saengine.soil.report import parse

        if factor_of_safety is not None and soil_text and soil_text.strip():
            soil_text = _with_factor_of_safety(soil_text, factor_of_safety)
        self.text = soil_text
        self.foundation = foundation
        self.problems: list[str] = []
        self.boreholes = 0
        self.method = ""
        if soil_text and soil_text.strip():
            report = parse(soil_text)
            if isinstance(report, list):
                self.problems = report
            else:
                from saengine.soil.bearing import method_text

                self.boreholes = len(report.boreholes)
                self.method = method_text(report.design)

    @property
    def used(self) -> bool:
        """Whether the soil report gives (or would give, but for the override) qa."""
        return self.boreholes > 0

    def notes(self) -> list[str]:
        """What the footing notes say once about the soil report."""
        if self.problems:
            return [
                "The soil report has errors, so qa is not taken from it ("
                + "; ".join(self.problems[:3])
                + ("; …" if len(self.problems) > 3 else "")
                + ")."
            ]
        if self.used and not self.foundation.allowableBearing:
            return [f"Allowable bearing pressures from 1 Soil Report: {self.method}"]
        return []

    def at(
        self,
        x: float,
        y: float,
        founding_level: float,
        b: float,
        l_: float,
        override: float | None = None,
        owner: str | None = None,
    ) -> Bearing:
        """qa of a footing B × L [mm] at plan position (x, y) founded at ``founding_level``
        (project datum, mm); ``override`` [kPa] is the footing's own (``owner`` its id)."""
        if override:
            return Bearing(
                override,
                "override",
                f"qa = {override:g} kPa, the override of {owner} in 9 Substructure",
            )
        override = self.foundation.allowableBearing
        if not self.used:
            return manual_bearing(self.foundation)
        from saengine.soil.report import allowable_bearing

        found = allowable_bearing(self.text or "", None, x, y, founding_level, b, l_)
        soil_qa = found.get("qa_kpa")
        where = str(found.get("note", "")).rstrip(".")
        if override:
            here = (
                f"; 1 Soil Report gives {soil_qa:.0f} kPa here ({where})"
                if soil_qa is not None
                else ""
            )
            return Bearing(
                override,
                "override",
                f"qa = {override:g} kPa, the override in Project Settings → Foundation{here}",
            )
        if soil_qa is None:
            reason = where or "the soil report gives no allowable pressure here"
            reason = reason.removeprefix("No allowable pressure: ")
            return Bearing(
                None,
                "none",
                f"1 Soil Report gives no qa here ({reason}); enter the override qa in Project "
                "Settings → Foundation, or the missing soil data",
            )
        where = re.sub(r"; governed by [^;]*$", "", where)
        governs = "settlement" if found.get("qa_settlement") == soil_qa else "shear"
        return Bearing(
            float(soil_qa),
            "soilReport",
            f"qa = {soil_qa:.1f} kPa from 1 Soil Report: {where} (shear "
            f"{_kpa(found.get('qa_shear'))}, settlement {_kpa(found.get('qa_settlement'))}: "
            f"{governs} governs)",
            _float(found.get("overburden")),
            _float(found.get("groundLevel")),
            found.get("borehole"),
        )


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


def _kpa(value: Any) -> str:
    return "–" if value is None else f"{float(value):.1f} kPa"


def _with_factor_of_safety(soil_text: str, factor_of_safety: float) -> str:
    """The soil report's text with its factor of safety on the bearing capacity replaced."""
    import json

    try:
        data = json.loads(soil_text)
    except ValueError:
        return soil_text
    if not isinstance(data, dict) or "boreholes" not in data:
        return soil_text
    design = data.setdefault("design", {})
    if isinstance(design, dict):
        design["factorOfSafety"] = factor_of_safety
    return json.dumps(data)


# ──────────────────────────────── foundations of the substructure ─────────────────────────────────


@dataclass
class Placed:
    """A footing of the substructure set up for :func:`design_footing`: the spec, the support
    node under each of its columns (and wall pieces), its plan centre and axes."""

    spec: FootingSpec
    nodes: list[int]
    center: np.ndarray  # [x, y] mm
    axis_u: np.ndarray
    axis_v: np.ndarray
    founding_level: float
    notes: list[str] = field(default_factory=list)


def _wall_pieces(
    ctx: Any,
    wall: Any,
    base: Any,
    center: np.ndarray,
    axis_u: np.ndarray,
    axis_v: np.ndarray,
    founding: float,
) -> list[tuple[ColumnBase, int]]:
    """The support nodes of a wall along a strip footing, each a piece of the wall over its
    tributary length (half the distance to its neighbours)."""
    from saengine.library.objects import Wall
    from saengine.substructure.context import Skip

    wall_type = ctx.types.get(wall.type)
    if not isinstance(wall_type, Wall):
        raise Skip(f"{wall.id}: unknown wall type '{wall.type}'")
    along = np.array([*wall.end, 0.0]) - np.array([*wall.start, 0.0])
    length = float(np.linalg.norm(along))
    if length <= 0 or abs(float(along @ axis_v)) / length > math.sin(math.radians(1)):
        raise Skip(f"{wall.id} does not run along the strip")
    start = np.array([*wall.start, 0.0])
    s = [float((xyz - start) @ along) / length for _, xyz in base.nodes]
    sign = 1.0 if float(along @ axis_u) >= 0 else -1.0
    pieces = []
    for k, (node, xyz) in enumerate(base.nodes):
        lo = (s[k] + s[k - 1]) / 2 if k > 0 else s[k]
        hi = (s[k] + s[k + 1]) / 2 if k + 1 < len(s) else s[k]
        if hi - lo <= 0:
            continue
        offset = np.array([xyz[0] - center[0], xyz[1] - center[1], 0.0])
        mid = (lo + hi) / 2 - s[k]  # the piece's centre from its node, along the wall
        pieces.append(
            (
                ColumnBase(
                    f"{wall.id}#{k + 1}",
                    float(offset @ axis_u) + sign * mid,
                    float(offset @ axis_v),
                    hi - lo,
                    wall_type.thickness,
                    max(wall.bottom - founding, 0.0),
                    punching=False,
                ),
                node,
            )
        )
    return pieces


def place_footing(ctx: Any, foundation: Any) -> Placed:
    """The footing ``foundation`` (isolated, combined or strip) of the substructure set up for
    design: its columns (and walls) in its axes, its materials and meshes. Raises
    :class:`~saengine.substructure.context.Skip` when it cannot be designed."""
    from saengine.library.bim import ColumnElement, WallElement
    from saengine.substructure.context import Skip

    loads = ctx.require_loads()
    notes: list[str] = []
    if not foundation.columns:
        raise Skip("it carries no column or wall")
    for element_id in foundation.columns:
        if not isinstance(ctx.elements.get(element_id), ColumnElement | WallElement):
            raise Skip(f"'{element_id}' is not a column or wall of 6 BIM")
        if element_id not in loads.bases:
            raise Skip(f"{element_id} stands on no support of the analysis model")
    strip = foundation.type == "strip"
    if strip:
        path = np.array(foundation.path, dtype=float)
        direction = path[-1] - path[0]
        norm = float(np.linalg.norm(direction))
        for point in path[1:-1]:
            rel = point - path[0]
            if abs(direction[0] * rel[1] - direction[1] * rel[0]) / norm > 1:
                raise Skip(
                    "only straight strip footings are designed: split the path into straight strips"
                )
        length = norm
    else:
        length = float(foundation.length)
    width, thickness = float(foundation.width), float(foundation.thickness)
    center = ctx.center(foundation)
    axis_u, axis_v = ctx.axes(foundation)
    founding = ctx.founding_level(foundation)
    top = founding + thickness
    rotation = math.degrees(math.atan2(axis_u[1], axis_u[0]))
    columns: list[ColumnBase] = []
    nodes: list[int] = []
    # Columns first: a node a column shares with a wall's base carries both, as the column's.
    order = sorted(foundation.columns, key=lambda i: isinstance(ctx.elements.get(i), WallElement))
    for element_id in order:
        element = ctx.elements.get(element_id)
        if not isinstance(element, ColumnElement | WallElement):
            raise Skip(f"'{element_id}' is not a column or wall of 6 BIM")
        base = loads.bases.get(element_id)
        if base is None:
            raise Skip(f"{element_id} stands on no support of the analysis model")
        if isinstance(element, WallElement):
            if not strip:
                raise Skip(f"wall {element_id} can stand on a strip footing only")
            for piece, node in _wall_pieces(ctx, element, base, center, axis_u, axis_v, founding):
                if abs(piece.u) > length / 2 + 1 or abs(piece.v) + piece.cv / 2 > width / 2 + 1:
                    raise Skip(f"wall {element_id} extends beyond the strip")
                if node in nodes:
                    continue
                columns.append(piece)
                nodes.append(node)
        else:
            offset = np.array([*(np.array(element.position[:2]) - center), 0.0])
            u, v = float(offset @ axis_u), float(offset @ axis_v)
            if abs(u) > length / 2 + 1 or abs(v) > width / 2 + 1:
                raise Skip(f"{element_id} lies outside the footing")
            cu, cv, note = ctx.column_sides(element, rotation)
            if note:
                notes.append(f"{foundation.id}: {note}")
            columns.append(
                ColumnBase(element_id, u, v, cu, cv, max(element.bottom - founding, 0.0))
            )
            nodes.append(base.nodes[0][0])
        if element.bottom < top - 1:
            notes.append(
                f"{foundation.id}: the base of {element_id} ({element.bottom / 1e3:+.2f} m) lies "
                f"below the top of the footing ({top / 1e3:+.2f} m)"
            )
    concrete = ctx.concrete(foundation.material, foundation.id)
    reinforcement = foundation.reinforcement
    if reinforcement is None:
        raise Skip("no reinforcement")
    bars = ctx.rebar(reinforcement.material)
    if foundation.type == "isolated" and len(columns) > 1:
        notes.append(
            f"{foundation.id}: an isolated footing under {len(columns)} columns is designed as "
            "a combined footing"
        )
    density = concrete.mechanical.density or 2400.0
    spec = FootingSpec(
        id=foundation.id,
        type=foundation.type,
        footing_type=foundation.type,
        length=length,
        width=width,
        thickness=thickness,
        elevation=top,
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
        punching_reinforcement=getattr(foundation, "punchingReinforcement", None),
    )
    if min(spec.depths("bottom").values()) <= 0:
        raise Skip("the cover and bars leave no effective depth")
    return Placed(spec, nodes, center, axis_u, axis_v, founding, notes)


def footing_loads(loads: Any, placed: Placed) -> tuple[Loads, Loads]:
    """The service and strength loads ``[P, Cu, Cv]`` of each column of a placed footing."""
    zero = np.zeros(6)
    per_case = {
        case: [
            column_action(reactions.get(node, zero), c.arm, placed.axis_u, placed.axis_v)
            for c, node in zip(placed.spec.columns, placed.nodes, strict=True)
        ]
        for case, reactions in loads.cases.items()
    }
    return (
        {name: combine(per_case, factors) for name, factors in loads.service},
        {name: combine(per_case, factors) for name, factors in loads.strength},
    )


def summary(
    foundation: Any, checks: list[dict[str, Any]], members: list[str], **extra: Any
) -> dict[str, Any]:
    """A foundation's result in the report's format: the governing utilisation of the checks
    that count (``flag`` checks are reported only)."""
    counted = [c for c in checks if not c["flag"]]
    return {
        "id": foundation.id,
        "type": foundation.type,
        "columns": members,
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in counted), default=0.0),
        "ok": all(c["ok"] for c in counted),
        **extra,
    }


def design_shallow(ctx: Any, foundation: Any) -> tuple[dict[str, Any], list[str]]:
    """The checks of an isolated, combined or strip footing of the substructure: ``(result,
    notes)``, the result in the report's format (see
    :func:`saengine.substructure.report.substructure_report`). Raises
    :class:`~saengine.substructure.context.Skip` when it cannot be designed."""
    placed = place_footing(ctx, foundation)
    spec = placed.spec
    service, strength = footing_loads(ctx.loads, placed)
    bearing = ctx.soil.at(
        float(placed.center[0]),
        float(placed.center[1]),
        placed.founding_level,
        min(spec.width, spec.length),
        max(spec.width, spec.length),
        foundation.allowableBearing,
        foundation.id,
    )
    checks, notes = design_footing(
        spec, service, strength, ctx.settings.foundation, ctx.loads.dead, bearing
    )
    members = list(dict.fromkeys(c.id.split("#")[0] for c in spec.columns))
    bearing_check = next((c for c in checks if c["name"] == "Bearing (service)"), None)
    pressure = None
    if bearing_check is not None:
        pressure = {
            "net": bearing_check["demand"],
            "qa": bearing_check["capacity"],
            "combination": bearing_check["combination"],
            "source": bearing.source,
        }
    sizes = {
        "length": spec.length,
        "width": spec.width,
        "thickness": spec.thickness,
        "foundingLevel": placed.founding_level,
        "center": [round(float(placed.center[0]), 1), round(float(placed.center[1]), 1)],
        "rotation": round(math.degrees(math.atan2(placed.axis_u[1], placed.axis_u[0])), 3),
    }
    result = summary(foundation, checks, members, sizes=sizes, pressure=pressure)
    if bearing_check is None and service:
        # No qa: the footing is not checked for what sizes it, whatever its other checks say.
        result["notChecked"] = ["bearing"]
    return result, placed.notes + notes


# ─────────────────────────────────────────── tie beams ───────────────────────────────────────────


def footing_load(loads: Any, columns: list[str]) -> float:
    """The largest factored downward load [N] on a foundation carrying ``columns`` under any
    strength combination: the sum of its bases' support reactions, a node shared by two bases
    (a wall and its column) counted once."""
    nodes = {n for c in columns if c in loads.bases for n, _ in loads.bases[c].nodes}
    if not nodes:
        return 0.0
    # The support reaction Fz is the downward load the base puts on its foundation.
    return max(
        (sum(float(loads.reaction(n, f)[2]) for n in nodes) for _, f in loads.strength),
        default=0.0,
    )


def tie_force(loads: Any, ends: list[tuple[str, list[str]]]) -> tuple[float, str | None]:
    """BNBC 2020 Part 6 Sec 1.8.5.2 (b): 10 % of the larger footing or column load [N] of the
    two foundations ``ends`` (id, the columns it carries): the largest factored compression of
    a foundation (all its columns together) or of any one column; and what governs it."""
    best, which = 0.0, None
    for foundation_id, columns in ends:
        carried = [c for c in columns if c in loads.bases]
        for column in carried:
            p = loads.max_axial(column)
            if p > best:
                best, which = p, column
        if len(carried) > 1:
            p = footing_load(loads, carried)
            if p > best + 1e-6:
                best, which = p, f"{foundation_id} ({', '.join(carried)})"
    return 0.1 * best, which


def design_tie_beam(ctx: Any, tie: Any) -> tuple[dict[str, Any], list[str]]:
    """The checks of a tie beam between two foundations: the strut-tie force of BNBC 2020 Part 6
    Sec 1.8.5.2 in tension and compression, its size against Sec 8.3.11.3 (b), and the moment
    and shear of a given differential settlement. Raises
    :class:`~saengine.substructure.context.Skip` when it cannot be designed."""
    from saengine.design.rc import DesignError, InteractionSurface, section_of, shear
    from saengine.library.objects import Beam, RectangleProfile
    from saengine.library.settings import derived
    from saengine.substructure.context import Skip

    loads = ctx.require_loads()
    ends = [ctx.substructure.foundation(tie.from_), ctx.substructure.foundation(tie.to)]
    beam_type = ctx.types.get(tie.type)
    if not isinstance(beam_type, Beam):
        raise Skip(f"object type '{tie.type}' is not a beam")
    profile = beam_type.profile
    if not isinstance(profile, RectangleProfile):
        raise Skip("only rectangular tie beams are designed")
    if beam_type.reinforcement is None:
        raise Skip(f"{tie.type} has no reinforcement")
    concrete = ctx.concrete(beam_type.material, tie.id)
    bars = ctx.rebar(beam_type.reinforcement.material)
    try:
        section = section_of(
            profile,
            beam_type.reinforcement,
            concrete.concrete.fc,
            bars.steel.fy,
            bars.mechanical.E or STEEL_E,
        )
    except DesignError as error:
        raise Skip(str(error)) from error
    notes: list[str] = []
    checks: list[dict[str, Any]] = []
    force, governing = tie_force(loads, [(f.id, _carried(ctx, f)) for f in ends])
    flag = derived(ctx.settings)["zone"] == 1
    rule = "10 % of the larger footing or column load (BNBC 2020 Part 6 Sec 1.8.5.2 (b))"
    if governing is not None:
        rule += f": {governing}, {force * 10 / 1e3:.0f} kN factored"
    if flag:
        rule += "; seismic zone 1: not required by Sec 1.8.5, reported only"
    checks.append(
        _check(
            "Tie force (tension)",
            force / 1e3,
            section.phi_tension / 1e3,
            "kN",
            None,
            f"{rule}; φ fy As, φ = 0.90, As = {section.steel_area:.0f} mm²",
            flag,
        )
    )
    checks.append(
        _check(
            "Tie force (compression)",
            force / 1e3,
            section.phi_pn_max / 1e3,
            "kN",
            None,
            f"{rule}; 0.80 φ P0, φ = 0.65 (a short member braced by the soil)",
            flag,
        )
    )

    # Size: the clear spacing between the connected columns / 20, at most 450 mm.
    centres = [ctx.center(f) for f in ends]
    positions = [[(c, p) for c in f.columns if (p := ctx.position(c)) is not None] for f in ends]
    clear = float(np.linalg.norm(centres[1] - centres[0]))
    if positions[0] and positions[1]:
        (ca, a), (cb, b) = min(
            ((pa, pb) for pa in positions[0] for pb in positions[1]),
            key=lambda pair: float(np.linalg.norm(pair[1][1] - pair[0][1])),
        )
        direction = (b - a) / max(float(np.linalg.norm(b - a)), 1e-9)
        clear = float(np.linalg.norm(b - a))
        for column_id in (ca, cb):
            clear -= _half_depth(ctx, column_id, direction)
    clear = max(clear, 0.0)
    required = min(clear / 20, 450.0)
    checks.append(
        _check(
            "Size (BNBC 8.3.11.3)",
            required,
            min(profile.xDim, profile.yDim),
            "mm",
            None,
            f"smallest dimension ≥ the clear spacing {clear:.0f} mm between the columns / 20, "
            "need not exceed 450 mm (BNBC 2020 Part 6 Sec 8.3.11.3 (b))",
            flag,
        )
    )

    if tie.settlement:
        e = concrete.mechanical.E or 4700 * math.sqrt(concrete.concrete.fc)
        inertia = 0.35 * profile.xDim * profile.yDim**3 / 12
        length = float(np.linalg.norm(centres[1] - centres[0]))
        if length <= 0:
            raise Skip("its two foundations are at the same place")
        moment = 6 * e * inertia * tie.settlement / length**2
        shear_force = 2 * moment / length
        surface = InteractionSurface(section)
        results = [(surface.check(p, moment, 0.0), p) for p in (-force, force)]
        check, p = max(results, key=lambda item: item[0].utilisation)
        checks.append(
            _check(
                "Flexure from settlement",
                moment / 1e6,
                check.phi_mn / 1e6,
                "kN·m",
                None,
                f"Δ = {tie.settlement:g} mm over L = {length:.0f} mm: M = 6 E (0.35 Ig) Δ / L², "
                f"E = {e:.0f} MPa, with {'tension' if p < 0 else 'compression'} "
                f"{abs(p) / 1e3:.0f} kN",
                utilisation=check.utilisation,
            )
        )
        transverse = beam_type.reinforcement.transverse
        try:
            capacity = shear(
                section,
                transverse.dia if transverse else None,
                transverse.legs if transverse else 2,
                transverse.spacing if transverse else None,
            )
        except DesignError as error:
            notes.append(f"{tie.id}: shear not checked: {error}")
        else:
            # The tie force in tension at the same time lowers Vc by Nu / (6 Ag) bw d (ACI
            # 318-19 Table 22.5.5.1, Nu negative in tension), Vc not less than zero.
            area = profile.xDim * profile.yDim
            reduction = force / (6 * area) * profile.xDim * capacity.d
            vc = max(capacity.vc - reduction, 0.0)
            phi_vn = PHI_SHEAR * (vc + capacity.vs)
            checks.append(
                _check(
                    "Shear from settlement",
                    shear_force / 1e3,
                    phi_vn / 1e3,
                    "kN",
                    None,
                    f"V = 2M / L, d = {capacity.d:.0f} mm; with the tie force {force / 1e3:.0f} "
                    f"kN in tension: Vc = {capacity.vc / 1e3:.1f} - Nu / (6 Ag) bw d = "
                    f"{vc / 1e3:.1f} kN (ACI 318-19 Table 22.5.5.1), Vs = "
                    f"{capacity.vs / 1e3:.1f} kN, φ = {PHI_SHEAR:g}",
                )
            )
    counted = [c for c in checks if not c["flag"]]
    result = {
        "id": tie.id,
        "type": "tieBeam",
        "columns": [tie.from_, tie.to],
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in counted), default=0.0),
        "ok": all(c["ok"] for c in counted),
        "force": round(force / 1e3, 2),
    }
    return result, notes


def _carried(ctx: Any, foundation: Any) -> list[str]:
    """The columns and walls a foundation carries: its own list, or for a raft without one
    every analysed column base inside its outline."""
    if foundation.columns or foundation.type != "raft" or not foundation.outline:
        return list(foundation.columns)
    from saengine.substructure.report import _inside

    loads = ctx.require_loads()
    return [
        base_id
        for base_id, base in loads.bases.items()
        if hasattr(base.element, "position") and _inside(base.element.position, foundation.outline)
    ]


def _half_depth(ctx: Any, column_id: str, direction: np.ndarray) -> float:
    """Half the extent of a column along the plan ``direction`` (a unit [x, y]) [mm]: from
    its centre to its face; 0 for a wall or an unknown profile."""
    from saengine.library.objects import CircleProfile, RectangleProfile

    element = ctx.elements.get(column_id)
    column_type = ctx.types.get(getattr(element, "type", ""))
    profile = getattr(column_type, "profile", None)
    if isinstance(profile, CircleProfile):
        return profile.radius
    if not isinstance(profile, RectangleProfile) or not hasattr(element, "rotation"):
        return 0.0
    theta = math.radians(element.rotation)
    x = abs(direction[0] * math.cos(theta) + direction[1] * math.sin(theta))
    y = abs(-direction[0] * math.sin(theta) + direction[1] * math.cos(theta))
    return min(profile.xDim / 2 / max(x, 1e-9), profile.yDim / 2 / max(y, 1e-9))

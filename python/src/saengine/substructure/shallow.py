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
combined footing. Tie beams between footings take the strut-tie force of the code pack's
``foundations.shallow.tieBeams`` (the default pack: BNBC 2020 Part 6 Sec 1.8.5.2 (b), 10 % of the
larger footing or column load), in tension or compression, and the moment and shear of a given
differential settlement between their ends.

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
from saengine.substructure.loads import column_action

G = 9.80665
#: The least share of a footing's base in contact under a service combination before it is
#: reported as a stability failure (close to overturning) rather than as a high bearing
#: pressure: SAEngine practice, not a code value, used only when the code pack has no
#: overturning rule for shallow foundations (the default pack's FS 1.5 replaces it).
MIN_CONTACT = 0.25
#: A service combination with wind or earthquake (its name names the case: WX, WTY, EX...).
LATERAL = re.compile(r"\b[\d.]*(W|E)T?[XY]\b")

_SHALLOW_METHOD = [
    (
        "Footings (isolated, combined and strip): the support reactions of the columns and "
        "walls they carry, reversed, in the footing's axes; a horizontal reaction adds H times "
        "the depth from the column base to the footing's underside. Columns: rectangles as "
        "drawn, circles as the square of the same area (ACI R13.2.7.1)."
    ),
    (
        "Bearing under the allowable-stress combinations of ASCE 7-05 2.4.1 for nominal wind: "
        "D, D + L + Lr (enveloping D + L, D + Lr and D + 0.75L + Lr), D + W, "
        "D + 0.75L + 0.75Lr + 0.75W, 0.6D + W, D + 0.7E, D + 0.75L + 0.75Lr + 0.525E, "
        "0.6D + 0.7E; W and E in ±X and ±Y (with strength-level wind, ASCE 7-16 2.4.1: "
        "0.6W and 0.45W). Gross pressure q = P/A ± Mx/Sx ± My/Sy with the footing's weight "
        "and the soil above it inside the kern; beyond it partial contact, "
        "qmax = 2P / (3 B (L/2 - e)) for one eccentricity and the exact no-tension plane for "
        "two. The net pressure (gross minus γ Df, Df from the ground level to the underside) "
        "is compared with the net allowable bearing pressure qa. A code pack with rules for "
        "shallow foundations replaces these combinations by its own for the bearing (the "
        "default pack: D + L, D + L + W, D + L + E and 0.9D + buoyancy, L the normal live "
        "load reduced as in the column design when live load reduction is on), increases qa "
        "with wind or earthquake by its lateral increase, and checks overturning (FS = B / 2e) "
        "and sliding (μ V / H, no passive resistance; reported only for a footing tied to "
        "others, the building's sliding counting) under its stability combinations with the "
        "dead load resisting, the resultant within B/6 (reported only), the founding depth "
        "(every footing, and exterior footings by the soil at the base), the depth above the "
        "bottom bars, the distance to a slope face, the bearing at each column's base and the "
        "bars across it, and the settlement of each footing (the settlement combination of the "
        "soil at its base, at the nearest borehole) with the differential settlement and "
        "angular distortion between neighbouring footings against its permissible values for "
        "the type of structure. Without such rules, a footing keeping less than "
        "MIN_CONTACT of its base in contact fails as close to overturning (SAEngine practice)."
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
        "Sloped and stepped isolated footings (ACI 318-19 13.2.7.3: the depth and location of "
        "the reinforcement satisfy the design requirements at every section): the full "
        "thickness over the flat top or upper step round the column, the edge thickness at the "
        "edges (sloped: the top's hipped planes in between; stepped: the lower step outside "
        "the upper). Every section takes its own concrete: one-way shear sums 0.66 λs ρw^(1/3) "
        "√f'c b d over strips across the section with their own d (at d from the column faces, "
        "at d from the step for a stepped footing, and along the slope); flexure takes the "
        "section's greatest d and its compression face only as wide as the top there; punching "
        "at d/2 round the column with the depth at that section, and for a stepped footing "
        "also at d/2 round the upper step with the lower step's d. The footing's weight is its "
        "true volume (soil fills the rest of the depth)."
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
]


def _tie_beam_method() -> str:
    """The tie beams' method line, with the pack in force's rules and clauses."""
    from saengine.substructure import shallow_rules

    ties = _tie_rules()
    common = (
        "A given differential settlement Δ between the ends adds M = 6 E (0.35 Ig) Δ / L² and "
        "V = 2M / L (both ends fixed; 0.35 Ig per ACI 318-19 Table 6.6.3.1.1), checked with the "
        "axial force on the interaction surface and for shear (ACI Table 22.5.5.1, Vc reduced by "
        "Nu / (6 Ag) bw d for the tie force in tension, not below zero)."
    )
    if ties is None:
        return (
            "Tie beams: "
            + shallow_rules.not_covered("the strut-tie force and size")
            + ". "
            + common
        )
    clause = shallow_rules.cite("shallow.tieBeams", shallow_rules.code_name())
    size = shallow_rules.cite("shallow.tieBeams.size")
    zones = ", ".join(str(z) for z in ties.zones[:-1]) + (
        f" and {ties.zones[-1]}" if len(ties.zones) > 1 else str(ties.zones[0])
    )
    return (
        f"Tie beams: {clause} (seismic zones {zones}): the strut ties between footings resist "
        f"in tension or compression at least {ties.forceShare * 100:g} % of the larger footing "
        "or column load (here the largest factored compression of either foundation, all its "
        "columns and walls together, or of any one column on them), unless friction and passive "
        "soil resistance give equivalent restraint; φPn in tension φ fy As (φ = 0.9) and in "
        "compression 0.80 φ P0 (φ = 0.65, a short member braced by the soil)."
        + (f" {size}:" if size else "")
        + " the smallest cross-section dimension at least the clear spacing between the "
        f"connected columns / {ties.spanDivisor:g}, need not exceed {ties.sizeMax:g} mm (as in "
        f"ACI 318-19 18.13.3). {common}"
    )


def shallow_method() -> list[str]:
    """The footings' method lines, with the pack in force's tie beam rules."""
    return [*_SHALLOW_METHOD, _tie_beam_method()]


def __getattr__(name: str) -> Any:
    if name == "SHALLOW_METHOD":  # the former constant, with the pack in force
        return shallow_method()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    #: Isolated footings: "flat", "sloped" or "stepped" (``Foundation.section``), the edge
    #: thickness and the plan of the full-thickness top, centred on the column [mm].
    section: str = "flat"
    edge_thickness: float | None = None
    top_length: float | None = None
    top_width: float | None = None

    @property
    def profiled(self) -> bool:
        """Whether the footing is sloped or stepped (one column, thinner at the edges)."""
        return (
            self.section in ("sloped", "stepped")
            and self.edge_thickness is not None
            and self.edge_thickness < self.thickness
            and len(self.columns) == 1
        )

    def top_plan(self) -> tuple[float, float, float, float]:
        """(u0, u1, v0, v1) of the flat top or upper step, centred on the column, in the
        footing's plan."""
        c = self.columns[0]
        lt = min(self.top_length or self.length, self.length)
        bt = min(self.top_width or self.width, self.width)
        u0 = min(max(c.u - lt / 2, -self.length / 2), self.length / 2 - lt)
        v0 = min(max(c.v - bt / 2, -self.width / 2), self.width / 2 - bt)
        return u0, u0 + lt, v0, v0 + bt

    def thickness_at(self, u: Any, v: Any) -> Any:
        """Thickness [mm] at plan points (u, v) (arrays allowed): the full thickness on the top,
        the edge thickness outside a stepped footing's upper step, and between, on a sloped one,
        the hipped planes from the top's edges down to the footing's edges."""
        if not self.profiled:
            return np.full(np.broadcast(u, v).shape, self.thickness)
        u, v = np.asarray(u, dtype=float), np.asarray(v, dtype=float)
        u0, u1, v0, v1 = self.top_plan()
        h, he = self.thickness, float(self.edge_thickness)  # type: ignore[arg-type]
        if self.section == "stepped":
            on_top = (u >= u0 - 1e-6) & (u <= u1 + 1e-6) & (v >= v0 - 1e-6) & (v <= v1 + 1e-6)
            return np.where(on_top, h, he)

        def share(x: Any, lo: float, hi: float, edge: float) -> Any:
            below = np.where(lo > -edge + 1e-6, (lo - x) / max(lo + edge, 1e-6), 0.0)
            above = np.where(hi < edge - 1e-6, (x - hi) / max(edge - hi, 1e-6), 0.0)
            return np.clip(np.maximum(below, above), 0.0, 1.0)

        t = np.maximum(share(u, u0, u1, self.length / 2), share(v, v0, v1, self.width / 2))
        return h - (h - he) * t

    def mean_thickness(self) -> float:
        """Concrete volume / plan area [mm] (:meth:`saengine.library.substructure.Foundation.
        concrete_volume`'s shapes)."""
        if not self.profiled:
            return self.thickness
        lt, bt = self.top_length or self.length, self.top_width or self.width
        he = float(self.edge_thickness)  # type: ignore[arg-type]
        area = self.length * self.width
        rise = self.thickness - he
        if self.section == "stepped":
            return he + lt * bt * rise / area
        return he + rise / 6 * (area + lt * bt + (self.length + lt) * (self.width + bt)) / area

    def section_strips(self, axis: str, s: float, count: int = 41) -> tuple[np.ndarray, float]:
        """The thicknesses [mm] of ``count`` equal strips across the section at ``s`` along
        ``axis`` and the width of each strip [mm]."""
        across = self.width if axis == "u" else self.length
        step = across / count
        t = -across / 2 + step * (np.arange(count) + 0.5)
        if axis == "u":
            return self.thickness_at(np.full(count, s), t), step
        return self.thickness_at(t, np.full(count, s)), step

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

    def moments(stations: list[float]) -> list[float]:
        """:func:`moment` at many stations. In full contact the soil pressure across the beam
        integrates to across · (a + g s), so its force and moment are polynomials in s: all
        stations at once (N-U4: the flexure scan took most of the sizing time). In partial
        contact, one station at a time."""
        if pressure.clip:
            return [moment(s) for s in stations]
        s = np.asarray(stations, dtype=float)
        g = pressure.gu if axis == "u" else pressure.gv
        a = pressure.a
        force = across * (a * (s - start) + g * (s**2 - start**2) / 2)
        first = across * (a * (s**2 - start**2) / 2 + g * (s**3 - start**3) / 3)
        part = np.maximum(s - start, 0.0)
        value = s * force - first - weight * across * part**2 / 2
        for lo, hi, p, couple in point:
            top = np.minimum(s, hi)
            value -= np.where(top > lo, p / (hi - lo) * ((s - lo) ** 2 - (s - top) ** 2) / 2, 0.0)
            value += couple * np.clip((s - lo) / (hi - lo), 0.0, 1.0)
        return [float(v) for v in value]

    return shear, moment, moments, point, span


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
    # The soil at the founding level ("cohesive" or "granular") and the water table below the
    # base [mm] (negative: above it), when the soil report gives them.
    founding_soil: str | None = None
    water_depth: float | None = None


def manual_bearing(foundation: Foundation) -> Bearing:
    """qa from Project Settings → Foundation alone (projects without a soil report)."""
    if foundation.allowableBearing:
        return Bearing(
            foundation.allowableBearing,
            "settings",
            f"qa = {foundation.allowableBearing:g} kPa from Project Settings → Foundation",
        )
    return Bearing(None, "none", "")


# ─────────────────────────────────────── sloped and stepped footings ─────────────────────────


def _profiled_shear(
    spec: FootingSpec,
    axis: str,
    d: float,
    shear: Any,
    sections: list[float],
    keep: Any,
    label: str,
    name: str,
) -> None:
    """One-way shear of a sloped or stepped footing along ``axis``: at the sections at d from
    the column faces (``sections``), at d from the upper step, and along the slope; each
    section's capacity summed over strips across it with their own d (ACI 318-19 13.2.7.3)."""
    offset = spec.thickness - d  # top face to this direction's bars
    span = spec.length if axis == "u" else spec.width
    u0, u1, v0, v1 = spec.top_plan()
    lo, hi = (u0, u1) if axis == "u" else (v0, v1)
    c = spec.columns[0]
    face_lo = (c.u - c.cu / 2) if axis == "u" else (c.v - c.cv / 2)
    face_hi = (c.u + c.cu / 2) if axis == "u" else (c.v + c.cv / 2)
    if spec.section == "stepped":
        de = float(spec.edge_thickness) - offset  # type: ignore[arg-type]
        extra = [lo - de, hi + de]
    else:
        extra = [*np.linspace(-span / 2, lo, 8)[1:-1], *np.linspace(hi, span / 2, 8)[1:-1]]
    candidates = [
        float(s)
        for s in [*sections, *extra]
        if -span / 2 < s < span / 2 and (s <= face_lo - d + 1e-6 or s >= face_hi + d - 1e-6)
    ]
    as_per_m = mesh_area(spec.bottom_x if axis == "u" else spec.bottom_y)
    best: tuple[float, float, float, float, float, float] | None = None
    for s in candidates:
        thick, step = spec.section_strips(axis, s)
        depths = thick - offset
        depths = depths[depths > 0]
        if not len(depths):
            continue
        capacity = sum(
            one_way_shear_capacity(step, float(di), as_per_m / (1000 * float(di)), spec.fc)
            for di in depths
        )
        vu = abs(shear(s))
        ratio = vu / capacity if capacity > 0 else math.inf
        if best is None or ratio > best[0]:
            best = (ratio, vu, capacity, s, float(depths.min()), float(depths.max()))
    if best is None:
        return
    ratio, vu, capacity, at, d_min, d_max = best
    keep(
        f"One-way shear {label}",
        ratio,
        vu / 1e3,
        capacity / 1e3,
        "kN",
        name,
        f"{spec.section} footing: at {label.lower()} = {at:.0f} mm, d = {d_min:.0f} to "
        f"{d_max:.0f} mm across the section, Σ 0.66 λs ρw^(1/3) √f'c b d over its strips "
        "(ACI 22.5.5.1 (c), 13.2.7.3)",
    )


def _profiled_flexure(
    spec: FootingSpec,
    axis: str,
    d: float,
    moments: list[tuple[float, float]],
    as_per_m: float,
    keep: Any,
    label: str,
    name: str,
) -> None:
    """Bottom flexure of a sloped or stepped footing along ``axis``: at each station the
    section's greatest d and a compression face as wide as the top there (ACI 318-19
    13.2.7.3), the bars across the whole width."""
    offset = spec.thickness - d
    across = spec.width if axis == "u" else spec.length
    per_m = 1000 / across
    steel = as_per_m * across / 1000
    best: tuple[float, float, float, float, float, float] | None = None
    for moment, s in moments:
        if moment <= 0:
            continue
        thick, step = spec.section_strips(axis, s)
        top = float(thick.max())
        width = step * int(np.count_nonzero(thick >= top - 1.0))
        depth = top - offset
        if steel <= 0 or depth <= 0:
            capacity = 0.0
        else:
            capacity = strip_flexure(steel * 1000 / width, depth, spec.fc, spec.fy, spec.es).phi_mn
            capacity *= width / 1000
        ratio = moment / capacity if capacity > 0 else math.inf
        if best is None or ratio > best[0]:
            best = (ratio, moment, capacity, s, depth, width)
    if best is None:
        keep(f"Flexure {label} (bottom)", 0.0, 0.0, 0.0, "kN·m/m", name, "no sagging moment")
        return
    ratio, moment, capacity, at, depth, width = best
    keep(
        f"Flexure {label} (bottom)",
        ratio,
        moment * per_m / 1e6,
        capacity * per_m / 1e6,
        "kN·m/m",
        name,
        f"{spec.section} footing: at {label.lower()} = {at:.0f} mm, d = {depth:.0f} mm, "
        f"compression face {width:.0f} mm wide (the top there), As = {steel:.0f} mm² across "
        f"{across:.0f} mm (ACI 13.2.7.3); per metre of the footing's width",
    )


def _punching_depth(spec: FootingSpec, column: ColumnBase, d: float) -> float:
    """d [mm] of the punching section at d/2 round a column of a sloped or stepped footing:
    the least depth along that section (a few fixed-point steps, the section moving in as d
    shrinks)."""
    offset = spec.thickness - d
    dp = d
    t = np.linspace(0.0, 1.0, 21)
    for _ in range(6):
        u0, u1 = column.u - column.cu / 2 - dp / 2, column.u + column.cu / 2 + dp / 2
        v0, v1 = column.v - column.cv / 2 - dp / 2, column.v + column.cv / 2 + dp / 2
        along_u, along_v = u0 + (u1 - u0) * t, v0 + (v1 - v0) * t
        us = np.concatenate([along_u, along_u, np.full(21, u0), np.full(21, u1)])
        vs = np.concatenate([np.full(21, v0), np.full(21, v1), along_v, along_v])
        inside = (np.abs(us) <= spec.length / 2) & (np.abs(vs) <= spec.width / 2)
        if not inside.any():
            return dp
        least = float(spec.thickness_at(us[inside], vs[inside]).min()) - offset
        if abs(least - dp) < 0.5:
            return least
        dp = max(min(d, least), 1.0)
    return dp


def _step_punching(
    spec: FootingSpec,
    pressure: SoilPressure,
    weight: float,
    column: ColumnBase,
    load: np.ndarray,
    name: str,
    keep: Any,
) -> None:
    """Punching at d/2 round the upper step of a stepped footing (ACI 22.6), the step as the
    loaded area and d of the lower step."""
    de = float(spec.edge_thickness) - (spec.thickness - spec.d)  # type: ignore[arg-type]
    if de <= 0:
        return
    u0, u1, v0, v1 = spec.top_plan()
    lt, bt = u1 - u0, v1 - v0
    a0, a1, b0_, b1_ = u0 - de / 2, u1 + de / 2, v0 - de / 2, v1 + de / 2
    half_l, half_w = spec.length / 2, spec.width / 2
    sides = {"u-": a0 > -half_l, "u+": a1 < half_l, "v-": b0_ > -half_w, "v+": b1_ < half_w}
    ca0, ca1 = max(a0, -half_l), min(a1, half_l)
    cb0, cb1 = max(b0_, -half_w), min(b1_, half_w)
    b0 = (sides["u-"] + sides["u+"]) * (cb1 - cb0) + (sides["v-"] + sides["v+"]) * (ca1 - ca0)
    count = sum(sides.values())
    if count < 2 or b0 <= 0:
        return
    alpha_s = {4: 40, 3: 30, 2: 20}[count]
    pu, cu_moment, cv_moment = float(load[0]), float(load[1]), float(load[2])
    inside = pressure.over(ca0, ca1, cb0, cb1) - weight * (ca1 - ca0) * (cb1 - cb0)
    vu = max(pu - inside, 0.0)
    b1u, b1v = lt + de, bt + de
    moment_u = gamma_v(b1u, b1v) * abs(cv_moment) * (b1u / 2) / polar_j(b1u, b1v, de)
    moment_v = gamma_v(b1v, b1u) * abs(cu_moment) * (b1v / 2) / polar_j(b1v, b1u, de)
    stress = vu / (b0 * de) + moment_u + moment_v
    phi_vc = PHI_SHEAR * punching_stress(lt, bt, de, b0, alpha_s, spec.fc)
    keep(
        f"Punching at the step of {column.id}",
        stress / phi_vc,
        stress * b0 * de / 1e3,
        phi_vc * b0 * de / 1e3,
        "kN",
        name,
        f"at d/2 round the upper step {lt:.0f} × {bt:.0f} mm, d = {de:.0f} mm of the lower "
        f"step, b0 = {b0:.0f} mm, vu = {stress:.2f} MPa (Vu = {vu / 1e3:.0f} kN), φvc = "
        f"{phi_vc:.2f} MPa, αs = {alpha_s}",
    )


def _stability_checks(
    spec: FootingSpec,
    stability: Loads,
    own_weight: float,
    horizontal: dict[str, float],
    tied: bool,
    kern: tuple[float, str, float, float] | None,
) -> list[dict[str, Any]]:
    """The code pack's stability checks of a footing: overturning (FS = B / 2e about its edges)
    and sliding (μ V / H) under its stability combinations, and the resultant within the kern
    (reported only)."""
    from saengine.substructure import shallow_rules

    checks: list[dict[str, Any]] = []
    worst_over: dict[str, Any] | None = None
    worst_slide: dict[str, Any] | None = None
    for name, loads in stability.items():
        total, eu, ev = _eccentricity(spec, loads, own_weight * spec.length * spec.width)
        if total <= 0:
            found = shallow_rules.rules()
            row = _check(
                "Overturning (service)",
                found.overturning if found is not None else 1.0,
                0.0,
                "FS",
                name,
                "the dead load does not hold the footing down: it lifts off",
                utilisation=99.0,
            )
        else:
            row = shallow_rules.overturning_check(name, eu, ev, spec.length, spec.width)
            share = abs(eu) / spec.length + abs(ev) / spec.width
            if kern is None or share > kern[0]:
                kern = (share, name, eu, ev)
        if row is not None and (
            worst_over is None or row["utilisation"] > worst_over["utilisation"]
        ):
            worst_over = row
        if name in horizontal:
            row = shallow_rules.sliding_check(name, horizontal[name], max(total, 0.0), tied, None)
            if row is not None and (
                worst_slide is None or row["utilisation"] > worst_slide["utilisation"]
            ):
                worst_slide = row
    checks += [r for r in (worst_over, worst_slide) if r is not None]
    if kern is not None:
        checks.append(shallow_rules.kern_check(kern[1], kern[2], kern[3], spec.length, spec.width))
    return checks


def design_footing(
    spec: FootingSpec,
    service: Loads,
    strength: Loads,
    foundation: Foundation,
    dead: dict[str, float] | None = None,
    bearing: Bearing | None = None,
    stability: Loads | None = None,
    horizontal: dict[str, float] | None = None,
    buoyant: dict[str, tuple[float, float]] | None = None,
    tied: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The checks of one footing and notes on it. ``dead`` gives, per strength combination,
    the factor on the weight of the footing and the soil above it (its dead-load factor;
    1.0 when not given). ``bearing`` is the footing's qa and its source (see
    :func:`footing_bearing`); without it, the qa of ``foundation`` (:func:`manual_bearing`).

    Under a code pack with rules for shallow foundations (:mod:`saengine.substructure.
    shallow_rules`): ``service`` are its bearing combinations (qa increased with wind or
    earthquake), ``buoyant`` gives per combination (the factor on the weight of the footing
    and the soil above it, the uplift pressure of the water at the base [N/mm²]),
    ``stability`` the overturning and sliding combinations and ``horizontal`` their horizontal
    force at the base [N]; ``tied``: tie beams join the footing to others (sliding is the
    building's)."""
    from saengine.substructure import shallow_rules

    if bearing is None:
        bearing = manual_bearing(foundation)
    code_rules = shallow_rules.rules()
    buoyant = buoyant or {}
    notes: list[str] = []
    checks: list[dict[str, Any]] = []
    length, width, h = spec.length, spec.width, spec.thickness

    # ── bearing (service) ──
    gamma = foundation.soilUnitWeight * 1e-6  # N/mm³
    cover_depth = max(0.0, foundation.groundLevel - spec.elevation)
    founding = max(0.0, foundation.groundLevel - (spec.elevation - h))
    # A sloped or stepped footing weighs its true volume; soil fills the rest of its depth.
    mean = spec.mean_thickness()
    own_weight = spec.unit_weight * mean + gamma * (cover_depth + h - mean)  # N/mm² of base
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
    # (utilisation, q net, combination, note, the qa allowed under it)
    worst: tuple[float, float, str, str, float] | None = None
    qa = bearing.qa / 1e3 if bearing.qa else None
    kern: tuple[float, str, float, float] | None = None  # (e/B share, name, eu, ev)
    # The resultant outside the base or the footing lifted off: reported as their own checks,
    # with the eccentricity against the half side (the bearing check takes the other cases).
    outside: tuple[float, float, float, str, str] | None = None  # (ratio, e, half, name, note)
    uplift: tuple[float, str] | None = None  # (upward force N, name)
    least: tuple[float, str, str] | None = None  # (share of the base in contact, name, note)
    lifted: tuple[float, str] | None = None  # gravity only: (share in contact, name)
    for name, loads in service.items():
        weight = own_weight
        if name in buoyant:
            factor, uplift_pressure = buoyant[name]
            weight = factor * own_weight - uplift_pressure
        pressure = _contact(spec, loads, weight)
        note = f"eu = {pressure.eu:.0f} mm, ev = {pressure.ev:.0f} mm"
        if name in buoyant and buoyant[name][1] > 0:
            note += f"; buoyancy {buoyant[name][1] * 1e3:.1f} kPa at the base"
        if pressure.state != "uplift":
            share = abs(pressure.eu) / length + abs(pressure.ev) / width
            if kern is None or share > kern[0]:
                kern = (share, name, pressure.eu, pressure.ev)
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
            allowed, increase = shallow_rules.allowed(qa, name) if qa else (0.0, "")
            utilisation = net / allowed if qa else 0.0
            note = f"gross qmax = {pressure.qmax * 1e3:.0f} kPa, " + note
            if increase:
                note += f"; {increase}"
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
            worst = (utilisation, net, name, note, allowed if qa else 0.0)
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
    if code_rules is None and least is not None and least[0] < MIN_CONTACT:
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
    if code_rules is not None:
        checks += _stability_checks(spec, stability or {}, own_weight, horizontal or {}, tied, kern)
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
        utilisation, net, name, note, allowed = worst
        note += f"; {overburden_note}"
        if qa:
            checks.append(
                _check(
                    "Bearing (service)",
                    net * 1e3 if math.isfinite(net) else 0.0,
                    allowed * 1e3,
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
        shear, _, moments_at, point, span = _beam(beam_spec, pressure, loads, axis, weight)
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
        profiled = beam_spec.profiled and strip_of is None
        if profiled and sections:
            _profiled_shear(beam_spec, axis, d, shear, sections, keep, label, name)
            sections = []
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
        moments = list(zip(moments_at(stations), stations, strict=True))
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
        if profiled:
            _profiled_flexure(beam_spec, axis, d, moments, mesh_area(bottom), keep, label, name)
        else:
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
            dp = _punching_depth(spec, column, d) if spec.profiled else d
            u0, u1 = column.u - column.cu / 2 - dp / 2, column.u + column.cu / 2 + dp / 2
            v0, v1 = column.v - column.cv / 2 - dp / 2, column.v + column.cv / 2 + dp / 2
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
            b1u, b1v = column.cu + dp, column.cv + dp
            moment_u = gamma_v(b1u, b1v) * abs(cv_moment) * (b1u / 2) / polar_j(b1u, b1v, dp)
            moment_v = gamma_v(b1v, b1u) * abs(cu_moment) * (b1v / 2) / polar_j(b1v, b1u, dp)
            stress = vu / (b0 * dp) + moment_u + moment_v
            vc = punching_stress(column.cu, column.cv, dp, b0, alpha_s, fc)
            phi_vc = PHI_SHEAR * vc
            keep(
                check_name,
                stress / phi_vc,
                stress * b0 * dp / 1e3,
                phi_vc * b0 * dp / 1e3,
                "kN",
                name,
                f"vu = {stress:.2f} MPa (Vu = {vu / 1e3:.0f} kN, moments "
                f"{(moment_u + moment_v):.2f} MPa), φvc = {phi_vc:.2f} MPa, b0 = {b0:.0f} mm, "
                f"d = {dp:.0f} mm, αs = {alpha_s}"
                + (f" ({spec.section} footing: the depth at d/2)" if dp < d else ""),
            )
            if spec.profiled and spec.section == "stepped":
                _step_punching(spec, pressure, weight, column, f, name, keep)

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
        *(f"Punching at the step of {c.id}" for c in spec.columns),
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
        presumptive: str | None = None,
        water_table: float | None = None,
    ) -> None:
        """``presumptive``: the code pack's presumptive bearing row for projects without a soil
        report (light structures and preliminary design); ``water_table``: the design water
        table [m below the finished ground] for its reduction."""
        from saengine.soil.report import parse

        self.presumptive = presumptive
        self.water_table = water_table
        self.report: Any = None
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
                self.report = report

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

    def _presumptive(self, founding_level: float, b: float, l_: float) -> Bearing:
        """qa from the code pack's presumptive values (no soil report)."""
        from saengine.substructure import shallow_rules

        water = None
        if self.water_table is not None:
            water = self.foundation.groundLevel - self.water_table * 1e3 - founding_level
        try:
            qa, note = shallow_rules.presumptive(str(self.presumptive), water, min(b, l_))
        except ValueError as error:
            return Bearing(None, "none", str(error))
        return Bearing(qa, "presumptive", f"qa = {qa:g} kPa: {note}", water_depth=water)

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
            if not override and self.presumptive:
                return self._presumptive(founding_level, b, l_)
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
            found.get("foundingSoil"),
            _float(found.get("waterDepth")),
        )


def footing_settlement_at(
    soil: SoilBearing, x: float, y: float, founding_level: float, b: float, l_: float, q: float
) -> tuple[float, str, str] | None:
    """The computed settlement [mm] of a footing B × L [mm] founded at ``founding_level`` under
    a net pressure ``q`` [kPa], at the nearest borehole of the soil report, with its soil
    column ("sand" or "plasticClay") and the borehole; None without a soil report."""
    from saengine.soil.profile import Profile
    from saengine.soil.settlement import settlement, soil_column

    report = soil.report
    if report is None or not report.boreholes:
        return None
    nearest = min(report.boreholes, key=lambda bh: math.hypot(bh.x - x, bh.y - y))
    profile = Profile(report, nearest)
    df = max((report.ground_level(nearest) - founding_level) / 1e3, 0.0)
    bm, lm = min(b, l_) / 1e3, max(b, l_) / 1e3
    found = settlement(profile, bm, lm, df, max(q, 0.0))
    column = soil_column(profile, df, 2 * bm)
    return float(found["total"]), column, nearest.id


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
        section=getattr(foundation, "section", "flat"),
        edge_thickness=getattr(foundation, "edgeThickness", None),
        top_length=getattr(foundation, "topLength", None),
        top_width=getattr(foundation, "topWidth", None),
    )
    if min(spec.depths("bottom").values()) <= 0:
        raise Skip("the cover and bars leave no effective depth")
    if spec.section != "flat" and not spec.profiled:
        notes.append(
            f"{foundation.id}: designed as a flat footing: a {spec.section} footing needs one "
            "column and an edge thickness less than the thickness"
        )
    elif spec.profiled and float(spec.edge_thickness) - spec.thickness + spec.d <= 0:
        raise Skip("the edge thickness leaves no effective depth at the edges")
    return Placed(spec, nodes, center, axis_u, axis_v, founding, notes)


def _factors(cases: list[str], combinations: list[tuple[str, dict[str, float]]]) -> np.ndarray:
    """The factors of ``combinations`` as a matrix (combination x case, in the order of
    ``cases``)."""
    index = {case: k for k, case in enumerate(cases)}
    matrix = np.zeros((len(combinations), len(cases)))
    for row, (_, factors) in enumerate(combinations):
        for case, factor in factors.items():
            matrix[row, index[case]] += factor  # a case that was not analysed: KeyError
    return matrix


def footing_combinations(loads: Any) -> Any:
    """The code pack's combinations of shallow foundations over the analysed cases
    (:func:`saengine.substructure.shallow_rules.footing_combinations`), formed once per pack;
    None when the pack does not cover them."""
    from saengine.codes import context as code_context
    from saengine.substructure import shallow_rules

    cache = loads.__dict__.setdefault("_footing_combinations", {})
    key = code_context.current().id
    if key not in cache:
        cache[key] = shallow_rules.footing_combinations(loads.cases, loads.strength_level_wind)
    return cache[key]


def _actions(loads: Any, placed: Placed) -> tuple[list[str], np.ndarray]:
    """The analysed cases and each case's column actions ``[P, Cu, Cv]`` of the footing's
    columns (case x column x 3); the floor live cases of a column scaled by its live load
    reduction (``loads.live_factors``)."""
    from saengine.design.live_reduction import is_live_case

    zero = np.zeros(6)
    cases = list(loads.cases)
    per_case = np.array(
        [
            [
                column_action(
                    loads.cases[case].get(node, zero), c.arm, placed.axis_u, placed.axis_v
                )
                for c, node in zip(placed.spec.columns, placed.nodes, strict=True)
            ]
            for case in cases
        ]
    ).reshape(len(cases), len(placed.spec.columns), 3)
    factors = getattr(loads, "live_factors", None) or {}
    if factors:
        for k, case in enumerate(cases):
            if not is_live_case(case):
                continue
            for j, column in enumerate(placed.spec.columns):
                per_case[k, j] *= factors.get(column.id.split("#")[0], 1.0)
    return cases, per_case


def combination_loads(
    loads: Any,
    placed: Placed,
    combinations: list[tuple[str, dict[str, float]]],
    actions: tuple[list[str], np.ndarray] | None = None,
) -> Loads:
    """The loads ``[P, Cu, Cv]`` of each column of a placed footing under ``combinations``.

    All the combinations at once (factor matrix x the cases' column actions): the sizing
    assistant calls this for every trial size, and a building has some 300 combinations of
    some 60 cases (N-U4: one loop per combination took most of the 19 min of 20 columns)."""
    cases, per_case = actions if actions is not None else _actions(loads, placed)
    key = (tuple(cases), id(combinations), len(combinations))
    cache = loads.__dict__.setdefault("_factor_matrices", {})
    if key not in cache:
        cache[key] = _factors(cases, combinations)
    values = np.einsum("kc,cjd->kjd", cache[key], per_case)
    return {name: list(values[k]) for k, (name, _) in enumerate(combinations)}


def footing_loads(loads: Any, placed: Placed) -> tuple[Loads, Loads]:
    """The bearing and strength loads ``[P, Cu, Cv]`` of each column of a placed footing: the
    code pack's bearing combinations of shallow foundations when it has them
    (:func:`footing_combinations`), else the allowable-stress service combinations; and the
    project's strength combinations."""
    actions = _actions(loads, placed)
    combos = footing_combinations(loads)
    service = combos.bearing if combos is not None else loads.service
    return (
        combination_loads(loads, placed, service, actions),
        combination_loads(loads, placed, loads.strength, actions),
    )


def footing_horizontal(
    loads: Any, placed: Placed, combinations: list[tuple[str, dict[str, float]]]
) -> dict[str, float]:
    """The horizontal force [N] the columns of a placed footing put on it under each of
    ``combinations``: the resultant of their support reactions in plan."""
    nodes = list(dict.fromkeys(placed.nodes))
    out = {}
    for name, factors in combinations:
        total = sum((loads.reaction(n, factors)[:2] for n in nodes), np.zeros(2))
        out[name] = float(np.hypot(*total))
    return out


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
    combos = footing_combinations(ctx.loads)
    extra: dict[str, Any] = {}
    if combos is not None:
        water = _water_depth(ctx, bearing, placed.founding_level)
        uplift = GAMMA_W * max(-water, 0.0) if water is not None else 0.0
        extra = {
            "stability": combination_loads(ctx.loads, placed, combos.stability),
            "horizontal": footing_horizontal(ctx.loads, placed, combos.stability),
            "buoyant": {
                name: (_dead_factor(combos.bearing, name), factor * uplift)
                for name, factor in combos.buoyancy.items()
            },
            "tied": any(foundation.id in (t.from_, t.to) for t in ctx.substructure.tieBeams),
        }
    checks, notes = design_footing(
        spec, service, strength, ctx.settings.foundation, ctx.loads.dead, bearing, **extra
    )
    checks += footing_rule_checks(ctx, foundation, placed, strength, bearing)
    members = list(dict.fromkeys(c.id.split("#")[0] for c in spec.columns))
    bearing_check = next((c for c in checks if c["name"] == "Bearing (service)"), None)
    pressure = None
    if bearing_check is not None:
        pressure = {
            "net": bearing_check["demand"],
            "qa": bearing.qa,
            "allowed": bearing_check["capacity"],
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
    if combos is not None:
        found = footing_settlement(ctx, placed, combos, bearing)
        if found is not None:
            result["settlement"] = found
        live_notes = getattr(ctx.loads, "live_notes", {}) or {}
        reduced = {m: live_notes[m] for m in members if m in live_notes}
        if reduced:
            notes.append(
                f"{foundation.id}: normal live load reduced as in the column design: "
                + "; ".join(f"{m}: {why}" for m, why in reduced.items())
            )
    if bearing_check is None and service:
        # No qa: the footing is not checked for what sizes it, whatever its other checks say.
        result["notChecked"] = ["bearing"]
    return result, placed.notes + notes


#: Unit weight of water [N/mm³].
GAMMA_W = 9.81e-6


def _dead_factor(combinations: list[tuple[str, dict[str, float]]], name: str) -> float:
    factors = dict(combinations).get(name, {})
    return factors.get("D", factors.get("SD", 1.0))


def _water_depth(ctx: Any, bearing: Bearing, founding_level: float) -> float | None:
    """The design water table below a footing's base [mm] (negative: above it): the
    substructure's design water table when given, else the soil report's measured level."""
    level = ctx.substructure.earthPressure.designWaterTable
    if level is not None:
        return ctx.ground_level - level * 1e3 - founding_level
    return bearing.water_depth


def _natural_depth(ctx: Any, bearing: Bearing, founding_level: float) -> float:
    """The founding depth below the natural ground [mm]: below the lower of the finished ground
    and the borehole's ground (the natural one) when the soil report gives it."""
    ground = ctx.ground_level
    if bearing.ground_level is not None:
        ground = min(ground, bearing.ground_level)
    return ground - founding_level


def _exterior(ctx: Any, foundation: Any) -> bool:
    """Whether a footing is an exterior one: a column on it without floor all round its top,
    or a wall on it (strip footings under walls)."""
    from saengine.design.live_reduction import _interior
    from saengine.library.bim import ColumnElement

    for element_id in foundation.columns:
        element = ctx.elements.get(element_id)
        if not isinstance(element, ColumnElement):
            return True
        try:
            if not _interior(element, ctx.building):
                return True
        except Exception:  # noqa: BLE001 - a building without slabs: take it as exterior
            return True
    return False


def footing_rule_checks(
    ctx: Any, foundation: Any, placed: Placed, strength: Loads, bearing: Bearing
) -> list[dict[str, Any]]:
    """The code pack's rules of shallow foundations on one footing: the founding depth (every
    footing, and exterior ones by the soil at the base), the depth above the bottom bars, the
    distance to a slope face and the force transfer at each column's base."""
    from saengine.library.bim import ColumnElement
    from saengine.library.objects import Column
    from saengine.substructure import shallow_rules

    if shallow_rules.rules() is None:
        return []
    spec = placed.spec
    checks = shallow_rules.depth_check(
        foundation.id,
        _natural_depth(ctx, bearing, placed.founding_level),
        _exterior(ctx, foundation),
        bearing.founding_soil,
        ctx.substructure.design.temporary,
    )
    edge = float(spec.edge_thickness) if spec.profiled else spec.thickness
    dia_x = spec.bottom_x.dia if spec.bottom_x else 0.0
    dia_y = spec.bottom_y.dia if spec.bottom_y else 0.0
    row = shallow_rules.thickness_check(foundation.id, edge - spec.cover - dia_x - dia_y)
    if row is not None:
        checks.append(row)
    distance = getattr(foundation, "slopeDistance", None)
    if distance:
        row = shallow_rules.slope_check(min(spec.length, spec.width), float(distance))
        if row is not None:
            checks.append(row)
    for k, column in enumerate(spec.columns):
        element = ctx.elements.get(column.id)
        if not column.punching or not isinstance(element, ColumnElement):
            continue
        worst = max(
            ((float(loads[k][0]), name) for name, loads in strength.items()),
            default=(0.0, ""),
        )
        if worst[0] <= 0:
            continue
        column_type = ctx.types.get(element.type)
        fc_column = spec.fc
        bars_area = bars_count = None
        if isinstance(column_type, Column):
            material = ctx.mats.get(column_type.material)
            if material is not None and material.concrete is not None:
                fc_column = material.concrete.fc
            reinforcement = column_type.reinforcement
            if reinforcement is not None and reinforcement.longitudinal:
                bars_count = sum(g.count for g in reinforcement.longitudinal)
                bars_area = sum(
                    g.count * math.pi * g.dia**2 / 4 for g in reinforcement.longitudinal
                )
        # A2: the largest area of the footing's top concentric with the column, its sides
        # reaching no further than 2 h (a 1:2 frustum within the footing).
        reach = min(
            spec.length / 2 - abs(column.u) - column.cu / 2,
            spec.width / 2 - abs(column.v) - column.cv / 2,
            2 * spec.thickness,
        )
        reach = max(reach, 0.0)
        a2 = (column.cu + 2 * reach) * (column.cv + 2 * reach)
        checks += shallow_rules.column_base_checks(
            column.id,
            worst[0],
            column.cu,
            column.cv,
            fc_column,
            spec.fc,
            a2,
            bars_area,
            bars_count,
            spec.fy,
            worst[1],
        )
    return checks


def footing_settlement(
    ctx: Any, placed: Placed, combos: Any, bearing: Bearing
) -> dict[str, Any] | None:
    """The computed settlement of a footing under the code pack's settlement combination of its
    soil (granular or cohesive at the base), at the uniform net pressure (the column loads, the
    footing and the soil above it, less the overburden), for the differential settlements
    between footings; None without a soil report."""
    spec = placed.spec
    soil = bearing.founding_soil or "granular"
    combination = combos.settlement.get(soil) or next(iter(combos.settlement.values()), None)
    if combination is None or ctx.soil.report is None:
        return None
    loads = combination_loads(ctx.loads, placed, [combination])[combination[0]]
    area = spec.length * spec.width
    gamma = ctx.settings.foundation.soilUnitWeight * 1e-6
    cover = max(0.0, ctx.ground_level - spec.elevation)
    mean = spec.mean_thickness()
    weight = spec.unit_weight * mean + gamma * (cover + spec.thickness - mean)
    founding = max(0.0, ctx.ground_level - placed.founding_level)
    overburden = gamma * founding
    if bearing.overburden is not None:
        overburden = min(overburden, bearing.overburden / 1e3)
    q = (sum(float(f[0]) for f in loads) / area + weight - overburden) * 1e3  # kPa
    found = footing_settlement_at(
        ctx.soil,
        float(placed.center[0]),
        float(placed.center[1]),
        placed.founding_level,
        spec.width,
        spec.length,
        q,
    )
    if found is None:
        return None
    value, column, borehole = found
    return {
        "value": round(value, 1),
        "soil": column,
        "q": round(q, 1),
        "combination": combination[0],
        "borehole": borehole,
    }


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


def tie_force(
    loads: Any, ends: list[tuple[str, list[str]]], share: float | None = None
) -> tuple[float, str | None]:
    """The pack's ``tieBeams.forceShare`` (the default pack: 10 %, BNBC 2020 Part 6 Sec
    1.8.5.2 (b)) of the larger footing or column load [N] of the two foundations ``ends`` (id,
    the columns it carries): the largest factored compression of a foundation (all its columns
    together) or of any one column; and what governs it."""
    if share is None:
        ties = _tie_rules()
        share = 0.0 if ties is None else float(ties.forceShare)
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
    return share * best, which


def _tie_rules() -> Any | None:
    """The pack's tie beam rules (``foundations.shallow.tieBeams``), or None. Read on their
    own: they do not depend on the shallow foundations' geotechnical rules being used."""
    from saengine.substructure import shallow_rules

    shallow = shallow_rules.foundations_value("shallow")
    return None if shallow is None else shallow.tieBeams


def design_tie_beam(ctx: Any, tie: Any) -> tuple[dict[str, Any], list[str]]:
    """The checks of a tie beam between two foundations: the strut-tie force of the pack's
    ``tieBeams`` rules in tension and compression and its least size (the default pack: BNBC
    2020 Part 6 Secs 1.8.5.2 and 8.3.11.3 (b)), and the moment and shear of a given differential
    settlement. Raises
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
    from saengine.substructure import shallow_rules

    ties = _tie_rules()
    force, governing = 0.0, None
    if ties is None:
        notes.append(f"{tie.id}: " + shallow_rules.not_covered("the tie force and least size"))
    else:
        force, governing = tie_force(
            loads, [(f.id, _carried(ctx, f)) for f in ends], float(ties.forceShare)
        )
        zone = derived(ctx.settings)["zone"]
        flag = zone not in ties.zones
        share = float(ties.forceShare)
        clause = shallow_rules.cite("shallow.tieBeams", shallow_rules.code_name())
        rule = f"{share * 100:g} % of the larger footing or column load ({clause})"
        if governing is not None:
            rule += f": {governing}, {force / share / 1e3:.0f} kN factored"
        if flag:
            rule += f"; seismic zone {zone}: not required by {clause}, reported only"
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

    # Size: the clear spacing between the connected columns / the pack's divisor, at most its
    # largest size (the default pack: / 20, 450 mm).
    centres = [ctx.center(f) for f in ends]
    if ties is not None:
        positions = [
            [(c, p) for c in f.columns if (p := ctx.position(c)) is not None] for f in ends
        ]
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
        divisor, largest = float(ties.spanDivisor), float(ties.sizeMax)
        required = min(clear / divisor, largest)
        size_clause = shallow_rules.cite("shallow.tieBeams.size")
        checks.append(
            _check(
                "Least size",
                required,
                min(profile.xDim, profile.yDim),
                "mm",
                None,
                f"smallest dimension ≥ the clear spacing {clear:.0f} mm between the columns / "
                f"{divisor:g}, need not exceed {largest:g} mm"
                + (f" ({size_clause})" if size_clause else ""),
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

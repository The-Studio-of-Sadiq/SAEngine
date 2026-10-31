"""Post-tensioned slabs: tendon forces and losses, load balancing, hyperstatic moments, stresses
at transfer and service, flexural strength, bonded reinforcement, precompression, tendon
spacing and punching with prestress (BNBC 2020 Part 6 Chapter 9, prestressed concrete, which
follows ACI 318-11 Chapter 18; sections and pages of BNBC not checked). The limits are the code
pack's ``concrete.prestress``.

A tendon group (``bim.SlabTendon``) designs the strip of slab it serves: ``width`` wide, the
slab's thickness ``h`` deep, along the tendons from start to end. The strip is analysed as a
continuous beam on knife-edge supports at the profile's high points (the ends and the interior
local highest points: the designer places them over the supports), without the columns'
stiffness: an equivalent-frame simplification, noted with the checks.

Profile. Between two profile points the CGS follows a parabola with its vertex (zero slope) at
the lower one: y = y_low + (y_high - y_low) (x / c)², c the segment's length. The tendon force P
then puts on the concrete (load balancing): an upward load P y'' = 2 P Δy / c² per length along
each segment, a point load P (s_right - s_left) where the slopes meet (downward at a high point),
and at each anchor the force along the tendon with the moment of its eccentricity from the
centroid (h / 2). These loads are in equilibrium on their own.

Hyperstatic moments. The continuous strip under the balancing loads gives the total moment of
the prestress M_bal; the primary moment is M1 = -P e (e = h/2 - y below the centroid, sagging
positive), and the hyperstatic (secondary) moment M2 = M_bal - M1, linear between supports. The
strength demand adds 1.0 M2 to the factored gravity moments (ACI 318-11 18.10.3); the service
stresses take M_bal.

Forces (one average force per stage for the balancing loads; mechanics where the code lists the
loss without a formula, ACI 318-11 18.6.1):

- jacking: fpj = jacking × fpu, at most 0.80 fpu and 0.94 fpy (18.5.1);
- friction (18.6.2.1): P(x) = Pj e^-(K x + μ α), α the angle change from the live end (both
  live ends: the larger of the two);
- anchor set: the draw-in Δ reverses the friction near the live end over the length x_set where
  ∫(2 (P(x) - P(x_set))) dx = Δ Ep Aps; stress at the anchors after transfer at most 0.70 fpu;
- elastic shortening of tendons stressed one after another: half the shortening of the average
  precompression, ΔfES = 0.5 (Ep / Eci) fcp, Eci = 4700 √f'ci (BNBC 2020 Part 6 Sec 6.1.7.1);
- long-term losses (creep, shrinkage, relaxation): the stress the engineer enters (a time-step
  method is a planned feature).

Checks along the strip (stresses compression positive, f = P/A ± M/S with A = b h, S = b h²/6):

- transfer (P after the immediate losses, self-weight): compression <= 0.60 f'ci, tension <=
  0.25 √f'ci (18.4.1);
- service, total load (D + SD + L): compression <= 0.60 f'c; tension <= 0.50 √f'c in two-way
  slabs (Class U, 18.3.3), 0.62 √f'c in one-way slabs (Class U); sustained (D + SD):
  compression <= 0.45 f'c (18.4.2);
- strength: the gravity strength combinations of the pack plus 1.0 M2 against φMn of the
  tendons and the bonded bars of the strip's direction: unbonded fps = fse + 70 + f'c / (100 ρp)
  <= fpy, fse + 420 for span/depth <= 35, else fse + 70 + f'c / (300 ρp) <= fpy, fse + 210
  (18.7.2 (c), (d)); bonded fps = fpu (1 - γp / β1 ρp fpu / f'c) (18.7.2 (a), γp = 0.28);
  a = (Aps fps + As fy) / (0.85 f'c b); φ from εt (ACI 21.2.2);
- bonded reinforcement (18.9): two-way slabs, top bars over each interior support As >= 0.00075
  Acf (Acf taken as the strip's section h b); bottom bars As = Nc / (0.5 fy) where the service
  tension exceeds 0.17 √f'c (Nc the tension force of the concrete); one-way slabs with unbonded
  tendons As >= 0.004 Act (Act = b h / 2);
- average precompression P_e / (b h) >= 0.9 MPa, and distributed tendons at most min(8 h,
  1.5 m) apart (18.12.4).

Punching with prestress (ACI 318-11 11.11.2.2, :func:`punching_vc`): at interior columns of
two-way slabs with fpc between 0.9 and 3.5 MPa each way, vc = βp √f'c + 0.3 fpc, βp = min(0.29,
0.083 (αs d / b0 + 1.5)), √f'c <= 5.8 MPa; Vp is taken as zero (conservative).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design.rc import EPS_CU, beta1, phi_axial_flexure

#: Elements per profile segment of the strip's beam model.
ELEMENTS_PER_SEGMENT = 16


def limits() -> Any:
    """The pack's ``concrete.prestress`` limits (see :class:`codes.tables.PrestressLimits`)."""
    found = getattr(code_context.table("concrete"), "prestress", None)
    if found is None:
        raise ValueError("the code pack has no prestressed concrete limits")
    return found


# ─────────────────────────────────────── profile ───────────────────────────────────────


@dataclass(frozen=True)
class Segment:
    """A parabolic piece of the profile from ``x0`` to ``x1`` (mm), heights ``y0``, ``y1``
    (mm above the soffit), with its vertex at the lower end."""

    x0: float
    x1: float
    y0: float
    y1: float

    @property
    def length(self) -> float:
        return self.x1 - self.x0

    @property
    def curvature(self) -> float:
        """y'' [1/mm], >= 0 (concave up)."""
        return 2 * abs(self.y1 - self.y0) / self.length**2

    def height(self, x: float) -> float:
        if self.y0 <= self.y1:  # vertex at the start
            return self.y0 + (self.y1 - self.y0) * ((x - self.x0) / self.length) ** 2
        return self.y1 + (self.y0 - self.y1) * ((self.x1 - x) / self.length) ** 2

    def slope(self, x: float) -> float:
        if self.y0 <= self.y1:
            return 2 * (self.y1 - self.y0) * (x - self.x0) / self.length**2
        return -2 * (self.y0 - self.y1) * (self.x1 - x) / self.length**2


def segments(points: list[tuple[float, float]]) -> list[Segment]:
    """The profile's parabolic segments from its (distance, height) points."""
    return [Segment(a[0], b[0], a[1], b[1]) for a, b in pairwise(points)]


def supports(points: list[tuple[float, float]]) -> list[float]:
    """The strip's supports [mm]: the ends and the interior high points (higher than both
    neighbours)."""
    found = [points[0][0]]
    for before, here, after in zip(points, points[1:], points[2:], strict=False):
        if here[1] > before[1] and here[1] >= after[1]:
            found.append(here[0])
    found.append(points[-1][0])
    return found


def angle_change(pieces: list[Segment], x: float) -> float:
    """α [rad] from the start to ``x``: the curvature along the segments plus the kinks where
    they meet."""
    total = 0.0
    for k, piece in enumerate(pieces):
        if x <= piece.x0:
            break
        end = min(x, piece.x1)
        total += abs(piece.slope(end) - piece.slope(piece.x0))
        if k + 1 < len(pieces) and x > piece.x1:
            total += abs(pieces[k + 1].slope(piece.x1) - piece.slope(piece.x1))
    return total


# ─────────────────────────────────────── forces ───────────────────────────────────────


@dataclass
class TendonForces:
    """Force [N] of the whole group along the strip at ``stations`` [mm], per stage."""

    stations: np.ndarray
    jacking: float  # N, the group's
    friction: np.ndarray
    after_set: np.ndarray
    initial: np.ndarray  # after the immediate losses (friction, set, elastic shortening)
    effective: np.ndarray  # after the long-term losses
    area: float  # Aps of the group [mm²]
    set_length: float  # mm
    elastic: float  # ΔfES [MPa]
    notes: list[str] = field(default_factory=list)


def friction_forces(
    pj: float, pieces: list[Segment], stations: np.ndarray, k: float, mu: float, ends: str
) -> np.ndarray:
    """P(x) = Pj e^-(K x + μ α) from the live end(s) (ACI 318-11 18.6.2.1; K per metre)."""
    length = float(stations[-1])
    total = angle_change(pieces, length)
    alpha = np.array([angle_change(pieces, float(x)) for x in stations])
    from_start = pj * np.exp(-(k * stations / 1000 + mu * alpha))
    from_end = pj * np.exp(-(k * (length - stations) / 1000 + mu * (total - alpha)))
    if ends == "start":
        return from_start
    if ends == "end":
        return from_end
    return np.maximum(from_start, from_end)


def _set_one_end(force: np.ndarray, stations: np.ndarray, work: float) -> tuple[np.ndarray, float]:
    """The force after a draw-in at ``stations[0]`` worth ``work`` = Δ Ep Aps [N·mm]: mirrored
    about the force at the set length."""
    if work <= 0:
        return force.copy(), 0.0

    def area(index: int) -> float:
        lost = 2 * (force[: index + 1] - force[index])
        return float(np.trapezoid(lost, stations[: index + 1]))

    for index in range(1, len(stations)):
        if area(index) >= work:
            # Between the last two stations: interpolate the set length.
            lo, hi = area(index - 1), area(index)
            t = (work - lo) / (hi - lo) if hi > lo else 1.0
            x_set = float(stations[index - 1] + t * (stations[index] - stations[index - 1]))
            p_set = float(np.interp(x_set, stations, force))
            after = np.where(stations < x_set, 2 * p_set - force, force)
            return after, x_set
    # The draw-in reaches the far end: the mirrored diagram drops further by a constant.
    whole = area(len(stations) - 1)
    drop = (work - whole) / float(stations[-1] - stations[0])
    return 2 * force[-1] - force - drop, float(stations[-1])


def anchor_set(
    force: np.ndarray, stations: np.ndarray, draw_in: float, ep: float, aps: float, ends: str
) -> tuple[np.ndarray, float]:
    """The force after the anchor set at the live end(s), and the set length [mm]."""
    work = draw_in * ep * aps
    after, length = force.copy(), 0.0
    if ends in ("start", "both"):
        after, length = _set_one_end(after, stations, work)
    if ends in ("end", "both"):
        flipped, other = _set_one_end(after[::-1], stations[-1] - stations[::-1], work)
        after = np.minimum(after, flipped[::-1]) if ends == "both" else flipped[::-1]
        length = max(length, other)
    return after, length


def tendon_forces(
    tendon: Any,
    pieces: list[Segment],
    stations: np.ndarray,
    section_area: float,
    fc: float,
) -> TendonForces:
    """The group's forces along the strip (see the module notes). ``section_area``: b h of the
    strip [mm²]."""
    lim = limits()
    fpy = tendon.fpy or 0.9 * tendon.fpu
    aps = tendon.count * tendon.strands * tendon.strandArea
    notes = []
    fpj = tendon.jacking * tendon.fpu
    if fpj > lim.jackingFpu * tendon.fpu + 1e-6 or fpj > lim.jackingFpy * fpy + 1e-6:
        notes.append(
            f"jacking stress {fpj:.0f} MPa above min(0.80 fpu, 0.94 fpy) = "
            f"{min(lim.jackingFpu * tendon.fpu, lim.jackingFpy * fpy):.0f} MPa"
        )
    pj = fpj * aps
    friction = friction_forces(
        pj, pieces, stations, tendon.wobble, tendon.friction, tendon.stressedAt
    )
    after_set, set_length = anchor_set(
        friction, stations, tendon.anchorSet, tendon.ep, aps, tendon.stressedAt
    )
    fci = tendon.transferStrength or fc
    eci = 4700 * math.sqrt(fci)
    fcp = float(np.mean(after_set)) / section_area
    elastic = 0.5 * tendon.ep / eci * fcp
    initial = after_set - elastic * aps
    effective = initial - tendon.longTermLoss * aps
    return TendonForces(
        stations, pj, friction, after_set, initial, effective, aps, set_length, elastic, notes
    )


# ─────────────────────────────────── the strip as a beam ───────────────────────────────────


@dataclass
class StripModel:
    """The strip's beam model: nodes at ``stations`` [mm], supports at ``fixed`` nodes."""

    stations: np.ndarray
    fixed: list[int]

    def moments(
        self,
        distributed: np.ndarray,
        nodal: np.ndarray | None = None,
        couples: np.ndarray | None = None,
    ) -> np.ndarray:
        """Sagging-positive moments [N·mm] at the nodes of a continuous beam (EI constant; the
        moments of a beam on rigid supports do not depend on it) under ``distributed`` upward
        loads per element [N/mm], upward ``nodal`` forces [N] and counter-clockwise ``couples``
        [N·mm] at the nodes."""
        n = len(self.stations)
        size = 2 * n
        stiffness = np.zeros((size, size))
        loads = np.zeros(size)
        fixed_end = []
        for e in range(n - 1):
            length = float(self.stations[e + 1] - self.stations[e])
            k = _beam_stiffness(length)
            q = float(distributed[e])
            equivalent = np.array([q * length / 2, q * length**2 / 12, q * length / 2,
                                   -q * length**2 / 12])  # fmt: skip
            dofs = [2 * e, 2 * e + 1, 2 * e + 2, 2 * e + 3]
            stiffness[np.ix_(dofs, dofs)] += k
            loads[dofs] += equivalent
            fixed_end.append((k, equivalent, dofs))
        if nodal is not None:
            loads[0::2] += nodal
        if couples is not None:
            loads[1::2] += couples
        held = sorted({2 * i for i in self.fixed})
        free = [d for d in range(size) if d not in held]
        displacement = np.zeros(size)
        displacement[free] = np.linalg.solve(stiffness[np.ix_(free, free)], loads[free])
        result = np.zeros(n)
        for e, (k, equivalent, dofs) in enumerate(fixed_end):
            end = k @ displacement[dofs] - equivalent
            if e == 0:
                result[0] = -end[1]
            result[e + 1] = end[3]
        return result


def _beam_stiffness(length: float) -> np.ndarray:
    """Bending stiffness of a beam element (EI = 1): v, θ at each end."""
    a = length
    return (
        np.array(
            [
                [12, 6 * a, -12, 6 * a],
                [6 * a, 4 * a**2, -6 * a, 2 * a**2],
                [-12, -6 * a, 12, -6 * a],
                [6 * a, 2 * a**2, -6 * a, 4 * a**2],
            ]
        )
        / a**3
    )


def strip_model(points: list[tuple[float, float]]) -> tuple[StripModel, list[Segment]]:
    """The beam model of a profile: nodes along each segment, supports at its high points."""
    pieces = segments(points)
    stations = np.unique(
        np.concatenate([np.linspace(p.x0, p.x1, ELEMENTS_PER_SEGMENT + 1) for p in pieces])
    )
    fixed = [int(np.argmin(np.abs(stations - x))) for x in supports(points)]
    return StripModel(stations, fixed), pieces


def balancing_loads(
    pieces: list[Segment], model: StripModel, force: float, h: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The loads of a tendon force ``force`` [N] on the concrete (load balancing): upward load
    per element [N/mm], upward nodal forces [N] (kinks and anchors) and anchor couples [N·mm]."""
    stations = model.stations
    middles = (stations[:-1] + stations[1:]) / 2
    distributed = np.zeros(len(middles))
    for i, x in enumerate(middles):
        piece = next(p for p in pieces if p.x0 <= x <= p.x1)
        distributed[i] = force * piece.curvature
    nodal = np.zeros(len(stations))
    couples = np.zeros(len(stations))
    for left, right in pairwise(pieces):
        node = int(np.argmin(np.abs(stations - left.x1)))
        nodal[node] += force * (right.slope(left.x1) - left.slope(left.x1))
    first, last = pieces[0], pieces[-1]
    nodal[0] += force * first.slope(first.x0)
    nodal[-1] -= force * last.slope(last.x1)
    # The anchors' eccentricity below the centroid: hogging couples at both ends.
    couples[0] += force * (h / 2 - first.y0)
    couples[-1] -= force * (h / 2 - last.y1)
    return distributed, nodal, couples


# ─────────────────────────────────────── strength ───────────────────────────────────────


def stress_at_strength(
    fse: float,
    fpu: float,
    fpy: float,
    fc: float,
    rho_p: float,
    span_depth: float,
    bonded: bool,
) -> float:
    """fps [MPa] (ACI 318-11 18.7.2): bonded fpu (1 - γp / β1 ρp fpu / f'c); unbonded fse + 70 +
    f'c / (100 ρp) <= fpy, fse + 420 up to span/depth 35, else fse + 70 + f'c / (300 ρp) <= fpy,
    fse + 210."""
    lim = limits()
    if bonded:
        return fpu * (1 - lim.gammaP / beta1(fc) * rho_p * fpu / fc)
    slender = span_depth > lim.unbondedSpanDepth
    k = lim.unbondedK[1] if slender else lim.unbondedK[0]
    cap = lim.unbondedCap[1] if slender else lim.unbondedCap[0]
    fps = fse + lim.unbondedAdd + fc / (k * rho_p)
    return min(fps, fpy, fse + cap)


@dataclass(frozen=True)
class Strength:
    phi_mn: float  # N·mm
    fps: float
    a: float
    c: float
    phi: float


def flexural_strength(
    aps: float,
    fps: float,
    dp: float,
    bars: float,
    fy: float,
    d: float,
    fc: float,
    width: float,
) -> Strength:
    """φMn [N·mm] of a strip ``width`` wide with ``aps`` at ``dp`` stressed to ``fps`` and
    ``bars`` [mm²] at ``d`` (rectangular stress block, ACI 22.2; φ from εt, ACI 21.2.2)."""
    tension = aps * fps + bars * fy
    a = tension / (0.85 * fc * width)
    c = a / beta1(fc)
    depth = max(dp, d if bars > 0 else 0.0)
    eps_t = EPS_CU * (depth - c) / c if c > 0 else math.inf
    phi = phi_axial_flexure(eps_t, fy)
    mn = aps * fps * (dp - a / 2) + bars * fy * (d - a / 2)
    return Strength(phi * mn, fps, a, c, phi)


def punching_vc(fc: float, d: float, b0: float, alpha_s: float, fpc: float) -> float | None:
    """vc [MPa] of two-way shear at an interior column of a prestressed slab (ACI 318-11
    11.11.2.2): βp √f'c + 0.3 fpc, βp = min(0.29, 0.083 (1.5 + αs d / b0)), √f'c <= 5.8 MPa;
    None when fpc (the average of the two directions; each must be in range, checked by the
    caller) is outside 0.9-3.5 MPa."""
    lim = limits()
    lo, hi = lim.punchingFpcRange
    if not lo <= fpc <= hi:
        return None
    beta_p = min(lim.punchingBetaMax, lim.punchingBetaA * (1.5 + alpha_s * d / b0))
    root = min(math.sqrt(fc), lim.punchingRootMax)
    return beta_p * root + lim.punchingFpc * fpc


# ─────────────────────────────────────── the checks ───────────────────────────────────────


@dataclass
class StripLoads:
    """Loads on the strip [N/mm² of plan]: self-weight, superimposed dead and live."""

    dead: float
    superimposed: float
    live: float


@dataclass
class TendonDesign:
    """A tendon group's design: its checks, the effective precompression [MPa] and notes."""

    checks: list[dict[str, Any]]
    precompression: float
    forces: TendonForces
    notes: list[str]


def tendon_design(
    tendon: Any,
    h: float,
    fc: float,
    fy: float,
    loads: StripLoads,
    bars_bottom: float,
    bars_top: float,
    d_bottom: float,
    d_top: float,
    two_way: bool,
) -> TendonDesign:
    """The checks of one tendon group (see the module notes). ``bars_bottom``, ``bars_top``:
    bonded bars [mm²/m] along the tendons at depths ``d_bottom``, ``d_top`` [mm]."""
    from saengine.design.check import _check

    lim = limits()
    points = [(float(p.at), float(p.height)) for p in tendon.profile]
    model, pieces = strip_model(points)
    stations = model.stations
    b = float(tendon.width)
    area, modulus = b * h, b * h**2 / 6
    forces = tendon_forces(tendon, pieces, stations, area, fc)
    notes = list(forces.notes)
    notes.append(
        "the strip is analysed as a continuous beam on supports at the profile's high points "
        "(the columns' stiffness is not included)"
    )
    fpy = tendon.fpy or 0.9 * tendon.fpu
    aps = forces.area
    p_i, p_e = float(np.mean(forces.initial)), float(np.mean(forces.effective))
    heights = np.array([next(p for p in pieces if p.x0 <= x <= p.x1).height(x) for x in stations])
    eccentricity = h / 2 - heights

    def gravity(load: float) -> np.ndarray:
        return model.moments(np.full(len(stations) - 1, -load * b))

    m_dead, m_super, m_live = (
        gravity(loads.dead),
        gravity(loads.superimposed),
        gravity(loads.live),
    )

    def balanced(force: float) -> np.ndarray:
        return model.moments(*balancing_loads(pieces, model, force, h))

    m_bal_i, m_bal_e = balanced(p_i), balanced(p_e)
    m_hyp = m_bal_e + p_e * eccentricity
    checks: list[dict[str, Any]] = []
    name = f"PT {tendon.id}"
    where = lambda i: f"at {stations[i] / 1e3:.2f} m along {tendon.id}"

    # Stresses at the anchors after transfer (18.5.1 (c)).
    anchor_stress = float(max(forces.after_set[0], forces.after_set[-1])) / aps
    checks.append(
        _check(
            f"{name}: stress at the anchors after transfer",
            anchor_stress,
            lim.anchorFpu * tendon.fpu,
            "MPa",
            None,
            f"jacking {tendon.jacking:.2f} fpu, set length {forces.set_length / 1e3:.2f} m "
            f"(draw-in {tendon.anchorSet:g} mm); <= 0.70 fpu (ACI 318-11 18.5.1)",
        )
    )

    def stress_check(
        label: str, moment: np.ndarray, force: float, compression: float, tension: float, why: str
    ) -> None:
        top = force / area + moment / modulus
        bottom = force / area - moment / modulus
        worst_c = max(float(top.max()), float(bottom.max()))
        i_c = int(np.argmax(np.maximum(top, bottom)))
        worst_t = max(float(-top.min()), float(-bottom.min()), 0.0)
        i_t = int(np.argmax(np.maximum(-top, -bottom)))
        checks.append(
            _check(
                f"{name}: {label} compression",
                worst_c,
                compression,
                "MPa",
                None,
                f"P = {force / 1e3:.0f} kN, b = {b:.0f} mm, h = {h:.0f} mm; {why}; {where(i_c)}",
            )
        )
        if tension > 0:
            checks.append(
                _check(
                    f"{name}: {label} tension",
                    worst_t,
                    tension,
                    "MPa",
                    None,
                    f"{why}; {where(i_t)}",
                )
            )

    if tendon.transferStrength:
        fci = float(tendon.transferStrength)
        stress_check(
            "transfer",
            m_dead + m_bal_i,
            p_i,
            lim.transferCompression * fci,
            lim.transferTension * math.sqrt(fci),
            f"self-weight and P after the immediate losses; 0.60 f'ci, 0.25 √f'ci "
            f"(ACI 318-11 18.4.1), f'ci = {fci:g} MPa",
        )
    else:
        notes.append(f"{tendon.id}: no f'ci entered, the stresses at transfer are not checked")
    tension_limit = (lim.tensionTwoWay if two_way else lim.tensionClassU) * math.sqrt(fc)
    total = m_dead + m_super + m_live + m_bal_e
    stress_check(
        "service",
        total,
        p_e,
        lim.totalCompression * fc,
        tension_limit,
        "D + SD + L with the effective force; 0.60 f'c (ACI 318-11 18.4.2), tension "
        + ("0.50 √f'c, two-way Class U (18.3.3)" if two_way else "0.62 √f'c, Class U (18.3.3)"),
    )
    stress_check(
        "sustained",
        m_dead + m_super + m_bal_e,
        p_e,
        lim.sustainedCompression * fc,
        0.0,
        "D + SD with the effective force; 0.45 f'c (ACI 318-11 18.4.2)",
    )

    # Strength: the gravity combinations plus 1.0 M2.
    spans = [float(stations[j] - stations[i]) for i, j in pairwise(model.fixed) if j > i] or [
        float(stations[-1])
    ]
    span_depth = max(spans) / h
    fse = p_e / aps
    worst: tuple[float, float, float, str, int, Strength] | None = None
    for combination in code_context.table("combinations").gravity:
        factors = combination.factors
        dead = factors.get("D", 0.0)
        live = factors.get("L", 0.0) + factors.get("Lr", 0.0)
        mu = dead * (m_dead + m_super) + live * m_live + m_hyp
        for i, moment in enumerate(mu):
            sagging = moment >= 0
            dp = h - heights[i] if sagging else heights[i]
            rho_p = aps / (b * dp)
            fps = stress_at_strength(fse, tendon.fpu, fpy, fc, rho_p, span_depth, tendon.bonded)
            bars = (bars_bottom if sagging else bars_top) * b / 1000
            d = d_bottom if sagging else d_top
            strength = flexural_strength(aps, fps, dp, bars, fy, d, fc, b)
            ratio = abs(moment) / strength.phi_mn if strength.phi_mn > 0 else math.inf
            if worst is None or ratio > worst[0]:
                worst = (ratio, abs(float(moment)), strength.phi_mn, combination.name, i, strength)
    if worst is not None:
        ratio, demand, capacity, combination_name, i, strength = worst
        checks.append(
            _check(
                f"{name}: flexural strength",
                demand / 1e6,
                capacity / 1e6,
                "kN·m",
                f"{combination_name} + 1.0 M2",
                f"Mu with the hyperstatic M2 = {m_hyp[i] / 1e6:.1f} kN·m (ACI 318-11 18.10.3); "
                f"fps = {strength.fps:.0f} MPa ({'bonded' if tendon.bonded else 'unbonded'}, "
                f"18.7.2), span/depth {span_depth:.1f}, a = {strength.a:.0f} mm, "
                f"φ = {strength.phi:.2f}; {where(i)}",
                utilisation=ratio,
            )
        )

    # Bonded reinforcement (18.9).
    if two_way:
        acf = h * b
        needed = lim.bondedNegative * acf
        provided = bars_top * b / 1000
        if len(model.fixed) > 2:
            checks.append(
                _check(
                    f"{name}: bonded top bars over the supports",
                    needed,
                    provided,
                    "mm²",
                    None,
                    f"As >= 0.00075 Acf, Acf = h b = {acf / 1e6:.3f} m² (the strip's section; "
                    "ACI 318-11 18.9.3.3)",
                    utilisation=needed / provided if provided > 0 else math.inf,
                )
            )
        top = p_e / area + total / modulus
        bottom = p_e / area - total / modulus
        i = int(np.argmin(bottom))
        ft = -float(bottom[i])
        if ft > lim.bondedPositiveTension * math.sqrt(fc):
            depth = h * ft / (ft + max(float(top[i]), 0.0)) if ft > 0 else 0.0
            nc = 0.5 * ft * depth * b
            needed = nc / (lim.bondedPositiveStress * fy)
            provided = bars_bottom * b / 1000
            checks.append(
                _check(
                    f"{name}: bonded bottom bars in the span",
                    needed,
                    provided,
                    "mm²",
                    None,
                    f"service tension {ft:.2f} MPa > 0.17 √f'c: As = Nc / (0.5 fy), Nc = "
                    f"{nc / 1e3:.0f} kN (ACI 318-11 18.9.3.2); {where(i)}",
                    utilisation=needed / provided if provided > 0 else math.inf,
                )
            )
    elif not tendon.bonded:
        needed = lim.bondedOneWay * b * h / 2
        provided = bars_bottom * b / 1000
        checks.append(
            _check(
                f"{name}: bonded bars (unbonded one-way)",
                needed,
                provided,
                "mm²",
                None,
                "As >= 0.004 Act, Act = b h / 2 (ACI 318-11 18.9.2)",
                utilisation=needed / provided if provided > 0 else math.inf,
            )
        )

    precompression = p_e / area
    checks.append(
        _check(
            f"{name}: average precompression",
            lim.minPrecompression,
            precompression,
            "MPa",
            None,
            f"P_e / (b h) = {p_e / 1e3:.0f} kN / {area / 1e6:.3f} m² >= 0.9 MPa "
            f"(ACI 318-11 18.12.4); after the immediate losses {p_i / pj_share(forces):.0f} % "
            f"of jacking, "
            f"elastic shortening {forces.elastic:.0f} MPa, long-term {tendon.longTermLoss:g} "
            "MPa (entered)",
            utilisation=lim.minPrecompression / precompression if precompression > 0 else math.inf,
        )
    )
    if tendon.layout == "distributed":
        spacing = b / tendon.count
        limit = min(lim.spacingThickness * h, lim.spacingMax)
        checks.append(
            _check(
                f"{name}: tendon spacing",
                spacing,
                limit,
                "mm",
                None,
                f"{tendon.count} tendons over {b:.0f} mm; <= min(8 h, 1.5 m) (ACI 318-11 18.12.4)",
            )
        )
    return TendonDesign(checks, precompression, forces, notes)


def pj_share(forces: TendonForces) -> float:
    """The jacking force / 100: the immediate force reads as a percentage of it."""
    return forces.jacking / 100

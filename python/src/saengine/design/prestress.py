"""Post-tensioned slabs: tendon forces and losses, load balancing, hyperstatic moments, stresses
at transfer and service, member class, deflection, flexural strength, bonded reinforcement,
precompression, tendon spacing, structural integrity, anchorage zones and punching with
prestress; and the reinforcement rules of prestressed compression members.

Every limit is the code pack's ``concrete.prestress`` (:class:`codes.tables.PrestressLimits`),
the lump creep and shrinkage of the losses the pack's ``concreteTime.prestress``, and the clause
of each result the pack's ``concrete.clauses`` (``prestress*`` keys); the default pack's sources
are in ``concrete.sources.prestress``. A limit the pack does not give leaves its check out with
a "not covered" note.

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
strength demand adds 1.0 M2 to the factored gravity moments; the service stresses take M_bal.

Forces (one average force per stage for the balancing loads):

- jacking: fpj = jacking × fpu, at most jackingFpu fpu and jackingFpy fpy;
- friction: P(x) = Pj e^-(K x + μ α), α the angle change from the live end (both live ends: the
  larger of the two);
- anchor set: the draw-in Δ reverses the friction near the live end over the length x_set where
  ∫(2 (P(x) - P(x_set))) dx = Δ Ep Aps;
- elastic shortening of tendons stressed one after another: half the shortening of the average
  precompression, ΔfES = 0.5 (Ep / Eci) fcp, Eci by the pack's Ec rule at f'ci (at f'c times
  the strength gain to the age at stressing when no f'ci is entered);
- long-term losses (:func:`long_term_losses`), unless the engineer enters one: relaxation from
  the pack's table by the stress after transfer / fpu; creep Ep φ fcs / Eci with φ the pack's
  creep coefficient at the age at stressing (interpolated on log age between the printed ages,
  times the post-tensioned share) and fcs the concrete stress at the CGS under the prestress and
  the sustained loads (D + SD), averaged along the tendon and over the period (the mean of its
  values with the force after transfer and the effective force, iterated); shrinkage Ep εsh,
  εsh the pack's post-tensioned shrinkage over log10(t + 2), t the age at stressing.

Checks along the strip (stresses compression positive, f = P/A ± M/S with A = b h, S = b h²/6):

- tendon stress: at the anchors after the set, and anywhere immediately after transfer;
- transfer (P after the immediate losses, self-weight): compression at most transferCompression
  f'ci (transferCompressionEnds near the ends of a strip with two supports); tension above
  transferTension √f'ci (transferTensionEnds at those ends) needs bonded bars for the whole
  tension of the uncracked section at transferBonded.stressShare fy;
- service, total load (D + SD + L) and sustained (D + SD): compression limits; the member class
  from the extreme tension (Class U up to tensionClassU √f'c, T up to tensionClassT, C above);
  two-way slabs must be Class U with tensionTwoWay √f'c; Class C needs the crack-control spacing
  of the bonded bars nearest the tension face (and bonded tendons at the pack's share of it,
  Δfps taken at its cap);
- deflection: the live-load deflection with Ig (Class U) or Ie = (Mcr/Ma)³ Ig + (1 - (Mcr/Ma)³)
  Icr (T, C), Mcr = fr Ig / yt; after attachment the creep of the sustained deflection (the
  creep coefficient of the losses) plus the loss of prestress after transfer plus the live
  load, against the pack's span divisors (Project Settings > Design > deflection);
- strength: the gravity strength combinations of the pack plus 1.0 M2 against φMn of the
  tendons and the bonded bars of the strip's direction: unbonded fps = fse + unbondedAdd +
  f'c / (k ρp) at most fpy and fse + cap; bonded fps = fpu (1 - γp / β1 ρp fpu / f'c), γp by
  fpy / fpu; a = (Aps fps + As fy) / (0.85 f'c b); φ from εt; with bonded tendons φMn at least
  cracking.factor × Mcr unless at least cracking.waiver × Mu;
- bonded reinforcement: two-way slabs, top bars over each interior support As >= bondedNegative
  Acf (Acf taken as the strip's section h b), at least bondedTop.minBars bars within
  bondedTop.beyondFace h of the column faces, at most bondedTop.maxSpacing apart; bottom bars
  As = Nc / (bondedPositiveStress fy), fy at most bondedFyMax, where the service tension exceeds
  bondedPositiveTension √f'c (Nc the tension force of the concrete); one-way slabs with unbonded
  tendons As >= bondedOneWay Act (Act = b h / 2);
- average precompression P_e / (b h) >= minPrecompression, and distributed tendons at most
  min(spacingThickness h, spacingMax) apart;
- anchorage zones: Ppu = anchorage.loadFactor × the jacking force, f'ci at stressing at least
  the pack's value for single or multi-strand tendons; monostrand slab anchors get the edge bars
  and hairpins of the pack; multi-strand anchors spalling steel spalling × Ppu and, with the
  anchor plate entered, the bursting force of the pack's simplified equations.

Structural integrity (:func:`integrity_checks`): in two-way slabs with unbonded tendons, at least
``integrity.strands`` strands each way through each column, else bottom bars through it.

Punching with prestress (:func:`punching_vc`): by the pack's ``punchingMethod``:
``precompression`` vc = βp √f'c + punchingFpc fpc at interior columns with fpc in range;
``reinforced`` (the default pack): no prestress term, the slab's nonprestressed vc applies.

Compression members (:func:`compression_member_checks`): above ``compression.threshold`` of
effective prestress, ties or spirals enclosing the tendons.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design.rc import beta1, phi_axial_flexure
from saengine.design.rc import value as rc_value

#: Elements per profile segment of the strip's beam model.
ELEMENTS_PER_SEGMENT = 16


def limits() -> Any:
    """The pack's ``concrete.prestress`` limits (see :class:`codes.tables.PrestressLimits`)."""
    found = getattr(code_context.table("concrete"), "prestress", None)
    if found is None:
        raise ValueError("the code pack has no prestressed concrete limits")
    return found


def clause(key: str) -> str:
    """The pack's clause of a prestressed result (``concrete.clauses`` key ``prestress<Key>``),
    after the pack's edition; empty when it gives none."""
    from saengine.design.rc_detailing import clause as table_clause

    return table_clause("concrete", f"prestress{key[:1].upper()}{key[1:]}")


def _cite(key: str) -> str:
    found = clause(key)
    return f" ({found})" if found else ""


def not_covered(what: str) -> str:
    pack = code_context.current()
    return f"{what}: not covered by the code pack {pack.name}"


# ─────────────────────────────────────── long-term losses ───────────────────────────────────────


def _lump() -> Any:
    """The pack's ``concreteTime.prestress`` lump creep and shrinkage, or None."""
    from saengine.fem import concrete_time

    found = concrete_time.table()
    return getattr(found, "prestress", None) if found is not None else None


def creep_coefficient(age: float, post_tensioned: bool = True) -> float:
    """Creep coefficient of the prestress losses for loading at ``age`` [days]: the pack's
    values at its ages of loading, linear on log(age) between them and the nearest outside,
    times the post-tensioned share."""
    from saengine.fem import concrete_time

    lump = _lump()
    if lump is None:
        raise concrete_time.NotCovered(not_covered("creep of the prestress losses"))
    ages, values = list(lump.creepAgesDays), list(lump.creepCoefficients)
    phi = concrete_time._log_interp(max(age, 1e-9), ages, values) if len(ages) > 1 else values[0]
    return phi * (lump.postTensionedCreepShare if post_tensioned else 1.0)


def shrinkage_strain(age: float, post_tensioned: bool = True) -> float:
    """Shrinkage strain of the prestress losses: post-tensioned the pack's value over
    log10(t + 2), t the age at transfer [days]; pretensioned the pack's value."""
    from saengine.fem import concrete_time

    lump = _lump()
    if lump is None:
        raise concrete_time.NotCovered(not_covered("shrinkage of the prestress losses"))
    if not post_tensioned:
        return float(lump.pretensionedShrinkage)
    return float(lump.postTensionedShrinkage) / math.log10(age + 2.0)


def relaxation_loss(stress: float, fpu: float) -> float:
    """Relaxation loss [MPa] of strand at the initial ``stress`` [MPa] by the pack's table
    (linear between its stress ratios; its first loss below, its last above)."""
    table = getattr(limits(), "relaxation", None)
    if table is None:
        raise ValueError(not_covered("relaxation of prestressing steel"))
    return float(np.interp(stress / fpu, table.stressRatios, table.losses))


@dataclass(frozen=True)
class LongTermLosses:
    """The long-term losses [MPa] of a tendon group and how they were found."""

    creep: float
    shrinkage: float
    relaxation: float
    stress: float  # fcs, the concrete stress at the CGS the creep is of [MPa]
    coefficient: float  # φ
    strain: float  # εsh

    @property
    def total(self) -> float:
        return self.creep + self.shrinkage + self.relaxation

    def text(self) -> str:
        return (
            f"creep {self.creep:.0f} MPa (φ = {self.coefficient:.2f}, fcs = {self.stress:.2f} "
            f"MPa{_cite('creep')}), shrinkage {self.shrinkage:.0f} MPa (εsh = "
            f"{self.strain * 1e6:.0f} × 10⁻⁶{_cite('shrinkage')}), relaxation "
            f"{self.relaxation:.0f} MPa{_cite('relaxation')}"
        )


def long_term_losses(
    ep: float,
    fpu: float,
    aps: float,
    p_initial: float,
    stress_at_cgs: Any,
    eci: float,
    age: float,
    post_tensioned: bool = True,
) -> LongTermLosses:
    """The lump long-term losses of a group with ``aps`` [mm²] at the mean force ``p_initial``
    [N] after the immediate losses: ``stress_at_cgs(P)`` gives the mean concrete compression at
    the CGS [MPa] under the force P and the sustained loads; ``eci`` the modulus at loading and
    ``age`` the age at stressing [days]. The creep stress is the mean of the stresses at the
    start and the end of the period (the effective force iterated)."""
    phi = creep_coefficient(age, post_tensioned)
    strain = shrinkage_strain(age, post_tensioned)
    shrinkage = ep * strain
    relaxation = relaxation_loss(p_initial / aps, fpu)
    start = float(stress_at_cgs(p_initial))
    stress, creep = start, 0.0
    for _ in range(20):
        p_e = p_initial - (creep + shrinkage + relaxation) * aps
        stress = 0.5 * (start + float(stress_at_cgs(p_e)))
        updated = ep * phi * max(stress, 0.0) / eci
        if abs(updated - creep) < 1e-6:
            creep = updated
            break
        creep = updated
    return LongTermLosses(creep, shrinkage, relaxation, stress, phi, strain)


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
    long_term: float = 0.0  # MPa, the long-term loss in ``effective``
    eci: float = 0.0  # MPa, the modulus at stressing

    def with_long_term(self, loss: float) -> TendonForces:
        """The forces with the long-term ``loss`` [MPa] in the effective force."""
        self.long_term = loss
        self.effective = self.initial - loss * self.area
        return self


def friction_forces(
    pj: float, pieces: list[Segment], stations: np.ndarray, k: float, mu: float, ends: str
) -> np.ndarray:
    """P(x) = Pj e^-(K x + μ α) from the live end(s) (K per metre)."""
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
    strip [mm²]. The effective force takes the long-term loss entered (none when it is left
    empty: :func:`tendon_design` works it out)."""
    lim = limits()
    fpy = tendon.fpy or 0.9 * tendon.fpu
    aps = tendon.count * tendon.strands * tendon.strandArea
    notes = []
    fpj = tendon.jacking * tendon.fpu
    if fpj > lim.jackingFpu * tendon.fpu + 1e-6 or fpj > lim.jackingFpy * fpy + 1e-6:
        notes.append(
            f"jacking stress {fpj:.0f} MPa above min({lim.jackingFpu:g} fpu, "
            f"{lim.jackingFpy:g} fpy) = "
            f"{min(lim.jackingFpu * tendon.fpu, lim.jackingFpy * fpy):.0f} MPa{_cite('jacking')}"
        )
    pj = fpj * aps
    friction = friction_forces(
        pj, pieces, stations, tendon.wobble, tendon.friction, tendon.stressedAt
    )
    after_set, set_length = anchor_set(
        friction, stations, tendon.anchorSet, tendon.ep, aps, tendon.stressedAt
    )
    eci = modulus_at_stressing(tendon, fc)
    fcp = float(np.mean(after_set)) / section_area
    elastic = 0.5 * tendon.ep / eci * fcp
    initial = after_set - elastic * aps
    forces = TendonForces(
        stations, pj, friction, after_set, initial, initial.copy(), aps, set_length, elastic,
        notes, eci=eci,
    )  # fmt: skip
    return forces.with_long_term(tendon.longTermLoss or 0.0)


def modulus_at_stressing(tendon: Any, fc: float) -> float:
    """Eci [MPa]: the pack's Ec rule at f'ci; without f'ci, at f'c times the strength gain to
    the age at stressing (the 28-day modulus when the pack has no strength gain)."""
    from saengine.design.rc_detailing import concrete_modulus

    if tendon.transferStrength:
        return concrete_modulus(float(tendon.transferStrength))[0]
    from saengine.fem import concrete_time

    try:
        share = concrete_time.strength_share(float(getattr(tendon, "transferAge", 28.0)))
    except concrete_time.NotCovered:
        share = 1.0
    return concrete_modulus(fc * max(share, 1e-3))[0]


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
        displacement, fixed_end = self._solve(distributed, nodal, couples)
        result = np.zeros(len(self.stations))
        for e, (k, equivalent, dofs) in enumerate(fixed_end):
            end = k @ displacement[dofs] - equivalent
            if e == 0:
                result[0] = -end[1]
            result[e + 1] = end[3]
        return result

    def deflections(
        self,
        distributed: np.ndarray,
        nodal: np.ndarray | None = None,
        couples: np.ndarray | None = None,
    ) -> np.ndarray:
        """Upward deflections [mm × EI, EI in N·mm²] at the nodes under the same loads as
        :meth:`moments`: divide by the strip's EI."""
        return self._solve(distributed, nodal, couples)[0][0::2]

    def spans(self) -> np.ndarray:
        """The length [mm] of the span each node is in (between the supports either side)."""
        out = np.zeros(len(self.stations))
        fixed = sorted(self.fixed)
        for i, j in pairwise(fixed):
            out[i : j + 1] = self.stations[j] - self.stations[i]
        return out

    def _solve(
        self,
        distributed: np.ndarray,
        nodal: np.ndarray | None,
        couples: np.ndarray | None,
    ) -> tuple[np.ndarray, list[Any]]:
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
        return displacement, fixed_end


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
    bars_term: float = 0.0,
) -> float:
    """fps [MPa]: bonded fpu (1 - γp / β1 (ρp fpu / f'c + d / dp ω)), γp by fpy / fpu
    (:func:`gamma_p`), ω = ρ fy / f'c of the bonded bars in tension (``bars_term`` = d / dp ω;
    compression bars left out, on the safe side); unbonded fse + unbondedAdd + f'c / (k ρp) at most fpy and fse + cap, k
    and cap up to and above the pack's span/depth."""
    lim = limits()
    if bonded:
        return fpu * (1 - gamma_p(fpy, fpu) / beta1(fc) * (rho_p * fpu / fc + bars_term))
    slender = span_depth > lim.unbondedSpanDepth
    k = lim.unbondedK[1] if slender else lim.unbondedK[0]
    cap = lim.unbondedCap[1] if slender else lim.unbondedCap[0]
    fps = fse + lim.unbondedAdd + fc / (k * rho_p)
    return min(fps, fpy, fse + cap)


def gamma_p(fpy: float, fpu: float) -> float:
    """γp of the bonded fps: the pack's row with the largest fpy / fpu ratio met (its first,
    the largest γp, when none is met); the pack's single γp when it has no rows."""
    lim = limits()
    rows = getattr(lim, "gammaPByRatio", None)
    if not rows:
        return float(lim.gammaP)
    ratio = fpy / fpu
    met = [g for r, g in sorted(rows) if ratio >= r - 1e-9]
    return float(met[-1]) if met else float(min(rows)[1])


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
    ``bars`` [mm²] at ``d`` (rectangular stress block of 0.85 f'c over β1 c; φ from εt by the
    pack's φ rules)."""
    tension = aps * fps + bars * fy
    a = tension / (0.85 * fc * width)
    c = a / beta1(fc)
    depth = max(dp, d if bars > 0 else 0.0)
    eps_t = rc_value("EPS_CU") * (depth - c) / c if c > 0 else math.inf
    phi = phi_axial_flexure(eps_t, fy)
    mn = aps * fps * (dp - a / 2) + bars * fy * (d - a / 2)
    return Strength(phi * mn, fps, a, c, phi)


def punching_vc(fc: float, d: float, b0: float, alpha_s: float, fpc: float) -> float | None:
    """vc [MPa] of two-way shear at an interior column of a prestressed slab by the pack's
    ``punchingMethod``: ``precompression`` βp √f'c + punchingFpc fpc, βp = min(punchingBetaMax,
    punchingBetaA (1.5 + αs d / b0)), √f'c at most punchingRootMax; None when fpc (the average
    of the two directions; each must be in range, checked by the caller) is outside the pack's
    range, or the method is ``reinforced`` (the nonprestressed vc applies)."""
    lim = limits()
    if getattr(lim, "punchingMethod", "precompression") != "precompression":
        return None
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
class Anchorage:
    """The anchorage zone of each tendon of a group: the factored force and what the zone
    needs (see the module notes)."""

    ppu: float  # N, per tendon
    monostrand: bool
    edge_bars: tuple[int, float, float, float] | None = None  # count, Ø, ahead, beyond [mm]
    hairpins: tuple[int, float, float, float] | None = None  # count, Ø, from, to ahead [mm]
    spalling: float = 0.0  # mm² each way per anchor
    bursting: tuple[float, float, float] | None = None  # T [N], its distance [mm], As [mm²]
    notes: list[str] = field(default_factory=list)


@dataclass
class TendonDesign:
    """A tendon group's design: its checks, the effective precompression [MPa] and notes."""

    checks: list[dict[str, Any]]
    precompression: float
    forces: TendonForces
    notes: list[str]
    losses: LongTermLosses | None = None
    member_class: str = ""
    anchorage: Anchorage | None = None


def member_class(ft: float, fc: float) -> str:
    """The class of a prestressed flexural member from its extreme service tension ``ft``
    [MPa]: "U", "T" or "C" by the pack's √f'c limits ("C" above Class U when the pack has no
    Class T limit)."""
    lim = limits()
    root = math.sqrt(fc)
    if ft <= lim.tensionClassU * root:
        return "U"
    if lim.tensionClassT is not None and ft <= lim.tensionClassT * root:
        return "T"
    return "C"


def anchorage_zone(tendon: Any, h: float, fy: float, jacking_per_tendon: float) -> Anchorage | None:
    """What the anchorage zone of each tendon of the group needs; None when the pack does not
    cover anchorage zones."""
    rule = getattr(limits(), "anchorage", None)
    if rule is None:
        return None
    ppu = rule.loadFactor * jacking_per_tendon
    mono = tendon.strands == 1 and tendon.strandArea <= rule.monostrandArea * (1 + 1e-6)
    found = Anchorage(ppu, mono)
    if mono:
        found.edge_bars = (
            rule.edgeBars,
            rule.edgeBarDia,
            rule.edgeBarAhead * h,
            rule.edgeBarExtension,
        )
        # Banded tendons are anchored together; distributed ones width / count apart.
        spacing = float(tendon.width) / tendon.count if tendon.layout == "distributed" else 0.0
        if tendon.count >= rule.groupMin and spacing <= rule.groupSpacing:
            found.hairpins = (
                tendon.count + 1,
                rule.hairpinDia,
                rule.hairpinFrom * h,
                rule.hairpinTo * h,
            )
        return found
    found.spalling = rule.spalling * ppu / fy
    bursting = rule.bursting
    if bursting is not None and tendon.anchorPlate:
        a = float(tendon.anchorPlate)
        e = max(abs(h / 2 - tendon.profile[0].height), abs(h / 2 - tendon.profile[-1].height))
        force = bursting.share * ppu * max(1.0 - a / h, 0.0)
        where = bursting.depthShare * max(h - 2 * e, 0.0)
        found.bursting = (force, where, force / (rule.phi * fy))
    elif bursting is not None:
        found.notes.append("anchor plate not entered: the bursting force is not worked out")
    return found


def _anchorage_text(found: Anchorage) -> str:
    parts = [f"Ppu = {found.ppu / 1e3:.0f} kN per tendon{_cite('anchorage')}"]
    if found.edge_bars:
        n, dia, ahead, beyond = found.edge_bars
        parts.append(
            f"{n} Ø{dia:g} bars parallel to the slab edge within {ahead:.0f} mm ahead of the "
            f"anchors, {beyond:.0f} mm beyond the outer ones{_cite('slabAnchorage')}"
        )
    if found.hairpins:
        n, dia, start, end = found.hairpins
        parts.append(
            f"{n} Ø{dia:g} hairpins, one between and one each side of the anchors, "
            f"{start:.0f}-{end:.0f} mm ahead of them{_cite('slabAnchorage')}"
        )
    if found.spalling:
        parts.append(
            f"spalling steel As >= {found.spalling:.0f} mm² each way behind each anchor"
            f"{_cite('spalling')}"
        )
    if found.bursting:
        force, where, steel = found.bursting
        parts.append(
            f"bursting T = {force / 1e3:.0f} kN at {where:.0f} mm ahead, As >= {steel:.0f} mm²"
            f"{_cite('bursting')}"
        )
    return "; ".join(parts + found.notes)


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
    *,
    spacing_bottom: float | None = None,
    spacing_top: float | None = None,
    cover: float | None = None,
    deflection: str = "sensitive",
    roof: bool = False,
    column_width: float = 0.0,
) -> TendonDesign:
    """The checks of one tendon group (see the module notes). ``bars_bottom``, ``bars_top``:
    bonded bars [mm²/m] along the tendons at depths ``d_bottom``, ``d_top`` [mm], spaced
    ``spacing_bottom``, ``spacing_top`` [mm] with ``cover`` [mm] to their surface; ``deflection``:
    the project's deflection option ("sensitive", "insensitive" or "off"); ``column_width``: of
    the columns across the strip [mm], for the bonded top bars."""
    from saengine.design.check import _check
    from saengine.design.rc_detailing import concrete_modulus, lambda_factor

    lim = limits()
    points = [(float(p.at), float(p.height)) for p in tendon.profile]
    model, pieces = strip_model(points)
    stations = model.stations
    b = float(tendon.width)
    area, modulus, inertia = b * h, b * h**2 / 6, b * h**3 / 12
    root = math.sqrt(fc)
    forces = tendon_forces(tendon, pieces, stations, area, fc)
    notes = list(forces.notes)
    notes.append(
        "the strip is analysed as a continuous beam on supports at the profile's high points "
        "(the columns' stiffness is not included)"
    )
    fpy = tendon.fpy or 0.9 * tendon.fpu
    aps = forces.area
    heights = np.array([next(p for p in pieces if p.x0 <= x <= p.x1).height(x) for x in stations])
    eccentricity = h / 2 - heights
    elements = len(stations) - 1

    def gravity(load: float) -> np.ndarray:
        return model.moments(np.full(elements, -load * b))

    m_dead, m_super, m_live = (
        gravity(loads.dead),
        gravity(loads.superimposed),
        gravity(loads.live),
    )
    m_sustained = m_dead + m_super
    unit_loads = balancing_loads(pieces, model, 1.0, h)
    unit_moment = model.moments(*unit_loads)

    def balanced(force: float) -> np.ndarray:
        return force * unit_moment

    p_i = float(np.mean(forces.initial))
    losses: LongTermLosses | None = None
    if tendon.longTermLoss is None:

        def stress_at_cgs(force: float) -> float:
            moment = m_sustained + balanced(force)
            return float(np.mean(force / area - moment * eccentricity / inertia))

        try:
            losses = long_term_losses(
                tendon.ep,
                tendon.fpu,
                aps,
                p_i,
                stress_at_cgs,
                forces.eci,
                float(tendon.transferAge),
            )
            forces.with_long_term(losses.total)
            notes.append(f"{tendon.id}: long-term loss {losses.total:.0f} MPa: {losses.text()}")
        except ValueError as error:
            notes.append(
                f"{tendon.id}: long-term losses not worked out ({error}); none taken: enter the "
                "long-term loss of the tendon group"
            )
    p_e = float(np.mean(forces.effective))
    m_bal_i, m_bal_e = balanced(p_i), balanced(p_e)
    m_hyp = m_bal_e + p_e * eccentricity
    checks: list[dict[str, Any]] = []
    name = f"PT {tendon.id}"

    def where(i: int) -> str:
        return f"at {stations[i] / 1e3:.2f} m along {tendon.id}"

    # Tendon stress at the anchors after the set, and anywhere immediately after transfer.
    anchor_stress = float(max(forces.after_set[0], forces.after_set[-1])) / aps
    checks.append(
        _check(
            f"{name}: stress at the anchors after transfer",
            anchor_stress,
            lim.anchorFpu * tendon.fpu,
            "MPa",
            None,
            f"jacking {tendon.jacking:.2f} fpu, set length {forces.set_length / 1e3:.2f} m "
            f"(draw-in {tendon.anchorSet:g} mm); <= {lim.anchorFpu:g} fpu{_cite('anchors')}",
        )
    )
    if lim.transferSteelFpy is not None and lim.transferSteelFpu is not None:
        steel_limit = min(lim.transferSteelFpy * fpy, lim.transferSteelFpu * tendon.fpu)
        steel = float(np.max(forces.initial)) / aps
        checks.append(
            _check(
                f"{name}: tendon stress after transfer",
                steel,
                steel_limit,
                "MPa",
                None,
                f"<= {lim.transferSteelFpy:g} fpy and {lim.transferSteelFpu:g} fpu"
                f"{_cite('steelTransfer')}",
            )
        )

    def faces(moment: np.ndarray, force: float) -> tuple[np.ndarray, np.ndarray]:
        return force / area + moment / modulus, force / area - moment / modulus

    def stress_check(
        label: str, moment: np.ndarray, force: float, compression: float, tension: float, why: str
    ) -> None:
        top, bottom = faces(moment, force)
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
        checks += _transfer_checks(
            name,
            model,
            faces(m_dead + m_bal_i, p_i),
            fci,
            h,
            b,
            fy,
            bars_bottom,
            bars_top,
            where,
        )
    else:
        notes.append(f"{tendon.id}: no f'ci entered, the stresses at transfer are not checked")

    # Service: compression limits, the member class and its tension.
    total = m_sustained + m_live + m_bal_e
    top, bottom = faces(total, p_e)
    tension = np.maximum(np.maximum(-top, -bottom), 0.0)
    i_t = int(np.argmax(tension))
    ft = float(tension[i_t])
    klass = "U" if two_way else member_class(ft, fc)
    stress_check(
        "service",
        total,
        p_e,
        lim.totalCompression * fc,
        lim.tensionTwoWay * root if two_way else 0.0,
        f"D + SD + L with the effective force; {lim.totalCompression:g} f'c"
        + (f", two-way slabs Class U: tension <= {lim.tensionTwoWay:g} √f'c" if two_way else "")
        + f"{_cite('service')}{_cite('class') if two_way else ''}",
    )
    stress_check(
        "sustained",
        m_sustained + m_bal_e,
        p_e,
        lim.sustainedCompression * fc,
        0.0,
        f"D + SD with the effective force; {lim.sustainedCompression:g} f'c{_cite('service')}",
    )
    if not two_way:
        class_t = f", T up to {lim.tensionClassT:g} √f'c" if lim.tensionClassT is not None else ""
        notes.append(
            f"{tendon.id}: Class {klass}, service tension {ft:.2f} MPa = {ft / root:.2f} √f'c "
            f"(Class U up to {lim.tensionClassU:g} √f'c{class_t}){_cite('class')}"
        )
    if klass == "C":
        bottom_face = bool(-bottom[i_t] >= -top[i_t])
        checks += _class_c_spacing(
            name,
            tendon,
            bottom_face,
            spacing_bottom if bottom_face else spacing_top,
            cover,
            fy,
            float(heights[i_t]),
            h,
            b,
        )

    # Deflection.
    fr = lim.rupture * lambda_factor() * root if lim.rupture is not None else None
    ec = concrete_modulus(fc)[0]
    checks += _deflection_checks(
        name,
        tendon,
        model,
        loads,
        b,
        h,
        ec,
        inertia,
        klass,
        fr,
        total,
        (bars_bottom, d_bottom),
        aps,
        heights,
        (p_i, p_e),
        deflection,
        roof,
        notes,
        unit_loads,
    )

    # Strength: the gravity combinations plus 1.0 M2.
    spans = [float(stations[j] - stations[i]) for i, j in pairwise(model.fixed) if j > i] or [
        float(stations[-1])
    ]
    span_depth = max(spans) / h
    fse = p_e / aps
    if lim.fpsMinFse is not None and fse < lim.fpsMinFse * tendon.fpu:
        notes.append(
            f"{tendon.id}: fse = {fse:.0f} MPa below {lim.fpsMinFse:g} fpu: the approximate fps "
            f"is not permitted, check fps by strain compatibility{_cite('fps')}"
        )
    worst: tuple[float, float, float, str, int, Strength] | None = None
    for combination in code_context.table("combinations").gravity:
        factors = combination.factors
        dead = factors.get("D", 0.0)
        live = factors.get("L", 0.0) + factors.get("Lr", 0.0)
        mu = dead * m_sustained + live * m_live + m_hyp
        for i, moment in enumerate(mu):
            sagging = moment >= 0
            dp = h - heights[i] if sagging else heights[i]
            rho_p = aps / (b * dp)
            bars = (bars_bottom if sagging else bars_top) * b / 1000
            d = d_bottom if sagging else d_top
            omega = d / dp * bars / (b * d) * fy / fc if d > 0 else 0.0
            fps = stress_at_strength(
                fse, tendon.fpu, fpy, fc, rho_p, span_depth, tendon.bonded, omega
            )
            strength = flexural_strength(aps, fps, dp, bars, fy, d, fc, b)
            ratio = abs(moment) / strength.phi_mn if strength.phi_mn > 0 else math.inf
            if worst is None or ratio > worst[0]:
                worst = (ratio, float(moment), strength.phi_mn, combination.name, i, strength)
    if worst is not None:
        ratio, demand, capacity, combination_name, i, strength = worst
        checks.append(
            _check(
                f"{name}: flexural strength",
                abs(demand) / 1e6,
                capacity / 1e6,
                "kN·m",
                f"{combination_name} + 1.0 M2",
                f"Mu with the hyperstatic M2 = {m_hyp[i] / 1e6:.1f} kN·m{_cite('hyperstatic')}; "
                f"fps = {strength.fps:.0f} MPa ({'bonded' if tendon.bonded else 'unbonded'}"
                f"{_cite('fps')}), span/depth {span_depth:.1f}, a = {strength.a:.0f} mm, "
                f"φ = {strength.phi:.2f}{_cite('phi')}; {where(i)}",
                utilisation=ratio,
            )
        )
        cracking = lim.cracking
        if tendon.bonded and cracking is not None and fr is not None:
            sign = 1.0 if demand >= 0 else -1.0
            mcr = modulus * (fr + p_e / area) + sign * p_e * float(eccentricity[i])
            if capacity >= cracking.waiver * abs(demand):
                notes.append(
                    f"{tendon.id}: φMn >= {cracking.waiver:g} Mu, the {cracking.factor:g} Mcr "
                    f"rule is waived{_cite('cracking')}"
                )
            else:
                checks.append(
                    _check(
                        f"{name}: strength against cracking",
                        cracking.factor * max(mcr, 0.0) / 1e6,
                        capacity / 1e6,
                        "kN·m",
                        None,
                        f"φMn >= {cracking.factor:g} Mcr, Mcr = S (fr + P/A) ± P e = "
                        f"{mcr / 1e6:.1f} kN·m, fr = {fr:.2f} MPa{_cite('rupture')}"
                        f"{_cite('cracking')}; {where(i)}",
                    )
                )

    # Bonded reinforcement.
    checks += _bonded_checks(
        name,
        tendon,
        model,
        h,
        b,
        fc,
        fy,
        two_way,
        (p_e, total, area, modulus),
        (bars_bottom, bars_top, spacing_top),
        column_width,
        where,
        notes,
    )

    precompression = p_e / area
    long_term_how = (
        "lump losses" if losses is not None else "entered" if tendon.longTermLoss else "none"
    )
    checks.append(
        _check(
            f"{name}: average precompression",
            lim.minPrecompression,
            precompression,
            "MPa",
            None,
            f"P_e / (b h) = {p_e / 1e3:.0f} kN / {area / 1e6:.3f} m² >= {lim.minPrecompression:g} "
            f"MPa{_cite('slab')}; after the immediate losses {p_i / pj_share(forces):.0f} % of "
            f"jacking, elastic shortening {forces.elastic:.0f} MPa{_cite('elastic')}, long-term "
            f"{forces.long_term:.0f} MPa ({long_term_how})",
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
                f"{tendon.count} tendons over {b:.0f} mm; <= min({lim.spacingThickness:g} h, "
                f"{lim.spacingMax:g} mm){_cite('slab')}",
            )
        )

    # Anchorage zones.
    anchorage = anchorage_zone(tendon, h, fy, forces.jacking / tendon.count)
    if anchorage is None:
        notes.append(f"{tendon.id}: {not_covered('anchorage zones')}")
    else:
        rule = lim.anchorage
        notes.append(f"{tendon.id}: anchorage zone: {_anchorage_text(anchorage)}")
        single = tendon.strands == 1
        needed = rule.transferSingle if single else rule.transferMulti
        if tendon.transferStrength:
            checks.append(
                _check(
                    f"{name}: concrete strength at stressing",
                    needed,
                    float(tendon.transferStrength),
                    "MPa",
                    None,
                    f"f'ci >= {needed:g} MPa for {'single' if single else 'multi'}-strand "
                    "tendons, unless the anchors are oversize or at most half the final force is "
                    f"applied{_cite('transferStrength')}",
                )
            )
    return TendonDesign(checks, precompression, forces, notes, losses, klass, anchorage)


def pj_share(forces: TendonForces) -> float:
    """The jacking force / 100: the immediate force reads as a percentage of it."""
    return forces.jacking / 100


# ───────────────────────────────────── parts of the design ─────────────────────────────────────


def _transfer_checks(
    name: str,
    model: StripModel,
    stresses: tuple[np.ndarray, np.ndarray],
    fci: float,
    h: float,
    b: float,
    fy: float,
    bars_bottom: float,
    bars_top: float,
    where: Any,
) -> list[dict[str, Any]]:
    """The concrete stresses at transfer (self-weight and the force after the immediate
    losses): compression; tension, or the bonded bars it needs above the limits."""
    from saengine.design.check import _check

    lim = limits()
    stations = model.stations
    top, bottom = stresses
    rule = lim.transferBonded
    simply = len(model.fixed) == 2
    region = (rule.endRegion if rule is not None else 0.0) * h
    if simply:
        ends = (stations <= stations[0] + region) | (stations >= stations[-1] - region)
    else:
        ends = np.zeros(len(stations), dtype=bool)
    compression_ends = lim.transferCompressionEnds or lim.transferCompression
    c_limit = np.where(ends, compression_ends, lim.transferCompression) * fci
    t_limit = np.where(ends, lim.transferTensionEnds, lim.transferTension) * math.sqrt(fci)
    compression = np.maximum(top, bottom)
    i_c = int(np.argmax(compression / c_limit))
    tension = np.maximum(np.maximum(-top, -bottom), 0.0)
    i_t = int(np.argmax(tension / t_limit))
    end_text = (
        f", {compression_ends:g} f'ci and {lim.transferTensionEnds:g} √f'ci within "
        f"{region:.0f} mm of the ends (two supports)"
        if simply
        else ""
    )
    out = [
        _check(
            f"{name}: transfer compression",
            float(compression[i_c]),
            float(c_limit[i_c]),
            "MPa",
            None,
            f"self-weight and P after the immediate losses; {lim.transferCompression:g} f'ci"
            f"{end_text}, f'ci = {fci:g} MPa{_cite('transfer')}; {where(i_c)}",
        )
    ]
    ft = float(tension[i_t])
    if ft <= float(t_limit[i_t]) or rule is None:
        missing = "" if rule is not None else f"; {not_covered('bonded bars at transfer')}"
        out.append(
            _check(
                f"{name}: transfer tension",
                ft,
                float(t_limit[i_t]),
                "MPa",
                None,
                f"{lim.transferTension:g} √f'ci{end_text}{_cite('transfer')}; {where(i_t)}"
                + missing,
            )
        )
        return out
    top_face = bool(-top[i_t] >= -bottom[i_t])
    other = float(bottom[i_t] if top_face else top[i_t])
    depth = h * ft / (ft + max(other, 0.0))
    force = 0.5 * ft * depth * b
    needed = force / (rule.stressShare * fy)
    provided = (bars_top if top_face else bars_bottom) * b / 1000
    face = "top" if top_face else "bottom"
    out.append(
        _check(
            f"{name}: bonded bars for the tension at transfer",
            needed,
            provided,
            "mm²",
            None,
            f"tension {ft:.2f} MPa above {float(t_limit[i_t]):.2f} MPa: the {face} bars carry "
            f"T = {force / 1e3:.0f} kN of the uncracked section at {rule.stressShare:g} fy"
            f"{_cite('transfer')}; {where(i_t)}",
            utilisation=needed / provided if provided > 0 else math.inf,
        )
    )
    return out


def _class_c_spacing(
    name: str,
    tendon: Any,
    bottom_face: bool,
    spacing: float | None,
    cover: float | None,
    fy: float,
    height: float,
    h: float,
    b: float,
) -> list[dict[str, Any]]:
    """Class C: the bonded bars nearest the tension face at most the crack-control spacing, and
    bonded tendons at the pack's share of it (Δfps taken at its cap)."""
    from saengine.design.check import _check
    from saengine.design.rc_detailing import (
        crack_spacing_limit,
        service_stress,
        tendon_spacing_limit,
    )

    face = "bottom" if bottom_face else "top"
    out = []
    cc = float(cover) if cover is not None else 20.0
    fs = service_stress(fy)
    limit = crack_spacing_limit(fs, cc)
    if limit is None:
        return []
    if spacing:
        out.append(
            _check(
                f"{name}: Class C spacing of the {face} bars",
                float(spacing),
                max(limit, 0.0),
                "mm",
                None,
                f"Class C: the crack-control spacing with fs = {fs:.0f} MPa, cc = {cc:.0f} mm"
                f"{_cite('spacingClassC')}",
            )
        )
    else:
        out.append(
            _check(
                f"{name}: Class C bonded bars at the {face}",
                1.0,
                0.0,
                "",
                None,
                f"Class C needs bonded bars near the {face} face, none entered"
                f"{_cite('spacingClassC')}",
            )
        )
    if tendon.bonded:
        rule = getattr(code_context.pack_table("detailing"), "tendonSpacing", None)
        radius = math.sqrt(4 * tendon.strandArea / math.pi) / 2
        cc_t = (height if bottom_face else h - height) - radius
        delta = float(rule.deltaMax) if rule is not None else 0.0
        found, how = tendon_spacing_limit(delta, cc_t)
        if found is not None:
            out.append(
                _check(
                    f"{name}: Class C tendon spacing",
                    b / tendon.count,
                    max(found, 0.0),
                    "mm",
                    None,
                    f"bonded tendons, Δfps taken at its cap {delta:g} MPa (conservative): {how}",
                )
            )
    return out


def _deflection_checks(
    name: str,
    tendon: Any,
    model: StripModel,
    loads: StripLoads,
    b: float,
    h: float,
    ec: float,
    ig: float,
    klass: str,
    fr: float | None,
    total: np.ndarray,
    bottom_bars: tuple[float, float],
    aps: float,
    heights: np.ndarray,
    forces: tuple[float, float],
    option: str,
    roof: bool,
    notes: list[str],
    unit_loads: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> list[dict[str, Any]]:
    """The live-load deflection and the deflection after attachment (see the module notes)."""
    from saengine.design.check import _check
    from saengine.design.deflection import DeflectionLimits, Strip, cracked_section

    try:
        divisors = DeflectionLimits.from_pack()
    except (AttributeError, KeyError, TypeError):
        notes.append(f"{tendon.id}: {not_covered('deflection limits')}")
        return []
    p_i, p_e = forces
    inertia, how = ig, "Ig (Class U)"
    if klass != "U":
        if fr is None:
            notes.append(f"{tendon.id}: {not_covered('the modulus of rupture')}: Ig is used")
        else:
            mcr = fr * ig / (h / 2)
            ma = float(np.max(np.abs(total)))
            i = int(np.argmax(total))
            bars, d = bottom_bars
            transformed = [(d, rc_value("STEEL_E") / ec * bars * b / 1000)] if bars > 0 else []
            if tendon.bonded:
                transformed.append((h - float(heights[i]), tendon.ep / ec * aps))
            try:
                icr = cracked_section([Strip(b, 0.0, h)], transformed, 1.0)[1]
            except ValueError:
                icr = 0.0
            if ma > mcr:
                share = (mcr / ma) ** 3
                inertia = min(ig, share * ig + (1 - share) * icr)
            how = (
                f"Ie = {inertia / ig:.2f} Ig (Class {klass}, Mcr = {mcr / 1e6:.1f} kN·m, Ma = "
                f"{ma / 1e6:.1f} kN·m)"
            )
    ei = ec * inertia
    elements = len(model.stations) - 1
    spans = model.spans()
    live = model.deflections(np.full(elements, -loads.live * b)) / ei
    unit = model.deflections(*unit_loads)
    gravity = model.deflections(np.full(elements, -(loads.dead + loads.superimposed) * b))

    def sustained(force: float) -> np.ndarray:
        return (gravity + force * unit) / ei

    def worst(values: np.ndarray, divisor: float) -> tuple[float, float, int]:
        ratios = np.where(spans > 0, np.abs(values) * divisor / np.maximum(spans, 1e-9), 0.0)
        i = int(np.argmax(ratios))
        return float(abs(values[i])), float(spans[i] / divisor), i

    divisor = divisors.live_roof if roof else divisors.live_floor
    demand, capacity, i = worst(live, divisor)
    out = [
        _check(
            f"{name}: live-load deflection",
            demand,
            capacity,
            "mm",
            None,
            f"l/{divisor:g} of the span, Ec = {ec:.0f} MPa, {how}{_cite('deflection')}; at "
            f"{model.stations[i] / 1e3:.2f} m",
        )
    ]
    if option == "off":
        return out
    try:
        phi = creep_coefficient(float(tendon.transferAge))
    except ValueError as error:
        notes.append(f"{tendon.id}: deflection after attachment not checked ({error})")
        return out
    added = phi * sustained(0.5 * (p_i + p_e)) + (sustained(p_e) - sustained(p_i)) + live
    if option == "sensitive":
        divisor = divisors.attached_sensitive
    else:
        divisor = divisors.attached_insensitive
    demand, capacity, i = worst(added, divisor)
    out.append(
        _check(
            f"{name}: deflection after attachment",
            demand,
            capacity,
            "mm",
            None,
            f"creep of the sustained deflection (φ = {phi:.2f}, D + SD and the mean force) + the "
            f"loss of prestress after transfer + live; l/{divisor:g}{_cite('longDeflection')} "
            "(the sum of the long-term parts is SAEngine practice); at "
            f"{model.stations[i] / 1e3:.2f} m",
        )
    )
    return out


def _bonded_checks(
    name: str,
    tendon: Any,
    model: StripModel,
    h: float,
    b: float,
    fc: float,
    fy: float,
    two_way: bool,
    service: tuple[float, np.ndarray, float, float],
    bars: tuple[float, float, float | None],
    column_width: float,
    where: Any,
    notes: list[str],
) -> list[dict[str, Any]]:
    """The bonded reinforcement of the strip (see the module notes). ``service``: the effective
    force [N], the service moments [N·mm], the area and the section modulus; ``bars``: bottom
    and top bars [mm²/m] and the top bars' spacing [mm]."""
    from saengine.design.check import _check

    lim = limits()
    p_e, total, area, modulus = service
    bars_bottom, bars_top, spacing_top = bars
    stations = model.stations
    out: list[dict[str, Any]] = []
    if not two_way:
        if tendon.bonded:
            return out
        needed = lim.bondedOneWay * b * h / 2
        provided = bars_bottom * b / 1000
        out.append(
            _check(
                f"{name}: bonded bars (unbonded one-way)",
                needed,
                provided,
                "mm²",
                None,
                f"As >= {lim.bondedOneWay:g} Act, Act = b h / 2{_cite('bondedOneWay')}",
                utilisation=needed / provided if provided > 0 else math.inf,
            )
        )
        return out
    acf = h * b
    top_rule = lim.bondedTop
    if len(model.fixed) > 2:
        needed = lim.bondedNegative * acf
        provided = bars_top * b / 1000
        out.append(
            _check(
                f"{name}: bonded top bars over the supports",
                needed,
                provided,
                "mm²",
                None,
                f"As >= {lim.bondedNegative:g} Acf, Acf = h b = {acf / 1e6:.3f} m² (the strip's "
                f"section){_cite('bondedNegative')}",
                utilisation=needed / provided if provided > 0 else math.inf,
            )
        )
        if top_rule is not None and spacing_top:
            band = column_width + 2 * top_rule.beyondFace * h
            count = int(band // spacing_top) + 1
            out.append(
                _check(
                    f"{name}: bonded top bars near the columns",
                    top_rule.minBars,
                    count,
                    "bars",
                    None,
                    f"{count} bars at {spacing_top:g} mm within {band:.0f} mm (the column "
                    f"{column_width:.0f} mm and {top_rule.beyondFace:g} h each side); at least "
                    f"{top_rule.minBars}{_cite('bondedNegative')}",
                    utilisation=top_rule.minBars / count if count else math.inf,
                )
            )
            out.append(
                _check(
                    f"{name}: spacing of the bonded top bars",
                    float(spacing_top),
                    top_rule.maxSpacing,
                    "mm",
                    None,
                    f"<= {top_rule.maxSpacing:g} mm{_cite('bondedNegative')}",
                )
            )
    top = p_e / area + total / modulus
    bottom = p_e / area - total / modulus
    i = int(np.argmin(bottom))
    ft = -float(bottom[i])
    if ft > lim.bondedPositiveTension * math.sqrt(fc):
        depth = h * ft / (ft + max(float(top[i]), 0.0)) if ft > 0 else 0.0
        nc = 0.5 * ft * depth * b
        fy_b = min(fy, lim.bondedFyMax) if lim.bondedFyMax is not None else fy
        needed = nc / (lim.bondedPositiveStress * fy_b)
        provided = bars_bottom * b / 1000
        out.append(
            _check(
                f"{name}: bonded bottom bars in the span",
                needed,
                provided,
                "mm²",
                None,
                f"service tension {ft:.2f} MPa > {lim.bondedPositiveTension:g} √f'c: As = Nc / "
                f"({lim.bondedPositiveStress:g} fy), fy = {fy_b:g} MPa, Nc = {nc / 1e3:.0f} kN"
                f"{_cite('bondedPositive')}; {where(i)}",
                utilisation=needed / provided if provided > 0 else math.inf,
            )
        )
    if top_rule is not None:
        longest = max(float(stations[j] - stations[k]) for k, j in pairwise(sorted(model.fixed)))
        notes.append(
            f"{tendon.id}: bonded bars at least {top_rule.negativeLength * longest / 1e3:.2f} m "
            f"each side of the interior supports (top) and "
            f"{top_rule.positiveLength * longest / 1e3:.2f} m centred in the spans (bottom), the "
            f"longest span taken as the clear span{_cite('bondedLength')}"
        )
    return out


# ───────────────────────────────────── structural integrity ─────────────────────────────────────


def tendon_lines(tendon: Any) -> list[tuple[np.ndarray, np.ndarray]]:
    """The tendons of a group in plan for the integrity check [mm]: a banded group together on
    its line, a distributed group evenly over its width."""
    a = np.array([tendon.x1, tendon.y1], dtype=float)
    c = np.array([tendon.x2, tendon.y2], dtype=float)
    run = c - a
    normal = np.array([-run[1], run[0]]) / (np.linalg.norm(run) or 1.0)
    if tendon.layout != "distributed":
        return [(a, c)] * tendon.count
    step = float(tendon.width) / tendon.count
    offsets = [(k + 0.5) * step - float(tendon.width) / 2 for k in range(tendon.count)]
    return [(a + o * normal, c + o * normal) for o in offsets]


def _crosses(a: np.ndarray, c: np.ndarray, column: Any, inset: float) -> bool:
    """Whether the segment a-c crosses the column's section less ``inset`` each side."""
    t = math.radians(column.angle)
    u = np.array([math.cos(t), math.sin(t)])
    v = np.array([-math.sin(t), math.cos(t)])
    centre = np.asarray(column.centre, dtype=float)
    p0 = np.array([(a - centre) @ u, (a - centre) @ v])
    d = np.array([(c - a) @ u, (c - a) @ v])
    half = np.array([column.c1 / 2 - inset, column.c2 / 2 - inset])
    if np.any(half <= 0):
        half = np.array([column.c1 / 2, column.c2 / 2])
    lo, hi = 0.0, 1.0
    for k in range(2):
        if abs(d[k]) < 1e-12:
            if abs(p0[k]) > half[k]:
                return False
            continue
        t1, t2 = (-half[k] - p0[k]) / d[k], (half[k] - p0[k]) / d[k]
        lo, hi = max(lo, min(t1, t2)), min(hi, max(t1, t2))
        if lo > hi:
            return False
    return True


def integrity_checks(
    tendons: list[tuple[Any, str]],
    columns: list[Any],
    x_axis: Any,
    fc: float,
    fy: float,
    layers: dict[str, Any],
    two_way: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Structural integrity of a slab with unbonded tendons (``tendons``: (tendon, "X" or "Y"
    of the slab)) at its ``columns`` (``slab.ColumnJoint``; ``x_axis`` the slab's X in plan):
    per direction, the strands through each column, else the bottom bars of that direction
    through it (``layers``: :func:`saengine.design.slab.layers_of`)."""
    from saengine.design.check import _check

    if not two_way or not columns or all(t.bonded for t, _ in tendons):
        return [], []
    rule = getattr(limits(), "integrity", None)
    if rule is None:
        return [], [not_covered("structural integrity tendons")]
    ux = np.asarray(x_axis, dtype=float)[:2]
    ux = ux / (np.linalg.norm(ux) or 1.0)
    checks: list[dict[str, Any]] = []
    notes: list[str] = []
    for direction in ("X", "Y"):
        group = [t for t, d in tendons if d == direction]
        lacking: list[tuple[Any, float]] = []
        least: int | None = None
        for column in columns:
            strands = 0
            for tendon in group:
                if tendon.strandArea < rule.strandArea * (1 - 1e-6):
                    continue
                for a, c in tendon_lines(tendon):
                    if _crosses(a, c, column, rule.coreInset):
                        strands += tendon.strands
            least = strands if least is None else min(least, strands)
            if strands < rule.strands:
                t = math.radians(column.angle)
                along_u = abs(math.cos(t) * ux[0] + math.sin(t) * ux[1]) >= math.sqrt(0.5)
                # bw: the column face the bars of the direction pass through.
                if direction == "X":
                    bw = column.c2 if along_u else column.c1
                else:
                    bw = column.c1 if along_u else column.c2
                lacking.append((column, float(bw)))
        if not lacking:
            checks.append(
                _check(
                    f"PT integrity strands, {direction}",
                    rule.strands,
                    least or 0,
                    "strands",
                    None,
                    f"at least {rule.strands} strands of {rule.strandArea:g} mm² or more through "
                    f"every column{_cite('integrity')}",
                )
            )
            continue
        layer = layers.get(f"bottom{direction}")
        worst: tuple[float, float, float, Any, float] | None = None
        for column, bw in lacking:
            d = layer.d if layer is not None else 0.0
            needed = max(
                rule.bottomFactor * rule.bottomRoot * math.sqrt(fc) * bw * d / fy,
                rule.bottomMin * bw * d / fy,
            )
            provided = layer.area * bw / 1000 if layer is not None else 0.0
            ratio = needed / provided if provided > 0 else math.inf
            if worst is None or ratio > worst[0]:
                worst = (ratio, needed, provided, column, bw)
        assert worst is not None
        ratio, needed, provided, column, bw = worst
        names = ", ".join(str(c.id) for c, _ in lacking[:6])
        more = f" and {len(lacking) - 6} more" if len(lacking) > 6 else ""
        checks.append(
            _check(
                f"PT integrity bottom bars, {direction}",
                needed,
                provided,
                "mm²",
                None,
                f"fewer than {rule.strands} strands through columns {names}{more}"
                f"{_cite('integrity')}: bottom bars through the column instead, As >= "
                f"{rule.bottomFactor:g} × {rule.bottomRoot:g} √f'c bw d / fy and "
                f"{rule.bottomMin:g} bw d / fy, bw = {bw:.0f} mm at {column.id}; anchored at the "
                f"exterior supports{_cite('integrityBars')}",
                utilisation=ratio,
            )
        )
        notes.append(
            f"integrity {direction}: the region bounded by the column bars taken as the column "
            f"less {rule.coreInset:g} mm each side"
        )
    return checks, notes


# ───────────────────────────────────── compression members ─────────────────────────────────────


def compression_member_checks(
    name: str,
    prestress_stress: float,
    least_dimension: float,
    wall: bool = False,
    tie_dia: float | None = None,
    tie_spacing: float | None = None,
    spiral: tuple[float, float, float, float, float] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The reinforcement of a prestressed compression member with ``prestress_stress`` [MPa] of
    average effective prestress: below the pack's threshold the ordinary column or wall minimums
    apply (noted); at or above it, columns need ties (``tie_dia``, ``tie_spacing`` [mm]) or a
    spiral (``spiral`` = (ρs provided, Ag, Ach [mm²], f'c, fyt [MPa])) enclosing the tendons;
    walls may drop the wall minimums where analysis shows strength and stability."""
    from saengine.design.check import _check

    rule = getattr(limits(), "compression", None)
    if rule is None:
        return [], [not_covered("prestressed compression members")]
    if prestress_stress < rule.threshold:
        return [], [
            (
                f"{name}: effective prestress {prestress_stress:.2f} MPa < {rule.threshold:g} MPa: "
                f"the ordinary minimum reinforcement of columns and walls applies{_cite('compression')}"
            )
        ]
    if wall:
        return [], [
            (
                f"{name}: effective prestress >= {rule.threshold:g} MPa: the wall minimum "
                "reinforcement need not apply where analysis shows strength and stability"
                f"{_cite('compression')}"
            )
        ]
    checks = []
    if spiral is not None:
        provided, ag, ach, fc, fyt = spiral
        needed = rule.spiralCoefficient * (ag / ach - 1) * fc / min(fyt, rule.spiralFytMax)
        checks.append(
            _check(
                f"{name}: spiral ratio",
                needed,
                provided,
                "",
                None,
                f"ρs >= {rule.spiralCoefficient:g} (Ag/Ach - 1) f'c / fyt, fyt <= "
                f"{rule.spiralFytMax:g} MPa{_cite('compression')}",
                utilisation=needed / provided if provided > 0 else math.inf,
            )
        )
        return checks, []
    dia = tie_dia or 0.0
    checks.append(
        _check(
            f"{name}: tie size",
            rule.tieMinDia,
            dia,
            "mm",
            None,
            f"ties >= Ø{rule.tieMinDia:g} enclosing all tendons{_cite('compression')}",
            utilisation=rule.tieMinDia / dia if dia > 0 else math.inf,
        )
    )
    limit = min(rule.tieSpacingDiameters * dia, least_dimension) if dia else least_dimension
    checks.append(
        _check(
            f"{name}: tie spacing",
            tie_spacing if tie_spacing is not None else math.inf,
            limit,
            "mm",
            None,
            f"<= {rule.tieSpacingDiameters:g} tie diameters and the least dimension"
            f"{_cite('compression')}",
        )
    )
    return checks, []

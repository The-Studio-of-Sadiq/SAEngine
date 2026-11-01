"""Capacity design of reinforced-concrete moment frames for earthquake: probable moments, strong
column / weak beam, beam-column joints, capacity-design shear, foundations and members that are
not part of the seismic-force-resisting system.

Code basis: BNBC 2020 Part 6 Chapter 8, Sec 8.3 "Earthquake-Resistant Design Provisions"
(bnbc-2020-part1.pdf pages 1088-1123), and Chapter 6 where Sec 8.3 sends there. Every rule
below names its clause and page; where BNBC refers to ACI or is silent, the docstring says so.

- Probable moment Mpr (notation, p 882; Sec 8.3.8.1, p 1111): the bars at fs = 1.25 fy, φ = 1.0
  (:func:`probable_moments`, :func:`column_moment`).
- Strong column / weak beam (Sec 8.3.5.2, p 1096, Eq. 6.8.5): ΣMnc ≥ 1.2 ΣMnb at every joint of
  a special moment frame whose columns carry more than 0.1 Ag f'c, nominal strengths at the
  joint faces, the column's at the factored axial force giving the lowest strength, summed so
  the column moments oppose the beam moments, for beam moments in both senses
  (:func:`strong_column_checks`). Failing joints: the columns below and above need the
  confinement of Sec 8.3.5.4 over their full height and their lateral strength and stiffness
  is to be ignored (8.3.5.2(a), (c)).
- Joints (Sec 8.3.7, pp 1108-1111): beam bar forces at 1.25 fy (8.3.7.1(a)), φ = 0.85 for joint
  shear (Sec 6.2.3.3(c), p 898), Vn = γ √f'c Aj with γ = 1.7 (confined on all four faces), 1.2
  (three faces or two opposite faces) and 1.0 (others), a face confined when a member covers at
  least three quarters of it (8.3.7.3, p 1110); column depth ≥ 20 db of beam bars passing
  through (26 db lightweight, 8.3.7.1(d)); hooked beam bars ending in a joint: ldh ≥ max(8 db,
  150 mm, fy db / (5.4 √f'c)) inside the confined core (8.3.7.4(a), Eq. 6.8.12, p 1111)
  (:func:`joint_checks`).
- Capacity-design shear (Sec 8.3.8, pp 1111-1112): beams Ve = (Mpr1 + Mpr2) / ln + the
  factored tributary gravity shear (8.3.8.1(a)); columns from the Mpr of their ends over the
  range of factored axial forces, not more than what the beams' Mpr at the joints can deliver,
  not less than the analysis shear (8.3.8.1(b)); Vc = 0 when the earthquake part is at least
  half of Ve and the factored axial compression is below 0.05 Ag f'c (8.3.8.2(a)).
  Intermediate moment frames (Sec 8.3.10.3, p 1114): the smaller of the shear from the
  nominal moments plus the gravity shear and the largest shear of the combinations with E
  doubled (:func:`beam_capacity_shear`, :func:`column_capacity_shear`).
- Foundations (Sec 8.3.11, pp 1120-1122): column bars developed into the footing with
  standard hooks (8.3.11.2(a), (b); ldh by Sec 8.2.6, p 1079), confinement of columns near a
  footing edge (8.3.11.2(c)), grade beam ties (8.3.11.3(b)), the confined length of piles
  (8.3.11.4(d), and 120 % of the flexural length by Sec 1.8.5.1, p 507). The tie beam force
  of Sec 1.8.5.2(b) (p 507, 10 % of the larger footing or column load) is
  :func:`saengine.substructure.shallow.tie_force`.
- Members not part of the seismic-force-resisting system (Sec 8.3.12, pp 1122-1123, SDC D;
  Sec 8.3.9, p 1113, the others): the induced moments and shears under the design
  displacement against the design strengths decide which detailing applies
  (:func:`non_sfrs_checks`).

Units: mm, MPa, N, N·mm. Checks are rows of :func:`saengine.design.check._check`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design.clauses import clause, short_clause, short_name
from saengine.design.rc import (
    DesignError,
    RcSection,
    bar_area,
    flexure,
    shear,
)
from saengine.design.rc import value as rc_value
from saengine.library.objects import CircleProfile, RectangleProfile

# The plain numbers of special moment frame joints are the pack's ``detailing.joints`` group
# and the joint φ its ``factors.phi.joint``, read when the checks run (BNBC 2020):
# ``probableStress`` 1.25, the stress of the beam bars for probable moments and joint forces as
# a multiple of fy (Sec 8.3.7.1(a), p 1108; the notation of Mpr, p 882); ``strongColumnRatio``
# 1.2, Eq. 6.8.5 (Sec 8.3.5.2(b), p 1096): ΣMnc ≥ 1.2 ΣMnb; ``axialLimit`` 0.1, columns of
# special moment frames: factored axial compression above this share of Ag f'c (Sec 8.3.5.1,
# 8.3.5.2(a), pp 1095-1096); ``gamma`` {"4": 1.7, "3": 1.2, "opposite": 1.2, "other": 1.0},
# the joint shear coefficients γ of Vn = γ √f'c Aj (Sec 8.3.7.3, p 1110), SI units;
# ``vcZeroAxial`` 0.05, Vc = 0 below this axial compression as a share of Ag f'c (Sec
# 8.3.8.2(a), p 1112); φ for joint shear 0.85 (Sec 6.2.3.3(c), p 898).


def _joints(name: str) -> float:
    """The pack's ``detailing.joints`` number ``name`` (BNBC 2020: see above)."""
    return float(code_context.table("detailing").joints[name])


def _gamma(key: int | str) -> float:
    """The pack's joint shear coefficient γ for ``key`` (4, 3, "opposite" or "other")."""
    return float(code_context.table("detailing").joints.gamma[str(key)])


def _phi_joint() -> float:
    """The pack's φ for joint shear (BNBC 2020 Sec 6.2.3.3(c), p 898: 0.85)."""
    return float(code_context.table("factors").phi["joint"])


def _section() -> str:
    """The code and part the joint rules cite ("<code> Part 6"), from the pack in force."""
    return clause("ductileJoints", "part")


def _check(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from saengine.design.check import _check as check

    return check(*args, **kwargs)


# ─────────────────────────────────────── strengths ───────────────────────────────────────


#: Integrator glue (performance): results per section object, so a type's section shared by
#: its members is analysed once per design (strain compatibility is the slow part). Keyed by
#: ``id`` with the object kept, so a reused id never returns another section's value.
_MEMO: dict[tuple[Any, ...], tuple[Any, Any]] = {}
_MEMO_SIZE = 4096


def _memo(section: Any, key: tuple[Any, ...], compute: Any) -> Any:
    full = (id(section), *key)
    found = _MEMO.get(full)
    if found is not None and found[0] is section:
        return found[1]
    if len(_MEMO) > _MEMO_SIZE:
        _MEMO.clear()
    value = compute()
    _MEMO[full] = (section, value)
    return value


def probable_section(section: RcSection) -> RcSection:
    """The section with its bars at fs = 1.25 fy (elastic-perfectly plastic), for Mpr."""
    stress = _joints("probableStress")
    return _memo(section, ("probable", stress), lambda: replace(section, fy=stress * section.fy))


@dataclass(frozen=True)
class BeamMoments:
    """Nominal and probable moments of a beam section without axial force [N·mm]."""

    mn_sag: float
    mn_hog: float
    mpr_sag: float
    mpr_hog: float
    as_top: float  # mm², the top bars
    as_bottom: float
    db_max: float  # mm, the largest longitudinal bar


def beam_moments(section: RcSection) -> BeamMoments:
    """Mn (fy, φ = 1) and Mpr (1.25 fy, φ = 1) of a beam section, sagging (bottom bars in
    tension) and hogging (top bars), from :func:`saengine.design.rc.flexure`."""
    return _memo(section, ("beam",), lambda: _beam_moments(section))


def _beam_moments(section: RcSection) -> BeamMoments:
    probable = probable_section(section)
    return BeamMoments(
        mn_sag=flexure(section, False).mn,
        mn_hog=flexure(section, True).mn,
        mpr_sag=flexure(probable, False).mn,
        mpr_hog=flexure(probable, True).mn,
        as_top=sum(b.area for b in section.bars if b.y > 0),
        as_bottom=sum(b.area for b in section.bars if b.y < 0),
        db_max=max((b.dia for b in section.bars), default=0.0),
    )


def probable_moments(section: RcSection) -> tuple[float, float]:
    """(Mpr sagging, Mpr hogging) [N·mm] of a beam section: fs = 1.25 fy, φ = 1.0."""
    m = beam_moments(section)
    return m.mpr_sag, m.mpr_hog


def column_moment(section: RcSection, axial: float, compression: float) -> float:
    """Nominal moment [N·mm] of a section at the axial force ``axial`` [N, compression
    positive], with the compression face towards the angle ``compression`` (rad, from the
    section's x axis): the neutral axis lies at ``compression - π/2``. 0 when the axial force
    is beyond the section's strength. Pass :func:`probable_section` for Mpr."""
    from concreteproperties.utils import AnalysisError

    theta = math.remainder(compression - math.pi / 2, 2 * math.pi)

    def compute() -> float:
        try:
            result = section.analysis.ultimate_bending_capacity(theta=theta, n=axial)
        except AnalysisError:
            return 0.0
        return float(math.hypot(result.m_x, result.m_y))

    return _memo(section, ("column", round(axial, 0), round(theta, 9)), compute)


def _axial_samples(
    pmin: float, pmax: float, count: int = 9, step: float | None = None
) -> list[float]:
    """Axial forces over ``pmin`` … ``pmax``: ``count`` evenly spaced, or with ``step`` the
    ends and the multiples of ``step`` between them (shared by the members of a section, so
    their analyses are reused)."""
    if pmax - pmin < 1.0:
        return [pmin]
    if step:
        inner = np.arange(math.floor(pmin / step) + 1, math.ceil(pmax / step)) * step
        return [float(pmin), *(float(p) for p in inner if pmin < p < pmax), float(pmax)]
    return [float(p) for p in np.linspace(pmin, pmax, count)]


def lowest_column_moment(
    section: RcSection, pmin: float, pmax: float, compression: float
) -> tuple[float, float]:
    """(Mnc, P): the lowest nominal moment over the factored axial forces ``pmin`` … ``pmax``
    (Sec 8.3.5.2(b): the axial force "resulting in the lowest flexural strength"), both
    senses of bending. Mn(P) is concave, so the lowest is at an end of the range."""
    best = (math.inf, pmin)
    for p in {pmin, pmax}:
        for angle in (compression, compression + math.pi):
            m = column_moment(section, p, angle)
            if m < best[0]:
                best = (m, p)
    return best


def highest_column_moment(
    section: RcSection, pmin: float, pmax: float, compression: float, probable: bool = True
) -> tuple[float, float]:
    """(M, P): the largest moment over the axial range (Sec 8.3.8.1(b): "the maximum probable
    moment strengths ... associated with the range of factored axial loads"), Mpr (``probable``)
    or Mn, at the ends of the range and every 0.05 P0 between them (the peak near the balanced
    point may fall between them: within about one per cent, Mn(P) being flat there)."""
    used = probable_section(section) if probable else section
    best = (0.0, pmin)
    for p in _axial_samples(pmin, pmax, step=0.05 * section.p0):
        for angle in (compression, compression + math.pi):
            m = column_moment(used, p, angle)
            if m > best[0]:
                best = (m, p)
    return best


# ─────────────────────────────────────── geometry ───────────────────────────────────────


def column_axes(rotation: float) -> tuple[np.ndarray, np.ndarray]:
    """Plan unit vectors of a column profile's x (``xDim``) and y (``yDim``) axes."""
    a = math.radians(rotation or 0.0)
    return np.array([math.cos(a), math.sin(a)]), np.array([-math.sin(a), math.cos(a)])


@dataclass(frozen=True)
class ColumnFrame:
    """A column section's dimensions for a plan direction."""

    along: float  # mm, the column dimension parallel to the direction (the joint depth h)
    across: float  # mm, perpendicular to it
    compression: float  # rad, the direction in the section's axes
    axis: str  # "x" or "y": the profile axis the direction lies nearest


def column_frame(profile: Any, rotation: float, direction: np.ndarray) -> ColumnFrame:
    ex, ey = column_axes(rotation)
    ux, uy = float(direction @ ex), float(direction @ ey)
    if isinstance(profile, CircleProfile):
        d = 2 * profile.radius
        return ColumnFrame(d, d, math.atan2(uy, ux), "x" if abs(ux) >= abs(uy) else "y")
    if not isinstance(profile, RectangleProfile):
        raise DesignError("columns are checked with rectangular or circular profiles only")
    if abs(ux) >= abs(uy):
        return ColumnFrame(profile.xDim, profile.yDim, math.atan2(uy, ux), "x")
    return ColumnFrame(profile.yDim, profile.xDim, math.atan2(uy, ux), "y")


@dataclass
class JointBeam:
    """A beam framing into a joint."""

    id: str
    type: str
    direction: tuple[float, float]  # plan unit vector from the joint along the beam
    length: float  # mm, from the joint to the beam's other end (centre to centre)


@dataclass
class FrameJoint:
    """A beam-column joint of the building model: the column through it (``below``, and
    ``above`` unless the column ends there), the beams framing in and the storey heights
    (centre to centre of the joints, mm)."""

    id: str
    position: tuple[float, float]
    level: float
    below: str
    above: str | None
    beams: list[JointBeam] = field(default_factory=list)
    height_below: float = 0.0
    height_above: float = 0.0


def frame_joints(building: Any, types: dict[str, Any], tolerance: float = 50.0) -> list[FrameJoint]:
    """The beam-column joints of a building model (:class:`saengine.library.bim.BuildingModel`;
    ``types``: object types by id): at every level a column passes or ends at where beams meet
    it. A beam meets a column when its end, or its line, falls inside the column's plan outline
    (``tolerance`` mm around it) at the beam's elevation within ``tolerance``. A beam running
    through the column counts on both sides. The column above is the same element when it
    continues, else a column standing at the same place on that level."""
    from saengine.library.bim import BeamElement, ColumnElement

    columns = [e for e in building.elements if isinstance(e, ColumnElement)]
    beams = [e for e in building.elements if isinstance(e, BeamElement)]
    joints: list[FrameJoint] = []
    found_levels: dict[str, dict[float, list[JointBeam]]] = {}
    for column in columns:
        position = np.asarray(column.position, dtype=float)
        profile = getattr(types.get(column.type), "profile", None)
        if isinstance(profile, RectangleProfile):
            reach = 0.5 * math.hypot(profile.xDim, profile.yDim)
        elif isinstance(profile, CircleProfile):
            reach = profile.radius
        else:
            reach = 0.0
        reach += tolerance
        at: dict[float, list[JointBeam]] = {}
        for beam in beams:
            level = float(beam.elevation)
            if not (column.bottom + tolerance < level < column.top + tolerance):
                continue
            a, b = np.asarray(beam.start, dtype=float), np.asarray(beam.end, dtype=float)
            span = float(np.linalg.norm(b - a))
            if span <= 0:
                continue
            u = (b - a) / span
            t = float((position - a) @ u)
            offset = float(np.linalg.norm(a + t * u - position))
            if offset > reach or t < -reach or t > span + reach:
                continue
            found = at.setdefault(round(level, 3), [])
            if t > reach:  # the part towards the start
                found.append(JointBeam(beam.id, beam.type, tuple(-u), t))
            if t < span - reach:  # the part towards the end
                found.append(JointBeam(beam.id, beam.type, tuple(u), span - t))
        # A beam lying wholly inside the column's reach (a stub) frames no side: not a level.
        found_levels[column.id] = {level: found for level, found in at.items() if found}
    for column in columns:
        position = np.asarray(column.position, dtype=float)
        at = found_levels[column.id]
        levels = sorted(at)
        for k, level in enumerate(levels):
            previous = levels[k - 1] if k else column.bottom
            if level < column.top - tolerance:
                above: str | None = column.id
                following = levels[k + 1] if k + 1 < len(levels) else column.top
            else:
                above, following = None, level
                for other in columns:
                    if (
                        other.id != column.id
                        and abs(other.bottom - level) <= tolerance
                        and np.linalg.norm(np.asarray(other.position) - position) <= tolerance
                    ):
                        above = other.id
                        # The next joint on the column above, else its top.
                        following = min(
                            (z for z in found_levels[other.id] if z > level + tolerance),
                            default=other.top,
                        )
                        break
            joints.append(
                FrameJoint(
                    id=f"{column.id}@{level:g}",
                    position=(float(position[0]), float(position[1])),
                    level=level,
                    below=column.id,
                    above=above,
                    beams=at[level],
                    height_below=level - previous,
                    height_above=(following - level) if above else 0.0,
                )
            )
    # A column continuing through a level is found from it; drop the duplicate a column
    # starting there would add (its own bottom is not a joint level of it).
    unique: dict[tuple[float, float, float], FrameJoint] = {}
    for joint in joints:
        key = (round(joint.position[0]), round(joint.position[1]), round(joint.level))
        unique.setdefault(key, joint)
    return list(unique.values())


# ─────────────────────────────────── members at a joint ───────────────────────────────────


@dataclass
class JointColumn:
    """A column at a joint: its section, plan rotation and the factored axial forces of the
    combinations with earthquake at that end [N, compression positive]; ``cover`` and
    ``tie_dia`` for the confined core (mm)."""

    section: RcSection
    rotation: float = 0.0
    pmin: float = 0.0
    pmax: float = 0.0
    cover: float = 40.0
    tie_dia: float = 10.0

    @property
    def axial_share(self) -> float:
        """The largest factored compression as a share of Ag f'c."""
        return self.pmax / (self.section.gross_area * self.section.fc)


@dataclass
class _Direction:
    name: str
    axis: np.ndarray
    plus: list[tuple[JointBeam, RcSection, BeamMoments]]
    minus: list[tuple[JointBeam, RcSection, BeamMoments]]
    skew: float  # rad, the largest angle of a beam to the direction


def _directions(
    joint: FrameJoint, beams: dict[str, RcSection], rotation: float
) -> tuple[list[_Direction], list[str]]:
    """The beams of a joint grouped along the column's two profile axes."""
    notes: list[str] = []
    ex, ey = column_axes(rotation)
    out = [_Direction("x", ex, [], [], 0.0), _Direction("y", ey, [], [], 0.0)]
    for beam in joint.beams:
        section = beams.get(beam.type)
        if section is None:
            notes.append(f"{beam.id}: no beam section, left out of the joint")
            continue
        u = np.asarray(beam.direction, dtype=float)
        ux, uy = float(u @ ex), float(u @ ey)
        direction = out[0] if abs(ux) >= abs(uy) else out[1]
        cosine = abs(ux) if direction is out[0] else abs(uy)
        direction.skew = max(direction.skew, math.acos(min(1.0, cosine)))
        side = direction.plus if (ux if direction is out[0] else uy) > 0 else direction.minus
        side.append((beam, section, beam_moments(section)))
    for d in out:
        if d.skew > math.radians(10):
            notes.append(
                f"{joint.id}: a beam meets the column's {d.name} axis at "
                f"{math.degrees(d.skew):.0f}°: taken along that axis"
            )
    return [d for d in out if d.plus or d.minus], notes


def _sum_beams(d: _Direction, sense: int, probable: bool) -> float:
    """Σ beam moments at the joint for a sway sense: +1 hogging on the + side and sagging on
    the - side, -1 the reverse (the beam moments then all turn the joint the same way)."""
    total = 0.0
    for side, hog in ((d.plus, sense > 0), (d.minus, sense < 0)):
        if not side:
            continue
        if probable:
            total += max(m.mpr_hog if hog else m.mpr_sag for _, _, m in side)
        else:
            total += max(m.mn_hog if hog else m.mn_sag for _, _, m in side)
    return total


def strong_column_checks(
    joint: FrameJoint,
    beams: dict[str, RcSection],
    below: JointColumn,
    above: JointColumn | None,
    profile: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Sec 8.3.5.2 (p 1096, special moment frames): ΣMnc ≥ 1.2 ΣMnb at the joint, per column
    axis direction with beams, for beam moments in both senses (the larger ΣMnb governs).
    ``beams``: beam sections by object type id; ``profile``: the column profile below
    (dimensions of the joint). Mnc of each column at its own lowest-strength factored axial
    force (:func:`lowest_column_moment`).

    Not required, a row flagged, when neither column carries more than 0.1 Ag f'c (8.3.5.2(a)).
    BNBC does not say whether slab bars count in ΣMnb; ACI 318-19 18.7.3.2 adds the slab bars
    within the effective flange width when the slab is in tension: not included here."""
    directions, notes = _directions(joint, beams, below.rotation)
    rows: list[dict[str, Any]] = []
    columns = [c for c in (below, above) if c is not None]
    required = max(c.axial_share for c in columns) > _joints("axialLimit")
    ratio = _joints("strongColumnRatio")
    for d in directions:
        mnc = 0.0
        parts = []
        for name, c in (("below", below), ("above", above)):
            if c is None:
                continue
            # Each column bends in the joint's plane about its own axes: the column above may
            # stand turned in plan against the column below.
            own = column_frame(c.section.profile if c is not below else profile, c.rotation, d.axis)
            m, p = lowest_column_moment(c.section, c.pmin, c.pmax, own.compression)
            mnc += m
            parts.append(f"Mnc {name} = {m / 1e6:.1f} kN·m at P = {p / 1e3:.0f} kN")
        mnb = max(_sum_beams(d, s, probable=False) for s in (1, -1))
        note = (
            f"ΣMnc = {mnc / 1e6:.1f} ≥ 1.2 ΣMnb = 1.2 × {mnb / 1e6:.1f} kN·m "
            f"({_section()} Sec 8.3.5.2(b), Eq. 6.8.5); " + "; ".join(parts)
        )
        if above is None:
            note += "; column ends at this joint"
        if not required:
            note += (
                "; not required: the columns carry at most 0.1 Ag f'c (Sec 8.3.5.2(a)), "
                "reported only"
            )
        else:
            note += (
                "; if not met: transverse reinforcement of Sec 8.3.5.4 over the full height "
                "of the columns (8.3.5.2(c)), their lateral strength and stiffness ignored "
                "(8.3.5.2(a))"
            )
        rows.append(
            _check(
                f"Strong column / weak beam, {joint.id} {d.name}",
                ratio * mnb / 1e6,
                mnc / 1e6,
                "kN·m",
                None,
                note,
                flag=not required,
            )
        )
    return rows, notes


def joint_confinement(
    joint: FrameJoint, beams: dict[str, RcSection], profile: Any, rotation: float
) -> tuple[float, int, bool]:
    """(γ, the faces confined, whether the half transverse reinforcement of Sec 8.3.7.2(b) may
    be used): a face is confined when a beam frames into it covering at least three quarters of
    its width (Sec 8.3.7.3, p 1110). γ = 1.7 for four faces, 1.2 for three or two opposite
    faces, 1.0 otherwise. 8.3.7.2(b): members on all four sides, each at least three quarters
    of the column width (here: the face's width), allow half of the 8.3.5.4(a) hoops within the
    depth of the shallowest member and their spacing up to 150 mm. BNBC (like ACI 318-08)
    counts the width only; ACI 318-19 Table 18.8.4.1 also asks for the beam depth and
    distinguishes columns continuing above: not applied."""
    ex, ey = column_axes(rotation)
    faces: dict[tuple[int, int], bool] = {}
    for beam in joint.beams:
        section = beams.get(beam.type)
        if section is None:
            continue
        u = np.asarray(beam.direction, dtype=float)
        ux, uy = float(u @ ex), float(u @ ey)
        axis = 0 if abs(ux) >= abs(uy) else 1
        sign = 1 if (ux if axis == 0 else uy) > 0 else -1
        frame = column_frame(profile, rotation, ex if axis == 0 else ey)
        covered = section.width >= 0.75 * frame.across
        faces[(axis, sign)] = faces.get((axis, sign), False) or covered
    confined = {k for k, v in faces.items() if v}
    count = len(confined)
    opposite = {(0, 1), (0, -1)} <= confined or {(1, 1), (1, -1)} <= confined
    if count == 4:
        gamma = _gamma(4)
    elif count == 3 or opposite:
        gamma = _gamma(3)
    else:
        gamma = _gamma("other")
    return gamma, count, count == 4


def hooked_anchorage_seismic(db: float, fy: float, fc: float, lam: float = 1.0) -> float:
    """ldh [mm] of a bar with a standard 90° hook in a joint of a special moment frame (Sec
    8.3.7.4(a), p 1111, Eq. 6.8.12): max(8 db, 150 mm, fy db / (5.4 √f'c)); lightweight
    concrete (λ < 1): max(10 db, 190 mm, 1.25 times Eq. 6.8.12). BNBC gives it for bars of
    10-36 mm (the text says "Eq. 6.8.9": the formula printed is Eq. 6.8.12)."""
    basic = fy * db / (5.4 * math.sqrt(fc))
    if lam < 1:
        return max(10 * db, 190.0, 1.25 * basic)
    return max(8 * db, 150.0, basic)


def joint_checks(
    joint: FrameJoint,
    beams: dict[str, RcSection],
    below: JointColumn,
    above: JointColumn | None,
    profile: Any,
    lam: float = 1.0,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Sec 8.3.7 (pp 1108-1111) at a joint of a special moment frame, per column axis direction
    with beams:

    - shear: Vj = T1 + T2 - Vcol, T = 1.25 fy As of the beam bars in tension on each side for
      the sway sense giving the larger Vj (8.3.7.1(a)), against φ γ √f'c Aj, φ = 0.85 (6.2.3.3(c),
      p 898), γ from :func:`joint_confinement`. Aj = h bj, h the column dimension along the
      beams; BNBC defines Aj only as "the effective cross-sectional area within a joint in a
      plane parallel to the plane of the reinforcement generating shear" (notation, p 873):
      bj = min(column width, narrowest beam width + h) follows ACI 318-19 18.8.4.3 for a beam
      on the column's axis. Vcol = ΣMpr / (the mid-heights of the columns above and below:
      contraflexure at mid-height), BNBC is silent on it.
    - beam bars passing through: h ≥ 20 db of the largest beam bar (26 db lightweight,
      8.3.7.1(d));
    - beam bars ending in the joint (a beam on one side only): hooked anchorage
      :func:`hooked_anchorage_seismic` within the confined core, h - cover - tie dia
      (8.3.7.1(c), 8.3.7.4(a)).
    """
    directions, notes = _directions(joint, beams, below.rotation)
    gamma, faces, _ = joint_confinement(joint, beams, profile, below.rotation)
    fc = below.section.fc
    rows: list[dict[str, Any]] = []
    lever = (joint.height_below + joint.height_above) / 2 if above else joint.height_below / 2
    stress, phi = _joints("probableStress"), _phi_joint()
    for d in directions:
        frame = column_frame(profile, below.rotation, d.axis)
        h = frame.along
        widths = [s.width for side in (d.plus, d.minus) for _, s, _ in side]
        bj = min(frame.across, min(widths) + h)
        aj = h * bj
        best = (-math.inf, 0.0, 0.0, 0)
        for sense in (1, -1):
            tension = 0.0
            for side, hog in ((d.plus, sense > 0), (d.minus, sense < 0)):
                if side:
                    fy = side[0][1].fy
                    tension += max(
                        stress * fy * (m.as_top if hog else m.as_bottom) for _, _, m in side
                    )
            mpr = _sum_beams(d, sense, probable=True)
            vcol = mpr / lever if lever > 0 else 0.0
            vj = tension - vcol
            if vj > best[0]:
                best = (vj, tension, vcol, sense)
        vj, tension, vcol, _ = best
        capacity = phi * gamma * math.sqrt(fc) * aj
        kind = {1.7: "all four faces", 1.2: "three or two opposite faces"}.get(gamma, "others")
        rows.append(
            _check(
                f"Joint shear, {joint.id} {d.name}",
                max(vj, 0.0) / 1e3,
                capacity / 1e3,
                "kN",
                None,
                f"Vj = ΣT - Vcol = {tension / 1e3:.0f} - {vcol / 1e3:.0f} kN, T = 1.25 fy As "
                f"({_section()} Sec 8.3.7.1(a)); φ γ √f'c Aj, φ = {phi:g} (Sec 6.2.3.3(c)), "
                f"γ = {gamma:g} (confined: {kind}, {faces} face(s), Sec 8.3.7.3), Aj = "
                f"{h:.0f} × {bj:.0f} mm (bj by ACI 318-19 18.8.4.3: {short_name()} does not define it); "
                f"Vcol = ΣMpr / {lever:.0f} mm",
            )
        )
        through = d.plus and d.minus
        if through:
            db = max(m.db_max for side in (d.plus, d.minus) for _, _, m in side)
            factor = 26 if lam < 1 else 20
            rows.append(
                _check(
                    f"Beam bars through joint, {joint.id} {d.name}",
                    factor * db,
                    h,
                    "mm",
                    None,
                    f"column dimension parallel to the beam bars ≥ {factor} db = {factor} × "
                    f"{db:g} mm (Sec 8.3.7.1(d))",
                )
            )
        else:
            core = h - below.cover - below.tie_dia
            for beam, section, m in d.plus or d.minus:
                db = m.db_max
                need = hooked_anchorage_seismic(db, section.fy, fc, lam)
                note = (
                    f"{beam.id} ends here: hooked bars to the far face of the confined core, "
                    f"ldh = max(8 db, 150, fy db / (5.4 √f'c)) = {need:.0f} mm for db = "
                    f"{db:g} mm (Sec 8.3.7.1(c), 8.3.7.4(a), Eq. 6.8.12); available h - cover "
                    f"- tie = {core:.0f} mm"
                )
                if not 10 <= db <= 36:
                    note += f"; {short_name()} gives ldh for 10-36 mm bars only"
                rows.append(
                    _check(
                        f"Beam bar anchorage, {joint.id} {beam.id}", need, core, "mm", None, note
                    )
                )
    if above is None:
        notes.append(
            f"{joint.id}: the column ends at this joint; "
            f"{short_clause('ductileJoints', 'jointShear')} gives no lower joint "
            "shear coefficients for it (ACI 318-19 Table 18.8.4.3 does)"
        )
    return rows, notes


# ─────────────────────────────────── capacity-design shear ───────────────────────────────────


@dataclass(frozen=True)
class Stirrups:
    dia: float
    legs: int
    spacing: float

    @property
    def av_s(self) -> float:
        return self.legs * bar_area(self.dia) / self.spacing


def _shear_rows(
    label: str,
    ve: float,
    v_sway: float,
    axial: float,
    gross_area: float,
    fc: float,
    fyt: float,
    bw: float,
    d: float,
    vc_full: float,
    stirrups: Stirrups | None,
    special: bool,
    note: str,
) -> list[dict[str, Any]]:
    """Ve against φ (Vc + Vs), with Vc = 0 by Sec 8.3.8.2(a) in special moment frames, and the
    required transverse steel Av/s against the provided."""
    zero = special and v_sway >= 0.5 * ve and axial < _joints("vcZeroAxial") * gross_area * fc
    vc = 0.0 if zero else vc_full
    fyt = min(fyt, rc_value("FYT_SHEAR_MAX"))
    vs_max = 0.66 * math.sqrt(fc) * bw * d
    av_s = stirrups.av_s if stirrups else 0.0
    vs = min(av_s * fyt * d, vs_max)
    capacity = rc_value("PHI_SHEAR") * (vc + vs)
    need = max(ve / rc_value("PHI_SHEAR") - vc, 0.0) / (fyt * d)
    parts = [
        note,
        f"Vc = {vc / 1e3:.1f} kN"
        + (
            " (0: the earthquake part is at least half of Ve and Pu < 0.05 Ag f'c, Sec 8.3.8.2(a))"
            if zero
            else ""
        ),
        f"Vs = {vs / 1e3:.1f} kN, fyt ≤ {rc_value('FYT_SHEAR_MAX'):g} MPa (Sec 8.3.3.4(d), 6.4.3.2), "
        + f"φ = {rc_value('PHI_SHEAR'):g}",
    ]
    if need * fyt * d > vs_max:
        parts.append("Ve needs Vs above 0.66 √f'c bw d: enlarge the section")
    rows = [
        _check(label, ve / 1e3, capacity / 1e3, "kN", None, "; ".join(p for p in parts if p)),
        _check(
            f"{label}: transverse steel Av/s",
            need,
            av_s,
            "mm²/mm",
            None,
            f"Av/s required = (Ve / φ - Vc) / (fyt d), d = {d:.0f} mm"
            + ("; none: φ Vc carries Ve, the confinement rules set the ties" if need <= 0 else "")
            + (
                f"; provided {stirrups.legs} legs Ø{stirrups.dia:g} at {stirrups.spacing:g} mm"
                if stirrups
                else "; no transverse bars"
            )
            + "; the hinge-zone spacing (the model holds one spacing)",
        ),
    ]
    return rows


def _frame_level(level: str) -> bool | None:
    """True for a special moment frame, False for an intermediate one, None for an ordinary
    one (Sec 8.3.9, p 1113, has no capacity-design shear rule); anything else is an error."""
    if level == "special":
        return True
    if level == "intermediate":
        return False
    if level == "ordinary":
        return None
    raise DesignError(f"unknown moment frame level {level!r}: special, intermediate or ordinary")


def beam_capacity_shear(
    section: RcSection,
    clear_span: float,
    gravity_shear: float,
    analysis_shear: float = 0.0,
    stirrups: Stirrups | None = None,
    axial: float = 0.0,
    level: str = "special",
    doubled_e_shear: float | None = None,
    lam: float = 1.0,
) -> list[dict[str, Any]]:
    """The capacity-design shear of a beam of a moment frame [checks]:

    - ``level`` "special" (Sec 8.3.8.1(a), p 1111): Ve = (Mpr,hog + Mpr,sag) / ln + Vg: moments
      of opposite sign at the two faces (the same section at both ends), ``gravity_shear`` Vg
      [N] the shear of the factored tributary gravity load at the face (BNBC says "factored
      tributary gravity load"; the gravity part 1.2D + 1.0L of the combination with E is what
      the caller passes); at least the analysis shear ``analysis_shear`` (as 8.3.8.1(b) says
      for columns). Vc = 0 by 8.3.8.2(a) with ``axial`` the factored compression [N].
    - "intermediate" (Sec 8.3.10.3, p 1114): the smaller of (Mn,hog + Mn,sag) / ln + Vg and
      ``doubled_e_shear``, the largest shear of the combinations with E doubled (when given).
    ``clear_span`` ln [mm]; ``stirrups`` the transverse bars in the end zones."""
    if not isinstance(section.profile, RectangleProfile):
        raise DesignError("capacity shear is checked for rectangular beams only")
    m = beam_moments(section)
    resistance = shear(
        section,
        stirrups.dia if stirrups else None,
        stirrups.legs if stirrups else 0,
        stirrups.spacing if stirrups else None,
        lam,
    )
    special = _frame_level(level)
    if special is None:
        return []
    if special:
        v_sway = (m.mpr_hog + m.mpr_sag) / clear_span
        ve = max(v_sway + abs(gravity_shear), abs(analysis_shear))
        note = (
            f"Ve = (Mpr- + Mpr+) / ln + Vg = ({m.mpr_hog / 1e6:.1f} + {m.mpr_sag / 1e6:.1f}) "
            f"kN·m / {clear_span:.0f} mm + {abs(gravity_shear) / 1e3:.1f} kN, Mpr at 1.25 fy, "
            f"φ = 1 ({_section()} Sec 8.3.8.1(a))"
        )
        label = "Capacity shear Ve (SMF)"
    else:
        v_sway = (m.mn_hog + m.mn_sag) / clear_span
        ve = v_sway + abs(gravity_shear)
        note = (
            f"(Mn- + Mn+) / ln + Vg = ({m.mn_hog / 1e6:.1f} + {m.mn_sag / 1e6:.1f}) kN·m / "
            f"{clear_span:.0f} mm + {abs(gravity_shear) / 1e3:.1f} kN"
        )
        if doubled_e_shear is not None and doubled_e_shear < ve:
            ve = abs(doubled_e_shear)
            note += f"; the combinations with 2E give less: {ve / 1e3:.1f} kN governs"
        note += f" ({_section()} Sec 8.3.10.3)"
        label = "Capacity shear (IMF)"
    return _shear_rows(
        label,
        ve,
        v_sway,
        axial,
        section.gross_area,
        section.fc,
        section.fy,
        section.width,
        resistance.d,
        resistance.vc,
        stirrups,
        special,
        note,
    )


def _column_shear_depth(section: RcSection, frame: ColumnFrame) -> tuple[float, float]:
    """(bw, d) of a column for shear along ``frame``'s direction: d from the compression face
    to the centroid of the bars of the far half; circles bw = D, d = 0.8 D (ACI 318-19
    22.5.2.2, BNBC is silent)."""
    if isinstance(section.profile, CircleProfile):
        diameter = 2 * section.profile.radius
        return diameter, 0.8 * diameter
    # One rule for d with the non-ductile column shear (saengine.design.column_shear): bars on
    # the centre line are not in the far half (counting them pulled d in, 305 mm instead of
    # 340 mm for 3 bars a face of a 400 mm column).
    from saengine.design.column_shear import shear_depth

    return frame.across, shear_depth(section, frame.compression)


def column_capacity_shear(
    section: RcSection,
    rotation: float,
    direction: np.ndarray,
    clear_height: float,
    pmin: float,
    pmax: float,
    analysis_shear: float = 0.0,
    beam_limit: float | None = None,
    stirrups: Stirrups | None = None,
    level: str = "special",
    doubled_e_shear: float | None = None,
    lam: float = 1.0,
    base_beam_moment: float | None = None,
) -> list[dict[str, Any]]:
    """The capacity-design shear of a column [checks] along the plan ``direction`` (the
    moments bend it in that plane):

    - "special" (Sec 8.3.8.1(b), p 1111): Ve = 2 Mpr / lu, Mpr the largest over the factored
      axial forces ``pmin`` … ``pmax`` [N] (:func:`highest_column_moment`), not more than
      ``beam_limit`` [N] (the shear the beams' Mpr at the two joints can deliver to this column,
      :func:`beam_limited_column_shear`) and not less than ``analysis_shear``. A column on a
      base (beams at its top joint only) gives ``base_beam_moment`` [N·mm] instead: its share
      of the top joint's ΣMpr, so Ve is at most (Mpr + min(Mpr, that share)) / lu, the hinge at
      the base taking the column's own Mpr. Vc = 0 by 8.3.8.2(a) when Pu,min < 0.05 Ag f'c and
      the earthquake part is at least half.
    - "intermediate" (Sec 8.3.10.3): the smaller of 2 Mn / lu (Mn the largest over the range)
      and ``doubled_e_shear``.
    Vc otherwise 0.17 λ √f'c bw d: the axial compression's increase (ACI 318-19 Eq.
    22.5.6.1) is left out, on the safe side."""
    special = _frame_level(level)
    if special is None:
        return []
    frame = column_frame(section.profile, rotation, np.asarray(direction, dtype=float))
    m, p = highest_column_moment(section, pmin, pmax, frame.compression, probable=special)
    v_moment = 2 * m / clear_height
    bw, d = _column_shear_depth(section, frame)
    if special:
        ve = v_moment
        note = (
            f"Ve = 2 Mpr / lu = 2 × {m / 1e6:.1f} kN·m / {clear_height:.0f} mm, Mpr at "
            f"P = {p / 1e3:.0f} kN ({_section()} Sec 8.3.8.1(b))"
        )
        if beam_limit is not None and beam_limit < ve:
            ve = beam_limit
            note += f"; limited by the beams' Mpr at the joints: {ve / 1e3:.1f} kN"
        elif base_beam_moment is not None and base_beam_moment < m:
            ve = (m + base_beam_moment) / clear_height
            note += (
                f"; on a base: (Mpr + the beams' {base_beam_moment / 1e6:.1f} kN·m at the top "
                f"joint) / lu = {ve / 1e3:.1f} kN"
            )
        if abs(analysis_shear) > ve:
            ve = abs(analysis_shear)
            note += f"; the analysis shear {ve / 1e3:.1f} kN governs"
        v_sway = ve
        label = f"Capacity shear Ve (SMF column, {frame.axis})"
    else:
        ve = v_moment
        note = f"2 Mn / lu = 2 × {m / 1e6:.1f} kN·m / {clear_height:.0f} mm"
        if doubled_e_shear is not None and abs(doubled_e_shear) < ve:
            ve = abs(doubled_e_shear)
            note += f"; the combinations with 2E give less: {ve / 1e3:.1f} kN governs"
        note += f" ({_section()} Sec 8.3.10.3)"
        v_sway = ve
        label = f"Capacity shear (IMF column, {frame.axis})"
    vc = 0.17 * lam * min(math.sqrt(section.fc), 8.3) * bw * d
    return _shear_rows(
        label,
        ve,
        v_sway,
        pmin,
        section.gross_area,
        section.fc,
        section.fy,
        bw,
        d,
        vc,
        stirrups,
        special,
        note,
    )


def beam_limited_column_shear(
    mpr_beams_top: float,
    mpr_beams_bottom: float,
    clear_height: float,
    share_top: float = 0.5,
    share_bottom: float = 0.5,
) -> float:
    """The column shear [N] the beams' probable moments can deliver (Sec 8.3.8.1(b): "need
    not exceed those determined from joint strengths based on the probable moment strength
    Mpr of the transverse members framing into the joint"): (share_top ΣMpr,top +
    share_bottom ΣMpr,bottom) / lu, each joint's ΣMpr shared between the columns above and
    below it (0.5 each by default, 1 where the column ends; BNBC does not say how to share)."""
    return (share_top * mpr_beams_top + share_bottom * mpr_beams_bottom) / clear_height


def joint_beam_mpr(
    joint: FrameJoint, beams: dict[str, RcSection], rotation: float
) -> dict[str, float]:
    """ΣMpr of the beams at a joint per column axis ("x", "y"), the larger sway sense."""
    directions, _ = _directions(joint, beams, rotation)
    return {d.name: max(_sum_beams(d, s, probable=True) for s in (1, -1)) for d in directions}


# ─────────────────────────────────── demands from the analysis ───────────────────────────────────


@dataclass(frozen=True)
class SeismicDemands:
    """What a member's analysis gives the capacity design, over the combinations with E."""

    pmin: float  # N, compression positive
    pmax: float
    shear: float  # N, the largest |V|
    gravity_shear: float  # N, the largest |V| of the gravity part (forces less the lateral)
    doubled_e_shear: float  # N, the largest |V + V_lateral| (the lateral part doubled)
    shear_x: float = 0.0  # N, the other shear of a column ("Vx", when the forces give it)
    doubled_e_shear_x: float = 0.0


def stacked_parts(parts: list[Any] | None, combinations: list[int]) -> np.ndarray | None:
    """The arrays ``parts[c]`` of ``combinations`` stacked (combination first), or None when
    they are not all arrays of one shape (the caller then goes one by one)."""
    if not parts or not combinations or any(c >= len(parts) for c in combinations):
        return None
    chosen = [parts[c] for c in combinations]
    if not all(isinstance(a, np.ndarray) for a in chosen):
        return None
    if any(a.shape != chosen[0].shape for a in chosen):
        return None
    return np.stack(chosen)


def seismic_demands(
    pieces: list[Any], combinations: list[int], turned: bool, profile_forces: Any
) -> SeismicDemands:
    """From a member's analysis pieces (``check._Piece``: ``forces`` and ``sway`` per
    combination) over the combination indices ``combinations`` (those with E), through
    ``profile_forces`` (``check._profile_forces``: ``P``, ``Vy`` and, when it gives it, ``Vx``;
    it is given the combinations stacked, a leading axis before the stations, where they agree
    in shape)."""
    pmin, pmax = math.inf, -math.inf
    v = vg = v2 = vx = v2x = 0.0
    for piece in pieces:
        forces_all = stacked_parts(piece.forces, combinations)
        lateral_all = (
            stacked_parts(piece.sway, combinations)
            if piece.sway is not None
            else (None if forces_all is None else np.zeros_like(forces_all))
        )
        if (
            forces_all is not None
            and lateral_all is not None
            and (lateral_all.shape == forces_all.shape)
        ):
            # Every combination at once: the same extremes as one by one.
            blocks = [(forces_all, lateral_all)]
        else:
            blocks = [
                (
                    piece.forces[c],
                    piece.sway[c] if piece.sway is not None else np.zeros_like(piece.forces[c]),
                )
                for c in combinations
            ]
        for forces, lateral in blocks:
            total = profile_forces(piece, turned, forces)
            sway = profile_forces(piece, turned, lateral)
            pmin = min(pmin, float(np.min(total["P"])))
            pmax = max(pmax, float(np.max(total["P"])))
            v = max(v, float(np.max(np.abs(total["Vy"]))))
            vg = max(vg, float(np.max(np.abs(total["Vy"] - sway["Vy"]))))
            v2 = max(v2, float(np.max(np.abs(total["Vy"] + sway["Vy"]))))
            if "Vx" in total:
                vx = max(vx, float(np.max(np.abs(total["Vx"]))))
                v2x = max(v2x, float(np.max(np.abs(total["Vx"] + sway["Vx"]))))
    if not math.isfinite(pmin):
        pmin = pmax = 0.0
    return SeismicDemands(pmin, pmax, v, vg, v2, vx, v2x)


# ─────────────────────────────────────── foundations ───────────────────────────────────────


def hooked_development(
    db: float, fy: float, fc: float, lam: float = 1.0, psi_e: float = 1.0, factor: float = 1.0
) -> float:
    """ldh [mm] of a bar with a standard hook in tension (Sec 8.2.6.1-8.2.6.3, p 1079):
    0.24 ψe fy db / (λ √f'c) times the applicable factors of 8.2.6.3 (``factor``), not less
    than 8 db nor 150 mm."""
    return max(0.24 * psi_e * fy * db / (lam * math.sqrt(fc)) * factor, 8 * db, 150.0)


def column_dowel_checks(
    column_id: str,
    db: float,
    fy: float,
    fc: float,
    footing_thickness: float,
    cover: float,
    mesh_dia: float,
    lam: float = 1.0,
) -> list[dict[str, Any]]:
    """Sec 8.3.11.2(a), (b) (p 1120): the column bars extend into the footing, mat or pile cap
    and are developed in tension at the interface; a fixed-base column's hooked bars have 90°
    hooks near the bottom of the foundation, free ends towards the column's centre. The hooked
    development (Sec 8.2.6, ``fc`` of the foundation) against the depth available above the
    bottom mesh: thickness - cover - 2 mesh bars."""
    need = hooked_development(db, fy, fc, lam)
    available = footing_thickness - cover - 2 * mesh_dia
    return [
        _check(
            f"Column bars into foundation, {column_id}",
            need,
            available,
            "mm",
            None,
            f"ldh = max(0.24 fy db / (λ √f'c), 8 db, 150) = {need:.0f} mm for db = {db:g} mm "
            f"({_section()} Sec 8.2.6.1, 8.2.6.2); available t - cover - 2 mesh bars = "
            f"{available:.0f} mm; 90° hooks at the bottom, turned towards the column's centre "
            "(Sec 8.3.11.2(a), (b))",
        )
    ]


def column_near_footing_edge(
    column_centre: tuple[float, float],
    column_size: tuple[float, float],
    footing_centre: tuple[float, float],
    footing_size: tuple[float, float],
    footing_thickness: float,
) -> bool:
    """Sec 8.3.11.2(c) (p 1120): a column with an edge within half the footing depth of a
    footing edge needs the transverse reinforcement of Sec 8.3.5.4 below the top of the footing,
    extended into it. Plan rectangles aligned with each other (sizes along X, Y)."""
    for k in range(2):
        gap_low = (column_centre[k] - column_size[k] / 2) - (
            footing_centre[k] - footing_size[k] / 2
        )
        gap_high = (footing_centre[k] + footing_size[k] / 2) - (
            column_centre[k] + column_size[k] / 2
        )
        if min(gap_low, gap_high) < footing_thickness / 2:
            return True
    return False


def grade_beam_tie_check(
    beam_id: str, width: float, depth: float, tie_spacing: float | None
) -> dict[str, Any]:
    """Sec 8.3.11.3(b) (p 1120): grade beams acting as ties between footings or pile caps have
    closed ties at most min(half the smallest dimension, 300 mm) apart. (Its size rule, clear
    spacing / 20 up to 450 mm, is checked by
    :func:`saengine.substructure.shallow.design_tie_beam`.)"""
    limit = min(0.5 * min(width, depth), 300.0)
    if tie_spacing is None:
        return _check(
            f"Grade beam ties, {beam_id}",
            math.inf,
            limit,
            "mm",
            None,
            f"no closed ties: they are required at ≤ {limit:.0f} mm (Sec 8.3.11.3(b))",
        )
    return _check(
        f"Grade beam ties, {beam_id}",
        tie_spacing,
        limit,
        "mm",
        None,
        f"closed ties at ≤ min(smallest dimension / 2, 300 mm) = {limit:.0f} mm "
        f"({_section()} Sec 8.3.11.3(b)); grade beams bent by the columns of the seismic system "
        "also follow Sec 8.3.4 (8.3.11.3(c))",
    )


def pile_confined_length(
    dimension: float, unsupported: float = 0.0, flexural_length: float | None = None
) -> float:
    """The length [mm] from the pile cap's bottom over which a pile has the detailing of Sec
    8.3, the larger of:

    - Sec 8.3.11.4(d) (p 1121): the transverse reinforcement of Sec 8.3.5.4 over at least 5
      times its cross-section dimension and 1.8 m, plus the length in soil unable to support it
      laterally, air or water (``unsupported``);
    - Sec 1.8.5.1 (p 507, seismic zones 2, 3 and 4): the criteria and detailing of Sec 8.3 over
      120 percent of the flexural length, when ``flexural_length`` [mm] is given. BNBC does not
      define the flexural length; the depth to the pile's lowest point of zero moment (or of
      fixity) under the lateral load is what the caller passes.

    One- and two-storey stud bearing wall buildings are exempt from 8.3.11.4(d) (8.3.11.4(f))."""
    length = max(5 * dimension, 1800.0) + unsupported
    if flexural_length is not None:
        length = max(length, 1.2 * flexural_length)
    return length


# ─────────────────────────────── members outside the seismic system ───────────────────────────────


def induced_forces(gravity: np.ndarray, lateral: np.ndarray, factor: float) -> float:
    """The largest |gravity ± factor × lateral| over the stations: the moments or shears of a
    member following the design displacement. ``factor``: Cd / I for the design displacement
    δu of Sec 8.3.12 (the analysis' lateral case gives the elastic δxe; BNBC Part 6 Chapter 2
    amplifies it by Cd / I), 2 for "twice the lateral displacement under the factored lateral
    forces" of Sec 8.3.9.1 (p 1113)."""
    g = np.abs(np.asarray(gravity, dtype=float))
    lat = np.abs(np.asarray(lateral, dtype=float))
    return float(np.max(g + factor * lat)) if g.size else 0.0


def non_sfrs_checks(
    member_id: str,
    section: RcSection,
    gravity_axial: float,
    induced_moment: float,
    induced_shear: float,
    phi_mn: float,
    phi_vn: float,
    category: str | None,
    stirrups: Stirrups | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """A frame member not designated part of the seismic-force-resisting system.

    SDC D (Sec 8.3.12, pp 1122-1123): the induced moment and shear under the design
    displacement δu with the factored gravity forces (1.2D + 1.0L + 0.2S or 0.9D; L may take
    0.5 except garages, assembly and L > 4.8 kN/m²) against φMn, φVn:

    - within them (8.3.12.2): Pu ≤ Ag f'c / 10: Sec 8.3.4.2(a) and stirrups at ≤ d/2 over the
      full length (a); above: Sec 8.3.5.3(a) and 8.3.5.4 with ties at so ≤ min(6 db, 150 mm)
      over the full length (b); above 0.35 P0: (b) with half of the 8.3.5.4(a) amount (c);
    - beyond them, or not computed (8.3.12.3): materials of 8.3.3.3, 8.3.3.4; Pu ≤ Ag f'c / 10:
      Sec 8.3.4.2 and 8.3.8, stirrups ≤ d/2 over the length; above: 8.3.5.3, 8.3.5.4, 8.3.7.1
      and 8.3.8.

    Other categories (Sec 8.3.3.1(d), 8.3.9.1, p 1113, twice the lateral displacement): beyond
    φMn, Pu ≤ 0.1 Ag f'c: 8.3.4.2(a) and 8.3.8.1(a); above: 8.3.5.4, 8.3.7.2(a) and 8.3.8.1(b);
    within φMn: 8.3.4.2(a).

    Returns the checks SAEngine has the data for (the induced forces, and the full-length
    stirrup or tie spacing) and the detailing clauses that apply, as notes for the member
    checks of :mod:`saengine.design.ductile_members` to run."""
    fc, ag = section.fc, section.gross_area
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    light = gravity_axial <= _joints("axialLimit") * ag * fc
    exceeds = induced_moment > phi_mn or induced_shear > phi_vn
    if category == "D":
        rows.append(
            _check(
                f"Induced moment, {member_id}",
                induced_moment / 1e6,
                phi_mn / 1e6,
                "kN·m",
                None,
                f"under the design displacement δu with the gravity forces ({_section()} "
                "Sec 8.3.12.2); beyond φMn the detailing of Sec 8.3.12.3 applies",
                flag=True,
            )
        )
        rows.append(
            _check(
                f"Induced shear, {member_id}",
                induced_shear / 1e3,
                phi_vn / 1e3,
                "kN",
                None,
                "under the design displacement δu with the gravity forces (Sec 8.3.12.2)",
                flag=True,
            )
        )
        d = _depth(section)
        if exceeds:
            clauses = (
                "8.3.3.3, 8.3.3.4, 8.3.4.2, 8.3.8"
                if light
                else "8.3.3.3, 8.3.3.4, 8.3.5.3, 8.3.5.4, 8.3.7.1, 8.3.8"
            )
            notes.append(f"{member_id}: Sec 8.3.12.3 applies: {clauses}")
            if light:
                rows.append(_full_length(member_id, stirrups, d / 2, "d / 2", "8.3.12.3(b)"))
        elif light:
            notes.append(f"{member_id}: Sec 8.3.12.2(a) applies: 8.3.4.2(a)")
            rows.append(_full_length(member_id, stirrups, d / 2, "d / 2", "8.3.12.2(a)"))
        else:
            db = min((b.dia for b in section.bars), default=0.0)
            so = min(6 * db, 150.0)
            half = gravity_axial > 0.35 * section.p0
            notes.append(
                f"{member_id}: Sec 8.3.12.2({'c' if half else 'b'}) applies: 8.3.5.3(a), "
                f"8.3.5.4{' with half the 8.3.5.4(a) amount' if half else ''}"
            )
            rows.append(
                _full_length(
                    member_id, stirrups, so, "so = min(6 db, 150 mm)", "8.3.12.2(b)", tie=True
                )
            )
    else:
        rows.append(
            _check(
                f"Induced moment, {member_id}",
                induced_moment / 1e6,
                phi_mn / 1e6,
                "kN·m",
                None,
                f"under twice the lateral displacement of the factored lateral forces ({_section()}"
                " Sec 8.3.9.1); beyond φMn the detailing of 8.3.9.1(a) applies",
                flag=True,
            )
        )
        if induced_moment > phi_mn:
            clauses = "8.3.4.2(a), 8.3.8.1(a)" if light else "8.3.5.4, 8.3.7.2(a), 8.3.8.1(b)"
            notes.append(f"{member_id}: Sec 8.3.9.1(a) applies: {clauses}")
        else:
            notes.append(f"{member_id}: Sec 8.3.9.1(b) applies: 8.3.4.2(a)")
        if not light:
            notes.append(f"{member_id}: ties of Sec 8.3.9.2 (Pu > 0.1 Ag f'c)")
    return rows, notes


def _depth(section: RcSection) -> float:
    try:
        return section.effective_depth(top=False)
    except DesignError:
        return 0.8 * section.depth


def _full_length(
    member_id: str,
    stirrups: Stirrups | None,
    limit: float,
    rule: str,
    clause: str,
    tie: bool = False,
) -> dict[str, Any]:
    what = "Tie" if tie else "Stirrup"
    spacing = stirrups.spacing if stirrups else math.inf
    return _check(
        f"{what} spacing (full length), {member_id}",
        spacing,
        limit,
        "mm",
        None,
        f"≤ {rule} = {limit:.0f} mm over the full length ({_section()} Sec {clause})"
        + ("" if stirrups else "; no transverse bars"),
    )

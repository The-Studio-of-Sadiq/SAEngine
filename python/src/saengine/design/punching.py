"""Two-way (punching) shear at columns of flat slabs, footings and mats, with shear
reinforcement where the concrete alone is not enough.

Code basis the default pack's BNBC 2020 Part 6 Chapter 6, Sec 6.4.10 (pdf pp. 937-943), which follows ACI 318:

- Critical section at d/2 from the column faces, its perimeter b0 a minimum (6.4.10.1.2, p. 937),
  four straight sides for rectangular columns (6.4.10.1.3); sides beyond a free edge are left out
  and the others run to the edge (:func:`saengine.design.slab.critical_section`).
- vc without shear reinforcement: the least of 0.17 (1 + 2/β), 0.083 (αs d / b0 + 2) and 0.33
  times λ √f'c (Eq. 6.6.72-6.6.74, p. 938), αs 40 / 30 / 20 for interior / edge / corner
  columns. As the rest of SAEngine (:func:`saengine.design.slab.punching_capacity`) these are
  also multiplied by the size factor λs of ACI 318-19 22.5.5.1.3, which the default pack's BNBC does not have
  (conservative).
- Openings closer than 10 h to the column: the part of the critical section between the
  straight lines from the column centroid tangent to the opening is ineffective (6.4.10.6.1,
  p. 942).
- Unbalanced moment: γv Mu transferred by eccentric shear, γv = 1 - γf, the stress varying
  linearly about the centroid of the critical section, v = Vu / (b0 d) + γv Mu c / Jc
  (6.4.10.7, Eq. 6.6.77-6.6.80, pp. 942-943).
- Stirrups (single or multi-leg, bars or wires): permitted where d >= 150 mm and d >= 16 db
  (6.4.10.3); vc at most 0.17 λ √f'c (6.4.10.3.1), vs = Av fyt / (b0 s) with Av all the legs of
  one peripheral line (Eq. 6.6.56 with 6.4.10.3.1), vn at most 0.5 √f'c (6.4.10.3.2); the first
  line at most d/2 from the column face, lines at most d/2 apart, legs along a line at most 2d
  apart (6.4.10.3.3, p. 938).
- Headed shear studs (6.4.10.5, p. 941): vc at most 0.25 λ √f'c and vn at most 0.66 λ √f'c
  (6.4.10.5.1), Av fyt / (b0 s) at least 0.17 √f'c; the first line at most d/2 from the face,
  constant spacing of at most 0.75 d where vu <= 0.5 φ √f'c and 0.5 d above it (6.4.10.5.2),
  studs along the first line at most 2d apart (6.4.10.5.3). Here vc with studs is also kept
  within Eq. 6.6.72-6.6.73 (ACI 318-19 Table 22.6.6.1).
- Beyond the reinforcement: v at most 0.17 φ λ √f'c on the critical section d/2 outside the
  outermost line (6.4.10.5.4 for studs, 6.4.10.7.2 for stirrups). That outer section is taken
  as the octagon through the points d/2 beyond the last stud of the rails at the column corners
  (straight across each face, chords across the corners; ACI R22.6.4.2), clipped by the slab
  or footing edges and the opening shadows.
- φ = 0.75 (:data:`saengine.design.rc.PHI_SHEAR`). Units: mm, MPa, N, N·mm.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import LineString, MultiPoint, Polygon, box
from shapely.geometry.base import BaseGeometry

from saengine.design.clauses import clause
from saengine.design.rc import bar_area
from saengine.design.rc import value as rc_value
from saengine.design.slab import critical_section, punching_capacity

__all__ = [
    "PUNCHING_METHOD",  # noqa: F822 - module __getattr__ (read from the code pack)
    "STIRRUP_DIAMETERS",
    "STUD_DIAMETERS",
    "STUD_FY",
    "Demand",
    "Perimeter",
    "PunchingResult",
    "PunchingRow",
    "Reinforcement",
    "ShearReinforcement",
    "column_perimeter",
    "design_reinforcement",
    "footing_punching",
    "outer_perimeter",
    "provided_of",
    "recheckable",
    "slab_punching",
    "unit_relief",
]


def _punching_method() -> list[str]:
    """``PUNCHING_METHOD``: the method text of the design report, with the clauses of the code pack in
    force (read as a module attribute)."""
    return [
        (
            f"Punching ({clause('punching', 'punching')}): critical section at d/2 from the "
            "column faces, cut by free edges and by the shadow of openings within 10 h "
            "(6.4.10.6.1); vc the least of Eq. 6.6.72-6.6.74 (times λs of ACI 318-19 22.5.5.1.3); "
            "v = Vu/(b0 d) + γv Mu c/Jc about the section's centroid (6.4.10.7). Where v > φ vc: "
            "headed shear studs (6.4.10.5: vc <= 0.25 √f'c, vn <= 0.66 √f'c, Av fyt/(b0 s) >= "
            "0.17 √f'c, s <= 0.75 d or 0.5 d) or stirrups (6.4.10.3: d >= 150 mm and 16 db, "
            "vc <= 0.17 √f'c, vn <= 0.5 √f'c, s <= d/2), the first line within d/2 of the face, "
            "elements along it at most 2d apart; enough lines for v <= 0.17 φ √f'c on the section "
            "d/2 outside the last line (6.4.10.5.4, 6.4.10.7.2); beyond vn,max: a thicker slab, "
            "a drop panel or a larger column."
        )
    ]


#: Headed stud shank diameters offered [mm] and their yield strength [MPa] (ASTM A1044 studs
#: have fy >= 51 ksi, 350 MPa).
STUD_DIAMETERS = (10.0, 12.0, 16.0, 20.0)
STUD_FY = 350.0
#: Stirrup bar diameters offered [mm]; stirrup fyt is taken at most 420 MPa (ACI 20.2.2.4).
STIRRUP_DIAMETERS = (8.0, 10.0, 12.0)
STIRRUP_FY_MAX = 420.0
#: The most peripheral lines a proposal uses before it asks for a thicker slab.
MAX_LINES = 30
STEP = 5.0  # spacings are rounded down to this [mm]
FAIL = 1.001  # the least utilisation a failing check reports (it is rounded to 3 decimals)


# ─────────────────────────────────────── geometry ───────────────────────────────────────


@dataclass
class Perimeter:
    """A critical section in the column's axes (u, v) [mm], origin at the column centre: its
    straight pieces ``(u0, v0, u1, v1)``, the depth ``d`` and where it stands."""

    pieces: list[tuple[float, float, float, float]]
    d: float
    location: str  # interior, edge, corner
    widths: tuple[float, float]  # b1 along u, b2 along v (for γv)
    faces: tuple[bool, bool, bool, bool] = (True, True, True, True)  # -u, +u, -v, +v sides kept
    ineffective: float = 0.0  # perimeter left out for openings [mm]
    area: float = 0.0  # plan area inside the section, within the member [mm²]

    @property
    def b0(self) -> float:
        return sum(math.hypot(p[2] - p[0], p[3] - p[1]) for p in self.pieces)

    @property
    def alpha_s(self) -> float:
        return {"interior": 40.0, "edge": 30.0}.get(self.location, 20.0)

    def centroid(self) -> tuple[float, float]:
        total = self.b0
        if total <= 0:
            return 0.0, 0.0
        u = sum(math.hypot(p[2] - p[0], p[3] - p[1]) * (p[0] + p[2]) / 2 for p in self.pieces)
        v = sum(math.hypot(p[2] - p[0], p[3] - p[1]) * (p[1] + p[3]) / 2 for p in self.pieces)
        return u / total, v / total

    def polar(self, along_u: bool) -> tuple[float, float]:
        """Jc [mm⁴] about the centroid for a moment bending the slab along u (``along_u``) or
        v, and c, the farthest point of the section that way. Each straight piece adds
        d ∫ a² ds plus, for its part along the bending direction, L d³ / 12 (the analogue of
        the polar moment of inertia, ACI R8.4.4.2.3, for pieces of any direction)."""
        uc, vc = self.centroid()
        d = self.d
        jc = reach = 0.0
        for u0, v0, u1, v1 in self.pieces:
            length = math.hypot(u1 - u0, v1 - v0)
            if length <= 0:
                continue
            a0, a1 = (u0 - uc, u1 - uc) if along_u else (v0 - vc, v1 - vc)
            cos = abs(a1 - a0) / length
            jc += d * length * (a0 * a0 + a0 * a1 + a1 * a1) / 3 + length * d**3 / 12 * cos**2
            reach = max(reach, abs(a0), abs(a1))
        return jc, reach

    def stress(self, vu: float, m_u: float, m_v: float) -> tuple[float, float, float, float]:
        """(v, Vu/(b0 d), γv for m_u, γv for m_v) [MPa]: the largest shear stress under ``vu``
        [N] and the unbalanced moments [N·mm] bending the slab along u (``m_u``) and v,
        v = Vu/(b0 d) + Σ γv |M| c / Jc (both terms at their farthest points, conservative),
        γv = 1 - 1 / (1 + (2/3) √(b1 / b2)) (Eq. 6.6.77)."""
        b0, d = self.b0, self.d
        width_u, width_v = self.widths
        gamma_u = 1 - 1 / (1 + 2 / 3 * math.sqrt(width_u / width_v))
        gamma_v = 1 - 1 / (1 + 2 / 3 * math.sqrt(width_v / width_u))
        direct = vu / (b0 * d)
        stress = direct
        for gamma, moment, along_u in ((gamma_u, m_u, True), (gamma_v, m_v, False)):
            jc, reach = self.polar(along_u)
            if jc > 0:
                stress += gamma * abs(moment) * reach / jc
        return stress, direct, gamma_u, gamma_v


def _local(points: Sequence[Sequence[float]], centre: Sequence[float], angle: float) -> list:
    t = math.radians(angle)
    cu, su = math.cos(t), math.sin(t)
    cx, cy = float(centre[0]), float(centre[1])
    return [
        ((p[0] - cx) * cu + (p[1] - cy) * su, -(p[0] - cx) * su + (p[1] - cy) * cu) for p in points
    ]


def _shadows(
    openings: Sequence[Sequence[Sequence[float]]],
    c1: float,
    c2: float,
    reach: float | None,
) -> tuple[list[BaseGeometry], list[str]]:
    """The ineffective wedges (local axes) of the openings: from the column centroid, between
    the straight lines tangent to each opening (6.4.10.6.1); only openings within ``reach`` of
    the column (10 h) count. An opening around the column centre is skipped with a note."""
    column = box(-c1 / 2, -c2 / 2, c1 / 2, c2 / 2)
    wedges: list[BaseGeometry] = []
    notes: list[str] = []
    for opening in openings:
        if len(opening) < 3:
            continue
        hull = Polygon(opening).convex_hull
        if reach is not None and hull.distance(column) >= reach:
            continue
        if hull.contains(column.centroid) or hull.intersects(column):
            notes.append("an opening overlaps the column: left out of the critical section")
            continue
        far = []
        for x, y in hull.exterior.coords:
            r = math.hypot(x, y)
            far.append((x / r * 1e7, y / r * 1e7))
        wedges.append(MultiPoint([(0.0, 0.0), *hull.exterior.coords, *far]).convex_hull)
    return wedges, notes


def _segments(geometry: BaseGeometry) -> list[tuple[float, float, float, float]]:
    """The straight pieces of a (multi)line geometry."""
    result = []
    parts = getattr(geometry, "geoms", [geometry])
    for part in parts:
        if part.is_empty or part.geom_type not in ("LineString", "LinearRing"):
            if part.geom_type in ("MultiLineString", "GeometryCollection"):
                result += _segments(part)
            continue
        coords = list(part.coords)
        for (u0, v0), (u1, v1) in itertools.pairwise(coords):
            if math.hypot(u1 - u0, v1 - v0) > 1e-6:
                result.append((u0, v0, u1, v1))
    return result


def _cut(
    pieces: list[tuple[float, float, float, float]], shadows: list[BaseGeometry]
) -> tuple[list[tuple[float, float, float, float]], float]:
    if not shadows:
        return pieces, 0.0
    kept: list[tuple[float, float, float, float]] = []
    lost = 0.0
    for u0, v0, u1, v1 in pieces:
        line: BaseGeometry = LineString([(u0, v0), (u1, v1)])
        before = line.length
        for wedge in shadows:
            line = line.difference(wedge)
        lost += before - line.length
        kept += _segments(line)
    return kept, lost


def column_perimeter(
    centre: Sequence[float],
    c1: float,
    c2: float,
    angle: float,
    d: float,
    boundary: Sequence[Sequence[float]],
    openings: Sequence[Sequence[Sequence[float]]] = (),
    thickness: float | None = None,
) -> tuple[Perimeter, list[str]]:
    """The critical section at d/2 around a ``c1`` x ``c2`` column (``c1`` along its u axis,
    ``angle`` degrees from global X) at ``centre`` of a slab with the plan ``boundary`` and
    ``openings`` (plan polygons, mm). Openings count within 10 ``thickness`` of the column
    (all of them without a thickness). Returns the section and notes."""
    section = critical_section(centre, c1, c2, angle, d, boundary)
    lo_u, hi_u, lo_v, hi_v = section.extents
    faces = (
        any(abs(s[0] - s[2]) < 1e-9 and s[0] < 0 for s in section.sides),
        any(abs(s[0] - s[2]) < 1e-9 and s[0] > 0 for s in section.sides),
        any(abs(s[1] - s[3]) < 1e-9 and s[1] < 0 for s in section.sides),
        any(abs(s[1] - s[3]) < 1e-9 and s[1] > 0 for s in section.sides),
    )
    local = [_local(o, centre, angle) for o in openings]
    reach = 10 * thickness if thickness else None
    shadows, notes = _shadows(local, c1, c2, reach)
    pieces, lost = _cut(list(section.sides), shadows)
    if lost > 0:
        notes.append(
            f"openings make {lost:.0f} mm of the critical section ineffective (Sec 6.4.10.6.1)"
        )
    return (
        Perimeter(
            pieces,
            d,
            section.location,
            section.widths(),
            faces,
            lost,
            (lo_u + hi_u) * (lo_v + hi_v),
        ),
        notes,
    )


def outer_perimeter(
    c1: float,
    c2: float,
    d: float,
    distance: float,
    member: BaseGeometry | None = None,
    shadows: Sequence[BaseGeometry] = (),
) -> Perimeter:
    """The critical section d/2 beyond the last line of shear reinforcement, ``distance`` [mm]
    from the column faces to that line, in the column's axes: the octagon straight across each
    face and chorded across the corners (rails at the column corners, ACI R22.6.4.2), cut by
    the ``member``'s outline (local axes; None: unbounded) and the opening ``shadows``."""
    a = distance + d / 2
    hu, hv = c1 / 2, c2 / 2
    ring = [
        (hu + a, -hv),
        (hu + a, hv),
        (hu, hv + a),
        (-hu, hv + a),
        (-hu - a, hv),
        (-hu - a, -hv),
        (-hu, -hv - a),
        (hu, -hv - a),
    ]
    octagon = Polygon(ring)
    line: BaseGeometry = octagon.exterior
    inside = octagon
    if member is not None:
        # The part of the ring inside the member: a piece along its edge is not a section.
        line = line.intersection(member.buffer(-1e-6))
        inside = octagon.intersection(member)
    pieces, lost = _cut(_segments(line), list(shadows))
    faces = (
        any(p[0] < -hu - a + 1 and abs(p[0] - p[2]) < 1e-6 for p in pieces),
        any(p[0] > hu + a - 1 and abs(p[0] - p[2]) < 1e-6 for p in pieces),
        any(p[1] < -hv - a + 1 and abs(p[1] - p[3]) < 1e-6 for p in pieces),
        any(p[1] > hv + a - 1 and abs(p[1] - p[3]) < 1e-6 for p in pieces),
    )
    if pieces:
        us = [x for p in pieces for x in (p[0], p[2])]
        vs = [y for p in pieces for y in (p[1], p[3])]
        widths = (max(max(us) - min(us), 1.0), max(max(vs) - min(vs), 1.0))
    else:
        widths = (c1 + 2 * a, c2 + 2 * a)
    count = sum(faces)
    location = "interior" if count == 4 else "edge" if count == 3 else "corner"
    return Perimeter(pieces, d, location, widths, faces, lost, inside.area)


# ─────────────────────────────────────── reinforcement ───────────────────────────────────


@dataclass(frozen=True)
class ShearReinforcement:
    """Shear reinforcement provided around a column: ``kind`` "studs" or "stirrups", the bar
    or stud shank diameter, the elements (studs or legs) on one peripheral line, the number
    of lines, the distance s0 of the first line from the column face and the spacing s of
    the lines [mm], fyt [MPa]."""

    kind: str
    bar: float
    per_line: int
    lines: int
    s0: float
    s: float
    fyt: float = STUD_FY


@dataclass
class Reinforcement:
    """The shear reinforcement a column needs (a proposal) or the check of what is given."""

    kind: str  # "studs", "stirrups" or "thicken" (vn,max exceeded or no layout works)
    ok: bool
    text: str
    layout: ShearReinforcement | None = None
    vc: float = 0.0  # MPa, with this reinforcement
    vs: float = 0.0  # MPa, provided
    vs_required: float = 0.0
    vn_max: float = 0.0
    utilisation: float = 0.0  # vu / φ(vc + vs), or vu / φ vn,max where that governs
    outer_stress: float = 0.0  # MPa, on the section outside the last line
    outer_limit: float = 0.0  # 0.17 φ λ √f'c
    outer_b0: float = 0.0
    stud_height: float | None = None  # the least overall stud assembly height [mm]
    issues: list[str] = field(default_factory=list)


def _floor(value: float, step: float = STEP) -> float:
    return math.floor(value / step + 1e-9) * step


def _vc_with(kind: str, fc: float, d: float, b0: float, beta: float, alpha_s: float, lam: float):
    """vc [MPa] with shear reinforcement: stirrups 0.17 λ √f'c (6.4.10.3.1); studs the least
    of 0.25 λ √f'c (6.4.10.5.1) and Eq. 6.6.72-6.6.73 (λs = 1 with shear reinforcement)."""
    root = min(math.sqrt(fc), 8.3)
    if kind == "stirrups":
        return 0.17 * lam * root
    return lam * root * min(0.25, 0.17 * (1 + 2 / beta), 0.083 * (2 + alpha_s * d / b0))


def _vn_max(kind: str, fc: float, lam: float) -> float:
    root = math.sqrt(fc)
    return 0.5 * root if kind == "stirrups" else 0.66 * lam * root


def _spacing_limit(kind: str, vu: float, fc: float, d: float) -> float:
    if kind == "stirrups":
        return d / 2
    return 0.75 * d if vu <= 0.5 * rc_value("PHI_SHEAR") * math.sqrt(fc) else 0.5 * d


def _rails(faces: tuple[bool, ...], c1: float, c2: float, d: float) -> int:
    """Elements on one peripheral line: a rail (or stirrup leg line) at both ends of every
    kept column face and enough between them for at most 2d along the face (6.4.10.3.3,
    6.4.10.5.3); faces that share a corner share nothing (each face's end rails run square
    to it)."""
    total = 0
    for kept, side in zip(faces, (c2, c2, c1, c1), strict=True):
        if kept:
            total += max(2, math.ceil(side / (2 * d)) + 1)
    return total


def design_reinforcement(
    *,
    vu: float,
    b0: float,
    d: float,
    alpha_s: float,
    beta: float,
    fc: float,
    c1: float,
    c2: float,
    faces: tuple[bool, bool, bool, bool],
    outer: Callable[[float], tuple[float, float]],
    kind: str = "studs",
    fyt: float | None = None,
    lam: float = 1.0,
    h: float | None = None,
    covers: tuple[float, float] = (25.0, 25.0),
    flexural_bar: float = 12.0,
    provided: ShearReinforcement | None = None,
) -> Reinforcement:
    """Shear reinforcement for the largest shear stress ``vu`` [MPa] on the critical section
    (``b0``, ``d``, ``alpha_s``; β of the column; ``faces`` the kept column faces) when it is
    beyond φ vc: ``kind`` "studs" or "stirrups". ``outer(distance)`` gives (v, b0) on the
    section d/2 outside a last line ``distance`` from the column faces. With ``provided`` it
    checks that layout instead of proposing one. ``h`` and ``covers`` (to the flexural tension
    and the other face's bars) give the stud assembly height (6.4.10.5)."""
    if provided is not None:
        kind = provided.kind
    if kind not in ("studs", "stirrups"):
        raise ValueError(f"unknown shear reinforcement '{kind}'")
    phi = rc_value("PHI_SHEAR")
    root = math.sqrt(fc)
    vn_max = _vn_max(kind, fc, lam)
    vc = _vc_with(kind, fc, d, b0, beta, alpha_s, lam)
    limit_out = 0.17 * phi * lam * min(root, 8.3)
    fy_cap = fyt if fyt is not None else (STUD_FY if kind == "studs" else STIRRUP_FY_MAX)
    if kind == "stirrups":
        fy_cap = min(fy_cap, STIRRUP_FY_MAX)
    vs_required = max(vu / phi - vc, 0.0)
    if kind == "studs":
        vs_required = max(vs_required, 0.17 * root)
    stud_height = None
    if h is not None and kind == "studs":
        stud_height = h - covers[0] - covers[1] - flexural_bar / 2

    def thicken(reason: str) -> Reinforcement:
        # A failure: the utilisation is never below 1, even where vn,max itself is not reached
        # (d < 150 mm for stirrups, no bar or no number of lines works).
        utilisation = max(vu / (phi * vn_max), FAIL)
        return Reinforcement(
            "thicken",
            False,
            f"{reason}: increase the thickness, add a drop panel or a shear cap, or enlarge the "
            "column",
            vc=vc,
            vs_required=vs_required,
            vn_max=vn_max,
            utilisation=utilisation,
            outer_limit=limit_out,
            issues=[reason],
        )

    if vu > phi * vn_max:
        name = "headed studs" if kind == "studs" else "stirrups"
        return thicken(
            f"v = {vu:.2f} MPa exceeds φ vn,max = {phi * vn_max:.2f} MPa with {name} "
            f"({'6.4.10.5.1' if kind == 'studs' else '6.4.10.3.2'})"
        )
    if kind == "stirrups" and d < 150:
        return thicken(f"stirrups need d >= 150 mm (6.4.10.3), d = {d:.0f} mm")

    s_max = _spacing_limit(kind, vu, fc, d)
    elements = _rails(faces, c1, c2, d)

    def lines_for(s0: float, s: float) -> tuple[int, float, float] | None:
        for n in range(1, MAX_LINES + 1):
            v_out, b0_out = outer(s0 + (n - 1) * s)
            if v_out <= limit_out or b0_out <= 0:
                return n, v_out, b0_out
        return None

    if provided is not None:
        issues = []
        s, s0 = provided.s, provided.s0
        fy_used = min(provided.fyt, STIRRUP_FY_MAX) if kind == "stirrups" else provided.fyt
        vs = provided.per_line * bar_area(provided.bar) * fy_used / (b0 * s) if s > 0 else 0.0
        if s0 > d / 2 + 1e-6:
            issues.append(f"first line {s0:.0f} mm from the face exceeds d/2 = {d / 2:.0f} mm")
        if s > s_max + 1e-6:
            issues.append(f"line spacing {s:.0f} mm exceeds {s_max:.0f} mm")
        if provided.per_line < elements:
            issues.append(
                f"{provided.per_line} elements per line: at least {elements} for 2d along the faces"
            )
        if kind == "stirrups" and d < 16 * provided.bar:
            issues.append(f"d = {d:.0f} mm is less than 16 db = {16 * provided.bar:.0f} mm")
        if kind == "studs" and vs < 0.17 * root:
            issues.append(f"Av fyt/(b0 s) = {vs:.2f} MPa is below 0.17 √f'c = {0.17 * root:.2f}")
        v_out, b0_out = outer(s0 + (provided.lines - 1) * s)
        if b0_out > 0 and v_out > limit_out:
            issues.append(
                f"v = {v_out:.2f} MPa outside the last line exceeds 0.17 φ λ √f'c = "
                f"{limit_out:.2f} MPa: more lines"
            )
        capacity = phi * min(vc + vs, vn_max)
        utilisation = vu / capacity if capacity > 0 else math.inf
        if b0_out > 0 and limit_out > 0:
            utilisation = max(utilisation, v_out / limit_out)
        ok = utilisation <= 1.0 + 1e-9 and not issues
        if not ok:
            # Detailing faults fail the check even where the stresses are within the limits.
            utilisation = max(utilisation, FAIL)
        return Reinforcement(
            kind,
            ok,
            f"{provided.lines} lines of {provided.per_line} {_name(kind, provided.bar)}, "
            f"s0 = {s0:.0f} mm, s = {s:.0f} mm: φ(vc + vs) = {capacity:.2f} MPa"
            + ("; " + "; ".join(issues) if issues else ""),
            provided,
            vc,
            vs,
            vs_required,
            vn_max,
            utilisation,
            v_out,
            limit_out,
            b0_out,
            stud_height,
            issues,
        )

    s = _floor(s_max)
    s0 = _floor(min(d / 2, s))
    diameters = STUD_DIAMETERS if kind == "studs" else STIRRUP_DIAMETERS
    choice = None
    for per_line in (elements, elements * 2):  # a larger bar before more rails
        for bar in diameters:
            if kind == "stirrups" and d < 16 * bar:
                continue
            vs = per_line * bar_area(bar) * fy_cap / (b0 * s)
            if vs >= vs_required - 1e-9:
                choice = (bar, per_line, vs)
                break
        if choice:
            break
    if choice is None:
        return thicken(
            f"no {kind} layout up to Ø{diameters[-1]:g} gives vs = {vs_required:.2f} MPa"
        )
    bar, per_line, vs = choice
    found = lines_for(s0, s)
    if found is None:
        return thicken(
            f"{MAX_LINES} lines of {kind} do not bring v outside them below "
            f"0.17 φ λ √f'c = {limit_out:.2f} MPa"
        )
    lines, v_out, b0_out = found
    lines = max(lines, 2)
    v_out, b0_out = outer(s0 + (lines - 1) * s)
    layout = ShearReinforcement(kind, bar, per_line, lines, s0, s, fy_cap)
    capacity = phi * min(vc + vs, vn_max)
    extent = s0 + (lines - 1) * s
    text = (
        f"{lines} lines of {per_line} {_name(kind, bar)} (fyt {fy_cap:g} MPa), first line "
        f"{s0:.0f} mm from the column face, then every {s:.0f} mm, to {extent:.0f} mm from "
        f"the face: vs = {vs:.2f} MPa (needs {vs_required:.2f}), φ(vc + vs) = "
        f"{capacity:.2f} MPa, v = {v_out:.2f} MPa <= {limit_out:.2f} MPa outside the last line"
    )
    if stud_height is not None:
        text += f"; stud assembly at least {stud_height:.0f} mm high"
    return Reinforcement(
        kind,
        True,
        text,
        layout,
        vc,
        vs,
        vs_required,
        vn_max,
        vu / capacity,
        v_out,
        limit_out,
        b0_out,
        stud_height,
    )


def _name(kind: str, bar: float) -> str:
    return f"Ø{bar:g} headed studs" if kind == "studs" else f"Ø{bar:g} stirrup legs"


# ─────────────────────────────────────── checks ───────────────────────────────────────


@dataclass(frozen=True)
class Demand:
    """One combination's actions on the critical section: Vu [N] and the unbalanced moments
    [N·mm] bending the slab along the column's u axis (``m_u``) and along v."""

    vu: float
    m_u: float = 0.0
    m_v: float = 0.0
    combination: str = ""


@dataclass
class PunchingResult:
    """Punching at one column: the governing combination, the stresses [MPa], the concrete
    capacity and, where it is short, the shear reinforcement."""

    location: str
    b0: float
    d: float
    alpha_s: float
    beta: float
    vu: float  # largest shear stress
    direct: float
    gamma_v: tuple[float, float]
    combination: str
    vc: float  # without shear reinforcement
    expressions: tuple[float, float, float]
    lambda_s: float
    phi_vc: float
    utilisation: float  # vu / φ vc (without reinforcement)
    reinforcement: Reinforcement | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def needs_reinforcement(self) -> bool:
        return self.utilisation > 1.0 + 1e-9

    @property
    def ok(self) -> bool:
        if not self.needs_reinforcement:
            return True
        return self.reinforcement is not None and self.reinforcement.ok

    def check(self, name: str) -> dict[str, Any]:
        """The result as a design check (:func:`saengine.design.check._check`): v b0 d against
        φ vc b0 d, or φ(vc + vs) b0 d where reinforcement is given or proposed."""
        from saengine.design.check import _check

        area = self.b0 * self.d
        r = self.reinforcement
        capacity = self.phi_vc
        utilisation = self.utilisation
        if self.needs_reinforcement and r is not None:
            if r.kind != "thicken":
                # Reinforcement given or proposed: φ(vc + vs) (its detailing faults and the
                # outer section are in r.utilisation and r.ok).
                capacity = rc_value("PHI_SHEAR") * min(r.vc + r.vs, r.vn_max)
                utilisation = r.utilisation
            else:
                # No layout works: the plain concrete check, failing.
                utilisation = max(utilisation, r.utilisation)
        if not self.ok:
            # Pass/fail of _check follows the utilisation, so a failure never reports <= 1.
            utilisation = max(utilisation, FAIL)
        a, b, c = self.expressions
        note = (
            f"{self.location} column, b0 = {self.b0:.0f} mm, d = {self.d:.0f} mm, "
            f"vu = {self.vu:.3f} MPa (direct {self.direct:.3f}, γv = {self.gamma_v[0]:.2f}/"
            f"{self.gamma_v[1]:.2f}), vc = min({a:.3f}, {b:.3f}, {c:.3f}) MPa, "
            f"λs = {self.lambda_s:.2f}, αs = {self.alpha_s:g}, β = {self.beta:.2f}"
        )
        if r is not None:
            note += f"; {r.text}"
        if self.notes:
            note += "; " + "; ".join(self.notes)
        result = _check(
            name,
            self.vu * area / 1e3,
            capacity * area / 1e3,
            "kN",
            self.combination,
            note + "; shown as v b0 d",
            utilisation=utilisation,
        )
        if r is not None and r.layout is not None:
            layout = r.layout
            result["shearReinforcement"] = {
                "kind": layout.kind,
                "bar": layout.bar,
                "perLine": layout.per_line,
                "lines": layout.lines,
                "s0": layout.s0,
                "s": layout.s,
                "fyt": layout.fyt,
                "studHeight": r.stud_height,
            }
        return result


def _result(
    section: Perimeter,
    worst: tuple[float, float, float, float, str],
    beta: float,
    fc: float,
    lam: float,
    notes: list[str],
) -> PunchingResult:
    vu, direct, g_u, g_v, combination = worst
    capacity = punching_capacity(fc, section.d, section.b0, beta, section.alpha_s, lam)
    phi_vc = rc_value("PHI_SHEAR") * capacity.vc
    return PunchingResult(
        section.location,
        section.b0,
        section.d,
        section.alpha_s,
        beta,
        vu,
        direct,
        (g_u, g_v),
        combination,
        capacity.vc,
        capacity.expressions,
        capacity.lambda_s,
        phi_vc,
        vu / phi_vc,
        notes=notes,
    )


def slab_punching(
    centre: Sequence[float],
    c1: float,
    c2: float,
    angle: float,
    d: float,
    boundary: Sequence[Sequence[float]],
    demands: Sequence[Demand],
    fc: float,
    *,
    openings: Sequence[Sequence[Sequence[float]]] = (),
    thickness: float | None = None,
    kind: str = "studs",
    fyt: float | None = None,
    lam: float = 1.0,
    covers: tuple[float, float] = (20.0, 20.0),
    flexural_bar: float = 12.0,
    provided: ShearReinforcement | None = None,
) -> PunchingResult | None:
    """Punching of a flat slab (or mat) at a column: the section of :func:`column_perimeter`,
    the largest stress of the ``demands`` and, where it exceeds φ vc, the shear reinforcement
    (``provided`` checked, else a ``kind`` proposed). None when no critical section is left."""
    section, notes = column_perimeter(centre, c1, c2, angle, d, boundary, openings, thickness)
    if not section.pieces or not demands:
        return None
    beta = max(c1, c2) / min(c1, c2)
    worst = None
    for demand in demands:
        v, direct, g_u, g_v = section.stress(max(demand.vu, 0.0), demand.m_u, demand.m_v)
        if worst is None or v > worst[0]:
            worst = (v, direct, g_u, g_v, demand.combination)
    assert worst is not None
    result = _result(section, worst, beta, fc, lam, notes)
    if not result.needs_reinforcement and provided is None:
        return result
    member = Polygon(_local(boundary, centre, angle))
    local_openings = [_local(o, centre, angle) for o in openings]
    shadows, _ = _shadows(local_openings, c1, c2, 10 * thickness if thickness else None)

    def outer(distance: float) -> tuple[float, float]:
        ring = outer_perimeter(c1, c2, d, distance, member, shadows)
        if ring.b0 <= 0:
            return 0.0, 0.0
        # Every combination: the moment term fades faster than the direct shear, so the one
        # governing the column face need not govern out here.
        v = max(ring.stress(max(dm.vu, 0.0), dm.m_u, dm.m_v)[0] for dm in demands)
        return v, ring.b0

    result.reinforcement = design_reinforcement(
        vu=result.vu,
        b0=section.b0,
        d=d,
        alpha_s=section.alpha_s,
        beta=beta,
        fc=fc,
        c1=c1,
        c2=c2,
        faces=section.faces,
        outer=outer,
        kind=kind,
        fyt=fyt,
        lam=lam,
        h=thickness,
        covers=covers,
        flexural_bar=flexural_bar,
        provided=provided,
    )
    return result


def footing_punching(
    u: float,
    v: float,
    cu: float,
    cv: float,
    length: float,
    width: float,
    d: float,
    fc: float,
    demands: Sequence[
        tuple[str, float, float, float, Callable[[float, float, float, float], float]]
    ],
    *,
    lam: float = 1.0,
    kind: str = "studs",
    fyt: float | None = None,
    thickness: float | None = None,
    covers: tuple[float, float] = (75.0, 50.0),
    flexural_bar: float = 16.0,
    provided: ShearReinforcement | None = None,
) -> PunchingResult | None:
    """Punching of a footing at the column at (``u``, ``v``) [mm, footing axes, origin at its
    centre], ``cu`` x ``cv``, in a ``length`` (along u) x ``width`` footing, as
    :func:`saengine.substructure.shallow.design_footing` checks it: ``demands`` per
    combination ``(name, Pu [N], moment about u [N·mm], moment about v, relief)`` with
    ``relief(u0, u1, v0, v1)`` the net upward force [N] on that rectangle (soil pressure less
    the factored weight of the footing and the soil on it). The section at d/2 runs to the
    footing's edges, Vu = Pu - relief inside, v = Vu/(b0 d) + γv M (b1/2)/Jc with Jc of the
    full rectangle (ACI R8.4.4.2.3) for both moments: the same numbers as the footing design
    without reinforcement. Where v > φ vc, the reinforcement as :func:`slab_punching` (the
    section outside it about its own centroid, its Vu less the relief inside it). None when
    the section lies outside the footing (fewer than two sides)."""
    u0, u1 = u - cu / 2 - d / 2, u + cu / 2 + d / 2
    v0, v1 = v - cv / 2 - d / 2, v + cv / 2 + d / 2
    sides = (u0 > -length / 2, u1 < length / 2, v0 > -width / 2, v1 < width / 2)
    cu0, cu1 = max(u0, -length / 2), min(u1, length / 2)
    cv0, cv1 = max(v0, -width / 2), min(v1, width / 2)
    b0 = (sides[0] + sides[1]) * (cv1 - cv0) + (sides[2] + sides[3]) * (cu1 - cu0)
    count = sum(sides)
    if count < 2 or b0 <= 0 or not demands:
        return None
    location = {4: "interior", 3: "edge", 2: "corner"}[count]
    b1u, b1v = cu + d, cv + d
    jc_u = d * b1u**3 / 6 + b1u * d**3 / 6 + d * b1v * b1u**2 / 2
    jc_v = d * b1v**3 / 6 + b1v * d**3 / 6 + d * b1u * b1v**2 / 2
    g_u = 1 - 1 / (1 + (2 / 3) * math.sqrt(b1u / b1v))
    g_v = 1 - 1 / (1 + (2 / 3) * math.sqrt(b1v / b1u))
    worst = None
    for name, pu, m_about_u, m_about_v, relief in demands:
        vu = max(pu - relief(cu0, cu1, cv0, cv1), 0.0)
        # A moment about v bends the footing along u, as in design_footing.
        stress = vu / (b0 * d) + g_u * abs(m_about_v) * (b1u / 2) / jc_u
        stress += g_v * abs(m_about_u) * (b1v / 2) / jc_v
        if worst is None or stress > worst[0]:
            worst = (stress, vu / (b0 * d), g_u, g_v, name)
    assert worst is not None
    pieces = []
    if sides[0]:
        pieces.append((cu0 - u, cv0 - v, cu0 - u, cv1 - v))
    if sides[1]:
        pieces.append((cu1 - u, cv0 - v, cu1 - u, cv1 - v))
    if sides[2]:
        pieces.append((cu0 - u, cv0 - v, cu1 - u, cv0 - v))
    if sides[3]:
        pieces.append((cu0 - u, cv1 - v, cu1 - u, cv1 - v))
    section = Perimeter(pieces, d, location, (b1u, b1v), sides, 0.0, (cu1 - cu0) * (cv1 - cv0))
    beta = max(cu, cv) / min(cu, cv)
    result = _result(section, worst, beta, fc, lam, [])
    if not result.needs_reinforcement and provided is None:
        return result
    member = box(-length / 2 - u, -width / 2 - v, length / 2 - u, width / 2 - v)

    def outer(distance: float) -> tuple[float, float]:
        ring = outer_perimeter(cu, cv, d, distance, member)
        if ring.b0 <= 0:
            return 0.0, 0.0
        a = distance + d / 2
        r0, r1 = max(-cu / 2 - a, -length / 2 - u), min(cu / 2 + a, length / 2 - u)
        s0, s1 = max(-cv / 2 - a, -width / 2 - v), min(cv / 2 + a, width / 2 - v)
        rect = (r1 - r0) * (s1 - s0)
        # The octagon's share of the relief over its bounding rectangle (exact for a uniform
        # pressure, close for a planar one).
        share = ring.area / rect if rect > 0 else 0.0
        # Every combination, each with its own relief: the one governing the column face need
        # not govern out here.
        stress = 0.0
        for _name_, pu, m_about_u, m_about_v, relief in demands:
            inside = relief(u + r0, u + r1, v + s0, v + s1) * share
            stress = max(stress, ring.stress(max(pu - inside, 0.0), m_about_v, m_about_u)[0])
        return stress, ring.b0

    result.reinforcement = design_reinforcement(
        vu=result.vu,
        b0=b0,
        d=d,
        alpha_s=section.alpha_s,
        beta=beta,
        fc=fc,
        c1=cu,
        c2=cv,
        faces=sides,
        outer=outer,
        kind=kind,
        fyt=fyt,
        lam=lam,
        h=thickness,
        covers=covers,
        flexural_bar=flexural_bar,
        provided=provided,
    )
    return result


def unit_relief(q: float) -> Callable[[float, float, float, float], float]:
    """A uniform net upward pressure ``q`` [MPa] as the ``relief`` of :func:`footing_punching`."""

    def relief(u0: float, u1: float, v0: float, v1: float) -> float:
        return q * max(u1 - u0, 0.0) * max(v1 - v0, 0.0)

    return relief


# ─────────────────────────── integrator glue: re-checking a shared layout ───────────────────────────


class PunchingRow(dict):  # type: ignore[type-arg]
    """Integrator glue (saengine.design.proposal): a punching check row, a plain ``dict`` to
    JSON and to the report, that also carries ``recheck(layout)``: the same column checked
    again with another layout (a ``punchingReinforcement`` dict: kind, dia, perLine, lines,
    firstLine, spacing, fyt?), giving its check row (None when no critical section is left).
    The design mode uses it to check the one layout it proposes for a slab type or footing at
    every column before proposing it."""

    recheck: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None


def provided_of(layout: dict[str, Any], fy: float = 420.0) -> ShearReinforcement:
    """A ``punchingReinforcement`` dict (04 Objects / 09 Substructure) as the layout to check;
    fyt, when not given, 350 MPa for studs (:data:`STUD_FY`) and min(fy, 420) for stirrups."""
    kind = str(layout.get("kind", "studs"))
    fyt = layout.get("fyt") or (STUD_FY if kind == "studs" else min(fy, STIRRUP_FY_MAX))
    return ShearReinforcement(
        kind,
        float(layout["dia"]),
        int(layout["perLine"]),
        int(layout["lines"]),
        float(layout["firstLine"]),
        float(layout["spacing"]),
        float(fyt),
    )


def recheckable(
    row: dict[str, Any],
    name: str,
    run: Callable[[ShearReinforcement | None], PunchingResult | None],
    fy: float,
    provided: ShearReinforcement | None,
) -> PunchingRow:
    """Integrator glue: ``row`` (``run(provided).check(name)``) as a :class:`PunchingRow` whose
    ``recheck`` runs the column again with a layout. Where the given layout fails, the row
    also gets ``proposedReinforcement``: the layout proposed without it (same shape as
    ``shearReinforcement``; None when no layout works and a thicker member is needed)."""
    out = PunchingRow(row)
    if provided is not None and not row.get("ok", True):
        try:
            fresh = run(None)
        except (ValueError, ArithmeticError):
            fresh = None
        out["proposedReinforcement"] = (
            fresh.check(name).get("shearReinforcement") if fresh is not None else None
        )

    def recheck(layout: dict[str, Any]) -> dict[str, Any] | None:
        result = run(provided_of(layout, fy))
        return result.check(name) if result is not None else None

    out.recheck = recheck
    return out


def __getattr__(name: str) -> list[str]:
    # The method text names the clauses of the pack in force: built when it is read.
    if name == "PUNCHING_METHOD":
        return _punching_method()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

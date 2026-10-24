"""Flanged structural walls: walls that meet in plan (L, T, C, box and X shapes) designed as one
composite section, to BNBC 2020 Part 6 (bnbc-2020-part1.pdf).

:mod:`saengine.design.walls` checks each pier of a wall as a rectangle. Where walls of 06 BIM
meet at a corner or a T in a storey, BNBC asks for the section they make together:

- Sec 8.3.6.5(a) (p. 1102): walls under flexure and axial load by 6.3.2 and 6.3.3; "concrete and
  developed longitudinal reinforcement within effective flange widths, boundary elements, and
  the wall web shall be considered effective".
- Sec 8.3.6.5(b) (p. 1102): unless a more detailed analysis is made, the effective flange width
  extends from the face of the web the smaller of one-half the distance to an adjacent wall web
  and 25 percent of the total wall height (:func:`effective_section`).
- Sec 8.3.6.4(d) (p. 1102): the vertical segments that resist a common lateral force together
  have Vn <= 0.66 Acv √f'c (Acv their gross combined area), each one <= 0.83 Acw √f'c.
- Sec 8.3.6.6(c) (p. 1103): the extreme fibre stress of the stress method with the effective
  flange width; 8.3.6.6(d)(i) the boundary element's length max(c - 0.1 lw, c/2) from the
  extreme compression fibre; (d)(ii) (p. 1103) in flanged sections it includes the effective
  flange width in compression and extends at least 300 mm into the web.

BNBC's Chapter 6 (ordinary walls) gives no flange rule: the same effective widths are used for
ordinary walls (stated in the method).

**Groups.** Walls whose centre lines meet (an end on the other wall's line within half its
thickness, or the lines crossing inside both) and whose heights overlap form a group
(:func:`wall_groups`); a junction is an L (both at an end), a T (one at an end) or an X.

**Section.** Per family of parallel walls (one per direction in the group) the section with
those walls as webs and the others as flanges: each web full length, each flange the part
within its effective width of the webs it meets (8.3.6.5(b)); the wall ends at a junction run
on to the other wall's outer face (so an L's outer corner is solid). The polygon is the union of
those rectangles (shapely). The vertical bars of each wall's type lie in its effective part (two
layers at the type's spacing, as :func:`walls.pier_section` lays them), the type's end bars at
the free ends; bars falling inside a wall already laid (the junction) are not counted twice.
End bars at a junction are not counted (on the safe side).

**P-M interaction.** Strain compatibility on the polygon with the assumptions of
:mod:`saengine.design.rc` (εcu = 0.003, the stress block 0.85 f'c over β1 c, elastic-perfectly
plastic bars displacing the concrete, φ from εt of the extreme tension bar, φPn <= 0.80 φ P0):
the compression block is the polygon clipped at depth a = β1 c (exact for any polygon), the
meridians over the full turn of neutral-axis angles, interpolated and cut at Pu as
:class:`saengine.design.rc.InteractionSurface` (:class:`FlangedInteraction` reuses its
meridian interpolation and contour). An unsymmetric section (T, L) has different strengths for
the two senses: the demand is checked along its own signed direction. Moments are carried as
the vector S = Σ F r (the first moment of the compressive forces about the section's centroid,
N·mm), which points to the compressed side: ``(Sx, Sy)`` in plan axes.

**Forces.** The group's forces at a cut are the sum of its piers' cuts (of
:mod:`saengine.design.wall_forces`) of the same combination, each pier's moments turned to plan
axes and its axial force moved to the group's reference point: exact for static combinations;
for a response spectrum combination each pier's modal resultant was combined on its own (CQC or
SRSS) before the sum, which does not cancel the opposite modal forces of the piers (a note).

Units: mm, MPa, N, N·mm (kN, kN·m in the check rows).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.design import walls as W
from saengine.design.ductile_members import _row
from saengine.design.rc import (
    _DEPTHS,
    _SUBDIVISIONS,
    _TRANSITION_POINTS,
    EPS_CU,
    PHI_SHEAR,
    PHI_TENSION,
    PHI_TIED,
    STEEL_E,
    Bar,
    ColumnCheck,
    DesignError,
    InteractionSurface,
    _encloses_origin,
    bar_area,
    beta1,
    phi_axial_flexure,
)

CLAUSES = {
    "flexure": "BNBC 2020 Part 6 Sec 8.3.6.5(a) (p. 1102)",
    "flange": "BNBC 2020 Part 6 Sec 8.3.6.5(b) (p. 1102)",
    "shear": "BNBC 2020 Part 6 Sec 8.3.6.4(d) (p. 1102)",
    "stress": "BNBC 2020 Part 6 Sec 8.3.6.6(c) (p. 1103)",
    "boundary": "BNBC 2020 Part 6 Sec 8.3.6.6(d)(i), (ii) (p. 1103)",
}

#: Effective flange: at most this share of the total wall height from the web face (8.3.6.5(b)).
FLANGE_HEIGHT_SHARE = 0.25
#: A boundary element in a flanged section extends at least this far into the web
#: (8.3.6.6(d)(ii)) [mm].
INTO_WEB = 300.0
#: Combined shear of the vertical segments resisting a common lateral force (8.3.6.4(d)).
COMBINED_SHEAR = 0.66
#: Walls within this angle of each other are parallel (one family, one web direction) [°].
PARALLEL = 10.0
#: A wall within 45° of a direction is a web for bending along it, else a flange.
WEB_ANGLE = 45.0
#: Tolerance on positions [mm].
TOL = 1.0
#: Neutral-axis angles of the computed meridians, this far apart.
_STEP = math.radians(7.5)

METHOD = [
    (
        "Flanged walls (BNBC 2020 Part 6 Sec 8.3.6.5): walls meeting at an L, T or C in a "
        "storey are checked as one section, per direction with the walls along it as webs and "
        "the others as flanges of effective width min(half the distance to the adjacent web, "
        "25 % of the wall height) beyond the web face (8.3.6.5(b), also used for ordinary "
        "walls); axial force and biaxial bending by strain compatibility on the composite "
        "polygon (the forces the sum of the piers' cuts); the webs' shear together within "
        "0.66 Acv √f'c (8.3.6.4(d)); boundary elements at the web ends and flanges "
        "(8.3.6.6(b)-(d), with the flange in compression and 300 mm into the web). The "
        "rectangular piers' P-M and boundary rows of those walls are then informative."
    ),
]


# ─────────────────────────────────────── plan geometry ───────────────────────────────────────


@dataclass(frozen=True)
class Leg:
    """One wall of a group in plan: its centre line and thickness."""

    id: str
    start: tuple[float, float]
    end: tuple[float, float]
    thickness: float
    bars: W.WallBars | None = None
    type: str = ""
    bottom: float = 0.0
    top: float = 0.0

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)

    @property
    def along(self) -> np.ndarray:
        run = np.subtract(self.end, self.start, dtype=float)
        return run / (np.linalg.norm(run) or 1.0)

    @property
    def normal(self) -> np.ndarray:
        a = self.along
        return np.array([-a[1], a[0]])

    def point(self, s: float, n: float = 0.0) -> np.ndarray:
        return np.asarray(self.start, dtype=float) + self.along * s + self.normal * n

    def local(self, p: Iterable[float]) -> tuple[float, float]:
        d = np.asarray(p, dtype=float) - np.asarray(self.start, dtype=float)
        return float(d @ self.along), float(d @ self.normal)


@dataclass(frozen=True)
class Junction:
    """Where two walls' centre lines meet: ``a`` and ``b`` at ``sa``, ``sb`` along them."""

    a: str
    b: str
    point: tuple[float, float]
    sa: float
    sb: float
    a_end: bool  # the junction is at an end of ``a``
    b_end: bool

    @property
    def kind(self) -> str:
        if self.a_end and self.b_end:
            return "L"
        return "T" if self.a_end or self.b_end else "X"

    def along(self, leg: str) -> float:
        return self.sa if leg == self.a else self.sb

    def other(self, leg: str) -> str:
        return self.b if leg == self.a else self.a


def _cross(u: np.ndarray, v: np.ndarray) -> float:
    return float(u[0] * v[1] - u[1] * v[0])


def junction(a: Leg, b: Leg) -> Junction | None:
    """The junction of two walls in plan, None when they do not meet (or are parallel)."""
    da, db = a.along, b.along
    cross = _cross(da, db)
    if abs(cross) < math.sin(math.radians(PARALLEL)):
        return None
    w = np.subtract(b.start, a.start, dtype=float)
    sa = _cross(w, db) / cross
    sb = _cross(w, da) / cross
    tol_a, tol_b = b.thickness / 2 + TOL, a.thickness / 2 + TOL
    la, lb = a.length, b.length
    if not (-tol_a <= sa <= la + tol_a and -tol_b <= sb <= lb + tol_b):
        return None
    a_end = sa <= tol_a or sa >= la - tol_a
    b_end = sb <= tol_b or sb >= lb - tol_b
    sa = min(max(sa, 0.0), la)
    sb = min(max(sb, 0.0), lb)
    p = a.point(sa)
    if a_end and not b_end:
        sa = 0.0 if sa <= la / 2 else la
    if b_end and not a_end:
        sb = 0.0 if sb <= lb / 2 else lb
    return Junction(a.id, b.id, (float(p[0]), float(p[1])), sa, sb, a_end, b_end)


def find_junctions(legs: list[Leg]) -> list[Junction]:
    """Every junction between the walls ``legs`` whose heights overlap."""
    out = []
    for i, a in enumerate(legs):
        for b in legs[i + 1 :]:
            if min(a.top, b.top) - max(a.bottom, b.bottom) <= TOL and (a.top or b.top):
                continue
            j = junction(a, b)
            if j is not None:
                out.append(j)
    return out


@dataclass
class Group:
    """Walls meeting in plan, with their junctions."""

    legs: list[Leg]
    junctions: list[Junction]

    @property
    def id(self) -> str:
        return "+".join(leg.id for leg in self.legs)

    def leg(self, leg_id: str) -> Leg:
        return next(leg for leg in self.legs if leg.id == leg_id)


def groups_of(legs: list[Leg]) -> list[Group]:
    """The connected groups (two walls or more) of ``legs`` by their junctions."""
    junctions = find_junctions(legs)
    parent = {leg.id: leg.id for leg in legs}

    def root(k: str) -> str:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for j in junctions:
        parent[root(j.a)] = root(j.b)
    members: dict[str, list[Leg]] = {}
    for leg in legs:
        members.setdefault(root(leg.id), []).append(leg)
    out = []
    for group in members.values():
        if len(group) < 2:
            continue
        ids = {leg.id for leg in group}
        group.sort(key=lambda leg: leg.id)
        out.append(Group(group, [j for j in junctions if j.a in ids and j.b in ids]))
    out.sort(key=lambda g: g.id)
    return out


def wall_groups(
    building: Any, types: Mapping[str, Any], ids: Iterable[str] | None = None
) -> list[Group]:
    """The groups of structural walls of 06 BIM (``types``: 04 Objects by id; walls whose type
    is not a structural ``Wall`` are left out). ``ids``: only these walls (the designed RC
    walls), so a brick wall or an undesigned wall touching an RC group neither joins it nor
    breaks it up."""
    keep = None if ids is None else set(ids)
    from saengine.library.bim import WallElement
    from saengine.library.objects import Wall

    legs = []
    for e in building.elements:
        if not isinstance(e, WallElement) or (keep is not None and e.id not in keep):
            continue
        t = types.get(e.type)
        if not isinstance(t, Wall) or not t.structural:
            continue
        legs.append(
            Leg(
                e.id,
                (float(e.start[0]), float(e.start[1])),
                (float(e.end[0]), float(e.end[1])),
                float(t.thickness),
                W.wall_bars(t.reinforcement) if t.reinforcement is not None else None,
                e.type,
                float(e.bottom),
                float(e.top),
            )
        )
    return groups_of(legs)


def families(legs: Iterable[Leg]) -> list[np.ndarray]:
    """The distinct wall directions (unit vectors, one per family of parallel walls)."""
    out: list[np.ndarray] = []
    for leg in legs:
        u = leg.along
        if not any(abs(_cross(u, v)) < math.sin(math.radians(PARALLEL)) for v in out):
            out.append(u)
    return out


# ─────────────────────────────────────── the section ───────────────────────────────────────


@dataclass
class FlangedSection:
    """The composite section for one web direction: polygon and bars about its gross centroid
    (``origin``: that centroid in plan [mm])."""

    polygon: Any  # shapely Polygon or MultiPolygon, centroid at (0, 0)
    bars: tuple[Bar, ...]
    fc: float
    fy: float
    es: float
    origin: tuple[float, float]
    direction: tuple[float, float]  # the webs' direction
    webs: list[str]
    flanges: list[dict[str, Any]] = field(default_factory=list)
    rects: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    spiral: bool = False
    symmetric: bool = False

    @property
    def gross_area(self) -> float:
        return float(self.polygon.area)

    @property
    def steel_area(self) -> float:
        return sum(b.area for b in self.bars)

    @property
    def p0(self) -> float:
        ast = self.steel_area
        return 0.85 * self.fc * (self.gross_area - ast) + self.fy * ast

    @property
    def phi_pn_max(self) -> float:
        return 0.80 * PHI_TIED * self.p0

    @property
    def phi_tension(self) -> float:
        return PHI_TENSION * self.fy * self.steel_area

    def extent(self, u: Iterable[float]) -> tuple[float, float]:
        """(least, largest) projection of the polygon on ``u`` [mm]."""
        xy = _vertices(self.polygon)
        v = xy @ np.asarray(u, dtype=float)
        return float(v.min()), float(v.max())


def _vertices(polygon: Any) -> np.ndarray:
    parts = getattr(polygon, "geoms", [polygon])
    return np.concatenate([np.asarray(p.exterior.coords)[:-1] for p in parts])


def _end_extension(group: Group, leg: Leg, at_start: bool) -> float:
    """How far the wall runs on past its end at a junction: to the other wall's outer face."""
    out = 0.0
    for j in group.junctions:
        if leg.id not in (j.a, j.b):
            continue
        s = j.along(leg.id)
        if (at_start and s <= TOL) or (not at_start and s >= leg.length - TOL):
            out = max(out, group.leg(j.other(leg.id)).thickness / 2)
    return out


def _merge(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1] + 1e-9:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def flange_widths(
    group: Group, leg: Leg, webs: set[str], height: float
) -> tuple[list[tuple[float, float]], list[dict[str, Any]]]:
    """The effective parts of the flange ``leg`` (intervals along it) beside the ``webs`` it
    meets, by 8.3.6.5(b), and what governed each overhang."""
    lo, hi = -_end_extension(group, leg, True), leg.length + _end_extension(group, leg, False)
    meets = sorted(
        (j.along(leg.id), group.leg(j.other(leg.id)).thickness, j.other(leg.id))
        for j in group.junctions
        if leg.id in (j.a, j.b) and j.other(leg.id) in webs
    )
    cap = FLANGE_HEIGHT_SHARE * height
    intervals, info = [], []
    for k, (s, t, web) in enumerate(meets):
        sides = []
        for step in (-1, 1):
            n = k + step
            if 0 <= n < len(meets):
                s2, t2, _ = meets[n]
                clear = abs(s2 - s) - t / 2 - t2 / 2
                half = max(clear, 0.0) / 2
                b, why = (half, "half the distance to the next web") if half < cap else (cap, "")
            else:
                b, why = cap, ""
            sides.append((b, why or f"25 % of the wall height {height:.0f} mm"))
        a, z = max(lo, s - t / 2 - sides[0][0]), min(hi, s + t / 2 + sides[1][0])
        intervals.append((a, z))
        info.append(
            {
                "flange": leg.id,
                "web": web,
                "from": round(a, 1),
                "to": round(z, 1),
                "overhang": [
                    round(min(sides[0][0], s - t / 2 - lo), 1),
                    round(min(sides[1][0], hi - s - t / 2), 1),
                ],
                "rule": [sides[0][1], sides[1][1]],
            }
        )
    return _merge(intervals), info


def _rect(leg: Leg, s0: float, s1: float) -> list[tuple[float, float]]:
    t = leg.thickness / 2
    return [tuple(map(float, leg.point(s, n))) for s, n in ((s0, -t), (s1, -t), (s1, t), (s0, t))]


def _inside(leg: Leg, interval: tuple[float, float], p: np.ndarray) -> bool:
    s, n = leg.local(p)
    return interval[0] - 1e-6 < s < interval[1] + 1e-6 and abs(n) < leg.thickness / 2 - 1e-6


def _leg_bars(
    group: Group, leg: Leg, interval: tuple[float, float], full: tuple[float, float]
) -> list[tuple[np.ndarray, float, float]]:
    """(plan point, area, dia) of the bars of ``leg`` within ``interval`` (``full``: the wall's
    own extent, whose free ends carry the type's end bars)."""
    bars = leg.bars
    if bars is None:
        return []
    t = leg.thickness
    dv, dh = bars.vertical_dia, bars.horizontal_dia
    face = t / 2 - bars.cover - dh - dv / 2
    if face <= 0 and bars.layers == 2:
        raise DesignError(f"{leg.id}: the cover leaves no room for two layers of bars")
    ns = [-face, face] if bars.layers == 2 else [0.0]
    inset = bars.cover + dh + dv / 2
    a, z = interval[0] + inset, interval[1] - inset
    out: list[tuple[np.ndarray, float, float]] = []
    b = bars.boundary
    zones: list[tuple[float, float]] = []
    if b is not None:
        for at_start in (True, False):
            end = full[0] if at_start else full[1]
            real = abs(end - (0.0 if at_start else leg.length)) <= TOL
            free = real and _end_extension(group, leg, at_start) == 0.0
            within = interval[0] <= end + TOL and end - TOL <= interval[1]
            if not (free and within):
                continue
            sign = 1 if at_start else -1
            outer = end + sign * (bars.cover + b.hoop_dia + b.dia / 2)
            inner = end + sign * (b.length - b.hoop_dia - b.dia / 2)
            rows = max(1, math.ceil(b.count / 2))
            bx = t / 2 - bars.cover - b.hoop_dia - b.dia / 2
            if bx <= 0 or sign * (inner - outer) < -1e-9:
                raise DesignError(f"{leg.id}: the end bars do not fit the wall's end")
            left = b.count
            for k in range(rows):
                s = outer + (inner - outer) * k / max(rows - 1, 1)
                for n in (-bx, bx) if left >= 2 else (0.0,):
                    out.append((leg.point(s, n), bar_area(b.dia), b.dia))
                    left -= 1
            zones.append(tuple(sorted((end, end + sign * b.length))))
    for s in W._positions(a, z, bars.vertical_spacing):
        if any(z0 - 1e-6 <= s <= z1 + 1e-6 for z0, z1 in zones):
            continue
        for n in ns:
            out.append((leg.point(s, n), bar_area(dv), dv))
    return out


def effective_section(
    group: Group,
    direction: Iterable[float],
    height: float,
    fc: float,
    fy: float,
    es: float = STEEL_E,
) -> FlangedSection:
    """The composite section with the walls along ``direction`` as webs (see the module notes).
    ``height``: the total wall height for 8.3.6.5(b)."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    u = np.asarray(direction, dtype=float)
    u = u / (np.linalg.norm(u) or 1.0)
    webs = {
        leg.id
        for leg in group.legs
        if abs(float(leg.along @ u)) >= math.cos(math.radians(WEB_ANGLE)) - 1e-9
    }
    if not webs:
        raise DesignError("no wall of the group runs along this direction")
    notes: list[str] = []
    parts: list[tuple[Leg, tuple[float, float], tuple[float, float]]] = []
    flanges: list[dict[str, Any]] = []
    # Flanges first: a T's flange runs through the junction, the web's bars there are its.
    for leg in sorted(group.legs, key=lambda g: (g.id in webs, g.id)):
        full = (-_end_extension(group, leg, True), leg.length + _end_extension(group, leg, False))
        if leg.id in webs:
            parts.append((leg, full, full))
            continue
        intervals, info = flange_widths(group, leg, webs, height)
        flanges += info
        if not intervals:
            notes.append(f"{leg.id}: meets no web along this direction: not counted")
        for interval in intervals:
            parts.append((leg, interval, full))
    polygon = unary_union([Polygon(_rect(leg, *interval)) for leg, interval, _ in parts])
    laid: list[tuple[Leg, tuple[float, float]]] = []
    points: list[tuple[np.ndarray, float, float]] = []
    for leg, interval, full in parts:
        for p, area, dia in _leg_bars(group, leg, interval, full):
            if any(_inside(other, iv, p) for other, iv in laid if other.id != leg.id):
                continue
            points.append((p, area, dia))
        laid.append((leg, interval))
    if not points:
        raise DesignError("no vertical bars in the walls of the group")
    from shapely import affinity

    c = polygon.centroid
    origin = (float(c.x), float(c.y))
    moved = affinity.translate(polygon, -origin[0], -origin[1])
    bars = tuple(Bar(float(p[0] - origin[0]), float(p[1] - origin[1]), a, d) for p, a, d in points)
    rects = {}
    for leg, interval, _ in parts:
        rects.setdefault(leg.id, []).append((round(interval[0], 1), round(interval[1], 1)))
    return FlangedSection(
        moved,
        bars,
        fc,
        fy,
        es,
        origin,
        (float(u[0]), float(u[1])),
        sorted(webs),
        flanges,
        rects,
        notes,
    )


# ─────────────────────────────────────── gross properties ───────────────────────────────────────


def gross_moments(polygon: Any) -> tuple[float, np.ndarray, np.ndarray]:
    """(A, first moments (∫x, ∫y), second moments [[∫x², ∫xy], [∫xy, ∫y²]]) of a polygon about
    its own origin (Green's theorem over the rings)."""
    from shapely.geometry.polygon import orient

    area, first, second = 0.0, np.zeros(2), np.zeros((2, 2))
    for p in getattr(polygon, "geoms", [polygon]):
        p = orient(p, 1.0)
        for ring in [p.exterior, *p.interiors]:
            xy = np.asarray(ring.coords)
            x0, y0, x1, y1 = xy[:-1, 0], xy[:-1, 1], xy[1:, 0], xy[1:, 1]
            cr = x0 * y1 - x1 * y0
            area += cr.sum() / 2
            first += [((x0 + x1) * cr).sum() / 6, ((y0 + y1) * cr).sum() / 6]
            xx = ((x0**2 + x0 * x1 + x1**2) * cr).sum() / 12
            yy = ((y0**2 + y0 * y1 + y1**2) * cr).sum() / 12
            xy_ = ((x0 * y1 + 2 * x0 * y0 + 2 * x1 * y1 + x1 * y0) * cr).sum() / 24
            second += [[xx, xy_], [xy_, yy]]
    return area, first, second


def extreme_stress(section: FlangedSection, pu: float, s: Iterable[float]) -> float:
    """The largest compressive stress [MPa] on the gross section under Pu [N] and the moment
    vector ``s`` = (Sx, Sy) [N·mm] (linear elastic, 8.3.6.6(c)): σ = P/A + r·J⁻¹S."""
    area, _, j = gross_moments(section.polygon)
    k = np.linalg.solve(j, np.asarray(s, dtype=float))
    return float(pu / area + (_vertices(section.polygon) @ k).max())


# ─────────────────────────────────────── interaction ───────────────────────────────────────


class FlangedInteraction(InteractionSurface):
    """The φ-factored P-Sx-Sy surface of a :class:`FlangedSection` (see the module notes)."""

    def __init__(self, section: FlangedSection, coarse: bool = False) -> None:
        self.section = section  # type: ignore[assignment]
        self.symmetric = False
        self._subdivisions = 2 if coarse else _SUBDIVISIONS
        step = 2 * _STEP if coarse else _STEP
        steps = round(2 * math.pi / step)
        angles = sorted(
            {*(k * 2 * math.pi / steps for k in range(steps)), *self._switches(2 * math.pi)}
        )
        angles = [a for k, a in enumerate(angles) if k == 0 or a - angles[k - 1] > 1e-4]
        eps_ty = section.fy / section.es
        points = 5 if coarse else _TRANSITION_POINTS
        transition = EPS_CU / (EPS_CU + eps_ty + EPS_CU * np.linspace(0, 1, points))
        depths = _DEPTHS[::2] if coarse else _DEPTHS
        ratios = np.unique(np.concatenate([depths, transition]))
        base = np.array([self._meridian(a, ratios) for a in angles])
        self._meridians = self._interpolate(np.concatenate([base, base[:1]]))

    def _frame(self, theta: float) -> tuple[Any, np.ndarray, np.ndarray]:
        """The polygon and bars in the frame of the neutral axis at ``theta`` (v' towards the
        compressed side n = (-sin θ, cos θ))."""
        from shapely import affinity

        s = self.section
        rotated = affinity.rotate(s.polygon, -theta, origin=(0, 0), use_radians=True)
        xy = np.array([[b.x, b.y] for b in s.bars])
        c, si = math.cos(theta), math.sin(theta)
        local = np.column_stack([xy[:, 0] * c + xy[:, 1] * si, -xy[:, 0] * si + xy[:, 1] * c])
        return rotated, local, np.array([b.area for b in s.bars])

    def actions(self, theta: float, c: float) -> tuple[float, float, float, float]:
        """Nominal (Pn [N], Sx, Sy [N·mm], εt) at the neutral-axis angle ``theta`` and depth
        ``c`` [mm] (math.inf: uniform εcu)."""
        from shapely import clip_by_rect

        s = self.section
        rotated, local, area = self._frame(theta)
        x0, y0, x1, y1 = rotated.bounds
        top = y1
        dist = top - local[:, 1]
        d_bar = float(dist.max())
        if math.isfinite(c):
            a = min(beta1(s.fc) * c, y1 - y0)
            block = clip_by_rect(rotated, x0 - 1, top - a, x1 + 1, top + 1)
            strain = EPS_CU * (c - dist) / c
            eps_t = EPS_CU * (d_bar - c) / c
        else:
            a = y1 - y0
            block = rotated
            strain = np.full(len(dist), EPS_CU)
            eps_t = -EPS_CU
        stress = np.clip(s.es * strain, -s.fy, s.fy) - np.where(dist < a, 0.85 * s.fc, 0.0)
        force = stress * area
        conc = 0.85 * s.fc * float(block.area) if not block.is_empty else 0.0
        if conc > 0:
            ct = block.centroid
            cu, cv = ct.x, ct.y
        else:
            cu = cv = 0.0
        su = conc * cu + float((force * local[:, 0]).sum())
        sv = conc * cv + float((force * local[:, 1]).sum())
        co, si = math.cos(theta), math.sin(theta)
        return conc + float(force.sum()), su * co - sv * si, su * si + sv * co, float(eps_t)

    def _meridian(self, angle: float, ratios: np.ndarray) -> np.ndarray:
        rotated, local, _ = self._frame(angle)
        d_bar = float((rotated.bounds[3] - local[:, 1]).max())
        rows = []
        for d_n in [*(ratios * d_bar), math.inf]:
            pn, sx, sy, eps_t = self.actions(angle, d_n)
            phi = phi_axial_flexure(eps_t, self.section.fy, self.section.es)
            rows.append([phi * pn, phi * sx, phi * sy])
        return np.array(rows)

    def capacity(self, pu: float, direction: Iterable[float]) -> float:
        """φMn [N·mm] at ``pu`` along the signed moment direction ``direction`` (the
        compressed side, as S); 0 outside the surface."""
        p = self.contour(pu)
        if p is None or not _encloses_origin(p):
            return 0.0
        u = np.asarray(direction, dtype=float)
        u = u / (np.linalg.norm(u) or 1.0)
        d = np.roll(p, -1, axis=0) - p
        det = d[:, 0] * u[1] - d[:, 1] * u[0]
        ok = np.abs(det) > 1e-12 * np.maximum(1.0, (d * d).sum(axis=1))
        safe = np.where(ok, det, 1.0)
        t = (p[:, 1] * d[:, 0] - p[:, 0] * d[:, 1]) / safe
        r = (u[0] * p[:, 1] - u[1] * p[:, 0]) / safe
        ok &= (t >= 0) & (r >= -1e-12) & (r <= 1 + 1e-12)
        return float(t[ok].min()) if ok.any() else 0.0

    def check(self, pu: float, sx: float, sy: float) -> ColumnCheck:  # type: ignore[override]
        """Utilisation of (Pu, Sx, Sy) along the demand's own signed direction."""
        s = self.section
        mu = math.hypot(sx, sy)
        if pu > s.phi_pn_max:
            return ColumnCheck(pu / s.phi_pn_max, 0.0, mu, "Pu exceeds φPn,max")
        if pu < -s.phi_tension:
            return ColumnCheck(-pu / s.phi_tension, 0.0, mu, "tension exceeds φ fy Ast")
        if mu <= 0:
            axial = pu / s.phi_pn_max if pu >= 0 else -pu / s.phi_tension
            return ColumnCheck(axial, 0.0, 0.0, "axial force only")
        cap = self.capacity(pu, (sx, sy))
        if cap <= 0:
            return ColumnCheck(math.inf, 0.0, mu, "no moment capacity at this axial force")
        return ColumnCheck(mu / cap, cap, mu, "")

    def nominal(self, pu: float, direction: Iterable[float]) -> tuple[float, float]:  # type: ignore[override]
        """(Mn along ``direction`` [N·mm], c [mm]) at Pn = ``pu`` with the neutral axis across
        ``direction`` and the compression on its side; (0, inf) when ``pu`` is beyond the
        section's compressive strength, (0, 0) beyond its tensile strength."""
        u = np.asarray(direction, dtype=float)
        u = u / (np.linalg.norm(u) or 1.0)
        theta = math.atan2(-u[0], u[1])
        lo_x, hi_x = self.section.extent(u)
        depth = hi_x - lo_x
        lo, hi = 1e-6 * depth, 50.0 * depth
        if self.actions(theta, hi)[0] < pu:
            return 0.0, math.inf
        if self.actions(theta, lo)[0] > pu:
            return 0.0, 0.0
        for _ in range(70):
            mid = (lo + hi) / 2
            if self.actions(theta, mid)[0] < pu:
                lo = mid
            else:
                hi = mid
        c = (lo + hi) / 2
        _, sx, sy, _ = self.actions(theta, c)
        return float(sx * u[0] + sy * u[1]), c


# ─────────────────────────────────────── forces ───────────────────────────────────────


@dataclass(frozen=True)
class GroupForces:
    """The group's forces at one cut for one combination: P [N] compression positive, the
    moment vector S = Σ F r (Sx, Sy) [N·mm] about the plan point ``about``, the horizontal force
    (Vx, Vy) [N]; ``piers``: each pier's own :class:`walls.PierForces` (for its shear)."""

    combination: str
    P: float
    Sx: float
    Sy: float
    Vx: float
    Vy: float
    earthquake: bool
    where: str
    about: tuple[float, float]
    piers: dict[str, W.PierForces] = field(default_factory=dict)

    def moved(self, point: Iterable[float]) -> tuple[float, float]:
        """(Sx, Sy) about ``point``: S' = S - P (point - about)."""
        p = np.asarray(point, dtype=float) - np.asarray(self.about, dtype=float)
        return self.Sx - self.P * float(p[0]), self.Sy - self.P * float(p[1])


def group_forces(
    group: Group,
    piers: Mapping[str, Mapping[str, Any]],
    earthquake: Iterable[str] | None = None,
    cuts: Iterable[str] = ("bottom", "middle", "top"),
    about: tuple[float, float] | None = None,
) -> list[GroupForces]:
    """The summed cut forces of the group's piers (``piers``: per wall id, its pier of
    :func:`saengine.design.wall_forces.wall_forces` in one storey band, cuts in kN, kN·m) for
    the combinations every pier has. ``earthquake``: the combinations with E (None: all)."""
    seismic = None if earthquake is None else set(earthquake)
    about = about or group.legs[0].start
    ref = np.asarray(about, dtype=float)
    out = []
    for cut in cuts:
        tables = {wid: (p.get("cuts", {}).get(cut) or {}) for wid, p in piers.items()}
        if not tables or any(not t for t in tables.values()):
            continue
        names = [n for n in next(iter(tables.values())) if all(n in t for t in tables.values())]
        for name in names:
            total = np.zeros(5)  # P, Sx, Sy, Vx, Vy
            own: dict[str, W.PierForces] = {}
            for wid, table in tables.items():
                leg = group.leg(wid)
                pier = piers[wid]
                r = table[name]
                e2, e3 = leg.along, np.array([-leg.along[1], leg.along[0]])
                centre = leg.point((float(pier["start"]) + float(pier["end"])) / 2)
                p = float(r.get("P", 0.0)) * 1e3
                m = (float(r.get("M2", 0.0)) * e2 + float(r.get("M3", 0.0)) * e3) * 1e6
                s = np.array([m[1], -m[0]]) + p * (centre - ref)
                v = (float(r.get("V2", 0.0)) * e2 + float(r.get("V3", 0.0)) * e3) * 1e3
                total += [p, s[0], s[1], v[0], v[1]]
                own[wid] = W.PierForces(
                    name,
                    p,
                    float(r.get("V2", 0.0)) * 1e3,
                    float(r.get("M3", 0.0)) * 1e6,
                    float(r.get("V3", 0.0)) * 1e3,
                    float(r.get("M2", 0.0)) * 1e6,
                    True if seismic is None else name in seismic,
                    f"{pier.get('pier', wid)} {cut}",
                )
            out.append(
                GroupForces(
                    name,
                    *map(float, total),
                    True if seismic is None else name in seismic,
                    cut,
                    (float(ref[0]), float(ref[1])),
                    own,
                )
            )
    return out


# ─────────────────────────────────────── the checks ───────────────────────────────────────


def _kn(v: float) -> float:
    return v / 1e3


def _knm(v: float) -> float:
    return v / 1e6


def _angle(u: Iterable[float]) -> float:
    x, y = u
    return math.degrees(math.atan2(y, x)) % 180.0


@dataclass
class FlangedDesign:
    checks: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    sections: list[FlangedSection] = field(default_factory=list)
    boundary: list[dict[str, Any]] = field(default_factory=list)
    utilisation: float = 0.0


def _edge(section: FlangedSection, group: Group, u: np.ndarray) -> tuple[str, Leg, np.ndarray]:
    """("web" | "flange", the wall, the extreme point) at the extreme fibre towards ``u``."""
    xy = _vertices(section.polygon)
    k = int(np.argmax(xy @ u))
    point = xy[k] + np.asarray(section.origin)
    best: tuple[float, Leg] | None = None
    for leg in group.legs:
        s, n = leg.local(point)
        if (
            abs(n) <= leg.thickness / 2 + TOL
            and -leg.thickness - TOL <= s <= leg.length + leg.thickness + TOL
        ):
            web = abs(float(leg.along @ u)) >= math.cos(math.radians(WEB_ANGLE))
            # A wall across u at the extreme fibre is a flange there, else the web's end.
            score = 0.0 if not web else 1.0
            if best is None or score < best[0]:
                best = (score, leg)
    if best is None:
        leg = min(group.legs, key=lambda g: abs(g.local(point)[1]))
        best = (1.0, leg)
    kind = "web" if best[0] > 0 else "flange"
    return kind, best[1], point


def flanged_checks(
    group: Group,
    forces: list[GroupForces],
    fc: float,
    fy: float,
    es: float = STEEL_E,
    *,
    height: float,
    special: bool = False,
    drift: float | None = None,
    continuous: bool = True,
    lam: float = 1.0,
) -> FlangedDesign:
    """The checks of a group of walls as flanged sections (see the module notes): P-M per
    combination and cut on the section of the web direction nearest the moment's, the webs'
    shear per direction, and (``special``) the boundary elements at each extreme fibre.
    ``height``: total wall height hw [mm]; ``drift``: δu/hw (None: the stress method)."""
    out = FlangedDesign()
    dirs = families(group.legs)
    surfaces: list[tuple[np.ndarray, FlangedSection, FlangedInteraction]] = []
    for u in dirs:
        section = effective_section(group, u, height, fc, fy, es)
        surfaces.append((u, section, FlangedInteraction(section)))
        out.sections.append(section)
        out.notes += section.notes
    if any(" [" in f.combination for f in forces):
        out.notes.append(
            "response spectrum combinations: the piers' modal resultants are combined per pier "
            "before they are summed, which does not cancel their opposite modal forces (on the "
            "safe side for the axial force, not exact for the moment)"
        )

    def nearest(f: GroupForces) -> list[int]:
        values = [f.moved(sec.origin) for _, sec, _ in surfaces]
        mags = [math.hypot(*v) for v in values]
        if max(mags) <= 0:
            return list(range(len(surfaces)))
        k = max(
            range(len(surfaces)),
            key=lambda i: abs(np.dot(surfaces[i][0], values[i])) / (mags[i] or 1),
        )
        return [k]

    # Axial force and bending.
    worst: tuple[ColumnCheck, GroupForces, int] | None = None
    for f in forces:
        for k in nearest(f):
            sx, sy = f.moved(surfaces[k][1].origin)
            r = surfaces[k][2].check(f.P, sx, sy)
            if worst is None or r.utilisation > worst[0].utilisation:
                worst = (r, f, k)
    clause = "8.3.6.5(a)" if special else "6.6.4"
    if worst is not None:
        r, f, k = worst
        u, section, _ = surfaces[k]
        sx, sy = f.moved(section.origin)
        along = sx * u[0] + sy * u[1]
        across = -sx * u[1] + sy * u[0]
        out.checks.append(
            _row(
                f"Axial force and bending, flanged section ({clause}; flanges 8.3.6.5(b))",
                _knm(r.mu),
                _knm(r.phi_mn),
                "kN·m",
                f.combination,
                f"webs {', '.join(section.webs)} ({_angle(u):.0f}°): Pu = {_kn(f.P):.1f} kN, M "
                f"along the webs = {_knm(along):.1f}, across = {_knm(across):.1f} kN·m at "
                f"{f.where}; Ag = {section.gross_area / 1e6:.3f} m², {len(section.bars)} bars"
                + (f"; {r.note}" if r.note else ""),
                utilisation=r.utilisation,
            )
        )

    # Shear along each direction: the webs together (8.3.6.4(d) for special walls).
    for u, section, surface in surfaces:
        webs = [group.leg(w) for w in section.webs]
        best: tuple[float, dict[str, Any]] | None = None
        for f in forces:
            vu = abs(f.Vx * u[0] + f.Vy * u[1])
            if vu <= 0:
                continue
            vn, acv, parts = 0.0, 0.0, []
            for leg in webs:
                pf = f.piers.get(leg.id)
                if leg.bars is None or pf is None:
                    continue
                g = W.WallGeometry(leg.length, leg.thickness, height, height)
                if special:
                    sv = W.special_vn(g, leg.bars.rho_t(leg.thickness), fc, fy, lam)
                    vn_i = sv["vn"]
                else:
                    vn_i = float(W.wall_vn(g, leg.bars, pf, fc, fy, lam)["vn"])
                vn += vn_i
                acv += g.gross_area
                parts.append(f"{leg.id} {_kn(vn_i):.0f}")
            if vn <= 0:
                continue
            limit = COMBINED_SHEAR * acv * math.sqrt(fc)
            note_limit = ""
            if special and vn > limit:
                vn, note_limit = limit, f"; 0.66 Acv √f'c = {_kn(limit):.1f} kN governs"
            phi = PHI_SHEAR
            if special:
                sx, sy = f.moved(section.origin)
                mu = abs(sx * u[0] + sy * u[1])
                sense = 1 if sx * u[0] + sy * u[1] >= 0 else -1
                mn, _ = surface.nominal(f.P, sense * u)
                v_at_mn = vu * mn / mu if mu > 0 else math.inf
                if vn < v_at_mn:
                    phi = W.PHI_SHEAR_SEISMIC
            u_ = vu / (phi * vn)
            if best is None or u_ > best[0]:
                best = (
                    u_,
                    {
                        "vu": vu,
                        "cap": phi * vn,
                        "f": f,
                        "note": f"Vn of the webs ({', '.join(parts)} kN){note_limit}; φ = "
                        f"{phi:.2f}",
                    },
                )
        if best is not None:
            u_, b = best
            out.checks.append(
                _row(
                    f"Shear along {', '.join(section.webs)}, webs together "
                    + ("(8.3.6.4(a), (d))" if special else "(6.4.8)"),
                    _kn(b["vu"]),
                    _kn(b["cap"]),
                    "kN",
                    b["f"].combination,
                    b["note"],
                    utilisation=u_,
                )
            )

    if special:
        out.checks += _boundary(group, forces, surfaces, fc, height, drift, continuous, out)
    strength = [c for c in out.checks if not c["flag"]]
    out.utilisation = max((c["utilisation"] for c in strength), default=0.0)
    return out


def boundary_length(c: float, lw: float, flange: Leg | None = None) -> float:
    """Least length from the extreme compression fibre (8.3.6.6(d)(i)), with a flange in
    compression its thickness plus 300 mm into the web (8.3.6.6(d)(ii)), rounded up to 50 mm."""
    need = W.boundary_length(c, lw)
    if flange is not None:
        need = max(need, flange.thickness + INTO_WEB)
    return math.ceil(max(need, W.LENGTH_STEP) / W.LENGTH_STEP - 1e-9) * W.LENGTH_STEP


def _boundary(
    group: Group,
    forces: list[GroupForces],
    surfaces: list[tuple[np.ndarray, FlangedSection, FlangedInteraction]],
    fc: float,
    height: float,
    drift: float | None,
    continuous: bool,
    out: FlangedDesign,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    method = "displacement" if drift is not None and continuous else "stress"
    seismic = [f for f in forces if f.earthquake] or list(forces)
    base = [f for f in seismic if f.where == "bottom"] or seismic
    for u, section, surface in surfaces:
        lo, hi = section.extent(u)
        lw = hi - lo
        for sense in (1, -1):
            d = sense * u
            kind, leg, _ = _edge(section, group, d)
            where = f"{'flange' if kind == 'flange' else 'end of'} {leg.id}"
            c_max, stress, governing = 0.0, -math.inf, None
            for f in seismic:
                _, c = surface.nominal(f.P, d)
                if c > c_max:
                    c_max = c
                    governing = f
                sx, sy = f.moved(section.origin)
                if sx * d[0] + sy * d[1] > 0:
                    stress = max(stress, extreme_stress(section, f.P, (sx, sy)))
            if method == "displacement":
                trigger = W.displacement_trigger(lw, drift or 0.0)
                required = c_max >= trigger
                shown_c = f"{c_max:.0f}" if math.isfinite(c_max) else "∞"
                row = _row(
                    f"Boundary element at {where}: c >= lw / 600(δu/hw) (8.3.6.6(b))",
                    c_max if math.isfinite(c_max) else 99_999.0,
                    trigger,
                    "mm",
                    governing.combination if governing else None,
                    f"c = {shown_c} mm, lw = {lw:.0f} mm along {_angle(u):.0f}°: "
                    + ("required" if required else "not required"),
                )
            else:
                stress = max(stress, 0.0)
                required = stress > W.STRESS_REQUIRED * fc
                row = _row(
                    f"Boundary element at {where}: stress > 0.2 f'c, flanged gross section "
                    "(8.3.6.6(c))",
                    stress,
                    W.STRESS_REQUIRED * fc,
                    "MPa",
                    note="required" if required else "not required",
                )
            row["flag"] = True
            rows.append(row)
            entry: dict[str, Any] = {
                "where": where,
                "wall": leg.id,
                "edge": kind,
                "direction": round(_angle(u), 1),
                "sense": sense,
                "required": bool(required),
                "method": method,
                "c": round(c_max, 1) if math.isfinite(c_max) else None,
                "length": None,
            }
            if required:
                flange = leg if kind == "flange" else None
                need = boundary_length(c_max if math.isfinite(c_max) else lw, lw, flange)
                tall = height
                if governing is not None and base:
                    g = max(base, key=lambda f: abs(f.Vx * u[0] + f.Vy * u[1]))
                    vu = abs(g.Vx * u[0] + g.Vy * u[1])
                    sx, sy = g.moved(section.origin)
                    mu = abs(sx * u[0] + sy * u[1])
                    tall = max(lw, mu / (4 * vu)) if vu > 0 else lw
                provided, how = 0.0, ""
                b = leg.bars.boundary if leg.bars is not None else None
                if kind == "web" and b is not None and b.hoops:
                    provided, how = b.length, f"the type's end bars over {b.length:.0f} mm"
                elif kind == "flange":
                    how = (
                        "the wall types do not detail a flanged boundary element: confine the "
                        "flange's effective width in compression and 300 mm into the web"
                    )
                else:
                    how = "the wall type has no end bars with hoops"
                entry["length"] = need
                entry["height"] = round(tall, 0)
                rows.append(
                    _row(
                        f"Boundary element length at {where} (8.3.6.6(d)(i)"
                        + (", (ii))" if flange else ")"),
                        need,
                        provided,
                        "mm",
                        governing.combination if governing else None,
                        "max(c - 0.1 lw, c/2"
                        + (f", t_flange + {INTO_WEB:.0f}" if flange else "")
                        + f") from the extreme fibre; over {tall:.0f} mm above the critical "
                        f"section; {how}",
                    )
                )
            out.boundary.append(entry)
    return rows


def section_json(section: FlangedSection) -> dict[str, Any]:
    """The report's summary of a section (no geometry beyond the walls' effective parts)."""
    area, _, j = gross_moments(section.polygon)
    return {
        "direction": round(_angle(section.direction), 1),
        "webs": section.webs,
        "parts": {k: [list(v) for v in vs] for k, vs in section.rects.items()},
        "flanges": section.flanges,
        "area": round(area / 1e6, 4),
        "centroid": [round(section.origin[0], 1), round(section.origin[1], 1)],
        "inertia": [round(j[0, 0] / 1e12, 4), round(j[1, 1] / 1e12, 4), round(j[0, 1] / 1e12, 4)],
        "bars": len(section.bars),
        "steel": round(section.steel_area, 0),
    }

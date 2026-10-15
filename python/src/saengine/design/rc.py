"""Section capacities of reinforced-concrete members by strength design.

The code basis is ACI 318-19, which BNBC 2020 Part 6 Chapter 6 adopts: the same clauses and
factors apply to both.

- Flexure and axial force: strain compatibility with the ACI rectangular stress block
  (0.85 f'c over β1 c, εcu = 0.003) and elastic-perfectly plastic bars, analysed with
  concreteproperties (MIT). Bars displace the concrete they occupy.
- Strength reduction (ACI 21.2.2): φ = 0.90 when the net tensile strain εt of the extreme
  tension bar is at least εty + 0.003 (tension-controlled), 0.65 for tied and 0.75 for spiral
  members when εt is at most εty = fy / Es (compression-controlled), linear between.
- Shear (ACI 22.5): φVn = 0.75 (Vc + Vs); Vc = 0.17 λ √f'c b d when Av >= Av,min, else
  0.66 λs λ ρw^(1/3) √f'c b d (Table 22.5.5.1), Vs = Av fyt d / s with Vs at most
  0.66 √f'c b d, √f'c at most 8.3 MPa and fyt at most 420 MPa (see :func:`shear`).
- Axial (ACI 22.4.2): φPn,max = 0.80 φ P0 for tied and 0.85 φ P0 for spiral columns, with
  P0 = 0.85 f'c (Ag - Ast) + fy Ast.
- Biaxial bending of columns: the capacity at the demand's axial force in the direction of the
  demand's moment vector, read from the φ-factored interaction surface: meridians (φPn, φMnx,
  φMny) are computed at neutral-axis angles 15° apart, cut at φPn = Pu, and the demand ray is
  intersected with the resulting contour (chords between the computed points: slightly
  conservative).

Units: mm, MPa, N, N·mm. Section coordinates: x along the profile's width (``xDim``), y along
its depth (``yDim``), origin at the centroid, +y the "top" face.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import cached_property

import numpy as np

from saengine.library.objects import CircleProfile, LinearReinforcement, RectangleProfile

EPS_CU = 0.003
"""Concrete strain at the extreme compression fibre at nominal strength (ACI 22.2.2.1)."""
STEEL_E = 200_000.0
PHI_TENSION = 0.90
PHI_TIED = 0.65
PHI_SPIRAL = 0.75
PHI_SHEAR = 0.75
FYT_SHEAR_MAX = 420.0
SLENDERNESS_LIMIT = 22.0
"""k lu / r below which slenderness may be neglected in sway frames (ACI 6.2.5.1(a))."""

#: Neutral-axis angles of the interaction surface within a quadrant.
_QUADRANT = np.radians(np.arange(0, 91, 15))
#: Neutral-axis depths of a meridian, as a share of the section depth at that angle.
_DEPTHS = np.concatenate(
    [np.geomspace(1e-3, 0.05, 6), np.linspace(0.07, 1.4, 24), np.geomspace(1.6, 8.0, 6)]
)


class DesignError(ValueError):
    """The member cannot be checked (unsupported profile, no bars, ...)."""


def beta1(fc: float) -> float:
    """Depth factor of the rectangular stress block (ACI Table 22.2.2.4.3)."""
    if fc <= 28:
        return 0.85
    if fc >= 55:
        return 0.65
    return 0.85 - 0.05 * (fc - 28) / 7


def phi_axial_flexure(eps_t: float, fy: float, es: float = STEEL_E, spiral: bool = False) -> float:
    """φ for moment and axial force from the net tensile strain (ACI Table 21.2.2)."""
    eps_ty = fy / es
    low = PHI_SPIRAL if spiral else PHI_TIED
    if eps_t <= eps_ty:
        return low
    if eps_t >= eps_ty + EPS_CU:
        return PHI_TENSION
    return low + (PHI_TENSION - low) * (eps_t - eps_ty) / EPS_CU


def bar_area(dia: float) -> float:
    return math.pi * dia**2 / 4


@dataclass(frozen=True)
class Bar:
    x: float
    y: float
    area: float
    dia: float


@dataclass(frozen=True)
class RcSection:
    """A reinforced-concrete cross-section: profile, bars and materials."""

    profile: RectangleProfile | CircleProfile
    bars: tuple[Bar, ...]
    fc: float
    fy: float
    es: float = STEEL_E
    spiral: bool = False
    transverse_dia: float = 0.0
    notes: tuple[str, ...] = field(default=())

    @property
    def width(self) -> float:
        p = self.profile
        return p.xDim if isinstance(p, RectangleProfile) else 2 * p.radius

    @property
    def depth(self) -> float:
        p = self.profile
        return p.yDim if isinstance(p, RectangleProfile) else 2 * p.radius

    @property
    def gross_area(self) -> float:
        p = self.profile
        return p.xDim * p.yDim if isinstance(p, RectangleProfile) else math.pi * p.radius**2

    @property
    def steel_area(self) -> float:
        return sum(b.area for b in self.bars)

    @property
    def p0(self) -> float:
        """Nominal axial strength at zero eccentricity [N] (ACI 22.4.2.2)."""
        ast = self.steel_area
        return 0.85 * self.fc * (self.gross_area - ast) + self.fy * ast

    @property
    def phi_pn_max(self) -> float:
        """Largest design axial compression [N] (ACI Table 22.4.2.1)."""
        if self.spiral:
            return 0.85 * PHI_SPIRAL * self.p0
        return 0.80 * PHI_TIED * self.p0

    @property
    def phi_tension(self) -> float:
        """Design axial tension [N]: the bars at yield."""
        return PHI_TENSION * self.fy * self.steel_area

    @property
    def symmetric(self) -> bool:
        """True when the bars are symmetric about both section axes."""

        def mirrored(sx: int, sy: int) -> bool:
            for b in self.bars:
                if not any(
                    abs(o.x - sx * b.x) < 1 and abs(o.y - sy * b.y) < 1 and abs(o.area - b.area) < 1
                    for o in self.bars
                ):
                    return False
            return True

        return mirrored(-1, 1) and mirrored(1, -1)

    def effective_depth(self, top: bool) -> float:
        """Depth from the compression face to the centroid of the tension bars of that face's
        half: the bottom bars for sagging (``top`` False), the top bars for hogging."""
        h = self.depth
        tension = [b for b in self.bars if (b.y > 0 if top else b.y < 0)]
        if not tension:
            raise DesignError("no bars on the tension face")
        centroid = sum(b.area * b.y for b in tension) / sum(b.area for b in tension)
        return h / 2 + (centroid if top else -centroid)

    @cached_property
    def analysis(self):
        return _concrete_section(self)


def section_of(
    profile: object,
    reinforcement: LinearReinforcement,
    fc: float,
    fy: float,
    es: float = STEEL_E,
) -> RcSection:
    """The section of a member type, with its bars laid out from the reinforcement groups.

    Rectangles: see :func:`_rectangle_bars`. Circles: every group as a ring.
    """
    if not isinstance(profile, (RectangleProfile, CircleProfile)):
        shape = getattr(profile, "shape", "?")
        raise DesignError(f"profile '{shape}' is not supported (rectangle and circle only)")
    if not reinforcement.longitudinal:
        raise DesignError("no longitudinal bars")
    transverse = reinforcement.transverse
    tdia = transverse.dia if transverse else 0.0
    inset = reinforcement.cover + tdia
    bars: list[Bar] = []
    notes: list[str] = []
    if isinstance(profile, CircleProfile):
        for group in reinforcement.longitudinal:
            r = profile.radius - inset - group.dia / 2
            if r <= 0:
                raise DesignError("the cover leaves no room for the bars")
            for k in range(group.count):
                angle = 2 * math.pi * k / group.count
                bars.append(
                    Bar(r * math.cos(angle), r * math.sin(angle), bar_area(group.dia), group.dia)
                )
    else:
        bars, notes = _rectangle_bars(profile, reinforcement, inset)
    if not bars:
        raise DesignError("no longitudinal bars")
    return RcSection(
        profile=profile,
        bars=tuple(bars),
        fc=fc,
        fy=fy,
        es=es,
        spiral=bool(transverse and transverse.type == "spiral"),
        transverse_dia=tdia,
        notes=tuple(notes),
    )


def _arrange(dias: list[float]) -> list[float]:
    """Bars of one row or face in order, symmetric where the counts allow: equal bars in pairs
    from the ends inwards, the largest outermost, the unpaired ones in the middle."""
    slots: list[float] = [0.0] * len(dias)
    lo, hi = 0, len(dias) - 1
    unpaired: list[float] = []
    for dia in sorted(set(dias), reverse=True):
        pairs, odd = divmod(dias.count(dia), 2)
        for _ in range(pairs):
            slots[lo], slots[hi] = dia, dia
            lo, hi = lo + 1, hi - 1
        unpaired += [dia] * odd
    slots[lo : hi + 1] = unpaired
    return slots


def _rectangle_bars(
    profile: RectangleProfile, reinforcement: LinearReinforcement, inset: float
) -> tuple[list[Bar], list[str]]:
    """The bars of a rectangle, from all its bar groups (several groups may share a position,
    e.g. 3T20 + 2T16 bottom: they form one row, larger bars at the ends).

    ``top`` and ``bottom`` bars lie in one row inside the cover and the transverse bars, each
    bar resting on the stirrup; ``sides`` are shared between the two vertical faces, evenly
    spaced between the top and bottom rows. ``perimeter`` bars: the four largest at the corners,
    the rest shared between the faces in proportion to their lengths; ``top``, ``bottom`` and
    ``sides`` groups beside a perimeter group are added between its corner bars on those faces
    (the corners are never counted twice).
    """
    b, h = profile.xDim, profile.yDim
    dias: dict[str, list[float]] = {"top": [], "bottom": [], "sides": [], "perimeter": []}
    for group in reinforcement.longitudinal:
        dias[group.position] += [group.dia] * group.count
    notes: list[str] = []
    ring = sorted(dias["perimeter"], reverse=True)
    sides = sorted(dias["sides"], reverse=True)
    if ring:
        if len(ring) < 4:
            raise DesignError("a rectangular member needs at least 4 perimeter bars")
        corners, rest = ring[:4], ring[4:]
        pairs, odd = divmod(len(rest), 2)
        per_x_face = round(pairs * b / (b + h))  # bars between the corners on the x faces
        per_y_face = pairs - per_x_face
        room = {"top": per_x_face, "bottom": per_x_face + odd, "left": per_y_face}
        room["right"] = per_y_face
        faces: dict[str, list[float]] = {face: [] for face in room}
        order = ["top", "bottom", "left", "right"]
        k = 0
        for dia in rest:
            while len(faces[order[k % 4]]) >= room[order[k % 4]]:
                k += 1
            faces[order[k % 4]].append(dia)
            k += 1
        if odd:
            notes.append("odd perimeter bar count: the extra bar is placed on the bottom face")
        if dias["top"] or dias["bottom"] or sides:
            notes.append("top, bottom and side bars are added between the perimeter corner bars")
        top = [corners[0], *_arrange(faces["top"] + dias["top"]), corners[1]]
        bottom = [corners[2], *_arrange(faces["bottom"] + dias["bottom"]), corners[3]]
        left, right = faces["left"] + sides[0::2], faces["right"] + sides[1::2]
    else:
        top, bottom = _arrange(dias["top"]), _arrange(dias["bottom"])
        left, right = sides[0::2], sides[1::2]

    bars: list[Bar] = []
    levels: dict[int, float] = {}
    for name, row, sy in (("top", top, 1), ("bottom", bottom, -1)):
        if not row:
            continue
        reach = [b / 2 - inset - d / 2 for d in row]
        heights = [h / 2 - inset - d / 2 for d in row]
        if min(reach) <= 0 or min(heights) <= 0:
            raise DesignError("the cover leaves no room for the bars")
        xs = [0.0] if len(row) == 1 else list(np.linspace(-reach[0], reach[-1], len(row)))
        bars += [
            Bar(float(x), sy * y, bar_area(d), d) for x, y, d in zip(xs, heights, row, strict=True)
        ]
        levels[sy] = sy * min(heights)
        gaps = [xs[k + 1] - xs[k] - (row[k] + row[k + 1]) / 2 for k in range(len(row) - 1)]
        if gaps and min(gaps) < max(25.0, max(row)):
            notes.append(
                f"{name} row: clear spacing {min(gaps):.0f} mm is below max(25 mm, db); "
                "the bars are still taken in one row"
            )
    for sx, face in ((-1, left), (1, right)):
        if not face:
            continue
        face = _arrange(face)
        largest = max(face)
        reach = b / 2 - inset - largest / 2
        y_top = levels.get(1, h / 2 - inset - largest / 2)
        y_bottom = levels.get(-1, -(h / 2 - inset - largest / 2))
        if reach <= 0 or y_top <= y_bottom:
            raise DesignError("the cover leaves no room for the bars")
        ys = np.linspace(y_bottom, y_top, len(face) + 2)[1:-1]
        bars += [
            Bar(sx * (b / 2 - inset - d / 2), float(y), bar_area(d), d)
            for y, d in zip(ys, face, strict=True)
        ]
    return bars, notes


def _concrete_section(section: RcSection):
    from concreteproperties.concrete_section import ConcreteSection
    from concreteproperties.material import Concrete, SteelBar
    from concreteproperties.pre import add_bar
    from concreteproperties.stress_strain_profile import (
        ConcreteLinear,
        RectangularStressBlock,
        SteelElasticPlastic,
    )
    from sectionproperties.pre.library import circular_section_by_area, rectangular_section

    concrete = Concrete(
        name="concrete",
        density=2.4e-6,
        stress_strain_profile=ConcreteLinear(elastic_modulus=4700 * math.sqrt(section.fc)),
        ultimate_stress_strain_profile=RectangularStressBlock(
            compressive_strength=section.fc,
            alpha=0.85,
            gamma=beta1(section.fc),
            ultimate_strain=EPS_CU,
        ),
        flexural_tensile_strength=0.62 * math.sqrt(section.fc),
        colour="lightgrey",
    )
    steel = SteelBar(
        name="bars",
        density=7.85e-6,
        stress_strain_profile=SteelElasticPlastic(
            yield_strength=section.fy, elastic_modulus=section.es, fracture_strain=0.05
        ),
        colour="grey",
    )
    p = section.profile
    if isinstance(p, RectangleProfile):
        geometry = rectangular_section(d=p.yDim, b=p.xDim, material=concrete).shift_section(
            x_offset=-p.xDim / 2, y_offset=-p.yDim / 2
        )
    else:
        geometry = circular_section_by_area(area=math.pi * p.radius**2, n=48, material=concrete)
    for bar in section.bars:
        geometry = add_bar(geometry, area=bar.area, material=steel, x=bar.x, y=bar.y)
    return ConcreteSection(geometry, moment_centroid=(0.0, 0.0))


# ─────────────────────────────────────── beams ───────────────────────────────────────


@dataclass(frozen=True)
class Flexure:
    phi_mn: float  # N·mm
    mn: float
    phi: float
    eps_t: float


def flexure(section: RcSection, hogging: bool) -> Flexure:
    """Design moment of a beam section without axial force: sagging puts the bottom bars in
    tension, hogging the top bars."""
    from concreteproperties.utils import AnalysisError

    tension = [b for b in section.bars if (b.y > 0 if hogging else b.y < 0)]
    if not tension:
        return Flexure(0.0, 0.0, PHI_TENSION, float("inf"))
    try:
        result = section.analysis.ultimate_bending_capacity(theta=math.pi if hogging else 0.0, n=0)
    except AnalysisError:
        return Flexure(0.0, 0.0, PHI_TENSION, float("inf"))
    eps_t = EPS_CU * (1 / result.k_u - 1)
    phi = phi_axial_flexure(eps_t, section.fy, section.es, section.spiral)
    mn = abs(result.m_x)
    return Flexure(phi * mn, mn, phi, eps_t)


@dataclass(frozen=True)
class Shear:
    phi_vn: float  # N
    vc: float
    vs: float
    vs_limited: bool
    d: float
    av: float  # mm², stirrup legs at one spacing (0 without stirrups)
    av_min: float  # mm², ACI 9.6.3.4 at that spacing (0 without stirrups)
    rho_w: float
    lambda_s: float
    with_min_stirrups: bool  # Av >= Av,min: simplified Vc (ACI Table 22.5.5.1 (a))
    vc_simplified: float  # N, 0.17 λ √f'c bw d

    @property
    def av_min_threshold(self) -> float:
        """Vu [N] above which ACI 9.6.3.1 requires at least Av,min: 0.083 φ λ √f'c bw d."""
        return PHI_SHEAR * self.vc_simplified * 0.083 / 0.17


def shear(
    section: RcSection,
    stirrup_dia: float | None,
    legs: int,
    spacing: float | None,
    lam: float = 1.0,
) -> Shear:
    """Design shear strength of a rectangular, non-prestressed beam without axial force.

    ACI 318-19 Table 22.5.5.1 with Nu = 0: when Av >= Av,min (9.6.3.4: max(0.062 √f'c,
    0.35) bw s / fyt), Vc = 0.17 λ √f'c bw d (a); otherwise Vc = 0.66 λs λ ρw^(1/3) √f'c bw d
    (c) with the size effect λs = √(2 / (1 + 0.004 d)) <= 1 (22.5.5.1.3). Vc <= 0.42 λ √f'c bw d,
    √f'c <= 8.3 MPa in Vc (22.5.3.1), fyt <= 420 MPa (20.2.2.4), Vs = Av fyt d / s <=
    0.66 √f'c bw d (the section limit of 22.5.1.2). ρw = As / (bw d) of the face with the fewer bars (conservative: shear at a
    support meets hogging, at midspan sagging).
    """
    if not isinstance(section.profile, RectangleProfile):
        raise DesignError("shear is checked for rectangular beams only")
    b = section.profile.xDim
    try:
        d = section.effective_depth(top=False)
    except DesignError:
        d = section.effective_depth(top=True)
    faces = [
        sum(bar.area for bar in section.bars if (bar.y > 0 if top else bar.y < 0))
        for top in (True, False)
    ]
    rho_w = min(a for a in faces if a > 0) / (b * d)
    root = min(math.sqrt(section.fc), 8.3)
    fyt = min(section.fy, FYT_SHEAR_MAX)
    av = legs * bar_area(stirrup_dia) if stirrup_dia and spacing else 0.0
    av_min = max(0.062 * root, 0.35) * b * spacing / fyt if av else 0.0
    lambda_s = min(1.0, math.sqrt(2 / (1 + 0.004 * d)))
    simplified = 0.17 * lam * root * b * d
    with_min = av > 0 and av >= av_min
    if with_min:
        vc = simplified
    else:
        vc = 0.66 * lambda_s * lam * rho_w ** (1 / 3) * root * b * d
    vc = min(vc, 0.42 * lam * root * b * d)
    vs = av * fyt * d / spacing if av else 0.0
    vs_max = 0.66 * math.sqrt(section.fc) * b * d  # the 8.3 MPa cap is for Vc only
    limited = vs > vs_max
    vs = min(vs, vs_max)
    return Shear(
        PHI_SHEAR * (vc + vs),
        vc,
        vs,
        limited,
        d,
        av,
        av_min,
        rho_w,
        lambda_s,
        with_min,
        simplified,
    )


# ─────────────────────────────────────── columns ───────────────────────────────────────


@dataclass(frozen=True)
class ColumnCheck:
    utilisation: float
    phi_mn: float  # N·mm, capacity along the demand's moment direction at Pu (0 if none)
    mu: float  # N·mm, resultant demand moment
    note: str


class InteractionSurface:
    """The φ-factored P-Mx-My interaction surface of a column section (compression positive)."""

    def __init__(self, section: RcSection) -> None:
        from concreteproperties.utils import calculate_extreme_fibre

        self.section = section
        cp = section.analysis
        points = cp.compound_geometry.points
        # Quadrants of neutral-axis angles: one suffices for a doubly symmetric bar layout.
        offsets = [0.0] if section.symmetric else [0.0, math.pi / 2, math.pi, -math.pi / 2]
        self.quadrants: list[list[np.ndarray]] = []
        for offset in offsets:
            meridians = []
            for angle in _QUADRANT + offset:
                theta = math.atan2(math.sin(angle), math.cos(angle))
                _, d_t = calculate_extreme_fibre(points=points, theta=theta)
                rows = [self._point(theta, d_n) for d_n in [*(_DEPTHS * d_t), math.inf]]
                meridians.append(np.array(rows))
            self.quadrants.append(meridians)

    def _point(self, theta: float, d_n: float) -> list[float]:
        from concreteproperties.results import UltimateBendingResults

        cp = self.section.analysis
        result = cp.calculate_ultimate_section_actions(
            d_n=d_n,
            ultimate_results=UltimateBendingResults(default_units=cp.default_units, theta=theta),
        )
        k_u = result.k_u if result.k_u else math.inf
        eps_t = EPS_CU * (1 / k_u - 1) if math.isfinite(d_n) else -EPS_CU
        phi = phi_axial_flexure(eps_t, self.section.fy, self.section.es, self.section.spiral)
        return [phi * result.n, phi * abs(result.m_x), phi * abs(result.m_y)]

    def moment_capacity(self, pu: float, angle: float) -> float:
        """φMn [N·mm] at axial force ``pu`` [N] in the direction ``angle`` (rad, 0 … π/2, from
        the x axis) of the moment vector (|Mx|, |My|); the least over the quadrants."""
        return min(self._quadrant_capacity(q, pu, angle) for q in self.quadrants)

    @staticmethod
    def _quadrant_capacity(meridians: list[np.ndarray], pu: float, angle: float) -> float:
        contour = []
        for m in meridians:
            n, mx, my = m[:, 0], m[:, 1], m[:, 2]
            best: tuple[float, float] | None = None
            for k in range(len(n) - 1):
                lo, hi = n[k] - pu, n[k + 1] - pu
                if lo == 0 or lo * hi < 0:
                    t = 0.0 if lo == 0 else lo / (lo - hi)
                    point = (mx[k] + t * (mx[k + 1] - mx[k]), my[k] + t * (my[k + 1] - my[k]))
                    if best is None or math.hypot(*point) < math.hypot(*best):
                        best = point
            if best is None:
                return 0.0  # the axial force is beyond this meridian
            contour.append(best)
        contour.sort(key=lambda p: math.atan2(p[1], p[0]))
        angles = [math.atan2(p[1], p[0]) for p in contour]
        u = np.array([math.cos(angle), math.sin(angle)])
        if angle <= angles[0]:
            return float(np.dot(contour[0], u)) if angles[0] > 1e-9 else math.hypot(*contour[0])
        if angle >= angles[-1]:
            return math.hypot(*contour[-1])
        for (a0, p0), (a1, p1) in zip(
            zip(angles, contour, strict=True),
            zip(angles[1:], contour[1:], strict=True),
            strict=True,
        ):
            if a0 <= angle <= a1:
                # Ray t·u meets the chord p0 + s (p1 - p0).
                p0v, d = np.array(p0), np.array(p1) - np.array(p0)
                matrix = np.column_stack([u, -d])
                if abs(np.linalg.det(matrix)) < 1e-12:
                    return math.hypot(*p0)
                t, _ = np.linalg.solve(matrix, p0v)
                return float(t)
        return math.hypot(*contour[-1])

    def check(self, pu: float, mux: float, muy: float) -> ColumnCheck:
        """Utilisation of a demand (Pu compression positive [N], Mux, Muy [N·mm])."""
        s = self.section
        mu = math.hypot(mux, muy)
        if pu > s.phi_pn_max:
            return ColumnCheck(pu / s.phi_pn_max, 0.0, mu, "Pu exceeds φPn,max")
        if pu < -s.phi_tension:
            return ColumnCheck(-pu / s.phi_tension, 0.0, mu, "tension exceeds φ fy Ast")
        if mu <= 0:
            axial = pu / s.phi_pn_max if pu >= 0 else -pu / s.phi_tension
            return ColumnCheck(axial, 0.0, 0.0, "axial force only")
        capacity = self.moment_capacity(pu, math.atan2(abs(muy), abs(mux)))
        if capacity <= 0:
            return ColumnCheck(math.inf, 0.0, mu, "no moment capacity at this axial force")
        return ColumnCheck(mu / capacity, capacity, mu, "")


def slenderness(section: RcSection, length: float, k: float = 1.0) -> float:
    """The larger k lu / r of the two section axes, r = 0.3 h (rectangle) or 0.25 D (circle)."""
    p = section.profile
    r = 0.3 * min(p.xDim, p.yDim) if isinstance(p, RectangleProfile) else 0.25 * 2 * p.radius
    return k * length / r

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
  φMny) are computed at neutral-axis angles 7.5° apart at the same ratios of neutral-axis
  depth to the depth of the extreme tension bar (so with the same εt and φ row by row),
  interpolated linearly to 1.875° apart at those ratios, cut at φPn = Pu, and the demand ray
  is intersected with the resulting contour (see :class:`InteractionSurface`). Each meridian
  has 13 points evenly spaced from εt = εty to εty + 0.003, where φ bends the factored diagram
  inwards. On 6 rectangular sections (4 doubly symmetric, 2 not; 2.5° x 60 depths of exact
  concreteproperties points each) the capacity read off the surface was at most 0.3 % above
  the exact one, the largest where the contour runs almost along the demand ray; it was 1.4 %
  with chords between meridians 15° apart cut at Pu. Unsymmetric bar layouts are read with
  signed moments, the least over the four signs of (Mx, My); where the contour at Pu does not
  enclose the origin (tension on unsymmetric bars, whose resultant is off the centroid) the
  capacity is 0.

Units: mm, MPa, N, N·mm. Section coordinates: x along the profile's width (``xDim``), y along
its depth (``yDim``), origin at the centroid, +y the "top" face.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

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

#: Neutral-axis angles of the interaction surface's computed meridians, this far apart.
_STEP = math.radians(7.5)
#: Meridians per computed span, the computed one and those interpolated after it.
_SUBDIVISIONS = 4
#: Neutral-axis depths of a meridian, as a share of the depth of the extreme tension bar.
_DEPTHS = np.concatenate(
    [np.geomspace(1e-3, 0.05, 6), np.linspace(0.07, 1.4, 24), np.geomspace(1.6, 8.0, 6)]
)
#: Extra neutral-axis depths per meridian, evenly spaced in εt over the φ transition.
_TRANSITION_POINTS = 13


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
    aggregate: float | None = None,
) -> RcSection:
    """The section of a member type, with its bars laid out from the reinforcement groups.

    Rectangles: see :func:`_rectangle_bars`. Circles: every group as a ring. ``aggregate``:
    the concrete's largest aggregate size [mm], which sets the least clear spacing of the bars
    of a row with the bar diameter and 25 mm (ACI 25.2.1).
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
        bars, notes = _rectangle_bars(profile, reinforcement, inset, aggregate)
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


def min_clear_spacing(dia: float, aggregate: float | None = None) -> float:
    """Least clear spacing [mm] between parallel bars of a row (ACI 25.2.1): the greater of
    25 mm, the bar diameter and 4/3 of the largest aggregate size."""
    return max(25.0, dia, 4 / 3 * aggregate if aggregate else 0.0)


#: Least clear distance [mm] between two horizontal rows of bars (ACI 25.2.2).
ROW_CLEAR = 25.0


def bars_per_row(width: float, inset: float, dia: float, aggregate: float | None = None) -> int:
    """How many bars of ``dia`` fit in one row across ``width`` inside ``inset`` (the cover
    and the transverse bars) at the least clear spacing (ACI 25.2.1); at least 2."""
    reach = width - 2 * inset - dia  # between the centres of the outer bars
    pitch = dia + min_clear_spacing(dia, aggregate)
    return max(2, math.floor(1 + reach / pitch + 1e-9))


def _rows(
    row: list[float], width: float, inset: float, aggregate: float | None
) -> list[list[float]]:
    """A face's bars in rows, the outer row first: as many as fit at the least clear spacing
    (ACI 25.2.1) in the outer row, its end bars kept and the largest bars in it, the rest in
    further rows."""
    if len(row) <= 2:
        return [row]
    fit = bars_per_row(width, inset, max(row), aggregate)
    if len(row) <= fit:
        return [row]
    middle = sorted(row[1:-1], reverse=True)
    rows = [[row[0], *_arrange(middle[: fit - 2]), row[-1]]]
    rest = middle[fit - 2 :]
    while rest:
        rows.append(_arrange(rest[:fit]))
        rest = rest[fit:]
    return rows


def _rectangle_bars(
    profile: RectangleProfile,
    reinforcement: LinearReinforcement,
    inset: float,
    aggregate: float | None = None,
) -> tuple[list[Bar], list[str]]:
    """The bars of a rectangle, from all its bar groups (several groups may share a position,
    e.g. 3T20 + 2T16 bottom: they form one row, larger bars at the ends).

    ``top`` and ``bottom`` bars lie in one row inside the cover and the transverse bars, each
    bar resting on the stirrup; when they do not fit in one row at the least clear spacing
    (ACI 25.2.1: max(25 mm, db, 4/3 of the aggregate)), the bars left over go into further
    rows inwards, 25 mm clear between the rows (ACI 25.2.2), the outer row keeping its end bars
    and the largest bars. ``sides`` are shared between the two vertical faces, evenly spaced
    between the top and bottom rows. ``perimeter`` bars: the four largest at the corners,
    the rest shared between the faces in proportion to their lengths; ``top``, ``bottom`` and
    ``sides`` groups beside a perimeter group are added between its corner bars on those faces
    (the corners are never counted twice; such faces keep one row).
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
    for name, face_bars, sy in (("top", top, 1), ("bottom", bottom, -1)):
        if not face_bars:
            continue
        rows = [face_bars] if ring else _rows(face_bars, b, inset, aggregate)
        if len(rows) > 1:
            notes.append(
                f"{name} bars in {len(rows)} rows ({' + '.join(str(len(r)) for r in rows)}): "
                f"they do not fit in one row at the least clear spacing (ACI 25.2.1); "
                f"{ROW_CLEAR:g} mm clear between the rows (ACI 25.2.2)"
            )
        edge = h / 2 - inset  # the outer row's bars rest on the stirrup
        for k, row in enumerate(rows):
            reach = [b / 2 - inset - d / 2 for d in row]
            heights = [edge - d / 2 for d in row]
            if min(reach) <= 0 or min(heights) <= 0:
                raise DesignError("the cover leaves no room for the bars")
            xs = [0.0] if len(row) == 1 else list(np.linspace(-reach[0], reach[-1], len(row)))
            bars += [
                Bar(float(x), sy * y, bar_area(d), d)
                for x, y, d in zip(xs, heights, row, strict=True)
            ]
            if k == 0:
                levels[sy] = sy * min(heights)
                gaps = [xs[j + 1] - xs[j] - (row[j] + row[j + 1]) / 2 for j in range(len(row) - 1)]
                clear = min_clear_spacing(max(row), aggregate)
                if gaps and min(gaps) < clear - 1e-6:
                    notes.append(
                        f"{name} row: clear spacing {min(gaps):.0f} mm is below {clear:.0f} mm "
                        "(ACI 25.2.1); the bars are still taken in one row"
                    )
            edge -= max(row) + ROW_CLEAR
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
    # The ultimate actions in closed form (saengine.design.fast_ultimate): the same numbers,
    # tens of times faster than the meshed integration.
    from saengine.design.fast_ultimate import FastConcreteSection

    return FastConcreteSection(geometry, moment_centroid=(0.0, 0.0))


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


def _encloses_origin(polygon: np.ndarray) -> bool:
    """True when the closed polygon (rows x, y) winds around the origin."""
    q = np.roll(polygon, -1, axis=0)
    cross = polygon[:, 0] * q[:, 1] - polygon[:, 1] * q[:, 0]
    return abs(float(np.arctan2(cross, (polygon * q).sum(axis=1)).sum())) > math.pi


class InteractionSurface:
    """The φ-factored P-Mx-My interaction surface of a column section (compression positive).

    Meridians (φPn, φMnx, φMny over the neutral-axis depth) are computed with concreteproperties
    at neutral-axis angles :data:`_STEP` apart: over a quadrant with |Mx|, |My| for a doubly
    symmetric bar layout, over the full turn with signed moments for any other. Every meridian
    is sampled at the same depth ratios k = c / d_t (d_t: depth of the extreme tension bar), so
    the same rows share εt = 0.003 (1/k - 1) and with it φ. Meridians between the computed ones
    are interpolated linearly, row by row: φ is the same along such an interpolation, so the
    inward bends that φ puts into the factored contour at a given Pu are followed rather than
    cut by chords. The contour at Pu joins the cuts of all meridians.
    """

    def __init__(self, section: RcSection, coarse: bool = False) -> None:
        """``coarse``: meridians twice as far apart, fewer depths and 2 interpolated spans
        instead of 4, about four times faster and a little less exact (the design mode's
        search for the bars uses it, then checks its pick on the full surface)."""
        self.section = section
        self.symmetric = section.symmetric
        self._subdivisions = 2 if coarse else _SUBDIVISIONS
        step = 2 * _STEP if coarse else _STEP
        span = math.pi / 2 if self.symmetric else 2 * math.pi
        steps = round(span / step)
        angles = sorted({*(k * span / steps for k in range(steps + 1)), *self._switches(span)})
        angles = [a for k, a in enumerate(angles) if k == 0 or a - angles[k - 1] > 1e-4]
        eps_ty = section.fy / section.es
        # Depth ratios of the φ transition (ACI Table 21.2.2), both ends included: φ bends the
        # factored diagram inwards at εty and at εty + 0.003, and in between it may curve the
        # wrong way, so chords there need closely spaced points.
        points = 5 if coarse else _TRANSITION_POINTS
        transition = EPS_CU / (EPS_CU + eps_ty + EPS_CU * np.linspace(0, 1, points))
        depths = _DEPTHS[::2] if coarse else _DEPTHS
        ratios = np.unique(np.concatenate([depths, transition]))
        computed = angles if self.symmetric else angles[:-1]  # the full turn: 2π is 0
        base = np.array([self._meridian(a, ratios) for a in computed])
        if not self.symmetric:
            base = np.concatenate([base, base[:1]])
        self._meridians = self._interpolate(base)

    def _switches(self, span: float) -> list[float]:
        """Neutral-axis angles in [0, ``span``) at which the extreme tension bar changes: parallel
        to an edge of the bars' convex hull. The meridians kink there, so they are computed."""
        from shapely.geometry import MultiPoint

        hull = MultiPoint([(b.x, b.y) for b in self.section.bars]).convex_hull
        if hull.geom_type != "Polygon":
            return []
        xy = np.asarray(hull.exterior.coords)
        edges = np.diff(xy, axis=0)
        angles = np.arctan2(edges[:, 1], edges[:, 0])
        both = np.concatenate([angles, angles + math.pi]) % (2 * math.pi)
        return [float(a) for a in both if a < span]

    def _interpolate(self, base: np.ndarray) -> np.ndarray:
        """:data:`_SUBDIVISIONS` (coarse: 2) meridians per computed span, linear in the angle row by row
        (the closing meridian of a quadrant kept, of the full turn dropped: it is the first)."""
        s = np.linspace(0, 1, self._subdivisions, endpoint=False)[:, None, None]
        fine = (base[:-1, None] + s * (base[1:, None] - base[:-1, None])).reshape(
            -1, *base.shape[1:]
        )
        return np.concatenate([fine, base[-1:]]) if self.symmetric else fine

    def _meridian(self, angle: float, ratios: np.ndarray) -> np.ndarray:
        """Rows (φPn, φMnx, φMny) [N, N·mm] at the depth ratios, then at infinite depth."""
        from concreteproperties.utils import calculate_extreme_fibre, global_to_local

        section = self.section
        points = section.analysis.compound_geometry.points
        theta = math.atan2(math.sin(angle), math.cos(angle))
        fibre, _ = calculate_extreme_fibre(points=points, theta=theta)
        _, fibre_v = global_to_local(theta=theta, x=fibre[0], y=fibre[1])
        # Depth of the extreme tension bar, the one εt is measured at.
        d_bar = max(fibre_v - global_to_local(theta=theta, x=b.x, y=b.y)[1] for b in section.bars)
        return np.array([self._point(theta, d_n) for d_n in [*(ratios * d_bar), math.inf]])

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
        mx, my = phi * result.m_x, phi * result.m_y
        if self.symmetric:
            mx, my = abs(mx), abs(my)
        return [phi * result.n, mx, my]

    def contour(self, pu: float) -> np.ndarray | None:
        """The closed contour (φMnx, φMny) [N·mm] at axial force ``pu`` [N], anticlockwise, or
        None if some meridian never reaches ``pu``. On each meridian the crossing nearest the
        origin is taken."""
        m = self._meridians
        lo, hi = m[:, :-1, 0] - pu, m[:, 1:, 0] - pu
        hit = (lo == 0) | (lo * hi < 0)
        if not hit.any(axis=1).all():
            return None
        t = np.where(hit, lo / np.where(hit & (lo != hi), lo - hi, 1.0), 0.0)
        points = m[:, :-1, 1:] + t[..., None] * (m[:, 1:, 1:] - m[:, :-1, 1:])
        reach = np.where(hit, np.hypot(points[..., 0], points[..., 1]), np.inf)
        contour = points[np.arange(len(m)), np.argmin(reach, axis=1)]
        if not self.symmetric:
            return contour
        # A quadrant, reflected into the other three (a reflection in one axis reverses it).
        return np.concatenate(
            [contour, contour[::-1] * [-1, 1], contour * [-1, -1], contour[::-1] * [1, -1]]
        )

    def moment_capacity(self, pu: float, angle: float) -> float:
        """φMn [N·mm] at axial force ``pu`` [N] in the direction ``angle`` (rad, 0 … π/2, from
        the x axis) of the moment vector (|Mx|, |My|): the least over the four signs of the
        moments, each the distance from the origin to the nearest crossing of the contour. 0 if
        the axial force is beyond a meridian or the contour does not enclose the origin (e.g.
        tension on unsymmetric bars, whose resultant is off the centroid)."""
        p = self.contour(pu)
        if p is None or not _encloses_origin(p):
            return 0.0
        d = np.roll(p, -1, axis=0) - p
        c, s = math.cos(angle), math.sin(angle)
        signs = ((1, 1),) if self.symmetric else ((1, 1), (-1, 1), (-1, -1), (1, -1))
        least = math.inf
        for sx, sy in signs:
            u = (sx * c, sy * s)
            det = d[:, 0] * u[1] - d[:, 1] * u[0]
            ok = np.abs(det) > 1e-12 * np.maximum(1.0, (d * d).sum(axis=1))
            safe = np.where(ok, det, 1.0)
            t = (p[:, 1] * d[:, 0] - p[:, 0] * d[:, 1]) / safe  # ray t·u = p + r (q - p)
            r = (u[0] * p[:, 1] - u[1] * p[:, 0]) / safe
            ok &= (t >= 0) & (r >= -1e-12) & (r <= 1 + 1e-12)
            if not ok.any():
                return 0.0
            least = min(least, float(t[ok].min()))
        return least

    #: Demands worked out together by :meth:`max_utilisation` (bounds its memory).
    _BLOCK = 256

    def max_utilisation(self, points: Any, stop_above: float | None = None) -> float:
        """The largest :meth:`check` utilisation of many demands (rows Pu, Mux, Muy [N, N·mm]),
        worked out on arrays: the same contours and rays as :meth:`check`, for the design mode's
        bar search, which asks it of thousands of stations and combinations per layout (X2 of
        the usability walk: the proposal took minutes in the per-point loop).

        ``stop_above``: return as soon as some demand exceeds it (a utilisation above it, not
        necessarily the largest): the search only asks whether a layout carries them all. The
        demands with the largest moments go first, so a layout that fails is found quickly."""
        pts = np.asarray(points, dtype=float).reshape(-1, 3)
        if not len(pts):
            return 0.0
        s = self.section
        pu, mu = pts[:, 0], np.hypot(pts[:, 1], pts[:, 2])
        worst = 0.0
        over, tension = pu > s.phi_pn_max, pu < -s.phi_tension
        if over.any():
            worst = max(worst, float(pu[over].max() / s.phi_pn_max))
        if tension.any():
            worst = max(worst, float((-pu[tension]).max() / s.phi_tension))
        inside = ~over & ~tension
        axial = inside & (mu <= 0)
        for p in pts[axial]:  # few: axial force alone (the scalar rules, notes and all)
            worst = max(worst, self.check(*p).utilisation)
        if stop_above is not None and worst > stop_above:
            return worst
        bending = pts[inside & (mu > 0)]
        if stop_above is not None:
            bending = bending[np.argsort(-np.hypot(bending[:, 1], bending[:, 2]))]
        for start in range(0, len(bending), self._BLOCK):
            block = bending[start : start + self._BLOCK]
            caps = self._capacities(
                block[:, 0], np.arctan2(np.abs(block[:, 2]), np.abs(block[:, 1]))
            )
            m = np.hypot(block[:, 1], block[:, 2])
            if (caps <= 0).any():
                return math.inf
            worst = max(worst, float((m / caps).max()))
            if stop_above is not None and worst > stop_above:
                break
        return worst

    def utilisations(self, points: Any) -> np.ndarray:
        """The :meth:`check` utilisation of each demand (rows Pu, Mux, Muy [N, N·mm]), on
        arrays: the design checks ask it of every station and combination of a member (on 10
        storeys, close to a million points), then :meth:`check` the governing one for its
        details."""
        pts = np.asarray(points, dtype=float).reshape(-1, 3)
        out = np.zeros(len(pts))
        if not len(pts):
            return out
        s = self.section
        pu, mu = pts[:, 0], np.hypot(pts[:, 1], pts[:, 2])
        over, tension = pu > s.phi_pn_max, pu < -s.phi_tension
        out[over] = pu[over] / s.phi_pn_max
        out[tension] = -pu[tension] / s.phi_tension
        inside = ~over & ~tension
        for i in np.flatnonzero(inside & (mu <= 0)):  # few: axial force alone (scalar rules)
            out[i] = self.check(*pts[i]).utilisation
        bending = np.flatnonzero(inside & (mu > 0))
        for start in range(0, len(bending), self._BLOCK):
            rows = bending[start : start + self._BLOCK]
            block = pts[rows]
            caps = self._capacities(
                block[:, 0], np.arctan2(np.abs(block[:, 2]), np.abs(block[:, 1]))
            )
            out[rows] = np.where(caps > 0, mu[rows] / np.where(caps > 0, caps, 1.0), math.inf)
        return out

    def _capacities(self, pu: np.ndarray, angle: np.ndarray) -> np.ndarray:
        """:meth:`moment_capacity` of each (``pu``, ``angle``), on arrays."""
        # The contour depends on Pu alone: worked out once per distinct Pu (the stations of a
        # piece and the combinations often share one), the rays per demand.
        values, inverse = np.unique(pu, return_inverse=True)
        p, reaches, encloses = self._contours(values)
        p, reaches, encloses = p[inverse], reaches[inverse], encloses[inverse]
        q = np.roll(p, -1, axis=1)
        d = q - p
        c, s = np.cos(angle)[:, None], np.sin(angle)[:, None]
        signs = ((1, 1),) if self.symmetric else ((1, 1), (-1, 1), (-1, -1), (1, -1))
        least = np.full(len(pu), np.inf)
        found = np.ones(len(pu), dtype=bool)
        scale = 1e-12 * np.maximum(1.0, (d * d).sum(axis=2))
        for sx, sy in signs:
            ux, uy = sx * c, sy * s
            det = d[..., 0] * uy - d[..., 1] * ux
            ok = np.abs(det) > scale
            safe = np.where(ok, det, 1.0)
            t_ray = (p[..., 1] * d[..., 0] - p[..., 0] * d[..., 1]) / safe
            r = (ux * p[..., 1] - uy * p[..., 0]) / safe
            ok &= (t_ray >= 0) & (r >= -1e-12) & (r <= 1 + 1e-12)
            found &= ok.any(axis=1)
            least = np.minimum(least, np.where(ok, t_ray, np.inf).min(axis=1))
        return np.where(reaches & encloses & found, least, 0.0)

    def _contours(self, pu: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """The contours of :meth:`contour` at each ``pu`` (closed polygons, anticlockwise),
        whether every meridian reaches it and whether the contour encloses the origin."""
        m = self._meridians  # (meridians, rows, 3)
        rising = self.__dict__.get("_rising")
        if rising is None:
            rising = self._rising = (np.diff(m[:, :, 0], axis=1) >= 0).all(axis=1)
        rows = m.shape[1]
        p = np.broadcast_to(m[None, :, 0, 1:], (len(pu), m.shape[0], 2)).copy()
        reaches = np.ones(len(pu), dtype=bool)
        for k in range(m.shape[0]):
            if not rising[k]:
                p[:, k], reached = self._cuts(m[k], pu)
                reaches &= reached
                continue
            # φPn never falls along the meridian (as a rule): the row crossing Pu is found by a
            # sorted search, the same cut as below; Pu equal to several rows goes below.
            col = m[k, :, 0]
            a = np.searchsorted(col, pu, "left")
            b = np.searchsorted(col, pu, "right")
            equal = np.minimum(b, rows - 1) - a
            between = (a == b) & (a >= 1) & (a <= rows - 1)
            one = between | (equal == 1)
            many = equal > 1
            reaches &= one | many
            n = np.flatnonzero(one)
            r = np.where(between, a - 1, a)[n]
            lo, hi = col[r] - pu[n], col[r + 1] - pu[n]
            t = lo / np.where(lo != hi, lo - hi, 1.0)
            start, end = m[k, r, 1:], m[k, r + 1, 1:]
            p[n, k] = start + t[:, None] * (end - start)
            if many.any():
                p[many, k], _ = self._cuts(m[k], pu[many])
        if self.symmetric:
            p = np.concatenate(
                [p, p[:, ::-1] * [-1, 1], p * [-1, -1], p[:, ::-1] * [1, -1]], axis=1
            )
        q = np.roll(p, -1, axis=1)
        cross = p[..., 0] * q[..., 1] - p[..., 1] * q[..., 0]
        encloses = np.abs(np.arctan2(cross, (p * q).sum(axis=2)).sum(axis=1)) > math.pi
        return p, reaches, encloses

    @staticmethod
    def _cuts(meridian: np.ndarray, pu: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """The cut of one meridian (rows φPn, φMnx, φMny) at each ``pu`` nearest the origin (the
        first of equals; its first row where it does not reach Pu) and whether it reaches it."""
        lo = meridian[None, :-1, 0] - pu[:, None]
        hi = meridian[None, 1:, 0] - pu[:, None]
        hit = (lo == 0) | (lo * hi < 0)
        n, r = np.nonzero(hit)
        lo_hit, hi_hit = lo[n, r], hi[n, r]
        t = lo_hit / np.where(lo_hit != hi_hit, lo_hit - hi_hit, 1.0)
        a, b = meridian[r, 1:], meridian[r + 1, 1:]
        cuts = a + t[:, None] * (b - a)
        reach = np.hypot(cuts[:, 0], cuts[:, 1])
        order = np.lexsort((r, reach, n))
        _, first = np.unique(n[order], return_index=True)
        chosen = order[first]
        p = np.broadcast_to(meridian[0, 1:], (len(pu), 2)).copy()
        p[n[chosen]] = cuts[chosen]
        return p, hit.any(axis=1)

    def check(self, pu: float, mux: float, muy: float) -> ColumnCheck:
        """Utilisation of a demand (Pu compression positive [N], Mux, Muy [N·mm])."""
        s = self.section
        mu = math.hypot(mux, muy)
        if pu > s.phi_pn_max:
            return ColumnCheck(pu / s.phi_pn_max, 0.0, mu, "Pu exceeds φPn,max")
        if pu < -s.phi_tension:
            return ColumnCheck(-pu / s.phi_tension, 0.0, mu, "tension exceeds φ fy Ast")
        if mu <= 0:
            if not self.symmetric and pu < 0:
                p = self.contour(pu)
                if p is not None and not _encloses_origin(p):
                    note = "axial force only: at the centroid it is outside the surface"
                    return ColumnCheck(math.inf, 0.0, 0.0, note)
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

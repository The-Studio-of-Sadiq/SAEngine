"""Design of reinforced-concrete walls and coupling beams to BNBC 2020 Part 6 (bnbc-2020-part1.pdf).

Pure functions over a wall pier's geometry, its object type's bars and the pier forces at its
cuts (one row per load combination and cut: ``{P, V2, M3, V3, M2}``, see :class:`PierForces`).
They return rows in the design report's check format ``{name, demand, capacity, unit,
utilisation, combination, ok, note, flag}`` (as ``check._check``), notes, and what the design
mode needs (:class:`WallNeed`).

Ordinary walls (Part 6 Chapter 6)
- 6.6.3.2 / 6.6.3.3 (p. 969): ρl >= 0.0012 and ρt >= 0.0020 for deformed bars not larger than
  16 mm with fy not less than 420 MPa, 0.0015 and 0.0025 for other deformed bars.
- 6.6.3.4 (p. 969): walls more than 250 mm thick (not basement walls) in two layers.
- 6.6.3.5 (p. 969): vertical and horizontal bars at most min(3 t, 450 mm) apart.
- 6.6.4 (p. 970): axial force and flexure as a compression member (6.3.2, 6.3.3): the pier's
  section, with its vertical bars distributed along the length in each layer (and the boundary
  bars when the type defines them): :class:`PierInteraction`, the strain compatibility of
  :mod:`saengine.design.rc` written out for the rectangle (it reproduces rc.py's
  concreteproperties analysis to 1e-5 and takes milliseconds where
  :class:`~saengine.design.rc.InteractionSurface` takes 5-20 s for a wall's many bars), with
  biaxial demands on the linear load contour M3/φMn3 + M2/φMn2 <= 1 (conservative); an
  InteractionSurface may be passed for the exact biaxial check.
- 6.6.5 (p. 970): the empirical method, φPn = 0.55 φ f'c Ag [1 - (k lc / 32 h)²] (Eq. 6.6.89),
  φ = 0.65, k = 0.8 / 1.0 / 2.0; only for solid rectangular walls with the resultant within the
  middle third of the thickness: an alternative to 6.6.4, reported as an informative row; and
  6.6.5.3 the least thickness of walls so designed: 1/25 of the shorter of the supported height
  and length, not less than 100 mm (190 mm for exterior basement and foundation walls).
- 6.4.8 (pp. 935-937): in-plane shear. d = 0.8 lw (6.4.8.4); Vc = 0.17 λ √f'c h d in
  compression, 0.17 (1 + 0.29 Nu/Ag) λ √f'c h d >= 0 in tension (6.4.8.5, Eq. 6.6.54), or the
  lesser of Eq. 6.6.68 (0.27 λ √f'c h d + Nu d / 4 lw) and Eq. 6.6.69 ((0.05 λ √f'c + lw (0.1
  λ √f'c + 0.2 Nu / lw h) / (Mu/Vu - lw/2)) h d; not applied when Mu/Vu - lw/2 <= 0) (6.4.8.6):
  the larger of the simplified and the detailed value is used, as either is permitted;
  Vs = Av fy d / s (Eq. 6.6.70), Vn <= 0.83 √f'c h d (6.4.8.3); φ = 0.75 (6.2.3.2.4). Where Vu
  > 0.5 φ Vc (6.4.8.8): ρt >= 0.0025 (6.4.8.9.2), s <= min(lw/5, 3h, 450 mm) (6.4.8.9.3), ρl >=
  max(0.0025, 0.0025 + 0.5 (2.5 - hw/lw)(ρt - 0.0025)) (Eq. 6.6.71) but not more than the ρt
  the shear requires, s <= min(lw/3, 3h, 450 mm) (6.4.8.9.5). √f'c at most 8.3 MPa and fy at
  most 420 MPa in shear, as :func:`saengine.design.rc.shear`.
- 6.4.8.1 (p. 935): out-of-plane shear as a slab (6.4.10 → one-way 6.4.1: φ 0.17 λ √f'c b d per
  metre); out-of-plane bending (M2 per metre of length) as a slab strip of the vertical bars of
  one face (:func:`saengine.design.bars.strip_capacity`, without the axial force, which the P-M
  surface carries): informative beside the surface check.
- Slenderness (6.6.4 → 6.3.10): k lc / r out of the plane (r = 0.3 t) is reported; the moment
  magnification itself is :mod:`saengine.design.slender`'s.

Special structural walls (Sec 8.3.6, pp. 1100-1107), when the seismic scope says 8.3.6 applies
(:func:`special_applies`)
- 8.3.6.2(a): ρl, ρt >= 0.0025, except that where Vu <= 0.083 Acv λ √f'c the values of (i)/(ii)
  (those of 6.6.3) apply; spacing each way <= 450 mm. (b) two curtains where Vu > 0.17 Acv λ
  √f'c.
- 8.3.6.3: Vu from the analysis (BNBC sets no shear amplification for walls).
- 8.3.6.4(a): Vn = Acv (αc λ √f'c + ρt fy) (Eq. 6.8.9), αc = 0.25 for hw/lw <= 1.5, 0.17 for
  hw/lw >= 2.0, linear between; (b) hw/lw the larger of the entire wall's and the segment's;
  (c) ρl >= ρt where hw/lw <= 2.0; (d) Vn <= 0.83 Acw √f'c for one segment (the 0.66 Acv √f'c
  of all segments sharing a lateral force is the integrator's, across walls). φ = 0.60 where Vn
  is less than the shear at the nominal flexural strength (Vu Mn / Mu at Pu), else 0.75
  (6.2.3.3(a), p. 898).
- 8.3.6.5: flexure and axial load by 6.3.2 and 6.3.3 (the same P-M surface); flanges (T, L from
  intersecting walls) are not taken: rectangular piers only.
- 8.3.6.6 boundary elements: (b) for walls continuous from the base to the top with one
  critical section, where c >= lw / (600 (δu/hw)), δu/hw not less than 0.007 (Eq. 6.8.10), c
  the largest neutral-axis depth for the factored axial force and the nominal moment; the
  boundary reinforcement then extends max(lw, Mu / 4 Vu) above the critical section; (c)
  otherwise where the extreme fibre stress Pu/Ag + Mu (lw/2) / I of a combination with E
  exceeds 0.2 f'c (it may stop where it is below 0.15 f'c). (d)(i) length from the extreme
  compression fibre >= max(c - 0.1 lw, c/2); (iii) transverse bars per 8.3.5.4 without Eq.
  6.8.7: Ash >= 0.09 s bc f'c / fyt (Eq. 6.8.8, fyt <= 700 MPa), spacing <= min(least
  dimension of the boundary element / 3, 6 db, so), so = 100 + (350 - hx)/3 within [100, 150]
  mm, hx <= 350 mm (8.3.5.4(c)). (e) where no boundary element is required and the
  longitudinal ratio at the boundary exceeds 2.8 / fy: ties per 8.3.5.4(a)(iii) and (c) at most
  200 mm apart over max(c - 0.1 lw, c/2); (e)(ii) the hooks of the horizontal bars where Vu >=
  0.083 Acv λ √f'c: a note.

Coupling beams (8.3.6.7, p. 1105-1106): ln/h > 4: as flexural members of a special moment frame
(the text refers to "8.3.7" [sic]: the flexural-member provisions are 8.3.4,
:func:`saengine.design.ductile_members.beam_checks`); ln/h < 2 with Vu > 0.33 Acw λ √f'c: two
groups of diagonal bars; between: either. Diagonal bars: Vn = 2 Avd fy sin α <= 0.83 Acw √f'c
(Eq. 6.8.11), φ = 0.85 (6.2.3.3(c)), at least four bars per group (8.3.6.7(d)(ii)), full-section
transverse bars at <= min(150 mm, 6 db) (8.3.6.7(d)(iv)).

Section and bar layout. The pier section is a :class:`~saengine.library.objects.RectangleProfile`
with ``xDim`` = t and ``yDim`` = lw: +y towards the wall's end (the pier's local 2 of
:mod:`saengine.design.wall_forces`, whose M3 > 0 compresses that edge), +x its -3 face (M2 >
0 compresses it); the in-plane moment M3 is the section's Mx, M2 its My. Clear cover
``cover`` is to the horizontal bars, which lie outside the vertical bars; with two layers the vertical bars of each layer sit at ±(t/2 - cover - dh -
dv/2), with one at the middle. Vertical bars run from cover + dh + dv/2 off each end at the
largest equal pitch not above their spacing; boundary bars (when given) replace the web bars
within the boundary length, in two rows along the faces.

Units: mm, MPa, N, N·mm (kN, kN·m, %, mm in the check rows).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from saengine.design.bars import (
    SPACING_STEP,
    Mesh,
    column_min_clear,
    mesh_for,
    round_down,
    strip_capacity,
)
from saengine.design.ductile_members import _row, so_special
from saengine.design.rc import (
    EPS_CU,
    FYT_SHEAR_MAX,
    PHI_SHEAR,
    PHI_TENSION,
    PHI_TIED,
    STEEL_E,
    Bar,
    ColumnCheck,
    DesignError,
    InteractionSurface,
    RcSection,
    bar_area,
    beta1,
    phi_axial_flexure,
)
from saengine.library.objects import RectangleProfile

CLAUSES = {
    "minimum": "BNBC 2020 Part 6 Sec 6.6.3.2, 6.6.3.3 (p. 969)",
    "layers": "BNBC 2020 Part 6 Sec 6.6.3.4 (p. 969)",
    "spacing": "BNBC 2020 Part 6 Sec 6.6.3.5 (p. 969)",
    "compression": "BNBC 2020 Part 6 Sec 6.6.4 (p. 970)",
    "empirical": "BNBC 2020 Part 6 Sec 6.6.5, Eq. 6.6.89 (p. 970)",
    "thickness": "BNBC 2020 Part 6 Sec 6.6.5.3, 6.6.6.1 (p. 970)",
    "shear": "BNBC 2020 Part 6 Sec 6.4.8 (pp. 935-937)",
    "phi": "BNBC 2020 Part 6 Sec 6.2.3.2, 6.2.3.3 (pp. 897-898)",
    "special": "BNBC 2020 Part 6 Sec 8.3.6 (pp. 1100-1107)",
    "boundary": "BNBC 2020 Part 6 Sec 8.3.6.6 (pp. 1102-1105)",
    "coupling": "BNBC 2020 Part 6 Sec 8.3.6.7 (pp. 1105-1106)",
    "confinement": "BNBC 2020 Part 6 Sec 8.3.5.4 (pp. 1097-1098)",
}

#: Least ratios (vertical, horizontal) of 6.6.3.2 / 6.6.3.3 and 8.3.6.2(a)(i)/(ii): bars not
#: larger than 16 mm with fy not less than 420 MPa, and other deformed bars.
RHO_SMALL_BARS = (0.0012, 0.0020)
RHO_OTHER_BARS = (0.0015, 0.0025)
SMALL_BAR_MAX = 16.0
SMALL_BAR_FY = 420.0
#: 6.4.8.9.2, 6.4.8.9.4 and 8.3.6.2(a).
RHO_SHEAR = 0.0025
#: Thickness above which the bars go in two layers (6.6.3.4).
TWO_LAYER_THICKNESS = 250.0
SPACING_MAX = 450.0
#: Shear thresholds of 8.3.6.2: x Acv λ √f'c.
RELAXED_SHARE = 0.083
TWO_CURTAIN_SHARE = 0.17
#: Displacement-based boundary elements: least δu/hw (8.3.6.6(b)(i)).
DRIFT_MIN = 0.007
#: Stress-based boundary elements: required above / may stop below x f'c (8.3.6.6(c)).
STRESS_REQUIRED, STRESS_STOP = 0.2, 0.15
#: φ for shear of members whose Vn is below the shear at Mn (6.2.3.3(a)); diagonally
#: reinforced coupling beams (6.2.3.3(c)).
PHI_SHEAR_SEISMIC = 0.60
PHI_DIAGONAL = 0.85
FYT_CONFINEMENT_MAX = 700.0
HX_MAX = 350.0
#: Least horizontal and vertical wall-bar diameters of the design mode's meshes.
WALL_DIAMETERS = (10.0, 12.0, 16.0, 20.0)
BOUNDARY_DIAMETERS = (16.0, 20.0, 25.0, 32.0)
HOOP_DIAMETERS = (10.0, 12.0)
MIN_WALL_SPACING = 100.0
#: Boundary element lengths are rounded up to this [mm].
LENGTH_STEP = 50.0


# ─────────────────────────────────────── inputs ───────────────────────────────────────


@dataclass(frozen=True)
class WallGeometry:
    """One wall pier: a straight wall between two floors (BIM ``WallElement`` per storey)."""

    length: float  # lw [mm]
    thickness: float  # t (h in Chapter 6) [mm]
    height: float  # hw: overall height of the wall, base to top [mm]
    clear_height: float  # lc: unsupported height of this storey [mm]
    braced: bool = True  # braced top and bottom against lateral translation (6.6.5.2)
    restrained: bool = True  # restrained against rotation at one or both ends (6.6.5.2)
    basement: bool = False  # exterior basement or foundation wall (6.6.3.4, 6.6.5.3.2)
    continuous: bool = True  # base to top with one critical section (8.3.6.6(b))
    segment_ratio: float | None = None  # hw/lw of the segment considered (8.3.6.4(b))

    @property
    def gross_area(self) -> float:
        return self.length * self.thickness

    @property
    def aspect(self) -> float:
        """hw/lw for αc: the larger of the entire wall's and the segment's (8.3.6.4(b))."""
        own = self.height / self.length
        return max(own, self.segment_ratio or 0.0)


@dataclass(frozen=True)
class Boundary:
    """Bars and hoops at each end of a wall (a boundary element), the same at both ends."""

    length: float  # from the wall end [mm]
    count: int  # vertical bars per end, in two rows along the faces
    dia: float
    hoop_dia: float = 10.0
    hoop_spacing: float = 100.0
    legs_across: int = 2  # legs running across the thickness, counted along the length
    legs_along: int = 2  # legs running along the length, counted across the thickness
    # False when the wall type enters end bars but no hoops: hoop_dia then only places the
    # bars (a nominal tie), and no tie or confinement check may count the hoops.
    hoops: bool = True


@dataclass(frozen=True)
class WallBars:
    cover: float  # clear, to the horizontal bars
    vertical_dia: float
    vertical_spacing: float
    horizontal_dia: float
    horizontal_spacing: float
    layers: int = 2
    boundary: Boundary | None = None

    def rho_l(self, t: float) -> float:
        """Distributed vertical (web) ratio ρl."""
        return self.layers * bar_area(self.vertical_dia) / (t * self.vertical_spacing)

    def rho_t(self, t: float) -> float:
        """Distributed horizontal ratio ρt."""
        return self.layers * bar_area(self.horizontal_dia) / (t * self.horizontal_spacing)


def _get(source: Any, name: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def wall_bars(reinforcement: Any) -> WallBars | None:
    """The bars of an ``objects.WallReinforcement`` (or a dict of its fields), None when the
    vertical or horizontal mesh is missing. The optional ``boundary`` field (proposed:
    ``{length, count, dia, hoop: {dia, spacing, legsAcross, legsAlong}}``) is read when
    present."""
    vertical, horizontal = _get(reinforcement, "vertical"), _get(reinforcement, "horizontal")
    if vertical is None or horizontal is None:
        return None
    b = _get(reinforcement, "boundary")
    boundary = None
    if b is not None:
        hoop = _get(b, "hoop")
        boundary = Boundary(
            float(_get(b, "length")),
            int(_get(b, "count")),
            float(_get(b, "dia")),
            float(_get(hoop, "dia", 10.0)),
            float(_get(hoop, "spacing", 100.0)),
            int(_get(hoop, "legsAcross", 2)),
            int(_get(hoop, "legsAlong", 2)),
            hoops=hoop is not None,
        )
    return WallBars(
        float(_get(reinforcement, "cover")),
        float(_get(vertical, "dia")),
        float(_get(vertical, "spacing")),
        float(_get(horizontal, "dia")),
        float(_get(horizontal, "spacing")),
        int(_get(reinforcement, "layers", 2)),
        boundary,
    )


@dataclass(frozen=True)
class PierForces:
    """Factored forces of a pier at one cut for one combination (compression positive).

    P [N], V2 [N] in-plane shear, M3 [N·mm] in-plane moment, V3 [N] out-of-plane shear and M2
    [N·mm] out-of-plane moment, both over the whole length."""

    combination: str | None
    P: float
    V2: float
    M3: float
    V3: float = 0.0
    M2: float = 0.0
    earthquake: bool = True  # the combination includes E (stress-based boundary elements)
    where: str = ""


def pier_forces(
    rows: Iterable[Mapping[str, Any]],
    force: float = 1.0,
    moment: float = 1.0,
    tension_positive: bool = False,
) -> list[PierForces]:
    """:class:`PierForces` from rows ``{P, V2, M3, V3?, M2?, combination?, earthquake?,
    where?}`` (stream F's per-combination pier forces). ``force`` and ``moment`` scale them to
    N and N·mm (e.g. 1e3 and 1e6 from kN and kN·m); ``tension_positive``: P is positive in
    tension in the rows."""
    sign = -1.0 if tension_positive else 1.0
    out = []
    for r in rows:
        out.append(
            PierForces(
                r.get("combination", r.get("name")),
                sign * float(r.get("P", 0.0)) * force,
                float(r.get("V2", 0.0)) * force,
                float(r.get("M3", 0.0)) * moment,
                float(r.get("V3", 0.0)) * force,
                float(r.get("M2", 0.0)) * moment,
                bool(r.get("earthquake", True)),
                str(r.get("where", "")),
            )
        )
    return out


def pier_rows(
    pier: Mapping[str, Any],
    earthquake: Iterable[str] | None = None,
    cuts: Iterable[str] = ("bottom", "middle", "top"),
) -> list[PierForces]:
    """:class:`PierForces` of a pier of :func:`saengine.design.wall_forces.wall_forces`
    (``cuts`` ``{cut: {combination: {P, V2, V3, T, M2, M3}}}`` in kN, kN·m, P compression
    positive, M3 > 0 compressing the wall's end-side edge: the section's +y here).
    ``earthquake``: the names of the combinations that include E; None: all of them (on the safe
    side for the boundary elements)."""
    seismic = None if earthquake is None else set(earthquake)
    out: list[PierForces] = []
    for cut in cuts:
        for name, r in (pier.get("cuts", {}).get(cut) or {}).items():
            out.append(
                PierForces(
                    name,
                    float(r.get("P", 0.0)) * 1e3,
                    float(r.get("V2", 0.0)) * 1e3,
                    float(r.get("M3", 0.0)) * 1e6,
                    float(r.get("V3", 0.0)) * 1e3,
                    float(r.get("M2", 0.0)) * 1e6,
                    True if seismic is None else name in seismic,
                    f"{pier.get('pier', '')} {cut}".strip(),
                )
            )
    return out


def geometry_of(
    pier: Mapping[str, Any], wall_height: float | None = None, **options: Any
) -> WallGeometry:
    """The :class:`WallGeometry` of a pier of ``wall_forces`` (``lw``, ``tw``, ``bottom``,
    ``top`` in mm): lc its storey height; hw ``wall_height`` (the wall's overall height, base
    to top: the stack of its storeys), the storey's when not given. ``options``: the other
    fields (braced, restrained, basement, continuous, segment_ratio)."""
    lc = float(pier["top"]) - float(pier["bottom"])
    return WallGeometry(
        float(pier["lw"]), float(pier["tw"]), float(wall_height or lc), lc, **options
    )


# ─────────────────────────────────────── section ───────────────────────────────────────


def _positions(start: float, end: float, spacing: float) -> list[float]:
    """Bars from ``start`` to ``end`` at the largest equal pitch not above ``spacing``."""
    if end < start - 1e-9:
        return []
    if end - start < 1e-9:
        return [start]
    n = math.ceil((end - start) / spacing - 1e-9)
    return [start + (end - start) * k / n for k in range(n + 1)]


def pier_section(
    geometry: WallGeometry, bars: WallBars, fc: float, fy: float, es: float = STEEL_E
) -> RcSection:
    """The pier's :class:`RcSection` (see the module notes on the layout)."""
    t, lw = geometry.thickness, geometry.length
    dv, dh = bars.vertical_dia, bars.horizontal_dia
    face = t / 2 - bars.cover - dh - dv / 2
    if face <= 0 and bars.layers == 2:
        raise DesignError("the cover leaves no room for two layers of bars")
    xs = [-face, face] if bars.layers == 2 else [0.0]
    end = lw / 2 - bars.cover - dh - dv / 2
    out: list[Bar] = []
    b = bars.boundary
    if b is None:
        web = _positions(-end, end, bars.vertical_spacing)
    else:
        if 2 * b.length >= lw:
            raise DesignError("the boundary elements overlap: their length is lw / 2 or more")
        rows = max(1, math.ceil(b.count / 2))
        bx = t / 2 - bars.cover - b.hoop_dia - b.dia / 2
        outer = lw / 2 - bars.cover - b.hoop_dia - b.dia / 2
        inner = lw / 2 - b.length + b.hoop_dia + b.dia / 2
        if bx <= 0 or inner > outer + 1e-9:
            raise DesignError("the boundary element is too small for its bars")
        ys = [outer - (outer - inner) * k / max(rows - 1, 1) for k in range(rows)]
        for sign in (1, -1):
            left = b.count
            for y in ys:
                pair = (-bx, bx) if left >= 2 else (0.0,)
                for x in pair:
                    out.append(Bar(x, sign * y, bar_area(b.dia), b.dia))
                    left -= 1
        # Web bars strictly between the boundary elements, at a pitch not above the spacing.
        span = lw - 2 * b.length
        n = math.ceil(span / bars.vertical_spacing - 1e-9)
        web = [-span / 2 + span * k / n for k in range(1, n)]
    for y in web:
        for x in xs:
            out.append(Bar(x, y, bar_area(dv), dv))
    if not out:
        raise DesignError("no vertical bars in the wall")
    return RcSection(
        profile=RectangleProfile(xDim=t, yDim=lw),
        bars=tuple(out),
        fc=fc,
        fy=fy,
        es=es,
        transverse_dia=dh,
    )


#: Neutral-axis depths of a uniaxial diagram, as a share of the depth of the extreme bar.
_DEPTHS = np.unique(
    np.concatenate(
        [np.geomspace(1e-3, 0.05, 8), np.linspace(0.05, 1.5, 120), np.geomspace(1.5, 20.0, 24)]
    )
)


class PierInteraction:
    """Uniaxial P-M diagrams of a rectangular pier section, by strain compatibility.

    The same assumptions as :mod:`saengine.design.rc` (ACI 22.2: εcu = 0.003, the rectangular
    stress block 0.85 f'c over β1 c, elastic-perfectly plastic bars displacing the concrete
    they occupy; φ from εt of the extreme tension bar, φPn <= 0.80 φ P0), written out for the
    rectangle: the stress block of a rectangle bent about one axis is a rectangle, so the
    diagram is exact and fast (a wall's 30-100 bars make
    :class:`~saengine.design.rc.InteractionSurface` take 5-20 s per section). In-plane (M3,
    about the section's x, depth lw along y) and out-of-plane (M2, about y, depth t along x),
    each for both senses. Biaxial demands are checked on the linear load contour M3/φMn3 +
    M2/φMn2 <= 1 at Pu, which lies inside the true contour (it is convex): conservative; pass
    an InteractionSurface to :func:`wall_checks` for the exact biaxial check."""

    def __init__(self, section: RcSection) -> None:
        if not isinstance(section.profile, RectangleProfile):
            raise DesignError("wall piers are rectangular")
        self.section = section
        self._diagrams: dict[tuple[str, int], tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        for axis in ("M3", "M2"):
            for sense in (1, -1):
                self._diagrams[(axis, sense)] = self._diagram(axis, sense)

    def _geometry(self, axis: str, sense: int) -> tuple[float, float, np.ndarray, np.ndarray]:
        """(depth, width, bar distances from the compression fibre, bar areas)."""
        s = self.section
        p = s.profile
        coord = np.array([b.y if axis == "M3" else b.x for b in s.bars])
        depth = p.yDim if axis == "M3" else p.xDim
        width = p.xDim if axis == "M3" else p.yDim
        dist = depth / 2 - sense * coord
        return depth, width, dist, np.array([b.area for b in s.bars])

    def actions(self, axis: str, sense: int, c: np.ndarray | float) -> tuple[Any, Any, Any]:
        """Nominal (Pn [N], Mn [N·mm] about the centroid, εt) at neutral-axis depths ``c``."""
        s = self.section
        depth, width, dist, area = self._geometry(axis, sense)
        c = np.atleast_1d(np.asarray(c, dtype=float))[:, None]
        a = np.minimum(beta1(s.fc) * c, depth)
        strain = EPS_CU * (c - dist[None, :]) / c
        stress = np.clip(s.es * strain, -s.fy, s.fy)
        stress = stress - np.where(dist[None, :] < a, 0.85 * s.fc, 0.0)
        force = stress * area[None, :]
        conc = 0.85 * s.fc * width * a[:, 0]
        pn = conc + force.sum(axis=1)
        mn = conc * (depth / 2 - a[:, 0] / 2) + (force * (depth / 2 - dist[None, :])).sum(axis=1)
        eps_t = EPS_CU * (dist.max() - c[:, 0]) / c[:, 0]
        return pn, mn, eps_t

    def _diagram(self, axis: str, sense: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Factored (φPn, φMn) and c, from pure tension to φPn,max, ordered by c."""
        s = self.section
        _, _, dist, _ = self._geometry(axis, sense)
        eps_ty = s.fy / s.es
        dt = float(dist.max())
        transition = EPS_CU / (EPS_CU + eps_ty + EPS_CU * np.linspace(0, 1, 13))
        c = dt * np.unique(np.concatenate([_DEPTHS, transition]))
        pn, mn, eps_t = self.actions(axis, sense, c)
        phi = np.array([phi_axial_flexure(e, s.fy, s.es, s.spiral) for e in eps_t])
        ppn, pmn = phi * pn, phi * mn
        cap = s.phi_pn_max
        # Cut at φPn,max: the moment where the diagram crosses it, then the plateau ends.
        keep = ppn <= cap
        if not keep.all():
            k = int(np.argmax(~keep))
            if k > 0:
                t = (cap - ppn[k - 1]) / (ppn[k] - ppn[k - 1])
                m_cut = pmn[k - 1] + t * (pmn[k] - pmn[k - 1])
                c_cut = c[k - 1] + t * (c[k] - c[k - 1])
                ppn = np.concatenate([ppn[:k], [cap]])
                pmn = np.concatenate([pmn[:k], [m_cut]])
                c = np.concatenate([c[:k], [c_cut]])
        tension = -PHI_TENSION * s.fy * s.steel_area
        return (
            np.concatenate([[tension], ppn]),
            np.concatenate([[0.0], pmn]),
            np.concatenate([[0.0], c]),
        )

    def capacity(self, pu: float, axis: str, sense: int = 1) -> float:
        """φMn [N·mm] at ``pu`` [N] about ``axis`` ("M3" or "M2"), compression on the +side
        (``sense`` 1) or the -side; 0 outside the axial range."""
        p, m, _ = self._diagrams[(axis, sense)]
        if pu > p[-1] or pu < p[0]:
            return 0.0
        k = int(np.searchsorted(p, pu)) if np.all(np.diff(p) >= 0) else _first_crossing(p, pu)
        k = max(1, min(k, len(p) - 1))
        t = (pu - p[k - 1]) / (p[k] - p[k - 1]) if p[k] != p[k - 1] else 0.0
        return max(0.0, float(m[k - 1] + t * (m[k] - m[k - 1])))

    def nominal(self, pu: float, axis: str = "M3", sense: int = 1) -> tuple[float, float]:
        """Nominal Mn [N·mm] and c [mm] at the factored axial force ``pu`` [N] (Pn = Pu), by
        bisection on c; (0, 0) when Pu is outside the nominal range."""
        s = self.section
        _, _, dist, _ = self._geometry(axis, sense)
        lo, hi = 1e-6 * float(dist.max()), 50.0 * float(dist.max())
        p_lo = float(self.actions(axis, sense, lo)[0][0])
        p_hi = float(self.actions(axis, sense, hi)[0][0])
        if not p_lo <= pu <= p_hi:
            return 0.0, 0.0
        for _ in range(80):
            mid = (lo + hi) / 2
            if float(self.actions(axis, sense, mid)[0][0]) < pu:
                lo = mid
            else:
                hi = mid
        c = (lo + hi) / 2
        del s
        return abs(float(self.actions(axis, sense, c)[1][0])), c

    def check(self, pu: float, m3: float, m2: float) -> ColumnCheck:
        """Utilisation of (Pu, M3, M2) on the linear load contour (see the class notes)."""
        s = self.section
        mu = math.hypot(m3, m2)
        if pu > s.phi_pn_max:
            return ColumnCheck(pu / s.phi_pn_max, 0.0, mu, "Pu exceeds φPn,max")
        if pu < -s.phi_tension:
            return ColumnCheck(-pu / s.phi_tension, 0.0, mu, "tension exceeds φ fy Ast")
        if mu <= 0:
            axial = pu / s.phi_pn_max if pu >= 0 else -pu / s.phi_tension
            return ColumnCheck(axial, 0.0, 0.0, "axial force only")
        c3 = self.capacity(pu, "M3", 1 if m3 >= 0 else -1)
        c2 = self.capacity(pu, "M2", 1 if m2 >= 0 else -1)
        parts = []
        for m, cap in ((m3, c3), (m2, c2)):
            if abs(m) > 0:
                parts.append(abs(m) / cap if cap > 0 else math.inf)
        u = sum(parts)
        # The capacity along the demand's direction on the linear contour.
        cap = mu / u if u > 0 and math.isfinite(u) else 0.0
        note = "" if abs(m2) <= 0 or abs(m3) <= 0 else "biaxial: M3/φMn3 + M2/φMn2"
        return ColumnCheck(u, cap, mu, note)


def _first_crossing(p: np.ndarray, pu: float) -> int:
    hit = np.nonzero((p[:-1] - pu) * (p[1:] - pu) <= 0)[0]
    return int(hit[0]) + 1 if len(hit) else len(p) - 1


def nominal_bending(section: RcSection, pu: float, top: bool) -> tuple[float, float]:
    """In-plane nominal moment Mn [N·mm] and neutral-axis depth c [mm] at the axial force
    ``pu`` [N, compression positive], compression at the +y end (``top``) or the -y end.
    (0, 0) when the section cannot carry ``pu``."""
    return PierInteraction(section).nominal(pu, "M3", 1 if top else -1)


# ─────────────────────────────────────── rules ───────────────────────────────────────


def minimum_ratios(dia_vertical: float, dia_horizontal: float, fy: float) -> tuple[float, float]:
    """Least ρl and ρt of 6.6.3.2 / 6.6.3.3 (and 8.3.6.2(a)(i)/(ii)) by bar size and grade."""

    def small(dia: float) -> bool:
        return dia <= SMALL_BAR_MAX and fy >= SMALL_BAR_FY

    return (
        RHO_SMALL_BARS[0] if small(dia_vertical) else RHO_OTHER_BARS[0],
        RHO_SMALL_BARS[1] if small(dia_horizontal) else RHO_OTHER_BARS[1],
    )


def alpha_c(aspect: float) -> float:
    """αc of Eq. 6.8.9 for hw/lw (8.3.6.4(a))."""
    if aspect <= 1.5:
        return 0.25
    if aspect >= 2.0:
        return 0.17
    return 0.25 - 0.08 * (aspect - 1.5) / 0.5


def _root(fc: float) -> float:
    return min(math.sqrt(fc), 8.3)


def wall_vc(
    geometry: WallGeometry, f: PierForces, fc: float, lam: float = 1.0
) -> tuple[float, str]:
    """Vc [N] of a wall in in-plane shear (6.4.8.5, 6.4.8.6) and how it was found."""
    h, lw = geometry.thickness, geometry.length
    d = 0.8 * lw
    ag = geometry.gross_area
    root = _root(fc)
    nu = f.P
    if nu >= 0:
        simple = 0.17 * lam * root * h * d
        how = "0.17 λ √f'c h d"
    else:
        simple = max(0.0, 0.17 * (1 + 0.29 * nu / ag) * lam * root * h * d)
        how = "0.17 (1 + 0.29 Nu/Ag) λ √f'c h d (Eq. 6.6.54)"
    e68 = 0.27 * lam * root * h * d + nu * d / (4 * lw)
    detailed = e68
    vu, mu = abs(f.V2), abs(f.M3)
    if vu > 0 and mu / vu - lw / 2 > 0:
        e69 = (
            (0.05 * lam * root + lw * (0.1 * lam * root + 0.2 * nu / (lw * h)) / (mu / vu - lw / 2))
            * h
            * d
        )
        detailed = min(e68, e69)
    detailed = max(detailed, 0.0)
    if detailed > simple:
        return detailed, "Eq. 6.6.68 / 6.6.69"
    return simple, how


def wall_vn(
    geometry: WallGeometry, bars: WallBars, f: PierForces, fc: float, fy: float, lam: float = 1.0
) -> dict[str, float | str]:
    """Nominal in-plane shear strength of an ordinary wall (6.4.8): {vc, vs, vn, vmax, how}."""
    h, d = geometry.thickness, 0.8 * geometry.length
    vc, how = wall_vc(geometry, f, fc, lam)
    av = bars.layers * bar_area(bars.horizontal_dia)
    vs = av * min(fy, FYT_SHEAR_MAX) * d / bars.horizontal_spacing
    vmax = 0.83 * math.sqrt(fc) * h * d
    return {"vc": vc, "vs": vs, "vn": min(vc + vs, vmax), "vmax": vmax, "how": how}


def special_vn(
    geometry: WallGeometry, rho_t: float, fc: float, fy: float, lam: float = 1.0
) -> dict[str, float]:
    """Vn of a special structural wall (Eq. 6.8.9) and its limit 0.83 Acw √f'c (8.3.6.4(d))."""
    acv = geometry.gross_area
    a = alpha_c(geometry.aspect)
    vn = acv * (a * lam * math.sqrt(fc) + rho_t * min(fy, FYT_SHEAR_MAX))
    vmax = 0.83 * acv * math.sqrt(fc)
    return {"alpha": a, "vn": min(vn, vmax), "raw": vn, "vmax": vmax}


def special_applies(scope: Mapping[str, Any] | None, structural: bool = True) -> bool:
    """True when the seismic scope (:func:`seismic_rules.seismic_detailing_scope`) puts 8.3.6 in
    force for a structural wall."""
    if not scope or not structural:
        return False
    entry = (scope.get("applies") or {}).get("8.3.6") or {}
    return bool(entry.get("applies"))


def boundary_length(c: float, lw: float) -> float:
    """Least horizontal length of a boundary element from the extreme compression fibre:
    max(c - 0.1 lw, c/2) (8.3.6.6(d)(i))."""
    return max(c - 0.1 * lw, c / 2)


def displacement_trigger(lw: float, drift: float) -> float:
    """The neutral-axis depth at and above which boundary elements are required (Eq. 6.8.10):
    lw / (600 max(δu/hw, 0.007))."""
    return lw / (600 * max(drift, DRIFT_MIN))


def extreme_stress(geometry: WallGeometry, pu: float, mu: float) -> float:
    """Pu/Ag + |Mu| (lw/2) / I [MPa], gross section, linear elastic (8.3.6.6(c))."""
    t, lw = geometry.thickness, geometry.length
    return pu / (t * lw) + abs(mu) * (lw / 2) / (t * lw**3 / 12)


def boundary_ash(bc: float, fc: float, fyt: float) -> float:
    """Least Ash / s [mm²/mm] across a core dimension bc: Eq. 6.8.8 (8.3.6.6(d)(iii) waives
    Eq. 6.8.7), fyt at most 700 MPa (8.3.3.4(c))."""
    return 0.09 * bc * fc / min(fyt, FYT_CONFINEMENT_MAX)


# ─────────────────────────────────────── results ───────────────────────────────────────


@dataclass(frozen=True)
class BoundaryNeed:
    required: bool
    method: str  # "displacement" | "stress"
    c: float  # largest neutral-axis depth [mm]
    length: float  # from the wall end, rounded up to 50 mm [mm] (0 when not required)
    height: float | None  # above the critical section (displacement method) [mm]
    ash_s: tuple[float, float] | None  # bc along the length, across the thickness [mm²/mm]
    spacing: float | None  # largest hoop spacing [mm]
    stress: float = 0.0  # largest extreme fibre stress [MPa]
    ties: bool = False  # 8.3.6.6(e)(i): ties at the ends though no boundary element
    ties_spacing: float | None = None
    proposal: Boundary | None = None
    least_length: float = 0.0  # max(c - 0.1 lw, c/2) [mm], not rounded
    trigger: float | None = None  # lw / (600 max(δu/hw, 0.007)) [mm] (displacement method)


@dataclass(frozen=True)
class WallNeed:
    """What the design mode works from (for proposal.py)."""

    special: bool
    layers: int
    rho_l: float
    rho_t: float
    vertical_s_max: float
    horizontal_s_max: float
    vertical: Mesh | None  # proposal per face (mm²/m of one layer)
    horizontal: Mesh | None
    boundary: BoundaryNeed | None = None
    end_bars: Boundary | None = None  # bars the P-M checks need at the ends (None: web only)
    notes: tuple[str, ...] = ()


@dataclass
class WallDesign:
    checks: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    need: WallNeed | None = None
    utilisation: float = 0.0


def _kn(v: float) -> float:
    return v / 1e3


def _knm(v: float) -> float:
    return v / 1e6


def _largest(forces: list[PierForces], key) -> PierForces | None:
    return max(forces, key=key, default=None)


# ─────────────────────────────────────── the checks ───────────────────────────────────────


def wall_checks(
    geometry: WallGeometry,
    bars: WallBars,
    forces: list[PierForces],
    fc: float,
    fy: float,
    es: float = STEEL_E,
    *,
    lam: float = 1.0,
    special: bool = False,
    drift: float | None = None,
    surface: InteractionSurface | PierInteraction | None = None,
    fyt: float | None = None,
) -> WallDesign:
    """All checks of a wall pier (ordinary, and 8.3.6 when ``special``).

    ``drift``: δu/hw of the wall (the design displacement at its top over its height, BNBC
    2.5.9 Cd δe / I) for the displacement-based boundary elements; None: the stress-based method
    (8.3.6.6(c)). ``surface``: the pier section's interaction surface when the caller caches it
    per type and length. ``fyt``: the hoops' yield strength (default ``fy``)."""
    out = WallDesign()
    t, lw = geometry.thickness, geometry.length
    acv = geometry.gross_area
    fyt = fy if fyt is None else fyt
    rho_l, rho_t = bars.rho_l(t), bars.rho_t(t)
    section = pier_section(geometry, bars, fc, fy, es)
    pier = PierInteraction(section)
    surface = surface or pier
    vu_case = _largest(forces, lambda f: abs(f.V2))
    vu = abs(vu_case.V2) if vu_case else 0.0
    vu_name = vu_case.combination if vu_case else None
    root = math.sqrt(fc)

    # Minimum distributed reinforcement.
    min_l, min_t = minimum_ratios(bars.vertical_dia, bars.horizontal_dia, fy)
    rule = "6.6.3.2 / 6.6.3.3"
    shear_reinforced = _shear_reinforced(geometry, forces, fc, lam)  # 6.4.8.8
    req_l, req_t = min_l, min_t
    if special:
        if vu > RELAXED_SHARE * acv * lam * root:
            req_l = req_t = RHO_SHEAR
            rule = "8.3.6.2(a)"
        else:
            rule = "8.3.6.2(a)(i)/(ii): Vu <= 0.083 Acv λ √f'c"
    elif shear_reinforced:
        req_t = max(req_t, RHO_SHEAR)
        t_need = _rho_t_shear(geometry, forces, fc, fy, lam)
        req_l = max(req_l, rho_l_eq71(geometry, rho_t, t_need))
        rule = "6.4.8.9.2 / 6.4.8.9.4 (Vu > 0.5 φVc, 6.4.8.8)"
    out.checks.append(
        _row(
            f"Vertical web ratio ρl ({rule})",
            100 * req_l,
            100 * rho_l,
            "%",
            note=f"{bars.layers} x Ø{bars.vertical_dia:g} @ {bars.vertical_spacing:g}",
        )
    )
    out.checks.append(
        _row(
            f"Horizontal web ratio ρt ({rule})",
            100 * req_t,
            100 * rho_t,
            "%",
            note=f"{bars.layers} x Ø{bars.horizontal_dia:g} @ {bars.horizontal_spacing:g}",
        )
    )
    if special and geometry.aspect <= 2.0:
        out.checks.append(
            _row(
                "ρl >= ρt where hw/lw <= 2.0 (8.3.6.4(c))",
                100 * rho_t,
                100 * rho_l,
                "%",
                note=f"hw/lw = {geometry.aspect:.2f}",
            )
        )

    # Spacing.
    s_v, s_h = min(3 * t, SPACING_MAX), min(3 * t, SPACING_MAX)
    why_v = why_h = "min(3t, 450 mm) (6.6.3.5)"
    if shear_reinforced and not special:
        s_h, why_h = min(lw / 5, 3 * t, SPACING_MAX), "min(lw/5, 3h, 450 mm) (6.4.8.9.3)"
        s_v, why_v = min(lw / 3, 3 * t, SPACING_MAX), "min(lw/3, 3h, 450 mm) (6.4.8.9.5)"
    if special:
        why_v = why_h = "450 mm (8.3.6.2(a)) and min(3t, 450 mm) (6.6.3.5)"
    out.checks.append(_row(f"Vertical bar spacing, {why_v}", bars.vertical_spacing, s_v, "mm"))
    out.checks.append(_row(f"Horizontal bar spacing, {why_h}", bars.horizontal_spacing, s_h, "mm"))

    # Layers.
    if t > TWO_LAYER_THICKNESS and not geometry.basement:
        out.checks.append(
            _row("Two layers in walls thicker than 250 mm (6.6.3.4)", 2, bars.layers, "layers")
        )
    if special:
        need2 = vu > TWO_CURTAIN_SHARE * acv * lam * root
        out.checks.append(
            _row(
                "Two curtains where Vu > 0.17 Acv λ √f'c (8.3.6.2(b))",
                2 if need2 else 1,
                bars.layers,
                "curtains",
                vu_name,
                f"Vu = {_kn(vu):.1f} kN, 0.17 Acv λ √f'c = "
                f"{_kn(TWO_CURTAIN_SHARE * acv * lam * root):.1f} kN",
            )
        )

    # Axial force and flexure on the P-M3-M2 surface (6.6.4, 8.3.6.5).
    worst = None
    for f in forces:
        r = surface.check(f.P, f.M3, f.M2)
        if worst is None or r.utilisation > worst[0].utilisation:
            worst = (r, f)
    if worst is not None:
        r, f = worst
        out.checks.append(
            _row(
                "Axial force and bending P-M3-M2 (6.6.4" + (", 8.3.6.5)" if special else ")"),
                _knm(r.mu),
                _knm(r.phi_mn),
                "kN·m",
                f.combination,
                f"Pu = {_kn(f.P):.1f} kN, M3 = {_knm(f.M3):.1f}, M2 = {_knm(f.M2):.1f} kN·m"
                + (f" at {f.where}" if f.where else "")
                + (f"; {r.note}" if r.note else ""),
                utilisation=r.utilisation,
            )
        )

    # In-plane shear.
    phi_v = PHI_SHEAR
    if vu_case is not None:
        if special:
            sv = special_vn(geometry, rho_t, fc, fy, lam)
            vn = sv["vn"]
            # 6.2.3.3(a): φ is the member's, over the most critical combinations: 0.60 when Vn
            # is below the shear at the nominal moment Vu Mn/Mu of any of them (a moment of 0
            # never develops Mn: that shear is unbounded).
            v_at_mn, phi_case = 0.0, None
            for g in [g for g in forces if g.earthquake] or list(forces):
                if abs(g.V2) <= 0:
                    continue
                mu = abs(g.M3)
                if mu > 0:
                    mn, _ = pier.nominal(g.P, "M3", 1 if g.M3 >= 0 else -1)
                    v = abs(g.V2) * mn / mu
                else:
                    v = math.inf
                if phi_case is None or v > v_at_mn:
                    v_at_mn, phi_case = v, g
            if phi_case is not None and vn < v_at_mn:
                phi_v = PHI_SHEAR_SEISMIC
            shown = f"{_kn(v_at_mn):.1f} kN" if math.isfinite(v_at_mn) else "∞"
            note = (
                f"Vn = Acv (αc λ √f'c + ρt fy), αc = {sv['alpha']:.3f} (hw/lw = "
                f"{geometry.aspect:.2f}), <= 0.83 Acw √f'c = {_kn(sv['vmax']):.1f} kN; φ = "
                f"{phi_v:.2f} for the wall (6.2.3.3(a): Vn "
                f"{'<' if phi_v < PHI_SHEAR else '>='} the largest Vu Mn/Mu = {shown}"
                + (f", {phi_case.combination})" if phi_case is not None else ")")
            )
            name = "In-plane shear (8.3.6.4, Eq. 6.8.9)"
        else:
            sv = wall_vn(geometry, bars, vu_case, fc, fy, lam)
            vn = float(sv["vn"])
            note = (
                f"Vc = {_kn(float(sv['vc'])):.1f} kN ({sv['how']}), Vs = Av fy d/s = "
                f"{_kn(float(sv['vs'])):.1f} kN, d = 0.8 lw; Vn <= 0.83 √f'c h d = "
                f"{_kn(float(sv['vmax'])):.1f} kN"
            )
            name = "In-plane shear (6.4.8)"
        # Every combination against its own Vn: the ordinary Vc depends on Nu, Mu.
        best = (vu / (phi_v * vn) if vn > 0 else math.inf, vu_case, vn)
        if not special:
            for f in forces:
                v = float(wall_vn(geometry, bars, f, fc, fy, lam)["vn"])
                u = abs(f.V2) / (PHI_SHEAR * v) if v > 0 else math.inf
                if u > best[0]:
                    best = (u, f, v)
        u, f, vn = best
        out.checks.append(
            _row(name, _kn(abs(f.V2)), _kn(phi_v * vn), "kN", f.combination, note, utilisation=u)
        )

    # Out-of-plane: slab strip and slab shear (6.4.8.1), slenderness.
    m2_case = _largest(forces, lambda f: abs(f.M2))
    if m2_case is not None and abs(m2_case.M2) > 0:
        if bars.layers == 2:
            d = t - bars.cover - bars.horizontal_dia - bars.vertical_dia / 2
        else:
            d = t / 2
        area = bar_area(bars.vertical_dia) * 1000 / bars.vertical_spacing
        cap = strip_capacity(area, d, fc, fy, es)
        mu = abs(m2_case.M2) / lw * 1000
        out.checks.append(
            _row(
                "Out-of-plane bending per metre, as a slab strip (6.4.8.1)",
                mu / 1e6,
                cap / 1e6,
                "kN·m/m",
                m2_case.combination,
                f"one face Ø{bars.vertical_dia:g} @ {bars.vertical_spacing:g}, d = {d:.0f} mm, "
                "axial force not counted (the P-M surface carries it)",
            )
        )
        out.checks[-1]["flag"] = True
    v3_case = _largest(forces, lambda f: abs(f.V3))
    if v3_case is not None and abs(v3_case.V3) > 0:
        d = (
            t - bars.cover - bars.horizontal_dia - bars.vertical_dia / 2
            if bars.layers == 2
            else t / 2
        )
        cap = PHI_SHEAR * 0.17 * lam * _root(fc) * 1000 * d
        q = abs(v3_case.V3) / lw * 1000
        out.checks.append(
            _row(
                "Out-of-plane shear per metre, as a slab (6.4.8.1, 6.4.10.1.1)",
                q / 1e3,
                cap / 1e3,
                "kN/m",
                v3_case.combination,
                f"φ 0.17 λ √f'c b d, d = {d:.0f} mm",
            )
        )
    k = _k_factor(geometry)
    klr = k * geometry.clear_height / (0.3 * t)
    out.notes.append(
        f"out-of-plane slenderness k lc / r = {k:g} x {geometry.clear_height:.0f} / (0.3 x "
        f"{t:.0f}) = {klr:.1f}: moment magnification by Sec 6.3.10 (6.6.4)"
        + (" may be neglected" if klr <= 22 else " applies")
    )

    # Empirical method (informative alternative to 6.6.4) and its least thickness.
    p_case = _largest(forces, lambda f: f.P)
    if p_case is not None and p_case.P > 0:
        middle = all(f.P > 0 and abs(f.M2) / f.P <= t / 6 for f in forces)
        if middle:
            phi_pn = empirical_capacity(geometry, fc)
            out.checks.append(
                _row(
                    "Empirical method φPn = 0.55 φ f'c Ag [1 - (k lc/32h)²] (6.6.5.2, informative)",
                    _kn(p_case.P),
                    _kn(phi_pn),
                    "kN",
                    p_case.combination,
                    f"k = {k:g}; resultant within the middle third of the thickness; the "
                    "in-plane moment is not part of this method: 6.6.4 governs",
                )
            )
            out.checks[-1]["flag"] = True
            least = 190.0 if geometry.basement else max(100.0, min(geometry.clear_height, lw) / 25)
            out.checks.append(
                _row(
                    "Least thickness, empirical method (6.6.5.3)",
                    least,
                    t,
                    "mm",
                    note="1/25 of the shorter of the supported height and length, >= 100 mm",
                )
            )
            out.checks[-1]["flag"] = True
    out.checks.append(_row("Least thickness (6.6.5.3.1, 6.6.6.1)", 100.0, t, "mm"))

    # Boundary elements (8.3.6.6).
    boundary = None
    if special:
        boundary = boundary_need(geometry, section, forces, fc, fyt, bars, drift, pier)
        out.checks += _boundary_rows(boundary, bars, geometry, fc)
        if drift is None:
            out.notes.append(
                "δu/hw not given: boundary elements by the stress method of 8.3.6.6(c)"
            )
        if vu >= RELAXED_SHARE * acv * lam * root and not boundary.required:
            out.notes.append(
                "8.3.6.6(e)(ii): the horizontal bars ending at the wall edges need a standard "
                "hook engaging the edge bars, or U-stirrups of the same size and spacing "
                "spliced to them"
            )
        out.notes.append(
            "8.3.6.6(d)(v): horizontal web bars to within 150 mm of the wall end, developed "
            "in the confined core"
        )
    out.need = wall_need(
        geometry,
        forces,
        fc,
        fy,
        es,
        lam=lam,
        special=special,
        drift=drift,
        fyt=fyt,
        bars=bars,
        boundary=boundary,
    )
    strength = [c for c in out.checks if not c["flag"]]
    out.utilisation = max((c["utilisation"] for c in strength), default=0.0)
    return out


def _shear_reinforced(
    geometry: WallGeometry, forces: list[PierForces], fc: float, lam: float
) -> bool:
    """Some combination has Vu > 0.5 φ Vc (6.4.8.8): the shear reinforcement rules of 6.4.8.9
    then apply instead of the minimums of 6.6.3."""
    return any(abs(f.V2) > 0.5 * PHI_SHEAR * wall_vc(geometry, f, fc, lam)[0] for f in forces)


def rho_l_eq71(geometry: WallGeometry, rho_t: float, rho_t_required: float) -> float:
    """Least vertical ratio of 6.4.8.9.4 (Eq. 6.6.71): max(0.0025, 0.0025 + 0.5 (2.5 - hw/lw)
    (ρt - 0.0025)) with ρt the horizontal ratio provided (6.4.8.9.2), but not more than the ρt
    required by 6.4.8.9.1 (and 0.0025 of 6.4.8.9.2)."""
    eq71 = RHO_SHEAR + 0.5 * (2.5 - geometry.height / geometry.length) * (rho_t - RHO_SHEAR)
    return max(RHO_SHEAR, min(eq71, max(rho_t_required, RHO_SHEAR)))


def _k_factor(geometry: WallGeometry) -> float:
    if not geometry.braced:
        return 2.0
    return 0.8 if geometry.restrained else 1.0


def empirical_capacity(geometry: WallGeometry, fc: float) -> float:
    """φPn [N] of Eq. 6.6.89, φ = 0.65 (compression-controlled, 6.2.3.2.2)."""
    k = _k_factor(geometry)
    ratio = k * geometry.clear_height / (32 * geometry.thickness)
    return 0.55 * PHI_TIED * fc * geometry.gross_area * max(0.0, 1 - ratio**2)


def _rho_t_shear(
    geometry: WallGeometry, forces: list[PierForces], fc: float, fy: float, lam: float
) -> float:
    """ρt the in-plane shear needs (6.4.8.9.1): (Vu/φ - Vc) s / (fy d) per h s."""
    h, d = geometry.thickness, 0.8 * geometry.length
    need = 0.0
    for f in forces:
        vc, _ = wall_vc(geometry, f, fc, lam)
        vs = max(abs(f.V2) / PHI_SHEAR - vc, 0.0)
        need = max(need, vs / (min(fy, FYT_SHEAR_MAX) * d * h))
    return need


def boundary_need(
    geometry: WallGeometry,
    section: RcSection,
    forces: list[PierForces],
    fc: float,
    fyt: float,
    bars: WallBars | None = None,
    drift: float | None = None,
    pier: PierInteraction | None = None,
) -> BoundaryNeed:
    """Whether 8.3.6.6 needs boundary elements, their length, height and hoops.

    c is the largest neutral-axis depth at the factored axial force and the nominal moment
    over the combinations with E (all combinations when none is marked) and both senses of the
    in-plane moment; the stress of 8.3.6.6(c) the largest of those combinations. The height
    (8.3.6.6(b)(ii)) is max(lw, Mu/4Vu) of the row governing c at the critical section (the
    bottom cut), not above the wall."""
    lw, t = geometry.length, geometry.thickness
    method = "displacement" if drift is not None and geometry.continuous else "stress"
    seismic = [f for f in forces if f.earthquake] or list(forces)
    pier = pier or PierInteraction(section)
    c_max, stress, height, trigger = 0.0, 0.0, None, None
    governing: tuple[float, float, PierForces] | None = None  # (c, |Vu|, row) at the base
    critical = _critical_section(seismic)
    for f in seismic:
        c_f = max(pier.nominal(f.P, "M3", 1 if top else -1)[1] for top in (True, False))
        c_max = max(c_max, c_f)
        stress = max(stress, extreme_stress(geometry, f.P, f.M3))
        if f in critical and (governing is None or (c_f, abs(f.V2)) > governing[:2]):
            governing = (c_f, abs(f.V2), f)
    if method == "displacement":
        trigger = displacement_trigger(lw, drift or 0.0)
        required = c_max >= trigger
        if required:
            # 8.3.6.6(b)(ii): from the critical section, max(lw, Mu/4Vu) of the combination
            # that governs c there; not above the wall.
            height = lw
            if governing is not None and governing[1] > 0:
                height = max(lw, abs(governing[2].M3) / (4 * governing[1]))
            if geometry.height > 0:
                height = min(height, max(geometry.height, lw))
    else:
        required = stress > STRESS_REQUIRED * fc
    least = length = boundary_length(c_max, lw)
    cover = bars.cover if bars else 40.0
    b = bars.boundary if bars else None
    db = b.dia if b else (bars.vertical_dia if bars else 16.0)
    ash_s = spacing = ties_spacing = None
    ties = False
    proposal = None
    if required:
        length = math.ceil(max(length, LENGTH_STEP) / LENGTH_STEP - 1e-9) * LENGTH_STEP
        own = b.length if b else length
        bc_len, bc_t = own - cover, t - 2 * cover
        ash_s = (boundary_ash(bc_len, fc, fyt), boundary_ash(bc_t, fc, fyt))
        if b:
            hx = max(bc_len / max(b.legs_across - 1, 1), bc_t / max(b.legs_along - 1, 1))
        else:
            hx = HX_MAX
        spacing = min(min(t, own) / 3, 6 * db, so_special(hx))
        proposal = propose_boundary(length, t, cover, fc, fyt, db, b.count if b else 0)
    elif bars is not None:
        # 8.3.6.6(e)(i): ρ at the boundary (Figure 6.8.12).
        if b:
            rho_b = b.count * bar_area(b.dia) / (t * b.length)
        else:
            rho_b = bars.layers * bar_area(bars.vertical_dia) / (t * bars.vertical_spacing)
        ties = rho_b > 2.8 / section.fy
        ties_spacing = 200.0 if ties else None
        if ties:
            length = math.ceil(max(length, LENGTH_STEP) / LENGTH_STEP - 1e-9) * LENGTH_STEP
    return BoundaryNeed(
        required,
        method,
        c_max,
        length if (required or ties) else 0.0,
        height,
        ash_s,
        spacing,
        stress,
        ties,
        ties_spacing,
        proposal,
        least,
        trigger,
    )


def _critical_section(forces: list[PierForces]) -> list[PierForces]:
    """The rows at the critical section (the pier's bottom cut: ``where`` ending in "bottom");
    all rows when none is marked."""
    base = [f for f in forces if f.where.split(" ")[-1] == "bottom"]
    return base or list(forces)


def propose_boundary(
    length: float, t: float, cover: float, fc: float, fyt: float, db: float, count: int = 0
) -> Boundary:
    """Hoops for a boundary element ``length`` long and ``t`` thick: per hoop diameter the
    fewest legs each way that keep hx <= 350 mm (8.3.5.4(c)), more legs while the spacing Ash
    allows (Eq. 6.8.8) is below 75 mm, the spacing the least of Ash's and the limits of
    8.3.6.6(d)(iii) rounded down to 25 mm; the diameter with the least hoop steel per metre of
    height. ``db``: the boundary bars' diameter (6 db), ``count``: their number (kept)."""
    bc_len, bc_t = length - cover, t - 2 * cover
    need_len, need_t = boundary_ash(bc_len, fc, fyt), boundary_ash(bc_t, fc, fyt)
    best: tuple[float, Boundary] | None = None
    for dh in HOOP_DIAMETERS:
        across = max(2, math.ceil(bc_len / HX_MAX - 1e-9) + 1)
        along = max(2, math.ceil(bc_t / HX_MAX - 1e-9) + 1)
        while across * bar_area(dh) / need_len < 75.0:
            across += 1
        while along * bar_area(dh) / need_t < 75.0:
            along += 1
        hx = max(bc_len / (across - 1), bc_t / (along - 1))
        s = min(
            min(t, length) / 3,
            6 * db,
            so_special(hx),
            across * bar_area(dh) / need_len,
            along * bar_area(dh) / need_t,
        )
        s = max(round_down(s, SPACING_STEP), 50.0)
        weight = (across * bc_t + along * bc_len) * bar_area(dh) / s
        if best is None or weight < best[0] - 1e-9:
            best = (weight, Boundary(length, count, db, dh, s, across, along))
    assert best is not None
    return best[1]


def _boundary_rows(
    need: BoundaryNeed, bars: WallBars, geometry: WallGeometry, fc: float
) -> list[dict[str, Any]]:
    """The rows of 8.3.6.6 (the trigger rows are informative: flag)."""
    rows: list[dict[str, Any]] = []
    lw, t = geometry.length, geometry.thickness
    state = "required" if need.required else "not required"
    if need.method == "displacement":
        rows.append(
            _row(
                "Boundary elements: c >= lw / 600(δu/hw) (8.3.6.6(b), Eq. 6.8.10)",
                need.c,
                need.trigger if need.trigger is not None else need.c,
                "mm",
                note=f"largest c = {need.c:.0f} mm against lw / (600 max(δu/hw, 0.007)) = "
                + (f"{need.trigger:.0f} mm" if need.trigger is not None else "?")
                + f": {state}",
                utilisation=0.0,
            )
        )
    else:
        rows.append(
            _row(
                "Boundary elements: extreme fibre stress > 0.2 f'c (8.3.6.6(c))",
                need.stress,
                STRESS_REQUIRED * fc,
                "MPa",
                note=f"{state}; may stop where the stress is below 0.15 f'c = "
                f"{STRESS_STOP * fc:.1f} MPa",
                utilisation=0.0,
            )
        )
    rows[-1]["flag"] = True
    if not need.required:
        if need.ties:
            over = f"over max(c - 0.1 lw, c/2) = {boundary_length(need.c, lw):.0f} mm"
            b = bars.boundary
            if b is None or not b.hoops:
                rows.append(
                    _row(
                        "End ties where ρ at the boundary > 2.8/fy (8.3.6.6(e)(i))",
                        need.length,
                        0.0,
                        "mm",
                        note="ties per 8.3.5.4(a)(iii) and (c) at <= 200 mm "
                        + over
                        + (
                            "; the wall type defines no end bars or ties"
                            if b is None
                            else "; the wall type's end bars have no ties entered"
                        ),
                    )
                )
            else:
                rows.append(
                    _row(
                        "End tie spacing <= 200 mm where ρ at the boundary > 2.8/fy "
                        "(8.3.6.6(e)(i))",
                        b.hoop_spacing,
                        need.ties_spacing or 200.0,
                        "mm",
                        note=f"Ø{b.hoop_dia:g} @ {b.hoop_spacing:g}, ties per 8.3.5.4(a)(iii) "
                        "and (c) " + over,
                    )
                )
        return rows
    b = bars.boundary
    extent = f", height >= {need.height:.0f} mm above the critical section" if need.height else ""
    if b is None:
        rows.append(
            _row(
                "Boundary element provided (8.3.6.6(d))",
                need.length,
                0.0,
                "mm",
                note=f"length >= max(c - 0.1 lw, c/2) = {need.length:.0f} mm{extent}; the wall "
                "type defines none",
            )
        )
        return rows
    rows.append(
        _row(
            "Boundary element length >= max(c - 0.1 lw, c/2) (8.3.6.6(d)(i))",
            need.least_length,
            b.length,
            "mm",
            note=f"c = {need.c:.0f} mm{extent}",
        )
    )
    assert need.ash_s is not None and need.spacing is not None
    if not b.hoops:
        rows.append(
            _row(
                "Boundary hoops provided (8.3.6.6(d)(iii), 8.3.5.4)",
                need.spacing,
                0.0,
                "mm",
                note=f"hoops at <= {need.spacing:.0f} mm needed; the wall type's end bars "
                "have no hoops entered",
            )
        )
        return rows
    rows.append(
        _row(
            "Boundary hoop spacing (8.3.6.6(d)(iii), 8.3.5.4(b))",
            b.hoop_spacing,
            need.spacing,
            "mm",
            note="min(least dimension / 3, 6 db, so)",
        )
    )
    for k, (what, legs) in enumerate(
        (("along the length", b.legs_across), ("across the thickness", b.legs_along))
    ):
        rows.append(
            _row(
                f"Boundary Ash, bc {what} (Eq. 6.8.8)",
                need.ash_s[k] * b.hoop_spacing,
                legs * bar_area(b.hoop_dia),
                "mm²",
                note=f"{legs} legs Ø{b.hoop_dia:g} @ {b.hoop_spacing:g}; 0.09 s bc f'c / fyt",
            )
        )
    hx = max(
        (b.length - bars.cover) / max(b.legs_across - 1, 1),
        (t - 2 * bars.cover) / max(b.legs_along - 1, 1),
    )
    rows.append(_row("Boundary hoop legs hx <= 350 mm (8.3.5.4(c))", hx, HX_MAX, "mm"))
    return rows


# ─────────────────────────────────────── design mode ───────────────────────────────────────


def wall_need(
    geometry: WallGeometry,
    forces: list[PierForces],
    fc: float,
    fy: float,
    es: float = STEEL_E,
    *,
    lam: float = 1.0,
    special: bool = False,
    drift: float | None = None,
    fyt: float | None = None,
    bars: WallBars | None = None,
    boundary: BoundaryNeed | None = None,
    cover: float = 25.0,
    search: bool = False,
) -> WallNeed:
    """The reinforcement a wall needs: ρl, ρt, the largest spacings, the layers, a mesh per face
    (:func:`saengine.design.bars.mesh_for`, Ø10-Ø20, >= 100 mm apart) and, for special walls,
    the boundary elements. ``search``: also look for the end bars the P-M checks need."""
    t, lw = geometry.thickness, geometry.length
    acv = geometry.gross_area
    root = math.sqrt(fc)
    fyt = fy if fyt is None else fyt
    vu = max((abs(f.V2) for f in forces), default=0.0)
    notes: list[str] = []
    cover = bars.cover if bars else cover
    layers = 2 if (t > TWO_LAYER_THICKNESS and not geometry.basement) else 1
    if special and vu > TWO_CURTAIN_SHARE * acv * lam * root:
        layers = 2
    if bars is not None:
        layers = max(layers, bars.layers)
    s_v = s_h = min(3 * t, SPACING_MAX)
    base_l = base_t = 0.0
    eq71 = False
    if special:
        if vu > RELAXED_SHARE * acv * lam * root:
            base_l = base_t = RHO_SHEAR
        # Vu <= φ Acv (αc λ √f'c + ρt fy) with φ = 0.60 (6.2.3.3(a)): the check takes 0.75
        # where Vn reaches the shear at Mn; the proposal does not rely on it.
        sv_need = vu / PHI_SHEAR_SEISMIC / acv - alpha_c(geometry.aspect) * lam * root
        sv_need = max(sv_need, 0.0) / min(fy, FYT_SHEAR_MAX)
        notes.append("ρt for shear with φ = 0.60 (6.2.3.3(a)), on the safe side")
    else:
        sv_need = _rho_t_shear(geometry, forces, fc, fy, lam)
        vmax = PHI_SHEAR * 0.83 * root * t * 0.8 * lw
        if vu > vmax:
            notes.append(
                f"Vu = {_kn(vu):.0f} kN above φ 0.83 √f'c h d = {_kn(vmax):.0f} kN (6.4.8.3): "
                "the wall is too thin or short"
            )
        if _shear_reinforced(geometry, forces, fc, lam):
            base_t = RHO_SHEAR
            eq71 = True  # Eq. 6.6.71 with the ρt of the proposed horizontal mesh, below
            s_h = min(lw / 5, 3 * t, SPACING_MAX)
            s_v = min(lw / 3, 3 * t, SPACING_MAX)

    def per_face(rho_of) -> dict[float, float]:
        return {dia: rho_of(dia) * t * 1000 / layers for dia in WALL_DIAMETERS}

    def rho_horizontal(dia: float) -> float:
        return max(minimum_ratios(dia, dia, fy)[1], base_t, sv_need)

    horizontal = mesh_for(0.0, s_h, WALL_DIAMETERS, MIN_WALL_SPACING, per_face(rho_horizontal))
    rho_t = (
        layers * bar_area(horizontal.dia) / (t * horizontal.spacing)
        if horizontal
        else rho_horizontal(SMALL_BAR_MAX)
    )
    floor = rho_t if special and geometry.aspect <= 2.0 else 0.0
    if floor:
        notes.append("8.3.6.4(c): ρl >= ρt (hw/lw <= 2.0)")
    if eq71:
        base_l = rho_l_eq71(geometry, rho_t, sv_need)

    def rho_vertical(dia: float) -> float:
        return max(minimum_ratios(dia, dia, fy)[0], base_l, floor)

    vertical = mesh_for(0.0, s_v, WALL_DIAMETERS, MIN_WALL_SPACING, per_face(rho_vertical))
    rho_l = (
        layers * bar_area(vertical.dia) / (t * vertical.spacing)
        if vertical
        else rho_vertical(SMALL_BAR_MAX)
    )
    if horizontal is None or vertical is None:
        notes.append("no mesh of Ø10-Ø20 at >= 100 mm apart carries it: the wall is too thin")
    if special and vu > PHI_SHEAR_SEISMIC * 0.83 * acv * root:
        notes.append(
            f"Vu = {_kn(vu):.0f} kN above φ 0.83 Acw √f'c = "
            f"{_kn(PHI_SHEAR_SEISMIC * 0.83 * acv * root):.0f} kN: the wall is too thin or short"
        )
    end_bars = None
    web = None
    if vertical is not None and horizontal is not None:
        web = WallBars(
            cover, vertical.dia, vertical.spacing, horizontal.dia, horizontal.spacing, layers
        )
    if special and boundary is None and web is not None:
        try:
            section = pier_section(geometry, web, fc, fy, es)
            boundary = boundary_need(geometry, section, forces, fc, fyt, web, drift)
        except DesignError as error:
            notes.append(f"boundary elements not found: {error}")
    if search and web is not None:
        # End bars, then the boundary elements of the section with them (c grows with the end
        # steel), again until the boundary element stops growing.
        for _ in range(4):
            found, end_bars = _search_end_bars(
                geometry, forces, fc, fy, es, fyt, web, boundary, special
            )
            if not found:
                notes.append(
                    "no end bars up to 12 Ø32 per end carry the axial force and bending: "
                    "enlarge the wall"
                )
                break
            if not special or end_bars is None:
                break
            trial = replace(web, boundary=end_bars)
            again = boundary_need(
                geometry, pier_section(geometry, trial, fc, fy, es), forces, fc, fyt, trial, drift
            )
            grown = again.required and (
                boundary is None or not boundary.required or again.length > end_bars.length
            )
            boundary = again
            if not grown:
                break
    return WallNeed(
        special,
        layers,
        rho_l,
        rho_t,
        s_v,
        s_h,
        vertical,
        horizontal,
        boundary,
        end_bars,
        tuple(notes),
    )


def end_length(count: int, dia: float, cover: float, hoop: float = 10.0) -> float:
    """Length from the wall end [mm] that ``count`` end bars in two rows need at the least
    clear spacing of column bars (:func:`saengine.design.bars.column_min_clear`), rounded up
    to 50 mm."""
    rows = math.ceil(count / 2)
    length = cover + 2 * hoop + rows * dia + (rows - 1) * column_min_clear(dia)
    return math.ceil(length / LENGTH_STEP - 1e-9) * LENGTH_STEP


def _search_end_bars(
    geometry: WallGeometry,
    forces: list[PierForces],
    fc: float,
    fy: float,
    es: float,
    fyt: float,
    web: WallBars,
    boundary: BoundaryNeed | None,
    special: bool = False,
) -> tuple[bool, Boundary | None]:
    """(found, end bars): the least end steel (count x area, then the diameter) whose section
    passes the P-M checks (:class:`PierInteraction`); (True, None) when the web mesh alone
    passes and neither a boundary element nor end ties (8.3.6.6(e)(i)) are required."""

    def passes(b: WallBars) -> bool:
        try:
            section = pier_section(geometry, b, fc, fy, es)
        except DesignError:
            return False
        s = PierInteraction(section)
        return all(s.check(f.P, f.M3, f.M2).utilisation <= 1.0 for f in forces)

    required = bool(boundary and boundary.required)
    ties = bool(special and boundary and boundary.ties)  # 8.3.6.6(e)(i): end bars and ties
    if not required and not ties and passes(web):
        return True, None
    options = sorted(
        ((n, d) for n in (4, 6, 8, 10, 12) for d in BOUNDARY_DIAMETERS),
        key=lambda o: (o[0] * bar_area(o[1]), o[1]),
    )
    for n, d in options:
        length = max(boundary.length if required and boundary else 0.0, end_length(n, d, web.cover))
        if 2 * length >= geometry.length:
            continue
        b = propose_boundary(length, geometry.thickness, web.cover, fc, fyt, d, n)
        if not required:
            # Ties, not a boundary element: at most 200 mm apart in special walls (8.3.6.6(e)
            # (i)), else as column ties min(16 db, 48 dt, t) (as bars.column_ties).
            tie = min(16 * d, 48 * b.hoop_dia, geometry.thickness)
            b = replace(b, hoop_spacing=round_down(min(tie, 200.0) if special else tie))
        if passes(replace(web, boundary=b)):
            return True, b
    return False, None


# ─────────────────────────────────────── coupling beams ───────────────────────────────────────


@dataclass(frozen=True)
class Diagonal:
    """One of the two groups of diagonal bars of a coupling beam."""

    count: int
    dia: float
    edge: float = 0.0  # centroid of the group from the beam face at the wall face [mm]
    angle: float | None = None  # α [rad]; None: from the depth, edge and span

    def area(self) -> float:
        return self.count * bar_area(self.dia)


@dataclass
class CouplingBeam:
    mode: str  # "diagonal" (required), "either", "flexural"
    checks: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    avd_required: float = 0.0  # mm² per group
    proposal: Diagonal | None = None


def coupling_beam_checks(
    ln: float,
    h: float,
    bw: float,
    vu: float,
    fc: float,
    fy: float,
    *,
    diagonal: Diagonal | None = None,
    lam: float = 1.0,
    combination: str | None = None,
    cover: float = 40.0,
) -> CouplingBeam:
    """A coupling beam of special structural walls (8.3.6.7): ``ln`` clear span, ``h`` depth,
    ``bw`` width [mm], ``vu`` the largest factored shear [N]. ``mode`` "flexural": check it as
    a special moment frame beam (``ductile_members.beam_checks``); "either": diagonals or the
    beam rules; "diagonal": diagonal bars required."""
    acw = bw * h
    root = math.sqrt(fc)
    ratio = ln / h
    threshold = 0.33 * acw * lam * root
    if ratio > 4:
        mode = "flexural"
    elif ratio < 2 and vu > threshold:
        mode = "diagonal"
    else:
        mode = "either"
    out = CouplingBeam(mode)
    out.notes.append(
        f"ln/h = {ratio:.2f}, Vu = {_kn(vu):.1f} kN, 0.33 Acw λ √f'c = {_kn(threshold):.1f} kN: "
        + {
            "flexural": "a flexural member of a special moment frame (8.3.6.7(a); the text's "
            "8.3.7 [sic], the beam rules are 8.3.4)",
            "diagonal": "two intersecting groups of diagonal bars required (8.3.6.7(b))",
            "either": "diagonal bars or the beam rules (8.3.6.7(c))",
        }[mode]
    )
    edge = diagonal.edge if diagonal and diagonal.edge else cover + 10.0 + 2 * 20.0
    if diagonal is not None and diagonal.angle is not None:
        alpha = diagonal.angle
    else:
        alpha = math.atan((h - 2 * edge) / ln)
    vmax = 0.83 * acw * root
    sin = math.sin(alpha)
    out.avd_required = vu / (PHI_DIAGONAL * 2 * fy * sin) if sin > 0 else math.inf
    if mode != "flexural":
        for d in BOUNDARY_DIAMETERS:
            n = max(4, 2 * math.ceil(out.avd_required / bar_area(d) / 2))
            if n <= 8:
                out.proposal = Diagonal(n, d, edge, alpha)
                break
    if diagonal is not None and mode != "flexural":
        vn = min(2 * diagonal.area() * fy * sin, vmax)
        out.checks.append(
            _row(
                "Coupling beam diagonal bars Vn = 2 Avd fy sin α <= 0.83 Acw √f'c (Eq. 6.8.11)",
                _kn(vu),
                _kn(PHI_DIAGONAL * vn),
                "kN",
                combination,
                f"{diagonal.count} Ø{diagonal.dia:g} per group, α = {math.degrees(alpha):.1f}°, "
                f"φ = 0.85 (6.2.3.3(c)); 0.83 Acw √f'c = {_kn(vmax):.1f} kN",
            )
        )
        out.checks.append(
            _row("Diagonal bars per group (8.3.6.7(d)(ii))", 4, diagonal.count, "bars")
        )
        out.notes.append(
            f"8.3.6.7(d)(iv): transverse bars over the whole section at <= min(150 mm, 6 db) = "
            f"{min(150.0, 6 * diagonal.dia):.0f} mm, crossties and legs <= 200 mm apart"
        )
    elif mode == "diagonal":
        out.checks.append(
            _row(
                "Coupling beam diagonal bars required (8.3.6.7(b))",
                out.avd_required,
                0.0,
                "mm²",
                combination,
                f"Avd >= Vu / (φ 2 fy sin α) per group, α = {math.degrees(alpha):.1f}°",
            )
        )
    return out

"""Design of reinforced-concrete walls and coupling beams to the default pack's BNBC 2020 Part 6 (the code PDF).

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
  metre); out-of-plane bending (M2 per metre of length) of a 1 m strip of the web with its
  axial force per metre (6.6.4, :func:`web_strip_check`): a design check beside the pier's
  P-M3-M2 row, which counts the end bars too (R3-1).
- Slenderness (6.6.4 → 6.3.10): k lc / r out of the plane (r = 0.3 t) is reported; the moment
  magnification itself is :mod:`saengine.design.slender`'s.

Special structural walls (Sec 8.3.6, pp. 1100-1107), when the seismic scope says 8.3.6 applies
(:func:`special_applies`)
- 8.3.6.2(a): ρl, ρt >= 0.0025, except that where Vu <= 0.083 Acv λ √f'c the values of (i)/(ii)
  (those of 6.6.3) apply; spacing each way <= 450 mm. (b) two curtains where Vu > 0.17 Acv λ
  √f'c.
- 8.3.6.3: Vu from the analysis (default pack BNBC sets no shear amplification for walls).
- 8.3.6.4(a): Vn = Acv (αc λ √f'c + ρt fy) (Eq. 6.8.9), αc = 0.25 for hw/lw <= 1.5, 0.17 for
  hw/lw >= 2.0, linear between; (b) hw/lw the larger of the entire wall's and the segment's;
  (c) ρl >= ρt where hw/lw <= 2.0; (d) Vn <= 0.83 Acw √f'c for one segment (the 0.66 Acv √f'c
  of all segments sharing a lateral force is the integrator's, across walls). φ = 0.60 where Vn
  is less than the shear at the nominal flexural strength (Vu Mn / Mu at Pu), else 0.75
  (6.2.3.3(a), p. 898).
- 8.3.6.5: flexure and axial load by 6.3.2 and 6.3.3 (the same P-M surface) of the rectangular
  pier here; walls meeting at an L, T, C or X are designed as one flanged section (effective
  flange widths of 8.3.6.5(b)) by :mod:`saengine.design.wall_flanges`, called from
  :mod:`saengine.design.wall_design`, which marks the superseded pier rows.
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
(Eq. 6.8.11), φ = 0.85 (6.2.3.3(c)), at least four bars per group (8.3.6.7(d)(ii)) embedded
1.25 ld into the wall (the narrower pier beside the beam: (lw - cover) / cos α along the bar),
and either (iv) hoops over the whole section: at most min(150 mm, 6 db) apart along the beam,
their legs and crossties at most 200 mm apart each way, Ash of 8.3.5.4 (the larger of Eq. 6.8.7
and 6.8.8) across the core's depth and across its width, each leg engaging a longitudinal bar of
at least its diameter (the type's coupling-beam longitudinal bars, else the wall's horizontal
bars: one per face at each leg down the depth); or, when the type gives no such hoops, (iii)
hoops around each group: out-to-out at least bw/2 parallel to bw and bw/5 along the other sides,
Ash of 8.3.5.4 on the group's section with the cover on all four sides, spacing along the bars
at most min(bw/4, so, 6 db) (8.3.5.4(b); owner 2026-11-04: bw/4 too, beyond ACI 18.10.7.4(c)), legs at most 350 mm
apart, and bars around the beam's perimeter at least 0.002 bw s each way at most 300 mm apart
(the pack's ``detailing.walls`` coupling* values).

Wall piers (8.3.6.8, pp. 1109-1110). The code does not define a wall pier's proportions: the
pack's pierLengthRatioMax and pierHeightRatioMin (default pack and generic: ACI 318-19 2.3's
lw/bw <= 6.0 and clear height / lw >= 2.0) pick the piers beside openings that are wall piers
(:func:`pier_kind`); those with lw/bw at most pierAlternativeRatio (2.5) take the column rules
(8.3.5.3(a) steel ratio, 8.3.5.4 hoops over the clear height, the capacity-design shear with
Vc = 0), the others the alternative (i)-(vi) (:func:`wall_pier_rows`): Ve by capacity design
2 Mpr / hc, at most Ω0 Vu, against Vn of 8.3.6.4 with ρt of the web and the hoops; hoops at most
pierHoopSpacingMax (150 mm) apart, extended pierHoopExtension (300 mm) above and below the clear
height (measured by the bill and the bar schedule); boundary elements by 8.3.6.6(c); at an edge
of the wall, the horizontal bars above and below the clear height (within lw of it) carry Ve
(8.3.6.8(b)).

Check-row names cite the clauses of the pack's ``designClauses.wallsRows`` (:func:`named`); a
pack without them names the rows without a clause.

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

from saengine.codes import context as code_context
from saengine.design.bars import (
    Mesh,
    column_min_clear,
    column_rho,
    mesh_for,
    round_down,
    spacing_step,
)
from saengine.design.clauses import Clauses
from saengine.design.clauses import own_text as clause_text
from saengine.design.ductile_members import _row, so_special
from saengine.design.rc import (
    Bar,
    ColumnCheck,
    DesignError,
    InteractionSurface,
    RcSection,
    bar_area,
    beta1,
    phi_axial_flexure,
    stress_block,
)
from saengine.design.rc import value as rc_value
from saengine.library.objects import RectangleProfile

#: The clause of each check, from the code pack in force (``designClauses.walls``).
CLAUSES: Clauses = Clauses("walls")

#: The pack's group of the clause numbers the check rows' names cite (``designClauses.
#: wallsRows``: the clause without the code's name, e.g. "8.3.6.7(d)(iv)" in the default pack).
ROWS = "wallsRows"


def ref(key: str) -> str:
    """The clause row ``key`` cites, from the pack in force ("" when it has none, C11 also when
    it would only inherit another code's number: the row is then named without a clause)."""
    return clause_text(ROWS, key)


def _paren(label: str, text: str) -> str:
    """``label (text)``, or ``label`` alone when ``text`` is empty."""
    return f"{label} ({text})" if text else label


def named(label: str, *keys: str, extra: Iterable[str] = ()) -> str:
    """A check row's name: ``label`` with the pack's clauses of ``keys`` (and ``extra`` words)
    in parentheses; ``label`` alone when the pack has none of them."""
    return _paren(label, ", ".join(t for t in [*(ref(k) for k in keys), *extra] if t))


def steel_limit(name: str) -> float:
    """The pack's ``concrete.walls`` value ``name`` (default pack BNBC 2020: smallBarMax 16 mm and smallBarFy
    420 MPa, the bars of the small-bar ratios of 6.6.3.2 / 6.6.3.3; rhoShear 0.0025 of
    6.4.8.9.2, 6.4.8.9.4 and 8.3.6.2(a); twoLayerThickness 250 mm, above which the bars go in
    two layers (6.6.3.4); spacingMax 450 mm (6.6.3.5, 8.3.6.2(a)))."""
    return float(code_context.table("concrete").walls[name])


def least_ratios(name: str) -> tuple[float, float]:
    """The pack's least ratios (vertical, horizontal) ``name`` of 6.6.3.2 / 6.6.3.3 and
    8.3.6.2(a)(i)/(ii) (default pack BNBC 2020: rhoSmallBars (0.0012, 0.0020), bars not larger than 16 mm
    with fy not less than 420 MPa; rhoOtherBars (0.0015, 0.0025), other deformed bars)."""
    rho = code_context.table("concrete").walls[name]
    return (float(rho[0]), float(rho[1]))


def special_limit(name: str) -> float:
    """The pack's ``detailing.walls`` value ``name`` (default pack BNBC 2020: relaxedShare 0.083 and
    twoCurtainShare 0.17, shear thresholds of 8.3.6.2 as x Acv λ √f'c; driftMin 0.007, the
    least δu/hw of displacement-based boundary elements (8.3.6.6(b)(i)); stressRequired 0.2 and
    stressStop 0.15, stress-based boundary elements required above / may stop below x f'c
    (8.3.6.6(c)); fytConfinementMax 700 MPa; hxMax 350 mm (8.3.5.4(c)))."""
    return float(code_context.table("detailing").walls[name])


def wall_phi(name: str) -> float:
    """The pack's φ ``name`` (default pack BNBC 2020: shearSeismic 0.60, shear of members whose Vn is below
    the shear at Mn (6.2.3.3(a)); diagonalCoupling 0.85, diagonally reinforced coupling beams
    (6.2.3.3(c)))."""
    return float(code_context.table("factors").phi[name])


def bar_sizes(name: str) -> tuple[float, ...]:
    """The pack's bar size set ``name`` [mm] of the design mode (default pack BNBC 2020: wall (10, 12, 16,
    20), the horizontal and vertical wall bars; boundary (16, 20, 25, 32); hoop (10, 12))."""
    return tuple(float(d) for d in code_context.table("concrete").barDiameters[name])


#: Least spacing of the design mode's wall meshes [mm].
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
    # Hoops of the type's wall piers (8.3.6.8), in addition to the web bars; None: none.
    pier_hoop: CouplingHoops | None = None

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
    p = _get(reinforcement, "pierHoop")
    pier_hoop = None
    if p is not None:
        pier_hoop = CouplingHoops(
            float(_get(p, "dia", 10.0)),
            float(_get(p, "spacing", 100.0)),
            int(_get(p, "legsAcross", 2)),
            int(_get(p, "legsAlong", 2)),
        )
    return WallBars(
        float(_get(reinforcement, "cover")),
        float(_get(vertical, "dia")),
        float(_get(vertical, "spacing")),
        float(_get(horizontal, "dia")),
        float(_get(horizontal, "spacing")),
        int(_get(reinforcement, "layers", 2)),
        boundary,
        pier_hoop,
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
    geometry: WallGeometry, bars: WallBars, fc: float, fy: float, es: float | None = None
) -> RcSection:
    """The pier's :class:`RcSection` (see the module notes on the layout)."""
    if es is None:
        es = rc_value("STEEL_E")
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
        # Alpha 9 C5b: the pack's block (η fcd, λ, εcu3, fyd with partial factors).
        bk = stress_block(s.fc, s.fy)
        a = np.minimum(bk.beta * c, depth)
        strain = bk.eps_cu * (c - dist[None, :]) / c
        stress = np.clip(s.es * strain, -bk.fy, bk.fy)
        stress = stress - np.where(dist[None, :] < a, bk.k, 0.0)
        force = stress * area[None, :]
        conc = bk.k * width * a[:, 0]
        pn = conc + force.sum(axis=1)
        mn = conc * (depth / 2 - a[:, 0] / 2) + (force * (depth / 2 - dist[None, :])).sum(axis=1)
        eps_t = bk.eps_cu * (dist.max() - c[:, 0]) / c[:, 0]
        return pn, mn, eps_t

    def _diagram(self, axis: str, sense: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Factored (φPn, φMn) and c, from pure tension to φPn,max, ordered by c."""
        s = self.section
        _, _, dist, _ = self._geometry(axis, sense)
        eps_ty = s.fy / s.es
        dt = float(dist.max())
        transition = rc_value("EPS_CU") / (
            rc_value("EPS_CU") + eps_ty + rc_value("EPS_CU") * np.linspace(0, 1, 13)
        )
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
        tension = -rc_value("PHI_TENSION") * s.fy * s.steel_area
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
    if _pack_walls():  # Alpha 9 C5b: the pack's member steel
        from saengine.design import limit_state_rows

        m = limit_state_rows._table().memberSteel
        return float(m.wallVerticalMin), float(
            max(m.wallHorizontalMin, m.wallHorizontalShare * m.wallVerticalMin)
        )

    small_max, small_fy = steel_limit("smallBarMax"), steel_limit("smallBarFy")
    small_bars, other_bars = least_ratios("rhoSmallBars"), least_ratios("rhoOtherBars")

    def small(dia: float) -> bool:
        return dia <= small_max and fy >= small_fy

    return (
        small_bars[0] if small(dia_vertical) else other_bars[0],
        small_bars[1] if small(dia_horizontal) else other_bars[1],
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
    vs = av * min(fy, rc_value("FYT_SHEAR_MAX")) * d / bars.horizontal_spacing
    vmax = 0.83 * math.sqrt(fc) * h * d
    return {"vc": vc, "vs": vs, "vn": min(vc + vs, vmax), "vmax": vmax, "how": how}


def special_vn(
    geometry: WallGeometry, rho_t: float, fc: float, fy: float, lam: float = 1.0
) -> dict[str, float]:
    """Vn of a special structural wall (Eq. 6.8.9) and its limit 0.83 Acw √f'c (8.3.6.4(d))."""
    acv = geometry.gross_area
    a = alpha_c(geometry.aspect)
    vn = acv * (a * lam * math.sqrt(fc) + rho_t * min(fy, rc_value("FYT_SHEAR_MAX")))
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
    lw / (600 max(δu/hw, 0.007)); C2: lw / (600 · driftFactor · max(δu/hw, driftMin)) for a
    pack with a drift factor (ACI 318-19 Eq 18.10.6.2: 1.5, δu/hw at least 0.005)."""
    factor = special_limit("driftFactor")
    if factor == 1.0:
        return lw / (600 * max(drift, special_limit("driftMin")))
    return lw / (600 * factor * max(drift, special_limit("driftMin")))


def _drift_times() -> str:
    """The drift factor and a space before δu/hw in the row name (C2: e.g. 1.5); nothing in a
    pack without one."""
    factor = special_limit("driftFactor")
    return f"{factor:g} " if factor != 1.0 else ""


def trigger_text() -> str:
    """The displacement trigger as the notes print it: "600 max(δu/hw, 0.007)" in the default
    pack; with the pack's drift factor "600 × 1.5 max(δu/hw, 0.005)" (C2)."""
    factor, least = special_limit("driftFactor"), special_limit("driftMin")
    times = f" × {factor:g}" if factor != 1.0 else ""
    return f"600{times} max(δu/hw, {least:g})"


def two_curtains_by_aspect(geometry: WallGeometry) -> bool:
    """C2: two curtains also because hw/lw reaches the pack's ``curtainAspect`` (ACI 318-19
    18.10.2.2: 2.0); False without the value."""
    aspect = getattr(code_context.table("detailing").walls, "curtainAspect", None)
    return bool(aspect) and geometry.length > 0 and geometry.height / geometry.length >= aspect


def shear_amplification(geometry: WallGeometry) -> tuple[float, str]:
    """C2: (Ωv ωv, how) of a special wall's design shear Ve = Ωv ωv Vu <= cap Vu by the pack's
    ``detailing.walls.shearAmplification`` (ACI 318-19 18.10.3.3); (1.0, "") without it.

    Ωv = ``omega`` where hw/lw exceeds ``aspect`` (the pack's lower bound; the overstrength
    Mpr/Mu, which may be larger, is not computed: SAEngine practice), else 1.0. ωv = 1.0 where
    hw/lw is below ``dynamicAspect``; else a + ns/b with ns the storeys of the wall, taken as
    hw over the storey's clear height rounded (SAEngine practice), (a, b) ``dynamicLow`` up to
    ``dynamicStoreys`` storeys, ``dynamicHigh`` at most ``dynamicMax`` above."""
    rule = getattr(code_context.table("detailing").walls, "shearAmplification", None)
    if rule is None or geometry.length <= 0:
        return 1.0, ""
    aspect = geometry.height / geometry.length
    omega = rule.omega if aspect > rule.aspect else 1.0
    if aspect < rule.dynamicAspect:
        omega_v, storeys = 1.0, ""
    else:
        ns = (
            max(1, round(geometry.height / geometry.clear_height))
            if geometry.clear_height > 0
            else 1
        )
        a, b = rule.dynamicLow if ns <= rule.dynamicStoreys else rule.dynamicHigh
        omega_v = a + ns / b
        if ns > rule.dynamicStoreys:
            omega_v = min(omega_v, rule.dynamicMax)
        storeys = f", ns = {ns} (hw / storey height)"
    factor = min(omega * omega_v, rule.cap)
    how = _paren(
        f"Ve = Ωv ωv Vu = {omega:g} × {omega_v:.2f} Vu (hw/lw = {aspect:.2f}{storeys}), at most "
        f"{rule.cap:g} Vu",
        ref("shearAmplification"),
    )
    return factor, how


def amplified(forces: list[PierForces], factor: float) -> list[PierForces]:
    """C2: the earthquake combinations' in-plane shear × ``factor`` (the others unchanged)."""
    if factor == 1.0:
        return forces
    return [replace(f, V2=f.V2 * factor) if f.earthquake else f for f in forces]


def extreme_stress(geometry: WallGeometry, pu: float, mu: float) -> float:
    """Pu/Ag + |Mu| (lw/2) / I [MPa], gross section, linear elastic (8.3.6.6(c))."""
    t, lw = geometry.thickness, geometry.length
    return pu / (t * lw) + abs(mu) * (lw / 2) / (t * lw**3 / 12)


def boundary_ash(bc: float, fc: float, fyt: float) -> float:
    """Least Ash / s [mm²/mm] across a core dimension bc: Eq. 6.8.8 (8.3.6.6(d)(iii) waives
    Eq. 6.8.7), fyt at most 700 MPa (8.3.3.4(c))."""
    return 0.09 * bc * fc / min(fyt, special_limit("fytConfinementMax"))


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
    pier_hoop: CouplingHoops | None = None  # a wall pier's hoops (8.3.6.8); None: not a pier


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
    es: float | None = None,
    *,
    lam: float = 1.0,
    special: bool = False,
    drift: float | None = None,
    surface: InteractionSurface | PierInteraction | None = None,
    fyt: float | None = None,
    grade_beam: Any = None,
    wall_pier: WallPier | None = None,
    ductility: str | None = None,
    mu_phi: tuple | None = None,
) -> WallDesign:
    """All checks of a wall pier (ordinary, and 8.3.6 when ``special``).

    ``wall_pier``: where the pier stands beside its openings; a special wall's pier that is a wall
    pier (:func:`pier_kind`) adds the rows of :func:`wall_pier_rows` (8.3.6.8) and takes its
    boundary elements by the stress method (8.3.6.8(a)(vi) -> 8.3.6.6(c)).

    B33: the pack's slender-wall method out of the plane (:func:`slender_wall_checks`, checks
    where k lc / r exceeds the slenderness limit, informative otherwise) and, with
    ``grade_beam`` (the type's ``GradeBeamWall``), the wall as a grade beam
    (:func:`grade_beam_checks`).

    ``drift``: δu/hw of the wall (the design displacement at its top over its height, the default pack's BNBC
    2.5.9 Cd δe / I) for the displacement-based boundary elements; None: the stress-based method
    (8.3.6.6(c)). ``surface``: the pier section's interaction surface when the caller caches it
    per type and length. ``fyt``: the hoops' yield strength (default ``fy``)."""
    if es is None:
        es = rc_value("STEEL_E")
    # Alpha 9 C8: a pack with its own ductile detailing (IS 13920) checks a special wall as an
    # ordinary one here and adds its own special wall rows at the end.
    from saengine.design import ductile_detailing

    ductile_wall = special and ductile_detailing.rules() is not None
    if ductile_wall:
        special = False
    out = WallDesign()
    if special:
        # C2: the pack's design shear of special walls (none in the default pack).
        factor, how = shear_amplification(geometry)
        if factor != 1.0:
            forces = amplified(forces, factor)
            out.notes.append(f"In-plane shear of the earthquake combinations: {how}")
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
    pier_rows: list[dict[str, Any]] = []
    if special and wall_pier is not None:
        pier_rows, pier_notes, kind = wall_pier_rows(
            geometry, bars, forces, fc, fy, es, wall_pier, lam=lam, fyt=fyt
        )
        out.notes += pier_notes
        if kind != "wall":
            drift = None  # 8.3.6.8(a)(vi): boundary elements by 8.3.6.6(c)

    # Minimum distributed reinforcement.
    min_l, min_t = minimum_ratios(bars.vertical_dia, bars.horizontal_dia, fy)
    rule = ref("minimum")
    shear_reinforced = _shear_reinforced(geometry, forces, fc, lam)  # 6.4.8.8
    req_l, req_t = min_l, min_t
    if special:
        if vu > special_limit("relaxedShare") * acv * lam * root:
            req_l = req_t = steel_limit("rhoShear")
            rule = ref("webSpecial")
        else:
            relaxed = ref("webRelaxed")
            rule = (f"{relaxed}: " if relaxed else "") + "Vu <= 0.083 Acv λ √f'c"
    elif shear_reinforced:
        req_t = max(req_t, steel_limit("rhoShear"))
        t_need = _rho_t_shear(geometry, forces, fc, fy, lam)
        req_l = max(req_l, rho_l_eq71(geometry, rho_t, t_need))
        rule = ref("webShear")
        why = ", ".join(t for t in ("Vu > 0.5 φVc", ref("shearReinforced")) if t)
        rule = _paren(rule, why) if rule else why
    out.checks.append(
        _row(
            _paren("Vertical web ratio ρl", rule),
            100 * req_l,
            100 * rho_l,
            "%",
            note=f"{bars.layers} x Ø{bars.vertical_dia:g} @ {bars.vertical_spacing:g}",
        )
    )
    out.checks.append(
        _row(
            _paren("Horizontal web ratio ρt", rule),
            100 * req_t,
            100 * rho_t,
            "%",
            note=f"{bars.layers} x Ø{bars.horizontal_dia:g} @ {bars.horizontal_spacing:g}",
        )
    )
    if special and geometry.aspect <= 2.0:
        out.checks.append(
            _row(
                named("ρl >= ρt where hw/lw <= 2.0", "rhoLAtLeastT"),
                100 * rho_t,
                100 * rho_l,
                "%",
                note=f"hw/lw = {geometry.aspect:.2f}",
            )
        )

    # Spacing.
    s_max = steel_limit("spacingMax")
    s_v, s_h = min(3 * t, s_max), min(3 * t, s_max)
    why_v = why_h = named("min(3t, 450 mm)", "spacing")
    if shear_reinforced and not special:
        s_h, why_h = (
            min(lw / 5, 3 * t, s_max),
            named("min(lw/5, 3h, 450 mm)", "spacingHorizontalShear"),
        )
        s_v, why_v = (
            min(lw / 3, 3 * t, s_max),
            named("min(lw/3, 3h, 450 mm)", "spacingVerticalShear"),
        )
    if special:
        why_v = why_h = f"{named('450 mm', 'webSpecial')} and {named('min(3t, 450 mm)', 'spacing')}"
    out.checks.append(_row(f"Vertical bar spacing, {why_v}", bars.vertical_spacing, s_v, "mm"))
    out.checks.append(_row(f"Horizontal bar spacing, {why_h}", bars.horizontal_spacing, s_h, "mm"))

    # Layers.
    if t > steel_limit("twoLayerThickness") and not geometry.basement:
        out.checks.append(
            _row(
                named("Two layers in walls thicker than 250 mm", "layers"), 2, bars.layers, "layers"
            )
        )
    if special:
        curtains = special_limit("twoCurtainShare") * acv * lam * root
        tall = two_curtains_by_aspect(geometry)
        need2 = vu > curtains or tall
        out.checks.append(
            _row(
                named(
                    "Two curtains where Vu > 0.17 Acv λ √f'c"
                    + (" or hw/lw is large" if tall else ""),
                    "curtains",
                ),
                2 if need2 else 1,
                bars.layers,
                "curtains",
                vu_name,
                f"Vu = {_kn(vu):.1f} kN, 0.17 Acv λ √f'c = {_kn(curtains):.1f} kN"
                + (f"; hw/lw = {geometry.height / lw:.2f}" if tall else ""),
            )
        )

    # R3-2: the end bars over their zone no more than a compression member's largest ratio
    # (walls designed as compression members, 6.6.4 -> 6.3.8.1; the pack's concrete.columnRho).
    if bars.boundary is not None:
        out.checks.append(end_ratio_row(bars.boundary, t))

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
                named(
                    "Axial force and bending P-M3-M2",
                    "compression",
                    *(("flexureSpecial",) if special else ()),
                ),
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
    phi_v = rc_value("PHI_SHEAR")
    from saengine.design import tabulated_shear

    if vu_case is not None and tabulated_shear.wall_rules() is not None:
        # Alpha 9 C8: in-plane shear by the aspect ratio (IS 456 32.4, IS 13920 for special
        # walls with the same τc), the horizontal bars Ah/Sv = ρt t.
        out.checks.append(
            tabulated_shear.wall_shear_row(
                vu, t, lw, geometry.aspect * lw, fc, fy, rho_t * t, vu_name
            )
        )
    elif vu_case is not None:
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
                phi_v = wall_phi("shearSeismic")
            shown = f"{_kn(v_at_mn):.1f} kN" if math.isfinite(v_at_mn) else "∞"
            note = (
                f"Vn = Acv (αc λ √f'c + ρt fy), αc = {sv['alpha']:.3f} (hw/lw = "
                f"{geometry.aspect:.2f}), <= 0.83 Acw √f'c = {_kn(sv['vmax']):.1f} kN; φ = "
                f"{phi_v:.2f} for the wall (6.2.3.3(a): Vn "
                f"{'<' if phi_v < rc_value('PHI_SHEAR') else '>='} the largest Vu Mn/Mu = {shown}"
                + (f", {phi_case.combination})" if phi_case is not None else ")")
            )
            name = named("In-plane shear", "shearSpecial")
        else:
            sv = wall_vn(geometry, bars, vu_case, fc, fy, lam)
            vn = float(sv["vn"])
            note = (
                f"Vc = {_kn(float(sv['vc'])):.1f} kN ({sv['how']}), Vs = Av fy d/s = "
                f"{_kn(float(sv['vs'])):.1f} kN, d = 0.8 lw; Vn <= 0.83 √f'c h d = "
                f"{_kn(float(sv['vmax'])):.1f} kN"
            )
            name = named("In-plane shear", "shear")
        # Every combination against its own Vn: the ordinary Vc depends on Nu, Mu.
        best = (vu / (phi_v * vn) if vn > 0 else math.inf, vu_case, vn)
        if not special:
            for f in forces:
                v = float(wall_vn(geometry, bars, f, fc, fy, lam)["vn"])
                u = abs(f.V2) / (rc_value("PHI_SHEAR") * v) if v > 0 else math.inf
                if u > best[0]:
                    best = (u, f, v)
        u, f, vn = best
        out.checks.append(
            _row(name, _kn(abs(f.V2)), _kn(phi_v * vn), "kN", f.combination, note, utilisation=u)
        )
    out.checks += pier_rows

    # Out-of-plane: bending of the web per metre with its axial force (6.6.4), slab shear
    # (6.4.8.1), slenderness.
    strip_row = web_strip_check(geometry, bars, forces, fc, fy, es)
    if strip_row is not None:
        out.checks.append(strip_row)
    v3_case = _largest(forces, lambda f: abs(f.V3))
    if v3_case is not None and abs(v3_case.V3) > 0:
        d = (
            t - bars.cover - bars.horizontal_dia - bars.vertical_dia / 2
            if bars.layers == 2
            else t / 2
        )
        cap = rc_value("PHI_SHEAR") * 0.17 * lam * _root(fc) * 1000 * d
        q = abs(v3_case.V3) / lw * 1000
        out.checks.append(
            _row(
                named("Out-of-plane shear per metre, as a slab", "outOfPlaneShear"),
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
    out.checks += slender_wall_checks(geometry, bars, forces, fc, fy, es, lam, required=klr > 22)
    out.checks += grade_beam_checks(geometry, grade_beam, bars, forces, fc, fy, es, lam)
    out.checks += _joint_rows(geometry, bars, forces, fc, fy)

    # Empirical method (informative alternative to 6.6.4) and its least thickness.
    p_case = _largest(forces, lambda f: f.P)
    if tabulated_shear.wall_rules() is not None:
        # Alpha 9 C9b: the pack's empirical wall method (IS 456 32.2 type) in place of 6.6.5.
        out.checks += tabulated_shear.wall_axial_rows(geometry, forces, fc, _k_factor(geometry))
    elif p_case is not None and p_case.P > 0:
        middle = all(f.P > 0 and abs(f.M2) / f.P <= t / 6 for f in forces)
        if middle:
            phi_pn = empirical_capacity(geometry, fc)
            out.checks.append(
                _row(
                    named(
                        "Empirical method φPn = 0.55 φ f'c Ag [1 - (k lc/32h)²]",
                        "empirical",
                        extra=("informative",),
                    ),
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
                    named("Least thickness, empirical method", "empiricalThickness"),
                    least,
                    t,
                    "mm",
                    note="1/25 of the shorter of the supported height and length, >= 100 mm",
                )
            )
            out.checks[-1]["flag"] = True
    out.checks.append(_row(named("Least thickness", "thickness"), 100.0, t, "mm"))

    # Boundary elements (8.3.6.6).
    boundary = None
    if special:
        boundary = boundary_need(geometry, section, forces, fc, fyt, bars, drift, pier)
        out.checks += _boundary_rows(boundary, bars, geometry, fc)
        if drift is None:
            out.notes.append(
                "δu/hw not given: boundary elements by the stress method of 8.3.6.6(c)"
            )
        if vu >= special_limit("relaxedShare") * acv * lam * root and not boundary.required:
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
        pier=wall_pier,
    )
    if _pack_walls():
        # Alpha 9 C5b: the pack's wall steel, in-plane shear and ductile wall rows
        # (saengine.design.limit_state_rows) take the place of the parent pack's.
        from saengine.design import limit_state_rows

        out.checks = limit_state_rows.wall_rows(
            out.checks, geometry, bars, forces, fc, fy, ductility
        )
        # Alpha 9 C5c: out of the plane by the pack's wall method (limit_state_members).
        from saengine.design import limit_state_members

        if limit_state_members.wall_slenderness_rules() is not None:
            out.checks = limit_state_members.wall_out_of_plane_rows(
                out.checks, geometry, bars, forces, fc, fy, es
            )
            out.notes = [n for n in out.notes if not n.startswith("out-of-plane slenderness")]
        if ductility and mu_phi is not None and bars.boundary is not None:
            # Alpha 9 C5c: the confinement of the ductile wall's boundary elements.
            from saengine.design import curvature_ductility

            out.checks += curvature_ductility.wall_confinement_rows(
                bars.boundary,
                geometry.thickness,
                geometry.length,
                bars.cover,
                max((f.P for f in forces), default=0.0),
                fc,
                fy,
                bars.rho_l(geometry.thickness),
                ductility,
                mu_phi,
            )
    if ductile_wall:
        # Alpha 9 C8: the pack's special shear wall rows (IS 13920) in place of Sec 8.3.6's.
        from saengine.design import ductile_detailing

        out.checks += ductile_detailing.wall_rows(geometry, bars, forces, fc)
    settle_informative(out.checks)
    strength = [c for c in out.checks if not c["flag"]]
    out.utilisation = max((c["utilisation"] for c in strength), default=0.0)
    return out


def _pack_walls() -> bool:
    """Alpha 9 C5b: True when the pack in force gives walls its partial-factor methods and
    member steel."""
    from saengine.design import limit_state_rows, method_selection

    return (
        limit_state_rows.partial_factors() and method_selection.concrete("memberSteel") is not None
    )


def settle_informative(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """R3-1: an informative row (``flag``) never says ok=false: the element's ok and
    utilisation are those of its design checks only, so an informative row that is exceeded
    keeps its numbers and says so in its note, ok stays true. Returns ``rows``."""
    for row in rows:
        if row.get("flag") and row.get("ok") is False:
            row["ok"] = True
            text = "informative: exceeded, not a design check of this element"
            if text not in str(row.get("note", "")):
                row["note"] = f"{row['note']}; {text}" if row.get("note") else text
    return rows


def web_strip_check(
    geometry: WallGeometry,
    bars: WallBars,
    forces: list[PierForces],
    fc: float,
    fy: float,
    es: float,
) -> dict[str, Any] | None:
    """R3-1: out-of-plane bending of the web per metre with its axial force per metre (a wall
    designed as a compression member, 6.6.4 by 6.3.2-6.3.3): a 1 m strip of the web, its
    vertical web bars only (the end bars stand at the pier's ends, not under the web's moment),
    the worst combination of M2 / lw against φMn2 at Pu / lw. The pier's P-M3-M2 row sums the
    whole section, end bars included, and so cannot show a web too weak out of its plane.
    None without out-of-plane moment."""
    lw, t = geometry.length, geometry.thickness
    if lw <= 0 or not any(abs(f.M2) > 0 for f in forces):
        return None
    face = t / 2 - bars.cover - bars.horizontal_dia - bars.vertical_dia / 2
    xs = [-face, face] if bars.layers == 2 and face > 0 else [0.0]
    area = bar_area(bars.vertical_dia) * 1000 / bars.vertical_spacing
    strip = PierInteraction(
        RcSection(
            profile=RectangleProfile(xDim=t, yDim=1000.0),
            bars=tuple(Bar(x, 0.0, area, bars.vertical_dia) for x in xs),
            fc=fc,
            fy=fy,
            es=es,
            transverse_dia=bars.horizontal_dia,
        )
    )
    worst = None
    for f in forces:
        if abs(f.M2) <= 0:
            continue
        pu = f.P / lw * 1000
        mu = abs(f.M2) / lw * 1000
        cap = strip.capacity(pu, "M2", 1 if f.M2 >= 0 else -1)
        u = mu / cap if cap > 0 else math.inf
        if worst is None or u > worst[0]:
            worst = (u, f, mu, cap, pu)
    if worst is None:
        return None
    u, f, mu, cap, pu = worst
    layout = f"{len(xs)} x Ø{bars.vertical_dia:g} @ {bars.vertical_spacing:g}" + (
        " at the faces" if len(xs) == 2 else " at mid-thickness"
    )
    return _row(
        named("Out-of-plane bending per metre of web, with its axial force", "compression"),
        mu / 1e6,
        cap / 1e6,
        "kN·m/m",
        f.combination,
        f"Mu = M2 / lw, Pu = {pu / 1e3:.1f} kN/m (P / lw), 1 m strip of the web: {layout}"
        + (f" at {f.where}" if f.where else "")
        + ("" if cap > 0 else "; the strip cannot carry Pu"),
        utilisation=u,
    )


def _shear_reinforced(
    geometry: WallGeometry, forces: list[PierForces], fc: float, lam: float
) -> bool:
    """Some combination has Vu > 0.5 φ Vc (6.4.8.8): the shear reinforcement rules of 6.4.8.9
    then apply instead of the minimums of 6.6.3."""
    return any(
        abs(f.V2) > 0.5 * rc_value("PHI_SHEAR") * wall_vc(geometry, f, fc, lam)[0] for f in forces
    )


def rho_l_eq71(geometry: WallGeometry, rho_t: float, rho_t_required: float) -> float:
    """Least vertical ratio of 6.4.8.9.4 (Eq. 6.6.71): max(0.0025, 0.0025 + 0.5 (2.5 - hw/lw)
    (ρt - 0.0025)) with ρt the horizontal ratio provided (6.4.8.9.2), but not more than the ρt
    required by 6.4.8.9.1 (and 0.0025 of 6.4.8.9.2)."""
    least = steel_limit("rhoShear")
    eq71 = least + 0.5 * (2.5 - geometry.height / geometry.length) * (rho_t - least)
    return max(least, min(eq71, max(rho_t_required, least)))


def _k_factor(geometry: WallGeometry) -> float:
    if not geometry.braced:
        return 2.0
    return 0.8 if geometry.restrained else 1.0


def empirical_capacity(geometry: WallGeometry, fc: float) -> float:
    """φPn [N] of Eq. 6.6.89, φ = 0.65 (compression-controlled, 6.2.3.2.2)."""
    k = _k_factor(geometry)
    ratio = k * geometry.clear_height / (32 * geometry.thickness)
    return 0.55 * rc_value("PHI_TIED") * fc * geometry.gross_area * max(0.0, 1 - ratio**2)


def _rho_t_shear(
    geometry: WallGeometry, forces: list[PierForces], fc: float, fy: float, lam: float
) -> float:
    """ρt the in-plane shear needs (6.4.8.9.1): (Vu/φ - Vc) s / (fy d) per h s."""
    h, d = geometry.thickness, 0.8 * geometry.length
    need = 0.0
    for f in forces:
        vc, _ = wall_vc(geometry, f, fc, lam)
        vs = max(abs(f.V2) / rc_value("PHI_SHEAR") - vc, 0.0)
        need = max(need, vs / (min(fy, rc_value("FYT_SHEAR_MAX")) * d * h))
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
        required = stress > special_limit("stressRequired") * fc
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
            hx = special_limit("hxMax")
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


def _midheight(forces: list[PierForces]) -> list[PierForces]:
    """The rows at the pier's midheight (``where`` ending in "middle"); all rows when none is
    marked (forces given per combination only)."""
    middle = [f for f in forces if f.where.split(" ")[-1] == "middle"]
    return middle or list(forces)


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
    hx_max = special_limit("hxMax")
    step = spacing_step()
    for dh in bar_sizes("hoop"):
        across = max(2, math.ceil(bc_len / hx_max - 1e-9) + 1)
        along = max(2, math.ceil(bc_t / hx_max - 1e-9) + 1)
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
        s = max(round_down(s, step), 50.0)
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
                named(
                    f"Boundary elements: c >= lw / 600({_drift_times()}δu/hw)",
                    "boundaryDisplacement",
                ),
                need.c,
                need.trigger if need.trigger is not None else need.c,
                "mm",
                note=f"largest c = {need.c:.0f} mm against lw / ({trigger_text()}) = "
                + (f"{need.trigger:.0f} mm" if need.trigger is not None else "?")
                + f": {state}",
                utilisation=0.0,
            )
        )
    else:
        rows.append(
            _row(
                named("Boundary elements: extreme fibre stress > 0.2 f'c", "boundaryStress"),
                need.stress,
                special_limit("stressRequired") * fc,
                "MPa",
                note=f"{state}; may stop where the stress is below 0.15 f'c = "
                f"{special_limit('stressStop') * fc:.1f} MPa",
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
                        named("End ties where ρ at the boundary > 2.8/fy", "endTies"),
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
                        named(
                            "End tie spacing <= 200 mm where ρ at the boundary > 2.8/fy", "endTies"
                        ),
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
                named("Boundary element provided", "boundaryProvided"),
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
            named("Boundary element length >= max(c - 0.1 lw, c/2)", "boundaryLength"),
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
                named("Boundary hoops provided", "boundaryHoops"),
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
            named("Boundary hoop spacing", "boundaryHoopSpacing"),
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
                named(f"Boundary Ash, bc {what}", "boundaryAsh"),
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
    rows.append(
        _row(named("Boundary hoop legs hx <= 350 mm", "hx"), hx, special_limit("hxMax"), "mm")
    )
    return rows


# ─────────────────────────────────────── design mode ───────────────────────────────────────


def wall_need(
    geometry: WallGeometry,
    forces: list[PierForces],
    fc: float,
    fy: float,
    es: float | None = None,
    *,
    lam: float = 1.0,
    special: bool = False,
    drift: float | None = None,
    fyt: float | None = None,
    bars: WallBars | None = None,
    boundary: BoundaryNeed | None = None,
    cover: float = 25.0,
    search: bool = False,
    pier: WallPier | None = None,
) -> WallNeed:
    """The reinforcement a wall needs: ρl, ρt, the largest spacings, the layers, a mesh per face
    (:func:`saengine.design.bars.mesh_for`, Ø10-Ø20, >= 100 mm apart) and, for special walls,
    the boundary elements. ``search``: also look for the end bars the P-M checks need."""
    if es is None:
        es = rc_value("STEEL_E")
    if special:
        # C2: the pack's design shear of special walls (none in the default pack).
        forces = amplified(forces, shear_amplification(geometry)[0])
    t, lw = geometry.thickness, geometry.length
    acv = geometry.gross_area
    root = math.sqrt(fc)
    fyt = fy if fyt is None else fyt
    vu = max((abs(f.V2) for f in forces), default=0.0)
    notes: list[str] = []
    cover = bars.cover if bars else cover
    layers = 2 if (t > steel_limit("twoLayerThickness") and not geometry.basement) else 1
    if special and (
        vu > special_limit("twoCurtainShare") * acv * lam * root or two_curtains_by_aspect(geometry)
    ):
        layers = 2
    if bars is not None:
        layers = max(layers, bars.layers)
    s_max = steel_limit("spacingMax")
    s_v = s_h = min(3 * t, s_max)
    if _pack_walls():  # Alpha 9 C5b: the pack's spacings
        from saengine.design import limit_state_rows

        m = limit_state_rows._table().memberSteel
        s_v = min(m.wallVerticalSpacing[0] * t, m.wallVerticalSpacing[1], s_v)
        s_h = min(m.wallHorizontalSpacing, s_h)
    base_l = base_t = 0.0
    eq71 = False
    if special:
        if vu > special_limit("relaxedShare") * acv * lam * root:
            base_l = base_t = steel_limit("rhoShear")
        # Vu <= φ Acv (αc λ √f'c + ρt fy) with φ = 0.60 (6.2.3.3(a)): the check takes 0.75
        # where Vn reaches the shear at Mn; the proposal does not rely on it.
        sv_need = vu / wall_phi("shearSeismic") / acv - alpha_c(geometry.aspect) * lam * root
        sv_need = max(sv_need, 0.0) / min(fy, rc_value("FYT_SHEAR_MAX"))
        notes.append("ρt for shear with φ = 0.60 (6.2.3.3(a)), on the safe side")
    else:
        sv_need = _rho_t_shear(geometry, forces, fc, fy, lam)
        vmax = rc_value("PHI_SHEAR") * 0.83 * root * t * 0.8 * lw
        if vu > vmax:
            notes.append(
                f"Vu = {_kn(vu):.0f} kN above φ 0.83 √f'c h d = {_kn(vmax):.0f} kN (6.4.8.3): "
                "the wall is too thin or short"
            )
        if _shear_reinforced(geometry, forces, fc, lam):
            base_t = steel_limit("rhoShear")
            eq71 = True  # Eq. 6.6.71 with the ρt of the proposed horizontal mesh, below
            s_h = min(lw / 5, 3 * t, s_max)
            s_v = min(lw / 3, 3 * t, s_max)

    sizes = bar_sizes("wall")

    def per_face(rho_of) -> dict[float, float]:
        return {dia: rho_of(dia) * t * 1000 / layers for dia in sizes}

    def rho_horizontal(dia: float) -> float:
        return max(minimum_ratios(dia, dia, fy)[1], base_t, sv_need)

    horizontal = mesh_for(0.0, s_h, sizes, MIN_WALL_SPACING, per_face(rho_horizontal))
    rho_t = (
        layers * bar_area(horizontal.dia) / (t * horizontal.spacing)
        if horizontal
        else rho_horizontal(steel_limit("smallBarMax"))
    )
    floor = rho_t if special and geometry.aspect <= 2.0 else 0.0
    if floor:
        notes.append("8.3.6.4(c): ρl >= ρt (hw/lw <= 2.0)")
    if eq71:
        base_l = rho_l_eq71(geometry, rho_t, sv_need)

    def rho_vertical(dia: float) -> float:
        return max(minimum_ratios(dia, dia, fy)[0], base_l, floor)

    vertical = mesh_for(0.0, s_v, sizes, MIN_WALL_SPACING, per_face(rho_vertical))
    rho_l = (
        layers * bar_area(vertical.dia) / (t * vertical.spacing)
        if vertical
        else rho_vertical(steel_limit("smallBarMax"))
    )
    if horizontal is None or vertical is None:
        notes.append("no mesh of Ø10-Ø20 at >= 100 mm apart carries it: the wall is too thin")
    vmax_special = wall_phi("shearSeismic") * 0.83 * acv * root
    if special and vu > vmax_special:
        notes.append(
            f"Vu = {_kn(vu):.0f} kN above φ 0.83 Acw √f'c = "
            f"{_kn(vmax_special):.0f} kN: the wall is too thin or short"
        )
    end_bars = None
    web = None
    if vertical is not None and horizontal is not None:
        web = WallBars(
            cover, vertical.dia, vertical.spacing, horizontal.dia, horizontal.spacing, layers
        )
    pier_hoop = None
    if special and pier is not None and pier_kind(lw, t, pier.clear_height) != "wall":
        drift = None  # 8.3.6.8(a)(vi): boundary elements by 8.3.6.6(c)
        if web is not None:
            try:
                pier_hoop = propose_pier_hoops(
                    geometry, web, forces, fc, fy, es, pier, lam=lam, fyt=fyt
                )
            except DesignError as error:
                notes.append(f"wall pier hoops not found: {error}")
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
        pier_hoop,
    )


def end_ratio_row(b: Boundary, t: float) -> dict[str, Any]:
    """R3-2: the end bars' ratio over the end zone (count x area / (length x t)) against the
    pack's largest ratio of a compression member (``concrete.columnRho``; the default pack: 0.08,
    Part 6 Sec 6.3.8.1, walls being designed as compression members by 6.6.4)."""
    high = column_rho()[1]
    rho = b.count * bar_area(b.dia) / (b.length * t) if b.length > 0 and t > 0 else math.inf
    return _row(
        named(f"End bars over the end zone, ρ <= {100 * high:g} %", "endBars"),
        100 * rho,
        100 * high,
        "%",
        note=f"{b.count} Ø{b.dia:g} over {b.length:g} x {t:g} mm",
    )


def end_zone_length(count: int, dia: float, t: float) -> float:
    """R3-2: the least end-zone length [mm] that keeps ``count`` bars of ``dia`` within the
    largest ratio of a compression member (:func:`end_ratio_row`), rounded up to 50 mm."""
    high = column_rho()[1]
    if high <= 0 or t <= 0:
        return 0.0
    length = count * bar_area(dia) / (high * t)
    return math.ceil(length / LENGTH_STEP - 1e-9) * LENGTH_STEP


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
        ((n, d) for n in (4, 6, 8, 10, 12) for d in bar_sizes("boundary")),
        key=lambda o: (o[0] * bar_area(o[1]), o[1]),
    )
    for n, d in options:
        length = max(
            boundary.length if required and boundary else 0.0,
            end_length(n, d, web.cover),
            end_zone_length(n, d, geometry.thickness),
        )
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


# ─────────────────────────────────────── wall piers ───────────────────────────────────────


@dataclass(frozen=True)
class WallPier:
    """Where a pier of a special wall stands beside its openings (8.3.6.8): ``clear_height``
    the height of the openings beside it (the taller); ``edge``: at an end of the wall
    (8.3.6.8(b)); ``above``, ``below``: the depth of the wall in the storey above and below its
    clear height [mm]; ``omega``: Ω0 of the system (the design shear need not exceed Ω0 times
    the analysis shear, 8.3.6.8(a)(i)); None: not capped."""

    clear_height: float
    edge: bool = False
    above: float = 0.0
    below: float = 0.0
    omega: float | None = None


def pier_kind(lw: float, bw: float, clear_height: float) -> str:
    """ "wall": not a wall pier (lw/bw above the pack's pierLengthRatioMax, or the clear
    height below pierHeightRatioMin lw); "column": a wall pier the column rules of 8.3.5
    design (lw/bw at most pierAlternativeRatio); "pier": a wall pier that may take the
    alternative of 8.3.6.8(a)(i)-(vi)."""
    if bw <= 0 or lw <= 0:
        return "wall"
    if lw / bw > special_limit("pierLengthRatioMax") + 1e-9:
        return "wall"
    if clear_height / lw < special_limit("pierHeightRatioMin") - 1e-9:
        return "wall"
    return "column" if lw / bw <= special_limit("pierAlternativeRatio") + 1e-9 else "pier"


def pier_segments(
    length: float, height: float, openings: Iterable[Any], min_opening: float | None = None
) -> list[dict[str, Any]]:
    """The piers of a wall ``length`` by ``height`` between its openings (``offset``, ``width``,
    ``sill``, ``height`` from the wall's start and bottom; those reaching over less than
    ``min_opening`` of the height do not split it, as :mod:`saengine.design.wall_forces`):
    ``{start, end, lw, clear, edge, above, below, bounded}`` with ``clear`` the height of the
    taller opening beside it, ``above``/``below`` the wall over and under that opening and
    ``bounded`` whether an opening is beside it (else the whole wall, not a pier)."""
    if min_opening is None:
        from saengine.design.wall_forces import MIN_OPENING

        min_opening = MIN_OPENING
    cuts = []
    for w in openings:
        start = max(float(_get(w, "offset")), 0.0)
        end = min(float(_get(w, "offset")) + float(_get(w, "width")), length)
        sill = max(float(_get(w, "sill", 0.0) or 0.0), 0.0)
        head = min(sill + float(_get(w, "height")), height)
        if end <= start or head - sill < min_opening * height - 1e-6:
            continue
        cuts.append((start, end, sill, head))
    cuts.sort()
    out: list[dict[str, Any]] = []
    edges = [0.0]
    for start, end, *_ in cuts:
        edges += [start, end]
    edges.append(length)
    for a, b in zip(edges[::2], edges[1::2], strict=False):
        if b - a <= 1.0:
            continue
        beside = [c for c in cuts if abs(c[1] - a) <= 1.0 or abs(c[0] - b) <= 1.0]
        if beside:
            tall = max(beside, key=lambda c: c[3] - c[2])
            clear, above, below = tall[3] - tall[2], height - tall[3], tall[2]
        else:
            clear, above, below = height, 0.0, 0.0
        out.append(
            {
                "start": a,
                "end": b,
                "lw": b - a,
                "clear": clear,
                "edge": a <= 1.0 or b >= length - 1.0,
                "above": above,
                "below": below,
                "bounded": bool(beside),
            }
        )
    return out


def pier_rho_t(t: float, bars: WallBars) -> float:
    """ρt of a wall pier: the horizontal web bars and its hoops' legs along the length."""
    rho = bars.rho_t(t)
    h = bars.pier_hoop
    if h is not None:
        rho += h.legs_along * bar_area(h.dia) / (t * h.spacing)
    return rho


def pier_design_shear(
    geometry: WallGeometry,
    bars: WallBars,
    forces: list[PierForces],
    fc: float,
    fy: float,
    es: float,
    pier: WallPier,
) -> tuple[float, float, str, str | None]:
    """(Ve, the shear at the nominal moments 2 Mn / hc, how, combination) [N] of a wall pier
    (8.3.6.8(a)(i), by the capacity design of 8.3.8.1): Ve = 2 Mpr / hc with Mpr the probable
    moment (the pack's ``detailing.lintels.probable`` x fy, 1.25 in the default pack, φ = 1)
    at the axial force of the combinations with E giving the largest,
    the clear height hc between the joint faces; at most Ω0 times the largest analysis shear of
    those combinations (when Ω0 is given), at least the largest factored Vu."""
    hc = max(pier.clear_height, 1.0)
    seismic = [f for f in forces if f.earthquake] or list(forces)
    factor = float(code_context.table("detailing").lintels["probable"])  # 1.25 fy (8.3.8.1)
    probable = PierInteraction(pier_section(geometry, bars, fc, factor * fy, es))
    nominal = PierInteraction(pier_section(geometry, bars, fc, fy, es))
    mpr = mn = 0.0
    case = None
    for f in seismic:
        for sense in (1, -1):
            m = probable.nominal(f.P, "M3", sense)[0]
            if m > mpr:
                mpr, case = m, f.combination
            mn = max(mn, nominal.nominal(f.P, "M3", sense)[0])
    ve = 2 * mpr / hc
    how = f"2 Mpr / hc = 2 x {_knm(mpr):.1f} / {hc / 1e3:.2f} m"
    vu_e = max((abs(f.V2) for f in seismic), default=0.0)
    if pier.omega:
        cap = pier.omega * vu_e
        if cap < ve:
            ve, how = cap, f"Ω0 Vu = {pier.omega:g} x {_kn(vu_e):.1f} kN (below {how})"
    vu = max((abs(f.V2) for f in forces), default=0.0)
    if vu > ve:
        ve, how = vu, f"the factored Vu (above {how})"
    return ve, 2 * mn / hc, how, case


def pier_hoop_limits(
    geometry: WallGeometry, bars: WallBars, kind: str, fc: float, fyt: float
) -> dict[str, Any]:
    """What a wall pier's hoops must meet: ``spacing`` the largest vertical spacing and, for
    the column rules, ``ash`` (Ash/s along the length and across the thickness, mm²/mm) and
    ``hx`` of the legs entered (the pier's core to the outside of the hoops)."""
    from saengine.design.ductile_members import ash_per_spacing

    t, lw = geometry.thickness, geometry.length
    if kind != "column":
        return {"spacing": special_limit("pierHoopSpacingMax"), "rule": "pier"}
    cover = bars.cover
    bc_len, bc_t = lw - 2 * cover, t - 2 * cover
    ag, ach = lw * t, max(bc_len, 1.0) * max(bc_t, 1.0)
    h = bars.pier_hoop
    db = bars.vertical_dia
    if h is not None:
        hx = max(
            (bc_len - 2 * h.dia - db) / max(h.legs_across - 1, 1),
            (bc_t - 2 * h.dia - db) / max(h.legs_along - 1, 1),
        )
    else:
        hx = special_limit("hxMax")
    so = so_special(hx)
    return {
        "spacing": min(min(t, lw) / 4, 6 * db, so),
        "rule": f"min(least dimension/4, 6 db, so), so = {so:.0f} mm",
        "ash": (ash_per_spacing(bc_len, ag, ach, fc, fyt), ash_per_spacing(bc_t, ag, ach, fc, fyt)),
        "hx": hx,
    }


def pier_shear_capacity(
    geometry: WallGeometry, bars: WallBars, kind: str, fc: float, fy: float, lam: float = 1.0
) -> tuple[float, str]:
    """(Vn, how) [N] of a wall pier: the alternative by 8.3.6.4 (Eq. 6.8.9 with αc for its
    clear height and ρt of its web bars and hoops, at most 0.83 Acw √f'c); the column rules
    by the hoops and the web's horizontal bars alone (Vc taken as 0 on the safe side), d =
    0.8 lw."""
    t, lw = geometry.thickness, geometry.length
    fy_v = min(fy, rc_value("FYT_SHEAR_MAX"))
    rho = pier_rho_t(t, bars)
    if kind == "column":
        vs = rho * t * fy_v * 0.8 * lw
        return vs, f"Vs = ρt fy t d = {_kn(vs):.1f} kN, d = 0.8 lw, Vc = 0"
    a = alpha_c(geometry.clear_height / lw)
    vn = lw * t * (a * lam * math.sqrt(fc) + rho * fy_v)
    vmax = 0.83 * lw * t * math.sqrt(fc)
    return min(vn, vmax), (
        f"Vn = Acv (αc λ √f'c + ρt fy), αc = {a:.2f}, ρt = {100 * rho:.3f} % (web and hoops), "
        f"<= 0.83 Acw √f'c = {_kn(vmax):.1f} kN"
    )


def wall_pier_rows(
    geometry: WallGeometry,
    bars: WallBars,
    forces: list[PierForces],
    fc: float,
    fy: float,
    es: float,
    pier: WallPier,
    *,
    lam: float = 1.0,
    fyt: float | None = None,
) -> tuple[list[dict[str, Any]], list[str], str]:
    """The checks of a wall pier (8.3.6.8): (rows, notes, kind of :func:`pier_kind`). The
    column rules (lw/bw at most the pack's pierAlternativeRatio): the vertical steel ratio of
    8.3.5.3(a), hoops of 8.3.5.4 over the clear height (Ash, spacing, hx) and the
    capacity-design shear; otherwise the alternative (i)-(v): the capacity-design shear (i)
    against Vn of 8.3.6.4 (ii), hoops (iii) at most 150 mm apart (iv), extended 300 mm above and
    below the clear height (v, in the bill and the bar schedule), the boundary elements by
    8.3.6.6(c) (vi, :func:`wall_checks`). At an edge of the wall, (b): the horizontal bars of
    the wall above and below the clear height (within lw of it) carry Ve."""
    t, lw = geometry.thickness, geometry.length
    fyt = fy if fyt is None else fyt
    kind = pier_kind(lw, t, pier.clear_height)
    if kind == "wall":
        return [], [], kind
    rows: list[dict[str, Any]] = []
    notes = [
        f"a wall pier: lw/bw = {lw / t:.2f} <= {special_limit('pierLengthRatioMax'):g} and clear "
        f"height / lw = {pier.clear_height:.0f} / {lw:.0f} = {pier.clear_height / lw:.2f} >= "
        f"{special_limit('pierHeightRatioMin'):g}: "
        + (
            "the column rules"
            if kind == "column"
            else f"the alternative to the column rules (lw/bw > "
            f"{special_limit('pierAlternativeRatio'):g})"
        )
        + f" ({ref('pier') or 'wall piers'}); boundary elements by the stress method"
    ]
    ve, v_mn, how, case = pier_design_shear(geometry, bars, forces, fc, fy, es, pier)
    vn, vn_how = pier_shear_capacity(geometry, bars, kind, fc, fy, lam)
    phi = rc_value("PHI_SHEAR")
    if kind == "pier" and vn < v_mn:
        phi = wall_phi("shearSeismic")
    rows.append(
        _row(
            named("Wall pier design shear Ve, capacity design", "pierShear"),
            _kn(ve),
            _kn(phi * vn),
            "kN",
            case,
            f"Ve = {how}; {vn_how}; φ = {phi:.2f}",
        )
    )
    h = bars.pier_hoop
    limits = pier_hoop_limits(geometry, bars, kind, fc, fyt)
    hoops_key = "pierColumnHoops" if kind == "column" else "pierHoops"
    spacing_key = "pierColumnSpacing" if kind == "column" else "pierSpacing"
    if h is None:
        rows.append(
            _row(
                named("Wall pier hoops provided", hoops_key),
                limits["spacing"],
                0.0,
                "mm",
                note=f"hoops at <= {limits['spacing']:.0f} mm over the clear height and "
                f"{special_limit('pierHoopExtension'):g} mm above and below needed; the wall "
                "type has no wall pier hoops entered",
            )
        )
    else:
        rows.append(
            _row(
                named("Wall pier hoop spacing", spacing_key),
                h.spacing,
                limits["spacing"],
                "mm",
                note=f"Ø{h.dia:g} @ {h.spacing:g}"
                + (f"; {limits['rule']}" if kind == "column" else ""),
            )
        )
        if kind == "column":
            for k, (what, legs) in enumerate(
                (("along the length", h.legs_across), ("across the thickness", h.legs_along))
            ):
                rows.append(
                    _row(
                        named(f"Wall pier Ash, bc {what}", hoops_key),
                        limits["ash"][k] * h.spacing,
                        legs * bar_area(h.dia),
                        "mm²",
                        note=f"{legs} legs Ø{h.dia:g} @ {h.spacing:g}; the larger of Eq. 6.8.7 "
                        "and 6.8.8",
                    )
                )
            rows.append(
                _row(
                    named("Wall pier hoop legs hx <= 350 mm", "hx"),
                    limits["hx"],
                    special_limit("hxMax"),
                    "mm",
                )
            )
        notes.append(
            f"wall pier hoops over the clear height {pier.clear_height:.0f} mm and at least "
            f"{special_limit('pierHoopExtension'):g} mm above and below it"
            + (
                "; with one curtain, single-leg horizontal bars with 180° bends at each end "
                "engaging the pier's boundary bars may serve instead"
                if bars.layers == 1 and kind == "pier"
                else ""
            )
        )
    if kind == "column":
        section = pier_section(geometry, bars, fc, fy, es)
        from saengine.design.ductile_members import _column_rho

        low, high = _column_rho()
        rho = section.steel_area / section.gross_area
        rows.append(
            _row(
                named("Wall pier as a column: least steel ratio", "pierColumnBars"),
                100 * low,
                100 * rho,
                "%",
            )
        )
        rows.append(
            _row(
                named("Wall pier as a column: largest steel ratio", "pierColumnBars"),
                100 * rho,
                100 * high,
                "%",
            )
        )
    if pier.edge:
        reach = [min(d, lw) for d in (pier.above, pier.below) if d > 1.0]
        area = sum(
            bars.layers * bars_down(d, bars.horizontal_spacing) * bar_area(bars.horizontal_dia)
            for d in reach
        )
        fy_t = min(fy, rc_value("FYT_SHEAR_MAX"))
        phi_t = rc_value("PHI_SHEAR")
        rows.append(
            _row(
                named("Edge wall pier: horizontal bars above and below carry Ve", "pierEdge"),
                _kn(ve),
                _kn(phi_t * area * fy_t),
                "kN",
                case,
                f"{bars.layers} x Ø{bars.horizontal_dia:g} @ {bars.horizontal_spacing:g} within "
                + (
                    " and ".join(f"{d:.0f} mm" for d in reach)
                    if reach
                    else "no wall above or below the clear height in the storey"
                )
                + f"; φ As fy, φ = {phi_t:.2f}; the bars run on past the pier into the wall",
            )
        )
        if not reach:
            rows[-1]["flag"] = True
            rows[-1]["note"] += " (the floor or foundation takes it: informative)"
    return rows, notes, kind


def propose_pier_hoops(
    geometry: WallGeometry,
    bars: WallBars,
    forces: list[PierForces],
    fc: float,
    fy: float,
    es: float,
    pier: WallPier,
    *,
    lam: float = 1.0,
    fyt: float | None = None,
) -> CouplingHoops | None:
    """The hoops of a wall pier (None when it is not one): per hoop diameter the fewest legs
    (the column rules: hx <= 350 mm, more while Ash allows a spacing below 75 mm; the
    alternative: a closed hoop, two legs each way), the spacing the least of the rules' and
    what the capacity-design shear needs, rounded down to the spacing step; the lightest."""
    t, lw = geometry.thickness, geometry.length
    fyt = fy if fyt is None else fyt
    kind = pier_kind(lw, t, pier.clear_height)
    if kind == "wall":
        return None
    ve = pier_design_shear(geometry, bars, forces, fc, fy, es, pier)[0]
    step = spacing_step()
    best: tuple[float, CouplingHoops] | None = None
    bc_len, bc_t = lw - 2 * bars.cover, t - 2 * bars.cover
    for dh in bar_sizes("hoop"):
        across = along = 2
        if kind == "column":
            across = max(2, math.ceil(bc_len / special_limit("hxMax") - 1e-9) + 1)
            along = max(2, math.ceil(bc_t / special_limit("hxMax") - 1e-9) + 1)
        for _ in range(12):
            trial = replace(bars, pier_hoop=CouplingHoops(dh, 1000.0, across, along))
            limits = pier_hoop_limits(geometry, trial, kind, fc, fyt)
            s = limits["spacing"]
            if kind == "column":
                need_len, need_t = limits["ash"]
                s = min(s, across * bar_area(dh) / need_len, along * bar_area(dh) / need_t)
                if s < 75.0:
                    if across * bar_area(dh) / need_len <= along * bar_area(dh) / need_t:
                        across += 1
                    else:
                        along += 1
                    continue
            break
        s = max(round_down(s, step), 50.0)
        # The capacity-design shear: closer hoops while φVn < Ve.
        while s > 50.0:
            trial = replace(bars, pier_hoop=CouplingHoops(dh, s, across, along))
            vn = pier_shear_capacity(geometry, trial, kind, fc, fy, lam)[0]
            if wall_phi("shearSeismic") * vn >= ve:
                break
            s = max(s - step, 50.0)
        weight = (across * bc_t + along * bc_len) * bar_area(dh) / s
        if best is None or weight < best[0] - 1e-9:
            best = (weight, CouplingHoops(dh, s, across, along))
    return best[1] if best else None


# ─────────────────────────────────────── coupling beams ───────────────────────────────────────


@dataclass(frozen=True)
class Diagonal:
    """One of the two groups of diagonal bars of a coupling beam."""

    count: int
    dia: float
    edge: float = 0.0  # centroid of the group from the beam face at the wall face [mm]
    angle: float | None = None  # α [rad]; None: from the depth, edge and span
    hoop: CouplingHoops | None = None  # over the whole section (8.3.6.7(d)(iv)); None: none
    group_hoop: GroupHoops | None = None  # around each group (8.3.6.7(d)(iii)); None: none
    # Longitudinal bars along each face (dia, spacing down the depth); None: the web's bars.
    longitudinal: tuple[float, float] | None = None

    def area(self) -> float:
        return self.count * bar_area(self.dia)


@dataclass(frozen=True)
class GroupHoops:
    """Hoops around each group of diagonal bars (8.3.6.7(d)(iii)): out-to-out ``width``
    parallel to the wall's thickness and ``depth`` along the other sides (None: from the wall's
    curtains and the group's bars)."""

    dia: float
    spacing: float
    width: float | None = None
    depth: float | None = None


@dataclass(frozen=True)
class CouplingHoops:
    """Hoops and crossties over a diagonally reinforced coupling beam's whole section
    (8.3.6.7(d)(iv)): ``legs_across`` legs across the thickness, counted down the depth;
    ``legs_along`` legs along the depth (vertical), counted across the thickness."""

    dia: float
    spacing: float
    legs_across: int = 2
    legs_along: int = 2


def coupling_hoop_need(
    h: float, bw: float, cover: float, fc: float, fyt: float, db: float
) -> tuple[float, float, float, float]:
    """(largest spacing along the beam, largest leg spacing, Ash/s down the depth, Ash/s
    across the width) [mm, mm, mm²/mm] of the hoops over a diagonally reinforced coupling
    beam's whole section (8.3.6.7(d)(iv) with 8.3.5.4: the larger of Eq. 6.8.7 and 6.8.8, the
    core to the outside of the hoops)."""
    from saengine.design.ductile_members import ash_per_spacing

    depth, width = h - 2 * cover, bw - 2 * cover
    ag, ach = bw * h, max(depth, 1.0) * max(width, 1.0)
    s_max = min(special_limit("couplingHoopSpacingMax"), special_limit("couplingHoopDb") * db)
    return (
        s_max,
        special_limit("couplingLegSpacingMax"),
        ash_per_spacing(depth, ag, ach, fc, fyt),
        ash_per_spacing(width, ag, ach, fc, fyt),
    )


def propose_coupling_hoops(
    h: float, bw: float, cover: float, fc: float, fyt: float, db: float
) -> CouplingHoops:
    """The hoops over a coupling beam ``h`` deep and ``bw`` wide with diagonal bars of
    ``db``: per hoop diameter the fewest legs each way at most the leg spacing apart, more while
    Ash allows a spacing below 75 mm, the spacing the least of Ash's and the limit along the
    beam rounded down to the spacing step; the diameter with the least steel per metre."""
    s_max, legs_max, need_depth, need_width = coupling_hoop_need(h, bw, cover, fc, fyt, db)
    depth, width = h - 2 * cover, bw - 2 * cover
    step = spacing_step()
    best: tuple[float, CouplingHoops] | None = None
    for dh in bar_sizes("hoop"):
        across = max(2, math.ceil(depth / legs_max - 1e-9) + 1)
        along = max(2, math.ceil(width / legs_max - 1e-9) + 1)
        while across * bar_area(dh) / need_depth < 75.0:
            across += 1
        while along * bar_area(dh) / need_width < 75.0:
            along += 1
        s = min(s_max, across * bar_area(dh) / need_depth, along * bar_area(dh) / need_width)
        s = max(round_down(s, step), 50.0)
        weight = (across * width + along * depth) * bar_area(dh) / s
        if best is None or weight < best[0] - 1e-9:
            best = (weight, CouplingHoops(dh, s, across, along))
    assert best is not None
    return best[1]


def coupling_hoop_rows(
    hoop: CouplingHoops | None,
    h: float,
    bw: float,
    cover: float,
    fc: float,
    fyt: float,
    db: float,
) -> list[dict[str, Any]]:
    """The rows of the hoops over a diagonally reinforced coupling beam (8.3.6.7(d)(iv))."""
    s_max, legs_max, need_depth, need_width = coupling_hoop_need(h, bw, cover, fc, fyt, db)
    if hoop is None:
        return [
            _row(
                named("Coupling beam hoops provided", "couplingTransverse"),
                s_max,
                0.0,
                "mm",
                note=f"hoops over the whole section at <= {s_max:.0f} mm, or hoops around each "
                "group of diagonal bars, needed; the wall type's diagonal bars have no hoops "
                "entered",
            )
        ]
    depth, width = h - 2 * cover, bw - 2 * cover
    leg = max(depth / max(hoop.legs_across - 1, 1), width / max(hoop.legs_along - 1, 1))
    rows = [
        _row(
            named("Coupling beam hoop spacing", "couplingHoops"),
            hoop.spacing,
            s_max,
            "mm",
            note=f"Ø{hoop.dia:g} @ {hoop.spacing:g}; min("
            f"{special_limit('couplingHoopSpacingMax'):g} mm, "
            f"{special_limit('couplingHoopDb'):g} db) with db = Ø{db:g}",
        ),
        _row(
            named("Coupling beam hoop legs and crossties apart", "couplingHoops"),
            leg,
            legs_max,
            "mm",
            note=f"{hoop.legs_across} legs across down {depth:.0f} mm, {hoop.legs_along} along "
            f"over {width:.0f} mm",
        ),
    ]
    for what, legs, need in (
        ("down the depth", hoop.legs_across, need_depth),
        ("across the width", hoop.legs_along, need_width),
    ):
        rows.append(
            _row(
                named(f"Coupling beam Ash, bc {what}", "couplingAsh"),
                need * hoop.spacing,
                legs * bar_area(hoop.dia),
                "mm²",
                note=f"{legs} legs Ø{hoop.dia:g} @ {hoop.spacing:g}; the larger of 0.3 s bc f'c / "
                "fyt (Ag/Ach - 1) and 0.09 s bc f'c / fyt",
            )
        )
    return rows


def coupling_longitudinal(
    diagonal: Diagonal, web: WallBars | None
) -> tuple[float, float, int, str]:
    """(diameter, spacing down the depth, faces, what) of a coupling beam's longitudinal bars:
    the type's own (``diagonal.longitudinal``), else the wall's horizontal web bars."""
    layers = web.layers if web is not None else 2
    if diagonal.longitudinal is not None:
        dia, spacing = diagonal.longitudinal
        return dia, spacing, layers, "the coupling beam's longitudinal bars"
    if web is not None:
        return web.horizontal_dia, web.horizontal_spacing, layers, "the wall's horizontal bars"
    return 0.0, math.inf, layers, "no longitudinal bars known"


def bars_down(depth: float, spacing: float) -> int:
    """Bars of one face at ``spacing`` down a core ``depth`` deep (one at each end)."""
    if not math.isfinite(spacing) or spacing <= 0:
        return 0
    return math.floor(max(depth, 0.0) / spacing + 1e-9) + 1


def coupling_engagement_rows(
    hoop: CouplingHoops, diagonal: Diagonal, h: float, cover: float, web: WallBars | None
) -> list[dict[str, Any]]:
    """8.3.6.7(d)(iv): each crosstie and hoop leg engages a longitudinal bar of equal or larger
    diameter: a bar of each face at each leg down the depth, a face of bars at each leg across
    the thickness, and their diameter at least the hoop's."""
    dia, spacing, faces, what = coupling_longitudinal(diagonal, web)
    if dia <= 0:
        return []  # neither the beam's bars nor the wall's web given: a note of the caller
    depth = h - 2 * cover
    count = bars_down(depth, spacing)
    rows = [
        _row(
            named("Coupling beam longitudinal bars, one at each hoop leg", "couplingHoops"),
            hoop.legs_across,
            count,
            "bars",
            note=f"{hoop.legs_across} legs across down {depth:.0f} mm; {what} Ø{dia:g} @ "
            f"{spacing:g}: {count} per face",
        ),
        _row(
            named("Coupling beam longitudinal bar Ø >= the hoop's", "couplingHoops"),
            hoop.dia,
            dia,
            "mm",
            note=what,
        ),
    ]
    if hoop.legs_along > faces:
        rows.append(
            _row(
                named("Coupling beam legs along engage a face of bars", "couplingHoops"),
                hoop.legs_along,
                faces,
                "faces",
                note=f"{hoop.legs_along} legs along across the thickness, {faces} curtain(s)",
            )
        )
    return rows


def group_hoop_size(
    group: GroupHoops, diagonal: Diagonal, bw: float, cover: float, web: WallBars | None
) -> tuple[float, float]:
    """(width parallel to bw, depth) out to out [mm] of the hoops around a group: as entered,
    else the room inside the wall's curtains and two layers of the group's bars."""
    if group.width:
        width = group.width
    elif web is not None:
        width = bw - 2 * (cover + web.horizontal_dia + web.vertical_dia)
    else:
        width = bw - 2 * cover
    db = diagonal.dia
    depth = group.depth or (2 * group.dia + 2 * db + max(25.0, db))
    return width, depth


def coupling_group_rows(
    diagonal: Diagonal,
    h: float,
    bw: float,
    cover: float,
    fc: float,
    fyt: float,
    web: WallBars | None,
) -> list[dict[str, Any]]:
    """8.3.6.7(d)(iii): hoops around each group of diagonal bars (out-to-out at least bw/2 and
    bw/5, Ash of 8.3.5.4 on the group's section with the cover on all four sides, spacing along
    the bars at most min(bw/4, so, 6 db), legs at most 350 mm apart) and the bars around the beam's
    perimeter (at least 0.002 bw s each way, at most 300 mm apart)."""
    from saengine.design.ductile_members import ash_per_spacing

    group = diagonal.group_hoop
    assert group is not None
    db, dh = diagonal.dia, group.dia
    width, depth = group_hoop_size(group, diagonal, bw, cover, web)
    rows = []
    for what, size, share in (
        ("parallel to bw", width, special_limit("couplingGroupWidthShare")),
        ("along the other sides", depth, special_limit("couplingGroupDepthShare")),
    ):
        rows.append(
            _row(
                named(f"Coupling beam group hoops out to out, {what}", "couplingGroup"),
                share * bw,
                size,
                "mm",
                note=f"at least {share:g} bw, bw = {bw:.0f} mm",
            )
        )
    legs = max(width, depth) - 2 * dh
    hx = max(width - 2 * dh - db, depth - 2 * dh - db, 0.0)
    s_max = min(bw / 4, so_special(hx), special_limit("couplingHoopDb") * db)
    rows.append(
        _row(
            named("Coupling beam group hoop spacing along the bars", "couplingGroup"),
            group.spacing,
            s_max,
            "mm",
            note=f"Ø{dh:g} @ {group.spacing:g}; min(bw/4, so, {special_limit('couplingHoopDb'):g} db), "
            f"so = {so_special(hx):.0f} mm, db = Ø{db:g}",
        )
    )
    rows.append(
        _row(
            named("Coupling beam group hoop legs apart", "couplingGroup"),
            legs,
            special_limit("couplingGroupLegSpacingMax"),
            "mm",
            note="two legs each way, perpendicular to the diagonal bars",
        )
    )
    ag = (width + 2 * cover) * (depth + 2 * cover)
    ach = max(width, 1.0) * max(depth, 1.0)
    for what, bc in (("across the width", width), ("across the depth", depth)):
        rows.append(
            _row(
                named(f"Coupling beam group Ash, bc {what}", "couplingGroupAsh"),
                ash_per_spacing(bc, ag, ach, fc, fyt) * group.spacing,
                2 * bar_area(dh),
                "mm²",
                note=f"2 legs Ø{dh:g} @ {group.spacing:g}; Ag with {cover:g} mm cover on all four "
                "sides of the group",
            )
        )
    rows += coupling_perimeter_rows(diagonal, bw, web)
    return rows


def coupling_perimeter_rows(
    diagonal: Diagonal, bw: float, web: WallBars | None
) -> list[dict[str, Any]]:
    """8.3.6.7(d)(iii): longitudinal and transverse bars around the beam's perimeter, area each
    way at least 0.002 bw s and at most 300 mm apart (the longitudinal bars of
    :func:`coupling_longitudinal`, the wall's vertical bars transverse)."""
    ratio, s_max = (
        special_limit("couplingPerimeterRatio"),
        special_limit("couplingPerimeterSpacingMax"),
    )
    dia, spacing, faces, what = coupling_longitudinal(diagonal, web)
    sets = [("longitudinal", dia, spacing, faces, what)]
    if web is not None:
        sets.append(
            (
                "transverse",
                web.vertical_dia,
                web.vertical_spacing,
                web.layers,
                "the wall's vertical bars",
            )
        )
    rows = []
    for kind, d, s, n, source in sets:
        rho = n * bar_area(d) / (bw * s) if d > 0 and math.isfinite(s) else 0.0
        rows.append(
            _row(
                named(f"Coupling beam perimeter bars, {kind}: area / (bw s)", "couplingGroup"),
                100 * ratio,
                100 * rho,
                "%",
                note=f"{source}: {n} x Ø{d:g} @ {s:g}",
            )
        )
        rows.append(
            _row(
                named(f"Coupling beam perimeter bars, {kind} spacing", "couplingGroup"),
                s,
                s_max,
                "mm",
                note=source,
            )
        )
    return rows


def coupling_embedment_row(
    diagonal: Diagonal, alpha: float, piers: Iterable[float], cover: float, fy: float, fc: float
) -> dict[str, Any] | None:
    """8.3.6.7(d)(ii): the diagonal bars embedded into the wall at least 1.25 ld in tension:
    the length along the bar within the narrower of the piers beside the beam, (lw - cover) /
    cos α; None when the piers are not known."""
    from saengine.drawings.detailing import development_tension

    widths = [float(w) for w in piers]
    if not widths:
        return None
    k = special_limit("couplingEmbedment")
    ld = development_tension(diagonal.dia, fy, fc).value
    least = min(widths)
    cos = math.cos(alpha) if alpha < math.pi / 2 else 1e-9
    available = max(least - cover, 0.0) / max(cos, 1e-9)
    return _row(
        named(f"Diagonal bars embedded into the piers >= {k:g} ld", "couplingEmbedment"),
        k * ld,
        available,
        "mm",
        note=f"ld = {ld:.0f} mm for Ø{diagonal.dia:g}; the narrower pier beside the beam "
        f"{least:.0f} mm: ({least:.0f} - {cover:g}) / cos {math.degrees(alpha):.1f}°",
    )


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
    fyt: float | None = None,
    piers: Iterable[float] | None = None,
    web: WallBars | None = None,
) -> CouplingBeam:
    """A coupling beam of special structural walls (8.3.6.7): ``ln`` clear span, ``h`` depth,
    ``bw`` width [mm], ``vu`` the largest factored shear [N]. ``mode`` "flexural": check it as
    a special moment frame beam (``ductile_members.beam_checks``); "either": diagonals or the
    beam rules; "diagonal": diagonal bars required. ``fyt``: the hoops' yield strength (``fy``
    when not given). ``piers``: the lengths of the piers beside it (the diagonal bars'
    embedment, (d)(ii)); ``web``: the wall's web bars (its longitudinal and perimeter bars
    unless the type gives the beam's own)."""
    from saengine.design import ductile_detailing

    if ductile_detailing.rules() is not None:
        # Alpha 9 C8: the pack's coupling beam rule (IS 13920): diagonal bars by τv and ls/D,
        # their strength 2 Asd fyd sin α; the beam rules otherwise (the frame beams' rows).
        from saengine.design import design_strength

        row = ductile_detailing.coupling_row(ln, h, bw, vu, fc, diagonal is not None)
        out = CouplingBeam("diagonal" if row is not None and not row["flag"] else "either")
        if row is not None:
            out.checks.append(row)
        edge = diagonal.edge if diagonal and diagonal.edge else cover + 10.0 + 2 * 20.0
        alpha = diagonal.angle if diagonal and diagonal.angle else math.atan((h - 2 * edge) / ln)
        fyd = design_strength.fyd(fy)
        sin = math.sin(alpha)
        out.avd_required = vu / (2 * fyd * sin) if sin > 0 else math.inf
        if diagonal is not None:
            out.checks.append(
                _row(
                    named("Coupling beam diagonal bars Vu <= 2 Asd fyd sin α", "couplingShear"),
                    _kn(vu), _kn(2 * diagonal.area() * fyd * sin), "kN", combination,
                    f"α = {math.degrees(alpha):.1f}°, fyd = {fyd:.0f} MPa",
                )
            )  # fmt: skip
        return out
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
    phi_d = wall_phi("diagonalCoupling")
    out.avd_required = vu / (phi_d * 2 * fy * sin) if sin > 0 else math.inf
    if mode != "flexural":
        for d in bar_sizes("boundary"):
            n = max(4, 2 * math.ceil(out.avd_required / bar_area(d) / 2))
            if n <= 8:
                out.proposal = Diagonal(n, d, edge, alpha)
                break
    if diagonal is not None and mode != "flexural":
        vn = min(2 * diagonal.area() * fy * sin, vmax)
        out.checks.append(
            _row(
                named(
                    "Coupling beam diagonal bars Vn = 2 Avd fy sin α <= 0.83 Acw √f'c",
                    "couplingShear",
                ),
                _kn(vu),
                _kn(phi_d * vn),
                "kN",
                combination,
                f"{diagonal.count} Ø{diagonal.dia:g} per group, α = {math.degrees(alpha):.1f}°, "
                f"φ = 0.85 (6.2.3.3(c)); 0.83 Acw √f'c = {_kn(vmax):.1f} kN",
            )
        )
        out.checks.append(
            _row(named("Diagonal bars per group", "couplingBars"), 4, diagonal.count, "bars")
        )
        if diagonal.hoop is None and diagonal.group_hoop is not None:
            # (iii): hoops around each group, with bars around the beam's perimeter.
            out.checks += coupling_group_rows(diagonal, h, bw, cover, fc, fyt or fy, web)
            out.notes.append(
                "the group hoops continue through the intersection of the diagonal bars "
                f"({ref('couplingGroup') or 'hoops around each group'})"
            )
        else:
            # (iv): hoops over the whole section (none entered: the failing "provided" row).
            out.checks += coupling_hoop_rows(
                diagonal.hoop, h, bw, cover, fc, fyt or fy, diagonal.dia
            )
            if diagonal.hoop is not None:
                engaged = coupling_engagement_rows(diagonal.hoop, diagonal, h, cover, web)
                out.checks += engaged
                if not engaged:
                    out.notes.append(
                        "each hoop leg and crosstie engages a longitudinal bar of at least its "
                        f"diameter ({ref('couplingHoops') or 'hoops over the section'}): the "
                        "beam's longitudinal bars are not known here"
                    )
        embedment = coupling_embedment_row(diagonal, alpha, piers or (), cover, fy, fc)
        if embedment is not None:
            out.checks.append(embedment)
        else:
            out.notes.append(
                f"diagonal bars embedded at least {special_limit('couplingEmbedment'):g} ld into "
                "the wall: the piers beside the beam are not known here"
            )
    elif mode == "diagonal":
        out.checks.append(
            _row(
                named("Coupling beam diagonal bars required", "couplingRequired"),
                out.avd_required,
                0.0,
                "mm²",
                combination,
                f"Avd >= Vu / (φ 2 fy sin α) per group, α = {math.degrees(alpha):.1f}°",
            )
        )
    return out


# ─────────────────────────── slender walls and walls as grade beams (B33) ───────────────────────────


def wall_methods() -> Any:
    """The pack's ``wallMethods`` table, None when the pack in force does not cover it."""
    pack = code_context.current()
    return pack.table("wallMethods") if pack.has("wallMethods") else None


def method_clause(key: str) -> str:
    """The pack's clause ``key`` of ``wallMethods`` after its edition ("" when none)."""
    table = wall_methods()
    text = (getattr(table, "clauses", None) or {}).get(key) if table is not None else None
    if not text:
        return ""
    # Alpha 9 C5b: an inherited clause is named after the pack that wrote it.
    return code_context.cite("wallMethods", key)


@dataclass(frozen=True)
class SlenderSection:
    """The out-of-plane section of a slender wall at midheight under an axial force:
    the effective tension steel Ase = As + Pu h / (2 fy d) [mm²], the stress block a and the
    neutral axis c [mm], Icr [mm⁴], the nominal moment Mn [N·mm] and εt."""

    ase: float
    a: float
    c: float
    icr: float
    mn: float
    eps_t: float


def slender_section(
    length: float, t: float, d: float, as_: float, pu: float, fc: float, fy: float, es: float,
    ec: float, rules: Any,
) -> SlenderSection:  # fmt: skip
    """The midheight section of a wall ``length`` long and ``t`` thick (Eq 6.6.95 of the
    pack's slender-wall method): Ase = As + (Pu/fy)(t/2d), a = Ase fy / (0.85 f'c lw),
    c = a/β1, Icr = n Ase (d - c)² + lw c³ / 3 with n = Es/Ec not less than
    ``minModularRatio``, Mn = Ase fy (d - a/2)."""
    ase = as_ + max(pu, 0.0) / fy * t / (2 * d)
    a = ase * fy / (0.85 * fc * length)
    c = a / beta1(fc)
    n = max(es / ec, float(rules.minModularRatio))
    icr = n * ase * (d - c) ** 2 + length * c**3 / 3
    mn = ase * fy * (d - a / 2)
    eps_t = rc_value("EPS_CU") * (d - c) / c if c > 0 else math.inf
    return SlenderSection(ase, a, c, icr, mn, eps_t)


def second_order_moment(mua: float, pu: float, lc: float, ec: float, icr: float, rules: Any):
    """Mu = Mua / (1 - 5 Pu lc² / (factor 48 Ec Icr)) (Eq 6.6.94) and Δu = 5 Mu lc² /
    (factor 48 Ec Icr) (Eq 6.6.93); (inf, inf) when the wall buckles (denominator <= 0)."""
    k = 5 * lc**2 / (float(rules.deflectionFactor) * 48 * ec * icr)
    denominator = 1 - pu * k
    if denominator <= 0:
        return math.inf, math.inf
    mu = mua / denominator
    return mu, mu * k


def service_deflection(
    msa: float, ps: float, lc: float, ec: float, ig: float, icr: float, mcr: float, mn: float,
    rules: Any, iterations: int = 50,
) -> tuple[float, float]:  # fmt: skip
    """(Δs [mm], Ma [N·mm]) of a slender wall under service loads, Ma = Msa + Ps Δs by
    iteration (Eqs 6.6.96-6.6.99): Δs = (Ma/Mcr) Δcr up to ``serviceCrackShare`` Mcr, else
    (2/3)Δcr + (Ma - (2/3)Mcr)/(Mn - (2/3)Mcr) (Δn - (2/3)Δcr); Δcr = 5 Mcr lc²/(48 Ec Ig),
    Δn = 5 Mn lc²/(48 Ec Icr)."""
    share = float(rules.serviceCrackShare)
    d_cr = 5 * mcr * lc**2 / (48 * ec * ig)
    d_n = 5 * mn * lc**2 / (48 * ec * icr)
    delta = 0.0
    ma = msa
    for _ in range(iterations):
        ma = msa + ps * delta
        if ma <= share * mcr:
            new = ma / mcr * d_cr
        else:
            span = mn - share * mcr
            new = share * d_cr + ((ma - share * mcr) / span if span > 0 else math.inf) * (
                d_n - share * d_cr
            )
        if not math.isfinite(new) or abs(new - delta) < 1e-6:
            delta = new
            break
        delta = new
    return delta, ma


def slender_wall_checks(
    geometry: WallGeometry,
    bars: WallBars,
    forces: list[PierForces],
    fc: float,
    fy: float,
    es: float,
    lam: float = 1.0,
    service: list[PierForces] | None = None,
    required: bool = False,
) -> list[dict[str, Any]]:
    """The pack's alternative design of slender walls (``wallMethods.slender``, method
    ``midheightMoment``) out of the plane, from the out-of-plane moment M2 and the axial force P
    of each combination (the wall as a simply supported panel lc high, the whole length): the
    axial stress, φMn >= Mcr, tension control and φMn >= Mu with the P-Δ moment; with
    ``service`` forces, the service deflection. ``required``: the rows are checks (the wall is
    slender), else informative. [] when the pack has no such method or there is no M2.

    The method works from the midheight section (the default pack's BNBC 2020 Part 6 Sec
    6.6.8.2.1: the panel simply supported, the largest moment and deflection at midspan; Sec
    6.6.8.2.6 the axial stress and Sec 6.6.8.3 Mua "at midheight"): the forces of the pier's
    middle cut (``where`` ending in "middle") when it has one. The moments at the bottom and top
    cuts are the end moments of the frame the wall is part of (a shear wall's out-of-plane
    bending in double curvature): taken as the midheight moment they made a 6 m shear wall of R2
    fail this alternative method with end bars the P-M surface accepted (R2-1)."""
    from saengine.design.rc_detailing import concrete_modulus

    table = wall_methods()
    rules = getattr(table, "slender", None) if table is not None else None
    forces = _midheight(forces)
    service = _midheight(service) if service else service
    if rules is None or not forces or max(abs(f.M2) for f in forces) <= 0:
        return []
    t, lw, lc = geometry.thickness, geometry.length, geometry.clear_height
    d = t - bars.cover - bars.horizontal_dia - bars.vertical_dia / 2 if bars.layers == 2 else t / 2
    as_ = bar_area(bars.vertical_dia) * lw / bars.vertical_spacing  # one face
    ec, _ = concrete_modulus(fc)
    ig = lw * t**3 / 12
    fr = float(rules.ruptureCoefficient) * lam * _root(fc)
    mcr = fr * ig / (t / 2)
    rows: list[dict[str, Any]] = []
    where = method_clause("slender")
    worst_axial = max(forces, key=lambda f: f.P)
    stress = max(worst_axial.P, 0.0) / (lw * t)
    rows.append(
        _row(
            f"Slender wall: Pu/Ag at midheight ({method_clause('slenderAxial')})",
            stress,
            float(rules.maxAxialShare) * fc,
            "MPa",
            worst_axial.combination,
            f"at most {rules.maxAxialShare:g} f'c for the method of {where}",
        )
    )
    worst: tuple[float, PierForces, float, float, SlenderSection] | None = None
    for f in forces:
        section = slender_section(lw, t, d, as_, f.P, fc, fy, es, ec, rules)
        mu, delta = second_order_moment(abs(f.M2), max(f.P, 0.0), lc, ec, section.icr, rules)
        ratio = mu / (rc_value("PHI_TENSION") * section.mn) if section.mn > 0 else math.inf
        if worst is None or ratio > worst[0]:
            worst = (ratio, f, mu, delta, section)
    assert worst is not None
    ratio, f, mu, delta, section = worst
    rows.append(
        _row(
            f"Slender wall: φMn >= Mu with P-Δ ({method_clause('slenderStrength')})",
            mu / 1e6,
            rc_value("PHI_TENSION") * section.mn / 1e6,
            "kN·m",
            f.combination,
            f"Mua = {abs(f.M2) / 1e6:.1f} kN·m at midheight"
            + (f" ({f.where})" if f.where else "")
            + f", Pu = {max(f.P, 0) / 1e3:.0f} kN, Δu = "
            f"{delta:.1f} mm, Icr = {section.icr / 1e6:.0f}e6 mm⁴, Ase = {section.ase:.0f} mm², "
            f"d = {d:.0f} mm, lc = {lc:.0f} mm",
            utilisation=ratio,
        )
    )
    rows.append(
        _row(
            f"Slender wall: φMn >= Mcr ({method_clause('slenderCracking')})",
            mcr / 1e6,
            rc_value("PHI_TENSION") * section.mn / 1e6,
            "kN·m",
            f.combination,
            f"Mcr = fr Ig / (t/2), fr = {rules.ruptureCoefficient:g} λ √f'c = {fr:.2f} MPa",
        )
    )
    rows.append(
        _row(
            f"Slender wall: tension-controlled ({method_clause('slenderTension')})",
            fy / es + rc_value("EPS_CU"),
            section.eps_t,
            "",
            f.combination,
            f"εt = {section.eps_t:.4f} at least εty + 0.003 (tension-controlled)",
        )
    )
    if service:
        worst_s = None
        for s in service:
            sec = slender_section(lw, t, d, as_, s.P, fc, fy, es, ec, rules)
            delta_s, ma = service_deflection(
                abs(s.M2), max(s.P, 0.0), lc, ec, ig, sec.icr, mcr, sec.mn, rules
            )
            if worst_s is None or delta_s > worst_s[0]:
                worst_s = (delta_s, ma, s)
        assert worst_s is not None
        delta_s, ma, s = worst_s
        rows.append(
            _row(
                f"Slender wall: service deflection ({method_clause('slenderDeflection')})",
                delta_s,
                lc / float(rules.deflectionDivisor),
                "mm",
                s.combination,
                f"Ma = {ma / 1e6:.1f} kN·m with P-Δ by iteration, lc/{rules.deflectionDivisor:g}",
            )
        )
    if not required:
        for row in rows:
            row["flag"] = True
            row["note"] += "; informative: the wall is not slender out of its plane"
    return rows


def grade_beam_checks(
    geometry: WallGeometry,
    grade: Any,
    bars: WallBars,
    forces: list[PierForces],
    fc: float,
    fy: float,
    es: float,
    lam: float = 1.0,
) -> list[dict[str, Any]]:
    """A wall designed as a grade beam (``wallMethods.gradeBeam``, method ``beam``;
    ``grade``: the type's ``GradeBeamWall``): the largest axial force at its cuts spread
    uniformly along the span, w = Pu / lw, simply supported (w ln²/8 sagging) or continuous
    (w ln²/8 also hogging over the supports, conservative), shear w ln / 2; flexure of the
    rectangle t x hw with the bottom (top) bars, shear with the vertical web bars as stirrups.
    The wall's own minimum steel rows stand for the part above grade. [] when the pack has no
    such method."""
    table = wall_methods()
    rules = getattr(table, "gradeBeam", None) if table is not None else None
    if rules is None or grade is None:
        return []
    t, hw = geometry.thickness, geometry.clear_height
    ln = float(grade.span or geometry.length)
    worst = max(forces, key=lambda f: f.P)
    w = max(worst.P, 0.0) / geometry.length  # N/mm
    mu = w * ln**2 / 8
    vu = w * ln / 2
    rows: list[dict[str, Any]] = []
    where = method_clause("gradeBeam")
    for label, count, dia, demand in (
        ("bottom", grade.bottomBars, grade.bottomDia, mu),
        ("top", grade.topBars, grade.topDia, mu if grade.continuous else 0.0),
    ):
        if demand <= 0:
            continue
        d = hw - bars.cover - bars.horizontal_dia - dia / 2
        area = count * bar_area(dia)
        a = area * fy / (0.85 * fc * t)
        phi_mn = rc_value("PHI_TENSION") * area * fy * (d - a / 2) if area > 0 else 0.0
        rows.append(
            _row(
                f"Grade beam wall: flexure, {label} bars ({where})",
                demand / 1e6,
                phi_mn / 1e6,
                "kN·m",
                worst.combination,
                f"{count} Ø{dia:g}, d = {d:.0f} mm; w = Pu/lw = {w:.1f} kN/m over ln = "
                f"{ln:.0f} mm, w ln²/8"
                + (" (also over the supports: continuous)" if label == "top" else ""),
            )
        )
    d = hw - bars.cover - bars.horizontal_dia - grade.bottomDia / 2
    vc = 0.17 * lam * _root(fc) * t * d
    av = bars.layers * bar_area(bars.vertical_dia)
    vs = av * min(fy, rc_value("FYT_SHEAR_MAX")) * d / bars.vertical_spacing
    rows.append(
        _row(
            f"Grade beam wall: shear ({where})",
            vu / 1e3,
            rc_value("PHI_SHEAR") * (vc + vs) / 1e3,
            "kN",
            worst.combination,
            f"Vc = 0.17 λ √f'c t d, Vs = Av fy d / s of the vertical bars ({bars.layers} x "
            f"Ø{bars.vertical_dia:g} @ {bars.vertical_spacing:g}); w ln / 2"
            + ("; ln/h < 4: a deep beam" if ln / hw < 4 else ""),
        )
    )
    if ln / hw < 4:
        rows[-1]["note"] += " (design it by the deep beam rules as well)"
    rows.append(
        _row(
            f"Grade beam wall: above grade ({method_clause('gradeBeamExposed')})",
            0.0,
            1.0,
            "",
            None,
            "the wall's own minimum reinforcement rows apply to the part above grade",
        )
    )
    rows[-1]["flag"] = True
    return rows


def _joint_rows(
    geometry: WallGeometry, bars: WallBars, forces: list[PierForces], fc: float, fy: float
) -> list[dict[str, Any]]:
    """B33 (left by B21): shear friction across the horizontal construction joint at the
    pier's bottom under its own storey shear V2, the vertical bars crossing it
    (:func:`saengine.design.rc_detailing.wall_joint_check`; [] when the pack has no rule)."""
    from types import SimpleNamespace

    from saengine.design.rc_detailing import wall_joint_check

    base = [f for f in forces if f.where.split(" ")[-1] == "bottom"] or forces
    worst = max(base, key=lambda f: abs(f.V2), default=None)
    if worst is None or abs(worst.V2) <= 0:
        return []
    wall_type = SimpleNamespace(
        thickness=geometry.thickness,
        reinforcement=SimpleNamespace(
            layers=bars.layers,
            vertical=SimpleNamespace(dia=bars.vertical_dia, spacing=bars.vertical_spacing),
        ),
    )
    row = wall_joint_check(
        "Construction joint at the pier's bottom (storey shear)",
        abs(worst.V2),
        wall_type,
        geometry.length,
        fc,
        fy,
        worst.combination,
        None
        if bars.boundary is None
        else (bars.boundary.count, bars.boundary.dia, bars.boundary.length),
    )
    if row is None:
        return []
    # R3-1: a design check (shear friction across the joint, the pack's shear-friction clause):
    # the design mode answers it with a heavier vertical web, or dowels the engineer adds.
    row["note"] += "; the vertical web bars crossing the joint (or dowels added across it)"
    return [row]

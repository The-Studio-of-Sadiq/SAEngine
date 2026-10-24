"""Lintels over door and window openings, and the spandrels of reinforced-concrete walls designed
as beams, to BNBC 2020 Part 6 (bnbc-2020-part1.pdf).

**Lintels** (:func:`design_lintel`, :func:`lintels_of`): an RC beam over each opening of 06 BIM
(``additions.wallOpenings``) in a wall that is not a structural concrete wall (masonry infill,
partitions): those openings are not in the analysis model's shells, so the lintel is designed
by hand.

- Span: simply supported over the opening, effective span L = clear width + one bearing (centre
  to centre of bearings of length ``bearing`` at each end, 150 mm unless given). Sec 7.4.3.2
  (p. 1015): lintels bear at least 100 mm on each end, and members supporting masonry deflect
  no more than 1/600 of the clear span under total loads.
- Loads (the arching rule, stated): the masonry above the opening arches over it when the wall
  rises at least the height of the load triangle above the lintel; the lintel then carries the
  masonry within the triangle on its span with sides at ``angle`` (45° unless given; height
  L/2 · tan(angle)), as a triangular load of peak γ t L/2 tan(angle). Where the wall above is
  lower than that, the arch cannot form: the lintel carries all the masonry above it as a
  uniform load and the floor's line load on the wall (``floor_dead``, ``floor_live``; zero
  where a beam over the wall carries the floor, as :func:`lintels_of` finds). Its own weight
  (24 kN/m³ unless the concrete's density is given) is uniform.
- Factored by the gravity strength combinations of the settings (Sec 2.7.3.1, p. 685, as
  :func:`saengine.design.stairs.loads_from_settings` finds them: 1.4D and 1.2D + 1.6L unless the
  settings have others). Mu at midspan = q_t L²/12 + w L²/8, Vu at the bearing = q_t L/4 +
  w L/2 (on the safe side: not at d from the face).
- Flexure with the beam design of :mod:`saengine.design.bars` (the stress block, compression
  bars past the tension-controlled limit, As,min = max(0.25 √f'c, 1.4) bw d / fy or 4/3 of
  the bars required, the bars in one row where they fit); shear with its stirrups (Vc = 0.17
  λ √f'c bw d, at least Av,min, s <= d/2). Two Ø10 hangers on top.
- Deflection (7.4.3.2): immediate, with Ie of Eq. 6.6.1 (p. 900; Mcr = fr Ig / yt, fr = 0.62
  λ √f'c, Eq. 6.6.2-6.6.3), Ec = 4700 √f'c (6.1.7.1), service loads D + L: 5 w L⁴ / 384 Ec Ie
  for the uniform part and q_t L⁴ / 120 Ec Ie for the triangle; long-term deflection is not
  added (a note). The depth of Table 6.6.1 (p. 900: L/16 simply supported, × (0.4 + fy/700))
  is reported for information.
- Sec 7.9.6.3 (p. 1045, masonry in high wind regions, basic wind speed above 200 km/h): spans
  not over 3.5 m and bars at least 600 mm beyond the opening's edges: an informative row and a
  note.

**Spandrels of RC walls** (:func:`spandrel_design`): the wall over an opening between two piers,
with the cut forces of :mod:`saengine.design.wall_forces` (``V2`` across the span, ``M3``
in-plane, at its left, middle and right cuts). Special structural walls: Sec 8.3.6.7 (p. 1105)
classifies it (:func:`saengine.design.walls.coupling_beam_checks`): ln/h > 4 a flexural member
of a special moment frame (8.3.6.7(a); the text's "8.3.7" [sic]: the beam rules are 8.3.4),
whose 8.3.4.1(c), (d) (the width to depth ratio and width) need not be met only "if it can be
shown by analysis that the beam has adequate lateral stability": no such analysis is made, so
they count unless ``lateral_stability=True`` (the engineer has shown it); ln/h < 2 with Vu > 0.33 Acw √f'c diagonal bars
(8.3.6.7(b), checked by the walls module); between, either (8.3.6.7(c)): the beam rules when no
diagonal bars are entered. Designed as a beam: the same top and bottom bars (the moment
reverses) for the largest |M3|, the special moment frame beam rules of
:func:`saengine.design.ductile_members.beam_checks` (ρmin, ρmax 0.025, hoops at min(d/4, 8 db,
24 dh, 300 mm) over 2h), and the capacity-design shear Ve = (Mpr⁺ + Mpr⁻)/ln + the gravity
shear (8.3.8.1(a), p. 1111; Mpr with the bars at 1.25 fy and φ = 1, by the stress block), Vc = 0
where the earthquake shear is at least half of Ve and the axial compression is below Ag f'c / 20
(8.3.8.2(a), p. 1112). Ordinary walls: a beam with the analysis shear (Chapter 6); where ln/h <
4 it is a deep beam, whose strut-and-tie design is not done here: the sectional beam design
is used (a note).

Units: mm, MPa, N, N·mm (kN, kN·m in the check rows).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from saengine.design.bars import (
    STIRRUP_DIAMETERS,
    beam_flexure_need,
    beam_min_area,
    beam_shear_need,
    choose_stirrups,
    face_options,
    round_down,
    with_minimum,
)
from saengine.design.ductile_members import _row
from saengine.design.rc import (
    EPS_CU,
    FYT_SHEAR_MAX,
    PHI_SHEAR,
    STEEL_E,
    Flexure,
    bar_area,
    beta1,
    phi_axial_flexure,
)

CLAUSES = {
    "support": "BNBC 2020 Part 6 Sec 7.4.3.2 (p. 1015)",
    "wind": "BNBC 2020 Part 6 Sec 7.9.6.3 (p. 1045)",
    "deflection": "BNBC 2020 Part 6 Sec 6.2.5.2.3, Eq. 6.6.1-6.6.3, Table 6.6.1 (p. 900)",
    "combinations": "BNBC 2020 Part 6 Sec 2.7.3.1 (p. 685)",
    "coupling": "BNBC 2020 Part 6 Sec 8.3.6.7 (p. 1105)",
    "capacity": "BNBC 2020 Part 6 Sec 8.3.8.1(a) (p. 1111), 8.3.8.2(a) (p. 1112)",
}

#: Least bearing of a lintel on each end (7.4.3.2) [mm], and the default bearing.
MIN_BEARING = 100.0
BEARING = 150.0
#: Deflection limit of members supporting masonry: clear span / 600 (7.4.3.2).
DEFLECTION_RATIO = 600.0
#: Lintel span limit and bar extension beyond the opening (7.9.6.3, high wind regions) [mm].
WIND_SPAN_MAX = 3500.0
WIND_BAR_EXTENSION = 600.0
#: Least lintel depth and the depth step [mm].
MIN_DEPTH = 150.0
DEPTH_STEP = 25.0
#: Unit weights [kN/m³] when the material has no density: reinforced concrete, brick masonry.
CONCRETE_WEIGHT = 24.0
MASONRY_WEIGHT = 18.85
#: Lintel bars: main diameters, hangers.
LINTEL_DIAMETERS = (10.0, 12.0, 16.0, 20.0, 25.0)
HANGER = (2, 10.0)
COVER = 25.0
#: Members at most this deep need no shear reinforcement where Vu <= φVc (ACI Table
#: 9.6.3.1); their nominal links (legs, dia, spacing).
SHALLOW = 250.0
NOMINAL_LINKS = (2, 8.0, 150.0)
#: Probable moment: bars at 1.25 fy (notation p. 882, 8.3.8.1).
PROBABLE = 1.25
G = 9.80665

METHOD = [
    (
        "Lintels (masonry and partition walls): simply supported RC beams over each opening, "
        "span = clear width + bearing (>= 100 mm each end, BNBC 2020 Part 6 Sec 7.4.3.2); the "
        "masonry above as a triangle at 45° where the wall above is high enough to arch, else "
        "all of it with the floor's line load; flexure, shear (Chapter 6 beam design), the "
        "deflection under service loads with Ie (Eq. 6.6.1) within clear span / 600 "
        "(7.4.3.2). Spandrels of RC walls not designed with diagonal bars: as beams, special "
        "walls' flexural coupling beams (ln/h > 4, 8.3.6.7(a)) to the special moment frame "
        "beam rules with the capacity-design shear (8.3.8.1(a)); their width rules (8.3.4.1(c), "
        "(d)) count, since no lateral stability analysis is made (8.3.6.7(a))."
    ),
]


# ─────────────────────────────────────── loads ───────────────────────────────────────


@dataclass(frozen=True)
class LintelLoads:
    """Unfactored loads on a lintel: ``triangle`` the peak of the triangular masonry load
    [N/mm], ``dead`` and ``live`` uniform [N/mm]."""

    span: float  # effective span L [mm]
    clear: float  # clear opening width [mm]
    triangle: float
    dead: float
    live: float
    arching: bool
    height_above: float  # masonry above the lintel [mm]
    triangle_height: float  # [mm]
    notes: tuple[str, ...] = ()

    def moment(self, d: float, l_: float) -> float:
        """Midspan moment [N·mm] with the factors ``d`` (dead, masonry) and ``l_`` (live)."""
        w = d * self.dead + l_ * self.live
        return d * self.triangle * self.span**2 / 12 + w * self.span**2 / 8

    def shear(self, d: float, l_: float) -> float:
        """Shear at the bearing [N]."""
        w = d * self.dead + l_ * self.live
        return d * self.triangle * self.span / 4 + w * self.span / 2


def lintel_loads(
    clear: float,
    width: float,
    depth: float,
    height_above: float,
    *,
    masonry_weight: float = MASONRY_WEIGHT,
    concrete_weight: float = CONCRETE_WEIGHT,
    bearing: float = BEARING,
    angle: float = 45.0,
    floor_dead: float = 0.0,
    floor_live: float = 0.0,
) -> LintelLoads:
    """The loads on a lintel ``width`` x ``depth`` over an opening ``clear`` wide [mm] with
    ``height_above`` [mm] of masonry above it (unit weights in kN/m³, the floor's line loads in
    kN/m = N/mm): see the module notes."""
    span = clear + bearing
    rise = span / 2 * math.tan(math.radians(angle))
    gamma = masonry_weight * 1e-6  # N/mm³
    own = concrete_weight * 1e-6 * width * depth
    notes = []
    if height_above >= rise:
        triangle, dead, live = gamma * width * rise, own, 0.0
        arching = True
        notes.append(
            f"the masonry above ({height_above:.0f} mm) reaches the {angle:g}° load triangle's "
            f"height {rise:.0f} mm: it arches, the lintel carries the triangle (the floor above "
            "is carried by the arch)"
        )
    else:
        triangle = 0.0
        dead = own + gamma * width * max(height_above, 0.0) + floor_dead
        live = floor_live
        arching = False
        notes.append(
            f"the masonry above ({max(height_above, 0.0):.0f} mm) is lower than the {angle:g}° "
            f"load triangle ({rise:.0f} mm): no arching, all of it and the floor's line load "
            f"({floor_dead:g} kN/m dead, {floor_live:g} kN/m live) on the lintel"
        )
    return LintelLoads(span, clear, triangle, dead, live, arching, height_above, rise, tuple(notes))


# ─────────────────────────────────────── beam sections ───────────────────────────────────────


def flexure_of(area: float, b: float, d: float, fc: float, fy: float, es: float = STEEL_E):
    """(φMn, Mn [N·mm], φ, εt) of a singly reinforced rectangle (the stress block)."""
    if area <= 0:
        return 0.0, 0.0, 0.9, math.inf
    a = area * fy / (0.85 * fc * b)
    c = a / beta1(fc)
    eps_t = EPS_CU * (d - c) / c
    phi = phi_axial_flexure(eps_t, fy, es)
    mn = area * fy * (d - a / 2)
    return phi * mn, mn, phi, eps_t


def probable_moment(area: float, b: float, d: float, fc: float, fy: float) -> float:
    """Mpr [N·mm]: the bars at 1.25 fy, φ = 1 (the stress block, singly reinforced)."""
    if area <= 0:
        return 0.0
    a = area * PROBABLE * fy / (0.85 * fc * b)
    return area * PROBABLE * fy * (d - a / 2)


def cracked_inertia(area: float, b: float, d: float, n: float) -> float:
    """Icr [mm⁴] of a singly reinforced rectangle (transformed section)."""
    rho_n = n * area / (b * d)
    k = math.sqrt(2 * rho_n + rho_n**2) - rho_n
    kd = k * d
    return b * kd**3 / 3 + n * area * (d - kd) ** 2


def effective_inertia(ma: float, b: float, h: float, area: float, d: float, fc: float, es: float):
    """(Ie, Ig, Mcr) by Eq. 6.6.1-6.6.3 (λ = 1)."""
    ig = b * h**3 / 12
    mcr = 0.62 * math.sqrt(fc) * ig / (h / 2)
    if ma <= mcr:
        return ig, ig, mcr
    icr = cracked_inertia(area, b, d, es / (4700 * math.sqrt(fc)))
    r = (mcr / ma) ** 3
    return min(ig, r * ig + (1 - r) * icr), ig, mcr


@dataclass
class BeamDesign:
    """Bars of a rectangular beam and its check rows."""

    bottom: tuple[int, float] | None  # (count, dia)
    top: tuple[int, float] | None
    stirrups: tuple[int, float, float] | None  # (legs, dia, spacing)
    d: float
    checks: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    too_small: bool = False

    def label(self) -> str:
        parts = []
        if self.bottom:
            parts.append(f"bottom {self.bottom[0]}Ø{self.bottom[1]:g}")
        if self.top:
            parts.append(f"top {self.top[0]}Ø{self.top[1]:g}")
        if self.stirrups:
            legs, dia, s = self.stirrups
            parts.append(f"{legs}-leg Ø{dia:g} @ {s:g}")
        return ", ".join(parts)


def _bars_for(
    area: float, b: float, inset: float, max_count: int | None = None
) -> tuple[int, float] | None:
    """The best bars of one face (one row if they fit), with at most ``max_count`` bars where
    such a choice exists (two-leg hoops hold every corner and alternate bar of three)."""
    for rows in (1, 2):
        options = face_options(area, b, inset, LINTEL_DIAMETERS, min_count=2, max_rows=rows)
        if max_count is not None:
            few = [o for o in options if o.count <= max_count]
            options = few or options
        if options:
            return options[0].count, options[0].dia
    return None


def design_beam(
    mu: float,
    vu: float,
    b: float,
    h: float,
    fc: float,
    fy: float,
    *,
    fyt: float | None = None,
    cover: float = COVER,
    combination: str | None = None,
    shear_combination: str | None = None,
    symmetric: bool = False,
    stirrup_s_max: float | None = None,
    vc_zero: bool = False,
    es: float = STEEL_E,
    max_count: int | None = None,
) -> BeamDesign:
    """Bars for ``mu`` [N·mm] and stirrups for ``vu`` [N] of a ``b`` x ``h`` beam: bottom bars
    (and the same on top when ``symmetric``, else Ø10 hangers), with their rows. ``vc_zero``:
    Vc = 0 (8.3.8.2(a)); ``stirrup_s_max``: a closer spacing limit (the hoop zones);
    ``max_count``: bars per face preferred at most."""
    fyt = fy if fyt is None else fyt
    stirrup = STIRRUP_DIAMETERS[0]
    dia = 12.0
    need = None
    bars = None
    d = h - cover - stirrup - dia / 2
    for _ in range(3):
        d = h - cover - stirrup - dia / 2
        if d <= 0:
            out = BeamDesign(None, None, None, d, too_small=True)
            out.checks.append(
                _row("Effective depth d > 0", 1.0, 0.0, "mm", note="the beam is too shallow")
            )
            return out
        need = beam_flexure_need(mu, b, d, cover + stirrup + 6.0, fc, fy, es, h=h)
        required = with_minimum(need.area, beam_min_area(b, d, fc, fy))
        required = max(required, beam_min_area(b, d, fc, fy) if symmetric else 0.0)
        bars = _bars_for(max(required, 1.0), b, cover + stirrup, max_count)
        if bars is None or bars[1] == dia:
            break
        dia = bars[1]
    assert need is not None
    out = BeamDesign(bars, None, None, d)
    if bars is None:
        out.too_small = True
        out.checks.append(
            _row("Bars fit in the width", 1.0, 0.0, "", note=f"b = {b:.0f} mm: no bars fit")
        )
        return out
    out.top = bars if symmetric else HANGER
    area = bars[0] * bar_area(bars[1])
    phi_mn, _, phi, eps_t = flexure_of(area, b, d, fc, fy, es)
    out.checks.append(
        _row(
            "Flexure φMn (Chapter 6, stress block)",
            mu / 1e6,
            phi_mn / 1e6,
            "kN·m",
            combination,
            f"{bars[0]}Ø{bars[1]:g} = {area:.0f} mm², d = {d:.0f} mm, φ = {phi:.2f} (εt = "
            f"{eps_t:.4f})" + (f"; {need.note}" if need.note else ""),
        )
    )
    as_min = beam_min_area(b, d, fc, fy)
    out.checks.append(
        _row(
            "Least flexural steel As,min (or 4/3 As required)",
            min(as_min, 4 / 3 * need.area) if not symmetric else as_min,
            area,
            "mm²",
            note=f"max(0.25 √f'c, 1.4) bw d / fy = {as_min:.0f} mm²",
        )
    )
    if need.too_small:
        out.too_small = True
        out.notes.append(need.note)
    shear = beam_shear_need(vu, b, d, fc, fyt)
    if vc_zero:
        vs = vu / PHI_SHEAR
        shear = replace(
            shear,
            vc=0.0,
            vs=vs,
            av_s=max(vs / (min(fyt, FYT_SHEAR_MAX) * d), shear.av_s_min),
            too_small=vs > 0.66 * math.sqrt(fc) * b * d,
            note="Vc = 0 (8.3.8.2(a))",
        )
    if stirrup_s_max is not None:
        shear = replace(shear, s_max=min(shear.s_max, stirrup_s_max))
    chosen = choose_stirrups(shear, b)
    phi_vc = PHI_SHEAR * 0.17 * min(math.sqrt(fc), 8.3) * b * d
    if chosen is None and not vc_zero and h <= SHALLOW and vu <= phi_vc:
        # A shallow member (h <= 250 mm) needs no shear reinforcement where Vu <= φVc (ACI
        # Table 9.6.3.1): nominal links hold the bars.
        out.stirrups = NOMINAL_LINKS
        out.checks.append(
            _row(
                "Shear φVc, no stirrups required (h ≤ 250 mm)",
                vu / 1e3,
                phi_vc / 1e3,
                "kN",
                shear_combination or combination,
                f"Vc = 0.17 λ √f'c bw d, d = {d:.0f} mm; nominal links "
                f"Ø{NOMINAL_LINKS[1]:g} @ {NOMINAL_LINKS[2]:g} hold the bars",
            )
        )
        return out
    if chosen is None:
        out.too_small = True
        out.checks.append(
            _row(
                "Shear stirrups",
                vu / 1e3,
                0.0,
                "kN",
                shear_combination,
                "no stirrups of Ø8-Ø12 at ≥ 75 mm carry it: " + shear.note,
            )
        )
        return out
    out.stirrups = (chosen.legs, chosen.dia, chosen.spacing)
    vs = min(chosen.av_s * min(fyt, FYT_SHEAR_MAX) * d, 0.66 * math.sqrt(fc) * b * d)
    vc = 0.0 if vc_zero else 0.17 * min(math.sqrt(fc), 8.3) * b * d
    out.checks.append(
        _row(
            "Shear φ(Vc + Vs)",
            vu / 1e3,
            PHI_SHEAR * (vc + vs) / 1e3,
            "kN",
            shear_combination or combination,
            f"{chosen.legs}-leg Ø{chosen.dia:g} @ {chosen.spacing:g}; Vc = {vc / 1e3:.1f} kN, "
            f"Vs = {vs / 1e3:.1f} kN; s ≤ {shear.s_max:.0f} mm",
        )
    )
    return out


# ─────────────────────────────────────── lintels ───────────────────────────────────────


def lintel_depth(span: float, fy: float) -> float:
    """Table 6.6.1's least depth of a simply supported beam, L/16 × (0.4 + fy/700), not below
    150 mm, rounded up to 25 mm."""
    least = span / 16 * (0.4 + fy / 700)
    return max(MIN_DEPTH, math.ceil(least / DEPTH_STEP - 1e-9) * DEPTH_STEP)


def design_lintel(
    loads: LintelLoads,
    width: float,
    depth: float,
    fc: float,
    fy: float,
    *,
    combinations: Iterable[tuple[str, float, float]] = (
        ("1.4D", 1.4, 0.0),
        ("1.2D + 1.6L", 1.2, 1.6),
    ),
    bearing: float = BEARING,
    cover: float = COVER,
    es: float = STEEL_E,
    high_wind: bool = False,
) -> dict[str, Any]:
    """A lintel's design: ``{"span", "clear", "b", "h", "loads", "bars", "label", "checks",
    "utilisation", "ok", "notes"}`` (bars ``{"bottom": [count, dia], "top": ..., "stirrups":
    [legs, dia, spacing]}``)."""
    combos = list(combinations)
    mu, m_name = max(((loads.moment(d, l_), n) for n, d, l_ in combos), default=(0.0, None))
    vu, v_name = max(((loads.shear(d, l_), n) for n, d, l_ in combos), default=(0.0, None))
    beam = design_beam(
        mu,
        vu,
        width,
        depth,
        fc,
        fy,
        cover=cover,
        combination=m_name,
        shear_combination=v_name,
        es=es,
    )
    checks = list(beam.checks)
    notes = list(loads.notes) + beam.notes
    checks.append(
        _row(
            "Bearing on each end (7.4.3.2)",
            MIN_BEARING,
            bearing,
            "mm",
            note="lintels bear at least 100 mm on the supporting masonry",
        )
    )
    if beam.bottom is not None:
        area = beam.bottom[0] * bar_area(beam.bottom[1])
        ma = loads.moment(1.0, 1.0)
        ie, ig, mcr = effective_inertia(ma, width, depth, area, beam.d, fc, es)
        ec = 4700 * math.sqrt(fc)
        w = loads.dead + loads.live
        delta = 5 * w * loads.span**4 / (384 * ec * ie) + loads.triangle * loads.span**4 / (
            120 * ec * ie
        )
        checks.append(
            _row(
                "Deflection under total loads ≤ clear span / 600 (7.4.3.2)",
                delta,
                loads.clear / DEFLECTION_RATIO,
                "mm",
                "D + L",
                f"immediate, Ie = {ie / 1e6:.1f}e6 mm⁴ (Eq. 6.6.1; Ig = {ig / 1e6:.1f}e6, Mcr = "
                f"{mcr / 1e6:.2f} kN·m, Ma = {ma / 1e6:.2f} kN·m), Ec = 4700 √f'c",
            )
        )
        notes.append(
            "deflection: immediate only; the long-term part (creep and shrinkage) is not added"
        )
    least = lintel_depth(loads.span, fy)
    row = _row(
        "Depth for no deflection calculation, L/16 (Table 6.6.1, informative)",
        least,
        depth,
        "mm",
        note=f"× (0.4 + fy/700) for fy = {fy:g} MPa",
    )
    row["flag"] = True
    checks.append(row)
    wind = _row(
        "Lintel span ≤ 3.5 m in high wind regions (7.9.6.3)",
        loads.span,
        WIND_SPAN_MAX,
        "mm",
        note="masonry where the basic wind speed exceeds 200 km/h",
    )
    wind["flag"] = not high_wind
    checks.append(wind)
    notes.append(
        "bars into the supports: at least the development length past each face"
        + (
            f", and {WIND_BAR_EXTENSION:.0f} mm beyond the opening's edges (7.9.6.3)"
            if high_wind
            else ""
        )
    )
    strength = [c for c in checks if not c["flag"]]
    return {
        "span": round(loads.span, 1),
        "clear": round(loads.clear, 1),
        "b": width,
        "h": depth,
        "loads": {
            "arching": loads.arching,
            "triangle": round(loads.triangle, 3),
            "dead": round(loads.dead, 3),
            "live": round(loads.live, 3),
            "heightAbove": round(loads.height_above, 0),
            "triangleHeight": round(loads.triangle_height, 0),
            "units": "kN/m (N/mm)",
            "Mu": round(mu / 1e6, 2),
            "Vu": round(vu / 1e3, 2),
        },
        "bars": {
            "bottom": list(beam.bottom) if beam.bottom else None,
            "top": list(beam.top) if beam.top else None,
            "stirrups": list(beam.stirrups) if beam.stirrups else None,
        },
        "label": beam.label(),
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in strength), default=0.0),
        "ok": all(c["ok"] for c in strength) and not beam.too_small,
        "notes": notes,
    }


def _weight(material: Any, default: float) -> float:
    density = getattr(getattr(material, "mechanical", None), "density", None)
    return float(density) * G / 1e3 if density else default


def _beam_over(building: Any, types: Mapping[str, Any], wall: Any) -> float | None:
    """Depth [mm] of a beam along the wall at its top (None: no beam)."""
    import numpy as np

    from saengine.library.bim import BeamElement

    a, b = np.asarray(wall.start, dtype=float), np.asarray(wall.end, dtype=float)
    run = b - a
    length = float(np.linalg.norm(run)) or 1.0
    u = run / length
    found = None
    for e in building.elements:
        if not isinstance(e, BeamElement) or abs(float(e.elevation) - float(wall.top)) > 1.0:
            continue
        p, q = np.asarray(e.start, dtype=float) - a, np.asarray(e.end, dtype=float) - a
        if abs(p[0] * u[1] - p[1] * u[0]) > 1.0 or abs(q[0] * u[1] - q[1] * u[0]) > 1.0:
            continue
        s0, s1 = sorted((float(p @ u), float(q @ u)))
        if s1 - s0 <= 1.0 or s1 <= 1.0 or s0 >= length - 1.0:
            continue
        profile = getattr(types.get(e.type), "profile", None)
        depth = getattr(profile, "yDim", None) or getattr(profile, "depth", None)
        found = max(found or 0.0, float(depth or 0.0))
    return found


def lintels_of(
    building: Any,
    types: Mapping[str, Any],
    mats: Mapping[str, Any],
    settings: Any = None,
    *,
    concrete: str | None = None,
    steel: str | None = None,
    floor_loads: Mapping[str, tuple[float, float]] | None = None,
    angle: float = 45.0,
    bearing: float = BEARING,
    high_wind: bool = False,
) -> dict[str, Any]:
    """The lintels of every opening in a wall that is not a structural concrete wall:
    ``{"elements", "skipped", "notes"}`` with elements in the design report's shape (``id`` the
    opening's, ``kind`` "lintel", ``type`` the host wall's type, ``host``, ``members`` empty,
    ``checks``, ``utilisation``, ``ok`` and :func:`design_lintel`'s fields).

    ``concrete``, ``steel``: material ids of the lintels (default: the first concrete with f'c
    and the first reinforcing steel of ``mats``); ``floor_loads``: per wall id the floor's
    line load on the wall (dead, live) [kN/m] used where the arch cannot form (default 0 where
    a beam runs over the wall, else 0 with a note)."""
    from saengine.design.stairs import loads_from_settings
    from saengine.library.bim import WallElement
    from saengine.library.materials import Category
    from saengine.library.objects import Wall

    elements: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    notes: list[str] = []
    walls = {e.id: e for e in building.elements if isinstance(e, WallElement)}
    openings = list(building.additions.wallOpenings)
    if not openings:
        return {"elements": [], "skipped": [], "notes": []}
    conc = mats.get(concrete) if concrete else None
    if conc is None:
        conc = next(
            (m for m in mats.values() if m.category == Category.CONCRETE and m.concrete), None
        )
    bar = mats.get(steel) if steel else None
    if bar is None:
        bar = next(
            (m for m in mats.values() if m.steel is not None and m.category == Category.REBAR),
            None,
        )
    if bar is None:
        bar = next((m for m in mats.values() if getattr(m, "steel", None) is not None), None)
    if conc is None or bar is None:
        notes.append("lintels: no concrete or reinforcing steel among the materials")
        return {"elements": [], "skipped": [], "notes": notes}
    fc, fy = float(conc.concrete.fc), float(bar.steel.fy)
    es = float(getattr(bar.mechanical, "E", None) or STEEL_E)
    combos = loads_from_settings(settings).combinations
    for o in openings:
        wall = walls.get(o.host)
        t = types.get(wall.type) if wall else None
        if wall is None or not isinstance(t, Wall):
            continue
        material = mats.get(t.material)
        rc_wall = (
            t.structural
            and material is not None
            and material.category == Category.CONCRETE
            and t.reinforcement is not None
        )
        if rc_wall:
            continue  # the wall over it is a spandrel of the shell model
        head = float(wall.bottom) + float(o.sill) + float(o.height)
        if head >= float(wall.top) - 1.0:
            skipped.append(
                {
                    "id": o.id,
                    "kind": "lintel",
                    "type": wall.type,
                    "reason": "the opening reaches the top of the wall: the beam or slab over it "
                    "spans it",
                }
            )
            continue
        width = float(t.thickness)
        span = float(o.width) + bearing
        depth = lintel_depth(span, fy)
        beam = _beam_over(building, types, wall)
        above = float(wall.top) - head - depth - (beam or 0.0)
        dead = live = 0.0
        own_notes = []
        if floor_loads and wall.id in floor_loads:
            dead, live = floor_loads[wall.id]
        elif beam is None:
            own_notes.append(
                "no beam found over the wall: where the arch cannot form, the floor's line load "
                "on the wall is not included (pass it as floor_loads)"
            )
        else:
            own_notes.append(f"a beam {beam:.0f} mm deep over the wall carries the floor")
        weight = _weight(material, MASONRY_WEIGHT)
        if material is None or not getattr(getattr(material, "mechanical", None), "density", None):
            own_notes.append(f"masonry unit weight {MASONRY_WEIGHT:g} kN/m³ assumed")
        loads = lintel_loads(
            float(o.width),
            width,
            depth,
            above,
            masonry_weight=weight,
            concrete_weight=_weight(conc, CONCRETE_WEIGHT),
            bearing=bearing,
            angle=angle,
            floor_dead=dead,
            floor_live=live,
        )
        found = design_lintel(
            loads,
            width,
            depth,
            fc,
            fy,
            combinations=combos,
            bearing=bearing,
            es=es,
            high_wind=high_wind,
        )
        elements.append(
            {
                "id": o.id,
                "kind": "lintel",
                "type": wall.type,
                "host": wall.id,
                "members": [],
                "concrete": conc.id,
                "steel": bar.id,
                **found,
                "notes": own_notes + found["notes"],
            }
        )
    if elements:
        notes.append(
            f"lintels: {len(elements)} over openings in masonry and partition walls, "
            f"{conc.id} and {bar.id}, depth L/16 × (0.4 + fy/700) ≥ 150 mm"
        )
    return {"elements": elements, "skipped": skipped, "notes": notes}


# ─────────────────────────────────────── spandrels ───────────────────────────────────────


def spandrel_mode(ln: float, h: float, vu: float, bw: float, fc: float, special: bool) -> str:
    """ "flexural" | "either" | "diagonal" (special walls, 8.3.6.7 (a)-(c)), or "beam" | "deep"
    (ordinary walls: ln/h >= 4 a beam, else a deep beam)."""
    ratio = ln / h
    if special:
        if ratio > 4:
            return "flexural"
        if ratio < 2 and vu > 0.33 * bw * h * math.sqrt(fc):
            return "diagonal"
        return "either"
    return "beam" if ratio >= 4 else "deep"


def spandrel_design(
    spandrel: Mapping[str, Any],
    fc: float,
    fy: float,
    *,
    special: bool,
    earthquake: Iterable[str] | None = None,
    cover: float = COVER,
    es: float = STEEL_E,
    lateral_stability: bool = False,
) -> dict[str, Any]:
    """A spandrel of :func:`saengine.design.wall_forces.wall_forces` (``length``, ``depth``,
    ``tw``, ``cuts`` {left, middle, right: {combination: {P, V2, M3, ...}}} in kN, kN·m)
    designed as a beam (see the module notes): ``{"id", "mode", "ln", "h", "bars", "label",
    "checks", "utilisation", "ok", "notes"}``. ``lateral_stability``: the engineer has shown
    by analysis that the beam is laterally stable, so the width rules of 8.3.7.1(c), (d) are
    waived (8.3.6.7(a)); otherwise they count."""
    from saengine.design import ductile_members as D
    from saengine.design.rc import section_of
    from saengine.library.objects import (
        BarGroup,
        LinearReinforcement,
        RectangleProfile,
        Transverse,
        TransverseZone,
    )

    seismic = None if earthquake is None else set(earthquake)
    ln, h, bw = float(spandrel["length"]), float(spandrel["depth"]), float(spandrel["tw"])
    mu = vu = vg = pu = 0.0
    m_name = v_name = None
    for rows in (spandrel.get("cuts") or {}).values():
        for name, r in (rows or {}).items():
            m, v = abs(float(r.get("M3", 0.0))) * 1e6, abs(float(r.get("V2", 0.0))) * 1e3
            if m > mu:
                mu, m_name = m, name
            if v > vu:
                vu, v_name = v, name
            if seismic is not None and name not in seismic:
                vg = max(vg, v)
            pu = max(pu, float(r.get("P", 0.0)) * 1e3)
    mode = spandrel_mode(ln, h, vu, bw, fc, special)
    notes = [
        f"ln/h = {ln / h:.2f}: "
        + {
            "flexural": "a flexural member of a special moment frame (8.3.6.7(a))",
            "either": "diagonal bars or the beam rules (8.3.6.7(c)): the beam rules here",
            "diagonal": "diagonal bars required (8.3.6.7(b))",
            "beam": "a beam",
            "deep": "a deep beam (ln/h < 4): designed as a beam (sectional shear, on the safe "
            "side of a deep beam's strut action); its strut-and-tie design is not done",
        }[mode]
    ]
    base = {"id": spandrel.get("spandrel"), "mode": mode, "ln": round(ln, 1), "h": round(h, 1)}
    if mode == "diagonal":
        return {
            **base,
            "bars": None,
            "label": "",
            "checks": [],
            "utilisation": None,
            "ok": None,
            "notes": notes + ["designed with diagonal bars (walls.coupling_beam_checks)"],
        }
    ductile = special
    few = 3 if ductile else None
    beam = design_beam(
        mu,
        vu,
        bw,
        h,
        fc,
        fy,
        cover=cover,
        combination=m_name,
        shear_combination=v_name,
        symmetric=True,
        es=es,
        max_count=few,
    )
    checks = list(beam.checks)
    if ductile and beam.bottom is not None and beam.stirrups is not None:
        area = beam.bottom[0] * bar_area(beam.bottom[1])
        mpr = probable_moment(area, bw, beam.d, fc, fy)
        ve = 2 * mpr / ln + vg
        vc_zero = (ve - vg) >= ve / 2 and pu < bw * h * fc / 20
        section = section_of(
            RectangleProfile(xDim=bw, yDim=h),
            LinearReinforcement(
                material="rebar",
                cover=cover,
                longitudinal=[
                    BarGroup(position="top", count=beam.bottom[0], dia=beam.bottom[1]),
                    BarGroup(position="bottom", count=beam.bottom[0], dia=beam.bottom[1]),
                ],
                transverse=Transverse(
                    type="stirrup",
                    dia=beam.stirrups[1],
                    spacing=beam.stirrups[2],
                    legs=beam.stirrups[0],
                ),
            ),
            fc,
            fy,
            es,
        )
        need = D.beam_need(section, "special", beam.stirrups[1])
        zone = round_down(need.zone_spacing) if need.zone_spacing else None
        capacity = design_beam(
            mu,
            ve,
            bw,
            h,
            fc,
            fy,
            cover=cover,
            combination=m_name,
            shear_combination="Ve = 2 Mpr / ln + Vg",
            symmetric=True,
            stirrup_s_max=zone,
            vc_zero=vc_zero,
            es=es,
            max_count=few,
        )
        if capacity.too_small or any(not c["ok"] for c in capacity.checks):
            notes.append(
                "the capacity-design shear needs more than the beam can take: diagonal bars "
                "(8.3.6.7(c), (d)), a wider wall or a shallower spandrel"
            )
        shear_rows = [c for c in capacity.checks if c["name"].startswith("Shear")]
        for c in shear_rows:
            c["name"] = "Capacity-design shear Ve (8.3.8.1(a))"
            c["note"] += (
                f"; Mpr = {mpr / 1e6:.1f} kN·m each end (1.25 fy, φ = 1), Vg = {vg / 1e3:.1f} kN"
                + ("; Vc = 0 (8.3.8.2(a))" if vc_zero else "")
            )
        checks = [c for c in checks if not c["name"].startswith("Shear")] + shear_rows
        stirrups = capacity.stirrups or beam.stirrups
        beam.stirrups = stirrups
        if stirrups is not None:
            transverse = Transverse(
                type="stirrup",
                dia=stirrups[1],
                spacing=min(stirrups[2], round_down(need.outside_spacing or stirrups[2])),
                legs=stirrups[0],
                zone=TransverseZone(spacing=stirrups[2], length=2 * h),
            )
            phi_mn, mn, phi, eps_t = flexure_of(area, bw, beam.d, fc, fy, es)
            caps = {hog: Flexure(phi_mn, mn, phi, eps_t) for hog in (False, True)}
            detailing = D.beam_checks(
                section, transverse, "special", clear_span=ln, capacities=caps
            )
            # 8.3.6.7(a) waives the width rules only "if it can be shown by analysis that the
            # beam has adequate lateral stability": no such analysis is made here, so they
            # count unless the engineer says it was shown (``lateral_stability``). (c) asks
            # only for the longitudinal, transverse and shear rules ("8.3.7.2 to 8.3.7.4"
            # [sic]: 8.3.4.2-8.3.4.4), not the member limits of 8.3.4.1.
            widths = ("Width to depth", "Width ≥ 250")
            waived = widths if lateral_stability else ()
            if mode == "either":
                waived += ("Clear span ≥ 4d", "Axial force of a flexural member")
            for c in detailing.checks:
                if waived and c["name"].startswith(waived):
                    c["flag"] = True
                    c["note"] = (c["note"] + "; " if c["note"] else "") + (
                        "lateral stability shown by the engineer's analysis: waived (8.3.6.7(a))"
                        if c["name"].startswith(widths)
                        else "not required of a coupling beam (8.3.6.7(c))"
                    )
                elif c["name"].startswith(widths) and not c.get("ok", True):
                    c["note"] = (c["note"] + "; " if c["note"] else "") + (
                        "may be waived only if analysis shows the beam is laterally stable "
                        "(8.3.6.7(a)); no such analysis is made here"
                    )
                checks.append(c)
            notes += detailing.notes
    strength = [c for c in checks if not c["flag"]]
    return {
        **base,
        "bars": {
            "bottom": list(beam.bottom) if beam.bottom else None,
            "top": list(beam.top) if beam.top else None,
            "stirrups": list(beam.stirrups) if beam.stirrups else None,
        },
        "label": beam.label(),
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in strength), default=0.0),
        "ok": all(c["ok"] for c in strength) and not beam.too_small,
        "notes": notes + beam.notes,
    }

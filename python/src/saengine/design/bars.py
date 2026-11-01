"""Required reinforcement by closed-form strength design, and practical bar arrangements: the
building blocks of the design mode (:mod:`saengine.design.required`,
:mod:`saengine.design.proposal`).

Code basis ACI 318-19 (adopted by the default pack's BNBC 2020 Part 6 Chapter 6), the same factors as
:mod:`saengine.design.rc`:

- Flexure, rectangular stress block (22.2): a singly reinforced section needs
  As = 0.85 f'c b d / fy (1 - √(1 - 2 Mu / (φ 0.85 f'c b d²))) with φ = 0.90 while the
  section is tension-controlled, εt >= εty + 0.003 (21.2.2), i.e. c <= 0.003 d /
  (0.006 + εty). Beyond that a beam takes compression bars: the tension bars at the
  tension-controlled limit carry Mn1 = As1 fy (d - a/2), the rest Mn2 = Mu/φ - Mn1 is carried by
  compression bars As' (stress f's from strain compatibility at c, less the concrete they
  displace) and as much extra tension steel. A slab has no compression bars: it may enter the
  transition zone down to εt = 0.004 (7.3.3.1, 8.3.3.1), with φ from εt.
- Least flexural steel of beams (9.6.1.2): max(0.25 √f'c, 1.4) bw d / fy; it need not be met
  where the bars provided are at least 4/3 of those required (9.6.1.3). Slabs and footings:
  the ratio of Table 24.4.3.2 (7.6.1.1, 8.6.1.1).
- Shear (22.5): Vs = Vu/φ - Vc with Vc = 0.17 λ √f'c bw d (Table 22.5.5.1 (a), stirrups at least
  Av,min), Av/s = Vs / (fyt d) (22.5.8.5.3), at least Av,min/s = max(0.062 √f'c, 0.35) bw / fyt
  (9.6.3.4); √f'c at most 8.3 MPa in Vc (22.5.3.1), fyt at most 420 MPa (20.2.2.4). The
  section is too small when Vs exceeds 0.66 √f'c bw d (22.5.1.2). Largest stirrup spacing
  min(d/2, 600 mm), halved to min(d/4, 300 mm) where Vs > 0.33 √f'c bw d (9.7.6.2.2).
- Bars in a row at least max(25 mm, db, 4/3 aggregate) clear (25.2.1), rows 25 mm clear
  (25.2.2); column bars at least max(40 mm, 1.5 db, 4/3 aggregate) clear (25.2.3).
- Column ties (25.7.2): Ø10 for bars up to Ø32, Ø13 above (Ø12 is the nearest Bangladeshi bar,
  flagged); spacing at most min(16 db, 48 dt, the least column dimension) (25.7.2.1); every
  corner bar and every other bar held by a tie corner, and no bar more than 150 mm clear from a
  held bar (25.7.2.3).

Units: mm, MPa, N, N·mm.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from saengine.codes import context as code_context
from saengine.design.rc import bar_area, beta1
from saengine.design.rc import value as rc_value

EPS_T_SLAB = 0.004

# The practice values below are the code pack's ``concrete`` table (read where they are used,
# so the pack in force is the one read).


def diameters(kind: str) -> tuple[float, ...]:
    """Bar diameters [mm] of use ``kind``, the pack's ``concrete.barDiameters[kind]``. The default pack's BNBC 2020
    (BDS ISO 6935-2 sizes in common Bangladeshi practice): "all" 10, 12, 16, 20, 25, 32; "main"
    (beam and column main bars, the practical subset) 12 to 32; "column" 16 to 32; "slab" 10,
    12, 16; "stirrup" 8, 10, 12; "tank" (water and septic tanks) 10 to 25; "foundation" (9
    Substructure's minimum mesh and sizing) 12 to 25. A pack without the set reads the default pack's (BNBC 2020)."""
    sets = code_context.table("concrete").barDiameters
    if kind not in sets:
        from saengine.codes.tables import builtin_table

        sets = builtin_table("concrete").barDiameters
    return tuple(sets[kind])


#: :func:`diameters` under a name the functions with a ``diameters`` argument can call.
diameters_of = diameters


def spacing_step() -> float:
    """Bar spacings of slabs and footings, and stirrup spacings, are multiples of this [mm]
    (the pack's ``concrete.spacingStep``; the default pack's BNBC 2020: 25 mm)."""
    return float(code_context.table("concrete").spacingStep)


def min_slab_spacing() -> float:
    """Least practical spacing of slab and footing bars [mm] (site practice, not a code limit;
    the pack's ``concrete.minSlabSpacing``; the default pack's BNBC 2020: 100 mm)."""
    return float(code_context.table("concrete").minSlabSpacing)


def min_stirrup_spacing() -> float:
    """Least practical spacing of stirrups [mm] (site practice, not a code limit; the pack's
    ``concrete.minStirrupSpacing``; the default pack's BNBC 2020: 75 mm)."""
    return float(code_context.table("concrete").minStirrupSpacing)


def column_rho() -> tuple[float, float]:
    """(least, largest) column steel ratio (ACI 10.6.1.1; the pack's ``concrete.columnRho``;
    the default pack's BNBC 2020: 0.01, 0.08)."""
    low, high = code_context.table("concrete").columnRho
    return float(low), float(high)


def beam_ratio_max() -> float:
    """Largest tension steel of a beam, as a share of b h, before the section is called too
    small: a practical limit (congestion), not an ACI clause (the pack's
    ``concrete.beamRatioMax``; the default pack's BNBC 2020: 0.04)."""
    return float(code_context.table("concrete").beamRatioMax)


def round_down(value: float, step: float | None = None) -> float:
    """``value`` rounded down to a multiple of ``step`` (default :func:`spacing_step`; a hair
    of tolerance kept)."""
    if step is None:
        step = spacing_step()
    return math.floor(value / step + 1e-9) * step


def tension_controlled_depth(d: float, fy: float, es: float | None = None) -> float:
    """Neutral-axis depth [mm] at which εt = εty + 0.003 (ACI 21.2.2): φ = 0.90 above it."""
    if es is None:
        es = rc_value("STEEL_E")
    return rc_value("EPS_CU") * d / (2 * rc_value("EPS_CU") + fy / es)


# ─────────────────────────────────────── flexure ───────────────────────────────────────


@dataclass(frozen=True)
class FlexureNeed:
    """The bars a moment needs: tension ``area`` and compression ``compression`` [mm²]."""

    mu: float  # N·mm
    area: float
    compression: float = 0.0
    too_small: bool = False
    note: str = ""


def singly_area(mu: float, b: float, d: float, fc: float, fy: float, phi: float | None = None):
    """As [mm²] of a singly reinforced section for ``mu`` [N·mm] at φ (the stress block), or
    None when the concrete cannot carry it at all (the root goes negative)."""
    if phi is None:
        phi = rc_value("PHI_TENSION")
    if mu <= 0:
        return 0.0
    k = 1 - 2 * mu / (phi * 0.85 * fc * b * d**2)
    if k < 0:
        return None
    return 0.85 * fc * b * d / fy * (1 - math.sqrt(k))


def beam_flexure_need(
    mu: float,
    b: float,
    d: float,
    d_comp: float,
    fc: float,
    fy: float,
    es: float | None = None,
    ratio_max: float | None = None,
    h: float | None = None,
) -> FlexureNeed:
    """The tension and compression bars of a rectangular beam section for ``mu`` (see the
    module notes). ``d_comp``: depth of the compression bars from the compression face;
    ``ratio_max`` default :func:`beam_ratio_max`."""
    if es is None:
        es = rc_value("STEEL_E")
    if mu <= 0:
        return FlexureNeed(0.0, 0.0)
    if ratio_max is None:
        ratio_max = beam_ratio_max()
    b1 = beta1(fc)
    c_tc = tension_controlled_depth(d, fy, es)
    a_tc = b1 * c_tc
    as_tc = 0.85 * fc * b * a_tc / fy
    mn_tc = as_tc * fy * (d - a_tc / 2)
    limit = ratio_max * b * (h if h else d)
    if mu <= rc_value("PHI_TENSION") * mn_tc:
        area = singly_area(mu, b, d, fc, fy) or as_tc
        if area > limit:
            return FlexureNeed(mu, area, 0.0, True, "tension steel above the practical limit")
        return FlexureNeed(mu, area)
    # Compression bars, the tension bars at the tension-controlled limit.
    mn2 = mu / rc_value("PHI_TENSION") - mn_tc
    strain = rc_value("EPS_CU") * (c_tc - d_comp) / c_tc
    fs = min(es * strain, fy)
    if fs <= 0.85 * fc or d <= d_comp:
        return FlexureNeed(
            mu,
            as_tc,
            0.0,
            True,
            "compression bars would not work (they lie near the neutral axis): section too small",
        )
    compression = mn2 / ((fs - 0.85 * fc) * (d - d_comp))
    area = as_tc + compression * (fs - 0.85 * fc) / fy
    note = (
        f"compression bars: beyond the tension-controlled limit c = {c_tc:.0f} mm "
        f"(εt = εty + 0.003, ACI 21.2.2), f's = {fs:.0f} MPa"
    )
    too_small = area > limit
    if too_small:
        note += f"; tension steel {area:.0f} mm² above {ratio_max:g} b h: section too small"
    return FlexureNeed(mu, area, compression, too_small, note)


def beam_min_area(b: float, d: float, fc: float, fy: float) -> float:
    """As,min of a beam (ACI 9.6.1.2): max(0.25 √f'c, 1.4) bw d / fy."""
    return max(0.25 * math.sqrt(fc), 1.4) * b * d / fy


def with_minimum(required: float, minimum: float) -> float:
    """The flexural bars to provide: As,min, or 4/3 of the bars required where that is less
    (ACI 9.6.1.3); nothing where nothing is required."""
    if required <= 0:
        return 0.0
    return max(required, min(minimum, 4 / 3 * required))


def strip_capacity(area: float, d: float, fc: float, fy: float, es: float | None = None) -> float:
    """φMn [N·mm per metre] of ``area`` [mm²/m] at ``d`` in a 1 m strip (as
    :func:`saengine.design.slab.layer_capacity`)."""
    if es is None:
        es = rc_value("STEEL_E")
    from saengine.design.slab import layer_capacity

    return layer_capacity(area, d, fc, fy, es).phi_mn


def slab_max_area(d: float, fc: float, fy: float, eps_t: float = EPS_T_SLAB) -> float:
    """The most bars per metre [mm²/m] a slab may have at ``d``: those that put the neutral
    axis at εt = 0.004 (ACI 7.3.3.1, 8.3.3.1)."""
    c = rc_value("EPS_CU") * d / (rc_value("EPS_CU") + eps_t)
    return 0.85 * fc * 1000 * beta1(fc) * c / fy


def slab_flexure_need(
    mu: float, d: float, fc: float, fy: float, es: float | None = None
) -> FlexureNeed:
    """As [mm²/m] of a slab strip for ``mu`` [N·mm/m]: the stress block at φ = 0.90, raised
    by bisection while the strip is in the transition zone (φ from εt), up to εt = 0.004."""
    if es is None:
        es = rc_value("STEEL_E")
    if mu <= 0:
        return FlexureNeed(0.0, 0.0)
    top = slab_max_area(d, fc, fy)
    if strip_capacity(top, d, fc, fy, es) < mu:
        return FlexureNeed(mu, top, 0.0, True, "even at εt = 0.004 the slab is too thin")
    area = singly_area(mu, 1000.0, d, fc, fy)
    if area is not None and area <= top and strip_capacity(area, d, fc, fy, es) >= mu * 0.9999:
        return FlexureNeed(mu, area)
    lo, hi = (area if area is not None and area < top else 0.0), top
    for _ in range(60):
        mid = (lo + hi) / 2
        if strip_capacity(mid, d, fc, fy, es) >= mu:
            hi = mid
        else:
            lo = mid
    return FlexureNeed(mu, hi, 0.0, False, "φ below 0.90 (εt in the transition zone)")


# ─────────────────────────────────────── shear ───────────────────────────────────────


@dataclass(frozen=True)
class ShearNeed:
    vu: float  # N
    vc: float
    vs: float  # N, required (0 when Vc suffices)
    av_s: float  # mm²/mm, to provide (at least the minimum)
    av_s_min: float
    s_max: float  # mm
    too_small: bool = False
    note: str = ""


def beam_shear_need(vu: float, b: float, d: float, fc: float, fyt: float, lam: float = 1.0):
    """Stirrups of a beam for ``vu`` [N] (see the module notes), as :func:`rc.shear` checks
    them: Vc of Table 22.5.5.1 (a) since at least Av,min is always provided."""
    root = min(math.sqrt(fc), 8.3)
    fyt = min(fyt, 420.0)
    vc = 0.17 * lam * root * b * d
    vs = max(vu / rc_value("PHI_SHEAR") - vc, 0.0)
    vs_max = 0.66 * math.sqrt(fc) * b * d
    av_s_min = max(0.062 * root, 0.35) * b / fyt
    av_s = max(vs / (fyt * d), av_s_min)
    if vs > 0.33 * math.sqrt(fc) * b * d:
        s_max, rule = min(d / 4, 300.0), "min(d/4, 300 mm)"
    else:
        s_max, rule = min(d / 2, 600.0), "min(d/2, 600 mm)"
    note = f"Vc = {vc / 1e3:.1f} kN, Vs = {vs / 1e3:.1f} kN; s ≤ {rule} (ACI 9.7.6.2.2)"
    too_small = vs > vs_max
    if too_small:
        note += (
            f"; Vs above 0.66 √f'c bw d = {vs_max / 1e3:.1f} kN (ACI 22.5.1.2): section too small "
            "for shear"
        )
    return ShearNeed(vu, vc, vs, av_s, av_s_min, s_max, too_small, note)


def slab_shear_rho(q: float, d: float, fc: float, lam: float = 1.0) -> float | None:
    """The tension steel ratio a slab without shear bars needs for one-way shear ``q`` [N/m]
    (ACI Table 22.5.5.1 (c): φ 0.66 λs λ ρ^(1/3) √f'c b d), or None when even the upper limit
    φ 0.42 λ √f'c b d does not carry it (the slab is too thin)."""
    root = min(math.sqrt(fc), 8.3)
    lambda_s = min(1.0, math.sqrt(2 / (1 + 0.004 * d)))
    if q > rc_value("PHI_SHEAR") * 0.42 * lam * root * 1000 * d:
        return None
    return (q / (rc_value("PHI_SHEAR") * 0.66 * lambda_s * lam * root * 1000 * d)) ** 3


# ─────────────────────────────────────── arrangements ───────────────────────────────────────


@dataclass(frozen=True)
class Stirrups:
    dia: float
    legs: int
    spacing: float

    @property
    def av_s(self) -> float:
        return self.legs * bar_area(self.dia) / self.spacing


def choose_stirrups(
    need: ShearNeed,
    b: float,
    diameters: tuple[float, ...] | None = None,
    min_spacing: float | None = None,
) -> Stirrups | None:
    """The stirrups that give ``need.av_s`` with the least steel: spacings in 25 mm steps
    within the largest spacing, two legs before four (four only in beams at least 300 mm wide),
    the smaller bar on a tie; None when none fits. Defaults: the pack's stirrup diameters and
    least stirrup spacing."""
    if diameters is None:
        diameters = diameters_of("stirrup")
    if min_spacing is None:
        min_spacing = min_stirrup_spacing()
    step = spacing_step()
    s_max = round_down(need.s_max, step)
    best: tuple[float, int, float, Stirrups] | None = None
    for legs in (2, 4) if b >= 300 else (2,):
        for dia in diameters:
            spacing = min(round_down(legs * bar_area(dia) / need.av_s, step), s_max)
            if spacing < min_spacing:
                continue
            option = Stirrups(dia, legs, spacing)
            # Steel per length; a small premium on 4 legs and on close spacing (labour).
            cost = option.av_s * (1 + 0.1 * (legs > 2) + (0.05 if spacing < 100 else 0.0))
            key = (round(cost, 6), legs, dia, option)
            if best is None or key[:3] < best[:3]:
                best = key
    return best[3] if best else None


@dataclass(frozen=True)
class FaceBars:
    count: int
    dia: float
    rows: int

    @property
    def area(self) -> float:
        return self.count * bar_area(self.dia)

    @property
    def score(self) -> float:
        """Ranks the choices, lower first: the steel, 15 % more for each extra row (spacers,
        a smaller lever arm) and the equivalent of 25 mm² per bar (fewer bars to place)."""
        return self.area * (1 + 0.15 * (self.rows - 1)) + 25.0 * self.count

    def label(self) -> str:
        text = f"{self.count}Ø{self.dia:g}"
        return text + (f" in {self.rows} rows" if self.rows > 1 else "")


def face_options(
    required: float,
    width: float,
    inset: float,
    diameters: tuple[float, ...] | None = None,
    aggregate: float | None = None,
    min_count: int = 2,
    max_rows: int = 2,
) -> list[FaceBars]:
    """Bar choices of one beam face for ``required`` [mm²], best first: one diameter, at least
    ``min_count`` bars, in at most ``max_rows`` rows at the least clear spacing (ACI 25.2.1);
    ranked by :attr:`FaceBars.score` (the steel, extra rows and the number of bars).
    ``diameters`` default: the pack's main bars."""
    from saengine.design.rc import bars_per_row

    if diameters is None:
        diameters = diameters_of("main")

    options: list[FaceBars] = []
    for dia in diameters:
        count = max(min_count, math.ceil(required / bar_area(dia) - 1e-9))
        fit = bars_per_row(width, inset, dia, aggregate)
        rows = math.ceil(count / fit)
        if rows > max_rows:
            continue
        options.append(FaceBars(count, dia, rows))
    options.sort(key=lambda o: (round(o.score, 1), o.count, o.dia))
    return options


@dataclass(frozen=True)
class Mesh:
    dia: float
    spacing: float

    @property
    def area(self) -> float:
        """mm²/m."""
        return bar_area(self.dia) * 1000 / self.spacing

    def label(self) -> str:
        return f"Ø{self.dia:g} @ {self.spacing:g}"


def mesh_for(
    required: float,
    s_max: float,
    diameters: tuple[float, ...] | None = None,
    min_spacing: float | None = None,
    required_of: dict[float, float] | None = None,
) -> Mesh | None:
    """The slab or footing mesh with the least steel giving ``required`` [mm²/m] (or, per
    diameter, ``required_of[dia]`` when the requirement depends on the bar through d), the
    spacing rounded down to 25 mm and at most ``s_max``; a wider spacing on a tie; None when
    every diameter needs bars closer than ``min_spacing``. Defaults: the pack's slab diameters
    and least slab spacing."""
    if diameters is None:
        diameters = diameters_of("slab")
    if min_spacing is None:
        min_spacing = min_slab_spacing()
    step = spacing_step()
    best: Mesh | None = None
    for dia in diameters:
        need = (required_of or {}).get(dia, required)
        spacing = round_down(s_max, step)
        if need > 0:
            spacing = min(spacing, round_down(bar_area(dia) * 1000 / need, step))
        if spacing < min_spacing:
            continue
        option = Mesh(dia, spacing)
        if best is None or (round(option.area, 3), -option.spacing) < (
            round(best.area, 3),
            -best.spacing,
        ):
            best = option
    return best


# ─────────────────────────────────────── columns ───────────────────────────────────────


def column_min_clear(dia: float, aggregate: float | None = None) -> float:
    """Least clear spacing of column bars (ACI 25.2.3)."""
    return max(40.0, 1.5 * dia, 4 / 3 * aggregate if aggregate else 0.0)


@dataclass(frozen=True)
class ColumnLayout:
    """Equal bars round a column: ``count`` Ø``dia``; on a rectangle ``per_x`` bars between the
    corners on each face along the width (x) and ``per_y`` on each face along the depth, as
    :func:`saengine.design.rc.section_of` lays out a perimeter group."""

    count: int
    dia: float
    per_x: int = 0
    per_y: int = 0
    circle: bool = False

    @property
    def area(self) -> float:
        return self.count * bar_area(self.dia)

    def label(self) -> str:
        return f"{self.count}Ø{self.dia:g}"


def column_layouts(
    shape: str,
    b: float,
    h: float,
    inset: float,
    diameters: tuple[float, ...] | None = None,
    aggregate: float | None = None,
    rho_min: float | None = None,
    rho_max: float | None = None,
) -> list[ColumnLayout]:
    """The symmetric layouts of a rectangular (``b`` x ``h``) or circular (``b`` the diameter)
    column with a steel ratio in [``rho_min``, ``rho_max``] (ACI 10.6.1.1, 10.7.3.1: at least 4
    bars in a rectangle, 6 in a circle) and the least clear spacing of ACI 25.2.3, by area
    (fewer bars first on a tie). A square column (sides within 10 %) gets the same number of bars
    on each face (4, 8, 12, ... bars); a rectangle shares the bars between its faces in proportion
    to their lengths, as :func:`saengine.design.rc.section_of` lays them out. Defaults: the
    pack's column diameters and :func:`column_rho`."""
    if diameters is None:
        diameters = diameters_of("column")
    if rho_min is None or rho_max is None:
        low, high = column_rho()
        rho_min = low if rho_min is None else rho_min
        rho_max = high if rho_max is None else rho_max
    layouts: list[ColumnLayout] = []
    if shape == "circle":
        gross = math.pi * b**2 / 4
        for dia in diameters:
            ring = math.pi * (b - 2 * inset - dia)
            for count in range(6, 61, 2):
                area = count * bar_area(dia)
                if area > rho_max * gross:
                    break
                if ring / count - dia < column_min_clear(dia, aggregate):
                    break
                if area >= rho_min * gross:
                    layouts.append(ColumnLayout(count, dia, circle=True))
    else:
        gross = b * h
        for dia in diameters:
            for count in range(4, 81, 2):
                area = count * bar_area(dia)
                if area > rho_max * gross:
                    break
                pairs = (count - 4) // 2
                per_x = round(pairs * b / (b + h))
                per_y = pairs - per_x
                if abs(b - h) <= 0.1 * max(b, h) and per_x != per_y:
                    # A square (or nearly square) column takes the same bars on all four faces:
                    # an odd number of pairs would load two faces only.
                    continue
                clear_x = (b - 2 * inset - dia) / (per_x + 1) - dia
                clear_y = (h - 2 * inset - dia) / (per_y + 1) - dia
                if min(clear_x, clear_y) < column_min_clear(dia, aggregate):
                    continue
                if area >= rho_min * gross:
                    layouts.append(ColumnLayout(count, dia, per_x, per_y))
    layouts.sort(key=lambda o: (round(o.area, 1), o.count))
    return layouts


@dataclass(frozen=True)
class Ties:
    dia: float
    spacing: float
    legs: int
    notes: tuple[str, ...] = field(default=())


def column_ties(
    layout: ColumnLayout,
    least_dimension: float,
    b: float,
    h: float,
    cover: float,
    diameters: tuple[float, ...] | None = None,
) -> Ties:
    """Ties of a column (ACI 25.7.2, see the module notes); ``legs``: the larger number of tie
    legs across either face (crossties included) that hold the bars per 25.7.2.3.
    ``diameters`` default: the pack's stirrup diameters."""
    if diameters is None:
        diameters = diameters_of("stirrup")
    notes: list[str] = []
    wanted = 10.0 if layout.dia <= 32 else 13.0
    usable = [d for d in diameters if d >= wanted]
    if usable:
        dia = min(usable)
    else:
        dia = max(diameters)
        notes.append(f"Ø{wanted:g} ties are required (ACI 25.7.2.2); Ø{dia:g} is the largest given")
    spacing = round_down(min(16 * layout.dia, 48 * dia, least_dimension))
    if layout.circle:
        return Ties(dia, spacing, 2, tuple(notes))
    inset = cover + dia

    def held(bars_on_face: int, length: float) -> int:
        """Bars held on a face of ``bars_on_face`` (corners included) by 25.7.2.3."""
        if bars_on_face <= 2:
            return 2
        clear = (length - 2 * inset - layout.dia) / (bars_on_face - 1) - layout.dia
        if clear > 150:  # every bar within 150 mm of a held one: all held
            return bars_on_face
        return 2 + (bars_on_face - 2) // 2  # the corners and every other bar between them

    legs = max(held(layout.per_x + 2, b), held(layout.per_y + 2, h))
    return Ties(dia, spacing, legs, tuple(notes))

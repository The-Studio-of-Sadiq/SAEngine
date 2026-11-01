"""Allowable stress (working stress) design of masonry walls: the ``"allowableStress"`` method
of the code pack's ``masonry`` table.

The forces are the wall piers' under the code pack's allowable stress combinations (the shell
model's section cuts at the bottom, middle and top of each storey band; :mod:`saengine.design.
wall_design` forms them). Stresses are linear: the gross section of plain masonry, a cracked
transformed section (no tension in the masonry, the bars in tension elastic, n = Es/Em) of
reinforced masonry. The allowable masonry stresses are the pack's share of the full values when
the masonry is not built under special inspection with prism tests (or f'm is estimated), and
are increased by the pack's factor in the combinations with wind or earthquake.

Per pier, the governing combination of each check:

- both: slenderness h'/t (h' the clear height, twice it with a free top), least thickness of a
  bearing wall, axial stress fa = P/Ae ≤ Fa = (f'm/5)[1 - (h'/42t)³], combined fa/Fa + fb/Fb ≤
  1 with Fb = 0.33 f'm ≤ 10 MPa, out-of-plane shear against the flexural members' Fv; a
  basement wall's deemed-to-satisfy thickness as a flag, walls longer than the pack's limit
  noted (their supports are the analysis's);
- plain masonry: fb = M/S in and out of plane on the gross section, the net tension fb - fa ≤
  Ft (normal to the bed joints, by unit and mortar grade), in-plane shear fv = V/Ae ≤ Fv;
- reinforced masonry: the cracked section in and out of plane (the bars in compression not
  counted: they are not tied), steel fs ≤ Fs, in-plane shear fv = V/(t j d) against Table
  6.7.4 with the masonry or the reinforcement taking it all (Av = s V/(Fs d)), the bar size,
  clear spacing and shear bar spacing; h/t above the pack's limit flagged (second-order
  analysis).

The numbers and the clause of each check are the pack's (``masonry.json``).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from saengine.design import masonry as M
from saengine.design import masonry_dimensions as D
from saengine.design import walls as W
from saengine.design.ductile_members import _row
from saengine.design.rc import DesignError, bar_area

#: The combinations this method checks: the code pack's allowable stress combinations.
COMBINATIONS = "allowable"


def _t() -> Any:
    return M.table()


def method_text() -> list[str]:
    a = _t().allowable
    share = float(_t().quality.reducedShare)
    increase = float(_t().lateralIncrease.factor)
    return [
        f"Masonry walls ({M.clause('chapter')}, allowable stress design): structural walls of "
        "a masonry material, from the pier forces of the shell model (section cuts at the "
        "bottom, middle and top of each storey band) under the code pack's allowable stress "
        f"combinations. Allowable masonry stresses: Fa = {float(a.axial.fmShare):g} f'm [1 - "
        f"(h'/{float(a.axial.slenderness):g}t)^{float(a.axial.exponent):g}] "
        f"({M.clause('axial')}), Fb = {float(a.flexuralCompression.fmShare):g} f'm ≤ "
        f"{float(a.flexuralCompression.cap):g} MPa ({M.clause('flexuralCompression')}), Ft "
        f"({M.clause('flexuralTension')}), Fv ({M.clause('wallShearPlain')}; "
        f"{M.clause('wallShearReinforced')}); {share:.0%} of them without special inspection "
        f"and prism tests ({M.clause('quality')}); × {increase:.3g} with wind or earthquake "
        f"({M.clause('lateralIncrease')}). Combined fa/Fa + fb/Fb ≤ 1 "
        f"({M.clause('interaction')}). Plain masonry on the gross section; reinforced masonry "
        "on the cracked transformed section (n = Es/Em, no masonry tension, bars in "
        "compression not counted), steel Fs = 0.5 fy ≤ 165 MPa "
        f"({M.clause('steel')}), shear fv = V/(t j d) ({M.clause('reinforcedShear')}). "
        f"Slenderness h'/t ≤ {D.slenderness_limit('wall'):g} ({M.clause('slenderness')}), "
        f"least bearing wall thickness ({M.clause('minimumThickness')})."
    ]


# ─────────────────────────────────────── allowable stresses ───────────────────────────────────────


def allowable_axial(fm: float, h_eff: float, t: float) -> float:
    """Fa [MPa] of unreinforced walls and columns and reinforced walls (full value)."""
    a = _t().allowable.axial
    return float(a.fmShare) * fm * (1.0 - (h_eff / (float(a.slenderness) * t)) ** float(a.exponent))


def allowable_axial_column(fm: float, h_eff: float, t: float, steel: float, gross: float, fsc: float) -> float:
    """Fa [MPa] of a reinforced masonry column (full value): (f'm/5 + As Fsc/(1.5 Ag)) [1 -
    (h'/42t)³]."""
    a = _t().allowable.axial
    reduction = 1.0 - (h_eff / (float(a.slenderness) * t)) ** float(a.exponent)
    return (float(a.fmShare) * fm + steel * fsc / (float(a.columnSteelArea) * gross)) * reduction


def allowable_flexural_compression(fm: float) -> float:
    """Fb [MPa] (full value)."""
    b = _t().allowable.flexuralCompression
    return min(float(b.fmShare) * fm, float(b.cap))


def allowable_flexural_tension(m: M.Masonry, normal_to: str = "bed") -> float:
    """Ft [MPa] of masonry without tensile reinforcement (full value): normal to the bed
    joints, or to the head joints (running bond; none in stack bond), by the units and the
    mortar grade (the full values with the pack's richer grades, reduced with the next ones,
    none with the rest or an unknown grade)."""
    ft = _t().allowable.flexuralTension
    if m.mortar in ft.fullMortars:
        factor = 1.0
    elif m.mortar in ft.reducedMortars:
        factor = 1.0 - float(ft.reduction)
    else:
        return 0.0
    if normal_to == "bed":
        return factor * float(ft.bedJoints[m.units])
    if m.bond == "stack":
        return 0.0
    return factor * float(ft.headJointsByUnit[m.kind][m.units])


def allowable_beam_shear(fm: float, reinforced: bool = False) -> float:
    """Fv [MPa] of flexural members (full value): without shear reinforcement, or with it
    taking all the shear."""
    row = _t().allowable.beamShear.reinforced if reinforced else _t().allowable.beamShear.unreinforced
    return min(float(row.factor) * math.sqrt(fm), float(row.cap))


def allowable_wall_shear_plain(m: M.Masonry) -> float:
    """Fv [MPa] of unreinforced shear walls (full value): clay units by √f'm, concrete units by
    mortar grade (none with a grade the pack does not list)."""
    s = _t().allowable.wallShearPlain
    if m.kind == "clay":
        return min(float(s.clay.factor) * math.sqrt(m.fm), float(s.clay.cap))
    return float(s.concrete.get(m.mortar or "", 0.0))


def allowable_wall_shear_reinforced(fm: float, ratio: float, reinforcement: bool) -> float:
    """Fv [MPa] of reinforced masonry shear walls (full value) at M/Vd = ``ratio``: the
    masonry taking all the shear, or the reinforcement (``reinforcement``)."""
    w = _t().allowable.wallShearReinforced
    row = w.reinforcement if reinforcement else w.masonry
    ratio = max(ratio, 0.0)
    root = math.sqrt(fm)
    if ratio < 1.0:
        value = (float(row.first) - ratio) / float(row.divisor) * root
        cap = float(row.maxFirst) - float(row.maxSlope) * ratio
    else:
        value = float(row.above) * root
        cap = float(row.maxAbove)
    return min(value, cap)


def allowable_steel(fy: float, kind: str = "tensionDeformed") -> float:
    """Fs or Fsc [MPa]: ``kind`` tensionDeformed, tensionPlain, compressionWalls or
    compressionFlexural."""
    row = _t().allowable.steel[kind]
    return min(float(row.fyShare) * fy, float(row.cap))


def bond_stress(deformed: bool = True) -> float:
    """Allowable bond stress u [MPa]."""
    return float(_t().allowable.bond["deformed" if deformed else "plain"])


def lateral_factor(combination: str | None, lateral: Iterable[str]) -> float:
    """The pack's increase of the allowable stresses for a combination with wind or
    earthquake, else 1."""
    names = set(lateral)
    if combination and (combination in names or combination.rsplit(" [", 1)[0] in names):
        return float(_t().lateralIncrease.factor)
    return 1.0


# ─────────────────────────────────────── section stresses ───────────────────────────────────────


def design_coefficients(n: float, rho: float) -> tuple[float, float]:
    """(k, j) of a rectangular flexural element: k = √((nρ)² + 2nρ) - nρ, j = 1 - k/3."""
    nr = n * rho
    k = math.sqrt(nr * nr + 2.0 * nr) - nr
    return k, 1.0 - k / 3.0


def flexural_stresses(m_: float, b: float, d: float, steel: float, n: float) -> tuple[float, float]:
    """(fb, fs) [MPa] of a rectangular flexural element under ``m_`` [N·mm]: fb = (M/bd²)(2/jk),
    fs = M/(As j d)."""
    k, j = design_coefficients(n, steel / (b * d))
    return m_ / (b * d * d) * 2.0 / (j * k), m_ / (steel * j * d)


def cracked_section(
    depth: float,
    width: float,
    bars: list[tuple[float, float]],
    n_force: float,
    moment: float,
    n: float,
) -> tuple[float, float, float]:
    """(largest masonry compression, largest steel tension, neutral axis c) [MPa, MPa, mm] of a
    rectangular section ``depth`` × ``width`` with ``bars`` ``(x from the compression face,
    area)`` under the axial force ``n_force`` [N, compression positive] and the moment
    ``moment`` [N·mm, ≥ 0], linear stresses: the masonry carries no tension, the bars in tension
    are elastic (n = Es/Em), the bars in compression are not counted. Uncracked (the gross
    section in compression throughout): the gross stresses, no steel tension. ``inf`` when no
    equilibrium exists (net tension the bars cannot take)."""
    moment = abs(moment)
    area = depth * width
    modulus = width * depth**2 / 6.0
    if n_force > 0 and n_force / area - moment / modulus >= -1e-12:
        return n_force / area + moment / modulus, 0.0, math.inf
    steel_area = sum(a for _, a in bars)
    if moment <= 1e-9 * max(abs(n_force), 1.0) * depth:
        # Net tension without bending: the bars take it all.
        return 0.0, (-n_force / steel_area if steel_area > 0 else math.inf), 0.0

    def resultants(c: float) -> tuple[float, float]:
        a = min(c, depth)
        # Masonry: σ (c - x)/c over 0..a, per unit σmax.
        force = width * (a * c - a * a / 2.0) / c
        lever = width * ((depth / 2.0) * (a * c - a * a / 2.0) - (c * a * a / 2.0 - a**3 / 3.0)) / c
        for x, steel in bars:
            if x > c:
                t = n * steel * (x - c) / c
                force -= t
                lever += t * (x - depth / 2.0)
        return force, lever

    def gap(c: float) -> float:
        force, lever = resultants(c)
        return force * moment - lever * n_force

    grid = [depth * 10 ** (k / 40.0 - 3.0) for k in range(0, 121)]  # 0.001 depth to 1 depth
    previous = None
    root = None
    for c in grid:
        value = gap(c)
        if previous is not None and (previous[1] <= 0 <= value or value <= 0 <= previous[1]):
            lo, hi = previous[0], c
            for _ in range(80):
                mid = 0.5 * (lo + hi)
                if (gap(lo) <= 0) == (gap(mid) <= 0):
                    lo = mid
                else:
                    hi = mid
            candidate = 0.5 * (lo + hi)
            _force, lever = resultants(candidate)
            if lever > 0:
                root = candidate
                break
        previous = (c, value)
    if root is None:
        return math.inf, math.inf, 0.0
    _force, lever = resultants(root)
    sigma = moment / lever if lever > 0 else math.inf
    far = max((x for x, _ in bars if x > root), default=None)
    fs = n * sigma * (far - root) / root if far is not None else 0.0
    return sigma, fs, root


def _wall_bars(lw: float, bars: W.WallBars) -> list[tuple[float, float]]:
    """The vertical bars along the wall: ``(x from one end, area of the layers there)``."""
    end = bars.cover + bars.horizontal_dia + bars.vertical_dia / 2
    if lw <= 2 * end:
        raise DesignError("the wall is too short for its bars and cover")
    area = bars.layers * bar_area(bars.vertical_dia)
    return [(x, area) for x in W._positions(end, lw - end, bars.vertical_spacing)]


# ─────────────────────────────────────────── the checks ───────────────────────────────────────────


def _worst(rows: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    return max(rows, key=lambda r: r["utilisation"], default=None)


def _flag(name: str, demand: float, capacity: float, unit: str, note: str) -> dict[str, Any]:
    row = _row(name, demand, capacity, unit, note=note)
    row["flag"] = True
    return row


def wall_checks(
    geometry: W.WallGeometry,
    bars: W.WallBars | None,
    forces: list[W.PierForces],
    m: M.Masonry,
    fy: float = 420.0,
    lateral: Iterable[str] = (),
    storeys: int | None = None,
) -> M.MasonryDesign:
    """The allowable stress checks of a masonry wall pier (see the module notes). ``forces``:
    service forces under the allowable stress combinations, compression positive [N, N·mm];
    ``lateral``: the combinations with wind or earthquake."""
    lateral = set(lateral)
    t, lw, h = geometry.thickness, geometry.length, geometry.clear_height
    ae = t * lw  # solid units or grouted cells: the effective area is the gross area
    s_in = t * lw**2 / 6.0
    s_out = lw * t**2 / 6.0
    h_eff = D.effective_height(h, geometry.braced)
    share = M.allowable_share(m)
    notes: list[str] = list(m.notes)
    checks: list[dict[str, Any]] = []
    if share < 1.0:
        notes.append(
            f"{share:.0%} of the allowable masonry stresses ({M.clause('quality')}): "
            + (
                "f'm is estimated, not from prism tests"
                if m.fm_source == "estimate"
                else "no special inspection with prism tests entered on the masonry material"
            )
        )
    if m.units == "hollow" and not m.grouted:
        notes.append(
            "hollow units: the section is taken as solid (effective = gross area); "
            f"{M.clause('effectiveArea')} takes the least bedded area: check the face shells by "
            "hand or grout the cells"
        )
    if D.needs_stability_analysis(lw):
        notes.append(
            f"wall longer than {float(_t().dimensions.stability.lengthNeedingAnalysis) / 1e3:g} m "
            f"({M.clause('lengthNeedingAnalysis')}): its lateral supports are the shell model's"
        )

    # Geometry: slenderness and the least thickness of a bearing wall.
    limit = D.slenderness_limit("wall")
    checks.append(
        _row(
            f"Slenderness h'/t ≤ {limit:g} ({M.clause('slenderness')})",
            h_eff / t,
            limit,
            "",
            note=f"h' = {h_eff:.0f} mm ({M.clause('effectiveHeight')})"
            + ("" if geometry.braced else ", free top"),
        )
    )
    bearing = any(f.P > 0 for f in forces)
    if bearing:
        least = D.minimum_bearing_thickness(storeys, geometry.height)
        checks.append(
            _row(
                f"Bearing wall thickness ≥ {least:.0f} mm ({M.clause('minimumThickness')})",
                least,
                t,
                "mm",
            )
        )
    if geometry.basement:
        dead = [f for f in forces if (f.combination or "").strip() == "D"]
        load = max((f.P for f in dead), default=0.0) / lw  # N/mm = kN/m
        ground = D.basement_ground_height(t, load)
        checks.append(
            _flag(
                f"Basement wall: ground height ≤ table height ({M.clause('basement')})",
                h,
                ground or 0.0,
                "mm",
                "deemed to satisfy the stability (the wall is also checked by analysis); the "
                "clear height taken as the ground height above the basement floor"
                + ("" if ground else "; thinner than the table: by analysis only"),
            )
        )
    if not forces:
        return M.MasonryDesign([c for c in checks if c], notes + ["no forces: not checked"], 0.0)

    fa_full = allowable_axial(m.fm, h_eff, t)
    fb_full = allowable_flexural_compression(m.fm)
    fv_out_full = allowable_beam_shear(m.fm, reinforced=False)

    def where(f: W.PierForces) -> str:
        return f.where or ""

    def factor(f: W.PierForces) -> float:
        return share * lateral_factor(f.combination, lateral)

    def increase_note(f: W.PierForces) -> str:
        k = lateral_factor(f.combination, lateral)
        return f"; × {k:.3g} (wind or earthquake)" if k > 1 else ""

    axial, combined, shear_out = [], [], []
    for f in forces:
        fa = max(f.P, 0.0) / ae
        axial.append(
            _row(
                f"Axial stress fa ≤ Fa ({M.clause('axial')})",
                fa,
                factor(f) * fa_full,
                "MPa",
                f.combination,
                f"{where(f)}; h'/t = {h_eff / t:.1f}{increase_note(f)}",
            )
        )
        shear_out.append(
            _row(
                f"Out-of-plane shear fv ≤ Fv ({M.clause('plainStresses')})",
                abs(f.V3) / ae,
                factor(f) * fv_out_full,
                "MPa",
                f.combination,
                where(f),
            )
        )
    checks.append(_worst(axial))

    if bars is None:
        ft_full = allowable_flexural_tension(m, "bed")
        fv_full = allowable_wall_shear_plain(m)
        tension, shear = [], []
        for f in forces:
            k = factor(f)
            fa = f.P / ae
            fb = abs(f.M3) / s_in + abs(f.M2) / s_out
            combined.append(
                _row(
                    f"Combined fa/Fa + fb/Fb ≤ 1 ({M.clause('interaction')})",
                    max(fa, 0.0) / (k * fa_full) + fb / (k * fb_full),
                    float(_t().allowable.interaction),
                    "",
                    f.combination,
                    f"{where(f)}; fb = M/S in and out of plane {fb:.2f} MPa, Fb "
                    f"{k * fb_full:.2f} MPa{increase_note(f)}",
                )
            )
            tension.append(
                _row(
                    f"Flexural tension fb - fa ≤ Ft ({M.clause('flexuralTension')})",
                    max(fb - fa, 0.0),
                    k * ft_full,
                    "MPa",
                    f.combination,
                    f"{where(f)}; normal to the bed joints, mortar {m.mortar or 'of unknown grade'}"
                    f"{increase_note(f)}",
                )
            )
            shear.append(
                _row(
                    f"In-plane shear fv = V/Ae ≤ Fv ({M.clause('wallShearPlain')})",
                    abs(f.V2) / ae,
                    k * fv_full,
                    "MPa",
                    f.combination,
                    f"{where(f)}{increase_note(f)}",
                )
            )
        for group in (combined, tension, shear, shear_out):
            checks.append(_worst(group))
    else:
        checks += _reinforced(geometry, bars, forces, m, fy, factor, increase_note, where, notes)
        checks.append(_worst(shear_out))
    found = [c for c in checks if c]
    strength = [c for c in found if not c["flag"]]
    utilisation = max((c["utilisation"] for c in strength), default=0.0)
    return M.MasonryDesign(found, notes, utilisation)


def _reinforced(
    geometry: W.WallGeometry,
    bars: W.WallBars,
    forces: list[W.PierForces],
    m: M.Masonry,
    fy: float,
    factor: Any,
    increase_note: Any,
    where: Any,
    notes: list[str],
) -> list[dict[str, Any] | None]:
    """The reinforced masonry rows of :func:`wall_checks`."""
    table = _t()
    t, lw, h = geometry.thickness, geometry.length, geometry.clear_height
    ae = t * lw
    h_eff = D.effective_height(h, geometry.braced)
    n = float(table.elastic.es) / m.em
    fa_full = allowable_axial(m.fm, h_eff, t)
    fb_full = allowable_flexural_compression(m.fm)
    fs_allow = allowable_steel(fy, "tensionDeformed")
    layout = _wall_bars(lw, bars)
    one = bar_area(bars.vertical_dia)
    d_in = max(x for x, _ in layout)
    steel_total = sum(a for _, a in layout)
    _k, j_in = design_coefficients(n, steel_total / 2.0 / (t * d_in))
    # Out of plane: the bars' effective width (running or stack bond), one layer at the centre
    # or two at the faces (the far layer in tension).
    count = len(layout)
    width = min(lw, count * D.reinforced_effective_width(t, bars.vertical_spacing, m.bond))
    if bars.layers == 2:
        face = t / 2 - bars.cover - bars.horizontal_dia - bars.vertical_dia / 2
        out_bars = [(t / 2 + face, count * one)]
    else:
        out_bars = [(t / 2, count * one)]
    av_s = bars.layers * bar_area(bars.horizontal_dia) / bars.horizontal_spacing
    combined, steel_in, steel_out, shear = [], [], [], []
    needs_steel = False
    for f in forces:
        k = factor(f)
        fa = max(f.P, 0.0) / ae
        f_in, fs_in, _c = cracked_section(lw, t, layout, f.P, f.M3, n)
        p_strip = f.P * width / lw
        f_out, fs_out, _c = cracked_section(t, width, out_bars, p_strip, f.M2 * width / lw, n)
        fb = max(f_in - max(f.P, 0.0) / ae, 0.0) + max(f_out - max(p_strip, 0.0) / (t * width), 0.0)
        combined.append(
            _row(
                f"Combined fa/Fa + fb/Fb ≤ 1 ({M.clause('reinforcedCombined')}; "
                f"{M.clause('interaction')})",
                fa / (k * fa_full) + fb / (k * fb_full),
                float(table.allowable.interaction),
                "",
                f.combination,
                f"{where(f)}; cracked section, fb {fb:.2f} MPa (in plane {f_in:.2f}, out of plane "
                f"{f_out:.2f} MPa at the extreme fibre), Fb {k * fb_full:.2f} MPa"
                f"{increase_note(f)}",
            )
        )
        steel_in.append(
            _row(
                f"In-plane steel stress fs ≤ Fs ({M.clause('steel')})",
                fs_in,
                fs_allow,
                "MPa",
                f.combination,
                f"{where(f)}; n = {n:.1f}",
            )
        )
        steel_out.append(
            _row(
                f"Out-of-plane steel stress fs ≤ Fs ({M.clause('steel')})",
                fs_out,
                fs_allow,
                "MPa",
                f.combination,
                f"{where(f)}; effective width {width:.0f} mm ({M.clause('reinforcedWidth')})",
            )
        )
        v = abs(f.V2)
        fv = v / (t * j_in * d_in)
        ratio = abs(f.M3) / (v * d_in) if v > 0 else 1.0
        masonry_fv = k * allowable_wall_shear_reinforced(m.fm, ratio, reinforcement=False)
        if fv <= masonry_fv:
            shear.append(
                _row(
                    f"In-plane shear fv = V/(t j d) ≤ Fv ({M.clause('wallShearReinforced')})",
                    fv,
                    masonry_fv,
                    "MPa",
                    f.combination,
                    f"{where(f)}; masonry taking all the shear, M/Vd = {ratio:.2f}"
                    f"{increase_note(f)}",
                )
            )
            continue
        needs_steel = True
        steel_fv = k * allowable_wall_shear_reinforced(m.fm, ratio, reinforcement=True)
        need = v / (fs_allow * d_in)
        row = _row(
            f"In-plane shear fv = V/(t j d) ≤ Fv ({M.clause('wallShearReinforced')})",
            fv,
            steel_fv,
            "MPa",
            f.combination,
            f"{where(f)}; reinforcement taking all the shear, M/Vd = {ratio:.2f}; Av/s needed "
            f"{need:.3f} mm²/mm, provided {av_s:.3f} ({M.clause('reinforcedShear')})"
            f"{increase_note(f)}",
            utilisation=max(fv / steel_fv if steel_fv > 0 else math.inf, need / av_s),
        )
        shear.append(row)
    rows: list[dict[str, Any] | None] = [
        _worst(combined),
        _worst(steel_in),
        _worst(steel_out),
        _worst(shear),
    ]
    # Bar details.
    r = table.reinforcement
    rows.append(
        _row(
            f"Bar diameter ≤ {float(r.maxBarDia):g} mm ({M.clause('details')})",
            max(bars.vertical_dia, bars.horizontal_dia),
            float(r.maxBarDia),
            "mm",
        )
    )
    clear = bars.vertical_spacing - bars.vertical_dia
    rows.append(
        _row(
            f"Clear spacing of the vertical bars ({M.clause('details')})",
            D.least_clear_spacing(bars.vertical_dia),
            clear,
            "mm",
        )
    )
    rows.append(
        _flag(
            f"Cover ≥ {D.least_cover('interior'):g} mm ({M.clause('details')})",
            D.least_cover("interior"),
            bars.cover,
            "mm",
            f"not exposed to weather; {D.least_cover('weather'):g} mm exposed to weather, "
            f"{D.least_cover('soil'):g} mm exposed to soil",
        )
    )
    if needs_steel:
        rows.append(
            _row(
                f"Shear bar spacing ≤ d/2 and {float(r.shearSpacing['max']):g} mm "
                f"({M.clause('reinforcedShear')})",
                bars.horizontal_spacing,
                D.shear_spacing_limit(d_in),
                "mm",
            )
        )
    limit = float(table.dimensions.heightThicknessAnalysis)
    if h / t > limit:
        rows.append(
            _flag(
                f"h/t ≤ {limit:g} without second-order analysis ({M.clause('reinforcedCombined')})",
                h / t,
                limit,
                "",
                "above it the forces need a second-order analysis with the cracked stiffness",
            )
        )
    if bars.boundary is not None:
        notes.append("the wall type's end bars are not counted in a masonry wall")
    return rows


__all__ = [
    "COMBINATIONS",
    "allowable_axial",
    "allowable_axial_column",
    "allowable_beam_shear",
    "allowable_flexural_compression",
    "allowable_flexural_tension",
    "allowable_steel",
    "allowable_wall_shear_plain",
    "allowable_wall_shear_reinforced",
    "bond_stress",
    "cracked_section",
    "design_coefficients",
    "flexural_stresses",
    "lateral_factor",
    "method_text",
    "wall_checks",
]

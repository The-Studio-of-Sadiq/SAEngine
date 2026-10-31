"""Masonry walls to BNBC 2020 Part 6 Chapter 7 (strength design).

Unreinforced (plain) and reinforced masonry walls of 06 BIM: a structural wall whose 04 Objects
type has a masonry material (03 Materials, category "masonry") is designed here instead of as
reinforced concrete (:mod:`saengine.design.wall_design` routes it). A type with vertical and
horizontal bars (``reinforcement``) is reinforced masonry, one without is plain masonry. The
forces are the piers' of :mod:`saengine.design.wall_forces` (the shell model's section cuts at
the bottom, middle and top of each storey band, factored combinations), so the method is
strength design.

The clauses are those of the strength design chapter of the MSJC (TMS 402 / ACI 530-08
Chapter 3), which BNBC 2020 Part 6 Chapter 7 follows for masonry; the numbers are in the code
pack (``masonry.json``) with their sources. SI forms: a ``c √f'm`` psi limit is ``0.083 c √f'm``
MPa.

Per pier, the governing combination of each check:

- plain masonry: axial strength φPn (Eqs. 3-15, 3-16), the net flexural tension in-plane and
  out-of-plane against φ fr (Sec 3.2.2, Table 3.1.8.2), the compressive stress with bending
  against 0.80 f'm, in-plane shear (Sec 3.2.4);
- reinforced masonry: axial strength (Eqs. 3-18, 3-19, the bars in compression not counted as
  they are not tied, Sec 3.3.2), in-plane axial force and bending by strain compatibility (Sec
  3.3.2: εmu, the 0.80 f'm block over 0.80 c, bars elastic-plastic), the largest steel (Sec
  3.3.3.5, α εy at the extreme bar), in-plane shear (Sec 3.3.4.1.2), out-of-plane bending of
  the wall strip (Sec 3.3.5, with Pu/Ag and h/t limits), the bar spacing and size of ordinary
  reinforced masonry shear walls (Sec 1.17.3.2.3.1);
- both: f'm within the strength design range (Sec 3.1.8.1.1) as a flag.

Not included: the slender-wall P-delta moment of Sec 3.3.5.4 (the out-of-plane moments are the
analysis's), bearing under concentrated loads, the empirical design of Chapter 5, allowable
stress design, and confined masonry (planned).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from saengine.codes import context as code_context
from saengine.design import walls as W
from saengine.design.ductile_members import _row
from saengine.design.rc import STEEL_E, DesignError, bar_area

CODE = "BNBC 2020 Part 6 Chapter 7 (strength design; TMS 402 / ACI 530-08 Chapter 3)"
CLAUSE = "BNBC 2020 Part 6 Ch 7"

METHOD = [
    (
        f"Masonry walls ({CODE}): structural walls of a masonry material, from the same pier "
        "forces as the concrete walls (section cuts of the shell model at the bottom, middle "
        "and top of each storey band, factored combinations). Plain masonry: φPn = φ 0.80 "
        "[0.80 An f'm] R(h/r) with R = 1 - (h/140r)² up to h/r = 99 and (70r/h)² above "
        "(φ 0.60); net flexural tension in-plane and out-of-plane Mu/S - Pu/An ≤ φ fr; "
        "compressive stress Pu/An + Mu/S ≤ 0.80 f'm; shear Vn the least of 0.316 An √f'm, "
        "2.07 An and the bond's constant An + 0.45 Nu (φ 0.80). Reinforced masonry: the same "
        "axial strength without the bars in compression (φ 0.90); P-M by strain compatibility "
        "(εmu 0.0035 clay, 0.0025 concrete, 0.80 f'm over a = 0.80 c); the extreme bar strain "
        "at least 1.5 εy at εmu (largest steel); shear Vnm + Vns with Vn ≤ 0.50 to 0.33 An "
        "√f'm by Mu/(Vu dv); out-of-plane Mn = (As fy + Pu)(d - a/2), Pu/Ag ≤ 0.20 f'm and "
        "h/t ≤ 30 above 0.05 f'm; bars of ordinary reinforced masonry shear walls at most "
        "3048 mm apart. The out-of-plane P-delta of slender walls (Sec 3.3.5.4) is not added."
    ),
]


# ─────────────────────────────────────── pack data ───────────────────────────────────────


def _table() -> Any:
    return code_context.pack_table("masonry")


def phi(name: str) -> float:
    """φ ``name`` of the masonry table (axialFlexureReinforced, axialFlexureUnreinforced,
    shear, bearing)."""
    return float(_table().phi[name])


# ─────────────────────────────────────── the masonry ───────────────────────────────────────


@dataclass(frozen=True)
class Masonry:
    """The masonry of a wall: f'm [MPa] and what its checks depend on."""

    fm: float
    kind: str = "clay"  # "clay" or "concrete"
    mortar: str = "S"  # "M", "S" or "N"
    units: str = "solid"  # "solid" or "hollow"
    grouting: str = "none"  # "none", "partial" or "full"
    bond: str = "running"  # "running" or "stack"
    fm_source: str = "entered"  # "entered" or "units" (from the unit strength)

    @property
    def em(self) -> float:
        """Em = ratio · f'm [MPa] (Sec 1.8.2.2.1)."""
        return float(_table().modulusRatio[self.kind]) * self.fm

    @property
    def emu(self) -> float:
        """εmu (Sec 3.3.2(c))."""
        return float(_table().ultimateStrain[self.kind])

    @property
    def grouted(self) -> bool:
        return self.grouting == "full"


def prism_strength(unit_strength: float, kind: str = "clay", mortar: str = "S") -> float | None:
    """f'm [MPa] from the net-area strength of the units [MPa] and the mortar type (TMS 602 /
    ACI 530.1 Tables 1 and 2, linear between the rows, the top row's f'm above it); None below
    the first row (a prism test is needed)."""
    rows = _table().prismStrength[kind]
    units = rows.MS if mortar in ("M", "S") else rows.N
    if unit_strength < units[0]:
        return None
    if unit_strength >= units[-1]:
        return float(rows.fm[-1])
    for k in range(1, len(units)):
        if unit_strength <= units[k]:
            share = (unit_strength - units[k - 1]) / (units[k] - units[k - 1])
            return float(rows.fm[k - 1] + share * (rows.fm[k] - rows.fm[k - 1]))
    return float(rows.fm[-1])  # pragma: no cover - the loop returns


def mortar_type_of_mix(sand_parts: float) -> str:
    """M, S or N for a cement : sand mix of ``sand_parts`` per part of cement (SAEngine
    practice, the pack's ``mortarFromMix``)."""
    limits = _table().mortarFromMix
    if sand_parts <= float(limits["M"]):
        return "M"
    if sand_parts <= float(limits["S"]):
        return "S"
    return "N"


def masonry_of(material: Any, mats: dict[str, Any] | None = None) -> Masonry:
    """The :class:`Masonry` of a masonry material (``library.materials.Material``); its mortar
    material (``mats``) gives the mortar type when the material has none. Raises
    :class:`DesignError` when neither f'm nor a unit strength in the tables is given."""
    props = getattr(material, "masonry", None)
    if props is None:
        raise DesignError(f"'{getattr(material, 'id', '?')}' is not a masonry material")
    mortar = props.mortarType
    if mortar is None:
        mortar = "S"
        mix = getattr((mats or {}).get(props.mortar or ""), "composition", None)
        ratio = getattr(mix, "ratio", None)
        if ratio and len(ratio) == 2 and ratio[0] > 0:
            mortar = mortar_type_of_mix(ratio[1] / ratio[0])
    kind = props.unitKind
    fm = props.fm
    source = "entered"
    if fm is None and props.unitStrength is not None:
        fm = prism_strength(props.unitStrength, kind, mortar)
        source = "units"
        if fm is None:
            raise DesignError(
                f"the unit strength {props.unitStrength:g} MPa is below the f'm tables (TMS 602 "
                "Tables 1-2): enter f'm from prism tests on the masonry material"
            )
    if fm is None:
        raise DesignError(
            "no masonry strength: enter f'm (prism strength) or the unit strength on the "
            "masonry material (03 Materials)"
        )
    return Masonry(
        float(fm), kind, mortar, props.units, props.grouting, props.bond, fm_source=source
    )


# ─────────────────────────────────────── strengths ───────────────────────────────────────


def slenderness_factor(h: float, r: float) -> float:
    """R(h/r): 1 - (h/140r)² up to h/r = 99, (70r/h)² above (Eqs. 3-15, 3-16)."""
    a = _table().axial
    ratio = h / r
    if ratio <= float(a.slendernessBreak):
        return 1.0 - (h / (float(a.short) * r)) ** 2
    return (float(a.long) * r / h) ** 2


def axial_strength(area: float, fm: float, h: float, r: float) -> float:
    """Pn [N] = 0.80 [0.80 An f'm] R(h/r) (Eqs. 3-15, 3-16; reinforced 3-18, 3-19 without the
    bars in compression, which are not laterally tied in a wall)."""
    a = _table()
    return (
        float(a.axial.reduction)
        * float(a.stressBlock.stress)
        * area
        * fm
        * slenderness_factor(h, r)
    )


def modulus_of_rupture(m: Masonry) -> float:
    """fr normal to the bed joints [MPa] (Table 3.1.8.2): fully grouted, hollow (ungrouted or
    partly grouted) or solid units."""
    key = "grouted" if m.grouted else ("hollow" if m.units == "hollow" else "solid")
    return float(_table().modulusOfRupture[key][m.mortar])


def plain_shear_strength(m: Masonry, an: float, nu: float) -> float:
    """Vn [N] of plain masonry (Sec 3.2.4): the least of 0.316 An √f'm, 2.07 An, and for
    running bond (0.386 not solidly grouted, 0.621 solidly grouted) An + 0.45 Nu, for stack
    bond 0.159 An; ``nu`` the compressive force (tension: 0)."""
    s = _table().plainShear
    nu = max(nu, 0.0)
    limits = [float(s.root) * an * math.sqrt(m.fm), float(s.cap) * an]
    if m.bond == "stack":
        limits.append(float(s.stackBond) * an)
    else:
        base = float(s.runningBondGrouted) if m.grouted else float(s.runningBond)
        limits.append(base * an + float(s.axialShare) * nu)
    return min(limits)


def reinforced_shear_strength(
    an: float, fm: float, mu: float, vu: float, dv: float, pu: float, av_s: float, fy: float
) -> tuple[float, float, float, float]:
    """(Vn, Vnm, Vns, Vn max) [N] of reinforced masonry (Sec 3.3.4.1.2): Vnm = 0.083 [4.0 -
    1.75 Mu/(Vu dv)] An √f'm + 0.25 Pu, Vns = 0.5 (Av/s) fy dv, Vn ≤ 0.50 An √f'm at
    Mu/(Vu dv) ≤ 0.25 and 0.33 An √f'm at ≥ 1.0, linear between; Mu/(Vu dv) is taken
    between 0 and 1. ``pu`` compression positive."""
    s = _table().reinforcedShear
    ratio = abs(mu) / (abs(vu) * dv) if abs(vu) > 0 and dv > 0 else 1.0
    ratio = min(max(ratio, 0.0), 1.0)
    root = an * math.sqrt(fm)
    vnm = float(s.masonry) * (float(s.first) - float(s.slope) * ratio) * root
    vnm = max(vnm + float(s.axialShare) * pu, 0.0)
    vns = float(s.steelShare) * av_s * fy * dv
    low, high = float(s.maxLow), float(s.maxHigh)
    if ratio <= 0.25:
        cap = low * root
    else:
        cap = (low + (high - low) * (ratio - 0.25) / 0.75) * root
    return min(vnm + vns, cap), vnm, vns, cap


def _section_force(
    c: float,
    lw: float,
    t: float,
    bars: list[tuple[float, float]],
    fm: float,
    fy: float,
    es: float,
    emu: float,
) -> tuple[float, float]:
    """(N [N], M [N·mm] about the wall's centre) of a wall section of length ``lw`` with the
    neutral axis ``c`` from its compression end: the 0.80 f'm block over 0.80 c (at most lw),
    the bars ``(x from the compression end, area)`` elastic-plastic in tension; bars in
    compression are not counted (not tied)."""
    block = _table().stressBlock
    a = min(float(block.depth) * c, lw)
    compression = float(block.stress) * fm * t * a
    n = compression
    m = compression * (lw / 2 - a / 2)
    for x, area in bars:
        strain = emu * (c - x) / c
        if strain >= 0:
            continue
        stress = max(es * strain, -fy)
        force = stress * area  # negative: tension
        n += force
        m += force * (lw / 2 - x)
    return n, m


def wall_bar_layout(lw: float, bars: W.WallBars) -> list[tuple[float, float]]:
    """The vertical bars of a reinforced masonry wall along its length: ``(x from one end,
    area of the layers there)``, at the wall type's spacing from end to end."""
    end = bars.cover + bars.horizontal_dia + bars.vertical_dia / 2
    if lw <= 2 * end:
        raise DesignError("the wall is too short for its bars and cover")
    area = bars.layers * bar_area(bars.vertical_dia)
    xs = W._positions(end, lw - end, bars.vertical_spacing)
    return [(x, area) for x in xs]


def in_plane_moment(
    lw: float,
    t: float,
    bars: list[tuple[float, float]],
    fm: float,
    fy: float,
    pu: float,
    emu: float,
    es: float = STEEL_E,
) -> float:
    """Mn [N·mm] of the wall section at the axial force ``pu`` [N, compression positive] by
    strain compatibility (Sec 3.3.2); 0 when ``pu`` is above the section's crushing force or
    below its tension strength. The bars are symmetric, so either end may be in compression."""

    def net(c: float) -> float:
        return _section_force(c, lw, t, bars, fm, fy, es, emu)[0] - pu

    lo, hi = 1e-3 * lw, 50.0 * lw
    if net(lo) > 0 or net(hi) < 0:
        return 0.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if net(mid) > 0:
            hi = mid
        else:
            lo = mid
    c = 0.5 * (lo + hi)
    _, m = _section_force(c, lw, t, bars, fm, fy, es, emu)
    # About the centre, the compression end's block and the far bars give the moment; the
    # axial force acts at the centre and adds none.
    return max(m, 0.0)


def max_steel_ratio(
    lw: float,
    t: float,
    bars: list[tuple[float, float]],
    fm: float,
    fy: float,
    pu: float,
    emu: float,
    alpha: float,
    es: float = STEEL_E,
) -> tuple[float, float]:
    """(T + Pu, C) [N] of the largest steel check (Sec 3.3.3.5): at the strain εmu at the
    compression end and α εy at the extreme tension bar, the bars' tension plus the axial
    force must not exceed the masonry's compression (the bars in compression not counted)."""
    if not bars:
        return 0.0, 1.0
    d = max(x for x, _ in bars)
    ey = fy / es
    c = emu / (emu + alpha * ey) * d
    block = _table().stressBlock
    compression = float(block.stress) * fm * t * min(float(block.depth) * c, lw)
    tension = 0.0
    for x, area in bars:
        strain = emu * (c - x) / c
        if strain < 0:
            tension += min(es * -strain, fy) * area
    return tension + pu, compression


def out_of_plane_moment(
    width: float, d: float, steel: float, fm: float, fy: float, pu: float
) -> float:
    """Mn [N·mm] of a reinforced wall strip of ``width`` bending out of its plane (Sec
    3.3.5.3): (As fy + Pu)(d - a/2), a = (Pu + As fy) / (0.80 f'm b); ``steel`` the bars in
    tension, ``d`` their depth."""
    block = _table().stressBlock
    force = steel * fy + max(pu, 0.0)
    a = force / (float(block.stress) * fm * width)
    return max(force * (d - a / 2), 0.0)


# ─────────────────────────────────────── the checks ───────────────────────────────────────


@dataclass
class MasonryDesign:
    checks: list[dict[str, Any]]
    notes: list[str]
    utilisation: float


def _worst(rows: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    return max(rows, key=lambda r: r["utilisation"], default=None)


def _flag(name: str, note: str) -> dict[str, Any]:
    row = _row(name, 0.0, 0.0, "", note=note, utilisation=0.0)
    row["flag"] = True
    return row


def masonry_wall_checks(
    geometry: W.WallGeometry,
    bars: W.WallBars | None,
    forces: list[W.PierForces],
    m: Masonry,
    fy: float = 420.0,
    es: float = STEEL_E,
    detailing: str = "ordinary",
) -> MasonryDesign:
    """The checks of a masonry wall pier: plain masonry without ``bars``, reinforced masonry
    with them (see the module notes). ``forces`` compression positive [N, N·mm];
    ``detailing``: "ordinary", "intermediate" or "special" (the largest steel's α)."""
    table = _table()
    t, lw, h = geometry.thickness, geometry.length, geometry.clear_height
    an = t * lw  # solid units or grouted cells: the net area is the gross area
    r = t / math.sqrt(12.0)
    s_in = t * lw**2 / 6.0
    s_out = lw * t**2 / 6.0
    notes: list[str] = []
    checks: list[dict[str, Any]] = []
    if m.units == "hollow" and not m.grouted:
        notes.append(
            "hollow units: the section is taken as solid (net = gross area); enter the net "
            "area by grouting the cells or check the face shells by hand"
        )
    low, high = table.fmRange[m.kind]
    if not low <= m.fm <= high:
        checks.append(
            _flag(
                f"f'm within the strength design range ({CLAUSE}; TMS 402 Sec 3.1.8.1.1)",
                f"f'm = {m.fm:.1f} MPa outside {low:g}-{high:g} MPa: the strength formulas are "
                "used beyond their range",
            )
        )
    if m.fm_source == "units":
        notes.append(
            f"f'm = {m.fm:.1f} MPa from the unit strength and type {m.mortar} mortar (TMS 602 "
            "Tables 1-2); prism tests give it better"
        )
    if not forces:
        return MasonryDesign(checks, notes + ["no forces: not checked"], 0.0)

    reinforced = bars is not None
    phi_af = phi("axialFlexureReinforced" if reinforced else "axialFlexureUnreinforced")
    phi_v = phi("shear")
    pn = axial_strength(an, m.fm, h, r)
    ratio = h / r

    def where(f: W.PierForces) -> str:
        return f.where or ""

    # Axial strength.
    rows = [
        _row(
            f"Axial strength φPn ({CLAUSE}; TMS 402 Eqs. 3-{'18, 3-19' if reinforced else '15, 3-16'})",
            f.P / 1e3,
            phi_af * pn / 1e3,
            "kN",
            f.combination,
            f"{where(f)}; h/r = {ratio:.1f}, R = {slenderness_factor(h, r):.3f}",
        )
        for f in forces
    ]
    checks.append(_worst(rows))  # type: ignore[arg-type]

    if not reinforced:
        fr = modulus_of_rupture(m)
        stress_limit = float(table.stressBlock.stress) * m.fm
        tension_in, tension_out, compression, shear = [], [], [], []
        for f in forces:
            mean = f.P / an
            tension_in.append(
                _row(
                    f"In-plane flexural tension Mu/S - Pu/An ≤ φ fr ({CLAUSE}; TMS 402 Sec "
                    "3.2.2, Table 3.1.8.2)",
                    max(abs(f.M3) / s_in - mean, 0.0),
                    phi_af * fr,
                    "MPa",
                    f.combination,
                    f"{where(f)}; fr = {fr:.3f} MPa (type {m.mortar} mortar)",
                )
            )
            tension_out.append(
                _row(
                    f"Out-of-plane flexural tension Mu/S - Pu/An ≤ φ fr ({CLAUSE}; TMS 402 Sec "
                    "3.2.2, Table 3.1.8.2)",
                    max(abs(f.M2) / s_out - mean, 0.0),
                    phi_af * fr,
                    "MPa",
                    f.combination,
                    where(f),
                )
            )
            compression.append(
                _row(
                    f"Compressive stress Pu/An + Mu/S ≤ 0.80 f'm ({CLAUSE}; TMS 402 Sec 3.2.2)",
                    max(mean + abs(f.M3) / s_in + abs(f.M2) / s_out, 0.0),
                    stress_limit,
                    "MPa",
                    f.combination,
                    where(f),
                )
            )
            vn = plain_shear_strength(m, an, f.P)
            shear.append(
                _row(
                    f"In-plane shear φVn ({CLAUSE}; TMS 402 Sec 3.2.4)",
                    abs(f.V2) / 1e3,
                    phi_v * vn / 1e3,
                    "kN",
                    f.combination,
                    f"{where(f)}; {m.bond} bond{', solidly grouted' if m.grouted else ''}",
                )
            )
        for group in (tension_in, tension_out, compression, shear):
            checks.append(_worst(group))  # type: ignore[arg-type]
    else:
        assert bars is not None
        layout = wall_bar_layout(lw, bars)
        emu = m.emu
        pm, steel, shear, oop, axial_limit = [], [], [], [], []
        alpha = float(table.maxSteelStrain[detailing])
        av_s = bars.layers * bar_area(bars.horizontal_dia) / bars.horizontal_spacing
        # Out of plane: per metre is not needed; the whole length as one strip. One layer sits
        # at the centre; two layers at their faces, the tension layer's bars counted.
        count = len(layout)
        one = bar_area(bars.vertical_dia)
        if bars.layers == 2:
            face = t / 2 - bars.cover - bars.horizontal_dia - bars.vertical_dia / 2
            d_out, steel_out = t / 2 + face, count * one
        else:
            d_out, steel_out = t / 2, count * one
        mn_out_cache: dict[float, float] = {}
        slender = table.slenderWall
        for f in forces:
            mn = in_plane_moment(lw, t, layout, m.fm, fy, f.P, emu, es)
            pm.append(
                _row(
                    f"In-plane axial force and bending φMn at Pu ({CLAUSE}; TMS 402 Sec 3.3.2)",
                    abs(f.M3) / 1e6,
                    phi_af * mn / 1e6,
                    "kN·m",
                    f.combination,
                    f"{where(f)}; Pu = {f.P / 1e3:.0f} kN",
                )
            )
            demand, capacity = max_steel_ratio(lw, t, layout, m.fm, fy, f.P, emu, alpha, es)
            steel.append(
                _row(
                    f"Largest steel: T + Pu ≤ C at εmu and {alpha:g} εy ({CLAUSE}; TMS 402 Sec "
                    "3.3.3.5)",
                    demand / 1e3,
                    capacity / 1e3,
                    "kN",
                    f.combination,
                    f"{where(f)}; the factored Pu (on the safe side of D + 0.75L + 0.525QE)",
                )
            )
            vn, vnm, vns, cap = reinforced_shear_strength(an, m.fm, f.M3, f.V2, lw, f.P, av_s, fy)
            shear.append(
                _row(
                    f"In-plane shear φVn ({CLAUSE}; TMS 402 Sec 3.3.4.1.2)",
                    abs(f.V2) / 1e3,
                    phi_v * vn / 1e3,
                    "kN",
                    f.combination,
                    f"{where(f)}; Vnm {vnm / 1e3:.0f} kN + Vns {vns / 1e3:.0f} kN, max "
                    f"{cap / 1e3:.0f} kN",
                )
            )
            key = round(f.P, 0)
            if key not in mn_out_cache:
                mn_out_cache[key] = out_of_plane_moment(lw, d_out, steel_out, m.fm, fy, f.P)
            oop.append(
                _row(
                    f"Out-of-plane bending φMn ({CLAUSE}; TMS 402 Sec 3.3.5.3)",
                    abs(f.M2) / 1e6,
                    phi_af * mn_out_cache[key] / 1e6,
                    "kN·m",
                    f.combination,
                    f"{where(f)}; first-order moment (P-delta of Sec 3.3.5.4 not added)",
                )
            )
            axial_limit.append(
                _row(
                    f"Slender wall Pu/Ag ≤ {float(slender.axialMax):g} f'm ({CLAUSE}; TMS 402 "
                    "Sec 3.3.5.1)",
                    max(f.P, 0.0) / an,
                    float(slender.axialMax) * m.fm,
                    "MPa",
                    f.combination,
                    where(f),
                )
            )
        for group in (pm, steel, shear, oop, axial_limit):
            checks.append(_worst(group))  # type: ignore[arg-type]
        top = max(max(f.P, 0.0) for f in forces) / an
        if top > float(slender.axialSlender) * m.fm:
            checks.append(
                _row(
                    f"h/t ≤ {float(slender.heightThickness):g} where Pu/Ag > "
                    f"{float(slender.axialSlender):g} f'm ({CLAUSE}; TMS 402 Sec 3.3.5.1)",
                    h / t,
                    float(slender.heightThickness),
                    "",
                )
            )
        ordinary = table.ordinaryWalls
        spacing = max(bars.vertical_spacing, bars.horizontal_spacing)
        checks.append(
            _row(
                f"Bar spacing ≤ {float(ordinary.maxSpacing):.0f} mm ({CLAUSE}; TMS 402 Sec "
                "1.17.3.2.3.1)",
                spacing,
                float(ordinary.maxSpacing),
                "mm",
            )
        )
        checks.append(
            _row(
                f"Vertical bar area ≥ {float(ordinary.leastBarArea):.0f} mm² ({CLAUSE}; TMS 402 "
                "Sec 1.17.3.2.3.1)",
                float(ordinary.leastBarArea),
                bars.layers * one,
                "mm²",
            )
        )
        if bars.boundary is not None:
            notes.append("the wall type's end bars are not counted in a masonry wall")
    strength = [c for c in checks if c and not c["flag"]]
    utilisation = max((c["utilisation"] for c in strength), default=0.0)
    return MasonryDesign([c for c in checks if c], notes, utilisation)


def describe(m: Masonry, reinforced: bool) -> str:
    """'Reinforced clay masonry, f'm 8.6 MPa, type S mortar' for the report."""
    kind = "clay" if m.kind == "clay" else "concrete"
    return (
        f"{'Reinforced' if reinforced else 'Plain'} {kind} masonry, f'm {m.fm:.1f} MPa, "
        f"Em {m.em:.0f} MPa, type {m.mortar} mortar"
    )


__all__ = [
    "CLAUSE",
    "CODE",
    "METHOD",
    "Masonry",
    "MasonryDesign",
    "axial_strength",
    "describe",
    "in_plane_moment",
    "masonry_of",
    "masonry_wall_checks",
    "max_steel_ratio",
    "modulus_of_rupture",
    "mortar_type_of_mix",
    "out_of_plane_moment",
    "plain_shear_strength",
    "prism_strength",
    "reinforced_shear_strength",
    "slenderness_factor",
    "wall_bar_layout",
]

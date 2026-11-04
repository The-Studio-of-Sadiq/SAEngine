"""Steel members by limit state design with partial safety factors on the materials and
buckling curves: the pack's ``steelLimitState`` table (alpha 9 C9; IS 800:2007 is the first
pack to choose it, EN 1993-1-1 is the same method family).

When the pack in force has the table, :func:`saengine.design.steel.members.check_member` hands
the member to :func:`check_member` here (the design run, the section proposals and the report
all go through it); a pack without it keeps the LRFD checks of its ``steel`` table, so the
default pack's results do not change.

What is checked, every number from the table and every clause from its ``clauses``:

- **Classification** (:func:`classify`): each plate element's width-thickness ratio against the
  plastic, compact and semi-compact limits in ε = √(250 / fy) (ε² for circular hollow
  sections); the web limits fall with the axial compression; the section takes its worst
  element.
- **Tension**: yielding Ag fy / γm0, rupture ``ruptureShare`` An fu / γm1, single angles α An fu
  / γm1 by the bolts the table assumes (the end connection is not known to the member); block
  shear belongs to the connection (:mod:`saengine.design.steel_connections`).
- **Compression**: fcd = χ fy / γm0 with χ of the buckling curve of the shape and axis
  (imperfection factor α), λ = √(fy / fcc); single angles by the equivalent slenderness λe of
  their legs; slender sections on the effective area (each slender element counted up to its
  semi-compact width: SAEngine's reading of the effective area).
- **Flexure**: Md = βb Zp fy / γm0 ≤ cap Ze fy / γm0 (βb = 1 plastic and compact, Ze / Zp
  semi-compact), the reduced Mdv under high shear; lateral-torsional buckling by the elastic
  critical moment Mcr = c1 √[(π² E Iy / L²)(G It + π² E Iw / L²)] (c1 the equivalent moment
  factor SAEngine takes from the moment diagram, the load at the shear centre), λLT, φLT and
  χLT with αLT of rolled or welded sections.
- **Shear**: Vd = Av fyw / (√3 γm0) with the shear area of the shape, the web's shear buckling
  by the simple post-critical method when d / tw exceeds the limit.
- **Combined forces**: the section by the plastic interaction of plastic and compact I sections
  (else linearly), members in compression by the two member equations with Ky, Kz and KLT on
  the equivalent uniform moment factors Cm, members in tension by the reduced moment Meff.
- **Slenderness** KL/r and L/r against the table's limits.

Units: mm, MPa, N, N·mm (reported in kN, kN·m). The checks' format is the steel member's
(:func:`saengine.design.steel.members._check`).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design.steel.lengths import cb_from_diagram, source_tag
from saengine.design.steel.members import (
    Capacity,
    Steel,
    _check,
    _ratio,
    _Worst,
    moment_coefficient,
)
from saengine.design.steel.properties import ShapeProperties

TABLE = "steelLimitState"

PLASTIC = "plastic"
COMPACT = "compact"
SEMI_COMPACT = "semi-compact"
SLENDER = "slender"
_ORDER = (PLASTIC, COMPACT, SEMI_COMPACT, SLENDER)

#: Names of the combined force rows (the composite column treats them as steel-alone rows).
SECTION_ROW = "Axial force and flexure: section strength"
MEMBER_ROW = "Axial force and flexure: member buckling"


# ─────────────────────────────────────────── data ───────────────────────────────────────────


def rules() -> Any | None:
    """The pack's ``steelLimitState`` table; None when the pack in force has none (or there
    is no pack machinery)."""
    try:
        pack = code_context.current()
        return pack.table(TABLE) if pack.has(TABLE) else None
    except Exception:  # noqa: BLE001 - a bare calculation without packs
        return None


def connection_rules() -> Any | None:
    """The table's ``connections`` group; None without the table or the group."""
    t = rules()
    return getattr(t, "connections", None) if t is not None else None


def seismic_rules() -> Any | None:
    t = rules()
    return getattr(t, "seismic", None) if t is not None else None


def erw(default: bool = True) -> bool:
    """Whether hollow sections take the ERW design wall thickness: ``default`` unless the
    pack's limit state table designs them on the nominal wall."""
    t = rules()
    return default if t is None else bool(default and not t.nominalHollowWall)


def cite(key: str) -> str:
    """The clause of ``key`` after the code's name ("" when the pack gives none)."""
    return code_context.cite(TABLE, key)


def _t(table: Any | None) -> Any:
    found = table if table is not None else rules()
    if found is None:
        raise ValueError("the code pack in force has no limit state steel table")
    return found


def epsilon(fy: float, table: Any | None = None) -> float:
    """ε = √(referenceFy / fy)."""
    return math.sqrt(float(_t(table).classification.referenceFy) / fy)


# ─────────────────────────────────────── classification ───────────────────────────────────────


@dataclass(frozen=True)
class Element:
    """One plate element of a shape, its ratio and its class limits (absolute, ε included)."""

    name: str
    ratio: float
    plastic: float | None
    compact: float | None
    semi_compact: float

    @property
    def cls(self) -> str:
        if self.plastic is not None and self.ratio <= self.plastic:
            return PLASTIC
        if self.compact is not None and self.ratio <= self.compact:
            return COMPACT
        if self.ratio <= self.semi_compact:
            return SEMI_COMPACT
        return SLENDER

    def describe(self) -> str:
        limits = ", ".join(
            f"{n} {v:.1f}"
            for n, v in (
                ("plastic", self.plastic),
                ("compact", self.compact),
                ("semi-compact", self.semi_compact),
            )
            if v is not None
        )
        return f"{self.name} b/t = {self.ratio:.1f} ({limits}): {self.cls}"


def _limits(row: Any, eps: float, name: str, ratio: float) -> Element:
    f = eps**2 if row.squared else eps
    return Element(
        name,
        ratio,
        None if row.plastic is None else row.plastic * f,
        None if row.compact is None else row.compact * f,
        row.semiCompact * f,
    )


def _web(c: Any, eps: float, ratio: float, r: float, name: str = "web") -> Element:
    """The web of an I, H or box section with the axial stress ratio ``r`` (compression +)."""
    floor = c.webAxial * eps
    if r <= 0:
        return _limits(c.web, eps, name, ratio)
    k1, k2, k3 = c.webAxialFactors
    w = c.web

    def lim(base: float | None, k: float) -> float | None:
        return None if base is None else max(base * eps / (1 + k * r), floor)

    return Element(name, ratio, lim(w.plastic, k1), lim(w.compact, k2), lim(w.semiCompact, k3))


def classify(
    shape: ShapeProperties,
    fy: float,
    axial: float = 0.0,
    mode: str = "bending",
    table: Any | None = None,
) -> list[Element]:
    """The elements of ``shape`` and their classes: ``mode`` "bending" (``axial`` the axial
    stress ratio P / (A fy / γm0) with the bending, compression positive), "axial" (uniform
    compression) or "minor" (bending about the minor axis: the flanges only)."""
    t = _t(table)
    c = t.classification
    eps = epsilon(fy, t)
    d = shape.dims
    out = c.outstandWelded if t.welded else c.outstandRolled
    axial_only = mode == "axial"
    match shape.family:
        case "I":
            els = [_limits(out, eps, "flange", d["bf"] / 2 / d["tf"])]
            if mode != "minor":
                ratio = d["h"] / d["tw"]
                els.append(
                    Element("web", ratio, None, None, c.webAxial * eps)
                    if axial_only
                    else _web(c, eps, ratio, axial)
                )
            return els
        case "channel":
            els = [_limits(out, eps, "flange", d["bf"] / d["tf"])]
            if mode != "minor":
                els.append(_limits(c.channelWeb, eps, "web", d["h"] / d["tw"]))
            return els
        case "tee":
            return [
                _limits(out, eps, "flange", d["bf"] / 2 / d["tf"]),
                _limits(c.teeStem, eps, "stem", d["d"] / d["tw"]),
            ]
        case "angle":
            b_t, d_t = d["b"] / d["t"], d["d"] / d["t"]
            if axial_only:
                each, both = c.angleAxial
                return [
                    Element("legs b/t, d/t", max(b_t, d_t), None, None, each * eps),
                    Element("legs (b + d)/t", b_t + d_t, None, None, both * eps),
                ]
            return [_limits(c.angleBending, eps, "leg", max(b_t, d_t))]
        case "rhs":
            if axial_only:
                return [
                    Element("wall (width)", d["b"] / d["t"], None, None, c.internalAxial * eps),
                    Element("wall (depth)", d["h"] / d["t"], None, None, c.internalAxial * eps),
                ]
            flange_b, web_h = (d["b"], d["h"]) if mode != "minor" else (d["h"], d["b"])
            return [
                _limits(c.internalFlange, eps, "flange", flange_b / d["t"]),
                _web(c, eps, web_h / d["t"], axial),
            ]
        case "chs":
            if axial_only:
                return [Element("wall D/t", d["D"] / d["t"], None, None, c.circularAxial * eps**2)]
            return [_limits(c.circularBending, eps, "wall D/t", d["D"] / d["t"])]
        case "bar" | "round":
            return []
    raise ValueError(f"unknown shape family {shape.family}")


def section_class(elements: Sequence[Element]) -> str:
    """The class of the section: its worst element (plastic without plate elements)."""
    return max((e.cls for e in elements), key=_ORDER.index, default=PLASTIC)


def _slender_loss(shape: ShapeProperties, elements: Sequence[Element]) -> float:
    """The area [mm²] of the slender elements beyond their semi-compact widths (the effective
    area of slender compression members, SAEngine's reading)."""
    d = shape.dims
    loss = 0.0
    for el in elements:
        if el.cls != SLENDER or el.ratio <= 0:
            continue
        excess = 1.0 - el.semi_compact / el.ratio
        match shape.family, el.name:
            case ("I", "flange"):
                loss += 2 * d["bf"] * d["tf"] * excess
            case ("channel", "flange"):
                loss += 2 * d["bf"] * d["tf"] * excess
            case ("tee", "flange"):
                loss += d["bf"] * d["tf"] * excess
            case ("I" | "channel", "web"):
                loss += d["h"] * d["tw"] * excess
            case ("tee", "stem"):
                loss += d["d"] * d["tw"] * excess
            case ("rhs", "wall (width)"):
                loss += 2 * d["b"] * d["t"] * excess
            case ("rhs", "wall (depth)"):
                loss += 2 * d["h"] * d["t"] * excess
            case ("angle", _):
                loss = max(loss, (d["b"] + d["d"]) * d["t"] * excess)
            case ("chs", _):
                loss = max(loss, shape.area * excess)
    return min(loss, 0.9 * shape.area)


# ─────────────────────────────────────────── tension ───────────────────────────────────────────


def tension_yielding(shape: ShapeProperties, steel: Steel, table: Any | None = None) -> Capacity:
    t = _t(table)
    g = float(t.partialFactors.gammaM0)
    return Capacity(
        1 / g,
        steel.fy * shape.area,
        "yielding of the gross section",
        cite("tensionYield"),
        f"Tdg = Ag fy / γm0, Ag = {shape.area:.0f} mm², fy = {steel.fy:g} MPa, γm0 = {g:g}",
    )


def angle_alpha(bolts: int, table: Any | None = None) -> float:
    """α of a single angle's net section by the bolts of its end."""
    rows = _t(table).tension.angleAlpha
    for most, alpha in rows:
        if bolts <= most:
            return float(alpha)
    return float(rows[-1][1])


def tension_rupture(
    shape: ShapeProperties,
    steel: Steel,
    net_ratio: float = 1.0,
    given: float | None = None,
    table: Any | None = None,
) -> Capacity:
    """Rupture of the net section; ``given``: the share of An fu (the member's shear lag
    option) in place of the table's."""
    t = _t(table)
    g = float(t.partialFactors.gammaM1)
    an = net_ratio * shape.area
    if given is not None:
        share, why = float(given), f"share {given:g} (given)"
    elif shape.family == "angle":
        bolts = int(t.tension.angleBolts)
        share = angle_alpha(bolts, t)
        why = f"α = {share:g} of a single angle ({bolts} bolts assumed in the end connection)"
    else:
        share = float(t.tension.ruptureShare)
        why = f"{share:g} An fu / γm1 (every element connected)"
    return Capacity(
        1 / g,
        share * steel.fu * an,
        "rupture of the net section",
        cite("tensionAngle" if shape.family == "angle" and given is None else "tensionRupture"),
        f"Tdn: {why}, An = {an:.0f} mm²"
        + (" (= Ag)" if net_ratio == 1.0 else "")
        + f", fu = {steel.fu:g} MPa, γm1 = {g:g}",
    )


# ───────────────────────────────────────── compression ─────────────────────────────────────────


def chi(lam: float, alpha: float, plateau: float) -> float:
    """χ = 1 / (φ + √(φ² - λ²)) ≤ 1, φ = 0.5 [1 + α (λ - plateau) + λ²]."""
    if lam <= plateau:
        return 1.0
    phi = 0.5 * (1 + alpha * (lam - plateau) + lam**2)
    return min(1.0, 1.0 / (phi + math.sqrt(max(phi**2 - lam**2, 0.0))))


def buckling_curves(shape: ShapeProperties, table: Any | None = None) -> tuple[str, str]:
    """(major, minor) buckling curves of the shape."""
    t = _t(table)
    comp = t.compression
    d = shape.dims
    if shape.family == "I":
        tf = d["tf"]
        if t.welded:
            for most, major, minor in comp.weldedI:
                if tf <= most:
                    return major, minor
            return comp.weldedI[-1][1], comp.weldedI[-1][2]
        ratio = d["d"] / d["bf"]
        for above, most, major, minor in comp.rolledI:
            if ratio > above and tf <= most:
                return major, minor
        return comp.rolledI[-1][2], comp.rolledI[-1][3]
    rule = comp.families.get(shape.family)
    if rule is None:
        raise ValueError(f"no buckling curve for a {shape.family}")
    return rule.major, rule.minor


def _fcd(fy: float, e: float, kl: float, r: float, curve: str, t: Any) -> tuple[float, float]:
    """(fcd [MPa], λ) of flexural buckling over KL / r on ``curve``."""
    if kl <= 0:
        return fy / t.partialFactors.gammaM0, 0.0
    lam = math.sqrt(fy / (math.pi**2 * e / (kl / r) ** 2))
    c = chi(lam, float(t.compression.alpha[curve]), float(t.compression.plateau))
    return c * fy / float(t.partialFactors.gammaM0), lam


@dataclass(frozen=True)
class Compression:
    """The compression strength of a member: ``cap`` the governing one, ``pdx`` / ``pdy``
    about the major (x) and minor (y) axes, their λ."""

    cap: Capacity
    pdx: float
    pdy: float
    lam_x: float
    lam_y: float


def compression(
    shape: ShapeProperties,
    steel: Steel,
    klx: float,
    kly: float,
    lx: float,
    ly: float,
    table: Any | None = None,
) -> Compression:
    """The design compressive strength [N] for KL [mm] about x (major) and y (minor); ``lx``,
    ``ly`` the unbraced lengths (single angles: λe on the longer)."""
    t = _t(table)
    fy, e = steel.fy, steel.e
    g0 = float(t.partialFactors.gammaM0)
    elements = classify(shape, fy, mode="axial", table=t)
    cls = section_class(elements)
    area = shape.area - (_slender_loss(shape, elements) if cls == SLENDER else 0.0)
    note_area = (
        f"slender section: effective area {area:.0f} of {shape.area:.0f} mm²"
        if cls == SLENDER
        else f"A = {shape.area:.0f} mm²"
    )
    if shape.family == "angle":
        comp = t.compression
        k1, k2, k3 = comp.angleConstants[comp.angleCondition]
        eps = epsilon(fy, t)
        base = eps * math.sqrt(math.pi**2 * e / float(t.classification.referenceFy))
        length = max(lx, ly)
        lam_vv = (length / shape.rz) / base
        lam_phi = (shape.dims["b"] + shape.dims["d"]) / (2 * shape.dims["t"]) / base
        lam_e = math.sqrt(max(k1 + k2 * lam_vv**2 + k3 * lam_phi**2, 0.0))
        c = chi(lam_e, float(comp.alpha[comp.angleCurve]), float(comp.plateau))
        pd = area * c * fy / g0
        cap = Capacity(
            1.0,
            pd,
            "flexural-torsional buckling of a single angle",
            cite("compressionAngle"),
            f"λe = √(k1 + k2 λvv² + k3 λφ²) = {lam_e:.3f} (k {k1:g}, {k2:g}, {k3:g}: "
            f"{comp.angleCondition}; λvv = {lam_vv:.3f} on L = {length:.0f} mm, rvv = "
            f"{shape.rz:.1f} mm; λφ = {lam_phi:.3f}), curve {comp.angleCurve}, χ = {c:.3f}; "
            f"{note_area}; fy = {fy:g} MPa, γm0 = {g0:g}",
        )
        return Compression(cap, pd, pd, lam_e, lam_e)
    major, minor = buckling_curves(shape, t)
    fx, lam_x = _fcd(fy, e, klx, shape.rx, major, t)
    fy_, lam_y = _fcd(fy, e, kly, shape.ry, minor, t)
    pdx, pdy = area * fx, area * fy_
    axis = "x (major)" if pdx <= pdy else "y (minor)"
    pd = min(pdx, pdy)
    cap = Capacity(
        1.0,
        pd,
        f"flexural buckling about {axis}",
        cite("compression"),
        f"fcd = χ fy / γm0: about x curve {major}, λ = {lam_x:.3f}, fcd = {fx:.1f} MPa; about y "
        f"curve {minor}, λ = {lam_y:.3f}, fcd = {fy_:.1f} MPa (KL = {klx:.0f} / {kly:.0f} mm); "
        f"{note_area}; γm0 = {g0:g}",
    )
    return Compression(cap, pdx, pdy, lam_x, lam_y)


# ─────────────────────────────────────────── flexure ───────────────────────────────────────────


def beta_b(shape: ShapeProperties, cls: str, ze: float, zp: float, elements: Sequence[Element]):
    """βb of the design moment and what it is: 1 plastic and compact, Ze / Zp semi-compact,
    slender: Ze / Zp × the worst slender element's semi-compact share (SAEngine's reading of
    the effective section)."""
    if zp <= 0:
        return 1.0, ""
    if cls in (PLASTIC, COMPACT):
        return 1.0, "βb = 1"
    beta = ze / zp
    if cls == SEMI_COMPACT:
        return beta, f"βb = Ze / Zp = {beta:.3f}"
    worst = min((e.semi_compact / e.ratio for e in elements if e.cls == SLENDER), default=1.0)
    return beta * worst, (
        f"slender: βb = Ze / Zp × {worst:.3f} (the slender element at its semi-compact width) "
        f"= {beta * worst:.3f}"
    )


def critical_moment(
    shape: ShapeProperties, e: float, g: float, length: float, c1: float = 1.0
) -> float:
    """Mcr = c1 √[(π² E Iy / L²)(G It + π² E Iw / L²)] [N·mm] (the load at the shear centre,
    no warping restraint); infinite for L = 0."""
    if length <= 0:
        return math.inf
    a = math.pi**2 * e * shape.iy / length**2
    return c1 * math.sqrt(a * (g * shape.j + math.pi**2 * e * shape.cw / length**2))


def _ltb_susceptible(shape: ShapeProperties) -> bool:
    """Open sections bent about their major axis (closed and solid sections are taken as not
    susceptible: SAEngine practice, they buckle laterally only at very long spans)."""
    return shape.family in ("I", "channel", "tee", "angle") and shape.ix > shape.iy


@dataclass(frozen=True)
class Flexure:
    cap: Capacity
    lam_lt: float
    section: float  # the laterally supported Md [N·mm]
    cls: str


def flexure_major(
    shape: ShapeProperties,
    steel: Steel,
    lb: float,
    c1: float,
    axial: float = 0.0,
    cantilever: bool = False,
    table: Any | None = None,
) -> Flexure:
    """The design bending strength about x (major) over the unbraced length ``lb`` [mm] with
    the equivalent moment factor ``c1``; ``axial`` the axial stress ratio (classification)."""
    t = _t(table)
    fy, e = steel.fy, steel.e
    g0 = float(t.partialFactors.gammaM0)
    elements = classify(shape, fy, axial, "bending", t)
    cls = section_class(elements)
    zp, ze = shape.zx, shape.sx
    beta, why = beta_b(shape, cls, ze, zp, elements)
    cap_share = t.flexure.elasticCapCantilever if cantilever else t.flexure.elasticCap
    md = min(beta * zp * fy / g0, float(cap_share) * ze * fy / g0)
    note = (
        f"{cls}; Md = βb Zp fy / γm0 ≤ {float(cap_share):g} Ze fy / γm0 ({why}, Zp = "
        f"{zp / 1e3:.0f}e3, Ze = {ze / 1e3:.0f}e3 mm³)"
    )
    if not _ltb_susceptible(shape) or lb <= 0:
        return Flexure(Capacity(1.0, md, "yielding", cite("flexure"), note), 0.0, md, cls)
    g = float(t.shearModulus)
    mcr = critical_moment(shape, e, g, lb, c1)
    lam = math.sqrt(beta * zp * fy / mcr) if mcr > 0 else math.inf
    lam = min(lam, math.sqrt(float(cap_share) * ze * fy / mcr)) if mcr > 0 else lam
    if lam <= float(t.flexure.ltbPlateau):
        return Flexure(
            Capacity(
                1.0,
                md,
                "yielding",
                cite("flexure"),
                f"{note}; λLT = {lam:.3f} ≤ {float(t.flexure.ltbPlateau):g}: no lateral-torsional "
                f"buckling (Lb = {lb:.0f} mm)",
            ),
            lam,
            md,
            cls,
        )
    alpha = float(t.flexure.alphaLT["welded" if t.welded else "rolled"])
    c = chi(lam, alpha, float(t.flexure.ltbBase))
    mdl = min(beta * zp * c * fy / g0, md)
    return Flexure(
        Capacity(
            1.0,
            mdl,
            "lateral-torsional buckling",
            cite("lateralTorsional"),
            f"{cls}; Md = βb Zp χLT fy / γm0, Mcr = {mcr / 1e6:.1f} kN·m (c1 = {c1:.2f}, Lb = "
            f"{lb:.0f} mm), λLT = {lam:.3f}, αLT = {alpha:g}, χLT = {c:.3f} ({why})",
        ),
        lam,
        md,
        cls,
    )


def flexure_minor(shape: ShapeProperties, steel: Steel, table: Any | None = None) -> Capacity:
    """The design bending strength about y (minor); no lateral-torsional buckling."""
    t = _t(table)
    fy = steel.fy
    g0 = float(t.partialFactors.gammaM0)
    elements = classify(shape, fy, mode="minor", table=t)
    cls = section_class(elements)
    beta, why = beta_b(shape, cls, shape.sy, shape.zy, elements)
    md = min(beta * shape.zy * fy / g0, float(t.flexure.elasticCap) * shape.sy * fy / g0)
    return Capacity(
        1.0,
        md,
        "yielding",
        cite("flexure"),
        f"{cls}; Md = βb Zp fy / γm0 ≤ {float(t.flexure.elasticCap):g} Ze fy / γm0 ({why})",
    )


def high_shear_moment(
    shape: ShapeProperties, steel: Steel, md: float, cls: str, v: float, vd: float, t: Any
) -> tuple[float, str] | None:
    """Mdv [N·mm] of the section under a high shear V > highShare Vd (I and channel sections
    about x): plastic and compact Md - β (Md - Mfd), β = (2 V / Vd - 1)², semi-compact Ze fy /
    γm0; None below the share."""
    if shape.family not in ("I", "channel") or vd <= 0 or v <= float(t.flexure.highShare) * vd:
        return None
    g0 = float(t.partialFactors.gammaM0)
    if cls in (PLASTIC, COMPACT):
        d = shape.dims
        mfd = d["bf"] * d["tf"] * (d["d"] - d["tf"]) * steel.fy / g0
        beta = (2 * v / vd - 1) ** 2
        mdv = min(md, max(md - beta * (md - mfd), mfd))
        return mdv, (
            f"high shear V = {v / 1e3:.0f} kN > {float(t.flexure.highShare):g} Vd: Mdv = Md - "
            f"β (Md - Mfd), β = {beta:.3f}, Mfd = {mfd / 1e6:.1f} kN·m"
        )
    return min(md, shape.sx * steel.fy / g0), "high shear: Mdv = Ze fy / γm0"


# ──────────────────────────────────────────── shear ────────────────────────────────────────────


def shear_area(shape: ShapeProperties, axis: str, welded: bool = False) -> tuple[float, str]:
    """(Av [mm²], how) for shear along y (``axis`` "y": the depth) or x (the width)."""
    d = shape.dims
    match shape.family:
        case "I" | "channel":
            if axis == "y":
                if welded:
                    return d["h"] * d["tw"], "Av = d tw"
                return d["d"] * d["tw"], "Av = h tw"
            return 2 * d["bf"] * d["tf"], "Av = 2 bf tf"
        case "tee":
            return (
                (d["d"] * d["tw"], "Av = D tw")
                if axis == "y"
                else (
                    d["bf"] * d["tf"],
                    "Av = bf tf",
                )
            )
        case "angle":
            return (
                (d["d"] * d["t"], "Av = d t (the vertical leg)")
                if axis == "y"
                else (
                    d["b"] * d["t"],
                    "Av = b t (the horizontal leg)",
                )
            )
        case "rhs":
            b, h = d["B"], d["H"]
            if axis == "y":
                return shape.area * h / (b + h), "Av = A h / (b + h)"
            return shape.area * b / (b + h), "Av = A b / (b + h)"
        case "chs":
            return 2 * shape.area / math.pi, "Av = 2 A / π"
    return shape.area, "Av = A"


def shear_capacity(
    shape: ShapeProperties,
    steel: Steel,
    axis: str,
    stiffener_spacing: float | None = None,
    table: Any | None = None,
) -> Capacity:
    """Vd [N] along ``axis``; the webs of I and channel sections (along y) with the shear
    buckling of the simple post-critical method when d / tw exceeds the limit."""
    t = _t(table)
    fy, e = steel.fy, steel.e
    g0 = float(t.partialFactors.gammaM0)
    av, how = shear_area(shape, axis, t.welded)
    vp = av * fy / math.sqrt(3)
    note = f"Vd = Av fyw / (√3 γm0), {how} = {av:.0f} mm², γm0 = {g0:g}"
    if axis != "y" or shape.family not in ("I", "channel"):
        return Capacity(1 / g0, vp, "shear yielding", cite("shear"), note)
    s = t.shear
    d, tw = shape.dims["h"], shape.dims["tw"]
    eps = epsilon(fy, t)
    if stiffener_spacing:
        a, b = s.kvStiffened
        ratio = stiffener_spacing / d
        kv = a + b / ratio**2 if ratio < 1 else b + a / ratio**2
        limit = float(s.bucklingLimit) * eps * math.sqrt(kv / float(s.kvUnstiffened))
        stiff = f"stiffeners at c = {stiffener_spacing:.0f} mm, kv = {kv:.2f}"
    else:
        kv = float(s.kvUnstiffened)
        limit = float(s.bucklingLimit) * eps
        stiff = f"no intermediate stiffeners, kv = {kv:g}"
    if d / tw <= limit:
        return Capacity(
            1 / g0,
            vp,
            "shear yielding",
            cite("shear"),
            f"{note}; d/tw = {d / tw:.1f} ≤ {limit:.1f}",
        )
    tau_e = kv * math.pi**2 * e / (12 * (1 - float(s.poisson) ** 2) * (d / tw) ** 2)
    lam = math.sqrt(fy / (math.sqrt(3) * tau_e))
    low, high = s.lambdaLimits
    if lam <= low:
        tau = fy / math.sqrt(3)
    elif lam < high:
        tau = (1 - float(s.lambdaSlope) * (lam - low)) * fy / math.sqrt(3)
    else:
        tau = fy / (math.sqrt(3) * lam**2)
    return Capacity(
        1 / g0,
        av * tau,
        "shear buckling of the web",
        cite("shearBuckling"),
        f"Vcr = Av τb, d/tw = {d / tw:.1f} > {limit:.1f} ({stiff}), τcr,e = {tau_e:.0f} MPa, "
        f"λw = {lam:.3f}, τb = {tau:.0f} MPa; γm0 = {g0:g}",
    )


# ───────────────────────────────────────── interaction ─────────────────────────────────────────


def section_interaction(
    shape: ShapeProperties,
    n: float,
    mz: float,
    mdz: float,
    my: float,
    mdy: float,
    cls: str,
    table: Any | None = None,
) -> tuple[float, str]:
    """The section's combined axial force and bending: plastic and compact I sections by
    (My/Mndy)^α1 + (Mz/Mndz)^α2 ≤ 1, else N/Nd + Mz/Mdz + My/Mdy ≤ 1; (ratio, how). ``n`` =
    N / Nd, z the major (x) axis."""
    t = _t(table)
    it = t.interaction
    linear = n + _ratio(mz, mdz) + _ratio(my, mdy)
    if not (it.plastic and shape.family == "I" and cls in (PLASTIC, COMPACT)) or n >= 1:
        return linear, f"N/Nd + Mz/Mdz + My/Mdy ({cite('sectionLinear')})"
    d = shape.dims
    a = min((shape.area - 2 * d["bf"] * d["tf"]) / shape.area, float(it.flangeShare))
    mndz = min(mdz, mdz * (1 - n) / (1 - float(it.majorReduction) * a))
    mndy = mdy if n <= a else mdy * (1 - ((n - a) / (1 - a)) ** 2)
    a1 = max(float(it.alphaMinor) * n, 1.0)
    a2 = float(it.alphaMajor)
    ratio = _ratio(my, mndy) ** a1 + _ratio(mz, mndz) ** a2
    return min(ratio, linear), (
        f"(My/Mndy)^α1 + (Mz/Mndz)^α2, n = {n:.3f}, Mndz = {mndz / 1e6:.1f}, Mndy = "
        f"{mndy / 1e6:.1f} kN·m, α1 = {a1:.2f}, α2 = {a2:g} ({cite('sectionPlastic')})"
    )


def member_interaction(
    p: float,
    comp: Compression,
    mz: float,
    mdz: float,
    my: float,
    mdy: float,
    cmz: float,
    cmy: float,
    lam_lt: float,
    table: Any | None = None,
) -> tuple[float, str]:
    """Members in compression and bending: the larger of P/Pdy + Ky Cmy My/Mdy + KLT Mz/Mdz
    and P/Pdz + share Ky Cmy My/Mdy + Kz Cmz Mz/Mdz (z the major axis, x of SAEngine)."""
    t = _t(table)
    it = t.interaction
    cap = float(it.kCap)
    ny = _ratio(p, comp.pdy)
    nz = _ratio(p, comp.pdx)
    ky = min(1 + (comp.lam_y - 0.2) * ny, 1 + cap * ny)
    kz = min(1 + (comp.lam_x - 0.2) * nz, 1 + cap * nz)
    cmy, cmz = max(cmy, float(it.cmMin)), max(cmz, float(it.cmMin))
    cm_lt = cmz
    f, off = float(it.ltbFactor), float(it.ltbOffset)
    klt = max(1 - f * lam_lt * ny / (cm_lt - off), 1 - f * ny / (cm_lt - off)) if lam_lt else 1.0
    klt = min(klt, 1.0)
    uy, uz = _ratio(my, mdy), _ratio(mz, mdz)
    a = ny + ky * cmy * uy + klt * uz
    b = nz + float(it.minorShare) * ky * cmy * uy + kz * cmz * uz
    return max(a, b), (
        f"max(P/Pdy + Ky Cmy My/Mdy + KLT Mz/Mdz = {a:.3f}, P/Pdz + {float(it.minorShare):g} Ky "
        f"Cmy My/Mdy + Kz Cmz Mz/Mdz = {b:.3f}); Pdz = {comp.pdx / 1e3:.0f}, Pdy = "
        f"{comp.pdy / 1e3:.0f} kN, Ky = {ky:.3f}, Kz = {kz:.3f}, KLT = {klt:.3f}, Cmy = "
        f"{cmy:.2f}, Cmz = {cmz:.2f} ({cite('memberCompression')})"
    )


# ─────────────────────────────────────────── the member ───────────────────────────────────────────


def check_member(
    shape: ShapeProperties,
    steel: Steel,
    stations: Sequence[Any],
    lengths: Any,
    kind: str = "member",
    options: Any = None,
) -> list[dict[str, Any]]:
    """The limit state checks of one steel member, enveloping its combinations and stations,
    in the steel member's report format (forces in kN and kN·m). ``options``:
    :class:`saengine.design.steel.members.SteelOptions` (its net ratio, shear lag share,
    lengths, stiffener spacing and the stability method's K are used)."""
    from saengine.design.steel.members import SteelOptions

    t = _t(None)
    options = SteelOptions.of(options)
    g0 = float(t.partialFactors.gammaM0)
    nd = shape.area * steel.fy / g0
    ty = tension_yielding(shape, steel, t)
    tr = tension_rupture(shape, steel, options.net_ratio, options.shear_lag, t)
    td = min(ty.design, tr.design)
    stiff = options.stiffener_spacing if shape.family in ("I", "channel") else None
    v_major = shear_capacity(shape, steel, "y", stiff, t)
    v_minor = shear_capacity(shape, steel, "x", None, t)
    m_minor = flexure_minor(shape, steel, t)
    unit_k = getattr(options.stability, "unit_k", None)
    comp_cache: dict[tuple[float, ...], Compression] = {}
    flex_cache: dict[tuple[float, ...], Flexure] = {}

    def comp(klx: float, kly: float, lx: float, ly: float) -> Compression:
        key = (round(klx, 1), round(kly, 1), round(lx, 1), round(ly, 1))
        if key not in comp_cache:
            comp_cache[key] = compression(shape, steel, klx, kly, lx, ly, t)
        return comp_cache[key]

    def flex(lb: float, c1: float, r: float, cantilever: bool) -> Flexure:
        key = (round(lb, 1), round(c1, 3), round(r, 2), cantilever)
        if key not in flex_cache:
            flex_cache[key] = flexure_major(shape, steel, lb, c1, r, cantilever, t)
        return flex_cache[key]

    worst = {k: _Worst() for k in ("ty", "tr", "c", "mx", "my", "vy", "vx", "sec", "mem")}
    worst.update(klr=_Worst(), lr=_Worst())
    compressed = tensioned = False
    psi = float(t.interaction.tensionPsi)
    for st in stations:
        s = st.s
        for k in range(len(s)):
            p = float(st.P[k])
            where = st.where[k]
            kx, lx, _ = lengths.effective("x", float(s[k]), unit_k)
            ky, ly, _ = lengths.effective("y", float(s[k]), unit_k)
            r_axial = max(p, 0.0) / nd if nd > 0 else 0.0
            cap_c = None
            if p < 0:
                tensioned = True
                tension = -p
                worst["ty"].offer(
                    _ratio(tension, ty.design),
                    tension,
                    ty.design,
                    st.combination,
                    f"{ty.note}; {where}",
                    ty.clause,
                )
                worst["tr"].offer(
                    _ratio(tension, tr.design),
                    tension,
                    tr.design,
                    st.combination,
                    f"{tr.note}; {where}",
                    tr.clause,
                )
                r_least = shape.rz if shape.family == "angle" else min(shape.rx, shape.ry)
                lr = max(lx, ly) / r_least
                limit = float(t.slenderness.tension)
                worst["lr"].offer(
                    lr / limit,
                    lr,
                    limit,
                    st.combination,
                    f"L/r with r = {r_least:.1f} mm; {where}",
                    cite("slenderness"),
                )
            if p > 0:
                compressed = True
                cap_c = comp(kx * lx, ky * ly, lx, ly)
                worst["c"].offer(
                    _ratio(p, cap_c.cap.design),
                    p,
                    cap_c.cap.design,
                    st.combination,
                    f"{cap_c.cap.note}; {where}",
                    cap_c.cap.clause,
                )
                r_least = shape.rz if shape.family == "angle" else None
                klr = (
                    max(kx * lx, ky * ly) / r_least
                    if r_least
                    else max(kx * lx / shape.rx, ky * ly / shape.ry)
                )
                limit = float(t.slenderness.compression)
                worst["klr"].offer(
                    klr / limit,
                    klr,
                    limit,
                    st.combination,
                    f"K = {kx:g}{source_tag(lengths, 'kx')} / {ky:g}{source_tag(lengths, 'ky')}, "
                    f"L = {lx:.0f}{source_tag(lengths, 'Lx')} / {ly:.0f}"
                    f"{source_tag(lengths, 'Ly')} mm; {where}",
                    cite("slenderness"),
                )

            # Flexure about x: the unbraced length of the flange in compression.
            mx = float(st.Mx[k])
            top = mx < 0
            ltb = lengths.ltb_top if top else lengths.ltb_bottom
            fl = min(
                (
                    flex(
                        (b - a) * 1e3,
                        1.0 if free else cb_from_diagram(s, st.Mx, a, b),
                        r_axial,
                        free,
                    )
                    for a, b, free in ltb.around_all(float(s[k]))
                ),
                key=lambda f: f.cap.design,
            )
            vy, vx = abs(float(st.Vy[k])), abs(float(st.Vx[k]))
            mdx, mdx_note = fl.cap.design, fl.cap.note
            reduced = high_shear_moment(shape, steel, fl.section, fl.cls, vy, v_major.design, t)
            if reduced is not None and reduced[0] < mdx:
                mdx, mdx_note = reduced[0], f"{mdx_note}; {reduced[1]}"
            mrx, mry = abs(mx), abs(float(st.My[k]))
            demand_x = mrx
            if p < 0 and fl.cap.state == "lateral-torsional buckling":
                # Members in tension and bending: the tension reduces the moment for the
                # lateral-torsional buckling check.
                demand_x = max(mrx - psi * (-p) * shape.sx / shape.area, 0.0)
                mdx_note += f"; Meff = M - {psi:g} T Ze / A = {demand_x / 1e6:.1f} kN·m"
            worst["mx"].offer(
                _ratio(demand_x, mdx),
                demand_x,
                mdx,
                st.combination,
                f"{mdx_note}; {where}",
                fl.cap.clause,
            )
            worst["my"].offer(
                _ratio(mry, m_minor.design),
                mry,
                m_minor.design,
                st.combination,
                f"{m_minor.note}; {where}",
                m_minor.clause,
            )
            worst["vy"].offer(
                _ratio(vy, v_major.design),
                vy,
                v_major.design,
                st.combination,
                f"{v_major.note}; {where}",
                v_major.clause,
            )
            worst["vx"].offer(
                _ratio(vx, v_minor.design),
                vx,
                v_minor.design,
                st.combination,
                f"{v_minor.note}; {where}",
                v_minor.clause,
            )
            # The section: N/Nd with Nd = A fy / γm0 (tension: Td).
            n = _ratio(abs(p), nd if p >= 0 else td)
            sec_md = fl.section if reduced is None else min(fl.section, reduced[0])
            ratio, how = section_interaction(shape, n, mrx, sec_md, mry, m_minor.design, fl.cls, t)
            sense = "compression" if p > 0 else "tension"
            worst["sec"].offer(
                ratio,
                ratio,
                1.0,
                st.combination,
                f"{how}: N = {abs(p) / 1e3:.1f} kN ({sense}), Mz = {mrx / 1e6:.1f} / "
                f"{sec_md / 1e6:.1f}, My = {mry / 1e6:.1f} / {m_minor.design / 1e6:.1f} kN·m; "
                f"{where}",
                cite("section"),
            )
            if cap_c is not None:
                xa, xb, _ = lengths.x.around(float(s[k]))
                ya, yb, _ = lengths.y.around(float(s[k]))
                cmz = moment_coefficient(s, st.Mx, xa, xb)
                cmy = moment_coefficient(s, st.My, ya, yb)
                ratio, how = member_interaction(
                    p, cap_c, mrx, fl.cap.design, mry, m_minor.design, cmz, cmy, fl.lam_lt, t
                )
                worst["mem"].offer(
                    ratio,
                    ratio,
                    1.0,
                    st.combination,
                    f"{how}: P = {p / 1e3:.1f} kN, Mz = {mrx / 1e6:.1f}, My = {mry / 1e6:.1f} "
                    f"kN·m; {where}",
                    cite("memberCompression"),
                )

    rows: list[dict[str, Any]] = []
    if tensioned:
        rows.append(_check("Tension: yielding (gross section)", worst["ty"], "kN", 1e3))
        rows.append(_check("Tension: rupture (net section)", worst["tr"], "kN", 1e3))
    if compressed:
        rows.append(_check("Compression: buckling", worst["c"], "kN", 1e3))
    rows.append(_check("Flexure about x (major)", worst["mx"], "kN·m", 1e6))
    rows.append(_check("Flexure about y (minor)", worst["my"], "kN·m", 1e6))
    rows.append(_check("Shear along y (depth)", worst["vy"], "kN", 1e3))
    rows.append(_check("Shear along x (width)", worst["vx"], "kN", 1e3))
    rows.append(_check(SECTION_ROW, worst["sec"], "", 1.0))
    if compressed:
        rows.append(_check(MEMBER_ROW, worst["mem"], "", 1.0))
    beam = kind == "beam"
    if compressed:
        rows.append(_check("Slenderness KL/r (compression)", worst["klr"], "", 1.0, flag=beam))
    if tensioned:
        rows.append(_check("Slenderness L/r (tension)", worst["lr"], "", 1.0, flag=beam))
    for c in rows:
        if c["utilisation"] < 0:
            c.update(utilisation=0.0, ok=True, demand=0.0)
    return rows


def _has_torsion(torque: Any) -> bool:
    if torque is None:
        return False
    try:
        return bool(np.max(np.abs(np.asarray(torque, dtype=float))) > 1e3)  # > 1 N·m
    except (TypeError, ValueError):
        return False


def member_notes(stations: Sequence[Any]) -> list[str]:
    """The member's notes of what the method does not check."""
    out = []
    if any(_has_torsion(getattr(st, "T", None)) for st in stations):
        out.append("torsion: not covered by the code pack's limit state steel method (not checked)")
    return out


def section_summary(shape: ShapeProperties, steel: Steel) -> tuple[str, list[str]]:
    """The section's class in bending about x and its elements' descriptions (the report)."""
    elements = classify(shape, steel.fy, 0.0, "bending")
    return section_class(elements), [e.describe() for e in elements]


# ─────────────────────────────────────────── report ───────────────────────────────────────────


def method_lines(table: Any | None = None) -> list[str]:
    """The design report's method paragraphs of the limit state steel members."""
    t = _t(table)
    pf = t.partialFactors
    return [
        (
            f"Steel members: limit state design to {cite('code')}, partial safety "
            f"factors γm0 = {float(pf.gammaM0):g} (yielding, buckling), γm1 = "
            f"{float(pf.gammaM1):g} (ultimate stress) ({cite('partialFactors')}); the load "
            "combinations are the project's factored ones."
        ),
        (
            f"Classification ({cite('classification')}): plastic, compact, semi-compact or "
            "slender by the width-thickness ratios in ε = √(250/fy), the web limits reduced by "
            "the axial compression."
        ),
        (
            f"Tension ({cite('tensionYield')}; {cite('tensionRupture')}): Ag fy / γm0 and "
            f"{float(t.tension.ruptureShare):g} An fu / γm1 (An = Ag with welded ends unless "
            f"set; single angles α An fu / γm1 with {int(t.tension.angleBolts)} bolts assumed)."
        ),
        (
            f"Compression ({cite('compression')}): fcd = χ fy / γm0 by the buckling curves "
            f"(α {', '.join(f'{k} {float(v):g}' for k, v in t.compression.alpha.items())}), "
            "the curve of each shape and axis; single angles by λe "
            f"({cite('compressionAngle')}); slender sections on the effective area; K from the "
            "analysis model's brace points (1.0 unless overridden)."
        ),
        (
            f"Flexure ({cite('flexure')}; {cite('lateralTorsional')}): Md = βb Zp fy / γm0 ≤ "
            f"{float(t.flexure.elasticCap):g} Ze fy / γm0, Mdv under high shear; "
            "lateral-torsional buckling by Mcr (c1 from the moment diagram, the load at the "
            f"shear centre), χLT with αLT {float(t.flexure.alphaLT['rolled']):g} rolled / "
            f"{float(t.flexure.alphaLT['welded']):g} welded; a slab braces the top flange."
        ),
        (
            f"Shear ({cite('shear')}; {cite('shearBuckling')}): Vd = Av fyw / (√3 γm0), the "
            "web's shear buckling by the simple post-critical method."
        ),
        (
            f"Combined forces ({cite('section')}; {cite('memberCompression')}): the section by "
            "the plastic interaction of plastic and compact I sections (else linearly), members "
            "in compression by the two member equations with Ky, Kz, KLT and Cm, in tension by "
            f"Meff; slenderness KL/r ≤ {float(t.slenderness.compression):g}, L/r ≤ "
            f"{float(t.slenderness.tension):g} ({cite('slenderness')})."
        ),
        (
            "Deflection of beams (serviceability): as the code pack's serviceability table gives "
            "the limits, under the unfactored load cases. Not checked here: torsion, built-up "
            "lacing, fatigue, fire; connections: see the steel connection checks."
        ),
    ]


# ─────────────────────────────────────────── seismic ───────────────────────────────────────────


def seismic_frames(settings: Any) -> dict[str, list[str]]:
    """The frame kinds of the structural systems in use (``seismic.systems``) whose R is above
    the table's ``rAbove``: {frame kind: [system ids]}; {} when the pack has no rules."""
    sr = seismic_rules()
    if sr is None or settings is None:
        return {}
    from saengine.design.steel.seismic import _systems_in_use

    rows = code_context.table("seismic").systems
    found: dict[str, list[str]] = {}
    for system, override in _systems_in_use(settings):
        frame = sr.systems.get(system)
        if frame is None or frame not in sr.frames:
            continue
        row = rows.get(system)
        r = float(override if override is not None else (row.R if row is not None else 0.0))
        if r <= float(sr.rAbove):
            continue
        found.setdefault(frame, []).append(system)
    return found


def _seismic_row(name: str, demand: float, capacity: float, clause: str, note: str, **kw: Any):
    u = demand / capacity if capacity > 0 else (0.0 if demand <= 0 else 99.0)
    u = round(float(u), 3) if math.isfinite(u) else 99.0
    return {
        "name": "Seismic: " + name,
        "demand": round(float(demand), 3),
        "capacity": round(float(capacity), 3),
        "unit": kw.get("unit", ""),
        "utilisation": u,
        "combination": kw.get("combination"),
        "ok": bool(u <= 1.0),
        "note": note,
        "flag": bool(kw.get("flag", False)),
        "clause": clause,
    }


def _capacity(entry: dict[str, Any], prefix: str) -> float:
    found = next((c for c in entry["checks"] if c["name"].startswith(prefix)), None)
    return float(found["capacity"]) * 1e3 if found else 0.0


def _rescore(entry: dict[str, Any]) -> None:
    strength = [c for c in entry["checks"] if not c["flag"]]
    entry["utilisation"] = max((c["utilisation"] for c in strength), default=0.0)
    entry["ok"] = all(c["ok"] for c in strength)


def seismic_apply(
    building: Any,
    types: dict[str, Any],
    members: Sequence[Any],
    combinations: Sequence[str],
    earthquake: Sequence[int],
    settings: Any,
) -> dict[str, Any]:
    """The pack's steel seismic frame rules (``seismic`` group, method ``prescriptiveFrames``)
    on the steel members' report entries (:class:`saengine.design.steel.seismic.SteelMember`,
    braces included): brace slenderness and compression, the plastic sections, the share of
    the axial force the tension braces of each direction take, the strong column ratio at the
    joints, the connection design moment and rotation (flags) and the columns' axial strength
    under the amplified seismic load. Returns ``{applies, frames, checks, notes}`` (``checks``:
    the project's own: joints and brace lines)."""
    from saengine.design.steel import members as sm
    from saengine.design.steel.properties import shape_properties

    sr = seismic_rules()
    frames = seismic_frames(settings)
    out: dict[str, Any] = {
        "applies": bool(frames),
        "frames": sorted(frames),
        "checks": [],
        "notes": [],
    }
    if sr is None or not frames:
        if sr is not None:
            out["notes"].append(
                "no steel seismic frame of the code pack is in use with R above "
                f"{float(sr.rAbove):g}: its steel seismic rules are not required"
            )
        return out
    braced = [f for f in frames if sr.frames[f].braceSlenderness is not None]
    omega = {c for c, name in enumerate(combinations) if name.startswith("Ω0: ")}
    plain = set(range(len(combinations))) - omega
    info: dict[str, tuple[ShapeProperties, Steel, list[Any]]] = {}
    for m in members:
        if getattr(m.object, "seismicRole", None) == "gravity":
            continue
        try:
            stations = sm.member_stations(m.pieces, list(combinations), m.turned)
            info[m.id] = (shape_properties(m.object.profile), sm.Steel.of(m.material), stations)
        except (ValueError, sm.SteelDesignError) as error:
            out["notes"].append(f"{m.id}: not checked for the seismic rules: {error}")

    for m in members:
        if m.id not in info:
            continue
        shape, steel, stations = info[m.id]
        rows: list[dict[str, Any]] = []
        for frame in frames:
            fr = sr.frames[frame]
            clause = cite(f"seismic_{frame}") or cite("seismic")
            if m.kind in fr.plasticMembers:
                mode = "axial" if m.kind == "brace" else "bending"
                for el in classify(shape, steel.fy, 0.0, mode):
                    limit = el.plastic if el.plastic is not None else el.semi_compact
                    rows.append(
                        _seismic_row(
                            f"{el.name} plastic section ({frame.upper()})",
                            el.ratio,
                            limit,
                            clause,
                            f"b/t = {el.ratio:.1f} ≤ {limit:.1f} (the plastic limit"
                            + ("" if el.plastic is not None else "; none: the semi-compact one")
                            + ")",
                        )
                    )
            if m.kind == "brace" and fr.braceSlenderness is not None:
                klr = next(
                    (
                        c["demand"]
                        for c in m.entry["checks"]
                        if c["name"].startswith("Slenderness KL/r")
                    ),
                    None,
                )
                if klr is not None:
                    rows.append(
                        _seismic_row(
                            f"brace slenderness KL/r ({frame.upper()})",
                            float(klr),
                            float(fr.braceSlenderness),
                            clause,
                            f"KL/r ≤ {float(fr.braceSlenderness):g}",
                        )
                    )
                pd = _capacity(m.entry, "Compression: buckling")
                pu = _largest_compression(stations, plain)
                if fr.braceCompressionShare is not None and pd > 0 and pu > 0:
                    share = float(fr.braceCompressionShare)
                    rows.append(
                        _seismic_row(
                            f"brace compression ≤ {share:g} Pd ({frame.upper()})",
                            pu / 1e3,
                            share * pd / 1e3,
                            clause,
                            f"P = {pu / 1e3:.1f} kN, Pd = {pd / 1e3:.1f} kN",
                            unit="kN",
                        )
                    )
            if m.kind == "beam" and fr.connectionMoment is not None:
                mp = shape.zx * steel.fy
                design = float(fr.connectionMoment) * mp
                rows.append(
                    _seismic_row(
                        f"connection design moment ({frame.upper()})",
                        0.0,
                        design / 1e6,
                        clause,
                        f"the beam-to-column connections are designed for "
                        f"{float(fr.connectionMoment):g} Mp = {design / 1e6:.1f} kN·m"
                        + (
                            f" with a rotation capacity of {float(fr.driftAngle):g} rad"
                            if fr.driftAngle
                            else ""
                        )
                        + " (verify on the connection design)",
                        unit="kN·m",
                        flag=True,
                    )
                )
        if m.kind == "column" and sr.columnAmplified and omega:
            pu = _largest_compression(stations, omega)
            pd = _capacity(m.entry, "Compression: buckling")
            if pu > 0 and pd > 0:
                rows.append(
                    _seismic_row(
                        "column axial strength under the amplified seismic load",
                        pu / 1e3,
                        pd / 1e3,
                        cite("seismicColumns"),
                        f"P = {pu / 1e3:.1f} kN of the Ω0 combinations, Pd = {pd / 1e3:.1f} kN",
                        unit="kN",
                    )
                )
        if rows:
            m.entry["checks"] += rows
            _rescore(m.entry)

    strong = [f for f in frames if sr.frames[f].strongColumn]
    if strong and building is not None:
        out["checks"] += _strong_column_rows(building, types, members, info, sr, strong, out)
    if braced:
        out["checks"] += _brace_line_rows(members, info, combinations, earthquake, sr, braced)
    if any(not sr.frames[f].kBracing for f in braced):
        out["notes"].append(
            f"K bracing is not permitted in the braced frames in use ({cite('seismic')}): "
            "SAEngine does not detect it from the model, check the bracing layout"
        )
    return out


def _largest_compression(stations: Sequence[Any], only: set[int]) -> float:
    """The largest axial compression [N] of the stations of the combinations ``only``."""
    best = 0.0
    for c, st in enumerate(stations):
        if c in only and len(st.P):
            best = max(best, float(np.max(st.P)))
    return best


def _strong_column_rows(building, types, members, info, sr, strong, out) -> list[dict[str, Any]]:
    """ΣMpc ≥ factor ΣMpb at the joints of the moment frames (Mpc = Zp (fy - P/A) with the
    column's largest axial compression)."""
    from saengine.design import ductile_joints as dj

    try:
        joints = dj.frame_joints(building, types)
    except Exception as error:  # noqa: BLE001 - a model the joint search cannot read
        out["notes"].append(f"the beam-column joints could not be found: {error}")
        return []
    by_id = {m.id: m for m in members}
    factor = max(float(sr.frames[f].strongColumn) for f in strong)
    clause = cite(f"seismic_{strong[0]}") or cite("seismic")
    rows = []
    for j in joints:
        cols = [c for c in (j.below, j.above) if c in by_id and c in info]
        beams = [b.id for b in j.beams if b.id in by_id and b.id in info]
        if not cols or not beams:
            continue
        mpc = 0.0
        for c in cols:
            shape, steel, stations = info[c]
            pu = _largest_compression(stations, set(range(len(stations))))
            mpc += shape.zx * max(steel.fy - pu / shape.area, 0.0)
        mpb = sum(info[b][0].zx * info[b][1].fy for b in beams)
        if mpb <= 0:
            continue
        rows.append(
            _seismic_row(
                f"strong column ΣMpc ≥ {factor:g} ΣMpb at joint {j.id}",
                factor * mpb / 1e6,
                mpc / 1e6,
                clause,
                f"ΣMpc = {mpc / 1e6:.1f} kN·m (Zp (fy - P/A) of {', '.join(cols)}), ΣMpb = "
                f"{mpb / 1e6:.1f} kN·m ({', '.join(beams)})",
                unit="kN·m",
            )
        )
    return rows


def _brace_line_rows(members, info, combinations, earthquake, sr, braced) -> list[dict[str, Any]]:
    """The share of the braces' axial force the tension braces take, per plan direction of the
    braces, in the earthquake combinations (a flag: the share of the horizontal force the
    code asks for is taken as the share of the axial forces of the braces of one direction)."""
    from saengine.design.steel.seismic_braced import _ends

    shares = [sr.frames[f].tensionShare for f in braced if sr.frames[f].tensionShare]
    if not shares:
        return []
    low, high = shares[0]
    clause = cite(f"seismic_{braced[0]}") or cite("seismic")
    groups: dict[str, list[list[Any]]] = {}
    for m in members:
        if m.kind != "brace" or m.id not in info:
            continue
        ends = _ends(m.element)
        if ends is None:
            continue
        v = ends[1] - ends[0]
        if abs(v[0]) + abs(v[1]) <= 0:
            continue
        key = "X" if abs(v[0]) >= abs(v[1]) else "Y"
        groups.setdefault(key, []).append(info[m.id][2])
    rows = []
    for key, stations_list in sorted(groups.items()):
        found: tuple[float, float, str] | None = None
        for c in sorted(set(earthquake)):
            if c >= len(combinations):
                continue
            tension = total = 0.0
            for stations in stations_list:
                if c < len(stations) and len(stations[c].P):
                    axial = float(stations[c].P[0])  # compression positive
                    total += abs(axial)
                    tension += max(-axial, 0.0)
            if total <= 0:
                continue
            share = tension / total
            off = max(low - share, share - high, 0.0)
            if found is None or off > found[0]:
                found = (off, share, combinations[c])
        if found is None:
            continue
        _off, share, combination = found
        rows.append(
            _seismic_row(
                f"braces along {key}: tension share {low:g}-{high:g}",
                share,
                high if share > high else low,
                clause,
                f"the braces in tension take {share:.0%} of the axial force of the braces along "
                f"{key} (the share of the horizontal force taken as that; between {low:.0%} and "
                f"{high:.0%})",
                combination=combination,
                flag=True,
            )
        )
    return rows


def seismic_method_lines() -> list[str]:
    sr = seismic_rules()
    if sr is None:
        return []
    kinds = ", ".join(sorted(sr.frames))
    return [
        (
            f"Steel seismic frames ({cite('seismic')}; frames {kinds}): the braces' slenderness "
            "and compression share of Pd, plastic sections of the members the frame names, the "
            "tension braces' share of each brace line, the strong column ratio at the moment "
            "frame joints, the beam-to-column connection design moment (a flag) and the columns' "
            f"axial strength under the amplified seismic load ({cite('seismicColumns')})."
        )
    ]


# ───────────────────────────────────────── connections ─────────────────────────────────────────
# The strengths the shared connection checks (saengine.design.steel_connections) take from the
# limit state method when the pack has its ``connections`` group: the geometry of the checks
# (holes, edges, spacing, weld sizes) stays the steel table's, which the pack sets.


def bolt_strength(grade: str, rules_: Any | None = None) -> Any:
    """The grade's fub and fyb (the group's aliases resolved); ValueError when unknown."""
    b = (rules_ or connection_rules()).bolts
    found = b.grades.get(b.aliases.get(grade, grade))
    if found is None:
        raise ValueError(
            f"bolt grade '{grade}' is not a grade of the code pack ({', '.join(b.grades)})"
        )
    return found


def _gamma(name: str) -> float:
    return float(getattr(_t(None).partialFactors, name))


def bolt_shear(grade: str, d: float, planes: int = 1, factor: float = 1.0) -> float:
    """Vdsb [N] of one bolt: fub / (√3 γmb) × planes × Anb (the threads in every shear plane)
    × ``factor`` (βlj of a long joint)."""
    cr = connection_rules()
    g = bolt_strength(grade, cr)
    anb = float(cr.bolts.netShare) * math.pi * d**2 / 4
    return factor * float(g.fub) / (math.sqrt(3) * _gamma("gammaMb")) * planes * anb


def bolt_tension(grade: str, d: float, frv: float = 0.0) -> tuple[float, str]:
    """Tdb [N] of one bolt, Tnb = share fub An ≤ fyb Asb γmb / γm0, Tdb = Tnb / γmb; with the
    bolt's shear stress ``frv`` [MPa on the shank] by (V/Vd)² + (T/Td)² ≤ 1; and the note."""
    cr = connection_rules()
    g = bolt_strength(grade, cr)
    gmb, gm0 = _gamma("gammaMb"), _gamma("gammaM0")
    asb = math.pi * d**2 / 4
    an = float(cr.bolts.netShare) * asb
    tnb = min(float(cr.bolts.tensionShare) * float(g.fub) * an, float(g.fyb) * asb * gmb / gm0)
    tdb = tnb / gmb
    note = f"Tdb = Tnb / γmb, Tnb = {float(cr.bolts.tensionShare):g} fub An ≤ fyb Asb γmb / γm0"
    if frv <= 0:
        return tdb, f"{note} ({cite('boltTension')})"
    vd = bolt_shear(grade, d, 1)
    share = frv * asb / vd if vd > 0 else math.inf
    if share >= 1:
        return 0.0, f"{note}; the shear alone uses the bolt ({cite('boltCombined')})"
    reduced = tdb * math.sqrt(1 - share**2)
    return reduced, (
        f"{note}, × √(1 - (V/Vd)²) with V/Vd = {share:.2f} ({cite('boltTension')}; "
        f"{cite('boltCombined')})"
    )


def slip_resistance(c: Any, d: float, planes: int = 1, tension: float = 0.0) -> tuple[float, str]:
    """Vdsf [N] of one friction grip bolt: μf ne Kh F0 / γmf, F0 = share fub Anb, γmf of the
    ultimate or the service load (the connection's ``slipCritical``); with the bolt's applied
    tension by (V/Vdf)² + (T/Tdf)² ≤ 1."""
    cr = connection_rules()
    b = cr.bolts
    g = bolt_strength(c.boltGrade, cr)
    if not g.pretensioned:
        return 0.0, f"{c.boltGrade} M{d:g}: not a friction grip grade of the code pack"
    mu = b.slipMu.get(c.surfaceClass)
    kh = b.holeKh.get(c.holeType)
    if mu is None or kh is None:
        return 0.0, (
            f"no slip factor for surface '{c.surfaceClass}' or hole '{c.holeType}' in the code pack"
        )
    gmf = _gamma("gammaMf" if c.slipCritical == "strength" else "gammaMfService")
    anb = float(b.netShare) * math.pi * d**2 / 4
    f0 = float(b.proofShare) * float(g.fub) * anb
    vdsf = float(mu) * planes * float(kh) * f0 / gmf
    note = (
        f"Vdsf = μf ne Kh F0 / γmf: μf {float(mu):g} × {planes} plane(s) × Kh {float(kh):g} × F0 "
        f"{f0 / 1e3:.0f} kN / γmf {gmf:g} ({cite('slip')})"
    )
    if tension > 0:
        tdf = float(b.tensionShare) * float(g.fub) * anb / gmf
        share = min(tension / tdf, 1.0) if tdf > 0 else 1.0
        vdsf *= math.sqrt(1 - share**2)
        note += f"; with T/Tdf = {share:.2f}: × √(1 - (T/Tdf)²)"
    return vdsf, note


def bearing(d: float, t: float, fu: float, lc: float, d0: float, at: str | None) -> float:
    """Vdpb [N] of one bolt hole: factor kb d t fu / γmb, kb the least of e / (3 d0) (``at``
    "end"), p / (3 d0) - 0.25 ("pitch"), 1; ``lc`` the clear distance of SAEngine's checks
    (e = lc + d0 / 2, p = lc + d0); None: the lesser of both readings. fub / fu is not known
    here (taken ≥ 1)."""
    b = connection_rules().bolts
    if math.isinf(lc):
        kb = 1.0
    else:
        end = (max(lc, 0.0) + d0 / 2) / (float(b.bearingEnd) * d0)
        a, off = b.bearingPitch
        pitch = (max(lc, 0.0) + d0) / (float(a) * d0) - float(off)
        kb = {"end": end, "pitch": pitch}.get(at or "", min(end, pitch))
        kb = max(min(kb, 1.0), 0.0)
    return float(b.bearingFactor) * kb * d * t * fu / _gamma("gammaMb")


def block_shear(fy: float, fu: float, agv: float, anv: float, ant: float) -> float:
    """Tdb [N]: the lesser of Avg fy / (√3 γm0) + share Atn fu / γm1 and share Avn fu / (√3
    γm1) + Atg fy / γm0, the gross tension area taken as the net one (Atg ≥ Atn: on the safe
    side, the checks give only the net area)."""
    cr = connection_rules()
    tn, vn = (float(x) for x in cr.blockShear)
    gm0, gm1 = _gamma("gammaM0"), _gamma("gammaM1")
    one = agv * fy / (math.sqrt(3) * gm0) + tn * ant * fu / gm1
    two = vn * anv * fu / (math.sqrt(3) * gm1) + ant * fy / gm0
    return min(one, two)


def fillet_per_mm(w: float, fu: float) -> float:
    """The design strength of a fillet weld per mm [N/mm]: share w × fu / (√3 γmw), ``fu`` the
    weld metal's (the electrode's; the parent metal is not known here)."""
    cr = connection_rules()
    gmw = _gamma("gammaMwField" if cr.welds.field else "gammaMw")
    return float(cr.welds.throatShare) * w * fu / (math.sqrt(3) * gmw)


def long_joint(length: float, d: float | None) -> float:
    """βlj of a joint ``length`` [mm] long along the force: a - b lj / d above c d, at least
    the least, at most 1 (1 without the bolt diameter)."""
    if not d:
        return 1.0
    a, b, c, least = (float(x) for x in connection_rules().bolts.longJoint)
    if length <= c * d:
        return 1.0
    return max(min(a - b * length / d, 1.0), least)


def rewrite_note(note: str) -> str:
    """A connection note with the parent pack's clause texts in this pack's words (the group's
    ``clauseMap``); a parent clause the map does not give is named after the parent code."""
    import re

    cr = connection_rules()
    if cr is None or not note:
        return note
    for old in sorted(cr.clauseMap, key=len, reverse=True):
        note = note.replace(old, cr.clauseMap[old])
    if cr.parentCode:
        note = re.sub(
            r"(?<![\w.])((?:Secs?|Eqs?|Tables?) (?:6\.10\.|10\.)[0-9][0-9a-z.\-()]*)",
            lambda m: f"{cr.parentCode} {m.group(1)}",
            note,
        )
    return note


def connection_method_lines() -> list[str]:
    """The report's paragraph of the connection strengths of the method (none without them)."""
    cr = connection_rules()
    if cr is None:
        return []
    pf = _t(None).partialFactors
    grades = ", ".join(cr.bolts.grades)
    return [
        (
            "Steel connections (when the object type sets one): fin plate, shear end plate, "
            "brace gusset, flange plate, splices, base plates and HSS joints as the code pack's "
            "steel table lays them out, with the strengths of this method: bolts in shear "
            f"({cite('boltShear')}), bearing ({cite('boltBearing')}), tension and combined "
            f"({cite('boltTension')}; {cite('boltCombined')}), γmb = {float(pf.gammaMb):g}, grades "
            f"{grades}; friction grip bolts by their slip resistance ({cite('slip')}, γmf "
            f"{float(pf.gammaMf):g} ultimate / {float(pf.gammaMfService):g} service); block "
            f"shear ({cite('blockShear')}); fillet welds on the throat ({cite('fillet')}, γmw "
            f"{float(pf.gammaMw):g} shop / {float(pf.gammaMwField):g} field); long joints βlj "
            f"({cite('longJoint')}). The other connection rules (HSS joints, the column side under "
            "the flange forces, base plate bearing) are the parent pack's, named so in the notes."
        )
    ]

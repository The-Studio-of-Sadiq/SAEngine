"""Beam deflection by span / effective depth ratios with modification factors and by the
calculation with creep and shrinkage, and the crack width from the strain and the distance to
the bars (alpha 9 C8; the pack's ``concreteMethods.deflection`` method
``spanDepthModification`` and ``cracking`` method ``strainSpacing``, as IS 456:2000 23.2.1,
Annex C and Annex F give them).

Span / depth (23.2.1): l / d at most basic × kt × kc × kf, basic by the support (cantilever,
simply supported, continuous: a span continuous at one end or both), × longSpan / l for spans
longer than ``longSpan`` (not cantilevers). kt of the tension steel by the curve fit 1 / (a +
b fs - c log10(1 / pt)) <= max with fs = stressShare × fy (As,req / As,prov taken 1: on the
safe side), kc = 1 + pc / (a + pc) <= max, kf by bw / bf with bf of the T or L flange.

Calculated (Annex C): the analysis's unfactored D + SD and L deflections, scaled from the
analysis E I to Ec Ieff with Ieff = Ir / (1.2 - (Mr/M)(z/d)(1 - x/d)(bw/b)), Ir <= Ieff <= Igr,
Mr = fcr Igr / yt, fcr = c √fck, z = d - x/3; the creep of the permanent loads (D + SD and the
sustained share of L) θ × their short-term deflection (θ by the age at loading); shrinkage
acs = k3 ψcs l², ψcs = k4 εcs / D. Final at most l / limitTotal; after the partitions (creep,
shrinkage and the live load) at most l / limitAfter and limitAfterMax.

Crack width (Annex F): Wcr = 3 acr εm / (1 + 2 (acr - cmin) / (h - x)), εm = ε1 - b (h - x)
(a' - x) / (div Es As (d - x)), ε1 the steel strain scaled to the tension face, acr the distance
from the tension face's corner to the corner bar's surface (the worst point of a beam's
soffit), under the service moment, against the exposure's limit.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.design.tabulated_shear import _group, _interp, _paren


def rules() -> Any | None:
    return _group("deflection", "spanDepthModification")


def crack_rules() -> Any | None:
    return _group("cracking", "strainSpacing")


def _row(name: str, demand: float, capacity: float, unit: str, note: str, flag: bool = False):
    from saengine.design.check import _check

    return _check(name, demand, capacity, unit, "service", note, flag=flag)


def support_kind(ends: int, cantilever: bool) -> str:
    if cantilever:
        return "cantilever"
    return "continuous" if ends >= 1 else "simple"


def tension_factor(pt: float, fy: float, r: Any | None = None) -> float:
    r = r or rules()
    a, b, c, top = r.tension
    fs = r.stressShare * fy
    if pt <= 0:
        return top
    value = 1 / (a + b * fs - c * math.log10(1 / pt))
    return min(top, max(value, 0.0))


def compression_factor(pc: float, r: Any | None = None) -> float:
    r = r or rules()
    a, top = r.compression
    return min(top, 1 + pc / (a + pc)) if pc > 0 else 1.0


def flange_factor(ratio: float, r: Any | None = None) -> float:
    r = r or rules()
    points = sorted(r.flange)
    return _interp(ratio, [p for p, _ in points], [k for _, k in points])


def flange_width(bw: float, span: float, slab: float, sides: int, r: Any | None = None) -> float:
    r = r or rules()
    if sides <= 0 or slab <= 0:
        return bw
    a, b = r.flangeT if sides >= 2 else r.flangeL
    return span / a + bw + b * slab


def allowed_ratio(
    span: float, kind: str, pt: float, pc: float, fy: float, bw_bf: float = 1.0
) -> tuple[float, str]:
    """The allowed span / effective depth and how it was found."""
    r = rules()
    basic = r.basic[kind]
    long_factor = r.longSpan / span if span > r.longSpan and kind != "cantilever" else 1.0
    kt, kc, kf = tension_factor(pt, fy, r), compression_factor(pc, r), flange_factor(bw_bf, r)
    ratio = basic * long_factor * kt * kc * kf
    how = (
        f"{basic:g} ({kind}) × {long_factor:.2f} × kt {kt:.2f} (pt {pt:.2f} %) × kc {kc:.2f} "
        f"(pc {pc:.2f} %) × kf {kf:.2f}"
    )
    return ratio, how


def effective_inertia(
    ir: float, igr: float, mr: float, m: float, z: float, d: float, x: float, bw_b: float = 1.0
) -> float:
    """Ieff of Annex C, between Ir and Igr."""
    if m <= 0:
        return igr
    denominator = 1.2 - (mr / m) * (z / d) * (1 - x / d) * bw_b
    value = ir / denominator if denominator > 0 else igr
    return min(max(value, ir), igr)


def shrinkage_deflection(span: float, depth: float, pt: float, pc: float, kind: str) -> float:
    """acs = k3 ψcs l² [mm], ψcs = k4 εcs / D."""
    r = rules()
    diff = max(pt - pc, 0.0)
    rows = sorted(r.shrinkageK4)
    # The coefficient of the last row starting at or below pt - pc (the first row's below it).
    coefficient = rows[0][1]
    for start, value in rows:
        if diff >= start:
            coefficient = value
    k4 = min(coefficient * diff / math.sqrt(pt), 1.0) if pt > 0 else 0.0
    k3 = r.shrinkageK3.get(kind, r.shrinkageK3.get("simple", 0.125))
    return k3 * k4 * r.shrinkageStrain / depth * span**2


def creep_coefficient() -> float:
    r = rules()
    points = sorted(r.creep)
    return _interp(r.loadingAge, [a for a, _ in points], [t for _, t in points])


def span_rows(
    section: Any,
    stiffness: Any,
    ec: float,
    span: float,
    ends: int,
    cantilever: bool,
    dead: tuple[float, float],
    live: tuple[float, float],
    ei: float,
    sustained: float,
    where: str,
    flange: tuple[float, int] = (0.0, 0),
) -> list[dict[str, Any]]:
    """The deflection rows of one span (see the module notes). ``dead``, ``live``: (service
    moment [N·mm], the analysis's deflection [mm]); ``stiffness``: the section's
    :class:`saengine.design.deflection.SectionStiffness` with its tension face; ``flange``:
    (slab thickness, sides with a slab)."""
    r = rules()
    kind = support_kind(ends, cantilever)
    hogging = cantilever
    b, h = section.width, section.depth
    d = stiffness.d
    tension = sum(x.area for x in section.bars if (x.y > 0 if hogging else x.y < 0))
    compression = sum(x.area for x in section.bars if (x.y < 0 if hogging else x.y > 0))
    pt, pc = 100 * tension / (b * d), 100 * compression / (b * d)
    bf = flange_width(b, span, flange[0], flange[1], r) if not hogging else b
    ratio, how = allowed_ratio(span, kind, pt, pc, section.fy, b / bf)
    rows = [
        _row(
            f"Deflection: span / effective depth{_paren('spanDepth')}",
            span / d,
            ratio,
            "",
            f"l/d = {span:.0f}/{d:.0f}; allowed {how}; {where}",
        )
    ]
    m_dead, d_dead = dead
    m_live, d_live = live
    if ei <= 0 or d_dead + d_live <= 0:
        return rows
    fcr = r.ruptureCoefficient * math.sqrt(section.fc)
    mr = fcr * stiffness.ig / stiffness.yt
    x = stiffness.c
    z = d - x / 3
    m_total = max(m_dead, 0.0) + max(m_live, 0.0)
    ieff = effective_inertia(stiffness.icr, stiffness.ig, mr, m_total, z, d, x)
    scale = ei / (ec * ieff)
    short_dead, short_live = d_dead * scale, d_live * scale
    theta = creep_coefficient()
    permanent = short_dead + sustained * short_live
    creep = theta * permanent
    # k3 by the support: a span continuous at one end only takes the pack's "continuousOne".
    shrink = shrinkage_deflection(
        span, h, pt, pc, "continuousOne" if kind == "continuous" and ends == 1 else kind
    )
    total = short_dead + short_live + creep + shrink
    after = creep + shrink + short_live
    common = (
        f"Ieff = {ieff:.3g} mm⁴ (Ir {stiffness.icr:.3g}, Igr {stiffness.ig:.3g}, Mr = "
        f"{mr / 1e6:.1f} kN·m, M = {m_total / 1e6:.1f} kN·m); short-term D {short_dead:.1f} + L "
        f"{short_live:.1f} mm, creep θ = {theta:.2f}: {creep:.1f} mm, shrinkage {shrink:.1f} mm"
    )
    rows.append(
        _row(
            f"Deflection: final, calculated{_paren('calculatedDeflection')}",
            total,
            span / r.limitTotal,
            "mm",
            f"at most l/{r.limitTotal:g}; {common}; {where}",
        )
    )
    rows.append(
        _row(
            f"Deflection: after the partitions{_paren('calculatedDeflection')}",
            after,
            min(span / r.limitAfter, r.limitAfterMax),
            "mm",
            f"creep + shrinkage + live, at most l/{r.limitAfter:g} and {r.limitAfterMax:g} mm; "
            f"{where}",
        )
    )
    crack = crack_row(section, stiffness, m_total, hogging, ec, where)
    if crack is not None:
        rows.append(crack)
    return rows


def crack_width(
    section: Any,
    stiffness: Any,
    moment: float,
    hogging: bool,
    ec: float,
    cover: float | None = None,
) -> tuple[float, str]:
    """Wcr [mm] at the tension face's corner bar under the service moment (Annex F)."""
    c = crack_rules()
    b, h = section.width, section.depth
    d, x = stiffness.d, stiffness.c
    tension = [bar for bar in section.bars if (bar.y > 0 if hogging else bar.y < 0)]
    area = sum(bar.area for bar in tension)
    es = section.es
    n = es / ec
    # Steel stress of the cracked section under M, and its strain scaled to the face.
    fs = n * moment * (d - x) / stiffness.icr if stiffness.icr > 0 else 0.0
    eps_s = fs / es
    eps_1 = eps_s * (h - x) / (d - x) if d > x else eps_s
    eps_m = eps_1 - b * (h - x) * (h - x) / (c.stiffeningDivisor * es * area * (d - x))
    eps_m = max(eps_m, 0.0)
    corner = min(tension, key=lambda bar: (abs(bar.x) - b / 2) ** 2 + (abs(bar.y) - h / 2) ** 2)
    cx = b / 2 - abs(corner.x)
    cy = h / 2 - abs(corner.y)
    acr = math.hypot(cx, cy) - corner.dia / 2
    cmin = min(cx, cy) - corner.dia / 2
    w = 3 * acr * eps_m / (1 + 2 * (acr - cmin) / (h - x))
    how = (
        f"Wcr = 3 acr εm / (1 + 2 (acr - cmin)/(h - x)), acr = {acr:.0f} mm, cmin = {cmin:.0f} mm, "
        f"fs = {fs:.0f} MPa, εm = {eps_m:.2e}"
    )
    return w, how


def crack_row(section: Any, stiffness: Any, moment: float, hogging: bool, ec: float, where: str):
    from saengine.design.member_limits import exposure

    c = crack_rules()
    if c is None or moment <= 0:
        return None
    found = exposure()
    key = found[0] if found else next(iter(c.width))
    limit = c.width.get(key, max(c.width.values()))
    try:
        w, how = crack_width(section, stiffness, moment, hogging, ec)
    except (ValueError, ZeroDivisionError):
        return None
    return _row(
        f"Crack width{_paren('cracking')}",
        w,
        limit,
        "mm",
        f"{how}; exposure '{key}'; {where}",
    )

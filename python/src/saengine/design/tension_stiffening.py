"""Beam deflection by the long-term stiffness and crack width with the bars' strain
non-uniformity ψ (alpha 9 C20b; the pack's ``concreteMethods.deflection`` method
``longTermStiffness`` and ``cracking`` method ``effectiveTensionRatio``, as GB 50010-2010
7.1.2-7.1.4 and 7.2.1-7.2.5 give them).

Both under the quasi-permanent moment Mq = Mdead + ψq Mlive (the pack's ``liveShare``) at the
span's governing section (a cantilever: its support), with the tension bars of that face:

- ρte = As / (areaShare b h) at least rhoTeMin; σs = Mq / (leverArm h0 As); ψ = a - b ftk /
  (ρte σs) within (low, high) (``psi``), ftk the characteristic tensile strength.
- Crack width: wmax = αcr ψ σs / Es (coverFactor cs + barFactor deq / ρte), cs the clear cover
  of the outermost tension bar within ``coverRange``, deq = Σ d² / Σ d of the tension bars
  (ribbed), against wlim of the exposure (environment) class in force
  (``concreteMethods.defaultExposure``).
- Deflection: Bs = Es As h0² / (psiFactor ψ + offset + ratioFactor αE ρ / (1 + flangeFactor
  γf')) with ρ = As / (b h0), αE = Es / Ec, γf' = 0 (the compression flange not counted: on the
  safe side), B = Bs / θ, θ = a - (a - b) ρ'/ρ (ρ'/ρ at most 1); the analysis's deflection
  under Mq (D + SD and ψq × the live cases) scaled from its E I to B; at most l0 / divisor
  (the first ``limits`` row holding l0; a cantilever on l0 = cantileverFactor × its length).

Units: mm, MPa, N, N·mm.
"""

from __future__ import annotations

from typing import Any

from saengine.design.tabulated_shear import _group, _paren


def deflection_rules() -> Any | None:
    """The pack's ``concreteMethods.deflection`` of method ``longTermStiffness``, or None."""
    return _group("deflection", "longTermStiffness")


def crack_rules() -> Any | None:
    """The pack's ``concreteMethods.cracking`` of method ``effectiveTensionRatio``, or None."""
    return _group("cracking", "effectiveTensionRatio")


def _row(name: str, demand: float, capacity: float, unit: str, note: str, flag: bool = False):
    from saengine.design.check import _check

    return _check(name, demand, capacity, unit, "service", note, flag=flag)


def _tension(section: Any, hogging: bool) -> list[Any]:
    return [bar for bar in section.bars if (bar.y > 0 if hogging else bar.y < 0)]


def _h0(section: Any, hogging: bool) -> float:
    return float(section.effective_depth(top=hogging))


def steel_terms(
    section: Any, moment: float, hogging: bool, r: Any
) -> tuple[float, float, float, float]:
    """(As [mm²], ρte, σs [MPa], ψ) of the face in tension under ``moment`` [N·mm]."""
    from saengine.design import design_strength

    tension = _tension(section, hogging)
    area = sum(bar.area for bar in tension)
    if area <= 0:
        raise ValueError("no tension bars")
    b, h = float(section.width), float(section.depth)
    rho_te = max(area / (r.areaShare * b * h), float(r.rhoTeMin))
    sigma = abs(moment) / (r.leverArm * _h0(section, hogging) * area)
    a, k, lo, hi = r.psi
    ftk = design_strength.properties(section.fc).fctk005
    psi = a - k * ftk / (rho_te * sigma) if sigma > 0 else lo
    return area, rho_te, sigma, min(max(psi, lo), hi)


def crack_width(section: Any, moment: float, hogging: bool) -> tuple[float, str]:
    """wmax [mm] under ``moment`` (see the module notes) and the note."""
    c = crack_rules()
    _area, rho_te, sigma, psi = steel_terms(section, moment, hogging, c)
    tension = _tension(section, hogging)
    h = float(section.depth)
    outer = max(tension, key=lambda bar: abs(bar.y))
    cs = h / 2 - abs(outer.y) - outer.dia / 2
    lo, hi = c.coverRange
    cs = min(max(cs, lo), hi)
    deq = sum(bar.dia**2 for bar in tension) / sum(bar.dia for bar in tension)
    es = float(section.es)
    w = c.memberFactor * psi * sigma / es * (c.coverFactor * cs + c.barFactor * deq / rho_te)
    how = (
        f"wmax = {c.memberFactor:g} ψ σs/Es ({c.coverFactor:g} cs + {c.barFactor:g} deq/ρte), "
        f"ψ = {psi:.2f}, σs = {sigma:.0f} MPa, ρte = {rho_te:.4f}, cs = {cs:.0f} mm, deq = "
        f"{deq:.1f} mm, Mq = {abs(moment) / 1e6:.1f} kN·m"
    )
    return w, how


def crack_row(section: Any, moment: float, hogging: bool, where: str) -> dict[str, Any] | None:
    """The crack width row (None without the method or a moment)."""
    from saengine.design.member_limits import exposure

    c = crack_rules()
    if c is None or moment <= 0:
        return None
    found = exposure()
    key = found[0] if found else next(iter(c.width))
    limit = c.width.get(key, min(c.width.values()))
    try:
        w, how = crack_width(section, moment, hogging)
    except (ValueError, ZeroDivisionError):
        return None
    return _row(
        f"Crack width{_paren('cracking')}",
        w,
        limit,
        "mm",
        f"{how}; exposure '{key}'; {where}",
    )


def stiffness(section: Any, moment: float, hogging: bool, ec: float) -> tuple[float, str]:
    """B = Bs / θ [N·mm²] under ``moment`` and the note."""
    r = deflection_rules()
    area, _rho_te, _sigma, psi = steel_terms(section, moment, hogging, r)
    b = float(section.width)
    h0 = _h0(section, hogging)
    es = float(section.es)
    rho = area / (b * h0)
    alpha_e = es / ec
    bs = es * area * h0**2 / (r.psiFactor * psi + r.offset + r.ratioFactor * alpha_e * rho)
    compression = sum(bar.area for bar in section.bars if (bar.y < 0 if hogging else bar.y > 0))
    share = min(compression / area, 1.0) if area > 0 else 0.0
    t0, t1 = r.theta
    theta = t0 - (t0 - t1) * share
    note = (
        f"B = Bs/θ, Bs = Es As h0²/({r.psiFactor:g} ψ + {r.offset:g} + {r.ratioFactor:g} αE ρ) "
        f"= {bs:.3g} N·mm², ψ = {psi:.2f}, ρ = {rho:.4f}, αE = {alpha_e:.2f}, θ = {theta:.2f} "
        f"(ρ'/ρ = {share:.2f})"
    )
    return bs / theta, note


def limit_divisor(l0: float) -> float:
    """The divisor of l0 / divisor of the first ``limits`` row holding l0 [mm]."""
    r = deflection_rules()
    for up_to, divisor in r.limits:
        if up_to is None or l0 <= float(up_to) + 1e-9:
            return float(divisor)
    return float(r.limits[-1][1])


def span_rows(
    section: Any,
    ec: float,
    span: float,
    cantilever: bool,
    dead: tuple[float, float],
    live: tuple[float, float],
    ei: float,
    where: str,
) -> list[dict[str, Any]]:
    """The deflection and crack rows of one span (see the module notes). ``dead``, ``live``:
    (service moment [N·mm], the analysis's deflection [mm]); ``ei`` the analysis's E I
    [N·mm²]."""
    r = deflection_rules()
    if r is None:
        return []
    m_dead, d_dead = dead
    m_live, d_live = live
    psi_q = float(r.liveShare)
    mq = max(m_dead, 0.0) + psi_q * max(m_live, 0.0)
    rows: list[dict[str, Any]] = []
    hogging = cantilever
    if ei > 0 and d_dead + d_live > 0 and mq > 0:
        try:
            b_long, note = stiffness(section, mq, hogging, ec)
        except (ValueError, ZeroDivisionError) as error:
            b_long, note = 0.0, f"not computed: {error}"
        if b_long > 0:
            elastic = d_dead + psi_q * d_live
            f = elastic * ei / b_long
            l0 = r.cantileverFactor * span if cantilever else span
            divisor = limit_divisor(l0)
            rows.append(
                _row(
                    f"Deflection: long-term, calculated{_paren('calculatedDeflection')}",
                    f,
                    l0 / divisor,
                    "mm",
                    f"f = the analysis's {elastic:.1f} mm under Mq (D + {psi_q:g} L) × E I / B; "
                    f"{note}; at most l0/{divisor:g}, l0 = {l0:.0f} mm; {where}",
                )
            )
    crack = crack_row(section, mq, hogging, where)
    if crack is not None:
        rows.append(crack)
    return rows


def method_line() -> str:
    """The report's line of the deflection method."""
    r = deflection_rules()
    rows = ", ".join(
        f"l0/{d:g}" + (f" to {u / 1e3:g} m" if u is not None else "") for u, d in r.limits
    )
    c = crack_rules()
    crack = (
        f"; crack widths wmax = {c.memberFactor:g} ψ σs/Es ({c.coverFactor:g} cs + "
        f"{c.barFactor:g} deq/ρte) under Mq{_paren('cracking')}"
        if c is not None
        else ""
    )
    return (
        "deflection under the quasi-permanent moment Mq by the long-term stiffness B = Bs/θ"
        f"{_paren('deflection')} (the analysis's deflection scaled from its E I), at most "
        f"{rows}{crack}"
    )

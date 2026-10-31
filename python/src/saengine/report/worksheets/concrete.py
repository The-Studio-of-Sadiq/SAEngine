"""Concrete worksheets: beams, columns, slabs, punching, bars, lintels and stairs.

Every value comes from the design functions the model's design uses (BNBC 2020 Part 6
Chapter 6 and 8, which adopt ACI 318); the clauses printed are those the functions name.
Inputs in mm, kN, kN·m, kN/m² and MPa; the functions take N and N·mm.
"""

from __future__ import annotations

import math

from saengine.design import bars as B
from saengine.design import deflection as D
from saengine.design import slab as S
from saengine.design import slender as SL
from saengine.design import stairs as ST
from saengine.design.lintels import design_lintel, lintel_loads
from saengine.design.rc import PHI_SHEAR, PHI_SPIRAL, PHI_TIED, STEEL_E, bar_area, beta1
from saengine.design.torsion import TorsionSection, cracking_torsion, threshold_torsion
from saengine.drawings import detailing as DT
from saengine.library.materials import EC_COEFFICIENT
from saengine.report.worksheets.core import (
    CODE,
    Sheet,
    WorksheetInputError,
    choice,
    concrete_inputs,
    flag,
    fmt,
    number,
    worksheet,
)

ACI = "ACI 318-19 (adopted by BNBC 2020 Part 6 Ch 6)"


def _aci(clause: str) -> str:
    return f"ACI 318-19 {clause} (BNBC 2020 Part 6 Ch 6)"


def _bnbc(clause: str) -> str:
    return f"{CODE} {clause}"


def ec_of(fc: float) -> float:
    """Ec [MPa] of normal-weight concrete (BNBC 2020 Part 6 Sec 6.1.7.1)."""
    return EC_COEFFICIENT * math.sqrt(fc)


def factored(sheet: Sheet, dead: float, live: float, unit: str) -> tuple[float, str]:
    """The governing gravity strength combination of ``dead`` and ``live`` (the pack's,
    BNBC 2020 Part 6 Sec 2.7.3.1): writes each and returns (value, name)."""
    best, name = 0.0, ""
    for combo, fd, fl in ST.gravity_combinations():
        value = fd * dead + fl * live
        sheet.step(f"w ({combo})", value, unit, f"{fd:g} D + {fl:g} L", _bnbc("Sec 2.7.3.1"))
        if value > best:
            best, name = value, combo
    return best, name


BAR_GROUP = "Bars"
SECTION_GROUP = "Section"
LOAD_GROUP = "Loads"

# ─────────────────────────────────────── beams ───────────────────────────────────────


@worksheet(
    "beam-flexure",
    "Beam in flexure",
    group="Concrete",
    summary="Tension (and compression) steel of a rectangular beam for Mu, the least steel and "
    "φMn of the bars provided.",
    inputs=[
        number("b", "Width b", 300, "mm", minimum=100, group=SECTION_GROUP),
        number("h", "Depth h", 500, "mm", minimum=150, group=SECTION_GROUP),
        number("dc", "Cover to the bars' centroid", 60, "mm", minimum=20, group=SECTION_GROUP),
        number("mu", "Factored moment Mu", 150, "kN·m", minimum=0, group=LOAD_GROUP),
        *concrete_inputs(),
        number("n", "Bars provided (count)", 4, minimum=0, group=BAR_GROUP),
        number("dia", "Bar diameter", 20, "mm", minimum=6, maximum=40, group=BAR_GROUP),
    ],
    references=(_aci("22.2, 21.2.2, 9.6.1.2-9.6.1.3"),),
)
def _beam_flexure(s: Sheet) -> None:
    b, h, fc, fy = s["b"], s["h"], s["fc"], s["fy"]
    d = s.step("Effective depth d", h - s["dc"], "mm", "h - cover to centroid")
    if d <= 0:
        raise WorksheetInputError("the cover leaves no effective depth")
    mu = s["mu"] * 1e6
    s.step("β1", beta1(fc), "", "stress block depth factor", _aci("Table 22.2.2.4.3"))
    s.step(
        "c at tension-controlled limit",
        B.tension_controlled_depth(d, fy),
        "mm",
        "εt = εty + 0.003",
        _aci("21.2.2"),
    )
    need = B.beam_flexure_need(mu, b, d, s["dc"], fc, fy, h=h)
    s.step(
        "As required",
        need.area,
        "mm²",
        "0.85 f'c b d / fy (1 - √(1 - 2Mu/(φ 0.85 f'c b d²)))",
        _aci("22.2"),
    )
    if need.compression:
        s.step("A's required (compression)", need.compression, "mm²", need.note, _aci("22.2"))
    if need.too_small:
        s.note(need.note)
    as_min = B.beam_min_area(b, d, fc, fy)
    s.step("As,min", as_min, "mm²", "max(0.25 √f'c, 1.4) bw d / fy", _aci("9.6.1.2"))
    to_give = B.with_minimum(need.area, as_min)
    s.step("As to provide", to_give, "mm²", "As,min or 4/3 As,req", _aci("9.6.1.3"))
    provided = s["n"] * bar_area(s["dia"])
    s.step(f"As provided ({s['n']:g} Ø{s['dia']:g})", provided, "mm²", "n π db² / 4")
    if provided > 0:
        cap = S.layer_capacity(provided, d, fc, fy, width=b)
        s.step("a", cap.a, "mm", "As fy / (0.85 f'c b)", _aci("22.2.2"))
        s.step("εt", cap.eps_t, "", "0.003 (d - c) / c", _aci("21.2.2"))
        s.step("φ", cap.phi, "", "from εt", _aci("Table 21.2.2"))
        s.step("φMn", cap.phi_mn / 1e6, "kN·m", "φ As fy (d - a/2)", _aci("22.2"))
        s.check("Mu ≤ φMn", s["mu"], cap.phi_mn / 1e6, "kN·m", _aci("9.5.1.1"))
    s.check("As provided ≥ As to provide", provided, to_give, "mm²", _aci("9.6.1"), at_least=True)


@worksheet(
    "beam-shear",
    "Beam in shear",
    group="Concrete",
    summary="Vc, the stirrups needed, the largest spacing and φVn of the stirrups provided.",
    inputs=[
        number("b", "Width bw", 300, "mm", minimum=100, group=SECTION_GROUP),
        number("h", "Depth h", 500, "mm", minimum=150, group=SECTION_GROUP),
        number("dc", "Cover to the bars' centroid", 60, "mm", minimum=20, group=SECTION_GROUP),
        number(
            "vu",
            "Factored shear Vu (at d from the support)",
            150,
            "kN",
            minimum=0,
            group=LOAD_GROUP,
        ),
        number("fc", "f'c", 25, "MPa", minimum=10, maximum=100, group="Materials"),
        number("fyt", "fyt (stirrups)", 420, "MPa", minimum=200, maximum=700, group="Materials"),
        number("legs", "Stirrup legs", 2, minimum=1, group=BAR_GROUP),
        number("dia", "Stirrup diameter", 10, "mm", minimum=6, maximum=16, group=BAR_GROUP),
        number("spacing", "Stirrup spacing s", 150, "mm", minimum=25, group=BAR_GROUP),
    ],
    references=(_aci("22.5, 9.6.3, 9.7.6.2.2"),),
)
def _beam_shear(s: Sheet) -> None:
    b, fc, fyt = s["b"], s["fc"], s["fyt"]
    d = s.step("Effective depth d", s["h"] - s["dc"], "mm", "h - cover to centroid")
    if d <= 0:
        raise WorksheetInputError("the cover leaves no effective depth")
    need = B.beam_shear_need(s["vu"] * 1e3, b, d, fc, fyt)
    s.step("Vc", need.vc / 1e3, "kN", "0.17 λ √f'c bw d", _aci("Table 22.5.5.1 (a)"))
    s.step("Vs required", need.vs / 1e3, "kN", "Vu/φ - Vc", _aci("22.5.1.1"))
    s.step("Av/s required", need.av_s, "mm²/mm", "max(Vs / (fyt d), Av,min/s)", _aci("22.5.8.5.3"))
    s.step("Av,min/s", need.av_s_min, "mm²/mm", "max(0.062 √f'c, 0.35) bw / fyt", _aci("9.6.3.4"))
    s.step("s,max", need.s_max, "mm", "d/2 (d/4 where Vs > 0.33 √f'c bw d)", _aci("9.7.6.2.2"))
    av = s["legs"] * bar_area(s["dia"])
    av_s = s.step("Av/s provided", av / s["spacing"], "mm²/mm", "legs π dt² / 4 / s")
    vs_max = 0.66 * math.sqrt(fc) * b * d
    vs = min(av_s * min(fyt, 420.0) * d, vs_max)
    s.step("Vs provided", vs / 1e3, "kN", "Av fyt d / s ≤ 0.66 √f'c bw d", _aci("22.5.8.5.3"))
    phi_vn = PHI_SHEAR * (need.vc + vs)
    s.step("φVn", phi_vn / 1e3, "kN", "φ (Vc + Vs), φ = 0.75", _aci("21.2.1"))
    s.check("Vu ≤ φVn", s["vu"], phi_vn / 1e3, "kN", _aci("9.5.1.1"))
    s.check("Vs required ≤ 0.66 √f'c bw d", need.vs / 1e3, vs_max / 1e3, "kN", _aci("22.5.1.2"))
    s.check(
        "Av/s ≥ Av,min/s", av_s, need.av_s_min, "mm²/mm", _aci("9.6.3.4"), at_least=True, digits=3
    )
    s.check("s ≤ s,max", s["spacing"], need.s_max, "mm", _aci("9.7.6.2.2"))


@worksheet(
    "beam-deflection",
    "Beam deflection",
    group="Concrete",
    summary="The least depth without a calculation, Ie, the immediate and long-term deflection of "
    "a rectangular beam against the limits.",
    inputs=[
        number("b", "Width b", 300, "mm", minimum=100, group=SECTION_GROUP),
        number("h", "Depth h", 500, "mm", minimum=150, group=SECTION_GROUP),
        number("dc", "Cover to the bars' centroid", 60, "mm", minimum=20, group=SECTION_GROUP),
        number("as_", "Tension steel As", 1256, "mm²", minimum=1, group=BAR_GROUP),
        number("asc", "Compression steel A's", 0, "mm²", minimum=0, group=BAR_GROUP),
        number("span", "Span l", 6000, "mm", minimum=500, group="Span"),
        choice(
            "ends",
            "Continuity",
            "0",
            [("0", "Simply supported"), ("1", "One end continuous"), ("2", "Both ends continuous")],
            group="Span",
        ),
        number("md", "Service moment, dead (D + SD)", 60, "kN·m", minimum=0, group=LOAD_GROUP),
        number("ml", "Service moment, live", 40, "kN·m", minimum=0, group=LOAD_GROUP),
        number("psi", "Sustained share of live", 0.25, minimum=0, maximum=1, group=LOAD_GROUP),
        number(
            "months", "Duration of the sustained load", 60, "months", minimum=1, group=LOAD_GROUP
        ),
        flag("sensitive", "Carries elements likely to be damaged", False, group=LOAD_GROUP),
        *concrete_inputs(),
    ],
    references=(_bnbc("Sec 6.2.5, Tables 6.6.1-6.6.2, Eqs. 6.6.1-6.6.4"),),
)
def _beam_deflection(s: Sheet) -> None:
    b, h, fc, fy, span = s["b"], s["h"], s["fc"], s["fy"], s["span"]
    ends = int(s["ends"])
    limits = D.DeflectionLimits.from_pack()
    hmin = D.beam_minimum_depth(span, ends, fy, False, limits)
    s.step(
        "h,min without a calculation",
        hmin,
        "mm",
        "l / divisor × (0.4 + fy/700)",
        _bnbc("Table 6.6.1"),
    )
    d = h - s["dc"]
    ec = s.step("Ec", ec_of(fc), "MPa", "4700 √f'c", _bnbc("Sec 6.1.7.1"))
    n = STEEL_E / ec
    ig = b * h**3 / 12
    s.step("Ig", ig / 1e6, "×10⁶ mm⁴", "b h³ / 12")
    mcr = D.cracking_moment(fc, ig, h / 2)
    s.step("Mcr", mcr / 1e6, "kN·m", "0.62 λ √f'c Ig / yt", _bnbc("Eqs. 6.6.2-6.6.3"))
    bars = [(d, s["as_"])] + ([(s["dc"], s["asc"])] if s["asc"] > 0 else [])
    _, icr = D.cracked_section([D.Strip(b, 0.0, h)], bars, n)
    s.step("Icr", icr / 1e6, "×10⁶ mm⁴", "cracked transformed section, n = Es/Ec")

    # Immediate deflection of a uniformly loaded span, 5 M l² / (48 Ec Ie) with M the midspan
    # moment (the end moments' effect left out: conservative for continuous spans).
    def delta(moment: float) -> float:
        ie = D.effective_inertia(moment, mcr, ig, icr)
        return 5 * moment * span**2 / (48 * ec * ie) if moment > 0 else 0.0

    md, ml = s["md"] * 1e6, s["ml"] * 1e6
    dd = s.step("Δ dead", delta(md), "mm", "5 M l² / (48 Ec Ie), Ie at D", _bnbc("Eq. 6.6.1"))
    dt = s.step("Δ dead + live", delta(md + ml), "mm", "Ie at D + L", _bnbc("Eq. 6.6.1"))
    ds = s.step("Δ sustained", delta(md + s["psi"] * ml), "mm", "Ie at D + ψL", _bnbc("Eq. 6.6.1"))
    live = dt - dd
    s.step("Δ live", live, "mm", "Δ(D+L) - Δ(D)")
    xi = D.xi_factor(s["months"], limits.xi)
    s.step("ξ", xi, "", "time-dependent factor", _bnbc("Sec 6.2.5.2.5"))
    rho_p = s["asc"] / (b * d)
    lam = D.long_term_multiplier(rho_p, xi)
    s.step("λΔ", lam, "", "ξ / (1 + 50 ρ')", _bnbc("Eq. 6.6.4"))
    after = lam * ds + live
    s.step("Δ after attachment", after, "mm", "λΔ Δsustained + Δlive", _bnbc("Table 6.6.2"))
    s.check(
        "Δ live ≤ l / " + fmt(limits.live_floor),
        live,
        span / limits.live_floor,
        "mm",
        _bnbc("Table 6.6.2"),
    )
    divisor = limits.attached_sensitive if s["sensitive"] else limits.attached_insensitive
    s.check(
        "Δ after attachment ≤ l / " + fmt(divisor),
        after,
        span / divisor,
        "mm",
        _bnbc("Table 6.6.2"),
    )
    s.note(
        "Immediate deflection of a uniformly loaded span with the midspan moment; the end "
        "moments of a continuous span reduce it."
    )


@worksheet(
    "beam-torsion",
    "Beam torsion threshold",
    group="Concrete",
    summary="Whether torsion may be neglected (φTth), and the compatibility torsion cap φTcr.",
    inputs=[
        number("b", "Width b", 300, "mm", minimum=100, group=SECTION_GROUP),
        number("h", "Depth h", 500, "mm", minimum=150, group=SECTION_GROUP),
        number("cover", "Clear cover to stirrups", 25, "mm", minimum=10, group=SECTION_GROUP),
        number("stirrup", "Stirrup diameter", 10, "mm", minimum=6, group=SECTION_GROUP),
        number("slab", "Slab cast with it (0: none)", 125, "mm", minimum=0, group=SECTION_GROUP),
        choice(
            "sides",
            "Slab on",
            "1",
            [("1", "One side (edge beam)"), ("2", "Both sides")],
            group=SECTION_GROUP,
        ),
        number("tu", "Factored torsion Tu", 4, "kN·m", minimum=0, group=LOAD_GROUP),
        number("nu", "Axial compression Nu", 0, "kN", minimum=0, group=LOAD_GROUP),
        number("fc", "f'c", 25, "MPa", minimum=10, maximum=100, group="Materials"),
    ],
    references=(_bnbc("Sec 6.4.4.1, 6.4.4.2.2"),),
)
def _beam_torsion(s: Sheet) -> None:
    d = s["h"] - s["cover"] - s["stirrup"] - 10
    sec = TorsionSection(
        s["b"],
        s["h"],
        s["cover"],
        s["stirrup"],
        d,
        s["slab"],
        int(s["sides"]) if s["slab"] > 0 else 0,
    )
    acp, pcp, _ = sec.outline()
    s.step("Acp", acp, "mm²", "area within the outside perimeter (with the flange overhang)")
    s.step("pcp", pcp, "mm", "outside perimeter")
    nu = s["nu"] * 1e3
    tth = threshold_torsion(sec, s["fc"], nu)
    tcr = cracking_torsion(sec, s["fc"], nu)
    s.step(
        "φTth",
        tth / 1e6,
        "kN·m",
        "φ 0.083 λ √f'c Acp²/pcp √(1 + Nu/(0.33 Ag λ √f'c))",
        _bnbc("Sec 6.4.4.1"),
    )
    s.step("φTcr", tcr / 1e6, "kN·m", "φ 0.33 λ √f'c Acp²/pcp √(...)", _bnbc("Sec 6.4.4.2.2"))
    if s.check(
        "Tu ≤ φTth (torsion may be neglected)", s["tu"], tth / 1e6, "kN·m", _bnbc("Sec 6.4.4.1")
    ):
        return
    s.note(
        "Tu exceeds φTth: design the beam for torsion (closed stirrups and longitudinal "
        f"bars). For compatibility torsion Tu may be reduced to φTcr = {tcr / 1e6:.1f} kN·m "
        "(Sec 6.4.4.2.2)."
    )


# ─────────────────────────────────────── columns ───────────────────────────────────────


@worksheet(
    "column-axial",
    "Column axial capacity",
    group="Concrete",
    summary="P0 and the largest design axial compression φPn,max of a short tied or spiral "
    "column, and its steel ratio.",
    inputs=[
        number("b", "Width b", 400, "mm", minimum=150, group=SECTION_GROUP),
        number("h", "Depth h", 400, "mm", minimum=150, group=SECTION_GROUP),
        choice(
            "ties",
            "Transverse bars",
            "tied",
            [("tied", "Ties"), ("spiral", "Spiral")],
            group=SECTION_GROUP,
        ),
        number("n", "Longitudinal bars (count)", 8, minimum=4, group=BAR_GROUP),
        number("dia", "Bar diameter", 20, "mm", minimum=10, maximum=40, group=BAR_GROUP),
        number("pu", "Factored axial load Pu", 2000, "kN", minimum=0, group=LOAD_GROUP),
        *concrete_inputs(),
    ],
    references=(_aci("22.4.2, Table 21.2.2, 10.6.1.1"),),
)
def _column_axial(s: Sheet) -> None:
    fc, fy = s["fc"], s["fy"]
    ag = s.step("Ag", s["b"] * s["h"], "mm²", "b h")
    ast = s.step("Ast", s["n"] * bar_area(s["dia"]), "mm²", "n π db² / 4")
    rho = s.step("ρg", ast / ag, "", "Ast / Ag", digits=4)
    p0 = 0.85 * fc * (ag - ast) + fy * ast
    s.step("P0", p0 / 1e3, "kN", "0.85 f'c (Ag - Ast) + fy Ast", _aci("22.4.2.2"))
    spiral = s["ties"] == "spiral"
    phi, k = (PHI_SPIRAL, 0.85) if spiral else (PHI_TIED, 0.80)
    s.step("φ", phi, "", "compression-controlled", _aci("Table 21.2.2"))
    cap = s.step("φPn,max", k * phi * p0 / 1e3, "kN", f"{k:g} φ P0", _aci("Table 22.4.2.1"))
    s.check("Pu ≤ φPn,max", s["pu"], cap, "kN", _aci("22.4.2.1"))
    lo, hi = B.column_rho()
    s.check("ρg ≥ minimum", rho, lo, "", _aci("10.6.1.1"), at_least=True, digits=4)
    s.check("ρg ≤ maximum", rho, hi, "", _aci("10.6.1.1") + " (the pack's limit)", digits=4)
    s.note(
        "Axial load alone: a column with moment is checked on its interaction diagram "
        "(the Section Designer, or the design of the model)."
    )


@worksheet(
    "column-slenderness",
    "Column slenderness (non-sway)",
    group="Concrete",
    summary="k from the alignment chart, k lu/r against the limit, and the magnified moment Mc "
    "of a braced column.",
    inputs=[
        number("b", "Width (across bending)", 400, "mm", minimum=150, group=SECTION_GROUP),
        number(
            "h", "Depth h (in the plane of bending)", 400, "mm", minimum=150, group=SECTION_GROUP
        ),
        number("lu", "Unsupported length lu", 3500, "mm", minimum=500, group=SECTION_GROUP),
        number("psi_a", "ψA (top)", 1.0, minimum=0, group="Restraint"),
        number("psi_b", "ψB (bottom)", 1.0, minimum=0, group="Restraint"),
        number("pu", "Factored axial load Pu", 1500, "kN", minimum=0, group=LOAD_GROUP),
        number(
            "m1",
            "Smaller end moment M1",
            30,
            "kN·m",
            group=LOAD_GROUP,
            help="Positive in single curvature, negative in double curvature.",
        ),
        number("m2", "Larger end moment M2", 60, "kN·m", minimum=0, group=LOAD_GROUP),
        number("beta", "βdns (sustained axial share)", 0.6, minimum=0, maximum=1, group=LOAD_GROUP),
        flag("transverse", "Transverse load between the ends", False, group=LOAD_GROUP),
        number("fc", "f'c", 25, "MPa", minimum=10, maximum=100, group="Materials"),
    ],
    references=(_bnbc("Sec 6.3.10, Figure 6.6.5, Eqs. 6.6.14, 6.6.19-6.6.24"),),
)
def _column_slenderness(s: Sheet) -> None:
    h, lu = s["h"], s["lu"]
    k = s.step(
        "k",
        SL.k_nonsway(s["psi_a"], s["psi_b"]),
        "",
        "nonsway alignment chart",
        _bnbc("Figure 6.6.5 (a)"),
    )
    r = s.step("r", 0.3 * h, "mm", "0.3 h (rectangle)", _bnbc("Sec 6.3.10.2"))
    ratio = s.step("k lu / r", k * lu / r, "", "")
    m2 = max(abs(s["m2"]), abs(s["m1"]))
    m1m2 = s["m1"] / m2 if m2 else 1.0
    limit = s.step("Limit", SL.nonsway_limit(m1m2), "", "34 - 12 M1/M2 ≤ 40", _bnbc("Eq. 6.6.14"))
    if ratio <= limit:
        s.note("k lu / r is within the limit: slenderness may be neglected.")
    ec = ec_of(s["fc"])
    ig = s["b"] * h**3 / 12
    ei = SL.effective_ei(ec, ig, s["beta"])
    s.step("EI", ei / 1e12, "×10¹² N·mm²", "0.4 Ec Ig / (1 + βdns)", _bnbc("Eq. 6.6.22"))
    pc = SL.critical_load(ei, k, lu)
    s.step("Pc", pc / 1e3, "kN", "π² EI / (k lu)²", _bnbc("Eq. 6.6.20"))
    cm = s.step(
        "Cm", SL.cm_factor(m1m2, s["transverse"]), "", "0.6 + 0.4 M1/M2", _bnbc("Eq. 6.6.23")
    )
    pu = s["pu"] * 1e3
    s.check("Pu < 0.75 Pc", s["pu"], 0.75 * pc / 1e3, "kN", _bnbc("Eq. 6.6.19"))
    dns = SL.delta_ns(cm, pu, pc)
    s.step("δns", dns, "", "Cm / (1 - Pu / 0.75 Pc) ≥ 1", _bnbc("Eq. 6.6.19"))
    mmin = SL.minimum_moment(pu, h) / 1e6
    s.step("M2,min", mmin, "kN·m", "Pu (15 + 0.03 h)", _bnbc("Eq. 6.6.24"))
    if math.isfinite(dns):
        s.step("Mc", dns * max(m2, mmin), "kN·m", "δns max(M2, M2,min)", _bnbc("Sec 6.3.10.6"))
        s.note("Design the section for Pu with Mc.")


# ─────────────────────────────────────── slabs ───────────────────────────────────────


def _slab_mesh_checks(s: Sheet, mu_knm: float, d: float, h: float, label: str) -> None:
    """As required for ``mu_knm`` per metre, the minimum, and the mesh entered."""
    fc, fy = s["fc"], s["fy"]
    need = B.slab_flexure_need(mu_knm * 1e6, d, fc, fy)
    s.step(
        f"As required ({label})",
        need.area,
        "mm²/m",
        "1 m strip, stress block",
        _aci("22.2, 7.3.3.1"),
    )
    if need.too_small:
        s.note(f"{label}: {need.note}")
    as_min = S.min_steel_ratio(fy) * 1000 * h
    s.step("As,min", as_min, "mm²/m", "ratio × b h", _aci("7.6.1.1, Table 24.4.3.2"))
    provided = bar_area(s["dia"]) * 1000 / s["spacing"]
    s.check(
        f"Ø{s['dia']:g} @ {s['spacing']:g} ≥ As ({label})",
        provided,
        max(need.area, as_min),
        "mm²/m",
        _aci("7.6.1.1"),
        at_least=True,
    )


SLAB_INPUTS = [
    number("h", "Thickness h", 150, "mm", minimum=75, group=SECTION_GROUP),
    number("dc", "Cover to the bars' centroid", 25, "mm", minimum=15, group=SECTION_GROUP),
    number(
        "dead",
        "Superimposed dead load",
        1.5,
        "kN/m²",
        minimum=0,
        group=LOAD_GROUP,
        help="Finishes and partitions; the self weight is added.",
    ),
    number("live", "Live load", 2.0, "kN/m²", minimum=0, group=LOAD_GROUP),
    number("gamma", "Concrete unit weight", 24, "kN/m³", minimum=15, group=LOAD_GROUP),
    *concrete_inputs(),
    number("dia", "Bar diameter", 10, "mm", minimum=6, maximum=25, group=BAR_GROUP),
    number("spacing", "Bar spacing", 150, "mm", minimum=50, group=BAR_GROUP),
]


@worksheet(
    "slab-one-way",
    "One-way slab",
    group="Concrete",
    summary="Least thickness, the moments by BNBC's coefficients, steel and one-way shear of a "
    "1 m strip.",
    inputs=[
        number("span", "Clear span ln", 3500, "mm", minimum=500, group="Span"),
        choice(
            "position",
            "Span",
            "end",
            [
                ("simple", "Single span, simply supported"),
                ("end", "End span (discontinuous end integral with support)"),
                ("interior", "Interior span"),
            ],
            group="Span",
        ),
        *SLAB_INPUTS,
    ],
    references=(_bnbc("Sec 6.1.4.3, Table 6.6.1"),),
)
def _slab_one_way(s: Sheet) -> None:
    span, h = s["span"], s["h"]
    ends = {"simple": 0, "end": 1, "interior": 2}[s["position"]]
    t = S.one_way_thickness(span, ends, s["fy"])
    s.step("h,min", t.required, "mm", t.note, _bnbc("Table 6.6.1"))
    s.check("h ≥ h,min", h, t.required, "mm", _bnbc("Table 6.6.1"), at_least=True)
    d = s.step("d", h - s["dc"], "mm", "h - cover to centroid")
    sw = s.step("Self weight", s["gamma"] * h / 1000, "kN/m²", "γc h")
    wu, combo = factored(s, sw + s["dead"], s["live"], "kN/m²")
    ln = span / 1000
    coeff = S.coefficient_table()["oneWay"]
    if s["position"] == "simple":
        pos, neg = 8.0, None
        s.step("M+", wu * ln**2 / pos, "kN·m/m", "wu ln² / 8 (statics)")
    else:
        pos = coeff["positive"]["endIntegral" if ends == 1 else "interior"]
        neg = coeff["negative"]["firstInteriorMoreSpans" if ends == 1 else "otherInterior"]
        s.step("M+", wu * ln**2 / pos, "kN·m/m", f"wu ln² / {pos:g}", _bnbc("Sec 6.1.4.3"))
        s.step(
            "M- (interior support)",
            wu * ln**2 / neg,
            "kN·m/m",
            f"wu ln² / {neg:g}",
            _bnbc("Sec 6.1.4.3"),
        )
        s.note(
            "BNBC's coefficients hold for two or more spans differing by no more than 20 %, "
            "uniform load, and L ≤ 3 D (Sec 6.1.4.3)."
        )
    _slab_mesh_checks(s, wu * ln**2 / pos, d, h, "midspan")
    if neg:
        _slab_mesh_checks(s, wu * ln**2 / neg, d, h, "support")
    share = coeff.get("shearFirstInterior", 1.15) if ends == 1 else 1.0
    vu = s.step("Vu", share * wu * ln / 2, "kN/m", f"{share:g} wu ln / 2", _bnbc("Sec 6.1.4.3"))
    rho = max(bar_area(s["dia"]) * 1000 / s["spacing"] / (1000 * d), 1e-6)
    phi_vc, _ = S.one_way_shear(rho, d, s["fc"])
    s.check("Vu ≤ φVc", vu, phi_vc / 1e3, "kN/m", _aci("Table 22.5.5.1 (c)"))
    s.note(f"Governing combination: {combo}.")


@worksheet(
    "slab-two-way",
    "Two-way slab panel (coefficients)",
    group="Concrete",
    summary="Moments of a two-way panel by BNBC's coefficient tables, steel each way and the "
    "least thickness.",
    inputs=[
        number("la", "Clear short span la", 4000, "mm", minimum=500, group="Panel"),
        number("lb", "Clear long span lb", 5000, "mm", minimum=500, group="Panel"),
        choice(
            "long_cont",
            "Continuous long edges",
            "2",
            [("0", "0"), ("1", "1"), ("2", "2")],
            group="Panel",
            help="Edges of length lb (at the ends of the short span).",
        ),
        choice(
            "short_cont",
            "Continuous short edges",
            "2",
            [("0", "0"), ("1", "1"), ("2", "2")],
            group="Panel",
        ),
        number(
            "alpha_fm",
            "αfm (beam stiffness ratio)",
            2.0,
            minimum=0,
            group="Panel",
            help="0 for a flat plate; above 2 for stiff beams on every side.",
        ),
        *SLAB_INPUTS,
    ],
    references=(_bnbc("Sec 6.5.8, Tables 6.6.8-6.6.11"), _aci("8.3.1")),
)
def _slab_two_way(s: Sheet) -> None:
    la, lb, h = s["la"], s["lb"], s["h"]
    if la > lb:
        raise WorksheetInputError("la is the short span: it is longer than lb")
    m = la / lb
    s.step("m", m, "", "la / lb", digits=3)
    if m < 0.5:
        raise WorksheetInputError(f"la/lb = {m:.2f} below 0.5: a one-way slab")
    case = S.two_way_case(int(s["long_cont"]), int(s["short_cont"]))
    s.step("Case", f"{case}", "", "continuity of the edges", _bnbc("Tables 6.6.8-6.6.11"))
    c = S.two_way_coefficients(m, case)
    t = S.two_way_thickness(
        lb,
        lb / la,
        s["alpha_fm"],
        s["fy"],
        int(s["long_cont"]) < 2 or int(s["short_cont"]) < 2,
        s["alpha_fm"] > 0.2,
    )
    s.step("h,min", t.required, "mm", t.note, _aci("8.3.1"))
    s.check("h ≥ h,min", h, t.required, "mm", _aci("8.3.1"), at_least=True)
    d = s.step("d (outer layer)", h - s["dc"], "mm", "h - cover to centroid")
    sw = s.step("Self weight", s["gamma"] * h / 1000, "kN/m²", "γc h")
    dead, live = sw + s["dead"], s["live"]
    combos = ST.gravity_combinations()
    for label, length, cneg, cd, cl, depth in (
        ("a", la / 1000, c.neg_a, c.dead_a, c.live_a, d),
        ("b", lb / 1000, c.neg_b, c.dead_b, c.live_b, d - s["dia"]),
    ):
        s.heading(f"Direction {label}")
        pos = max(cd * fd * dead * length**2 + cl * fl * live * length**2 for _, fd, fl in combos)
        s.step(
            f"M{label},pos",
            pos,
            "kN·m/m",
            f"C{label},dl wD l{label}² + C{label},ll wL l{label}² ({cd:.3f}, {cl:.3f})",
            _bnbc("Tables 6.6.9-6.6.10"),
        )
        _slab_mesh_checks(s, pos, depth, h, f"{label}, midspan")
        if cneg is not None:
            wu = max(fd * dead + fl * live for _, fd, fl in combos)
            neg = s.step(
                f"M{label},neg",
                cneg * wu * length**2,
                "kN·m/m",
                f"C{label},neg wu l{label}² ({cneg:.3f})",
                _bnbc("Table 6.6.8"),
            )
            _slab_mesh_checks(s, neg, d, h, f"{label}, continuous edge")


@worksheet(
    "punching",
    "Punching shear at a column",
    group="Concrete",
    summary="The critical section b0 at d/2 around an interior, edge or corner column, vc and "
    "the shear stress from Vu (no unbalanced moment).",
    inputs=[
        number(
            "c1",
            "Column c1",
            400,
            "mm",
            minimum=100,
            group=SECTION_GROUP,
            help="Across the free edge for an edge column.",
        ),
        number("c2", "Column c2", 400, "mm", minimum=100, group=SECTION_GROUP),
        number("h", "Slab thickness h", 250, "mm", minimum=100, group=SECTION_GROUP),
        number(
            "dc", "Cover to the bars' centroid (mean)", 30, "mm", minimum=15, group=SECTION_GROUP
        ),
        choice(
            "location",
            "Column",
            "interior",
            [("interior", "Interior"), ("edge", "Edge"), ("corner", "Corner")],
            group=SECTION_GROUP,
        ),
        number(
            "vu",
            "Factored shear Vu",
            600,
            "kN",
            minimum=0,
            group=LOAD_GROUP,
            help="The column load less the load within the critical section.",
        ),
        number("fc", "f'c", 25, "MPa", minimum=10, maximum=100, group="Materials"),
    ],
    references=(_aci("22.6.4, 22.6.5.2"),),
)
def _punching(s: Sheet) -> None:
    c1, c2 = s["c1"], s["c2"]
    d = s.step("d", s["h"] - s["dc"], "mm", "h - mean cover to centroid")
    big = 100 * (c1 + c2 + d)
    lo_u = -c1 / 2 if s["location"] in ("edge", "corner") else -big
    lo_v = -c2 / 2 if s["location"] == "corner" else -big
    boundary = [(lo_u, lo_v), (big, lo_v), (big, big), (lo_u, big)]
    section = S.critical_section((0.0, 0.0), c1, c2, 0.0, d, boundary)
    b0 = s.step("b0", section.b0, "mm", f"perimeter at d/2 ({section.location})", _aci("22.6.4.1"))
    beta = max(c1, c2) / min(c1, c2)
    s.step("β", beta, "", "long / short side of the column")
    s.step("αs", section.alpha_s, "", "40 interior, 30 edge, 20 corner", _aci("22.6.5.3"))
    cap = S.punching_capacity(s["fc"], d, b0, beta, section.alpha_s)
    a, b_, c_ = cap.expressions
    s.step("λs", cap.lambda_s, "", "√(2 / (1 + 0.004 d)) ≤ 1", _aci("22.5.5.1.3"))
    s.step("vc (a)", a, "MPa", "0.33 λs λ √f'c", _aci("Table 22.6.5.2 (a)"))
    s.step("vc (b)", b_, "MPa", "0.17 (1 + 2/β) λs λ √f'c", _aci("Table 22.6.5.2 (b)"))
    s.step("vc (c)", c_, "MPa", "0.083 (2 + αs d / b0) λs λ √f'c", _aci("Table 22.6.5.2 (c)"))
    vu = s.step("vu", s["vu"] * 1e3 / (b0 * d), "MPa", "Vu / (b0 d)", _aci("22.6.1.2"))
    s.check("vu ≤ φvc", vu, PHI_SHEAR * cap.vc, "MPa", _aci("22.6.1.2"), digits=3)
    s.note("Without the unbalanced moment: the design of the model adds γv Mu (ACI 8.4.4.2).")


# ─────────────────────────────────────── bars ───────────────────────────────────────


@worksheet(
    "development-length",
    "Development length",
    group="Detailing",
    summary="ld in tension (simplified or general form), ldc in compression and ldh of a "
    "standard hook.",
    inputs=[
        number("db", "Bar diameter db", 20, "mm", minimum=6, maximum=40, group=BAR_GROUP),
        *concrete_inputs(),
        choice(
            "concrete",
            "Concrete",
            "normal",
            [("normal", "Normal weight (λ = 1.0)"), ("light", "Lightweight (λ = 0.75)")],
            group="Materials",
        ),
        flag("top", "Top bar (over 300 mm of fresh concrete below)", False, group=BAR_GROUP),
        choice(
            "coating",
            "Coating",
            "1.0",
            [
                ("1.0", "Uncoated (ψe = 1.0)"),
                ("1.2", "Epoxy, other (ψe = 1.2)"),
                ("1.5", "Epoxy, small cover (ψe = 1.5)"),
            ],
            group=BAR_GROUP,
        ),
        choice(
            "method",
            "Form",
            "simplified",
            [("simplified", "Simplified (8.2.3.2)"), ("general", "General (Eq. 6.8.1)")],
            group="Method",
        ),
        flag(
            "spacing_ok", "Spacing and cover at least db (with code stirrups)", True, group="Method"
        ),
        number("cb", "cb (general form)", 50, "mm", minimum=1, group="Method"),
        number("ktr", "Ktr (general form; 0 permitted)", 0, "mm", minimum=0, group="Method"),
        number("excess", "As,req / As,prov", 1.0, minimum=0.1, maximum=1, group="Method"),
        flag("hook_cover", "Hook: side cover ≥ 65 mm", False, group="Hook"),
        flag("hook_confined", "Hook: inside ties at ≤ 3 db", False, group="Hook"),
        number("available", "Length available (0: not checked)", 0, "mm", minimum=0, group="Check"),
    ],
    references=(_bnbc("Sec 8.2.3, 8.2.4, 8.2.6"),),
)
def _development(s: Sheet) -> None:
    db, fy, fc = s["db"], s["fy"], s["fc"]
    lam = 0.75 if s["concrete"] == "light" else 1.0
    psi_e = float(s["coating"])
    ld = DT.development_tension(
        db,
        fy,
        fc,
        lam=lam,
        top=s["top"],
        psi_e=psi_e,
        method=s["method"],
        spacing_ok=s["spacing_ok"],
        cb=s["cb"],
        k_tr=s["ktr"],
        excess=s["excess"],
    )
    s.step("ld (tension)", ld.value, "mm", ld.formula, ld.clause)
    ldc = DT.development_compression(db, fy, fc, lam=lam, excess=s["excess"])
    s.step("ldc (compression)", ldc.value, "mm", ldc.formula, ldc.clause)
    ldh = DT.hook_development(
        db,
        fy,
        fc,
        lam=lam,
        psi_e=psi_e,
        cover=s["hook_cover"],
        confined=s["hook_confined"],
        excess=s["excess"],
    )
    s.step("ldh (standard hook)", ldh.value, "mm", ldh.formula, ldh.clause)
    if s["available"] > 0:
        s.check("Length available ≥ ld", s["available"], ld.value, "mm", ld.clause, at_least=True)


@worksheet(
    "lap-splice",
    "Lap splice",
    group="Detailing",
    summary="Class A or B tension lap and the compression lap of a bar.",
    inputs=[
        number("db", "Bar diameter db", 20, "mm", minimum=6, maximum=32, group=BAR_GROUP),
        *concrete_inputs(),
        flag("top", "Top bar", False, group=BAR_GROUP),
        number("ratio", "As,prov / As,req over the lap", 1.0, minimum=1, group="Lap"),
        number(
            "share", "Share of bars spliced within the lap", 1.0, minimum=0, maximum=1, group="Lap"
        ),
        flag("spacing_ok", "Spacing and cover at least db (with code stirrups)", True, group="Lap"),
    ],
    references=(_bnbc("Sec 8.2.13, 8.2.14"),),
)
def _lap(s: Sheet) -> None:
    db, fy, fc = s["db"], s["fy"], s["fc"]
    cls = DT.splice_class(s["ratio"], s["share"])
    s.step("Class", cls, "", "A: As,prov ≥ 2 As,req and ≤ half spliced", _bnbc("Sec 8.2.13.2"))
    lap = DT.lap_tension(db, fy, fc, cls=cls, top=s["top"], spacing_ok=s["spacing_ok"])
    s.step("Tension lap", lap.value, "mm", lap.formula, lap.clause)
    comp = DT.lap_compression(db, fy, fc)
    s.step("Compression lap", comp.value, "mm", comp.formula, comp.clause)


# ─────────────────────────────────────── lintels and stairs ───────────────────────────────────


@worksheet(
    "lintel",
    "Lintel over an opening",
    group="Concrete",
    summary="Loads (with arching of the masonry above), bars, stirrups and the checks of a lintel, "
    "as the design of the model makes them.",
    inputs=[
        number("clear", "Clear opening", 1200, "mm", minimum=300, group="Opening"),
        number("above", "Masonry above the lintel", 1500, "mm", minimum=0, group="Opening"),
        number("b", "Width", 250, "mm", minimum=100, group=SECTION_GROUP),
        number("h", "Depth", 250, "mm", minimum=100, group=SECTION_GROUP),
        number("floor_dead", "Floor dead load on it", 0, "kN/m", minimum=0, group=LOAD_GROUP),
        number("floor_live", "Floor live load on it", 0, "kN/m", minimum=0, group=LOAD_GROUP),
        number("masonry", "Masonry unit weight", 18.85, "kN/m³", minimum=10, group=LOAD_GROUP),
        *concrete_inputs(),
    ],
    references=(_bnbc("Table 6.6.1"), ACI),
)
def _lintel(s: Sheet) -> None:
    loads = lintel_loads(
        s["clear"],
        s["b"],
        s["h"],
        s["above"],
        masonry_weight=s["masonry"],
        floor_dead=s["floor_dead"],
        floor_live=s["floor_live"],
    )
    s.step("Effective span L", loads.span, "mm", "clear + bearing")
    s.step("Dead load", loads.dead, "kN/m", "self weight and masonry")
    if loads.triangle:
        s.step(
            "Masonry triangle (peak)",
            loads.triangle,
            "kN/m",
            f"45° triangle {loads.triangle_height:.0f} mm high",
        )
    result = design_lintel(loads, s["b"], s["h"], s["fc"], s["fy"])
    s.step("Mu", result["loads"]["Mu"], "kN·m", "governing combination")
    s.step("Vu", result["loads"]["Vu"], "kN", "governing combination")
    s.step("Bars", result["label"], "", "the least that pass")
    for check in result["checks"]:
        s.adopt(check)
    for text in result["notes"]:
        s.note(text)


@worksheet(
    "stair-flight",
    "Stair flight",
    group="Concrete",
    summary="Geometry, loads, moments and the checks of a straight flight spanning between "
    "beams, as the design of the model makes them.",
    inputs=[
        number("rise", "Rise of the flight", 1750, "mm", minimum=300, group="Geometry"),
        number("riser", "Riser", 175, "mm", minimum=100, maximum=250, group="Geometry"),
        number("tread", "Tread", 290, "mm", minimum=150, maximum=400, group="Geometry"),
        number("width", "Width", 1200, "mm", minimum=600, group="Geometry"),
        number("waist", "Waist", 150, "mm", minimum=80, group="Geometry"),
        number("support", "Support width", 250, "mm", minimum=0, group="Geometry"),
        flag("continuous", "Continuous at both ends", False, group="Geometry"),
        number("finish", "Finish", 1.2, "kN/m²", minimum=0, group=LOAD_GROUP),
        number("live", "Live load", ST.LIVE_STAIRS, "kN/m²", minimum=0, group=LOAD_GROUP),
        *concrete_inputs(),
        number("cover", "Cover", 20, "mm", minimum=15, group=BAR_GROUP),
        number("dia", "Main bars", 12, "mm", minimum=8, maximum=20, group=BAR_GROUP),
        number("spacing", "Main bar spacing", 150, "mm", minimum=75, group=BAR_GROUP),
        number("dist_dia", "Distribution bars", 10, "mm", minimum=6, maximum=16, group=BAR_GROUP),
        number("dist_spacing", "Distribution spacing", 200, "mm", minimum=75, group=BAR_GROUP),
    ],
    references=(_bnbc("Sec 6.7.1, Table 6.6.1"), "BNBC 2020 Part 3 Sec 1.14"),
)
def _stair(s: Sheet) -> None:
    end = "continuous" if s["continuous"] else "simple"
    top = ST.Mesh(s["dia"], s["spacing"]) if s["continuous"] else None
    bars = ST.StairBars(
        "",
        s["cover"],
        ST.Mesh(s["dia"], s["spacing"]),
        ST.Mesh(s["dist_dia"], s["dist_spacing"]),
        top,
    )
    spec = ST.StairSpec(
        s["waist"],
        s["riser"],
        s["tread"],
        s["width"],
        support_width=s["support"],
        bottom_end=end,
        top_end=end,
        bars=bars,
    )
    material = ST.StairMaterial(s["fc"], s["fy"])
    loads = ST.StairLoads(s["finish"], s["live"], ST.gravity_combinations())
    result = ST.design_stair("worksheet", "worksheet", spec, s["rise"], material, loads)
    for flight in result.geometry.flights:
        s.step(f"{flight.name}: risers", f"{flight.risers} × {flight.riser:.1f} mm")
        s.step(f"{flight.name}: span", flight.span, "mm", flight.rule)
        s.step(
            f"{flight.name}: mean thickness",
            flight.mean_thickness(spec.waist),
            "mm",
            "t / cos θ + R / 2",
        )
    if result.entry:
        for part in result.entry["parts"]:
            s.step(f"{part['name']}: wu", part["wu"], "kN/m²", part["combination"] or "")
            s.step(f"{part['name']}: Mu", part["mu"], "kN·m/m")
            s.step(f"{part['name']}: Vu", part["vu"], "kN/m")
        for check in result.entry["checks"]:
            s.adopt(check)
    for text in result.notes:
        s.note(text)

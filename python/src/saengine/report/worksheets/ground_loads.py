"""Foundation and load worksheets: an isolated footing, bearing capacity, a cantilever
retaining wall, the wind on a sign and the equivalent static seismic base shear.

The footing uses the capacities of :mod:`saengine.substructure.shallow`, the bearing capacity
:mod:`saengine.soil.bearing`, the loads :mod:`saengine.fem.loads` with the code pack in force.
"""

from __future__ import annotations

import math

from saengine.codes import context as code_context
from saengine.codes.context import default_pack
from saengine.design import bars as B
from saengine.design import slab as S
from saengine.design.rc import PHI_SHEAR, bar_area
from saengine.fem import loads as L
from saengine.report.worksheets.concrete import BAR_GROUP, LOAD_GROUP, SECTION_GROUP, _aci, _bnbc
from saengine.report.worksheets.core import (
    Sheet,
    WorksheetInputError,
    choice,
    concrete_inputs,
    flag,
    number,
    worksheet,
)
from saengine.soil.bearing import ultimate
from saengine.soil.earth_pressure import rankine_active
from saengine.substructure import shallow as SH

SOIL_GROUP = "Soil"

# ─────────────────────────────────────── footing ───────────────────────────────────────


@worksheet(
    "footing-isolated",
    "Isolated footing (concentric)",
    group="Foundations",
    summary="Soil pressure against the allowable, one-way shear, punching and flexure of a "
    "rectangular pad under one column, each way.",
    inputs=[
        number("c1", "Column c1 (along L)", 400, "mm", minimum=100, group=SECTION_GROUP),
        number("c2", "Column c2 (along B)", 400, "mm", minimum=100, group=SECTION_GROUP),
        number("length", "Footing length L", 2400, "mm", minimum=300, group=SECTION_GROUP),
        number("width", "Footing width B", 2400, "mm", minimum=300, group=SECTION_GROUP),
        number("h", "Thickness h", 700, "mm", minimum=150, group=SECTION_GROUP),
        number(
            "dc", "Cover to the outer bars' centroid", 85, "mm", minimum=50, group=SECTION_GROUP
        ),
        number(
            "p",
            "Service load (D + L, with the footing and fill)",
            1400,
            "kN",
            minimum=0,
            group=LOAD_GROUP,
        ),
        number("pu", "Factored load Pu (column only)", 1900, "kN", minimum=0, group=LOAD_GROUP),
        number("qa", "Allowable bearing pressure qa", 250, "kPa", minimum=1, group=LOAD_GROUP),
        *concrete_inputs(),
        number(
            "dia", "Bar diameter (both ways)", 16, "mm", minimum=10, maximum=32, group=BAR_GROUP
        ),
        number("spacing", "Bar spacing", 150, "mm", minimum=75, group=BAR_GROUP),
    ],
    references=(_aci("13.3, 22.5, 22.6, 7.6.1.1"), "BNBC 2020 Part 6 Ch 3"),
)
def _footing(s: Sheet) -> None:
    lg, wd, h, fc, fy = s["length"], s["width"], s["h"], s["fc"], s["fy"]
    c1, c2 = s["c1"], s["c2"]
    if c1 >= lg or c2 >= wd:
        raise WorksheetInputError("the column is wider than the footing")
    pressure = SH.soil_pressure(s["p"] * 1e3, 0.0, 0.0, lg, wd)
    q = s.step("q (service)", pressure.qmax * 1e3, "kPa", "P / (B L)")
    s.check("q ≤ qa", q, s["qa"], "kPa", "BNBC 2020 Part 6 Ch 3 (allowable bearing)")
    qu = s.step("qu (factored)", s["pu"] * 1e3 / (lg * wd) * 1e3, "kPa", "Pu / (B L)")
    qu_mpa = qu / 1e3
    d_outer = s.step("d (outer layer)", h - s["dc"], "mm", "h - cover to centroid")
    as_m = bar_area(s["dia"]) * 1000 / s["spacing"]
    s.step("As provided", as_m, "mm²/m", f"Ø{s['dia']:g} @ {s['spacing']:g}")
    as_min = SH.min_steel_ratio(fy) * 1000 * h
    s.step("As,min", as_min, "mm²/m", "ratio × b h", _aci("Table 7.6.1.1"))
    s.check("As provided ≥ As,min", as_m, as_min, "mm²/m", _aci("7.6.1.1"), at_least=True)
    for name, span, col, across, d in (
        ("along L", lg, c1, wd, d_outer),
        ("along B", wd, c2, lg, d_outer - s["dia"]),
    ):
        s.heading(f"Bending {name} (d = {d:.0f} mm)")
        arm = (span - col) / 2
        mu = qu_mpa * across * arm**2 / 2
        s.step(
            f"Mu ({name})",
            mu / 1e6,
            "kN·m",
            "qu B' (cantilever)² / 2 at the column face",
            _aci("13.2.7.1"),
        )
        need = B.slab_flexure_need(mu / across * 1000, d, fc, fy)
        s.step("As required", need.area, "mm²/m", "1 m strip, stress block", _aci("22.2"))
        s.check(
            f"As provided ≥ As required ({name})",
            as_m,
            need.area,
            "mm²/m",
            _aci("22.2"),
            at_least=True,
        )
        shear_arm = arm - d
        vu = qu_mpa * across * max(shear_arm, 0.0)
        rho = as_m / (1000 * d)
        phi_vc = SH.one_way_shear_capacity(across, d, rho, fc)
        s.step(f"Vu at d ({name})", vu / 1e3, "kN", "qu B' (cantilever - d)", _aci("13.2.7.2"))
        s.check(f"Vu ≤ φVc ({name})", vu / 1e3, phi_vc / 1e3, "kN", _aci("Table 22.5.5.1 (c)"))
    s.heading("Punching at the column")
    d = d_outer - s["dia"] / 2
    b0 = s.step(
        "b0", 2 * (c1 + d) + 2 * (c2 + d), "mm", "2 (c1 + d) + 2 (c2 + d)", _aci("22.6.4.1")
    )
    vu = s["pu"] * 1e3 - qu_mpa * (c1 + d) * (c2 + d)
    s.step("Vu", vu / 1e3, "kN", "Pu - qu (c1 + d)(c2 + d)", _aci("22.6.4"))
    vc = SH.punching_stress(c1, c2, d, b0, 40.0, fc)
    s.step("vc", vc, "MPa", "least of (a), (b), (c) × λs λ √f'c", _aci("Table 22.6.5.2"))
    s.check("vu ≤ φvc", vu / (b0 * d), PHI_SHEAR * vc, "MPa", _aci("22.6.1.2"), digits=3)


# ─────────────────────────────────────── bearing ───────────────────────────────────────


@worksheet(
    "bearing-capacity",
    "Bearing capacity (general equation)",
    group="Foundations",
    summary="Ultimate and allowable bearing pressure of a shallow footing with Vesic's factors.",
    inputs=[
        number("c", "Cohesion c", 0, "kPa", minimum=0, group=SOIL_GROUP),
        number("phi", "Friction angle φ", 30, "°", minimum=0, maximum=45, group=SOIL_GROUP),
        number(
            "gamma",
            "Unit weight γ (below the base)",
            18,
            "kN/m³",
            minimum=5,
            group=SOIL_GROUP,
            help="Submerged where the water table is within B below it.",
        ),
        number(
            "gamma_above", "Unit weight above the base", 18, "kN/m³", minimum=5, group=SOIL_GROUP
        ),
        number("df", "Depth of the base Df", 1.5, "m", minimum=0, group="Footing"),
        number("b", "Width B", 2.0, "m", minimum=0.3, group="Footing"),
        number("l", "Length L", 2.0, "m", minimum=0.3, group="Footing"),
        number(
            "fs",
            "Factor of safety",
            3.0,
            minimum=1,
            group="Footing",
            help="The project's factor of safety on the ultimate bearing capacity.",
        ),
        number("q", "Applied pressure (0: not checked)", 0, "kPa", minimum=0, group="Check"),
    ],
    references=(
        "BNBC 2020 Part 6 Ch 3 (shallow foundations)",
        "Vesic (1973) bearing capacity factors",
    ),
)
def _bearing(s: Sheet) -> None:
    q = s.step("q (overburden)", s["gamma_above"] * s["df"], "kPa", "γ Df")
    r = ultimate(s["c"], s["phi"], q, s["gamma"], s["b"], s["l"], s["df"])
    s.step("Nc", r["Nc"], "", "(Nq - 1) cot φ")
    s.step("Nq", r["Nq"], "", "e^(π tan φ) tan²(45° + φ/2)")
    s.step("Nγ", r["Ngamma"], "", "2 (Nq + 1) tan φ")
    s.step(
        "sc, sq, sγ", f"{r['sc']:.2f}, {r['sq']:.2f}, {r['sgamma']:.2f}", "", "shape factors (B/L)"
    )
    s.step("dc, dq", f"{r['dc']:.2f}, {r['dq']:.2f}", "", "depth factors (Df/B)")
    qu = s.step("qu", r["qu"], "kPa", "c Nc sc dc + q Nq sq dq + ½ γ B Nγ sγ")
    qa = s.step("qa", qu / s["fs"], "kPa", "qu / FS")
    if s["q"] > 0:
        s.check("q ≤ qa", s["q"], qa, "kPa", "BNBC 2020 Part 6 Ch 3")
    s.note("The settlement may govern the allowable pressure; see 1 Soil Report.")


# ─────────────────────────────────────── retaining wall ───────────────────────────────────


@worksheet(
    "retaining-wall",
    "Cantilever retaining wall",
    group="Foundations",
    summary="Rankine active pressure, overturning, sliding and bearing of a cantilever wall, "
    "and the stem's flexure and shear at its base.",
    inputs=[
        number(
            "height",
            "Retained height H (top of base to ground)",
            3000,
            "mm",
            minimum=500,
            group="Geometry",
        ),
        number("stem", "Stem thickness at the base", 300, "mm", minimum=150, group="Geometry"),
        number("stem_top", "Stem thickness at the top", 200, "mm", minimum=150, group="Geometry"),
        number("toe", "Toe length", 800, "mm", minimum=0, group="Geometry"),
        number("heel", "Heel length", 1600, "mm", minimum=0, group="Geometry"),
        number("base", "Base thickness", 400, "mm", minimum=200, group="Geometry"),
        number(
            "phi", "Backfill friction angle φ", 30, "°", minimum=10, maximum=45, group=SOIL_GROUP
        ),
        number("gamma", "Backfill unit weight γ", 18, "kN/m³", minimum=10, group=SOIL_GROUP),
        number("surcharge", "Surcharge q", 10, "kPa", minimum=0, group=SOIL_GROUP),
        number("mu", "Base friction coefficient μ", 0.5, minimum=0.1, maximum=1, group=SOIL_GROUP),
        number("qa", "Allowable bearing pressure qa", 150, "kPa", minimum=1, group=SOIL_GROUP),
        number(
            "fs_ot",
            "Required FS overturning",
            2.0,
            minimum=1,
            group="Stability",
            help="The project's factor; BNBC 2020 does not set one for retaining walls.",
        ),
        number(
            "fs_sl",
            "Required FS sliding",
            1.5,
            minimum=1,
            group="Stability",
            help="The project's factor; BNBC 2020 does not set one for retaining walls.",
        ),
        number("gamma_c", "Concrete unit weight", 24, "kN/m³", minimum=15, group="Materials"),
        *concrete_inputs(),
        number("dc", "Stem cover to the bars' centroid", 60, "mm", minimum=40, group=BAR_GROUP),
        number("dia", "Stem bar diameter", 16, "mm", minimum=10, maximum=32, group=BAR_GROUP),
        number("spacing", "Stem bar spacing", 150, "mm", minimum=75, group=BAR_GROUP),
    ],
    references=(
        _bnbc("Sec 2.6.5, 2.7.3.1"),
        _aci("11, 22.2, 22.5"),
        "Rankine active earth pressure",
    ),
)
def _retaining(s: Sheet) -> None:
    hm = (s["height"] + s["base"]) / 1000  # m, full height to the underside of the base
    t, tt, toe, heel, tb = (s[k] / 1000 for k in ("stem", "stem_top", "toe", "heel", "base"))
    gamma, q, gc = s["gamma"], s["surcharge"], s["gamma_c"]
    ka = s.step("Ka", rankine_active(s["phi"]), "", "(1 - sin φ) / (1 + sin φ)", digits=3)
    s.heading("Stability (service, per metre)")
    pa_soil = s.step(
        "Pa (soil)", 0.5 * ka * gamma * hm**2, "kN/m", "½ Ka γ H'²", _bnbc("Sec 2.6.5")
    )
    pa_q = s.step("Pa (surcharge)", ka * q * hm, "kN/m", "Ka q H'", _bnbc("Sec 2.6.5"))
    m_ot = s.step("Overturning moment", pa_soil * hm / 3 + pa_q * hm / 2, "kN·m/m", "about the toe")
    width = toe + t + heel
    stem_h = s["height"] / 1000
    parts = [
        ("stem (rectangle)", gc * tt * stem_h, toe + t - tt / 2),
        ("stem (taper)", gc * (t - tt) * stem_h / 2, toe + (t - tt) * 2 / 3),
        ("base", gc * width * tb, width / 2),
        ("soil on heel", gamma * heel * stem_h, toe + t + heel / 2),
        ("surcharge on heel", q * heel, toe + t + heel / 2),
    ]
    total = sum(w for _, w, _ in parts)
    m_r = sum(w * x for _, w, x in parts)
    s.step("ΣW", total, "kN/m", " + ".join(n for n, _, _ in parts))
    s.step("Resisting moment", m_r, "kN·m/m", "Σ W x about the toe")
    s.check("FS overturning", m_r / m_ot, s["fs_ot"], "", "the project's factor", at_least=True)
    s.check(
        "FS sliding",
        s["mu"] * total / (pa_soil + pa_q),
        s["fs_sl"],
        "",
        "μ ΣW / Pa; the project's factor",
        at_least=True,
    )
    x = (m_r - m_ot) / total
    e = s.step("e", width / 2 - x, "m", "B/2 - (Mr - Mo)/ΣW", digits=3)
    pressure = SH.soil_pressure(total * 1e3, e * 1000, 0.0, width * 1000, 1000.0)
    s.step("q,max", pressure.qmax * 1e3, "kPa", "trapezoid or triangle (no tension)")
    s.step("q,min", pressure.qmin * 1e3, "kPa", "")
    s.check("q,max ≤ qa", pressure.qmax * 1e3, s["qa"], "kPa", "BNBC 2020 Part 6 Ch 3")
    s.check(
        "Resultant in the middle third",
        abs(e),
        width / 6,
        "m",
        "no tension under the base",
        digits=3,
    )
    s.heading("Stem at the top of the base (strength, per metre)")
    hs = stem_h
    factor = 1.6  # H in BNBC 2020 Part 6 Sec 2.7.3.1 combinations (2) and (6)
    mu = factor * (ka * gamma * hs**3 / 6 + ka * q * hs**2 / 2)
    vu = factor * (ka * gamma * hs**2 / 2 + ka * q * hs)
    s.step("Mu", mu, "kN·m/m", "1.6 (Ka γ h³/6 + Ka q h²/2)", _bnbc("Sec 2.7.3.1"))
    s.step("Vu", vu, "kN/m", "1.6 (Ka γ h²/2 + Ka q h)", _bnbc("Sec 2.7.3.1"))
    d = s.step("d", s["stem"] - s["dc"], "mm", "stem - cover to centroid")
    need = B.slab_flexure_need(mu * 1e6, d, s["fc"], s["fy"])
    s.step("As required", need.area, "mm²/m", "1 m strip, stress block", _aci("22.2"))
    as_m = bar_area(s["dia"]) * 1000 / s["spacing"]
    as_min = S.min_steel_ratio(s["fy"]) * 1000 * s["stem"]
    s.check(
        "As provided ≥ As required",
        as_m,
        max(need.area, as_min),
        "mm²/m",
        _aci("22.2, 11.6.1"),
        at_least=True,
    )
    phi_vc, _ = S.one_way_shear(as_m / (1000 * d), d, s["fc"])
    s.check("Vu ≤ φVc", vu, phi_vc / 1e3, "kN/m", _aci("Table 22.5.5.1 (c)"))
    s.note(
        "Level backfill, drained (no water pressure behind the wall), active pressure on the "
        "vertical plane through the heel; passive resistance at the toe is left out."
    )


# ─────────────────────────────────────── wind on a sign ───────────────────────────────────


def _categories() -> list[tuple[str, str]]:
    table = default_pack().table("occupancyCategories")
    return [(k, f"{k}: {v.description}") for k, v in table.categories.items()]


@worksheet(
    "wind-sign",
    "Wind on a freestanding sign or wall",
    group="Loads",
    summary="The velocity pressure at the top of a solid freestanding sign or wall and the "
    "design wind force F = qh G Cf As.",
    inputs=[
        number(
            "speed",
            "Basic wind speed V",
            65.7,
            "m/s",
            minimum=20,
            maximum=100,
            group="Site",
            help="BNBC 2020 Part 6 Table 6.2.8 for the location (Dhaka 65.7).",
        ),
        choice("exposure", "Exposure", "B", [("A", "A"), ("B", "B"), ("C", "C")], group="Site"),
        choice("category", "Occupancy category", "II", _categories(), group="Site"),
        number("height", "Height to the top h", 8, "m", minimum=1, group="Sign"),
        number("depth", "Sign depth s (vertical)", 3, "m", minimum=0.1, group="Sign"),
        number("width", "Sign width B (horizontal)", 6, "m", minimum=0.1, group="Sign"),
        number(
            "cf",
            "Force coefficient Cf",
            1.8,
            minimum=0.5,
            maximum=3,
            group="Sign",
            help="From BNBC 2020 Part 6's force coefficients for solid freestanding walls "
            "and signs, for s/h and B/s.",
        ),
    ],
    references=(_bnbc("Sec 2.4 (Tables 6.2.8, 6.2.9, 6.2.11, 6.2.12; Sec 2.4.7, 2.4.8.1)"),),
)
def _wind_sign(s: Sheet) -> None:
    h, sd, b = s["height"], s["depth"], s["width"]
    if sd > h:
        raise WorksheetInputError("the sign is deeper than its height to the top")
    importance = code_context.table("occupancyCategories").categories[s["category"]]
    i_w = s.step("I", importance.windImportance, "", "wind importance", _bnbc("Table 6.2.9"))
    kz = s.step(
        "Kz at h",
        L.exposure_coefficient(h, s["exposure"]),
        "",
        "2.01 (z/zg)^(2/α)",
        _bnbc("Table 6.2.11"),
    )
    s.step("Kzt", L.wind_factor("topographic"), "", "topographic factor", _bnbc("Sec 2.4.7"))
    s.step("Kd", L.wind_factor("directionality"), "", "directionality", _bnbc("Table 6.2.12"))
    qh = s.step(
        "qh",
        L.velocity_pressure(h, s["speed"], s["exposure"], i_w),
        "kN/m²",
        "0.000613 Kz Kzt Kd V² I",
        _bnbc("Sec 2.4"),
    )
    g = s.step("G", L.wind_factor("gust"), "", "gust-effect factor (rigid)", _bnbc("Sec 2.4.8.1"))
    s.step("s/h, B/s", f"{sd / h:.2f}, {b / sd:.2f}", "", "for Cf")
    area = s.step("As", b * sd, "m²", "B s")
    force = s.step("F", qh * g * s["cf"] * area, "kN", "qh G Cf As", _bnbc("Sec 2.4"))
    s.step("Height of F (case A)", h - sd / 2, "m", "at the sign's mid-height")
    s.step("Moment at the ground", force * (h - sd / 2), "kN·m", "F × height (case A)")
    s.note(
        f"Kz = {kz:.3f}. Check the eccentric case (B, resultant at 0.2 B from the centre) "
        "and, for B/s ≥ 2, case C as BNBC's figure for signs requires."
    )


# ─────────────────────────────────────── seismic base shear ───────────────────────────────


def _systems() -> list[tuple[str, str]]:
    return [(k, v.name) for k, v in default_pack().table("seismic").systems.items()]


def _site_classes() -> list[tuple[str, str]]:
    return [(k, k) for k in default_pack().table("seismic").siteClasses]


def _zones() -> list[tuple[str, str]]:
    zones = default_pack().table("zoneCoefficients").zones
    return [(str(k), f"Zone {k} (Z = {v:g})") for k, v in zones.items()]


@worksheet(
    "seismic-base-shear",
    "Seismic base shear (equivalent static)",
    group="Loads",
    summary="Approximate period, design spectral acceleration Sa and base shear V = Sa W, with "
    "the forces per level when the levels are given.",
    inputs=[
        choice("zone", "Seismic zone", "2", _zones(), group="Site"),
        choice("site", "Site class", "SD", _site_classes(), group="Site"),
        choice("category", "Occupancy category", "II", _categories(), group="Site"),
        choice("system", "Structural system", "rcImf", _systems(), group="Structure"),
        number("hn", "Height hn above the base", 30, "m", minimum=1, group="Structure"),
        number("weight", "Seismic weight W", 50000, "kN", minimum=1, group="Structure"),
        number(
            "storeys",
            "Storeys (equal height and weight; 0: no distribution)",
            10,
            minimum=0,
            maximum=60,
            group="Structure",
        ),
        flag("period_given", "Use a period from analysis", False, group="Period"),
        number("period", "Period from analysis T", 1.0, "s", minimum=0.01, group="Period"),
    ],
    references=(_bnbc("Sec 2.5 (Tables 6.2.14-6.2.20; Eq. 6.2.38; Sec 2.5.7)"),),
)
def _seismic(s: Sheet) -> None:
    table = code_context.table("seismic")
    z = s.step(
        "Z",
        code_context.table("zoneCoefficients").zones[int(s["zone"])],
        "",
        f"zone {s['zone']}",
        _bnbc("Table 6.2.14"),
    )
    cat = code_context.table("occupancyCategories").categories[s["category"]]
    i_e = s.step("I", cat.seismicImportance, "", f"category {s['category']}", _bnbc("Table 6.2.17"))
    system = table.systems[s["system"]]
    r = s.step("R", system.R, "", system.name, _bnbc(f"Table 6.2.19 row {system.row}"))
    family = system.periodFamily or "other"
    coef = table.periodCoefficients[family]
    ta = s.step(
        "Ta",
        L.approximate_period(s["hn"], s["system"]),
        "s",
        f"Ct hn^m (Ct = {coef.Ct:g}, m = {coef.m:g})",
        _bnbc("Table 6.2.20, Eq. 6.2.38"),
    )
    t = ta
    if s["period_given"]:
        cap = float(getattr(table, "periodUpperFactor", None) or 1.4) * ta
        t = s.step(
            "T", min(max(s["period"], ta), cap), "s", "Ta ≤ T ≤ 1.4 Ta", _bnbc("Sec 2.5.7.2 (a)")
        )
    site = table.siteClasses[s["site"]]
    s.step(
        "S, TB, TC, TD",
        f"{site.S:g}, {site.TB:g}, {site.TC:g}, {site.TD:g}",
        "",
        f"site class {s['site']}",
        _bnbc("Table 6.2.16"),
    )
    s.step(
        "Cs", L.normalized_spectrum(t, s["site"]), "", "normalized spectrum at T", _bnbc("Sec 2.5")
    )
    sa = s.step(
        "Sa",
        L.design_acceleration(t, s["site"], z, i_e, r),
        "g",
        "(2/3) Z I / R Cs",
        _bnbc("Sec 2.5"),
        digits=4,
    )
    v = s.step("V", sa * s["weight"], "kN", "Sa W", _bnbc("Sec 2.5.7"))
    n = int(s["storeys"])
    if n:
        s.heading("Vertical distribution")
        storey = s["hn"] / n
        levels = [((i + 1) * storey, s["weight"] / n) for i in range(n)]
        forces = L.vertical_distribution(levels, v, t)
        k = 1.0 if t <= 0.5 else 2.0 if t >= 2.5 else 1 + (t - 0.5) / 2
        s.step("k", k, "", "1 for T ≤ 0.5 s, 2 for T ≥ 2.5 s", _bnbc("Sec 2.5.7"))
        for (height, _), force in reversed(list(zip(levels, forces, strict=True))):
            s.step(f"F at {height:.1f} m", force, "kN", "V wx hx^k / Σ wi hi^k", _bnbc("Sec 2.5.7"))
    s.note(
        f"T = {t:.3f} s. The design of the model also adds the accidental torsion and checks "
        "the drifts (Sec 2.5.7.6, 2.5.7.7)."
    )
    if math.isclose(t, ta):
        s.note("Approximate period: a period from analysis may raise T up to 1.4 Ta.")

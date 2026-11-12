"""Foundation and load worksheets: an isolated footing, bearing capacity, a cantilever
retaining wall, the wind on a sign and the equivalent static seismic base shear.

The footing uses the capacities of :mod:`saengine.substructure.shallow`, the bearing capacity
:mod:`saengine.soil.bearing`, the loads :mod:`saengine.fem.loads` with the code pack in force.
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

from saengine.codes import context as code_context
from saengine.codes.context import default_pack
from saengine.design import bars as B
from saengine.design import rc
from saengine.design import slab as S
from saengine.design.rc import bar_area
from saengine.fem import loads as L
from saengine.fem import open_wind as OW
from saengine.report.worksheets.concrete import BAR_GROUP, LOAD_GROUP, SECTION_GROUP, _aci, _code
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


def earth_pressure_factor() -> float:
    """The largest factor of H (lateral earth pressure) in the strength combinations of the code
    pack in force (1.6 in the default pack)."""
    factors = [
        float((getattr(c, "factors", None) or {}).get("H", 0.0))
        for c in code_context.table("combinations").strength
    ]
    if not factors or max(factors) <= 0:
        raise WorksheetInputError("the code pack in force has no strength factor of H")
    return max(factors)


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
    references=(_aci("13.3, 22.5, 22.6, 7.6.1.1"), _code("wsFoundations")),
)
def _footing(s: Sheet) -> None:
    lg, wd, h, fc, fy = s["length"], s["width"], s["h"], s["fc"], s["fy"]
    c1, c2 = s["c1"], s["c2"]
    if c1 >= lg or c2 >= wd:
        raise WorksheetInputError("the column is wider than the footing")
    pressure = SH.soil_pressure(s["p"] * 1e3, 0.0, 0.0, lg, wd)
    q = s.step("q (service)", pressure.qmax * 1e3, "kPa", "P / (B L)")
    s.check("q ≤ qa", q, s["qa"], "kPa", _code("wsFoundations", " (allowable bearing)"))
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
    s.check(
        "vu ≤ φvc", vu / (b0 * d), rc.value("PHI_SHEAR") * vc, "MPa", _aci("22.6.1.2"), digits=3
    )


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
        _code("wsFoundations", " (shallow foundations)"),
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
        s.check("q ≤ qa", s["q"], qa, "kPa", _code("wsFoundations"))
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
            help="The project's factor (the default code pack sets none for retaining walls).",
        ),
        number(
            "fs_sl",
            "Required FS sliding",
            1.5,
            minimum=1,
            group="Stability",
            help="The project's factor (the default code pack sets none for retaining walls).",
        ),
        number("gamma_c", "Concrete unit weight", 24, "kN/m³", minimum=15, group="Materials"),
        *concrete_inputs(),
        number("dc", "Stem cover to the bars' centroid", 60, "mm", minimum=40, group=BAR_GROUP),
        number("dia", "Stem bar diameter", 16, "mm", minimum=10, maximum=32, group=BAR_GROUP),
        number("spacing", "Stem bar spacing", 150, "mm", minimum=75, group=BAR_GROUP),
    ],
    references=(
        _code("wsRetaining"),
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
        "Pa (soil)", 0.5 * ka * gamma * hm**2, "kN/m", "½ Ka γ H'²", _code("wsEarthPressure")
    )
    pa_q = s.step("Pa (surcharge)", ka * q * hm, "kN/m", "Ka q H'", _code("wsEarthPressure"))
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
    s.check("q,max ≤ qa", pressure.qmax * 1e3, s["qa"], "kPa", _code("wsFoundations"))
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
    factor = earth_pressure_factor()
    mu = factor * (ka * gamma * hs**3 / 6 + ka * q * hs**2 / 2)
    vu = factor * (ka * gamma * hs**2 / 2 + ka * q * hs)
    s.step("Mu", mu, "kN·m/m", f"{factor:g} (Ka γ h³/6 + Ka q h²/2)", _code("wsCombinations"))
    s.step("Vu", vu, "kN/m", f"{factor:g} (Ka γ h²/2 + Ka q h)", _code("wsCombinations"))
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


def _topography_inputs() -> list[Any]:
    group = "Topography"
    return [
        choice(
            "feature",
            "Topographic feature",
            "none",
            [
                ("none", "None (flat terrain)"),
                ("ridge", "2-D ridge"),
                ("escarpment", "2-D escarpment"),
                ("hill", "3-D axisymmetrical hill"),
            ],
            group=group,
        ),
        number("hillHeight", "Height of the feature H", 20, "m", minimum=0.1, group=group),
        number("hillLength", "Half-height distance Lh", 60, "m", minimum=0.1, group=group),
        number("crest", "Distance from the crest x", 0, "m", minimum=0, group=group),
        flag("downwind", "Downwind of the crest", False, group=group),
    ]


def _topography_settings(s: Sheet) -> Any:
    """The worksheet's topography inputs as the wind settings :func:`L.wind_overrides` reads."""
    topo = SimpleNamespace(
        feature=s["feature"],
        height=s["hillHeight"],
        length=s["hillLength"],
        distance=s["crest"],
        side="downwind" if s["downwind"] else "upwind",
        isolated=True,
    )
    return SimpleNamespace(topography=topo)


def _kz_formula() -> str:
    """How Kz is found by the wind method of the pack in force (C11: the formula text follows
    the method, not the default pack's)."""
    table = code_context.table("wind")
    if table.method == "speedFactors":
        return "k2² (terrain and height factor)"
    factor = table.kzFactor if table.kzFactor is not None else 2.01
    return f"{factor:g} (z/zg)^(2/α)"


def _pressure_formula() -> str:
    """How qz is found by the wind method of the pack in force (C11)."""
    method = code_context.table("wind").method
    if method == "peakVelocityPressure":
        return "peak velocity pressure qp(z) = ce(z) qb"
    if method == "speedFactors":
        return "design wind pressure from Vz = Vb k1 k2 k3 k4"
    return "0.000613 Kz Kzt Kd V² I"


def _velocity_steps(s: Sheet, z: float, where: str) -> tuple[float, float]:
    """The steps I, Kz, Kzt, Kd and qz at height ``z``; returns (qz, Kz)."""
    importance = code_context.table("occupancyCategories").categories[s["category"]]
    i_w = s.step("I", importance.windImportance, "", "wind importance", _code("wsWindImportance"))
    kz = s.step(
        f"Kz at {where}",
        L.exposure_coefficient(z, s["exposure"]),
        "",
        _kz_formula(),
        _code("wsExposure"),
    )
    terms = L.topographic_terms(z, s["exposure"])
    if terms is not None and terms["applies"]:
        s.step(
            "K1, K2, K3",
            f"{terms['K1']:.3f}, {terms['K2']:.3f}, {terms['K3']:.3f}",
            "",
            "speed-up multipliers",
            code_context.table("wind").topography.source,
        )
    elif terms is not None:
        s.note(f"Topography: {terms['reason']}, so Kzt = 1.")
    s.step(
        "Kzt",
        L.topographic_factor(z, s["exposure"]),
        "",
        "(1 + K1 K2 K3)²" if terms and terms["applies"] else "topographic factor",
        _code("wsTopographic"),
    )
    s.step("Kd", L.wind_factor("directionality"), "", "directionality", _code("wsDirectionality"))
    q = s.step(
        "qz" if where != "h" else "qh",
        L.velocity_pressure(z, s["speed"], s["exposure"], i_w),
        "kN/m²",
        _pressure_formula(),
        _code("wsVelocityPressure"),
    )
    return float(q), float(kz)


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
            help="The basic wind speed of the site's location in the code pack's table.",
        ),
        choice("exposure", "Exposure", "B", [("A", "A"), ("B", "B"), ("C", "C")], group="Site"),
        choice("category", "Occupancy category", "II", _categories(), group="Site"),
        number("height", "Height to the top h", 8, "m", minimum=1, group="Sign"),
        number("depth", "Sign depth s (vertical)", 3, "m", minimum=0.1, group="Sign"),
        number("width", "Sign width B (horizontal)", 6, "m", minimum=0.1, group="Sign"),
        number(
            "solidity",
            "Solidity ratio ε (solid / gross area)",
            1.0,
            minimum=0.05,
            maximum=1,
            group="Sign",
            help="1 for a solid wall or sign. Openings reduce Cf; a sign 30 % or more open is "
            "an open sign.",
        ),
        number(
            "corner",
            "Return corner Lr",
            0,
            "m",
            minimum=0,
            group="Sign",
            help="Length of a return corner at the end of a long wall (0: none).",
        ),
        *_topography_inputs(),
    ],
    references=(_code("wsSigns"),),
)
def _wind_sign(s: Sheet) -> None:
    h, sd, b = s["height"], s["depth"], s["width"]
    if sd > h:
        raise WorksheetInputError("the sign is deeper than its height to the top")
    wind = code_context.table("wind")
    if getattr(wind, "solidSigns", None) is None:
        raise WorksheetInputError("the code pack in force has no force coefficients of signs")
    with L.wind_overrides(_topography_settings(s)):
        qh, kz = _velocity_steps(s, h, "h")
        g = s.step("G", L.wind_factor("gust"), "", "gust-effect factor (rigid)", _code("gustRigid"))
    s.step("s/h, B/s", f"{sd / h:.2f}, {b / sd:.2f}", "", "clearance and aspect ratios")
    corner = s["corner"] / sd if s["corner"] > 0 else None
    result = OW.solid_sign_wind(
        qh, g, b, sd, h, s["solidity"], corner, getattr(wind, "openStructures", None)
    )
    source = wind.solidSigns.source
    cf = s.step("Cf (cases A, B)", result["Cf"], "", "by s/h and B/s", source)
    area = s.step("As", result["As_m2"], "m²", "B s" if result["kind"] == "solid" else "ε B s")
    force = s.step("F", qh * g * cf * area, "kN", "qh G Cf As", source)
    a = result["cases"]["A"]
    s.step("Height of F", a["z_m"], "m", "the sign's centre (+0.05 s when s/h = 1)")
    s.step("Moment at the ground", force * a["z_m"], "kN·m", "F × height")
    if "B" in result["cases"]:
        s.step(
            "Case B offset",
            result["cases"]["B"]["offset_m"],
            "m",
            "0.2 B from the centre toward the windward edge",
            source,
        )
        s.step("Case B torsion", force * result["cases"]["B"]["offset_m"], "kN·m", "F × offset")
    if result["caseC"]:
        s.heading("Case C (B/s ≥ 2): each region's force at its centre")
        for r in result["caseC"]:
            s.step(
                f"Cf, {r['from_s']:g}s to {r['to_s']:g}s",
                r["Cf"],
                "",
                f"F = {r['F_kN']:.2f} kN at {r['x_m']:.2f} m from the windward edge",
                source,
            )
        s.step("Case C total", sum(r["F_kN"] for r in result["caseC"]), "kN", "Σ F")
    for n in result["notes"]:
        s.note(n)
    s.note(f"Kz = {kz:.3f}.")


# ─────────────────────────────── wind on chimneys, tanks, rooftop units ───────────────────────────


@worksheet(
    "wind-chimney",
    "Wind on a chimney, tank or rooftop unit",
    group="Loads",
    summary="Force coefficient by cross-section and h/D and the design wind force F = qz G Cf "
    "Af on a chimney, tank, rooftop equipment or similar structure, with the increase for "
    "rooftop equipment on low buildings.",
    inputs=[
        number("speed", "Basic wind speed V", 65.7, "m/s", minimum=20, maximum=100, group="Site"),
        choice("exposure", "Exposure", "B", [("A", "A"), ("B", "B"), ("C", "C")], group="Site"),
        choice("category", "Occupancy category", "II", _categories(), group="Site"),
        choice(
            "section",
            "Cross-section",
            "round",
            [
                ("square", "Square, wind normal to a face"),
                ("squareDiagonal", "Square, wind along the diagonal"),
                ("polygonal", "Hexagonal or octagonal"),
                ("round", "Round"),
            ],
            group="Structure",
        ),
        choice(
            "surface",
            "Surface (round)",
            "moderatelySmooth",
            [
                ("moderatelySmooth", "Moderately smooth"),
                ("rough", "Rough"),
                ("veryRough", "Very rough"),
            ],
            group="Structure",
        ),
        number("diameter", "D (diameter or least width)", 3, "m", minimum=0.05, group="Structure"),
        number("tall", "Height of the structure", 12, "m", minimum=0.1, group="Structure"),
        number(
            "base",
            "Base above the ground",
            0,
            "m",
            minimum=0,
            group="Structure",
            help="0 on the ground; the roof height for rooftop equipment.",
        ),
        number(
            "buildingHeight",
            "Building mean roof height h",
            0,
            "m",
            minimum=0,
            group="Rooftop",
            help="0: not on a roof.",
        ),
        number(
            "buildingWidth",
            "Building width B across the wind",
            20,
            "m",
            minimum=0.1,
            group="Rooftop",
        ),
        *_topography_inputs(),
    ],
    references=(_code("wsChimneys"),),
)
def _wind_chimney(s: Sheet) -> None:
    wind = code_context.table("wind")
    table = getattr(wind, "chimneys", None)
    if table is None:
        raise WorksheetInputError("the code pack in force has no force coefficients of chimneys")
    d, tall, base = s["diameter"], s["tall"], s["base"]
    z = base + tall / 2
    with L.wind_overrides(_topography_settings(s)):
        qz, _ = _velocity_steps(s, z, "z (centroid of Af)")
        g = s.step("G", L.wind_factor("gust"), "", "gust-effect factor (rigid)", _code("gustRigid"))
    ratio = s.step("h/D", tall / d, "", "height over D")
    root = s.step("D√qz", d * math.sqrt(qz * 1e3), "", "D in m, qz in N/m²")
    cf = s.step(
        "Cf",
        OW.chimney_cf(table, s["section"], s["surface"], ratio, root),
        "",
        f"{s['section']}, by h/D",
        table.source,
    )
    area = s.step("Af", d * tall, "m²", "D × height (projected)")
    factor = 1.0
    roof = s["buildingHeight"]
    if roof > 0:
        factor = s.step(
            "Rooftop factor",
            L.rooftop_factor(area, s["buildingWidth"], roof),
            "",
            "1.9 for Af ≤ 0.1 B h, to 1.0 at B h (h ≤ 18.3 m)",
            getattr(getattr(wind, "rooftop", None), "source", ""),
        )
    force = s.step("F", qz * g * cf * area * factor, "kN", "qz G Cf Af × factor", table.source)
    s.step("Moment at the base", force * tall / 2, "kN·m", "F × height / 2")
    for row in table.rows:
        if row.note and row.section == s["section"] and row.surface == s["surface"]:
            s.note(row.note)


# ─────────────────────────────────────── seismic base shear ───────────────────────────────


def _acceleration_formula() -> str:
    """How Sa is found by the design spectrum method of the pack in force (C11: the formula
    text follows the method, not the default pack's)."""
    rule = getattr(code_context.table("seismic"), "designSpectrum", None)
    if rule is not None and rule.method == "behaviourFactor":
        return "Sd(T) of ag = Z I with the behaviour factor q = R"
    if rule is not None and rule.method == "influenceCoefficient":  # Alpha 9 C20
        return "α(T) = (α(T)/αmax) Z I / R, Z = αmax (η2, γ, η1 by the damping)"
    factor = rule.factor if rule is not None and rule.factor is not None else None
    if factor is None or math.isclose(factor, 2 / 3):
        return "(2/3) Z I / R Cs"
    return f"{factor:g} Z I / R Cs"


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
    references=(_code("wsSeismic"),),
)
def _seismic(s: Sheet) -> None:
    table = code_context.table("seismic")
    from saengine.fem.spectral_hazard import takes_mapped_values, uses_mapped

    if uses_mapped() and not takes_mapped_values():  # Alpha 9 C16: the ubc97 method
        s.note(
            f"{code_context.code_name()} finds the design spectrum from the seismic "
            "coefficients Ca and Cv of the zone and the soil profile: this worksheet works with "
            "the zone spectrum and does not cover it. The analysis model's derivation states "
            "Ca, Cv, V and the forces per level."
        )
        return
    if uses_mapped():  # C1: this worksheet's inputs are a zone's; not covered for mapped values
        s.note(
            f"{code_context.code_name()} takes the seismic hazard from the site's mapped "
            "spectral values (SDS, SD1): this worksheet works with seismic zones and does not "
            "cover it. The analysis model's derivation states Cs, V and the forces per level."
        )
        return
    z = s.step(
        "Z",
        code_context.table("zoneCoefficients").zones[int(s["zone"])],
        "",
        f"zone {s['zone']}",
        _code("wsZone"),
    )
    cat = code_context.table("occupancyCategories").categories[s["category"]]
    i_e = s.step("I", cat.seismicImportance, "", f"category {s['category']}", _code("wsImportance"))
    system = table.systems[s["system"]]
    r = s.step("R", system.R, "", system.name, _code("wsSystem", f" row {system.row}"))
    family = system.periodFamily or "other"
    coef = table.periodCoefficients[family]
    ta = s.step(
        "Ta",
        L.approximate_period(s["hn"], s["system"]),
        "s",
        f"Ct hn^m (Ct = {coef.Ct:g}, m = {coef.m:g})",
        _code("wsPeriod"),
    )
    t = ta
    upper = getattr(table, "periodUpperFactor", None)
    if s["period_given"]:
        # The pack's cap on a period from analysis; none: the period is not capped.
        cap = float(upper) * ta if upper else math.inf
        bound = f"Ta ≤ T ≤ {float(upper):g} Ta" if upper else "Ta ≤ T"
        t = s.step("T", min(max(s["period"], ta), cap), "s", bound, _code("periodCap"))
    site = table.siteClasses[s["site"]]
    s.step(
        "S, TB, TC, TD",
        f"{site.S:g}, {site.TB:g}, {site.TC:g}, {site.TD:g}",
        "",
        f"site class {s['site']}",
        _code("wsSiteFactors"),
    )
    s.step(
        "Cs",
        L.normalized_spectrum(t, s["site"]),
        "",
        "normalized spectrum at T",
        _code("wsSpectrum"),
    )
    sa = s.step(
        "Sa",
        L.design_acceleration(t, s["site"], z, i_e, r),
        "g",
        _acceleration_formula(),
        _code("wsSpectrum"),
        digits=4,
    )
    v = s.step("V", sa * s["weight"], "kN", "Sa W", _code("wsBaseShear"))
    n = int(s["storeys"])
    if n:
        s.heading("Vertical distribution")
        storey = s["hn"] / n
        levels = [((i + 1) * storey, s["weight"] / n) for i in range(n)]
        forces = L.vertical_distribution(levels, v, t, s["site"])  # C20b: TC of the site
        k = 1.0 if t <= 0.5 else 2.0 if t >= 2.5 else 1 + (t - 0.5) / 2
        s.step("k", k, "", "1 for T ≤ 0.5 s, 2 for T ≥ 2.5 s", _code("wsBaseShear"))
        for (height, _), force in reversed(list(zip(levels, forces, strict=True))):
            s.step(
                f"F at {height:.1f} m", force, "kN", "V wx hx^k / Σ wi hi^k", _code("wsBaseShear")
            )
    s.note(
        f"T = {t:.3f} s. The design of the model also adds the accidental torsion and checks "
        f"the drifts{_code('wsTorsionDrift').paren()}."
    )
    if math.isclose(t, ta):
        raise_to = f" up to {float(upper):g} Ta" if upper else ""
        s.note(f"Approximate period: a period from analysis may raise T{raise_to}.")

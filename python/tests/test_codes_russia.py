"""The Russian pack (``russia-sp``, alpha 9 track C25): SP 20 loads (γf, the basic and special
combinations, ψA1 / ψn1, the snow and wind regions, k(ze) with ze by the proportions and the
pulsation ζ ν), SP 14 seismic (A, β(T) by the soil category with the one-point shift, K0, K1,
the OSR-2015 maps by the responsibility, ηk of the linear mode), SP 63 concrete (Rb, Rbt, Eb,
Rs, ξR, the nonlinear deformation model's diagrams, the inclined section), SP 16 steel (φ by
the curves a, b, c), SP 22 (the design resistance R), values pinned to their clauses, the
default packs unchanged, and a small generated building derived and designed.

The values are those of the pack's ``VERIFY.md``; a test failing here after a value is changed
there says the pack and its verification list disagree.
"""

from __future__ import annotations

import math

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

RU = "russia-sp"


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    """No pack of the machine's user folder takes part."""
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def ru():
    loaded = registry.load(RU)
    with code_context.using(loaded):
        yield loaded


def _beam(fc=18.5, fy=500.0, b=300.0, h=500.0, bottom=3, top=2, dia=16.0, cover=35.0):
    from saengine.design.rc import Bar, RcSection, bar_area
    from saengine.library.objects import RectangleProfile

    y = h / 2 - cover - dia / 2
    xs = lambda n: [
        (-b / 2 + cover + dia / 2) + k * (b - 2 * cover - dia) / (n - 1) for k in range(n)
    ]
    bars = [Bar(x, -y, bar_area(dia), dia) for x in xs(bottom)] + [
        Bar(x, y, bar_area(dia), dia) for x in xs(top)
    ]
    return RcSection(RectangleProfile(xDim=b, yDim=h), tuple(bars), fc, fy)


# ───────────────────────────── the pack ─────────────────────────────


def test_pack_is_built_in_and_valid():
    assert RU in [p.id for p in registry.list_packs()]
    found = registry.validate(registry.BUILTIN_DIR / RU)
    assert not [p for p in found.problems if p.severity == "error"], found.problems


# ───────────────────────────── SP 20 loads ─────────────────────────────


def test_basic_and_special_combinations(ru):
    combos = {c.name: dict(c.factors) for c in ru.table("combinations").strength}
    first = combos["1.1D + 1.3L + 0.9·1.4S"]  # SP 20 6.3: ψt1 1.0, ψt2 0.9
    assert (first["D"], first["L"], first["Lr"]) == pytest.approx((1.1, 1.3, 1.26))
    wind = combos["1.1D + 1.4W + 0.9·1.3L + 0.7·1.4S"]  # wind leading, ψt3 0.7
    assert (wind["W"], wind["L"], wind["Lr"]) == pytest.approx((1.4, 1.17, 0.98))
    assert combos["0.9D + 1.4W"] == pytest.approx({"D": 0.9, "W": 1.4})  # SP 20 7.2
    quake = combos["0.9·1.1D + 0.5(1.3L + 1.4S) + 1.0E"]  # SP 14 Table 2: 0.9 / 0.5
    assert (quake["D"], quake["L"], quake["Lr"], quake["E"]) == pytest.approx(
        (0.99, 0.65, 0.7, 1.0)
    )
    assert "W" not in quake  # SP 14 5.1: no wind with the earthquake
    service = {c.name: dict(c.factors) for c in ru.table("combinations").service}
    assert service["D + L + S"] == pytest.approx({"D": 1.0, "L": 1.0, "Lr": 1.0})  # γf 1


def test_live_loads_and_the_area_reduction(ru):
    from saengine.design import live_reduction as lr

    uses = ru.table("areaLoads").uses
    assert (uses["residential"].live, uses["office"].live) == (1.5, 2.0)  # Table 8.3
    assert (uses["roof"].live, uses["stairs"].live) == (0.5, 4.0)
    scope = lr.LiveScope(live=1.5)
    # SP 20 8.2.4: ψA1 = 0.4 + 0.6/√(A/9) at A = 36 m²: 0.7.
    factor, _ = lr.reduction(1.0, 36.0, 1, scope)
    assert factor == pytest.approx(0.7)
    # 8.2.5: ψn1 = 0.4 + (ψA1 - 0.4)/√n, n = 4 floors of 36 m² (AT 144 m²).
    factor, _ = lr.reduction(1.0, 144.0, 4, scope)
    assert factor == pytest.approx(0.4 + (0.7 - 0.4) / 2)
    assert lr.reduction(1.0, 8.0, 1, scope)[0] == 1.0  # A <= A1: none


def test_snow_and_wind_regions_of_the_cities(ru):
    towns = ru.table("locations").locations
    moscow = towns["moscow"]
    assert moscow.groundSnow == 1.5  # snow region III (Table 10.1)
    assert moscow.windSpeed == pytest.approx(math.sqrt(230 / 0.613), abs=0.01)  # wind region I
    kamchatka = towns["petropavlovskKamchatsky"]
    assert kamchatka.windSpeed == pytest.approx(math.sqrt(850 / 0.613), abs=0.01)  # VII 0.85
    assert kamchatka.mapZones == {"A": 4, "B": 4, "C": 5}  # 9, 9, 10 points
    snow = ru.table("snow")  # B.1: μ 1 to 30°, 0 from 60°
    assert [tuple(p) for p in snow.shape] == [(0.0, 1.0), (30.0, 1.0), (60.0, 0.0)]


def test_wind_profile_reference_height_and_pulsation(ru):
    from saengine.fem import loads as fl

    w0 = 0.30  # region II
    v = math.sqrt(w0 * 1000 / 0.613)
    # k(ze) = k10 (ze/10)^2α: B at 10 m 0.65, at 40 m 0.65 × 4^0.4; C at most from 10 m.
    assert fl.velocity_pressure(10.0, v, "B", 1.0) == pytest.approx(0.65 * w0, rel=1e-6)
    assert fl.velocity_pressure(40.0, v, "B", 1.0) == pytest.approx(0.65 * 4**0.4 * w0, rel=1e-6)
    assert fl.velocity_pressure(3.0, v, "C", 1.0) == pytest.approx(0.4 * w0, rel=1e-6)
    # Table 11.6: ν at ρ = 20 m, χ = 40 m: 0.73; between the rows bilinear.
    assert fl.pulsation_correlation(20.0, 40.0) == pytest.approx(0.73)
    assert fl.pulsation_correlation(30.0, 40.0) == pytest.approx((0.73 + 0.67) / 2)
    # 11.1.8: G = 1 + ζ(ze) ν, ζ10 of B 1.06, ζ(40) = 1.06 × 4^-0.2.
    assert fl.pulsation_factor(10.0, "B", 0.73) == pytest.approx(1 + 1.06 * 0.73)
    assert fl.pulsation_factor(40.0, "B", 0.73) == pytest.approx(1 + 1.06 * 4**-0.2 * 0.73)
    # 11.1.5: a squat building (h <= b) takes ze = h on its whole windward face.
    levels = fl.wind_levels([3.0, 6.0], [(0.0, 20.0)] * 2, [10.0, 10.0], v, "B", 1.0)
    nu = fl.pulsation_correlation(20.0, 6.0)
    qh = fl.velocity_pressure(6.0, v, "B", 1.0)
    g = fl.pulsation_factor(6.0, "B", nu)
    expected_top = (qh * g * 0.8 + qh * g * 0.5) * 20.0 * 1.5
    assert levels[1].force == pytest.approx(expected_top, rel=1e-6)


def test_default_pack_wind_is_unchanged():
    from saengine.fem import loads as fl

    with code_context.using(registry.load("bnbc2020")):
        wind = code_context.table("wind")
        assert wind.pulsation is None and wind.referenceHeight == "level"
        base = fl.wind_levels([3.0, 6.0], [(0.0, 20.0)] * 2, [10.0, 10.0], 40.0, "B", 1.0)
        qz = fl.velocity_pressure(3.0, 40.0, "B", 1.0)
        g = fl.gust_factor(6.0, "B")
        assert base[0].force > 0 and qz > 0 and g == pytest.approx(0.85)


# ───────────────────────────── SP 14 seismic ─────────────────────────────


def test_dynamic_factor_by_soil_category(ru):
    from saengine.fem import loads as fl

    # SP 14 5.6: β = 1 + 15 T to 0.1 s, 2.5 to 0.4 s (I-II) / 0.8 s (III-IV), 2.5 (Tc/T)^0.5,
    # at least 0.8.
    assert fl.normalized_spectrum(0.05, "II") == pytest.approx(1.75)
    assert fl.normalized_spectrum(0.3, "II") == pytest.approx(2.5)
    assert fl.normalized_spectrum(1.6, "II") == pytest.approx(2.5 * (0.4 / 1.6) ** 0.5)
    assert fl.normalized_spectrum(6.0, "II") == pytest.approx(0.8)
    assert fl.normalized_spectrum(0.6, "III") == pytest.approx(2.5)
    assert fl.normalized_spectrum(1.6, "III") == pytest.approx(2.5 * (0.8 / 1.6) ** 0.5)
    assert fl.normalized_spectrum(0.3, "I") == pytest.approx(2.5)
    # Table 1: category I one point less (S 0.5), III one more (S 2) on the design spectrum
    # (the soil factors of alpha 9 C24).
    ii = fl.design_acceleration(0.3, "II", 0.2, 1.0, 1 / 0.35)
    assert fl.design_acceleration(0.3, "I", 0.2, 1.0, 1 / 0.35) == pytest.approx(0.5 * ii)
    assert fl.design_acceleration(0.3, "III", 0.2, 1.0, 1 / 0.35) == pytest.approx(2 * ii)


def test_design_load_k0_k1_and_a(ru):
    from saengine.fem import loads as fl

    systems = ru.table("seismic").systems
    assert systems["rcFrame"].R == pytest.approx(1 / 0.35, rel=1e-5)  # Table 5: K1 0.35
    assert systems["rcWall"].R == pytest.approx(4.0)  # K1 0.25
    assert systems["steelBraced"].R == pytest.approx(1 / 0.22, rel=1e-5)
    zones = ru.table("zoneCoefficients").zones  # 5.5: A 0.1, 0.2, 0.4 g
    assert (zones[2], zones[3], zones[4]) == (0.1, 0.2, 0.4)
    # Sik/Qk = K0 K1 A β Kψ: 8 points, soil II, plateau, K0 1.0, RC frame: 0.2 × 2.5 × 0.35.
    sa = fl.design_acceleration(0.3, "II", 0.2, 1.0, 1 / 0.35)
    assert sa == pytest.approx(0.2 * 2.5 * 0.35, rel=1e-5)
    k0 = ru.table("occupancyCategories").categories["III"].seismicImportance  # Table 3
    assert fl.design_acceleration(0.3, "II", 0.2, k0, 1 / 0.35) == pytest.approx(1.2 * sa)


def test_linear_mode_share_and_default_correction(ru):
    from saengine.fem import loads as fl

    levels = [(3.0, 100.0), (6.0, 100.0), (9.0, 100.0)]
    # SP 14 5.5 ηk with X linear: (Σ W h)² / (Σ W Σ W h²) = 18² / (3 × 126).
    share = fl.linear_mode_share(levels)
    assert share == pytest.approx(18.0**2 / (3 * 126.0))
    assert fl.base_shear_correction(0.5, 3, "II", levels=levels) == pytest.approx(share)
    assert fl.linear_mode_share([(3.0, 50.0)]) == pytest.approx(1.0)
    with code_context.using(registry.load("eurocodes")):  # λ 0.85 unchanged
        assert fl.base_shear_correction(0.3, 4, "B") == pytest.approx(0.85)
    with code_context.using(registry.load("bnbc2020")):
        assert fl.base_shear_correction(0.3, 4, "SC", levels=levels) == 1.0


def test_hazard_map_by_responsibility():
    from saengine.library.settings import default_project_settings, derived

    settings = default_project_settings("Project", code_pack=RU)
    assert settings.codePack == RU and settings.site.location == "moscow"
    settings.site.location = "irkutsk"  # OSR-2015 A 8, B 9, C 9
    with code_context.using(code_context.pack_for(settings)):
        values = derived(settings)
    assert values["hazardMap"] == "A" and float(values["Z"]) == pytest.approx(0.2)
    settings.occupancy.category = "III"  # increased responsibility: map B (4.3)
    with code_context.using(code_context.pack_for(settings)):
        values = derived(settings)
    assert values["hazardMap"] == "B" and float(values["Z"]) == pytest.approx(0.4)
    assert values["zone"] == 4


def test_default_pack_has_no_hazard_maps():
    from saengine.library.settings import default_project_settings, derived

    settings = default_project_settings("Project")
    with code_context.using(code_context.pack_for(settings)):
        values = derived(settings)
        assert code_context.table("seismic").hazardMaps is None
    assert "hazardMap" not in values


def test_height_limits_by_intensity(ru):
    systems = ru.table("seismic").systems
    frame = systems["rcFrame"].heightLimits  # Table 8 (U): 7 / 8 / 9 points
    assert (frame["B"], frame["C"], frame["D"]) == (30.0, 23.0, 17.0)
    assert frame["A"] is None
    table = ru.table("seismic").designCategories
    assert table.bySiteClass["II"]["all"][2:5] == ["B", "C", "D"]  # 7, 8, 9 points
    assert table.bySiteClass["III"]["all"][1:4] == ["B", "C", "D"]  # one point more


# ───────────────────────────── SP 63 concrete ─────────────────────────────


def test_sp63_design_strengths_and_block(ru):
    from saengine.design import design_strength as ds

    assert ds.partial_factors()
    # Table 6.8 with γb1 0.9: B25 Rb 14.5, Rbt 1.05; Table 6.11 Eb 30 GPa.
    assert ds.fcd(18.5) == pytest.approx(0.9 * 14.5)
    assert ds.fctd(18.5) == pytest.approx(0.9 * 1.05)
    assert ds.properties(18.5).ecm == pytest.approx(30000.0)
    assert ds.fcd(43.0) == pytest.approx(0.9 * 33.0)  # B60
    assert ds.strength_class(18.5) == "B25"
    # Table 6.14: Rs A400 350, A500C 435.
    assert (ds.fyd(400.0), ds.fyd(500.0)) == pytest.approx((350.0, 435.0))
    p = ds.properties(22.0)
    assert (p.eta, p.lam, p.eps_cu3, p.eps_c2) == pytest.approx((1.0, 0.8, 0.0035, 0.002))
    # 8.1.6: ξR = 0.8 / (1 + Rs/(Es εb2)), A500: 0.493.
    xi = p.lam / (1 + 435.0 / (200000.0 * p.eps_cu3))
    assert xi == pytest.approx(0.493, abs=0.001)
    # The fit of Rbtn (Table 6.7) within 0.02 MPa.
    assert p.fctk005 == pytest.approx(1.75, abs=0.02)


def test_nonlinear_deformation_model_diagrams():
    from saengine.design import design_strength as ds

    pack = registry.load(RU)
    with code_context.using(
        pack.with_overrides({"concreteMethods.ultimate.stressBlock": "bilinear"})
    ):
        profile = ds.concrete_profile(18.5)
        f = 0.9 * 14.5
        assert profile.strains[-2:] == pytest.approx([0.0015, 0.0035])  # εb1,red, εb2
        assert profile.stresses[-1] == pytest.approx(f)
        assert ds.ultimate_strain(18.5) == pytest.approx(0.0035)
    with code_context.using(
        pack.with_overrides({"concreteMethods.ultimate.stressBlock": "trilinear"})
    ):
        profile = ds.concrete_profile(18.5)
        f = 0.9 * 14.5
        # 6.1.22: 0.6 Rb at 0.6 Rb / Eb, Rb from εb0 0.002 to εb2 0.0035.
        assert profile.strains[2:] == pytest.approx([0.6 * f / 30000.0, 0.002, 0.0035])
        assert profile.stresses[2:] == pytest.approx([0.6 * f, f, f])
        assert profile.get_compressive_strength() == pytest.approx(f)
        assert "nonlinear deformation model" in ds.block_text()


def test_inclined_section_shear(ru):
    from saengine.design import tabulated_shear as ts

    rule = ts.rules().inclinedSection
    fctd = 0.9 * 1.05  # B25 with γb1
    b, d = 300.0, 450.0
    # 8.1.33 without links: Qb at c = 3 h0, 0.5 Rbt b h0.
    found = ts.inclined_resistance(b, d, fctd, 0.0, rule)
    assert found.total == pytest.approx(0.5 * fctd * b * d)
    assert found.c == pytest.approx(3 * d)
    # With qsw = 100 N/mm (>= 0.25 Rbt b): the least at c = 3 h0, Qb 0.5 Rbt b h0 + Qsw 0.75
    # qsw 2 h0.
    found = ts.inclined_resistance(b, d, fctd, 100.0, rule)
    assert found.total == pytest.approx(0.5 * fctd * b * d + 0.75 * 100.0 * 2 * d)
    assert not found.reduced
    # Links below 0.25 Rbt b: Rbt b = 4 qsw.
    assert ts.inclined_resistance(b, d, fctd, 40.0, rule).reduced
    # Rsw = 0.8 Rs <= 300 (Table 6.15): A400 280, A500 300.
    assert ts.stirrup_yield(400.0) == pytest.approx(280.0)
    assert ts.stirrup_yield(500.0) == pytest.approx(300.0)
    # Design Reinforcement inverts it.
    need = ts.required_stirrups(found.total, b, d, 18.5, 400.0, 1.0)
    assert need * 280.0 == pytest.approx(100.0, rel=1e-3)
    s = ts.beam_shear(_beam(), 8.0, 2, 150.0)
    assert s.phi_vn <= 0.3 * 0.9 * 14.5 * 300.0 * s.d + 1e-6  # 8.1.32 strut
    assert any("inclined section" in n for n in s.notes)


def test_other_tabulated_packs_keep_their_shear():
    from saengine.design import tabulated_shear as ts

    with code_context.using(registry.load("china-gb")):
        r = ts.rules()
        assert r.inclinedSection is None and r.stirrupYieldShare is None
        assert ts.tau_c(20.1, 0.5) == pytest.approx(0.7 * 1.43)
    with code_context.using(registry.load("eurocodes")):
        from saengine.design import design_strength as ds

        assert ds.rules().designStrengths is None
        assert ds.fcd(30.0) == pytest.approx(ds.rules().alphaCC * 30.0 / ds.rules().gammaC)


# ───────────────────────────── SP 16 steel ─────────────────────────────


def test_sp16_stability_coefficient(ru):
    from saengine.design.steel import limit_state as ls

    curves = ru.table("steelLimitState").compression.perry
    # 7.1.3: φ = 0.5 (δ - √(δ² - 39.48 λ̄²)) / λ̄², δ = 9.87 (1 - α + β λ̄) + λ̄²; on λn = λ̄/π.
    for curve, (alpha, beta) in {"a": (0.03, 0.06), "b": (0.04, 0.09), "c": (0.04, 0.14)}.items():
        for lam_bar in (1.0, 2.0, 3.0):
            delta = math.pi**2 * (1 - alpha + beta * lam_bar) + lam_bar**2
            phi = 0.5 * (delta - math.sqrt(delta**2 - 4 * math.pi**2 * lam_bar**2)) / lam_bar**2
            assert ls.perry_phi(lam_bar / math.pi, curves[curve]) == pytest.approx(phi, rel=1e-4)
    assert ls.perry_phi(0.1, curves["b"]) == pytest.approx(1.0, abs=1e-5)  # λ̄ <= 0.4
    strengths = ru.table("steelLimitState").designStrength  # Table B.5: C345 by thickness
    assert [tuple(r) for r in strengths["345"]][:2] == [(10, 345), (20, 325)]
    assert ru.table("steelLimitState").partialFactors.gammaM0 == pytest.approx(1.025)


# ───────────────────────────── SP 22 foundations ─────────────────────────────


def test_sp22_design_resistance(ru):
    from saengine.soil import bearing

    rule = bearing._design_resistance_rules()
    assert rule is not None
    # Table 5.5 at 30°: Mγ 1.15, Mq 5.59, Mc 7.95.
    assert bearing.resistance_factors(30.0, rule) == pytest.approx((1.15, 5.59, 7.95))
    assert bearing.resistance_factors(0.0, rule) == pytest.approx((0.0, 1.0, 3.14))
    # 5.6.7: R = γc1 γc2 / k (Mγ kz b γ + Mq d γ' + Mc c), sand γc1 1.25, k 1.1, b 2 m, d 2 m.
    found = bearing.design_resistance(rule, 0.0, 30.0, 36.0, 18.0, 2.0, "granular")
    expected = 1.25 * 1.0 / 1.1 * (1.15 * 1.0 * 2.0 * 18.0 + 5.59 * 36.0)
    assert found["R"] == pytest.approx(expected)
    wide = bearing.design_resistance(rule, 0.0, 30.0, 36.0, 18.0, 16.0, "granular")
    assert wide["kz"] == pytest.approx(8.0 / 16.0 + 0.2)  # b >= 10 m
    with code_context.using(registry.load("bnbc2020")):
        assert bearing._design_resistance_rules() is None


# ──────────────────────── settings and generated buildings ────────────────────────


def test_settings_derive_the_citys_values():
    from saengine.library.settings import check, default_project_settings, derived

    settings = default_project_settings("Project", code_pack=RU)
    assert (settings.site.location, settings.site.siteClass) == ("moscow", "II")
    assert settings.wind.exposure == "B"
    assert not [p for p in check(settings) if p.startswith("codePack")]
    with code_context.using(code_context.pack_for(settings)):
        values = derived(settings)
    assert float(values["Z"] or 0.0) == 0.0  # Moscow: 5 points on map A
    assert values["windSpeed"] == pytest.approx(math.sqrt(230 / 0.613), abs=0.01)


def test_generated_building_derives_wind_and_earthquake():
    from saengine.fem.derive import derive_fem
    from saengine.library import FloorPlan, MaterialLibrary, ObjectLibrary
    from saengine.library.bim import generate
    from saengine.library.generator import generate_building
    from saengine.library.settings import ProjectSettings

    spec = {
        "name": "Frame",
        "gridsX": [6000, 6000],
        "gridsY": [5000, 5000],
        "storyCount": 3,
        "groundHeight": 3600,
        "typicalHeight": 3300,
        "codePack": RU,
    }
    result = generate_building(spec)
    settings = ProjectSettings.model_validate(result["settings"])
    assert settings.codePack == RU
    settings.site.location = "irkutsk"  # 8 points on map A: A = 0.2 g
    building = generate(FloorPlan.model_validate(result["floorPlan"]), "s")
    with code_context.using(code_context.pack_for(settings)):
        d = derive_fem(
            building,
            ObjectLibrary.model_validate(result["objects"]),
            MaterialLibrary.model_validate(result["materials"]),
            settings,
            {"bim": "abc"},
        )
    assert not d.summary.get("lateralMissing"), d.summary.get("lateralMissing")
    seismic = d.summary["seismic"]["EX"]
    # V/W = K0 K1 A β × the linear mode's share (< 1 for three storeys).
    assert 0 < seismic["Sa_g"] <= 0.2 * 2.5 + 1e-9
    assert 0.75 < seismic["correction"] < 1.0
    wx = sum(
        n["forces"][0]
        for p in d.project["load_patterns"]
        if p["name"] == "WX"
        for n in p["nodal_loads"]
    )
    assert wx > 0


def test_generated_building_is_designed_under_the_pack(tmp_path):
    import json
    from pathlib import Path

    from saengine.pipeline.run_all import run_all
    from saengine.project.new_building import create_building

    spec = {
        "name": "Concrete",
        "gridsX": [5000],
        "gridsY": [4000],
        "storyCount": 1,
        "typicalHeight": 3000,
        "system": "rcFrame",
        "codePack": RU,
        "lateralSizing": "gravity",
    }
    root = Path(create_building(spec, tmp_path)["root"])
    result = run_all(root, steps=["derive", "analysis"])
    assert [s.status for s in result.steps] == ["ok", "ok"], [s.message for s in result.steps]
    from saengine.rpc import handlers

    with code_context.project(root):
        proposal = handlers.design_proposal(
            str(root / "08 FEM/model.results"), str(root / "08 FEM/model.osmodel")
        )
    objects_path, bim_path = root / "04 Objects/objects.json", root / "06 BIM/bim.json"
    applied = handlers.design_apply_proposal(
        objects_path.read_text(encoding="utf-8"), bim_path.read_text(encoding="utf-8"), proposal
    )
    objects_path.write_text(applied["objectsText"], encoding="utf-8")
    bim_path.write_text(applied["bimText"], encoding="utf-8")
    result = run_all(root, steps=["derive", "analysis", "design"])
    assert result.steps[-1].status in ("ok", "warning"), [s.message for s in result.steps]
    report = json.loads(
        (root / "08 FEM/model.results/design-report.json").read_text(encoding="utf-8")
    )["result"]
    assert any("SP 63" in line for line in report["method"]), report["method"]
    assert any("inclined section" in line for line in report["method"]), report["method"]

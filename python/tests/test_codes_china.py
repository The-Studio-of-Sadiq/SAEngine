"""The Chinese pack (``china-gb``, alpha 9 track C20): GB 55001 / GB 50009 loads, the GB 50011
seismic influence coefficient spectrum by the generic method ``influenceCoefficient`` (η1, η2,
γ by the damping), the design earthquake group of the city, the drift limits by structure type,
the two-level design (the rare earthquake's elasto-plastic drift, the seismic grades), GB 50010
design strengths and beam shear, GB 50017 members by the Perry constants, values pinned to their
clauses, and a small generated building derived and designed.

The values are those of the pack's ``VERIFY.md``; a test failing here after a value is changed
there says the pack and its verification list disagree.
"""

from __future__ import annotations

import math

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

CN = "china-gb"


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    """No pack of the machine's user folder takes part."""
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def cn():
    loaded = registry.load(CN)
    with code_context.using(loaded):
        yield loaded


def _beam(fc=20.1, fy=400.0, b=300.0, h=500.0, bottom=3, top=2, dia=16.0, cover=35.0):
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
    assert CN in [p.id for p in registry.list_packs()]
    found = registry.validate(registry.BUILTIN_DIR / CN)
    assert not [p for p in found.problems if p.severity == "error"], found.problems


def test_combinations_live_loads_and_reduction(cn):
    combos = {c.name: dict(c.factors) for c in cn.table("combinations").strength}
    assert (combos["1.3G + 1.5Q"]["D"], combos["1.3G + 1.5Q"]["L"]) == (1.3, 1.5)  # GB 55001
    assert combos["1.3G + 1.5Q + 0.9W"]["W"] == pytest.approx(1.5 * 0.6)  # ψc wind 0.6
    assert combos["1.3G + 1.5W + 1.05Q"]["L"] == pytest.approx(1.5 * 0.7)  # ψc live 0.7
    assert combos["1.0G + 1.5W"] == {"D": 1.0, "W": 1.5}
    quake = combos["1.3(G + 0.5Q) + 1.4E"]  # GB 55002 4.3.2
    assert (quake["D"], quake["L"], quake["E"]) == (1.3, 0.65, 1.4)
    uses = cn.table("areaLoads").uses
    assert (uses["residential"].live, uses["office"].live) == (2.0, 2.5)  # GB 55001 4.2.2
    assert (uses["roof"].live, uses["storageLight"].live) == (0.5, 6.0)
    rows = cn.table("liveReduction").floorCount.rows  # GB 50009 Table 5.1.2
    assert [tuple(r) for r in rows][:3] == [(1, 0.0), (3, 0.15), (5, 0.30)]


def test_wind_pressure_height_coefficient_and_snow(cn):
    from saengine.fem import wind_speed_factors as wsf

    # GB 50009 Table 8.2.1: μz terrain B 1.00 at 10 m, 1.39 at 30 m (1.000 (z/10)^0.30).
    assert wsf.height_factor(10.0, "B") ** 2 == pytest.approx(1.0, abs=1e-3)
    assert wsf.height_factor(30.0, "B") ** 2 == pytest.approx(3**0.30, abs=2e-3)
    assert wsf.height_factor(20.0, "C") ** 2 == pytest.approx(0.544 * 2**0.44, abs=2e-3)
    # w0 = v0² / 1600: Beijing 0.45 kN/m².
    beijing = cn.table("locations").locations["beijing"]
    assert beijing.windSpeed**2 / 1600 == pytest.approx(0.45, abs=1e-3)
    f = wsf.factors(10.0, beijing.windSpeed, "B", 1.0)
    assert f["pz"] == pytest.approx(0.45, abs=2e-3)
    wind = cn.table("wind")
    assert (wind.gust, wind.cpWindward) == (1.2, 0.8)  # GB 55001 4.6.5; Table 8.3.1
    assert beijing.groundSnow == 0.40 and cn.table("snow").shape[1] == (25.0, 1.0)


# ───────────────────────────── earthquake ─────────────────────────────


def test_influence_coefficient_spectrum_at_five_percent(cn):
    from saengine.fem import loads as fl

    # Pack default group 3, class II: Tg 0.45 s (Table 5.1.4-2).
    tg = cn.table("seismic").siteClasses["II"].TC
    assert tg == 0.45
    assert fl.normalized_spectrum(0.0, "II") == pytest.approx(0.45)  # 0.45 αmax at T = 0
    assert fl.normalized_spectrum(0.05, "II") == pytest.approx(0.45 + 0.55 * 0.5)
    assert fl.normalized_spectrum(0.3, "II") == pytest.approx(1.0)  # plateau η2 = 1
    assert fl.normalized_spectrum(0.9, "II") == pytest.approx((0.45 / 0.9) ** 0.9)
    assert fl.normalized_spectrum(3.0, "II") == pytest.approx(0.2**0.9 - 0.02 * (3.0 - 2.25))
    assert fl.normalized_spectrum(8.0, "II") == pytest.approx(0.2**0.9 - 0.02 * (6.0 - 2.25))
    # Sa = αmax α/αmax with Z = αmax (8 degree 0.20g frequent 0.16), R = I = 1.
    assert fl.design_acceleration(1.0, "II", 0.16, 1.0, 1.0) == pytest.approx(
        0.16 * (0.45 / 1.0) ** 0.9
    )


def test_damping_adjustment_eta1_eta2_gamma(cn):
    from saengine.fem import loads as fl
    from saengine.fem import spectra

    rule = cn.table("seismic").designSpectrum.influence
    t = spectra.influence_terms(0.02, rule)  # GB 50011 Eqs 5.1.5-1 to -3
    assert t["gamma"] == pytest.approx(0.9 + 0.03 / (0.3 + 6 * 0.02))
    assert t["eta1"] == pytest.approx(0.02 + 0.03 / (4 + 32 * 0.02))
    assert t["eta2"] == pytest.approx(1 + 0.03 / (0.08 + 1.6 * 0.02))
    assert spectra.influence_terms(0.30, rule)["eta2"] == 0.55  # at least 0.55
    assert spectra.influence_terms(0.30, rule)["eta1"] == 0.0  # at least 0
    assert fl.normalized_spectrum(0.3, "II", damping=0.02) == pytest.approx(t["eta2"])


def test_rare_earthquake_ratio_and_minimum_shear(cn):
    from saengine.fem import loads as fl
    from saengine.fem import spectra

    rule = cn.table("seismic").designSpectrum.influence
    # 8 degree 0.20g (zone 4): rare αmax 0.90, Tg + 0.05 s.
    expected = 0.90 * (0.50 / 1.0) ** 0.9 / (0.16 * (0.45 / 1.0) ** 0.9)
    assert spectra.rare_ratio(1.0, 0.45, 4, 0.16, None, rule) == pytest.approx(expected)
    # 7 degree 0.10g (zone 2): rare αmax 0.50, no Tg increase.
    assert spectra.rare_ratio(1.0, 0.45, 2, 0.08, None, rule) == pytest.approx(0.50 / 0.08)
    assert fl.minimum_base_share(4) == 0.032 and fl.minimum_base_share(6) == 0.064  # λ
    lf = cn.table("seismic").lateralForce
    assert (lf.correction, lf.minStoreys, lf.distribution) == (0.85, 2, "linear")  # 5.2.1
    assert cn.table("zoneCoefficients").zones[4] == 0.16


def test_city_sets_the_design_earthquake_group():
    from saengine.library.settings import default_project_settings

    settings = default_project_settings("Project", code_pack=CN)
    for town, tg in (("chengdu", 0.45), ("shanghai", 0.40), ("guangzhou", 0.35)):
        chosen = settings.model_copy(
            update={"site": settings.site.model_copy(update={"location": town})}
        )
        pack = code_context.pack_for(chosen)
        assert pack.table("seismic").siteClasses["II"].TC == tg, town
    own = settings.model_copy(
        update={
            "site": settings.site.model_copy(update={"location": "chengdu"}),
            "codeOverrides": {"seismic.spectrumType": "group1"},
        }
    )
    assert code_context.pack_for(own).table("seismic").siteClasses["II"].TC == 0.35


def test_drift_limits_by_structure_type(cn):
    from saengine.fem.seismic_design import drift_limit

    assert drift_limit("II", system="rcFrame")["ratio"] == pytest.approx(1 / 550)
    assert drift_limit("II", system="rcFrameWall")["ratio"] == pytest.approx(1 / 800)
    assert drift_limit("II", system="rcWall")["ratio"] == pytest.approx(1 / 1000)
    assert drift_limit("II", system="steelFrame")["ratio"] == pytest.approx(1 / 250)


def test_seismic_grades_and_their_factors(cn):
    from saengine.fem.two_level_seismic import seismic_grade

    # Table 6.1.2: frame, 8 degree: <= 24 m grade 2, above grade 1.
    low = seismic_grade("rcFrame", 20.0, 4, "II")
    assert (low["grade"], low["level"]) == ("frame-2", "special")
    assert low["factors"]["strongColumn"] == 1.5 and low["factors"]["axialRatio"] == 0.75
    assert seismic_grade("rcFrame", 30.0, 4, "II")["grade"] == "frame-1"
    assert seismic_grade("rcFrame", 20.0, 1, "II")["grade"] == "frame-4"  # 6 degree
    # 乙 buildings (slot III) take the measures one degree higher: 7 -> 8.
    assert seismic_grade("rcFrame", 20.0, 2, "III")["grade"] == "frame-2"
    wall = seismic_grade("rcWall", 60.0, 4, "II")
    assert wall["grade"] == "dual-2" and wall["factors"]["wallShear"] == 1.4
    assert seismic_grade("steelFrame", 40.0, 1, "II")["grade"] == "steel-none"


def test_rare_earthquake_elasto_plastic_drift(cn):
    from saengine.fem import two_level_seismic as tl
    from saengine.library.settings import default_project_settings

    settings = default_project_settings("Project", code_pack=CN)
    period = 0.8
    spectra = {"X": {"modes": [{"angular_frequency": 2 * math.pi / period}]}}
    drift = [
        {"direction": "X", "bottom": 0.0, "top": 3.5, "height": 3.5, "designDrift": 0.004},
    ]
    found = tl.rare_drift(drift, spectra, settings, 4, 0.16, 3)
    rule = cn.table("seismic").designSpectrum.influence
    tg = cn.table("seismic").siteClasses[settings.site.siteClass].TC
    from saengine.fem.spectra import rare_ratio

    ratio = rare_ratio(period, tg, 4, 0.16, None, rule)
    row = found["rows"][0]
    # Table 5.5.4: uniform frames of 2-4 storeys at ξy 0.5, ηp 1.30; Table 5.5.5 1/50.
    assert found["amplification"] == pytest.approx(1.3)
    assert row["plasticDrift"] == pytest.approx(1.3 * 0.004 * ratio)
    assert row["allowableRatio"] == pytest.approx(1 / 50)
    assert row["ok"] == (row["plasticDrift"] / 3.5 <= 1 / 50)
    assert tl.rare_drift(drift, spectra, settings, 1, 0.04, 3) is None  # 6 degree: not checked


def test_default_pack_has_no_two_level_design():
    from saengine.fem import two_level_seismic as tl

    with code_context.using(registry.load("bnbc2020")):
        seismic = code_context.table("seismic")
        assert seismic.rareDrift is None and seismic.seismicGrades is None
        assert tl.summary_block(None, {}, [], {}, [], []) == {}
        method = getattr(seismic.designSpectrum, "method", "reducedElastic")
        assert method != "influenceCoefficient"


# ───────────────────────────── concrete ─────────────────────────────


def test_gb50010_design_strengths_and_block(cn):
    from saengine.design import design_strength as ds

    assert ds.partial_factors()
    assert ds.fcd(20.1) == pytest.approx(20.1 / 1.4, rel=1e-6)  # C30 fc 14.3 (4.1.4)
    assert ds.fyd(400.0) == pytest.approx(400 / 1.15)
    p50, p80 = ds.properties(32.4), ds.properties(50.2)
    assert (p50.eta, p50.lam, p50.eps_cu3) == pytest.approx((1.0, 0.8, 0.0033))  # 6.2.6
    assert (p80.eta, p80.lam, p80.eps_cu3) == pytest.approx((0.94, 0.74, 0.0030))
    # Table 4.1.4-2 by the fit: ft of C30 = ftk/1.4 about 1.43.
    assert ds.fctd(20.1) == pytest.approx(1.43, abs=0.03)


def test_gb50010_beam_shear(cn):
    from saengine.design import tabulated_shear as ts

    # 6.3.4: Vc = 0.7 ft b h0; C30 ft 1.43, independent of the steel ratio.
    assert ts.tau_c(20.1, 0.5) == pytest.approx(0.7 * 1.43)
    assert ts.tau_c(20.1, 2.0) == pytest.approx(0.7 * 1.43)
    assert ts.tau_c_max(20.1) == pytest.approx(0.25 * 14.3)  # 6.3.1, βc 1.0
    assert ts.tau_c_max(50.2) == pytest.approx(0.25 * 0.8 * 35.9)  # βc 0.8 at C80
    s = ts.beam_shear(_beam(), 8.0, 2, 150.0)
    assert s is not None


# ───────────────────────────── steel ─────────────────────────────


def test_gb50017_stability_coefficient_by_perry_constants(cn):
    from saengine.design.steel import limit_state as ls

    curves = cn.table("steelLimitState").compression.perry
    # Appendix D: class b at λn = 1.0 about 0.601 (λ/εk ≈ 93).
    s = 0.965 + 0.300 + 1.0
    expected = (s - math.sqrt(s**2 - 4)) / 2
    assert ls.perry_phi(1.0, curves["b"]) == pytest.approx(expected)
    assert expected == pytest.approx(0.601, abs=0.002)
    assert ls.perry_phi(0.2, curves["a"]) == pytest.approx(1 - 0.41 * 0.04)
    # Class c beyond λn 1.05 takes its second pair (1.216, 0.302).
    s = 1.216 + 0.302 * 1.5 + 2.25
    assert ls.perry_phi(1.5, curves["c"]) == pytest.approx((s - math.sqrt(s**2 - 9)) / 4.5)
    # The other packs' curves keep χ (no Perry constants).
    with code_context.using(registry.load("australia-as")):
        assert not code_context.table("steelLimitState").compression.perry


# ──────────────────────── settings and generated buildings ────────────────────────


def test_settings_derive_the_citys_values():
    from saengine.library.settings import check, default_project_settings, derived

    settings = default_project_settings("Project", code_pack=CN)
    assert settings.codePack == CN
    assert (settings.site.location, settings.site.siteClass) == ("beijing", "II")
    assert settings.wind.exposure == "B"
    assert not [p for p in check(settings) if p.startswith("codePack")]
    with code_context.using(code_context.pack_for(settings)):
        values = derived(settings)
        assert code_context.table("seismic").siteClasses["II"].TC == 0.40  # Beijing group 2
    assert float(values["Z"]) == pytest.approx(0.16)
    assert values["windSpeed"] == pytest.approx(math.sqrt(1600 * 0.45), abs=0.01)


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
        "codePack": CN,
    }
    result = generate_building(spec)
    settings = ProjectSettings.model_validate(result["settings"])
    assert settings.codePack == CN
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
    # V/W = 0.85 α1 (Geq), at least 0.85 λ (λ 0.032 at 8 degree 0.20g).
    assert seismic["Sa_g"] >= 0.032 and seismic["base_shear_kN"] > 0
    assert seismic["correction"] == 0.85
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
        "codePack": CN,
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
    assert any("GB 50010" in line for line in report["method"]), report["method"]
    names = {c["name"] for e in report["elements"] for c in e.get("checks", [])}
    assert names, "no checks in the design report"

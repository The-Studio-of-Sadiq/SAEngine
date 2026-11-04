"""The Indian Standards loads pack (``is-codes``, alpha 9 track C7): its values pinned to their
clauses, the generic methods it picks (design wind speed factors, the IS spectrum form, the
floor-count live load reduction, the drift of the design forces) and a small generated building
derived and analysed under it.

The values are those of the pack's ``VERIFY.md``; a test failing here after a value is changed
there says the pack and its verification list disagree.
"""

from __future__ import annotations

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

PACK = "is-codes"


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    """No pack of the machine's user folder takes part."""
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def pack():
    loaded = registry.load(PACK)
    with code_context.using(loaded):
        yield loaded


# ───────────────────────────── the pack ─────────────────────────────


def test_pack_is_built_in_and_valid():
    assert PACK in [p.id for p in registry.list_packs()]
    found = registry.validate(registry.BUILTIN_DIR / PACK)
    assert not [p for p in found.problems if p.severity == "error"], found.problems


def test_zone_factors_and_importance(pack):
    # IS 1893 (Part 1):2016 Table 3; Table 8.
    assert dict(pack.table("zoneCoefficients").zones) == {2: 0.10, 3: 0.16, 4: 0.24, 5: 0.36}
    cats = pack.table("occupancyCategories").categories
    assert [cats[k].seismicImportance for k in ("I", "II", "III", "IV")] == [1.0, 1.0, 1.2, 1.5]
    towns = pack.table("locations").locations
    assert (towns["delhi"].zone, towns["delhi"].windSpeed) == (4, 47.0)
    assert (towns["mumbai"].zone, towns["mumbai"].windSpeed) == (3, 44.0)
    assert (towns["guwahati"].zone, towns["chennai"].windSpeed) == (5, 50.0)


def test_response_reduction_factors(pack):
    # IS 1893 (Part 1):2016 Table 9.
    systems = pack.table("seismic").systems
    expected = {
        "rcOmf": 3.0,
        "rcSmf": 5.0,
        "steelOmf": 3.0,
        "steelSmf": 5.0,
        "steelScbf": 4.0,
        "steelEbf": 5.0,
        "masonryOrdinaryPlain": 1.5,
        "masonryBands": 2.0,
        "masonryOrdinaryReinforced": 2.5,
        "rcOrdinaryWallFrame": 3.0,
        "rcSpecialWallFrame": 4.0,
        "rcDualOrdinary": 3.0,
        "rcDualSpecialOrdinaryWalls": 4.0,
        "rcDualOrdinaryFrameDuctileWalls": 4.5,
        "rcDualSpecial": 5.0,
        "rcFlatSlabWalls": 3.0,
    }
    assert {k: systems[k].R for k in expected} == expected
    # The displacement estimate is R times the elastic one (Clause 7.11.3): Cd = R.
    assert all(row.Cd == row.R for row in systems.values())


@pytest.mark.parametrize(
    ("site", "period", "static", "rs"),
    [
        # Clause 6.4.2: Figure 2(a) for the static method, 2(b) for response spectrum.
        ("I", 0.05, 2.5, 1.75),
        ("I", 0.30, 2.5, 2.5),
        ("I", 1.00, 1.0, 1.0),
        ("I", 5.00, 0.25, 0.25),
        ("II", 0.50, 2.5, 2.5),
        ("II", 1.00, 1.36, 1.36),
        ("II", 6.00, 0.34, 0.34),
        ("III", 1.00, 1.67, 1.67),
        ("III", 4.50, 0.4175, 0.4175),
    ],
)
def test_spectrum_sa_g(pack, site, period, static, rs):
    from saengine.fem import loads as fl

    assert fl.normalized_spectrum(period, site, static=True) == pytest.approx(static, abs=1e-4)
    assert fl.normalized_spectrum(period, site) == pytest.approx(rs, abs=1e-4)


def test_design_horizontal_acceleration(pack):
    from saengine.fem import loads as fl

    # Ah = (Z/2)(I/R)(Sa/g): zone IV, I 1.2, R 5, soil II, T 1.0 s: 0.12 × 0.24 × 1.36.
    assert fl.design_acceleration(1.0, "II", 0.24, 1.2, 5.0, static=True) == pytest.approx(
        0.24 / 2 * 1.2 / 5.0 * 1.36
    )


def test_approximate_period(pack):
    from saengine.fem import loads as fl

    # Clause 7.6.2 (a) bare RC frame 0.075 h^0.75, steel 0.085 h^0.75; (c) 0.09 h / √d.
    assert fl.approximate_period(20.0, "rcSmf") == pytest.approx(0.075 * 20**0.75)
    assert fl.approximate_period(20.0, "steelSmf") == pytest.approx(0.085 * 20**0.75)
    assert fl.approximate_period(20.0, "rcDualSpecial", 16.0) == pytest.approx(0.09 * 20 / 4.0)


def test_base_shear_rules(pack):
    from saengine.fem import loads as fl

    # Clause 7.2.2 Table 7: least VB / W by zone.
    assert [fl.minimum_base_share(z) for z in (2, 3, 4, 5)] == [0.007, 0.011, 0.016, 0.024]
    # Clause 7.6.3: Qi = VB Wi hi² / Σ Wj hj², whatever the period.
    forces = fl.vertical_distribution([(3.0, 1.0), (6.0, 1.0)], 100.0, 0.2)
    assert forces == pytest.approx([20.0, 80.0])
    seismic = pack.table("seismic")
    # Clause 7.7.3 (scaled to VB), 7.11.1 (0.004), Table 10 (25 % / 50 % over 3 kN/m²).
    assert seismic.minimumScale == 1.0
    assert seismic.allowableDrift["II"] == 0.004
    assert seismic.driftAmplification == "designForces"
    assert (seismic.liveShare, seismic.heavyLiveLimit, seismic.heavyLiveShare) == (0.25, 3.0, 0.5)
    # Table 5 (i) Δmax > 1.2 Δmin as Δmax / Δavg.
    assert seismic.torsionIrregular == pytest.approx(2 * 1.2 / 2.2, abs=1e-4)


def test_seismic_categories_follow_the_zones(pack):
    from saengine.fem.seismic_design import seismic_design_category

    assert seismic_design_category(2, "II", "II") == "B"
    assert [seismic_design_category(z, "III", "IV") for z in (3, 4, 5)] == ["C", "C", "C"]


def test_wind_speed_factors(pack):
    from saengine.fem import loads as fl
    from saengine.fem import wind_speed_factors as wsf

    # IS 875 (Part 3):2015 Table 2 (k2), Table 1 (k1), Clauses 6.4 and 7.2.
    assert wsf.height_factor(10, "2") == 1.00
    assert wsf.height_factor(5, "4") == 0.80
    assert wsf.height_factor(40, "3") == pytest.approx((1.06 + 1.12) / 2)
    assert wsf.risk_coefficient(47, 1.07) == 1.07
    assert wsf.risk_coefficient(33, 0.9) == 0.94
    f = wsf.factors(30.0, 47.0, "2", 1.0)
    assert f["Vz"] == pytest.approx(47 * 1.12)
    assert f["K"] == pytest.approx(0.9 * 1.0 * 0.9)
    assert f["pd"] == pytest.approx(0.81 * 0.6 * (47 * 1.12) ** 2 / 1000)
    assert fl.velocity_pressure(30.0, 47.0, "2", 1.0) == pytest.approx(f["pd"])
    # Kd Ka Kc at least 0.7.
    with fl.wind_overrides(type("W", (), {"directionality": 0.7})()):
        assert wsf.factors(10, 47, "2", 1.0)["K"] == 0.7
    # Table 5: h/w ≤ 1/2, l/w ≤ 3/2: +0.7 / -0.2; 3/2 < h/w: +0.8.
    assert fl.wall_coefficients(5.0, 12.0, 12.0) == (0.7, -0.2)
    assert fl.wall_coefficients(40.0, 15.0, 20.0)[0] == 0.8


def test_combinations(pack):
    rows = {r.id: r.factors for r in pack.table("combinations").strength}
    # IS 456 Table 18 / IS 875 (Part 5) 8.4 / IS 1893 (Part 1) 6.3.4.1.
    assert rows["1"]["D"] == rows["1"]["L"] == 1.5
    assert (rows["2E"]["D"], rows["2E"]["L"], rows["2E"]["E"]) == (1.2, 1.2, 1.2)
    assert (rows["3W"]["D"], rows["3W"]["W"]) == (1.5, 1.5)
    assert (rows["4E"]["D"], rows["4E"]["E"]) == (0.9, 1.5)


def test_imposed_loads_and_reduction(pack):
    from saengine.design import live_reduction as lr

    uses = pack.table("areaLoads").uses
    # IS 875 (Part 2):1987 Tables 1 and 2.
    assert (uses["residential"].live, uses["office"].live, uses["classroom"].live) == (
        2.0,
        2.5,
        3.0,
    )
    assert (uses["roof"].live, uses["roofAccess"].live) == (0.75, 1.5)
    assert pack.table("areaLoads").partitions.minimum == 1.0
    # Clause 3.2.1 Table 3, 3.2.2 beams.
    scope = lr.LiveScope(live=2.5)
    factors = [lr.reduction(1, 10.0, n, scope)[0] for n in (1, 2, 3, 4, 7, 12)]
    assert factors == pytest.approx([1.0, 0.9, 0.8, 0.7, 0.6, 0.5])
    assert lr.reduction(1, 120.0, 1, scope)[0] == pytest.approx(0.9)
    assert lr.reduction(1, 400.0, 1, scope)[0] == pytest.approx(0.75)
    assert pack.table("deadLoads").masonry["burntClayBrick"] == 18.85


# ──────────────────────── settings and a generated building ────────────────────────


def test_settings_for_the_pack():
    from saengine.library.settings import check, default_project_settings, derived

    settings = default_project_settings("India", code_pack=PACK)
    assert settings.codePack == PACK
    assert (settings.site.location, settings.site.siteClass) == ("delhi", "II")
    assert (settings.seismic.system, settings.wind.exposure) == ("rcSmf", "2")
    assert {c.name for c in settings.combinations} >= {"1.5(D + L)", "0.9D + 1.5EX"}
    assert not [p for p in check(settings) if p.startswith("codePack")]
    with code_context.using(code_context.pack_for(settings)):
        values = derived(settings)
    assert (values["Z"], values["windSpeed"], values["R"]) == (0.24, 47.0, 5.0)


def _generated() -> dict:
    from saengine.library.generator import generate_building

    spec = {
        "name": "IS frame",
        "gridsX": [5000, 5000],
        "gridsY": [4000, 4000],
        "storyCount": 3,
        "groundHeight": 3500,
        "typicalHeight": 3200,
        "codePack": PACK,
    }
    result = generate_building(spec)
    assert result["settings"]["codePack"] == PACK
    return result


def _derive(result: dict, **analysis: object):
    from saengine.fem.derive import derive_fem
    from saengine.library import FloorPlan, MaterialLibrary, ObjectLibrary
    from saengine.library.bim import generate
    from saengine.library.settings import ProjectSettings

    settings = ProjectSettings.model_validate(result["settings"])
    if analysis:
        settings = settings.model_copy(
            update={"analysis": settings.analysis.model_copy(update=analysis)}
        )
    building = generate(FloorPlan.model_validate(result["floorPlan"]), "s")
    return derive_fem(
        building,
        ObjectLibrary.model_validate(result["objects"]),
        MaterialLibrary.model_validate(result["materials"]),
        settings,
        {"bim": "abc"},
    )


def test_generated_building_derives_seismic_and_wind():
    result = _generated()
    settings = result["settings"]
    assert (settings["site"]["location"], settings["seismic"]["system"]) == ("delhi", "rcSmf")
    d = _derive(result)
    names = {p["name"] for p in d.project["load_patterns"]}
    assert {"EX", "EY", "WX", "WY"} <= names
    ex = d.summary["seismic"]["EX"]
    # Delhi: zone IV, Z 0.24, soil II, RC SMRF R 5, I 1.0; Ta = 0.075 h^0.75 (Clause 7.6.2).
    height = 3.5 + 2 * 3.2
    ta = 0.075 * height**0.75
    sa_g = 2.5 if ta <= 0.544 else 1.36 / ta
    assert ex["period_s"] == pytest.approx(ta, rel=1e-6)
    ah = max(0.24 / 2 * 1.0 / 5.0 * sa_g, 0.016)
    assert ex["Sa_g"] == pytest.approx(ah, rel=1e-6)
    assert ex["base_shear_kN"] == pytest.approx(ah * d.summary["weight_kN"], rel=1e-6)
    # Qi ∝ Wi hi² (Clause 7.6.3): the forces of the levels sum to VB.
    applied = sum(
        n["forces"][0]
        for p in d.project["load_patterns"]
        if p["name"] == "EX"
        for n in p["nodal_loads"]
    )
    assert applied == pytest.approx(ah * d.summary["weight_kN"] * 1e3, rel=1e-4)
    # Wind: IS 875 (Part 3) pd at the roof, Vb 47 m/s, terrain 2, k1 1.0.
    wx = sum(
        n["forces"][0]
        for p in d.project["load_patterns"]
        if p["name"] == "WX"
        for n in p["nodal_loads"]
    )
    assert wx > 0


def test_generated_building_response_spectrum_is_the_is_spectrum():
    from saengine.fem.derive import G

    d = _derive(_generated(), seismicDesign="responseSpectrum")
    spectrum = d.project["spectra"][0]
    # Figure 2(b), soil II, zone IV, I 1.0, R 5: Ah = 0.12 × 0.2 × Sa/g, Sa/g = 1 + 15T below
    # 0.1 s, 2.5 to 0.544 s, 1.36/T to 4 s, 0.34 beyond (in m/s²).
    for t, a in zip(spectrum["periods"], spectrum["accelerations"], strict=True):
        sa = 1 + 15 * t if t <= 0.1 else 2.5 if t <= 0.544 else 1.36 / t if t <= 4 else 0.34
        assert a == pytest.approx(G * 0.024 * sa, rel=1e-4, abs=1e-6), t


def test_wizard_spec_takes_the_pack_town_and_soil_type():
    from saengine.project.new_building import spec_from_wizard

    spec, _ = spec_from_wizard(
        {
            "schema": "saengine.newBuilding/1",
            "name": "IS",
            "spacings": {"x": [5000], "y": [4000]},
            "storyHeights": [3200],
            "site": {"location": "mumbai", "siteClass": "III", "siteClassSource": "assumed"},
            "designCode": PACK,
            "wind": {"exposure": "3"},
        }
    )
    assert (spec["codePack"], spec["location"], spec["siteClass"]) == (PACK, "mumbai", "III")
    assert spec["windExposure"] == "3"

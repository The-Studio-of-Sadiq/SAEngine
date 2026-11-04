"""C1: the US code pack ``aci318-asce7-22`` (ASCE 7-22 loads) and the generic methods it picks.

Pins the pack's values with their clauses (VERIFY.md in the pack lists them for checking against
the printed standard), the mapped spectral hazard (:mod:`saengine.fem.spectral_hazard`), the
roof snow (:mod:`saengine.fem.snow_load`), and a small generated building that derives its
earthquake and wind loads with the pack.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.fem import loads as fl
from saengine.fem import snow_load
from saengine.fem import spectral_hazard as sh

PACK_ID = "aci318-asce7-22"
SETTINGS = "02 Project Settings/project-settings.json"


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    """No pack of the machine's user folder takes part."""
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def pack():
    return registry.load(PACK_ID)


# ───────────────────────────── the pack: loads, coverage, fallbacks ─────────────────────────────


def test_pack_is_usable_and_extends_bnbc_for_the_materials(pack):
    info = registry.info(PACK_ID)
    assert info.usable and not info.problems
    assert info.extends == "bnbc2020"
    assert set(info.covers) >= {"combinations", "seismic", "wind", "snow", "areaLoads"}
    # C2 gives the concrete tables (ACI 318-19), C3 the steel (AISC 360-22); timber still falls
    # back to the pack it extends.
    for table in ("timber",):
        assert pack.has(table)
        assert pack.table(table) == registry.load("bnbc2020").table(table), table
    assert pack.basis["concrete"] == "ACI 318-19"
    assert pack.basis["general"] == "ASCE 7-22"


def test_risk_categories_and_importance(pack):
    # ASCE 7-22 Table 1.5-2 (Ie); wind by risk-category maps: no importance factor.
    cats = pack.table("occupancyCategories").categories
    assert {k: c.seismicImportance for k, c in cats.items()} == {
        "I": 1.0,
        "II": 1.0,
        "III": 1.25,
        "IV": 1.5,
    }
    assert {c.windImportance for c in cats.values()} == {1.0}


def test_live_loads_and_reduction(pack):
    uses = pack.table("areaLoads").uses
    # ASCE 7-22 Table 4.3-1 (SI)
    assert uses["office"].live == 2.40 and uses["office"].concentrated == 8.90
    assert uses["residential"].live == 1.92
    assert uses["stairs"].live == 4.79 and uses["stairs"].concentrated == 1.33
    assert uses["roof"].live == 0.96 and uses["roof"].roof
    assert uses["storageHeavy"].live == 11.97
    assert uses["parking"].concentrated == 13.35 and uses["parking"].patch == 114
    # Sec 4.3.2: partitions at least 15 psf
    assert pack.table("areaLoads").partitions.minimum == 0.72
    red = pack.table("liveReduction")
    # Eq 4.7-1: L = L0 (0.25 + 15/sqrt(KLL AT)), 4.57 in metres; Sec 4.8.2: 12-20 psf
    assert (red.constant, red.coefficient, red.influenceMin) == (0.25, 4.57, 37.16)
    assert (red.roof.minimum, red.roof.maximum) == (0.58, 0.96)
    assert red.heavyLive == 4.79 and red.notReducedBuildings == []


def test_combinations(pack):
    table = pack.table("combinations")
    by_id = {c.id: c.factors for c in table.strength}
    # ASCE 7-22 Sec 2.3.1 and 2.3.6
    assert by_id["1"] == {"D": 1.4, "F": 1.4}
    assert (
        by_id["3W"]["W"] == 0.5
        and by_id["4"]["W"] == 1.0
        and by_id["5"]
        == {
            "D": 0.9,
            "W": 1.0,
            "H": 1.6,
        }
    )
    assert by_id["6"]["E"] == 1.0 and by_id["6"]["S"] == 0.2
    assert (table.seismicDeadUpper, table.seismicDeadLower) == (1.2, 0.9)
    assert table.alternates == {"Lr": ["S", "R"]}
    assert "S" in table.loadCases and "S" in table.optionalCases
    # Sec 2.4.1, 2.4.5
    allowable = {c.id: c.factors for c in table.allowable}
    assert allowable["5W"]["W"] == 0.6 and allowable["6W"]["W"] == 0.45
    assert allowable["8"] == {"D": 0.6, "E": 0.7, "H": 1.0}
    # Exception 1: L at 0.5 where L0 <= 100 psf
    exception = table.exceptions["reducedLive"]
    assert exception.to == 0.5 and exception.liveMax == 4.79
    assert set(exception.rows) == {"3L", "4", "6", "4Fa"}
    # Sec 2.3.2: coastal 1.0W + 2.0Fa, noncoastal 0.5W + 1.0Fa
    coastal = {c.id: c.factors for c in table.flood["coastal"].strength}
    inland = {c.id: c.factors for c in table.flood["inland"].strength}
    assert (coastal["5Fa"]["W"], coastal["5Fa"]["Fa"]) == (1.0, 2.0)
    assert (inland["5Fa"]["W"], inland["5Fa"]["Fa"]) == (0.5, 1.0)


def test_seismic_systems_and_limits(pack):
    s = pack.table("seismic")
    # ASCE 7-22 Table 12.2-1
    smf = s.systems["rcSmf"]
    assert (smf.R, smf.Omega0, smf.Cd) == (8.0, 3.0, 5.5)
    assert smf.heightLimits == {"B": None, "C": None, "D": None, "E": None, "F": None}
    walls = s.systems["rcSpecialWallFrame"]
    assert (walls.R, walls.Omega0, walls.Cd) == (6.0, 2.5, 5.0)
    assert walls.heightLimits["D"] == 48.8 and walls.heightLimits["F"] == 30.5
    assert s.systems["rcImf"].heightLimits["D"] == 0.0
    assert s.systems["rcOmf"].heightLimits["C"] == 0.0
    assert s.systems["rcOrdinaryWallFrame"].Cd == 4.5
    # Table 12.12-1, Sec 12.9.1.4.1, 12.4.2.2, Eq 12.8-16
    assert s.allowableDrift == {"I": 0.02, "II": 0.02, "III": 0.015, "IV": 0.01}
    assert s.minimumScale == 1.0
    assert s.pgaFactor * s.verticalFactor == pytest.approx(0.2)
    assert s.stability.method == "elasticDrift" and s.designSpectrum.method == "mappedSpectral"
    assert s.siteClasses["SD"].vs30 == (213, 305)
    assert s.dynamicAnalysis is None and s.softStorey is None  # not covered


def test_wind_constants(pack):
    wind = pack.table("wind")
    # ASCE 7-22 Table 26.11-1: alpha, zg (3280, 2460, 1935 ft); Kz = 2.41 (z/zg)^(2/alpha)
    assert {k: (e.alpha, e.zg) for k, e in wind.exposures.items()} == {
        "B": (7.5, 999.7),
        "C": (9.8, 749.8),
        "D": (11.5, 589.8),
    }
    assert (wind.kzFactor, wind.kzMinHeight, wind.directionality, wind.gust) == (
        2.41,
        4.57,
        0.85,
        0.85,
    )
    with code_context.using(pack):
        # Kz of exposure C at 33 ft (10 m) is about 1.0, as in the earlier editions.
        assert fl.exposure_coefficient(10.0, "C") == pytest.approx(0.9986, abs=5e-4)
        assert fl.exposure_coefficient(2.0, "B") == fl.exposure_coefficient(4.57, "B")
    assert wind.topography.shapes["escarpment"].k1 == {"B": 0.75, "C": 0.85, "D": 0.95}


def test_bnbc_kz_is_unchanged():
    # The default pack gives no kzFactor: 2.01 and 4.57 m (BNBC 2020 Table 6.2.11).
    profile = code_context.table("wind").exposures["B"]
    expected = 2.01 * (10.0 / profile.zg) ** (2 / profile.alpha)
    assert fl.exposure_coefficient(10.0, "B") == pytest.approx(expected, rel=1e-12)


# ───────────────────────────── mapped spectral hazard (Ch 11-12) ─────────────────────────────


def _hazard(sds=1.0, sd1=0.6, s1=None, tl=8.0):
    return sh.SpectralHazard(sds, sd1, s1, tl)


def test_two_period_spectrum(pack):
    h = _hazard()
    with code_context.using(pack):
        # Sec 11.4.6: TS = SD1/SDS = 0.6, T0 = 0.12; 0.4 SDS at T = 0
        assert sh.two_period(0.0, h) == pytest.approx(0.4)
        assert sh.two_period(0.06, h) == pytest.approx(0.7)
        assert sh.two_period(0.12, h) == pytest.approx(1.0)
        assert sh.two_period(0.6, h) == pytest.approx(1.0)
        assert sh.two_period(1.2, h) == pytest.approx(0.5)
        assert sh.two_period(10.0, h) == pytest.approx(0.6 * 8 / 100)
        # The design spectrum Sa I/R
        assert fl.design_acceleration(1.2, "SD", h, 1.25, 8.0) == pytest.approx(0.5 * 1.25 / 8)


def test_multi_period_spectrum_is_used_where_given(pack):
    h = sh.SpectralHazard(1.0, 0.6, None, 8.0, [(0.0, 0.4), (0.5, 1.2), (2.0, 0.3)])
    with code_context.using(pack):
        assert sh.spectral_acceleration(0.5, h) == pytest.approx(1.2)
        assert sh.spectral_acceleration(1.25, h) == pytest.approx(0.75)


def test_elf_coefficient_and_its_bounds(pack):
    with code_context.using(pack):
        # Eq 12.8-2: SDS/(R/Ie); Eq 12.8-3: at most SD1/(T R/Ie)
        assert fl.elf_coefficient(0.3, "SD", _hazard(), 1.0, 8.0) == pytest.approx(0.125)
        assert fl.elf_coefficient(1.0, "SD", _hazard(), 1.0, 8.0) == pytest.approx(0.075)
        # Eq 12.8-4: beyond TL, SD1 TL/(T² R/Ie)
        assert fl.elf_coefficient(10.0, "SD", _hazard(), 1.0, 8.0) == pytest.approx(
            max(0.6 * 8 / (100 * 8), 0.044 * 1.0, 0.01)
        )
        # Eq 12.8-5: at least 0.044 SDS Ie, and 0.01
        low = _hazard(sds=0.2, sd1=0.05)
        assert fl.elf_coefficient(4.0, "SD", low, 1.0, 8.0) == pytest.approx(0.01)
        assert fl.elf_coefficient(4.0, "SD", _hazard(sds=0.5, sd1=0.1), 1.5, 8.0) == pytest.approx(
            0.044 * 0.5 * 1.5
        )
        # Eq 12.8-6: S1 >= 0.6: at least 0.5 S1/(R/Ie)
        near = _hazard(sds=1.0, sd1=0.9, s1=0.9)
        assert fl.elf_coefficient(3.0, "SD", near, 1.0, 8.0) == pytest.approx(0.5 * 0.9 / 8)


def test_period_upper_factor_by_sd1(pack):
    with code_context.using(pack):
        # Table 12.8-1
        assert fl.period_upper_factor(_hazard(sd1=0.5)) == pytest.approx(1.4)
        assert fl.period_upper_factor(_hazard(sd1=0.2)) == pytest.approx(1.5)
        assert fl.period_upper_factor(_hazard(sd1=0.175)) == pytest.approx(1.55)
        assert fl.period_upper_factor(_hazard(sd1=0.05)) == pytest.approx(1.7)
    # The default pack: its single factor.
    assert fl.period_upper_factor(0.2) == pytest.approx(1.4)


@pytest.mark.parametrize(
    ("sds", "sd1", "s1", "category", "sdc"),
    [
        (0.1, 0.05, None, "II", "A"),
        (0.2, 0.05, None, "II", "B"),
        (0.2, 0.05, None, "IV", "C"),
        (0.4, 0.1, None, "II", "C"),
        (0.4, 0.25, None, "II", "D"),  # SD1 governs (Table 11.6-2)
        (0.6, 0.3, None, "I", "D"),
        (1.5, 0.9, 0.8, "II", "E"),  # S1 >= 0.75 (Sec 11.6)
        (1.5, 0.9, 0.8, "IV", "F"),
    ],
)
def test_seismic_design_category(pack, sds, sd1, s1, category, sdc):
    from saengine.fem.seismic_design import seismic_design_category, zone_of

    with code_context.using(pack):
        h = _hazard(sds, sd1, s1)
        assert seismic_design_category(zone_of(h), "SD", category) == sdc


def test_sms_sm1_from_a_multi_period_mcer_spectrum(pack):
    mcer = [(0.0, 0.6), (0.2, 1.5), (0.5, 1.6), (1.0, 1.0), (2.0, 0.55), (5.0, 0.2)]
    with code_context.using(pack):
        sds, sd1 = sh.from_mcer(mcer, "SC")
        # Sec 21.4: SMS = 0.9 x 1.6; SM1 = max T Sa from 1 to 2 s = 1.1; design 2/3
        assert sds == pytest.approx(2 / 3 * 0.9 * 1.6, rel=1e-6)
        assert sd1 == pytest.approx(2 / 3 * 1.1, rel=1e-6)
        # A soft site: T Sa from 1 to 5 s
        assert sh.from_mcer(mcer, "SD")[1] == pytest.approx(2 / 3 * 1.1, rel=1e-6)


def test_default_pack_spectrum_is_unchanged():
    """The zone-factor method (BNBC 2020) keeps its formula: ELF = design spectrum."""
    t, z = 0.6, 0.2
    expected = 2 / 3 * z * 1.0 / 8.0 * fl.normalized_spectrum(t, "SD")
    assert fl.design_acceleration(t, "SD", z, 1.0, 8.0) == pytest.approx(expected, rel=1e-12)
    assert fl.elf_coefficient(t, "SD", z, 1.0, 8.0) == fl.design_acceleration(t, "SD", z, 1.0, 8.0)
    assert not sh.uses_mapped()


# ───────────────────────────────────────── snow (Ch 7) ─────────────────────────────────────────


def _snow_settings(angle: float = 0.0, **snow):
    from types import SimpleNamespace

    from saengine.library.settings import SnowSite

    roof = SimpleNamespace(form="flat" if not angle else "gable", angle=angle)
    return SimpleNamespace(
        site=SimpleNamespace(snow=SnowSite(**snow)),
        wind=SimpleNamespace(claddingRoof=roof),
        occupancy=SimpleNamespace(category="II"),
    )


def test_roof_snow(pack):
    from saengine.library.settings import SnowDrift

    with code_context.using(pack):
        snow = snow_load.roof_snow(_snow_settings(groundLoad=1.92))
        # Eq 7.3-1: pf = 0.7 Ce Ct pg (C, partially exposed: Ce 1.0); low slope: pm = 20 psf
        assert snow["method"] == "slopeFactor" and snow["case"] == "S"
        assert snow["pf_kPa"] == pytest.approx(0.7 * 1.0 * 1.0 * 1.92)
        assert snow["mu1"] == 1.0 and snow["pm_kPa"] == pytest.approx(0.96)
        assert snow["s_kPa"] == pytest.approx(1.344)
        # Figure 7.4-1: a warm, non-slippery roof sheds snow from 30 to 70 degrees
        steep = snow_load.roof_snow(_snow_settings(50.0, groundLoad=1.92))
        assert steep["mu1"] == pytest.approx(0.5) and steep["pm_kPa"] is None
        # Table 7.3-1 by the exposure id
        windy = snow_load.roof_snow(_snow_settings(groundLoad=2.0, exposure="D-fullyExposed"))
        assert windy["Ce"] == 0.8
        # Eq 7.7-1: gamma = 0.426 pg + 2.2 <= 4.7
        assert snow_load.density(pack.table("snow"), 1.92) == pytest.approx(0.426 * 1.92 + 2.2)
        step = SnowDrift(upperLength=30.0, stepHeight=1.5, windParameter=0.45)
        drift = snow_load.roof_snow(_snow_settings(groundLoad=1.92, drift=step))["drift"]
        assert 0 < drift["hd"] <= 1.5 and drift["pd"] > 0


def test_bnbc_does_not_cover_snow():
    with pytest.raises(LookupError):
        snow_load.roof_snow(_snow_settings(groundLoad=1.0))


# ──────────────────────────── settings and a generated building ────────────────────────────


WIZARD = {
    "schema": "saengine.newBuilding/1",
    "name": "US Frame",
    "spacings": {"x": [6000, 6000], "y": [5000]},
    "stories": [
        {"id": "BASE", "name": "Base", "elevation": 0},
        {"id": "L1", "name": "Level 1", "elevation": 3500},
        {"id": "L2", "name": "Level 2", "elevation": 6500},
        {"id": "L3", "name": "Level 3", "elevation": 9500},
    ],
    "storyHeights": [3500, 3000, 3000],
    "system": "rcFrame",
    "footing": "isolated",
    "site": {
        "siteClass": "SD",
        "siteClassSource": "assumed",
        "spectral": {"sds": 1.0, "sd1": 0.6, "s1": 0.65, "tl": 8},
        "windSpeed": 50,
    },
    "occupancy": {"use": "office", "category": "II"},
    "designCode": PACK_ID,
}


def test_settings_lists_follow_the_pack():
    from saengine.library.settings import ProjectSettings, default_project_settings, pack_choices

    choices = pack_choices(registry.load(PACK_ID))
    assert [c["id"] for c in choices["exposures"]] == ["B", "C", "D"]
    assert [c["id"] for c in choices["locations"]] == ["custom"]  # no towns: values entered
    assert choices["designSpectrum"] == [{"id": "mappedSpectral", "label": "mappedSpectral"}]
    base = default_project_settings("x").model_dump(mode="json", by_alias=True)
    with pytest.raises(ValueError, match="wind.exposure 'A'"):
        ProjectSettings.model_validate({**base, "codePack": PACK_ID})


def test_generated_building_derives_seismic_and_wind(tmp_path: Path):
    from saengine.library.settings import ProjectSettings, check, derived
    from saengine.pipeline.run_all import run_all
    from saengine.project.new_building import create_building

    result = create_building(WIZARD, tmp_path)
    root = Path(result["root"])
    raw = json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    assert raw["codePack"] == PACK_ID and raw["wind"]["exposure"] == "B"
    assert raw["site"]["location"] == "custom" and raw["site"]["spectral"]["sds"] == 1.0
    with code_context.project(root):
        settings = ProjectSettings.model_validate(raw)
        assert not [p for p in check(settings) if p.startswith(("site.", "codePack"))]
        values = derived(settings)
    assert isinstance(values["Z"], sh.SpectralHazard) and values["zone"] == 4  # SDC D band
    steps = run_all(root, steps=["derive"]).steps
    assert [s.status for s in steps] == ["ok"], [s.message for s in steps]
    derivation = json.loads((root / "08 FEM/model.derivation.json").read_text(encoding="utf-8"))
    summary = derivation["summary"]
    # Cs = SDS/(R/Ie) = 1.0/8 (SD1/(T R/Ie) larger at Ta = 0.0466 x 9.5^0.9)
    ta = 0.0466 * 9.5**0.9
    assert summary["period_s"] == pytest.approx(ta, rel=1e-3)
    assert summary["Sa_g"] == pytest.approx(0.125)
    assert summary["base_shear_kN"] == pytest.approx(0.125 * summary["weight_kN"], rel=1e-6)
    assert "SDS = 1.000 g" in summary["spectral"] and "Cs" not in summary
    assert summary["wind"]["levels"]["WX"] and summary["wind"]["levels"]["WY"]
    model = json.loads((root / "08 FEM/model.osmodel").read_text(encoding="utf-8"))
    names = {p["name"] for p in model["load_patterns"]}
    assert {"EX", "EY", "WX", "WY"} <= names
    ex = next(p for p in model["load_patterns"] if p["name"] == "EX")
    total = sum(n["forces"][0] for n in ex["nodal_loads"]) / 1e3
    assert total == pytest.approx(summary["base_shear_kN"], rel=1e-3)
    assert any("mapped spectral values" in n for n in derivation["notes"])


def test_without_mapped_values_the_earthquake_cases_stay_empty():
    from saengine.library.settings import ProjectSettings, check, default_project_settings, derived

    base = default_project_settings("x").model_dump(mode="json", by_alias=True)
    base["codePack"] = PACK_ID
    base["wind"]["exposure"] = "C"
    base["site"]["location"] = "custom"
    settings = ProjectSettings.model_validate(base)
    assert derived(settings)["Z"] is None
    problems = check(settings)
    assert any(p.startswith("site.spectral") for p in problems)
    assert any(p.startswith("site.windSpeed") for p in problems)
    assert not any(p.startswith("site.zoneCoefficient") for p in problems)


def test_snow_case_on_the_roof(tmp_path: Path):
    from saengine.pipeline.run_all import run_all
    from saengine.project.new_building import create_building

    root = Path(create_building(WIZARD, tmp_path)["root"])
    path = root / SETTINGS
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["site"]["snow"] = {"groundLoad": 2.0, "exposure": "C-fullyExposed"}
    path.write_text(json.dumps(raw, indent="\t"), encoding="utf-8")
    steps = run_all(root, steps=["derive"]).steps
    assert [s.status for s in steps] == ["ok"], [s.message for s in steps]
    derivation = json.loads((root / "08 FEM/model.derivation.json").read_text(encoding="utf-8"))
    snow = derivation["summary"]["specialLoads"]["snow"]
    assert snow["pf_kPa"] == pytest.approx(0.7 * 0.9 * 1.0 * 2.0, abs=1e-4)
    assert snow["s_kPa"] == pytest.approx(max(snow["pf_kPa"], 0.96), abs=1e-4)
    model = json.loads((root / "08 FEM/model.osmodel").read_text(encoding="utf-8"))
    assert "S" in {p["name"] for p in model["load_patterns"]}
    assert math.isfinite(snow["s_kPa"])

"""The thin country packs of alpha 9 track C23: myanmar-mnbc, bhutan, qatar-qcs, hongkong-cop.

Each extends a built-in pack and sets only what its country changes; the tests pin those values
(with their clauses, see each pack's VERIFY.md), the generic mechanisms the packs needed (the
site coefficients Fa, Fv with the towns' SS and S1, the reference pressures by height, the
stress block and neutral axis by strength band) and derive a small generated building under each
pack.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

PACKS = {
    "myanmar-mnbc": ["myanmar-mnbc", "aci318-asce7-22", "bnbc2020"],
    "bhutan": ["bhutan", "is-codes", "bnbc2020"],
    "qatar-qcs": ["qatar-qcs", "bs8110", "bnbc2020"],
    "hongkong-cop": ["hongkong-cop", "bs8110", "bnbc2020"],
}


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.mark.parametrize("pack_id", sorted(PACKS))
def test_pack_is_listed_sound_and_extends(pack_id):
    assert pack_id in [p.id for p in registry.list_packs()]
    pack = registry.load(pack_id)
    assert pack.broken == {}
    assert pack.chain == PACKS[pack_id]
    for table in pack.info.covers:
        assert pack.provided_by(table) == pack_id
    assert pack.info.units == "SI"
    assert (Path(pack.path) / "VERIFY.md").is_file()
    assert (Path(pack.path) / "README.md").is_file()


# ───────────────────────────── Myanmar: MNBC 2020 ─────────────────────────────


def test_mnbc_values():
    pack = registry.load("myanmar-mnbc")
    yangon = pack.table("locations").locations["yangon"]
    assert (yangon.zone, yangon.ss, yangon.s1, yangon.windSpeed) == (3, 0.75, 0.3, 45.0)
    coefficients = pack.table("seismic").designSpectrum.siteCoefficients
    # ASCE 7-05 Tables 11.4-1 and 11.4-2 form (MNBC 2020 Part 3).
    assert coefficients.fa.classes["SD"] == [1.6, 1.4, 1.2, 1.1, 1.0]
    assert coefficients.fv.classes["SE"] == [3.5, 3.2, 2.8, 2.4, 2.4]
    strength = {c.id: c.factors for c in pack.table("combinations").strength}
    assert strength["4"]["W"] == 1.6 and strength["5"] == {"D": 0.9, "W": 1.6, "H": 1.6}
    assert strength["6"]["E"] == 1.0
    allowable = {c.id: c.factors for c in pack.table("combinations").allowable}
    assert allowable["5W"]["W"] == 1.0
    assert pack.table("occupancyCategories").categories["IV"].windImportance == 1.15
    wind = pack.table("wind")
    assert (wind.exposures["C"].alpha, wind.exposures["C"].zg, wind.kzFactor) == (9.5, 274.32, 2.01)
    assert pack.table("concrete").barNames == {}
    assert pack.table("barSchedule").standard == "bs8666"
    # What it does not set stays the US pack's.
    assert pack.provided_by("steel") == "aci318-asce7-22"


def test_site_coefficients_from_the_town():
    from saengine.fem import spectral_hazard as sh

    pack = registry.load("myanmar-mnbc")
    yangon = pack.table("locations").locations["yangon"]
    spectral = sh.with_location(None, yangon)
    # SS 0.75, S1 0.3, site class D: Fa 1.2, Fv 1.8; SDS = 2/3 × 0.9, SD1 = 2/3 × 0.54.
    hazard = sh.site_hazard(spectral, "SD", pack)
    assert float(hazard) == pytest.approx(0.6)
    assert hazard.sd1 == pytest.approx(0.36)
    assert sh.band(hazard, pack) == 4  # SD1 >= 0.2: the fourth band (D)
    # Between the points: SS 0.6 on class C, Fa = 1.2 - 0.1 × 0.4 = 1.16.
    assert sh.site_factors(0.6, 0.25, "SC", pack)[0] == pytest.approx(1.16)
    # Class F: read as the assumed class E until a site study.
    assert sh.site_factors(0.75, 0.3, "SF", pack)[2] == "SE"
    # A project's own SDS, SD1 still win; the US pack has no Fa, Fv (unchanged).
    own = SimpleNamespace(sds=0.5, sd1=0.2, ss=None, s1=None, tl=None)
    assert float(sh.site_hazard(sh.with_location(own, yangon), "SD", pack)) == 0.5
    us = registry.load("aci318-asce7-22")
    assert sh.site_hazard(SimpleNamespace(ss=0.75, s1=0.3), "SD", us) is None


# ───────────────────────────── Bhutan and Qatar ─────────────────────────────


def test_bhutan_and_qatar_values():
    bt = registry.load("bhutan")
    towns = bt.table("locations").locations
    assert (towns["thimphu"].zone, towns["thimphu"].windSpeed) == (4, 47.0)
    assert (towns["trashigang"].zone, towns["samdrupJongkhar"].windSpeed) == (5, 50.0)
    assert bt.table("zoneCoefficients").zones[5] == 0.36  # IS 1893 Table 3 (parent)
    qa = registry.load("qatar-qcs")
    assert qa.table("locations").locations["doha"].windSpeed == 25.0
    assert qa.table("zoneCoefficients").zones == {0: 0.0}  # not covered
    assert qa.table("wind").defaultExposure == "town2"
    assert qa.table("concreteMethods").defaultExposure == "severe"


# ───────────────────────────── Hong Kong ─────────────────────────────


def test_hk_wind_reference_pressures():
    from saengine.fem import loads
    from saengine.fem import wind_speed_factors as wsf

    pack = registry.load("hongkong-cop")
    with code_context.using(pack):
        assert loads.velocity_pressure(10.0, 60.3, "hongKong", 1.0) == pytest.approx(2.23)
        # Linear between the heights of the table: 2.46 + 0.5 × 0.14 at 25 m.
        assert loads.velocity_pressure(25.0, 60.3, "hongKong", 1.0) == pytest.approx(2.53)
        assert loads.velocity_pressure(600.0, 60.3, "hongKong", 1.0) == pytest.approx(3.88)
        f = wsf.factors(10.0, 60.3, "hongKong", 1.0)
        assert (f["k2"], f["Kc"]) == (1.0, 1.0)
    with code_context.using(registry.load("bs8110")):  # the parent unchanged
        assert wsf.reference_pressure(10.0, "country10") is None


def test_hk_concrete():
    from saengine.design import design_strength, limit_state_rows, tabulated_shear

    pack = registry.load("hongkong-cop")
    with code_context.using(pack):
        assert design_strength.rules().gammaS == 1.15  # Table 2.2
        assert design_strength.properties(40).lam == 0.9  # 6.1.2.4
        assert design_strength.properties(60).lam == 0.8
        assert design_strength.properties(80).lam == 0.72
        assert design_strength.properties(30).ecm == pytest.approx(3210 + 3460 * 30**0.5)
        assert limit_state_rows.neutral_axis_limit(500, 40) == 0.5  # 6.1.2.4(c)
        assert limit_state_rows.neutral_axis_limit(500, 60) == 0.4
        assert tabulated_shear.tau_c_max(80) == 7.0  # 6.1.2.5(a)
        assert tabulated_shear.tau_c(25, 1.0) == pytest.approx(0.632)
        assert tabulated_shear.tau_c(80, 1.0) == pytest.approx(0.931)
    assert pack.table("areaLoads").uses["office"].live == 3.0
    with code_context.using(registry.load("bs8110")):  # the parent unchanged
        assert design_strength.properties(60).lam == 0.9
        assert limit_state_rows.neutral_axis_limit(500, 60) == 0.5
        assert tabulated_shear.tau_c_max(80) == 5.0


# ───────────────────────────── generated buildings ─────────────────────────────


def _derive(tmp_path, spec):
    from saengine.pipeline.project import open_project
    from saengine.pipeline.run_all import DERIVATION_INPUTS
    from saengine.project.new_building import create_building
    from saengine.rpc import handlers

    base = {
        "name": "C23 Frame",
        "gridsX": [6000, 6000],
        "gridsY": [5000, 5000],
        "storyCount": 3,
        "typicalHeight": 3200,
        "system": "rcFrame",
        "lateralSizing": "gravity",
        "siteClass": "SD",
        "siteClassSource": "entered",
    }
    root = Path(create_building({**base, **spec}, tmp_path)["root"])
    settings = json.loads(
        (root / "02 Project Settings/project-settings.json").read_text(encoding="utf-8")
    )
    project = open_project(root)
    texts = project.texts(DERIVATION_INPUTS)
    with code_context.project(root):
        out = handlers.derive_fem(
            texts["bim"], texts["objects"], texts["materials"], texts["settings"],
            str(root / "08 FEM"),
        )  # fmt: skip
    return settings, out


def test_myanmar_building_derives(tmp_path):
    settings, out = _derive(tmp_path, {"codePack": "myanmar-mnbc", "location": "mandalay"})
    assert settings["site"]["location"] == "mandalay"
    seismic = out["summary"]["seismic"]["EX"]
    assert seismic["Sa_g"] > 0  # SS 1.25, S1 0.5 of the town with Fa, Fv of class D
    assert out["summary"]["wind_X_kN"] > 0


def test_bhutan_building_derives(tmp_path):
    _, out = _derive(tmp_path, {"codePack": "bhutan", "location": "trashigang"})
    assert out["summary"]["seismic"]["EX"]["Sa_g"] > 0
    assert out["summary"]["wind_X_kN"] > 0


def test_qatar_building_derives(tmp_path):
    _, out = _derive(tmp_path, {"codePack": "qatar-qcs", "location": "doha"})
    assert "Z" in out["summary"]["lateralMissing"]  # no seismic loading: no EX, EY
    assert out["summary"]["wind_X_kN"] > 0


def test_hk_building_derives(tmp_path):
    settings, out = _derive(tmp_path, {"codePack": "hongkong-cop", "location": "kowloon"})
    assert settings["wind"]["exposure"] == "hongKong"
    assert "Z" in out["summary"]["lateralMissing"]
    assert out["summary"]["wind_X_kN"] > 0

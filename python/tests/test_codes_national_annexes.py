"""The National Annex packs on the Eurocodes (alpha 9 track C15): eurocodes-uk, -de, -my, -sg.

Each pack extends ``eurocodes`` and sets only its Nationally Determined Parameters; the tests pin
those (with their clauses, see each pack's VERIFY.md), the generic mechanisms the annexes needed
(αcc of shear, the ν1 cap, the altitude factor, the qp(z) profiles and stepped pressures, the
ground snow load by zone and altitude, the least horizontal load) and derive a small generated
building under each pack.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

ANNEXES = ("eurocodes-uk", "eurocodes-de", "eurocodes-my", "eurocodes-sg")


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.mark.parametrize("pack_id", ANNEXES)
def test_annex_is_listed_sound_and_extends_eurocodes(pack_id):
    assert pack_id in [p.id for p in registry.list_packs()]
    pack = registry.load(pack_id)
    assert pack.broken == {}
    assert pack.chain == [pack_id, "eurocodes", "bnbc2020"]
    # What the annex does not set stays the base pack's.
    assert pack.provided_by("pushover") == "eurocodes"
    assert pack.table("seismic").designSpectrum.method == "behaviourFactor"


def test_uk_ndps():
    pack = registry.load("eurocodes-uk")
    c = pack.table("combinations")
    by_id = {x.id: x.factors for x in c.strength}
    # UK NA to BS EN 1990 Table NA.A1.2(B): 6.10a/b, ξ 0.925; ψ0 wind 0.5 (Table NA.A1.1).
    assert c.strengthSet == "6.10ab"
    assert by_id["6.10b-Q"]["D"] == pytest.approx(0.925 * 1.35)
    assert by_id["6.10a-QW"]["W"] == pytest.approx(0.75)
    assert by_id["6.10b-W"]["W"] == 1.5 and by_id["6.10b-W"]["L"] == pytest.approx(1.05)
    service = {x.name: x.factors for x in c.service}
    assert service["Characteristic: G + Q + 0.5S + 0.5W"]["W"] == 0.5
    assert "Characteristic: G + Q + 0.5S + 0.6W" not in service
    # UK NA to BS EN 1991-1-1 Tables NA.3, NA.7.
    uses = pack.table("areaLoads").uses
    assert uses["office"].live == 2.5 and uses["dwelling"].live == 1.5
    assert pack.table("areaLoads").roofLive[0].live == 0.6
    # Figure NA.1 towns, calt = 1 + 0.001 A (Eq NA.2a); no seismic design (PD 6698).
    assert pack.table("locations").locations["london"].windSpeed == 21.5
    assert pack.table("wind").altitude.factor == 0.001
    assert pack.table("zoneCoefficients").zones == {0: 0.0}
    # UK NA to BS EN 1992-1-1 3.1.6(1): αcc 0.85 / 1.0; BS EN 1993-1-1 6.1: γM2 1.10.
    u = pack.table("concreteMethods").ultimate
    assert (u.alphaCC, u.alphaCCShear) == (0.85, 1.0)
    steel = pack.table("steelLimitState")
    assert steel.memberResistance.gammaM2 == 1.1 and steel.connections.gammaM2 == 1.25
    assert pack.table("geotechnicalMethods").designApproach == "DA1"
    assert pack.table("barSchedule").standard == "bs8666"


def test_de_ndps():
    pack = registry.load("eurocodes-de")
    assert pack.table("combinations").strengthSet == "6.10"
    assert pack.table("areaLoads").uses["office"].live == 2.0
    zones = pack.table("zoneCoefficients").zones
    assert zones[3] == pytest.approx(0.8 / 9.81, abs=1e-3)
    assert pack.table("locations").locations["westerland"].windSpeed == 30.0
    assert pack.table("seismic").siteClasses["CS"].S == 0.75
    shear = pack.table("concreteMethods").shear
    assert (shear.crdcCoefficient, shear.nuMax) == (0.15, 0.75)
    assert pack.table("concreteMethods").ultimate.alphaCC == 0.85
    assert pack.table("steelLimitState").memberResistance.gammaM1 == 1.1
    geo = pack.table("geotechnicalMethods")
    assert geo.designApproach == "DA2*" and geo.approaches["DA2*"][0].resistances == "R2"


def test_my_and_sg_ndps():
    my = registry.load("eurocodes-my")
    assert my.table("locations").locations["kotaKinabalu"].zone == 5
    assert my.table("concreteMethods").ultimate.alphaCC == 0.85
    sg = registry.load("eurocodes-sg")
    assert sg.table("locations").locations["singapore"].windSpeed == 20.0
    assert sg.table("wind").minimumLateral.share == 0.015
    assert sg.table("steelLimitState").memberResistance.gammaM2 == 1.1


# ───────────────────────────── the generic mechanisms ─────────────────────────────


def test_shear_alpha_cc_and_nu_cap():
    from saengine.design import design_strength, strut_shear

    with code_context.using(registry.load("eurocodes-uk")):
        assert design_strength.fcd(30) == pytest.approx(0.85 * 30 / 1.5)
        assert design_strength.fcd(30, shear=True) == pytest.approx(30 / 1.5)
    with code_context.using(registry.load("eurocodes-de")):
        r = strut_shear.rules()
        assert strut_shear.nu1(30, r) == 0.75  # ν2 capped at 1.0
        assert strut_shear.nu1(70, r) == pytest.approx(0.75 * (1.1 - 70 / 500))
    with code_context.using(registry.load("eurocodes")):  # the base pack unchanged
        assert design_strength.fcd(30, shear=True) == design_strength.fcd(30) == 20.0
        assert strut_shear.nu1(30, strut_shear.rules()) == pytest.approx(0.6 * (1 - 30 / 250))


def test_de_velocity_pressure_profiles():
    from saengine.fem.peak_velocity_pressure import peak_velocity_pressure, simplified_pressure

    with code_context.using(registry.load("eurocodes-de")):
        qb = 0.5 * 1.25 * 25.0**2 / 1000
        assert peak_velocity_pressure(5.0, 25.0, "inland") == pytest.approx(1.5 * qb)
        assert peak_velocity_pressure(20.0, 25.0, "inland") == pytest.approx(1.7 * qb * 2.0**0.37)
        assert peak_velocity_pressure(1.0, 30.0, "northSeaIslands") == pytest.approx(1.1)
        assert simplified_pressure(12.0, 25.0, "inland") is None  # opt-in
    pack = registry.load("eurocodes-de").with_overrides(
        {"wind.peakVelocityPressure.useSimplified": True}
    )
    with code_context.using(pack):
        q, row = simplified_pressure(12.0, 25.0, "inland")
        assert q == 0.8 and row.vb0 == 25.0
        assert simplified_pressure(30.0, 25.0, "inland") is None  # above 25 m: the profile


def test_ground_snow_by_zone_and_altitude():
    from types import SimpleNamespace

    from saengine.fem.snow_load import ground_snow

    def settings(zone, altitude):
        return SimpleNamespace(
            site=SimpleNamespace(altitude=altitude, snow=SimpleNamespace(zone=zone))
        )

    uk = registry.load("eurocodes-uk").table("snow")
    # UK NA Eq NA.1: sk = 0.15 + 0.1 Z + 0.05 + (A - 100)/525.
    assert ground_snow(settings("3", 200.0), uk)["sk_kPa"] == pytest.approx(0.5 + 100 / 525)
    de = registry.load("eurocodes-de").table("snow")
    x = (400 + 140) / 760
    assert ground_snow(settings("2", 400.0), de)["sk_kPa"] == pytest.approx(0.25 + 1.91 * x * x)
    assert ground_snow(settings("1a", 0.0), de)["sk_kPa"] == pytest.approx(1.25 * 0.65)
    assert ground_snow(settings(None, 0.0), de) is None
    assert ground_snow(settings("2", 0.0), registry.load("eurocodes").table("snow")) is None


# ───────────────────────────── generated buildings ─────────────────────────────


def _derive(tmp_path, spec, site=None):
    from saengine.pipeline.project import open_project
    from saengine.pipeline.run_all import DERIVATION_INPUTS
    from saengine.project.new_building import create_building
    from saengine.rpc import handlers

    base = {
        "name": "NA Frame",
        "gridsX": [6000, 6000],
        "gridsY": [5000, 5000],
        "storyCount": 3,
        "typicalHeight": 3200,
        "system": "rcFrame",
        "lateralSizing": "gravity",
        "siteClass": "SB",
        "siteClassSource": "entered",
    }
    root = Path(create_building({**base, **spec}, tmp_path)["root"])
    path = root / "02 Project Settings/project-settings.json"
    settings = json.loads(path.read_text(encoding="utf-8"))
    for key, value in (site or {}).items():
        if isinstance(value, dict):
            settings["site"].setdefault(key, {}).update(value)
        else:
            settings["site"][key] = value
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    project = open_project(root)
    texts = project.texts(DERIVATION_INPUTS)
    with code_context.project(root):
        out = handlers.derive_fem(
            texts["bim"], texts["objects"], texts["materials"], texts["settings"],
            str(root / "08 FEM"),
        )  # fmt: skip
    return settings, out


def test_uk_building_derives(tmp_path):
    settings, out = _derive(
        tmp_path,
        {"codePack": "eurocodes-uk", "location": "manchester", "windExposure": "II"},
        {"altitude": 150.0, "snow": {"zone": "2"}},
    )
    assert settings["site"]["location"] == "manchester"
    notes = " ".join(out["notes"])
    assert "calt = 23.5 × 1.150" in notes.replace("vb,map × calt = ", "calt = ")
    assert "snow zone 2" in notes
    assert "Z" in out["summary"]["lateralMissing"]  # very low seismicity: no EX, EY
    assert out["summary"]["wind_X_kN"] > 0


def test_de_building_derives(tmp_path):
    _, out = _derive(
        tmp_path,
        {"codePack": "eurocodes-de", "location": "aachen", "windExposure": "inland",
         "siteClass": "CR"},
        {"altitude": 200.0, "snow": {"zone": "2"}},
    )  # fmt: skip
    notes = " ".join(out["notes"])
    assert "velocity pressure profile" in notes
    seismic = out["summary"]["seismic"]["EX"]
    assert seismic["Sa_g"] > 0  # zone 3, agR 0.0816 g
    assert out["summary"]["wind_X_kN"] > 0


def test_my_building_derives(tmp_path):
    _, out = _derive(tmp_path, {"codePack": "eurocodes-my", "location": "kotaKinabalu"})
    assert out["summary"]["seismic"]["EX"]["Sa_g"] > 0
    assert out["summary"]["wind_X_kN"] > 0


def test_sg_building_takes_the_least_horizontal_load(tmp_path):
    _, out = _derive(tmp_path, {"codePack": "eurocodes-sg", "windExposure": "III"})
    notes = " ".join(out["notes"])
    # The roof's wind force is below 1.5 % of its dead weight: it takes the least load.
    assert "WX: 1 level(s) take the least horizontal load 1.5%" in notes
    assert "vb,0 = 20 m/s" in notes
    assert "Z" in out["summary"]["lateralMissing"]

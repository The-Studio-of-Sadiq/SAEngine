"""Packs that adopt the US codes with local values (alpha 9 track C16): saudi-sbc,
pakistan-bcp, philippines-nscp, indonesia-sni.

Each pack extends ``aci318-asce7-22`` and sets only its own values; the tests pin a few of them
(with their clauses, see each pack's VERIFY.md), the two generic mechanisms the packs needed (the
site coefficients Fa, Fv of the ASCE 7-16 form with a town's SS and S1, and the ``ubc97``
spectrum method: Ca, Cv by soil profile and Z with the near-source factors) and derive a small
generated building under each pack.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.fem import spectral_hazard as sh
from saengine.library.settings import default_project_settings

PACKS = ("saudi-sbc", "pakistan-bcp", "philippines-nscp", "indonesia-sni")


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.mark.parametrize("pack_id", PACKS)
def test_pack_is_listed_sound_and_extends_the_us_pack(pack_id):
    assert pack_id in [p.id for p in registry.list_packs()]
    pack = registry.load(pack_id)
    assert pack.broken == {}
    assert pack.chain == [pack_id, "aci318-asce7-22", "bnbc2020"]
    assert default_project_settings("P", pack_id).units.system == "SI"
    # What the pack does not set stays the base pack's.
    assert pack.provided_by("pushover") == "aci318-asce7-22"
    assert pack.provided_by("combinations") == "aci318-asce7-22"


def test_the_us_pack_is_unchanged():
    pack = registry.load("aci318-asce7-22")
    rule = pack.table("seismic").designSpectrum
    assert rule.method == "mappedSpectral"
    assert rule.siteCoefficients is None and rule.ubc97 is None
    assert pack.table("locations").locations == {}
    assert sh.site_hazard(None, "SD", pack) is None
    assert default_project_settings("P", "aci318-asce7-22").units.system == "USCustomary"


# ───────────────────────────── the ASCE 7-16 form: Fa, Fv ─────────────────────────────


def test_site_coefficients_interpolate():
    pack = registry.load("saudi-sbc")
    # SBC 301-2018 Table 11.4-1 / 11.4-2 (ASCE 7-16 values), class D (C23's site coefficients).
    fa, fv, used = sh.site_factors(0.6, 0.25, "SD", pack)
    assert fa == pytest.approx(1.4 - 0.1 / 0.25 * 0.2)
    assert fv == pytest.approx(2.1) and used == "SD"
    assert sh.site_factors(0.1, 0.05, "SD", pack) == (1.6, 2.4, "SD")  # held below
    assert sh.site_factors(0.6, 0.25, "SF", pack)[2] == "SE"  # SF reads SE meanwhile
    se = registry.load("indonesia-sni")
    assert sh.site_factors(1.5, 0.6, "SE", se)[:2] == (0.8, 2.0)  # SNI 1726:2019 Tabel 6, 7


def _settings(pack_id, location, site_class="SD", **site):
    from saengine.library.settings import ProjectSettings, default_project_settings

    base = default_project_settings("x").model_dump(mode="json", by_alias=True)
    base["codePack"] = pack_id
    base["wind"]["exposure"] = "C"
    base["site"].update({"location": location, "siteClass": site_class, **site})
    return ProjectSettings.model_validate(base)


def test_saudi_town_values_give_sds_and_sd1():
    from saengine.library.settings import check, derived

    settings = _settings("saudi-sbc", "jeddah")
    with code_context.using(registry.load("saudi-sbc")):
        values = derived(settings)
        problems = check(settings)
    z = values["Z"]
    # Jeddah SS 0.24, S1 0.07 (VERIFY S1): Fa 1.6, Fv 2.4; SDS = 2/3 Fa SS, SD1 = 2/3 Fv S1.
    assert isinstance(z, sh.SpectralHazard)
    assert float(z) == pytest.approx(2 / 3 * 1.6 * 0.24, rel=1e-6)
    assert z.sd1 == pytest.approx(2 / 3 * 2.4 * 0.07, rel=1e-6)
    assert z.s1 == 0.07 and "Fa = 1.6" in z.source
    assert values["zone"] == 2  # SDS >= 0.167, SD1 >= 0.067: the second band (SDC B)
    assert values["windSpeed"] == 47.0
    assert not any(p.startswith("site.spectral") for p in problems)
    # The project's entered SDS, SD1 still come first.
    entered = _settings("saudi-sbc", "jeddah", spectral={"sds": 0.5, "sd1": 0.2})
    with code_context.using(registry.load("saudi-sbc")):
        assert float(derived(entered)["Z"]) == 0.5


def test_indonesia_town_carries_tl():
    from saengine.library.settings import derived

    with code_context.using(registry.load("indonesia-sni")):
        z = derived(_settings("indonesia-sni", "padang"))["Z"]
    # Padang SS 1.55, S1 0.65 (VERIFY I1), SD: Fa 1.0, Fv 1.7; TL 20 s (VERIFY I2).
    assert float(z) == pytest.approx(2 / 3 * 1.0 * 1.55, rel=1e-6)
    assert z.sd1 == pytest.approx(2 / 3 * 1.7 * 0.65, rel=1e-6)
    assert z.tl == 20.0


# ───────────────────────────── the ubc97 method ─────────────────────────────


def test_ubc97_coefficients_and_bounds():
    from saengine.library.settings import derived

    pack = registry.load("philippines-nscp")
    with code_context.using(pack):
        z = derived(_settings("philippines-nscp", "metroManila"))["Z"]
        # NSCP 2015 Tables 208-7 / 208-8, zone 4, SD, Na = Nv = 1.0: Ca 0.44, Cv 0.64.
        assert float(z) == pytest.approx(2.5 * 0.44)
        assert z.sd1 == pytest.approx(0.64)
        assert z.zone == 4 and sh.band(z) == 4 and z.label == "seismic coefficients"
        assert "Ca = 0.44" in sh.describe(z)
        # Figure 208-3: Ca at T = 0, 2.5 Ca on the plateau, Cv / T beyond Ts.
        assert sh.two_period(0.0, z) == pytest.approx(0.44)
        assert sh.two_period(1.0, z) == pytest.approx(0.64)
        # Eqs 208-8 to 208-11 with R 8.5, I 1.0.
        assert sh.response_coefficient(0.5, z, 1.0, 8.5) == pytest.approx(1.1 / 8.5)
        assert sh.response_coefficient(1.5, z, 1.0, 8.5) == pytest.approx(0.64 / (1.5 * 8.5))
        assert sh.response_coefficient(4.0, z, 1.0, 8.5) == pytest.approx(0.11 * 0.44)
        assert sh.period_upper_factor(z) == 1.3  # zone 4
    # Source type A at 5 km (Tables 208-5, 208-6): Na 1.2, Nv 1.6.
    near = _settings(
        "philippines-nscp", "metroManila", spectral={"sourceType": "A", "sourceDistance": 5.0}
    )
    with code_context.using(pack):
        z = derived(near)["Z"]
        assert float(z) == pytest.approx(2.5 * 0.44 * 1.2)
        assert z.sd1 == pytest.approx(0.64 * 1.6)
        assert z.nearFloor == pytest.approx(0.8 * 0.4 * 1.6)
        assert sh.response_coefficient(6.0, z, 1.0, 8.5) == pytest.approx(0.8 * 0.4 * 1.6 / 8.5)
    assert pickle.loads(pickle.dumps(z)).nearFloor == z.nearFloor


def test_ubc97_zones_and_categories():
    from saengine.library.settings import check, derived, design_category

    pack = registry.load("pakistan-bcp")
    with code_context.using(pack):
        quetta = _settings("pakistan-bcp", "quetta")
        z = derived(quetta)["Z"]
        # BCP SP-2007 zone 3 (id 4), Z 0.3, SD: Ca 0.36, Cv 0.54; no near-source factors.
        assert float(z) == pytest.approx(2.5 * 0.36) and z.sd1 == pytest.approx(0.54)
        assert z.nearFloor is None and sh.period_upper_factor(z) == 1.4
        assert design_category(quetta)["sdc"] == "D"
        assert design_category(_settings("pakistan-bcp", "islamabad"))["sdc"] == "C"
        # An entered Z between columns: Ca, Cv linear, the nearest zone.
        custom = _settings("pakistan-bcp", "custom", zoneCoefficient=0.25, windSpeed=45.0)
        z = derived(custom)["Z"]
        assert float(z) == pytest.approx(2.5 * (0.28 + 0.36) / 2)
        assert not any(p.startswith("site.zoneCoefficient") for p in check(custom))
        assert any(
            p.startswith("site.zoneCoefficient")
            for p in check(_settings("pakistan-bcp", "custom", windSpeed=45.0))
        )
    with code_context.using(registry.load("philippines-nscp")):
        manila = _settings("philippines-nscp", "metroManila")
        assert any("near-source" in p for p in check(manila))
        palawan = _settings("philippines-nscp", "palawan")
        assert design_category(palawan)["sdc"] == "C"
        assert derived(palawan)["Z"].sd1 == pytest.approx(0.40)  # zone 2, SD: Cv 0.40


def test_pack_choices_name_the_zones():
    from saengine.library.settings import pack_choices

    labels = {c["id"]: c["label"] for c in pack_choices(registry.load("pakistan-bcp"))["locations"]}
    assert labels["lahore"].startswith("Lahore (zone 2A, Z 0.15")
    labels = {c["id"]: c["label"] for c in pack_choices(registry.load("saudi-sbc"))["locations"]}
    assert labels["haql"].startswith("Haql (zone 0, SS 1, S1 0.33, V 45")


def test_local_bars_and_clause_names():
    saudi = registry.load("saudi-sbc")
    assert saudi.table("concrete").barDiameters["all"][:3] == [8.0, 10.0, 12.0]
    assert saudi.table("concrete").barNames == {}
    assert saudi.table("barSchedule").standard == "bs8666"
    assert saudi.clause_code("citations", "barDevelopment") == "SBC 304-2018"
    nscp = registry.load("philippines-nscp")
    assert nscp.table("citations").clauses["barDevelopment"] == "425.4.2"
    assert nscp.table("barSchedule").standards["aci315"].stockLength == 12000.0
    sni = registry.load("indonesia-sni")
    assert sni.table("concrete").barNames["13"] == "D13"
    assert sni.table("wind").kzFactor == 2.01  # SNI 1727:2020 (ASCE 7-16 form)
    assert registry.load("pakistan-bcp").table("seismic").systems["rcSmf"].R == 8.5


# ───────────────────────────── generated buildings ─────────────────────────────


def _derive(tmp_path, spec, site=None):
    from saengine.pipeline.project import open_project
    from saengine.pipeline.run_all import DERIVATION_INPUTS
    from saengine.project.new_building import create_building
    from saengine.rpc import handlers

    base = {
        "name": "C16 Frame",
        "gridsX": [6000, 6000],
        "gridsY": [5000, 5000],
        "storyCount": 3,
        "typicalHeight": 3200,
        "system": "rcFrame",
        "lateralSizing": "gravity",
        "siteClass": "SD",
        "siteClassSource": "entered",
        "windExposure": "C",
    }
    root = Path(create_building({**base, **spec}, tmp_path)["root"])
    path = root / "02 Project Settings/project-settings.json"
    settings = json.loads(path.read_text(encoding="utf-8"))
    for key, value in (site or {}).items():
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


@pytest.mark.parametrize(
    ("pack_id", "location"),
    [
        ("saudi-sbc", "jeddah"),
        ("indonesia-sni", "jakarta"),
        ("pakistan-bcp", "quetta"),
        ("philippines-nscp", "metroManila"),
    ],
)
def test_building_derives(tmp_path, pack_id, location):
    settings, out = _derive(tmp_path, {"codePack": pack_id, "location": location})
    assert settings["codePack"] == pack_id and settings["site"]["location"] == location
    summary = out["summary"]
    assert summary["seismic"]["EX"]["Sa_g"] > 0
    assert summary["wind_X_kN"] > 0
    assert "spectral" in summary


def test_ubc97_building_base_shear(tmp_path):
    _, out = _derive(tmp_path, {"codePack": "philippines-nscp", "location": "metroManila"})
    summary = out["summary"]
    assert "Ca = 0.44" in summary["spectral"]
    notes = " ".join(out["notes"])
    assert "the site's seismic coefficients" in notes
    # V = Cs W with Cs = min(2.5 Ca / R, Cv / (R T)) at least 0.11 Ca, 0.8 Z Nv / R (I = 1).
    t = summary["period_s"]
    r = 8.5  # the special moment frame zone 4 needs (D)
    expected = max(min(1.1 / r, 0.64 / (r * t)), 0.11 * 0.44, 0.8 * 0.4 / r)
    assert summary["Sa_g"] == pytest.approx(expected, rel=1e-6)

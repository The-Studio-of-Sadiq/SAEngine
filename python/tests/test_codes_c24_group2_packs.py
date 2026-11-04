"""Alpha 9 track C24: the group 2 country packs (Korea KDS 41, Iran Standard 2800, Egypt ECP
201 / 203, South Africa SANS 10160 / 10100, Brazil NBR, Chile NCh 433 / 430, Peru E.030 /
E.060) and the generic mechanisms they brought, all default off:

- a shape branch's divisor 1 + d (t0 / T)^m and negative powers (NCh 433 Eq 6-10:
  α = (1 + 4.5 (T/T0)^p) / (1 + (T/T0)^3));
- ``shapeFactors.ductilityForm`` "periodRatio" (NCh 433 Eq 6-11: R* = 1 + T / (0.10 T0 + T/R0));
- ``shapeFactors.soilFactors`` (E.030 Table 3: S by soil profile and Z);
- ``shapeFactors.leastSoilShare`` and ``capByDuctility`` (E.030 C/R ≥ 0.11; NCh 433 Cmin and
  Cmax).

The values pinned are the packs' (see each pack's VERIFY.md for the clause and how sure each
is). Written in the week of no test runs (owner, 2026-11-05): not run yet.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.fem import spectral_hazard as sh

PACKS = {
    "korea-kds": ["korea-kds", "aci318-asce7-22", "bnbc2020"],
    "iran-2800": ["iran-2800", "aci318-asce7-22", "bnbc2020"],
    "peru-e030": ["peru-e030", "aci318-asce7-22", "bnbc2020"],
    "chile-nch": ["chile-nch", "aci318-asce7-22", "bnbc2020"],
    "brazil-nbr": ["brazil-nbr", "aci318-asce7-22", "bnbc2020"],
    "egypt-ecp": ["egypt-ecp", "bs8110", "bnbc2020"],
    "southafrica-sans": ["southafrica-sans", "eurocodes", "bnbc2020"],
}


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


def _settings(pack_id, location, site_class, **site):
    from saengine.library.settings import ProjectSettings, default_project_settings

    base = default_project_settings("x", pack_id).model_dump(mode="json", by_alias=True)
    base["codePack"] = pack_id
    base["site"].update({"location": location, "siteClass": site_class, **site})
    return ProjectSettings.model_validate(base)


def _rule(pack_id):
    return registry.load(pack_id).table("seismic").designSpectrum.shapeFactors


def _shape(pack_id, site_class):
    return registry.load(pack_id).table("seismic").siteClasses[site_class].shape


@pytest.mark.parametrize("pack_id", sorted(PACKS))
def test_pack_is_listed_sound_and_extends_its_base(pack_id):
    from saengine.library.settings import default_project_settings

    assert pack_id in [p.id for p in registry.list_packs()]
    pack = registry.load(pack_id)
    assert pack.broken == {}
    assert pack.chain == PACKS[pack_id]
    assert default_project_settings("P", pack_id).units.system == "SI"
    for name in ("README.md", "VERIFY.md"):
        assert (Path(pack.path) / name).is_file()


# ───────────────────────────── the generic mechanisms, default off ─────────────────────────────


def test_new_shape_fields_default_off_and_the_base_packs_keep_theirs():
    from saengine.codes.tables import ShapeBranch, ShapeFactorsRule
    from saengine.fem.spectra import ductility_factor, shape_factor, soil_factor

    branch = ShapeBranch(c=1.0, n=1.0, t0=1.0)
    assert branch.d == 0.0 and branch.m == 1.0
    assert shape_factor(2.0, [branch]) == pytest.approx(0.5)
    rule = ShapeFactorsRule(performance=[(1.0, 1.0)])
    assert rule.ductilityForm == "linear" and rule.soilFactors == {}
    assert rule.leastSoilShare is None and rule.capByDuctility == []
    assert soil_factor("C", 0.3, rule) == 1.0
    assert ductility_factor(0.5, 4.0, "C", rule) == 4.0
    # The packs that use shapeFactors already (AS 1170.4, NZS 1170.5, NBC 105) set none of them.
    for pack_id in ("australia-as", "newzealand-nzs", "nepal-nbc"):
        found = registry.load(pack_id).table("seismic").designSpectrum.shapeFactors
        assert found.ductilityForm == "linear" and not found.soilFactors
        assert found.leastSoilShare is None and not found.capByDuctility


def test_a_positive_power_at_zero_period_stays_infinite():
    from saengine.codes.tables import ShapeBranch
    from saengine.fem.spectra import shape_factor

    # As before C24: c (t0 / T)^n at T = 0 is infinite (capped by ``most``).
    assert shape_factor(0.0, [ShapeBranch(c=1.0, n=1.0, t0=1.0, most=3.0)]) == 3.0
    # A negative power is a power of T / t0: 0 at T = 0.
    assert shape_factor(0.0, [ShapeBranch(a=1.0, c=4.5, n=-2.0, t0=0.15, d=1.0, m=-3.0)]) == 1.0


# ───────────────────────────── Chile: NCh 433 + DS 61 ─────────────────────────────


def test_nch433_alpha_and_r_star():
    from saengine.fem.spectra import ductility_factor, shape_factor

    # α = (1 + 4.5 (T/T0)^p) / (1 + (T/T0)^3), soil B: T0 0.30 s, p 1.5 (DS 61 Table 6.3).
    x = 0.5 / 0.3
    assert shape_factor(0.5, _shape("chile-nch", "B")) == pytest.approx(
        (1 + 4.5 * x**1.5) / (1 + x**3), rel=1e-9
    )
    assert shape_factor(0.3, _shape("chile-nch", "B")) == pytest.approx(2.75)  # at T0
    # R* = 1 + T / (0.10 T0 + T / R0) (NCh 433 Eq 6-11), R0 = 11.
    assert ductility_factor(0.5, 11.0, "B", _rule("chile-nch")) == pytest.approx(
        1 + 0.5 / (0.03 + 0.5 / 11.0)
    )
    assert ductility_factor(0.0, 11.0, "B", _rule("chile-nch")) == pytest.approx(1.0)


def test_nch433_design_spectrum_between_cmin_and_cmax():
    from saengine.fem import loads as fl

    pack = registry.load("chile-nch")
    with code_context.using(pack):
        # Soil B (S 1.00), A0 0.4 g, R0 11, I 1.0, T = 0.5 s: within the bounds.
        x = 0.5 / 0.3
        alpha = (1 + 4.5 * x**1.5) / (1 + x**3)
        r_star = 1 + 0.5 / (0.03 + 0.5 / 11.0)
        mid = fl.design_acceleration(0.5, "B", 0.4, 1.0, 11.0)
        # Soil A (S 0.90) at T0 = 0.15 s: α 2.75, R* 6.24 → 0.159 > Cmax 0.35 S A0 = 0.126.
        capped = fl.design_acceleration(0.15, "A", 0.4, 1.0, 11.0)
        # Long period: α tends to 0 → Cmin = A0 S / 6 = 0.06 (S 0.90).
        floor = fl.design_acceleration(6.0, "A", 0.4, 1.0, 11.0)
        # Confined masonry (R0 4): Cmax 0.55 S A0.
        masonry = fl.design_acceleration(0.15, "A", 0.4, 1.0, 4.0)
    assert mid == pytest.approx(0.4 * 1.0 * alpha / r_star, rel=1e-9)
    assert capped == pytest.approx(0.35 * 0.4 * 0.9)
    assert floor == pytest.approx(0.4 * 0.9 / 6.0, rel=1e-5)
    r4 = 1 + 0.15 / (0.015 + 0.15 / 4.0)
    assert masonry == pytest.approx(min(0.4 * 0.9 * 2.75 / r4, 0.55 * 0.4 * 0.9), rel=1e-9)


def test_nch_values():
    from saengine.library.settings import derived

    pack = registry.load("chile-nch")
    seismic = pack.table("seismic")
    assert seismic.allowableDrift["II"] == 0.002 and seismic.driftAmplification == "designForces"
    assert seismic.systems["rcSpecialWallFrame"].R == 11.0
    assert pack.table("detailing").walls["driftMin"] == 0.007
    assert pack.table("detailing").walls["driftFactor"] == 1.0
    strength = {c.id: c.factors for c in pack.table("combinations").strength}
    assert strength["5E"]["E"] == 1.4 and strength["7E"]["D"] == 0.9
    with code_context.using(pack):
        values = derived(_settings("chile-nch", "santiago", "C"))
    assert values["Z"] == pytest.approx(0.3)  # Santiago zone 2, A0 0.30 g


# ───────────────────────────── Peru: E.030 2018 ─────────────────────────────


def test_e030_soil_factor_by_zone():
    from saengine.fem.spectra import soil_factor

    rule = _rule("peru-e030")
    assert soil_factor("S2", 0.45, rule) == 1.05
    assert soil_factor("S2", 0.35, rule) == 1.15
    assert soil_factor("S2", 0.25, rule) == 1.2
    assert soil_factor("S2", 0.10, rule) == 1.6
    assert soil_factor("S3", 0.10, rule) == 2.0
    assert soil_factor("S0", 0.45, rule) == 0.8


def test_e030_amplification_and_design_spectrum():
    from saengine.fem import loads as fl
    from saengine.fem.spectra import shape_factor

    s2 = _shape("peru-e030", "S2")  # TP 0.6, TL 2.0
    assert shape_factor(0.06, s2) == pytest.approx(1 + 7.5 * 0.06 / 0.6)  # modal rise
    assert shape_factor(0.06, s2, static=True) == pytest.approx(2.5)  # static plateau
    assert shape_factor(1.0, s2) == pytest.approx(2.5 * 0.6 / 1.0)
    assert shape_factor(3.0, s2) == pytest.approx(2.5 * 0.6 * 2.0 / 9.0, rel=1e-4)
    with code_context.using(registry.load("peru-e030")):
        # Lima (Z 0.45), S2 (S 1.05), U 1.0, R0 8: Sa = Z U C S / R.
        plateau = fl.design_acceleration(0.5, "S2", 0.45, 1.0, 8.0, static=True)
        # Long period: C/R ≥ 0.11 → Sa ≥ 0.11 Z U S.
        floor = fl.design_acceleration(4.0, "S2", 0.45, 1.0, 8.0)
    assert plateau == pytest.approx(0.45 * 2.5 * 1.05 / 8.0)
    assert floor == pytest.approx(0.11 * 0.45 * 1.05)


def test_e030_values():
    pack = registry.load("peru-e030")
    seismic = pack.table("seismic")
    assert seismic.systems["rcSmf"].R == 8.0 and seismic.systems["rcSmf"].Cd == 6.0
    rows = {row.id: row.limits["II"] for row in seismic.driftLimits}
    assert rows == {"masonry": 0.005, "concrete": 0.007}
    assert seismic.allowableDrift["II"] == 0.01
    assert seismic.periodCoefficients["concreteMomentFrame"].Ct == pytest.approx(1 / 35, rel=1e-4)
    phi = pack.table("factors").phi
    assert phi.compressionTied == 0.7 and phi.shear == 0.85 and phi.tension == 0.9
    strength = {c.id: c.factors for c in pack.table("combinations").strength}
    assert strength["1"]["D"] == 1.4 and strength["1"]["L"] == 1.7
    assert strength["4E"]["D"] == 1.25
    assert pack.table("occupancyCategories").categories["IV"].seismicImportance == 1.5
    assert pack.table("concrete").barNames["16"] == '5/8"'


# ───────────────────────────── Iran: Standard 2800 ─────────────────────────────


def test_2800_reflection_factor_b1_times_n():
    from saengine.fem.spectra import shape_factor

    # Soil II (T0 0.1, Ts 0.5, S0 1.0, S 1.5), zones of very high and high hazard.
    shape = _shape("iran-2800", "II")
    assert shape_factor(0.0, shape) == pytest.approx(1.0)  # S0
    assert shape_factor(0.3, shape) == pytest.approx(2.5)  # S + 1
    t = 2.0  # B1 (S + 1) Ts / T × N, N = 1 + 0.7 (T - Ts) / (4 - Ts)
    assert shape_factor(t, shape) == pytest.approx(2.5 * 0.5 / t * (1 + 0.7 * 1.5 / 3.5), rel=1e-4)
    assert shape_factor(5.0, shape) == pytest.approx(2.5 * 0.5 / 5.0 * 1.7, rel=1e-4)
    low = _shape("iran-2800", "IIL")  # N up to 1.4 in the moderate and low zones
    assert shape_factor(5.0, low) == pytest.approx(2.5 * 0.5 / 5.0 * 1.4, rel=1e-4)


def test_2800_base_shear_and_minimum():
    from saengine.fem import loads as fl
    from saengine.library.settings import derived

    pack = registry.load("iran-2800")
    with code_context.using(pack):
        values = derived(_settings("iran-2800", "tehran", "III"))
        # C = A B I / Ru on the plateau: A 0.35, B 2.75, Ru 7.5.
        plateau = fl.design_acceleration(0.5, "III", 0.35, 1.0, 7.5)
        # At least 0.12 A I.
        least = fl.design_acceleration(3.9, "I", 0.35, 1.0, 7.5)
    assert values["Z"] == pytest.approx(0.35) and values["R"] == 7.5
    assert plateau == pytest.approx(0.35 * 2.75 / 7.5)
    assert least == pytest.approx(0.12 * 0.35)
    methods = pack.table("concreteMethods").ultimate
    assert methods.gammaC == pytest.approx(1 / 0.65) and methods.gammaS == pytest.approx(1 / 0.85)
    assert pack.table("occupancyCategories").categories["IV"].seismicImportance == 1.4


# ───────────────────────────── Korea: KDS 41 17 00 ─────────────────────────────


def test_kds_sds_sd1_from_s():
    from saengine.library.settings import derived

    with code_context.using(registry.load("korea-kds")):
        values = derived(_settings("korea-kds", "seoul", "S4"))
    z = values["Z"]
    # S = 0.22 (zone I, 2400 years): SS 0.55, S1 0.22; S4: Fa 1.36 (between 1.4 and 1.2),
    # Fv 1.96 (between 2.0 and 1.8); SDS = 2/3 Fa SS, SD1 = 2/3 Fv S1.
    assert isinstance(z, sh.SpectralHazard)
    assert float(z) == pytest.approx(2 / 3 * 1.36 * 0.55, rel=1e-6)
    assert z.sd1 == pytest.approx(2 / 3 * 1.96 * 0.22, rel=1e-6)


def test_kds_values():
    pack = registry.load("korea-kds")
    phi = pack.table("factors").phi
    assert phi.tension == 0.85 and phi.compressionSpiral == 0.7 and phi.plain == 0.55
    assert phi.shear == 0.75 and phi.compressionTied == 0.65  # the base pack's
    assert pack.table("concrete").barNames["13"] == "D13"
    categories = pack.table("occupancyCategories").categories
    assert categories["III"].seismicImportance == 1.2
    assert categories["IV"].seismicImportance == 1.5
    assert pack.table("locations").locations["jeju"].ss == 0.35


# ───────────────────────────── Brazil: NBR 15421, 6123, 6118 ─────────────────────────────


def test_nbr15421_spectrum_from_ag():
    from saengine.library.settings import derived

    with code_context.using(registry.load("brazil-nbr")):
        values = derived(_settings("brazil-nbr", "natal", "SD"))
    z = values["Z"]
    # ag 0.10: Ca 1.6 (class D, ag ≤ 0.10), Cv 2.4; SDS = 2.5 Ca ag, SD1 = Cv ag (no 2/3).
    assert float(z) == pytest.approx(2.5 * 1.6 * 0.10, rel=1e-6)
    assert z.sd1 == pytest.approx(2.4 * 0.10, rel=1e-6)
    with code_context.using(registry.load("brazil-nbr")):
        cs = sh.response_coefficient(3.0, sh.SpectralHazard(0.0625, 0.02, 0.025, None), 1.0, 8.0)
    assert cs == pytest.approx(0.01)  # Cs at least 0.01 (no 0.044 SDS term)


def test_nbr6123_speed_factors():
    pack = registry.load("brazil-nbr")
    wind = pack.table("wind")
    assert wind.method == "speedFactors" and wind.speedFactors.airFactor == 0.613
    s2 = dict(wind.speedFactors.heightFactors["II"])
    assert s2[10] == pytest.approx(0.98)  # b Fr (z/10)^p = 1.00 × 0.98 at 10 m
    assert s2[50] == pytest.approx(0.98 * 5**0.09, abs=1e-3)
    assert pack.table("occupancyCategories").categories["IV"].windImportance == 1.1  # S3


def test_nbr6118_concrete():
    pack = registry.load("brazil-nbr")
    methods = pack.table("concreteMethods")
    assert methods.ultimate.gammaC == 1.4 and methods.ultimate.gammaS == 1.15
    assert methods.ultimate.alphaCC == 0.85
    assert methods.shear.method == "tabulatedStress"
    c30 = methods.shear.grades.index(30)
    assert methods.shear.tauC[0][c30] == pytest.approx(0.09 * 30 ** (2 / 3), abs=1e-4)
    assert methods.shear.maxStress[c30] == pytest.approx(0.27 * (1 - 30 / 250) * 30 / 1.4, abs=1e-4)
    assert pack.table("concrete").barNames["12.5"] == "Ø12,5"
    strength = {c.id: c.factors for c in pack.table("combinations").strength}
    assert strength["1"]["D"] == 1.4 and strength["1"]["L"] == 1.4


# ───────────────────────────── Egypt: ECP 201, ECP 203 ─────────────────────────────


def test_ecp201_spectrum():
    from saengine.fem import loads as fl

    pack = registry.load("egypt-ecp")
    seismic = pack.table("seismic")
    assert seismic.designSpectrum.method == "behaviourFactor"
    assert seismic.siteClasses["C"].TC == 0.6  # Type 2 spectrum taken
    with code_context.using(pack):
        # Cairo ag 0.15, class C (S 1.15), γI 1.0, R 7, plateau: ag γI S 2.5 / R.
        sd = fl.design_acceleration(0.5, "C", 0.15, 1.0, 7.0)
        low = fl.design_acceleration(4.0, "C", 0.15, 1.0, 7.0)
    assert sd == pytest.approx(0.15 * 1.15 * 2.5 / 7.0)
    assert low == pytest.approx(0.2 * 0.15)  # β = 0.20


def test_ecp203_concrete():
    pack = registry.load("egypt-ecp")
    ultimate = pack.table("concreteMethods").ultimate
    assert ultimate.gammaC == 1.5 and ultimate.gammaS == 1.15 and ultimate.alphaCC == 0.67
    assert ultimate.relations.lam.base == 0.8 and ultimate.relations.eta.base == 1.0
    assert ultimate.eccentricityMax is None and ultimate.eccentricityMin == 20
    assert ultimate.axialShares == (0.35, 0.67)
    shear = pack.table("concreteMethods").shear
    assert shear.depthFactor is None
    c25 = shear.grades.index(25)
    assert shear.tauC[0][c25] == pytest.approx(0.12 * (25 / 1.5) ** 0.5, abs=1e-4)
    strength = {c.id: c.factors for c in pack.table("combinations").strength}
    assert strength["2W"]["D"] == pytest.approx(1.12) and strength["2W"]["W"] == pytest.approx(1.28)


# ───────────────────────────── South Africa: SANS 10160 ─────────────────────────────


def test_sans_values():
    pack = registry.load("southafrica-sans")
    seismic = pack.table("seismic")
    assert seismic.spectrumType == "SANS" and seismic.siteClasses["2"].S == 1.35
    assert seismic.spectrumTypeGuidance is None
    combinations = pack.table("combinations")
    assert combinations.strengthSet == "sans"
    assert [c.id for c in combinations.strength][:2] == ["STR-P", "STR-Q"]
    assert "6.10" in combinations.strengthSets  # the parent's sets stay selectable
    assert pack.table("concreteMethods").ultimate.alphaCC == 0.85
    assert pack.table("zoneCoefficients").zones[2] == 0.1


def test_the_parents_keep_their_values():
    assert registry.load("eurocodes").table("concreteMethods").ultimate.alphaCC == 1.0
    assert registry.load("eurocodes").table("combinations").strengthSet == "6.10"
    bs = registry.load("bs8110").table("concreteMethods").ultimate
    assert bs.gammaS == 1.05 and bs.eccentricityMax == 20
    assert registry.load("aci318-asce7-22").table("factors").phi.tension == 0.9


# ───────────────────────────── generated buildings ─────────────────────────────


def _derive(tmp_path, spec):
    from saengine.pipeline.project import open_project
    from saengine.pipeline.run_all import DERIVATION_INPUTS
    from saengine.project.new_building import create_building
    from saengine.rpc import handlers

    base = {
        "name": "C24 Frame",
        "gridsX": [6000, 6000],
        "gridsY": [5000, 5000],
        "storyCount": 3,
        "typicalHeight": 3200,
        "system": "rcFrame",
        "lateralSizing": "gravity",
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


@pytest.mark.parametrize(
    ("pack_id", "location", "site_class", "exposure"),
    [
        ("korea-kds", "seoul", "S4", "C"),
        ("iran-2800", "tehran", "III", "C"),
        ("peru-e030", "lima", "S2", "C"),
        ("chile-nch", "santiago", "C", "C"),
        ("brazil-nbr", "saopaulo", "SD", "II"),
        ("egypt-ecp", "cairo", "C", "country10"),
        ("southafrica-sans", "johannesburg", "2", "II"),
    ],
)
def test_building_derives(tmp_path, pack_id, location, site_class, exposure):
    settings, out = _derive(
        tmp_path,
        {
            "codePack": pack_id,
            "location": location,
            "siteClass": site_class,
            "windExposure": exposure,
        },
    )
    assert settings["codePack"] == pack_id and settings["site"]["location"] == location
    summary = out["summary"]
    assert summary["wind_X_kN"] > 0
    assert summary["seismic"]["EX"]["Sa_g"] > 0


def test_peru_building_base_shear_uses_the_soil_factor(tmp_path):
    _, out = _derive(
        tmp_path,
        {"codePack": "peru-e030", "location": "lima", "siteClass": "S2", "windExposure": "C"},
    )
    summary = out["summary"]
    t = summary["period_s"]
    # Lima Z 0.45, S2 (S 1.05, TP 0.6, TL 2.0), U 1.0, R0 8; the static method: C = 2.5 to TP.
    c = 2.5 if t <= 0.6 else 2.5 * 0.6 / t if t <= 2.0 else 2.5 * 0.6 * 2.0 / t**2
    assert summary["Sa_g"] == pytest.approx(max(0.45 * c * 1.05 / 8.0, 0.11 * 0.45 * 1.05))

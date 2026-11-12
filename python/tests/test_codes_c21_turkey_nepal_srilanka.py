"""Alpha 9 track C21: the Turkey (TBDY 2018, TS 500), Nepal (NBC 105:2020) and Sri Lanka
(Eurocodes with the Sri Lankan wind zones) packs and the generic mechanisms they brought:

- ``designSpectrum.shortPeriodReduction`` (method ``overstrengthRamp``): Ra(T) = D + (R/I - D)
  T/TS below TS (TBDY 2018 Eq 4.1);
- ``seismic.driftServiceRatio`` (λ of λ δ/h ≤ limit) and the ``concrete`` condition of a
  drift row (κ of TBDY 2018 4.9.1.3);
- ``seismic.performanceBased``: the building height class and the performance-based design
  requirement (TBDY 2018 3.3-3.4, Bolum 13);
- ``lateralForce.topForce.storeyFactor`` (ΔFN = 0.0075 N Vt, TBDY 2018 4.7.2.2);
- the second power term of a spectral shape branch (NBC 105:2020 Eq 4.1(1)).

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
    "turkey-tbdy": ["turkey-tbdy", "aci318-asce7-22", "bnbc2020"],
    "nepal-nbc": ["nepal-nbc", "is-codes", "bnbc2020"],
    "srilanka": ["srilanka", "eurocodes", "bnbc2020"],
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


def test_the_base_packs_keep_their_spectra():
    us = registry.load("aci318-asce7-22").table("seismic")
    assert us.designSpectrum.shortPeriodReduction is None
    assert us.driftServiceRatio is None and us.performanceBased is None
    assert registry.load("bnbc2020").table("seismic").performanceBased is None
    assert registry.load("is-codes").table("seismic").designSpectrum.method == "reducedElastic"


# ───────────────────────────── Turkey: TBDY 2018 ─────────────────────────────


def test_tbdy_site_coefficients_and_category():
    from saengine.library.settings import derived

    settings = _settings("turkey-tbdy", "istanbul", "ZC")
    with code_context.using(registry.load("turkey-tbdy")):
        values = derived(settings)
    z = values["Z"]
    # Istanbul (example) SS 0.90, S1 0.25 (VERIFY T1); ZC: FS 1.2 (Tablo 2.1), F1 1.5 (Tablo 2.2);
    # SDS = SS FS, SD1 = S1 F1 (no 2/3: designShare 1.0); TL = 6 s.
    assert isinstance(z, sh.SpectralHazard)
    assert float(z) == pytest.approx(0.9 * 1.2, rel=1e-6)
    assert z.sd1 == pytest.approx(0.25 * 1.5, rel=1e-6)
    assert z.tl == 6.0
    assert values["zone"] == 4  # SDS ≥ 0.75: DTS 1 (SAEngine's category D)
    assert values["R"] == 8.0 and values["omega"] == 3.0  # Tablo 4.1 A11 R = 8, D = 3


def test_tbdy_elastic_spectrum_shape():
    hazard = sh.SpectralHazard(1.08, 0.375, 0.25, 6.0)
    pack = registry.load("turkey-tbdy")
    ts = 0.375 / 1.08
    with code_context.using(pack):
        assert sh.two_period(0.0, hazard) == pytest.approx(0.4 * 1.08)  # 0.4 SDS at T = 0
        assert sh.two_period(0.2 * ts, hazard) == pytest.approx(1.08)  # SDS at TA
        assert sh.two_period(1.0, hazard) == pytest.approx(0.375)  # SD1 / T
        assert sh.two_period(8.0, hazard) == pytest.approx(0.375 * 6.0 / 64.0)  # beyond TL


def test_tbdy_reduction_ramps_from_d_to_r_over_i():
    hazard = sh.SpectralHazard(1.08, 0.375, 0.25, 6.0)
    ts = hazard.ts
    with code_context.using(registry.load("turkey-tbdy")):
        # TBDY 2018 Eq 4.1: Ra = D + (R/I - D) T/TB below TB, R/I beyond (R 8, D 3, I 1).
        assert sh.reduction(0.0, hazard, 1.0, 8.0, 3.0) == pytest.approx(3.0)
        assert sh.reduction(0.5 * ts, hazard, 1.0, 8.0, 3.0) == pytest.approx(5.5)
        assert sh.reduction(2.0 * ts, hazard, 1.0, 8.0, 3.0) == pytest.approx(8.0)
        # No D given (an elastic or a sizing spectrum): R/I.
        assert sh.reduction(0.1, hazard, 1.5, 8.0, None) == pytest.approx(8.0 / 1.5)
        # An elastic spectrum (R/I ≤ 1) is never reduced.
        assert sh.reduction(0.1, hazard, 1.0, 1.0, 3.0) == pytest.approx(1.0)
    with code_context.using(registry.load("aci318-asce7-22")):
        assert sh.reduction(0.0, hazard, 1.0, 8.0, 3.0) == pytest.approx(8.0)  # no block


def test_tbdy_equivalent_static_coefficient():
    hazard = sh.SpectralHazard(1.08, 0.375, 0.25, 6.0)
    with code_context.using(registry.load("turkey-tbdy")):
        # T = 1.0 s > TB: SaR = SD1 / T / (R/I) = 0.375 / 8, above 0.04 I SDS = 0.0432.
        cs = sh.response_coefficient(1.0, hazard, 1.0, 8.0, overstrength=3.0)
        assert cs == pytest.approx(0.375 / 8.0)
        # T = 2.0 s: 0.375 / 2 / 8 = 0.0234 < 0.04 SDS: the least value of 4.7.1.1.
        cs = sh.response_coefficient(2.0, hazard, 1.0, 8.0, overstrength=3.0)
        assert cs == pytest.approx(0.04 * 1.08)
        # Below TB the plateau over Ra(T): T = TB / 2, Ra = 5.5.
        t = 0.5 * hazard.ts
        cs = sh.response_coefficient(t, hazard, 1.0, 8.0, overstrength=3.0)
        assert cs == pytest.approx(1.08 / 5.5)


def test_tbdy_design_spectrum_with_and_without_d():
    from saengine.fem import loads as fl

    hazard = sh.SpectralHazard(1.08, 0.375, 0.25, 6.0)
    t = 0.5 * hazard.ts
    with code_context.using(registry.load("turkey-tbdy")):
        reduced = fl.design_acceleration(t, "ZC", hazard, 1.0, 8.0, overstrength=3.0)
        plain = fl.design_acceleration(t, "ZC", hazard, 1.0, 8.0)
    assert reduced == pytest.approx(1.08 / 5.5)
    assert plain == pytest.approx(1.08 / 8.0)


def test_tbdy_drift_limits_with_kappa_and_lambda():
    from saengine.fem.seismic_design import drift_limit

    with code_context.using(registry.load("turkey-tbdy")):
        concrete = drift_limit("II", "D", "rcSmf")
        steel = drift_limit("II", "D", "steelSmf")
        tolerant = drift_limit("II", "D", "rcSmf", tolerant=True)
        steel_tolerant = drift_limit("II", "D", "steelSmf", tolerant=True)
    # TBDY 2018 4.9.1.3: 0.008 κ (fixed infill) or 0.016 κ, κ = 1 concrete, 0.5 steel; λ = 1.0.
    assert concrete["ratio"] == pytest.approx(0.008) and concrete["row"] == "other"
    assert steel["ratio"] == pytest.approx(0.004) and steel["row"] == "steel"
    assert tolerant["ratio"] == pytest.approx(0.016)
    assert steel_tolerant["ratio"] == pytest.approx(0.008)
    assert "λ" in concrete["label"]


def test_drift_service_ratio_divides_the_limit():
    from saengine.codes.tables import DriftServiceRatio
    from saengine.fem import seismic_design

    pack = registry.load("turkey-tbdy")
    table = pack.table("seismic").model_copy(
        update={"driftServiceRatio": DriftServiceRatio(value=0.5)}
    )
    with code_context.using(pack):
        original = seismic_design._seismic
        seismic_design._seismic = lambda: table
        try:
            found = seismic_design.drift_limit("II", "D", "rcSmf")
        finally:
            seismic_design._seismic = original
    assert found["ratio"] == pytest.approx(0.016)  # 0.008 / λ, λ = 0.5


@pytest.mark.parametrize(
    ("height", "category", "expected"),
    [
        (75.0, "D", "1"),  # DTS 1-2: BYS 1 above 70 m
        (60.0, "D", "2"),
        (95.0, "C", "1"),  # DTS 3: above 91 m
        (95.0, "B", "2"),  # DTS 4: BYS 1 above 105 m
        (20.0, "D", "5"),
        (6.0, "D", "8"),
    ],
)
def test_tbdy_height_classes(height, category, expected):
    from saengine.fem import performance_requirements as pr

    block = pr.rules(registry.load("turkey-tbdy"))
    found = pr.height_class(height, category, block)
    assert found is not None and found.id == expected


def test_tbdy_tall_buildings_need_performance_based_design():
    from saengine.fem import performance_requirements as pr

    pack = registry.load("turkey-tbdy")
    tall = pr.requirements(80.0, "D", pack)
    assert tall is not None and [r.classes for r in tall["rules"]] == [["1"]]
    procedures = [o.procedure for o in tall["rules"][0].objectives]
    assert procedures == ["linear", "strength", "nonlinearHistory"]
    notes = pr.notes(80.0, "D", pack)
    assert any("BYS 1" in n for n in notes)
    assert any("Nonlinear time history" in n and "DD-1" in n for n in notes)
    low = pr.requirements(30.0, "D", pack)
    assert low is not None and low["rules"] == []
    # A pack without the block reports nothing (not covered).
    assert pr.notes(80.0, "D", registry.load("bnbc2020")) == []


def test_tbdy_top_force_by_storeys():
    from saengine.fem import loads as fl

    levels = [(3.0 * (i + 1), 1000.0) for i in range(10)]
    with code_context.using(registry.load("turkey-tbdy")):
        forces = fl.vertical_distribution(levels, 100.0, 1.0)
    # ΔFN = 0.0075 N Vt = 7.5 at the top; the rest linear in height (Fi ∝ mi Hi).
    total_h = sum(h for h, _ in levels)
    assert sum(forces) == pytest.approx(100.0)
    assert forces[-1] == pytest.approx(7.5 + 92.5 * 30.0 / total_h)
    assert forces[0] == pytest.approx(92.5 * 3.0 / total_h)


def test_top_force_by_period_unchanged():
    from saengine.codes.tables import TopForce

    rule = TopForce(periodFrom=0.7, factor=0.07, maxShare=0.25)
    assert rule.storeyFactor is None and rule.factor == 0.07


def test_tbdy_concrete_ts500_values():
    pack = registry.load("turkey-tbdy")
    methods = pack.table("concreteMethods")
    assert methods.ultimate.gammaC == 1.5 and methods.ultimate.gammaS == 1.15
    assert methods.ultimate.alphaCC == 0.85
    assert methods.shear.method == "tabulatedStress"
    # Vc = 0.8 × 0.65 fctd bw d, fctd = 0.35 √fck / 1.5: at C30 0.6646 MPa.
    c30 = methods.shear.grades.index(30)
    assert methods.shear.tauC[0][c30] == pytest.approx(0.52 * 0.35 * 30**0.5 / 1.5, abs=1e-4)
    assert methods.shear.maxStress[c30] == pytest.approx(0.22 * 30 / 1.5, abs=1e-4)
    assert methods.seismic.columns.strongColumn == 1.2
    assert methods.seismic.joints.gamma["4"] == 1.7
    assert pack.table("concrete").barNames["14"] == "Ø14"


# ───────────────────────────── Nepal: NBC 105:2020 ─────────────────────────────


@pytest.mark.parametrize(
    ("site_class", "period", "static", "expected"),
    [
        ("C", 0.05, False, 1.0 + 1.5 / 0.11 * 0.05),  # rising branch (modal)
        ("C", 0.05, True, 2.5),  # α below Ta for the equivalent static method
        ("C", 0.8, False, 2.5),  # plateau to Tc = 1.0
        ("C", 2.0, False, 2.5 * (1.8 + (1 - 1.8) * 0.25) * 0.25),  # α [K + (1-K)(Tc/T)²](Tc/T)²
        ("D", 1.0, False, 2.25),
        ("D", 4.0, False, 2.25 * (0.8 + 0.2 * 0.25) * 0.25),
    ],
)
def test_nbc105_spectral_shape_factor(site_class, period, static, expected):
    from saengine.fem.spectra import shape_factor

    shape = registry.load("nepal-nbc").table("seismic").siteClasses[site_class].shape
    assert shape_factor(period, shape, static) == pytest.approx(expected, rel=1e-4)


def test_nbc105_design_spectrum_and_town():
    from saengine.fem import loads as fl
    from saengine.library.settings import derived

    settings = _settings("nepal-nbc", "kathmandu", "C")
    pack = registry.load("nepal-nbc")
    with code_context.using(pack):
        values = derived(settings)
        # Cd(T) = Ch(T) Z I / (Rμ Ωu): RC MRF Rμ 4, Ωu 1.5 (R = 6), Kathmandu Z 0.35.
        cd = fl.design_acceleration(0.8, "C", 0.35, 1.0, 6.0)
    assert values["Z"] == pytest.approx(0.35)
    assert values["R"] == 6.0 and values["Cd"] == 4.0
    assert cd == pytest.approx(2.5 * 0.35 / 6.0, rel=1e-6)
    system = pack.table("seismic").systems["rcSmf"]
    assert system.Rd == 4.0 and system.Ro == 1.5
    # T1 = 1.25 kt H^(3/4), kt 0.075 (RC moment frames).
    assert pack.table("seismic").periodCoefficients["concreteMomentFrame"].Ct == 0.09375


def test_second_power_term_defaults_to_none():
    from saengine.codes.tables import ShapeBranch
    from saengine.fem.spectra import shape_factor

    branch = ShapeBranch(c=1.0, n=1.0, t0=1.0)
    assert branch.c2 == 0.0
    assert shape_factor(2.0, [branch]) == pytest.approx(0.5)


# ───────────────────────────── Sri Lanka ─────────────────────────────


def test_srilanka_wind_zones_and_no_seismic():
    from saengine.library.settings import derived

    pack = registry.load("srilanka")
    towns = pack.table("locations").locations
    # Zones 1-3: 49, 43, 33 m/s gusts / 1.53 (SAEngine practice, VERIFY S1-S3).
    assert towns["jaffna"].windSpeed == 32.0
    assert towns["anuradhapura"].windSpeed == 28.1
    assert towns["colombo"].windSpeed == 21.6
    settings = _settings("srilanka", "colombo", "SC")
    with code_context.using(pack):
        values = derived(settings)
    assert not values["Z"]
    assert values["windSpeed"] == pytest.approx(21.6)


# ───────────────────────────── generated buildings ─────────────────────────────


def _derive(tmp_path, spec):
    from saengine.pipeline.project import open_project
    from saengine.pipeline.run_all import DERIVATION_INPUTS
    from saengine.project.new_building import create_building
    from saengine.rpc import handlers

    base = {
        "name": "C21 Frame",
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
        ("turkey-tbdy", "istanbul", "ZC", "C"),
        ("nepal-nbc", "kathmandu", "C", "3"),
        ("srilanka", "colombo", "SC", "III"),
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
    if pack_id != "srilanka":  # Sri Lanka: no seismic design (zone 0)
        assert summary["seismic"]["EX"]["Sa_g"] > 0


def test_tbdy_building_base_shear_uses_the_reduction(tmp_path):
    _, out = _derive(
        tmp_path,
        {"codePack": "turkey-tbdy", "location": "istanbul", "siteClass": "ZC", "windExposure": "C"},
    )
    summary = out["summary"]
    assert "spectral" in summary
    t = summary["period_s"]
    sds, sd1 = 0.9 * 1.2, 0.25 * 1.5
    ts = sd1 / sds
    # rcSmf (R 8, D 3) in DTS 1 (D), I = 1: SaR(T) = Sae(T) / Ra(T), at least 0.04 SDS.
    if t < 0.2 * ts:
        sae = sds * (0.4 + 0.6 * t / (0.2 * ts))
    elif t <= ts:
        sae = sds
    else:
        sae = sd1 / t
    ra = 3.0 + (8.0 - 3.0) * t / ts if t < ts else 8.0
    assert summary["Sa_g"] == pytest.approx(max(sae / ra, 0.04 * sds), rel=1e-6)

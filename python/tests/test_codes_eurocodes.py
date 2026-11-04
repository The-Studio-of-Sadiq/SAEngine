"""The Eurocodes pack (``eurocodes``, loads and seismic, recommended values; alpha 9 track C4).

Pins the pack's values with their clauses (EN 1990, EN 1991-1-1, -1-3, -1-4, -1-7 Annex D,
EN 1998-1), the generic methods it picks (the behaviour-factor design spectrum, λ and the linear
distribution of the lateral force method, the peak velocity pressure, the area-and-storeys
reduction, roof snow, the design-drift θ and qd·de), a National Annex pack that extends it, and
a small generated building that derives its seismic and wind loads with it.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def ec():
    pack = registry.load("eurocodes")
    with code_context.using(pack):
        yield pack


# ───────────────────────────── the pack ─────────────────────────────


def test_pack_is_listed_sound_and_extends_the_default():
    ids = [p.id for p in registry.list_packs()]
    assert "eurocodes" in ids
    pack = registry.load("eurocodes")
    assert pack.broken == {}
    assert pack.chain == ["eurocodes", "bnbc2020"]
    # Loads are the pack's own; materials fall back to the pack it extends.
    for table in ("combinations", "seismic", "wind", "areaLoads", "liveReduction", "snow"):
        assert pack.provided_by(table) == "eurocodes"
    for table in ("concrete", "factors", "steel", "detailing", "foundations"):
        assert pack.provided_by(table) == "bnbc2020"


def test_en1990_combinations_and_psi(ec):
    table = ec.table("combinations")
    by_id = {c.id: c.factors for c in table.strength}
    # Eq 6.10, Table A1.2(B): 1.35 / 1.0 / 1.5; ψ0 L 0.7, snow 0.5, wind 0.6 (Table A1.1).
    assert by_id["6.10-G"] == {"D": 1.35, "F": 1.35, "H": 1.35}
    assert by_id["6.10-Q"]["L"] == 1.5 and by_id["6.10-Q"]["Lr"] == pytest.approx(0.75)
    assert by_id["6.10-QW"]["W"] == pytest.approx(0.9)
    assert by_id["6.10-W"]["L"] == pytest.approx(1.05)
    assert by_id["6.10-Wfav"]["D"] == 1.0
    # Eq 6.12b: G + AEd + ψ2 Q, ψ2 0.3 (A, B).
    assert by_id["6.12b"] == {"D": 1.0, "F": 1.0, "H": 1.0, "E": 1.0, "L": 0.3}
    assert table.seismicDeadUpper == table.seismicDeadLower == 1.0
    # SLS Eqs 6.14b-6.16b.
    service = {c.id: c.factors for c in table.service}
    assert service["6.14b-Q"] == {"D": 1.0, "L": 1.0, "Lr": 0.5, "W": 0.6}
    assert service["6.15b-Q"] == {"D": 1.0, "L": 0.5}
    assert service["6.16b"] == {"D": 1.0, "L": 0.3}


def test_610ab_is_chosen_by_an_override():
    pack = registry.load("eurocodes").with_overrides({"combinations.strengthSet": "6.10ab"})
    by_id = {c.id: c.factors for c in pack.table("combinations").strength}
    # Eq 6.10a: ψ0 on every variable action; Eq 6.10b: ξ γG = 0.85 × 1.35.
    assert by_id["6.10a-Q"]["L"] == pytest.approx(1.05)
    assert by_id["6.10b-Q"]["D"] == pytest.approx(0.85 * 1.35)
    assert "6.10-Q" not in by_id


def test_imposed_loads_and_reduction(ec):
    from saengine.design import live_reduction as lr

    uses = ec.table("areaLoads").uses
    # EN 1991-1-1 Table 6.2 (A 2.0/2.0, B 3.0/4.5, C3 5.0/4.0, D1 4.0/4.0), 6.4 (E1 7.5/7.0),
    # 6.8 (F 2.5/20), 6.10 (H 0.4/1.0).
    assert (uses["residential"].live, uses["residential"].concentrated) == (2.0, 2.0)
    assert (uses["office"].live, uses["office"].concentrated) == (3.0, 4.5)
    assert (uses["assemblyMovable"].live, uses["assemblyMovable"].category) == (5.0, "C3")
    assert uses["retailUpper"].live == 4.0
    assert (uses["storageLight"].live, uses["storageLight"].concentrated) == (7.5, 7.0)
    assert (uses["parking"].live, uses["parking"].concentrated) == (2.5, 20.0)
    assert (uses["roof"].live, uses["roof"].concentrated, uses["roof"].roof) == (0.4, 1.0, True)
    # Eq 6.1: αA = 5/7·0.7 + 10/A; Eq 6.2: αn = (2 + (n-2)·0.7)/n.
    scope = lr.LiveScope(live=2.0, categories={"A"})
    factor, _ = lr.reduction(1.0, 40.0, 1, scope)
    assert factor == pytest.approx(0.5 + 0.25)
    factor, _ = lr.reduction(1.0, 400.0, 10, scope)
    assert factor == pytest.approx(min(0.5 + 0.025, (2 + 8 * 0.7) / 10))
    # Categories C and D: αA ≥ 0.6.
    factor, _ = lr.reduction(1.0, 400.0, 1, lr.LiveScope(live=4.0, categories={"D1"}))
    assert factor == pytest.approx(0.6)


def test_snow_on_the_roof(ec):
    from types import SimpleNamespace

    from saengine.fem import snow_load

    roof = SimpleNamespace(form="gable", angle=45.0)
    settings = SimpleNamespace(
        site=SimpleNamespace(
            snow=SimpleNamespace(groundLoad=1.5, exposure="sheltered", thermal=None)
        ),
        wind=SimpleNamespace(claddingRoof=roof),
    )
    s = snow_load.roof_snow(settings)
    # EN 1991-1-3 Eq 5.1, Table 5.1 (sheltered 1.2), Table 5.2 (μ1 = 0.8 (60 - 45)/30 = 0.4).
    assert s["mu1"] == pytest.approx(0.4)
    assert s["Ce"] == 1.2 and s["Ct"] == 1.0
    assert s["s_kPa"] == pytest.approx(0.4 * 1.2 * 1.5)
    roof.form = "flat"
    assert snow_load.roof_snow(settings)["s_kPa"] == pytest.approx(0.8 * 1.2 * 1.5)


def test_bnbc_pack_does_not_cover_snow():
    from types import SimpleNamespace

    from saengine.fem import snow_load

    settings = SimpleNamespace(site=SimpleNamespace(snow=SimpleNamespace(groundLoad=1.0)))
    with code_context.using(registry.load("bnbc2020")), pytest.raises(LookupError):
        snow_load.roof_snow(settings)


# ───────────────────────────── EN 1998-1 ─────────────────────────────


def test_ground_types_and_spectrum_types(ec):
    site = ec.table("seismic").siteClasses
    # Table 3.2 (Type 1).
    assert (site["SC"].S, site["SC"].TB, site["SC"].TC, site["SC"].TD) == (1.15, 0.2, 0.6, 2.0)
    assert (site["SD"].S, site["SD"].TC) == (1.35, 0.8)
    type2 = registry.load("eurocodes").with_overrides({"seismic.spectrumType": "2"})
    site2 = type2.table("seismic").siteClasses
    # Table 3.3 (Type 2).
    assert (site2["SD"].S, site2["SD"].TB, site2["SD"].TC, site2["SD"].TD) == (1.8, 0.1, 0.3, 1.2)


def test_design_spectrum_with_q(ec):
    from saengine.fem import loads as fl

    # Importance class III (γI 1.2), agR 0.2 g, ground C, q = 3.9 (RC frame DCM).
    ag, s, q = 0.2 * 1.2, 1.15, 3.9
    assert fl.design_acceleration(0.0, "SC", 0.2, 1.2, q) == pytest.approx(ag * s * 2 / 3)
    assert fl.design_acceleration(0.4, "SC", 0.2, 1.2, q) == pytest.approx(ag * s * 2.5 / q)
    assert fl.design_acceleration(1.2, "SC", 0.2, 1.2, q) == pytest.approx(ag * s * 2.5 / q * 0.5)
    # Beyond TD the lower bound β·ag (β = 0.2) governs.
    assert fl.design_acceleration(4.0, "SC", 0.2, 1.2, q) == pytest.approx(0.2 * ag)
    importance = ec.table("occupancyCategories").categories
    assert [importance[k].seismicImportance for k in ("I", "II", "III", "IV")] == [
        0.8,
        1.0,
        1.2,
        1.4,
    ]


def test_behaviour_factors_and_period(ec):
    from saengine.fem import loads as fl

    systems = ec.table("seismic").systems
    # Table 5.1 with αu/α1 = 1.3 (multi-storey multi-bay frames), 1.2 (wall-equivalent dual),
    # 1.1 (uncoupled walls); qd = q.
    assert systems["rcSmf"].R == pytest.approx(4.5 * 1.3)
    assert systems["rcImf"].R == pytest.approx(3.0 * 1.3)
    assert systems["rcDualSpecial"].R == pytest.approx(4.5 * 1.2)
    assert systems["rcSpecialWallFrame"].R == pytest.approx(4.0 * 1.1)
    assert systems["rcOrdinaryWallFrame"].R == 3.0
    assert systems["steelSmf"].R == pytest.approx(5 * 1.3)
    assert systems["masonryOrdinaryPlain"].R == 1.5
    assert all(row.Cd == row.R for row in systems.values())
    # Eq 4.6: T1 = 0.075 H^0.75 for RC moment frames.
    assert fl.approximate_period(20.0, "rcImf") == pytest.approx(0.075 * 20.0**0.75)


def test_lateral_force_lambda_and_linear_distribution(ec):
    from saengine.fem import loads as fl

    # λ = 0.85 when T1 ≤ 2 TC and more than two storeys (Eq 4.5).
    assert fl.base_shear_correction(0.5, 5, "SC") == 0.85
    assert fl.base_shear_correction(1.3, 5, "SC") == 1.0
    assert fl.base_shear_correction(0.5, 2, "SC") == 1.0
    # Eq 4.11 with linear mode shape: Fi ∝ zi mi, whatever the period.
    forces = fl.vertical_distribution([(3.0, 100.0), (6.0, 100.0)], 90.0, 3.0)
    assert forces == pytest.approx([30.0, 60.0])


def test_drift_and_theta_rules(ec):
    from saengine.fem.seismic_design import displacement_factor

    seismic = ec.table("seismic")
    # 4.4.3.2(1)a with ν = 0.5 (I, II) and 0.4 (III, IV); ds = qd de (4.3.4).
    assert seismic.allowableDrift == {"I": 0.01, "II": 0.01, "III": 0.0125, "IV": 0.0125}
    assert displacement_factor(3.9, 1.2) == 3.9
    assert seismic.stability.method == "designDrift"
    assert (seismic.stability.ignoreBelow, seismic.stability.thetaCap) == (0.1, 0.3)
    assert (seismic.accidentalEccentricity, seismic.orthogonalShare) == (0.05, 0.3)
    assert seismic.massParticipation == 0.9
    assert seismic.liveShare == 0.3


def test_default_pack_keeps_its_rules():
    from saengine.fem import loads as fl
    from saengine.fem.seismic_design import displacement_factor

    with code_context.using(registry.load("bnbc2020")):
        assert displacement_factor(5.5, 1.25) == pytest.approx(5.5 / 1.25)
        assert fl.base_shear_correction(0.5, 5, "SC") == 1.0
        cs = fl.normalized_spectrum(0.5, "SC")
        assert fl.design_acceleration(0.5, "SC", 0.2, 1.0, 8.0) == pytest.approx(
            2 / 3 * 0.2 / 8.0 * cs
        )


# ───────────────────────────── EN 1991-1-4 ─────────────────────────────


def test_peak_velocity_pressure(ec):
    from saengine.fem import peak_velocity_pressure as pvp

    # Terrain II, z = 10 m, vb,0 = 26 m/s: kr = 0.19, cr = 0.19 ln(10/0.05), Iv = 1/ln(200).
    cr = 0.19 * math.log(10 / 0.05)
    iv = 1 / math.log(10 / 0.05)
    expected = (1 + 7 * iv) * 0.5 * 1.25 * (cr * 26.0) ** 2 / 1000
    assert pvp.peak_velocity_pressure(10.0, 26.0, "II") == pytest.approx(expected)
    # Below zmin (terrain III: 5 m) the value at zmin; kr = 0.19 (0.3/0.05)^0.07.
    kr = 0.19 * (0.3 / 0.05) ** 0.07
    q3 = (1 + 7 / math.log(5 / 0.3)) * 0.5 * 1.25 * (kr * math.log(5 / 0.3) * 26.0) ** 2 / 1000
    assert pvp.peak_velocity_pressure(2.0, 26.0, "III") == pytest.approx(q3)
    # Table 7.1 and 7.2.2(3).
    assert pvp.wall_coefficients(1.0) == (0.8, -0.5)
    assert pvp.wall_coefficients(5.0) == (0.8, -0.7)
    assert pvp.wall_coefficients(0.25) == (0.7, -0.3)
    assert pvp.correlation_factor(1.0) == 0.85 and pvp.correlation_factor(5.0) == 1.0
    assert pvp.correlation_factor(3.0) == pytest.approx(0.925)
    # Figure 7.4 reference heights.
    assert pvp.reference_height(3.0, 10.0, 20.0) == 10.0
    assert pvp.reference_height(5.0, 30.0, 20.0) == 20.0
    assert pvp.reference_height(25.0, 30.0, 20.0) == 30.0
    assert pvp.reference_height(30.0, 60.0, 10.0) == 30.0
    assert pvp.structural_factor(12.0, 10.0)[0] == 1.0


def test_wind_levels_by_the_peak_pressure(ec):
    from saengine.fem import loads as fl
    from saengine.fem import peak_velocity_pressure as pvp

    heights, width, depth = [3.0, 6.0], 10.0, 8.0
    levels = fl.wind_levels(heights, [(0.0, width)] * 2, [depth] * 2, 26.0, "II", 1.0)
    qh = pvp.peak_velocity_pressure(6.0, 26.0, "II")
    cpd, cpe = pvp.wall_coefficients(6.0 / depth)
    rho = pvp.correlation_factor(6.0 / depth)
    # h ≤ b: ze = h on the whole windward face, so each level takes qh (cpe,D - cpe,E) ρ b ·
    # its tributary height (1.5 + 1.5 for level 1, 1.5 for the roof).
    net = qh * (cpd - cpe) * rho * width
    assert [lv.force for lv in levels] == pytest.approx([net * 3.0, net * 1.5])


# ───────────────────────────── EN 1991-1-7 Annex D ─────────────────────────────


def test_gas_explosion_annex_d(ec):
    from saengine.fem import special_loads as spl

    found = spl.explosion_pressure(0.1 * 50.0, 50.0)
    # pd = 3 + pstat/2 + 0.04/(Av/V)² with pstat 3: 4.5 + 4 = 8.5 kN/m².
    assert found["design_kPa"] == pytest.approx(8.5)


# ───────────────────────────── a National Annex ─────────────────────────────


def _annex(folder: Path) -> Path:
    pack = folder / "ec-annex-example"
    (pack / "data").mkdir(parents=True)
    (pack / "pack.json").write_text(
        json.dumps(
            {
                "schema": "saengine.codePack/1",
                "id": "ec-annex-example",
                "name": "Example National Annex",
                "edition": "Eurocodes with an example National Annex",
                "version": "1.0.0",
                "extends": "eurocodes",
                "covers": ["combinations", "seismic"],
                "sources": [{"id": "NA", "title": "Example National Annex", "edition": "2026"}],
                "hooks": None,
            }
        ),
        encoding="utf-8",
    )
    (pack / "data/combinations.json").write_text(
        json.dumps({"strengthSet": "6.10ab", "$sources": ["NA to EN 1990 A1.3.1"]}),
        encoding="utf-8",
    )
    (pack / "data/seismic.json").write_text(
        json.dumps(
            {
                "spectrumType": "2",
                "designSpectrum": {"lowerBound": 0.1},
                "systems": {"rcImf": {"R": 3.6}},
                "$sources": ["NA to EN 1998-1 3.2.2.5(4)"],
            }
        ),
        encoding="utf-8",
    )
    return pack


def test_a_national_annex_sets_only_its_parameters(tmp_path):
    folder = _annex(tmp_path)
    pack = registry.load_path(folder)
    assert pack.broken == {}
    assert pack.chain == ["ec-annex-example", "eurocodes", "bnbc2020"]
    assert "6.10b-Q" in {c.id for c in pack.table("combinations").strength}
    seismic = pack.table("seismic")
    assert seismic.siteClasses["SD"].S == 1.8
    assert seismic.designSpectrum.lowerBound == 0.1
    assert seismic.designSpectrum.method == "behaviourFactor"
    assert seismic.systems["rcImf"].R == 3.6 and seismic.systems["rcImf"].Cd == 3.9
    assert seismic.systems["rcSmf"].R == pytest.approx(5.85)


# ───────────────────────────── a generated building ─────────────────────────────


def test_generated_building_derives_seismic_and_wind(tmp_path):
    from saengine.pipeline.run_all import run_all
    from saengine.project.new_building import create_building

    spec = {
        "name": "EC Frame",
        "gridsX": [6000, 6000],
        "gridsY": [5000, 5000],
        "storyCount": 4,
        "typicalHeight": 3200,
        "system": "rcFrame",
        "codePack": "eurocodes",
        "zoneCoefficient": 0.16,
        "windSpeed": 27.0,
        "windExposure": "III",
        "siteClass": "SC",
        "siteClassSource": "entered",
        "lateralSizing": "gravity",
    }
    out = create_building(spec, tmp_path)
    root = Path(out["root"])
    settings = json.loads(
        (root / "02 Project Settings/project-settings.json").read_text(encoding="utf-8")
    )
    assert settings["codePack"] == "eurocodes"
    assert settings["site"]["location"] == "custom"
    assert settings["wind"]["exposure"] == "III"
    assert any(c["name"].startswith("G + EX + 0.3Q") for c in settings["combinations"])
    result = run_all(root, steps=["derive"])
    assert [s.status for s in result.steps] == ["ok"], [s.message for s in result.steps]
    model = json.loads((root / "08 FEM/model.osmodel").read_text(encoding="utf-8"))
    loaded = {p["name"] for p in model["load_patterns"] if p.get("nodal_loads")}
    assert {"EX", "EY", "WX", "WY"} <= loaded
    from saengine.pipeline.project import open_project
    from saengine.pipeline.run_all import DERIVATION_INPUTS
    from saengine.rpc import handlers

    project = open_project(root)
    texts = project.texts(DERIVATION_INPUTS)
    with code_context.project(root):
        derived = handlers.derive_fem(
            texts["bim"],
            texts["objects"],
            texts["materials"],
            texts["settings"],
            str(root / "08 FEM"),
        )
    summary = derived["summary"]
    notes = derived["notes"]
    seismic = summary["seismic"]["EX"]
    # Sd from the behaviour factor spectrum of a DCM frame (the generator's choice in D) with
    # λ = 0.85 (4 storeys, T1 = 0.075 H^0.75 ≤ 2 TC).
    period = 0.075 * 12.8**0.75
    assert seismic["period_s"] == pytest.approx(period, rel=1e-3)
    assert seismic["correction"] == 0.85
    q = settings_q(settings)
    with code_context.using(registry.load("eurocodes")):
        from saengine.fem import loads as fl

        assert seismic["Sa_g"] == pytest.approx(fl.design_acceleration(period, "SC", 0.16, 1.0, q))
    assert summary["wind_X_kN"] > 0 and summary["wind_Y_kN"] > 0
    assert any("peak velocity pressure" in n for n in notes)


def test_wizard_spec_maps_the_design_code():
    from saengine.project.new_building import spec_from_wizard

    spec, _ = spec_from_wizard(
        {
            "schema": "saengine.newBuilding/1",
            "name": "W",
            "spacings": {"x": [6000], "y": [5000]},
            "storyHeights": [3000],
            "stories": [{"id": "L1", "name": "L1", "elevation": 3000}],
            "site": {
                "location": "custom",
                "siteClass": "SC",
                "zoneCoefficient": 0.1,
                "windSpeed": 25,
            },
            "wind": {"exposure": "II"},
            "designCode": "eurocodes",
        }
    )
    assert spec["codePack"] == "eurocodes"
    assert (spec["zoneCoefficient"], spec["windSpeed"], spec["windExposure"]) == (0.1, 25.0, "II")


def settings_q(settings: dict) -> float:
    systems = registry.load("eurocodes").table("seismic").systems
    return systems[settings["seismic"]["system"]].R

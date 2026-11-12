"""The rest of the Eurocodes pack's concrete, foundation and load parts (alpha 9 track C5c).

Pins the values the pack's new method ids give (VERIFY.md rows C5c-1 to C5c-72, by clause):
strut-and-tie strengths (EN 1992-1-1 6.5), the punching of column bases (6.4.4), interface
shear (6.2.5), the bar shapes and compression laps (8.3, 8.5, 8.7), slab span/depth (7.4.2),
EN 1991-1-4 torsion (7.1.2), orography (Annex A.3), the detailed cscd (Annex B) and the local
pressures (7.2), EN 1991-1-3 drift (5.3.6, 6.2), EN 1998-1 SRSS/CQC (4.3.3.3.2), the vertical
component (4.3.3.5.2), the foundations' capacity design (4.4.2.6); that the default pack picks
none of them; and a generated building whose derivation runs the regularity criteria (4.2.3)
and the torsional wind cases under the pack.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

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


NEW_AREAS = {
    "strutAndTie": "designStressLimits",
    "interfaceShear": "interfaceShear",
    "ties": "tieForces",
    "footingPunching": "reducedPerimeter",
    "wallSlenderness": "columnAnalogy",
    "barShapes": "barShapes",
    "retaining": "limitStates",
}


def test_the_pack_picks_the_new_methods_and_the_default_none(ec):
    from saengine.design import method_selection

    summary = method_selection.summary()
    for area, method in NEW_AREAS.items():
        assert summary[area] == method, area
    with code_context.using(registry.load("bnbc2020")):
        summary = method_selection.summary()
        assert all(summary[a] is None for a in NEW_AREAS)
        seismic = code_context.table("seismic")
        for key in ("regularity", "torsionalEffects", "modalCombination", "verticalComponent",
                    "foundationCapacity"):  # fmt: skip
            assert getattr(seismic, key) is None


def test_strut_and_tie_strengths(ec):
    """EN 1992-1-1 6.5.2, 6.5.4: C30/37, fcd = 20 MPa, ν' = 0.88."""
    from saengine.design import stress_fields as sf

    assert sf.nu_prime(30) == pytest.approx(0.88)
    assert sf.strut_strength(30, cracked=False) == pytest.approx(20.0)
    assert sf.strut_strength(30) == pytest.approx(0.6 * 0.88 * 20)
    assert sf.node_strength(30, "CCC") == pytest.approx(0.88 * 20)
    assert sf.node_strength(30, "CCT") == pytest.approx(0.85 * 0.88 * 20)
    assert sf.node_strength(30, "CTT") == pytest.approx(0.75 * 0.88 * 20)
    assert sf.tie_capacity(1000, 500) == pytest.approx(1000 * 500 / 1.15)


def test_deep_beam_span_ratio(ec):
    """EN 1992-1-1 5.3.1(3): a beam is deep below a span of 3 h."""
    from saengine.design import deep_beams

    span = deep_beams.DeepSpan(2900, 1000, 300, 900, 30, 500, (300, 300), 1500, 200)
    assert deep_beams.is_deep(span)[0]
    span.clear = 3100
    assert not deep_beams.is_deep(span)[0]


def test_footing_punching_reduced_perimeter(ec):
    """EN 1992-1-1 6.4.4(2): vRd = vRd,c 2d/a, VEd less the pressure inside u(a)."""
    from saengine.design import perimeter_punching as pp

    d, c, ved = 500.0, 400.0, 1500e3
    pressure = ved / 2500**2  # a 2.5 m square footing, uniform

    found = pp.footing_punching(
        ved, d, c, c, 30, 0.005, lambda a: pressure * pp.footing_area(c, c, a)
    )
    assert found is not None and 0 < found.a <= 2 * d
    k = 1 + math.sqrt(200 / d)
    vrdc = max(0.12 * k * (100 * 0.005 * 30) ** (1 / 3), 0.035 * k**1.5 * math.sqrt(30))
    assert found.v_rd == pytest.approx(vrdc * 2 * d / found.a)
    u = 4 * c + 2 * math.pi * found.a
    reduced = ved - pressure * pp.footing_area(c, c, found.a)
    assert found.v_ed == pytest.approx(reduced / (u * d))
    assert pp.moment_k(400, 400) == pytest.approx(0.6)
    assert pp.moment_k(800, 400) == pytest.approx(0.7)


def test_interface_shear(ec):
    """EN 1992-1-1 6.2.5: rough surface c = 0.40, μ = 0.7, at most 0.5 ν fcd."""
    from saengine.design import rc_detailing

    found = rc_detailing.shear_friction(800, 500, 30, 300 * 300, "roughened")
    fctd = 0.7 * 0.30 * 30 ** (2 / 3) / 1.5
    expect = 0.40 * fctd * 90000 + 0.7 * 800 * 500 / 1.15
    assert found.phi == 1.0
    assert found.vn == pytest.approx(expect, rel=1e-3)
    assert found.limit == pytest.approx(0.5 * 0.6 * (1 - 30 / 250) * 20 * 90000)
    tension = rc_detailing.shear_friction(800, 500, 30, 90000, "roughened", tension=50e3)
    assert tension.cohesion == 0.0


def test_bar_shapes_and_compression_laps(ec):
    """EN 1992-1-1 8.3 Table 8.1N, 8.5 Figure 8.5, 8.7.3."""
    from saengine.design import bar_rules
    from saengine.drawings import detailing

    assert detailing.bend_diameter(12).value == pytest.approx(48)
    assert detailing.bend_diameter(20).value == pytest.approx(140)
    assert detailing.standard_hook(10, 135, transverse=True).tail == pytest.approx(50)
    assert detailing.standard_hook(12, 90, transverse=True).tail == pytest.approx(120)
    lap = detailing.lap_compression(20, 500, 30)
    lb = bar_rules.basic_length(20, 500 / 1.15, 30)
    assert lap.value == pytest.approx(1.5 * lb)


def test_slab_span_depth_row(ec):
    """EN 1992-1-1 7.4.2: an end span (K 1.3) with ρ of its bottom bars."""
    from saengine.design import crack_control
    from saengine.design import limit_state_members as lsm
    from saengine.design.slab import Thickness

    t = Thickness(150, "7.3.1.1", "", span=4000, ends=1, along="x")
    layer = SimpleNamespace(area=393.0, d=125.0)
    row = lsm.slab_span_depth_row(t, 150, 30, 500, {"bottomX": layer, "bottomY": None})
    limit = crack_control.span_depth_limit("endSpan", 393 / 125e3, 0.0, 30, 500, 1, 1, 4000)
    assert row["demand"] == pytest.approx(4000 / 125, rel=1e-3)
    assert row["capacity"] == pytest.approx(limit, rel=1e-3)


def test_wind_torsion_orography_cscd_and_local_pressures(ec):
    """EN 1991-1-4 7.1.2, Annex A.3, Annex B, 7.2."""
    from saengine.fem import loads as fl
    from saengine.fem import local_pressures
    from saengine.fem import peak_velocity_pressure as pvp

    cases = fl.wind_design_cases()
    assert (cases.partial, cases.eccentricity, cases.simultaneous) == (1.0, 0.1, None)
    labels = [label for label, _ in fl.wind_design_variants({"WX": 1.5}, cases)]
    assert labels == ["Case 1", "Case 2 +e", "Case 2 -e"]
    topo = SimpleNamespace(feature="hill", height=60, length=150, distance=0, side="upwind",
                           isolated=True)  # fmt: skip
    with fl.wind_overrides(SimpleNamespace(topography=topo)):
        found = pvp.orography_terms(10.0)
    z = 10 / 300
    a = 0.1552 * z**4 - 0.8575 * z**3 + 1.8133 * z**2 - 1.9115 * z + 1.0124
    assert found["phi"] == pytest.approx(0.2)
    assert found["co"] == pytest.approx(1 + 2 * a * 0.2)
    cscd, why = pvp.structural_factor(120, 30, None, 30, 26, "III")
    assert "detailed" in why and 0.8 < cscd < 1.1
    assert pvp.structural_factor(12, 10)[0] == 1.0
    lp = local_pressures.local_pressures(20, 30, 15, 26, "II", 1.0, area=5.0)
    zones = {(z["surface"], z["zone"]): z for z in lp["zones"]}
    assert zones[("wall", "A")]["GCpNeg"] == pytest.approx(-1.4 + 0.2 * math.log10(5))
    assert zones[("roof", "F")]["GCpNeg"] == pytest.approx(-2.5 + 0.7 * math.log10(5))
    assert lp["e_m"] == pytest.approx(30)


def test_snow_drift_at_a_step_and_a_parapet(ec):
    """EN 1991-1-3 5.3.6, 6.2."""
    from saengine.fem import snow_load

    rule = code_context.table("snow").drift
    step = SimpleNamespace(upperLength=8, lowerLength=4, stepHeight=2, windParameter=None)
    found = snow_load.shape_drift(rule, 1.0, step, 1.0, 1.0, None)
    assert found["muw"] == pytest.approx(3.0)  # (8 + 4)/(2 × 2), γh/sk = 4
    assert found["ls"] == pytest.approx(5.0)  # 2h = 4 m, at least 5 m
    parapet = snow_load.shape_drift(rule, 1.0, None, 1.0, 1.0, 0.6)
    assert parapet["mu2"] == pytest.approx(1.2)  # 2 × 0.6 / 1.0


def test_modal_rule_vertical_component_and_foundation_capacity(ec):
    """EN 1998-1 4.3.3.3.2, 4.3.3.5.2, 4.4.2.6."""
    from saengine.fem import seismic_design as sd
    from saengine.substructure import foundation_capacity as fc

    close = [{"angular_frequency": 2 * math.pi / 1.0}, {"angular_frequency": 2 * math.pi / 0.95}]
    apart = [{"angular_frequency": 2 * math.pi / 1.0}, {"angular_frequency": 2 * math.pi / 0.5}]
    assert sd.modal_rule(close, "CQC") == "CQC"
    assert sd.modal_rule(apart, "CQC") == "SRSS"
    from saengine.library import settings as library_settings

    base = library_settings.default_project_settings("C5c", "eurocodes")
    real = base.model_copy(
        update={
            "site": base.site.model_copy(update={"location": "custom", "zoneCoefficient": 0.35}),
            "seismic": base.seismic.model_copy(update={"system": "rcImf"}),
        }
    )
    found = sd.vertical_terms(real)
    gamma_i = library_settings.derived(real)["seismicImportance"]
    assert found["avg"] == pytest.approx(0.9 * gamma_i * 0.35)
    assert found["applies"]
    assert found["coefficient"] == pytest.approx(0.3 * found["avg"] * 3.0 / 1.5)
    value, _ = fc.factor(real)
    q = library_settings.derived(real)["R"]
    assert value == pytest.approx(min(1.2 * q, q))
    strength, how = fc.capacity_combinations(
        [("E", {"D": 1.0, "EX": 1.0}), ("G", {"D": 1.35})], real
    )
    assert strength[0][1]["EX"] == pytest.approx(value) and strength[1][1] == {"D": 1.35}
    assert how


def test_generated_building_regularity_and_torsional_wind(tmp_path):
    """A small regular frame under the pack: the regularity criteria (EN 1998-1 4.2.3) find it
    regular (q unchanged), the wind has its torsional cases (EN 1991-1-4 7.1.2) and the local
    pressures (7.2)."""
    from saengine.pipeline.project import open_project
    from saengine.pipeline.run_all import DERIVATION_INPUTS, run_all
    from saengine.project.new_building import create_building
    from saengine.rpc import handlers

    spec = {
        "name": "EC C5c",
        "gridsX": [6000, 6000],
        "gridsY": [5000, 5000],
        "storyCount": 3,
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
    root = Path(create_building(spec, tmp_path)["root"])
    result = run_all(root, steps=["derive"])
    assert [s.status for s in result.steps] == ["ok"], [s.message for s in result.steps]
    project = open_project(root)
    texts = project.texts(DERIVATION_INPUTS)
    with code_context.project(root):
        derived = handlers.derive_fem(
            texts["bim"], texts["objects"], texts["materials"], texts["settings"],
            str(root / "08 FEM"),
        )  # fmt: skip
    summary, notes = derived["summary"], derived["notes"]
    regularity = summary["regularity"]
    assert regularity["plan"] and regularity["elevation"], regularity["rows"]
    assert regularity["qFactor"] == 1.0
    assert any(r["check"] == "torsionalRadius" for r in regularity["rows"])
    assert any("seismic regularity" in n for n in notes)
    assert summary["wind"]["torsionCases"] == ["WTX", "WTY"]
    assert summary["wind"]["cladding"]["formula"].startswith("w = qp(ze)")
    model = json.loads((root / "08 FEM/model.osmodel").read_text(encoding="utf-8"))
    loaded = {p["name"] for p in model["load_patterns"] if p.get("nodal_loads")}
    assert {"WTX", "WTY"} <= loaded

"""The Japanese pack (Building Standard Law + AIJ) of alpha 9 track C19.

Pins the values with their articles (see the pack's VERIFY.md): Rt, Ai and Ci of the storey
shear coefficient method (Enforcement Order Art. 88, Notification 1793), the floor live loads of
Art. 85, the wind terms of Notification 1454, the allowable stresses of the AIJ standards, Ds,
Fs and Fe of Notification 1792; the generic mechanisms (standardShearCoefficient,
shearCoefficientAi, frameValue, liveWeight byUse, gustByHeight, allowableStress,
horizontalCapacity) unset in the other packs; a generated building through the primary design;
and the storeys' Qu >= Qun check on a pushover's results.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

PACK_ID = "japan-bsl"


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


def _pack():
    return registry.load(PACK_ID)


def test_pack_is_listed_sound_and_extends():
    assert PACK_ID in [p.id for p in registry.list_packs()]
    pack = _pack()
    assert pack.broken == {}
    assert pack.chain == [PACK_ID, "aci318-asce7-22", "bnbc2020"]
    for table in pack.info.covers:
        assert pack.provided_by(table) == PACK_ID
        pack.table(table)
    assert pack.info.units == "SI"
    assert (Path(pack.path) / "VERIFY.md").is_file()
    assert (Path(pack.path) / "README.md").is_file()


def test_rt_ai_ci_pins():
    from saengine.fem import shear_coefficient as sc

    with code_context.using(_pack()):
        block = sc.rule()
        # N1793 Art. 2: Rt = 1 (T < Tc), 1 - 0.2 (T/Tc - 1)^2 (Tc <= T < 2Tc), 1.6 Tc/T beyond.
        assert sc.vibration_factor(0.3, 0.6, block) == 1.0
        assert sc.vibration_factor(0.9, 0.6, block) == pytest.approx(1 - 0.2 * 0.5**2)
        assert sc.vibration_factor(1.5, 0.6, block) == pytest.approx(1.6 * 0.6 / 1.5)
        assert sc.site_corner("S1") == 0.4 and sc.site_corner("S3") == 0.8
        # Art. 3: Ai = 1 + (1/sqrt(a) - a) 2T / (1 + 3T); Ai = 1 at the first storey.
        t = 0.5
        assert sc.distribution_factor(1.0, t, block) == pytest.approx(1.0)
        a = 0.4
        assert sc.distribution_factor(a, t, block) == pytest.approx(
            1 + (1 / math.sqrt(a) - a) * 2 * t / (1 + 3 * t)
        )
        # Art. 88: C = Z Rt C0, C0 0.2 (primary) and 1.0 (ultimate).
        assert sc.coefficient(0.3, "S2", 1.0) == pytest.approx(0.2)
        assert sc.coefficient(0.3, "S2", 0.8, ultimate=True) == pytest.approx(0.8)
        # T = 0.02 h for concrete, 0.03 h for steel.
        from saengine.fem.loads import approximate_period

        assert approximate_period(30.0, "rcSmf") == pytest.approx(0.6)
        assert approximate_period(30.0, "steelSmf") == pytest.approx(0.9)
        # The storey shears Qi = V Ai ai; the level forces their differences, summing to V.
        levels = [(3.0, 100.0), (6.0, 100.0), (9.0, 100.0)]
        forces = sc.level_forces(levels, 60.0, 0.18)
        assert sum(forces) == pytest.approx(60.0)
        terms = sc.storey_terms(levels, 0.18)
        top = 60.0 * terms[2]["Ai"] * terms[2]["alpha"]
        assert forces[2] == pytest.approx(top)


def test_bsl_load_values():
    pack = _pack()
    uses = pack.table("areaLoads").uses
    # Art. 85(1): slabs / frames / seismic force [kN/m2].
    assert (uses["residential"].live, uses["residential"].frameLive) == (1.8, 1.3)
    assert uses["residential"].seismicLive == 0.6
    assert (uses["office"].live, uses["office"].frameLive, uses["office"].seismicLive) == (
        2.9,
        1.8,
        0.8,
    )
    assert uses["parking"].live == 5.4 and uses["parking"].seismicLive == 2.0
    seismic = pack.table("seismic")
    assert seismic.liveWeight == "byUse"
    assert seismic.allowableDrift["II"] == 0.005  # Art. 82-2: 1/200
    assert pack.table("zoneCoefficients").zones == {1: 0.7, 2: 0.8, 3: 0.9, 4: 1.0}
    tokyo = pack.table("locations").locations["tokyo"]
    assert (tokyo.zone, tokyo.windSpeed) == (4, 34.0)
    assert pack.table("locations").locations["naha"].windSpeed == 46.0
    allowable = {c.id: c.factors for c in pack.table("combinations").allowable}
    assert allowable["L2"]["S"] == 0.7 and allowable["E2"]["S"] == 0.35  # Art. 82(2)
    assert pack.table("concrete").barNames["9.53"] == "D10"


def test_wind_terms():
    from saengine.fem import loads as fl

    with code_context.using(_pack()):
        # N1454: Er = 1.7 (H/ZG)^a, q = 0.6 Er^2 Gf V0^2 (the program's 0.613 carried).
        h, v = 20.0, 34.0
        er = 1.7 * (h / 450.0) ** 0.20
        q = fl.velocity_pressure(h, v, "III", 1.0)
        assert q == pytest.approx(0.6 * er**2 * v**2 / 1000, rel=1e-3)
        # Below Zb (10 m for III) Er is that of Zb.
        assert fl.velocity_pressure(4.0, v, "III", 1.0) == pytest.approx(
            fl.velocity_pressure(10.0, v, "III", 1.0)
        )
        # Gf of III: 2.5 at H <= 10 m, 2.1 at H >= 40 m, linear between.
        assert fl.gust_factor(8.0, "III") == 2.5
        assert fl.gust_factor(25.0, "III") == pytest.approx(2.3)
        assert fl.gust_factor(60.0, "IV") == 2.3


def test_allowable_stresses():
    from saengine.design import allowable_stress as al

    with code_context.using(_pack()):
        # BSL EO Art. 91 / AIJ RC Art. 6: Fc/3, 2Fc/3; fs = min(Fc/30, 0.49 + Fc/100).
        assert al.concrete_stress(24.0, True) == pytest.approx(8.0)
        assert al.concrete_stress(24.0, False) == pytest.approx(16.0)
        assert al.concrete_shear(24.0, True) == pytest.approx(0.73)
        assert al.concrete_shear(24.0, False) == pytest.approx(1.095)
        # Art. 90: SD345 215 (195 from D29), short-term F.
        assert al.rebar_stress(345.0, 25.4, True) == 215.0
        assert al.rebar_stress(345.0, 28.6, True) == 195.0
        assert al.rebar_stress(345.0, 28.6, False) == 345.0
        # alpha = 4 / (M/(Q d) + 1) within 1-2 (beams).
        assert al.shear_alpha(0.0, 10.0, 500.0, False) == 2.0
        assert al.shear_alpha(1e9, 1.0, 500.0, False) == 1.0
        # Steel: ft = F/1.5, fc at lambda = 0 is F/1.5 too.
        assert al.steel_stresses(235.0, True)["ft"] == pytest.approx(235 / 1.5)
        assert al.steel_compression(235.0, 0.0, True) == pytest.approx(235 / 1.5)
        # The elastic section: a singly reinforced beam at N = 0 against the textbook value
        # Ma = at ft (d - x/3) with x from b x^2 / 2 = n at (d - x) (steel governing).
        b, h, at, d, n = 300.0, 600.0, 1500.0, 540.0, 15.0
        bars = [(h / 2 - (h - d), at, 22.2)]
        curve = al.interaction_curve(b, h, bars, 1e6, [215.0], n)
        x = (-n * at + math.sqrt((n * at) ** 2 + 2 * b * n * at * d)) / b
        expected = at * 215.0 * (d - x / 3)
        assert al.allowable_moment(curve, 0.0, positive=False) == pytest.approx(expected, rel=0.01)


def test_ds_fs_fe_and_required_capacity():
    from saengine.fem import horizontal_capacity as hc

    with code_context.using(_pack()):
        # N1792 Art. 5: Fs = 2 - Rs/0.6 below 0.6; Fe = 1 to Re 0.15, 1.5 from 0.45.
        assert hc.stiffness_factor(0.8) == 1.0
        assert hc.stiffness_factor(0.3) == pytest.approx(1.5)
        assert hc.eccentricity_factor(0.1) == 1.0
        assert hc.eccentricity_factor(0.3) == pytest.approx(1.25)
        assert hc.eccentricity_factor(0.6) == 1.5
        # N1792 Art. 4: RC frames (beta_u <= 0.3) FA 0.30 ... FD 0.45; walls FD 0.55.
        assert hc.structural_factor("concrete", "FA", 0.0) == 0.30
        assert hc.structural_factor("concrete", "FD", 1.0) == 0.55
        assert hc.structural_factor("steel", "FA", 0.0) == 0.25
        assert hc.required_capacity(0.3, 1.0, 1.25, 1000.0) == pytest.approx(375.0)


def test_member_rank_and_mean_shear():
    from saengine.design import member_rank

    with code_context.using(_pack()):
        ranks, strength = member_rank.tables()
        # Qsu = {0.068 pt^0.23 (Fc + 18) / (M/(Qd) + 0.12) + 0.85 sqrt(pw swy) + 0.1 s0} b j.
        qsu = member_rank.mean_shear_strength(strength, 400, 500, 24, 1.0, 0.004, 345, 2.0, 1.5)
        expected = (
            (0.068 * 1.0**0.23 * 42 / 1.62 + 0.85 * math.sqrt(0.004 * 345) + 0.1 * 2.0)
            * 400
            * 0.875
            * 500
        )
        assert qsu == pytest.approx(expected)
        values = {"clearRatio": 3.0, "axialRatio": 0.3, "tensionRatio": 0.7, "shearRatio": 0.09}
        assert member_rank._rank(ranks.order, ranks.columns, values) == "FA"
        values["axialRatio"] = 0.5
        assert member_rank._rank(ranks.order, ranks.columns, values) == "FC"
        values["axialRatio"] = 0.6
        assert member_rank._rank(ranks.order, ranks.columns, values) == "FD"


def test_storey_capacity_from_a_pushover():
    from saengine.fem import horizontal_capacity as hc

    # Two storeys of 3 m, the pattern 1 kN at level 1 and 2 kN at level 2 (shares 1, 2/3).
    project = {
        "nodes": [
            {"id": 1, "coords": [0, 0, 0], "restraint": [1] * 6},
            {"id": 2, "coords": [0, 0, 3.0]},
            {"id": 3, "coords": [0, 0, 6.0]},
        ],
        "load_patterns": [
            {
                "id": 1,
                "nodal_loads": [
                    {"node_id": 2, "forces": [1.0, 0, 0, 0, 0, 0]},
                    {"node_id": 3, "forces": [2.0, 0, 0, 0, 0, 0]},
                ],
            }
        ],
    }
    analysis = {"control_dof": 1, "target_disp": 0.2, "pattern_ids": [1]}
    steps = np.linspace(0.0, 0.1, 11)
    results = SimpleNamespace(
        base_shear=np.array([1000.0 * s / 0.1 for s in steps]),
        node_disp={
            1: np.zeros((11, 6)),
            2: np.array([[s * 0.5, 0, 0, 0, 0, 0] for s in steps]),
            3: np.array([[s, 0, 0, 0, 0, 0] for s in steps]),
        },
    )
    with code_context.using(_pack()):
        found = hc.storey_capacity(project, analysis, results, [0.0, 3.0, 6.0], 0.0095)
    # Storey drift 0.5 s / 3 first passes 0.0095 at s = 0.06 (step 6): V = 600 kN.
    assert found["reached"] and found["step"] == 6
    assert found["Qu"][0] == pytest.approx(600.0)
    assert found["Qu"][1] == pytest.approx(400.0)


def test_other_packs_keep_their_methods():
    from saengine.design import allowable_stress, member_rank
    from saengine.fem import horizontal_capacity, shear_coefficient
    from saengine.library.settings import seismic_weight_rule

    for pack_id in ("bnbc2020", "aci318-asce7-22", "eurocodes", "canada-nbcc"):
        pack = registry.load(pack_id)
        with code_context.using(pack):
            assert shear_coefficient.rule() is None
            assert allowable_stress.table() is None
            assert horizontal_capacity.table() is None
            assert member_rank.tables() is None
            assert seismic_weight_rule(pack=pack).use_shares == {}
            assert pack.table("liveReduction").method != "frameValue"


def test_generated_building_through_the_primary_design(tmp_path):
    from saengine.pipeline.run_all import run_all
    from saengine.project.new_building import create_building
    from saengine.rpc import handlers

    spec = {
        "name": "C19 Concrete",
        "gridsX": [5000],
        "gridsY": [4000],
        "storyCount": 2,
        "typicalHeight": 3000,
        "system": "rcFrame",
        "codePack": PACK_ID,
        "lateralSizing": "gravity",
        "siteClassSource": "entered",
        "location": "osaka",
        "siteClass": "S2",
    }
    root = Path(create_building(spec, tmp_path)["root"])
    result = run_all(root, steps=["derive", "analysis"])
    assert [s.status for s in result.steps] == ["ok", "ok"], [s.message for s in result.steps]
    summary = json.loads((root / "08 FEM/model.derivation.json").read_text(encoding="utf-8"))
    ex = summary["summary"]["seismic"]["EX"]
    assert ex["period_s"] == pytest.approx(0.02 * 6.0, rel=1e-3)
    assert ex["Sa_g"] == pytest.approx(0.2)  # Z 1.0, Rt 1, C0 0.2
    assert ex["shearCoefficient"]["storeys"][0]["Ai"] == pytest.approx(1.0)
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
    names = {c["name"] for e in report["elements"] for c in e.get("checks", [])}
    assert "Allowable stress, flexure (long-term)" in names, sorted(names)
    assert "Allowable stress, axial force and bending about x (short-term)" in names
    ranks = {c.get("rank") for e in report["elements"] for c in e.get("checks", [])}
    assert ranks & {"FA", "FB", "FC", "FD"}
    # The primary design's Rs and Re from the linear model.
    from saengine.fem import horizontal_capacity as hc

    model_path = root / "08 FEM/model.osmodel"
    model = json.loads(model_path.read_text(encoding="utf-8"))
    with code_context.project(root):
        shape = hc.stiffness_eccentricity(model, root / "08 FEM/model.results", model_path)
    assert {r["direction"] for r in shape["rows"]} == {"X", "Y"}
    assert all(r["Fs"] >= 1.0 and r["Fe"] >= 1.0 for r in shape["rows"])

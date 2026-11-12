"""Alpha 9 L9: bridges and special structures. Moving loads on influence lines (HL-93 in the US
pack, EN 1991-2 LM1/LM2 in the Eurocodes pack, IRC Class A / 70R in the IS pack, SAEngine
practice on the HL-93 basis for a pack without traffic loads), girder bridges (line girders and
deck grillages, girder checks, bearings, joints, load rating), lattice towers, silos (Janssen),
chimneys (vortex shedding), cooling towers, offshore jackets (Morison, Airy and the stream
function wave) and piping stress. The bnbc2020 pack covers none of the new tables (its
results unchanged).

Written for the alpha 9 test pass (not run when written, owner 2026-11-05)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.codes.bridge_special_tables import MovingLoadsTable
from saengine.codes.tables import TABLE_MODELS, builtin_manifest
from saengine.library.defaults import default_material_library
from saengine.library.shapes import (
    DeckGrillage,
    JacketFrame,
    RevolutionShell,
    TrussTower,
    insert,
    revolution_radius,
    shape_geometry,
)
from saengine.library.special_structures import (
    Bridge,
    PipingSystem,
    Silo,
    SpecialStructures,
)
from saengine.library.structure import default_structural_model
from saengine.special import bridges as br
from saengine.special import moving_loads as ml
from saengine.special import offshore as off
from saengine.special import piping as pp
from saengine.special import shells as sh

NEW_TABLES = (
    "movingLoads",
    "bridgeDesign",
    "latticeTowers",
    "shellStructures",
    "offshore",
    "pipingStress",
)


def _pack(pack_id: str):
    return registry.load(pack_id)


# ───────────────────────────── packs ─────────────────────────────


def test_tables_registered_and_not_in_the_default_pack():
    for name in NEW_TABLES:
        assert name in TABLE_MODELS
    covered = set(builtin_manifest("bnbc2020")["covers"])
    assert not covered & set(NEW_TABLES)


@pytest.mark.parametrize(
    ("pack_id", "tables"),
    [
        (
            "aci318-asce7-22",
            ["movingLoads", "bridgeDesign", "latticeTowers", "offshore", "pipingStress"],
        ),
        (
            "eurocodes",
            ["movingLoads", "bridgeDesign", "latticeTowers", "shellStructures", "offshore"],
        ),
        ("is-codes", ["movingLoads", "bridgeDesign"]),
    ],
)
def test_packs_load_their_tables(pack_id, tables):
    pack = _pack(pack_id)
    for name in tables:
        assert pack.has(name)
        pack.table(name)


def test_us_hl93_values():
    t = _pack("aci318-asce7-22").table("movingLoads")
    truck = t.vehicles["designTruck"]
    assert [a.load for a in truck.axles] == [35.0, 145.0, 145.0]  # AASHTO 3.6.1.2.2
    assert truck.axles[2].spacingMax == 9.0
    assert [a.load for a in t.vehicles["designTandem"].axles] == [110.0, 110.0]  # 3.6.1.2.3
    assert t.loadModels["truckLane"].lanes[0].lineLoad == 9.3  # 3.6.1.2.4
    assert t.multiplePresence == [1.2, 1.0, 0.85, 0.65]  # Table 3.6.1.1.2-1
    assert ml.dynamic_factor(t, 20.0)[0] == pytest.approx(1.33)  # Table 3.6.2.1-1


def test_en_lm1_values():
    t = _pack("eurocodes").table("movingLoads")
    lm1 = t.loadModels["lm1"]
    assert [lane.areaLoad for lane in lm1.lanes] == [9.0, 2.5, 2.5, 2.5]  # EN 1991-2 Table 4.2
    assert t.vehicles["ts1"].axles[0].load == 300.0
    assert ml.dynamic_factor(t, 20.0)[0] == 1.0  # included
    assert ml.lane_count(5.0, t) == 1 and ml.lane_count(5.5, t) == 2 and ml.lane_count(10.0, t) == 3


def test_irc_impact_and_lanes():
    t = _pack("is-codes").table("movingLoads")
    factor, _ = ml.dynamic_factor(t, 20.0, "concrete")
    assert factor == pytest.approx(1 + 4.5 / 26.0)  # IRC:6 Cl 208
    assert ml.lane_count(7.5, t) == 2  # IRC:6 Table 6


def test_practice_tables_for_a_pack_without_traffic_loads():
    with code_context.using(_pack("bnbc2020")):
        b = ml.basis("movingLoads")
        assert b.practice
        assert "HL-93" in b.label
        assert ml.basis("bridgeDesign").table.strength.ll == 1.75


# ───────────────────────────── influence lines and envelopes ─────────────────────────────


def test_simple_span_influence_lines():
    infl = ml.line_influence([20.0], 0.5)
    mid = int(np.argmin(np.abs(infl.x - 10.0)))
    assert infl.moment[mid, mid] == pytest.approx(5.0, rel=1e-6)  # L/4
    assert infl.reaction[0, mid] == pytest.approx(0.5, rel=1e-6)
    assert infl.reaction[0, 0] == pytest.approx(1.0)


def test_two_span_middle_reaction():
    infl = ml.line_influence([10.0, 10.0], 0.5)
    quarter = int(np.argmin(np.abs(infl.x - 5.0)))
    # a unit load at the middle of span 1 of two equal spans: the middle support takes 11/16
    assert infl.reaction[1, quarter] == pytest.approx(11 / 16, rel=1e-6)


def test_uniform_load_effects():
    found = ml.uniform_effects([20.0], 10.0, 0.5)
    assert float(np.max(found["moment"])) == pytest.approx(10 * 20**2 / 8, rel=1e-6)
    assert found["reaction"][0] == pytest.approx(100.0, rel=1e-6)


def _table(**changes):
    data = {
        "laneWidth": 3.0,
        "vehicles": {"axle": {"label": "one axle", "axles": [{"load": 100.0}], "gauge": 2.0}},
        "loadModels": {
            "m": {"label": "axle and lane", "lanes": [{"vehicle": "axle", "lineLoad": 10.0}]}
        },
        "multiplePresence": [1.2, 1.0],
        "dynamic": {"method": "constant", "constant": 0.0},
    }
    data.update(changes)
    return MovingLoadsTable.model_validate(data)


def test_axle_and_lane_on_a_simple_span():
    t = _table()
    basis = ml.Basis(t, False, "test")
    infl = ml.line_influence([20.0], 0.25)
    mid = int(np.argmin(np.abs(infl.x - 10.0)))
    il = infl.moment[mid].copy()
    lanes = [(infl.x, il, il, 3.0, 1.0)]
    high, low = ml.envelope(lanes, basis, 1.0)
    assert high.value == pytest.approx(1.2 * (100 * 20 / 4 + 10 * 20**2 / 8), rel=1e-3)
    assert low.value == pytest.approx(0.0, abs=1e-9)


def test_multiple_presence_picks_the_worst_lane_count():
    t = _table()
    basis = ml.Basis(t, False, "test")
    infl = ml.line_influence([20.0], 0.25)
    mid = int(np.argmin(np.abs(infl.x - 10.0)))
    il = infl.moment[mid].copy()
    one = 100 * 20 / 4 + 10 * 20**2 / 8
    high, _ = ml.envelope([(infl.x, il, il, 3.0, 1.0), (infl.x, il, il, 3.0, 1.0)], basis, 1.0)
    assert high.value == pytest.approx(max(1.2 * one, 2 * 1.0 * one), rel=1e-3)
    assert high.lanes == 2


def test_scaled_lane_with_negative_share():
    effect = ml.LaneEffect(10.0, -2.0)
    scaled = ml._scaled(effect, -0.5)
    assert scaled.high == pytest.approx(1.0)
    assert scaled.low == pytest.approx(-5.0)


def test_courbon_shares_sum_to_one():
    shares = ml.courbon_share(2.0, [-3.75, -1.25, 1.25, 3.75])
    assert sum(shares) == pytest.approx(1.0)
    assert shares[-1] > shares[0]


def test_variable_spacing_groups():
    t = _pack("aci318-asce7-22").table("movingLoads")
    groups = ml.vehicle_groups(t.vehicles["designTruck"])
    lengths = sorted({round(g.length, 3) for g in groups})
    assert lengths[0] == pytest.approx(8.6) and lengths[-1] == pytest.approx(13.3)


# ───────────────────────────── bridges ─────────────────────────────


def _bridge(**changes) -> Bridge:
    data = {
        "id": "BR1",
        "spans": [20.0],
        "carriageway": 7.5,
        "girders": 4,
        "girderSpacing": 2.5,
        "analysis": "lineGirder",
        "girder": {
            "depth": 1500,
            "webWidth": 400,
            "concrete": "C24.1",
            "rebar": "B420DWR",
            "bottomBars": 10,
            "bottomDiameter": 32,
        },
    }
    data.update(changes)
    return Bridge.model_validate(data)


@pytest.mark.parametrize("pack_id", ["aci318-asce7-22", "eurocodes", "is-codes", "bnbc2020"])
def test_line_girder_bridge_checks(pack_id):
    with code_context.using(_pack(pack_id)):
        found = br.check_bridge(_bridge(), default_material_library())
    names = [r["name"] for r in found["rows"]]
    assert any("sagging" in n for n in names)
    assert any("shear" in n for n in names)
    assert found["bearings"] and found["joints"]
    assert found["chart"]["x"]


def test_bridge_rating_us_pack():
    bridge = _bridge(rating={"condition": 0.95, "system": 1.0})
    with code_context.using(_pack("aci318-asce7-22")):
        found = br.check_bridge(bridge, default_material_library())
    levels = {(r["effect"], r["level"]) for r in found["rating"]}
    assert ("flexure", "inventory") in levels and ("flexure", "operating") in levels
    inv = next(r for r in found["rating"] if r["effect"] == "flexure" and r["level"] == "inventory")
    op = next(r for r in found["rating"] if r["effect"] == "flexure" and r["level"] == "operating")
    # Both factors are reported to two decimals.
    assert op["rf"] == pytest.approx(inv["rf"] * 1.75 / 1.35, abs=0.01)


def test_bridge_grillage_runs():
    bridge = _bridge(analysis="grillage", spans=[12.0], girders=3)
    with code_context.using(_pack("aci318-asce7-22")):
        found = br.check_bridge(bridge, default_material_library())
    assert any("grillage" in n for n in found["notes"])


def test_prestressed_girder_rows():
    bridge = _bridge(
        girder={
            "depth": 1500,
            "webWidth": 400,
            "concrete": "C24.1",
            "rebar": "B420DWR",
            "bottomBars": 4,
            "bottomDiameter": 20,
            "prestress": {"area": 2800, "depth": 1350},
        }
    )
    with code_context.using(_pack("aci318-asce7-22")):
        found = br.check_bridge(bridge, default_material_library())
    assert any(r["name"].startswith("Transfer") for r in found["rows"])
    assert any(r["name"].startswith("Service") for r in found["rows"])


def test_bearing_kinds():
    bridge = _bridge(bearings=[{"support": 1, "kind": "free"}])
    assert br.bearing_fixity(bridge, 0) == (1, 1, 1, 0, 0, 0)
    assert br.bearing_fixity(bridge, 1) == (0, 0, 1, 0, 0, 0)


def test_expansion_joint_movement():
    bridge = _bridge(spans=[30.0, 30.0], continuity="continuous", thermalRange=40)
    with code_context.using(_pack("aci318-asce7-22")):
        joints = br.joint_rows(bridge, ml.basis("bridgeDesign").table)
    end = next(j for j in joints if j["line"] == 2)
    assert end["movement"] == pytest.approx(1.08e-5 * 40 * 60 * 1000, rel=1e-3)


def test_tee_section_properties():
    tee = br.TeeSection(depth=1000, web=300, flange=2000, slab=200)
    assert tee.area == pytest.approx(2000 * 200 + 300 * 800)
    assert 0 < tee.top < 500


# ───────────────────────────── shapes ─────────────────────────────


def test_deck_grillage_shape():
    shape = DeckGrillage(spans=[10000, 10000], girders=3, girderSpacing=2500, divisions=5,
                         memberType="G")  # fmt: skip
    g = shape.local()
    assert len(g.members) == 3 * 10 + 11 * 2
    assert len(g.supports) == 3 * 3


def test_truss_tower_shape():
    shape = TrussTower(height=30000, baseWidth=6000, topWidth=2000, panels=6, memberType="L")
    g = shape.local()
    legs = [m for m in g.members if m.type == "L"]
    assert len(legs) >= 4 * 6
    assert len(g.supports) == 4


def test_revolution_shell_inserts_flat_panels():
    shape = RevolutionShell(profile="hyperboloid", height=100000, baseRadius=40000,
                            topRadius=28000, throatRadius=26000, throatHeight=80000,
                            rings=6, segments=12, panelType="W")  # fmt: skip
    model, _, _ = insert(default_structural_model(), shape_geometry(shape))
    assert len(model.areas) == 6 * 12
    assert revolution_radius("hyperboloid", 80000, 100000, 40000, 28000, 26000, 80000) == (
        pytest.approx(26000)
    )
    assert revolution_radius("hyperboloid", 0, 100000, 40000, 28000, 26000, 80000) == (
        pytest.approx(40000)
    )


def test_jacket_shape():
    g = JacketFrame(height=40000, bays=4, memberType="LEG", braceType="BR").local()
    assert len([m for m in g.members if m.type == "LEG"]) == 16
    assert len(g.supports) == 4
    mono = JacketFrame(form="monopile", height=40000, bays=4, memberType="P").local()
    assert len(mono.members) == 4 and len(mono.supports) == 1


# ───────────────────────────── shells ─────────────────────────────


def test_janssen_asymptote():
    found = sh.janssen(8.0, 9.0, 0.6, 0.4, np.array([0.0, 1000.0]))
    assert found["ph"][0] == 0.0
    assert found["ph"][-1] == pytest.approx(9.0 * 8.0 / (4 * 0.4), rel=1e-6)  # γ D / (4 μ)


def test_silo_en_pack():
    silo = Silo.model_validate(
        {"id": "S1", "diameter": 8.0, "height": 24.0, "concrete": "C24.1", "rebar": "B420DWR"}
    )
    with code_context.using(_pack("eurocodes")):
        found = sh.analyse_silo(silo, default_material_library())
    assert found["rows"][0]["demand"] > 0
    assert len(found["pressures"]) == 11


def test_silo_not_covered_by_the_us_pack():
    silo = Silo.model_validate(
        {"id": "S1", "diameter": 8.0, "height": 24.0, "concrete": "C24.1", "rebar": "B420DWR"}
    )
    with (
        code_context.using(_pack("aci318-asce7-22")),
        pytest.raises(ValueError, match="not covered"),
    ):
        sh.analyse_silo(silo, default_material_library())


def test_cylinder_pressure_shape():
    with code_context.using(_pack("eurocodes")):
        rows = _pack("eurocodes").table("shellStructures").coolingTowers.rows
    row = rows[-1]
    assert sh.pressure_coefficient(0.0, row) == pytest.approx(1.0)
    assert sh.pressure_coefficient(row.alphaMin, row) == pytest.approx(row.cpMin)
    assert sh.pressure_coefficient(180.0, row) == pytest.approx(row.cpBase)


def test_cantilever_first_mode():
    # a prismatic tube: f1 = 1.875² / (2π L²) √(EI / m)
    beam = {
        "z": np.linspace(0, 50, 41),
        "ei": np.full(41, 2.0e11),
        "mass": np.full(41, 5000.0),
    }
    f1, shape = sh.first_mode(beam)
    expected = 1.87510**2 / (2 * math.pi * 50**2) * math.sqrt(2.0e11 / 5000.0)
    assert f1 == pytest.approx(expected, rel=1e-3)
    assert shape[-1] == pytest.approx(1.0)


# ───────────────────────────── offshore ─────────────────────────────


def test_wave_number_deep_water():
    k = off.wave_number(8.0, 500.0)
    omega = 2 * math.pi / 8.0
    assert k == pytest.approx(omega**2 / 9.80665, rel=1e-6)


def test_stream_function_small_wave_close_to_airy():
    a = off.airy(0.5, 10.0, 30.0)
    s = off.stream_function(0.5, 10.0, 30.0)
    assert s.k == pytest.approx(a.k, rel=0.01)
    u_a = a.kinematics(0.0, 0.0)[0]
    u_s = s.kinematics(0.0, 0.0)[0]
    assert u_s == pytest.approx(u_a, rel=0.05)


def test_steep_stream_function_wave_crest_above_trough():
    s = off.stream_function(10.0, 10.0, 30.0)
    assert s.eta(0.0) > abs(s.eta(s.length / 2))  # a crest higher than the trough is deep
    assert s.eta(0.0) - s.eta(s.length / 2) == pytest.approx(10.0, rel=1e-4)


# ───────────────────────────── piping ─────────────────────────────


def test_piping_factors():
    t = _pack("aci318-asce7-22").table("pipingStress")
    assert pp.range_factor(t, 7000) == pytest.approx(1.0)
    assert pp.range_factor(t, 100000) == pytest.approx(6.0 * 100000**-0.2)
    h, ii, io = pp.bend_sif(t, 168.3, 7.11, 1.5 * 168.3)
    r2 = (168.3 - 7.11) / 2
    assert h == pytest.approx(7.11 * 1.5 * 168.3 / r2**2)
    assert ii == pytest.approx(max(1.0, 0.9 / h ** (2 / 3)))
    assert io == pytest.approx(max(1.0, 0.75 / h ** (2 / 3)))


def test_piping_l_bend_runs():
    system = PipingSystem.model_validate(
        {
            "id": "P1",
            "route": [
                {"x": 0, "y": 0, "z": 3},
                {"x": 12, "y": 0, "z": 3},
                {"x": 12, "y": 6, "z": 3},
            ],
            "outsideDiameter": 168.3,
            "wallThickness": 7.11,
            "pressure": 2.0,
            "temperature": 200,
            "supports": [
                {"at": 0, "kind": "anchor", "nozzle": True},
                {"at": 2, "kind": "anchor"},
            ],
        }
    )
    with code_context.using(_pack("aci318-asce7-22")):
        found = pp.analyse_piping(system)
    names = [r["name"] for r in found["rows"]]
    assert "Expansion stress range SE" in names
    assert found["nozzles"]


# ───────────────────────────── settings ─────────────────────────────


def test_settings_without_special_structures_unchanged():
    from saengine.library.settings import default_project_settings

    settings = default_project_settings()
    assert settings.specialStructures.is_empty()
    assert "specialStructures" not in settings.model_dump(mode="json", by_alias=True)


def test_special_structures_ids_unique():
    with pytest.raises(ValueError, match="duplicate"):
        SpecialStructures.model_validate(
            {
                "silos": [
                    {"id": "X", "diameter": 8, "height": 20, "concrete": "C", "rebar": "R"},
                    {"id": "X", "diameter": 8, "height": 20, "concrete": "C", "rebar": "R"},
                ]
            }
        )


def test_tower_quadratic_cf():
    from saengine.special.towers import _Coefficients

    with code_context.using(_pack("aci318-asce7-22")):
        c = _Coefficients()
        flat, rr = c.cf(0.2, "square", diagonal=False)
    assert flat == pytest.approx(4.0 * 0.04 - 5.9 * 0.2 + 4.0)  # TIA-222-H 2.6.11.2
    assert rr == pytest.approx(min(1.0, 0.51 * 0.04 + 0.57))


def test_tower_annex_b_cf():
    from saengine.special.towers import _Coefficients

    with code_context.using(_pack("eurocodes")):
        c = _Coefficients()
        flat, _ = c.cf(0.2, "square", diagonal=False)
    assert flat == pytest.approx(1.76 * 2.25 * (1 - 1.5 * 0.2 + 0.04))  # EN 1993-3-1 B.2.2

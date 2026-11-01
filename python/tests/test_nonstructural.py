"""Nonstructural components and wall anchorage: the bnbc2020 pack's values (BNBC 2020 Part 6 Sec
2.5.15, Tables 6.2.22-6.2.23, Sec 1.7.3.2(b), 1.7.3.6) and hand calculations of the engine."""

from __future__ import annotations

import pytest

from saengine.codes.tables import builtin_table
from saengine.design import nonstructural as ns
from saengine.design.nonstructural import Component, Ground
from saengine.library import default_project_settings
from saengine.library.architecture import Architecture
from saengine.library.mep import Equipment, MepModel, Plinth
from saengine.library.settings import code_pack, derived

T = builtin_table("nonstructural")


# ───────────────────────────── the pack's values, with their clauses ─────────────────────────────


def test_force_factors_eq_6_2_57():
    """Sec 2.5.15.3, Eq 6.2.57 (p. 651): ah = 0.67 Z S (as printed), 1 + 2 z/h, bounds 0.75 and
    1.5 ah Wc Ic, vertical ± 0.5 ah Wc, z/h ≤ 1."""
    f = T.force
    assert f.method == "amplifiedHeight"
    assert (f.groundFactor, f.heightFactor, f.minFactor, f.maxFactor) == (0.67, 2.0, 0.75, 1.5)
    assert (f.verticalFactor, f.zOverHMax) == (0.5, 1.0)


def test_importance_sec_2_5_15_1():
    assert (T.importance.essential, T.importance.default) == (1.5, 1.0)


@pytest.mark.parametrize(
    ("row", "alpha", "R"),
    [
        # Table 6.2.22 (pp. 654-655)
        ("interiorWallPlainMasonry", 1.0, 1.5),
        ("interiorWallOther", 1.0, 2.5),
        ("parapetCantilever", 2.5, 2.5),
        ("parapetBracedAbove", 1.0, 2.5),
        ("exteriorWall", 1.0, 2.5),
        ("exteriorFasteners", 1.25, 1.0),
        ("veneerLow", 1.0, 1.5),
        ("penthouse", 2.5, 3.5),
        ("accessFloorOther", 1.0, 1.5),
        ("otherFlexibleLow", 2.5, 1.5),
        ("otherRigidHigh", 1.0, 3.5),
        # Table 6.2.23 (pp. 656-657)
        ("hvacAirSide", 2.5, 6.0),
        ("hvacWetSide", 1.0, 2.5),
        ("electricalSheetMetal", 2.5, 6.0),
        ("roofTowerBracedBelow", 2.5, 3.0),
        ("lighting", 1.0, 1.5),
        ("isolatedSpring", 2.5, 2.0),
        ("pipingStandardWelded", 2.5, 12.0),
        ("pipingOtherThreaded", 2.5, 4.5),
        ("ductWelded", 2.5, 9.0),
        ("conduitPlumbing", 1.0, 2.5),
        ("cableTraySuspended", 2.5, 6.0),
    ],
)
def test_component_rows(row, alpha, R):
    assert (T.components[row].alpha, T.components[row].R) == (alpha, R)


def test_exemption_limits_sec_2_5_15():
    """Items (4) and (5) (pp. 649-650): 1.2 m and 1780 N; 89 N and 73 N/m."""
    by_id = {e.id: e for e in T.exemptions}
    assert by_id["4"].alternatives[1].maxMountHeight == 1200
    assert by_id["4"].alternatives[1].maxWeight == 1780
    assert by_id["5"].alternatives[0].maxWeight == 89
    assert by_id["5"].alternatives[1].maxWeightPerLength == 73


def test_other_rules():
    assert (T.interaction.share, T.interaction.period) == (0.25, 0.06)  # Sec 2.5.15
    assert (T.isolation.factor, T.isolation.clearance) == (2.0, 6.0)  # Table 6.2.23 note b
    c = T.connections  # Sec 1.7.3.2(b)
    assert (c.bodyFactor, c.fastenerFactor, c.jointDriftFactor, c.jointMinimum) == (
        1.33,
        4.0,
        2.0,
        12.0,
    )
    assert (T.anchorage.minimum, T.anchorage.maxSpacing) == (4.09, 1200.0)  # Sec 1.7.3.6


# ─────────────────────────────────────── hand calculations ───────────────────────────────────────

GROUND = Ground(a=0.2, Z=0.2, S=1.0, sdc="D", h=30000.0)


def _item(row: str, z: float, **kw) -> Component:
    return Component(id="C", name="C", row=row, weight=kw.pop("weight", 10.0), z=z, **kw)


def test_force_upper_bound_parapet():
    # 2.5 × 0.2 × 10 / 2.5 × (1 + 2) = 6.0 > 1.5 × 0.2 × 10 = 3.0
    r = ns.component_force(_item("parapetCantilever", 30000), GROUND)
    assert r["raw"] == pytest.approx(6.0)
    assert r["Fc"] == pytest.approx(3.0)
    assert r["Fv"] == pytest.approx(1.0)  # 0.5 × 0.2 × 10


def test_force_mid_height_and_lower_bound():
    # 1.0 × 0.2 × 10 / 1.5 × (1 + 2 × 0.5) = 2.667
    assert ns.component_force(_item("interiorWallPlainMasonry", 15000), GROUND)[
        "Fc"
    ] == pytest.approx(2.667, abs=1e-3)
    # at the base: 0.2 × 10 / 2.5 = 0.8 < 0.75 × 0.2 × 10 = 1.5
    assert ns.component_force(_item("exteriorWall", 0), GROUND)["Fc"] == pytest.approx(1.5)
    # z/h capped at 1 above the roof
    r = ns.component_force(_item("interiorWallOther", 45000), GROUND)
    assert r["zOverH"] == 1.0


def test_essential_importance():
    r = ns.component_force(_item("interiorWallOther", 15000, essential=True), GROUND)
    assert r["Ic"] == 1.5
    assert r["Fc"] == pytest.approx(1.0 * 0.2 * 10 * 1.5 / 2.5 * 2.0)


def test_isolators_double_force():
    wide = ns.component_force(_item("isolatedSpring", 0, isolator_clearance=10.0), GROUND)
    tight = ns.component_force(_item("isolatedSpring", 0, isolator_clearance=5.0), GROUND)
    assert wide["design"] == pytest.approx(2 * wide["Fc"])
    assert tight["design"] == pytest.approx(tight["Fc"])


def test_exemptions():
    def exempt(row, sdc, **kw):
        found = ns.exemption(_item(row, 0, **kw), sdc)
        return found.id if found else None

    assert exempt("hvacAirSide", "B") == "2"
    assert exempt("hvacAirSide", "C") == "3"
    assert exempt("hvacAirSide", "C", essential=True) is None
    assert exempt("hvacAirSide", "D", weight=1.5, mount=1000) == "4"
    assert exempt("hvacAirSide", "D", weight=2.0) is None
    assert exempt("hvacAirSide", "D", weight=2.0, flexible=True) == "4"
    # (5): a distribution run of 0.07 kN over 1 m with flexible connections, Category D
    assert exempt("conduitPlumbing", "D", weight=0.07, length=1000.0, flexible=True) == "4"
    assert exempt("interiorWallOther", "B") == "1"
    assert exempt("interiorWallOther", "C") is None
    assert exempt("parapetCantilever", "B", on_structural_wall=True) is None
    assert exempt("hvacAirSide", None) is None


def test_relative_displacements_eqs_6_2_58_61():
    one = ns.relative_displacement(30.0, 10.0, 6000.0, 3000.0, 0.02)
    assert (one["Dc"], one["max"], one["ok"]) == (20.0, 60.0, True)
    two = ns.relative_displacement_between(10.0, -15.0, 6000.0, 3000.0, 0.02, 0.015)
    assert (two["Dc"], two["max"]) == (25.0, 165.0)


def test_panel_connections_and_joints():
    forces = ns.connection_forces(1.0)
    assert forces == {"body": pytest.approx(1.33), "fasteners": pytest.approx(4.0)}
    assert ns.joint_movement(3.0) == 12.0
    assert ns.joint_movement(10.0) == 20.0


def test_anchorage_minimum_sec_1_7_3_6():
    a = ns.anchorage(2.0, spacing=1500.0)
    assert (a["design"], a["governs"], a["bending"]) == (4.09, "minimum", True)
    b = ns.anchorage(6.0, spacing=1000.0)
    assert (b["design"], b["governs"], b["bending"]) == (6.0, "force", False)


def test_interaction_share():
    assert ns.interaction_check([300.0], 1000.0)["interaction"] is True
    assert ns.interaction_check([200.0], 1000.0)["interaction"] is False


def test_ground_motion_uses_printed_factor():
    settings = default_project_settings()
    g = ns.ground_motion(settings)
    s = code_pack(settings).table("seismic").siteClasses[settings.site.siteClass].S
    assert g.a == pytest.approx(0.67 * derived(settings)["Z"] * s)


# ─────────────────────────────── architecture walls and equipment ───────────────────────────────

ELEVATIONS = {"BASE": 0.0, "L1": 3000.0, "ROOF": 6000.0}
G6 = Ground(a=0.2, Z=0.2, S=1.0, sdc="D", h=6000.0, drift_ratio=0.02)


def test_architecture_walls():
    arch = Architecture.model_validate(
        {
            "wallTypes": [
                {"id": "BW", "name": "Brick", "layers": [
                    {"material": "Brick", "thickness": 250, "unitWeight": 20.0}
                ]},
            ],
            "walls": [
                {"id": "W1", "type": "BW", "base": "L1", "path": [[0, 0], [4000, 0]]},
                {"id": "P1", "type": "BW", "base": "ROOF", "height": 1000,
                 "path": [[0, 0], [2000, 0]]},
                {"id": "X1", "type": "BW", "base": "BASE", "component": "exteriorWall",
                 "path": [[0, 0], [1000, 0]]},
            ],
        }
    )  # fmt: skip
    rows, notes = ns.architecture_components(arch, G6, ELEVATIONS)
    by_id = {r["id"]: r for r in rows}
    assert not notes
    w1 = by_id["W1"]  # 5 kN/m² × 3 m × 4 m = 60 kN, at its top z = h
    assert w1["row"] == "interiorWallPlainMasonry"
    assert w1["Wc"] == pytest.approx(60.0)
    # 1.0 × 0.2 × 60 / 1.5 × 3 = 24 > 1.5 × 0.2 × 60 = 18: 18 kN, 4.5 kN/m, 2.25 to each floor
    assert w1["Fc"] == pytest.approx(18.0)
    assert w1["anchorage"] == pytest.approx(2.25)
    p1 = by_id["P1"]  # a parapet, attached at its base (z = h)
    assert p1["row"] == "parapetCantilever"
    assert p1["anchorageShare"] == 1.0
    x1 = by_id["X1"]
    assert x1["row"] == "exteriorWall"
    assert x1["connections"]["fasteners"] == pytest.approx(4.0 * x1["design"], abs=1e-3)
    assert x1["joint"] == pytest.approx(120.0)  # 2 × 0.02 × 3000


def test_equipment_defaults_and_mep():
    from saengine.mep.loads import seismic_components

    tank = Equipment(
        id="T", kind="tank", story="ROOF", x=0, y=0, length=2000, width=2000,
        operatingWeight=100.0, plinth=Plinth(height=300, material="C"),
    )  # fmt: skip
    ahu = Equipment(
        id="A", kind="ahu", story="L1", x=0, y=0, length=1000, width=1000,
        operatingWeight=1.0, flexibleConnections=True,
    )  # fmt: skip
    rows, _ = seismic_components(MepModel(equipment=[tank, ahu]), G6, ELEVATIONS)
    by_id = {r["id"]: r for r in rows}
    assert by_id["T"]["row"] == "hvacWetSide"
    # 1.0 × 0.2 × 100 / 2.5 × 3 = 24, within 15 ... 30
    assert by_id["T"]["Fc"] == pytest.approx(24.0)
    assert by_id["A"]["row"] == "hvacAirSide"
    assert by_id["A"]["exempt"] == "4"


def test_report_section_shape(tmp_path):
    (tmp_path / "02 Project Settings").mkdir()
    (tmp_path / "02 Project Settings" / "project-settings.json").write_text(
        default_project_settings().model_dump_json(by_alias=True), encoding="utf-8"
    )
    assert ns.report_section(tmp_path) is None  # nothing to design

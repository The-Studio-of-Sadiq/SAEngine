"""Curtain walls, roofs, ramps and railings of the architecture (track T46): their weights, loads,
bill quantities and IFC, checked by hand on the one-bay frame of test_line_loads (A-B 6 m along
x, 1-2 5 m along y, 3.2 m stories, beams 300 x 500, slab 150 mm)."""

from __future__ import annotations

import math

import pytest
from test_architecture_loads import FINISH, WALL_TYPES, architecture
from test_line_loads import OBJECTS, plan

from saengine.fem import architecture_loads as al
from saengine.library import architecture as arch_lib
from saengine.library import default_material_library
from saengine.library.bim import generate

CURTAIN = {"id": "CW1", "name": "Curtain wall"}
#: 40 mm cement screed at 20.4 kN/m³ + 5 mm membrane at 12 kN/m³ = 0.816 + 0.060 = 0.876 kN/m².
ROOF_TYPE = {
    "id": "RF2",
    "name": "Screed and waterproofing",
    "layers": [
        {"material": "Cement screed", "thickness": 40, "unitWeight": 20.4},
        {"material": "Waterproofing membrane", "thickness": 5, "unitWeight": 12},
    ],
}
RAILING_TYPE = {"id": "RL1", "name": "Steel railing", "height": 1000, "weight": 0.3}
BAY = [[0, 0], [6000, 0], [6000, 5000], [0, 5000]]


def extras(**parts):
    return architecture(
        curtainWallTypes=[CURTAIN], roofTypes=[ROOF_TYPE], railingTypes=[RAILING_TYPE], **parts
    )


def test_type_weights_by_hand() -> None:
    curtain = arch_lib.CurtainWallType.model_validate(CURTAIN)
    # Glass 12 mm × 25 kN/m³ = 0.30 kN/m², + 0.15 kN/m² of frame = 0.45 kN/m².
    assert curtain.weight == pytest.approx(0.45)
    assert curtain.thickness == 150 and curtain.locationLine == "center"
    assert arch_lib.RoofType.model_validate(ROOF_TYPE).weight == pytest.approx(0.876)
    defaults = arch_lib.default_architecture()
    assert [t.id for t in defaults.curtainWallTypes] == ["CW1"]
    assert [t.id for t in defaults.roofTypes] == ["RF1", "RF2"]
    assert [t.id for t in defaults.railingTypes] == ["RL1", "RL2"]


def test_references_of_the_extras_are_checked() -> None:
    with pytest.raises(ValueError, match="no curtain wall type"):
        extras(curtainWalls=[{"id": "C1", "type": "X", "base": "L1", "path": [[0, 0], [1, 0]]}])
    with pytest.raises(ValueError, match="no roof type"):
        extras(roofs=[{"id": "RF", "type": "X", "story": "L1", "outline": BAY}])
    with pytest.raises(ValueError, match="no railing type"):
        extras(railings=[{"id": "RL", "type": "X", "base": "L1", "path": [[0, 0], [1, 0]]}])
    with pytest.raises(ValueError, match="no floor finish"):
        extras(ramps=[{"id": "RP", "story": "L1", "start": [0, 0], "end": [1, 0], "finish": "X"}])
    with pytest.raises(ValueError, match="has no length"):
        extras(ramps=[{"id": "RP", "story": "L1", "start": [0, 0], "end": [0, 0]}])


def test_curtain_wall_and_railing_on_a_beam_by_hand() -> None:
    arch = extras(
        curtainWalls=[
            {"id": "CW", "type": "CW1", "base": "L1", "height": 3000, "path": [[0, 0], [6000, 0]]}
        ],
        railings=[{"id": "RL", "type": "RL1", "base": "L1", "path": [[0, 5000], [6000, 5000]]}],
    )
    loads = al.architecture_loads(arch, generate(plan(2), "s"), OBJECTS)
    by_source = {line.source: line for line in loads.lines}
    # Curtain wall: 0.45 kN/m² × 3.0 m = 1.35 kN/m on the A-1 to B-1 beam.
    assert by_source["CW"].member == "B11"
    assert by_source["CW"].load / 1e3 == pytest.approx(1.35, rel=1e-9)
    # Railing: its 0.3 kN/m on the beam under it.
    assert by_source["RL"].load / 1e3 == pytest.approx(0.3, rel=1e-9)
    # A facade and a railing are not partitions: L1 keeps its partition allowance.
    assert loads.walled == set()


def test_curtain_wall_bounds_rooms() -> None:
    arch = extras(
        curtainWalls=[{"id": "CW", "type": "CW1", "base": "L1", "path": [*BAY, [0, 0]]}],
        rooms=[{"id": "R1", "story": "L1", "point": [3000, 2500]}],
    )
    elevations = {"BASE": 0.0, "L1": 3200.0, "L2": 6400.0}
    face, net = arch_lib.room_boundary(arch, arch.rooms[0], elevations)
    assert face.area == pytest.approx(30e6, rel=1e-6)
    # Net: inside the 150 mm mullions, (6.0 − 0.15) × (5.0 − 0.15) = 28.3725 m².
    assert net.area == pytest.approx(5850 * 4850, rel=1e-6)


def test_roof_covering_and_live_load_by_hand() -> None:
    roof = {"id": "RF", "type": "RF2", "story": "L2", "outline": BAY}
    loads = al.architecture_loads(extras(roofs=[roof]), generate(plan(2), "s"), OBJECTS)
    [load] = loads.rooms
    assert load.finish == pytest.approx(0.876) and load.live is None
    assert load.polygon.area == pytest.approx(30e6)
    # Pitched 30°: 0.876 / cos 30° = 1.01152 kN/m² of plan.
    pitched = al.architecture_loads(
        extras(roofs=[{**roof, "slope": 30}]), generate(plan(2), "s"), OBJECTS
    )
    assert pitched.rooms[0].finish == pytest.approx(0.876 / math.cos(math.radians(30)))
    plan_area, surface = arch_lib.roof_area(arch_lib.Roof.model_validate({**roof, "slope": 30}))
    assert surface == pytest.approx(plan_area / math.cos(math.radians(30)))


def test_ramp_fill_finish_and_rooms_by_hand() -> None:
    from test_architecture_loads import SEPARATORS

    ramp = {
        "id": "RP",
        "story": "L1",
        "start": [1000, 2500],
        "end": [3000, 2500],
        "width": 1500,
        "rise": 400,
        "finish": "SCT",
    }
    arch = extras(
        separators=SEPARATORS,
        rooms=[{"id": "R1", "story": "L1", "point": [500, 500], "floorFinish": "SCT"}],
        ramps=[ramp],
    )
    model = arch_lib.Ramp.model_validate(ramp)
    # 400 mm over 2 m: 1 in 5.
    assert arch_lib.ramp_gradient(model) == pytest.approx(0.2)
    assert arch_lib.ramp_length(model) == pytest.approx(math.hypot(2000, 400))
    loads = al.architecture_loads(arch, generate(plan(2), "s"), OBJECTS)
    room, ramp_load = loads.rooms
    # Fill: 0.4 / 2 m × 16 kN/m³ = 3.2 kN/m², + the 1.26 kN/m² finish = 4.46 kN/m² over 3 m².
    assert ramp_load.room == "RP" and ramp_load.finish == pytest.approx(4.46)
    assert ramp_load.polygon.area == pytest.approx(3e6)
    # The ramp sits in R1 (4 x 5 m): the room keeps 20 − 3 = 17 m².
    assert room.polygon.area == pytest.approx(17e6)


def test_boq_of_the_extras_by_hand() -> None:
    from saengine.boq.quantities import bill_of_quantities

    arch = arch_lib.Architecture.model_validate(
        {
            "wallTypes": WALL_TYPES,
            "finishTypes": [FINISH],
            "curtainWallTypes": [CURTAIN],
            "roofTypes": [ROOF_TYPE],
            "railingTypes": [RAILING_TYPE],
            "curtainWalls": [
                {"id": "CW", "type": "CW1", "base": "L1", "path": [[0, 0], [6000, 0]]}
            ],
            "roofs": [{"id": "RF", "type": "RF2", "story": "L2", "outline": BAY, "slope": 30}],
            "ramps": [
                {
                    "id": "RP",
                    "story": "L1",
                    "start": [1000, 2500],
                    "end": [3000, 2500],
                    "width": 1500,
                    "rise": 400,
                    "finish": "SCT",
                }
            ],
            "railings": [
                {"id": "RL", "type": "RL1", "base": "L1", "path": [[0, 5000], [6000, 5000]]}
            ],
        }
    )
    bill = bill_of_quantities(
        generate(plan(2), "s"), OBJECTS, default_material_library(), architecture=arch
    )
    items = {i.description: i for i in bill.items}

    def quantity(start: str) -> float:
        return sum(i.quantity for d, i in items.items() if d.startswith(start))

    # Curtain wall: 6.0 m × 3.2 m (L1 to L2) = 19.2 m².
    assert quantity("Curtain wall CW1") == pytest.approx(19.2, abs=1e-6)
    # Roof at 30°: 30 m² / cos 30° = 34.641 m² for each of its two layers.
    assert quantity("Roof covering: Cement screed") == pytest.approx(30 / math.cos(math.pi / 6))
    # Ramp: fill 3.0 m² × 0.2 m = 0.6 m³; finish 3.0 × 2.0396 / 2.0 = 3.0594 m² along the slope.
    assert quantity("Filling under ramps") == pytest.approx(0.6)
    # The bill gives quantities to 3 decimals.
    assert quantity("Ramp finish") == pytest.approx(3.0 * math.hypot(2.0, 0.4) / 2.0, abs=5e-4)
    assert quantity("Railing RL1") == pytest.approx(6.0)


def test_ifc_export_of_the_extras() -> None:
    from test_architecture import _export, flat

    # The default types (CW1, RF2, RL1) with the test box of walls and rooms.
    arch = flat(
        curtainWalls=[
            {
                "id": "CW",
                "type": "CW1",
                "base": "L1",
                "height": 3000,
                "path": [[0, -500], [6000, -500]],
            }
        ],
        roofs=[{"id": "RF", "type": "RF2", "story": "L1", "outline": BAY}],
        ramps=[{"id": "RP", "story": "L1", "start": [1000, 2500], "end": [3000, 2500]}],
        railings=[{"id": "RL", "type": "RL1", "base": "L1", "path": [[0, 5000], [6000, 5000]]}],
    )
    file = _export(arch)
    assert [e.Tag for e in file.by_type("IfcCurtainWall")] == ["CW"]
    assert [(e.Tag, e.PredefinedType) for e in file.by_type("IfcRoof")] == [("RF", "FLAT_ROOF")]
    assert [e.Tag for e in file.by_type("IfcRamp")] == ["RP"]
    assert [(e.Tag, e.PredefinedType) for e in file.by_type("IfcRailing")] == [("RL", "GUARDRAIL")]


# ───────────────────────────── R1: footprint roofs, ceilings, curtain walls ─────────────────────────────


def test_hip_roof_10x6_at_30_deg_by_hand() -> None:
    # 10 x 6 m rectangle, all 4 edges sloping at 30°:
    # - Half-width = 3 m; ridge height = 3.0 * tan 30° = 3 / sqrt(3) = 1.73205 m.
    # - Ridge length = 10 - 2 * 3 = 4 m (4000 mm).
    # - Plan area = 10 * 6 = 60 m²; sloped area = 60 / cos 30° = 69.28203 m².
    # - 4 faces (two 10-m trapezoids of 21 m² plan, two 6-m triangles of 9 m² plan).
    # - RF2 covering = 0.876 kN/m² on slope -> 0.876 / cos 30° = 1.01152 kN/m² of plan.
    from saengine.boq.quantities import bill_of_quantities

    rect = [[0, 0], [10000, 0], [10000, 6000], [0, 6000]]
    roof = arch_lib.Roof.model_validate(
        {
            "id": "RF_HIP",
            "type": "RF2",
            "story": "L2",
            "outline": rect,
            "edgeSlopes": [30, 30, 30, 30],
        }
    )
    geom = arch_lib.roof_geometry(roof)
    assert geom.kind == "hip"
    assert len(geom.faces) == 4
    assert all(f.slope == pytest.approx(30.0) for f in geom.faces)
    assert geom.plan_area == pytest.approx(60e6, rel=1e-6)
    assert geom.sloped_area == pytest.approx(60e6 / math.cos(math.radians(30)), rel=1e-6)
    assert geom.sloped_area / 1e6 == pytest.approx(69.282, abs=1e-3)
    ridges = [ln for ln in geom.lines if ln.kind == "ridge"]
    hips = [ln for ln in geom.lines if ln.kind == "hip"]
    assert len(ridges) == 1 and ridges[0].length_plan == pytest.approx(4000.0, abs=1.0)
    assert len(hips) == 4
    assert geom.max_height == pytest.approx(3000.0 * math.tan(math.radians(30)), abs=1.0)

    # Same 10 x 6 m roof in loads and BOQ over a 10 x 6 m plan? Check on the 6 x 5 m bay with RF2:
    # Over the 6 x 5 m bay, 30° hip has plan area 30 m², sloped area 30 / cos 30° = 34.641 m².
    bay_hip = {
        "id": "RF",
        "type": "RF2",
        "story": "L2",
        "outline": BAY,
        "edgeSlopes": [30, 30, 30, 30],
    }
    arch = extras(roofs=[bay_hip])
    loads = al.architecture_loads(arch, generate(plan(2), "s"), OBJECTS)
    assert loads.rooms[0].finish == pytest.approx(0.876 / math.cos(math.radians(30)))
    bill = bill_of_quantities(
        generate(plan(2), "s"), OBJECTS, default_material_library(), architecture=arch
    )
    screed = next(i for i in bill.items if i.description.startswith("Roof covering: Cement screed"))
    assert screed.quantity == pytest.approx(30.0 / math.cos(math.radians(30)), abs=1e-3)


def test_gable_roof_10x6_at_30_deg_by_hand() -> None:
    # 10 x 6 m rectangle with the 6 m ends (edges 1 and 3) non-sloping (0°), 10 m eaves at 30°:
    # - Ridge spans the full length: 10 m (10000 mm) at y = 3 m, height = 3.0 * tan 30°.
    # - Plan area = 60 m²; sloped area = 60 / cos 30° = 69.28203 m² (two 10 x 3 m plan rectangles).
    rect = [[0, 0], [10000, 0], [10000, 6000], [0, 6000]]
    roof = arch_lib.Roof.model_validate(
        {
            "id": "RF_GAB",
            "type": "RF2",
            "story": "L2",
            "outline": rect,
            "edgeSlopes": [30, 0, 30, 0],
        }
    )
    geom = arch_lib.roof_geometry(roof)
    assert geom.kind == "gable"
    assert len(geom.faces) == 2
    assert all(f.slope == pytest.approx(30.0) for f in geom.faces)
    assert geom.plan_area == pytest.approx(60e6, rel=1e-6)
    assert geom.sloped_area == pytest.approx(60e6 / math.cos(math.radians(30)), rel=1e-6)
    assert geom.sloped_area / 1e6 == pytest.approx(69.282, abs=1e-3)
    ridges = [ln for ln in geom.lines if ln.kind == "ridge"]
    rakes = [ln for ln in geom.lines if ln.kind == "rake"]
    assert len(ridges) == 1 and ridges[0].length_plan == pytest.approx(10000.0, abs=1.0)
    assert len(rakes) == 4


def _assert_faces_planar_and_sloped(
    geom: arch_lib.roof_geometry.RoofGeometry, expected_plan: float, slope_deg: float
) -> None:
    assert geom.plan_area == pytest.approx(expected_plan, rel=1e-4)
    assert geom.sloped_area == pytest.approx(
        expected_plan / math.cos(math.radians(slope_deg)), rel=1e-4
    )
    for face in geom.faces:
        assert face.slope == pytest.approx(slope_deg)
        nx, ny, nz = face.normal
        # Every vertex of a face must lie on the same plane n · p = const.
        dots = [nx * x + ny * y + nz * z for x, y, z in face.vertices]
        assert max(dots) - min(dots) < 1e-2


def test_l_and_t_shaped_hip_roofs_by_hand() -> None:
    # 1) Equal-wing L-shape: 10 x 4 m + 4 x 6 m = 64 m² plan, all edges 30° -> 64 / cos 30° = 73.8999 m².
    l_equal = [[0, 0], [10000, 0], [10000, 4000], [4000, 4000], [4000, 10000], [0, 10000]]
    g1 = arch_lib.roof_geometry(
        arch_lib.Roof.model_validate(
            {"id": "L1", "type": "RF2", "story": "L2", "outline": l_equal, "edgeSlopes": [30] * 6}
        )
    )
    _assert_faces_planar_and_sloped(g1, 64e6, 30.0)
    assert any(ln.kind == "valley" for ln in g1.lines)

    # 2) Unequal-wing L-shape: 12 x 6 m + 4 x 4 m = 88 m² plan, all edges 30°.
    l_unequal = [[0, 0], [12000, 0], [12000, 6000], [4000, 6000], [4000, 10000], [0, 10000]]
    g2 = arch_lib.roof_geometry(
        arch_lib.Roof.model_validate(
            {"id": "L2", "type": "RF2", "story": "L2", "outline": l_unequal, "edgeSlopes": [30] * 6}
        )
    )
    _assert_faces_planar_and_sloped(g2, 88e6, 30.0)
    assert any(ln.kind == "valley" for ln in g2.lines)

    # 3) T-shape (equal wings 4 m wide: 4 x 6 stem + 10 x 4 bar = 64 m²), all edges 30°.
    t_equal = [
        [3000, 0],
        [7000, 0],
        [7000, 6000],
        [10000, 6000],
        [10000, 10000],
        [0, 10000],
        [0, 6000],
        [3000, 6000],
    ]
    g3 = arch_lib.roof_geometry(
        arch_lib.Roof.model_validate(
            {"id": "T1", "type": "RF2", "story": "L2", "outline": t_equal, "edgeSlopes": [30] * 8}
        )
    )
    _assert_faces_planar_and_sloped(g3, 64e6, 30.0)
    assert sum(1 for ln in g3.lines if ln.kind == "valley") == 2

    # 4) Unequal T-shape (4 x 6 stem + 10 x 6 bar = 84 m²), all edges 30°.
    t_unequal = [
        [3000, 0],
        [7000, 0],
        [7000, 6000],
        [10000, 6000],
        [10000, 12000],
        [0, 12000],
        [0, 6000],
        [3000, 6000],
    ]
    g4 = arch_lib.roof_geometry(
        arch_lib.Roof.model_validate(
            {"id": "T2", "type": "RF2", "story": "L2", "outline": t_unequal, "edgeSlopes": [30] * 8}
        )
    )
    _assert_faces_planar_and_sloped(g4, 84e6, 30.0)


def test_shed_mansard_drainage_and_overhang_roofs_by_hand() -> None:
    rect = [[0, 0], [10000, 0], [10000, 6000], [0, 6000]]

    # Shed: 1 edge at 20°, others 0° -> 1 sloped face of 60 / cos 20° m².
    shed = arch_lib.roof_geometry(
        arch_lib.Roof.model_validate(
            {"id": "SH", "type": "RF2", "story": "L2", "outline": rect, "edgeSlopes": [20, 0, 0, 0]}
        )
    )
    assert shed.kind == "shed"
    assert len(shed.faces) == 1
    assert shed.sloped_area == pytest.approx(60e6 / math.cos(math.radians(20)), rel=1e-5)

    # Mansard: lower 60° up to breakHeight = 1000 * tan 60° (1 m horizontal inset -> 8 x 4 = 32 m² upper),
    # upper 15°. Lower plan = 60 - 32 = 28 m² -> sloped 28 / cos 60° = 56 m²; upper sloped = 32 / cos 15°.
    break_h = 1000.0 * math.tan(math.radians(60))
    mansard = arch_lib.roof_geometry(
        arch_lib.Roof.model_validate(
            {
                "id": "MN",
                "type": "RF2",
                "story": "L2",
                "outline": rect,
                "edgeSlopes": [60, 60, 60, 60],
                "breakHeight": break_h,
                "upperSlope": 15,
            }
        )
    )
    assert mansard.kind == "mansard"
    assert mansard.plan_area == pytest.approx(60e6, rel=1e-4)
    expected_mansard = 28e6 / math.cos(math.radians(60)) + 32e6 / math.cos(math.radians(15))
    assert mansard.sloped_area == pytest.approx(expected_mansard, rel=1e-4)

    # Flat with 2° drainage fall: plan 60 m², sloped = 60 / cos 2°.
    drain = arch_lib.roof_geometry(
        arch_lib.Roof.model_validate(
            {"id": "DR", "type": "RF2", "story": "L2", "outline": rect, "drainageSlope": 2.0}
        )
    )
    assert drain.kind == "flat"
    assert drain.plan_area == pytest.approx(60e6, rel=1e-6)
    assert drain.sloped_area == pytest.approx(60e6 / math.cos(math.radians(2.0)), rel=1e-6)

    # 500 mm overhang around 10 x 6 m hip at 30° -> outer 11 x 7 m = 77 m², sloped = 77 / cos 30°.
    over = arch_lib.roof_geometry(
        arch_lib.Roof.model_validate(
            {
                "id": "OH",
                "type": "RF2",
                "story": "L2",
                "outline": rect,
                "edgeSlopes": [30, 30, 30, 30],
                "overhang": 500,
            }
        )
    )
    assert over.plan_area == pytest.approx(77e6, rel=1e-5)
    assert over.sloped_area == pytest.approx(77e6 / math.cos(math.radians(30)), rel=1e-5)


def test_ceiling_void_and_boq_by_hand() -> None:
    # One-bay plan: BASE at 0 mm, L1 at 3600 mm, slab S1 150 mm thick at L1 -> soffit at 3450 mm.
    # Room R1 enclosed by walls on BASE; ceiling CL1 at 2700 mm above BASE:
    # Ceiling void = (3600 - 150) - 2700 = 750 mm (0.75 m).
    from saengine.boq.quantities import bill_of_quantities
    from saengine.library import FloorPlan
    from saengine.library.mep import MepModel
    from saengine.mep.rooms import check_ceiling_voids

    fp_data = plan(1).model_dump(mode="json", by_alias=True)
    fp_data["stories"][1]["elevation"] = 3600
    building = generate(FloorPlan.model_validate(fp_data), "s")

    arch = arch_lib.Architecture.model_validate(
        {
            **arch_lib.default_architecture().model_dump(
                mode="json", by_alias=True, exclude_none=True
            ),
            "walls": [
                {
                    "id": "AW1",
                    "type": "BW250",
                    "base": "BASE",
                    "path": [[0, 0], [6000, 0], [6000, 5000], [0, 5000], [0, 0]],
                }
            ],
            "rooms": [{"id": "R1", "story": "BASE", "point": [3000, 2500], "name": "Office"}],
            "ceilings": [
                {
                    "id": "CL_OFF",
                    "type": "CL2",
                    "story": "BASE",
                    "height": 2700,
                    "room": "R1",
                    "openings": [
                        {
                            "id": "OP1",
                            "outline": [[4000, 3000], [5000, 3000], [5000, 4000], [4000, 4000]],
                        }
                    ],
                }
            ],
        }
    )

    assert arch_lib.ceiling_void(arch, building, OBJECTS, "R1") == pytest.approx(750.0)
    assert arch_lib.ceiling_void(arch, building, OBJECTS, arch.rooms[0]) == pytest.approx(750.0)
    assert arch_lib.ceiling_void(
        arch, building, OBJECTS, [3000, 2500], story="BASE"
    ) == pytest.approx(750.0)

    void = arch_lib.ceiling_void_check(arch, building, OBJECTS, "R1")
    assert void is not None
    assert void.void_depth == pytest.approx(750.0)
    assert void.fits(400, clearance=50)
    assert void.margin(400, clearance=50) == pytest.approx(300.0)
    assert not void.fits(800)

    # MEP side queries void vs duct depth (400 mm passes, 800 mm fails).
    mep = MepModel.model_validate(
        {
            "hvac": {
                "ducts": [
                    {
                        "id": "DT1",
                        "story": "BASE",
                        "path": [[1000, 2500], [5000, 2500]],
                        "width": 500,
                        "height": 400,
                    },
                    {
                        "id": "DT2",
                        "story": "BASE",
                        "path": [[1000, 2500], [5000, 2500]],
                        "width": 500,
                        "height": 800,
                    },
                ]
            }
        }
    )
    checks = check_ceiling_voids(arch, building, mep, objects=OBJECTS, clearance=50.0)
    assert [(c["service"], c["ok"], c["margin"]) for c in checks] == [
        ("DT1", True, 300.0),
        ("DT2", False, -100.0),
    ]

    # Net room area inside 274 mm outer walls = (6.0 - 0.274) * (5.0 - 0.274) = 5.726 * 4.726 = 27.061076 m².
    # Less 1.0 * 1.0 m opening = 26.061076 m².
    bill = bill_of_quantities(building, OBJECTS, default_material_library(), architecture=arch)
    ceil_item = next(i for i in bill.items if i.description.startswith("Ceiling CL2"))
    assert ceil_item.quantity == pytest.approx(5.726 * 4.726 - 1.0, abs=1e-3)


def test_curtain_wall_grid_panels_mullions_and_beam_load_by_hand() -> None:
    # Curtain wall 6.0 m long x 3.6 m high:
    # - Vertical grid: maxSpacing = 1500 mm -> 4 bays of 1.5 m -> 5 vertical mullions (5 * 3.6 = 18.0 m).
    # - Horizontal grid: fixedNumber = 2 -> 3 rows of 1.2 m -> 4 horizontal transoms (4 * 6.0 = 24.0 m).
    # - 4 x 3 = 12 panels, each 1.5 * 1.2 = 1.8 m², total 21.6 m².
    # - Glazed panel 0.30 kN/m² -> 21.6 * 0.30 = 6.48 kN.
    # - Vertical mullions 0.05 kN/m (18 * 0.05 = 0.90 kN) + transoms 0.04 kN/m (24 * 0.04 = 0.96 kN) = 1.86 kN.
    # - Total weight = 6.48 + 1.86 = 8.34 kN -> line load on B11 = 8.34 / 6.0 = 1.39 kN/m.
    arch = arch_lib.Architecture.model_validate(
        {
            "curtainPanelTypes": [
                {"id": "PG", "name": "Glazed", "kind": "glazed", "thickness": 12, "weight": 0.30},
                {
                    "id": "PS",
                    "name": "Solid spandrel",
                    "kind": "solid",
                    "thickness": 25,
                    "weight": 0.50,
                },
            ],
            "curtainMullionTypes": [
                {
                    "id": "MV",
                    "name": "Vertical mullion",
                    "width": 50,
                    "depth": 150,
                    "weightPerMetre": 0.05,
                },
                {
                    "id": "MH",
                    "name": "Horizontal transom",
                    "width": 50,
                    "depth": 120,
                    "weightPerMetre": 0.04,
                },
            ],
            "curtainWallTypes": [
                {
                    "id": "CWG",
                    "name": "Unitised 4x3",
                    "verticalGrid": {"layout": "maxSpacing", "spacing": 1500},
                    "horizontalGrid": {"layout": "fixedNumber", "count": 2},
                    "panelType": "PG",
                    "verticalMullion": "MV",
                    "horizontalMullion": "MH",
                }
            ],
            "curtainWalls": [
                {
                    "id": "CW",
                    "type": "CWG",
                    "base": "L1",
                    "height": 3600,
                    "path": [[0, 0], [6000, 0]],
                }
            ],
        }
    )
    layout = arch_lib.curtain_wall_layout(arch, arch.curtainWalls[0])
    assert layout is not None
    assert (layout.columns, layout.rows) == (4, 3)
    assert len(layout.panels) == 12
    assert len(layout.mullions) == 9  # 5 vertical + 4 horizontal
    assert layout.panels_weight == pytest.approx(6.48, rel=1e-9)
    assert layout.mullions_weight == pytest.approx(1.86, rel=1e-9)
    assert layout.total_weight == pytest.approx(8.34, rel=1e-9)
    assert layout.line_load == pytest.approx(1.39, rel=1e-9)

    loads = al.architecture_loads(arch, generate(plan(2), "s"), OBJECTS)
    [line] = loads.lines
    assert line.member == "B11"
    assert line.load / 1e3 == pytest.approx(1.39, rel=1e-9)

    # Override one panel (1.8 m²) from 0.30 to 0.50 kN/m² (+0.36 kN -> 8.70 kN -> 1.45 kN/m).
    arch_ov = arch.model_copy(
        update={
            "curtainWalls": [
                arch.curtainWalls[0].model_copy(
                    update={
                        "panelOverrides": [
                            arch_lib.CurtainPanelOverride(
                                segment=0, column=1, row=1, panelType="PS"
                            )
                        ]
                    }
                )
            ]
        }
    )
    ov_loads = al.architecture_loads(arch_ov, generate(plan(2), "s"), OBJECTS)
    assert ov_loads.lines[0].load / 1e3 == pytest.approx(1.45, rel=1e-9)


def test_ifc_export_r1_roof_ceiling_curtain_wall() -> None:
    import ifcopenshell.geom
    from test_architecture import _export, flat

    rect = [[0, 0], [10000, 0], [10000, 6000], [0, 6000]]
    base_arch = flat()
    data = base_arch.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["curtainPanelTypes"] = [
        {"id": "PG", "name": "Glazed", "kind": "glazed", "thickness": 12, "weight": 0.30}
    ]
    data["curtainMullionTypes"] = [
        {"id": "MV", "name": "Mullion", "width": 50, "depth": 150, "weightPerMetre": 0.05}
    ]
    data["curtainWallTypes"].append(
        {
            "id": "CWG",
            "name": "Grid wall",
            "verticalGrid": {"layout": "maxSpacing", "spacing": 1500},
            "horizontalGrid": {"layout": "fixedNumber", "count": 2},
            "panelType": "PG",
            "verticalMullion": "MV",
            "horizontalMullion": "MV",
        }
    )
    data["curtainWalls"] = [
        {"id": "CW", "type": "CWG", "base": "L1", "height": 3600, "path": [[0, -500], [6000, -500]]}
    ]
    data["ceilings"] = [{"id": "CL_R2", "type": "CL2", "story": "L1", "height": 2700, "room": "R2"}]
    data["roofs"] = [
        {
            "id": "RF_HIP",
            "type": "RF2",
            "story": "L2",
            "outline": rect,
            "edgeSlopes": [30, 30, 30, 30],
        }
    ]
    arch = arch_lib.Architecture.model_validate(data)
    file = _export(arch)

    [ifc_roof] = file.by_type("IfcRoof")
    assert ifc_roof.PredefinedType == "HIP_ROOF"
    roof_slabs = [s for s in file.by_type("IfcSlab") if s.PredefinedType == "ROOF"]
    assert len(roof_slabs) == 4

    ceilings = [c for c in file.by_type("IfcCovering") if c.PredefinedType == "CEILING"]
    assert any(c.Tag == "CL_R2" for c in ceilings)

    [ifc_cw] = file.by_type("IfcCurtainWall")
    assert ifc_cw.Tag == "CW"
    plates = file.by_type("IfcPlate")
    members = file.by_type("IfcMember")
    assert len(plates) == 12
    assert len(members) == 9

    settings = ifcopenshell.geom.settings()
    for part in [*roof_slabs[:1], ceilings[-1], plates[0], members[0]]:
        shape = ifcopenshell.geom.create_shape(settings, part)
        assert len(shape.geometry.verts) > 0

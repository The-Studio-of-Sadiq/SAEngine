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
    assert quantity("Ramp finish") == pytest.approx(3.0 * math.hypot(2.0, 0.4) / 2.0)
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

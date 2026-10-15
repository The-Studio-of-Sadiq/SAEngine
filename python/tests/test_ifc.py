"""IFC export of the building model (IfcOpenShell)."""

from __future__ import annotations

import ifcopenshell
import ifcopenshell.geom
import numpy as np

from saengine.library import BuildingModel, FloorPlan, ObjectLibrary, default_floor_plan
from saengine.library.bim import Additions, generate
from saengine.library.ifc import export_ifc, global_id
from saengine.rpc.handlers import building_ifc

OBJECTS = ObjectLibrary.model_validate(
    {
        "objects": [
            {
                "id": "COL",
                "name": "Column 400x600",
                "kind": "column",
                "material": "C24",
                "profile": {"shape": "rectangle", "xDim": 400, "yDim": 600},
            },
            {
                "id": "BM",
                "name": "Beam I",
                "kind": "beam",
                "material": "S275",
                "profile": {
                    "shape": "I",
                    "overallWidth": 150,
                    "overallDepth": 300,
                    "webThickness": 7,
                    "flangeThickness": 10,
                },
            },
            {"id": "SL", "name": "Slab 150", "kind": "slab", "material": "C24", "thickness": 150},
            {"id": "WL", "name": "Wall 200", "kind": "wall", "material": "C24", "thickness": 200},
            {
                "id": "FT",
                "name": "Pad 2x1.5",
                "kind": "footing",
                "material": "C24",
                "length": 2000,
                "width": 1500,
                "thickness": 500,
            },
        ]
    }
)

PLAN = FloorPlan.model_validate(
    {
        **default_floor_plan().model_dump(mode="json", by_alias=True),
        "columns": [
            {
                "id": "C1",
                "type": "COL",
                "at": {"x": "B", "y": "1"},
                "base": "BASE",
                "top": "L1",
                "rotation": 90,
            }
        ],
        "beams": [
            {
                "id": "B1",
                "type": "BM",
                "story": "L1",
                "start": {"x": "A", "y": "1"},
                "end": {"x": "B", "y": "1"},
            }
        ],
        "walls": [
            {
                "id": "W1",
                "type": "WL",
                "base": "BASE",
                "top": "L1",
                "start": {"x": "A", "y": "1"},
                "end": {"x": "A", "y": "2"},
            }
        ],
        "slabs": [
            {
                "id": "S1",
                "type": "SL",
                "story": "L1",
                "boundary": [
                    {"x": "A", "y": "1"},
                    {"x": "B", "y": "1"},
                    {"x": "B", "y": "2"},
                    {"x": "A", "y": "2"},
                ],
            }
        ],
        "footings": [{"id": "F1", "type": "FT", "story": "BASE", "at": {"x": "A", "y": "1"}}],
    }
)


def bounds(file: ifcopenshell.file) -> dict[str, list[list[float]]]:
    """World bounding box of every element in mm, by name."""
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    result = {}
    for element in file.by_type("IfcElement"):
        verts = np.array(ifcopenshell.geom.create_shape(settings, element).geometry.verts).reshape(
            -1, 3
        )
        result[element.Name] = [
            list(np.round(verts.min(0) * 1000)),
            list(np.round(verts.max(0) * 1000)),
        ]
    return result


def test_elements_are_placed_with_their_sections() -> None:
    file, ids, skipped = export_ifc(generate(PLAN, "s"), OBJECTS, None, "Test")
    assert skipped == []
    assert ids == {key: global_id(key) for key in ["C1", "B1", "W1", "S1", "F1"]}
    assert {
        e.Name: (e.is_a(), e.ContainedInStructure[0].RelatingStructure.Name)
        for e in file.by_type("IfcElement")
    } == {
        "C1": ("IfcColumn", "Base"),
        "B1": ("IfcBeam", "Level 1"),
        "W1": ("IfcWall", "Base"),
        "S1": ("IfcSlab", "Level 1"),
        "F1": ("IfcFooting", "Base"),
    }
    assert bounds(file) == {
        # 400 x 600 rotated 90 degrees about B-1 (6000, 0), from Base to Level 1.
        "C1": [[5700, -200, 0], [6300, 200, 3200]],
        # I 150 x 300 hanging from Level 1 between A-1 and B-1.
        "B1": [[0, -75, 2900], [6000, 75, 3200]],
        "W1": [[-100, 0, 0], [100, 5000, 3200]],
        "S1": [[0, 0, 3050], [6000, 5000, 3200]],
        "F1": [[-1000, -750, -500], [1000, 750, 0]],
    }
    beam = file.by_type("IfcBeam")[0]
    profile = beam.Representation.Representations[0].Items[0].SweptArea
    assert (profile.is_a(), profile.OverallDepth, profile.ProfileName) == (
        "IfcIShapeProfileDef",
        300.0,
        "BM",
    )


def test_handler_returns_ifc_text_and_ids() -> None:
    building = generate(PLAN, "s").model_dump_json(by_alias=True)
    result = building_ifc(building, OBJECTS.model_dump_json(by_alias=True), None, "Tower")
    file = ifcopenshell.file.from_string(result["text"])
    assert file.by_type("IfcProject")[0].Name == "Tower"
    assert set(result["ids"]) == {"C1", "B1", "W1", "S1", "F1"}
    unknown = BuildingModel.model_validate(
        {
            "elements": [
                {"id": "X", "type": "NOPE", "kind": "footing", "position": [0, 0], "elevation": 0}
            ]
        }
    )
    assert building_ifc(unknown.model_dump_json(by_alias=True), "{}", None, "T")["skipped"] == [
        "X: unknown object type 'NOPE'"
    ]


ADDITIONS = {
    "slabOpenings": [{"id": "O1", "host": "S1", "x": 3000, "y": 2500, "xDim": 1000, "yDim": 800}],
    "wallOpenings": [
        {"id": "D1", "host": "W1", "offset": 1000, "sill": 0, "width": 900, "height": 2100}
    ],
    "stairs": [
        {
            "id": "ST1",
            "type": "STR",
            "base": "BASE",
            "top": "L1",
            "x": 2000,
            "y": 1000,
            "direction": 90,
        }
    ],
    "members": [
        {"id": "BR1", "type": "BM", "x1": 0, "y1": 0, "z1": 0, "x2": 6000, "y2": 0, "z2": 3200}
    ],
}

STAIR_OBJECTS = ObjectLibrary.model_validate(
    {
        "objects": [
            *OBJECTS.model_dump(mode="json", by_alias=True)["objects"],
            {
                "id": "STR",
                "name": "Stair",
                "kind": "staircase",
                "material": "C24",
                "waistThickness": 150,
                "riser": 160,
                "tread": 280,
                "flightWidth": 1200,
            },
        ]
    }
)


def test_additions_cut_hosts_and_add_stairs_and_inclined_members() -> None:
    building = generate(PLAN, "s").model_copy(
        update={"additions": Additions.model_validate(ADDITIONS)}
    )
    file, ids, skipped = export_ifc(building, STAIR_OBJECTS, None, "Test")
    assert skipped == []
    assert {"O1", "D1", "ST1", "BR1"} <= set(ids)
    voids = {
        r.RelatedOpeningElement.Name: r.RelatingBuildingElement.Name
        for r in file.by_type("IfcRelVoidsElement")
    }
    assert voids == {"O1": "S1", "D1": "W1"}
    box = bounds(file)
    # The slab and wall keep their outer size; the openings are cut by the geometry engine.
    assert box["S1"] == [[0, 0, 3050], [6000, 5000, 3200]]
    # 3200 mm rise / 160 mm riser = 20 risers of 280 mm going, rising towards +Y from (2000, 1000).
    assert box["ST1"] == [[1400, 1000, 0], [2600, 6600, 3200]]
    # I 150 x 300 on a 28.07° slope: its top reaches 150 sin(a) beyond the end and 150 cos(a) above it.
    assert [round(v) for v in box["BR1"][1]] == [6071, 75, 3332]
    settings = ifcopenshell.geom.settings()
    slab = ifcopenshell.geom.create_shape(settings, file.by_type("IfcSlab")[0])
    # A slab with a hole has more faces than the six of a box.
    assert len(slab.geometry.faces) // 3 > 12


def test_additions_survive_rebuilds_and_report_broken_references() -> None:
    previous = BuildingModel.model_validate(
        {**generate(PLAN, "s").model_dump(mode="json", by_alias=True), "additions": ADDITIONS}
    )
    smaller = FloorPlan.model_validate(
        {**PLAN.model_dump(mode="json", by_alias=True), "walls": [], "slabs": []}
    )
    rebuilt = generate(smaller, "t", previous)
    assert rebuilt.additions == previous.additions
    assert rebuilt.check_additions() == [
        "O1: there is no slab 'S1' to cut",
        "D1: there is no wall 'W1' to cut",
    ]
    _, _, skipped = export_ifc(rebuilt, STAIR_OBJECTS, None, "Test")
    assert skipped == ["O1: there is no slab 'S1' to cut", "D1: there is no wall 'W1' to cut"]
    clash = previous.model_copy(deep=True)
    clash.additions.members[0].id = "C1"
    assert clash.check_additions() == ["C1: an element from the floor plan already uses this id"]
    assert previous.check_objects(OBJECTS) == ["ST1: 'STR' is not a staircase type"]

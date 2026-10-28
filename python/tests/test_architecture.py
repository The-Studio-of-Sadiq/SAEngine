"""The architecture (``05 Floor Plan/architecture.json``): model, rooms and the IFC round trip."""

from __future__ import annotations

import json
import math

import ifcopenshell
import pytest
from pydantic import ValidationError

from saengine.library import FloorPlan, default_floor_plan
from saengine.library.architecture import (
    Architecture,
    check,
    default_architecture,
    offset_path,
    parse,
    room_boundary,
)
from saengine.library.architecture_ifc import import_architecture
from saengine.library.bim import generate
from saengine.library.export import library_json
from saengine.library.ifc import export_ifc
from saengine.library.objects import ObjectLibrary
from saengine.rpc.handlers import architecture_check, architecture_import_ifc, building_ifc

PLAN = FloorPlan.model_validate(
    {
        **default_floor_plan().model_dump(mode="json", by_alias=True),
        "stories": [
            {"id": "BASE", "name": "Base", "elevation": 0},
            {"id": "L1", "name": "Level 1", "elevation": 3200},
            {"id": "L2", "name": "Level 2", "elevation": 6400},
        ],
    }
)
ELEVATIONS = {s.id: s.elevation for s in PLAN.stories}
OBJECTS = ObjectLibrary.model_validate({"objects": []})


def flat(**instances: object) -> Architecture:
    """The default types with ``instances``: a 6 x 5 m box of 250 walls on L1, a 125 partition
    at x = 3000 splitting it into two rooms."""
    data = library_json(default_architecture())
    data.update(
        {
            "walls": [
                {
                    "id": "AW1",
                    "type": "BW250",
                    "base": "L1",
                    "path": [[0, 0], [6000, 0], [6000, 5000], [0, 5000], [0, 0]],
                },
                {"id": "AW2", "type": "BW125", "base": "L1", "path": [[3000, 0], [3000, 5000]]},
            ],
            "doors": [{"id": "D1", "type": "D2", "wall": "AW2", "offset": 2500}],
            "windows": [{"id": "W1", "type": "W1", "wall": "AW1", "offset": 1500}],
            "rooms": [
                {
                    "id": "R1",
                    "story": "L1",
                    "point": [1500, 2500],
                    "name": "Bed",
                    "number": "101",
                    "floorFinish": "TILE",
                    "ceilingFinish": "CEIL",
                },
                {
                    "id": "R2",
                    "story": "L1",
                    "point": [4500, 2500],
                    "name": "Living",
                    "number": "102",
                    "occupancy": "residential",
                    "wet": False,
                },
            ],
        }
    )
    data.update(instances)
    return Architecture.model_validate(data)


# ───────────────────────────── model ─────────────────────────────


def test_default_types_and_weights() -> None:
    arch = default_architecture()
    types = {t.id: t for t in arch.wallTypes}
    assert types["BW250"].thickness == 274
    # 250 mm brick at 18.85 and two 12 mm plasters at 20.4 [kN/m²].
    assert types["BW250"].weight == pytest.approx(0.25 * 18.85 + 2 * 0.012 * 20.4)
    assert parse("").walls == []
    assert parse(json.dumps({"schema": 1, "part": "architecture"})).wallTypes  # a placeholder


def test_references_are_checked() -> None:
    with pytest.raises(ValidationError, match="no wall type 'X'"):
        flat(
            walls=[{"id": "AW1", "type": "X", "base": "L1", "path": [[0, 0], [1000, 0]]}],
            doors=[],
            windows=[],
        )
    with pytest.raises(ValidationError, match="no wall 'AW9'"):
        flat(doors=[{"id": "D1", "type": "D2", "wall": "AW9", "offset": 100}])
    with pytest.raises(ValidationError, match="duplicate ids: AW1"):
        flat(rooms=[{"id": "AW1", "story": "L1", "point": [1, 1]}])
    with pytest.raises(ValidationError, match="is a floor finish"):
        flat(rooms=[{"id": "R1", "story": "L1", "point": [1, 1], "wallFinish": "TILE"}])
    with pytest.raises(ValidationError, match="not both"):
        flat(
            walls=[
                {
                    "id": "AW1",
                    "type": "BW250",
                    "base": "L1",
                    "top": "L2",
                    "height": 3000,
                    "path": [[0, 0], [1, 0]],
                }
            ],
            doors=[],
            windows=[],
        )


def test_check_against_the_floor_plan() -> None:
    assert check(flat(), PLAN) == []
    problems = check(
        flat(
            windows=[{"id": "W1", "type": "W1", "wall": "AW2", "offset": 300}],
            rooms=[{"id": "R9", "story": "L1", "point": [9000, 9000]}],
            separators=[{"id": "S1", "story": "XX", "start": [0, 0], "end": [1, 1]}],
        ),
        PLAN,
    )
    assert "W1: does not fit in wall AW2" in problems
    assert "R9: its point is not enclosed by walls or separators" in problems
    assert "S1: no story 'XX'" in problems


def test_location_line_offsets_the_centre() -> None:
    assert offset_path([[0, 0], [1000, 0], [1000, 1000]], 100) == [
        (0, 100),
        (900, 100),
        (900, 1000),
    ]
    # A closed path is mitred where it closes.
    loop = offset_path([[0, 0], [1000, 0], [1000, 1000], [0, 1000], [0, 0]], 100)
    assert loop[0] == pytest.approx((100, 100))
    assert loop[-1] == pytest.approx((100, 100))


# ───────────────────────────── rooms ─────────────────────────────


def test_rooms_found_by_polygonize() -> None:
    arch = flat()
    gross, net = room_boundary(arch, arch.rooms[0], ELEVATIONS)
    assert gross.area == pytest.approx(3000 * 5000)
    # Less half of the 274 outer wall on three sides and half of the 149 partition.
    assert net.area == pytest.approx((3000 - 137 - 74.5) * (5000 - 2 * 137))
    assert room_boundary(arch, arch.rooms[1], ELEVATIONS)[0].area == pytest.approx(3000 * 5000)


def test_wall_through_stories_bounds_rooms_above() -> None:
    arch = flat(
        walls=[
            {
                "id": "AW1",
                "type": "BW250",
                "base": "L1",
                "height": 6400,
                "path": [[0, 0], [6000, 0], [6000, 5000], [0, 5000], [0, 0]],
            }
        ],
        doors=[],
        windows=[],
        rooms=[{"id": "R1", "story": "L2", "point": [100, 100]}],
    )
    assert room_boundary(arch, arch.rooms[0], ELEVATIONS) is not None


def test_separator_closes_an_open_plan() -> None:
    arch = flat(
        walls=[
            {
                "id": "AW1",
                "type": "BW250",
                "base": "L1",
                "path": [[0, 0], [6000, 0], [6000, 5000], [0, 5000], [0, 0]],
            }
        ],
        doors=[],
        windows=[],
        rooms=[{"id": "R1", "story": "L1", "point": [1000, 1000]}],
    )
    assert room_boundary(arch, arch.rooms[0], ELEVATIONS)[0].area == pytest.approx(30e6)
    split = arch.model_copy(update={"separators": [*arch.separators]})
    split = Architecture.model_validate(
        {
            **library_json(arch),
            "separators": [{"id": "S1", "story": "L1", "start": [2000, 0], "end": [2000, 5000]}],
        }
    )
    gross, net = room_boundary(split, split.rooms[0], ELEVATIONS)
    assert gross.area == pytest.approx(2000 * 5000)
    assert net.area == pytest.approx((2000 - 137) * (5000 - 274))


def test_walls_joined_at_faces_still_close_rooms() -> None:
    # The partition stops at the outer wall's inner face, as Revit joins walls.
    arch = flat(
        walls=[
            {
                "id": "AW1",
                "type": "BW250",
                "base": "L1",
                "path": [[0, 0], [6000, 0], [6000, 5000], [0, 5000], [0, 0]],
            },
            {"id": "AW2", "type": "BW125", "base": "L1", "path": [[3000, 137], [3000, 4863]]},
        ]
    )
    assert room_boundary(arch, arch.rooms[0], ELEVATIONS)[0].area == pytest.approx(15e6, rel=1e-3)


def test_check_handler_returns_room_outlines() -> None:
    result = architecture_check(
        json.dumps(library_json(flat())), PLAN.model_dump_json(by_alias=True)
    )
    assert result["problems"] == []
    assert result["rooms"]["R1"]["area"] == pytest.approx((3000 - 211.5) * 4726 / 1e6)


# ───────────────────────────── IFC ─────────────────────────────


def _export(arch: Architecture) -> ifcopenshell.file:
    file, ids, skipped = export_ifc(generate(PLAN, "s"), OBJECTS, None, "Test", architecture=arch)
    assert skipped == []
    assert {"arch:AW1", "arch:D1", "arch:W1", "arch:R1", "arch:R1:flooring"} <= set(ids)
    return file


def test_ifc_export_has_walls_openings_spaces_and_coverings() -> None:
    file = _export(flat())
    assert len(file.by_type("IfcWall")) == 2
    door, window = file.by_type("IfcDoor")[0], file.by_type("IfcWindow")[0]
    assert (door.OverallWidth, door.OverallHeight) == (900, 2100)
    assert (
        door.FillsVoids[0].RelatingOpeningElement.VoidsElements[0].RelatingBuildingElement.Tag
        == "AW2"
    )
    assert (
        window.FillsVoids[0].RelatingOpeningElement.VoidsElements[0].RelatingBuildingElement.Tag
        == "AW1"
    )
    spaces = file.by_type("IfcSpace")
    assert sorted((s.Name, s.LongName) for s in spaces) == [("101", "Bed"), ("102", "Living")]
    assert all(s.Decomposes[0].RelatingObject.Name == "Level 1" for s in spaces)
    coverings = file.by_type("IfcCovering")
    assert sorted(c.PredefinedType for c in coverings) == ["CEILING", "FLOORING"]
    assert file.by_type("IfcRelCoversSpaces")[0].RelatingSpace.LongName == "Bed"
    loop = next(w for w in file.by_type("IfcWall") if w.Tag == "AW1")
    (body,) = [
        r for r in loop.Representation.Representations if r.RepresentationIdentifier == "Body"
    ]
    # A closed loop of walls is a ring: a profile with a void, not a self-touching outline.
    assert body.Items[0].SweptArea.is_a("IfcArbitraryProfileDefWithVoids")
    layers = file.by_type("IfcMaterialLayerSet")
    assert sorted(sum(layer.LayerThickness for layer in s.MaterialLayers) for s in layers) == [
        149,
        274,
    ]


def test_ifc_round_trip(tmp_path) -> None:
    source = flat(
        walls=[
            {
                "id": "AW1",
                "type": "BW250",
                "base": "L1",
                "path": [[0, 0], [6000, 0], [6000, 5000], [0, 5000], [0, 0]],
            },
            {
                "id": "AW2",
                "type": "BW125",
                "base": "L1",
                "path": [[3000, 0], [3000, 5000]],
                "structuralRef": "B1",
            },
            {
                "id": "AW3",
                "type": "BW125",
                "base": "L1",
                "height": 1200,
                "baseOffset": 100,
                "path": [[0, 2500], [1000, 2500]],
            },
        ],
        doors=[{"id": "D1", "type": "D2", "wall": "AW2", "offset": 2500, "flip": True}],
        windows=[
            {"id": "W1", "type": "W1", "wall": "AW1", "offset": 1500},
            {"id": "W2", "type": "W2", "wall": "AW1", "offset": 8000, "sill": 1000},
        ],
    )
    path = tmp_path / "model.ifc"
    _export(source).write(str(path))

    empty = Architecture.model_validate({**library_json(default_architecture())})
    adopted, summary = import_architecture(str(path), empty, ELEVATIONS)
    assert summary["adopted"] == {"walls": 3, "doors": 1, "windows": 2, "rooms": 2, "types": 0}
    assert summary["skipped"] == []

    walls = {w.id: w for w in adopted.walls}
    for wall in source.walls:
        back = walls[wall.id]
        assert (back.type, back.base, back.top, back.structuralRef) == (
            wall.type,
            wall.base,
            wall.top,
            wall.structuralRef,
        )
        assert back.height == wall.height
        assert back.baseOffset == pytest.approx(wall.baseOffset, abs=0.5)
        assert len(back.path) == len(wall.path)
        for a, b in zip(back.path, wall.path, strict=True):
            assert math.dist(a, b) < 1
    for kind in ("doors", "windows"):
        back = {o.id: o for o in getattr(adopted, kind)}
        for opening in getattr(source, kind):
            assert back[opening.id].wall == opening.wall
            assert back[opening.id].type == opening.type
            assert back[opening.id].offset == pytest.approx(opening.offset, abs=1)
    assert adopted.doors[0].flip
    assert {w.id: w.sill for w in adopted.windows} == {"W1": None, "W2": 1000}
    rooms = {r.id: r for r in adopted.rooms}
    for room in source.rooms:
        back = rooms[room.id]
        assert (back.name, back.number, back.story, back.occupancy, back.floorFinish) == (
            room.name,
            room.number,
            room.story,
            room.occupancy,
            room.floorFinish,
        )
        before = room_boundary(source, room, ELEVATIONS)[1]
        after = room_boundary(adopted, back, ELEVATIONS)[1]
        assert after.symmetric_difference(before).area < 1e3  # mm²


def test_import_of_an_architects_ifc(tmp_path) -> None:
    """A file from another tool: no SAEngine property sets, a storey off the plan, a door outside
    any wall; types are added by size, ids from the tags."""
    import ifcopenshell.api

    run = ifcopenshell.api.run
    f = run("project.create_file", version="IFC4")
    project = run("root.create_entity", f, ifc_class="IfcProject", name="Arch")
    run("unit.assign_unit", f, length={"is_metric": True, "raw": "METERS"})
    model = run("context.add_context", f, context_type="Model")
    body = run(
        "context.add_context",
        f,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model,
    )
    site = run("root.create_entity", f, ifc_class="IfcSite")
    building = run("root.create_entity", f, ifc_class="IfcBuilding")
    run("aggregate.assign_object", f, products=[site], relating_object=project)
    run("aggregate.assign_object", f, products=[building], relating_object=site)
    storeys = {}
    for name, level in (("Level 1", 3.2), ("Mezzanine", 4.7)):
        storey = run("root.create_entity", f, ifc_class="IfcBuildingStorey", name=name)
        storey.Elevation = level
        run("aggregate.assign_object", f, products=[storey], relating_object=building)
        run("geometry.edit_object_placement", f, product=storey)
        storeys[name] = storey

    def wall(tag: str, start, end, storey: str):
        w = run("root.create_entity", f, ifc_class="IfcWall", name=f"Basic Wall:{tag}")
        w.Tag = tag
        length = math.dist(start, end)
        rep = run(
            "geometry.add_wall_representation",
            f,
            context=body,
            length=length,
            height=3.0,
            thickness=0.2,
        )
        run("geometry.assign_representation", f, product=w, representation=rep)
        import numpy as np

        dx, dy = (end[0] - start[0]) / length, (end[1] - start[1]) / length
        matrix = np.eye(4)
        matrix[:3, 0], matrix[:3, 1], matrix[:3, 3] = (dx, dy, 0), (-dy, dx, 0), (*start, 3.2)
        run("geometry.edit_object_placement", f, product=w, matrix=matrix)
        run("spatial.assign_container", f, products=[w], relating_structure=storeys[storey])
        return w

    host = wall("1001", (0, 0), (6, 0), "Level 1")
    wall("1002", (0, 0), (0, 5), "Mezzanine")
    door = run("root.create_entity", f, ifc_class="IfcDoor", name="Single-Flush:900")
    door.OverallWidth, door.OverallHeight = 0.9, 2.1
    rep = run(
        "geometry.add_profile_representation",
        f,
        context=body,
        profile=run("profile.add_parameterized_profile", f, ifc_class="IfcRectangleProfileDef"),
        depth=2.1,
    )
    rep.Items[0].SweptArea.XDim, rep.Items[0].SweptArea.YDim = 0.9, 0.05
    run("geometry.assign_representation", f, product=door, representation=rep)
    import numpy as np

    matrix = np.eye(4)
    matrix[:3, 3] = (2.0, 0.1, 3.2)
    run("geometry.edit_object_placement", f, product=door, matrix=matrix)
    run("spatial.assign_container", f, products=[door], relating_structure=storeys["Level 1"])
    opening = run("root.create_entity", f, ifc_class="IfcOpeningElement")
    run("feature.add_feature", f, feature=opening, element=host)
    run("feature.add_filling", f, opening=opening, element=door)
    loose = run("root.create_entity", f, ifc_class="IfcWindow", name="Loose")
    run("spatial.assign_container", f, products=[loose], relating_structure=storeys["Level 1"])
    path = tmp_path / "architect.ifc"
    f.write(str(path))

    result = architecture_import_ifc(str(path), None, PLAN.model_dump_json(by_alias=True))
    summary = result["summary"]
    assert summary["adopted"] == {"walls": 1, "doors": 1, "windows": 0, "rooms": 0, "types": 1}
    assert "Wall Basic Wall:1002: not on a floor-plan story" in summary["skipped"]
    assert "Window Loose: not in a wall" in summary["skipped"]
    assert any("Mezzanine" in n for n in summary["notes"])
    # Adopted items are written as the editor writes them: without their default values.
    assert "baseOffset" not in result["architecture"]["walls"][0]
    arch = Architecture.model_validate(result["architecture"])
    (imported,) = arch.walls
    assert (imported.id, imported.base, imported.height) == ("1001", "L1", 3000)  # not up to L2
    assert [list(map(round, p)) for p in imported.path] == [[0, 100], [6000, 100]]
    assert next(t for t in arch.wallTypes if t.id == imported.type).thickness == pytest.approx(200)
    (d,) = arch.doors
    assert (
        d.type == "D2" and d.wall == "1001" and d.offset == pytest.approx(2000, abs=1)
    )  # its box is centred on x = 2 m


def test_building_ifc_handler_takes_the_architecture() -> None:
    result = building_ifc(
        generate(PLAN, "s").model_dump_json(by_alias=True),
        OBJECTS.model_dump_json(by_alias=True),
        None,
        "Test",
        architecture_text=json.dumps(library_json(flat())),
    )
    assert result.get("problems") is None
    assert "arch:AW1" in result["ids"]
    bad = building_ifc(
        generate(PLAN, "s").model_dump_json(by_alias=True),
        OBJECTS.model_dump_json(by_alias=True),
        None,
        "Test",
        architecture_text='{"schema": "saengine.architecture/1", "walls": [{"id": "x"}]}',
    )
    assert bad["problems"][0].startswith("Architecture:")

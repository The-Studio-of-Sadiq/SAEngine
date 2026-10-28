"""An architect's DWG/DXF plan adopted into the architecture: walls, doors, windows and rooms from
small synthetic drawings made with ezdxf (double-line walls with L and T junctions, door and window
blocks, room texts; mm and m; a rotated drawing; loose door arcs; single centre lines)."""

from __future__ import annotations

import itertools
import json
import math

import ezdxf
import pytest
from shapely.geometry import LineString, box
from shapely.ops import unary_union

from saengine.library import FloorPlan, default_floor_plan
from saengine.library.architecture import Architecture, default_architecture, room_boundary
from saengine.library.architecture_dxf import (
    import_drawing,
    inspect_drawing,
    placement_from_points,
    room_label,
)
from saengine.rpc.handlers import architecture_import_drawing, architecture_inspect_drawing

PLAN = FloorPlan.model_validate(
    {
        **default_floor_plan().model_dump(mode="json", by_alias=True),
        "stories": [
            {"id": "BASE", "name": "Base", "elevation": 0},
            {"id": "L1", "name": "Level 1", "elevation": 3200},
            {"id": "ROOF", "name": "Roof", "elevation": 6400},
        ],
    }
)
ELEVATIONS = {s.id: s.elevation for s in PLAN.stories}
LAYERS = {"A-WALL": "walls", "A-DOOR": "doors", "A-GLAZ": "windows", "A-ROOM": "rooms"}

#: The test flat: (centre line, thickness) of each wall, in mm.
WALLS = [
    (((0, 0), (6000, 0)), 250),  # south
    (((6000, 0), (6000, 4000)), 250),  # east
    (((6000, 4000), (0, 4000)), 250),  # north
    (((0, 4000), (0, 0)), 250),  # west: L corners with south and north
    (((3000, 0), (3000, 4000)), 125),  # partition: T-junctions with south and north
]
#: Door in the partition (hinge at y = 1000, 900 wide, swinging into the east room).
DOOR = {"hinge": (3000, 1000), "width": 900}
#: Window in the south wall, x = 1000 to 2500.
WINDOW = {"start": (1000, 0), "width": 1500}


def _faces(walls, openings) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """The wall outlines as an architect draws them: the union of the walls (square ends, so
    corners close), cut at the openings; every edge a line."""
    shape = unary_union(
        [LineString(c).buffer(t / 2, cap_style="square", join_style="mitre") for c, t in walls]
    )
    for cut in openings:
        shape = shape.difference(cut)
    shape = shape.simplify(0)
    lines = []
    for polygon in getattr(shape, "geoms", [shape]):
        for ring in [polygon.exterior, *polygon.interiors]:
            coords = list(ring.coords)
            lines += list(itertools.pairwise(coords))
    return lines


def _flat(
    unit: str = "mm",
    rotation: float = 0.0,
    origin: tuple[float, float] = (0.0, 0.0),
    door_blocks: bool = True,
) -> ezdxf.document.Drawing:
    """The test flat drawn in ``unit``, turned ``rotation``° about the plan origin and moved so
    the plan origin is at ``origin`` (drawing units)."""
    scale = {"mm": 1.0, "m": 0.001}[unit]
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = {"mm": 4, "m": 6}[unit]
    for name in LAYERS:
        doc.layers.add(name)
    doc.layers.add("A-DIMS")
    door = doc.blocks.new("DOOR-UNIT")
    door.add_line((0, 0), (0, 1))  # the open leaf
    door.add_arc((0, 0), 1, 0, 90)  # its swing, closing on the jamb at (1, 0)
    window = doc.blocks.new("WIN-250")
    for y in (-125, 0, 125):
        window.add_line((0, y * scale), (1, y * scale))
    window.add_line((0, -125 * scale), (0, 125 * scale))
    window.add_line((1, -125 * scale), (1, 125 * scale))

    def put(p: tuple[float, float]) -> tuple[float, float]:
        c, s = math.cos(math.radians(rotation)), math.sin(math.radians(rotation))
        x, y = p[0] * scale, p[1] * scale
        return (origin[0] + c * x - s * y, origin[1] + s * x + c * y)

    hx, hy = DOOR["hinge"]
    door_cut = box(hx - 70, hy, hx + 70, hy + DOOR["width"])
    wx, wy = WINDOW["start"]
    window_cut = box(wx, wy - 130, wx + WINDOW["width"], wy + 130)
    msp = doc.modelspace()
    for a, b in _faces(WALLS, [door_cut, window_cut]):
        msp.add_line(put(a), put(b), dxfattribs={"layer": "A-WALL"})
    # Door: hinge on the partition's centre line; the jamb up the partition (local x = +y).
    if door_blocks:
        msp.add_blockref(
            "DOOR-UNIT",
            put((hx, hy)),
            dxfattribs={
                "layer": "A-DOOR",
                "xscale": DOOR["width"] * scale,
                # Mirrored in local y: the leaf opens towards +x (the east room).
                "yscale": -DOOR["width"] * scale,
                "rotation": 90 + rotation,
            },
        )
    else:
        # Exploded: the leaf and the swing as loose entities.
        msp.add_line(put((hx, hy)), put((hx + DOOR["width"], hy)), dxfattribs={"layer": "A-DOOR"})
        centre = put((hx, hy))
        msp.add_arc(
            centre,
            DOOR["width"] * scale,
            rotation,
            90 + rotation,
            dxfattribs={"layer": "A-DOOR"},
        )
    msp.add_blockref(
        "WIN-250",
        put((wx, wy)),
        dxfattribs={"layer": "A-GLAZ", "xscale": WINDOW["width"] * scale, "rotation": rotation},
    )
    msp.add_text(
        "BED ROOM-1",
        height=200 * scale,
        dxfattribs={"layer": "A-ROOM", "insert": put((1000, 2000)), "rotation": rotation},
    )
    msp.add_text(
        "12'-0\" x 14'-0\"",
        height=150 * scale,
        dxfattribs={"layer": "A-ROOM", "insert": put((1000, 1700)), "rotation": rotation},
    )
    msp.add_mtext(
        "101\\PLIVING",
        dxfattribs={"layer": "A-ROOM", "insert": put((4000, 2500)), "char_height": 200 * scale},
    )
    msp.add_text("VERANDA", dxfattribs={"layer": "A-ROOM", "insert": put((3000, -1500))})
    msp.add_line(put((0, -800)), put((6000, -800)), dxfattribs={"layer": "A-DIMS"})
    return doc


def _import(tmp_path, doc, name="flat.dxf", **options):
    path = tmp_path / name
    doc.saveas(path)
    arch = options.pop("arch", default_architecture())
    opts = {"layers": LAYERS, "story": "L1", "source": name, **options}
    return import_drawing(path, arch, ELEVATIONS, opts)


def _walls(arch: Architecture):
    types = {t.id: t for t in arch.wallTypes}
    return sorted(
        ((w, types[w.type].thickness) for w in arch.walls), key=lambda wt: (wt[0].path[0], wt[1])
    )


def _check_flat(arch: Architecture, summary) -> None:
    assert summary["adopted"]["walls"] == 5, summary
    assert {w.type for w in arch.walls} == {"BW250", "BW125"}
    # Joined at the corners and T-junctions: the outer walls meet at their centre lines.
    ends = [tuple(round(c) for c in p) for w in arch.walls for p in (w.path[0], w.path[-1])]
    assert len(ends) == 2 * len(arch.walls)
    for corner in ((0, 0), (6000, 0), (6000, 4000), (0, 4000), (3000, 0), (3000, 4000)):
        assert any(math.dist(corner, e) < 2 for e in ends), (corner, ends)
    partition = next(w for w in arch.walls if w.type == "BW125" and w.id != "MINE")
    assert {round(p[0]) for p in partition.path} == {3000}
    assert sorted(round(p[1]) for p in partition.path) == [0, 4000]
    south = next(w for w in arch.walls if w.type == "BW250" and all(abs(p[1]) < 2 for p in w.path))
    assert sorted(round(p[0]) for p in south.path) == [0, 6000]  # one wall across the window

    assert len(arch.doors) == 1 and len(arch.windows) == 1
    door, window = arch.doors[0], arch.windows[0]
    assert door.wall == partition.id and door.type == "D2"  # 900 wide
    start = min(partition.path, key=lambda p: p[1])
    along = 1450 if start == partition.path[0] else 4000 - 1450
    assert door.offset == pytest.approx(along, abs=2)
    # It swings into the east room (+x): left of the partition run downwards, else flipped.
    assert door.flip == (partition.path[0][1] < partition.path[1][1])
    assert window.wall == south.id and window.type == "W1"  # 1500 wide
    west = min(p[0] for p in south.path)
    centre = 1750 if south.path[0][0] == west else 6000 - 1750
    assert window.offset == pytest.approx(centre, abs=2)

    names = {r.name: r for r in arch.rooms}
    assert set(names) == {"BED ROOM-1", "LIVING"}
    assert names["LIVING"].number == "101"
    for room in arch.rooms:
        assert room.story == "L1"
        assert room_boundary(arch, room, ELEVATIONS) is not None
    assert any("VERANDA" in s for s in summary["skipped"])
    assert any("sizes or areas" in n for n in summary["notes"])


def test_flat_in_mm(tmp_path) -> None:
    arch, summary = _import(tmp_path, _flat(), unit="mm")
    _check_flat(arch, summary)
    assert summary["adopted"]["types"] == 0
    record = arch.imports[0]
    assert record.file == "flat.dxf" and record.story == "L1" and record.layers == LAYERS
    made = set(record.items)
    assert {w.id for w in arch.walls} | {d.id for d in arch.doors} <= made
    # The rooms' net areas: the west room is 3 m by 4 m less half the walls.
    west = next(r for r in arch.rooms if r.name == "BED ROOM-1")
    net = room_boundary(arch, west, ELEVATIONS)[1].area / 1e6
    assert net == pytest.approx((3000 - 137 - 74.5) * (4000 - 274) / 1e6, rel=0.01)


def test_flat_in_metres(tmp_path) -> None:
    arch, summary = _import(tmp_path, _flat("m"), unit="m")
    _check_flat(arch, summary)


def test_rotated_drawing_placed_by_a_point_and_rotation(tmp_path) -> None:
    origin = (25000.0, -4000.0)
    doc = _flat(rotation=30, origin=origin)
    arch, summary = _import(tmp_path, doc, unit="mm", base=list(origin), at=[0, 0], rotation=-30)
    _check_flat(arch, summary)


def test_rotated_drawing_aligned_by_two_points(tmp_path) -> None:
    origin = (1000.0, 2000.0)
    doc = _flat(rotation=-45, origin=origin)
    c = math.cos(math.radians(-45))
    far = (origin[0] + 6000 * c, origin[1] - 6000 * c)  # the plan's (6000, 0) in the drawing
    arch, summary = _import(
        tmp_path, doc, unit="mm", base=list(origin), at=[0, 0], align={"base": far, "at": [6000, 0]}
    )
    _check_flat(arch, summary)
    assert arch.imports[0].rotation == pytest.approx(45)


def test_loose_door_arc_without_a_block(tmp_path) -> None:
    arch, summary = _import(tmp_path, _flat(door_blocks=False), unit="mm")
    _check_flat(arch, summary)


def test_reimport_replaces_the_earlier_import(tmp_path) -> None:
    arch, _ = _import(tmp_path, _flat(), unit="mm")
    # A wall drawn by hand stays; a window put by hand in an imported wall goes with it.
    data = arch.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["walls"].append(
        {"id": "MINE", "type": "BW125", "base": "L1", "path": [[0, 6000], [3000, 6000]]}
    )
    data["windows"].append({"id": "WX", "type": "W2", "wall": arch.walls[0].id, "offset": 3000})
    again, summary = _import(tmp_path, _flat(), unit="mm", arch=Architecture.model_validate(data))
    _check_flat(again, summary)
    assert len(again.imports) == 1
    assert len(again.walls) == 6 and any(w.id == "MINE" for w in again.walls)
    assert not any(w.id == "WX" for w in again.windows)
    assert summary["replaced"] == len(arch.imports[0].items) + 1
    assert any("added by hand" in n for n in summary["notes"])
    # The same file onto another story is a second import (a typical floor).
    third, _ = _import(tmp_path, _flat(), unit="mm", arch=again, story="BASE")
    assert len(third.imports) == 2 and len(third.walls) == 11


def test_new_types_for_sizes_not_in_the_library(tmp_path) -> None:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for a, b in _faces([(((0, 0), (5000, 0)), 200)], []):
        msp.add_line(a, b, dxfattribs={"layer": "WALL"})
    arch, summary = _import(tmp_path, doc, unit="mm", layers={"WALL": "walls"})
    assert summary["adopted"] == {"walls": 1, "doors": 0, "windows": 0, "rooms": 0, "types": 1}
    wall_type = next(t for t in arch.wallTypes if t.id == arch.walls[0].type)
    assert wall_type.id == "IW200" and wall_type.thickness == 200
    # Its free ends where the drawing ends them (square ends: half the thickness past the line).
    assert sorted(round(p[0]) for p in arch.walls[0].path) == [-100, 5100]
    assert any("IW200" in n for n in summary["notes"])


def test_plastered_walls_drawn_with_four_lines_make_one_wall(tmp_path) -> None:
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    for y in (-137, -125, 125, 137):
        msp.add_line((0, y), (4000, y), dxfattribs={"layer": "WALL"})
    arch, summary = _import(tmp_path, doc, unit="mm", layers={"WALL": "walls"})
    assert summary["adopted"]["walls"] == 1
    assert arch.walls[0].type == "BW250"


def test_single_centre_lines_take_the_default_type(tmp_path) -> None:
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(0, 0), (4000, 0), (4000, 3000), (0, 3000)], close=True, dxfattribs={"layer": "A-WALL-CEN"}
    )
    msp.add_text("STORE", dxfattribs={"layer": "ROOMS", "insert": (2000, 1500)})
    arch, summary = _import(
        tmp_path, doc, unit="mm", layers={"A-WALL-CEN": "walls", "ROOMS": "rooms"}, wallType="BW125"
    )
    assert summary["adopted"]["walls"] == 4
    assert {w.type for w in arch.walls} == {"BW125"}
    assert [r.name for r in arch.rooms] == ["STORE"]
    assert room_boundary(arch, arch.rooms[0], ELEVATIONS) is not None


def test_two_texts_in_one_room_keep_the_first(tmp_path) -> None:
    doc = _flat()
    doc.modelspace().add_text("DINING", dxfattribs={"layer": "A-ROOM", "insert": (4500, 1000)})
    arch, summary = _import(tmp_path, doc, unit="mm")
    assert {r.name for r in arch.rooms} == {"BED ROOM-1", "LIVING"}
    assert any("DINING" in s and "same walls" in s for s in summary["skipped"])


def test_inspect_lists_layers_unit_and_preview(tmp_path) -> None:
    path = tmp_path / "flat.dxf"
    _flat("m").saveas(path)
    info = inspect_drawing(path)
    assert info["unit"] == "m" and not info["unitGuessed"]
    layers = {layer["name"]: layer for layer in info["layers"]}
    assert layers["A-WALL"]["counts"]["lines"] > 10
    assert layers["A-DOOR"]["counts"]["blocks"] == 1 and layers["A-DOOR"]["blocks"] == ["DOOR-UNIT"]
    assert layers["A-GLAZ"]["counts"]["blocks"] == 1
    assert layers["A-ROOM"]["counts"]["texts"] == 4
    assert "BED ROOM-1" in layers["A-ROOM"]["texts"]
    assert info["preview"]["A-DOOR"]  # the block drawn on its insert's layer
    (x0, y0), (x1, y1) = info["extents"]
    assert x0 <= -0.125 and x1 >= 6.125 and y0 <= -0.8 and y1 >= 4.125


def test_unit_guessed_without_insunits(tmp_path) -> None:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 0
    doc.modelspace().add_line((0, 0), (12, 0))
    path = tmp_path / "metres.dxf"
    doc.saveas(path)
    info = inspect_drawing(path)
    assert info["unit"] == "m" and info["unitGuessed"]


def test_placement_from_two_points() -> None:
    place, mismatch = placement_from_points("m", ((1, 1), (0, 0)), ((1, 3), (0, 2000)))
    assert place.rotation == pytest.approx(0) and mismatch == pytest.approx(0)
    assert place((1, 3)) == pytest.approx((0, 2000))
    place, mismatch = placement_from_points("mm", ((0, 0), (0, 0)), ((0, 1000), (1000, 0)))
    assert place.rotation == pytest.approx(-90)
    assert place((0, 1000)) == pytest.approx((1000, 0))


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("BED ROOM-1", ("BED ROOM-1", "")),
        ("101\nLIVING", ("LIVING", "101")),
        ("R-201 KITCHEN", ("KITCHEN", "R-201")),
        ("TOILET\n5'-0\" x 7'-0\"", ("TOILET", "")),
        ("12'-0\" x 14'-0\"", None),
        ("AREA = 1250 SFT", None),
        ("3.6 x 4.2", None),
        ("  ", None),
    ],
)
def test_room_labels(text, label) -> None:
    assert room_label(text) == label


def test_handlers(tmp_path) -> None:
    path = tmp_path / "flat.dxf"
    _flat().saveas(path)
    info = architecture_inspect_drawing(str(path))
    assert "layers" in info and not info.get("problems")
    plan = PLAN.model_dump_json(by_alias=True)
    result = architecture_import_drawing(
        str(path), None, plan, {"layers": LAYERS, "story": "L1", "unit": "mm", "source": "flat.dxf"}
    )
    assert not result.get("problems"), result
    # As the editor sends it: layer names are not identifiers, so pairs, not an object.
    pairs = architecture_import_drawing(
        str(path), None, plan, {"layers": [list(kv) for kv in LAYERS.items()], "story": "L1"}
    )
    assert pairs["summary"]["adopted"]["walls"] == 5
    arch = Architecture.model_validate(result["architecture"])
    assert len(arch.walls) == 5 and len(arch.imports) == 1
    # Defaults are left out of the adopted items, as the editor writes them.
    assert all("baseOffset" not in w for w in result["architecture"]["walls"])
    json.dumps(result)
    bad = architecture_import_drawing(str(path), None, plan, {"layers": {}, "story": "L1"})
    assert bad["problems"]
    missing = architecture_inspect_drawing(str(tmp_path / "none.dxf"))
    assert missing["problems"]


def test_architect_style_flat_on_a_three_by_two_grid(tmp_path) -> None:
    """The two-bedroom flat an architect sends: walls stopping at columns, door blocks with
    frames, window blocks, names with sizes, hatch, dimensions, furniture, grid and title."""
    import architect_flat

    path = tmp_path / "flat.dxf"
    architect_flat.make(str(path))
    layers = {
        "A-WALL": "walls",
        "A-DOOR": "doors",
        "A-GLAZ": "windows",
        "A-ROOM-NAME": "rooms",
        "A-ROOM-SIZE": "rooms",
    }
    arch, summary = import_drawing(
        path,
        default_architecture(),
        ELEVATIONS,
        {"layers": layers, "story": "L1", "unit": "mm", "base": list(architect_flat.ORIGIN)},
    )
    centre_lines = {
        tuple(sorted(tuple(round(c) for c in p) for p in w.path)): w.type for w in arch.walls
    }
    expected = {
        tuple(sorted((tuple(a), tuple(b)))): "BW250" if t == 250 else "BW125"
        for (a, b), t in architect_flat.WALLS
        if a[0] != 5000  # the living / dining stubs end at the opening, not at grid points
    }
    for line, wall_type in expected.items():
        assert centre_lines.get(line) == wall_type, (line, sorted(centre_lines))
    assert summary["adopted"] == {"walls": 13, "doors": 8, "windows": 10, "rooms": 8, "types": 0}
    assert sorted(d.type for d in arch.doors) == ["D1", "D2", "D2", "D2", "D2", "D3", "D3", "D3"]
    assert sorted(w.type for w in arch.windows).count("V1") == 2
    # Every door swings to the side the drawing shows.
    for (block, hinge, jamb, side), door in zip(architect_flat.DOORS, arch.doors, strict=True):
        wall = next(w for w in arch.walls if w.id == door.wall)
        (x0, y0), (x1, y1) = wall.path
        along = ((x1 - x0) * (jamb[0] - hinge[0]) + (y1 - y0) * (jamb[1] - hinge[1])) > 0
        assert door.flip == ((side < 0) == along), block
    assert {r.name for r in arch.rooms} == {n for n, _, _ in architect_flat.ROOMS} - {"DINING"}
    assert any("DINING" in s for s in summary["skipped"])
    for room in arch.rooms:
        assert room_boundary(arch, room, ELEVATIONS) is not None, room.name

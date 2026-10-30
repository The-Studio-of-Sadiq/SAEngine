"""Architectural sheets (saengine.drawings.sheets.architecture): the plans, elevations, sections
and schedules of the architecture, drawn on the 2 x 2 bay frame of test_drawings_sheets (a flat
with a 250 mm outer wall, two 125 mm partitions, four doors, four windows, three rooms and a
roof parapet); the DXFs read back with ezdxf; a project's architecture.json into the set."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import ezdxf
import pytest
from test_drawings_sheets import SAMPLE, _architecture, _frame_two_by_two, _synthetic_set

from saengine.drawings.sheets import (
    DrawingSettings,
    Sheet,
    TitleInfo,
    build_sheets,
    drawing_set,
    write_drawings,
)
from saengine.drawings.sheets import architecture as ar
from saengine.drawings.sheets.model import DrawingSet
from saengine.library import architecture as arch_lib


def _arch_sheets(size: str = "A1") -> list[Sheet]:
    data = DrawingSet(
        title=TitleInfo(project="Flat"), building=_frame_two_by_two(), architecture=_architecture()
    )
    sheets = build_sheets(data, DrawingSettings.from_dict({"size": size}))
    assert data.problems == []
    return [s for s in sheets if s.number.startswith("A-")]


def _on(sheet: Sheet, layer: str, kind: str | None = None) -> list:
    return [e for e in sheet.msp if e.dxf.layer == layer and (kind is None or e.dxftype() == kind)]


def _texts(sheet: Sheet, layer: str | None = None) -> list[str]:
    return [e.dxf.text for e in sheet.msp.query("TEXT") if layer is None or e.dxf.layer == layer]


def _view_sheet(spec) -> Sheet:
    sheet = Sheet("A-1", "T", "A1", spec.scale, TitleInfo())
    sheet.view(spec, 30, 30)
    return sheet


def test_the_architectural_sheets_and_their_numbers() -> None:
    sheets = _arch_sheets()
    assert [(s.number, s.title) for s in sheets] == [
        ("A-101", "Architectural plans - Base, Level 1"),
        ("A-102", "Elevations"),
        ("A-103", "Sections"),
        ("A-104", "Door and window schedule"),
        ("A-105", "Room finish schedule"),
    ]
    views = [v.spec.title for s in sheets for v in s.views]
    assert views[:2] == ["Architectural plan - Base", "Architectural plan - Level 1"]
    # north +y: the front (grid 1) is south
    assert "South elevation (grid 1)" in views and "West elevation (grid A)" in views
    assert "Section X-X" in views and "Section Y-Y" in views
    for sheet in sheets:
        assert sheet.labels.conflicts() == [], sheet.number
    # the plans carry the north arrow and the architectural notes
    assert any("cut 1.2 m above the floor" in t for t in _texts(sheets[0]))


def test_no_architecture_no_architectural_sheets() -> None:
    data = DrawingSet(building=_frame_two_by_two())
    assert not any(s.number.startswith("A-") for s in build_sheets(data))
    data.architecture = arch_lib.default_architecture()  # types only, no walls
    assert not any(s.number.startswith("A-") for s in build_sheets(data))


def test_the_plan_walls_doors_windows_and_rooms() -> None:
    b = _frame_two_by_two()
    arch = _architecture()
    sheet = _view_sheet(ar.floor_plan(b, arch, b.levels[0], 100, ar.section_lines(arch, b)))
    # walls: outlines, and the brick layers hatched (plaster not)
    assert _on(sheet, "A-WALL", "LWPOLYLINE")
    hatches = _on(sheet, "A-WALL-PATT", "HATCH")
    assert hatches and {h.dxf.pattern_name for h in hatches} == {"ANSI31"}
    # swings: one per single door, two for the double door, none for the sliding one
    assert len(_on(sheet, "A-DOOR", "ARC")) == 2 + 2
    for arc in _on(sheet, "A-DOOR", "ARC"):
        span = (arc.dxf.end_angle - arc.dxf.start_angle) % 360
        assert span == pytest.approx(90)
    # D-1's leaf: 1000 long, at right angles to the wall, into the room (+y), hinged at x 2500
    leaves = [
        e for e in _on(sheet, "A-DOOR", "LINE")
        if abs(e.dxf.start.distance(e.dxf.end) - 1000 * sheet.scale / 100) < 1e-6
    ]  # fmt: skip
    assert leaves
    # windows: the ventilator (sill 1650) is above the cut: dashed, the others solid
    glass = _on(sheet, "A-GLAZ", "LINE")
    assert sum(1 for e in glass if e.dxf.get("linetype") == "HIDDEN") == 3
    assert len(glass) == 3 * 5 + 3
    # marks and room tags
    marks = _texts(sheet, "S-TEXT")
    for mark in ("D1", "D2", "DD", "DS", "W1", "W2", "W3", "V1"):
        assert mark in marks
    rooms = _texts(sheet, "A-AREA-IDEN")
    assert {"101 LIVING", "102 BED", "103 KITCHEN"} <= set(rooms)
    elevations = {lv.id: lv.elevation for lv in b.levels}
    area = arch_lib.room_boundary(arch, arch.rooms[0], elevations)[1].area / 1e6
    assert f"{area:.2f} m²" in rooms and area == pytest.approx(56.3, abs=0.01)
    assert rooms.count("TILE/PLASTER/CEIL") == 3
    # dimensions: the grids' and the openings' along the top and right walls
    dims = [round(d.get_measurement()) for d in sheet.msp.query("DIMENSION")]
    assert dims.count(6000) == 2 and 12000 in dims  # the grid chain and the overall
    assert {8550, 900, 2550} <= set(dims)  # W3 in the top wall
    assert {1900, 1200, 6900} <= set(dims)  # W2 in the right wall
    # section marks
    assert sorted(_texts(sheet, "A-ANNO-SYMB")) == ["X", "X", "Y", "Y"]


def test_section_lines_pass_through_openings() -> None:
    b = _frame_two_by_two()
    cuts = ar.section_lines(_architecture(), b)
    assert [(c.name, c.look, c.depth) for c in cuts] == [
        ("X", (0.0, 1.0), 2500.0),  # through D2 and W2
        ("Y", (1.0, 0.0), 9000.0),  # through W1, DD and W3
    ]


def test_an_elevation_shows_only_what_faces_it() -> None:
    b = _frame_two_by_two()
    arch = _architecture()
    south = _view_sheet(ar.elevation(b, arch, "front"))
    north = _view_sheet(ar.elevation(b, arch, "rear"))
    # south: the main door (outline and frame) and W1; the doors inside are hidden
    assert len(_on(south, "A-DOOR")) == 2
    assert len(_on(south, "A-GLAZ")) == 1 + 1 + 1  # outline, glass, the sliding mullion
    # north: no door; W3 with its casement sign
    assert _on(north, "A-DOOR") == []
    assert len(_on(north, "A-GLAZ")) == 3
    # levels, the parapet's top and grid bubbles
    assert "LEVEL 1 +3.200" in _texts(south) and "BASE +0.000" in _texts(south)
    tops = [p[1] for e in _on(south, "A-ELEV", "LWPOLYLINE") for p in e.get_points("xy")]
    assert max(tops) == pytest.approx(south.views[0].m(0, 4200)[1])
    assert {"A", "B", "C"} <= set(_texts(south, "S-GRID-BUBBLE"))


def test_a_section_cuts_walls_with_their_openings() -> None:
    b = _frame_two_by_two()
    arch = _architecture()
    cut = ar.section_lines(arch, b)[1]  # Y-Y at x 9000
    sheet = _view_sheet(ar.section(b, arch, cut))
    view = sheet.views[0]
    # the slab and the beams cut: solid
    assert any(h.dxf.solid_fill for h in _on(sheet, "S-HATCH", "HATCH"))
    # the walls cut: brick hatched, outlined heavy; the window W1 in the outer wall at y 0
    # leaves the wall below its sill (900) and above its head (2400)
    assert _on(sheet, "A-WALL-PATT", "HATCH")
    outlines = _on(sheet, "A-SECT", "LWPOLYLINE")
    u = view.m(137, 0)[0]  # the outer face (y -137) of the wall on grid 1 (u = -y)
    zs = sorted(
        {round((p[1] - view.m(0, 0)[1]) / view.k) for e in outlines for p in e.get_points("xy")
         if abs(p[0] - u) < 1e-6}
    )  # fmt: skip
    assert {0, 900, 2400, 3200} <= set(zs)


def test_the_schedules() -> None:
    b = _frame_two_by_two()
    arch = _architecture()
    doors, windows = ar.door_window_tables(arch, b)
    assert doors.title == "Door schedule"
    assert [r[0] for r in doors.rows] == ["D1", "D2", "DD", "DS"]
    assert doors.rows[2][:5] == ["DD", "Double door", "Double", "1500", "2100"]
    assert all(r[-1] == "1" and r[-2] == "Base" for r in doors.rows)
    assert [r[0] for r in windows.rows] == ["V1", "W1", "W2", "W3"]
    assert windows.rows[0][5] == "1650"  # the ventilator's sill
    rooms, finishes = ar.room_tables(arch, b)
    assert [r[:4] for r in rooms.rows] == [
        ["101", "Living", "Base", "56.30"],
        ["102", "Bed", "Base", "27.72"],
        ["103", "Kitchen", "Base", "27.72"],
    ]
    assert rooms.rows[2][4:] == [
        "TILE Floor tiles on mortar",
        "PLASTER Plaster and paint",
        "CEIL Ceiling plaster",
        "Yes",
    ]
    assert [r[0] for r in finishes.rows] == ["TILE", "PLASTER", "CEIL"]


def test_an_unenclosed_room_is_a_problem() -> None:
    data = _architecture().model_dump(by_alias=True)
    data["rooms"].append({"id": "R9", "story": "BASE", "point": [50000, 0], "number": "109"})
    set_ = DrawingSet(
        building=_frame_two_by_two(), architecture=arch_lib.Architecture.model_validate(data)
    )
    build_sheets(set_)
    assert set_.problems == ["Room 109: no walls around its point, not drawn"]


def test_the_dxf_files_open_again(tmp_path: Path) -> None:
    sheets = [s for s in build_sheets(_synthetic_set()) if s.number.startswith("A-")]
    result = write_drawings(sheets, tmp_path, ppi=10)
    assert [r["number"] for r in result["sheets"]] == [f"A-{101 + i}" for i in range(5)]
    for row in result["sheets"]:
        doc = ezdxf.readfile(row["dxf"])
        auditor = doc.audit()
        assert not auditor.has_errors, (row["number"], auditor.errors)
        assert Path(row["png"]).is_file()
    plan = ezdxf.readfile(result["sheets"][0]["dxf"])
    layers = {e.dxf.layer for e in plan.modelspace()}
    assert {"A-WALL", "A-WALL-PATT", "A-DOOR", "A-GLAZ", "A-AREA-IDEN", "A-ANNO-SYMB"} <= layers
    schedule = ezdxf.readfile(result["sheets"][3]["dxf"])
    texts = {e.dxf.text for e in schedule.modelspace().query("TEXT")}
    assert {"DOOR SCHEDULE", "WINDOW SCHEDULE", "Double door", "Ventilator"} <= texts
    assert Path(result["pdf"]).is_file()


@pytest.mark.skipif(not SAMPLE.is_dir(), reason="the app's sample is not in this checkout")
def test_a_projects_architecture_is_drawn(tmp_path: Path) -> None:
    """The sample with an architecture.json beside its floor plan: the set gets its A- sheets;
    an unreadable file is a problem, not a failure."""
    root = tmp_path / "Sample"
    shutil.copytree(SAMPLE, root)
    arch = arch_lib.default_architecture().model_dump(by_alias=True)
    arch["walls"] = [
        {"id": "AW1", "type": "BW250", "base": "BASE",
         "path": [[0, 0], [13000, 0], [13000, 5000], [0, 5000], [0, 0]]},
    ]  # fmt: skip
    arch["windows"] = [{"id": "W-1", "type": "W1", "wall": "AW1", "offset": 3000}]
    arch["rooms"] = [{"id": "R1", "story": "BASE", "point": [6000, 2500], "name": "Hall"}]
    target = root / arch_lib.ARCHITECTURE_FILE
    target.write_text(json.dumps(arch), encoding="utf-8")
    data = drawing_set(root, detailing={"elements": [], "notes": []})
    assert data.architecture is not None and len(data.architecture.walls) == 1
    sheets = build_sheets(data, DrawingSettings.from_dict({"size": "A3"}))
    titles = [s.title for s in sheets if s.number.startswith("A-")]
    assert titles[0] == "Architectural plan - Base"
    assert "Window schedule" in [v.spec.title for s in sheets for v in s.views]
    target.write_text("{not json", encoding="utf-8")
    data = drawing_set(root, detailing={"elements": [], "notes": []})
    assert data.architecture is None
    assert any(p.startswith("The architecture could not be read") for p in data.problems)

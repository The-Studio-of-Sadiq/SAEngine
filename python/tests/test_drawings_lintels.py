"""Lintels in the drawings: the lintels designed over the openings of masonry walls
(saengine.design.lintels) detailed with bar marks (drawings.detailing), drawn in the wall's
elevation (drawings.sheets) and listed in the bar bending schedule (drawings.bbs). Synthetic
building."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saengine.design import lintels as L
from saengine.drawings.bbs import bar_schedule
from saengine.drawings.detailing import detailing_model
from saengine.drawings.sheets import Sheet, TitleInfo
from saengine.drawings.sheets.details import wall_detail as draw_wall
from saengine.drawings.sheets.model import Level
from saengine.drawings.sheets.project import lintel_details, wall_detail
from saengine.library import ObjectLibrary, default_material_library
from saengine.library.bim import BuildingModel

OBJECTS = {
    "schema": "saengine.objects/1",
    "objects": [
        {"id": "BW250", "name": "Brick wall 250", "kind": "wall", "material": "BRICK",
         "thickness": 250, "structural": False},
        {"id": "B300", "name": "Beam 300x500", "kind": "beam", "material": "C24.1",
         "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500}},
    ],
}  # fmt: skip
BIM = {
    "schema": "saengine.bim/2",
    "stories": [
        {"id": "BASE", "name": "Base", "elevation": 0},
        {"id": "L1", "name": "Level 1", "elevation": 3000},
    ],
    "elements": [
        {"id": "W1", "type": "BW250", "kind": "wall", "start": [0, 0], "end": [5000, 0],
         "bottom": 0, "top": 3000},
        {"id": "B1", "type": "B300", "kind": "beam", "start": [0, 0], "end": [5000, 0],
         "elevation": 3000},
    ],
    "additions": {
        "wallOpenings": [
            {"id": "D1", "host": "W1", "offset": 1000, "sill": 0, "width": 1000, "height": 2100},
            {"id": "V1", "host": "W1", "offset": 3500, "sill": 2000, "width": 600, "height": 1000},
        ]
    },
}  # fmt: skip


@pytest.fixture(scope="module")
def model() -> dict:
    materials = default_material_library().model_dump(mode="json", by_alias=True, exclude_none=True)
    texts = {"bim": json.dumps(BIM), "objects": json.dumps(OBJECTS),
             "materials": json.dumps(materials)}  # fmt: skip
    return detailing_model(texts=texts)


def _design() -> dict:
    """The lintel as the design report has it (saengine.design.lintels)."""
    objects = {o.id: o for o in ObjectLibrary.model_validate(OBJECTS).objects}
    mats = {m.id: m for m in default_material_library().materials}
    (found,) = L.lintels_of(BuildingModel.model_validate(BIM), objects, mats)["elements"]
    return found


def test_lintel_bars_are_detailed_on_the_wall(model: dict) -> None:
    designed = _design()
    wall = next(e for e in model["elements"] if e["id"] == "W1")
    lintel = [b for b in wall["bars"] if str(b["role"]).startswith("lintel")]
    roles = {b["role"]: b for b in lintel}
    # The door's lintel only (the ventilator reaches the beam: the beam spans it).
    assert {b["at"]["opening"] for b in lintel} == {"D1"}
    assert set(roles) == {"lintel bottom", "lintel top", "lintel stirrup"}
    count, dia = designed["bars"]["bottom"]
    assert (roles["lintel bottom"]["count"], roles["lintel bottom"]["dia"]) == (count, dia)
    # The lintel runs the clear opening plus a bearing each end; the bars that less the cover.
    bearing = designed["span"] - designed["clear"]
    at = roles["lintel bottom"]["at"]
    assert at["from"] == pytest.approx(1000 - bearing)
    assert at["to"] - at["from"] == pytest.approx(1000 + 2 * bearing)
    assert at["bottom"] == pytest.approx(2100)
    assert roles["lintel bottom"]["dims"]["A"] == pytest.approx(
        1000 + 2 * bearing - 2 * L.lintel_cover()
    )
    # Stirrups at the design's spacing, first 50 mm in from each end.
    _legs, ds, spacing = designed["bars"]["stirrups"]
    stirrup = roles["lintel stirrup"]
    assert (stirrup["dia"], stirrup["at"]["spacing"]) == (ds, spacing)
    assert stirrup["count"] == int((1000 + 2 * bearing - 100) // spacing) + 1
    # Marks: the wall's letters LB, LT, LS, unique.
    marks = [b["mark"] for b in lintel]
    assert len(set(marks)) == 3 and all(m for m in marks)
    assert any(m.endswith("LB") or "LB" in m for m in marks)
    assert any("lintels over D1 are" in n for n in wall["notes"])
    # Its size is known for the elevation (an unreinforced wall drawn for its lintels).
    assert wall["at"]["length"] == pytest.approx(5000)
    assert wall["at"]["thickness"] == pytest.approx(250)


SAMPLE_SETTINGS = (
    Path(__file__).resolve().parents[2]
    / "workbench/resources/saengine/samples/Sample Frame/02 Project Settings/project-settings.json"
)


@pytest.mark.skipif(not SAMPLE_SETTINGS.exists(), reason="sample project not present")
def test_drawings_without_a_report_use_the_high_wind_bars_as_the_design_does() -> None:
    """In a high-wind region (Dhaka: 65.7 m/s > 200 km/h) the lintel bars run 600 mm past
    each side of the opening (7.9.6.3) whether or not a design report is given."""
    from saengine.library.settings import ProjectSettings, derived

    settings_text = SAMPLE_SETTINGS.read_text(encoding="utf-8")
    settings = ProjectSettings.model_validate_json(settings_text)
    assert derived(settings)["windSpeed"] * 3.6 > 200.0
    materials = default_material_library().model_dump(mode="json", by_alias=True, exclude_none=True)
    texts = {"bim": json.dumps(BIM), "objects": json.dumps(OBJECTS),
             "materials": json.dumps(materials), "settings": settings_text}  # fmt: skip
    objects = {o.id: o for o in ObjectLibrary.model_validate(OBJECTS).objects}
    mats = {m.id: m for m in default_material_library().materials}
    (designed,) = L.lintels_of(
        BuildingModel.model_validate(BIM), objects, mats, settings, high_wind=True
    )["elements"]

    def bottom(design_report: dict | None) -> dict:
        m = detailing_model(texts=texts, design_report=design_report)
        wall = next(e for e in m["elements"] if e["id"] == "W1")
        return next(b for b in wall["bars"] if b["role"] == "lintel bottom")

    without, with_report = bottom(None), bottom({"elements": [designed]})
    assert without["at"]["from"] == pytest.approx(with_report["at"]["from"])
    assert without["at"]["to"] == pytest.approx(with_report["at"]["to"])
    assert without["dims"]["A"] == pytest.approx(with_report["dims"]["A"])
    assert without["at"]["from"] == pytest.approx(1000 - L.WIND_BAR_EXTENSION)


def test_lintel_bars_are_in_the_bar_bending_schedule(model: dict) -> None:
    schedule = bar_schedule(model)
    rows = [r for r in schedule.rows if r.role.startswith("lintel")]
    wall = next(e for e in model["elements"] if e["id"] == "W1")
    marks = {b["mark"] for b in wall["bars"] if str(b["role"]).startswith("lintel")}
    assert {r.mark for r in rows} == marks
    assert all(r.total_count > 0 and r.cutting_length > 0 for r in rows)
    assert all("lintel over D1" in r.remarks for r in rows)


def test_lintels_are_drawn_in_the_wall_elevation_with_their_marks(model: dict) -> None:
    wall = next(e for e in model["elements"] if e["id"] == "W1")
    (detail,) = lintel_details(wall, 0.0)
    assert detail.opening == "D1" and detail.bottom == pytest.approx(2100)
    assert detail.bottom_bars and detail.top_bars and detail.stirrups
    for mark in (detail.bottom_bars[2], detail.top_bars[2], detail.stirrups[2]):
        assert mark in detail.text
    objects = ObjectLibrary.model_validate(OBJECTS)
    levels = {"BASE": Level("BASE", "Base", 0.0), "L1": Level("L1", "Level 1", 3000.0)}
    w = wall_detail(
        wall, {o.id: o for o in objects.objects}["BW250"], BuildingModel.model_validate(BIM), levels
    )
    assert w.length == pytest.approx(5000) and [lt.opening for lt in w.lintels] == ["D1"]
    sheet = Sheet("S-301", "Walls", "A1", 50, TitleInfo())
    sheet.view(draw_wall(w, 50), *sheet.area[:2])
    texts = [e.dxf.text for e in sheet.msp.query("TEXT MTEXT") if e.dxftype() == "TEXT"]
    label = next(t for t in texts if t.startswith("LINTEL D1"))
    assert detail.bottom_bars[2] in label and detail.stirrups[2] in label
    # The lintel's outline: the opening plus its bearings, as deep as designed (the 1:50 view
    # on a 1:50 sheet: model units are real millimetres).
    sizes = set()
    for e in sheet.msp.query("LWPOLYLINE[layer=='S-CONC']"):
        xs = [p[0] for p in e.get_points("xy")]
        ys = [p[1] for p in e.get_points("xy")]
        sizes.add((round(max(xs) - min(xs)), round(max(ys) - min(ys))))
    assert (round(detail.x1 - detail.x0), round(detail.depth)) in sizes

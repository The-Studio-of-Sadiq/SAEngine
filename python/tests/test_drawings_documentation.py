"""Revit-parity drawing documentation and user-defined schedule tests."""

import ezdxf
import pytest

from saengine.drawings.automation import auto_tag
from saengine.drawings.sheets.build import DrawingSettings, build_sheets
from saengine.drawings.sheets.documentation import (
    ScopeBox,
    build_dependent_plans,
    create_callout,
    documentation_legend,
    update_callout_reference,
)
from saengine.drawings.sheets.keynotes import keynote_legend, load_keynotes, place_keynote_legend
from saengine.drawings.sheets.layout import APP_ID, Sheet, TitleInfo, ViewSpec
from saengine.drawings.sheets.model import Building, DrawingSet, Grid, Level, PlanBeam, PlanColumn
from saengine.drawings.sheets.schedule_builder import build_schedule, evaluate_expression
from saengine.library.settings import DrawingScopeBox


def _two_scope_building() -> Building:
    building = Building(
        grids_x=[Grid("A", 0), Grid("B", 20000), Grid("C", 40000)],
        grids_y=[Grid("1", 0), Grid("2", 20000)],
        levels=[Level("L1", "Level 1", 0)],
    )
    for i, (x, y) in enumerate(
        [(0, 0), (20000, 0), (40000, 0), (0, 20000), (20000, 20000), (40000, 20000)], 1
    ):
        building.columns.append(PlanColumn(f"C{i}", f"C{i}", x, y, -3000, 0, 400, 400))
    building.beams.extend(
        [
            PlanBeam("B1", "B1", (0, 0), (40000, 0), 300, 500, 0),
            PlanBeam("B2", "B2", (0, 20000), (40000, 20000), 300, 500, 0),
            PlanBeam("B3", "B3", (20000, 0), (20000, 20000), 300, 500, 0),
        ]
    )
    return building


def test_scope_boxes_make_cropped_dependent_sheets_and_reciprocal_matchlines() -> None:
    # A 40 x 20 m rectangle split at x=20 m has two dependent views, one per sheet.
    scopes = [
        ScopeBox("West", (0, 0, 20000, 20000), ("L1",)),
        ScopeBox("East", (20000, 0, 40000, 20000), ("L1",)),
    ]
    plans = build_dependent_plans(_two_scope_building(), scopes)
    assert [plan.sheet.number for plan in plans] == ["S-101", "S-102"]
    assert len({plan.view.spec.key for plan in plans}) == 2
    for plan, target in zip(plans, ("S-102", "S-101"), strict=True):
        labels = [entity.dxf.text for entity in plan.sheet.msp.query("TEXT")]
        assert f"MATCHLINE - SEE SHEET {target}" in labels
        edge = plan.view.m(20000, 10000)[0]
        assert any(
            abs(entity.dxf.start.x - edge) < 1e-6 and abs(entity.dxf.end.x - edge) < 1e-6
            for entity in plan.sheet.msp.query("LINE[layer=='S-GRID']")
        )
        assert any(
            entity.dxftype() == "HATCH" and entity.dxf.layer == "S-TITLE"
            for entity in plan.sheet.msp
        )
        assert "KEY PLAN" in labels


def test_scope_boxes_from_project_settings_are_used_by_the_drawing_set() -> None:
    definitions = [
        DrawingScopeBox(name="West", bounds=(0, 0, 20000, 20000), levels=["L1"]),
        DrawingScopeBox(name="East", bounds=(20000, 0, 40000, 20000), levels=["L1"]),
    ]
    settings = DrawingSettings.from_dict(
        {"scopeBoxes": [definition.model_dump() for definition in definitions]}
    )
    sheets = build_sheets(DrawingSet(building=_two_scope_building()), settings)
    assert [sheet.number for sheet in sheets] == ["S-101", "S-102"]
    assert all(
        any(e.dxftype() == "HATCH" and e.dxf.layer == "S-TITLE" for e in s.msp) for s in sheets
    )


def test_callout_scale_is_paper_size_and_reference_renumbers() -> None:
    parent_sheet = Sheet("A-101", "Plan", "A1", 100, TitleInfo())
    parent_spec = ViewSpec("Plan", 100, (0, 0, 10000, 10000), lambda view: None)
    parent = parent_sheet.view(parent_spec, *parent_sheet.area[:2])
    target_sheet = Sheet("A-201", "Detail", "A1", 20, TitleInfo())
    detail = ViewSpec(
        "Enlarged plan",
        20,
        (0, 0, 3000, 3000),
        lambda view: view.rect(0, 0, 3000, 3000, "A-WALL"),
    )
    callout = create_callout(parent, (1000, 1000, 4000, 4000), target_sheet, detail, "1")
    assert detail.bbox[2] / detail.scale == pytest.approx(150)
    assert detail.bbox[3] / detail.scale == pytest.approx(150)
    assert callout.reference == "1 / A-201"
    update_callout_reference(callout, "A-202")
    texts = [entity.dxf.text for entity in parent_sheet.msp.query("TEXT")]
    assert "1 / A-202" in texts
    assert "1 / A-201" not in texts


def test_auto_tag_adds_element_and_material_keynotes_and_only_used_legend_keys() -> None:
    doc = ezdxf.new()
    doc.appids.add(APP_ID)
    doc.layers.add("S-COLS")
    entity = doc.modelspace().add_lwpolyline(
        [(0, 0), (400, 0), (400, 400), (0, 400)],
        close=True,
        dxfattribs={"layer": "S-COLS"},
    )
    entity.set_xdata(
        APP_ID,
        [(1000, "mark=C1"), (1000, "keynote=S-001"), (1000, "materialKeynote=M-001")],
    )
    result = auto_tag(doc, {"S-001": "Structural work", "M-001": "Specified material"})
    assert result["added"] == 1
    assert result["keynotesAdded"] == 2
    table = keynote_legend(
        doc,
        {"S-001": "Structural work", "M-001": "Specified material", "UNUSED": "Not on this sheet"},
    )
    assert table.rows == [["M-001", "Specified material"], ["S-001", "Structural work"]]
    assert set(load_keynotes()) == {"A-001", "M-001", "S-001"}
    sheet = Sheet("S-111", "Keynotes", "A1", 100, TitleInfo())
    tagged = sheet.msp.add_line((0, 0), (100, 0), dxfattribs={"layer": "S-GRID"})
    tagged.set_xdata(APP_ID, [(1000, "keynote=S-001")])
    assert place_keynote_legend(sheet, {"S-001": "Structural work"})
    assert sheet.msp.query("LINE[layer=='S-TABLE']")


def test_documentation_legend_lists_only_dxf_conventions_used() -> None:
    sheet = Sheet("S-112", "Legend", "A1", 100, TitleInfo())
    doc = sheet.doc
    sheet.msp.add_line((0, 0), (100, 0), dxfattribs={"layer": "S-GRID"})
    block = doc.blocks.new("SECTION_MARK")
    block.add_line((0, 0), (1, 1))
    sheet.msp.add_blockref("SECTION_MARK", (0, 0))
    hatch = sheet.msp.add_hatch()
    hatch.set_pattern_fill("ANSI31")
    table = documentation_legend(doc)
    values = {row[1] for row in table.rows}
    assert {"Continuous", "CENTER", "ANSI31", "SECTION_MARK"} <= values


def test_user_schedule_filters_groups_sorts_and_totals_with_safe_calculation(tmp_path) -> None:
    doors = [
        {"mark": "D-3", "level": "L1", "width": 1000, "area": 2.0, "rate": 12},
        {"mark": "D-1", "level": "L2", "width": 1200, "area": 3.0, "rate": 10},
        {"mark": "D-2", "level": "L1", "width": 900, "area": 1.5, "rate": 8},
        {"mark": "D-4", "level": "L1", "width": 800, "area": 1.0, "rate": 5},
    ]
    definition = {
        "name": "Door schedule",
        "category": "doors",
        "fields": [
            {"key": "mark", "title": "Mark"},
            {"key": "level", "title": "Level"},
            {"key": "width", "title": "Width"},
            {"key": "cost", "title": "Cost", "expression": "area * rate"},
        ],
        "filters": [{"field": "width", "operator": ">=", "value": 900}],
        "sort": [{"field": "mark", "order": "asc"}],
        "groupBy": ["level"],
        "totals": ["count", "width", "cost"],
        "itemize": True,
    }
    result = build_schedule(definition, {"doors": doors})
    # Three doors pass; the per-level hand counts are L1=2, L2=1; total width=3100,
    # and cost is (2*12)+(1.5*8)+(3*10)=66.
    assert result.rows == [
        ["Level: L1", "", "", "", ""],
        ["D-2", "L1", "900", "12", "1"],
        ["D-3", "L1", "1000", "24", "1"],
        ["TOTAL", "", "1900", "36", "2"],
        ["Level: L2", "", "", "", ""],
        ["D-1", "L2", "1200", "30", "1"],
        ["TOTAL", "", "1200", "30", "1"],
        ["GRAND TOTAL", "", "3100", "66", "3"],
    ]
    assert evaluate_expression("area * rate", {"area": 2, "rate": 12}) == 24
    assert "Mark,Level,Width,Cost,Count" in result.csv_text()
    sheet = Sheet("S-301", "Door schedule", "A1", 1, TitleInfo())
    assert result.add_to_sheet(sheet)
    assert sheet.msp.query("LINE[layer=='S-TABLE']")
    workbook = result.write_xlsx(tmp_path / "doors.xlsx")
    assert workbook["sheets"] == 1
    with pytest.raises(ValueError, match="allow only"):
        evaluate_expression('__import__("os")', {})


def test_non_itemized_schedule_counts_identical_rows() -> None:
    definition = {
        "category": "doors",
        "fields": [
            {"key": "level", "title": "Level"},
            {"key": "width", "title": "Width"},
        ],
        "groupBy": ["level"],
        "totals": ["count"],
        "itemize": False,
    }
    result = build_schedule(
        definition,
        {
            "doors": [
                {"level": "L1", "width": 900},
                {"level": "L1", "width": 900},
                {"level": "L1", "width": 1000},
            ]
        },
    )
    # Two identical 900-wide doors collapse into one row of count 2; grand count remains 3.
    assert result.rows == [
        ["Level: L1", "", ""],
        ["L1", "900", "2"],
        ["L1", "1000", "1"],
        ["TOTAL", "", "3"],
        ["GRAND TOTAL", "", "3"],
    ]

"""Structural steel sheets: present only with steel members, on SAEngine's layers, the member
schedule's total equal to the bill of quantities' steel, the connection details' bolt pattern
equal to the designed connection (ezdxf on the written DXFs)."""

from __future__ import annotations

import itertools
import json
import math
import shutil
from pathlib import Path

import ezdxf
import pytest
from ezdxf import bbox
from test_drawings_sheets import SAMPLE, _frame_two_by_two, _synthetic_set

from saengine.drawings.sheets import LAYERS, PAPER, DrawingSettings, build_sheets, write_drawings
from saengine.drawings.sheets.layout import MARGIN, MARGIN_LEFT, TEXT_HEIGHTS, read_tags
from saengine.drawings.sheets.model import (
    SteelConnectionDetail,
    SteelMember,
    SteelSet,
)
from saengine.drawings.sheets.steel import GussetGeometry, member_schedule

STEEL_LAYERS = {"S-STEEL", "S-STEEL-AXIS", "S-STEEL-PLATE", "S-BOLT", "S-WELD"}
LAYER_NAMES = {name for name, *_ in LAYERS}

GUSSET = {
    "type": "gusset",
    "boltGrade": "A325N",
    "boltDiameter": 20,
    "rows": 3,
    "pitch": 70,
    "endDistance": 35,
    "edgeDistance": 35,
    "plateThickness": 10,
    "weldSize": 6,
    "electrode": 480,
    "lines": 2,
    "gauge": 60,
    "tabThickness": 10,
    "tabWelds": 4,
    "tabWeldLength": 150,
    "gussetWeldLength": 300,
}


def _steel_set() -> SteelSet:
    """A brace on grid 1 from A at the base to B at L1, a steel beam on grid 2, an end plate."""
    brace = SteelMember(
        "M1", "M1", "brace", "SHS 150x150x8", "rectangleHollow", 150, 150,
        (0.0, 0.0, 0.0), (6000.0, 0.0, 3000.0), "ASTM A572 Grade 50", "A572-50", 250.0, "CN1",
    )  # fmt: skip
    beam = SteelMember(
        "SB1", "SB1", "beam", "W310x39", "I", 310, 165,
        (0.0, 5000.0, 3000.0), (6000.0, 5000.0, 3000.0), "ASTM A992", "A992", 234.5, "CN2",
    )  # fmt: skip
    gusset = SteelConnectionDetail(
        "CN1", "gusset", dict(GUSSET), "SHS 150x150x8", "rectangleHollow", 150, 150, 8, 8,
        ["M1"], "A572-50", 26.6, 222.0, 0.41, True,
    )  # fmt: skip
    end_plate = SteelConnectionDetail(
        "CN2", "endPlate",
        {"type": "endPlate", "boltGrade": "8.8", "boltDiameter": 20, "rows": 3, "pitch": 70,
         "endDistance": 35, "edgeDistance": 35, "plateThickness": 10, "weldSize": 6,
         "electrode": 480, "gauge": 90},
        "W310x39", "I", 310, 165, 5.8, 9.7, ["SB1"], "A992",
    )  # fmt: skip
    return SteelSet(
        [brace, beam],
        [gusset, end_plate],
        [("S.01", "Structural steel A572-50 in braces", 250.0),
         ("S.02", "Structural steel A992 in beams", 234.5)],
        484.5,
        "10 BOQ",
        ["ASTM A572 Grade 50 (A572-50)", "ASTM A992 (A992)"],
        ["8.8", "A325N"],
        [480.0],
    )  # fmt: skip


def _with_steel():
    data = _synthetic_set()
    data.steel = _steel_set()
    return data


def test_no_steel_no_steel_sheets() -> None:
    sheets = build_sheets(_synthetic_set())
    assert not [s for s in sheets if s.title.lower().startswith("steel")]


@pytest.fixture(scope="module", params=["A1", "A3"])
def steel_sheets(request, tmp_path_factory):
    data = _with_steel()
    concrete = len(
        build_sheets(_synthetic_set(), DrawingSettings.from_dict({"size": request.param}))
    )
    sheets = build_sheets(data, DrawingSettings.from_dict({"size": request.param}))
    out = tmp_path_factory.mktemp(f"steel-{request.param}")
    steel = [s for s in sheets if s.category.startswith("Steel")]
    result = write_drawings(steel, out, ppi=10)
    docs = [(row, ezdxf.readfile(row["dxf"])) for row in result["sheets"]]
    return sheets, concrete, steel, docs


def test_steel_sheets_follow_the_concrete_ones(steel_sheets) -> None:
    sheets, concrete, steel, _ = steel_sheets
    assert sheets[:concrete] == [s for s in sheets if not s.category.startswith("Steel")]
    categories = [s.category for s in steel]
    for wanted in (
        "Steel general notes",
        "Steel framing plans",
        "Steel elevations",
        "Steel member schedule",
        "Steel connection details",
    ):
        assert wanted in categories, wanted
    numbers = [int(s.number.split("-")[1]) for s in sheets]
    assert numbers == list(range(101, 101 + len(sheets)))
    for sheet in steel:
        assert sheet.labels.overlaps() == [], sheet.number
        assert sheet.labels.conflicts() == [], sheet.number
        x0, y0, x1, y1 = sheet.area
        for view in sheet.views:
            bx0, by0, bx1, by1 = view.box
            assert bx0 >= x0 - 1e-6 and bx1 <= x1 + 1e-6 and by0 >= y0 - 1e-6 and by1 <= y1 + 1e-6


def test_steel_sheets_layers_text_and_border(steel_sheets) -> None:
    *_, docs = steel_sheets
    used: set[str] = set()
    for row, doc in docs:
        auditor = doc.audit()
        assert not auditor.has_errors, (row["number"], [str(e) for e in auditor.errors])
        scale = float(doc.header["$DIMSCALE"])
        w, h = (v * scale for v in PAPER[row["size"]])
        border = (MARGIN_LEFT * scale, MARGIN * scale, w - MARGIN * scale, h - MARGIN * scale)
        tol = 0.01 * scale
        cache = bbox.Cache()
        for e in doc.modelspace():
            assert e.dxf.layer in LAYER_NAMES, (row["number"], e.dxf.layer)
            used.add(e.dxf.layer)
            assert e.dxf.get("color", 256) == 256 or e.dxf.layer == "S-TITLE"
            if e.dxftype() == "TEXT":
                assert e.dxf.style == "SAE"
                assert round(e.dxf.height / scale, 3) in TEXT_HEIGHTS, (row["number"], e.dxf.text)
            box = bbox.extents([e], fast=True, cache=cache)
            if box.has_data and e.dxf.layer != "S-SHEET":
                assert box.extmin.x >= border[0] - tol and box.extmin.y >= border[1] - tol
                assert box.extmax.x <= border[2] + tol and box.extmax.y <= border[3] + tol
    assert STEEL_LAYERS <= used


def _bolts(doc) -> list[tuple[dict, tuple[float, float]]]:
    out = []
    for c in doc.modelspace().query("CIRCLE[layer=='S-BOLT']"):
        tags = read_tags(c)
        if "row" in tags:
            out.append((tags, (c.dxf.center.x, c.dxf.center.y)))
    return out


def test_connection_detail_bolts_are_the_design(steel_sheets) -> None:
    *_, docs = steel_sheets
    details = [d for r, d in docs if r["title"].startswith("Steel connection")]
    # the details are drawn at the sheet's scale: model units are real millimetres
    assert all(float(doc.header["$DIMSCALE"]) == 5 for doc in details)
    bolts = [b for doc in details for b in _bolts(doc)]
    # 3 rows x 2 lines on the gusset, 3 rows x 2 lines on the end plate: 12 bolts
    assert len(bolts) == 6 + 6
    # the gusset's bolts: the first six drawn
    g = bolts[:6]
    rows = {int(t["row"]) for t, _ in g}
    lines = {int(t["line"]) for t, _ in g}
    assert rows == {1, 2, 3} and lines == {1, 2}
    at = {(int(t["row"]), int(t["line"])): p for t, p in g}
    for r, line in itertools.product((1, 2), (1, 2)):
        assert math.dist(at[(r, line)], at[(r + 1, line)]) == pytest.approx(GUSSET["pitch"])
    for r in (1, 2, 3):
        assert math.dist(at[(r, 1)], at[(r, 2)]) == pytest.approx(GUSSET["gauge"])
    # the Whitmore section drawn is the design's width
    whitmore = [
        e for doc in details for e in doc.modelspace().query("LINE[layer=='S-STEEL-PLATE']")
        if read_tags(e).get("part") == "whitmore"
    ]  # fmt: skip
    assert len(whitmore) == 1
    line = whitmore[0]
    assert math.dist(line.dxf.start, line.dxf.end) == pytest.approx(222.0)
    # the end plate's bolts: 2 lines at the gauge
    e = {(int(t["row"]), int(t["line"])): p for t, p in bolts[6:]}
    assert math.dist(e[(1, 1)], e[(1, 2)]) == pytest.approx(90)
    assert math.dist(e[(1, 1)], e[(2, 1)]) == pytest.approx(70)
    # weld symbols: text on S-WELD with the leg sizes and lengths
    welds = [t.dxf.text for doc in details for t in doc.modelspace().query("TEXT[layer=='S-WELD']")]
    assert welds.count("6") >= 6 and "300" in welds and "150" in welds


def test_gusset_geometry_keeps_the_design_distances() -> None:
    c = _steel_set().connections[0]
    g = GussetGeometry(c)
    assert len(g.bolts) == 6
    assert g.first - g.tab_end == GUSSET["endDistance"]
    assert g.free_end - g.last == GUSSET["endDistance"]
    assert g.last - g.first == 2 * GUSSET["pitch"]
    assert g.half_tab == GUSSET["gauge"] / 2 + GUSSET["edgeDistance"]
    # the tab clears the frame member; the gusset stands on it
    for t in (-g.half_tab, g.half_tab):
        assert g.at(g.tab_end, t)[1] >= 50 - 1e-6
    assert min(y for _, y in g.gusset) == pytest.approx(0, abs=1e-6)


def test_member_schedule_total_is_the_boq() -> None:
    steel = _steel_set()
    table = member_schedule(steel, _frame_two_by_two().levels)
    total = table.rows[-1]
    assert total[0] == "TOTAL"
    assert float(total[6].replace(",", "")) == pytest.approx(steel.boq_total, abs=0.05)
    m1 = table.rows[0]
    assert m1[0] == "M1" and m1[4] == "6708" and m1[7] == m1[8] == "CN1"


@pytest.mark.skipif(not SAMPLE.is_dir(), reason="the app's sample is not in this checkout")
def test_the_sample_projects_steel(tmp_path: Path) -> None:
    from saengine.drawings.sheets import drawing_set

    root = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    boq = json.loads((root / "10 BOQ/boq.json").read_text(encoding="utf-8"))
    steel_items = [i for i in boq["items"] if i["group"] == "steel"]
    boq_total = sum(i["quantity"] for i in steel_items)
    objects = json.loads((root / "04 Objects/objects.json").read_text(encoding="utf-8"))
    designed = next(o["connection"] for o in objects["objects"] if o["id"] == "BR-SHS")

    data = drawing_set(root, detailing={"elements": [], "notes": []})
    steel = data.steel
    assert [m.mark for m in steel.members] == ["M2"]
    assert not [p for p in data.problems if p.startswith("Steel")]
    # the masses are the BOQ's, the schedule's total its steel total
    by_element = {b["element"]: b["quantity"] for i in steel_items for b in i["breakdown"]}
    assert steel.members[0].mass == pytest.approx(by_element["M2"])
    assert steel.boq_total == pytest.approx(boq_total)
    assert sum(m.mass for m in steel.members) == pytest.approx(boq_total)
    # the connection is the designed one (its defaults filled in)
    (cn,) = steel.connections
    assert cn.kind == "gusset" and cn.members == ["M2"]
    for key, value in designed.items():
        assert cn.data[key] == value
    assert cn.bolts == cn.data["rows"] * cn.data["lines"]

    for size in ("A1", "A3"):
        sheets = build_sheets(data, DrawingSettings.from_dict({"size": size}))
        steel_sheets = [s for s in sheets if s.category.startswith("Steel")]
        assert [s.title for s in steel_sheets] == [
            "Steel general notes",
            "Steel framing plan - Level 1",
            "Steel elevations",
            "Steel member schedule",
            "Steel connection details",
        ]
        for sheet in steel_sheets:
            assert sheet.labels.overlaps() == [] and sheet.labels.conflicts() == [], sheet.number
        schedule = next(s for s in steel_sheets if s.title == "Steel member schedule")
        texts = [t.dxf.text for t in schedule.msp.query("TEXT")]
        assert f"{boq_total:,.1f}" in texts


@pytest.mark.skipif(not SAMPLE.is_dir(), reason="the app's sample is not in this checkout")
def test_a_stale_boq_is_measured_again(tmp_path: Path) -> None:
    from saengine.drawings.sheets import drawing_set

    root = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    path = root / "10 BOQ/boq.json"
    boq = json.loads(path.read_text(encoding="utf-8"))
    expected = sum(i["quantity"] for i in boq["items"] if i["group"] == "steel")
    boq["source"]["bim"] = "stale"
    for item in boq["items"]:
        if item["group"] == "steel":
            item["quantity"] = 1.0
    path.write_text(json.dumps(boq), encoding="utf-8")
    data = drawing_set(root, detailing={"elements": [], "notes": []})
    assert any("older than 06 BIM" in p for p in data.problems)
    assert data.steel.boq_total == pytest.approx(expected)

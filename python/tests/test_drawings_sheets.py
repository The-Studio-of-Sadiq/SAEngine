"""Drawing sheets (saengine.drawings.sheets): sheet setup, title block, layers, plans,
schedules, details, DXF round trip and the PDF set. Synthetic buildings, and the app's sample
(a synthetic project)."""

from __future__ import annotations

import itertools
import math
import shutil
from pathlib import Path

import ezdxf
import pytest

from saengine.drawings.sheets import (
    LAYERS,
    PAPER,
    DrawingSettings,
    Sheet,
    TitleInfo,
    build_sheets,
    drawing_set,
    write_drawings,
)
from saengine.drawings.sheets.layout import read_tags
from saengine.drawings.sheets.model import (
    BeamBar,
    BeamDetail,
    Building,
    ColumnLine,
    ColumnSection,
    DrawingSet,
    FootingDetail,
    Grid,
    Level,
    LinkZone,
    Mesh,
    PlanBeam,
    PlanColumn,
    PlanSlab,
    SlabDetail,
    StairDetail,
    Support,
    Table,
    WallDetail,
)
from saengine.drawings.sheets.plans import framing_plan, grids
from saengine.drawings.sheets.project import beam_detail
from saengine.drawings.sheets.schedules import beam_elevation

SAMPLE = Path(__file__).resolve().parents[2] / "workbench/resources/saengine/samples/Sample Frame"


def _texts(doc) -> list[str]:
    return [e.dxf.text for e in doc.modelspace().query("TEXT")]


def _frame_two_by_two() -> Building:
    """A 2 x 2 bay frame: grids A-C at 6 m, 1-3 at 5 m, columns at every crossing."""
    b = Building(
        grids_x=[Grid("A", 0), Grid("B", 6000), Grid("C", 12000)],
        grids_y=[Grid("1", 0), Grid("2", 5000), Grid("3", 10000)],
        levels=[Level("BASE", "Base", 0), Level("L1", "Level 1", 3200)],
    )
    n = 1
    for x in (0, 6000, 12000):
        for y in (0, 5000, 10000):
            b.columns.append(PlanColumn(f"C{n}", f"C{n}", x, y, 0, 3200, 400, 600))
            n += 1
    n = 1
    for y in (0, 5000, 10000):
        for x0 in (0, 6000):
            b.beams.append(PlanBeam(f"B{n}", f"B{n}", (x0, y), (x0 + 6000, y), 300, 500, 3200))
            n += 1
    for x in (0, 6000, 12000):
        for y0 in (0, 5000):
            b.beams.append(PlanBeam(f"B{n}", f"B{n}", (x, y0), (x, y0 + 5000), 300, 500, 3200))
            n += 1
    n = 1
    for x0 in (0, 6000):
        for y0 in (0, 5000):
            pts = [(x0, y0), (x0 + 6000, y0), (x0 + 6000, y0 + 5000), (x0, y0 + 5000)]
            b.slabs.append(PlanSlab(f"S{n}", f"S{n}", pts, 150, 3200))
            n += 1
    return b


def _architecture():
    """The architecture of a flat on the 2 x 2 bay frame: a 250 mm outer wall as one loop on the
    grids, 125 mm partitions on grid B and on grid 2 (B-C), single, double and sliding doors,
    sliding, casement and high windows, three rooms; a 1 m parapet on the roof (L1)."""
    from saengine.library import architecture as arch_lib

    data = arch_lib.default_architecture().model_dump(by_alias=True)
    data["doorTypes"].append(
        {"id": "DS", "name": "Sliding door", "style": "sliding", "width": 1800, "height": 2100}
    )
    data["windowTypes"].append(
        {"id": "W3", "name": "Casement", "style": "casement", "width": 900, "height": 1200}
    )
    loop = [[0, 0], [12000, 0], [12000, 10000], [0, 10000], [0, 0]]
    data["walls"] = [
        {"id": "AW1", "type": "BW250", "base": "BASE", "path": loop},
        {"id": "AW2", "type": "BW125", "base": "BASE", "path": [[6000, 0], [6000, 10000]]},
        {"id": "AW3", "type": "BW125", "base": "BASE", "path": [[6000, 5000], [12000, 5000]]},
        {"id": "AW4", "type": "BW125", "base": "L1", "height": 1000, "path": loop},
    ]
    data["doors"] = [
        {"id": "D-1", "type": "D1", "wall": "AW1", "offset": 3000},
        {"id": "D-2", "type": "D2", "wall": "AW2", "offset": 2500, "flip": True},
        {"id": "D-3", "type": "DD", "wall": "AW3", "offset": 3000},
        {"id": "D-4", "type": "DS", "wall": "AW2", "offset": 7500},
    ]
    data["windows"] = [
        {"id": "W-1", "type": "W1", "wall": "AW1", "offset": 9000},
        {"id": "W-2", "type": "W2", "wall": "AW1", "offset": 14500},
        {"id": "W-3", "type": "W3", "wall": "AW1", "offset": 25000},
        {"id": "W-4", "type": "V1", "wall": "AW1", "offset": 36000},
    ]
    finishes = {"floorFinish": "TILE", "wallFinish": "PLASTER", "ceilingFinish": "CEIL"}
    data["rooms"] = [
        {"id": "R1", "story": "BASE", "point": [3000, 5000], "name": "Living", "number": "101",
         **finishes},
        {"id": "R2", "story": "BASE", "point": [9000, 2500], "name": "Bed", "number": "102",
         **finishes},
        {"id": "R3", "story": "BASE", "point": [9000, 7500], "name": "Kitchen", "number": "103",
         "wet": True, **finishes},
    ]  # fmt: skip
    return arch_lib.Architecture.model_validate(data)


def _beam() -> BeamDetail:
    """A two-span beam line with continuous, cut-off and hooked bars."""
    return BeamDetail(
        mark="B1",
        members=["B1", "B2"],
        level="Level 1",
        width=300,
        depth=500,
        cover=40,
        length=12000,
        supports=[Support(-200, 200, "C1"), Support(5800, 6200, "C2"), Support(11800, 12200, "C3")],
        bars=[
            BeamBar("B1-T1", 16, 2, -160, 12160, "top", 1, 256, 256, cut_length=12780.5),
            BeamBar("B1-T2", 16, 1, 4200, 7800, "top"),
            BeamBar("B1-T3", 20, 1, -160, 1800, "top", 1, 300, 0),
            BeamBar("B1-B1", 16, 3, -160, 12160, "bottom", 1, 256, 256),
            BeamBar("B1-B2", 12, 2, 900, 5100, "bottom", 2),
        ],
        links=[
            LinkZone(250, 1250, 10, 100, 2, "B1-S1"),
            LinkZone(1250, 4750, 10, 150, 2, "B1-S1"),
            LinkZone(4750, 5750, 10, 100, 2, "B1-S1"),
        ],
        sections=[("A", 600), ("B", 3000)],
        slab=150,
    )


# ─────────────────────────────── sheet setup ───────────────────────────────


@pytest.mark.parametrize("size", ["A1", "A2", "A3"])
def test_sheet_size_frame_and_title_block(size: str) -> None:
    info = TitleInfo(
        project="Test Tower",
        number="P-7",
        client="Owner Ltd",
        address="Dhaka",
        firm="Firm Ltd",
        engineer="E. Engineer",
        drawn="AB",
        checked="CD",
        approved="EF",
        date="2026-01-02",
        revision="B",
    )
    sheet = Sheet("S-123", "Framing plan level 1", size, 100, info, north=0)
    sheet.finish()
    w, h = PAPER[size]
    outer = next(e for e in sheet.msp.query("LWPOLYLINE[layer=='S-SHEET']"))
    xs = [p[0] for p in outer.get_points("xy")]
    ys = [p[1] for p in outer.get_points("xy")]
    assert (max(xs) - min(xs), max(ys) - min(ys)) == pytest.approx((w * 100, h * 100))
    texts = _texts(sheet.doc)
    for value in (
        "Test Tower",
        "P-7",
        "Owner Ltd",
        "Dhaka",
        "Firm Ltd",
        "E. Engineer",
        "AB",
        "CD",
        "EF",
        "2026-01-02",
        "B",
        "S-123",
        "1:100",
        size,
        "N",
    ):
        assert value in texts, value
    assert "FRAMING PLAN LEVEL 1" in texts
    assert any("SAEngine" in t for t in texts)
    # the paper space layout: one viewport of the sheet at 1:100
    layout = sheet.doc.layouts.get("S-123")
    viewport = next(e for e in layout.query("VIEWPORT") if e.dxf.id > 1)
    assert viewport.dxf.view_height == pytest.approx(h * 100)


def test_title_info_from_settings_keys() -> None:
    info = TitleInfo.from_dict(
        {
            "name": "P",
            "projectNumber": "12",
            "drawnBy": "X",
            "checkedBy": "Y",
            "approvedBy": "Z",
            "location": "Khulna",
            "revisions": [{"rev": "A", "date": "d", "description": "first"}],
        }
    )
    assert (info.project, info.number, info.drawn, info.checked, info.approved, info.address) == (
        "P",
        "12",
        "X",
        "Y",
        "Z",
        "Khulna",
    )
    assert info.revisions[0].description == "first"


def test_layers_styles_and_dimension_style() -> None:
    sheet = Sheet("S-1", "T", "A3", 50, TitleInfo())
    doc = sheet.doc
    for name, color, linetype, lineweight, _, _ in LAYERS:
        layer = doc.layers.get(name)
        assert (layer.color, layer.dxf.linetype, layer.dxf.lineweight) == (
            color,
            linetype,
            lineweight,
        )
    assert doc.layers.get("S-GRID").dxf.linetype == "CENTER"
    assert doc.layers.get("S-VIEWPORT").dxf.plot == 0
    assert doc.styles.get("SAE").dxf.font == "arial.ttf"
    style = doc.dimstyles.get("SAE-50")
    assert (style.dxf.dimscale, style.dxf.dimtxt, style.dxf.dimblk) == (50, 2.5, "ARCHTICK")
    assert doc.units == ezdxf.units.MM


# ─────────────────────────────── plans ───────────────────────────────


def test_framing_plan_of_a_two_by_two_bay_frame() -> None:
    building = _frame_two_by_two()
    sheet = Sheet("S-101", "Framing plan", "A1", 100, TitleInfo())
    spec = framing_plan(building, building.levels[1])
    sheet.view(spec, *sheet.area[:2])
    msp = sheet.msp
    # 3 + 3 grid lines, a bubble at each end, chain dims (2 + 2) and the overall dims (1 + 1)
    assert len(msp.query("LINE[layer=='S-GRID']")) == 6
    assert len(msp.query("CIRCLE[layer=='S-GRID-BUBBLE']")) == 12
    dims = msp.query("DIMENSION")
    assert len(dims) == 6
    measured = sorted(round(d.get_measurement()) for d in dims)
    assert measured == [5000, 5000, 6000, 6000, 10000, 12000]
    texts = _texts(sheet.doc)
    for mark in ("C1", "C9", "B1 300x500", "B12 300x500", "A", "C", "1", "3"):
        assert mark in texts
    assert sum(t == "150 THK" for t in texts) == 4
    # columns below the level are hatched, beams under the slab are hidden lines
    assert len(msp.query("HATCH[layer=='S-HATCH']")) == 9
    assert len(msp.query("LINE[layer=='S-BEAM']")) == 24
    assert sheet.labels.overlaps() == []


def test_grid_dimensions_count() -> None:
    b = Building(grids_x=[Grid("A", 0), Grid("B", 4000)], grids_y=[Grid("1", 0)])
    sheet = Sheet("S-1", "T", "A3", 100, TitleInfo())
    spec = framing_plan(b, Level("L", "L", 0))
    view = sheet.view(spec, *sheet.area[:2])
    assert grids(view, b, (0, 0, 4000, 0)) == 1  # one span: no overall dimension


# ─────────────────────────────── beam elevations ───────────────────────────────


def _bar_polylines(sheet: Sheet) -> dict[str, list]:
    found: dict[str, list] = {}
    for e in sheet.msp.query("LWPOLYLINE[layer=='S-REBAR-MAIN']"):
        tags = read_tags(e)
        if "mark" in tags:
            found.setdefault(tags["mark"], []).append(e)
    return found


def _length(polyline) -> float:
    pts = list(polyline.get_points("xy"))
    return sum(math.dist(a, b) for a, b in itertools.pairwise(pts))


def test_beam_elevation_bar_lengths_match_the_detailing() -> None:
    beam = _beam()
    sheet = Sheet("S-201", "Beams", "A1", 50, TitleInfo())
    sheet.view(beam_elevation(beam, 50, 25), *sheet.area[:2])
    bars = _bar_polylines(sheet)
    for bar in beam.bars:
        (entity,) = bars[bar.mark]
        # the elevation is the sheet's base scale: model units are real millimetres
        assert _length(entity) == pytest.approx(bar.length, abs=0.01)
        pts = list(entity.get_points("xy"))
        xs = [p[0] for p in pts]
        assert max(xs) - min(xs) == pytest.approx(bar.end - bar.start, abs=0.01)
        tags = read_tags(entity)
        assert tags["drawn"] == f"{bar.length:.0f}"
        # the cutting length is the detailing model's, not the sum of the drawn dimensions
        if bar.cut_length is None:
            assert "length" not in tags
        else:
            assert tags["length"] == f"{bar.cut_length:.0f}" != tags["drawn"]
    # links at their spacings: 11 + 24 + 11 in the three zones
    assert len(sheet.msp.query("LINE[layer=='S-REBAR-LINK']")) >= sum(z.count for z in beam.links)
    measured = {round(d.get_measurement()) for d in sheet.msp.query("DIMENSION")}
    assert {3600, 1960, 4200} <= measured  # the cut-off bars' extents
    assert {1000, 3500} <= measured  # the link zones
    texts = _texts(sheet.doc)
    assert "B1-T2 1Ø16" in texts and "SECTION A-A" in texts and "SECTION B-B" in texts
    assert sheet.labels.overlaps() == []


def test_beam_section_dimensions_read_real_millimetres() -> None:
    sheet = Sheet("S-201", "Beams", "A1", 50, TitleInfo())
    sheet.view(beam_elevation(_beam(), 50, 25), *sheet.area[:2])
    # the 1:25 sections are drawn twice real size; their dimension style scales back (DIMLFAC
    # 0.5, a style of its own: LibreCAD reads no entity overrides)
    style = sheet.doc.dimstyles.get("SAE-50-25")
    assert style.dxf.dimlfac == pytest.approx(0.5)
    sections = [d for d in sheet.msp.query("DIMENSION") if d.dxf.dimstyle == "SAE-50-25"]
    values = sorted(round(d.get_measurement() * 0.5) for d in sections)
    assert values == [300, 300, 500, 500]
    assert all(not d.has_xdata("ACAD") for d in sheet.msp.query("DIMENSION"))


def test_beam_detail_from_the_detailing_model() -> None:
    """The adapter of a detailing-model beam line: runs, legs and zones as given."""
    element = {
        "id": "B1+B2",
        "kind": "beam",
        "member": "B1 + B2",
        "members": ["B1", "B2"],
        "story": "L1",
        "at": {
            "origin": [0, 0],
            "direction": [1, 0],
            "length": 13000,
            "width": 300,
            "depth": 500,
            "cover": 40,
            "supports": [
                {"s": 150, "width": 400, "ref": "C1"},
                {"s": 6000, "width": 600, "ref": "C2"},
            ],
            "spans": [{"from": 350, "to": 5700}],
        },
        "bars": [
            {
                "mark": "B1-T2",
                "role": "top",
                "dia": 16,
                "count": 2,
                "shape": "L",
                "segments": [10633.3, 256],
                "dims": {"A": 10633.3, "B": 256},
                "length": 10849.3,
                "at": {
                    "from": 0,
                    "to": 10633.3,
                    "face": "top",
                    "layer": 1,
                    "hooks": ["down", None],
                },
                "lap": 1125,
            },
            {
                "mark": "B1-B1",
                "role": "bottom",
                "dia": 16,
                "count": 4,
                "shape": "U",
                "segments": [256, 11744, 256],
                "length": 12200,
                "at": {"from": 0, "to": 11744, "face": "bottom", "layer": 1, "hooks": ["up", "up"]},
            },
            {"mark": "B1-S1", "role": "stirrup", "dia": 10, "count": 36, "segments": [220, 420]},
        ],
        "transverse": [
            {"from": 400, "to": 5650, "spacing": 150, "zone": "middle", "mark": "B1-S1"}
        ],
    }
    beam = beam_detail(element, "Level 1", slab=150)
    t2, b1 = beam.bars
    assert (t2.start, t2.end, t2.leg_start, t2.leg_end, t2.note) == (0, 10633.3, 256, 0, "LAP 1125")
    assert (b1.leg_start, b1.leg_end, b1.face) == (256, 256, "bottom")
    assert beam.links[0].dia == 10 and beam.links[0].spacing == 150
    assert [(s.start, s.end, s.label) for s in beam.supports] == [
        (-50, 350, "C1"),
        (5700, 6300, "C2"),
    ]
    sheet = Sheet("S-201", "Beams", "A1", 50, TitleInfo())
    sheet.view(beam_elevation(beam), *sheet.area[:2])
    bars = _bar_polylines(sheet)
    assert _length(bars["B1-T2"][0]) == pytest.approx(10633.3 + 256, abs=0.01)
    assert read_tags(bars["B1-T2"][0])["length"] == "10849"  # the model's cutting length
    assert read_tags(bars["B1-B1"][0])["length"] == "12200"
    assert _length(bars["B1-B1"][0]) == pytest.approx(11744 + 2 * 256, abs=0.01)


# ─────────────────────────────── the drawing set ───────────────────────────────


def _synthetic_set() -> DrawingSet:
    building = _frame_two_by_two()
    section = ColumnSection(
        400,
        600,
        40,
        [(4, 20), (6, 16)],
        10,
        150,
        legs_x=3,
        legs_y=2,
        zone_length=600,
        zone_spacing=100,
    )
    slab = building.slabs[0]
    return DrawingSet(
        architecture=_architecture(),
        title=TitleInfo(project="Synthetic", firm="Firm"),
        building=building,
        columns=[
            ColumnLine("C1", ["C1"], {"L1": section}),
            ColumnLine("C2", ["C2"], {"L1": section}),
        ],
        beams=[_beam()],
        slabs=[
            SlabDetail(
                "S1",
                "S1",
                slab.boundary,
                150,
                20,
                "L1",
                Mesh(10, 150, "S1-BX1"),
                Mesh(10, 150, "S1-BY1"),
            )
        ],
        footings=[
            FootingDetail(
                "F1",
                ["F1"],
                2000,
                1500,
                500,
                75,
                Mesh(12, 150, "F1-BX1"),
                Mesh(12, 150, "F1-BY1", 192),
                column=(400, 600),
                starters=(10, 20),
                founding_level=-1500,
            )
        ],
        walls=[
            WallDetail(
                "W1",
                ["W1"],
                4000,
                3200,
                200,
                25,
                Mesh(10, 200, "W1-V1"),
                Mesh(10, 200, "W1-H1"),
                boundary_length=400,
                boundary_bars=(6, 16),
                hoops=Mesh(10, 100),
                openings=[(1000, 0, 900, 2100)],
                levels=[("Base", 0), ("Level 1", 3200)],
            )
        ],
        stairs=[
            StairDetail(
                "ST1",
                ["ST1"],
                160,
                300,
                [10, 10],
                150,
                1200,
                1200,
                150,
                20,
                Mesh(12, 125, "ST1-M1"),
                Mesh(10, 200, "ST1-N1"),
                Mesh(12, 150, "ST1-T1"),
            )
        ],
        bbs=[
            Table(
                "Bar bending schedule",
                [
                    {"key": "mark", "title": "Bar\nmark", "width": 6, "align": "left"},
                    {"key": "L", "title": "Length\n(mm)", "width": 6, "align": "right"},
                    {"key": "r", "title": "Remarks", "width": 20, "align": "left"},
                ],
                [[f"B1-T{i}", f"{1000 + i}", "lap 800\ncut-off"] for i in range(150)],
                [{"first": i, "count": 1} for i in range(150)],
            )
        ],
        notes=["All dimensions in millimetres.", "Concrete f'c 24 MPa."],
        tables=[
            Table(
                "Clear covers",
                [
                    {"key": "k", "title": "Element", "align": "left"},
                    {"key": "c", "title": "Cover", "align": "right"},
                ],
                [["beam", "40"], ["slab", "20"]],
            )
        ],
    )


def test_drawing_set_sheets_dxf_round_trip_and_pdf(tmp_path: Path) -> None:
    from pypdf import PdfReader

    data = _synthetic_set()
    sheets = build_sheets(data, DrawingSettings.from_dict({"size": "A2", "firstNumber": 201}))
    numbers = [s.number for s in sheets if s.number.startswith("S-")]
    assert numbers == [f"S-{201 + i}" for i in range(len(numbers))]
    # the architectural sheets after the structural ones, numbered on their own
    arch = [s.number for s in sheets if s.number.startswith("A-")]
    assert arch == [f"A-{201 + i}" for i in range(len(arch))]
    assert [s.number for s in sheets] == numbers + arch
    titles = [s.title for s in sheets]
    assert titles[0] == "General notes"
    assert any(t.startswith("Framing plan") for t in titles)
    assert any(t.startswith("Bar bending schedule (") for t in titles)  # split over sheets
    for kind in (
        "Column schedule",
        "Beam elevations",
        "Foundation details",
        "Wall details",
        "Stair details",
        "Slab reinforcement",
    ):
        assert any(t.startswith(kind) for t in titles), kind
    result = write_drawings(sheets, tmp_path, ppi=20)
    assert len(result["sheets"]) == len(sheets)
    for row in result["sheets"]:
        doc = ezdxf.readfile(row["dxf"])
        auditor = doc.audit()
        assert not auditor.has_errors, auditor.errors
        assert Path(row["png"]).is_file()
        assert row["size"] == "A2"
    reader = PdfReader(result["pdf"])
    assert len(reader.pages) == len(sheets)
    w, h = PAPER["A2"]
    box = reader.pages[0].mediabox
    assert (float(box.width), float(box.height)) == pytest.approx(
        (w / 25.4 * 72, h / 25.4 * 72), abs=1
    )


def test_text_is_legible_on_paper() -> None:
    sheets = build_sheets(_synthetic_set(), DrawingSettings())
    for sheet in sheets:
        for e in sheet.msp.query("TEXT"):
            assert e.dxf.height / sheet.scale >= 2.5 - 1e-9, (sheet.number, e.dxf.text)
        assert sheet.labels.overlaps() == [], sheet.number


def test_plans_drawn_at_a_smaller_scale_when_too_large() -> None:
    b = Building(
        grids_x=[Grid("A", 0), Grid("B", 90000)],
        grids_y=[Grid("1", 0), Grid("2", 40000)],
        levels=[Level("L1", "Level 1", 3000)],
    )
    b.slabs.append(
        PlanSlab("S1", "S1", [(0, 0), (90000, 0), (90000, 40000), (0, 40000)], 150, 3000)
    )
    data = DrawingSet(building=b)
    sheets = build_sheets(data, DrawingSettings.from_dict({"size": "A3"}))
    plan = next(s for s in sheets if s.title.startswith("Framing plan"))
    assert plan.scale > 100
    assert any("does not fit" in p for p in data.problems)


@pytest.mark.skipif(not SAMPLE.is_dir(), reason="the app's sample is not in this checkout")
def test_the_sample_project(tmp_path: Path) -> None:
    from saengine.drawings import bbs
    from saengine.drawings.detailing import detailing_model

    root = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    model = detailing_model(root)
    schedule = bbs.sheet_table(bbs.bar_schedule(model))
    data = drawing_set(
        root, detailing=model, schedule=schedule, title={"firm": "Example Engineers"}
    )
    assert data.title.project == "Sample Frame"
    sheets = build_sheets(data)
    titles = [s.title for s in sheets]
    assert titles[:3] == ["General notes", "Foundation plan", "Framing plan - Level 1"]
    for kind in (
        "Slab reinforcement",
        "Column schedule",
        "Beam elevations",
        "Foundation details",
        "Wall details",
        "Stair details",
        "Bar bending schedule",
    ):
        assert any(t.startswith(kind) for t in titles), kind
    for sheet in sheets:
        assert sheet.labels.overlaps() == [], sheet.number
        assert sheet.labels.conflicts() == [], sheet.number
    # every beam bar drawn carries the cutting length of the BBS and of the detailing model
    # (independent of what the elevation draws)
    keys = [c["key"] for c in schedule["columns"]]
    listed = {r[keys.index("mark")]: r[keys.index("cutting_length")] for r in schedule["rows"]}
    model_bars = {b["mark"]: b for e in model["elements"] if e["kind"] == "beam" for b in e["bars"]}
    beams = next(s for s in sheets if s.title == "Beam elevations")
    drawn = _bar_polylines(beams)
    assert drawn
    for mark, entities in drawn.items():
        for e in entities:
            tags = read_tags(e)
            assert tags["length"] == listed[mark], mark
            assert float(tags["modelLength"]) == pytest.approx(model_bars[mark]["length"], abs=0.1)
    # the footing section: the model's bar count, the column where it stands
    footing = next(s for s in sheets if s.title == "Foundation details")
    f1 = next(e for e in model["elements"] if e["id"] == "F1")
    by = next(b for b in f1["bars"] if b["at"]["direction"] == "Y")
    dots = [h for h in footing.msp.query("HATCH[layer=='S-REBAR-MAIN']")]
    assert len(dots) >= by["count"]
    # on A3 too: everything inside the drawing area, no label on a line or forced
    data3 = drawing_set(root, detailing=model, schedule=schedule)
    for sheet in build_sheets(data3, DrawingSettings.from_dict({"size": "A3"})):
        assert sheet.labels.overlaps() == [] and sheet.labels.conflicts() == [], sheet.number
        x0, y0, x1, y1 = sheet.area
        for view in sheet.views:
            bx0, by0, bx1, by1 = view.box
            assert bx0 >= x0 - 1e-6 and bx1 <= x1 + 1e-6, (sheet.number, view.spec.title)
            assert by0 >= y0 - 1e-6 and by1 <= y1 + 1e-6, (sheet.number, view.spec.title)
    assert not [p for p in data3.problems if "larger than" in p]


@pytest.mark.parametrize("size", ["A1", "A3"])
def test_views_stay_inside_the_drawing_area(size: str) -> None:
    data = _synthetic_set()
    sheets = build_sheets(data, DrawingSettings.from_dict({"size": size}))
    for sheet in sheets:
        x0, y0, x1, y1 = sheet.area
        for view in sheet.views:
            bx0, by0, bx1, by1 = view.box
            assert bx0 >= x0 - 1e-6 and by0 >= y0 - 1e-6, (sheet.number, view.spec.title)
            assert bx1 <= x1 + 1e-6 and by1 <= y1 + 1e-6, (sheet.number, view.spec.title)
    if size == "A3":  # the 12 m beam does not fit at 1:50 on A3
        beams = next(s for s in sheets if s.title.startswith("Beam elevations"))
        assert beams.scale_text == "AS SHOWN"
        assert any("does not fit" in p for p in data.problems)


# ─────────────────────────────── tables on small sheets ───────────────────────────────


def _bbs_like_table(rows: int = 40) -> Table:
    """A table with the 16 columns of the bar bending schedule (as saengine.drawings.bbs
    writes them) and long remarks."""
    spec = [
        ("member", "Member", "left", 8),
        ("mark", "Bar\nmark", "left", 8),
        ("size", "Type and\nsize", "left", 12),
        ("shape", "Shape\ncode", "left", 6),
        ("A", "A\n(mm)", "right", 6),
        ("B", "B\n(mm)", "right", 5),
        ("C", "C\n(mm)", "right", 5),
        ("D", "D\n(mm)", "right", 5),
        ("E", "E/R\n(mm)", "right", 5),
        ("members", "No. of\nmbrs", "right", 7),
        ("per_member", "No. in\neach", "right", 7),
        ("total_count", "Total\nno.", "right", 6),
        ("cutting_length", "Length of\neach (mm)", "right", 10),
        ("total_length", "Total\nlength (m)", "right", 11),
        ("mass", "Mass\n(kg)", "right", 7),
        ("remarks", "Remarks", "left", 28),
    ]
    columns = [{"key": k, "title": t, "align": a, "width": w} for k, t, a, w in spec]
    remark = "over the support at 6000,\n2025 mm from each face\n(0.30 ln, Figure 6.6.20),\ncut-off"
    body = [
        [
            "B1 + B2",
            f"B1-T{i}",
            "B420DWR Ø16",
            "11",
            "10633",
            "256",
            "",
            "",
            "",
            "1",
            "2",
            "2",
            "10850",
            "21.70",
            "34.25",
            remark,
        ]
        for i in range(rows)
    ]
    return Table(
        "Bar bending schedule", columns, body, [{"first": i, "count": 1} for i in range(rows)]
    )


def test_a_wide_schedule_is_fitted_to_an_a3_sheet() -> None:
    from saengine.drawings.sheets.layout import drawing_area
    from saengine.drawings.sheets.schedules import fit_table

    table = _bbs_like_table()
    area = drawing_area("A3")
    room = area[2] - area[0]
    fitted, widths, ok = fit_table(table, room - 4)
    assert ok and sum(widths) <= room - 4 + 1e-6
    # the remarks and the headers are wrapped onto more lines, no word is cut
    assert fitted.rows[0][-1].count("\n") > table.rows[0][-1].count("\n")
    assert set(" ".join(fitted.rows[0][-1].split()).split()) == set(table.rows[0][-1].split())
    data = DrawingSet(bbs=[table])
    sheets = build_sheets(data, DrawingSettings.from_dict({"size": "A3"}))
    assert not [p for p in data.problems if "larger than" in p]
    for sheet in sheets:
        x0, y0, x1, y1 = sheet.area
        for view in sheet.views:
            bx0, by0, bx1, by1 = view.box
            assert bx0 >= x0 - 1e-6 and bx1 <= x1 + 1e-6, (sheet.number, view.box)
            assert by0 >= y0 - 1e-6 and by1 <= y1 + 1e-6, (sheet.number, view.box)
        # and nothing of the table reaches the title block
        xs = [
            p[0]
            for e in sheet.msp.query("LINE[layer=='S-TABLE']")
            for p in (e.dxf.start, e.dxf.end)
        ]
        assert max(xs) / sheet.scale <= x1 + 1e-6


def test_a_table_that_fits_keeps_its_widths() -> None:
    from saengine.drawings.sheets.schedules import _col_widths, fit_table

    table = _bbs_like_table(3)
    fitted, widths, ok = fit_table(table, 1000)
    assert ok and fitted is table and widths == _col_widths(table)


# ─────────────────────────────── footing details ───────────────────────────────


def _offset_footing() -> FootingDetail:
    return FootingDetail(
        "F1",
        ["F1"],
        2000,
        1500,
        500,
        75,
        Mesh(12, 150, "F1-BX1", count=10),
        Mesh(12, 150, "F1-BY1", 192, count=13),
        column=(400, 600),
        column_at=(150.0, 0.0),
        starters=(10, 20),
        starter_leg=320,
        starter_hook="toCentre",
        starter_inset=40 + 10 + 10,
        starter_mark="C1-D1",
    )


def test_footing_section_bars_and_starters_follow_the_model() -> None:
    from saengine.drawings.sheets.details import footing_detail

    f = _offset_footing()
    sheet = Sheet("S-107", "Footings", "A1", 25, TitleInfo())
    sheet.view(footing_detail(f, 25), *sheet.area[:2])
    msp = sheet.msp
    # the 1:25 detail on a 1:25 sheet: model units are real millimetres
    outlines = [e for e in msp.query("LWPOLYLINE[layer=='S-CONC']") if e.closed and len(e) == 4]
    boxes = []
    for e in outlines:
        xs = [p[0] for p in e.get_points("xy")]
        ys = [p[1] for p in e.get_points("xy")]
        boxes.append((min(xs), min(ys), max(xs), max(ys)))
    plan = next(b for b in boxes if round(b[2] - b[0]) == 2000 and round(b[3] - b[1]) == 1500)
    section = next(b for b in boxes if round(b[2] - b[0]) == 2000 and round(b[3] - b[1]) == 500)
    # the cross (Y) bars in the section: the model's 13, spread over the footing's length
    dots = [c for c in msp.query("CIRCLE[layer=='S-REBAR-MAIN']")]
    assert len(dots) == 13
    xs = sorted(c.dxf.center[0] - (section[0] + section[2]) / 2 for c in dots)
    # 12 spaces of 150 centred in the footing, inside the cover at both ends
    assert xs[0] == pytest.approx(-900, abs=0.5) and xs[-1] == pytest.approx(900, abs=0.5)
    assert xs[0] >= -1000 + 75 + 6 - 1e-6
    assert xs[1] - xs[0] == pytest.approx(150, abs=0.5)
    # the column 150 mm off the footing's centre, in plan and in section
    col = next(e for e in msp.query("LWPOLYLINE[layer=='S-COLS']") if e.closed)
    cx = sum(p[0] for p in col.get_points("xy")) / 4 - (plan[0] + plan[2]) / 2
    assert cx == pytest.approx(150, abs=0.5)
    # the starters: inside the ties (60 from the faces), feet of 320 towards the footing centre
    starters = [
        e
        for e in msp.query("LWPOLYLINE[layer=='S-REBAR-MAIN']")
        if read_tags(e).get("mark") == "C1-D1"
    ]
    assert len(starters) == 2
    mid = (section[0] + section[2]) / 2
    for e in starters:
        (x_top, _), (x_bend, _), (x_foot, y_foot) = list(e.get_points("xy"))
        assert x_top == x_bend
        assert x_bend - mid in (pytest.approx(150 - 200 + 60), pytest.approx(150 + 200 - 60))
        assert x_foot < x_bend  # towards the centre (both bars are right of it)
        assert x_bend - x_foot == pytest.approx(320 - 10)
        assert y_foot - section[1] == pytest.approx(75 + 12 + 12 + 10)  # on the mesh
    assert sheet.labels.conflicts() == []


# ─────────────────────────────── adapters ───────────────────────────────


def test_column_end_zone_length_is_measured_from_the_joint_face() -> None:
    from types import SimpleNamespace

    from saengine.drawings.sheets.project import column_section

    t = SimpleNamespace(
        profile=SimpleNamespace(shape="rectangle", xDim=400, yDim=600),
        reinforcement=SimpleNamespace(
            longitudinal=[SimpleNamespace(dia=20, count=10)],
            transverse=SimpleNamespace(dia=10, spacing=150, legs=2, legsX=None),
            cover=40,
        ),
    )

    def element(rows):
        return {
            "id": "C7",
            "at": {"bottom": 3200, "top": 6400, "clearHeight": 2700},
            "bars": [{"mark": "C7-H1", "role": "tie", "dia": 10, "count": 30}],
            "transverse": rows,
        }

    # the first hoop 50 above the floor: the bottom row is 550 long, lo is 600
    rows = [
        {"from": 3250, "to": 3800, "spacing": 100, "zone": "lo", "mark": "C7-H1"},
        {"from": 3800, "to": 5300, "spacing": 150, "zone": "middle", "mark": "C7-H1"},
        {"from": 5300, "to": 5900, "spacing": 100, "zone": "lo", "mark": "C7-H1"},
        {"from": 5900, "to": 6350, "spacing": 100, "zone": "joint", "mark": "C7-H1"},
    ]
    s = column_section(element(rows), t)
    assert (s.zone_length, s.zone_spacing, s.tie_spacing) == (600, 100, 150)
    # an upper row that does not reach the soffit (cut by a splice zone) does not set lo
    rows[2] = {"from": 5300, "to": 5700, "spacing": 100, "zone": "lo", "mark": "C7-H1"}
    assert column_section(element(rows), t).zone_length == 600


def test_slab_bar_lines_keep_clear_of_openings() -> None:
    from saengine.drawings.sheets.plans import clear_pieces, slab_plan
    from saengine.drawings.sheets.project import across_position

    # a free line beside the opening: moved off the preferred share
    hole = (3000, 700, 5600, 2400)
    v = across_position(0, 6000, (0, 5000), True, 0.3, [hole])
    assert not (700 - 150 < v < 2400 + 150)
    # an opening across the whole band: the line is drawn broken at it
    assert clear_pieces((0, 2000), (6000, 2000), [(3000, 700, 5600, 4840)]) == [
        ((0, 2000), (3000, 2000)),
        ((5600, 2000), (6000, 2000)),
    ]
    building = _frame_two_by_two()
    opening = [(3000, 700), (5600, 700), (5600, 4840), (3000, 4840)]
    building.slabs[0].openings = [opening]
    slab = SlabDetail(
        "S1",
        "S1",
        building.slabs[0].boundary,
        150,
        20,
        "L1",
        openings=[opening],
        bottom_runs=[
            __import__("saengine.drawings.sheets.model", fromlist=["TopBar"]).TopBar(
                (150, 2000), (5850, 2000), Mesh(10, 150, "S1-BX2")
            )
        ],
    )
    sheet = Sheet("S-104", "Slab", "A1", 50, TitleInfo())
    sheet.view(slab_plan(building, [slab], building.levels[1], 50), *sheet.area[:2])
    view = sheet.views[0]
    x0, y0 = view.m(3000, 700)
    x1, y1 = view.m(5600, 4840)
    for e in sheet.msp.query("LWPOLYLINE[layer=='S-REBAR-MAIN']"):
        if read_tags(e).get("mark") != "S1-BX2":
            continue
        pts = list(e.get_points("xy"))
        for (ax, ay), (bx, by) in itertools.pairwise(pts):
            mid = ((ax + bx) / 2, (ay + by) / 2)
            assert not (x0 < mid[0] < x1 and y0 < mid[1] < y1), "a bar drawn through the opening"
    assert sheet.labels.conflicts() == []


def test_identical_beams_of_typical_floors_share_one_elevation() -> None:
    from saengine.drawings.sheets.project import merge_beams

    beams = []
    for n in range(1, 21):
        b = _beam()
        b.mark, b.members, b.level = f"B{n}", [f"B{n}"], f"Level {n}"
        beams.append(b)
    merged = merge_beams(beams)
    assert len(merged) == 1
    assert merged[0].level == "Level 1 to Level 20, 20 levels"
    assert merged[0].mark.split(", ") == [f"B{n}" for n in range(1, 21)]
    spec = beam_elevation(merged[0])
    assert "20 beams" in spec.title
    sheet = Sheet("S-106", "Beams", "A1", 50, TitleInfo())
    sheet.view(spec, *sheet.area[:2])
    texts = " ".join(_texts(sheet.doc))
    assert "B20" in texts  # every mark is listed on the elevation
    # Members come in id order (L10 before L7): the title runs bottom up by elevation.
    beams = []
    for n in (10, 7, 8, 9):
        b = _beam()
        b.mark, b.members, b.level = f"B-L{n}", [f"B-L{n}"], f"Level {n}"
        beams.append(b)
    order = {f"Level {n}": 3200.0 * n for n in range(1, 11)}
    assert merge_beams(beams, order)[0].level == "Level 7 to Level 10, 4 levels"


def test_labels_keep_off_lines_and_leaders_off_texts() -> None:
    sheet = Sheet("S-1", "T", "A3", 100, TitleInfo())

    def draw(view) -> None:
        view.line((0, 0), (10000, 0), "S-REBAR-MAIN")  # a bar along y = 0
        view.text("1234", (5000, 600), TEXT_HEIGHT, "MC")  # a text right above the anchor
        # the preferred place is on the bar: the label moves off it
        view.label("MARK A", (5000, 0), [(0, 0, "MC")], leader=True)
        # rings=False and force=False: nothing is drawn where nothing is free
        assert view.label("MARK B", (5000, 0), [(0, 0, "MC")], rings=False, force=False) is None

    from saengine.drawings.sheets.layout import ViewSpec

    sheet.view(ViewSpec("V", 100, (0, -3000, 10000, 3000), draw), *sheet.area[:2])
    labels = sheet.labels
    assert labels.overlaps() == [] and labels.conflicts() == [] and labels.forced == []
    texts = _texts(sheet.doc)
    assert "MARK A" in texts and "MARK B" not in texts


def test_a_label_with_no_free_place_is_reported() -> None:
    sheet = Sheet("S-1", "T", "A3", 100, TitleInfo())

    def draw(view) -> None:
        for y in range(-3000, 3001, 100):  # hatching everywhere
            view.line((0, y), (10000, y), "S-REBAR-MAIN")
        view.label("NOWHERE", (5000, 0), [(0, 0, "MC")])

    from saengine.drawings.sheets.layout import ViewSpec

    sheet.view(ViewSpec("V", 100, (0, -3000, 10000, 3000), draw, pad=(0, 0, 0, 0)), *sheet.area[:2])
    assert sheet.labels.forced == ["NOWHERE"]
    assert any("NOWHERE" in c for c in sheet.labels.conflicts())


TEXT_HEIGHT = 2.5


# ─────────────────────────────── files ───────────────────────────────


def test_write_drawings_removes_the_files_of_an_earlier_run(tmp_path: Path) -> None:
    out = tmp_path / "Drawings"
    first = [Sheet(f"S-{101 + i}", f"Sheet {i}", "A3", 100, TitleInfo()) for i in range(3)]
    write_drawings(first, out, pdf=False)
    assert len(list(out.glob("*.dxf"))) == 3 and len(list((out / "previews").glob("*.png"))) == 3
    (out / "my notes.txt").write_text("mine", encoding="utf-8")
    (out / "elevation copy.dxf").write_text("0\nEOF\n", encoding="utf-8")
    second = [Sheet("S-101", "Renamed", "A3", 100, TitleInfo())]
    result = write_drawings(second, out, pdf=False)
    names = sorted(p.name for p in out.glob("*.dxf"))
    assert names == ["S-101 Renamed.dxf", "elevation copy.dxf"]
    assert sorted(p.name for p in (out / "previews").glob("*.png")) == ["S-101.png"]
    assert (out / "my notes.txt").exists()
    assert Path(result["sheets"][0]["dxf"]).name == "S-101 Renamed.dxf"
    # writing some sheets only keeps the others
    write_drawings([Sheet("S-102", "Extra", "A3", 100, TitleInfo())], out, pdf=False, clean=False)
    assert sorted(p.name for p in out.glob("S-*.dxf")) == ["S-101 Renamed.dxf", "S-102 Extra.dxf"]
    write_drawings(second, out, pdf=False, png=False)
    assert sorted(p.name for p in out.glob("S-*.dxf")) == ["S-101 Renamed.dxf"]

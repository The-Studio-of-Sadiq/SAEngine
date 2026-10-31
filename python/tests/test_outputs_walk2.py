"""The drawings and report fixes of usability walkthrough 2 (batch 10): undesigned members on the
sheets and in the report, the report's appendix scope, the column schedule's labels."""

from __future__ import annotations

from types import SimpleNamespace

from saengine.drawings.sheets.layout import Sheet, TitleInfo
from saengine.drawings.sheets.model import ColumnLine, ColumnSection, Grid, Level
from saengine.drawings.sheets.project import (
    NOT_FOR_CONSTRUCTION,
    column_lines,
    grid_position,
    undesigned_members,
)
from saengine.drawings.sheets.schedules import column_schedule
from saengine.report.build import _appendix, _not_designed, counted, design_status


def _section(bars: list[tuple[int, float]], zone: float | None = 75.0) -> ColumnSection:
    return ColumnSection(400, 400, 40, bars, 10, 75, zone_length=600, zone_spacing=zone)


def _texts(spec) -> list[str]:
    sheet = Sheet("S-116", "Column schedule", "A1", 1, TitleInfo())
    sheet.view(spec, *sheet.area[:2])
    return [e.dxf.text for e in sheet.msp.query("TEXT")]


def test_an_undesigned_column_says_so_in_the_schedule() -> None:
    # N-R1: 400x400 columns with no bars showed "-" on sheets marked current.
    assert not _section([]).designed
    assert _section([]).bars_text == "NOT DESIGNED"
    levels = [Level("L1", "Level 1", 3000), Level("L2", "Level 2", 6000)]
    lines = [ColumnLine("A1", ["C1"], {"L1": _section([]), "L2": _section([(8, 20)])})]
    (spec,) = column_schedule(lines, levels)
    text = " ".join(_texts(spec))
    assert "NOT DESIGNED" in text
    assert "8Ø20" in text


def test_equal_tie_spacing_reads_throughout() -> None:
    # N-R11: "Ø10@75 in lo 2400" over "Ø10@75 elsewhere".
    assert _section([(8, 20)]).ties_text == ["Ø10@75 throughout"]
    assert _section([(8, 20)], zone=100.0).ties_text[0] == "Ø10@100 in lo 600"


def test_undesigned_members_are_counted_by_kind_and_type() -> None:
    elements = [
        {"kind": "column", "type": "C400", "id": "C1", "notes": ["C400 has no reinforcement: not detailed"]},
        {"kind": "column", "type": "C400", "id": "C2", "notes": ["C400 has no reinforcement: not detailed"]},
        {"kind": "slab", "type": "S150", "id": "S1", "notes": ["no slab reinforcement: not detailed"]},
        {"kind": "beam", "type": "B1", "id": "B1+B2", "members": ["B1", "B2"],
         "notes": ["B1 has no reinforcement: not detailed"]},
        {"kind": "column", "type": "C900", "id": "C3", "notes": []},
    ]  # fmt: skip
    assert undesigned_members(elements) == {
        "column": {"C400": 2},
        "slab": {"S150": 1},
        "beam": {"B1": 2},
    }
    assert NOT_FOR_CONSTRUCTION == "NOT FOR CONSTRUCTION"


def test_column_lines_are_marked_by_grid_position() -> None:
    gx, gy = [Grid("A", 0.0), Grid("B", 6000.0)], [Grid("1", 0.0)]
    assert grid_position(6010, -20, gx, gy) == "B1"
    assert grid_position(3000, 0, gx, gy) is None
    profile = SimpleNamespace(shape="rectangle", xDim=400, yDim=400)
    t = SimpleNamespace(profile=profile, reinforcement=None)
    objects = SimpleNamespace(objects=[SimpleNamespace(id="C400", **vars(t))])
    columns = [
        {"id": f"C-B1-L{i}", "type": "C400", "story": f"L{i}", "bars": [],
         "at": {"position": [6000, 0], "bottom": 3000.0 * (i - 1)}}
        for i in (1, 2)
    ]  # fmt: skip
    (line,) = column_lines(columns, objects, gx, gy)
    assert line.mark == "B1"
    assert line.members == ["C-B1-L1", "C-B1-L2"]
    # Off the grid (150 mm off A1): its member id alone would read as grid C1.
    off = [{"id": "C1", "type": "C400", "story": "L1", "bars": [],
            "at": {"position": [150, 0], "bottom": 0.0}}]  # fmt: skip
    assert [line.mark for line in column_lines(off, objects, gx, gy)] == ["C1 (near A1)"]
    off[0]["at"]["position"] = [3000, 0]
    assert [line.mark for line in column_lines(off, objects, gx, gy)] == ["C1"]


def test_the_appendix_prints_the_governing_element_of_each_type_and_storey() -> None:
    # N-R2: 584 pages of every element's checks for a 10-storey frame.
    def el(i: str, t: str, u: float, ok: bool = True) -> dict:
        return {"id": i, "kind": "beam", "type": t, "utilisation": u, "ok": ok}

    elements = [el("B1", "B300", 0.5), el("B2", "B300", 0.9), el("B3", "B300", 1.2, ok=False),
                el("B4", "B300", 0.4), el("B5", "B400", 0.3)]  # fmt: skip
    storeys = {"B1": "L1", "B2": "L1", "B3": "L2", "B4": "L2", "B5": "L1"}
    chosen = {e["id"]: why for e, why in _appendix(elements, storeys, "governing")}
    assert chosen == {
        "B2": "governs the 2 of type B300 on L1",
        "B3": "governs the 2 of type B300 on L2",
        "B5": "",
    }
    # every failing element is printed even when another governs its group
    elements.append(el("B6", "B300", 1.1, ok=False))
    storeys["B6"] = "L2"
    assert [e["id"] for e, _ in _appendix(elements, storeys, "governing")] == [
        "B2",
        "B3",
        "B5",
        "B6",
    ]
    assert len(_appendix(elements, storeys, "all")) == 6
    assert _appendix(elements, storeys, "none") == []


def test_slabs_noted_as_not_designed_are_listed_and_counted() -> None:
    # N-R3: the cover omitted 28 undesigned columns and 120 slabs; 5.7 listed no slabs.
    report = {
        "skipped": [{"id": "C1", "kind": "column", "type": "C400", "reason": "no reinforcement"}],
        "notes": [
            "S1: slab not designed (no reinforcement, not analysed as shells)",
            "Another note.",
        ],
    }
    building = SimpleNamespace(elements=[SimpleNamespace(id="S1", type="S150")])
    rows, counts, notes = _not_designed(report, building)
    assert rows[1] == ["S1", "slab", "S150", "no reinforcement, not analysed as shells"]
    assert counts == {"column": 1, "slab": 1}
    assert notes == ["Another note."]
    assert counted({"column": 28, "slab": 120}) == "28 columns and 120 slabs"


def test_the_cover_names_members_not_designed() -> None:
    design = {"available": True, "checked": 10, "failed": 0,
              "counts": [["members", 10, 0]], "notDesigned": {"column": 28, "slab": 120}}  # fmt: skip
    status = design_status({"design": design, "foundations": {}})
    assert status["state"] == "incomplete"
    assert "28 columns and 120 slabs are not designed" in status["headline"]
    assert status["notDesigned"] == {"column": 28, "slab": 120}
    design["failed"], design["counts"] = 2, [["members", 10, 2]]
    status = design_status({"design": design, "foundations": {}})
    assert status["state"] == "fail"
    assert status["headline"].startswith("DESIGN FAILS: 2 of 10 members fail")
    assert "28 columns and 120 slabs are not designed" in status["headline"]

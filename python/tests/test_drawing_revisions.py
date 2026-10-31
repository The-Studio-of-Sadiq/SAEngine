"""Drawing revisions (saengine.drawings.sheets.revisions): the engineer's edits kept on
regenerate, revision codes, clouds around changes since the last issue, the register, and the
DWG writer (LibreDWG's dxf2dwg, a separate program)."""

from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest

from saengine.drawings.sheets import revisions as rv
from saengine.drawings.sheets.layout import Sheet, TitleInfo
from saengine.library import dwg


def _sheet(number: str = "S-101", extra: bool = False) -> Sheet:
    sheet = Sheet(number, "Framing plan", "A3", 100, TitleInfo(project="P", date="2026-11-01"))
    x0, y0, _x1, _y1 = sheet.area
    sheet.msp.add_line(
        sheet.m(x0 + 20, y0 + 20), sheet.m(x0 + 80, y0 + 20), dxfattribs={"layer": "S-BEAM"}
    )
    sheet.msp.add_circle(sheet.m(x0 + 50, y0 + 50), 300, dxfattribs={"layer": "S-COLS"})
    if extra:
        sheet.msp.add_line(
            sheet.m(x0 + 150, y0 + 120), sheet.m(x0 + 190, y0 + 120), dxfattribs={"layer": "S-BEAM"}
        )
    return sheet


@pytest.mark.parametrize(
    ("code", "after"),
    [
        ("", "0"),
        ("0", "1"),
        ("9", "10"),
        ("A", "B"),
        ("Z", "AA"),
        ("AZ", "BA"),
        ("P1", "P2"),
        ("C09", "C10"),
        ("b", "c"),
    ],
)
def test_next_revision(code: str, after: str) -> None:
    assert rv.next_revision(code) == after


def test_fingerprints_ignore_handles_and_order() -> None:
    a, b = _sheet(), _sheet()
    keys_a = sorted(k for k, _ in rv.fingerprints(list(a.msp), a.scale))
    keys_b = sorted(k for k, _ in rv.fingerprints(reversed(list(b.msp)), b.scale))
    assert keys_a == keys_b


def test_content_index_is_the_drawing_area_only() -> None:
    sheet = _sheet()
    content = rv.content_index(sheet)
    assert len(content) == 2  # the line and the circle; not the frame or the title block
    assert all(rv._in_area(sheet, e) for _, e in content)


def test_user_edits_are_carried_to_the_new_sheet(tmp_path: Path) -> None:
    old = _sheet()
    old.finish()
    index = rv.full_index(old)
    # the engineer adds a note on their own layer and a line on an S- layer
    old.doc.layers.add("MY-NOTES")
    old.msp.add_text("SEE ARCH. DWG A-201", dxfattribs={"layer": "MY-NOTES"}).set_placement(
        (5000, 5000)
    )
    old.msp.add_line((1000, 1000), (2000, 1500), dxfattribs={"layer": "S-TEXT"})
    path = tmp_path / "S-101.dxf"
    old.doc.saveas(path)
    new = _sheet(extra=True)
    new.finish()
    carried = rv.carry_edits(new, path, index)
    assert carried.count == 2 and not carried.resaved
    texts = [e.dxf.text for e in new.msp.query("TEXT[layer=='MY-NOTES']")]
    assert texts == ["SEE ARCH. DWG A-201"]
    assert "MY-NOTES" in new.doc.layers
    assert "2 drawing object(s)" in (carried.note("S-101") or "")


def test_without_an_index_only_other_layers_are_kept(tmp_path: Path) -> None:
    old = _sheet()
    old.finish()
    old.doc.layers.add("MINE")
    old.msp.add_line((0, 0), (10, 10), dxfattribs={"layer": "MINE"})
    path = tmp_path / "old.dxf"
    old.doc.saveas(path)
    entities, resaved = rv.user_entities(ezdxf.readfile(path), None, old.scale)
    assert [e.dxf.layer for e in entities] == ["MINE"] and not resaved


def test_a_resaved_file_keeps_other_layers_only(tmp_path: Path) -> None:
    old = _sheet()
    old.finish()
    index = rv.full_index(old)
    # a CAD program that moved everything by 1 mm on paper: nothing of SAEngine's is known
    for e in old.msp:
        if e.dxftype() in ("LINE", "CIRCLE", "TEXT", "LWPOLYLINE"):
            e.translate(100, 100, 0)
    old.doc.layers.add("MINE")
    old.msp.add_line((0, 0), (10, 10), dxfattribs={"layer": "MINE"})
    entities, resaved = rv.user_entities(old.doc, index, old.scale)
    assert resaved and [e.dxf.layer for e in entities] == ["MINE"]


def test_clouds_around_changes() -> None:
    old = _sheet()
    new = _sheet(extra=True)
    boxes, throughout = rv.clouds_for(new, rv.content_index(new), rv.content_index(old))
    assert len(boxes) == 1 and not throughout
    x0, _y0, _, _ = new.area
    b = boxes[0]
    # around the added beam line (paper x0+150..x0+190 at y0+120), with the cloud's margin
    assert b[0] == pytest.approx(x0 + 150 - rv.CLOUD_MARGIN, abs=0.2)
    assert b[2] == pytest.approx(x0 + 190 + rv.CLOUD_MARGIN, abs=0.2)
    rv.draw_cloud(new, b, "B")
    assert len(new.msp.query(f"LWPOLYLINE[layer=='{rv.CLOUD_LAYER}']")) == 2  # cloud, triangle
    assert "B" in [t.dxf.text for t in new.msp.query(f"TEXT[layer=='{rv.CLOUD_LAYER}']")]


def test_unchanged_sheet_has_no_clouds_and_a_new_one_is_throughout() -> None:
    old = _sheet()
    assert rv.clouds_for(old, rv.content_index(old), rv.content_index(_sheet())) == ([], False)
    _, throughout = rv.clouds_for(old, rv.content_index(old), [])
    assert throughout


def test_merge_boxes_and_cloud_points() -> None:
    merged = rv.merge_boxes([(0, 0, 10, 10), (12, 0, 20, 10), (100, 100, 110, 110)], gap=6)
    assert sorted(merged) == [(0, 0, 20, 10), (100, 100, 110, 110)]
    points = rv.cloud_points((0, 0, 60, 30), arc=6)
    assert len(points) == 30  # 10 + 5 + 10 + 5 arcs
    assert all(b > 0 for _, _, b in points)  # outward arcs, counter-clockwise


def test_register_round_trip_and_rows(tmp_path: Path) -> None:
    register = rv.Register()
    first = rv.new_issue(register, None, "2026-11-01", "First issue", "AB", "For approval")
    assert first.code == "0"
    first.sheets = [rv.IssuedSheet("S-101", "Plan", "new"), rv.IssuedSheet("S-102", "Old", "new")]
    first.folder = "Issued/0 2026-11-01"
    register.issues.append(first)
    register.save(tmp_path)
    loaded = rv.Register.load(tmp_path)
    assert loaded.issues[0].to_json() == first.to_json()
    assert loaded.pending_code() == "1"
    with pytest.raises(rv.IssueError):
        rv.new_issue(loaded, "0")
    second = rv.new_issue(loaded, None, "2026-12-01", "Beams revised")
    second.sheets = [rv.IssuedSheet("S-101", "Plan", "revised", 2)]
    loaded.issues.append(second)
    head, rows = rv.register_rows(loaded, [("S-101", "Plan"), ("S-103", "New")])
    assert head == ["Sheet No.", "Title", "0 (2026-11-01)", "1 (2026-12-01)", "Current"]
    assert rows[0] == ["S-101", "Plan", "0", "1", "1"]
    assert rows[1] == ["S-103", "New", "", "", "-"]
    assert rows[2] == ["S-102", "Old (withdrawn)", "0", "", "0"]
    assert [r.rev for r in (i.revision() for i in loaded.issues_of("S-101"))] == ["0", "1"]
    assert "Beams revised" in rv.register_csv(loaded, [("S-101", "Plan")])


def test_reviser_sets_the_sheets_revisions(tmp_path: Path) -> None:
    register = rv.Register()
    issue = rv.new_issue(register, "A", "2026-11-01", "For construction")
    reviser = rv.Reviser(tmp_path, TitleInfo(project="P"), register, issue)
    sheet = _sheet()
    reviser(sheet)
    sheet.finish()
    assert sheet.info.revision == "A" and sheet.info.revisions[-1].description == "For construction"
    state = reviser.states["S-101"]
    assert state.issued and state.changed and state.last is None


def test_write_dwg_without_the_writer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(dwg.ENV_VAR, str(tmp_path / "nowhere"))
    monkeypatch.setattr(dwg.sys, "executable", str(tmp_path / "python" / "python.exe"))
    monkeypatch.setattr(dwg.shutil, "which", lambda name: None)
    sheet = _sheet()
    sheet.finish()
    dxf = tmp_path / "S-101.dxf"
    sheet.doc.saveas(dxf)
    assert dwg.find_writer() is None
    with pytest.raises(dwg.WriterMissing, match="dxf2dwg"):
        dwg.write_dwg(dxf, tmp_path / "S-101.dwg")


def test_the_writer_is_found_beside_the_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "libredwg"
    folder.mkdir()
    (folder / dwg.EXE).write_bytes(b"")
    (folder / dwg.WRITER).write_bytes(b"")
    monkeypatch.setenv(dwg.ENV_VAR, str(folder / dwg.EXE))
    assert dwg.find_writer() == folder / dwg.WRITER
    assert dwg.find_converter() == folder / dwg.EXE

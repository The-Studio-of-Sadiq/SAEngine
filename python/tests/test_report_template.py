"""The configurable design report: report templates, the shared document and the Word file."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from test_report import project  # noqa: F401 - the module fixture of the report tests

from saengine.library.report_template import (
    SECTIONS,
    MemberSelection,
    ReportSection,
    ReportTemplate,
    list_templates,
    load_template,
    save_template,
    summary_report_template,
)
from saengine.report import build_report, report_data
from saengine.report.document import register_section, report_document
from saengine.report.word import render_docx


def _data() -> dict:
    """Report data with just enough of every chapter for the document builder."""
    rows = [
        ["C1", "C40", "Axial", "10", "20", "kN", "0.500", "1.2D", "OK"],
        ["C2", "C40", "Axial", "30", "20", "kN", "1.500", "1.2D", "FAIL"],
        ["C3", "C40", "Axial", "18", "20", "kN", "0.900", "1.2D", "OK"],
    ]
    detail = {
        "title": "C2 (column, type C40): utilisation 1.500, FAIL",
        "ok": False,
        "rows": [["Axial", "30", "20", "kN", "1.500", "1.2D", "FAIL", ""]],
        "fails": [True],
    }
    return {
        "meta": {
            "title": "Structural Design Report",
            "project": "P",
            "details": [],
            "titleBlock": [["Firm", "F"]],
            "code": "BNBC 2020",
            "date": "31 October 2026",
            "isoDate": "2026-10-31",
            "version": "9.9.9",
            "units": "Units: SI.",
        },
        "status": {"state": "fail", "headline": "DESIGN FAILS"},
        "warnings": [],
        "basis": {"materials": [], "cases": []},
        "soil": {"available": False},
        "foundations": {"available": False, "message": "No substructure.", "limits": []},
        "model": {"rows": [], "derived": [], "run": [], "runWarnings": []},
        "results": {
            "modal": None,
            "reactions": [],
            "displacements": [],
            "notes": [],
            "seismicDesign": {"available": False},
            "secondOrder": {"stiffness": "cracked sections", "pDelta": False},
        },
        "design": {
            "available": True,
            "code": "BNBC 2020",
            "summary": [["Elements checked", "3"]],
            "failed": 1,
            "failedText": "1 column",
            "tables": [
                {
                    "kind": "column",
                    "title": "Columns",
                    "count": 3,
                    "failed": 1,
                    "rows": rows,
                    "fails": [False, True, False],
                    "storeys": ["L1", "L1", "L2"],
                }
            ],
            "required": {"available": False},
            "skipped": [],
            "notDesigned": {},
            "stability": [],
            "slenderness": [],
            "method": ["ACI 318-19"],
            "combinations": ["1.2D"],
            "details": [{**detail, "id": "C2", "kind": "column", "storey": "L1"}],
            "appendix": {"scope": "governing", "count": 1, "of": 3},
        },
        "mep": {"available": False, "problem": ""},
        "plumbing": {"available": False, "problem": ""},
        "hvac": {"available": False, "problem": ""},
        "electrical": {"available": False, "problem": ""},
        "fire": {"available": False, "problem": ""},
        "boq": {"status": "ok", "groups": []},
        "limitations": {k: [] for k in ("design", "boq", "soil", "foundations", "model", "run")},
    }


def _blocks(document: dict, section: str) -> list[dict]:
    return next(s for s in document["sections"] if s["id"] == section)["blocks"]


def test_default_template_prints_every_section_in_order() -> None:
    document = report_document(_data())
    ids = [s["id"] for s in document["sections"]]
    # Sections without content (soil, MEP, worksheets) are skipped; the appendix is last.
    assert ids == ["basis", "foundations", "model", "results", "design", "boq", "limitations",
                   "appendix"]  # fmt: skip
    assert document["sections"][-1]["landscape"]
    assert document["letterhead"]["organisation"] == "F"  # the drawings' firm by default


def test_template_chooses_order_titles_and_sections() -> None:
    template = ReportTemplate(
        sections=[
            ReportSection(id="design", title="Members"),
            ReportSection(id="basis"),
            ReportSection(id="boq", include=False),
        ]
    )
    document = report_document(_data(), template)
    assert [(s["id"], s["title"]) for s in document["sections"]] == [
        ("design", "Members"),
        ("basis", "Design basis"),
    ]


def test_summary_detail_keeps_failing_and_governing_members_only() -> None:
    data = _data()
    full = _blocks(report_document(data), "design")
    summary = report_document(data, summary_report_template())
    blocks = _blocks(summary, "design")
    table = next(b for b in blocks if b["t"] == "table" and b["head"][0] == "Element")
    assert [r[0] for r in table["rows"]] == ["C2"]  # C2 fails and governs
    assert "appendix" not in [s["id"] for s in summary["sections"]]
    # Calculations (the method) are left out at summary detail, never the results.
    assert any(b["t"] == "bullets" for b in full)
    assert not any(b["t"] == "bullets" and b["items"] == ["ACI 318-19"] for b in blocks)
    assert not any("full" in b for b in blocks)


def test_member_selection_filters_tables_and_appendix() -> None:
    template = ReportTemplate(members=MemberSelection(storeys=["L2"]))
    document = report_document(_data(), template)
    table = next(
        b for b in _blocks(document, "design") if b["t"] == "table" and b["head"][0] == "Element"
    )
    assert [r[0] for r in table["rows"]] == ["C3"]
    # C2 is on L1: the appendix has nothing left to print.
    assert "appendix" not in [s["id"] for s in document["sections"]]
    only_failing = ReportTemplate(members=MemberSelection(failingOnly=True))
    table = next(
        b
        for b in _blocks(report_document(_data(), only_failing), "design")
        if b["t"] == "table" and b["head"][0] == "Element"
    )
    assert table["bad"] == [True]


def test_worksheets_hook_prints_registered_blocks() -> None:
    data = {**_data(), "worksheets": [{"title": "Beam B1", "blocks": [{"t": "p", "text": "x"}]}]}
    document = report_document(data)
    assert _blocks(document, "worksheets")[0] == {"t": "h", "level": 2, "text": "Beam B1"}
    with pytest.raises(ValueError):
        register_section("not-a-section")


def test_templates_load_save_and_list(tmp_path: Path) -> None:
    template, problems = load_template(tmp_path, "summary")
    assert template.detail == "summary" and problems == []
    template, problems = load_template(tmp_path, "missing")
    assert template.id == "default" and "missing" in problems[0]
    own = ReportTemplate(id="client", name="Client", sections=[ReportSection(id="design")])
    path = save_template(tmp_path, own)
    assert path == tmp_path / "11 Exports" / "report-templates" / "client.json"
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == "saengine.reportTemplate/1"
    assert load_template(tmp_path, "client")[0] == own
    assert {t["id"] for t in list_templates(tmp_path)} == {"default", "summary", "client"}
    path.write_text("{", encoding="utf-8")
    template, problems = load_template(tmp_path, "client")
    assert template.id == "default" and "could not be read" in problems[0]


def test_every_section_has_a_builder() -> None:
    from saengine.report import document

    assert set(document._BUILDERS) == set(SECTIONS)


def test_word_file_draws_the_document() -> None:
    content, warnings = render_docx(report_document(_data()))
    assert warnings == []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "DESIGN FAILS" in xml and "Member design" in xml and "TOC" in xml
    assert 'w:orient="landscape"' in xml  # the appendix
    assert "F9D9D6" in xml  # the failing row is highlighted


def test_build_report_writes_word_and_follows_the_settings(project: Path) -> None:  # noqa: F811
    result = build_report(project, version="9.9.9", format="docx")
    assert "problems" not in result, result
    assert Path(result["path"]) == project / "11 Exports" / "report.docx"
    assert result["format"] == "docx" and result["template"] == "default"
    with zipfile.ZipFile(result["path"]) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    # User text is printed literally, as in the PDF.
    assert "Bay #1 $x$ *bold* _it_ @ref &lt;lbl&gt; [b]" in xml

    out = project / "11 Exports" / "summary.pdf"
    summary = build_report(project, out, version="9.9.9", template="summary")
    assert summary["template"] == "summary" and summary["pages"] >= 3
    full = report_data(project)
    assert full["design"]["tables"][0]["storeys"]  # the selection's storeys reach the data
    assert build_report(project, format="odt")["problems"]

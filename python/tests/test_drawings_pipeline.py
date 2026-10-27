"""The structural drawings as the app and the command line make them
(``saengine.pipeline.drawings``): the drawing settings, the files of ``11 Exports/Drawings`` and
their record, staleness, a partial generation, the RPC handlers, the ``export --format
drawings`` command, Run All's drawings step and the bill of quantities' reconciliation with the
bar bending schedule. Synthetic data only: the Sample Frame project."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from saengine.pipeline import drawings as d

SAMPLE = (
    Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"
)
SETTINGS = "02 Project Settings/project-settings.json"


def _settings(root: Path, **drawings: object) -> None:
    path = root / SETTINGS
    data = json.loads(path.read_text(encoding="utf-8"))
    data["drawings"] = drawings
    path.write_text(json.dumps(data, indent="\t"), encoding="utf-8")


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict]:
    """The sample with its drawings generated once (A3, a title block of its own)."""
    root = tmp_path_factory.mktemp("drawings") / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    _settings(
        root,
        firm="Example Consulting Engineers",
        checkedBy="QC",
        revisions=[{"code": "0", "date": "2026-10-01"}, {"code": "A", "description": "beams"}],
    )
    steps: list[str] = []
    answer = d.generate(root, size="A3", progress=lambda step, *_: steps.append(step))
    assert steps == [s for s, _ in d.STEPS]
    return root, answer


def _copy(generated: tuple[Path, dict], tmp_path: Path) -> Path:
    target = tmp_path / "Sample Frame"
    shutil.copytree(generated[0], target)
    return target


def test_drawing_settings_and_the_title_block():
    from saengine.library.settings import Drawings, ProjectSettings

    defaults = Drawings()
    assert (defaults.sheetSize, defaults.planScale, defaults.detailScale) == ("A1", 100, 25)
    assert defaults.boqReinforcement == "measured" and defaults.developmentLength == "simplified"
    text = (SAMPLE / SETTINGS).read_text(encoding="utf-8")
    data = json.loads(text)
    data["project"].update(number="P-17", engineer="A. Engineer")
    data["drawings"] = {"checkedBy": "QC", "revisions": [{"code": "0"}, {"code": "B"}]}
    ProjectSettings.model_validate(data)
    settings, title = d.drawing_settings(json.dumps(data))
    assert settings["sheetSize"] == "A1" and settings["planScale"] == 100
    # The engineer and the number fall back to Project's; the revision is the last one.
    assert title["engineer"] == "A. Engineer" and title["number"] == "P-17"
    assert title["checked"] == "QC" and title["revision"] == "B" and len(title["revisions"]) == 2
    data["drawings"]["planScale"] = 90
    with pytest.raises(ValueError):
        ProjectSettings.model_validate(data)


def test_generate_writes_the_set_and_its_record(generated: tuple[Path, dict]):
    root, answer = generated
    folder = root / d.FOLDER
    numbers = [s["number"] for s in answer["sheets"]]
    assert numbers[0] == "S-101" and len(numbers) >= 10
    assert all(Path(s["dxf"]).is_file() and Path(s["png"]).is_file() for s in answer["sheets"])
    assert [s["pdfPage"] for s in answer["sheets"]] == list(range(1, len(numbers) + 1))
    assert {s["size"] for s in answer["sheets"]} == {"A3"} and answer["size"] == "A3"
    assert Path(answer["pdf"]) == folder / "drawings.pdf"
    assert (folder / "drawings.pdf").read_bytes().startswith(b"%PDF")
    assert (folder / "bbs.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    assert not answer["stale"] and not any(s["stale"] for s in answer["sheets"])
    assert isinstance(answer["generatedAt"], int)
    assert answer["bbs"]["total"] > 0 and answer["bbs"]["rows"] > 0
    # The bill of quantities is in the sample: the schedule is reconciled per bar size.
    assert {r["dia"] for r in answer["reconciliation"]} >= {10.0, 16.0}
    assert any(n.startswith("Bar bending schedule against 10 BOQ: Ø10") for n in answer["notes"])
    # The sample's failing detailing checks (C1's dowels, S2's top bars into W1) are problems
    # to resolve before issue, and the general notes sheet says so.
    errors = [p["message"] for p in answer["problems"] if p["severity"] == "error"]
    assert any(e.startswith("C1: Column bars into foundation") for e in errors)
    assert any(e.startswith("S2: Top X bars") and "not met" in e for e in errors)
    assert all(p["severity"] in ("error", "warning") for p in answer["problems"])
    record = json.loads((folder / d.RECORD).read_text(encoding="utf-8"))
    assert record["schema"] == d.SCHEMA_ID and record["marks"]
    assert set(record["source"]) == {"settings", "materials", "objects", "floorPlan", "bim",
                                     "substructure", "results"}  # fmt: skip
    assert record["settings"]["firm"] == "Example Consulting Engineers"
    # The title block of the sheets carries the drawing settings.
    dxf = Path(answer["sheets"][0]["dxf"]).read_text(encoding="utf-8", errors="replace")
    assert "EXAMPLE CONSULTING ENGINEERS" in dxf.upper() and "QC" in dxf
    assert "NOT FOR CONSTRUCTION until these are resolved" in dxf
    assert d.list_drawings(root) == answer


def test_a_change_makes_the_sheets_stale_and_some_can_be_drawn_again(
    generated: tuple[Path, dict], tmp_path: Path
):
    root = _copy(generated, tmp_path)
    bim = root / "06 BIM/bim.json"
    bim.write_text(bim.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    listed = d.list_drawings(root)
    assert listed["stale"] and listed["changed"] == ["Building Model"]
    assert listed["staleReason"] == "changed since: Building Model"
    assert all(s["stale"] for s in listed["sheets"])
    answer = d.generate(root, sheets=["S-103"], size="A3")
    stale = {s["number"]: s["stale"] for s in answer["sheets"]}
    assert stale["S-103"] is False and stale["S-101"] is True
    assert answer["pdfStale"] and any("has the earlier pages" in n for n in answer["notes"])
    # A sheet's files gone: it is listed out of date, without them.
    Path(answer["sheets"][0]["dxf"]).unlink()
    listed = d.list_drawings(root)
    assert listed["sheets"][0]["dxf"] is None and listed["sheets"][0]["stale"]
    assert any("are missing" in n for n in listed["notes"])


def test_the_rpc_handlers(tmp_path: Path):
    from saengine.rpc import handlers

    assert handlers.drawings_list(str(tmp_path)) == {
        "sheets": [], "stale": False, "notes": [], "problems": []
    }  # fmt: skip
    answer = handlers.drawings_generate(str(tmp_path))
    assert answer["sheets"] == [] and "building model (06 BIM)" in answer["problems"][0]
    assert handlers.drawings_progress(str(tmp_path)) == {"running": False}
    # One generation per project at a time.
    with d._GUARD:
        d._RUNNING[d._key(tmp_path)] = {"step": "sheets", "index": 4, "count": 5,
                                        "message": "drawing the sheets", "started": 0.0}  # fmt: skip
    try:
        assert handlers.drawings_progress(str(tmp_path))["step"] == "sheets"
        assert "already" in handlers.drawings_generate(str(tmp_path))["problems"][0]
    finally:
        d._RUNNING.clear()
    answer = handlers.drawings_generate(str(SAMPLE), size="A0")
    assert answer["problems"] == ["Sheet size 'A0': A1, A2 or A3."]


def test_export_drawings_from_the_command_line(
    capsys: pytest.CaptureFixture[str], generated: tuple[Path, dict], tmp_path: Path
):
    from saengine.cli.main import EXIT_OK, main

    root = _copy(generated, tmp_path)
    out = tmp_path / "issued"
    code = main(["export", str(root), "--format", "drawings", "--size", "A2", "--out", str(out),
                 "--json"])  # fmt: skip
    document = json.loads(capsys.readouterr().out)
    assert code == EXIT_OK and document["format"] == "drawings"
    files = {Path(f).relative_to(out).as_posix() for f in document["files"]}
    assert {"drawings.pdf", "bbs.csv", "previews/S-101.png"} <= files
    assert any(f.startswith("S-101 ") and f.endswith(".dxf") for f in files)
    assert d.list_drawings(root)["size"] == "A2"


def test_run_all_keeps_a_generated_set_current(generated: tuple[Path, dict], tmp_path: Path):
    from saengine.pipeline.project import open_project
    from saengine.pipeline.run_all import STEP_IDS, StepResult, _drawings

    assert STEP_IDS[-1] == "drawings"
    fresh = tmp_path / "fresh"
    shutil.copytree(SAMPLE, fresh)
    step = StepResult("drawings")
    _drawings(open_project(fresh), step, None, asked=False)
    assert step.status == "skipped" and "not generated yet" in step.message
    root = _copy(generated, tmp_path)
    step = StepResult("drawings")
    _drawings(open_project(root), step, None, asked=False)
    assert step.status == "skipped" and step.message == "drawings up to date"


def test_the_bill_reconciles_or_takes_the_bar_bending_schedule(tmp_path: Path):
    from saengine.boq.quantities import compute_boq

    def texts(root: Path) -> list[str | None]:
        def read(relative: str) -> str | None:
            path = root / relative
            return path.read_text(encoding="utf-8") if path.exists() else None

        return [read("06 BIM/bim.json"), read("04 Objects/objects.json"),
                read("03 Materials/materials.json"), read("09 Substructure/substructure.json"),
                read(SETTINGS), read("07 MEP/mep.json"), str(root)]  # fmt: skip

    def steel(document: dict) -> dict[float, float]:
        return {i["diameter"]: i["quantity"] for i in document["items"]
                if i["group"] == "reinforcement"}  # fmt: skip

    root = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    measured = compute_boq(*texts(root))
    note = next(n for n in measured["notes"] if n.startswith("Reinforcement against the bar"))
    assert "Ø16" in note and "Not detailed in the drawings: M1." in note
    _settings(root, boqReinforcement="bbs")
    taken = compute_boq(*texts(root))
    from saengine.drawings import bbs
    from saengine.drawings.detailing import detailing_model

    schedule = bbs.bar_schedule(detailing_model(root))
    # Every detailed element takes the schedule's bars; M1 (an inclined member) keeps the bill's.
    m1 = {
        i["diameter"]: sum(e["quantity"] for e in i["breakdown"] if e["element"] == "M1")
        for i in measured["items"]
        if i["group"] == "reinforcement"
    }
    for dia, mass in schedule.by_diameter.items():
        assert steel(taken)[dia] == pytest.approx(mass + m1.get(dia, 0.0), abs=0.01)
    assert any(n.endswith("not detailed in the drawings: M1.") for n in taken["notes"])
    assert not any(n.startswith("Reinforcement against the bar") for n in taken["notes"])
    beams = next(i for i in taken["items"] if i["group"] == "reinforcement" and i["diameter"] == 16)
    elements = {e["element"] for e in beams["breakdown"]}
    assert {"B1", "B2"} <= elements and "B1+B2" not in elements
    codes = [i["code"] for i in taken["items"] if i["group"] == "reinforcement"]
    assert codes == [f"R.{n:02d}" for n in range(1, len(codes) + 1)]


def test_edge_top_bars_of_two_panels_of_one_type_are_both_drawn():
    """S1 and S2 (one slab type) each have their S1-TY1 edge bars over the beams on grids 1 and
    2: four lines on the plan, not the two of the first panel (found on the sample's sheet)."""
    from saengine.drawings.sheets import drawing_set

    data = drawing_set(SAMPLE)
    lines = [(s.id, b) for s in data.slabs for b in s.top_bars if b.mesh.mark == "S1-TY1"]
    assert sorted(s for s, _ in lines) == ["S1", "S1", "S2", "S2"]


def test_some_sheets_at_another_size_draw_the_whole_set(
    generated: tuple[Path, dict], tmp_path: Path
):
    """The page sends the ticked sheets with the size picker's value: at another size the set
    is drawn whole (one layout), not A3 sheets numbered into an A1 set."""
    root = _copy(generated, tmp_path)
    before = d.list_drawings(root)
    answer = d.generate(root, sheets=["S-103"], size="A1")
    assert answer["size"] == "A1" and {s["size"] for s in answer["sheets"]} == {"A1"}
    assert not answer["stale"] and not answer["pdfStale"]
    assert len(answer["sheets"]) < len(before["sheets"])  # A1 fits more on a sheet
    titles = [s["title"] for s in answer["sheets"]]
    assert len(set(titles)) == len(titles) and any("Bar bending schedule" in t for t in titles)
    assert any("sheet size changed from A3 to A1" in n for n in answer["notes"])
    folder = root / d.FOLDER
    dxfs = sorted(p.name for p in folder.glob("*.dxf"))
    assert dxfs == sorted(Path(s["dxf"]).name for s in answer["sheets"])
    # The same size: only the sheet asked for.
    again = d.generate(root, sheets=["S-103"], size="A1")
    assert any(n.startswith("Drawn again: S-103.") for n in again["notes"])
    assert not again["pdfStale"]


def test_malformed_settings_still_draw_with_the_defaults(tmp_path: Path):
    settings, title = d.drawing_settings('{"project": {"name": "x"}, "drawings": {')
    assert settings["sheetSize"] == "A1" and title["revision"] == "0"
    settings, _ = d.drawing_settings('{"project": 3, "drawings": {"firm": "F", "planScale": 90}}')
    assert settings["firm"] is None  # an invalid drawings section: the defaults
    settings, title = d.drawing_settings('{"project": {}, "drawings": {"firm": "F"}}')
    assert title["firm"] == "F"


def test_the_design_checks_are_kept_for_the_drawings(tmp_path: Path, monkeypatch):
    """The design checks are made once per analysis run (kept beside the results), the
    response spectrum design's summary rewritten by every design does not make them stale,
    and missing required steel is said."""
    from saengine.pipeline import design_mode

    root = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    out = root / "08 FEM/model.results"
    (out / "rs-design").mkdir(parents=True)
    (out / "manifest.json").write_text("{}", encoding="utf-8")
    (out / "case_1.results.h5").write_bytes(b"results")
    model = root / d.FEM_MODEL
    stamp = design_mode.inputs_stamp(out, model)
    (out / "rs-design/seismic-design.json").write_text('{"again": 1}', encoding="utf-8")
    assert design_mode.inputs_stamp(out, model) == stamp
    calls: list[str] = []

    def gather(out_dir, project_path, substructure=True):
        # The sample's object types all have bars: the checks come from the one gathering
        # shared with the design proposal and the required steel (PR #30).
        calls.append(str(out_dir))
        report = {"elements": [{"id": "B1", "ok": False, "checks": []},
                               {"id": "B2", "ok": True, "checks": []}],
                  "summary": {"joints": {"failed": 1}}}  # fmt: skip
        return SimpleNamespace(report=report, assumed=set())

    monkeypatch.setattr(design_mode, "_ensure_seismic_design", lambda *_: None)
    monkeypatch.setattr("saengine.design.required.gather", gather)
    # The stub's gathering is not left in the process's memo for the next tests.
    monkeypatch.setattr(design_mode, "_GATHERED", None)
    monkeypatch.setattr(design_mode, "_REPORT", None)
    report, required, notes = d._design_inputs(root)
    again, _, _ = d._design_inputs(root)
    assert len(calls) == 1 and again == report and (out / design_mode.REPORT_FILE).is_file()
    assert required is None and d.REQUIRED_MISSING in notes
    design_mode.keep(out, design_mode.inputs_stamp(out, model), {"elements": []})
    assert d._design_inputs(root)[1] == {"elements": []}
    assert d.kept_detailing_inputs(root)["design_report"] == report
    assert d.check_problems({"elements": []}, report) == [
        "Design checks: 1 of 2 members fail (B1): the sheets show the bars entered in 04 Objects.",
        "Design checks: 1 beam-column joint(s) fail.",
    ]
    # A new analysis (a result file written again): the kept checks are stale.
    (out / "case_1.results.h5").write_bytes(b"results, again")
    d._design_inputs(root)
    assert len(calls) == 2


def test_the_bill_takes_the_marks_of_the_drawings(generated: tuple[Path, dict], tmp_path: Path):
    """With "reinforcement from the BBS", the bill details the bars with the drawings' kept
    marks: after a model edit its marks are those of the sheets and bbs.csv."""
    import csv

    from saengine.boq.quantities import compute_boq

    root = _copy(generated, tmp_path)
    _settings(root, boqReinforcement="bbs")
    bim = root / "06 BIM/bim.json"
    data = json.loads(bim.read_text(encoding="utf-8"))
    data["elements"] = [e for e in data["elements"] if e.get("id") != "S1"]
    bim.write_text(json.dumps(data, indent="	"), encoding="utf-8")
    d.generate(root)
    with (root / d.FOLDER / d.BBS_CSV).open(encoding="utf-8-sig", newline="") as f:
        sheets = {r["Bar mark"] for r in csv.DictReader(f) if r["Member"] == "S2"}

    def read(relative: str) -> str | None:
        path = root / relative
        return path.read_text(encoding="utf-8") if path.exists() else None

    bill = compute_boq(read("06 BIM/bim.json"), read("04 Objects/objects.json"),
                       read("03 Materials/materials.json"), read("09 Substructure/substructure.json"),
                       read(SETTINGS), read("07 MEP/mep.json"), str(root))  # fmt: skip
    marks = {
        e["detail"].removeprefix("bar mark ").removesuffix(" (bar bending schedule)")
        for i in bill["items"]
        if i["group"] == "reinforcement"
        for e in i["breakdown"]
        if e["element"] == "S2" and "bar bending schedule" in (e.get("detail") or "")
    }
    assert sheets and marks == sheets

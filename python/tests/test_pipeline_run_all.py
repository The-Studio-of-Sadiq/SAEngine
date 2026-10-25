"""Run All on a copy of the sample through the command line, end to end (a few minutes: the
analysis, the tank designs and the report): the steps, the files the app writes, the summaries in
the app's format with current stamps, the part statuses, ``check`` and its exit code.

EnergyPlus is not needed: Run All never starts it (the HVAC loads are the estimate without a
cached run, as in the app)."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
from pathlib import Path

import pytest

from saengine.cli.main import EXIT_CHECKS, JSON_SCHEMA, main
from saengine.fem.derive import mep_stamp
from saengine.library.bim import source_stamp
from saengine.pipeline.project import open_project
from saengine.pipeline.status import part_statuses, recorded_sources

pytestmark = pytest.mark.slow

SAMPLE = (
    Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"
)
STEPS = ["derive", "analysis", "ssi", "design", "substructure", "mep", "boq", "report", "drawings"]


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict, str]:
    code = main([*argv, "--json"])
    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert document["schema"] == JSON_SCHEMA and document["exitCode"] == code
    return code, document, captured.err


@pytest.fixture(scope="module")
def ran(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, int, dict, str]:
    root = tmp_path_factory.mktemp("runall") / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    # capsys is function-scoped: the module's one run is captured by hand.
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["run-all", str(root), "--json"])
    return root, code, json.loads(out.getvalue()), err.getvalue()


def test_every_step_ran_and_wrote_the_apps_files(ran):
    root, code, document, progress = ran
    assert [(s["id"], s["status"]) for s in document["steps"]] == [
        (s, "skipped" if s in ("ssi", "drawings") else "ok") for s in STEPS
    ]
    # The sample's drawings were never generated: Run All leaves them to the engineer.
    assert document["steps"][-1]["message"].startswith("drawings not generated yet")
    assert document["ok"] and document["stoppedAt"] is None
    # The sample has failing members, a failing footing and failing plumbing and HVAC checks.
    assert code == EXIT_CHECKS
    assert {f["part"] for f in document["failures"]} == {"fem", "substructure", "mep"}
    assert "[1/9] analysis model" in progress and "[8/9] report" in progress
    for relative in (
        "08 FEM/model.osmodel",
        "08 FEM/model.results/manifest.json",
        "08 FEM/model.results/design-summary.json",
        "09 Substructure/substructure.results/summary.json",
        "07 MEP/mep.results/summary.json",
        "11 Exports/report.pdf",
    ):
        assert (root / relative).is_file(), relative
    assert document["summary"].startswith("Done: ") and "report written" in document["summary"]


def test_the_summaries_are_the_apps_with_current_stamps(ran):
    root, _, _, _ = ran
    design = (root / "08 FEM/model.results/design-summary.json").read_text(encoding="utf-8")
    assert design.startswith('{\n\t"checked": ') and design.endswith("}\n")
    assert list(json.loads(design)) == [
        "checked", "passed", "failed", "maxUtilisation", "governing", "computed"]  # fmt: skip
    foundations = json.loads(
        (root / "09 Substructure/substructure.results/summary.json").read_text(encoding="utf-8")
    )
    assert list(foundations) == ["foundations", "checked", "passed", "failed", "maxUtilisation",
                                 "governing", "computed", "source"]  # fmt: skip
    project = open_project(root)
    for part, stamp in foundations["source"].items():
        text = project.text(part)
        assert stamp == ("" if text is None else source_stamp(text)), part
    mep = json.loads((root / "07 MEP/mep.results/summary.json").read_text(encoding="utf-8"))
    assert list(mep) == ["equipment", "openings", "openingsFailed", "openingsPartial", "clashes",
                         "clashesOpen", "computed", "source", "plumbing", "hvac", "electrical",
                         "fire"]  # fmt: skip
    assert list(mep["plumbing"]) == ["risers", "tanks", "failed", "floorsLow", "source"]
    assert list(mep["hvac"]) == ["plant", "ducts", "cooling", "engine", "failed"]
    assert list(mep["electrical"]) == ["equipment", "risers", "demand", "downConductors", "failed"]
    # the sample's fire section: extinguishers only (Sec 5.7(i)), no water systems, nothing fails
    assert mep["fire"] == {"risers": 0, "pumps": 0, "tanks": 0, "required": ["extinguishers"],
                           "openingsToAdd": 0, "failed": 0}  # fmt: skip
    assert mep["hvac"]["engine"] == "estimate"
    assert mep["source"]["mep"] == source_stamp(project.text("mep"))
    model = json.loads(project.text("fem"))
    recorded = recorded_sources(model["meta"]["description"])
    assert recorded["mep"] == mep_stamp(project.text("mep"))
    assert recorded["bim"] == source_stamp(project.text("bim"))


def test_the_sidebar_shows_the_results_as_current(ran):
    root, _, document, _ = ran
    statuses = {s.part: s for s in part_statuses(open_project(root))}
    assert statuses["fem"].state == "failed" and statuses["fem"].text.endswith(" fail")
    assert statuses["substructure"].state == "failed"
    assert statuses["mep"].state == "failed"
    assert statuses["boq"].state == "done"
    # The report shows a failing design, so Exports is not "done" either (R4).
    assert statuses["exports"].state == "failed"
    assert [p["state"] for p in document["parts"]] == [
        s.state for s in part_statuses(open_project(root))
    ]


def test_check_exits_1_and_writes_no_deliverables(ran, capsys: pytest.CaptureFixture[str]):
    root, _, _, _ = ran
    report = root / "11 Exports" / "report.pdf"
    before = report.stat().st_mtime_ns
    bill = (root / "10 BOQ" / "boq.json").read_bytes()
    code, document, _ = _run(capsys, "check", str(root))
    assert code == EXIT_CHECKS
    assert [s["id"] for s in document["steps"]] == STEPS[:6]
    assert document["steps"][0]["status"] == "skipped"  # the model is up to date
    failures = {(f["part"], f["check"]) for f in document["failures"]}
    assert {("fem", "design"), ("substructure", "foundations")} <= failures
    assert all(f["count"] > 0 and f["message"] for f in document["failures"])
    assert report.stat().st_mtime_ns == before
    assert (root / "10 BOQ" / "boq.json").read_bytes() == bill


def test_a_planted_solver_in_the_project_does_not_run(ran, capsys: pytest.CaptureFixture[str]):
    """The solver runs with the project's 08 FEM as its working folder: a received project (or a
    .civil archive) carrying an ``opensees_studio`` package there must not replace the solver.
    Last in the module: it runs the analysis again in the shared project. Also: the project may
    come after ``--steps``."""
    root, _, _, _ = ran
    planted = root / "08 FEM" / "opensees_studio"
    planted.mkdir()
    marker = root.parent / "planted-code-ran.txt"
    (planted / "__init__.py").write_text("", encoding="utf-8")
    (planted / "run.py").write_text(
        f"import pathlib, sys\npathlib.Path({str(marker)!r}).write_text('ran')\nsys.exit(0)\n",
        encoding="utf-8",
    )
    code, document, _ = _run(capsys, "run-all", "--steps", "analysis", str(root))
    assert [(s["id"], s["status"]) for s in document["steps"]] == [("analysis", "ok")]
    assert not marker.exists()
    assert document["steps"][0]["counts"]["cases"] > 0
    assert (root / "08 FEM" / "model.results" / "manifest.json").is_file()
    assert code in (0, EXIT_CHECKS)

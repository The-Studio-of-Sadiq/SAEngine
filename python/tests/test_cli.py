"""The ``saengine`` command line: exit codes, the JSON documents, validate, status, the exports,
the .civil round trip and the versions. Run All itself is in ``test_pipeline_run_all.py``."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from saengine.cli.main import EXIT_CHECKS, EXIT_ERROR, EXIT_OK, EXIT_USAGE, JSON_SCHEMA, main

SAMPLE = (
    Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"
)


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    target = tmp_path / "projects" / "Sample Frame"
    shutil.copytree(SAMPLE, target)
    return target


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    """Runs the command with --json; its exit code and document."""
    code = main([*argv, "--json"])
    out = capsys.readouterr().out
    document = json.loads(out)
    assert document["schema"] == JSON_SCHEMA and document["exitCode"] == code
    return code, document


def test_version_and_usage(capsys: pytest.CaptureFixture[str], tmp_path: Path):
    assert main(["--version"]) == EXIT_OK
    assert capsys.readouterr().out.startswith("saengine ")
    assert main([]) == EXIT_USAGE
    assert main(["no-such-command"]) == EXIT_USAGE
    assert main(["run-all", str(tmp_path), "--steps", "nope"]) == EXIT_USAGE
    capsys.readouterr()
    code, document = run(capsys, "validate", str(tmp_path / "missing"))
    assert code == EXIT_USAGE and "does not exist" in document["error"]
    code, document = run(capsys, "status", str(tmp_path))
    assert code == EXIT_USAGE and "not a SAEngine project" in document["error"]


def test_python_dash_m_runs_the_command_line():
    done = subprocess.run([sys.executable, "-m", "saengine.cli", "--version"], capture_output=True,
                          text=True, check=False)  # fmt: skip
    assert done.returncode == 0 and done.stdout.startswith("saengine ")


def test_validate_the_sample_and_a_broken_project(capsys: pytest.CaptureFixture[str], sample: Path):
    code, document = run(capsys, "validate", str(sample))
    assert code == EXIT_OK and document["ok"] and document["errors"] == 0
    states = {p["part"]: p["state"] for p in document["parts"]}
    # The sample has a (synthetic) soil report since the site map: 1 Soil Report is filled in.
    assert states["soil"] == "ok" and states["fem"] == "missing"
    assert states["bim"] == states["floorPlan"] == states["mep"] == "ok"

    materials = sample / "03 Materials" / "materials.json"
    data = json.loads(materials.read_text(encoding="utf-8"))
    data["materials"].append(dict(data["materials"][0]))  # a duplicate id
    materials.write_text(json.dumps(data), encoding="utf-8")
    (sample / "07 MEP" / "mep.json").write_text("{ not json", encoding="utf-8")
    (sample / "02 Project Settings" / "project-settings.json").unlink()
    code, document = run(capsys, "validate", str(sample))
    assert code == EXIT_CHECKS and not document["ok"]
    parts = {p["part"]: p for p in document["parts"]}
    assert parts["materials"]["state"] == "problems"
    assert parts["mep"]["problems"][0]["message"].startswith("Invalid JSON")
    assert parts["settings"]["problems"][0]["message"].endswith("is missing")
    assert {p["severity"] for p in parts["materials"]["problems"]} == {"error"}


def test_status_of_the_sample(capsys: pytest.CaptureFixture[str], sample: Path):
    code, document = run(capsys, "status", str(sample / "Sample Frame.saengine"))
    assert code == EXIT_OK and document["project"]["name"] == "Sample Frame"
    states = {p["part"]: (p["state"], p["text"]) for p in document["parts"]}
    assert states["fem"] == ("notStarted", "not derived")
    # The sample keeps the default materials, which the status (as the workbench's since K2)
    # reads as defaults to review: that is the first open step, ahead of the analysis model.
    assert states["materials"] == ("defaults", "defaults") and document["next"] == "materials"
    # The sample's bill leaves its three tanks unmeasured (no current design): incomplete, not
    # "measured" (N-Q1 of usability walk 2).
    assert states["boq"] == ("inProgress", "incomplete")


def test_exports(capsys: pytest.CaptureFixture[str], sample: Path):
    exports = sample / "11 Exports"
    code, document = run(capsys, "export", str(sample), "--format", "csv")
    assert code == EXIT_OK and document["files"] == [str(exports / "boq.csv")]
    assert (exports / "boq.csv").read_bytes().startswith(b"Row,Code,Group,Description,")
    code, document = run(capsys, "export", str(sample), "--format", "ifc")
    ifc = (exports / "IFC" / "Sample Frame.ifc").read_text()
    assert code == EXIT_OK and ifc.startswith("ISO")
    # As the app's saengine.bim.ifc: the substructure's footing and the MEP coordination
    # elements (the shaft's slab opening, the DN100 drain opening) are in the IFC too.
    assert "IFCFOOTING('" in ifc and "'Isolated footing'" in ifc
    assert "'SH1.S2'" in ifc and "'DN100 drain'" in ifc
    assert ifc.count("IFCOPENINGELEMENT(") == 6
    code, document = run(capsys, "export", str(sample), "--format", "dxf")
    assert code == EXIT_OK and len(document["files"]) == 4
    import ezdxf

    plan = ezdxf.readfile(exports / "Floor Plan" / "L1 Level 1.dxf")
    assert {"S-GRID", "S-COLS", "S-BEAM"} <= {layer.dxf.name for layer in plan.layers}
    assert len(plan.modelspace().query("LWPOLYLINE[layer=='S-COLS']")) > 0
    # The status counts them as the sidebar does: no report yet.
    _, status = run(capsys, "status", str(sample))
    assert status["parts"][-1]["text"] == "6 files, no report"
    (sample / "10 BOQ" / "boq.json").write_text('{"schema": 1, "part": "boq"}', encoding="utf-8")
    code, document = run(capsys, "export", str(sample), "--format", "csv")
    assert code == EXIT_ERROR and "Measure the bill" in document["error"]


def test_civil_round_trip(capsys: pytest.CaptureFixture[str], sample: Path, tmp_path: Path):
    archive = tmp_path / "sample.civil"
    code, document = run(capsys, "export", str(sample), "--format", "civil", "--out", str(archive))
    assert code == EXIT_OK and archive.is_file() and document["files"] == [str(archive)]
    dest = tmp_path / "imported"
    code, document = run(capsys, "import", str(archive), str(dest))
    assert code == EXIT_OK
    root = Path(document["import"]["root"])
    assert root == dest / "Sample Frame"
    for path in SAMPLE.rglob("*"):
        if path.is_file():
            relative = path.relative_to(SAMPLE)
            assert (root / relative).read_bytes() == path.read_bytes(), relative
    code, document = run(capsys, "import", str(archive), str(dest))
    assert code == EXIT_ERROR  # the folder exists: refused unless --overwrite
    code, _ = run(capsys, "import", str(archive), str(dest), "--overwrite")
    assert code == EXIT_OK
    code, document = run(capsys, "import", str(tmp_path / "none.civil"), str(dest))
    assert code == EXIT_USAGE


def test_versions(capsys: pytest.CaptureFixture[str], sample: Path):
    author = "Test Engineer <test@example.com>"
    code, document = run(capsys, "versions", "save", str(sample), "-m", "First", "--author", author)
    assert code == EXIT_OK and document["result"]["version"]["number"] == 1
    code, document = run(capsys, "versions", "save", str(sample), "-m", "Again")
    assert code == EXIT_ERROR and "Nothing changed" in document["error"]
    settings = sample / "02 Project Settings" / "project-settings.json"
    settings.write_text(settings.read_text(encoding="utf-8").replace("\n", "\r\n"), "utf-8")
    materials = sample / "03 Materials" / "materials.json"
    data = json.loads(materials.read_text(encoding="utf-8"))
    data["materials"][0]["name"] = "Renamed"
    materials.write_text(json.dumps(data, indent="\t"), encoding="utf-8")
    code, document = run(capsys, "versions", "status", str(sample))
    assert code == EXIT_OK and "materials" in document["result"]["changedParts"]
    code, document = run(capsys, "versions", "diff", str(sample))
    assert code == EXIT_OK
    assert any(p["part"] == "materials" for p in document["result"]["parts"])
    run(capsys, "versions", "save", str(sample), "-m", "Renamed", "--author", author)
    code, document = run(capsys, "versions", "list", str(sample))
    assert [v["message"] for v in document["result"]["versions"]] == ["Renamed", "First"]
    first = document["result"]["versions"][1]["id"]
    code, document = run(capsys, "versions", "restore", str(sample), first, "--parts", "materials",
                         "--author", author)  # fmt: skip
    assert code == EXIT_OK
    assert json.loads(materials.read_text(encoding="utf-8"))["materials"][0]["name"] != "Renamed"
    code, document = run(capsys, "versions", "issue", str(sample), first, "Tender")
    assert code == EXIT_OK and document["result"]["tag"].startswith("issued/")


def test_versions_by_number(capsys: pytest.CaptureFixture[str], sample: Path):
    """The versions as ``list`` shows them: ``v1``, ``V1``, ``1``, with ``~N``."""
    author = "Test Engineer <test@example.com>"
    run(capsys, "versions", "save", str(sample), "-m", "First", "--author", author)
    materials = sample / "03 Materials" / "materials.json"
    original = materials.read_bytes()
    data = json.loads(original)
    data["materials"][0]["name"] = "Renamed"
    materials.write_text(json.dumps(data, indent="\t"), encoding="utf-8")
    run(capsys, "versions", "save", str(sample), "-m", "Renamed", "--author", author)
    code, document = run(capsys, "versions", "list", str(sample))
    first = document["result"]["versions"][1]
    assert first["number"] == 1
    for ref in ("v1", "V1", "1", "v2~1"):
        code, document = run(capsys, "versions", "diff", str(sample), ref, "v2")
        assert code == EXIT_OK, (ref, document)
        assert any(p["part"] == "materials" for p in document["result"]["parts"])
    code, document = run(capsys, "versions", "diff", str(sample), "v9")
    assert code == EXIT_ERROR and "v1 to v2" in document["error"]
    code, _ = run(capsys, "versions", "restore", str(sample), "v1", "--no-commit")
    assert code == EXIT_OK and materials.read_bytes() == original
    assert main(["versions", "issue", str(sample), "v1", "Tender"]) == EXIT_OK
    assert "Marked v1 issued" in capsys.readouterr().out
    code, document = run(capsys, "versions", "diff", str(sample), first["id"])  # a commit id
    assert code == EXIT_OK


@pytest.mark.parametrize("name", ["Tower: Phase 1", "Plot 12/A", "../escaped", 'a\\b"c'])
def test_civil_export_name_is_a_file_name(
    capsys: pytest.CaptureFixture[str], sample: Path, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, name: str,
):  # fmt: skip
    manifest = sample / "Sample Frame.saengine"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["name"] = name
    manifest.write_text(json.dumps(data, indent="\t"), encoding="utf-8")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    code, document = run(capsys, "export", str(sample), "--format", "civil")
    assert code == EXIT_OK, document
    written = Path(document["files"][0])
    assert written.parent == cwd and written.is_file() and written.suffix == ".civil"
    assert [p.name for p in cwd.iterdir()] == [written.name]
    assert not any(c in written.stem for c in '<>:"/\\|?*')
    assert not (tmp_path / "escaped.civil").exists()


def test_usage_errors_write_the_json_document(capsys: pytest.CaptureFixture[str], sample: Path):
    for argv, command in (
        (["run-all", "--json"], "run-all"),
        (["versions", "diff", "--json"], "versions diff"),
        (["export", str(sample), "--json"], "export"),  # --format is required
        (["--json", "no-such-command"], ""),
    ):
        code = main(argv)
        captured = capsys.readouterr()
        document = json.loads(captured.out)
        assert code == EXIT_USAGE and document["exitCode"] == EXIT_USAGE, argv
        assert document["schema"] == JSON_SCHEMA and document["command"] == command
        assert document["error"] and document["usage"].startswith("usage:")
        assert "error:" in captured.err


def test_steps_may_come_before_the_project(capsys: pytest.CaptureFixture[str], sample: Path):
    # The project after --steps is found (nargs="+" took it).
    code, document = run(capsys, "run-all", "--steps", "derive", "boq", str(sample))
    assert [s["id"] for s in document["steps"]] == ["derive", "boq"], document
    code, document = run(capsys, "run-all", "--steps", "derive,nope", str(sample))
    assert code == EXIT_USAGE and "nope" in document["error"]
    # A folder name with a comma is the project, kept whole, not split into steps.
    comma = sample.parent / "My Proj, A"
    sample.rename(comma)
    code, document = run(capsys, "run-all", "--steps", "derive", str(comma))
    assert [s["id"] for s in document["steps"]] == ["derive"], document
    code, document = run(capsys, "run-all", "--steps", "derive,boq", str(comma))
    assert [s["id"] for s in document["steps"]] == ["derive", "boq"], document


def test_verify_json_is_one_document(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The verification pack prints its table to stdout: with --json it must not get there."""
    import saengine.verification.run as pack

    def fake_main(argv: list[str]) -> int:
        out = Path(argv[argv.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        data = {"cases": [{"id": "D1", "pass": True}, {"id": "D2", "pass": False}],
                "summary": {"cases": 2, "passed": 1, "failed": 1}}  # fmt: skip
        (out / "verification.json").write_text(json.dumps(data), encoding="utf-8")
        print("Case  Quantity  Reference  SAEngine")
        print(f"wrote {out / 'verification.json'}")
        return 1

    monkeypatch.setattr(pack, "main", fake_main)
    folder = tmp_path / "verify"
    code = main(["verify", "--json", "--out", str(folder)])
    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert code == EXIT_CHECKS and document["exitCode"] == EXIT_CHECKS
    assert document["summary"]["failed"] == 1 and document["failedCases"] == ["D2"]
    assert document["files"] == [str((folder / "verification.json").resolve())]
    assert "Case  Quantity" in captured.err
    code = main(["verify", "--json", "-q", "--out", str(folder)])
    captured = capsys.readouterr()
    assert json.loads(captured.out)["command"] == "verify" and captured.err == ""
    assert main(["verify", "--out", str(folder)]) == EXIT_CHECKS
    assert "Case  Quantity" in capsys.readouterr().out  # without --json: as the pack prints


def test_text_output_goes_to_stdout(capsys: pytest.CaptureFixture[str], sample: Path):
    assert main(["status", str(sample)]) == EXIT_OK
    captured = capsys.readouterr()
    assert "8 FEM" in captured.out and "not derived" in captured.out and captured.err == ""

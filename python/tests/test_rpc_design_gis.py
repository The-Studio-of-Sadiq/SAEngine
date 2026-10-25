"""The integration of the design mode and the site map: the RPC methods over stdio, the kept
required steel (``saengine.pipeline.design_mode``), its report tables, and the sample project's
soil report on the map and in a GeoPackage."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from saengine.pipeline import design_mode
from saengine.rpc import handlers

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"


def _rpc(proc: subprocess.Popen[bytes], request_id: int, method: str, params: Any) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    data = body.encode("utf-8")
    assert proc.stdin and proc.stdout
    proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(data) + data)
    proc.stdin.flush()
    length = 0
    while True:
        line = proc.stdout.readline().decode("ascii").strip()
        if not line:
            break
        name, _, value = line.partition(":")
        if name.lower() == "content-length":
            length = int(value)
    return json.loads(proc.stdout.read(length))


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    root = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    return root


def test_rpc_methods_over_stdio(sample: Path) -> None:
    soil = (sample / "01 Soil Report" / "soil-report.json").read_text("utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "saengine.rpc"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        located = _rpc(proc, 1, "soil/location", {"soilText": soil})["result"]
        assert (located["site"]["lat"], located["site"]["lon"]) == (23.78, 90.4)
        assert [b["id"] for b in located["boreholes"]] == ["BH-1", "BH-2", "BH-3"]
        assert located["suggestion"]["town"] == "Dhaka"

        out = sample / "11 Exports" / "site.gpkg"
        exported = _rpc(
            proc, 2, "soil/gisExport",
            {"projectRoot": str(sample), "format": "gpkg", "outPath": str(out)},
        )["result"]  # fmt: skip
        assert exported["counts"]["boreholes"] == 3 and out.is_file()

        imported = _rpc(proc, 3, "soil/gisImport", {"path": str(out), "soilText": soil})["result"]
        assert json.loads(imported["soilText"])["boreholes"][0]["id"] == "BH-1"

        program = _rpc(proc, 4, "soil/qgisProgram", {})["result"]
        assert program is None or Path(program).is_file()  # QGIS is not bundled

        command = _rpc(
            proc,
            5,
            "soil/qgisCommand",
            {"program": r"C:\QGIS\bin\qgis.bat", "filePath": "a%b.gpkg"},
        )["result"]
        assert "problems" in command  # cmd.exe would expand the %: refused

        # A proposal with nothing to apply leaves the files as they are.
        objects = (sample / "04 Objects" / "objects.json").read_text("utf-8")
        applied = _rpc(
            proc, 6, "design/applyProposal",
            {"objectsText": objects, "bimText": None,
             "proposal": {"mode": "byType", "types": [], "newTypes": [], "reassign": [],
                          "foundations": []}},
        )["result"]  # fmt: skip
        assert json.loads(applied["objectsText"]) == json.loads(objects)
        assert applied["changes"] == []

        unknown = _rpc(
            proc, 7, "design/proposal",
            {"outDir": str(sample), "projectPath": str(sample / "08 FEM" / "model.osmodel"),
             "options": {"mode": "everything"}},
        )  # fmt: skip
        assert "error" in unknown
    finally:
        proc.kill()
        proc.wait()


def test_the_sample_geopackage_has_the_standard_structure(sample: Path) -> None:
    path = sample / "site.gpkg"
    out = handlers.gis_export(str(sample), "gpkg", str(path))
    assert out["counts"] == {"site": 1, "site_boundary": 1, "boreholes": 3, "building": 1}
    con = sqlite3.connect(path)
    try:
        assert con.execute("PRAGMA application_id").fetchone()[0] == 0x47504B47  # "GPKG"
        assert con.execute("PRAGMA user_version").fetchone()[0] == 10201
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        contents = dict(con.execute("SELECT table_name, srs_id FROM gpkg_contents"))
        assert contents == {
            "site": 4326,
            "site_boundary": 4326,
            "boreholes": 4326,
            "building": 4326,
        }
        assert con.execute("SELECT id FROM boreholes ORDER BY fid").fetchall() == [
            ("BH-1",), ("BH-2",), ("BH-3",),
        ]  # fmt: skip
    finally:
        con.close()


def test_the_sample_soil_report_has_increments_and_a_grain_size_test() -> None:
    report = json.loads((SAMPLE / "01 Soil Report" / "soil-report.json").read_text("utf-8"))
    bh1 = report["boreholes"][0]
    assert {"seat", "N1", "N2"} <= set(bh1["spt"][0]) and "N" not in bh1["spt"][0]
    assert sum(1 for s in bh1["samples"] if s.get("grainSize")) == 2
    assert report["site"]["lat"] and report["boreholes"][2]["position"] == "wgs84"
    computed = handlers.soil_report(json.dumps(report))
    assert computed["siteClass"]  # the report reads (no data-entry error rejects it)


def test_the_sample_soil_agrees_with_the_sample_design() -> None:
    # The sample's synthetic soil must not contradict the rest of the sample: no liquefiable
    # layer (no S2 flag) under the project's own amax, the site class the analysis was run
    # with (SD, entered in the settings), and a qa at the reference footing of each borehole
    # no lower than the 150 kPa override its footing F1 is checked against.
    soil = (SAMPLE / "01 Soil Report" / "soil-report.json").read_text("utf-8")
    settings_text = (SAMPLE / "02 Project Settings" / "project-settings.json").read_text("utf-8")
    settings = json.loads(settings_text)
    computed = handlers.soil_report(soil, settings_text)
    assert computed["siteClass"]["class"] == settings["site"]["siteClass"] == "SD"
    assert computed["siteClass"]["flags"] == []
    override = settings["foundation"]["allowableBearing"]
    for borehole in computed["boreholes"]:
        liquefaction = borehole["liquefaction"]
        assert not [p for p in liquefaction["points"] if p["liquefiable"]], borehole["id"]
        assert liquefaction["lpi"] == 0
        reference = next(
            t for t in borehole["bearing"]["table"] if (t["B"], t["Df"]) == (2000, 1500)
        )
        assert reference["qa"] >= override, borehole["id"]
    assert not any("liquefiable" in note for note in computed["notes"])


# ─────────────────────────────── the kept required steel ───────────────────────────────


def _project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "P"
    for relative in design_mode.INPUT_FILES:
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text("{}", "utf-8")
    model = root / "08 FEM" / "model.osmodel"
    model.parent.mkdir(parents=True)
    model.write_text("{}", "utf-8")
    out = root / "08 FEM" / "model.results"
    out.mkdir()
    (out / "case-1.h5").write_bytes(b"results")
    return out, model


def test_required_steel_is_kept_until_an_input_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def fake(
        out_dir: Any, project_path: Any, options: Any = None, gathered: Any = None
    ) -> dict[str, Any]:
        calls.append(1)
        return {"elements": [], "summary": {"elements": 0}, "worked": len(calls)}

    import saengine.design

    monkeypatch.setattr(saengine.design, "design_required", fake)
    monkeypatch.setattr(design_mode, "gathered", lambda *_, **__: None)
    out, model = _project(tmp_path)
    first = design_mode.required(out, model)
    assert design_mode.required(out, model) == first and len(calls) == 1
    # Run All's own summary beside the results does not make it stale ...
    (out / "design-summary.json").write_text("{}", "utf-8")
    assert design_mode.required(out, model)["worked"] == 1
    # ... new bars in 04 Objects do, and so does a new run of the analysis.
    (model.parent.parent / "04 Objects" / "objects.json").write_text('{"objects": []}', "utf-8")
    assert design_mode.required(out, model)["worked"] == 2
    stamp = (out / "case-1.h5").stat()
    os.utime(out / "case-1.h5", ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 10**9))
    assert design_mode.required(out, model)["worked"] == 3
    assert design_mode.required(out, model, fresh=True)["worked"] == 4
    assert json.loads((out / design_mode.REQUIRED_FILE).read_text("utf-8"))["result"]["worked"] == 4


def test_two_writers_at_once_never_raise_and_leave_a_whole_file(tmp_path: Path) -> None:
    # The Properties panel and Run All can keep an answer for the same results at once (worker
    # threads of one process): a write that loses the race is not kept, it never raises.
    out = tmp_path / "model.results"
    out.mkdir()
    big = {"elements": [{"element": f"E{i}", "notes": "n" * 200} for i in range(3000)]}
    errors: list[BaseException] = []

    def write(tag: str) -> None:
        for _ in range(30):
            try:
                design_mode.keep(out, tag, big)
            except BaseException as error:  # noqa: BLE001 - the test collects every failure
                errors.append(error)

    threads = [threading.Thread(target=write, args=(f"s{i}",)) for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    kept = json.loads((out / design_mode.REQUIRED_FILE).read_text("utf-8"))
    assert kept["stamp"] in {"s0", "s1", "s2"} and len(kept["result"]["elements"]) == 3000
    assert not list(out.glob("*.tmp"))  # every temporary file is gone


def _row(element: str, kind: str, type_id: str, quantity: str, required: float, provided: Any,
         unit: str = "mm²", ok: Any = True, too_small: bool = False, location: str = "start"):  # fmt: skip
    return {
        "element": element, "kind": kind, "type": type_id, "location": location,
        "quantity": quantity, "required": required, "provided": provided, "unit": unit,
        "ok": ok, "tooSmall": too_small,
    }  # fmt: skip


def test_required_tables_give_one_row_per_type_at_the_governing_location() -> None:
    result = {
        "elements": [
            _row("B1", "beam", "B300", "top bars (hogging)", 500, 603),
            _row("B2", "beam", "B300", "top bars (hogging)", 820, 603, ok=False),
            _row("B2", "beam", "B300", "stirrups Av/s", 250, 1047, unit="mm²/m"),
            _row(
                "C1", "column", "C400", "tie spacing (max)", 320, 150, unit="mm", location="column"
            ),
            _row("C1", "column", "C400", "longitudinal bars", 2400, 3142, location="column"),
            _row("F1", "isolated", "F1", "top X bars", 0, None, unit="mm²/m", ok=None),
            _row("F1", "isolated", "F1", "bottom X bars", 900, 754, unit="mm²/m", ok=False),
            _row(
                "F1",
                "isolated",
                "F1",
                "other check",
                0,
                None,
                unit="",
                ok=None,
                too_small=True,
                location="foundation",
            ),
        ],
        "summary": {"elements": 4, "assumed": []},
    }
    tables = design_mode.required_tables(result)
    assert [(t["title"], t["rows"], t["bad"]) for t in tables] == [
        ("Columns", [["C400", "1", "longitudinal bars (column, C1)", "2,400", "3,142", "mm²", "–",
                      "OK"]], [False]),
        ("Beams", [["B300", "2", "top bars (hogging) (start, B2)", "820", "603", "mm²", "B2",
                    "SHORT"]], [True]),
        ("Isolated footings", [["F1", "1", "bottom X bars (start, F1)", "900", "754", "mm²/m",
                                "F1", "SHORT"]], [True]),
    ]  # fmt: skip
    assert design_mode.required_summary(result) == {
        "elements": 4, "short": ["B2", "F1"], "tooSmall": [], "otherFailures": ["F1"],
        "assumed": [],
    }  # fmt: skip

"""Walkthrough 3 fix track 3: the design loop's plumbing (no design number changes here).

- the code pack tables a computation reads are recorded, and a project override of a table the
  analysis never reads (a ramp slope) leaves the analysis model's stamp unchanged (B10-32);
- the design stamps leave out overrides of tables the design work has not read (B10-33);
- a building none of whose members has bars gets its design report at once (B10-11);
- the counts: diaphragms are not members (B10-22), the foundations' failures are counted of all
  of them (B10-34), the no-capacity sentinel is never printed as a utilisation (FD-17, SL-15);
- the RPC server's jobs and their notes (B10-21);
- one proposal at a time for the same inputs (FD-5).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from saengine.codes import registry
from saengine.codes.overrides import restricted, table_of
from saengine.fem.derive import code_tables_of, code_tables_text, settings_stamp

# ─────────────────────────────── code tables read ───────────────────────────────


def test_recording_tables_names_the_tables_read_nested() -> None:
    from saengine.codes import context as code_context

    pack = code_context.default_pack()
    with registry.recording_tables() as outer:
        pack.table("factors")
        with registry.recording_tables() as inner:
            pack.data("wind")
            pack.override("seismic", "zone")
    assert inner == {"wind", "seismic"}
    assert outer == {"factors", "wind", "seismic"}
    # Outside a recording nothing is kept.
    pack.table("factors")


def test_override_paths_name_their_table() -> None:
    assert table_of("factors.phi.shear") == "factors"
    assert table_of("combinations.strength[1.2D + 1.6L].factors.L") == "combinations"
    assert table_of("[a.b].c") == "a.b"
    assert table_of("") is None
    overrides = {"accessibility.ramp.gradient": 12, "factors.phi.shear": 0.7, "": 1}
    assert restricted(overrides, {"factors"}) == {"factors.phi.shear": 0.7, "": 1}


def _settings_text(overrides: dict | None = None) -> str:
    data = {"project": {"name": "P"}, "analysis": {"x": 1}}
    if overrides is not None:
        data["codeOverrides"] = overrides
    return json.dumps(data)


def test_settings_stamp_leaves_out_overrides_of_tables_not_read() -> None:
    tables = frozenset({"seismic", "wind", "combinations"})
    plain = settings_stamp(_settings_text(), code_tables=tables)
    ramp = settings_stamp(_settings_text({"accessibility.ramp": 12}), code_tables=tables)
    zone = settings_stamp(_settings_text({"seismic.zone": 0.3}), code_tables=tables)
    assert ramp == plain  # the analysis never reads it: the model stays current
    assert zone != plain
    # Without the tables (a model derived before they were recorded) every override counts.
    assert settings_stamp(_settings_text({"accessibility.ramp": 12})) != settings_stamp(
        _settings_text()
    )
    # The stamp without overrides is the one models have always recorded.
    assert plain == settings_stamp(_settings_text())


def test_code_tables_round_trip_through_the_recorded_sources() -> None:
    assert code_tables_of({"codeTables": code_tables_text({"wind", "seismic"})}) == {
        "wind",
        "seismic",
    }
    assert code_tables_of({"codeTables": code_tables_text(set())}) == frozenset()
    assert code_tables_of({}) is None


def test_the_derived_model_records_its_tables_and_a_ramp_override_keeps_it_current() -> None:
    from test_correctness_wiring import _three_bays_two_storeys

    from saengine.library import default_material_library
    from saengine.library.settings import default_project_settings
    from saengine.pipeline.status import fem_source_changed, recorded_sources
    from saengine.rpc.handlers import derive_fem

    building, objects = _three_bays_two_storeys()
    settings = json.loads(default_project_settings("F3").model_dump_json(by_alias=True))
    text = json.dumps(settings)
    result = derive_fem(
        building.model_dump_json(by_alias=True),
        objects.model_dump_json(by_alias=True),
        default_material_library().model_dump_json(by_alias=True),
        text,
    )
    model = json.loads(result["text"])
    recorded = recorded_sources(model["meta"]["description"])
    tables = code_tables_of(recorded)
    assert tables is not None and "accessibility" not in tables and "seismic" in tables
    ramp = json.dumps({**settings, "codeOverrides": {"accessibility.ramps.maxGradient": 0.1}})
    zone = json.dumps({**settings, "codeOverrides": {"zoneCoefficients.zones.2": 0.25}})
    assert not fem_source_changed({"settings": text}, "settings", recorded["settings"], tables)
    assert not fem_source_changed({"settings": ramp}, "settings", recorded["settings"], tables)
    assert fem_source_changed({"settings": zone}, "settings", recorded["settings"], tables)


# ─────────────────────────────── design stamps ───────────────────────────────


def _design_project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "F3"
    for folder in ("02 Project Settings", "08 FEM/model.results"):
        (root / folder).mkdir(parents=True)
    model = root / "08 FEM" / "model.osmodel"
    model.write_text(json.dumps({"meta": {}, "nodes": []}), encoding="utf-8")
    (root / "08 FEM/model.results/manifest.json").write_text("{}", encoding="utf-8")
    return root, model


def _write_settings(root: Path, overrides: dict | None) -> None:
    data: dict = {"project": {"name": "F3"}}
    if overrides:
        data["codeOverrides"] = overrides
    (root / "02 Project Settings/project-settings.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def test_design_stamp_ignores_overrides_of_tables_the_design_did_not_read(tmp_path) -> None:
    from saengine.codes import context as code_context
    from saengine.pipeline import design_mode

    root, model = _design_project(tmp_path)
    out = model.parent / "model.results"
    _write_settings(root, None)
    before = design_mode.inputs_stamp(out, model)
    # Before anything was recorded every override counts.
    _write_settings(root, {"accessibility.ramps.maxGradient": 0.1})
    assert design_mode.inputs_stamp(out, model) != before
    # The design work read the factors only.
    with design_mode.recording(out):
        code_context.default_pack().table("factors")
    assert design_mode.learned_tables(out) == {"factors"}
    _write_settings(root, None)
    plain = design_mode.inputs_stamp(out, model)
    _write_settings(root, {"accessibility.ramps.maxGradient": 0.1})
    assert design_mode.inputs_stamp(out, model) == plain
    _write_settings(root, {"factors.phi.shear": 0.7})
    assert design_mode.inputs_stamp(out, model) != plain
    # Recording more adds to the tables, never fewer; the file does not enter the stamp.
    with design_mode.recording(out):
        code_context.default_pack().table("wind")
    assert design_mode.learned_tables(out) == {"factors", "wind"}


# ─────────────────────────────── no bars: at once ───────────────────────────────


def _unreinforced_project(tmp_path: Path, bars: bool = False) -> Path:
    from test_correctness_wiring import _three_bays_two_storeys

    from saengine.library import default_material_library
    from saengine.library.settings import default_project_settings

    building, objects = _three_bays_two_storeys()
    root = tmp_path / "NoBars"
    for folder in ("02 Project Settings", "03 Materials", "04 Objects", "06 BIM", "08 FEM"):
        (root / folder).mkdir(parents=True)
    data = json.loads(objects.model_dump_json(by_alias=True, exclude_none=True))
    if bars:
        data["objects"][0]["reinforcement"] = {"material": "B420DWR"}
    (root / "04 Objects/objects.json").write_text(json.dumps(data), encoding="utf-8")
    (root / "06 BIM/bim.json").write_text(building.model_dump_json(by_alias=True), encoding="utf-8")
    (root / "03 Materials/materials.json").write_text(
        default_material_library().model_dump_json(by_alias=True), encoding="utf-8"
    )
    (root / "02 Project Settings/project-settings.json").write_text(
        default_project_settings("NoBars").model_dump_json(by_alias=True), encoding="utf-8"
    )
    model = root / "08 FEM/model.osmodel"
    model.write_text("{}", encoding="utf-8")
    return model


def test_a_building_without_bars_gets_its_report_at_once(tmp_path) -> None:
    from saengine.pipeline.design_mode import unreinforced_report

    model = _unreinforced_project(tmp_path)
    report = unreinforced_report(model)
    assert report is not None
    summary = report["summary"]
    assert summary["checked"] == 0 and summary["elements"]["checked"] == 0
    assert summary["noBars"] == ["BM", "COL"]
    assert summary["counts"]["members"]["notChecked"] == len(report["skipped"])
    assert {s["kind"] for s in report["skipped"]} == {"beam", "column"}
    assert all(s["reason"] == "no reinforcement" for s in report["skipped"])
    assert summary["maxUtilisation"] is None


def test_a_type_with_bars_is_checked_as_usual(tmp_path) -> None:
    from saengine.pipeline.design_mode import unreinforced_report

    assert unreinforced_report(_unreinforced_project(tmp_path, bars=True)) is None


# ─────────────────────────────── counts ───────────────────────────────


def test_diaphragms_are_counted_apart_from_the_members() -> None:
    from saengine.design.check import design_counts

    checked = [
        {"kind": "beam", "ok": True},
        {"kind": "column", "ok": False},
        {"kind": "diaphragm", "ok": False},
    ]
    counts = design_counts(checked, [{"kind": "beam", "reason": "no reinforcement"}], [], [])
    assert counts["members"]["total"] == 3
    assert counts["members"]["checked"] == 2 and counts["members"]["failed"] == 1
    assert "diaphragm" not in counts["members"]["byKind"]
    assert counts["diaphragms"] == {"checked": 1, "passed": 0, "failed": 1}


def test_foundation_failures_are_counted_of_all_the_foundations() -> None:
    from saengine.report.build import design_status

    status = design_status(
        {
            "design": {"available": True, "checked": 0, "failed": 0},
            "foundations": {"available": True, "checked": 1, "failed": 6, "total": 20},
        }
    )
    assert "6 of 20 foundations or tie beams fail" in status["headline"]


def test_the_no_capacity_sentinel_is_never_a_utilisation() -> None:
    from saengine.report.build import _utilisation_text

    assert _utilisation_text(99.0) == "no capacity"
    assert _utilisation_text(None) == "–"
    assert _utilisation_text(0.8123) == "0.812"


# ─────────────────────────────── jobs ───────────────────────────────


def test_jobs_say_what_each_request_does() -> None:
    from saengine.rpc import jobs

    jobs.note("outside any request")  # nothing to say it of: ignored
    job, token = jobs.start("design/report")
    try:
        seen: list = []

        def work(_params):
            jobs.note("Design checks")
            seen.extend(jobs.running())

        thread = threading.Thread(target=jobs.run_as, args=(job, work, None))
        thread.start()
        thread.join()
        assert [(j["method"], j["note"]) for j in seen] == [("design/report", "Design checks")]
    finally:
        jobs.finish(job, token)
    assert all(j["id"] != job.id for j in jobs.running())


def test_the_server_answers_its_jobs() -> None:
    from saengine.rpc.server import create_server

    server = create_server()
    assert "saengine/jobs" in server.protocol.fm.features


# ─────────────────────────────── one proposal at a time ───────────────────────────────


def test_the_same_proposal_asked_twice_at_once_is_worked_out_once(monkeypatch, tmp_path) -> None:
    from saengine.design import proposal
    from saengine.pipeline import design_mode

    calls: list[int] = []
    started = threading.Event()
    release = threading.Event()

    def propose(out_dir, project_path, options, gathered):
        calls.append(1)
        started.set()
        release.wait(5)
        return {"mode": "byType", "types": []}

    monkeypatch.setattr(proposal, "propose", propose)
    monkeypatch.setattr(design_mode, "report_stamp", lambda out, model: "stamp")
    monkeypatch.setattr(design_mode, "gathered", lambda *a, **k: None)
    proposal._PROPOSED.clear()
    answers: list = []
    first = threading.Thread(
        target=lambda: answers.append(proposal.design_proposal(tmp_path, tmp_path / "m"))
    )
    first.start()
    started.wait(5)
    second = threading.Thread(
        target=lambda: answers.append(proposal.design_proposal(tmp_path, tmp_path / "m"))
    )
    second.start()
    release.set()
    first.join(5)
    second.join(5)
    proposal._PROPOSED.clear()
    assert len(calls) == 1
    assert answers == [{"mode": "byType", "types": []}] * 2

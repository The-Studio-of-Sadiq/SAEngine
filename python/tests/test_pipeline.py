"""The headless pipeline's pieces: the part statuses (a port of partStatus.ts, checked against
its own test cases), the summary files' format, Run All stopping at a failed step, the bill's
line endings and the exports. The full run on the sample is in ``test_pipeline_run_all.py``."""

from __future__ import annotations

import importlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from saengine.fem.derive import mep_stamp
from saengine.library.bim import source_stamp
from saengine.pipeline import summaries as S
from saengine.pipeline.exports import boq_csv, floor_plan_drawing, profile_outline
from saengine.pipeline.project import PROJECT_PARTS, open_project, project_parts
from saengine.pipeline.status import (
    StatusInputs,
    compute_part_statuses,
    export_kind,
    ground_level_stamp_text,
    next_step,
    recorded_sources,
)

#: The module (``saengine.pipeline.run_all`` the package attribute is the function).
R = importlib.import_module("saengine.pipeline.run_all")
SAMPLE = (
    Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"
)


def placeholder(part: str) -> str:
    return json.dumps({"schema": 1, "part": part})


SOURCES = {
    "settings": '{"schema": "saengine.projectSettings/1"}',
    "materials": '{"materials": []}',
    "objects": '{"objects": [{"id": "C1"}]}',
    "floorPlan": '{"schema": "saengine.floorPlan/1", "columns": [{"id": "C1"}]}',
}
BIM = json.dumps(
    {"schema": "saengine.bim/2", "source": {"floorPlan": source_stamp(SOURCES["floorPlan"])},
     "elements": []}
)  # fmt: skip


def fem_model(sources: dict[str, str]) -> str:
    entries = "; ".join(
        f"{k}={mep_stamp(t) if k == 'mep' else source_stamp(t)}" for k, t in sources.items()
    )
    return json.dumps(
        {"schema_version": 2, "meta": {"description": f"Derived by SAEngine. Sources: {entries}"}}
    )


DERIVED = fem_model({"bim": BIM, **{k: SOURCES[k] for k in ("settings", "objects", "materials")}})
BOQ = json.dumps({
    "schema": "saengine.boq/1",
    "source": {"bim": source_stamp(BIM), "objects": source_stamp(SOURCES["objects"]),
               "materials": source_stamp(SOURCES["materials"])},
    "items": [],
})  # fmt: skip


def inputs(texts: dict[str, str | None] | None = None, **rest) -> StatusInputs:
    base = {
        "soil": placeholder("soil"), "mep": placeholder("mep"),
        "substructure": placeholder("substructure"), **SOURCES, "bim": BIM, "fem": DERIVED,
        "boq": placeholder("boq"),
    }  # fmt: skip
    return StatusInputs(texts={**base, **(texts or {})}, **rest)


def lines(state: StatusInputs, parts=PROJECT_PARTS) -> list[str]:
    statuses = compute_part_statuses(parts, state, lambda t: f"day {t:g}")
    return [f"{s.part}: {s.state}{' ' + s.text if s.text else ''}" for s in statuses]


def test_status_of_a_derived_project_not_analysed():
    assert lines(inputs()) == [
        "soil: notStarted not started",
        "settings: done",
        "materials: done",
        "objects: done 1 type",
        "floorPlan: done 1 member",
        "bim: done",
        "mep: notStarted not started",
        "fem: inProgress not analysed",
        "substructure: notStarted not started",
        "boq: notStarted not measured",
        "exports: notStarted no report",
    ]


def test_status_of_the_analysis_model():
    def fem(texts=None, **rest) -> str:
        return lines(inputs(texts, **rest))[7]

    passing = json.dumps({"checked": 13, "passed": 13, "failed": 0})
    failing = json.dumps({"checked": 13, "passed": 10, "failed": 3})
    assert [
        fem({"fem": json.dumps({"schema_version": 2, "meta": {"name": "P"}})}),
        fem({"fem": None}),
        fem({"fem": "{ not json"}),
        fem({"materials": '{"materials": [1]}'}),
        fem(femModelTime=10, femResultsTime=20),
        fem(femModelTime=30, femResultsTime=20),
        fem(femModelTime=10, femResultsTime=20, designSummaryText=passing, designSummaryTime=25),
        fem(femModelTime=10, femResultsTime=20, designSummaryText=failing, designSummaryTime=25),
        fem(femModelTime=10, femResultsTime=20, designSummaryText=failing, designSummaryTime=15),
    ] == [
        "fem: notStarted not derived",
        "fem: notStarted not derived",
        "fem: error invalid file",
        "fem: stale stale",
        "fem: inProgress analysed",
        "fem: stale stale",
        "fem: done 13 pass",
        "fem: failed 3 fail",
        "fem: inProgress analysed",
    ]
    nothing = json.dumps({"checked": 0, "passed": 0, "failed": 0})
    assert fem(
        femModelTime=1, femResultsTime=2, designSummaryText=nothing, designSummaryTime=3
    ) == ("fem: inProgress nothing checked")


def test_status_of_the_bill_the_building_model_and_the_report():
    def line(texts=None, **rest) -> list[str]:
        return lines(inputs(texts, **rest))

    assert [
        line({"boq": BOQ})[9],
        line({"boq": BOQ, "objects": '{"objects": [1]}'})[9],
        line({"boq": "["})[9],
        line({"floorPlan": '{"schema": "saengine.floorPlan/1", "columns": [1, 2]}'})[5],
        line({"bim": json.dumps({"schema": "saengine.bim/2", "elements": []})})[5],
        line(reportTime=42)[10],
        line({"materials": "{"})[2],
        line({"settings": None})[1],
    ] == [
        "boq: done measured",
        "boq: stale stale",
        "boq: error invalid file",
        "bim: stale stale",
        "bim: notStarted not built",
        "exports: inProgress report day 42",
        "materials: error invalid file",
        "settings: notStarted not started",
    ]


def test_status_of_mep_and_substructure_from_their_summaries():
    mep = json.dumps({"schema": "saengine.mep/1", "equipment": [{"id": "E1"}],
                      "plumbing": {"risers": [{"id": "R1"}], "tanks": []}})  # fmt: skip
    sources = {p: source_stamp(SOURCES[p]) for p in ("settings", "materials", "objects")}
    summary = {"equipment": 1, "openings": 0, "openingsFailed": 0, "clashes": 0, "clashesOpen": 0,
               "source": {**sources, "bim": source_stamp(BIM), "mep": source_stamp(mep)}}  # fmt: skip
    plumbing = {"risers": 1, "tanks": 0, "failed": 2, "floorsLow": 0, "source": {"soil": ""}}
    soil_missing = {"soil": None}

    def line(texts, **rest) -> str:
        return lines(inputs({"mep": mep, **texts}, **rest))[6]

    assert [
        line({}),
        line({}, mepSummaryText=json.dumps(summary), mepSummaryTime=5),
        line(soil_missing, mepSummaryText=json.dumps({**summary, "plumbing": plumbing}),
             mepSummaryTime=5),
        line(soil_missing, mepSummaryText=json.dumps({**summary, "plumbing": plumbing,
             "hvac": {"failed": 1}}), mepSummaryTime=5),
        line(soil_missing, mepSummaryText=json.dumps({**summary, "plumbing": {**plumbing,
             "failed": 0}}), mepSummaryTime=5, femResultsTime=9),
    ] == [
        "mep: inProgress not checked",
        "mep: inProgress plumbing not checked",
        "mep: failed 2 plumbing checks fail",
        "mep: failed 3 checks fail",
        "mep: inProgress not checked",
    ]  # fmt: skip
    foundations = json.dumps({"schema": "saengine.substructure/1", "foundations": [{"id": "F1"}]})
    checked = json.dumps({"foundations": 1, "checked": 1, "passed": 0, "failed": 1,
                          "source": {"substructure": source_stamp(foundations)}})  # fmt: skip
    statuses = lines(inputs({"substructure": foundations}, substructureSummaryText=checked,
                            substructureSummaryTime=3))  # fmt: skip
    assert statuses[8] == "substructure: failed 1 fail"
    assert next_step(compute_part_statuses(PROJECT_PARTS, inputs()))[1].part == "fem"


def test_status_helpers_match_the_typescript():
    assert recorded_sources("Derived. Sources: bim=abc; mep=def") == {"bim": "abc", "mep": "def"}
    # JavaScript's `$` is the very end of the text: a trailing line break hides the list.
    assert recorded_sources("Sources: bim=abc\n") == {}
    assert ground_level_stamp_text('{"foundation": {"groundLevel": -150}}') == source_stamp(
        "groundLevel=-150000"
    )
    assert [export_kind(p) for p in ("report.pdf", "IFC/a.ifc", "Floor Plan/L1.dxf", "boq.csv",
                                     "x/boq.csv", "notes.txt")] == [
        "report", "ifc", "dxf", "csv", None, None]  # fmt: skip
    assert [p.id for p in project_parts("structure")][4] == "structure"


# ─────────────────────────────── summaries ───────────────────────────────

#: A summary file as the app's Run All wrote it (captured from the sample with a synthetic soil
#: report): the text the Python writers must reproduce, key order and number format included.
APP_MEP_SUMMARY = (
    '{\n\t"equipment": 0,\n\t"openings": 1,\n\t"openingsFailed": 0,\n\t"openingsPartial": 0,\n'
    '\t"clashes": 0,\n\t"clashesOpen": 0,\n\t"computed": "2026-10-18T10:34:38.462Z",\n'
    '\t"source": {\n\t\t"settings": "ca07",\n\t\t"mep": "d0ff"\n\t},\n'
    '\t"plumbing": {\n\t\t"risers": 2,\n\t\t"tanks": 3,\n\t\t"failed": 2,\n\t\t"floorsLow": 1,\n'
    '\t\t"source": {\n\t\t\t"soil": "ce9c"\n\t\t}\n\t},\n'
    '\t"hvac": {\n\t\t"plant": 2,\n\t\t"ducts": 1,\n\t\t"cooling": 11.831,\n'
    '\t\t"engine": "EnergyPlus version 26.2.0",\n\t\t"failed": 1\n\t},\n'
    '\t"electrical": {\n\t\t"equipment": 2,\n\t\t"risers": 1,\n\t\t"demand": 9.242352941176472,\n'
    '\t\t"downConductors": 2,\n\t\t"failed": 0\n\t}\n}\n'
)


def test_summary_text_is_what_javascript_writes():
    assert S.summary_text(json.loads(APP_MEP_SUMMARY)) == APP_MEP_SUMMARY
    assert S.js_stringify({"a": 3.0, "b": [], "c": {}, "d": None, "e": "Ā"}) == (
        '{\n\t"a": 3,\n\t"b": [],\n\t"c": {},\n\t"d": null,\n\t"e": "Ā"\n}'
    )
    from datetime import UTC, datetime

    assert S.iso_time(datetime(2026, 10, 18, 10, 34, 38, 462999, UTC)) == "2026-10-18T10:34:38.462Z"


def test_summary_writers_have_the_app_keys_in_the_app_order():
    document = {"equipment": [], "openings": [{"id": "O1"}], "shafts": [], "ifcModels": [],
                "plumbing": {"risers": [{}, {}], "tanks": [{}, {}, {}]},
                "hvac": {"plant": [{}, {}], "ducts": [{}]},
                "electrical": {"equipment": [{}, {}], "risers": [{}]}}  # fmt: skip
    raw = {"openings": [{"id": "O1", "ok": True}], "clashes": [],
           "sources": {"settings": "ca07"}}  # fmt: skip
    summary = S.mep_summary_file(document, raw, "{}", {p: None for p in S.MEP_SOURCE_PARTS})
    summary["plumbing"] = S.plumbing_summary_file(
        document, {"checks": [{"status": "fail"}, {"ok": False}],
                   "hydraulics": {"floors": [{"story": "L3", "head": 3, "required": 7}]},
                   "sources": {"soil": "ce9c"}})  # fmt: skip
    summary["hvac"] = S.hvac_summary_file(
        document, {"total": 11.831, "engine": "EnergyPlus version 26.2.0",
                   "air": {"checks": [{"status": "fail"}]}})  # fmt: skip
    summary["electrical"] = S.electrical_summary_file(
        document, {"demand": {"kva": 9.242352941176472}, "checks": [{"ok": True}],
                   "lightning": {"downConductors": ["C1", "C4"]}})  # fmt: skip
    app = json.loads(APP_MEP_SUMMARY)

    def shape(value):
        return {k: shape(v) for k, v in value.items()} if isinstance(value, dict) else type(value)

    assert list(summary) == list(app)
    for key in ("plumbing", "hvac", "electrical"):
        assert summary[key] == app[key]
    assert summary["source"]["mep"] == source_stamp("{}") and summary["source"]["bim"] == ""
    design = S.design_summary_file({"summary": {"checked": 15, "passed": 10, "failed": 5,
                                                "maxUtilisation": 1.873, "governing": "S1"}})  # fmt: skip
    assert list(design) == [
        "checked",
        "passed",
        "failed",
        "maxUtilisation",
        "governing",
        "computed",
    ]
    substructure = S.substructure_summary_file(
        {"foundations": [{"id": "F1"}]},
        {"foundations": [{"id": "F1", "ok": False, "utilisation": 1.784}], "sources": {"soil": ""}},
    )
    assert list(substructure) == ["foundations", "checked", "total", "passed", "failed", "unsupported",
                                  "status", "maxUtilisation", "governing", "computed", "source"]  # fmt: skip
    assert (substructure["failed"], substructure["governing"]) == (1, "F1")
    # Checked of total and the verdict the part list reads (U2).
    verdict = (substructure["checked"], substructure["total"], substructure["status"])
    assert verdict == (1, 1, "fail")


# ─────────────────────────────── Run All ───────────────────────────────


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    target = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, target)
    return target


def test_derivation_state_and_bill_sources(sample: Path):
    project = open_project(sample)
    texts = project.texts(R.DERIVATION_INPUTS)
    assert R.derivation_state(None, texts) == (False, [
        "Building Model", "Project Settings", "Object Types", "Materials"])  # fmt: skip
    description = "Sources: " + "; ".join(
        f"{p}={source_stamp(texts[p])}" for p in ("bim", "settings", "objects", "materials")
    )
    # The sample's MEP has content the model would take: a model derived without it is stale.
    assert R.derivation_state(description, texts) == (True, ["MEP"])
    description += f"; mep={mep_stamp(texts['mep'])}"
    assert R.derivation_state(description, texts) == (True, [])
    bill = R.parse_boq(project.text("boq"))
    assert R.changed_boq_sources(bill, project.texts([p for p, *_ in R.BOQ_SOURCES])) == []
    assert R.changed_boq_sources(None, {"bim": "{}"}) == ["bim", "objects", "materials"]


def test_the_bill_keeps_its_line_endings(tmp_path: Path):
    crlf = tmp_path / "crlf.json"
    crlf.write_bytes(b'\xef\xbb\xbf{\r\n"a": 1\r\n}\r\n')
    R._write_like_text_model(crlf, '{\n"b": 2\n}\n')
    assert crlf.read_bytes() == b'\xef\xbb\xbf{\r\n"b": 2\r\n}\r\n'
    lf = tmp_path / "lf.json"
    lf.write_bytes(b'{\n"a": 1\n}\n')
    R._write_like_text_model(lf, '{\n"b": 2\n}\n')
    assert lf.read_bytes() == b'{\n"b": 2\n}\n'


def test_a_failed_step_blocks_only_the_steps_that_need_it(
    sample: Path, monkeypatch: pytest.MonkeyPatch
):
    from saengine.rpc import handlers

    monkeypatch.setattr(
        handlers, "derive_fem", lambda *a, **k: {"problems": ["Building model: bad"]}
    )
    monkeypatch.setattr(handlers, "compute_boq", lambda *a, **k: {"problems": ["not measured"]})
    seen: list[str] = []
    result = R.run_all(
        sample,
        steps=["bim", "derive", "analysis", "design", "boq", "report"],
        progress=lambda step, i, n, m: seen.append(step),
    )
    assert [(s.id, s.status) for s in result.steps] == [
        ("bim", "skipped"),  # the sample's building model is up to date
        ("derive", "failed"),
        ("analysis", "notRun"),
        ("design", "notRun"),
        ("boq", result.step("boq").status),  # needs only the building model: it still runs
        ("report", "notRun"),
    ]
    assert "boq" in seen and "analysis" not in seen
    assert result.step("derive").message == "Building model: bad"
    assert (
        result.step("design").message == "Not run: it needs the analysis model step, which failed."
    )
    assert result.stopped_at == "derive" and not result.ok
    assert result.summary.startswith("Run All failed at step 2 of 10 (analysis model): Building")
    assert "step(s) not run" in result.summary
    with pytest.raises(ValueError, match="unknown step"):
        R.run_all(sample, steps=["derive", "nope"])
    assert R.normalise_steps(["report,derive"]) == ["derive", "report"]
    assert R.normalise_steps(["design,substructure"]) == ["substructure", "design"]


def test_a_building_model_without_members_is_nothing_to_analyse(tmp_path: Path):
    """G3: Run All on an empty project stops at once, not after a minute of "0 pass, 0 fail"."""
    project = tmp_path / "Empty"
    shutil.copytree(SAMPLE, project)
    bim = project / "06 BIM" / "bim.json"
    document = json.loads(bim.read_text(encoding="utf-8"))
    document["elements"] = []
    bim.write_text(json.dumps(document), encoding="utf-8")
    plan = project / "05 Floor Plan" / "floor-plan.json"
    document["source"] = {"floorPlan": source_stamp(plan.read_text(encoding="utf-8"))}
    bim.write_text(json.dumps(document), encoding="utf-8")
    result = R.run_all(project, steps=["bim", "derive", "analysis", "design"])
    assert [s.status for s in result.steps] == ["failed", "notRun", "notRun", "notRun"]
    assert result.steps[0].message.startswith("Nothing to analyse")


def test_a_design_that_checks_nothing_fails_and_removes_the_old_summary(
    sample: Path, monkeypatch: pytest.MonkeyPatch
):
    """G1: "0 pass, 0 fail" is a failure, and the previous summary does not stay current."""
    from saengine.pipeline import design_mode

    results = sample / "08 FEM" / "model.results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "design-summary.json").write_text('{"checked": 3, "passed": 3, "failed": 0}')
    empty = {"summary": {"checked": 0, "passed": 0, "failed": 0, "noBars": ["B1"]}, "notes": []}
    monkeypatch.setattr(design_mode, "report_stamp", lambda *a: None)
    monkeypatch.setattr(R, "_handlers", lambda: SimpleNamespace(design_report=lambda *a: empty))
    result = R.run_all(sample, steps=["design"])
    step = result.steps[0]
    assert step.status == "failed"
    assert step.message.startswith("The design checks checked nothing: the object types B1")
    assert not (results / "design-summary.json").exists()


def test_the_settings_stamp_leaves_out_the_title_block():
    """X28: the engineer's name and the drawings' title block do not make the model stale."""
    from saengine.fem.derive import settings_stamp

    base = {"schema": "s", "project": {"name": "A"}, "seismic": {"system": "SMF"}}
    named = {**base, "project": {"name": "A", "engineer": "E"}, "drawings": {"drawnBy": "X"}}
    assert settings_stamp(json.dumps(base)) == settings_stamp(json.dumps(named, indent=2))
    assert settings_stamp(json.dumps(base)) != settings_stamp(
        json.dumps({**base, "seismic": {"system": "IMF"}})
    )
    texts = {"settings": json.dumps(named)}
    from saengine.pipeline.status import fem_source_changed

    assert not fem_source_changed(texts, "settings", settings_stamp(json.dumps(base)))
    # A model derived before records the whole file's stamp: current while the file is unchanged.
    assert not fem_source_changed(texts, "settings", source_stamp(texts["settings"]))
    assert fem_source_changed(texts, "settings", "0" * 40)


def test_the_analysis_is_kept_while_the_model_computes_the_same(tmp_path: Path):
    """X28/X19: a model derived again to the same analysis keeps its results."""
    folder = tmp_path / "08 FEM"
    (folder / "model.results").mkdir(parents=True)
    model = folder / "model.osmodel"
    model.write_text(json.dumps({"meta": {"description": "Sources: settings=1"}, "nodes": [1]}))
    (folder / "model.results" / "manifest.json").write_text('{"cases": []}')
    assert not R.results_current(model)
    R.keep_analysis_inputs(model)
    assert R.results_current(model)
    model.write_text(json.dumps({"meta": {"description": "Sources: settings=2"}, "nodes": [1]}))
    assert R.results_current(model)  # only the meta changed
    model.write_text(json.dumps({"meta": {}, "nodes": [1, 2]}))
    assert not R.results_current(model)


def test_an_unexpected_error_is_the_steps_error(sample: Path, monkeypatch: pytest.MonkeyPatch):
    from saengine.rpc import handlers

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(handlers, "build_report", boom)
    result = R.run_all(sample, steps=["report"])
    assert (result.steps[0].status, result.steps[0].message) == ("error", "RuntimeError: disk full")


# ─────────────────────────────── exports ───────────────────────────────


def test_bill_as_csv_like_the_app():
    document = {"items": [{"code": "C.01", "group": "concrete", "description": 'Slab, "S1"',
                           "quantity": 1.5, "unit": "m3",
                           "breakdown": [{"element": "S1", "story": "L1", "quantity": 1.5}]}]}  # fmt: skip
    assert boq_csv(document) == (
        "Row,Code,Group,Description,Element,Story,Detail,Item Quantity,Element Quantity,Unit\r\n"
        'item,C.01,concrete,"Slab, ""S1""",,,,1.5,,m3\r\n'
        'element,C.01,concrete,"Slab, ""S1""",S1,L1,,,1.5,m3\r\n'
    )


def test_floor_plan_drawing_like_the_app(sample: Path):
    project = open_project(sample)
    layout = json.loads(project.text("floorPlan"))
    objects = json.loads(project.text("objects"))
    entities, problems = floor_plan_drawing(layout, objects, "L1")
    layers = {e["layer"] for e in entities}
    assert {"S-GRID", "S-GRID-IDEN", "S-COLS", "S-BEAM", "S-SLAB", "S-ANNO-IDEN"} <= layers
    assert problems == []
    assert profile_outline({"shape": "rectangle", "xDim": 300, "yDim": 500}) == (
        "polygon", [(-150, -250), (150, -250), (150, 250), (-150, 250)])  # fmt: skip
    grid_only, _ = floor_plan_drawing(layout, objects, "nowhere")
    assert {e["layer"] for e in grid_only} == {"S-GRID", "S-GRID-IDEN"}


def test_member_loads_count_once_recorded_or_once_they_have_a_load():
    """``05 Floor Plan/loads.json`` as a source of the analysis model, as femDerivationBar.ts."""
    from saengine.library.bim import source_stamp

    wall = json.dumps({"loads": [{"id": "L1", "story": "L1", "member": "B1", "value": 10}]})
    none = json.dumps({"loads": []})
    texts = {"bim": "b", "settings": "s", "objects": "o", "materials": "m", "loads": wall}
    sources = "; ".join(f"{k}={source_stamp(v)}" for k, v in list(texts.items())[:4])
    assert R.derivation_state(f"Sources: {sources}", texts) == (True, ["Line Loads"])
    assert R.derivation_state(f"Sources: {sources}", {**texts, "loads": none}) == (True, [])
    assert R.derivation_state(f"Sources: {sources}", {**texts, "loads": None}) == (True, [])
    current = f"Sources: {sources}; loads={source_stamp(wall)}"
    assert R.derivation_state(current, texts) == (True, [])
    assert R.derivation_state(current, {**texts, "loads": none}) == (True, ["Line Loads"])


def test_status_of_a_new_project_is_not_done():
    """K2: a new project's settings and materials hold the defaults, its objects and floor
    plan are empty (``partStatus.test.ts``, "a new project")."""
    from saengine.library.defaults import default_material_library
    from saengine.library.export import library_json
    from saengine.library.settings import default_project_settings

    settings = library_json(default_project_settings())
    settings = {**settings, "project": {"name": "Building"}}
    new = inputs({
        "settings": json.dumps(settings), "materials": json.dumps(library_json(
            default_material_library())), "objects": '{"objects": []}',
        "floorPlan": '{"schema": "saengine.floorPlan/1", "columns": []}', "bim": None,
        "fem": None,
    })  # fmt: skip
    assert lines(new)[1:6] == [
        "settings: defaults defaults",
        "materials: defaults defaults",
        "objects: notStarted not started",
        "floorPlan: notStarted not started",
        "bim: notStarted not built",
    ]
    assert next_step(compute_part_statuses(PROJECT_PARTS, new))[1].part == "settings"
    changed = {**settings, "project": {"name": "Building", "location": "dhaka"}}
    assert lines(inputs({"settings": json.dumps(changed)}))[1] == "settings: done"


def test_part_checks_make_a_part_honest(tmp_path: Path):
    """The part checks file (``checks.json``): problems fail a part, unchecked items keep it in
    progress, checks of a changed file are ignored."""
    from saengine.pipeline.status import (
        PART_CHECKS_FILE,
        apply_part_checks,
        part_checks_file,
        write_part_checks,
    )

    def settings(counts: dict, text: str = SOURCES["settings"]) -> str:
        checks = json.dumps(part_checks_file("settings", counts, {"settings": text}))
        return lines(inputs(checksTexts={"settings": checks}))[1]

    assert settings({"problems": 2, "items": [{"severity": "error", "message": "Z < 0"}]}) == (
        "settings: failed 2 problems"
    )
    assert settings({"problems": 0}) == "settings: done"
    assert settings({"problems": 3}, text="{}") == "settings: done"  # not current: ignored
    objects = json.dumps(
        part_checks_file("objects", {"problems": 0, "checked": 2, "total": 5},
                         {"objects": SOURCES["objects"]})
    )  # fmt: skip
    assert (
        lines(inputs(checksTexts={"objects": objects}))[3] == "objects: inProgress 2 of 5 checked"
    )
    unsupported = part_checks_file("bim", {"problems": 0, "unsupported": 1}, {})
    assert apply_part_checks(
        compute_part_statuses(PROJECT_PARTS, inputs())[5], unsupported
    ).state == ("inProgress")
    # Not started stays not started.
    blank = compute_part_statuses(PROJECT_PARTS, inputs({"objects": '{"objects": []}'}))[3]
    assert apply_part_checks(blank, {"problems": 4}) == blank
    # Written next to the part's main file; the inputs read it back.
    root = tmp_path / "p"
    shutil.copytree(SAMPLE, root)
    project = open_project(root)
    target = write_part_checks(project, "settings", {"problems": 1})
    assert target == root / "02 Project Settings" / PART_CHECKS_FILE
    statuses = {s.part: s for s in R.part_statuses(project)}
    assert statuses["settings"].state == "failed"


def test_report_and_foundations_follow_the_checks():
    """R4: the report is done only once the design passes; U2: skipped foundations are not
    "all pass"."""
    passing = json.dumps({"checked": 13, "passed": 13, "failed": 0})
    failing = json.dumps({"checked": 13, "passed": 10, "failed": 3})
    timing = {"femModelTime": 1, "femResultsTime": 2, "designSummaryTime": 3}
    assert [
        lines(inputs(designSummaryText=passing, reportTime=4, **timing))[10],
        lines(inputs(designSummaryText=failing, reportTime=4, **timing))[10],
        lines(inputs(designSummaryText=passing, reportTime=2.5, **timing))[10],
    ] == [
        "exports: done report day 4",
        "exports: failed report, design fails",
        "exports: stale stale",
    ]
    foundations = json.dumps({"schema": "saengine.substructure/1", "foundations": [{"id": "F1"}]})
    skipped = json.dumps({"foundations": 2, "checked": 1, "passed": 1, "failed": 0, "skipped": 1,
                          "source": {"substructure": source_stamp(foundations)}})  # fmt: skip
    statuses = lines(inputs({"substructure": foundations}, substructureSummaryText=skipped,
                            substructureSummaryTime=3))  # fmt: skip
    assert statuses[8] == "substructure: inProgress 1 not checked"

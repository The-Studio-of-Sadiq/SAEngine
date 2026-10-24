"""The headless pipeline's pieces: the part statuses (a port of partStatus.ts, checked against
its own test cases), the summary files' format, Run All stopping at a failed step, the bill's
line endings and the exports. The full run on the sample is in ``test_pipeline_run_all.py``."""

from __future__ import annotations

import importlib
import json
import shutil
from pathlib import Path

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
    "objects": '{"objects": []}',
    "floorPlan": '{"schema": "saengine.floorPlan/1"}',
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
        "objects: done",
        "floorPlan: done",
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
        "fem: done analysed",
        "fem: stale stale",
        "fem: done 13 pass",
        "fem: failed 3 fail",
        "fem: done analysed",
    ]


def test_status_of_the_bill_the_building_model_and_the_report():
    def line(texts=None, **rest) -> list[str]:
        return lines(inputs(texts, **rest))

    assert [
        line({"boq": BOQ})[9],
        line({"boq": BOQ, "objects": '{"objects": [1]}'})[9],
        line({"boq": "["})[9],
        line({"floorPlan": '{"schema": "saengine.floorPlan/1", "grids": {}}'})[5],
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
        "exports: done report day 42",
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
    assert list(substructure) == ["foundations", "checked", "passed", "failed", "maxUtilisation",
                                  "governing", "computed", "source"]  # fmt: skip
    assert (substructure["failed"], substructure["governing"]) == (1, "F1")


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


def test_run_all_stops_at_a_failed_step(sample: Path, monkeypatch: pytest.MonkeyPatch):
    from saengine.rpc import handlers

    monkeypatch.setattr(
        handlers, "derive_fem", lambda *a, **k: {"problems": ["Building model: bad"]}
    )
    seen: list[str] = []
    result = R.run_all(sample, progress=lambda step, i, n, m: seen.append(step))
    assert [(s.id, s.status) for s in result.steps] == [("derive", "failed")] + [
        (s, "skipped") for s in R.STEP_IDS[1:]
    ]
    assert result.steps[0].message == "Building model: bad"
    assert result.stopped_at == "derive" and not result.ok and seen == ["derive"]
    assert result.summary.startswith("Run All stopped at step 1 of 9 (analysis model)")
    assert result.steps[1].message == "Not run: Run All stopped at analysis model."
    with pytest.raises(ValueError, match="unknown step"):
        R.run_all(sample, steps=["derive", "nope"])
    assert R.normalise_steps(["report,derive"]) == ["derive", "report"]


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

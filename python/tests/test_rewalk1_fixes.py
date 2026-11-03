"""Re-walk 1 (8-storey frame after walkthrough 3's fixes): the fixes of fix track rewalk1.

- Stop Waiting cancels the proposal in the engine (R1-1): ``saengine/cancelJobs`` and the
  cooperative check of :mod:`saengine.rpc.jobs`;
- the design summary records the stamps of the files its checks read, so the part list calls the
  design and the report stale exactly when Run All checks again (R1-2), a ramp override leaving
  them current when the design read no accessibility table;
- one count of the foundations, "n of N", footings without a bearing check counted as such (R1-5,
  R1-17);
- the words of the report and the Code Values page (R1-6, R1-16, R1-18).

No design or analysis number changes here.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

# ─────────────────────────────── R1-1: cancelling a proposal ───────────────────────────────


def test_a_cancelled_job_stops_at_its_next_check_and_answers_an_error() -> None:
    from saengine.rpc import jobs

    job, token = jobs.start("design/proposal")
    other, other_token = jobs.start("design/report")
    try:
        started = threading.Event()
        go_on = threading.Event()
        outcome: dict[str, object] = {}

        def work(_params):
            jobs.check()  # not cancelled yet: goes on
            started.set()
            go_on.wait(5)
            jobs.check()  # cancelled meanwhile: stops here
            outcome["finished"] = True

        def run() -> None:
            try:
                jobs.run_as(job, work, None)
            except jobs.CancelledRequest as error:
                outcome["error"] = str(error)

        thread = threading.Thread(target=run)
        thread.start()
        assert started.wait(5)
        # Only the proposals: the design checks other requests wait for go on.
        assert jobs.cancel(["design/proposal"]) == 1
        go_on.set()
        thread.join(5)
        assert "finished" not in outcome
        assert "Cancelled" in str(outcome["error"])
        assert not other.cancelled
        # A note checks too, and outside a request nothing is ever cancelled.
        jobs.check()
        jobs.note("outside")
    finally:
        # The context's tokens back in the reverse order (the last started first).
        jobs.finish(other, other_token)
        jobs.finish(job, token)
    assert jobs.current() is None


def test_the_server_offers_cancel_jobs_on_its_own_thread() -> None:
    from saengine.rpc.server import create_server

    server = create_server()
    assert "saengine/cancelJobs" in server.protocol.fm.features


# ─────────────────────────────── R1-2: the design's source stamps ───────────────────────────────

SETTINGS = {"project": {"name": "R1"}, "codePack": "bnbc2020", "seismic": {"zone": 2}}


def _texts(settings: dict) -> dict[str, str | None]:
    return {
        "soil": None,
        "settings": json.dumps(settings),
        "materials": '{"materials": []}',
        "objects": '{"objects": []}',
        "bim": '{"elements": []}',
        "substructure": None,
    }


def _summary(out: Path, texts: dict[str, str | None], tables: list[str] | None) -> dict:
    from saengine.pipeline import design_mode

    if tables is not None:
        (out / design_mode.CODE_TABLES_FILE).write_text(json.dumps({"tables": tables}), "utf-8")
    return design_mode.design_source(out, texts)


def test_an_override_of_a_table_the_design_reads_makes_design_and_report_stale(
    tmp_path: Path,
) -> None:
    from saengine.pipeline.status import design_sources_current

    found = _summary(tmp_path, _texts(SETTINGS), ["factors", "seismic"])
    assert found["codeTables"] == ["factors", "seismic"]
    assert found["source"]["soil"] == ""
    assert design_sources_current(_texts(SETTINGS), found)
    # φ shear 0.75 -> 0.7: Run All checks every member again; so does the part list.
    phi = {**SETTINGS, "codeOverrides": {"factors.phi.shear": 0.7}}
    assert not design_sources_current(_texts(phi), found)
    # The bars changed (an Apply): stale too.
    texts = _texts(SETTINGS)
    texts["objects"] = '{"objects": [{"id": "B1"}]}'
    assert not design_sources_current(texts, found)
    # The engineer's name is not a design input (settings_stamp leaves it out).
    named = {**SETTINGS, "project": {"name": "R1", "engineer": "A. Engineer"}}
    assert design_sources_current(_texts(named), found)


def test_a_ramp_override_leaves_the_design_current_only_if_it_read_no_accessibility_table(
    tmp_path: Path,
) -> None:
    from saengine.pipeline.status import design_sources_current

    ramp = {**SETTINGS, "codeOverrides": {"accessibility.ramps.walkway.maxSlope.oneIn": 12}}
    without = tmp_path / "without"
    without.mkdir()
    found = _summary(without, _texts(SETTINGS), ["factors", "seismic"])
    assert design_sources_current(_texts(ramp), found)
    reading = tmp_path / "reading"
    reading.mkdir()
    found = _summary(reading, _texts(SETTINGS), ["accessibility", "factors"])
    assert not design_sources_current(_texts(ramp), found)
    # Before any table was recorded, every override counts.
    unknown = tmp_path / "unknown"
    unknown.mkdir()
    found = _summary(unknown, _texts(SETTINGS), None)
    assert "codeTables" not in found
    assert not design_sources_current(_texts(ramp), found)


def test_the_part_list_marks_design_and_report_stale_after_an_override(tmp_path: Path) -> None:
    from saengine.pipeline import status as S

    found = _summary(tmp_path, _texts(SETTINGS), ["factors"])
    summary = {"checked": 10, "passed": 10, "failed": 0, "maxUtilisation": 0.5, **found}
    summary["counts"] = {"members": {"checked": 10, "failed": 0, "notChecked": 0}}
    phi = {**SETTINGS, "codeOverrides": {"factors.phi.shear": 0.7}}
    inputs = S.StatusInputs(
        texts=_texts(phi),
        designSummaryText=json.dumps(summary),
        designSummaryTime=2000.0,
        femResultsTime=1000.0,
        reportTime=3000.0,
    )
    assert S._design_stale(inputs)
    assert S.design_sources_current(_texts(SETTINGS), summary)


def test_the_design_summary_file_carries_the_source(tmp_path: Path) -> None:
    from saengine.pipeline import design_mode
    from saengine.pipeline import summaries as S

    report = {"summary": {"checked": 1, "passed": 1, "failed": 0, "maxUtilisation": 0.4}}
    texts = _texts(SETTINGS)
    file = S.design_summary_file(design_mode.with_source(report, tmp_path, texts))
    assert set(file["source"]) == {
        "soil",
        "settings",
        "materials",
        "objects",
        "bim",
        "substructure",
    }
    assert "codeTables" not in file  # none recorded yet
    assert "source" not in S.design_summary_file(report)


# ─────────────────────────────── R1-5: one count of the foundations ───────────────────────────────


def _footings(n: int, bearing: bool = True) -> dict:
    return {
        "foundations": [
            {"id": f"F{i}", "ok": True, **({"notChecked": ["bearing"]} if bearing else {})}
            for i in range(n)
        ],
        "tieBeams": [],
        # The building's own checks are not foundations (report 2.1 said "checked 1").
        "retainingWalls": [{"id": "Building", "ok": True}],
        "summary": {"checked": 1, "total": n + 1, "unsupported": []},
    }


def test_footings_without_a_bearing_check_are_counted_as_such_n_of_n() -> None:
    from saengine.pipeline import summaries
    from saengine.pipeline.status import describe_foundation_counts

    ids = [f"F{i}" for i in range(20)]
    counts = summaries.foundation_counts(ids, [], _footings(20))
    assert (counts["total"], counts["checked"], counts["passed"], counts["failed"]) == (20, 0, 0, 0)
    assert len(counts["bearingUnchecked"]) == 20 and counts["notChecked"] == 0
    assert counts["status"] == "incomplete"
    assert describe_foundation_counts(counts) == ["20 of 20 without a bearing check"]
    done = summaries.foundation_counts(ids, [], _footings(20, bearing=False))
    assert describe_foundation_counts(done) == ["all 20 pass"]
    # The summary file counts the same.
    document = {"foundations": [{"id": i} for i in ids], "tieBeams": []}
    file = summaries.substructure_summary_file(document, _footings(20))
    assert (file["checked"], file["total"], len(file["bearingUnchecked"])) == (0, 20, 20)


def test_the_report_counts_the_footings_without_a_bearing_check() -> None:
    from saengine.report.build import design_status

    found = design_status(
        {
            "design": {"available": True, "checked": 579, "failed": 0, "notDesigned": {}},
            "foundations": {
                "available": True, "checked": 0, "failed": 0, "total": 20, "bearingUnchecked": 20,
            },
        }
    )  # fmt: skip
    assert found["state"] == "incomplete"
    assert found["foundationsChecked"] == 0
    assert found["foundationsTotal"] == 20
    assert found["foundationsBearingUnchecked"] == 20
    assert "20 of 20 foundations have no bearing check" in found["headline"]


def test_a_stale_foundation_summary_keeps_its_words_and_its_need_for_qa() -> None:
    from saengine.library.bim import source_stamp
    from saengine.pipeline import status as S

    soil = '{"schema": "saengine.soilReport/1"}'
    document = {
        "schema": S.SUBSTRUCTURE_SCHEMA_ID,
        "foundations": [{"id": f"F{i}"} for i in range(20)],
    }
    summary = {
        "foundations": 20, "checked": 0, "total": 20, "passed": 0, "failed": 0,
        "bearingUnchecked": [f"F{i}" for i in range(20)], "unsupported": [],
        "source": {"soil": source_stamp(soil), "settings": "old"},
    }  # fmt: skip
    inputs = S.StatusInputs(
        texts={"substructure": json.dumps(document), "soil": soil, "settings": "{}"},
        substructureSummaryText=json.dumps(summary),
        substructureSummaryTime=2000.0,
    )
    found = S.substructure_status(inputs)
    # R1-17: a code override made the summary stale; it said "20 foundations" and Overview's
    # Next left the soil report.
    assert found.text == "20 of 20 without a bearing check (stale)"
    assert found.needs == "soil"


# ─────────────────────────────── words ───────────────────────────────


def test_the_overturning_note_never_prints_the_cap_as_a_factor_of_safety() -> None:
    from saengine.substructure import shallow_rules

    found = shallow_rules.overturning_check("D", 0.0, 250.0, 3000.0, 3000.0)
    if found is None:
        pytest.skip("the default pack has no overturning rule")
    assert "99.00" not in found["note"]
    assert "over 99 along X" in found["note"]
    assert "6.00 along Y" in found["note"]


def test_overrides_and_values_have_their_names_and_units() -> None:
    from saengine.codes import context
    from saengine.codes.overrides import browse, words_of

    pack = context.default_pack()
    phi = words_of(pack, "factors.phi.shear")
    assert phi["title"] == "Factors › Phi › Shear"
    assert phi["clause"]
    rows = {r["path"]: r for r in browse(pack, ["areaLoads", "accessibility"])}
    office = rows.get("areaLoads.uses.office.concentrated")
    if office is not None:
        assert office["unit"] == "kN"  # R1-18: "float | None" fields kept no description
    flight = rows.get("accessibility.ramps.walkway.flight.max")
    if flight is not None:
        assert flight["unit"] == "mm"

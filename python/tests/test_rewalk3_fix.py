"""Re-walk 3 (R3) fixes: the walls' ok and classification, one count everywhere, what makes a
part stale, the issue revision. Each number change is pinned here with its clause (the default
pack, BNBC 2020 Part 6)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from test_proposal_anchorage import sample  # noqa: F401 - the Sample Frame's rooms (fixture)

from saengine.design import walls as W
from saengine.design.walls import PierForces, WallBars, WallGeometry

FC, FY, ES = 24.1, 420.0, 200000.0


def test_column_bar_sizes_that_anchor_are_offered_to_the_proposal(sample) -> None:  # noqa: F811
    """R3 misc: Ø20 needs ldh 0.24 fy db / √f'c = 411 mm in F1 (500 - 75 - 2 x 12 = 401 mm);
    the proposal tries the column bar sizes that anchor (concrete.barDiameters.column),
    keeping them when the type still passes, else the note says what to do."""
    from saengine.design import proposal as P
    from saengine.design.required import Options

    entry = {
        "type": "C400x600",
        "kind": "column",
        "members": ["C1"],
        "proposed": {"longitudinal": [{"position": "perimeter", "count": 10, "dia": 20}]},
    }
    opts = Options.of({})
    found = P._column_short(entry, sample.rooms, sample, opts)
    assert found is not None
    db, short, fitting = found
    assert db == 20 and [s[1] for s in short] == ["C1"]
    assert fitting and max(fitting) == 16 and all(d in opts.column_diameters for d in fitting)


# ─────────────────────────────── R3-1: the wall's ok reflects every check ───────────────────────


def test_web_strip_without_axial_force_is_the_slab_strip() -> None:
    """6.6.4 (walls as compression members): the web per metre, its axial force per metre.
    With Pu = 0 a single central curtain of Ø10 @ 125 in 250 mm is the slab strip of R3:
    As = 628.3 mm²/m, d = 125 mm, a = As fy / (0.85 f'c b) = 12.9 mm, φMn = 0.9 As fy (d - a/2)
    = 28.2 kN·m/m (the 28.2 of W1-L1)."""
    geometry = WallGeometry(6000, 250, 13200, 3600)
    bars = WallBars(25, 10, 125, 10, 125, 1)
    mu = 35.3e6 * 6  # 35.3 kN·m/m over 6 m (W1-L1)
    row = W.web_strip_check(geometry, bars, [PierForces("E", 0.0, 0.0, 0.0, 0.0, mu)], FC, FY, ES)
    area = math.pi * 25 * 1000 / 125
    a = area * FY / (0.85 * FC * 1000)
    expected = 0.9 * area * FY * (125 - a / 2) / 1e6
    assert row is not None and not row["flag"]
    assert row["capacity"] == pytest.approx(expected, abs=0.15)  # 28.2 kN·m/m
    assert row["demand"] == pytest.approx(35.3, abs=0.01)
    assert not row["ok"]  # fails, and now counts (it was informative, ok=false, flag=true)


def test_axial_compression_helps_the_web_strip() -> None:
    geometry = WallGeometry(6000, 250, 13200, 3600)
    bars = WallBars(25, 10, 125, 10, 125, 1)
    bare = W.web_strip_check(
        geometry, bars, [PierForces("E", 0.0, 0.0, 0.0, 0.0, 30e6 * 6)], FC, FY, ES
    )
    loaded = W.web_strip_check(
        geometry, bars, [PierForces("E", 300e3 * 6, 0.0, 0.0, 0.0, 30e6 * 6)], FC, FY, ES
    )
    assert loaded["capacity"] > bare["capacity"] + 10  # 300 kN/m of compression


def test_wall_ok_and_utilisation_count_every_design_check() -> None:
    """R3-1: W2-L1 was ok=true at 0.995 beside its out-of-plane bending (2.614) and its
    construction joint (1.098), both ok=false flag=true. Both count now; no informative row is
    ok=false."""
    geometry = WallGeometry(6000, 250, 13200, 3600)
    bars = WallBars(25, 10, 125, 10, 125, 1)
    forces = [
        PierForces("E", 1200e3, 1300e3, 2000e6, 0.0, 73.6e6 * 6, where="P1 bottom"),
        PierForces("E", 1100e3, 1200e3, 1500e6, 0.0, 10e6 * 6, where="P1 middle"),
    ]
    design = W.wall_checks(geometry, bars, forces, FC, FY, ES)
    assert all(c["ok"] for c in design.checks if c["flag"])  # informative: never ok=false
    strip = next(c for c in design.checks if c["name"].startswith("Out-of-plane bending"))
    joint = next(c for c in design.checks if c["name"].startswith("Construction joint"))
    assert not strip["flag"] and not joint["flag"]
    counted = [c for c in design.checks if not c["flag"]]
    assert design.utilisation == max(c["utilisation"] for c in counted)
    assert design.utilisation >= strip["utilisation"] > 1.0


def test_construction_joint_counts_the_end_bars() -> None:
    """Shear friction across the joint (6.4.5.4, Avf fy μ): the end bars cross it too."""
    geometry = WallGeometry(6000, 250, 13200, 3600)
    web = WallBars(25, 10, 125, 10, 125, 1)
    ends = WallBars(25, 10, 125, 10, 125, 1, boundary=W.Boundary(450, 10, 32, 10, 200, 2, 2))
    forces = [PierForces("E", 1200e3, 1304e3, 2000e6, 0.0, 1e6, where="P1 bottom")]
    plain = W._joint_rows(geometry, web, forces, FC, FY)[0]
    with_ends = W._joint_rows(geometry, ends, forces, FC, FY)[0]
    assert with_ends["capacity"] > plain["capacity"]
    assert "10 Ø32 per end over 450 mm" in with_ends["note"]


def test_settle_informative_keeps_the_numbers() -> None:
    rows = [{"name": "x", "ok": False, "flag": True, "note": "", "utilisation": 2.0}]
    W.settle_informative(rows)
    assert rows[0]["ok"] is True and rows[0]["utilisation"] == 2.0
    assert "informative: exceeded" in rows[0]["note"]


# ─────────────────────────────── R3-2: special walls, ρ of the ends ───────────────────────────


def test_end_zone_ratio_is_at_most_a_compression_members() -> None:
    """10 Ø32 over 400 mm of a 250 mm wall is 8.04 % > 8 % (6.6.4 -> 6.3.8.1, the pack's
    concrete.columnRho); 450 mm keeps it within (7.15 %)."""
    row = W.end_ratio_row(W.Boundary(400, 10, 32, 10, 200, 2, 2), 250)
    assert row["demand"] == pytest.approx(100 * 10 * W.bar_area(32) / (400 * 250), abs=0.01)
    assert row["capacity"] == pytest.approx(8.0) and not row["ok"]
    assert W.end_zone_length(10, 32, 250) == 450.0
    assert W.end_ratio_row(W.Boundary(450, 10, 32, 10, 200, 2, 2), 250)["ok"]


def test_two_curtains_rule_is_more_than_250_mm() -> None:
    """6.6.3.4: walls MORE than 250 mm thick have two layers; 250 mm takes one (in special
    walls a second where Vu > 0.17 Acv λ √f'c, 8.3.6.2(b))."""
    forces = [PierForces("E", 0.0, 100e3, 0.0, 0.0, 0.0)]
    assert W.wall_need(WallGeometry(6000, 250, 13200, 3600), forces, FC, FY).layers == 1
    assert W.wall_need(WallGeometry(6000, 260, 13200, 3600), forces, FC, FY).layers == 2
    big = [PierForces("E", 0.0, 0.17 * 6000 * 250 * math.sqrt(FC) * 1.01, 0.0, 0.0, 0.0)]
    special = W.wall_need(WallGeometry(6000, 250, 13200, 3600), big, FC, FY, special=True)
    assert special.layers == 2


def test_structural_walls_are_special_in_category_d() -> None:
    """8.3.2(b): in Category D every RC structure meets 8.3.3-8.3.8 (8.3.6 among them): the
    structural walls of a building declared an RC special moment frame (C.4, no walls in its
    system) are designed as special structural walls, with a note on the system."""
    import test_design_seismic_rules as T

    from saengine.design import seismic_rules as sr
    from saengine.library.bim import BuildingModel
    from saengine.library.objects import ObjectLibrary

    objects = T.objects().model_dump(mode="json")
    objects["objects"].append(
        {"id": "W250", "kind": "wall", "name": "Wall", "material": "C28", "thickness": 250}
    )
    building = T.frame().model_dump(mode="json")
    building["elements"].append(
        {"id": "W1", "kind": "wall", "type": "W250", "start": [0, 0], "end": [0, 6000],
         "bottom": 0, "top": 3000}
    )  # fmt: skip
    lib = ObjectLibrary.model_validate(objects)
    model = BuildingModel.model_validate(building)
    out = sr.seismic_detailing_scope(T.settings("dhaka", "SD"), T.GOOD, lib, model)
    assert out["sdc"] == "D"
    assert out["applies"]["8.3.6"]["applies"]
    assert any("designed as special structural walls" in n for n in out["notes"])
    # Without walls, a moment frame's scope has no 8.3.6.
    bare = sr.seismic_detailing_scope(T.settings("dhaka", "SD"), T.GOOD, T.objects(), T.frame())
    assert not bare["applies"]["8.3.6"]["applies"]


# ─────────────────────────────── counts: one definition everywhere ──────────────────────────────


def test_report_counts_foundations_apart_from_the_retaining_walls() -> None:
    """R3: "6 of 15 foundations or tie beams fail" counted RW1; it is named apart."""
    from saengine.report.build import design_status

    status = design_status(
        {
            "design": {"available": True, "checked": 0, "failed": 0},
            "foundations": {
                "available": True, "checked": 15, "failed": 5, "total": 15,
                "otherFailed": ["RW1"],
            },
        }
    )  # fmt: skip
    assert "5 of 15 foundations or tie beams fail" in status["headline"]
    assert "substructure element(s) RW1 fail" in status["headline"]
    assert status["foundationsFailed"] == 5


def test_drawings_count_the_members_as_the_design_summary() -> None:
    """R3: "158 of 206 members fail" counted the 4 diaphragms; the summary's 202 members."""
    from saengine.pipeline.drawings import check_problems

    elements = [{"id": f"B{i}", "kind": "beam", "ok": i > 2} for i in range(6)]
    elements += [{"id": "B1", "kind": "beam", "ok": False}]  # listed twice
    elements += [{"id": "D1", "kind": "diaphragm", "ok": True}]
    summary = {"counts": {"members": {"total": 6, "checked": 6, "failed": 3}}}
    (line,) = check_problems({}, {"elements": elements, "summary": summary})
    assert line.startswith("Design checks: 3 of 6 members fail (B0, B1, B2)")


# ─────────────────────────────── staleness: the code tables read ──────────────────────────────


SETTINGS = {
    "schema": "saengine.projectSettings/1",
    "codeOverrides": {"planning.rampSlope": 0.1, "foundations.x": 1},
}


def test_code_settings_stamp_leaves_out_tables_not_read() -> None:
    from saengine.fem.derive import code_settings_stamp
    from saengine.library.bim import source_stamp

    text = json.dumps(SETTINGS)
    ramp = json.dumps(
        {**SETTINGS, "codeOverrides": {**SETTINGS["codeOverrides"], "planning.rampSlope": 0.08}}
    )
    tables = frozenset({"foundations"})
    assert code_settings_stamp(text, tables) == code_settings_stamp(ramp, tables)
    assert code_settings_stamp(text, frozenset({"planning", "foundations"})) == source_stamp(text)
    founded = json.dumps(
        {**SETTINGS, "codeOverrides": {**SETTINGS["codeOverrides"], "foundations.x": 2}}
    )
    assert code_settings_stamp(founded, tables) != code_settings_stamp(text, tables)


def test_sources_with_code_tables_stay_current_on_a_ramp_slope() -> None:
    from saengine.fem.derive import code_settings_stamp
    from saengine.pipeline.status import _sources_unchanged

    text = json.dumps(SETTINGS)
    source = {
        "settings": code_settings_stamp(text, frozenset({"foundations"})),
        "codeTables": "foundations",
    }
    ramp = json.dumps(
        {**SETTINGS, "codeOverrides": {**SETTINGS["codeOverrides"], "planning.rampSlope": 0.08}}
    )
    assert _sources_unchanged({"settings": ramp}, source)
    founded = json.dumps(
        {**SETTINGS, "codeOverrides": {**SETTINGS["codeOverrides"], "foundations.x": 2}}
    )
    assert not _sources_unchanged({"settings": founded}, source)
    # A source without codeTables: every change counts, as before.
    from saengine.library.bim import source_stamp

    assert not _sources_unchanged({"settings": ramp}, {"settings": source_stamp(text)})


def test_substructure_sources_record_the_tables(tmp_path: Path) -> None:
    from saengine.rpc.handlers import substructure_sources

    folder = tmp_path / "02 Project Settings"
    folder.mkdir()
    (folder / "project-settings.json").write_text(json.dumps(SETTINGS), encoding="utf-8")
    sources = substructure_sources(str(tmp_path), {"foundations"})
    assert sources["codeTables"] == "foundations"
    from saengine.pipeline.status import _sources_unchanged

    ramp = {**SETTINGS, "codeOverrides": {**SETTINGS["codeOverrides"], "planning.rampSlope": 0.08}}
    texts = {p: None for p in sources if p != "codeTables"}
    texts["settings"] = json.dumps(ramp)
    assert _sources_unchanged(texts, sources)


def test_drawings_stamps_with_the_tables(tmp_path: Path) -> None:
    from saengine.pipeline.drawings import changed_sources, input_stamps

    folder = tmp_path / "02 Project Settings"
    folder.mkdir()
    path = folder / "project-settings.json"
    path.write_text(json.dumps(SETTINGS), encoding="utf-8")
    recorded = input_stamps(tmp_path, frozenset({"foundations"}))
    ramp = {**SETTINGS, "codeOverrides": {**SETTINGS["codeOverrides"], "planning.rampSlope": 0.08}}
    path.write_text(json.dumps(ramp), encoding="utf-8")
    assert changed_sources(recorded, input_stamps(tmp_path, frozenset({"foundations"}))) == []
    assert changed_sources(recorded, input_stamps(tmp_path)) == ["Project Settings"]


def test_kept_results_keep_the_design_current(tmp_path: Path) -> None:
    """R3-4: Run All's "results current" writes the manifest again; design checks made on
    those results are written again after it, so the part list does not say "analysed"."""
    import importlib
    import os

    run_all = importlib.import_module("saengine.pipeline.run_all")

    model = tmp_path / "08 FEM" / "model.osmodel"
    out = run_all.results_folder(model)
    out.mkdir(parents=True)
    manifest, summary = out / "manifest.json", out / "design-summary.json"
    manifest.write_text("{}", "utf-8")
    summary.write_text("{}", "utf-8")
    os.utime(manifest, (100, 100))
    os.utime(summary, (200, 200))
    model.write_text("{}", "utf-8")
    run_all.keep_analysis_inputs(model)

    class Step:
        def __init__(self) -> None:
            self.status = self.message = ""
            self.outputs: list = []

    class Project:
        def file(self, _part):
            return model

        root = tmp_path

    run_all._analysis(Project(), Step(), lambda _m: None)  # type: ignore[arg-type]
    assert summary.stat().st_mtime >= manifest.stat().st_mtime


# ─────────────────────────────── the issue revision ──────────────────────────────


def test_pending_revision_is_the_latest_row_not_issued() -> None:
    from saengine.drawings.sheets import revisions as rv

    register = rv.Register()
    # R3: rows 0 (an earlier date) and 1 (today), none issued: the title blocks show 1.
    assert register.pending_code("1", ["0", "1"]) == "1"
    register.issues.append(rv.Issue("0", "2026-11-03", "", "", "For construction"))
    assert register.pending_code("1", ["0", "1"]) == "1"


def test_issue_revision_through_the_rpc(tmp_path: Path) -> None:
    """End to end: drawings/list's register offers revision 1 of Project Settings."""
    from saengine.pipeline.drawings import FOLDER, RECORD, SCHEMA_ID
    from saengine.rpc import handlers

    settings = tmp_path / "02 Project Settings"
    settings.mkdir()
    (settings / "project-settings.json").write_text(
        json.dumps(
            {
                "schema": "saengine.projectSettings/1",
                "drawings": {
                    "revisions": [
                        {"code": "0", "date": "2026-10-23", "description": "First issue"},
                        {"code": "1", "date": "2026-11-03", "description": "For construction"},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    drawings = tmp_path / FOLDER
    drawings.mkdir(parents=True)
    (drawings / RECORD).write_text(json.dumps({"schema": SCHEMA_ID, "sheets": []}), "utf-8")
    listed = handlers.drawings_list(str(tmp_path))
    assert listed["register"]["pending"] == "1"

"""Issue #280: the actions the catalogue lacked (load patterns, grid systems, end releases and
point springs, every Run All step alone), undo and redo of written batches, and the terminal's
``saengine <noun> <verb>`` commands made from the catalogue."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saengine.actions import run_actions
from saengine.actions.journal import JOURNAL
from saengine.actions.paths import BIM, LOADS, SETTINGS
from saengine.actions.paths import FLOOR_PLAN as PLAN
from saengine.cli import main, verbs


def _ok(root: Path, *steps: tuple[str, dict], write: bool = True):
    result = run_actions(root, [{"action": a, "params": p} for a, p in steps], write=write)
    assert result.ok, [f"{r.action}: {r.message}" for r in result.results]
    return result


def _refused(root: Path, action: str, params: dict) -> str:
    result = run_actions(root, [{"action": action, "params": params}])
    assert not result.ok
    return result.results[-1].message


def _json(root: Path, path: Path) -> dict:
    return json.loads((root / path).read_text(encoding="utf-8"))


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "P"
    _ok(
        root,
        ("project.create", {"name": "P"}),
        ("grid.set", {"x": [5000, 5000], "y": [4000]}),
        ("storeys.set", {"count": 2, "height": 3000}),
        ("type.column.add", {"id": "C400", "width": 400, "depth": 400}),
        ("type.beam.add", {"id": "B300", "width": 300, "depth": 500}),
        ("columns.place", {"type": "C400"}),
        ("beams.place", {"type": "B300"}),
    )
    return root


# ── load patterns ──


def test_load_patterns_add_use_rename_delete(project: Path):
    _ok(project, ("load.pattern.add", {"id": "EQP", "name": "Equipment", "type": "Dead"}))
    patterns = _json(project, SETTINGS)["loadPatterns"]
    assert patterns == [{"id": "EQP", "name": "Equipment", "type": "Dead", "selfWeight": 0}]
    assert "D, SD, L, Lr" in _refused(project, "load.pattern.add", {"id": "L"})
    assert "already" in _refused(project, "load.pattern.add", {"id": "EQP"})
    # Member loads and the area loads' other load go to the project's patterns.
    _ok(
        project,
        ("load.line.add", {"beams": ["B1"], "value": 4, "case": "EQP"}),
        ("load.area.set", {"id": "FL", "otherLoad": 1.2, "otherPattern": "EQP"}),
    )
    assert "no load pattern 'XYZ'" in _refused(
        project, "load.line.add", {"beams": ["B1"], "value": 4, "case": "XYZ"}
    )
    # A rename follows into the loads and the area loads.
    _ok(project, ("load.pattern.set", {"id": "EQP", "newId": "EQ2", "selfWeight": 0.5}))
    assert _json(project, LOADS)["loads"][0]["case"] == "EQ2"
    area = next(a for a in _json(project, SETTINGS)["areaLoads"] if a["id"] == "FL")
    assert area["otherPattern"] == "EQ2"
    # Used patterns are deleted only with their loads.
    assert "deleteLoads" in _refused(project, "load.pattern.delete", {"id": "EQ2"})
    _ok(project, ("load.pattern.delete", {"id": "EQ2", "deleteLoads": True}))
    settings = _json(project, SETTINGS)
    assert "loadPatterns" not in settings
    assert not _json(project, LOADS)["loads"]
    assert "otherPattern" not in next(a for a in settings["areaLoads"] if a["id"] == "FL")


def test_member_loads_set_and_delete(project: Path):
    _ok(project, ("load.line.add", {"beams": ["B1", "B2"], "value": 4}))
    _ok(project, ("load.set", {"ids": ["LL1"], "value": 6, "case": "L"}))
    loads = {x["id"]: x for x in _json(project, LOADS)["loads"]}
    assert (loads["LL1"]["value"], loads["LL1"]["case"]) == (6, "L")
    assert "not a point load" in _refused(project, "load.set", {"ids": ["LL1"], "distance": 5})
    assert "no member load" in _refused(project, "load.delete", {"ids": ["LL9"]})
    _ok(project, ("load.delete", {"ids": ["LL1"]}))
    assert [x["id"] for x in _json(project, LOADS)["loads"]] == ["LL2"]


# ── grid systems ──


def test_grid_systems(project: Path):
    _ok(
        project,
        (
            "grid.system.add",
            {
                "kind": "radial",
                "originX": 0,
                "originY": 0,
                "rays": [{"label": "R1", "angle": 0}, {"label": "R2", "angle": 90}],
                "rings": [{"label": "K1", "radius": 8000}],
            },
        ),
    )
    systems = _json(project, PLAN)["grids"]["systems"]
    assert [s["id"] for s in systems] == ["GS1"] and systems[0]["kind"] == "radial"
    # Labels are unique across every system (the floor plan model's rule).
    assert "unique" in _refused(
        project,
        "grid.system.add",
        {"kind": "lines", "lines": [{"label": "A", "x1": 0, "y1": 0, "angle": 30}]},
    )
    # A column on the system's lines keeps a line from going.
    _ok(project, ("columns.place", {"type": "C400", "points": ["R1-K1"], "storeys": ["L1"]}))
    assert "R1" in _refused(project, "grid.system.set", {"id": "GS1", "rays": []})
    _ok(project, ("grid.system.set", {"id": "GS1", "angle": 10, "name": "Wing"}))
    assert _json(project, PLAN)["grids"]["systems"][0]["angle"] == 10
    assert "deleteMembers" in _refused(project, "grid.system.delete", {"id": "GS1"})
    _ok(project, ("grid.system.delete", {"id": "GS1", "deleteMembers": True}))
    assert "systems" not in _json(project, PLAN)["grids"]


# ── end releases and point springs ──


def test_releases_and_springs_need_the_building_model(project: Path):
    assert "building model" in _refused(
        project, "release.set", {"members": ["B1"], "preset": "pinned"}
    )
    _ok(project, ("run.step", {"step": "bim"}))
    bim_path = project / BIM
    bim = json.loads(bim_path.read_text(encoding="utf-8"))
    beam = next(e["id"] for e in bim["elements"] if e.get("kind") == "beam")
    _ok(project, ("release.set", {"members": [beam], "preset": "pinned"}))
    _ok(project, ("spring.set", {"at": [0, 0, 0], "UZ": 50000, "support": "pinned"}))
    # A change merges into what the member or joint has (as the Properties panel sends it).
    _ok(
        project,
        ("release.set", {"members": [beam], "end": {"M3": None, "T": 2000}}),
        ("spring.set", {"at": [0.4, 0, 0], "UX": 100}),
    )
    additions = json.loads(bim_path.read_text(encoding="utf-8"))["additions"]
    assert additions["endReleases"][0]["start"] == {"M2": 0.0, "M3": 0.0}
    assert additions["endReleases"][0]["end"] == {"T": 2000.0, "M2": 0.0}
    assert additions["pointSprings"] == [
        {"id": "PS1", "at": [0, 0, 0], "UZ": 50000.0, "support": "pinned", "UX": 100.0}
    ]
    _ok(project, ("spring.set", {"at": [0, 0, 0], "UZ": 0, "UX": None, "support": "none"}))
    assert not json.loads(bim_path.read_text(encoding="utf-8"))["additions"]["pointSprings"]
    _ok(project, ("spring.set", {"at": [0, 0, 0], "UZ": 1}))
    # A member that would slide along its axis is refused (the model's mechanism check).
    assert "P is released at both ends" in _refused(
        project, "release.set", {"members": [beam], "start": ["P"], "end": ["P"]}
    )
    assert "no beam, column or member" in _refused(
        project, "release.set", {"members": ["NOPE"], "preset": "pinned"}
    )
    _ok(project, ("release.set", {"members": [beam], "preset": "fixed"}))
    _ok(project, ("spring.delete", {"ids": ["PS1"]}))
    additions = json.loads(bim_path.read_text(encoding="utf-8"))["additions"]
    assert not additions["endReleases"] and not additions["pointSprings"]


# ── Run All steps ──


def test_run_step_takes_any_step_of_run_all(project: Path):
    assert "Give a step" in _refused(project, "run.step", {})
    assert "Not steps of Run All" in _refused(project, "run.step", {"steps": ["nope"]})
    result = _ok(project, ("run.step", {"steps": ["bim"]}))
    steps = {s["id"]: s["status"] for s in result.results[0].data["steps"]}
    assert steps["bim"] in ("ok", "warning")


# ── undo and redo ──


def test_undo_redo_of_written_batches(project: Path):
    before = (project / PLAN).read_text(encoding="utf-8")
    _ok(project, ("grid.line.add", {"axis": "x", "position": 15000}))
    after = (project / PLAN).read_text(encoding="utf-8")
    assert after != before
    _ok(project, ("edit.undo", {}))
    assert (project / PLAN).read_text(encoding="utf-8") == before
    _ok(project, ("edit.redo", {}))
    assert (project / PLAN).read_text(encoding="utf-8") == after
    history = _ok(project, ("edit.history", {})).results[0].data
    assert history["undo"][0]["label"] == "grid.line.add" and not history["redo"]
    # A file changed since is not overwritten unless forced.
    (project / PLAN).write_text(after.replace("15000", "16000"), encoding="utf-8")
    assert "Changed since" in _refused(project, "edit.undo", {})
    _ok(project, ("edit.undo", {"force": True}))
    assert (project / PLAN).read_text(encoding="utf-8") == before
    # A dry run records nothing; the journal is never versioned or archived.
    undo = _ok(project, ("edit.history", {})).results[0].data["undo"]
    run_actions(project, [{"action": "grid.line.add", "params": {"axis": "x", "position": 1}}])
    assert _ok(project, ("edit.history", {})).results[0].data["undo"] == undo
    from saengine.project import archive

    assert archive._is_junk(JOURNAL)


# ── the terminal ──


def test_terminal_words_map_to_actions():
    commands = verbs.tree()
    assert commands[("load", "pattern", "add")] == "load.pattern.add"
    assert commands[("member", "add", "column")] == "columns.place"
    assert commands[("design", "apply")] == "design.reinforcement.apply"
    assert commands[("run", "all")] == "run.all"
    assert commands[("undo",)] == "edit.undo"
    assert verbs.handles(["load", "pattern", "add", "X"])
    # The classic commands keep their words: "design <project>" is the design step.
    assert not verbs.handles(["design", "my-project"])
    assert not verbs.handles(["export", "proj", "--format", "ifc"])
    assert not verbs.handles(["run-all", "proj"])
    assert not verbs.handles(["versions", "list", "proj"])


def test_terminal_values():
    number = {"type": "number"}
    text = {"type": "string"}
    labels = {"type": "array", "items": {"type": "string"}}
    storeys = {"anyOf": [{"const": "all", "type": "string"}, labels]}
    assert verbs._convert("12.5", number) == 12.5
    assert verbs._convert("1", text) == "1"
    assert verbs._convert(["B1", "B2"], labels) == ["B1", "B2"]
    assert verbs._convert(["B1"], labels) == ["B1"]
    assert verbs._convert(["all"], storeys) == "all"
    assert verbs._convert(["L1"], storeys) == ["L1"]
    assert verbs._convert(["[1, 2]"], {"type": "array", "items": number}) == [1, 2]


def test_terminal_group_help_and_json(tmp_path: Path, capsys):
    assert main(["load"]) == 2
    assert "load pattern add" in capsys.readouterr().out
    root = tmp_path / "T"
    assert main(["project", "create", "--name", "T", "--project", str(root)]) == 0
    capsys.readouterr()
    code = main(
        ["load", "pattern", "add", "EQP", "--type", "Dead", "--project", str(root), "--json"]
    )
    document = json.loads(capsys.readouterr().out)
    assert code == 0 and document["command"] == "load pattern add"
    assert document["batch"]["results"][0]["created"] == ["EQP"]
    assert main(["load", "pattern", "add", "D", "--project", str(root)]) == 1

"""The Revit link's exchange file: written from a project, read back with a change preview, and
the picked changes applied to the floor plan."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from saengine.exporters import revit_link
from saengine.library.floorplan import FloorPlan

SAMPLE = (
    Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    return root


def exported(project: Path) -> tuple[Path, dict[str, Any]]:
    answer = revit_link.rpc_export({"projectRoot": str(project)})
    path = Path(answer["path"])
    return path, json.loads(path.read_text("utf-8"))


def write_back(project: Path, document: dict[str, Any]) -> Path:
    document = copy.deepcopy(document)
    document["origin"] = {"application": "Revit", "version": "2027"}
    path = project / "from-revit.exchange.json"
    path.write_text(json.dumps(document), "utf-8")
    return path


def test_export_writes_the_exchange_file(project: Path) -> None:
    path, document = exported(project)
    assert path == project / "11 Exports" / "Revit" / "Sample Frame.exchange.json"
    assert document["schema"] == revit_link.SCHEMA_ID
    assert document["units"]["length"] == "mm"
    kinds = {e["kind"] for e in document["elements"]}
    assert {"column", "beam", "slab"} <= kinds
    sections = {s["id"] for s in document["sections"]}
    assert all(e["section"] in sections for e in document["elements"])
    columns = [e for e in document["elements"] if e["kind"] == "column"]
    assert all(c["curve"][0][2] < c["curve"][1][2] for c in columns)  # bottom to top
    assert (project / "11 Exports" / "Revit" / revit_link.LINK_FILE).exists()


def test_the_file_as_exported_has_no_changes(project: Path) -> None:
    path, _ = exported(project)
    preview = revit_link.rpc_preview({"projectRoot": str(project), "path": str(path)})
    assert preview["changes"] == []


def test_preview_lists_moves_additions_and_deletions(project: Path) -> None:
    _, document = exported(project)
    columns = [e for e in document["elements"] if e["kind"] == "column"]
    beams = [e for e in document["elements"] if e["kind"] == "beam"]
    moved = columns[0]
    for point in moved["curve"]:
        point[0] += 250
    moved["revitId"] = "rvt-col"
    document["elements"].remove(beams[0])
    new = copy.deepcopy(beams[1])
    new.pop("id")
    new["revitId"] = "rvt-new"
    for point in new["curve"]:
        point[1] += 1000
    document["elements"].append(new)
    path = write_back(project, document)
    preview = revit_link.rpc_preview({"projectRoot": str(project), "path": str(path)})
    by_id = {c["id"]: c for c in preview["changes"]}
    assert set(by_id) == {
        f"element:modify:{moved['id']}",
        f"element:remove:{beams[0]['id']}",
        "element:add:rvt-new",
    }
    assert all(c["applicable"] for c in preview["changes"])
    assert by_id[f"element:modify:{moved['id']}"]["details"][0]["field"] == "location"


def test_apply_changes_the_floor_plan_and_keeps_a_copy(project: Path) -> None:
    _, document = exported(project)
    column = next(e for e in document["elements"] if e["kind"] == "column")
    for point in column["curve"]:
        point[0] += 250
    path = write_back(project, document)
    preview = revit_link.rpc_preview({"projectRoot": str(project), "path": str(path)})
    answer = revit_link.rpc_apply(
        {"projectRoot": str(project), "path": str(path), "changes": [preview["changes"][0]["id"]]}
    )
    assert answer["applied"] == [preview["changes"][0]["id"]] and answer["failed"] == []
    assert Path(answer["backupPath"]).exists()
    plan = FloorPlan.model_validate_json(
        (project / "05 Floor Plan" / "floor-plan.json").read_text("utf-8")
    )
    xs = {g.label: g.position for g in plan.grids.x}
    placed = next(c for c in plan.columns if c.id == column["id"])
    assert xs[placed.at.x] + placed.at.dx == pytest.approx(column["curve"][0][0])
    # Nothing is left to take back.
    again = revit_link.rpc_preview({"projectRoot": str(project), "path": str(path)})
    assert again["changes"] == []


def test_a_moved_grid_line_leaves_the_members_where_they_are(project: Path) -> None:
    _, document = exported(project)
    grid = document["grids"][0]
    grid["start"][0 if grid["axis"] == "x" else 1] += 100
    grid["end"][0 if grid["axis"] == "x" else 1] += 100
    path = write_back(project, document)
    preview = revit_link.rpc_preview({"projectRoot": str(project), "path": str(path)})
    assert [c["id"] for c in preview["changes"]] == [f"grid:modify:{grid['id']}"]
    revit_link.rpc_apply(
        {"projectRoot": str(project), "path": str(path), "changes": [preview["changes"][0]["id"]]}
    )
    again = revit_link.rpc_preview({"projectRoot": str(project), "path": str(path)})
    assert again["changes"] == []  # the grid moved, the members did not


def test_sloped_beams_and_unknown_sections_are_not_applicable(project: Path) -> None:
    _, document = exported(project)
    beams = [e for e in document["elements"] if e["kind"] == "beam"]
    beams[0]["curve"][1][2] += 600
    beams[1]["section"] = "W999"
    document["sections"].append({"id": "W999", "name": "Nothing like it", "kind": "beam"})
    path = write_back(project, document)
    preview = revit_link.rpc_preview({"projectRoot": str(project), "path": str(path)})
    by_ref = {c["ref"]: c for c in preview["changes"]}
    assert not by_ref[beams[0]["id"]]["applicable"]
    assert "sloped" in by_ref[beams[0]["id"]]["reason"]
    assert not by_ref[beams[1]["id"]]["applicable"]
    assert "04 Objects" in by_ref[beams[1]["id"]]["reason"]


def test_reinforcement_is_reported_not_taken_back(project: Path) -> None:
    _, document = exported(project)
    document["rebar"] = [{"id": "rebar:C1/0", "host": "C1", "dia": 20, "lines": []}]
    path = write_back(project, document)
    preview = revit_link.rpc_preview({"projectRoot": str(project), "path": str(path)})
    assert preview["changes"] == []
    assert any("not taken back" in n for n in preview["notes"])


def test_a_file_of_another_kind_is_refused(project: Path, tmp_path: Path) -> None:
    other = tmp_path / "other.json"
    other.write_text('{"schema": "something/1"}', "utf-8")
    answer = revit_link.rpc_preview({"projectRoot": str(project), "path": str(other)})
    assert set(answer) == {"error"}

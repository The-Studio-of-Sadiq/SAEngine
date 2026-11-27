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


def test_radial_grid_rings_export_as_revit_arcs_and_roundtrip(project: Path) -> None:
    plan_path = project / "05 Floor Plan" / "floor-plan.json"
    plan = json.loads(plan_path.read_text("utf-8"))
    plan["grids"]["systems"] = [
        {
            "id": "RAD",
            "kind": "radial",
            "originX": 10000,
            "originY": 5000,
            "angle": 0,
            "rays": [
                {"label": "R0", "angle": 0},
                {"label": "R45", "angle": 45},
                {"label": "R90", "angle": 90},
            ],
            "rings": [
                {"label": "R1", "radius": 6000},
                {"label": "R2", "radius": 9000},
            ],
        },
        {
            "id": "FULL",
            "kind": "radial",
            "originX": 0,
            "originY": 0,
            "angle": 0,
            "rays": [],
            "rings": [{"label": "F1", "radius": 4000}],
        },
    ]
    plan_path.write_text(json.dumps(plan), "utf-8")

    path, document = exported(project)
    assert not any("not exported" in n for n in document["notes"])

    by_name = {g["name"]: g for g in document["grids"]}
    # Rays at 0°, 45°, 90°: widest gap is 270° (90° → 360°), so arc runs 0° → 90° extended ±5°
    # to -5° → 95°. cos(5°) = 0.9961947, sin(5°) = 0.0871557.
    # R1 (r = 6000, centre (10000, 5000)):
    #   start (-5°): (10000 + 5977.168, 5000 - 522.934) = [15977.2, 4477.1]
    #   end   (95°): (10000 - 522.934, 5000 + 5977.168) = [9477.1, 10977.2]
    # R2 (r = 9000, centre (10000, 5000)):
    #   start (-5°): (10000 + 8965.752, 5000 - 784.402) = [18965.8, 4215.6]
    #   end   (95°): (10000 - 784.402, 5000 + 8965.752) = [9215.6, 13965.8]
    r1, r2 = by_name["R1"], by_name["R2"]
    assert r1["axis"] is None and r1["position"] is None
    assert r1["arc"] == {
        "center": [10000.0, 5000.0],
        "radius": 6000.0,
        "startAngle": -5.0,
        "endAngle": 95.0,
    }
    assert r1["start"] == pytest.approx([15977.2, 4477.1], abs=0.1)
    assert r1["end"] == pytest.approx([9477.1, 10977.2], abs=0.1)

    assert r2["axis"] is None and r2["position"] is None
    assert r2["arc"] == {
        "center": [10000.0, 5000.0],
        "radius": 9000.0,
        "startAngle": -5.0,
        "endAngle": 95.0,
    }
    assert r2["start"] == pytest.approx([18965.8, 4215.6], abs=0.1)
    assert r2["end"] == pytest.approx([9215.6, 13965.8], abs=0.1)

    # No rays: 350° arc with a 10° gap centred on bubble_angle (-90°) -> -85° to 265°.
    f1 = by_name["F1"]
    assert f1["arc"] == {
        "center": [0.0, 0.0],
        "radius": 4000.0,
        "startAngle": -85.0,
        "endAngle": 265.0,
    }

    # Unchanged export produces no import changes.
    assert revit_link.rpc_preview({"projectRoot": str(project), "path": str(path)})["changes"] == []

    # Moved arc ring and new symmetric arc grid coming back from Revit: reported as non-applicable
    # ("edit in Grid Systems"), never misclassified as straight grids and never crashing.
    edited = copy.deepcopy(document)
    next(g for g in edited["grids"] if g["name"] == "R1")["arc"]["radius"] = 6500.0
    edited["grids"].append(
        {
            "name": "RVT_ARC",
            "revitId": "rvt-arc-1",
            "start": [348.6, -3984.8],
            "end": [-348.6, -3984.8],
            "arc": {"center": [0.0, 0.0], "radius": 4000.0, "startAngle": -85.0, "endAngle": 265.0},
        }
    )
    back = write_back(project, edited)
    preview = revit_link.rpc_preview({"projectRoot": str(project), "path": str(back)})
    by_ref = {c["ref"]: c for c in preview["changes"]}
    assert set(by_ref) == {"RAD:R1", "RVT_ARC"}
    assert not by_ref["RAD:R1"]["applicable"]
    assert "Grid Systems" in by_ref["RAD:R1"]["reason"]
    assert not by_ref["RVT_ARC"]["applicable"]
    assert "Grid Systems" in by_ref["RVT_ARC"]["reason"]

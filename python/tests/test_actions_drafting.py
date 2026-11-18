"""Tests for floor plan drafting actions: drafting.add, drafting.delete, drafting.list, drafting.migrate."""

from __future__ import annotations

import json
from pathlib import Path

import ezdxf
import pytest

from saengine.actions import run_actions
from saengine.library.drafting_dxf import new_document
from saengine.library.drafting_dxf import write as write_dxf

BASE_STEPS = [
    {"action": "project.create", "params": {"name": "Base"}},
    {"action": "grid.set", "params": {"x": [5000, 5000], "y": [4000]}},
    {"action": "storeys.set", "params": {"count": 2, "height": 3000}},
]


@pytest.fixture
def project_path(tmp_path: Path) -> Path:
    root = tmp_path / "Base"
    result = run_actions(root, BASE_STEPS, write=True)
    assert result.ok, [r.message for r in result.results]
    return root


def test_drafting_add_list_delete(project_path: Path) -> None:
    # 1. Add a line and a closed polyline
    res = run_actions(
        project_path,
        [
            {
                "action": "drafting.add",
                "params": {
                    "shapes": [
                        {
                            "kind": "line",
                            "story": "L1",
                            "start": [0, 0],
                            "end": [5000, 0],
                        },
                        {
                            "kind": "polyline",
                            "story": "L1",
                            "points": [[0, 0], [5000, 0], [5000, 4000]],
                            "closed": True,
                        },
                    ]
                },
            }
        ],
        write=True,
    )
    assert res.ok
    assert len(res.results[0].created) == 2
    line_id, poly_id = res.results[0].created
    assert line_id and poly_id
    assert f"Added {line_id}, {poly_id}." in res.results[0].message

    # Verify DXF was written to 05 Floor Plan/drafting/L1.dxf
    dxf_file = project_path / "05 Floor Plan" / "drafting" / "L1.dxf"
    assert dxf_file.exists()
    doc = ezdxf.readfile(str(dxf_file))
    msp = doc.modelspace()
    handles = [e.dxf.handle for e in msp]
    assert line_id in handles
    assert poly_id in handles

    # 2. List them
    list_all = run_actions(project_path, [{"action": "drafting.list", "params": {}}])
    assert list_all.ok
    assert len(list_all.results[0].data) == 2
    assert [d["id"] for d in list_all.results[0].data] == [line_id, poly_id]

    # List by story
    list_l1 = run_actions(project_path, [{"action": "drafting.list", "params": {"story": "L1"}}])
    assert list_l1.ok
    assert len(list_l1.results[0].data) == 2

    list_l2 = run_actions(project_path, [{"action": "drafting.list", "params": {"story": "L2"}}])
    assert list_l2.ok
    assert len(list_l2.results[0].data) == 0

    # 3. Delete one
    del_res = run_actions(
        project_path,
        [{"action": "drafting.delete", "params": {"ids": [line_id], "story": "L1"}}],
        write=True,
    )
    assert del_res.ok
    assert f"Deleted {line_id}." in del_res.results[0].message

    # Verify list only has the remaining polyline
    list_after = run_actions(project_path, [{"action": "drafting.list", "params": {}}])
    assert list_after.ok
    assert [d["id"] for d in list_after.results[0].data] == [poly_id]


def test_drafting_refusal_unknown_story_and_id(project_path: Path) -> None:
    # Refusal for unknown story
    res_story = run_actions(
        project_path,
        [
            {
                "action": "drafting.add",
                "params": {
                    "shapes": [
                        {
                            "kind": "line",
                            "story": "L99",
                            "start": [0, 0],
                            "end": [5000, 0],
                        }
                    ]
                },
            }
        ],
    )
    assert not res_story.ok
    assert "no storey 'L99'" in res_story.results[0].message

    # Refusal for bad geometry (closed polyline with only 2 points)
    res_geom = run_actions(
        project_path,
        [
            {
                "action": "drafting.add",
                "params": {
                    "shapes": [
                        {
                            "kind": "polyline",
                            "story": "L1",
                            "points": [[0, 0], [5000, 0]],
                            "closed": True,
                        }
                    ]
                },
            }
        ],
    )
    assert not res_geom.ok
    assert "closed polyline needs at least 3 points" in res_geom.results[0].message

    # Refusal for unknown story in delete
    res_del_story = run_actions(
        project_path,
        [{"action": "drafting.delete", "params": {"ids": ["D999"], "story": "L99"}}],
    )
    assert not res_del_story.ok
    assert "no storey 'L99'" in res_del_story.results[0].message

    # Refusal for unknown id in delete
    res_id = run_actions(
        project_path,
        [{"action": "drafting.delete", "params": {"ids": ["D999"], "story": "L1"}}],
    )
    assert not res_id.ok
    assert "D999" in res_id.results[0].message


def test_draft_line_to_beam_batch(project_path: Path) -> None:
    # Add a drafted line first
    add_res = run_actions(
        project_path,
        [
            {
                "action": "drafting.add",
                "params": {
                    "shapes": [
                        {
                            "kind": "line",
                            "story": "L1",
                            "start": [0, 0],
                            "end": [5000, 0],
                        }
                    ]
                },
            }
        ],
        write=True,
    )
    assert add_res.ok
    line_id = add_res.results[0].created[0]

    # Convert drafted line to beam in one batch:
    # [beams.place with offset points {x,y,dx,dy} between two drafted line ends, drafting.delete the line]
    batch = run_actions(
        project_path,
        [
            {
                "action": "beams.place",
                "params": {
                    "type": "B250x450",
                    "between": [
                        [
                            {"x": "A", "y": "1", "dx": 0, "dy": 0},
                            {"x": "A", "y": "1", "dx": 5000, "dy": 0},
                        ]
                    ],
                    "storeys": ["L1"],
                },
            },
            {
                "action": "drafting.delete",
                "params": {"ids": [line_id], "story": "L1"},
            },
        ],
        write=True,
    )
    assert batch.ok
    assert len(batch.results) == 2
    assert len(batch.results[0].created) == 1
    beam_id = batch.results[0].created[0]
    assert beam_id.startswith("B")
    assert f"Deleted {line_id}." in batch.results[1].message

    # Verify line is deleted and beam is present
    drafts = run_actions(project_path, [{"action": "drafting.list", "params": {}}])
    assert drafts.ok
    assert not any(d["id"] == line_id for d in drafts.results[0].data)

    members = run_actions(
        project_path,
        [{"action": "members.list", "params": {"group": "beams", "storey": "L1"}}],
    )
    assert members.ok
    assert any(m["id"] == beam_id for m in members.results[0].data)


def test_drafting_arc_circle(project_path: Path) -> None:
    res = run_actions(
        project_path,
        [
            {
                "action": "drafting.add",
                "params": {
                    "shapes": [
                        {
                            "kind": "arc",
                            "story": "L1",
                            "center": [1000, 1000],
                            "radius": 500,
                            "startAngle": 0,
                            "endAngle": 90,
                        },
                        {
                            "kind": "circle",
                            "story": "L1",
                            "center": [2000, 2000],
                            "radius": 400,
                        },
                    ]
                },
            }
        ],
        write=True,
    )
    assert res.ok
    assert len(res.results[0].created) == 2

    drafts = run_actions(project_path, [{"action": "drafting.list", "params": {"story": "L1"}}])
    assert drafts.ok
    data = drafts.results[0].data
    assert len(data) == 2
    arc_data = next(d for d in data if d["dxftype"] == "ARC")
    assert arc_data["radius"] == 500
    assert arc_data["start_angle"] == 0
    assert arc_data["end_angle"] == 90

    circle_data = next(d for d in data if d["dxftype"] == "CIRCLE")
    assert circle_data["radius"] == 400
    assert circle_data["center"] == [2000.0, 2000.0]


def test_drafting_migration(project_path: Path) -> None:
    # Pre-populate 05 Floor Plan/drafting/L1.dxf with an existing LINE entity
    existing_doc = new_document()
    existing_msp = existing_doc.modelspace()
    existing_line = existing_msp.add_line((100, 100), (200, 200), dxfattribs={"layer": "DRAFT"})
    existing_handle = existing_line.dxf.handle

    l1_dxf_path = project_path / "05 Floor Plan" / "drafting" / "L1.dxf"
    l1_dxf_path.parent.mkdir(parents=True, exist_ok=True)
    l1_dxf_path.write_text(write_dxf(existing_doc), encoding="utf-8")

    # Put old drafting directly into floor-plan.json
    fp_path = project_path / "05 Floor Plan" / "floor-plan.json"
    plan = json.loads(fp_path.read_text(encoding="utf-8"))
    plan["drafting"] = [
        {
            "kind": "line",
            "id": "D1",
            "story": "L1",
            "start": [0, 0],
            "end": [5000, 0],
        },
        {
            "kind": "polyline",
            "id": "D2",
            "story": "L1",
            "points": [[0, 0], [5000, 0], [5000, 4000]],
            "closed": True,
        },
        {
            "kind": "arc",
            "id": "D3",
            "story": "L2",
            "center": [1000, 1000],
            "radius": 500,
            "startAngle": 0,
            "endAngle": 90,
        },
        {
            "kind": "circle",
            "id": "D4",
            "story": "L2",
            "center": [2000, 2000],
            "radius": 400,
        },
    ]
    fp_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    # Run drafting.migrate
    res = run_actions(project_path, [{"action": "drafting.migrate", "params": {}}], write=True)
    assert res.ok
    assert "Migrated 4 draft shapes to DXF." in res.results[0].message

    # Check floor-plan.json has no drafting
    plan_after = json.loads(fp_path.read_text(encoding="utf-8"))
    assert "drafting" not in plan_after

    # Check L1.dxf has 3 entities: existing line, migrated line, migrated polyline
    doc_l1 = ezdxf.readfile(str(l1_dxf_path))
    types_l1 = [e.dxftype() for e in doc_l1.modelspace()]
    handles_l1 = [e.dxf.handle for e in doc_l1.modelspace()]
    assert existing_handle in handles_l1
    assert types_l1.count("LINE") == 2
    assert types_l1.count("LWPOLYLINE") == 1

    # Check L2.dxf has 2 entities: migrated arc, migrated circle
    l2_dxf_path = project_path / "05 Floor Plan" / "drafting" / "L2.dxf"
    assert l2_dxf_path.exists()
    doc_l2 = ezdxf.readfile(str(l2_dxf_path))
    types_l2 = [e.dxftype() for e in doc_l2.modelspace()]
    assert types_l2 == ["ARC", "CIRCLE"]

    # Running it twice changes nothing (idempotent)
    res2 = run_actions(project_path, [{"action": "drafting.migrate", "params": {}}], write=True)
    assert res2.ok
    assert "No drafting to migrate." in res2.results[0].message
    assert len(list(ezdxf.readfile(str(l1_dxf_path)).modelspace())) == 3
    assert len(list(ezdxf.readfile(str(l2_dxf_path)).modelspace())) == 2

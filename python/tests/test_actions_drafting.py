"""Tests for floor plan drafting actions: drafting.add, drafting.delete, drafting.list."""

from __future__ import annotations

from pathlib import Path

import pytest

from saengine.actions import run_actions

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
    assert line_id == "D1"
    assert poly_id == "D2"
    assert "Added D1, D2." in res.results[0].message

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
        [{"action": "drafting.delete", "params": {"ids": [line_id]}}],
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

    # Refusal for unknown id in delete
    res_id = run_actions(
        project_path,
        [{"action": "drafting.delete", "params": {"ids": ["D999"]}}],
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
                "params": {"ids": [line_id]},
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
    )
    assert res.ok
    assert len(res.results[0].created) == 2

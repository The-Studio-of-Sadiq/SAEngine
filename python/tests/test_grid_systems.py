"""Grid systems beyond the orthogonal one (#300): rotated orthogonal, radial and single angled
lines, their intersections by hand, and a frame on a 30° grid analysed like the same frame at 0°."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from saengine.library import FloorPlan, ObjectLibrary, default_floor_plan
from saengine.library.bim import generate
from saengine.library.grid_geometry import GridError, GridGeometry

SQ3 = math.sqrt(3)


def _plan(grids: dict[str, Any], **parts: Any) -> FloorPlan:
    base = default_floor_plan().model_dump(mode="json", by_alias=True)
    return FloorPlan.model_validate({**base, "grids": grids, **parts})


ROTATED = {
    "id": "G2",
    "name": "Wing",
    "kind": "orthogonal",
    "originX": 10000,
    "originY": 2000,
    "angle": 30,
    "x": [{"label": "P", "position": 0}, {"label": "Q", "position": 6000}],
    "y": [{"label": "7", "position": 0}, {"label": "8", "position": 4000}],
}
RADIAL = {
    "id": "R1",
    "kind": "radial",
    "originX": -5000,
    "originY": 1000,
    "angle": 10,
    "rays": [{"label": "R0", "angle": 0}, {"label": "R45", "angle": 45}],
    "rings": [{"label": "C1", "radius": 4000}, {"label": "C2", "radius": 8000}],
}
LINES = {
    "id": "L1",
    "kind": "lines",
    "lines": [{"label": "S", "x1": 0, "y1": -1000, "angle": 45, "length": 9000}],
}
GRIDS = {
    "x": [{"label": "A", "position": 0}, {"label": "B", "position": 6000}],
    "y": [{"label": "1", "position": 0}, {"label": "2", "position": 5000}],
    "systems": [ROTATED, RADIAL, LINES],
}


def test_rotated_system_intersections_by_hand() -> None:
    g = GridGeometry(_plan(GRIDS).grids)
    # Q-8: origin + 6000 (cos 30, sin 30) + 4000 (−sin 30, cos 30)
    x = 10000 + 6000 * SQ3 / 2 - 4000 * 0.5
    y = 2000 + 6000 * 0.5 + 4000 * SQ3 / 2
    assert g.intersection("Q", "8") == pytest.approx((x, y))
    assert g.intersection("P", "7") == pytest.approx((10000, 2000))
    assert g.orientation("Q") == pytest.approx(30)
    # offsets are along the plan's axes
    assert g.point({"x": "Q", "y": "8", "dx": 100, "dy": -50}) == pytest.approx((x + 100, y - 50))


def test_radial_system_intersections_by_hand() -> None:
    g = GridGeometry(GRIDS)  # the JSON reads the same as the model
    # R45 at 10° + 45° = 55°, ring C2 of 8 m about (−5000, 1000)
    a = math.radians(55)
    assert g.intersection("R45", "C2") == pytest.approx(
        (-5000 + 8000 * math.cos(a), 1000 + 8000 * math.sin(a))
    )
    assert g.intersection("R0", "C1") == pytest.approx(
        (-5000 + 4000 * math.cos(math.radians(10)), 1000 + 4000 * math.sin(math.radians(10)))
    )
    assert g.orientation("R45") == pytest.approx(55)
    with pytest.raises(GridError, match="ray then the ring"):
        g.intersection("C1", "R0")
    with pytest.raises(GridError, match="two rings"):
        g.intersection("C1", "C2")


def test_angled_line_crosses_the_main_grid() -> None:
    g = GridGeometry(GRIDS)
    # S runs at 45° from (0, −1000): it crosses B (x = 6000) at y = 5000 and 1 (y = 0) at x = 1000
    assert g.intersection("B", "S") == pytest.approx((6000, 5000))
    assert g.intersection("S", "1") == pytest.approx((1000, 0))
    assert g.orientation("S") == pytest.approx(-45)
    with pytest.raises(GridError, match="parallel"):
        GridGeometry(
            {
                "x": [{"label": "A", "position": 0}],
                "systems": [
                    {
                        "id": "V",
                        "kind": "lines",
                        "lines": [{"label": "V", "x1": 100, "y1": 0, "x2": 100, "y2": 9}],
                    }
                ],
            }
        ).intersection("A", "V")


def test_intersections_and_find() -> None:
    g = GridGeometry(GRIDS)
    found = {(a, b) for a, b, _ in g.intersections()}
    assert {("A", "1"), ("Q", "8"), ("R45", "C2"), ("B", "S")} <= found
    assert ("C1", "R0") not in found  # named ray first
    x, y = g.intersection("Q", "8")
    assert g.find(x + 20, y - 20) == ("Q", "8")


def test_old_plans_load_unchanged_and_labels_stay_unique() -> None:
    old = default_floor_plan().model_dump(mode="json", by_alias=True)
    plan = FloorPlan.model_validate(old)
    assert plan.grids.systems == []
    assert GridGeometry(plan.grids).orthogonal_only
    with pytest.raises(ValidationError, match="unique across all grid systems"):
        _plan({**GRIDS, "systems": [{**ROTATED, "x": [{"label": "A", "position": 0}]}]})
    with pytest.raises(ValidationError, match="an end point or an angle"):
        _plan({**GRIDS, "systems": [{**LINES, "lines": [{"label": "S", "x1": 0, "y1": 0}]}]})
    with pytest.raises(ValidationError, match="has no rays"):
        _plan({**GRIDS, "systems": [{**ROTATED, "rays": [{"label": "Z", "angle": 0}]}]})
    # a member on the main grid still names an X line then a Y line
    with pytest.raises(ValidationError, match="X line then the Y line"):
        _plan(
            GRIDS,
            stories=old["stories"],
            footings=[
                {
                    "id": "F1",
                    "type": "FT",
                    "story": old["stories"][0]["id"],
                    "at": {"x": "1", "y": "A"},
                }
            ],
        )


def test_columns_turn_with_their_grid_system() -> None:
    stories = default_floor_plan().model_dump(mode="json", by_alias=True)["stories"]
    base, top = stories[0]["id"], stories[1]["id"]
    plan = _plan(
        GRIDS,
        stories=stories,
        columns=[
            {
                "id": "C1",
                "type": "COL",
                "at": {"x": "Q", "y": "8"},
                "base": base,
                "top": top,
                "rotation": 90,
            },
            {"id": "C2", "type": "COL", "at": {"x": "R45", "y": "C1"}, "base": base, "top": top},
            {"id": "C3", "type": "COL", "at": {"x": "A", "y": "1"}, "base": base, "top": top},
        ],
    )
    elements = {e.id: e for e in generate(plan, "s").elements}
    assert elements["C1"].rotation == pytest.approx(120)
    assert elements["C2"].rotation == pytest.approx(55)
    assert elements["C3"].rotation == 0
    assert elements["C1"].position == pytest.approx(
        list(GridGeometry(plan.grids).intersection("Q", "8"))
    )


# ── a frame on a 30° grid analyses like the same frame at 0° ──

OBJECTS = ObjectLibrary.model_validate(
    {
        "objects": [
            {
                "id": "COL",
                "name": "Column 300x500",
                "kind": "column",
                "material": "C24.1",
                "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
            },
            {
                "id": "BM",
                "name": "Beam 300x500",
                "kind": "beam",
                "material": "C24.1",
                "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
            },
        ]
    }
)


def _frame(angle: float) -> FloorPlan:
    """A one-bay, one-story frame (6 m × 5 m, 3.2 m high) of 300 × 500 columns and beams, on a
    grid system turned by ``angle`` about (2000, 1000) (none at 0)."""
    lines = {
        "x": [{"label": "A", "position": 0}, {"label": "B", "position": 6000}],
        "y": [{"label": "1", "position": 0}, {"label": "2", "position": 5000}],
    }
    if angle:
        grids = {
            "systems": [
                {
                    "id": "G",
                    "kind": "orthogonal",
                    "originX": 2000,
                    "originY": 1000,
                    "angle": angle,
                    **lines,
                }
            ]
        }
    else:
        grids = {**lines}
    corners = [("A", "1"), ("B", "1"), ("B", "2"), ("A", "2")]
    return _plan(
        grids,
        stories=[
            {"id": "BASE", "name": "Base", "elevation": 0},
            {"id": "L1", "name": "L1", "elevation": 3200},
        ],
        columns=[
            {"id": f"C{i}", "type": "COL", "at": {"x": x, "y": y}, "base": "BASE", "top": "L1"}
            for i, (x, y) in enumerate(corners)
        ],
        beams=[
            {
                "id": f"B{i}",
                "type": "BM",
                "story": "L1",
                "start": {"x": a[0], "y": a[1]},
                "end": {"x": b[0], "y": b[1]},
            }
            for i, (a, b) in enumerate(zip(corners, corners[1:] + corners[:1], strict=True))
        ],
    )


def _analysed(root: Path, plan: FloorPlan) -> tuple[dict, dict[int, np.ndarray]]:
    """The derived model and the dead case's element end forces (in the members' axes)."""
    from opensees_studio.services.result_store import load_manifest, load_results

    from saengine.fem.derive import derive_fem
    from saengine.library import default_material_library
    from saengine.library.settings import default_project_settings

    d = derive_fem(
        generate(plan, "s"),
        OBJECTS,
        default_material_library(),
        default_project_settings("Frame"),
        {"bim": "abc"},
        architecture=False,
    )
    project = d.project
    dead = [a["id"] for a in project["analyses"] if str(a.get("name", "")).startswith("D:")]
    dead = dead or [project["analyses"][0]["id"]]
    path = root / "model.osmodel"
    path.write_text(json.dumps(project), encoding="utf-8")
    out = root / "model.results"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(path),
            "--cases",
            str(dead[0]),
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    [entry] = [e for e in load_manifest(out)["cases"] if e.get("id", dead[0]) == dead[0]][:1]
    results = load_results(entry, out)
    return project, {k: np.asarray(v[-1], dtype=float) for k, v in results.element_forces.items()}


def _rot(angle: float) -> np.ndarray:
    a = math.radians(angle)
    return np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])


def test_frame_on_a_30_degree_grid_matches_the_frame_at_0(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    flat, f0 = _analysed(tmp_path / "a", _frame(0))
    turned, f30 = _analysed(tmp_path / "b", _frame(30))
    rot, origin = _rot(30), np.array([2000.0, 1000.0, 0.0])

    xyz0 = {n["id"]: np.array(n["coords"], dtype=float) for n in flat["nodes"]}
    xyz30 = {n["id"]: np.array(n["coords"], dtype=float) for n in turned["nodes"]}
    scale = 1.0 if max(abs(c).max() for c in xyz0.values()) > 100 else 1000.0  # m or mm

    # Every node of the turned frame is a node of the flat one, turned 30° about the origin
    # (the model's coordinates are rounded to the millimetre).
    places = list(xyz0.items())
    node_map = {}
    for j, p in xyz30.items():
        back = rot.T @ (p - origin / scale)
        i, q = min(places, key=lambda item: float(np.linalg.norm(item[1] - back)))
        assert np.linalg.norm(q - back) * scale < 2.0
        node_map[j] = i
    frames0 = {
        tuple(e["nodes"]): e for e in flat["elements"] if len(e["nodes"]) == 2 and e["id"] in f0
    }
    compared = 0
    for e in turned["elements"]:
        if len(e["nodes"]) != 2 or e["id"] not in f30:
            continue
        twin = frames0[tuple(node_map[n] for n in e["nodes"])]
        # the same length ...
        a, b = (xyz30[n] for n in e["nodes"])
        c, d = (xyz0[n] for n in twin["nodes"])
        assert np.linalg.norm(b - a) * scale == pytest.approx(np.linalg.norm(d - c) * scale, abs=2)
        # ... and the same end forces in the member's own axes (axial, shears, torsion and
        # moments): the beams' axes run along them and the columns turned with the grid, so a
        # column whose axes stayed on X and Y would bend the other way and fail here.
        mine, theirs = f30[e["id"]], f0[twin["id"]]
        tol = 5e-3 * max(1.0, np.abs(theirs).max())  # the model rounds coordinates to mm
        np.testing.assert_allclose(mine, theirs, atol=tol)
        compared += 1
    assert compared >= 8  # four columns and four beams, at least


def test_drawings_mark_columns_on_the_other_systems() -> None:
    from saengine.drawings.sheets.project import grid_position

    g = GridGeometry(GRIDS)
    others = [a for a in g.axes if a.system]
    x, y = g.intersection("Q", "8")
    assert grid_position(x + 10, y, [], [], others=others) == "Q8"
    assert grid_position(x + 500, y, [], [], others=others) is None

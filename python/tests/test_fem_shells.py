"""Walls and slabs as shells, rigid diaphragms and partition loads in the derived analysis model."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from saengine.fem.derive import derive_fem
from saengine.library import FloorPlan, ObjectLibrary, default_floor_plan, default_material_library
from saengine.library.bim import Additions, WallOpening, generate
from saengine.library.settings import default_project_settings

G = 9.80665
RHO = 2400.0  # kg/m³, concrete C24.1

OBJECTS = ObjectLibrary.model_validate(
    {
        "objects": [
            {
                "id": "COL",
                "name": "Column 400x400",
                "kind": "column",
                "material": "C24.1",
                "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
            },
            {
                "id": "BM",
                "name": "Beam 300x500",
                "kind": "beam",
                "material": "C24.1",
                "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
            },
            {"id": "SL", "name": "Slab 150", "kind": "slab", "material": "C24.1", "thickness": 150},
            {
                "id": "WL",
                "name": "Shear wall 200",
                "kind": "wall",
                "material": "C24.1",
                "thickness": 200,
            },
            {
                "id": "PW",
                "name": "Partition 125",
                "kind": "wall",
                "material": "C24.1",
                "thickness": 125,
                "structural": False,
            },
        ]
    }
)

# One bay (A-B 6 m, 1-2 5 m), two stories of 3.2 m: a shear wall along grid 1 with a door, and a
# partition on the level 1 beam along grid 2.
corners = [("A", "1"), ("B", "1"), ("B", "2"), ("A", "2")]
stories = [
    {"id": "BASE", "name": "Base", "elevation": 0},
    {"id": "L1", "name": "Level 1", "elevation": 3200},
    {"id": "L2", "name": "Level 2", "elevation": 6400},
]
PLAN = FloorPlan.model_validate(
    {
        **default_floor_plan().model_dump(mode="json", by_alias=True),
        "stories": stories,
        "columns": [
            {"id": f"C{i + 1}", "type": "COL", "at": {"x": x, "y": y}, "base": "BASE", "top": "L2"}
            for i, (x, y) in enumerate(corners)
        ],
        "beams": [
            {
                "id": f"B{story}{i + 1}",
                "type": "BM",
                "story": f"L{story}",
                "start": {"x": a[0], "y": a[1]},
                "end": {"x": b[0], "y": b[1]},
            }
            for story in (1, 2)
            for i, (a, b) in enumerate(zip(corners, corners[1:] + corners[:1]))
        ],
        "slabs": [
            {
                "id": f"S{story}",
                "type": "SL",
                "story": f"L{story}",
                "boundary": [{"x": x, "y": y} for x, y in corners],
            }
            for story in (1, 2)
        ],
        "walls": [
            {
                "id": "W1",
                "type": "WL",
                "base": "BASE",
                "top": "L2",
                "start": {"x": "A", "y": "1"},
                "end": {"x": "B", "y": "1"},
            },
            {
                "id": "P1",
                "type": "PW",
                "base": "L1",
                "top": "L2",
                "start": {"x": "A", "y": "2"},
                "end": {"x": "B", "y": "2"},
            },
        ],
    }
)
DOOR = WallOpening(id="D1", host="W1", offset=1000, sill=0, width=1000, height=2100)


def building():
    model = generate(PLAN, "s")
    return model.model_copy(update={"additions": Additions(wallOpenings=[DOOR])})


def settings(**analysis: object):
    s = default_project_settings("Walls")
    return s.model_copy(update={"analysis": s.analysis.model_copy(update=analysis)})


def total(project: dict, case: str) -> np.ndarray:
    """Total applied force of a pattern, element loads turned back to global axes."""
    from saengine.fem.derive import local_axes

    coords = {n["id"]: np.array(n["coords"]) for n in project["nodes"]}
    elements = {e["id"]: e for e in project["elements"]}
    pattern = next(p for p in project["load_patterns"] if p["name"] == case)
    result = sum((np.array(n["forces"][:3]) for n in pattern["nodal_loads"]), np.zeros(3))
    for load in pattern["element_loads"]:
        a, b = (coords[n] for n in elements[load["element_id"]]["nodes"])
        x, y, z = local_axes(a, b)
        result = result + (load["wx"] * x + load["wy"] * y + load["wz"] * z) * np.linalg.norm(b - a)
    return result


def run(project: dict, tmp: Path, cases: list[int]) -> dict:
    from opensees_studio.services.result_store import load_manifest, load_results

    model = tmp / "model.osmodel"
    model.write_text(json.dumps(project), encoding="utf-8")
    out = tmp / "model.results"
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(model),
            "--cases",
            *map(str, cases),
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return {e["case_id"]: load_results(e, out) for e in load_manifest(out)["cases"]}


def test_walls_become_shells_and_carry_their_weight() -> None:
    from opensees_studio.core.project import Project

    d = derive_fem(building(), OBJECTS, default_material_library(), settings())
    Project.model_validate(d.project).validate_references()
    assert d.summary["shells"] > 20 and d.summary["diaphragms"] == 2
    assert not [n for n in d.notes if "W1" in n or "P1" in n]
    shells = [e for e in d.project["elements"] if e["type"] == "Shell"]
    assert {e["name"].split("#")[0] for e in shells} == {"W1"}  # slabs stay loads-to-beams
    # The wall's whole base is fixed.
    coords = {n["id"]: n for n in d.project["nodes"]}
    base_nodes = {n for e in shells for n in e["nodes"] if coords[n]["coords"][2] == 0}
    assert all(all(coords[n]["restraint"]) for n in base_nodes) and len(base_nodes) > 4

    weight = (
        RHO
        * G
        * (
            2 * 30 * 0.15  # slabs
            + 4 * 0.16 * 6.4  # columns
            + 2 * 22 * 0.15  # beams
            + (6 * 6.4 - 1 * 2.1) * 0.2  # shear wall less the door
            + 6 * 3.2 * 0.125  # partition on the level 1 beam
        )
    )
    assert total(d.project, "D")[2] == pytest.approx(-weight, rel=1e-6)


def test_shell_slabs_carry_the_area_loads(tmp_path: Path) -> None:
    s = settings(slabs="shells", meshSize=1000)
    d = derive_fem(building(), OBJECTS, default_material_library(), s)
    names = {e["name"].split("#")[0] for e in d.project["elements"] if e["type"] == "Shell"}
    assert names == {"W1", "S1", "S2"}
    loads = {a.id: a for a in s.areaLoads}
    floor, roof = loads[s.floorLoad], loads[s.roofLoad]
    sd = 30 * (floor.finish + floor.partitions + roof.finish + roof.partitions) * 1e3
    assert total(d.project, "SD")[2] == pytest.approx(-sd, rel=1e-6)
    assert total(d.project, "L")[2] == pytest.approx(-30 * floor.live * 1e3, rel=1e-6)

    results = run(d.project, tmp_path, [1, 2, 7, 9])
    reaction = sum(r[-1] for r in results[1].node_reaction.values())
    assert reaction[2] == pytest.approx(-total(d.project, "D")[2], rel=1e-6)
    # Rigid floors: under the earthquake in X, level 2 translates and twists (the wall is off
    # centre) as one plate about its diaphragm node.
    tie = next(
        c
        for c in d.project["mp_constraints"]
        if c["retained_node"] in [n["id"] for n in d.project["nodes"] if n["coords"][2] == 6.4]
    )
    coords = {n["id"]: np.array(n["coords"]) for n in d.project["nodes"]}
    master = results[7].node_disp[tie["retained_node"]][-1]
    centre = coords[tie["retained_node"]]
    for n in tie["constrained_nodes"]:
        u = results[7].node_disp[n][-1]
        dx, dy = coords[n][:2] - centre[:2]
        expected = [master[0] - master[5] * dy, master[1] + master[5] * dx, master[5]]
        assert [u[0], u[1], u[5]] == pytest.approx(expected, rel=1e-6, abs=1e-12)
    assert abs(master[5]) > 0  # the off-centre wall makes the floor twist
    assert results[9].periods[0] > 0
    assert results[2].shell_forces

    from saengine.fem.display import result_view

    view = result_view(tmp_path / "model.results", tmp_path / "model.osmodel", "case:2")
    shells = {s["id"]: s for s in view["shells"]}
    assert len(shells) == d.summary["shells"]
    # Slab moments under the finishes: largest at the slab, in N·m/m.
    slab = [s for s in view["shells"] if s["name"].startswith("S")]
    assert max(abs(s["forces"][3]) for s in slab) > 100


def test_flexible_floors_have_no_diaphragm() -> None:
    d = derive_fem(building(), OBJECTS, default_material_library(), settings(diaphragm="flexible"))
    assert d.project["mp_constraints"] == [] and d.summary["diaphragms"] == 0

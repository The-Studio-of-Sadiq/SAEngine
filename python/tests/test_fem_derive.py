"""The analysis model derived from the building model, and combinations of its results."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from saengine.fem.combinations import combination_results
from saengine.fem.derive import derive_fem
from saengine.library import FloorPlan, ObjectLibrary, default_floor_plan, default_material_library
from saengine.library.bim import generate
from saengine.library.settings import default_project_settings

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
        ]
    }
)

# One bay (A-B 6 m, 1-2 5 m), one story at 3.2 m: four columns, four beams, one slab.
corners = [("A", "1"), ("B", "1"), ("B", "2"), ("A", "2")]
PLAN = FloorPlan.model_validate(
    {
        **default_floor_plan().model_dump(mode="json", by_alias=True),
        "columns": [
            {"id": f"C{i + 1}", "type": "COL", "at": {"x": x, "y": y}, "base": "BASE", "top": "L1"}
            for i, (x, y) in enumerate(corners)
        ],
        "beams": [
            {
                "id": f"B{i + 1}",
                "type": "BM",
                "story": "L1",
                "start": {"x": a[0], "y": a[1]},
                "end": {"x": b[0], "y": b[1]},
            }
            for i, (a, b) in enumerate(zip(corners, corners[1:] + corners[:1]))
        ],
        "slabs": [
            {
                "id": "S1",
                "type": "SL",
                "story": "L1",
                "boundary": [{"x": x, "y": y} for x, y in corners],
            }
        ],
    }
)
SETTINGS = default_project_settings("Bay")


def derivation():
    return derive_fem(
        generate(PLAN, "s"), OBJECTS, default_material_library(), SETTINGS, {"bim": "abc"}
    )


def applied(project: dict, name: str) -> np.ndarray:
    """Total applied force of a pattern, element loads turned back to global axes."""
    coords = {n["id"]: np.array(n["coords"]) for n in project["nodes"]}
    elements = {e["id"]: e for e in project["elements"]}
    pattern = next(p for p in project["load_patterns"] if p["name"] == name)
    total = sum((np.array(n["forces"][:3]) for n in pattern["nodal_loads"]), np.zeros(3))
    for load in pattern["element_loads"]:
        a, b = (coords[n] for n in elements[load["element_id"]]["nodes"])
        x = (b - a) / np.linalg.norm(b - a)
        vecxz = np.array([1.0, 0, 0]) if abs(x[2]) > abs(x[0]) else np.array([0, 0, 1.0])
        y = np.cross(vecxz, x)
        y /= np.linalg.norm(y)
        total = total + (
            load["wx"] * x + load["wy"] * y + load["wz"] * np.cross(x, y)
        ) * np.linalg.norm(b - a)
    return total


def test_derived_model_is_valid_with_bnbc_loads() -> None:
    from opensees_studio.core.project import Project

    d = derivation()
    project = Project.model_validate(d.project)
    # 8 frame nodes and the rigid diaphragm's node at the floor's centre of mass.
    assert (len(project.nodes), len(project.elements), d.summary["supports"]) == (9, 8, 4)
    assert d.summary["diaphragms"] == 1
    assert [p["name"] for p in d.project["load_patterns"]] == [
        "D",
        "SD",
        "L",
        "Lr",
        "WX",
        "WY",
        "EX",
        "EY",
    ]
    # The slab's area loads reach the beams in full: 30 m² of roof (L1 is the top story), so the
    # roof's finish and roof live load apply, and no floor live load.
    assert applied(d.project, "SD")[2] == pytest.approx(-1.5e3 * 30, rel=1e-6)
    assert applied(d.project, "Lr")[2] == pytest.approx(-1.0e3 * 30, rel=1e-6)
    assert applied(d.project, "L")[2] == pytest.approx(0)
    # Self-weight: slab 0.15 m x 2400 kg/m³ over 30 m², plus 4 columns 0.16 m² x 3.2 m and the
    # beams 0.15 m² around the 22 m perimeter.
    weight = 2400 * 9.80665 * (0.15 * 30 + 4 * 0.16 * 3.2 + 0.15 * 22)
    assert applied(d.project, "D")[2] == pytest.approx(-weight, rel=1e-6)
    assert applied(d.project, "EX")[0] == pytest.approx(d.summary["base_shear_kN"] * 1e3, rel=1e-6)
    beam = next(e for e in d.project["elements"] if e["name"] == "B1")
    # Beam sections carry the strong axis in Iy (gravity bends horizontal beams about local y).
    section = next(s for s in d.project["sections"] if s["id"] == beam["section_id"])
    assert (section["Iy"], section["Iz"]) == pytest.approx(
        (0.3 * 0.5**3 / 12, 0.5 * 0.3**3 / 12), rel=1e-3
    )


def test_analysis_runs_and_combinations_balance(tmp_path: Path) -> None:
    d = derivation()
    model = tmp_path / "08 FEM" / "model.osmodel"
    model.parent.mkdir()
    model.write_text(json.dumps(d.project), encoding="utf-8")
    out = tmp_path / "08 FEM" / "model.results"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(model),
            "--cases",
            *map(str, range(1, 10)),
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    entries = {e["caseName"]: e for e in combination_results(out, d.project, SETTINGS)}
    total = entries["1.2D + 1.6L + 0.5Lr"]["tables"][0]["rows"][-1]
    expected = (
        -1.2 * (applied(d.project, "D")[2] + applied(d.project, "SD")[2])
        - 0.5 * applied(d.project, "Lr")[2]
    )
    assert total[3] == pytest.approx(expected, rel=1e-4)
    assert "Envelope of all combinations" in entries

    # The 3D display of the same run: listing, a combination's reactions, a mode shape.
    from saengine.fem.display import result_list, result_view

    settings_file = tmp_path / "02 Project Settings" / "project-settings.json"
    settings_file.parent.mkdir()
    settings_file.write_text(SETTINGS.model_dump_json(by_alias=True), encoding="utf-8")
    listing = result_list(out, model)
    keys = {r["label"]: r["key"] for r in listing["results"]}
    assert not listing["stale"]
    view = result_view(out, model, keys["1.2D + 1.6L + 0.5Lr"])
    assert sum(r[3] for r in view["reactions"]) == pytest.approx(total[3], rel=1e-6)
    beam = next(e for e in view["elements"] if e["name"] == "B1")
    assert beam["forces"][0][4] > 0 > beam["forces"][len(beam["forces"]) // 2][4]  # hog, sag
    modal = next(r for r in listing["results"] if r["kind"] == "modal")
    shape = result_view(out, model, modal["key"], 1)
    assert max(abs(c) for n in shape["nodes"] for c in n[1:4]) == pytest.approx(1.0)

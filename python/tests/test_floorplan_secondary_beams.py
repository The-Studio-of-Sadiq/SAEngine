"""Beams that end on other beams (secondary beams) or in the air (cantilevers), as the floor plan
places them since the usability round (F1): they go through the building model into the analysis
model, which joins a secondary beam to the beam it rests on and splits that beam there."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saengine.rpc import handlers

SAMPLE = Path(__file__).resolve().parents[2] / "workbench/resources/saengine/samples/Sample Frame"

pytest.importorskip("gmsh")


def _derive(tmp_path: Path, extra_beams: list[dict]) -> tuple[dict, dict[int, tuple]]:
    plan = json.loads((SAMPLE / "05 Floor Plan/floor-plan.json").read_text(encoding="utf-8"))
    plan["beams"] += extra_beams
    bim = handlers.generate_building(json.dumps(plan), None)
    assert "text" in bim, bim
    model_folder = tmp_path / "08 FEM"
    model_folder.mkdir()
    derived = handlers.derive_fem(
        bim["text"],
        (SAMPLE / "04 Objects/objects.json").read_text(encoding="utf-8"),
        (SAMPLE / "03 Materials/materials.json").read_text(encoding="utf-8"),
        (SAMPLE / "02 Project Settings/project-settings.json").read_text(encoding="utf-8"),
        str(model_folder),
        None,
        None,
        None,
        "",
    )
    assert "text" in derived, derived
    model = json.loads(derived["text"])
    nodes = {n["id"]: tuple(round(c, 3) for c in n["coords"]) for n in model["nodes"]}
    return model, nodes


def _nodes_of(model: dict, nodes: dict[int, tuple], member: str) -> set[tuple]:
    return {
        nodes[n]
        for e in model["elements"]
        if str(e.get("name", "")).split("#")[0].split("/")[0] == member
        for n in e["nodes"]
    }


def test_secondary_beams_split_the_beams_they_rest_on_and_cantilevers_stay_free(tmp_path):
    # B90 spans from the middle of B1 (A-1 to B-1) to the middle of B3 (A-2 to B-2) on L1;
    # B91 is a 1.5 m cantilever off C-1; B92 is a diagonal A-1 to B-2 and B93 ends on it at
    # the foot of the perpendicular from A-2, stored to 0.001 mm as the floor plan does.
    model, nodes = _derive(
        tmp_path,
        [
            {"id": "B90", "type": "B300x500", "story": "L1",
             "start": {"x": "A", "y": "1", "dx": 3000}, "end": {"x": "A", "y": "2", "dx": 3000}},
            {"id": "B91", "type": "B300x500", "story": "L1",
             "start": {"x": "C", "y": "1"}, "end": {"x": "C", "y": "1", "dx": 1500}},
            {"id": "B92", "type": "B300x500", "story": "L2",
             "start": {"x": "A", "y": "1"}, "end": {"x": "B", "y": "2"}},
            {"id": "B93", "type": "B300x500", "story": "L2",
             "start": {"x": "A", "y": "2"}, "end": {"x": "A", "y": "1", "dx": 2459.016, "dy": 2049.18}},
        ],
    )
    degree: dict[tuple, int] = {}
    for e in model["elements"]:
        for n in e["nodes"]:
            degree[nodes[n]] = degree.get(nodes[n], 0) + 1

    # The supporting beams have a node where the secondary beam lands, shared with it.
    assert (3.0, 0.0, 3.2) in _nodes_of(model, nodes, "B1") & _nodes_of(model, nodes, "B90")
    assert (3.0, 5.0, 3.2) in _nodes_of(model, nodes, "B3") & _nodes_of(model, nodes, "B90")
    on_diagonal = _nodes_of(model, nodes, "B92") & _nodes_of(model, nodes, "B93")
    assert any(abs(x - 2.459) < 0.002 and abs(y - 2.049) < 0.002 for x, y, _ in on_diagonal)
    # The cantilever's tip is free: one element meets there.
    assert degree[(14.5, 0.0, 3.2)] == 1

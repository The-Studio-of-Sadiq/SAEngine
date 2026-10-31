"""Podium and multi-tower buildings (saengine.fem.towers): regions, tower nodes, the tower checks
of the response spectrum design, and the floor plan's and building model's towers."""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.fem import towers as T
from saengine.library.floorplan import FloorPlan

SQUARE = ((0.0, 0.0), (6.0, 0.0), (6.0, 5.0), (0.0, 5.0))


def test_inside_counts_the_edges() -> None:
    assert T.inside(3.0, 2.5, SQUARE)
    assert T.inside(0.0, 2.5, SQUARE)  # on an edge
    assert T.inside(6.0, 5.0, SQUARE)  # a corner
    assert not T.inside(6.01, 2.5, SQUARE)


def _towers() -> T.Towers:
    return T.Towers(
        podium=3.0,
        regions=(
            T.TowerRegion("A", "Tower A", SQUARE),
            T.TowerRegion("B", "Tower B", ((12.0, 0.0), (18.0, 0.0), (18.0, 5.0), (12.0, 5.0))),
        ),
    )


def _node(i: int, x: float, y: float, z: float, mass: float = 0.0) -> dict:
    return {"id": i, "coords": [x, y, z], "mass": [mass, mass, 0, 0, 0, 0]}


def _project() -> dict:
    nodes = [
        _node(1, 0, 0, 0), _node(2, 18, 0, 0),  # base
        _node(3, 0, 0, 3), _node(4, 6, 5, 3), _node(5, 9, 2, 3), _node(6, 12, 0, 3),  # podium
        _node(7, 0, 0, 6, 1000.0), _node(8, 6, 5, 6, 1000.0),  # tower A
        _node(9, 12, 0, 6, 2000.0), _node(10, 18, 5, 6, 2000.0),  # tower B
    ]  # fmt: skip
    return {
        "nodes": nodes,
        "load_patterns": [
            {
                "name": "EX",
                "nodal_loads": [
                    {"node_id": 7, "forces": [10e3, 0, 0, 0, 0, 0]},
                    {"node_id": 8, "forces": [10e3, 0, 0, 0, 0, 0]},
                    {"node_id": 9, "forces": [20e3, 0, 0, 0, 0, 0]},
                    {"node_id": 10, "forces": [20e3, 0, 0, 0, 0, 0]},
                ],
            }
        ],
    }


def test_tower_nodes_by_region_and_level() -> None:
    found = T.tower_nodes(_project(), _towers())
    assert found["A"] == {"above": {7, 8}, "podium": {3, 4}}
    assert found["B"] == {"above": {9, 10}, "podium": {6}}


def test_towers_of_a_building_model_in_metres() -> None:
    building = {
        "stories": [
            {"id": "L1", "name": "L1", "elevation": 0},
            {"id": "P", "name": "P", "elevation": 3000},
        ],
        "podiumTop": "P",
        "towers": [
            {
                "id": "A",
                "name": "Tower A",
                "boundary": [[0, 0], [6000, 0], [6000, 5000]],
            }
        ],
    }
    towers = T.towers_of(building)
    assert towers is not None and towers.podium == 3.0
    assert towers.regions[0].boundary == ((0.0, 0.0), (6.0, 0.0), (6.0, 5.0))
    assert T.towers_of({**building, "towers": []}) is None


def test_period_and_base_shear_of_each_tower() -> None:
    """Two modes in X: mode 1 moves tower B only, mode 2 tower A only. Peaks u = Γ·φ·Sa/ω²; the
    tower's modal shear V = Σ m·ω²·u, its effective mass V / Sa, and V_rs the SRSS of the modes
    (Sec 2.5.9.4); the static share is the EX load on the tower's nodes."""
    w1, w2, sa = 2 * math.pi / 1.5, 2 * math.pi / 0.8, 2.0
    u1, u2 = 0.01, 0.004
    spectra = {
        "X": {
            "rule": "SRSS",
            "damping": None,
            "modes": [
                {
                    "mode_number": 1,
                    "period": 1.5,
                    "angular_frequency": w1,
                    "sa_at_period": sa,
                },
                {
                    "mode_number": 2,
                    "period": 0.8,
                    "angular_frequency": w2,
                    "sa_at_period": sa,
                },
            ],
            "peaks": [
                {9: np.array([u1, 0, 0]), 10: np.array([u1, 0, 0])},
                {7: np.array([u2, 0, 0]), 8: np.array([u2, 0, 0])},
            ],
        }
    }
    shears = T.tower_shears(_project(), _towers(), spectra)
    a, b = shears["A"]["X"], shears["B"]["X"]
    assert a["period"] == pytest.approx(0.8) and a["mode"] == 2
    assert b["period"] == pytest.approx(1.5) and b["mode"] == 1
    v_a = 2 * 1000.0 * w2**2 * u2
    assert a["dynamic"] == pytest.approx(v_a)
    assert a["massRatio"] == pytest.approx(v_a / sa / 2000.0)
    assert a["static"] == pytest.approx(20e3) and b["static"] == pytest.approx(40e3)
    assert a["scale"] == pytest.approx(max(1.0, 0.85 * 20e3 / v_a))


def test_floor_plan_towers_need_a_podium_top_and_grid_lines() -> None:
    base = {
        "grids": {"x": [{"label": "A", "position": 0}, {"label": "B", "position": 6000}],
                  "y": [{"label": "1", "position": 0}, {"label": "2", "position": 5000}]},
        "stories": [{"id": "L0", "name": "Base", "elevation": 0},
                    {"id": "L1", "name": "Podium", "elevation": 3000}],
    }  # fmt: skip
    tower = {
        "id": "T1",
        "name": "Tower 1",
        "boundary": [{"x": "A", "y": "1"}, {"x": "B", "y": "1"}, {"x": "B", "y": "2"}],
    }
    plan = FloorPlan.model_validate({**base, "podiumTop": "L1", "towers": [tower]})
    assert plan.towers[0].id == "T1"
    with pytest.raises(ValueError, match="podium top"):
        FloorPlan.model_validate({**base, "towers": [tower]})
    with pytest.raises(ValueError, match="no story"):
        FloorPlan.model_validate({**base, "podiumTop": "L9"})
    bad = {**tower, "boundary": [{"x": "C", "y": "1"}, *tower["boundary"][1:]]}
    with pytest.raises(ValueError, match="grid line"):
        FloorPlan.model_validate({**base, "podiumTop": "L1", "towers": [bad]})


def _two_towers_plan() -> FloorPlan:
    """A podium A-D × 1-2 one storey high (P at 3.2 m) and two towers, A-B and C-D, one storey
    above it (L2 at 6.4 m)."""
    xs = {"A": 0, "B": 6000, "C": 12000, "D": 18000}
    left, right = (
        [("A", "1"), ("B", "1"), ("B", "2"), ("A", "2")],
        [("C", "1"), ("D", "1"), ("D", "2"), ("C", "2")],
    )
    podium = [("A", "1"), ("D", "1"), ("D", "2"), ("A", "2")]

    def ring(points: list[tuple[str, str]], story: str, prefix: str) -> list[dict]:
        return [
            {"id": f"{prefix}{i + 1}", "type": "BM", "story": story,
             "start": {"x": a[0], "y": a[1]}, "end": {"x": b[0], "y": b[1]}}
            for i, (a, b) in enumerate(zip(points, points[1:] + points[:1], strict=True))
        ]  # fmt: skip

    def slab(points: list[tuple[str, str]], story: str, sid: str) -> dict:
        return {"id": sid, "type": "SL", "story": story,
                "boundary": [{"x": x, "y": y} for x, y in points]}  # fmt: skip

    columns = [
        {"id": f"PC{x}{y}", "type": "COL", "at": {"x": x, "y": y}, "base": "BASE", "top": "P"}
        for x in xs for y in ("1", "2")
    ] + [
        {"id": f"TC{x}{y}", "type": "COL", "at": {"x": x, "y": y}, "base": "P", "top": "L2"}
        for x, y in left + right
    ]  # fmt: skip
    return FloorPlan.model_validate(
        {
            "grids": {"x": [{"label": k, "position": v} for k, v in xs.items()],
                      "y": [{"label": "1", "position": 0}, {"label": "2", "position": 5000}]},
            "stories": [{"id": "BASE", "name": "Base", "elevation": 0},
                        {"id": "P", "name": "Podium", "elevation": 3200},
                        {"id": "L2", "name": "Level 2", "elevation": 6400}],
            "columns": columns,
            "beams": ring(podium, "P", "PB") + ring(left, "L2", "LB") + ring(right, "L2", "RB"),
            "slabs": [slab(podium, "P", "PS"), slab(left, "L2", "LS"), slab(right, "L2", "RS")],
            "podiumTop": "P",
            "towers": [
                {"id": "T1", "name": "Tower 1", "boundary": [{"x": x, "y": y} for x, y in left]},
                {"id": "T2", "name": "Tower 2", "boundary": [{"x": x, "y": y} for x, y in right]},
            ],
        }
    )  # fmt: skip


def test_each_tower_gets_its_own_diaphragm_above_the_podium() -> None:
    from test_fem_derive import OBJECTS

    from saengine.fem.derive import derive_fem
    from saengine.library import default_material_library
    from saengine.library.bim import generate
    from saengine.library.settings import default_project_settings

    building = generate(_two_towers_plan(), "s")
    assert building.podiumTop == "P"
    assert building.towers[1].boundary[0] == [12000.0, 0.0]
    d = derive_fem(
        building, OBJECTS, default_material_library(), default_project_settings("Towers"),
        {"bim": "abc"},
    )  # fmt: skip
    diaphragms = [c for c in d.project["mp_constraints"] if c["type"] == "RigidDiaphragm"]
    coords = {n["id"]: n["coords"] for n in d.project["nodes"]}
    levels = sorted(round(coords[c["retained_node"]][2], 3) for c in diaphragms)
    assert levels == [3.2, 6.4, 6.4]  # the podium's floor, then one per tower
    towers = T.towers_of(building)
    assert towers is not None
    for c in diaphragms:
        if round(coords[c["retained_node"]][2], 3) == 6.4:
            regions = {T.region_of(*coords[n][:2], towers) for n in c["constrained_nodes"]}
            assert len(regions) == 1 and None not in regions
    assert any("rigid diaphragm per tower" in note for note in d.notes)

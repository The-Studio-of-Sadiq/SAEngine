"""#300: the New Project wizard's rotated and radial grids (saengine.library.grid_placement).

Every expected number is worked out by hand in the comments.
"""

from __future__ import annotations

import json
import math

import pytest

from saengine.library.floorplan import FloorPlan
from saengine.library.generator import building_texts, generate_building
from saengine.library.grid_geometry import GridGeometry
from saengine.project.new_building import NewBuildingError, spec_from_wizard

SIN30, COS30 = 0.5, math.sqrt(3) / 2


def _parts(spec: dict) -> tuple[dict, dict, dict, dict]:
    result = generate_building(spec)
    texts = building_texts(result)
    plan = json.loads(texts["05 Floor Plan/floor-plan.json"])
    FloorPlan.model_validate(plan)  # the plan the generator wrote is valid
    sub = json.loads(texts["09 Substructure/substructure.json"])
    bim = json.loads(texts["06 BIM/bim.json"])
    return result, plan, sub, bim


def _columns(bim: dict) -> dict[str, dict]:
    return {e["id"]: e for e in bim["elements"] if e["kind"] == "column"}


def test_rotated_30_degrees() -> None:
    # Two 6 m bays along x, one 5 m bay along y, one storey: lines A B C and 1 2, so 3 × 2 = 6
    # columns, beams 2 per y line × 2 + 1 per x line × 3 = 7, and 2 slabs.
    result, plan, sub, bim = _parts(
        {
            "gridsX": [6000, 6000],
            "gridsY": [5000],
            "storyCount": 1,
            "system": "rcFrame",
            "footing": "isolated",
            "gridKind": "rotated",
            "gridAngle": 30,
        }
    )
    assert plan["grids"]["x"] == [] and plan["grids"]["y"] == []
    (system,) = plan["grids"]["systems"]
    assert (system["kind"], system["angle"]) == ("orthogonal", 30)
    assert [g["label"] for g in system["x"]] == ["A", "B", "C"]
    assert (len(plan["columns"]), len(plan["beams"]), len(plan["slabs"])) == (6, 7, 2)
    # B2 is at local (6000, 5000): x = 6000 cos30 - 5000 sin30 = 2696.15,
    # y = 6000 sin30 + 5000 cos30 = 7330.13.
    expected = (6000 * COS30 - 5000 * SIN30, 6000 * SIN30 + 5000 * COS30)
    assert GridGeometry(plan["grids"]).point({"x": "B", "y": "2"}) == pytest.approx(expected)
    column = _columns(bim)["C-B2-L1"]
    assert column["position"][:2] == pytest.approx(expected, abs=0.5)
    assert column["rotation"] == pytest.approx(30)  # turns with its grid
    pad = next(f for f in sub["foundations"] if f["id"] == "F-B2")
    assert pad["center"] == pytest.approx(expected, abs=0.1)
    assert pad["rotation"] == pytest.approx(30)
    # C1 at local (12000, 0): (12000 cos30, 12000 sin30) = (10392.3, 6000).
    pad = next(f for f in sub["foundations"] if f["id"] == "F-C1")
    assert pad["center"] == pytest.approx([12000 * COS30, 6000], abs=0.1)
    assert "rotated 30° grid system" in result["notes"][-1]


def test_radial_full_circle() -> None:
    # Rings at 6, 10 and 14 m, rays every 90° (a closed circle): 3 rings × 4 rays = 12
    # columns; beams 4 chords on each of 3 rings = 12 plus 2 on each of 4 rays = 8, so 20;
    # 2 × 4 = 8 slabs.
    result, plan, sub, bim = _parts(
        {
            "gridsX": [4000, 4000],
            "gridKind": "radial",
            "innerRadius": 6000,
            "rayAngles": [90, 90, 90, 90],
            "storyCount": 1,
            "system": "rcFrame",
            "footing": "mat",
        }
    )
    (system,) = plan["grids"]["systems"]
    assert system["kind"] == "radial"
    assert [(r["label"], r["angle"]) for r in system["rays"]] == [
        ("1", 0),
        ("2", 90),
        ("3", 180),
        ("4", 270),
    ]
    assert [(r["label"], r["radius"]) for r in system["rings"]] == [
        ("A", 6000),
        ("B", 10000),
        ("C", 14000),
    ]
    assert (len(plan["columns"]), len(plan["beams"]), len(plan["slabs"])) == (12, 20, 8)
    assert result["summary"]["counts"]["columns"] == 12
    columns = {c["id"]: c for c in plan["columns"]}
    # Grid points name the ray, then the ring.
    assert columns["C-B2-L1"]["at"]["x"] == "2" and columns["C-B2-L1"]["at"]["y"] == "B"
    # Ray 2 at 90°, ring B at 10 m: (0, 10000); turned 90° with its ray.
    column = _columns(bim)["C-B2-L1"]
    assert column["position"][:2] == pytest.approx([0, 10000], abs=0.5)
    assert column["rotation"] == pytest.approx(90)
    # Ray 4 at 270°, ring C at 14 m: (0, -14000).
    assert _columns(bim)["C-C4-L1"]["position"][:2] == pytest.approx([0, -14000], abs=0.5)
    # The first ray carries bays on both sides: its columns take the next ray's sizes.
    assert columns["C-A1-L1"]["type"] == columns["C-A2-L1"]["type"]
    # No column repeats the first ray's (the generator's fifth y line is ray 1 again).
    assert len({(c["at"]["x"], c["at"]["y"]) for c in plan["columns"]}) == 12
    # The beam from ray 4 to the closing line ends on ray 1.
    assert any(
        b["start"]["x"] == "4" and b["end"]["x"] == "1" and b["start"]["y"] == "A"
        for b in plan["beams"]
    )
    # The mat: a circle 1 m beyond the outer ring, 14 + 1 = 15 m.
    (mat,) = sub["foundations"]
    assert mat["outline"][0] == pytest.approx([15000, 0])
    assert all(math.hypot(*p) == pytest.approx(15000, abs=0.2) for p in mat["outline"])


def test_radial_sector() -> None:
    # A 90° sector: rays at 30°, 75° and 120° (bays 45° + 45° from a first ray at 30°), rings
    # at 8 and 13 m: 2 × 3 = 6 columns; 2 chords on each of 2 rings + 1 on each of 3 rays = 7
    # beams; 2 slabs.
    _result, plan, sub, bim = _parts(
        {
            "gridsX": [5000],
            "gridKind": "radial",
            "gridAngle": 30,
            "gridOriginX": 1000,
            "gridOriginY": 2000,
            "innerRadius": 8000,
            "rayAngles": [45, 45],
            "storyCount": 1,
            "system": "rcFrame",
            "footing": "isolated",
        }
    )
    assert (len(plan["columns"]), len(plan["beams"]), len(plan["slabs"])) == (6, 7, 2)
    # Ray 3 at 30 + 90 = 120°, ring B at 13 m about (1000, 2000):
    # (1000 + 13000 cos120, 2000 + 13000 sin120) = (-5500, 13258.3).
    expected = (1000 - 6500, 2000 + 13000 * COS30)
    assert _columns(bim)["C-B3-L1"]["position"][:2] == pytest.approx(expected, abs=0.5)
    pad = next(f for f in sub["foundations"] if f["id"] == "F-B3")
    assert pad["center"] == pytest.approx(expected, abs=0.1)
    assert pad["rotation"] == pytest.approx(120)


def test_wizard_document_maps_the_grid() -> None:
    wizard = {
        "schema": "saengine.newBuilding/1",
        "name": "Round",
        "spacings": {"x": [4000, 4000], "y": [90, 90, 90, 90]},
        "storyHeights": [3000],
        "stories": [
            {"id": "BASE", "elevation": 0},
            {"id": "L1", "name": "Level 1", "elevation": 3000},
        ],
        "grid": {"kind": "radial", "angle": 0, "innerRadius": 6000, "rayAngles": [90, 90, 90, 90]},
    }
    spec, _notes = spec_from_wizard(wizard)
    assert spec["gridKind"] == "radial" and "gridsY" not in spec
    assert spec["rayAngles"] == [90, 90, 90, 90]
    # Its bays sized as arcs at the middle ring, 6 + 8 / 2 = 10 m: 10000 × π/2 = 15708 mm.
    _result, plan, _sub, _bim = _parts(spec)
    assert len(plan["columns"]) == 12
    with pytest.raises(NewBuildingError):
        spec_from_wizard({**wizard, "grid": {"kind": "hexagonal"}})


def test_radial_spec_errors() -> None:
    base = {"gridsX": [4000], "gridKind": "radial", "storyCount": 1}
    with pytest.raises(ValueError, match="radius above 0"):
        generate_building({**base, "rayAngles": [90]})
    with pytest.raises(ValueError, match="more than 360"):
        generate_building({**base, "innerRadius": 5000, "rayAngles": [180, 180, 90]})

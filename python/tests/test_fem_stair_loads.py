"""The stairs' loads on the analysis model and the e2k (walkthrough 3, OI-2): their support
reactions from the stair design (saengine.design.stairs), applied where they bear."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest
from test_line_loads import OBJECTS, _applied, plan

from saengine.fem import stair_loads as stl
from saengine.fem.derive import derive_fem
from saengine.library import (
    BuildingModel,
    MaterialLibrary,
    ObjectLibrary,
    ProjectSettings,
    default_material_library,
)
from saengine.library.bim import Stair, generate
from saengine.library.settings import default_project_settings

SAMPLE = (
    Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"
)

#: A straight flight between the beams on grid lines 1 and 2 (5 m apart): 16 risers of 200,
#: treads of 300 (going 15 × 300 = 4500), supported on beams 500 wide: span 4500 + 500 = 5000.
STAIR_TYPE = {
    "id": "ST",
    "name": "Straight stair",
    "kind": "staircase",
    "material": "C24.1",
    "waistThickness": 150,
    "riser": 200,
    "tread": 300,
    "flightWidth": 1200,
    "supportWidth": 500,
}


def _building(levels: int = 2, stair: bool = True) -> Any:
    building = generate(plan(levels), "s")
    if stair:
        building.additions.stairs = [
            Stair(id="S1", type="ST", base="L1", top="L2", x=3000, y=250, direction=90)
        ]
    return building


def _objects() -> ObjectLibrary:
    data = OBJECTS.model_dump(mode="json", by_alias=True)
    data["objects"].append(STAIR_TYPE)
    return ObjectLibrary.model_validate(data)


def _derived(stair: bool) -> Any:
    settings = default_project_settings("Bay")
    return derive_fem(
        _building(stair=stair),
        _objects(),
        default_material_library(),
        settings,
        {"bim": "abc"},
        architecture=False,
    )


def test_straight_flight_between_beams_by_hand() -> None:
    # The flight's mean thickness on plan t / cos θ + R / 2: cos θ = 300 / √(200² + 300²) =
    # 0.83205, 150 / 0.83205 + 100 = 280.28 mm; with C24.1 at 2400 kg/m³ × g = 23.536 kN/m³,
    # 6.5966 kN/m² over the 5.0 m span: 16.49 kN/m at each beam (per metre width), × 1.2 m.
    settings = default_project_settings("Bay")
    found = stl.stair_loads(_building(), _objects(), default_material_library(), settings)
    assert found is not None
    by_part = {s.part: s for s in found.supports}
    assert set(by_part) == {"F1 bottom", "F1 top"}
    bottom, top = by_part["F1 bottom"], by_part["F1 top"]
    weight = 2400 * 9.80665 / 1000 * (150 / (300 / math.hypot(200, 300)) + 100) / 1000
    assert bottom.loads["D"] == pytest.approx(weight * 5.0 / 2, rel=1e-6)
    # The supports: the beams' centres at y = 0 and 5000, on L1 and L2.
    assert (bottom.start[1], top.start[1]) == pytest.approx((0.0, 5000.0))
    assert (bottom.elevation, top.elevation) == (3200.0, 6400.0)
    live = settings.areaLoads[[a.use for a in settings.areaLoads].index("stairs")].live
    assert bottom.loads["L"] == pytest.approx(live * 5.0 / 2)
    # On the beams B?1 and B?3 (grid lines 1 and 2) of L1 and L2, as line loads.
    assert {line.member for line in found.placed.lines} == {"B11", "B23"}
    assert found.applied["D"] == pytest.approx(weight * 5.0 * 1.2, rel=1e-6)
    assert not found.left_out


def test_the_analysis_carries_the_stair() -> None:
    with_stair, without = _derived(True), _derived(False)
    weight = 2400 * 9.80665 / 1000 * (150 / (300 / math.hypot(200, 300)) + 100) / 1000
    added = (_applied(without.project, "D") - _applied(with_stair.project, "D")) / 1e3
    assert added == pytest.approx(weight * 5.0 * 1.2, rel=1e-3)
    live = (_applied(without.project, "L") - _applied(with_stair.project, "L")) / 1e3
    assert live == pytest.approx(4.8 * 5.0 * 1.2, rel=1e-3)
    assert with_stair.summary["stairLoads"]["appliedKN"]["D"] == pytest.approx(added, rel=1e-3)
    assert not any("loads are not applied" in n for n in with_stair.notes)


def _sample() -> tuple[Any, ...]:
    def read(part: str) -> str:
        return (SAMPLE / part).read_text(encoding="utf-8")

    return (
        BuildingModel.model_validate_json(read("06 BIM/bim.json")),
        ObjectLibrary.model_validate_json(read("04 Objects/objects.json")),
        MaterialLibrary.model_validate_json(read("03 Materials/materials.json")),
        ProjectSettings.model_validate_json(read("02 Project Settings/project-settings.json")),
    )


def test_sample_dog_legged_stair_from_the_ground() -> None:
    # ST1 rises from the base (the ground) to L1: its lower flight and the half landing's walls
    # stand on the ground (to its footing), the upper flight's top lands on beam B1 of L1
    # (landing edges, Sec 6.7.1.1 (b): 600 mm into the floor, y = 700 - 600 = 100, within B1's
    # 300 mm width). The live load there: 4.8 kN/m² × the flight's 4.143 m span / 2 = 9.943
    # kN/m over the 1.2 m width = 11.932 kN.
    found = stl.stair_loads(*_sample())
    assert found is not None
    parts = {s.part: s for s in found.supports}
    assert set(parts) == {"F1 bottom", "F2 top", "L1 left", "L1 right"}
    assert parts["L1 left"].moved_from == pytest.approx(1600.0)
    assert {line.member for line in found.placed.lines} == {"B1"}
    assert found.applied["L"] == pytest.approx(11.932, abs=1e-3)
    total = sum(s.total("D") + s.total("SD") for s in found.supports)
    # The whole stair's dead load (flights, half landing, finish) is about 72 kN: the BOQ's
    # 2.32 m³ of concrete is 54.6 kN, the rest the waist's slope, the landing and the finish.
    assert total == pytest.approx(71.96, abs=0.05)
    assert any("stand on the ground" in n for n in found.notes)

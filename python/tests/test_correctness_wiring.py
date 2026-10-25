"""The 0.0.45 correctness round as wired into the analysis model and the design: the design wind
load cases and the live load arrangements as combinations, the arrangement cases of a derived
model, and the beam framing the torsion and deflection checks use."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from saengine.fem.combinations import (
    CaseCombination,
    combination_factors,
    pattern_live_combinations,
    wind_case_combinations,
)
from saengine.library.settings import LoadCombination

WIND = LoadCombination(name="1.2D + 1.6WX + 1.0L", D=1.2, L=1.0, WX=1.6)
GRAVITY = LoadCombination(name="1.2D + 1.6L", D=1.2, L=1.6)
QUAKE = LoadCombination(name="1.2D + 1.0EX + 1.0L", D=1.2, L=1.0, EX=1.0)


def factors_of(combination: LoadCombination) -> dict[str, float]:
    """The factors of a combination in a model without the fluid case F."""
    return combination_factors(combination, set())


def test_case_combination_factors_carry_the_named_cases() -> None:
    combination = CaseCombination(name="c", D=1.2, cases={"LP3": 1.6, "WTX": 0.5})
    assert factors_of(combination) == {"D": 1.2, "SD": 1.2, "LP3": 1.6, "WTX": 0.5}


def test_wind_cases_of_figure_6_2_9() -> None:
    present = {"D", "SD", "L", "WX", "WY", "WTX", "WTY"}
    formed = wind_case_combinations([GRAVITY, WIND, QUAKE], present)
    assert formed is not None
    names = [c.name for c in formed]
    # The gravity and earthquake combinations unchanged; the wind one: Case 1 (itself), 2 x Case 2,
    # 2 x Case 3, 8 x Case 4 (BNBC 2020 Part 6 Figure 6.2.9, p. 574).
    assert names[0] == GRAVITY.name and names[-1] == QUAKE.name
    wind = formed[1:-1]
    assert len(wind) == 13 and wind[0] is WIND
    case2 = [c for c in wind if "Case 2" in c.name]
    assert len(case2) == 2
    assert factors_of(case2[0]) == pytest.approx(
        {"D": 1.2, "SD": 1.2, "L": 1.0, "WX": 0.75 * 1.6, "WTX": 0.75 * 1.6}
    )
    case4 = [c for c in wind if "Case 4" in c.name]
    f = factors_of(case4[0])
    assert f["WX"] == pytest.approx(0.563 * 1.6)
    assert abs(f["WY"]) == abs(f["WTX"]) == abs(f["WTY"]) == pytest.approx(0.563 * 1.6)
    # Without the torsional cases in the model: Cases 1 and 3 only.
    plain = wind_case_combinations([WIND], {"D", "SD", "L", "WX", "WY"})
    assert plain is not None and len(plain) == 3
    assert all("WTX" not in factors_of(c) for c in plain)


def test_live_arrangements_replace_l_in_gravity_combinations_only() -> None:
    present = {"D", "SD", "L", "LP1", "LP2", "WX", "EX"}
    formed = pattern_live_combinations([GRAVITY, WIND, QUAKE], present)
    assert formed is not None
    added = formed[3:]
    assert [c.name for c in added] == ["1.2D + 1.6L [LP1]", "1.2D + 1.6L [LP2]"]
    assert factors_of(added[0]) == {"D": 1.2, "SD": 1.2, "LP1": 1.6}
    assert pattern_live_combinations([GRAVITY], {"D", "L"}) is None


def _three_bays_two_storeys():
    from saengine.library import FloorPlan, ObjectLibrary, default_floor_plan
    from saengine.library.bim import generate

    objects = ObjectLibrary.model_validate(
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
                {
                    "id": "SL",
                    "name": "Slab 150",
                    "kind": "slab",
                    "material": "C24.1",
                    "thickness": 150,
                },
            ]
        }
    )
    base = default_floor_plan().model_dump(mode="json", by_alias=True)
    xs = ["A", "B", "C", "D"]
    grids = {
        "x": [{"label": g, "position": 5000.0 * k} for k, g in enumerate(xs)],
        "y": [{"label": "1", "position": 0.0}, {"label": "2", "position": 5000.0}],
    }
    stories = [
        {"id": "BASE", "name": "Base", "elevation": 0.0},
        {"id": "L1", "name": "Level 1", "elevation": 3200.0},
        {"id": "L2", "name": "Level 2", "elevation": 6400.0},
    ]
    columns, beams, slabs = [], [], []
    for level, below in (("L1", "BASE"), ("L2", "L1")):
        for x in xs:
            for y in ("1", "2"):
                columns.append(
                    {
                        "id": f"C{x}{y}{level}",
                        "type": "COL",
                        "at": {"x": x, "y": y},
                        "base": below,
                        "top": level,
                    }
                )
        for a, c in itertools.pairwise(xs):
            for y in ("1", "2"):
                beams.append(
                    {
                        "id": f"B{a}{c}{y}{level}",
                        "type": "BM",
                        "story": level,
                        "start": {"x": a, "y": y},
                        "end": {"x": c, "y": y},
                    }
                )
            slabs.append(
                {
                    "id": f"S{a}{level}",
                    "type": "SL",
                    "story": level,
                    "boundary": [
                        {"x": a, "y": "1"},
                        {"x": c, "y": "1"},
                        {"x": c, "y": "2"},
                        {"x": a, "y": "2"},
                    ],
                }
            )
        for x in xs:
            beams.append(
                {
                    "id": f"B{x}12{level}",
                    "type": "BM",
                    "story": level,
                    "start": {"x": x, "y": "1"},
                    "end": {"x": x, "y": "2"},
                }
            )
    plan = FloorPlan.model_validate(
        {
            **base,
            "grids": grids,
            "stories": stories,
            "columns": columns,
            "beams": beams,
            "slabs": slabs,
        }
    )
    return generate(plan, "s"), objects


def test_derived_model_has_the_live_load_arrangements() -> None:
    from saengine.fem.derive import derive_fem
    from saengine.fem.end_zones import element_offsets
    from saengine.library import default_material_library
    from saengine.library.settings import default_project_settings

    building, objects = _three_bays_two_storeys()
    settings = default_project_settings("Arrangements")
    d = derive_fem(building, objects, default_material_library(), settings, {"bim": "abc"})
    names = [p["name"] for p in d.project["load_patterns"]]
    # Level 1 carries L (Level 2 is the roof, Lr): one floor, three bays along X: two alternate
    # arrangements and two adjacent pairs; one bay along Y: none.
    arrangements = [n for n in names if n.startswith("LP")]
    assert arrangements == ["LP1", "LP2", "LP3", "LP4"]
    labels = {c["case"]: c["label"] for c in d.summary["patternLive"]["cases"]}
    assert "alternate bays along X: 1, 3" in labels["LP1"]
    assert "adjacent bays along X: 1 and 2" in labels["LP3"]

    coords = {n["id"]: np.array(n["coords"]) for n in d.project["nodes"]}
    elements = {e["id"]: e for e in d.project["elements"]}

    def total(name: str) -> float:
        pattern = next(p for p in d.project["load_patterns"] if p["name"] == name)
        out = sum(n["forces"][2] for n in pattern["nodal_loads"])
        for load in pattern["element_loads"]:
            element = elements[load["element_id"]]
            a, c = (coords[k] for k in element["nodes"])
            # Element loads act on the flexible length (rigid end zones).
            out += load["wz"] * (float(np.linalg.norm(c - a)) - sum(element_offsets(element)))
        return out

    full = total("L")
    live = next(a for a in settings.areaLoads if a.id == settings.floorLoad).live
    assert full == pytest.approx(-live * 1e3 * 75.0, rel=1e-6)  # 3 bays of 5 x 5 m
    # Alternate bays 1 and 3, then 2; adjacent 1-2 and 2-3: their share of the floor.
    assert total("LP1") == pytest.approx(full * 2 / 3, rel=1e-6)
    assert total("LP2") == pytest.approx(full / 3, rel=1e-6)
    assert total("LP3") == pytest.approx(full * 2 / 3, rel=1e-6)
    # The arrangements carry no seismic weight: W is that of the full live load's share.
    off = settings.model_copy(
        update={"analysis": settings.analysis.model_copy(update={"patternLive": "off"})}
    )
    plain = derive_fem(building, objects, default_material_library(), off, {"bim": "abc"})
    assert not [p for p in plain.project["load_patterns"] if p["name"].startswith("LP")]
    assert d.summary["weight_kN"] == pytest.approx(plain.summary["weight_kN"], rel=1e-9)


def test_beam_framing_finds_supports_ends_and_slabs() -> None:
    from saengine.design.check import _BeamFraming

    building, objects = _three_bays_two_storeys()
    types = {o.id: o for o in objects.objects}
    framing = _BeamFraming(building, types)
    beam = next(e for e in building.elements if e.id == "BAB1L1")
    assert framing.support_stations(beam) == pytest.approx([0.0, 1.0])
    assert framing.end_held(beam, 0) and framing.end_held(beam, 1)
    assert framing.continues(beam, 1) and not framing.continues(beam, 0)
    # An edge beam (grid 1): slab on one side only; an interior beam along Y: both sides.
    assert framing.slab_beside(beam, 300.0) == (150.0, 1)
    inner = next(e for e in building.elements if e.id == "BB12L1")
    assert framing.slab_beside(inner, 300.0) == (150.0, 2)
    assert not framing.carries_cantilever(beam, 300.0)


def test_sample_beam_framing() -> None:
    """The sample's edge beam B1 (0, 0)-(6, 0) at Level 1: the columns C7 at its start and C1
    150 mm along it are one support; its slab S1 has a free edge (x = 0) across it, not
    parallel to it, so S1 does not cantilever from B1 (compatibility torsion)."""
    import json
    from pathlib import Path

    from saengine.design.check import _BeamFraming
    from saengine.library import ObjectLibrary
    from saengine.library.bim import BuildingModel

    sample = (
        Path(__file__).resolve().parents[2] / "workbench/resources/saengine/samples/Sample Frame"
    )
    building = BuildingModel.model_validate_json(
        (sample / "06 BIM" / "bim.json").read_text(encoding="utf-8")
    )
    objects = ObjectLibrary.model_validate(
        json.loads((sample / "04 Objects" / "objects.json").read_text(encoding="utf-8"))
    )
    framing = _BeamFraming(building, {o.id: o for o in objects.objects})
    b1 = next(e for e in building.elements if e.id == "B1")
    assert framing.support_stations(b1) == pytest.approx([0.0, 1.0])
    assert framing.end_held(b1, 0) and framing.end_held(b1, 1)
    assert framing.slab_beside(b1, 300.0) == (150.0, 1)
    assert not framing.carries_cantilever(b1, 300.0)
    # B5 (x = 6 m): S1's free edge x = 0 is parallel to it, but S1 is held across it by B1
    # and B3, so it spans to them: no cantilever from B5 either.
    b5 = next(e for e in building.elements if e.id == "B5")
    assert framing.slab_beside(b5, 300.0) == (150.0, 2)
    assert not framing.carries_cantilever(b5, 300.0)

"""Input guardrails (U2): impossible values blocked, unusual ones warned, on every entry path."""

from __future__ import annotations

import json

import pytest

from saengine.library import guardrails
from saengine.library.check import check_library
from saengine.library.defaults import (
    default_floor_plan,
    default_material_library,
    default_object_library,
)


def _json(model) -> dict:
    return json.loads(model.model_dump_json(by_alias=True, exclude_none=True))


def test_defaults_have_no_guardrail_problems() -> None:
    for kind, doc in (
        ("materials", default_material_library()),
        ("objects", default_object_library()),
        ("floorPlan", default_floor_plan()),
    ):
        assert guardrails.check(kind, _json(doc)) == [], kind


def test_every_rule_has_a_reason_and_practice_limits_are_marked() -> None:
    for rule in guardrails.rules_document()["rules"]:
        kinds = {"materials", "objects", "floorPlan", "memberLoads", "settings", "project"}
        assert rule["kind"] in kinds, rule["id"]
        for limit in rule.get("block", []) + rule.get("warn", []):
            assert limit["reason"], rule["id"]
    for rule in guardrails.resolved_rules():
        for limit in rule["block"] + rule["warn"]:
            assert limit["source"], rule["id"]
            if "fromPack" not in limit and rule["id"] != "systemHeight":
                assert limit["source"] == guardrails.PRACTICE or "BNBC" in limit["source"]


def test_pack_limits_come_from_the_code_pack() -> None:
    fc = guardrails.rule("concreteStrength")
    assert any(w.get("min") == 17.0 and "6.1.3.6" in w["source"] for w in fc["warn"])
    fy = guardrails.rule("reinforcementStrength")
    assert any(b.get("max") == 550.0 for b in fy["block"])
    bars = guardrails.rule("barSize")["block"][0]["oneOf"]
    assert 16.0 in bars and 17.0 not in bars


def test_materials_block_impossible_and_warn_unusual_strengths() -> None:
    data = _json(default_material_library())
    concrete = next(m for m in data["materials"] if m["category"] == "concrete")
    concrete["concrete"]["fc"] = 3
    problems = check_library("materials", json.dumps(data))
    fc = [p for p in problems if p["path"] == "concrete.fc"]
    assert fc[0]["severity"] == "error" and "below 5 MPa" in fc[0]["message"]
    concrete["concrete"]["fc"] = 12  # lean concrete: possible, below the code's structural least
    fc = [p for p in check_library("materials", json.dumps(data)) if p["path"] == "concrete.fc"]
    assert fc[0]["severity"] == "warning" and "17 MPa" in fc[0]["message"]
    rebar = next(m for m in data["materials"] if m["category"] == "rebar")
    rebar["steel"]["fy"] = 600
    fy = [p for p in guardrails.check("materials", data) if p["path"] == "steel.fy"]
    assert fy[0]["severity"] == "error" and "550 MPa" in fy[0]["message"]


def test_objects_cover_larger_than_the_member_and_bar_sizes() -> None:
    data = _json(default_object_library())
    column = next(o for o in data["objects"] if o["kind"] == "column")
    column["reinforcement"]["cover"] = column["profile"]["xDim"] / 2
    column["reinforcement"]["longitudinal"][0]["dia"] = 17
    found = {p["path"]: p for p in guardrails.check("objects", data)}
    assert found["reinforcement.cover"]["severity"] == "error"
    assert "no concrete inside" in found["reinforcement.cover"]["message"]
    assert found["reinforcement.longitudinal.0.dia"]["severity"] == "error"


def test_floor_plan_storey_heights_spans_and_counts() -> None:
    data = _json(default_floor_plan())
    data["stories"][1]["elevation"] = data["stories"][0]["elevation"] + 400
    data["grids"]["x"][1]["position"] = data["grids"]["x"][0]["position"] + 50
    found = {p["path"]: p for p in check_library("floorPlan", json.dumps(data))}
    assert found["stories.1.elevation"]["severity"] == "error"
    assert found["grids.x.1.position"]["severity"] == "error"
    data = _json(default_floor_plan())
    data["stories"][1]["elevation"] = data["stories"][0]["elevation"] + 9000
    found = {p["path"]: p for p in guardrails.check("floorPlan", data)}
    assert found["stories.1.elevation"]["severity"] == "warning"


def test_gravity_loads_entered_upward_are_blocked() -> None:
    data = {"loads": [{"id": "P1", "kind": "point", "value": -5}]}
    (problem,) = guardrails.check("memberLoads", data)
    assert problem["severity"] == "error" and "downward" in problem["message"]


def test_new_project_spec_uses_the_same_rules() -> None:
    from saengine.library.generator import BuildingSpec

    with pytest.raises(ValueError, match="storeys is more than 200"):
        BuildingSpec(gridsX=[6000], gridsY=[6000], storyCount=500)
    with pytest.raises(ValueError, match="below 100 mm"):
        BuildingSpec(gridsX=[50], gridsY=[6000], storyCount=2)
    BuildingSpec(gridsX=[6000] * 3, gridsY=[6000], storyCount=90)  # tall: a warning only


# ── track D of the AI round: the mistakes an assistant makes (units, sizes, heights) ──


def _plan(spans_x, spans_y, heights) -> dict:
    """A floor plan with grid lines A.. and 1.. at the spans and storeys of the heights."""
    xs, ys, levels = [0.0], [0.0], [0.0]
    for s in spans_x:
        xs.append(xs[-1] + s)
    for s in spans_y:
        ys.append(ys[-1] + s)
    for h in heights:
        levels.append(levels[-1] + h)
    return {
        "schema": "saengine.floorplan/1",
        "grids": {
            "x": [{"label": chr(65 + i), "position": x} for i, x in enumerate(xs)],
            "y": [{"label": str(i + 1), "position": y} for i, y in enumerate(ys)],
        },
        "stories": [
            {"id": f"L{i}", "name": f"Level {i}", "elevation": e} for i, e in enumerate(levels)
        ],
        "columns": [],
        "beams": [],
        "slabs": [],
    }


def _objects(*entries: dict) -> dict:
    return {"schema": "saengine.objects/1", "objects": list(entries)}


def _beam(type_id: str, depth: float) -> dict:
    profile = {"shape": "rectangle", "xDim": 250, "yDim": depth}
    return {"id": type_id, "kind": "beam", "profile": profile}


def _line(member: str, a: tuple[str, str], b: tuple[str, str], type_id: str) -> dict:
    start, end = {"x": a[0], "y": a[1]}, {"x": b[0], "y": b[1]}
    return {"id": member, "type": type_id, "story": "L1", "start": start, "end": end}


def test_a_storey_of_20_m_or_more_is_refused_with_the_allowed_range() -> None:
    data = _plan([5000], [5000], [3000, 25000])
    found = {p["path"]: p for p in guardrails.check("floorPlan", data)}
    problem = found["stories.2.elevation"]
    assert problem["severity"] == "error"
    assert "above 20000 mm" in problem["message"] and "2.8 to 4.5 m" in problem["message"]
    data = _plan([5000], [5000], [3000, 7000])
    assert {p["severity"] for p in guardrails.check("floorPlan", data)} == {"warning"}


def test_a_span_given_in_metres_or_too_long_is_refused() -> None:
    found = guardrails.check("floorPlan", _plan([5], [5000], [3000]))
    assert any(p["severity"] == "error" and "below 100 mm" in p["message"] for p in found)
    found = guardrails.check("floorPlan", _plan([70000], [5000], [3000]))
    assert any(p["severity"] == "error" and "above 60000 mm" in p["message"] for p in found)
    found = guardrails.check("floorPlan", _plan([13000], [5000], [3000]))
    assert [p["severity"] for p in found] == ["warning"]


def test_beam_depth_against_its_span() -> None:
    data = _plan([15000], [5000], [3000])
    data["beams"] = [
        _line("B1", ("A", "1"), ("B", "1"), "B300"),
        _line("B2", ("A", "2"), ("B", "2"), "B450"),
        _line("B3", ("A", "1"), ("A", "2"), "B750"),
    ]
    objects = _objects(_beam("B300", 300), _beam("B450", 450), _beam("B750", 750))
    found = {p["path"]: p for p in guardrails.check("floorPlan", data, objects=objects)}
    message = found["beams.0.type"]["message"]
    assert found["beams.0.type"]["severity"] == "error"
    assert "B1: span/depth of a 15000 mm span 300 mm deep (B300) 50 is above 35" in message
    assert "at least 430 mm deep" in message
    assert found["beams.1.type"]["severity"] == "warning"  # 33: shallow, the checks decide
    assert "beams.2.type" not in found
    # Without the object types the rule is not checked.
    assert not any(p["path"].startswith("beams") for p in guardrails.check("floorPlan", data))
    # The same rule through the editors' check (objects.json as the companion file).
    problems = check_library("floorPlan", json.dumps(data), json.dumps(objects))
    assert any(p["path"] == "beams.0.type" and p["severity"] == "error" for p in problems)


def test_slab_thickness_against_its_panel() -> None:
    data = _plan([6000], [6000], [3000])
    corners = [{"x": x, "y": y} for x, y in (("A", "1"), ("B", "1"), ("B", "2"), ("A", "2"))]
    data["slabs"] = [{"id": "S1", "type": "S80", "story": "L1", "boundary": corners}]
    objects = _objects({"id": "S80", "kind": "slab", "thickness": 80})
    (problem,) = guardrails.check("floorPlan", data, objects=objects)
    assert problem["severity"] == "error" and "at least 100 mm thick" in problem["message"]
    objects = _objects({"id": "S80", "kind": "slab", "thickness": 150})
    assert guardrails.check("floorPlan", data, objects=objects) == []


def test_loads_in_the_wrong_unit_are_refused() -> None:
    settings = {"areaLoads": [{"id": "FL", "live": 2000, "finish": 1.5, "partitions": 1.0}]}
    (problem,) = guardrails.check("settings", settings)
    assert problem["path"] == "areaLoads.0.live" and problem["severity"] == "error"
    assert "kN/m²" in problem["message"] and "psf" in problem["message"]
    settings["areaLoads"][0]["live"] = 20
    (problem,) = guardrails.check("settings", settings)
    assert problem["severity"] == "warning"
    loads = {"loads": [{"id": "LL1", "kind": "line", "value": 25000}]}
    (problem,) = guardrails.check("memberLoads", loads)
    assert problem["severity"] == "error" and "not N/m or N" in problem["message"]


def test_storeys_against_the_height_limit_of_the_structural_system() -> None:
    from saengine.library.settings import default_project_settings

    settings = json.loads(
        default_project_settings("X").model_dump_json(by_alias=True, exclude_none=True)
    )
    settings["seismic"]["system"] = "steelOcbf"  # Dhaka, SD: Category D, at most 11 m
    data = _plan([5000], [5000], [3000] * 5)
    (problem,) = guardrails.check("floorPlan", data, settings=settings)
    assert problem["severity"] == "error" and problem["path"] == "stories.5.elevation"
    message = problem["message"]
    assert "15.0 m tall (5 storeys), above the 11 m height limit" in message
    assert "Seismic Design Category D" in message and "at most 3 storeys of 3.0 m" in message
    assert "Table 6.2.19" in message
    low = _plan([5000], [5000], [3000] * 3)
    assert guardrails.check("floorPlan", low, settings=settings) == []
    settings["seismic"]["system"] = "rcSmf"  # no limit
    assert guardrails.check("floorPlan", data, settings=settings) == []

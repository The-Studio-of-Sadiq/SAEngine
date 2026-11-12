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
        assert rule["kind"] in {"materials", "objects", "floorPlan", "memberLoads"}, rule["id"]
        for limit in rule.get("block", []) + rule.get("warn", []):
            assert limit["reason"], rule["id"]
    for rule in guardrails.resolved_rules():
        for limit in rule["block"] + rule["warn"]:
            assert limit["source"], rule["id"]
            if "fromPack" not in limit:
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

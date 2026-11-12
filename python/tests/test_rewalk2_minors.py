"""Re-walk 2 minors: the floor plan's stamp without its underlays (R2-10 second half, OI-24)
and the slab thickness note of the design proposal (R2-18)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from saengine.design.proposal import _thin_slabs
from saengine.library.bim import floor_plan_current, floor_plan_stamp, source_stamp
from saengine.pipeline import drawings as d

#: A floor plan as the workbench writes it (tabs), with an underlay. The same text and stamp
#: are in partSources.test.ts (floorPlanStamp): the two sides must agree.
PLAN = {
    "schema": "saengine.floorPlan/1",
    "grids": {"x": [{"label": "A", "position": 0}, {"label": "B", "position": 6000.5}], "y": []},
    "stories": [{"id": "L1", "name": "Level 1", "elevation": 3600}],
    "columns": [],
    "underlays": [{"file": "plan.dxf", "story": "L1", "scale": 1.0}],
}
STAMP = "0a246b6025a9f94811161541eb2aa347b6392c2e"


def test_underlays_leave_the_floor_plan_stamp_alone() -> None:
    text = json.dumps(PLAN, indent="\t")
    bare = json.dumps({k: v for k, v in PLAN.items() if k != "underlays"}, indent="\t")
    moved = json.loads(text)
    moved["underlays"][0]["scale"] = 2.0
    assert floor_plan_stamp(text) == floor_plan_stamp(bare) == floor_plan_stamp(json.dumps(moved))
    assert floor_plan_stamp(text) == STAMP
    # A change to the building does change it.
    changed = json.loads(text)
    changed["stories"][0]["elevation"] = 3500
    assert floor_plan_stamp(json.dumps(changed)) != STAMP
    # Building models recorded the whole text's stamp before: still current while it is the same.
    assert floor_plan_current(source_stamp(text), text)
    assert floor_plan_current(floor_plan_stamp(text), json.dumps(moved))
    assert not floor_plan_current(source_stamp(text), json.dumps(moved))
    assert floor_plan_stamp("not json") == source_stamp("not json")


def test_drawings_are_not_stale_after_an_underlay(tmp_path) -> None:
    plan = tmp_path / "05 Floor Plan" / "floor-plan.json"
    plan.parent.mkdir(parents=True)
    plan.write_text(json.dumps(PLAN, indent="\t"), encoding="utf-8")
    recorded = d.input_stamps(tmp_path)
    moved = dict(PLAN, underlays=[{"file": "other.pdf", "story": "L1"}])
    plan.write_text(json.dumps(moved, indent="\t"), encoding="utf-8")
    assert d.changed_sources(recorded, d.input_stamps(tmp_path)) == []
    # A set drawn before (the whole text's stamp) stays current until the plan changes.
    legacy = dict(recorded, floorPlan=source_stamp(plan.read_text(encoding="utf-8")))
    assert d.changed_sources(legacy, d.input_stamps(tmp_path)) == []
    moved["stories"] = [{"id": "L1", "name": "Level 1", "elevation": 3000}]
    plan.write_text(json.dumps(moved, indent="\t"), encoding="utf-8")
    assert d.changed_sources(recorded, d.input_stamps(tmp_path)) == ["Floor Plan"]


def test_thin_slabs_are_said_with_the_thickness_to_try() -> None:
    row = {"name": "Min. thickness (Table 8.3.1.2)", "demand": 136.2, "capacity": 125.0,
           "ok": False, "flag": True}  # fmt: skip
    passing = dict(row, demand=120.0, ok=True)
    collected = [
        {"id": "S1", "checks": [row]},
        {"id": "S2", "checks": [dict(row, demand=131.0)]},
        {"id": "S3", "checks": [passing]},
    ]
    note = _thin_slabs("S125", SimpleNamespace(thickness=125.0), collected)
    assert note == (
        "S125: 2 of its 3 slabs are thinner than the least thickness of Table 8.3.1.2 (up to "
        "136 mm needed, 125 mm given): try 150 mm, or check their deflection by calculation; "
        "bars do not cure it, and the analysis must be run again"
    )
    assert _thin_slabs("S125", SimpleNamespace(thickness=125.0), [collected[2]]) is None

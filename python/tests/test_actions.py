"""The shared editing actions (saengine.actions): one test per action, the all-or-nothing batch,
the guardrail refusals, the command line, the RPC handlers and the generated catalogue.

The edits run with ``write=False`` on one small project built once for the module (a 2x1-bay,
two-storey frame) and read the changed texts the batch returns; tests that write work on a copy.
The whole project from an empty folder to the report is tests/test_actions_e2e.py."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from saengine.actions import ActionResult, BatchResult, get, list_actions, run_actions
from saengine.actions.paths import (
    FLOOR_PLAN,
    LOADS,
    MATERIALS,
    OBJECTS,
    SETTINGS,
    SOIL,
    SUBSTRUCTURE,
)

ROOT = Path(__file__).resolve().parents[2]

#: The minimum catalogue of the brief (.claude/usability/brief-actions-round.md).
BRIEF = {
    "project.summary",
    "members.list",
    "results.summary",
    "checks.list",
    "actions.help",
    "project.create",
    "building.generate",
    "settings.code_pack",
    "settings.site",
    "settings.use",
    "settings.analysis",
    "soil.borehole.add",
    "soil.layer.add",
    "soil.spt.add",
    "soil.allowable_bearing.set",
    "grid.set",
    "grid.line.add",
    "grid.line.move",
    "grid.line.delete",
    "storeys.set",
    "storey.add",
    "storey.delete",
    "storey.height",
    "storey.typical",
    "material.concrete.add",
    "material.concrete.set",
    "material.steel.add",
    "material.steel.set",
    *(
        f"type.{k}.{v}"
        for k in ("column", "beam", "slab", "wall", "footing")
        for v in ("add", "set")
    ),
    "columns.place",
    "beams.place",
    "slabs.place",
    "walls.place",
    "member.set",
    "member.delete",
    "members.copy_to_storeys",
    "load.area.set",
    "load.line.add",
    "load.point.add",
    "load.wall.add",
    "foundations.generate",
    "footing.set",
    "run.all",
    "run.step",
    "design.reinforcement.apply",
    "export.drawings",
    "export.report",
    "export.ifc",
    "export.boq",
    "export.archive",
}

BASE_STEPS = [
    {"action": "project.create", "params": {"name": "Base"}},
    {"action": "grid.set", "params": {"x": [5000, 5000], "y": [4000]}},
    {"action": "storeys.set", "params": {"count": 2, "height": 3000}},
    {"action": "columns.place", "params": {"type": "C400x400"}},
    {"action": "beams.place", "params": {"type": "B250x450"}},
    {"action": "slabs.place", "params": {"type": "S125"}},
]


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("actions") / "Base"
    result = run_actions(root, BASE_STEPS, write=True)
    assert result.ok, [r.message for r in result.results]
    return root


@pytest.fixture
def copy(base: Path, tmp_path: Path) -> Path:
    target = tmp_path / "Copy"
    shutil.copytree(base, target)
    return target


def run(root: Path, *steps: tuple[str, dict[str, Any]], **options: Any) -> BatchResult:
    return run_actions(root, [{"action": a, "params": p} for a, p in steps], **options)


def one(root: Path, name: str, params: dict[str, Any] | None = None) -> tuple[ActionResult, dict]:
    """The result of one action and its changed parts (parsed)."""
    batch = run(root, (name, params or {}))
    return batch.results[-1], {k: json.loads(v) for k, v in batch.changes.items()}


def refused(root: Path, name: str, params: dict[str, Any]) -> ActionResult:
    batch = run(root, (name, params))
    assert not batch.ok and batch.changes == {} and batch.failed_step == 0
    result = batch.results[0]
    assert result.problems, result.message
    return result


def plan_of(changes: dict) -> dict:
    return changes[FLOOR_PLAN]


# ─────────────────────────────── the catalogue ───────────────────────────────


def test_catalogue_has_the_brief_minimum():
    names = {a.name for a in list_actions()}
    assert BRIEF <= names, sorted(BRIEF - names)
    for info in list_actions():
        assert info.kind in ("edit", "run", "query")
        assert info.params_schema.get("type") == "object"
        assert info.example is not None, info.name
        info.params.model_validate(info.example)
    assert {a.kind for a in list_actions("query")} == {"query"}


def test_unknown_action_and_bad_parameters_are_refused(base):
    batch = run(base, ("columns.plant", {}))
    assert not batch.ok and "no action 'columns.plant'" in batch.results[0].message
    result = refused(base, "columns.place", {"type": "C400x400", "rotaton": 5})
    assert result.problems[0].field == "rotaton"


def test_docs_catalogue_is_up_to_date():
    spec = importlib.util.spec_from_file_location(
        "gen_actions_doc", ROOT / "scripts" / "docs" / "gen_actions_doc.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    current = (ROOT / "docs" / "actions.md").read_text(encoding="utf-8")
    assert module.generate() == current, "run python -I scripts/docs/gen_actions_doc.py"


# ─────────────────────────────── project ───────────────────────────────


def test_project_create_empty(tmp_path):
    result = run(tmp_path / "New", ("project.create", {"name": "New", "occupancy": "office"}))
    assert result.ok
    assert "New.saengine" in result.changes and FLOOR_PLAN in result.changes
    settings = json.loads(result.changes[SETTINGS])
    assert settings["occupancy"]["use"] == "office"
    assert not (tmp_path / "New").exists()  # write=False writes nothing


def test_project_create_refuses_an_existing_project(base):
    result = refused(base, "project.create", {"name": "Again"})
    assert "already" in result.message


def test_project_create_with_a_building(tmp_path):
    building = {"gridsX": [5000], "gridsY": [4000], "storyCount": 2}
    batch = run(tmp_path / "Gen", ("project.create", {"name": "Gen", "building": building}))
    assert batch.ok, batch.results[0].message
    plan = json.loads(batch.changes[FLOOR_PLAN])
    assert len(plan["columns"]) == 8 and json.loads(batch.changes[SUBSTRUCTURE])["foundations"]


def test_building_generate(base):
    building = {"gridsX": [6000], "gridsY": [5000], "storyCount": 1}
    result = refused(base, "building.generate", {"building": building})
    assert result.problems[0].field == "replace"
    result, changes = one(base, "building.generate", {"building": building, "replace": True})
    assert result.ok and len(plan_of(changes)["columns"]) == 4


# ─────────────────────────────── settings ───────────────────────────────


def test_settings_code_pack(base):
    result, changes = one(base, "settings.code_pack", {"codePack": "aci318-asce7-22"})
    assert result.ok, result.message
    assert changes[SETTINGS]["codePack"] == "aci318-asce7-22"
    assert refused(base, "settings.code_pack", {"codePack": "no-such-pack"}).problems


def test_settings_site(base):
    _result, changes = one(
        base, "settings.site", {"siteClass": "SC", "windSpeed": 50, "allowableBearing": 120}
    )
    site = changes[SETTINGS]["site"]
    assert site["siteClass"] == "SC" and site["siteClassSource"] == "entered"
    assert site["windSpeed"] == 50 and changes[SETTINGS]["foundation"]["allowableBearing"] == 120
    assert refused(base, "settings.site", {"siteClass": "S9"}).problems[0].part == SETTINGS


def test_settings_use_takes_the_packs_live_load(base):
    _result, changes = one(base, "settings.use", {"occupancy": "office", "floorFinish": 1.5})
    floor = next(a for a in changes[SETTINGS]["areaLoads"] if a["id"] == "FL")
    assert changes[SETTINGS]["occupancy"]["use"] == "office"
    assert floor["use"] == "office" and floor["finish"] == 1.5 and floor["live"] > 2


def test_settings_analysis(base):
    _result, changes = one(base, "settings.analysis", {"set": {"meshSize": 750}})
    assert changes[SETTINGS]["analysis"]["meshSize"] == 750
    assert refused(base, "settings.analysis", {"set": {"meshSise": 1}}).problems[0].value == [
        "meshSise"
    ]


# ─────────────────────────────── soil ───────────────────────────────


def test_soil_borehole_layer_and_spt(base):
    batch = run(
        base,
        ("soil.borehole.add", {"x": 0, "y": 0, "waterTable": 1500}),
        ("soil.layer.add", {"borehole": "BH-1", "top": 0, "bottom": 3000, "soilType": "clay"}),
        ("soil.layer.add", {"borehole": "BH-1", "top": 3000, "bottom": 9000, "soilType": "sand"}),
        ("soil.spt.add", {"borehole": "BH-1", "depth": 1500, "N": 6}),
    )
    assert batch.ok, [r.message for r in batch.results]
    hole = json.loads(batch.changes[SOIL])["boreholes"][0]
    assert hole["id"] == "BH-1" and len(hole["layers"]) == 2 and hole["spt"][0]["N"] == 6
    overlap = run(
        base,
        ("soil.borehole.add", {"x": 0, "y": 0}),
        ("soil.layer.add", {"borehole": "BH-1", "top": 0, "bottom": 3000, "soilType": "clay"}),
        ("soil.layer.add", {"borehole": "BH-1", "top": 2000, "bottom": 4000, "soilType": "clay"}),
    )
    assert not overlap.ok and overlap.failed_step == 2 and overlap.changes == {}
    assert refused(base, "soil.spt.add", {"borehole": "BH-9", "depth": 1000, "N": 3}).problems


def test_soil_allowable_bearing(base):
    _result, changes = one(base, "soil.allowable_bearing.set", {"value": 150})
    assert changes[SETTINGS]["foundation"]["allowableBearing"] == 150
    assert refused(base, "soil.allowable_bearing.set", {"value": -5}).problems[0].part == SETTINGS


# ─────────────────────────────── grid and storeys ───────────────────────────────


def test_grid_set_and_its_guardrail(base):
    result, changes = one(base, "grid.set", {"x": [6000, 6000], "y": [5000]})
    assert [g["position"] for g in plan_of(changes)["grids"]["x"]] == [0, 6000, 12000]
    result = refused(base, "grid.set", {"x": [50, 5000], "y": [4000]})
    assert (
        "grids.x" in result.problems[0].field and "SAEngine practice" in result.problems[0].reason
    )
    assert "Members stand on" in refused(base, "grid.set", {"x": [5000], "y": [4000]}).message


def test_grid_lines(base):
    result, changes = one(base, "grid.line.add", {"axis": "x", "position": 15000})
    assert result.created == ["D"] and plan_of(changes)["grids"]["x"][-1]["label"] == "D"
    result, changes = one(base, "grid.line.move", {"label": "B", "by": 500})
    assert plan_of(changes)["grids"]["x"][1]["position"] == 5500
    assert "deleteMembers" in refused(base, "grid.line.delete", {"label": "C"}).message
    result, changes = one(base, "grid.line.delete", {"label": "C", "deleteMembers": True})
    plan = plan_of(changes)
    assert [g["label"] for g in plan["grids"]["x"]] == ["A", "B"]
    assert all(c["at"]["x"] != "C" for c in plan["columns"])


def test_storeys_set_and_its_guardrail(base):
    result, changes = one(base, "storeys.set", {"count": 2, "height": 3300})
    assert [s["elevation"] for s in plan_of(changes)["stories"]] == [0, 3300, 6600]
    result = refused(base, "storeys.set", {"count": 2, "height": 300})
    assert "storey height" in result.message.lower()


def test_storey_add_height_delete(base):
    result, changes = one(base, "storey.add", {"height": 3000, "name": "Roof"})
    assert result.created == ["L3"] and plan_of(changes)["stories"][-1]["elevation"] == 9000
    result, changes = one(base, "storey.height", {"id": "L1", "height": 3600})
    assert [s["elevation"] for s in plan_of(changes)["stories"]] == [0, 3600, 6600]
    assert "deleteMembers" in refused(base, "storey.delete", {"id": "L2"}).message
    result, changes = one(base, "storey.delete", {"id": "L2", "deleteMembers": True})
    plan = plan_of(changes)
    assert [s["id"] for s in plan["stories"]] == ["BASE", "L1"]
    assert all(c["top"] == "L1" for c in plan["columns"])


def test_storey_typical_copies_the_masters_plan(base):
    batch = run(
        base,
        ("storey.add", {"height": 3000}),
        ("storey.typical", {"master": "L2", "storeys": ["L3"]}),
    )
    assert batch.ok, [r.message for r in batch.results]
    plan = json.loads(batch.changes[FLOOR_PLAN])
    assert plan["stories"][-1]["similarTo"] == "L2"
    assert sum(1 for c in plan["columns"] if c["top"] == "L3") == 6
    assert sum(1 for b in plan["beams"] if b["story"] == "L3") == 7


# ─────────────────────────────── materials and types ───────────────────────────────


def test_concrete_add_and_set(base):
    result, changes = one(base, "material.concrete.add", {"fc": 28, "makeDefault": True})
    lib = changes[MATERIALS]
    concrete = next(m for m in lib["materials"] if m["id"] == "C28")
    assert lib["defaults"]["concrete"] == "C28" and 24000 < concrete["mechanical"]["E"] < 26000
    result, changes = one(base, "material.concrete.set", {"id": "C24.1", "fc": 30})
    concrete = next(m for m in changes[MATERIALS]["materials"] if m["id"] == "C24.1")
    assert concrete["concrete"]["fc"] == 30 and concrete["mechanical"]["E"] > 25000
    result = refused(base, "material.concrete.add", {"fc": 2})
    assert result.problems[0].field.endswith("concrete.fc") and result.problems[0].value == 2


def test_steel_add_and_set(base):
    _result, changes = one(
        base, "material.steel.add", {"kind": "rebar", "fy": 500, "grade": "B500"}
    )
    bar = next(m for m in changes[MATERIALS]["materials"] if m["id"] == "B500")
    assert bar["category"] == "rebar" and bar["mechanical"]["E"] == 200000
    _result, changes = one(base, "material.steel.set", {"id": "A992", "fy": 350})
    assert (
        next(m for m in changes[MATERIALS]["materials"] if m["id"] == "A992")["steel"]["fy"] == 350
    )
    assert refused(base, "material.steel.add", {"kind": "rebar", "fy": 5000}).problems


@pytest.mark.parametrize(
    ("kind", "params", "made"),
    [
        ("column", {"width": 450, "depth": 450}, "C450x450"),
        ("beam", {"width": 300, "depth": 600}, "B300x600"),
        ("slab", {"thickness": 150, "system": "oneWay"}, "S150"),
        ("wall", {"thickness": 250}, "W250"),
        ("footing", {"length": 1500, "footingWidth": 1500, "thickness": 450}, "F1500x1500x450"),
    ],
)
def test_type_add_and_set(base, kind, params, made):
    result, changes = one(base, f"type.{kind}.add", params)
    assert result.created == [made], result.message
    entry = next(o for o in changes[OBJECTS]["objects"] if o["id"] == made)
    assert entry["kind"] == kind and entry["material"]
    existing = {"column": "C400x400", "beam": "B250x450", "slab": "S125", "wall": "W200"}
    if kind in existing:
        size = {"width": 500, "depth": 500} if kind in ("column", "beam") else {"thickness": 175}
        result, changes = one(base, f"type.{kind}.set", {"id": existing[kind], **size})
        entry = next(o for o in changes[OBJECTS]["objects"] if o["id"] == existing[kind])
        assert entry.get("thickness", entry.get("profile", {}).get("xDim")) in (500, 175)


def test_type_guardrails(base):
    result = refused(base, "type.column.add", {"width": 50000, "depth": 400})
    assert result.problems[0].part == OBJECTS and "30000" in result.problems[0].reason
    assert refused(base, "type.slab.add", {"thickness": -10}).problems
    assert "beam" in refused(base, "type.column.set", {"id": "B250x450", "width": 300}).message


# ─────────────────────────────── members ───────────────────────────────


def test_columns_place(tmp_path):
    root = tmp_path / "P"
    batch = run(
        root,
        ("project.create", {"name": "P"}),
        ("grid.set", {"x": [5000], "y": [4000]}),
        ("storeys.set", {"count": 2, "height": 3000}),
        ("columns.place", {"type": "C400x400", "points": ["A-1", "B/2"], "storeys": ["L1"]}),
        ("columns.place", {"type": "C400x400"}),
    )
    assert batch.ok, [r.message for r in batch.results]
    assert batch.results[3].created == ["C1", "C2"]
    assert len(batch.results[4].created) == 6 and batch.results[4].warnings  # 2 were there
    plan = json.loads(batch.changes[FLOOR_PLAN])
    c1 = plan["columns"][0]
    assert c1["base"] == "BASE" and c1["top"] == "L1" and c1["at"]["x"] == "A"


def test_member_placement_refusals(base):
    assert (
        "already"
        in refused(
            base, "columns.place", {"type": "C400x400", "points": ["A-1"], "storeys": ["L1"]}
        ).message
    )
    assert (
        "not a grid point"
        in refused(base, "columns.place", {"type": "C400x400", "points": ["Q-9"]}).message
    )
    assert "is a beam" in refused(base, "columns.place", {"type": "B250x450"}).message
    assert (
        "no storey" in refused(base, "beams.place", {"type": "B250x450", "storeys": ["L7"]}).message
    )


def test_beams_walls_slabs_place(base):
    batch = run(
        base,
        ("member.delete", {"ids": ["B1"]}),
        ("beams.place", {"type": "B250x450", "between": "all", "lines": ["1"], "storeys": ["L1"]}),
    )
    assert batch.ok and len(batch.results[1].created) == 1
    _result, changes = one(
        base, "walls.place", {"type": "W200", "between": [["A-1", "A-2"]], "storeys": ["L1"]}
    )
    wall = plan_of(changes)["walls"][0]
    assert wall["id"] == "W1" and wall["base"] == "BASE" and wall["top"] == "L1"
    batch = run(
        base,
        ("member.delete", {"ids": ["S1"]}),
        ("slabs.place", {"type": "S125", "panels": ["A-1"], "storeys": ["L1"], "areaLoad": "RF"}),
    )
    assert batch.ok, [r.message for r in batch.results]
    slab = json.loads(batch.changes[FLOOR_PLAN])["slabs"][-1]
    assert slab["areaLoad"] == "RF" and len(slab["boundary"]) == 4


def test_member_set_delete_and_copy(base):
    _result, changes = one(base, "member.set", {"ids": ["C1"], "rotation": 90, "dx": 100})
    column = plan_of(changes)["columns"][0]
    assert column["rotation"] == 90 and column["at"]["dx"] == 100
    assert "has no rotation" in refused(base, "member.set", {"ids": ["B1"], "rotation": 5}).message
    batch = run(
        base,
        ("load.line.add", {"beams": ["B1"], "value": 4}),
        ("member.delete", {"ids": ["B1"]}),
    )
    assert batch.ok and json.loads(batch.changes[LOADS])["loads"] == []
    batch = run(
        base,
        ("storey.add", {"height": 3000}),
        ("members.copy_to_storeys", {"from": "L2", "to": ["L3"]}),
    )
    assert batch.ok and len(batch.results[1].created) == 6 + 7 + 2


# ─────────────────────────────── loads ───────────────────────────────


def test_typical_floors_follow_edits(base):
    batch = run(
        base,
        ("storey.add", {"height": 3000}),
        ("storey.typical", {"master": "L2", "storeys": ["L3"]}),
        ("member.set", {"ids": ["C7"], "rotation": 90}),
        ("member.delete", {"ids": ["B8"]}),
        ("member.set", {"ids": ["C8"], "rotation": 45, "thisStoreyOnly": True}),
    )
    assert batch.ok, [r.message for r in batch.results]
    plan = json.loads(batch.changes[FLOOR_PLAN])
    at = {(c["at"]["x"], c["at"]["y"], c["top"]): c for c in plan["columns"]}
    c7 = next(c for c in plan["columns"] if c["id"] == "C7")
    twin = at[(c7["at"]["x"], c7["at"]["y"], "L3")]
    assert c7["top"] == "L2" and twin["rotation"] == 90 and "twins" in batch.results[2].message
    c8 = next(c for c in plan["columns"] if c["id"] == "C8")
    assert at[(c8["at"]["x"], c8["at"]["y"], "L3")]["rotation"] == 0
    assert sum(1 for b in plan["beams"] if b["story"] == "L3") == 6  # B8's twin went too


def test_load_area_set(base):
    result, changes = one(base, "load.area.set", {"id": "FL", "SD": 2.0, "L": 3.0})
    floor = next(a for a in changes[SETTINGS]["areaLoads"] if a["id"] == "FL")
    assert floor["finish"] == 2.0 and floor["live"] == 3.0
    result, changes = one(base, "load.area.set", {"storeys": ["L2"], "Lr": 1.5, "SD": 1.0})
    assert result.created == ["AL1"]
    assert all(s.get("areaLoad") == "AL1" for s in plan_of(changes)["slabs"] if s["story"] == "L2")
    assert refused(base, "load.area.set", {"id": "FL", "L": 2, "Lr": 1}).problems


def test_load_line_point_and_wall(base):
    batch = run(
        base,
        ("load.line.add", {"beams": ["B1", "B2"], "value": 5, "case": "SD"}),
        ("load.point.add", {"member": "B1", "value": 20, "distance": 2500, "case": "L"}),
        ("load.point.add", {"member": "C1", "value": 10}),
        ("load.wall.add", {"storeys": ["L1"], "openings": 20}),
    )
    assert batch.ok, [r.message for r in batch.results]
    loads = json.loads(batch.changes[LOADS])["loads"]
    assert [x["id"] for x in loads[:2]] == ["LL1", "LL2"] and loads[2]["id"] == "PL1"
    assert loads[3]["story"] == "L1" and loads[-1]["wall"]["auto"] is True
    result = refused(base, "load.line.add", {"beams": ["B1"], "value": -5})
    assert result.problems[0].part == LOADS and "downward" in result.problems[0].reason
    assert (
        "beyond the end"
        in refused(base, "load.point.add", {"member": "B1", "value": 5, "distance": 9000}).message
    )


# ─────────────────────────────── foundations ───────────────────────────────


def test_footing_set(base):
    result, changes = one(
        base, "footing.set", {"at": "A-1", "length": 1500, "width": 1500, "thickness": 450}
    )
    footing = changes[SUBSTRUCTURE]["foundations"][-1]
    assert footing["columns"] == ["C1"] and footing["center"] == [0.0, 0.0]
    assert result.created == [footing["id"]]
    assert refused(base, "footing.set", {"at": "A-1", "length": 1500}).problems


# ─────────────────────────────── queries ───────────────────────────────


def test_queries(base):
    result, _ = one(base, "project.summary")
    assert result.data["members"] == {"columns": 12, "beams": 14, "slabs": 4}
    result, _ = one(base, "members.list", {"group": "columns", "storey": "L1"})
    assert len(result.data) == 6 and result.data[0]["at"] == "A-1"
    result, _ = one(base, "actions.help", {"name": "grid.set"})
    assert result.data["name"] == "grid.set" and result.data["params_schema"]
    result, _ = one(base, "actions.help")
    assert len(result.data["actions"]) == len(list_actions()) and result.data["playbook"]
    result, _ = one(base, "results.summary")
    assert {p["part"] for p in result.data["parts"]} >= {"floorPlan", "fem"}
    assert refused(base, "checks.list", {}).message.startswith("There are no design checks")


# ─────────────────────────────── batches ───────────────────────────────


def test_batch_is_all_or_nothing(copy):
    before = (copy / FLOOR_PLAN).read_text(encoding="utf-8")
    batch = run(
        copy,
        ("grid.line.add", {"axis": "x", "position": 15000}),
        ("storeys.set", {"count": 2, "height": 100}),
        ("grid.line.add", {"axis": "y", "position": 8000}),
        write=True,
    )
    assert not batch.ok and batch.failed_step == 1 and batch.changes == {} and not batch.written
    assert len(batch.results) == 2
    assert (copy / FLOOR_PLAN).read_text(encoding="utf-8") == before
    every = run(
        copy,
        ("storeys.set", {"count": 2, "height": 100}),
        ("grid.line.add", {"axis": "y", "position": 8000}),
        ("columns.place", {"type": "nope"}),
        stop_on_error=False,
    )
    assert [r.ok for r in every.results] == [False, True, False] and every.changes == {}


def test_later_steps_see_earlier_ones_and_overrides_are_used(base):
    plan = json.loads((base / FLOOR_PLAN).read_text(encoding="utf-8"))
    plan["grids"]["x"].append({"label": "Z", "position": 20000})
    overrides = {FLOOR_PLAN: json.dumps(plan, indent="\t")}
    batch = run(
        base,
        ("grid.line.add", {"axis": "y", "position": 8000, "label": "9"}),
        ("columns.place", {"type": "C400x400", "points": ["Z-9"], "storeys": ["L1"]}),
        overrides=overrides,
    )
    assert batch.ok, [r.message for r in batch.results]
    assert batch.changes[FLOOR_PLAN].startswith("{\n\t")  # the project's formatting


def test_run_step_refuses_unsaved_changes(base):
    batch = run(
        base, ("grid.line.add", {"axis": "x", "position": 15000}), ("run.step", {"step": "derive"})
    )
    assert not batch.ok and batch.failed_step == 1 and "not saved" in batch.results[1].message


def test_write_saves_a_version(copy):
    from saengine.project import versions

    versions.save(copy, "Start")
    batch = run(copy, ("grid.line.add", {"axis": "x", "position": 15000}), write=True)
    assert batch.ok and batch.written == [FLOOR_PLAN]
    assert batch.version and batch.version["message"] == "Actions: grid.line.add"
    assert '"label": "D"' in (copy / FLOOR_PLAN).read_text(encoding="utf-8")
    assert not list((copy / "05 Floor Plan").glob("*.tmp"))


def test_get_returns_the_action():
    assert get("grid.set").kind == "edit" and get("run.all").kind == "run"


# ─────────────────────────────── surfaces ───────────────────────────────


def test_cli(copy, tmp_path, capsys):
    from saengine.cli.main import main

    assert main(["action", "list", "--kind", "query", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert {a["name"] for a in doc["actions"]} >= {"project.summary", "checks.list"}
    assert main(["action", "describe", "columns.place"]) == 0
    assert "Parameters:" in capsys.readouterr().out
    assert main(["action", "describe", "columns.plant"]) == 2
    capsys.readouterr()
    params = json.dumps({"axis": "x", "position": 15000})
    code = main(
        [
            "action",
            "run",
            "grid.line.add",
            "--params",
            params,
            "--project",
            str(copy),
            "--dry-run",
            "--json",
        ]
    )
    doc = json.loads(capsys.readouterr().out)
    assert code == 0 and doc["batch"]["changed"] == [FLOOR_PLAN] and doc["batch"]["written"] == []
    steps = tmp_path / "steps.json"
    steps.write_text(json.dumps([{"action": "storeys.set", "params": {"count": 1, "height": 50}}]))
    assert main(["action", "batch", str(steps), "--project", str(copy)]) == 1
    assert "REFUSED" in capsys.readouterr().out
    steps.write_text(
        json.dumps(
            {"steps": [{"action": "grid.line.add", "params": {"axis": "y", "position": 8000}}]}
        )
    )
    assert main(["action", "batch", str(steps), "--project", str(copy)]) == 0
    assert '"label": "3"' in (copy / FLOOR_PLAN).read_text(encoding="utf-8")


def test_rpc_handlers(base):
    from saengine import api
    from saengine.rpc import handlers

    listed = handlers.actions_list("edit")
    assert listed and all(a["kind"] == "edit" for a in listed) and "params_schema" in listed[0]
    answer = handlers.actions_run(
        str(base), [{"action": "grid.line.add", "params": {"axis": "x", "position": 15000}}]
    )
    assert answer["ok"] and FLOOR_PLAN in answer["changes"] and answer["failed_step"] is None
    assert api.API_VERSION == "1.1.0" and api.run_actions is run_actions

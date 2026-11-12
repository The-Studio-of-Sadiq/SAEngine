"""The project's rebar (and concrete) chosen in New Building from Grid: recorded as ``defaults``
of 03 Materials and used wherever a type or element has no bars of its own (the design's
assumed bars, the BOQ, footing minimum bars, lintels, tanks), not the library's first rebar."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from saengine.boq.quantities import bill_of_quantities
from saengine.design.required import with_assumed_bars
from saengine.library import default_material_library
from saengine.library.bim import generate
from saengine.library.floorplan import FloorPlan
from saengine.library.generator import generate_building, write_building
from saengine.library.materials import Category, MaterialLibrary, default_of
from saengine.plumbing.tanks import TankContext, tank_spec
from saengine.project.new_building import spec_from_wizard
from saengine.substructure.run import add_minimum_bars

WIZARD = {
    "schema": "saengine.newBuilding/1",
    "name": "Rebar Test",
    "spacings": {"x": [5000, 5000], "y": [4000]},
    "stories": [
        {"id": "BASE", "name": "Base", "elevation": 0},
        {"id": "L1", "name": "Level 1", "elevation": 3200},
        {"id": "L2", "name": "Level 2", "elevation": 6400},
    ],
    "storyHeights": [3200, 3200],
    "system": "rcFrame",
    "materials": {"concrete": "C27.6", "rebar": "B500DWR"},
    "footing": "isolated",
}


@pytest.fixture(scope="module")
def generated() -> dict:
    spec, _ = spec_from_wizard(WIZARD)
    assert (spec["concrete"], spec["rebar"]) == ("C27.6", "B500DWR")
    return generate_building({**spec, "lateralSizing": "gravity"})


def test_the_generator_records_the_chosen_materials(generated: dict) -> None:
    library = MaterialLibrary.model_validate(generated["materials"])
    assert generated["materials"]["defaults"] == {"concrete": "C27.6", "rebar": "B500DWR"}
    assert (library.default_concrete(), library.default_rebar()) == ("C27.6", "B500DWR")
    # The generated types still carry no bars: the defaults are what records the choice.
    assert not any(o.get("reinforcement") for o in generated["objects"]["objects"])


def test_the_design_assumes_the_chosen_rebar(generated: dict) -> None:
    library = MaterialLibrary.model_validate(generated["materials"])
    objects, assumed = with_assumed_bars(json.dumps(generated["objects"]), library)
    assert assumed
    materials = {o.reinforcement.material for o in objects.objects if o.id in assumed}
    assert materials == {"B500DWR"}
    assert library.get("B500DWR").steel.fy == 500


def test_the_bill_takes_the_chosen_rebar(generated: dict) -> None:
    library = MaterialLibrary.model_validate(generated["materials"])
    # The bars Design Reinforcement writes start from the assumed ones (their material).
    objects, _ = with_assumed_bars(json.dumps(generated["objects"]), library)
    building = generate(FloorPlan.model_validate(generated["floorPlan"]), "test")
    bill = bill_of_quantities(building, objects, library)
    bars = {i.material for i in bill.items if i.group == "reinforcement"}
    assert bars == {"B500DWR"}


def test_footing_minimum_bars_take_the_chosen_rebar(generated: dict, tmp_path: Path) -> None:
    write_building(generated, tmp_path, "Rebar Test")
    document = json.loads(
        (tmp_path / "09 Substructure" / "substructure.json").read_text(encoding="utf-8")
    )
    assert document.get("foundations")
    assert add_minimum_bars(tmp_path, document)
    assert {f["reinforcement"]["material"] for f in document["foundations"]} == {"B500DWR"}


def test_tanks_take_the_project_rebar(generated: dict) -> None:
    library = MaterialLibrary.model_validate(generated["materials"])
    tank = {"id": "T1", "kind": "underground", "length": 3000, "width": 2000, "waterDepth": 1500}
    assert tank_spec(tank, TankContext.build(library)).rebar == "B500DWR"
    # The tank's own, then the options', win over the project's.
    assert tank_spec({**tank, "rebar": "B420DWR"}, TankContext.build(library)).rebar == "B420DWR"
    options = {"defaultRebar": "B420DWR"}
    assert tank_spec(tank, TankContext.build(library, options=options)).rebar == "B420DWR"
    # A project without defaults: its first rebar, as before.
    assert tank_spec(tank, TankContext.build()).rebar == "B420DWR"


def test_defaults_must_name_a_material_of_their_category() -> None:
    data = default_material_library().model_dump(mode="json", by_alias=True, exclude_none=True)
    with pytest.raises(ValidationError, match="defaults.rebar 'C24.1' is not a rebar"):
        MaterialLibrary.model_validate({**data, "defaults": {"rebar": "C24.1"}})
    with pytest.raises(ValidationError, match="defaults.concrete 'NOPE' is not a concrete"):
        MaterialLibrary.model_validate({**data, "defaults": {"concrete": "NOPE"}})
    # Without defaults: the first of the category, as before.
    library = MaterialLibrary.model_validate(data)
    assert (library.default_concrete(), library.default_rebar()) == ("C20.7", "B420DWR")
    # The raw JSON (read leniently): a stale default falls back to the first one.
    assert default_of({**data, "defaults": {"rebar": "B500DWR"}}, Category.REBAR) == "B500DWR"
    assert default_of({**data, "defaults": {"rebar": "GONE"}}, Category.REBAR) == "B420DWR"
    assert default_of({}, Category.REBAR) is None

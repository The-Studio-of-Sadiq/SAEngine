"""Rising mains, cable trays and the openings they need (BNBC 2020 Part 8 Sec 1.3.13)."""

from __future__ import annotations

import math

import pytest

from saengine.electrical.demand import demand
from saengine.electrical.risers import (
    BeamLine,
    Frame,
    busbar,
    path_beam_crossings,
    riser_openings,
    size_riser,
    tray_checks,
    tray_openings,
)
from saengine.library.mep import MepModel
from saengine.plumbing.building import Building
from saengine.verification.cases.electrical import (
    eight_storey,
    eight_storey_bim,
    eight_storey_electrical,
    eight_storey_objects,
)


def _mep(**changes) -> MepModel:
    electrical = {**eight_storey_electrical(), **changes}
    data = {"schema": "saengine.mep/1", "electrical": electrical}
    if "shafts" in changes:
        data["shafts"] = electrical.pop("shafts")
    return MepModel.model_validate(data)


def test_busbar_riser_current_and_slab_openings() -> None:
    mep, bim, _ = eight_storey()
    building = Building.of(bim)
    order = building.ordered()
    d = demand(mep.electrical, building)
    size = size_riser(mep.electrical.risers[0], d, building, order, 8)
    per_floor = 0.8 * 600 * 75 / 1000 / 0.85  # kVA
    amps = 1000 / (math.sqrt(3) * 400)
    assert size["current"] == pytest.approx(8 * per_floor * amps)
    assert size["rating"] == 630
    assert (size["width"], size["depth"]) == (150, 110)
    # At L7 the riser carries only L7.
    assert size["segments"][-1] == {"story": "L7", "current": pytest.approx(per_floor * amps)}
    out = riser_openings(mep, [size], building, order)
    openings = out["openings"]
    assert [o["id"] for o in openings] == [f"PE-ER1-L{i}" for i in range(1, 8)]
    first = openings[0]
    assert first["host"] == "S-L1"
    assert (first["width"], first["height"]) == (350, 350)  # 150 + 200; 110 + 200 -> 350
    assert first["position"] == {"x": 15000, "y": 7500}


def test_riser_in_a_shaft_needs_no_opening() -> None:
    shaft = {"id": "ES1", "outline": [[14500, 7000], [15500, 7000], [15500, 8000], [14500, 8000]],
             "fromStory": "GF", "toStory": "L7", "service": "Electrical shaft"}  # fmt: skip
    risers = [{"id": "ER1", "kind": "busbar", "x": 15000, "y": 7500, "fromStory": "GF",
               "toStory": "L7", "width": 200, "depth": 150}]  # fmt: skip
    mep = MepModel.model_validate({
        "schema": "saengine.mep/1", "shafts": [shaft],
        "electrical": {**eight_storey_electrical(), "risers": risers},
    })  # fmt: skip
    building = Building.of(eight_storey_bim())
    sizes = [{"id": "ER1", "width": 200, "depth": 150, "rating": 630}]
    assert riser_openings(mep, sizes, building, building.ordered())["openings"] == []
    # Outside the shaft, the entered size: (200 + 200) x (150 + 200) = 400 x 350.
    mep2 = MepModel.model_validate(
        {"schema": "saengine.mep/1", "electrical": {**eight_storey_electrical(), "risers": risers}}
    )
    opening = riser_openings(mep2, sizes, building, building.ordered())["openings"][0]
    assert (opening["width"], opening["height"]) == (400, 350)


def test_cable_riser_width_from_the_cable_count() -> None:
    risers = [{"id": "CR1", "kind": "cableTray", "x": 15000, "y": 7500, "fromStory": "GF",
               "toStory": "L3"}]  # fmt: skip
    mep = _mep(risers=risers)
    building = Building.of(eight_storey_bim())
    d = demand(mep.electrical, building)
    size = size_riser(mep.electrical.risers[0], d, building, building.ordered(), 8)
    # GF-L3: 4 cables for 61 A each (42.35 kVA) -> 26 mm OD: 4 x 26 + 3 x 37 = 215 -> 300 tray.
    assert size["cables"] == 4
    assert size["width"] == 300


def test_tray_crossing_beams_of_the_floor_above() -> None:
    mep, bim, objects = eight_storey()
    out = tray_openings(mep, Building.of(bim), Frame.of(bim, objects))
    openings = out["openings"]
    assert [o["host"] for o in openings] == [f"BY-L4-{x}-5000" for x in (6000, 12000, 18000, 24000)]
    o = openings[0]
    assert o["id"] == "PE-CT1-BY-L4-6000-5000"
    # Tray 300 x 100 at 14000 - 150 - 150 - 100 = 13600 to 13700; beam 600 deep: bottom 13400.
    assert (o["width"], o["height"]) == (400, 200)
    assert o["position"] == {"distance": 2500.0, "elevation": 250.0}
    assert o["kind"] == "opening" and o["shape"] == "rectangle"


def test_tray_below_the_beams_needs_no_opening() -> None:
    trays = [{"id": "CT1", "story": "L3", "path": [[1000, 7500], [29000, 7500]], "width": 300,
              "height": 100, "bottom": 2700}]  # fmt: skip
    mep = _mep(trays=trays)
    bim = eight_storey_bim()
    out = tray_openings(mep, Building.of(bim), Frame.of(bim, eight_storey_objects()))
    assert out["openings"] == []
    assert all(c["passesBelow"] for c in out["crossings"]) and len(out["crossings"]) == 4


def test_tray_just_below_the_beam_soffit_gets_no_notch() -> None:
    # L3 floor 10500 + 2860 = 13360 to 13460; beam bottom 13400: 60 mm overlap. An opening of
    # 200 mm centred at 13410 would run from 13310, 90 mm below the soffit: none is proposed.
    trays = [{"id": "CT9", "story": "L3", "path": [[1000, 7500], [29000, 7500]], "width": 300,
              "height": 100, "bottom": 2860}]  # fmt: skip
    mep = _mep(trays=trays)
    bim = eight_storey_bim()
    out = tray_openings(mep, Building.of(bim), Frame.of(bim, eight_storey_objects()))
    assert out["openings"] == []
    assert len(out["crossings"]) == 4 and not any(c["fits"] for c in out["crossings"])
    assert out["crossings"][0]["openingBottom"] == pytest.approx(13310.0)
    assert any("lower the tray by 60 mm" in n and "notch" in n for n in out["notes"])


def test_skewed_crossing_and_fill() -> None:
    beam = BeamLine("B", (0.0, 0.0), (0.0, 10000.0), 3000.0, 600.0)
    cross = path_beam_crossings([[-1000, 0], [1000, 2000]], [beam])
    assert cross[0]["sine"] == pytest.approx(math.sqrt(0.5))
    assert cross[0]["distance"] == pytest.approx(1000.0)
    # Parallel runs do not cross.
    assert path_beam_crossings([[100, 0], [100, 9000]], [beam]) == []
    trays = [{"id": "CT9", "story": "L3", "path": [[0, 0], [1000, 0]], "width": 300,
              "height": 100, "cableArea": 13000}]  # fmt: skip
    check = tray_checks(_mep(trays=trays).electrical)[0]
    assert check["capacity"] == pytest.approx(0.4 * 300 * 100)
    assert not check["ok"]
    assert busbar(489)[0] == 630
    assert busbar(5000) is None

"""The architecture's rooms as MEP inputs (saengine.mep.rooms): fixtures from the wet rooms, the
source of each story's counts, population, HVAC room groups and the branch runs, on the one-bay
frame of test_line_loads (A-B 6 m along x, 1-2 5 m along y, 3.2 m stories).

L1 is laid out with room separators:

    y 5000 +-----------------+--------+
           |                 | Kitchen|
           |     Bedroom     +--------+ 3000
           |                 | Toilet |
      1500 +-----------------+--------+
           |        Corridor          |
         0 +--------------------------+
           0                4000    6000
"""

from __future__ import annotations

from typing import Any

import pytest
from test_architecture_loads import architecture
from test_line_loads import plan

from saengine.hvac.gains import room_gains
from saengine.hvac.geometry import zones
from saengine.library.bim import generate
from saengine.library.mep import MepModel
from saengine.mep import rooms as R
from saengine.mep.routing import RoomGraph, RoomPlace
from saengine.plumbing.building import Building
from saengine.plumbing.report import plumbing_results

LINES = [
    ([0, 0], [6000, 0]),
    ([6000, 0], [6000, 5000]),
    ([6000, 5000], [0, 5000]),
    ([0, 5000], [0, 0]),
    ([0, 1500], [6000, 1500]),
    ([4000, 1500], [4000, 5000]),
    ([4000, 3000], [6000, 3000]),
]
ROOMS = [
    {"id": "R1", "name": "Corridor", "point": [3000, 700], "occupancy": "residentialPublic"},
    {"id": "R2", "name": "Bedroom", "point": [2000, 3000], "occupancy": "residential"},
    {"id": "R3", "name": "Toilet", "point": [5000, 2200], "occupancy": "residential", "wet": True},
    {"id": "R4", "name": "Kitchen", "point": [5000, 4000], "occupancy": "residential", "wet": True},
]


def layout(**extra: Any):
    return architecture(
        separators=[
            {"id": f"S{k}", "story": "L1", "start": a, "end": b} for k, (a, b) in enumerate(LINES)
        ],
        rooms=[{"story": "L1", **r} for r in ROOMS],
        **extra,
    )


def mep(**plumbing: Any) -> MepModel:
    return MepModel.model_validate(
        {
            "plumbing": {
                "risers": [
                    # in a duct outside the bay, west of the corridor
                    {
                        "id": "CW1",
                        "system": "coldWater",
                        "x": -300,
                        "y": 700,
                        "fromStory": "BASE",
                        "toStory": "L2",
                    },
                    # in the toilet
                    {
                        "id": "SS1",
                        "system": "soil",
                        "x": 5800,
                        "y": 1700,
                        "fromStory": "BASE",
                        "toStory": "L2",
                    },
                ],
                **plumbing,
            }
        }
    )


@pytest.fixture(scope="module")
def bim():
    return generate(plan(2), "s")


def inputs(bim: Any, plumbing: Any = None, arch: Any = None) -> R.RoomInputs:
    return R.room_inputs(arch or layout(), bim, plumbing)


def test_wet_kinds_from_names() -> None:
    assert R.wet_kind("Toilet") == "toilet"
    assert R.wet_kind("Master Bath") == "toilet"
    assert R.wet_kind("W.C.") == "toilet"
    assert R.wet_kind("Powder Room") == "halfBath"
    assert R.wet_kind("Gents Toilet") == "publicToilet"
    assert R.wet_kind("Kitchen") == "kitchen"
    assert R.wet_kind("Laundry") == "laundry"
    assert R.wet_kind("Verandah") == "wetArea"
    # a word inside another is not the word: "Bathan" is no bath, "Kitchenette" is a kitchen
    assert R.wet_kind("Bathan") == "wetArea"
    assert R.wet_kind("Kitchenette") == "kitchen"


def test_story_fixtures_from_the_wet_rooms(bim: Any) -> None:
    found = inputs(bim)
    story = found.story("L1")
    assert story is not None
    # areas are the net floors of room_boundary (the separators have no thickness)
    areas = {r.id: r.area for r in story.rooms}
    assert areas == pytest.approx({"R1": 9.0, "R2": 14.0, "R3": 3.0, "R4": 4.0})
    assert [r.id for r in story.wet] == ["R3", "R4"]
    # SAEngine defaults: toilet WC, basin, shower, floor drain; kitchen sink, floor drain
    assert story.fixtures == {"wc": 1, "basin": 1, "shower": 1, "floorDrain": 2, "kitchenSink": 1}
    assert story.occupancy == "residentialFlat"


def test_project_defaults_and_one_rooms_own(bim: Any) -> None:
    plumbing = mep(
        roomFixtures=[{"kind": "toilet", "fixtures": {"wc": 1, "basin": 1, "bathtub": 1}}],
        wetRooms=[{"room": "R4", "kind": "laundry"}],
    ).plumbing
    story = inputs(bim, plumbing).story("L1")
    assert story is not None
    by_id = {r.id: r for r in story.rooms}
    assert by_id["R3"].fixtures == {"wc": 1, "basin": 1, "bathtub": 1}
    assert (by_id["R4"].kind, by_id["R4"].kindFrom) == ("laundry", "07 MEP")
    assert by_id["R4"].fixtures == {"washingMachine": 1, "floorDrain": 1}


def test_which_counts_are_used(bim: Any) -> None:
    found = inputs(bim)
    # no story typed: the rooms' counts, and the story added
    model, rows = R.with_rooms(mep(), found)
    [entry] = model.plumbing.stories
    assert entry.story == "L1" and entry.fixtures.kitchenSink == 1 and entry.fixtures.wc == 1
    assert rows[0]["source"] == "rooms" and rows[0]["rooms"] == ["R3", "R4"]
    # typed counts override (auto), and the report says so
    typed = mep(stories=[{"story": "L1", "fixtures": {"wc": 3, "kitchenSink": 2}}])
    model, rows = R.with_rooms(typed, inputs(bim))
    assert model.plumbing.stories[0].fixtures.wc == 3
    assert rows[0]["source"] == "typed" and "override" in rows[0]["note"]
    assert rows[0]["fromRooms"]["wc"] == 1
    # unless the story asks for the rooms
    rooms_wanted = mep(stories=[{"story": "L1", "fixturesFrom": "rooms", "fixtures": {"wc": 3}}])
    model, rows = R.with_rooms(rooms_wanted, inputs(bim))
    assert model.plumbing.stories[0].fixtures.wc == 1 and rows[0]["source"] == "rooms"
    # without rooms nothing changes
    model, rows = R.with_rooms(typed, None)
    assert model is typed and rows[0]["source"] == "typed"


def test_sizing_counts_the_rooms_fixtures(bim: Any) -> None:
    report = plumbing_results(mep(), bim, rooms=inputs(bim))
    [story] = report["demand"]["stories"]
    # one dwelling (one kitchen sink) x 5 persons (Sec 5.6.3)
    assert story["population"] == 5
    # wsfu of Table 8.O.1 (private): WC flush tank 3, basin 1, shower 2, kitchen sink 2
    assert (
        story["supplyUnits"] == pytest.approx(report["demand"]["supplyUnits"])
        and story["supplyUnits"] > 0
    )
    assert "from the architecture's wet rooms on L1" in report["summary"][0]
    section = report["rooms"]
    assert [r["id"] for r in section["wetRooms"]] == ["R3", "R4"]


def test_office_population_from_its_rooms(bim: Any) -> None:
    arch = layout()
    for room in arch.rooms:
        if room.id in ("R1", "R2"):
            room.occupancy = "office"
    found = inputs(bim, arch=arch)
    model, rows = R.with_rooms(mep(stories=[{"story": "L1", "occupancy": "office"}]), found)
    # (9 + 14) m² of office rooms / 7.4 m² per person (Sec 5.6.4)
    assert model.plumbing.stories[0].population == pytest.approx(23 / 7.4, abs=0.05)
    assert "office rooms" in rows[0]["populationSource"]


def test_routing_prefers_the_corridor_and_wet_rooms() -> None:
    from shapely.geometry import box

    graph = RoomGraph(
        [
            RoomPlace("corridor", box(0, 0, 6000, 1500), True),
            RoomPlace("bedroom", box(0, 1500, 4000, 5000), False),
            RoomPlace("toilet", box(4000, 1500, 6000, 3000), True),
            RoomPlace("kitchen", box(4000, 3000, 6000, 5000), True),
        ]
    )
    path = graph.route((-300, 700), "kitchen")
    assert path is not None
    # in from the west through the corridor's wall, then corridor, toilet, kitchen: the bedroom
    # (twice the cost per mm) is avoided although its way is about as long
    assert path[0] == (-300, 700) and path[1] == (0, 700)
    assert (5000.0, 1500.0) in path and (5000.0, 3000.0) in path
    assert path[-1] == (5000.0, 4000.0)


def test_branch_runs_and_the_beams_they_cross(bim: Any) -> None:
    report = plumbing_results(mep(), bim, rooms=inputs(bim))
    runs = {(r["room"], r["system"]): r for r in report["rooms"]["branches"]}
    assert set(runs) == {("R3", "supply"), ("R3", "drainage"), ("R4", "supply"), ("R4", "drainage")}
    supply = runs[("R4", "supply")]
    assert supply["riser"] == "CW1"
    # the supply runs in L1's ceiling: it crosses L2's beam on grid A coming in from the duct
    beams_l2 = {e.id for e in bim.elements if e.kind == "beam" and e.elevation == 6400}
    assert supply["beams"] and set(supply["beams"]) <= beams_l2
    # the stack stands in the toilet: its drain stays inside the bay, no beam crossed
    assert runs[("R3", "drainage")]["riser"] == "SS1" and runs[("R3", "drainage")]["beams"] == []
    assert runs[("R4", "drainage")]["riser"] == "SS1"  # no waste stack: the soil stack


def test_hvac_gains_from_the_rooms(bim: Any) -> None:
    model = MepModel.model_validate({"hvac": {"stories": [{"story": "L1"}]}})
    zoning = zones(Building.of(bim), model.hvac)
    zone = next(z for z in zoning.zones if z.story == "L1")
    story = inputs(bim).story("L1")
    assert story is not None
    groups = story.hvac_groups()
    assert {g["use"] for g in groups} == {"livingArea", "corridor", "dwellingToilet",
                                          "dwellingKitchen"}  # fmt: skip
    g = room_gains(zone, model.hvac, groups, population=5)
    assert g.gainsFrom == "rooms" and g.use == "livingArea"
    # the bedroom (living area, no density) takes the 5 persons; Rp 7.5 l/s, 0.35 ACH over
    # 14 m² x 3.2 m; corridor Ra 0.3 l/s m² x 9 m²
    assert g.occupants == pytest.approx(5.0)
    air = max(0.35 * 14 * 3.2 / 3600, 7.5 * 5 / 1000) + 0.3 * 9 / 1000
    assert g.outdoor_air(zone.area, zone.volume) == pytest.approx(air, rel=1e-6)
    # typed gains win
    typed = MepModel.model_validate(
        {"hvac": {"stories": [{"story": "L1", "gainsFrom": "typed", "occupants": 12}]}}
    )
    zone_typed = next(z for z in zones(Building.of(bim), typed.hvac).zones if z.story == "L1")
    assert room_gains(zone_typed, typed.hvac, groups, 5).gainsFrom == "typed"


def test_project_files_feed_the_reports(bim: Any, tmp_path: Any) -> None:
    from saengine.hvac.report import hvac_loads
    from saengine.library import architecture as arch_lib
    from saengine.plumbing.project import full_report
    from saengine.plumbing.report import plumbing_report

    (tmp_path / "06 BIM").mkdir()
    (tmp_path / "06 BIM/bim.json").write_text(bim.model_dump_json(by_alias=True), "utf-8")
    (tmp_path / "05 Floor Plan").mkdir()
    (tmp_path / arch_lib.ARCHITECTURE_FILE).write_text(layout().model_dump_json(), "utf-8")
    (tmp_path / "07 MEP").mkdir()
    tank = {"id": "OHT1", "kind": "overhead", "story": "L2", "x": 3000, "y": 2500}
    data = mep(tanks=[tank]).model_dump(mode="json", by_alias=True, exclude_none=True)
    data["hvac"] = {"stories": [{"story": "L1"}]}
    (tmp_path / "07 MEP/mep.json").write_text(__import__("json").dumps(data), "utf-8")

    report = plumbing_report(tmp_path)
    assert report["rooms"]["stories"][0]["source"] == "rooms"
    assert report["demand"]["population"] == 5
    full = full_report(tmp_path, designs=False, hydraulics=True)
    assert full["sources"]["architecture"] == R.stamp(tmp_path) != ""
    # the hydraulics draw the same fixtures as the sizing: the rooms'
    floors = {f["story"]: f for f in full["hydraulics"]["floors"]}
    [story] = report["demand"]["stories"]
    assert floors["L1"]["units"] == pytest.approx(story["supplyUnits"]) and story["supplyUnits"]
    loads = hvac_loads(tmp_path, use_energyplus=False, cache=False)
    [zone] = [z for z in loads["zones"] if z["story"] == "L1"]
    assert zone["gainsFrom"] == "rooms" and zone["occupants"] == pytest.approx(5.0)
    assert {g["use"] for g in zone["rooms"]} >= {"livingArea", "corridor"}

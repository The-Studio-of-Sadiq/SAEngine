"""HVAC air side (stream H2): airflows, outdoor air, exhaust, duct sizes and shafts, by hand.

The project is synthetic (:func:`hvac_project`): two stories at 3.8 m (GF, L1) and a roof L2,
a 400 x 900 beam B1 under L1 along y = 5000 from x = 0 to 8000, 150 mm slabs on L1 and L2
over 8 x 10 m. The zone loads are a stub of the HVAC load calculation's result.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any

import pytest

from saengine.hvac import air

SAMPLE = Path(__file__).resolve().parents[2] / "workbench/resources/saengine/samples/Sample Frame"
REINFORCEMENT = {
    "material": "B420DWR",
    "cover": 40,
    "longitudinal": [
        {"position": "top", "count": 3, "dia": 20},
        {"position": "bottom", "count": 4, "dia": 20},
    ],
    "transverse": {"type": "tie", "dia": 10, "spacing": 150, "legs": 2},
}


def hvac_project(root: Path, hvac: dict[str, Any], **mep: Any) -> Path:
    """A synthetic project at ``root`` with this ``hvac`` section in 07 MEP."""
    (root / "03 Materials").mkdir(parents=True)
    shutil.copy(SAMPLE / "03 Materials/materials.json", root / "03 Materials/materials.json")
    objects = {
        "schema": "saengine.objects/1",
        "objects": [
            {"id": "B400x900", "name": "Beam 400x900", "kind": "beam", "material": "C20.7",
             "profile": {"shape": "rectangle", "xDim": 400, "yDim": 900},
             "reinforcement": REINFORCEMENT},
            {"id": "S150", "name": "Slab 150", "kind": "slab", "material": "C20.7",
             "thickness": 150},
        ],
    }  # fmt: skip
    sample_objects = json.loads((SAMPLE / "04 Objects/objects.json").read_text("utf-8"))
    objects["schema"] = sample_objects["schema"]
    (root / "04 Objects").mkdir()
    (root / "04 Objects/objects.json").write_text(json.dumps(objects), "utf-8")
    outline = [[0, 0], [8000, 0], [8000, 10000], [0, 10000]]
    bim = {
        "stories": [
            {"id": "GF", "name": "GF", "elevation": 0},
            {"id": "L1", "name": "L1", "elevation": 3800},
            {"id": "L2", "name": "L2", "elevation": 7600},
        ],
        "elements": [
            {"id": "B1", "type": "B400x900", "kind": "beam", "start": [0, 5000],
             "end": [8000, 5000], "elevation": 3800},
            {"id": "S1", "type": "S150", "kind": "slab", "boundary": outline, "elevation": 3800},
            {"id": "S2", "type": "S150", "kind": "slab", "boundary": outline, "elevation": 7600},
        ],
    }  # fmt: skip
    (root / "06 BIM").mkdir()
    (root / "06 BIM/bim.json").write_text(json.dumps(bim), "utf-8")
    (root / "07 MEP").mkdir()
    data = {"schema": "saengine.mep/1", **mep, "hvac": hvac}
    (root / "07 MEP/mep.json").write_text(json.dumps(data), "utf-8")
    return root


def swamee_jain_gradient(flow: float, diameter_mm: float) -> float:
    """Independent friction [Pa/m]: Swamee-Jain's explicit friction factor (not Colebrook)."""
    d = diameter_mm / 1000
    v = flow / (math.pi * d * d / 4)
    re = 1.2 * v * d / 1.81e-5
    f = 0.25 / math.log10(0.09 / diameter_mm / 3.7 + 5.74 / re**0.9) ** 2
    return f / d * 1.2 * v * v / 2


def test_supply_airflow_from_the_sensible_load() -> None:
    # 12 kW sensible at a 10 K supply difference: 12 / (1.2 x 1.005 x 10) = 0.99502 m³/s.
    assert air.supply_airflow(12.0) == pytest.approx(12 / 12.06, rel=1e-9)
    assert air.supply_airflow(12.0, dt=8) == pytest.approx(12 / (1.2 * 1.005 * 8))


def test_outdoor_air_by_table_823() -> None:
    # Office spaces: 2.5 l/s per person, 0.3 l/s per m², 5 per 100 m² (p. 866).
    # 100 m²: 5 people, 2.5 x 5 + 0.3 x 100 = 42.5 l/s.
    oa = air.outdoor_air("officeSpace", 100.0)
    assert oa["occupants"] == pytest.approx(5.0)
    assert oa["flow"] == pytest.approx(0.0425)
    # Corridors: 0.3 l/s per m² only.
    assert air.outdoor_air("corridor", 50.0)["flow"] == pytest.approx(0.015)
    # Dwellings: 0.35 ACH of 100 m² x 3 m = 105 m³/h = 0.02917 m³/s; 6 people x 7.5 = 45 l/s.
    assert air.outdoor_air("livingArea", 100.0, None, 3.0)["flow"] == pytest.approx(105 / 3600)
    assert air.outdoor_air("livingArea", 100.0, 6, 3.0)["flow"] == pytest.approx(0.045)


def test_exhaust_from_the_plumbing_fixtures() -> None:
    class Fixtures:
        wc, urinal, kitchenSink = 4, 2, 2

    # Offices: public toilets, 25 l/s per water closet or urinal: 6 x 25 = 150 l/s.
    assert air.story_exhaust("officeSpace", 500, Fixtures)["toilet"] == pytest.approx(0.150)
    # Dwellings: 10 l/s per bathroom (4) and 12.5 l/s per kitchen (2).
    flat = air.story_exhaust("livingArea", 500, Fixtures)
    assert flat["toilet"] == pytest.approx(0.040)
    assert flat["kitchen"] == pytest.approx(0.025)
    # Commercial kitchen: 3.5 l/s per m² of 40 m² = 140 l/s.
    assert air.story_exhaust("kitchenCooking", 40, None)["kitchen"] == pytest.approx(0.140)
    # Enclosed parking: 3.75 l/s per m².
    assert air.story_exhaust("parkingGarage", 1000, None)["general"] == pytest.approx(3.75)


def test_duct_by_equal_friction() -> None:
    # 1.0 m³/s at 1 Pa/m: the diameter found loses 1 Pa/m by Swamee-Jain too (independent).
    d = air.round_for_friction(1.0)
    assert swamee_jain_gradient(1.0, d) == pytest.approx(1.0, rel=0.02)
    assert 420 < d < 460  # the ASHRAE friction chart: about 440 mm at 1000 l/s, 1 Pa/m
    duct = air.size_duct(1.0, "supply")
    assert duct["governs"] == "friction"
    # Shallowest rectangle with De >= d, aspect <= 4, 50 mm steps: 200 mm deep cannot (800 x
    # 200: De = 1.30 x 160000^0.625 / 1000^0.25 = 413.6 mm); at 250 mm, 650 gives 428.7 and
    # 700 gives 442.9 mm.
    assert air.equivalent_diameter(800, 200) == pytest.approx(413.6, abs=0.5)
    assert air.equivalent_diameter(650, 250) < d < air.equivalent_diameter(700, 250)
    assert (duct["width"], duct["height"]) == (700, 250)
    assert duct["velocity"] == pytest.approx(1.0 / 0.175)
    assert duct["ok"]


def test_duct_by_the_velocity_limit() -> None:
    # 5 m³/s supply: equal friction gives 812 mm (9.7 m/s), above 7.5 m/s; the velocity limit
    # needs 5 / 7.5 = 0.6667 m², a 921 mm circle: 950 mm, 7.05 m/s.
    duct = air.size_duct(5.0, "supply", "round")
    assert duct["frictionDiameter"] == pytest.approx(811.6, abs=2)
    assert duct["velocityDiameter"] == pytest.approx(math.sqrt(4 * 5 / 7.5 / math.pi) * 1000)
    assert duct["governs"] == "velocity"
    assert duct["diameter"] == 950
    assert duct["velocity"] == pytest.approx(5 / (math.pi * 0.95**2 / 4))
    rect = air.size_duct(5.0, "supply")
    assert rect["width"] * rect["height"] >= 5 / 7.5 * 1e6
    assert rect["velocity"] <= 7.5


def test_kitchen_exhaust_velocity_range() -> None:
    # BNBC Sec 2.11.5.1(d): 7.62 to 12.7 m/s. 0.5 m³/s: at least 0.5 / 12.7 = 39370 mm².
    duct = air.size_duct(0.5, "kitchenExhaust")
    assert 7.62 <= duct["velocity"] <= 12.7
    assert duct["width"] * duct["height"] >= 0.5 / 12.7 * 1e6
    check = air.check_duct(0.5, {"shape": "rect", "width": 400, "height": 300}, "kitchenExhaust")
    assert check["velocity"] == pytest.approx(0.5 / 0.12)  # 4.17 m/s: too slow
    assert not check["ok"]


def test_zones_ducts_and_shafts(tmp_path: Path) -> None:
    hvac = {
        "system": "vrf",
        "stories": [{"story": "GF", "use": "officeSpace"}, {"story": "L1", "use": "officeSpace"}],
        "ducts": [
            {"id": "S-GF", "system": "supply", "story": "GF", "path": [[1000, 1000], [7000, 1000]]},
            {"id": "EX", "system": "exhaust", "shape": "rect", "width": 300, "height": 200,
             "story": "GF", "path": [[2000, 2000]], "riser": {"fromStory": "GF", "toStory": "L2"},
             "shaft": "SH1"},
        ],
    }  # fmt: skip
    shaft = {"id": "SH1", "outline": [[1500, 1500], [2500, 1500], [2500, 2500], [1500, 2500]],
             "fromStory": "GF", "toStory": "L2"}  # fmt: skip
    plumbing = {"stories": [{"story": "GF", "occupancy": "office", "fixtures": {"wc": 4}},
                            {"story": "L1", "occupancy": "office", "fixtures": {"wc": 2,
                                                                                 "urinal": 2}}]}  # fmt: skip
    root = hvac_project(tmp_path / "p", hvac, shafts=[shaft], plumbing=plumbing)
    loads = {"zones": [{"story": "GF", "sensible": 12.06, "total": 15, "area": 100},
                       {"story": "L1", "sensible": 6.03, "total": 8, "area": 100}]}  # fmt: skip
    result = air.hvac_air(root, loads, with_plant=False, with_openings=False)
    gf = result["zones"][0]
    assert gf["airflow"] == pytest.approx(1.0)  # 12.06 / (1.2 x 1.005 x 10)
    assert gf["outdoorAir"] == pytest.approx(0.0425)
    assert gf["ductMain"]["width"] == 700 and gf["ductMain"]["height"] == 250
    ducts = {d["id"]: d for d in result["ducts"]}
    assert ducts["S-GF"]["flow"] == pytest.approx(1.0)
    assert ducts["S-GF"]["proposed"] and ducts["S-GF"]["size"]["width"] == 700
    # The exhaust riser carries GF (4 x 25) and L1 (4 x 25) = 200 l/s (L2 has no zone).
    assert ducts["EX"]["flow"] == pytest.approx(0.200)
    assert ducts["EX"]["velocity"] == pytest.approx(0.2 / 0.06)
    # Shaft: (300 + 150) x (200 + 150) = 0.1575 m² of 1.0 m².
    (sh,) = result["shafts"]
    assert sh["need"] == pytest.approx(0.1575)
    assert sh["area"] == pytest.approx(1.0)
    assert sh["ok"]
    assert any(c["name"] == "Shaft SH1 area (HVAC risers)" and c["ok"] for c in result["checks"])


def test_energyplus_zone_mapping(tmp_path: Path) -> None:
    # The load calculation may give EnergyPlus's zones by name (the story id, upper case), the
    # outdoor air in "ventilation"; GF has no slab: the area of the slabs above (80 m²).
    root = hvac_project(tmp_path / "p", {"stories": [{"story": "GF", "use": "officeSpace"}]})
    loads = {"zones": {"GF": {"sensible": 6.03, "total": 7.0, "ventilation": {"flow": 0.05}},
                       "L1": {"problem": "no cooling output from EnergyPlus"}}}  # fmt: skip
    zones, notes = air.zone_air(air.load_project(root), loads)
    (gf,) = zones
    assert gf["story"] == "GF" and gf["area"] == pytest.approx(80.0)
    assert gf["airflow"] == pytest.approx(0.5) and gf["outdoorAir"] == pytest.approx(0.05)
    assert any("no cooling output" in n for n in notes)


def test_kitchen_exhaust_by_table_828() -> None:
    # BNBC Sec 2.11.5.1(g), Table 8.2.8 (p. 914): grill, gas, 61 l/s per kW; cooker/stove,
    # electric, 32 l/s per kW: 10 x 61 + 20 x 32 = 1250 l/s.
    items = [("grill", 10, "gas"), ("cookerStove", 20, "electric")]
    assert air.kitchen_exhaust_flow(items) == pytest.approx(1.25)
    with pytest.raises(ValueError):
        air.kitchen_exhaust_flow([("dishWasher", 5, "gas")])  # no gas rate in the table
    # A commercial kitchen with 60 kW of equipment (the story's W/m² x area): 35 l/s per kW
    # (cooker/stove, gas) = 2100 l/s; without it Table 8.2.3's 3.5 l/s per m² stands in.
    by_kw = air.story_exhaust("kitchenCooking", 40, None, kitchen_kw=60)
    assert by_kw["kitchen"] == pytest.approx(2.1) and by_kw["kitchenBasis"] == "table828"
    by_area = air.story_exhaust("kitchenCooking", 40, None)
    assert by_area["kitchenBasis"] == "table823"
    assert any("Table 8.2.8" in n for n in by_area["notes"])


def test_exhaust_of_a_story_that_is_not_conditioned(tmp_path: Path) -> None:
    # GF: enclosed parking, not conditioned (the load calculation has no zone for it). On grade
    # without a slab, it takes the 80 m² of the slabs above: 3.75 x 80 = 300 l/s of exhaust.
    hvac = {
        "system": "vrf",
        "stories": [{"story": "GF", "use": "parkingGarage", "conditioned": False},
                    {"story": "L1", "use": "officeSpace"}],
        "ducts": [{"id": "PX", "system": "exhaust", "story": "GF",
                   "path": [[1000, 1000], [1000, 4000]]}],
    }  # fmt: skip
    root = hvac_project(tmp_path / "p", hvac)
    loads = {"zones": [{"story": "L1", "sensible": 6.03, "total": 8, "area": 80}]}
    result = air.hvac_air(root, loads, with_plant=True, with_openings=False)
    gf = next(z for z in result["zones"] if z["story"] == "GF")
    assert gf["conditioned"] is False and gf["airflow"] == 0
    assert gf["exhaust"]["general"] == pytest.approx(0.300)
    (px,) = result["ducts"]
    assert px["flow"] == pytest.approx(0.300) and px["proposed"]
    # No fresh-air unit or AHU for the parking floor.
    assert not any(p["story"] == "GF" for p in result["plant"] if p["kind"] != "exhaustFan")


def test_a_kitchen_exhaust_riser_needs_its_own_enclosure(tmp_path: Path) -> None:
    # BNBC Sec 2.11.5.1(f) (p. 912): each duct enclosure contains only one exhaust duct.
    shaft = {"id": "SH1", "outline": [[1000, 1000], [3000, 1000], [3000, 3000], [1000, 3000]],
             "fromStory": "GF", "toStory": "L2"}  # fmt: skip
    riser = {"fromStory": "GF", "toStory": "L2"}
    ducts = [
        {"id": "KX", "system": "kitchenExhaust", "width": 400, "height": 300, "story": "GF",
         "path": [[1500, 1500]], "riser": riser, "flow": 1.0},
        {"id": "EX", "system": "exhaust", "width": 300, "height": 200, "story": "GF",
         "path": [[2500, 2500]], "riser": riser, "flow": 0.2},
    ]  # fmt: skip
    root = hvac_project(tmp_path / "p", {"ducts": ducts}, shafts=[shaft])
    result = air.hvac_air(root, {"zones": []}, with_plant=False, with_openings=False)
    (one,) = [c for c in result["checks"] if "one kitchen exhaust" in c["name"]]
    assert not one["ok"] and one["demand"] == 2
    alone = hvac_project(tmp_path / "q", {"ducts": ducts[:1]}, shafts=[shaft])
    result = air.hvac_air(alone, {"zones": []}, with_plant=False, with_openings=False)
    (one,) = [c for c in result["checks"] if "one kitchen exhaust" in c["name"]]
    assert one["ok"]

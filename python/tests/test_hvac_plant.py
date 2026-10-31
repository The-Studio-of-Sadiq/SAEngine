"""HVAC plant proposed for the structure (stream H2): chillers, cooling towers, pumps, AHUs,
VRF outdoor units and their loads, worked out by hand. The zone loads are a stub of the HVAC
load calculation's result; the project is :func:`test_hvac_air.hvac_project`'s."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_hvac_air import hvac_project

from saengine.hvac import plant
from saengine.hvac.air import load_project, zone_air
from saengine.library.mep import Equipment, HvacPlant


def test_cooling_tower_heat_rejection() -> None:
    # A 1000 kW water-cooled screw chiller: BNBC Table 8.2.11 minimum COP 5.40 (530 to 1050 kW).
    # The tower rejects Q (1 + 1/COP) = 1000 x (1 + 1/5.4) = 1185.19 kW.
    cop = plant.chiller_cop("screw", 1000)
    assert cop == 5.40
    assert plant.heat_rejection(1000, cop) == pytest.approx(1185.185, abs=1e-3)
    assert plant.chiller_cop("centrifugal", 2000) == 6.30
    assert plant.chiller_cop("airCooled", 400) == 2.90
    # Condenser water at 5.6 K: 1185.19 / (4.186 x 5.6) = 50.56 l/s.
    assert plant.water_flow(1185.185) == pytest.approx(50.56, abs=0.01)


def test_chiller_plan() -> None:
    # 2000 kW >= 1050: water-cooled; 2 x 1000 kW screw (<= 1050 a unit), and one on standby.
    p = plant.chiller_plan(2000)
    assert (p["kind"], p["duty"], p["standby"], p["unit"]) == ("screw", 2, 1, 1000)
    # 600 kW: two air-cooled units of 300 kW (two from 350 kW) + standby.
    p = plant.chiller_plan(600)
    assert (p["kind"], p["duty"], p["standby"], p["unit"]) == ("airCooled", 2, 1, 300)
    # 5000 kW: two centrifugal of 2500 kW.
    p = plant.chiller_plan(5000)
    assert (p["kind"], p["duty"], p["unit"]) == ("centrifugal", 2, 2500)


def test_ahu_by_face_velocity() -> None:
    # 5 m³/s at 2.5 m/s: 2 m² of coil face.
    a = plant.ahu_size(5.0)
    assert a["face"] == pytest.approx(2.0)
    assert (a["width"] - 300) * (a["height"] - 300) >= 2.0e6 - 1
    assert a["weight"] == pytest.approx(3.0 + 4.5 * 5.0)


def _zones(tmp_path: Path, system: str, totals: list[float], **hvac):
    stories = [{"story": s, "use": "officeSpace"} for s in ("GF", "L1")]
    root = hvac_project(tmp_path / "p", {"system": system, "stories": stories, **hvac})
    loads = {"zones": [{"story": s, "sensible": t * 0.8, "total": t, "area": 80}
                       for s, t in zip(("GF", "L1"), totals, strict=True)]}  # fmt: skip
    project = load_project(root)
    zones, _ = zone_air(project, loads)
    return project, zones


def test_chilled_water_plant(tmp_path: Path) -> None:
    # Two zones of 1010.101 kW: 2020.2 x 0.9 x 1.1 = 2000 kW: 3 screw chillers of 1000 kW on GF
    # (the lowest story), 3 towers of 1185.19 kW on L2 (the top), 6 pumps, an AHU per story.
    project, zones = _zones(tmp_path, "chilledWater", [1010.10101, 1010.10101])
    result = plant.propose_plant(project, zones)
    assert result["capacity"]["capacity"] == pytest.approx(2000, rel=1e-6)
    by_kind: dict[str, list] = {}
    for p in result["plant"]:
        by_kind.setdefault(p["kind"], []).append(p)
        assert p["sized"] is True
        HvacPlant.model_validate(p)  # the 07 MEP hvac.plant entry (stream H1's model)
    assert [c["story"] for c in by_kind["chiller"]] == ["GF"] * 3
    assert all(c["capacity"] == 1000 for c in by_kind["chiller"])
    assert [t["story"] for t in by_kind["coolingTower"]] == ["L2"] * 3
    assert by_kind["coolingTower"][0]["capacity"] == pytest.approx(1185.19, abs=0.01)
    assert len(by_kind["pump"]) == 6
    assert sorted(a["story"] for a in by_kind["ahu"]) == ["GF", "L1"]
    # Typical weights: 0.065 kN/kW for a water-cooled screw chiller.
    assert by_kind["chiller"][0]["operatingWeight"] == pytest.approx(65.0)
    assert {p["id"] for p in result["pipes"]} == {"CHW-main", "CW-main"}
    # Every plant entry is equipment for the loads, vibrating, never twice.
    assert len(result["equipment"]) == len(result["plant"])
    for item in result["equipment"]:
        Equipment.model_validate(item)
        assert item["vibrating"] and item["id"].startswith("EQ-")
    assert {e["kind"] for e in result["equipment"]} == {"chiller", "pump", "ahu", "other"}


def test_vrf_outdoor_units_and_given_plant(tmp_path: Path) -> None:
    # 2 x 50 kW: 100 x 0.9 x 1.1 = 99 kW: two 49.5 kW outdoor units (at most 56) on L2.
    project, zones = _zones(tmp_path, "vrf", [50, 50])
    result = plant.propose_plant(project, zones)
    odus = [p for p in result["plant"] if p["kind"] == "vrfOutdoor"]
    assert len(odus) == 2 and all(u["capacity"] == pytest.approx(49.5) for u in odus)
    assert all(u["story"] == "L2" for u in odus)
    assert {p["kind"] for p in result["plant"]} == {"vrfOutdoor", "freshAirUnit"}
    # The engineer's own outdoor unit (not sized) is kept with SAEngine's weight filled in.
    own = {"id": "MY1", "kind": "vrfOutdoor", "story": "L2", "x": 100, "y": 100, "sized": False}
    project, zones = _zones(tmp_path / "b", "vrf", [50, 50], plant=[own])
    result = plant.propose_plant(project, zones)
    odus = [p for p in result["plant"] if p["kind"] == "vrfOutdoor"]
    assert [u["id"] for u in odus] == ["MY1"]
    assert odus[0]["operatingWeight"] == pytest.approx(0.06 * 49.5, abs=0.1)
    assert odus[0]["x"] == 100


def test_riser_pipe_and_sleeve() -> None:
    # 2 x 1000 kW chilled water at 5.6 K: 85.3 l/s. DN200: 2.72 m/s.
    flow = 2 * plant.water_flow(1000)
    pipe = plant.pipe_size(flow)
    assert pipe["velocity"] <= 3.0 and pipe["friction"] <= 400
    assert pipe["nominal"] in (200, 250)
    assert plant.pipe_sleeve(pipe["nominal"]) >= pipe["nominal"] + 2 * 40 + 50


def test_coincident_peak_replaces_the_diversity() -> None:
    zones = [{"total": 100.0}, {"total": 100.0}]
    assert plant.plant_capacity(zones)["capacity"] == pytest.approx(200 * 0.9 * 1.1)
    # EnergyPlus's coincident peak of all zones, 170 kW: 170 x 1.1.
    assert plant.plant_capacity(zones, 170.0)["capacity"] == pytest.approx(187.0)
    assert plant.coincident_peak({"building": {"total": 170.0}}) == 170.0
    assert plant.coincident_peak({"zones": []}) is None


def test_an_engineer_placed_chiller_gets_the_weight_of_its_own_capacity(tmp_path: Path) -> None:
    # SAEngine would propose air-cooled units (2 x 450 x 1.1 = 990 kW < 1050), but the
    # engineer placed one 3000 kW chiller without a weight: over the 1400 kW air-cooled unit,
    # it is taken as water-cooled centrifugal (> 1050 kW): 0.055 kN/kW x 3000 = 165 kN,
    # 0.0039 m²/kW x 3000 = 11.7 m² at 2500 wide: 4680 long, 3000 high (TYPICAL).
    own = {"id": "MYCH", "kind": "chiller", "story": "GF", "x": 1000, "y": 1000,
           "capacity": 3000, "sized": False}  # fmt: skip
    project, zones = _zones(tmp_path, "chilledWater", [450, 450], plant=[own])
    result = plant.propose_plant(project, zones)
    (chiller,) = [p for p in result["plant"] if p["kind"] == "chiller"]
    assert chiller["id"] == "MYCH" and chiller["capacity"] == 3000
    assert chiller["operatingWeight"] == pytest.approx(165.0)
    assert (chiller["length"], chiller["width"], chiller["height"]) == (4680, 2500, 3000)
    # Air-cooled class kept up to 1400 kW: a 600 kW unit at 0.100 kN/kW = 60 kN.
    assert plant.own_size("chiller", 600, "airCooled")[3] == pytest.approx(60.0)
    # A given weight is kept.
    own["operatingWeight"] = 200.0
    project, zones = _zones(tmp_path / "b", "chilledWater", [450, 450], plant=[own])
    result = plant.propose_plant(project, zones)
    (chiller,) = [p for p in result["plant"] if p["kind"] == "chiller"]
    assert chiller["operatingWeight"] == 200.0


def test_plant_room_headroom_for_the_installation(tmp_path: Path) -> None:
    # 2 x 750 kW: 1500 x 0.9 x 1.1 = 1485 kW >= 1050: water-cooled, 2 duty screw chillers of
    # 742.5 kW + 1 standby: each under 500 TR (1758 kW) but the installation, 3 x 742.5 =
    # 2227.5 kW, is over: BNBC Sec 2.6.2.4(b)'s 3.6 m below the beam soffits applies. GF is
    # 3800 high with a 900 deep beam over it: 2900 < 3600.
    project, zones = _zones(tmp_path, "chilledWater", [750, 750])
    result = plant.propose_plant(project, zones)
    (check,) = [c for c in result["checks"] if "headroom" in c["name"]]
    assert check["demand"] == 3600 and check["capacity"] == pytest.approx(2900)
    assert not check["ok"]
    # 2 x 1010.1 kW (2000 kW, 3 x 1000 kW screw = 3000 kW installed): checked too.
    project, zones = _zones(tmp_path / "b", "chilledWater", [1010.10101, 1010.10101])
    result = plant.propose_plant(project, zones)
    assert any("headroom" in c["name"] for c in result["checks"])


def test_a_proposed_unit_gives_at_least_what_it_was_sized_for() -> None:
    # 0.0404 m³/s of outdoor air rounded to the nearest 0.01 gave a 0.04 m³/s fresh air unit
    # that failed its own check: proposals round up.
    from saengine.hvac.plant import _entry

    assert _entry("FAU-L1", "freshAirUnit", "L1", 1, 1, 1, 0.0404, 1)["capacity"] == 0.05
    assert _entry("SODU1", "splitOutdoor", "R", 1, 1, 1, 6.4, 1)["capacity"] == 6.4


def test_split_outdoor_units_are_packed_on_the_roof(tmp_path: Path) -> None:
    # Many split outdoor units: packed in rows on the roof's slabs, each with SPACING clear
    # around it, not strung out in one line beyond the building (N-E2); any that do not fit
    # are listed in one note.
    project, zones = _zones(tmp_path, "split", [120, 120])
    result = plant.propose_plant(project, zones)
    units = [p for p in result["plant"] if p["kind"] == "splitOutdoor"]
    assert len(units) > 10
    roof = project.building.roof(units[0]["story"])
    minx, miny, maxx, maxy = roof.bounds
    inside = [u for u in units if minx <= u["x"] <= maxx and miny <= u["y"] <= maxy]
    outside = len(units) - len(inside)
    assert inside
    assert (outside == 0) == (not any("do not fit on the slabs" in n for n in result["notes"]))
    for a in inside:
        for b in inside:
            if a is not b:
                apart_x = abs(a["x"] - b["x"]) >= a["length"] + plant.SPACING - 1
                apart_y = abs(a["y"] - b["y"]) >= a["width"] + plant.SPACING - 1
                assert apart_x or apart_y

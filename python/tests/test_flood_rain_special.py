"""Flood and surge (case Fa), rain (case R), helicopter landing areas, gas explosions and air
raid shelters, pinned through the bnbc2020 pack: Part 6 Sec 1.6.4-1.6.5, 2.6.2-2.6.3,
2.6.6-2.6.8 and the Fa rows of Sec 2.7.2.1 and 2.7.3.1 (gazette pp. 501, 667-685)."""

from __future__ import annotations

import math

import pytest

from saengine.codes import context as code_context
from saengine.fem import flood as ff
from saengine.fem import special_loads as spl
from saengine.fem.combinations import allowable_combinations, expand_rows
from saengine.library.settings import (
    AirRaidShelter,
    FloodSite,
    Helipad,
    RainSite,
    default_project_settings,
    strength_combinations,
)
from saengine.substructure.loads import flood_service_combinations, flood_uplift

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ pack values â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_flood_pack_values():
    t = code_context.table("flood")
    # Sec 2.6.3 (p. 667): 100-year for essential facilities (category IV), else 50-year.
    assert t.returnPeriod == {"I": 50, "II": 50, "III": 50, "IV": 100}
    # Sec 2.6.3.4.1 (p. 674): fresh 9.80, salt 10.05 kN/mÂ³.
    assert t.waterUnitWeight == {"fresh": 9.80, "salt": 10.05}
    # Table 6.2.25 (p. 670).
    rows = {k: (r.height50, r.height100) for k, r in t.surgeRegions.items()}
    assert rows == {
        "teknafCoxsBazar": (4.5, 5.8),
        "chakariaAnwara": (7.1, 8.6),
        "chittagongNoakhali": (7.9, 9.6),
        "sandwipHatiya": (7.9, 9.6),
        "bholaBarguna": (6.2, 7.7),
        "sarankholaShyamnagar": (5.3, 6.4),
    }
    # Eq 6.2.71 k: 0.5 Chittagong-Cox's Bazar-Teknaf, 0.33 elsewhere (Chittagong-Noakhali
    # takes the smaller rate, the more conservative; noted).
    assert t.surgeRegions["teknafCoxsBazar"].decay == 0.5
    assert t.surgeRegions["bholaBarguna"].decay == 0.33
    assert t.surgeRegions["chittagongNoakhali"].note
    # Table 6.2.26 (pp. 671-672): 23 locations, spot values.
    assert len(t.waterLevels) == 23
    assert (t.waterLevels["teknaf"].level50, t.waterLevels["teknaf"].level100) == (2.33, 2.44)
    assert (t.waterLevels["companyganj"].level50, t.waterLevels["companyganj"].level100) == (
        7.53,
        7.94,
    )
    assert (t.waterLevels["kaikhali"].level50, t.waterLevels["kaikhali"].level100) == (3.94, 4.12)
    # Sec 2.6.3.2.1 (p. 670): +0.30 m for free water; x = 1 if x < 1.
    assert t.freeWaterIncrease == 0.30 and t.minDistance == 1.0
    # Sec 2.6.3.2.2 (pp. 672-673).
    h = t.hydrodynamic
    assert (h.waveShare, h.minWave, h.maxVelocity, h.minDrag, h.gravity) == (
        0.25,
        1.0,
        3.0,
        1.25,
        9.81,
    )
    assert h.windSpeed == {"50": 80.0, "100": 90.0}
    # Sec 2.6.3.4 (pp. 674-676).
    w = t.breakingWave
    assert (w.heightRatio, w.depthRatio, w.dragRound, w.dragSquare, w.squareWidth) == (
        0.78,
        0.65,
        1.75,
        2.25,
        1.4,
    )
    assert w.dynamicPressure == {"I": 1.6, "II": 2.8, "III": 3.2, "IV": 3.5}
    assert (w.forceDynamic, w.forceStatic, w.forceStaticWet, w.staticFactor) == (1.1, 2.4, 1.9, 1.2)
    # Sec 2.6.3.5 Eq 6.2.81 (p. 677), Table 6.2.27 (p. 679).
    i = t.impact
    assert (i.debrisWeight, i.duration, i.orientation) == (4448.0, 0.03, 0.8)
    assert i.importance == {"I": 0.6, "II": 1.0, "III": 1.2, "IV": 1.3}
    # Sec 2.6.3.3 (p. 673); Sec 1.6.4 (p. 501).
    assert (t.breakaway.minPressure, t.breakaway.maxCollapse) == (0.5, 1.0)
    assert t.stabilityFactor == 1.5
    assert "SAEngine practice" in t.notes["flotationFactor"]
    # Sec 2.6.2.2 (p. 667): + 0.25 kN/mÂ² with controlled drainage.
    assert t.rain.controlledAllowance == 0.25
    # Sec 2.6.8 (p. 683): 5.0 kN/mÂ², k 0.75 / 1.5, 300 mm.
    assert t.helipad.distributed == 5.0 and t.helipad.patch == 300.0
    assert t.helipad.impact == {"hydraulic": 0.75, "rigid": 1.5}
    # Sec 2.6.6.2-2.6.6.3 (p. 682): 5 kN/mÂ² least, vents 1.0 kN/mÂ².
    assert (t.explosion.minPressure, t.explosion.reliefPressure) == (5.0, 1.0)
    # Table 6.2.28 (p. 682): 28 / 34 / 41, stable 28, threshold 5.0.
    assert [r.load for r in t.shelter.rows] == [28.0, 34.0, 41.0]
    assert (t.shelter.stable, t.shelter.liveThreshold) == (28.0, 5.0)


def test_water_level_column_is_the_conservative_reading():
    # Table 6.2.26 notes contradict Sec 2.6.3: the 100-year column for every category.
    t = code_context.table("flood")
    assert all(v == 100 for v in t.waterLevelReturnPeriod.values())
    assert ff.water_level_period("II", t) == 100 and ff.return_period("II", t) == 50


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ the design flood â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_surge_height_eq_6_2_71():
    # hs = hT - (x - 1) k: Bhola-Barguna 50-year 6.2 m, 4 km inland, k 0.33.
    assert ff.surge_height("bholaBarguna", 4.0, 50) == pytest.approx(6.2 - 3 * 0.33)
    # x < 1 is taken as 1.
    assert ff.surge_height("teknafCoxsBazar", 0.3, 100) == pytest.approx(5.8)
    # Never below zero.
    assert ff.surge_height("teknafCoxsBazar", 100.0, 50) == 0.0


def test_design_depth_eq_6_2_69_70():
    flood = FloodSite(
        zone="coastalRisk",
        groundLevel=2.0,
        surgeRegion="teknafCoxsBazar",
        distance=5.0,
        waterLevelStation="sonapur",
    )
    depth = ff.design_depth(flood, "II")
    hs = 4.5 - 4 * 0.5
    hf = 7.11 - 2.0  # the 100-year yT (conservative reading), minus yg
    assert depth.hs == pytest.approx(hs) and depth.hf == pytest.approx(hf)
    assert depth.hm == pytest.approx(max(hs, hf))
    assert depth.gamma == 10.05  # salt water at the coast
    # Category IV: the 100-year surge height.
    assert ff.design_depth(flood, "IV").hs == pytest.approx(5.8 - 4 * 0.5)


def test_inland_depth_and_missing_levels():
    flood = FloodSite(zone="inland", groundLevel=6.0, floodLevel=7.2)
    depth = ff.design_depth(flood, "II")
    assert depth.kind == "inland" and depth.hm == pytest.approx(1.2) and depth.gamma == 9.80
    assert ff.design_depth(FloodSite(zone="inland"), "II").hm == 0.0
    assert ff.design_depth(FloodSite(), "II") is None


def test_hydrodynamic_and_wave_equations():
    # Eq 6.2.72: dh = a VÂ² / 2g, a â‰¥ 1.25.
    dh, notes = ff.surcharge_depth(2.0, 1.0)
    assert dh == pytest.approx(1.25 * 4 / (2 * 9.81)) and notes
    dh, notes = ff.surcharge_depth(3.5)
    assert dh == pytest.approx(1.25 * 3.5**2 / (2 * 9.81)) and "rational" in notes[0]
    # hw = hs/4 â‰¥ 1 m.
    assert ff.wave_amplitude(2.0) == 1.0 and ff.wave_amplitude(6.0) == 1.5
    # Eqs 6.2.73-6.2.74.
    assert ff.still_water_depth(4.0) == pytest.approx(2.6)
    assert ff.breaking_wave_height(2.6) == pytest.approx(0.78 * 2.6)
    # Eq 6.2.75: square column 0.4 m, D = 1.4 Ã— 0.4.
    hb = 2.0
    assert ff.breaking_wave_on_pile(hb, 0.4, False, 10.05) == pytest.approx(
        0.5 * 10.05 * 2.25 * 0.56 * 4
    )
    assert ff.breaking_wave_on_pile(hb, 0.5, True, 9.80) == pytest.approx(
        0.5 * 9.8 * 1.75 * 0.5 * 4
    )
    # Eqs 6.2.76-6.2.78, category III Cp = 3.2.
    ds, g = 2.0, 10.05
    wall = ff.breaking_wave_on_wall(ds, "III", g)
    assert wall["Pmax"] == pytest.approx(3.2 * g * ds + 1.2 * g * ds)
    assert wall["Ft"] == pytest.approx(1.1 * 3.2 * g * ds**2 + 2.4 * g * ds**2)
    wet = ff.breaking_wave_on_wall(ds, "III", g, wet=True)
    assert wet["Ft"] == pytest.approx(1.1 * 3.2 * g * ds**2 + 1.9 * g * ds**2)


def test_impact_eq_6_2_81():
    # V 2 m/s, category II, depth 0.9 m (CD 0.5), channel 5.3 m (CB 0.5), ratio 0.5 (Rmax 1.5).
    found = ff.impact_force(2.0, "II", 0.9, 5.3, 0.5)
    assert found["CD"] == pytest.approx(0.5) and found["CB"] == pytest.approx(0.5)
    assert found["Rmax"] == 1.5
    expected = math.pi * 4448 * 2.0 * 1.0 * 0.8 * 0.5 * 0.5 * 1.5 / (2 * 9.81 * 0.03)
    assert found["F_N"] == pytest.approx(expected)
    assert ff.response_ratio(2.0) == 1.5  # â‰¥ 1.4
    assert ff.response_ratio(0.75) == pytest.approx(1.8)


def test_breakaway_wall_pressure():
    assert ff.breakaway_pressure(0.3, 0.2) == 0.5
    assert ff.breakaway_pressure(0.8) == 0.8


def test_level_bands_and_point_shares():
    shares, below = ff.band_shares([3.0, 6.0, 9.0], 4.0)
    # Levels at 3, 6, 9 m: bands 1.5-4.5, 4.5-7.5, 7.5-: the water to 4 m.
    assert below == pytest.approx(1.5)
    assert shares == pytest.approx([2.5, 0.0, 0.0])
    levels, ground = ff.point_shares([3.0, 6.0], 1.0)
    assert levels == pytest.approx([1 / 3, 0.0]) and ground == pytest.approx(2 / 3)
    levels, ground = ff.point_shares([3.0, 6.0], 4.5)
    assert levels == pytest.approx([0.5, 0.5]) and ground == 0.0


def test_flood_loads_coastal_dry_building():
    flood = FloodSite(
        zone="coastalRisk",
        surgeRegion="teknafCoxsBazar",
        distance=1.0,
        velocity=2.0,
        groundLevel=0.0,
    )
    depth, loads, summary, _notes = ff.flood_loads(
        flood, "II", [3.0, 6.0, 9.0], {0: [20.0] * 3, 1: [10.0] * 3}, []
    )
    hm = 4.5
    assert depth.hm == pytest.approx(hm)
    dh = 1.25 * 4.0 / (2 * 9.81)
    ds = 0.65 * hm
    ft = 1.1 * 2.8 * 10.05 * ds**2 + 2.4 * 10.05 * ds**2
    dynamic = 10.05 * dh * 20.0 * hm
    assert summary["totalX_kN"] == pytest.approx(dynamic + ft * 20.0)
    assert summary["hydrostaticBase_kPa"] == pytest.approx(10.05 * (hm + 0.30))
    assert loads[0].axis == 0 and len(loads[0].level_forces) == 3


def test_stability_and_flotation():
    rows = ff.stability({0: [(100.0, 3.0), (100.0, 6.0)]}, 2000.0, {0: 5.0})
    assert rows[0]["factor"] == pytest.approx(2000 * 5 / 900)
    assert rows[0]["ok"] and rows[0]["slidingFriction"] == pytest.approx(1.5 * 200 / 2000)
    found = flood_uplift(3000.0, 200.0, 1.0, 0.5, 9.80)
    assert found["U_kN"] == pytest.approx(9.80 * 1.5 * 200)
    assert found["factor"] == pytest.approx(3000 / (9.80 * 300)) and not found["ok"]
    assert flood_uplift(3000.0, 200.0, 1.0, openings=True) is None


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ the combinations â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_fa_rows_sec_2_7():
    pack = code_context.table("combinations")
    coastal, inland = pack.flood["coastal"], pack.flood["inland"]
    # Sec 2.7.3.1: 1.6W -> 1.6W + 2.0Fa (coastal), 0.8W + 1.0Fa (inland), rows 4 and 6.
    assert [(r.factors["W"], r.factors["Fa"]) for r in coastal.strength] == [(1.6, 2.0)] * 2
    assert [(r.factors["W"], r.factors["Fa"]) for r in inland.strength] == [(0.8, 1.0)] * 2
    # Sec 2.7.2.1: + 1.5Fa in 5 and 6 (coastal), + 0.75Fa in 5, 6 and 7 (inland), E = 0.
    assert [r.factors["Fa"] for r in coastal.allowable] == [1.5, 1.5]
    assert [r.factors["Fa"] for r in inland.allowable] == [0.75] * 3
    assert all("E" not in r.factors for r in coastal.allowable + inland.allowable)
    assert pack.loadCases["R"] and pack.loadCases["Fa"]
    assert pack.alternates == {"Lr": ["R"]}


def test_fa_expands_with_the_wind():
    row = code_context.table("combinations").flood["coastal"].strength[0]
    formed = expand_rows([row])
    assert len(formed) == 4
    name, factors, _ = formed[1]
    assert factors["WX"] == -1.6 and factors["FaX"] == -2.0 and "FaY" not in factors
    assert "(-FaX)" in name


def test_project_strength_and_allowable_combinations():
    settings = default_project_settings()
    plain = strength_combinations(settings=settings)
    assert not any(c.FaX or c.FaY for c in plain)
    settings.site.flood = FloodSite(zone="inland")
    flooded = strength_combinations(settings=settings)
    added = [c for c in flooded if c.FaX or c.FaY]
    assert len(added) == 8 and added[0].WX == 0.8 and added[0].FaX == 1.0
    present = {"D", "SD", "L", "Lr", "WX", "WY", "FaX", "FaY"}
    names = [n for n, _ in allowable_combinations(present, "inland") if "Fa" in n]
    assert len(names) == 12
    # Without the flood cases the flood rows lose Fa (a load not acting).
    no_fa = allowable_combinations({"D", "SD", "WX", "WY"}, "coastal")
    assert all("FaX" not in f for _, f in no_fa)
    service = flood_service_combinations({"D", "SD", "L", "WX", "FaX"}, "coastal")
    assert service and all("FaY" not in f for _, f in service)
    assert all(f["FaX"] in (1.5, -1.5) for _, f in service)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ rain, helipad, others â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_rain_load_sec_2_6_2():
    assert spl.rain_load(RainSite(depth=100.0)) == pytest.approx(0.98)
    assert spl.rain_load(RainSite(depth=100.0, controlledDrainage=True)) == pytest.approx(1.23)
    assert spl.rain_load(RainSite()) is None


def test_helipad_eq_6_2_82():
    found = spl.helipad_loads(Helipad(weight=30.0, loadedWeight=40.0, gear="rigid"))
    assert found["L1_kN"] == 30.0 and found["L2_kN"] == pytest.approx(60.0)
    assert found["L2_kPa"] == pytest.approx(60.0 / 0.09) and found["L3_kPa"] == 5.0
    assert spl.helipad_loads(Helipad(loadedWeight=40.0, gear="hydraulic"))["L2_kN"] == 30.0


def test_explosion_figure_6_2_33():
    assert spl.explosion_pressure(1.0, 30.0)["q0_kPa"] == pytest.approx(70.0, abs=0.1)
    assert spl.explosion_pressure(1.0, 5.0)["q0_kPa"] == pytest.approx(27.0)
    held = spl.explosion_pressure(1.0, 2.0)
    assert held["q0_kPa"] == pytest.approx(27.0) and held["notes"]
    assert spl.explosion_pressure(1.0, 20.0)["design_kPa"] == pytest.approx(47.0)


def test_shelter_table_6_2_28():
    assert spl.shelter_load(1, False)["load_kPa"] == 28.0
    assert spl.shelter_load(2, False)["load_kPa"] == 34.0  # the '< 2' / '3 - 4' gap: 34
    assert spl.shelter_load(4, False)["load_kPa"] == 34.0
    assert spl.shelter_load(5, False)["load_kPa"] == 41.0
    assert spl.shelter_load(8, True)["load_kPa"] == 28.0
    assert spl.shelter_load(3, False, 6.5)["load_kPa"] == pytest.approx(35.5)
    assert AirRaidShelter(storeysAbove=3).stableConstruction


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ the analysis model â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_derived_model_has_rain_and_flood_cases():
    from test_fem_derive import OBJECTS, PLAN, SETTINGS

    from saengine.fem.derive import derive_fem
    from saengine.library import default_material_library
    from saengine.library.bim import generate

    building = generate(PLAN, "s")
    site = SETTINGS.site.model_copy(
        update={
            "rain": RainSite(depth=100.0),
            "flood": FloodSite(zone="inland", groundLevel=0.0, floodLevel=5.0, velocity=2.0),
        }
    )
    settings = SETTINGS.model_copy(update={"site": site})
    derivation = derive_fem(building, OBJECTS, default_material_library(), settings, {"bim": "x"})
    names = [p["name"] for p in derivation.project["load_patterns"]]
    assert "R" in names and "FaX" in names and "FaY" in names
    rain = next(p for p in derivation.project["load_patterns"] if p["name"] == "R")
    assert sum(n["forces"][2] for n in rain["nodal_loads"]) < 0
    flood = derivation.summary["flood"]
    assert flood["Hm_m"] == pytest.approx(5.0) and flood["totalX_kN"] > 0
    assert derivation.summary["specialLoads"]["rain_kPa"] == pytest.approx(0.98)

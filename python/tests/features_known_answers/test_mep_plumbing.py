"""Independent known-answer tests for standalone calculators in MEP Plumbing, Fixtures, and Drainage."""

from __future__ import annotations

import math

import pytest

from saengine import features

# ── MEP Drainage (mep_drainage_review.py + mep_remaining_a.py: 22) ──────────────────────────────


def test_mep_drainage_attenuation_tank() -> None:
    # A = 1200 m2, i = 50 mm/h = 0.05 m/h, duration = 2 h -> inflow = 1200 * 0.05 * 2 * 1000 = 120,000 L
    # Permitted outflow = 10 L/s * 3600 * 2 = 72,000 L -> storage = 48,000 L.
    res = features.run(
        "mepDrainage.attenuationTank",
        None,
        {"area": 1200, "rain": 50, "duration": 2, "outflow": 10},
    )
    assert res["problems"] == []
    assert res["summary"]["inflowL"] == pytest.approx(120000.0, rel=0.01)
    assert res["summary"]["outflowL"] == pytest.approx(72000.0, rel=0.01)
    assert res["summary"]["requiredVolumeL"] == pytest.approx(48000.0, rel=0.01)


def test_mep_drainage_drain_layout() -> None:
    # fall = 0.75 m over 50 m -> gradient = 0.015 (1.5%).
    res = features.run("mepDrainage.drainLayout", None, {"length": 50, "fall": 0.75})
    assert res["problems"] == []
    assert res["summary"]["gradient"] == pytest.approx(0.015, rel=0.01)
    assert res["summary"]["fallPercent"] == pytest.approx(1.5, rel=0.01)


def test_mep_drainage_drainage_field() -> None:
    # Vp = 25 s/mm -> inverse loading rate = 600 / 25 = 24.0 L/m2/day
    # dailyEffluent = 1.5 m3/day = 1500 L/day -> area = 1500 / 24 = 62.5 m2
    # trench width = 0.5 m -> length = 62.5 / 0.5 = 125.0 m.
    res = features.run(
        "mepDrainage.drainageField",
        None,
        {"dailyEffluent": 1.5, "percolationRate": 25, "trenchWidth": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["applicationRateLPerM2Day"] == pytest.approx(24.0, rel=0.01)
    assert res["summary"]["infiltrationAreaM2"] == pytest.approx(62.5, rel=0.01)
    assert res["summary"]["trenchLengthM"] == pytest.approx(125.0, rel=0.01)


def test_mep_drainage_first_flush_diverter() -> None:
    # 400 m2 * 1.5 mm = 600 L = 0.6 m3.
    res = features.run(
        "mepDrainage.firstFlushDiverter",
        None,
        {"roofArea": 400, "diversionDepth": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["divertedVolumeM3"] == pytest.approx(0.6, rel=0.01)
    assert res["summary"]["divertedVolumeL"] == pytest.approx(600.0, rel=0.01)


def test_mep_drainage_flow_control() -> None:
    # Q = 5 L/s = 0.005 m3/s, h = 2 m -> v = sqrt(2 * 9.81 * 2) = 6.2642 m/s
    # A = 0.005 / 6.2642 = 7.9819e-4 m2 -> d = sqrt(4*A/pi) * 1000 = 31.879 mm.
    v_eff = math.sqrt(2 * 9.81 * 2)
    expected_d = math.sqrt(4 * (0.005 / v_eff) / math.pi) * 1000
    res = features.run("mepDrainage.flowControl", None, {"flow": 5, "head": 2})
    assert res["problems"] == []
    assert res["summary"]["orificeDiameterMm"] == pytest.approx(expected_d, rel=0.01)


def test_mep_drainage_gradient_check() -> None:
    # Invert 12.60 -> 12.15 over 30 m -> fall = 0.45 m, gradient = 0.015 >= 0.01.
    res = features.run(
        "mepDrainage.gradientCheck",
        None,
        {"upstreamInvert": 12.6, "downstreamInvert": 12.15, "length": 30, "minimumGradient": 0.01},
    )
    assert res["problems"] == []
    assert res["summary"]["fallM"] == pytest.approx(0.45, rel=0.01)
    assert res["summary"]["gradient"] == pytest.approx(0.015, rel=0.01)
    assert res["summary"]["pass"] is True


def test_mep_drainage_grease_traps() -> None:
    # Q = 3 L/s, retention = 30 min = 1800 s -> V = 3 * 1800 / 1000 = 5.4 m3.
    res = features.run("mepDrainage.greaseTraps", None, {"flow": 3, "retention": 30})
    assert res["problems"] == []
    assert res["summary"]["volumeM3"] == pytest.approx(5.4, rel=0.01)


def test_mep_drainage_gutters_downpipes() -> None:
    # width = 200 mm, depth = 50 mm -> area = 0.01 m2; Q = 10 L/s = 0.01 m3/s -> v = 1.0 m/s.
    res = features.run("mepDrainage.guttersDownpipes", None, {"flow": 10, "width": 200})
    assert res["problems"] == []
    assert res["summary"]["velocityMs"] == pytest.approx(1.0, rel=0.01)


def test_mep_drainage_harvest_system() -> None:
    # 500 m2 * 1000 mm / 1000 * 0.8 = 400 m3 yield; demand = 250 m3 -> 100% covered, surplus 150 m3.
    res = features.run(
        "mepDrainage.harvestSystem",
        None,
        {"roofArea": 500, "annualRain": 1000, "runoff": 0.8, "demand": 250},
    )
    assert res["problems"] == []
    assert res["summary"]["annualYieldM3"] == pytest.approx(400.0, rel=0.01)
    assert res["summary"]["annualSupplyCoveragePercent"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["surplusM3"] == pytest.approx(150.0, rel=0.01)


def test_mep_drainage_harvest_volume() -> None:
    # Dry demand = 1.0 * 15 = 15.0 m3; inflow = 4.0 m3 -> storage = 11.0 m3.
    res = features.run(
        "mepDrainage.harvestVolume",
        None,
        {"dailyDemand": 1.0, "dryPeriod": 15, "inflow": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["dryPeriodDemandM3"] == pytest.approx(15.0, rel=0.01)
    assert res["summary"]["requiredUsableStorageM3"] == pytest.approx(11.0, rel=0.01)


def test_mep_drainage_infiltration_check() -> None:
    # Excess = 3.2 - 2.0 = 1.2 L/s over 800 m -> 1.2 * 1000 / 800 = 1.5 L/s/km; ratio = 1.6.
    res = features.run(
        "mepDrainage.infiltrationCheck",
        None,
        {"baseFlow": 2.0, "observedFlow": 3.2, "length": 800},
    )
    assert res["problems"] == []
    assert res["summary"]["excessFlowLPerS"] == pytest.approx(1.2, rel=0.01)
    assert res["summary"]["infiltrationLPerSPerKm"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["observedToBaseRatio"] == pytest.approx(1.6, rel=0.01)


def test_mep_drainage_irrigation_demand() -> None:
    # Gross = 4 * 100 = 400 mm; net = 400 - 100 = 300 mm; volume = 1000 * 0.3 = 300 m3.
    res = features.run(
        "mepDrainage.irrigationDemand",
        None,
        {"landscapeArea": 1000, "dailyDepth": 4, "days": 100, "effectiveRain": 100},
    )
    assert res["problems"] == []
    assert res["summary"]["netIrrigationDepthMm"] == pytest.approx(300.0, rel=0.01)
    assert res["summary"]["seasonalDemandM3"] == pytest.approx(300.0, rel=0.01)


def test_mep_drainage_lift_station() -> None:
    # Exact cycle balance: t_fill + t_empty = T => V = Q_in * (Q_p - Q_in) / Q_p * T
    # Q_in = 5 L/s, Q_p = 8 L/s, T = 10 min = 600 s -> V = 5 * (8 - 5) / 8 * 600 / 1000 = 1.125 m3.
    # Check: t_fill = 1125 / 5 = 225 s, t_empty = 1125 / (8 - 5) = 375 s -> 225 + 375 = 600 s = 10 min.
    res = features.run(
        "mepDrainage.liftStation",
        None,
        {"inflow": 5, "pumpCapacity": 8, "cycleMinutes": 10},
    )
    assert res["problems"] == []
    assert res["summary"]["activeVolumeM3"] == pytest.approx(1.125, rel=0.01)


def test_mep_drainage_manholes() -> None:
    # Drain dia 600 mm -> max(900, 2*600) = 1200 mm.
    res = features.run("mepDrainage.manholes", None, {"diameter": 600, "depth": 2.5})
    assert res["problems"] == []
    assert res["summary"]["chamberDiameterMm"] == pytest.approx(1200.0, rel=0.01)
    assert res["summary"]["depthM"] == pytest.approx(2.5, rel=0.01)


def test_mep_drainage_package_treatment() -> None:
    # 100 persons * 172.8 L/p/d / 86400 s/d = 0.20 L/s avg; peak factor 2.5 -> 0.50 L/s.
    res = features.run(
        "mepDrainage.packageTreatment",
        None,
        {"population": 100, "flow": 172.8, "peakFactor": 2.5},
    )
    assert res["problems"] == []
    assert res["summary"]["averageFlowLPerS"] == pytest.approx(0.20, rel=0.01)
    assert res["summary"]["peakFlowLPerS"] == pytest.approx(0.50, rel=0.01)


def test_mep_drainage_pipe_condition() -> None:
    # age = 30 / 60 = 0.5; severity = 3 -> (3 - 1) / 3 = 2/3 -> index = 100 * (0.25 + 1/3) = 58.333.
    res = features.run(
        "mepDrainage.pipeCondition",
        None,
        {"ageYears": 30, "expectedLife": 60, "defectSeverity": 3},
    )
    assert res["problems"] == []
    assert res["summary"]["conditionIndex"] == pytest.approx(58.333, rel=0.01)
    assert res["summary"]["remainingLifeEstimateYears"] == pytest.approx(30.0, rel=0.01)


def test_mep_drainage_pump_station() -> None:
    # P = 9.81 * (10 / 1000) * 15 / 0.70 = 2.1021 kW.
    res = features.run(
        "mepDrainage.pumpStation",
        None,
        {"dutyFlow": 10, "totalHead": 15, "efficiency": 0.70, "pumpCount": 2},
    )
    assert res["problems"] == []
    assert res["summary"]["hydraulicInputKw"] == pytest.approx(2.1021, rel=0.01)
    assert res["summary"]["installedPumps"] == 2


def test_mep_drainage_rainfall_intensity() -> None:
    res = features.run("mepDrainage.rainfallIntensity", None, {"rain": 120})
    assert res["problems"] == []
    assert res["summary"]["rainfallMmPerH"] == pytest.approx(120.0, rel=0.01)


def test_mep_drainage_rainwater_pipes() -> None:
    # Q = 500 * 100 * 0.9 / 3600 = 12.5 L/s; d_min = sqrt(4*12.5 / (pi*2*1000)) * 1000 = 89.21 mm -> 100 mm.
    res = features.run(
        "mepDrainage.rainwaterPipes",
        None,
        {"area": 500, "rain": 100, "runoff": 0.9},
    )
    assert res["problems"] == []
    assert res["summary"]["flowLPerS"] == pytest.approx(12.5, rel=0.01)
    assert res["summary"]["diameterMm"] == 100


def test_mep_drainage_septic_tank() -> None:
    # Liquid = 20 * 150 * 2 / 1000 = 6.0 m3; sludge = 20 * 0.06 * 1.5 = 1.8 m3 -> total 7.8 m3.
    res = features.run(
        "mepDrainage.septicTank",
        None,
        {
            "population": 20,
            "retention": 2,
            "sludge": 0.06,
            "desludgeYears": 1.5,
            "dailyFlow": 150,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["liquidVolumeM3"] == pytest.approx(6.0, rel=0.01)
    assert res["summary"]["sludgeStorageM3"] == pytest.approx(1.8, rel=0.01)
    assert res["summary"]["workingVolumeM3"] == pytest.approx(7.8, rel=0.01)


def test_mep_drainage_soakaway_design() -> None:
    # infiltrationRate = 0.001 m/s over 50 m2 -> Q = 0.001 * 50 * 3600 = 180 m3/h (= 180,000 L/h).
    # inflow = 90 m3 -> drawdown = 90 / 180 = 0.50 h.
    res = features.run(
        "mepDrainage.soakawayDesign",
        None,
        {"inflow": 90, "infiltration": 0.001, "area": 50},
    )
    assert res["problems"] == []
    assert res["summary"]["infiltrationLPerH"] == pytest.approx(180000.0, rel=0.01)
    assert res["summary"]["drawdownHours"] == pytest.approx(0.5, rel=0.01)


def test_mep_drainage_sump_pits() -> None:
    # 6 L/s * 10 min * 60 s / 1000 = 3.6 m3.
    res = features.run("mepDrainage.sumpPits", None, {"inflow": 6, "cycle": 10})
    assert res["problems"] == []
    assert res["summary"]["requiredVolumeM3"] == pytest.approx(3.6, rel=0.01)


# ── MEP Fixtures (mep_fixtures.py + mep_remaining_b.py: 17) ─────────────────────────────────────


def test_mep_fixtures_accessibility() -> None:
    res = features.run(
        "mepFixtures.accessibility",
        None,
        {"clearWidthM": 1.4, "requiredWidthM": 1.2, "clearDepthM": 1.4, "requiredDepthM": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["widthPasses"] is True
    assert res["summary"]["depthPasses"] is False
    assert res["summary"]["passes"] is False


def test_mep_fixtures_accessible_wc() -> None:
    # room 2.4 x 2.0, wcProjection 0.70 -> sideAvailable = 1.70 >= 0.90; frontAvailable = 1.30 >= 1.20.
    res = features.run(
        "mepFixtures.accessibleWc",
        None,
        {
            "roomWidthM": 2.4,
            "roomDepthM": 2.0,
            "wcProjectionM": 0.7,
            "sideTransferM": 0.9,
            "frontClearanceM": 1.2,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["sideAvailableM"] == pytest.approx(1.7, rel=0.01)
    assert res["summary"]["frontAvailableM"] == pytest.approx(1.3, rel=0.01)
    assert res["summary"]["layoutPasses"] is True


def test_mep_fixtures_connection_points() -> None:
    # Cold = 0.1 L/s (>0), hot = 0 (inactive), waste = 50 mm (>0) -> 2 active connectors.
    res = features.run(
        "mepFixtures.connectionPoints",
        None,
        {
            "fixtureTag": "WC-02",
            "fixtureType": "wc",
            "coldWaterLps": 0.1,
            "hotWaterLps": 0.0,
            "wasteDiameterMm": 50,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["fixtureTag"] == "WC-02"
    assert res["summary"]["connectorCount"] == 2


def test_mep_fixtures_diversity_factor() -> None:
    # 4.0 * 0.45 = 1.8 L/s.
    res = features.run(
        "mepFixtures.diversityFactor",
        None,
        {"connectedFlowLps": 4.0, "diversityFactor": 0.45},
    )
    assert res["problems"] == []
    assert res["summary"]["coincidentFlowLps"] == pytest.approx(1.8, rel=0.01)


def test_mep_fixtures_fixture_units_table() -> None:
    res = features.run(
        "mepFixtures.fixtureUnitsTable",
        None,
        {"fixtureType": "basin", "waterSupplyUnits": 1.5, "drainageUnits": 1.0, "flowLps": 0.08},
    )
    assert res["problems"] == []
    assert res["summary"]["fixtureType"] == "basin"
    assert res["summary"]["waterSupplyUnits"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["drainageUnits"] == pytest.approx(1.0, rel=0.01)


def test_mep_fixtures_grab_bars() -> None:
    # length = 900, spacing = 450 -> int(900/450)+1 = 3 supports -> reaction = 1200 / 3 = 400 N <= 750.
    res = features.run(
        "mepFixtures.grabBars",
        None,
        {"barLengthMm": 900, "supportSpacingMm": 450, "designLoadN": 1200, "supportCapacityN": 750},
    )
    assert res["problems"] == []
    assert res["summary"]["supportCount"] == 3
    assert res["summary"]["reactionPerSupportN"] == pytest.approx(400.0, rel=0.01)
    assert res["summary"]["supportPasses"] is True


def test_mep_fixtures_hot_water_share() -> None:
    # Mixing heat balance: (42 - 12) / (62 - 12) = 30 / 50 = 0.60 -> 0.60 * 2.0 = 1.2 L/s hot, 0.8 L/s cold.
    res = features.run(
        "mepFixtures.hotWaterShare",
        None,
        {
            "totalFlowLps": 2.0,
            "hotFraction": 0.5,
            "hotTemperatureC": 62,
            "coldTemperatureC": 12,
            "mixedTemperatureC": 42,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["hotFlowLps"] == pytest.approx(1.2, rel=0.01)
    assert res["summary"]["coldFlowLps"] == pytest.approx(0.8, rel=0.01)


def test_mep_fixtures_mounting_height() -> None:
    res = features.run(
        "mepFixtures.mountingHeight",
        None,
        {
            "fixtureType": "basin",
            "heightMm": 850,
            "permittedMinimumMm": 750,
            "permittedMaximumMm": 900,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["passes"] is True


def test_mep_fixtures_peak_demand() -> None:
    # Table 8.5.5 Hunter curve at 35 tank FU = 84.2 L/min = 84.2 / 60 = 1.4033 L/s.
    res = features.run("mepFixtures.peakDemand", None, {"fixtureUnits": 35})
    assert res["problems"] == []
    assert res["summary"]["probableFlowLps"] == pytest.approx(84.2 / 60.0, rel=0.01)


def test_mep_fixtures_place_fixture() -> None:
    res = features.run(
        "mepFixtures.placeFixture",
        None,
        {"type": "Basin", "x": 1200, "y": 800, "height": 850},
    )
    assert res["problems"] == []
    assert res["summary"]["type"] == "Basin"
    assert res["summary"]["xMm"] == pytest.approx(1200.0, rel=0.01)
    assert res["summary"]["heightMm"] == pytest.approx(850.0, rel=0.01)


def test_mep_fixtures_pressure_requirement() -> None:
    # margin = 175 - 120 = +55 kPa -> passes.
    res = features.run(
        "mepFixtures.pressureRequirement",
        None,
        {"fixtureType": "shower", "minimumDynamicKpa": 120, "availableDynamicKpa": 175},
    )
    assert res["problems"] == []
    assert res["summary"]["pressureMarginKpa"] == pytest.approx(55.0, rel=0.01)
    assert res["summary"]["passes"] is True


def test_mep_fixtures_reach_range() -> None:
    res = features.run(
        "mepFixtures.reachRange",
        None,
        {"controlHeightMm": 1000, "minimumReachMm": 400, "maximumReachMm": 1200},
    )
    assert res["problems"] == []
    assert res["summary"]["withinReachBand"] is True


def test_mep_fixtures_shower_seat() -> None:
    # 1400 - 800 = 600 mm < 750 mm -> transferPasses = False.
    res = features.run(
        "mepFixtures.showerSeat",
        None,
        {
            "seatHeightMm": 460,
            "seatWidthMm": 800,
            "compartmentWidthMm": 1400,
            "requiredTransferMm": 750,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["transferClearanceMm"] == pytest.approx(600.0, rel=0.01)
    assert res["summary"]["transferPasses"] is False


def test_mep_fixtures_turning_circle() -> None:
    # min(1.8, 1.6) = 1.6 m >= 1.5 m -> fits.
    res = features.run(
        "mepFixtures.turningCircle",
        None,
        {"clearWidthM": 1.8, "clearDepthM": 1.6, "requiredDiameterM": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["availableDiameterM"] == pytest.approx(1.6, rel=0.01)
    assert res["summary"]["fits"] is True


def test_mep_fixtures_wall_support() -> None:
    # (40 + 60) kg * 9.80665 * 1.5 / 2 = 735.50 N <= 1000 N -> passes.
    res = features.run(
        "mepFixtures.wallSupport",
        None,
        {
            "fixtureMassKg": 40,
            "contentsMassKg": 60,
            "supportCount": 2,
            "loadFactor": 1.5,
            "supportCapacityN": 1000,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["reactionPerSupportN"] == pytest.approx(100 * 9.80665 * 1.5 / 2, rel=0.01)
    assert res["summary"]["passes"] is True


def test_mep_fixtures_waste_connection() -> None:
    # Table 8.5.x for 4 DFU at 2% slope selects 100 mm outlet -> provided 100 >= 100 passes.
    res = features.run(
        "mepFixtures.wasteConnection",
        None,
        {"fixtureType": "wc", "wasteDiameterMm": 100, "branchSlopePercent": 2, "fixtureUnits": 4},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredDiameterMm"] == 100
    assert res["summary"]["passes"] is True


def test_mep_fixtures_water_connection() -> None:
    # bore = 20 mm -> A = pi*(0.02^2)/4 = 3.14159e-4 m2; Q = 0.25 L/s = 2.5e-4 m3/s
    # velocity = 2.5e-4 / 3.14159e-4 = 0.7958 m/s.
    res = features.run(
        "mepFixtures.waterConnection",
        None,
        {
            "fixtureType": "basin",
            "flowLps": 0.25,
            "pipeDiameterMm": 20,
            "minimumPressureKpa": 100,
            "availablePressureKpa": 150,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["velocityMs"] == pytest.approx(0.7958, rel=0.01)
    assert res["summary"]["pressurePasses"] is True


# ── MEP Plumbing (mep_plumbing.py: 19) ──────────────────────────────────────────────────────────


def test_mep_plumbing_basin_flow_rate() -> None:
    res = features.run("mepPlumbing.basinFlowRate", None, {"count": 8, "flowEach": 6})
    assert res["problems"] == []
    assert res["summary"]["totalFlowLPerMin"] == pytest.approx(48.0, rel=0.01)
    assert res["summary"]["count"] == 8


def test_mep_plumbing_cold_water_sizing() -> None:
    # 30 L/min in 38 mm uPVC (C=150): Q = 5e-4 m3/s, A = pi*0.019^2 = 1.1341e-3 m2 -> v = 0.4409 m/s;
    # Hazen-Williams head loss = 10.67 * Q^1.852 / (150^1.852 * 0.038^4.87) * 100 = 0.6324 m/100m.
    q_m3s = 30.0 / 60000.0
    v_exp = q_m3s / (math.pi * 0.038**2 / 4)
    hl_exp = 10.67 * (q_m3s**1.852) / (150**1.852 * 0.038**4.87) * 100.0
    res = features.run(
        "mepPlumbing.coldWaterSizing",
        None,
        {"flow": 30, "units": 20, "material": "uPVC"},
    )
    assert res["problems"] == []
    assert res["summary"]["diameterMm"] == 38
    assert res["summary"]["velocityMs"] == pytest.approx(v_exp, rel=0.01)
    assert res["summary"]["headLossMPer100m"] == pytest.approx(hl_exp, rel=0.01)


def test_mep_plumbing_downpipe_sizing() -> None:
    # Q = 8 L/s = 0.008 m3/s at 2.0 m/s -> A = 0.004 m2 -> d = sqrt(0.016/pi)*1000 = 71.36 mm -> 75 mm.
    expected_d = math.sqrt(4 * 0.008 / (math.pi * 2.0)) * 1000
    res = features.run("mepPlumbing.downpipeSizing", None, {"flow": 8, "velocity": 2.0})
    assert res["problems"] == []
    assert res["summary"]["requiredBoreMm"] == pytest.approx(expected_d, rel=0.01)
    assert res["summary"]["suggestedNominalMm"] == 75


def test_mep_plumbing_drain_gradient() -> None:
    # fall = 0.45 m over 30 m -> gradient = 0.015 -> 1.5%.
    res = features.run("mepPlumbing.drainGradient", None, {"length": 30, "fall": 0.45})
    assert res["problems"] == []
    assert res["summary"]["gradient"] == pytest.approx(0.015, rel=0.01)
    assert res["summary"]["fallPercent"] == pytest.approx(1.5, rel=0.01)


def test_mep_plumbing_fixture_units() -> None:
    # 10 tank WCs -> supply_units returns positive FU count and >= 13 mm pipe.
    res = features.run(
        "mepPlumbing.fixtureUnits",
        None,
        {"fixture": "wc", "count": 10, "flushValves": False},
    )
    assert res["problems"] == []
    assert res["summary"]["count"] == 10
    assert res["summary"]["fixtureUnits"] >= 20
    assert res["summary"]["minimumPipeMm"] >= 19


def test_mep_plumbing_gutter_sizing() -> None:
    # 300 mm x 50 mm = 15,000 mm2 = 0.015 m2; flow = 12 L/s = 0.012 m3/s -> v = 0.80 m/s.
    res = features.run(
        "mepPlumbing.gutterSizing",
        None,
        {"flow": 12, "width": 300, "depth": 50},
    )
    assert res["problems"] == []
    assert res["summary"]["areaMm2"] == pytest.approx(15000.0, rel=0.01)
    assert res["summary"]["velocityMs"] == pytest.approx(0.8, rel=0.01)


def test_mep_plumbing_hot_water_demand() -> None:
    # 120 * 50 = 6000 L/day; peak = 6000 / 24 * 1.4 = 350 L/h; storage = 0.25 * 6000 = 1500 L.
    res = features.run(
        "mepPlumbing.hotWaterDemand",
        None,
        {"occupants": 120, "litresPerPerson": 50, "peakFactor": 1.4},
    )
    assert res["problems"] == []
    assert res["summary"]["dailyDemandL"] == pytest.approx(6000.0, rel=0.01)
    assert res["summary"]["peakDemandLPerH"] == pytest.approx(350.0, rel=0.01)
    assert res["summary"]["storageVolumeL"] == pytest.approx(1500.0, rel=0.01)


def test_mep_plumbing_overflow_check() -> None:
    res = features.run("mepPlumbing.overflowCheck", None, {"inflow": 6.0, "outflow": 7.5})
    assert res["problems"] == []
    assert res["summary"]["capacityMarginLPerS"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["ok"] is True


def test_mep_plumbing_pipe_velocity_check() -> None:
    # Q = 60 L/min = 0.001 m3/s, d = 25 mm -> A = pi*0.025^2/4 = 4.9087e-4 m2 -> v = 2.0372 m/s <= 2.5.
    expected_v = (60.0 / 60000.0) / (math.pi * 0.025**2 / 4)
    res = features.run(
        "mepPlumbing.pipeVelocityCheck",
        None,
        {"flow": 60, "diameter": 25, "limit": 2.5},
    )
    assert res["problems"] == []
    assert res["summary"]["velocityMs"] == pytest.approx(expected_v, rel=0.01)
    assert res["summary"]["ok"] is True


def test_mep_plumbing_pressure_drop_calc() -> None:
    # Q = 30 L/min = 5e-4 m3/s, d = 40 mm, C_GI = 120, L = 25 m:
    # hl_100 = 10.67 * (5e-4)^1.852 / (120^1.852 * 0.04^4.87) * 100 = 0.7429 m/100m -> *0.25 = 0.1857 m.
    q = 30.0 / 60000.0
    loss_m = 10.67 * (q**1.852) / (120**1.852 * 0.04**4.87) * 100.0 * (25.0 / 100.0)
    res = features.run(
        "mepPlumbing.pressureDropCalc",
        None,
        {"flow": 30, "diameter": 40, "length": 25, "material": "GI"},
    )
    assert res["problems"] == []
    assert res["summary"]["pressureLossM"] == pytest.approx(loss_m, rel=0.01)
    assert res["summary"]["pressureLossKpa"] == pytest.approx(loss_m * 9.807, rel=0.01)


def test_mep_plumbing_pressure_zones() -> None:
    # span = 80 - 5 = 75 m, maxStatic = 35 m -> ceil(75 / 35) = 3 zones.
    res = features.run(
        "mepPlumbing.pressureZones",
        None,
        {"topHeight": 80, "bottomHeight": 5, "maxStatic": 35},
    )
    assert res["problems"] == []
    assert res["summary"]["staticSpanM"] == pytest.approx(75.0, rel=0.01)
    assert res["summary"]["zones"] == 3


def test_mep_plumbing_pump_head_estimate() -> None:
    res = features.run(
        "mepPlumbing.pumpHeadEstimate",
        None,
        {"static": 28, "friction": 7.5, "residual": 12},
    )
    assert res["problems"] == []
    assert res["summary"]["totalHeadM"] == pytest.approx(47.5, rel=0.01)


def test_mep_plumbing_roof_drain_sizing() -> None:
    # 500 m2 * 100 mm/h * 0.90 / 3600 = 12.5 L/s;
    # At 2 m/s, d=75 cap=8.84 L/s (< 12.5), d=100 cap=15.71 L/s (>= 12.5) -> 100 mm.
    res = features.run(
        "mepPlumbing.roofDrainSizing",
        None,
        {"area": 500, "rainfall": 100, "runoff": 0.9},
    )
    assert res["problems"] == []
    assert res["summary"]["flowLPerS"] == pytest.approx(12.5, rel=0.01)
    assert res["summary"]["nominalDiameterMm"] == 100


def test_mep_plumbing_shower_flow_rate() -> None:
    res = features.run("mepPlumbing.showerFlowRate", None, {"count": 12, "flowEach": 9})
    assert res["problems"] == []
    assert res["summary"]["totalFlowLPerMin"] == pytest.approx(108.0, rel=0.01)


def test_mep_plumbing_stack_offsets() -> None:
    # 1000 mm at 30 deg -> horiz = 866.025 mm, vert = 500.0 mm.
    res = features.run("mepPlumbing.stackOffsets", None, {"length": 1000, "angle": 30})
    assert res["problems"] == []
    assert res["summary"]["horizontalMm"] == pytest.approx(866.025, rel=0.01)
    assert res["summary"]["verticalMm"] == pytest.approx(500.0, rel=0.01)


def test_mep_plumbing_urinal_flow_rate() -> None:
    res = features.run(
        "mepPlumbing.urinalFlowRate",
        None,
        {"count": 6, "flowEach": 4.5, "type": "sensor"},
    )
    assert res["problems"] == []
    assert res["summary"]["totalFlowLPerMin"] == pytest.approx(27.0, rel=0.01)


def test_mep_plumbing_waste_branch_sizing() -> None:
    # 30 DFU with 50 mm min outlet selects 100 mm branch per drainage table.
    res = features.run("mepPlumbing.wasteBranchSizing", None, {"units": 30, "outlet": 50})
    assert res["problems"] == []
    assert res["summary"]["diameterMm"] == 100
    assert res["summary"]["dfu"] == pytest.approx(30.0, rel=0.01)


def test_mep_plumbing_water_closet_flow() -> None:
    # 14 flush-valve WCs -> 14 * 2.5 = 35 FU (matching Table 8.5.5 flush-valve column, > tank flow).
    res = features.run(
        "mepPlumbing.waterClosetFlow",
        None,
        {"count": 14, "flushValves": True},
    )
    assert res["problems"] == []
    assert res["summary"]["fixtureUnits"] == pytest.approx(35.0, rel=0.01)
    assert res["summary"]["probableFlowLPerMin"] > 84.2


def test_mep_plumbing_water_meter_size() -> None:
    # flow = 45 L/min -> nominal 20 mm (rated step 50 L/min); nominalRate 60 -> ratio = 0.75 <= 1.
    res = features.run(
        "mepPlumbing.waterMeterSize",
        None,
        {"flow": 45, "nominalRate": 60},
    )
    assert res["problems"] == []
    assert res["summary"]["suggestedNominalMm"] == 20
    assert res["summary"]["flowRatio"] == pytest.approx(0.75, rel=0.01)
    assert res["summary"]["ok"] is True


# ── MEP Plumbing Design (mep_plumbing_design.py: 15) ────────────────────────────────────────────


def test_mep_plumbing_design_balancing_valve() -> None:
    # Authority a = dP_v / (dP_v + dP_c) -> dP_v = dP_c * (1/a - 1) = 15 * (1/0.6 - 1) = 10 kPa <= 25.
    res = features.run(
        "mepPlumbingDesign.balancingValve",
        None,
        {
            "branchFlowLps": 0.8,
            "availableDifferentialKpa": 25,
            "branchLossKpa": 15,
            "targetValveAuthority": 0.6,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["requiredValveDropKpa"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["passes"] is True


def test_mep_plumbing_design_booster_set() -> None:
    # 4.0 L/s over 2 pumps = 2.0 L/s each; hyd = 2.0 * 40 * 9.80665 / 1000 = 0.7845 kW;
    # smallest IEC rating >= 0.7845 kW is 1.1 kW (or 0.75? 0.7845 > 0.75 -> 1.1 kW) / 0.90 = 1.222 kW.
    res = features.run(
        "mepPlumbingDesign.boosterSet",
        None,
        {"peakFlowLps": 4.0, "requiredHeadM": 40, "pumpCount": 2, "motorEfficiency": 0.9},
    )
    assert res["problems"] == []
    assert res["summary"]["flowPerPumpLps"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["motorInputKwEach"] >= 0.7845 / 0.9


def test_mep_plumbing_design_disinfection_unit() -> None:
    # 3.0 m3/h * 20 min / 60 = 1.0 m3; chemical feed = 3.0 m3/h * 2.5 mg/L = 7.5 g/h.
    res = features.run(
        "mepPlumbingDesign.disinfectionUnit",
        None,
        {"flowM3h": 3.0, "contactMinutes": 20, "doseMgL": 2.5},
    )
    assert res["problems"] == []
    assert res["summary"]["contactVolumeM3"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["chemicalFeedGPerH"] == pytest.approx(7.5, rel=0.01)


def test_mep_plumbing_design_filtration_unit() -> None:
    # 4.0 m3/h / 8.0 m3/h/m2 = 0.50 m2 * 0.8 m = 0.40 m3.
    res = features.run(
        "mepPlumbingDesign.filtrationUnit",
        None,
        {"designFlowM3h": 4.0, "filtrationRateM3hM2": 8.0, "bedDepthM": 0.8},
    )
    assert res["problems"] == []
    assert res["summary"]["filterAreaM2"] == pytest.approx(0.5, rel=0.01)
    assert res["summary"]["mediaVolumeM3"] == pytest.approx(0.4, rel=0.01)


def test_mep_plumbing_design_gas_load_calc() -> None:
    # 52.5 kW * 0.80 = 42.0 kW; / 10.5 kWh/m3 = 4.0 m3/h.
    res = features.run(
        "mepPlumbingDesign.gasLoadCalc",
        None,
        {
            "connectedLoadKw": 52.5,
            "diversity": 0.80,
            "runLengthM": 20.0,
            "calorificValueKwhM3": 10.5,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["coincidentLoadKw"] == pytest.approx(42.0, rel=0.01)
    assert res["summary"]["flowM3h"] == pytest.approx(4.0, rel=0.01)


def test_mep_plumbing_design_gully_sizing() -> None:
    res = features.run(
        "mepPlumbingDesign.gullySizing",
        None,
        {"fixtureUnits": 12, "slopePercent": 2.0, "minimumOutletMm": 75},
    )
    assert res["problems"] == []
    assert res["summary"]["outletDiameterMm"] >= 75
    assert res["summary"]["passes"] is True


def test_mep_plumbing_design_hot_water_return() -> None:
    # Heat loss = 50 m * 12 W/m = 600 W = 0.6 kW; flow = 0.6 / (4.186 * 5) * 60 = 1.720 L/min.
    expected_lpm = (50 * 12 / 1000.0) / (4.186 * 5.0) * 60.0
    res = features.run(
        "mepPlumbingDesign.hotWaterReturn",
        None,
        {"lengthM": 50.0, "heatLossWPerM": 12.0, "returnDropC": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["circulationFlowLpm"] == pytest.approx(expected_lpm, rel=0.01)


def test_mep_plumbing_design_medical_gas_outlets() -> None:
    # Engine lookup for 8 O2 outlets = 31.0 L/min.
    res = features.run(
        "mepPlumbingDesign.medicalGasOutlets",
        None,
        {"gas": "O2", "outletCount": 8},
    )
    assert res["problems"] == []
    assert res["summary"]["outletCount"] == 8
    assert res["summary"]["designFlowLpm"] == pytest.approx(31.0, rel=0.01)


def test_mep_plumbing_design_pipe_insulation() -> None:
    # r1 = 30 mm, r2 = 30 + 30 = 60 mm -> ln(r2/r1) = ln(2)
    # q' = 2 * pi * 0.035 * 30 / ln(2) = 9.5177 W/m; OD = 120 mm.
    expected_q = 2 * math.pi * 0.035 * 30 / math.log(2.0)
    res = features.run(
        "mepPlumbingDesign.pipeInsulation",
        None,
        {
            "pipeOuterDiameterMm": 60,
            "insulationThicknessMm": 30,
            "conductivityWmK": 0.035,
            "temperatureDifferenceC": 30,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["heatLossWPerM"] == pytest.approx(expected_q, rel=0.01)
    assert res["summary"]["outerDiameterMm"] == pytest.approx(120.0, rel=0.01)


def test_mep_plumbing_design_pressure_reducing_valve() -> None:
    # upstream = 50 * 9.80665 = 490.3325 kPa; target = 300 -> reduction = 190.3325 kPa.
    res = features.run(
        "mepPlumbingDesign.pressureReducingValve",
        None,
        {"staticHeadM": 50, "targetPressureKpa": 300, "flowLps": 1.2},
    )
    assert res["problems"] == []
    assert res["summary"]["upstreamPressureKpa"] == pytest.approx(490.33, rel=0.01)
    assert res["summary"]["requiredReductionKpa"] == pytest.approx(190.33, rel=0.01)


def test_mep_plumbing_design_pump_curves() -> None:
    # Duty: 2.0 * 25 * 9.80665 / (1000 * 0.7) = 0.7005 kW;
    # Candidate: 2.5 * 30 * 9.80665 / (1000 * 0.7) = 1.0507 kW -> covers duty.
    res = features.run(
        "mepPlumbingDesign.pumpCurves",
        None,
        {
            "flowLps": 2.0,
            "headM": 25,
            "efficiency": 0.70,
            "candidateFlowLps": 2.5,
            "candidateHeadM": 30,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["requiredInputKw"] == pytest.approx(0.7005, rel=0.01)
    assert res["summary"]["candidateInputKw"] == pytest.approx(1.0507, rel=0.01)
    assert res["summary"]["dutyCovered"] is True


def test_mep_plumbing_design_tank_sizing() -> None:
    # 17,000 * 1 / 0.85 = 20,000 L gross; refill over 5 h = 20000 / 18000 = 1.1111 L/s.
    res = features.run(
        "mepPlumbingDesign.tankSizing",
        None,
        {"dailyDemandL": 17000, "autonomyDays": 1, "usableFraction": 0.85, "refillHours": 5},
    )
    assert res["problems"] == []
    assert res["summary"]["grossVolumeL"] == pytest.approx(20000.0, rel=0.01)
    assert res["summary"]["refillFlowLps"] == pytest.approx(1.1111, rel=0.01)


def test_mep_plumbing_design_trap_arm_check() -> None:
    # length 1.5 m <= 3.0 m; fall = 1.5 * 2.0 * 10 = 30.0 mm >= 10 mm -> passes.
    res = features.run(
        "mepPlumbingDesign.trapArmCheck",
        None,
        {
            "armLengthM": 1.5,
            "armDiameterMm": 50,
            "slopePercent": 2.0,
            "maximumLengthM": 3.0,
            "minimumFallMm": 10.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["fallMm"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["passes"] is True


def test_mep_plumbing_design_vent_stack_sizing() -> None:
    # Soil stack 100 mm, 30 FU, 12 m vent -> vent_size returns 65 mm.
    res = features.run(
        "mepPlumbingDesign.ventStackSizing",
        None,
        {"soilStackMm": 100, "fixtureUnits": 30, "stackHeightStories": 4, "ventLengthM": 12},
    )
    assert res["problems"] == []
    assert res["summary"]["ventDiameterMm"] == 65
    assert res["summary"]["stackCapacityUnits"] > 30


def test_mep_plumbing_design_water_softener() -> None:
    # removal = 300 - 50 = 250 mg/L; daily = 2.0 * 24 = 48 m3;
    # load = 48 * 250 / 50 = 240 eq/day * 1 day / 1.2 eq/L = 200 L resin.
    res = features.run(
        "mepPlumbingDesign.waterSoftener",
        None,
        {
            "flowM3h": 2.0,
            "hardnessMgL": 300,
            "targetHardnessMgL": 50,
            "regenerationIntervalDays": 1,
            "resinCapacityEqL": 1.2,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["hardnessRemovalMgL"] == pytest.approx(250.0, rel=0.01)
    assert res["summary"]["resinVolumeL"] == pytest.approx(200.0, rel=0.01)


# ── MEP Plumbing Heating (mep_plumbing_heating.py: 10) ──────────────────────────────────────────


def test_mep_plumbing_heating_balance_valves() -> None:
    # Q = 0.50 L/s = 1.8 m3/h, dP = 25 kPa = 0.25 bar -> Kv_req = 1.8 / sqrt(0.25) = 3.60.
    # Next standard Kv >= 3.60 is 4.5 (DN25); wide-open drop = (1.8 / 4.5)^2 * 100 = 16.0 kPa.
    res = features.run(
        "mepPlumbingHeating.balanceValves",
        None,
        {"flowLps": 0.50, "excessHeadKpa": 25.0, "authorityTarget": 0.50},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredKv"] == pytest.approx(3.60, rel=0.01)
    assert res["summary"]["selectedKv"] == pytest.approx(4.5, rel=0.01)
    assert res["summary"]["nominalDnMm"] == 25
    assert res["summary"]["valveDropKpa"] == pytest.approx(16.0, rel=0.01)


def test_mep_plumbing_heating_cylinder_size() -> None:
    # Office storageFactor = 2.0; 100 occ * 10 L/h = 1000 L/h, t_p = 2 h, uf = 0.75, dT = 45 K:
    # recovery = 2000 / (2 + 2*0.75) = 571.429 L/h; storage = 2.0 * 571.429 = 1142.857 L;
    # powerKw = (571.429 / 3600) * 4.186 * 45 = 29.90 kW.
    res = features.run(
        "mepPlumbingHeating.cylinderSize",
        None,
        {
            "occupancy": "office",
            "occupants": 100,
            "lphPerPerson": 10.0,
            "peakDurationHr": 2.0,
            "usableFraction": 0.75,
            "coldTempC": 15.0,
            "storageTempC": 60.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["recoveryRateLph"] == pytest.approx(571.4, rel=0.01)
    assert res["summary"]["storageVolumeL"] == pytest.approx(1142.9, rel=0.01)
    assert res["summary"]["powerKw"] == pytest.approx(29.90, rel=0.01)


def test_mep_plumbing_heating_heat_exchanger() -> None:
    # Q = 80 kW; prim 80->60, sec 15->60 -> dt1 = 20 K, dt2 = 45 K
    # LMTD = (45 - 20) / ln(45 / 20) = 25 / ln(2.25) = 30.8287 K
    # UA = 80000 / 30.8287 = 2594.98 W/K; Area (U=2500) = 1.038 m2
    # m_prim = 80 / (4.186 * 20) = 0.9556 L/s; m_sec = 80 / (4.186 * 45) = 0.4247 L/s.
    lmtd = (45.0 - 20.0) / math.log(45.0 / 20.0)
    ua = 80000.0 / lmtd
    res = features.run(
        "mepPlumbingHeating.heatExchanger",
        None,
        {
            "dutyKw": 80.0,
            "primaryInC": 80.0,
            "primaryOutC": 60.0,
            "secondaryInC": 15.0,
            "secondaryOutC": 60.0,
            "uValueWPerM2K": 2500.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["lmtdK"] == pytest.approx(lmtd, rel=0.01)
    assert res["summary"]["uaWPerK"] == pytest.approx(ua, rel=0.01)
    assert res["summary"]["areaM2"] == pytest.approx(ua / 2500.0, rel=0.01)
    assert res["summary"]["primaryFlowLps"] == pytest.approx(80.0 / (4.186 * 20.0), rel=0.01)
    assert res["summary"]["secondaryFlowLps"] == pytest.approx(80.0 / (4.186 * 45.0), rel=0.01)


def test_mep_plumbing_heating_heater_capacity() -> None:
    # 720 L/h * 4.186 * 45 K / 3600 = 37.674 kW output; / 0.90 eff = 41.86 kW input.
    q_out = 720.0 * 4.186 * 45.0 / 3600.0
    res = features.run(
        "mepPlumbingHeating.heaterCapacity",
        None,
        {"recoveryRateLph": 720.0, "coldTempC": 15.0, "hotTempC": 60.0, "thermalEfficiency": 0.90},
    )
    assert res["problems"] == []
    assert res["summary"]["thermalOutputKw"] == pytest.approx(q_out, rel=0.01)
    assert res["summary"]["inputPowerKw"] == pytest.approx(q_out / 0.90, rel=0.01)
    assert res["summary"]["deltaTK"] == pytest.approx(45.0, rel=0.01)


def test_mep_plumbing_heating_heater_type() -> None:
    # 3600 L * 4.186 * 45 / 3600 = 188.37 kWh thermal; 4 technologies compared.
    res = features.run(
        "mepPlumbingHeating.heaterType",
        None,
        {"dailyHotWaterL": 3600.0, "coldTempC": 15.0, "hotTempC": 60.0},
    )
    assert res["problems"] == []
    assert res["summary"]["dailyThermalKwh"] == pytest.approx(188.37, rel=0.01)
    assert res["summary"]["optionsCompared"] == 4


def test_mep_plumbing_heating_pump_control() -> None:
    # P0 = 2.0 kW, f = 0.60, hs = 0.20:
    # H(f) = 0.20 + 0.80 * 0.36 = 0.488; P_vfd = 2.0 * 0.488 * 0.60 = 0.5856 kW;
    # P_throt = 2.0 * (0.45 + 0.55 * 0.60) = 1.56 kW -> saving = (1.56 - 0.5856) / 1.56 = 62.46%.
    res = features.run(
        "mepPlumbingHeating.pumpControl",
        None,
        {"ratedPowerKw": 2.0, "partLoadRatio": 0.60, "staticHeadShare": 0.20},
    )
    assert res["problems"] == []
    assert res["summary"]["vfdPowerKw"] == pytest.approx(0.5856, rel=0.01)
    assert res["summary"]["throttledPowerKw"] == pytest.approx(1.56, rel=0.01)
    assert res["summary"]["energySavingPct"] == pytest.approx(62.5, rel=0.01)


def test_mep_plumbing_heating_recirculation_pump() -> None:
    # 100 m * 15 W/m = 1500 W; q = 1.500 / (4.186 * 5) = 0.071667 L/s = 4.30 L/min;
    # P_elec = 9.80665 * 0.071667 * 4.0 / 0.45 = 6.25 W.
    q_lps = 1500.0 / (4186.0 * 5.0)
    elec_w = 9.80665 * q_lps * 4.0 / 0.45
    res = features.run(
        "mepPlumbingHeating.recirculationPump",
        None,
        {"loopLengthM": 100.0, "heatLossWPerM": 15.0, "returnDropC": 5.0, "headLossM": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["loopHeatLossW"] == pytest.approx(1500.0, rel=0.01)
    assert res["summary"]["flowLpm"] == pytest.approx(q_lps * 60.0, rel=0.01)
    assert res["summary"]["pumpPowerW"] == pytest.approx(elec_w, rel=0.01)


def test_mep_plumbing_heating_recovery_rate() -> None:
    # 41.86 kW * 3600 / (4.186 * 50 K) = 720.0 L/h; 900 L tank reheat = 1.25 h = 75.0 min.
    res = features.run(
        "mepPlumbingHeating.recoveryRate",
        None,
        {"tankVolumeL": 900.0, "heaterOutputKw": 41.86, "coldTempC": 10.0, "targetTempC": 60.0},
    )
    assert res["problems"] == []
    assert res["summary"]["recoveryRateLph"] == pytest.approx(720.0, rel=0.01)
    assert res["summary"]["fullReheatMinutes"] == pytest.approx(75.0, rel=0.01)


def test_mep_plumbing_heating_standby_loss() -> None:
    # V = 1.0 m3 -> H=2D -> D = (2/pi)^(1/3) = 0.86025 m, area = 5/2*pi*D^2 = 5.8123 m2;
    # R = 0.05/0.028 + 0.13 = 1.9157 m2*K/W -> U = 0.5220; dT = 40 -> loss = 121.36 W, 2.91 kWh/d.
    d_m = (2.0 / math.pi) ** (1.0 / 3.0)
    area_m2 = 2.5 * math.pi * d_m**2
    u_val = 1.0 / (0.05 / 0.028 + 0.13)
    loss_w = u_val * area_m2 * 40.0
    res = features.run(
        "mepPlumbingHeating.standbyLoss",
        None,
        {"tankVolumeL": 1000.0, "insulationMm": 50.0, "storageTempC": 60.0, "ambientTempC": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["surfaceAreaM2"] == pytest.approx(area_m2, rel=0.01)
    assert res["summary"]["standbyLossW"] == pytest.approx(loss_w, rel=0.01)
    assert res["summary"]["dailyLossKwh"] == pytest.approx(loss_w * 24 / 1000, rel=0.01)


def test_mep_plumbing_heating_trace_heating() -> None:
    # r_in = 0.025 m, r_out = 0.050 m; R_cond = ln(2)/(2*pi*0.036) = 3.0644;
    # R_conv = 1/(9 * 2 * pi * 0.05) = 0.35368; dT = 45 K -> q' = 45 / 3.4181 = 13.165 W/m;
    # installed (+25%) = 16.456 W/m; 100 m -> 1.6456 kW; I_230V = 7.155 A.
    r_cond = math.log(0.05 / 0.025) / (2 * math.pi * 0.036)
    r_conv = 1.0 / (9.0 * 2 * math.pi * 0.05)
    q_m = 45.0 / (r_cond + r_conv)
    inst = 1.25 * q_m
    res = features.run(
        "mepPlumbingHeating.traceHeating",
        None,
        {
            "pipeLengthM": 100.0,
            "pipeOdMm": 50.0,
            "insulationMm": 25.0,
            "maintainTempC": 55.0,
            "ambientTempC": 10.0,
            "name": "traceTest",
        },
    )
    assert res["problems"] == []
    assert res["summary"]["lossWPerM"] == pytest.approx(q_m, rel=0.01)
    assert res["summary"]["installedWPerM"] == pytest.approx(inst, rel=0.01)
    assert res["summary"]["totalLoadKw"] == pytest.approx(inst * 100 / 1000, rel=0.01)
    assert res["summary"]["circuitCurrentA"] == pytest.approx(inst * 100 / 230, rel=0.01)


# ── MEP Plumbing Quality (mep_plumbing_quality.py: 2) ───────────────────────────────────────────


def test_mep_plumbing_quality_chlorine_level() -> None:
    # tau = 24 * 40 / 80 = 12.0 h; c_out = 1.0 * exp(-0.05 * 12) = exp(-0.6) = 0.5488 mg/L >= 0.2.
    res = features.run(
        "mepPlumbingQuality.chlorineLevel",
        None,
        {
            "dosedMgPerL": 1.0,
            "tankVolumeM3": 40.0,
            "dailyDemandM3": 80.0,
            "decayRatePerHr": 0.05,
            "minResidualMgPerL": 0.2,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["residenceTimeHr"] == pytest.approx(12.0, rel=0.01)
    assert res["summary"]["outletResidualMgPerL"] == pytest.approx(math.exp(-0.6), rel=0.01)
    assert res["summary"]["compliant"] is True


def test_mep_plumbing_quality_dead_leg_check() -> None:
    # d = 20 mm, L = 2.0 m -> L/D = 100; V = pi * 0.01^2 * 2.0 * 1000 = 0.6283 L; > 1.5 m -> fail.
    res = features.run(
        "mepPlumbingQuality.deadLegCheck",
        None,
        {"pipeDiameterMm": 20.0, "deadLegLengthM": 2.0, "maxLengthLimitM": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["lengthToDiameterRatio"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["stagnantVolumeL"] == pytest.approx(0.6283, rel=0.01)
    assert res["summary"]["compliant"] is False


# ── MEP Plumbing Rainwater (mep_plumbing_rainwater.py: 11) ──────────────────────────────────────


def test_mep_plumbing_rainwater_distribution_pump() -> None:
    # TDH = 16 + 4 + 10 = 30 m; P_motor = 9.80665 * (2/1000) * 30 / 0.60 = 0.9807 kW.
    res = features.run(
        "mepPlumbingRainwater.distributionPump",
        None,
        {
            "flowLps": 2.0,
            "staticHeadM": 16.0,
            "frictionHeadM": 4.0,
            "residualHeadM": 10.0,
            "pumpEff": 0.60,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["totalDynamicHeadM"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["motorPowerKw"] == pytest.approx(0.98, rel=0.01)


def test_mep_plumbing_rainwater_downpipe() -> None:
    # Effective area = 200 * 0.9 = 180 m2 at 100 mm/h -> flow = 180 * 100 / 3600 = 5.0 L/s;
    # At 100 mm/h, Table 8.7.2 limits are 65->91.75 m2, 75->149.5 m2, 100->321.75 m2 -> DN100.
    res = features.run(
        "mepPlumbingRainwater.downpipe",
        None,
        {"catchmentAreaM2": 200.0, "rainfallMmPerHr": 100.0, "runoffCoeff": 0.90},
    )
    assert res["problems"] == []
    assert res["summary"]["runoffFlowLps"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["leaderDiameterMm"] == 100


def test_mep_plumbing_rainwater_dual_pump_controller() -> None:
    # 2 L/s = 120 L/min, maxStarts = 12/h -> cycle = 5.0 min;
    # min wet well volume = 120 * 5.0 / 4 = 150.0 L; lag cut-in = 2.0 * 1.5 = 3.0 L/s.
    res = features.run(
        "mepPlumbingRainwater.dualPumpController",
        None,
        {"dutyFlowLps": 2.0, "maxStartsPerHour": 12.0, "leadLagFactor": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["minCycleTimeMin"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["minWetWellVolumeL"] == pytest.approx(150.0, rel=0.01)
    assert res["summary"]["lagCutInFlowLps"] == pytest.approx(3.0, rel=0.01)


def test_mep_plumbing_rainwater_gutter_size() -> None:
    # Non-tabular slope 1.5% (15 mm/m) snaps conservatively to 10 mm/m table column without KeyError;
    # flow = 200 * 100 / 3600 = 5.56 L/s.
    res = features.run(
        "mepPlumbingRainwater.gutterSize",
        None,
        {"catchmentAreaM2": 200.0, "rainfallMmPerHr": 100.0, "slopePct": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["peakFlowLps"] == pytest.approx(5.56, rel=0.01)
    assert res["summary"]["gutterWidthMm"] > 0


def test_mep_plumbing_rainwater_retention_basin() -> None:
    # q_in = 0.75 * 80 * 2400 / 3600 = 40.0 L/s; q_out = 15 L/s; t = 3600 s -> V = (40-15)*3.6 = 90.0 m3.
    res = features.run(
        "mepPlumbingRainwater.retentionBasin",
        None,
        {
            "catchmentM2": 2400.0,
            "runoffCoeff": 0.75,
            "rainfallMmPerHr": 80.0,
            "durationMin": 60.0,
            "allowableOutflowLps": 15.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["peakInflowLps"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["storageVolumeM3"] == pytest.approx(90.0, rel=0.01)


def test_mep_plumbing_rainwater_runoff_coefficient() -> None:
    # (0.95*800 + 0.85*400 + 0.25*400) / 1600 = (760 + 340 + 100) / 1600 = 0.75;
    # Q = 0.75 * 120 * 1600 / 3600 = 40.0 L/s.
    res = features.run(
        "mepPlumbingRainwater.runoffCoefficient",
        None,
        {"roofAreaM2": 800.0, "pavedAreaM2": 400.0, "greenAreaM2": 400.0, "rainfallMmPerHr": 120.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalAreaM2"] == pytest.approx(1600.0, rel=0.01)
    assert res["summary"]["compositeC"] == pytest.approx(0.75, rel=0.01)
    assert res["summary"]["peakRunoffLps"] == pytest.approx(40.0, rel=0.01)


def test_mep_plumbing_rainwater_sediment_trap() -> None:
    # 10 L/s = 0.01 m3/s * 60 s = 0.60 m3; depth 1.2 m -> area = 0.50 m2; SOR = 0.01 / 0.5 * 1000 = 20 mm/s.
    res = features.run(
        "mepPlumbingRainwater.sedimentTrap",
        None,
        {"inflowLps": 10.0, "detentionSec": 60.0, "chamberDepthM": 1.2},
    )
    assert res["problems"] == []
    assert res["summary"]["chamberVolumeM3"] == pytest.approx(0.60, rel=0.01)
    assert res["summary"]["planAreaM2"] == pytest.approx(0.50, rel=0.01)
    assert res["summary"]["surfaceOverflowMmPerS"] == pytest.approx(20.0, rel=0.01)


def test_mep_plumbing_rainwater_sizing_method() -> None:
    # yield = 500 * 0.8 * 2.0 = 800 m3; demand = 2.0 * 365 = 730 m3 -> Demand-limited;
    # tank = min(2.0 * 25 = 50, 800 * 0.25 = 200) = 50.0 m3.
    res = features.run(
        "mepPlumbingRainwater.sizingMethod",
        None,
        {
            "roofAreaM2": 500.0,
            "annualRainfallMm": 2000.0,
            "runoffCoeff": 0.80,
            "dailyNonPotableM3": 2.0,
            "dryDays": 25.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["annualYieldM3"] == pytest.approx(800.0, rel=0.01)
    assert res["summary"]["annualDemandM3"] == pytest.approx(730.0, rel=0.01)
    assert res["summary"]["recommendedTankM3"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["regime"] == "Demand-limited"


def test_mep_plumbing_rainwater_submersible_pump() -> None:
    # TDH = 6.5 + 3.0 + 0.5 = 10.0 m; motor = 9.80665 * 0.004 * 10.0 / 0.52 = 0.754 kW;
    # NPSHa = 10.33 + 0.45 - 0.32 - 0.30 = 10.16 m.
    res = features.run(
        "mepPlumbingRainwater.submersiblePump",
        None,
        {"flowLps": 4.0, "liftM": 6.5, "pipeLossM": 3.0, "submergenceMm": 450.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalHeadM"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["motorKw"] == pytest.approx(0.754, rel=0.01)
    assert res["summary"]["npshaM"] == pytest.approx(10.16, rel=0.01)


def test_mep_plumbing_rainwater_tank_inlet() -> None:
    # 12 L/s at 0.90 m/s -> d_min = sqrt(4*0.012 / (pi*0.9)) * 1000 = 130.3 mm -> next leader = 150 mm;
    # overflow next > 151 = 200 mm; v_actual = 0.012 / (pi * 0.075^2) = 0.6791 m/s.
    res = features.run(
        "mepPlumbingRainwater.tankInlet",
        None,
        {"inflowLps": 12.0, "maxInletVelMs": 0.90},
    )
    assert res["problems"] == []
    assert res["summary"]["inletDiameterMm"] == 150
    assert res["summary"]["overflowDiameterMm"] == 200
    assert res["summary"]["inletVelocityMs"] == pytest.approx(0.68, rel=0.01)


def test_mep_plumbing_rainwater_tank_size() -> None:
    # Standalone fallback: yield = 800 * 0.85 * 1.8 = 1224 m3; demand = 200 * 40 = 8000 L/d;
    # recommended = min(1224 * 0.06 = 73.44, 8000 * 15 / 1000 = 120) = 73.44 (~73.4) m3.
    res = features.run(
        "mepPlumbingRainwater.tankSize",
        None,
        {"population": 200.0, "catchmentAreaM2": 800.0, "annualRainfallMm": 1800.0},
    )
    assert res["problems"] == []
    assert res["summary"]["annualYieldM3"] == pytest.approx(1224.0, rel=0.01)
    assert res["summary"]["recommendedTankM3"] == pytest.approx(73.4, rel=0.01)

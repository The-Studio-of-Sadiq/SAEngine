"""Known-answer tests for Project Settings loads tabs (15+19+20+10 = 64 features)."""

import math

import pytest

from saengine import features

# ── settings_loads (15) ─────────────────────────────────────────────────────────────────────────────


def test_settings_loads_accidental_loads() -> None:
    # m = 2000 kg, v = 5.0 m/s, s = 0.20 m -> KE = 0.5*2000*25/1000 = 25.0 kJ; F = 25.0/0.20 = 125.0 kN.
    res = features.run(
        "settingsLoads.accidentalLoads",
        None,
        {
            "impactMassKg": 2000.0,
            "impactVelocityMPerS": 5.0,
            "stoppingDistM": 0.20,
            "internalBlastKpa": 40.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["impactEnergyKj"] == pytest.approx(25.0, rel=0.01)
    assert res["summary"]["equivalentImpactKn"] == pytest.approx(125.0, rel=0.01)
    assert res["summary"]["blastOverpressureKpa"] == pytest.approx(40.0, rel=0.01)


def test_settings_loads_ceiling_load() -> None:
    # 0.25 + 0.10 + 0.15 = 0.50 kN/m².
    res = features.run(
        "settingsLoads.ceilingLoad",
        None,
        {"gridFramingKnPerM2": 0.25, "insulationKnPerM2": 0.10, "lightingFixturesKnPerM2": 0.15},
    )
    assert res["problems"] == []
    assert res["summary"]["totalCeilingKnPerM2"] == pytest.approx(0.50, rel=0.01)


def test_settings_loads_construction_stage_loads() -> None:
    # slab = 250 mm -> 24*0.25 = 6.0 kPa; N = 2 -> peak_fac = 1 + 0.5 + 0.15*0.5 = 1.575.
    # peak = 1.575*6.0 + 0.6 + 3.0/2 = 9.45 + 0.6 + 1.5 = 11.55 kPa; ratio = 11.55/6.0 = 1.925.
    res = features.run(
        "settingsLoads.constructionStageLoads",
        None,
        {
            "slabThicknessMm": 250.0,
            "shoredLevels": 2.0,
            "formworkKnPerM2": 0.6,
            "constructionLiveKnPerM2": 3.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["slabWeightKnPerM2"] == pytest.approx(6.0, rel=0.01)
    assert res["summary"]["peakDemandKnPerM2"] == pytest.approx(11.55, rel=0.01)
    assert res["summary"]["peakLoadRatio"] == pytest.approx(1.925, rel=0.01)


def test_settings_loads_imperfection_factors() -> None:
    # h = 4.0 m -> alpha_h = min(1, 2/2) = 1.0; m = 1 -> alpha_m = 1.0; phi = 0.01 * 1 * 1 = 0.01.
    # L = 5.0 m -> e0 = 5000 / 250 = 20.0 mm.
    res = features.run(
        "settingsLoads.imperfectionFactors",
        None,
        {"buildingHeightM": 4.0, "columnsInRow": 1.0, "memberLengthM": 5.0, "basicPhi0": 0.01},
    )
    assert res["problems"] == []
    assert res["summary"]["alphaH"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["alphaM"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["globalSwayPhi"] == pytest.approx(0.01, rel=0.01)
    assert res["summary"]["memberBowMm"] == pytest.approx(20.0, rel=0.01)


def test_settings_loads_live_load_patterns() -> None:
    # Generates positive arrangement count for 2x2x3 grid.
    res = features.run(
        "settingsLoads.liveLoadPatterns",
        None,
        {"baysX": 2.0, "baysY": 2.0, "floors": 3.0, "bayWidthM": 7.0},
    )
    assert res["problems"] == []
    assert res["summary"]["baysX"] == 2
    assert res["summary"]["baysY"] == 2
    assert res["summary"]["arrangementCount"] > 0


def test_settings_loads_notional_load_set() -> None:
    # directAnalysis yields Ni / Yi = 0.003 -> 0.003 * 5000 = 15.0 kN.
    res = features.run(
        "settingsLoads.notionalLoadSet",
        None,
        {"method": "directAnalysis", "gravityLoadKn": 5000.0, "driftRatio": 0.002},
    )
    assert res["problems"] == []
    assert res["summary"]["coefficient"] == pytest.approx(0.003, rel=0.01)
    assert res["summary"]["notionalForceKn"] == pytest.approx(15.0, rel=0.01)


def test_settings_loads_partition_allowance() -> None:
    # 5.0 kN/m * 10 m / 25 m² = 2.0 kN/m² >= 1.2 pack min -> meetsMinimum = True, governing = 2.0.
    res = features.run(
        "settingsLoads.partitionAllowance",
        None,
        {"wallLinearKnPerM": 5.0, "bayAreaM2": 25.0, "wallLengthM": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["governingAllowanceKnPerM2"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["meetsMinimum"] is True


def test_settings_loads_pattern_ranges() -> None:
    # L = 5.0 m, wd = 1.2*10 = 12, wl = 1.6*10 = 16 kN/m -> L² = 25.
    # M+_all = 0.08*(12+16)*25 = 56.0; M+_skip = (0.08*12 + 0.101*16)*25 = 64.4.
    # M-_all = 0.10*28*25 = 70.0; M-_adj = (1.2 + 1.872)*25 = 76.8.
    res = features.run(
        "settingsLoads.patternRanges",
        None,
        {"spanM": 5.0, "deadKnPerM": 10.0, "liveKnPerM": 10.0, "gammaD": 1.2, "gammaL": 1.6},
    )
    assert res["problems"] == []
    assert res["summary"]["maxPositiveKnM"] == pytest.approx(64.4, rel=0.01)
    assert res["summary"]["maxNegativeKnM"] == pytest.approx(76.8, rel=0.01)
    assert res["summary"]["positiveAmplification"] == pytest.approx(64.4 / 56.0, rel=0.01)
    assert res["summary"]["negativeAmplification"] == pytest.approx(76.8 / 70.0, rel=0.01)


def test_settings_loads_rain_load() -> None:
    # (60 + 40) mm = 0.1 m * 10.0 kN/m³ = 1.00 kPa.
    res = features.run(
        "settingsLoads.rainLoad",
        None,
        {"staticHeadMm": 60.0, "hydraulicHeadMm": 40.0, "waterUnitWeightKnM3": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalDepthMm"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["rainLoadKnPerM2"] == pytest.approx(1.0, rel=0.01)


def test_settings_loads_roof_ponding() -> None:
    # Default inputs yield Cp = 0.1790, Cs = 0.0290, combined = 0.2051 <= 0.25 -> pondingStable = True.
    res = features.run(
        "settingsLoads.roofPonding",
        None,
        {
            "primarySpanM": 12.0,
            "primarySpacingM": 6.0,
            "primaryIxMm4": 3.5e8,
            "secondarySpanM": 6.0,
            "secondarySpacingM": 2.0,
            "secondaryIxMm4": 4.5e7,
            "elasticModulusMpa": 200000.0,
        },
    )
    assert res["problems"] == []
    gamma_w = 9.81e-6
    cp = (gamma_w * 6000.0 * (12000.0**4)) / ((math.pi**4) * 200000.0 * 3.5e8)
    cs = (gamma_w * 2000.0 * (6000.0**4)) / ((math.pi**4) * 200000.0 * 4.5e7)
    assert res["summary"]["cpIndex"] == pytest.approx(cp, rel=0.01)
    assert res["summary"]["csIndex"] == pytest.approx(cs, rel=0.01)
    assert res["summary"]["combinedIndex"] == pytest.approx(cp + 0.9 * cs, rel=0.01)
    assert res["summary"]["pondingStable"] is True


def test_settings_loads_self_weight_factors() -> None:
    # Echoes gravity and finish multipliers with default material list.
    res = features.run(
        "settingsLoads.selfWeightFactors",
        None,
        {"gravityMultiplier": 1.05, "slabAllowanceFactor": 1.1},
    )
    assert res["problems"] == []
    assert res["summary"]["gravityMultiplier"] == pytest.approx(1.05, rel=0.01)
    assert res["summary"]["finishMultiplier"] == pytest.approx(1.1, rel=0.01)
    assert res["summary"]["materialCount"] >= 3


def test_settings_loads_services_allowance() -> None:
    # 0.30 + 0.25 + 0.15 = 0.70 kN/m².
    res = features.run(
        "settingsLoads.servicesAllowance",
        None,
        {"hvacDuctKnPerM2": 0.30, "pipingSprinklerKnPerM2": 0.25, "electricalTraysKnPerM2": 0.15},
    )
    assert res["problems"] == []
    assert res["summary"]["totalServicesKnPerM2"] == pytest.approx(0.70, rel=0.01)


def test_settings_loads_snow_drift_load() -> None:
    # stepHeight = 1.5 m -> pack/physics drift returns positive height, width, and peak drift load.
    res = features.run(
        "settingsLoads.snowDriftLoad",
        None,
        {
            "groundSnowKnPerM2": 2.0,
            "stepHeightM": 1.5,
            "upperLengthM": 25.0,
            "exposureCe": 1.0,
            "thermalCt": 1.0,
        },
    )
    assert res["problems"] == []
    assert 0.0 < res["summary"]["driftHeightM"] <= 1.5
    assert res["summary"]["driftWidthM"] >= 3.0
    assert res["summary"]["peakDriftLoadKnPerM2"] > 0.0


def test_settings_loads_super_dead_load() -> None:
    # 60 mm * 22 = 1.32 + 0.50 + 0.60 = 2.42 kN/m²; vs default finish 1.2 -> diff = 1.22.
    res = features.run(
        "settingsLoads.superDeadLoad",
        None,
        {
            "screedMm": 60.0,
            "screedUnitWeightKnM3": 22.0,
            "tileKnPerM2": 0.50,
            "ceilingServicesKnPerM2": 0.60,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["calculatedSdKnPerM2"] == pytest.approx(2.42, rel=0.01)
    assert res["summary"]["differenceKnPerM2"] == pytest.approx(
        2.42 - res["summary"]["projectFinishKnPerM2"], rel=0.01
    )


def test_settings_loads_wind_pressure_cases() -> None:
    # H/D = 30/15 = 2.0; B/D = 24/15 = 1.6; designCaseCount >= 4.
    res = features.run(
        "settingsLoads.windPressureCases",
        None,
        {"buildingHeightM": 30.0, "planWidthM": 24.0, "planDepthM": 15.0},
    )
    assert res["problems"] == []
    assert res["summary"]["aspectRatioHOverD"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["aspectRatioBOverD"] == pytest.approx(1.6, rel=0.01)
    assert res["summary"]["designCaseCount"] >= 4


# ── settings_loads_live_tables (19) ─────────────────────────────────────────────────────────────────


def test_settings_loads_live_tables_accessible_roof() -> None:
    # 4.0 + 2.0 = 6.0 kN/m².
    res = features.run(
        "settingsLoadsLiveTables.accessibleRoof",
        None,
        {"terraceLiveKpa": 4.0, "paverToppingKpa": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalUnfactoredKpa"] == pytest.approx(6.0, rel=0.01)


def test_settings_loads_live_tables_apply_equipment() -> None:
    # Heavy mechanical equipment UDL = 8.0 kN/m² -> seismic = 8.0 * share.
    res = features.run("settingsLoadsLiveTables.applyEquipment", None, {"equipmentKpa": 8.0})
    assert res["problems"] == []
    assert res["summary"]["equipmentKpa"] == pytest.approx(8.0, rel=0.01)
    assert res["summary"]["seismicLoadKpa"] == pytest.approx(
        8.0 * res["summary"]["seismicMassShare"], rel=0.01
    )


def test_settings_loads_live_tables_apply_storage() -> None:
    # 12.0 kPa exceeds heavy-live limit (4.8 kPa) -> nonReducibleSingleFloor = True.
    res = features.run("settingsLoadsLiveTables.applyStorage", None, {"storageKpa": 12.0})
    assert res["problems"] == []
    assert res["summary"]["nonReducibleSingleFloor"] is True


def test_settings_loads_live_tables_area_load() -> None:
    # 100 m² * 8.5 kPa = 850 kN.
    res = features.run(
        "settingsLoadsLiveTables.areaLoad",
        None,
        {"plantAreaM2": 100.0, "equipmentIntensityKpa": 8.5},
    )
    assert res["problems"] == []
    assert res["summary"]["totalRoomForceKn"] == pytest.approx(850.0, rel=0.01)


def test_settings_loads_live_tables_assembly_factor() -> None:
    # 4.0 kPa <= assemblyCapKpa (4.8) -> reducible = False.
    res = features.run("settingsLoadsLiveTables.assemblyFactor", None, {"assemblyLiveKpa": 4.0})
    assert res["problems"] == []
    assert res["summary"]["reducible"] is False


def test_settings_loads_live_tables_crowd_load() -> None:
    # 5 persons/m² * 0.80 kN = 4.0 kN/m².
    res = features.run(
        "settingsLoadsLiveTables.crowdLoad",
        None,
        {"crowdDensityPerM2": 5.0, "personWeightKn": 0.80},
    )
    assert res["problems"] == []
    assert res["summary"]["crowdLoadKpa"] == pytest.approx(4.0, rel=0.01)


def test_settings_loads_live_tables_dance_floor_load() -> None:
    # 5.0 * 1.8 = 9.0 kN/m².
    res = features.run(
        "settingsLoadsLiveTables.danceFloorLoad",
        None,
        {"staticLiveKpa": 5.0, "dynamicMultiplier": 1.8},
    )
    assert res["problems"] == []
    assert res["summary"]["equivalentDynamicKpa"] == pytest.approx(9.0, rel=0.01)


def test_settings_loads_live_tables_equipment_load() -> None:
    # 60 kN / 5 m² = 12 kPa static * 1.25 = 15 kPa dynamic.
    res = features.run(
        "settingsLoadsLiveTables.equipmentLoad",
        None,
        {"operatingWeightKn": 60.0, "skidAreaM2": 5.0, "vibrationFactor": 1.25},
    )
    assert res["problems"] == []
    assert res["summary"]["staticFootprintKpa"] == pytest.approx(12.0, rel=0.01)
    assert res["summary"]["dynamicFootprintKpa"] == pytest.approx(15.0, rel=0.01)


def test_settings_loads_live_tables_grandstand_impact() -> None:
    # 5.0 * 0.12 = 0.60 kPa horizontal sway.
    res = features.run(
        "settingsLoadsLiveTables.grandstandImpact",
        None,
        {"verticalCrowdKpa": 5.0, "swayShare": 0.12},
    )
    assert res["problems"] == []
    assert res["summary"]["horizontalSwayKpa"] == pytest.approx(0.60, rel=0.01)


def test_settings_loads_live_tables_green_roof_load() -> None:
    # 250 mm * 18 = 4.5 + 0.5 = 5.0 kPa.
    res = features.run(
        "settingsLoadsLiveTables.greenRoofLoad",
        None,
        {"soilDepthMm": 250.0, "satUnitWeightKnM3": 18.0, "vegetationKpa": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["saturatedSoilKpa"] == pytest.approx(4.5, rel=0.01)
    assert res["summary"]["totalGreenRoofDeadKpa"] == pytest.approx(5.0, rel=0.01)


def test_settings_loads_live_tables_heavy_partition() -> None:
    # 0.15 m * 3.0 m * 20.0 = 9.0 kN/m.
    res = features.run(
        "settingsLoadsLiveTables.heavyPartition",
        None,
        {"wallThicknessMm": 150.0, "wallHeightM": 3.0, "masonryUnitWeightKnM3": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["wallLineLoadKnPerM"] == pytest.approx(9.0, rel=0.01)


def test_settings_loads_live_tables_height_factor() -> None:
    # 6.0 / 3.0 = 2.0 -> 10.0 * 2.0 = 20.0 kPa.
    res = features.run(
        "settingsLoadsLiveTables.heightFactor",
        None,
        {"stackHeightM": 6.0, "baseHeightM": 3.0, "baseLoadKpa": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["heightFactor"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["scaledStorageKpa"] == pytest.approx(20.0, rel=0.01)


def test_settings_loads_live_tables_load_reduction() -> None:
    # At = 50, KLL = 4 -> Ai = 200 m²; reduced = 3.0 * reductionFactor.
    res = features.run(
        "settingsLoadsLiveTables.loadReduction",
        None,
        {"tributaryM2": 50.0, "kll": 4.0, "l0Kpa": 3.0},
    )
    assert res["problems"] == []
    assert res["summary"]["influenceAreaM2"] == pytest.approx(200.0, rel=0.01)
    assert res["summary"]["reducedLiveKpa"] == pytest.approx(
        3.0 * res["summary"]["reductionFactor"], rel=0.01
    )


def test_settings_loads_live_tables_maintenance_load() -> None:
    # Direct echo of concentrated point load and distributed maintenance UDL.
    res = features.run(
        "settingsLoadsLiveTables.maintenanceLoad",
        None,
        {"concentratedKn": 2.0, "uniformMinKpa": 1.0},
    )
    assert res["problems"] == []
    assert res["summary"]["pointLoadKn"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["distributedKpa"] == pytest.approx(1.0, rel=0.01)


def test_settings_loads_live_tables_movable_partition() -> None:
    # 3.0 kN/m <= 5.5 lightMax -> eligibleForUdl = True; equivalent UDL = 3.0 * 0.33 = 0.99 kPa.
    res = features.run(
        "settingsLoadsLiveTables.movablePartition",
        None,
        {"lineWeightKnPerM": 3.0, "wallHeightM": 3.0},
    )
    assert res["problems"] == []
    assert res["summary"]["eligibleForUdl"] is True
    assert res["summary"]["equivalentUdlKpa"] == pytest.approx(0.99, rel=0.01)


def test_settings_loads_live_tables_partition_reserve() -> None:
    # 1.5 + 0.75 = 2.25 kPa.
    res = features.run(
        "settingsLoadsLiveTables.partitionReserve",
        None,
        {"reserveKpa": 0.75, "baseFloorFinishKpa": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["totalAllowanceKpa"] == pytest.approx(2.25, rel=0.01)


def test_settings_loads_live_tables_point_load() -> None:
    # 60 kN / 6 supports = 10.0 kN per support.
    res = features.run(
        "settingsLoadsLiveTables.pointLoad",
        None,
        {"totalWeightKn": 60.0, "supportCount": 6.0},
    )
    assert res["problems"] == []
    assert res["summary"]["loadPerSupportKn"] == pytest.approx(10.0, rel=0.01)


def test_settings_loads_live_tables_rack_load() -> None:
    # 10 kN * 5 levels * 2 pallets = 100 kN bay load -> 25 kN per post.
    res = features.run(
        "settingsLoadsLiveTables.rackLoad",
        None,
        {"palletWeightKn": 10.0, "levels": 5.0, "palletsPerBay": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalBayLoadKn"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["postLoadKn"] == pytest.approx(25.0, rel=0.01)


def test_settings_loads_live_tables_solar_panel_weight() -> None:
    # 0.25 + 0.55 = 0.80 kPa.
    res = features.run(
        "settingsLoadsLiveTables.solarPanelWeight",
        None,
        {"moduleKpa": 0.25, "ballastKpa": 0.55},
    )
    assert res["problems"] == []
    assert res["summary"]["totalSolarSdKpa"] == pytest.approx(0.80, rel=0.01)


# ── settings_loads_moving (20) ──────────────────────────────────────────────────────────────────────


def test_settings_loads_moving_apply_vehicle() -> None:
    # Span = 24 m gives dynamic multiplier 1.33 (33% impact).
    res = features.run("settingsLoadsMoving.applyVehicle", None, {"spanM": 24.0})
    assert res["problems"] == []
    assert res["summary"]["dynamicMultiplier"] == pytest.approx(1.33, rel=0.01)
    assert res["summary"]["impactPct"] == pytest.approx(33.0, rel=0.01)


def test_settings_loads_moving_axle_load() -> None:
    # 40 + 160 + 160 = 360 kN; s = 4.0 m -> span = 12 m -> M = 360*12/4 - 40*4 = 1080 - 160 = 920 kN·m.
    res = features.run(
        "settingsLoadsMoving.axleLoad",
        None,
        {"frontAxleKn": 40.0, "driveAxleKn": 160.0, "rearAxleKn": 160.0, "spacingM": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["grossVehicleKn"] == pytest.approx(360.0, rel=0.01)
    assert res["summary"]["wheelbaseM"] == pytest.approx(8.0, rel=0.01)
    assert res["summary"]["refSpanMaxMomentKnM"] == pytest.approx(920.0, rel=0.01)


def test_settings_loads_moving_braking_force() -> None:
    # 25% of 400 = 100.0 kN; 5% of (400 + 10*40) = 40.0 kN -> governing = 100.0 kN.
    res = features.run(
        "settingsLoadsMoving.brakingForce",
        None,
        {"designTruckKn": 400.0, "laneLoadKnPerM": 10.0, "loadedLengthM": 40.0},
    )
    assert res["problems"] == []
    assert res["summary"]["truck25PctKn"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["combo5PctKn"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["designBrakingKn"] == pytest.approx(100.0, rel=0.01)


def test_settings_loads_moving_centrifugal_force() -> None:
    # v = 72 km/h = 20 m/s, R = 200 m -> C = (4/3)*400 / (9.80665*200) = 0.27193; F = 0.27193 * 300 = 81.58 kN.
    res = features.run(
        "settingsLoadsMoving.centrifugalForce",
        None,
        {"speedKmPerH": 72.0, "curveRadiusM": 200.0, "axleWeightKn": 300.0},
    )
    assert res["problems"] == []
    c = (4.0 / 3.0) * (20.0**2) / (9.80665 * 200.0)
    assert res["summary"]["centrifugalRatioC"] == pytest.approx(c, rel=0.01)
    assert res["summary"]["centrifugalForceKn"] == pytest.approx(c * 300.0, rel=0.01)


def test_settings_loads_moving_crane_load() -> None:
    # Positive vertical impact wheel load > static max wheel load.
    res = features.run(
        "settingsLoadsMoving.craneLoad",
        None,
        {"capacityKn": 120.0, "bridgeWeightKn": 80.0, "trolleyWeightKn": 20.0, "spanM": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["staticWheelKn"] > 0.0
    assert res["summary"]["verticalWithImpactKn"] > res["summary"]["staticWheelKn"]


def test_settings_loads_moving_cyclic_vehicle() -> None:
    # 200 * 1.15 = 230.0 kN.
    res = features.run(
        "settingsLoadsMoving.cyclicVehicle",
        None,
        {"fatigueTruckKn": 200.0, "impactFactor": 1.15},
    )
    assert res["problems"] == []
    assert res["summary"]["factoredFatigueKn"] == pytest.approx(230.0, rel=0.01)


def test_settings_loads_moving_dynamic_factor() -> None:
    # Span = 20 m gives dynamic factor = 1.33.
    res = features.run("settingsLoadsMoving.dynamicFactor", None, {"spanM": 20.0})
    assert res["problems"] == []
    assert res["summary"]["dynamicFactor"] == pytest.approx(1.33, rel=0.01)


def test_settings_loads_moving_envelope_generation() -> None:
    # 24 m span moving load envelope yields positive max moment and shear > single-span 20 m.
    res = features.run("settingsLoadsMoving.envelopeGeneration", None, {"spanM": 24.0})
    assert res["problems"] == []
    assert res["summary"]["maxEnvelopeMomentKnM"] > 2500.0
    assert res["summary"]["maxEnvelopeShearKn"] > 500.0


def test_settings_loads_moving_influence_line() -> None:
    # Simple span 20 m -> peak midspan moment ordinate = L/4 = 5.0 m.
    res = features.run(
        "settingsLoadsMoving.influenceLine",
        None,
        {"span1M": 20.0, "span2M": 0.0},
    )
    assert res["problems"] == []
    assert res["summary"]["samplePeakMomentOrdinateM"] == pytest.approx(5.0, rel=0.02)


def test_settings_loads_moving_lane_definition() -> None:
    # 11.0 m carriageway -> 3 design lanes with m = 0.85.
    res = features.run("settingsLoadsMoving.laneDefinition", None, {"carriagewayWidthM": 11.0})
    assert res["problems"] == []
    assert res["summary"]["designLanes"] == 3
    assert res["summary"]["multiplePresenceFactor"] == pytest.approx(0.85, rel=0.01)


def test_settings_loads_moving_lane_eccentricity() -> None:
    # 14/2 - 0.5 - 3.6/2 = 7.0 - 0.5 - 1.8 = 4.7 m.
    res = features.run(
        "settingsLoadsMoving.laneEccentricity",
        None,
        {"deckWidthM": 14.0, "laneWidthM": 3.6, "curbClearanceM": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["maxLaneEccentricityM"] == pytest.approx(4.7, rel=0.01)


def test_settings_loads_moving_lane_path() -> None:
    # 80 m / 4 m + 1 = 21 stations.
    res = features.run(
        "settingsLoadsMoving.lanePath",
        None,
        {"bridgeLengthM": 80.0, "stationStepM": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["stationCount"] == 21


def test_settings_loads_moving_lane_width() -> None:
    # 9.0 / 3.0 = 3.0 kPa.
    res = features.run(
        "settingsLoadsMoving.laneWidth",
        None,
        {"laneWidthM": 3.0, "laneUdlKnPerM": 9.0},
    )
    assert res["problems"] == []
    assert res["summary"]["equivalentPressureKpa"] == pytest.approx(3.0, rel=0.01)


def test_settings_loads_moving_overload_truck() -> None:
    # 1200 / 800 = 1.5 > 1.0 -> exceedsDesignEnvelope = True.
    res = features.run(
        "settingsLoadsMoving.overloadTruck",
        None,
        {"designMomentKnM": 800.0, "overloadMomentKnM": 1200.0},
    )
    assert res["problems"] == []
    assert res["summary"]["overloadRatio"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["exceedsDesignEnvelope"] is True


def test_settings_loads_moving_permit_vehicle() -> None:
    # 800 kN / 8 axles = 100 kN/axle; factored = 800 * 1.35 = 1080 kN.
    res = features.run(
        "settingsLoadsMoving.permitVehicle",
        None,
        {"grossWeightKn": 800.0, "axles": 8.0, "permitLiveFactor": 1.35},
    )
    assert res["problems"] == []
    assert res["summary"]["meanAxleKn"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["factoredGrossKn"] == pytest.approx(1080.0, rel=0.01)


def test_settings_loads_moving_rating_vehicle() -> None:
    # (2000 - 500) / 1000 = 1.5 >= 1.0 -> adequate = True.
    res = features.run(
        "settingsLoadsMoving.ratingVehicle",
        None,
        {"capacityPhiRnKnM": 2000.0, "deadMomentKnM": 500.0, "vehicleMomentKnM": 1000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["ratingFactor"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["adequate"] is True


def test_settings_loads_moving_repetition_index() -> None:
    # 365 * 50 * 2000 * 1.5 = 54.75e6 cycles -> 54.75 million.
    res = features.run(
        "settingsLoadsMoving.repetitionIndex",
        None,
        {"adttSingleLane": 2000.0, "designLifeYears": 50.0, "cyclesPerTruck": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["totalFatigueCycles"] == pytest.approx(54.75e6, rel=0.01)
    assert res["summary"]["millionsOfCycles"] == pytest.approx(54.75, rel=0.01)


def test_settings_loads_moving_stress_range_truck() -> None:
    # 80 - (-20) = 100 MPa / 125 MPa = 0.80 <= 1.0 -> passing = True.
    res = features.run(
        "settingsLoadsMoving.stressRangeTruck",
        None,
        {"sigmaMaxMpa": 80.0, "sigmaMinMpa": -20.0, "allowableRangeMpa": 125.0},
    )
    assert res["problems"] == []
    assert res["summary"]["stressRangeMpa"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["utilisation"] == pytest.approx(0.80, rel=0.01)
    assert res["summary"]["passing"] is True


def test_settings_loads_moving_train_load() -> None:
    # L = 16 m -> phi = 1.44/(4 - 0.2) + 0.82 = 1.1989; static = 80*256/8 + 250*16/2 = 2560 + 2000 = 4560.
    res = features.run(
        "settingsLoadsMoving.trainLoad",
        None,
        {"udlKnPerM": 80.0, "axleKn": 250.0, "spanM": 16.0},
    )
    assert res["problems"] == []
    phi = 1.44 / (math.sqrt(16.0) - 0.2) + 0.82
    assert res["summary"]["dynamicFactor"] == pytest.approx(phi, rel=0.01)
    assert res["summary"]["staticMomentKnM"] == pytest.approx(4560.0, rel=0.01)
    assert res["summary"]["dynamicMomentKnM"] == pytest.approx(4560.0 * phi, rel=0.01)


def test_settings_loads_moving_wheel_spacing() -> None:
    # 160 kN / 2 = 80 kN wheel; 2.0 m / 2 = 1.0 m half offset.
    res = features.run(
        "settingsLoadsMoving.wheelSpacing",
        None,
        {"gaugeWidthM": 2.0, "axleLoadKn": 160.0},
    )
    assert res["problems"] == []
    assert res["summary"]["wheelLoadKn"] == pytest.approx(80.0, rel=0.01)
    assert res["summary"]["halfOffsetM"] == pytest.approx(1.0, rel=0.01)


# ── settings_loads_self_weight (10) ─────────────────────────────────────────────────────────────────


def test_settings_loads_self_weight_apply_density() -> None:
    # 2350 + 150 = 2500 kg/m³ -> * 9.80665e-3 = 24.5166 kN/m³.
    res = features.run(
        "settingsLoadsSelfWeight.applyDensity",
        None,
        {"rebarAllowanceKgM3": 150.0},
    )
    assert res["problems"] == []
    assert res["summary"]["effectiveRcDensityKgM3"] == pytest.approx(2500.0, rel=0.01)
    assert res["summary"]["unitWeightKnPerM3"] == pytest.approx(2500.0 * 9.80665e-3, rel=0.01)


def test_settings_loads_self_weight_cladding_weight() -> None:
    # 0.75 * 4.0 = 3.0 kN/m.
    res = features.run(
        "settingsLoadsSelfWeight.claddingWeight",
        None,
        {"curtainWallKpa": 0.75, "storeyHeightM": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["perimeterLineLoadKnPerM"] == pytest.approx(3.0, rel=0.01)


def test_settings_loads_self_weight_compare_estimate() -> None:
    # Area weight = 500 * 6 * 9.0 = 27,000 kN vs prelim 20,000 kN -> diff = +35%.
    res = features.run(
        "settingsLoadsSelfWeight.compareEstimate",
        None,
        {
            "preliminaryWeightKn": 20000.0,
            "floorAreaPerStoreyM2": 500.0,
            "storeys": 6.0,
            "unitBuildingWeightKpa": 9.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["areaBasedKn"] == pytest.approx(27000.0, rel=0.01)
    assert res["summary"]["differencePct"] == pytest.approx(35.0, rel=0.01)


def test_settings_loads_self_weight_dead_load_factor() -> None:
    # Echoes targetGammaD = 1.35 alongside active combination D bounds (min <= max).
    res = features.run("settingsLoadsSelfWeight.deadLoadFactor", None, {"gammaD": 1.35})
    assert res["problems"] == []
    assert res["summary"]["targetGammaD"] == pytest.approx(1.35, rel=0.01)
    assert res["summary"]["maxDeadFactor"] >= res["summary"]["minDeadFactor"]


def test_settings_loads_self_weight_density_override() -> None:
    # 2500 * 9.80665e-3 = 24.5166 kN/m³.
    res = features.run(
        "settingsLoadsSelfWeight.densityOverride",
        None,
        {"materialId": "C40", "overrideDensityKgM3": 2500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["unitWeightKnPerM3"] == pytest.approx(2500.0 * 9.80665e-3, rel=0.01)


def test_settings_loads_self_weight_gravity_multiplier() -> None:
    # g = 9.81 m/s² -> mass factor = 1 / 9.81 = 0.101937 t/kN.
    res = features.run("settingsLoadsSelfWeight.gravityMultiplier", None, {"gMPerS2": 9.81})
    assert res["problems"] == []
    assert res["summary"]["gravityMPerS2"] == pytest.approx(9.81, rel=0.01)
    assert res["summary"]["massFactorKgPerN"] == pytest.approx(1.0 / 9.81, rel=0.01)


def test_settings_loads_self_weight_load_multiplier() -> None:
    # Direct echo of global self-weight multiplier.
    res = features.run("settingsLoadsSelfWeight.loadMultiplier", None, {"selfWeightFactor": 1.08})
    assert res["problems"] == []
    assert res["summary"]["selfWeightMultiplier"] == pytest.approx(1.08, rel=0.01)


def test_settings_loads_self_weight_mep_weight() -> None:
    # Direct echo of MEP utility dead load allowance.
    res = features.run("settingsLoadsSelfWeight.mepWeight", None, {"mepKpa": 0.45})
    assert res["problems"] == []
    assert res["summary"]["mepAllowanceKpa"] == pytest.approx(0.45, rel=0.01)


def test_settings_loads_self_weight_topping_thickness() -> None:
    # 75 mm * 24.0 kN/m³ = 1.80 kN/m².
    res = features.run(
        "settingsLoadsSelfWeight.toppingThickness",
        None,
        {"toppingMm": 75.0, "unitWeightKnM3": 24.0},
    )
    assert res["problems"] == []
    assert res["summary"]["toppingLoadKpa"] == pytest.approx(1.80, rel=0.01)


def test_settings_loads_self_weight_unit_weight() -> None:
    # 7850 kg/m³ (steel) * 9.80665e-3 = 76.9822 kN/m³.
    res = features.run("settingsLoadsSelfWeight.unitWeight", None, {"densityKgM3": 7850.0})
    assert res["problems"] == []
    assert res["summary"]["unitWeightKnPerM3"] == pytest.approx(7850.0 * 9.80665e-3, rel=0.01)

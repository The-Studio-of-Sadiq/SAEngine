"""Independent known-answer tests for standalone calculators in MEP Fire, Sprinklers, Alarms, Dampers, and Smoke Control."""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import pytest

from saengine import features

# ── MEP Fire (mep_fire.py + mep_fire_design.py: 18) ──────────────────────────────────────────────


def test_mep_fire_alarm_valve() -> None:
    # Q = 10 L/s = 0.01 m3/s, d = 100 mm -> v = 0.01 / (pi * 0.05^2) = 1.2732 m/s
    # dP = K * rho * v^2 / 2 / 1000 = 2.5 * 1.27324^2 / 2 = 2.0264 kPa -> residual = 497.97 kPa.
    v = 0.01 / (math.pi * 0.05**2)
    dp = 2.5 * (v**2) / 2.0
    res = features.run(
        "mepFire.alarmValve",
        None,
        {
            "systemFlowLps": 10,
            "valveLossCoefficient": 2.5,
            "upstreamPressureKpa": 500,
            "minimumResidualKpa": 350,
            "valveBoreMm": 100,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["valveLossKpa"] == pytest.approx(dp, rel=0.01)
    assert res["summary"]["residualPressureKpa"] == pytest.approx(500 - dp, rel=0.01)
    assert res["summary"]["residualPasses"] is True


def test_mep_fire_beam_detector() -> None:
    # ceil(2500 / 1000) = 3 beams; 80 m <= 100 m max path -> passes.
    res = features.run(
        "mepFire.beamDetector",
        None,
        {"openAreaM2": 2500, "beamCoverageM2": 1000, "maximumPathM": 100, "longestPathM": 80},
    )
    assert res["problems"] == []
    assert res["summary"]["beamDetectorCount"] == 3
    assert res["summary"]["pathPasses"] is True


def test_mep_fire_booster_pump() -> None:
    # 350 + 25*9.80665 + 30 - 180 = 200 + 245.166 = 445.166 kPa (/ 9.80665 = 45.394 m).
    req_kpa = 350 + 25 * 9.80665 + 30 - 180
    res = features.run(
        "mepFire.boosterPump",
        None,
        {
            "requiredResidualKpa": 350,
            "availableSupplyKpa": 180,
            "elevationM": 25,
            "frictionLossKpa": 30,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["boosterDifferentialKpa"] == pytest.approx(req_kpa, rel=0.01)
    assert res["summary"]["boosterHeadM"] == pytest.approx(req_kpa / 9.80665, rel=0.01)
    assert res["summary"]["boosterRequired"] is True


def test_mep_fire_fire_compartments() -> None:
    res = features.run("mepFire.fireCompartments", None, {"area": 1500, "perimeter": 160})
    assert res["problems"] == []
    assert res["summary"]["areaM2"] == pytest.approx(1500.0, rel=0.01)
    assert res["summary"]["perimeterM"] == pytest.approx(160.0, rel=0.01)


def test_mep_fire_fire_doors() -> None:
    res = features.run("mepFire.fireDoors", None, {"count": 14, "leafWidth": 1000})
    assert res["problems"] == []
    assert res["summary"]["doorCount"] == 14
    assert res["summary"]["leafWidthMm"] == pytest.approx(1000.0, rel=0.01)


def test_mep_fire_fire_pump() -> None:
    # hyd = 9.80665 * 25 * 70 / 1000 = 17.1616 kW; input = 17.1616 / (0.72 * 0.90) = 26.484 kW;
    # installed pumps = 1 + 1 = 2.
    hyd = 9.80665 * 25 * 70 / 1000
    res = features.run(
        "mepFire.firePump",
        None,
        {
            "flowLps": 25,
            "headM": 70,
            "pumpEfficiency": 0.72,
            "motorEfficiency": 0.9,
            "standbyPumps": 1,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["hydraulicPowerKw"] == pytest.approx(hyd, rel=0.01)
    assert res["summary"]["motorInputKw"] == pytest.approx(hyd / (0.72 * 0.9), rel=0.01)
    assert res["summary"]["installedPumpCount"] == 2


def test_mep_fire_firestopping_seals() -> None:
    res = features.run("mepFire.firestoppingSeals", None, {"penetrations": 32, "allowance": 40})
    assert res["problems"] == []
    assert res["summary"]["penetrations"] == 32
    assert res["summary"]["sealAllowanceMm"] == pytest.approx(40.0, rel=0.01)


def test_mep_fire_flow_switch() -> None:
    res = features.run(
        "mepFire.flowSwitch",
        None,
        {"normalFlowLps": 0.1, "alarmFlowLps": 1.2, "switchSetpointLps": 0.5, "switchDelayS": 25},
    )
    assert res["problems"] == []
    assert res["summary"]["detectsDesignFlow"] is True
    assert res["summary"]["avoidsNormalFlowAlarm"] is True
    assert res["summary"]["delayS"] == pytest.approx(25.0, rel=0.01)


def test_mep_fire_heat_detector() -> None:
    # by_area = ceil(160 / 50) = 4; by_spacing = ceil(20 / 7) = 3 -> max = 4.
    res = features.run(
        "mepFire.heatDetector",
        None,
        {"roomAreaM2": 160, "detectorCoverageM2": 50, "roomLengthM": 20, "maximumSpacingM": 7},
    )
    assert res["problems"] == []
    assert res["summary"]["countByArea"] == 4
    assert res["summary"]["countBySpacing"] == 3
    assert res["summary"]["detectorCount"] == 4


def test_mep_fire_hose_reel() -> None:
    res = features.run("mepFire.hoseReel", None, {"travel": 35, "flow": 32})
    assert res["problems"] == []
    assert res["summary"]["travelM"] == pytest.approx(35.0, rel=0.01)
    assert res["summary"]["flowLPerMin"] == pytest.approx(32.0, rel=0.01)


def test_mep_fire_hydrant_flow() -> None:
    res = features.run(
        "mepFire.hydrantFlow",
        None,
        {"required": 1000, "available": 1350, "pressure": 240},
    )
    assert res["problems"] == []
    assert res["summary"]["ok"] is True
    assert res["summary"]["residualKpa"] == pytest.approx(240.0, rel=0.01)


def test_mep_fire_manual_call_point() -> None:
    # ceil(75 / 30) = 3 call points.
    res = features.run(
        "mepFire.manualCallPoint",
        None,
        {"escapeRouteLengthM": 75, "maximumTravelSpacingM": 30, "mountingHeightMm": 1200},
    )
    assert res["problems"] == []
    assert res["summary"]["callPointCount"] == 3


def test_mep_fire_pipe_schedule() -> None:
    # 600 L/min = 0.01 m3/s <= 5.0 m/s max velocity: DN38 bore 40.9 mm -> 7.61 m/s (fails),
    # DN50 bore 52.5 mm -> 4.62 m/s (passes) -> 50 mm.
    res = features.run(
        "mepFire.pipeSchedule",
        None,
        {"method": "schedule", "material": "steel", "designFlowLpm": 600, "minimumDiameterMm": 25},
    )
    assert res["problems"] == []
    assert res["summary"]["selectedDiameterMm"] == 50


def test_mep_fire_pump_curve() -> None:
    res = features.run("mepFire.pumpCurve", None, {"flow": 2500, "head": 65})
    assert res["problems"] == []
    assert res["summary"]["ratedFlowLPerMin"] == pytest.approx(2500.0, rel=0.01)
    assert res["summary"]["ratedHeadM"] == pytest.approx(65.0, rel=0.01)
    assert res["tables"][0]["rows"][1]["head"] == pytest.approx(65.0 * 0.8, rel=0.01)


def test_mep_fire_sprinkler_density() -> None:
    # 5 * 140 = 700 L/min + 500 hose = 1200 L/min = 20.0 L/s.
    res = features.run(
        "mepFire.sprinklerDensity",
        None,
        {"hazard": "ordinary", "densityLpmM2": 5, "designAreaM2": 140, "hoseAllowanceLpm": 500},
    )
    assert res["problems"] == []
    assert res["summary"]["sprinklerDemandLpm"] == pytest.approx(700.0, rel=0.01)
    assert res["summary"]["combinedDemandLpm"] == pytest.approx(1200.0, rel=0.01)
    assert res["summary"]["combinedFlowLps"] == pytest.approx(20.0, rel=0.01)


def test_mep_fire_sprinkler_piping() -> None:
    res = features.run(
        "mepFire.sprinklerPiping",
        None,
        {
            "material": "steel",
            "jointType": "grooved",
            "corrosionAllowanceMm": 1.5,
            "designPressureKpa": 1400,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["material"] == "steel"
    assert res["summary"]["jointType"] == "grooved"
    assert res["summary"]["designPressureKpa"] == pytest.approx(1400.0, rel=0.01)


def test_mep_fire_storage_tank() -> None:
    # (30 - 5) L/s * 60 min * 60 s = 90,000 L = 90 m3 net; / 0.90 = 100 m3 gross.
    res = features.run(
        "mepFire.storageTank",
        None,
        {"designFlowLps": 30, "durationMinutes": 60, "usableFraction": 0.9, "replenishmentLps": 5},
    )
    assert res["problems"] == []
    assert res["summary"]["netFireVolumeM3"] == pytest.approx(90.0, rel=0.01)
    assert res["summary"]["grossTankVolumeM3"] == pytest.approx(100.0, rel=0.01)


def test_mep_fire_suction_tank() -> None:
    # 60 m3 = 60,000 L at net (25 - 5) = 20 L/s -> 3000 s = 50.0 min.
    res = features.run(
        "mepFire.suctionTank",
        None,
        {"tankVolumeM3": 60, "pumpFlowLps": 25, "replenishmentLps": 5, "minimumSubmergenceM": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["netDrawOffLps"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["availableDurationMinutes"] == pytest.approx(50.0, rel=0.01)


# ── MEP Fire Alarm Zoning (mep_fire_alarm_zoning.py: 19) ────────────────────────────────────────


def test_mep_fire_alarm_zoning_cable_length_limit() -> None:
    # 800 * 0.08 = 64.0 nF <= 100.0 nF -> pass.
    res = features.run(
        "mepFireAlarmZoning.cableLengthLimit",
        None,
        {"runLengthM": 800, "capacitanceNfPerM": 0.08, "maximumCapacitanceNf": 100},
    )
    assert res["problems"] == []
    assert res["summary"]["estimatedCapacitanceNf"] == pytest.approx(64.0, rel=0.01)
    assert res["summary"]["pass"] is True


def test_mep_fire_alarm_zoning_call_point() -> None:
    # ceil(70 / 30) = 3.
    res = features.run(
        "mepFireAlarmZoning.callPoint",
        None,
        {"escapeRouteLengthM": 70, "maximumTravelM": 30},
    )
    assert res["problems"] == []
    assert res["summary"]["callPointCount"] == 3


def test_mep_fire_alarm_zoning_cause_and_effect() -> None:
    res = features.run(
        "mepFireAlarmZoning.causeAndEffect",
        None,
        {
            "initiatingZone": "Z-02",
            "output": "Trip AHU",
            "actionMode": "deactivate",
            "delaySeconds": 5,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["initiatingZone"] == "Z-02"
    assert res["summary"]["actionMode"] == "deactivate"
    assert res["summary"]["delaySeconds"] == pytest.approx(5.0, rel=0.01)


def test_mep_fire_alarm_zoning_create_zone() -> None:
    # 25 / 500 = 0.05 /m2.
    res = features.run(
        "mepFireAlarmZoning.createZone",
        None,
        {"zoneId": "Z-03", "floorAreaM2": 500, "deviceCount": 25},
    )
    assert res["problems"] == []
    assert res["summary"]["deviceDensityPerM2"] == pytest.approx(0.05, rel=0.01)


def test_mep_fire_alarm_zoning_elevator_recall() -> None:
    res = features.run(
        "mepFireAlarmZoning.elevatorRecall",
        None,
        {"elevatorTag": "LIFT-02", "primaryFloor": "G", "alternateFloor": "B1", "recallTimeS": 45},
    )
    assert res["problems"] == []
    assert res["summary"]["targetRecallTimeS"] == pytest.approx(45.0, rel=0.01)


def test_mep_fire_alarm_zoning_intelligibility_index() -> None:
    # margin = 78 - 55 = 23 dB -> min(1, 20/20)*exp(-1.2/2) = exp(-0.6) = 0.5488.
    res = features.run(
        "mepFireAlarmZoning.intelligibilityIndex",
        None,
        {"speechLevelDb": 78, "noiseLevelDb": 55, "reverberationS": 1.2},
    )
    assert res["problems"] == []
    assert res["summary"]["speechNoiseMarginDb"] == pytest.approx(23.0, rel=0.01)
    assert res["summary"]["screeningIndex"] == pytest.approx(math.exp(-0.6), rel=0.01)


def test_mep_fire_alarm_zoning_interface_module() -> None:
    res = features.run(
        "mepFireAlarmZoning.interfaceModule",
        None,
        {"moduleTag": "IM-02", "interface": "control", "loadMa": 2.5},
    )
    assert res["problems"] == []
    assert res["summary"]["interfaceType"] == "control"
    assert res["summary"]["loopLoadMa"] == pytest.approx(2.5, rel=0.01)


def test_mep_fire_alarm_zoning_isolator_location() -> None:
    # ceil(55 / 20) = 3 isolators.
    res = features.run(
        "mepFireAlarmZoning.isolatorLocation",
        None,
        {"loopDeviceCount": 55, "devicesPerSection": 20},
    )
    assert res["problems"] == []
    assert res["summary"]["isolatorCount"] == 3


def test_mep_fire_alarm_zoning_logic_rules() -> None:
    res = features.run(
        "mepFireAlarmZoning.logicRules",
        None,
        {"inputA": 1, "inputB": 0, "operator": "OR"},
    )
    assert res["problems"] == []
    assert res["summary"]["output"] is True


def test_mep_fire_alarm_zoning_loop_load_calculation() -> None:
    # 40 * 0.4 = 16 mA standby, 40 * 5 = 200 mA alarm <= 500 mA.
    res = features.run(
        "mepFireAlarmZoning.loopLoadCalculation",
        None,
        {"deviceCount": 40, "standbyMa": 0.4, "alarmMa": 5, "loopCapacityMa": 500},
    )
    assert res["problems"] == []
    assert res["summary"]["standbyLoadMa"] == pytest.approx(16.0, rel=0.01)
    assert res["summary"]["alarmLoadMa"] == pytest.approx(200.0, rel=0.01)
    assert res["summary"]["alarmCapacityPass"] is True


def test_mep_fire_alarm_zoning_matrix_report() -> None:
    # 8 * 12 = 96 cells.
    res = features.run(
        "mepFireAlarmZoning.matrixReport",
        None,
        {"system": "Voice", "inputCount": 8, "outputCount": 12},
    )
    assert res["problems"] == []
    assert res["summary"]["matrixCellCount"] == 96


def test_mep_fire_alarm_zoning_place_detector() -> None:
    # 120 m2 / (pi * 5^2 = 78.54 m2) -> ceil = 2.
    res = features.run(
        "mepFireAlarmZoning.placeDetector",
        None,
        {"roomLengthM": 12, "roomWidthM": 10, "coverageDiameterM": 10, "type": "smoke"},
    )
    assert res["problems"] == []
    assert res["summary"]["detectorCountEstimate"] == 2


def test_mep_fire_alarm_zoning_place_sounder() -> None:
    # ceil(150 / 80) = 2 <= 2 installed -> pass.
    res = features.run(
        "mepFireAlarmZoning.placeSounder",
        None,
        {"roomAreaM2": 150, "coveragePerSounderM2": 80, "sounderCount": 2},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredCount"] == 2
    assert res["summary"]["quantityPass"] is True


def test_mep_fire_alarm_zoning_sound_level_mapping() -> None:
    # direct = 100 - 20*log10(10) = 80 dB; combined with 60 dB = 10*log10(10^8 + 10^6) = 80.043 dB.
    comb = 10 * math.log10(10**8 + 10**6)
    res = features.run(
        "mepFireAlarmZoning.soundLevelMapping",
        None,
        {"sourceDb": 100, "distanceM": 10, "backgroundDb": 60},
    )
    assert res["problems"] == []
    assert res["summary"]["directSoundLevelDb"] == pytest.approx(80.0, rel=0.01)
    assert res["summary"]["combinedSoundLevelDb"] == pytest.approx(comb, rel=0.01)


def test_mep_fire_alarm_zoning_strobe_coverage() -> None:
    # 250 m2 / (pi * 8^2 = 201.06 m2) -> ceil = 2.
    res = features.run(
        "mepFireAlarmZoning.strobeCoverage",
        None,
        {"roomLengthM": 25, "roomWidthM": 10, "coverageRadiusM": 8},
    )
    assert res["problems"] == []
    assert res["summary"]["roomAreaM2"] == pytest.approx(250.0, rel=0.01)
    assert res["summary"]["strobeCountEstimate"] == 2


def test_mep_fire_alarm_zoning_test_matrix() -> None:
    res = features.run(
        "mepFireAlarmZoning.testMatrix",
        None,
        {"initiatingInput": 1, "expectedOutput": 1, "simulatedOutput": 1},
    )
    assert res["problems"] == []
    assert res["summary"]["pass"] is True


def test_mep_fire_alarm_zoning_voltage_drop_loop() -> None:
    # 0.2 A * 2 * 250 m * 20 ohm/km / 1000 = 2.0 V -> end = 22.0 V, drop% = 2/24*100 = 8.333%.
    res = features.run(
        "mepFireAlarmZoning.voltageDropLoop",
        None,
        {"currentA": 0.2, "oneWayLengthM": 250, "resistanceOhmPerKm": 20, "supplyVoltageV": 24},
    )
    assert res["problems"] == []
    assert res["summary"]["voltageDropV"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["endVoltageV"] == pytest.approx(22.0, rel=0.01)
    assert res["summary"]["dropPercent"] == pytest.approx(8.333, rel=0.01)


def test_mep_fire_alarm_zoning_zone_address() -> None:
    # start 10 + 15 devices -> last = 24 <= 127.
    res = features.run(
        "mepFireAlarmZoning.zoneAddress",
        None,
        {"loopNumber": 1, "firstAddress": 10, "deviceCount": 15, "addressCapacity": 127},
    )
    assert res["problems"] == []
    assert res["summary"]["lastAddress"] == 24
    assert res["summary"]["capacityPass"] is True


def test_mep_fire_alarm_zoning_zone_boundary() -> None:
    # 40 * 25 = 1000 m2, perimeter = 130 m.
    res = features.run("mepFireAlarmZoning.zoneBoundary", None, {"lengthM": 40, "widthM": 25})
    assert res["problems"] == []
    assert res["summary"]["boundaryAreaM2"] == pytest.approx(1000.0, rel=0.01)
    assert res["summary"]["boundaryPerimeterM"] == pytest.approx(130.0, rel=0.01)


# ── MEP Fire Dampers (mep_fire_dampers.py: 3) ───────────────────────────────────────────────────


def test_mep_fire_dampers_access_clearance_check() -> None:
    # coverage = 450 / 600 = 0.75; front 600 >= 500; panel 450 >= min(450, 600).
    res = features.run(
        "mepFireDampers.accessClearanceCheck",
        None,
        {
            "ductWidthMm": 600.0,
            "accessPanelWidthMm": 450.0,
            "clearFrontMm": 600.0,
            "minClearanceMm": 500.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["widthCoverageRatio"] == pytest.approx(0.75, rel=0.01)
    assert res["summary"]["compliant"] is True


def test_mep_fire_dampers_rating_check() -> None:
    # 120 min wall -> 90 min damper required; 90 provided -> compliant.
    res = features.run(
        "mepFireDampers.ratingCheck",
        None,
        {"barrierRatingMin": 120.0, "damperRatingMin": 90.0, "staticPressurePa": 350.0},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredDamperMin"] == pytest.approx(90.0, rel=0.01)
    assert res["summary"]["compliant"] is True


def test_mep_fire_dampers_seal_check() -> None:
    # 0.50 m2 * 18.0 L/(s*m2) = 9.0 L/s; 18.0 <= 20.3 -> ok.
    res = features.run(
        "mepFireDampers.sealCheck",
        None,
        {
            "damperAreaM2": 0.50,
            "testPressurePa": 1000.0,
            "leakageRateLpsPerM2": 18.0,
            "maxClassLimitLpsPerM2": 20.3,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["totalLeakageLps"] == pytest.approx(9.0, rel=0.01)
    assert res["summary"]["leakageClassOk"] is True


# ── MEP Fire Extinguishers (mep_fire_extinguishers.py: 3) ─────────────────────────────────────────


def test_mep_fire_extinguishers_dead_end_check() -> None:
    res = features.run(
        "mepFireExtinguishers.deadEndCheck",
        None,
        {"deadEndLengthM": 5.5, "limitLengthM": 6.0, "travelToExtinguisherM": 18.0},
    )
    assert res["problems"] == []
    assert res["summary"]["deadEndOk"] is True
    assert res["summary"]["travelOk"] is True
    assert res["summary"]["compliant"] is True


def test_mep_fire_extinguishers_expiry_check() -> None:
    curr = date.today().year
    base = curr - 2
    res = features.run(
        "mepFireExtinguishers.expiryCheck",
        None,
        {"manufactureYear": str(base), "hydroIntervalYr": 5.0, "annualCheckMonths": 12.0},
    )
    assert res["problems"] == []
    assert res["summary"]["nextHydroTestYear"] == base + 5
    assert res["summary"]["yearsRemaining"] == 3
    assert res["summary"]["status"] == "Valid"


def test_mep_fire_extinguishers_flammable_storage_check() -> None:
    # area = 300 m2, r_max = 9.0 m (<= 9.1 -> 40-B required);
    # cov = min(300, 0.75 * pi * 81 = 190.85) -> ceil(300 / 190.85) = 2 units.
    res = features.run(
        "mepFireExtinguishers.flammableStorageCheck",
        None,
        {"storageAreaM2": 300.0, "maxTravelLimitM": 9.0, "unitBRating": 40.0},
    )
    assert res["problems"] == []
    assert res["summary"]["recommendedUnits"] == 2
    assert res["summary"]["minimumUnitRatingB"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["ratingOk"] is True


# ── MEP Smoke Control (mep_smoke_control.py: 7) ─────────────────────────────────────────────────


def test_mep_smoke_air_balance_smoke() -> None:
    # v_crack = 0.65 * sqrt(2*50/1.2) = 5.9336 m/s; q_closed = 10 * 0.02 * 5.9336 = 1.1867 m3/s;
    # q_open = 1 * 1.8 * 1.0 = 1.80 m3/s; total (+15%) = (1.1867 + 1.80) * 1.15 = 3.4347 m3/s.
    q_c = 10 * 0.02 * 0.65 * math.sqrt(2 * 50 / 1.2)
    q_o = 1.8
    q_t = (q_c + q_o) * 1.15
    res = features.run(
        "mepSmoke.airBalanceSmoke",
        None,
        {
            "pressurisedFloorCount": 10,
            "closedDoorGapAreaM2": 0.02,
            "openDoorsCount": 1,
            "openDoorAreaM2": 1.8,
            "targetPressurePa": 50.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["closedDoorLeakageM3s"] == pytest.approx(q_c, rel=0.01)
    assert res["summary"]["openDoorAirflowM3s"] == pytest.approx(q_o, rel=0.01)
    assert res["summary"]["totalFanSupplyM3s"] == pytest.approx(q_t, rel=0.01)


def test_mep_smoke_door_force_check() -> None:
    # A = 0.9 * 2.1 = 1.89 m2, d_latch = 0.075 m -> F_air = (50 * 1.89 * 0.9) / (2 * (0.9 - 0.075))
    # = 85.05 / 1.65 = 51.545 N; F_total = 45 + 51.545 = 96.545 N <= 133 N.
    f_air = (50 * 0.9 * 2.1 * 0.9) / (2 * (0.9 - 0.075))
    res = features.run(
        "mepSmoke.doorForceCheck",
        None,
        {
            "doorWidthM": 0.9,
            "doorHeightM": 2.1,
            "closerForceN": 45.0,
            "pressureDiffPa": 50.0,
            "maxAllowedForceN": 133.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["airPressureForceN"] == pytest.approx(f_air, rel=0.01)
    assert res["summary"]["totalOpeningForceN"] == pytest.approx(45.0 + f_air, rel=0.01)
    assert res["summary"]["compliant"] is True


def test_mep_smoke_egress_width_check() -> None:
    # max(1100, 200 * 7.6) = 1520 mm > 1500 mm -> fails; cap = int(1500 / 7.6) = 197.
    res = features.run(
        "mepSmoke.egressWidthCheck",
        None,
        {"occupantLoad": 200, "widthPerPersonMm": 7.6, "providedClearMm": 1500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredClearWidthMm"] == pytest.approx(1520.0, rel=0.01)
    assert res["summary"]["egressCapacityPersons"] == 197
    assert res["summary"]["compliant"] is False


def test_mep_smoke_extraction_rate() -> None:
    # Heskestad: m_p = 0.071 * 3500^(1/3) * 6^(5/3) + 0.0018 * 3500 = 21.39 + 6.30 = 27.69 kg/s;
    # rho_s = 1.2 * 293.15 / 358.15 = 0.9822 kg/m3 -> V = 27.69 / 0.9822 = 28.19 m3/s.
    m_p = 0.071 * (3500 ** (1 / 3)) * (6 ** (5 / 3)) + 0.0018 * 3500
    rho_s = 1.2 * 293.15 / (85 + 273.15)
    res = features.run(
        "mepSmoke.extractionRate",
        None,
        {"heatReleaseKw": 3500.0, "clearHeightM": 6.0, "smokeTempC": 85.0},
    )
    assert res["problems"] == []
    assert res["summary"]["plumeMassRateKgPerS"] == pytest.approx(m_p, rel=0.01)
    assert res["summary"]["smokeDensityKgPerM3"] == pytest.approx(rho_s, rel=0.01)
    assert res["summary"]["extractionRateM3s"] == pytest.approx(m_p / rho_s, rel=0.01)


def test_mep_smoke_smoke_reservoirs() -> None:
    # 2000 * 1.8 = 3600 m3; <= 2600 m2 and <= 60 m -> 1 zone.
    res = features.run(
        "mepSmoke.smokeReservoirs",
        None,
        {"zoneAreaM2": 2000.0, "maxSideM": 50.0, "layerDepthM": 1.8},
    )
    assert res["problems"] == []
    assert res["summary"]["reservoirVolumeM3"] == pytest.approx(3600.0, rel=0.01)
    assert res["summary"]["recommendedSubZones"] == 1
    assert res["summary"]["areaOk"] is True
    assert res["summary"]["lengthOk"] is True


def test_mep_smoke_smoke_vents() -> None:
    # t_0 = 298.15, t_s = 363.15, dT = 65 K, rho_0 = 1.2*293.15/298.15 = 1.1799;
    # Aa = 18 / (rho_0 * sqrt(2*9.81*1.6*65*298.15 / 363.15^2)) = 7.09 m2; Ag = Aa / 0.6 = 11.81 m2.
    t0, ts = 298.15, 363.15
    rho0 = 1.2 * 293.15 / t0
    aa = 18.0 / (rho0 * math.sqrt(2 * 9.81 * 1.6 * 65 * t0 / (ts**2)))
    res = features.run(
        "mepSmoke.smokeVents",
        None,
        {
            "plumeMassKgPerS": 18.0,
            "smokeLayerDepthM": 1.6,
            "smokeTempC": 90.0,
            "ambientTempC": 25.0,
            "dischargeCoeff": 0.6,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["aerodynamicAreaM2"] == pytest.approx(aa, rel=0.01)
    assert res["summary"]["geometricVentAreaM2"] == pytest.approx(aa / 0.6, rel=0.01)


def test_mep_smoke_tenability() -> None:
    # Jin's law S = 3.0 / 0.20 = 15.0 m >= 10 m; temp 45 <= 60; rad 1.5 <= 2.5 -> tenable.
    res = features.run(
        "mepSmoke.tenability",
        None,
        {"opticalDensityPerM": 0.20, "airTempC": 45.0, "radiationKwPerM2": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["visibilityM"] == pytest.approx(15.0, rel=0.01)
    assert res["summary"]["tenable"] is True


# ── MEP Sprinkler (mep_sprinkler.py: 22) ────────────────────────────────────────────────────────


def test_mep_sprinkler_as_built_sprinkler() -> None:
    # offset (0.03, 0.04) m -> hypot = 0.05 m = 50.0 mm <= 50 mm tolerance.
    res = features.run(
        "mepSprinkler.asBuiltSprinkler",
        None,
        {"designXM": 0, "designYM": 0, "installedXM": 0.03, "installedYM": 0.04, "toleranceMm": 50},
    )
    assert res["problems"] == []
    assert res["summary"]["deviationMm"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["withinTolerance"] is True


def test_mep_sprinkler_balancing_valve_set() -> None:
    # Q = 5.0 L/s = 18.0 m3/h, Kv = 10 -> dP [bar] = 1.8^2 = 3.24 bar = 324.0 kPa;
    # error = (5.0 - 5.0) -> let's test 4.5 vs 5.0 -> -10%, Q=16.2 -> dP = 1.62^2 * 100 = 262.44 kPa.
    res = features.run(
        "mepSprinkler.balancingValveSet",
        None,
        {"designFlowLs": 5.0, "measuredFlowLs": 4.5, "valveCv": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["flowErrorPercent"] == pytest.approx(-10.0, rel=0.01)
    assert res["summary"]["estimatedValveDropKpa"] == pytest.approx(262.44, rel=0.01)


def test_mep_sprinkler_branch_lines() -> None:
    # 24 / 4 = 6 branches, 24 / 3 = 8 heads -> 48 heads.
    res = features.run(
        "mepSprinkler.branchLines",
        None,
        {"roomLengthM": 24, "branchSpacingM": 4, "headSpacingM": 3},
    )
    assert res["problems"] == []
    assert res["summary"]["branchCount"] == 6
    assert res["summary"]["headsPerBranch"] == 8
    assert res["summary"]["estimatedHeadCount"] == 48


def test_mep_sprinkler_coverage_check() -> None:
    # 3.5 * 3.0 = 10.5 m2 <= 12.0 m2 -> pass.
    res = features.run(
        "mepSprinkler.coverageCheck",
        None,
        {"spacingXM": 3.5, "spacingYM": 3.0, "maxCoverageM2": 12.0},
    )
    assert res["problems"] == []
    assert res["summary"]["coverageM2"] == pytest.approx(10.5, rel=0.01)
    assert res["summary"]["pass"] is True


def test_mep_sprinkler_cross_main_layout() -> None:
    # ceil(30 / 12) = 3 * 40 = 120 m.
    res = features.run(
        "mepSprinkler.crossMainLayout",
        None,
        {"buildingWidthM": 30, "mainSpacingM": 12, "mainLengthM": 40},
    )
    assert res["problems"] == []
    assert res["summary"]["crossMainCount"] == 3
    assert res["summary"]["totalLengthM"] == pytest.approx(120.0, rel=0.01)


def test_mep_sprinkler_demand_point() -> None:
    # 20 L/s * 350 kPa / 1000 = 7.0 kW.
    res = features.run(
        "mepSprinkler.demandPoint",
        None,
        {"flowLs": 20, "pressureKpa": 350},
    )
    assert res["problems"] == []
    assert res["summary"]["hydraulicPowerKw"] == pytest.approx(7.0, rel=0.01)


def test_mep_sprinkler_design_density_check() -> None:
    # 15 L/s * 60 / 150 m2 = 6.0 mm/min >= 5.0 -> pass.
    res = features.run(
        "mepSprinkler.designDensityCheck",
        None,
        {"deliveredFlowLs": 15, "remoteAreaM2": 150, "designDensityMmMin": 5},
    )
    assert res["problems"] == []
    assert res["summary"]["deliveredDensityMmPerMin"] == pytest.approx(6.0, rel=0.01)
    assert res["summary"]["pass"] is True


def test_mep_sprinkler_drop_nipples() -> None:
    # 40 * (300 + 25) mm / 1000 = 13.0 m.
    res = features.run(
        "mepSprinkler.dropNipples",
        None,
        {"headCount": 40, "dropLengthMm": 300, "allowanceMm": 25},
    )
    assert res["problems"] == []
    assert res["summary"]["totalLengthM"] == pytest.approx(13.0, rel=0.01)


def test_mep_sprinkler_flow_test() -> None:
    # 600 - 450 = 150 kPa drop.
    res = features.run(
        "mepSprinkler.flowTest",
        None,
        {"staticKpa": 600, "residualKpa": 450, "flowLs": 25},
    )
    assert res["problems"] == []
    assert res["summary"]["pressureDropKpa"] == pytest.approx(150.0, rel=0.01)


def test_mep_sprinkler_hazard_class() -> None:
    res = features.run(
        "mepSprinkler.hazardClass",
        None,
        {"room": "Archive", "hazard": "ordinary", "areaM2": 200},
    )
    assert res["problems"] == []
    assert res["summary"]["hazard"] == "ordinary"
    assert res["summary"]["areaM2"] == pytest.approx(200.0, rel=0.01)


def test_mep_sprinkler_head_spacing() -> None:
    res = features.run(
        "mepSprinkler.headSpacing",
        None,
        {"spacingXM": 3.5, "spacingYM": 4.0, "limitM": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["spacingXPass"] is True
    assert res["summary"]["spacingYPass"] is True
    assert res["summary"]["coverageM2"] == pytest.approx(14.0, rel=0.01)


def test_mep_sprinkler_hydraulic_report(tmp_path: Path) -> None:
    # Registry has requires_project=False, but implementation checks ctx.root and writes report file.
    missing = features.run(
        "mepSprinkler.hydraulicReport",
        None,
        {"flowLs": 20, "pressureKpa": 450, "systemTag": "SP-01"},
    )
    assert missing["problems"] == ["Choose a project to save the hydraulic report."]

    res = features.run(
        "mepSprinkler.hydraulicReport",
        str(tmp_path),
        {"flowLs": 22.5, "pressureKpa": 420.0, "systemTag": "SP-02"},
    )
    assert res["problems"] == []
    assert res["summary"]["flowLs"] == pytest.approx(22.5, rel=0.01)
    assert res["summary"]["pressureKpa"] == pytest.approx(420.0, rel=0.01)
    assert Path(res["summary"]["reportPath"]).is_file()


def test_mep_sprinkler_jockey_pump_set() -> None:
    # 8 m3 * 50 kPa / (1000 * 9.80665) / 600 s * 1000 = 0.06798 L/s.
    exp = 8 * 50 / (1000 * 9.80665) / (10 * 60) * 1000
    res = features.run(
        "mepSprinkler.jockeyPumpSet",
        None,
        {"systemVolumeM3": 8, "allowableDropKpa": 50, "recoveryMin": 10},
    )
    assert res["problems"] == []
    assert res["summary"]["estimatedMakeupFlowLs"] == pytest.approx(exp, rel=0.01)


def test_mep_sprinkler_pipe_sizing() -> None:
    # 12 L/s = 0.012 m3/s at 3 m/s -> A = 0.004 m2 -> d = sqrt(0.016/pi)*1000 = 71.365 mm.
    exp_d = math.sqrt(4 * 0.012 / (math.pi * 3)) * 1000
    res = features.run("mepSprinkler.pipeSizing", None, {"flowLs": 12, "velocityMs": 3})
    assert res["problems"] == []
    assert res["summary"]["minimumInternalDiameterMm"] == pytest.approx(exp_d, rel=0.01)


def test_mep_sprinkler_pressure_loss() -> None:
    # d=0.10 m, Q=0.015 m3/s -> v = 0.015 / (pi*0.01/4) = 1.90986 m/s;
    # Darcy h_f = 0.02 * (80/0.1) * v^2 / (2*9.80665) = 16 * 3.6476 / 19.6133 = 2.9756 m -> 29.18 kPa.
    v = 0.015 / (math.pi * 0.1**2 / 4)
    hf = 0.02 * (80 / 0.1) * (v**2) / (2 * 9.80665)
    res = features.run(
        "mepSprinkler.pressureLoss",
        None,
        {"lengthM": 80, "flowLs": 15, "diameterMm": 100, "frictionFactor": 0.02},
    )
    assert res["problems"] == []
    assert res["summary"]["velocityMs"] == pytest.approx(v, rel=0.01)
    assert res["summary"]["lossHeadM"] == pytest.approx(hf, rel=0.01)
    assert res["summary"]["pressureLossKpa"] == pytest.approx(hf * 9.80665, rel=0.01)


def test_mep_sprinkler_pump_duty_point() -> None:
    # H = 20 + 15 + 300/9.80665 = 65.591 m; P_hyd = 25 * 9.80665 * 65.591 / 1000 = 16.081 kW.
    h = 20 + 15 + 300 / 9.80665
    res = features.run(
        "mepSprinkler.pumpDutyPoint",
        None,
        {"flowLs": 25, "staticHeadM": 20, "frictionHeadM": 15, "residualPressureKpa": 300},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredHeadM"] == pytest.approx(h, rel=0.01)
    assert res["summary"]["hydraulicPowerKw"] == pytest.approx(25 * 9.80665 * h / 1000, rel=0.01)


def test_mep_sprinkler_remote_area() -> None:
    # 6 mm/min * 150 m2 / 60 = 15.0 L/s.
    res = features.run("mepSprinkler.remoteArea", None, {"densityMmPerMin": 6, "areaM2": 150})
    assert res["problems"] == []
    assert res["summary"]["requiredFlowLs"] == pytest.approx(15.0, rel=0.01)


def test_mep_sprinkler_spare_heads() -> None:
    # ceil(350 * 0.02) = 7.
    res = features.run(
        "mepSprinkler.spareHeads",
        None,
        {"installedCount": 350, "spareFraction": 0.02},
    )
    assert res["problems"] == []
    assert res["summary"]["spareHeadCount"] == 7


def test_mep_sprinkler_sprinkler_layout() -> None:
    # area=225 -> side=15 m; 4x3 m spacing -> ceil(15/4)=4, ceil(15/3)=5 -> 20 heads, 12 m2/head.
    res = features.run(
        "mepSprinkler.sprinklerLayout",
        None,
        {"areaM2": 225, "spacingXM": 4, "spacingYM": 3},
    )
    assert res["problems"] == []
    assert res["summary"]["gridX"] == 4
    assert res["summary"]["gridY"] == 5
    assert res["summary"]["estimatedHeadCount"] == 20
    assert res["summary"]["coveragePerHeadM2"] == pytest.approx(12.0, rel=0.01)


def test_mep_sprinkler_suction_layout() -> None:
    # 30 L/s = 0.03 m3/s at 1.5 m/s -> A = 0.02 m2 -> d = sqrt(0.08/pi)*1000 = 159.58 mm.
    exp_d = math.sqrt(4 * 0.03 / (math.pi * 1.5)) * 1000
    res = features.run("mepSprinkler.suctionLayout", None, {"flowLs": 30, "velocityMs": 1.5})
    assert res["problems"] == []
    assert res["summary"]["minimumInternalDiameterMm"] == pytest.approx(exp_d, rel=0.01)


def test_mep_sprinkler_supply_curve() -> None:
    # Pstatic=600, Pres=500 -> dP = 100, Q = 25 -> K = 25 / sqrt(100) = 2.50.
    res = features.run(
        "mepSprinkler.supplyCurve",
        None,
        {"staticKpa": 600, "flowLs": 25, "residualKpa": 500},
    )
    assert res["problems"] == []
    assert res["summary"]["curveCoefficient"] == pytest.approx(2.5, rel=0.01)


def test_mep_sprinkler_tank_capacity() -> None:
    # 25 L/s * 60 min * 60 / 1000 = 90.0 m3.
    res = features.run("mepSprinkler.tankCapacity", None, {"flowLs": 25, "durationMin": 60})
    assert res["problems"] == []
    assert res["summary"]["usableVolumeM3"] == pytest.approx(90.0, rel=0.01)

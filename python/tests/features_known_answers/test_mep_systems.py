"""Independent known-answer tests for standalone calculators in MEP Equipment, Maintenance, Balancing, Zoning, and Systems."""

from __future__ import annotations

import math

import pytest

from saengine import features

# ── MEP Equipment (mep_equipment.py: 22) ────────────────────────────────────────────────────────


def test_mep_equipment_ahu_placement() -> None:
    # A_face = Q / V_face = 3.0 m3/s / 2.5 m/s = 1.2 m2.
    res = features.run(
        "mepEquipment.ahuPlacement",
        None,
        {"flowM3s": 3.0, "faceVelocityMs": 2.5},
    )
    assert res["problems"] == []
    assert res["summary"]["faceAreaM2"] == pytest.approx(1.2, rel=0.01)


def test_mep_equipment_boilers() -> None:
    # Q_fuel = Q_out / eta = 180 / 0.90 = 200.0 kW; flue/jacket loss = 200 - 180 = 20.0 kW.
    res = features.run(
        "mepEquipment.boilers",
        None,
        {"outputKw": 180.0, "efficiency": 0.9},
    )
    assert res["problems"] == []
    assert res["summary"]["fuelInputKw"] == pytest.approx(200.0, rel=0.01)
    assert res["summary"]["lossKw"] == pytest.approx(20.0, rel=0.01)


def test_mep_equipment_chillers() -> None:
    # P_in = Q_evap / COP = 400 / 5.0 = 80.0 kW; Q_cond = Q_evap + P_in = 480.0 kW.
    res = features.run(
        "mepEquipment.chillers",
        None,
        {"loadKw": 400.0, "cop": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["inputPowerKw"] == pytest.approx(80.0, rel=0.01)
    assert res["summary"]["heatRejectionKw"] == pytest.approx(480.0, rel=0.01)


def test_mep_equipment_condensate_drain() -> None:
    # m_dot = 40 kW * 1.8 kg/kWh = 72 kg/h -> 72 / 3600 = 0.02 L/s (density 1 kg/L).
    # Over 10 h: volume = 72 * 10 = 720.0 L.
    res = features.run(
        "mepEquipment.condensateDrain",
        None,
        {"coolingKw": 40.0, "condensateRateKgPerKwh": 1.8, "operatingHours": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["condensateLPerS"] == pytest.approx(0.02, rel=0.01)
    assert res["summary"]["volumeL"] == pytest.approx(720.0, rel=0.01)


def test_mep_equipment_cooling_load_match() -> None:
    # ceil(620 / 200) = 4 units -> installed = 800 kW, margin = 800 - 620 = 180 kW.
    res = features.run(
        "mepEquipment.coolingLoadMatch",
        None,
        {"blockLoadKw": 620.0, "unitCapacityKw": 200.0},
    )
    assert res["problems"] == []
    assert res["summary"]["unitCount"] == 4
    assert res["summary"]["installedCapacityKw"] == pytest.approx(800.0, rel=0.01)
    assert res["summary"]["capacityMarginKw"] == pytest.approx(180.0, rel=0.01)


def test_mep_equipment_cooling_towers() -> None:
    # Q = m_dot * c_p * dT -> m_dot = 502.32 / (4.186 * 6.0) = 20.0 kg/s = 20.0 L/s.
    res = features.run(
        "mepEquipment.coolingTowers",
        None,
        {"heatKw": 502.32, "rangeC": 6.0},
    )
    assert res["problems"] == []
    assert res["summary"]["waterFlowLs"] == pytest.approx(20.0, rel=0.01)


def test_mep_equipment_duct_connections() -> None:
    # A = 2.0 / 8.0 = 0.25 m2; D = sqrt(4 * 0.25 / pi) * 1000 = 564.19 mm.
    expected_d = math.sqrt(4.0 * 0.25 / math.pi) * 1000.0
    res = features.run(
        "mepEquipment.ductConnections",
        None,
        {"flowM3s": 2.0, "velocityMs": 8.0},
    )
    assert res["problems"] == []
    assert res["summary"]["areaM2"] == pytest.approx(0.25, rel=0.01)
    assert res["summary"]["diameterMm"] == pytest.approx(expected_d, rel=0.01)


def test_mep_equipment_electrical_connections() -> None:
    # 3-phase balanced: I = P / (sqrt(3) * V * PF) = 36000 / (sqrt(3) * 400 * 0.9) = 57.735 A.
    expected_i = 36000.0 / (math.sqrt(3.0) * 400.0 * 0.9)
    res = features.run(
        "mepEquipment.electricalConnections",
        None,
        {"powerKw": 36.0, "voltageV": 400.0, "powerFactor": 0.9},
    )
    assert res["problems"] == []
    assert res["summary"]["lineCurrentA"] == pytest.approx(expected_i, rel=0.01)


def test_mep_equipment_energy_label() -> None:
    # Relative efficiency = 4.5 / 3.0 = 1.5.
    res = features.run(
        "mepEquipment.energyLabel",
        None,
        {"cop": 4.5, "referenceCop": 3.0},
    )
    assert res["problems"] == []
    assert res["summary"]["relativeEfficiency"] == pytest.approx(1.5, rel=0.01)


def test_mep_equipment_energy_rating() -> None:
    # Performance ratio = 42.0 / 12.0 = 3.5.
    res = features.run(
        "mepEquipment.energyRating",
        None,
        {"inputKw": 12.0, "outputKw": 42.0},
    )
    assert res["problems"] == []
    assert res["summary"]["performanceRatio"] == pytest.approx(3.5, rel=0.01)


def test_mep_equipment_equipment_curves() -> None:
    res = features.run(
        "mepEquipment.equipmentCurves",
        None,
        {"flowA": 25.0, "headA": 32.0, "flowB": 28.0, "headB": 29.0},
    )
    assert res["problems"] == []
    assert res["summary"]["candidateAFlowM3h"] == pytest.approx(25.0, rel=0.01)
    assert res["summary"]["candidateAHeadM"] == pytest.approx(32.0, rel=0.01)
    assert res["summary"]["candidateBFlowM3h"] == pytest.approx(28.0, rel=0.01)
    assert res["summary"]["candidateBHeadM"] == pytest.approx(29.0, rel=0.01)


def test_mep_equipment_equipment_data_sheet() -> None:
    res = features.run(
        "mepEquipment.equipmentDataSheet",
        None,
        {"tag": "CH-02", "type": "Chiller", "dutyKw": 320.0, "inputKw": 64.0},
    )
    assert res["problems"] == []
    assert res["summary"]["tag"] == "CH-02"
    assert res["summary"]["dutyKw"] == pytest.approx(320.0, rel=0.01)
    assert res["summary"]["inputKw"] == pytest.approx(64.0, rel=0.01)
    assert len(res["tables"][0]["rows"]) == 4


def test_mep_equipment_equipment_tags() -> None:
    # 4 tags starting at 10 with prefix "FCU" -> FCU-10, FCU-11, FCU-12, FCU-13.
    res = features.run(
        "mepEquipment.equipmentTags",
        None,
        {"prefix": "FCU", "firstNumber": 10, "itemCount": 4},
    )
    assert res["problems"] == []
    assert res["summary"]["tagCount"] == 4
    tags = [row["tag"] for row in res["tables"][0]["rows"]]
    assert tags == ["FCU-10", "FCU-11", "FCU-12", "FCU-13"]


def test_mep_equipment_maintenance_access() -> None:
    # 750 mm < 900 mm required -> pass is False.
    res = features.run(
        "mepEquipment.maintenanceAccess",
        None,
        {"routeWidthMm": 750.0, "minimumWidthMm": 900.0},
    )
    assert res["problems"] == []
    assert res["summary"]["pass"] is False


def test_mep_equipment_noise_rating() -> None:
    # 84 dB > 72 dB limit -> exceedsLimit True, margin = 72 - 84 = -12 dB.
    res = features.run(
        "mepEquipment.noiseRating",
        None,
        {"soundPowerDb": 84.0, "roomLimitDb": 72.0},
    )
    assert res["problems"] == []
    assert res["summary"]["exceedsLimit"] is True
    assert res["summary"]["marginDb"] == pytest.approx(-12.0, rel=0.01)


def test_mep_equipment_pipe_connections() -> None:
    # Q = 12 L/s = 0.012 m3/s, V = 1.5 m/s -> A = 0.008 m2, D = sqrt(4*0.008/pi)*1000 = 100.925 mm.
    expected_d = math.sqrt(4.0 * 0.012 / (math.pi * 1.5)) * 1000.0
    res = features.run(
        "mepEquipment.pipeConnections",
        None,
        {"flowLs": 12.0, "velocityMs": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["internalDiameterMm"] == pytest.approx(expected_d, rel=0.01)


def test_mep_equipment_plant_clearances() -> None:
    # Required width = 1500 + 2 * 500 = 2500 mm; service depth = 1200 mm.
    res = features.run(
        "mepEquipment.plantClearances",
        None,
        {"equipmentWidthMm": 1500.0, "sideClearanceMm": 500.0, "frontClearanceMm": 1200.0},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredWidthMm"] == pytest.approx(2500.0, rel=0.01)
    assert res["summary"]["serviceDepthMm"] == pytest.approx(1200.0, rel=0.01)


def test_mep_equipment_plantroom_layout() -> None:
    # Room = 15 * 10 = 150 m2; equipment = 60 m2 -> clear = 90 m2, footprint ratio = 60/150 = 0.40.
    res = features.run(
        "mepEquipment.plantroomLayout",
        None,
        {"lengthM": 15.0, "widthM": 10.0, "plantAreaM2": 60.0},
    )
    assert res["problems"] == []
    assert res["summary"]["roomAreaM2"] == pytest.approx(150.0, rel=0.01)
    assert res["summary"]["clearAreaM2"] == pytest.approx(90.0, rel=0.01)
    assert res["summary"]["footprintRatio"] == pytest.approx(0.4, rel=0.01)


def test_mep_equipment_pump_selection() -> None:
    # Q = 36 m3/h = 0.01 m3/s, H = 20 m -> P_hyd = 1000 * 9.80665 * 0.01 * 20 / 1000 = 1.96133 kW.
    # eta = 0.75 -> P_shaft = 1.96133 / 0.75 = 2.6151 kW.
    p_hyd = 1000.0 * 9.80665 * (36.0 / 3600.0) * 20.0 / 1000.0
    res = features.run(
        "mepEquipment.pumpSelection",
        None,
        {"flowM3h": 36.0, "headM": 20.0, "efficiency": 0.75},
    )
    assert res["problems"] == []
    assert res["summary"]["hydraulicPowerKw"] == pytest.approx(p_hyd, rel=0.01)
    assert res["summary"]["shaftPowerKw"] == pytest.approx(p_hyd / 0.75, rel=0.01)


def test_mep_equipment_redundancy_setup() -> None:
    # 3 duty + 1 standby = 4 installed units; duty = 3 * 150 = 450 kW, installed = 4 * 150 = 600 kW.
    res = features.run(
        "mepEquipment.redundancySetup",
        None,
        {"dutyUnits": 3, "unitCapacityKw": 150.0, "arrangement": "n-plus-one"},
    )
    assert res["problems"] == []
    assert res["summary"]["installedUnits"] == 4
    assert res["summary"]["dutyCapacityKw"] == pytest.approx(450.0, rel=0.01)
    assert res["summary"]["installedCapacityKw"] == pytest.approx(600.0, rel=0.01)


def test_mep_equipment_standby_units() -> None:
    # 3 duty + 2 standby = 5 total units, rotation = 240 h.
    res = features.run(
        "mepEquipment.standbyUnits",
        None,
        {"dutyCount": 3, "standbyCount": 2, "changeoverHours": 240.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalUnits"] == 5
    assert res["summary"]["dutyUnits"] == 3
    assert res["summary"]["standbyUnits"] == 2
    assert res["summary"]["changeoverHours"] == pytest.approx(240.0, rel=0.01)


def test_mep_equipment_vibration_isolation() -> None:
    # f_exc = 1800 / 60 = 30.0 Hz; f_nat = 5.0 Hz -> frequencyRatio = 30.0 / 5.0 = 6.0.
    res = features.run(
        "mepEquipment.vibrationIsolation",
        None,
        {"speedRpm": 1800.0, "naturalFrequencyHz": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["excitationFrequencyHz"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["frequencyRatio"] == pytest.approx(6.0, rel=0.01)


# ── MEP Systems Maintenance (mep_systems_maintenance.py: 12) ────────────────────────────────────


def test_mep_systems_maintenance_asset_deprecation() -> None:
    # Age 6 of 24 years -> remaining = 18 yr, lifeConsumed = 25%, depreciated = 20000 * 0.75 = 15000.
    res = features.run(
        "mepSystemsMaintenance.assetDeprecation",
        None,
        {"installedYears": 6.0, "usefulLifeYears": 24.0, "replacementCost": 20000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["remainingLifeYears"] == pytest.approx(18.0, rel=0.01)
    assert res["summary"]["depreciatedValue"] == pytest.approx(15000.0, rel=0.01)
    assert res["summary"]["lifeConsumedPercent"] == pytest.approx(25.0, rel=0.01)


def test_mep_systems_maintenance_failure_mode() -> None:
    # FMEA RPN = S * O * D = 7 * 4 * 5 = 140.
    res = features.run(
        "mepSystemsMaintenance.failureMode",
        None,
        {"failureMode": "Shaft seal leak", "severity": 7, "occurrence": 4, "detectability": 5},
    )
    assert res["problems"] == []
    assert res["summary"]["riskPriorityNumber"] == 140


def test_mep_systems_maintenance_meter_reading() -> None:
    # 2450 - 2000 = 450 kWh over 15 days -> 450 / 15 = 30.0 kWh/day.
    res = features.run(
        "mepSystemsMaintenance.meterReading",
        None,
        {"previous": 2000.0, "current": 2450.0, "periodDays": 15.0},
    )
    assert res["problems"] == []
    assert res["summary"]["consumptionKwh"] == pytest.approx(450.0, rel=0.01)
    assert res["summary"]["averageDailyKwh"] == pytest.approx(30.0, rel=0.01)


def test_mep_systems_maintenance_oil_analysis() -> None:
    # water 650 > 500 -> True; viscosity 50.6 vs 46.0 -> (50.6 - 46) / 46 * 100 = +10.0%.
    res = features.run(
        "mepSystemsMaintenance.oilAnalysis",
        None,
        {
            "waterPpm": 650.0,
            "limitPpm": 500.0,
            "viscosityMeasured": 50.6,
            "viscosityNominal": 46.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["waterLimitExceeded"] is True
    assert res["summary"]["viscosityDeviationPercent"] == pytest.approx(10.0, rel=0.01)


def test_mep_systems_maintenance_reorder_point() -> None:
    # Lead-time demand = 0.5 * 20 = 10 items; reorder point = 10 + 4 = 14 items.
    res = features.run(
        "mepSystemsMaintenance.reorderPoint",
        None,
        {"dailyUse": 0.5, "leadTime": 20.0, "safetyStock": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["leadTimeDemandItems"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["reorderPointItems"] == pytest.approx(14.0, rel=0.01)


def test_mep_systems_maintenance_replacement_plan() -> None:
    # Remaining = 20 - 15 = 5 yr; projected cost = 40000 * (1.04)^5 = 48666.116.
    expected_cost = 40000.0 * (1.04**5)
    res = features.run(
        "mepSystemsMaintenance.replacementPlan",
        None,
        {
            "currentAge": 15.0,
            "life": 20.0,
            "replacementCost": 40000.0,
            "annualEscalation": 0.04,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["yearsToReplacement"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["projectedCost"] == pytest.approx(expected_cost, rel=0.01)


def test_mep_systems_maintenance_run_hours() -> None:
    # 3150 - 2500 = 650 h.
    res = features.run(
        "mepSystemsMaintenance.runHours",
        None,
        {"previousHours": 2500.0, "currentHours": 3150.0},
    )
    assert res["problems"] == []
    assert res["summary"]["currentRunHours"] == pytest.approx(3150.0, rel=0.01)
    assert res["summary"]["periodRunHours"] == pytest.approx(650.0, rel=0.01)


def test_mep_systems_maintenance_service_interval() -> None:
    # 4 years = 48 months; interval = 3 months -> 48 // 3 = 16 planned services.
    res = features.run(
        "mepSystemsMaintenance.serviceInterval",
        None,
        {"intervalMonths": 3, "planningHorizonYears": 4},
    )
    assert res["problems"] == []
    assert res["summary"]["plannedServices"] == 16
    assert res["summary"]["planningHorizonMonths"] == 48


def test_mep_systems_maintenance_spare_part() -> None:
    res = features.run(
        "mepSystemsMaintenance.sparePart",
        None,
        {"partNumber": "BELT-42", "description": "V-belt A42", "quantity": 6},
    )
    assert res["problems"] == []
    assert res["summary"]["partNumber"] == "BELT-42"
    assert res["summary"]["quantityHeld"] == 6


def test_mep_systems_maintenance_stock_level() -> None:
    # 12 on hand - 5 allocated = 7 available.
    res = features.run(
        "mepSystemsMaintenance.stockLevel",
        None,
        {"onHand": 12, "allocated": 5},
    )
    assert res["problems"] == []
    assert res["summary"]["availableItems"] == 7
    assert res["summary"]["allocatedItems"] == 5


def test_mep_systems_maintenance_thermal_imaging() -> None:
    # 68 C - 32 C = 36 C rise.
    res = features.run(
        "mepSystemsMaintenance.thermalImaging",
        None,
        {"hotspotC": 68.0, "referenceC": 32.0},
    )
    assert res["problems"] == []
    assert res["summary"]["temperatureRiseC"] == pytest.approx(36.0, rel=0.01)


def test_mep_systems_maintenance_vibration_sensor() -> None:
    # 5.2 mm/s >= 4.5 mm/s -> alarm True.
    res = features.run(
        "mepSystemsMaintenance.vibrationSensor",
        None,
        {"velocityRms": 5.2, "alarmLimit": 4.5},
    )
    assert res["problems"] == []
    assert res["summary"]["alarm"] is True


# ── MEP Systems Balancing (mep_systems_balancing.py: 4) ─────────────────────────────────────────


def test_mep_systems_balancing_balance_mode() -> None:
    # Index = 160 kPa, sub-branch = 100 kPa -> excess = 60 kPa (>= 40 -> PICV),
    # throttling authority = 60 / 160 = 0.375 (~0.38).
    res = features.run(
        "mepSystemsBalancing.balanceMode",
        None,
        {"indexLossKpa": 160.0, "subBranchLossKpa": 100.0, "branchFlowLps": 3.0},
    )
    assert res["problems"] == []
    assert res["summary"]["excessHeadKpa"] == pytest.approx(60.0, rel=0.01)
    assert res["summary"]["throttlingAuthority"] == pytest.approx(0.375, rel=0.02)
    assert "PICV" in res["summary"]["recommendedStrategy"]


def test_mep_systems_balancing_imbalance_list() -> None:
    # B1: 80 vs 100 (-20%, flagged); B2: 105 vs 100 (+5%, ok); B3: 115 vs 100 (+15%, flagged).
    res = features.run(
        "mepSystemsBalancing.imbalanceList",
        None,
        {"measuredPairs": "B1=100:80;B2=100:105;B3=100:115", "tolerancePct": 10.0, "name": "imb"},
    )
    assert res["problems"] == []
    assert res["summary"]["totalBranches"] == 3
    assert res["summary"]["imbalancedCount"] == 2


def test_mep_systems_balancing_iterate_balance() -> None:
    # r_min = 0.80, r_max = 1.20 -> spread = (1.20 - 0.80)*100 = 40.0%,
    # pumpSpeedMultiplier = 1 / 0.80 = 1.25, head_mult = 1.25^2 = 1.5625,
    # adjustedPumpHeadKpa = 100.0 * 1.5625 = 156.25 kPa (~156.2),
    # maxThrottleFactor = 1.20 / 0.80 = 1.50.
    res = features.run(
        "mepSystemsBalancing.iterateBalance",
        None,
        {"minBranchRatio": 0.8, "maxBranchRatio": 1.2, "currentPumpHeadKpa": 100.0},
    )
    assert res["problems"] == []
    assert res["summary"]["initialSpreadPct"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["pumpSpeedMultiplier"] == pytest.approx(1.25, rel=0.01)
    assert res["summary"]["adjustedPumpHeadKpa"] == pytest.approx(156.25, rel=0.01)
    assert res["summary"]["maxThrottleFactor"] == pytest.approx(1.5, rel=0.01)


def test_mep_systems_balancing_pump_speed() -> None:
    # Q1 = 20 L/s, Q2 = 15 L/s -> ratio = 0.75;
    # N2 = 1400 * 0.75 = 1050 rpm; f2 = 50 * 0.75 = 37.5 Hz;
    # P2 = 16.0 * (0.75)^3 = 6.75 kW; saved = 16.0 - 6.75 = 9.25 kW.
    res = features.run(
        "mepSystemsBalancing.pumpSpeed",
        None,
        {
            "ratedRpm": 1400.0,
            "measuredFlowLps": 20.0,
            "targetFlowLps": 15.0,
            "ratedPowerKw": 16.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["speedRatio"] == pytest.approx(0.75, rel=0.01)
    assert res["summary"]["targetRpm"] == pytest.approx(1050.0, rel=0.01)
    assert res["summary"]["vfdFrequencyHz"] == pytest.approx(37.5, rel=0.01)
    assert res["summary"]["trimmedPowerKw"] == pytest.approx(6.75, rel=0.01)
    assert res["summary"]["powerSavedKw"] == pytest.approx(9.25, rel=0.01)


# ── MEP Systems Zoning (mep_systems_zoning.py: 2) ───────────────────────────────────────────────


def test_mep_systems_zoning_diversity_factor() -> None:
    # Connected = 500 kW, coincident = 400 kW -> CF = 0.80, DF = 1.25, reduction = 20.0%.
    res = features.run(
        "mepSystemsZoning.diversityFactor",
        None,
        {"connectedTotalKw": 500.0, "coincidentPeakKw": 400.0},
    )
    assert res["problems"] == []
    assert res["summary"]["coincidenceFactor"] == pytest.approx(0.8, rel=0.01)
    assert res["summary"]["diversityFactor"] == pytest.approx(1.25, rel=0.01)
    assert res["summary"]["plantReductionPct"] == pytest.approx(20.0, rel=0.01)


def test_mep_systems_zoning_peak_load_shift() -> None:
    # dayPeak = 200 kW, shift = 0.25 -> shaved = 50 kW, newOnPeak = 150 kW.
    # Shifted cooling = 50 kW_e * COP 4.0 = 200 kW_th; over 5 h -> TES = 1000 kWh_th.
    res = features.run(
        "mepSystemsZoning.peakLoadShift",
        None,
        {"dayPeakKw": 200.0, "shiftFraction": 0.25, "peakHours": 5.0, "chillerCop": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["shavedDemandKw"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["newOnPeakKw"] == pytest.approx(150.0, rel=0.01)
    assert res["summary"]["thermalStorageKwh"] == pytest.approx(1000.0, rel=0.01)


# ── MEP Systems Extra (mep_systems_extra.py: 1) ─────────────────────────────────────────────────


def test_mep_systems_size_mismatch() -> None:
    # Upstream = 200 mm, downstream = 100 mm -> ratio = 0.5 (Normal taper);
    # Borda-Carnot area-ratio K = (1 - (100/200)^2)^2 = (1 - 0.25)^2 = 0.5625.
    res = features.run(
        "mepSystems.sizeMismatch",
        None,
        {"upstreamSizeMm": 200.0, "downstreamSizeMm": 100.0},
    )
    assert res["problems"] == []
    assert res["summary"]["diameterRatio"] == pytest.approx(0.5, rel=0.01)
    assert res["summary"]["fittingLossK"] == pytest.approx(0.5625, rel=0.01)
    assert res["summary"]["verdict"] == "Normal taper"

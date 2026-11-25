"""Independent known-answer tests for standalone calculators in MEP HVAC, Ducts, Pipes, Terminals, and Controls."""

from __future__ import annotations

import math

import pytest

from saengine import features

# ── MEP HVAC (mep_hvac.py: 5) ───────────────────────────────────────────────────────────────────


def test_mep_hvac_air_systems() -> None:
    res = features.run(
        "mepHvac.airSystems",
        None,
        {"kind": "return", "flow": 1500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["kind"] == "return"
    assert res["summary"]["flowLPerS"] == pytest.approx(1500.0, rel=0.01)


def test_mep_hvac_internal_gains() -> None:
    # Area = 200 m2; equipment = 20 W/m2 -> 4.0 kW; lighting = 12 W/m2 -> 2.4 kW;
    # 25 people * 70 W/person = 1.75 kW -> total sensible = 8.15 kW.
    res = features.run(
        "mepHvac.internalGains",
        None,
        {"area": 200.0, "people": 25, "equipment": 20.0, "lighting": 12.0},
    )
    assert res["problems"] == []
    assert res["summary"]["sensibleGainKw"] == pytest.approx(8.15, rel=0.01)


def test_mep_hvac_load_settings() -> None:
    res = features.run(
        "mepHvac.loadSettings",
        None,
        {"density": 18.0, "occupancy": 75.0},
    )
    assert res["problems"] == []
    assert res["summary"]["equipmentDensityWPerM2"] == pytest.approx(18.0, rel=0.01)
    assert res["summary"]["occupancyWPerPerson"] == pytest.approx(75.0, rel=0.01)


def test_mep_hvac_terminal_units() -> None:
    res = features.run(
        "mepHvac.terminalUnits",
        None,
        {"flow": 320.0, "kind": "vav"},
    )
    assert res["problems"] == []
    assert res["summary"]["kind"] == "vav"
    assert res["summary"]["flowLPerS"] == pytest.approx(320.0, rel=0.01)


def test_mep_hvac_weather_data() -> None:
    res = features.run(
        "mepHvac.weatherData",
        None,
        {"location": "Austin", "summerDb": 38.0, "winterDb": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["location"] == "Austin"
    assert res["summary"]["summerDbC"] == pytest.approx(38.0, rel=0.01)
    assert res["summary"]["winterDbC"] == pytest.approx(2.0, rel=0.01)


# ── MEP HVAC More (mep_hvac_more.py: 15) ────────────────────────────────────────────────────────


def test_mep_hvac_coil_selection() -> None:
    # Water: Q = 41.86 kW, dT = 5.0 C -> m_dot = 41.86 / (4.186 * 5.0) = 2.0 L/s.
    # Air: V_dot = 3.0 m3/s, dT = 12.0 C -> Q_air = 3.0 * 1.2 * 1.006 * 12.0 = 43.4592 kW >= 41.86 kW.
    res = features.run(
        "mepHvac.coilSelection",
        None,
        {
            "coilDutyKw": 41.86,
            "waterTemperatureDropC": 5.0,
            "airflowM3s": 3.0,
            "airTemperatureChangeC": 12.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["waterFlowLs"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["airSideSensibleKw"] == pytest.approx(43.4592, rel=0.01)
    assert res["summary"]["airSideDutyPasses"] is True


def test_mep_hvac_control_sequences() -> None:
    # Occupied 7 to 19 -> 12 h, schedule valid, economizer = 1 -> True.
    res = features.run(
        "mepHvac.controlSequences",
        None,
        {
            "systemType": "ahu",
            "occupiedStartHour": 7,
            "occupiedEndHour": 19,
            "minimumOutsideAirFraction": 0.25,
            "economizerEnabled": 1,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["occupiedHours"] == 12
    assert res["summary"]["scheduleValid"] is True
    assert res["summary"]["economizer"] is True


def test_mep_hvac_efficiency_ratios() -> None:
    # COP margin = 3.8 - 3.2 = +0.6; EER margin = 13.0 - 11.0 = +2.0 -> bothTargetsMet True.
    res = features.run(
        "mepHvac.efficiencyRatios",
        None,
        {"measuredCop": 3.8, "targetCop": 3.2, "measuredEer": 13.0, "targetEer": 11.0},
    )
    assert res["problems"] == []
    assert res["summary"]["copMargin"] == pytest.approx(0.6, rel=0.01)
    assert res["summary"]["eerMargin"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["bothTargetsMet"] is True


def test_mep_hvac_energy_estimate() -> None:
    # Cooling: 120 kW * 1500 h / 4.0 = 45,000 kWh; Heating: 90 kW * 800 h / 0.90 = 80,000 kWh;
    # Total = 125,000 kWh.
    res = features.run(
        "mepHvac.energyEstimate",
        None,
        {
            "coolingLoadKw": 120.0,
            "heatingLoadKw": 90.0,
            "coolingEquivalentHours": 1500.0,
            "heatingEquivalentHours": 800.0,
            "coolingCop": 4.0,
            "heatingEfficiency": 0.9,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["coolingInputKwh"] == pytest.approx(45000.0, rel=0.01)
    assert res["summary"]["heatingInputKwh"] == pytest.approx(80000.0, rel=0.01)
    assert res["summary"]["annualInputKwh"] == pytest.approx(125000.0, rel=0.01)


def test_mep_hvac_equipment_sizing() -> None:
    # Cooling: 150 * 1.2 = 180 kW -> ceil(180/50) = 4 units.
    # Heating: 90 * 1.1 = 99 kW -> ceil(99/50) = 2 units.
    res = features.run(
        "mepHvac.equipmentSizing",
        None,
        {
            "coincidentCoolingKw": 150.0,
            "coincidentHeatingKw": 90.0,
            "coolingSafetyFactor": 1.2,
            "heatingSafetyFactor": 1.1,
            "unitCapacityKw": 50.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["requiredCoolingKw"] == pytest.approx(180.0, rel=0.01)
    assert res["summary"]["requiredHeatingKw"] == pytest.approx(99.0, rel=0.01)
    assert res["summary"]["coolingUnits"] == 4
    assert res["summary"]["heatingUnits"] == 2


def test_mep_hvac_fan_curve_pick() -> None:
    # Candidate (3.2 m3/s, 650 Pa) >= Required (3.0 m3/s, 600 Pa) -> dutyCovered True.
    # Air power = 3.0 * 600 / 1000 = 1.8 kW; input power = 1.8 / 0.75 = 2.4 kW.
    res = features.run(
        "mepHvac.fanCurvePick",
        None,
        {
            "requiredFlowM3s": 3.0,
            "requiredPressurePa": 600.0,
            "curveFlowM3s": 3.2,
            "curvePressurePa": 650.0,
            "fanEfficiency": 0.75,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["dutyCovered"] is True
    assert res["summary"]["airPowerKw"] == pytest.approx(1.8, rel=0.01)
    assert res["summary"]["inputPowerKw"] == pytest.approx(2.4, rel=0.01)


def test_mep_hvac_part_load_values() -> None:
    # Bins: (0.25, COP=5, 400h), (0.50, COP=4, 800h), (0.75, COP=3, 400h), (1.0, COP=2, 200h).
    # Cooling = 0.25*400 + 0.50*800 + 0.75*400 + 1.0*200 = 100 + 400 + 300 + 200 = 1000.
    # Elec = 100/5 + 400/4 + 300/3 + 200/2 = 20 + 100 + 100 + 100 = 320.
    # Seasonal COP = 1000 / 320 = 3.125; total hours = 1800.
    res = features.run(
        "mepHvac.partLoadValues",
        None,
        {
            "copAt25": 5.0,
            "copAt50": 4.0,
            "copAt75": 3.0,
            "copAt100": 2.0,
            "hours25": 400.0,
            "hours50": 800.0,
            "hours75": 400.0,
            "hours100": 200.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["seasonalCop"] == pytest.approx(3.125, rel=0.01)
    assert res["summary"]["operatingHours"] == pytest.approx(1800.0, rel=0.01)


def test_mep_hvac_schedule_profiles() -> None:
    # Occupied = 12 * 5 + 6 * 2 = 72 h/wk; unoccupied = 168 - 72 = 96 h/wk.
    # Weighted avg load = (72 * 1.0 + 96 * 0.25) / 168 = (72 + 24) / 168 = 96 / 168 = 4/7 = 0.57143.
    res = features.run(
        "mepHvac.scheduleProfiles",
        None,
        {
            "weekdayOccupiedHours": 12.0,
            "weekendOccupiedHours": 6.0,
            "weekdayCount": 5,
            "weekendCount": 2,
            "occupiedFraction": 1.0,
            "setbackFraction": 0.25,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["occupiedHoursPerWeek"] == pytest.approx(72.0, rel=0.01)
    assert res["summary"]["weeklyAverageLoadFraction"] == pytest.approx(96.0 / 168.0, rel=0.01)


def test_mep_hvac_sensor_layout() -> None:
    # Area: ceil(250 / 50) = 5; length: ceil(25 / 8) = 4 -> max = 5 sensors.
    res = features.run(
        "mepHvac.sensorLayout",
        None,
        {
            "zoneAreaM2": 250.0,
            "maximumAreaPerSensorM2": 50.0,
            "zoneLengthM": 25.0,
            "maximumSensorSpacingM": 8.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["sensorCount"] == 5


def test_mep_hvac_terminal_selection() -> None:
    # 80 <= 150 <= 200 -> airflowPasses True; NC 32 <= 35 -> noisePasses True.
    res = features.run(
        "mepHvac.terminalSelection",
        None,
        {
            "designFlowLs": 150.0,
            "terminalMaximumLs": 200.0,
            "terminalMinimumLs": 80.0,
            "roomNoiseLimitNc": 35.0,
            "terminalNoiseNc": 32.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["airflowPasses"] is True
    assert res["summary"]["noisePasses"] is True
    assert res["summary"]["requiredFlowLs"] == pytest.approx(150.0, rel=0.01)


def test_mep_hvac_thermostat_setpoints() -> None:
    # Occupied deadband = 24 - 21.5 = 2.5 C (< 3.0 C minimum) -> passes False;
    # unoccupied deadband = 29 - 15 = 14.0 C.
    res = features.run(
        "mepHvac.thermostatSetpoints",
        None,
        {
            "occupiedCoolingC": 24.0,
            "occupiedHeatingC": 21.5,
            "unoccupiedCoolingC": 29.0,
            "unoccupiedHeatingC": 15.0,
            "deadbandC": 3.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["occupiedDeadbandC"] == pytest.approx(2.5, rel=0.01)
    assert res["summary"]["unoccupiedDeadbandC"] == pytest.approx(14.0, rel=0.01)
    assert res["summary"]["passes"] is False


def test_mep_hvac_zone_cooling() -> None:
    # Total = 6.0 + 1.5 = 7.5 kW; dT = 25 - 15 = 10 K.
    # Sensible airflow = 6.0 / (1.2 * 1.005 * 10) * 1000 = 497.512 L/s.
    expected_flow = 6.0 / (1.2 * 1.005 * 10.0) * 1000.0
    res = features.run(
        "mepHvac.zoneCooling",
        None,
        {
            "sensibleLoadKw": 6.0,
            "latentLoadKw": 1.5,
            "supplyTemperatureC": 15.0,
            "roomTemperatureC": 25.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["totalCoolingKw"] == pytest.approx(7.5, rel=0.01)
    assert res["summary"]["sensibleAirflowLs"] == pytest.approx(expected_flow, rel=0.01)


def test_mep_hvac_zone_heating() -> None:
    # Load = 80 m2 * 60 W/m2 / 1000 = 4.8 kW; dT = 22 - (-2) = 24 C.
    res = features.run(
        "mepHvac.zoneHeating",
        None,
        {
            "zoneAreaM2": 80.0,
            "designHeatLossWm2": 60.0,
            "outsideTemperatureC": -2.0,
            "setpointC": 22.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["heatingLoadKw"] == pytest.approx(4.8, rel=0.01)
    assert res["summary"]["designTemperatureRiseC"] == pytest.approx(24.0, rel=0.01)


def test_mep_hvac_zone_reheat() -> None:
    # Q = 100 L/s = 0.1 m3/s; dT = 22 - 14 = 8 K;
    # reheat = 0.1 * 1.2 * 1.006 * 8 = 0.96576 kW.
    res = features.run(
        "mepHvac.zoneReheat",
        None,
        {
            "minimumAirflowLs": 100.0,
            "supplyTemperatureC": 14.0,
            "zoneSetpointC": 22.0,
            "airDensityKgM3": 1.2,
            "specificHeatKjKgK": 1.006,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["temperatureRiseC"] == pytest.approx(8.0, rel=0.01)
    assert res["summary"]["reheatDutyKw"] == pytest.approx(0.96576, rel=0.01)


def test_mep_hvac_zoning_rules() -> None:
    # 90 <= 120 (areaPasses True); 2.5 > 2.0 (solarPasses False).
    res = features.run(
        "mepHvac.zoningRules",
        None,
        {
            "adjacentZoneAreaM2": 90.0,
            "maximumZoneAreaM2": 120.0,
            "solarLoadDifferenceKw": 2.5,
            "maximumSolarLoadDifferenceKw": 2.0,
            "orientation": "west",
        },
    )
    assert res["problems"] == []
    assert res["summary"]["areaPasses"] is True
    assert res["summary"]["solarPasses"] is False
    assert res["summary"]["orientation"] == "west"


# ── MEP HVAC Analysis (mep_hvac.py + mep_hvac_analysis.py: 7) ───────────────────────────────────


def test_mep_hvac_analysis_duct_sizing() -> None:
    # Standard equal-friction textbook check: Q = 1000 L/s = 1.0 m3/s at 1.0 Pa/m, roughness 0.09 mm.
    # At D = 0.4415 m: A = 0.1531 m2, v = 6.53 m/s, Re = 192,200, Swamee-Jain f = 0.01723 ->
    # dp/L = f/D * 0.5*rho*v^2 = 0.01723 / 0.4415 * 0.6 * 6.53^2 = 1.00 Pa/m.
    # Rectangular 2:1 Huebscher: De = 1.30 * (2*b^2)^0.625 / (3*b)^0.25 = 1.30 * 2^0.625 / 3^0.25 * b = 1.5227 * b
    # -> b = 441.5 / 1.5227 = 290.0 mm, a = 580.0 mm.
    res = features.run(
        "mepHvacAnalysis.ductSizing",
        None,
        {"flow": 1000.0, "friction": 1.0, "roughnessMm": 0.09, "aspect": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["roundDiameterMm"] == pytest.approx(441.5, rel=0.01)
    assert res["summary"]["frictionPaPerM"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["rectHeightMm"] == pytest.approx(290.0, rel=0.01)
    assert res["summary"]["rectWidthMm"] == pytest.approx(580.0, rel=0.01)


def test_mep_hvac_analysis_dampers() -> None:
    # Q = 800 L/s = 0.8 m3/s, D = 400 mm = 0.4 m -> A = pi * 0.16 / 4 = 0.12566 m2 -> v = 6.3662 m/s.
    expected_v = 0.8 / (math.pi * 0.4**2 / 4.0)
    res = features.run(
        "mepHvacAnalysis.dampers",
        None,
        {"flow": 800.0, "diameter": 400.0},
    )
    assert res["problems"] == []
    assert res["summary"]["velocityMs"] == pytest.approx(expected_v, rel=0.01)


def test_mep_hvac_analysis_duct_fittings() -> None:
    # dp = C * 0.5 * rho * v^2 = 0.5 * 0.5 * 1.2 * 8^2 = 19.2 Pa.
    res = features.run(
        "mepHvacAnalysis.ductFittings",
        None,
        {"velocity": 8.0, "fitting": "elbow", "coefficient": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["pressureLossPa"] == pytest.approx(19.2, rel=0.01)


def test_mep_hvac_analysis_infiltration() -> None:
    # 720 m3 * 0.75 ACH / 3600 = 0.15 m3/s = 150 L/s.
    res = features.run(
        "mepHvacAnalysis.infiltration",
        None,
        {"volume": 720.0, "ach": 0.75},
    )
    assert res["problems"] == []
    assert res["summary"]["flowM3PerS"] == pytest.approx(0.15, rel=0.01)
    assert res["summary"]["flowLPerS"] == pytest.approx(150.0, rel=0.01)


def test_mep_hvac_analysis_peak_loads() -> None:
    res = features.run(
        "mepHvacAnalysis.peakLoads",
        None,
        {"cooling": 140.0, "heating": 85.0},
    )
    assert res["problems"] == []
    assert res["summary"]["peakCoolingKw"] == pytest.approx(140.0, rel=0.01)
    assert res["summary"]["peakHeatingKw"] == pytest.approx(85.0, rel=0.01)


def test_mep_hvac_analysis_shading() -> None:
    # 2500 W * 0.40 = 1000 W.
    res = features.run(
        "mepHvacAnalysis.shading",
        None,
        {"unshaded": 2500.0, "coefficient": 0.4},
    )
    assert res["problems"] == []
    assert res["summary"]["solarGainW"] == pytest.approx(1000.0, rel=0.01)


def test_mep_hvac_analysis_u_values() -> None:
    # R_total = 0.17 + 3.79 + 0.04 = 4.00 m2K/W -> U = 1 / 4.00 = 0.25 W/(m2K).
    res = features.run(
        "mepHvacAnalysis.uValues",
        None,
        {"surface": 0.17, "insulation": 3.79, "air": 0.04},
    )
    assert res["problems"] == []
    assert res["summary"]["uValueWPerM2K"] == pytest.approx(0.25, rel=0.01)


# ── MEP HVAC Analysis More (mep_hvac_analysis_more.py: 6) ───────────────────────────────────────


def test_mep_hvac_analysis_cfd_room_study() -> None:
    # V = 180 m3, Q = 400 L/s = 0.4 m3/s -> ACH = 400 * 3.6 / 180 = 8.0 /h.
    # Q_sens = 0.4 * 1.2 * 1.006 * (24 - 14) = 4.8288 kW; load = 4.0 kW -> coverage = 1.2072.
    expected_q = 0.4 * 1.2 * 1.006 * 10.0
    res = features.run(
        "mepHvacAnalysis.cfdRoomStudy",
        None,
        {
            "roomVolumeM3": 180.0,
            "supplyFlowLs": 400.0,
            "roomHeatLoadKw": 4.0,
            "supplyTemperatureC": 14.0,
            "roomTemperatureC": 24.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["airChangesPerHour"] == pytest.approx(8.0, rel=0.01)
    assert res["summary"]["idealSensibleCapacityKw"] == pytest.approx(expected_q, rel=0.01)
    assert res["summary"]["loadCoverageRatio"] == pytest.approx(expected_q / 4.0, rel=0.01)


def test_mep_hvac_analysis_duct_leakage() -> None:
    # 80 m2 * 0.4 L/(s*m2) = 32.0 L/s; 32 / 1600 * 100 = 2.0%.
    res = features.run(
        "mepHvacAnalysis.ductLeakage",
        None,
        {
            "ductSurfaceM2": 80.0,
            "leakageCoefficientLsM2": 0.4,
            "fanFlowLs": 1600.0,
            "testPressurePa": 750.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["leakageFlowLs"] == pytest.approx(32.0, rel=0.01)
    assert res["summary"]["leakagePercentOfFanFlow"] == pytest.approx(2.0, rel=0.01)


def test_mep_hvac_analysis_fan_power_check() -> None:
    # Q = 2.5 m3/s = 2500 L/s, dP = 720 Pa -> air = 1.8 kW.
    # eta_f = 0.72, eta_m = 0.90 -> P_in = 1.8 / (0.72 * 0.90) = 2.7778 kW = 2777.8 W.
    # SFP = 2777.8 / 2500 = 1.1111 W/(L/s) <= 1.8 W/(L/s) -> passes True.
    p_in = 2.5 * 720.0 / 1000.0 / 0.72 / 0.90
    res = features.run(
        "mepHvacAnalysis.fanPowerCheck",
        None,
        {
            "airflowM3s": 2.5,
            "totalPressurePa": 720.0,
            "fanEfficiency": 0.72,
            "motorEfficiency": 0.9,
            "maximumSpecificPowerWPerLs": 1.8,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["inputPowerKw"] == pytest.approx(p_in, rel=0.01)
    assert res["summary"]["specificFanPowerWPerLs"] == pytest.approx(p_in / 2.5, rel=0.01)
    assert res["summary"]["passes"] is True


def test_mep_hvac_analysis_internal_gain_profile() -> None:
    # Design: 30*75 + 1000 + 1500 = 2250 + 1000 + 1500 = 4750 W.
    # Scheduled (0.8 occ, 0.6 equip): (2250 + 1000)*0.8 + 1500*0.6 = 2600 + 900 = 3500 W.
    res = features.run(
        "mepHvacAnalysis.internalGainProfile",
        None,
        {
            "occupants": 30,
            "sensiblePerPersonW": 75.0,
            "lightingLoadW": 1000.0,
            "equipmentLoadW": 1500.0,
            "occupancyFraction": 0.8,
            "equipmentFraction": 0.6,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["designSensibleGainW"] == pytest.approx(4750.0, rel=0.01)
    assert res["summary"]["scheduledSensibleGainW"] == pytest.approx(3500.0, rel=0.01)


def test_mep_hvac_analysis_system_balancing() -> None:
    # Design = 200 L/s, measured = 220 L/s -> deviation = +10.0%.
    # Damper loss = K * 0.6 * (220 / 100)^2 = 2.5 * 0.6 * 4.84 = 7.26 Pa.
    res = features.run(
        "mepHvacAnalysis.systemBalancing",
        None,
        {
            "branchDesignLs": 200.0,
            "branchMeasuredLs": 220.0,
            "availablePressurePa": 45.0,
            "damperLossCoefficient": 2.5,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["airflowDeviationPercent"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["damperLossPa"] == pytest.approx(7.26, rel=0.01)


def test_mep_hvac_analysis_thermal_mass() -> None:
    # Concrete: 100 m2 * 0.20 m * 2400 kg/m3 * 900 J/(kg*K) / 1000 = 43,200 kJ/K.
    # Total = 43,200 + 300 = 43,500 kJ/K -> per m2 = 435.0 kJ/(m2*K).
    res = features.run(
        "mepHvacAnalysis.thermalMass",
        None,
        {
            "exposedConcreteAreaM2": 100.0,
            "thicknessM": 0.2,
            "densityKgM3": 2400.0,
            "specificHeatJkgK": 900.0,
            "zoneAirCapacityKjK": 300.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["concreteCapacityKjK"] == pytest.approx(43200.0, rel=0.01)
    assert res["summary"]["totalCapacityKjK"] == pytest.approx(43500.0, rel=0.01)
    assert res["summary"]["capacityPerAreaKjM2K"] == pytest.approx(435.0, rel=0.01)


# ── MEP Ducts (mep_ducts.py: 19) ────────────────────────────────────────────────────────────────


def test_mep_ducts_auto_route() -> None:
    # (1, 2) to (13, 7) via x-first corner (13, 2): length = 12 + 5 = 17 m, 2 legs (bends=2).
    res = features.run(
        "mepDucts.autoRoute",
        None,
        {"startXM": 1.0, "startYM": 2.0, "endXM": 13.0, "endYM": 7.0, "firstLeg": "x"},
    )
    assert res["problems"] == []
    assert res["summary"]["routeLengthM"] == pytest.approx(17.0, rel=0.01)
    assert res["summary"]["bendCount"] == 2


def test_mep_ducts_draw_duct() -> None:
    # 600 mm x 400 mm = 0.24 m2; flow = 1.2 m3/s (key flowLs has unit m3/s) -> v = 5.0 m/s.
    res = features.run(
        "mepDucts.drawDuct",
        None,
        {"flowLs": 1.2, "widthMm": 600.0, "heightMm": 400.0, "system": "supply"},
    )
    assert res["problems"] == []
    assert res["summary"]["areaM2"] == pytest.approx(0.24, rel=0.01)
    assert res["summary"]["velocityMs"] == pytest.approx(5.0, rel=0.01)


def test_mep_ducts_duct_accessories() -> None:
    # Damper = 2.5 * 20 = 50 Pa; total = 50 + 90 + 35 = 175 Pa.
    res = features.run(
        "mepDucts.ductAccessories",
        None,
        {
            "velocityMs": 5.8,
            "dynamicPressurePa": 20.0,
            "damperLossCoefficient": 2.5,
            "filterLossPa": 90.0,
            "silencerLossPa": 35.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["damperLossPa"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["totalAccessoryLossPa"] == pytest.approx(175.0, rel=0.01)


def test_mep_ducts_duct_clearance() -> None:
    # Available 250 >= required 150 -> passes True; envelope = 450 + 150 = 600 mm.
    res = features.run(
        "mepDucts.ductClearance",
        None,
        {
            "ductWidthMm": 700.0,
            "ductHeightMm": 450.0,
            "requiredClearanceMm": 150.0,
            "availableClearanceMm": 250.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["passes"] is True
    assert res["summary"]["overallEnvelopeMm"] == pytest.approx(600.0, rel=0.01)


def test_mep_ducts_duct_gauge() -> None:
    # 0.7 mm < 0.8 mm required -> passes False.
    res = features.run(
        "mepDucts.ductGauge",
        None,
        {
            "largestSideMm": 900.0,
            "pressureClassPa": 750.0,
            "sheetThicknessMm": 0.7,
            "minimumThicknessMm": 0.8,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["passes"] is False


def test_mep_ducts_duct_systems() -> None:
    res = features.run(
        "mepDucts.ductSystems",
        None,
        {
            "system": "exhaust",
            "designFlowM3s": 2.4,
            "pressureClassPa": 750.0,
            "systemTag": "EA-2",
        },
    )
    assert res["problems"] == []
    assert res["summary"]["system"] == "exhaust"
    assert res["summary"]["designFlowM3s"] == pytest.approx(2.4, rel=0.01)
    assert res["summary"]["pressureClassPa"] == pytest.approx(750.0, rel=0.01)


def test_mep_ducts_elbow_radius() -> None:
    # Ratio = 750 / 500 = 1.5; dp = 0.25 * 1.2 * 6^2 / 2 = 5.4 Pa.
    res = features.run(
        "mepDucts.elbowRadius",
        None,
        {
            "ductWidthMm": 500.0,
            "centrelineRadiusMm": 750.0,
            "velocityMs": 6.0,
            "lossCoefficient": 0.25,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["radiusRatio"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["pressureLossPa"] == pytest.approx(5.4, rel=0.01)


def test_mep_ducts_flex_duct() -> None:
    # D = 250 mm -> A = pi * 0.25^2 / 4 = 0.049087 m2; Q = 0.15 m3/s -> v = 3.0558 m/s.
    # Loss = 1.5 Pa/m * 2.4 m = 3.6 Pa; 2.4 <= 3.0 -> lengthPasses True.
    expected_v = 0.15 / (math.pi * 0.25**2 / 4.0)
    res = features.run(
        "mepDucts.flexDuct",
        None,
        {
            "flowM3s": 0.15,
            "diameterMm": 250.0,
            "lengthM": 2.4,
            "frictionPaPerM": 1.5,
            "maximumLengthM": 3.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["velocityMs"] == pytest.approx(expected_v, rel=0.01)
    assert res["summary"]["straightLossPa"] == pytest.approx(3.6, rel=0.01)
    assert res["summary"]["lengthPasses"] is True


def test_mep_ducts_friction_rate() -> None:
    # 1.0 m3/s supply round duct at 1.0 Pa/m: Darcy-Weisbach needs D ~ 441.5 mm -> next 50 mm step = 450 mm;
    # velocity = 1.0 / (pi * 0.45^2 / 4) = 6.288 m/s.
    expected_v = 1.0 / (math.pi * 0.45**2 / 4.0)
    res = features.run(
        "mepDucts.frictionRate",
        None,
        {"flowM3s": 1.0, "frictionRatePaM": 1.0, "system": "supply", "shape": "round"},
    )
    assert res["problems"] == []
    assert res["summary"]["equivalentDiameterMm"] == pytest.approx(450.0, rel=0.01)
    assert res["summary"]["velocityMs"] == pytest.approx(expected_v, rel=0.01)


def test_mep_ducts_insulation_check() -> None:
    # Q = k * A * dT / t = 0.040 * 15 * 20 / 0.030 = 400.0 W; 30 mm >= 25 mm -> True.
    res = features.run(
        "mepDucts.insulationCheck",
        None,
        {
            "ductSurfaceM2": 15.0,
            "insulationThicknessMm": 30.0,
            "conductivityWmK": 0.04,
            "temperatureDifferenceC": 20.0,
            "requiredThicknessMm": 25.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["heatTransferW"] == pytest.approx(400.0, rel=0.01)
    assert res["summary"]["thicknessPasses"] is True


def test_mep_ducts_place_diffuser() -> None:
    # ceil(420 / 60) = 7 diffusers -> scheduled = 420, excess = 0. Try 440 / 60 -> 8, 480, excess 40.
    res = features.run(
        "mepDucts.placeDiffuser",
        None,
        {"zoneFlowLs": 440.0, "diffuserFlowLs": 60.0, "maximumThrowM": 4.5},
    )
    assert res["problems"] == []
    assert res["summary"]["diffuserCount"] == 8
    assert res["summary"]["scheduledFlowLs"] == pytest.approx(480.0, rel=0.01)
    assert res["summary"]["excessFlowLs"] == pytest.approx(40.0, rel=0.01)


def test_mep_ducts_place_vav() -> None:
    # Range = 300 - 90 = 210 L/s; 90 <= 240 <= 300 -> True.
    res = features.run(
        "mepDucts.placeVav",
        None,
        {"maximumFlowLs": 300.0, "minimumFlowLs": 90.0, "designFlowLs": 240.0},
    )
    assert res["problems"] == []
    assert res["summary"]["controlRangeLs"] == pytest.approx(210.0, rel=0.01)
    assert res["summary"]["setpointPasses"] is True


def test_mep_ducts_reducer_size() -> None:
    # A_up = 0.64 m2 (sqrt=0.8), A_dn = 0.36 m2 (sqrt=0.6) -> ratio = 0.5625, reduction = 43.75%.
    # radial_change = (0.8 - 0.6) / 2 = 0.1 m; L = 0.5 m -> angle = atan(0.2) = 11.3099 deg -> included = 22.62 deg.
    expected_included = 2.0 * math.degrees(math.atan(0.1 / 0.5))
    res = features.run(
        "mepDucts.reducerSize",
        None,
        {"upstreamAreaM2": 0.64, "downstreamAreaM2": 0.36, "transitionLengthM": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["areaRatio"] == pytest.approx(0.5625, rel=0.01)
    assert res["summary"]["areaReductionPercent"] == pytest.approx(43.75, rel=0.01)
    assert res["summary"]["includedAngleDeg"] == pytest.approx(expected_included, rel=0.01)


def test_mep_ducts_risers() -> None:
    # 1000 x 500 mm = 0.5 m2; flow = 2.5 m3/s -> v = 5.0 m/s, aspect = 2.0.
    res = features.run(
        "mepDucts.risers",
        None,
        {"flowM3s": 2.5, "widthMm": 1000.0, "depthMm": 500.0, "storyHeightM": 3.5},
    )
    assert res["problems"] == []
    assert res["summary"]["areaM2"] == pytest.approx(0.5, rel=0.01)
    assert res["summary"]["velocityMs"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["aspectRatio"] == pytest.approx(2.0, rel=0.01)


def test_mep_ducts_sizing_method() -> None:
    res = features.run(
        "mepDucts.sizingMethod",
        None,
        {"method": "staticRegain", "frictionRatePaM": 0.8, "maximumVelocityMs": 7.5},
    )
    assert res["problems"] == []
    assert res["summary"]["method"] == "staticRegain"
    assert res["summary"]["frictionRatePaM"] == pytest.approx(0.8, rel=0.01)
    assert res["summary"]["maximumVelocityMs"] == pytest.approx(7.5, rel=0.01)


def test_mep_ducts_static_regain() -> None:
    # dp_v = 1.2 * (10^2 - 6^2) / 2 = 1.2 * 64 / 2 = 38.4 Pa; regain = 0.75 * 38.4 = 28.8 Pa.
    res = features.run(
        "mepDucts.staticRegain",
        None,
        {
            "upstreamVelocityMs": 10.0,
            "downstreamVelocityMs": 6.0,
            "recoveryFactor": 0.75,
            "airDensityKgM3": 1.2,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["availableRegainPa"] == pytest.approx(28.8, rel=0.01)


def test_mep_ducts_takeoff_fitting() -> None:
    # Branch fraction = 0.4 / 1.6 = 0.25; v_branch = 0.4 / 0.08 = 5.0 m/s;
    # loss = 0.8 * 1.2 * 5^2 / 2 = 12.0 Pa.
    res = features.run(
        "mepDucts.takeoffFitting",
        None,
        {
            "mainFlowM3s": 1.6,
            "branchFlowM3s": 0.4,
            "mainAreaM2": 0.4,
            "branchAreaM2": 0.08,
            "lossCoefficient": 0.8,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["branchFlowFraction"] == pytest.approx(0.25, rel=0.01)
    assert res["summary"]["branchVelocityMs"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["takeoffLossPa"] == pytest.approx(12.0, rel=0.01)


def test_mep_ducts_transition_piece() -> None:
    # dw = |800 - 400|/2 = 200 mm; dh = |400 - 300|/2 = 50 mm -> max = 200 mm.
    # min L = 200 / tan(15 deg) = 746.41 mm; A_up = 320,000 mm2, A_dn = 120,000 mm2.
    expected_len = 200.0 / math.tan(math.radians(15.0))
    res = features.run(
        "mepDucts.transitionPiece",
        None,
        {
            "upstreamWidthMm": 800.0,
            "downstreamWidthMm": 400.0,
            "upstreamHeightMm": 400.0,
            "downstreamHeightMm": 300.0,
            "maximumWallAngleDeg": 15.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["minimumLengthMm"] == pytest.approx(expected_len, rel=0.01)
    assert res["summary"]["upstreamAreaMm2"] == pytest.approx(320000.0, rel=0.01)
    assert res["summary"]["downstreamAreaMm2"] == pytest.approx(120000.0, rel=0.01)


def test_mep_ducts_velocity_check() -> None:
    # 500 x 400 mm = 0.20 m2; flow = 1.4 m3/s -> v = 7.0 m/s > 6.0 m/s -> passes False.
    res = features.run(
        "mepDucts.velocityCheck",
        None,
        {"flowM3s": 1.4, "widthMm": 500.0, "heightMm": 400.0, "maximumVelocityMs": 6.0},
    )
    assert res["problems"] == []
    assert res["summary"]["velocityMs"] == pytest.approx(7.0, rel=0.01)
    assert res["summary"]["passes"] is False


# ── MEP HVAC Pipes (mep_hvac_pipes.py: 22) ──────────────────────────────────────────────────────


def test_mep_hvac_pipes_air_separator_location() -> None:
    # P_local = 250 - 9.80665 * 10 = 151.9335 kPa; P_abs = 151.9335 + 101.325 = 253.2585 kPa.
    p_loc = 250.0 - 9.80665 * 10.0
    res = features.run(
        "mepHvacPipes.airSeparatorLocation",
        None,
        {"systemPressureKpa": 250.0, "temperatureC": 70.0, "separatorLocationHeightM": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["estimatedLocalPressureKpa"] == pytest.approx(p_loc, rel=0.01)
    assert res["summary"]["absolutePressureKpa"] == pytest.approx(p_loc + 101.325, rel=0.01)


def test_mep_hvac_pipes_auto_route() -> None:
    # (2, 3) to (10, 9) -> |8| + |6| = 14.0 m.
    res = features.run(
        "mepHvacPipes.autoRoute",
        None,
        {"startXM": 2.0, "startYM": 3.0, "endXM": 10.0, "endYM": 9.0, "firstLeg": "y"},
    )
    assert res["problems"] == []
    assert res["summary"]["routeLengthM"] == pytest.approx(14.0, rel=0.01)


def test_mep_hvac_pipes_balancing_valve_set() -> None:
    # Measured 2.0 vs design 2.5 -> error = -20.0%.
    # Kv = 2.0 * 3.6 / sqrt(25 / 100) = 7.2 / 0.5 = 14.4.
    res = features.run(
        "mepHvacPipes.balancingValveSet",
        None,
        {"designFlowLs": 2.5, "measuredFlowLs": 2.0, "measuredDropKpa": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["flowErrorPercent"] == pytest.approx(-20.0, rel=0.01)
    assert res["summary"]["inferredKv"] == pytest.approx(14.4, rel=0.01)


def test_mep_hvac_pipes_condensation_check() -> None:
    # Magnus dew point at T=25 C, RH=50%:
    # gamma = ln(0.5) + 17.62*25/(243.12+25) = -0.69315 + 1.64288 = 0.94973 ->
    # Td = 243.12 * 0.94973 / (17.62 - 0.94973) = 13.851 C.
    # Surface = 12.0 C <= 13.851 C -> condensationRisk True, margin = -1.851 C.
    gamma = math.log(0.5) + 17.62 * 25.0 / (243.12 + 25.0)
    td = 243.12 * gamma / (17.62 - gamma)
    res = features.run(
        "mepHvacPipes.condensationCheck",
        None,
        {"airTemperatureC": 25.0, "relativeHumidityPercent": 50.0, "surfaceTemperatureC": 12.0},
    )
    assert res["problems"] == []
    assert res["summary"]["dewPointC"] == pytest.approx(td, rel=0.01)
    assert res["summary"]["surfaceMarginC"] == pytest.approx(12.0 - td, rel=0.01)
    assert res["summary"]["condensationRisk"] is True


def test_mep_hvac_pipes_elbow_fitting() -> None:
    # D = 100 mm, R = 150 mm, 90 deg -> arc = (pi/2)*150 = 235.62 mm, R/D = 1.5.
    res = features.run(
        "mepHvacPipes.elbowFitting",
        None,
        {"pipeDiameterMm": 100.0, "centerlineRadiusMm": 150.0, "turnAngleDeg": 90.0},
    )
    assert res["problems"] == []
    assert res["summary"]["centerlineArcLengthMm"] == pytest.approx(75.0 * math.pi, rel=0.01)
    assert res["summary"]["radiusToDiameterRatio"] == pytest.approx(1.5, rel=0.01)


def test_mep_hvac_pipes_expansion_tank_size() -> None:
    # V = 2000 L, dT = 60 C -> expansion = 2000 * 0.00021 * 60 = 25.2 L.
    # P1 = 150 + 101.325 = 251.325 kPa abs; P2 = 450 + 101.325 = 551.325 kPa abs;
    # acceptance = 1 - 251.325 / 551.325 = 0.54414 -> V_min = 25.2 / 0.54414 = 46.311 L.
    acc = 1.0 - (150.0 + 101.325) / (450.0 + 101.325)
    res = features.run(
        "mepHvacPipes.expansionTankSize",
        None,
        {
            "systemVolumeL": 2000.0,
            "temperatureRiseC": 60.0,
            "coldPressureKpa": 150.0,
            "maximumPressureKpa": 450.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["waterExpansionL"] == pytest.approx(25.2, rel=0.01)
    assert res["summary"]["minimumVesselVolumeL"] == pytest.approx(25.2 / acc, rel=0.01)


def test_mep_hvac_pipes_fitting_schedule() -> None:
    # 16 + 6 + 4 + 3 = 29 fittings.
    res = features.run(
        "mepHvacPipes.fittingSchedule",
        None,
        {"elbows": 16, "tees": 6, "valves": 4, "reducers": 3},
    )
    assert res["problems"] == []
    assert res["summary"]["fittingCount"] == 29


def test_mep_hvac_pipes_flexible_connection() -> None:
    # Q = 8 L/s = 0.008 m3/s, D = 80 mm = 0.08 m -> A = 0.0050265 m2 -> v = 1.5915 m/s <= 2.0 -> True.
    expected_v = 0.008 / (math.pi * 0.08**2 / 4.0)
    res = features.run(
        "mepHvacPipes.flexibleConnection",
        None,
        {"pumpFlowLs": 8.0, "connectionDiameterMm": 80.0, "maximumVelocityMs": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["connectorVelocityMs"] == pytest.approx(expected_v, rel=0.01)
    assert res["summary"]["pass"] is True


def test_mep_hvac_pipes_friction_limit() -> None:
    # Q = 3.0 L/s = 0.003 m3/s, D = 50 mm = 0.05 m -> A = 0.0019635 m2 -> v = 1.5279 m/s.
    # dp/L = f / D * 1000 * v^2 / 2 / 1000 = 0.020 / 0.05 * 0.5 * 1.5279^2 = 0.4669 kPa/m > 0.3 -> False.
    v = 0.003 / (math.pi * 0.05**2 / 4.0)
    grad = 0.020 / 0.05 * 0.5 * v**2
    res = features.run(
        "mepHvacPipes.frictionLimit",
        None,
        {
            "flowLs": 3.0,
            "diameterMm": 50.0,
            "darcyFactor": 0.020,
            "maximumKpaPerM": 0.3,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["velocityMs"] == pytest.approx(v, rel=0.01)
    assert res["summary"]["pressureGradientKpaPerM"] == pytest.approx(grad, rel=0.01)
    assert res["summary"]["pass"] is False


def test_mep_hvac_pipes_insulation_thickness() -> None:
    # r1 = 30 mm = 0.03 m, dT = 24 K, k = 0.035 W/(mK), q = 12 W/m.
    # r2 = 0.03 * exp(2 * pi * 0.035 * 24 / 12) = 0.03 * exp(0.43982) = 0.046572 m -> t = 16.572 mm.
    r2 = 0.03 * math.exp(2.0 * math.pi * 0.035 * 24.0 / 12.0)
    res = features.run(
        "mepHvacPipes.insulationThickness",
        None,
        {
            "pipeDiameterMm": 60.0,
            "innerTemperatureC": 6.0,
            "ambientTemperatureC": 30.0,
            "conductivityWmK": 0.035,
            "heatLossWPerM": 12.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["requiredThicknessMm"] == pytest.approx((r2 - 0.03) * 1000.0, rel=0.01)


def test_mep_hvac_pipes_insulation_type() -> None:
    res = features.run(
        "mepHvacPipes.insulationType",
        None,
        {"material": "elastomeric foam", "conductivityWmK": 0.036, "pipeDiameterMm": 80.0},
    )
    assert res["problems"] == []
    assert res["summary"]["material"] == "elastomeric foam"
    assert res["summary"]["conductivityWmK"] == pytest.approx(0.036, rel=0.01)
    assert res["summary"]["pipeDiameterMm"] == pytest.approx(80.0, rel=0.01)


def test_mep_hvac_pipes_pipe_anchor_force() -> None:
    # F = E * A * eps = 200e9 Pa * 1000e-6 m2 * 0.0005 = 100,000 N = 100.0 kN.
    res = features.run(
        "mepHvacPipes.pipeAnchorForce",
        None,
        {"elasticModulusGpa": 200.0, "areaMm2": 1000.0, "thermalStrain": 0.0005},
    )
    assert res["problems"] == []
    assert res["summary"]["restrainedAxialForceKn"] == pytest.approx(100.0, rel=0.01)


def test_mep_hvac_pipes_pipe_size() -> None:
    # Q = 6 L/s = 0.006 m3/s, V = 1.5 m/s -> A = 0.004 m2 -> D = sqrt(4*0.004/pi)*1000 = 71.365 mm.
    expected_d = math.sqrt(4.0 * 0.006 / (math.pi * 1.5)) * 1000.0
    res = features.run(
        "mepHvacPipes.pipeSize",
        None,
        {"flowLs": 6.0, "velocityMs": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["minimumInternalDiameterMm"] == pytest.approx(expected_d, rel=0.01)


def test_mep_hvac_pipes_pipe_support() -> None:
    # Run = 25 m, end offsets = 0.5 m each -> span = 24 m; spacing = 3.0 m -> ceil(24/3)+1 = 9 supports.
    res = features.run(
        "mepHvacPipes.pipeSupport",
        None,
        {"runLengthM": 25.0, "supportSpacingM": 3.0, "endOffsetM": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["supportCount"] == 9


def test_mep_hvac_pipes_primary_secondary_loop() -> None:
    # Primary = 10 L/s, secondary = 14 L/s -> decoupler = 4 L/s secondary-to-primary; dT = 13 - 6 = 7 C.
    res = features.run(
        "mepHvacPipes.primarySecondaryLoop",
        None,
        {
            "primaryFlowLs": 10.0,
            "secondaryFlowLs": 14.0,
            "primarySupplyC": 6.0,
            "secondaryReturnC": 13.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["decouplerFlowLs"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["flowDirection"] == "secondary-to-primary"
    assert res["summary"]["temperatureDifferenceC"] == pytest.approx(7.0, rel=0.01)


def test_mep_hvac_pipes_pump_head_calculation() -> None:
    # 6 + 21 + 4 = 31 m.
    res = features.run(
        "mepHvacPipes.pumpHeadCalculation",
        None,
        {"staticHeadM": 6.0, "criticalPathLossM": 21.0, "terminalPressureM": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalDynamicHeadM"] == pytest.approx(31.0, rel=0.01)


def test_mep_hvac_pipes_system_curve_overlay() -> None:
    # k = H / Q^2 = 25 / 5^2 = 1.0 m/(L/s)^2. At maxFlow = 8 L/s (last row): H = 1.0 * 64 = 64 m.
    res = features.run(
        "mepHvacPipes.systemCurveOverlay",
        None,
        {"designFlowLs": 5.0, "designHeadM": 25.0, "maximumFlowLs": 8.0},
    )
    assert res["problems"] == []
    assert res["summary"]["systemCurveCoefficient"] == pytest.approx(1.0, rel=0.01)
    assert res["tables"][0]["rows"][-1]["headM"] == pytest.approx(64.0, rel=0.01)


def test_mep_hvac_pipes_thermal_expansion_loop() -> None:
    # 40 m * 60 C * 1.2e-5 /C * 1000 = 28.8 mm.
    res = features.run(
        "mepHvacPipes.thermalExpansionLoop",
        None,
        {"runLengthM": 40.0, "temperatureRiseC": 60.0, "expansionCoefficientPerC": 1.2e-5},
    )
    assert res["problems"] == []
    assert res["summary"]["freeExpansionMm"] == pytest.approx(28.8, rel=0.01)


def test_mep_hvac_pipes_valve_insert() -> None:
    # Q = 2.5 L/s = 9.0 m3/h; Kv = 18.0 -> dP = (9/18)^2 * 100 kPa = 25.0 kPa.
    res = features.run(
        "mepHvacPipes.valveInsert",
        None,
        {"flowLs": 2.5, "valveKv": 18.0},
    )
    assert res["problems"] == []
    assert res["summary"]["valvePressureDropKpa"] == pytest.approx(25.0, rel=0.01)


def test_mep_hvac_pipes_vapour_barrier() -> None:
    # Surface 19 C, dew point 18 C -> margin = 1 C < 2 C safety margin -> barrierRequired True.
    res = features.run(
        "mepHvacPipes.vapourBarrier",
        None,
        {"surfaceTemperatureC": 19.0, "dewPointC": 18.0, "safetyMarginC": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["surfaceDewPointMarginC"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["barrierRequired"] is True


def test_mep_hvac_pipes_variable_speed_drive() -> None:
    # Speed 1200 / 1500 = 0.8 -> flowRatio = 0.8, headRatio = 0.64, powerRatio = 0.512.
    # Power = 10.0 * 0.512 = 5.12 kW.
    res = features.run(
        "mepHvacPipes.variableSpeedDrive",
        None,
        {"designSpeedRpm": 1500.0, "newSpeedRpm": 1200.0, "designPowerKw": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["flowRatio"] == pytest.approx(0.8, rel=0.01)
    assert res["summary"]["headRatio"] == pytest.approx(0.64, rel=0.01)
    assert res["summary"]["powerRatio"] == pytest.approx(0.512, rel=0.01)
    assert res["summary"]["estimatedPowerKw"] == pytest.approx(5.12, rel=0.01)


def test_mep_hvac_pipes_velocity_limit() -> None:
    # Q = 4 L/s = 0.004 m3/s, D = 50 mm -> v = 2.0372 m/s > 1.8 m/s -> pass False.
    expected_v = 0.004 / (math.pi * 0.05**2 / 4.0)
    res = features.run(
        "mepHvacPipes.velocityLimit",
        None,
        {"flowLs": 4.0, "diameterMm": 50.0, "maximumVelocityMs": 1.8},
    )
    assert res["problems"] == []
    assert res["summary"]["velocityMs"] == pytest.approx(expected_v, rel=0.01)
    assert res["summary"]["pass"] is False


# ── MEP HVAC Terminals Extra (mep_hvac_terminals_extra.py: 5) ───────────────────────────────────


def test_mep_hvac_terminals_adpi_calculation() -> None:
    # T50 = 4.0 m, L = 4.0 m -> ratio = 1.0 (off_center = 0);
    # load = 85 W/m2 -> load_pen = (85 - 65) * 0.12 = 2.4 -> ADPI = 93.0 - 0 - 2.4 = 90.6% >= 80%.
    res = features.run(
        "mepHvacTerminals.adpiCalculation",
        None,
        {"throwT50M": 4.0, "characteristicLengthM": 4.0, "coolingLoadWPerM2": 85.0},
    )
    assert res["problems"] == []
    assert res["summary"]["throwRatioT50OverL"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["estimatedAdpiPct"] == pytest.approx(90.6, rel=0.01)
    assert res["summary"]["compliantGe80Pct"] is True


def test_mep_hvac_terminals_noise_level() -> None:
    # catalog = 30 NC, n = 3 -> multi_add = 10 * log10(1 + 0.5*2) = 10*log10(2) = 3.0103 dB.
    # distance = 3.0 m -> dist_adj = -5 * log10(3.0 / 1.5) = -5*log10(2) = -1.5051 dB.
    # predicted = 30 + 3.0103 - 1.5051 = 31.505 NC <= 35 NC -> compliant True.
    expected_nc = 30.0 + 10.0 * math.log10(2.0) - 5.0 * math.log10(2.0)
    res = features.run(
        "mepHvacTerminals.noiseLevel",
        None,
        {
            "catalogNcPerUnit": 30.0,
            "diffuserCount": 3,
            "distanceM": 3.0,
            "roomLimitNc": 35.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["predictedRoomNc"] == pytest.approx(expected_nc, rel=0.01)
    assert res["summary"]["compliant"] is True


def test_mep_hvac_terminals_regenerated_noise() -> None:
    # A = 0.10 m2, dP = 100 Pa, atten = 12 dB:
    # Lw = -4 + 10*log10(0.10) + 25*log10(100) = -4 - 10 + 50 = 36.0 dB.
    # Lp_room = 36.0 - 12.0 - 8.0 = 16.0 dB.
    res = features.run(
        "mepHvacTerminals.regeneratedNoise",
        None,
        {"faceAreaM2": 0.1, "staticDropPa": 100.0, "downstreamAttenDb": 12.0},
    )
    assert res["problems"] == []
    assert res["summary"]["soundPowerLwDb"] == pytest.approx(36.0, rel=0.01)
    assert res["summary"]["estimatedRoomLpDb"] == pytest.approx(16.0, rel=0.01)


def test_mep_hvac_terminals_reheat_coil_calculation() -> None:
    # Q = 200 L/s = 0.2 m3/s, T_ent = 14 C, T_leav = 34 C -> dT_air = 20 K.
    # Q_heat = 1.2 * 1.005 * 0.2 * 20 = 4.824 kW (~4.82).
    # dT_water = 10 K -> m_hw = 4.824 / (4.186 * 10) = 0.11524 L/s (~0.115).
    q_heat = 1.2 * 1.005 * 0.2 * 20.0
    res = features.run(
        "mepHvacTerminals.reheatCoilCalculation",
        None,
        {
            "minAirflowLps": 200.0,
            "enteringAirC": 14.0,
            "leavingAirC": 34.0,
            "waterDeltaTK": 10.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["airDeltaTK"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["reheatDutyKw"] == pytest.approx(q_heat, rel=0.01)
    assert res["summary"]["hotWaterFlowLps"] == pytest.approx(q_heat / (4.186 * 10.0), rel=0.01)


def test_mep_hvac_terminals_vav_box_sizing() -> None:
    # Q_peak = 350 L/s = 0.35 m3/s, v_lim = 10 m/s -> d_min = sqrt(4*0.35/(pi*10))*1000 = 211.1 mm.
    # Next standard collar >= 211.1 mm is 250 mm (A = pi*0.25^2/4 = 0.049087 m2).
    # V_peak = 0.35 / 0.049087 = 7.13 m/s; minRatio = 0.30 -> Q_min = 0.105 m3/s -> V_min = 2.139 m/s >= 1.5 -> True.
    area = math.pi * (0.25 / 2.0) ** 2
    res = features.run(
        "mepHvacTerminals.vavBoxSizing",
        None,
        {"peakAirflowLps": 350.0, "minFlowRatio": 0.3, "maxInletVelMs": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["selectedCollarMm"] == 250
    assert res["summary"]["peakVelocityMs"] == pytest.approx(0.35 / area, rel=0.01)
    assert res["summary"]["minVelocityMs"] == pytest.approx(0.105 / area, rel=0.01)
    assert res["summary"]["turndownSensorOk"] is True


# ── MEP HVAC Controls Extra (mep_hvac_controls_extra.py: 3) ─────────────────────────────────────


def test_mep_hvac_controls_control_deadband() -> None:
    # Heat 20.5 C, Cool 24.5 C -> db = 4.0 K; uncertainty = 0.6 K -> min_rec = max(2.0, 2.4) = 2.4 K.
    # Midpoint = 22.5 C, compliant True.
    res = features.run(
        "mepHvacControls.controlDeadband",
        None,
        {"heatingSetpointC": 20.5, "coolingSetpointC": 24.5, "sensorUncertaintyK": 0.6},
    )
    assert res["problems"] == []
    assert res["summary"]["deadbandK"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["minRecommendedK"] == pytest.approx(2.4, rel=0.01)
    assert res["summary"]["neutralMidpointC"] == pytest.approx(22.5, rel=0.01)
    assert res["summary"]["compliant"] is True


def test_mep_hvac_controls_occupancy_setpoint() -> None:
    # Occ = 24 C, setup = 4 K -> unocc = 28 C; T_out = 34 C -> grad_occ = 10 K, grad_unocc = 6 K.
    # Conduction reduction = (1 - 6/10)*100 = 40.0%.
    # Design OA = 400 L/s, standby ratio = 0.25 -> standby = 100 L/s;
    # Vent saving = 1.2 * 1.005 * (400 - 100)/1000 * 10 = 3.618 kW (~3.62).
    res = features.run(
        "mepHvacControls.occupancySetpoint",
        None,
        {
            "occupiedCoolC": 24.0,
            "unoccupiedSetupK": 4.0,
            "outdoorTempC": 34.0,
            "designFlowLps": 400.0,
            "standbyFlowRatio": 0.25,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["unoccupiedSetpointC"] == pytest.approx(28.0, rel=0.01)
    assert res["summary"]["conductionReductionPct"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["standbyOutdoorAirLps"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["ventilationSavingKw"] == pytest.approx(3.618, rel=0.01)


def test_mep_hvac_controls_pid_tuning() -> None:
    # Kp = 2.0, tau = 50 s, theta = 10 s -> controllability = 10 / 50 = 0.20.
    # PI: Kc = 0.9 * 50 / (2.0 * 10) = 2.25, Ti = 3.33 * 10 = 33.3 s.
    # PID: Kc = 1.2 * 50 / (2.0 * 10) = 3.00, Ti = 2.0 * 10 = 20.0 s, Td = 0.5 * 10 = 5.0 s.
    res = features.run(
        "mepHvacControls.pidTuning",
        None,
        {"processGain": 2.0, "timeConstantS": 50.0, "deadTimeS": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["controllabilityRatio"] == pytest.approx(0.2, rel=0.01)
    assert res["summary"]["piGainKc"] == pytest.approx(2.25, rel=0.01)
    assert res["summary"]["piIntegralTiS"] == pytest.approx(33.3, rel=0.01)
    assert res["summary"]["pidGainKc"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["pidIntegralTiS"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["pidDerivativeTdS"] == pytest.approx(5.0, rel=0.01)

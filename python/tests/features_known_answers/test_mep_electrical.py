"""Independent known-answer tests for standalone calculators in MEP Electrical, Earthing, Lighting, Containment, and Power Systems."""

from __future__ import annotations

import math

import pytest

from saengine import features

# ── MEP Containment (mep_containment_batch.py: 9) ───────────────────────────────────────────────


def test_mep_containment_conduit_bends() -> None:
    # 2*90 + 2*45 = 270 deg <= 360 deg; theta = 1.5*pi rad;
    # capstan = exp(0.35 * 1.5 * pi) = 5.2036 (~5.20); T_out = 0.8 * 5.2036 = 4.16 kN.
    cap = math.exp(0.35 * math.radians(270))
    res = features.run(
        "mepContainment.conduitBends",
        None,
        {"bends90": 2, "bends45": 2, "frictionCoeff": 0.35, "straightTensionKn": 0.8},
    )
    assert res["problems"] == []
    assert res["summary"]["totalAngleDeg"] == 270
    assert res["summary"]["within360DegLimit"] is True
    assert res["summary"]["capstanMultiplier"] == pytest.approx(cap, rel=0.01)
    assert res["summary"]["estimatedPullTensionKn"] == pytest.approx(0.8 * cap, rel=0.01)


def test_mep_containment_conduit_fill() -> None:
    # 4 conductors -> NEC/IEC 40% fill limit; A_cond = pi*12.5^2 = 490.87 mm2;
    # A_wires = 4*pi*3.1^2 = 120.76 mm2 -> 24.6% <= 40%; min ID = 6.2 * sqrt(4/0.4) = 19.61 mm.
    res = features.run(
        "mepContainment.conduitFill",
        None,
        {"conduitIdMm": 25.0, "cableCount": 4, "cableOdMm": 6.2},
    )
    assert res["problems"] == []
    assert res["summary"]["limitPercent"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["fillPercent"] == pytest.approx(24.6, rel=0.01)
    assert res["summary"]["minRequiredIdMm"] == pytest.approx(19.6, rel=0.01)
    assert res["summary"]["compliant"] is True


def test_mep_containment_earth_continuity() -> None:
    # 4.5 kA for 0.4 s with Cu PVC k=115: S_min = 4500 * sqrt(0.4) / 115 = 24.75 mm2;
    # 16 mm2 < 24.75 mm2 -> non-compliant; R2 = 0.0225 * 40 / 16 = 0.05625 ohm.
    s_min = 4500.0 * math.sqrt(0.4) / 115.0
    res = features.run(
        "mepContainment.earthContinuity",
        None,
        {"faultCurrentKa": 4.5, "clearingTimeS": 0.4, "cpcAreaMm2": 16.0, "runLengthM": 40.0},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredMinCpcMm2"] == pytest.approx(s_min, rel=0.01)
    assert res["summary"]["continuityResistanceOhm"] == pytest.approx(0.05625, rel=0.01)
    assert res["summary"]["compliant"] is False


def test_mep_containment_earthing_resistance() -> None:
    # Dwight: L=3 m, a=0.008 m, rho=80 -> R1 = (80/(2*pi*3))*(ln(12/0.008)-1) = 26.787 ohm;
    # 4 rods: eta = 1 - 0.08*2 = 0.84 -> R_total = 26.787 / (4 * 0.84) = 7.972 ohm > 2.0.
    r1 = (80.0 / (2 * math.pi * 3.0)) * (math.log(12.0 / 0.008) - 1.0)
    res = features.run(
        "mepContainment.earthingResistance",
        None,
        {
            "soilResistivityOhmM": 80.0,
            "rodLengthM": 3.0,
            "rodDiameterMm": 16.0,
            "rodCount": 4,
            "targetMaxOhm": 2.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["singleRodOhm"] == pytest.approx(r1, rel=0.01)
    assert res["summary"]["groupingEfficiency"] == pytest.approx(0.84, rel=0.01)
    assert res["summary"]["arrayResistanceOhm"] == pytest.approx(r1 / (4 * 0.84), rel=0.01)
    assert res["summary"]["compliant"] is False


def test_mep_containment_mixed_voltage_check() -> None:
    res = features.run(
        "mepContainment.mixedVoltageCheck",
        None,
        {"highestCircuitV": 400.0, "elvInsulationRatingV": 300.0, "barrierProvidedMm": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["insulationMatch"] is False
    assert res["summary"]["compliant"] is True


def test_mep_containment_segregation_check() -> None:
    # >100 A -> 200 mm base; <=35 m run -> x1.0; screenFactor 0.5 -> req = 100 mm <= 150 mm.
    res = features.run(
        "mepContainment.segregationCheck",
        None,
        {
            "powerCurrentA": 250.0,
            "parallelRunM": 30.0,
            "providedSpacingMm": 150.0,
            "screenFactor": 0.5,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["requiredSeparationMm"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["compliant"] is True


def test_mep_containment_support_spacing() -> None:
    # 20 kg/m -> 0.19613 kN/m * 2.0 m = 0.3923 kN/support; util = 20 / 40 = 0.50;
    # max span = 2.0 * sqrt(2) = 2.83 m.
    res = features.run(
        "mepContainment.supportSpacing",
        None,
        {"cableLoadKgPerM": 20.0, "supportSpanM": 2.0, "trayRatedLoadKgPerM": 40.0},
    )
    assert res["problems"] == []
    assert res["summary"]["hangerLoadKn"] == pytest.approx(20 * 9.80665 / 1000 * 2.0, rel=0.01)
    assert res["summary"]["utilisation"] == pytest.approx(0.50, rel=0.01)
    assert res["summary"]["maxAllowedSpanM"] == pytest.approx(2.83, rel=0.01)
    assert res["summary"]["compliant"] is True


def test_mep_containment_tray_bends() -> None:
    # 35 mm * 12 = 420 mm <= 450 mm -> compliant.
    res = features.run(
        "mepContainment.trayBends",
        None,
        {"largestCableOdMm": 35.0, "minBendMultiplier": 12.0, "trayBendRadiusMm": 450.0},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredBendRadiusMm"] == pytest.approx(420.0, rel=0.01)
    assert res["summary"]["compliant"] is True


def test_mep_containment_tray_fill_check() -> None:
    # 400 x 50 = 20,000 mm2; 6000 / 20000 = 30.0%; spare against 40% limit = 10.0%.
    res = features.run(
        "mepContainment.trayFillCheck",
        None,
        {"trayWidthMm": 400.0, "trayDepthMm": 50.0, "cablesAreaMm2": 6000.0, "maxFillPct": 40.0},
    )
    assert res["problems"] == []
    assert res["summary"]["trayAreaMm2"] == pytest.approx(20000.0, rel=0.01)
    assert res["summary"]["fillPercent"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["spareCapacityPct"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["compliant"] is True


# ── MEP Electrical (mep_electrical.py + mep_electrical_more.py: 13) ─────────────────────────────


def test_mep_electrical_board_layout() -> None:
    # int(600 * 0.75 / 18) = 25 modules/row; 40 breakers * 1 = 40 -> ceil(40/25) = 2 rows = 36 mm <= 800.
    res = features.run(
        "mepElectrical.boardLayout",
        None,
        {
            "boardWidthMm": 600,
            "boardHeightMm": 800,
            "modulePitchMm": 18,
            "usableWidthFraction": 0.75,
            "breakerCount": 40,
            "modulesPerBreaker": 1,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["modulesPerRow"] == 25
    assert res["summary"]["requiredRows"] == 2
    assert res["summary"]["requiredHeightMm"] == pytest.approx(36.0, rel=0.01)
    assert res["summary"]["physicalFit"] is True


def test_mep_electrical_circuit_grouping() -> None:
    # 6 * 15 * 0.8 = 72 A > 60 A capacity -> fails.
    res = features.run(
        "mepElectrical.circuitGrouping",
        None,
        {
            "circuitCount": 6,
            "currentPerCircuitA": 15,
            "simultaneityFactor": 0.8,
            "conduitCapacityA": 60,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["coincidentCurrentA"] == pytest.approx(72.0, rel=0.01)
    assert res["summary"]["capacityPasses"] is False


def test_mep_electrical_circuit_wiring() -> None:
    # I = 4140 W / (230 * 0.9) = 20.0 A.
    res = features.run(
        "mepElectrical.circuitWiring",
        None,
        {
            "circuitId": "L1-02",
            "loadKw": 4.14,
            "voltageV": 230,
            "powerFactor": 0.9,
            "cableLengthM": 20,
            "voltageDropLimitPercent": 3,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["designCurrentA"] == pytest.approx(20.0, rel=0.01)


def test_mep_electrical_demand_factor() -> None:
    # 120 * 0.75 = 90.0 kW; 90 / 0.90 = 100.0 kVA.
    res = features.run(
        "mepElectrical.demandFactor",
        None,
        {"connectedLoadKw": 120, "demandFactor": 0.75, "powerFactor": 0.9},
    )
    assert res["problems"] == []
    assert res["summary"]["maximumDemandKw"] == pytest.approx(90.0, rel=0.01)
    assert res["summary"]["apparentDemandKva"] == pytest.approx(100.0, rel=0.01)


def test_mep_electrical_distribution_board() -> None:
    res = features.run("mepElectrical.distributionBoard", None, {"ways": 18, "incomer": 160})
    assert res["problems"] == []
    assert res["summary"]["ways"] == 18
    assert res["summary"]["incomerA"] == pytest.approx(160.0, rel=0.01)


def test_mep_electrical_diversity_load() -> None:
    # (30 + 50)*0.75 + 60*0.90 + 20 = 60 + 54 + 20 = 134 kW.
    res = features.run(
        "mepElectrical.diversityLoad",
        None,
        {
            "lightingLoadKw": 30,
            "powerLoadKw": 50,
            "hvacLoadKw": 60,
            "essentialLoadKw": 20,
            "generalDiversity": 0.75,
            "hvacDiversity": 0.9,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["generalDemandKw"] == pytest.approx(60.0, rel=0.01)
    assert res["summary"]["hvacDemandKw"] == pytest.approx(54.0, rel=0.01)
    assert res["summary"]["diversifiedDemandKw"] == pytest.approx(134.0, rel=0.01)


def test_mep_electrical_electrical_notes() -> None:
    res = features.run(
        "mepElectrical.electricalNotes",
        None,
        {
            "systemVoltage": "230/400 V",
            "frequencyHz": 50,
            "designAmbientC": 35,
            "earthingArrangement": "TN-C-S",
        },
    )
    assert res["problems"] == []
    assert res["summary"]["noteCount"] == 4


def test_mep_electrical_home_run() -> None:
    # Manhattan (|12-2| + |8-2| = 16) + 4 vertical = 20 m; * 1.15 = 23.0 m.
    res = features.run(
        "mepElectrical.homeRun",
        None,
        {
            "panelXM": 2,
            "panelYM": 2,
            "deviceXM": 12,
            "deviceYM": 8,
            "verticalRiseM": 4,
            "routingAllowancePercent": 15,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["baseRouteLengthM"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["estimatedLengthM"] == pytest.approx(23.0, rel=0.01)


def test_mep_electrical_neutral_sizing() -> None:
    # hypot(12, 5) + 3*7 = 13 + 21 = 34 A <= 40 A -> passes.
    res = features.run(
        "mepElectrical.neutralSizing",
        None,
        {
            "fundamentalNeutralA": 12,
            "thirdHarmonicA": 7,
            "unbalanceA": 5,
            "neutralAmpacityA": 40,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["estimatedNeutralCurrentA"] == pytest.approx(34.0, rel=0.01)
    assert res["summary"]["ampacityMarginA"] == pytest.approx(6.0, rel=0.01)
    assert res["summary"]["passes"] is True


def test_mep_electrical_panel_upgrade() -> None:
    res = features.run("mepElectrical.panelUpgrade", None, {"existing": 100, "required": 160})
    assert res["problems"] == []
    assert res["summary"]["upgradeRequired"] is True
    assert res["summary"]["recommendedA"] == pytest.approx(160.0, rel=0.01)


def test_mep_electrical_place_socket() -> None:
    res = features.run("mepElectrical.placeSocket", None, {"x": 500, "y": 1200, "height": 350})
    assert res["problems"] == []
    assert res["summary"]["xMm"] == pytest.approx(500.0, rel=0.01)
    assert res["summary"]["heightMm"] == pytest.approx(350.0, rel=0.01)


def test_mep_electrical_place_switch() -> None:
    res = features.run("mepElectrical.placeSwitch", None, {"x": 200, "y": 400, "height": 1200})
    assert res["problems"] == []
    assert res["summary"]["heightMm"] == pytest.approx(1200.0, rel=0.01)


def test_mep_electrical_power_factor() -> None:
    # Qc = 100 * (tan(acos(0.8)) - tan(acos(0.96))) = 100 * (0.75 - 0.291667) = 45.833 kvar.
    q_c = 100 * (math.tan(math.acos(0.8)) - math.tan(math.acos(0.96)))
    res = features.run(
        "mepElectrical.powerFactor",
        None,
        {"activePowerKw": 100, "existingPowerFactor": 0.80, "targetPowerFactor": 0.96},
    )
    assert res["problems"] == []
    assert res["summary"]["compensationKvar"] == pytest.approx(q_c, rel=0.01)
    assert res["summary"]["initialApparentKva"] == pytest.approx(125.0, rel=0.01)
    assert res["summary"]["targetApparentKva"] == pytest.approx(104.167, rel=0.01)


# ── MEP Electrical Cable Sizing (mep_electrical_cable_sizing.py + mep_electrical_supply.py: 19) ─


def test_mep_electrical_cable_sizing_ambient_factor() -> None:
    # sqrt((90 - 45) / (90 - 30)) = sqrt(45 / 60) = sqrt(0.75) = 0.8660.
    res = features.run(
        "mepElectricalCableSizing.ambientFactor",
        None,
        {"conductorLimitC": 90, "ambientC": 45, "referenceAmbientC": 30},
    )
    assert res["problems"] == []
    assert res["summary"]["ambientCorrectionFactor"] == pytest.approx(math.sqrt(0.75), rel=0.01)


def test_mep_electrical_cable_sizing_ampacity() -> None:
    # 120 * 0.75 = 90.0 A.
    res = features.run(
        "mepElectricalCableSizing.ampacity",
        None,
        {"size": 25, "factor": 0.75, "base": 120},
    )
    assert res["problems"] == []
    assert res["summary"]["effectiveAmpacityA"] == pytest.approx(90.0, rel=0.01)


def test_mep_electrical_cable_sizing_asymmetrical_peak() -> None:
    # R/X = 0.01 / 0.1 = 0.1; kappa = sqrt(2)*(1.02 + 0.98*exp(-0.3)) = 2.4694; Ip = 24.694 kA.
    k_p = math.sqrt(2) * (1.02 + 0.98 * math.exp(-0.3))
    res = features.run(
        "mepElectricalCableSizing.asymmetricalPeak",
        None,
        {"symmetricalFaultKa": 10, "resistanceOhm": 0.01, "reactanceOhm": 0.1},
    )
    assert res["problems"] == []
    assert res["summary"]["rxRatio"] == pytest.approx(0.1, rel=0.01)
    assert res["summary"]["peakFactor"] == pytest.approx(k_p, rel=0.01)
    assert res["summary"]["peakAsymmetricalKa"] == pytest.approx(10 * k_p, rel=0.01)


def test_mep_electrical_cable_sizing_auto_size() -> None:
    # load=32 A, factor=0.8 -> Iz_req = 40 A, L=30 m, 400 V 3ph -> 6.0 mm2 Cu PVC, Vd = 1.92%.
    res = features.run(
        "mepElectricalCableSizing.autoSize",
        None,
        {"load": 32, "length": 30, "factor": 0.8, "voltage": 400},
    )
    assert res["problems"] == []
    assert res["summary"]["recommendedSizeMm2"] == pytest.approx(6.0, rel=0.01)
    assert res["summary"]["voltageDropPct"] == pytest.approx(1.92, rel=0.01)
    assert res["summary"]["ok"] is True


def test_mep_electrical_cable_sizing_cable_separation() -> None:
    res = features.run(
        "mepElectricalCableSizing.cableSeparation",
        None,
        {
            "serviceA": "power",
            "serviceB": "data",
            "providedSeparationMm": 150,
            "requiredSeparationMm": 100,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["servicePair"] == "power/data"
    assert res["summary"]["passes"] is True


def test_mep_electrical_cable_sizing_calculate_drop() -> None:
    # 25 mm2 Cu PVC 3ph mV/A/m = 1.5; Vd = 1.5 * 40 * 50 / 1000 = 3.0 V -> 0.75% of 400 V.
    res = features.run(
        "mepElectricalCableSizing.calculateDrop",
        None,
        {"size": 25, "current": 40, "length": 50, "voltage": 400, "pf": 0.85, "phases": "3"},
    )
    assert res["problems"] == []
    assert res["summary"]["dropV"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["dropPct"] == pytest.approx(0.75, rel=0.01)


def test_mep_electrical_cable_sizing_conduit_fill_ratio() -> None:
    # 4 * 8^2 / 32^2 = 256 / 1024 = 0.25 (25%) <= 40%.
    res = features.run(
        "mepElectricalCableSizing.conduitFillRatio",
        None,
        {
            "conduitInternalDiameterMm": 32,
            "cableOutsideDiameterMm": 8,
            "cableCount": 4,
            "maximumFillFraction": 0.4,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["fillFraction"] == pytest.approx(0.25, rel=0.01)
    assert res["summary"]["fillPercent"] == pytest.approx(25.0, rel=0.01)
    assert res["summary"]["passes"] is True


def test_mep_electrical_cable_sizing_correction_factor() -> None:
    # 0.9 * 0.8 * 0.75 = 0.54.
    res = features.run(
        "mepElectricalCableSizing.correctionFactor",
        None,
        {"ambient": 0.9, "grouping": 0.8, "thermal": 0.75},
    )
    assert res["problems"] == []
    assert res["summary"]["factor"] == pytest.approx(0.54, rel=0.01)


def test_mep_electrical_cable_sizing_drop_report() -> None:
    res = features.run("mepElectricalCableSizing.dropReport", None, {"drop": 3.2, "limit": 5.0})
    assert res["problems"] == []
    assert res["summary"]["ok"] is True


def test_mep_electrical_cable_sizing_fault_capacity_check() -> None:
    res = features.run(
        "mepElectricalCableSizing.faultCapacityCheck",
        None,
        {"fault": 12, "rating": 15},
    )
    assert res["problems"] == []
    assert res["summary"]["ok"] is True


def test_mep_electrical_cable_sizing_grouping_factor() -> None:
    # 50 * 0.7 = 35.0 A.
    res = features.run(
        "mepElectricalCableSizing.groupingFactor",
        None,
        {"cableCount": 8, "baseAmpacityA": 50, "groupFactor": 0.7},
    )
    assert res["problems"] == []
    assert res["summary"]["correctedAmpacityA"] == pytest.approx(35.0, rel=0.01)


def test_mep_electrical_cable_sizing_i2t_protection_integration() -> None:
    # 8^2 * 0.5 = 32.0 kA2s.
    res = features.run(
        "mepElectricalCableSizing.i2tProtectionIntegration",
        None,
        {"i": 8, "t": 0.5, "i2t": 0},
    )
    assert res["problems"] == []
    assert res["summary"]["i2tKa2s"] == pytest.approx(32.0, rel=0.01)


def test_mep_electrical_cable_sizing_longest_run() -> None:
    # 40 * 1.15 = 46.0 m.
    res = features.run(
        "mepElectricalCableSizing.longestRun",
        None,
        {"length": 40, "allowance": 15},
    )
    assert res["problems"] == []
    assert res["summary"]["designLengthM"] == pytest.approx(46.0, rel=0.01)


def test_mep_electrical_cable_sizing_skin_effect_ratio() -> None:
    # 0.96 / 0.80 = 1.20 (+20%).
    res = features.run(
        "mepElectricalCableSizing.skinEffectRatio",
        None,
        {"acResistanceOhmKm": 0.96, "dcResistanceOhmKm": 0.8, "frequencyHz": 50},
    )
    assert res["problems"] == []
    assert res["summary"]["acDcResistanceRatio"] == pytest.approx(1.2, rel=0.01)
    assert res["summary"]["additionalLossPercent"] == pytest.approx(20.0, rel=0.01)


def test_mep_electrical_cable_sizing_soil_conditions() -> None:
    # sqrt(2.5 / 1.0) = sqrt(2.5) = 1.5811 -> 100 * 1.5811 = 158.11 A.
    f = math.sqrt(2.5)
    res = features.run(
        "mepElectricalCableSizing.soilConditions",
        None,
        {"referenceResistivityKmW": 2.5, "siteResistivityKmW": 1.0, "referenceAmpacityA": 100},
    )
    assert res["problems"] == []
    assert res["summary"]["soilCorrectionFactor"] == pytest.approx(f, rel=0.01)
    assert res["summary"]["correctedAmpacityA"] == pytest.approx(100 * f, rel=0.01)


def test_mep_electrical_cable_sizing_thd_factor() -> None:
    # I1 = 40, I3 = 30, I5 = 0 -> harmonic = 30, THD = 30/40 = 0.75, RMS = hypot(40, 30) = 50 A.
    res = features.run(
        "mepElectricalCableSizing.thdFactor",
        None,
        {"fundamentalCurrentA": 40, "thirdHarmonicA": 30, "fifthHarmonicA": 0, "baseAmpacityA": 60},
    )
    assert res["problems"] == []
    assert res["summary"]["thdFraction"] == pytest.approx(0.75, rel=0.01)
    assert res["summary"]["phaseRmsCurrentA"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["ampacityMarginA"] == pytest.approx(10.0, rel=0.01)


def test_mep_electrical_cable_sizing_thermal_insulation() -> None:
    # 40 * 0.75 = 30 A; 5 / 25 = 0.20.
    res = features.run(
        "mepElectricalCableSizing.thermalInsulation",
        None,
        {
            "baseAmpacityA": 40,
            "insulationDeratingFactor": 0.75,
            "insulatedLengthM": 5,
            "totalLengthM": 25,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["deratedAmpacityA"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["insulatedLengthFraction"] == pytest.approx(0.20, rel=0.01)


def test_mep_electrical_cable_sizing_thermal_withstand() -> None:
    # 11.5 kA, 1.0 s, Cu PVC (k=115) -> S_min = 11500 * 1 / 115 = 100.0 mm2.
    res = features.run(
        "mepElectricalCableSizing.thermalWithstand",
        None,
        {"size": 95, "fault": 11.5, "time": 1.0, "conductor": "Cu", "insulation": "PVC"},
    )
    assert res["problems"] == []
    assert res["summary"]["minimumAdiabaticMm2"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["ok"] is False


def test_mep_electrical_cable_sizing_tray_loading() -> None:
    # 20 * 9.80665 / 1000 = 0.1961 kN/m <= 0.40; reaction over 2 m = 0.3923 kN.
    load = 20 * 9.80665 / 1000
    res = features.run(
        "mepElectricalCableSizing.trayLoading",
        None,
        {
            "cableMassKgPerM": 20,
            "trayWidthM": 0.3,
            "supportSpanM": 2,
            "allowableLineLoadKnM": 0.4,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["cableLineLoadKnM"] == pytest.approx(load, rel=0.01)
    assert res["summary"]["supportReactionKn"] == pytest.approx(2 * load, rel=0.01)
    assert res["summary"]["capacityPasses"] is True


# ── MEP Electrical Earthing (mep_electrical_earthing.py: 22) ────────────────────────────────────


def test_mep_electrical_earthing_air_terminal_grid() -> None:
    # ceil(40/10)+1 = 5 cols, ceil(30/10)+1 = 4 rows -> 20 terminals.
    res = features.run(
        "mepElectricalEarthing.airTerminalGrid",
        None,
        {"roofLengthM": 40, "roofWidthM": 30, "gridSpacingM": 10},
    )
    assert res["problems"] == []
    assert res["summary"]["columns"] == 5
    assert res["summary"]["rows"] == 4
    assert res["summary"]["terminalCountEstimate"] == 20


def test_mep_electrical_earthing_continuity_test() -> None:
    # |0.115 - 0.10| / 0.10 * 100 = 15% <= 20%.
    res = features.run(
        "mepElectricalEarthing.continuityTest",
        None,
        {"measuredOhm": 0.115, "calculatedOhm": 0.10, "tolerancePercent": 20},
    )
    assert res["problems"] == []
    assert res["summary"]["deviationPercent"] == pytest.approx(15.0, rel=0.01)
    assert res["summary"]["pass"] is True


def test_mep_electrical_earthing_cross_bonding() -> None:
    # 100 m / 25 m = 4 intervals -> 3 intermediate bonds.
    res = features.run(
        "mepElectricalEarthing.crossBonding",
        None,
        {"cableLengthM": 100, "bondingIntervalM": 25},
    )
    assert res["problems"] == []
    assert res["summary"]["intermediateBondCount"] == 3


def test_mep_electrical_earthing_down_conductor() -> None:
    # ceil(90 / 20) = 5 conductors * 16 m = 80 m.
    res = features.run(
        "mepElectricalEarthing.downConductor",
        None,
        {"buildingPerimeterM": 90, "maximumSpacingM": 20, "storeyHeightM": 16},
    )
    assert res["problems"] == []
    assert res["summary"]["downConductorCount"] == 5
    assert res["summary"]["estimatedVerticalLengthM"] == pytest.approx(80.0, rel=0.01)


def test_mep_electrical_earthing_earth_fault_current() -> None:
    # 230 / 0.5 = 460 A.
    res = features.run(
        "mepElectricalEarthing.earthFaultCurrent",
        None,
        {"phaseVoltageV": 230, "loopImpedanceOhm": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["prospectiveFaultCurrentA"] == pytest.approx(460.0, rel=0.01)


def test_mep_electrical_earthing_earth_grid() -> None:
    # area = 400 -> side = 20 m; spacing = 5 -> floor(20/5)+1 = 5 lines/dir;
    # L = 2 * 5 * 20 + 80 = 280 m.
    res = features.run(
        "mepElectricalEarthing.earthGrid",
        None,
        {"areaM2": 400, "spacingM": 5, "perimeterM": 80},
    )
    assert res["problems"] == []
    assert res["summary"]["meshCountPerDirection"] == 5
    assert res["summary"]["estimatedConductorLengthM"] == pytest.approx(280.0, rel=0.01)


def test_mep_electrical_earthing_earthing_report() -> None:
    res = features.run(
        "mepElectricalEarthing.earthingReport",
        None,
        {"soilResistivityOhmM": 95, "measuredResistanceOhm": 1.8, "testDate": "2026-05-01"},
    )
    assert res["problems"] == []
    assert res["summary"]["soilResistivityOhmM"] == pytest.approx(95.0, rel=0.01)
    assert res["summary"]["measuredResistanceOhm"] == pytest.approx(1.8, rel=0.01)


def test_mep_electrical_earthing_electrode_resistance() -> None:
    # R1 = 100 / (2*pi*3) * (ln(12/0.016) - 1) = 29.818 ohm; / 4 rods = 7.4545 ohm.
    r1 = (100 / (2 * math.pi * 3)) * (math.log(12 / 0.016) - 1)
    res = features.run(
        "mepElectricalEarthing.electrodeResistance",
        None,
        {
            "resistivityOhmM": 100,
            "electrodeLengthM": 3,
            "electrodeDiameterMm": 16,
            "electrodeCount": 4,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["singleRodOhm"] == pytest.approx(r1, rel=0.01)
    assert res["summary"]["idealParallelGroupOhm"] == pytest.approx(r1 / 4, rel=0.01)


def test_mep_electrical_earthing_gpr_calculation() -> None:
    # 4000 A * 0.5 ohm = 2000 V.
    res = features.run(
        "mepElectricalEarthing.gprCalculation",
        None,
        {"faultCurrentA": 4000, "gridResistanceOhm": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["groundPotentialRiseV"] == pytest.approx(2000.0, rel=0.01)


def test_mep_electrical_earthing_grid_conductor_size() -> None:
    # 5750 * sqrt(0.25) / 115 = 25.0 mm2.
    res = features.run(
        "mepElectricalEarthing.gridConductorSize",
        None,
        {"faultCurrentA": 5750, "clearingTimeS": 0.25, "kFactor": 115},
    )
    assert res["problems"] == []
    assert res["summary"]["minimumAreaMm2"] == pytest.approx(25.0, rel=0.01)


def test_mep_electrical_earthing_loop_impedance() -> None:
    # max = 230 / 460 = 0.50 ohm >= 0.40 ohm -> pass.
    res = features.run(
        "mepElectricalEarthing.loopImpedance",
        None,
        {"phaseVoltageV": 230, "faultCurrentA": 460, "measuredImpedanceOhm": 0.40},
    )
    assert res["problems"] == []
    assert res["summary"]["maximumImpedanceOhm"] == pytest.approx(0.50, rel=0.01)
    assert res["summary"]["pass"] is True


def test_mep_electrical_earthing_main_bonding() -> None:
    # 2300 * sqrt(0.25) / 115 = 10.0 mm2 <= 16.0 mm2 -> pass.
    res = features.run(
        "mepElectricalEarthing.mainBonding",
        None,
        {"conductorAreaMm2": 16, "faultCurrentA": 2300, "clearingTimeS": 0.25, "kFactor": 115},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredAreaMm2"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["thermalCheckPass"] is True


def test_mep_electrical_earthing_mesh_voltage() -> None:
    # 100 * 2000 * 0.7 / 200 = 700 V.
    res = features.run(
        "mepElectricalEarthing.meshVoltage",
        None,
        {"soilResistivityOhmM": 100, "gridCurrentA": 2000, "meshFactor": 0.7, "gridLengthM": 200},
    )
    assert res["problems"] == []
    assert res["summary"]["estimatedMeshVoltageV"] == pytest.approx(700.0, rel=0.01)


def test_mep_electrical_earthing_moisture_factor() -> None:
    # 200 * 0.65 = 130 ohm*m.
    res = features.run(
        "mepElectricalEarthing.moistureFactor",
        None,
        {"dryResistivityOhmM": 200, "wetSeasonFactor": 0.65},
    )
    assert res["problems"] == []
    assert res["summary"]["wetSeasonResistivityOhmM"] == pytest.approx(130.0, rel=0.01)


def test_mep_electrical_earthing_multi_layer_soil() -> None:
    # 100*(1 - exp(-0.5)) + 300*exp(-0.5) = 39.347 + 181.959 = 221.306 ohm*m.
    eff = 100 * (1 - math.exp(-0.5)) + 300 * math.exp(-0.5)
    res = features.run(
        "mepElectricalEarthing.multiLayerSoil",
        None,
        {"upperLayerOhmM": 100, "upperDepthM": 2, "lowerLayerOhmM": 300},
    )
    assert res["problems"] == []
    assert res["summary"]["effectiveResistivityOhmM"] == pytest.approx(eff, rel=0.01)


def test_mep_electrical_earthing_plate_electrode() -> None:
    # A = 0.6 * 0.6 = 0.36 -> r = sqrt(0.36/pi) = 0.3385 m; R = 100/(4*r)*(1 + r/(1+r)) = 92.51 ohm.
    r = math.sqrt(0.36 / math.pi)
    r_ohm = 100 / (4 * r) * (1 + r / (1 + r))
    res = features.run(
        "mepElectricalEarthing.plateElectrode",
        None,
        {"resistivityOhmM": 100, "widthM": 0.6, "heightM": 0.6, "burialM": 1.0},
    )
    assert res["problems"] == []
    assert res["summary"]["equivalentRadiusM"] == pytest.approx(r, rel=0.01)
    assert res["summary"]["estimatedResistanceOhm"] == pytest.approx(r_ohm, rel=0.01)


def test_mep_electrical_earthing_rod_electrode() -> None:
    # 100 / (2*pi*3) * (ln(12/0.016) - 1) = 29.818 ohm; ratio = 6 / 3 = 2.0.
    r_ohm = 100 / (2 * math.pi * 3) * (math.log(12 / 0.016) - 1)
    res = features.run(
        "mepElectricalEarthing.rodElectrode",
        None,
        {"resistivityOhmM": 100, "lengthM": 3, "diameterM": 0.016, "spacingM": 6},
    )
    assert res["problems"] == []
    assert res["summary"]["electrodeResistanceOhm"] == pytest.approx(r_ohm, rel=0.01)
    assert res["summary"]["spacingToLengthRatio"] == pytest.approx(2.0, rel=0.01)


def test_mep_electrical_earthing_seasonal_variation() -> None:
    # 1 + 0.02*(-15) = 0.70 -> 120 * 0.70 = 84.0 ohm*m.
    res = features.run(
        "mepElectricalEarthing.seasonalVariation",
        None,
        {
            "referenceResistivityOhmM": 120,
            "temperatureCoefficientPerC": 0.02,
            "temperatureChangeC": -15,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["correctionFactor"] == pytest.approx(0.70, rel=0.01)
    assert res["summary"]["correctedResistivityOhmM"] == pytest.approx(84.0, rel=0.01)


def test_mep_electrical_earthing_soil_resistivity_profile() -> None:
    res = features.run(
        "mepElectricalEarthing.soilResistivityProfile",
        None,
        {"resistivityShallowOhmM": 80, "resistivityDeepOhmM": 180, "layerDepthM": 3},
    )
    assert res["problems"] == []
    assert res["summary"]["layerCount"] == 2


def test_mep_electrical_earthing_supplementary_bonding() -> None:
    res = features.run(
        "mepElectricalEarthing.supplementaryBonding",
        None,
        {"measuredResistanceOhm": 0.08, "maximumResistanceOhm": 0.10},
    )
    assert res["problems"] == []
    assert res["summary"]["pass"] is True


def test_mep_electrical_earthing_surge_protection_zone() -> None:
    res = features.run(
        "mepElectricalEarthing.surgeProtectionZone",
        None,
        {"upstreamLevel": 1, "downstreamLevel": 2, "separationM": 12},
    )
    assert res["problems"] == []
    assert res["summary"]["levelsInDescendingOrder"] is True
    assert res["summary"]["separationM"] == pytest.approx(12.0, rel=0.01)


def test_mep_electrical_earthing_touch_voltage() -> None:
    # 300 A * 0.15 ohm = 45.0 V <= 50.0 V -> pass.
    res = features.run(
        "mepElectricalEarthing.touchVoltage",
        None,
        {"faultCurrentA": 300, "earthPathOhm": 0.15, "allowableVoltageV": 50},
    )
    assert res["problems"] == []
    assert res["summary"]["estimatedTouchVoltageV"] == pytest.approx(45.0, rel=0.01)
    assert res["summary"]["pass"] is True


# ── MEP Lighting (mep_lighting.py: 24) ──────────────────────────────────────────────────────────


def test_mep_lighting_daylight_factor() -> None:
    # 250 / 10000 * 100 = 2.5%.
    res = features.run(
        "mepLighting.daylightFactor",
        None,
        {"indoorLux": 250, "exteriorLux": 10000},
    )
    assert res["problems"] == []
    assert res["summary"]["daylightFactorPercent"] == pytest.approx(2.5, rel=0.01)


def test_mep_lighting_daylight_sensors() -> None:
    # (400 - 160) / 400 = 0.60 -> 0.60 * 500 = 300 W.
    res = features.run(
        "mepLighting.daylightSensors",
        None,
        {"targetLux": 400, "daylightLux": 160, "connectedPowerW": 500},
    )
    assert res["problems"] == []
    assert res["summary"]["outputFraction"] == pytest.approx(0.60, rel=0.01)
    assert res["summary"]["estimatedPowerW"] == pytest.approx(300.0, rel=0.01)


def test_mep_lighting_dimmer_zones() -> None:
    # ceil(20 / 6) = 4 zones.
    res = features.run("mepLighting.dimmerZones", None, {"fixtureCount": 20, "zoneCapacity": 6})
    assert res["problems"] == []
    assert res["summary"]["zoneCount"] == 4


def test_mep_lighting_energy_compliance() -> None:
    # 720 W / 90 m2 = 8.0 W/m2 <= 9.0 -> pass.
    res = features.run(
        "mepLighting.energyCompliance",
        None,
        {"connectedPowerW": 720, "floorAreaM2": 90, "limitWPerM2": 9.0},
    )
    assert res["problems"] == []
    assert res["summary"]["powerDensityWPerM2"] == pytest.approx(8.0, rel=0.01)
    assert res["summary"]["pass"] is True


def test_mep_lighting_facade_lighting() -> None:
    # ceil(30 / 6) = 5 fixtures; footprint = 2 * 6 * tan(30 deg) = 12 / sqrt(3) = 6.928 m.
    res = features.run(
        "mepLighting.facadeLighting",
        None,
        {"facadeWidthM": 30, "fixtureSpacingM": 6, "beamAngleDeg": 60},
    )
    assert res["problems"] == []
    assert res["summary"]["fixtureCount"] == 5
    assert res["summary"]["beamFootprintM"] == pytest.approx(
        12 * math.tan(math.radians(30)), rel=0.01
    )


def test_mep_lighting_fixture_maintenance() -> None:
    # 500 * 0.8 = 400 lux maintained, 100 lux loss.
    res = features.run(
        "mepLighting.fixtureMaintenance",
        None,
        {"initialLux": 500, "maintenanceFactor": 0.8},
    )
    assert res["problems"] == []
    assert res["summary"]["maintainedLux"] == pytest.approx(400.0, rel=0.01)
    assert res["summary"]["lossLux"] == pytest.approx(100.0, rel=0.01)


def test_mep_lighting_floodlight_aiming() -> None:
    # mount = 10 m, tilt = 45 deg -> horiz = 10 m, target = 15 m -> offset = 5 m, slant = 10*sqrt(2).
    res = features.run(
        "mepLighting.floodlightAiming",
        None,
        {"mountHeightM": 10, "targetDistanceM": 15, "tiltDeg": 45},
    )
    assert res["problems"] == []
    assert res["summary"]["horizontalAimM"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["targetOffsetM"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["slantDistanceM"] == pytest.approx(10 * math.sqrt(2), rel=0.01)


def test_mep_lighting_lamp_types() -> None:
    res = features.run(
        "mepLighting.lampTypes",
        None,
        {"technology": "LED", "ratedLifeHours": 50000, "wattageW": 28},
    )
    assert res["problems"] == []
    assert res["summary"]["wattageW"] == pytest.approx(28.0, rel=0.01)


def test_mep_lighting_light_fixtures() -> None:
    # ceil(10 / 2.5) = 4 cols, ceil(8 / 2.5) = 4 rows -> 4 * 4 = 16 fixtures.
    res = features.run(
        "mepLighting.lightFixtures",
        None,
        {"roomLengthM": 10, "roomWidthM": 8, "spacingM": 2.5, "fixtureType": "LED panel"},
    )
    assert res["problems"] == []
    assert res["summary"]["fixtureCount"] == 16


def test_mep_lighting_light_output_ratio() -> None:
    # 4200 / 5000 = 0.84.
    res = features.run(
        "mepLighting.lightOutputRatio",
        None,
        {"lampLumens": 5000, "luminaireOutputLumens": 4200},
    )
    assert res["problems"] == []
    assert res["summary"]["lightOutputRatio"] == pytest.approx(0.84, rel=0.01)


def test_mep_lighting_lumen_method() -> None:
    # 100 * 300 / (5000 * 0.60 * 0.80) = 30000 / 2400 = 12.5 -> ceil = 13 luminaires -> 312 lux.
    res = features.run(
        "mepLighting.lumenMethod",
        None,
        {"areaM2": 100, "targetLux": 300, "lumens": 5000, "utilisation": 0.60, "maintenance": 0.80},
    )
    assert res["problems"] == []
    assert res["summary"]["luminaireCount"] == 13
    assert res["summary"]["averageLux"] == pytest.approx(312.0, rel=0.01)


def test_mep_lighting_luminaire_schedule() -> None:
    # 25 * 32 = 800 W.
    res = features.run(
        "mepLighting.luminaireSchedule",
        None,
        {"type": "LED-600", "quantity": 25, "wattageW": 32, "mountingHeightM": 2.8},
    )
    assert res["problems"] == []
    assert res["summary"]["connectedLoadW"] == pytest.approx(800.0, rel=0.01)


def test_mep_lighting_lux_levels() -> None:
    res = features.run("mepLighting.luxLevels", None, {"calculatedLux": 350, "requiredLux": 300})
    assert res["problems"] == []
    assert res["summary"]["marginLux"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["pass"] is True


def test_mep_lighting_mounting_height() -> None:
    # 3.2 - 0.8 = 2.4 m.
    res = features.run("mepLighting.mountingHeight", None, {"mountingM": 3.2, "workplaneM": 0.8})
    assert res["problems"] == []
    assert res["summary"]["heightAboveWorkplaneM"] == pytest.approx(2.4, rel=0.01)


def test_mep_lighting_occupancy_sensors() -> None:
    # ceil(150 / 50) = 3 sensors.
    res = features.run(
        "mepLighting.occupancySensors",
        None,
        {"roomAreaM2": 150, "coveragePerSensorM2": 50, "holdMinutes": 15},
    )
    assert res["problems"] == []
    assert res["summary"]["sensorCount"] == 3


def test_mep_lighting_point_calculation() -> None:
    # 3-4-5 triangle: h=3 m, offset=4 m -> slant r = 5 m, r^3 = 125; E = 1250 * 3 / 125 = 30.0 lux.
    res = features.run(
        "mepLighting.pointCalculation",
        None,
        {"intensityCd": 1250, "heightM": 3.0, "offsetM": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["slantDistanceM"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["directIlluminanceLux"] == pytest.approx(30.0, rel=0.01)


def test_mep_lighting_pole_layout() -> None:
    # (200 - 2*10) / 30 = 180 / 30 = 6 -> 6 + 1 = 7 poles.
    res = features.run(
        "mepLighting.poleLayout",
        None,
        {"roadLengthM": 200, "poleSpacingM": 30, "setbackM": 10},
    )
    assert res["problems"] == []
    assert res["summary"]["poleCount"] == 7


def test_mep_lighting_scene_programming() -> None:
    res = features.run(
        "mepLighting.sceneProgramming",
        None,
        {"sceneName": "AV", "taskLevelPercent": 60, "accentLevelPercent": 30},
    )
    assert res["problems"] == []
    assert res["summary"]["sceneName"] == "AV"
    assert res["summary"]["taskLevelPercent"] == pytest.approx(60.0, rel=0.01)


def test_mep_lighting_sensor_placement() -> None:
    # Area = 100 m2; circle R=4 -> 50.265 m2 -> ceil(100 / 50.265) = 2 sensors.
    res = features.run(
        "mepLighting.sensorPlacement",
        None,
        {"roomLengthM": 10, "roomWidthM": 10, "coverageRadiusM": 4},
    )
    assert res["problems"] == []
    assert res["summary"]["roomAreaM2"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["sensorCountEstimate"] == 2


def test_mep_lighting_sky_glow_limit() -> None:
    # 1000 / 25000 * 100 = 4.0% <= 5.0% -> pass.
    res = features.run(
        "mepLighting.skyGlowLimit",
        None,
        {"upwardFluxLm": 1000, "totalFluxLm": 25000, "limitPercent": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["upwardFluxRatioPercent"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["pass"] is True


def test_mep_lighting_spill_light_check() -> None:
    # 400 cd / (10 m)^2 = 4.0 lux <= 5.0 lux -> pass.
    res = features.run(
        "mepLighting.spillLightCheck",
        None,
        {"intensityCd": 400, "distanceM": 10, "limitLux": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["boundaryIlluminanceLux"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["pass"] is True


def test_mep_lighting_switching_groups() -> None:
    # ceil(14 / 4) = 4 groups.
    res = features.run("mepLighting.switchingGroups", None, {"luminaireCount": 14, "groupSize": 4})
    assert res["problems"] == []
    assert res["summary"]["groupCount"] == 4


def test_mep_lighting_time_scheduling() -> None:
    # 8 h * 250 d * 5 kW = 10,000 kWh/yr over 2000 h.
    res = features.run(
        "mepLighting.timeScheduling",
        None,
        {"occupiedHours": 8, "daysPerYear": 250, "loadKw": 5},
    )
    assert res["problems"] == []
    assert res["summary"]["annualOperatingHours"] == pytest.approx(2000.0, rel=0.01)
    assert res["summary"]["annualEnergyKwh"] == pytest.approx(10000.0, rel=0.01)


def test_mep_lighting_uniformity_check() -> None:
    # 195 / 300 = 0.65 >= 0.60 -> pass.
    res = features.run(
        "mepLighting.uniformityCheck",
        None,
        {"minimumLux": 195, "averageLux": 300, "minimumRatio": 0.60},
    )
    assert res["problems"] == []
    assert res["summary"]["uniformityRatio"] == pytest.approx(0.65, rel=0.01)
    assert res["summary"]["pass"] is True


# ── MEP Low Voltage (mep_low_voltage_extra.py: 3) ───────────────────────────────────────────────


def test_mep_low_voltage_bandwidth_check() -> None:
    # 25 * 16 = 400 Mbps over 1000 Mbps = 40.0% <= 70%; min uplink at 70% = 400/700 = 0.57 Gbps.
    res = features.run(
        "mepLowVoltage.bandwidthCheck",
        None,
        {"endpoints": 25, "perEndpointMbps": 16.0, "uplinkGbps": 1.0, "maxUtilPct": 70.0},
    )
    assert res["problems"] == []
    assert res["summary"]["demandMbps"] == pytest.approx(400.0, rel=0.01)
    assert res["summary"]["uplinkUtilisationPct"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["recommendedUplinkGbps"] == pytest.approx(0.57, rel=0.01)
    assert res["summary"]["compliant"] is True


def test_mep_low_voltage_signal_loss_check() -> None:
    # 0.5 km * 3.0 dB/km = 1.5; 4 pairs * 0.5 = 2.0; 5 splices * 0.1 = 0.5; margin = 1.5 -> 5.5 dB.
    # budget 7.5 - 5.5 = +2.0 dB -> compliant.
    res = features.run(
        "mepLowVoltage.signalLossCheck",
        None,
        {
            "fiberLengthM": 500.0,
            "attenuationDbPerKm": 3.0,
            "connectorPairs": 4,
            "fusionSplices": 5,
            "linkBudgetDb": 7.5,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["linkLossDb"] == pytest.approx(5.5, rel=0.01)
    assert res["summary"]["marginDb"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["compliant"] is True


def test_mep_low_voltage_ups_sizing() -> None:
    # 24 kW at pf=0.80 -> 30.0 kVA required; 15 min at 88% inverter & 240 V DC ->
    # 24000 * 0.25 / 0.88 = 6818.18 VAh / 240 V = 28.41 Ah (~28.4 Ah).
    res = features.run(
        "mepLowVoltage.upsSizing",
        None,
        {"criticalLoadKw": 24.0, "autonomyMin": 15.0, "loadPf": 0.80, "dcBusV": 240.0},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredKva"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["standardFrameKva"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["batteryAh"] == pytest.approx(28.4, rel=0.01)


# ── MEP Power Systems (mep_power_systems_extra.py + mep_power_fire.py: 13) ──────────────────────


def test_mep_power_systems_arc_flash_study() -> None:
    # 20 kW * 0.1 s * 0.25 = 500 J radiated;
    # E at 0.5 m = 500 / (4*pi*0.25) / 1000 = 0.15915 kJ/m2;
    # boundary for 5 kJ/m2 = sqrt(500 / (4*pi*5000)) = 0.08921 m.
    e_rad = 20000.0 * 0.1 * 0.25
    inc_kj = e_rad / (4 * math.pi * 0.5**2) / 1000.0
    b_m = math.sqrt(e_rad / (4 * math.pi * 5000.0))
    res = features.run(
        "mepPowerSystems.arcFlashStudy",
        None,
        {
            "arcPower": 20,
            "duration": 0.1,
            "distance": 0.5,
            "radiantFraction": 0.25,
            "boundaryEnergy": 5,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["radiatedEnergyJ"] == pytest.approx(e_rad, rel=0.01)
    assert res["summary"]["incidentEnergyKjPerM2"] == pytest.approx(inc_kj, rel=0.01)
    assert res["summary"]["screeningBoundaryM"] == pytest.approx(b_m, rel=0.01)


def test_mep_power_systems_cable_derating() -> None:
    # 120 * 0.8 = 96.0 A.
    res = features.run("mepPowerSystems.cableDerating", None, {"base": 120, "factor": 0.8})
    assert res["problems"] == []
    assert res["summary"]["effectiveAmpacityA"] == pytest.approx(96.0, rel=0.01)


def test_mep_power_systems_discrimination() -> None:
    # 160 > 40 * 3 -> selective.
    res = features.run(
        "mepPowerSystems.discrimination",
        None,
        {"upstream": 160, "downstream": 40},
    )
    assert res["problems"] == []
    assert res["summary"]["selective"] is True


def test_mep_power_systems_earth_fault_loop() -> None:
    # zsCmin = 0.95, Type C (m=10) 32 A: Ia = 320 A -> Zs_max = 0.95 * 230 / 320 = 0.6828 ohm;
    # Ik1_min = 0.95 * 230 / 0.45 = 485.56 A -> compliant.
    res = features.run(
        "mepPowerSystems.earthFaultLoop",
        None,
        {"impedance": 0.45, "rating": 32, "voltage": 230},
    )
    assert res["problems"] == []
    assert res["summary"]["maximumImpedanceOhm"] == pytest.approx(0.95 * 230 / 320, rel=0.01)
    assert res["summary"]["prospectiveFaultCurrentA"] == pytest.approx(0.95 * 230 / 0.45, rel=0.01)
    assert res["summary"]["compliant"] is True


def test_mep_power_systems_earthing_grid() -> None:
    # 25 x 20 = 500 m2; ceil(25/5)*ceil(20/5) = 5*4 = 20 nodes.
    res = features.run(
        "mepPowerSystems.earthingGrid",
        None,
        {"length": 25, "width": 20, "spacing": 5},
    )
    assert res["problems"] == []
    assert res["summary"]["gridAreaM2"] == pytest.approx(500.0, rel=0.01)
    assert res["summary"]["nodes"] == 20


def test_mep_power_systems_emergency_lighting() -> None:
    # 100 m2 * 1.5 lux / (250 * 0.35 * 0.8) = 150 / 70 = 2.143 -> 3 luminaires -> 2.10 lux.
    res = features.run(
        "mepPowerSystems.emergencyLighting",
        None,
        {"area": 100, "targetLux": 1.5, "lumens": 250, "utilization": 0.35, "maintenance": 0.8},
    )
    assert res["problems"] == []
    assert res["summary"]["luminaireCount"] == 3
    assert res["summary"]["maintainedLux"] == pytest.approx(2.10, rel=0.01)


def test_mep_power_systems_fuel_storage() -> None:
    # 100 kW * 0.27 L/kWh * 20 h = 540 L net; / (1 - 0.10) = 600 L tank.
    res = features.run(
        "mepPowerSystems.fuelStorage",
        None,
        {"generatorLoad": 100, "specificConsumption": 0.27, "autonomy": 20, "reserve": 10},
    )
    assert res["problems"] == []
    assert res["summary"]["netFuelL"] == pytest.approx(540.0, rel=0.01)
    assert res["summary"]["tankCapacityL"] == pytest.approx(600.0, rel=0.01)


def test_mep_power_systems_generator_sizing() -> None:
    # running = 68 / 0.85 = 80.0 kVA; start inc for 17 kW motor (x3 -> +2*17/0.85 = 40.0 kVA);
    # with 1.15 margin -> (80 + 40) * 1.15 = 138.0 kVA.
    res = features.run(
        "mepPowerSystems.generatorSizing",
        None,
        {
            "essentialLoad": 68,
            "powerFactor": 0.85,
            "largestMotor": 17,
            "startingMultiplier": 3,
            "margin": 1.15,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["runningDemandKva"] == pytest.approx(80.0, rel=0.01)
    assert res["summary"]["startingIncrementKva"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["requiredGeneratorKva"] == pytest.approx(138.0, rel=0.01)


def test_mep_power_systems_lighting_circuits() -> None:
    # 46 * 45 = 2070 W -> I = 2070 / (230 * 0.9) = 10.0 A;
    # usable per 10 A breaker at 0.8 = 8.0 A -> ceil(10 / 8) = 2 circuits -> 23 luminaires/ckt.
    res = features.run(
        "mepPowerSystems.lightingCircuits",
        None,
        {
            "luminaireCount": 46,
            "wattage": 45,
            "voltage": 230,
            "powerFactor": 0.9,
            "rating": 10,
            "utilization": 0.8,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["connectedLoadW"] == pytest.approx(2070.0, rel=0.01)
    assert res["summary"]["designCurrentA"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["circuitCount"] == 2
    assert res["summary"]["luminairesPerCircuit"] == 23


def test_mep_power_systems_load_shedding() -> None:
    # 200 kW * (1 - 0.15) = 170 kW protected available across 3 stages.
    res = features.run(
        "mepPowerSystems.loadShedding",
        None,
        {
            "availablePower": 200,
            "stageOne": 10,
            "stageTwo": 20,
            "stageThree": 35,
            "reserve": 15,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["protectedAvailableKw"] == pytest.approx(170.0, rel=0.01)
    assert res["summary"]["stageCount"] == 3


def test_mep_power_systems_protective_devices() -> None:
    # Standard IEC breaker pool >= 35 A selects 40 A.
    res = features.run("mepPowerSystems.protectiveDevices", None, {"load": 35})
    assert res["problems"] == []
    assert res["summary"]["inA"] == 40


def test_mep_power_systems_surge_protection() -> None:
    res = features.run("mepPowerSystems.surgeProtection", None, {"load": 150, "distance": 45})
    assert res["problems"] == []
    assert res["summary"]["required"] is True
    assert res["summary"]["loadKva"] == pytest.approx(150.0, rel=0.01)


def test_mep_power_systems_transformer_sizing() -> None:
    # 500 kVA * 1.20 = 600 kVA -> next standard transformer >= 600 kVA is 630 kVA (1 unit).
    res = features.run("mepPowerSystems.transformerSizing", None, {"load": 500, "growth": 20})
    assert res["problems"] == []
    assert res["summary"]["requiredKva"] == pytest.approx(600.0, rel=0.01)
    assert res["summary"]["ratingKva"] == pytest.approx(630.0, rel=0.01)
    assert res["summary"]["count"] == 1

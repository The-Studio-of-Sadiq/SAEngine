"""Known-answer tests for Project Settings general tabs (audit, checks, occupancy, overrides, units)."""

import math

import pytest

from saengine import features

# ── settings_audit (2) ──────────────────────────────────────────────────────────────────────────────


def test_settings_audit_archive_policy() -> None:
    # Direct echo of archive age threshold = 120 days.
    res = features.run("settingsAudit.archivePolicy", None, {"archiveAfterDays": 120.0})
    assert res["problems"] == []
    assert res["summary"]["archiveAfterDays"] == pytest.approx(120.0, rel=0.01)


def test_settings_audit_retention_period() -> None:
    # Direct echo of statutory audit retention period = 15 years.
    res = features.run("settingsAudit.retentionPeriod", None, {"retentionYears": 15.0})
    assert res["problems"] == []
    assert res["summary"]["retentionYears"] == pytest.approx(15.0, rel=0.01)


# ── settings_checks (12) ────────────────────────────────────────────────────────────────────────────


def test_settings_checks_analysis_tolerances() -> None:
    # Echo solver displacement, force, and energy tolerances alongside project P-Delta flag.
    res = features.run(
        "settingsChecks.analysisTolerances",
        None,
        {"dispTolMm": 0.02, "forceTolKn": 0.25, "energyTol": 0.001},
    )
    assert res["problems"] == []
    assert res["summary"]["dispTolMm"] == pytest.approx(0.02, rel=0.01)
    assert res["summary"]["forceTolKn"] == pytest.approx(0.25, rel=0.01)
    assert res["summary"]["energyTol"] == pytest.approx(0.001, rel=0.01)


def test_settings_checks_convergence_tolerance() -> None:
    # Implied energy norm = du * df = 0.02 * 0.05 = 0.001; both > strict thresholds (1e-4, 1e-3).
    res = features.run(
        "settingsChecks.convergenceTolerance",
        None,
        {"normDisp": 0.02, "normUnbalance": 0.05},
    )
    assert res["problems"] == []
    assert res["summary"]["impliedEnergyNorm"] == pytest.approx(0.001, rel=0.01)
    assert res["summary"]["strictConvergence"] is False


def test_settings_checks_deflection_limit() -> None:
    # Span = 7200 mm -> L/360 = 20.0 mm live limit, L/240 = 30.0 mm total limit.
    res = features.run("settingsChecks.deflectionLimit", None, {"spanMm": 7200.0})
    assert res["problems"] == []
    assert res["summary"]["floorLiveLimitMm"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["floorTotalLimitMm"] == pytest.approx(30.0, rel=0.01)


def test_settings_checks_iteration_limit() -> None:
    # Total iteration cap = maxIterations * loadSteps = 40 * 12 = 480.
    res = features.run(
        "settingsChecks.iterationLimit",
        None,
        {"maxIterations": 40.0, "loadSteps": 12.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalIterationBudget"] == 480


def test_settings_checks_max_span_ratio() -> None:
    # Yield adjustment factor = 0.4 + fy/700 = 0.4 + 500/700 = 1.114286; check positive ratios.
    res = features.run("settingsChecks.maxSpanRatio", None, {"fyMpa": 500.0})
    assert res["problems"] == []
    fy_fac = 0.4 + 500.0 / 700.0
    assert res["summary"]["fyAdjustmentFactor"] == pytest.approx(fy_fac, rel=0.01)
    assert res["summary"]["beamSimpleRatio"] > 0.0
    assert res["summary"]["slabSimpleRatio"] > 0.0


def test_settings_checks_mesh_defaults() -> None:
    # L/h = 5000/500 = 10.0 (>= 6), h/t = 500/200 = 2.5 (>= 1) -> meshAdequate = True.
    res = features.run(
        "settingsChecks.meshDefaults",
        None,
        {"maxElementSizeMm": 500.0, "typicalSpanMm": 5000.0, "slabThicknessMm": 200.0},
    )
    assert res["problems"] == []
    assert res["summary"]["elementsPerSpan"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["sizeToThickness"] == pytest.approx(2.5, rel=0.01)
    assert res["summary"]["meshAdequate"] is True


def test_settings_checks_min_bar_spacing() -> None:
    # With db = 32 mm, agg = 15 mm: 4/3*agg = 20 mm, beam min >= 32 mm, col min >= 1.5*32 = 48 mm.
    res = features.run(
        "settingsChecks.minBarSpacing",
        None,
        {"barDiameterMm": 32.0, "maxAggregateMm": 15.0},
    )
    assert res["problems"] == []
    assert res["summary"]["beamMinClearMm"] >= 32.0
    assert res["summary"]["columnMinClearMm"] >= 48.0


def test_settings_checks_parallel_solver() -> None:
    # Explicit thread request = 4 overrides auto selection; minimal DOFs >= 72.
    res = features.run("settingsChecks.parallelSolver", None, {"requestedThreads": 4.0})
    assert res["problems"] == []
    assert res["summary"]["threadsUsed"] == 4
    assert res["summary"]["estimatedDofs"] >= 72


def test_settings_checks_residual_reporting() -> None:
    # Relative residual = 0.5 / 5000 = 0.0001 <= 1e-4 -> equilibriumAcceptable = True.
    res = features.run(
        "settingsChecks.residualReporting",
        None,
        {"totalGravityKn": 5000.0, "maxResidualKn": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["relativeResidual"] == pytest.approx(0.0001, rel=0.01)
    assert res["summary"]["equilibriumAcceptable"] is True


def test_settings_checks_slenderness_limit() -> None:
    # RC nonsway threshold = min(40, 34 - 12*(0.25)) = 31.0; sway threshold = 22.0.
    res = features.run("settingsChecks.slendernessLimit", None, {"m1OverM2": 0.25})
    assert res["problems"] == []
    assert res["summary"]["rcSwayLimit"] == pytest.approx(22.0, rel=0.01)
    assert res["summary"]["rcNonswayLimit"] == pytest.approx(31.0, rel=0.01)


def test_settings_checks_stability_limits() -> None:
    # Allowable drift [mm] = seismicDriftLimit * (4.0 * 1000) = seismicDriftLimit * 4000.
    res = features.run("settingsChecks.stabilityLimits", None, {"storeyHeightM": 4.0})
    assert res["problems"] == []
    assert res["summary"]["allowableDriftMm"] == pytest.approx(
        res["summary"]["seismicDriftLimit"] * 4000.0, rel=0.01
    )


def test_settings_checks_warning_threshold() -> None:
    # 0.80 <= 0.90 <= 1.05 -> WARNING status and not blocking.
    res = features.run(
        "settingsChecks.warningThreshold",
        None,
        {"warnRatio": 0.80, "blockRatio": 1.05, "sampleUtil": 0.90},
    )
    assert res["problems"] == []
    assert res["summary"]["sampleStatus"] == "WARNING"
    assert res["summary"]["isBlocking"] is False


# ── settings_occupancy (18) ─────────────────────────────────────────────────────────────────────────


def test_settings_occupancy_assembly_loads() -> None:
    # Effective dynamic crowd load = 5.0 * 1.4 = 7.0 kN/m².
    res = features.run(
        "settingsOccupancy.assemblyLoads",
        None,
        {"staticCrowdKnPerM2": 5.0, "dynamicFactor": 1.4},
    )
    assert res["problems"] == []
    assert res["summary"]["effectiveDynamicKnPerM2"] == pytest.approx(7.0, rel=0.01)


def test_settings_occupancy_concentrated_load() -> None:
    # P = 12 kN on 200x200 mm patch on h = 200 mm slab -> d = 170 mm, bo = 4*(200+170) = 1480 mm.
    # Contact pressure = 12000/40000 = 0.3 MPa; punching = 12000/(1480*170) = 0.047695 MPa.
    res = features.run(
        "settingsOccupancy.concentratedLoad",
        None,
        {"pointLoadKn": 12.0, "patchSizeMm": 200.0, "slabThicknessMm": 200.0},
    )
    assert res["problems"] == []
    assert res["summary"]["contactPressureMpa"] == pytest.approx(0.3, rel=0.01)
    assert res["summary"]["punchingStressMpa"] == pytest.approx(
        12000.0 / (1480.0 * 170.0), rel=0.01
    )


def test_settings_occupancy_corrosion_class() -> None:
    # Resistivity 800 < 1000 -> Severe / Aggressive, 0.050 mm/yr/face * 60 yr = 3.0 mm.
    res = features.run(
        "settingsOccupancy.corrosionClass",
        None,
        {
            "soilResistivityOhmCm": 800.0,
            "chloridePpm": 600.0,
            "sulfatePpm": 500.0,
            "designLifeYears": 60.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["corrosionClass"] == "Severe / Aggressive"
    assert res["summary"]["lossRateMmPerYr"] == pytest.approx(0.05, rel=0.01)
    assert res["summary"]["sacrificialThicknessMm"] == pytest.approx(3.0, rel=0.01)


def test_settings_occupancy_egress_occupancy() -> None:
    # ceil(140/1.4) + ceil(930/9.3) + ceil(279/27.9) = 100 + 100 + 10 = 210 occupants.
    # Stair width = max(1100, 210 * 7.6) = 1596.0 mm.
    res = features.run(
        "settingsOccupancy.egressOccupancy",
        None,
        {"assemblyM2": 140.0, "officeM2": 930.0, "storageM2": 279.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalOccupants"] == 210
    assert res["summary"]["requiredStairWidthMm"] == pytest.approx(1596.0, rel=0.01)


def test_settings_occupancy_fire_rating() -> None:
    # 2 hr rating yields positive minimum slab thickness and column dimension from pack.
    res = features.run("settingsOccupancy.fireRating", None, {"ratingHours": 2.0})
    assert res["problems"] == []
    assert res["summary"]["ratingHours"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["minSlabThicknessMm"] > 0.0
    assert res["summary"]["minColumnSizeMm"] > 0.0


def test_settings_occupancy_fresh_air_demand() -> None:
    # Vbz = 2.5 * 80 + 0.3 * 1000 = 200 + 300 = 500 L/s = 1800 m³/h.
    res = features.run(
        "settingsOccupancy.freshAirDemand",
        None,
        {"floorAreaM2": 1000.0, "occupants": 80.0, "rpLPerSecPerson": 2.5, "raLPerSecM2": 0.3},
    )
    assert res["problems"] == []
    assert res["summary"]["freshAirLPerS"] == pytest.approx(500.0, rel=0.01)
    assert res["summary"]["freshAirM3PerHr"] == pytest.approx(1800.0, rel=0.01)


def test_settings_occupancy_hospital_occupancy() -> None:
    # Essential healthcare checks pack Cat IV seismic importance and imaging equipment load.
    res = features.run(
        "settingsOccupancy.hospitalOccupancy",
        None,
        {"wardAreaM2": 500.0, "imagingEquipmentKn": 80.0},
    )
    assert res["problems"] == []
    assert res["summary"]["imagingLoadKn"] == pytest.approx(80.0, rel=0.01)
    assert res["summary"]["essentialSeismicI"] >= 1.25


def test_settings_occupancy_laboratory_load() -> None:
    # Direct echo of bench UDL and velocity vibration limit.
    res = features.run(
        "settingsOccupancy.laboratoryLoad",
        None,
        {"benchLoadKnPerM2": 4.5, "vibrationLimitMmPerS": 0.025},
    )
    assert res["problems"] == []
    assert res["summary"]["benchLiveKnPerM2"] == pytest.approx(4.5, rel=0.01)
    assert res["summary"]["vibrationLimitMmPerS"] == pytest.approx(0.025, rel=0.01)


def test_settings_occupancy_load_reduction_rule() -> None:
    # Influence area = KLL * At = 4 * 100 = 400 m²; reduced live = 3.0 * factor < 3.0.
    res = features.run(
        "settingsOccupancy.loadReductionRule",
        None,
        {"tributaryAreaM2": 100.0, "floorsSupported": 5.0, "baseLiveKnPerM2": 3.0},
    )
    assert res["problems"] == []
    assert res["summary"]["influenceAreaM2"] >= 200.0
    assert 0.4 <= res["summary"]["reductionFactor"] <= 1.0
    assert res["summary"]["reducedLiveKnPerM2"] == pytest.approx(
        3.0 * res["summary"]["reductionFactor"], rel=0.01
    )


def test_settings_occupancy_mercantile_load() -> None:
    # Total live = pack retail base + 1.5 kN/m²; total force = totalLive * 500 m².
    res = features.run(
        "settingsOccupancy.mercantileLoad",
        None,
        {"retailAreaM2": 500.0, "displayRackAllowanceKnPerM2": 1.5},
    )
    assert res["problems"] == []
    base = res["summary"]["packRetailLiveKnPerM2"]
    assert res["summary"]["totalLiveKnPerM2"] == pytest.approx(base + 1.5, rel=0.01)
    assert res["summary"]["totalForceKn"] == pytest.approx((base + 1.5) * 500.0, rel=0.01)


def test_settings_occupancy_occupant_load() -> None:
    # ceil(930 / 9.3) = 100 occupants; egress width = 100 * 5.0 = 500.0 mm.
    res = features.run(
        "settingsOccupancy.occupantLoad",
        None,
        {"floorAreaM2": 930.0, "areaPerPersonM2": 9.3},
    )
    assert res["problems"] == []
    assert res["summary"]["occupantCount"] == 100
    assert res["summary"]["egressWidthMm"] == pytest.approx(500.0, rel=0.01)


def test_settings_occupancy_parking_load() -> None:
    # Echoes design vehicle gross weight and pulls positive pack garage UDL & wheel load.
    res = features.run(
        "settingsOccupancy.parkingLoad",
        None,
        {"vehicleGrossKn": 25.0, "rampSlopePct": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["vehicleWeightKn"] == pytest.approx(25.0, rel=0.01)
    assert res["summary"]["garageLiveKnPerM2"] > 0.0
    assert res["summary"]["wheelLoadKn"] > 0.0


def test_settings_occupancy_people_density() -> None:
    # 300 / 2.0 = 150 occupants; static = 80 * 9.80665e-3 / 2.0 = 0.392266 kN/m².
    res = features.run(
        "settingsOccupancy.peopleDensity",
        None,
        {"areaM2": 300.0, "m2PerPerson": 2.0, "avgPersonMassKg": 80.0},
    )
    assert res["problems"] == []
    assert res["summary"]["occupants"] == pytest.approx(150.0, rel=0.01)
    assert res["summary"]["staticLoadKnPerM2"] == pytest.approx(80.0 * 9.80665e-3 / 2.0, rel=0.01)


def test_settings_occupancy_roof_live_load() -> None:
    # Reduced roof live = base (1.2) * factor in [0.6, 1.0].
    res = features.run(
        "settingsOccupancy.roofLiveLoad",
        None,
        {"tributaryAreaM2": 30.0, "roofSlopePct": 10.0, "baseRoofLiveKnPerM2": 1.2},
    )
    assert res["problems"] == []
    assert 0.6 <= res["summary"]["reductionFactor"] <= 1.0
    assert res["summary"]["reducedRoofLiveKnPerM2"] == pytest.approx(
        1.2 * res["summary"]["reductionFactor"], rel=0.01
    )


def test_settings_occupancy_seated_occupancy() -> None:
    # 300 seats / 200 m² = 1.5 seats/m²; seat DL = 300*0.4/200 = 0.6; occ LL = 300*0.75/200 = 1.125.
    res = features.run(
        "settingsOccupancy.seatedOccupancy",
        None,
        {"seatCount": 300.0, "hallAreaM2": 200.0, "seatWeightKn": 0.4},
    )
    assert res["problems"] == []
    assert res["summary"]["seatsPerM2"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["seatDeadKnPerM2"] == pytest.approx(0.6, rel=0.01)
    assert res["summary"]["occupantLiveKnPerM2"] == pytest.approx(1.125, rel=0.01)


def test_settings_occupancy_storage_load() -> None:
    # Stack footprint = 8.0 * 3.0 = 24.0 kN/m²; bay average = 24.0 * 0.7 = 16.8 kN/m².
    res = features.run(
        "settingsOccupancy.storageLoad",
        None,
        {"bulkDensityKnPerM3": 8.0, "stackHeightM": 3.0, "aisleUtilization": 0.7},
    )
    assert res["problems"] == []
    assert res["summary"]["stackFootprintKnPerM2"] == pytest.approx(24.0, rel=0.01)
    assert res["summary"]["bayAverageKnPerM2"] == pytest.approx(16.8, rel=0.01)


def test_settings_occupancy_storage_racking() -> None:
    # Bearing = 80000 / 200² = 2.0 MPa; d = 200-40 = 160 mm; bo = 4*(200+160) = 1440 mm.
    # Punching stress = 80000 / (1440 * 160) = 0.34722 MPa.
    res = features.run(
        "settingsOccupancy.storageRacking",
        None,
        {"uprightLoadKn": 80.0, "baseplateWidthMm": 200.0, "slabThicknessMm": 200.0},
    )
    assert res["problems"] == []
    assert res["summary"]["bearingMpa"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["punchingStressMpa"] == pytest.approx(
        80000.0 / (1440.0 * 160.0), rel=0.01
    )


def test_settings_occupancy_ventilation_rate() -> None:
    # Direct echo of Rp and Ra ventilation rates.
    res = features.run(
        "settingsOccupancy.ventilationRate",
        None,
        {"lPerSecPerson": 3.5, "lPerSecM2": 0.4},
    )
    assert res["problems"] == []
    assert res["summary"]["rpLPerSecPerson"] == pytest.approx(3.5, rel=0.01)
    assert res["summary"]["raLPerSecM2"] == pytest.approx(0.4, rel=0.01)


# ── settings_overrides (12) ─────────────────────────────────────────────────────────────────────────


def test_settings_overrides_accidental_combination() -> None:
    # 1.0 D + 1.1 A + 0.4 L.
    res = features.run(
        "settingsOverrides.accidentalCombination",
        None,
        {"psi1Accidental": 0.4, "accidentalFactor": 1.1},
    )
    assert res["problems"] == []
    assert res["summary"]["deadFactor"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["accidentalFactor"] == pytest.approx(1.1, rel=0.01)
    assert res["summary"]["liveCompanionFactor"] == pytest.approx(0.4, rel=0.01)


def test_settings_overrides_combination_factors() -> None:
    # Echoes psi0 = 0.8, psi1 = 0.6, psi2 = 0.4.
    res = features.run(
        "settingsOverrides.combinationFactors",
        None,
        {"psi0": 0.8, "psi1": 0.6, "psi2": 0.4},
    )
    assert res["problems"] == []
    assert res["summary"]["psi0"] == pytest.approx(0.8, rel=0.01)
    assert res["summary"]["psi1"] == pytest.approx(0.6, rel=0.01)
    assert res["summary"]["psi2"] == pytest.approx(0.4, rel=0.01)


def test_settings_overrides_decimal_places() -> None:
    # Echoes configured integer display decimal places.
    res = features.run(
        "settingsOverrides.decimalPlaces",
        None,
        {"lengthDec": 2.0, "forceDec": 2.0, "stressDec": 1.0, "ratioDec": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["lengthDecimals"] == 2
    assert res["summary"]["forceDecimals"] == 2
    assert res["summary"]["stressDecimals"] == 1


def test_settings_overrides_load_factors() -> None:
    # Echoes input factors 1.35 and 1.5 alongside pack strength combinations.
    res = features.run(
        "settingsOverrides.loadFactors",
        None,
        {"deadFactor": 1.35, "liveFactor": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["inputDeadFactor"] == pytest.approx(1.35, rel=0.01)
    assert res["summary"]["inputLiveFactor"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["packStrengthRows"] > 0


def test_settings_overrides_material_factors() -> None:
    # Reads active pack factors.phi entries; default project has 0 persistent overrides.
    res = features.run(
        "settingsOverrides.materialFactors",
        None,
        {"phiFlexureOverride": 0.85, "phiShearOverride": 0.70},
    )
    assert res["problems"] == []
    assert res["summary"]["packFactorCount"] > 0
    assert res["summary"]["projectOverrideCount"] == 0


def test_settings_overrides_rounding_rules() -> None:
    # 12.31 rounded up to nearest 0.05 = 12.35; delta = 0.04.
    res = features.run(
        "settingsOverrides.roundingRules",
        None,
        {"sampleQuantity": 12.31, "step": 0.05, "mode": "up"},
    )
    assert res["problems"] == []
    assert res["summary"]["roundedValue"] == pytest.approx(12.35, rel=0.01)
    assert res["summary"]["delta"] == pytest.approx(0.04, rel=0.01)


def test_settings_overrides_seismic_combination() -> None:
    # Echoes target seismic factor 1.2 and checks pack dead load bounds (upper > lower).
    res = features.run("settingsOverrides.seismicCombination", None, {"seismicFactorOverride": 1.2})
    assert res["problems"] == []
    assert res["summary"]["targetSeismicFactor"] == pytest.approx(1.2, rel=0.01)
    assert res["summary"]["seismicDeadUpper"] > res["summary"]["seismicDeadLower"]


def test_settings_overrides_significant_figures() -> None:
    # 0.00456789 to 3 sig figs -> "0.00457".
    res = features.run(
        "settingsOverrides.significantFigures",
        None,
        {"sigFigs": 3.0, "testValue": 0.00456789},
    )
    assert res["problems"] == []
    assert res["summary"]["significantFigures"] == 3
    assert res["summary"]["formattedValue"] == "0.00457"


def test_settings_overrides_snow_combination() -> None:
    # Echoes snow companion factor = 0.7.
    res = features.run("settingsOverrides.snowCombination", None, {"snowComboFactor": 0.7})
    assert res["problems"] == []
    assert res["summary"]["companionFactor"] == pytest.approx(0.7, rel=0.01)


def test_settings_overrides_tolerance_bands() -> None:
    # nearLimitThreshold = 1.0 - 0.08 = 0.92; comparisonTolerance = 0.02.
    res = features.run(
        "settingsOverrides.toleranceBands",
        None,
        {"nearLimitBandPct": 8.0, "comparisonTolPct": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["nearLimitThreshold"] == pytest.approx(0.92, rel=0.01)
    assert res["summary"]["comparisonTolerance"] == pytest.approx(0.02, rel=0.01)


def test_settings_overrides_wind_combination() -> None:
    # Echoes target wind override factor = 1.5 and lists default project wind combos.
    res = features.run("settingsOverrides.windCombination", None, {"windFactorOverride": 1.5})
    assert res["problems"] == []
    assert res["summary"]["targetOverrideFactor"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["windCombinations"] >= 0


def test_settings_overrides_zero_display_rule() -> None:
    # |0.0004| < 0.001 -> suppressed = True, displayedText = "0".
    res = features.run(
        "settingsOverrides.zeroDisplayRule",
        None,
        {"zeroCutoff": 0.001, "sampleValue": 0.0004},
    )
    assert res["problems"] == []
    assert res["summary"]["suppressed"] is True
    assert res["summary"]["displayedText"] == "0"


# ── settings_units (19) ─────────────────────────────────────────────────────────────────────────────


def test_settings_units_area_units() -> None:
    # 100 m² -> ft² = 100 / 0.3048² = 1076.391 ft², mm² = 1e8.
    res = features.run("settingsUnits.areaUnits", None, {"areaM2": 100.0})
    assert res["problems"] == []
    assert res["summary"]["m2"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["ft2"] == pytest.approx(100.0 / (0.3048**2), rel=0.01)
    assert res["summary"]["mm2"] == pytest.approx(1e8, rel=0.01)


def test_settings_units_currency() -> None:
    # 200,000 USD * 0.92 = 184,000 EUR.
    res = features.run(
        "settingsUnits.currency",
        None,
        {"currencyCode": "EUR", "exchangeRate": 0.92, "sampleCostUsd": 200000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["currency"] == "EUR"
    assert res["summary"]["convertedAmount"] == pytest.approx(184000.0, rel=0.01)


def test_settings_units_density_units() -> None:
    # 2500 kg/m³ -> 2500 * 9.80665e-3 = 24.5166 kN/m³, pcf = 2500 * 0.3048³ / 0.45359237 = 156.070 pcf.
    res = features.run("settingsUnits.densityUnits", None, {"densityKgM3": 2500.0})
    assert res["problems"] == []
    assert res["summary"]["knPerM3"] == pytest.approx(24.5166, rel=0.01)
    assert res["summary"]["pcf"] == pytest.approx(2500.0 * (0.3048**3) / 0.45359237, rel=0.01)


def test_settings_units_dimension_units() -> None:
    # 508 mm = 0.508 m = 20.0 in (since 1 in = 25.4 mm exact).
    res = features.run("settingsUnits.dimensionUnits", None, {"dimensionMm": 508.0})
    assert res["problems"] == []
    assert res["summary"]["m"] == pytest.approx(0.508, rel=0.01)
    assert res["summary"]["inches"] == pytest.approx(20.0, rel=0.01)


def test_settings_units_drawing_scale_units() -> None:
    # 25000 mm model at default planScale 100 -> 250.0 mm plotted.
    res = features.run("settingsUnits.drawingScaleUnits", None, {"modelLengthMm": 25000.0})
    assert res["problems"] == []
    assert res["summary"]["planScale"] == 100
    assert res["summary"]["plottedMm"] == pytest.approx(250.0, rel=0.01)


def test_settings_units_elevation_units() -> None:
    # 30.48 m = 30480 mm = 100.0 ft (exact 1 ft = 0.3048 m).
    res = features.run("settingsUnits.elevationUnits", None, {"elevationM": 30.48})
    assert res["problems"] == []
    assert res["summary"]["elevationMm"] == pytest.approx(30480.0, rel=0.01)
    assert res["summary"]["elevationFt"] == pytest.approx(100.0, rel=0.01)


def test_settings_units_energy_units() -> None:
    # 720 MJ / 3.6 = 200.0 kWh; BTU = 720 * 947.81712 = 682428.33 BTU.
    res = features.run("settingsUnits.energyUnits", None, {"energyMj": 720.0})
    assert res["problems"] == []
    assert res["summary"]["kwh"] == pytest.approx(200.0, rel=0.01)
    assert res["summary"]["btu"] == pytest.approx(720.0 * 947.81712, rel=0.01)


def test_settings_units_import_unit_mapping() -> None:
    # 10.0 ft * 304.8 mm/ft = 3048.0 mm.
    res = features.run(
        "settingsUnits.importUnitMapping",
        None,
        {"incomingUnit": "ft", "sampleCoord": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["scaleToMm"] == pytest.approx(304.8, rel=0.01)
    assert res["summary"]["convertedMm"] == pytest.approx(3048.0, rel=0.01)


def test_settings_units_length_force() -> None:
    # 3.048 m = 10.0 ft; 44.4822 kN = 10.0 kip -> 100.0 kip·ft.
    res = features.run(
        "settingsUnits.lengthForce",
        None,
        {"lengthM": 3.048, "forceKn": 44.482216152605},
    )
    assert res["problems"] == []
    assert res["summary"]["lengthFt"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["forceKip"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["momentKipFt"] == pytest.approx(100.0, rel=0.01)


def test_settings_units_moment_units() -> None:
    # 200 kN·m = 2e8 N·mm; kip·ft = 200000 / (4448.2216 * 0.3048) = 147.5124 kip·ft.
    res = features.run("settingsUnits.momentUnits", None, {"momentKnM": 200.0})
    assert res["problems"] == []
    assert res["summary"]["nMm"] == pytest.approx(2e8, rel=0.01)
    assert res["summary"]["kipFt"] == pytest.approx(200000.0 / (4448.2216152605 * 0.3048), rel=0.01)


def test_settings_units_number_format() -> None:
    # spaceComma style: 9876543.21 -> "9 876 543,21".
    res = features.run(
        "settingsUnits.numberFormat",
        None,
        {"sampleNumber": 9876543.21, "separator": "spaceComma"},
    )
    assert res["problems"] == []
    assert res["summary"]["formatted"] == "9 876 543,21"


def test_settings_units_pressure_units() -> None:
    # 10.0 kPa = 0.01 MPa; psf = 10000 / (4.4482216 / 0.3048²) = 208.854 psf.
    res = features.run("settingsUnits.pressureUnits", None, {"pressureKpa": 10.0})
    assert res["problems"] == []
    assert res["summary"]["mpa"] == pytest.approx(0.01, rel=0.01)
    assert res["summary"]["psf"] == pytest.approx(
        10000.0 / (4.4482216152605 / (0.3048**2)), rel=0.01
    )


def test_settings_units_project_base_point() -> None:
    # Direct echo of base point coordinates.
    res = features.run(
        "settingsUnits.projectBasePoint",
        None,
        {"eastM": 100.0, "northM": 200.0, "elevM": 15.0},
    )
    assert res["problems"] == []
    assert res["summary"]["eastingM"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["northingM"] == pytest.approx(200.0, rel=0.01)
    assert res["summary"]["elevationM"] == pytest.approx(15.0, rel=0.01)


def test_settings_units_rounding_on_convert() -> None:
    # 254.0 mm -> 10.00 in -> 254.0 mm round-trip (exact, error = 0.0 mm).
    res = features.run(
        "settingsUnits.roundingOnConvert",
        None,
        {"siValue": 254.0, "decimals": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["displayInches"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["roundTripMm"] == pytest.approx(254.0, rel=0.01)
    assert res["summary"]["roundTripErrorMm"] == pytest.approx(0.0, abs=1e-6)


def test_settings_units_stress_units() -> None:
    # 40 MPa = 40000 kPa; psi = 40e6 / (4.4482216 / 0.0254²) = 5801.51 psi = 5.80151 ksi.
    res = features.run("settingsUnits.stressUnits", None, {"stressMpa": 40.0})
    assert res["problems"] == []
    assert res["summary"]["kpa"] == pytest.approx(40000.0, rel=0.01)
    assert res["summary"]["ksi"] == pytest.approx(5.80151, rel=0.01)
    assert res["summary"]["psi"] == pytest.approx(5801.51, rel=0.01)


def test_settings_units_survey_point() -> None:
    # 500000 + 25 = 500025 m Easting; 2600000 + 15 = 2600015 m Northing.
    res = features.run(
        "settingsUnits.surveyPoint",
        None,
        {"surveyEastM": 500000.0, "surveyNorthM": 2600000.0, "localX": 25.0, "localY": 15.0},
    )
    assert res["problems"] == []
    assert res["summary"]["surveyEastingM"] == pytest.approx(500025.0, rel=0.01)
    assert res["summary"]["surveyNorthingM"] == pytest.approx(2600015.0, rel=0.01)


def test_settings_units_temperature_units() -> None:
    # 30 °C -> 30*1.8 + 32 = 86 °F, 303.15 K; ΔT = 25 °C -> 25*1.8 = 45 Δ°F.
    res = features.run(
        "settingsUnits.temperatureUnits",
        None,
        {"tempC": 30.0, "deltaTC": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["tempF"] == pytest.approx(86.0, rel=0.01)
    assert res["summary"]["tempK"] == pytest.approx(303.15, rel=0.01)
    assert res["summary"]["deltaTF"] == pytest.approx(45.0, rel=0.01)


def test_settings_units_true_north() -> None:
    # 60° -> cos(60°) = 0.5, sin(60°) = sqrt(3)/2 = 0.866025.
    res = features.run("settingsUnits.trueNorth", None, {"angleDeg": 60.0})
    assert res["problems"] == []
    assert res["summary"]["cosTheta"] == pytest.approx(0.5, rel=0.01)
    assert res["summary"]["sinTheta"] == pytest.approx(math.sqrt(3.0) / 2.0, rel=0.01)


def test_settings_units_volume_units() -> None:
    # 10 m³ = 10 / 0.3048³ = 353.1467 ft³ = 353.1467/27 = 13.0795 yd³.
    res = features.run("settingsUnits.volumeUnits", None, {"volumeM3": 10.0})
    assert res["problems"] == []
    ft3 = 10.0 / (0.3048**3)
    assert res["summary"]["ft3"] == pytest.approx(ft3, rel=0.01)
    assert res["summary"]["yd3"] == pytest.approx(ft3 / 27.0, rel=0.01)

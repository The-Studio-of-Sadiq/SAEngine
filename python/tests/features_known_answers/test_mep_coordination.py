"""Independent known-answer tests for standalone calculators in MEP Coordination, Views, Issues, and Commissioning."""

from __future__ import annotations

import math

import pytest

from saengine import features

# ── MEP Clash (mep_clash.py: 1) ─────────────────────────────────────────────────────────────────


def test_mep_clash_tolerance_settings() -> None:
    res = features.run(
        "mepClash.toleranceSettings",
        None,
        {"tolerance": 3.5, "clearance": 75.0},
    )
    assert res["problems"] == []
    assert res["summary"]["toleranceMm"] == pytest.approx(3.5, rel=0.01)
    assert res["summary"]["clearanceMm"] == pytest.approx(75.0, rel=0.01)


# ── MEP Commissioning (mep_commissioning_batch.py: 4) ─────────────────────────────────────────────


def test_mep_commissioning_air_balance() -> None:
    # q_des = 400 L/s, q_meas = 320 L/s:
    # deviationPct = (320 - 400) / 400 * 100 = -20.0% (outside +-10% tolerance)
    # Fan affinity laws: N_req / N_cur = Q_des / Q_meas = 400 / 320 = 1.25;
    # fanPowerRatio = (1.25)^3 = 1.953125 (~1.95 rounded to 2 dec in code).
    res = features.run(
        "mepCommissioning.airBalance",
        None,
        {"designFlowLps": 400.0, "measuredFlowLps": 320.0, "tolerancePct": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["deviationPct"] == pytest.approx(-20.0, rel=0.01)
    assert res["summary"]["withinTolerance"] is False
    assert res["summary"]["fanSpeedMultiplier"] == pytest.approx(1.25, rel=0.01)
    assert res["summary"]["fanPowerRatio"] == pytest.approx(1.95, rel=0.01)


def test_mep_commissioning_controls_checkout() -> None:
    # spanRange = 50, ref = 20.0, bms = 21.5 -> err = +1.5,
    # % span = 1.5 / 50 * 100 = 3.0% > maxErrorPctSpan (2.0%), zero offset = -1.5.
    res = features.run(
        "mepCommissioning.controlsCheckout",
        None,
        {
            "spanRange": 50.0,
            "referenceValue": 20.0,
            "bmsReading": 21.5,
            "maxErrorPctSpan": 2.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["offsetError"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["errorPctOfSpan"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["recommendedZeroOffset"] == pytest.approx(-1.5, rel=0.01)
    assert res["summary"]["calibrated"] is False


def test_mep_commissioning_energy_verify() -> None:
    # area = 4000 m2, baseline = 600,000 kWh -> 150.0 kWh/m2; measured = 480,000 -> 120.0 kWh/m2;
    # saving = 120,000 kWh -> 20.0%; annual cost saving at $0.15/kWh = $18,000.
    res = features.run(
        "mepCommissioning.energyVerify",
        None,
        {
            "floorAreaM2": 4000.0,
            "baselineKwhPerYr": 600000.0,
            "measuredKwhPerYr": 480000.0,
            "tariffPerKwh": 0.15,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["baselineEuiKwhM2"] == pytest.approx(150.0, rel=0.01)
    assert res["summary"]["measuredEuiKwhM2"] == pytest.approx(120.0, rel=0.01)
    assert res["summary"]["energySavingPct"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["annualCostSaving"] == pytest.approx(18000.0, rel=0.01)


def test_mep_commissioning_performance_verify() -> None:
    # Q = V_dot * rho * c_p * dT = 10.0 L/s * 4.186 kJ/(kg*K) * 6.0 K = 251.16 kW (~251.2)
    # % rated (260 kW) = 251.16 / 260 * 100 = 96.6% (>= 95% -> compliant)
    # COP = 251.16 / 60.0 = 4.186 (~4.19)
    res = features.run(
        "mepCommissioning.performanceVerify",
        None,
        {
            "ratedCoolingKw": 260.0,
            "chwFlowLps": 10.0,
            "chwDeltaTK": 6.0,
            "measuredInputKw": 60.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["measuredCoolingKw"] == pytest.approx(251.16, rel=0.01)
    assert res["summary"]["capacityRatioPct"] == pytest.approx(96.6, rel=0.01)
    assert res["summary"]["fieldCop"] == pytest.approx(4.186, rel=0.01)
    assert res["summary"]["compliant"] is True


# ── MEP Coordination (mep_coordination.py: 3) ───────────────────────────────────────────────────


def test_mep_coordination_clash_tolerance() -> None:
    res = features.run("mepCoordination.clashTolerance", None, {"clearance": 5.0})
    assert res["problems"] == []
    assert res["summary"]["clearanceMm"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["hardToleranceMm"] == pytest.approx(5.0, rel=0.01)


def test_mep_coordination_reserved_void() -> None:
    # 800 mm x 500 mm = 0.40 m2.
    res = features.run(
        "mepCoordination.reservedVoid",
        None,
        {"width": 800.0, "height": 500.0, "purpose": "Spare shaft"},
    )
    assert res["problems"] == []
    assert res["summary"]["widthMm"] == pytest.approx(800.0, rel=0.01)
    assert res["summary"]["heightMm"] == pytest.approx(500.0, rel=0.01)
    assert res["summary"]["areaM2"] == pytest.approx(0.4, rel=0.01)
    assert res["summary"]["purpose"] == "Spare shaft"


def test_mep_coordination_sleeve_rules() -> None:
    res = features.run(
        "mepCoordination.sleeveRules",
        None,
        {"service": "duct", "allowance": 40.0},
    )
    assert res["problems"] == []
    assert res["summary"]["allowanceMm"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["sleeveType"] == "duct"


# ── MEP Coordination Clearances (mep_coordination_clearances.py: 3) ─────────────────────────────


def test_mep_coordination_clearances_insulated_clearance() -> None:
    # bare = 100, insulation = 30 -> insulated OD = 100 + 2*30 = 160 mm;
    # working = 25 -> coordinated envelope = 160 + 2*25 = 210 mm;
    # min sleeve ID = 160 + 25 = 185 mm.
    res = features.run(
        "mepCoordinationClearances.insulatedClearance",
        None,
        {"bareOdMm": 100.0, "insulationMm": 30.0, "workingClearanceMm": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["insulatedOdMm"] == pytest.approx(160.0, rel=0.01)
    assert res["summary"]["coordinatedEnvelopeMm"] == pytest.approx(210.0, rel=0.01)
    assert res["summary"]["minSleeveIdMm"] == pytest.approx(185.0, rel=0.01)


def test_mep_coordination_clearances_min_clearance() -> None:
    # BNBC 2020 Part 8 Table 8.5.14 lookup for GI at DN300 gives supportSpacing = 3500 mm;
    # required clear gap = max(50, 0.025 * 3500) + flange (25) = 87.5 + 25 = 112.5 mm.
    res = features.run(
        "mepCoordinationClearances.minClearance",
        None,
        {
            "material": "GI",
            "diameterMm": 300.0,
            "flangeAllowanceMm": 25.0,
            "providedGapMm": 95.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["supportSpacingMm"] == pytest.approx(3500.0, rel=0.01)
    assert res["summary"]["requiredClearGapMm"] == pytest.approx(112.5, rel=0.01)
    assert res["summary"]["compliant"] is False


def test_mep_coordination_clearances_run_clearance() -> None:
    # plenum = 3500 - 2800 = 700 mm; service depth = 620 mm -> remaining = 80 mm >= 50 mm.
    res = features.run(
        "mepCoordinationClearances.runClearance",
        None,
        {"slabSoffitMm": 3500.0, "ceilingElevationMm": 2800.0, "serviceDepthMm": 620.0},
    )
    assert res["problems"] == []
    assert res["summary"]["plenumDepthMm"] == pytest.approx(700.0, rel=0.01)
    assert res["summary"]["remainingClearanceMm"] == pytest.approx(80.0, rel=0.01)
    assert res["summary"]["compliantGe50Mm"] is True


# ── MEP Coordination Penetrations (mep_coordination_penetrations.py: 15) ────────────────────────


def test_mep_coordination_penetrations_acoustic_seal() -> None:
    # Annular area = pi/4 * (140^2 - 80^2) = pi/4 * (19600 - 6400) = 10367.26 mm2
    # Volume at 50 mm depth = 10367.2557 * 50 / 1e6 = 0.5184 L
    res = features.run(
        "mepCoordinationPenetrations.acousticSeal",
        None,
        {"pipeDiameterMm": 80, "sleeveDiameterMm": 140, "sealDepthMm": 50},
    )
    assert res["problems"] == []
    assert res["summary"]["annularAreaMm2"] == pytest.approx(
        math.pi * (140**2 - 80**2) / 4, rel=0.01
    )
    assert res["summary"]["packingVolumeL"] == pytest.approx(0.5184, rel=0.01)


def test_mep_coordination_penetrations_apply_seal() -> None:
    # Theoretical volume = pi/4 * (160^2 - 100^2) * 40 / 1e6 = 0.49009 L
    # Procurement volume at 80% yield = 0.49009 / 0.80 = 0.61261 L
    theo = math.pi * (160**2 - 100**2) / 4 * 40 / 1e6
    res = features.run(
        "mepCoordinationPenetrations.applySeal",
        None,
        {
            "openingDiameterMm": 160,
            "serviceDiameterMm": 100,
            "sealDepthMm": 40,
            "materialYieldPercent": 80,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["theoreticalVolumeL"] == pytest.approx(theo, rel=0.01)
    assert res["summary"]["procurementVolumeL"] == pytest.approx(theo / 0.80, rel=0.01)


def test_mep_coordination_penetrations_assign_firestop() -> None:
    res = features.run(
        "mepCoordinationPenetrations.assignFirestop",
        None,
        {"systemType": "plastic pipe", "testedSystem": "UL-C-AJ-2010", "ratingMinutes": 120},
    )
    assert res["problems"] == []
    assert res["summary"]["systemType"] == "plastic pipe"
    assert res["summary"]["testedSystem"] == "UL-C-AJ-2010"
    assert res["summary"]["requiredRatingMinutes"] == 120


def test_mep_coordination_penetrations_conflict_check() -> None:
    # Opening at (0, 0) R=0.10 m, embed at (0.30, 0.40) R=0.12 m:
    # center distance = 0.50 m, edge clearance = 0.50 - 0.10 - 0.12 = 0.28 m -> no conflict.
    res = features.run(
        "mepCoordinationPenetrations.conflictCheck",
        None,
        {
            "openingXM": 0.0,
            "openingYM": 0.0,
            "openingRadiusM": 0.10,
            "embedXM": 0.30,
            "embedYM": 0.40,
            "embedRadiusM": 0.12,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["centerSeparationM"] == pytest.approx(0.50, rel=0.01)
    assert res["summary"]["edgeClearanceM"] == pytest.approx(0.28, rel=0.01)
    assert res["summary"]["conflict"] is False


def test_mep_coordination_penetrations_core_hole() -> None:
    # Core OD = 100 + 2*25 = 150 mm; drill depth = 250 mm; area = pi * 150^2 / 4e6 = 0.01767 m2.
    res = features.run(
        "mepCoordinationPenetrations.coreHole",
        None,
        {"pipeDiameterMm": 100, "annularClearanceMm": 25, "hostThicknessMm": 250},
    )
    assert res["problems"] == []
    assert res["summary"]["coreDiameterMm"] == pytest.approx(150.0, rel=0.01)
    assert res["summary"]["drillDepthMm"] == pytest.approx(250.0, rel=0.01)
    assert res["summary"]["coreAreaM2"] == pytest.approx(math.pi * 150**2 / 4e6, rel=0.01)


def test_mep_coordination_penetrations_cut_opening() -> None:
    # width = 400 + 2*50 = 500 mm; height = 300 + 2*50 = 400 mm; area = 0.20 m2.
    res = features.run(
        "mepCoordinationPenetrations.cutOpening",
        None,
        {"serviceWidthMm": 400, "serviceHeightMm": 300, "clearanceMm": 50},
    )
    assert res["problems"] == []
    assert res["summary"]["openingWidthMm"] == pytest.approx(500.0, rel=0.01)
    assert res["summary"]["openingHeightMm"] == pytest.approx(400.0, rel=0.01)
    assert res["summary"]["openingAreaM2"] == pytest.approx(0.20, rel=0.01)


def test_mep_coordination_penetrations_fire_rating() -> None:
    res = features.run(
        "mepCoordinationPenetrations.fireRating",
        None,
        {"hostRatingMinutes": 120, "sealRatingMinutes": 120},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredRatingMinutes"] == 120
    assert res["summary"]["providedRatingMinutes"] == 120
    assert res["summary"]["pass"] is True


def test_mep_coordination_penetrations_lintel_requirement() -> None:
    # 1200 mm > 900 mm -> lintel required; min lintel length = 1200 + 2*150 = 1500 mm.
    res = features.run(
        "mepCoordinationPenetrations.lintelRequirement",
        None,
        {
            "openingWidthMm": 1200,
            "wallThicknessMm": 200,
            "bearingMm": 150,
            "clearSpanLimitMm": 900,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["lintelRequired"] is True
    assert res["summary"]["minimumLintelLengthMm"] == pytest.approx(1500.0, rel=0.01)


def test_mep_coordination_penetrations_place_sleeve() -> None:
    # Sleeve ID = 100 + 2*15 = 130 mm; length = 250 mm.
    res = features.run(
        "mepCoordinationPenetrations.placeSleeve",
        None,
        {"serviceDiameterMm": 100, "radialClearanceMm": 15, "wallThicknessMm": 250},
    )
    assert res["problems"] == []
    assert res["summary"]["sleeveDiameterMm"] == pytest.approx(130.0, rel=0.01)
    assert res["summary"]["sleeveLengthMm"] == pytest.approx(250.0, rel=0.01)


def test_mep_coordination_penetrations_puddle_flange() -> None:
    # radial projection = (300 - 100) / 2 = 100 mm; area = pi * (300^2 - 100^2) / 4e6 = 0.06283 m2.
    res = features.run(
        "mepCoordinationPenetrations.puddleFlange",
        None,
        {"pipeDiameterMm": 100, "flangeDiameterMm": 300, "wallThicknessMm": 250},
    )
    assert res["problems"] == []
    assert res["summary"]["radialProjectionMm"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["grossFlangeAreaM2"] == pytest.approx(
        math.pi * (300**2 - 100**2) / 4e6, rel=0.01
    )


def test_mep_coordination_penetrations_rebar_conflict_check() -> None:
    # barClearanceMm = 110 - 75 - 16/2 = 27 mm >= 25 mm -> no conflict.
    res = features.run(
        "mepCoordinationPenetrations.rebarConflictCheck",
        None,
        {
            "openingRadiusMm": 75,
            "barCenterDistanceMm": 110,
            "barDiameterMm": 16,
            "requiredClearanceMm": 25,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["barClearanceMm"] == pytest.approx(27.0, rel=0.01)
    assert res["summary"]["conflict"] is False


def test_mep_coordination_penetrations_seal_type() -> None:
    res = features.run(
        "mepCoordinationPenetrations.sealType",
        None,
        {"service": "duct", "seal": "intumescent sealant", "annularGapMm": 18},
    )
    assert res["problems"] == []
    assert res["summary"]["service"] == "duct"
    assert res["summary"]["sealApproach"] == "intumescent sealant"
    assert res["summary"]["annularGapMm"] == pytest.approx(18.0, rel=0.01)


def test_mep_coordination_penetrations_sleeve_thickness() -> None:
    # cutLength = 220 + 2*20 = 260 mm; sleeve wall = 3.0 mm.
    res = features.run(
        "mepCoordinationPenetrations.sleeveThickness",
        None,
        {"wallThicknessMm": 220, "sleeveProjectionMm": 20, "sleeveWallMm": 3},
    )
    assert res["problems"] == []
    assert res["summary"]["cutLengthMm"] == pytest.approx(260.0, rel=0.01)
    assert res["summary"]["wallThicknessMm"] == pytest.approx(3.0, rel=0.01)


def test_mep_coordination_penetrations_structural_impact() -> None:
    # openingArea = 500 * 400 / 1e6 = 0.20 m2;
    # removed fraction = (500 * 400) / (250 * 1000) = 200000 / 250000 = 0.80.
    res = features.run(
        "mepCoordinationPenetrations.structuralImpact",
        None,
        {
            "openingWidthMm": 500,
            "openingHeightMm": 400,
            "hostThicknessMm": 250,
            "memberWidthMm": 1000,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["openingAreaM2"] == pytest.approx(0.20, rel=0.01)
    assert res["summary"]["removedAreaFraction"] == pytest.approx(0.80, rel=0.01)


def test_mep_coordination_penetrations_web_hole_limit() -> None:
    # beamDepth = 600 -> limit = 0.25 * 600 = 150 mm; hole = 120 <= 150 -> pass;
    # position = 1.2 >= shearZoneStart = 0.8 -> outsideSupportShearZone = True.
    res = features.run(
        "mepCoordinationPenetrations.webHoleLimit",
        None,
        {
            "beamDepthMm": 600,
            "holeDiameterMm": 120,
            "shearZoneStartM": 0.8,
            "holePositionM": 1.2,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["diameterLimitMm"] == pytest.approx(150.0, rel=0.01)
    assert res["summary"]["diameterPass"] is True
    assert res["summary"]["outsideSupportShearZone"] is True


# ── MEP Coordination Sequencing (mep_coordination_sequencing.py: 3) ─────────────────────────────


def test_mep_coordination_sequencing_access_path_check() -> None:
    # width = 1200 mm, corridor = 1600 mm -> per-side margin = (1600 - 1200)/2 = 200 mm (>= 100 mm);
    # footprint = max(0.8, 2.4 * 1.2) = 2.88 m2;
    # bearing = (1500 * 9.80665 / 1000) / 2.88 = 14.709975 / 2.88 = 5.1076 kN/m2 (~5.11 > 5.0 -> fail).
    res = features.run(
        "mepCoordinationSequencing.accessPathCheck",
        None,
        {
            "equipmentWidthMm": 1200.0,
            "corridorClearWidthMm": 1600.0,
            "equipmentWeightKg": 1500.0,
            "slabLiveLoadKnPerM2": 5.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["sideClearanceMm"] == pytest.approx(200.0, rel=0.01)
    assert res["summary"]["riggingBearingKnM2"] == pytest.approx(5.11, rel=0.01)
    assert res["summary"]["pathClear"] is False


def test_mep_coordination_sequencing_duration() -> None:
    # qty = 200, rate = 25/day, crews = 3 -> 200 / 75 = 2.667 -> ceil = 3 days;
    # man_hours = (200 / 25) * 16 = 128.0 man-h.
    res = features.run(
        "mepCoordinationSequencing.duration",
        None,
        {"quantityUnits": 200.0, "crewProductivityPerDay": 25.0, "crews": 3},
    )
    assert res["problems"] == []
    assert res["summary"]["workingDays"] == 3
    assert res["summary"]["totalManHours"] == pytest.approx(128.0, rel=0.01)
    assert res["summary"]["crews"] == 3


def test_mep_coordination_sequencing_task_lag() -> None:
    # pred = 10 days, overlap = 30% -> ss_lag = round(10 * 0.70) = 7 days;
    # effective offset with 2-day inspection buffer = 9 days.
    res = features.run(
        "mepCoordinationSequencing.taskLag",
        None,
        {"predecessorDurationD": 10, "overlapPct": 30.0, "inspectionBufferD": 2},
    )
    assert res["problems"] == []
    assert res["summary"]["ssLagDays"] == 7
    assert res["summary"]["inspectionBufferDays"] == 2
    assert res["summary"]["effectiveStartOffsetDays"] == 9


# ── MEP Issues (mep_issues.py: 1) ───────────────────────────────────────────────────────────────


def test_mep_issues_bcf_viewpoints() -> None:
    res = features.run(
        "mepIssues.bcfViewpoints",
        None,
        {"viewpoint": "Riser cam 2", "x": 1500.0, "y": -250.0, "z": 3200.0},
    )
    assert res["problems"] == []
    assert res["summary"]["viewpoint"] == "Riser cam 2"
    assert res["summary"]["pointMm"] == pytest.approx([1500.0, -250.0, 3200.0], rel=0.01)


# ── MEP Views (mep_views.py + mep_remaining_views.py: 9) ────────────────────────────────────────


def test_mep_views_clip_box() -> None:
    # width = 8000 - 2000 = 6000 mm, depth = 5000 - 1000 = 4000 mm -> area = 24.0 m2.
    res = features.run(
        "mepViews.clipBox",
        None,
        {"xmin": 2000, "xmax": 8000, "ymin": 1000, "ymax": 5000},
    )
    assert res["problems"] == []
    assert res["summary"]["widthMm"] == pytest.approx(6000.0, rel=0.01)
    assert res["summary"]["depthMm"] == pytest.approx(4000.0, rel=0.01)
    assert res["summary"]["areaM2"] == pytest.approx(24.0, rel=0.01)


def test_mep_views_clip_depth() -> None:
    res = features.run("mepViews.clipDepth", None, {"depth": 4500})
    assert res["problems"] == []
    assert res["summary"]["depthMm"] == pytest.approx(4500.0, rel=0.01)


def test_mep_views_detail_view() -> None:
    res = features.run("mepViews.detailView", None, {"detail": "Chiller header", "scale": 25})
    assert res["problems"] == []
    assert res["summary"]["detail"] == "Chiller header"
    assert res["summary"]["scaleMmPerM"] == pytest.approx(25.0, rel=0.01)


def test_mep_views_elevation_view() -> None:
    res = features.run(
        "mepViews.elevationView",
        None,
        {"direction": "east", "elevation": 4200},
    )
    assert res["problems"] == []
    assert res["summary"]["direction"] == "east"
    assert res["summary"]["elevationMm"] == pytest.approx(4200.0, rel=0.01)


def test_mep_views_section_cut() -> None:
    res = features.run("mepViews.sectionCut", None, {"x": 1200, "y": 3400, "z": 2900})
    assert res["problems"] == []
    assert res["summary"]["pointXmm"] == pytest.approx(1200.0, rel=0.01)
    assert res["summary"]["pointYmm"] == pytest.approx(3400.0, rel=0.01)
    assert res["summary"]["pointZmm"] == pytest.approx(2900.0, rel=0.01)


def test_mep_views_transparency() -> None:
    res = features.run("mepViews.transparency", None, {"percent": 35})
    assert res["problems"] == []
    assert res["summary"]["transparencyPercent"] == pytest.approx(35.0, rel=0.01)
    assert res["summary"]["opacityPercent"] == pytest.approx(65.0, rel=0.01)


def test_mep_views_view_history() -> None:
    res = features.run("mepViews.viewHistory", None, {"limit": 50})
    assert res["problems"] == []
    assert res["summary"]["limit"] == 50


def test_mep_views_view_range() -> None:
    res = features.run("mepViews.viewRange", None, {"bottom": 2400, "top": 4000})
    assert res["problems"] == []
    assert res["summary"]["bottomMm"] == pytest.approx(2400.0, rel=0.01)
    assert res["summary"]["topMm"] == pytest.approx(4000.0, rel=0.01)
    assert res["summary"]["heightMm"] == pytest.approx(1600.0, rel=0.01)


def test_mep_views_walk_to_view() -> None:
    res = features.run("mepViews.walkToView", None, {"x": 500, "y": 1500, "z": 1650})
    assert res["problems"] == []
    assert res["summary"]["xMm"] == pytest.approx(500.0, rel=0.01)
    assert res["summary"]["yMm"] == pytest.approx(1500.0, rel=0.01)
    assert res["summary"]["zMm"] == pytest.approx(1650.0, rel=0.01)

"""Known-answer tests for Project Settings foundation tabs (23+22+22+14 = 81 features)."""

import math

import pytest

from saengine import features

# ── settings_foundation (23) ────────────────────────────────────────────────────────────────────────


def test_settings_foundation_anchorage_rules() -> None:
    # db = 20 mm, fc = 25 MPa, fy = 500 MPa.
    # ld = max(300, 500/(1.1*5)*20*0.5) = 909.0909 mm.
    # ldh = max(150, 160, 0.24*500/5*20) = 480.0 mm.
    res = features.run(
        "settingsFoundation.anchorageRules",
        None,
        {"barDiameterMm": 20.0, "fcMpa": 25.0, "fyMpa": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["straightDevelopmentMm"] == pytest.approx(
        500.0 / (1.1 * 5.0) * 10.0, rel=0.01
    )
    assert res["summary"]["hookDevelopmentMm"] == pytest.approx(480.0, rel=0.01)


def test_settings_foundation_backfill_spec() -> None:
    # Echoes maxLiftMm = 250, maxPiPct = 10, and active settings backfill unit weight.
    res = features.run(
        "settingsFoundation.backfillSpec",
        None,
        {"maxLiftMm": 250.0, "maxPlasticityIndex": 10.0, "unitWeightKnM3": 19.5},
    )
    assert res["problems"] == []
    assert res["summary"]["maxLiftMm"] == pytest.approx(250.0, rel=0.01)
    assert res["summary"]["maxPiPct"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["settingsUnitWeightKnM3"] > 0.0


def test_settings_foundation_blinding_thickness() -> None:
    # Blinding volume = 300 m² * (100/1000) m = 30.0 m³.
    res = features.run(
        "settingsFoundation.blindingThickness",
        None,
        {"thicknessMm": 100.0, "footingAreaM2": 300.0},
    )
    assert res["problems"] == []
    assert res["summary"]["blindingMm"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["volumeM3"] == pytest.approx(30.0, rel=0.01)


def test_settings_foundation_compaction_requirement() -> None:
    # Target dry density = 2000 * 98/100 = 1960 kg/m³.
    res = features.run(
        "settingsFoundation.compactionRequirement",
        None,
        {"proctorPct": 98.0, "maxDryDensityKgM3": 2000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["proctorPct"] == pytest.approx(98.0, rel=0.01)
    assert res["summary"]["targetDryDensityKgM3"] == pytest.approx(1960.0, rel=0.01)


def test_settings_foundation_consolidation_settings() -> None:
    # Double drainage on 8.0 m clay -> Hdr = 4.0 m; U = 50% < 60% -> Tv = (pi/4)*0.5^2 = pi/16.
    # Time = Tv * 4^2 / 2.0 = pi / 2 = 1.5708 yr.
    res = features.run(
        "settingsFoundation.consolidationSettings",
        None,
        {"clayThicknessM": 8.0, "cvM2PerYear": 2.0, "drainage": "double", "targetDegreePct": 50.0},
    )
    assert res["problems"] == []
    tv = (math.pi / 4.0) * 0.25
    assert res["summary"]["drainagePathM"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["timeFactorTv"] == pytest.approx(tv, rel=0.01)
    assert res["summary"]["timeYears"] == pytest.approx(tv * 16.0 / 2.0, rel=0.01)


def test_settings_foundation_contact_stiffness() -> None:
    # Es = 30 MPa = 30,000 kPa, nu = 0.25 -> G = 30000/(2*1.25) = 12,000 kPa.
    # For elementSizeM = 2.0 m: kn = 15,000 kPa/m, kt = 6,000 kPa/m.
    res = features.run(
        "settingsFoundation.contactStiffness",
        None,
        {"soilModulusMpa": 30.0, "poisson": 0.25, "elementSizeM": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["shearModulusKpa"] == pytest.approx(12000.0, rel=0.01)
    assert res["summary"]["normalStiffnessKpaPerM"] == pytest.approx(15000.0, rel=0.01)
    assert res["summary"]["tangentialStiffnessKpaPerM"] == pytest.approx(6000.0, rel=0.01)


def test_settings_foundation_cover_spacing() -> None:
    # Pack default min spacing = 100 mm; minClearMm = 120 mm >= 100 mm -> valid = True.
    res = features.run(
        "settingsFoundation.coverSpacing",
        None,
        {"soilCoverMm": 75.0, "formedCoverMm": 50.0, "minClearMm": 120.0, "maxClearMm": 250.0},
    )
    assert res["problems"] == []
    assert res["summary"]["soilCoverMm"] == pytest.approx(75.0, rel=0.01)
    assert res["summary"]["packMinSpacingMm"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["valid"] is True


def test_settings_foundation_damp_proofing() -> None:
    # Direct echo of membrane thickness = 0.5 mm and sand cushion = 75 mm.
    res = features.run(
        "settingsFoundation.dampProofing",
        None,
        {"membraneThicknessMm": 0.5, "sandBlindingMm": 75.0},
    )
    assert res["problems"] == []
    assert res["summary"]["membraneThicknessMm"] == pytest.approx(0.5, rel=0.01)
    assert res["summary"]["sandCushionMm"] == pytest.approx(75.0, rel=0.01)


def test_settings_foundation_default_bearing() -> None:
    # Without a project soil report, defaults to qa = 150 kPa, overrideActive = False, 0 boreholes.
    res = features.run(
        "settingsFoundation.defaultBearing",
        None,
        {"footingWidthM": 2.5, "foundingDepthM": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["effectiveQaKpa"] == pytest.approx(150.0, rel=0.01)
    assert res["summary"]["overrideActive"] is False
    assert res["summary"]["boreholesChecked"] == 0


def test_settings_foundation_drainage_layer() -> None:
    # Inflow = 4.0 L/min/m (>= 2.0 -> 150 mm collector pipe); req trans = (4.0/60000)*3.0 = 0.0002 m²/s.
    res = features.run(
        "settingsFoundation.drainageLayer",
        None,
        {"wallHeightM": 5.0, "inflowLPerMinPerM": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredTransmissivityM2PerS"] == pytest.approx(0.0002, rel=0.01)
    assert res["summary"]["collectorPipeMm"] == pytest.approx(150.0, rel=0.01)


def test_settings_foundation_excavation_support() -> None:
    # Deep excavation (9.0 m) in softClay selects braced/anchored shoring string.
    res = features.run(
        "settingsFoundation.excavationSupport",
        None,
        {"excavationDepthM": 9.0, "soilKind": "softClay"},
    )
    assert res["problems"] == []
    assert res["summary"]["depthM"] == pytest.approx(9.0, rel=0.01)
    assert isinstance(res["summary"]["recommendedSupport"], str)
    assert len(res["summary"]["recommendedSupport"]) > 0


def test_settings_foundation_footing_defaults() -> None:
    # d = minThickness (500) - bottomCover (75) - 1.5*db (1.5*20=30) = 395.0 mm.
    res = features.run(
        "settingsFoundation.footingDefaults",
        None,
        {"minThicknessMm": 500.0, "bottomCoverMm": 75.0, "barDiaMm": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["effectiveDepthMm"] == pytest.approx(395.0, rel=0.01)
    assert res["summary"]["packSoilCoverMm"] == pytest.approx(75.0, rel=0.01)


def test_settings_foundation_ground_water_default() -> None:
    # GWT = 2.0 m, footing = 2.5 m (> 2.0 -> submerged), basement = 5.0 m -> uplift = 3.0 * 9.81 = 29.43 kPa.
    res = features.run(
        "settingsFoundation.groundWaterDefault",
        None,
        {"gwtDepthM": 2.0, "footingDepthM": 2.5, "basementDepthM": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["footingSubmerged"] is True
    assert res["summary"]["basementUpliftKpa"] == pytest.approx(3.0 * 9.81, rel=0.01)


def test_settings_foundation_hydrostatic_design() -> None:
    # Submerged depth = 2.0 m -> uplift = 19.62 kPa; resisting dead = 25.0 kPa -> FS = 25/19.62 = 1.274 >= 1.15.
    res = features.run(
        "settingsFoundation.hydrostaticDesign",
        None,
        {"submergedDepthM": 2.0, "deadWeightKnPerM2": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["upliftPressureKpa"] == pytest.approx(19.62, rel=0.01)
    assert res["summary"]["flotationSafetyFactor"] == pytest.approx(25.0 / 19.62, rel=0.01)
    assert res["summary"]["adequate"] is True


def test_settings_foundation_interface_elements() -> None:
    # phi = 30°, interfaceFactor = 0.7 -> delta = 21°, mu = tan(21°) = 0.38386, tau = 100 * 0.38386 = 38.386 kPa.
    res = features.run(
        "settingsFoundation.interfaceElements",
        None,
        {"soilPhiDeg": 30.0, "interfaceFactor": 0.7, "normalPressureKpa": 100.0},
    )
    assert res["problems"] == []
    mu = math.tan(math.radians(21.0))
    assert res["summary"]["interfaceFrictionDeg"] == pytest.approx(21.0, rel=0.01)
    assert res["summary"]["frictionCoeff"] == pytest.approx(mu, rel=0.01)
    assert res["summary"]["shearCapacityKpa"] == pytest.approx(100.0 * mu, rel=0.01)


def test_settings_foundation_nonlinear_springs() -> None:
    # Yield settlement = qult / ks * 1000 = 500 / 25000 * 1000 = 20.0 mm; compressionOnly = True.
    res = features.run(
        "settingsFoundation.nonlinearSprings",
        None,
        {"ksKnPerM3": 25000.0, "qultKpa": 500.0, "tensionCutoffKpa": 0.0},
    )
    assert res["problems"] == []
    assert res["summary"]["yieldSettlementMm"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["compressionOnly"] is True


def test_settings_foundation_pile_defaults() -> None:
    # D = 800 mm, spacingRatio = 3.0 -> 2400 mm; edgeOffsetRatio = 1.25 -> 1000 mm.
    res = features.run(
        "settingsFoundation.pileDefaults",
        None,
        {"diameterMm": 800.0, "spacingRatio": 3.0, "edgeOffsetRatio": 1.25},
    )
    assert res["problems"] == []
    assert res["summary"]["minSpacingMm"] == pytest.approx(2400.0, rel=0.01)
    assert res["summary"]["minEdgeMm"] == pytest.approx(1000.0, rel=0.01)


def test_settings_foundation_raft_defaults() -> None:
    # span/t = 5000 / 500 = 10.0; As_face = (pi*20²/4)*(1000/100) = 3141.59 mm²/m.
    # faceRatio = 3141.59 / (1000*500) = 0.006283.
    res = features.run(
        "settingsFoundation.raftDefaults",
        None,
        {"raftThicknessMm": 500.0, "columnSpanM": 5.0, "meshBarMm": 20.0, "meshSpacingMm": 100.0},
    )
    assert res["problems"] == []
    as_face = (math.pi * 400.0 / 4.0) * (1000.0 / 100.0)
    assert res["summary"]["spanToThickness"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["faceSteelMm2PerM"] == pytest.approx(as_face, rel=0.01)
    assert res["summary"]["faceRatio"] == pytest.approx(as_face / 500000.0, rel=0.01)


def test_settings_foundation_soil_spring_default() -> None:
    # qa = 200 kPa, settLimit = 20 mm (0.02 m), FS = 3.0 -> secant = 10,000, bowles = 30,000 kN/m³.
    res = features.run(
        "settingsFoundation.soilSpringDefault",
        None,
        {"qaKpa": 200.0, "settLimitMm": 20.0, "factorOfSafety": 3.0},
    )
    assert res["problems"] == []
    assert res["summary"]["secantKsKnPerM3"] == pytest.approx(10000.0, rel=0.01)
    assert res["summary"]["bowlesKsKnPerM3"] == pytest.approx(30000.0, rel=0.01)


def test_settings_foundation_subgrade_model() -> None:
    # pseudoCoupled multiplies interior Ks by 2.0 at edges -> 30,000 interior, 60,000 edge.
    res = features.run(
        "settingsFoundation.subgradeModel",
        None,
        {"modelType": "pseudoCoupled", "centerKsKnPerM3": 30000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["interiorKsKnPerM3"] == pytest.approx(30000.0, rel=0.01)
    assert res["summary"]["edgeKsKnPerM3"] == pytest.approx(60000.0, rel=0.01)


def test_settings_foundation_sump_allowance() -> None:
    # Area = 4000 m², rate = 0.45 L/m²/hr -> inflow = 1800/3600 = 0.5 L/s, pump = 1.0 L/s.
    # Detention = 60 min (1 hr) -> sumpVolume = max(0.5, 4000*0.45*1/1000) = 1.8 m³.
    res = features.run(
        "settingsFoundation.sumpAllowance",
        None,
        {"basementAreaM2": 4000.0, "seepageRateLPerM2Hr": 0.45, "detentionMin": 60.0},
    )
    assert res["problems"] == []
    assert res["summary"]["inflowLPerS"] == pytest.approx(0.5, rel=0.01)
    assert res["summary"]["sumpVolumeM3"] == pytest.approx(1.8, rel=0.01)
    assert res["summary"]["pumpCapacityLPerS"] == pytest.approx(1.0, rel=0.01)


def test_settings_foundation_waterproofing_system() -> None:
    # Pressure = 4.0 m * 9.81 = 39.24 kPa.
    res = features.run(
        "settingsFoundation.waterproofingSystem",
        None,
        {"hydrostaticHeadM": 4.0, "system": "hdpe"},
    )
    assert res["problems"] == []
    assert res["summary"]["pressureKpa"] == pytest.approx(39.24, rel=0.01)


def test_settings_foundation_working_space() -> None:
    # 3.0 x 2.0 m footing with 500 mm clearance each side -> 4.0 x 3.0 m -> area factor = 12/6 = 2.0.
    res = features.run(
        "settingsFoundation.workingSpace",
        None,
        {"formworkClearanceMm": 500.0, "footingLengthM": 3.0, "footingWidthM": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["excavationLengthM"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["excavationWidthM"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["areaExpansionFactor"] == pytest.approx(2.0, rel=0.01)


# ── settings_foundation_excavation (22) ─────────────────────────────────────────────────────────────


def test_settings_foundation_excavation_alarm_limit() -> None:
    # H = 10 m, maxShare = 0.004 -> red = 40.0 mm, amber = 0.75 * 40 = 30.0 mm.
    res = features.run(
        "settingsFoundationExcavation.alarmLimit",
        None,
        {"excavationDepthM": 10.0, "maxShare": 0.004},
    )
    assert res["problems"] == []
    assert res["summary"]["redLimitMm"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["amberLimitMm"] == pytest.approx(30.0, rel=0.01)


def test_settings_foundation_excavation_apply_slope() -> None:
    # atan(tan(35°) / 1.4) = atan(0.700208 / 1.4) = atan(0.500148) = 26.572 deg.
    res = features.run(
        "settingsFoundationExcavation.applySlope",
        None,
        {"phiDeg": 35.0, "requiredFs": 1.4},
    )
    assert res["problems"] == []
    expected = math.degrees(math.atan(math.tan(math.radians(35.0)) / 1.4))
    assert res["summary"]["maxSafeBatterDeg"] == pytest.approx(expected, rel=0.01)


def test_settings_foundation_excavation_bench_height() -> None:
    # total = 10 m, maxLift = 2.5 m -> 4 lifts of 2.5 m each.
    res = features.run(
        "settingsFoundationExcavation.benchHeight",
        None,
        {"totalDepthM": 10.0, "maxLiftHeightM": 2.5},
    )
    assert res["problems"] == []
    assert res["summary"]["liftCount"] == 4
    assert res["summary"]["benchHeightM"] == pytest.approx(2.5, rel=0.01)


def test_settings_foundation_excavation_bench_width() -> None:
    # 3 benches of 2.0 m width -> total setback = 6.0 m.
    res = features.run(
        "settingsFoundationExcavation.benchWidth",
        None,
        {"benchWidthM": 2.0, "benchCount": 3.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalBenchSetbackM"] == pytest.approx(6.0, rel=0.01)


def test_settings_foundation_excavation_building_load() -> None:
    # Line load q = 100 kN/m, x = 2.0 m, z = 4.0 m -> sigma_h = (4*100/pi)*(4*4)/(4+16)² = 400/pi * 16/400 = 16/pi = 5.09296 kPa.
    res = features.run(
        "settingsFoundationExcavation.buildingLoad",
        None,
        {"footingLineKnPerM": 100.0, "offsetM": 2.0, "depthZ": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["lateralPressureKpa"] == pytest.approx(16.0 / math.pi, rel=0.01)


def test_settings_foundation_excavation_crane_surcharge() -> None:
    # Mat bearing = 400 / 2.5 = 160.0 kPa.
    res = features.run(
        "settingsFoundationExcavation.craneSurcharge",
        None,
        {"outriggerLoadKn": 400.0, "matAreaM2": 2.5},
    )
    assert res["problems"] == []
    assert res["summary"]["matBearingKpa"] == pytest.approx(160.0, rel=0.01)


def test_settings_foundation_excavation_dewatering_method() -> None:
    # Echoes drawdown and k and returns a non-empty dewatering method classification.
    res = features.run(
        "settingsFoundationExcavation.dewateringMethod",
        None,
        {"drawdownM": 5.0, "kMPerS": 1e-4},
    )
    assert res["problems"] == []
    assert res["summary"]["drawdownM"] == pytest.approx(5.0, rel=0.01)
    assert isinstance(res["summary"]["recommendedMethod"], str)


def test_settings_foundation_excavation_discharge_route() -> None:
    # Q = 20 L/s = 0.02 m³/s; d = 0.2 m -> A = pi*0.04/4 = 0.01*pi -> v = 2/pi = 0.6366 m/s.
    # Settling tank = 0.02 * 300 = 6.0 m³.
    res = features.run(
        "settingsFoundationExcavation.dischargeRoute",
        None,
        {"flowRateLPerS": 20.0, "pipeDiameterMm": 200.0},
    )
    assert res["problems"] == []
    assert res["summary"]["velocityMPerS"] == pytest.approx(2.0 / math.pi, rel=0.01)
    assert res["summary"]["settlingTankM3"] == pytest.approx(6.0, rel=0.01)


def test_settings_foundation_excavation_drawdown_target() -> None:
    # Excavation = 7.0 m, freeboard = 0.5 m -> target = 7.5 m; GWT = 2.0 m -> drawdown = 5.5 m.
    res = features.run(
        "settingsFoundationExcavation.drawdownTarget",
        None,
        {"waterDepthM": 2.0, "excavationDepthM": 7.0, "freeboardM": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["targetWaterDepthM"] == pytest.approx(7.5, rel=0.01)
    assert res["summary"]["requiredDrawdownM"] == pytest.approx(5.5, rel=0.01)


def test_settings_foundation_excavation_dynamic_surcharge() -> None:
    # 20.0 kPa * 1.4 = 28.0 kPa.
    res = features.run(
        "settingsFoundationExcavation.dynamicSurcharge",
        None,
        {"staticSurchargeKpa": 20.0, "impactFactor": 1.4},
    )
    assert res["problems"] == []
    assert res["summary"]["factoredDynamicKpa"] == pytest.approx(28.0, rel=0.01)


def test_settings_foundation_excavation_ground_anchor() -> None:
    # Pack groundFactor = 2.0; load = 500 kN, d = 0.2 m, bond = 200 kPa -> Lb = (500*2)/(pi*0.2*200) = 7.9577 m.
    # Down drag at 30° = 500 * sin(30°) = 250.0 kN.
    res = features.run(
        "settingsFoundationExcavation.groundAnchor",
        None,
        {"anchorLoadKn": 500.0, "inclinationDeg": 30.0, "drillDiaMm": 200.0, "groutBondKpa": 200.0},
    )
    assert res["problems"] == []
    assert res["summary"]["groundSafetyFactor"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["bondLengthM"] == pytest.approx(1000.0 / (math.pi * 40.0), rel=0.01)
    assert res["summary"]["verticalDownDragKn"] == pytest.approx(250.0, rel=0.01)


def test_settings_foundation_excavation_inclinometer_layout() -> None:
    # Perimeter = 180 m, spacing = 30 m -> 6 inclinometers; depth = 10*1.5 + 3.0 = 18.0 m.
    res = features.run(
        "settingsFoundationExcavation.inclinometerLayout",
        None,
        {"perimeterM": 180.0, "spacingM": 30.0, "excavationDepthM": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["inclinometerCount"] == 6
    assert res["summary"]["casingDepthM"] == pytest.approx(18.0, rel=0.01)


def test_settings_foundation_excavation_overturning_factor() -> None:
    # Mr/Mo = 540 / 300 = 1.8 >= 1.5 -> passing = True.
    res = features.run(
        "settingsFoundationExcavation.overturningFactor",
        None,
        {"resistingMomentKnM": 540.0, "drivingMomentKnM": 300.0, "minFs": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["overturningFs"] == pytest.approx(1.8, rel=0.01)
    assert res["summary"]["passing"] is True


def test_settings_foundation_excavation_piezometer_target() -> None:
    # Baseline pressure = 5.0 m * 9.81 = 49.05 kPa.
    res = features.run(
        "settingsFoundationExcavation.piezometerTarget",
        None,
        {"aquiferDepthM": 12.0, "baselineHeadM": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["baselinePressureKpa"] == pytest.approx(49.05, rel=0.01)


def test_settings_foundation_excavation_piping_safety() -> None:
    # i_exit = 5.0 / (pi * 4.0) = 0.39789; i_crit = 9.81 / 9.81 = 1.0 -> FS = pi*4/5 = 2.513 >= 2.0 -> safe.
    res = features.run(
        "settingsFoundationExcavation.pipingSafety",
        None,
        {"headDiffM": 5.0, "embedmentM": 4.0, "gammaSubKnM3": 9.81},
    )
    assert res["problems"] == []
    assert res["summary"]["exitGradient"] == pytest.approx(5.0 / (4.0 * math.pi), rel=0.01)
    assert res["summary"]["criticalGradient"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["pipingFs"] == pytest.approx(4.0 * math.pi / 5.0, rel=0.01)
    assert res["summary"]["safe"] is True


def test_settings_foundation_excavation_settlement_marker() -> None:
    # Influence zone = 10.0 * 3.0 = 30.0 m.
    res = features.run(
        "settingsFoundationExcavation.settlementMarker",
        None,
        {"wallHeightM": 10.0, "zoneLimitMultiplier": 3.0},
    )
    assert res["problems"] == []
    assert res["summary"]["influenceZoneM"] == pytest.approx(30.0, rel=0.01)


def test_settings_foundation_excavation_slip_circle() -> None:
    # Taylor FS = (5.52 * 40) / (20 * 6) = 220.8 / 120 = 1.84 >= 1.3 (pack temporary FS) -> passing = True.
    res = features.run(
        "settingsFoundationExcavation.slipCircle",
        None,
        {"heightM": 6.0, "cuKpa": 40.0, "gammaKnM3": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["stabilityFs"] == pytest.approx(1.84, rel=0.01)
    assert res["summary"]["requiredTemporaryFs"] == pytest.approx(1.3, rel=0.01)
    assert res["summary"]["passing"] is True


def test_settings_foundation_excavation_slope_angle() -> None:
    # cutHeight = 6.0 m at 45° -> horizontal setback = 6.0 m, ratio H:V = 1.0.
    res = features.run(
        "settingsFoundationExcavation.slopeAngle",
        None,
        {"cutHeightM": 6.0, "batterAngleDeg": 45.0},
    )
    assert res["problems"] == []
    assert res["summary"]["horizontalSetbackM"] == pytest.approx(6.0, rel=0.01)
    assert res["summary"]["slopeRatioHTo1V"] == pytest.approx(1.0, rel=0.01)


def test_settings_foundation_excavation_strut_spacing() -> None:
    # sh = 5.0 m, sv = 4.0 m -> tributary = 20 m², strutLoad = 20 * 60 = 1200 kN.
    res = features.run(
        "settingsFoundationExcavation.strutSpacing",
        None,
        {"horizontalSpacingM": 5.0, "verticalSpacingM": 4.0, "lateralPressureKpa": 60.0},
    )
    assert res["problems"] == []
    assert res["summary"]["tributaryAreaM2"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["strutLoadKn"] == pytest.approx(1200.0, rel=0.01)


def test_settings_foundation_excavation_traffic_surcharge() -> None:
    # Lateral pressure = 0.35 * 20.0 = 7.0 kPa.
    res = features.run(
        "settingsFoundationExcavation.trafficSurcharge",
        None,
        {"surchargeKpa": 20.0, "ka": 0.35},
    )
    assert res["problems"] == []
    assert res["summary"]["lateralPressureKpa"] == pytest.approx(7.0, rel=0.01)


def test_settings_foundation_excavation_wedge_analysis() -> None:
    # phi = 30° -> wedge = 60°, Ka = tan(30°)² = 1/3, thrust = 0.5*(1/3)*18*6² = 108.0 kN/m.
    res = features.run(
        "settingsFoundationExcavation.wedgeAnalysis",
        None,
        {"heightM": 6.0, "phiDeg": 30.0, "gammaKnM3": 18.0},
    )
    assert res["problems"] == []
    assert res["summary"]["wedgeAngleDeg"] == pytest.approx(60.0, rel=0.01)
    assert res["summary"]["ka"] == pytest.approx(1.0 / 3.0, rel=0.01)
    assert res["summary"]["activeThrustKnPerM"] == pytest.approx(108.0, rel=0.01)


def test_settings_foundation_excavation_wellpoint_spacing() -> None:
    # ceil(150 / 2.0) = 75 wellpoints.
    res = features.run(
        "settingsFoundationExcavation.wellpointSpacing",
        None,
        {"perimeterM": 150.0, "spacingM": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["wellpointCount"] == 75


# ── settings_foundation_piles (22) ──────────────────────────────────────────────────────────────────


def test_settings_foundation_piles_base_capacity() -> None:
    # D = 1.0 m -> Ab = pi/4 = 0.7854 m², qb = 2000 kPa -> Qb = 500*pi = 1570.8 kN.
    res = features.run(
        "settingsFoundationPiles.baseCapacity",
        None,
        {"diameterM": 1.0, "unitEndBearingKpa": 2000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["toeAreaM2"] == pytest.approx(math.pi / 4.0, rel=0.01)
    assert res["summary"]["ultimateBaseKn"] == pytest.approx(500.0 * math.pi, rel=0.01)


def test_settings_foundation_piles_block_failure() -> None:
    # Bg = 4 m, Lg = 5 m, L = 10 m, cu = 50 kPa -> shaft = 2*(4+5)*10*50 = 9000 kN.
    # Nc = min(9, 5*(1 + 0.2*0.8)*(1 + 0.2*2.5)) = min(9, 5*1.16*1.5) = 8.7 -> base = 4*5*8.7*50 = 8700 kN.
    res = features.run(
        "settingsFoundationPiles.blockFailure",
        None,
        {"groupWidthM": 4.0, "groupLengthM": 5.0, "pileLengthM": 10.0, "cuKpa": 50.0},
    )
    assert res["problems"] == []
    assert res["summary"]["blockShaftKn"] == pytest.approx(9000.0, rel=0.01)
    assert res["summary"]["blockBaseKn"] == pytest.approx(8700.0, rel=0.01)
    assert res["summary"]["ultimateBlockKn"] == pytest.approx(17700.0, rel=0.01)


def test_settings_foundation_piles_bored_pile() -> None:
    # D = 800 mm, L = 20 m, fc = 35 MPa -> A = pi*0.4² = 0.50265 m², V = 10.053 m³.
    # Structural limit = 0.30 * 35 * (A*1e6) / 1000 = 5277.88 kN.
    res = features.run(
        "settingsFoundationPiles.boredPile",
        None,
        {"diameterMm": 800.0, "lengthM": 20.0, "fcMpa": 35.0},
    )
    assert res["problems"] == []
    area = math.pi * 0.16
    assert res["summary"]["concreteVolumeM3"] == pytest.approx(area * 20.0, rel=0.01)
    assert res["summary"]["structuralLimitKn"] == pytest.approx(
        0.30 * 35.0 * area * 1000.0, rel=0.01
    )


def test_settings_foundation_piles_capacity_factor() -> None:
    # Pack noLoadTestSafety = 3.0 -> Qult = 1200 + 600 = 1800 kN -> Qa = 600.0 kN.
    res = features.run(
        "settingsFoundationPiles.capacityFactor",
        None,
        {"ultimateShaftKn": 1200.0, "ultimateBaseKn": 600.0},
    )
    assert res["problems"] == []
    assert res["summary"]["safetyFactor"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["ultimateTotalKn"] == pytest.approx(1800.0, rel=0.01)
    assert res["summary"]["allowableKn"] == pytest.approx(600.0, rel=0.01)


def test_settings_foundation_piles_capacity_table() -> None:
    # D = 1.0 m, L = 20 m, fs = 50 kPa, qb = 1000 kPa.
    # Qult = pi*1*20*50 + (pi/4)*1000 = 1250*pi = 3926.99 -> Qa = Qult / 2.5 = 500*pi = 1570.8 kN.
    res = features.run(
        "settingsFoundationPiles.capacityTable",
        None,
        {"diameterM": 1.0, "maxDepthM": 20.0, "meanSkinKpa": 50.0, "toeBearingKpa": 1000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["maxAllowableKn"] == pytest.approx(500.0 * math.pi, rel=0.01)


def test_settings_foundation_piles_driven_pile() -> None:
    # 500 mm square pile, fc = 30 MPa -> perimeter = 2.0 m; capacity = 0.33*30*250000/1000 = 2475.0 kN.
    res = features.run(
        "settingsFoundationPiles.drivenPile",
        None,
        {"widthMm": 500.0, "lengthM": 16.0, "fcMpa": 30.0},
    )
    assert res["problems"] == []
    assert res["summary"]["perimeterM"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["structuralCapacityKn"] == pytest.approx(2475.0, rel=0.01)


def test_settings_foundation_piles_group_efficiency() -> None:
    # Converse-Labarre 2x2 group, D = 500 mm, s = 1500 mm -> theta = atan(1/3) = 18.435 deg.
    # eff = 1 - (18.435/90) * ((1*2 + 1*2)/4) = 1 - 0.20483 = 0.79517 -> effective = 4*0.79517 = 3.1807.
    res = features.run(
        "settingsFoundationPiles.groupEfficiency",
        None,
        {"rows": 2.0, "cols": 2.0, "diameterMm": 500.0, "spacingMm": 1500.0},
    )
    assert res["problems"] == []
    eff = 1.0 - math.degrees(math.atan(1.0 / 3.0)) / 90.0
    assert res["summary"]["pileCount"] == 4
    assert res["summary"]["efficiency"] == pytest.approx(eff, rel=0.01)
    assert res["summary"]["effectivePiles"] == pytest.approx(4.0 * eff, rel=0.01)


def test_settings_foundation_piles_group_settlement() -> None:
    # Bg/D = 3.2/0.8 = 4.0 -> sqrt(4) = 2.0 -> group = 10.0 * 2.0 = 20.0 mm.
    res = features.run(
        "settingsFoundationPiles.groupSettlement",
        None,
        {"singleSettMm": 10.0, "groupWidthM": 3.2, "pileDiaM": 0.8},
    )
    assert res["problems"] == []
    assert res["summary"]["amplificationRatio"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["groupSettlementMm"] == pytest.approx(20.0, rel=0.01)


def test_settings_foundation_piles_high_strain_test() -> None:
    # Target = 2*1000 = 2000 kN; ram = 10 t * 9.80665 = 98.0665 kN -> ratio = 4.903% >= 1.5%.
    res = features.run(
        "settingsFoundationPiles.highStrainTest",
        None,
        {"workingLoadKn": 1000.0, "dropHammerTon": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["targetMobilizationKn"] == pytest.approx(2000.0, rel=0.01)
    assert res["summary"]["ramMassRatioPct"] == pytest.approx(9.80665 / 2.0, rel=0.01)
    assert res["summary"]["adequateHammer"] is True


def test_settings_foundation_piles_integrity_test() -> None:
    # 2*25 m / 4000 m/s * 1000 = 12.5 ms.
    res = features.run(
        "settingsFoundationPiles.integrityTest",
        None,
        {"pileLengthM": 25.0, "waveSpeedMPerS": 4000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["toeReflectionMs"] == pytest.approx(12.5, rel=0.01)


def test_settings_foundation_piles_micropile() -> None:
    # drill=250 mm, casing OD=150 mm, wall=10 mm (ID=130 mm), fy=500 MPa.
    # A_steel = pi*(150²-130²)/4 = 4398.23 mm²; A_grout = pi*250²/4 - A_steel = 44689.15 mm².
    # Allowable = (0.40*35*A_grout + 0.47*500*A_steel) / 1000 = 1659.23 kN.
    res = features.run(
        "settingsFoundationPiles.micropile",
        None,
        {"drillDiaMm": 250.0, "casingOdMm": 150.0, "casingWallMm": 10.0, "fySteelMpa": 500.0},
    )
    assert res["problems"] == []
    a_st = math.pi * (150.0**2 - 130.0**2) / 4.0
    a_gr = math.pi * 250.0**2 / 4.0 - a_st
    allow = (0.40 * 35.0 * a_gr + 0.47 * 500.0 * a_st) / 1000.0
    assert res["summary"]["steelAreaMm2"] == pytest.approx(a_st, rel=0.01)
    assert res["summary"]["allowableAxialKn"] == pytest.approx(allow, rel=0.01)


def test_settings_foundation_piles_pile_diameter() -> None:
    # D = 1000 mm -> A = pi*250000, P = 1000*pi, I = pi*1e12/64.
    res = features.run("settingsFoundationPiles.pileDiameter", None, {"diameterMm": 1000.0})
    assert res["problems"] == []
    assert res["summary"]["areaMm2"] == pytest.approx(math.pi * 250000.0, rel=0.01)
    assert res["summary"]["perimeterMm"] == pytest.approx(1000.0 * math.pi, rel=0.01)
    assert res["summary"]["inertiaMm4"] == pytest.approx(math.pi * 1e12 / 64.0, rel=0.01)


def test_settings_foundation_piles_pile_reinforcement() -> None:
    # D = 800 mm, 10 bars of 25 mm, cover = 75 mm -> As = 10 * pi * 625/4 = 4908.74 mm².
    # pitch = 800 - 150 - 20 - 25 = 605 mm -> clear = pi*605/10 - 25 = 165.07 mm >= 75 -> adequate.
    res = features.run(
        "settingsFoundationPiles.pileReinforcement",
        None,
        {"diameterMm": 800.0, "barCount": 10.0, "barMm": 25.0, "coverMm": 75.0},
    )
    assert res["problems"] == []
    as_st = 10.0 * math.pi * 625.0 / 4.0
    assert res["summary"]["steelAreaMm2"] == pytest.approx(as_st, rel=0.01)
    assert res["summary"]["clearSpacingMm"] == pytest.approx(
        math.pi * 605.0 / 10.0 - 25.0, rel=0.01
    )
    assert res["summary"]["adequateSpacing"] is True


def test_settings_foundation_piles_pile_spacing() -> None:
    # D = 500 mm, factor = 3.5 -> center = 1750 mm, clear gap = 1250 mm.
    res = features.run(
        "settingsFoundationPiles.pileSpacing",
        None,
        {"diameterMm": 500.0, "factor": 3.5},
    )
    assert res["problems"] == []
    assert res["summary"]["centerSpacingMm"] == pytest.approx(1750.0, rel=0.01)
    assert res["summary"]["clearGapMm"] == pytest.approx(1250.0, rel=0.01)


def test_settings_foundation_piles_rock_joint_factor() -> None:
    # RQD = 100% -> 0.2 + 0.8*1.0^1.5 = 1.0; RQD = 60% -> 0.2 + 0.8*0.6^1.5 = 0.5718.
    res = features.run("settingsFoundationPiles.rockJointFactor", None, {"rqdPct": 60.0})
    assert res["problems"] == []
    expected = 0.2 + 0.8 * (0.6**1.5)
    assert res["summary"]["jointReductionFactor"] == pytest.approx(expected, rel=0.01)


def test_settings_foundation_piles_rock_strength() -> None:
    # UCS = 16 MPa -> fs = 0.25 * 4 = 1.0 MPa = 1000 kPa.
    res = features.run("settingsFoundationPiles.rockStrength", None, {"ucsMpa": 16.0})
    assert res["problems"] == []
    assert res["summary"]["unitShaftFrictionMpa"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["unitShaftFrictionKpa"] == pytest.approx(1000.0, rel=0.01)


def test_settings_foundation_piles_shaft_capacity() -> None:
    # D = 1.0 m, H = 10 m, fs = 50 kPa -> area = 10*pi m², Qs = 500*pi = 1570.8 kN.
    res = features.run(
        "settingsFoundationPiles.shaftCapacity",
        None,
        {"diameterM": 1.0, "layerThicknessM": 10.0, "unitSkinKpa": 50.0},
    )
    assert res["problems"] == []
    assert res["summary"]["shaftAreaM2"] == pytest.approx(10.0 * math.pi, rel=0.01)
    assert res["summary"]["ultimateShaftKn"] == pytest.approx(500.0 * math.pi, rel=0.01)


def test_settings_foundation_piles_sheet_pile() -> None:
    # W = 2000 cm³/m, fy = 400 MPa -> Mn = 2000*1000*400/1e6 = 800 kN·m/m; 0.9*Mn = 720 kN·m/m.
    res = features.run(
        "settingsFoundationPiles.sheetPile",
        None,
        {"sectionModulusCm3PerM": 2000.0, "fyMpa": 400.0, "lengthM": 14.0},
    )
    assert res["problems"] == []
    assert res["summary"]["designMomentKnMPerM"] == pytest.approx(720.0, rel=0.01)


def test_settings_foundation_piles_socket_length() -> None:
    # 0.8 m * 2.5 = 2.0 m.
    res = features.run(
        "settingsFoundationPiles.socketLength",
        None,
        {"pileDiaM": 0.8, "minMultipleD": 2.5},
    )
    assert res["problems"] == []
    assert res["summary"]["socketLengthM"] == pytest.approx(2.0, rel=0.01)


def test_settings_foundation_piles_socket_resistance() -> None:
    # D = 1.0 m, Ls = 2.0 m, UCS = 9 MPa, joint = 0.8 -> fs = 250*3*0.8 = 600 kPa.
    # qb = min(5000, 1.5*9000*0.8) = 5000 kPa -> Qs = pi*1*2*600 = 1200*pi, Qb = (pi/4)*5000 = 1250*pi.
    res = features.run(
        "settingsFoundationPiles.socketResistance",
        None,
        {"pileDiaM": 1.0, "socketLengthM": 2.0, "ucsMpa": 9.0, "jointFactor": 0.8},
    )
    assert res["problems"] == []
    assert res["summary"]["socketShaftKn"] == pytest.approx(1200.0 * math.pi, rel=0.01)
    assert res["summary"]["socketBaseKn"] == pytest.approx(1250.0 * math.pi, rel=0.01)
    assert res["summary"]["ultimateSocketKn"] == pytest.approx(2450.0 * math.pi, rel=0.01)


def test_settings_foundation_piles_static_load_test() -> None:
    # Proof = 1500 * 2.0 = 3000 kN; Davisson = 4.0 + 720/120 = 10.0 mm.
    res = features.run(
        "settingsFoundationPiles.staticLoadTest",
        None,
        {"designLoadKn": 1500.0, "testMultiplier": 2.0, "diameterMm": 720.0},
    )
    assert res["problems"] == []
    assert res["summary"]["proofLoadKn"] == pytest.approx(3000.0, rel=0.01)
    assert res["summary"]["davissonOffsetMm"] == pytest.approx(10.0, rel=0.01)


def test_settings_foundation_piles_wall_thickness() -> None:
    # OD = 500 mm, wall = 12 mm, corrosion = 2 mm -> t_eff = 10 mm, D/t = 50.0.
    # Area = pi*(500² - 480²)/4 = pi*19600/4 = 15393.8 mm².
    res = features.run(
        "settingsFoundationPiles.wallThickness",
        None,
        {"outerDiaMm": 500.0, "wallMm": 12.0, "corrosionAllowanceMm": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["effectiveThicknessMm"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["dOverT"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["effectiveSteelAreaMm2"] == pytest.approx(math.pi * 4900.0, rel=0.01)


# ── settings_foundation_soil (14) ───────────────────────────────────────────────────────────────────


def test_settings_foundation_soil_add_layer() -> None:
    # 5.0 m * 19.0 kN/m³ = 95.0 kPa overburden.
    res = features.run(
        "settingsFoundationSoil.addLayer",
        None,
        {"layerName": "Dense Sand", "thicknessM": 5.0, "soilType": "sand", "gammaKnM3": 19.0},
    )
    assert res["problems"] == []
    assert res["summary"]["overburdenKpa"] == pytest.approx(95.0, rel=0.01)


def test_settings_foundation_soil_artesian_condition() -> None:
    # Overburden = 5.0 * 18.0 = 90.0 kPa; uplift = 5.0 * 9.81 = 49.05 kPa -> FS = 1.835 >= 1.2 -> safe.
    res = features.run(
        "settingsFoundationSoil.artesianCondition",
        None,
        {"clayBlanketM": 5.0, "gammaClayKnM3": 18.0, "artesianHeadM": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["overburdenKpa"] == pytest.approx(90.0, rel=0.01)
    assert res["summary"]["artesianUpliftKpa"] == pytest.approx(49.05, rel=0.01)
    assert res["summary"]["safetyFactor"] == pytest.approx(90.0 / 49.05, rel=0.01)
    assert res["summary"]["safe"] is True


def test_settings_foundation_soil_cohesion_value() -> None:
    # phi = 0 -> Ka = 1.0 -> zc = 2*45/(18*1) = 5.0 m, qu = 2*45/1 = 90.0 kPa.
    res = features.run(
        "settingsFoundationSoil.cohesionValue",
        None,
        {"cohesionKpa": 45.0, "gammaKnM3": 18.0, "phiDeg": 0.0},
    )
    assert res["problems"] == []
    assert res["summary"]["tensionCrackDepthM"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["unconfinedStrengthKpa"] == pytest.approx(90.0, rel=0.01)


def test_settings_foundation_soil_consolidation_index() -> None:
    # LL = 50% -> Cc = 0.009*(50-10) = 0.36; Cr = 0.36 * 0.2 = 0.072.
    res = features.run(
        "settingsFoundationSoil.consolidationIndex",
        None,
        {"liquidLimitPct": 50.0, "recompressionRatio": 0.2},
    )
    assert res["problems"] == []
    assert res["summary"]["compressionIndexCc"] == pytest.approx(0.36, rel=0.01)
    assert res["summary"]["recompressionIndexCr"] == pytest.approx(0.072, rel=0.01)


def test_settings_foundation_soil_core_sample() -> None:
    # 1800/2000 = 90% TCR, 1280/2000 = 64% RQD -> Fair rock quality (50-75%).
    res = features.run(
        "settingsFoundationSoil.coreSample",
        None,
        {"runLengthMm": 2000.0, "recoveredMm": 1800.0, "piecesOver100Mm": 1280.0},
    )
    assert res["problems"] == []
    assert res["summary"]["tcrPct"] == pytest.approx(90.0, rel=0.01)
    assert res["summary"]["rqdPct"] == pytest.approx(64.0, rel=0.01)
    assert res["summary"]["rockQuality"] == "Fair"


def test_settings_foundation_soil_friction_angle() -> None:
    # phi = 30° -> Ka = 1/3, Kp = 3.0, K0 = 1 - sin(30°) = 0.5.
    res = features.run("settingsFoundationSoil.frictionAngle", None, {"phiDeg": 30.0})
    assert res["problems"] == []
    assert res["summary"]["ka"] == pytest.approx(1.0 / 3.0, rel=0.01)
    assert res["summary"]["kp"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["k0"] == pytest.approx(0.5, rel=0.01)


def test_settings_foundation_soil_layer_thickness() -> None:
    # 8.5 - 3.0 = 5.5 m.
    res = features.run(
        "settingsFoundationSoil.layerThickness",
        None,
        {"topDepthM": 3.0, "bottomDepthM": 8.5},
    )
    assert res["problems"] == []
    assert res["summary"]["thicknessM"] == pytest.approx(5.5, rel=0.01)


def test_settings_foundation_soil_modulus_elasticity() -> None:
    # Sand Es = 500*(25+15) = 20,000 kPa = 20.0 MPa.
    res = features.run(
        "settingsFoundationSoil.modulusElasticity",
        None,
        {"sptN60": 25.0, "soilKind": "sand"},
    )
    assert res["problems"] == []
    assert res["summary"]["esKpa"] == pytest.approx(20000.0, rel=0.01)
    assert res["summary"]["esMpa"] == pytest.approx(20.0, rel=0.01)


def test_settings_foundation_soil_permeability_class() -> None:
    # 1e-2 m/s -> clean gravel / coarse sand high permeability class.
    res = features.run("settingsFoundationSoil.permeabilityClass", None, {"kMPerS": 1e-2})
    assert res["problems"] == []
    assert isinstance(res["summary"]["permeabilityClass"], str)
    assert "High" in res["summary"]["permeabilityClass"]


def test_settings_foundation_soil_seasonal_variation() -> None:
    # Dry = 5.0 m, wet = 1.5 m -> fluctuation = 3.5 m, high = 1.5 m, low = 5.0 m.
    res = features.run(
        "settingsFoundationSoil.seasonalVariation",
        None,
        {"drySeasonDepthM": 5.0, "wetSeasonDepthM": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["fluctuationM"] == pytest.approx(3.5, rel=0.01)
    assert res["summary"]["governingHighGwtM"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["governingLowGwtM"] == pytest.approx(5.0, rel=0.01)


def test_settings_foundation_soil_seepage_coefficient() -> None:
    # i = 5.0/10.0 = 0.5; v = 2e-5 * 0.5 = 1e-5 m/s; flux = 1e-5 * 86400 = 0.864 m³/m²/day.
    res = features.run(
        "settingsFoundationSoil.seepageCoefficient",
        None,
        {"kMPerS": 2e-5, "headDiffM": 5.0, "flowPathM": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["hydraulicGradient"] == pytest.approx(0.5, rel=0.01)
    assert res["summary"]["fluxM3PerM2Day"] == pytest.approx(0.864, rel=0.01)


def test_settings_foundation_soil_spt_n_value() -> None:
    # N_raw = 20, Er = 75% -> N60 = 25; sigma' = 100 kPa -> CN = 1.0 -> N1,60 = 25.
    res = features.run(
        "settingsFoundationSoil.sptNValue",
        None,
        {"nRaw": 20.0, "energyRatioPct": 75.0, "sigmaVeffKpa": 100.0},
    )
    assert res["problems"] == []
    assert res["summary"]["n60"] == pytest.approx(25.0, rel=0.01)
    assert res["summary"]["cnFactor"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["n1_60"] == pytest.approx(25.0, rel=0.01)


def test_settings_foundation_soil_void_ratio() -> None:
    # Gs = 2.70, w = 25%, Sr = 100% -> e = 2.70 * 0.25 = 0.675; n = 0.675/1.675 = 0.40299.
    # gamma_sat = ((2.70+0.675)/1.675) * 9.81 = 19.766 kN/m³.
    res = features.run(
        "settingsFoundationSoil.voidRatio",
        None,
        {"specificGravity": 2.70, "waterContentPct": 25.0, "saturationPct": 100.0},
    )
    assert res["problems"] == []
    e = 2.70 * 0.25
    assert res["summary"]["voidRatio"] == pytest.approx(e, rel=0.01)
    assert res["summary"]["porosity"] == pytest.approx(e / (1.0 + e), rel=0.01)
    assert res["summary"]["saturatedUnitWeightKnM3"] == pytest.approx(
        ((2.70 + e) / (1.0 + e)) * 9.81, rel=0.01
    )


def test_settings_foundation_soil_water_table() -> None:
    # GWT = 2.0 m, z = 6.0 m, gamma = 19.0 -> u = 4*9.81 = 39.24 kPa; sigma' = 6*19 - 39.24 = 74.76 kPa.
    res = features.run(
        "settingsFoundationSoil.waterTable",
        None,
        {"waterDepthM": 2.0, "evalDepthM": 6.0, "gammaSoilKnM3": 19.0},
    )
    assert res["problems"] == []
    assert res["summary"]["porePressureKpa"] == pytest.approx(39.24, rel=0.01)
    assert res["summary"]["effectiveStressKpa"] == pytest.approx(114.0 - 39.24, rel=0.01)

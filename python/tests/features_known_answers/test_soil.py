"""Independent known-answer tests for standalone numeric calculators in the Soil Report window."""

from __future__ import annotations

import math

import pytest

from saengine import features


def _row_by(res: dict, key: str, value: object, table_index: int = 0) -> dict:
    for row in res["tables"][table_index]["rows"]:
        if row[key] == value:
            return row
    raise AssertionError(f"No row with {key}={value!r} in {res['tables'][table_index]['rows']}")


def test_soil_depth_ruler() -> None:
    # Standalone scaled depth ruler from 0 to depthM=8.0 m in 5 equal intervals (1.6 m step).
    res = features.run("soil.depthRuler", None, {"boreholeId": "BH-2", "depthM": 8.0})
    assert res["problems"] == []
    assert res["summary"]["depthM"] == pytest.approx(8.0, rel=0.01)
    assert res["summary"]["boreholeId"] == "BH-2"
    rows = res["tables"][0]["rows"]
    assert rows[0]["depthM"] == pytest.approx(0.0, abs=1e-6)
    assert rows[-1]["depthM"] == pytest.approx(8.0, rel=0.01)


def test_soil_falling_head_test() -> None:
    # k = (a / A) * (L / t) * ln(h1 / h2)
    #   = (1000 / 5000) * (0.2 / 10) * ln(1000 / 200)
    #   = 0.2 * 0.02 * 1.609438 = 0.006438 m/s
    res = features.run(
        "soil.fallingHeadTest",
        None,
        {
            "standpipeAreaMm2": 1000.0,
            "specimenAreaMm2": 5000.0,
            "lengthMm": 200.0,
            "headStartMm": 1000.0,
            "headEndMm": 200.0,
            "timeS": 10.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["permeabilityMPerS"] == pytest.approx(0.006438, rel=0.01)


def test_soil_field_density_test() -> None:
    # rho_d = rho_wet / (1 + w) = 2.10 / (1 + 0.20) = 1.75 Mg/m3
    # RC = 100 * 1.75 / 1.80 = 97.2222%
    res = features.run(
        "soil.fieldDensityTest",
        None,
        {"wetDensity": 2.10, "moisturePct": 20.0, "maxDryDensity": 1.80},
    )
    assert res["problems"] == []
    assert res["summary"]["dryDensityMgM3"] == pytest.approx(1.75, rel=0.01)
    assert res["summary"]["relativeCompactionPct"] == pytest.approx(97.2222, rel=0.01)


def test_soil_lugeon_test() -> None:
    # Lu = Q / (L * P) = 24.0 / (4.0 * 0.6) = 10.0 Lugeon
    res = features.run(
        "soil.lugeonTest",
        None,
        {"flowLpm": 24.0, "testLengthM": 4.0, "pressureMpa": 0.6},
    )
    assert res["problems"] == []
    assert res["summary"]["lugeonValue"] == pytest.approx(10.0, rel=0.01)


def test_soil_pressuremeter_test() -> None:
    # Cylindrical cavity expansion with L = r:
    # r = 0.04 m -> 2*pi*r^3 = 4.021239e-4 m^3
    # strain = dV / (2*pi*r^3) = 4e-6 / 4.021239e-4 = 0.00994718
    # G = dp / (2 * strain) = 200e3 / (2 * 0.00994718) = 10.0531 MPa
    # E = 2 * (1 + nu) * G = 2.5 * 10.0531 = 25.1327 MPa
    res = features.run(
        "soil.pressuremeterTest",
        None,
        {
            "pressureIncrementKpa": 200.0,
            "volumeIncrementCm3": 4.0,
            "cavityRadiusMm": 40.0,
            "poissonRatio": 0.25,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["pressuremeterModulusMpa"] == pytest.approx(25.1327, rel=0.01)


def test_soil_vane_shear_test() -> None:
    # cu = T / [pi * D^2 * (H/2 + D/6)]
    # D = 0.06 m, H = 0.12 m -> pi * 0.0036 * (0.06 + 0.01) = 7.916813e-4 m^3
    # cu = 4.5 / 7.916813e-4 / 1000 = 5.6841 kPa
    res = features.run(
        "soil.vaneShearTest",
        None,
        {"torqueNm": 4.5, "vaneDiameterMm": 60.0, "vaneHeightMm": 120.0},
    )
    assert res["problems"] == []
    assert res["summary"]["undrainedStrengthKpa"] == pytest.approx(5.6841, rel=0.01)


def test_soil_bearing_buoyancy_check() -> None:
    # Submerged depth = 4.0 - 1.5 = 2.5 m
    # Uplift U = 9.81 * 2.5 * 200 = 4905.0 kN
    # Stabilizing weight W = 25.0 * 1.2 * 200 + 500 = 6500.0 kN
    # FS = 6500 / 4905 = 1.3252; net = 6500 - 4905 = 1595.0 kN
    res = features.run(
        "soilBearing.buoyancyCheck",
        None,
        {
            "planAreaM2": 200.0,
            "thicknessM": 1.2,
            "embedmentM": 4.0,
            "waterTableM": 1.5,
            "concreteUnitWeight": 25.0,
            "superimposedDeadKn": 500.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["upliftKn"] == pytest.approx(4905.0, rel=0.01)
    assert res["summary"]["stabilizingDeadLoadKn"] == pytest.approx(6500.0, rel=0.01)
    assert res["summary"]["upliftFactorOfSafety"] == pytest.approx(1.3252, rel=0.01)
    assert res["summary"]["netDownwardKn"] == pytest.approx(1595.0, rel=0.01)


@pytest.mark.parametrize(
    ("feature_id", "slope", "depth", "c", "phi", "gamma", "ru", "key", "expected"),
    [
        # Infinite slope FS = [c' + (1 - ru)*gamma*z*cos^2(beta)*tan(phi')] / [gamma*z*sin(beta)*cos(beta)]
        # (1) criticalSlipSurface: gz=57, cos(25)=0.90631, sin(25)=0.42262, tan(28)=0.53171
        #     N' = 57 * 0.82139 * 0.8 = 37.4556, T = 57 * 0.42262 * 0.90631 = 21.8323
        #     FS = (12 + 37.4556 * 0.53171) / 21.8323 = 1.4619
        (
            "soilBearing.criticalSlipSurface",
            25.0,
            3.0,
            12.0,
            28.0,
            19.0,
            0.2,
            "minimumFactorOfSafety",
            1.4619,
        ),
        # (2) factorOfSafetyMap: gz=50, cos(20)=0.93969, sin(20)=0.34202, tan(32)=0.62487
        #     N' = 50 * 0.88302 * 0.9 = 39.7360, T = 16.0697 -> FS = 2.0430
        (
            "soilBearing.factorOfSafetyMap",
            20.0,
            2.5,
            8.0,
            32.0,
            20.0,
            0.1,
            "factorOfSafety",
            2.0430,
        ),
        # (3) limitEquilibriumLem: gz=72, cos(35)=0.81915, sin(35)=0.57358, tan(26)=0.48773
        #     N' = 72 * 0.67101 = 48.3127, T = 33.8289 -> FS = 1.1400
        (
            "soilBearing.limitEquilibriumLem",
            35.0,
            4.0,
            15.0,
            26.0,
            18.0,
            0.0,
            "factorOfSafety",
            1.1400,
        ),
        # (4) strengthReductionFem: gz=60, cos(30)=0.86603, sin(30)=0.5, tan(30)=0.57735
        #     N' = 45.0, T = 25.9808 -> SRF = FS = (15 + 45*0.57735)/25.9808 = 1.5774
        (
            "soilBearing.strengthReductionFem",
            30.0,
            3.0,
            15.0,
            30.0,
            20.0,
            0.0,
            "strengthReductionFactor",
            1.5774,
        ),
    ],
)
def test_soil_bearing_infinite_slope_features(
    feature_id: str,
    slope: float,
    depth: float,
    c: float,
    phi: float,
    gamma: float,
    ru: float,
    key: str,
    expected: float,
) -> None:
    res = features.run(
        feature_id,
        None,
        {
            "slopeAngleDeg": slope,
            "depthM": depth,
            "cohesionKpa": c,
            "phiDeg": phi,
            "gammaKnM3": gamma,
            "ru": ru,
        },
    )
    assert res["problems"] == []
    assert res["summary"][key] == pytest.approx(expected, rel=0.01)


def test_soil_bearing_dynamic_compaction() -> None:
    # D = alpha * sqrt(W * H) = 0.6 * sqrt(15 * 20) = 10.3923 m
    # E = 15 t * 1000 kg/t * 9.81 * 20 m * 10 passes / 1000 = 29430.0 kJ
    res = features.run(
        "soilBearing.dynamicCompaction",
        None,
        {"dropMassTonnes": 15.0, "dropHeightM": 20.0, "coefficient": 0.6, "passes": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["estimatedImprovementDepthM"] == pytest.approx(10.3923, rel=0.01)
    assert res["summary"]["energyPerPointKj"] == pytest.approx(29430.0, rel=0.01)


def test_soil_bearing_raft_pressure_check() -> None:
    # q0 = 14400 / (24 * 12) = 50.0 kPa
    # qx = 6 * 2880 / (12 * 24^2) = 2.5 kPa; qy = 6 * 1440 / (24 * 12^2) = 2.5 kPa
    # qmax = 55.0 kPa; qmin = 45.0 kPa
    res = features.run(
        "soilBearing.raftPressureCheck",
        None,
        {
            "lengthM": 24.0,
            "widthM": 12.0,
            "verticalLoadKn": 14400.0,
            "momentXKnM": 1440.0,
            "momentYKnM": 2880.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["averagePressureKpa"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["maximumPressureKpa"] == pytest.approx(55.0, rel=0.01)
    assert res["summary"]["minimumPressureKpa"] == pytest.approx(45.0, rel=0.01)
    assert res["summary"]["fullContact"] is True


def test_soil_bearing_stone_column_design() -> None:
    # ar = (pi * 1.0^2 / 4) / 2.5^2 = 0.785398 / 6.25 = 0.125664
    # Composite improvement factor = 1 + (n - 1) * ar = 1 + 4 * 0.125664 = 1.502655
    # Column stress concentration mu_c = n / [1 + (n - 1)*ar] = 5 / 1.502655 = 3.3274
    # q_comp = 5.14 * cu * [1 + (n - 1)*ar] = 5.14 * 25 * 1.502655 = 193.091 kPa
    res = features.run(
        "soilBearing.stoneColumnDesign",
        None,
        {
            "columnDiameterM": 1.0,
            "spacingM": 2.5,
            "stressConcentration": 5.0,
            "targetPressureKpa": 200.0,
            "soilCuKpa": 25.0,
            "columnPhiDeg": 40.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["areaReplacementRatio"] == pytest.approx(0.1257, rel=0.01)
    assert res["summary"]["stressConcentrationRatio"] == pytest.approx(3.3274, rel=0.01)
    assert res["summary"]["estimatedCompositeCapacityKpa"] == pytest.approx(193.091, rel=0.01)
    assert res["summary"]["targetMet"] is False


def test_soil_bearing_ultimate_bearing() -> None:
    # Vesic/De Beer/Hansen general bearing equation (default pack has no bearingFactors override):
    # phi=25 deg: Nq = exp(pi*tan25)*tan^2(57.5) = 10.6621, Nc = (Nq-1)/tan25 = 20.7204,
    # Ngamma = 2*(Nq+1)*tan25 = 10.8763.
    # B=3, L=6 (B/L=0.5): sc = 1.2573, sq = 1.2332, sg = 0.8.
    # Df=2 (Df/B=2/3): dc = 1.2667, dq = 1.2073. q = 20*2 = 40 kPa.
    # qu = 15*20.7204*1.2573*1.2667 + 40*10.6621*1.2332*1.2073 + 0.5*20*3*10.8763*0.8
    #    = 494.96 + 634.94 + 261.03 = 1390.93 kPa
    # qa = (1390.93 - 40)/2.5 + 40 = 580.37 kPa
    res = features.run(
        "soilBearing.ultimateBearing",
        None,
        {
            "width": 3.0,
            "length": 6.0,
            "depth": 2.0,
            "cohesion": 15.0,
            "phi": 25.0,
            "gamma": 20.0,
            "fs": 2.5,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["ultimateKpa"] == pytest.approx(1390.93, rel=0.01)
    assert res["summary"]["allowableKpa"] == pytest.approx(580.37, rel=0.01)


def test_soil_design_eccentricity_advice() -> None:
    # e = M / V = 300 / 1200 = 0.25 m <= B/6 = 4/6 = 0.6667 m
    res = features.run(
        "soilDesign.eccentricityAdvice",
        None,
        {"verticalLoadKn": 1200.0, "momentKnM": 300.0, "baseWidthM": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["eccentricityM"] == pytest.approx(0.25, rel=0.01)
    assert res["summary"]["middleThirdLimitM"] == pytest.approx(0.6667, rel=0.01)
    assert res["summary"]["fullContact"] is True
    assert res["summary"]["resultantWithinBase"] is True


def test_soil_design_overturning_advice() -> None:
    # M_res = 1200 * 4.0 / 2 = 2400.0 kN*m; M_ot = 150 * 3.0 = 450.0 kN*m
    # FS = 2400 / 450 = 5.3333; centroidal eccentricity e = M_ot / V = 450 / 1200 = 0.375 m
    res = features.run(
        "soilDesign.overturningAdvice",
        None,
        {
            "verticalLoadKn": 1200.0,
            "baseWidthM": 4.0,
            "horizontalLoadKn": 150.0,
            "loadHeightM": 3.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["resistingMomentKnM"] == pytest.approx(2400.0, rel=0.01)
    assert res["summary"]["overturningMomentKnM"] == pytest.approx(450.0, rel=0.01)
    assert res["summary"]["factorOfSafety"] == pytest.approx(5.3333, rel=0.01)
    assert res["summary"]["resultantEccentricityM"] == pytest.approx(0.375, rel=0.01)


def test_soil_design_sliding_resistance() -> None:
    # R = 1500 * tan(30 deg) + 10 * 12 = 866.025 + 120 = 986.025 kN; FS = 986.025 / 400 = 2.4651
    res = features.run(
        "soilDesign.slidingResistance",
        None,
        {
            "verticalLoadKn": 1500.0,
            "horizontalLoadKn": 400.0,
            "contactAreaM2": 12.0,
            "cohesionKpa": 10.0,
            "interfaceAngleDeg": 30.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["slidingResistanceKn"] == pytest.approx(986.025, rel=0.01)
    assert res["summary"]["factorOfSafety"] == pytest.approx(2.4651, rel=0.01)


def test_soil_design_uplift_resistance() -> None:
    # R = 800 * tan(20 deg) + 15 * 8 = 291.176 + 120 = 411.176 kN; FS = 411.176 / 200 = 2.0559
    res = features.run(
        "soilDesign.upliftResistance",
        None,
        {
            "verticalLoadKn": 800.0,
            "horizontalLoadKn": 200.0,
            "contactAreaM2": 8.0,
            "cohesionKpa": 15.0,
            "interfaceAngleDeg": 20.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["upliftResistanceKn"] == pytest.approx(411.176, rel=0.01)
    assert res["summary"]["factorOfSafety"] == pytest.approx(2.0559, rel=0.01)


def test_soil_earth_active_pressure() -> None:
    # Ka = tan^2(45 - 30/2) = 1/3
    # Uniform surcharge 15 kPa -> rect (1/3*15)*6 = 30 kN/m at 3.0 m
    # Soil 0.5*(1/3)*20*6^2 = 120 kN/m at 2.0 m
    # Total P = 150.0 kN/m; arm = (30*3 + 120*2)/150 = 2.20 m
    res = features.run(
        "soilEarth.activePressure",
        None,
        {
            "height": 6.0,
            "gamma": 20.0,
            "phi": 30.0,
            "cohesion": 0.0,
            "water": 100.0,
            "surcharge": 15.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["coefficient"] == pytest.approx(1 / 3, rel=0.01)
    assert res["summary"]["resultantKnPerM"] == pytest.approx(150.0, rel=0.01)
    assert res["summary"]["actsAboveBaseM"] == pytest.approx(2.20, rel=0.01)


def test_soil_earth_at_rest_pressure() -> None:
    # K0 = 1 - sin(30 deg) = 0.5; P0 = 0.5 * 0.5 * 20 * 5^2 = 125.0 kN/m; arm = 5/3 = 1.6667 m
    res = features.run(
        "soilEarth.atRestPressure",
        None,
        {
            "height": 5.0,
            "gamma": 20.0,
            "phi": 30.0,
            "cohesion": 0.0,
            "water": 100.0,
            "surcharge": 0.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["coefficient"] == pytest.approx(0.5, rel=0.01)
    assert res["summary"]["resultantKnPerM"] == pytest.approx(125.0, rel=0.01)
    assert res["summary"]["actsAboveBaseM"] == pytest.approx(1.6667, rel=0.01)


def test_soil_earth_passive_pressure() -> None:
    # Kp = tan^2(45 + 30/2) = 3.0; Pp = 0.5 * 3.0 * 20 * 3^2 = 270.0 kN/m; arm = 1.0 m
    res = features.run(
        "soilEarth.passivePressure",
        None,
        {
            "height": 3.0,
            "gamma": 20.0,
            "phi": 30.0,
            "cohesion": 0.0,
            "water": 100.0,
            "surcharge": 0.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["coefficient"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["resultantKnPerM"] == pytest.approx(270.0, rel=0.01)
    assert res["summary"]["actsAboveBaseM"] == pytest.approx(1.0, rel=0.01)


def test_soil_earth_surcharge_pressure() -> None:
    # Boussinesq doubled strip load: h=4, q=50, a=2, w=2.
    # At z = 1.6 m: a1 = atan(2/1.6) = 0.896055 rad, a2 = atan(4/1.6) = 1.190290 rad
    # beta = 0.294235, alpha = 1.043173 -> sigma = (2*50/pi)*(beta - sin(beta)*cos(2*alpha)) = 13.9175 kPa
    res = features.run(
        "soilEarth.surchargePressure",
        None,
        {"height": 4.0, "load": 50.0, "offset": 2.0, "width": 2.0},
    )
    assert res["problems"] == []
    row = _row_by(res, "depth", 1.6)
    assert row["pressure"] == pytest.approx(13.9175, rel=0.01)
    assert res["summary"]["maxPressureKpa"] >= row["pressure"]
    assert res["summary"]["resultantKnPerM"] > 0


def test_soil_earth_anchored_wall_pressure() -> None:
    # Ka = 1/3, gamma = 18 kN/m3, H = 5 m, q = 20 kPa
    # Rect = (20/3)*5 = 33.333 kN/m at 2.5 m; Tri = 0.5*(1/3)*18*25 = 75 kN/m at 5/3 m
    # Total P = 108.333 kN/m; arm = (33.333*2.5 + 75*5/3)/108.333 = 1.9231 m
    res = features.run(
        "soilEarth.anchoredWallPressure",
        None,
        {"pressureKpa": 20.0, "heightM": 5.0, "phiDeg": 30.0},
    )
    assert res["problems"] == []
    assert res["summary"]["activeResultantKnPerM"] == pytest.approx(108.333, rel=0.01)
    assert res["summary"]["actsAboveBaseM"] == pytest.approx(1.9231, rel=0.01)


def test_soil_earth_basement_wall_pressure() -> None:
    # K0 = 0.5, gamma = 18 kN/m3, H = 5 m, q = 10 kPa
    # Rect = 5*5 = 25 kN/m at 2.5 m; Tri = 0.5*0.5*18*25 = 112.5 kN/m at 5/3 m
    # Total P = 137.5 kN/m; arm = (25*2.5 + 112.5*5/3)/137.5 = 1.8182 m
    res = features.run(
        "soilEarth.basementWallPressure",
        None,
        {"pressureKpa": 10.0, "heightM": 5.0, "phiDeg": 30.0},
    )
    assert res["problems"] == []
    assert res["summary"]["lateralCoefficient"] == pytest.approx(0.5, rel=0.01)
    assert res["summary"]["resultantKnPerM"] == pytest.approx(137.5, rel=0.01)
    assert res["summary"]["actsAboveBaseM"] == pytest.approx(1.8182, rel=0.01)


def test_soil_earth_braced_excavation_pressure() -> None:
    # Terzaghi-Peck sand envelope: p = 0.65 * Ka * 18 * H = 0.65 * (1/3) * 18 * 6 = 23.4 kPa
    # Resultant P = 23.4 * 6 = 140.4 kN/m at H/2 = 3.0 m
    res = features.run(
        "soilEarth.bracedExcavationPressure",
        None,
        {"heightM": 6.0, "phiDeg": 30.0, "pressureKpa": 0.0, "slopeAngleDeg": 0.0},
    )
    assert res["problems"] == []
    assert res["summary"]["apparentPressureKpa"] == pytest.approx(23.4, rel=0.01)
    assert res["summary"]["resultantKnPerM"] == pytest.approx(140.4, rel=0.01)
    assert res["summary"]["actsAboveBaseM"] == pytest.approx(3.0, rel=0.01)


def test_soil_earth_compaction_induced_pressure() -> None:
    # Ka = 1/3, q0 = 60 kPa, z0 = 1.0 m, H = 5.0 m
    # Analytical integral = Ka * q0 * z0 * (1 - exp(-H/z0)) = 20 * (1 - e^-5) = 19.865 kN/m
    res = features.run(
        "soilEarth.compactionInducedPressure",
        None,
        {"pressureKpa": 60.0, "heightM": 5.0, "phiDeg": 30.0, "decayDepthM": 1.0},
    )
    assert res["problems"] == []
    assert res["summary"]["resultantKnPerM"] == pytest.approx(19.865, rel=0.01)


@pytest.mark.parametrize(
    ("feature_id", "pressure", "height", "phi", "expected_p", "expected_arm"),
    [
        # compactionLoads: Ka=1/3, gamma=18, q=25, H=4 -> P = (25*4 + 0.5*18*16)/3 = 81.333 kN/m
        # arm = (100/3*2 + 48*4/3)/81.333 = 1.6066 m
        ("soilEarth.compactionLoads", 25.0, 4.0, 30.0, 81.333, 1.6066),
        # railwaySurcharge: Ka=1/3, gamma=18, q=40, H=6 -> P = (240 + 324)/3 = 188.0 kN/m
        # arm = (80*3 + 108*2)/188 = 2.4255 m
        ("soilEarth.railwaySurcharge", 40.0, 6.0, 30.0, 188.0, 2.4255),
        # trafficSurcharge: Ka=1/3, gamma=18, q=15, H=5 -> P = (75 + 225)/3 = 100.0 kN/m
        # arm = (25*2.5 + 75*5/3)/100 = 1.875 m
        ("soilEarth.trafficSurcharge", 15.0, 5.0, 30.0, 100.0, 1.875),
    ],
)
def test_soil_earth_active_surcharge_variants(
    feature_id: str,
    pressure: float,
    height: float,
    phi: float,
    expected_p: float,
    expected_arm: float,
) -> None:
    res = features.run(
        feature_id,
        None,
        {"pressureKpa": pressure, "heightM": height, "phiDeg": phi},
    )
    assert res["problems"] == []
    assert res["summary"]["lateralCoefficient"] == pytest.approx(1 / 3, rel=0.01)
    assert res["summary"]["resultantKnPerM"] == pytest.approx(expected_p, rel=0.01)
    assert res["summary"]["actsAboveBaseM"] == pytest.approx(expected_arm, rel=0.01)


def test_soil_earth_silo_pressure() -> None:
    # Janssen circular silo: R = 4.0 m -> Rh = R/2 = 2.0 m, K0 = 1 - sin(30) = 0.5, mu = tan(20) = 0.36397
    # Characteristic depth z0 = Rh / (K0 * mu) = 2.0 / (0.5 * 0.36397) = 10.9899 m
    # At z = 10 m: sigma_v = gamma * z0 * (1 - exp(-z/z0)) = 9 * 10.9899 * (1 - exp(-10/10.9899)) = 59.093 kPa
    # sigma_h_max = K0 * sigma_v = 29.546 kPa
    res = features.run(
        "soilEarth.siloPressure",
        None,
        {
            "heightM": 10.0,
            "phiDeg": 30.0,
            "siloRadiusM": 4.0,
            "wallFrictionDeg": 20.0,
            "unitWeightKnM3": 9.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["characteristicDepthM"] == pytest.approx(10.9899, rel=0.01)
    assert res["summary"]["maximumLateralPressureKpa"] == pytest.approx(29.546, rel=0.01)


def test_soil_earth_slope_surcharge() -> None:
    # Rankine sloping backfill: phi=30, beta=15
    # Ka = cos15 * (cos15 - sqrt(cos^2(15) - cos^2(30))) / (cos15 + sqrt(cos^2(15) - cos^2(30))) = 0.37295
    # P = 0.5 * 0.37295 * 18 * 5^2 = 83.914 kN/m, arm = 5/3 = 1.6667 m
    res = features.run(
        "soilEarth.slopeSurcharge",
        None,
        {"pressureKpa": 0.0, "heightM": 5.0, "phiDeg": 30.0, "slopeAngleDeg": 15.0},
    )
    assert res["problems"] == []
    assert res["summary"]["lateralCoefficient"] == pytest.approx(0.37295, rel=0.01)
    assert res["summary"]["resultantKnPerM"] == pytest.approx(83.914, rel=0.01)
    assert res["summary"]["actsAboveBaseM"] == pytest.approx(1.6667, rel=0.01)


def test_soil_earth_wall_friction() -> None:
    # phi = 24 deg -> delta = min(24/2, 15) = 12 deg -> tan(12 deg) = 0.21256; Ka = (1-sin24)/(1+sin24) = 0.4217
    res = features.run("soilEarth.wallFriction", None, {"heightM": 5.0, "phiDeg": 24.0})
    assert res["problems"] == []
    assert res["summary"]["wallFrictionAngleDeg"] == pytest.approx(12.0, rel=0.01)
    assert res["summary"]["wallFrictionCoefficient"] == pytest.approx(0.2126, rel=0.01)
    assert res["summary"]["rankineActiveCoefficient"] == pytest.approx(0.4217, rel=0.01)


def test_soil_profile_dissipation_test() -> None:
    # u0 = 200, uinf = 0 -> target = 100 kPa -> t50 = 0.25 min = 15 s
    # cv = T50 * r^2 / t50 = 0.5 * 0.5^2 / 15 = 0.008333 m^2/s
    res = features.run(
        "soilProfile.dissipationTest",
        None,
        {
            "readings": "0, 200\n0.25, 100\n1.0, 0",
            "drainageRadiusM": 0.5,
            "timeFactor": 0.5,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["t50Min"] == pytest.approx(0.25, rel=0.01)
    assert res["summary"]["cvM2PerS"] == pytest.approx(0.008333, rel=0.01)


def test_soil_profile_equilibrium_pore_pressure() -> None:
    # Mean of (40, 80, 120) = 80.0 kPa; head = 80 / 9.81 = 8.1549 m; range = 80.0 kPa
    res = features.run(
        "soilProfile.equilibriumPorePressure",
        None,
        {"readings": "5, 40\n10, 80\n15, 120", "waterTableDepthM": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["meanPressureKpa"] == pytest.approx(80.0, rel=0.01)
    assert res["summary"]["equivalentWaterHeadM"] == pytest.approx(8.1549, rel=0.01)
    assert res["summary"]["pressureRangeKpa"] == pytest.approx(80.0, rel=0.01)


def test_soil_profile_excess_pore_pressure() -> None:
    # du = 250 - 70 = 180 kPa; Bq = 180 / (1920 - 120) = 0.10
    res = features.run(
        "soilProfile.excessPorePressure",
        None,
        {"u2Kpa": 250.0, "u0Kpa": 70.0, "qtKpa": 1920.0, "sigmaVKpa": 120.0},
    )
    assert res["problems"] == []
    assert res["summary"]["excessPorePressureKpa"] == pytest.approx(180.0, rel=0.01)
    assert res["summary"]["porePressureRatioBq"] == pytest.approx(0.10, rel=0.01)


@pytest.mark.parametrize(
    "feature_id", ["soilProfile.hydrostaticCorrection", "soilProfile.porePressureProfile"]
)
def test_soil_profile_hydrostatic_correction(feature_id: str) -> None:
    # Water table at 4 m: at z=10 m, u0 = 9.81 * 6 = 58.86 kPa, excess = 100 - 58.86 = 41.14 kPa
    res = features.run(
        feature_id,
        None,
        {"readings": "2, 10\n6, 50\n10, 100", "waterTableDepthM": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["maximumExcessKpa"] == pytest.approx(41.14, rel=0.01)
    row10 = _row_by(res, "depthM", 10.0)
    assert row10["hydrostaticKpa"] == pytest.approx(58.86, rel=0.01)
    assert row10["excessKpa"] == pytest.approx(41.14, rel=0.01)


def test_soil_profile_robertson_soil_class() -> None:
    # net = 10150 - 150 = 10000 kPa -> Qtn = 10000/100 = 100; Fr = 100*100/10000 = 1.0%
    # Ic = sqrt((3.47 - log10(100))^2 + (log10(1.0) + 1.22)^2) = sqrt(1.47^2 + 1.22^2) = 1.9103
    res = features.run(
        "soilProfile.robertsonSoilClass",
        None,
        {"qcMpa": 10.15, "fsKpa": 100.0, "sigmaVeffKpa": 100.0, "sigmaVKpa": 150.0},
    )
    assert res["problems"] == []
    assert res["summary"]["normalizedConeResistance"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["frictionRatioPct"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["soilBehaviorIndex"] == pytest.approx(1.9103, rel=0.01)
    assert res["summary"]["soilBehaviorGroup"] == "sand to silty sand"


def test_soil_seismic_arias_intensity() -> None:
    # Ia = pi * g / 2 * sum(a_g^2 * dt) = pi * 9.80665 / 2 * (0.04 + 0.16 + 0.04) * 0.5 = 1.8485 m/s
    res = features.run(
        "soilSeismic.ariasIntensity",
        None,
        {"accelerationG": "0.2\n0.4\n0.2", "timeStepS": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["ariasIntensityMPerS"] == pytest.approx(1.8485, rel=0.01)
    assert res["summary"]["peakAccelerationG"] == pytest.approx(0.4, rel=0.01)


def test_soil_seismic_hysteretic_damping() -> None:
    # Mean of (0.04, 0.08) = 0.06
    res = features.run(
        "soilSeismic.hystereticDamping",
        None,
        {"profileRows": "5, 200, 0.04\n10, 300, 0.08", "strainPct": 0.2},
    )
    assert res["problems"] == []
    assert res["summary"]["meanDampingRatio"] == pytest.approx(0.06, rel=0.01)
    assert res["summary"]["strainPct"] == pytest.approx(0.2, rel=0.01)


def test_soil_seismic_record_duration() -> None:
    # Squared accelerations: [0, 0, 0.01, 0.25, 0.25, 0.25, 0.25, 0.01, 0, 0], total = 1.02
    # 5% = 0.051 reached at t=3.0 s (cum=0.26); 95% = 0.969 reached at t=6.0 s (cum=1.01) -> D5-95 = 3.0 s
    res = features.run(
        "soilSeismic.recordDuration",
        None,
        {"accelerationG": "0 0 0.1 0.5 0.5 0.5 0.5 0.1 0 0", "timeStepS": 1.0},
    )
    assert res["problems"] == []
    assert res["summary"]["t5S"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["t95S"] == pytest.approx(6.0, rel=0.01)
    assert res["summary"]["significantDurationS"] == pytest.approx(3.0, rel=0.01)


def test_soil_seismic_retaining_displacement() -> None:
    # Ka = 1/3, pmax = 1/3 * 20 * 6 = 40.0 kPa
    # EI = 30e6 * (0.4^3 / 12) = 160000 kN*m^2/m
    # delta = pmax * H^4 / (30 * EI) = 40 * 1296 / 4.8e6 = 0.0108 m = 10.8 mm
    res = features.run(
        "soilSeismic.retainingDisplacement",
        None,
        {
            "heightM": 6.0,
            "wallThicknessM": 0.4,
            "concreteEMpa": 30000.0,
            "soilGammaKnM3": 20.0,
            "phiDeg": 30.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["activeBasePressureKpa"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["estimatedTopDisplacementMm"] == pytest.approx(10.8, rel=0.01)


def test_soil_seismic_earth_pressure() -> None:
    # Mononobe-Okabe with phi=30, kh=0.2, kv=0.1, H=5, gamma=20:
    # theta = atan(0.2 / 0.9) = 12.5288 deg; phi - theta = 17.4712 deg
    # Kae = cos^2(17.4712) / [cos^2(12.5288) * (1 + sqrt(sin30*sin17.4712/cos12.5288))^2] = 0.49266
    # Ka = 1/3 -> Pa = 0.5 * (1/3) * 20 * 25 = 83.333 kN/m
    # dPae = 0.5 * ((1 - 0.1)*0.49266 - 1/3) * 20 * 25 = 27.515 kN/m
    res = features.run(
        "soilSeismic.seismicEarthPressure",
        None,
        {
            "heightM": 5.0,
            "phiDeg": 30.0,
            "gammaKnM3": 20.0,
            "kh": 0.2,
            "kv": 0.1,
            "waterTableM": 100.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["staticKa"] == pytest.approx(1 / 3, rel=0.01)
    assert res["summary"]["seismicKae"] == pytest.approx(0.49266, rel=0.01)
    assert res["summary"]["staticResultantKnPerM"] == pytest.approx(83.333, rel=0.01)
    assert res["summary"]["seismicIncrementKnPerM"] == pytest.approx(27.515, rel=0.01)


def test_soil_seismic_slope_displacement() -> None:
    # Newmark block with ky = 0.1 g, dt = 0.1 s, a = [0.3, 0.0, 0.0] g:
    # Step 1: v = 0.2 * 9.80665 * 0.1 = 0.196133 m/s, d = 0.0196133 m
    # Step 2: v = 0.196133 - 0.1 * 9.80665 * 0.1 = 0.098067 m/s, d = 0.029420 m
    # Step 3: v = 0.0 m/s, d = 0.029420 m = 29.42 mm
    res = features.run(
        "soilSeismic.slopeDisplacement",
        None,
        {
            "accelerationG": "0.3\n0.0\n0.0",
            "timeStepS": 0.1,
            "yieldAccelerationG": 0.1,
            "slopeAngleDeg": 25.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["newmarkDisplacementMm"] == pytest.approx(29.420, rel=0.01)


def test_soil_seismic_time_history_pick() -> None:
    # EQ1 matches target M=7.0, Vs30=300, PGA=0.30 (scale=1.0, score=0.02*20=0.40) -> top pick.
    res = features.run(
        "soilSeismic.timeHistoryPick",
        None,
        {
            "recordRows": "EQ1, 7.0, 20, 300, 0.30, 30\nEQ2, 6.0, 50, 600, 0.10, 20",
            "targetMagnitude": 7.0,
            "targetPgaG": 0.30,
            "siteVs30": 300.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["topRecordId"] == "EQ1"
    eq2 = _row_by(res, "recordId", "EQ2")
    assert eq2["scaleFactor"] == pytest.approx(3.0, rel=0.01)


def test_soil_seismic_transfer_function() -> None:
    # Travel time t = 10/200 + 20/400 = 0.10 s -> f0 = 1/(4*0.10) = 2.5 Hz, T0 = 0.40 s
    # At resonance (f = 2.5 Hz, phase = pi/2), amplification = 1 / (2 * 0.05) = 10.0
    res = features.run(
        "soilSeismic.transferFunction",
        None,
        {"profileRows": "10, 200, 0.05\n20, 400, 0.05", "maximumFrequencyHz": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["travelTimeS"] == pytest.approx(0.10, rel=0.01)
    assert res["summary"]["fundamentalFrequencyHz"] == pytest.approx(2.5, rel=0.01)
    assert res["summary"]["fundamentalPeriodS"] == pytest.approx(0.40, rel=0.01)
    assert res["summary"]["maximumAmplification"] == pytest.approx(10.0, rel=0.01)


def test_soil_tests_brazilian_tensile() -> None:
    # sigma_t = 2 * P / (pi * D * t) = 2 * (1000 * pi) / (pi * 50 * 20) = 2.0 MPa
    res = features.run(
        "soilTests.brazilianTensile",
        None,
        {"loadN": 1000.0 * math.pi, "diameterMm": 50.0, "thicknessMm": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["indirectTensileStrengthMpa"] == pytest.approx(2.0, rel=0.01)


def test_soil_tests_point_load_index() -> None:
    # Is = 6400 / 40^2 = 4.0 MPa; F = (40 / 50)^0.45 = 0.90448; Is(50) = 4.0 * 0.90448 = 3.6179 MPa
    res = features.run(
        "soilTests.pointLoadIndex",
        None,
        {"loadN": 6400.0, "diameterMm": 40.0},
    )
    assert res["problems"] == []
    assert res["summary"]["pointLoadIsMpa"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["sizeCorrectionFactor"] == pytest.approx(0.9045, rel=0.01)
    assert res["summary"]["pointLoadIs50Mpa"] == pytest.approx(3.6179, rel=0.01)

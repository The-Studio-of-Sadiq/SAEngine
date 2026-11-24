"""Independent known-answer tests for FEM CFD, Wind Climate, Detailing, and Design calculators."""

from __future__ import annotations

import pytest

from saengine import features


def _row_by(res: dict, key: str, value: object, table_index: int = 0) -> dict:
    for row in res["tables"][table_index]["rows"]:
        if row[key] == value:
            return row
    raise AssertionError(f"No row with {key}={value!r} in {res['tables'][table_index]['rows']}")


# ── CFD Wind (fem_cfd.py: 23) ────────────────────────────────────────────────────────────────────


def test_fem_cfd_blockage_check() -> None:
    # A_bld = 20 * 30 = 600 m2; A_dom = 200 * 100 = 20000 m2 -> 100 * 600 / 20000 = 3.0% <= 4.0%.
    res = features.run(
        "femCfd.blockageCheck",
        None,
        {
            "projectedWidthM": 20.0,
            "buildingHeightM": 30.0,
            "domainWidthM": 200.0,
            "domainHeightM": 100.0,
            "maxBlockagePct": 4.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["blockagePercent"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["limitPercent"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_cfd_boundary_layers() -> None:
    # dy4 = 2.0 * 1.25^3 = 3.90625 mm
    # H_total = 2.0 * (1.25^4 - 1) / (1.25 - 1) = 2.0 * 1.44140625 / 0.25 = 11.53125 mm
    res = features.run(
        "femCfd.boundaryLayers",
        None,
        {"firstLayerMm": 2.0, "expansionRatio": 1.25, "nLayers": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["layers"] == 4
    assert res["summary"]["finalLayerMm"] == pytest.approx(3.90625, rel=0.01)
    assert res["summary"]["totalThicknessMm"] == pytest.approx(11.53125, rel=0.01)


def test_fem_cfd_cfd_mesh() -> None:
    # dx_surf = 8.0 / 2^2 = 2.0 m
    # bg_cells = 5,120,000 / 8^3 = 10,000; est_total = 10,000 * (1 + 0.35 * 2) = 17,000
    res = features.run(
        "femCfd.cfdMesh",
        None,
        {"baseCellM": 8.0, "surfaceLevel": 2.0, "domainVolumeM3": 5120000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["surfaceCellSizeM"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["estimatedCells"] == 17000


def test_fem_cfd_convergence_criteria() -> None:
    res = features.run(
        "femCfd.convergenceCriteria",
        None,
        {"residualTarget": 0.001, "forceDeltaPct": 0.25},
    )
    assert res["problems"] == []
    assert res["summary"]["residualTarget"] == pytest.approx(0.001, rel=0.01)
    assert res["summary"]["forceDriftPct"] == pytest.approx(0.25, rel=0.01)


def test_fem_cfd_domain_size() -> None:
    # Standard clearances: 5H upstream + 15H downstream = 20H, 5H sides (10H total), 5H above (6H total).
    # Lx = 12 + 20 * 20 = 412 m; Ly = 16 + 10 * 20 = 216 m; Lz = 6 * 20 = 120 m.
    # Volume = 412 * 216 * 120 = 10,679,040 m3.
    res = features.run(
        "femCfd.domainSize",
        None,
        {"buildingHeightM": 20.0, "planWidthM": 16.0, "planDepthM": 12.0},
    )
    assert res["problems"] == []
    assert res["summary"]["lengthM"] == pytest.approx(412.0, rel=0.01)
    assert res["summary"]["widthM"] == pytest.approx(216.0, rel=0.01)
    assert res["summary"]["heightM"] == pytest.approx(120.0, rel=0.01)
    assert res["summary"]["tunnelVolumeM3"] == pytest.approx(10679040.0, rel=0.01)


def test_fem_cfd_fluid_domain() -> None:
    # Standalone fallback building: H=15 m, Bx=18 m, By=12 m.
    # Lx = 18 + (4 + 12) * 15 = 258 m; Ly = 12 + 2 * 4 * 15 = 132 m; Lz = 15 * (1 + 4) = 75 m.
    # Volume = 258 * 132 * 75 = 2,554,200 m3.
    res = features.run(
        "femCfd.fluidDomain",
        None,
        {"upstreamH": 4.0, "downstreamH": 12.0, "sidesH": 4.0, "aboveH": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["buildingHeightM"] == pytest.approx(15.0, rel=0.01)
    assert res["summary"]["lengthM"] == pytest.approx(258.0, rel=0.01)
    assert res["summary"]["widthM"] == pytest.approx(132.0, rel=0.01)
    assert res["summary"]["heightM"] == pytest.approx(75.0, rel=0.01)
    assert res["summary"]["volumeM3"] == pytest.approx(2554200.0, rel=0.01)


def test_fem_cfd_gust_spectrum() -> None:
    # von Karman longitudinal PSD at f = 0.02 Hz:
    # var_u = 3.0^2 = 9.0 m2/s2; f_nd = 0.02 * 100 / 20 = 0.1
    # Su(0.02) = 4 * 9.0 * (100 / 20) / (1 + 70.78 * 0.1^2)^(5/6) = 180 / 1.7078^(5/6) = 115.2325 m2/s
    res = features.run(
        "femCfd.gustSpectrum",
        None,
        {"meanSpeedMs": 20.0, "integralScaleM": 100.0, "sigmaUMs": 3.0},
    )
    assert res["problems"] == []
    assert res["summary"]["varianceM2s2"] == pytest.approx(9.0, rel=0.01)
    assert res["summary"]["peakPsdM2s"] == pytest.approx(115.2325, rel=0.01)


def test_fem_cfd_incident_turbulence() -> None:
    # Iu = 1 / ln(30 / 0.1) = 1 / 5.70378 = 0.17532 -> 17.5322%
    # u* = 0.41 * 20 / ln(30.1 / 0.1) = 1.4368 m/s -> k = 1.4368^2 / sqrt(0.09) = 6.8814 m2/s2
    # Lu = 300 * (30 / 200)^(0.67 + 0.05 * ln(0.1)) = 300 * 0.15^0.55487 = 104.7028 m
    res = features.run(
        "femCfd.incidentTurbulence",
        None,
        {"heightM": 30.0, "z0M": 0.1, "uRefMs": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["turbulenceIntensityPct"] == pytest.approx(17.5322, rel=0.01)
    assert res["summary"]["tkeM2s2"] == pytest.approx(6.8814, rel=0.01)
    assert res["summary"]["lengthScaleM"] == pytest.approx(104.7028, rel=0.01)


def test_fem_cfd_initial_field() -> None:
    # u* = 0.41 * 20 / ln((20 + 0.1)/0.1) = 8.2 / 5.303305 = 1.5462 m/s
    # k = 1.5462^2 / 0.3 = 7.9692 m2/s2
    # eps = 1.5462^3 / (0.41 * 20.1) = 0.4486 m2/s3
    # omega = eps / (0.09 * k) = 0.6254 1/s
    res = features.run(
        "femCfd.initialField",
        None,
        {"uRefMs": 20.0, "z0M": 0.1, "heightM": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["ustar"] == pytest.approx(1.5462, rel=0.01)
    assert res["summary"]["k"] == pytest.approx(7.9692, rel=0.01)
    assert res["summary"]["epsilon"] == pytest.approx(0.4486, rel=0.01)
    assert res["summary"]["omega"] == pytest.approx(0.6254, rel=0.01)


def test_fem_cfd_inlet_profile() -> None:
    # Same ABL parameters at zRef=20 m, uRef=20 m/s, z0=0.1 m:
    # u* = 1.5462 m/s, k = 7.9692 m2/s2, eps(Href) = 0.4486 m2/s3
    # At z = 2.0 m: U(2) = (1.5462 / 0.41) * ln(2.1 / 0.1) = 11.4816 m/s
    res = features.run(
        "femCfd.inletProfile",
        None,
        {"z0M": 0.1, "zRefM": 20.0, "uRefMs": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["ustarMs"] == pytest.approx(1.5462, rel=0.01)
    assert res["summary"]["kM2s2"] == pytest.approx(7.9692, rel=0.01)
    assert res["summary"]["epsilonAtHrefM2s3"] == pytest.approx(0.4486, rel=0.01)
    row_2m = _row_by(res, "heightM", 2.0)
    assert row_2m["speedMs"] == pytest.approx(11.4816, rel=0.01)


def test_fem_cfd_outlet() -> None:
    # 300 / 20 = 15.0 H >= 12.0 H -> adequate = True
    res = features.run(
        "femCfd.outlet",
        None,
        {"gaugePressurePa": 5.0, "downstreamDistM": 300.0, "buildingHeightM": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["downstreamH"] == pytest.approx(15.0, rel=0.01)
    assert res["summary"]["adequate"] is True
    assert res["summary"]["outletPressurePa"] == pytest.approx(5.0, rel=0.01)


def test_fem_cfd_parallel_cores() -> None:
    # 4.0e6 / 32 = 125,000 cells/core (inside 25k..250k sweet spot)
    res = features.run("femCfd.parallelCores", None, {"totalCellsM": 4.0, "cores": 32.0})
    assert res["problems"] == []
    assert res["summary"]["cores"] == 32
    assert res["summary"]["cellsPerCore"] == 125000
    assert res["summary"]["inSweetSpot"] is True


def test_fem_cfd_profile_exponent() -> None:
    # log10(0.1) = -1 -> alpha = 0.24 + 0.096*(-1) + 0.016*(-1)^2 = 0.16
    res = features.run("femCfd.profileExponent", None, {"z0M": 0.1, "zGradientM": 400.0})
    assert res["problems"] == []
    assert res["summary"]["powerLawAlpha"] == pytest.approx(0.16, rel=0.01)


def test_fem_cfd_profile_library() -> None:
    # Open Terrain (z0 = 0.03 m) at H_ref = 20 m, U_ref = 15 m/s:
    # u* = 0.41 * 15 / ln(20.03 / 0.03) = 6.15 / 6.50379 = 0.9456 m/s
    # k = 0.9456^2 / 0.3 = 2.9805 m2/s2
    res = features.run("femCfd.profileLibrary", None, {"zRefM": 20.0, "uRefMs": 15.0})
    assert res["problems"] == []
    assert res["summary"]["profiles"] == 6
    open_row = _row_by(res, "exposure", "Open Terrain")
    assert open_row["ustarMs"] == pytest.approx(0.9456, rel=0.01)
    assert open_row["kM2s2"] == pytest.approx(2.9805, rel=0.01)


def test_fem_cfd_reference_height() -> None:
    # U(30) = 25 * ln(30.1 / 0.1) / ln(10.1 / 0.1) = 25 * 5.70711 / 4.61512 = 30.9153 m/s
    # q_ref = 0.5 * 1.225 * 30.9153^2 / 1000 = 0.5854 kPa
    res = features.run(
        "femCfd.referenceHeight",
        None,
        {"roofHeightM": 30.0, "z0M": 0.1, "u10Ms": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["uRefMs"] == pytest.approx(30.9153, rel=0.01)
    assert res["summary"]["qRefKpa"] == pytest.approx(0.5854, rel=0.01)


def test_fem_cfd_refinement_zones() -> None:
    # Far wake: level 2 -> 8/4 = 2.0 m; Near wake: level 3 -> 8/8 = 1.0 m; Roof: level 5 -> 8/32 = 0.25 m.
    res = features.run(
        "femCfd.refinementZones",
        None,
        {"baseCellM": 8.0, "nearWakeLevel": 3.0, "roofEdgeLevel": 5.0, "buildingHeightM": 30.0},
    )
    assert res["problems"] == []
    assert res["summary"]["zones"] == 3
    assert res["summary"]["finestCellM"] == pytest.approx(0.25, rel=0.01)
    assert _row_by(res, "zone", "Far Wake")["xExtentM"] == pytest.approx(180.0, rel=0.01)


def test_fem_cfd_relaxation_factors() -> None:
    # sumPU = 0.25 + 0.65 = 0.90
    res = features.run(
        "femCfd.relaxationFactors",
        None,
        {"pRelax": 0.25, "uRelax": 0.65, "turbRelax": 0.45},
    )
    assert res["problems"] == []
    assert res["summary"]["sumPU"] == pytest.approx(0.90, rel=0.01)


def test_fem_cfd_result_sampling() -> None:
    # tiers = round(32 / 4) = 8; totalTaps = 8 * 20 = 160; step = 360 / 12 = 30 deg.
    res = features.run(
        "femCfd.resultSampling",
        None,
        {"nDirections": 12.0, "buildingHeightM": 32.0, "probesPerTier": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["directions"] == 12
    assert res["summary"]["elevationTiers"] == 8
    assert res["summary"]["totalTaps"] == 160
    assert res["tables"][0]["rows"][0]["stepDeg"] == pytest.approx(30.0, rel=0.01)


def test_fem_cfd_roughness() -> None:
    # open: z0 = 0.03 m; ks = 9.793 * 0.03 / 0.4 = 0.734475 m
    res = features.run("femCfd.roughness", None, {"terrain": "open", "cs": 0.4})
    assert res["problems"] == []
    assert res["summary"]["z0M"] == pytest.approx(0.03, rel=0.01)
    assert res["summary"]["sandGrainKsM"] == pytest.approx(0.734475, rel=0.01)


def test_fem_cfd_solver_iterations() -> None:
    # checkpoints = 1500 // 300 = 5
    res = features.run(
        "femCfd.solverIterations",
        None,
        {"maxIter": 1500.0, "writeInterval": 300.0, "averageWindow": 300.0},
    )
    assert res["problems"] == []
    assert res["summary"]["checkpoints"] == 5
    assert res["summary"]["averageWindow"] == 300


def test_fem_cfd_time_stepping() -> None:
    # dt = 0.5 * 0.4 / 40.0 = 0.005 s; steps = 60.0 / 0.005 = 12000
    res = features.run(
        "femCfd.timeStepping",
        None,
        {"cellSizeM": 0.4, "windSpeedMs": 40.0, "targetCfl": 0.5, "durationS": 60.0},
    )
    assert res["problems"] == []
    assert res["summary"]["timeStepS"] == pytest.approx(0.005, rel=0.01)
    assert res["summary"]["totalSteps"] == 12000


def test_fem_cfd_wall_treatment() -> None:
    # Lookup: y+ < 5 -> "Viscous sublayer"
    res = features.run("femCfd.wallTreatment", None, {"yPlus": 2.0})
    assert res["problems"] == []
    assert res["summary"]["regime"] == "Viscous sublayer"


def test_fem_cfd_y_plus_check() -> None:
    # Re_L = 30 * 20 / 1.5e-5 = 4.0e7
    # Cf = 0.058 * (4.0e7)^(-0.2) = 0.00174886
    # u_tau = 30 * sqrt(0.5 * 0.00174886) = 0.88740 m/s
    # y+ = (0.5 * 0.003) * 0.88740 / 1.5e-5 = 88.74
    res = features.run(
        "femCfd.yPlusCheck",
        None,
        {"uRefMs": 30.0, "charLengthM": 20.0, "firstCellMm": 3.0},
    )
    assert res["problems"] == []
    assert res["summary"]["reynoldsNumber"] == pytest.approx(4.0e7, rel=0.01)
    assert res["summary"]["uTauMs"] == pytest.approx(0.8874, rel=0.01)
    assert res["summary"]["yPlus"] == pytest.approx(88.74, rel=0.01)


# ── Wind Climate (fem_wind_climate.py: 18) ──────────────────────────────────────────────────────


def test_fem_wind_climate_apply_to_facades() -> None:
    # Default settings: V = 44 m/s, I = 1.0; BNBC 2020 Exposure C: alpha=11.5, zg=213.36 m, Kd=0.85, G=0.85
    # Kz(30m) = 2.01 * (30 / 213.36)^(2/11.5) = 1.4290
    # qz = 0.000613 * 1.4290 * 0.85 * 44^2 * 1.0 * 0.85 (G) = 1.2253 kPa
    res = features.run(
        "femWindClimate.applyToFacades",
        None,
        {"heightM": 30.0, "exposure": "C"},
    )
    assert res["problems"] == []
    assert res["summary"]["roofQzKpa"] == pytest.approx(1.2253, rel=0.01)
    assert res["summary"]["exposure"] == "C"


def test_fem_wind_climate_compare_standards() -> None:
    # V50 = 50 m/s, z = 20 m; BNBC 2020 defines C and B (skips D):
    # Exp C (alpha=11.5, zg=213.36): Kz = 2.01 * (20 / 213.36)^(2/11.5) = 1.3317
    # qz = 0.000613 * 1.3317 * 0.85 * 50^2 = 1.7347 kPa
    res = features.run(
        "femWindClimate.compareStandards",
        None,
        {"v50Ms": 50.0, "heightM": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["terrainClasses"] == 2
    assert res["summary"]["maxQzKpa"] == pytest.approx(1.7347, rel=0.01)


def test_fem_wind_climate_confidence_bands() -> None:
    # Gumbel MoM standard error (Kite 1975):
    # y_50 = -ln(-ln(1 - 1/50)) = 3.90194
    # K_50 = (3.90194 - 0.57721566) * sqrt(6) / pi = 2.59229
    # SE = 4.0 * sqrt((1 + 1.14 * 2.59229 + 1.1 * 2.59229^2) / 36) = 2.2457 m/s
    # lower95 = 48.0 - 1.96 * 2.2457 = 43.5984 m/s; upper95 = 48.0 + 1.96 * 2.2457 = 52.4016 m/s
    res = features.run(
        "femWindClimate.confidenceBands",
        None,
        {"vTM": 48.0, "sampleStdMs": 4.0, "nYears": 36.0, "returnPeriodYr": 50.0},
    )
    assert res["problems"] == []
    assert res["summary"]["stdErrorMs"] == pytest.approx(2.2457, rel=0.01)
    assert res["summary"]["lower95Ms"] == pytest.approx(43.5984, rel=0.01)
    assert res["summary"]["upper95Ms"] == pytest.approx(52.4016, rel=0.01)


def test_fem_wind_climate_directional_analysis() -> None:
    # 4 sectors of 50.0 m/s * [0.80, 0.90, 1.00, 0.85] -> peak = 50.0 m/s; at 90 deg: 45.0 m/s, qRatio = 0.81
    res = features.run(
        "femWindClimate.directionalAnalysis",
        None,
        {"omnidirectionalMs": 50.0, "dirFactors": "0.80, 0.90, 1.00, 0.85"},
    )
    assert res["problems"] == []
    assert res["summary"]["sectors"] == 4
    assert res["summary"]["peakSectorSpeedMs"] == pytest.approx(50.0, rel=0.01)
    row_90 = _row_by(res, "azimuthDeg", 90.0)
    assert row_90["speedMs"] == pytest.approx(45.0, rel=0.01)
    assert row_90["qRatio"] == pytest.approx(0.81, rel=0.01)


def test_fem_wind_climate_directional_cases() -> None:
    # 360 / 45 = 8 directions starting at 0 deg
    res = features.run("femWindClimate.directionalCases", None, {"stepDeg": 45.0})
    assert res["problems"] == []
    assert res["summary"]["directions"] == 8
    assert res["tables"][0]["rows"][2]["azimuthDeg"] == pytest.approx(90.0, rel=0.01)


def test_fem_wind_climate_fatigue_wind() -> None:
    # P(U > 12) = exp(-(12 / 6)^1.9) = exp(-3.73213) = 0.0239416
    # activeHours = 40 * 8760 * 0.0239416 = 8389.185 h; cycles = int(8389.185 * 3600 * 0.25) = 7550266
    res = features.run(
        "femWindClimate.fatigueWind",
        None,
        {"designLifeYr": 40.0, "weibullScaleMs": 6.0, "thresholdMs": 12.0},
    )
    assert res["problems"] == []
    assert res["summary"]["activeHours"] == pytest.approx(8389.185, rel=0.01)
    assert res["summary"]["estimatedCycles"] == 7550266


def test_fem_wind_climate_fetch_distance() -> None:
    # h_IBL = 0.28 * 0.2 * (2000 / 0.2)^0.8 = 0.056 * 1584.893 = 88.754 m
    res = features.run("femWindClimate.fetchDistance", None, {"fetchKm": 2.0, "z0NewM": 0.2})
    assert res["problems"] == []
    assert res["summary"]["iblHeightM"] == pytest.approx(88.754, rel=0.01)


def test_fem_wind_climate_gumbel_fit() -> None:
    # alpha = 5.0 * sqrt(6) / pi = 3.89848; u = 40.0 - 0.57721566 * 3.89848 = 37.74974
    # y_100 = -ln(-ln(0.99)) = 4.60015 -> V_100 = 37.74974 + 3.89848 * 4.60015 = 55.6833 m/s
    res = features.run(
        "femWindClimate.gumbelFit",
        None,
        {"sampleMeanMs": 40.0, "sampleStdMs": 5.0, "returnPeriodYr": 100.0},
    )
    assert res["problems"] == []
    assert res["summary"]["scaleAlpha"] == pytest.approx(3.8985, rel=0.01)
    assert res["summary"]["modeMs"] == pytest.approx(37.7497, rel=0.01)
    assert res["summary"]["predictedSpeedMs"] == pytest.approx(55.6833, rel=0.01)


def test_fem_wind_climate_load_generation() -> None:
    # Default settings: V = 44 m/s, Exp A (alpha=7.0, zg=365.76, zmin=9.14, Kd=0.85, G=0.85, I=1.0).
    # H = 20 m -> round(20/3.5) = 6 storeys, dz = 20/6 = 3.3333 m, Cp = 1.3, B = 15 m.
    # For z <= 9.14 m (S1=3.33, S2=6.67): Kz = 2.01*(9.14/365.76)^(2/7) = 0.7007 -> q*G = 0.5947*0.85 = 0.5055?
    # Note: exposure_coefficient floors height at 4.57 m (default kzMinHeight):
    # S1..S6 pressures sum * 1.3 * 15 * (20/6) = 246.4331 kN (check scaling in B as well).
    res = features.run("femWindClimate.loadGeneration", None, {"heightM": 20.0, "widthM": 15.0})
    assert res["problems"] == []
    assert res["summary"]["baseShearKn"] == pytest.approx(246.4331, rel=0.01)
    res_double_b = features.run(
        "femWindClimate.loadGeneration", None, {"heightM": 20.0, "widthM": 30.0}
    )
    assert res_double_b["summary"]["baseShearKn"] == pytest.approx(2.0 * 246.4331, rel=0.01)


def test_fem_wind_climate_return_periods() -> None:
    # Cook's Gumbel factor: ((1 - 0.2*ln(-ln(1 - 1/T))) / (1 - 0.2*ln(-ln(0.98))))^0.5
    # denom = 1 - 0.2 * ln(-ln(0.98)) = 1.780388
    # T=100: num = 1 - 0.2*ln(-ln(0.99)) = 1.920030 -> factor = 1.038477 -> V100 = 50 * 1.038477 = 51.9238 m/s
    # T=700: num = 1 - 0.2*ln(-ln(1-1/700)) = 2.310126 -> factor = 1.139084 -> V700 = 56.9542 m/s
    res = features.run("femWindClimate.returnPeriods", None, {"v50Ms": 50.0})
    assert res["problems"] == []
    assert res["summary"]["v50Ms"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["v100Ms"] == pytest.approx(51.9238, rel=0.01)
    assert res["summary"]["v700Ms"] == pytest.approx(56.9542, rel=0.01)


def test_fem_wind_climate_roughness_length() -> None:
    # Lookup: 0.01 < z0 = 0.03 <= 0.05 -> "Open terrain"
    res = features.run("femWindClimate.roughnessLength", None, {"z0M": 0.03})
    assert res["problems"] == []
    assert res["summary"]["wmoClass"] == "Open terrain"


def test_fem_wind_climate_sector_table() -> None:
    # 8 sectors -> step = 360 / 8 = 45.0 deg; sector 1 spans 337.5..22.5 around 0.0 deg.
    # Default site Exp A at z = 20 m, V = 44 m/s: Kz = 2.01*(20/365.76)^(2/7) = 0.8761 -> q_ref = 0.7512 kPa.
    res = features.run("femWindClimate.sectorTable", None, {"nSectors": 8.0})
    assert res["problems"] == []
    assert res["summary"]["sectors"] == 8
    assert res["summary"]["stepDeg"] == pytest.approx(45.0, rel=0.01)
    assert res["summary"]["qRefKpa"] == pytest.approx(0.7512, rel=0.01)
    r0 = res["tables"][0]["rows"][0]
    assert r0["startDeg"] == pytest.approx(337.5, rel=0.01)
    assert r0["endDeg"] == pytest.approx(22.5, rel=0.01)


def test_fem_wind_climate_service_wind() -> None:
    # T = 10 yr: factor = sqrt((1 - 0.2*ln(-ln(0.9))) / (1 - 0.2*ln(-ln(0.98)))) = sqrt(1.45007 / 1.780388) = 0.90248
    # V_SLS = 50 * 0.90248 = 45.124 m/s; q_ratio = 0.90248^2 = 0.8145
    res = features.run("femWindClimate.serviceWind", None, {"v50Ms": 50.0, "serviceMriYr": 10.0})
    assert res["problems"] == []
    assert res["summary"]["serviceWindMs"] == pytest.approx(45.124, rel=0.01)
    assert res["summary"]["qRatioVs50Yr"] == pytest.approx(0.8145, rel=0.01)


def test_fem_wind_climate_shelter_factor() -> None:
    # gap_ratio = 30 / 15 = 2.0; h_ratio = 15 / 30 = 0.5
    # Ms = 1 - 0.25 * 0.5 * exp(-0.25 * 2.0) = 1 - 0.125 * 0.606531 = 0.92418
    res = features.run(
        "femWindClimate.shelterFactor",
        None,
        {"buildingHeightM": 30.0, "blockerHeightM": 15.0, "spacingM": 30.0},
    )
    assert res["problems"] == []
    assert res["summary"]["gapOverBlockerHeight"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["shelterFactor"] == pytest.approx(0.9242, rel=0.01)


def test_fem_wind_climate_site_summary() -> None:
    # Default site: V = 44 m/s, Exp A (alpha=7.0, zg=365.76 m), Kd = 0.85, I = 1.0
    # Kz(30m) = 2.01 * (30 / 365.76)^(2/7) = 0.9838
    # qz = 0.000613 * 0.9838 * 0.85 * 44^2 = 0.9924 kPa
    res = features.run("femWindClimate.siteSummary", None, {"roofHeightM": 30.0})
    assert res["problems"] == []
    assert res["summary"]["windSpeedMs"] == pytest.approx(44.0, rel=0.01)
    assert res["summary"]["roofQzKpa"] == pytest.approx(0.9924, rel=0.01)


def test_fem_wind_climate_storm_duration() -> None:
    # Durst curve: V_3600 / V_3s = 1.00 / 1.53 -> 51.0 * (1.00 / 1.53) = 33.3333 m/s
    res = features.run(
        "femWindClimate.stormDuration",
        None,
        {"gust3sMs": 51.0, "targetAvg": "3600s"},
    )
    assert res["problems"] == []
    assert res["summary"]["convertedSpeedMs"] == pytest.approx(33.3333, rel=0.01)


def test_fem_wind_climate_terrain_categories() -> None:
    # BNBC 2020 defines A, B, C (3 categories). At z = 20 m:
    # Exp A (alpha=7, zg=365.76): Kz = 2.01 * (20 / 365.76)^(2/7) = 0.8761
    # Exp C (alpha=11.5, zg=213.36): Kz = 2.01 * (20 / 213.36)^(2/11.5) = 1.3317
    res = features.run("femWindClimate.terrainCategories", None, {"heightM": 20.0})
    assert res["problems"] == []
    assert res["summary"]["categories"] == 3
    assert _row_by(res, "exposure", "A")["kz"] == pytest.approx(0.8761, rel=0.01)
    assert _row_by(res, "exposure", "C")["kz"] == pytest.approx(1.3317, rel=0.01)


def test_fem_wind_climate_topographic_factor() -> None:
    # BNBC 2020 ridge Exp C: k1/(H/Lh) = 1.55, gamma = 3.0, mu = 1.5
    # H/Lh = 30 / 100 = 0.30 -> K1 = 1.55 * 0.30 = 0.465
    # K2 = 1 - 25 / (1.5 * 100) = 0.83333; K3 = exp(-3.0 * 10 / 100) = 0.74082
    # Kzt = (1 + 0.465 * 0.83333 * 0.74082)^2 = 1.287067^2 = 1.6565 -> speed gain = 28.7067%
    res = features.run(
        "femWindClimate.topographicFactor",
        None,
        {
            "featureType": "ridge",
            "hillHeightM": 30.0,
            "halfLengthM": 100.0,
            "distanceM": 25.0,
            "evalHeightM": 10.0,
            "exposure": "C",
        },
    )
    assert res["problems"] == []
    assert res["summary"]["kzt"] == pytest.approx(1.6565, rel=0.01)
    assert res["summary"]["speedGainPercent"] == pytest.approx(28.7067, rel=0.01)


# ── Detailing (fem_detailing.py: 16) ─────────────────────────────────────────────────────────────


def test_fem_detailing_assembly_detail() -> None:
    # Pick offset = 0.207 * 10.0 = 2.07 m
    # Load/pick = 800 * 9.80665 / 1000 * 1.5 / 4 = 2.9420 kN
    res = features.run(
        "femDetailing.assemblyDetail",
        None,
        {"cageLengthM": 10.0, "cageMassKg": 800.0, "liftingPoints": 4},
    )
    assert res["problems"] == []
    assert res["summary"]["pickOffsetM"] == pytest.approx(2.07, rel=0.01)
    assert res["summary"]["designLoadPerPickKn"] == pytest.approx(2.9420, rel=0.01)


def test_fem_detailing_bar_spacing() -> None:
    # inner = 350 - 2 * (40 + 10) = 250 mm; clear = (250 - 4 * 25) / 3 = 50.0 mm >= 26.7 mm
    res = features.run(
        "femDetailing.barSpacing",
        None,
        {"beamWidthMm": 350.0, "coverMm": 40.0, "stirrupMm": 10.0, "barDiaMm": 25.0, "barCount": 4},
    )
    assert res["problems"] == []
    assert res["summary"]["clearSpacingMm"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_detailing_beam_detailing() -> None:
    # Defaults: fc=28, fy=420; d = 800 - 50 = 750 mm; depth > 750 -> skinBarsRequired True
    # As,min = max(0.25*sqrt(28), 1.4) * 350 * 750 / 420 = 1.4 * 350 * 750 / 420 = 875.0 mm2
    res = features.run(
        "femDetailing.beamDetailing",
        None,
        {"spanMm": 8000.0, "widthMm": 350.0, "depthMm": 800.0},
    )
    assert res["problems"] == []
    assert res["summary"]["asMinMm2"] == pytest.approx(875.0, rel=0.01)
    assert res["summary"]["skinBarsRequired"] is True


def test_fem_detailing_bending_diagram() -> None:
    # Cut length = 1500 + 400 - 2 * 20 = 1860.0 mm
    res = features.run(
        "femDetailing.bendingDiagram",
        None,
        {"straightLegMm": 1500.0, "hookLegMm": 400.0, "barDiaMm": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["cuttingLengthMm"] == pytest.approx(1860.0, rel=0.01)


def test_fem_detailing_column_detailing() -> None:
    # Default pack rho_min = 0.01 -> As,min = 0.01 * 500 * 600 = 3000 mm2
    # Max tie spacing = min(16*25, 48*10, 500) = min(400, 480, 500) = 400 mm
    res = features.run(
        "femDetailing.columnDetailing",
        None,
        {"bMm": 500.0, "hMm": 600.0, "barDiaMm": 25.0, "tieDiaMm": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["minSteelMm2"] == pytest.approx(3000.0, rel=0.01)
    assert res["summary"]["maxTieSpacingMm"] == pytest.approx(400.0, rel=0.01)


def test_fem_detailing_confinement_zones() -> None:
    # lo = max(500, 3600 / 6, 450) = 600.0 mm
    res = features.run(
        "femDetailing.confinementZones",
        None,
        {"columnDepthMm": 500.0, "clearHeightMm": 3600.0},
    )
    assert res["problems"] == []
    assert res["summary"]["confinementLengthMm"] == pytest.approx(600.0, rel=0.01)


def test_fem_detailing_curtailment() -> None:
    # ext = max(550, 12*25, 8000/16) = max(550, 300, 500) = 550 mm
    # topCutoff = 0.25 * 8000 + 550 = 2550 mm
    res = features.run(
        "femDetailing.curtailment",
        None,
        {"spanMm": 8000.0, "effectiveDepthMm": 550.0, "barDiaMm": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["cutoffExtensionMm"] == pytest.approx(550.0, rel=0.01)
    assert res["summary"]["topCutoffFromSupportMm"] == pytest.approx(2550.0, rel=0.01)


def test_fem_detailing_detail_dimensions() -> None:
    # clearSpanMm = 6400 mm; c/c = 6400 + 500 = 6900 mm
    res = features.run(
        "femDetailing.detailDimensions",
        None,
        {"spanMm": 6400.0, "supportWidthMm": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["clearSpanMm"] == pytest.approx(6400.0, rel=0.01)
    assert res["summary"]["centreToCentreMm"] == pytest.approx(6900.0, rel=0.01)


def test_fem_detailing_detail_scale() -> None:
    # plotted = 600 / 20 = 30.0 mm; CAD text height = 2.5 * 20 = 50.0 mm
    res = features.run(
        "femDetailing.detailScale",
        None,
        {"scaleDenominator": 20, "memberDepthMm": 600.0},
    )
    assert res["problems"] == []
    assert res["summary"]["scale"] == "1:20"
    assert res["summary"]["plottedDepthMm"] == pytest.approx(30.0, rel=0.01)


def test_fem_detailing_openings_trim_bars() -> None:
    # Interrupted = 600 * (1200/1000) = 720 mm2 -> 360 mm2/side; A_bar(16) = 201.06 mm2 -> ceil(360/201.06) = 2
    res = features.run(
        "femDetailing.openingsTrimBars",
        None,
        {"openingWidthMm": 1200.0, "slabSteelMm2PerM": 600.0, "trimBarDiaMm": 16.0},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredPerSideMm2"] == pytest.approx(360.0, rel=0.01)
    assert res["summary"]["barsPerSide"] == 2


def test_fem_detailing_punching_rebar() -> None:
    # Interior square column 450x450, d = 200 mm, fc = 28 MPa, phi = 0.75:
    # b0 = 4 * (450 + 200) = 2600 mm; lambda_s = min(1, sqrt(2/(1 + 0.004*200))) = 1.0
    # vc = 0.33 * sqrt(28) = 1.7462 MPa -> phiVc = 0.75 * 1.7462 * 2600 * 200 / 1000 = 681.016 kN
    # DCR = 500 / 681.016 = 0.7342
    res = features.run(
        "femDetailing.punchingRebar",
        None,
        {"vuKn": 500.0, "c1Mm": 450.0, "c2Mm": 450.0, "dMm": 200.0},
    )
    assert res["problems"] == []
    assert res["summary"]["utilisation"] == pytest.approx(0.7342, rel=0.01)
    r0 = res["tables"][0]["rows"][0]
    assert r0["perimeterMm"] == pytest.approx(2600.0, rel=0.01)
    assert r0["phiVcKn"] == pytest.approx(681.016, rel=0.01)


def test_fem_detailing_rebar_anchorage() -> None:
    # Default pack (BNBC 2020), fc=28, fy=420, straight 20 mm bar:
    # ld = fy / (1.7 * sqrt(fc)) * db = 420 / (1.7 * sqrt(28)) * 20 = 933.7946 mm
    res = features.run("femDetailing.rebarAnchorage", None, {"barDiaMm": 20.0, "bentHook": False})
    assert res["problems"] == []
    assert res["summary"]["anchorageLengthMm"] == pytest.approx(933.7946, rel=0.01)


def test_fem_detailing_section_details() -> None:
    # coreWidth = 450 - 2*45 = 360 mm; coreDepth = 700 - 2*45 = 610 mm
    res = features.run(
        "femDetailing.sectionDetails",
        None,
        {"widthMm": 450.0, "depthMm": 700.0, "coverMm": 45.0},
    )
    assert res["problems"] == []
    assert res["summary"]["coreWidthMm"] == pytest.approx(360.0, rel=0.01)
    assert res["summary"]["coreDepthMm"] == pytest.approx(610.0, rel=0.01)


def test_fem_detailing_slab_detailing() -> None:
    # Default pack shrinkage ratio (fy=420) = 0.0018 -> As,min = 0.0018 * 1000 * 200 = 360.0 mm2/m
    # Provided (10 mm @ 150 mm): pi * 5^2 * (1000 / 150) = 523.5988 mm2/m >= 360; 150 <= 450 -> passes
    res = features.run(
        "femDetailing.slabDetailing",
        None,
        {"thicknessMm": 200.0, "barDiaMm": 10.0, "providedSpacingMm": 150.0},
    )
    assert res["problems"] == []
    assert res["summary"]["asMinMm2PerM"] == pytest.approx(360.0, rel=0.01)
    assert res["summary"]["asProvidedMm2PerM"] == pytest.approx(523.5988, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_detailing_splice_design() -> None:
    # Default pack (BNBC 2020) compression lap (fy=420 <= 420, fc=28 >= 21):
    # l_comp = max(0.071 * 420 * 20, 300) = 596.4 mm
    res = features.run(
        "femDetailing.spliceDesign",
        None,
        {"barDiaMm": 20.0, "compressionOnly": True},
    )
    assert res["problems"] == []
    assert res["summary"]["lapLengthMm"] == pytest.approx(596.4, rel=0.01)


def test_fem_detailing_splice_length() -> None:
    # Default pack (BNBC 2020), db=16 mm (<= 19 mm -> denom 2.1), topBar=True (psi_t = 1.3), fc=28, fy=420:
    # ld = 420 * 1.3 / (2.1 * sqrt(28)) * 16 = 786.1661 mm
    # Class A = 1.0 * ld = 786.1661 mm; Class B = 1.3 * ld = 1022.0159 mm
    res = features.run("femDetailing.spliceLength", None, {"barDiaMm": 16.0, "topBar": True})
    assert res["problems"] == []
    assert res["summary"]["classALapMm"] == pytest.approx(786.1661, rel=0.01)
    assert res["summary"]["classBLapMm"] == pytest.approx(1022.0159, rel=0.01)


# ── Design (fem_design.py: 2) ────────────────────────────────────────────────────────────────────


def test_design_buckling_length() -> None:
    # Braced (nonsway) alignment chart for psiA = psiB = 1.0:
    # Solve (x/2)^2 + (1 - x/tan(x)) + 2*tan(x/2)/x - 1 = 0 for x = pi/K in [pi, 2*pi] -> x = 4.0574
    # K = pi / 4.0574 = 0.7743; K * lu = 0.7743 * 4000 = 3097.06 mm
    res = features.run(
        "design.bucklingLength",
        None,
        {"psiA": 1.0, "psiB": 1.0, "clearLengthMm": 4000.0, "swayFrame": False},
    )
    assert res["problems"] == []
    assert res["summary"]["kFactor"] == pytest.approx(0.7743, rel=0.01)
    assert res["summary"]["effectiveLengthMm"] == pytest.approx(3097.06, rel=0.01)


def test_design_development_length() -> None:
    # Default pack (BNBC 2020), db=25 mm (>19 -> denom 1.7), topBar=True (psi_t=1.3), cover=70 (>=65 -> 0.7):
    # ld = 420 * 1.3 / (1.7 * sqrt(28)) * 25 = 1517.4162 mm
    # ldc = max(0.24 * 420 * 25 / sqrt(28), 0.043 * 420 * 25, 200) = 476.2352 mm
    # ldh = 0.24 * 420 * 25 / sqrt(28) * 0.7 = 333.3647 mm
    res = features.run(
        "design.developmentLength",
        None,
        {"barDiameterMm": 25.0, "topBar": True, "clearCoverMm": 70.0},
    )
    assert res["problems"] == []
    assert res["summary"]["tensionLengthMm"] == pytest.approx(1517.4162, rel=0.01)
    assert res["summary"]["compressionLengthMm"] == pytest.approx(476.2352, rel=0.01)
    assert res["summary"]["hookLengthMm"] == pytest.approx(333.3647, rel=0.01)

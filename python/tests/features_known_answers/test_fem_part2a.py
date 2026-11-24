"""Independent known-answer tests for FEM CFD Dispersion, Seismic Detailing, and Model calculators."""

from __future__ import annotations

import math

import pytest

from saengine import features


def _row_by(res: dict, key: str, value: object, table_index: int = 0) -> dict:
    for row in res["tables"][table_index]["rows"]:
        if row[key] == value:
            return row
    raise AssertionError(f"No row with {key}={value!r} in {res['tables'][table_index]['rows']}")


# ── CFD Dispersion (fem_cfd_dispersion.py: 21) ──────────────────────────────────────────────────


def test_fem_cfd_dispersion_add_source() -> None:
    res = features.run(
        "femCfdDispersion.addSource",
        None,
        {"sourceName": "Chimney-A", "xM": 15.0, "yM": -8.0, "heightM": 24.0, "rateGs": 8.0},
    )
    assert res["problems"] == []
    assert res["summary"]["source"] == "Chimney-A"
    assert res["summary"]["rateGs"] == pytest.approx(8.0, rel=0.01)
    assert res["summary"]["heightM"] == pytest.approx(24.0, rel=0.01)
    r0 = res["tables"][0]["rows"][0]
    assert r0["xM"] == pytest.approx(15.0, rel=0.01)
    assert r0["yM"] == pytest.approx(-8.0, rel=0.01)


def test_fem_cfd_dispersion_air_exchange() -> None:
    # ACH = 3600 * 0.5 / 900 = 2.0 1/hr; tau = 1 / 2.0 = 0.5 hr
    res = features.run(
        "femCfdDispersion.airExchange",
        None,
        {"infiltrationM3s": 0.5, "roomVolumeM3": 900.0},
    )
    assert res["problems"] == []
    assert res["summary"]["ach"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["timeConstantHr"] == pytest.approx(0.5, rel=0.01)


def test_fem_cfd_dispersion_buoyant_plume() -> None:
    # Fb = 0.0089 * 1000 = 8.9 m4/s3
    # dh = 1.6 * 8.9^(1/3) * 125^(2/3) / 4.0 = 1.6 * 2.07235 * 25 / 4 = 20.7235 m
    res = features.run(
        "femCfdDispersion.buoyantPlume",
        None,
        {"heatFluxKw": 1000.0, "windSpeedMs": 4.0, "distanceM": 125.0},
    )
    assert res["problems"] == []
    assert res["summary"]["buoyancyFluxM4s3"] == pytest.approx(8.9, rel=0.01)
    assert res["summary"]["plumeRiseM"] == pytest.approx(20.7235, rel=0.01)


def test_fem_cfd_dispersion_chemical_reaction() -> None:
    # Da = 0.005 * 200 = 1.0; converted = 100 * (1 - exp(-1)) = 63.2121%
    res = features.run(
        "femCfdDispersion.chemicalReaction",
        None,
        {"rateConstantPerS": 0.005, "ozonePpb": 50.0, "residenceS": 200.0},
    )
    assert res["problems"] == []
    assert res["summary"]["damkohlerNumber"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["convertedPercent"] == pytest.approx(63.2121, rel=0.01)


def test_fem_cfd_dispersion_concentration_map() -> None:
    # Peak on grid occurs at (x=100, y=0) under stability D (ay=0.08, az=0.06):
    # sy = 8 / sqrt(1.01) = 7.9603 m, sz = 6 / sqrt(1.02) = 5.9409 m
    # vert = exp(-0.5 * ((2-10)/5.9409)^2) + exp(-0.5 * ((2+10)/5.9409)^2) = 0.4039 + 0.1299 = 0.5338
    # C = 8000 / (2 * pi * 2 * 7.9603 * 5.9409) * 0.5338 = 7.1872 mg/m3
    res = features.run(
        "femCfdDispersion.concentrationMap",
        None,
        {"rateGs": 8.0, "windSpeedMs": 2.0, "receptorHeightM": 2.0, "sourceHeightM": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["gridPoints"] == 9
    assert res["summary"]["maxConcMgM3"] == pytest.approx(7.1872, rel=0.01)


def test_fem_cfd_dispersion_deposition_velocity() -> None:
    # vd = 0.015 + 1 / (40 + 60) = 0.015 + 0.010 = 0.025 m/s
    res = features.run(
        "femCfdDispersion.depositionVelocity",
        None,
        {"settlingVelMs": 0.015, "aerodynamicResSm": 40.0, "surfaceResSm": 60.0},
    )
    assert res["problems"] == []
    assert res["summary"]["depositionVelocityMs"] == pytest.approx(0.025, rel=0.01)


def test_fem_cfd_dispersion_dispersion_report() -> None:
    # Stability D, Q=4 g/s = 4000 mg/s, u=4 m/s:
    # At x=25 m: sy=2/sqrt(1.0025)=1.9975, sz=1.5/sqrt(1.005)=1.4963 -> C = 106.5011 mg/m3
    # At x=100 m: C = 6.731 > 5.0; at x=200 m: sy=15.842, sz=11.767 -> C = 1.708 <= 5.0 -> safeSetbackM = 200 m
    res = features.run(
        "femCfdDispersion.dispersionReport",
        None,
        {"rateGs": 4.0, "windSpeedMs": 4.0, "limitMgM3": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["safeSetbackM"] == pytest.approx(200.0, rel=0.01)
    assert res["summary"]["maxConcMgM3"] == pytest.approx(106.5011, rel=0.01)


def test_fem_cfd_dispersion_dose_estimate() -> None:
    # C*t = 15 * 40 = 600 mg*min/m3; Dose = 15 * (25 / 1000) * 40 = 15.0 mg
    res = features.run(
        "femCfdDispersion.doseEstimate",
        None,
        {"concMgM3": 15.0, "exposureMin": 40.0, "inhalationLmin": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["ctIndexMgMinM3"] == pytest.approx(600.0, rel=0.01)
    assert res["summary"]["inhaledDoseMg"] == pytest.approx(15.0, rel=0.01)


def test_fem_cfd_dispersion_emission_rate() -> None:
    # Q = 12 * 250 / 1000 = 3.0 g/s = 3.0 * 3.6 = 10.8 kg/hr
    res = features.run(
        "femCfdDispersion.emissionRate",
        None,
        {"volFlowM3s": 12.0, "exhaustConcMgM3": 250.0},
    )
    assert res["problems"] == []
    assert res["summary"]["massRateGs"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["massRateKghr"] == pytest.approx(10.8, rel=0.01)


def test_fem_cfd_dispersion_evacuation_zone() -> None:
    # Stability D, Q=20 g/s = 20000 mg/s, u=5 m/s, threshold=10 mg/m3:
    # At x=150 m: sy=12/sqrt(1.015)=11.9110, sz=9/sqrt(1.03)=8.8680 -> C0=12.054 >= 10 (at 175 m: 8.888 < 10)
    # Peak half-width at x=100 m: sy=7.9603, C0=26.924 -> hw = 7.9603 * sqrt(2 * ln(2.6924)) = 11.2035 m
    res = features.run(
        "femCfdDispersion.evacuationZone",
        None,
        {"rateGs": 20.0, "windSpeedMs": 5.0, "thresholdMgM3": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["downwindSetbackM"] == pytest.approx(150.0, rel=0.01)
    assert res["summary"]["maxHalfWidthM"] == pytest.approx(11.2035, rel=0.01)


def test_fem_cfd_dispersion_exceedance_check() -> None:
    # 12.0 / 8.0 = 1.50 > 1.0 -> passes False
    res = features.run(
        "femCfdDispersion.exceedanceCheck",
        None,
        {"predictedMgM3": 12.0, "twaLimitMgM3": 8.0},
    )
    assert res["problems"] == []
    assert res["summary"]["utilisation"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["passes"] is False


def test_fem_cfd_dispersion_facade_leakage() -> None:
    # A_eff = 2.0e-4 * 500 = 0.1 m2
    # Q_in = 0.65 * 0.1 * sqrt(2 * 49 / 1.225) = 0.065 * sqrt(80) = 0.58138 m3/s
    # ingress = 0.58138 * 8.0 = 4.6510 mg/s
    res = features.run(
        "femCfdDispersion.facadeLeakage",
        None,
        {
            "deltaPPa": 49.0,
            "leakageAreaCm2M2": 2.0,
            "facadeAreaM2": 500.0,
            "outdoorConcMgM3": 8.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["infiltrationFlowM3s"] == pytest.approx(0.5814, rel=0.01)
    assert res["summary"]["pollutantIngressMgS"] == pytest.approx(4.6510, rel=0.01)


def test_fem_cfd_dispersion_gas_properties() -> None:
    # M = 16.04 g/mol (methane), T = 27 C = 300.15 K:
    # rho = 101325 * 0.01604 / (8.3145 * 300.15) = 0.65119 kg/m3
    # rel = 0.65119 / 1.184 = 0.5500 < 0.95 -> "Buoyant"
    res = features.run(
        "femCfdDispersion.gasProperties",
        None,
        {"molarMassGmol": 16.04, "tempC": 27.0, "schmidtNumber": 0.8},
    )
    assert res["problems"] == []
    assert res["summary"]["gasDensityKgM3"] == pytest.approx(0.6512, rel=0.01)
    assert res["summary"]["relativeDensity"] == pytest.approx(0.5500, rel=0.01)
    assert res["summary"]["regime"] == "Buoyant"


def test_fem_cfd_dispersion_hvac_intake() -> None:
    # C_exh = 3.0 * 1000 / 5.0 = 600 mg/m3
    # D_min = (sqrt(5.0 / 5.0) * 15.0 + 1.0)^2 = 16^2 = 256.0
    # C_intake = 600 / 256 = 2.34375 mg/m3
    res = features.run(
        "femCfdDispersion.hvacIntake",
        None,
        {"exhaustRateGs": 3.0, "distanceM": 15.0, "exhaustFlowM3s": 5.0, "windSpeedMs": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["dilutionFactor"] == pytest.approx(256.0, rel=0.01)
    assert res["summary"]["intakeConcMgM3"] == pytest.approx(2.34375, rel=0.01)


def test_fem_cfd_dispersion_particulate_size() -> None:
    # d = 20 um = 2e-5 m, rho_p = 1810 kg/m3, mu_air = 1.81e-5 Pa*s:
    # vs = 1810 * (2e-5)^2 * 9.81 / (18 * 1.81e-5) = 0.02180 m/s
    res = features.run(
        "femCfdDispersion.particulateSize",
        None,
        {"diameterUm": 20.0, "particleDensityKgM3": 1810.0},
    )
    assert res["problems"] == []
    assert res["summary"]["settlingVelocityMs"] == pytest.approx(0.0218, rel=0.01)
    assert res["tables"][0]["rows"][0]["pmClass"] == "Coarse"


def test_fem_cfd_dispersion_release_timing() -> None:
    # Q_avg = 40 * 1000 / 500 = 80.0 g/s
    res = features.run(
        "femCfdDispersion.releaseTiming",
        None,
        {"mode": "intermittent", "durationS": 500.0, "totalMassKg": 40.0},
    )
    assert res["problems"] == []
    assert res["summary"]["mode"] == "intermittent"
    assert res["summary"]["averageRateGs"] == pytest.approx(80.0, rel=0.01)


def test_fem_cfd_dispersion_source_height() -> None:
    # dh = 3.0 * 1.0 * (15.0 / 5.0) = 9.0 m; H_eff = 20.0 + 9.0 = 29.0 m
    res = features.run(
        "femCfdDispersion.sourceHeight",
        None,
        {"stackHeightM": 20.0, "stackDiameterM": 1.0, "exitSpeedMs": 15.0, "windSpeedMs": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["plumeRiseM"] == pytest.approx(9.0, rel=0.01)
    assert res["summary"]["effectiveHeightM"] == pytest.approx(29.0, rel=0.01)


def test_fem_cfd_dispersion_species_decay() -> None:
    # t = 200 / 2 = 100 s = t1/2 -> C/C0 = 0.50; k = ln(2) / 100 = 0.006931 1/s
    res = features.run(
        "femCfdDispersion.speciesDecay",
        None,
        {"halfLifeS": 100.0, "distanceM": 200.0, "windSpeedMs": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["travelTimeS"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["decayRatePerS"] == pytest.approx(math.log(2.0) / 100.0, rel=0.01)
    assert res["summary"]["remainingFraction"] == pytest.approx(0.50, rel=0.01)


def test_fem_cfd_dispersion_terrain_effects() -> None:
    # speedup = 1 + 1.6 * 0.25 = 1.40; eff_sigma_z = 16 * (1 + 0.5 * 0.25) = 18.0 m
    res = features.run(
        "femCfdDispersion.terrainEffects",
        None,
        {"hillHeightM": 40.0, "hillSlope": 0.25, "baseSigmaZM": 16.0},
    )
    assert res["problems"] == []
    assert res["summary"]["windSpeedup"] == pytest.approx(1.40, rel=0.01)
    assert res["summary"]["effectiveSigmaZM"] == pytest.approx(18.0, rel=0.01)


def test_fem_cfd_dispersion_threshold_limits() -> None:
    res = features.run(
        "femCfdDispersion.thresholdLimits",
        None,
        {"twa8hMgM3": 3.0, "stel15mMgM3": 9.0, "idlhMgM3": 75.0},
    )
    assert res["problems"] == []
    assert res["summary"]["twaMgM3"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["stelMgM3"] == pytest.approx(9.0, rel=0.01)
    assert res["summary"]["idlhMgM3"] == pytest.approx(75.0, rel=0.01)


def test_fem_cfd_dispersion_wind_driven() -> None:
    # Stability C (ay=0.11, az=0.08), Q=12 g/s = 12000 mg/s, u=4 m/s, H=15 m:
    # Peak on grid [50..800] is at x=100 m: sy=11/sqrt(1.01)=10.9454, sz=8/sqrt(1.02)=7.9212
    # C = 12000 / (pi * 4 * 10.9454 * 7.9212) * exp(-0.5 * (15/7.9212)^2) = 11.0185 * 0.16640 = 1.8335 mg/m3
    res = features.run(
        "femCfdDispersion.windDriven",
        None,
        {"rateGs": 12.0, "windSpeedMs": 4.0, "effectiveHeightM": 15.0, "stability": "C"},
    )
    assert res["problems"] == []
    assert res["summary"]["stability"] == "C"
    assert res["summary"]["peakGroundMgM3"] == pytest.approx(1.8335, rel=0.01)


# ── Seismic Detailing (fem_design_seismic_detailing.py: 20) ──────────────────────────────────────


def test_fem_design_seismic_detailing_anchorage_detail() -> None:
    # Default materials fc=28, fy=420:
    # ldh = max(420 * 25 / (5.4 * sqrt(28)), 8 * 25, 150) = 367.4655 mm <= 450 - 50 = 400 mm -> True
    res = features.run(
        "femDesignSeismicDetailing.anchorageDetail",
        None,
        {"barDiaMm": 25.0, "columnDepthMm": 450.0},
    )
    assert res["problems"] == []
    assert res["summary"]["seismicHookLengthMm"] == pytest.approx(367.4655, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_design_seismic_detailing_bar_development() -> None:
    # min_hc = 20 * 25 = 500 mm > 450 mm provided -> passes False
    res = features.run(
        "femDesignSeismicDetailing.barDevelopment",
        None,
        {"beamBarDiaMm": 25.0, "columnDepthMm": 450.0},
    )
    assert res["problems"] == []
    assert res["summary"]["minColumnDepthMm"] == pytest.approx(500.0, rel=0.01)
    assert res["summary"]["passes"] is False


def test_fem_design_seismic_detailing_beam_column_joint() -> None:
    # Default fc=28, fy=420; exterior confinement gamma=1.25 (SI):
    # Vj = 1.25 * 2000 * 420 / 1000 - 200 = 1050 - 200 = 850.0 kN
    # phiVn = 0.85 * 1.25 * sqrt(28) * (500 * 500) / 1000 = 1405.5554 kN
    # DCR = 850 / 1405.5554 = 0.6047 -> passes True
    res = features.run(
        "femDesignSeismicDetailing.beamColumnJoint",
        None,
        {
            "columnWidthMm": 500.0,
            "columnDepthMm": 500.0,
            "beamTopSteelMm2": 2000.0,
            "columnShearKn": 200.0,
            "confinement": "exterior",
        },
    )
    assert res["problems"] == []
    assert res["summary"]["jointShearDemandKn"] == pytest.approx(850.0, rel=0.01)
    assert res["summary"]["jointCapacityKn"] == pytest.approx(1405.5554, rel=0.01)
    assert res["summary"]["utilisation"] == pytest.approx(0.6047, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_design_seismic_detailing_boundary_elements() -> None:
    # c_limit = 5000 / (600 * 1.5 * 0.01) = 5000 / 9 = 555.56 mm; c=1000 >= 555.56 -> True
    # boundaryLength = max(1000 - 0.1*5000, 0.5*1000) = 500.0 mm
    # Ash/s = 0.09 * (380 - 80) * 28 / 420 = 0.09 * 300 * 28 / 420 = 1.80 mm2/mm
    res = features.run(
        "femDesignSeismicDetailing.boundaryElements",
        None,
        {
            "neutralAxisDepthMm": 1000.0,
            "wallLengthMm": 5000.0,
            "wallThicknessMm": 380.0,
            "designDriftRatio": 0.01,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["specialBoundaryRequired"] is True
    assert res["summary"]["boundaryLengthMm"] == pytest.approx(500.0, rel=0.01)
    assert res["summary"]["ashOverS"] == pytest.approx(1.80, rel=0.01)


def test_fem_design_seismic_detailing_buckling_restrained() -> None:
    # Py = 4000 * 250 / 1000 = 1000 kN; Tmax = 1.4 * 1000 = 1400 kN; Cmax = 1.4 * 1.1 * 1000 = 1540 kN
    res = features.run(
        "femDesignSeismicDetailing.bucklingRestrained",
        None,
        {"coreAreaMm2": 4000.0, "coreFyMpa": 250.0, "omegaHardening": 1.4, "betaComp": 1.1},
    )
    assert res["problems"] == []
    assert res["summary"]["yieldForceKn"] == pytest.approx(1000.0, rel=0.01)
    assert res["summary"]["maxTensionKn"] == pytest.approx(1400.0, rel=0.01)
    assert res["summary"]["maxCompressionKn"] == pytest.approx(1540.0, rel=0.01)


def test_fem_design_seismic_detailing_confinement_check() -> None:
    # 300 / 250 = 1.20 > 1.0 -> passes False
    res = features.run(
        "femDesignSeismicDetailing.confinementCheck",
        None,
        {"providedAshMm2": 250.0, "requiredAshMm2": 300.0},
    )
    assert res["problems"] == []
    assert res["summary"]["dcr"] == pytest.approx(1.20, rel=0.01)
    assert res["summary"]["passes"] is False


def test_fem_design_seismic_detailing_confinement_zones() -> None:
    # Column: lo = max(600, 4200 / 6, 450) = 700.0 mm
    res = features.run(
        "femDesignSeismicDetailing.confinementZones",
        None,
        {"memberDepthMm": 600.0, "clearSpanOrHeightMm": 4200.0, "memberKind": "column"},
    )
    assert res["problems"] == []
    assert res["summary"]["confinementLengthMm"] == pytest.approx(700.0, rel=0.01)


def test_fem_design_seismic_detailing_coupling_beam() -> None:
    # ln/h = 1200/800 = 1.5 < 2.0; d = 740 mm; vu = 800e3 / (300*740) = 3.6036 MPa > 0.33*sqrt(28) = 1.7462 -> True
    # alpha = atan2(800 - 120, 1200) = atan2(680, 1200) -> sin(alpha) = 680 / hypot(1200, 680) = 0.4930
    # Avd = 800e3 / (2 * 0.85 * 420 * 0.4930) = 2272.22 mm2
    res = features.run(
        "femDesignSeismicDetailing.couplingBeam",
        None,
        {"clearSpanMm": 1200.0, "depthMm": 800.0, "widthMm": 300.0, "shearVuKn": 800.0},
    )
    assert res["problems"] == []
    assert res["summary"]["aspectRatio"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["diagonalBarsRequired"] is True
    assert res["summary"]["avdPerGroupMm2"] == pytest.approx(2272.22, rel=0.01)


def test_fem_design_seismic_detailing_crosstie_spacing() -> None:
    # s_vert = min(360/3, 6*25, 150) = 120.0 mm; legs = ceil(700 / 200) + 1 = 4 + 1 = 5
    res = features.run(
        "femDesignSeismicDetailing.crosstieSpacing",
        None,
        {"boundaryLengthMm": 700.0, "wallThicknessMm": 360.0, "longBarDiaMm": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["maxVerticalSpacingMm"] == pytest.approx(120.0, rel=0.01)
    assert res["summary"]["requiredCrosstieLegs"] == 5


def test_fem_design_seismic_detailing_ductility_check() -> None:
    # T1=0.4 < Tc=0.6 -> mu_phi = 1 + 2 * (4.0 - 1) * (0.6 / 0.4) = 1 + 6 * 1.5 = 10.0
    res = features.run(
        "femDesignSeismicDetailing.ductilityCheck",
        None,
        {"q0": 4.0, "t1S": 0.4, "tcS": 0.6, "ductilityClass": "DCM"},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredCurvatureDuctility"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["ductilityClass"] == "DCM"


def test_fem_design_seismic_detailing_friction_damper() -> None:
    # mu = 400 / (2 * 500) = 0.40; E = 4 * 400 * (50 / 1000) = 80.0 kJ
    res = features.run(
        "femDesignSeismicDetailing.frictionDamper",
        None,
        {"slipLoadKn": 400.0, "strokeMm": 50.0, "boltClampKn": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredFrictionMu"] == pytest.approx(0.40, rel=0.01)
    assert res["summary"]["energyPerCycleKj"] == pytest.approx(80.0, rel=0.01)


def test_fem_design_seismic_detailing_hinge_region() -> None:
    # zone = 2 * 600 = 1200 mm; s_max = min(520/4, 6*22, 150) = min(130, 132, 150) = 130.0 mm
    res = features.run(
        "femDesignSeismicDetailing.hingeRegion",
        None,
        {"beamDepthMm": 600.0, "longBarDiaMm": 22.0, "effDepthMm": 520.0},
    )
    assert res["problems"] == []
    assert res["summary"]["hingeZoneLengthMm"] == pytest.approx(1200.0, rel=0.01)
    assert res["summary"]["maxStirrupSpacingMm"] == pytest.approx(130.0, rel=0.01)


def test_fem_design_seismic_detailing_hoop_size() -> None:
    # Default fc=28, fy=420; Ag = 500*500 = 250000, Ach = 400*400 = 160000 -> Ag/Ach - 1 = 0.5625
    # Eq 6.8.7: 0.3 * 400 * (28/420) * 0.5625 = 4.50 mm2/mm (governs over 0.09*400*28/420 = 2.40)
    # Ash_req = 4.50 * 100 = 450.0 mm2
    res = features.run(
        "femDesignSeismicDetailing.hoopSize",
        None,
        {
            "coreWidthBcMm": 400.0,
            "coreDepthHcMm": 400.0,
            "grossWidthMm": 500.0,
            "grossDepthMm": 500.0,
            "spacingMm": 100.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["ashOverS"] == pytest.approx(4.50, rel=0.01)
    assert res["summary"]["ashRequiredMm2"] == pytest.approx(450.0, rel=0.01)


def test_fem_design_seismic_detailing_hoop_spacing() -> None:
    # b/4 = 480/4 = 120 mm; 6*db = 120 mm; so = 100 + (350 - 260)/3 = 130 mm -> min = 120.0 mm
    res = features.run(
        "femDesignSeismicDetailing.hoopSpacing",
        None,
        {"leastDimensionMm": 480.0, "longBarDiaMm": 20.0, "crosstieSpacingHxMm": 260.0},
    )
    assert res["problems"] == []
    assert res["summary"]["maxHoopSpacingMm"] == pytest.approx(120.0, rel=0.01)


def test_fem_design_seismic_detailing_joint_transverse() -> None:
    # bc=400 -> Ach=160000, Ag=250000 -> Ag/Ach - 1 = 0.5625 -> Ash/s = 4.50 mm2/mm * 100 = 450.0 mm2
    res = features.run(
        "femDesignSeismicDetailing.jointTransverse",
        None,
        {"coreWidthMm": 400.0, "columnAreaMm2": 250000.0, "hoopSpacingMm": 100.0},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredJointHoopAreaMm2"] == pytest.approx(450.0, rel=0.01)


def test_fem_design_seismic_detailing_lap_splice() -> None:
    # Default pack BNBC 2020, fc=28, fy=420, db=25 mm (>19 -> denom 1.7):
    # ld = 420 / (1.7 * sqrt(28)) * 25 = 1167.243 mm -> Class B = 1.3 * 1167.243 = 1517.416 mm
    # midHeightWindow = 3600 - 2 * 600 = 2400 mm >= 1517.416 -> fitsOutsideHinge True
    res = features.run(
        "femDesignSeismicDetailing.lapSplice",
        None,
        {"barDiaMm": 25.0, "clearHeightMm": 3600.0, "loZoneMm": 600.0},
    )
    assert res["problems"] == []
    assert res["summary"]["lapLengthMm"] == pytest.approx(1517.4162, rel=0.01)
    assert res["summary"]["midHeightWindowMm"] == pytest.approx(2400.0, rel=0.01)
    assert res["summary"]["fitsOutsideHinge"] is True


def test_fem_design_seismic_detailing_overstrength_factor() -> None:
    # Explicit override Omega0 = 2.5 passed through to em_factors and 8 code-pack combinations.
    res = features.run(
        "femDesignSeismicDetailing.overstrengthFactor",
        None,
        {"omega0Override": 2.5},
    )
    assert res["problems"] == []
    assert res["summary"]["omega0"] == pytest.approx(2.5, rel=0.01)
    assert res["summary"]["combinations"] == 8


def test_fem_design_seismic_detailing_shear_demand() -> None:
    # Ve_sway = (300 + 360) / 6.0 = 110.0 kN; Ve = 110 + 90 = 200.0 kN
    res = features.run(
        "femDesignSeismicDetailing.shearDemand",
        None,
        {"mprLeftKnm": 300.0, "mprRightKnm": 360.0, "clearSpanM": 6.0, "gravityShearKn": 90.0},
    )
    assert res["problems"] == []
    assert res["summary"]["plasticHingeShearKn"] == pytest.approx(110.0, rel=0.01)
    assert res["summary"]["designShearVeKn"] == pytest.approx(200.0, rel=0.01)


def test_fem_design_seismic_detailing_wall_web_rebar() -> None:
    # Two curtains of 16 mm @ 250 mm in 300 mm wall:
    # rho = 2 * pi * 8^2 / (300 * 250) = 402.1239 / 75000 = 0.005362 >= 0.0025 -> passes True
    res = features.run(
        "femDesignSeismicDetailing.wallWebRebar",
        None,
        {"wallThicknessMm": 300.0, "barDiaMm": 16.0, "spacingMm": 250.0},
    )
    assert res["problems"] == []
    assert res["summary"]["providedRatio"] == pytest.approx(0.005362, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_design_seismic_detailing_yielding_steel() -> None:
    # Vy = 0.60 * 200 * 20 * 250 / 1000 = 600.0 kN; Vcap = 1.3 * 600 = 780.0 kN
    res = features.run(
        "femDesignSeismicDetailing.yieldingSteel",
        None,
        {
            "plateThicknessMm": 20.0,
            "fuseWidthMm": 250.0,
            "fuseFyMpa": 200.0,
            "overstrengthOmega": 1.3,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["nominalYieldKn"] == pytest.approx(600.0, rel=0.01)
    assert res["summary"]["capacityProtectedDemandKn"] == pytest.approx(780.0, rel=0.01)


# ── FEM Model (fem_model.py: 16) ────────────────────────────────────────────────────────────────


def test_fem_model_add_member() -> None:
    # 3-4-5 horizontal triangle in XY: L = 5.0 m, axial unit vector (0.6, 0.8, 0.0), isVertical False
    res = features.run(
        "femModel.addMember",
        None,
        {"x1M": 1.0, "y1M": 2.0, "z1M": 0.0, "x2M": 4.0, "y2M": 6.0, "z2M": 0.0},
    )
    assert res["problems"] == []
    assert res["summary"]["lengthM"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["isVertical"] is False
    ax = res["tables"][0]["rows"][0]
    assert ax["x"] == pytest.approx(0.6, rel=0.01)
    assert ax["y"] == pytest.approx(0.8, rel=0.01)


def test_fem_model_add_node() -> None:
    res = features.run(
        "femModel.addNode",
        None,
        {"xM": 3.5, "yM": 4.5, "zM": 6.4, "restraint": "1,1,1,0,0,0"},
    )
    assert res["problems"] == []
    assert res["summary"]["xM"] == pytest.approx(3.5, rel=0.01)
    assert res["summary"]["yM"] == pytest.approx(4.5, rel=0.01)
    assert res["summary"]["zM"] == pytest.approx(6.4, rel=0.01)
    assert res["tables"][0]["rows"][0]["restraint"] == "1,1,1,0,0,0"


def test_fem_model_add_shell() -> None:
    # 8 x 4 rectangle: A = 32 m2, P = 24 m, V = 32 * 0.2 = 6.4 m3, centroid = (4.0, 2.0)
    res = features.run(
        "femModel.addShell",
        None,
        {"vertices": "0,0; 8,0; 8,4; 0,4", "thicknessMm": 200.0},
    )
    assert res["problems"] == []
    assert res["summary"]["areaM2"] == pytest.approx(32.0, rel=0.01)
    assert res["summary"]["perimeterM"] == pytest.approx(24.0, rel=0.01)
    assert res["summary"]["volumeM3"] == pytest.approx(6.4, rel=0.01)
    assert res["summary"]["centroidXM"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["centroidYM"] == pytest.approx(2.0, rel=0.01)


def test_fem_model_add_solid() -> None:
    # V = 3 * 2 * 1.6 = 9.6 m3; W = 9.6 * 25 = 240 kN; mesh = min(3,2,1.6)*1000/4 = 400 mm
    res = features.run(
        "femModel.addSolid",
        None,
        {"widthM": 3.0, "depthM": 2.0, "heightM": 1.6, "densityKnM3": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["volumeM3"] == pytest.approx(9.6, rel=0.01)
    assert res["summary"]["weightKn"] == pytest.approx(240.0, rel=0.01)
    assert res["summary"]["recommendedMeshMm"] == pytest.approx(400.0, rel=0.01)


def test_fem_model_copy_replicate() -> None:
    # 4 copies * (5, 1, 3) -> totalShiftX = 20 m, totalShiftZ = 12 m
    res = features.run(
        "femModel.copyReplicate",
        None,
        {"dxM": 5.0, "dyM": 1.0, "dzM": 3.0, "copies": 4},
    )
    assert res["problems"] == []
    assert res["summary"]["copies"] == 4
    assert res["summary"]["totalShiftXM"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["totalShiftZM"] == pytest.approx(12.0, rel=0.01)


def test_fem_model_duplicate_storey() -> None:
    # shift = 7.5 - 4.0 = 3.5 m
    res = features.run(
        "femModel.duplicateStorey",
        None,
        {"sourceElevM": 4.0, "targetElevM": 7.5},
    )
    assert res["problems"] == []
    assert res["summary"]["shiftZM"] == pytest.approx(3.5, rel=0.01)
    assert res["summary"]["elementsMatched"] == 0


def test_fem_model_generate_bracing() -> None:
    # Chevron V with B=8 m (half=4 m), H=3 m -> L = hypot(4, 3) = 5.0 m, 2 braces -> total = 10.0 m
    # angle = atan2(3, 4) = 36.8699 deg
    res = features.run(
        "femModel.generateBracing",
        None,
        {"pattern": "V", "bayWidthM": 8.0, "storeyHeightM": 3.0},
    )
    assert res["problems"] == []
    assert res["summary"]["braceLengthM"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["angleDeg"] == pytest.approx(36.8699, rel=0.01)
    assert res["summary"]["totalSteelLengthM"] == pytest.approx(10.0, rel=0.01)


def test_fem_model_mirror_selection() -> None:
    # Reflect (3, 7) across Y = 5 -> (3, 2*5 - 7) = (3, 3)
    res = features.run(
        "femModel.mirrorSelection",
        None,
        {"xM": 3.0, "yM": 7.0, "axis": "yEquals", "planeCoordM": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["mirroredXM"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["mirroredYM"] == pytest.approx(3.0, rel=0.01)


def test_fem_model_move_node() -> None:
    # (1, 2, 3) + (3, 4, 0) = (4, 6, 3), shift = 5.0 m
    res = features.run(
        "femModel.moveNode",
        None,
        {"x0M": 1.0, "y0M": 2.0, "z0M": 3.0, "dxM": 3.0, "dyM": 4.0, "dzM": 0.0},
    )
    assert res["problems"] == []
    assert res["summary"]["newXM"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["newYM"] == pytest.approx(6.0, rel=0.01)
    assert res["summary"]["newZM"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["shiftDistanceM"] == pytest.approx(5.0, rel=0.01)


def test_fem_model_parametric_frame() -> None:
    # 4 x 3 bays, 3 storeys @ 3.5 m:
    # nodes = 5 * 4 * 4 = 80; cols = 5 * 4 * 3 = 60; bx = 4 * 4 * 3 = 48; by = 5 * 3 * 3 = 45
    # members = 60 + 48 + 45 = 153; totalHeight = 3 * 3.5 = 10.5 m
    res = features.run(
        "femModel.parametricFrame",
        None,
        {
            "baysX": 4,
            "baysY": 3,
            "bayWidthXM": 7.0,
            "bayWidthYM": 5.0,
            "storeys": 3,
            "storeyHeightM": 3.5,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["nodes"] == 80
    assert res["summary"]["members"] == 153
    assert res["summary"]["totalHeightM"] == pytest.approx(10.5, rel=0.01)


def test_fem_model_rigid_links() -> None:
    # sqrt(300^2 + 400^2 + 0^2) = 500.0 mm
    res = features.run(
        "femModel.rigidLinks",
        None,
        {"dxMm": 300.0, "dyMm": 400.0, "dzMm": 0.0},
    )
    assert res["problems"] == []
    assert res["summary"]["offsetLengthMm"] == pytest.approx(500.0, rel=0.01)


def test_fem_model_rotate_selection() -> None:
    # Rotate (5, 2) by +90 deg CCW around (1, 2): dx=4, dy=0 -> dx'=0, dy'=4 -> (1, 6)
    res = features.run(
        "femModel.rotateSelection",
        None,
        {"xM": 5.0, "yM": 2.0, "originXM": 1.0, "originYM": 2.0, "angleDeg": 90.0},
    )
    assert res["problems"] == []
    assert res["summary"]["rotatedXM"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["rotatedYM"] == pytest.approx(6.0, rel=0.01)


def test_fem_model_scale_selection() -> None:
    # (4*1.5, 5*2.0, 6*0.5) = (6.0, 10.0, 3.0)
    res = features.run(
        "femModel.scaleSelection",
        None,
        {"xM": 4.0, "yM": 5.0, "zM": 6.0, "scaleX": 1.5, "scaleY": 2.0, "scaleZ": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["scaledXM"] == pytest.approx(6.0, rel=0.01)
    assert res["summary"]["scaledYM"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["scaledZM"] == pytest.approx(3.0, rel=0.01)


def test_fem_model_section_assign() -> None:
    # b=400, h=600 -> A = 240,000 mm2; Ix = 400*600^3/12 = 7.2e9 mm4; Iy = 600*400^3/12 = 3.2e9 mm4
    # J = 600 * 400^3 * (1/3 - 0.21 * (400/600) * (1 - (400/600)^4 / 12)) = 7.51249e9 mm4
    res = features.run(
        "femModel.sectionAssign",
        None,
        {"widthMm": 400.0, "depthMm": 600.0, "eMpa": 30000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["areaMm2"] == pytest.approx(240000.0, rel=0.01)
    assert res["summary"]["ixMm4"] == pytest.approx(7.2e9, rel=0.01)
    assert res["summary"]["iyMm4"] == pytest.approx(3.2e9, rel=0.01)
    assert res["tables"][0]["rows"][0]["jMm4"] == pytest.approx(7.51249e9, rel=0.01)


def test_fem_model_split_member() -> None:
    # 0.25 * 8 = 2.0 m, 0.75 * 8 = 6.0 m
    res = features.run("femModel.splitMember", None, {"lengthM": 8.0, "splitRatio": 0.25})
    assert res["problems"] == []
    assert res["summary"]["segment1M"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["segment2M"] == pytest.approx(6.0, rel=0.01)


def test_fem_model_storey_generator() -> None:
    # base = 1.0 m, 4 storeys @ 3.5 m -> 5 levels, roof = 1.0 + 4*3.5 = 15.0 m
    res = features.run(
        "femModel.storeyGenerator",
        None,
        {"baseElevM": 1.0, "count": 4, "typicalHeightM": 3.5},
    )
    assert res["problems"] == []
    assert res["summary"]["levels"] == 5
    assert res["summary"]["roofElevationM"] == pytest.approx(15.0, rel=0.01)

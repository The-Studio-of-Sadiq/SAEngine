"""Independent known-answer tests for FEM Fire Design, Pedestrian CFD, and Diaphragms & Links calculators."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from saengine import features
from saengine.library.settings import default_project_settings


def _row_by(res: dict, key: str, value: object, table_index: int = 0) -> dict:
    for row in res["tables"][table_index]["rows"]:
        if row[key] == value:
            return row
    raise AssertionError(f"No row with {key}={value!r} in {res['tables'][table_index]['rows']}")


# ── Fire Design (fem_design_fire.py: 21) ─────────────────────────────────────────────────────────


def test_fem_design_fire_board_encasement() -> None:
    # [Am/V]_box = (1200 / 8000) * 1000 = 150.0 1/m
    # R = (30 / 1000) / 0.15 = 0.20 m2*K/W
    res = features.run(
        "femDesignFire.boardEncasement",
        None,
        {"boardThicknessMm": 30.0, "boxPerimeterMm": 1200.0, "steelAreaMm2": 8000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["boxedAmVPerM"] == pytest.approx(150.0, rel=0.01)
    assert res["summary"]["boardRValue"] == pytest.approx(0.2, rel=0.01)


def test_fem_design_fire_capacity_check() -> None:
    # Default pack (BNBC 2020) has no steelFire table -> linear retention:
    # ky(600) = 1 - (600 - 400)/800 = 0.75; Tcr(0.5) = 400 + (1 - 0.5)*400 = 600.0 C
    # DCR = 0.5 / 0.75 = 0.6667 <= 1.0 -> passes True
    res = features.run(
        "femDesignFire.capacityCheck",
        None,
        {"loadRatioMu0": 0.5, "steelTempC": 600.0},
    )
    assert res["problems"] == []
    assert res["summary"]["kyTheta"] == pytest.approx(0.75, rel=0.01)
    assert res["summary"]["criticalTempC"] == pytest.approx(600.0, rel=0.01)
    assert res["summary"]["utilisation"] == pytest.approx(0.6667, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_design_fire_catenary_action() -> None:
    # sag = 500 mm = 0.5 m -> T = 20 * 10^2 / (8 * 0.5) = 2000 / 4 = 500.0 kN
    res = features.run(
        "femDesignFire.catenaryAction",
        None,
        {"udlKnPerM": 20.0, "spanM": 10.0, "sagMm": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["catenaryTensionKn"] == pytest.approx(500.0, rel=0.01)


def test_fem_design_fire_compartment_size() -> None:
    # Af = 100 m2 -> perimeter = 4*sqrt(100) = 40 m -> At = 2*100 + 40*3.5 = 340.0 m2
    # O = 15 * sqrt(4.0) / 340 = 30 / 340 = 0.088235 m^0.5
    # t_max = max(15.0, (0.2e-3 * 500 * 100 / (340 * 0.088235)) * 60) = 20.0 min
    res = features.run(
        "femDesignFire.compartmentSize",
        None,
        {"floorAreaM2": 100.0, "fuelLoadMjM2": 500.0, "openingAreaM2": 15.0, "openingHeightM": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["openingFactor"] == pytest.approx(0.088235, rel=0.01)
    assert res["summary"]["burningDurationMin"] == pytest.approx(20.0, rel=0.01)
    assert res["tables"][0]["rows"][0]["totalEnclosureM2"] == pytest.approx(340.0, rel=0.01)


def test_fem_design_fire_conductivity_map() -> None:
    # T = 500 C:
    # steel: 54.0 - 0.0333 * 500 = 37.35 W/(m*K)
    # concrete: 1.36 - 0.136 * 5 + 0.0057 * 25 = 1.36 - 0.68 + 0.1425 = 0.8225 W/(m*K)
    res = features.run("femDesignFire.conductivityMap", None, {"temperatureC": 500.0})
    assert res["problems"] == []
    assert res["summary"]["steelLambdaWmK"] == pytest.approx(37.35, rel=0.01)
    assert res["summary"]["concreteLambdaWmK"] == pytest.approx(0.8225, rel=0.01)


def test_fem_design_fire_cooling_phase() -> None:
    # 900 - 12 * 60 = 180.0 C
    res = features.run(
        "femDesignFire.coolingPhase",
        None,
        {"peakGasTempC": 900.0, "coolingRateCMin": 12.0},
    )
    assert res["problems"] == []
    assert res["summary"]["peakTempC"] == pytest.approx(900.0, rel=0.01)
    assert res["summary"]["tempAfter60MinC"] == pytest.approx(180.0, rel=0.01)


def test_fem_design_fire_fire_curve() -> None:
    # ISO-834 at t = 60 min: 20 + 345 * log10(8*60 + 1) = 20 + 345 * log10(481) = 945.3401 C
    res = features.run(
        "femDesignFire.fireCurve",
        None,
        {"curve": "standard", "durationMin": 60.0},
    )
    assert res["problems"] == []
    assert res["summary"]["curve"] == "standard"
    assert res["summary"]["durationMin"] == pytest.approx(60.0, rel=0.01)
    assert res["summary"]["peakGasTempC"] == pytest.approx(945.3401, rel=0.01)


def test_fem_design_fire_fire_duration(tmp_path: Path) -> None:
    # Pure lookup from default pack (BNBC 2020 Part 3 Table 3.3.1(a)) for Construction Type I-A:
    # column = 4.0 hr, beam = 3.0 hr, slab = 3.0 hr, wall = 4.0 hr.
    sdir = tmp_path / "02 Project Settings"
    sdir.mkdir()
    s = default_project_settings("BNBC")
    s = s.model_copy(
        update={"construction": s.construction.model_copy(update={"constructionType": "I-A"})}
    )
    (sdir / "project-settings.json").write_text(s.model_dump_json(by_alias=True), encoding="utf-8")
    res = features.run("femDesignFire.fireDuration", str(tmp_path), {"buildingHeightM": 24.0})
    assert res["problems"] == []
    assert res["summary"]["covered"] is True
    assert res["summary"]["ratingsCount"] == 4
    assert _row_by(res, "kind", "column")["hours"] == pytest.approx(4.0, rel=0.01)
    assert _row_by(res, "kind", "beam")["hours"] == pytest.approx(3.0, rel=0.01)


def test_fem_design_fire_heat_transfer() -> None:
    # Property + boundary check for 1D explicit finite-difference heat conduction:
    # Boundary at x=0 follows ISO-834 at t=60 min: 20 + 345 * log10(481) = 945.3401 C.
    # Unexposed face is bounded in (20, 945.34), temperature decreases monotonically with depth,
    # and longer duration increases unexposed face temperature.
    res = features.run(
        "femDesignFire.heatTransfer",
        None,
        {"slabThicknessMm": 160.0, "durationMin": 60.0},
    )
    assert res["problems"] == []
    assert res["summary"]["fireFaceTempC"] == pytest.approx(945.3401, rel=0.01)
    assert 20.0 < res["summary"]["unexposedFaceTempC"] < 945.3401
    temps = [r["tempC"] for r in res["tables"][0]["rows"]]
    assert all(temps[i] >= temps[i + 1] for i in range(len(temps) - 1))
    res_longer = features.run(
        "femDesignFire.heatTransfer",
        None,
        {"slabThicknessMm": 160.0, "durationMin": 120.0},
    )
    assert res_longer["summary"]["unexposedFaceTempC"] > res["summary"]["unexposedFaceTempC"]


def test_fem_design_fire_insulation_layer() -> None:
    # dp = 0.025 m -> R = 0.025 / 0.10 = 0.25 m2*K/W
    # C_areal = 400 * 1000 * 0.025 = 10,000.0 J/(m2*K)
    res = features.run(
        "femDesignFire.insulationLayer",
        None,
        {
            "thicknessMm": 25.0,
            "conductivityWmK": 0.10,
            "specificHeatJKgK": 1000.0,
            "densityKgM3": 400.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["thermalResistanceM2KW"] == pytest.approx(0.25, rel=0.01)
    assert res["summary"]["arealHeatCapacityJm2K"] == pytest.approx(10000.0, rel=0.01)
    assert res["tables"][0]["rows"][0]["arealHeatCapacityJm2K"] == pytest.approx(10000.0, rel=0.01)


def test_fem_design_fire_insulation_thickness() -> None:
    # Protected steel ODE: dTa/dt = k * (Tg(t) - Ta), k = (lam_p / dp) * (Am/V) / (600 * 7850)
    # 6-step exact exponential integration at 10-min midpoints (5, 15, 25, 35, 45, 55 min):
    # dp = 20 mm -> k = (0.15/0.020)*150/4.71e6 = 2.3885e-4 /s -> Ta(60m) = 487.96 C <= 500 C
    # dp = 19 mm -> k = 2.5142e-4 /s -> Ta(60m) = 503.93 C > 500 C -> integer ceil dp = 20 mm
    res = features.run(
        "femDesignFire.insulationThickness",
        None,
        {
            "sectionFactorPerM": 150.0,
            "durationMin": 60.0,
            "criticalTempC": 500.0,
            "conductivityWmK": 0.15,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["requiredThicknessMm"] == 20
    assert res["summary"]["achievedTempC"] == pytest.approx(487.96, rel=0.01)


def test_fem_design_fire_intumescent_paint() -> None:
    # dft = 0.005 * 200 * (90 / 60)^1.3 = 1.0 * 1.5^1.3 = 1.69402 mm = 1694.02 microns
    res = features.run(
        "femDesignFire.intumescentPaint",
        None,
        {"sectionFactorPerM": 200.0, "durationMin": 90.0},
    )
    assert res["problems"] == []
    assert res["summary"]["dryFilmThicknessMm"] == pytest.approx(1.6940, rel=0.01)
    assert res["summary"]["dftMicrons"] == pytest.approx(1694.02, rel=0.01)


def test_fem_design_fire_protected_zone() -> None:
    # Three-sided: 1600 - 250 = 1350.0 mm
    res = features.run(
        "femDesignFire.protectedZone",
        None,
        {"exposure": "threeSided", "perimeterMm": 1600.0, "topFlangeWidthMm": 250.0},
    )
    assert res["problems"] == []
    assert res["summary"]["heatedPerimeterMm"] == pytest.approx(1350.0, rel=0.01)
    assert res["summary"]["exposure"] == "threeSided"


def test_fem_design_fire_reduced_strength() -> None:
    # Default pack linear retention at 600 C (default steel fy = 250 MPa):
    # ky = 1 - (600 - 400)/800 = 0.75; ke = 1 - (600 - 100)/900 = 0.44444
    # fy_eff = 0.75 * 250 = 187.5 MPa
    res = features.run("femDesignFire.reducedStrength", None, {"steelTempC": 600.0})
    assert res["problems"] == []
    assert res["summary"]["kyTheta"] == pytest.approx(0.75, rel=0.01)
    assert res["summary"]["keTheta"] == pytest.approx(0.4444, rel=0.01)
    assert res["summary"]["effectiveFyMpa"] == pytest.approx(187.5, rel=0.01)


def test_fem_design_fire_restraint_force() -> None:
    # P = 0.4 * 100,000 * 5000 * 1.2e-5 * 250 / 1000 = 600.0 kN
    res = features.run(
        "femDesignFire.restraintForce",
        None,
        {"steelAreaMm2": 5000.0, "eThetaMpa": 100000.0, "tempRiseC": 250.0, "restraintRatio": 0.4},
    )
    assert res["problems"] == []
    assert res["summary"]["thermalRestraintForceKn"] == pytest.approx(600.0, rel=0.01)


def test_fem_design_fire_section_factor() -> None:
    # Am/V = (1200 / 8000) * 1000 = 150.0 1/m
    res = features.run(
        "femDesignFire.sectionFactor",
        None,
        {"exposedPerimeterMm": 1200.0, "steelAreaMm2": 8000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["sectionFactorPerM"] == pytest.approx(150.0, rel=0.01)


def test_fem_design_fire_spray_insulation() -> None:
    # Area = 1.5 * 8.0 = 12.0 m2; Volume = 12.0 * 0.020 = 0.24 m3; Mass = 0.24 * 300 = 72.0 kg
    res = features.run(
        "femDesignFire.sprayInsulation",
        None,
        {"thicknessMm": 20.0, "memberPerimeterM": 1.5, "lengthM": 8.0},
    )
    assert res["problems"] == []
    assert res["summary"]["coatedAreaM2"] == pytest.approx(12.0, rel=0.01)
    assert res["summary"]["dryMassKg"] == pytest.approx(72.0, rel=0.01)


def test_fem_design_fire_temperature_check() -> None:
    # k = (0.12 / 0.020) * 150 / (600 * 7850) = 900 / 4.71e6 = 1.91083e-4 /s
    # 6-step exact exponential integration at 10-min midpoints gives Ta(60m) = 421.01 C
    # (10s Euler in feature gives 419.43 C, within 0.4% of 6-step ODE) <= 550 C -> passes True
    res = features.run(
        "femDesignFire.temperatureCheck",
        None,
        {
            "sectionFactorPerM": 150.0,
            "durationMin": 60.0,
            "protectionThicknessMm": 20.0,
            "criticalTempC": 550.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["steelTempC"] == pytest.approx(421.01, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_design_fire_thermal_deflection() -> None:
    # delta = 1.2e-5 * 400 * 10000^2 / (8 * 500) = 480000 / 4000 = 120.0 mm
    # L / delta = 10000 / 120 = 83.3333
    res = features.run(
        "femDesignFire.thermalDeflection",
        None,
        {"spanMm": 10000.0, "depthMm": 500.0, "tempGradientC": 400.0},
    )
    assert res["problems"] == []
    assert res["summary"]["thermalDeflectionMm"] == pytest.approx(120.0, rel=0.01)
    assert res["summary"]["spanOverDefl"] == pytest.approx(83.3333, rel=0.01)


def test_fem_design_fire_thermal_expansion() -> None:
    # eps = 1.2e-5 * 500 = 0.006; dL = 0.006 * 10 * 1000 = 60.0 mm
    res = features.run(
        "femDesignFire.thermalExpansion",
        None,
        {"tempRiseC": 500.0, "memberLengthM": 10.0, "material": "steel"},
    )
    assert res["problems"] == []
    assert res["summary"]["thermalStrain"] == pytest.approx(0.006, rel=0.01)
    assert res["summary"]["elongationMm"] == pytest.approx(60.0, rel=0.01)


def test_fem_design_fire_thermal_profile() -> None:
    # Cool face = 45 C; T_mean = 0.5*(845 + 45) = 445.0 C; grad = (845 - 45) / 0.4 = 2000.0 C/m
    res = features.run(
        "femDesignFire.thermalProfile",
        None,
        {"fireFaceC": 845.0, "depthMm": 400.0},
    )
    assert res["problems"] == []
    assert res["summary"]["meanTempC"] == pytest.approx(445.0, rel=0.01)
    assert res["summary"]["gradientCPerM"] == pytest.approx(2000.0, rel=0.01)


# ── CFD Pedestrian Comfort (fem_cfd_pedestrian.py: 18) ───────────────────────────────────────────


def test_fem_cfd_pedestrian_canopy_shield() -> None:
    # proj_ratio = min(1.0, 3.0 / (0.12 * 50)) = 3 / 6 = 0.5
    # reduction = 0.35 * 0.5 = 0.175 (17.5%); gamma = 1.4 * (1 - 0.175) = 1.155
    res = features.run(
        "femCfdPedestrian.canopyShield",
        None,
        {"canopyProjectionM": 3.0, "buildingHeightM": 50.0, "unshieldedGamma": 1.4},
    )
    assert res["problems"] == []
    assert res["summary"]["reductionPercent"] == pytest.approx(17.5, rel=0.01)
    assert res["summary"]["gammaMitigated"] == pytest.approx(1.155, rel=0.01)


def test_fem_cfd_pedestrian_comfort_category() -> None:
    # Lookup: 2.0 < P(U>5) = 4.0 <= 5.0 -> "B - Standing / Strolling", safeForStanding True
    res = features.run(
        "femCfdPedestrian.comfortCategory",
        None,
        {"pOver5Pct": 4.0, "pOver10Pct": 0.5, "pOver15Pct": 0.01},
    )
    assert res["problems"] == []
    assert res["summary"]["category"] == "B - Standing / Strolling"
    assert res["summary"]["safeForStanding"] is True


def test_fem_cfd_pedestrian_comfort_map() -> None:
    # Max gamma = 1.25 -> c_loc = 1.25 * 4.0 = 5.0 m/s -> P(U>5) = 100 * exp(-1^1.9) = 36.7879%
    res = features.run(
        "femCfdPedestrian.comfortMap",
        None,
        {"gammaGrid": "0.5, 1.0, 1.25", "weibullCMs": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["mappedPoints"] == 3
    assert res["summary"]["maxPOver5Pct"] == pytest.approx(100.0 * math.exp(-1.0), rel=0.01)


def test_fem_cfd_pedestrian_comfort_report() -> None:
    # Report summary passes through inputs and checks hazardAreaM2 <= 0.5
    res = features.run(
        "femCfdPedestrian.comfortReport",
        None,
        {"areaM2": 1800.0, "sittingSharePct": 75.0, "hazardAreaM2": 0.0},
    )
    assert res["problems"] == []
    assert res["summary"]["areaM2"] == pytest.approx(1800.0, rel=0.01)
    assert res["summary"]["sittingSharePct"] == pytest.approx(75.0, rel=0.01)
    assert res["summary"]["safetyPass"] is True


def test_fem_cfd_pedestrian_diurnal_cycle() -> None:
    # c_day = 5.0 -> P5_day = 100 * exp(-1) = 36.7879%
    # c_night = 2.5 -> P5_night = 100 * exp(-2^1.9) = 100 * exp(-3.73213) = 2.3942%
    res = features.run(
        "femCfdPedestrian.diurnalCycle",
        None,
        {"daytimeWeibullScaleMs": 5.0, "nightWeibullScaleMs": 2.5},
    )
    assert res["problems"] == []
    assert res["summary"]["daytimePOver5Pct"] == pytest.approx(36.7879, rel=0.01)
    assert res["summary"]["nighttimePOver5Pct"] == pytest.approx(2.3942, rel=0.01)


def test_fem_cfd_pedestrian_exceedance_limit() -> None:
    # P(U > 6) = exp(-(6/3)^2) = exp(-4) = 0.0183156 -> 1.8316%, hours = 8760 * 0.0183156 = 160.445 hr
    res = features.run(
        "femCfdPedestrian.exceedanceLimit",
        None,
        {"thresholdMs": 6.0, "weibullScaleMs": 3.0, "weibullShapeK": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["exceedancePercent"] == pytest.approx(1.8316, rel=0.01)
    assert res["summary"]["hoursPerYear"] == pytest.approx(160.445, rel=0.01)


def test_fem_cfd_pedestrian_export_map() -> None:
    res = features.run("femCfdPedestrian.exportMap", None, {"nPoints": 250.0, "format": "vtk"})
    assert res["problems"] == []
    assert res["summary"]["format"] == "vtk"
    assert res["summary"]["points"] == 250


def test_fem_cfd_pedestrian_gust_factor() -> None:
    # U_gust = 4.0 * (1 + 3.5 * 0.30) = 8.2 m/s
    # U_gem = max(4.0, 8.2 / 1.85) = 4.4324 m/s
    res = features.run(
        "femCfdPedestrian.gustFactor",
        None,
        {"meanSpeedMs": 4.0, "turbulenceIntensity": 0.30, "peakFactor": 3.5},
    )
    assert res["problems"] == []
    assert res["summary"]["gustMs"] == pytest.approx(8.2, rel=0.01)
    assert res["summary"]["gemMs"] == pytest.approx(4.4324, rel=0.01)


def test_fem_cfd_pedestrian_mean_speed() -> None:
    # 0.80 * 7.5 = 6.0 m/s
    res = features.run(
        "femCfdPedestrian.meanSpeed",
        None,
        {"speedupFactor": 0.80, "uRefMs": 7.5},
    )
    assert res["problems"] == []
    assert res["summary"]["pedestrianMeanMs"] == pytest.approx(6.0, rel=0.01)


def test_fem_cfd_pedestrian_pass_rate() -> None:
    # [1.0, 3.0, 5.0, 7.0] <= 5.0 -> 3 of 4 passing = 75.0%
    res = features.run(
        "femCfdPedestrian.passRate",
        None,
        {"p5Samples": "1.0, 3.0, 5.0, 7.0", "targetLimitPct": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["passingProbes"] == 3
    assert res["summary"]["totalProbes"] == 4
    assert res["summary"]["passRatePct"] == pytest.approx(75.0, rel=0.01)


def test_fem_cfd_pedestrian_porosity_modeler() -> None:
    # K = (1 / (0.65 * 0.5) - 1)^2 = (1 / 0.325 - 1)^2 = 2.07692^2 = 4.3136
    # U_down = 10.0 / sqrt(1 + 4.3136) = 10.0 / 2.30513 = 4.3382 m/s
    res = features.run(
        "femCfdPedestrian.porosityModeler",
        None,
        {"openAreaRatio": 0.5, "windSpeedMs": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["lossCoefficientK"] == pytest.approx(4.3136, rel=0.01)
    assert res["summary"]["downstreamSpeedMs"] == pytest.approx(4.3382, rel=0.01)


def test_fem_cfd_pedestrian_probe_point() -> None:
    # c_loc = 1.0 * 5.0 = 5.0 m/s -> P5 = 100 * exp(-1) = 36.7879%
    # P10 = 100 * exp(-2^1.9) = 2.39% > 2.0%, P15 = 100 * exp(-3^1.9) = 0.031% <= 0.3% -> "D - Fast Walking Only"
    res = features.run(
        "femCfdPedestrian.probePoint",
        None,
        {"xM": 10.0, "yM": 4.0, "gamma": 1.0, "weibullScaleRefMs": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["pOver5Pct"] == pytest.approx(36.7879, rel=0.01)
    assert res["summary"]["grade"] == "D - Fast Walking Only"


def test_fem_cfd_pedestrian_seasonal_filter() -> None:
    # 5.0 * 1.2^1.9 = 5.0 * 1.41398 = 7.0699%
    res = features.run(
        "femCfdPedestrian.seasonalFilter",
        None,
        {"season": "winter", "seasonalFactor": 1.2, "annualP5Pct": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["season"] == "winter"
    assert res["summary"]["seasonalPOver5Pct"] == pytest.approx(7.0699, rel=0.01)


def test_fem_cfd_pedestrian_terrain_roughness() -> None:
    # Macdonald (1998): lf=0.25, h=16 m:
    # d = 16 * (1 + 4^(-0.25) * (-0.75)) = 16 * (1 - 0.75 / sqrt(2)) = 16 * 0.46967 = 7.5147 m
    # z0 = (16 - 7.5147) * exp(-(0.5 * 1.2 / 0.41^2 * (1 - 0.46967) * 0.25)^(-0.5))
    #    = 8.4853 * exp(-(0.47323)^(-0.5)) = 8.4853 * exp(-1.45364) = 1.9831 m
    res = features.run(
        "femCfdPedestrian.terrainRoughness",
        None,
        {"frontalAreaRatio": 0.25, "obstacleHeightM": 16.0},
    )
    assert res["problems"] == []
    assert res["summary"]["displacementHeightM"] == pytest.approx(7.5147, rel=0.01)
    assert res["summary"]["roughnessZ0M"] == pytest.approx(1.9831, rel=0.01)


def test_fem_cfd_pedestrian_tree_porosity() -> None:
    # C2 = 2 * 0.30 * 2.0 = 1.2 1/m; K(3m) = 1.2 * 3 = 3.6
    res = features.run(
        "femCfdPedestrian.treePorosity",
        None,
        {"leafAreaDensity": 2.0, "dragCoeffCd": 0.30},
    )
    assert res["problems"] == []
    assert res["summary"]["inertialCoeffC2PerM"] == pytest.approx(1.2, rel=0.01)
    assert res["summary"]["pressureLossFactorK"] == pytest.approx(3.6, rel=0.01)


def test_fem_cfd_pedestrian_weibull_parameters() -> None:
    # k = (2.5 / 5.0)^(-1.086) = 2^1.086 = 2.12285
    # c = 5.0 / Gamma(1 + 1/2.12285) = 5.0 / Gamma(1.47107) = 5.0 / 0.88565 = 5.6456 m/s
    res = features.run(
        "femCfdPedestrian.weibullParameters",
        None,
        {"meanSpeedMs": 5.0, "stdDevMs": 2.5},
    )
    assert res["problems"] == []
    assert res["summary"]["weibullShapeK"] == pytest.approx(2.1228, rel=0.01)
    assert res["summary"]["weibullScaleCMs"] == pytest.approx(5.6456, rel=0.01)


def test_fem_cfd_pedestrian_worst_locations() -> None:
    # [0.8, 1.4, 0.9, 1.2] -> worst is Probe-2 with 1.4
    res = features.run(
        "femCfdPedestrian.worstLocations",
        None,
        {"gammas": "0.8, 1.4, 0.9, 1.2", "targetMaxGamma": 1.1},
    )
    assert res["problems"] == []
    assert res["summary"]["worstProbe"] == "Probe-2"
    assert res["summary"]["peakGamma"] == pytest.approx(1.4, rel=0.01)


def test_fem_cfd_pedestrian_zone_average() -> None:
    # mean([0.5, 0.7, 0.9, 1.1]) = 0.8, max = 1.1
    # c_loc = 0.8 * 5.0 = 4.0 m/s -> P5 = 100 * exp(-(5/4)^1.9) = 100 * exp(-1.5280) = 21.6965%
    res = features.run(
        "femCfdPedestrian.zoneAverage",
        None,
        {"zoneName": "West Arcade", "probeGammas": "0.5, 0.7, 0.9, 1.1", "weibullScaleRefMs": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["zone"] == "West Arcade"
    assert res["summary"]["meanGamma"] == pytest.approx(0.8, rel=0.01)
    assert res["summary"]["peakGamma"] == pytest.approx(1.1, rel=0.01)
    assert res["summary"]["meanPOver5Pct"] == pytest.approx(21.6965, rel=0.01)


# ── Model Diaphragms & Links (fem_model_diaphragms.py: 17) ───────────────────────────────────────


def test_fem_model_diaphragms_copy_releases() -> None:
    res = features.run("femModelDiaphragms.copyReleases", None, {"memberCount": 18})
    assert res["problems"] == []
    assert res["summary"]["targetMembers"] == 18
    assert res["summary"]["existingPinLinks"] == 0


def test_fem_model_diaphragms_define_diaphragm() -> None:
    res = features.run(
        "femModelDiaphragms.defineDiaphragm",
        None,
        {"behaviour": "semiRigid", "elevationM": 6.4},
    )
    assert res["problems"] == []
    assert res["summary"]["elevationM"] == pytest.approx(6.4, rel=0.01)
    assert res["summary"]["behaviour"] == "semiRigid"
    assert res["summary"]["nodesAtLevel"] == 0


def test_fem_model_diaphragms_diaphragm_mass() -> None:
    # Area = 20 * 10 = 200 m2; M = 200 * 800 / 1000 = 160.0 t
    # Izz = 160 * (20^2 + 10^2) / 12 = 160 * 500 / 12 = 6666.6667 t*m2
    res = features.run(
        "femModelDiaphragms.diaphragmMass",
        None,
        {"widthXM": 20.0, "depthYM": 10.0, "arealMassKgM2": 800.0},
    )
    assert res["problems"] == []
    assert res["summary"]["massTonnes"] == pytest.approx(160.0, rel=0.01)
    assert res["summary"]["rotationalInertiaTm2"] == pytest.approx(6666.6667, rel=0.01)


def test_fem_model_diaphragms_eccentricity_mass() -> None:
    # e = 20 * 0.05 = 1.0 m; Mt = 600 * 1.0 = 600.0 kN*m
    res = features.run(
        "femModelDiaphragms.eccentricityMass",
        None,
        {"buildingWidthM": 20.0, "eccentricityPct": 5.0, "storeyForceKn": 600.0},
    )
    assert res["problems"] == []
    assert res["summary"]["offsetM"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["accidentalTorsionKnm"] == pytest.approx(600.0, rel=0.01)


def test_fem_model_diaphragms_flexible_behaviour() -> None:
    # t = 0.12 m, E = 2.4e7 kPa, G = 1.0e7 kPa, I = 0.12 * 6^3 / 12 = 2.16 m4, As = 0.12 * 6 / 1.2 = 0.6 m2
    # d_flex = 5 * 15 * 12^4 / (384 * 2.4e7 * 2.16) * 1000 = 1,555,200 / 19,906,560,000 * 1000 = 0.078125 mm
    # d_shear = 15 * 12^2 / (8 * 1.0e7 * 0.6) * 1000 = 2160 / 4.8e7 * 1000 = 0.045 mm
    # total = 0.123125 mm
    res = features.run(
        "femModelDiaphragms.flexibleBehaviour",
        None,
        {
            "spanM": 12.0,
            "depthM": 6.0,
            "thicknessMm": 120.0,
            "eMpa": 24000.0,
            "shearLoadKnPerM": 15.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["flexuralMm"] == pytest.approx(0.078125, rel=0.01)
    assert res["summary"]["shearMm"] == pytest.approx(0.045, rel=0.01)
    assert res["summary"]["totalDeflectionMm"] == pytest.approx(0.123125, rel=0.01)


def test_fem_model_diaphragms_gap_element() -> None:
    # initialGap = 2 mm, testDisp = -7 mm -> penetration = 5.0 mm = 0.005 m -> F = -40000 * 0.005 = -200.0 kN
    res = features.run(
        "femModelDiaphragms.gapElement",
        None,
        {"stiffnessKnM": 40000.0, "initialGapMm": 2.0, "testDispMm": -7.0},
    )
    assert res["problems"] == []
    assert res["summary"]["contactActive"] is True
    assert res["summary"]["penetrationMm"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["forceKn"] == pytest.approx(-200.0, rel=0.01)


def test_fem_model_diaphragms_ground_spring() -> None:
    # G0 = 2000 * 200^2 / 1000 = 80,000 kPa; L=B=3.0 m, D=0.0, nu=0.35:
    # Kx = 80000 * 3 / (2 - 0.35) * (3.4 * 1 + 1.2) = 145454.55 * 4.6 = 669,090.91 kN/m
    # Kz = 80000 * 3 / (1 - 0.35) * (1.55 * 1 + 0.8) = 369230.77 * 2.35 = 867,692.31 kN/m
    # Krx = 80000 * 27 / (1 - 0.35) * (0.4 * 1 + 0.1) = 3,323,076.92 * 0.5 = 1,661,538.46 kN*m/rad
    res = features.run(
        "femModelDiaphragms.groundSpring",
        None,
        {
            "footingLengthM": 3.0,
            "footingWidthM": 3.0,
            "embedmentM": 0.0,
            "vsMS": 200.0,
            "densityKgM3": 2000.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["g0Kpa"] == pytest.approx(80000.0, rel=0.01)
    assert res["summary"]["kxKnPerM"] == pytest.approx(669090.91, rel=0.01)
    assert res["summary"]["kzKnPerM"] == pytest.approx(867692.31, rel=0.01)
    assert res["summary"]["krxKnmPerRad"] == pytest.approx(1661538.46, rel=0.01)


def test_fem_model_diaphragms_interpolation_link() -> None:
    # 5 slaves, 120 kN -> weight = 0.2, force/node = 24.0 kN
    res = features.run(
        "femModelDiaphragms.interpolationLink",
        None,
        {"nSlaves": 5, "loadKn": 120.0},
    )
    assert res["problems"] == []
    assert res["summary"]["weightPerNode"] == pytest.approx(0.2, rel=0.01)
    assert res["summary"]["forcePerNodeKn"] == pytest.approx(24.0, rel=0.01)


def test_fem_model_diaphragms_line_spring() -> None:
    # k_line = 20000 * 0.8 = 16000 kN/m2; Kz = 16000 * 0.5 = 8000.0 kN/m
    res = features.run(
        "femModelDiaphragms.lineSpring",
        None,
        {"subgradeKsKnM3": 20000.0, "widthM": 0.8, "nodeSpacingM": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["lineStiffnessKnPerM2"] == pytest.approx(16000.0, rel=0.01)
    assert res["summary"]["nodalSpringKnPerM"] == pytest.approx(8000.0, rel=0.01)


def test_fem_model_diaphragms_member_releases() -> None:
    # k_theta = (3 * 30000 / 5) * (0.4 / 0.6) = 18000 * 0.66667 = 12000.0 kN*m/rad
    res = features.run(
        "femModelDiaphragms.memberReleases",
        None,
        {"eiKnm2": 30000.0, "lengthM": 5.0, "fixityRatio": 0.4},
    )
    assert res["problems"] == []
    assert res["summary"]["rotationalStiffnessKnmPerRad"] == pytest.approx(12000.0, rel=0.01)


def test_fem_model_diaphragms_node_spring() -> None:
    # Pure pass-through of diagonal nodal stiffness components
    res = features.run(
        "femModelDiaphragms.nodeSpring",
        None,
        {
            "kxKnM": 10000.0,
            "kyKnM": 12000.0,
            "kzKnM": 50000.0,
            "kRxKnmRad": 60000.0,
            "kRyKnmRad": 70000.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["kxKnPerM"] == pytest.approx(10000.0, rel=0.01)
    assert res["summary"]["kzKnPerM"] == pytest.approx(50000.0, rel=0.01)
    assert res["summary"]["krxKnmPerRad"] == pytest.approx(60000.0, rel=0.01)


def test_fem_model_diaphragms_p_y_curve() -> None:
    # Matlock soft clay: D=0.8 m, z=4.0 m, cu=50 kPa, gamma'=10 kN/m3, J=0.5:
    # Np = min(3 + 10*4/50 + 0.5*4/0.8, 9) = min(3 + 0.8 + 2.5, 9) = 6.3
    # pu = 6.3 * 50 * 0.8 = 252.0 kN/m; y50 = 2.5 * 0.01 * 0.8 * 1000 = 20.0 mm
    res = features.run(
        "femModelDiaphragms.pYCurve",
        None,
        {"pileDiameterM": 0.8, "depthM": 4.0, "cuKpa": 50.0, "gammaKnM3": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["puKnPerM"] == pytest.approx(252.0, rel=0.01)
    assert res["summary"]["y50Mm"] == pytest.approx(20.0, rel=0.01)


def test_fem_model_diaphragms_partial_fixity() -> None:
    # k_beam = 24000 / 6 = 4000 kN*m; norm = 40000 / 4000 = 10.0 (0.5 < 10 < 25 -> "Semi-rigid")
    res = features.run(
        "femModelDiaphragms.partialFixity",
        None,
        {"beamEI": 24000.0, "beamSpanM": 6.0, "jointStiffnessKnmRad": 40000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["normalizedStiffness"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["classification"] == "Semi-rigid"


def test_fem_model_diaphragms_rigid_behaviour() -> None:
    # Configuration report: 3 coupled in-plane DOFs (Ux, Uy, Rz); standalone plan dims 18.0 x 12.0 m
    res = features.run("femModelDiaphragms.rigidBehaviour", None, {"slabThicknessMm": 180.0})
    assert res["problems"] == []
    assert res["summary"]["constrainedDofs"] == 3
    assert res["summary"]["planWidthM"] == pytest.approx(18.0, rel=0.01)
    assert res["summary"]["planDepthM"] == pytest.approx(12.0, rel=0.01)


def test_fem_model_diaphragms_rigid_link() -> None:
    # leverArm = hypot(0.3, 0.4, 0.0) = 0.5 m
    res = features.run(
        "femModelDiaphragms.rigidLink",
        None,
        {"dxM": 0.3, "dyM": 0.4, "dzM": 0.0, "linkKind": "rod"},
    )
    assert res["problems"] == []
    assert res["summary"]["linkKind"] == "rod"
    assert res["summary"]["leverArmM"] == pytest.approx(0.5, rel=0.01)


def test_fem_model_diaphragms_rotational_inertia() -> None:
    # I_cm = 120 * (15^2 + 9^2) / 12 = 10 * (225 + 81) = 3060.0 t*m2
    # I_cr = 3060 + 120 * 1.5^2 = 3060 + 270 = 3330.0 t*m2
    # r_g = sqrt(3060 / 120) = sqrt(25.5) = 5.0498 m
    res = features.run(
        "femModelDiaphragms.rotationalInertia",
        None,
        {"massTonnes": 120.0, "lxM": 15.0, "lyM": 9.0, "eccentricityM": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["centroidalInertiaTm2"] == pytest.approx(3060.0, rel=0.01)
    assert res["summary"]["shiftedInertiaTm2"] == pytest.approx(3330.0, rel=0.01)
    assert res["summary"]["radiusOfGyrationM"] == pytest.approx(5.0498, rel=0.01)


def test_fem_model_diaphragms_subgrade_modulus() -> None:
    # ks = 200 / (20 / 1000) = 10,000.0 kN/m3; Kz = 10000 * 0.5 = 5000.0 kN/m
    res = features.run(
        "femModelDiaphragms.subgradeModulus",
        None,
        {"allowableBearingKpa": 200.0, "targetSettlementMm": 20.0, "tributaryAreaM2": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["subgradeModulusKnPerM3"] == pytest.approx(10000.0, rel=0.01)
    assert res["summary"]["nodalKzKnPerM"] == pytest.approx(5000.0, rel=0.01)

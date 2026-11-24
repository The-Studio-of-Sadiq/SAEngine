"""Independent known-answer tests for standalone calculators in the Studies window."""

from __future__ import annotations

import json
import math

import pytest

from saengine import features


def _row_by(res: dict, key: str, value: object, table_index: int = 0) -> dict:
    for row in res["tables"][table_index]["rows"]:
        if row[key] == value:
            return row
    raise AssertionError(f"No row with {key}={value!r} in {res['tables'][table_index]['rows']}")


# ── Studies Design (studies_design.py: 3) ─────────────────────────────────────────────────────────


def test_studies_design_response_surface() -> None:
    # Exact quadratic y = 2 - 3x + 0.5x^2 sampled at x = -2, 0, 2, 4 -> y = 10, 2, -2, -2.
    # At x = 6 -> y = 2 - 18 + 18 = 2.0.
    obs = [
        {"x": -2, "y": 10},
        {"x": 0, "y": 2},
        {"x": 2, "y": -2},
        {"x": 4, "y": -2},
    ]
    res = features.run(
        "studiesDesign.responseSurface",
        None,
        {"observations": json.dumps(obs), "predictAt": 6.0},
    )
    assert res["problems"] == []
    assert res["summary"]["constant"] == pytest.approx(2.0, abs=1e-4)
    assert res["summary"]["linear"] == pytest.approx(-3.0, rel=0.01)
    assert res["summary"]["quadratic"] == pytest.approx(0.5, rel=0.01)
    assert res["summary"]["prediction"] == pytest.approx(2.0, abs=1e-4)


def test_studies_design_sampler() -> None:
    # Stochastic LHS sampler: test exact sample count, bounds, LHS stratification (1 per stratum),
    # and repeatability for a fixed seed.
    vars_json = json.dumps(
        [{"name": "b", "min": 200, "max": 600}, {"name": "h", "min": 400, "max": 800}]
    )
    res1 = features.run(
        "studiesDesign.sampler",
        None,
        {"variables": vars_json, "samples": 8, "seed": 42, "method": "lhs"},
    )
    res2 = features.run(
        "studiesDesign.sampler",
        None,
        {"variables": vars_json, "samples": 8, "seed": 42, "method": "lhs"},
    )
    assert res1["problems"] == []
    assert res1["summary"]["sampleCount"] == 8
    assert res1["summary"]["variableCount"] == 2
    assert res1["tables"][0]["rows"] == res2["tables"][0]["rows"]
    b_vals = sorted(r["b"] for r in res1["tables"][0]["rows"])
    for k, val in enumerate(b_vals):
        lo = 200.0 + k * (400.0 / 8.0)
        hi = 200.0 + (k + 1) * (400.0 / 8.0)
        assert lo <= val <= hi


def test_studies_design_surrogate_model() -> None:
    # Points (1, 5), (2, 8), (3, 11), (4, 14): exact line y = 2 + 3x, RMSE = 0.
    # Prediction at x = 5 -> 17.0.
    obs = [{"x": 1, "y": 5}, {"x": 2, "y": 8}, {"x": 3, "y": 11}, {"x": 4, "y": 14}]
    res = features.run(
        "studiesDesign.surrogateModel",
        None,
        {"observations": json.dumps(obs), "predictAt": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["intercept"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["slope"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["prediction"] == pytest.approx(17.0, rel=0.01)
    assert res["summary"]["trainingRmse"] == pytest.approx(0.0, abs=1e-4)


# ── Studies Environment (studies_environment.py: 21) ──────────────────────────────────────────────


def test_studies_environment_air_quality() -> None:
    # 50 occupants @ 8 L/s/person = 400 L/s; CO2 gen = 0.005 L/s/person -> total = 0.25 L/s.
    # Rise = 0.25 / 400 * 1e6 = 625 ppm; indoor = 400 + 625 = 1025 ppm.
    res = features.run(
        "studiesEnvironment.airQuality",
        None,
        {"occupants": 50.0, "outdoorAir": 8.0, "co2Generation": 0.005, "outdoorCo2": 400.0},
    )
    assert res["problems"] == []
    assert res["summary"]["outdoorAirLPerS"] == pytest.approx(400.0, rel=0.01)
    assert res["summary"]["co2RisePpm"] == pytest.approx(625.0, rel=0.01)
    assert res["summary"]["indoorCo2Ppm"] == pytest.approx(1025.0, rel=0.01)


def test_studies_environment_daylight_factor() -> None:
    # Littlefair DF = T * Aw * theta * M / (A * (1 - R^2))
    # = 0.7 * 20 * 60 * 0.85 / (200 * (1 - 0.5^2)) = 714 / 150 = 4.76%.
    res = features.run(
        "studiesEnvironment.daylightFactor",
        None,
        {
            "glazingArea": 20.0,
            "transmittance": 0.7,
            "skyAngle": 60.0,
            "maintenance": 0.85,
            "surfaceArea": 200.0,
            "reflectance": 0.5,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["averageDaylightFactorPercent"] == pytest.approx(4.76, rel=0.01)


def test_studies_environment_energy_benchmark() -> None:
    # 480,000 kWh / 4,000 m2 = 120 kWh/m2/yr vs ref 150 -> diff = -30, ratio = 0.80.
    res = features.run(
        "studiesEnvironment.energyBenchmark",
        None,
        {
            "annualEnergy": 480000.0,
            "floorArea": 4000.0,
            "referenceIntensity": 150.0,
            "benchmarkName": "Office target",
        },
    )
    assert res["problems"] == []
    assert res["summary"]["energyIntensityKwhPerM2"] == pytest.approx(120.0, rel=0.01)
    assert res["summary"]["differenceKwhPerM2"] == pytest.approx(-30.0, rel=0.01)
    assert res["summary"]["ratioToReference"] == pytest.approx(0.8, rel=0.01)


def test_studies_environment_energy_model() -> None:
    # fabric = 400 * 0.35 + 100 * 1.5 = 140 + 150 = 290 W/K.
    # ventilation = 0.33 * 2000 * 0.5 = 330 W/K.
    # total = 620 W/K; per floor area (500 m2) = 1.24 W/m2K.
    res = features.run(
        "studiesEnvironment.energyModel",
        None,
        {
            "floorArea": 500.0,
            "wallArea": 400.0,
            "wallU": 0.35,
            "windowArea": 100.0,
            "windowU": 1.5,
            "volume": 2000.0,
            "airChanges": 0.5,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["fabricHeatLossWPerK"] == pytest.approx(290.0, rel=0.01)
    assert res["summary"]["ventilationHeatLossWPerK"] == pytest.approx(330.0, rel=0.01)
    assert res["summary"]["totalHeatLossWPerK"] == pytest.approx(620.0, rel=0.01)
    assert res["summary"]["heatLossPerAreaWPerM2K"] == pytest.approx(1.24, rel=0.01)


def test_studies_environment_energy_simulation() -> None:
    # gross = 2000 W/K * 1500 K*day * 24 / 1000 = 72,000 kWh.
    # useful = 72,000 - 12,000 - 10,000 = 50,000 kWh.
    # delivered = 50,000 / 0.8 = 62,500 kWh.
    res = features.run(
        "studiesEnvironment.energySimulation",
        None,
        {
            "heatLoss": 2000.0,
            "heatingDegreeDays": 1500.0,
            "internalGains": 12000.0,
            "solarGains": 10000.0,
            "systemEfficiency": 0.8,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["grossSpaceHeatKwh"] == pytest.approx(72000.0, rel=0.01)
    assert res["summary"]["usefulSpaceHeatKwh"] == pytest.approx(50000.0, rel=0.01)
    assert res["summary"]["deliveredEnergyKwh"] == pytest.approx(62500.0, rel=0.01)


def test_studies_environment_glare_analysis() -> None:
    # contrast = 10000 / 200 = 50; index = (10000^2 * 0.02) / (200 * 2^2) = 2e6 / 800 = 2500.
    res = features.run(
        "studiesEnvironment.glareAnalysis",
        None,
        {
            "sourceLuminance": 10000.0,
            "backgroundLuminance": 200.0,
            "solidAngle": 0.02,
            "positionIndex": 2.0,
            "adaptationLuminance": 150.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["luminanceContrast"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["sourceGlareIndex"] == pytest.approx(2500.0, rel=0.01)


def test_studies_environment_hvac_profiles() -> None:
    # 12 hours at 22 C (load = 2*(22-2) = 40 kW), 12 hours at 18 C (load = 2*(18-2) = 32 kW).
    # Peak = 40 kW; daily energy = 12*40 + 12*32 = 480 + 384 = 864 kWh.
    temps = ",".join(["18"] * 12 + ["22"] * 12)
    res = features.run(
        "studiesEnvironment.hvacProfiles",
        None,
        {"hourlySetpoints": temps, "designTemperature": 2.0, "heatLoss": 2000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["peakHeatingLoadKw"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["dailyHeatingEnergyKwh"] == pytest.approx(864.0, rel=0.01)


def test_studies_environment_irradiance() -> None:
    # Sun due south (180), elevation 30 deg; south-facing (180) panel tilted 60 deg (so sun is normal to panel: 30+60=90 deg!).
    # cos(theta_i) = sin(30)*cos(60) + cos(30)*sin(60)*1 = sin(30+60) = 1.0 -> beam = 800 * 1.0 = 800 W/m2.
    # sky = 120 * (1 + cos 60)/2 = 120 * 0.75 = 90 W/m2.
    # GHI = 800 * sin(30) + 120 = 400 + 120 = 520 W/m2 -> ground = 520 * 0.2 * (1 - 0.5)/2 = 26.0 W/m2.
    # total = 800 + 90 + 26 = 916.0 W/m2.
    res = features.run(
        "studiesEnvironment.irradiance",
        None,
        {
            "dni": 800.0,
            "dhi": 120.0,
            "sunAzimuth": 180.0,
            "sunElevation": 30.0,
            "surfaceAzimuth": 180.0,
            "tilt": 60.0,
            "albedo": 0.2,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["beamWPerM2"] == pytest.approx(800.0, rel=0.01)
    assert res["summary"]["skyDiffuseWPerM2"] == pytest.approx(90.0, rel=0.01)
    assert res["summary"]["groundReflectedWPerM2"] == pytest.approx(26.0, rel=0.01)
    assert res["summary"]["globalTiltedWPerM2"] == pytest.approx(916.0, rel=0.01)


def test_studies_environment_load_profiles() -> None:
    # 23 hours @ 1, 1 hour (hour 10) @ 2 -> sum = 25; dailyEnergy = 500 -> hour 10 = 500 * 2 / 25 = 40 kWh.
    mults = ["1"] * 24
    mults[10] = "2"
    res = features.run(
        "studiesEnvironment.loadProfiles",
        None,
        {"hourlyMultipliers": ",".join(mults), "dailyEnergy": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["dailyEnergyKwh"] == pytest.approx(500.0, rel=0.01)
    assert res["summary"]["peakHour"] == 10
    assert res["summary"]["peakHourEnergyKwh"] == pytest.approx(40.0, rel=0.01)


def test_studies_environment_noise_map() -> None:
    # L = 95 - 20*log10(d / 1) - 5:
    # d=10 m -> 95 - 20 - 5 = 70.0 dB(A); d=100 m -> 95 - 40 - 5 = 50.0 dB(A).
    receivers = json.dumps(
        [
            {"id": "A", "x": 10, "y": 0, "distanceM": 10},
            {"id": "B", "x": 100, "y": 0, "distanceM": 100},
        ]
    )
    res = features.run(
        "studiesEnvironment.noiseMap",
        None,
        {
            "receivers": receivers,
            "sourceLevel": 95.0,
            "referenceDistance": 1.0,
            "barrierAttenuation": 5.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["maximumLevelDbA"] == pytest.approx(70.0, rel=0.01)
    assert _row_by(res, "receiver", "B")["levelDbA"] == pytest.approx(50.0, rel=0.01)


def test_studies_environment_offset_targets() -> None:
    # Baseline = 20,000; 25% reduction -> reduction = 5,000, residual = 15,000.
    # 40% offset -> offset = 6,000, unabated = 9,000.
    res = features.run(
        "studiesEnvironment.offsetTargets",
        None,
        {"baselineCarbon": 20000.0, "reductionPercent": 25.0, "offsetPercent": 40.0},
    )
    assert res["problems"] == []
    assert res["summary"]["reductionKgCo2ePerYear"] == pytest.approx(5000.0, rel=0.01)
    assert res["summary"]["residualKgCo2ePerYear"] == pytest.approx(15000.0, rel=0.01)
    assert res["summary"]["offsetTargetKgCo2ePerYear"] == pytest.approx(6000.0, rel=0.01)
    assert res["summary"]["unabatedKgCo2ePerYear"] == pytest.approx(9000.0, rel=0.01)


def test_studies_environment_operational_carbon() -> None:
    # 100,000 * 0.5 + 50,000 * 0.2 = 50,000 + 10,000 = 60,000 kgCO2e; / 2,000 m2 = 30 kgCO2e/m2.
    res = features.run(
        "studiesEnvironment.operationalCarbon",
        None,
        {
            "electricity": 100000.0,
            "electricityFactor": 0.5,
            "gas": 50000.0,
            "gasFactor": 0.2,
            "floorArea": 2000.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["totalCarbonKgCo2e"] == pytest.approx(60000.0, rel=0.01)
    assert res["summary"]["intensityKgCo2ePerM2"] == pytest.approx(30.0, rel=0.01)


def test_studies_environment_pedestrian_wind() -> None:
    # V = 10 * (2 / 16)^0.25? Let's use (2.5 / 10)^0.5 = 0.5 -> mean = 10 * 0.5 = 5.0 m/s.
    # gust = 5.0 * 1.6 = 8.0 m/s; exceeds 4.5 m/s -> True.
    res = features.run(
        "studiesEnvironment.pedestrianWind",
        None,
        {
            "referenceSpeed": 10.0,
            "height": 2.5,
            "referenceHeight": 10.0,
            "exponent": 0.5,
            "comfortLimit": 4.5,
            "gustFactor": 1.6,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["meanSpeedMPerS"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["estimatedGustMPerS"] == pytest.approx(8.0, rel=0.01)
    assert res["summary"]["exceedsComfortLimit"] is True


def test_studies_environment_pmv_comfort() -> None:
    # ISO 7730:2005 Annex D Table D.1 benchmark:
    # Ta = Tr = 22 C, v = 0.1 m/s, RH = 60%, met = 1.2, clo = 0.5 -> PMV = -0.75, PPD = 16.9%.
    res = features.run(
        "studiesEnvironment.pmvComfort",
        None,
        {
            "airTemperature": 22.0,
            "meanRadiantTemperature": 22.0,
            "airSpeed": 0.1,
            "relativeHumidity": 60.0,
            "metabolicRate": 1.2,
            "clothing": 0.5,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["pmv"] == pytest.approx(-0.75, rel=0.02)
    assert res["summary"]["ppdPercent"] == pytest.approx(16.9, rel=0.02)
    assert res["summary"]["thermalSensation"] == "cold"


def test_studies_environment_renewables() -> None:
    # PV = 200 * 1600 * 0.25 * 0.8 = 64,000 kWh/yr.
    # HP = 90,000 / 3.0 = 30,000 kWh/yr; total demand = 50,000 + 30,000 = 80,000 -> net = -16,000.
    res = features.run(
        "studiesEnvironment.renewables",
        None,
        {
            "pvArea": 200.0,
            "irradiation": 1600.0,
            "pvEfficiency": 0.25,
            "performanceRatio": 0.8,
            "heatDemand": 90000.0,
            "heatPumpCop": 3.0,
            "electricityDemand": 50000.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["pvGenerationKwhPerYear"] == pytest.approx(64000.0, rel=0.01)
    assert res["summary"]["heatPumpElectricityKwhPerYear"] == pytest.approx(30000.0, rel=0.01)
    assert res["summary"]["annualElectricityDemandKwh"] == pytest.approx(80000.0, rel=0.01)
    assert res["summary"]["netElectricityKwhPerYear"] == pytest.approx(-16000.0, rel=0.01)


def test_studies_environment_retrofit_options() -> None:
    # Capex = 100,000, savings = 25,000/yr, life = 10 yr, r = 0.05:
    # payback = 4.0 yr; PV = 25000 * (1 - 1.05^-10) / 0.05 = 193,043.37; NPV = 93,043.37.
    res = features.run(
        "studiesEnvironment.retrofitOptions",
        None,
        {"capitalCost": 100000.0, "annualSavings": 25000.0, "life": 10, "discountRate": 0.05},
    )
    pv = 25000.0 * (1.0 - 1.05**-10) / 0.05
    assert res["problems"] == []
    assert res["summary"]["simplePaybackYears"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["presentValueSavings"] == pytest.approx(pv, rel=0.01)
    assert res["summary"]["netPresentValue"] == pytest.approx(pv - 100000.0, rel=0.01)


def test_studies_environment_shadow_range() -> None:
    # At lat = 45 deg, lon = 0, utc = 0, H = 10 m:
    # Summer solstice noon elevation ~ 90 - (45 - 23.44) = 68.44 deg -> min shadow ~ 10/tan(68.44) = 3.95 m.
    # Winter solstice noon elevation ~ 90 - (45 + 23.44) = 21.56 deg -> max shadow ~ 10/tan(21.56) = 25.31 m.
    res = features.run(
        "studiesEnvironment.shadowRange",
        None,
        {"latitude": 45.0, "longitude": 0.0, "height": 10.0, "utcOffset": 0.0},
    )
    assert res["problems"] == []
    assert res["summary"]["minimumShadowLengthM"] == pytest.approx(
        10.0 / math.tan(math.radians(90.0 - 45.0 + 23.44)), rel=0.02
    )
    assert res["summary"]["maximumShadowLengthM"] == pytest.approx(
        10.0 / math.tan(math.radians(90.0 - 45.0 - 23.44)), rel=0.02
    )


def test_studies_environment_solar_path() -> None:
    # Equinox (2026-03-20) at lat=45, lon=0, utc=0, 60-min steps:
    # ~12 daytime hours above horizon; at 12:00 UTC solar elevation ~ 90 - 45 = 45 deg.
    res = features.run(
        "studiesEnvironment.solarPath",
        None,
        {
            "latitude": 45.0,
            "longitude": 0.0,
            "date": "2026-03-20",
            "utcOffset": 0.0,
            "stepMinutes": 60.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["sunUpSamples"] == 12
    noon = _row_by(res, "time", "12:00")
    assert noon["elevation"] == pytest.approx(45.0, rel=0.02)


def test_studies_environment_sun_hours() -> None:
    # Lat=45 N, lon=0, Dec 21 (sun stays in southern sky all day), 60-min steps:
    # Horizontal roof (0,0) and vertical south wall (180,90) receive the same ~9 h; north wall (0,90) gets 0 h.
    res = features.run(
        "studiesEnvironment.sunHours",
        None,
        {
            "latitude": 45.0,
            "longitude": 0.0,
            "date": "2026-12-21",
            "surfaceNormals": "0,0;180,90;0,90",
            "utcOffset": 0.0,
            "stepMinutes": 60.0,
        },
    )
    assert res["problems"] == []
    rows = res["tables"][0]["rows"]
    assert rows[0]["sunHours"] == pytest.approx(rows[1]["sunHours"], rel=0.01)
    assert rows[0]["sunHours"] >= 8.0
    assert rows[2]["sunHours"] == pytest.approx(0.0, abs=1e-6)


def test_studies_environment_tariffs() -> None:
    # 50,000 * 0.20 + 80,000 * 0.05 + 1,200 = 10,000 + 4,000 + 1,200 = 15,200.
    res = features.run(
        "studiesEnvironment.tariffs",
        None,
        {
            "electricity": 0.20,
            "gas": 0.05,
            "electricityUse": 50000.0,
            "gasUse": 80000.0,
            "fixedCharge": 1200.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["electricityCharge"] == pytest.approx(10000.0, rel=0.01)
    assert res["summary"]["gasCharge"] == pytest.approx(4000.0, rel=0.01)
    assert res["summary"]["annualBill"] == pytest.approx(15200.0, rel=0.01)


def test_studies_environment_thermal_comfort() -> None:
    # ISO 7730:2005 Annex D Table D.1 benchmark:
    # Ta = Tr = 27 C, v = 0.1 m/s, RH = 60%, met = 1.2, clo = 0.5 -> PMV = +0.77, PPD = 17.4%.
    res = features.run(
        "studiesEnvironment.thermalComfort",
        None,
        {
            "airTemperature": 27.0,
            "meanRadiantTemperature": 27.0,
            "airSpeed": 0.1,
            "relativeHumidity": 60.0,
            "metabolicRate": 1.2,
            "clothing": 0.5,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["pmv"] == pytest.approx(0.77, rel=0.02)
    assert res["summary"]["ppdPercent"] == pytest.approx(17.4, rel=0.02)


# ── Studies Optimisation (studies_optimisation.py: 8) ─────────────────────────────────────────────


def test_studies_optimisation_algorithm_select() -> None:
    # Grid search: 4 variables, budget 300 -> floor(300^(1/4)) = floor(4.16) = 4 levels/var -> 4^4 = 256 evals.
    res = features.run(
        "studiesOptimisation.algorithmSelect",
        None,
        {"algorithm": "grid", "variables": 4, "evaluations": 300},
    )
    assert res["problems"] == []
    assert res["summary"]["estimatedGridLevelsPerVariable"] == 4
    assert res["summary"]["plannedEvaluations"] == 256


def test_studies_optimisation_density_method() -> None:
    # Densities [0.0, 0.5, 1.0], min=0.1, p=3 -> effective [0.1, 0.5, 1.0] -> E/E0 = [0.001, 0.125, 1.0].
    # Mean = (0.001 + 0.125 + 1.0) / 3 = 0.375333.
    res = features.run(
        "studiesOptimisation.densityMethod",
        None,
        {"densities": "0.0,0.5,1.0", "penalty": 3.0, "minimumDensity": 0.1},
    )
    assert res["problems"] == []
    assert res["summary"]["elementCount"] == 3
    assert res["summary"]["meanRelativeStiffness"] == pytest.approx(
        (0.001 + 0.125 + 1.0) / 3, rel=0.01
    )


def test_studies_optimisation_erection_cost() -> None:
    # 200 members, 800 h @ 60 = 48,000; 10 days @ 2,000 = 20,000; travel = 12,000 -> total = 80,000 -> 400/member.
    res = features.run(
        "studiesOptimisation.erectionCost",
        None,
        {
            "members": 200,
            "crewHours": 800.0,
            "hourlyRate": 60.0,
            "craneDays": 10.0,
            "craneDailyCost": 2000.0,
            "travel": 12000.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["erectionCost"] == pytest.approx(80000.0, rel=0.01)
    assert res["summary"]["costPerMember"] == pytest.approx(400.0, rel=0.01)


def test_studies_optimisation_filter_radius() -> None:
    # radius = 750 mm, element = 300 mm -> ratio = 2.5 -> ceil = 3.
    res = features.run(
        "studiesOptimisation.filterRadius",
        None,
        {"radius": 750.0, "elementSize": 300.0},
    )
    assert res["problems"] == []
    assert res["summary"]["radiusInElements"] == pytest.approx(2.5, rel=0.01)
    assert res["summary"]["integerStencilRadius"] == 3


def test_studies_optimisation_generation_count() -> None:
    # pop = 50, gen = 20, eliteFraction = 0.15 -> elite = ceil(7.5) = 8 -> new/gen = 42 -> 840; total = 1000.
    res = features.run(
        "studiesOptimisation.generationCount",
        None,
        {"population": 50, "generations": 20, "eliteFraction": 0.15},
    )
    assert res["problems"] == []
    assert res["summary"]["evaluations"] == 1000
    assert res["summary"]["elitePerGeneration"] == 8
    assert res["summary"]["newCandidates"] == 840


def test_studies_optimisation_minimum_length() -> None:
    # element = 200 mm, minWidth = 700 mm, elements = 3 -> required = 600 mm, ratio = 3.5, resolved = True.
    res = features.run(
        "studiesOptimisation.minimumLength",
        None,
        {"elementLength": 200.0, "minimumMemberWidth": 700.0, "minimumFeatureElements": 3},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredFeatureWidthMm"] == pytest.approx(600.0, rel=0.01)
    assert res["summary"]["featureResolutionRatio"] == pytest.approx(3.5, rel=0.01)
    assert res["summary"]["resolved"] is True


def test_studies_optimisation_smooth_surface() -> None:
    # 2x2 grid: (0,0)=0, (1,0)=4, (0,1)=4, (1,1)=8; blend = 0.5.
    # For (0,0): neighbors are (1,0)=4 and (0,1)=4 -> mean=4 -> smoothed = 0 + 0.5*(4-0) = 2.0.
    # For (1,1): neighbors are (0,1)=4 and (1,0)=4 -> mean=4 -> smoothed = 8 + 0.5*(4-8) = 6.0.
    verts = "0,0,0\n1,0,4\n0,1,4\n1,1,8"
    res = features.run(
        "studiesOptimisation.smoothSurface",
        None,
        {"vertices": verts, "blend": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["vertexCount"] == 4
    rows = res["tables"][0]["rows"]
    assert rows[0]["smoothed"] == pytest.approx(2.0, rel=0.01)
    assert rows[3]["smoothed"] == pytest.approx(6.0, rel=0.01)


def test_studies_optimisation_volume_fraction() -> None:
    # Mean of [0.2, 0.4, 0.6, 0.8] = 0.50; target = 0.45 -> diff = +0.05 -> meetsTarget = False.
    res = features.run(
        "studiesOptimisation.volumeFraction",
        None,
        {"densities": "0.2,0.4,0.6,0.8", "target": 0.45},
    )
    assert res["problems"] == []
    assert res["summary"]["actualVolumeFraction"] == pytest.approx(0.5, rel=0.01)
    assert res["summary"]["difference"] == pytest.approx(0.05, rel=0.01)
    assert res["summary"]["meetsTarget"] is False


# ── Studies Risk (studies_risk.py: 17) ────────────────────────────────────────────────────────────


def test_studies_risk_beta_index() -> None:
    # mu_R = 500, mu_L = 300, sigma_R = 60, sigma_L = 80, rho = 0 ->
    # sigma_g = sqrt(3600 + 6400) = 100 kN -> beta = 200 / 100 = 2.0 -> pf = 0.5*erfc(2/sqrt(2)) = 0.02275.
    res = features.run(
        "studiesRisk.betaIndex",
        None,
        {
            "meanResistance": 500.0,
            "meanLoad": 300.0,
            "stdResistance": 60.0,
            "stdLoad": 80.0,
            "correlation": 0.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["limitStateStd"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["beta"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["failureProbability"] == pytest.approx(
        0.5 * math.erfc(2.0 / math.sqrt(2.0)), rel=0.01
    )


def test_studies_risk_confidence_level() -> None:
    # mean = 200, s = 20, n = 25 (s/sqrt(n) = 4), confidence = 0.95 (z = 1.96) -> half = 7.84.
    res = features.run(
        "studiesRisk.confidenceLevel",
        None,
        {"mean": 200.0, "standardDeviation": 20.0, "sampleCount": 25, "confidence": 0.95},
    )
    assert res["problems"] == []
    assert res["summary"]["halfWidth"] == pytest.approx(1.96 * 4.0, rel=0.01)
    assert res["summary"]["lowerBound"] == pytest.approx(200.0 - 7.84, rel=0.01)
    assert res["summary"]["upperBound"] == pytest.approx(200.0 + 7.84, rel=0.01)


def test_studies_risk_distribution_type() -> None:
    # Normal distribution with low=2, mode(mean)=11, high=20 -> sigma = (20-2)/6 = 3.0.
    # For samples=101, index 84 corresponds to p = 0.84 (where Phi^-1(0.84) = 0.99446 ~ 1.0):
    # expected quantile = 11 + 3.0 * 0.99446 = 13.9834 (not 11 + 3*sqrt(2)*0.99446).
    res = features.run(
        "studiesRisk.distributionType",
        None,
        {"distribution": "normal", "low": 2.0, "mode": 11.0, "high": 20.0, "samples": 101},
    )
    assert res["problems"] == []
    assert res["summary"]["mean"] == pytest.approx(11.0, rel=0.01)
    assert res["summary"]["standardDeviation"] == pytest.approx(3.0, rel=0.01)
    p84 = _row_by(res, "probability", 0.84)["value"]
    assert p84 == pytest.approx(13.9834, rel=0.01)


def test_studies_risk_explosion_load() -> None:
    # P = 60 kPa, t = 0.05 s, A = 10 m2, M = 5000 kg:
    # peakForce = 600 kN; impulse = 60000 * 0.05 / 2 = 1500 Pa*s; panelImpulse = 15000 N*s; dV = 3.0 m/s.
    res = features.run(
        "studiesRisk.explosionLoad",
        None,
        {"peakPressure": 60.0, "duration": 0.05, "panelArea": 10.0, "mass": 5000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["peakForceKn"] == pytest.approx(600.0, rel=0.01)
    assert res["summary"]["impulsePaS"] == pytest.approx(1500.0, rel=0.01)
    assert res["summary"]["panelImpulseNs"] == pytest.approx(15000.0, rel=0.01)
    assert res["summary"]["rigidBodyVelocityChangeMPerS"] == pytest.approx(3.0, rel=0.01)


def test_studies_risk_failure_probability() -> None:
    # C ~ N(600, 50^2), D = 500 -> beta = (600 - 500) / 50 = 2.0 -> pf = Phi(-2) = 0.022750.
    res = features.run(
        "studiesRisk.failureProbability",
        None,
        {"capacityMean": 600.0, "capacityStd": 50.0, "demand": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["reliabilityIndex"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["failureProbability"] == pytest.approx(
        0.5 * math.erfc(2.0 / math.sqrt(2.0)), rel=0.01
    )


def test_studies_risk_fire_exposure() -> None:
    # ISO 834 curve: T = 25 + 345 * log10(8 * 30 + 1) = 25 + 345 * log10(241) = 25 + 821.80 = 846.80 C.
    res = features.run(
        "studiesRisk.fireExposure",
        None,
        {"exposureMinutes": 30.0, "initialTemperature": 25.0, "targetTemperature": 600.0},
    )
    expected = 25.0 + 345.0 * math.log10(241.0)
    assert res["problems"] == []
    assert res["summary"]["gasTemperatureC"] == pytest.approx(expected, rel=0.01)
    assert res["summary"]["temperatureDifferenceC"] == pytest.approx(expected - 600.0, rel=0.01)


def test_studies_risk_impact_rating() -> None:
    # direct = 150,000 + delay = 60 * 2,000 = 120,000 -> total = 270,000 (in [250k, 1M) -> "severe").
    res = features.run(
        "studiesRisk.impactRating",
        None,
        {"directCost": 150000.0, "duration": 60.0, "costPerDay": 2000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["delayCost"] == pytest.approx(120000.0, rel=0.01)
    assert res["summary"]["combinedCost"] == pytest.approx(270000.0, rel=0.01)
    assert res["summary"]["rating"] == "severe"


def test_studies_risk_iteration_count() -> None:
    # p = 0.2, z = 2.0, r = 0.1 -> n = ceil(4 * 0.8 / (0.01 * 0.2)) = ceil(1600) = 1600.
    res = features.run(
        "studiesRisk.iterationCount",
        None,
        {"eventProbability": 0.2, "relativeHalfWidth": 0.1, "confidenceZ": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["recommendedTrials"] == 1600


def test_studies_risk_likelihood_rating() -> None:
    # 0.25 is in [0.2, 0.5) -> "likely".
    res = features.run("studiesRisk.likelihoodRating", None, {"annualProbability": 0.25})
    assert res["problems"] == []
    assert res["summary"]["rating"] == "likely"


def test_studies_risk_mitigation_cost() -> None:
    # saving = 100k - 40k = 60k/yr; r=0.05, n=5 -> PV = 60000*(1 - 1.05^-5)/0.05 = 259,768.60.
    # cost = 100k -> NPV = 159,768.60, BCR = 2.5977.
    res = features.run(
        "studiesRisk.mitigationCost",
        None,
        {
            "mitigationCost": 100000.0,
            "lossBefore": 100000.0,
            "lossAfter": 40000.0,
            "life": 5,
            "discountRate": 0.05,
        },
    )
    pv = 60000.0 * (1.0 - 1.05**-5) / 0.05
    assert res["problems"] == []
    assert res["summary"]["annualExpectedLossReduction"] == pytest.approx(60000.0, rel=0.01)
    assert res["summary"]["presentValueBenefit"] == pytest.approx(pv, rel=0.01)
    assert res["summary"]["netPresentValue"] == pytest.approx(pv - 100000.0, rel=0.01)
    assert res["summary"]["benefitCostRatio"] == pytest.approx(pv / 100000.0, rel=0.01)


def test_studies_risk_monte_carlo() -> None:
    # Stochastic Bernoulli + triangular simulation with 50,000 trials:
    # Event 1: p=0.4, tri(10k, 20k, 30k) -> E[loss] = 0.4 * 20,000 = 8,000.
    # Event 2: p=0.2, tri(30k, 40k, 50k) -> E[loss] = 0.2 * 40,000 = 8,000.
    # Analytical total expected loss = 16,000; analytical P(loss > 0) = 1 - 0.6*0.8 = 0.52.
    events = json.dumps(
        [
            {
                "name": "E1",
                "probability": 0.4,
                "costLow": 10000,
                "costMode": 20000,
                "costHigh": 30000,
            },
            {
                "name": "E2",
                "probability": 0.2,
                "costLow": 30000,
                "costMode": 40000,
                "costHigh": 50000,
            },
        ]
    )
    res = features.run(
        "studiesRisk.monteCarlo",
        None,
        {"events": events, "iterations": 50000, "seed": 123},
    )
    assert res["problems"] == []
    assert res["summary"]["meanLossCurrency"] == pytest.approx(16000.0, rel=0.03)
    assert res["summary"]["probabilityOfLoss"] == pytest.approx(0.52, rel=0.03)


def test_studies_risk_progressive_collapse() -> None:
    # Demand = 800 * 0.75 * 1.5 = 900 kN; capacity = 1200 -> reserve = +300 kN, ratio = 1.3333.
    res = features.run(
        "studiesRisk.progressiveCollapse",
        None,
        {
            "lostColumnLoad": 800.0,
            "alternatePathCapacity": 1200.0,
            "dynamicIncrease": 1.5,
            "redistributionFactor": 0.75,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["amplifiedDemandKn"] == pytest.approx(900.0, rel=0.01)
    assert res["summary"]["reserveKn"] == pytest.approx(300.0, rel=0.01)
    assert res["summary"]["capacityDemandRatio"] == pytest.approx(1200.0 / 900.0, rel=0.01)
    assert res["summary"]["passesScreen"] is True


def test_studies_risk_residual_risk() -> None:
    # Initial = 0.4 * 200 = 80; p2 = 0.4 * 0.5 = 0.2, i2 = 200 * 0.7 = 140 -> residual = 28, red = 52.
    res = features.run(
        "studiesRisk.residualRisk",
        None,
        {
            "initialProbability": 0.4,
            "initialImpact": 200.0,
            "probabilityReduction": 0.5,
            "impactReduction": 0.3,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["initialScore"] == pytest.approx(80.0, rel=0.01)
    assert res["summary"]["residualScore"] == pytest.approx(28.0, rel=0.01)
    assert res["summary"]["scoreReduction"] == pytest.approx(52.0, rel=0.01)


def test_studies_risk_response_action() -> None:
    # Transfer: initial = 0.25 * 200,000 = 50,000; residual = 0.25 * 200,000 * (1 - 0.6) = 20,000; red = 30,000.
    res = features.run(
        "studiesRisk.responseAction",
        None,
        {"strategy": "transfer", "probability": 0.25, "impact": 200000.0, "effectiveness": 0.6},
    )
    assert res["problems"] == []
    assert res["summary"]["initialExpectedLoss"] == pytest.approx(50000.0, rel=0.01)
    assert res["summary"]["residualExpectedLoss"] == pytest.approx(20000.0, rel=0.01)
    assert res["summary"]["expectedLossReduction"] == pytest.approx(30000.0, rel=0.01)


def test_studies_risk_risk_score() -> None:
    # 0.3 * 5 * 2 = 3.0.
    res = features.run(
        "studiesRisk.riskScore",
        None,
        {"probability": 0.3, "impact": 5.0, "exposure": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["riskScore"] == pytest.approx(3.0, rel=0.01)


def test_studies_risk_run_simulation() -> None:
    # Stochastic demand ~ N(400, 40^2) vs deterministic capacity = 440 -> z = (440 - 400)/40 = 1.0 ->
    # analytical P(D > C) = 0.5 * erfc(1 / sqrt(2)) = 0.158655. With 100,000 trials, within 2%.
    res = features.run(
        "studiesRisk.runSimulation",
        None,
        {
            "distribution": "normal",
            "meanDemand": 400.0,
            "standardDeviation": 40.0,
            "capacity": 440.0,
            "iterations": 100000,
            "seed": 77,
        },
    )
    expected_pf = 0.5 * math.erfc(1.0 / math.sqrt(2.0))
    assert res["problems"] == []
    assert res["summary"]["estimatedFailureProbability"] == pytest.approx(expected_pf, rel=0.02)


def test_studies_risk_vehicle_impact() -> None:
    # m = 4000 kg, v = 20 m/s, angle = 60 deg -> v_n = 20 * cos(60) = 10 m/s.
    # KE = 0.5 * 4000 * 10^2 = 200 kJ; crush = 0.5 m -> F_avg = 200 / 0.5 = 400 kN.
    res = features.run(
        "studiesRisk.vehicleImpact",
        None,
        {"vehicleMass": 4000.0, "speed": 20.0, "crushDistance": 0.5, "impactAngle": 60.0},
    )
    assert res["problems"] == []
    assert res["summary"]["normalImpactSpeedMPerS"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["normalKineticEnergyKj"] == pytest.approx(200.0, rel=0.01)
    assert res["summary"]["averageStoppingForceKn"] == pytest.approx(400.0, rel=0.01)


# ── Studies Site (studies_site.py: 3) ─────────────────────────────────────────────────────────────


def test_studies_site_platform_levels() -> None:
    # Design = 10000 mm; points z = [9700, 10200, 10100] -> diffs = [+300 (fill), -200 (cut), -100 (cut)].
    # Mean abs diff = (300 + 200 + 100) / 3 = 200.0 mm.
    pts = "0,0,9700\n5000,0,10200\n10000,0,10100"
    res = features.run(
        "studiesSite.platformLevels",
        None,
        {"designLevel": 10000.0, "checkPoints": pts},
    )
    assert res["problems"] == []
    assert res["summary"]["checkCount"] == 3
    assert res["summary"]["meanAbsoluteDifferenceMm"] == pytest.approx(200.0, rel=0.01)
    rows = res["tables"][0]["rows"]
    assert rows[0]["cutOrFill"] == "fill"
    assert rows[1]["cutOrFill"] == "cut"


def test_studies_site_spoil_areas() -> None:
    # volume = 1200 m3, depth = 2.0 m -> net = 600 m2; gross = 600 * 1.25 / 0.75 = 1000 m2; side = sqrt(1000) = 31.6228 m.
    res = features.run(
        "studiesSite.spoilAreas",
        None,
        {"volume": 1200.0, "depth": 2.0, "usableFraction": 0.75, "slopeAllowance": 1.25},
    )
    assert res["problems"] == []
    assert res["summary"]["netFootprintM2"] == pytest.approx(600.0, rel=0.01)
    assert res["summary"]["grossAllocatedAreaM2"] == pytest.approx(1000.0, rel=0.01)
    assert res["summary"]["equivalentSquareSideM"] == pytest.approx(math.sqrt(1000.0), rel=0.01)


def test_studies_site_stockpile_volumes() -> None:
    # Frustum: rb = 6 m, rt = 3 m, h = 4 m -> V = pi * 4 * (36 + 18 + 9) / 3 = 84 * pi = 263.8938 m3.
    # Footprint = pi * 36 = 113.0973 m2; avg depth = V / footprint = 2.3333 m.
    res = features.run(
        "studiesSite.stockpileVolumes",
        None,
        {"baseRadius": 6.0, "topRadius": 3.0, "height": 4.0, "shape": "frustum"},
    )
    assert res["problems"] == []
    assert res["summary"]["volumeM3"] == pytest.approx(84.0 * math.pi, rel=0.01)
    assert res["summary"]["baseFootprintM2"] == pytest.approx(36.0 * math.pi, rel=0.01)
    assert res["summary"]["averageDepthM"] == pytest.approx(84.0 / 36.0, rel=0.01)


# ── Studies Verification (studies_verification.py: 3) ─────────────────────────────────────────────


def test_studies_verification_hand_calculations() -> None:
    # Simply supported beam: L = 8 m, w = 15 kN/m (= 15 N/mm), E = 200,000 MPa, I = 1e9 mm4:
    # M_max = 15 * 64 / 8 = 120.0 kN*m; R = 15 * 8 / 2 = 60.0 kN;
    # delta = 5 * 15 * 8000^4 / (384 * 200000 * 1e9) = 5 * 15 * 4.096e15 / 7.68e16 = 4.0 mm.
    res = features.run(
        "studiesVerification.handCalculations",
        None,
        {"span": 8.0, "load": 15.0, "elasticModulus": 200000.0, "inertia": 1e9},
    )
    assert res["problems"] == []
    assert res["summary"]["maximumMomentKnM"] == pytest.approx(120.0, rel=0.01)
    assert res["summary"]["supportReactionKn"] == pytest.approx(60.0, rel=0.01)
    assert res["summary"]["midspanDeflectionMm"] == pytest.approx(4.0, rel=0.01)


def test_studies_verification_solver_validity() -> None:
    # Case D: applied=200, reaction=199 -> rel=0.005 <= 0.01 (pass).
    # Case L: applied=100, reaction=103 -> rel=0.03 > 0.01 (fail).
    eq = json.dumps(
        [
            {"case": "D", "appliedKn": 200, "reactionKn": 199},
            {"case": "L", "appliedKn": 100, "reactionKn": 103},
        ]
    )
    res = features.run(
        "studiesVerification.solverValidity",
        None,
        {"equilibrium": eq, "relativeTolerance": 0.01},
    )
    assert res["problems"] == []
    assert res["summary"]["caseCount"] == 2
    assert res["summary"]["equilibriumPassCount"] == 1
    assert _row_by(res, "case", "D")["passes"] is True
    assert _row_by(res, "case", "L")["passes"] is False


def test_studies_verification_tolerance_setup() -> None:
    res = features.run(
        "studiesVerification.toleranceSetup",
        None,
        {"relative": 0.015, "absolute": 0.25, "quantity": "moment", "unit": "kN m"},
    )
    assert res["problems"] == []
    assert res["summary"]["quantity"] == "moment"
    assert res["summary"]["unit"] == "kN m"
    assert res["summary"]["relativeTolerance"] == pytest.approx(0.015, rel=0.01)
    assert res["summary"]["absoluteTolerance"] == pytest.approx(0.25, rel=0.01)

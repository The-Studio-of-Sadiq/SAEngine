"""Known-answer tests for Project Settings hazard tabs (18+10+18+21 = 67 features)."""

import math

import pytest

from saengine import features
from saengine.fem import thermal

# ── settings_hazard (18) ────────────────────────────────────────────────────────────────────────────


def test_settings_hazard_annual_exceedance() -> None:
    # T = 100 yr, L = 50 yr -> p_ann = (1 - exp(-0.01))*100 = 0.995%, p_life = (1 - (1-p)^50)*100 = 39.347%.
    res = features.run(
        "settingsHazard.annualExceedance",
        None,
        {"returnPeriodYears": 100.0, "exposureYears": 50.0},
    )
    assert res["problems"] == []
    p_ann = 1.0 - math.exp(-0.01)
    p_life = 1.0 - (1.0 - p_ann) ** 50.0
    assert res["summary"]["annualProbabilityPct"] == pytest.approx(p_ann * 100.0, rel=0.01)
    assert res["summary"]["lifetimeProbabilityPct"] == pytest.approx(p_life * 100.0, rel=0.01)


def test_settings_hazard_basic_wind_speed() -> None:
    # Default location yields V = 65.7 m/s; altitude = 500 m -> calt = 1 + 0.001*500 = 1.5 -> Vsite = 98.55.
    # q10 = 0.5 * 1.225 * 98.55^2 / 1000 = 5.9487 kPa.
    res = features.run("settingsHazard.basicWindSpeed", None, {"altitudeM": 500.0})
    assert res["problems"] == []
    v_site = 65.7 * 1.5
    q10 = 0.5 * 1.225 * (v_site**2) / 1000.0
    assert res["summary"]["altitudeFactor"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["windSpeedMPerS"] == pytest.approx(v_site, rel=0.01)
    assert res["summary"]["referencePressureKpa"] == pytest.approx(q10, rel=0.01)


def test_settings_hazard_construction_loads() -> None:
    # Vfull = 65.7 m/s, factor = 0.80 -> Vtemp = 52.56 m/s, pressureRatio = 0.64; staging = 2.0 + 2.5 = 4.5.
    res = features.run(
        "settingsHazard.constructionLoads",
        None,
        {"windReturnFactor": 0.80, "erectionLiveKnPerM2": 2.0, "materialStackKnPerM2": 2.5},
    )
    assert res["problems"] == []
    assert res["summary"]["constructionWindMPerS"] == pytest.approx(65.7 * 0.80, rel=0.01)
    assert res["summary"]["pressureRatio"] == pytest.approx(0.64, rel=0.01)
    assert res["summary"]["stagingLiveKnPerM2"] == pytest.approx(4.5, rel=0.01)


def test_settings_hazard_directionality_factor() -> None:
    # Override Kd = 0.90 vs packKd = 0.85 -> ratio = 0.90 / 0.85 = 1.0588.
    res = features.run("settingsHazard.directionalityFactor", None, {"kdOverride": 0.90})
    assert res["problems"] == []
    assert res["summary"]["packKd"] == pytest.approx(0.85, rel=0.01)
    assert res["summary"]["appliedKd"] == pytest.approx(0.90, rel=0.01)
    assert res["summary"]["pressureRatio"] == pytest.approx(0.90 / 0.85, rel=0.01)


def test_settings_hazard_expansive_soil_zone() -> None:
    # LL = 65 >= 60, PI = 40 >= 35 -> High / Very High; S = 0.00216 * 40^2.44 = 17.56%.
    res = features.run(
        "settingsHazard.expansiveSoilZone",
        None,
        {"liquidLimitPct": 65.0, "plasticityIndexPct": 40.0, "freeSwellPct": 110.0},
    )
    assert res["problems"] == []
    assert res["summary"]["expansionClass"] == "High / Very High"
    assert res["summary"]["estimatedSwellPct"] == pytest.approx(0.00216 * (40.0**2.44), rel=0.01)
    assert res["summary"]["requiresMitigation"] is True


def test_settings_hazard_fault_distance() -> None:
    # Source A, dist = 6.0 km -> Na = 1.5 - 0.3*(4/8) = 1.35, Nv = 2.0 - 0.4*(4/8) = 1.80.
    res = features.run(
        "settingsHazard.faultDistance",
        None,
        {"faultDistanceKm": 6.0, "sourceType": "A"},
    )
    assert res["problems"] == []
    assert res["summary"]["na"] == pytest.approx(1.35, rel=0.01)
    assert res["summary"]["nv"] == pytest.approx(1.80, rel=0.01)
    assert res["summary"]["nearFaultActive"] is True


def test_settings_hazard_frost_depth() -> None:
    # Stefan eq: FI=500 °C·day, k=2.0, w=20%, rho_d=1500 -> L = 334000*1500*0.2 = 1.002e8 J/m³.
    # zf = sqrt(2*2*500*86400 / 1.002e8) = 1.3151 m <= 1.5 m -> adequateEmbedment = True.
    res = features.run(
        "settingsHazard.frostDepth",
        None,
        {
            "airFreezingIndexDegDays": 500.0,
            "soilThermalCondWPerMK": 2.0,
            "moistureContentPct": 20.0,
            "dryDensityKgPerM3": 1500.0,
            "footingDepthM": 1.5,
        },
    )
    assert res["problems"] == []
    zf = math.sqrt((2.0 * 2.0 * 500.0 * 86400.0) / (334000.0 * 1500.0 * 0.20))
    assert res["summary"]["frostDepthM"] == pytest.approx(zf, rel=0.01)
    assert res["summary"]["adequateEmbedment"] is True


def test_settings_hazard_gust_factor() -> None:
    # Rigid building (n1 = 1.5 Hz >= 1.0 Hz) uses pack rigidGustFactor = 0.85.
    res = features.run(
        "settingsHazard.gustFactor",
        None,
        {"heightM": 40.0, "widthM": 25.0, "depthM": 20.0, "frequencyHz": 1.5, "dampingRatio": 0.02},
    )
    assert res["problems"] == []
    assert res["summary"]["flexible"] is False
    assert res["summary"]["governingGustFactor"] == pytest.approx(0.85, rel=0.01)


def test_settings_hazard_magnitude_distance() -> None:
    # Mw = 7.0, R = 20 km, Vs30 = 350 m/s -> r_eff = sqrt(400+56.25) = 21.36 km.
    # rockPga = exp(-2.1 + 0.85*7.0 - 1.35*ln(r_eff)), sitePga = rockPga * (760/350)^0.3.
    res = features.run(
        "settingsHazard.magnitudeDistance",
        None,
        {"magnitudeMw": 7.0, "distanceKm": 20.0, "vs30MPerS": 350.0},
    )
    assert res["problems"] == []
    r_eff = math.sqrt(20.0**2 + 7.5**2)
    pga_rock = math.exp(-2.1 + 0.85 * 7.0 - 1.35 * math.log(r_eff))
    pga_site = pga_rock * ((760.0 / 350.0) ** 0.3)
    assert res["summary"]["rockPgaG"] == pytest.approx(pga_rock, rel=0.01)
    assert res["summary"]["sitePgaG"] == pytest.approx(pga_site, rel=0.01)


def test_settings_hazard_pga_value() -> None:
    # Explicit override = 0.30 g overrides Z * pgaFactor.
    res = features.run("settingsHazard.pgaValue", None, {"pgaOverrideG": 0.30})
    assert res["problems"] == []
    assert res["summary"]["effectivePgaG"] == pytest.approx(0.30, rel=0.01)
    assert res["summary"]["zoneCoefficient"] == pytest.approx(0.20, rel=0.01)


def test_settings_hazard_radon_zone() -> None:
    # High radon potential over 600 m² -> 0.50 mm barrier and ceil(600/250) = 3 vent stacks.
    res = features.run(
        "settingsHazard.radonZone",
        None,
        {"radonClass": "high", "footprintAreaM2": 600.0},
    )
    assert res["problems"] == []
    assert res["summary"]["barrierThicknessMm"] == pytest.approx(0.50, rel=0.01)
    assert res["summary"]["ventStackCount"] == 3


def test_settings_hazard_snow_load_map() -> None:
    # With groundSnow = 1.5 kN/m² and pitch = 15°, flat/low-slope factor 0.8 -> roof snow = 1.20 kN/m².
    res = features.run(
        "settingsHazard.snowLoadMap",
        None,
        {"groundSnowKnPerM2": 1.5, "altitudeM": 300.0, "roofPitchDeg": 15.0},
    )
    assert res["problems"] == []
    assert res["summary"]["groundSnowKnPerM2"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["roofSnowKnPerM2"] == pytest.approx(1.20, rel=0.01)


def test_settings_hazard_spectral_acceleration() -> None:
    # Site class SD at default damping 0.05 produces peak normalized Cs = 3.375 and positive Sa.
    res = features.run("settingsHazard.spectralAcceleration", None, {"dampingRatio": 0.05})
    assert res["problems"] == []
    assert res["summary"]["siteClass"] == "SD"
    assert res["summary"]["peakCs"] == pytest.approx(3.375, rel=0.01)
    assert res["summary"]["peakDesignSaG"] > 0.0


def test_settings_hazard_terrain_categories() -> None:
    # Default exposure A up to z = 45 m yields power-law top factor > 1.0.
    res = features.run("settingsHazard.terrainCategories", None, {"maxHeightM": 45.0})
    assert res["problems"] == []
    assert res["summary"]["exposure"] == "A"
    assert res["summary"]["topFactor"] > 1.0


def test_settings_hazard_thermal_actions() -> None:
    # Steel frame (alpha = DEFAULT_ALPHA['steel']), dTu = 30 °C, E = 200,000 MPa.
    res = features.run(
        "settingsHazard.thermalActions",
        None,
        {"deltaTuC": 30.0, "deltaTgC": 10.0, "material": "steel", "modulusMpa": 200000.0},
    )
    assert res["problems"] == []
    alpha = thermal.DEFAULT_ALPHA["steel"]
    assert res["summary"]["freeStrainMicro"] == pytest.approx(alpha * 30.0 * 1e6, rel=0.01)
    assert res["summary"]["restrainedStressMpa"] == pytest.approx(200000.0 * alpha * 30.0, rel=0.01)


def test_settings_hazard_tsunami_zone() -> None:
    # h = 3.0 m, u = 4.0 m/s, b = 0.5 m, Cd = 2.0, rho_sw = 1025 kg/m³.
    # p_hydro = 1025*9.80665/1000 * 3.0 = 30.155 kPa; q_dyn = 0.5*1025*16/1000 = 8.2 kPa.
    # Fd = 2.0 * 8.2 * 0.5 * 3.0 = 24.6 kN.
    res = features.run(
        "settingsHazard.tsunamiZone",
        None,
        {"inundationDepthM": 3.0, "flowVelocityMPerS": 4.0, "columnWidthM": 0.5, "dragCoeff": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["hydrostaticBaseKpa"] == pytest.approx(
        1025.0 * 9.80665 / 1000.0 * 3.0, rel=0.01
    )
    assert res["summary"]["dynamicPressureKpa"] == pytest.approx(8.2, rel=0.01)
    assert res["summary"]["totalDragKn"] == pytest.approx(24.6, rel=0.01)


def test_settings_hazard_upwind_fetch() -> None:
    # x = 800 m, z0_max = 0.3 m -> delta_i = 0.28 * 0.3 * (800/0.3)^0.8 = 46.238 m >= 40 m.
    res = features.run(
        "settingsHazard.upwindFetch",
        None,
        {
            "fetchLengthM": 800.0,
            "roughnessUpstreamM": 0.03,
            "roughnessSiteM": 0.30,
            "buildingHeightM": 40.0,
        },
    )
    assert res["problems"] == []
    delta_i = 0.28 * 0.30 * ((800.0 / 0.30) ** 0.8)
    assert res["summary"]["boundaryHeightM"] == pytest.approx(delta_i, rel=0.01)
    assert res["summary"]["fullyAdaptedToSite"] is True


def test_settings_hazard_wind_exposure() -> None:
    # At height z = 20 m, active exposure A factor equals 0.8761 across 3 categories.
    res = features.run("settingsHazard.windExposure", None, {"heightM": 20.0})
    assert res["problems"] == []
    assert res["summary"]["activeExposure"] == "A"
    assert res["summary"]["exposureCount"] == 3
    row_a = next(r for r in res["tables"][0]["rows"] if r["id"] == "A")
    assert row_a["factorAtZ"] == pytest.approx(0.8761, rel=0.01)


# ── settings_hazard_maps (10) ───────────────────────────────────────────────────────────────────────


def test_settings_hazard_maps_active_faults() -> None:
    # ~0.10 deg longitude apart at lat 24° is ~10.16 km <= 15 km -> withinNearField15Km = True.
    res = features.run(
        "settingsHazardMaps.activeFaults",
        None,
        {"siteLat": 24.0, "siteLon": 90.0, "faultLat": 24.0, "faultLon": 90.1},
    )
    assert res["problems"] == []
    assert 9.5 < res["summary"]["distanceToFaultKm"] < 11.5
    assert res["summary"]["withinNearField15Km"] is True


def test_settings_hazard_maps_attenuation_model() -> None:
    # Mw = 6.5, R = 24 km -> r_eff = sqrt(24² + 8²) = sqrt(640) = 25.298 km.
    # sa02 = exp(-1.5 + 0.85*6.5 - 1.30*ln(r_eff)), sa10 = exp(-2.8 + 6.5 - 1.15*ln(r_eff)).
    res = features.run(
        "settingsHazardMaps.attenuationModel",
        None,
        {"magnitudeMw": 6.5, "distanceKm": 24.0},
    )
    assert res["problems"] == []
    r_eff = math.sqrt(24.0**2 + 8.0**2)
    assert res["summary"]["sa02G"] == pytest.approx(
        math.exp(-1.5 + 0.85 * 6.5 - 1.30 * math.log(r_eff)), rel=0.01
    )
    assert res["summary"]["sa10G"] == pytest.approx(
        math.exp(-2.8 + 1.00 * 6.5 - 1.15 * math.log(r_eff)), rel=0.01
    )


def test_settings_hazard_maps_contour_value() -> None:
    # Dhaka station lookup returns wind speed = 65.7 m/s and positive Z.
    res = features.run(
        "settingsHazardMaps.contourValue",
        None,
        {"latitudeDeg": 23.8103, "longitudeDeg": 90.4125},
    )
    assert res["problems"] == []
    assert res["summary"]["nearestStation"] == "Dhaka"
    assert res["summary"]["windMPerS"] == pytest.approx(65.7, rel=0.01)


def test_settings_hazard_maps_grid_overlay() -> None:
    # 3x3 sampling grid yields 9 points with step = 0.1 deg.
    res = features.run(
        "settingsHazardMaps.gridOverlay",
        None,
        {"centerLat": 24.0, "centerLon": 90.0, "stepDeg": 0.1},
    )
    assert res["problems"] == []
    assert res["summary"]["gridPoints"] == 9
    assert res["summary"]["stepDeg"] == pytest.approx(0.1, rel=0.01)


def test_settings_hazard_maps_interpolate_value() -> None:
    # kNearest = 4 stations weighted by 1/d² yields positive interpolated wind speed.
    res = features.run(
        "settingsHazardMaps.interpolateValue",
        None,
        {"latitudeDeg": 23.95, "longitudeDeg": 90.45, "kNearest": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["stationsUsed"] == 4
    assert res["summary"]["interpolatedWindMPerS"] > 50.0


def test_settings_hazard_maps_landslide_area() -> None:
    # kh = 0.5 * 0.30 = 0.15; phi_req = 25.0 + degrees(atan(0.15)) = 33.53°; elevatedRisk = True.
    res = features.run(
        "settingsHazardMaps.landslideArea",
        None,
        {"hillSlopeDeg": 25.0, "pgaG": 0.30},
    )
    assert res["problems"] == []
    assert res["summary"]["kh"] == pytest.approx(0.15, rel=0.01)
    assert res["summary"]["requiredFrictionDeg"] == pytest.approx(
        25.0 + math.degrees(math.atan(0.15)), rel=0.01
    )
    assert res["summary"]["elevatedRisk"] is True


def test_settings_hazard_maps_latitude_longitude() -> None:
    # Lon = 91.5° -> UTM zone = int((91.5 + 180)/6) + 1 = 46; lat > 0 -> "46N".
    res = features.run(
        "settingsHazardMaps.latitudeLongitude",
        None,
        {"latitudeDeg": 24.5, "longitudeDeg": 91.5},
    )
    assert res["problems"] == []
    assert res["summary"]["utmZone"] == "46N"


def test_settings_hazard_maps_map_preview() -> None:
    # Radius 150 km around Dhaka captures mapped weather/seismic stations.
    res = features.run(
        "settingsHazardMaps.mapPreview",
        None,
        {"latitudeDeg": 23.81, "longitudeDeg": 90.41, "radiusKm": 150.0},
    )
    assert res["problems"] == []
    assert res["summary"]["stationsWithinRadius"] > 0
    assert res["summary"]["radiusKm"] == pytest.approx(150.0, rel=0.01)


def test_settings_hazard_maps_site_amplification() -> None:
    # T_site = 4 * 30 / 240 = 0.50 s -> frequency = 2.0 Hz.
    res = features.run(
        "settingsHazardMaps.siteAmplification",
        None,
        {"softLayerDepthM": 30.0, "shearWaveVsMPerS": 240.0},
    )
    assert res["problems"] == []
    assert res["summary"]["sitePeriodS"] == pytest.approx(0.5, rel=0.01)
    assert res["summary"]["siteFrequencyHz"] == pytest.approx(2.0, rel=0.01)


def test_settings_hazard_maps_soil_factor() -> None:
    # Vs30 = 190 m/s -> 760/190 = 4.0 -> Fa = 4^0.25 = sqrt(2) = 1.4142, Fv = 4^0.40 = 1.7411.
    res = features.run("settingsHazardMaps.soilFactor", None, {"vs30MPerS": 190.0})
    assert res["problems"] == []
    assert res["summary"]["shortPeriodFactor"] == pytest.approx(4.0**0.25, rel=0.01)
    assert res["summary"]["oneSecFactor"] == pytest.approx(4.0**0.40, rel=0.01)


# ── settings_hazard_return (18) ─────────────────────────────────────────────────────────────────────


def test_settings_hazard_return_annual_probability() -> None:
    # P = 1.0% (0.01) -> TR = -1 / ln(0.99) = 99.499 yr.
    res = features.run("settingsHazardReturn.annualProbability", None, {"annualProbPct": 1.0})
    assert res["problems"] == []
    assert res["summary"]["impliedReturnPeriodYears"] == pytest.approx(
        -1.0 / math.log(0.99), rel=0.01
    )


def test_settings_hazard_return_apply_other() -> None:
    # Direct echo of snow, rain, and flood return periods.
    res = features.run(
        "settingsHazardReturn.applyOther",
        None,
        {"snowReturnYears": 75.0, "rainReturnYears": 150.0, "floodReturnYears": 200.0},
    )
    assert res["problems"] == []
    assert res["summary"]["snowReturnYears"] == pytest.approx(75.0, rel=0.01)
    assert res["summary"]["rainReturnYears"] == pytest.approx(150.0, rel=0.01)
    assert res["summary"]["floodReturnYears"] == pytest.approx(200.0, rel=0.01)


def test_settings_hazard_return_apply_seismic() -> None:
    # Scale = (950 / 475)^0.38 = 2^0.38 = 1.3013.
    res = features.run(
        "settingsHazardReturn.applySeismic",
        None,
        {"targetReturnYears": 950.0, "baselineReturnYears": 475.0},
    )
    assert res["problems"] == []
    assert res["summary"]["impliedHazardMultiplier"] == pytest.approx(2.0**0.38, rel=0.01)


def test_settings_hazard_return_apply_wind() -> None:
    # Echoes adopted wind return period 100 yr alongside derived basic wind 65.7 m/s.
    res = features.run("settingsHazardReturn.applyWind", None, {"returnYears": 100.0})
    assert res["problems"] == []
    assert res["summary"]["returnPeriodYears"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["derivedWindMPerS"] == pytest.approx(65.7, rel=0.01)


def test_settings_hazard_return_drift_return() -> None:
    # Direct echo of wind and seismic drift check return periods.
    res = features.run(
        "settingsHazardReturn.driftReturn",
        None,
        {"windDriftReturnYears": 20.0, "seismicDriftReturnYears": 475.0},
    )
    assert res["problems"] == []
    assert res["summary"]["windDriftReturnYears"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["seismicDriftReturnYears"] == pytest.approx(475.0, rel=0.01)


def test_settings_hazard_return_envelope_multiplier() -> None:
    # 0.40 * 1.25 = 0.50.
    res = features.run(
        "settingsHazardReturn.envelopeMultiplier",
        None,
        {"baseHazard": 0.40, "envMultiplier": 1.25},
    )
    assert res["problems"] == []
    assert res["summary"]["envelopedHazard"] == pytest.approx(0.50, rel=0.01)


def test_settings_hazard_return_exposure_time() -> None:
    # TL = 50 yr, P = 10% -> TR = -50 / ln(0.90) = 474.56 yr.
    res = features.run(
        "settingsHazardReturn.exposureTime",
        None,
        {"exposureYears": 50.0, "targetExceedancePct": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredReturnPeriodYears"] == pytest.approx(
        -50.0 / math.log(0.90), rel=0.01
    )


def test_settings_hazard_return_extreme_scaling() -> None:
    # 0.40 g * 1.50 = 0.60 g.
    res = features.run(
        "settingsHazardReturn.extremeScaling",
        None,
        {"scaleFactor": 1.50, "saAtT1G": 0.40},
    )
    assert res["problems"] == []
    assert res["summary"]["scaledSaG"] == pytest.approx(0.60, rel=0.01)


def test_settings_hazard_return_frequent_return() -> None:
    # TR = 10 yr -> p = 1/10 -> v_ratio = sqrt((1 - 0.14*ln(-ln(0.9)))/1.54), q_ratio = v_ratio².
    res = features.run("settingsHazardReturn.frequentReturn", None, {"frequentYears": 10.0})
    assert res["problems"] == []
    v_ratio = math.sqrt((1.0 - 0.14 * math.log(-math.log(0.9))) / 1.54)
    assert res["summary"]["speedRatio"] == pytest.approx(v_ratio, rel=0.01)
    assert res["summary"]["pressureRatio"] == pytest.approx(v_ratio**2, rel=0.01)


def test_settings_hazard_return_gust_duration() -> None:
    # 60s sustained uses Durst factor 0.806 -> 50.0 * 0.806 = 40.30 m/s.
    res = features.run(
        "settingsHazardReturn.gustDuration",
        None,
        {"gust3sMPerS": 50.0, "targetDuration": "60s"},
    )
    assert res["problems"] == []
    assert res["summary"]["durstFactor"] == pytest.approx(0.806, rel=0.01)
    assert res["summary"]["convertedSpeedMPerS"] == pytest.approx(40.30, rel=0.01)


def test_settings_hazard_return_maximum_considered() -> None:
    # MCE TR = 2500 yr -> 50-yr exceedance = (1 - exp(-50/2500))*100 = 1.9801%.
    res = features.run(
        "settingsHazardReturn.maximumConsidered",
        None,
        {"mceReturnYears": 2500.0, "dbeScale": 0.6667},
    )
    assert res["problems"] == []
    assert res["summary"]["exceedance50YrPct"] == pytest.approx(
        (1.0 - math.exp(-50.0 / 2500.0)) * 100.0, rel=0.01
    )
    assert res["summary"]["dbeToMceRatio"] == pytest.approx(0.6667, rel=0.01)


def test_settings_hazard_return_occasional_return() -> None:
    # TR = 100 yr -> (100 / 475)^0.38 = 0.5535.
    res = features.run("settingsHazardReturn.occasionalReturn", None, {"occasionalYears": 100.0})
    assert res["problems"] == []
    assert res["summary"]["hazardRatioVs475"] == pytest.approx((100.0 / 475.0) ** 0.38, rel=0.01)


def test_settings_hazard_return_rain_return() -> None:
    # i_50 = 100 * (50/100)^0.16 = 89.5025 mm/hr.
    res = features.run(
        "settingsHazardReturn.rainReturn",
        None,
        {"rain100MmHr": 100.0, "targetReturnYears": 50.0},
    )
    assert res["problems"] == []
    assert res["summary"]["intensityMmPerHr"] == pytest.approx(100.0 * (0.5**0.16), rel=0.01)


def test_settings_hazard_return_rare_event() -> None:
    # Direct echo of rare return period and rare-to-design spectrum ratio.
    res = features.run(
        "settingsHazardReturn.rareEvent",
        None,
        {"rareReturnYears": 2500.0, "rareRatio": 1.6},
    )
    assert res["problems"] == []
    assert res["summary"]["rareReturnYears"] == pytest.approx(2500.0, rel=0.01)
    assert res["summary"]["rareToDesignRatio"] == pytest.approx(1.6, rel=0.01)


def test_settings_hazard_return_return_period() -> None:
    # TR = 500 yr, TL = 50 yr -> p_ann = (1 - exp(-1/500))*100 = 0.1998%, p_life = (1 - exp(-0.1))*100 = 9.516%.
    res = features.run(
        "settingsHazardReturn.returnPeriod",
        None,
        {"returnPeriodYears": 500.0, "designLifeYears": 50.0},
    )
    assert res["problems"] == []
    assert res["summary"]["annualExceedancePct"] == pytest.approx(
        (1.0 - math.exp(-1.0 / 500.0)) * 100.0, rel=0.01
    )
    assert res["summary"]["lifetimeExceedancePct"] == pytest.approx(
        (1.0 - math.exp(-50.0 / 500.0)) * 100.0, rel=0.01
    )


def test_settings_hazard_return_service_factor() -> None:
    # Compares target wind service factor 0.65 against active pack wind service factor 0.70.
    res = features.run("settingsHazardReturn.serviceFactor", None, {"windServiceFactor": 0.65})
    assert res["problems"] == []
    assert res["summary"]["packWindServiceFactor"] == pytest.approx(0.70, rel=0.01)
    assert res["summary"]["targetFactor"] == pytest.approx(0.65, rel=0.01)


def test_settings_hazard_return_snow_return() -> None:
    # sk50 = 2.0, TR = 100 -> k = 1 + 0.23*ln(2) = 1.1594 -> sk100 = 2.3189 kPa.
    res = features.run(
        "settingsHazardReturn.snowReturn",
        None,
        {"snow50Kpa": 2.0, "targetReturnYears": 100.0},
    )
    assert res["problems"] == []
    k = 1.0 + 0.23 * math.log(2.0)
    assert res["summary"]["scaleFactor"] == pytest.approx(k, rel=0.01)
    assert res["summary"]["scaledSnowKpa"] == pytest.approx(2.0 * k, rel=0.01)


def test_settings_hazard_return_wind_return() -> None:
    # V50 = 60 m/s, TR = 100 yr -> Gumbel scaling > 1.0 gives V100 > 60 m/s.
    res = features.run(
        "settingsHazardReturn.windReturn",
        None,
        {"returnYears": 100.0, "baseSpeedMPerS": 60.0},
    )
    assert res["problems"] == []
    p = 1.0 - math.exp(-0.01)
    k_tr = (1.0 - 0.138 * math.log(-math.log(1.0 - p))) / (1.0 - 0.138 * math.log(-math.log(0.98)))
    v_tr = 60.0 * math.sqrt(k_tr)
    assert res["summary"]["speedMultiplier"] == pytest.approx(math.sqrt(k_tr), rel=0.01)
    assert res["summary"]["scaledWindMPerS"] == pytest.approx(v_tr, rel=0.01)


# ── settings_hazard_snow_thermal (21) ───────────────────────────────────────────────────────────────


def test_settings_hazard_snow_thermal_apply_rain() -> None:
    # 120 mm water head * 9.81 = 1.1772 kPa.
    res = features.run("settingsHazardSnowThermal.applyRain", None, {"waterDepthMm": 120.0})
    assert res["problems"] == []
    assert res["summary"]["rainLoadKpa"] == pytest.approx(1.1772, rel=0.01)


def test_settings_hazard_snow_thermal_apply_snow() -> None:
    # pf = 0.7 * 1.1 * 1.0 * 2.0 = 1.54 kPa.
    res = features.run(
        "settingsHazardSnowThermal.applySnow",
        None,
        {"groundSnowKpa": 2.0, "ce": 1.1, "ct": 1.0},
    )
    assert res["problems"] == []
    assert res["summary"]["flatRoofSnowKpa"] == pytest.approx(1.54, rel=0.01)


def test_settings_hazard_snow_thermal_combined_wind_ice() -> None:
    # b = 300 mm, ti = 25 mm -> iced = 350 mm = 0.35 m. Vi = 30 m/s -> qi = 0.5*1.225*900/1000 = 0.55125 kPa.
    # Fw = 1.4 * 0.55125 * 0.35 = 0.27011 kN/m.
    res = features.run(
        "settingsHazardSnowThermal.combinedWindIce",
        None,
        {"memberWidthMm": 300.0, "iceThicknessMm": 25.0, "concurrentWindMPerS": 30.0, "cf": 1.4},
    )
    assert res["problems"] == []
    assert res["summary"]["icedWidthMm"] == pytest.approx(350.0, rel=0.01)
    assert res["summary"]["iceWindPressureKpa"] == pytest.approx(0.55125, rel=0.01)
    assert res["summary"]["windForceKnPerM"] == pytest.approx(1.4 * 0.55125 * 0.35, rel=0.01)


def test_settings_hazard_snow_thermal_deflection_ponding() -> None:
    # Cp = 0.20 -> amp = 1 / 0.8 = 1.25; final = 16.0 * 1.25 = 20.0 mm; stable = True.
    res = features.run(
        "settingsHazardSnowThermal.deflectionPonding",
        None,
        {"initialDeflectionMm": 16.0, "flexibilityIndex": 0.20},
    )
    assert res["problems"] == []
    assert res["summary"]["pondingAmplification"] == pytest.approx(1.25, rel=0.01)
    assert res["summary"]["finalDeflectionMm"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["stable"] is True


def test_settings_hazard_snow_thermal_drain_clogging() -> None:
    # 60 + 60 = 120 mm total water -> 0.12 * 9.81 = 1.1772 kPa.
    res = features.run(
        "settingsHazardSnowThermal.drainClogging",
        None,
        {"scupperSillMm": 60.0, "hydraulicHeadMm": 60.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalWaterMm"] == pytest.approx(120.0, rel=0.01)
    assert res["summary"]["pondingLoadKpa"] == pytest.approx(1.1772, rel=0.01)


def test_settings_hazard_snow_thermal_elevation_factor() -> None:
    # alt = 800 m -> factor = 1 + 0.0008*(800-300) = 1.40; snow = 1.5 * 1.40 = 2.10 kPa.
    res = features.run(
        "settingsHazardSnowThermal.elevationFactor",
        None,
        {"altitudeM": 800.0, "baseSnowKpa": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["elevationMultiplier"] == pytest.approx(1.40, rel=0.01)
    assert res["summary"]["adjustedSnowKpa"] == pytest.approx(2.10, rel=0.01)


def test_settings_hazard_snow_thermal_freezing_rain() -> None:
    # ti = 40 mm = 0.04 m, D = 200 mm = 0.20 m -> A = pi*0.04*0.24 = 0.030159 m² = 30159.3 mm².
    # w = 0.030159 * 9.0 = 0.27143 kN/m.
    res = features.run(
        "settingsHazardSnowThermal.freezingRain",
        None,
        {"iceThicknessMm": 40.0, "memberDiameterMm": 200.0},
    )
    assert res["problems"] == []
    a_ice = math.pi * 0.04 * 0.24
    assert res["summary"]["iceAreaMm2"] == pytest.approx(a_ice * 1e6, rel=0.01)
    assert res["summary"]["iceWeightKnPerM"] == pytest.approx(a_ice * 9.0, rel=0.01)


def test_settings_hazard_snow_thermal_ground_load() -> None:
    # Direct override ground snow = 1.8 kN/m².
    res = features.run("settingsHazardSnowThermal.groundLoad", None, {"groundSnowKpa": 1.8})
    assert res["problems"] == []
    assert res["summary"]["groundSnowKnPerM2"] == pytest.approx(1.8, rel=0.01)


def test_settings_hazard_snow_thermal_overflow_scupper() -> None:
    # b = 0.4 m, h = 0.09 m -> h^1.5 = 0.027 -> Q = 1.84 * 0.4 * 0.027 = 0.019872 m³/s = 19.872 L/s.
    res = features.run(
        "settingsHazardSnowThermal.overflowScupper",
        None,
        {"scupperWidthMm": 400.0, "headMm": 90.0},
    )
    assert res["problems"] == []
    assert res["summary"]["scupperFlowLPerS"] == pytest.approx(19.872, rel=0.01)


def test_settings_hazard_snow_thermal_radial_ice() -> None:
    # z = 10 m -> fz = 1.0 -> designIce = 20.0 mm; z = 80 m -> 8^0.10 = 1.2311.
    res = features.run(
        "settingsHazardSnowThermal.radialIce",
        None,
        {"baseIceMm": 20.0, "heightM": 80.0},
    )
    assert res["problems"] == []
    fz = 8.0**0.10
    assert res["summary"]["heightFactor"] == pytest.approx(fz, rel=0.01)
    assert res["summary"]["designIceMm"] == pytest.approx(20.0 * fz, rel=0.01)


def test_settings_hazard_snow_thermal_rain_duration() -> None:
    # d = 15 min, i60 = 100 mm/hr -> i15 = 100 * 4^0.55 = 214.35 mm/hr; depth = i15 * 0.25 = 53.59 mm.
    res = features.run(
        "settingsHazardSnowThermal.rainDuration",
        None,
        {"durationMin": 15.0, "intensity60MmHr": 100.0},
    )
    assert res["problems"] == []
    i_t = 100.0 * (4.0**0.55)
    assert res["summary"]["adjustedIntensityMmHr"] == pytest.approx(i_t, rel=0.01)
    assert res["summary"]["totalDepthMm"] == pytest.approx(i_t * 0.25, rel=0.01)


def test_settings_hazard_snow_thermal_rain_intensity() -> None:
    # Q = 90 mm/hr * 800 m² / 3600 = 20.0 L/s.
    res = features.run(
        "settingsHazardSnowThermal.rainIntensity",
        None,
        {"intensityMmHr": 90.0, "roofAreaM2": 800.0},
    )
    assert res["problems"] == []
    assert res["summary"]["runoffLPerS"] == pytest.approx(20.0, rel=0.01)


def test_settings_hazard_snow_thermal_roof_drainage() -> None:
    # runoff = 30 L/s, drain cap = 10 L/s -> 3 primary drains -> 900 / 3 = 300 m²/drain.
    res = features.run(
        "settingsHazardSnowThermal.roofDrainage",
        None,
        {"roofAreaM2": 900.0, "drainCapacityLPerS": 10.0, "runoffLPerS": 30.0},
    )
    assert res["problems"] == []
    assert res["summary"]["primaryDrains"] == 3
    assert res["summary"]["areaPerDrainM2"] == pytest.approx(300.0, rel=0.01)


def test_settings_hazard_snow_thermal_roof_shape() -> None:
    # Shallow pitch 15° keeps full shape factor 1.0 under standard rules.
    res = features.run(
        "settingsHazardSnowThermal.roofShape",
        None,
        {"pitchDeg": 15.0, "slippery": False},
    )
    assert res["problems"] == []
    assert res["summary"]["shapeOrSlopeFactor"] == pytest.approx(1.0, rel=0.01)


def test_settings_hazard_snow_thermal_snow_drift() -> None:
    # parapet = 0.8 m, sk = 2.0 kPa -> hd = min(0.8, 1.5) = 0.8 m; ls = min(15, max(5, 1.6)) = 5.0 m; pd = 1.6 kPa.
    res = features.run(
        "settingsHazardSnowThermal.snowDrift",
        None,
        {"parapetHeightM": 0.8, "groundSnowKpa": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["driftHeightM"] == pytest.approx(0.8, rel=0.01)
    assert res["summary"]["driftLengthM"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["driftSurchargeKpa"] == pytest.approx(1.6, rel=0.01)


def test_settings_hazard_snow_thermal_solar_radiation() -> None:
    # solAirRise = 0.80 * 1000 / 25 = 32.0 °C.
    res = features.run(
        "settingsHazardSnowThermal.solarRadiation",
        None,
        {"absorptance": 0.80, "irradianceWPerM2": 1000.0, "hConvWPerM2K": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["solAirRiseC"] == pytest.approx(32.0, rel=0.01)


def test_settings_hazard_snow_thermal_temperature_gradient() -> None:
    # top=65 °C, bottom=15 °C -> dTg = 50 °C; slab = 100 mm = 0.1 m -> kappa = alpha_conc * 50 / 0.1 = 0.005 /m.
    res = features.run(
        "settingsHazardSnowThermal.temperatureGradient",
        None,
        {"topTempC": 65.0, "bottomTempC": 15.0, "slabDepthMm": 100.0},
    )
    assert res["problems"] == []
    alpha = thermal.DEFAULT_ALPHA["concrete"]
    assert res["summary"]["deltaTgC"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["thermalCurvaturePerM"] == pytest.approx((alpha * 50.0) / 0.1, rel=0.01)


def test_settings_hazard_snow_thermal_temperature_range() -> None:
    # Tmin = -5, Tmax = 45, T0 = 20 -> +25 expansion, -25 contraction, 50 swing.
    res = features.run(
        "settingsHazardSnowThermal.temperatureRange",
        None,
        {"tMinC": -5.0, "tMaxC": 45.0, "tInstallC": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["expansionDeltaTC"] == pytest.approx(25.0, rel=0.01)
    assert res["summary"]["contractionDeltaTC"] == pytest.approx(-25.0, rel=0.01)
    assert res["summary"]["totalSwingC"] == pytest.approx(50.0, rel=0.01)


def test_settings_hazard_snow_thermal_thermal_movement() -> None:
    # dL = alpha_steel * 50000 mm * 30 °C.
    res = features.run(
        "settingsHazardSnowThermal.thermalMovement",
        None,
        {"lengthM": 50.0, "deltaTC": 30.0, "material": "steel"},
    )
    assert res["problems"] == []
    expected = thermal.DEFAULT_ALPHA["steel"] * 50000.0 * 30.0
    assert res["summary"]["movementMm"] == pytest.approx(expected, rel=0.01)


def test_settings_hazard_snow_thermal_urban_thermal() -> None:
    # 35.0 + 4.5 = 39.5 °C.
    res = features.run(
        "settingsHazardSnowThermal.urbanThermal",
        None,
        {"ruralTempC": 35.0, "urbanHeatIslandC": 4.5},
    )
    assert res["problems"] == []
    assert res["summary"]["effectiveMaxTempC"] == pytest.approx(39.5, rel=0.01)


def test_settings_hazard_snow_thermal_water_head() -> None:
    # 200 mm = 0.2 m * 9.81 = 1.962 kPa.
    res = features.run("settingsHazardSnowThermal.waterHead", None, {"depthMm": 200.0})
    assert res["problems"] == []
    assert res["summary"]["pressureKpa"] == pytest.approx(1.962, rel=0.01)

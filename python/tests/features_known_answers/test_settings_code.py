"""Independent known-answer tests for standalone calculators in Project Settings Code, Libraries, Localisation, and Code Values."""

from __future__ import annotations

import math

import pytest

from saengine import features

# ── Settings Code (settings_code.py: 5) ─────────────────────────────────────────────────────────


def test_settings_design_approach() -> None:
    # Default pack shallow bearing resistance factor gamma_r = 3.5 (bearingPhi = 1/3.5 in default pack),
    # gamma_g = 1.0, gamma_m = 1.0 -> q_design = 400 / 3.5 = 114.286 kPa, Rd = 114.286 * 4.0 = 457.143 kN.
    # Vd = 800 * 1.0 = 800 kN -> utilisation = 800 / 457.143 = 1.75 (> 1.0 -> passing False).
    res = features.run(
        "settings.designApproach",
        None,
        {
            "approach": "pack",
            "characteristicLoadKn": 800.0,
            "characteristicBearingKpa": 400.0,
            "footingAreaM2": 4.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["designDemandKn"] == pytest.approx(800.0, rel=0.01)
    assert res["summary"]["designResistanceKn"] == pytest.approx(457.143, rel=0.01)
    assert res["summary"]["utilisation"] == pytest.approx(1.75, rel=0.01)
    assert res["summary"]["passing"] is False


def test_settings_design_working_life() -> None:
    # T = 100 yr, Tr = 500 yr: annual_p = 1 - exp(-1/500) = 0.00199800 (0.1998%),
    # lifetime_p = 1 - (1 - annual_p)^100 = 1 - exp(-100/500) = 1 - exp(-0.2) = 18.1269%.
    # T >= 100 yr -> default pack concreteMethods.cover.longLifeIncrease = 2.
    annual_p = 1.0 - math.exp(-1.0 / 500.0)
    life_p = 1.0 - (1.0 - annual_p) ** 100.0
    res = features.run(
        "settings.designWorkingLife",
        None,
        {"workingLifeYears": 100.0, "returnPeriodYears": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["annualExceedancePct"] == pytest.approx(annual_p * 100.0, rel=0.01)
    assert res["summary"]["lifetimeExceedancePct"] == pytest.approx(life_p * 100.0, rel=0.01)
    assert res["summary"]["structuralClassIncrease"] == 2


def test_settings_exposure_conditions() -> None:
    # XC4, bar = 25 mm, f'c = 30 MPa, aggregate = 20 mm:
    # From default pack concreteMethods.cover (BNBC 2020): cmin,b = 25 mm, cmin,dur = 30 mm,
    # delta_cdev = 10 mm -> cnom = 40 mm.
    res = features.run(
        "settings.exposureConditions",
        None,
        {"exposure": "XC4", "barDiameterMm": 25.0, "fckMpa": 30.0, "aggregateMm": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["cminBondMm"] == pytest.approx(25.0, rel=0.01)
    assert res["summary"]["cminDurabilityMm"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["nominalCoverMm"] == pytest.approx(40.0, rel=0.01)


def test_settings_regional_format() -> None:
    # SI formatting with commas and 3+ significant digits rounds 54321.5 kN -> "54,322 kN".
    res = features.run(
        "settings.regionalFormat",
        None,
        {"sampleValueKn": 54321.5, "sampleStressMpa": 35.25, "dateStyle": "dmy"},
    )
    assert res["problems"] == []
    assert res["summary"]["dateStyle"] == "dmy"
    assert res["summary"]["forceDisplay"] == "54,322 kN"


def test_settings_site_location() -> None:
    # Coordinates (23.8103, 90.4125) are Dhaka in the default pack's GIS towns table (distance < 1 km).
    res = features.run(
        "settings.siteLocation",
        None,
        {"latitudeDeg": 23.8103, "longitudeDeg": 90.4125, "elevationM": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["nearestStation"] == "Dhaka"
    assert res["summary"]["distanceKm"] < 2.0
    assert res["summary"]["windSpeedMPerS"] > 0.0


# ── Settings Code Libraries (settings_code_libraries.py: 4) ─────────────────────────────────────


def test_settings_code_libraries_mesh_grades() -> None:
    # 10 mm wire at 200 mm spacing: A_s = (pi * 10^2 / 4) * (1000 / 200) = 78.5398 * 5 = 392.699 mm2/m.
    # Mass (both ways) = 2 * 392.699 * 7.85e-3 = 6.1654 kg/m2.
    # Tensile force at fy = 500 MPa: 392.699 * 500 / 1000 = 196.350 kN/m.
    area_m = (math.pi * 10.0**2 / 4.0) * (1000.0 / 200.0)
    res = features.run(
        "settingsCodeLibraries.meshGrades",
        None,
        {"barMm": 10.0, "spacingMm": 200.0, "fyMpa": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["areaMm2PerM"] == pytest.approx(area_m, rel=0.01)
    assert res["summary"]["massKgPerM2"] == pytest.approx(2.0 * area_m * 7.85e-3, rel=0.01)
    assert res["summary"]["tensileForceKnPerM"] == pytest.approx(area_m * 0.5, rel=0.01)


def test_settings_code_libraries_rebar_catalogue() -> None:
    # For fy = 500 MPa, check the 20 mm bar row: area = pi*20^2/4 = 314.159 mm2,
    # yieldKn = 314.159 * 500 / 1000 = 157.080 kN, minBendRadiusMm = 3 * 20 = 60 mm.
    res = features.run(
        "settingsCodeLibraries.rebarCatalogue",
        None,
        {"fyMpa": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["fyMpa"] == pytest.approx(500.0, rel=0.01)
    row_20 = next(r for r in res["tables"][0]["rows"] if r["diaMm"] == pytest.approx(20.0))
    assert row_20["areaMm2"] == pytest.approx(math.pi * 100.0, rel=0.01)
    assert row_20["yieldKn"] == pytest.approx(math.pi * 100.0 * 0.5, rel=0.01)
    assert row_20["minBendRadiusMm"] == pytest.approx(60.0, rel=0.01)


def test_settings_code_libraries_tendon_types() -> None:
    # 12.7 mm strand: A = 98.7 mm2, fpu = 1860 MPa -> breaking = 98.7 * 1.860 = 183.582 kN;
    # jacking at 0.80 * fpu -> 183.582 * 0.80 = 146.8656 kN.
    res = features.run(
        "settingsCodeLibraries.tendonTypes",
        None,
        {"strandSize": "12.7", "fpuMpa": 1860.0, "jackingShare": 0.8},
    )
    assert res["problems"] == []
    assert res["summary"]["strandAreaMm2"] == pytest.approx(98.7, rel=0.01)
    assert res["summary"]["breakingForceKn"] == pytest.approx(98.7 * 1.86, rel=0.01)
    assert res["summary"]["jackingForceKn"] == pytest.approx(98.7 * 1.86 * 0.8, rel=0.01)


def test_settings_code_libraries_weld_types() -> None:
    # Leg w = 8.0 mm -> throat te = 0.7071 * 8 = 5.6568 mm.
    # Fexx = 500 MPa -> Rn/mm = 0.60 * 500 * 5.6568 / 1000 = 1.69704 kN/mm.
    # Default pack steel.phi["weld"] = 0.75 -> design phi*Rn = 0.75 * 1.69704 = 1.27278 kN/mm.
    throat = 0.7071 * 8.0
    phi_rn = 0.75 * 0.60 * 500.0 * throat / 1000.0
    res = features.run(
        "settingsCodeLibraries.weldTypes",
        None,
        {"electrodeFexxMpa": 500.0, "legSizeMm": 8.0},
    )
    assert res["problems"] == []
    assert res["summary"]["throatMm"] == pytest.approx(throat, rel=0.01)
    assert res["summary"]["designStrengthKnPerMm"] == pytest.approx(phi_rn, rel=0.01)


# ── Settings Code Localisation (settings_code_localisation.py: 6) ───────────────────────────────


def test_settings_code_localisation_convert_units() -> None:
    # 10 m -> ft: 10.0 / 0.3048 = 32.8084 ft.
    res = features.run(
        "settingsCodeLocalisation.convertUnits",
        None,
        {"inputValue": 10.0, "fromUnit": "m"},
    )
    assert res["problems"] == []
    assert res["summary"]["toUnit"] == "ft"
    assert res["summary"]["convertedValue"] == pytest.approx(10.0 / 0.3048, rel=0.01)


def test_settings_code_localisation_currency_format() -> None:
    res = features.run(
        "settingsCodeLocalisation.currencyFormat",
        None,
        {"symbol": "EUR ", "amount": 123456.78},
    )
    assert res["problems"] == []
    assert res["summary"]["formatted"] == "EUR 123,456.78"


def test_settings_code_localisation_decimal_symbol() -> None:
    res = features.run(
        "settingsCodeLocalisation.decimalSymbol",
        None,
        {"symbol": "comma", "sample": 42.5},
    )
    assert res["problems"] == []
    assert res["summary"]["rendered"] == "42,50"


def test_settings_code_localisation_imperial_metric() -> None:
    # 6.0 m / 0.3048 = 19.6850 ft.
    res = features.run(
        "settingsCodeLocalisation.imperialMetric",
        None,
        {"valueSi": 6.0},
    )
    assert res["problems"] == []
    assert res["summary"]["metricM"] == pytest.approx(6.0, rel=0.01)
    assert res["summary"]["imperialFt"] == pytest.approx(6.0 / 0.3048, rel=0.01)


def test_settings_code_localisation_number_format() -> None:
    # South Asian 2,2,3 grouping of 1234567.89 with 2 decimals -> "12,34,567.89".
    res = features.run(
        "settingsCodeLocalisation.numberFormat",
        None,
        {"sampleNumber": 1234567.89, "decimals": 2, "grouping": "southAsian"},
    )
    assert res["problems"] == []
    assert res["summary"]["formatted"] == "12,34,567.89"


def test_settings_code_localisation_precision_settings() -> None:
    res = features.run(
        "settingsCodeLocalisation.precisionSettings",
        None,
        {"dimDecimals": 2, "forceDecimals": 3},
    )
    assert res["problems"] == []
    assert res["summary"]["dimDecimals"] == 2
    assert res["summary"]["forceDecimals"] == 3


# ── Settings Code Values: Anchorage (settings_code_values_anchorage.py: 23) ─────────────────────


def test_settings_cv_anchorage_anchor_plate() -> None:
    # hef = 200 mm, ca1 = 150 mm, f'c = 25 MPa:
    # psi_ed = min(1.0, 0.7 + 0.3 * 150 / (1.5 * 200)) = min(1.0, 0.7 + 0.15) = 0.85.
    # Nb = 10 * sqrt(25) * 200^1.5 / 1000 = 50 * 2828.427 / 1000 = 141.421 kN.
    # Ncb = 0.85 * 141.421 = 120.208 kN.
    nb = 10.0 * math.sqrt(25.0) * (200.0**1.5) / 1000.0
    res = features.run(
        "settingsCodeValuesAnchorage.anchorPlate",
        None,
        {"embedDepthMm": 200.0, "edgeDistanceMm": 150.0, "fcMpa": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["basicBreakoutKn"] == pytest.approx(nb, rel=0.01)
    assert res["summary"]["edgeFactor"] == pytest.approx(0.85, rel=0.01)
    assert res["summary"]["breakoutCapacityKn"] == pytest.approx(0.85 * nb, rel=0.01)


def test_settings_cv_anchorage_anchorage_factor() -> None:
    res = features.run(
        "settingsCodeValuesAnchorage.anchorageFactor",
        None,
        {"bondSafety": 1.15},
    )
    assert res["problems"] == []
    assert res["summary"]["anchorageMultiplier"] == pytest.approx(1.15, rel=0.01)


def test_settings_cv_anchorage_bend_radius() -> None:
    # Stirrup 12 mm (<= 16 mm) -> mandrel diameter = 4 * 12 = 48 mm, bend radius = 24 mm.
    res = features.run(
        "settingsCodeValuesAnchorage.bendRadius",
        None,
        {"barMm": 12.0, "stirrup": True},
    )
    assert res["problems"] == []
    assert res["summary"]["mandrelDiameterMm"] == pytest.approx(48.0, rel=0.01)
    assert res["summary"]["bendRadiusMm"] == pytest.approx(24.0, rel=0.01)


def test_settings_cv_anchorage_bond_coefficient() -> None:
    # fck = 27 MPa -> fctm = 0.30 * 27^(2/3) = 0.30 * 9 = 2.70 MPa.
    # fctd = 0.7 * 2.70 / 1.5 = 1.26 MPa.
    # Poor bond (goodBond=False -> eta1 = 0.7) -> fbd = 2.25 * 0.7 * 1.26 = 1.9845 MPa.
    res = features.run(
        "settingsCodeValuesAnchorage.bondCoefficient",
        None,
        {"fckMpa": 27.0, "goodBond": False},
    )
    assert res["problems"] == []
    assert res["summary"]["fctmMpa"] == pytest.approx(2.7, rel=0.01)
    assert res["summary"]["fctdMpa"] == pytest.approx(1.26, rel=0.01)
    assert res["summary"]["fbdMpa"] == pytest.approx(1.9845, rel=0.01)


def test_settings_cv_anchorage_cast_in_anchor() -> None:
    # Default pack anchors.spacing: untorquedCastIn = 4.0 * d, edgeTorquedCastIn = 6.0 * d.
    # For boltDiaMm = 24 mm, embedMm = 240 mm: minSpacing = 96 mm, minEdge = 144 mm, hef/d = 10.
    res = features.run(
        "settingsCodeValuesAnchorage.castInAnchor",
        None,
        {"boltDiaMm": 24.0, "embedMm": 240.0},
    )
    assert res["problems"] == []
    assert res["summary"]["minSpacingMm"] == pytest.approx(96.0, rel=0.01)
    assert res["summary"]["minEdgeMm"] == pytest.approx(144.0, rel=0.01)
    assert res["summary"]["hefOverD"] == pytest.approx(10.0, rel=0.01)


def test_settings_cv_anchorage_compression_anchorage() -> None:
    # db = 20 mm, f'c = 25 MPa, fy = 400 MPa:
    # term1 = 0.24 * 400 / sqrt(25) * 20 = 19.2 * 20 = 384.0 mm;
    # term2 = 0.043 * 400 * 20 = 344.0 mm -> ldc = max(200, 384, 344) = 384.0 mm (19.2 db).
    res = features.run(
        "settingsCodeValuesAnchorage.compressionAnchorage",
        None,
        {"barMm": 20.0, "fcMpa": 25.0, "fyMpa": 400.0},
    )
    assert res["problems"] == []
    assert res["summary"]["compressionDevelopmentMm"] == pytest.approx(384.0, rel=0.01)
    assert res["summary"]["multipleDb"] == pytest.approx(19.2, rel=0.01)


def test_settings_cv_anchorage_contact_lap() -> None:
    # lap = 600 mm -> max gap = min(0.2 * 600, 150) = 120.0 mm; gap 100 <= 120 -> True.
    res = features.run(
        "settingsCodeValuesAnchorage.contactLap",
        None,
        {"lapLengthMm": 600.0, "clearGapMm": 100.0},
    )
    assert res["problems"] == []
    assert res["summary"]["maxAllowedGapMm"] == pytest.approx(120.0, rel=0.01)
    assert res["summary"]["compliant"] is True


def test_settings_cv_anchorage_coupler_type() -> None:
    # Type 1, db = 20 mm (A = pi*10^2 = 314.159 mm2), fy = 400 MPa, fu = 550 MPa:
    # req_stress = 1.25 * 400 = 500 MPa; force = 314.159 * 500 / 1000 = 157.080 kN.
    res = features.run(
        "settingsCodeValuesAnchorage.couplerType",
        None,
        {"type": "type1", "barMm": 20.0, "fyMpa": 400.0, "fuMpa": 550.0},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredStressMpa"] == pytest.approx(500.0, rel=0.01)
    assert res["summary"]["requiredForceKn"] == pytest.approx(math.pi * 100.0 * 0.5, rel=0.01)


def test_settings_cv_anchorage_development_length() -> None:
    # Default pack uses simplified ACI formula: ld = (fy * psi_t * psi_s / (1.1 * sqrt(fc))) * db * 0.5.
    # For db = 25 mm (> 19 -> psi_s=1.0), topBar=False (psi_t=1.0), fc = 30 MPa, fy = 420 MPa:
    # ld = (420 / (1.1 * sqrt(30))) * 25 * 0.5 = 871.377 mm.
    expected_ld = (420.0 / (1.1 * math.sqrt(30.0))) * 25.0 * 0.5
    res = features.run(
        "settingsCodeValuesAnchorage.developmentLength",
        None,
        {"barMm": 25.0, "fcMpa": 30.0, "fyMpa": 420.0, "topBar": False},
    )
    assert res["problems"] == []
    assert res["summary"]["developmentLengthMm"] == pytest.approx(expected_ld, rel=0.01)
    assert res["summary"]["multipleDb"] == pytest.approx(expected_ld / 25.0, rel=0.01)


def test_settings_cv_anchorage_embed_depth() -> None:
    # Nu = 70 kN, phi = 0.70, f'c = 25 MPa -> N_req = 100 kN = 100,000 N.
    # hef = (100000 / (10 * sqrt(25)))^(2/3) = (2000)^(2/3) = 158.740 mm -> rounded up to 10 mm = 160 mm.
    expected_hef = (100000.0 / 50.0) ** (2.0 / 3.0)
    res = features.run(
        "settingsCodeValuesAnchorage.embedDepth",
        None,
        {"tensileDemandKn": 70.0, "fcMpa": 25.0, "phiFactor": 0.7},
    )
    assert res["problems"] == []
    assert res["summary"]["exactHefMm"] == pytest.approx(expected_hef, rel=0.01)
    assert res["summary"]["roundedHefMm"] == pytest.approx(160.0, rel=0.01)


def test_settings_cv_anchorage_epoxy_coating() -> None:
    # db = 20 mm, cover = 50 mm (< 3*20 = 60 mm) -> splittingSensitive True -> psi_e = 1.5.
    res = features.run(
        "settingsCodeValuesAnchorage.epoxyCoating",
        None,
        {"coverMm": 50.0, "clearSpacingMm": 140.0, "barMm": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["psiEpoxy"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["splittingSensitive"] is True


def test_settings_cv_anchorage_headed_bars() -> None:
    # db = 20 mm (Ab = 100*pi), head D = 60 mm (Ahead = 900*pi) -> Abrg/Ab = 8.0 >= 4.0.
    # f'c = 25 MPa, fy = 400 MPa -> ldt = max(150, 8*20, 0.19*400/sqrt(25)*20) = max(150, 160, 304) = 304 mm.
    res = features.run(
        "settingsCodeValuesAnchorage.headedBars",
        None,
        {"barMm": 20.0, "headOuterDiaMm": 60.0, "fcMpa": 25.0, "fyMpa": 400.0},
    )
    assert res["problems"] == []
    assert res["summary"]["netBearingRatio"] == pytest.approx(8.0, rel=0.01)
    assert res["summary"]["meets4AbRequirement"] is True
    assert res["summary"]["headedDevelopmentMm"] == pytest.approx(304.0, rel=0.01)


def test_settings_cv_anchorage_hook_extension() -> None:
    # db = 20 mm -> 90 deg ext = 12*20 = 240 mm, 135 deg ext = max(75, 6*20) = 120 mm.
    res = features.run(
        "settingsCodeValuesAnchorage.hookExtension",
        None,
        {"barMm": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["ext90Mm"] == pytest.approx(240.0, rel=0.01)
    assert res["summary"]["ext135Mm"] == pytest.approx(120.0, rel=0.01)


def test_settings_cv_anchorage_hook_geometry() -> None:
    # db = 12 mm (<= 25 -> bend_d = 6*12 = 72 mm), 135 deg -> tail = max(75, 6*12) = 75 mm.
    res = features.run(
        "settingsCodeValuesAnchorage.hookGeometry",
        None,
        {"barMm": 12.0, "angleDeg": "135"},
    )
    assert res["problems"] == []
    assert res["summary"]["angleDeg"] == 135
    assert res["summary"]["insideBendDiaMm"] == pytest.approx(72.0, rel=0.01)
    assert res["summary"]["tailExtensionMm"] == pytest.approx(75.0, rel=0.01)


def test_settings_cv_anchorage_lap_length() -> None:
    # Class B -> 1.3 * 800 = 1040 mm.
    res = features.run(
        "settingsCodeValuesAnchorage.lapLength",
        None,
        {"ldMm": 800.0, "lapClass": "classB"},
    )
    assert res["problems"] == []
    assert res["summary"]["multiplier"] == pytest.approx(1.3, rel=0.01)
    assert res["summary"]["lapLengthMm"] == pytest.approx(1040.0, rel=0.01)


def test_settings_cv_anchorage_modify_factor() -> None:
    # psiTop = 1.3, psiEpoxy = 1.5 -> product = 1.95 capped at 1.7;
    # net = 1.7 * 0.8 * 0.85 = 1.156.
    res = features.run(
        "settingsCodeValuesAnchorage.modifyFactor",
        None,
        {"psiTop": 1.3, "psiEpoxy": 1.5, "psiSize": 0.8, "excessSteelRatio": 0.85},
    )
    assert res["problems"] == []
    assert res["summary"]["cappedTopEpoxy"] == pytest.approx(1.7, rel=0.01)
    assert res["summary"]["netMultiplier"] == pytest.approx(1.156, rel=0.01)


def test_settings_cv_anchorage_modify_hooks() -> None:
    res = features.run(
        "settingsCodeValuesAnchorage.modifyHooks",
        None,
        {"main90MultipleDb": 14.0, "seismic135MultipleDb": 8.0},
    )
    assert res["problems"] == []
    assert res["summary"]["main90Db"] == pytest.approx(14.0, rel=0.01)
    assert res["summary"]["seismic135Db"] == pytest.approx(8.0, rel=0.01)


def test_settings_cv_anchorage_modify_laps() -> None:
    res = features.run(
        "settingsCodeValuesAnchorage.modifyLaps",
        None,
        {"lapFactor": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["lapFactor"] == pytest.approx(1.5, rel=0.01)


def test_settings_cv_anchorage_post_installed() -> None:
    # da = 20 mm, hef = 200 mm, tau = 8.0 MPa -> Na0 = pi * 20 * 200 * 8.0 / 1000 = 32*pi = 100.531 kN.
    # minSpacing = 4 * 20 = 80 mm.
    res = features.run(
        "settingsCodeValuesAnchorage.postInstalled",
        None,
        {"anchorDiaMm": 20.0, "embedMm": 200.0, "bondMpa": 8.0},
    )
    assert res["problems"] == []
    assert res["summary"]["nominalBondPulloutKn"] == pytest.approx(32.0 * math.pi, rel=0.01)
    assert res["summary"]["minSpacingMm"] == pytest.approx(80.0, rel=0.01)


def test_settings_cv_anchorage_sleeve_length() -> None:
    # grout = 64 MPa -> f_bond = 1.4 * 8 = 11.2 MPa; db = 25 mm, fy = 500 MPa:
    # l_end = (1.25 * 500 * 25) / (4 * 11.2) = 15625 / 44.8 = 348.772 mm;
    # total sleeve = 2 * 348.772 + 20 = 717.545 mm.
    f_bond = 1.4 * 8.0
    l_end = (1.25 * 500.0 * 25.0) / (4.0 * f_bond)
    res = features.run(
        "settingsCodeValuesAnchorage.sleeveLength",
        None,
        {"barMm": 25.0, "groutStrengthMpa": 64.0, "fyMpa": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["groutBondMpa"] == pytest.approx(f_bond, rel=0.01)
    assert res["summary"]["embedmentPerBarMm"] == pytest.approx(l_end, rel=0.01)
    assert res["summary"]["totalSleeveMm"] == pytest.approx(2.0 * l_end + 20.0, rel=0.01)


def test_settings_cv_anchorage_stagger_laps() -> None:
    # l0 = 1000 mm -> stagger = 1.3 * 1000 = 1300 mm; 30% spliced (<= 33%) -> alpha6 = 1.15.
    res = features.run(
        "settingsCodeValuesAnchorage.staggerLaps",
        None,
        {"lapLengthMm": 1000.0, "pctSpliced": 30.0},
    )
    assert res["problems"] == []
    assert res["summary"]["minStaggerMm"] == pytest.approx(1300.0, rel=0.01)
    assert res["summary"]["lapProportionFactor"] == pytest.approx(1.15, rel=0.01)


def test_settings_cv_anchorage_tension_anchorage() -> None:
    # db = 20 mm, fc = 25 MPa, fy = 440 MPa:
    # straight = max(300, 440 / (1.1 * 5) * 20 * 0.5) = 80 * 10 = 800.0 mm.
    # hook = max(150, 8*20, 0.24 * 440 / 5 * 20) = max(150, 160, 422.4) = 422.4 mm.
    res = features.run(
        "settingsCodeValuesAnchorage.tensionAnchorage",
        None,
        {"barMm": 20.0, "fcMpa": 25.0, "fyMpa": 440.0},
    )
    assert res["problems"] == []
    assert res["summary"]["straightMm"] == pytest.approx(800.0, rel=0.01)
    assert res["summary"]["hookMm"] == pytest.approx(422.4, rel=0.01)


def test_settings_cv_anchorage_threaded_anchorage() -> None:
    # db = 20 mm -> Ag = 100*pi = 314.159 mm2; Anet = 0.80 * Ag = 251.327 mm2;
    # design cap at fu = 500 MPa: 0.75 * 251.327 * 500 / 1000 = 94.248 kN.
    ag = math.pi * 100.0
    anet = 0.8 * ag
    res = features.run(
        "settingsCodeValuesAnchorage.threadedAnchorage",
        None,
        {"barMm": 20.0, "netThreadAreaRatio": 0.8, "fuMpa": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["grossAreaMm2"] == pytest.approx(ag, rel=0.01)
    assert res["summary"]["netThreadAreaMm2"] == pytest.approx(anet, rel=0.01)
    assert res["summary"]["designThreadCapacityKn"] == pytest.approx(0.75 * anet * 0.5, rel=0.01)


# ── Settings Code Values: Detailing (settings_code_values_detailing.py: 19) ─────────────────────


def test_settings_cv_detailing_apply_cover() -> None:
    res = features.run(
        "settingsCodeValuesDetailing.applyCover",
        None,
        {"beamCoverMm": 45.0, "slabCoverMm": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["beamCoverMm"] == pytest.approx(45.0, rel=0.01)
    assert res["summary"]["slabCoverMm"] == pytest.approx(25.0, rel=0.01)


def test_settings_cv_detailing_apply_spacing() -> None:
    res = features.run(
        "settingsCodeValuesDetailing.applySpacing",
        None,
        {"minSlabSpacingMm": 125.0, "minStirrupSpacingMm": 100.0},
    )
    assert res["problems"] == []
    assert res["summary"]["minSlabSpacingMm"] == pytest.approx(125.0, rel=0.01)
    assert res["summary"]["minStirrupSpacingMm"] == pytest.approx(100.0, rel=0.01)


def test_settings_cv_detailing_bar_grouping() -> None:
    # bw = 400 mm, cover = 40 mm, stirrup = 10 mm -> avail = 400 - 2*50 = 300 mm.
    # bar = 20 mm -> s_min = max(25, 20) = 25 mm -> n_max = (300 + 25) // (20 + 25) = 325 // 45 = 7.
    res = features.run(
        "settingsCodeValuesDetailing.barGrouping",
        None,
        {"beamWidthMm": 400.0, "coverMm": 40.0, "stirrupMm": 10.0, "barMm": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["availableWidthMm"] == pytest.approx(300.0, rel=0.01)
    assert res["summary"]["maxBarsPerLayer"] == 7


def test_settings_cv_detailing_bundle_clearance() -> None:
    # agg = 24 mm -> 4/3 * 24 = 32.0 mm -> 32 + 10 = 42.0 mm; eq = 36 mm -> c_min = max(36, 42) = 42 mm.
    res = features.run(
        "settingsCodeValuesDetailing.bundleClearance",
        None,
        {"aggregateMm": 24.0, "equivalentDiaMm": 36.0},
    )
    assert res["problems"] == []
    assert res["summary"]["aggregateClearMm"] == pytest.approx(32.0, rel=0.01)
    assert res["summary"]["recommendedCoverMm"] == pytest.approx(42.0, rel=0.01)


def test_settings_cv_detailing_bundle_limit() -> None:
    # 4 bars of 25 mm -> d_eq = 25 * sqrt(4) = 50.0 mm; max_allowed = 4 -> compliant True.
    res = features.run(
        "settingsCodeValuesDetailing.bundleLimit",
        None,
        {"barsInBundle": 4, "barMm": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["equivalentDiaMm"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["compliant"] is True


def test_settings_cv_detailing_bundle_spacing() -> None:
    # eq = 45 mm, agg = 20 mm (4/3*20 = 26.67 mm) -> max(45, 26.67, 25) = 45.0 mm.
    res = features.run(
        "settingsCodeValuesDetailing.bundleSpacing",
        None,
        {"equivalentDiaMm": 45.0, "aggregateMm": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["minBundleClearMm"] == pytest.approx(45.0, rel=0.01)


def test_settings_cv_detailing_closed_ties() -> None:
    # d = 480 mm (d/4 = 120 mm), long bar = 22 mm (6*22 = 132 mm), cap = 150 mm -> min = 120.0 mm.
    res = features.run(
        "settingsCodeValuesDetailing.closedTies",
        None,
        {"memberDepthMm": 480.0, "longBarDiaMm": 22.0},
    )
    assert res["problems"] == []
    assert res["summary"]["maxHoopSpacingMm"] == pytest.approx(120.0, rel=0.01)


def test_settings_cv_detailing_contact_splice() -> None:
    # lap = 1000 mm -> limit = min(1000/5, 150) = 150.0 mm; spacing 160 > 150 -> compliant False.
    res = features.run(
        "settingsCodeValuesDetailing.contactSplice",
        None,
        {"lapLengthMm": 1000.0, "lapMm": 1000.0, "transverseSpacingMm": 160.0},
    )
    assert res["problems"] == []
    assert res["summary"]["maxAllowedOffsetMm"] == pytest.approx(150.0, rel=0.01)
    assert res["summary"]["compliant"] is False


def test_settings_cv_detailing_corner_bend_radius() -> None:
    # dt = 12 mm -> mandrel = 48 mm, inside radius = 24 mm.
    res = features.run(
        "settingsCodeValuesDetailing.cornerBendRadius",
        None,
        {"tieDiaMm": 12.0},
    )
    assert res["problems"] == []
    assert res["summary"]["mandrelDiaMm"] == pytest.approx(48.0, rel=0.01)
    assert res["summary"]["insideRadiusMm"] == pytest.approx(24.0, rel=0.01)


def test_settings_cv_detailing_cover_exposure() -> None:
    # Default pack concreteMethods.cover for XC4: cmin,dur = 30 mm + 10 mm dev = 40.0 mm.
    res = features.run(
        "settingsCodeValuesDetailing.coverExposure",
        None,
        {"exposure": "XC4", "fckMpa": 35.0},
    )
    assert res["problems"] == []
    assert res["summary"]["nominalCoverMm"] == pytest.approx(40.0, rel=0.01)


def test_settings_cv_detailing_cover_tolerance() -> None:
    # cnom = 35 + 10 = 45.0 mm.
    res = features.run(
        "settingsCodeValuesDetailing.coverTolerance",
        None,
        {"cminMm": 35.0, "deltaDevMm": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["nominalCoverMm"] == pytest.approx(45.0, rel=0.01)


def test_settings_cv_detailing_crosstie_spacing() -> None:
    # core = 620 mm, hx_max = 300 mm -> ceil(620/300) = 3 spaces -> 4 legs, actual hx = 620/3 = 206.67 mm.
    res = features.run(
        "settingsCodeValuesDetailing.crosstieSpacing",
        None,
        {"coreWidthMm": 620.0, "hxMaxMm": 300.0},
    )
    assert res["problems"] == []
    assert res["summary"]["internalLegs"] == 4
    assert res["summary"]["actualHxMm"] == pytest.approx(620.0 / 3.0, rel=0.01)


def test_settings_cv_detailing_lap_offset() -> None:
    # bar = 25 mm, slope = 8 (>= 6 -> compliant True), crank length = 25 * 8 = 200 mm.
    res = features.run(
        "settingsCodeValuesDetailing.lapOffset",
        None,
        {"barMm": 25.0, "crankSlope": 8.0},
    )
    assert res["problems"] == []
    assert res["summary"]["transverseOffsetMm"] == pytest.approx(25.0, rel=0.01)
    assert res["summary"]["crankLengthMm"] == pytest.approx(200.0, rel=0.01)
    assert res["summary"]["slopeCompliant"] is True


def test_settings_cv_detailing_layer_spacing() -> None:
    # Default pack detailing.spacing.betweenLayers = 25 mm; agg = 24 mm -> 4/3 * 24 = 32.0 mm > 25 mm.
    res = features.run(
        "settingsCodeValuesDetailing.layerSpacing",
        None,
        {"aggregateMm": 24.0},
    )
    assert res["problems"] == []
    assert res["summary"]["verticalClearMm"] == pytest.approx(32.0, rel=0.01)


def test_settings_cv_detailing_max_spacing() -> None:
    # h = 120 mm -> primary = min(3*120, 450) = 360 mm; shrinkage = min(5*120, 450) = 450 mm.
    res = features.run(
        "settingsCodeValuesDetailing.maxSpacing",
        None,
        {"slabThicknessMm": 120.0},
    )
    assert res["problems"] == []
    assert res["summary"]["maxPrimarySpacingMm"] == pytest.approx(360.0, rel=0.01)
    assert res["summary"]["maxShrinkageSpacingMm"] == pytest.approx(450.0, rel=0.01)


def test_settings_cv_detailing_min_spacing() -> None:
    # db = 25 mm, agg = 20 mm (4/3*20 = 26.67 mm):
    # Default pack beam min = max(25, 1.0*25, 26.67) = 26.67 mm; col min = max(40, 1.5*25, 26.67) = 40.0 mm.
    res = features.run(
        "settingsCodeValuesDetailing.minSpacing",
        None,
        {"barMm": 25.0, "aggregateMm": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["beamMinClearMm"] == pytest.approx(80.0 / 3.0, rel=0.01)
    assert res["summary"]["columnMinClearMm"] == pytest.approx(40.0, rel=0.01)


def test_settings_cv_detailing_splice_location() -> None:
    # L = 9.0 m -> top middle third: 0.33*9 = 2.97 m to 0.67*9 = 6.03 m.
    res = features.run(
        "settingsCodeValuesDetailing.spliceLocation",
        None,
        {"spanM": 9.0},
    )
    assert res["problems"] == []
    assert res["summary"]["topSpliceZoneStartM"] == pytest.approx(2.97, rel=0.01)
    assert res["summary"]["topSpliceZoneEndM"] == pytest.approx(6.03, rel=0.01)


def test_settings_cv_detailing_stagger_distance() -> None:
    # lap = 1000 mm -> center offset = 1.3 * 1000 = 1300 mm, clear gap = 0.3 * 1000 = 300 mm.
    res = features.run(
        "settingsCodeValuesDetailing.staggerDistance",
        None,
        {"lapMm": 1000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["centerOffsetMm"] == pytest.approx(1300.0, rel=0.01)
    assert res["summary"]["clearEndGapMm"] == pytest.approx(300.0, rel=0.01)


def test_settings_cv_detailing_tie_leg_count() -> None:
    # b = 680 mm, cover = 40 mm -> core = 600 mm; 3 bars/face -> pitch = 600 / 2 = 300 mm (> 150 mm)
    # -> min_legs = ceil(600 / 300) + 1 = 3.
    res = features.run(
        "settingsCodeValuesDetailing.tieLegCount",
        None,
        {"sectionWidthMm": 680.0, "coverMm": 40.0, "longBarsPerFace": 3},
    )
    assert res["problems"] == []
    assert res["summary"]["barPitchMm"] == pytest.approx(300.0, rel=0.01)
    assert res["summary"]["minTieLegs"] == 3


# ── Settings Code Values: Limits (settings_code_values_limits.py: 23) ───────────────────────────


def test_settings_cv_limits_acceleration_limit() -> None:
    # Office limit = 0.005 g; M* = 20,000 kg -> W = 20000 * 9.80665 = 196133 N;
    # beta = 0.04, fn = 6.0 Hz -> ap/g = 290 * exp(-0.35 * 6.0) / (0.04 * 196133).
    expected_ap = (290.0 * math.exp(-0.35 * 6.0)) / (0.04 * 20000.0 * 9.80665)
    res = features.run(
        "settingsCodeValuesLimits.accelerationLimit",
        None,
        {"occupancy": "office", "modalMassKg": 20000.0, "dampingRatio": 0.04, "freqHz": 6.0},
    )
    assert res["problems"] == []
    assert res["summary"]["peakAccelG"] == pytest.approx(expected_ap, rel=0.01)
    assert res["summary"]["limitG"] == pytest.approx(0.005, rel=0.01)
    assert res["summary"]["passing"] is True


def test_settings_cv_limits_apply_deflection() -> None:
    res = features.run(
        "settingsCodeValuesLimits.applyDeflection",
        None,
        {"liveDivisor": 480.0, "totalDivisor": 300.0},
    )
    assert res["problems"] == []
    assert res["summary"]["liveDivisor"] == pytest.approx(480.0, rel=0.01)
    assert res["summary"]["totalDivisor"] == pytest.approx(300.0, rel=0.01)


def test_settings_cv_limits_apply_drift() -> None:
    res = features.run(
        "settingsCodeValuesLimits.applyDrift",
        None,
        {"targetRatio": 0.015},
    )
    assert res["problems"] == []
    assert res["summary"]["targetRatio"] == pytest.approx(0.015, rel=0.01)


def test_settings_cv_limits_apply_expansion() -> None:
    res = features.run(
        "settingsCodeValuesLimits.applyExpansion",
        None,
        {"maxSpacingM": 50.0, "designDeltaTC": 30.0},
    )
    assert res["problems"] == []
    assert res["summary"]["maxJointSpacingM"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["designDeltaTC"] == pytest.approx(30.0, rel=0.01)


def test_settings_cv_limits_apply_stress() -> None:
    res = features.run(
        "settingsCodeValuesLimits.applyStress",
        None,
        {"k1Concrete": 0.55, "k3Steel": 0.75},
    )
    assert res["problems"] == []
    assert res["summary"]["k1Concrete"] == pytest.approx(0.55, rel=0.01)
    assert res["summary"]["k3Steel"] == pytest.approx(0.75, rel=0.01)


def test_settings_cv_limits_apply_sway() -> None:
    res = features.run(
        "settingsCodeValuesLimits.applySway",
        None,
        {"thetaMax": 0.2, "enablePDelta": False},
    )
    assert res["problems"] == []
    assert res["summary"]["thetaMax"] == pytest.approx(0.2, rel=0.01)
    assert res["summary"]["enablePDelta"] is False


def test_settings_cv_limits_apply_vibration() -> None:
    res = features.run(
        "settingsCodeValuesLimits.applyVibration",
        None,
        {"minFreqHz": 5.0, "maxAccelPctG": 0.4},
    )
    assert res["problems"] == []
    assert res["summary"]["minFreqHz"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["maxAccelPctG"] == pytest.approx(0.4, rel=0.01)


def test_settings_cv_limits_beam_limit() -> None:
    # Default pack serviceability.deflection.uses["floor"]: live = 360, deadLive = 240.
    # Span = 7200 mm -> live limit = 7200 / 360 = 20.0 mm, total limit = 7200 / 240 = 30.0 mm.
    res = features.run(
        "settingsCodeValuesLimits.beamLimit",
        None,
        {"spanMm": 7200.0, "divisor": 0.0},
    )
    assert res["problems"] == []
    assert res["summary"]["allowableLiveMm"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["allowableTotalMm"] == pytest.approx(30.0, rel=0.01)


def test_settings_cv_limits_cantilever_limit() -> None:
    # Default pack cantileverSpan = 2.0 -> l_eff = 2 * 2400 = 4800 mm; divisor = 360 -> 13.333 mm.
    res = features.run(
        "settingsCodeValuesLimits.cantileverLimit",
        None,
        {"cantileverMm": 2400.0, "divisor": 360.0},
    )
    assert res["problems"] == []
    assert res["summary"]["effectiveSpanMultiplier"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["allowableTipMm"] == pytest.approx(4800.0 / 360.0, rel=0.01)


def test_settings_cv_limits_crack_width() -> None:
    # Default pack detailing.crackControl: coeff = 380, ref = 280, coverFactor = 2.5, cap = 300.
    # fs = 280 MPa, cover = 40 mm -> s_max = min(380*(280/280) - 2.5*40, 300*(280/280)) = 280.0 mm.
    res = features.run(
        "settingsCodeValuesLimits.crackWidth",
        None,
        {"wMaxMm": 0.3, "barSpacingMm": 200.0, "coverMm": 40.0, "steelServiceMpa": 280.0},
    )
    assert res["problems"] == []
    assert res["summary"]["maxAllowedSpacingMm"] == pytest.approx(280.0, rel=0.01)
    assert res["summary"]["passing"] is True


def test_settings_cv_limits_expansion_joint() -> None:
    # L = 100 m, maxSpacing = 45 m -> ceil(100/45) - 1 = 3 - 1 = 2 joints -> segment = 100/3 = 33.333 m.
    res = features.run(
        "settingsCodeValuesLimits.expansionJoint",
        None,
        {"buildingLengthM": 100.0, "maxJointSpacingM": 45.0, "jointWidthMm": 30.0},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredJoints"] == 2
    assert res["summary"]["segmentLengthM"] == pytest.approx(100.0 / 3.0, rel=0.01)


def test_settings_cv_limits_frequency_limit() -> None:
    # f1 = 18 / sqrt(9.0) = 6.0 Hz >= 4.5 Hz -> passing True.
    res = features.run(
        "settingsCodeValuesLimits.frequencyLimit",
        None,
        {"spanM": 8.0, "midspanDeflectionMm": 9.0, "minFreqHz": 4.5},
    )
    assert res["problems"] == []
    assert res["summary"]["estimatedFreqHz"] == pytest.approx(6.0, rel=0.01)
    assert res["summary"]["passing"] is True


def test_settings_cv_limits_p_delta_threshold() -> None:
    # theta = (10000 * 14.0) / (500 * 3500) = 140000 / 1750000 = 0.08 <= 0.10 (default pack thetaMin).
    res = features.run(
        "settingsCodeValuesLimits.pDeltaThreshold",
        None,
        {
            "storeyGravityKn": 10000.0,
            "storeyDriftMm": 14.0,
            "storeyShearKn": 500.0,
            "storeyHeightMm": 3500.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["stabilityIndexTheta"] == pytest.approx(0.08, rel=0.01)
    assert res["summary"]["pDeltaRequired"] is False


def test_settings_cv_limits_shrinkage_limit() -> None:
    # 400e-6 * 0.6 * 15000 MPa = 3.60 MPa.
    res = features.run(
        "settingsCodeValuesLimits.shrinkageLimit",
        None,
        {"ultimateShrinkageMicro": 400.0, "restraintFactor": 0.6, "concreteEcMpa": 15000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["restrainedStressMpa"] == pytest.approx(3.6, rel=0.01)


def test_settings_cv_limits_slab_limit() -> None:
    # Default pack concrete.twoWayThickness["420.0"][0] = 30.0 -> 6000 / 30 = 200.0 mm;
    # deflection L/360 = 6000 / 360 = 16.667 mm.
    res = features.run(
        "settingsCodeValuesLimits.slabLimit",
        None,
        {"spanMm": 6000.0, "condition": "twoWayFlat"},
    )
    assert res["problems"] == []
    assert res["summary"]["spanDivisor"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["minThicknessMm"] == pytest.approx(200.0, rel=0.01)
    assert res["summary"]["deflectionL360Mm"] == pytest.approx(6000.0 / 360.0, rel=0.01)


def test_settings_cv_limits_slenderness_limit() -> None:
    # Default pack concrete.slendernessLimit = 22.0.
    res = features.run(
        "settingsCodeValuesLimits.slendernessLimit",
        None,
        {"maxKlr": 120.0},
    )
    assert res["problems"] == []
    assert res["summary"]["swayThreshold"] == pytest.approx(22.0, rel=0.01)
    assert res["summary"]["upperSlendernessCap"] == pytest.approx(120.0, rel=0.01)


def test_settings_cv_limits_stability_index() -> None:
    # theta = 0.10 (> 0.05 -> swayFrame True) -> amplification = 1 / (1 - 0.10) = 1.1111.
    res = features.run(
        "settingsCodeValuesLimits.stabilityIndex",
        None,
        {"theta": 0.1},
    )
    assert res["problems"] == []
    assert res["summary"]["swayFrame"] is True
    assert res["summary"]["amplificationFactor"] == pytest.approx(1.0 / 0.9, rel=0.01)


def test_settings_cv_limits_stiffness_threshold() -> None:
    # k = 2.0 kN / 0.8 mm = 2.5 kN/mm >= 1.5 kN/mm -> adequate True.
    res = features.run(
        "settingsCodeValuesLimits.stiffnessThreshold",
        None,
        {"pointLoadKn": 2.0, "pointDeflectionMm": 0.8, "minStiffnessKnPerMm": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["stiffnessKnPerMm"] == pytest.approx(2.5, rel=0.01)
    assert res["summary"]["adequate"] is True


def test_settings_cv_limits_story_drift() -> None:
    # Default pack: seismic allowableDrift = 0.02, wind storeyDrift.shortPeriod = 0.005.
    # For h = 3500 mm: seismic = 70.0 mm, wind = 17.5 mm.
    res = features.run(
        "settingsCodeValuesLimits.storyDrift",
        None,
        {"storeyHeightMm": 3500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["seismicLimitMm"] == pytest.approx(70.0, rel=0.01)
    assert res["summary"]["windLimitMm"] == pytest.approx(17.5, rel=0.01)


def test_settings_cv_limits_stress_limit() -> None:
    # Default pack k1=0.60, k2=0.45, k3=0.80 -> f'c=30: char=18.0 MPa, quasi=13.5 MPa; fy=500: steel=400.0 MPa.
    res = features.run(
        "settingsCodeValuesLimits.stressLimit",
        None,
        {"fckMpa": 30.0, "fykMpa": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["concreteCharMpa"] == pytest.approx(18.0, rel=0.01)
    assert res["summary"]["concreteQuasiMpa"] == pytest.approx(13.5, rel=0.01)
    assert res["summary"]["steelServiceMpa"] == pytest.approx(400.0, rel=0.01)


def test_settings_cv_limits_sway_factor() -> None:
    # theta = 0.20 -> B2 = 1 / (1 - 0.20) = 1.25 <= 1.5 -> exceeds1_5 False.
    res = features.run(
        "settingsCodeValuesLimits.swayFactor",
        None,
        {"theta": 0.2},
    )
    assert res["problems"] == []
    assert res["summary"]["swayAmplificationB2"] == pytest.approx(1.25, rel=0.01)
    assert res["summary"]["exceeds1_5"] is False


def test_settings_cv_limits_thermal_strain() -> None:
    # alpha = 1.2e-5, dT = 25 C -> eps = 3.0e-4; L = 50 m -> dL = 3.0e-4 * 50000 = 15.0 mm (7.5 mm/end).
    res = features.run(
        "settingsCodeValuesLimits.thermalStrain",
        None,
        {"alphaPerC": 1.2e-5, "deltaTC": 25.0, "buildingLengthM": 50.0},
    )
    assert res["problems"] == []
    assert res["summary"]["thermalStrain"] == pytest.approx(3.0e-4, rel=0.01)
    assert res["summary"]["totalExpansionMm"] == pytest.approx(15.0, rel=0.01)
    assert res["summary"]["endMovementMm"] == pytest.approx(7.5, rel=0.01)


def test_settings_cv_limits_total_drift() -> None:
    # Default pack serviceability.sway.ratio = 0.002 (H/500). For H = 40 m = 40000 mm -> 80.0 mm.
    res = features.run(
        "settingsCodeValuesLimits.totalDrift",
        None,
        {"buildingHeightM": 40.0},
    )
    assert res["problems"] == []
    assert res["summary"]["swayRatio"] == pytest.approx(0.002, rel=0.01)
    assert res["summary"]["topSwayLimitMm"] == pytest.approx(80.0, rel=0.01)

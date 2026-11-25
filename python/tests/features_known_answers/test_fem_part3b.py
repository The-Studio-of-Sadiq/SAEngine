"""Independent known-answer tests for FEM Wind, Loads, STM Ties, Pushover Mechanism, Analyze, and STM calculators."""

from __future__ import annotations

from pathlib import Path

import pytest

from saengine import features
from saengine.design import stm_model
from saengine.library.settings import default_project_settings
from saengine.library.strut_and_tie import StrutAndTieFile


def _row_by(res: dict, key: str, value: object, table_index: int = 0) -> dict:
    for row in res["tables"][table_index]["rows"]:
        if row[key] == value:
            return row
    raise AssertionError(f"No row with {key}={value!r} in {res['tables'][table_index]['rows']}")


# ── Wind (fem_wind.py: 16) ───────────────────────────────────────────────────────────────────────


def test_fem_wind_acceleration_check() -> None:
    # Standalone defaults: H=12 m, B=18 m, D=12 m, Vb=44 m/s, Exp A (alphaBar=0.25, bBar=0.45, c=0.3, l=97.54, eps=0.3333, zmin=9.14)
    # BNBC 2020 windComfort: 10-yr return -> speed_ratio = 0.83875 -> V_10 = 44 * 0.83875 = 36.905 m/s
    # z_bar = max(0.6*12, 9.14) = 9.14 m; Iz = 0.3*(10/9.14)^(1/6) = 0.30453; Lz = 97.54*(9.14/10)^0.3333 = 94.660 m
    # Vz = 0.45*(9.14/10)^0.25 * 36.905 = 16.240 m/s; N1 = 0.4*94.660/16.240 = 2.3315
    # Rn = 7.47*2.3315 / (1 + 10.3*2.3315)^(5/3) = 0.08023; Rh = R_term(4.6*0.4*12/16.240=1.3596)=0.4847
    # RB = R_term(2.0394)=0.3712; RL = R_term(4.5517)=0.1956 -> R = sqrt(0.08023*0.4847*0.3712*(0.53+0.47*0.1956)/0.02) = 0.67016
    # Cfx = 0.8 - (-0.5) = 1.3; K = 1.65^0.25 / (0.25 + 1.0 + 1.0) = 0.50372
    # sigma = 0.85 * 1.25 * 18 * 12 * 1.3 * 16.240^2 * 0.30453 * 0.50372 * 0.67016 / 500000 = 0.016278 m/s2
    # g = sqrt(2*ln(3600*0.4)) + 0.577/sqrt(2*ln(1440)) = 3.8136 + 0.1513 = 3.9649
    # a_peak = 3.9649 * 0.016278 / 9.81 * 1000 = 6.5788 milli-g <= 15.0 (residential) -> passes True
    res = features.run(
        "femWind.accelerationCheck",
        None,
        {"frequencyHz": 0.4, "damping": 0.02, "modalMassTonnes": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["peakAccelMg"] == pytest.approx(6.5788, rel=0.01)
    assert res["summary"]["limitMg"] == pytest.approx(15.0, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_wind_along_wind_load(tmp_path: Path) -> None:
    # Eurocodes (EN 1991-1-4 peakVelocityPressure): default site vb,0=44 m/s, terrain "0" (z0=0.003, zmin=1.0), I=1.0
    # kr = 0.19*(0.003/0.05)^0.07 = 0.15602; cr(40) = 0.15602 * ln(40/0.003) = 1.4819
    # vm = 1.4819 * 44 = 65.203 m/s; Iv = 1 / ln(40/0.003) = 0.10528
    # qp(40) = (1 + 7*0.10528) * 0.5 * 1.25 * 65.203^2 / 1000 = 1.7370 * 2.6572 = 4.6154 kPa
    # H=40 m < 100 m and < 4*16 -> simplified CsCd = 1.0
    # V_est = 4.6154 * 1.0 * 1.3 * 20 * 40 * 0.75 = 3600.0 kN
    sdir = tmp_path / "02 Project Settings"
    sdir.mkdir()
    s = default_project_settings("EC", code_pack="eurocodes")
    (sdir / "project-settings.json").write_text(s.model_dump_json(by_alias=True), encoding="utf-8")
    res = features.run(
        "femWind.alongWindLoad",
        str(tmp_path),
        {"heightM": 40.0, "widthM": 20.0, "depthM": 16.0, "n1Hz": 0.8, "damping": 0.02},
    )
    assert res["problems"] == []
    assert res["summary"]["peakPressureKpa"] == pytest.approx(4.6154, rel=0.01)
    assert res["summary"]["structuralFactor"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["estimatedShearKn"] == pytest.approx(3600.0, rel=0.01)


def test_fem_wind_external_coefficients() -> None:
    # Default pack (BNBC 2020) cladding_pressures at standalone H=12 m, Exp B (alpha=9.5, zg=274.32, Kd=0.85, V=44, I=1.0):
    # Kz(12) = 2.01 * (12/274.32)^(2/9.5) = 1.0402 -> qh = 0.000613 * 1.0402 * 0.85 * 44^2 = 1.0496 kPa?
    # Wait: lowRiseWallFactor = 1.0 (not needed), wall zone 4 GCp(10 m2) = +0.736 / -0.826, GCpi = 0.18
    # Note: default site exposure is "A" (alpha=7.0, zg=365.76): Kz(12) = 2.01*(12/365.76)^(2/7) = 0.7569 -> qh = 0.7638 kPa
    # wall 4: p+ = 0.7638 * (0.7360 + 0.18) = 0.6997 kPa, p- = 0.7638 * (-0.8260 - 0.18) = -0.7684 kPa
    res = features.run(
        "femWind.externalCoefficients",
        None,
        {"tributaryAreaM2": 10.0, "parapetM": 1.2},
    )
    assert res["problems"] == []
    assert res["summary"]["qhKpa"] == pytest.approx(0.7638, rel=0.01)
    assert res["summary"]["zonesEvaluated"] == 7
    row_w4 = res["tables"][0]["rows"][0]
    assert row_w4["pPosKpa"] == pytest.approx(0.6997, rel=0.01)
    assert row_w4["pNegKpa"] == pytest.approx(-0.7684, rel=0.01)


def test_fem_wind_face_loads() -> None:
    # Area = 5 * 4 = 20 m2; F_total = 1.5 * 20 = 30.0 kN; corner = 30 / 4 = 7.5 kN
    res = features.run(
        "femWind.faceLoads",
        None,
        {"pressureKpa": 1.5, "panelWidthM": 5.0, "panelHeightM": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["panelAreaM2"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["totalForceKn"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["cornerNodeForceKn"] == pytest.approx(7.5, rel=0.01)


def test_fem_wind_frame_loads() -> None:
    # w = 1.5 * 6.0 = 9.0 kN/m
    res = features.run(
        "femWind.frameLoads",
        None,
        {"pressureKpa": 1.5, "tributaryWidthM": 6.0},
    )
    assert res["problems"] == []
    assert res["summary"]["lineLoadKnPerM"] == pytest.approx(9.0, rel=0.01)


def test_fem_wind_gust_duration() -> None:
    # V_1hr = 45.6 / 1.52 = 30.0 m/s
    # ratio(300s) = 1.52 - 0.16 * log10(300 / 3) = 1.52 - 0.16 * 2.0 = 1.20 -> V_300 = 30 * 1.20 = 36.0 m/s
    res = features.run(
        "femWind.gustDuration",
        None,
        {"speed3sMS": 45.6, "targetDurationS": 300.0},
    )
    assert res["problems"] == []
    assert res["summary"]["v1HrMS"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["vTargetMS"] == pytest.approx(36.0, rel=0.01)


def test_fem_wind_gust_factor() -> None:
    # Default pack rigid G = 0.85; n1 = 0.8 Hz < 1.0 Hz -> isFlexible True
    res = features.run(
        "femWind.gustFactor",
        None,
        {"frequencyHz": 0.8, "damping": 0.02},
    )
    assert res["problems"] == []
    assert res["summary"]["rigidGustFactor"] == pytest.approx(0.85, rel=0.01)
    assert res["summary"]["isFlexible"] is True


def test_fem_wind_internal_pressure() -> None:
    # partial -> GCpi = 0.55; pi+ = 1.5 * 0.55 = 0.825 kPa, pi- = -0.825 kPa
    res = features.run(
        "femWind.internalPressure",
        None,
        {"enclosure": "partial", "qhKpa": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["gcpi"] == pytest.approx(0.55, rel=0.01)
    assert res["summary"]["positivePressureKpa"] == pytest.approx(0.825, rel=0.01)
    assert res["summary"]["negativePressureKpa"] == pytest.approx(-0.825, rel=0.01)


def test_fem_wind_openings_pressure() -> None:
    # Ao / Aoi = 10 / 5 = 2.0 > 1.1 and Ao = 10 > 0.37 -> "Partially Enclosed", GCpi = 0.55
    res = features.run(
        "femWind.openingsPressure",
        None,
        {
            "windwardOpenAreaM2": 10.0,
            "otherOpenAreaM2": 5.0,
            "volumeM3": 1500.0,
            "gcpiEnclosed": 0.18,
            "gcpiPartial": 0.55,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["openingRatio"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["enclosure"] == "Partially Enclosed"
    assert res["summary"]["gcpiMagnitude"] == pytest.approx(0.55, rel=0.01)


def test_fem_wind_shape_factor_table() -> None:
    # D/B = 1.5 (1.0 < 1.5 <= 2.0) -> Cp_lee = -0.3; net = 0.8 - (-0.3) = 1.1
    res = features.run("femWind.shapeFactorTable", None, {"depthOverWidth": 1.5})
    assert res["problems"] == []
    assert res["summary"]["netWallCp"] == pytest.approx(1.1, rel=0.01)
    assert _row_by(res, "surface", "Leeward wall")["cp"] == pytest.approx(-0.3, rel=0.01)


def test_fem_wind_shielding_factor() -> None:
    # gap/H = 30 / 10 = 3.0 -> ks = 0.75 + 0.25 * (3 / 6) = 0.875
    res = features.run(
        "femWind.shieldingFactor",
        None,
        {"shelterGapM": 30.0, "obstructionHeightM": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["gapToHeightRatio"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["shieldingFactor"] == pytest.approx(0.875, rel=0.01)


def test_fem_wind_surface_pressure() -> None:
    # Default site Exp A (alpha=7.0, zg=365.76 m), V=44 m/s, Kd=0.85, G=0.85, I=1.0:
    # Kz(20) = 2.01 * (20/365.76)^(2/7) = 0.8761 -> qz = 0.000613 * 0.8761 * 0.85 * 44^2 = 0.8838 kPa
    # p_net = 0.8838 * 0.85 * (0.8 - (-0.5)) = 0.9766 kPa
    res = features.run(
        "femWind.surfacePressure",
        None,
        {"heightM": 20.0, "cpWindward": 0.8, "cpLeeward": -0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["qzKpa"] == pytest.approx(0.8838, rel=0.01)
    assert res["summary"]["netPressureKpa"] == pytest.approx(0.9766, rel=0.01)


def test_fem_wind_torsion_from_wind() -> None:
    # e = 20 * 0.15 = 3.0 m; Mt = 400 * 3.0 = 1200.0 kN*m
    res = features.run(
        "femWind.torsionFromWind",
        None,
        {"windShearKn": 400.0, "widthM": 20.0, "eccentricityRatio": 0.15},
    )
    assert res["problems"] == []
    assert res["summary"]["eccentricityM"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["torsionMomentKnm"] == pytest.approx(1200.0, rel=0.01)


def test_fem_wind_turbulence_intensity(tmp_path: Path) -> None:
    # IS-codes speedFactors.gustFactor (turbulence=[0.3507, 0.0535, 0.466, 0.1358], z0_1=0.002, z0_4=2.0, default exp="2" share=0.142857):
    # I1(20) = 0.3507 - 0.0535 * log10(20 / 0.002) = 0.3507 - 0.0535 * 4.0 = 0.1367
    # I4(20) = 0.466 - 0.1358 * log10(20 / 2.0) = 0.466 - 0.1358 * 1.0 = 0.3302
    # Iz(20) = 0.1367 + 0.142857 * (0.3302 - 0.1367) = 0.16434
    sdir = tmp_path / "02 Project Settings"
    sdir.mkdir()
    s = default_project_settings("IS", code_pack="is-codes")
    (sdir / "project-settings.json").write_text(s.model_dump_json(by_alias=True), encoding="utf-8")
    res = features.run("femWind.turbulenceIntensity", str(tmp_path), {"heightM": 20.0})
    assert res["problems"] == []
    assert res["summary"]["turbulenceIntensity"] == pytest.approx(0.16434, rel=0.01)


def test_fem_wind_vortex_shedding() -> None:
    # Vcr = 1.5 * 4.0 / 0.2 = 30.0 m/s <= 1.25 * 30 = 37.5 m/s -> susceptible True
    res = features.run(
        "femWind.vortexShedding",
        None,
        {"diameterOrWidthM": 4.0, "frequencyHz": 1.5, "strouhal": 0.2, "siteMeanSpeedMS": 30.0},
    )
    assert res["problems"] == []
    assert res["summary"]["criticalVelocityMS"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["susceptible"] is True


def test_fem_wind_wind_profile() -> None:
    # Default site Exp A (alpha=7.0, zg=365.76 m), V=44 m/s, Kd=0.85, I=1.0:
    # At z = 25 m: Kz = 2.01 * (25/365.76)^(2/7) = 0.9337 -> qz = 0.000613 * 0.9337 * 0.85 * 44^2 = 0.9420 kPa
    res = features.run("femWind.windProfile", None, {"heightM": 25.0})
    assert res["problems"] == []
    assert res["summary"]["roofPressureKpa"] == pytest.approx(0.9420, rel=0.01)
    assert _row_by(res, "heightM", 25.0)["kz"] == pytest.approx(0.9337, rel=0.01)


# ── FEM Loads (fem_loads.py: 13) ─────────────────────────────────────────────────────────────────


def test_fem_loads_area_loads() -> None:
    # lx=4 m, ly=8 m, q=6 kPa -> Area = 32 m2, Total = 192 kN
    # Short edge UDL eq = 6 * 4 / 3 = 8.0 kN/m
    # Long edge UDL eq = (6 * 4 / 6) * (3 - (4/8)^2) = 4 * 2.75 = 11.0 kN/m
    res = features.run("femLoads.areaLoads", None, {"lxM": 4.0, "lyM": 8.0, "pressureKpa": 6.0})
    assert res["problems"] == []
    assert res["summary"]["areaM2"] == pytest.approx(32.0, rel=0.01)
    assert res["summary"]["totalLoadKn"] == pytest.approx(192.0, rel=0.01)
    assert res["summary"]["longEdgeEquivKnPerM"] == pytest.approx(11.0, rel=0.01)
    assert res["summary"]["shortEdgeEquivKnPerM"] == pytest.approx(8.0, rel=0.01)


def test_fem_loads_influence_lines() -> None:
    # L=12 m, x/L = 0.25 -> x = 3.0 m -> peak M ordinate = 3.0 * 0.75 = 2.25 m
    res = features.run("femLoads.influenceLines", None, {"spanM": 12.0, "sectionRatio": 0.25})
    assert res["problems"] == []
    assert res["summary"]["sectionXM"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["peakMomentOrdinateM"] == pytest.approx(2.25, rel=0.01)


def test_fem_loads_line_loads() -> None:
    # L=6 m, w1=10, w2=20 -> Total = 0.5*(10+20)*6 = 90.0 kN
    # FEM_i = 36*(30 + 40)/60 = 42.0 kN*m; FEM_j = 36*(20 + 60)/60 = 48.0 kN*m
    res = features.run(
        "femLoads.lineLoads",
        None,
        {"spanM": 6.0, "wStartKnPerM": 10.0, "wEndKnPerM": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalForceKn"] == pytest.approx(90.0, rel=0.01)
    assert res["summary"]["femIKnm"] == pytest.approx(42.0, rel=0.01)
    assert res["summary"]["femJKnm"] == pytest.approx(48.0, rel=0.01)


def test_fem_loads_live_load_reduction() -> None:
    # KLL * AT = 4 * 50 = 200.0 m2 -> R = 0.25 + 4.57 / sqrt(200) = 0.25 + 0.32315 = 0.57315 >= 0.40
    # L = 5.0 * 0.57315 = 2.8657 kPa
    res = features.run(
        "femLoads.liveLoadReduction",
        None,
        {"unreducedLiveKpa": 5.0, "tributaryAreaM2": 50.0, "kll": 4.0, "isFloorBeam": False},
    )
    assert res["problems"] == []
    assert res["summary"]["influenceAreaM2"] == pytest.approx(200.0, rel=0.01)
    assert res["summary"]["reductionFactor"] == pytest.approx(0.57315, rel=0.01)
    assert res["summary"]["reducedLiveKpa"] == pytest.approx(2.8657, rel=0.01)


def test_fem_loads_moving_loads() -> None:
    # 2 equal 80 kN wheels spaced b=2.0 m on L=10.0 m simple span:
    # M_max = (W / (2L)) * (L - b/2)^2 = (80 / 20) * (10 - 1)^2 = 4 * 81 = 324.0 kN*m
    # V_max = 80 * (1 + 8/10) = 144.0 kN; R_max = 144.0 kN
    res = features.run(
        "femLoads.movingLoads",
        None,
        {"spanM": 10.0, "wheelLoadKn": 80.0, "wheelBaseM": 2.0, "wheels": 2},
    )
    assert res["problems"] == []
    assert res["summary"]["maxMomentKnm"] == pytest.approx(324.0, rel=0.01)
    assert res["summary"]["maxShearKn"] == pytest.approx(144.0, rel=0.01)
    assert res["summary"]["maxReactionKn"] == pytest.approx(144.0, rel=0.01)


def test_fem_loads_notional_loads(tmp_path: Path) -> None:
    # Default pack BNBC 2020 directAnalysis (additive tau=1): 0.002 + 0.001 = 0.003 -> 0.003 * 4000 = 12.0 kN
    res = features.run(
        "femLoads.notionalLoads",
        None,
        {"method": "directAnalysis", "gravityLoadKn": 4000.0, "heightM": 16.0},
    )
    assert res["problems"] == []
    assert res["summary"]["coefficient"] == pytest.approx(0.003, rel=0.01)
    assert res["summary"]["notionalForceKn"] == pytest.approx(12.0, rel=0.01)

    # Eurocodes sway imperfection: phi = phi0 * alpha_h = (1/200) * (2/sqrt(16)) = 0.005 * (2/3? capped [2/3, 1.0]):
    # alpha_h = 2/sqrt(16) = 0.5 -> clamped to min 2/3 = 0.6667 -> phi = 0.005 * 0.6667 = 0.003333 -> 13.333 kN
    sdir = tmp_path / "02 Project Settings"
    sdir.mkdir()
    s = default_project_settings("EC", code_pack="eurocodes")
    (sdir / "project-settings.json").write_text(s.model_dump_json(by_alias=True), encoding="utf-8")
    res_sway = features.run(
        "femLoads.notionalLoads",
        str(tmp_path),
        {"method": "sway", "gravityLoadKn": 4000.0, "heightM": 16.0},
    )
    assert res_sway["problems"] == []
    assert res_sway["summary"]["coefficient"] == pytest.approx(0.003333, rel=0.01)
    assert res_sway["summary"]["notionalForceKn"] == pytest.approx(13.3333, rel=0.01)


def test_fem_loads_point_loads() -> None:
    # L=10, P=100, a=4, b=6 -> M_simple = 100*4*6/10 = 240.0 kN*m
    # FEM_i = 100*4*36/100 = 144.0 kN*m; FEM_j = 100*16*6/100 = 96.0 kN*m
    res = features.run(
        "femLoads.pointLoads",
        None,
        {"spanM": 10.0, "loadKn": 100.0, "offsetRatio": 0.4},
    )
    assert res["problems"] == []
    assert res["summary"]["simpleMomentKnm"] == pytest.approx(240.0, rel=0.01)
    assert res["summary"]["femIKnm"] == pytest.approx(144.0, rel=0.01)
    assert res["summary"]["femJKnm"] == pytest.approx(96.0, rel=0.01)


def test_fem_loads_seismic_static_loads() -> None:
    # Default pack (BNBC 2020), rcSmf (Ct=0.0466, m=0.9, R=8.0), Dhaka Z=0.18, SD (S=1.35, TB=0.2, TC=0.8), I=1.0:
    # Ta = 0.0466 * 16^0.9 = 0.5651 s -> Cs_norm = 2.5 * 1.35 = 3.375
    # Cs = (2/3) * (0.18 * 1.0 / 8.0) * 3.375 = 0.050625 -> V = 0.050625 * 10000 = 506.25 kN
    # k = 1.0 + 0.5 * (0.5651 - 0.5) = 1.03255
    res = features.run(
        "femLoads.seismicStaticLoads",
        None,
        {"weightKn": 10000.0, "heightM": 16.0, "storeys": 4},
    )
    assert res["problems"] == []
    assert res["summary"]["periodS"] == pytest.approx(0.5651, rel=0.01)
    assert res["summary"]["cs"] == pytest.approx(0.050625, rel=0.01)
    assert res["summary"]["baseShearKn"] == pytest.approx(506.25, rel=0.01)
    assert res["summary"]["exponentK"] == pytest.approx(1.03255, rel=0.01)


def test_fem_loads_self_weight() -> None:
    # Standalone fallback: 0.3 * 0.5 m2 * 25 kN/m3 * 1.2 = 4.5 kN/m; * 6.0 m = 27.0 kN
    res = features.run(
        "femLoads.selfWeight",
        None,
        {"deadMultiplier": 1.2, "concreteDensityKnM3": 25.0, "steelDensityKnM3": 78.5},
    )
    assert res["problems"] == []
    assert res["summary"]["estimatedSelfWeightKn"] == pytest.approx(27.0, rel=0.01)


def test_fem_loads_snow_load_case() -> None:
    # angle = 45 deg > 30 -> mu1 = 0.8 * (60 - 45) / 30 = 0.4
    # pf = 0.4 * 1.1 * 1.0 * 1.5 = 0.66 kPa
    res = features.run(
        "femLoads.snowLoadCase",
        None,
        {
            "groundSnowKpa": 1.5,
            "exposureFactorCe": 1.1,
            "thermalFactorCt": 1.0,
            "roofAngleDeg": 45.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["shapeCoeff"] == pytest.approx(0.4, rel=0.01)
    assert res["summary"]["roofSnowKpa"] == pytest.approx(0.66, rel=0.01)


def test_fem_loads_storey_load_assign() -> None:
    # Standalone fallback floor: 18 x 12 = 216 m2; SD = 216*2 = 432 kN; Live = 216*3 = 648 kN
    res = features.run("femLoads.storeyLoadAssign", None, {"sdKpa": 2.0, "liveKpa": 3.0})
    assert res["problems"] == []
    assert res["summary"]["floorAreaM2"] == pytest.approx(216.0, rel=0.01)
    assert res["summary"]["totalSdKn"] == pytest.approx(432.0, rel=0.01)
    assert res["summary"]["totalLiveKn"] == pytest.approx(648.0, rel=0.01)


def test_fem_loads_temperature_loads() -> None:
    # E=25e9 Pa, t=0.2 m, nu=0.2, alpha=1e-5 /C, dT=25 C, dTg=10 C:
    # NT = (25e9 * 0.2 * 1e-5 * 25 / 0.8) / 1000 = 1562.5 kN/m
    # MT = (25e9 * 0.04 * 1e-5 * 10 / (12 * 0.8)) / 1000 = 10.4167 kN*m/m
    res = features.run(
        "femLoads.temperatureLoads",
        None,
        {
            "uniformDeltaC": 25.0,
            "gradientC": 10.0,
            "thicknessMm": 200.0,
            "eMpa": 25000.0,
            "alphaPerC": 1e-5,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["axialResultantKnPerM"] == pytest.approx(1562.5, rel=0.01)
    assert res["summary"]["momentResultantKnmPerM"] == pytest.approx(10.4167, rel=0.01)


def test_fem_loads_wind_pressure_loads() -> None:
    # Default site Exp A (alpha=7.0, zg=365.76), V=44 m/s, Kd=0.85, G=0.85, I=1.0:
    # Kz(20) = 2.01 * (20/365.76)^(2/7) = 0.8761 -> qz = 0.000613 * 0.8761 * 0.85 * 44^2 = 0.8838 kPa
    res = features.run(
        "femLoads.windPressureLoads",
        None,
        {"heightM": 20.0, "widthM": 24.0, "depthM": 12.0},
    )
    assert res["problems"] == []
    assert res["summary"]["qzRoofKpa"] == pytest.approx(0.8838, rel=0.01)
    assert res["summary"]["gustFactor"] == pytest.approx(0.85, rel=0.01)


# ── STM Ties (fem_stm_ties.py: 13) ───────────────────────────────────────────────────────────────


def _write_sized_deep_beam(
    root: Path, width: float = 250.0, bar_area: float = 2000.0, bar_dia: float = 20.0
) -> None:
    model = stm_model.template("deepBeam", {})
    sized = model.model_copy(
        update={
            "members": [
                m.model_copy(update={"width": width, "barArea": bar_area, "barDiameter": bar_dia})
                if m.id == "T1"
                else m
                for m in model.members
            ]
        }
    )
    fem_dir = root / "08 FEM"
    fem_dir.mkdir(exist_ok=True)
    (fem_dir / "strut-and-tie.json").write_text(
        StrutAndTieFile(models=[sized]).model_dump_json(by_alias=True), encoding="utf-8"
    )


def _write_eurocodes_settings(root: Path) -> None:
    sdir = root / "02 Project Settings"
    sdir.mkdir(exist_ok=True)
    s = default_project_settings("EC", code_pack="eurocodes")
    (sdir / "project-settings.json").write_text(s.model_dump_json(by_alias=True), encoding="utf-8")


def test_fem_stm_ties_bar_bundle(tmp_path: Path) -> None:
    # barArea=2000, dia=20 -> single = pi*100 = 314.159 mm2 -> totalBars = ceil(2000/314.159) = 7
    # 3 bars/bundle -> bundleCount = ceil(7/3) = 3; bundleArea = 3 * 314.159 = 942.4778 mm2; residual = 1
    _write_sized_deep_beam(tmp_path)
    res = features.run("femStmTies.barBundle", str(tmp_path), {"tieId": "T1", "barsPerBundle": 3})
    assert res["problems"] == []
    assert res["summary"]["totalBars"] == 7
    assert res["summary"]["bundleCount"] == 3
    assert res["summary"]["bundleAreaMm2"] == pytest.approx(942.4778, rel=0.01)
    assert res["summary"]["residualBars"] == 1


def test_fem_stm_ties_bend_radius(tmp_path: Path) -> None:
    # Eurocodes anchorage (fc=28, bar=20, sigma_sd=400, cd=50, bent=True):
    # fctd(28) = 1.2909 MPa -> fbd = 2.25 * 1.2909 = 2.9046 MPa
    # lb,rqd = (20/4) * (400 / 2.9046) = 688.57 mm
    # cd = 50 <= 3*20 = 60 -> alpha1 = 1.0 -> lbd = 688.57 mm; ratio = 100 / 20 = 5.0
    _write_eurocodes_settings(tmp_path)
    res = features.run(
        "femStmTies.bendRadius",
        str(tmp_path),
        {"barDiameterMm": 20, "barStressMpa": 400, "bendCoverMm": 50, "innerBendDiameterMm": 100},
    )
    assert res["problems"] == []
    assert res["summary"]["bendDiameterRatio"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["straightBasicLengthMm"] == pytest.approx(688.57, rel=0.01)
    assert res["summary"]["bentAnchorageLengthMm"] == pytest.approx(688.57, rel=0.01)


def test_fem_stm_ties_crack_width(tmp_path: Path) -> None:
    # deepBeam T1 tension = 500 * (1500/1350) = 555.5556 kN; barArea = 2000 mm2
    # sigma_s = 555555.6 * 0.65 / 2000 = 180.5556 MPa
    # eps = 180.5556 / 200000 = 0.0009028; w = 0.0009028 * 120 = 0.1083 mm
    _write_sized_deep_beam(tmp_path)
    res = features.run(
        "femStmTies.crackWidth",
        str(tmp_path),
        {"tieId": "T1", "serviceFactor": 0.65, "barSpacingMm": 120},
    )
    assert res["problems"] == []
    assert res["summary"]["serviceStressMpa"] == pytest.approx(180.556, rel=0.01)
    assert res["summary"]["estimatedCrackWidthMm"] == pytest.approx(0.1083, rel=0.01)


def test_fem_stm_ties_curtailment_point(tmp_path: Path) -> None:
    # Eurocodes (fc=28, fy=420, bar=20): fyd = 420/1.15 = 365.217 MPa, fbd = 2.9046 MPa
    # lbd = (20/4)*(365.217/2.9046) = 628.69 mm; deepBeam T1 length = 3000 mm
    # remaining = 3000 - 2*628.69 = 1742.61 mm > 0 -> True
    _write_eurocodes_settings(tmp_path)
    res = features.run(
        "femStmTies.curtailmentPoint",
        str(tmp_path),
        {"tieId": "T1", "barDiameterMm": 20},
    )
    assert res["problems"] == []
    assert res["summary"]["tieLengthMm"] == pytest.approx(3000.0, rel=0.01)
    assert res["summary"]["developmentEachEndMm"] == pytest.approx(628.69, rel=0.01)
    assert res["summary"]["availableBetweenAnchorageZonesMm"] == pytest.approx(1742.61, rel=0.01)
    assert res["summary"]["curtailmentPermittedByGeometry"] is True


def test_fem_stm_ties_development_length(tmp_path: Path) -> None:
    # Eurocodes (fc=28, bar=20, sigma_sd=400, cd=None):
    # lb,rqd = 688.57 mm; lb,min = max(0.3*688.57, 10*20, 100) = 206.57 mm; lbd = 688.57 mm
    _write_eurocodes_settings(tmp_path)
    res = features.run(
        "femStmTies.developmentLength",
        str(tmp_path),
        {"tieId": "T1", "barDiameterMm": 20, "barStressMpa": 400},
    )
    assert res["problems"] == []
    assert res["summary"]["basicLengthMm"] == pytest.approx(688.57, rel=0.01)
    assert res["summary"]["minimumLengthMm"] == pytest.approx(206.57, rel=0.01)
    assert res["summary"]["requiredLengthMm"] == pytest.approx(688.57, rel=0.01)


def test_fem_stm_ties_effective_tension(tmp_path: Path) -> None:
    # T1 force = 555.556 kN -> service = 555.556 * 0.65 = 361.111 kN
    # stress = 361111 / 2000 = 180.556 MPa; ratio = 180.556 / 420 = 0.4299
    _write_sized_deep_beam(tmp_path)
    res = features.run(
        "femStmTies.effectiveTension",
        str(tmp_path),
        {"tieId": "T1", "serviceFactor": 0.65},
    )
    assert res["problems"] == []
    assert res["summary"]["effectiveTensionKn"] == pytest.approx(361.111, rel=0.01)
    assert res["summary"]["steelStressMpa"] == pytest.approx(180.556, rel=0.01)
    assert res["summary"]["stressRatio"] == pytest.approx(0.4299, rel=0.01)


def test_fem_stm_ties_layer_distribution(tmp_path: Path) -> None:
    # 2000 mm2 across 2 layers * 2 bars = 4 bars -> 500 mm2/bar, 1000 mm2/layer, eq dia = sqrt(2000/pi) = 25.2313 mm
    _write_sized_deep_beam(tmp_path)
    res = features.run(
        "femStmTies.layerDistribution",
        str(tmp_path),
        {"tieId": "T1", "layers": 2, "barsPerLayer": 2},
    )
    assert res["problems"] == []
    assert res["summary"]["areaPerBarMm2"] == pytest.approx(500.0, rel=0.01)
    assert res["summary"]["equivalentDiameterMm"] == pytest.approx(25.2313, rel=0.01)
    assert res["summary"]["steelPerLayerMm2"] == pytest.approx(1000.0, rel=0.01)


def test_fem_stm_ties_spacing_check() -> None:
    # clear = (260 - 5 * 20) / (5 - 1) = 160 / 4 = 40.0 mm >= 30.0 -> passes True
    res = features.run(
        "femStmTies.spacingCheck",
        None,
        {
            "tieId": "T1",
            "barDiameterMm": 20,
            "barCount": 5,
            "clearWidthMm": 260,
            "minimumClearSpacingMm": 30,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["clearSpacingMm"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_stm_ties_splice_length(tmp_path: Path) -> None:
    # Eurocodes (fc=28, fy=420, d=20, lapped=1.0, cd=40):
    # lb,rqd = 628.69 mm; alpha2 = 1 - 0.15*(40 - 20)/20 = 0.85; alpha6 = 1.5
    # l0 = 0.85 * 1.5 * 628.69 = 801.58 mm
    _write_eurocodes_settings(tmp_path)
    res = features.run(
        "femStmTies.spliceLength",
        str(tmp_path),
        {"barDiameterMm": 20, "lappedShare": 1, "coverMm": 40},
    )
    assert res["problems"] == []
    assert res["summary"]["basicBondLengthMm"] == pytest.approx(628.69, rel=0.01)
    assert res["summary"]["lapFactor"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["requiredLapLengthMm"] == pytest.approx(801.58, rel=0.01)


def test_fem_stm_ties_stirrup_leg() -> None:
    # A_leg = pi * 6^2 = 113.0973 mm2; 2 legs -> 226.1947 mm2
    # per mm = 226.1947 / 150 = 1.5080 mm2/mm; ratio across 300 mm thickness = 226.1947 / (300*150) = 0.005027
    res = features.run(
        "femStmTies.stirrupLeg",
        None,
        {"barDiameterMm": 12, "legCount": 2, "spacingMm": 150},
    )
    assert res["problems"] == []
    assert res["summary"]["barAreaPerLegMm2"] == pytest.approx(113.0973, rel=0.01)
    assert res["summary"]["totalLegAreaMm2"] == pytest.approx(226.1947, rel=0.01)
    assert res["summary"]["ratioAcrossThickness"] == pytest.approx(0.005027, rel=0.01)


def test_fem_stm_ties_strain_compatibility(tmp_path: Path) -> None:
    # sigma_s = 180.556 MPa -> eps_s = 0.0009028 <= eps_y = 420 / 200000 = 0.0021 -> True
    _write_sized_deep_beam(tmp_path)
    res = features.run(
        "femStmTies.strainCompatibility",
        str(tmp_path),
        {"tieId": "T1", "serviceFactor": 0.65},
    )
    assert res["problems"] == []
    assert res["summary"]["steelStressMpa"] == pytest.approx(180.556, rel=0.01)
    assert res["summary"]["yieldStrain"] == pytest.approx(0.0021, rel=0.01)
    assert res["summary"]["elasticCompatibility"] is True


def test_fem_stm_ties_tie_cover(tmp_path: Path) -> None:
    # T1 width=250, barDiameter=20, clearCover=40 -> centroidCover = 40 + 10 = 50 mm
    # availableWidth = 250 - 2*40 = 170 mm; coverRatio = 50 / 300 = 0.1667
    _write_sized_deep_beam(tmp_path)
    res = features.run("femStmTies.tieCover", str(tmp_path), {"tieId": "T1", "clearCoverMm": 40})
    assert res["problems"] == []
    assert res["summary"]["barCentroidCoverMm"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["availableWidthMm"] == pytest.approx(170.0, rel=0.01)
    assert res["summary"]["coverRatio"] == pytest.approx(0.1667, rel=0.01)


def test_fem_stm_ties_tie_depth() -> None:
    # standalone deepBeam T1 barDiameter = 16 mm -> eff = 350 - 45 = 305 mm; centroid = 45 + 8 = 53 mm
    res = features.run(
        "femStmTies.tieDepth",
        None,
        {"tieId": "T1", "depthMm": 350, "coverMm": 45},
    )
    assert res["problems"] == []
    assert res["summary"]["effectiveDepthMm"] == pytest.approx(305.0, rel=0.01)
    assert res["summary"]["centroidFromFaceMm"] == pytest.approx(53.0, rel=0.01)


# ── Pushover Mechanism (fem_pushover_mechanism.py: 8) ────────────────────────────────────────────


def test_fem_pushover_mechanism_fiber_discretization() -> None:
    # FIBERS_DEPTH=12, FIBERS_WIDTH=6 -> core = 72 fibers, cover = 4*12 = 48 -> total = 120
    # b_core = 500 - 100 = 400 mm, h_core = 700 - 100 = 600 mm -> A_fiber = 400*600/72 = 3333.3333 mm2
    res = features.run(
        "femPushoverMechanism.fiberDiscretization",
        None,
        {"bMm": 500.0, "hMm": 700.0, "coverMm": 50.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalConcreteFibers"] == 120
    assert res["summary"]["coreFiberAreaMm2"] == pytest.approx(3333.3333, rel=0.01)


def test_fem_pushover_mechanism_hinge_capacity() -> None:
    # Defaults: fc=28, fy=420 -> d = 550 - 50 = 500 mm
    # a = 1600 * 420 / (0.85 * 28 * 300) = 672000 / 7140 = 94.1176 mm
    # Mn = 1600 * 420 * (500 - 47.0588) / 1e6 = 304.3765 kN*m
    res = features.run(
        "femPushoverMechanism.hingeCapacity",
        None,
        {"bMm": 300.0, "hMm": 550.0, "asMm2": 1600.0},
    )
    assert res["problems"] == []
    assert res["summary"]["compressionBlockMm"] == pytest.approx(94.1176, rel=0.01)
    assert res["summary"]["nominalMomentKnm"] == pytest.approx(304.3765, rel=0.01)


def test_fem_pushover_mechanism_interaction_surface() -> None:
    # Defaults: fc=28, fy=420; Ag = 500*500 = 250,000 mm2, Ast = 3200 mm2
    # P0 = (0.85*28*(250000 - 3200) + 420*3200)/1000 = (5873840 + 1344000)/1000 = 7217.84 kN
    # Pb = 0.35*0.85*28*250000/1000 = 2082.5 kN; Mb = 2082.5*(500/2000)*0.8 + 0.5*3200*420*400/1e6 = 416.5 + 268.8 = 685.3 kN*m
    # M0 = 0.5*3200*420*(500 - 80)/1e6 = 282.24 kN*m
    res = features.run(
        "femPushoverMechanism.interactionSurface",
        None,
        {"bMm": 500.0, "hMm": 500.0, "astMm2": 3200.0},
    )
    assert res["problems"] == []
    assert res["summary"]["p0Kn"] == pytest.approx(7217.84, rel=0.01)
    assert res["summary"]["mbKnm"] == pytest.approx(685.3, rel=0.01)
    assert res["summary"]["m0Knm"] == pytest.approx(282.24, rel=0.01)


def test_fem_pushover_mechanism_kinematic_energy() -> None:
    # W_int = 200 * 6 * 0.02 = 24.0 kN*m; W_ext = 600 * 0.04 = 24.0 kN*m -> lambda = 1.0
    res = features.run(
        "femPushoverMechanism.kinematicEnergy",
        None,
        {
            "mpKnm": 200.0,
            "hingeCount": 6,
            "virtualRotationRad": 0.02,
            "lateralForceKn": 600.0,
            "virtualRoofDispM": 0.04,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["internalWorkKnm"] == pytest.approx(24.0, rel=0.01)
    assert res["summary"]["externalWorkKnm"] == pytest.approx(24.0, rel=0.01)
    assert res["summary"]["collapseMultiplier"] == pytest.approx(1.0, rel=0.01)


def test_fem_pushover_mechanism_kinematic_validity() -> None:
    # r = 8 -> required = 9 <= 9 -> isCompleteMechanism True
    res = features.run(
        "femPushoverMechanism.kinematicValidity",
        None,
        {"plasticHinges": 9, "degreeIndeterminacy": 8},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredHinges"] == 9
    assert res["summary"]["isCompleteMechanism"] is True


def test_fem_pushover_mechanism_moment_rotation() -> None:
    # theta_y = 240 * 8 / (6 * 40000) = 1920 / 240000 = 0.008 rad; M_cap = 1.08 * 240 = 259.2 kN*m
    res = features.run(
        "femPushoverMechanism.momentRotation",
        None,
        {"mnKnm": 240.0, "eiKnm2": 40000.0, "spanM": 8.0},
    )
    assert res["problems"] == []
    assert res["summary"]["yieldRotationRad"] == pytest.approx(0.008, rel=0.01)
    assert res["summary"]["cappingMomentKnm"] == pytest.approx(259.2, rel=0.01)


def test_fem_pushover_mechanism_strengthen_member() -> None:
    # 160 * 1.25 = 200.0 kN*m (gain = 40.0 kN*m)
    res = features.run(
        "femPushoverMechanism.strengthenMember",
        None,
        {"currentCapacityKnm": 160.0, "increasePct": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["newCapacityKnm"] == pytest.approx(200.0, rel=0.01)
    assert res["summary"]["gainKnm"] == pytest.approx(40.0, rel=0.01)


def test_fem_pushover_mechanism_yield_line_check() -> None:
    # V_beam_sway = (2*250 + 2*150) / 4.0 = 800 / 4 = 200.0 kN
    # V_col_sway = 4*250 / 4.0 = 250.0 kN -> Beam-sway governs
    res = features.run(
        "femPushoverMechanism.yieldLineCheck",
        None,
        {"baySpanM": 7.0, "storeyHeightM": 4.0, "mpBeamKnm": 150.0, "mpColKnm": 250.0},
    )
    assert res["problems"] == []
    assert res["summary"]["beamSwayShearKn"] == pytest.approx(200.0, rel=0.01)
    assert res["summary"]["colSwayShearKn"] == pytest.approx(250.0, rel=0.01)
    assert res["summary"]["governingMechanism"] == "Beam-sway (desirable)"


# ── Analyze (fem_analyze.py: 7) ──────────────────────────────────────────────────────────────────


def test_analyze_diaphragm_flexibility() -> None:
    # aspect = 24 / 10 = 2.4 (<= 3.0); deflRatio = 15 / 10 = 1.5 (0.5 < 1.5 <= 2.0) -> "Semi-rigid"
    res = features.run(
        "analyze.diaphragmFlexibility",
        None,
        {
            "spanM": 24.0,
            "depthM": 10.0,
            "slabThicknessMm": 160.0,
            "maxDriftMm": 10.0,
            "diaphragmDeflMm": 15.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["aspectRatio"] == pytest.approx(2.4, rel=0.01)
    assert res["summary"]["deflectionRatio"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["classification"] == "Semi-rigid"


def test_analyze_eigen_modal_solver() -> None:
    # Standalone H=12 m, BNBC rcSmf (Ct=0.0466, m=0.9) -> T1 = 0.0466 * 12^0.9 = 0.43618 s -> f1 = 2.2926 Hz
    res = features.run(
        "analyze.eigenModalSolver",
        None,
        {"numModes": 18, "shiftFreqHz": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["numModes"] == 18
    assert res["summary"]["shiftHz"] == pytest.approx(0.5, rel=0.01)
    assert res["summary"]["estFundamentalHz"] == pytest.approx(2.2926, rel=0.01)


def test_analyze_memory_profile() -> None:
    # Standalone fallback: 100 nodes (600 DOFs), 160 elems; nnz = 600*42 = 25200
    # k_mb = 25200 * 8 / 1024^2 = 0.19226 MB; lu_mb = 6.5 * 0.19226 = 1.2497 MB; buf = 160*0.05 = 8.0 MB
    # peak = 9.4420 MB; util = 9.4420 / (8 * 1024) * 100 = 0.11526%
    res = features.run("analyze.memoryProfile", None, {"availableRamGb": 8.0})
    assert res["problems"] == []
    assert res["summary"]["dofs"] == 600
    assert res["summary"]["estimatedPeakMb"] == pytest.approx(9.4420, rel=0.01)
    assert res["summary"]["ramUtilizationPct"] == pytest.approx(0.11526, rel=0.01)


def test_analyze_modal_cases() -> None:
    # Standalone T_approx = 0.0466 * 12^0.9 = 0.43618 s
    res = features.run(
        "analyze.modalCases",
        None,
        {"extraction": "ritz", "modes": 15, "massRatioTarget": 0.95},
    )
    assert res["problems"] == []
    assert res["summary"]["extraction"] == "ritz"
    assert res["summary"]["requestedModes"] == 15
    assert res["summary"]["approxPeriodS"] == pytest.approx(0.43618, rel=0.01)


def test_analyze_p_delta() -> None:
    # Configuration lookup against default project settings (secondOrder="none", directAnalysis=False)
    res = features.run(
        "analyze.pDelta",
        None,
        {"method": "directAnalysis", "gravityScale": 1.2},
    )
    assert res["problems"] == []
    assert res["summary"]["method"] == "directAnalysis"
    assert res["summary"]["configuredOption"] == "none"
    assert res["summary"]["directAnalysis"] is False


def test_analyze_ritz_vector_analysis() -> None:
    # 2 directions (UX, UY; includeVertical=False) * 8 vectors = 16 total Ritz vectors
    res = features.run(
        "analyze.ritzVectorAnalysis",
        None,
        {"vectorsPerDirection": 8, "includeVertical": False},
    )
    assert res["problems"] == []
    assert res["summary"]["directions"] == 2
    assert res["summary"]["totalRitzVectors"] == 16


def test_analyze_solver_options() -> None:
    # Standalone fallback: 48 nodes -> 288 DOFs -> max(4.0, 288*36*8/1024^2) = 4.0 MB <= 2048 MB
    res = features.run(
        "analyze.solverOptions",
        None,
        {"solver": "Mumps", "threads": 8, "memoryMb": 2048},
    )
    assert res["problems"] == []
    assert res["summary"]["estimatedDofs"] == 288
    assert res["summary"]["estimatedMemoryMb"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["withinBudget"] is True


# ── Strut-and-Tie (fem_stm.py: 4) ────────────────────────────────────────────────────────────────


def test_fem_strut_tie_crack_reinforcement() -> None:
    # A_bar(16) = pi * 8^2 = 201.0619 mm2; thickness = 300 mm, spacing = 150 mm
    # ratio = 201.0619 / (300 * 150) = 0.004468 >= 0.003 (default pack webRatio) -> passes True
    # bars/m/face = 1000 / 150 = 6.6667
    res = features.run(
        "femStrutTie.crackReinforcement",
        None,
        {"barDiameterMm": 16, "maxSpacingMm": 150},
    )
    assert res["problems"] == []
    assert res["summary"]["barAreaMm2"] == pytest.approx(201.0619, rel=0.01)
    assert res["summary"]["providedRatio"] == pytest.approx(0.004468, rel=0.01)
    assert res["summary"]["barsPerMetrePerFace"] == pytest.approx(6.6667, rel=0.01)
    assert res["summary"]["passesRatio"] is True


def test_fem_strut_tie_reinforcement_layout() -> None:
    # deepBeam T1 tension = 555.5556 kN; phi=0.75, fy=420 -> As_req = 555555.6 / (0.75*420) = 1763.68 mm2
    # A_bar(25) = pi * 12.5^2 = 490.8739 mm2 -> ceil(1763.68 / 490.8739) = 4 bars
    # provided = 4 * 490.8739 = 1963.50 mm2; designCap = 0.75 * 1963.50 * 420 / 1000 = 618.501 kN
    res = features.run(
        "femStrutTie.reinforcementLayout",
        None,
        {"tieId": "T1", "barDiameterMm": 25},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredSteelMm2"] == pytest.approx(1763.68, rel=0.01)
    assert res["summary"]["barCount"] == 4
    assert res["summary"]["providedSteelMm2"] == pytest.approx(1963.50, rel=0.01)
    assert res["summary"]["designCapacityKn"] == pytest.approx(618.501, rel=0.01)


def test_fem_strut_tie_serviceability_check(tmp_path: Path) -> None:
    # Sized deepBeam T1: F=555.556 kN, barArea=2000 mm2 -> sigma_s = 555555.6 * 0.65 / 2000 = 180.556 MPa
    # strain = 180.556 / 200000 = 0.0009028
    _write_sized_deep_beam(tmp_path)
    res = features.run(
        "femStrutTie.serviceabilityCheck",
        str(tmp_path),
        {"serviceLoadFactor": 0.65},
    )
    assert res["problems"] == []
    assert res["summary"]["tiesChecked"] == 1
    row = res["tables"][0]["rows"][0]
    assert row["serviceStressMpa"] == pytest.approx(180.556, rel=0.01)
    assert row["steelStrain"] == pytest.approx(0.0009028, abs=1e-4)


def test_fem_strut_tie_topology_optimise(tmp_path: Path) -> None:
    # dappedEnd shifted B(350, 425) -> (350, 375) with A(150,425), C(350,700), E(1100,700), F(1100,50), Fy(A)=+300 kN:
    # Joint A: F_S1 = -313.88 kN (L=340.04 mm), F_T2 = +190.30 kN (L=206.16 mm)
    # Joint B: F_T4 = +201.20 kN (L=817.39 mm), F_T3 = +33.85 kN (L=325.00 mm)
    # Joint C: F_T6 = +335.91 kN (L=992.47 mm), F_S5 = -438.46 kN (L=750.00 mm)
    # sum(|F_i| * L_i) = 106,731 + 39,231 + 11,000 + 164,462 + 328,846 + 333,385 = 983,655 N*mm (kN*mm)
    model = stm_model.template("dappedEnd", {})
    fem_dir = tmp_path / "08 FEM"
    fem_dir.mkdir()
    (fem_dir / "strut-and-tie.json").write_text(
        StrutAndTieFile(models=[model]).model_dump_json(by_alias=True), encoding="utf-8"
    )
    res = features.run("femStrutTie.topologyOptimise", str(tmp_path), {"maxMoveMm": 50})
    assert res["problems"] == []
    assert res["summary"]["movedNode"] == "B"
    assert res["summary"]["deltaXmm"] == pytest.approx(0.0, abs=1e-6)
    assert res["summary"]["deltaYmm"] == pytest.approx(-50.0, rel=0.01)
    assert res["summary"]["candidateEnergyNmm"] == pytest.approx(983655.0, rel=0.01)

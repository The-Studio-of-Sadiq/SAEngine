"""Independent known-answer tests for FEM Pushover Pattern, Seismic, Mesh, Serviceability, and STM calculators."""

from __future__ import annotations

import json
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


# ── Pushover Pattern (fem_pushover_pattern.py: 15) ──────────────────────────────────────────────


def test_fem_pushover_pattern_cqc_combination() -> None:
    # r = 0.8 / 1.0 = 0.8, xi = 0.05:
    # rho12 = 8 * 0.0025 * 1.8 * 0.8^1.5 / ((1 - 0.64)^2 + 4 * 0.0025 * 0.8 * 1.8^2)
    #       = 0.025759 / (0.1296 + 0.02592) = 0.16563
    # F_cqc = sqrt(300^2 + 200^2 + 2 * 0.16563 * 300 * 200) = sqrt(149875.8) = 387.138 kN
    res = features.run(
        "femPushoverPattern.cqcCombination",
        None,
        {"t1S": 1.0, "t2S": 0.8, "damping": 0.05, "r1Kn": 300.0, "r2Kn": 200.0},
    )
    assert res["problems"] == []
    assert res["summary"]["periodRatio"] == pytest.approx(0.8, rel=0.01)
    assert res["summary"]["correlationRho12"] == pytest.approx(0.1656, rel=0.01)
    assert res["summary"]["cqcForceKn"] == pytest.approx(387.1384, rel=0.01)


def test_fem_pushover_pattern_custom_pattern() -> None:
    # Weights [1, 2, 3, 4], sum = 10 -> Level 1 = 100 kN, total = 1000 kN
    res = features.run(
        "femPushoverPattern.customPattern",
        None,
        {"weights": "1, 2, 3, 4", "baseShearKn": 1000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["levels"] == 4
    assert res["summary"]["totalForceKn"] == pytest.approx(1000.0, rel=0.01)
    assert res["tables"][0]["rows"][0]["forceKn"] == pytest.approx(100.0, rel=0.01)


def test_fem_pushover_pattern_first_mode_pattern() -> None:
    # 3 storeys: phi = [sin(pi/6), sin(pi/3), sin(pi/2)] = [0.5, 0.866025, 1.0], sum = 2.366025
    # roofForce = 800 * 1.0 / 2.366025 = 338.1198 kN
    res = features.run(
        "femPushoverPattern.firstModePattern",
        None,
        {"baseShearKn": 800.0, "storeys": 3},
    )
    assert res["problems"] == []
    assert res["summary"]["levels"] == 3
    assert res["summary"]["roofForceKn"] == pytest.approx(338.1198, rel=0.01)


def test_fem_pushover_pattern_height_exponent() -> None:
    # T1 = 1.5 s -> k = 1.0 + 0.5 * (1.5 - 0.5) = 1.50
    # 4 storeys (3.2, 6.4, 9.6, 12.8): 1^1.5 + 2^1.5 + 3^1.5 + 4^1.5 = 1 + 2.8284 + 5.1962 + 8 = 17.0246
    # Level 1 share = 1 / 17.0246 = 0.05874
    res = features.run(
        "femPushoverPattern.heightExponent",
        None,
        {"periodS": 1.5, "storeys": 4},
    )
    assert res["problems"] == []
    assert res["summary"]["exponentK"] == pytest.approx(1.5, rel=0.01)
    assert res["tables"][0]["rows"][0]["share"] == pytest.approx(0.05874, rel=0.01)


def test_fem_pushover_pattern_inelastic_displacement() -> None:
    # C1 * C2 * Sd_el = 1.25 * 1.1 * 80 = 110.0 mm
    res = features.run(
        "femPushoverPattern.inelasticDisplacement",
        None,
        {"elasticDispMm": 80.0, "c1": 1.25, "c2": 1.1},
    )
    assert res["problems"] == []
    assert res["summary"]["amplification"] == pytest.approx(1.375, rel=0.01)
    assert res["summary"]["inelasticDispMm"] == pytest.approx(110.0, rel=0.01)


def test_fem_pushover_pattern_instantaneous_vector() -> None:
    # Displacements [10, 20, 30, 40], sum = 100 -> Level 1 = 500 * 10/100 = 50.0 kN
    res = features.run(
        "femPushoverPattern.instantaneousVector",
        None,
        {"displacementsMm": "10, 20, 30, 40", "totalShearKn": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalShearKn"] == pytest.approx(500.0, rel=0.01)
    assert res["tables"][0]["rows"][0]["forceKn"] == pytest.approx(50.0, rel=0.01)


def test_fem_pushover_pattern_max_steps() -> None:
    # 300 * 1.5 = 450.0 mm
    res = features.run("femPushoverPattern.maxSteps", None, {"maxSteps": 300, "stepMm": 1.5})
    assert res["problems"] == []
    assert res["summary"]["maxSteps"] == 300
    assert res["summary"]["maxTravelMm"] == pytest.approx(450.0, rel=0.01)


def test_fem_pushover_pattern_pattern_scale() -> None:
    # sum(30, 60, 90, 120) = 300 -> sf = 900 / 300 = 3.0 -> scaled Level 1 = 90.0 kN
    res = features.run(
        "femPushoverPattern.patternScale",
        None,
        {"referenceBaseShearKn": 900.0, "rawVector": "30, 60, 90, 120"},
    )
    assert res["problems"] == []
    assert res["summary"]["scaleFactor"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["scaledTotalKn"] == pytest.approx(900.0, rel=0.01)
    assert res["tables"][0]["rows"][0]["scaledKn"] == pytest.approx(90.0, rel=0.01)


def test_fem_pushover_pattern_step_size() -> None:
    # ceil(300 / 2.5) = 120 steps
    res = features.run(
        "femPushoverPattern.stepSize",
        None,
        {"targetRoofDispMm": 300.0, "stepIncrementMm": 2.5},
    )
    assert res["problems"] == []
    assert res["summary"]["steps"] == 120
    assert res["summary"]["incrementMm"] == pytest.approx(2.5, rel=0.01)


def test_fem_pushover_pattern_stop_criteria() -> None:
    # 16.0 * 0.04 * 1000 = 640.0 mm
    res = features.run(
        "femPushoverPattern.stopCriteria",
        None,
        {"buildingHeightM": 16.0, "maxDriftRatio": 0.04, "minShearShare": 0.75},
    )
    assert res["problems"] == []
    assert res["summary"]["stopRoofDispMm"] == pytest.approx(640.0, rel=0.01)
    assert res["summary"]["minShearRetention"] == pytest.approx(0.75, rel=0.01)


def test_fem_pushover_pattern_story_force() -> None:
    # 200 * 9.80665 * 0.8 * 0.25 = 392.266 kN
    res = features.run(
        "femPushoverPattern.storyForce",
        None,
        {"storeyMassTonnes": 200.0, "modeOrdinate": 0.8, "accelG": 0.25},
    )
    assert res["problems"] == []
    assert res["summary"]["storeyForceKn"] == pytest.approx(392.266, rel=0.01)


def test_fem_pushover_pattern_triangular_pattern() -> None:
    # 3 storeys @ 3.2 m: weights 1:2:3 (sum=6) -> roof = 600 * 3/6 = 300.0 kN
    res = features.run(
        "femPushoverPattern.triangularPattern",
        None,
        {"baseShearKn": 600.0, "storeys": 3},
    )
    assert res["problems"] == []
    assert res["summary"]["levels"] == 3
    assert res["summary"]["roofForceKn"] == pytest.approx(300.0, rel=0.01)


def test_fem_pushover_pattern_uniform_pattern() -> None:
    # 600 / 5 = 120.0 kN per floor
    res = features.run(
        "femPushoverPattern.uniformPattern",
        None,
        {"baseShearKn": 600.0, "storeys": 5},
    )
    assert res["problems"] == []
    assert res["summary"]["levels"] == 5
    assert res["summary"]["forcePerFloorKn"] == pytest.approx(120.0, rel=0.01)


def test_fem_pushover_pattern_update_spectrum() -> None:
    # Te = 0.8 / sqrt(0.25) = 1.6 s
    # Default pack (BNBC 2020, SD: S=1.35, TC=0.8, TD=2.0; Dhaka Z=0.18):
    # Sa(1.6) = 2.5 * 1.35 * (0.8 / 1.6) * 0.18 = 0.30375 g
    res = features.run(
        "femPushoverPattern.updateSpectrum",
        None,
        {"initialPeriodS": 0.8, "stiffnessRatio": 0.25},
    )
    assert res["problems"] == []
    assert res["summary"]["elongatedPeriodS"] == pytest.approx(1.6, rel=0.01)
    assert res["summary"]["updatedSaG"] == pytest.approx(0.30375, rel=0.01)


def test_fem_pushover_pattern_vector_overlay() -> None:
    # 4 default levels (3.2..12.8 m), sum = 1+2+3+4 = 10 -> Level 1 Fx = 800 * 1/10 = 80.0 kN
    res = features.run("femPushoverPattern.vectorOverlay", None, {"baseShearKn": 800.0})
    assert res["problems"] == []
    assert res["summary"]["vectors"] == 4
    assert res["tables"][0]["rows"][0]["fxKn"] == pytest.approx(80.0, rel=0.01)
    assert res["tables"][0]["rows"][0]["arrowLengthM"] == pytest.approx(0.5, rel=0.01)


# ── Seismic (fem_seismic.py: 14) ────────────────────────────────────────────────────────────────


def test_fem_seismic_accelerogram() -> None:
    # 6 points, dt=0.05 s -> duration = 5 * 0.05 = 0.25 s; PGA = 0.4 g
    # Trapezoid of a^2 [0, 0.01, 0.04, 0.16, 0.04, 0] * 0.05 = 0.25 * 0.05 = 0.0125 g^2*s
    # IA = (pi / (2 * 9.80665)) * 0.0125 * 9.80665^2 = 0.5 * pi * 9.80665 * 0.0125 = 0.19255 m/s
    res = features.run(
        "femSeismic.accelerogram",
        None,
        {"series": "0, 0.1, -0.2, 0.4, -0.2, 0", "dtS": 0.05},
    )
    assert res["problems"] == []
    assert res["summary"]["points"] == 6
    assert res["summary"]["durationS"] == pytest.approx(0.25, rel=0.01)
    assert res["summary"]["pgaG"] == pytest.approx(0.4, rel=0.01)
    assert res["summary"]["ariasIntensityMS"] == pytest.approx(0.19255, rel=0.01)


def test_fem_seismic_accidental_torsion() -> None:
    # Fallback building dimensions (18.0 m x 12.0 m):
    # offsetX = 0.08 * 18.0 = 1.44 m; offsetY = 0.08 * 12.0 = 0.96 m
    res = features.run("femSeismic.accidentalTorsion", None, {"eccentricityShare": 0.08})
    assert res["problems"] == []
    assert res["summary"]["offsetXM"] == pytest.approx(1.44, rel=0.01)
    assert res["summary"]["offsetYM"] == pytest.approx(0.96, rel=0.01)


def test_fem_seismic_behaviour_factor() -> None:
    # Pure code-pack lookup: default project system rcSmf in BNBC 2020 has R=8.0, Omega0=3.0, Cd=5.5.
    res = features.run("femSeismic.behaviourFactor", None, {"rFactor": 6.0})
    assert res["problems"] == []
    assert res["summary"]["rx"] == pytest.approx(8.0, rel=0.01)
    assert res["summary"]["omegaX"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["cdX"] == pytest.approx(5.5, rel=0.01)


def test_fem_seismic_damping() -> None:
    # BNBC 2020 / EC8 damping factor: eta = max(0.55, sqrt(10 / (5 + 100 * 0.10))) = sqrt(10/15) = 0.8165
    res = features.run("femSeismic.damping", None, {"dampingRatio": 0.10})
    assert res["problems"] == []
    assert res["summary"]["dampingCorrectionEta"] == pytest.approx(0.8165, rel=0.01)


def test_fem_seismic_lateral_force_distribution() -> None:
    # 5 storeys -> triangular sum 1+2+3+4+5 = 15 -> Level 1 = 900 * 1/15 = 60.0 kN
    res = features.run(
        "femSeismic.lateralForceDistribution",
        None,
        {"baseShearKn": 900.0, "storeys": 5},
    )
    assert res["problems"] == []
    assert res["summary"]["levels"] == 5
    assert res["summary"]["totalForceKn"] == pytest.approx(900.0, rel=0.01)
    assert res["tables"][0]["rows"][0]["forceKn"] == pytest.approx(60.0, rel=0.01)


def test_fem_seismic_motion_scaling() -> None:
    # sf = 0.6 / 0.3 = 2.0 in [0.5, 3.0] -> withinAmplitudeBounds True
    res = features.run(
        "femSeismic.motionScaling",
        None,
        {"recordSaG": 0.3, "targetSaG": 0.6, "minScale": 0.5, "maxScale": 3.0},
    )
    assert res["problems"] == []
    assert res["summary"]["scaleFactor"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["withinAmplitudeBounds"] is True


def test_fem_seismic_period_estimate() -> None:
    # Default pack (BNBC 2020) rcSmf: Ct = 0.0466, m = 0.9:
    # Ta = 0.0466 * 20^0.9 = 0.6907 s; upper = 1.4 * 0.6907 = 0.9670 s
    res = features.run("femSeismic.periodEstimate", None, {"heightM": 20.0, "depthM": 16.0})
    assert res["problems"] == []
    assert res["summary"]["approxPeriodS"] == pytest.approx(0.6907, rel=0.01)
    assert res["summary"]["upperBoundPeriodS"] == pytest.approx(0.9670, rel=0.01)


def test_fem_seismic_redundancy_factor() -> None:
    # baysX = 1 < 2 -> governingRho = 1.3
    res = features.run(
        "femSeismic.redundancyFactor",
        None,
        {"baysX": 1, "baysY": 3, "extremeTorsion": False},
    )
    assert res["problems"] == []
    assert res["summary"]["governingRho"] == pytest.approx(1.3, rel=0.01)


def test_fem_seismic_response_spectrum() -> None:
    # Default pack (BNBC 2020, Dhaka Z=0.18, SD: S=1.35, TB=0.2, TC=0.8, TD=2.0, R=8, I=1):
    # Plateau elastic Sa = 2.5 * 1.35 * 0.18 = 0.6075 g; design Cs = (2/3) * 0.6075 * (1/8) = 0.050625 g
    res = features.run("femSeismic.responseSpectrum", None, {"damping": 0.05})
    assert res["problems"] == []
    assert res["summary"]["peakSaG"] == pytest.approx(0.6075, rel=0.01)
    row_plateau = _row_by(res, "periodS", 0.4)
    assert row_plateau["elasticSaG"] == pytest.approx(0.6075, rel=0.01)
    assert row_plateau["designCs"] == pytest.approx(0.050625, rel=0.01)


def test_fem_seismic_seismic_coefficient() -> None:
    # Ta = 0.0466 * 20^0.9 = 0.6907 s (in plateau [0.2, 0.8])
    # Cs = (2/3) * 0.18 * (1/8) * (2.5 * 1.35) = 0.050625 -> V = 0.050625 * 10000 = 506.25 kN
    res = features.run(
        "femSeismic.seismicCoefficient",
        None,
        {"heightM": 20.0, "weightKn": 10000.0, "damping": 0.05},
    )
    assert res["problems"] == []
    assert res["summary"]["periodS"] == pytest.approx(0.6907, rel=0.01)
    assert res["summary"]["cs"] == pytest.approx(0.050625, rel=0.01)
    assert res["summary"]["baseShearKn"] == pytest.approx(506.25, rel=0.01)


def test_fem_seismic_spectrum_compare() -> None:
    # Plateau T=0.5 s: elasticSaG = 0.6075 g, designCsG = 0.050625 g, reductionRatio = 12.0
    res = features.run("femSeismic.spectrumCompare", None, {"damping": 0.05})
    assert res["problems"] == []
    row = _row_by(res, "periodS", 0.5)
    assert row["elasticSaG"] == pytest.approx(0.6075, rel=0.01)
    assert row["designCsG"] == pytest.approx(0.050625, rel=0.01)
    assert row["reductionRatio"] == pytest.approx(12.0, rel=0.01)


def test_fem_seismic_spectrum_matching() -> None:
    # Property + spectral check: doubling the seed accelerogram doubles every recordSaG and meanSpectralRatio.
    base = features.run(
        "femSeismic.spectrumMatching",
        None,
        {"series": "0, 0.1, -0.2, 0.4, -0.2, 0", "dtS": 0.05, "damping": 0.05},
    )
    doubled = features.run(
        "femSeismic.spectrumMatching",
        None,
        {"series": "0, 0.2, -0.4, 0.8, -0.4, 0", "dtS": 0.05, "damping": 0.05},
    )
    assert base["problems"] == []
    assert doubled["problems"] == []
    assert base["summary"]["periods"] == 6
    assert doubled["summary"]["meanSpectralRatio"] == pytest.approx(
        2.0 * base["summary"]["meanSpectralRatio"], rel=0.01
    )


def test_fem_seismic_storey_shear_distribution() -> None:
    # T=0.4 <= 0.5 -> k = 1.0; 4 storeys -> 1:2:3:4 (sum=10) -> roof = 1000 * 4/10 = 400.0 kN
    res = features.run(
        "femSeismic.storeyShearDistribution",
        None,
        {"baseShearKn": 1000.0, "storeys": 4, "storeyHeightM": 3.0, "periodS": 0.4},
    )
    assert res["problems"] == []
    assert res["summary"]["exponentK"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["roofForceKn"] == pytest.approx(400.0, rel=0.01)
    assert res["tables"][0]["rows"][0]["storeyShearKn"] == pytest.approx(1000.0, rel=0.01)


def test_fem_seismic_time_history() -> None:
    # Pure code-pack lookup: BNBC 2020 uses "max" for 3 records (< 7) and "mean" for >= 7 records.
    r3 = features.run(
        "femSeismic.timeHistory",
        None,
        {"procedure": "nonlinear", "recordsCount": 3},
    )
    r7 = features.run(
        "femSeismic.timeHistory",
        None,
        {"procedure": "nonlinear", "recordsCount": 7},
    )
    assert r3["problems"] == []
    assert r7["problems"] == []
    assert r3["summary"]["designRule"] == "max"
    assert r7["summary"]["designRule"] == "mean"


# ── Mesh (fem_mesh.py: 11) ──────────────────────────────────────────────────────────────────────


def test_fem_mesh_adaptive_refinement() -> None:
    # ratio = 16 / 4 = 4.0 -> h_new = 800 / sqrt(4) = 400.0 mm -> refinementFactor = 2.0
    res = features.run(
        "femMesh.adaptiveRefinement",
        None,
        {"errorTargetPct": 4.0, "currentSizeMm": 800.0, "estimatedJumpPct": 16.0},
    )
    assert res["problems"] == []
    assert res["summary"]["recommendedSizeMm"] == pytest.approx(400.0, rel=0.01)
    assert res["summary"]["refinementFactor"] == pytest.approx(2.0, rel=0.01)


def test_fem_mesh_embedded_rebar() -> None:
    # A_bar(16) = pi * 8^2 = 201.0619 mm2; As/m = 201.0619 * (1000 / 200) = 1005.3096 mm2/m
    # EA/m = 1005.3096 * 200 = 201,061.93 kN/m; T_y = 1005.3096 * 500 / 1000 = 502.6548 kN/m
    res = features.run(
        "femMesh.embeddedRebar",
        None,
        {"barDiameterMm": 16.0, "spacingMm": 200.0, "fyMpa": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["barAreaMm2"] == pytest.approx(201.0619, rel=0.01)
    assert res["summary"]["asPerMMm2"] == pytest.approx(1005.3096, rel=0.01)
    assert res["summary"]["eaPerMKn"] == pytest.approx(201061.93, rel=0.01)
    assert res["summary"]["yieldForceKnPerM"] == pytest.approx(502.6548, rel=0.01)


def test_fem_mesh_generate_mesh() -> None:
    # nx = 8 / 0.4 = 20, ny = 6 / 0.4 = 15 -> 300 shells, 21 * 16 = 336 nodes
    res = features.run(
        "femMesh.generateMesh",
        None,
        {"meshSizeMm": 400.0, "slabLengthM": 8.0, "slabWidthM": 6.0},
    )
    assert res["problems"] == []
    assert res["summary"]["shellElements"] == 300
    assert res["summary"]["nodes"] == 336


def test_fem_mesh_local_refinement() -> None:
    # ratio = 800 / 200 = 4.0; rings = ceil(ln(4) / ln(1.35)) = ceil(4.619) = 5
    res = features.run(
        "femMesh.localRefinement",
        None,
        {"baseSizeMm": 800.0, "refinedSizeMm": 200.0, "zoneRadiusM": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["refinementRatio"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["transitionRings"] == 5


def test_fem_mesh_quality(tmp_path: Path) -> None:
    # Two shell quads: 1x1 m (AR=1.0) and 4x1 m (AR=4.0); limit=3.0 -> 1 fail -> 50% pass
    osmodel = {
        "nodes": [
            {"id": 1, "coords": [0.0, 0.0, 0.0]},
            {"id": 2, "coords": [1.0, 0.0, 0.0]},
            {"id": 3, "coords": [1.0, 1.0, 0.0]},
            {"id": 4, "coords": [0.0, 1.0, 0.0]},
            {"id": 5, "coords": [5.0, 0.0, 0.0]},
            {"id": 6, "coords": [5.0, 1.0, 0.0]},
        ],
        "elements": [
            {"id": 1, "type": "ShellMITC4", "nodes": [1, 2, 3, 4]},
            {"id": 2, "type": "ShellMITC4", "nodes": [2, 5, 6, 3]},
        ],
    }
    fem_dir = tmp_path / "08 FEM"
    fem_dir.mkdir()
    (fem_dir / "model.osmodel").write_text(json.dumps(osmodel), encoding="utf-8")
    res = features.run("femMesh.meshQuality", str(tmp_path), {"maxAspectRatio": 3.0})
    assert res["problems"] == []
    assert res["summary"]["elementsChecked"] == 2
    assert res["summary"]["maxAspectRatio"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["failingElements"] == 1
    assert res["summary"]["passRatePct"] == pytest.approx(50.0, rel=0.01)


def test_fem_mesh_mesh_size() -> None:
    # step 0 = 400, step 1 = 600, step 2 = 900, step 3 = 1350, step 4 = 2025 mm
    res = features.run(
        "femMesh.meshSize",
        None,
        {"globalSizeMm": 400.0, "growthRate": 1.5, "minSpanDivisions": 10},
    )
    assert res["problems"] == []
    assert res["summary"]["globalSizeMm"] == pytest.approx(400.0, rel=0.01)
    assert _row_by(res, "step", 4)["elementSizeMm"] == pytest.approx(2025.0, rel=0.01)


def test_fem_mesh_mesh_smoothing() -> None:
    # 24.0 * 0.72^3 = 8.95795 deg
    res = features.run("femMesh.meshSmoothing", None, {"iterations": 3})
    assert res["problems"] == []
    assert res["summary"]["passes"] == 3
    assert res["summary"]["finalSkewDeg"] == pytest.approx(8.9580, rel=0.01)


def test_fem_mesh_remesh_region() -> None:
    # 25 / 1^2 = 25 -> 25 / 0.5^2 = 100 -> multiplier = 4.0
    res = features.run(
        "femMesh.remeshRegion",
        None,
        {"oldSizeMm": 1000.0, "newSizeMm": 500.0, "regionAreaM2": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["previousElements"] == 25
    assert res["summary"]["newElements"] == 100
    assert res["summary"]["elementMultiplier"] == pytest.approx(4.0, rel=0.01)


def test_fem_mesh_shell_elements() -> None:
    # t = 0.2 m, E = 3e7 kPa, nu = 0.2 -> 1 - nu^2 = 0.96
    # D = 3e7 * 0.008 / (12 * 0.96) = 20833.3333 kN*m
    # C = 3e7 * 0.2 / 0.96 = 6,250,000 kN/m
    res = features.run(
        "femMesh.shellElements",
        None,
        {"formulation": "ShellDKGQ", "thicknessMm": 200.0, "eMpa": 30000.0, "nu": 0.2},
    )
    assert res["problems"] == []
    assert res["summary"]["flexuralRigidityKnm"] == pytest.approx(20833.3333, rel=0.01)
    assert res["summary"]["membraneRigidityKnPerM"] == pytest.approx(6250000.0, rel=0.01)


def test_fem_mesh_solid_elements() -> None:
    # 900 / 6 = 150.0 mm
    res = features.run(
        "femMesh.solidElements",
        None,
        {"topology": "FourNodeTetrahedron", "minThicknessMm": 900.0, "layersAcross": 6},
    )
    assert res["problems"] == []
    assert res["summary"]["maxElementSizeMm"] == pytest.approx(150.0, rel=0.01)


def test_fem_mesh_tendons() -> None:
    # Ap = 150 * 6 = 900 mm2; P = 900 * 1400 / 1000 = 1260 kN
    # w_bal = 8 * 1260 * 0.25 / 10^2 = 25.2 kN/m
    res = features.run(
        "femMesh.tendons",
        None,
        {
            "strandAreaMm2": 150.0,
            "strands": 6,
            "jackingStressMpa": 1400.0,
            "spanM": 10.0,
            "drapeMm": 250.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["totalAreaMm2"] == pytest.approx(900.0, rel=0.01)
    assert res["summary"]["prestressForceKn"] == pytest.approx(1260.0, rel=0.01)
    assert res["summary"]["balancingLoadKnPerM"] == pytest.approx(25.2, rel=0.01)


# ── Serviceability (fem_serviceability.py: 11) ──────────────────────────────────────────────────


def test_fem_serviceability_camber() -> None:
    # req = 20 * (1 + 0.5 * 1.6) = 36.0 mm -> nearest 5 mm = 35.0 mm
    res = features.run(
        "femServiceability.camber",
        None,
        {"spanMm": 12000.0, "deadDeflectionMm": 20.0, "longTermFactor": 1.6},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredCamberMm"] == pytest.approx(36.0, rel=0.01)
    assert res["summary"]["specifiedCamberMm"] == pytest.approx(35.0, rel=0.01)


def test_fem_serviceability_comfort_criteria() -> None:
    # 1.2 <= 1.5 (shopping) -> passes True
    res = features.run(
        "femServiceability.comfortCriteria",
        None,
        {"peakAccelPercentG": 1.2, "occupancy": "shopping"},
    )
    assert res["problems"] == []
    assert res["summary"]["limitPctG"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_serviceability_crack_width(tmp_path: Path) -> None:
    # Eurocode 2 directWidth requires a pack with concreteMethods.cracking (eurocodes):
    # fck=28 -> fctm=2.7663 MPa, Ecm=32308.25 MPa, ae=200000/32308.25=6.1904
    # b=350, h=550, d=510, As=1256, M=60e6 Nmm -> x=129.94 mm, Icr=1.37905e9 mm4, sigma_s=102.38 MPa
    # hc,ef=min(100, (550-129.94)/3, 275)=100 mm, rho_eff=1256/35000=0.03589
    # eps_diff=0.0003235, sr,max=3.4*30 + 0.8*0.5*0.425*20/0.03589=196.75 mm -> wk = 0.0636 mm <= 0.3 mm (XS1)
    settings_dir = tmp_path / "02 Project Settings"
    settings_dir.mkdir()
    settings = default_project_settings("EC", code_pack="eurocodes")
    (settings_dir / "project-settings.json").write_text(
        settings.model_dump_json(by_alias=True), encoding="utf-8"
    )
    res = features.run(
        "femServiceability.crackWidth",
        str(tmp_path),
        {
            "exposure": "XS1",
            "momentKnm": 60.0,
            "bMm": 350.0,
            "hMm": 550.0,
            "barMm": 20.0,
            "asMm2": 1256.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["wkMm"] == pytest.approx(0.0636, rel=0.02)
    assert res["summary"]["wmaxMm"] == pytest.approx(0.3, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_serviceability_creep_shrinkage() -> None:
    # Default pack BNBC 2020 concreteTime table at h0=300 mm, RH=70%, t0=28 d:
    # Final creep cc = 1.86; development at 3650 d on log1p between (912.5, 0.8) and (10950, 1.0) = 0.91155
    # phi(3650, 28) = 1.86 * 0.91155 = 1.6955
    res = features.run(
        "femServiceability.creepShrinkage",
        None,
        {"thicknessMm": 300.0, "humidityPct": 70.0, "loadingAgeDays": 28.0},
    )
    assert res["problems"] == []
    assert res["summary"]["finalCreepPhi"] == pytest.approx(1.6955, rel=0.01)
    assert res["summary"]["finalShrinkageMicrostrain"] > 0.0


def test_fem_serviceability_deflection_check() -> None:
    # Ig = 300 * 600^3 / 12 = 5.4e9 mm4; Icr = 0.35 * 5.4e9 = 1.89e9 mm4
    # Ec = 4700 * sqrt(30) = 25742.96 MPa; Mcr = 0.62 * sqrt(30) * 5.4e9 / 300 = 61.1258e6 Nmm
    # (Mcr/Ma)^3 = (61.1258 / 80)^3 = 0.4459 -> Ie = 0.4459*5.4e9 + 0.5541*1.89e9 = 3.4553e9 mm4 (Ie/Ig = 0.6399)
    # delta = (5/48) * 80e6 * 7200^2 / (25742.96 * 3.4553e9) = 4.8561 mm <= 7200/360 = 20.0 mm
    res = features.run(
        "femServiceability.deflectionCheck",
        None,
        {"spanMm": 7200.0, "bMm": 300.0, "hMm": 600.0, "maKnm": 80.0, "fcMpa": 30.0},
    )
    assert res["problems"] == []
    assert res["summary"]["ieOverIg"] == pytest.approx(0.6399, rel=0.01)
    assert res["summary"]["deflectionMm"] == pytest.approx(4.8561, rel=0.01)
    assert res["summary"]["limitMm"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_serviceability_floor_vibration() -> None:
    # Default pack floorVibration (concrete responseFactor, residential default -> damping=0.02, modalShare=0.25):
    # w = 320 / 64 = 5.0 kN/m2; modal mass m = 0.25 * (5000 / 9.81 * 64) = 8154.94 kg
    # At fn = 6.0 Hz, harmonic 3 (fp = 2.0 Hz): r_3 = 0.007*(6 + 5.2) = 0.0784
    # build = 1 - exp(-2*pi*0.02*8/0.75) = 0.7383; peak = 1 / (2*0.02) = 25
    # a_rms = 0.7383 * 0.0784 * 746 * 25 / (sqrt(2) * 8154.94) = 0.09359 m/s2 -> R = 0.09359 / 0.005 = 18.718
    res = features.run(
        "femServiceability.floorVibration",
        None,
        {"fnHz": 6.0, "spanM": 8.0, "areaM2": 64.0, "panelWeightKn": 320.0},
    )
    assert res["problems"] == []
    assert res["summary"]["value"] == pytest.approx(18.718, rel=0.01)
    assert res["summary"]["limit"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["ok"] is False


def test_fem_serviceability_long_term_deflection() -> None:
    # lambda = 2.0 / (1 + 50 * 0.005) = 2.0 / 1.25 = 1.60
    # sustained = 8.0 + 0.4 * 5.0 = 10.0 mm -> creep = 1.60 * 10.0 = 16.0 mm
    # total = 8.0 + 5.0 + 16.0 = 29.0 mm
    res = features.run(
        "femServiceability.longTermDeflection",
        None,
        {
            "immediateDeadMm": 8.0,
            "immediateLiveMm": 5.0,
            "sustainedLiveShare": 0.4,
            "rhoPrime": 0.005,
            "xi": 2.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["lambdaDelta"] == pytest.approx(1.60, rel=0.01)
    assert res["summary"]["creepDeflectionMm"] == pytest.approx(16.0, rel=0.01)
    assert res["summary"]["totalDeflectionMm"] == pytest.approx(29.0, rel=0.01)


def test_fem_serviceability_long_term_factors() -> None:
    # xi(12) = 1.0 + sqrt((12 - 3) / 57) = 1.0 + sqrt(9/57) = 1.39736
    res = features.run("femServiceability.longTermFactors", None, {"months": 12.0})
    assert res["problems"] == []
    assert res["summary"]["xiFactor"] == pytest.approx(1.3974, rel=0.01)


def test_fem_serviceability_natural_frequency() -> None:
    # fn = 18.0 / sqrt(9.0) = 6.0 Hz >= 3.0 -> passesMin3Hz True
    res = features.run(
        "femServiceability.naturalFrequency",
        None,
        {"midspanDeflectionMm": 9.0, "constantC": 18.0},
    )
    assert res["problems"] == []
    assert res["summary"]["naturalFrequencyHz"] == pytest.approx(6.0, rel=0.01)
    assert res["summary"]["passesMin3Hz"] is True


def test_fem_serviceability_settlement_influence() -> None:
    # M = 6 * 30000 * 0.010 / 5^2 = 1800 / 25 = 72.0 kN*m
    # V = 12 * 30000 * 0.010 / 5^3 = 3600 / 125 = 28.8 kN
    res = features.run(
        "femServiceability.settlementInfluence",
        None,
        {"spanM": 5.0, "eiKnm2": 30000.0, "deltaMm": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["inducedMomentKnm"] == pytest.approx(72.0, rel=0.01)
    assert res["summary"]["inducedShearKn"] == pytest.approx(28.8, rel=0.01)


def test_fem_serviceability_span_ratios() -> None:
    # Default fy=420 -> modifier = 0.4 + 420/700 = 1.0; bothEnds base = 21.0 -> limit = 21.0
    # actual = 7000 / 350 = 20.0 <= 21.0 -> passes True; minDepth = 7000 / 21 = 333.33 mm
    res = features.run(
        "femServiceability.spanRatios",
        None,
        {"spanMm": 7000.0, "depthMm": 350.0, "support": "bothEnds"},
    )
    assert res["problems"] == []
    assert res["summary"]["actualSpanDepth"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["limitSpanDepth"] == pytest.approx(21.0, rel=0.01)
    assert res["summary"]["minDepthMm"] == pytest.approx(333.3333, rel=0.01)
    assert res["summary"]["passes"] is True


# ── STM Results (fem_stm_results.py: 5) ─────────────────────────────────────────────────────────


def test_fem_stm_results_bursting_steel() -> None:
    # deepBeam: R_A = 500 kN -> bursting = 0.2 * 500 = 100.0 kN
    # As = 100,000 / (0.75 * 420) = 317.4603 mm2
    res = features.run("femStmResults.burstingSteel", None, {"loadShare": 0.2})
    assert res["problems"] == []
    assert res["summary"]["bearingZones"] == 3
    row_a = _row_by(res, "nodeId", "A")
    assert row_a["burstingForceKn"] == pytest.approx(100.0, rel=0.01)
    assert row_a["requiredSteelMm2"] == pytest.approx(317.4603, rel=0.01)


def test_fem_stm_results_deformation_scale() -> None:
    # Returns unfabricated coordinates with displayScale=25 and displacementsAvailable=False
    res = features.run("femStmResults.deformationScale", None, {"displayScale": 25})
    assert res["problems"] == []
    assert res["summary"]["nodes"] == 3
    assert res["summary"]["displayScale"] == pytest.approx(25.0, rel=0.01)
    assert res["summary"]["displacementsAvailable"] is False
    row_c = _row_by(res, "nodeId", "C")
    assert row_c["scaledXmm"] == pytest.approx(1500.0, rel=0.01)
    assert row_c["scaledYmm"] == pytest.approx(1425.0, rel=0.01)


def test_fem_stm_results_detailing_check(tmp_path: Path) -> None:
    # Sized deepBeam tie T1: width=250 mm, barArea=2000 mm2, barDiameter=20 mm -> A_bar=314.159 -> 7 bars
    # clearWidth = 250 - 2*35 - 7*20 = 40.0 mm < (7-1)*30 = 180 mm -> barFitPass False
    model = stm_model.template("deepBeam", {})
    sized = model.model_copy(
        update={
            "members": [
                m.model_copy(update={"width": 250.0, "barArea": 2000.0, "barDiameter": 20.0})
                if m.id == "T1"
                else m
                for m in model.members
            ]
        }
    )
    fem_dir = tmp_path / "08 FEM"
    fem_dir.mkdir()
    (fem_dir / "strut-and-tie.json").write_text(
        StrutAndTieFile(models=[sized]).model_dump_json(by_alias=True), encoding="utf-8"
    )
    res = features.run(
        "femStmResults.detailingCheck",
        str(tmp_path),
        {"coverMm": 35, "minimumClearSpacingMm": 30},
    )
    assert res["problems"] == []
    r0 = res["tables"][0]["rows"][0]
    assert r0["barCount"] == 7
    assert r0["clearWidthMm"] == pytest.approx(40.0, rel=0.01)
    assert r0["barFitPass"] is False


def test_fem_stm_results_service_load_check(tmp_path: Path) -> None:
    # Sized deepBeam tie T1: F_tie = 555.56 kN, barArea = 2000 mm2
    # serviceStress = 555,555.6 * 0.7 / 2000 = 194.444 MPa <= 240.0 MPa -> passes True
    model = stm_model.template("deepBeam", {})
    sized = model.model_copy(
        update={
            "members": [
                m.model_copy(update={"width": 250.0, "barArea": 2000.0, "barDiameter": 20.0})
                if m.id == "T1"
                else m
                for m in model.members
            ]
        }
    )
    fem_dir = tmp_path / "08 FEM"
    fem_dir.mkdir()
    (fem_dir / "strut-and-tie.json").write_text(
        StrutAndTieFile(models=[sized]).model_dump_json(by_alias=True), encoding="utf-8"
    )
    res = features.run(
        "femStmResults.serviceLoadCheck",
        str(tmp_path),
        {"serviceFactor": 0.7, "steelStressLimitMpa": 240},
    )
    assert res["problems"] == []
    r0 = res["tables"][0]["rows"][0]
    assert r0["serviceStressMpa"] == pytest.approx(194.444, rel=0.01)
    assert r0["passes"] is True


def test_fem_stm_results_tie_layout() -> None:
    # deepBeam T1 force = 555.56 kN -> As_req = 555555.6 / (0.75 * 420) = 1763.67 mm2
    # A_bar(25) = pi * 12.5^2 = 490.87 mm2 -> ceil(1763.67 / 490.87) = 4 bars -> As_prov = 1963.50 mm2
    res = features.run("femStmResults.tieLayout", None, {"barDiameterMm": 25, "coverMm": 35})
    assert res["problems"] == []
    r0 = res["tables"][0]["rows"][0]
    assert r0["barCount"] == 4
    assert r0["requiredSteelMm2"] == pytest.approx(1763.68, rel=0.01)
    assert r0["providedSteelMm2"] == pytest.approx(1963.50, rel=0.01)


# ── STM Topology (fem_stm_topology.py: 5) ───────────────────────────────────────────────────────


def test_fem_stm_topology_angle_envelope() -> None:
    # deepBeam: angle between T1 (horizontal) and S2 (dx=1500, dy=1350) = atan2(1350, 1500) = 41.9872 deg
    # 30 <= 41.9872 <= 60 -> withinEnvelope True
    res = features.run(
        "femStmTopology.angleEnvelope",
        None,
        {"minimumAngleDeg": 30, "maximumAngleDeg": 60},
    )
    assert res["problems"] == []
    assert res["summary"]["jointAngles"] == 2
    r0 = res["tables"][0]["rows"][0]
    assert r0["angleDeg"] == pytest.approx(41.9872, rel=0.01)
    assert r0["withinEnvelope"] is True


def test_fem_stm_topology_fixity_envelope() -> None:
    # Standalone fallback uses dappedEnd where unloaded/unsupported internal node C is at (350, 1450) mm.
    # Envelope [200, 500] x [1300, 1600] contains (350, 1450) -> withinEnvelope True, allowed 300 x 300 mm.
    res = features.run(
        "femStmTopology.fixityEnvelope",
        None,
        {"nodeId": "C", "xMinMm": 200, "xMaxMm": 500, "yMinMm": 1300, "yMaxMm": 1600},
    )
    assert res["problems"] == []
    assert res["summary"]["xMm"] == pytest.approx(350.0, rel=0.01)
    assert res["summary"]["yMm"] == pytest.approx(1450.0, rel=0.01)
    assert res["summary"]["withinEnvelope"] is True
    assert res["summary"]["movementAllowedXmm"] == pytest.approx(300.0, rel=0.01)
    assert res["summary"]["movementAllowedYmm"] == pytest.approx(300.0, rel=0.01)


def test_fem_stm_topology_strut_boundaries() -> None:
    # deepBeam nodes A(0,75) and B(3000,75) are outside x=[100, 2900] -> both struts outsideBounds=2
    res = features.run(
        "femStmTopology.strutBoundaries",
        None,
        {"xMinMm": 100, "xMaxMm": 2900, "yMinMm": 0, "yMaxMm": 1500},
    )
    assert res["problems"] == []
    assert res["summary"]["strutsScreened"] == 2
    assert res["summary"]["outsideBounds"] == 2


def test_fem_stm_topology_tie_constraints() -> None:
    # T1 axis = 0 deg, required = 5 deg, tolerance = 10 deg -> deviation = 5.0 deg <= 10 -> True
    res = features.run(
        "femStmTopology.tieConstraints",
        None,
        {"tieIds": "T1", "orientationDeg": 5, "toleranceDeg": 10},
    )
    assert res["problems"] == []
    r0 = res["tables"][0]["rows"][0]
    assert r0["axisDeg"] == pytest.approx(0.0, abs=1e-6)
    assert r0["deviationDeg"] == pytest.approx(5.0, rel=0.01)
    assert r0["withinTolerance"] is True


def test_fem_stm_topology_volume_target() -> None:
    # deepBeam: 2 struts of length hypot(1500, 1350) = 2018.044 mm, width=300, thickness=300
    # Concrete vol = 2 * 300 * 300 * 2018.044 * 1e-9 = 0.36325 m3 (T1 barArea=0 -> steel vol=0)
    # excess = 0.36325 - 0.40 = -0.03675 m3 -> targetSatisfied True
    res = features.run("femStmTopology.volumeTarget", None, {"targetVolumeM3": 0.40})
    assert res["problems"] == []
    assert res["summary"]["modelMaterialVolumeM3"] == pytest.approx(0.36325, rel=0.01)
    assert res["summary"]["excessVolumeM3"] == pytest.approx(-0.03675, rel=0.02)
    assert res["summary"]["targetSatisfied"] is True

"""Independent known-answer tests for FEM Nonlinear, Design Optimisation, Pushover Target, and STM calculators."""

from __future__ import annotations

import math

import pytest

from saengine import features


def _row_by(res: dict, key: str, value: object, table_index: int = 0) -> dict:
    for row in res["tables"][table_index]["rows"]:
        if row[key] == value:
            return row
    raise AssertionError(f"No row with {key}={value!r} in {res['tables'][table_index]['rows']}")


# ── Nonlinear (fem_nonlinear.py: 15) ─────────────────────────────────────────────────────────────


def test_fem_nonlinear_arc_length_method() -> None:
    res = features.run("femNonlinear.arcLengthMethod", None, {"arcRadius": 0.05, "psi": 0.5})
    assert res["problems"] == []
    assert res["summary"]["arcRadius"] == pytest.approx(0.05, rel=0.01)
    assert res["summary"]["psi"] == pytest.approx(0.5, rel=0.01)


def test_fem_nonlinear_buckling_analysis() -> None:
    # B2 = 1 / (1 - 1 / 5.0) = 1.25; lambda_cr = 5.0 < 10.0 -> requiresSecondOrder True
    res = features.run("femNonlinear.bucklingAnalysis", None, {"elasticPcrRatio": 5.0})
    assert res["problems"] == []
    assert res["summary"]["amplifierB2"] == pytest.approx(1.25, rel=0.01)
    assert res["summary"]["requiresSecondOrder"] is True


def test_fem_nonlinear_concrete_cracking() -> None:
    # fc = 36 MPa -> sqrt(36) = 6.0
    # ft = 0.62 * 6 = 3.72 MPa; Ec = 4700 * 6 = 28200 MPa; Ets = 0.1 * Ec = 2820 MPa
    # eps_cr = 3.72 / 28200 = 0.0001319 (rounded to 4 decimals = 0.0001 by features._clean)
    res = features.run("femNonlinear.concreteCracking", None, {"fcMpa": 36.0})
    assert res["problems"] == []
    assert res["summary"]["tensileStrengthMpa"] == pytest.approx(3.72, rel=0.01)
    assert res["summary"]["softeningEtsMpa"] == pytest.approx(2820.0, rel=0.01)
    assert res["summary"]["crackingStrain"] == pytest.approx(0.0001319, abs=1e-4)


def test_fem_nonlinear_crushing_limit() -> None:
    # K = 1 + 0.015 * 400 / 36 = 1.1667; f'cc = 1.1667 * 36 = 42.0 MPa
    # eps_cu = max(0.004 + 0.9 * 0.015 * 400 / 300, 0.006) = 0.022
    res = features.run(
        "femNonlinear.crushingLimit",
        None,
        {"fcMpa": 36.0, "confinementRatio": 0.015, "fyhMpa": 400.0},
    )
    assert res["problems"] == []
    assert res["summary"]["confinementFactorK"] == pytest.approx(1.1667, rel=0.01)
    assert res["summary"]["confinedStrengthMpa"] == pytest.approx(42.0, rel=0.01)
    assert res["summary"]["crushingStrain"] == pytest.approx(0.022, rel=0.01)


def test_fem_nonlinear_hinge_properties() -> None:
    # 16 * 8 = 128 core concrete fibres
    res = features.run("femNonlinear.hingeProperties", None, {"fibersDepth": 16, "fibersWidth": 8})
    assert res["problems"] == []
    assert res["summary"]["coreFibers"] == 128


def test_fem_nonlinear_imperfections() -> None:
    # e0 = 4000 / 800 = 5.0 mm; Delta0 = 4000 / 400 = 10.0 mm
    res = features.run(
        "femNonlinear.imperfections",
        None,
        {"storeyHeightMm": 4000.0, "bowDenominator": 800.0, "swayDenominator": 400.0},
    )
    assert res["problems"] == []
    assert res["summary"]["localBowMm"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["globalSwayMm"] == pytest.approx(10.0, rel=0.01)


def test_fem_nonlinear_line_search() -> None:
    res = features.run("femNonlinear.lineSearch", None, {"tolerance": 0.6, "maxSubIters": 12})
    assert res["problems"] == []
    assert res["summary"]["lineSearchTolerance"] == pytest.approx(0.6, rel=0.01)
    assert res["summary"]["maxTrials"] == 12


def test_fem_nonlinear_load_steps() -> None:
    # 15 + 120 = 135 total steps
    res = features.run("femNonlinear.loadSteps", None, {"gravitySteps": 15, "lateralSteps": 120})
    assert res["problems"] == []
    assert res["summary"]["totalSteps"] == 135


def test_fem_nonlinear_nonlinear_settings() -> None:
    res = features.run(
        "femNonlinear.nonlinearSettings",
        None,
        {"maxIterations": 80, "tolDisp": 0.001, "algorithm": "ModifiedNewton"},
    )
    assert res["problems"] == []
    assert res["summary"]["algorithm"] == "ModifiedNewton"
    assert res["summary"]["maxIterations"] == 80
    assert res["summary"]["tolerance"] == pytest.approx(0.001, rel=0.01)


def test_fem_nonlinear_plastic_rotation() -> None:
    # DCR = 0.020 / 0.025 = 0.80 <= 1.0 -> passes True
    res = features.run(
        "femNonlinear.plasticRotation",
        None,
        {"demandRad": 0.02, "limitRad": 0.025},
    )
    assert res["problems"] == []
    assert res["summary"]["dcr"] == pytest.approx(0.80, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_nonlinear_pushover_case() -> None:
    res = features.run(
        "femNonlinear.pushoverCase",
        None,
        {"direction": "Y+", "targetDriftRatio": 0.05, "steps": 80},
    )
    assert res["problems"] == []
    assert res["summary"]["direction"] == "Y+"
    assert res["summary"]["targetDrift"] == pytest.approx(0.05, rel=0.01)
    assert res["summary"]["steps"] == 80


def test_fem_nonlinear_redistribution() -> None:
    # delta = 1 - 20/100 = 0.80; midspan increase = 0.5 * 20 = 10%
    res = features.run("femNonlinear.redistribution", None, {"momentRedistPct": 20.0})
    assert res["problems"] == []
    assert res["summary"]["momentMultiplier"] == pytest.approx(0.80, rel=0.01)
    assert res["tables"][0]["rows"][0]["midspanIncreasePct"] == pytest.approx(10.0, rel=0.01)


def test_fem_nonlinear_steel_yielding() -> None:
    # Es = 200,000 MPa -> eps_y = 500 / 200000 = 0.0025; b*Es = 0.02 * 200000 = 4000.0 MPa
    res = features.run(
        "femNonlinear.steelYielding",
        None,
        {"fyMpa": 500.0, "hardeningRatio": 0.02},
    )
    assert res["problems"] == []
    assert res["summary"]["yieldStrain"] == pytest.approx(0.0025, rel=0.01)
    assert res["summary"]["postYieldModulusMpa"] == pytest.approx(4000.0, rel=0.01)


def test_fem_nonlinear_step_control() -> None:
    # nominalSteps = ceil(240 / 8) = 30; adaptiveSubstep=False -> minSubstep = 8.0 mm
    res = features.run(
        "femNonlinear.stepControl",
        None,
        {"targetDispMm": 240.0, "incrementMm": 8.0, "adaptiveSubstep": False},
    )
    assert res["problems"] == []
    assert res["summary"]["nominalSteps"] == 30
    assert res["summary"]["minSubstepMm"] == pytest.approx(8.0, rel=0.01)


def test_fem_nonlinear_tension_stiffening() -> None:
    # At eps/eps_cr = 2.0: retained share = exp(-0.4 * (2 - 1)) = exp(-0.4) = 0.67032
    # avg stress = 3.2 * 0.67032 = 2.1450 MPa
    res = features.run(
        "femNonlinear.tensionStiffening",
        None,
        {"ftMpa": 3.2, "rhoEff": 0.02},
    )
    assert res["problems"] == []
    assert res["summary"]["crackingStressMpa"] == pytest.approx(3.2, rel=0.01)
    row_2 = _row_by(res, "strainMultCr", 2.0)
    assert row_2["retainedStressShare"] == pytest.approx(math.exp(-0.4), rel=0.01)
    assert row_2["avgStressMpa"] == pytest.approx(3.2 * math.exp(-0.4), rel=0.01)


# ── Design Optimisation (fem_design_optimisation.py: 14) ─────────────────────────────────────────


def test_fem_design_optimisation_bar_selection() -> None:
    # Required As = 1500 mm2 in 350 mm beam width (40 mm inset):
    # 2Ø32 gives 2 * pi * 16^2 = 1608.4954 mm2 (7.23% excess) in 1 row with clear spacing 206 mm.
    res = features.run(
        "femDesignOptimisation.barSelection",
        None,
        {"requiredAsMm2": 1500.0, "beamWidthMm": 350.0},
    )
    assert res["problems"] == []
    assert res["summary"]["lightestAreaMm2"] == pytest.approx(1608.4954, rel=0.01)
    assert res["tables"][0]["rows"][0]["bars"] == "2Ø32"


def test_fem_design_optimisation_cost_rates() -> None:
    # Reference 300x500 mm RC beam:
    # Concrete = 0.3 * 0.5 * 120 = 18.0; Formwork = (0.3 + 2*0.5) * 25 = 32.5; Rebar = 22 * 1.2 = 26.4
    # Total = 18.0 + 32.5 + 26.4 = 76.9 USD/m
    res = features.run(
        "femDesignOptimisation.costRates",
        None,
        {"concreteRatePerM3": 120.0, "rebarRatePerKg": 1.2, "formworkRatePerM2": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalCostPerM"] == pytest.approx(76.9, rel=0.01)


def test_fem_design_optimisation_discrete_opt() -> None:
    # Lightest catalog section with A >= 3500 mm2 and Ix >= 8e7 mm4 is IPE 300:
    # A = 5381.2 mm2, Ix = 83.56e6 mm4, mass = 5381.2 * 7850e-6 = 42.24 kg/m.
    res = features.run(
        "femDesignOptimisation.discreteOpt",
        None,
        {"requiredAreaMm2": 3500.0, "requiredIxMm4": 80000000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["lightestSection"] == "IPE 300"
    assert res["summary"]["lightestMassKgPerM"] == pytest.approx(42.2424, rel=0.01)


def test_fem_design_optimisation_drift_constraint() -> None:
    # Stiffness multiplier = 0.024 / 0.016 = 1.50 > 1.0 -> satisfied False
    res = features.run(
        "femDesignOptimisation.driftConstraint",
        None,
        {"currentDrift": 0.024, "limitDrift": 0.016},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredStiffnessMultiplier"] == pytest.approx(1.50, rel=0.01)
    assert res["summary"]["satisfied"] is False


def test_fem_design_optimisation_frequency_bound() -> None:
    # K_req / K_cur = (4.5 / 3.0)^2 = 1.5^2 = 2.25 > 1.0 -> satisfied False
    res = features.run(
        "femDesignOptimisation.frequencyBound",
        None,
        {"currentFreqHz": 3.0, "minFreqHz": 4.5},
    )
    assert res["problems"] == []
    assert res["summary"]["requiredStiffnessRatio"] == pytest.approx(2.25, rel=0.01)
    assert res["summary"]["satisfied"] is False


def test_fem_design_optimisation_genetic_algorithm() -> None:
    # Trace at g = 10: 10000 * (0.78 + 0.22 * exp(-0.25 * 10)) = 7980.587 kg
    # minDiscreteAreaMm2 = 3 * 600 = 1800 mm2
    res = features.run(
        "femDesignOptimisation.geneticAlgorithm",
        None,
        {"population": 30, "generations": 10, "targetMassKg": 10000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["finalMassKg"] == pytest.approx(7980.587, rel=0.01)
    assert res["summary"]["minDiscreteAreaMm2"] == pytest.approx(1800.0, rel=0.01)


def test_fem_design_optimisation_gradient_solver() -> None:
    # Exact target = 600,000 / 200 = 3000.0 mm2
    # 5 damped OC iterations A_{k+1} = A_k * (600e3 / (A_k * 200))^0.8 from A0=4000 -> 3000.2762 mm2
    res = features.run(
        "femDesignOptimisation.gradientSolver",
        None,
        {"loadKn": 600.0, "allowableStressMpa": 200.0, "initialAreaMm2": 4000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["targetAreaMm2"] == pytest.approx(3000.0, rel=0.01)
    assert res["summary"]["convergedAreaMm2"] == pytest.approx(3000.2762, rel=0.01)


def test_fem_design_optimisation_layout_opt() -> None:
    # H = w * L^2 / (8 * h) = 25 * 24^2 / (8 * 3) = 14400 / 24 = 600.0 kN
    # At x = 0: slope = 4*3/24 = 0.5 -> N = 600 * sqrt(1 + 0.25) = 670.8204 kN
    res = features.run(
        "femDesignOptimisation.layoutOpt",
        None,
        {"spanM": 24.0, "riseM": 3.0, "udlKnPerM": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["horizontalThrustKn"] == pytest.approx(600.0, rel=0.01)
    assert res["tables"][0]["rows"][0]["axialCompressionKn"] == pytest.approx(670.8204, rel=0.01)
    assert _row_by(res, "xM", 12.0)["yOptimalM"] == pytest.approx(3.0, rel=0.01)


def test_fem_design_optimisation_material_minimizer() -> None:
    # 1 / (k + 1)^1.6 >= 0.05 -> (k + 1) <= 20^(1/1.6) = 6.502 -> 6 retained, 10 pruned out of 16
    res = features.run(
        "femDesignOptimisation.materialMinimizer",
        None,
        {"elementCount": 16, "cutoffShare": 0.05},
    )
    assert res["problems"] == []
    assert res["summary"]["retainedMembers"] == 6
    assert res["summary"]["prunedMembers"] == 10


def test_fem_design_optimisation_minimise_weight() -> None:
    # Rebar = (2500 / 1e6) * 5 * 7850 = 98.125 kg; Concrete = (200000 / 1e6) * 5 * 2400 = 2400.0 kg
    # steelRatio = 2500 / 200000 = 0.0125
    res = features.run(
        "femDesignOptimisation.minimiseWeight",
        None,
        {"concreteAreaMm2": 200000.0, "steelAreaMm2": 2500.0, "lengthM": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["rebarMassKg"] == pytest.approx(98.125, rel=0.01)
    assert res["summary"]["concreteMassKg"] == pytest.approx(2400.0, rel=0.01)
    assert res["summary"]["steelRatio"] == pytest.approx(0.0125, rel=0.01)


def test_fem_design_optimisation_slenderness_limit() -> None:
    # r_min = 4500 / 150 = 30.0 mm
    res = features.run(
        "femDesignOptimisation.slendernessLimit",
        None,
        {"effectiveLengthMm": 4500.0, "maxSlenderness": 150.0},
    )
    assert res["problems"] == []
    assert res["summary"]["minRadiusGyrationMm"] == pytest.approx(30.0, rel=0.01)


def test_fem_design_optimisation_spacing_limits() -> None:
    # s_min = max(40, 1.5*25, 4/3*25) = 40.0 mm
    # max_per_row = int((400 - 80 + 40) // (25 + 40)) = 360 // 65 = 5
    res = features.run(
        "femDesignOptimisation.spacingLimits",
        None,
        {"barDiaMm": 25.0, "aggregateMm": 25.0, "beamWidthMm": 400.0},
    )
    assert res["problems"] == []
    assert res["summary"]["minClearSpacingMm"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["maxBarsPerRow"] == 5


def test_fem_design_optimisation_target_ratio() -> None:
    # (0.64 / 0.80)^(1/3) = 0.8^(1/3) = 0.928318
    res = features.run(
        "femDesignOptimisation.targetRatio",
        None,
        {"targetDcr": 0.80, "currentDcr": 0.64},
    )
    assert res["problems"] == []
    assert res["summary"]["estimatedDepthScale"] == pytest.approx(0.9283, rel=0.01)


def test_fem_design_optimisation_truss_topology() -> None:
    # M_mid = 160 * 16 / 4 = 640 kN.m -> chord = 640 / 2.0 = 320.0 kN
    # dx = 16 / 8 = 2.0 m, L_diag = hypot(2.0, 2.0) = 2.8284 m -> diag F = 0.5 * 160 * (2.8284/2) = 113.1371 kN
    res = features.run(
        "femDesignOptimisation.trussTopology",
        None,
        {"spanM": 16.0, "depthM": 2.0, "panels": 8, "pointLoadKn": 160.0},
    )
    assert res["problems"] == []
    assert res["summary"]["spanOverDepth"] == pytest.approx(8.0, rel=0.01)
    assert res["summary"]["maxChordForceKn"] == pytest.approx(320.0, rel=0.01)
    assert res["summary"]["maxDiagonalForceKn"] == pytest.approx(113.1371, rel=0.01)


# ── Pushover Target (fem_pushover_target.py: 12) ─────────────────────────────────────────────────


def test_fem_pushover_target_compute_target() -> None:
    # Default pack (BNBC 2020, SD: S=1.35, TB=0.2, TC=0.8, TD=2.0; Z=0.20, R=1, I=1):
    # Sa(0.70) = (2/3) * 0.20 * 2.5 * 1.35 = 0.45 g.
    # Bilinear fit up to converged target ~78.4 mm yields Vy=498.71 kN, Ke=k1=320/0.015 -> Te = T1 = 0.70 s.
    # Rd = 0.45 / (498.71 / 6500) = 5.865; C1 = (1 + (5.865 - 1)*(0.8/0.7)) / 5.865 = 1.1186.
    # dt = 1.28 * 1.1186 * 0.45 * 9806.65 * (0.7 / (2*pi))^2 = 78.418 mm.
    res = features.run(
        "femPushoverTarget.computeTarget",
        None,
        {
            "curvePairs": "0,0; 15,320; 35,540; 70,600; 130,580",
            "t1S": 0.7,
            "c0": 1.28,
            "weightKn": 6500.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["effectivePeriodS"] == pytest.approx(0.7, rel=0.01)
    assert res["summary"]["vyKn"] == pytest.approx(498.71, rel=0.01)
    assert res["summary"]["targetDispMm"] == pytest.approx(78.418, rel=0.01)


def test_fem_pushover_target_damping_reduction() -> None:
    # B(beta=20%) = 4.0 / (5.6 - ln(20)) = 4.0 / (5.6 - 2.99573) = 1.5359
    res = features.run("femPushoverTarget.dampingReduction", None, {"effectiveDamping": 0.20})
    assert res["problems"] == []
    assert res["summary"]["dampingReductionB"] == pytest.approx(1.5359, rel=0.01)


def test_fem_pushover_target_drift_limit() -> None:
    # 20.0 m * 0.015 * 1000 = 300.0 mm
    res = features.run(
        "femPushoverTarget.driftLimit",
        None,
        {"buildingHeightM": 20.0, "allowableRatio": 0.015},
    )
    assert res["problems"] == []
    assert res["summary"]["allowableRoofDispMm"] == pytest.approx(300.0, rel=0.01)


def test_fem_pushover_target_drift_profile() -> None:
    # 3 storeys @ 4.0 m, quarter-sine profile at 120 mm roof disp:
    # Level 1: 120 * sin(pi / 6) = 60.0 mm -> storey drift = 60 / 4000 = 0.015 (maximum)
    res = features.run(
        "femPushoverTarget.driftProfile",
        None,
        {"targetRoofDispMm": 120.0, "storeys": 3, "storeyHeightM": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["maxStoreyDrift"] == pytest.approx(0.015, rel=0.01)


def test_fem_pushover_target_effective_mass() -> None:
    # W* = 10000 * 0.75 = 7500 kN; M* = 7500 / 9.80665 = 764.7872 t
    res = features.run(
        "femPushoverTarget.effectiveMass",
        None,
        {"totalWeightKn": 10000.0, "modalShare": 0.75},
    )
    assert res["problems"] == []
    assert res["summary"]["effectiveWeightKn"] == pytest.approx(7500.0, rel=0.01)
    assert res["summary"]["effectiveMassTonnes"] == pytest.approx(764.7872, rel=0.01)


def test_fem_pushover_target_height_factor() -> None:
    # Inverted triangular 6 storeys: C0 = 3*N / (2*N + 1) = 18 / 13 = 1.3846
    res = features.run("femPushoverTarget.heightFactor", None, {"storeys": 6})
    assert res["problems"] == []
    assert res["summary"]["c0Factor"] == pytest.approx(18.0 / 13.0, rel=0.01)


def test_fem_pushover_target_manual_override() -> None:
    res = features.run(
        "femPushoverTarget.manualOverride",
        None,
        {"manualTargetMm": 180.0, "justification": "Sensitivity check"},
    )
    assert res["problems"] == []
    assert res["summary"]["overrideTargetMm"] == pytest.approx(180.0, rel=0.01)


def test_fem_pushover_target_mdof_conversion() -> None:
    # 120 * 1.25 = 150.0 mm
    res = features.run("femPushoverTarget.mdofConversion", None, {"sdofDispMm": 120.0, "c0": 1.25})
    assert res["problems"] == []
    assert res["summary"]["mdofRoofDispMm"] == pytest.approx(150.0, rel=0.01)


def test_fem_pushover_target_mode_shape() -> None:
    # Quarter-sine 4 storeys: phi = [sin(pi/8), sin(pi/4), sin(3pi/8), 1.0]
    # sum(phi) = 3.01367; sum(phi^2) = 2.5 -> C0 = 3.01367 / 2.5 = 1.20547
    res = features.run("femPushoverTarget.modeShape", None, {"shape": "sine", "storeys": 4})
    assert res["problems"] == []
    assert res["summary"]["c0Factor"] == pytest.approx(1.2055, rel=0.01)


def test_fem_pushover_target_sensitivity_study() -> None:
    # Nominal (T=0.8 s): 1.3 * 0.5 * 9806.65 * (0.8 / (2*pi))^2 = 103.3366 mm
    # Range (+-20% T): (1.2^2 - 0.8^2) * 103.3366 = 0.8 * 103.3366 = 82.6693 mm
    res = features.run(
        "femPushoverTarget.sensitivityStudy",
        None,
        {"baseT1S": 0.8, "saG": 0.5, "c0": 1.3},
    )
    assert res["problems"] == []
    assert res["summary"]["nominalTargetMm"] == pytest.approx(103.3366, rel=0.01)
    assert res["summary"]["rangeMm"] == pytest.approx(82.6693, rel=0.01)


def test_fem_pushover_target_strain_limits() -> None:
    # Concrete 0.008 <= 0.012 (True); Steel 0.060 > 0.050 (False)
    res = features.run(
        "femPushoverTarget.strainLimits",
        None,
        {"concreteStrain": 0.008, "steelStrain": 0.06},
    )
    assert res["problems"] == []
    assert res["summary"]["concreteOk"] is True
    assert res["summary"]["steelOk"] is False


def test_fem_pushover_target_target_audit() -> None:
    # Target = 120 * (0.9 / 0.6)^2 = 270.0 mm; 5 relaxed steps (0.65 old + 0.35 target):
    # d5 = 270 - (270 - 120) * 0.65^5 = 252.5956 mm; resid5 = 0.35 * 150 * 0.65^4 = 9.3716 mm
    res = features.run(
        "femPushoverTarget.targetAudit",
        None,
        {"initialGuessMm": 120.0, "t1S": 0.6, "teS": 0.9},
    )
    assert res["problems"] == []
    assert res["summary"]["convergedDeltaMm"] == pytest.approx(252.5956, rel=0.01)
    assert res["summary"]["finalResidualMm"] == pytest.approx(9.3716, rel=0.01)


# ── STM Regions (fem_stm_regions.py: 9) ──────────────────────────────────────────────────────────
# Standalone deepBeam template: span=3000, depth=1500, thickness=300, load=1000 kN, cover=75,
# fc=28, fy=420, phi=0.75; nodes A(0,75), B(3000,75), C(1500,1425); T1 force = 555.56 kN.


def test_fem_stm_regions_boundary_trimming() -> None:
    # Box [100, 2900] x [0, 1500] contains only C(1500, 1425); A and B are outside -> 2 struts cross
    res = features.run(
        "femStmRegions.boundaryTrimming",
        None,
        {"xMinMm": 100, "xMaxMm": 2900, "yMinMm": 0, "yMaxMm": 1500},
    )
    assert res["problems"] == []
    assert res["summary"]["nodesInside"] == 1
    assert res["summary"]["nodesOutside"] == 2
    assert res["summary"]["membersCrossingBoundary"] == 2


def test_fem_stm_regions_confinement_layout() -> None:
    # A_bar(12) = pi * 6^2 = 113.0973 mm2; ratio = 113.0973 / (300 * 120) = 0.003142 >= 0.003 (pack webRatio)
    res = features.run(
        "femStmRegions.confinementLayout",
        None,
        {"barDiameterMm": 12, "spacingMm": 120},
    )
    assert res["problems"] == []
    assert res["summary"]["providedRatio"] == pytest.approx(0.003142, rel=0.02)
    assert res["summary"]["passes"] is True


def test_fem_stm_regions_d_region_limit() -> None:
    # Pack dRegionDepth = 1.0 -> extent = 1500 mm -> [250, 1750]
    res = features.run("femStmRegions.dRegionLimit", None, {"discontinuityXmm": 250})
    assert res["problems"] == []
    assert res["summary"]["startXmm"] == pytest.approx(250.0, rel=0.01)
    assert res["summary"]["endXmm"] == pytest.approx(1750.0, rel=0.01)
    assert res["summary"]["extentMm"] == pytest.approx(1500.0, rel=0.01)


def test_fem_stm_regions_discontinuity_region() -> None:
    # 1800 mm > 1500 mm pack extent -> coveredByPackExtent False
    res = features.run("femStmRegions.discontinuityRegion", None, {"regionDepthMm": 1800})
    assert res["problems"] == []
    assert res["summary"]["packExtentMm"] == pytest.approx(1500.0, rel=0.01)
    assert res["summary"]["coveredByPackExtent"] is False


def test_fem_stm_regions_edge_reinforcement() -> None:
    # Projected node box: span = 3000, depth = 1425 - 75 = 1350 -> perimeter = 2*(3000+1350) = 8700 mm
    # count = ceil(8700 / 250) = 35; totalSteel = 35 * pi * 8^2 = 7037.17 mm2
    res = features.run(
        "femStmRegions.edgeReinforcement",
        None,
        {"perimeterBarSpacingMm": 250, "barDiameterMm": 16},
    )
    assert res["problems"] == []
    assert res["summary"]["perimeterMm"] == pytest.approx(8700.0, rel=0.01)
    assert res["summary"]["barCount"] == 35
    assert res["summary"]["totalSteelMm2"] == pytest.approx(7037.1675, rel=0.01)


def test_fem_stm_regions_fan_detailing() -> None:
    # T1 force = 555.556 kN; As_req = 555555.6 / (0.75 * 420) = 1763.67 mm2
    # A_bar(20) = 314.16 mm2 -> 6 bars; clear width = 600 - 2*50 = 500 mm >= 6*20 = 120 -> fits True
    res = features.run(
        "femStmRegions.fanDetailing",
        None,
        {"availableWidthMm": 600, "coverMm": 50, "barDiameterMm": 20},
    )
    assert res["problems"] == []
    assert res["summary"]["totalTieForceKn"] == pytest.approx(555.56, rel=0.01)
    r0 = res["tables"][0]["rows"][0]
    assert r0["barCount"] == 6
    assert r0["fits"] is True


def test_fem_stm_regions_fan_reinforcement() -> None:
    # As_req = 1763.67 mm2; barLegs = ceil(1763.67 / 200) = 9 -> provided = 1800 mm2
    res = features.run("femStmRegions.fanReinforcement", None, {"barAreaMm2": 200})
    assert res["problems"] == []
    r0 = res["tables"][0]["rows"][0]
    assert r0["requiredSteelMm2"] == pytest.approx(1763.67, rel=0.01)
    assert r0["barLegs"] == 9
    assert r0["providedSteelMm2"] == pytest.approx(1800.0, rel=0.01)


def test_fem_stm_regions_opening_region() -> None:
    # Opening box [1300, 1700] x [650, 950] misses bottom tie T1 (y=75) and crosses struts S2, S3 -> 2
    res = features.run(
        "femStmRegions.openingRegion",
        None,
        {"openingXmm": 1500, "openingYmm": 800, "openingWidthMm": 400, "openingHeightMm": 300},
    )
    assert res["problems"] == []
    assert res["summary"]["openingMembers"] == 2
    assert res["summary"]["reviewedMembers"] == 3


def test_fem_stm_regions_region_rebar() -> None:
    # As_req = 1763.67 mm2; A_bar(25) = 490.87 mm2 -> ceil(1763.67 / 490.87) = 4 bars
    res = features.run("femStmRegions.regionRebar", None, {"tieBarDiameterMm": 25})
    assert res["problems"] == []
    r0 = res["tables"][0]["rows"][0]
    assert r0["requiredAreaMm2"] == pytest.approx(1763.67, rel=0.01)
    assert r0["barCount"] == 4


# ── STM Nodes (fem_stm_nodes.py: 7) ──────────────────────────────────────────────────────────────


def test_fem_stm_nodes_bearing_plate() -> None:
    # Node B (CCT: beta=0.8): fce = 0.85 * 0.8 * 28 = 19.04 MPa; R = 500 kN
    # reqArea = 500e3 / (0.75 * 19.04) = 35014.0 mm2 -> reqLength = 35014.0 / 250 = 140.056 mm
    res = features.run("femStmNodes.bearingPlate", None, {"nodeId": "B", "plateWidthMm": 250})
    assert res["problems"] == []
    assert res["summary"]["nodeType"] == "CCT"
    assert res["summary"]["bearingForceKn"] == pytest.approx(500.0, rel=0.01)
    assert res["summary"]["requiredBearingLengthMm"] == pytest.approx(140.056, rel=0.01)


def test_fem_stm_nodes_bursting_steel() -> None:
    # Node A (R = 500 kN): bursting = 0.2 * 500 = 100 kN -> As = 100e3 / (0.75 * 420) = 317.46 mm2
    # A_bar(16) = 201.06 mm2 -> 2 bars
    res = features.run(
        "femStmNodes.burstingSteel",
        None,
        {"burstingShare": 0.2, "barDiameterMm": 16},
    )
    assert res["problems"] == []
    row_a = _row_by(res, "nodeId", "A")
    assert row_a["burstingForceKn"] == pytest.approx(100.0, rel=0.01)
    assert row_a["requiredSteelMm2"] == pytest.approx(317.4603, rel=0.01)
    assert row_a["barCount"] == 2


def test_fem_stm_nodes_effective_strength() -> None:
    # CCC (pack betaCCC = 1.0, effective = 0.85): fce = 0.85 * 1.0 * 35 = 29.75 MPa
    res = features.run("femStmNodes.effectiveStrength", None, {"fcMpa": 35, "nodeType": "CCC"})
    assert res["problems"] == []
    assert res["summary"]["betaN"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["effectiveStrengthMpa"] == pytest.approx(29.75, rel=0.01)


def test_fem_stm_nodes_extended_zone() -> None:
    # Node C is at (1500, 1425) with 0 anchored ties -> +-250 mm box is [1250, 1750] x [1175, 1675]
    res = features.run("femStmNodes.extendedZone", None, {"nodeId": "C", "extensionMm": 250})
    assert res["problems"] == []
    assert res["summary"]["xminMm"] == pytest.approx(1250.0, rel=0.01)
    assert res["summary"]["xmaxMm"] == pytest.approx(1750.0, rel=0.01)
    assert res["summary"]["yminMm"] == pytest.approx(1175.0, rel=0.01)
    assert res["summary"]["ymaxMm"] == pytest.approx(1675.0, rel=0.01)
    assert res["summary"]["anchoredTies"] == 0


def test_fem_stm_nodes_node_confinement() -> None:
    # A_bar(12) = 113.0973 mm2; ratio = 113.0973 / (300 * 100) = 0.00377 >= 0.003 -> passes True
    res = features.run(
        "femStmNodes.nodeConfinement",
        None,
        {"barDiameterMm": 12, "spacingMm": 100},
    )
    assert res["problems"] == []
    assert res["summary"]["confinementRatio"] == pytest.approx(0.00377, rel=0.02)
    assert res["summary"]["passes"] is True


def test_fem_stm_nodes_principal_stress_check() -> None:
    # Control-zone area = 400 * 300 = 120,000 mm2.
    # At node A: T1 (+555.56 kN, c=1, s=0 -> sxx=+4.6296 MPa) and
    # S2 (-747.42 kN, c=0.7433, s=0.6690 -> sigma=-6.2285 MPa -> sxx=-3.4412, syy=-2.7873, txy=-3.0970).
    # Net: sxx=1.1884, syy=-2.7873, txy=-3.0970 -> mean=-0.7995, R=3.6802 MPa
    # sigma1 = 2.8807 MPa, sigma2 = -4.4796 MPa, tauMax = 3.6802 MPa.
    res = features.run("femStmNodes.principalStressCheck", None, {"nodeZoneDepthMm": 400})
    assert res["problems"] == []
    row_a = _row_by(res, "nodeId", "A")
    assert row_a["sigma1Mpa"] == pytest.approx(2.8807, rel=0.01)
    assert row_a["sigma2Mpa"] == pytest.approx(-4.4796, rel=0.01)
    assert row_a["tauMaxMpa"] == pytest.approx(3.6802, rel=0.01)


def test_fem_stm_nodes_spalling_steel() -> None:
    # Node A (R = 500 kN): spalling = 0.15 * 500 = 75 kN -> As = 75e3 / (0.75 * 420) = 238.095 mm2
    # A_bar(12) = 113.097 mm2 -> 3 bars
    res = features.run(
        "femStmNodes.spallingSteel",
        None,
        {"spallingShare": 0.15, "barDiameterMm": 12},
    )
    assert res["problems"] == []
    row_a = _row_by(res, "nodeId", "A")
    assert row_a["surfaceForceKn"] == pytest.approx(75.0, rel=0.01)
    assert row_a["requiredSteelMm2"] == pytest.approx(238.0952, rel=0.01)
    assert row_a["barCount"] == 3

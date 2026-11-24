"""Independent known-answer tests for FEM Hinges, CFD Solver, Dynamics, Pushover, STM Load Paths, and Capacity."""

from __future__ import annotations

from pathlib import Path

import pytest

from saengine import features
from saengine.design import stm_model
from saengine.library.strut_and_tie import StrutAndTieFile


def _row_by(res: dict, key: str, value: object, table_index: int = 0) -> dict:
    for row in res["tables"][table_index]["rows"]:
        if row[key] == value:
            return row
    raise AssertionError(f"No row with {key}={value!r} in {res['tables'][table_index]['rows']}")


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


# ── Pushover Hinges (fem_hinges.py: 15) ──────────────────────────────────────────────────────────


def test_fem_hinges_acceptance_criteria() -> None:
    # demand = 0.012 rad: > IO (0.006) and <= LS (0.016) -> state = "LS", passesLS = True
    # DCR_IO = 0.012 / 0.006 = 2.0; DCR_LS = 0.012 / 0.016 = 0.75; DCR_CP = 0.012 / 0.024 = 0.50
    res = features.run(
        "femHinges.acceptanceCriteria",
        None,
        {
            "plasticDemandRad": 0.012,
            "ioLimitRad": 0.006,
            "lsLimitRad": 0.016,
            "cpLimitRad": 0.024,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["state"] == "LS"
    assert res["summary"]["passesLS"] is True
    assert _row_by(res, "level", "IO")["dcr"] == pytest.approx(2.0, rel=0.01)
    assert _row_by(res, "level", "LS")["dcr"] == pytest.approx(0.75, rel=0.01)


def test_fem_hinges_auto_placement() -> None:
    # startXi = 0.08, endXi = 1.0 - 0.08 = 0.92
    res = features.run("femHinges.autoPlacement", None, {"relativePositions": 0.08})
    assert res["problems"] == []
    assert res["summary"]["startXi"] == pytest.approx(0.08, rel=0.01)
    assert res["summary"]["endXi"] == pytest.approx(0.92, rel=0.01)


def test_fem_hinges_backbone_curve() -> None:
    # Normalized backbone ordinates: B (0, 1.0), C (0.025, 1.05), D (0.025, 0.25), E (0.045, 0.25)
    res = features.run(
        "femHinges.backboneCurve",
        None,
        {"myKnm": 300.0, "aRad": 0.025, "bRad": 0.045, "cRatio": 0.25},
    )
    assert res["problems"] == []
    assert res["summary"]["yieldMomentKnm"] == pytest.approx(300.0, rel=0.01)
    assert res["summary"]["cappingRotRad"] == pytest.approx(0.025, rel=0.01)
    assert res["summary"]["collapseRotRad"] == pytest.approx(0.045, rel=0.01)
    assert _row_by(res, "segment", "E (failure)")["mOverMy"] == pytest.approx(0.25, rel=0.01)


def test_fem_hinges_cyclic_degradation() -> None:
    # Retained share after N = 3 cycles at lambda = 0.10: (1 - 0.10)^3 = 0.729 -> 72.9%
    # Final moment = 400.0 * 0.729 = 291.6 kN·m
    res = features.run(
        "femHinges.cyclicDegradation",
        None,
        {"cycles": 3, "degradationRate": 0.10, "initialMomentKnm": 400.0},
    )
    assert res["problems"] == []
    assert res["summary"]["cycles"] == 3
    assert res["summary"]["finalRetainedPct"] == pytest.approx(72.9, rel=0.01)
    assert res["summary"]["finalMomentKnm"] == pytest.approx(291.6, rel=0.01)


def test_fem_hinges_define_hinge() -> None:
    # Point C: theta = 0.004 + 0.020 = 0.024 rad, M = 1.05 * 240 = 252.0 kN·m
    # Point E: theta = 0.004 + 0.040 = 0.044 rad, M = 0.25 * 240 = 60.0 kN·m
    res = features.run(
        "femHinges.defineHinge",
        None,
        {
            "component": "rcColumn",
            "myKnm": 240.0,
            "thetaY": 0.004,
            "aPlasticRad": 0.020,
            "bPlasticRad": 0.040,
            "residualShare": 0.25,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["yieldMomentKnm"] == pytest.approx(240.0, rel=0.01)
    assert res["summary"]["ultimatePlasticRad"] == pytest.approx(0.040, rel=0.01)
    pt_c = _row_by(res, "point", "C (Peak/Drop)")
    assert pt_c["rotRad"] == pytest.approx(0.024, rel=0.01)
    assert pt_c["momentKnm"] == pytest.approx(252.0, rel=0.01)
    pt_e = _row_by(res, "point", "E (Loss)")
    assert pt_e["rotRad"] == pytest.approx(0.044, rel=0.01)
    assert pt_e["momentKnm"] == pytest.approx(60.0, rel=0.01)


def test_fem_hinges_end_hinges() -> None:
    # Lp = 0.5 * 600 = 300 mm each end -> elastic mid-span = 5000 - 2 * 300 = 4400.0 mm
    res = features.run("femHinges.endHinges", None, {"depthMm": 600.0, "spanMm": 5000.0})
    assert res["problems"] == []
    assert res["summary"]["elasticMidSpanMm"] == pytest.approx(4400.0, rel=0.01)
    assert res["summary"]["validClearance"] is True
    assert res["tables"][0]["rows"][0]["elasticMidSpanMm"] == pytest.approx(4400.0, rel=0.01)


def test_fem_hinges_force_check() -> None:
    # DCR = 180 / 240 = 0.75 <= 1.0 -> passes True
    res = features.run(
        "femHinges.forceCheck", None, {"demandShearKn": 180.0, "shearCapacityKn": 240.0}
    )
    assert res["problems"] == []
    assert res["summary"]["shearDcr"] == pytest.approx(0.75, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_hinges_hinge_length() -> None:
    # Paulay-Priestley with default fy = 420 MPa:
    # Lp = max(0.08 * 3000 + 0.022 * 420 * 25, 0.044 * 420 * 25) = max(240 + 231, 462) = 471.0 mm
    res = features.run(
        "femHinges.hingeLength", None, {"shearSpanMm": 3000.0, "barDiameterMm": 25.0}
    )
    assert res["problems"] == []
    assert res["summary"]["plasticHingeLengthMm"] == pytest.approx(471.0, rel=0.01)


def test_fem_hinges_hinge_overrides() -> None:
    res = features.run(
        "femHinges.hingeOverrides",
        None,
        {
            "memberId": "C2",
            "aOverrideRad": 0.035,
            "ioLimitRad": 0.006,
            "lsLimitRad": 0.018,
            "cpLimitRad": 0.032,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["member"] == "C2"
    assert res["summary"]["aLimitRad"] == pytest.approx(0.035, rel=0.01)
    assert _row_by(res, "limit", "LS")["rotRad"] == pytest.approx(0.018, rel=0.01)


def test_fem_hinges_hinge_plot() -> None:
    # 5 points: (0, 0), (0.006, 250), (0.030, 262.5), (0.030, 50.0), (0.042, 50.0)
    res = features.run(
        "femHinges.hingePlot",
        None,
        {"myKnm": 250.0, "thetaY": 0.006, "aRad": 0.024},
    )
    assert res["problems"] == []
    assert res["summary"]["points"] == 5
    assert res["summary"]["myKnm"] == pytest.approx(250.0, rel=0.01)
    rows = res["tables"][0]["rows"]
    assert rows[2]["thetaRad"] == pytest.approx(0.030, rel=0.01)
    assert rows[2]["momentKnm"] == pytest.approx(262.5, rel=0.01)
    assert rows[4]["thetaRad"] == pytest.approx(0.042, rel=0.01)
    assert rows[4]["momentKnm"] == pytest.approx(50.0, rel=0.01)


def test_fem_hinges_hinge_zones() -> None:
    # Offset = 0.5 * 600 = 300 mm; critical zone = 2.0 * 600 = 1200 mm; End (j) at 4800 - 300 = 4500 mm
    res = features.run(
        "femHinges.hingeZones", None, {"memberLengthMm": 4800.0, "sectionDepthMm": 600.0}
    )
    assert res["problems"] == []
    assert res["summary"]["hingeOffsetMm"] == pytest.approx(300.0, rel=0.01)
    assert res["summary"]["criticalConfinementZoneMm"] == pytest.approx(1200.0, rel=0.01)
    assert _row_by(res, "end", "End (j)")["centreOffsetMm"] == pytest.approx(4500.0, rel=0.01)


def test_fem_hinges_rotation_check() -> None:
    # DCR = 0.015 / 0.025 = 0.60 <= 1.0 -> passes True
    res = features.run("femHinges.rotationCheck", None, {"demandRad": 0.015, "capacityRad": 0.025})
    assert res["problems"] == []
    assert res["summary"]["dcr"] == pytest.approx(0.60, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_hinges_rotation_demand() -> None:
    # theta_total = 36 / 2400 = 0.015 rad; theta_p = 0.015 - 0.005 = 0.010 rad -> hasYielded True
    res = features.run(
        "femHinges.rotationDemand",
        None,
        {"chordDispMm": 36.0, "clearLengthMm": 2400.0, "yieldRotRad": 0.005},
    )
    assert res["problems"] == []
    assert res["summary"]["totalChordRad"] == pytest.approx(0.015, rel=0.01)
    assert res["summary"]["plasticRotRad"] == pytest.approx(0.010, rel=0.01)
    assert res["summary"]["hasYielded"] is True


def test_fem_hinges_ultimate_rotation() -> None:
    # theta_y = 0.010 * 3.0 / 3 = 0.010 rad
    # theta_p = (0.070 - 0.010) * 0.50 = 0.030 rad -> theta_u = 0.010 + 0.030 = 0.040 rad
    res = features.run(
        "femHinges.ultimateRotation",
        None,
        {
            "phiYieldPerM": 0.010,
            "phiUltPerM": 0.070,
            "hingeLengthMm": 500.0,
            "shearSpanMm": 3000.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["yieldRotRad"] == pytest.approx(0.010, rel=0.01)
    assert res["summary"]["plasticCapacityRad"] == pytest.approx(0.030, rel=0.01)
    assert res["summary"]["ultimateRotRad"] == pytest.approx(0.040, rel=0.01)


def test_fem_hinges_yield_moment() -> None:
    # Cracked transformed section (default fc = 28 MPa, fy = 420 MPa, Es = 200,000 MPa):
    # Ec = 4700 * sqrt(28) = 24,870.06 MPa -> n = 8.04180
    # rho = 1600 / (350 * 500) = 0.0091429 -> rho*n = 0.073525
    # k = sqrt(0.073525^2 + 2*0.073525) - 0.073525 = 0.316931; jd = 500*(1 - k/3) = 447.1782 mm
    # My = 1600 * 420 * 447.1782 / 1e6 = 300.5037 kN·m
    # phi_y = (420 / 200,000) / (500 * (1 - 0.316931)) * 1000 = 0.006149 1/m
    res = features.run(
        "femHinges.yieldMoment",
        None,
        {"bMm": 350.0, "dMm": 500.0, "asMm2": 1600.0},
    )
    assert res["problems"] == []
    assert res["summary"]["yieldMomentKnm"] == pytest.approx(300.5037, rel=0.01)
    assert res["summary"]["yieldCurvaturePerM"] == pytest.approx(0.006149, rel=0.01)


# ── CFD Solver (fem_cfd_solver.py: 14) ───────────────────────────────────────────────────────────


def test_fem_cfd_solver_auto_tune() -> None:
    # maxNonOrthoDeg = 70 > 65 -> Conservative schedule: alphaP = 0.2, alphaU = 0.5, nonOrtho = 3
    res = features.run("femCfdSolver.autoTune", None, {"maxNonOrthoDeg": 70.0, "maxSkewness": 2.0})
    assert res["problems"] == []
    assert res["summary"]["alphaP"] == pytest.approx(0.2, rel=0.01)
    assert res["summary"]["alphaU"] == pytest.approx(0.5, rel=0.01)
    assert res["summary"]["nonOrthoCorrectors"] == 3


def test_fem_cfd_solver_cfl_adjust() -> None:
    # new_dt = 0.02 * (0.75 / 3.0) = 0.005 s
    res = features.run(
        "femCfdSolver.cflAdjust",
        None,
        {"currentCo": 3.0, "targetCo": 0.75, "currentDtS": 0.02},
    )
    assert res["problems"] == []
    assert res["summary"]["recommendedDtS"] == pytest.approx(0.005, rel=0.01)
    assert res["summary"]["targetCo"] == pytest.approx(0.75, rel=0.01)


def test_fem_cfd_solver_courant_target() -> None:
    # Co = 30.0 * 0.01 / 0.5 = 0.60 <= 1.0 -> passesLesCfl True
    res = features.run(
        "femCfdSolver.courantTarget",
        None,
        {"velocityMs": 30.0, "deltaTS": 0.01, "cellSizeM": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["courantNumber"] == pytest.approx(0.60, rel=0.01)
    assert res["summary"]["passesLesCfl"] is True


def test_fem_cfd_solver_domain_decompose() -> None:
    # 2,000,000 / 8 = 250,000 cells per subdomain
    res = features.run(
        "femCfdSolver.domainDecompose",
        None,
        {"method": "hierarchical", "nSubdomains": 8.0, "totalCells": 2000000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["method"] == "hierarchical"
    assert res["summary"]["subdomains"] == 8
    assert res["summary"]["cellsPerSubdomain"] == 250000


def test_fem_cfd_solver_gpu_acceleration() -> None:
    # estVram = 10.0 * 1.65 = 16.5 GB > 0.9 * 16.0 (14.4 GB) -> fitsInGpu False
    res = features.run("femCfdSolver.gpuAcceleration", None, {"totalCellsM": 10.0, "vramGb": 16.0})
    assert res["problems"] == []
    assert res["summary"]["estimatedVramGb"] == pytest.approx(16.5, rel=0.01)
    assert res["summary"]["fitsInGpu"] is False


def test_fem_cfd_solver_limiters() -> None:
    res = features.run(
        "femCfdSolver.limiters", None, {"limiterCoeff": 0.5, "scalarScheme": "upwind"}
    )
    assert res["problems"] == []
    assert res["summary"]["limiterCoeff"] == pytest.approx(0.5, rel=0.01)
    assert res["summary"]["scalarScheme"] == "upwind"


def test_fem_cfd_solver_max_iterations() -> None:
    res = features.run("femCfdSolver.maxIterations", None, {"nOuter": 4000.0, "nInnerP": 30.0})
    assert res["problems"] == []
    assert res["summary"]["maxOuter"] == 4000
    assert res["summary"]["maxInnerP"] == 30


def test_fem_cfd_solver_monitor_point() -> None:
    res = features.run("femCfdSolver.monitorPoint", None, {"xM": 40.0, "yM": 5.0, "zM": 18.0})
    assert res["problems"] == []
    assert res["summary"]["xM"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["yM"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["zM"] == pytest.approx(18.0, rel=0.01)


def test_fem_cfd_solver_pressure_scheme() -> None:
    # costMultiplier = 1.0 + 0.15 * 4 = 1.60
    res = features.run(
        "femCfdSolver.pressureScheme",
        None,
        {"scheme": "clippedLinear", "nNonOrthogonalCorrectors": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["scheme"] == "clippedLinear"
    assert res["summary"]["nonOrthogonalCorrectors"] == 4
    assert res["tables"][0]["rows"][0]["costMultiplier"] == pytest.approx(1.60, rel=0.01)


def test_fem_cfd_solver_pseudo_transient() -> None:
    # pseudo_dt = 4.0 * 0.5 / 20.0 = 0.10 s; dampingRatio = 1 / (1 + 4.0) = 0.20
    res = features.run(
        "femCfdSolver.pseudoTransient",
        None,
        {"localCo": 4.0, "minCellM": 0.5, "refSpeedMs": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["equivalentDtS"] == pytest.approx(0.10, rel=0.01)
    assert res["summary"]["pseudoCfl"] == pytest.approx(4.0, rel=0.01)
    assert res["tables"][0]["rows"][0]["dampingRatio"] == pytest.approx(0.20, rel=0.01)


def test_fem_cfd_solver_residual_target() -> None:
    res = features.run(
        "femCfdSolver.residualTarget",
        None,
        {"pTol": 5e-4, "uTol": 2e-4, "turbTol": 1e-3},
    )
    assert res["problems"] == []
    assert res["summary"]["pTarget"] == pytest.approx(5e-4, rel=0.01)
    assert res["summary"]["uTarget"] == pytest.approx(2e-4, rel=0.01)
    assert res["summary"]["turbTarget"] == pytest.approx(1e-3, rel=0.01)


def test_fem_cfd_solver_time_step_control() -> None:
    res = features.run(
        "femCfdSolver.timeStepControl",
        None,
        {"adjustTimeStep": False, "maxCo": 0.8, "maxDeltaT": 0.02},
    )
    assert res["problems"] == []
    assert res["summary"]["adaptive"] is False
    assert res["summary"]["maxCo"] == pytest.approx(0.8, rel=0.01)
    assert res["summary"]["maxDeltaTS"] == pytest.approx(0.02, rel=0.01)


def test_fem_cfd_solver_tolerance_setup() -> None:
    res = features.run(
        "femCfdSolver.toleranceSetup",
        None,
        {"pAbsTol": 1e-7, "pRelTol": 0.02, "uRelTol": 0.05},
    )
    assert res["problems"] == []
    assert res["summary"]["pRelTol"] == pytest.approx(0.02, rel=0.01)
    assert res["summary"]["uRelTol"] == pytest.approx(0.05, rel=0.01)
    assert _row_by(res, "field", "p")["absTol"] == "1.0e-07"


def test_fem_cfd_solver_under_relaxation() -> None:
    # p + u = 0.25 + 0.65 = 0.90; min(0.25, 0.65, 0.45, 0.40) = 0.25
    res = features.run(
        "femCfdSolver.underRelaxation",
        None,
        {"p": 0.25, "u": 0.65, "k": 0.45, "omega": 0.40},
    )
    assert res["problems"] == []
    assert res["summary"]["pPlusU"] == pytest.approx(0.90, rel=0.01)
    assert res["summary"]["minAlpha"] == pytest.approx(0.25, rel=0.01)


# ── Dynamics (fem_dynamics.py: 12) ───────────────────────────────────────────────────────────────


def test_fem_dynamics_damping_assignment() -> None:
    res = features.run(
        "femDynamics.dampingAssignment",
        None,
        {"concreteDampingPct": 4.5, "steelDampingPct": 2.5},
    )
    assert res["problems"] == []
    assert res["summary"]["concretePct"] == pytest.approx(4.5, rel=0.01)
    assert res["summary"]["steelPct"] == pytest.approx(2.5, rel=0.01)


def test_fem_dynamics_damping_estimate() -> None:
    # delta = ln(16 / 4) / 5 = ln(4) / 5 = 0.277259
    # xi = 0.277259 / sqrt(4*pi^2 + 0.277259^2) = 0.277259 / 6.28930 = 0.044084 (4.4084%)
    res = features.run(
        "femDynamics.dampingEstimate",
        None,
        {"amplitude0": 16.0, "amplitudeK": 4.0, "cycles": 5},
    )
    assert res["problems"] == []
    assert res["summary"]["logDecrement"] == pytest.approx(0.277259, rel=0.01)
    assert res["summary"]["effectiveDampingRatio"] == pytest.approx(0.044084, rel=0.01)
    assert res["summary"]["dampingPct"] == pytest.approx(4.4084, rel=0.01)


def test_fem_dynamics_damping_ratios() -> None:
    # Default pack (BNBC 2020) eta = max(0.55, sqrt(10 / (5 + 100*xi)))
    # At 10% damping: sqrt(10 / 15) = 0.816497
    res = features.run("femDynamics.dampingRatios", None, {"modalDampingPct": 10.0})
    assert res["problems"] == []
    assert res["summary"]["dampingPct"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["spectralEta"] == pytest.approx(0.816497, rel=0.01)


def test_fem_dynamics_energy_balance() -> None:
    # Es = 0.5 * 600 * 0.10 = 30.0 kN·m
    # Ed = 2 * pi * 0.08 * 600 * 0.10 = 30.15929 kN·m
    # Ei = Es + Ed = 60.15929 kN·m
    res = features.run(
        "femDynamics.energyBalance",
        None,
        {"peakDispM": 0.10, "baseShearKn": 600.0, "dampingRatio": 0.08},
    )
    assert res["problems"] == []
    assert res["summary"]["strainEnergyKnm"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["dampingEnergyKnm"] == pytest.approx(30.15929, rel=0.01)
    assert res["summary"]["inputEnergyKnm"] == pytest.approx(60.15929, rel=0.01)


def test_fem_dynamics_floor_spectra() -> None:
    # Default pack floorSpectra table: 120 geomspaced periods [0.02, 4.0] s, first 20 tabulated, ±15% broadening.
    res = features.run("femDynamics.floorSpectra", None, {"componentDamping": 0.03})
    assert res["problems"] == []
    assert res["summary"]["packTableLoaded"] is True
    assert res["summary"]["periods"] == 20
    assert res["tables"][0]["rows"][0]["periodS"] == pytest.approx(0.02, rel=0.01)
    assert res["tables"][0]["rows"][0]["broadeningShare"] == pytest.approx(0.15, rel=0.01)


def test_fem_dynamics_mass_source() -> None:
    res = features.run("femDynamics.massSource", None, {"deadFactor": 1.05, "liveFactor": 0.50})
    assert res["problems"] == []
    assert res["summary"]["deadMassFactor"] == pytest.approx(1.05, rel=0.01)
    assert res["summary"]["liveMassFactor"] == pytest.approx(0.50, rel=0.01)


def test_fem_dynamics_modal_combination() -> None:
    # R1 = 100, R2 = 60, T1 = 1.0 s, T2 = 0.8 s (r = 0.8), xi = 0.05:
    # SRSS = sqrt(100^2 + 60^2) = 116.6190
    # ABS = |100| + |60| = 160.0
    # Der Kiureghian rho12 = 8 * 0.05^2 * 1.8 * 0.8^1.5 / (0.36^2 + 4*0.05^2*0.8*1.8^2) = 0.165635
    # CQC = sqrt(13600 + 2 * 0.165635 * 6000) = 124.8504
    res = features.run(
        "femDynamics.modalCombination",
        None,
        {
            "rule": "ABS",
            "damping": 0.05,
            "mode1PeriodS": 1.0,
            "mode2PeriodS": 0.8,
            "peak1": 100.0,
            "peak2": 60.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["selectedRule"] == "ABS"
    assert res["summary"]["combinedResponse"] == pytest.approx(160.0, rel=0.01)
    assert res["summary"]["srssValue"] == pytest.approx(116.6190, rel=0.01)
    assert res["summary"]["cqcValue"] == pytest.approx(124.8504, rel=0.01)


def test_fem_dynamics_mode_count() -> None:
    # 8 storeys * 3 DOFs/storey = 24 modes (>= 12 min)
    res = features.run("femDynamics.modeCount", None, {"storeys": 8})
    assert res["problems"] == []
    assert res["summary"]["storeys"] == 8
    assert res["summary"]["recommendedModes"] == 24


def test_fem_dynamics_output_steps() -> None:
    # totalSteps = 20.0 / 0.005 = 4000; savedFrames = 4000 // 4 = 1000; outputDt = 0.02 s
    res = features.run(
        "femDynamics.outputSteps", None, {"durationS": 20.0, "dtS": 0.005, "stride": 4}
    )
    assert res["problems"] == []
    assert res["summary"]["totalSteps"] == 4000
    assert res["summary"]["savedFrames"] == 1000
    assert res["tables"][0]["rows"][0]["outputDtS"] == pytest.approx(0.02, rel=0.01)


def test_fem_dynamics_ritz_settings() -> None:
    res = features.run("femDynamics.ritzSettings", None, {"maxVectors": 24})
    assert res["problems"] == []
    assert res["summary"]["maxRitzVectors"] == 24


def test_fem_dynamics_spectrum_curves() -> None:
    # Default pack (BNBC 2020) standalone settings: site SD (S=1.35, TB=0.2, TC=0.8, TD=2.0),
    # z_val = a_h = 0.18, I = 1.0, R = 8.0. At damping = 0.08: eta = sqrt(10 / (5 + 8)) = 0.877058.
    # Plateau (0.2..0.8 s): elasticSaG = 2.5 * 1.35 * 0.877058 * 0.18 = 0.53281 g
    # designCs = (2/3) * (1.0 / 8.0) * 0.53281 = 0.04440 g
    res = features.run("femDynamics.spectrumCurves", None, {"damping": 0.08})
    assert res["problems"] == []
    assert res["summary"]["siteClass"] == "SD"
    assert res["summary"]["peakElasticG"] == pytest.approx(0.53281, rel=0.01)
    row_04 = _row_by(res, "periodS", 0.4)
    assert row_04["elasticSaG"] == pytest.approx(0.53281, rel=0.01)
    assert row_04["designCs"] == pytest.approx(0.04440, rel=0.01)


def test_fem_dynamics_time_step() -> None:
    # T_min = 1 / 25.0 = 0.04 s; dt_max = 0.04 / 20 = 0.002 s
    res = features.run("femDynamics.timeStep", None, {"highestFreqHz": 25.0, "stepsPerCycle": 20})
    assert res["problems"] == []
    assert res["summary"]["shortestPeriodS"] == pytest.approx(0.04, rel=0.01)
    assert res["summary"]["recommendedDtS"] == pytest.approx(0.002, rel=0.01)


# ── Pushover Performance (fem_pushover_performance.py: 9) ────────────────────────────────────────


def test_fem_pushover_performance_bilinear_fitting() -> None:
    # Exact bilinear input curve (0,0) -> (20 mm, 400 kN) -> (100 mm, 480 kN) up to target 100 mm:
    # Equal-area bilinear fit recovers exact elastic-hardening corner:
    # Ke = 400 / 0.02 = 20,000 kN/m, Vy = 400 kN, dy = 20 mm, Vt = 480 kN.
    res = features.run(
        "femPushoverPerformance.bilinearFitting",
        None,
        {"curvePairs": "0,0; 20,400; 100,480", "targetDispMm": 100.0},
    )
    assert res["problems"] == []
    assert res["summary"]["vyKn"] == pytest.approx(400.0, rel=0.01)
    assert res["summary"]["dyMm"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["keKnPerM"] == pytest.approx(20000.0, rel=0.01)


def test_fem_pushover_performance_capacity_spectrum() -> None:
    # Peak point (100 mm, 800 kN): Sd = 100 / 1.25 = 80.0 mm; Sa = 800 / 4000 = 0.20 g
    res = features.run(
        "femPushoverPerformance.capacitySpectrum",
        None,
        {"curvePairs": "0,0; 25,400; 100,800", "modalWeightKn": 4000.0, "pf1": 1.25},
    )
    assert res["problems"] == []
    assert res["summary"]["points"] == 3
    assert res["summary"]["maxSdMm"] == pytest.approx(80.0, rel=0.01)
    assert res["summary"]["peakSaG"] == pytest.approx(0.20, rel=0.01)


def test_fem_pushover_performance_concrete_strain() -> None:
    # DCR = 0.006 / 0.015 = 0.40 <= 1.0 -> passes True
    res = features.run(
        "femPushoverPerformance.concreteStrain",
        None,
        {"extremeStrain": 0.006, "confinementLimit": 0.015},
    )
    assert res["problems"] == []
    assert res["summary"]["strainDcr"] == pytest.approx(0.40, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_pushover_performance_custom_level() -> None:
    res = features.run(
        "femPushoverPerformance.customLevel",
        None,
        {
            "name": "Immediate Repair",
            "driftLimit": 0.012,
            "concreteStrain": 0.006,
            "steelStrain": 0.025,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["name"] == "Immediate Repair"
    assert res["summary"]["driftLimit"] == pytest.approx(0.012, rel=0.01)
    assert res["summary"]["steelStrainLimit"] == pytest.approx(0.025, rel=0.01)


def test_fem_pushover_performance_level_limits() -> None:
    res = features.run(
        "femPushoverPerformance.levelLimits",
        None,
        {"ioDrift": 0.008, "lsDrift": 0.018, "cpDrift": 0.035},
    )
    assert res["problems"] == []
    assert res["summary"]["ioLimit"] == pytest.approx(0.008, rel=0.01)
    assert res["summary"]["lsLimit"] == pytest.approx(0.018, rel=0.01)
    assert res["summary"]["cpLimit"] == pytest.approx(0.035, rel=0.01)
    assert res["tables"][0]["rows"][1]["pctHeight"] == pytest.approx(1.8, rel=0.01)


def test_fem_pushover_performance_rebar_strain() -> None:
    # DCR = 0.030 / 0.060 = 0.50 <= 1.0 -> passes True
    res = features.run(
        "femPushoverPerformance.rebarStrain",
        None,
        {"tensileStrain": 0.030, "limitStrain": 0.060},
    )
    assert res["problems"] == []
    assert res["summary"]["steelStrainDcr"] == pytest.approx(0.50, rel=0.01)
    assert res["summary"]["passes"] is True


def test_fem_pushover_performance_rotation_limits() -> None:
    res = features.run(
        "femPushoverPerformance.rotationLimits",
        None,
        {"ioRotRad": 0.004, "lsRotRad": 0.012, "cpRotRad": 0.024},
    )
    assert res["problems"] == []
    assert res["summary"]["ioRad"] == pytest.approx(0.004, rel=0.01)
    assert res["summary"]["lsRad"] == pytest.approx(0.012, rel=0.01)
    assert res["summary"]["cpRad"] == pytest.approx(0.024, rel=0.01)


def test_fem_pushover_performance_section_ductility() -> None:
    # mu_phi = 0.045 / 0.005 = 9.0
    res = features.run(
        "femPushoverPerformance.sectionDuctility",
        None,
        {"phiYieldPerM": 0.005, "phiUltPerM": 0.045},
    )
    assert res["problems"] == []
    assert res["summary"]["curvatureDuctility"] == pytest.approx(9.0, rel=0.01)


def test_fem_pushover_performance_storey_drift_limits() -> None:
    res = features.run(
        "femPushoverPerformance.storeyDriftLimits",
        None,
        {"operationalLimit": 0.004, "lifeSafetyLimit": 0.025},
    )
    assert res["problems"] == []
    assert res["summary"]["operationalLimit"] == pytest.approx(0.004, rel=0.01)
    assert res["summary"]["lifeSafetyLimit"] == pytest.approx(0.025, rel=0.01)


# ── STM Load Paths (fem_stm_load_paths.py: 7) ────────────────────────────────────────────────────


def test_fem_stm_load_paths_detour_path() -> None:
    # deepBeam template (span 3000, z = 1350, P = 1000 kN at C, supports at A & B):
    # Two direct 1-member paths C->A (S2) and C->B (S3), each with |F| = 500*hypot(1500,1350)/1350 = 747.42 kN.
    res = features.run("femStmLoadPaths.detourPath", None, {"loadNode": "C", "maximumPaths": 5})
    assert res["problems"] == []
    assert res["summary"]["alternatePaths"] == 2
    assert res["tables"][0]["rows"][0]["minimumMemberForceKn"] == pytest.approx(747.42, rel=0.01)


def test_fem_stm_load_paths_material_utilization() -> None:
    # deepBeam struts S2 & S3: F = 747.42 kN; bottle strut without web steel -> beta_s = 0.60, fc = 28 MPa:
    # phi*Fns = 0.75 * (0.85 * 0.60 * 28) * (300 * 300) / 1000 = 963.90 kN -> u = 747.42 / 963.90 = 0.7754 >= 0.40
    res = features.run("femStmLoadPaths.materialUtilization", None, {"lowUtilisationLimit": 0.40})
    assert res["problems"] == []
    assert res["summary"]["strutsReviewed"] == 2
    assert res["summary"]["lowUtilisationStruts"] == 0
    assert _row_by(res, "strutId", "S2")["utilisation"] == pytest.approx(0.7754, rel=0.01)


def test_fem_stm_load_paths_principal_trajectories() -> None:
    # Control-zone area = 400 * 300 = 120,000 mm2 on deepBeam:
    # At node A: T1 (+555.56 kN, c=1, s=0 -> sxx=+4.6296 MPa) and
    # S2 (-747.42 kN, c=0.7433, s=0.6690 -> sigma=-6.2285 MPa -> sxx=-3.4412, syy=-2.7873, txy=-3.0970).
    # Net: sxx=1.1884, syy=-2.7873, txy=-3.0970 -> mean=-0.7995, R=3.6802 MPa
    # sigma1 = 2.8807 MPa, sigma2 = -4.4796 MPa, axis = 0.5*atan2(-6.1940, 3.9757) = -28.652 deg.
    res = features.run("femStmLoadPaths.principalTrajectories", None, {"controlDepthMm": 400.0})
    assert res["problems"] == []
    assert res["summary"]["trajectorySeeds"] == 3
    row_a = _row_by(res, "nodeId", "A")
    assert row_a["principal1Mpa"] == pytest.approx(2.8807, rel=0.01)
    assert row_a["principal2Mpa"] == pytest.approx(-4.4796, rel=0.01)
    assert row_a["principalAxisDeg"] == pytest.approx(-28.652, rel=0.01)


def test_fem_stm_load_paths_redistribute_forces(tmp_path: Path) -> None:
    # dappedEnd template: node B=(350,425) is an unloaded, unsupported internal node; T2(A-B) = +218.18 kN.
    # Baseline at B: T4(B-F) slope -375/750 -> T4 = 218.18*sqrt(5)/2 = 243.93 kN, T3(B-C) = 109.09 kN.
    # Shift B by (+100, 0) to (450, 425): B-C=(-100,275), B-F=(650,-375), T2 still 218.18 kN:
    # Equilibrium at shifted B gives T4 = 318.76 kN (+74.83 kN) and T3 = 169.50 kN (+60.41 kN).
    dap = stm_model.template("dappedEnd", {})
    fem_dir = tmp_path / "08 FEM"
    fem_dir.mkdir()
    (fem_dir / "strut-and-tie.json").write_text(
        StrutAndTieFile(models=[dap]).model_dump_json(by_alias=True), encoding="utf-8"
    )
    res = features.run(
        "femStmLoadPaths.redistributeForces",
        str(tmp_path),
        {"internalNode": "B", "shiftXmm": 100.0, "shiftYmm": 0.0},
    )
    assert res["problems"] == []
    assert res["summary"]["nodeId"] == "B"
    assert res["summary"]["membersCompared"] == 6
    row_t3 = _row_by(res, "memberId", "T3")
    assert row_t3["originalForceKn"] == pytest.approx(109.09, rel=0.01)
    assert row_t3["trialForceKn"] == pytest.approx(169.50, rel=0.01)
    assert row_t3["changeKn"] == pytest.approx(60.41, rel=0.01)
    row_t4 = _row_by(res, "memberId", "T4")
    assert row_t4["trialForceKn"] == pytest.approx(318.76, rel=0.01)


def test_fem_stm_load_paths_streamline_density() -> None:
    # deepBeam member lengths: T1 = 3000 mm -> ceil(3000/500)+1 = 7 pts;
    # S2 & S3 = hypot(1500, 1350) = 2018.04 mm -> ceil(2018.04/500)+1 = 6 pts each -> total 7 + 6 + 6 = 19 pts.
    res = features.run("femStmLoadPaths.streamlineDensity", None, {"sampleSpacingMm": 500.0})
    assert res["problems"] == []
    assert res["summary"]["samplePoints"] == 19
    assert res["summary"]["sampleSpacingMm"] == pytest.approx(500.0, rel=0.01)


def test_fem_stm_load_paths_stress_band(tmp_path: Path) -> None:
    # Sized deepBeam (T1 barArea = 2000 mm2, S2/S3 area = 300*300 = 90,000 mm2):
    # T1 stress = 555,556 / 2000 = 277.78 MPa -> 5 MPa band [275, 280]
    # S2 stress = 747,424 / 90,000 = 8.3047 MPa -> 5 MPa band [5, 10]
    _write_sized_deep_beam(tmp_path)
    res = features.run("femStmLoadPaths.stressBand", str(tmp_path), {"bandWidthMpa": 5.0})
    assert res["problems"] == []
    assert res["summary"]["membersBanded"] == 3
    row_t1 = _row_by(res, "memberId", "T1")
    assert row_t1["stressMpa"] == pytest.approx(277.78, rel=0.01)
    assert row_t1["bandLowerMpa"] == pytest.approx(275.0, rel=0.01)
    assert row_t1["bandUpperMpa"] == pytest.approx(280.0, rel=0.01)
    row_s2 = _row_by(res, "memberId", "S2")
    assert row_s2["stressMpa"] == pytest.approx(8.3047, rel=0.01)
    assert row_s2["bandLowerMpa"] == pytest.approx(5.0, rel=0.01)


def test_fem_stm_load_paths_stress_hotspot(tmp_path: Path) -> None:
    # Sized deepBeam with threshold 8.0 MPa:
    # T1 = 277.78 MPa (>= 8), S2 = S3 = 8.3047 MPa (>= 8) -> 3 member hotspots, 3 node hotspots (A, B, C).
    _write_sized_deep_beam(tmp_path)
    res = features.run("femStmLoadPaths.stressHotspot", str(tmp_path), {"minimumStressMpa": 8.0})
    assert res["problems"] == []
    assert res["summary"]["memberHotspots"] == 3
    assert res["summary"]["nodeHotspots"] == 3
    assert _row_by(res, "memberId", "S2")["axialStressMpa"] == pytest.approx(8.3047, rel=0.01)


# ── Pushover Capacity (fem_capacity.py: 3) ───────────────────────────────────────────────────────


def test_fem_capacity_bilinear_idealisation() -> None:
    # Exact bilinear input (0,0; 20,400; 100,480) up to 100 mm -> Vy = 400 kN, dy = 20 mm, Ke = 20,000 kN/m.
    res = features.run(
        "femCapacity.bilinearIdealisation",
        None,
        {"curvePairs": "0,0; 20,400; 100,480", "targetDispMm": 100.0},
    )
    assert res["problems"] == []
    assert res["summary"]["vyKn"] == pytest.approx(400.0, rel=0.01)
    assert res["summary"]["dyMm"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["keKnPerM"] == pytest.approx(20000.0, rel=0.01)


def test_fem_capacity_effective_damping() -> None:
    # Takeda-adjusted hysteretic damping for mu = 4.0, alpha = 0.10:
    # beta_hyst = (2 / pi) * (3.0 * 0.90) / (4.0 * 1.30) * 0.65 = 0.63662 * 0.51923 * 0.65 = 0.214859
    # beta_eff = 0.05 + 0.214859 = 0.264859
    res = features.run(
        "femCapacity.effectiveDamping",
        None,
        {"ductilityMu": 4.0, "postYieldRatioAlpha": 0.10},
    )
    assert res["problems"] == []
    assert res["summary"]["hystereticDamping"] == pytest.approx(0.214859, rel=0.01)
    assert res["summary"]["effectiveDamping"] == pytest.approx(0.264859, rel=0.01)


def test_fem_capacity_spectral_reduction() -> None:
    # FEMA-440 B(beta) = 4 / (5.6 - ln(100 * beta)):
    # At beta = 0.20 (20%): B = 4 / (5.6 - ln(20)) = 4 / (5.6 - 2.99573) = 1.53594
    # 1 / B = 0.65107
    res = features.run("femCapacity.spectralReduction", None, {"effectiveDamping": 0.20})
    assert res["problems"] == []
    assert res["summary"]["reductionFactorB"] == pytest.approx(1.53594, rel=0.01)
    assert res["summary"]["spectralMultiplier"] == pytest.approx(0.65107, rel=0.01)
    row_20 = _row_by(res, "dampingPct", 20.0)
    assert row_20["reductionB"] == pytest.approx(1.53594, rel=0.01)
    assert row_20["spectralMultiplier"] == pytest.approx(0.65107, rel=0.01)

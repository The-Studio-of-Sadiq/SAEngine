"""Pushover - Nonlinear tab: solver controls, material laws, geometric imperfections, stability, and convergence."""

from __future__ import annotations

import math
from typing import Any

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
)
from saengine.features.fem_common import (
    export_fem_file,
    load_manifest,
    load_settings,
    optional_osmodel,
    require_results,
)
from saengine.fem import acceptance, nonlinear


@feature(
    "femNonlinear.pushoverCase",
    "Pushover Case",
    part="fem",
    fields=[
        select(
            "direction",
            "Pushover direction",
            [("X+", "+X"), ("X-", "-X"), ("Y+", "+Y"), ("Y-", "-Y")],
            "X+",
        ),
        number("targetDriftRatio", "Target roof drift ratio", 0.04, min=0.005, max=0.15),
        number("steps", "Load/displacement steps", 50, min=5, max=500),
    ],
    requires_project=False,
)
def pushover_case(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure pushover direction, target roof drift, and displacement increment size."""
    settings = load_settings(ctx)
    configured = getattr(getattr(settings, "analysis", None), "pushover", None) is not None
    rows = [
        {
            "direction": values["direction"],
            "targetDrift": values["targetDriftRatio"],
            "steps": int(values["steps"]),
            "projectConfigured": configured,
        }
    ]
    return result(
        summary={
            "direction": values["direction"],
            "targetDrift": values["targetDriftRatio"],
            "steps": int(values["steps"]),
        },
        tables=[
            table(
                "Pushover case specification",
                [
                    ("direction", "Direction"),
                    ("targetDrift", "Target Drift"),
                    ("steps", "Steps"),
                    ("projectConfigured", "In Settings"),
                ],
                rows,
            )
        ],
        notes=["Displacement-controlled static nonlinear pushover from gravity-preloaded state."],
    )


@feature(
    "femNonlinear.nonlinearSettings",
    "Nonlinear Settings",
    part="fem",
    fields=[
        number("maxIterations", "Max Newton-Raphson iterations", 50, min=5, max=500),
        number("tolDisp", "Displacement norm tolerance", 1e-5, min=1e-9, max=1e-2),
        select(
            "algorithm",
            "Nonlinear solver algorithm",
            [
                ("KrylovNewton", "Krylov-Newton"),
                ("NewtonLineSearch", "Newton with Line Search"),
                ("ModifiedNewton", "Modified Newton"),
            ],
            "KrylovNewton",
        ),
    ],
    requires_project=False,
)
def nonlinear_settings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure Newton-Raphson equilibrium tolerance and tangent update strategy."""
    rows = [
        {
            "algorithm": values["algorithm"],
            "maxIterations": int(values["maxIterations"]),
            "tolDisp": values["tolDisp"],
        }
    ]
    return result(
        summary={
            "algorithm": values["algorithm"],
            "maxIterations": int(values["maxIterations"]),
            "tolerance": values["tolDisp"],
        },
        tables=[
            table(
                "Nonlinear solver tolerances",
                [
                    ("algorithm", "Algorithm"),
                    ("maxIterations", "Max Iters"),
                    ("tolDisp", "Norm Tol"),
                ],
                rows,
            )
        ],
        notes=[
            "Krylov-Newton accelerates convergence across concrete cracking and rebar yielding."
        ],
    )


@feature(
    "femNonlinear.stepControl",
    "Step Control",
    part="fem",
    fields=[
        number("targetDispMm", "Target roof displacement", 300.0, unit="mm", min=5.0),
        number("incrementMm", "Base displacement step Δu", 5.0, unit="mm", min=0.2),
        checkbox("adaptiveSubstep", "Enable automatic step bisection", True),
    ],
    requires_project=False,
)
def step_control(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute nominal and sub-stepped displacement increment counts."""
    n_steps = math.ceil(values["targetDispMm"] / values["incrementMm"])
    min_substep = (
        values["incrementMm"] / 16.0 if values["adaptiveSubstep"] else values["incrementMm"]
    )
    rows = [
        {
            "targetDispMm": values["targetDispMm"],
            "baseStepMm": values["incrementMm"],
            "nominalSteps": n_steps,
            "minSubstepMm": min_substep,
        }
    ]
    return result(
        summary={
            "nominalSteps": n_steps,
            "baseStepMm": values["incrementMm"],
            "minSubstepMm": min_substep,
        },
        tables=[
            table(
                "Displacement step control",
                [
                    ("targetDispMm", "Target", "mm"),
                    ("baseStepMm", "Base Δu", "mm"),
                    ("nominalSteps", "Steps"),
                    ("minSubstepMm", "Min Substep", "mm"),
                ],
                rows,
            )
        ],
        notes=["Automatic step halving activates whenever Newton-Raphson fails to converge."],
    )


@feature(
    "femNonlinear.hingeProperties",
    "Hinge Properties",
    part="fem",
    fields=[
        number("fibersDepth", "Core fibers along depth", nonlinear.FIBERS_DEPTH, min=4, max=40),
        number("fibersWidth", "Core fibers along width", nonlinear.FIBERS_WIDTH, min=2, max=20),
    ],
    requires_project=False,
)
def hinge_properties(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure force-based fibre section discretization parameters for distributed plasticity."""
    total_core = int(values["fibersDepth"]) * int(values["fibersWidth"])
    rows = [
        {"item": "Core concrete fibres", "count": total_core},
        {"item": "Integration points per element", "count": 5},
        {"item": "Formulation", "count": "ForceBeamColumn"},
    ]
    return result(
        summary={
            "coreFibers": total_core,
            "fibersDepth": int(values["fibersDepth"]),
            "fibersWidth": int(values["fibersWidth"]),
        },
        tables=[
            table(
                "Fibre-hinge section discretization",
                [("item", "Parameter"), ("count", "Value")],
                rows,
            )
        ],
        notes=[
            "Distributed fibre sections capture P-M interaction and neutral-axis migration naturally."
        ],
    )


@feature(
    "femNonlinear.plasticRotation",
    "Plastic Rotation",
    part="fem",
    fields=[
        number("demandRad", "Observed plastic rotation", 0.015, unit="rad", min=0.0),
        number("limitRad", "Acceptance limit", 0.025, unit="rad", min=0.001),
    ],
    requires_project=False,
)
def plastic_rotation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify inelastic member chord rotation demand against acceptance capacity."""
    dcr = values["demandRad"] / values["limitRad"]
    rows = [
        {
            "demandRad": values["demandRad"],
            "limitRad": values["limitRad"],
            "dcr": dcr,
            "ok": dcr <= 1.0,
        }
    ]
    return result(
        summary={"dcr": dcr, "passes": dcr <= 1.0},
        tables=[
            table(
                "Plastic rotation acceptance check",
                [
                    ("demandRad", "θp Demand", "rad"),
                    ("limitRad", "θp Limit", "rad"),
                    ("dcr", "DCR"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Monitors post-yield rotation capacity across nonlinear analysis steps."],
    )


@feature(
    "femNonlinear.redistribution",
    "Redistribution",
    part="fem",
    fields=[
        number(
            "momentRedistPct", "Allowed moment redistribution", 15.0, unit="%", min=0.0, max=30.0
        )
    ],
    requires_project=False,
)
def redistribution(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate inelastic force redistribution factor δ = 1 - ΔM/M_elastic."""
    delta = 1.0 - values["momentRedistPct"] / 100.0
    rows = [
        {
            "redistributionPct": values["momentRedistPct"],
            "momentMultiplier": delta,
            "midspanIncreasePct": values["momentRedistPct"] * 0.5,
        }
    ]
    return result(
        summary={"redistributionPct": values["momentRedistPct"], "momentMultiplier": delta},
        tables=[
            table(
                "Post-yield moment redistribution",
                [
                    ("redistributionPct", "Redist.", "%"),
                    ("momentMultiplier", "δ"),
                    ("midspanIncreasePct", "Span Δ", "%"),
                ],
                rows,
            )
        ],
        notes=["Supports yield hinge shedding excess negative moment into adjacent spans."],
    )


@feature(
    "femNonlinear.bucklingAnalysis",
    "Buckling Analysis",
    part="fem",
    fields=[number("elasticPcrRatio", "Critical load factor λcr", 3.5, min=0.1)],
    requires_project=False,
)
def buckling_analysis(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assess nonlinear GMNIA stability sensitivity using elastic critical load factor λcr."""
    lam = values["elasticPcrRatio"]
    b2 = 1.0 / max(1.0 - 1.0 / lam, 0.05)
    needs_gm = lam < 10.0
    rows = [{"lambdaCr": lam, "elasticAmplifierB2": b2, "secondOrderRequired": needs_gm}]
    return result(
        summary={"lambdaCr": lam, "amplifierB2": b2, "requiresSecondOrder": needs_gm},
        tables=[
            table(
                "Nonlinear buckling & P-Δ sensitivity",
                [
                    ("lambdaCr", "λcr"),
                    ("elasticAmplifierB2", "B2 = 1/(1-1/λcr)"),
                    ("secondOrderRequired", "2nd Order Req."),
                ],
                rows,
            )
        ],
        notes=["Frames with λcr < 10 require explicit second-order geometric nonlinearity."],
    )


@feature(
    "femNonlinear.imperfections",
    "Imperfections",
    part="fem",
    fields=[
        number("storeyHeightMm", "Column/storey height L", 3200.0, unit="mm", min=500.0),
        number("bowDenominator", "Member bow imperfection L / N", 1000.0, min=100.0, max=2000.0),
        number("swayDenominator", "Global out-of-plumbness H / N", 500.0, min=100.0, max=1000.0),
    ],
    requires_project=False,
)
def imperfections(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute geometric member bow e0 and global sway imperfection Δ0 magnitudes."""
    bow_mm = values["storeyHeightMm"] / values["bowDenominator"]
    sway_mm = values["storeyHeightMm"] / values["swayDenominator"]
    rows = [
        {
            "type": "Local member bow e0",
            "ratio": f"L/{values['bowDenominator']:.0f}",
            "magnitudeMm": bow_mm,
        },
        {
            "type": "Global frame out-of-plumb Δ0",
            "ratio": f"H/{values['swayDenominator']:.0f}",
            "magnitudeMm": sway_mm,
        },
    ]
    return result(
        summary={"localBowMm": bow_mm, "globalSwayMm": sway_mm},
        tables=[
            table(
                "Geometric imperfection amplitudes",
                [("type", "Imperfection"), ("ratio", "Ratio"), ("magnitudeMm", "Amplitude", "mm")],
                rows,
            )
        ],
        notes=["Applied along the governing buckling mode shape for GMNIA stability runs."],
    )


@feature(
    "femNonlinear.secondOrder",
    "Second Order",
    part="fem",
    fields=[
        select(
            "geomTransf",
            "Geometric transformation",
            [
                ("Corotational", "Corotational (large displacement)"),
                ("PDelta", "P-Delta (moderate rotation)"),
                ("Linear", "Linear small-strain"),
            ],
            "Corotational",
        )
    ],
    requires_project=False,
)
def second_order(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure corotational or P-Delta geometric transformation for nonlinear pushover runs."""
    rows = [
        {
            "transformation": values["geomTransf"],
            "capturesPD": values["geomTransf"] != "Linear",
            "capturesLargeRot": values["geomTransf"] == "Corotational",
        }
    ]
    return result(
        summary={
            "transformation": values["geomTransf"],
            "largeDisplacement": values["geomTransf"] == "Corotational",
        },
        tables=[
            table(
                "Nonlinear geometric transformation",
                [
                    ("transformation", "Type"),
                    ("capturesPD", "P-Δ"),
                    ("capturesLargeRot", "Large Rot."),
                ],
                rows,
            )
        ],
        notes=[
            "Corotational transformation captures exact large-displacement equilibrium and P-δ softening."
        ],
    )


@feature(
    "femNonlinear.loadSteps",
    "Load Steps",
    part="fem",
    fields=[
        number("gravitySteps", "Gravity preload steps", 10, min=1, max=50),
        number("lateralSteps", "Lateral push steps", 100, min=5, max=1000),
    ],
    requires_project=False,
)
def load_steps(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure two-stage gravity-then-lateral nonlinear incremental loading schedule."""
    rows = [
        {
            "stage": "1. Gravity preload (D + 0.5L)",
            "steps": int(values["gravitySteps"]),
            "control": "Load Control",
        },
        {
            "stage": "2. Lateral pushover",
            "steps": int(values["lateralSteps"]),
            "control": "Displacement Control",
        },
    ]
    return result(
        summary={
            "gravitySteps": int(values["gravitySteps"]),
            "lateralSteps": int(values["lateralSteps"]),
            "totalSteps": int(values["gravitySteps"] + values["lateralSteps"]),
        },
        tables=[
            table(
                "Nonlinear incremental loading stages",
                [("stage", "Stage"), ("steps", "Steps"), ("control", "Control")],
                rows,
            )
        ],
        notes=["Gravity loads must be applied and locked prior to lateral pushover."],
    )


@feature(
    "femNonlinear.arcLengthMethod",
    "Arc Length Method",
    part="fem",
    fields=[
        number("arcRadius", "Initial arc-length radius Δs", 0.02, min=0.001),
        number("psi", "Load/displacement weighting ψ", 0.0, min=0.0, max=1.0),
    ],
    requires_project=False,
)
def arc_length_method(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure Crisfield spherical arc-length path following for snap-through/softening curves."""
    rows = [
        {
            "arcRadius": values["arcRadius"],
            "psi": values["psi"],
            "method": "Spherical Crisfield Arc-Length",
        }
    ]
    return result(
        summary={"arcRadius": values["arcRadius"], "psi": values["psi"]},
        tables=[
            table(
                "Arc-length continuation parameters",
                [("method", "Method"), ("arcRadius", "Δs"), ("psi", "ψ")],
                rows,
            )
        ],
        notes=["Tracks post-peak descending and snap-back equilibrium paths cleanly."],
    )


@feature(
    "femNonlinear.lineSearch",
    "Line Search",
    part="fem",
    fields=[
        number("tolerance", "Line-search energy tolerance", 0.8, min=0.1, max=0.99),
        number("maxSubIters", "Max line-search trials", 10, min=1, max=50),
    ],
    requires_project=False,
)
def line_search(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure secant line-search step damping to stabilize Newton iterations."""
    rows = [
        {
            "tolerance": values["tolerance"],
            "maxTrials": int(values["maxSubIters"]),
            "minStepFactor": 0.1,
        }
    ]
    return result(
        summary={
            "lineSearchTolerance": values["tolerance"],
            "maxTrials": int(values["maxSubIters"]),
        },
        tables=[
            table(
                "Line-search stabilization parameters",
                [
                    ("tolerance", "Residual Ratio Tol"),
                    ("maxTrials", "Max Trials"),
                    ("minStepFactor", "Min α"),
                ],
                rows,
            )
        ],
        notes=["Reduces overshooting across sudden cracking or yielding stiffness drops."],
    )


@feature(
    "femNonlinear.convergenceLog",
    "Convergence Log",
    part="fem",
    fields=[],
    requires_project=True,
)
def convergence_log(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect nonlinear step completion and early-stop convergence warnings from 08 FEM/model.results."""
    out_dir, _ = require_results(ctx)
    manifest = load_manifest(out_dir)
    rows = [
        {
            "case": str(c.get("case_name", "")),
            "type": str(c.get("result_type", "")),
            "completedSteps": int(c.get("completed_steps") or 1),
            "earlyStop": bool(c.get("early_stop", False)),
        }
        for c in manifest.get("cases", [])
    ]
    return result(
        summary={"cases": len(rows), "earlyStops": sum(1 for r in rows if r["earlyStop"])},
        tables=[
            table(
                "Analysis convergence log",
                [
                    ("case", "Case"),
                    ("type", "Type"),
                    ("completedSteps", "Steps"),
                    ("earlyStop", "Early Stop"),
                ],
                rows,
            )
        ],
        notes=["Reports step completion and solver warnings from 08 FEM/model.results."],
    )


@feature(
    "femNonlinear.restartPoint",
    "Restart Point",
    part="fem",
    fields=[number("saveIntervalSteps", "Checkpoint every N steps", 10, min=1, max=200)],
    requires_project=True,
)
def restart_point(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record nonlinear solver checkpoint metadata against 08 FEM/model.osmodel."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError(
            "Derive 08 FEM/model.osmodel first to configure restart checkpoints."
        )
    path = export_fem_file(
        ctx,
        "nonlinear-checkpoint.json",
        f'{{"saveIntervalSteps": {int(values["saveIntervalSteps"])}, "nodes": {len(model.get("nodes", []))}}}\n',
    )
    rows = [{"intervalSteps": int(values["saveIntervalSteps"]), "checkpointPath": str(path)}]
    return result(
        summary={
            "saveIntervalSteps": int(values["saveIntervalSteps"]),
            "checkpointPath": str(path),
        },
        tables=[
            table(
                "Restart checkpoint settings",
                [("intervalSteps", "Interval"), ("checkpointPath", "Metadata Path")],
                rows,
            )
        ],
        notes=[f"Checkpoint metadata written to {path}"],
    )


@feature(
    "femNonlinear.concreteCracking",
    "Concrete Cracking",
    part="fem",
    fields=[number("fcMpa", "Unconfined concrete strength f'c", 28.0, unit="MPa", min=10.0)],
    requires_project=False,
)
def concrete_cracking(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Concrete02 modulus of rupture ft, cracking strain εcr, and tension-softening slope Ets."""
    fc = values["fcMpa"]
    ft = 0.62 * math.sqrt(fc)
    ec = 4700.0 * math.sqrt(fc)
    eps_cr = ft / ec
    ets = 0.1 * ec
    rows = [{"ftMpa": ft, "ecMpa": ec, "crackingStrain": eps_cr, "softeningSlopeEtsMpa": ets}]
    return result(
        summary={"tensileStrengthMpa": ft, "crackingStrain": eps_cr, "softeningEtsMpa": ets},
        tables=[
            table(
                "Concrete02 tensile cracking law",
                [
                    ("ftMpa", "ft", "MPa"),
                    ("ecMpa", "Ec", "MPa"),
                    ("crackingStrain", "εcr"),
                    ("softeningEtsMpa", "Ets", "MPa"),
                ],
                rows,
            )
        ],
        notes=["Matches saengine.fem.nonlinear.FiberMaterials.concrete linear tension softening."],
    )


@feature(
    "femNonlinear.steelYielding",
    "Steel Yielding",
    part="fem",
    fields=[
        number("fyMpa", "Yield stress fy", 420.0, unit="MPa", min=200.0),
        number(
            "hardeningRatio", "Strain hardening ratio b", nonlinear.HARDENING, min=0.0, max=0.10
        ),
    ],
    requires_project=False,
)
def steel_yielding(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Steel02 Giuffré-Menegotto-Pinto yield strain and post-yield tangent modulus."""
    es = 200000.0
    eps_y = values["fyMpa"] / es
    e_post = values["hardeningRatio"] * es
    rows = [
        {"fyMpa": values["fyMpa"], "esMpa": es, "yieldStrain": eps_y, "postYieldModulusMpa": e_post}
    ]
    return result(
        summary={"yieldStrain": eps_y, "postYieldModulusMpa": e_post},
        tables=[
            table(
                "Steel02 uniaxial yielding parameters",
                [
                    ("fyMpa", "fy", "MPa"),
                    ("esMpa", "Es", "MPa"),
                    ("yieldStrain", "εy"),
                    ("postYieldModulusMpa", "b·Es", "MPa"),
                ],
                rows,
            )
        ],
        notes=["Giuffré-Menegotto-Pinto cyclic Bauschinger hardening curve."],
    )


@feature(
    "femNonlinear.crushingLimit",
    "Crushing Limit",
    part="fem",
    fields=[
        number("fcMpa", "Unconfined concrete f'c", 28.0, unit="MPa", min=10.0),
        number("confinementRatio", "Volumetric hoop ratio ρs", 0.012, min=0.0, max=0.05),
        number("fyhMpa", "Hoop yield strength fyh", 420.0, unit="MPa", min=200.0),
    ],
    requires_project=False,
)
def crushing_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Mander/Scott-Park-Priestley confined peak f'cc and crushing strain εcu."""
    fc = values["fcMpa"]
    k = 1.0 + values["confinementRatio"] * values["fyhMpa"] / fc
    fcc = k * fc
    eps_cu = max(
        0.004 + 0.9 * values["confinementRatio"] * values["fyhMpa"] / 300.0, nonlinear.EPS_SPALL
    )
    rows = [
        {"state": "Unconfined cover spalling", "fpcMpa": fc, "epsUltimate": nonlinear.EPS_SPALL},
        {"state": "Confined core crushing", "fpcMpa": fcc, "epsUltimate": eps_cu},
    ]
    return result(
        summary={"confinementFactorK": k, "confinedStrengthMpa": fcc, "crushingStrain": eps_cu},
        tables=[
            table(
                "Modified Kent-Park concrete crushing limits",
                [("state", "Concrete Zone"), ("fpcMpa", "Peak f'c", "MPa"), ("epsUltimate", "εcu")],
                rows,
            )
        ],
        notes=["Matches saengine.fem.nonlinear.FiberMaterials.concrete confined core curve."],
    )


@feature(
    "femNonlinear.tensionStiffening",
    "Tension Stiffening",
    part="fem",
    fields=[
        number("ftMpa", "Concrete tensile strength fct", 2.8, unit="MPa", min=0.5),
        number("rhoEff", "Effective reinforcement ratio ρ_eff", 0.015, min=0.002),
    ],
    requires_project=False,
)
def tension_stiffening(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute average concrete tensile stress retention between cracks after cracking."""
    rows = [
        {
            "strainMultCr": m,
            "retainedStressShare": math.exp(-0.4 * (m - 1.0)),
            "avgStressMpa": values["ftMpa"] * math.exp(-0.4 * (m - 1.0)),
        }
        for m in (1.0, 2.0, 4.0, 8.0, 15.0)
    ]
    return result(
        summary={"crackingStressMpa": values["ftMpa"], "rhoEff": values["rhoEff"]},
        tables=[
            table(
                "Tension stiffening stress decay",
                [
                    ("strainMultCr", "ε / εcr"),
                    ("retainedStressShare", "σc / ft"),
                    ("avgStressMpa", "σc", "MPa"),
                ],
                rows,
            )
        ],
        notes=[
            "Models bond transfer between reinforcing bars and concrete between primary cracks."
        ],
    )


@feature(
    "femNonlinear.hysteresisRules",
    "Hysteresis Rules",
    part="fem",
    fields=[
        select(
            "model",
            "Cyclic hysteresis rule",
            [
                ("Takeda", "Modified Takeda (RC pinching/unloading)"),
                ("MenegottoPinto", "Giuffré-Menegotto-Pinto (Steel)"),
                ("Bilinear", "Bilinear kinematic hardening"),
            ],
            "Takeda",
        )
    ],
    requires_project=False,
)
def hysteresis_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure cyclic unloading/reloading stiffness degradation parameters."""
    params = {
        "Takeda": (0.4, 0.5, "Unloading exponent α=0.4, reloading pinching β=0.5"),
        "MenegottoPinto": (20.0, 0.925, "Transition R0=20, cR1=0.925 smooth Bauschinger curvature"),
        "Bilinear": (0.0, 0.0, "Constant elastic unloading slope K0"),
    }
    p1, p2, desc = params[values["model"]]
    rows = [{"model": values["model"], "param1": p1, "param2": p2, "notes": desc}]
    return result(
        summary={"hysteresisModel": values["model"], "param1": p1, "param2": p2},
        tables=[
            table(
                "Cyclic hysteresis rule parameters",
                [
                    ("model", "Model"),
                    ("param1", "Param 1"),
                    ("param2", "Param 2"),
                    ("notes", "Behaviour"),
                ],
                rows,
            )
        ],
        notes=["Controls cyclic energy dissipation and stiffness degradation during unloading."],
    )


@feature(
    "femNonlinear.driftCapacity",
    "Drift Capacity",
    part="fem",
    fields=[
        number("buildingHeightM", "Building height H", 12.0, unit="m", min=3.0),
        number("targetDriftRatio", "Target drift limit", 0.025, min=0.005),
    ],
    requires_project=True,
)
def drift_capacity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare achieved pushover roof drift against target drift capacity."""
    out_dir, model_path = require_results(ctx)
    runs = acceptance.pushover_results(out_dir, model_path)
    if not runs:
        raise FeatureInputError("No pushover results found in 08 FEM/model.results.")
    rows = []
    for r in runs:
        d_mm = float(r.get("maxDispMm") or 0.0)
        dr = (d_mm / 1000.0) / values["buildingHeightM"]
        rows.append(
            {
                "case": str(r.get("name", "")),
                "achievedDrift": dr,
                "targetDrift": values["targetDriftRatio"],
                "ok": dr >= values["targetDriftRatio"],
            }
        )
    return result(
        summary={"cases": len(rows), "maxAchievedDrift": max(r["achievedDrift"] for r in rows)},
        tables=[
            table(
                "Pushover roof drift capacity check",
                [
                    ("case", "Case"),
                    ("achievedDrift", "Achieved"),
                    ("targetDrift", "Target"),
                    ("ok", "Reached"),
                ],
                rows,
            )
        ],
        notes=["Confirms pushover reached at least the target roof drift."],
    )


@feature(
    "femNonlinear.overstrengthFactor",
    "Overstrength Factor",
    part="fem",
    fields=[number("designShearKn", "Design base shear Vd", 300.0, unit="kN", min=1.0)],
    requires_project=True,
)
def overstrength_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Derive system overstrength factor Ω from pushover peak shear vs design shear."""
    out_dir, model_path = require_results(ctx)
    runs = acceptance.pushover_results(out_dir, model_path)
    if not runs:
        raise FeatureInputError("No pushover results found in 08 FEM/model.results.")
    rows = [
        {
            "case": str(r.get("name", "")),
            "peakShearKn": float(r.get("maxShearKn") or 0.0),
            "omega": float(r.get("maxShearKn") or 0.0) / values["designShearKn"],
        }
        for r in runs
    ]
    return result(
        summary={"meanOverstrength": sum(r["omega"] for r in rows) / len(rows)},
        tables=[
            table(
                "Pushover overstrength factor Ω",
                [("case", "Case"), ("peakShearKn", "V_max", "kN"), ("omega", "Ω")],
                rows,
            )
        ],
        notes=["Ω = V_max / V_design reflects material overstrength and internal redundancy."],
    )


@feature(
    "femNonlinear.collapseMargin",
    "Collapse Margin",
    part="fem",
    fields=[
        number("mcerSpectralG", "MCE spectral acceleration SMT", 0.90, unit="g", min=0.05),
        number("collapseSaG", "Estimated collapse Sa(T1)", 1.65, unit="g", min=0.05),
    ],
    requires_project=True,
)
def collapse_margin(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate Collapse Margin Ratio (CMR) against MCE ground motion intensity."""
    require_results(ctx)
    cmr = values["collapseSaG"] / values["mcerSpectralG"]
    rows = [
        {
            "mcerSaG": values["mcerSpectralG"],
            "collapseSaG": values["collapseSaG"],
            "cmr": cmr,
            "acceptable": cmr >= 1.5,
        }
    ]
    return result(
        summary={"collapseMarginRatio": cmr, "acceptable": cmr >= 1.5},
        tables=[
            table(
                "Global Collapse Margin Ratio (CMR)",
                [
                    ("mcerSaG", "MCE Sa", "g"),
                    ("collapseSaG", "Collapse Sa", "g"),
                    ("cmr", "CMR"),
                    ("acceptable", ">= 1.5"),
                ],
                rows,
            )
        ],
        notes=["CMR = Sa_collapse(T1) / S_MT(T1)."],
    )


@feature(
    "femNonlinear.nonlinearReport",
    "Nonlinear Report",
    part="fem",
    fields=[],
    requires_project=True,
)
def nonlinear_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile nonlinear assumptions, convergence status, and pushover metrics to Markdown."""
    out_dir, model_path = require_results(ctx)
    manifest = load_manifest(out_dir)
    runs = acceptance.pushover_results(out_dir, model_path)
    lines = [
        "# Nonlinear Analysis Report",
        "",
        f"- Total result cases: {len(manifest.get('cases', []))}",
        f"- Pushover cases: {len(runs)}",
    ]
    path = export_fem_file(ctx, "nonlinear-report.md", "\n".join(lines) + "\n")
    rows = [
        {"item": "Manifest cases", "value": len(manifest.get("cases", []))},
        {"item": "Pushover runs", "value": len(runs)},
    ]
    return result(
        summary={"reportPath": str(path), "pushoverRuns": len(runs)},
        tables=[table("Nonlinear report summary", [("item", "Item"), ("value", "Count")], rows)],
        notes=[f"Nonlinear report exported to {path}"],
    )

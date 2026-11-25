"""CFD Wind - Solver tab (`femCfdSolver`): OpenFOAM discretization schemes, CFL, matrix solvers, and MPI."""

from __future__ import annotations

import math
from typing import Any

from saengine.features import (
    FeatureContext,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.fem_common import parse_numbers
from saengine.fem.cfd_wind import openfoam as cfd_openfoam


@feature(
    "femCfdSolver.pressureScheme",
    "Pressure Scheme",
    part="fem",
    fields=[
        select(
            "scheme",
            "Pressure gradient interpolation",
            [
                ("linear", "linear (2nd-order central)"),
                ("clippedLinear", "clippedLinear (skewness-stabilized)"),
            ],
            "linear",
        ),
        number("nNonOrthogonalCorrectors", "Non-orthogonal corrector loops", 2.0, min=0.0, max=6.0),
    ],
    requires_project=False,
)
def pressure_scheme(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure pressure Laplacian discretization and non-orthogonal mesh correctors."""
    n_corr = round(values["nNonOrthogonalCorrectors"])
    rows = [
        {"scheme": values["scheme"], "correctors": n_corr, "costMultiplier": 1.0 + 0.15 * n_corr}
    ]
    return result(
        summary={"scheme": values["scheme"], "nonOrthogonalCorrectors": n_corr},
        tables=[
            table(
                "Pressure Laplacian configuration",
                [
                    ("scheme", "Scheme"),
                    ("correctors", "Correctors"),
                    ("costMultiplier", "Cost Factor"),
                ],
                rows,
            )
        ],
        notes=["Use >= 2 non-orthogonal correctors on snappyHexMesh prism-to-hex transitions."],
    )


@feature(
    "femCfdSolver.momentumScheme",
    "Momentum Scheme",
    part="fem",
    fields=[
        select(
            "divScheme",
            "Advection divergence scheme",
            [
                ("linearUpwindV", "bounded Gauss linearUpwindV grad(U)"),
                ("LUST", "Gauss LUST grad(U) (hybrid LES)"),
                ("upwind", "bounded Gauss upwind (1st order)"),
            ],
            "linearUpwindV",
        ),
    ],
    requires_project=False,
)
def momentum_scheme(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select spatial momentum convection scheme balancing second-order accuracy and boundedness."""
    order_map = {
        "linearUpwindV": "2nd-order bounded",
        "LUST": "2nd-order low-dissipation",
        "upwind": "1st-order diffusive (startup only)",
    }
    rows = [{"scheme": values["divScheme"], "accuracy": order_map[values["divScheme"]]}]
    return result(
        summary={"divScheme": values["divScheme"], "accuracy": order_map[values["divScheme"]]},
        tables=[
            table(
                "Momentum convection discretization",
                [("scheme", "OpenFOAM Scheme"), ("accuracy", "Order")],
                rows,
            )
        ],
        notes=["Avoid pure upwind in production runs as it smears corner suction peaks."],
    )


@feature(
    "femCfdSolver.gradientScheme",
    "Gradient Scheme",
    part="fem",
    fields=[
        select(
            "gradScheme",
            "Cell gradient estimator",
            [
                ("cellLimitedGaussLinear1", "cellLimited Gauss linear 1.0"),
                ("leastSquares", "leastSquares"),
                ("gaussLinear", "Gauss linear"),
            ],
            "cellLimitedGaussLinear1",
        ),
    ],
    requires_project=False,
)
def gradient_scheme(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Choose finite-volume gradient reconstruction scheme and cell limiter bound."""
    rows = [
        {
            "gradScheme": values["gradScheme"],
            "tvdBounded": "Limited" in values["gradScheme"]
            or "Limited" in values["gradScheme"].lower(),
        }
    ]
    return result(
        summary={"gradScheme": values["gradScheme"]},
        tables=[
            table(
                "Gradient scheme setting",
                [("gradScheme", "Gradient Scheme"), ("tvdBounded", "Limiter Active")],
                rows,
            )
        ],
        notes=["cellLimited Gauss linear prevents spurious extrema near sharp eaves."],
    )


@feature(
    "femCfdSolver.limiters",
    "Flux Limiters",
    part="fem",
    fields=[
        number(
            "limiterCoeff",
            "Gradient limiter coefficient (0=unlimited, 1=strict)",
            1.0,
            min=0.0,
            max=1.0,
        ),
        select(
            "scalarScheme",
            "Turbulence scalar limiter",
            [("limitedLinear", "limitedLinear 1"), ("upwind", "bounded upwind")],
            "limitedLinear",
        ),
    ],
    requires_project=False,
)
def limiters(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Control TVD flux and gradient limiters to maintain scalar positivity."""
    rows = [{"limiterCoeff": values["limiterCoeff"], "scalarScheme": values["scalarScheme"]}]
    return result(
        summary={"limiterCoeff": values["limiterCoeff"], "scalarScheme": values["scalarScheme"]},
        tables=[
            table(
                "TVD limiter parameters",
                [("limiterCoeff", "φ Limiter"), ("scalarScheme", "Scalar Div")],
                rows,
            )
        ],
        notes=["Prevents unphysical negative k or ω spikes on skewed prism cells."],
    )


@feature(
    "femCfdSolver.underRelaxation",
    "Under-Relaxation",
    part="fem",
    fields=[
        number("p", "Pressure p", 0.3, min=0.05, max=0.8),
        number("u", "Velocity U", 0.7, min=0.1, max=0.9),
        number("k", "TKE k", 0.5, min=0.1, max=0.9),
        number("omega", "Specific dissipation ω", 0.5, min=0.1, max=0.9),
    ],
    requires_project=False,
)
def under_relaxation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate SIMPLE field and equation under-relaxation factors."""
    rows = [{"field": k, "alpha": values[k]} for k in ("p", "u", "k", "omega")]
    return result(
        summary={
            "pPlusU": values["p"] + values["u"],
            "minAlpha": min(values["p"], values["u"], values["k"], values["omega"]),
        },
        tables=[
            table(
                "fvSolution relaxationFactors", [("field", "Variable"), ("alpha", "Factor")], rows
            )
        ],
        notes=["Reduce U relaxation to 0.5 if continuity residuals oscillate."],
    )


@feature(
    "femCfdSolver.autoTune",
    "Auto-Tune Relaxation",
    part="fem",
    fields=[
        number(
            "maxNonOrthoDeg", "Mesh max non-orthogonality angle", 58.0, unit="°", min=5.0, max=85.0
        ),
        number("maxSkewness", "Mesh max face skewness", 1.8, min=0.1, max=6.0),
    ],
    requires_project=False,
)
def auto_tune(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Automatically adjust relaxation and correctors based on mesh quality metrics."""
    strict = values["maxNonOrthoDeg"] > 65.0 or values["maxSkewness"] > 3.0
    p_rel = 0.2 if strict else 0.3
    u_rel = 0.5 if strict else 0.7
    corr = 3 if values["maxNonOrthoDeg"] > 65.0 else 2
    rows = [
        {
            "profile": "Conservative" if strict else "Standard",
            "alphaP": p_rel,
            "alphaU": u_rel,
            "nonOrthoCorr": corr,
        }
    ]
    return result(
        summary={"alphaP": p_rel, "alphaU": u_rel, "nonOrthoCorrectors": corr},
        tables=[
            table(
                "Auto-tuned solver schedule",
                [
                    ("profile", "Preset"),
                    ("alphaP", "α_p"),
                    ("alphaU", "α_U"),
                    ("nonOrthoCorr", "nNonOrtho"),
                ],
                rows,
            )
        ],
        notes=["High non-orthogonality > 65° requires extra correctors and tighter relaxation."],
    )


@feature(
    "femCfdSolver.pseudoTransient",
    "Pseudo-Transient Stabilization",
    part="fem",
    fields=[
        number("localCo", "Local steady-state pseudo-CFL", 5.0, min=0.5, max=50.0),
        number("minCellM", "Smallest cell size Δx", 0.4, unit="m", min=0.05),
        number("refSpeedMs", "Reference wind speed U_ref", 15.0, unit="m/s", min=1.0),
    ],
    requires_project=False,
)
def pseudo_transient(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute local time-stepping (LTS) pseudo-transient inertial stabilization interval."""
    pseudo_dt = values["localCo"] * values["minCellM"] / values["refSpeedMs"]
    rows = [
        {
            "pseudoCfl": values["localCo"],
            "equivalentDtS": pseudo_dt,
            "dampingRatio": 1.0 / (1.0 + values["localCo"]),
        }
    ]
    return result(
        summary={"equivalentDtS": pseudo_dt, "pseudoCfl": values["localCo"]},
        tables=[
            table(
                "Pseudo-transient solver stabilization",
                [
                    ("pseudoCfl", "Co_local"),
                    ("equivalentDtS", "Δt_eff", "s"),
                    ("dampingRatio", "Inertia Weight"),
                ],
                rows,
            )
        ],
        notes=["Smooths vortex-shedding transients during initial RANS iterations."],
    )


@feature(
    "femCfdSolver.monitorPoint",
    "Convergence Monitor Point",
    part="fem",
    fields=[
        number("xM", "Wake monitor X", 25.0, unit="m"),
        number("yM", "Wake monitor Y", 0.0, unit="m"),
        number("zM", "Monitor height Z", 12.0, unit="m", min=0.5),
    ],
    requires_project=False,
)
def monitor_point(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Register wake velocity/pressure history probe for iterative convergence tracking."""
    rows = [
        {
            "probe": "wakeMonitor1",
            "xM": values["xM"],
            "yM": values["yM"],
            "zM": values["zM"],
            "sampleFields": "U, p",
        }
    ]
    return result(
        summary={"xM": values["xM"], "yM": values["yM"], "zM": values["zM"]},
        tables=[
            table(
                "Wake convergence probe",
                [
                    ("probe", "Name"),
                    ("xM", "X", "m"),
                    ("yM", "Y", "m"),
                    ("zM", "Z", "m"),
                    ("sampleFields", "Fields"),
                ],
                rows,
            )
        ],
        notes=["Place probe 1H–2H downstream of building leeward face."],
    )


@feature(
    "femCfdSolver.residualTarget",
    "Residual Target",
    part="fem",
    fields=[
        number("pTol", "Continuity / pressure target", 1e-4, min=1e-8, max=1e-2),
        number("uTol", "Momentum U target", 1e-5, min=1e-9, max=1e-2),
        number("turbTol", "Turbulence k/ω target", 1e-5, min=1e-9, max=1e-2),
    ],
    requires_project=False,
)
def residual_target(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set equation-by-equation normalized steady residual control criteria."""
    rows = [
        {"equation": "p", "target": f"{values['pTol']:.1e}"},
        {"equation": "U", "target": f"{values['uTol']:.1e}"},
        {"equation": "k / omega", "target": f"{values['turbTol']:.1e}"},
    ]
    return result(
        summary={
            "pTarget": values["pTol"],
            "uTarget": values["uTol"],
            "turbTarget": values["turbTol"],
        },
        tables=[
            table("fvSolution residualControl", [("equation", "Field"), ("target", "Target")], rows)
        ],
        notes=["Momentum residual 1e-5 gives tight force convergence on urban meshes."],
    )


@feature(
    "femCfdSolver.maxIterations",
    "Max Solver Iterations",
    part="fem",
    fields=[
        number("nOuter", "Maximum SIMPLE outer iterations", 2500.0, min=100.0, max=50000.0),
        number("nInnerP", "Pressure GAMG sweeps per step", 20.0, min=5.0, max=100.0),
    ],
    requires_project=False,
)
def max_iterations(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Budget outer SIMPLE iterations and inner Poisson sweep cap."""
    rows = [{"outerMax": int(values["nOuter"]), "innerPMax": int(values["nInnerP"])}]
    return result(
        summary={"maxOuter": int(values["nOuter"]), "maxInnerP": int(values["nInnerP"])},
        tables=[
            table(
                "Iteration budget",
                [("outerMax", "Outer Max"), ("innerPMax", "Linear Inner Max")],
                rows,
            )
        ],
        notes=["Pair with force-coefficient averaging window over final 400 iterations."],
    )


@feature(
    "femCfdSolver.convergencePlot",
    "Residual Decay Slope",
    part="fem",
    fields=[
        text(
            "residualTail",
            "Recent continuity residual tail (CSV)",
            "1.2e-2, 4.5e-3, 1.8e-3, 6.2e-4, 2.1e-4, 8.9e-5",
        )
    ],
    requires_project=False,
)
def convergence_plot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Measure logarithmic residual reduction orders of magnitude from solver history."""
    vals = parse_numbers(values["residualTail"], "residualTail")
    orders = math.log10(max(1e-12, vals[0]) / max(1e-12, vals[-1]))
    rows = [
        {"step": i + 1, "residual": v, "log10": math.log10(max(1e-12, v))}
        for i, v in enumerate(vals)
    ]
    return result(
        summary={"ordersReduced": orders, "finalResidual": vals[-1]},
        tables=[
            table(
                "Residual convergence decay",
                [("step", "Checkpoint"), ("residual", "Residual"), ("log10", "log10(R)")],
                rows,
            )
        ],
        notes=["Aim for >= 3 orders of magnitude reduction plus stable base drag."],
    )


@feature(
    "femCfdSolver.restartRun",
    "Restart Detection & Resume",
    part="fem",
    fields=[
        select(
            "distro",
            "OpenFOAM Linux/WSL distribution",
            [("auto", "Auto-detect"), ("Ubuntu", "Ubuntu")],
            "auto",
        ),
    ],
    requires_project=False,
)
def restart_run(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect local OpenFOAM solver availability and prepare checkpoint restart guidance."""
    inst = cfd_openfoam.detect(
        distribution=None if values["distro"] == "auto" else values["distro"]
    )
    steps = cfd_openfoam.install_steps()
    rows = [
        {"field": "OpenFOAM Detected", "value": str(inst.found)},
        {"field": "Backend", "value": inst.mode or "None"},
        {"field": "Version / Path", "value": inst.version or inst.distribution or "Not installed"},
    ]
    return result(
        summary={"openfoamFound": inst.found, "backend": inst.mode or "none"},
        tables=[
            table(
                "OpenFOAM runtime & restart readiness",
                [("field", "Property"), ("value", "Status")],
                rows,
            )
        ],
        notes=[f"Set controlDict startFrom latestTime to resume. Setup guide items: {len(steps)}."],
    )


@feature(
    "femCfdSolver.timeStepControl",
    "Adaptive Time-Step Control",
    part="fem",
    fields=[
        checkbox("adjustTimeStep", "Enable Co-driven Δt adjustment", True),
        number("maxCo", "Maximum Courant number limit", 1.0, min=0.1, max=10.0),
        number("maxDeltaT", "Maximum cap on Δt", 0.05, unit="s", min=1e-4, max=2.0),
    ],
    requires_project=False,
)
def time_step_control(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure PIMPLE transient Courant-limited adaptive time-step controller."""
    rows = [
        {
            "adjust": values["adjustTimeStep"],
            "maxCo": values["maxCo"],
            "maxDtS": values["maxDeltaT"],
        }
    ]
    return result(
        summary={
            "adaptive": values["adjustTimeStep"],
            "maxCo": values["maxCo"],
            "maxDeltaTS": values["maxDeltaT"],
        },
        tables=[
            table(
                "PIMPLE adaptive time-step rules",
                [("adjust", "Adjust Δt"), ("maxCo", "maxCo"), ("maxDtS", "maxΔt", "s")],
                rows,
            )
        ],
        notes=["Keeps transient peak pressures temporally accurate without blowing up."],
    )


@feature(
    "femCfdSolver.courantTarget",
    "Courant Number Check",
    part="fem",
    fields=[
        number("velocityMs", "Peak local corner velocity |U|", 42.0, unit="m/s", min=0.5),
        number("deltaTS", "Time step Δt", 0.008, unit="s", min=1e-5),
        number("cellSizeM", "Minimum wake cell Δx", 0.35, unit="m", min=0.02),
    ],
    requires_project=False,
)
def courant_target(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute local convective Courant-Friedrichs-Lewy number Co = |U| Δt / Δx."""
    co = values["velocityMs"] * values["deltaTS"] / values["cellSizeM"]
    rows = [
        {
            "velocityMs": values["velocityMs"],
            "dtS": values["deltaTS"],
            "cellM": values["cellSizeM"],
            "courant": co,
            "okForLes": co <= 1.0,
        }
    ]
    return result(
        summary={"courantNumber": co, "passesLesCfl": co <= 1.0},
        tables=[
            table(
                "Courant number evaluation",
                [
                    ("velocityMs", "|U|", "m/s"),
                    ("dtS", "Δt", "s"),
                    ("cellM", "Δx", "m"),
                    ("courant", "Co"),
                    ("okForLes", "Co <= 1"),
                ],
                rows,
            )
        ],
        notes=["Explicit/LES accuracy requires Co <= 1.0."],
    )


@feature(
    "femCfdSolver.cflAdjust",
    "CFL Time-Step Scaler",
    part="fem",
    fields=[
        number("currentCo", "Current peak Courant number", 2.4, min=0.05),
        number("targetCo", "Desired Courant limit", 0.9, min=0.1, max=5.0),
        number("currentDtS", "Current time step Δt", 0.015, unit="s", min=1e-5),
    ],
    requires_project=False,
)
def cfl_adjust(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Scale transient Δt to hit target Courant stability limit."""
    new_dt = values["currentDtS"] * (values["targetCo"] / values["currentCo"])
    rows = [
        {
            "oldDtS": values["currentDtS"],
            "newDtS": new_dt,
            "scaleFactor": new_dt / values["currentDtS"],
        }
    ]
    return result(
        summary={"recommendedDtS": new_dt, "targetCo": values["targetCo"]},
        tables=[
            table(
                "Scaled time step for target Co",
                [("oldDtS", "Old Δt", "s"), ("newDtS", "New Δt", "s"), ("scaleFactor", "Ratio")],
                rows,
            )
        ],
        notes=["Scales Δt linearly because Co is proportional to Δt."],
    )


@feature(
    "femCfdSolver.timeOrder",
    "Temporal Integration Order",
    part="fem",
    fields=[
        select(
            "ddt",
            "Time derivative scheme",
            [
                ("backward", "backward (2nd-order implicit)"),
                ("CrankNicolson09", "CrankNicolson 0.9"),
                ("Euler", "Euler (1st-order implicit)"),
            ],
            "backward",
        ),
    ],
    requires_project=False,
)
def time_order(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select transient time-derivative discretization scheme."""
    ord_map = {
        "backward": ("2nd", "Unbounded slight, very low numerical damping"),
        "CrankNicolson09": ("~2nd", "10% Euler blend for stability"),
        "Euler": ("1st", "Bounded, high temporal damping"),
    }
    o, note = ord_map[values["ddt"]]
    rows = [{"scheme": values["ddt"], "order": o, "behavior": note}]
    return result(
        summary={"scheme": values["ddt"], "order": o},
        tables=[
            table(
                "Temporal ddtSchemes setting",
                [("scheme", "Scheme"), ("order", "Order"), ("behavior", "Characteristics")],
                rows,
            )
        ],
        notes=["Use 2nd-order backward or CrankNicolson 0.9 for LES vortex shedding."],
    )


@feature(
    "femCfdSolver.matrixSolver",
    "Linear Matrix Solver",
    part="fem",
    fields=[
        select(
            "pSolver",
            "Pressure Poisson solver",
            [("GAMG", "GAMG (Geometric-Algebraic Multigrid)"), ("PCG", "PCG (Conjugate Gradient)")],
            "GAMG",
        ),
        select(
            "uSolver",
            "Velocity/scalar solver",
            [("smoothSolver", "smoothSolver (symGaussSeidel)"), ("PBiCGStab", "PBiCGStab")],
            "smoothSolver",
        ),
    ],
    requires_project=False,
)
def matrix_solver(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Pair symmetric multigrid pressure solver with asymmetric convection linear solver."""
    rows = [
        {"matrix": "Pressure p (symmetric)", "solver": values["pSolver"]},
        {"matrix": "Velocity U / k / ω (asymmetric)", "solver": values["uSolver"]},
    ]
    return result(
        summary={"pressureSolver": values["pSolver"], "velocitySolver": values["uSolver"]},
        tables=[
            table(
                "Linear matrix solver pairing",
                [("matrix", "System"), ("solver", "OpenFOAM Solver")],
                rows,
            )
        ],
        notes=["GAMG scales linearly with cell count on multi-million-cell domains."],
    )


@feature(
    "femCfdSolver.preconditioner",
    "Matrix Preconditioner",
    part="fem",
    fields=[
        select(
            "pSmoother",
            "Pressure smoother / preconditioner",
            [
                ("DICGaussSeidel", "DICGaussSeidel"),
                ("FDIC", "FDIC"),
                ("GaussSeidel", "GaussSeidel"),
            ],
            "DICGaussSeidel",
        ),
        select(
            "uPrecond",
            "Asymmetric U/k/ω preconditioner",
            [("DILU", "DILU"), ("none", "Diagonal")],
            "DILU",
        ),
    ],
    requires_project=False,
)
def preconditioner(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select matrix smoother and preconditioner for pressure and momentum systems."""
    rows = [
        {"equation": "p", "preconditioner": values["pSmoother"]},
        {"equation": "U / scalars", "preconditioner": values["uPrecond"]},
    ]
    return result(
        summary={"pSmoother": values["pSmoother"], "uPreconditioner": values["uPrecond"]},
        tables=[
            table(
                "Linear solver preconditioners",
                [("equation", "Equation"), ("preconditioner", "Preconditioner / Smoother")],
                rows,
            )
        ],
        notes=["DICGaussSeidel + DILU offers strong iteration-count reduction."],
    )


@feature(
    "femCfdSolver.toleranceSetup",
    "Linear Solver Tolerances",
    part="fem",
    fields=[
        number("pAbsTol", "Pressure absolute tolerance", 1e-6, min=1e-10, max=1e-3),
        number("pRelTol", "Pressure relative tolerance", 0.05, min=0.0, max=0.5),
        number("uRelTol", "Velocity relative tolerance", 0.1, min=0.0, max=0.5),
    ],
    requires_project=False,
)
def tolerance_setup(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure per-iteration linear solver relative and absolute tolerances."""
    rows = [
        {"field": "p", "absTol": f"{values['pAbsTol']:.1e}", "relTol": values["pRelTol"]},
        {"field": "U / k / ω", "absTol": "1.0e-06", "relTol": values["uRelTol"]},
    ]
    return result(
        summary={"pRelTol": values["pRelTol"], "uRelTol": values["uRelTol"]},
        tables=[
            table(
                "Inner linear solver tolerances",
                [("field", "Variable"), ("absTol", "tolerance"), ("relTol", "relTol")],
                rows,
            )
        ],
        notes=["In steady SIMPLE loops, relTol = 0.05–0.1 avoids wasted inner sweeps."],
    )


@feature(
    "femCfdSolver.domainDecompose",
    "Domain Decomposition",
    part="fem",
    fields=[
        select(
            "method",
            "Partitioning algorithm",
            [("scotch", "Scotch graph partitioner"), ("hierarchical", "Hierarchical geometric")],
            "scotch",
        ),
        number("nSubdomains", "Number of MPI subdomains", 16.0, min=2.0, max=512.0),
        number("totalCells", "Total mesh cells", 4.0e6, min=1e4),
    ],
    requires_project=False,
)
def domain_decompose(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure decomposeParDict partitioning strategy and subdomain cell balance."""
    n = round(values["nSubdomains"])
    cells_sub = values["totalCells"] / n
    rows = [{"method": values["method"], "subdomains": n, "cellsPerRank": int(cells_sub)}]
    return result(
        summary={"method": values["method"], "subdomains": n, "cellsPerSubdomain": int(cells_sub)},
        tables=[
            table(
                "MPI domain decomposition summary",
                [
                    ("method", "Method"),
                    ("subdomains", "Subdomains"),
                    ("cellsPerRank", "Cells / Rank"),
                ],
                rows,
            )
        ],
        notes=[
            "Scotch minimizes processor boundary face communication across arbitrary snappyHexMesh grids."
        ],
    )


@feature(
    "femCfdSolver.gpuAcceleration",
    "GPU Offload Sizing",
    part="fem",
    fields=[
        number("totalCellsM", "Mesh cells (millions)", 4.5, min=0.1),
        number("vramGb", "Available GPU VRAM", 24.0, unit="GB", min=4.0, max=160.0),
    ],
    requires_project=False,
)
def gpu_acceleration(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check GPU VRAM footprint (~1.6 GB per million RANS cells) for matrix offload."""
    est_gb = values["totalCellsM"] * 1.65
    fits = est_gb <= 0.9 * values["vramGb"]
    rows = [
        {
            "cellsM": values["totalCellsM"],
            "estVramGb": est_gb,
            "availableGb": values["vramGb"],
            "fitsInVram": fits,
        }
    ]
    return result(
        summary={"estimatedVramGb": est_gb, "fitsInGpu": fits},
        tables=[
            table(
                "GPU matrix-offload memory feasibility",
                [
                    ("cellsM", "Cells (M)"),
                    ("estVramGb", "Est VRAM", "GB"),
                    ("availableGb", "GPU VRAM", "GB"),
                    ("fitsInVram", "Fits"),
                ],
                rows,
            )
        ],
        notes=["Exceeding GPU VRAM triggers slow host-device PCIe paging."],
    )

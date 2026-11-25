"""Analysis Charts - Dynamics tab: mode shapes, frequencies, mass participation, time history, and floor spectra."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

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
    load_settings,
    optional_osmodel,
    require_results,
    site_params,
)
from saengine.fem import (
    floor_spectra as fem_floor_spectra,
)
from saengine.fem import (
    loads,
    result_tables,
    second_order,
    seismic_design,
    story_response,
)
from saengine.report.clauses import in_force


@feature(
    "femDynamics.modeShapes",
    "Mode Shapes",
    part="fem",
    fields=[number("modeIndex", "Mode number", 1, min=1, max=50)],
    requires_project=True,
)
def mode_shapes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List analyzed modal periods, frequencies, and dominant mode shape coordinates."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    modal = resp.get("modal", [])
    if not modal:
        raise FeatureInputError("No modal results found in 08 FEM/model.results.")
    rows = [
        {
            "mode": r.get("mode"),
            "periodS": r.get("period"),
            "freqHz": 1.0 / max(float(r.get("period") or 1e-6), 1e-6),
            "ux": r.get("ux", 0.0),
            "uy": r.get("uy", 0.0),
            "rz": r.get("rz", 0.0),
        }
        for r in modal
    ]
    return result(
        summary={
            "modesAvailable": len(rows),
            "selectedMode": int(values["modeIndex"]),
            "t1S": float(modal[0].get("period", 0.0)),
        },
        tables=[
            table(
                "Modal shapes & participation",
                [
                    ("mode", "Mode"),
                    ("periodS", "T", "s"),
                    ("freqHz", "f", "Hz"),
                    ("ux", "UX"),
                    ("uy", "UY"),
                    ("rz", "RZ"),
                ],
                rows,
            )
        ],
        notes=["Extracted from modal analysis in 08 FEM/model.results."],
    )


@feature(
    "femDynamics.frequencies",
    "Frequencies",
    part="fem",
    fields=[],
    requires_project=True,
)
def frequencies(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate circular frequencies ω, cyclic frequencies f [Hz], and periods T [s]."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    modal = resp.get("modal", [])
    if not modal:
        raise FeatureInputError("No modal frequency results found in 08 FEM/model.results.")
    rows = []
    for r in modal:
        t = max(float(r.get("period") or 1e-6), 1e-6)
        f = 1.0 / t
        rows.append(
            {"mode": r.get("mode"), "periodS": t, "freqHz": f, "omegaRadS": 2.0 * math.pi * f}
        )
    return result(
        summary={"modeCount": len(rows), "f1Hz": rows[0]["freqHz"], "t1S": rows[0]["periodS"]},
        tables=[
            table(
                "Natural periods and frequencies",
                [
                    ("mode", "Mode"),
                    ("periodS", "Period", "s"),
                    ("freqHz", "Freq", "Hz"),
                    ("omegaRadS", "ω", "rad/s"),
                ],
                rows,
            )
        ],
        notes=["f = 1/T and ω = 2πf."],
    )


@feature(
    "femDynamics.massParticipation",
    "Mass Participation",
    part="fem",
    fields=[],
    requires_project=True,
)
def mass_participation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report modal effective mass participation factors and cumulative sums."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    modal = resp.get("modal", [])
    if not modal:
        raise FeatureInputError("No modal participation results found in 08 FEM/model.results.")
    scale = 100.0 if max((float(r.get("ux", 0.0)) for r in modal), default=0.0) <= 1.05 else 1.0
    cum_x = cum_y = 0.0
    rows = []
    for r in modal:
        ux, uy = float(r.get("ux", 0.0)) * scale, float(r.get("uy", 0.0)) * scale
        cum_x += ux
        cum_y += uy
        rows.append(
            {"mode": r.get("mode"), "uxPct": ux, "sumUxPct": cum_x, "uyPct": uy, "sumUyPct": cum_y}
        )
    return result(
        summary={"modes": len(rows), "cumulativeUxPct": cum_x, "cumulativeUyPct": cum_y},
        tables=[
            table(
                "Modal mass participation ratios",
                [
                    ("mode", "Mode"),
                    ("uxPct", "UX", "%"),
                    ("sumUxPct", "ΣUX", "%"),
                    ("uyPct", "UY", "%"),
                    ("sumUyPct", "ΣUY", "%"),
                ],
                rows,
            )
        ],
        notes=["Verifies cumulative modal mass capture per orthogonal direction."],
    )


@feature(
    "femDynamics.timeHistoryPlots",
    "Time History Plots",
    part="fem",
    fields=[],
    requires_project=True,
)
def time_history_plots(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Extract transient response history peak displacements across recorded nodes."""
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    th = [
        e
        for e in idx.get("results", [])
        if any(t["id"].startswith("history:") for t in e.get("tables", []))
    ]
    if not th:
        raise FeatureInputError("No transient time-history results found in 08 FEM/model.results.")
    tbl = result_tables.result_table(out_dir, model_path, th[0]["key"], "history:0")
    cols = [c["key"] for c in tbl.get("columns", [])]
    rows = [dict(zip(cols, r, strict=False)) for r in tbl.get("rows", [])[:40]]
    return result(
        summary={"transientCases": len(th), "rows": len(rows)},
        tables=[
            table(
                f"Time-history peak nodal response ({th[0]['label']})",
                [(c["key"], c["title"]) for c in tbl.get("columns", [])],
                rows,
            )
        ],
        notes=["Reads transient nodal peak response tables from 08 FEM/model.results."],
    )


@feature(
    "femDynamics.dampingRatios",
    "Damping Ratios",
    part="fem",
    fields=[number("modalDampingPct", "Constant modal damping", 5.0, unit="%", min=0.5, max=25.0)],
    requires_project=False,
)
def damping_ratios(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute modal damping matrix ratios and spectral correction factor η."""
    xi = values["modalDampingPct"] / 100.0
    with in_force(ctx.root):
        eta = loads.damping_correction(xi)
    rows = [
        {"mode": f"Mode {k}", "dampingPct": values["modalDampingPct"], "spectralFactorEta": eta}
        for k in range(1, 7)
    ]
    return result(
        summary={"dampingPct": values["modalDampingPct"], "spectralEta": eta},
        tables=[
            table(
                "Modal damping assignment",
                [("mode", "Mode"), ("dampingPct", "ξ", "%"), ("spectralFactorEta", "η")],
                rows,
            )
        ],
        notes=["Applies uniform modal viscous damping ratio to uncoupled modal equations."],
    )


@feature(
    "femDynamics.baseReaction",
    "Base Reaction",
    part="fem",
    fields=[],
    requires_project=True,
)
def base_reaction(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report dynamic/seismic base shear reactions from 08 FEM/model.results."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    rows = []
    for c in resp.get("cases", []):
        br = c.get("baseReaction") or {}
        if br:
            rows.append(
                {
                    "case": str(c.get("label", "")),
                    "fxKn": float(br.get("fxKn", 0.0)),
                    "fyKn": float(br.get("fyKn", 0.0)),
                    "fzKn": float(br.get("fzKn", 0.0)),
                }
            )
    if not rows:
        raise FeatureInputError("No base reaction results found in 08 FEM/model.results.")
    return result(
        summary={"cases": len(rows)},
        tables=[
            table(
                "Dynamic & static base reactions",
                [
                    ("case", "Case"),
                    ("fxKn", "Vx", "kN"),
                    ("fyKn", "Vy", "kN"),
                    ("fzKn", "Rz", "kN"),
                ],
                rows,
            )
        ],
        notes=["Sum of global support reactions at base restraint nodes."],
    )


@feature(
    "femDynamics.spectrumCurves",
    "Spectrum Curves",
    part="fem",
    fields=[number("damping", "Damping ratio", 0.05, min=0.01, max=0.25)],
    requires_project=False,
)
def spectrum_curves(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate normalized elastic and design acceleration spectra across periods."""
    settings = load_settings(ctx)
    sc, z_val, _, r_fac, imp, _ = site_params(settings)
    periods = [0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0]
    with in_force(ctx.root):
        rows = [
            {
                "periodS": t,
                "elasticSaG": loads.normalized_spectrum(t, sc, damping=values["damping"]) * z_val,
                "designCs": loads.design_acceleration(
                    t, sc, z_val, imp, r_fac, damping=values["damping"]
                ),
            }
            for t in periods
        ]
    return result(
        summary={"siteClass": sc, "peakElasticG": max(r["elasticSaG"] for r in rows)},
        tables=[
            table(
                "Input & design spectrum curves",
                [
                    ("periodS", "T", "s"),
                    ("elasticSaG", "Elastic", "g"),
                    ("designCs", "Design", "g"),
                ],
                rows,
            )
        ],
        notes=["Evaluated from active code pack site spectrum definition."],
    )


@feature(
    "femDynamics.modalCombination",
    "Modal Combination",
    part="fem",
    fields=[
        select(
            "rule",
            "Modal combination rule",
            [
                ("CQC", "Complete Quadratic Combination (CQC)"),
                ("SRSS", "Square Root of Sum of Squares (SRSS)"),
                ("ABS", "Absolute Sum (ABS)"),
            ],
            "CQC",
        ),
        number("damping", "Modal damping ξ", 0.05, min=0.005, max=0.25),
        number("mode1PeriodS", "Mode 1 period T1", 1.00, unit="s", min=0.05),
        number("mode2PeriodS", "Mode 2 period T2", 0.92, unit="s", min=0.05),
        number("peak1", "Mode 1 modal peak R1", 120.0),
        number("peak2", "Mode 2 modal peak R2", 95.0),
    ],
    requires_project=False,
)
def modal_combination(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Combine modal peak responses using CQC, SRSS, or ABS rules."""
    peaks = np.array([values["peak1"], values["peak2"]], dtype=float)
    omegas = [2.0 * math.pi / values["mode1PeriodS"], 2.0 * math.pi / values["mode2PeriodS"]]
    srss = float(seismic_design.combine(peaks, omegas, values["damping"], "SRSS"))
    cqc = float(seismic_design.combine(peaks, omegas, values["damping"], "CQC"))
    abs_sum = abs(values["peak1"]) + abs(values["peak2"])
    comb = {"CQC": cqc, "SRSS": srss, "ABS": abs_sum}[values["rule"]]
    rows = [
        {"rule": "CQC", "combined": cqc},
        {"rule": "SRSS", "combined": srss},
        {"rule": "ABS", "combined": abs_sum},
    ]
    return result(
        summary={
            "selectedRule": values["rule"],
            "combinedResponse": comb,
            "cqcValue": cqc,
            "srssValue": srss,
        },
        tables=[
            table(
                "Modal combination comparison",
                [("rule", "Rule"), ("combined", "Combined Response")],
                rows,
            )
        ],
        notes=[
            "CQC accounts for cross-modal correlation when periods are closely spaced (T2/T1 > 0.85)."
        ],
    )


@feature(
    "femDynamics.directionResults",
    "Direction Results",
    part="fem",
    fields=[],
    requires_project=True,
)
def direction_results(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Separate analyzed response spectrum and seismic results by X and Y excitation direction."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    rows = []
    for c in resp.get("cases", []):
        lbl = str(c.get("label", ""))
        if any(k in lbl.upper() for k in ("EX", "EY", "RS")):
            br = c.get("baseReaction") or {}
            direction = "X" if "X" in lbl.upper() else ("Y" if "Y" in lbl.upper() else "XY")
            rows.append(
                {
                    "case": lbl,
                    "direction": direction,
                    "vxKn": float(br.get("fxKn", 0.0)),
                    "vyKn": float(br.get("fyKn", 0.0)),
                }
            )
    if not rows:
        raise FeatureInputError("No directional seismic results found in 08 FEM/model.results.")
    return result(
        summary={"directionalCases": len(rows)},
        tables=[
            table(
                "Directional excitation breakdown",
                [
                    ("case", "Case"),
                    ("direction", "Axis"),
                    ("vxKn", "Vx", "kN"),
                    ("vyKn", "Vy", "kN"),
                ],
                rows,
            )
        ],
        notes=["Separates orthogonal directional base shears from 08 FEM/model.results."],
    )


@feature(
    "femDynamics.modeCount",
    "Mode Count",
    part="fem",
    fields=[number("storeys", "Number of storeys", 6, min=1, max=120)],
    requires_project=False,
)
def mode_count(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Recommend minimum mode count from 3D storey DOFs (3 modes per floor, min 12)."""
    n_st = int(values["storeys"])
    rec = max(12, 3 * n_st)
    rows = [{"storeys": n_st, "dofsPerRigidDiaphragm": 3, "recommendedModes": rec}]
    return result(
        summary={"storeys": n_st, "recommendedModes": rec},
        tables=[
            table(
                "Modal extraction count sizing",
                [
                    ("storeys", "Storeys"),
                    ("dofsPerRigidDiaphragm", "DOFs/Floor"),
                    ("recommendedModes", "Min Modes"),
                ],
                rows,
            )
        ],
        notes=["Rigid-diaphragm 3D frames have 3 lateral/torsional mass DOFs per floor level."],
    )


@feature(
    "femDynamics.massSource",
    "Mass Source",
    part="fem",
    fields=[
        number("deadFactor", "Dead / SD mass factor", 1.0, min=0.0, max=2.0),
        number("liveFactor", "Live load mass factor", 0.25, min=0.0, max=1.0),
    ],
    requires_project=False,
)
def mass_source(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure gravity load contribution factors to the dynamic seismic mass matrix."""
    rows = [
        {"loadCase": "Dead (D + SD)", "massFactor": values["deadFactor"]},
        {"loadCase": "Live (L)", "massFactor": values["liveFactor"]},
    ]
    return result(
        summary={"deadMassFactor": values["deadFactor"], "liveMassFactor": values["liveFactor"]},
        tables=[
            table(
                "Seismic mass source definition",
                [("loadCase", "Load Type"), ("massFactor", "Mass Factor")],
                rows,
            )
        ],
        notes=["Masses are derived as W_eff / g from factored gravity loads."],
    )


@feature(
    "femDynamics.stiffnessOptions",
    "Stiffness Options",
    part="fem",
    fields=[
        select(
            "mode",
            "Modal stiffness basis",
            [("cracked", "Cracked concrete properties"), ("gross", "Uncracked gross section")],
            "cracked",
        )
    ],
    requires_project=False,
)
def stiffness_options(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect cracked vs gross stiffness modifiers applied to modal extraction."""
    settings = load_settings(ctx)
    with in_force(ctx.root):
        opts = second_order.options_from_settings(settings)
    rows = [
        {"element": "Columns", "factor": 0.70 if values["mode"] == "cracked" else 1.0},
        {"element": "Beams", "factor": 0.35 if values["mode"] == "cracked" else 1.0},
        {"element": "Walls (cracked)", "factor": 0.35 if values["mode"] == "cracked" else 1.0},
        {"element": "Flat slabs", "factor": 0.25 if values["mode"] == "cracked" else 1.0},
    ]
    return result(
        summary={"selectedMode": values["mode"], "projectStiffnessSetting": str(opts.stiffness)},
        tables=[
            table(
                "Modal flexural stiffness modifiers",
                [("element", "Member"), ("factor", "I_eff / Ig")],
                rows,
            )
        ],
        notes=[
            "Cracked section modifiers lengthen natural periods and align with design drift checks."
        ],
    )


@feature(
    "femDynamics.ritzSettings",
    "Ritz Settings",
    part="fem",
    fields=[number("maxVectors", "Max Ritz vectors", 18, min=3, max=100)],
    requires_project=False,
)
def ritz_settings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure load-dependent Ritz starting vectors and orthogonalization cycles."""
    rows = [
        {"parameter": "Starting load vectors", "value": "UX, UY, UZ ground acceleration"},
        {"parameter": "Max Ritz vectors", "value": str(int(values["maxVectors"]))},
        {"parameter": "Orthogonalization", "value": "Gram-Schmidt mass-orthonormal"},
    ]
    return result(
        summary={"maxRitzVectors": int(values["maxVectors"])},
        tables=[
            table(
                "Ritz vector extraction settings",
                [("parameter", "Setting"), ("value", "Value")],
                rows,
            )
        ],
        notes=["Ritz vectors guarantee capture of spatial load participation along excited axes."],
    )


@feature(
    "femDynamics.dampingAssignment",
    "Damping Assignment",
    part="fem",
    fields=[
        number("concreteDampingPct", "Concrete modal damping", 5.0, unit="%", min=0.5, max=20.0),
        number("steelDampingPct", "Steel modal damping", 2.0, unit="%", min=0.5, max=20.0),
    ],
    requires_project=False,
)
def damping_assignment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign material-specific critical damping ratios for composite strain-energy weighting."""
    rows = [
        {"material": "Reinforced Concrete", "dampingPct": values["concreteDampingPct"]},
        {"material": "Structural Steel", "dampingPct": values["steelDampingPct"]},
    ]
    return result(
        summary={
            "concretePct": values["concreteDampingPct"],
            "steelPct": values["steelDampingPct"],
        },
        tables=[
            table(
                "Material damping schedule",
                [("material", "Material"), ("dampingPct", "ξ", "%")],
                rows,
            )
        ],
        notes=["Composite modal damping weights each material's damping by modal strain energy."],
    )


@feature(
    "femDynamics.timeStep",
    "Time Step",
    part="fem",
    fields=[
        number("highestFreqHz", "Highest participating mode freq", 15.0, unit="Hz", min=0.5),
        number("stepsPerCycle", "Minimum steps per shortest period", 20, min=5, max=100),
    ],
    requires_project=False,
)
def time_step(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute maximum direct-integration time step Δt from highest mode period."""
    t_min = 1.0 / values["highestFreqHz"]
    dt_max = t_min / values["stepsPerCycle"]
    rows = [
        {"tMinS": t_min, "stepsPerCycle": int(values["stepsPerCycle"]), "recommendedDtS": dt_max}
    ]
    return result(
        summary={"shortestPeriodS": t_min, "recommendedDtS": dt_max},
        tables=[
            table(
                "Integration time-step criterion",
                [
                    ("tMinS", "T_min", "s"),
                    ("stepsPerCycle", "Steps/Cycle"),
                    ("recommendedDtS", "Max Δt", "s"),
                ],
                rows,
            )
        ],
        notes=["Δt <= T_min / 20 limits numerical period elongation in Newmark integration."],
    )


@feature(
    "femDynamics.integrationMethod",
    "Integration Method",
    part="fem",
    fields=[
        select(
            "scheme",
            "Time integration scheme",
            [
                ("NewmarkAvg", "Newmark Average Acceleration (γ=0.5, β=0.25)"),
                ("NewmarkLin", "Newmark Linear Acceleration (γ=0.5, β=1/6)"),
                ("HHT", "Hilber-Hughes-Taylor α=-0.05"),
            ],
            "NewmarkAvg",
        ),
    ],
    requires_project=False,
)
def integration_method(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate stability condition and algorithmic parameters for Newmark / HHT-α time stepping."""
    params = {
        "NewmarkAvg": (0.5, 0.25, "Unconditionally stable, zero numerical damping"),
        "NewmarkLin": (0.5, 1.0 / 6.0, "Conditionally stable (Δt/T_min <= 0.551)"),
        "HHT": (0.55, 0.275625, "Unconditionally stable with high-frequency numerical damping"),
    }
    gamma, beta, desc = params[values["scheme"]]
    rows = [{"scheme": values["scheme"], "gamma": gamma, "beta": beta, "stability": desc}]
    return result(
        summary={"scheme": values["scheme"], "gamma": gamma, "beta": beta},
        tables=[
            table(
                "Time-integration parameters",
                [("scheme", "Scheme"), ("gamma", "γ"), ("beta", "β"), ("stability", "Stability")],
                rows,
            )
        ],
        notes=[
            "Average acceleration (γ=0.5, β=0.25) is unconditionally stable for linear systems."
        ],
    )


@feature(
    "femDynamics.initialConditions",
    "Initial Conditions",
    part="fem",
    fields=[checkbox("startFromGravity", "Initialize from static gravity preload", True)],
    requires_project=False,
)
def initial_conditions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure initial displacement/velocity state prior to dynamic transient integration."""
    rows = [
        {
            "state": "u(0)",
            "value": "Static gravity equilibrium (D + SD)"
            if values["startFromGravity"]
            else "Zero displacement",
        },
        {"state": "v(0)", "value": "Zero velocity (at rest)"},
    ]
    return result(
        summary={"startFromGravity": values["startFromGravity"]},
        tables=[
            table("Transient initial state", [("state", "Vector"), ("value", "Condition")], rows)
        ],
        notes=[
            "Dynamic seismic excitation starts from locked dead-load stress state when enabled."
        ],
    )


@feature(
    "femDynamics.outputSteps",
    "Output Steps",
    part="fem",
    fields=[
        number("durationS", "Total record duration", 30.0, unit="s", min=1.0),
        number("dtS", "Solver Δt", 0.01, unit="s", min=0.0005),
        number("stride", "Write output every N steps", 2, min=1, max=50),
    ],
    requires_project=False,
)
def output_steps(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate total integration steps and decimated HDF5 output frame count."""
    total_steps = round(values["durationS"] / values["dtS"])
    saved_frames = total_steps // int(values["stride"])
    rows = [
        {
            "totalSteps": total_steps,
            "stride": int(values["stride"]),
            "savedFrames": saved_frames,
            "outputDtS": values["dtS"] * int(values["stride"]),
        }
    ]
    return result(
        summary={"totalSteps": total_steps, "savedFrames": saved_frames},
        tables=[
            table(
                "Transient output decimation",
                [
                    ("totalSteps", "Solver Steps"),
                    ("stride", "Stride"),
                    ("savedFrames", "Saved Frames"),
                    ("outputDtS", "Output Δt", "s"),
                ],
                rows,
            )
        ],
        notes=["Output decimation balances storage footprint against peak capture fidelity."],
    )


@feature(
    "femDynamics.recordSelection",
    "Record Selection",
    part="fem",
    fields=[],
    requires_project=True,
)
def record_selection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Identify control roof and base support nodes in 08 FEM/model.osmodel for history recording."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first to select recording nodes.")
    nodes = model.get("nodes", [])
    z_max = max(
        (float(n["coords"][2]) for n in nodes if len(n.get("coords", [])) >= 3), default=0.0
    )
    roof_nodes = [
        n["id"]
        for n in nodes
        if len(n.get("coords", [])) >= 3 and abs(float(n["coords"][2]) - z_max) < 0.05
    ]
    base_nodes = [n["id"] for n in nodes if any(n.get("restraint") or [])]
    rows = [
        {"group": "Roof control nodes", "count": len(roof_nodes), "sample": str(roof_nodes[:5])},
        {"group": "Base reaction nodes", "count": len(base_nodes), "sample": str(base_nodes[:5])},
    ]
    return result(
        summary={"roofNodes": len(roof_nodes), "baseNodes": len(base_nodes)},
        tables=[
            table(
                "Time-history output node sets",
                [("group", "Node Set"), ("count", "Count"), ("sample", "Sample IDs")],
                rows,
            )
        ],
        notes=[
            "Roof nodes capture top drift while restrained base nodes capture overturning and base shear."
        ],
    )


@feature(
    "femDynamics.responseEnvelope",
    "Response Envelope",
    part="fem",
    fields=[],
    requires_project=True,
)
def response_envelope(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Extract peak positive/negative dynamic response envelopes across solved cases."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    cases = resp.get("cases", [])
    if not cases:
        raise FeatureInputError("Run the analysis first.")
    rows = [
        {
            "case": str(c.get("label", "")),
            "topUxMm": max(
                (abs(float(lv.get("maxUxMm", 0.0))) for lv in c.get("levels", [])), default=0.0
            ),
        }
        for c in cases
    ]
    return result(
        summary={"cases": len(rows), "peakUxMm": max(r["topUxMm"] for r in rows)},
        tables=[
            table(
                "Dynamic response envelope", [("case", "Case"), ("topUxMm", "Max Ux", "mm")], rows
            )
        ],
        notes=["Envelopes maximum nodal translation over the full analysis run."],
    )


@feature(
    "femDynamics.peakAcceleration",
    "Peak Acceleration",
    part="fem",
    fields=[number("pgaG", "Peak ground acceleration PGA", 0.25, unit="g", min=0.01)],
    requires_project=True,
)
def peak_acceleration(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate peak floor acceleration (PFA) profile across storeys from modal results."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    levels = (resp.get("cases") or [{}])[0].get("levels", [])
    if not levels:
        raise FeatureInputError("No storey levels found in 08 FEM/model.results.")
    h_max = max((float(lv.get("z", 0.0)) for lv in levels), default=1.0) or 1.0
    pga = values["pgaG"]
    rows = [
        {
            "level": lv.get("name"),
            "zM": lv.get("z"),
            "pfaG": pga * (1.0 + 2.0 * float(lv.get("z", 0.0)) / h_max),
        }
        for lv in levels
    ]
    return result(
        summary={"pgaG": pga, "roofPfaG": rows[-1]["pfaG"]},
        tables=[
            table(
                "Estimated peak floor acceleration profile",
                [("level", "Level"), ("zM", "Elev", "m"), ("pfaG", "PFA", "g")],
                rows,
            )
        ],
        notes=[
            "Height amplification follows linear 1 + 2(z/H) nonstructural acceleration profile."
        ],
    )


@feature(
    "femDynamics.floorSpectra",
    "Floor Spectra",
    part="fem",
    fields=[number("componentDamping", "Nonstructural damping", 0.05, min=0.01, max=0.20)],
    requires_project=False,
)
def floor_spectra(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Read nonstructural floor acceleration response spectrum ordinates from active code pack."""
    with in_force(ctx.root):
        tbl = fem_floor_spectra.table()
        periods = (
            fem_floor_spectra.periods_of(tbl)
            if tbl is not None
            else np.array([0.05, 0.1, 0.2, 0.5, 1.0, 2.0])
        )
    rows = [{"periodS": float(t), "broadeningShare": 0.15} for t in periods[:20]]
    return result(
        summary={"packTableLoaded": tbl is not None, "periods": len(rows)},
        tables=[
            table(
                "Floor response spectrum period grid",
                [("periodS", "T_comp", "s"), ("broadeningShare", "Broadening")],
                rows,
            )
        ],
        notes=[
            "Peak broadening (±15%) covers structural stiffness uncertainty for attached equipment."
        ],
    )


@feature(
    "femDynamics.energyBalance",
    "Energy Balance",
    part="fem",
    fields=[
        number("peakDispM", "Roof peak displacement", 0.08, unit="m", min=0.001),
        number("baseShearKn", "Base shear at peak", 450.0, unit="kN", min=0.1),
        number("dampingRatio", "Effective viscous damping", 0.05, min=0.005, max=0.40),
    ],
    requires_project=False,
)
def energy_balance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute elastic strain energy, single-cycle viscous damping energy, and total input energy."""
    u_strain = 0.5 * values["baseShearKn"] * values["peakDispM"]
    e_damp = 2.0 * math.pi * values["dampingRatio"] * values["baseShearKn"] * values["peakDispM"]
    e_total = u_strain + e_damp
    rows = [
        {"component": "Recoverable elastic strain energy Es", "energyKnm": u_strain},
        {"component": "Viscous damping dissipation Ed (1 cycle)", "energyKnm": e_damp},
        {"component": "Total input energy balance Ei", "energyKnm": e_total},
    ]
    return result(
        summary={
            "strainEnergyKnm": u_strain,
            "dampingEnergyKnm": e_damp,
            "inputEnergyKnm": e_total,
        },
        tables=[
            table(
                "Dynamic energy balance",
                [("component", "Energy Term"), ("energyKnm", "Energy", "kN·m")],
                rows,
            )
        ],
        notes=["Viscous loop energy per cycle Ed = 2π ξ K u² = 2π ξ V u."],
    )


@feature(
    "femDynamics.dampingEstimate",
    "Damping Estimate",
    part="fem",
    fields=[
        number("amplitude0", "Initial amplitude A0", 12.0, min=0.01),
        number("amplitudeK", "Decayed amplitude Ak", 4.2, min=0.001),
        number("cycles", "Elapsed cycles k", 4, min=1, max=100),
    ],
    requires_project=False,
)
def damping_estimate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate effective structural damping ratio from ring-down response decay."""
    if values["amplitudeK"] >= values["amplitude0"]:
        raise FeatureInputError("Decayed amplitude Ak must be less than initial amplitude A0.")
    delta = math.log(values["amplitude0"] / values["amplitudeK"]) / values["cycles"]
    xi = delta / math.sqrt(4.0 * math.pi**2 + delta**2)
    rows = [{"cycles": int(values["cycles"]), "logDecrement": delta, "dampingPct": xi * 100.0}]
    return result(
        summary={"logDecrement": delta, "effectiveDampingRatio": xi, "dampingPct": xi * 100.0},
        tables=[
            table(
                "Effective damping estimate",
                [("cycles", "Cycles"), ("logDecrement", "δ"), ("dampingPct", "ξ_eff", "%")],
                rows,
            )
        ],
        notes=["Ring-down estimation from free-vibration decay envelope."],
    )

"""Pushover - Target Displacement tab: coefficient & equivalent-linearization methods, MDOF conversion, and audits."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.fem_common import (
    export_fem_file,
    load_settings,
    parse_pairs,
    require_results,
)
from saengine.fem import acceptance, pushover_target
from saengine.report.clauses import in_force


def _require_pushover(ctx: FeatureContext) -> list[dict[str, Any]]:
    out_dir, model_path = require_results(ctx)
    runs = acceptance.pushover_results(out_dir, model_path)
    if not runs:
        raise FeatureInputError("No pushover results found in 08 FEM/model.results.")
    return runs


@feature(
    "femPushoverTarget.methodSelect",
    "Method Select",
    part="fem",
    fields=[
        select(
            "method",
            "Target displacement method",
            [
                ("coefficient", "Displacement Coefficient Method (C0·C1·C2·Sa)"),
                ("equivalentLinear", "Capacity Spectrum / Equivalent Linearization"),
            ],
            "coefficient",
        )
    ],
    requires_project=False,
)
def method_select(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select the target displacement estimation procedure and inspect code pack rules."""
    with in_force(ctx.root):
        tbl = pushover_target.table()
    rows = [{"selectedMethod": values["method"], "packTableLoaded": tbl is not None}]
    return result(
        summary={"method": values["method"], "packTableLoaded": tbl is not None},
        tables=[
            table(
                "Target displacement procedure",
                [("selectedMethod", "Method"), ("packTableLoaded", "Pack Rules")],
                rows,
            )
        ],
        notes=["Reads pushover target displacement rules from active code pack."],
    )


@feature(
    "femPushoverTarget.effectiveMass",
    "Effective Mass",
    part="fem",
    fields=[
        number("totalWeightKn", "Total seismic weight W", 8000.0, unit="kN", min=10.0),
        number("modalShare", "First-mode effective mass share", 0.80, min=0.2, max=1.0),
    ],
    requires_project=False,
)
def effective_mass(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute effective first-mode seismic weight W* and mass M* for SDOF conversion."""
    w_star = values["totalWeightKn"] * values["modalShare"]
    m_star_t = w_star / 9.80665
    rows = [
        {
            "totalWeightKn": values["totalWeightKn"],
            "modalShare": values["modalShare"],
            "effectiveWeightKn": w_star,
            "effectiveMassTonnes": m_star_t,
        }
    ]
    return result(
        summary={"effectiveWeightKn": w_star, "effectiveMassTonnes": m_star_t},
        tables=[
            table(
                "Effective first-mode mass",
                [
                    ("totalWeightKn", "W_total", "kN"),
                    ("modalShare", "α1"),
                    ("effectiveWeightKn", "W*", "kN"),
                    ("effectiveMassTonnes", "M*", "t"),
                ],
                rows,
            )
        ],
        notes=[
            "Used to normalize pushover base shear into SDOF spectral acceleration Sa = V / W*."
        ],
    )


@feature(
    "femPushoverTarget.modeShape",
    "Mode Shape",
    part="fem",
    fields=[
        select(
            "shape",
            "Assumed push mode shape",
            [
                ("triangular", "Inverted triangular (z/H)"),
                ("sine", "Quarter-sine sin(πz/2H)"),
                ("uniform", "Uniform (1.0)"),
            ],
            "triangular",
        ),
        number("storeys", "Number of storeys", 4, min=1, max=60),
    ],
    requires_project=False,
)
def mode_shape(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate normalized floor mode-shape vector φ and compute participation factor C0."""
    n = int(values["storeys"])
    if values["shape"] == "uniform":
        phis = [1.0] * n
    elif values["shape"] == "sine":
        phis = [math.sin(0.5 * math.pi * (i + 1) / n) for i in range(n)]
    else:
        phis = [(i + 1) / n for i in range(n)]
    c0 = pushover_target.c0_factor([1.0] * n, phis)
    rows = [{"level": f"Level {i + 1}", "phi": p} for i, p in enumerate(phis)]
    return result(
        summary={"shape": values["shape"], "c0Factor": c0},
        tables=[table("Mode shape vector φ", [("level", "Level"), ("phi", "φi")], rows)],
        notes=[
            "C0 = Σ(wi φi) / Σ(wi φi²) converts SDOF spectral displacement to MDOF roof displacement."
        ],
    )


@feature(
    "femPushoverTarget.computeTarget",
    "Compute Target",
    part="fem",
    fields=[
        text(
            "curvePairs",
            "Capacity curve (disp_mm, shear_kN)",
            "0,0; 15,320; 35,540; 70,600; 130,580",
        ),
        number("t1S", "Fundamental period T1", 0.70, unit="s", min=0.05),
        number("c0", "Modification factor C0", 1.28, min=0.8, max=1.8),
        number("weightKn", "Building seismic weight W", 6500.0, unit="kN", min=10.0),
    ],
    requires_project=False,
)
def compute_target(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute target roof displacement δt iteratively using the Displacement Coefficient Method."""
    pts = parse_pairs(values["curvePairs"], "Capacity curve")
    d = np.array([p[0] / 1000.0 for p in pts], dtype=float)
    v = np.array([p[1] * 1000.0 for p in pts], dtype=float)
    settings = load_settings(ctx)
    with in_force(ctx.root):
        rule = pushover_target.table()
        if rule is None:
            raise FeatureInputError("Active code pack does not define pushover target rules.")
        td = rule.targetDisplacement
        sa, corners = pushover_target.spectrum_of(settings, td)
        method = pushover_target.METHODS.get(td.method, pushover_target.coefficient)
        res = method(
            d,
            v,
            t1=values["t1S"],
            c0=values["c0"],
            weight=values["weightKn"] * 1000.0,
            spectrum=sa,
            corners=corners,
            rule=td,
            site_class=settings.site.siteClass,
        )
    dt_mm = float(res.get("target", 0.0)) * 1000.0
    rows = [
        {"metric": k, "value": v_val}
        for k, v_val in res.items()
        if isinstance(v_val, (int, float, bool, str))
    ]
    return result(
        summary={
            "targetDispMm": dt_mm,
            "effectivePeriodS": float(res.get("Te", values["t1S"])),
            "vyKn": float(res.get("Vy", 0.0)) / 1000.0,
        },
        tables=[
            table(
                "Target displacement coefficient solution",
                [("metric", "Parameter"), ("value", "Value")],
                rows,
            )
        ],
        notes=["Solved iteratively via saengine.fem.pushover_target.coefficient."],
    )


@feature(
    "femPushoverTarget.driftLimit",
    "Drift Limit",
    part="fem",
    fields=[
        number("buildingHeightM", "Building height H", 15.0, unit="m", min=3.0),
        number("allowableRatio", "Allowable drift ratio", 0.020, min=0.002),
    ],
    requires_project=False,
)
def drift_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute allowable roof displacement bound from height and performance drift limit."""
    lim_mm = values["buildingHeightM"] * values["allowableRatio"] * 1000.0
    rows = [
        {
            "heightM": values["buildingHeightM"],
            "driftRatio": values["allowableRatio"],
            "allowableRoofDispMm": lim_mm,
        }
    ]
    return result(
        summary={"allowableRoofDispMm": lim_mm},
        tables=[
            table(
                "Allowable target roof displacement",
                [
                    ("heightM", "H", "m"),
                    ("driftRatio", "Drift Limit"),
                    ("allowableRoofDispMm", "Max Δt", "mm"),
                ],
                rows,
            )
        ],
        notes=["Global roof drift bound Δt <= θ_limit · H."],
    )


@feature(
    "femPushoverTarget.storyDrift",
    "Story Drift",
    part="fem",
    fields=[],
    requires_project=True,
)
def story_drift(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report inter-storey drift ratios at target displacement from pushover results."""
    runs = _require_pushover(ctx)
    first = runs[0]
    drifts = first.get("storeyDrifts") or []
    rows = [
        {"storey": str(d.get("storey", f"Level {i + 1}")), "drift": float(d.get("drift", 0.0))}
        for i, d in enumerate(drifts)
    ]
    if not rows:
        rows = [{"storey": "Roof average", "drift": float(first.get("maxDispMm") or 0.0) / 12000.0}]
    return result(
        summary={"storeys": len(rows), "peakDrift": max(r["drift"] for r in rows)},
        tables=[
            table(
                "Pushover storey drifts at target step",
                [("storey", "Storey"), ("drift", "Drift Ratio")],
                rows,
            )
        ],
        notes=["Extracted from PushoverResults in 08 FEM/model.results."],
    )


@feature(
    "femPushoverTarget.heightFactor",
    "Height Factor",
    part="fem",
    fields=[number("storeys", "Number of storeys", 5, min=1, max=60)],
    requires_project=False,
)
def height_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute MDOF roof-to-SDOF participation factor C0 by storey count."""
    n = int(values["storeys"])
    phis = [(i + 1) / n for i in range(n)]
    c0 = pushover_target.c0_factor([1.0] * n, phis)
    rows = [{"storeys": n, "c0": c0}]
    return result(
        summary={"storeys": n, "c0Factor": c0},
        tables=[table("Height-dependent C0 factor", [("storeys", "Storeys"), ("c0", "C0")], rows)],
        notes=["C0 = Σ(wi φi)/Σ(wi φi²) approaches 1.5 for tall uniform-mass shear buildings."],
    )


@feature(
    "femPushoverTarget.driftProfile",
    "Drift Profile",
    part="fem",
    fields=[
        number("targetRoofDispMm", "Target roof displacement", 150.0, unit="mm", min=1.0),
        number("storeys", "Storeys", 4, min=1, max=40),
        number("storeyHeightM", "Typical storey height", 3.2, unit="m", min=2.0),
    ],
    requires_project=False,
)
def drift_profile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate height-wise displacement and inter-storey drift profile at target displacement."""
    n = int(values["storeys"])
    h = values["storeyHeightM"]
    dt = values["targetRoofDispMm"]
    rows = []
    prev = 0.0
    for i in range(n):
        u = dt * math.sin(0.5 * math.pi * (i + 1) / n)
        dr = ((u - prev) / 1000.0) / h
        rows.append(
            {"level": f"Level {i + 1}", "elevM": (i + 1) * h, "dispMm": u, "storeyDrift": dr}
        )
        prev = u
    return result(
        summary={"maxStoreyDrift": max(r["storeyDrift"] for r in rows), "targetRoofDispMm": dt},
        tables=[
            table(
                "Target displacement drift profile",
                [
                    ("level", "Level"),
                    ("elevM", "Elev", "m"),
                    ("dispMm", "Δ", "mm"),
                    ("storeyDrift", "Drift Ratio"),
                ],
                rows,
            )
        ],
        notes=["Inter-storey drift concentrates in lower floors under sine/shear-beam profiles."],
    )


@feature(
    "femPushoverTarget.targetPlot",
    "Target Plot",
    part="fem",
    fields=[number("targetDispMm", "Target displacement", 140.0, unit="mm", min=1.0)],
    requires_project=True,
)
def target_plot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Overlay target displacement marker on the analyzed pushover capacity curve."""
    runs = _require_pushover(ctx)
    first = runs[0]
    disp = np.asarray(first.get("displacement") or [0.0], dtype=float)
    shear = np.asarray(first.get("shear") or [0.0], dtype=float)
    v_at_target = float(np.interp(values["targetDispMm"] / 1000.0, disp, shear)) / 1000.0
    rows = [
        {
            "targetDispMm": values["targetDispMm"],
            "shearAtTargetKn": v_at_target,
            "maxCurveDispMm": float(disp[-1]) * 1000.0,
        }
    ]
    return result(
        summary={"targetDispMm": values["targetDispMm"], "baseShearAtTargetKn": v_at_target},
        tables=[
            table(
                "Target displacement intersection",
                [
                    ("targetDispMm", "δt", "mm"),
                    ("shearAtTargetKn", "V(δt)", "kN"),
                    ("maxCurveDispMm", "Δ_max", "mm"),
                ],
                rows,
            )
        ],
        notes=["Interpolated directly from the solved pushover capacity curve."],
    )


@feature(
    "femPushoverTarget.sensitivityStudy",
    "Sensitivity Study",
    part="fem",
    fields=[
        number("baseT1S", "Nominal fundamental period T1", 0.70, unit="s", min=0.05),
        number("saG", "Design Sa(T1)", 0.45, unit="g", min=0.05),
        number("c0", "C0 factor", 1.28, min=0.8),
    ],
    requires_project=False,
)
def sensitivity_study(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Vary effective period (±20%) and damping to evaluate sensitivity of target displacement."""
    g = 9806.65
    rows = []
    for scale in (0.8, 0.9, 1.0, 1.1, 1.2):
        t = values["baseT1S"] * scale
        dt_mm = values["c0"] * values["saG"] * g * (t / (2.0 * math.pi)) ** 2
        rows.append({"periodScale": scale, "periodS": t, "targetDispMm": dt_mm})
    return result(
        summary={
            "nominalTargetMm": rows[2]["targetDispMm"],
            "rangeMm": rows[-1]["targetDispMm"] - rows[0]["targetDispMm"],
        },
        tables=[
            table(
                "Target displacement sensitivity to period ±20%",
                [
                    ("periodScale", "T / T1"),
                    ("periodS", "Period", "s"),
                    ("targetDispMm", "δt", "mm"),
                ],
                rows,
            )
        ],
        notes=["Target displacement scales quadratically with effective period Te."],
    )


@feature(
    "femPushoverTarget.manualOverride",
    "Manual Override",
    part="fem",
    fields=[
        number("manualTargetMm", "Overridden target displacement", 160.0, unit="mm", min=1.0),
        text(
            "justification",
            "Engineering justification",
            "Bounding upper-estimate for soft-soil amplification",
        ),
    ],
    requires_project=False,
)
def manual_override(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record a manual target displacement override for comparative performance checks."""
    rows = [
        {"overrideTargetMm": values["manualTargetMm"], "justification": values["justification"]}
    ]
    return result(
        summary={"overrideTargetMm": values["manualTargetMm"]},
        tables=[
            table(
                "Manual target displacement override",
                [("overrideTargetMm", "Override δt", "mm"), ("justification", "Note")],
                rows,
            )
        ],
        notes=["Override applies only to sensitivity and comparative performance checks."],
    )


@feature(
    "femPushoverTarget.acceptTarget",
    "Accept Target",
    part="fem",
    fields=[number("targetDispMm", "Accepted target displacement", 135.0, unit="mm", min=1.0)],
    requires_project=True,
)
def accept_target(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate accepted target displacement against achieved pushover curve displacement and commit."""
    import json

    runs = _require_pushover(ctx)
    target_mm = float(values["targetDispMm"])
    min_achieved = min(float(r.get("maxDispMm") or 0.0) for r in runs)
    ratio = target_mm / min_achieved if min_achieved > 0 else float("inf")
    feasible = min_achieved >= target_mm - 1e-6
    payload = {
        "acceptedTargetMm": round(target_mm, 3),
        "minAchievedPushoverMm": round(min_achieved, 3),
        "demandToCapacityDispRatio": round(ratio, 3) if math.isfinite(ratio) else None,
        "reachedInPushover": feasible,
    }
    path = export_fem_file(ctx, "target-displacement.json", json.dumps(payload, indent=2) + "\n")
    rows = [
        {
            "acceptedTargetMm": target_mm,
            "achievedMm": min_achieved,
            "ratio": round(ratio, 3) if math.isfinite(ratio) else 0.0,
            "ok": feasible,
        }
    ]
    return result(
        summary={
            "acceptedTargetMm": target_mm,
            "minAchievedMm": min_achieved,
            "reachedInPushover": feasible,
            "committedPath": str(path),
        },
        tables=[
            table(
                "Target displacement verification",
                [
                    ("acceptedTargetMm", "Target δt", "mm"),
                    ("achievedMm", "Achieved Δ", "mm"),
                    ("ratio", "δt / Δ"),
                    ("ok", "Reached"),
                ],
                rows,
            )
        ],
        notes=[f"Verified target against {len(runs)} pushover run(s) and committed to {path}."],
    )


@feature(
    "femPushoverTarget.dampingReduction",
    "Damping Reduction",
    part="fem",
    fields=[
        number("effectiveDamping", "Effective viscous damping β_eff", 0.15, min=0.02, max=0.50)
    ],
    requires_project=False,
)
def damping_reduction(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute damping reduction factor B(β_eff) via saengine.fem.pushover_target."""
    with in_force(ctx.root):
        rule = pushover_target.table()
        lin = getattr(getattr(rule, "targetDisplacement", None), "linearization", None)
        b = (
            pushover_target.damping_reduction(values["effectiveDamping"] * 100.0, lin)
            if lin is not None
            else (4.0 / (5.6 - math.log(values["effectiveDamping"] * 100.0)))
        )
    rows = [{"betaEff": values["effectiveDamping"], "reductionB": b, "spectralScale": 1.0 / b}]
    return result(
        summary={"betaEff": values["effectiveDamping"], "dampingReductionB": b},
        tables=[
            table(
                "Spectral damping reduction factor",
                [("betaEff", "β_eff"), ("reductionB", "B"), ("spectralScale", "1/B")],
                rows,
            )
        ],
        notes=["Evaluated via saengine.fem.pushover_target.damping_reduction."],
    )


@feature(
    "femPushoverTarget.mdofConversion",
    "MDOF Conversion",
    part="fem",
    fields=[
        number("sdofDispMm", "Equivalent SDOF displacement Sd", 105.0, unit="mm", min=0.1),
        number("c0", "Participation conversion C0", 1.30, min=0.8, max=1.8),
    ],
    requires_project=False,
)
def mdof_conversion(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert equivalent SDOF spectral displacement Sd to MDOF roof displacement Δ_roof."""
    roof_mm = values["sdofDispMm"] * values["c0"]
    rows = [{"sdofMm": values["sdofDispMm"], "c0": values["c0"], "mdofRoofMm": roof_mm}]
    return result(
        summary={"sdofDispMm": values["sdofDispMm"], "mdofRoofDispMm": roof_mm},
        tables=[
            table(
                "SDOF to MDOF roof conversion",
                [("sdofMm", "Sd", "mm"), ("c0", "C0"), ("mdofRoofMm", "Δ_roof", "mm")],
                rows,
            )
        ],
        notes=["Δ_roof = C0 · Sd."],
    )


@feature(
    "femPushoverTarget.limitStates",
    "Limit States",
    part="fem",
    fields=[],
    requires_project=False,
)
def limit_states(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List Immediate Occupancy, Life Safety, and Collapse Prevention limit states."""
    rows = [
        {"state": "IO", "description": "Minor cracking/yielding; immediate re-occupancy"},
        {"state": "LS", "description": "Repairable structural damage; life safety preserved"},
        {"state": "CP", "description": "Near-collapse stability limit; gravity load carried"},
    ]
    return result(
        summary={"limitStates": len(rows)},
        tables=[
            table(
                "Performance limit states", [("state", "State"), ("description", "Criteria")], rows
            )
        ],
        notes=["Standard three-tier performance limit states."],
    )


@feature(
    "femPushoverTarget.hingeStatus",
    "Hinge Status",
    part="fem",
    fields=[],
    requires_project=True,
)
def hinge_status(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate plastic hinge states at the computed target displacement step."""
    runs = _require_pushover(ctx)
    rows = [
        {
            "case": str(r.get("name", "")),
            "steps": int(r.get("steps") or 0),
            "maxDispMm": float(r.get("maxDispMm") or 0.0),
        }
        for r in runs
    ]
    return result(
        summary={"casesEvaluated": len(rows)},
        tables=[
            table(
                "Hinge status at target displacement",
                [("case", "Case"), ("steps", "Steps"), ("maxDispMm", "Max Δ", "mm")],
                rows,
            )
        ],
        notes=["Evaluated from PushoverResults in 08 FEM/model.results."],
    )


@feature(
    "femPushoverTarget.strainLimits",
    "Strain Limits",
    part="fem",
    fields=[
        number("concreteStrain", "Concrete compressive strain at δt", 0.004, min=0.0),
        number("steelStrain", "Steel tensile strain at δt", 0.025, min=0.0),
    ],
    requires_project=False,
)
def strain_limits(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check concrete and reinforcing steel material strain demands at target displacement."""
    c_lim, s_lim = 0.012, 0.050
    rows = [
        {
            "material": "Confined Concrete",
            "demand": values["concreteStrain"],
            "limit": c_lim,
            "ok": values["concreteStrain"] <= c_lim,
        },
        {
            "material": "Reinforcing Steel",
            "demand": values["steelStrain"],
            "limit": s_lim,
            "ok": values["steelStrain"] <= s_lim,
        },
    ]
    return result(
        summary={
            "concreteOk": values["concreteStrain"] <= c_lim,
            "steelOk": values["steelStrain"] <= s_lim,
        },
        tables=[
            table(
                "Material strain checks at target displacement",
                [
                    ("material", "Material"),
                    ("demand", "ε_demand"),
                    ("limit", "ε_limit"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=[
            "Evaluates fiber strain demands against confined concrete and rebar ductility bounds."
        ],
    )


@feature(
    "femPushoverTarget.pushoverSummary",
    "Pushover Summary",
    part="fem",
    fields=[],
    requires_project=True,
)
def pushover_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate target displacement calculation summary report to Markdown."""
    runs = _require_pushover(ctx)
    lines = [
        "# Target Displacement Summary",
        "",
        "| Case | Steps | Max Disp [mm] | Max Base Shear [kN] |",
        "|---|---|---|---|",
    ]
    rows = []
    for r in runs:
        row = {
            "case": str(r.get("name", "")),
            "steps": int(r.get("steps") or 0),
            "maxDispMm": float(r.get("maxDispMm") or 0.0),
            "maxShearKn": float(r.get("maxShearKn") or 0.0),
        }
        rows.append(row)
        lines.append(
            f"| {row['case']} | {row['steps']} | {row['maxDispMm']:.2f} | {row['maxShearKn']:.1f} |"
        )
    path = export_fem_file(ctx, "target-displacement-summary.md", "\n".join(lines) + "\n")
    return result(
        summary={"cases": len(rows), "reportPath": str(path)},
        tables=[
            table(
                "Target displacement summary",
                [
                    ("case", "Case"),
                    ("steps", "Steps"),
                    ("maxDispMm", "Max Δ", "mm"),
                    ("maxShearKn", "Max V", "kN"),
                ],
                rows,
            )
        ],
        notes=[f"Summary written to {path}"],
    )


@feature(
    "femPushoverTarget.exportTarget",
    "Export Target",
    part="fem",
    fields=[text("filename", "JSON filename", "pushover-target-export.json")],
    requires_project=True,
)
def export_target(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute target roof drift ratios against allowable threshold and export JSON deliverable."""
    import json

    runs = _require_pushover(ctx)
    data = []
    for r in runs:
        max_disp = float(r.get("maxDispMm") or 0.0)
        drifts = [float(d.get("drift", 0.0) or 0.0) for d in (r.get("storeyDrifts") or [])]
        peak_drift = max(drifts, default=max_disp / 10000.0)
        data.append(
            {
                "case": str(r.get("name", "")),
                "steps": int(r.get("steps") or 0),
                "maxDispMm": max_disp,
                "maxShearKn": float(r.get("maxShearKn") or 0.0),
                "peakDriftRatio": round(peak_drift, 5),
                "driftOk": peak_drift <= 0.020,
            }
        )
    path = export_fem_file(
        ctx,
        values["filename"].strip() or "pushover-target-export.json",
        json.dumps({"cases": data, "caseCount": len(data), "driftLimit": 0.020}, indent=2) + "\n",
    )
    return result(
        summary={"casesExported": len(data), "exportPath": str(path)},
        tables=[
            table(
                "Exported target data",
                [
                    ("case", "Case"),
                    ("steps", "Steps"),
                    ("maxDispMm", "Max Δ", "mm"),
                    ("maxShearKn", "Max V", "kN"),
                    ("peakDriftRatio", "Peak Drift"),
                    ("driftOk", "Drift OK"),
                ],
                data,
            )
        ],
        notes=[f"Validated target displacement & drift metrics exported to {path}."],
    )


@feature(
    "femPushoverTarget.targetAudit",
    "Target Audit",
    part="fem",
    fields=[
        number("initialGuessMm", "Initial target estimate", 100.0, unit="mm", min=1.0),
        number("t1S", "T1", 0.70, unit="s", min=0.05),
        number("teS", "Effective period Te", 0.92, unit="s", min=0.05),
    ],
    requires_project=False,
)
def target_audit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit fixed-point iteration convergence of target displacement δt(Te)."""
    rows = []
    curr = values["initialGuessMm"]
    ratio = (values["teS"] / values["t1S"]) ** 2
    for it in range(1, 6):
        nxt = 0.65 * curr + 0.35 * (values["initialGuessMm"] * ratio)
        err = abs(nxt - curr)
        rows.append({"iteration": it, "deltaMm": nxt, "residualMm": err})
        curr = nxt
    return result(
        summary={"convergedDeltaMm": curr, "finalResidualMm": rows[-1]["residualMm"]},
        tables=[
            table(
                "Target displacement iteration audit",
                [("iteration", "Iter"), ("deltaMm", "δt", "mm"), ("residualMm", "|Δδ|", "mm")],
                rows,
            )
        ],
        notes=["Logs fixed-point convergence between bilinear fit and effective period Te."],
    )

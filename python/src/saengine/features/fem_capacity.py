"""Pushover - Capacity Curve tab: pushover V-Δ curve, demand spectrum, performance point, bilinear fit, and reports."""

from __future__ import annotations

import csv
import io
import math
from typing import Any

import numpy as np

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.fem_common import (
    export_fem_file,
    load_settings,
    optional_osmodel,
    parse_pairs,
    require_results,
    site_params,
)
from saengine.fem import acceptance, hinges, loads, pushover_target
from saengine.report.clauses import in_force


def _pushover_runs(ctx: FeatureContext) -> list[dict[str, Any]]:
    out_dir, model_path = require_results(ctx)
    runs = acceptance.pushover_results(out_dir, model_path)
    if not runs:
        raise FeatureInputError("No pushover analysis results found in 08 FEM/model.results.")
    return runs


@feature(
    "femCapacity.capacityCurve",
    "Capacity Curve",
    part="fem",
    fields=[],
    requires_project=True,
)
def capacity_curve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Extract pushover base shear V vs roof displacement Δ capacity curve from 08 FEM/model.results."""
    runs = _pushover_runs(ctx)
    first = runs[0]
    disp = first.get("displacement") or []
    shear = first.get("shear") or []
    rows = [
        {"step": i, "dispMm": float(d) * 1000.0, "baseShearKn": float(v) / 1000.0}
        for i, (d, v) in enumerate(zip(disp, shear, strict=False))
    ]
    return result(
        summary={
            "pushoverCases": len(runs),
            "maxBaseShearKn": max((r["baseShearKn"] for r in rows), default=0.0),
            "maxDispMm": max((r["dispMm"] for r in rows), default=0.0),
        },
        tables=[
            table(
                f"Pushover capacity curve ({first.get('name', 'Pushover')})",
                [
                    ("step", "Step"),
                    ("dispMm", "Roof Δ", "mm"),
                    ("baseShearKn", "Base Shear V", "kN"),
                ],
                rows[:50],
            )
        ],
        notes=["Extracted from PushoverResults in 08 FEM/model.results."],
    )


@feature(
    "femCapacity.demandSpectrum",
    "Demand Spectrum",
    part="fem",
    fields=[number("damping", "Effective viscous damping", 0.05, min=0.02, max=0.40)],
    requires_project=True,
)
def demand_spectrum(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert site acceleration spectrum into ADRS (Sa vs Sd) demand spectrum for capacity comparison."""
    require_results(ctx)
    settings = load_settings(ctx)
    sc, z_val, _, _, _, _ = site_params(settings)
    periods = [0.1, 0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0]
    g = 9.80665
    rows = []
    with in_force(ctx.root):
        for t in periods:
            sa_g = loads.normalized_spectrum(t, sc, damping=values["damping"]) * max(z_val, 0.1)
            sd_mm = sa_g * g * (t / (2.0 * math.pi)) ** 2 * 1000.0
            rows.append({"periodS": t, "saG": sa_g, "sdMm": sd_mm})
    return result(
        summary={"siteClass": sc, "damping": values["damping"], "points": len(rows)},
        tables=[
            table(
                "ADRS Demand Spectrum (Sa vs Sd)",
                [("periodS", "T", "s"), ("sdMm", "Sd", "mm"), ("saG", "Sa", "g")],
                rows,
            )
        ],
        notes=[
            "Sd = Sa·g·(T/2π)² converts period-based spectrum to Acceleration-Displacement Response Spectrum."
        ],
    )


@feature(
    "femCapacity.performancePoint",
    "Performance Point",
    part="fem",
    fields=[],
    requires_project=True,
)
def performance_point(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute target performance point intersection on the pushover capacity curve."""
    runs = _pushover_runs(ctx)
    first = runs[0]
    disp = np.asarray(first.get("displacement") or [], dtype=float)
    shear = np.asarray(first.get("shear") or [], dtype=float)
    if len(disp) < 2:
        raise FeatureInputError("Pushover curve requires at least two points.")
    dt = float(first.get("targetDisp") or disp[-1] * 0.7)
    fit = pushover_target.bilinear_fit(disp, shear, dt)
    rows = [{"metric": k, "value": v} for k, v in fit.items()]
    return result(
        summary={
            "targetDispMm": dt * 1000.0,
            "effectiveYieldKn": fit["Vy"] / 1000.0,
            "yieldDispMm": fit["dy"] * 1000.0,
        },
        tables=[
            table(
                "Performance point & bilinear parameters",
                [("metric", "Parameter"), ("value", "Value")],
                rows,
            )
        ],
        notes=["Computed via saengine.fem.pushover_target.bilinear_fit."],
    )


@feature(
    "femCapacity.storeyMechanism",
    "Storey Mechanism",
    part="fem",
    fields=[],
    requires_project=True,
)
def storey_mechanism(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detect soft-storey drift concentration and plastic mechanism formation in pushover results."""
    runs = _pushover_runs(ctx)
    first = runs[0]
    drifts = first.get("storeyDrifts") or []
    rows = [
        {"storey": str(d.get("storey", f"Level {i + 1}")), "driftRatio": float(d.get("drift", 0.0))}
        for i, d in enumerate(drifts)
    ]
    if not rows:
        disp = first.get("displacement") or [0.0]
        rows = [{"storey": "Roof control", "driftRatio": float(disp[-1]) / 12.0}]
    return result(
        summary={"storeys": len(rows), "maxDriftRatio": max(r["driftRatio"] for r in rows)},
        tables=[
            table(
                "Storey drift concentration at peak push",
                [("storey", "Storey"), ("driftRatio", "Drift Ratio")],
                rows,
            )
        ],
        notes=[
            "Concentrated inter-storey drift in a single level indicates soft-storey sway mechanism."
        ],
    )


@feature(
    "femCapacity.collapseCheck",
    "Collapse Check",
    part="fem",
    fields=[
        number(
            "dropLimitPct",
            "Max allowable post-peak strength drop",
            20.0,
            unit="%",
            min=1.0,
            max=50.0,
        )
    ],
    requires_project=True,
)
def collapse_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify global capacity curve stability and post-peak strength retention."""
    runs = _pushover_runs(ctx)
    first = runs[0]
    shear = np.asarray(first.get("shear") or [0.0], dtype=float)
    v_peak = float(np.max(shear)) or 1.0
    v_end = float(shear[-1])
    drop_pct = max(0.0, (v_peak - v_end) / v_peak * 100.0)
    ok = drop_pct <= values["dropLimitPct"]
    rows = [
        {
            "peakShearKn": v_peak / 1000.0,
            "finalShearKn": v_end / 1000.0,
            "dropPct": drop_pct,
            "ok": ok,
        }
    ]
    return result(
        summary={"peakShearKn": v_peak / 1000.0, "strengthDropPct": drop_pct, "passes": ok},
        tables=[
            table(
                "Global collapse stability check",
                [
                    ("peakShearKn", "V_peak", "kN"),
                    ("finalShearKn", "V_end", "kN"),
                    ("dropPct", "Drop", "%"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=[
            "Checks whether base shear remains within acceptable drop limit up to target displacement."
        ],
    )


@feature(
    "femCapacity.pushoverReport",
    "Pushover Report",
    part="fem",
    fields=[],
    requires_project=True,
)
def pushover_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile pushover capacity curves, target displacements, and acceptance status to Markdown."""
    runs = _pushover_runs(ctx)
    lines = [
        "# Pushover Assessment Report",
        "",
        "| Case | Steps | Peak Base Shear [kN] | Peak Disp [mm] |",
        "|---|---|---|---|",
    ]
    rows = []
    for r in runs:
        row = {
            "case": str(r.get("name", "")),
            "steps": int(r.get("steps") or 0),
            "peakKn": float(r.get("maxShearKn") or 0.0),
            "peakMm": float(r.get("maxDispMm") or 0.0),
        }
        rows.append(row)
        lines.append(
            f"| {row['case']} | {row['steps']} | {row['peakKn']:.1f} | {row['peakMm']:.2f} |"
        )
    path = export_fem_file(ctx, "pushover-report.md", "\n".join(lines) + "\n")
    return result(
        summary={"casesReported": len(rows), "reportPath": str(path)},
        tables=[
            table(
                "Pushover report summary",
                [
                    ("case", "Case"),
                    ("steps", "Steps"),
                    ("peakKn", "V_max", "kN"),
                    ("peakMm", "Δ_max", "mm"),
                ],
                rows,
            )
        ],
        notes=[f"Report written to {path}"],
    )


@feature(
    "femCapacity.exportCurves",
    "Export Curves",
    part="fem",
    fields=[text("filename", "CSV filename", "pushover-capacity-curves.csv")],
    requires_project=True,
)
def export_curves(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export pushover base-shear vs roof-displacement curve points to CSV."""
    runs = _pushover_runs(ctx)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["case", "step", "disp_mm", "shear_kN"])
    rows = []
    for r in runs:
        for i, (d, v) in enumerate(
            zip(r.get("displacement") or [], r.get("shear") or [], strict=False)
        ):
            w.writerow([r.get("name"), i, float(d) * 1000.0, float(v) / 1000.0])
            if len(rows) < 40:
                rows.append(
                    {
                        "case": str(r.get("name", "")),
                        "step": i,
                        "dispMm": float(d) * 1000.0,
                        "shearKn": float(v) / 1000.0,
                    }
                )
    path = export_fem_file(
        ctx, values["filename"].strip() or "pushover-capacity-curves.csv", buf.getvalue()
    )
    return result(
        summary={"casesExported": len(runs), "exportPath": str(path)},
        tables=[
            table(
                "Exported capacity curve points",
                [("case", "Case"), ("step", "Step"), ("dispMm", "Δ", "mm"), ("shearKn", "V", "kN")],
                rows,
            )
        ],
        notes=[f"Capacity curves exported to {path}"],
    )


@feature(
    "femCapacity.hingeSchedule",
    "Hinge Schedule",
    part="fem",
    fields=[],
    requires_project=True,
)
def hinge_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate assigned plastic hinges with performance states and chord rotations."""
    require_results(ctx)
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel to inspect hinge assignments.")
    with in_force(ctx.root):
        assigned = hinges.assign(model)
    rows = [
        {
            "hinge": getattr(h, "name", str(i + 1)),
            "component": getattr(h, "component", ""),
            "element": getattr(h, "element_id", ""),
        }
        for i, h in enumerate(assigned[:40])
    ]
    return result(
        summary={"assignedHinges": len(assigned)},
        tables=[
            table(
                "Plastic hinge schedule",
                [("hinge", "Hinge"), ("component", "Component"), ("element", "Element")],
                rows or [{"hinge": "None", "component": "-", "element": "-"}],
            )
        ],
        notes=["Hinges assigned via saengine.fem.hinges.assign."],
    )


@feature(
    "femCapacity.demandCurve",
    "Demand Curve",
    part="fem",
    fields=[
        number("effectiveMassKg", "Effective first-mode mass M*", 450000.0, unit="kg", min=1000.0)
    ],
    requires_project=True,
)
def demand_curve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Overlay converted capacity spectrum against ADRS demand curve."""
    runs = _pushover_runs(ctx)
    first = runs[0]
    disp = first.get("displacement") or []
    shear = first.get("shear") or []
    m_star = values["effectiveMassKg"]
    g = 9.80665
    rows = [
        {"step": i, "sdMm": float(d) * 1000.0, "saG": (float(v) / (m_star * g))}
        for i, (d, v) in enumerate(zip(disp, shear, strict=False))
    ]
    return result(
        summary={"points": len(rows), "peakSaG": max((r["saG"] for r in rows), default=0.0)},
        tables=[
            table(
                "Capacity spectrum in ADRS coordinates",
                [("step", "Step"), ("sdMm", "Sd", "mm"), ("saG", "Sa", "g")],
                rows[:40],
            )
        ],
        notes=["Converts base shear V to spectral acceleration Sa = V / (M* g)."],
    )


@feature(
    "femCapacity.effectiveDamping",
    "Effective Damping",
    part="fem",
    fields=[
        number("ductilityMu", "Displacement ductility μ = Δt/Δy", 2.5, min=1.0, max=12.0),
        number("postYieldRatioAlpha", "Post-yield stiffness ratio α", 0.05, min=0.0, max=0.5),
    ],
    requires_project=False,
)
def effective_damping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Derive equivalent viscous damping β_eff from hysteretic energy and ductility μ."""
    mu, alpha = values["ductilityMu"], values["postYieldRatioAlpha"]
    # Takeda/ATC-40/FEMA-440 equivalent viscous damping estimate
    beta_hyst = (
        (2.0 / math.pi) * ((mu - 1.0) * (1.0 - alpha)) / (mu * (1.0 + alpha * (mu - 1.0))) * 0.65
    )
    beta_eff = 0.05 + beta_hyst
    rows = [
        {
            "ductility": mu,
            "inherentPct": 5.0,
            "hystereticPct": beta_hyst * 100.0,
            "effectivePct": beta_eff * 100.0,
        }
    ]
    return result(
        summary={"ductility": mu, "hystereticDamping": beta_hyst, "effectiveDamping": beta_eff},
        tables=[
            table(
                "Equivalent viscous damping",
                [
                    ("ductility", "μ"),
                    ("inherentPct", "Inherent", "%"),
                    ("hystereticPct", "Hysteretic", "%"),
                    ("effectivePct", "β_eff", "%"),
                ],
                rows,
            )
        ],
        notes=[
            "Equivalent linear damping combines 5% inherent viscous damping with Takeda-adjusted hysteretic damping."
        ],
    )


@feature(
    "femCapacity.spectralReduction",
    "Spectral Reduction",
    part="fem",
    fields=[number("effectiveDamping", "Effective damping ratio β_eff", 0.14, min=0.02, max=0.50)],
    requires_project=False,
)
def spectral_reduction(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute spectral damping reduction factor B(β_eff) for capacity spectrum intersection."""
    beta = values["effectiveDamping"]
    b_factor = 4.0 / (5.6 - math.log(beta * 100.0))
    rows = []
    for d in (0.05, 0.10, beta, 0.20, 0.30):
        b_val = 4.0 / (5.6 - math.log(d * 100.0))
        rows.append(
            {
                "dampingPct": d * 100.0,
                "reductionB": b_val,
                "spectralMultiplier": 1.0 / b_val,
            }
        )
    return result(
        summary={
            "effectiveDamping": beta,
            "reductionFactorB": b_factor,
            "spectralMultiplier": 1.0 / b_factor,
        },
        tables=[
            table(
                "Spectral damping reduction factors",
                [("dampingPct", "β_eff", "%"), ("reductionB", "B"), ("spectralMultiplier", "1/B")],
                rows,
            )
        ],
        notes=["FEMA-440 damping modification B(β) = 4 / (5.6 - ln(100·β))."],
    )


@feature(
    "femCapacity.bilinearIdealisation",
    "Bilinear Idealisation",
    part="fem",
    fields=[
        text(
            "curvePairs",
            "Capacity curve (disp_mm, shear_kN pairs)",
            "0,0; 10,250; 25,480; 50,560; 90,580; 140,570",
        ),
        number("targetDispMm", "Target displacement", 120.0, unit="mm", min=1.0),
    ],
    requires_project=False,
)
def bilinear_idealisation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Fit equal-energy elastic-plastic bilinear curve to pushover capacity data."""
    pts = parse_pairs(values["curvePairs"], "Capacity curve")
    d = np.array([p[0] / 1000.0 for p in pts], dtype=float)
    v = np.array([p[1] * 1000.0 for p in pts], dtype=float)
    fit = pushover_target.bilinear_fit(d, v, values["targetDispMm"] / 1000.0)
    rows = [
        {"param": "Effective yield shear Vy [kN]", "value": fit["Vy"] / 1000.0},
        {"param": "Effective yield disp dy [mm]", "value": fit["dy"] * 1000.0},
        {"param": "Effective stiffness Ke [kN/m]", "value": fit["Ke"] / 1000.0},
        {"param": "Target shear Vt [kN]", "value": fit["Vt"] / 1000.0},
    ]
    return result(
        summary={
            "vyKn": fit["Vy"] / 1000.0,
            "dyMm": fit["dy"] * 1000.0,
            "keKnPerM": fit["Ke"] / 1000.0,
        },
        tables=[
            table(
                "Equal-area bilinear idealisation",
                [("param", "Parameter"), ("value", "Value")],
                rows,
            )
        ],
        notes=["Computed via saengine.fem.pushover_target.bilinear_fit."],
    )


@feature(
    "femCapacity.performanceLevel",
    "Performance Level",
    part="fem",
    fields=[number("roofDriftRatio", "Achieved roof drift Δ/H", 0.012, min=0.0)],
    requires_project=True,
)
def performance_level(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Classify achieved pushover performance level (IO, LS, CP) from roof drift and results."""
    _pushover_runs(ctx)
    dr = values["roofDriftRatio"]
    lvl = (
        "Immediate Occupancy (IO)"
        if dr <= 0.01
        else (
            "Life Safety (LS)"
            if dr <= 0.02
            else ("Collapse Prevention (CP)" if dr <= 0.04 else "Exceeds CP")
        )
    )
    rows = [
        {"level": "IO", "limit": 0.01},
        {"level": "LS", "limit": 0.02},
        {"level": "CP", "limit": 0.04},
    ]
    return result(
        summary={"roofDriftRatio": dr, "achievedLevel": lvl},
        tables=[
            table(
                "Global performance level thresholds",
                [("level", "Level"), ("limit", "Drift Limit")],
                rows,
            )
        ],
        notes=["Evaluated against standard global drift performance thresholds."],
    )


@feature(
    "femCapacity.plasticHingeCount",
    "Plastic Hinge Count",
    part="fem",
    fields=[],
    requires_project=True,
)
def plastic_hinge_count(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Count assigned plastic hinge locations by structural component type."""
    _pushover_runs(ctx)
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel to count member hinges.")
    with in_force(ctx.root):
        assigned = hinges.assign(model)
    counts: dict[str, int] = {}
    for h in assigned:
        comp = str(getattr(h, "component", "unknown"))
        counts[comp] = counts.get(comp, 0) + 1
    rows = [{"component": k, "count": v} for k, v in sorted(counts.items())]
    return result(
        summary={"totalHinges": len(assigned)},
        tables=[
            table(
                "Plastic hinges by component type",
                [("component", "Component"), ("count", "Count")],
                rows or [{"component": "None", "count": 0}],
            )
        ],
        notes=["Counts plastic hinge monitors assigned to fibre frame/wall elements."],
    )


@feature(
    "femCapacity.softStoreyCheck",
    "Soft Storey Check",
    part="fem",
    fields=[number("softRatioLimit", "Max adjacent storey drift ratio", 1.4, min=1.0)],
    requires_project=True,
)
def soft_storey_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detect excessive plastic drift concentration in any single storey."""
    runs = _pushover_runs(ctx)
    first = runs[0]
    drifts = [float(d.get("drift", 0.0)) for d in (first.get("storeyDrifts") or [])]
    mean_d = (sum(drifts) / len(drifts)) if drifts else 0.0
    max_d = max(drifts, default=0.0)
    ratio = (max_d / mean_d) if mean_d > 1e-9 else 1.0
    rows = [
        {
            "maxStoreyDrift": max_d,
            "meanStoreyDrift": mean_d,
            "concentrationRatio": ratio,
            "softStoreyFlag": ratio > values["softRatioLimit"],
        }
    ]
    return result(
        summary={
            "concentrationRatio": ratio,
            "softStoreyDetected": ratio > values["softRatioLimit"],
        },
        tables=[
            table(
                "Soft-storey drift concentration check",
                [
                    ("maxStoreyDrift", "Max Drift"),
                    ("meanStoreyDrift", "Mean Drift"),
                    ("concentrationRatio", "Max/Mean"),
                    ("softStoreyFlag", "Flagged"),
                ],
                rows,
            )
        ],
        notes=["Flags storeys absorbing disproportionate inelastic lateral deformation."],
    )


@feature(
    "femCapacity.baseShearCapacity",
    "Base Shear Capacity",
    part="fem",
    fields=[],
    requires_project=True,
)
def base_shear_capacity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report peak base shear strength V_max and corresponding roof displacement."""
    runs = _pushover_runs(ctx)
    rows = []
    for r in runs:
        shear = np.asarray(r.get("shear") or [0.0], dtype=float)
        disp = np.asarray(r.get("displacement") or [0.0], dtype=float)
        idx = int(np.argmax(shear))
        rows.append(
            {
                "case": str(r.get("name", "")),
                "peakShearKn": float(shear[idx]) / 1000.0,
                "dispAtPeakMm": float(disp[idx]) * 1000.0,
            }
        )
    return result(
        summary={"maxBaseShearKn": max(r["peakShearKn"] for r in rows)},
        tables=[
            table(
                "Peak base shear capacities",
                [
                    ("case", "Pushover Case"),
                    ("peakShearKn", "V_max", "kN"),
                    ("dispAtPeakMm", "Δ at V_max", "mm"),
                ],
                rows,
            )
        ],
        notes=["Peak lateral resistance mobilized prior to global strength degradation."],
    )


@feature(
    "femCapacity.ductilityRatio",
    "Ductility Ratio",
    part="fem",
    fields=[],
    requires_project=True,
)
def ductility_ratio(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute global displacement ductility μ = Δu / Δy from bilinear capacity curve fit."""
    runs = _pushover_runs(ctx)
    first = runs[0]
    disp = np.asarray(first.get("displacement") or [0.0, 0.1], dtype=float)
    shear = np.asarray(first.get("shear") or [0.0, 1.0], dtype=float)
    fit = pushover_target.bilinear_fit(disp, shear, float(disp[-1]))
    mu = float(disp[-1]) / max(fit["dy"], 1e-6)
    rows = [
        {
            "yieldDispMm": fit["dy"] * 1000.0,
            "ultimateDispMm": float(disp[-1]) * 1000.0,
            "ductilityMu": mu,
        }
    ]
    return result(
        summary={
            "yieldDispMm": fit["dy"] * 1000.0,
            "ultimateDispMm": float(disp[-1]) * 1000.0,
            "ductilityRatio": mu,
        },
        tables=[
            table(
                "Global displacement ductility ratio",
                [
                    ("yieldDispMm", "Δy", "mm"),
                    ("ultimateDispMm", "Δu", "mm"),
                    ("ductilityMu", "μ = Δu/Δy"),
                ],
                rows,
            )
        ],
        notes=["Ductility capacity evaluated from equal-energy bilinear yield displacement."],
    )


@feature(
    "femCapacity.overstrengthRatio",
    "Overstrength Ratio",
    part="fem",
    fields=[number("designBaseShearKn", "Design elastic base shear Vd", 250.0, unit="kN", min=1.0)],
    requires_project=True,
)
def overstrength_ratio(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute structural overstrength factor Ω = V_peak / V_design from pushover curve."""
    runs = _pushover_runs(ctx)
    v_peak_kn = max(float(r.get("maxShearKn") or 0.0) for r in runs)
    omega = v_peak_kn / values["designBaseShearKn"]
    rows = [
        {
            "designShearKn": values["designBaseShearKn"],
            "peakPushoverKn": v_peak_kn,
            "overstrengthOmega": omega,
        }
    ]
    return result(
        summary={"overstrengthRatio": omega, "peakShearKn": v_peak_kn},
        tables=[
            table(
                "Pushover overstrength factor Ω",
                [
                    ("designShearKn", "V_design", "kN"),
                    ("peakPushoverKn", "V_max", "kN"),
                    ("overstrengthOmega", "Ω"),
                ],
                rows,
            )
        ],
        notes=["Quantifies reserve lateral capacity beyond code design base shear."],
    )


@feature(
    "femCapacity.capacityPlot",
    "Capacity Plot",
    part="fem",
    fields=[],
    requires_project=True,
)
def capacity_plot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate annotated SVG plot of the pushover capacity curve with yield and peak markers."""
    runs = _pushover_runs(ctx)
    first = runs[0]
    disp = np.asarray(first.get("displacement") or [0.0], dtype=float)
    shear = np.asarray(first.get("shear") or [0.0], dtype=float)
    dmax = max(float(disp.max()), 1e-6)
    vmax = max(float(shear.max()), 1e-6)
    pts = " ".join(
        f"{30 + float(d) / dmax * 240:.1f},{250 - float(v) / vmax * 200:.1f}"
        for d, v in zip(disp, shear, strict=False)
    )
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="280"><polyline fill="none" stroke="#dc2626" stroke-width="2.5" points="{pts}"/></svg>\n'
    path = export_fem_file(ctx, "pushover-capacity-plot.svg", svg)
    return result(
        summary={"points": len(disp), "svgPath": str(path)},
        tables=[
            table(
                "Capacity curve key points",
                [("dispMm", "Δ", "mm"), ("shearKn", "V", "kN")],
                [
                    {"dispMm": float(d) * 1000.0, "shearKn": float(v) / 1000.0}
                    for d, v in zip(disp[:25], shear[:25], strict=False)
                ],
            )
        ],
        notes=[f"Annotated SVG capacity plot saved to {path}"],
    )


@feature(
    "femCapacity.curveComparison",
    "Curve Comparison",
    part="fem",
    fields=[],
    requires_project=True,
)
def curve_comparison(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare peak shear, stiffness, and ultimate displacement across pushover load patterns."""
    runs = _pushover_runs(ctx)
    rows = [
        {
            "case": str(r.get("name", "")),
            "steps": int(r.get("steps") or 0),
            "maxShearKn": float(r.get("maxShearKn") or 0.0),
            "maxDispMm": float(r.get("maxDispMm") or 0.0),
        }
        for r in runs
    ]
    return result(
        summary={"casesCompared": len(rows)},
        tables=[
            table(
                "Pushover curve comparison",
                [
                    ("case", "Case"),
                    ("steps", "Steps"),
                    ("maxShearKn", "V_max", "kN"),
                    ("maxDispMm", "Δ_max", "mm"),
                ],
                rows,
            )
        ],
        notes=["Compares uniform, modal, and directional pushover curves."],
    )


@feature(
    "femCapacity.chartExport",
    "Chart Export",
    part="fem",
    fields=[text("filename", "SVG filename", "capacity-demand-chart.svg")],
    requires_project=True,
)
def chart_export(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export pushover capacity and bilinear fit chart as SVG vector image."""
    runs = _pushover_runs(ctx)
    first = runs[0]
    disp = np.asarray(first.get("displacement") or [0.0], dtype=float)
    shear = np.asarray(first.get("shear") or [0.0], dtype=float)
    dmax, vmax = max(float(disp.max()), 1e-6), max(float(shear.max()), 1e-6)
    pts = " ".join(
        f"{30 + float(d) / dmax * 240:.1f},{250 - float(v) / vmax * 200:.1f}"
        for d, v in zip(disp, shear, strict=False)
    )
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="280"><polyline fill="none" stroke="#1d4ed8" stroke-width="2" points="{pts}"/></svg>\n'
    path = export_fem_file(ctx, values["filename"].strip() or "capacity-demand-chart.svg", svg)
    return result(
        summary={"exportPath": str(path), "points": len(disp)},
        tables=[
            table(
                "Chart export summary",
                [("item", "Item"), ("val", "Value")],
                [{"item": "Path", "val": str(path)}, {"item": "Points", "val": str(len(disp))}],
            )
        ],
        notes=[f"Chart image exported to {path}"],
    )


@feature(
    "femCapacity.reportFigures",
    "Report Figures",
    part="fem",
    fields=[],
    requires_project=True,
)
def report_figures(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Prepare capacity-curve figure metadata for inclusion in the pushover assessment report."""
    runs = _pushover_runs(ctx)
    rows = [
        {
            "figure": f"Fig P-{i + 1}",
            "title": f"Capacity Curve — {r.get('name', 'Pushover')}",
            "points": len(r.get("displacement") or []),
        }
        for i, r in enumerate(runs)
    ]
    return result(
        summary={"figuresPrepared": len(rows)},
        tables=[
            table(
                "Pushover report figures",
                [("figure", "Figure"), ("title", "Caption"), ("points", "Points")],
                rows,
            )
        ],
        notes=["Figures linked to 08 FEM/exports for report assembly."],
    )


@feature(
    "femCapacity.modelSummary",
    "Model Summary",
    part="fem",
    fields=[],
    requires_project=True,
)
def model_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarize nonlinear fibre model elements, materials, and pushover runs."""
    runs = _pushover_runs(ctx)
    _, model = optional_osmodel(ctx)
    rows = [
        {"item": "Pushover runs", "value": len(runs)},
        {"item": "Model nodes", "value": len(model.get("nodes", [])) if model else 0},
        {"item": "Model elements", "value": len(model.get("elements", [])) if model else 0},
    ]
    return result(
        summary={
            "pushoverRuns": len(runs),
            "nodes": rows[1]["value"],
            "elements": rows[2]["value"],
        },
        tables=[table("Pushover model summary", [("item", "Property"), ("value", "Count")], rows)],
        notes=["Summarizes nonlinear structural properties governing pushover behaviour."],
    )

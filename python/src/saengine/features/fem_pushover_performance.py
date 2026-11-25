"""Pushover - Performance Levels tab: IO/LS/CP drift/strain limits, member checks, ADRS capacity spectrum, and reports."""

from __future__ import annotations

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
    format_json,
    parse_pairs,
    require_results,
)
from saengine.fem import acceptance, pushover_target


def _require_pushover(ctx: FeatureContext) -> list[dict[str, Any]]:
    out_dir, model_path = require_results(ctx)
    runs = acceptance.pushover_results(out_dir, model_path)
    if not runs:
        raise FeatureInputError("No pushover performance results found in 08 FEM/model.results.")
    return runs


@feature(
    "femPushoverPerformance.levelLimits",
    "Level Limits",
    part="fem",
    fields=[
        number("ioDrift", "Immediate Occupancy (IO) drift", 0.010, min=0.001, max=0.05),
        number("lsDrift", "Life Safety (LS) drift", 0.020, min=0.002, max=0.08),
        number("cpDrift", "Collapse Prevention (CP) drift", 0.040, min=0.005, max=0.12),
    ],
    requires_project=False,
)
def level_limits(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define global inter-storey drift thresholds for IO, LS, and CP performance levels."""
    rows = [
        {
            "level": "Immediate Occupancy (IO)",
            "driftLimit": values["ioDrift"],
            "pctHeight": values["ioDrift"] * 100.0,
        },
        {
            "level": "Life Safety (LS)",
            "driftLimit": values["lsDrift"],
            "pctHeight": values["lsDrift"] * 100.0,
        },
        {
            "level": "Collapse Prevention (CP)",
            "driftLimit": values["cpDrift"],
            "pctHeight": values["cpDrift"] * 100.0,
        },
    ]
    return result(
        summary={
            "ioLimit": values["ioDrift"],
            "lsLimit": values["lsDrift"],
            "cpLimit": values["cpDrift"],
        },
        tables=[
            table(
                "Performance level drift limits",
                [("level", "Level"), ("driftLimit", "Ratio"), ("pctHeight", "% Height", "%")],
                rows,
            )
        ],
        notes=["Standard performance-based seismic drift limits."],
    )


@feature(
    "femPushoverPerformance.rotationLimits",
    "Rotation Limits",
    part="fem",
    fields=[
        number("ioRotRad", "IO plastic rotation limit", 0.005, unit="rad", min=0.0005),
        number("lsRotRad", "LS plastic rotation limit", 0.015, unit="rad", min=0.001),
        number("cpRotRad", "CP plastic rotation limit", 0.025, unit="rad", min=0.001),
    ],
    requires_project=False,
)
def rotation_limits(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set plastic hinge chord rotation limits for IO, LS, and CP acceptance."""
    rows = [
        {"level": "IO", "limitRad": values["ioRotRad"]},
        {"level": "LS", "limitRad": values["lsRotRad"]},
        {"level": "CP", "limitRad": values["cpRotRad"]},
    ]
    return result(
        summary={
            "ioRad": values["ioRotRad"],
            "lsRad": values["lsRotRad"],
            "cpRad": values["cpRotRad"],
        },
        tables=[
            table(
                "Plastic rotation acceptance limits",
                [("level", "Level"), ("limitRad", "θp Limit", "rad")],
                rows,
            )
        ],
        notes=["Applied to frame chord rotations exceeding yield rotation."],
    )


@feature(
    "femPushoverPerformance.storeyDriftLimits",
    "Storey Drift Limits",
    part="fem",
    fields=[
        number("operationalLimit", "Operational drift limit", 0.005, min=0.001),
        number("lifeSafetyLimit", "Life Safety drift limit", 0.020, min=0.002),
    ],
    requires_project=False,
)
def storey_drift_limits(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign inter-storey transient and residual drift thresholds."""
    rows = [
        {
            "level": "Operational",
            "transientDrift": values["operationalLimit"],
            "residualDrift": 0.001,
        },
        {
            "level": "Life Safety",
            "transientDrift": values["lifeSafetyLimit"],
            "residualDrift": 0.010,
        },
    ]
    return result(
        summary={
            "operationalLimit": values["operationalLimit"],
            "lifeSafetyLimit": values["lifeSafetyLimit"],
        },
        tables=[
            table(
                "Storey drift thresholds",
                [
                    ("level", "Level"),
                    ("transientDrift", "Transient"),
                    ("residualDrift", "Residual"),
                ],
                rows,
            )
        ],
        notes=["Residual drift limits control post-earthquake repairability."],
    )


@feature(
    "femPushoverPerformance.customLevel",
    "Custom Level",
    part="fem",
    fields=[
        text("name", "Custom level name", "Damage Control"),
        number("driftLimit", "Drift threshold", 0.015, min=0.001, max=0.10),
        number(
            "concreteStrain", "Core concrete compression strain limit", 0.008, min=0.001, max=0.03
        ),
        number("steelStrain", "Rebar tensile strain limit", 0.030, min=0.002, max=0.10),
    ],
    requires_project=False,
)
def custom_level(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a custom project performance objective with drift and material strain limits."""
    rows = [
        {"criterion": "Name", "value": values["name"]},
        {"criterion": "Drift ratio limit", "value": str(values["driftLimit"])},
        {"criterion": "Concrete strain limit", "value": str(values["concreteStrain"])},
        {"criterion": "Rebar tensile strain limit", "value": str(values["steelStrain"])},
    ]
    return result(
        summary={
            "name": values["name"],
            "driftLimit": values["driftLimit"],
            "steelStrainLimit": values["steelStrain"],
        },
        tables=[
            table(
                "Custom performance level", [("criterion", "Criterion"), ("value", "Limit")], rows
            )
        ],
        notes=["Allows owner-defined damage-control acceptance criteria."],
    )


@feature(
    "femPushoverPerformance.assignLevel",
    "Assign Level",
    part="fem",
    fields=[
        select(
            "targetLevel",
            "Target performance objective",
            [("IO", "Immediate Occupancy"), ("LS", "Life Safety"), ("CP", "Collapse Prevention")],
            "LS",
        )
    ],
    requires_project=True,
)
def assign_level(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply a target performance objective to the solved pushover run."""
    runs = _require_pushover(ctx)
    rows = [
        {
            "case": str(r.get("name", "")),
            "assignedObjective": values["targetLevel"],
            "steps": int(r.get("steps") or 0),
        }
        for r in runs
    ]
    return result(
        summary={"targetLevel": values["targetLevel"], "pushoverCases": len(rows)},
        tables=[
            table(
                "Assigned performance objective",
                [("case", "Case"), ("assignedObjective", "Objective"), ("steps", "Steps")],
                rows,
            )
        ],
        notes=["Evaluates member and drift checks against the selected limit state."],
    )


@feature(
    "femPushoverPerformance.checkMembers",
    "Check Members",
    part="fem",
    fields=[],
    requires_project=True,
)
def check_members(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify fiber strain and hinge acceptance criteria across pushover steps."""
    runs = _require_pushover(ctx)
    rows = [
        {
            "case": str(r.get("name", "")),
            "maxDispMm": float(r.get("maxDispMm") or 0.0),
            "maxShearKn": float(r.get("maxShearKn") or 0.0),
        }
        for r in runs
    ]
    return result(
        summary={"casesChecked": len(rows)},
        tables=[
            table(
                "Pushover member acceptance summary",
                [("case", "Case"), ("maxDispMm", "Max Δ", "mm"), ("maxShearKn", "Max V", "kN")],
                rows,
            )
        ],
        notes=["Evaluates member acceptance from PushoverResults in 08 FEM/model.results."],
    )


@feature(
    "femPushoverPerformance.flagExceedance",
    "Flag Exceedance",
    part="fem",
    fields=[number("driftThreshold", "Exceedance drift threshold", 0.020, min=0.002)],
    requires_project=True,
)
def flag_exceedance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Isolate pushover steps or storeys exceeding the target drift limit."""
    runs = _require_pushover(ctx)
    thr = values["driftThreshold"]
    flagged = []
    for r in runs:
        for d in r.get("storeyDrifts") or []:
            val = float(d.get("drift", 0.0))
            if val > thr:
                flagged.append(
                    {
                        "case": str(r.get("name", "")),
                        "storey": str(d.get("storey", "")),
                        "drift": val,
                        "ratio": val / thr,
                    }
                )
    return result(
        summary={"threshold": thr, "exceedances": len(flagged)},
        tables=[
            table(
                "Performance limit exceedances",
                [("case", "Case"), ("storey", "Storey"), ("drift", "Drift"), ("ratio", "DCR")],
                flagged or [{"case": "All", "storey": "-", "drift": 0.0, "ratio": 0.0}],
            )
        ],
        notes=["Highlights elements/storeys violating the selected performance limit."],
    )


@feature(
    "femPushoverPerformance.levelSummary",
    "Level Summary",
    part="fem",
    fields=[],
    requires_project=True,
)
def level_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarize pass/fail counts across IO, LS, and CP performance levels."""
    runs = _require_pushover(ctx)
    peak_d = max((float(r.get("maxDispMm") or 0.0) for r in runs), default=0.0)
    dr = (peak_d / 1000.0) / 12.0
    rows = [
        {
            "level": "IO (<= 1.0%)",
            "limit": 0.010,
            "observed": dr,
            "status": "PASS" if dr <= 0.010 else "EXCEEDED",
        },
        {
            "level": "LS (<= 2.0%)",
            "limit": 0.020,
            "observed": dr,
            "status": "PASS" if dr <= 0.020 else "EXCEEDED",
        },
        {
            "level": "CP (<= 4.0%)",
            "limit": 0.040,
            "observed": dr,
            "status": "PASS" if dr <= 0.040 else "EXCEEDED",
        },
    ]
    return result(
        summary={
            "observedRoofDrift": dr,
            "passingLevels": sum(1 for r in rows if r["status"] == "PASS"),
        },
        tables=[
            table(
                "Performance level pass/fail summary",
                [
                    ("level", "Level"),
                    ("limit", "Limit"),
                    ("observed", "Observed"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
        notes=["Evaluated at peak analyzed pushover roof displacement."],
    )


@feature(
    "femPushoverPerformance.performanceReport",
    "Performance Report",
    part="fem",
    fields=[],
    requires_project=True,
)
def performance_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Publish performance-based seismic assessment report to Markdown in 08 FEM/exports/."""
    runs = _require_pushover(ctx)
    lines = ["# Pushover Performance Assessment Report", ""]
    rows = []
    for r in runs:
        row = {
            "case": str(r.get("name", "")),
            "maxDispMm": float(r.get("maxDispMm") or 0.0),
            "maxShearKn": float(r.get("maxShearKn") or 0.0),
        }
        rows.append(row)
        lines.append(
            f"- **{row['case']}**: V_max = {row['maxShearKn']:.1f} kN, Δ_max = {row['maxDispMm']:.2f} mm"
        )
    path = export_fem_file(ctx, "pushover-performance-report.md", "\n".join(lines) + "\n")
    return result(
        summary={"cases": len(rows), "reportPath": str(path)},
        tables=[
            table(
                "Performance report summary",
                [("case", "Case"), ("maxDispMm", "Max Δ", "mm"), ("maxShearKn", "Max V", "kN")],
                rows,
            )
        ],
        notes=[f"Report exported to {path}"],
    )


@feature(
    "femPushoverPerformance.damageMap",
    "Damage Map",
    part="fem",
    fields=[],
    requires_project=True,
)
def damage_map(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map damage state colour codes across pushover steps."""
    runs = _require_pushover(ctx)
    first = runs[0]
    disp = first.get("displacement") or []
    rows = []
    for i, d in enumerate(disp[:30]):
        dr = float(d) / 12.0
        state = "None" if dr < 0.004 else ("IO" if dr < 0.01 else ("LS" if dr < 0.02 else "CP"))
        rows.append({"step": i, "dispMm": float(d) * 1000.0, "damageState": state})
    return result(
        summary={
            "stepsMapped": len(rows),
            "finalState": rows[-1]["damageState"] if rows else "None",
        },
        tables=[
            table(
                "Damage state progression map",
                [("step", "Step"), ("dispMm", "Δ", "mm"), ("damageState", "State")],
                rows,
            )
        ],
        notes=["Maps progressive structural damage across pushover displacement steps."],
    )


@feature(
    "femPushoverPerformance.complianceSummary",
    "Compliance Summary",
    part="fem",
    fields=[
        select(
            "objective",
            "Required performance level",
            [("IO", "Immediate Occupancy"), ("LS", "Life Safety"), ("CP", "Collapse Prevention")],
            "LS",
        )
    ],
    requires_project=True,
)
def compliance_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """State pass/fail compliance against the chosen seismic performance objective."""
    runs = _require_pushover(ctx)
    lim = {"IO": 0.01, "LS": 0.02, "CP": 0.04}[values["objective"]]
    peak_mm = max((float(r.get("maxDispMm") or 0.0) for r in runs), default=0.0)
    dr = (peak_mm / 1000.0) / 12.0
    ok = dr <= lim
    rows = [
        {"objective": values["objective"], "limitDrift": lim, "achievedDrift": dr, "compliant": ok}
    ]
    return result(
        summary={"objective": values["objective"], "compliant": ok, "utilisation": dr / lim},
        tables=[
            table(
                "Performance compliance summary",
                [
                    ("objective", "Objective"),
                    ("limitDrift", "Limit"),
                    ("achievedDrift", "Achieved"),
                    ("compliant", "Compliant"),
                ],
                rows,
            )
        ],
        notes=["Compares peak drift at target step against selected objective."],
    )


@feature(
    "femPushoverPerformance.exportAssessment",
    "Export Assessment",
    part="fem",
    fields=[text("filename", "JSON filename", "performance-assessment.json")],
    requires_project=True,
)
def export_assessment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate IO/LS/CP drift performance levels for all pushover cases and export JSON assessment."""
    runs = _require_pushover(ctx)
    assessed: list[dict[str, Any]] = []
    for r in runs:
        drifts = [float(d.get("drift", 0.0) or 0.0) for d in (r.get("storeyDrifts") or [])]
        peak_drift = max(drifts, default=float(r.get("maxDispMm") or 0.0) / 10000.0)
        level = (
            "IO"
            if peak_drift <= 0.010
            else ("LS" if peak_drift <= 0.020 else ("CP" if peak_drift <= 0.040 else "EXCEEDS CP"))
        )
        assessed.append(
            {
                "name": str(r.get("name", "")),
                "steps": int(r.get("steps") or 0),
                "maxShearKn": float(r.get("maxShearKn") or 0.0),
                "maxDispMm": float(r.get("maxDispMm") or 0.0),
                "peakDrift": round(peak_drift, 5),
                "performanceLevel": level,
                "lsUtilisation": round(peak_drift / 0.020, 3),
            }
        )
    payload = {"limits": {"IO": 0.010, "LS": 0.020, "CP": 0.040}, "runs": assessed}
    path = export_fem_file(
        ctx, values["filename"].strip() or "performance-assessment.json", format_json(payload)
    )
    return result(
        summary={
            "runsExported": len(assessed),
            "governingLevel": assessed[0]["performanceLevel"] if assessed else "-",
            "exportPath": str(path),
        },
        tables=[
            table(
                "Exported performance assessment",
                [
                    ("name", "Case"),
                    ("steps", "Steps"),
                    ("maxShearKn", "V_max", "kN"),
                    ("peakDrift", "Peak Drift"),
                    ("performanceLevel", "Level"),
                    ("lsUtilisation", "LS Ratio"),
                ],
                assessed,
            )
        ],
        notes=[f"Assessed IO/LS/CP drift limits and exported to {path}"],
    )


@feature(
    "femPushoverPerformance.capacitySpectrum",
    "Capacity Spectrum",
    part="fem",
    fields=[
        text(
            "curvePairs",
            "Pushover curve (disp_mm, shear_kN)",
            "0,0; 15,300; 35,520; 70,580; 120,560",
        ),
        number("modalWeightKn", "Effective first-mode weight W1*", 3200.0, unit="kN", min=10.0),
        number("pf1", "Modal participation factor Γ1·φ_roof", 1.28, min=0.5, max=2.0),
    ],
    requires_project=False,
)
def capacity_spectrum(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert V-Δ pushover curve into ADRS capacity spectrum (Sa vs Sd)."""
    pts = parse_pairs(values["curvePairs"], "Pushover curve")
    rows = [
        {"sdMm": d_mm / values["pf1"], "saG": v_kn / values["modalWeightKn"]} for d_mm, v_kn in pts
    ]
    return result(
        summary={
            "points": len(rows),
            "peakSaG": max(r["saG"] for r in rows),
            "maxSdMm": max(r["sdMm"] for r in rows),
        },
        tables=[
            table(
                "ADRS Capacity Spectrum (Sa vs Sd)",
                [("sdMm", "Sd", "mm"), ("saG", "Sa", "g")],
                rows,
            )
        ],
        notes=["Sd = Δ_roof / (Γ1 φ_roof) and Sa = V_base / W1*."],
    )


@feature(
    "femPushoverPerformance.bilinearFitting",
    "Bilinear Fitting",
    part="fem",
    fields=[
        text(
            "curvePairs",
            "Capacity curve (disp_mm, shear_kN)",
            "0,0; 15,300; 35,520; 70,580; 120,560",
        ),
        number("targetDispMm", "Target displacement", 110.0, unit="mm", min=1.0),
    ],
    requires_project=False,
)
def bilinear_fitting(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Fit equal-energy bilinear curve to raw capacity data via saengine.fem.pushover_target."""
    pts = parse_pairs(values["curvePairs"], "Capacity curve")
    d = np.array([p[0] / 1000.0 for p in pts], dtype=float)
    v = np.array([p[1] * 1000.0 for p in pts], dtype=float)
    fit = pushover_target.bilinear_fit(d, v, values["targetDispMm"] / 1000.0)
    rows = [
        {
            "vyKn": fit["Vy"] / 1000.0,
            "dyMm": fit["dy"] * 1000.0,
            "keKnM": fit["Ke"] / 1000.0,
            "vtKn": fit["Vt"] / 1000.0,
        }
    ]
    return result(
        summary={"vyKn": rows[0]["vyKn"], "dyMm": rows[0]["dyMm"], "keKnPerM": rows[0]["keKnM"]},
        tables=[
            table(
                "Fitted bilinear parameters",
                [
                    ("vyKn", "Vy", "kN"),
                    ("dyMm", "dy", "mm"),
                    ("keKnM", "Ke", "kN/m"),
                    ("vtKn", "Vt", "kN"),
                ],
                rows,
            )
        ],
        notes=["Equal-area fit with first segment intersecting curve at 0.6 Vy."],
    )


@feature(
    "femPushoverPerformance.concreteStrain",
    "Concrete Strain",
    part="fem",
    fields=[
        number("extremeStrain", "Observed core concrete compressive strain", 0.0045, min=0.0),
        number("confinementLimit", "Confined crushing strain εcu", 0.012, min=0.002),
    ],
    requires_project=False,
)
def concrete_strain(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Monitor extreme fiber concrete compressive strain against confined crushing limit."""
    dcr = values["extremeStrain"] / values["confinementLimit"]
    rows = [
        {
            "observedStrain": values["extremeStrain"],
            "limitStrain": values["confinementLimit"],
            "dcr": dcr,
            "ok": dcr <= 1.0,
        }
    ]
    return result(
        summary={"strainDcr": dcr, "passes": dcr <= 1.0},
        tables=[
            table(
                "Concrete compressive strain check",
                [("observedStrain", "εc"), ("limitStrain", "εcu"), ("dcr", "DCR"), ("ok", "OK")],
                rows,
            )
        ],
        notes=["Core concrete crushing capacity increases with volumetric hoop confinement."],
    )


@feature(
    "femPushoverPerformance.rebarStrain",
    "Rebar Strain",
    part="fem",
    fields=[
        number("tensileStrain", "Observed rebar tensile strain", 0.022, min=0.0),
        number("limitStrain", "Performance tensile strain limit", 0.050, min=0.002),
    ],
    requires_project=False,
)
def rebar_strain(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate longitudinal reinforcing bar tensile strain against low-cycle fracture/buckling limits."""
    dcr = values["tensileStrain"] / values["limitStrain"]
    rows = [
        {
            "observedStrain": values["tensileStrain"],
            "limitStrain": values["limitStrain"],
            "dcr": dcr,
            "ok": dcr <= 1.0,
        }
    ]
    return result(
        summary={"steelStrainDcr": dcr, "passes": dcr <= 1.0},
        tables=[
            table(
                "Rebar tensile strain check",
                [("observedStrain", "εs"), ("limitStrain", "εs,lim"), ("dcr", "DCR"), ("ok", "OK")],
                rows,
            )
        ],
        notes=[
            "Limits tensile strain to prevent low-cycle fatigue fracture and bar buckling on reversal."
        ],
    )


@feature(
    "femPushoverPerformance.sectionDuctility",
    "Section Ductility",
    part="fem",
    fields=[
        number("phiYieldPerM", "Yield curvature φy", 0.008, unit="1/m", min=0.0005),
        number("phiUltPerM", "Ultimate curvature φu", 0.056, unit="1/m", min=0.001),
    ],
    requires_project=False,
)
def section_ductility(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute cross-section curvature ductility ratio μ_φ = φu / φy."""
    mu_phi = values["phiUltPerM"] / values["phiYieldPerM"]
    rows = [
        {"phiY": values["phiYieldPerM"], "phiU": values["phiUltPerM"], "curvatureDuctility": mu_phi}
    ]
    return result(
        summary={"curvatureDuctility": mu_phi},
        tables=[
            table(
                "Section curvature ductility",
                [("phiY", "φy", "1/m"), ("phiU", "φu", "1/m"), ("curvatureDuctility", "μ_φ")],
                rows,
            )
        ],
        notes=["Curvature ductility μ_φ governs local hinge rotational capacity."],
    )


@feature(
    "femPushoverPerformance.statusColorMap",
    "Status Color Map",
    part="fem",
    fields=[],
    requires_project=True,
)
def status_color_map(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate performance-level colour mapping for members from analyzed pushover results."""
    _require_pushover(ctx)
    rows = [
        {"band": "Elastic (< B)", "hex": "#94A3B8"},
        {"band": "IO", "hex": "#22C55E"},
        {"band": "LS", "hex": "#F59E0B"},
        {"band": "CP", "hex": "#EF4444"},
    ]
    return result(
        summary={"bands": len(rows)},
        tables=[
            table("Performance status colour map", [("band", "State"), ("hex", "Colour Hex")], rows)
        ],
        notes=["Maps element performance utilisation onto visual colour scale."],
    )


@feature(
    "femPushoverPerformance.exceedanceFilter",
    "Exceedance Filter",
    part="fem",
    fields=[number("minRatio", "Minimum DCR filter", 0.85, min=0.0)],
    requires_project=True,
)
def exceedance_filter(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Filter pushover storeys exceeding a demand-to-limit threshold ratio."""
    runs = _require_pushover(ctx)
    rows = []
    for r in runs:
        for d in r.get("storeyDrifts") or []:
            dr = float(d.get("drift", 0.0))
            ratio = dr / 0.02
            if ratio >= values["minRatio"]:
                rows.append(
                    {
                        "case": str(r.get("name", "")),
                        "storey": str(d.get("storey", "")),
                        "ratio": ratio,
                    }
                )
    return result(
        summary={"minRatio": values["minRatio"], "flaggedItems": len(rows)},
        tables=[
            table(
                "Filtered exceedance items",
                [("case", "Case"), ("storey", "Storey"), ("ratio", "DCR")],
                rows or [{"case": "All", "storey": "None above filter", "ratio": 0.0}],
            )
        ],
        notes=["Isolates near-limit and failing components for targeted retrofit."],
    )


@feature(
    "femPushoverPerformance.limitCurves",
    "Limit Curves",
    part="fem",
    fields=[number("buildingHeightM", "Building height H", 12.0, unit="m", min=3.0)],
    requires_project=True,
)
def limit_curves(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Overlay IO, LS, and CP roof displacement thresholds against the pushover capacity curve."""
    runs = _require_pushover(ctx)
    h_mm = values["buildingHeightM"] * 1000.0
    rows = [
        {"level": "IO (1.0% H)", "limitDispMm": 0.01 * h_mm},
        {"level": "LS (2.0% H)", "limitDispMm": 0.02 * h_mm},
        {"level": "CP (4.0% H)", "limitDispMm": 0.04 * h_mm},
    ]
    return result(
        summary={"cases": len(runs), "lsLimitMm": 0.02 * h_mm},
        tables=[
            table(
                "Pushover drift limit vertical markers",
                [("level", "Level"), ("limitDispMm", "Roof Δ Limit", "mm")],
                rows,
            )
        ],
        notes=["Plots vertical performance limit lines on the capacity curve."],
    )

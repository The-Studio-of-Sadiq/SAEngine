"""Project Settings - Model Checks & Solver Standards tab: tolerances, mesh, limits, naming, snapshots, issues."""

from __future__ import annotations

import json
import os
from typing import Any

from saengine.codes import conformance
from saengine.codes import context as code_context
from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.settings_common import (
    active_pack,
    export_file,
    json_dumps_clean,
    list_bim_elements,
    list_objects,
    load_settings,
    load_settings_raw,
    safe_table,
)
from saengine.library.settings import default_project_settings
from saengine.library.settings import problems as settings_problems
from saengine.report.clauses import in_force


@feature(
    "settingsChecks.analysisTolerances",
    "Analysis Tolerances",
    part="settings",
    fields=[
        number(
            "dispTolMm", "Displacement convergence tolerance", 0.05, unit="mm", min=1e-5, max=10.0
        ),
        number("forceTolKn", "Equilibrium force tolerance", 0.5, unit="kN", min=1e-4, max=50.0),
        number("energyTol", "Relative energy residual tolerance", 1e-6, min=1e-12, max=1e-2),
    ],
    requires_project=False,
)
def analysis_tolerances(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate and summarise solver equilibrium and convergence tolerances."""
    st = load_settings(ctx)
    an = st.analysis
    rows = [
        {"criterion": "Displacement norm tolerance", "value": values["dispTolMm"], "unit": "mm"},
        {"criterion": "Force equilibrium tolerance", "value": values["forceTolKn"], "unit": "kN"},
        {"criterion": "Energy residual tolerance", "value": values["energyTol"], "unit": "-"},
        {
            "criterion": "P-Delta enabled in project",
            "value": float(bool(getattr(an, "pDelta", False))),
            "unit": "flag",
        },
    ]
    return result(
        summary={
            "dispTolMm": values["dispTolMm"],
            "forceTolKn": values["forceTolKn"],
            "energyTol": values["energyTol"],
            "pDeltaEnabled": bool(getattr(an, "pDelta", False)),
        },
        tables=[
            table(
                "Analysis solver tolerances",
                [("criterion", "Criterion"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Tight energy tolerances (<= 1e-5) are recommended for nonlinear and P-Delta iterations."
        ],
    )


@feature(
    "settingsChecks.meshDefaults",
    "Mesh Defaults",
    part="settings",
    fields=[
        number(
            "maxElementSizeMm",
            "Maximum shell element size",
            600.0,
            unit="mm",
            min=100.0,
            max=3000.0,
        ),
        number("typicalSpanMm", "Typical slab panel span", 6000.0, unit="mm", min=500.0),
        number("slabThicknessMm", "Typical slab thickness", 175.0, unit="mm", min=80.0),
    ],
    requires_project=False,
)
def mesh_defaults(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate FEM shell mesh element sizing against span resolution and thick-plate aspect limits."""
    h_elem = values["maxElementSizeMm"]
    span = values["typicalSpanMm"]
    t = values["slabThicknessMm"]
    divs = span / h_elem
    thick_ratio = h_elem / t
    adequate = divs >= 6.0 and thick_ratio >= 1.0
    rows = [
        {"metric": "Elements per span (L / h)", "value": divs, "recommended": ">= 6.0"},
        {
            "metric": "Size-to-thickness ratio (h / t)",
            "value": thick_ratio,
            "recommended": ">= 1.0",
        },
    ]
    return result(
        summary={"elementsPerSpan": divs, "sizeToThickness": thick_ratio, "meshAdequate": adequate},
        tables=[
            table(
                "FEM shell mesh quality screening",
                [("metric", "Metric"), ("value", "Value"), ("recommended", "Target")],
                rows,
            )
        ],
        notes=[
            "At least 6 shell elements per span captures bending curvature without excessive locking."
        ],
    )


@feature(
    "settingsChecks.stabilityLimits",
    "Stability Limits",
    part="settings",
    fields=[
        number("storeyHeightM", "Typical storey height", 3.2, unit="m", min=1.5),
    ],
    requires_project=False,
)
def stability_limits(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Retrieve allowable seismic drift, wind sway, and P-Delta stability coefficient limits from pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        seis = safe_table(pack, "seismic")
        serv = safe_table(pack, "serviceability")
        drift_map = getattr(seis, "allowableDrift", None) or {}
        cat_drift = float(drift_map.get(st.occupancy.category, 0.02))
        wind_sway = float(getattr(getattr(serv, "sway", None), "ratio", 0.002) or 0.002)
        theta_max = float(getattr(getattr(seis, "stability", None), "thetaMax", 0.25) or 0.25)
    h_mm = values["storeyHeightM"] * 1000.0
    rows = [
        {
            "limit": f"Seismic storey drift (Cat {st.occupancy.category})",
            "ratio": cat_drift,
            "mm": cat_drift * h_mm,
        },
        {"limit": "Wind overall sway", "ratio": wind_sway, "mm": wind_sway * h_mm},
        {"limit": "P-Delta stability θmax", "ratio": theta_max, "mm": 0.0},
    ]
    return result(
        summary={
            "seismicDriftLimit": cat_drift,
            "windSwayLimit": wind_sway,
            "allowableDriftMm": cat_drift * h_mm,
            "pDeltaThetaMax": theta_max,
        },
        tables=[
            table(
                "Stability & drift limits",
                [("limit", "Limit"), ("ratio", "Ratio"), ("mm", "At storey h", "mm")],
                rows,
            )
        ],
        notes=[
            f"Limits read from {code_context.code_name(pack)} seismic and serviceability tables."
        ],
    )


@feature(
    "settingsChecks.namingConventions",
    "Naming Conventions",
    part="settings",
    fields=[],
    requires_project=False,
)
def naming_conventions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit sheet prefixes, fabrication assembly marks, and area load identifiers in project settings."""
    st = load_settings(ctx)
    std = st.drawings.standard
    fab = st.drawings.fabrication
    rows = [
        {"category": "Structural sheets", "prefix": std.structuralPrefix},
        {"category": "Architectural sheets", "prefix": std.architecturalPrefix},
        {"category": "MEP coordination sheets", "prefix": std.coordinationPrefix},
        {"category": "Beam marks", "prefix": fab.beamPrefix},
        {"category": "Column marks", "prefix": fab.columnPrefix},
        {"category": "Brace marks", "prefix": fab.bracePrefix},
        {"category": "Part marks", "prefix": fab.partPrefix},
    ]
    return result(
        summary={
            "prefixCount": len(rows),
            "layerPrefix": std.layerPrefix or "(none)",
            "areaLoadIds": len(st.areaLoads),
        },
        tables=[
            table("Project naming prefixes", [("category", "Category"), ("prefix", "Prefix")], rows)
        ],
        notes=["Configured in drawings.standard and drawings.fabrication."],
    )


@feature(
    "settingsChecks.layerStandards",
    "Layer Standards",
    part="settings",
    fields=[],
    requires_project=False,
)
def layer_standards(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect configured CAD layer overrides, prefixes, colors, and lineweights."""
    st = load_settings(ctx)
    std = st.drawings.standard
    rows = [
        {
            "saengineLayer": lyr.layer,
            "officeName": lyr.name or f"{std.layerPrefix}{lyr.layer}",
            "color": lyr.color if lyr.color is not None else "-",
            "lineweightMm": lyr.lineweight if lyr.lineweight is not None else "-",
        }
        for lyr in std.layers
    ]
    if not rows:
        for default_lyr, col, lw in (
            ("S-GRID", 8, 0.13),
            ("S-COLS", 3, 0.35),
            ("S-BEAM", 4, 0.25),
            ("S-SLAB", 7, 0.18),
        ):
            rows.append(
                {
                    "saengineLayer": default_lyr,
                    "officeName": f"{std.layerPrefix}{default_lyr}",
                    "color": col,
                    "lineweightMm": lw,
                }
            )
    return result(
        summary={
            "configuredLayers": len(std.layers),
            "displayedLayers": len(rows),
            "layerPrefix": std.layerPrefix or "(none)",
        },
        tables=[
            table(
                "CAD layer mapping",
                [
                    ("saengineLayer", "Base layer"),
                    ("officeName", "Output name"),
                    ("color", "ACI color"),
                    ("lineweightMm", "Lineweight", "mm"),
                ],
                rows,
            )
        ],
        notes=["Office layer names override the global layerPrefix when specified."],
    )


@feature(
    "settingsChecks.tagRules",
    "Tag Rules",
    part="settings",
    fields=[],
    requires_project=False,
)
def tag_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check object library and BIM element tag uniqueness against assembly mark prefixes."""
    st = load_settings(ctx)
    objs = list_objects(ctx)
    elems, _ = list_bim_elements(ctx)
    obj_ids = [str(o.get("id", "")) for o in objs if o.get("id")]
    elem_ids = [str(e.get("id", "")) for e in elems if e.get("id")]
    dup_obj = len(obj_ids) - len(set(obj_ids))
    dup_elem = len(elem_ids) - len(set(elem_ids))
    rows = [
        {"scope": "Object types (04 Objects)", "count": len(obj_ids), "duplicates": dup_obj},
        {"scope": "BIM elements (06 BIM)", "count": len(elem_ids), "duplicates": dup_elem},
    ]
    return result(
        summary={
            "objectTypeCount": len(obj_ids),
            "bimElementCount": len(elem_ids),
            "duplicateTags": dup_obj + dup_elem,
            "beamPrefix": st.drawings.fabrication.beamPrefix,
        },
        tables=[
            table(
                "Element & object tag audit",
                [("scope", "Scope"), ("count", "Count"), ("duplicates", "Duplicates")],
                rows,
            )
        ],
        notes=[
            "Verifies unique tag identifiers across object library definitions and BIM elements."
        ],
    )


@feature(
    "settingsChecks.iterationLimit",
    "Iteration Limit",
    part="settings",
    fields=[
        number("maxIterations", "Maximum solver iterations per step", 50.0, min=5.0, max=5000.0),
        number("loadSteps", "Number of incremental load steps", 10.0, min=1.0, max=500.0),
    ],
    requires_project=False,
)
def iteration_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate total Newton-Raphson iteration budget for nonlinear and P-Delta runs."""
    max_it = int(values["maxIterations"])
    steps = int(values["loadSteps"])
    total_budget = max_it * steps
    rows = [
        {"parameter": "Iterations per load step", "value": max_it},
        {"parameter": "Load increments", "value": steps},
        {"parameter": "Total iteration cap", "value": total_budget},
    ]
    return result(
        summary={
            "maxIterationsPerStep": max_it,
            "loadSteps": steps,
            "totalIterationBudget": total_budget,
        },
        tables=[
            table("Solver iteration budget", [("parameter", "Parameter"), ("value", "Count")], rows)
        ],
        notes=[
            "Nonlinear runs should allocate at least 25-50 iterations per step for stiffness reversals."
        ],
    )


@feature(
    "settingsChecks.convergenceTolerance",
    "Convergence Tolerance",
    part="settings",
    fields=[
        number("normDisp", "Displacement increment tolerance", 1e-4, min=1e-9, max=1e-1),
        number("normUnbalance", "Residual force ratio tolerance", 1e-3, min=1e-9, max=1e-1),
    ],
    requires_project=False,
)
def convergence_tolerance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check relative displacement and unbalanced force convergence criteria."""
    du = values["normDisp"]
    df = values["normUnbalance"]
    energy_est = du * df
    strict = du <= 1e-4 and df <= 1e-3
    rows = [
        {
            "norm": "Displacement increment ||Δu|| / ||u||",
            "tolerance": du,
            "status": "strict" if du <= 1e-4 else "relaxed",
        },
        {
            "norm": "Unbalanced force ||R|| / ||F||",
            "tolerance": df,
            "status": "strict" if df <= 1e-3 else "relaxed",
        },
        {
            "norm": "Implied work norm Δu·R",
            "tolerance": energy_est,
            "status": "strict" if energy_est <= 1e-7 else "relaxed",
        },
    ]
    return result(
        summary={
            "displacementTolerance": du,
            "forceTolerance": df,
            "impliedEnergyNorm": energy_est,
            "strictConvergence": strict,
        },
        tables=[
            table(
                "Convergence criteria",
                [("norm", "Norm"), ("tolerance", "Tolerance"), ("status", "Assessment")],
                rows,
            )
        ],
        notes=[
            "Combining displacement and residual force norms prevents false convergence on stiff or flat plateaus."
        ],
    )


@feature(
    "settingsChecks.residualReporting",
    "Residual Reporting",
    part="settings",
    fields=[
        number("totalGravityKn", "Total model gravity reaction", 12000.0, unit="kN", min=1.0),
        number("maxResidualKn", "Max nodal equilibrium residual", 0.25, unit="kN", min=0.0),
    ],
    requires_project=False,
)
def residual_reporting(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate solver global equilibrium residual relative to total model gravity load."""
    grav = values["totalGravityKn"]
    res = values["maxResidualKn"]
    rel = res / grav
    ok = rel <= 1e-4
    rows = [
        {"metric": "Total gravity load", "value": grav, "unit": "kN"},
        {"metric": "Maximum residual force", "value": res, "unit": "kN"},
        {"metric": "Relative unbalance ratio", "value": rel, "unit": "-"},
    ]
    return result(
        summary={"relativeResidual": rel, "maxResidualKn": res, "equilibriumAcceptable": ok},
        tables=[
            table(
                "Residual equilibrium check",
                [("metric", "Metric"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Global equilibrium residuals below 1e-4 of total gravity indicate clean numerical conditioning."
        ],
    )


@feature(
    "settingsChecks.parallelSolver",
    "Parallel Solver",
    part="settings",
    fields=[
        number("requestedThreads", "Requested solver threads (0 = auto)", 0.0, min=0.0, max=128.0),
    ],
    requires_project=False,
)
def parallel_solver(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate model DOF size from BIM elements and recommend solver thread count."""
    elems, stories = list_bim_elements(ctx)
    est_nodes = max(12, len(elems) * 2)
    est_dofs = est_nodes * 6
    cpus = os.cpu_count() or 4
    req = int(values["requestedThreads"])
    recommended = min(cpus, max(1, 2 if est_dofs < 5000 else min(8, cpus)))
    chosen = req if req > 0 else recommended
    rows = [
        {"metric": "BIM elements found", "value": len(elems)},
        {"metric": "Storeys found", "value": len(stories)},
        {"metric": "Estimated active DOFs", "value": est_dofs},
        {"metric": "Host logical CPUs", "value": cpus},
        {"metric": "Selected solver threads", "value": chosen},
    ]
    return result(
        summary={"estimatedDofs": est_dofs, "hostCpus": cpus, "threadsUsed": chosen},
        tables=[table("Parallel solver sizing", [("metric", "Metric"), ("value", "Value")], rows)],
        notes=["Thread count is capped at host CPU count and scaled by estimated DOF bandwidth."],
    )


@feature(
    "settingsChecks.maxSpanRatio",
    "Max Span Ratio",
    part="settings",
    fields=[
        number("fyMpa", "Reinforcement yield strength fy", 420.0, unit="MPa", min=250.0, max=700.0),
    ],
    requires_project=False,
)
def max_span_ratio(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List minimum thickness span-to-depth limits for beams and slabs from active code pack."""
    st = load_settings(ctx)
    fy = values["fyMpa"]
    fy_factor = 0.4 + fy / 700.0
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        conc = safe_table(pack, "concrete")
        beam_div = list(
            getattr(conc, "beamThickness", [16.0, 18.5, 21.0, 8.0]) or [16.0, 18.5, 21.0, 8.0]
        )
        one_way = list(
            getattr(conc, "oneWaySlabThickness", [20.0, 24.0, 28.0, 10.0])
            or [20.0, 24.0, 28.0, 10.0]
        )
    labels = ("Simply supported", "One end continuous", "Both ends continuous", "Cantilever")
    rows = [
        {"member": f"Beam - {lbl}", "baseLOverH": val, "adjustedLOverH": val / fy_factor}
        for lbl, val in zip(labels, beam_div)
    ] + [
        {"member": f"One-way slab - {lbl}", "baseLOverH": val, "adjustedLOverH": val / fy_factor}
        for lbl, val in zip(labels, one_way)
    ]
    return result(
        summary={
            "fyAdjustmentFactor": fy_factor,
            "beamSimpleRatio": beam_div[0] / fy_factor,
            "slabSimpleRatio": one_way[0] / fy_factor,
        },
        tables=[
            table(
                "Span-to-depth limits",
                [
                    ("member", "Member / support"),
                    ("baseLOverH", "Base L/h"),
                    ("adjustedLOverH", "At fy L/h"),
                ],
                rows,
            )
        ],
        notes=[f"Adjusted for fy = {fy:g} MPa using factor (0.4 + fy/700)."],
    )


@feature(
    "settingsChecks.minBarSpacing",
    "Min Bar Spacing",
    part="settings",
    fields=[
        number("barDiameterMm", "Bar diameter db", 20.0, unit="mm", min=8.0, max=50.0),
        number("maxAggregateMm", "Nominal max aggregate size", 20.0, unit="mm", min=10.0, max=50.0),
    ],
    requires_project=False,
)
def min_bar_spacing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute minimum clear bar spacing for beams, columns, and slabs from the active code pack."""
    db = values["barDiameterMm"]
    agg = values["maxAggregateMm"]
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        det = safe_table(pack, "detailing")
        sp = getattr(det, "spacing", None) if det else None
        beam_min = max(
            float(getattr(sp, "layerMin", 25.0) or 25.0),
            float(getattr(sp, "layerDb", 1.0) or 1.0) * db,
            4.0 / 3.0 * agg,
        )
        col_min = max(
            float(getattr(sp, "columnMin", 40.0) or 40.0),
            float(getattr(sp, "columnDb", 1.5) or 1.5) * db,
            4.0 / 3.0 * agg,
        )
    rows = [
        {"element": "Beam / flexural row", "minClearMm": beam_min},
        {"element": "Column longitudinal bars", "minClearMm": col_min},
    ]
    return result(
        summary={"beamMinClearMm": beam_min, "columnMinClearMm": col_min},
        tables=[
            table(
                "Minimum clear bar spacing",
                [("element", "Element"), ("minClearMm", "Min clear spacing", "mm")],
                rows,
            )
        ],
        notes=["Governs max of code minimum, bar-diameter multiple, and 4/3 × max aggregate size."],
    )


@feature(
    "settingsChecks.slendernessLimit",
    "Slenderness Limit",
    part="settings",
    fields=[
        number("m1OverM2", "End moment ratio M1/M2 (+ single curvature)", 0.5, min=-1.0, max=1.0),
    ],
    requires_project=False,
)
def slenderness_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute RC column and steel member slenderness thresholds from active code pack."""
    st = load_settings(ctx)
    ratio = values["m1OverM2"]
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        conc = safe_table(pack, "concrete")
        steel = safe_table(pack, "steel")
        rc_sway = float(getattr(conc, "slendernessLimit", 22.0) or 22.0)
        rc_nonsway = min(40.0, 34.0 - 12.0 * ratio)
        st_comp = (
            float((getattr(steel, "slenderness", None) or {}).get("compression", 150.0))
            if steel
            else 150.0
        )
        st_tens = (
            float((getattr(steel, "slenderness", None) or {}).get("tension", 300.0))
            if steel
            else 300.0
        )
    rows = [
        {"member": "RC column (sway)", "limit": rc_sway},
        {"member": "RC column (nonsway at M1/M2)", "limit": rc_nonsway},
        {"member": "Steel compression member KL/r", "limit": st_comp},
        {"member": "Steel tension member L/r", "limit": st_tens},
    ]
    return result(
        summary={
            "rcSwayLimit": rc_sway,
            "rcNonswayLimit": rc_nonsway,
            "steelCompressionLimit": st_comp,
            "steelTensionLimit": st_tens,
        },
        tables=[
            table(
                "Slenderness thresholds", [("member", "Member"), ("limit", "k·lu / r limit")], rows
            )
        ],
        notes=[
            "Nonsway RC threshold is 34 - 12(M1/M2) <= 40; sway threshold and steel KL/r read from active pack."
        ],
    )


@feature(
    "settingsChecks.deflectionLimit",
    "Deflection Limit",
    part="settings",
    fields=[
        number("spanMm", "Member clear span L", 6000.0, unit="mm", min=500.0),
    ],
    requires_project=False,
)
def deflection_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate serviceability deflection limits in mm across member uses from active code pack."""
    st = load_settings(ctx)
    span = values["spanMm"]
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        serv = safe_table(pack, "serviceability")
        uses = getattr(getattr(serv, "deflection", None), "uses", None) or {}
    rows = []
    for k, u in uses.items():
        live_div = getattr(u, "live", None)
        dl_div = getattr(u, "deadLive", None)
        rows.append(
            {
                "use": k,
                "label": getattr(u, "label", k),
                "liveMm": span / live_div if live_div else 0.0,
                "deadLiveMm": span / dl_div if dl_div else 0.0,
            }
        )
    if not rows:
        rows = [
            {
                "use": "floor",
                "label": "Floor member",
                "liveMm": span / 360.0,
                "deadLiveMm": span / 240.0,
            }
        ]
    return result(
        summary={
            "spanMm": span,
            "floorLiveLimitMm": span / 360.0,
            "floorTotalLimitMm": span / 240.0,
            "useCount": len(rows),
        },
        tables=[
            table(
                "Serviceability deflection limits",
                [
                    ("use", "Key"),
                    ("label", "Member use"),
                    ("liveMm", "Live", "mm"),
                    ("deadLiveMm", "Dead+Live", "mm"),
                ],
                rows,
            )
        ],
        notes=["Divisors retrieved from active code pack serviceability.deflection.uses."],
    )


@feature(
    "settingsChecks.checkSummary",
    "Check Summary",
    part="settings",
    fields=[],
    requires_project=False,
)
def check_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Run full project settings validation and code pack conformance audit."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        st_probs = settings_problems(st)
        pack_findings = conformance.check_pack(pack)
    rows = [{"source": "Settings", "level": "error", "path": p, "message": m} for p, m in st_probs]
    rows += [
        {"source": "CodePack", "level": f.level, "path": f.table or f.check, "message": f.message}
        for f in pack_findings
    ]
    err_n = sum(1 for r in rows if r["level"] == "error")
    warn_n = sum(1 for r in rows if r["level"] == "warning")
    return result(
        summary={
            "errorCount": err_n,
            "warningCount": warn_n,
            "totalFindings": len(rows),
            "allPassing": err_n == 0,
        },
        tables=[
            table(
                "Project settings check summary",
                [
                    ("source", "Source"),
                    ("level", "Severity"),
                    ("path", "Location"),
                    ("message", "Finding"),
                ],
                rows
                or [
                    {
                        "source": "All",
                        "level": "ok",
                        "path": "-",
                        "message": "No settings or conformance problems found.",
                    }
                ],
            )
        ],
        notes=[f"Checked settings against code pack {code_context.code_name(pack)}."],
    )


@feature(
    "settingsChecks.warningThreshold",
    "Warning Threshold",
    part="settings",
    fields=[
        number("warnRatio", "Warning utilisation threshold", 0.85, min=0.5, max=1.0),
        number("blockRatio", "Blocking error utilisation threshold", 1.00, min=0.8, max=1.5),
        number("sampleUtil", "Test utilisation ratio", 0.92, min=0.0, max=2.0),
    ],
    requires_project=False,
)
def warning_threshold(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Classify member utilisation against warning and blocking failure thresholds."""
    w = values["warnRatio"]
    b = values["blockRatio"]
    u = values["sampleUtil"]
    if b < w:
        raise FeatureInputError("Blocking error threshold must be >= warning threshold.")
    status = "FAIL (blocking)" if u > b else ("WARNING" if u >= w else "PASS")
    rows = [
        {"band": "Pass", "range": f"< {w:.2f}"},
        {"band": "Warning", "range": f"{w:.2f} to {b:.2f}"},
        {"band": "Blocking failure", "range": f"> {b:.2f}"},
    ]
    return result(
        summary={"warnRatio": w, "blockRatio": b, "sampleStatus": status, "isBlocking": u > b},
        tables=[
            table(
                "Utilisation severity bands",
                [("band", "Band"), ("range", "Utilisation range")],
                rows,
            )
        ],
        notes=["Controls escalation of near-limit checks into blocking workflow errors."],
    )


@feature(
    "settingsChecks.resultsArchive",
    "Results Archive",
    part="settings",
    fields=[
        checkbox("writeArchive", "Save JSON snapshot to project exports", True),
    ],
    requires_project=False,
)
def results_archive(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Capture a settings and conformance check archive snapshot."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        probs = settings_problems(st)
    snapshot = {
        "project": st.project.name,
        "codePack": st.codePack,
        "problemCount": len(probs),
        "problems": [{"path": p, "message": m} for p, m in probs],
        "settings": st.model_dump(mode="json", by_alias=True, exclude_none=True),
    }
    out_path = None
    if values["writeArchive"] and ctx.root is not None:
        out_path = export_file(ctx, "checks-snapshot.json", json_dumps_clean(snapshot))
    return result(
        summary={
            "problemCount": len(probs),
            "codePack": st.codePack,
            "archived": out_path is not None,
        },
        tables=[
            table(
                "Snapshot summary",
                [("path", "Path"), ("message", "Message")],
                snapshot["problems"] or [{"path": "-", "message": "Clean snapshot"}],
            )
        ],
        notes=[
            f"Archive written to {out_path}"
            if out_path
            else "Open a project folder to write checks-snapshot.json."
        ],
    )


@feature(
    "settingsChecks.snapshotCompare",
    "Snapshot Compare",
    part="settings",
    fields=[
        text("baselineJson", "Baseline settings JSON (blank = compare with pack defaults)", ""),
    ],
    requires_project=False,
)
def snapshot_compare(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare current project settings against a baseline JSON or default pack settings."""
    st = load_settings(ctx)
    cur = st.model_dump(mode="json", by_alias=True, exclude_none=True)
    raw_base = values["baselineJson"].strip()
    if raw_base:
        try:
            base = json.loads(raw_base)
        except ValueError as exc:
            raise FeatureInputError(f"Invalid baseline JSON: {exc}") from exc
    else:
        base = default_project_settings(st.project.name, st.codePack).model_dump(
            mode="json", by_alias=True, exclude_none=True
        )

    diffs = []
    for k in sorted(set(cur) | set(base)):
        if cur.get(k) != base.get(k):
            diffs.append(
                {
                    "section": k,
                    "currentType": type(cur.get(k)).__name__,
                    "baselineType": type(base.get(k)).__name__,
                    "changed": True,
                }
            )
    return result(
        summary={"sectionsCompared": len(set(cur) | set(base)), "changedSections": len(diffs)},
        tables=[
            table(
                "Settings snapshot comparison",
                [
                    ("section", "Top-level key"),
                    ("currentType", "Current"),
                    ("baselineType", "Baseline"),
                    ("changed", "Differs"),
                ],
                diffs
                or [{"section": "all", "currentType": "-", "baselineType": "-", "changed": False}],
            )
        ],
        notes=[
            "Compares top-level project settings sections against baseline JSON or pack defaults."
        ],
    )


@feature(
    "settingsChecks.checkProfiles",
    "Check Profiles",
    part="settings",
    fields=[
        select(
            "stage",
            "Design stage profile",
            [
                ("concept", "Concept / Preliminary"),
                ("permit", "Permit Submission"),
                ("detailed", "Detailed Design"),
                ("ifc", "Issued for Construction"),
            ],
            "detailed",
        ),
    ],
    requires_project=False,
)
def check_profiles(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure verification check scope by project delivery stage."""
    stage = values["stage"]
    profiles = {
        "concept": [
            ("Gravity sizing", True),
            ("Lateral drift", True),
            ("Foundation bearing", False),
            ("Rebar detailing", False),
        ],
        "permit": [
            ("Gravity sizing", True),
            ("Lateral drift", True),
            ("Foundation bearing", True),
            ("Rebar detailing", False),
        ],
        "detailed": [
            ("Gravity sizing", True),
            ("Lateral drift", True),
            ("Foundation bearing", True),
            ("Rebar detailing", True),
        ],
        "ifc": [
            ("Gravity sizing", True),
            ("Lateral drift", True),
            ("Foundation bearing", True),
            ("Rebar detailing", True),
        ],
    }
    rows = [{"check": name, "enabled": en, "stage": stage} for name, en in profiles[stage]]
    return result(
        summary={
            "stage": stage,
            "enabledChecks": sum(1 for _, en in profiles[stage] if en),
            "totalChecks": len(rows),
        },
        tables=[
            table(
                "Stage check profile",
                [("check", "Check group"), ("enabled", "Enabled"), ("stage", "Stage")],
                rows,
            )
        ],
        notes=["Selects active validation gates appropriate for the current project milestone."],
    )


@feature(
    "settingsChecks.autoRunChecks",
    "Auto Run Checks",
    part="settings",
    fields=[],
    requires_project=False,
)
def auto_run_checks(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect dependency pipeline and stale-check triggers across project parts."""
    raw = load_settings_raw(ctx)
    has_soil = ctx.raw("soil") is not None
    has_mats = ctx.raw("materials") is not None
    has_bim = ctx.raw("bim") is not None
    rows = [
        {
            "stage": "1. Soil -> Settings",
            "upstreamPresent": has_soil,
            "trigger": "Site class & hazard",
        },
        {
            "stage": "2. Settings -> Materials",
            "upstreamPresent": bool(raw),
            "trigger": "Code pack & exposure",
        },
        {
            "stage": "3. Materials -> Objects/BIM",
            "upstreamPresent": has_mats,
            "trigger": "Elastic modulus & strength",
        },
        {
            "stage": "4. BIM -> FEM/Design",
            "upstreamPresent": has_bim,
            "trigger": "Loads, combinations & checks",
        },
    ]
    return result(
        summary={
            "hasSettings": bool(raw),
            "hasSoil": has_soil,
            "hasMaterials": has_mats,
            "hasBim": has_bim,
        },
        tables=[
            table(
                "Automated dependency triggers",
                [
                    ("stage", "Pipeline stage"),
                    ("upstreamPresent", "Data present"),
                    ("trigger", "Propagated settings"),
                ],
                rows,
            )
        ],
        notes=[
            "Upstream changes invalidate downstream derived loads, stiffnesses, and design checks."
        ],
    )


@feature(
    "settingsChecks.issueAssignment",
    "Issue Assignment",
    part="settings",
    fields=[
        text("defaultAssignee", "Default reviewer / assignee", "Lead Structural Engineer"),
        text("dueDate", "Target resolution date", "2026-12-01"),
    ],
    requires_project=False,
)
def issue_assignment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate an assigned issue register from active project settings validation problems."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        probs = settings_problems(st)
    rows = [
        {
            "issueId": f"SET-{i:03d}",
            "path": path,
            "description": msg,
            "assignee": values["defaultAssignee"],
            "dueDate": values["dueDate"],
        }
        for i, (path, msg) in enumerate(probs, start=1)
    ]
    return result(
        summary={"openIssues": len(rows), "assignee": values["defaultAssignee"]},
        tables=[
            table(
                "Settings issue assignment register",
                [
                    ("issueId", "ID"),
                    ("path", "Field"),
                    ("description", "Issue"),
                    ("assignee", "Assignee"),
                    ("dueDate", "Due"),
                ],
                rows
                or [
                    {
                        "issueId": "SET-000",
                        "path": "-",
                        "description": "No open settings issues",
                        "assignee": values["defaultAssignee"],
                        "dueDate": values["dueDate"],
                    }
                ],
            )
        ],
        notes=[
            "Populated from live validation of 02 Project Settings against the active code pack."
        ],
    )

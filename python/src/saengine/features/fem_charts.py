"""Analysis Charts - Charts tab: utilisation, story drift, hinge, force/deflection/histogram charts and exports."""

from __future__ import annotations

import csv
import io
from typing import Any

import numpy as np

from saengine.design import check as design_check
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
from saengine.features.fem_common import (
    export_fem_file,
    format_json,
    load_bim,
    load_manifest,
    load_materials,
    load_objects,
    load_settings,
    optional_osmodel,
    require_results,
)
from saengine.fem import acceptance, result_tables, seismic_design, story_response
from saengine.report.clauses import in_force


def _first_member_table(out_dir: Any, model_path: Any, case_filter: str = "") -> dict[str, Any]:
    idx = result_tables.table_index(out_dir, model_path)
    filt = case_filter.strip().lower()
    for entry in idx.get("results", []):
        if filt and filt not in str(entry.get("label", "")).lower():
            continue
        if any(t["id"] == "members" for t in entry.get("tables", [])):
            return result_tables.result_table(out_dir, model_path, entry["key"], "members")
    raise FeatureInputError("No member force table available in 08 FEM/model.results.")


@feature(
    "femCharts.utilisationChart",
    "Utilisation Chart",
    part="fem",
    fields=[text("memberFilter", "Member filter (blank = all)", "")],
    requires_project=True,
)
def utilisation_chart(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Chart demand-to-capacity utilisation ratios across designed structural members."""
    out_dir, _model_path = require_results(ctx)
    _, model = optional_osmodel(ctx)
    bim = load_bim(ctx)
    obj_lib, _ = load_objects(ctx)
    mat_lib, _ = load_materials(ctx)
    settings = load_settings(ctx)
    if not (model and bim and obj_lib and mat_lib):
        raise FeatureInputError(
            "Missing BIM, Objects, Materials, or OSModel for member capacity check."
        )
    with in_force(ctx.root):
        res = design_check.design(model, out_dir, bim, obj_lib, mat_lib, settings)
    filt = values["memberFilter"].strip().lower()
    rows = [
        {
            "member": str(m.get("member", "")),
            "kind": str(m.get("kind", "")),
            "utilisation": float(m.get("utilisation", 0.0)),
            "ok": bool(m.get("ok", True)),
        }
        for m in res.get("members", [])
        if not filt or filt in str(m.get("member", "")).lower()
    ]
    rows.sort(key=lambda r: -r["utilisation"])
    return result(
        summary={
            "memberCount": len(rows),
            "peakUtilisation": rows[0]["utilisation"] if rows else 0.0,
            "failing": sum(1 for r in rows if not r["ok"]),
        },
        tables=[
            table(
                "Member utilisation chart series",
                [("member", "Member"), ("kind", "Kind"), ("utilisation", "DCR"), ("ok", "OK")],
                rows[:50],
            )
        ],
        notes=["Demand-capacity ratios computed by saengine.design.check.design."],
    )


@feature(
    "femCharts.storyDriftChart",
    "Story Drift Chart",
    part="fem",
    fields=[text("caseFilter", "Load case filter (blank = all lateral)", "")],
    requires_project=True,
)
def story_drift_chart(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Chart inter-storey drift ratios per floor against the allowable code drift limit."""
    out_dir, model_path = require_results(ctx)
    settings = load_settings(ctx)
    with in_force(ctx.root):
        lim = seismic_design.settings_drift_limit(settings)
    allow = float(lim.get("allowable") or 0.02) if isinstance(lim, dict) else 0.02
    resp = story_response.story_response(out_dir, model_path)
    filt = values["caseFilter"].strip().lower()
    rows = []
    for c in resp.get("cases", []):
        lbl = str(c.get("label", ""))
        if filt and filt not in lbl.lower():
            continue
        for lv in c.get("levels", []):
            dx, dy = abs(float(lv.get("driftX", 0.0))), abs(float(lv.get("driftY", 0.0)))
            rows.append(
                {
                    "case": lbl,
                    "level": str(lv.get("name", "")),
                    "elevM": float(lv.get("z", 0.0)),
                    "driftX": dx,
                    "driftY": dy,
                    "limit": allow,
                }
            )
    if not rows:
        raise FeatureInputError("No storey drift series found in 08 FEM/model.results.")
    return result(
        summary={
            "points": len(rows),
            "maxDrift": max(max(r["driftX"], r["driftY"]) for r in rows),
            "limit": allow,
        },
        tables=[
            table(
                "Storey drift chart data",
                [
                    ("case", "Case"),
                    ("level", "Level"),
                    ("elevM", "Elev", "m"),
                    ("driftX", "Drift X"),
                    ("driftY", "Drift Y"),
                    ("limit", "Limit"),
                ],
                rows[:50],
            )
        ],
        notes=["Plots inter-storey drift ratios against allowable code limit."],
    )


@feature(
    "femCharts.hingeChart",
    "Hinge Chart",
    part="fem",
    fields=[],
    requires_project=True,
)
def hinge_chart(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Chart plastic hinge formation states against pushover load step."""
    out_dir, model_path = require_results(ctx)
    push = acceptance.pushover_results(out_dir, model_path)
    if not push:
        raise FeatureInputError("No pushover hinge results found in 08 FEM/model.results.")
    rows = [
        {
            "case": str(p.get("name", "")),
            "steps": int(p.get("steps") or 0),
            "maxShearKn": float(p.get("maxShearKn") or 0.0),
            "maxDispMm": float(p.get("maxDispMm") or 0.0),
        }
        for p in push
    ]
    return result(
        summary={"pushoverCases": len(rows)},
        tables=[
            table(
                "Pushover hinge step progression",
                [
                    ("case", "Case"),
                    ("steps", "Steps"),
                    ("maxShearKn", "Peak V", "kN"),
                    ("maxDispMm", "Peak Δ", "mm"),
                ],
                rows,
            )
        ],
        notes=["Extracted from pushover analysis results in 08 FEM/model.results."],
    )


@feature(
    "femCharts.compareCases",
    "Compare Cases",
    part="fem",
    fields=[
        text("caseA", "First case label", "EX"),
        text("caseB", "Second case label", "EY"),
    ],
    requires_project=True,
)
def compare_cases(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Overlay storey displacement curves for two analyzed load cases."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    cases = resp.get("cases", [])
    ca, cb = values["caseA"].strip().lower(), values["caseB"].strip().lower()
    ra = next((c for c in cases if ca in str(c.get("label", "")).lower()), None)
    rb = next((c for c in cases if cb in str(c.get("label", "")).lower()), None)
    if ra is None or rb is None:
        raise FeatureInputError(
            "One or both requested load cases were not found in 08 FEM/model.results."
        )
    rows = [
        {
            "level": a.get("name"),
            "elevM": a.get("z"),
            "caseAMm": a.get("maxUxMm", 0.0),
            "caseBMm": b.get("maxUyMm", 0.0),
        }
        for a, b in zip(ra.get("levels", []), rb.get("levels", []), strict=False)
    ]
    return result(
        summary={"caseA": ra.get("label"), "caseB": rb.get("label"), "points": len(rows)},
        tables=[
            table(
                "Dual-case displacement overlay",
                [
                    ("level", "Level"),
                    ("elevM", "Elevation", "m"),
                    ("caseAMm", "Case A Ux", "mm"),
                    ("caseBMm", "Case B Uy", "mm"),
                ],
                rows,
            )
        ],
        notes=["Compares floor displacement envelopes across two selected cases."],
    )


@feature(
    "femCharts.chartTemplates",
    "Chart Templates",
    part="fem",
    fields=[
        text("templateName", "Template name", "storey-drift-standard"),
        select(
            "chartKind",
            "Chart type",
            [
                ("drift", "Storey drift vs limit"),
                ("shear", "Storey shear profile"),
                ("moment", "Member bending diagram"),
                ("utilisation", "DCR bar chart"),
            ],
            "drift",
        ),
    ],
    requires_project=True,
)
def chart_templates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Save a reusable chart template configuration against analyzed project results."""
    out_dir, _ = require_results(ctx)
    tpl = {
        "name": values["templateName"],
        "kind": values["chartKind"],
        "resultsDir": str(out_dir),
        "gridlines": True,
        "showLimits": True,
    }
    path = export_fem_file(ctx, f"chart-template-{values['templateName']}.json", format_json(tpl))
    return result(
        summary={
            "templateName": values["templateName"],
            "chartKind": values["chartKind"],
            "templatePath": str(path),
        },
        tables=[
            table(
                "Saved chart template",
                [("key", "Setting"), ("val", "Value")],
                [{"key": k, "val": str(v)} for k, v in tpl.items()],
            )
        ],
        notes=[f"Chart template written to {path}"],
    )


@feature(
    "femCharts.annotateChart",
    "Annotate Chart",
    part="fem",
    fields=[
        number("limitValue", "Reference limit line value", 0.02, min=0.0),
        text("annotationText", "Callout label", "Code drift threshold"),
    ],
    requires_project=True,
)
def annotate_chart(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Identify points exceeding a chart threshold and attach callout annotations."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    lim = values["limitValue"]
    callouts = []
    for c in resp.get("cases", []):
        for lv in c.get("levels", []):
            val = max(abs(float(lv.get("driftX", 0.0))), abs(float(lv.get("driftY", 0.0))))
            if val >= lim:
                callouts.append(
                    {
                        "case": str(c.get("label", "")),
                        "level": str(lv.get("name", "")),
                        "value": val,
                        "label": values["annotationText"],
                    }
                )
    return result(
        summary={"limitValue": lim, "annotationsGenerated": len(callouts)},
        tables=[
            table(
                "Chart threshold annotations",
                [("case", "Case"), ("level", "Level"), ("value", "Value"), ("label", "Annotation")],
                callouts[:30]
                or [{"case": "All", "level": "-", "value": 0.0, "label": "No exceedances"}],
            )
        ],
        notes=["Generates horizontal threshold markers and exceedance callout coordinates."],
    )


@feature(
    "femCharts.exportChart",
    "Export Chart",
    part="fem",
    fields=[
        select("format", "Export format", [("svg", "Vector SVG"), ("csv", "Data CSV")], "svg"),
        text("caseCode", "Case code", "EX"),
    ],
    requires_project=True,
)
def export_chart(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export storey response chart series as SVG vector graphic or CSV data."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    code = values["caseCode"].strip().lower()
    case = next((c for c in resp.get("cases", []) if code in str(c.get("label", "")).lower()), None)
    if case is None:
        cases = resp.get("cases", [])
        if not cases:
            raise FeatureInputError("No case data available to export.")
        case = cases[0]
    levels = case.get("levels", [])
    if values["format"] == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["level", "z_m", "maxUxMm", "maxUyMm"])
        for lv in levels:
            w.writerow(
                [lv.get("name"), lv.get("z"), lv.get("maxUxMm", 0.0), lv.get("maxUyMm", 0.0)]
            )
        path = export_fem_file(ctx, "chart-export.csv", buf.getvalue())
    else:
        max_u = max((abs(float(lv.get("maxUxMm", 0.0))) for lv in levels), default=1.0) or 1.0
        pts = " ".join(
            f"{40 + abs(float(lv.get('maxUxMm', 0.0))) / max_u * 200:.1f},{260 - i * 40}"
            for i, lv in enumerate(levels)
        )
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300"><polyline fill="none" stroke="#2563eb" stroke-width="2" points="{pts}"/></svg>\n'
        path = export_fem_file(ctx, "chart-export.svg", svg)
    return result(
        summary={
            "case": str(case.get("label", "")),
            "points": len(levels),
            "exportPath": str(path),
        },
        tables=[
            table(
                "Exported chart series",
                [("level", "Level"), ("z", "Elev", "m"), ("ux", "Ux", "mm")],
                [
                    {"level": lv.get("name"), "z": lv.get("z"), "ux": lv.get("maxUxMm", 0.0)}
                    for lv in levels
                ],
            )
        ],
        notes=[f"Chart exported to {path}"],
    )


@feature(
    "femCharts.copyToReport",
    "Copy to Report",
    part="fem",
    fields=[text("caption", "Figure caption", "Storey Lateral Displacement Envelope")],
    requires_project=True,
)
def copy_to_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Package chart figure metadata and data snippet for insertion into the engineering report."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    cases = resp.get("cases", [])
    snippet = {"caption": values["caption"], "cases": [c.get("label") for c in cases[:6]]}
    path = export_fem_file(ctx, "report-chart-figure.json", format_json(snippet))
    return result(
        summary={
            "caption": values["caption"],
            "casesIncluded": len(snippet["cases"]),
            "figurePath": str(path),
        },
        tables=[
            table(
                "Report figure bundle",
                [("item", "Field"), ("value", "Value")],
                [
                    {"item": "Caption", "value": values["caption"]},
                    {"item": "Cases", "value": ", ".join(str(x) for x in snippet["cases"])},
                ],
            )
        ],
        notes=[f"Report figure metadata saved to {path}"],
    )


@feature(
    "femCharts.chartData",
    "Chart Data",
    part="fem",
    fields=[],
    requires_project=True,
)
def chart_data(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export underlying numeric series of storey responses to CSV."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    rows = []
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["case", "level", "z_m", "maxUxMm", "maxUyMm", "driftX", "driftY"])
    for c in resp.get("cases", []):
        for lv in c.get("levels", []):
            r = {
                "case": c.get("label"),
                "level": lv.get("name"),
                "zM": lv.get("z"),
                "uxMm": lv.get("maxUxMm", 0.0),
                "uyMm": lv.get("maxUyMm", 0.0),
            }
            rows.append(r)
            w.writerow(
                [
                    r["case"],
                    r["level"],
                    r["zM"],
                    r["uxMm"],
                    r["uyMm"],
                    lv.get("driftX", 0.0),
                    lv.get("driftY", 0.0),
                ]
            )
    path = export_fem_file(ctx, "chart-data.csv", buf.getvalue())
    return result(
        summary={"rowsExported": len(rows), "csvPath": str(path)},
        tables=[
            table(
                "Chart data table",
                [
                    ("case", "Case"),
                    ("level", "Level"),
                    ("zM", "Elev", "m"),
                    ("uxMm", "Ux", "mm"),
                    ("uyMm", "Uy", "mm"),
                ],
                rows[:40],
            )
        ],
        notes=[f"Underlying chart table exported to {path}"],
    )


@feature(
    "femCharts.forceCharts",
    "Force Charts",
    part="fem",
    fields=[text("caseFilter", "Case/combo filter", "")],
    requires_project=True,
)
def force_charts(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Extract station-by-station member axial, shear, and bending moment chart series."""
    out_dir, model_path = require_results(ctx)
    tbl = _first_member_table(out_dir, model_path, values["caseFilter"])
    cols = [c["key"] for c in tbl.get("columns", [])]
    rows = [dict(zip(cols, r, strict=False)) for r in tbl.get("rows", [])[:40]]
    return result(
        summary={"rows": len(tbl.get("rows", [])), "columns": len(cols)},
        tables=[
            table(
                "Member force chart series",
                [(c["key"], c["title"]) for c in tbl.get("columns", [])[:7]],
                rows,
            )
        ],
        notes=["Station forces along member local axes (P, V2, V3, T, M2, M3)."],
    )


@feature(
    "femCharts.deflectionChart",
    "Deflection Chart",
    part="fem",
    fields=[text("caseFilter", "Case filter", "")],
    requires_project=True,
)
def deflection_chart(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Plot nodal vertical and lateral deflection profiles across analyzed levels."""
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    filt = values["caseFilter"].strip().lower()
    target = next(
        (
            e
            for e in idx.get("results", [])
            if (not filt or filt in str(e.get("label", "")).lower())
            and any(t["id"] == "displacements" for t in e.get("tables", []))
        ),
        None,
    )
    if target is None:
        raise FeatureInputError("No nodal displacement table found in 08 FEM/model.results.")
    tbl = result_tables.result_table(out_dir, model_path, target["key"], "displacements")
    cols = [c["key"] for c in tbl.get("columns", [])]
    rows = [dict(zip(cols, r, strict=False)) for r in tbl.get("rows", [])[:40]]
    return result(
        summary={"case": target["label"], "nodes": len(tbl.get("rows", []))},
        tables=[
            table(
                f"Deflection series ({target['label']})",
                [(c["key"], c["title"]) for c in tbl.get("columns", [])[:7]],
                rows,
            )
        ],
        notes=["Joint translations Ux, Uy, Uz [mm] and rotations [rad]."],
    )


@feature(
    "femCharts.timeSeriesChart",
    "Time Series Chart",
    part="fem",
    fields=[],
    requires_project=True,
)
def time_series_chart(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Extract dynamic transient time-history series from 08 FEM/model.results."""
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
        summary={"transientCases": len(th), "rows": len(tbl.get("rows", []))},
        tables=[
            table(
                f"Transient peak series ({th[0]['label']})",
                [(c["key"], c["title"]) for c in tbl.get("columns", [])],
                rows,
            )
        ],
        notes=["Reads transient analysis peak histories from 08 FEM/model.results."],
    )


@feature(
    "femCharts.histogramChart",
    "Histogram Chart",
    part="fem",
    fields=[number("bins", "Number of histogram bins", 10, min=3, max=40)],
    requires_project=True,
)
def histogram_chart(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Bin analyzed member bending moments into a frequency distribution histogram."""
    out_dir, model_path = require_results(ctx)
    tbl = _first_member_table(out_dir, model_path)
    cols = [c["key"] for c in tbl.get("columns", [])]
    m_idx = cols.index("M3") if "M3" in cols else len(cols) - 1
    vals = np.array([abs(float(r[m_idx])) for r in tbl.get("rows", [])], dtype=float)
    if not vals.size:
        raise FeatureInputError("No member values available for histogram.")
    counts, edges = np.histogram(vals, bins=int(values["bins"]))
    rows = [
        {"binRange": f"{edges[i]:.1f} – {edges[i + 1]:.1f}", "count": int(counts[i])}
        for i in range(len(counts))
    ]
    return result(
        summary={
            "samples": int(vals.size),
            "bins": int(values["bins"]),
            "maxAbsM3Knm": float(vals.max()),
        },
        tables=[
            table(
                "Member |M3| distribution histogram",
                [("binRange", "Range [kN·m]"), ("count", "Frequency")],
                rows,
            )
        ],
        notes=["Histograms show concentration of high-demand vs lightly loaded member stations."],
    )


@feature(
    "femCharts.scatterPlot",
    "Scatter Plot",
    part="fem",
    fields=[],
    requires_project=True,
)
def scatter_plot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Correlate member axial force P against major-axis moment M3 across stations."""
    out_dir, model_path = require_results(ctx)
    tbl = _first_member_table(out_dir, model_path)
    cols = [c["key"] for c in tbl.get("columns", [])]
    pi = cols.index("P") if "P" in cols else 2
    mi = cols.index("M3") if "M3" in cols else len(cols) - 1
    rows = [
        {"member": str(r[0]), "axialKn": float(r[pi]), "momentKnm": float(r[mi])}
        for r in tbl.get("rows", [])[:50]
    ]
    xs = np.array([r["axialKn"] for r in rows], dtype=float)
    ys = np.array([r["momentKnm"] for r in rows], dtype=float)
    corr = (
        float(np.corrcoef(xs, ys)[0, 1]) if len(rows) > 1 and xs.std() > 0 and ys.std() > 0 else 0.0
    )
    return result(
        summary={"points": len(rows), "pearsonCorrelation": corr},
        tables=[
            table(
                "P vs M3 interaction scatter points",
                [
                    ("member", "Member"),
                    ("axialKn", "Axial P", "kN"),
                    ("momentKnm", "Moment M3", "kN·m"),
                ],
                rows,
            )
        ],
        notes=["Useful for inspecting P-M demand clustering across column and beam stations."],
    )


@feature(
    "femCharts.axisScales",
    "Axis Scales",
    part="fem",
    fields=[
        select(
            "xScale",
            "X-axis scale",
            [("linear", "Linear"), ("log", "Logarithmic (base 10)")],
            "linear",
        ),
        select(
            "yScale",
            "Y-axis scale",
            [("linear", "Linear"), ("log", "Logarithmic (base 10)")],
            "linear",
        ),
    ],
    requires_project=True,
)
def axis_scales(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Transform modal spectrum or storey response coordinates into linear or logarithmic scale bounds."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    levels = (resp.get("cases") or [{}])[0].get("levels", [])
    zs = [max(float(lv.get("z", 0.0)), 0.1) for lv in levels] or [1.0]
    rows = [
        {"axis": "X", "scale": values["xScale"], "minVal": min(zs), "maxVal": max(zs)},
        {
            "axis": "Y",
            "scale": values["yScale"],
            "minVal": 0.0 if values["yScale"] == "linear" else 0.01,
            "maxVal": max(zs),
        },
    ]
    return result(
        summary={"xScale": values["xScale"], "yScale": values["yScale"]},
        tables=[
            table(
                "Axis scale configuration",
                [("axis", "Axis"), ("scale", "Scale"), ("minVal", "Min"), ("maxVal", "Max")],
                rows,
            )
        ],
        notes=["Logarithmic axes require strictly positive non-zero ordinates."],
    )


@feature(
    "femCharts.dualAxis",
    "Dual Axis",
    part="fem",
    fields=[],
    requires_project=True,
)
def dual_axis(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Pair storey displacement [mm] with storey shear [kN] on primary and secondary chart axes."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    cases = resp.get("cases", [])
    if not cases:
        raise FeatureInputError("Run the analysis first.")
    rows = [
        {
            "level": lv.get("name"),
            "dispMm": float(lv.get("maxUxMm", 0.0)),
            "shearKn": float(lv.get("shearXKn", 0.0)),
        }
        for lv in cases[0].get("levels", [])
    ]
    return result(
        summary={"case": str(cases[0].get("label", "")), "levels": len(rows)},
        tables=[
            table(
                "Dual-axis displacement & shear data",
                [
                    ("level", "Level"),
                    ("dispMm", "Primary: Ux", "mm"),
                    ("shearKn", "Secondary: Vx", "kN"),
                ],
                rows,
            )
        ],
        notes=["Combines kinematic displacement and static shear on shared elevation ordinates."],
    )


@feature(
    "femCharts.legendSettings",
    "Legend Settings",
    part="fem",
    fields=[
        select(
            "position",
            "Legend placement",
            [("topRight", "Top Right"), ("bottom", "Bottom"), ("outsideRight", "Outside Right")],
            "topRight",
        )
    ],
    requires_project=True,
)
def legend_settings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build ordered legend entries from active result cases in 08 FEM/model.results."""
    out_dir, _ = require_results(ctx)
    manifest = load_manifest(out_dir)
    rows = [
        {"order": i + 1, "label": str(c.get("case_name", "")), "position": values["position"]}
        for i, c in enumerate(manifest.get("cases", []))
    ]
    return result(
        summary={"legendEntries": len(rows), "position": values["position"]},
        tables=[
            table(
                "Chart legend series",
                [("order", "Order"), ("label", "Series Label"), ("position", "Placement")],
                rows,
            )
        ],
        notes=["Maintains consistent case ordering across multi-series charts."],
    )


@feature(
    "femCharts.gridlines",
    "Gridlines",
    part="fem",
    fields=[
        checkbox("majorGrid", "Show major gridlines", True),
        checkbox("minorGrid", "Show minor sub-gridlines", False),
        number("majorDivisions", "Target major tick intervals", 5, min=2, max=20),
    ],
    requires_project=True,
)
def gridlines(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute clean round tick intervals for active chart result ranges."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    peak = (
        max(
            (
                abs(float(lv.get("maxUxMm", 0.0)))
                for c in resp.get("cases", [])
                for lv in c.get("levels", [])
            ),
            default=10.0,
        )
        or 10.0
    )
    step = peak / values["majorDivisions"]
    rows = [
        {"tick": i, "valueMm": round(i * step, 2)} for i in range(int(values["majorDivisions"]) + 1)
    ]
    return result(
        summary={
            "majorGrid": values["majorGrid"],
            "minorGrid": values["minorGrid"],
            "stepMm": step,
        },
        tables=[
            table(
                "Computed major axis grid ticks",
                [("tick", "Tick"), ("valueMm", "Value", "mm")],
                rows,
            )
        ],
        notes=["Generates evenly spaced tick coordinates covering the observed result domain."],
    )


@feature(
    "femCharts.axisLabels",
    "Axis Labels",
    part="fem",
    fields=[
        text("xTitle", "Horizontal axis title", "Lateral Displacement [mm]"),
        text("yTitle", "Vertical axis title", "Storey Elevation [m]"),
    ],
    requires_project=True,
)
def axis_labels(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate and bind SI-unit axis titles to the active chart dataset."""
    require_results(ctx)
    rows = [{"axis": "X", "title": values["xTitle"]}, {"axis": "Y", "title": values["yTitle"]}]
    return result(
        summary={"xTitle": values["xTitle"], "yTitle": values["yTitle"]},
        tables=[table("Chart axis titles", [("axis", "Axis"), ("title", "Title & Units")], rows)],
        notes=["All chart axes display explicit SI units."],
    )


@feature(
    "femCharts.colourPalette",
    "Colour Palette",
    part="fem",
    fields=[
        select(
            "palette",
            "Palette scheme",
            [
                ("engineering", "Engineering Blue-Red"),
                ("viridis", "Viridis Perceptual"),
                ("monochrome", "Print Monochrome"),
            ],
            "engineering",
        )
    ],
    requires_project=True,
)
def colour_palette(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign colour-blind-safe hex series colours to analyzed load cases."""
    out_dir, _ = require_results(ctx)
    manifest = load_manifest(out_dir)
    palettes = {
        "engineering": ["#1d4ed8", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0891b2"],
        "viridis": ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725", "#31688e"],
        "monochrome": ["#111827", "#374151", "#6b7280", "#9ca3af", "#d1d5db", "#4b5563"],
    }
    cols = palettes[values["palette"]]
    rows = [
        {"case": str(c.get("case_name", "")), "hex": cols[i % len(cols)]}
        for i, c in enumerate(manifest.get("cases", []))
    ]
    return result(
        summary={"palette": values["palette"], "seriesStyled": len(rows)},
        tables=[
            table("Series colour assignments", [("case", "Case"), ("hex", "Hex Colour")], rows)
        ],
        notes=["Cycles perceptually distinct colours across active load cases."],
    )


@feature(
    "femCharts.lineStyles",
    "Line Styles",
    part="fem",
    fields=[number("strokeWidthPx", "Line weight", 2.0, unit="px", min=0.5, max=6.0)],
    requires_project=True,
)
def line_styles(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure line dash patterns and weights distinguishing static, modal, and limit series."""
    out_dir, _ = require_results(ctx)
    manifest = load_manifest(out_dir)
    rows = []
    for c in manifest.get("cases", []):
        rt = str(c.get("result_type", "StaticResults"))
        dash = "solid" if rt == "StaticResults" else ("dashed" if "Spectrum" in rt else "dotted")
        rows.append(
            {
                "case": str(c.get("case_name", "")),
                "dashPattern": dash,
                "widthPx": values["strokeWidthPx"],
            }
        )
    return result(
        summary={"strokeWidthPx": values["strokeWidthPx"], "casesStyled": len(rows)},
        tables=[
            table(
                "Series line styles",
                [("case", "Case"), ("dashPattern", "Dash"), ("widthPx", "Weight", "px")],
                rows,
            )
        ],
        notes=["Differentiates static, response-spectrum, and time-history curves visually."],
    )


@feature(
    "femCharts.markerStyles",
    "Marker Styles",
    part="fem",
    fields=[
        select(
            "marker",
            "Data point marker",
            [
                ("circle", "Circle"),
                ("square", "Square"),
                ("triangle", "Triangle"),
                ("diamond", "Diamond"),
            ],
            "circle",
        ),
        number("markerSizePx", "Marker diameter", 5.0, unit="px", min=1.0, max=16.0),
    ],
    requires_project=True,
)
def marker_styles(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set discrete data-point marker geometry for floor levels and station plots."""
    require_results(ctx)
    rows = [{"marker": values["marker"], "sizePx": values["markerSizePx"]}]
    return result(
        summary={"marker": values["marker"], "sizePx": values["markerSizePx"]},
        tables=[
            table(
                "Chart marker configuration", [("marker", "Shape"), ("sizePx", "Size", "px")], rows
            )
        ],
        notes=["Highlights discrete floor levels or member integration stations."],
    )


@feature(
    "femCharts.chartTitle",
    "Chart Title",
    part="fem",
    fields=[
        text("title", "Main title", "Structural Response Profile"),
        text("subtitle", "Subtitle", "Model Analysis Envelope"),
    ],
    requires_project=True,
)
def chart_title(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Attach title, subtitle, and project metadata footer to result charts."""
    out_dir, _ = require_results(ctx)
    manifest = load_manifest(out_dir)
    footer = f"Cases: {len(manifest.get('cases', []))} | Source: 08 FEM/model.results"
    rows = [
        {"field": "Title", "value": values["title"]},
        {"field": "Subtitle", "value": values["subtitle"]},
        {"field": "Footnote", "value": footer},
    ]
    return result(
        summary={"title": values["title"], "subtitle": values["subtitle"]},
        tables=[table("Chart title block", [("field", "Field"), ("value", "Text")], rows)],
        notes=["Provides traceable header metadata for exported figures."],
    )


@feature(
    "femCharts.backgroundStyle",
    "Background Style",
    part="fem",
    fields=[
        select(
            "theme",
            "Background theme",
            [
                ("light", "Clean White (#FFFFFF)"),
                ("slate", "Light Slate (#F8FAFC)"),
                ("dark", "Dark Canvas (#0F172A)"),
            ],
            "light",
        )
    ],
    requires_project=True,
)
def background_style(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure chart canvas background and border styling for screen or print export."""
    require_results(ctx)
    colors = {
        "light": ("#FFFFFF", "#E2E8F0"),
        "slate": ("#F8FAFC", "#CBD5E1"),
        "dark": ("#0F172A", "#334155"),
    }
    bg, border = colors[values["theme"]]
    rows = [{"theme": values["theme"], "backgroundHex": bg, "borderHex": border}]
    return result(
        summary={"theme": values["theme"], "backgroundHex": bg, "borderHex": border},
        tables=[
            table(
                "Canvas styling",
                [("theme", "Theme"), ("backgroundHex", "Background"), ("borderHex", "Border")],
                rows,
            )
        ],
        notes=["Light background is recommended for printed engineering calculation reports."],
    )

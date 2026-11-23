"""Analysis Charts - Envelopes tab: envelope creation, SRSS/linear/abs combination, governing case, and statistical envelopes."""

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
    select,
    table,
    text,
)
from saengine.features.fem_common import export_fem_file, require_results
from saengine.fem import result_tables, story_response


def _collect_member_series(
    ctx: FeatureContext, component: str = "M3"
) -> tuple[list[str], dict[str, dict[str, float]]]:
    """Return (case_labels, {member: {case_label: peak_val}}) from 08 FEM/model.results."""
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    cases = [
        e for e in idx.get("results", []) if any(t["id"] == "members" for t in e.get("tables", []))
    ]
    if not cases:
        raise FeatureInputError("No member force tables found in 08 FEM/model.results.")
    labels: list[str] = []
    matrix: dict[str, dict[str, float]] = {}
    for entry in cases[:10]:
        lbl = str(entry["label"])
        labels.append(lbl)
        tbl = result_tables.result_table(out_dir, model_path, entry["key"], "members")
        cols = [c["key"] for c in tbl.get("columns", [])]
        ci = cols.index(component) if component in cols else len(cols) - 1
        for row in tbl.get("rows", []):
            m = str(row[0])
            v = float(row[ci])
            cur = matrix.setdefault(m, {})
            if lbl not in cur or abs(v) > abs(cur[lbl]):
                cur[lbl] = v
    return labels, matrix


@feature(
    "femChartsEnvelopes.createEnvelope",
    "Create Envelope",
    part="fem",
    fields=[
        select(
            "component",
            "Force component",
            [("M3", "Major moment M3"), ("V2", "Major shear V2"), ("P", "Axial force P")],
            "M3",
        )
    ],
    requires_project=True,
)
def create_envelope(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build min/max envelope set across analyzed cases and combinations."""
    labels, mat = _collect_member_series(ctx, values["component"])
    rows = [
        {"member": m, "maxVal": max(d.values()), "minVal": min(d.values())}
        for m, d in list(mat.items())[:40]
    ]
    return result(
        summary={
            "component": values["component"],
            "casesIncluded": len(labels),
            "members": len(mat),
        },
        tables=[
            table(
                f"Created envelope ({values['component']})",
                [("member", "Member"), ("maxVal", "Max"), ("minVal", "Min")],
                rows,
            )
        ],
        notes=["Envelopes extreme values across all solved static and combination tables."],
    )


@feature(
    "femChartsEnvelopes.addCases",
    "Add Cases",
    part="fem",
    fields=[text("caseFilter", "Additional case filter", "")],
    requires_project=True,
)
def add_cases(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List and include matching cases/combinations into the active envelope set."""
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    filt = values["caseFilter"].strip().lower()
    matched = [
        r for r in idx.get("results", []) if not filt or filt in str(r.get("label", "")).lower()
    ]
    rows = [
        {"key": str(r["key"]), "label": str(r["label"]), "group": str(r["group"])} for r in matched
    ]
    return result(
        summary={"addedCases": len(rows)},
        tables=[
            table(
                "Envelope constituent cases",
                [("key", "Key"), ("label", "Label"), ("group", "Group")],
                rows,
            )
        ],
        notes=["All listed results contribute to envelope extrema."],
    )


@feature(
    "femChartsEnvelopes.extremaType",
    "Extrema Type",
    part="fem",
    fields=[
        select(
            "extrema",
            "Extrema mode",
            [("max", "Maximum positive"), ("min", "Minimum negative"), ("abs", "Absolute maximum")],
            "abs",
        ),
        select("component", "Component", [("M3", "M3"), ("V2", "V2"), ("P", "P")], "M3"),
    ],
    requires_project=True,
)
def extrema_type(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Extract maximum, minimum, or absolute-maximum envelope values per member."""
    _, mat = _collect_member_series(ctx, values["component"])
    mode = values["extrema"]
    rows = []
    for m, d in list(mat.items())[:40]:
        vals = list(d.values())
        val = (
            max(vals)
            if mode == "max"
            else (min(vals) if mode == "min" else max(abs(v) for v in vals))
        )
        rows.append({"member": m, "extremaVal": val})
    return result(
        summary={"mode": mode, "component": values["component"], "members": len(mat)},
        tables=[
            table(
                f"Envelope ({mode}) for {values['component']}",
                [("member", "Member"), ("extremaVal", "Extrema Value")],
                rows,
            )
        ],
        notes=["Filters envelope output by algebraic sign or absolute magnitude."],
    )


@feature(
    "femChartsEnvelopes.updateEnvelope",
    "Update Envelope",
    part="fem",
    fields=[],
    requires_project=True,
)
def update_envelope(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Recompute storey response envelopes after analysis result updates."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    cases = resp.get("cases", [])
    rows = []
    for c in cases[:20]:
        top = (c.get("levels") or [{}])[-1]
        rows.append(
            {
                "case": str(c.get("label", "")),
                "topUxMm": float(top.get("maxUxMm", 0.0)),
                "topUyMm": float(top.get("maxUyMm", 0.0)),
            }
        )
    return result(
        summary={"updatedCases": len(cases)},
        tables=[
            table(
                "Updated roof displacement summary",
                [("case", "Case"), ("topUxMm", "Top Ux", "mm"), ("topUyMm", "Top Uy", "mm")],
                rows,
            )
        ],
        notes=["Refreshed directly from 08 FEM/model.results."],
    )


@feature(
    "femChartsEnvelopes.linearAdd",
    "Linear Add",
    part="fem",
    fields=[
        number("factorA", "Scale factor A", 1.2),
        number("factorB", "Scale factor B", 1.6),
    ],
    requires_project=True,
)
def linear_add(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Combine first two solved static cases by algebraic linear superposition."""
    labels, mat = _collect_member_series(ctx, "M3")
    if len(labels) < 2:
        raise FeatureInputError("Need at least two solved member force cases to combine.")
    ca, cb = labels[0], labels[1]
    fa, fb = values["factorA"], values["factorB"]
    rows = [
        {
            "member": m,
            "valA": d.get(ca, 0.0),
            "valB": d.get(cb, 0.0),
            "combined": fa * d.get(ca, 0.0) + fb * d.get(cb, 0.0),
        }
        for m, d in list(mat.items())[:40]
    ]
    return result(
        summary={"caseA": ca, "caseB": cb, "members": len(rows)},
        tables=[
            table(
                f"Linear superposition ({fa:g}·{ca} + {fb:g}·{cb})",
                [
                    ("member", "Member"),
                    ("valA", "Case A"),
                    ("valB", "Case B"),
                    ("combined", "Combined"),
                ],
                rows,
            )
        ],
        notes=["Valid for linear elastic structural models."],
    )


@feature(
    "femChartsEnvelopes.srssCombine",
    "SRSS Combine",
    part="fem",
    fields=[],
    requires_project=True,
)
def srss_combine(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Combine member responses across cases by Square Root of Sum of Squares (SRSS)."""
    labels, mat = _collect_member_series(ctx, "M3")
    rows = [
        {"member": m, "srssM3": math.sqrt(sum(v**2 for v in d.values()))}
        for m, d in list(mat.items())[:40]
    ]
    return result(
        summary={"casesCombined": len(labels), "members": len(rows)},
        tables=[
            table(
                "SRSS combined M3 [kN·m]",
                [("member", "Member"), ("srssM3", "SRSS M3", "kN·m")],
                rows,
            )
        ],
        notes=["SRSS = √(Σ R_i²) across selected response cases."],
    )


@feature(
    "femChartsEnvelopes.absoluteMax",
    "Absolute Max",
    part="fem",
    fields=[],
    requires_project=True,
)
def absolute_max(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute absolute maximum |R| envelope across all solved cases."""
    labels, mat = _collect_member_series(ctx, "M3")
    rows = [
        {"member": m, "absMaxM3": max(abs(v) for v in d.values())}
        for m, d in list(mat.items())[:40]
    ]
    return result(
        summary={
            "cases": len(labels),
            "peakAbsM3Knm": max((r["absMaxM3"] for r in rows), default=0.0),
        },
        tables=[
            table(
                "Absolute maximum M3 envelope",
                [("member", "Member"), ("absMaxM3", "|M3|max", "kN·m")],
                rows,
            )
        ],
        notes=["Conservative upper bound taking max |R_i| per member."],
    )


@feature(
    "femChartsEnvelopes.scaleFactor",
    "Scale Factor",
    part="fem",
    fields=[number("scale", "Uniform multiplier", 1.15, min=-10.0, max=10.0)],
    requires_project=True,
)
def scale_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply a uniform scale factor to member force envelope values."""
    _, mat = _collect_member_series(ctx, "M3")
    sf = values["scale"]
    rows = [
        {"member": m, "unscaledMax": max(d.values()), "scaledMax": max(d.values()) * sf}
        for m, d in list(mat.items())[:40]
    ]
    return result(
        summary={"scaleFactor": sf, "membersScaled": len(rows)},
        tables=[
            table(
                f"Scaled envelope (× {sf:g})",
                [("member", "Member"), ("unscaledMax", "Unscaled"), ("scaledMax", "Scaled")],
                rows,
            )
        ],
        notes=["Linearly scales envelope responses by user multiplier."],
    )


@feature(
    "femChartsEnvelopes.envelopePlot",
    "Envelope Plot",
    part="fem",
    fields=[],
    requires_project=True,
)
def envelope_plot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate min/max storey displacement envelope curves with governing cases."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    cases = resp.get("cases", [])
    if not cases:
        raise FeatureInputError("Run the analysis first.")
    by_level: dict[str, dict[str, Any]] = {}
    for c in cases:
        for lv in c.get("levels", []):
            nm = str(lv.get("name", ""))
            ux = float(lv.get("maxUxMm", 0.0))
            rec = by_level.setdefault(
                nm,
                {
                    "level": nm,
                    "elevM": float(lv.get("z", 0.0)),
                    "maxUxMm": ux,
                    "govCase": str(c.get("label", "")),
                },
            )
            if abs(ux) > abs(rec["maxUxMm"]):
                rec["maxUxMm"] = ux
                rec["govCase"] = str(c.get("label", ""))
    rows = sorted(by_level.values(), key=lambda r: r["elevM"])
    return result(
        summary={"levels": len(rows), "casesEvaluated": len(cases)},
        tables=[
            table(
                "Storey displacement envelope plot",
                [
                    ("level", "Level"),
                    ("elevM", "Elevation", "m"),
                    ("maxUxMm", "Extreme Ux", "mm"),
                    ("govCase", "Governing"),
                ],
                rows,
            )
        ],
        notes=["Highlights governing load case at each floor elevation."],
    )


@feature(
    "femChartsEnvelopes.governingCase",
    "Governing Case",
    part="fem",
    fields=[select("component", "Component", [("M3", "M3"), ("V2", "V2"), ("P", "P")], "M3")],
    requires_project=True,
)
def governing_case(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Identify the governing load case producing peak absolute demand per member."""
    _, mat = _collect_member_series(ctx, values["component"])
    rows = []
    for m, d in list(mat.items())[:40]:
        gov_k = max(d, key=lambda k: abs(d[k]))
        rows.append({"member": m, "governingCase": gov_k, "value": d[gov_k]})
    return result(
        summary={"component": values["component"], "members": len(rows)},
        tables=[
            table(
                f"Governing load case per member ({values['component']})",
                [
                    ("member", "Member"),
                    ("governingCase", "Governing Case"),
                    ("value", "Peak Value"),
                ],
                rows,
            )
        ],
        notes=["Maps each member to the case causing its largest absolute demand."],
    )


@feature(
    "femChartsEnvelopes.jumpToCase",
    "Jump To Case",
    part="fem",
    fields=[text("memberId", "Member ID (blank = overall governing)", "")],
    requires_project=True,
)
def jump_to_case(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Locate the governing case and full station forces for a target member."""
    _, mat = _collect_member_series(ctx, "M3")
    mid = values["memberId"].strip()
    target = mid if mid in mat else next(iter(mat))
    d = mat[target]
    gov = max(d, key=lambda k: abs(d[k]))
    rows = [{"case": k, "m3Knm": v, "governing": k == gov} for k, v in d.items()]
    return result(
        summary={"member": target, "governingCase": gov, "peakM3Knm": d[gov]},
        tables=[
            table(
                f"Case breakdown for {target}",
                [("case", "Case"), ("m3Knm", "M3", "kN·m"), ("governing", "Governing")],
                rows,
            )
        ],
        notes=["Allows immediate drill-down into the controlling analysis case."],
    )


@feature(
    "femChartsEnvelopes.exportEnvelope",
    "Export Envelope",
    part="fem",
    fields=[text("filename", "CSV filename", "force-envelope.csv")],
    requires_project=True,
)
def export_envelope(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export member force envelopes to CSV inside 08 FEM/exports/."""
    _, mat = _collect_member_series(ctx, "M3")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["member", "maxM3_kNm", "minM3_kNm", "governing"])
    rows = []
    for m, d in mat.items():
        gov = max(d, key=lambda k: abs(d[k]))
        r = {"member": m, "maxM3": max(d.values()), "minM3": min(d.values()), "gov": gov}
        rows.append(r)
        w.writerow([m, r["maxM3"], r["minM3"], gov])
    path = export_fem_file(ctx, values["filename"].strip() or "force-envelope.csv", buf.getvalue())
    return result(
        summary={"membersExported": len(rows), "exportPath": str(path)},
        tables=[
            table(
                "Exported member envelope",
                [
                    ("member", "Member"),
                    ("maxM3", "Max M3", "kN·m"),
                    ("minM3", "Min M3", "kN·m"),
                    ("gov", "Governing"),
                ],
                rows[:30],
            )
        ],
        notes=[f"Envelope table written to {path}"],
    )


@feature(
    "femChartsEnvelopes.filterComponents",
    "Filter Components",
    part="fem",
    fields=[
        select(
            "component",
            "Force component",
            [
                ("P", "Axial P"),
                ("V2", "Shear V2"),
                ("V3", "Shear V3"),
                ("T", "Torsion T"),
                ("M2", "Minor M2"),
                ("M3", "Major M3"),
            ],
            "V2",
        )
    ],
    requires_project=True,
)
def filter_components(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Filter member envelope output to a single internal force/moment component."""
    _, mat = _collect_member_series(ctx, values["component"])
    rows = [
        {"member": m, "maxVal": max(d.values()), "minVal": min(d.values())}
        for m, d in list(mat.items())[:40]
    ]
    return result(
        summary={"component": values["component"], "members": len(rows)},
        tables=[
            table(
                f"Filtered component envelope: {values['component']}",
                [("member", "Member"), ("maxVal", "Max"), ("minVal", "Min")],
                rows,
            )
        ],
        notes=["Isolates a single stress resultant across all analyzed combinations."],
    )


@feature(
    "femChartsEnvelopes.nodeFilter",
    "Node Filter",
    part="fem",
    fields=[number("minElevM", "Minimum elevation filter", 0.0, unit="m")],
    requires_project=True,
)
def node_filter(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Restrict storey displacement envelope to levels at or above a target elevation."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    z_min = values["minElevM"]
    rows = []
    for c in resp.get("cases", [])[:8]:
        for lv in c.get("levels", []):
            if float(lv.get("z", 0.0)) >= z_min:
                rows.append(
                    {
                        "case": str(c.get("label", "")),
                        "level": str(lv.get("name", "")),
                        "elevM": float(lv.get("z", 0.0)),
                        "uxMm": float(lv.get("maxUxMm", 0.0)),
                    }
                )
    return result(
        summary={"minElevM": z_min, "filteredRows": len(rows)},
        tables=[
            table(
                f"Nodal envelope above z = {z_min:g} m",
                [
                    ("case", "Case"),
                    ("level", "Level"),
                    ("elevM", "Elev", "m"),
                    ("uxMm", "Ux", "mm"),
                ],
                rows[:40],
            )
        ],
        notes=["Filters nodal displacement envelope results by elevation band."],
    )


@feature(
    "femChartsEnvelopes.thresholdFilter",
    "Threshold Filter",
    part="fem",
    fields=[number("minMagnitude", "Minimum absolute M3 threshold", 10.0, unit="kN·m", min=0.0)],
    requires_project=True,
)
def threshold_filter(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Exclude envelope members whose peak absolute demand falls below the threshold."""
    _, mat = _collect_member_series(ctx, "M3")
    thr = values["minMagnitude"]
    rows = [
        {"member": m, "peakAbsM3": max(abs(v) for v in d.values())}
        for m, d in mat.items()
        if max(abs(v) for v in d.values()) >= thr
    ]
    return result(
        summary={"thresholdKnm": thr, "passingFilter": len(rows), "totalMembers": len(mat)},
        tables=[
            table(
                f"Members with |M3| >= {thr:g} kN·m",
                [("member", "Member"), ("peakAbsM3", "|M3|max", "kN·m")],
                rows[:40] or [{"member": "None", "peakAbsM3": 0.0}],
            )
        ],
        notes=["Suppresses lightly loaded secondary members from envelope review."],
    )


@feature(
    "femChartsEnvelopes.memberSelector",
    "Member Selector",
    part="fem",
    fields=[text("prefix", "Member ID prefix (e.g. C or B)", "")],
    requires_project=True,
)
def member_selector(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Focus envelope computation on a selected member subset (columns, beams, braces)."""
    _, mat = _collect_member_series(ctx, "M3")
    pref = values["prefix"].strip().upper()
    rows = [
        {"member": m, "maxM3": max(d.values()), "minM3": min(d.values())}
        for m, d in mat.items()
        if not pref or m.upper().startswith(pref)
    ]
    return result(
        summary={"prefix": pref or "ALL", "selectedMembers": len(rows)},
        tables=[
            table(
                "Selected member envelope",
                [("member", "Member"), ("maxM3", "Max M3", "kN·m"), ("minM3", "Min M3", "kN·m")],
                rows[:40],
            )
        ],
        notes=["Subsets member force envelopes by structural group prefix."],
    )


@feature(
    "femChartsEnvelopes.percentileEnvelope",
    "Percentile Envelope",
    part="fem",
    fields=[number("percentile", "Target percentile", 90.0, unit="%", min=1.0, max=99.9)],
    requires_project=True,
)
def percentile_envelope(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute statistical percentile of peak absolute member demands across combinations."""
    _, mat = _collect_member_series(ctx, "M3")
    q = values["percentile"]
    rows = [
        {"member": m, "percentileVal": float(np.percentile([abs(v) for v in d.values()], q))}
        for m, d in list(mat.items())[:40]
    ]
    return result(
        summary={"percentile": q, "members": len(rows)},
        tables=[
            table(
                f"{q:g}th percentile |M3| envelope",
                [("member", "Member"), ("percentileVal", "Percentile |M3|", "kN·m")],
                rows,
            )
        ],
        notes=["Useful for evaluating typical vs outlier combination demands."],
    )


@feature(
    "femChartsEnvelopes.standardDeviation",
    "Standard Deviation",
    part="fem",
    fields=[],
    requires_project=True,
)
def standard_deviation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute mean and sample standard deviation of member forces across load cases."""
    _, mat = _collect_member_series(ctx, "M3")
    rows = []
    for m, d in list(mat.items())[:40]:
        arr = np.array(list(d.values()), dtype=float)
        rows.append(
            {
                "member": m,
                "meanKnm": float(arr.mean()),
                "stdDevKnm": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
            }
        )
    return result(
        summary={"members": len(rows)},
        tables=[
            table(
                "Member demand dispersion (mean ± σ)",
                [
                    ("member", "Member"),
                    ("meanKnm", "Mean", "kN·m"),
                    ("stdDevKnm", "Std Dev σ", "kN·m"),
                ],
                rows,
            )
        ],
        notes=["High standard deviation indicates sensitivity to lateral/variable load reversals."],
    )


@feature(
    "femChartsEnvelopes.meanResponse",
    "Mean Response",
    part="fem",
    fields=[],
    requires_project=True,
)
def mean_response(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute arithmetic mean response across all analyzed load cases per member."""
    _, mat = _collect_member_series(ctx, "M3")
    rows = [
        {
            "member": m,
            "meanM3Knm": float(np.mean(list(d.values()))),
            "meanAbsM3Knm": float(np.mean([abs(v) for v in d.values()])),
        }
        for m, d in list(mat.items())[:40]
    ]
    return result(
        summary={"members": len(rows)},
        tables=[
            table(
                "Mean member moment response",
                [
                    ("member", "Member"),
                    ("meanM3Knm", "Mean M3", "kN·m"),
                    ("meanAbsM3Knm", "Mean |M3|", "kN·m"),
                ],
                rows,
            )
        ],
        notes=["Evaluated across all member-force result sets in 08 FEM/model.results."],
    )


@feature(
    "femChartsEnvelopes.compareEnvelopes",
    "Compare Envelopes",
    part="fem",
    fields=[],
    requires_project=True,
)
def compare_envelopes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Overlay M3 and V2 absolute envelopes across structural members."""
    _, mat_m = _collect_member_series(ctx, "M3")
    _, mat_v = _collect_member_series(ctx, "V2")
    rows = [
        {
            "member": m,
            "absMaxM3Knm": max(abs(v) for v in mat_m[m].values()),
            "absMaxV2Kn": max(abs(v) for v in mat_v.get(m, {0: 0.0}).values()),
        }
        for m in list(mat_m.keys())[:40]
    ]
    return result(
        summary={"membersCompared": len(rows)},
        tables=[
            table(
                "Bending vs shear envelope comparison",
                [
                    ("member", "Member"),
                    ("absMaxM3Knm", "|M3|max", "kN·m"),
                    ("absMaxV2Kn", "|V2|max", "kN"),
                ],
                rows,
            )
        ],
        notes=["Side-by-side comparison of flexural and shear governing envelopes."],
    )


@feature(
    "femChartsEnvelopes.envelopeDifference",
    "Envelope Difference",
    part="fem",
    fields=[],
    requires_project=True,
)
def envelope_difference(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute positive-to-negative envelope range (span = max - min) per member."""
    _, mat = _collect_member_series(ctx, "M3")
    rows = [
        {
            "member": m,
            "maxM3": max(d.values()),
            "minM3": min(d.values()),
            "rangeKnm": max(d.values()) - min(d.values()),
        }
        for m, d in list(mat.items())[:40]
    ]
    return result(
        summary={
            "members": len(rows),
            "maxRangeKnm": max((r["rangeKnm"] for r in rows), default=0.0),
        },
        tables=[
            table(
                "Envelope reversal range (Max - Min)",
                [
                    ("member", "Member"),
                    ("maxM3", "Max", "kN·m"),
                    ("minM3", "Min", "kN·m"),
                    ("rangeKnm", "Range", "kN·m"),
                ],
                rows,
            )
        ],
        notes=[
            "Large reversal range flags members subject to cyclic wind/seismic stress reversals."
        ],
    )

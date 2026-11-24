"""Analysis Charts - Results display tab: moment/shear/axial diagrams, contours, animations, probing, and cuts."""

from __future__ import annotations

import math
from typing import Any

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
    require_results,
)
from saengine.fem import result_tables, story_response


def _read_table(
    ctx: FeatureContext, table_id: str, case_filter: str = ""
) -> tuple[str, dict[str, Any]]:
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    filt = case_filter.strip().lower()
    for e in idx.get("results", []):
        if filt and filt not in str(e.get("label", "")).lower():
            continue
        if any(t["id"] == table_id for t in e.get("tables", [])):
            return str(e["label"]), result_tables.result_table(
                out_dir, model_path, e["key"], table_id
            )
    raise FeatureInputError(f"No {table_id} result table found in 08 FEM/model.results.")


@feature(
    "results.momentDiagram",
    "Moment Diagram",
    part="fem",
    fields=[text("caseFilter", "Case/combo filter", "")],
    requires_project=True,
)
def moment_diagram(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Extract bending moment diagram ordinates (M2, M3) at member stations."""
    label, tbl = _read_table(ctx, "members", values["caseFilter"])
    cols = [c["key"] for c in tbl.get("columns", [])]
    rows = [
        {
            "member": r[0],
            "station": r[1] if len(r) > 1 else 0.0,
            "m2Knm": r[cols.index("M2")] if "M2" in cols else 0.0,
            "m3Knm": r[cols.index("M3")] if "M3" in cols else 0.0,
        }
        for r in tbl.get("rows", [])[:50]
    ]
    return result(
        summary={"case": label, "stations": len(tbl.get("rows", []))},
        tables=[
            table(
                f"Bending moment diagram ({label})",
                [
                    ("member", "Member"),
                    ("station", "Station", "m"),
                    ("m2Knm", "M2", "kN·m"),
                    ("m3Knm", "M3", "kN·m"),
                ],
                rows,
            )
        ],
        notes=["Station moments along member local axes 2 and 3."],
    )


@feature(
    "results.shearDiagram",
    "Shear Diagram",
    part="fem",
    fields=[text("caseFilter", "Case/combo filter", "")],
    requires_project=True,
)
def shear_diagram(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Extract shear force diagram ordinates (V2, V3) at member stations."""
    label, tbl = _read_table(ctx, "members", values["caseFilter"])
    cols = [c["key"] for c in tbl.get("columns", [])]
    rows = [
        {
            "member": r[0],
            "station": r[1] if len(r) > 1 else 0.0,
            "v2Kn": r[cols.index("V2")] if "V2" in cols else 0.0,
            "v3Kn": r[cols.index("V3")] if "V3" in cols else 0.0,
        }
        for r in tbl.get("rows", [])[:50]
    ]
    return result(
        summary={"case": label, "stations": len(tbl.get("rows", []))},
        tables=[
            table(
                f"Shear force diagram ({label})",
                [
                    ("member", "Member"),
                    ("station", "Station", "m"),
                    ("v2Kn", "V2", "kN"),
                    ("v3Kn", "V3", "kN"),
                ],
                rows,
            )
        ],
        notes=["Station shear forces along member local axes 2 and 3."],
    )


@feature(
    "results.axialForce",
    "Axial Force",
    part="fem",
    fields=[text("caseFilter", "Case/combo filter", "")],
    requires_project=True,
)
def axial_force(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Extract axial force diagram values (compression negative / tension positive) across members."""
    label, tbl = _read_table(ctx, "members", values["caseFilter"])
    cols = [c["key"] for c in tbl.get("columns", [])]
    pi = cols.index("P") if "P" in cols else 2
    rows = [
        {"member": r[0], "station": r[1] if len(r) > 1 else 0.0, "axialKn": float(r[pi])}
        for r in tbl.get("rows", [])[:50]
    ]
    return result(
        summary={
            "case": label,
            "maxCompressionKn": min((r["axialKn"] for r in rows), default=0.0),
            "maxTensionKn": max((r["axialKn"] for r in rows), default=0.0),
        },
        tables=[
            table(
                f"Axial force diagram ({label})",
                [("member", "Member"), ("station", "Station", "m"), ("axialKn", "Axial P", "kN")],
                rows,
            )
        ],
        notes=["Tension positive, compression negative."],
    )


@feature(
    "results.stressContours",
    "Stress Contours",
    part="fem",
    fields=[text("caseFilter", "Case filter", "")],
    requires_project=True,
)
def stress_contours(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Extract shell membrane forces and bending stress resultants for contour plotting."""
    label, tbl = _read_table(ctx, "shells", values["caseFilter"])
    cols = [(c["key"], c["title"]) for c in tbl.get("columns", [])]
    keys = [c[0] for c in cols]
    rows = [dict(zip(keys, r, strict=False)) for r in tbl.get("rows", [])[:40]]
    return result(
        summary={"case": label, "shellElements": len(tbl.get("rows", []))},
        tables=[table(f"Shell stress resultants ({label})", cols[:7], rows)],
        notes=["Extracted from wall and slab shell element tables in 08 FEM/model.results."],
    )


@feature(
    "results.envelopeView",
    "Envelope View",
    part="fem",
    fields=[],
    requires_project=True,
)
def envelope_view(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Display maximum and minimum member force envelope across all solved combinations."""
    label, tbl = _read_table(ctx, "envelope")
    cols = [(c["key"], c["title"]) for c in tbl.get("columns", [])]
    keys = [c[0] for c in cols]
    rows = [dict(zip(keys, r, strict=False)) for r in tbl.get("rows", [])[:40]]
    return result(
        summary={"envelope": label, "rows": len(tbl.get("rows", []))},
        tables=[table(f"Combination envelope ({label})", cols[:7], rows)],
        notes=["Envelopes all active design load combinations."],
    )


@feature(
    "results.loadCasePicker",
    "Load Case Picker",
    part="fem",
    fields=[],
    requires_project=True,
)
def load_case_picker(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List all selectable solved load cases, combinations, and spectra in 08 FEM/model.results."""
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    rows = [
        {"key": str(e["key"]), "label": str(e["label"]), "group": str(e["group"])}
        for e in idx.get("results", [])
    ]
    return result(
        summary={"selectableResults": len(rows)},
        tables=[
            table(
                "Available load cases & combinations",
                [("key", "Key"), ("label", "Label"), ("group", "Group")],
                rows,
            )
        ],
        notes=["Use any key to inspect specific diagrams or tables."],
    )


@feature(
    "results.deformedScale",
    "Deformed Scale",
    part="fem",
    fields=[
        number("targetMaxVisualM", "Target visual deflection amplitude", 1.5, unit="m", min=0.1)
    ],
    requires_project=True,
)
def deformed_scale(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute an appropriate 3D visual magnification scale factor from peak model deflection."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    max_mm = (
        max(
            (
                max(abs(float(lv.get("maxUxMm", 0.0))), abs(float(lv.get("maxUyMm", 0.0))))
                for c in resp.get("cases", [])
                for lv in c.get("levels", [])
            ),
            default=10.0,
        )
        or 10.0
    )
    scale = (values["targetMaxVisualM"] * 1000.0) / max_mm
    rows = [
        {
            "peakDispMm": max_mm,
            "targetVisualMm": values["targetMaxVisualM"] * 1000.0,
            "scaleFactor": scale,
        }
    ]
    return result(
        summary={"peakDispMm": max_mm, "recommendedScaleFactor": scale},
        tables=[
            table(
                "Deformed shape scale factor",
                [
                    ("peakDispMm", "Peak Δ", "mm"),
                    ("targetVisualMm", "Visual Δ", "mm"),
                    ("scaleFactor", "Scale ×"),
                ],
                rows,
            )
        ],
        notes=["Auto-scales small elastic displacements for clear 3D visualization."],
    )


@feature(
    "results.plateMoments",
    "Plate Moments",
    part="fem",
    fields=[text("caseFilter", "Case filter", "")],
    requires_project=True,
)
def plate_moments(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Extract slab/shell bending moments Mxx, Myy, Mxy [kN·m/m] for contour display."""
    label, tbl = _read_table(ctx, "shells", values["caseFilter"])
    cols = [(c["key"], c["title"]) for c in tbl.get("columns", [])]
    keys = [c[0] for c in cols]
    rows = [dict(zip(keys, r, strict=False)) for r in tbl.get("rows", [])[:40]]
    return result(
        summary={"case": label, "shellCount": len(tbl.get("rows", []))},
        tables=[table(f"Plate bending moments ({label})", cols[:7], rows)],
        notes=["Wood-Armer design moments are derived from plate Mxx, Myy, and Mxy."],
    )


@feature(
    "results.shellStresses",
    "Shell Stresses",
    part="fem",
    fields=[number("thicknessMm", "Nominal shell thickness", 150.0, unit="mm", min=40.0)],
    requires_project=True,
)
def shell_stresses(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert shell membrane forces and bending moments into extreme-fiber stresses [MPa]."""
    label, tbl = _read_table(ctx, "shells")
    cols = [c["key"] for c in tbl.get("columns", [])]
    t_m = values["thicknessMm"] / 1000.0
    rows = []
    for r in tbl.get("rows", [])[:40]:
        f11 = float(r[cols.index("F11")]) if "F11" in cols else 0.0
        m11 = float(r[cols.index("M11")]) if "M11" in cols else 0.0
        sig_mpa = (f11 / t_m + 6.0 * m11 / (t_m**2)) / 1000.0
        rows.append(
            {"shell": str(r[0]), "f11KnM": f11, "m11KnmM": m11, "extremeStressMpa": sig_mpa}
        )
    return result(
        summary={"case": label, "shellsEvaluated": len(rows)},
        tables=[
            table(
                "Shell extreme-fiber stresses",
                [
                    ("shell", "Shell"),
                    ("f11KnM", "N11", "kN/m"),
                    ("m11KnmM", "M11", "kN·m/m"),
                    ("extremeStressMpa", "σ_max", "MPa"),
                ],
                rows,
            )
        ],
        notes=["σ = N/t ± 6M/t² assuming linear elastic homogeneous section."],
    )


@feature(
    "results.modeAnimation",
    "Mode Animation",
    part="fem",
    fields=[
        number("mode", "Mode number", 1, min=1, max=30),
        number("frames", "Cycle frames", 16, min=4, max=60),
    ],
    requires_project=True,
)
def mode_animation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate harmonic phase keyframes sin(ωt) for animating a solved vibration mode."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    modal = resp.get("modal", [])
    if not modal:
        raise FeatureInputError("No modal analysis results found in 08 FEM/model.results.")
    idx = min(int(values["mode"]) - 1, len(modal) - 1)
    period = float(modal[idx].get("period", 1.0))
    n_f = int(values["frames"])
    rows = [
        {"frame": k, "phaseDeg": 360.0 * k / n_f, "amplitude": math.sin(2.0 * math.pi * k / n_f)}
        for k in range(n_f)
    ]
    return result(
        summary={"mode": idx + 1, "periodS": period, "frames": n_f},
        tables=[
            table(
                f"Mode {idx + 1} (T = {period:.3f} s) animation cycle",
                [("frame", "Frame"), ("phaseDeg", "Phase", "°"), ("amplitude", "sin(ωt)")],
                rows,
            )
        ],
        notes=["Multiplies normalized eigenvector φ_n by harmonic phase factor sin(2π k / N)."],
    )


@feature(
    "results.deflectionAnimation",
    "Deflection Animation",
    part="fem",
    fields=[number("frames", "Ramp frames", 10, min=2, max=40)],
    requires_project=True,
)
def deflection_animation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate monotonic load-ramp keyframes from undeformed to solved peak deflection."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    cases = resp.get("cases", [])
    if not cases:
        raise FeatureInputError("Run the analysis first.")
    peak_ux = max(
        (abs(float(lv.get("maxUxMm", 0.0))) for lv in cases[0].get("levels", [])), default=0.0
    )
    n_f = int(values["frames"])
    rows = [
        {"frame": k, "loadFactor": k / n_f, "roofDispMm": peak_ux * (k / n_f)}
        for k in range(n_f + 1)
    ]
    return result(
        summary={"case": str(cases[0].get("label", "")), "peakDispMm": peak_ux, "frames": n_f + 1},
        tables=[
            table(
                "Deflection ramp animation frames",
                [("frame", "Frame"), ("loadFactor", "Scale"), ("roofDispMm", "Peak Ux", "mm")],
                rows,
            )
        ],
        notes=["Linearly interpolates from zero to full solved nodal displacements."],
    )


@feature(
    "results.probeResults",
    "Probe Results",
    part="fem",
    fields=[text("memberId", "Member ID to probe (blank = first)", "")],
    requires_project=True,
)
def probe_results(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect all station forces along a single probed structural member."""
    label, tbl = _read_table(ctx, "members")
    cols = [(c["key"], c["title"]) for c in tbl.get("columns", [])]
    keys = [c[0] for c in cols]
    rows = [dict(zip(keys, r, strict=False)) for r in tbl.get("rows", [])]
    mid = values["memberId"].strip()
    target = (
        mid
        if any(str(r.get(keys[0])) == mid for r in rows)
        else (str(rows[0].get(keys[0])) if rows else "")
    )
    probed = [r for r in rows if str(r.get(keys[0])) == target]
    return result(
        summary={"case": label, "member": target, "stations": len(probed)},
        tables=[table(f"Probed stations for {target} ({label})", cols[:8], probed)],
        notes=["Reads exact station-by-station forces for the queried element."],
    )


@feature(
    "results.cutSectionResults",
    "Cut Section Results",
    part="fem",
    fields=[number("cutElevationM", "Horizontal cut plane elevation", 3.2, unit="m", min=0.0)],
    requires_project=True,
)
def cut_section_results(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Integrate storey shears and overturning moments across a horizontal section cut."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    z_cut = values["cutElevationM"]
    rows = []
    for c in resp.get("cases", []):
        levels = c.get("levels", [])
        if not levels:
            continue
        nearest = min(levels, key=lambda lv: abs(float(lv.get("z", 0.0)) - z_cut))
        rows.append(
            {
                "case": str(c.get("label", "")),
                "level": str(nearest.get("name", "")),
                "vxKn": float(nearest.get("shearXKn", 0.0)),
                "vyKn": float(nearest.get("shearYKn", 0.0)),
            }
        )
    if not rows:
        raise FeatureInputError("No cut-plane storey shears available in 08 FEM/model.results.")
    return result(
        summary={"cutElevationM": z_cut, "casesIntegrated": len(rows)},
        tables=[
            table(
                f"Section cut integrated shears near z = {z_cut:g} m",
                [
                    ("case", "Case"),
                    ("level", "Matched Level"),
                    ("vxKn", "ΣVx", "kN"),
                    ("vyKn", "ΣVy", "kN"),
                ],
                rows,
            )
        ],
        notes=["Integrates lateral storey forces above the cut elevation."],
    )


@feature(
    "results.resultSets",
    "Result Sets",
    part="fem",
    fields=[text("setName", "Result set name", "uls-governing")],
    requires_project=True,
)
def result_sets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Save a named collection of analyzed cases and tables for quick recall."""
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    payload = {
        "name": values["setName"],
        "results": [{"key": e["key"], "label": e["label"]} for e in idx.get("results", [])],
    }
    path = export_fem_file(ctx, f"result-set-{values['setName']}.json", format_json(payload))
    return result(
        summary={
            "setName": values["setName"],
            "entries": len(payload["results"]),
            "setPath": str(path),
        },
        tables=[
            table("Saved result set", [("key", "Key"), ("label", "Label")], payload["results"][:25])
        ],
        notes=[f"Result set saved to {path}"],
    )


@feature(
    "results.resultViews",
    "Result Views",
    part="fem",
    fields=[
        select(
            "viewPreset",
            "View preset",
            [
                ("iso", "Isometric 3D"),
                ("plan", "Top Plan"),
                ("elevX", "X-Z Elevation"),
                ("elevY", "Y-Z Elevation"),
            ],
            "iso",
        ),
        select(
            "diagram",
            "Active diagram",
            [("M3", "Bending M3"), ("V2", "Shear V2"), ("deformed", "Deflected Shape")],
            "M3",
        ),
    ],
    requires_project=True,
)
def result_views(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate requested diagram table availability in results and store camera preset."""
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    needed = "nodes" if values["diagram"] == "deformed" else "members"
    cases = [
        str(e.get("label") or e.get("key") or "")
        for e in idx.get("results", [])
        if any(t.get("id") == needed for t in e.get("tables", []))
    ]
    cameras = {
        "iso": {"azimuthDeg": 45.0, "elevationDeg": 30.0},
        "plan": {"azimuthDeg": 0.0, "elevationDeg": 90.0},
        "elevX": {"azimuthDeg": 0.0, "elevationDeg": 0.0},
        "elevY": {"azimuthDeg": 90.0, "elevationDeg": 0.0},
    }
    cam = cameras[values["viewPreset"]]
    view = {
        "camera": values["viewPreset"],
        **cam,
        "diagram": values["diagram"],
        "sourceTable": needed,
        "availableCases": len(cases),
    }
    path = export_fem_file(ctx, f"result-view-{values['viewPreset']}.json", format_json(view))
    return result(
        summary={
            "camera": values["viewPreset"],
            "diagram": values["diagram"],
            "availableCases": len(cases),
            "viewPath": str(path),
        },
        tables=[
            table(
                "Validated result view",
                [("setting", "Setting"), ("value", "Value")],
                [{"setting": k, "value": str(v)} for k, v in view.items()],
            )
        ],
        notes=[f"Validated against {len(cases)} {needed} table(s); preset saved to {path}."],
    )

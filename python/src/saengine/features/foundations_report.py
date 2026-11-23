"""Substructure - Reports & Deliverables tab: audits, CAD exports, calculation reports & QA sheets."""

from __future__ import annotations

import datetime as dt
import io
import json
import math
from typing import Any

import ezdxf

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
from saengine.features.foundations_common import (
    export_bytes,
    export_file,
    load_substructure_context,
    load_substructure_model,
    require_root,
)
from saengine.report.clauses import in_force
from saengine.soil import bearing as soil_bearing
from saengine.soil import settlement as soil_settlement
from saengine.soil.profile import Profile
from saengine.substructure import excavation, piles, retaining_walls
from saengine.substructure import report as sub_report


@feature(
    "foundationsReport.excavationReport",
    "Excavation Report",
    part="substructure",
    fields=[],
    requires_project=True,
)
def excavation_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile excavation depths, side-slope checks, dewatering, and formwork notes to Markdown."""
    sub_ctx = load_substructure_context(ctx)
    with in_force(ctx.root):
        exc_list, exc_notes = excavation.design_excavations(sub_ctx)
        fill_n = excavation.fill_notes(sub_ctx)
        wp_n = excavation.waterproofing_notes(sub_ctx)
    lines = [
        "# Substructure Excavation & Dewatering Report",
        "",
        f"- Excavations checked: {len(exc_list)}",
        "",
        "## Notes & Requirements",
        *(
            [f"- {n}" for n in (exc_notes + fill_n + wp_n)]
            or ["- No excavation records defined in 09 Substructure."]
        ),
    ]
    out_path = export_file(ctx, "excavation-report.md", "\n".join(lines) + "\n")
    rows = [
        {
            "id": e.get("id", "-"),
            "depthMm": e.get("depth", 0.0),
            "support": e.get("support", "-"),
            "ok": e.get("ok", True),
        }
        for e in exc_list
    ]
    return result(
        summary={"excavationCount": len(exc_list), "reportPath": str(out_path)},
        tables=[
            table(
                "Excavation checks",
                [("id", "ID"), ("depthMm", "Depth", "mm"), ("support", "Support"), ("ok", "OK")],
                rows or [{"id": "-", "depthMm": 0.0, "support": "None defined", "ok": True}],
            )
        ],
        notes=[f"Report written to {out_path}"],
    )


@feature(
    "foundationsReport.pileReport",
    "Pile Report",
    part="substructure",
    fields=[],
    requires_project=True,
)
def pile_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile project pile types, capacities across boreholes, and load test summaries."""
    sub = load_substructure_model(ctx)
    soil_rep = ctx.soil()
    rows = []
    if soil_rep is not None and soil_rep.boreholes and sub.pileTypes:
        with in_force(ctx.root):
            prof = Profile(soil_rep, soil_rep.boreholes[0])
            for pt in sub.pileTypes:
                sp = piles.single_pile(
                    prof,
                    pt.kind,
                    pt.diameter / 1000.0,
                    pt.length / 1000.0,
                    1.5,
                    method=sub.design.pileCapacity,
                )
                rows.append(
                    {
                        "id": pt.id,
                        "kind": pt.kind,
                        "diaMm": pt.diameter,
                        "lenM": pt.length / 1000.0,
                        "qaKn": sp["Qa"],
                        "taKn": sp["Ta"],
                    }
                )
    lines = [
        "# Substructure Pile Capacity Report",
        "",
        f"- Pile types defined: {len(sub.pileTypes)}",
        f"- Placed piles: {len(sub.piles)}",
        f"- Load tests recorded: {len(sub.loadTests)}",
    ]
    for r in rows:
        lines.append(
            f"- {r['id']} ({r['kind']} Ø{r['diaMm']:g} × {r['lenM']:g} m): Qa = {r['qaKn']:.1f} kN, Ta = {r['taKn']:.1f} kN"
        )
    out_path = export_file(ctx, "pile-report.md", "\n".join(lines) + "\n")
    return result(
        summary={
            "pileTypes": len(sub.pileTypes),
            "placedPiles": len(sub.piles),
            "reportPath": str(out_path),
        },
        tables=[
            table(
                "Project pile types & capacities",
                [
                    ("id", "ID"),
                    ("kind", "Kind"),
                    ("diaMm", "D", "mm"),
                    ("lenM", "L", "m"),
                    ("qaKn", "Qa", "kN"),
                    ("taKn", "Ta", "kN"),
                ],
                rows
                or [
                    {
                        "id": "-",
                        "kind": "None defined",
                        "diaMm": 0.0,
                        "lenM": 0.0,
                        "qaKn": 0.0,
                        "taKn": 0.0,
                    }
                ],
            )
        ],
        notes=[f"Pile report written to {out_path}"],
    )


@feature(
    "foundationsReport.retainingReport",
    "Retaining Report",
    part="substructure",
    fields=[],
    requires_project=True,
)
def retaining_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Run retaining wall stability and RC design checks and publish report to 09 Substructure/exports."""
    sub_ctx = load_substructure_context(ctx)
    with in_force(ctx.root):
        walls, skipped, notes_list = retaining_walls.design_retaining_walls(sub_ctx)
    lines = [
        "# Retaining & Basement Wall Stability Report",
        "",
        f"- Designed walls: {len(walls)}",
        f"- Skipped walls: {len(skipped)}",
        *(
            [f"- {n}" for n in notes_list]
            if notes_list
            else ["- No retaining walls defined in 09 Substructure."]
        ),
    ]
    out_path = export_file(ctx, "retaining-wall-report.md", "\n".join(lines) + "\n")
    rows = [
        {"id": w["id"], "ok": w.get("ok", False), "util": w.get("utilisation", 0.0)} for w in walls
    ]
    return result(
        summary={
            "designedWalls": len(walls),
            "skippedWalls": len(skipped),
            "reportPath": str(out_path),
        },
        tables=[
            table(
                "Retaining wall checks",
                [("id", "Wall"), ("ok", "Pass"), ("util", "Max utilisation")],
                rows or [{"id": "-", "ok": True, "util": 0.0}],
            )
        ],
        notes=[f"Report written to {out_path}"],
    )


@feature(
    "foundationsReport.designAudit",
    "Design Audit",
    part="substructure",
    fields=[],
    requires_project=True,
)
def design_audit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Run the full substructure design audit and list skipped, failed, or unsupported items."""
    sub_ctx = load_substructure_context(ctx)
    with in_force(ctx.root):
        rep = sub_report.report(sub_ctx)
    foundations = rep.get("foundations", [])
    skipped = rep.get("skipped", [])
    failed = [f for f in foundations if not f.get("ok", True)]
    rows = [
        {
            "id": f["id"],
            "type": f["type"],
            "status": "PASS" if f.get("ok") else "FAIL",
            "reason": f"Util {f.get('utilisation', 0.0):.2f}",
        }
        for f in foundations
    ]
    rows += [
        {"id": s["id"], "type": s["type"], "status": "SKIPPED", "reason": s.get("reason", "")}
        for s in skipped
    ]
    return result(
        summary={
            "designedCount": len(foundations),
            "failedCount": len(failed),
            "skippedCount": len(skipped),
            "auditClean": len(failed) == 0 and len(skipped) == 0,
        },
        tables=[
            table(
                "Foundation design audit",
                [("id", "ID"), ("type", "Type"), ("status", "Status"), ("reason", "Details")],
                rows,
            )
        ],
        notes=rep.get("notes", ["Audit completed across 09 Substructure."])[:8],
    )


@feature(
    "foundationsReport.clashWithServices",
    "Clash With Services",
    part="substructure",
    fields=[
        number(
            "minClearanceMm", "Minimum required clear horizontal buffer", 300.0, unit="mm", min=50.0
        ),
    ],
    requires_project=True,
)
def clash_with_services(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check 09 Substructure foundations against buried MEP pipes/drains in 07 MEP/mep.json."""
    sub = load_substructure_model(ctx)
    mep_raw = ctx.raw("mep") or {}
    runs = mep_raw.get("runs") or mep_raw.get("pipes") or mep_raw.get("elements") or []
    clashes = []
    buf = values["minClearanceMm"]
    for f in sub.foundations:
        cx, cy = (f.center[0], f.center[1]) if f.center else (0.0, 0.0)
        hl = (f.length or 1500.0) / 2.0 + buf
        hb = (f.width or 1500.0) / 2.0 + buf
        for r in runs:
            pts = r.get("points") or r.get("path") or []
            for pt in pts:
                if len(pt) >= 2 and abs(float(pt[0]) - cx) <= hl and abs(float(pt[1]) - cy) <= hb:
                    clashes.append(
                        {
                            "foundation": f.id,
                            "service": r.get("id", "MEP"),
                            "xMm": float(pt[0]),
                            "yMm": float(pt[1]),
                        }
                    )
    return result(
        summary={
            "foundationsChecked": len(sub.foundations),
            "mepItemsChecked": len(runs),
            "clashCount": len(clashes),
            "clashFree": len(clashes) == 0,
        },
        tables=[
            table(
                "Substructure vs buried services clash check",
                [
                    ("foundation", "Foundation"),
                    ("service", "MEP item"),
                    ("xMm", "x", "mm"),
                    ("yMm", "y", "mm"),
                ],
                clashes
                or [{"foundation": "-", "service": "No clashes detected", "xMm": 0.0, "yMm": 0.0}],
            )
        ],
        notes=[f"Checked with {buf:g} mm clearance buffer around footing footprints."],
    )


@feature(
    "foundationsReport.asBuiltCheck",
    "As-Built Check",
    part="substructure",
    fields=[
        text("foundationId", "Foundation ID", "F1"),
        number("designTopMm", "Design top level", -1000.0, unit="mm"),
        number("asBuiltTopMm", "Surveyed as-built top level", -1012.0, unit="mm"),
        number("planOffsetXMm", "Surveyed centre offset ΔX", 18.0, unit="mm"),
        number("planOffsetYMm", "Surveyed centre offset ΔY", -12.0, unit="mm"),
        number("levelTolMm", "Permissible level tolerance (±)", 15.0, unit="mm", min=2.0),
        number("planTolMm", "Permissible plan offset tolerance", 25.0, unit="mm", min=5.0),
    ],
    requires_project=False,
)
def as_built_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare as-built foundation survey levels and plan positions against construction tolerances."""
    dz = values["asBuiltTopMm"] - values["designTopMm"]
    dr = math.hypot(values["planOffsetXMm"], values["planOffsetYMm"])
    z_ok = abs(dz) <= values["levelTolMm"]
    r_ok = dr <= values["planTolMm"]
    rows = [
        {
            "check": "Top elevation ΔZ",
            "actualMm": dz,
            "tolMm": values["levelTolMm"],
            "status": "PASS" if z_ok else "OUT OF TOL",
        },
        {
            "check": "Plan radial shift ΔR",
            "actualMm": dr,
            "tolMm": values["planTolMm"],
            "status": "PASS" if r_ok else "OUT OF TOL",
        },
    ]
    return result(
        summary={
            "foundationId": values["foundationId"],
            "levelErrorMm": dz,
            "planShiftMm": dr,
            "withinTolerance": z_ok and r_ok,
        },
        tables=[
            table(
                f"As-built survey check ({values['foundationId']})",
                [
                    ("check", "Check"),
                    ("actualMm", "Deviation", "mm"),
                    ("tolMm", "Tolerance", "mm"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
        notes=[
            "Out-of-tolerance eccentricity should be re-checked with column base bending moments."
        ],
    )


@feature(
    "foundationsReport.foundationPlan",
    "Foundation Plan",
    part="substructure",
    fields=[
        text("filename", "DXF filename", "foundation-plan.dxf"),
    ],
    requires_project=True,
)
def foundation_plan(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate the foundation setting-out plan and export a CAD DXF into 09 Substructure/exports."""
    sub = load_substructure_model(ctx)
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    rows = []
    for f in sub.foundations:
        cx, cy = (f.center[0], f.center[1]) if f.center else (0.0, 0.0)
        l_mm, b_mm = float(f.length or 1500.0), float(f.width or 1500.0)
        hl, hb = l_mm / 2.0, b_mm / 2.0
        pts = [
            (cx - hl, cy - hb),
            (cx + hl, cy - hb),
            (cx + hl, cy + hb),
            (cx - hl, cy + hb),
            (cx - hl, cy - hb),
        ]
        msp.add_lwpolyline(pts, dxfattribs={"layer": "FOOTINGS"})
        msp.add_text(f.id, dxfattribs={"height": 180.0, "layer": "LABELS"}).set_placement((cx, cy))
        rows.append(
            {
                "id": f.id,
                "type": f.type,
                "xMm": cx,
                "yMm": cy,
                "lengthMm": l_mm,
                "widthMm": b_mm,
                "thickMm": f.thickness or 0.0,
                "levelMm": f.foundingLevel or -2000.0,
            }
        )
    buf = io.StringIO()
    doc.write(buf)
    fname = values["filename"].strip() or "foundation-plan.dxf"
    out_path = export_bytes(ctx, fname, buf.getvalue().encode("utf-8"))
    return result(
        summary={"foundationCount": len(rows), "dxfPath": str(out_path)},
        tables=[
            table(
                "Foundation setting-out plan schedule",
                [
                    ("id", "ID"),
                    ("type", "Type"),
                    ("xMm", "X", "mm"),
                    ("yMm", "Y", "mm"),
                    ("lengthMm", "L", "mm"),
                    ("widthMm", "B", "mm"),
                    ("levelMm", "Founding", "mm"),
                ],
                rows,
            )
        ],
        notes=[f"CAD setting-out plan exported to {out_path}"],
    )


@feature(
    "foundationsReport.sectionDrawings",
    "Section Drawings",
    part="substructure",
    fields=[],
    requires_project=True,
)
def section_drawings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate cross-section drawings for project footings/walls into 09 Substructure/exports/foundation-sections.dxf."""
    sub = load_substructure_model(ctx)
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    rows = []
    x_offset = 0.0
    for f in sub.foundations:
        l_mm = float(f.length or 2000.0)
        h_mm = float(f.thickness or 500.0)
        msp.add_lwpolyline(
            [
                (x_offset, 0),
                (x_offset + l_mm, 0),
                (x_offset + l_mm, h_mm),
                (x_offset, h_mm),
                (x_offset, 0),
            ]
        )
        msp.add_text(f"{f.id} ({l_mm:g}x{h_mm:g})", dxfattribs={"height": 120.0}).set_placement(
            (x_offset, -250.0)
        )
        rows.append({"id": f.id, "spanMm": l_mm, "depthMm": h_mm, "originXMm": x_offset})
        x_offset += l_mm + 1200.0
    buf = io.StringIO()
    doc.write(buf)
    out_path = export_bytes(ctx, "foundation-sections.dxf", buf.getvalue().encode("utf-8"))
    return result(
        summary={"sectionCount": len(rows), "dxfPath": str(out_path)},
        tables=[
            table(
                "Generated foundation sections",
                [
                    ("id", "ID"),
                    ("spanMm", "Section width", "mm"),
                    ("depthMm", "Depth", "mm"),
                    ("originXMm", "Sheet X", "mm"),
                ],
                rows,
            )
        ],
        notes=[f"Section DXF written to {out_path}"],
    )


@feature(
    "foundationsReport.detailSheets",
    "Detail Sheets",
    part="substructure",
    fields=[
        text("sheetPrefix", "Drawing sheet series prefix", "S-FDN"),
    ],
    requires_project=True,
)
def detail_sheets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assemble the substructure drawing sheet register and export JSON to 09 Substructure/exports."""
    sub = load_substructure_model(ctx)
    pref = values["sheetPrefix"].strip() or "S-FDN"
    sheets = [
        {"sheetNo": f"{pref}-01", "title": "Foundation General Notes & Key", "scale": "NTS"},
        {
            "sheetNo": f"{pref}-02",
            "title": f"Foundation Setting-Out Plan ({len(sub.foundations)} bases)",
            "scale": "1:50",
        },
        {
            "sheetNo": f"{pref}-03",
            "title": "Footing & Pile Cap Reinforcement Details",
            "scale": "1:20",
        },
    ]
    if sub.retainingWalls:
        sheets.append(
            {
                "sheetNo": f"{pref}-04",
                "title": "Retaining Wall Sections & Waterstops",
                "scale": "1:25",
            }
        )
    out_path = export_file(ctx, "detail-sheet-index.json", json.dumps({"sheets": sheets}, indent=2))
    return result(
        summary={"sheetCount": len(sheets), "indexPath": str(out_path)},
        tables=[
            table(
                "Substructure detail sheet register",
                [("sheetNo", "Sheet No."), ("title", "Sheet Title"), ("scale", "Scale")],
                sheets,
            )
        ],
        notes=[f"Sheet index written to {out_path}"],
    )


@feature(
    "foundationsReport.rebarDrawings",
    "Rebar Drawings",
    part="substructure",
    fields=[],
    requires_project=True,
)
def rebar_drawings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Issue foundation reinforcement drawing schedule manifest to 09 Substructure/exports."""
    sub = load_substructure_model(ctx)
    rows = []
    for f in sub.foundations:
        reinf = f.reinforcement
        bx = (
            f"Ø{reinf.bottomX.dia:g}@{reinf.bottomX.spacing:g}"
            if reinf and reinf.bottomX
            else "Unassigned"
        )
        by = (
            f"Ø{reinf.bottomY.dia:g}@{reinf.bottomY.spacing:g}"
            if reinf and reinf.bottomY
            else "Unassigned"
        )
        rows.append(
            {"id": f.id, "coverMm": reinf.cover if reinf else 75.0, "bottomX": bx, "bottomY": by}
        )
    lines = [
        "# Substructure Rebar Drawing Manifest",
        "",
        *[
            f"- {r['id']}: Bottom X {r['bottomX']}, Bottom Y {r['bottomY']}, Cover {r['coverMm']:g} mm"
            for r in rows
        ],
    ]
    out_path = export_file(ctx, "rebar-drawings-manifest.md", "\n".join(lines) + "\n")
    return result(
        summary={"elementCount": len(rows), "manifestPath": str(out_path)},
        tables=[
            table(
                "Issued footing rebar specifications",
                [
                    ("id", "Element"),
                    ("coverMm", "Cover", "mm"),
                    ("bottomX", "Bottom X"),
                    ("bottomY", "Bottom Y"),
                ],
                rows,
            )
        ],
        notes=[f"Rebar drawing manifest saved to {out_path}"],
    )


@feature(
    "foundationsReport.designCalculations",
    "Design Calculations",
    part="substructure",
    fields=[],
    requires_project=True,
)
def design_calculations(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile foundation design calculation summary and export Markdown to 09 Substructure/exports."""
    sub_ctx = load_substructure_context(ctx)
    with in_force(ctx.root):
        rep = sub_report.report(sub_ctx)
    lines = [
        "# Foundation Design Calculations",
        "",
        f"- Designed elements: {len(rep.get('foundations', []))}",
        f"- Skipped elements: {len(rep.get('skipped', []))}",
        "",
        "## Method & Basis",
        *[f"- {m}" for m in rep.get("method", [])],
        "",
        "## Design Notes",
        *[f"- {n}" for n in rep.get("notes", [])],
    ]
    out_path = export_file(ctx, "design-calculations.md", "\n".join(lines) + "\n")
    return result(
        summary={
            "designedCount": len(rep.get("foundations", [])),
            "skippedCount": len(rep.get("skipped", [])),
            "reportPath": str(out_path),
        },
        tables=[
            table(
                "Design calculation element status",
                [("id", "ID"), ("type", "Type"), ("reason", "Note")],
                [
                    {"id": s["id"], "type": s["type"], "reason": s["reason"]}
                    for s in rep.get("skipped", [])
                ]
                or [{"id": "All", "type": "-", "reason": "Complete"}],
            )
        ],
        notes=[f"Calculation report written to {out_path}"],
    )


@feature(
    "foundationsReport.settlementCalculations",
    "Settlement Calculations",
    part="substructure",
    fields=[
        number(
            "assumedBearingKpa",
            "Fallback service pressure (if no FEM)",
            140.0,
            unit="kPa",
            min=10.0,
        ),
    ],
    requires_project=True,
)
def settlement_calculations(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute settlement calculations for every project foundation on the soil report."""
    sub = load_substructure_model(ctx)
    soil_rep = ctx.soil()
    if soil_rep is None or not soil_rep.boreholes:
        raise FeatureInputError(
            "Add a borehole to 01 Soil Report before running settlement calculations."
        )
    rows = []
    with in_force(ctx.root):
        prof = Profile(soil_rep, soil_rep.boreholes[0])
        for f in sub.foundations:
            b_m = min(float(f.width or 1500.0), float(f.length or 2000.0)) / 1000.0
            l_m = max(float(f.width or 1500.0), float(f.length or 2000.0)) / 1000.0
            df_m = max(0.3, abs(float(f.foundingLevel or -1500.0)) / 1000.0)
            res = soil_settlement.settlement(prof, b_m, l_m, df_m, values["assumedBearingKpa"])
            rows.append(
                {
                    "id": f.id,
                    "widthM": b_m,
                    "lengthM": l_m,
                    "immediateMm": res.get("immediate", 0.0),
                    "consolMm": res.get("consolidation", 0.0),
                    "totalMm": res["total"],
                }
            )
    lines = [
        "# Foundation Settlement Calculations",
        "",
        *[
            f"- {r['id']} ({r['widthM']:.2f}×{r['lengthM']:.2f} m): Total = {r['totalMm']:.2f} mm (Immediate {r['immediateMm']:.2f} + Consol {r['consolMm']:.2f})"
            for r in rows
        ],
    ]
    out_path = export_file(ctx, "settlement-calculations.md", "\n".join(lines) + "\n")
    return result(
        summary={
            "foundationCount": len(rows),
            "maxSettlementMm": max((r["totalMm"] for r in rows), default=0.0),
            "reportPath": str(out_path),
        },
        tables=[
            table(
                "Foundation settlement calculations",
                [
                    ("id", "ID"),
                    ("widthM", "B", "m"),
                    ("lengthM", "L", "m"),
                    ("immediateMm", "Immediate", "mm"),
                    ("consolMm", "Consol", "mm"),
                    ("totalMm", "Total", "mm"),
                ],
                rows,
            )
        ],
        notes=[f"Settlement calculation sheet written to {out_path}"],
    )


@feature(
    "foundationsReport.capacityCalculations",
    "Capacity Calculations",
    part="substructure",
    fields=[],
    requires_project=True,
)
def capacity_calculations(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile allowable bearing and pile capacity calculations for all project foundations."""
    sub = load_substructure_model(ctx)
    soil_rep = ctx.soil()
    if soil_rep is None or not soil_rep.boreholes:
        raise FeatureInputError(
            "Add a borehole to 01 Soil Report before compiling capacity calculations."
        )
    rows = []
    with in_force(ctx.root):
        prof = Profile(soil_rep, soil_rep.boreholes[0])
        for f in sub.foundations:
            b_m = min(float(f.width or 1500.0), float(f.length or 2000.0)) / 1000.0
            l_m = max(float(f.width or 1500.0), float(f.length or 2000.0)) / 1000.0
            df_m = max(0.3, abs(float(f.foundingLevel or -1500.0)) / 1000.0)
            res = soil_bearing.allowable(prof, b_m, l_m, df_m)
            rows.append(
                {
                    "id": f.id,
                    "type": f.type,
                    "allowableKpa": res["qa"],
                    "governing": res.get("governs", "bearing"),
                }
            )
    lines = [
        "# Foundation Capacity Calculations",
        "",
        *[
            f"- {r['id']} ({r['type']}): qa = {r['allowableKpa']:.1f} kPa ({r['governing']})"
            for r in rows
        ],
    ]
    out_path = export_file(ctx, "capacity-calculations.md", "\n".join(lines) + "\n")
    return result(
        summary={
            "foundationCount": len(rows),
            "minAllowableKpa": min((r["allowableKpa"] for r in rows), default=0.0),
            "reportPath": str(out_path),
        },
        tables=[
            table(
                "Allowable foundation bearing capacities",
                [
                    ("id", "ID"),
                    ("type", "Type"),
                    ("allowableKpa", "Allowable qa", "kPa"),
                    ("governing", "Governing"),
                ],
                rows,
            )
        ],
        notes=[f"Capacity calculation sheet written to {out_path}"],
    )


@feature(
    "foundationsReport.stabilityCalculations",
    "Stability Calculations",
    part="substructure",
    fields=[],
    requires_project=True,
)
def stability_calculations(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile overall building stability, retaining wall, and excavation checks to Markdown."""
    sub_ctx = load_substructure_context(ctx)
    with in_force(ctx.root):
        b_stab = sub_report.building_stability(sub_ctx)
        walls, _, _ = retaining_walls.design_retaining_walls(sub_ctx)
        exc_list, _ = excavation.design_excavations(sub_ctx)
    lines = [
        "# Substructure Stability Calculations",
        "",
        f"- Retaining walls checked: {len(walls)}",
        f"- Excavations checked: {len(exc_list)}",
        f"- Overall building buoyancy/sliding status: {b_stab if b_stab else 'Not triggered / no basement flood data'}",
    ]
    out_path = export_file(ctx, "stability-calculations.md", "\n".join(lines) + "\n")
    rows = [
        {
            "scope": "Building global stability",
            "count": 1 if b_stab else 0,
            "status": "Evaluated" if b_stab else "N/A",
        },
        {
            "scope": "Retaining walls",
            "count": len(walls),
            "status": "Evaluated" if walls else "None in model",
        },
        {
            "scope": "Excavation stability",
            "count": len(exc_list),
            "status": "Evaluated" if exc_list else "None in model",
        },
    ]
    return result(
        summary={
            "retainingWalls": len(walls),
            "excavations": len(exc_list),
            "reportPath": str(out_path),
        },
        tables=[
            table(
                "Substructure stability calculations status",
                [("scope", "Scope"), ("count", "Items"), ("status", "Status")],
                rows,
            )
        ],
        notes=[f"Stability calculation report written to {out_path}"],
    )


@feature(
    "foundationsReport.reportCover",
    "Report Cover",
    part="substructure",
    fields=[
        text("reportTitle", "Report title", "Substructure & Foundation Engineering Design Report"),
        text("author", "Prepared by", "Structural Engineering Team"),
        text("revision", "Revision mark", "R0"),
    ],
    requires_project=True,
)
def report_cover(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate the substructure report cover sheet using project settings metadata."""
    settings = ctx.settings()
    proj_name = (
        getattr(getattr(settings, "project", None), "name", None) or ctx.root.name
        if ctx.root
        else "Project"
    )
    today = dt.date.today().isoformat()
    content = (
        f"# {values['reportTitle']}\n\n"
        f"**Project:** {proj_name}\n\n"
        f"**Revision:** {values['revision']}\n\n"
        f"**Prepared by:** {values['author']}\n\n"
        f"**Date:** {today}\n"
    )
    out_path = export_file(ctx, "report-cover.md", content)
    return result(
        summary={
            "project": proj_name,
            "revision": values["revision"],
            "date": today,
            "coverPath": str(out_path),
        },
        tables=[
            table(
                "Report cover metadata",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Title", "value": values["reportTitle"]},
                    {"field": "Project", "value": proj_name},
                    {"field": "Revision", "value": values["revision"]},
                    {"field": "Date", "value": today},
                ],
            )
        ],
        notes=[f"Cover page written to {out_path}"],
    )


@feature(
    "foundationsReport.contentsPage",
    "Contents Page",
    part="substructure",
    fields=[],
    requires_project=True,
)
def contents_page(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate an automatic table of contents indexing all generated foundation deliverables."""
    root = require_root(ctx, "contents page")
    exp_dir = root / "09 Substructure" / "exports"
    existing = sorted(p.name for p in exp_dir.iterdir() if p.is_file()) if exp_dir.is_dir() else []
    sections = [
        {
            "sec": "1.0",
            "title": "Basis of Design & Geotechnical Summary",
            "artifact": "capacity-calculations.md",
        },
        {
            "sec": "2.0",
            "title": "Foundation Load Audit & Combinations",
            "artifact": "load-audit-report.md",
        },
        {
            "sec": "3.0",
            "title": "Bearing & Settlement Calculations",
            "artifact": "settlement-calculations.md",
        },
        {
            "sec": "4.0",
            "title": "Structural Design Calculations",
            "artifact": "design-calculations.md",
        },
        {
            "sec": "5.0",
            "title": "Retaining & Excavation Stability",
            "artifact": "stability-calculations.md",
        },
        {
            "sec": "6.0",
            "title": "Drawings & Bar Bending Schedule",
            "artifact": "foundation-plan.dxf",
        },
    ]
    lines = [
        "# Table of Contents",
        "",
        *[f"- {s['sec']} {s['title']} ({s['artifact']})" for s in sections],
        "",
        f"Exported files present: {len(existing)}",
    ]
    out_path = export_file(ctx, "contents-page.md", "\n".join(lines) + "\n")
    return result(
        summary={
            "sectionCount": len(sections),
            "exportedFilesFound": len(existing),
            "contentsPath": str(out_path),
        },
        tables=[
            table(
                "Report contents index",
                [("sec", "Section"), ("title", "Title"), ("artifact", "Linked deliverable")],
                sections,
            )
        ],
        notes=[f"Contents page written to {out_path}"],
    )


@feature(
    "foundationsReport.photoAppendix",
    "Photo Appendix",
    part="substructure",
    fields=[
        text("captionPrefix", "Figure caption prefix", "Site Photo"),
    ],
    requires_project=True,
)
def photo_appendix(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Index site and geotechnical photographs in the project folder into a numbered appendix."""
    root = require_root(ctx, "photo appendix")
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    photos = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in exts)
    rows = [
        {
            "fig": f"{values['captionPrefix']} {i + 1}",
            "file": str(p.relative_to(root)),
            "sizeKb": round(p.stat().st_size / 1024.0, 1),
        }
        for i, p in enumerate(photos)
    ]
    lines = [
        "# Photo Appendix",
        "",
        *(
            [f"- {r['fig']}: {r['file']} ({r['sizeKb']} KB)" for r in rows]
            or ["- No site photographs found in project directory."]
        ),
    ]
    out_path = export_file(ctx, "photo-appendix.md", "\n".join(lines) + "\n")
    return result(
        summary={"photoCount": len(rows), "appendixPath": str(out_path)},
        tables=[
            table(
                "Indexed site photographs",
                [("fig", "Figure"), ("file", "Relative path"), ("sizeKb", "Size", "KB")],
                rows or [{"fig": "-", "file": "None found", "sizeKb": 0.0}],
            )
        ],
        notes=[f"Photo appendix written to {out_path}"],
    )


@feature(
    "foundationsReport.issueSheet",
    "Issue Sheet",
    part="substructure",
    fields=[
        select(
            "purpose",
            "Issue purpose",
            [
                ("IFA", "Issued for Approval"),
                ("IFC", "Issued for Construction"),
                ("IFR", "Issued for Review"),
                ("PRELIM", "Preliminary"),
            ],
        ),
        text(
            "recipients",
            "Distribution recipients",
            "Client, Lead Architect, Geotechnical Consultant, Site Contractor",
        ),
        text("revision", "Revision", "R0"),
    ],
    requires_project=True,
)
def issue_sheet(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record document issue purpose, revision, recipients, and date into 09 Substructure/exports."""
    today = dt.date.today().isoformat()
    rec_list = [r.strip() for r in values["recipients"].split(",") if r.strip()]
    lines = [
        "# Substructure Deliverable Issue Sheet",
        "",
        f"- Issue Purpose: {values['purpose']}",
        f"- Revision: {values['revision']}",
        f"- Date: {today}",
        "",
        "## Distribution",
        *[f"- {r}" for r in rec_list],
    ]
    out_path = export_file(ctx, "issue-sheet.md", "\n".join(lines) + "\n")
    rows = [
        {
            "recipient": r,
            "purpose": values["purpose"],
            "revision": values["revision"],
            "date": today,
        }
        for r in rec_list
    ]
    return result(
        summary={
            "purpose": values["purpose"],
            "revision": values["revision"],
            "recipientCount": len(rows),
            "sheetPath": str(out_path),
        },
        tables=[
            table(
                "Document issue distribution",
                [
                    ("recipient", "Recipient"),
                    ("purpose", "Purpose"),
                    ("revision", "Rev"),
                    ("date", "Date"),
                ],
                rows,
            )
        ],
        notes=[f"Issue sheet written to {out_path}"],
    )


@feature(
    "foundationsReport.checkerComments",
    "Checker Comments",
    part="substructure",
    fields=[
        text("commentId", "Comment ID", "CHK-01"),
        text("elementRef", "Element / Drawing ref", "F1 / S-FDN-02"),
        text(
            "comment",
            "Checker comment",
            "Verify minimum clear earth cover of 75 mm at pad underside.",
        ),
        select(
            "status",
            "Resolution status",
            [("Open", "Open"), ("Addressed", "Addressed"), ("Closed", "Closed")],
        ),
    ],
    requires_project=False,
)
def checker_comments(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Log and track independent checker comments and resolution status."""
    row = {
        "id": values["commentId"],
        "ref": values["elementRef"],
        "comment": values["comment"],
        "status": values["status"],
    }
    saved_note = "Logged in memory (open a project to save file)."
    if ctx.root is not None and ctx.root.exists():
        out_path = export_file(
            ctx,
            "checker-comments.md",
            f"# Checker Comments Register\n\n| ID | Ref | Comment | Status |\n| --- | --- | --- | --- |\n| {row['id']} | {row['ref']} | {row['comment']} | {row['status']} |\n",
        )
        saved_note = f"Checker register saved to {out_path}"
    return result(
        summary={
            "commentId": row["id"],
            "status": row["status"],
            "openCount": 1 if row["status"] == "Open" else 0,
        },
        tables=[
            table(
                "Checker comments log",
                [("id", "ID"), ("ref", "Reference"), ("comment", "Comment"), ("status", "Status")],
                [row],
            )
        ],
        notes=[saved_note],
    )


@feature(
    "foundationsReport.revisionNotes",
    "Revision Notes",
    part="substructure",
    fields=[
        text("revision", "Revision code", "R0"),
        text("author", "Author initials", "SE"),
        text(
            "description", "Summary of revision changes", "Initial substructure issue for review."
        ),
    ],
    requires_project=False,
)
def revision_notes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record report revision history notes and date."""
    today = dt.date.today().isoformat()
    row = {
        "rev": values["revision"],
        "date": today,
        "author": values["author"],
        "changes": values["description"],
    }
    note_msg = "Revision record formatted (open a project to export file)."
    if ctx.root is not None and ctx.root.exists():
        out_path = export_file(
            ctx,
            "revision-notes.md",
            f"# Revision History\n\n| Rev | Date | Author | Description |\n| --- | --- | --- | --- |\n| {row['rev']} | {today} | {row['author']} | {row['changes']} |\n",
        )
        note_msg = f"Revision notes written to {out_path}"
    return result(
        summary={"revision": row["rev"], "date": today, "author": row["author"]},
        tables=[
            table(
                "Revision log",
                [
                    ("rev", "Rev"),
                    ("date", "Date"),
                    ("author", "Author"),
                    ("changes", "Description"),
                ],
                [row],
            )
        ],
        notes=[note_msg],
    )


@feature(
    "foundationsReport.approvalSheet",
    "Approval Sheet",
    part="substructure",
    fields=[
        text("designer", "Designed by", "Structural Engineer"),
        text("checker", "Checked by", "Senior Geotechnical/Structural Reviewer"),
        text("approver", "Approved by", "Principal Engineer"),
    ],
    requires_project=True,
)
def approval_sheet(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Produce a formal design, check, and approval signature sheet into 09 Substructure/exports."""
    today = dt.date.today().isoformat()
    rows = [
        {
            "role": "Design",
            "name": values["designer"],
            "signature": "________________",
            "date": today,
        },
        {
            "role": "Check",
            "name": values["checker"],
            "signature": "________________",
            "date": today,
        },
        {
            "role": "Approval",
            "name": values["approver"],
            "signature": "________________",
            "date": today,
        },
    ]
    lines = [
        "# Substructure Design Approval Sheet",
        "",
        "| Role | Name | Signature | Date |",
        "| --- | --- | --- | --- |",
    ]
    lines += [f"| {r['role']} | {r['name']} | {r['signature']} | {r['date']} |" for r in rows]
    out_path = export_file(ctx, "approval-sheet.md", "\n".join(lines) + "\n")
    return result(
        summary={"signoffRoles": len(rows), "date": today, "sheetPath": str(out_path)},
        tables=[
            table(
                "Approval sign-off sheet",
                [
                    ("role", "Role"),
                    ("name", "Engineer"),
                    ("signature", "Signature"),
                    ("date", "Date"),
                ],
                rows,
            )
        ],
        notes=[f"Approval sheet written to {out_path}"],
    )

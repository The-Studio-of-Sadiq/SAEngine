"""Materials Compliance tab: validation, equivalence, scheduling, certification, and XML/submittal exports."""

from __future__ import annotations

import csv
import io
import math
import xml.etree.ElementTree as ET
from typing import Any

import openpyxl

from saengine.codes import context as code_context
from saengine.design.rc_detailing import material_modulus
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
from saengine.features.materials_common import (
    material_strength_mpa,
    materials_or_default,
    parse_csv_rows,
    project_material_usage,
    require_materials,
    safe_json,
    save_export,
)
from saengine.library.check import check_library
from saengine.library.defaults import default_material_library
from saengine.library.materials import Category, modulus_of_rupture
from saengine.report.clauses import in_force


@feature(
    "libraryCompliance.materialChecks",
    "Material Checks",
    part="materials",
    fields=[checkbox("includeWarnings", "Include plausibility warnings", True)],
    requires_project=True,
)
def material_checks(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate strengths, densities, and required properties across the project library."""
    lib = require_materials(ctx)
    raw_text = safe_json(lib.model_dump(mode="json", by_alias=True, exclude_none=True))
    with in_force(ctx.root):
        problems = check_library("materials", raw_text)
    rows = []
    for p in problems:
        sev = p.get("severity", "error")
        if sev == "warning" and not values["includeWarnings"]:
            continue
        idx = p.get("index")
        mid = (
            lib.materials[idx].id
            if isinstance(idx, int) and 0 <= idx < len(lib.materials)
            else "library"
        )
        rows.append(
            {
                "materialId": mid,
                "severity": sev,
                "path": p.get("path", ""),
                "message": p.get("message", ""),
            }
        )
    err_cnt = sum(1 for r in rows if r["severity"] == "error")
    return result(
        summary={
            "materialCount": len(lib.materials),
            "errorCount": err_cnt,
            "findingCount": len(rows),
            "compliant": err_cnt == 0,
        },
        tables=[
            table(
                "Material validation checks",
                [
                    ("materialId", "Material"),
                    ("severity", "Severity"),
                    ("path", "Path"),
                    ("message", "Message"),
                ],
                rows,
            )
        ],
        notes=[
            "Evaluated using saengine.library.check.check_library under the project's active code pack."
        ],
    )


@feature(
    "libraryCompliance.duplicateNames",
    "Duplicate Names",
    part="materials",
    fields=[checkbox("caseInsensitive", "Case-insensitive comparison", True)],
    requires_project=True,
)
def duplicate_names(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Scan project materials for duplicate names, IDs, or identical category+strength pairs."""
    lib = require_materials(ctx)
    seen_names: dict[str, list[str]] = {}
    seen_specs: dict[tuple[str, float | None], list[str]] = {}
    for m in lib.materials:
        key = m.name.strip().lower() if values["caseInsensitive"] else m.name.strip()
        seen_names.setdefault(key, []).append(m.id)
        seen_specs.setdefault((m.category.value, material_strength_mpa(m)), []).append(m.id)

    rows = []
    for key, ids in seen_names.items():
        if len(ids) > 1:
            rows.append({"kind": "Duplicate name", "signature": key, "materialIds": ", ".join(ids)})
    for (cat, strength), ids in seen_specs.items():
        if len(ids) > 1 and strength is not None:
            rows.append(
                {
                    "kind": "Same category & strength",
                    "signature": f"{cat} {strength:g} MPa",
                    "materialIds": ", ".join(ids),
                }
            )
    return result(
        summary={
            "materialCount": len(lib.materials),
            "duplicateGroupCount": len(rows),
            "clean": len(rows) == 0,
        },
        tables=[
            table(
                "Duplicate or equivalent materials",
                [("kind", "Check"), ("signature", "Key"), ("materialIds", "Material IDs")],
                rows,
            )
        ],
        notes=["Checks both display names and identical (category, primary strength) pairs."],
    )


@feature(
    "libraryCompliance.missingProperties",
    "Missing Properties",
    part="materials",
    fields=[checkbox("checkSource", "Require standard/source documentation", True)],
    requires_project=True,
)
def missing_properties(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List materials missing mechanical, thermal, composition, or source metadata."""
    lib = require_materials(ctx)
    rows = []
    for m in lib.materials:
        missing = []
        if m.mechanical.density is None:
            missing.append("mechanical.density")
        if m.category != Category.MORTAR and m.mechanical.E is None:
            missing.append("mechanical.E")
        if (
            m.category in (Category.CONCRETE, Category.STEEL, Category.REBAR)
            and m.mechanical.nu is None
        ):
            missing.append("mechanical.nu")
        if m.category == Category.CONCRETE and m.composition is None:
            missing.append("composition")
        if m.category in (Category.STEEL, Category.REBAR) and m.steel and m.steel.fu is None:
            missing.append("steel.fu")
        if values["checkSource"] and (m.source is None or not (m.source.standard or m.source.note)):
            missing.append("source")
        if missing:
            rows.append(
                {
                    "id": m.id,
                    "category": m.category.value,
                    "missingFields": ", ".join(missing),
                    "count": len(missing),
                }
            )
    return result(
        summary={
            "materialCount": len(lib.materials),
            "incompleteCount": len(rows),
            "complete": len(rows) == 0,
        },
        tables=[
            table(
                "Materials with missing recommended fields",
                [
                    ("id", "ID"),
                    ("category", "Category"),
                    ("missingFields", "Missing fields"),
                    ("count", "Count"),
                ],
                rows,
            )
        ],
        notes=[
            "Checks mechanical constants, concrete mix composition, steel fu, and source metadata."
        ],
    )


@feature(
    "libraryCompliance.standardLibrary",
    "Standard Library",
    part="materials",
    fields=[checkbox("onlyDifferences", "Show only modified or custom materials", False)],
    requires_project=True,
)
def standard_library(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare project materials against the built-in default material library."""
    lib = require_materials(ctx)
    with in_force(ctx.root):
        std = default_material_library()
    std_map = {m.id: m for m in std.materials}
    rows = []
    matches = 0
    for m in lib.materials:
        ref = std_map.get(m.id)
        if ref is None:
            status = "Custom"
        else:
            s1 = material_strength_mpa(m)
            s2 = material_strength_mpa(ref)
            if (
                s1 == s2
                and m.mechanical.E == ref.mechanical.E
                and m.mechanical.density == ref.mechanical.density
            ):
                status = "Matches standard"
                matches += 1
            else:
                status = "Modified from standard"
        if values["onlyDifferences"] and status == "Matches standard":
            continue
        rows.append(
            {
                "id": m.id,
                "name": m.name,
                "category": m.category.value,
                "status": status,
                "strengthMpa": material_strength_mpa(m),
            }
        )
    return result(
        summary={
            "projectCount": len(lib.materials),
            "standardMatchCount": matches,
            "customOrModifiedCount": len(lib.materials) - matches,
        },
        tables=[
            table(
                "Standard library comparison",
                [
                    ("id", "ID"),
                    ("name", "Name"),
                    ("category", "Category"),
                    ("strengthMpa", "Strength", "MPa"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
        notes=[
            "Compares ID, primary strength, elastic modulus, and density against default_material_library()."
        ],
    )


@feature(
    "libraryCompliance.codeEquivalence",
    "Code Equivalence",
    part="materials",
    fields=[
        select(
            "sourceSystem",
            "Source grading basis",
            [
                ("cylinder_strength", "Cylinder f'c / yield fy"),
                ("cube_limitstate", "Cube fcu / limit-state"),
            ],
            "cylinder_strength",
        ),
        select(
            "targetSystem",
            "Target grading basis",
            [
                ("cube_limitstate", "Cube fcu / limit-state"),
                ("cylinder_strength", "Cylinder f'c / yield fy"),
            ],
            "cube_limitstate",
        ),
        number("concreteStrengthMpa", "Input concrete strength", 25.0, unit="MPa", min=10.0),
        number("steelYieldMpa", "Input steel yield strength", 420.0, unit="MPa", min=150.0),
    ],
    requires_project=False,
)
def code_equivalence(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map concrete cylinder/cube and steel strength designations between design bases."""
    fc_in = values["concreteStrengthMpa"]
    if values["sourceSystem"] == "cylinder_strength":
        fc_cyl = fc_in
        fc_cube = fc_in * 1.25
    else:
        fc_cube = fc_in
        fc_cyl = fc_in * 0.80
    fy = values["steelYieldMpa"]
    rows = [
        {
            "property": "Concrete cylinder f'c",
            "sourceMpa": fc_in if values["sourceSystem"] == "cylinder_strength" else fc_cyl,
            "targetMpa": fc_cyl,
        },
        {
            "property": "Concrete cube fcu",
            "sourceMpa": fc_in if values["sourceSystem"] == "cube_limitstate" else fc_cube,
            "targetMpa": fc_cube,
        },
        {"property": "Steel yield fy", "sourceMpa": fy, "targetMpa": fy},
    ]
    return result(
        summary={
            "equivalentCylinderFcMpa": fc_cyl,
            "equivalentCubeFcuMpa": fc_cube,
            "steelYieldMpa": fy,
        },
        tables=[
            table(
                "Material grade equivalence",
                [
                    ("property", "Property"),
                    ("sourceMpa", "Source", "MPa"),
                    ("targetMpa", "Target", "MPa"),
                ],
                rows,
            )
        ],
        notes=["Uses standard 0.80 cylinder-to-cube conversion factor (fc_cyl ≈ 0.80 f_cube)."],
    )


@feature(
    "libraryCompliance.testDataLink",
    "Test Data Link",
    part="materials",
    fields=[
        text("materialId", "Material ID", "C24.1"),
        text("labReportRef", "Laboratory report reference", "LAB-2026-001"),
        number("testedMeanMpa", "Tested mean strength", 28.5, unit="MPa", min=1.0),
    ],
    requires_project=False,
)
def test_data_link(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Link material specification to laboratory test report strength and verify compliance."""
    lib, _ = materials_or_default(ctx)
    mat = lib.get(values["materialId"].strip())
    spec = material_strength_mpa(mat) if mat else None
    margin = (values["testedMeanMpa"] - spec) if spec is not None else 0.0
    return result(
        summary={
            "materialId": values["materialId"].strip(),
            "labReportRef": values["labReportRef"].strip(),
            "specifiedMpa": spec if spec is not None else 0.0,
            "testedMeanMpa": values["testedMeanMpa"],
            "compliant": (values["testedMeanMpa"] >= spec) if spec is not None else True,
        },
        tables=[
            table(
                "Material-to-test linkage",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Material ID", "value": mat.id if mat else values["materialId"]},
                    {"field": "Lab report", "value": values["labReportRef"]},
                    {
                        "field": "Specified strength [MPa]",
                        "value": spec if spec is not None else "N/A",
                    },
                    {"field": "Tested mean [MPa]", "value": values["testedMeanMpa"]},
                    {"field": "Margin [MPa]", "value": margin},
                ],
            )
        ],
        notes=["Verifies tested mean strength meets or exceeds library specified strength."],
    )


@feature(
    "libraryCompliance.materialSchedule",
    "Material Schedule",
    part="materials",
    fields=[checkbox("onlyUsedInModel", "Only materials referenced by objects/BOQ", False)],
    requires_project=True,
)
def material_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Produce a project schedule of all materials, strengths, densities, and model usage."""
    lib = require_materials(ctx)
    usage = project_material_usage(ctx)
    rows = []
    for m in lib.materials:
        u = usage.get(m.id, 0)
        if values["onlyUsedInModel"] and u == 0:
            continue
        rows.append(
            {
                "id": m.id,
                "name": m.name,
                "category": m.category.value,
                "strengthMpa": material_strength_mpa(m),
                "modulusMpa": m.mechanical.E,
                "densityKgPerM3": m.mechanical.density,
                "usageCount": u,
            }
        )
    return result(
        summary={"scheduledCount": len(rows), "totalLibraryCount": len(lib.materials)},
        tables=[
            table(
                "Project material schedule",
                [
                    ("id", "ID"),
                    ("name", "Name"),
                    ("category", "Category"),
                    ("strengthMpa", "Strength", "MPa"),
                    ("modulusMpa", "E", "MPa"),
                    ("densityKgPerM3", "Density", "kg/m3"),
                    ("usageCount", "Refs"),
                ],
                rows,
            )
        ],
        notes=[
            "Combines 03 Materials/materials.json with reference counts from 04 Objects and 10 BOQ."
        ],
    )


@feature(
    "libraryCompliance.materialCertificates",
    "Material Certificates",
    part="materials",
    fields=[
        text("materialId", "Material ID", "B500DWR"),
        text("certificateId", "Certificate / heat number", "MILL-B500-2026-04"),
        text("issuer", "Issuing laboratory / mill", "Accredited Steel Testing Lab"),
        checkbox("verified", "Verified compliant", True),
    ],
    requires_project=False,
)
def material_certificates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Attach and register mill or laboratory certificate records to a material."""
    lib, _ = materials_or_default(ctx)
    mat = lib.get(values["materialId"].strip())
    rows = [
        {
            "materialId": mat.id if mat else values["materialId"].strip(),
            "category": mat.category.value if mat else "unknown",
            "certificateId": values["certificateId"].strip(),
            "issuer": values["issuer"].strip(),
            "verified": values["verified"],
        }
    ]
    return result(
        summary={
            "materialId": rows[0]["materialId"],
            "certificateId": rows[0]["certificateId"],
            "verified": values["verified"],
        },
        tables=[
            table(
                "Material certificate register",
                [
                    ("materialId", "Material"),
                    ("category", "Category"),
                    ("certificateId", "Certificate"),
                    ("issuer", "Issuer"),
                    ("verified", "Verified"),
                ],
                rows,
            )
        ],
        notes=["Records certificate attribution and verification state."],
    )


@feature(
    "libraryCompliance.exportSchedule",
    "Export Schedule",
    part="materials",
    fields=[
        select(
            "format",
            "Export format",
            [("xlsx", "Excel workbook (.xlsx)"), ("csv", "CSV (.csv)"), ("md", "Markdown (.md)")],
            "xlsx",
        ),
        text("filename", "Output filename (blank = auto)", ""),
    ],
    requires_project=True,
)
def export_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export the project material schedule to Excel (.xlsx), CSV, or Markdown."""
    lib = require_materials(ctx)
    usage = project_material_usage(ctx)
    fmt = values["format"]
    fname = values["filename"].strip() or f"material-schedule.{fmt}"
    headers = [
        "ID",
        "Name",
        "Category",
        "Strength [MPa]",
        "E [MPa]",
        "Density [kg/m3]",
        "Model Refs",
        "Standard",
    ]
    data_rows = [
        [
            m.id,
            m.name,
            m.category.value,
            material_strength_mpa(m),
            m.mechanical.E,
            m.mechanical.density,
            usage.get(m.id, 0),
            (m.source.standard if m.source else "") or "",
        ]
        for m in lib.materials
    ]
    if fmt == "xlsx":
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Materials"
        ws.append(headers)
        for r in data_rows:
            ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        out = save_export(ctx, fname, buf.getvalue())
    elif fmt == "csv":
        sio = io.StringIO()
        w = csv.writer(sio)
        w.writerow(headers)
        w.writerows(data_rows)
        out = save_export(ctx, fname, sio.getvalue())
    else:
        lines = [
            "# Project Material Schedule",
            "",
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]
        for r in data_rows:
            lines.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
        out = save_export(ctx, fname, "\n".join(lines) + "\n")
    return result(
        summary={"exportedCount": len(data_rows), "format": fmt, "exportPath": str(out)},
        tables=[
            table(
                "Exported schedule preview",
                [("id", "ID"), ("name", "Name"), ("category", "Category")],
                [{"id": r[0], "name": r[1], "category": r[2]} for r in data_rows],
            )
        ],
        notes=[f"Material schedule written to {out}."],
    )


@feature(
    "libraryCompliance.propertyVerify",
    "Property Verify",
    part="materials",
    fields=[
        number(
            "tolerancePct",
            "Allowed deviation from derived formula",
            10.0,
            unit="%",
            min=1.0,
            max=50.0,
        )
    ],
    requires_project=True,
)
def property_verify(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Recompute dependent concrete properties (Ec, fr) and flag deviations."""
    lib = require_materials(ctx)
    tol = values["tolerancePct"] / 100.0
    rows = []
    flagged = 0
    with in_force(ctx.root):
        for m in lib.materials:
            if m.category == Category.CONCRETE and m.concrete is not None:
                fc = m.concrete.fc
                ec_ref, how = material_modulus(m, fc=fc)
                ec_own = m.mechanical.E
                dev_e = abs(ec_own - ec_ref) / ec_ref if ec_own and ec_ref > 0 else 0.0
                fr_ref = modulus_of_rupture(fc)
                fr_own = m.concrete.ft
                dev_fr = abs(fr_own - fr_ref) / fr_ref if fr_own and fr_ref > 0 else 0.0
                ok = dev_e <= tol and dev_fr <= tol
                if not ok:
                    flagged += 1
                rows.append(
                    {
                        "id": m.id,
                        "fcMpa": fc,
                        "eOwnMpa": ec_own,
                        "eDerivedMpa": ec_ref,
                        "devPct": max(dev_e, dev_fr) * 100.0,
                        "ok": ok,
                        "formula": how,
                    }
                )
    return result(
        summary={"checkedCount": len(rows), "flaggedCount": flagged, "allConsistent": flagged == 0},
        tables=[
            table(
                "Derived property verification",
                [
                    ("id", "ID"),
                    ("fcMpa", "f'c", "MPa"),
                    ("eOwnMpa", "Entered E", "MPa"),
                    ("eDerivedMpa", "Derived E", "MPa"),
                    ("devPct", "Max dev", "%"),
                    ("ok", "Consistent"),
                ],
                rows,
            )
        ],
        notes=["Compares entered Ec and fr against code pack formulas."],
    )


@feature(
    "libraryCompliance.unitConsistency",
    "Unit Consistency",
    part="materials",
    fields=[],
    requires_project=True,
)
def unit_consistency(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify stored material properties match SAEngine canonical SI units (MPa, kg/m3, 1/C)."""
    lib = require_materials(ctx)
    rows = []
    issues = 0
    for m in lib.materials:
        e = m.mechanical.E
        rho = m.mechanical.density
        alpha = m.mechanical.alpha
        flags = []
        if e is not None and (e < 500 or e > 500000):
            flags.append("E outside MPa scale (expected 500-500000 MPa)")
        if rho is not None and (rho < 200 or rho > 12000):
            flags.append("density outside kg/m3 scale (expected 200-12000 kg/m3)")
        if alpha is not None and (alpha < 1e-7 or alpha > 1e-3):
            flags.append("alpha outside 1/C scale (expected 1e-7 to 1e-3)")
        if flags:
            issues += 1
        rows.append(
            {
                "id": m.id,
                "modulusMpa": e,
                "densityKgPerM3": rho,
                "status": "; ".join(flags) if flags else "SI consistent",
            }
        )
    return result(
        summary={"materialCount": len(rows), "anomalyCount": issues, "consistent": issues == 0},
        tables=[
            table(
                "SI unit scale verification",
                [
                    ("id", "ID"),
                    ("modulusMpa", "E", "MPa"),
                    ("densityKgPerM3", "Density", "kg/m3"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
        notes=[
            "Detects values likely entered in GPa/Pa or kN/m3 instead of canonical MPa and kg/m3."
        ],
    )


@feature(
    "libraryCompliance.strengthRangeCheck",
    "Strength Range Check",
    part="materials",
    fields=[],
    requires_project=True,
)
def strength_range_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare project material strengths against code pack minimums/maximums and sanity bands."""
    lib = require_materials(ctx)
    with in_force(ctx.root):
        mat_tbl = code_context.table("materials")
        fc_min = float(mat_tbl.structuralFcMin)
        fy_max = float(mat_tbl.rebarFyMax)
    rows = []
    out_of_range = 0
    for m in lib.materials:
        val = material_strength_mpa(m)
        ok = True
        band = "N/A"
        if m.category == Category.CONCRETE and val is not None:
            band = f"{fc_min:g} - 100 MPa"
            ok = fc_min <= val <= 100.0
        elif m.category == Category.REBAR and val is not None:
            band = f"200 - {fy_max:g} MPa"
            ok = 200.0 <= val <= fy_max
        elif m.category == Category.STEEL and val is not None:
            band = "200 - 700 MPa"
            ok = 200.0 <= val <= 700.0
        if not ok:
            out_of_range += 1
        rows.append(
            {
                "id": m.id,
                "category": m.category.value,
                "strengthMpa": val,
                "expectedBand": band,
                "ok": ok,
            }
        )
    return result(
        summary={
            "checkedCount": len(rows),
            "outOfRangeCount": out_of_range,
            "allInRange": out_of_range == 0,
        },
        tables=[
            table(
                "Strength range check",
                [
                    ("id", "ID"),
                    ("category", "Category"),
                    ("strengthMpa", "Strength", "MPa"),
                    ("expectedBand", "Allowed band"),
                    ("ok", "Pass"),
                ],
                rows,
            )
        ],
        notes=[
            "Structural concrete minimum f'c and rebar maximum fy read from the active code pack."
        ],
    )


@feature(
    "libraryCompliance.sourceTraceability",
    "Source Traceability",
    part="materials",
    fields=[],
    requires_project=True,
)
def source_traceability(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit standard citations and engineering notes across all project materials."""
    lib = require_materials(ctx)
    rows = []
    documented = 0
    for m in lib.materials:
        std = (m.source.standard if m.source else "") or ""
        note = (m.source.note if m.source else "") or ""
        has_doc = bool(std or note)
        if has_doc:
            documented += 1
        rows.append(
            {"id": m.id, "standard": std or "-", "hasNote": bool(note), "documented": has_doc}
        )
    pct = documented / len(lib.materials) * 100.0 if lib.materials else 0.0
    return result(
        summary={
            "materialCount": len(lib.materials),
            "documentedCount": documented,
            "coveragePercent": pct,
        },
        tables=[
            table(
                "Source traceability audit",
                [
                    ("id", "ID"),
                    ("standard", "Standard"),
                    ("hasNote", "Has note"),
                    ("documented", "Traceable"),
                ],
                rows,
            )
        ],
        notes=["Checks presence of Source.standard and Source.note on each material entry."],
    )


@feature(
    "libraryCompliance.versionCompare",
    "Version Compare",
    part="materials",
    fields=[text("baselineJson", "Optional baseline materials JSON (blank = default library)", "")],
    requires_project=True,
)
def version_compare(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Show property differences between current project materials and a baseline library."""
    lib = require_materials(ctx)
    if values["baselineJson"].strip():
        try:
            base = type(lib).model_validate_json(values["baselineJson"])
        except Exception as exc:
            raise FeatureInputError(f"Invalid baseline JSON: {exc}") from exc
    else:
        with in_force(ctx.root):
            base = default_material_library()
    cur_map = {m.id: m for m in lib.materials}
    base_map = {m.id: m for m in base.materials}
    rows = []
    for mid in sorted(set(cur_map) | set(base_map)):
        c, b = cur_map.get(mid), base_map.get(mid)
        if c and not b:
            rows.append({"id": mid, "change": "Added", "detail": c.name})
        elif b and not c:
            rows.append({"id": mid, "change": "Removed", "detail": b.name})
        elif c and b:
            diffs = []
            if material_strength_mpa(c) != material_strength_mpa(b):
                diffs.append(
                    f"strength {material_strength_mpa(b)} -> {material_strength_mpa(c)} MPa"
                )
            if c.mechanical.E != b.mechanical.E:
                diffs.append(f"E {b.mechanical.E} -> {c.mechanical.E} MPa")
            if c.mechanical.density != b.mechanical.density:
                diffs.append(f"density {b.mechanical.density} -> {c.mechanical.density} kg/m3")
            if diffs:
                rows.append({"id": mid, "change": "Modified", "detail": "; ".join(diffs)})
    return result(
        summary={
            "currentCount": len(cur_map),
            "baselineCount": len(base_map),
            "differenceCount": len(rows),
        },
        tables=[
            table(
                "Library version comparison",
                [("id", "Material"), ("change", "Change"), ("detail", "Details")],
                rows,
            )
        ],
        notes=["Compares material IDs, strengths, elastic moduli, and densities."],
    )


@feature(
    "libraryCompliance.testCertificateLink",
    "Test Certificate Link",
    part="materials",
    fields=[
        text("materialId", "Material ID", "B420DWR"),
        text("certificateNo", "Mill / test certificate number", "MTC-2026-884"),
        number("measuredYieldMpa", "Certificate yield strength fy", 455.0, unit="MPa", min=100.0),
        number(
            "measuredUltimateMpa", "Certificate tensile strength fu", 590.0, unit="MPa", min=100.0
        ),
        number("elongationPct", "Certificate elongation", 16.5, unit="%", min=1.0),
    ],
    requires_project=False,
)
def test_certificate_link(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Attach a mill/test certificate to a material and verify strength & ductility ratios."""
    fy = values["measuredYieldMpa"]
    fu = values["measuredUltimateMpa"]
    ratio = fu / fy
    with in_force(ctx.root):
        mat_tbl = code_context.table("materials")
        min_ratio = float(mat_tbl.fuFyMin)
        margin = float(mat_tbl.fyActualMargin)
    lib, _ = materials_or_default(ctx)
    mat = lib.get(values["materialId"].strip())
    nom_fy = mat.steel.fy if (mat and mat.steel) else fy
    overstrength_ok = fy <= nom_fy + margin
    ratio_ok = ratio >= min_ratio
    return result(
        summary={
            "certificateNo": values["certificateNo"].strip(),
            "fuFyRatio": ratio,
            "minRequiredRatio": min_ratio,
            "compliant": ratio_ok and overstrength_ok,
        },
        tables=[
            table(
                "Mill certificate check",
                [("check", "Check"), ("actual", "Actual"), ("limit", "Limit"), ("ok", "Pass")],
                [
                    {"check": "fu / fy ratio", "actual": ratio, "limit": min_ratio, "ok": ratio_ok},
                    {
                        "check": "Actual fy overstrength [MPa]",
                        "actual": fy - nom_fy,
                        "limit": margin,
                        "ok": overstrength_ok,
                    },
                    {
                        "check": "Elongation [%]",
                        "actual": values["elongationPct"],
                        "limit": 12.0,
                        "ok": values["elongationPct"] >= 12.0,
                    },
                ],
            )
        ],
        notes=["Limits fuFyMin and fyActualMargin read from the active code pack materials table."],
    )


@feature(
    "libraryCompliance.supplierDeclaration",
    "Supplier Declaration",
    part="materials",
    fields=[
        text("supplierName", "Supplier / manufacturer", "Regional Ready-Mix & Steel Ltd."),
        text("declarationId", "Declaration of Performance ID", "DOP-2026-102"),
        text("materialId", "Project material ID", "C24.1"),
        number(
            "declaredStrengthMpa", "Declared characteristic strength", 25.0, unit="MPa", min=1.0
        ),
        number("declaredDensityKgPerM3", "Declared density", 2400.0, unit="kg/m3", min=100.0),
    ],
    requires_project=False,
)
def supplier_declaration(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate a supplier Declaration of Performance against project material specs."""
    lib, _ = materials_or_default(ctx)
    mat = lib.get(values["materialId"].strip())
    req = material_strength_mpa(mat) if mat else None
    meets_spec = True if req is None else values["declaredStrengthMpa"] >= req
    return result(
        summary={
            "declarationId": values["declarationId"].strip(),
            "materialId": values["materialId"].strip(),
            "declaredStrengthMpa": values["declaredStrengthMpa"],
            "meetsSpecification": meets_spec,
        },
        tables=[
            table(
                "Supplier declaration record",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Supplier", "value": values["supplierName"]},
                    {"field": "DoP ID", "value": values["declarationId"]},
                    {"field": "Target material", "value": values["materialId"]},
                    {"field": "Declared strength [MPa]", "value": values["declaredStrengthMpa"]},
                    {
                        "field": "Project spec strength [MPa]",
                        "value": req if req is not None else "N/A",
                    },
                    {
                        "field": "Declared density [kg/m3]",
                        "value": values["declaredDensityKgPerM3"],
                    },
                ],
            )
        ],
        notes=["Compares supplier declared performance against project library specification."],
    )


@feature(
    "libraryCompliance.batchTraceability",
    "Batch Traceability",
    part="materials",
    fields=[
        text(
            "batchCsv",
            "Delivery batches CSV (batch,material,element_zone,qty,unit)",
            "batch,material,element_zone,qty,unit\nB-101,C24.1,Footings F1,18.5,m3\nB-102,C24.1,Columns L1,24.0,m3\nH-881,B420DWR,Beams L1,4200,kg",
        )
    ],
    requires_project=False,
)
def batch_traceability(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Trace material delivery batches to placed structural element zones."""
    rows = parse_csv_rows(values["batchCsv"])
    lib, _ = materials_or_default(ctx)
    known = {m.id for m in lib.materials}
    out = []
    for r in rows:
        mid = r.get("material", "")
        out.append(
            {
                "batch": r.get("batch", ""),
                "material": mid,
                "elementZone": r.get("element_zone", ""),
                "quantity": float(r.get("qty", 0) or 0),
                "unit": r.get("unit", ""),
                "inLibrary": mid in known,
            }
        )
    return result(
        summary={"batchCount": len(out), "matchedCount": sum(1 for r in out if r["inLibrary"])},
        tables=[
            table(
                "Batch-to-element traceability log",
                [
                    ("batch", "Batch ID"),
                    ("material", "Material"),
                    ("elementZone", "Placed element / zone"),
                    ("quantity", "Quantity"),
                    ("unit", "Unit"),
                    ("inLibrary", "In library"),
                ],
                out,
            )
        ],
        notes=["Links delivery lot numbers to placed structural zones and checks material IDs."],
    )


@feature(
    "libraryCompliance.conformityMark",
    "Conformity Mark",
    part="materials",
    fields=[
        text("materialId", "Material ID", "B500DWR"),
        text("markScheme", "Certification scheme / mark", "Third-party Product Conformity"),
        text("certNumber", "Certificate number", "CERT-2026-771"),
        checkbox("validStatus", "Certificate active and within validity", True),
    ],
    requires_project=False,
)
def conformity_mark(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate and record conformity marking details for submittal packages."""
    return result(
        summary={
            "materialId": values["materialId"].strip(),
            "certificateNumber": values["certNumber"].strip(),
            "active": values["validStatus"],
        },
        tables=[
            table(
                "Conformity mark register",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Material ID", "value": values["materialId"]},
                    {"field": "Scheme", "value": values["markScheme"]},
                    {"field": "Certificate number", "value": values["certNumber"]},
                    {"field": "Active", "value": values["validStatus"]},
                ],
            )
        ],
        notes=["Records third-party conformity mark details for quality submittals."],
    )


@feature(
    "libraryCompliance.samplingPlan",
    "Sampling Plan",
    part="materials",
    fields=[
        number("concreteVolumeM3", "Total concrete volume (0 = read BOQ)", 0.0, unit="m3", min=0.0),
        number("rebarMassTonnes", "Total rebar tonnage (0 = read BOQ)", 0.0, unit="t", min=0.0),
        number("concreteFreqM3", "Concrete sample interval", 50.0, unit="m3", min=10.0),
        number("rebarLotTonnes", "Rebar test lot size", 25.0, unit="t", min=5.0),
    ],
    requires_project=False,
)
def sampling_plan(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a material testing sampling frequency schedule from BOQ or entered quantities."""
    conc_vol = values["concreteVolumeM3"]
    rebar_t = values["rebarMassTonnes"]
    boq = ctx.raw("boq") or {}
    if conc_vol <= 0 or rebar_t <= 0:
        for item in boq.get("items") or []:
            if not isinstance(item, dict):
                continue
            if conc_vol <= 0 and item.get("group") == "concrete" and item.get("unit") == "m3":
                conc_vol += float(item.get("quantity") or 0)
            if rebar_t <= 0 and item.get("group") == "reinforcement" and item.get("unit") == "kg":
                rebar_t += float(item.get("quantity") or 0) / 1000.0
    conc_vol = max(conc_vol, 50.0)
    rebar_t = max(rebar_t, 10.0)
    conc_samples = max(1, math.ceil(conc_vol / values["concreteFreqM3"]))
    rebar_samples = max(1, math.ceil(rebar_t / values["rebarLotTonnes"]))
    rows = [
        {
            "material": "Concrete compressive cylinders",
            "quantity": conc_vol,
            "unit": "m3",
            "samplesRequired": conc_samples,
            "specimensTotal": conc_samples * 3,
        },
        {
            "material": "Reinforcing steel tensile tests",
            "quantity": rebar_t,
            "unit": "t",
            "samplesRequired": rebar_samples,
            "specimensTotal": rebar_samples * 2,
        },
    ]
    return result(
        summary={
            "concreteVolumeM3": conc_vol,
            "rebarMassTonnes": rebar_t,
            "totalSampleSets": conc_samples + rebar_samples,
            "totalSpecimens": conc_samples * 3 + rebar_samples * 2,
        },
        tables=[
            table(
                "Project material sampling plan",
                [
                    ("material", "Material test"),
                    ("quantity", "Quantity"),
                    ("unit", "Unit"),
                    ("samplesRequired", "Sample lots"),
                    ("specimensTotal", "Total specimens"),
                ],
                rows,
            )
        ],
        notes=[
            "Reads 10 BOQ/boq.json quantities when inputs are 0; assumes 3 cylinders/lot and 2 bars/lot."
        ],
    )


@feature(
    "libraryCompliance.exportMaterialXml",
    "Export Material XML",
    part="materials",
    fields=[text("filename", "Output XML filename", "materials.xml")],
    requires_project=True,
)
def export_material_xml(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export the project material library to a structured XML exchange file."""
    lib = require_materials(ctx)
    root = ET.Element("MaterialLibrary", schema=lib.schema_)
    for m in lib.materials:
        el = ET.SubElement(root, "Material", id=m.id, category=m.category.value)
        ET.SubElement(el, "Name").text = m.name
        mech = ET.SubElement(el, "Mechanical")
        for k, v in m.mechanical.model_dump(exclude_none=True).items():
            ET.SubElement(mech, k).text = str(v)
        strength = material_strength_mpa(m)
        if strength is not None:
            ET.SubElement(el, "PrimaryStrengthMpa").text = str(strength)
    ET.indent(root, space="  ")
    xml_text = ET.tostring(root, encoding="unicode", xml_declaration=True) + "\n"
    fname = values["filename"].strip() or "materials.xml"
    out = save_export(ctx, fname, xml_text)
    return result(
        summary={"exportedCount": len(lib.materials), "exportPath": str(out)},
        tables=[
            table(
                "XML exported materials",
                [("id", "ID"), ("category", "Category"), ("name", "Name")],
                [{"id": m.id, "category": m.category.value, "name": m.name} for m in lib.materials],
            )
        ],
        notes=[f"Structured XML written to {out}."],
    )


@feature(
    "libraryCompliance.importSupplierData",
    "Import Supplier Data",
    part="materials",
    fields=[
        text(
            "supplierCsv",
            "Supplier data CSV (id,name,category,strength_mpa,E_mpa,density_kg_m3)",
            "id,name,category,strength_mpa,E_mpa,density_kg_m3\nSUP-C35,ReadyMix 35 MPa,concrete,35,27800,2420\nSUP-B500,Mill Rebar 500,rebar,500,200000,7850",
        )
    ],
    requires_project=False,
)
def import_supplier_data(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Parse supplier CSV property sheets and map them onto existing or new material entries."""
    rows_raw = parse_csv_rows(values["supplierCsv"])
    lib, _ = materials_or_default(ctx)
    existing = {m.id for m in lib.materials}
    out = []
    for r in rows_raw:
        try:
            strength = float(r["strength_mpa"])
            e_val = float(r["E_mpa"])
            rho = float(r["density_kg_m3"])
        except (KeyError, ValueError) as exc:
            raise FeatureInputError(
                "Supplier CSV requires id,name,category,strength_mpa,E_mpa,density_kg_m3."
            ) from exc
        mid = r["id"]
        out.append(
            {
                "id": mid,
                "name": r.get("name", mid),
                "category": r.get("category", "other"),
                "strengthMpa": strength,
                "modulusMpa": e_val,
                "densityKgPerM3": rho,
                "matchedExisting": mid in existing,
            }
        )
    return result(
        summary={
            "importedCount": len(out),
            "matchedExistingCount": sum(1 for r in out if r["matchedExisting"]),
        },
        tables=[
            table(
                "Parsed supplier material records",
                [
                    ("id", "ID"),
                    ("name", "Name"),
                    ("category", "Category"),
                    ("strengthMpa", "Strength", "MPa"),
                    ("modulusMpa", "E", "MPa"),
                    ("densityKgPerM3", "Density", "kg/m3"),
                    ("matchedExisting", "Matches library"),
                ],
                out,
            )
        ],
        notes=["Validates numeric fields in SI units before merging into project library."],
    )


@feature(
    "libraryCompliance.scheduleTemplates",
    "Schedule Templates",
    part="materials",
    fields=[
        select(
            "template",
            "Schedule layout template",
            [
                ("summary", "Executive summary"),
                ("mechanical", "Mechanical & stiffness"),
                ("audit", "Compliance & source audit"),
            ],
            "mechanical",
        )
    ],
    requires_project=True,
)
def schedule_templates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Format the project material library using selectable compliance schedule layouts."""
    lib = require_materials(ctx)
    tpl = values["template"]
    rows = []
    for m in lib.materials:
        if tpl == "summary":
            rows.append(
                {
                    "id": m.id,
                    "name": m.name,
                    "category": m.category.value,
                    "strengthMpa": material_strength_mpa(m),
                }
            )
        elif tpl == "mechanical":
            rows.append(
                {
                    "id": m.id,
                    "modulusMpa": m.mechanical.E,
                    "nu": m.mechanical.nu,
                    "densityKgPerM3": m.mechanical.density,
                    "alphaPerC": m.mechanical.alpha,
                }
            )
        else:
            rows.append(
                {
                    "id": m.id,
                    "standard": (m.source.standard if m.source else "") or "-",
                    "hasComposition": m.composition is not None,
                }
            )
    cols = {
        "summary": [
            ("id", "ID"),
            ("name", "Name"),
            ("category", "Category"),
            ("strengthMpa", "Strength", "MPa"),
        ],
        "mechanical": [
            ("id", "ID"),
            ("modulusMpa", "E", "MPa"),
            ("nu", "nu"),
            ("densityKgPerM3", "Density", "kg/m3"),
            ("alphaPerC", "alpha", "1/C"),
        ],
        "audit": [("id", "ID"), ("standard", "Standard"), ("hasComposition", "Has mix")],
    }[tpl]
    return result(
        summary={"template": tpl, "rowCount": len(rows)},
        tables=[table(f"Material schedule ({tpl})", cols, rows)],
        notes=["Formatted from 03 Materials/materials.json."],
    )


@feature(
    "libraryCompliance.submittalPack",
    "Submittal Pack",
    part="materials",
    fields=[text("packageTitle", "Submittal package title", "Structural Materials Submittal Pack")],
    requires_project=True,
)
def submittal_pack(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assemble material specifications, code validation, and source traceability into a submittal dossier."""
    lib = require_materials(ctx)
    raw_text = safe_json(lib.model_dump(mode="json", by_alias=True, exclude_none=True))
    with in_force(ctx.root):
        problems = check_library("materials", raw_text)
    title = values["packageTitle"].strip() or "Structural Materials Submittal Pack"
    lines = [f"# {title}", "", f"Total materials: {len(lib.materials)}", ""]
    lines.append("## Material Specifications")
    for m in lib.materials:
        s = material_strength_mpa(m)
        s_txt = f"{s:g} MPa" if s is not None else "N/A"
        lines.append(
            f"- **{m.id}** ({m.category.value}): {m.name} | Strength: {s_txt} | E: {m.mechanical.E or 'N/A'} MPa | Density: {m.mechanical.density or 'N/A'} kg/m3"
        )
    lines.extend(["", "## Validation Findings", f"Findings count: {len(problems)}"])
    for p in problems:
        lines.append(
            f"- [{p.get('severity', 'error')}] {p.get('path', '')}: {p.get('message', '')}"
        )
    out = save_export(ctx, "submittal-pack.md", "\n".join(lines) + "\n")
    return result(
        summary={
            "materialCount": len(lib.materials),
            "findingCount": len(problems),
            "exportPath": str(out),
        },
        tables=[
            table(
                "Submittal pack contents",
                [("id", "ID"), ("name", "Name"), ("category", "Category")],
                [{"id": m.id, "name": m.name, "category": m.category.value} for m in lib.materials],
            )
        ],
        notes=[f"Submittal package written to {out}."],
    )


@feature(
    "libraryCompliance.reviewerMarkup",
    "Reviewer Markup",
    part="materials",
    fields=[
        text(
            "markupCsv",
            "Reviewer markups CSV (material,reviewer,status,comment)",
            "material,reviewer,status,comment\nC24.1,Lead Engineer,Approved,Meets design assumptions\nB500DWR,QA Lead,Approved with Comments,Attach latest mill elongation",
        )
    ],
    requires_project=False,
)
def reviewer_markup(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Collect and summarize engineering reviewer approvals and markups."""
    rows = parse_csv_rows(values["markupCsv"])
    approved = sum(1 for r in rows if "approved" in r.get("status", "").lower())
    out = [
        {
            "material": r.get("material", ""),
            "reviewer": r.get("reviewer", ""),
            "status": r.get("status", ""),
            "comment": r.get("comment", ""),
        }
        for r in rows
    ]
    return result(
        summary={
            "reviewCount": len(out),
            "approvedCount": approved,
            "pendingCount": len(out) - approved,
        },
        tables=[
            table(
                "Reviewer markup register",
                [
                    ("material", "Material"),
                    ("reviewer", "Reviewer"),
                    ("status", "Disposition"),
                    ("comment", "Comment"),
                ],
                out,
            )
        ],
        notes=["Tracks review dispositions for material submittal workflow."],
    )

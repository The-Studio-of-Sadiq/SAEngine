"""Materials Test Data tab: sample tracking, lab reductions, curve fitting, calibration, and QA statistics."""

from __future__ import annotations

import datetime as dt
import math
from statistics import median
from typing import Any

import numpy as np

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
from saengine.features.materials_common import (
    material_strength_mpa,
    materials_or_default,
    parse_csv_rows,
    parse_numbers,
    parse_pairs,
    safe_json,
    save_export,
)
from saengine.report.clauses import in_force


@feature(
    "materialsTests.addSample",
    "Add Sample",
    part="materials",
    fields=[
        text("sampleId", "Sample identifier", "SMP-2026-01"),
        text("materialId", "Material ID", "C24.1"),
        text("batchRef", "Pour / heat / batch reference", "POUR-L1-03"),
        number("measuredMpa", "Measured strength", 27.4, unit="MPa", min=0.1),
    ],
    requires_project=False,
)
def add_sample(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Register and validate a material test sample against project material specification."""
    lib, _ = materials_or_default(ctx)
    mid = values["materialId"].strip()
    mat = lib.get(mid)
    spec = material_strength_mpa(mat) if mat else None
    ratio = (values["measuredMpa"] / spec) if spec else 1.0
    return result(
        summary={
            "sampleId": values["sampleId"].strip(),
            "materialId": mid,
            "measuredMpa": values["measuredMpa"],
            "specifiedMpa": spec if spec is not None else 0.0,
            "passesSpec": True if spec is None else values["measuredMpa"] >= spec,
        },
        tables=[
            table(
                "Registered sample",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Sample ID", "value": values["sampleId"]},
                    {"field": "Material ID", "value": mid},
                    {"field": "Batch", "value": values["batchRef"]},
                    {"field": "Measured strength [MPa]", "value": values["measuredMpa"]},
                    {
                        "field": "Specified strength [MPa]",
                        "value": spec if spec is not None else "N/A",
                    },
                    {"field": "Strength ratio", "value": ratio},
                ],
            )
        ],
        notes=["Validates sample identity against material library strength."],
    )


@feature(
    "materialsTests.sampleBatch",
    "Sample Batch",
    part="materials",
    fields=[
        text(
            "samplesCsv",
            "Samples CSV (batch,sample,strength_mpa)",
            "batch,sample,strength_mpa\nB01,S1,28.1\nB01,S2,29.4\nB02,S3,26.8\nB02,S4,27.5",
        )
    ],
    requires_project=False,
)
def sample_batch(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Group test samples by pour, heat, or delivery batch and compute batch averages."""
    rows_raw = parse_csv_rows(values["samplesCsv"])
    groups: dict[str, list[float]] = {}
    for r in rows_raw:
        try:
            b = r["batch"]
            val = float(r["strength_mpa"])
        except (KeyError, ValueError) as exc:
            raise FeatureInputError("Samples CSV requires batch,sample,strength_mpa.") from exc
        groups.setdefault(b, []).append(val)
    rows = [
        {
            "batch": b,
            "count": len(vals),
            "meanMpa": sum(vals) / len(vals),
            "minMpa": min(vals),
            "maxMpa": max(vals),
        }
        for b, vals in sorted(groups.items())
    ]
    return result(
        summary={"batchCount": len(rows), "totalSamples": sum(r["count"] for r in rows)},
        tables=[
            table(
                "Batch sample summary",
                [
                    ("batch", "Batch"),
                    ("count", "Samples"),
                    ("meanMpa", "Mean", "MPa"),
                    ("minMpa", "Min", "MPa"),
                    ("maxMpa", "Max", "MPa"),
                ],
                rows,
            )
        ],
        notes=["Aggregates test sample counts, means, and ranges by delivery or pour batch."],
    )


@feature(
    "materialsTests.sampleLocation",
    "Sample Location",
    part="materials",
    fields=[
        text(
            "locationCsv",
            "Location CSV (sample,story,zone,element)",
            "sample,story,zone,element\nS1,L1,Grid A-B/1-2,B1\nS2,L2,Core Wall,W1",
        )
    ],
    requires_project=False,
)
def sample_location(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record where samples were taken and cross-check story IDs against 06 BIM when available."""
    rows_raw = parse_csv_rows(values["locationCsv"])
    bim = ctx.raw("bim") or {}
    story_ids = {s.get("id") for s in (bim.get("stories") or []) if isinstance(s, dict)}
    rows = []
    for r in rows_raw:
        st = r.get("story", "")
        rows.append(
            {
                "sample": r.get("sample", ""),
                "story": st,
                "zone": r.get("zone", ""),
                "element": r.get("element", ""),
                "storyInBim": (st in story_ids) if story_ids else True,
            }
        )
    return result(
        summary={
            "sampleCount": len(rows),
            "matchedStories": sum(1 for r in rows if r["storyInBim"]),
        },
        tables=[
            table(
                "Sample locations",
                [
                    ("sample", "Sample"),
                    ("story", "Story"),
                    ("zone", "Zone"),
                    ("element", "Element"),
                    ("storyInBim", "In BIM"),
                ],
                rows,
            )
        ],
        notes=["Cross-checks story tags with 06 BIM/bim.json stories when a project is open."],
    )


@feature(
    "materialsTests.sampleDate",
    "Sample Date",
    part="materials",
    fields=[
        text("castDate", "Casting / sampling date (YYYY-MM-DD)", "2026-10-01"),
        text("testDate", "Testing date (YYYY-MM-DD)", "2026-10-29"),
        number("measuredMpa", "Measured strength at test date", 29.0, unit="MPa", min=0.1),
        number("target28Mpa", "Target 28-day strength", 28.0, unit="MPa", min=1.0),
    ],
    requires_project=False,
)
def sample_date(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute specimen age at testing and maturity-projected 28-day strength."""
    try:
        d1 = dt.date.fromisoformat(values["castDate"].strip())
        d2 = dt.date.fromisoformat(values["testDate"].strip())
    except ValueError as exc:
        raise FeatureInputError("Use YYYY-MM-DD format for cast and test dates.") from exc
    age = (d2 - d1).days
    if age <= 0:
        raise FeatureInputError("Test date must be after cast date.")
    # CEB-FIP exponential age factor s=0.25 (normal cement): beta_cc(t) = exp(s*(1 - sqrt(28/t)))
    beta_age = math.exp(0.25 * (1.0 - math.sqrt(28.0 / age)))
    projected_28 = values["measuredMpa"] / beta_age
    return result(
        summary={
            "ageDays": age,
            "maturityFactor": beta_age,
            "projected28DayMpa": projected_28,
            "meetsTarget28Day": projected_28 >= values["target28Mpa"],
        },
        tables=[
            table(
                "Specimen age and projection",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Age at test", "value": float(age), "unit": "days"},
                    {"parameter": "Age factor beta(t)", "value": beta_age, "unit": "-"},
                    {
                        "parameter": "Measured strength",
                        "value": values["measuredMpa"],
                        "unit": "MPa",
                    },
                    {
                        "parameter": "Projected 28-day strength",
                        "value": projected_28,
                        "unit": "MPa",
                    },
                ],
            )
        ],
        notes=["Uses normal-hardening hydration factor exp(0.25 * (1 - sqrt(28/t)))."],
    )


@feature(
    "materialsTests.testType",
    "Test Type",
    part="materials",
    fields=[
        select(
            "testKind",
            "Test method",
            [
                ("cylinder_150x300", "Concrete cylinder 150x300 mm"),
                ("cube_150", "Concrete cube 150 mm"),
                ("rebar_tensile", "Rebar tensile coupon"),
                ("steel_tensile", "Steel plate coupon"),
                ("mortar_cube_50", "Mortar cube 50 mm"),
            ],
            "cylinder_150x300",
        ),
        number("failureLoadKn", "Peak test machine load", 530.0, unit="kN", min=0.1),
    ],
    requires_project=False,
)
def test_type(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure specimen bearing area and conversion factor for standard laboratory test types."""
    specs = {
        "cylinder_150x300": (math.pi * 150.0**2 / 4.0, 1.0, "Standard cylinder (factor 1.00)"),
        "cube_150": (150.0 * 150.0, 0.80, "150 mm cube (equiv cylinder factor 0.80)"),
        "rebar_tensile": (math.pi * 16.0**2 / 4.0, 1.0, "16 mm nominal bar area"),
        "steel_tensile": (25.0 * 12.0, 1.0, "25 x 12 mm rectangular coupon"),
        "mortar_cube_50": (50.0 * 50.0, 1.0, "50 mm mortar cube"),
    }
    area_mm2, conv, desc = specs[values["testKind"]]
    raw_mpa = values["failureLoadKn"] * 1000.0 / area_mm2
    return result(
        summary={
            "areaMm2": area_mm2,
            "rawStressMpa": raw_mpa,
            "convertedStrengthMpa": raw_mpa * conv,
        },
        tables=[
            table(
                "Specimen test reduction",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Specimen type", "value": desc, "unit": "-"},
                    {"parameter": "Loaded area", "value": area_mm2, "unit": "mm2"},
                    {"parameter": "Raw stress", "value": raw_mpa, "unit": "MPa"},
                    {
                        "parameter": "Equivalent standard strength",
                        "value": raw_mpa * conv,
                        "unit": "MPa",
                    },
                ],
            )
        ],
        notes=[f"Test basis: {desc}."],
    )


@feature(
    "materialsTests.measuredValue",
    "Measured Value",
    part="materials",
    fields=[
        text("loadsKn", "Failure loads [kN] (comma-separated)", "485, 512, 498"),
        number("areaMm2", "Specimen cross-section area", 17671.5, unit="mm2", min=10.0),
    ],
    requires_project=False,
)
def measured_value(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert raw failure loads [kN] and cross-sectional area [mm2] into strengths [MPa]."""
    loads = parse_numbers(values["loadsKn"], "Failure loads")
    area = values["areaMm2"]
    rows = [
        {"specimen": i + 1, "loadKn": p, "stressMpa": p * 1000.0 / area}
        for i, p in enumerate(loads)
    ]
    stresses = [r["stressMpa"] for r in rows]
    return result(
        summary={
            "specimenCount": len(rows),
            "meanStressMpa": sum(stresses) / len(stresses),
            "minStressMpa": min(stresses),
            "maxStressMpa": max(stresses),
        },
        tables=[
            table(
                "Measured test stresses",
                [
                    ("specimen", "Specimen #"),
                    ("loadKn", "Load", "kN"),
                    ("stressMpa", "Strength", "MPa"),
                ],
                rows,
            )
        ],
        notes=["Stress [MPa] = Load [kN] * 1000 / Area [mm2]."],
    )


@feature(
    "materialsTests.expectedValue",
    "Expected Value",
    part="materials",
    fields=[
        text("materialId", "Material ID", "C24.1"),
        text("measuredMpa", "Measured test strengths [MPa]", "25.1, 26.8, 24.5"),
    ],
    requires_project=False,
)
def expected_value(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare measured strengths against the library material's specified characteristic value."""
    lib, _ = materials_or_default(ctx)
    mat = lib.get(values["materialId"].strip())
    if mat is None:
        raise FeatureInputError(f"Material {values['materialId']!r} not found.")
    spec = material_strength_mpa(mat)
    if spec is None:
        raise FeatureInputError(f"Material {mat.id!r} has no specified characteristic strength.")
    vals = parse_numbers(values["measuredMpa"], "Measured strengths")
    rows = [
        {
            "test": i + 1,
            "measuredMpa": v,
            "expectedMpa": spec,
            "marginMpa": v - spec,
            "ok": v >= spec,
        }
        for i, v in enumerate(vals)
    ]
    return result(
        summary={
            "materialId": mat.id,
            "specifiedMpa": spec,
            "meanMeasuredMpa": sum(vals) / len(vals),
            "passCount": sum(1 for r in rows if r["ok"]),
        },
        tables=[
            table(
                "Measured vs specified strength",
                [
                    ("test", "Test #"),
                    ("measuredMpa", "Measured", "MPa"),
                    ("expectedMpa", "Specified", "MPa"),
                    ("marginMpa", "Margin", "MPa"),
                    ("ok", "Meets spec"),
                ],
                rows,
            )
        ],
        notes=["Compares each test specimen directly against the library characteristic strength."],
    )


@feature(
    "materialsTests.deviation",
    "Deviation",
    part="materials",
    fields=[
        text("measuredMpa", "Measured strengths [MPa]", "28.0, 29.5, 22.1, 30.2, 27.8"),
        number("targetMpa", "Target characteristic strength", 28.0, unit="MPa", min=0.5),
        number(
            "tolerancePct",
            "Allowed negative deviation tolerance",
            10.0,
            unit="%",
            min=1.0,
            max=50.0,
        ),
    ],
    requires_project=False,
)
def deviation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute signed/percentage deviations and flag out-of-tolerance test results."""
    vals = parse_numbers(values["measuredMpa"], "Measured strengths")
    target = values["targetMpa"]
    tol = values["tolerancePct"]
    rows = []
    flagged = 0
    for i, v in enumerate(vals):
        pct = (v - target) / target * 100.0
        out_tol = pct < -tol
        if out_tol:
            flagged += 1
        rows.append(
            {
                "test": i + 1,
                "measuredMpa": v,
                "diffMpa": v - target,
                "diffPct": pct,
                "outOfTolerance": out_tol,
            }
        )
    return result(
        summary={
            "testCount": len(vals),
            "flaggedCount": flagged,
            "maxNegativePct": min(r["diffPct"] for r in rows),
        },
        tables=[
            table(
                "Test deviation analysis",
                [
                    ("test", "Test #"),
                    ("measuredMpa", "Measured", "MPa"),
                    ("diffMpa", "Diff", "MPa"),
                    ("diffPct", "Diff", "%"),
                    ("outOfTolerance", "Flagged"),
                ],
                rows,
            )
        ],
        notes=[f"Flags results more than {tol:g}% below target {target:g} MPa."],
    )


@feature(
    "materialsTests.attachCertificate",
    "Attach Certificate",
    part="materials",
    fields=[
        text("materialId", "Material ID", "A572-50"),
        text("certificateRef", "Certificate filename or ID", "CERT-A572-HEAT-441.pdf"),
    ],
    requires_project=False,
)
def attach_certificate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate and record a mill/test certificate attachment link for a material."""
    lib, _ = materials_or_default(ctx)
    mat = lib.get(values["materialId"].strip())
    return result(
        summary={
            "materialId": values["materialId"].strip(),
            "certificateRef": values["certificateRef"].strip(),
            "materialExists": mat is not None,
        },
        tables=[
            table(
                "Certificate linkage",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Material ID", "value": values["materialId"].strip()},
                    {"field": "Found in library", "value": mat is not None},
                    {"field": "Certificate reference", "value": values["certificateRef"].strip()},
                ],
            )
        ],
        notes=["Stores certificate reference metadata linked to the selected material ID."],
    )


@feature(
    "materialsTests.supplierRecord",
    "Supplier Record",
    part="materials",
    fields=[
        text("supplier", "Supplier / plant name", "Metro Batching Plant #2"),
        text("deliveryRef", "Delivery ticket / challan reference", "DLV-2026-0912"),
        text("materialId", "Material ID", "C24.1"),
        number("quantity", "Delivered quantity", 42.0, unit="m3/t", min=0.1),
    ],
    requires_project=False,
)
def supplier_record(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record supplier delivery reference and delivered lot quantity."""
    return result(
        summary={
            "supplier": values["supplier"].strip(),
            "deliveryRef": values["deliveryRef"].strip(),
            "materialId": values["materialId"].strip(),
            "quantity": values["quantity"],
        },
        tables=[
            table(
                "Supplier delivery record",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Supplier", "value": values["supplier"]},
                    {"field": "Delivery ref", "value": values["deliveryRef"]},
                    {"field": "Material ID", "value": values["materialId"]},
                    {"field": "Delivered quantity", "value": values["quantity"]},
                ],
            )
        ],
        notes=["Links supplier batch delivery ticket to material quality records."],
    )


@feature(
    "materialsTests.verifyCertificate",
    "Verify Certificate",
    part="materials",
    fields=[
        number("specifiedFyMpa", "Specified yield fy", 420.0, unit="MPa", min=100.0),
        number("actualFyMpa", "Certificate actual fy", 458.0, unit="MPa", min=100.0),
        number("actualFuMpa", "Certificate actual fu", 595.0, unit="MPa", min=100.0),
    ],
    requires_project=False,
)
def verify_certificate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check mill certificate values against code pack overstrength and fu/fy ductility limits."""
    fy_spec, fy_act, fu_act = values["specifiedFyMpa"], values["actualFyMpa"], values["actualFuMpa"]
    with in_force(ctx.root):
        mat_tbl = code_context.table("materials")
        margin = float(mat_tbl.fyActualMargin)
        fu_fy_min = float(mat_tbl.fuFyMin)
    ok_min = fy_act >= fy_spec
    ok_over = (fy_act - fy_spec) <= margin
    ok_ratio = (fu_act / fy_act) >= fu_fy_min
    return result(
        summary={
            "overstrengthMpa": fy_act - fy_spec,
            "fuFyRatio": fu_act / fy_act,
            "verified": ok_min and ok_over and ok_ratio,
        },
        tables=[
            table(
                "Certificate verification checks",
                [("check", "Check"), ("actual", "Actual"), ("limit", "Limit"), ("ok", "Pass")],
                [
                    {
                        "check": "fy_actual >= fy_spec [MPa]",
                        "actual": fy_act,
                        "limit": fy_spec,
                        "ok": ok_min,
                    },
                    {
                        "check": "Overstrength fy_act - fy_spec [MPa]",
                        "actual": fy_act - fy_spec,
                        "limit": margin,
                        "ok": ok_over,
                    },
                    {
                        "check": "fu / fy ratio",
                        "actual": fu_act / fy_act,
                        "limit": fu_fy_min,
                        "ok": ok_ratio,
                    },
                ],
            )
        ],
        notes=[
            "Checks actual yield margin and tensile-to-yield ratio against the active code pack."
        ],
    )


@feature(
    "materialsTests.archiveResults",
    "Archive Results",
    part="materials",
    fields=[
        text("archiveName", "Archive filename", "test-archive.json"),
        text("samplesMpa", "Test strengths to archive [MPa]", "28.4, 29.1, 30.2, 27.9"),
    ],
    requires_project=True,
)
def archive_results(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Archive material test statistics and records into 03 Materials/exports/."""
    vals = parse_numbers(values["samplesMpa"], "Test strengths")
    payload = {
        "count": len(vals),
        "meanMpa": sum(vals) / len(vals),
        "minMpa": min(vals),
        "maxMpa": max(vals),
        "valuesMpa": vals,
    }
    fname = values["archiveName"].strip() or "test-archive.json"
    out = save_export(ctx, fname, safe_json(payload))
    return result(
        summary={"archivedCount": len(vals), "meanMpa": payload["meanMpa"], "exportPath": str(out)},
        tables=[
            table(
                "Archived test series",
                [("index", "Sample #"), ("strengthMpa", "Strength", "MPa")],
                [{"index": i + 1, "strengthMpa": v} for i, v in enumerate(vals)],
            )
        ],
        notes=[f"Test archive written to {out}."],
    )


@feature(
    "materialsTests.importLabFile",
    "Import Lab File",
    part="materials",
    fields=[
        text(
            "utmCsv",
            "UTM CSV (strain,stress_mpa)",
            "strain,stress_mpa\n0.0000,0\n0.0005,100\n0.0010,200\n0.0017,340\n0.0020,348\n0.0150,352\n0.0600,445\n0.1200,468",
        )
    ],
    requires_project=False,
)
def import_lab_file(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Import raw stress-strain CSV output from a universal testing machine and extract key parameters."""
    rows_raw = parse_csv_rows(values["utmCsv"])
    pts = []
    for r in rows_raw:
        try:
            pts.append((float(r["strain"]), float(r["stress_mpa"])))
        except (KeyError, ValueError) as exc:
            raise FeatureInputError("UTM CSV requires strain and stress_mpa columns.") from exc
    pts.sort(key=lambda p: p[0])
    # Secant elastic slope from first non-zero segment
    slopes = [s / e for e, s in pts if 0.0 < e <= 0.002]
    e_est = sum(slopes) / len(slopes) if slopes else 0.0
    peak_s = max(s for _, s in pts)
    return result(
        summary={
            "pointCount": len(pts),
            "initialModulusMpa": e_est,
            "peakStressMpa": peak_s,
            "maxStrain": pts[-1][0],
        },
        tables=[
            table(
                "Imported UTM stress-strain points",
                [("strain", "Strain", "-"), ("stressMpa", "Stress", "MPa")],
                [{"strain": round(e, 6), "stressMpa": s} for e, s in pts],
            )
        ],
        notes=["Extracts initial elastic slope (for strain <= 0.002) and peak engineering stress."],
    )


@feature(
    "materialsTests.rawStressStrain",
    "Raw Stress Strain",
    part="materials",
    fields=[
        text(
            "pairs",
            "Raw strain, stress [MPa] pairs",
            "0, 0\n0.0004, 82\n0.0008, 161\n0.0012, 239\n0.0018, 342\n0.010, 355",
        )
    ],
    requires_project=False,
)
def raw_stress_strain(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect uncalibrated stress-strain data points and compute incremental tangent moduli."""
    pts = sorted(parse_pairs(values["pairs"], "Raw stress-strain"), key=lambda p: p[0])
    rows = []
    for i, (e, s) in enumerate(pts):
        et = (s - pts[i - 1][1]) / (e - pts[i - 1][0]) if i > 0 and e > pts[i - 1][0] else 0.0
        rows.append({"point": i + 1, "strain": round(e, 6), "stressMpa": s, "incrementalEtMpa": et})
    return result(
        summary={
            "pointCount": len(rows),
            "peakStressMpa": max(p[1] for p in pts),
            "maxStrain": pts[-1][0],
        },
        tables=[
            table(
                "Uncalibrated stress-strain series",
                [
                    ("point", "#"),
                    ("strain", "Strain", "-"),
                    ("stressMpa", "Stress", "MPa"),
                    ("incrementalEtMpa", "Increment Et", "MPa"),
                ],
                rows,
            )
        ],
        notes=["Incremental tangent modulus Et = d_sigma / d_eps between successive readings."],
    )


@feature(
    "materialsTests.automatedCurveFit",
    "Automated Curve Fit",
    part="materials",
    fields=[
        text(
            "pairs",
            "Empirical strain, stress [MPa] pairs",
            "0.0005, 100\n0.0010, 200\n0.0020, 345\n0.010, 365\n0.040, 425\n0.080, 460",
        )
    ],
    requires_project=False,
)
def automated_curve_fit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Fit an elastic-plastic bilinear constitutive model (E0, fy, E_sh) to empirical data."""
    pts = sorted(parse_pairs(values["pairs"], "Curve fit pairs"), key=lambda p: p[0])
    elastic = [(e, s) for e, s in pts if e > 0 and e <= 0.0025]
    if not elastic:
        elastic = pts[:2]
    e0 = sum(s / e for e, s in elastic if e > 0) / len(elastic)
    plastic = [(e, s) for e, s in pts if e > 0.0025]
    if len(plastic) >= 2:
        xs = np.array([p[0] for p in plastic])
        ys = np.array([p[1] for p in plastic])
        slope, intercept = np.polyfit(xs, ys, 1)
        e_sh = max(0.0, float(slope))
        fy_fit = float(intercept + e_sh * (intercept / max(e0 - e_sh, 1.0)))
    else:
        e_sh = 0.0
        fy_fit = max(s for _, s in elastic)
    rows = []
    sq_err = 0.0
    for e, s in pts:
        pred = min(e0 * e, fy_fit + e_sh * max(0.0, e - fy_fit / e0))
        sq_err += (s - pred) ** 2
        rows.append(
            {"strain": round(e, 6), "measuredMpa": s, "fittedMpa": pred, "residualMpa": s - pred}
        )
    rmse = math.sqrt(sq_err / len(pts))
    return result(
        summary={
            "fittedModulusMpa": e0,
            "fittedYieldMpa": fy_fit,
            "fittedHardeningMpa": e_sh,
            "rmseMpa": rmse,
        },
        tables=[
            table(
                "Bilinear constitutive fit",
                [
                    ("strain", "Strain", "-"),
                    ("measuredMpa", "Measured", "MPa"),
                    ("fittedMpa", "Fitted", "MPa"),
                    ("residualMpa", "Residual", "MPa"),
                ],
                rows,
            )
        ],
        notes=["Least-squares bilinear fit over elastic and strain-hardening regimes."],
    )


@feature(
    "materialsTests.machineCalibration",
    "Machine Calibration",
    part="materials",
    fields=[
        text("rawLoadsKn", "Raw load cell readings [kN]", "100.0, 250.0, 500.0, 750.0"),
        number("gainFactor", "Calibration slope gain a", 1.012, min=0.8, max=1.2),
        number("zeroOffsetKn", "Zero-offset bias b", -1.5, unit="kN"),
    ],
    requires_project=False,
)
def machine_calibration(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply linear load-cell calibration F_cal = a * F_raw + b and report adjustment errors."""
    raw = parse_numbers(values["rawLoadsKn"], "Raw loads")
    a, b = values["gainFactor"], values["zeroOffsetKn"]
    rows = []
    for i, r in enumerate(raw):
        cal = a * r + b
        err_pct = (cal - r) / r * 100.0 if r != 0 else 0.0
        rows.append({"reading": i + 1, "rawKn": r, "calibratedKn": cal, "correctionPct": err_pct})
    return result(
        summary={
            "readingCount": len(rows),
            "maxCorrectionPct": max(abs(r["correctionPct"]) for r in rows),
        },
        tables=[
            table(
                "Load-cell calibration adjustments",
                [
                    ("reading", "#"),
                    ("rawKn", "Raw", "kN"),
                    ("calibratedKn", "Calibrated", "kN"),
                    ("correctionPct", "Correction", "%"),
                ],
                rows,
            )
        ],
        notes=[f"Linear calibration curve: F_cal = {a:.4f} * F_raw + ({b:+.2f} kN)."],
    )


@feature(
    "materialsTests.meanDeviation",
    "Mean Deviation",
    part="materials",
    fields=[text("valuesMpa", "Sample test values [MPa]", "29.2, 31.0, 28.5, 32.1, 30.4, 29.8")],
    requires_project=False,
)
def mean_deviation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute mean, median, standard deviation, CoV, and 95% confidence interval."""
    vals = parse_numbers(values["valuesMpa"], "Test values")
    n = len(vals)
    mean = sum(vals) / n
    std = math.sqrt(sum((x - mean) ** 2 for x in vals) / (n - 1)) if n > 1 else 0.0
    cov = (std / mean * 100.0) if mean > 0 else 0.0
    ci95 = 1.96 * std / math.sqrt(n)
    return result(
        summary={
            "sampleCount": n,
            "meanMpa": mean,
            "stdDevMpa": std,
            "covPercent": cov,
            "medianMpa": median(vals),
        },
        tables=[
            table(
                "Sample batch statistics",
                [("statistic", "Statistic"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"statistic": "Count n", "value": float(n), "unit": "-"},
                    {"statistic": "Sample mean", "value": mean, "unit": "MPa"},
                    {"statistic": "Sample std dev s", "value": std, "unit": "MPa"},
                    {"statistic": "Coefficient of variation", "value": cov, "unit": "%"},
                    {"statistic": "95% CI half-width", "value": ci95, "unit": "MPa"},
                    {
                        "statistic": "Minimum / Maximum",
                        "value": f"{min(vals):.2f} / {max(vals):.2f}",
                        "unit": "MPa",
                    },
                ],
            )
        ],
        notes=["Sample standard deviation uses Bessel (n - 1) denominator."],
    )


@feature(
    "materialsTests.characteristicValue",
    "Characteristic Value",
    part="materials",
    fields=[
        text("valuesMpa", "Sample test strengths [MPa]", "31.2, 33.4, 30.8, 34.1, 32.0, 29.9"),
        checkbox("knownSigma", "Population standard deviation assumed known", False),
    ],
    requires_project=False,
)
def characteristic_value(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute 5th-percentile characteristic strength fk using normal or Student-t tolerance factor."""
    vals = parse_numbers(values["valuesMpa"], "Sample strengths")
    n = len(vals)
    if n < 2:
        raise FeatureInputError(
            "At least 2 test values are required to compute characteristic strength."
        )
    mean = sum(vals) / n
    std = math.sqrt(sum((x - mean) ** 2 for x in vals) / (n - 1))
    # Approximate unknown-sigma 5% fractile k_n (75% confidence): 1.645 + 1.8 / sqrt(n - 1)
    k = 1.645 if values["knownSigma"] else (1.645 + 1.8 / math.sqrt(n - 1))
    fk = mean - k * std
    return result(
        summary={
            "sampleCount": n,
            "meanMpa": mean,
            "stdDevMpa": std,
            "factorK": k,
            "characteristicMpa": fk,
        },
        tables=[
            table(
                "Characteristic 5th-percentile calculation",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Sample mean", "value": mean, "unit": "MPa"},
                    {"parameter": "Sample std dev s", "value": std, "unit": "MPa"},
                    {"parameter": "Fractile multiplier k", "value": k, "unit": "-"},
                    {"parameter": "Characteristic strength fk", "value": fk, "unit": "MPa"},
                ],
            )
        ],
        notes=["Unknown-sigma k_n accounts for finite-sample uncertainty at 75% confidence."],
    )


@feature(
    "materialsTests.outlierFilter",
    "Outlier Filter",
    part="materials",
    fields=[
        text("valuesMpa", "Test strengths [MPa]", "30.1, 31.4, 29.8, 18.2, 30.9, 32.0, 30.5"),
        number("zThreshold", "Modified Z-score cutoff", 2.5, min=1.5, max=4.0),
    ],
    requires_project=False,
)
def outlier_filter(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detect anomalous test results using robust MAD modified Z-score filtering."""
    vals = parse_numbers(values["valuesMpa"], "Test values")
    med = median(vals)
    abs_devs = [abs(v - med) for v in vals]
    mad = median(abs_devs) or 1e-6
    cutoff = values["zThreshold"]
    rows = []
    kept = []
    for i, v in enumerate(vals):
        mz = 0.6745 * (v - med) / mad
        is_out = abs(mz) > cutoff
        if not is_out:
            kept.append(v)
        rows.append({"sample": i + 1, "valueMpa": v, "modifiedZ": mz, "outlier": is_out})
    return result(
        summary={
            "totalCount": len(vals),
            "outlierCount": len(vals) - len(kept),
            "rawMeanMpa": sum(vals) / len(vals),
            "filteredMeanMpa": (sum(kept) / len(kept)) if kept else 0.0,
        },
        tables=[
            table(
                "Robust MAD outlier screening",
                [
                    ("sample", "Sample #"),
                    ("valueMpa", "Value", "MPa"),
                    ("modifiedZ", "Modified Z"),
                    ("outlier", "Outlier"),
                ],
                rows,
            )
        ],
        notes=["Iglewicz & Hoaglin robust MAD Z-score = 0.6745 * (x - median) / MAD."],
    )


@feature(
    "materialsTests.batchAcceptance",
    "Batch Acceptance",
    part="materials",
    fields=[
        text("valuesMpa", "Batch test results [MPa]", "28.5, 29.8, 30.2, 27.4, 31.0"),
        number("specifiedMpa", "Specified characteristic strength", 28.0, unit="MPa", min=1.0),
        number(
            "minIndividualOffsetMpa", "Allowed negative individual offset", 3.5, unit="MPa", min=0.0
        ),
    ],
    requires_project=False,
)
def batch_acceptance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate batch acceptance against mean and minimum individual strength specifications."""
    vals = parse_numbers(values["valuesMpa"], "Batch test results")
    spec = values["specifiedMpa"]
    mean = sum(vals) / len(vals)
    min_lim = spec - values["minIndividualOffsetMpa"]
    accepted = mean >= spec and min(vals) >= min_lim
    return result(
        summary={
            "batchCount": len(vals),
            "batchMeanMpa": mean,
            "batchMinMpa": min(vals),
            "accepted": accepted,
        },
        tables=[
            table(
                "Batch acceptance summary",
                [
                    ("criterion", "Criterion"),
                    ("actualMpa", "Actual", "MPa"),
                    ("limitMpa", "Limit", "MPa"),
                    ("ok", "Pass"),
                ],
                [
                    {
                        "criterion": "Batch mean >= specified",
                        "actualMpa": mean,
                        "limitMpa": spec,
                        "ok": mean >= spec,
                    },
                    {
                        "criterion": "Minimum specimen >= spec - offset",
                        "actualMpa": min(vals),
                        "limitMpa": min_lim,
                        "ok": min(vals) >= min_lim,
                    },
                ],
            )
        ],
        notes=[
            "Requires both batch mean >= specified strength and all specimens above lower limit."
        ],
    )


@feature(
    "materialsTests.conformanceScore",
    "Conformance Score",
    part="materials",
    fields=[
        text("valuesMpa", "Test strengths [MPa]", "29.5, 31.2, 30.1, 28.9, 32.0"),
        number("specifiedMpa", "Specified strength", 28.0, unit="MPa", min=1.0),
        checkbox("certificatesVerified", "All mill/lab certificates verified", True),
    ],
    requires_project=False,
)
def conformance_score(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute a 0-100 material quality index combining margin, variability, and documentation."""
    vals = parse_numbers(values["valuesMpa"], "Test strengths")
    spec = values["specifiedMpa"]
    mean = sum(vals) / len(vals)
    std = math.sqrt(sum((x - mean) ** 2 for x in vals) / (len(vals) - 1)) if len(vals) > 1 else 0.0
    cov = std / mean if mean > 0 else 1.0
    margin_pts = min(40.0, max(0.0, 25.0 + 15.0 * (mean - spec) / max(0.15 * spec, 1.0)))
    consistency_pts = min(40.0, max(0.0, 40.0 * (1.0 - cov / 0.20)))
    doc_pts = 20.0 if values["certificatesVerified"] else 0.0
    score = margin_pts + consistency_pts + doc_pts
    return result(
        summary={
            "conformanceScore": score,
            "meanMpa": mean,
            "covPercent": cov * 100.0,
            "rating": "Excellent"
            if score >= 85
            else ("Satisfactory" if score >= 70 else "Needs review"),
        },
        tables=[
            table(
                "Quality conformance index breakdown",
                [("component", "Score component"), ("points", "Points"), ("maxPoints", "Max")],
                [
                    {
                        "component": "Strength margin vs spec",
                        "points": margin_pts,
                        "maxPoints": 40.0,
                    },
                    {
                        "component": "Statistical consistency (CoV)",
                        "points": consistency_pts,
                        "maxPoints": 40.0,
                    },
                    {"component": "Certificate verification", "points": doc_pts, "maxPoints": 20.0},
                ],
            )
        ],
        notes=["Composite 0-100 quality assurance index."],
    )


@feature(
    "materialsTests.qaSummary",
    "QA Summary",
    part="materials",
    fields=[
        text("valuesMpa", "Sample strengths [MPa]", "29.0, 30.4, 28.2, 31.1, 29.8"),
        number("specifiedMpa", "Specified strength", 28.0, unit="MPa", min=1.0),
        checkbox("writeReport", "Write QA summary Markdown to project exports", True),
    ],
    requires_project=False,
)
def qa_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile a comprehensive material quality assurance summary report."""
    vals = parse_numbers(values["valuesMpa"], "Sample strengths")
    spec = values["specifiedMpa"]
    mean = sum(vals) / len(vals)
    std = math.sqrt(sum((x - mean) ** 2 for x in vals) / (len(vals) - 1)) if len(vals) > 1 else 0.0
    fk = mean - 1.645 * std
    pass_cnt = sum(1 for v in vals if v >= spec)
    export_path = ""
    if values["writeReport"] and ctx.root is not None:
        md = (
            "# Materials Quality Assurance Summary\n\n"
            f"- Sample count: {len(vals)}\n"
            f"- Specified strength: {spec:.2f} MPa\n"
            f"- Sample mean: {mean:.2f} MPa\n"
            f"- Sample std dev: {std:.2f} MPa\n"
            f"- 5th-percentile characteristic strength: {fk:.2f} MPa\n"
            f"- Specimens >= specified: {pass_cnt} / {len(vals)}\n"
        )
        export_path = str(save_export(ctx, "qa-summary.md", md))
    notes = ["Summarizes mean, scatter, characteristic fractile, and pass rate."]
    if export_path:
        notes.append(f"Report written to {export_path}.")
    return result(
        summary={
            "sampleCount": len(vals),
            "meanMpa": mean,
            "characteristicMpa": fk,
            "passRatePercent": pass_cnt / len(vals) * 100.0,
        },
        tables=[
            table(
                "QA summary metrics",
                [("metric", "Metric"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"metric": "Specified strength", "value": spec, "unit": "MPa"},
                    {"metric": "Sample mean", "value": mean, "unit": "MPa"},
                    {"metric": "Standard deviation", "value": std, "unit": "MPa"},
                    {"metric": "Estimated 5th percentile fk", "value": fk, "unit": "MPa"},
                ],
            )
        ],
        notes=notes,
    )

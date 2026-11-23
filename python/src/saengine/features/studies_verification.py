"""Studies Verification - benchmark catalog, numerical checks and evidence tracking."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import zipfile

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.studies_common import numbers, records, write_text


@feature(
    "studiesVerification.verificationSets",
    "Verification Sets",
    part="settings",
    fields=[
        text(
            "sets",
            "Verification set definitions",
            '[{"name":"Analysis","cases":["A36","C24.1"]},{"name":"Hydraulics","cases":["H1"]}]',
        )
    ],
    requires_project=False,
)
def verification_sets(ctx: FeatureContext, values: dict) -> dict:
    """Validate named verification sets and count their distinct benchmark identifiers."""
    sets = records(values["sets"], "verification sets")
    output = []
    for item in sets:
        cases = item.get("cases", [])
        if not isinstance(cases, list):
            raise FeatureInputError("Each verification set needs a list of case identifiers.")
        output.append(
            {
                "name": str(item.get("name", "Set")),
                "caseCount": len(cases),
                "identifiers": ", ".join(str(case) for case in cases),
            }
        )
    return result(
        summary={"setCount": len(output), "caseCount": sum(row["caseCount"] for row in output)},
        tables=[
            table(
                "Verification sets",
                [("name", "Set"), ("caseCount", "Cases"), ("identifiers", "Identifiers")],
                output,
            )
        ],
        notes=["Sets define traceable groupings; this tool does not run solver cases."],
    )


@feature(
    "studiesVerification.benchmarkCases",
    "Benchmark Cases",
    part="settings",
    fields=[text("category", "Category filter", "analysis")],
    requires_project=False,
)
def benchmark_cases(ctx: FeatureContext, values: dict) -> dict:
    """List the engine's published verification cases in a selected category."""
    from saengine.verification.cases import CASES

    query = values["category"].strip().casefold()
    rows = [
        {
            "id": case.id,
            "title": case.title,
            "category": case.category,
            "reference": case.description,
            "fast": case.fast,
        }
        for case in CASES
        if not query or query in case.category.casefold()
    ]
    return result(
        summary={"caseCount": len(rows), "categories": len({row["category"] for row in rows})},
        tables=[
            table(
                "Available benchmark cases",
                [
                    ("id", "Case id"),
                    ("title", "Title"),
                    ("category", "Category"),
                    ("fast", "Fast case"),
                ],
                rows,
            )
        ],
        notes=[
            "The engine's verification catalog is read directly; case listing does not execute analyses."
        ],
    )


@feature(
    "studiesVerification.regressionTests",
    "Regression Tests",
    part="settings",
    fields=[
        text("baseline", "Baseline result JSON", '{"displacementMm":12.5,"reactionKn":100}'),
        text("current", "Current result JSON", '{"displacementMm":12.6,"reactionKn":100.1}'),
        number("relativeTolerance", "Relative tolerance", 0.02, min=0, max=1),
        number("absoluteTolerance", "Absolute tolerance", 0.1, min=0),
    ],
)
def regression_tests(ctx: FeatureContext, values: dict) -> dict:
    """Compare current numeric result fields to a baseline using combined absolute-relative tolerance."""
    baseline, current = json.loads(values["baseline"]), json.loads(values["current"])
    if not isinstance(baseline, dict) or not isinstance(current, dict):
        raise FeatureInputError("Baseline and current results must be JSON objects.")
    rows = []
    for key in sorted(baseline.keys() | current.keys()):
        if key not in baseline or key not in current:
            rows.append(
                {
                    "quantity": key,
                    "status": "missing field",
                    "baseline": baseline.get(key),
                    "current": current.get(key),
                }
            )
            continue
        try:
            ref, actual = float(baseline[key]), float(current[key])
        except (TypeError, ValueError):
            rows.append(
                {
                    "quantity": key,
                    "status": "unchanged" if baseline[key] == current[key] else "changed text",
                    "baseline": baseline[key],
                    "current": current[key],
                }
            )
            continue
        error = abs(actual - ref)
        limit = values["absoluteTolerance"] + values["relativeTolerance"] * abs(ref)
        rows.append(
            {
                "quantity": key,
                "status": "pass" if error <= limit else "regression",
                "baseline": ref,
                "current": actual,
                "absoluteError": error,
                "tolerance": limit,
            }
        )
    return result(
        summary={
            "quantityCount": len(rows),
            "regressions": sum(row["status"] == "regression" for row in rows),
            "allPass": all(row["status"] in ("pass", "unchanged") for row in rows),
        },
        tables=[
            table(
                "Regression comparison",
                [
                    ("quantity", "Quantity"),
                    ("status", "Status"),
                    ("baseline", "Baseline"),
                    ("current", "Current"),
                    ("absoluteError", "Absolute error"),
                    ("tolerance", "Tolerance"),
                ],
                rows,
            )
        ],
        notes=[
            "Numeric pass limit is absoluteTolerance + relativeTolerance × |baseline|; strings must match exactly."
        ],
    )


@feature(
    "studiesVerification.handCalculations",
    "Hand Calculations",
    part="settings",
    fields=[
        number("span", "Simply supported span", 6, unit="m", min=0.01),
        number("load", "Uniform line load", 12, unit="kN/m", min=0),
        number("elasticModulus", "Elastic modulus", 200000, unit="MPa", min=0.001),
        number("inertia", "Second moment of area", 8e8, unit="mm⁴", min=0.001),
    ],
    requires_project=False,
)
def hand_calculations(ctx: FeatureContext, values: dict) -> dict:
    """Calculate reference maximum moment, support reaction and elastic midspan deflection for a simple beam."""
    span_m, w = values["span"], values["load"]
    moment = w * span_m**2 / 8
    reaction = w * span_m / 2
    span_mm = span_m * 1000
    deflection = 5 * (w / 1000) * span_mm**4 / (384 * values["elasticModulus"] * values["inertia"])
    return result(
        summary={
            "maximumMomentKnM": moment,
            "supportReactionKn": reaction,
            "midspanDeflectionMm": deflection,
        },
        notes=[
            "Closed-form Euler–Bernoulli elastic solution for a simply supported prismatic beam under a full-span uniform load; shear deformation and self-weight are omitted."
        ],
    )


@feature(
    "studiesVerification.codeExamples",
    "Code Examples",
    part="settings",
    fields=[
        text(
            "examples",
            "Example input-output records",
            '[{"name":"beam reaction","input":20,"factor":6,"expected":120},{"name":"stress","input":250,"factor":1,"expected":250}]',
        )
    ],
    requires_project=False,
)
def code_examples(ctx: FeatureContext, values: dict) -> dict:
    """Recalculate simple reference examples as explicit input-times-factor checks."""
    rows = records(values["examples"], "code examples")
    output = []
    for row in rows:
        try:
            actual = float(row["input"]) * float(row["factor"])
            expected = float(row["expected"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Every example needs numeric input, factor and expected values."
            ) from error
        output.append(
            {
                "name": row.get("name", "Example"),
                "calculated": actual,
                "expected": expected,
                "difference": actual - expected,
                "pass": math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9),
            }
        )
    return result(
        summary={"exampleCount": len(output), "passed": sum(row["pass"] for row in output)},
        tables=[
            table(
                "Example checks",
                [
                    ("name", "Example"),
                    ("calculated", "Calculated"),
                    ("expected", "Expected"),
                    ("difference", "Difference"),
                    ("pass", "Passes"),
                ],
                output,
            )
        ],
        notes=[
            "The check evaluates each declared multiplication; these examples are inputs for review, not executable source code."
        ],
    )


@feature(
    "studiesVerification.resultComparison",
    "Result Comparison",
    part="settings",
    fields=[
        text(
            "results",
            "Result pairs",
            '[{"quantity":"moment","reference":120,"model":118},{"quantity":"deflection","reference":10,"model":10.5}]',
        )
    ],
    requires_project=False,
)
def result_comparison(ctx: FeatureContext, values: dict) -> dict:
    """Calculate signed and relative differences for model results and independent references."""
    rows = records(values["results"], "result pairs")
    output = []
    for row in rows:
        try:
            ref, model = float(row["reference"]), float(row["model"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each result pair needs numeric reference and model values."
            ) from error
        output.append(
            {
                "quantity": row.get("quantity", "Quantity"),
                "reference": ref,
                "model": model,
                "difference": model - ref,
                "relativeErrorPercent": 100 * (model - ref) / abs(ref) if ref else None,
            }
        )
    return result(
        summary={
            "quantityCount": len(output),
            "meanAbsoluteRelativeErrorPercent": sum(
                abs(row["relativeErrorPercent"])
                for row in output
                if row["relativeErrorPercent"] is not None
            )
            / max(1, sum(row["relativeErrorPercent"] is not None for row in output)),
        },
        tables=[
            table(
                "Model to reference comparison",
                [
                    ("quantity", "Quantity"),
                    ("reference", "Reference"),
                    ("model", "Model"),
                    ("difference", "Model minus reference"),
                    ("relativeErrorPercent", "Relative error", "%"),
                ],
                output,
            )
        ],
        notes=[
            "Differences are model minus reference; relative error is blank for a zero reference."
        ],
    )


@feature(
    "studiesVerification.unitConsistency",
    "Unit Consistency",
    part="settings",
    fields=[
        text(
            "quantities",
            "Quantities with units",
            '[{"name":"length","value":1200,"unit":"mm","expected":"m"},{"name":"force","value":2,"unit":"kN","expected":"N"}]',
        )
    ],
    requires_project=False,
)
def unit_consistency(ctx: FeatureContext, values: dict) -> dict:
    """Convert declared quantities between common structural SI units and flag unsupported pairs."""
    factors = {
        "m": ("length", 1.0),
        "mm": ("length", 1e-3),
        "cm": ("length", 1e-2),
        "kN": ("force", 1e3),
        "N": ("force", 1.0),
        "MPa": ("stress", 1e6),
        "kPa": ("stress", 1e3),
        "Pa": ("stress", 1.0),
        "kg": ("mass", 1.0),
        "t": ("mass", 1000.0),
    }
    rows = []
    for item in records(values["quantities"], "unit quantities"):
        source, target = item.get("unit"), item.get("expected")
        if (
            source not in factors
            or target not in factors
            or factors[source][0] != factors[target][0]
        ):
            rows.append(
                {
                    "name": item.get("name", "Quantity"),
                    "status": "incompatible or unsupported unit pair",
                    "converted": None,
                }
            )
            continue
        converted = float(item["value"]) * factors[source][1] / factors[target][1]
        rows.append(
            {
                "name": item.get("name", "Quantity"),
                "status": "consistent dimension",
                "converted": converted,
            }
        )
    return result(
        summary={
            "quantityCount": len(rows),
            "unitProblems": sum(row["converted"] is None for row in rows),
        },
        tables=[
            table(
                "Unit checks",
                [("name", "Quantity"), ("status", "Status"), ("converted", "Converted value")],
                rows,
            )
        ],
        notes=[
            "Conversions are limited to explicit common length, force, stress and mass units; no silent dimensional inference is performed."
        ],
    )


@feature(
    "studiesVerification.solverValidity",
    "Solver Validity",
    part="fem",
    fields=[
        text(
            "equilibrium",
            "Force and reaction balance pairs",
            '[{"case":"D","appliedKn":100,"reactionKn":99.8},{"case":"W","appliedKn":80,"reactionKn":80.1}]',
        ),
        number("relativeTolerance", "Relative equilibrium tolerance", 0.01, min=0, max=0.5),
    ],
    requires_project=False,
)
def solver_validity(ctx: FeatureContext, values: dict) -> dict:
    """Check supplied global force resultants against reactions within a relative tolerance."""
    rows = []
    for item in records(values["equilibrium"], "equilibrium resultants"):
        try:
            load, reaction = float(item["appliedKn"]), float(item["reactionKn"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each equilibrium pair needs appliedKn and reactionKn."
            ) from error
        residual = reaction - load
        ratio = abs(residual) / max(abs(load), 1e-12)
        rows.append(
            {
                "case": item.get("case", "Case"),
                "appliedKn": load,
                "reactionKn": reaction,
                "residualKn": residual,
                "relativeResidual": ratio,
                "passes": ratio <= values["relativeTolerance"],
            }
        )
    return result(
        summary={
            "caseCount": len(rows),
            "equilibriumPassCount": sum(row["passes"] for row in rows),
        },
        tables=[
            table(
                "Force equilibrium",
                [
                    ("case", "Case"),
                    ("appliedKn", "Applied", "kN"),
                    ("reactionKn", "Reaction", "kN"),
                    ("residualKn", "Residual", "kN"),
                    ("relativeResidual", "Relative residual"),
                    ("passes", "Passes"),
                ],
                rows,
            )
        ],
        notes=[
            "Checks only global vertical resultant balance as supplied; energy balance, stiffness conditioning and local equilibrium require separate checks."
        ],
    )


@feature(
    "studiesVerification.meshConvergence",
    "Mesh Convergence",
    part="fem",
    fields=[
        text(
            "refinements",
            "Mesh response sequence",
            '[{"elements":20,"response":10.2},{"elements":80,"response":10.05},{"elements":320,"response":10.01}]',
        ),
        number("tolerancePercent", "Last-pair change limit", 2, unit="%", min=0),
    ],
)
def mesh_convergence(ctx: FeatureContext, values: dict) -> dict:
    """Compute successive response changes and decide whether the last mesh pair meets a tolerance."""
    samples = records(values["refinements"], "mesh refinements")
    try:
        vals = [(int(row["elements"]), float(row["response"])) for row in samples]
    except (KeyError, TypeError, ValueError) as error:
        raise FeatureInputError(
            "Each mesh refinement needs element count and numeric response."
        ) from error
    if len(vals) < 2 or any(vals[i + 1][0] <= vals[i][0] for i in range(len(vals) - 1)):
        raise FeatureInputError("Provide at least two meshes in strictly increasing element count.")
    changes = [
        {
            "fromElements": vals[i][0],
            "toElements": vals[i + 1][0],
            "responseChangePercent": 100
            * (vals[i + 1][1] - vals[i][1])
            / max(abs(vals[i + 1][1]), 1e-12),
        }
        for i in range(len(vals) - 1)
    ]
    last = abs(changes[-1]["responseChangePercent"])
    return result(
        summary={
            "lastChangePercent": last,
            "meetsTolerance": last <= values["tolerancePercent"],
            "meshCount": len(vals),
        },
        tables=[
            table(
                "Mesh refinement changes",
                [
                    ("fromElements", "From elements"),
                    ("toElements", "To elements"),
                    ("responseChangePercent", "Response change", "%"),
                ],
                changes,
            )
        ],
        notes=[
            "Successive relative changes are measured against the finer mesh response; convergence is assessed for only the supplied quantity."
        ],
    )


@feature(
    "studiesVerification.signOff",
    "Sign-Off",
    part="settings",
    fields=[
        text("reviewer", "Reviewer", "Engineer"),
        text("evidence", "Evidence item names", "Model, calculations, independent review"),
        checkbox("approved", "Approve this verification record", False),
    ],
    requires_project=False,
)
def sign_off(ctx: FeatureContext, values: dict) -> dict:
    """Create a sign-off record only when the reviewer identifies evidence and approves it."""
    evidence = [x.strip() for x in values["evidence"].split(",") if x.strip()]
    if not values["reviewer"].strip() or not evidence:
        raise FeatureInputError("Enter a reviewer and at least one evidence item.")
    return result(
        summary={
            "reviewer": values["reviewer"].strip(),
            "approved": values["approved"],
            "evidenceCount": len(evidence),
            "status": "approved" if values["approved"] else "pending review",
        },
        tables=[
            table(
                "Sign-off evidence",
                [("item", "Evidence item")],
                [{"item": item} for item in evidence],
            )
        ],
        notes=[
            "This records the supplied review decision; it is not an electronic signature or a substitute for the project's approval process."
        ],
    )


@feature(
    "studiesVerification.auditTrail",
    "Audit Trail",
    part="settings",
    fields=[number("maximumFiles", "Maximum project files to hash", 500, min=1, max=10000)],
)
def audit_trail(ctx: FeatureContext, values: dict) -> dict:
    """Build a read-only list of project file sizes, timestamps and SHA-256 digests."""
    if ctx.root is None or not ctx.root.is_dir():
        raise FeatureInputError("Open a project folder to inspect its audit trail.")
    rows = []
    for path in sorted(ctx.root.rglob("*")):
        if not path.is_file() or any(
            part.startswith(".") for part in path.relative_to(ctx.root).parts
        ):
            continue
        if len(rows) >= int(values["maximumFiles"]):
            break
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            stat = path.stat()
        except OSError:
            continue
        rows.append(
            {
                "path": path.relative_to(ctx.root).as_posix(),
                "sizeBytes": stat.st_size,
                "modifiedNs": stat.st_mtime_ns,
                "sha256": digest,
            }
        )
    return result(
        summary={
            "hashedFileCount": len(rows),
            "fileLimitReached": len(rows) >= int(values["maximumFiles"]),
        },
        tables=[
            table(
                "Project file audit",
                [
                    ("path", "Relative path"),
                    ("sizeBytes", "Size", "byte"),
                    ("modifiedNs", "Modified time", "ns"),
                    ("sha256", "SHA-256"),
                ],
                rows,
            )
        ],
        notes=[
            "This inventory is read-only and records current file hashes; it does not establish author identity or a trusted timestamp."
        ],
    )


@feature(
    "studiesVerification.certification",
    "Certification",
    part="settings",
    fields=[
        text("scope", "Verification scope", "Linear frame analysis"),
        text("standard", "Reference method description", "Independent elastic solution"),
        text("results", "Result records", '[{"quantity":"reaction","value":100,"unit":"kN"}]'),
    ],
    requires_project=False,
)
def certification(ctx: FeatureContext, values: dict) -> dict:
    """Create a dated verification certificate record from explicit scope and result data."""
    output = {
        "scope": values["scope"].strip(),
        "referenceMethod": values["standard"].strip(),
        "results": records(values["results"], "certificate results"),
        "issuedDate": __import__("datetime").date.today().isoformat(),
    }
    if not output["scope"] or not output["referenceMethod"]:
        raise FeatureInputError("Enter the verification scope and reference method.")
    return result(
        summary={
            "scope": output["scope"],
            "quantityCount": len(output["results"]),
            "issuedDate": output["issuedDate"],
        },
        tables=[
            table(
                "Certified result quantities",
                [(key, key.replace("_", " ").title()) for key in output["results"][0]],
                output["results"],
            )
        ],
        notes=[
            "This is a structured certificate record for engineering review; it is not a regulatory approval or cryptographic signature."
        ],
    )


@feature(
    "studiesVerification.benchmarkLibrary",
    "Benchmark Library",
    part="settings",
    fields=[text("search", "Search case title or id", "beam")],
    requires_project=False,
)
def benchmark_library(ctx: FeatureContext, values: dict) -> dict:
    """Search the verification benchmark library by case identifier or title."""
    from saengine.verification.cases import CASES

    query = values["search"].strip().casefold()
    cases = [
        case for case in CASES if query in case.id.casefold() or query in case.title.casefold()
    ]
    rows = [
        {
            "id": case.id,
            "title": case.title,
            "category": case.category,
            "description": case.description,
        }
        for case in cases
    ]
    return result(
        summary={"matchedCases": len(rows), "availableCases": len(CASES)},
        tables=[
            table(
                "Benchmark library search",
                [
                    ("id", "Case"),
                    ("title", "Title"),
                    ("category", "Category"),
                    ("description", "Reference problem"),
                ],
                rows,
            )
        ],
        notes=["Searches the engine's curated verification case catalog."],
    )


@feature(
    "studiesVerification.standardCases",
    "Standard Cases",
    part="settings",
    fields=[text("ids", "Case identifiers", "A36,C24.1")],
    requires_project=False,
)
def standard_cases(ctx: FeatureContext, values: dict) -> dict:
    """Validate selected identifiers against the engine verification case catalog."""
    from saengine.verification.cases import BY_ID

    ids = [item.strip() for item in values["ids"].split(",") if item.strip()]
    unknown = [item for item in ids if item not in BY_ID]
    if unknown:
        raise FeatureInputError("Unknown verification case identifier(s): " + ", ".join(unknown))
    rows = [
        {
            "id": key,
            "title": BY_ID[key].title,
            "category": BY_ID[key].category,
            "fast": BY_ID[key].fast,
        }
        for key in ids
    ]
    return result(
        summary={"selectedCases": len(rows), "fastCases": sum(row["fast"] for row in rows)},
        tables=[
            table(
                "Selected standard cases",
                [("id", "Case"), ("title", "Title"), ("category", "Category"), ("fast", "Fast")],
                rows,
            )
        ],
        notes=[
            "The IDs refer to the engine's verification case definitions; selection alone does not execute them."
        ],
    )


@feature(
    "studiesVerification.customCases",
    "Custom Cases",
    part="settings",
    fields=[
        text(
            "cases",
            "Custom reference cases",
            '[{"name":"Beam reaction","quantity":"reaction","model":100,"reference":99.8,"unit":"kN"}]',
        )
    ],
    requires_project=False,
)
def custom_cases(ctx: FeatureContext, values: dict) -> dict:
    """Validate user-defined reference cases and calculate their reference differences."""
    rows = records(values["cases"], "custom cases")
    output = []
    for row in rows:
        try:
            model, reference = float(row["model"]), float(row["reference"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each custom case needs numeric model and reference results."
            ) from error
        output.append(
            {
                "case": row.get("name", "Custom case"),
                "quantity": row.get("quantity", "Response"),
                "model": model,
                "reference": reference,
                "error": model - reference,
                "unit": row.get("unit", ""),
            }
        )
    return result(
        summary={
            "customCaseCount": len(output),
            "meanAbsoluteError": sum(abs(row["error"]) for row in output) / len(output),
        },
        tables=[
            table(
                "Custom reference cases",
                [
                    ("case", "Case"),
                    ("quantity", "Quantity"),
                    ("model", "Model"),
                    ("reference", "Reference"),
                    ("error", "Difference"),
                    ("unit", "Unit"),
                ],
                output,
            )
        ],
        notes=[
            "The feature stores a comparison record; the custom analytical reference remains the engineer's responsibility."
        ],
    )


@feature(
    "studiesVerification.compareCurves",
    "Compare Curves",
    part="settings",
    fields=[
        text("reference", "Reference curve ordinates", "0,10,20,30,20,10,0"),
        text("model", "Model curve ordinates", "0,9.8,19.5,29.6,19.7,10.2,0"),
    ],
    requires_project=False,
)
def compare_curves(ctx: FeatureContext, values: dict) -> dict:
    """Align two equally sampled curves and compute pointwise absolute differences."""
    reference, model = (
        numbers(values["reference"], "reference curve"),
        numbers(values["model"], "model curve"),
    )
    if len(reference) != len(model):
        raise FeatureInputError("Reference and model curves must have the same number of samples.")
    rows = [
        {"sample": i + 1, "reference": a, "model": b, "difference": b - a}
        for i, (a, b) in enumerate(zip(reference, model, strict=True))
    ]
    return result(
        summary={
            "sampleCount": len(rows),
            "maximumAbsoluteDifference": max(abs(row["difference"]) for row in rows),
            "meanAbsoluteDifference": sum(abs(row["difference"]) for row in rows) / len(rows),
        },
        tables=[
            table(
                "Curve comparison",
                [
                    ("sample", "Sample"),
                    ("reference", "Reference"),
                    ("model", "Model"),
                    ("difference", "Model minus reference"),
                ],
                rows,
            )
        ],
        notes=["Samples are paired by index; no interpolation or time alignment is applied."],
    )


@feature(
    "studiesVerification.errorMetrics",
    "Error Metrics",
    part="settings",
    fields=[
        text(
            "pairs",
            "Model-reference pairs",
            '[{"model":10.2,"reference":10},{"model":8.9,"reference":9}]',
        )
    ],
    requires_project=False,
)
def error_metrics(ctx: FeatureContext, values: dict) -> dict:
    """Calculate mean absolute, root mean square, maximum and nonzero-reference percentage errors."""
    pairs = records(values["pairs"], "error pairs")
    try:
        differences = [(float(row["model"]), float(row["reference"])) for row in pairs]
    except (KeyError, TypeError, ValueError) as error:
        raise FeatureInputError("Each pair needs numeric model and reference fields.") from error
    errors = [model - ref for model, ref in differences]
    mape = [
        abs(error / ref) * 100 for error, (_, ref) in zip(errors, differences, strict=True) if ref
    ]
    return result(
        summary={
            "meanAbsoluteError": sum(abs(e) for e in errors) / len(errors),
            "rootMeanSquareError": math.sqrt(sum(e * e for e in errors) / len(errors)),
            "maximumAbsoluteError": max(abs(e) for e in errors),
            "meanAbsolutePercentError": sum(mape) / len(mape) if mape else None,
        },
        notes=[
            "MAPE excludes zero-reference values; all other error metrics retain the supplied response units."
        ],
    )


@feature(
    "studiesVerification.toleranceSetup",
    "Tolerance Setup",
    part="settings",
    fields=[
        number("relative", "Relative tolerance", 0.02, min=0, max=1),
        number("absolute", "Absolute tolerance", 0.1, min=0),
        text("quantity", "Quantity name", "displacement"),
        text("unit", "Quantity unit", "mm"),
    ],
    requires_project=False,
)
def tolerance_setup(ctx: FeatureContext, values: dict) -> dict:
    """Create an explicit absolute-relative tolerance rule for one response quantity."""
    return result(
        summary={
            "quantity": values["quantity"],
            "unit": values["unit"],
            "relativeTolerance": values["relative"],
            "absoluteTolerance": values["absolute"],
        },
        tables=[
            table(
                "Acceptance rule",
                [("term", "Term"), ("value", "Value")],
                [
                    {"term": "Absolute allowance", "value": values["absolute"]},
                    {"term": "Relative allowance", "value": values["relative"]},
                    {"term": "Combined limit", "value": "absolute + relative × |reference|"},
                ],
            )
        ],
        notes=["Combined acceptance limit is absoluteTolerance + relativeTolerance × |reference|."],
    )


@feature(
    "studiesVerification.verificationReport",
    "Verification Report",
    part="settings",
    fields=[
        text(
            "cases",
            "Case result records",
            '[{"id":"A36","pass":true,"error":0.5},{"id":"C24.1","pass":false,"error":2.1}]',
        )
    ],
    requires_project=False,
)
def verification_report(ctx: FeatureContext, values: dict) -> dict:
    """Summarize passed and failed verification records and their absolute error values."""
    rows = records(values["cases"], "verification case results")
    output = []
    for row in rows:
        try:
            error = abs(float(row.get("error", 0)))
        except (TypeError, ValueError) as exc:
            raise FeatureInputError("Verification errors must be numeric.") from exc
        output.append(
            {"id": row.get("id", "Case"), "pass": bool(row.get("pass")), "absoluteError": error}
        )
    return result(
        summary={
            "caseCount": len(output),
            "passed": sum(row["pass"] for row in output),
            "failed": sum(not row["pass"] for row in output),
            "maximumAbsoluteError": max((row["absoluteError"] for row in output), default=0),
        },
        tables=[
            table(
                "Verification summary",
                [("id", "Case"), ("pass", "Passes"), ("absoluteError", "Absolute error")],
                output,
            )
        ],
        notes=["Aggregates supplied case outcomes without re-running their models."],
    )


@feature(
    "studiesVerification.exportResults",
    "Export Results",
    part="settings",
    fields=[
        text(
            "rows", "Result rows", '[{"case":"A36","response":"moment","value":120,"unit":"kN m"}]'
        ),
        text("filename", "CSV filename", "verification-results"),
    ],
)
def export_results(ctx: FeatureContext, values: dict) -> dict:
    """Export verification result rows as UTF-8 CSV under the project Exports folder."""
    rows = records(values["rows"], "verification results")
    if ctx.root is None:
        raise FeatureInputError("Open a project to save verification results.")
    columns = list(dict.fromkeys(key for row in rows for key in row))
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    name = (
        "".join(char for char in values["filename"] if char.isalnum() or char in "-_")
        or "verification-results"
    )
    path = write_text(ctx, f"11 Exports/{name}.csv", buffer.getvalue())
    return result(
        summary={"rowCount": len(rows), "outputPath": path},
        notes=[f"Verification results exported to {path}."],
    )


@feature(
    "studiesVerification.versionHistory",
    "Version History",
    part="settings",
    fields=[number("limit", "Versions to show", 50, min=1, max=500)],
)
def version_history(ctx: FeatureContext, values: dict) -> dict:
    """Read the project's version history and show changed-file counts by revision."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to inspect its version history.")
    from saengine.project.versions import list_versions

    history = list_versions(ctx.root, limit=int(values["limit"]))
    rows = [
        {
            "version": item.get("version"),
            "date": item.get("date"),
            "author": item.get("author"),
            "message": item.get("message"),
            "changedFiles": len(item.get("changes", [])),
        }
        for item in history.get("versions", [])
    ]
    return result(
        summary={"versionCount": len(rows), "branch": history.get("branch", "")},
        tables=[
            table(
                "Project revisions",
                [
                    ("version", "Version"),
                    ("date", "Date"),
                    ("author", "Author"),
                    ("message", "Message"),
                    ("changedFiles", "Changed files"),
                ],
                rows,
            )
        ],
        notes=["Reads the project's local version history; no revision is created or restored."],
    )


@feature(
    "studiesVerification.evidencePack",
    "Evidence Pack",
    part="settings",
    fields=[
        text(
            "files",
            "Evidence paths relative to project",
            "01 Soil Report/soil-report.json,02 Project Settings/project-settings.json",
        ),
        text("filename", "Evidence archive", "verification-evidence"),
    ],
)
def evidence_pack(ctx: FeatureContext, values: dict) -> dict:
    """Package selected project evidence files with hashes and relative paths in a ZIP archive."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to package evidence files.")
    selected = [
        item.strip().replace("\\", "/") for item in values["files"].split(",") if item.strip()
    ]
    manifest, safe_paths = [], []
    for relative in selected:
        target = (ctx.root / relative).resolve()
        if ctx.root.resolve() not in target.parents or not target.is_file():
            raise FeatureInputError(f"Evidence file does not exist inside the project: {relative}")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        manifest.append({"path": relative, "sha256": digest, "sizeBytes": target.stat().st_size})
        safe_paths.append((target, relative))
    name = (
        "".join(char for char in values["filename"] if char.isalnum() or char in "-_")
        or "verification-evidence"
    )
    target = ctx.root / "11 Exports" / f"{name}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source, relative in safe_paths:
            archive.write(source, f"evidence/{relative}")
        archive.writestr("manifest.json", json.dumps({"files": manifest}, indent=2) + "\n")
    rel = target.relative_to(ctx.root).as_posix()
    return result(
        summary={"fileCount": len(manifest), "archivePath": rel},
        tables=[
            table(
                "Evidence manifest",
                [("path", "Project path"), ("sizeBytes", "Size", "byte"), ("sha256", "SHA-256")],
                manifest,
            )
        ],
        notes=[f"Evidence files and a readable checksum manifest are packaged in {rel}."],
    )


@feature(
    "studiesVerification.traceability",
    "Traceability",
    part="settings",
    fields=[
        text(
            "requirements",
            "Requirement-to-evidence mappings",
            '[{"requirement":"R-01","description":"Check member forces","evidence":["A36","beam worksheet"]},{"requirement":"R-02","description":"Check material data","evidence":["materials.json"]}]',
        )
    ],
    requires_project=False,
)
def traceability(ctx: FeatureContext, values: dict) -> dict:
    """Build a requirement coverage matrix from supplied requirement and evidence identifiers."""
    rows = records(values["requirements"], "traceability mappings")
    output = []
    for row in rows:
        evidence = row.get("evidence", [])
        if not isinstance(evidence, list):
            raise FeatureInputError("Each requirement's evidence field must be a list.")
        output.append(
            {
                "requirement": row.get("requirement", "Requirement"),
                "description": row.get("description", ""),
                "evidenceCount": len(evidence),
                "evidence": ", ".join(map(str, evidence)),
                "covered": bool(evidence),
            }
        )
    return result(
        summary={
            "requirementCount": len(output),
            "coveredCount": sum(row["covered"] for row in output),
            "uncoveredCount": sum(not row["covered"] for row in output),
        },
        tables=[
            table(
                "Requirement traceability",
                [
                    ("requirement", "Requirement"),
                    ("description", "Description"),
                    ("evidenceCount", "Evidence count"),
                    ("evidence", "Evidence"),
                    ("covered", "Covered"),
                ],
                output,
            )
        ],
        notes=[
            "Coverage is based on non-empty evidence references; the referenced evidence is not verified by this matrix."
        ],
    )

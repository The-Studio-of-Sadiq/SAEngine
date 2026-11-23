"""Soil Report laboratory and field-test reductions with traceable sample tables."""

from __future__ import annotations

import math
from statistics import median
from typing import Any

from saengine.features import number, result, select, table, text
from saengine.features.soil_feature_utils import (
    FeatureInputError,
    common_fields,
    register_tab,
    require_report,
    result_rows,
    sample_rows,
    samples,
    save_json,
    spt_rows,
)


def _fields(fid: str) -> list[Any]:
    if fid == "soilTests.pointLoadIndex":
        return [
            number("loadN", "Failure load [N]", 2500.0, unit="N", min=0.01),
            number("diameterMm", "Equivalent core diameter [mm]", 50.0, unit="mm", min=1),
        ]
    if fid == "soilTests.brazilianTensile":
        return [
            number("loadN", "Failure load [N]", 1800.0, unit="N", min=0.01),
            number("diameterMm", "Disc diameter [mm]", 50.0, unit="mm", min=1),
            number("thicknessMm", "Disc thickness [mm]", 25.0, unit="mm", min=1),
        ]
    if fid == "soilTests.corePhotos":
        return [
            *common_fields(fid),
            text("photoPaths", "Project-relative photo paths (one per line)", ""),
        ]
    if fid == "soilTests.chainOfCustody":
        return [*common_fields(fid), text("history", "Date, custodian, action rows", "")]
    if fid in {"soilTests.outlierFlag", "soilTests.repeatTestAdvice"}:
        return [
            *common_fields(fid),
            select(
                "parameter",
                "Result to review",
                [
                    ("cu", "Undrained strength cu"),
                    ("phi", "Friction angle φ'"),
                    ("moisture", "Water content"),
                    ("unitWeight", "Unit weight"),
                ],
                "cu",
            ),
        ]
    return common_fields(fid)


def _needs_project(fid: str) -> bool:
    return fid not in {
        "soilTests.pointLoadIndex",
        "soilTests.brazilianTensile",
        "soilTests.chainOfCustody",
    }


def _handle(fid: str, ctx: Any, values: dict[str, Any]) -> dict[str, Any]:
    if fid == "soilTests.pointLoadIndex":
        de = values["diameterMm"]
        is_mpa = values["loadN"] / de**2
        f50 = (de / 50) ** 0.45
        return result(
            summary={
                "pointLoadIs50Mpa": is_mpa * f50,
                "pointLoadIsMpa": is_mpa,
                "sizeCorrectionFactor": f50,
            },
            tables=[
                table(
                    "Point-load index reduction",
                    [("parameter", "Parameter"), ("value", "Value")],
                    [
                        {"parameter": "Failure load [N]", "value": values["loadN"]},
                        {"parameter": "Equivalent diameter [mm]", "value": de},
                        {"parameter": "Is [MPa]", "value": is_mpa},
                        {"parameter": "Is(50) [MPa]", "value": is_mpa * f50},
                    ],
                )
            ],
            notes=[
                "Is = P/De² and Is(50) = (De/50)^0.45·Is; this size correction is an empirical index, not a direct UCS measurement."
            ],
        )
    if fid == "soilTests.brazilianTensile":
        strength = 2 * values["loadN"] / (math.pi * values["diameterMm"] * values["thicknessMm"])
        return result(
            summary={"indirectTensileStrengthMpa": strength},
            tables=[
                table(
                    "Brazilian disc reduction",
                    [("parameter", "Parameter"), ("value", "Value")],
                    [
                        {"parameter": "Failure load [N]", "value": values["loadN"]},
                        {"parameter": "Disc diameter [mm]", "value": values["diameterMm"]},
                        {"parameter": "Disc thickness [mm]", "value": values["thicknessMm"]},
                        {"parameter": "Indirect tensile strength [MPa]", "value": strength},
                    ],
                )
            ],
            notes=[
                "σt = 2P/(πDt), with load in N and dimensions in mm so the result is MPa; the standard diametral loading geometry is assumed."
            ],
        )
    if fid == "soilTests.chainOfCustody":
        lines = [line.strip() for line in values["history"].splitlines() if line.strip()]
        if not lines:
            raise FeatureInputError("Enter custody history rows as date, custodian, action.")
        rows = []
        for line_number, line in enumerate(lines, 1):
            bits = [part.strip() for part in line.split(",", 2)]
            if len(bits) != 3 or not all(bits):
                raise FeatureInputError(
                    f"Custody row {line_number} must contain date, custodian and action."
                )
            rows.append({"date": bits[0], "custodian": bits[1], "action": bits[2]})
        return result(
            summary={
                "custodyEventsCount": len(rows),
                "firstCustodian": rows[0]["custodian"],
                "lastCustodian": rows[-1]["custodian"],
            },
            tables=[
                table(
                    "Sample chain of custody",
                    [
                        ("date", "Date / time"),
                        ("custodian", "Custodian"),
                        ("action", "Transfer or storage action"),
                    ],
                    rows,
                )
            ],
            notes=[
                "Chronological custody history supplied in the panel; link the record to the laboratory sample number before issue."
            ],
        )

    report = require_report(ctx)
    records = samples(report)
    if fid == "soilTests.sampleRegister":
        rows = sample_rows(report)
        if not rows:
            raise FeatureInputError("No soil samples are recorded in the boreholes.")
        return result_rows(
            "Soil sample register",
            [
                ("borehole", "Borehole"),
                ("sample", "Sample"),
                ("type", "Type"),
                ("depthM", "Depth", "m"),
                ("depthToM", "Depth to", "m"),
                ("recoveryPct", "Recovery", "%"),
                ("moisturePct", "Moisture", "%"),
                ("unitWeightKnM3", "Unit weight", "kN/m³"),
                ("issues", "Record issues"),
            ],
            rows,
            summary={"samplesCount": len(rows), "boreholesCount": len(report.boreholes)},
            notes=["Sample numbers and intervals are shown as stored in the borehole records."],
        )
    if fid == "soilTests.corePhotos":
        paths = [
            p.strip().replace("\\", "/") for p in values["photoPaths"].splitlines() if p.strip()
        ]
        if not paths:
            raise FeatureInputError(
                "Enter one or more project-relative core-photo paths; paths must point to files inside the project."
            )
        root = ctx.root.resolve()
        rows = []
        for item in paths:
            path = (root / item).resolve()
            if root not in path.parents or not path.is_file():
                raise FeatureInputError(
                    f"Core photo {item!r} is missing or outside the project folder."
                )
            rows.append(
                {"path": item, "bytes": path.stat().st_size, "extension": path.suffix.lower()}
            )
        export = save_json(ctx, "01 Soil Report/exports/core-photo-register.json", rows)
        return result(
            summary={"photosCount": len(rows), "exportPath": export},
            tables=[
                table(
                    "Core photo attachments",
                    [
                        ("path", "Project-relative path"),
                        ("bytes", "File size", "bytes"),
                        ("extension", "Format"),
                    ],
                    rows,
                )
            ],
            notes=[
                f"Photo register written to {export}. Images remain in their project folders; the soil schema has no image-blob field."
            ],
        )
    if fid == "soilTests.scheduleTests":
        rows = []
        for bh, sample, i in records:
            kind = next(
                (layer.soilType for layer in bh.layers if layer.top <= sample.depth < layer.bottom),
                None,
            )
            tests = ["water content", "specific gravity"]
            if kind in {"clay", "silt", "organic"}:
                tests.extend(
                    ["Atterberg limits", "consolidation if compressible", "UU or CU triaxial"]
                )
            elif kind in {"sand", "gravel"}:
                tests.extend(["particle-size distribution", "drained direct shear"])
            elif kind == "rock":
                tests.extend(["UCS", "point-load index", "Brazilian tensile where relevant"])
            rows.append(
                {
                    "borehole": bh.id,
                    "sample": sample.number or f"S{i + 1}",
                    "depthM": sample.depth / 1000,
                    "soilType": kind or "unclassified",
                    "recommendedTests": "; ".join(tests),
                }
            )
        if not rows:
            raise FeatureInputError("No samples are available for a laboratory test programme.")
        return result_rows(
            "Recommended laboratory programme",
            [
                ("borehole", "Borehole"),
                ("sample", "Sample"),
                ("depthM", "Depth", "m"),
                ("soilType", "Soil type"),
                ("recommendedTests", "Suggested programme"),
            ],
            rows,
            summary={
                "samplesCount": len(rows),
                "recommendationsCount": sum(row["recommendedTests"].count(";") + 1 for row in rows),
            },
            notes=[
                "Recommendations are based on logged soil type and support characterization; select the final tests to match the design questions, sample quality and investigation specification."
            ],
        )
    if fid == "soilTests.atterbergLimits":
        rows = []
        for bh, sample, i in records:
            if sample.liquidLimit is not None or sample.plasticLimit is not None:
                pi = (
                    0.0
                    if sample.nonPlastic
                    else (
                        sample.liquidLimit - sample.plasticLimit
                        if sample.liquidLimit is not None and sample.plasticLimit is not None
                        else None
                    )
                )
                li = (
                    (sample.moisture - sample.plasticLimit) / pi
                    if pi and sample.moisture is not None and sample.plasticLimit is not None
                    else None
                )
                rows.append(
                    {
                        "borehole": bh.id,
                        "sample": sample.number or f"S{i + 1}",
                        "depthM": sample.depth / 1000,
                        "liquidLimitPct": sample.liquidLimit,
                        "plasticLimitPct": sample.plasticLimit,
                        "plasticityIndexPct": pi,
                        "liquidityIndex": li,
                    }
                )
        if not rows:
            raise FeatureInputError("No liquid or plastic limit results are recorded.")
        return result_rows(
            "Atterberg limits",
            [
                ("borehole", "Borehole"),
                ("sample", "Sample"),
                ("depthM", "Depth", "m"),
                ("liquidLimitPct", "LL", "%"),
                ("plasticLimitPct", "PL", "%"),
                ("plasticityIndexPct", "PI", "%"),
                ("liquidityIndex", "Liquidity index"),
            ],
            rows,
            summary={"testedSamplesCount": len(rows)},
            notes=[
                "PI = LL − PL; the liquidity index uses the sample moisture content and is omitted when one input is unavailable."
            ],
        )
    if fid in {
        "soilTests.directShear",
        "soilTests.triaxialSuite",
        "soilTests.consolidationTest",
        "soilTests.particleSizeAnalysis",
        "soilTests.ucsTest",
    }:
        from saengine.soil import lab

        rows = []
        for bh, sample, i in records:
            common = {
                "borehole": bh.id,
                "sample": sample.number or f"S{i + 1}",
                "depthM": sample.depth / 1000,
            }
            if fid == "soilTests.directShear" and sample.directShear:
                c, phi, how = lab.direct_shear(sample.directShear)
                rows.append(
                    {
                        **common,
                        "cohesionKpa": c,
                        "phiDeg": phi,
                        "specimensCount": len(sample.directShear.specimens),
                        "basis": how,
                    }
                )
            elif fid == "soilTests.triaxialSuite" and sample.triaxial:
                tri = lab.triaxial(sample.triaxial)
                if tri:
                    rows.append(
                        {
                            **common,
                            "testType": sample.triaxial.type,
                            "cuKpa": tri["cu"],
                            "cohesionKpa": tri["c"],
                            "phiDeg": tri["phi"],
                            "effective": tri["effective"],
                            "basis": tri["how"],
                        }
                    )
            elif fid == "soilTests.consolidationTest" and sample.consolidation:
                out = lab.consolidation(sample.consolidation)
                rows.append(
                    {
                        **common,
                        "e0": out["e0"],
                        "Cc": out["Cc"],
                        "Cr": out["Cr"],
                        "preconsolidationKpa": out["preconsolidation"],
                        "cvM2PerYear": sample.consolidation.cv,
                        "basis": str(out["how"]),
                    }
                )
            elif fid == "soilTests.particleSizeAnalysis" and sample.grading:
                out = lab.grading_summary(sample.grading)
                rows.append({**common, **out})
            elif fid == "soilTests.ucsTest" and sample.ucs:
                rows.append(
                    {
                        **common,
                        "quKpa": sample.ucs.qu,
                        "cuKpa": sample.ucs.qu / 2,
                        "failureStrainPct": sample.ucs.strain,
                    }
                )
        if not rows:
            label = {
                "soilTests.directShear": "direct-shear",
                "soilTests.triaxialSuite": "triaxial",
                "soilTests.consolidationTest": "consolidation",
                "soilTests.particleSizeAnalysis": "grain-size",
                "soilTests.ucsTest": "UCS",
            }[fid]
            raise FeatureInputError(f"No {label} test records are stored in the samples.")
        columns = [("borehole", "Borehole"), ("sample", "Sample"), ("depthM", "Depth", "m")]
        columns.extend(
            (
                key,
                key.replace("Kpa", " [kPa]")
                .replace("M2PerYear", " [m²/year]")
                .replace("Pct", " [%]")
                .replace("Deg", " [°]"),
            )
            for key in rows[0]
            if key not in {"borehole", "sample", "depthM"}
        )
        return result_rows(
            "Laboratory test reduction",
            columns,
            rows,
            summary={"testResultsCount": len(rows)},
            notes=[
                "Reported parameters are taken from the logged test groups or reduced by the soil laboratory engine."
            ],
        )
    if fid == "soilTests.sptCorrelations":
        rows = spt_rows(report)
        if not rows:
            raise FeatureInputError("No SPT results are recorded in the boreholes.")
        return result_rows(
            "SPT corrected values",
            [
                ("borehole", "Borehole"),
                ("depthM", "Depth", "m"),
                ("fieldN", "Field N"),
                ("energyPct", "Energy", "%"),
                ("n60", "N60"),
                ("n160", "(N1)60"),
                ("effectiveStressKpa", "Effective stress", "kPa"),
                ("issues", "Issues"),
            ],
            rows,
            summary={
                "sptTestsCount": len(rows),
                "meanN60": sum(row["n60"] for row in rows) / len(rows),
            },
            notes=[
                "Corrections use the project SPT practice, report hammer energy and recorded correction factors."
            ],
        )
    if fid in {"soilTests.phiFromSpt", "soilTests.cuFromSpt"}:
        output = []
        for bh in report.boreholes:
            prof = __import__("saengine.features.soil_feature_utils", fromlist=["profile"]).profile(
                report, bh
            )
            for point in prof.spt:
                layer = point.layer
                if layer is None:
                    continue
                granular = layer.behaviour == "granular"
                if (fid.endswith("phiFromSpt") and granular) or (
                    fid.endswith("cuFromSpt") and layer.behaviour == "cohesive"
                ):
                    output.append(
                        {
                            "borehole": bh.id,
                            "depthM": point.depth,
                            "fieldN": point.n,
                            "n60": point.n60,
                            "n160": point.n160,
                            "soilType": layer.soil_type,
                            "correlatedPhiDeg": layer.phi if granular else None,
                            "correlatedCuKpa": layer.cu if layer.behaviour == "cohesive" else None,
                            "source": layer.sources.get("phi" if granular else "cu"),
                        }
                    )
        if not output:
            raise FeatureInputError(
                "No compatible granular or cohesive SPT intervals are available for this correlation."
            )
        title = (
            "Friction-angle correlation from SPT"
            if fid.endswith("phiFromSpt")
            else "Undrained strength correlation from SPT"
        )
        return result_rows(
            title,
            [
                ("borehole", "Borehole"),
                ("depthM", "Depth", "m"),
                ("fieldN", "Field N"),
                ("n60", "N60"),
                ("n160", "(N1)60"),
                ("soilType", "Soil type"),
                ("correlatedPhiDeg", "φ'", "°"),
                ("correlatedCuKpa", "cu", "kPa"),
                ("source", "Correlation basis"),
            ],
            output,
            summary={"intervalsCount": len(output)},
            notes=[
                "The resolved profile correlation follows the engine's documented SPT correlations; use measured laboratory values where available."
            ],
        )
    if fid in {"soilTests.moistureContent", "soilTests.specificGravity"}:
        key, title = (
            ("moisture", "Water content")
            if fid.endswith("moistureContent")
            else ("specificGravity", "Specific gravity")
        )
        rows = [
            {
                "borehole": bh.id,
                "sample": s.number or f"S{i + 1}",
                "depthM": s.depth / 1000,
                "value": getattr(s, key),
            }
            for bh, s, i in records
            if getattr(s, key) is not None
        ]
        if not rows:
            raise FeatureInputError(f"No {title.lower()} results are recorded in the samples.")
        values_list = [row["value"] for row in rows]
        return result_rows(
            f"{title} test results",
            [
                ("borehole", "Borehole"),
                ("sample", "Sample"),
                ("depthM", "Depth", "m"),
                ("value", title, "%" if key == "moisture" else ""),
            ],
            rows,
            summary={
                "testedSamplesCount": len(rows),
                "meanValue": sum(values_list) / len(values_list),
            },
            notes=["Values are listed as measured in the Soil Report sample records."],
        )
    if fid == "soilTests.outlierFlag":
        parameter = values["parameter"]
        vals = [
            (bh, s, i, getattr(s, parameter))
            for bh, s, i in records
            if getattr(s, parameter, None) is not None
        ]
        if len(vals) < 3:
            raise FeatureInputError(
                "At least three samples with the selected result are needed for a robust outlier screen."
            )
        center = median(v for _, _, _, v in vals)
        mad = median(abs(v - center) for _, _, _, v in vals)
        if mad == 0:
            flagged = [abs(v - center) > 1e-9 for _, _, _, v in vals]
        else:
            flagged = [abs(0.6745 * (v - center) / mad) > 3.5 for _, _, _, v in vals]
        rows = [
            {
                "borehole": bh.id,
                "sample": s.number or f"S{i + 1}",
                "depthM": s.depth / 1000,
                "value": value,
                "robustZ": None if mad == 0 else 0.6745 * (value - center) / mad,
                "flagged": flag,
            }
            for (bh, s, i, value), flag in zip(vals, flagged, strict=True)
        ]
        return result_rows(
            "Robust test-result outlier screen",
            [
                ("borehole", "Borehole"),
                ("sample", "Sample"),
                ("depthM", "Depth", "m"),
                ("value", parameter),
                ("robustZ", "Modified z"),
                ("flagged", "Review flag"),
            ],
            rows,
            summary={
                "samplesCount": len(rows),
                "outliersCount": sum(flagged),
                "medianValue": center,
            },
            notes=[
                "Modified z = 0.6745·(x−median)/MAD; values beyond 3.5 are review flags, not automatic exclusions."
            ],
        )
    if fid == "soilTests.repeatTestAdvice":
        rows = []
        for bh, sample, i in records:
            issues = list(sample.issues)
            if sample.recovery is not None and sample.recovery < 50:
                issues.append("low sample recovery")
            if sample.nonPlastic and (
                sample.liquidLimit is not None or sample.plasticLimit is not None
            ):
                issues.append("non-plastic flag conflicts with Atterberg values")
            parameter = values["parameter"]
            if getattr(sample, parameter, None) is None:
                issues.append(f"selected result {parameter} is missing")
            if issues:
                rows.append(
                    {
                        "borehole": bh.id,
                        "sample": sample.number or f"S{i + 1}",
                        "depthM": sample.depth / 1000,
                        "reason": "; ".join(issues),
                        "advice": "Review sample condition and repeat the affected test if material remains.",
                    }
                )
        return result_rows(
            "Sample retest review",
            [
                ("borehole", "Borehole"),
                ("sample", "Sample"),
                ("depthM", "Depth", "m"),
                ("reason", "Reason for review"),
                ("advice", "Advice"),
            ],
            rows,
            summary={"samplesForReviewCount": len(rows)},
            notes=[
                "Retest suggestions flag missing, inconsistent or low-recovery records; engineering judgement determines whether a repeat test is possible and representative."
            ],
        )
    raise FeatureInputError(
        "The requested laboratory operation needs a matching test record in a sample."
    )


register_tab("soilTests", _handle, requires_project=_needs_project, fields=_fields)

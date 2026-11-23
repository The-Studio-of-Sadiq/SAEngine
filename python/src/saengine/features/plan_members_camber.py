"""Beam Camber ribbon: elastic deflection estimates and fabrication callouts."""

from __future__ import annotations

import json
import math

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.plan_common import export_csv, profile, selected_members


def _beams(ctx: FeatureContext, ids: str) -> list[dict]:
    rows = selected_members(profile(ctx)[1], ids)
    beams = [r for r in rows if r["category"] == "beam"]
    if len(beams) != len(rows):
        raise FeatureInputError("Camber calculations require beam members only.")
    return beams


def _uniform_deflection_mm(
    w_kn_per_m: float, length_m: float, elastic_mpa: float, inertia_mm4: float
) -> float:
    w_n_per_mm = w_kn_per_m
    L = length_m * 1000
    return 5 * w_n_per_mm * L**4 / (384 * elastic_mpa * inertia_mm4)


@feature(
    "planMembersCamber.camberValue",
    "Camber Value",
    part="floorPlan",
    fields=[
        text("beamId", "Beam id", "B1"),
        number("deadLoadKnPerM", "Unfactored dead line load", 5, unit="kN/m", min=0),
        number("elasticModulusMpa", "Elastic modulus", 25000, unit="MPa", min=1),
        number("inertiaMm4", "Moment of inertia", 1e9, unit="mm⁴", min=1),
        number("camberFraction", "Camber fraction of dead-load deflection", 1, min=0, max=2),
    ],
)
def camber_value(ctx: FeatureContext, values: dict) -> dict:
    """Calculate a dead-load beam deflection and a matching upward camber target."""
    beam = _beams(ctx, values["beamId"])[0]
    delta = _uniform_deflection_mm(
        values["deadLoadKnPerM"], beam["lengthM"], values["elasticModulusMpa"], values["inertiaMm4"]
    )
    return result(
        summary={
            "beamId": beam["id"],
            "spanM": beam["lengthM"],
            "deadLoadDeflectionMm": delta,
            "camberMm": delta * values["camberFraction"],
        },
        notes=[
            "Simply supported prismatic beam under uniform dead load; elastic small-deflection response, with E and I supplied by the engineer."
        ],
    )


@feature(
    "planMembersCamber.naturalCamber",
    "Natural Camber",
    part="floorPlan",
    fields=[
        text("beamId", "Beam id", "B1"),
        number("measuredCamberMm", "Measured upward sweep", 8, unit="mm"),
        number("deadLoadDeflectionMm", "Predicted dead-load deflection", 12, unit="mm", min=0),
    ],
)
def natural_camber(ctx: FeatureContext, values: dict) -> dict:
    """Compare measured initial upward sweep with predicted dead-load deflection."""
    beam = _beams(ctx, values["beamId"])[0]
    net = values["measuredCamberMm"] - values["deadLoadDeflectionMm"]
    return result(
        summary={
            "beamId": beam["id"],
            "measuredNaturalCamberMm": values["measuredCamberMm"],
            "deadLoadDeflectionMm": values["deadLoadDeflectionMm"],
            "residualCamberMm": net,
        },
        notes=["Measured sweep and predicted deflection are compared with upward positive."],
    )


@feature(
    "planMembersCamber.fabricationLimit",
    "Fabrication Limit",
    part="floorPlan",
    fields=[
        text("beamIds", "Beam ids", "B1,B2"),
        number("maximumCamberMm", "Maximum fabrication camber", 25, unit="mm", min=0),
        number("maximumRatio", "Maximum camber-to-span ratio", 0.01, min=0),
    ],
)
def fabrication_limit(ctx: FeatureContext, values: dict) -> dict:
    """Check proposed camber values against absolute and span-proportional shop limits."""
    beams = _beams(ctx, values["beamIds"])
    out = []
    for b in beams:
        camber = values["maximumRatio"] * b["lengthM"] * 1000
        limit = min(values["maximumCamberMm"], camber)
        out.append(
            {
                "beamId": b["id"],
                "spanM": b["lengthM"],
                "ratioLimitMm": camber,
                "absoluteLimitMm": values["maximumCamberMm"],
                "governingLimitMm": limit,
            }
        )
    return result(
        summary={
            "checkedBeams": len(out),
            "maximumPermittedCamberMm": max((r["governingLimitMm"] for r in out), default=0),
        },
        tables=[
            table(
                "Fabrication camber limits",
                [
                    ("beamId", "Beam"),
                    ("spanM", "Span", "m"),
                    ("ratioLimitMm", "Ratio limit", "mm"),
                    ("absoluteLimitMm", "Absolute limit", "mm"),
                    ("governingLimitMm", "Governing limit", "mm"),
                ],
                out,
            )
        ],
        notes=["Limits are user-entered fabrication criteria, not code limits."],
    )


@feature(
    "planMembersCamber.straightenBeam",
    "Straighten Beam",
    part="floorPlan",
    fields=[
        text("beamId", "Beam id", "B1"),
        number("measuredSweepMm", "Measured sweep", 15, unit="mm"),
        number("supportDifferentialMm", "Support differential elevation", 0, unit="mm"),
    ],
)
def straighten_beam(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the residual midspan sweep after subtracting a straight support-to-support chord."""
    beam = _beams(ctx, values["beamId"])[0]
    residual = values["measuredSweepMm"] - values["supportDifferentialMm"] / 2
    return result(
        summary={
            "beamId": beam["id"],
            "spanM": beam["lengthM"],
            "measuredSweepMm": values["measuredSweepMm"],
            "chordCorrectionMm": values["supportDifferentialMm"] / 2,
            "residualSweepMm": residual,
        }
    )


@feature(
    "planMembersCamber.deflectionCheck",
    "Deflection Check",
    part="floorPlan",
    fields=[
        text("beamIds", "Beam ids", "B1,B2"),
        number("uniformLoadKnPerM", "Service uniform load", 8, unit="kN/m", min=0),
        number("elasticModulusMpa", "Elastic modulus", 25000, unit="MPa", min=1),
        number("inertiaMm4", "Moment of inertia", 1e9, unit="mm⁴", min=1),
        number("allowableRatio", "Allowable deflection ratio", 360, min=1),
    ],
)
def deflection_check(ctx: FeatureContext, values: dict) -> dict:
    """Calculate elastic uniform-load deflection and compare with span divided by a user limit."""
    beams = _beams(ctx, values["beamIds"])
    out = []
    for b in beams:
        delta = _uniform_deflection_mm(
            values["uniformLoadKnPerM"],
            b["lengthM"],
            values["elasticModulusMpa"],
            values["inertiaMm4"],
        )
        limit = b["lengthM"] * 1000 / values["allowableRatio"]
        out.append(
            {
                "beamId": b["id"],
                "spanM": b["lengthM"],
                "deflectionMm": delta,
                "allowableMm": limit,
                "withinLimit": delta <= limit,
            }
        )
    return result(
        summary={"checkedBeams": len(out), "exceedances": sum(not r["withinLimit"] for r in out)},
        tables=[
            table(
                "Service deflection",
                [
                    ("beamId", "Beam"),
                    ("spanM", "Span", "m"),
                    ("deflectionMm", "Deflection", "mm"),
                    ("allowableMm", "Allowable", "mm"),
                    ("withinLimit", "Within limit"),
                ],
                out,
            )
        ],
        notes=[
            "Simply supported prismatic beam under uniform service load; stiffness and allowable ratio are entered assumptions."
        ],
    )


@feature(
    "planMembersCamber.pondingCheck",
    "Ponding Check",
    part="floorPlan",
    fields=[
        text("beamId", "Roof beam id", "B1"),
        number("spanM", "Beam span if not in plan", 6, unit="m", min=0),
        number("initialSlopeMm", "Roof fall end-to-end", 20, unit="mm"),
        number("predictedMidspanDeflectionMm", "Midspan deflection", 10, unit="mm", min=0),
    ],
)
def ponding_check(ctx: FeatureContext, values: dict) -> dict:
    """Screen whether predicted midspan deflection consumes the geometric roof fall."""
    _, rows = profile(ctx)
    beam = next((r for r in rows if r["id"] == values["beamId"] and r["category"] == "beam"), None)
    span = beam["lengthM"] if beam else values["spanM"]
    if span <= 0:
        raise FeatureInputError("Provide an existing beam or positive span.")
    residual = values["initialSlopeMm"] - 2 * values["predictedMidspanDeflectionMm"]
    return result(
        summary={
            "spanM": span,
            "initialFallMm": values["initialSlopeMm"],
            "remainingFallMm": residual,
            "pondingGeometryRisk": residual <= 0,
        },
        notes=[
            "Geometric screening only: water depth, roof plate stiffness and nonlinear load-deflection feedback are not included."
        ],
    )


@feature(
    "planMembersCamber.vibrationCheck",
    "Vibration Check",
    part="floorPlan",
    fields=[
        text("beamIds", "Beam ids", "B1,B2"),
        number("elasticModulusMpa", "Elastic modulus", 200000, unit="MPa", min=1),
        number("inertiaMm4", "Moment of inertia", 1e9, unit="mm⁴", min=1),
        number("massKgPerM", "Mass per length", 250, unit="kg/m", min=0.01),
    ],
)
def vibration_check(ctx: FeatureContext, values: dict) -> dict:
    """Estimate first bending frequency for simply supported beams with uniform mass."""
    beams = _beams(ctx, values["beamIds"])
    out = []
    for b in beams:
        e = values["elasticModulusMpa"] * 1e6
        inertia = values["inertiaMm4"] * 1e-12
        mass = values["massKgPerM"]
        length = b["lengthM"]
        freq = math.pi / (2 * length**2) * math.sqrt(e * inertia / mass)
        out.append({"beamId": b["id"], "spanM": length, "frequencyHz": freq})
    return result(
        summary={
            "checkedBeams": len(out),
            "minimumFrequencyHz": min((r["frequencyHz"] for r in out), default=None),
        },
        tables=[
            table(
                "Beam frequency estimates",
                [
                    ("beamId", "Beam"),
                    ("spanM", "Span", "m"),
                    ("frequencyHz", "First frequency", "Hz"),
                ],
                out,
            )
        ],
        notes=[
            "Euler-Bernoulli simply supported beam with uniform mass; nonstructural mass and floor-system coupling are excluded."
        ],
    )


@feature(
    "planMembersCamber.camberReport",
    "Camber Report",
    part="floorPlan",
    fields=[
        text(
            "camberRowsJson", "Camber result rows JSON", '[{"beamId":"B1","spanM":6,"camberMm":12}]'
        )
    ],
)
def camber_report(ctx: FeatureContext, values: dict) -> dict:
    """Summarise supplied beam camber results by maximum, mean and total span."""
    try:
        rows = json.loads(values["camberRowsJson"])
    except ValueError as exc:
        raise FeatureInputError("Camber report rows must be valid JSON.") from exc
    if not isinstance(rows, list):
        raise FeatureInputError("Camber report rows must be a JSON array.")
    camber = [float(r.get("camberMm", 0)) for r in rows]
    return result(
        summary={
            "beamCount": len(rows),
            "maximumCamberMm": max(camber, default=0),
            "meanCamberMm": sum(camber) / len(camber) if camber else 0,
            "totalSpanM": sum(float(r.get("spanM", 0)) for r in rows),
        },
        tables=[
            table(
                "Camber results",
                [("beamId", "Beam"), ("spanM", "Span", "m"), ("camberMm", "Camber", "mm")],
                rows,
            )
        ],
    )


@feature(
    "planMembersCamber.camberSchedule",
    "Camber Schedule",
    part="floorPlan",
    fields=[
        text("beamIds", "Beam ids", "B1,B2"),
        number("camberMm", "Camber target", 12, unit="mm"),
    ],
)
def camber_schedule(ctx: FeatureContext, values: dict) -> dict:
    """Schedule a uniform camber target against the measured span of each selected beam."""
    beams = _beams(ctx, values["beamIds"])
    rows = [
        {
            "beamId": b["id"],
            "spanM": b["lengthM"],
            "camberMm": values["camberMm"],
            "camberToSpan": values["camberMm"] / (b["lengthM"] * 1000),
        }
        for b in beams
    ]
    return result(
        summary={"scheduledBeams": len(rows), "camberMm": values["camberMm"]},
        tables=[
            table(
                "Beam camber schedule",
                [
                    ("beamId", "Beam"),
                    ("spanM", "Span", "m"),
                    ("camberMm", "Camber", "mm"),
                    ("camberToSpan", "Camber/span"),
                ],
                rows,
            )
        ],
    )


@feature(
    "planMembersCamber.beamMark",
    "Beam Mark",
    part="floorPlan",
    fields=[
        text("beamIds", "Beam ids", "B1,B2"),
        text("markPrefix", "Mark prefix", "BM"),
        number("firstNumber", "First number", 1, min=0),
    ],
)
def beam_mark(ctx: FeatureContext, values: dict) -> dict:
    """Assign sequential camber schedule marks in the requested beam selection order."""
    beams = _beams(ctx, values["beamIds"])
    rows = [
        {"beamId": b["id"], "mark": f"{values['markPrefix']}{int(values['firstNumber']) + i}"}
        for i, b in enumerate(beams)
    ]
    return result(
        summary={"markedBeams": len(rows)},
        tables=[table("Beam marks", [("beamId", "Beam"), ("mark", "Camber mark")], rows)],
    )


@feature(
    "planMembersCamber.camberTolerance",
    "Camber Tolerance",
    part="floorPlan",
    fields=[
        number("designCamberMm", "Design camber", 12, unit="mm"),
        number("fabricationToleranceMm", "Fabrication tolerance", 3, unit="mm", min=0),
        number("measuredCamberMm", "Measured camber", 10, unit="mm"),
    ],
    requires_project=False,
)
def camber_tolerance(ctx: FeatureContext, values: dict) -> dict:
    """Compare a fabricated camber measurement with design target and allowed tolerance."""
    deviation = values["measuredCamberMm"] - values["designCamberMm"]
    return result(
        summary={
            "deviationMm": deviation,
            "absoluteDeviationMm": abs(deviation),
            "toleranceMm": values["fabricationToleranceMm"],
            "withinTolerance": abs(deviation) <= values["fabricationToleranceMm"],
        }
    )


@feature(
    "planMembersCamber.exportSchedule",
    "Export Schedule",
    part="floorPlan",
    fields=[
        text("beamIds", "Beam ids", "B1,B2"),
        number("camberMm", "Camber target", 12, unit="mm"),
        text("filename", "CSV filename", "camber-schedule.csv"),
    ],
)
def export_schedule(ctx: FeatureContext, values: dict) -> dict:
    """Write selected beam spans and camber callouts to a CSV fabrication schedule."""
    beams = _beams(ctx, values["beamIds"])
    rows = [
        {"beamId": b["id"], "spanM": b["lengthM"], "camberMm": values["camberMm"]} for b in beams
    ]
    name = values["filename"].strip()
    if not name.lower().endswith(".csv") or "/" in name or "\\" in name:
        raise FeatureInputError("Use a simple .csv filename without folders.")
    path = export_csv(ctx, name, ["beamId", "spanM", "camberMm"], rows)
    return result(
        summary={"exportedBeams": len(rows), "file": path},
        notes=[f"Wrote camber schedule to {path}."],
    )


@feature(
    "planMembersCamber.camberRules",
    "Camber Rules",
    part="floorPlan",
    fields=[
        number("minimumSpanM", "Minimum span for camber", 6, unit="m", min=0),
        number(
            "minimumDeflectionMm", "Minimum predicted dead-load deflection", 5, unit="mm", min=0
        ),
        number("camberFraction", "Camber fraction", 1, min=0, max=2),
    ],
)
def camber_rules(ctx: FeatureContext, values: dict) -> dict:
    """Define automatic camber eligibility based on minimum span and predicted deflection."""
    _, rows = profile(ctx)
    beams = [r for r in rows if r["category"] == "beam"]
    eligible = [r for r in beams if r["lengthM"] >= values["minimumSpanM"]]
    return result(
        summary={
            "beamCount": len(beams),
            "spanEligibleCount": len(eligible),
            "minimumSpanM": values["minimumSpanM"],
            "minimumDeflectionMm": values["minimumDeflectionMm"],
            "camberFraction": values["camberFraction"],
        },
        tables=[
            table(
                "Camber rule beam screening",
                [("beamId", "Beam"), ("spanM", "Span", "m"), ("spanEligible", "Eligible")],
                [
                    {
                        "beamId": r["id"],
                        "spanM": r["lengthM"],
                        "spanEligible": r["lengthM"] >= values["minimumSpanM"],
                    }
                    for r in beams
                ],
            )
        ],
    )


@feature(
    "planMembersCamber.minSpanLimit",
    "Min Span Limit",
    part="floorPlan",
    fields=[
        number("minimumSpanM", "Minimum beam span", 6, unit="m", min=0),
        text("beamIds", "Beam ids (blank for all beams)", ""),
    ],
)
def min_span_limit(ctx: FeatureContext, values: dict) -> dict:
    """Separate selected beams that meet a minimum camber span threshold from shorter beams."""
    _, rows = profile(ctx)
    beams = [r for r in rows if r["category"] == "beam"]
    if values["beamIds"]:
        beams = selected_members(beams, values["beamIds"])
    eligible = [r for r in beams if r["lengthM"] >= values["minimumSpanM"]]
    return result(
        summary={"eligibleBeams": len(eligible), "excludedShortBeams": len(beams) - len(eligible)},
        tables=[
            table(
                "Camber span limit",
                [("beamId", "Beam"), ("spanM", "Span", "m"), ("eligible", "Meets minimum")],
                [
                    {
                        "beamId": r["id"],
                        "spanM": r["lengthM"],
                        "eligible": r["lengthM"] >= values["minimumSpanM"],
                    }
                    for r in beams
                ],
            )
        ],
    )


@feature(
    "planMembersCamber.camberRounding",
    "Camber Rounding",
    part="floorPlan",
    fields=[
        number("calculatedCamberMm", "Calculated camber", 12.4, unit="mm"),
        number("roundingIncrementMm", "Shop rounding increment", 2, unit="mm", min=0.1),
    ],
    requires_project=False,
)
def camber_rounding(ctx: FeatureContext, values: dict) -> dict:
    """Round a calculated camber magnitude to a fabrication increment."""
    rounded = (
        round(values["calculatedCamberMm"] / values["roundingIncrementMm"])
        * values["roundingIncrementMm"]
    )
    return result(
        summary={
            "calculatedCamberMm": values["calculatedCamberMm"],
            "roundedCamberMm": rounded,
            "roundingIncrementMm": values["roundingIncrementMm"],
            "roundingChangeMm": rounded - values["calculatedCamberMm"],
        }
    )


@feature(
    "planMembersCamber.deadLoadCamber",
    "Dead Load Camber",
    part="floorPlan",
    fields=[
        text("beamIds", "Beam ids", "B1,B2"),
        number("deadLoadKnPerM", "Unfactored dead line load", 5, unit="kN/m", min=0),
        number("elasticModulusMpa", "Elastic modulus", 25000, unit="MPa", min=1),
        number("inertiaMm4", "Moment of inertia", 1e9, unit="mm⁴", min=1),
    ],
)
def dead_load_camber(ctx: FeatureContext, values: dict) -> dict:
    """Calculate upward camber targets equal to the elastic deflection under unfactored dead load."""
    beams = _beams(ctx, values["beamIds"])
    rows = [
        {
            "beamId": b["id"],
            "spanM": b["lengthM"],
            "deadLoadDeflectionMm": _uniform_deflection_mm(
                values["deadLoadKnPerM"],
                b["lengthM"],
                values["elasticModulusMpa"],
                values["inertiaMm4"],
            ),
        }
        for b in beams
    ]
    return result(
        summary={
            "calculatedBeams": len(rows),
            "totalCamberMm": sum(r["deadLoadDeflectionMm"] for r in rows),
        },
        tables=[
            table(
                "Dead-load camber",
                [
                    ("beamId", "Beam"),
                    ("spanM", "Span", "m"),
                    ("deadLoadDeflectionMm", "Camber", "mm"),
                ],
                rows,
            )
        ],
        notes=[
            "Simply supported prismatic elastic beam with uniform dead load; stiffness is supplied by the engineer."
        ],
    )


@feature(
    "planMembersCamber.compositeStage",
    "Composite Stage",
    part="floorPlan",
    fields=[
        text("beamId", "Beam id", "B1"),
        number(
            "wetConcreteLoadKnPerM", "Wet concrete and construction load", 8, unit="kN/m", min=0
        ),
        number("elasticModulusMpa", "Steel elastic modulus", 200000, unit="MPa", min=1),
        number("steelInertiaMm4", "Bare steel inertia", 1e9, unit="mm⁴", min=1),
    ],
)
def composite_stage(ctx: FeatureContext, values: dict) -> dict:
    """Estimate bare-steel deflection during wet-concrete construction before composite action."""
    beam = _beams(ctx, values["beamId"])[0]
    delta = _uniform_deflection_mm(
        values["wetConcreteLoadKnPerM"],
        beam["lengthM"],
        values["elasticModulusMpa"],
        values["steelInertiaMm4"],
    )
    return result(
        summary={
            "beamId": beam["id"],
            "constructionStageDeflectionMm": delta,
            "constructionLoadKnPerM": values["wetConcreteLoadKnPerM"],
        },
        notes=[
            "Bare steel section, simply supported, uniform construction load; shore interaction and staged composite stiffness are excluded."
        ],
    )


@feature(
    "planMembersCamber.creepAdjustment",
    "Creep Adjustment",
    part="floorPlan",
    fields=[
        number("shortTermDeflectionMm", "Short-term deflection", 10, unit="mm", min=0),
        number("creepCoefficient", "Creep coefficient", 2, min=0),
        number("longTermLoadFraction", "Sustained load fraction", 0.5, min=0, max=1),
    ],
)
def creep_adjustment(ctx: FeatureContext, values: dict) -> dict:
    """Add a sustained-load creep increment to short-term deflection using an explicit coefficient."""
    increment = (
        values["shortTermDeflectionMm"]
        * values["creepCoefficient"]
        * values["longTermLoadFraction"]
    )
    return result(
        summary={
            "creepDeflectionIncrementMm": increment,
            "longTermDeflectionMm": values["shortTermDeflectionMm"] + increment,
            "creepCoefficient": values["creepCoefficient"],
        }
    )


@feature(
    "planMembersCamber.camberTag",
    "Camber Tag",
    part="floorPlan",
    fields=[
        text("beamId", "Beam id", "B1"),
        number("camberMm", "Camber", 12, unit="mm"),
        text("tagPrefix", "Tag prefix", "CAM"),
    ],
    requires_project=False,
)
def camber_tag(ctx: FeatureContext, values: dict) -> dict:
    """Format an unambiguous beam camber callout tag."""
    return result(
        summary={
            "tag": f"{values['tagPrefix']}-{values['beamId']}",
            "label": f"CAMBER {values['camberMm']:.1f} mm",
            "beamId": values["beamId"],
        }
    )


@feature(
    "planMembersCamber.markCamber",
    "Mark Camber",
    part="floorPlan",
    fields=[text("beamIds", "Beam ids", "B1,B2"), number("camberMm", "Camber", 12, unit="mm")],
)
def mark_camber(ctx: FeatureContext, values: dict) -> dict:
    """Attach a camber dimension annotation to each selected beam schedule row."""
    beams = _beams(ctx, values["beamIds"])
    rows = [
        {
            "beamId": b["id"],
            "spanM": b["lengthM"],
            "camberMm": values["camberMm"],
            "annotation": f"{values['camberMm']:.1f} mm up",
        }
        for b in beams
    ]
    return result(
        summary={"annotatedBeams": len(rows)},
        tables=[
            table(
                "Camber annotations",
                [
                    ("beamId", "Beam"),
                    ("spanM", "Span", "m"),
                    ("camberMm", "Camber", "mm"),
                    ("annotation", "Callout"),
                ],
                rows,
            )
        ],
    )


@feature(
    "planMembersCamber.colorCode",
    "Color Code",
    part="floorPlan",
    fields=[
        text(
            "beamCamberJson",
            "Beam camber JSON",
            '[{"id":"B1","camberMm":8},{"id":"B2","camberMm":18}]',
        ),
        number("lowThresholdMm", "Low camber threshold", 10, unit="mm"),
        number("highThresholdMm", "High camber threshold", 20, unit="mm"),
    ],
)
def color_code(ctx: FeatureContext, values: dict) -> dict:
    """Assign low, medium or high visual classes from explicit camber magnitude thresholds."""
    try:
        rows = json.loads(values["beamCamberJson"])
    except ValueError as exc:
        raise FeatureInputError("Beam camber input must be valid JSON.") from exc
    if values["highThresholdMm"] < values["lowThresholdMm"]:
        raise FeatureInputError("High threshold must not be below low threshold.")
    out = [
        {
            "beamId": r.get("id", ""),
            "camberMm": float(r.get("camberMm", 0)),
            "class": "low"
            if float(r.get("camberMm", 0)) < values["lowThresholdMm"]
            else "medium"
            if float(r.get("camberMm", 0)) < values["highThresholdMm"]
            else "high",
        }
        for r in rows
    ]
    return result(
        summary={"codedBeams": len(out), "classes": len({r["class"] for r in out})},
        tables=[
            table(
                "Camber color classes",
                [("beamId", "Beam"), ("camberMm", "Camber", "mm"), ("class", "Color class")],
                out,
            )
        ],
    )


@feature(
    "planMembersCamber.camberBatch",
    "Camber Batch",
    part="floorPlan",
    fields=[
        text("beamIds", "Beam ids", "B1,B2"),
        number("deadLoadKnPerM", "Unfactored dead line load", 5, unit="kN/m", min=0),
        number("elasticModulusMpa", "Elastic modulus", 25000, unit="MPa", min=1),
        number("inertiaMm4", "Moment of inertia", 1e9, unit="mm⁴", min=1),
        number("camberFraction", "Camber fraction", 1, min=0, max=2),
    ],
)
def camber_batch(ctx: FeatureContext, values: dict) -> dict:
    """Batch calculate dead-load camber for selected floor beams."""
    beams = _beams(ctx, values["beamIds"])
    rows = []
    for b in beams:
        delta = _uniform_deflection_mm(
            values["deadLoadKnPerM"],
            b["lengthM"],
            values["elasticModulusMpa"],
            values["inertiaMm4"],
        )
        rows.append(
            {
                "beamId": b["id"],
                "spanM": b["lengthM"],
                "deadLoadDeflectionMm": delta,
                "camberMm": delta * values["camberFraction"],
            }
        )
    return result(
        summary={"processedBeams": len(rows), "totalCamberMm": sum(r["camberMm"] for r in rows)},
        tables=[
            table(
                "Batch camber results",
                [
                    ("beamId", "Beam"),
                    ("spanM", "Span", "m"),
                    ("deadLoadDeflectionMm", "Dead-load deflection", "mm"),
                    ("camberMm", "Camber", "mm"),
                ],
                rows,
            )
        ],
    )

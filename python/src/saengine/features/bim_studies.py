"""BIM 3D design and analysis studies."""

from __future__ import annotations

import math
from typing import Any

from saengine.features import FeatureContext, checkbox, feature, number, result, select, table, text
from saengine.features.bim_common import kind_counts, require_bim, write_bim_json


@feature(
    "bimStudies.designOptions",
    "Design Options",
    part="bim",
    fields=[
        text("optionNames", "Option names", "A: Base,B: Alternate"),
        text("selectedOption", "Selected option", "A"),
    ],
)
def design_options(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define named design options for the BIM model."""
    require_bim(ctx)
    names = [v.strip() for v in str(values["optionNames"]).split(",") if v.strip()]
    return result(
        summary={"optionCount": len(names), "selectedOption": values["selectedOption"]},
        tables=[
            table("Design Options", [("option", "Option")], [{"option": name} for name in names])
        ],
    )


@feature(
    "bimStudies.solarStudy",
    "Solar Study",
    part="bim",
    fields=[
        number("latitude", "Site latitude", 23.8, unit="°"),
        number("day", "Day of year", 172.0, unit="day", min=1, max=365),
        number("hour", "Solar hour", 12.0, unit="h", min=0, max=24),
    ],
)
def solar_study(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate apparent solar elevation for a simple sun-position study."""
    require_bim(ctx)
    declination = 23.45 * math.sin(math.radians(360 * (284 + values["day"]) / 365))
    hour_angle = 15 * (values["hour"] - 12)
    lat = math.radians(values["latitude"])
    dec = math.radians(declination)
    ha = math.radians(hour_angle)
    altitude = math.degrees(
        math.asin(math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(ha))
    )
    return result(
        summary={
            "dayOfYear": int(values["day"]),
            "hour": values["hour"],
            "declinationDeg": declination,
            "solarAltitudeDeg": altitude,
        },
        notes=[
            "Approximation uses the day-angle equation and ignores refraction, terrain and atmospheric attenuation."
        ],
    )


@feature(
    "bimStudies.costStudy",
    "Cost Study",
    part="bim",
    fields=[
        number("baseCost", "Base model cost", 1000000.0, unit="currency"),
        number("materialIncrease", "Material escalation", 5.0, unit="%", min=-100),
    ],
)
def cost_study(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply a material escalation factor to a design-cost baseline."""
    require_bim(ctx)
    adjusted = values["baseCost"] * (1 + values["materialIncrease"] / 100)
    return result(
        summary={
            "baseCost": values["baseCost"],
            "materialIncreasePercent": values["materialIncrease"],
            "adjustedCost": adjusted,
        }
    )


@feature(
    "bimStudies.studyResults",
    "Study Results",
    part="bim",
    fields=[
        select(
            "metric",
            "Result metric",
            [("elementCount", "Element count"), ("height", "Building height"), ("cost", "Cost")],
            "elementCount",
        ),
        select(
            "order",
            "Order",
            [("ascending", "Ascending"), ("descending", "Descending")],
            "descending",
        ),
    ],
)
def study_results(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarize available BIM study metrics."""
    data = require_bim(ctx)
    heights = [
        float(e.get("top", e.get("elevation", 0)))
        for e in data["elements"]
        if isinstance(e, dict) and isinstance(e.get("top", e.get("elevation", 0)), (int, float))
    ]
    metric = {
        "elementCount": len(data["elements"]),
        "height": max(heights) if heights else 0,
        "cost": 0,
    }[values["metric"]]
    return result(summary={"metric": values["metric"], "value": metric, "order": values["order"]})


@feature(
    "bimStudies.optionSets",
    "Option Sets",
    part="bim",
    fields=[
        text("setName", "Option set name", "Envelope"),
        text("optionIds", "Option identifiers", "EN1,EN2"),
    ],
)
def option_sets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Save a set of design options."""
    data = require_bim(ctx)
    ids = [v.strip() for v in str(values["optionIds"]).split(",") if v.strip()]
    payload = {
        "name": values["setName"].strip() or "Envelope",
        "optionIds": ids,
        "elementCount": len(data["elements"]),
    }
    path = write_bim_json(ctx, "bim_option_set.json", payload)
    return result(summary={"setName": payload["name"], "optionCount": len(ids), "exportPath": path})


@feature(
    "bimStudies.energyUseStudy",
    "Energy Use Study",
    part="bim",
    fields=[
        number("floorArea", "Total conditioned floor area", 250.0, unit="m²", min=0.1),
        number("annualUse", "Annual energy use", 75000.0, unit="kWh/a", min=0),
    ],
)
def energy_use_study(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate annual energy-use intensity."""
    require_bim(ctx)
    intensity = values["annualUse"] / values["floorArea"]
    return result(
        summary={
            "floorAreaM2": values["floorArea"],
            "annualUseKWhPerYear": values["annualUse"],
            "energyUseIntensityKWhPerM2Year": intensity,
        },
        notes=[
            "Use intensity is annual metered energy divided by conditioned floor area; it excludes weather correction."
        ],
    )


@feature(
    "bimStudies.daylightStudy",
    "Daylight Study",
    part="bim",
    fields=[
        number("windowArea", "Window opening area", 20.0, unit="m²", min=0),
        number("floorArea", "Occupied floor area", 100.0, unit="m²", min=0.1),
        number("visibleTransmittance", "Visible transmittance", 0.75, unit="", min=0, max=1),
    ],
)
def daylight_study(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate a simplified daylight aperture ratio."""
    require_bim(ctx)
    ratio = values["windowArea"] / values["floorArea"]
    weighted = ratio * values["visibleTransmittance"]
    return result(
        summary={"windowToFloorRatio": ratio, "effectiveDaylightAperture": weighted},
        notes=["This simplified index is not an illuminance or daylight-factor analysis."],
    )


@feature(
    "bimStudies.thermalStudy",
    "Thermal Study",
    part="bim",
    fields=[
        number("outsideTemperature", "Outside temperature", 35.0, unit="°C"),
        number("insideTemperature", "Inside temperature", 24.0, unit="°C"),
        number("wallArea", "Wall area", 500.0, unit="m²", min=0),
        number("uValue", "Wall U-value", 1.8, unit="W/(m²·K)", min=0),
    ],
)
def thermal_study(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate steady-state wall conduction heat gain."""
    require_bim(ctx)
    delta = values["insideTemperature"] - values["outsideTemperature"]
    gain = values["uValue"] * values["wallArea"] * delta
    return result(
        summary={"temperatureDifferenceK": abs(delta), "steadyStateHeatTransferW": abs(gain)},
        notes=[
            "Assumes steady-state one-dimensional conduction, no solar, ventilation or thermal bridging effects."
        ],
    )


@feature(
    "bimStudies.windStudy",
    "Wind Study",
    part="bim",
    fields=[
        number("windSpeed", "Reference wind speed", 25.0, unit="m/s", min=0),
        number("area", "Exposed area", 500.0, unit="m²", min=0),
        number("pressureCoefficient", "Pressure coefficient", 0.8, unit="", min=-2, max=2),
        number("airDensity", "Air density", 1.225, unit="kg/m³", min=0),
    ],
)
def wind_study(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate an equivalent wind pressure and force."""
    require_bim(ctx)
    pressure = 0.5 * values["airDensity"] * values["windSpeed"] ** 2 * values["pressureCoefficient"]
    force = pressure * values["area"] / 1000
    return result(
        summary={
            "pressureKPa": pressure / 1000,
            "windForceKN": abs(force),
            "forceSign": 1 if force >= 0 else -1,
        },
        notes=["Uses dynamic pressure q=0.5ρv² times the entered pressure coefficient."],
    )


@feature(
    "bimStudies.carbonStudy",
    "Carbon Study",
    part="bim",
    fields=[
        number("steelKg", "Steel quantity", 50000.0, unit="kg", min=0),
        number("steelFactor", "Steel embodied-carbon factor", 1.8, unit="kgCO2e/kg", min=0),
        number("concreteKg", "Concrete quantity", 500000.0, unit="kg", min=0),
        number("concreteFactor", "Concrete embodied-carbon factor", 0.12, unit="kgCO2e/kg", min=0),
    ],
)
def carbon_study(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate embodied carbon from entered quantities and factors."""
    require_bim(ctx)
    steel = values["steelKg"] * values["steelFactor"]
    concrete = values["concreteKg"] * values["concreteFactor"]
    total = (steel + concrete) / 1000
    return result(
        summary={"steelTCO2e": steel / 1000, "concreteTCO2e": concrete / 1000, "totalTCO2e": total}
    )


@feature(
    "bimStudies.optionComparison",
    "Option Comparison",
    part="bim",
    fields=[
        text("optionA", "Option A", "A"),
        number("valueA", "Value A", 100.0, unit="score"),
        text("optionB", "Option B", "B"),
        number("valueB", "Value B", 95.0, unit="score"),
    ],
)
def option_comparison(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare two entered option values."""
    require_bim(ctx)
    rows = [
        {"option": values["optionA"], "value": values["valueA"]},
        {"option": values["optionB"], "value": values["valueB"]},
    ]
    difference = values["valueA"] - values["valueB"]
    return result(
        summary={
            "difference": difference,
            "higherOption": values["optionA"] if difference >= 0 else values["optionB"],
        },
        tables=[table("Option Comparison", [("option", "Option"), ("value", "Value")], rows)],
    )


@feature(
    "bimStudies.scorecardMatrix",
    "Scorecard Matrix",
    part="bim",
    fields=[text("criteria", "Criteria", "Cost,Carbon,Speed"), text("options", "Options", "A,B,C")],
)
def scorecard_matrix(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build an empty criteria-versus-options scorecard matrix."""
    require_bim(ctx)
    criteria = [v.strip() for v in str(values["criteria"]).split(",") if v.strip()]
    options = [v.strip() for v in str(values["options"]).split(",") if v.strip()]
    rows = [{"criterion": c, **{o: 0.0 for o in options}} for c in criteria]
    return result(
        summary={"criterionCount": len(criteria), "optionCount": len(options)},
        tables=[
            table(
                "Scorecard Matrix", [("criterion", "Criterion")] + [(o, o) for o in options], rows
            )
        ],
    )


@feature(
    "bimStudies.weightedCriteria",
    "Weighted Criteria",
    part="bim",
    fields=[
        number("costWeight", "Cost weight", 40.0, unit="%", min=0, max=100),
        number("carbonWeight", "Carbon weight", 30.0, unit="%", min=0, max=100),
        number("qualityWeight", "Quality weight", 30.0, unit="%", min=0, max=100),
    ],
)
def weighted_criteria(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Normalize three decision-criteria weights."""
    require_bim(ctx)
    total = values["costWeight"] + values["carbonWeight"] + values["qualityWeight"]
    if total <= 0:
        from saengine.features import FeatureInputError

        raise FeatureInputError("The three criterion weights must have a positive sum.")
    return result(
        summary={
            "costWeightPercent": values["costWeight"] / total * 100,
            "carbonWeightPercent": values["carbonWeight"] / total * 100,
            "qualityWeightPercent": values["qualityWeight"] / total * 100,
            "enteredTotalPercent": total,
        }
    )


@feature(
    "bimStudies.optionVariants",
    "Option Variants",
    part="bim",
    fields=[
        text("baseOption", "Base option", "A"),
        number("variants", "Number of variants", 3.0, unit="variants", min=1, max=100),
    ],
)
def option_variants(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List generated design-variant names."""
    require_bim(ctx)
    count = int(values["variants"])
    base = values["baseOption"].strip() or "A"
    rows = [{"variant": f"{base}-{i}"} for i in range(1, count + 1)]
    return result(
        summary={"baseOption": base, "variantCount": count},
        tables=[table("Option Variants", [("variant", "Variant")], rows)],
    )


@feature(
    "bimStudies.reportExport",
    "Report Export",
    part="bim",
    fields=[
        select(
            "format", "Report format", [("json", "JSON"), ("csv", "CSV"), ("html", "HTML")], "json"
        ),
        text("title", "Report title", "BIM Study Report"),
    ],
)
def report_export(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export a basic BIM study report."""
    data = require_bim(ctx)
    payload = {
        "title": values["title"],
        "elementCount": len(data["elements"]),
        "kindCounts": kind_counts(data),
    }
    path = write_bim_json(ctx, "bim_study_report.json", payload)
    return result(
        summary={"format": values["format"], "title": values["title"], "exportPath": path}
    )


@feature(
    "bimStudies.colourByOption",
    "Colour by Option",
    part="bim",
    fields=[
        text("optionA", "Option A elements", "C1,C2"),
        text("optionB", "Option B elements", "C3,C4"),
    ],
)
def colour_by_option(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map element selections to option colours."""
    data = require_bim(ctx)
    a = {v.strip() for v in values["optionA"].split(",") if v.strip()}
    b = {v.strip() for v in values["optionB"].split(",") if v.strip()}
    rows = [
        {"id": e["id"], "option": "A" if e["id"] in a else "B" if e["id"] in b else "Unassigned"}
        for e in data["elements"]
        if isinstance(e, dict)
    ]
    return result(
        summary={"optionACount": len(a), "optionBCount": len(b), "elementCount": len(rows)},
        tables=[
            table("Element Option Colours", [("id", "Element id"), ("option", "Option")], rows)
        ],
    )


@feature(
    "bimStudies.sideBySide",
    "Side by Side",
    part="bim",
    fields=[
        text("leftOption", "Left option", "A"),
        text("rightOption", "Right option", "B"),
        checkbox("syncCamera", "Synchronize camera", True),
    ],
)
def side_by_side(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure a side-by-side option comparison view."""
    require_bim(ctx)
    return result(
        summary={
            "leftOption": values["leftOption"],
            "rightOption": values["rightOption"],
            "syncCamera": bool(values["syncCamera"]),
        }
    )


@feature(
    "bimStudies.overlayOptions",
    "Overlay Options",
    part="bim",
    fields=[
        text("optionNames", "Options to overlay", "A,B"),
        number("opacity", "Overlay opacity", 50.0, unit="%", min=0, max=100),
    ],
)
def overlay_options(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure translucent option overlays."""
    require_bim(ctx)
    names = [v.strip() for v in values["optionNames"].split(",") if v.strip()]
    return result(summary={"optionCount": len(names), "opacityPercent": values["opacity"]})


@feature(
    "bimStudies.visibilityToggle",
    "Visibility Toggle",
    part="bim",
    fields=[text("optionName", "Option name", "A"), checkbox("visible", "Visible", True)],
)
def visibility_toggle(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Toggle the visibility of an option."""
    require_bim(ctx)
    return result(summary={"optionName": values["optionName"], "visible": bool(values["visible"])})


@feature(
    "bimStudies.studyLegend",
    "Study Legend",
    part="bim",
    fields=[
        select(
            "legendType",
            "Legend type",
            [("colour", "Colour"), ("symbol", "Symbol"), ("text", "Text")],
            "colour",
        ),
        checkbox("showValues", "Show values", True),
    ],
)
def study_legend(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure a study-result legend."""
    require_bim(ctx)
    return result(
        summary={"legendType": values["legendType"], "showValues": bool(values["showValues"])}
    )


@feature(
    "bimStudies.scenarioBuilder",
    "Scenario Builder",
    part="bim",
    fields=[
        text("scenarioName", "Scenario name", "Peak demand"),
        text("parameters", "Parameters", "loadFactor=1.2,windSpeed=25"),
    ],
)
def scenario_builder(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record a named study scenario."""
    data = require_bim(ctx)
    params = [v.strip() for v in values["parameters"].split(",") if v.strip()]
    payload = {
        "name": values["scenarioName"].strip() or "Peak demand",
        "parameters": params,
        "elementCount": len(data["elements"]),
    }
    path = write_bim_json(ctx, "bim_scenario.json", payload)
    return result(
        summary={"scenarioName": payload["name"], "parameterCount": len(params), "exportPath": path}
    )


@feature(
    "bimStudies.parameterSweep",
    "Parameter Sweep",
    part="bim",
    fields=[
        text("parameterName", "Parameter name", "Load factor"),
        number("start", "Start value", 1.0, unit="value"),
        number("end", "End value", 1.5, unit="value"),
        number("step", "Step", 0.1, unit="value", min=0.0001),
    ],
)
def parameter_sweep(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate an arithmetic parameter-sweep list."""
    require_bim(ctx)
    if values["step"] <= 0 or values["end"] < values["start"]:
        from saengine.features import FeatureInputError

        raise FeatureInputError(
            "End value must not be below start value and step must be positive."
        )
    rows = []
    value = values["start"]
    while value <= values["end"] + values["step"] / 2:
        rows.append({"step": len(rows) + 1, "value": value})
        value += values["step"]
    return result(
        summary={"parameterName": values["parameterName"], "sampleCount": len(rows)},
        tables=[table("Parameter Sweep", [("step", "Sample"), ("value", "Value")], rows)],
    )


@feature(
    "bimStudies.resultCapture",
    "Result Capture",
    part="bim",
    fields=[
        text("captureName", "Capture name", "Envelope - run 1"),
        text("notes", "Capture notes", ""),
    ],
)
def result_capture(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Capture named study metadata."""
    data = require_bim(ctx)
    payload = {
        "name": values["captureName"].strip() or "Study capture",
        "notes": values["notes"],
        "elementCount": len(data["elements"]),
    }
    path = write_bim_json(ctx, "bim_study_capture.json", payload)
    return result(
        summary={
            "captureName": payload["name"],
            "elementCount": len(data["elements"]),
            "exportPath": path,
        }
    )


@feature(
    "bimStudies.sensitivityChart",
    "Sensitivity Chart",
    part="bim",
    fields=[
        number("baseValue", "Base parameter value", 1.0, unit="value"),
        number("lowValue", "Low parameter value", 0.8, unit="value"),
        number("highValue", "High parameter value", 1.2, unit="value"),
        number("baseResult", "Base result", 100.0, unit="result"),
        number("lowResult", "Low-result case", 90.0, unit="result"),
        number("highResult", "High-result case", 110.0, unit="result"),
    ],
)
def sensitivity_chart(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate low, base and high sensitivity points."""
    require_bim(ctx)
    rows = [
        {"case": "Low", "parameter": values["lowValue"], "result": values["lowResult"]},
        {"case": "Base", "parameter": values["baseValue"], "result": values["baseResult"]},
        {"case": "High", "parameter": values["highValue"], "result": values["highResult"]},
    ]
    return result(
        summary={
            "lowDifference": values["lowResult"] - values["baseResult"],
            "highDifference": values["highResult"] - values["baseResult"],
        },
        tables=[
            table(
                "Sensitivity Chart",
                [("case", "Case"), ("parameter", "Parameter"), ("result", "Result")],
                rows,
            )
        ],
    )

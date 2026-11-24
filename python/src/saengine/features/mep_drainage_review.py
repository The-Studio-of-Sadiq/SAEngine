"""Drainage treatment, condition review and rainwater resource calculations."""

from __future__ import annotations

import json

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


@feature(
    "mepDrainage.septicTank",
    "Septic Tank",
    part="mep",
    fields=[
        number("population", "Design population", 10, unit="persons", min=1),
        number("retention", "Detention period", 2, unit="days", min=0.1),
        number("sludge", "Sludge accumulation rate", 0.06, unit="m³/person/year", min=0),
        number("desludgeYears", "Desludging interval", 1, unit="years", min=0.1),
        number("dailyFlow", "Sewage flow", 150, unit="L/person/day", min=0),
    ],
    requires_project=False,
)
def septic_tank(ctx: FeatureContext, v: dict) -> dict:
    """Estimate working volume from hydraulic retention and accumulated sludge."""
    liquid = v["population"] * v["dailyFlow"] * v["retention"] / 1000
    sludge = v["population"] * v["sludge"] * v["desludgeYears"]
    return result(
        {"liquidVolumeM3": liquid, "sludgeStorageM3": sludge, "workingVolumeM3": liquid + sludge},
        [
            table(
                "Septic tank volume",
                [("component", "Component"), ("volume", "Volume", "m³")],
                [
                    {"component": "Liquid retention", "volume": liquid},
                    {"component": "Sludge storage", "volume": sludge},
                    {"component": "Total working volume", "volume": liquid + sludge},
                ],
            )
        ],
        [
            "Preliminary volume estimate; provide settling, scum storage, compartment and local health requirements separately."
        ],
    )


@feature(
    "mepDrainage.drainageField",
    "Drainage Field",
    part="mep",
    fields=[
        number("dailyEffluent", "Daily effluent", 1.5, unit="m³/day", min=0),
        number("percolationRate", "Percolation rate", 25, unit="s/mm", min=0.1),
        number("trenchWidth", "Trench width", 0.6, unit="m", min=0.1),
    ],
    requires_project=False,
)
def drainage_field(ctx: FeatureContext, v: dict) -> dict:
    """Estimate soakage trench length using entered percolation-test rate and width."""
    application_rate = 0.2 * (v["percolationRate"] + 1)
    area = v["dailyEffluent"] * 1000 / application_rate
    length = area / v["trenchWidth"]
    return result(
        {
            "applicationRateLPerM2Day": application_rate,
            "infiltrationAreaM2": area,
            "trenchLengthM": length,
        },
        [
            table(
                "Drainage field",
                [("measure", "Measure"), ("value", "Value")],
                [
                    {"measure": "Application rate [L/m²/day]", "value": application_rate},
                    {"measure": "Required area [m²]", "value": area},
                    {"measure": "Trench length [m]", "value": length},
                ],
            )
        ],
        [
            "Screening relationship between percolation time and loading; confirm the method against the site's approved test procedure."
        ],
    )


@feature(
    "mepDrainage.packageTreatment",
    "Package Treatment",
    part="mep",
    fields=[
        number("population", "Design population", 50, unit="persons", min=1),
        number("flow", "Sewage flow", 150, unit="L/person/day", min=0),
        number("peakFactor", "Peak flow factor", 2.5, min=1),
    ],
    requires_project=False,
)
def package_treatment(ctx: FeatureContext, v: dict) -> dict:
    """Calculate average and peak treatment flows for a stated design population."""
    average = v["population"] * v["flow"] / 86400
    return result(
        {"averageFlowLPerS": average, "peakFlowLPerS": average * v["peakFactor"]},
        [
            table(
                "Treatment duty",
                [("condition", "Condition"), ("flow", "Flow", "L/s")],
                [
                    {"condition": "Average", "flow": average},
                    {"condition": "Peak", "flow": average * v["peakFactor"]},
                ],
            )
        ],
        [
            "Select a packaged unit using its certified process performance, effluent limits and peak-load data."
        ],
    )


@feature(
    "mepDrainage.pumpStation",
    "Pump Station",
    part="mep",
    fields=[
        number("dutyFlow", "Duty flow", 8, unit="L/s", min=0.01),
        number("totalHead", "Total dynamic head", 12, unit="m", min=0.1),
        number("efficiency", "Pump efficiency", 0.65, min=0.05, max=1),
        number("pumpCount", "Installed pumps", 2, min=1),
    ],
    requires_project=False,
)
def pump_station(ctx: FeatureContext, v: dict) -> dict:
    """Estimate hydraulic power and installed pump duty from flow, head and efficiency."""
    power = 9.81 * (v["dutyFlow"] / 1000) * v["totalHead"] / v["efficiency"]
    return result(
        {
            "hydraulicInputKw": power,
            "installedPumps": int(v["pumpCount"]),
            "dutyFlowLPerS": v["dutyFlow"],
            "totalHeadM": v["totalHead"],
        },
        [
            table(
                "Pump duty",
                [("measure", "Measure"), ("value", "Value")],
                [
                    {"measure": "Flow [L/s]", "value": v["dutyFlow"]},
                    {"measure": "Head [m]", "value": v["totalHead"]},
                    {"measure": "Estimated shaft input [kW]", "value": power},
                ],
            )
        ],
        [
            "Water density is approximated as 1000 kg/m³; confirm pump curves, solids handling and standby duty."
        ],
    )


@feature(
    "mepDrainage.liftStation",
    "Lift Station",
    part="mep",
    fields=[
        number("inflow", "Peak inflow", 5, unit="L/s", min=0),
        number("pumpCapacity", "Pump capacity", 8, unit="L/s", min=0.01),
        number("cycleMinutes", "Maximum pump cycle", 10, unit="min", min=0.1),
    ],
    requires_project=False,
)
def lift_station(ctx: FeatureContext, v: dict) -> dict:
    """Estimate wet-well active volume for an entered inflow and operating cycle."""
    if v["pumpCapacity"] <= v["inflow"]:
        raise FeatureInputError(
            "Pump capacity must exceed the design inflow to draw down the wet well."
        )
    active = (
        v["inflow"]
        * v["pumpCapacity"]
        / (v["pumpCapacity"] - v["inflow"])
        * v["cycleMinutes"]
        * 60
        / 4000
    )
    return result(
        {
            "activeVolumeM3": active,
            "pumpCapacityLPerS": v["pumpCapacity"],
            "inflowLPerS": v["inflow"],
        },
        [
            table(
                "Wet-well operating volume",
                [("measure", "Measure"), ("value", "Value")],
                [
                    {"measure": "Active volume [m³]", "value": active},
                    {"measure": "Cycle [min]", "value": v["cycleMinutes"]},
                ],
            )
        ],
        [
            "Active-volume estimate assumes a constant inflow and pump delivery; add dead volume and alarm reserve."
        ],
    )


@feature(
    "mepDrainage.cctvSurvey",
    "CCTV Survey",
    part="mep",
    fields=[
        text("segmentId", "Pipeline segment ID", ""),
        number("defects", "Observed defects", 0, min=0),
        select(
            "worstDefect",
            "Worst observed defect",
            [("none", "None"), ("minor", "Minor"), ("moderate", "Moderate"), ("severe", "Severe")],
        ),
    ],
)
def cctv_survey(ctx: FeatureContext, v: dict) -> dict:
    """Classify a recorded pipe survey observation and export a condition summary."""
    raw = ctx.raw("mep")
    if not isinstance(raw, dict):
        raise FeatureInputError("Add a MEP project before recording a CCTV survey.")
    if not v["segmentId"].strip():
        raise FeatureInputError("Enter the surveyed pipeline segment ID.")
    records = raw.get("pipes", raw.get("pipeRuns", []))
    if not any(isinstance(p, dict) and str(p.get("id", "")) == v["segmentId"] for p in records):
        raise FeatureInputError("The surveyed segment ID must match a pipe in the MEP model.")
    rating = {"none": 1, "minor": 2, "moderate": 3, "severe": 4}[v["worstDefect"]]
    survey = {
        "segmentId": v["segmentId"],
        "defectCount": int(v["defects"]),
        "worstDefect": v["worstDefect"],
        "screeningGrade": rating,
    }
    path = ctx.path("11 Exports/mep-cctv-survey.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"surveys": [survey]}, indent=2) + "\n", encoding="utf-8")
    return result(
        {"segmentId": v["segmentId"], "screeningGrade": rating, "exportPath": str(path)},
        [
            table(
                "Survey findings",
                [("item", "Item"), ("value", "Value")],
                [{"item": key, "value": value} for key, value in survey.items()],
            )
        ],
        [
            "Screening grade maps the entered worst defect category to an ordinal 1–4 scale; use the adopted survey standard for formal coding."
        ],
    )


@feature(
    "mepDrainage.pipeCondition",
    "Pipe Condition",
    part="mep",
    fields=[
        number("ageYears", "Pipe age", 20, unit="years", min=0),
        number("expectedLife", "Reference service life", 60, unit="years", min=1),
        number("defectSeverity", "Survey severity", 2, min=1, max=4),
    ],
    requires_project=False,
)
def pipe_condition(ctx: FeatureContext, v: dict) -> dict:
    """Combine age consumption and survey severity into a transparent condition screening index."""
    age_fraction = min(1, v["ageYears"] / v["expectedLife"])
    index = min(100, 100 * (0.5 * age_fraction + 0.5 * (v["defectSeverity"] - 1) / 3))
    return result(
        {
            "conditionIndex": index,
            "remainingLifeEstimateYears": max(0, v["expectedLife"] - v["ageYears"]),
        },
        [
            table(
                "Condition indicators",
                [("indicator", "Indicator"), ("value", "Value")],
                [
                    {"indicator": "Age consumed [%]", "value": age_fraction * 100},
                    {"indicator": "Defect severity [1–4]", "value": v["defectSeverity"]},
                    {"indicator": "Screening index [0–100]", "value": index},
                ],
            )
        ],
        [
            "Weighted screening index is not a structural capacity assessment or a formal pipe-condition grade."
        ],
    )


@feature(
    "mepDrainage.gradientCheck",
    "Gradient Check",
    part="mep",
    fields=[
        number("upstreamInvert", "Upstream invert", 12.5, unit="m"),
        number("downstreamInvert", "Downstream invert", 12.2, unit="m"),
        number("length", "Pipe length", 30, unit="m", min=0.01),
        number("minimumGradient", "Required minimum gradient", 0.01, min=0),
    ],
    requires_project=False,
)
def gradient_check(ctx: FeatureContext, v: dict) -> dict:
    """Calculate as-built pipe fall and compare it with the engineer-entered minimum gradient."""
    fall = v["upstreamInvert"] - v["downstreamInvert"]
    gradient = fall / v["length"]
    return result(
        {
            "fallM": fall,
            "gradient": gradient,
            "pass": fall >= 0 and gradient >= v["minimumGradient"],
        },
        [
            table(
                "As-built gradient",
                [("measure", "Measure"), ("value", "Value")],
                [
                    {"measure": "Fall [m]", "value": fall},
                    {"measure": "Length [m]", "value": v["length"]},
                    {"measure": "Gradient [m/m]", "value": gradient},
                    {"measure": "Minimum [m/m]", "value": v["minimumGradient"]},
                ],
            )
        ],
        ["Check survey datum, pipe invert endpoints and the specified minimum gradient."],
    )


@feature(
    "mepDrainage.infiltrationCheck",
    "Infiltration Check",
    part="mep",
    fields=[
        number("baseFlow", "Dry-weather flow", 2, unit="L/s", min=0),
        number("observedFlow", "Observed flow", 2.6, unit="L/s", min=0),
        number("length", "Network length", 1200, unit="m", min=0.1),
    ],
    requires_project=False,
)
def infiltration_check(ctx: FeatureContext, v: dict) -> dict:
    """Estimate excess infiltration rate per unit length from measured and base flows."""
    excess = max(0, v["observedFlow"] - v["baseFlow"])
    return result(
        {
            "excessFlowLPerS": excess,
            "infiltrationLPerSPerKm": excess * 1000 / v["length"],
            "observedToBaseRatio": v["observedFlow"] / max(v["baseFlow"], 1e-12),
        },
        [
            table(
                "Infiltration estimate",
                [("measure", "Measure"), ("value", "Value")],
                [
                    {"measure": "Observed flow [L/s]", "value": v["observedFlow"]},
                    {"measure": "Base flow [L/s]", "value": v["baseFlow"]},
                    {
                        "measure": "Excess per kilometre [L/s/km]",
                        "value": excess * 1000 / v["length"],
                    },
                ],
            )
        ],
        [
            "Flow difference is an infiltration screening estimate; account for rainfall, diurnal variation and measurement uncertainty."
        ],
    )


@feature(
    "mepDrainage.drainageAudit",
    "Drainage Audit",
    part="mep",
    fields=[],
)
def drainage_audit(ctx: FeatureContext, values: dict) -> dict:
    """Audit modelled drainage pipe connectivity and identify unconnected pipe endpoints."""
    raw = ctx.raw("mep")
    if not isinstance(raw, dict):
        raise FeatureInputError("Add a MEP model to audit its drainage network.")
    pipes = raw.get("pipes", raw.get("pipeRuns", []))
    if not isinstance(pipes, list):
        raise FeatureInputError("The MEP pipe collection is not a list.")
    connections: dict[str, int] = {}
    for pipe in pipes:
        if not isinstance(pipe, dict):
            continue
        for endpoint in ("startNode", "endNode", "from", "to"):
            node = pipe.get(endpoint)
            if node is not None:
                connections[str(node)] = connections.get(str(node), 0) + 1
    isolated = [node for node, count in connections.items() if count == 1]
    return result(
        {
            "pipeCount": len(pipes),
            "networkNodeCount": len(connections),
            "singleConnectionNodes": len(isolated),
        },
        [
            table(
                "Drainage network audit",
                [("node", "Endpoint node"), ("connectionCount", "Connections")],
                [{"node": node, "connectionCount": connections[node]} for node in isolated],
            )
        ],
        [
            "Endpoint checks are based on explicit node references; they do not prove hydraulic connectivity or capacity."
        ],
    )


@feature(
    "mepDrainage.harvestSystem",
    "Harvest System",
    part="mep",
    fields=[
        number("roofArea", "Roof catchment", 500, unit="m²", min=0),
        number("annualRain", "Annual rainfall", 900, unit="mm/year", min=0),
        number("runoff", "Runoff coefficient", 0.85, min=0, max=1),
        number("demand", "Non-potable annual demand", 250, unit="m³/year", min=0),
    ],
    requires_project=False,
)
def harvest_system(ctx: FeatureContext, v: dict) -> dict:
    """Compare annual rainwater yield with the stated non-potable demand."""
    yield_m3 = v["roofArea"] * v["annualRain"] / 1000 * v["runoff"]
    return result(
        {
            "annualYieldM3": yield_m3,
            "demandM3": v["demand"],
            "annualSupplyCoveragePercent": min(100, yield_m3 / v["demand"] * 100)
            if v["demand"]
            else 0,
            "surplusM3": max(0, yield_m3 - v["demand"]),
        },
        [
            table(
                "Annual water balance",
                [("component", "Component"), ("volume", "Volume", "m³/year")],
                [
                    {"component": "Rainwater yield", "volume": yield_m3},
                    {"component": "Demand", "volume": v["demand"]},
                ],
            )
        ],
        [
            "Annual balance ignores daily timing, first-flush losses, overflow and storage constraints."
        ],
    )


@feature(
    "mepDrainage.harvestVolume",
    "Harvest Volume",
    part="mep",
    fields=[
        number("dailyDemand", "Daily demand", 0.8, unit="m³/day", min=0),
        number("dryPeriod", "Design dry period", 14, unit="days", min=0),
        number("inflow", "Available inflow during period", 6, unit="m³", min=0),
    ],
    requires_project=False,
)
def harvest_volume(ctx: FeatureContext, v: dict) -> dict:
    """Estimate usable storage required to bridge the entered low-supply period."""
    required = max(0, v["dailyDemand"] * v["dryPeriod"] - v["inflow"])
    return result(
        {
            "requiredUsableStorageM3": required,
            "dryPeriodDemandM3": v["dailyDemand"] * v["dryPeriod"],
        },
        [
            table(
                "Storage balance",
                [("measure", "Measure"), ("volume", "Volume", "m³")],
                [
                    {
                        "measure": "Demand during dry period",
                        "volume": v["dailyDemand"] * v["dryPeriod"],
                    },
                    {"measure": "Available inflow", "volume": v["inflow"]},
                    {"measure": "Usable storage", "volume": required},
                ],
            )
        ],
        [
            "Simple period balance; apply a time-step rainfall and demand simulation for variable supply."
        ],
    )


@feature(
    "mepDrainage.firstFlushDiverter",
    "First Flush Diverter",
    part="mep",
    fields=[
        number("roofArea", "Roof catchment", 300, unit="m²", min=0),
        number("diversionDepth", "Initial runoff depth", 1, unit="mm", min=0),
    ],
    requires_project=False,
)
def first_flush_diverter(ctx: FeatureContext, v: dict) -> dict:
    """Calculate initial runoff volume diverted using catchment area and selected depth."""
    volume = v["roofArea"] * v["diversionDepth"] / 1000
    return result(
        {"divertedVolumeM3": volume, "divertedVolumeL": volume * 1000},
        [
            table(
                "First-flush volume",
                [("measure", "Measure"), ("value", "Value")],
                [
                    {"measure": "Catchment area [m²]", "value": v["roofArea"]},
                    {"measure": "Diversion depth [mm]", "value": v["diversionDepth"]},
                    {"measure": "Diverter volume [L]", "value": volume * 1000},
                ],
            )
        ],
        ["Volume is the selected initial runoff depth multiplied by catchment area."],
    )


@feature(
    "mepDrainage.irrigationDemand",
    "Irrigation Demand",
    part="mep",
    fields=[
        number("landscapeArea", "Irrigated area", 1000, unit="m²", min=0),
        number("dailyDepth", "Daily irrigation depth", 3, unit="mm/day", min=0),
        number("days", "Irrigation days", 120, unit="days", min=0),
        number("effectiveRain", "Effective rainfall", 80, unit="mm", min=0),
    ],
    requires_project=False,
)
def irrigation_demand(ctx: FeatureContext, v: dict) -> dict:
    """Estimate seasonal irrigation volume after subtracting effective rainfall."""
    net_depth = max(0, v["dailyDepth"] * v["days"] - v["effectiveRain"])
    volume = v["landscapeArea"] * net_depth / 1000
    return result(
        {"netIrrigationDepthMm": net_depth, "seasonalDemandM3": volume},
        [
            table(
                "Irrigation water balance",
                [("measure", "Measure"), ("value", "Value")],
                [
                    {"measure": "Gross seasonal depth [mm]", "value": v["dailyDepth"] * v["days"]},
                    {"measure": "Effective rainfall [mm]", "value": v["effectiveRain"]},
                    {"measure": "Net demand [m³]", "value": volume},
                ],
            )
        ],
        [
            "This simplified balance excludes irrigation efficiency, soil storage and plant-specific crop coefficients."
        ],
    )

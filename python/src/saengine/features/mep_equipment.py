"""Mechanical plant selection, connections and schedules."""

from __future__ import annotations

import math

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


def _equipment(ctx: FeatureContext) -> list[dict]:
    raw = ctx.raw("mep")
    items = raw.get("equipment", []) if isinstance(raw, dict) else []
    if not isinstance(items, list) or not items:
        raise FeatureInputError("Add mechanical equipment to 07 MEP/mep.json first.")
    return [item for item in items if isinstance(item, dict)]


@feature(
    "mepEquipment.chillers",
    "Chillers",
    part="mep",
    fields=[
        number("loadKw", "Cooling duty", 350, unit="kW", min=0.1),
        number("cop", "COP", 5.2, min=0.1),
    ],
    requires_project=False,
)
def chillers(ctx: FeatureContext, v: dict) -> dict:
    """Estimate chiller input power and heat rejection from the cooling duty."""
    power = v["loadKw"] / v["cop"]
    return result(
        {
            "coolingDutyKw": v["loadKw"],
            "inputPowerKw": power,
            "heatRejectionKw": v["loadKw"] + power,
        },
        notes=["First-law balance; manufacturer part-load performance is not represented."],
    )


@feature(
    "mepEquipment.boilers",
    "Boilers",
    part="mep",
    fields=[
        number("outputKw", "Required output", 250, unit="kW", min=0.1),
        number("efficiency", "Thermal efficiency", 0.9, min=0.1, max=1),
    ],
    requires_project=False,
)
def boilers(ctx: FeatureContext, v: dict) -> dict:
    """Calculate boiler fuel input from useful heat output and efficiency."""
    fuel = v["outputKw"] / v["efficiency"]
    return result(
        {"outputKw": v["outputKw"], "fuelInputKw": fuel, "lossKw": fuel - v["outputKw"]},
        notes=["Steady-state energy balance using the entered efficiency."],
    )


@feature(
    "mepEquipment.ahuPlacement",
    "AHU Placement",
    part="mep",
    fields=[
        number("flowM3s", "Supply airflow", 2, unit="m³/s", min=0.01),
        number("faceVelocityMs", "Coil face velocity", 2, unit="m/s", min=0.1),
    ],
    requires_project=False,
)
def ahu_placement(ctx: FeatureContext, v: dict) -> dict:
    """Estimate the minimum AHU coil face area for the specified airflow."""
    area = v["flowM3s"] / v["faceVelocityMs"]
    return result(
        {"faceAreaM2": area, "flowM3s": v["flowM3s"], "faceVelocityMs": v["faceVelocityMs"]},
        notes=[
            "Clear coil face area is airflow divided by face velocity; casing and access clearances are additional."
        ],
    )


@feature(
    "mepEquipment.coolingTowers",
    "Cooling Towers",
    part="mep",
    fields=[
        number("heatKw", "Heat rejection", 420, unit="kW", min=0.1),
        number("rangeC", "Water range", 5, unit="°C", min=0.1),
    ],
    requires_project=False,
)
def cooling_towers(ctx: FeatureContext, v: dict) -> dict:
    """Estimate tower water circulation from heat rejection and temperature range."""
    flow = v["heatKw"] / (4.186 * v["rangeC"])
    return result(
        {"waterFlowLs": flow, "heatRejectionKw": v["heatKw"]},
        notes=["Water heat capacity is taken as 4.186 kJ/(kg·K), with density 1 kg/L."],
    )


@feature(
    "mepEquipment.plantroomLayout",
    "Plantroom Layout",
    part="mep",
    fields=[
        number("lengthM", "Room length", 12, unit="m", min=0.1),
        number("widthM", "Room width", 8, unit="m", min=0.1),
        number("plantAreaM2", "Equipment footprint", 48, unit="m²", min=0),
    ],
    requires_project=False,
)
def plantroom_layout(ctx: FeatureContext, v: dict) -> dict:
    """Calculate residual plantroom floor area and footprint ratio."""
    area = v["lengthM"] * v["widthM"]
    if v["plantAreaM2"] > area:
        raise FeatureInputError("Equipment footprint exceeds the entered plantroom area.")
    return result(
        {
            "roomAreaM2": area,
            "clearAreaM2": area - v["plantAreaM2"],
            "footprintRatio": v["plantAreaM2"] / area,
        },
        notes=["Area check does not verify access routes, lifting space or statutory clearances."],
    )


@feature(
    "mepEquipment.plantClearances",
    "Plant Clearances",
    part="mep",
    fields=[
        number("equipmentWidthMm", "Equipment width", 1200, unit="mm", min=1),
        number("sideClearanceMm", "Side clearance", 600, unit="mm", min=0),
        number("frontClearanceMm", "Service clearance", 1000, unit="mm", min=0),
    ],
    requires_project=False,
)
def plant_clearances(ctx: FeatureContext, v: dict) -> dict:
    """Calculate the plant footprint including entered maintenance envelopes."""
    return result(
        {
            "requiredWidthMm": v["equipmentWidthMm"] + 2 * v["sideClearanceMm"],
            "serviceDepthMm": v["frontClearanceMm"],
        },
        notes=[
            "Clearances are user-specified working envelopes; verify against the selected equipment's service instructions."
        ],
    )


@feature(
    "mepEquipment.maintenanceAccess",
    "Maintenance Access",
    part="mep",
    fields=[
        number("routeWidthMm", "Clear route width", 900, unit="mm", min=0),
        number("minimumWidthMm", "Required route width", 800, unit="mm", min=1),
    ],
    requires_project=False,
)
def maintenance_access(ctx: FeatureContext, v: dict) -> dict:
    """Check that the measured service route meets the selected access width."""
    passed = v["routeWidthMm"] >= v["minimumWidthMm"]
    return result(
        {"clearWidthMm": v["routeWidthMm"], "requiredWidthMm": v["minimumWidthMm"], "pass": passed},
        notes=[
            "Width-only access check; turning circles, doors and vertical obstructions are excluded."
        ],
    )


@feature(
    "mepEquipment.equipmentSchedule",
    "Equipment Schedule",
    part="mep",
    fields=[],
    requires_project=True,
)
def equipment_schedule(ctx: FeatureContext, v: dict) -> dict:
    """List project mechanical equipment and its recorded duty."""
    rows = _equipment(ctx)
    return result(
        {"equipmentCount": len(rows)},
        [
            table(
                "Mechanical equipment",
                [("tag", "Tag"), ("type", "Type"), ("dutyKw", "Duty", "kW"), ("system", "System")],
                [
                    {
                        "tag": x.get("tag", ""),
                        "type": x.get("type", ""),
                        "dutyKw": x.get("dutyKw"),
                        "system": x.get("system", ""),
                    }
                    for x in rows
                ],
            )
        ],
    )


@feature(
    "mepEquipment.plantSchedule",
    "Plant Schedule",
    part="mep",
    fields=[text("plantroom", "Plantroom filter", "")],
    requires_project=True,
)
def plant_schedule(ctx: FeatureContext, v: dict) -> dict:
    """Schedule equipment recorded for the selected plantroom."""
    rows = [
        x for x in _equipment(ctx) if not v["plantroom"] or x.get("plantroom") == v["plantroom"]
    ]
    return result(
        {"plantroom": v["plantroom"], "itemCount": len(rows)},
        [
            table(
                "Plant items",
                [
                    ("tag", "Tag"),
                    ("type", "Type"),
                    ("plantroom", "Plantroom"),
                    ("dutyKw", "Duty", "kW"),
                ],
                [
                    {
                        "tag": x.get("tag", ""),
                        "type": x.get("type", ""),
                        "plantroom": x.get("plantroom", ""),
                        "dutyKw": x.get("dutyKw"),
                    }
                    for x in rows
                ],
            )
        ],
    )


@feature(
    "mepEquipment.energyLabel",
    "Energy Label",
    part="mep",
    fields=[
        number("cop", "Seasonal COP", 4, min=0.1),
        number("referenceCop", "Reference COP", 3, min=0.1),
    ],
    requires_project=False,
)
def energy_label(ctx: FeatureContext, v: dict) -> dict:
    """Compare entered seasonal COP with a user-selected reference."""
    ratio = v["cop"] / v["referenceCop"]
    return result(
        {"cop": v["cop"], "referenceCop": v["referenceCop"], "relativeEfficiency": ratio},
        notes=["Relative efficiency is a ratio to the entered benchmark, not a regulatory label."],
    )


@feature(
    "mepEquipment.pumpSelection",
    "Pump Selection",
    part="mep",
    fields=[
        number("flowM3h", "Design flow", 32, unit="m³/h", min=0),
        number("headM", "Total head", 22, unit="m", min=0),
        number("efficiency", "Pump efficiency", 0.72, min=0.1, max=1),
    ],
    requires_project=False,
)
def pump_selection(ctx: FeatureContext, v: dict) -> dict:
    """Calculate hydraulic duty and shaft input for a proposed pump point."""
    hydraulic = 1000 * 9.80665 * v["flowM3h"] / 3600 * v["headM"] / 1000
    return result(
        {
            "hydraulicPowerKw": hydraulic,
            "shaftPowerKw": hydraulic / v["efficiency"],
            "flowM3h": v["flowM3h"],
            "headM": v["headM"],
        },
        notes=[
            "Water density is 1000 kg/m³; confirm the duty point against the manufacturer's pump curve and system curve."
        ],
    )


@feature(
    "mepEquipment.coolingLoadMatch",
    "Cooling Load Match",
    part="mep",
    fields=[
        number("blockLoadKw", "Coincident block load", 500, unit="kW", min=0),
        number("unitCapacityKw", "Unit capacity", 250, unit="kW", min=0.1),
    ],
    requires_project=False,
)
def cooling_load_match(ctx: FeatureContext, v: dict) -> dict:
    """Calculate the number of equal-capacity units required for a block load."""
    count = math.ceil(v["blockLoadKw"] / v["unitCapacityKw"])
    return result(
        {
            "unitCount": count,
            "installedCapacityKw": count * v["unitCapacityKw"],
            "capacityMarginKw": count * v["unitCapacityKw"] - v["blockLoadKw"],
        },
        notes=[
            "Coincident load is compared with nominal unit capacity; part-load derating and redundancy are not included."
        ],
    )


@feature(
    "mepEquipment.redundancySetup",
    "Redundancy Setup",
    part="mep",
    fields=[
        number("dutyUnits", "Duty units", 2, min=1),
        number("unitCapacityKw", "Unit capacity", 100, unit="kW", min=0.1),
        select("arrangement", "Arrangement", ["duty-standby", "n-plus-one"]),
    ],
    requires_project=False,
)
def redundancy_setup(ctx: FeatureContext, v: dict) -> dict:
    """Calculate installed capacity for duty-standby or N+1 plant."""
    standby = 1
    count = int(v["dutyUnits"]) + standby
    return result(
        {
            "arrangement": v["arrangement"],
            "installedUnits": count,
            "dutyCapacityKw": v["dutyUnits"] * v["unitCapacityKw"],
            "installedCapacityKw": count * v["unitCapacityKw"],
        },
        notes=[
            "One equal-sized standby unit is added; confirm that one unit failure leaves the required duty capacity."
        ],
    )


@feature(
    "mepEquipment.standbyUnits",
    "Standby Units",
    part="mep",
    fields=[
        number("dutyCount", "Duty unit count", 2, min=1),
        number("standbyCount", "Standby unit count", 1, min=0),
        number("changeoverHours", "Changeover interval", 168, unit="h", min=1),
    ],
    requires_project=False,
)
def standby_units(ctx: FeatureContext, v: dict) -> dict:
    """Summarize duty and standby unit counts and planned rotation interval."""
    return result(
        {
            "totalUnits": int(v["dutyCount"] + v["standbyCount"]),
            "dutyUnits": int(v["dutyCount"]),
            "standbyUnits": int(v["standbyCount"]),
            "changeoverHours": v["changeoverHours"],
        },
        notes=[
            "Rotation interval is an operating input; availability and failure probabilities are not modelled."
        ],
    )


@feature(
    "mepEquipment.equipmentCurves",
    "Equipment Curves",
    part="mep",
    fields=[
        number("flowA", "Candidate A flow", 20, unit="m³/h", min=0),
        number("headA", "Candidate A head", 30, unit="m", min=0),
        number("flowB", "Candidate B flow", 22, unit="m³/h", min=0),
        number("headB", "Candidate B head", 27, unit="m", min=0),
    ],
    requires_project=False,
)
def equipment_curves(ctx: FeatureContext, v: dict) -> dict:
    """Compare two entered manufacturer curve points at their stated duties."""
    return result(
        {
            "candidateAFlowM3h": v["flowA"],
            "candidateAHeadM": v["headA"],
            "candidateBFlowM3h": v["flowB"],
            "candidateBHeadM": v["headB"],
        },
        [
            table(
                "Candidate points",
                [("candidate", "Candidate"), ("flowM3h", "Flow", "m³/h"), ("headM", "Head", "m")],
                [
                    {"candidate": "A", "flowM3h": v["flowA"], "headM": v["headA"]},
                    {"candidate": "B", "flowM3h": v["flowB"], "headM": v["headB"]},
                ],
            )
        ],
        [
            "Entered points are reported for comparison; interpolation and efficiency require the full manufacturer curves."
        ],
    )


@feature(
    "mepEquipment.pipeConnections",
    "Pipe Connections",
    part="mep",
    fields=[
        number("flowLs", "Water flow", 8, unit="L/s", min=0),
        number("velocityMs", "Target velocity", 1.5, unit="m/s", min=0.1),
    ],
    requires_project=False,
)
def pipe_connections(ctx: FeatureContext, v: dict) -> dict:
    """Estimate internal pipe diameter from flow and target velocity."""
    diameter = math.sqrt(4 * v["flowLs"] / 1000 / (math.pi * v["velocityMs"])) * 1000
    return result(
        {"internalDiameterMm": diameter, "flowLs": v["flowLs"], "velocityMs": v["velocityMs"]},
        notes=["Continuity sizing; select a commercial bore and check pressure loss and noise."],
    )


@feature(
    "mepEquipment.ductConnections",
    "Duct Connections",
    part="mep",
    fields=[
        number("flowM3s", "Airflow", 1.5, unit="m³/s", min=0),
        number("velocityMs", "Target velocity", 5, unit="m/s", min=0.1),
    ],
    requires_project=False,
)
def duct_connections(ctx: FeatureContext, v: dict) -> dict:
    """Estimate circular duct diameter from airflow and target velocity."""
    return result(
        {
            "areaM2": v["flowM3s"] / v["velocityMs"],
            "diameterMm": math.sqrt(4 * v["flowM3s"] / (math.pi * v["velocityMs"])) * 1000,
        },
        notes=[
            "Continuity estimate excludes fittings, acoustic criteria and available standard sizes."
        ],
    )


@feature(
    "mepEquipment.electricalConnections",
    "Electrical Connections",
    part="mep",
    fields=[
        number("powerKw", "Electrical input", 40, unit="kW", min=0),
        number("voltageV", "Line voltage", 400, unit="V", min=1),
        number("powerFactor", "Power factor", 0.9, min=0.1, max=1),
    ],
    requires_project=False,
)
def electrical_connections(ctx: FeatureContext, v: dict) -> dict:
    """Calculate three-phase current for the entered equipment input."""
    current = v["powerKw"] * 1000 / (math.sqrt(3) * v["voltageV"] * v["powerFactor"])
    return result(
        {"lineCurrentA": current, "powerKw": v["powerKw"], "voltageV": v["voltageV"]},
        notes=[
            "Balanced three-phase current; starting current and protective-device selection are excluded."
        ],
    )


@feature(
    "mepEquipment.vibrationIsolation",
    "Vibration Isolation",
    part="mep",
    fields=[
        number("speedRpm", "Operating speed", 1450, unit="rpm", min=1),
        number("naturalFrequencyHz", "Isolator natural frequency", 4, unit="Hz", min=0.1),
    ],
    requires_project=False,
)
def vibration_isolation(ctx: FeatureContext, v: dict) -> dict:
    """Estimate excitation-to-isolator frequency ratio for vibration isolation."""
    ratio = v["speedRpm"] / 60 / v["naturalFrequencyHz"]
    return result(
        {"excitationFrequencyHz": v["speedRpm"] / 60, "frequencyRatio": ratio},
        notes=[
            "Frequency ratio is a screening metric; isolation performance depends on damping, load distribution and mounting details."
        ],
    )


@feature(
    "mepEquipment.condensateDrain",
    "Condensate Drain",
    part="mep",
    fields=[
        number("coolingKw", "Sensible plus latent capacity", 30, unit="kW", min=0),
        number("condensateRateKgPerKwh", "Condensate factor", 1.5, unit="kg/kWh", min=0),
        number("operatingHours", "Operating hours", 8, unit="h", min=0),
    ],
    requires_project=False,
)
def condensate_drain(ctx: FeatureContext, v: dict) -> dict:
    """Estimate condensate volume over the entered operating period."""
    flow = v["coolingKw"] * v["condensateRateKgPerKwh"] / 3600
    return result(
        {"condensateLPerS": flow, "volumeL": flow * 3600 * v["operatingHours"]},
        notes=[
            "Water density is approximated as 1 kg/L; the entered condensate factor must reflect the actual coil condition."
        ],
    )


@feature(
    "mepEquipment.equipmentDataSheet",
    "Equipment Data Sheet",
    part="mep",
    fields=[
        text("tag", "Equipment tag", "AHU-01"),
        text("type", "Equipment type", "Air handling unit"),
        number("dutyKw", "Duty", 25, unit="kW", min=0),
        number("inputKw", "Input power", 4, unit="kW", min=0),
    ],
    requires_project=False,
)
def equipment_data_sheet(ctx: FeatureContext, v: dict) -> dict:
    """Compile the entered equipment identifiers and duty into a data-sheet table."""
    return result(
        {"tag": v["tag"], "dutyKw": v["dutyKw"], "inputKw": v["inputKw"]},
        [
            table(
                "Equipment data",
                [("parameter", "Parameter"), ("value", "Value")],
                [
                    {"parameter": "Tag", "value": v["tag"]},
                    {"parameter": "Type", "value": v["type"]},
                    {"parameter": "Duty (kW)", "value": v["dutyKw"]},
                    {"parameter": "Input power (kW)", "value": v["inputKw"]},
                ],
            )
        ],
    )


@feature(
    "mepEquipment.energyRating",
    "Energy Rating",
    part="mep",
    fields=[
        number("inputKw", "Electrical input", 10, unit="kW", min=0),
        number("outputKw", "Useful output", 35, unit="kW", min=0),
    ],
    requires_project=False,
)
def energy_rating(ctx: FeatureContext, v: dict) -> dict:
    """Calculate a useful-output to electrical-input performance ratio."""
    if v["inputKw"] == 0:
        raise FeatureInputError("Electrical input must be greater than zero to calculate a rating.")
    return result(
        {
            "performanceRatio": v["outputKw"] / v["inputKw"],
            "inputKw": v["inputKw"],
            "outputKw": v["outputKw"],
        },
        notes=["This ratio is not a certified product efficiency class."],
    )


@feature(
    "mepEquipment.noiseRating",
    "Noise Rating",
    part="mep",
    fields=[
        number("soundPowerDb", "Equipment sound power", 82, unit="dB", min=0),
        number("roomLimitDb", "Plantroom sound limit", 75, unit="dB", min=0),
    ],
    requires_project=False,
)
def noise_rating(ctx: FeatureContext, v: dict) -> dict:
    """Compare equipment sound power with the entered room criterion."""
    return result(
        {
            "exceedsLimit": v["soundPowerDb"] > v["roomLimitDb"],
            "marginDb": v["roomLimitDb"] - v["soundPowerDb"],
        },
        notes=[
            "Unweighted levels are compared directly; distance attenuation and frequency weighting are not included."
        ],
    )


@feature(
    "mepEquipment.equipmentTags",
    "Equipment Tags",
    part="mep",
    fields=[
        text("prefix", "Tag prefix", "AHU"),
        number("firstNumber", "First sequence number", 1, min=1),
        number("itemCount", "Number of tags", 5, min=1, max=500),
    ],
    requires_project=False,
)
def equipment_tags(ctx: FeatureContext, v: dict) -> dict:
    """Create sequential tags for the requested number of equipment items."""
    tags = [f"{v['prefix']}-{int(v['firstNumber']) + i:02d}" for i in range(int(v["itemCount"]))]
    return result(
        {"tagCount": len(tags)},
        [
            table(
                "Equipment tags",
                [("sequence", "Sequence"), ("tag", "Tag")],
                [{"sequence": i + 1, "tag": tag} for i, tag in enumerate(tags)],
            )
        ],
    )

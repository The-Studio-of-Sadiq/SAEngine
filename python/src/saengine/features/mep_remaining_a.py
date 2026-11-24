"""MEP drainage, fixture, equipment, duct and containment features."""

from __future__ import annotations

import math

from saengine.features import feature, number, result, table


@feature(
    "mepDrainage.rainfallIntensity",
    "Rainfall Intensity",
    part="mep",
    fields=[number("rain", "Rainfall intensity", 100, unit="mm/h", min=0)],
    requires_project=False,
)
def rainfall_intensity(ctx, v):
    return result(
        summary={"rainfallMmPerH": v["rain"]},
        tables=[
            table(
                "Rainfall",
                [("item", "Intensity", "mm/h")],
                [{"item": "Design rainfall", "Intensity": v["rain"]}],
            )
        ],
        notes=["Direct design-rainfall input for rational drainage calculations."],
    )


@feature(
    "mepDrainage.rainwaterPipes",
    "Rainwater Pipes",
    part="mep",
    fields=[
        number("area", "Roof area", 500, unit="m²", min=0.1),
        number("rain", "Rainfall", 100, unit="mm/h", min=0),
        number("runoff", "Runoff coefficient", 0.9, min=0, max=1),
    ],
    requires_project=False,
)
def rainwater_pipes(ctx, v):
    q = v["area"] * v["rain"] * v["runoff"] / 3600
    d = max(75, math.ceil(math.sqrt(4 * (q / 1000) / (math.pi * 2)) * 1000 / 25) * 25)
    return result(
        summary={"flowLPerS": q, "diameterMm": d},
        tables=[
            table(
                "Rainwater pipe",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Flow", "value": q}, {"item": "Diameter", "value": d}],
            )
        ],
        notes=["Rational flow Q=CiA/3600; diameter assumes 2 m/s preliminary velocity."],
    )


@feature(
    "mepDrainage.guttersDownpipes",
    "Gutters & Downpipes",
    part="mep",
    fields=[
        number("flow", "Flow", 10, unit="l/s", min=0),
        number("width", "Gutter width", 300, unit="mm", min=50),
    ],
    requires_project=False,
)
def gutters_downpipes(ctx, v):
    depth = 50
    area = v["width"] * depth / 1e6
    velocity = v["flow"] / 1000 / area
    return result(
        summary={"velocityMs": velocity, "gutterWidthMm": v["width"]},
        tables=[
            table(
                "Gutter",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Velocity", "value": velocity}],
            )
        ],
        notes=["Continuity check with an assumed 50 mm water depth."],
    )


@feature(
    "mepDrainage.sumpPits",
    "Sump Pits",
    part="mep",
    fields=[
        number("inflow", "Inflow", 5, unit="l/s", min=0),
        number("cycle", "Pump cycle", 10, unit="min", min=1),
    ],
    requires_project=False,
)
def sump_pits(ctx, v):
    volume = v["inflow"] * v["cycle"] * 60 / 1000
    return result(
        summary={"requiredVolumeM3": volume, "inflowLPerS": v["inflow"]},
        tables=[
            table(
                "Sump pit",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Volume", "value": volume}],
            )
        ],
        notes=["Usable storage equals inflow volume during the selected pump cycle."],
    )


@feature(
    "mepDrainage.drainLayout",
    "Drain Layout",
    part="mep",
    fields=[
        number("length", "Drain run", 50, unit="m", min=0.1),
        number("fall", "Fall", 0.5, unit="m", min=0),
    ],
    requires_project=False,
)
def drain_layout(ctx, v):
    gradient = v["fall"] / v["length"]
    return result(
        summary={"lengthM": v["length"], "gradient": gradient, "fallPercent": gradient * 100},
        tables=[
            table(
                "Drain layout",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Gradient", "value": gradient}],
            )
        ],
        notes=["Layout gradient is fall divided by horizontal run."],
    )


@feature(
    "mepDrainage.manholes",
    "Manholes",
    part="mep",
    fields=[
        number("diameter", "Drain diameter", 300, unit="mm", min=100),
        number("depth", "Chamber depth", 2, unit="m", min=0),
    ],
    requires_project=False,
)
def manholes(ctx, v):
    chamber = max(900, v["diameter"] * 2)
    return result(
        summary={"chamberDiameterMm": chamber, "depthM": v["depth"]},
        tables=[
            table(
                "Manhole",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Chamber diameter", "value": chamber},
                    {"item": "Depth", "value": v["depth"]},
                ],
            )
        ],
        notes=[
            "Chamber diameter is a preliminary minimum equal to twice drain diameter or 900 mm."
        ],
    )


@feature(
    "mepDrainage.greaseTraps",
    "Grease Traps",
    part="mep",
    fields=[
        number("flow", "Peak flow", 2, unit="l/s", min=0),
        number("retention", "Retention", 30, unit="min", min=1),
    ],
    requires_project=False,
)
def grease_traps(ctx, v):
    volume = v["flow"] * v["retention"] * 60 / 1000
    return result(
        summary={"volumeM3": volume, "flowLPerS": v["flow"]},
        tables=[
            table(
                "Grease trap",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Volume", "value": volume}],
            )
        ],
        notes=["Retention volume is peak flow × retention time."],
    )


@feature(
    "mepDrainage.attenuationTank",
    "Attenuation Tank",
    part="mep",
    fields=[
        number("area", "Catchment", 1000, unit="m²", min=0.1),
        number("rain", "Rainfall", 50, unit="mm/h", min=0),
        number("duration", "Storm duration", 1, unit="h", min=0.1),
        number("outflow", "Permitted outflow", 5, unit="l/s", min=0),
    ],
    requires_project=False,
)
def attenuation_tank(ctx, v):
    inflow = v["area"] * v["rain"] / 1000 * v["duration"] * 1000
    outflow = v["outflow"] * 3600 * v["duration"]
    volume = max(0, inflow - outflow)
    return result(
        summary={"requiredVolumeL": volume, "inflowL": inflow, "outflowL": outflow},
        tables=[
            table(
                "Attenuation",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Required volume", "value": volume}],
            )
        ],
        notes=["Storage is inflow volume less permitted discharge volume for the design storm."],
    )


@feature(
    "mepDrainage.soakawayDesign",
    "Soakaway Design",
    part="mep",
    fields=[
        number("inflow", "Runoff volume", 100, unit="m³", min=0),
        number("infiltration", "Infiltration rate", 0.001, unit="m/s", min=0.000001),
        number("area", "Side and base area", 50, unit="m²", min=0.1),
    ],
    requires_project=False,
)
def soakaway_design(ctx, v):
    q = v["infiltration"] * v["area"] * 3600
    drawdown = v["inflow"] / q if q > 0 else 0.0
    return result(
        summary={"drawdownHours": drawdown, "infiltrationLPerH": q * 1000},
        tables=[
            table(
                "Soakaway",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Drawdown", "value": drawdown}],
            )
        ],
        notes=["Simple volume-and-infiltration estimate; confirm by an infiltration test."],
    )


@feature(
    "mepDrainage.flowControl",
    "Flow Control",
    part="mep",
    fields=[
        number("flow", "Target flow", 5, unit="l/s", min=0),
        number("head", "Head", 2, unit="m", min=0),
    ],
    requires_project=False,
)
def flow_control(ctx, v):
    q = v["flow"] / 1000
    area = q / math.sqrt(2 * 9.81 * v["head"])
    diameter = math.sqrt(4 * area / math.pi) * 1000
    return result(
        summary={"orificeDiameterMm": diameter, "targetFlowLPerS": v["flow"]},
        tables=[
            table(
                "Flow control",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Orifice diameter", "value": diameter}],
            )
        ],
        notes=[
            "Orifice diameter from Q=CdA√2gh with Cd=1.0; apply the selected device discharge coefficient."
        ],
    )

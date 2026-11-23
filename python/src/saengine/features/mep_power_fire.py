"""MEP power-system, earthing and fire-protection features."""

from __future__ import annotations

import math

from saengine.features import FeatureInputError, feature, number, result, table


def _mep(ctx):
    raw = ctx.raw("mep")
    if raw is None:
        raise FeatureInputError("Add 07 MEP/mep.json to the project.")
    from saengine.library.mep import parse

    return parse(__import__("json").dumps(raw))


@feature(
    "mepPowerSystems.cableDerating",
    "Cable Derating",
    part="mep",
    fields=[
        number("base", "Base ampacity", 119, unit="A", min=0),
        number("factor", "Derating factor", 0.8, min=0.1, max=1),
    ],
    requires_project=False,
)
def cable_derating(ctx, v):
    iz = v["base"] * v["factor"]
    return result(
        summary={"effectiveAmpacityA": iz, "factor": v["factor"]},
        tables=[
            table(
                "Cable derating",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Effective ampacity", "value": iz}],
            )
        ],
        notes=["Effective ampacity = base ampacity × pack-based combined factors."],
    )


@feature(
    "mepPowerSystems.protectiveDevices",
    "Protective Devices",
    part="mep",
    fields=[number("load", "Design current", 32, unit="A", min=0)],
    requires_project=False,
)
def protective_devices(ctx, v):
    from saengine.electrical.tables import circuit_rules

    pool = circuit_rules().breakerRatings
    rating = next((r for r in pool if r >= v["load"]), None)
    if rating is None:
        raise FeatureInputError("The design current exceeds the standard breaker range.")
    return result(
        summary={"inA": rating, "ibA": v["load"]},
        tables=[
            table(
                "Protective device",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Design current", "value": v["load"]}, {"item": "In", "value": rating}],
            )
        ],
        notes=["The next standard device rating meeting In >= Ib is selected."],
    )


@feature(
    "mepPowerSystems.discrimination",
    "Discrimination",
    part="mep",
    fields=[
        number("upstream", "Upstream rating", 100, unit="A", min=1),
        number("downstream", "Downstream rating", 32, unit="A", min=1),
    ],
    requires_project=False,
)
def discrimination(ctx, v):
    return result(
        summary={
            "selective": v["upstream"] > v["downstream"] * 3,
            "upstreamA": v["upstream"],
            "downstreamA": v["downstream"],
        },
        tables=[
            table(
                "Discrimination",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Upstream/downstream ratio", "value": v["upstream"] / v["downstream"]}],
            )
        ],
        notes=["Preliminary selectivity ratio; protection curves are required for confirmation."],
    )


@feature(
    "mepPowerSystems.transformerSizing",
    "Transformer Sizing",
    part="mep",
    fields=[
        number("load", "Maximum demand", 500, unit="kVA", min=0),
        number("growth", "Future growth", 20, unit="%", min=0),
    ],
    requires_project=False,
)
def transformer_sizing(ctx, v):
    from saengine.electrical.supply import transformers

    required = v["load"] * (1 + v["growth"] / 100)
    out = transformers(required)
    return result(
        summary={"requiredKva": required, "ratingKva": out["rating"], "count": out["count"]},
        tables=[
            table(
                "Transformer",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Required", "value": required},
                    {"item": "Rating", "value": out["rating"]},
                ],
            )
        ],
        notes=["Uses the existing transformer-size selection engine."],
    )


@feature(
    "mepPowerSystems.earthingGrid",
    "Earthing Grid",
    part="mep",
    fields=[
        number("length", "Grid length", 20, unit="m", min=1),
        number("width", "Grid width", 20, unit="m", min=1),
        number("spacing", "Grid spacing", 5, unit="m", min=0.5),
    ],
    requires_project=False,
)
def earthing_grid(ctx, v):
    nodes = max(1, math.ceil(v["length"] / v["spacing"]) * math.ceil(v["width"] / v["spacing"]))
    area = v["length"] * v["width"]
    return result(
        summary={"gridAreaM2": area, "nodes": nodes},
        tables=[
            table(
                "Earthing grid",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Area", "value": area}, {"item": "Junctions", "value": nodes}],
            )
        ],
        notes=[
            "Conceptual grid density only; earthing resistance requires soil resistivity and electrode geometry."
        ],
    )


@feature(
    "mepPowerSystems.surgeProtection",
    "Surge Protection",
    part="mep",
    fields=[
        number("load", "Connected load", 100, unit="kVA", min=0),
        number("distance", "Distance to SPD", 20, unit="m", min=0),
    ],
    requires_project=False,
)
def surge_protection(ctx, v):
    return result(
        summary={
            "required": v["distance"] <= 100,
            "distanceM": v["distance"],
            "loadKva": v["load"],
        },
        tables=[
            table(
                "Surge protection",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Distance", "value": v["distance"]},
                    {"item": "Required", "value": v["distance"] <= 100},
                ],
            )
        ],
        notes=[
            "Preliminary location check; coordinated SPD selection requires system voltage and exposure."
        ],
    )

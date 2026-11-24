"""MEP HVAC, ducting, plant and terminal features."""

from __future__ import annotations

import math

from saengine.features import FeatureInputError, feature, number, result, select, table, text


def _raw(ctx):
    raw = ctx.raw("mep")
    if raw is None:
        raise FeatureInputError("Add 07 MEP/mep.json to the project.")
    return raw


@feature(
    "mepHvac.zoneManager",
    "Zone Manager",
    part="mep",
    fields=[
        text("zone", "Zone name", "Zone 1"),
        number("area", "Zone area", 100, unit="m²", min=0.1),
    ],
    requires_project=True,
)
def zone_manager(ctx, v):
    return result(
        summary={"zone": v["zone"], "areaM2": v["area"]},
        tables=[
            table(
                "HVAC zone",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Zone", "value": v["zone"]},
                    {"property": "Area", "value": v["area"]},
                ],
            )
        ],
        notes=["Zone assignment is stored separately from room geometry."],
    )


@feature(
    "mepHvac.airSystems",
    "Air Systems",
    part="mep",
    fields=[
        select(
            "kind",
            "System",
            [
                ("supply", "Supply"),
                ("return", "Return"),
                ("exhaust", "Exhaust"),
                ("fresh", "Fresh air"),
            ],
            "supply",
        ),
        number("flow", "System flow", 1000, unit="l/s", min=0),
    ],
    requires_project=False,
)
def air_systems(ctx, v):
    return result(
        summary={"kind": v["kind"], "flowLPerS": v["flow"]},
        tables=[
            table(
                "Air system",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Kind", "value": v["kind"]}, {"item": "Flow", "value": v["flow"]}],
            )
        ],
        notes=["System flow is used for duct sizing and balancing."],
    )


@feature(
    "mepHvac.systemTypes",
    "System Types",
    part="mep",
    fields=[
        select(
            "type",
            "Type",
            [
                ("constant", "Constant volume"),
                ("vav", "VAV"),
                ("vrf", "VRF"),
                ("fanCoil", "Fan coil"),
            ],
            "vav",
        )
    ],
    requires_project=False,
)
def system_types(ctx, v):
    return result(
        summary={"systemType": v["type"]},
        tables=[table("System type", [("type", "Type")], [{"type": v["type"]}])],
        notes=["System template selection only."],
    )


@feature(
    "mepHvac.terminalUnits",
    "Terminal Units",
    part="mep",
    fields=[
        number("flow", "Terminal flow", 200, unit="l/s", min=0),
        select(
            "kind",
            "Terminal",
            [("diffuser", "Diffuser"), ("grille", "Grille"), ("vav", "VAV box")],
            "diffuser",
        ),
    ],
    requires_project=False,
)
def terminal_units(ctx, v):
    return result(
        summary={"kind": v["kind"], "flowLPerS": v["flow"]},
        tables=[
            table(
                "Terminal unit",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Type", "value": v["kind"]}, {"item": "Flow", "value": v["flow"]}],
            )
        ],
        notes=["Terminal selection requires throw and pressure-loss product data."],
    )


@feature(
    "mepHvac.loadSettings",
    "Load Settings",
    part="mep",
    fields=[
        number("density", "Internal equipment load", 15, unit="W/m²", min=0),
        number("occupancy", "Occupancy load", 70, unit="W/person", min=0),
    ],
    requires_project=False,
)
def load_settings(ctx, v):
    return result(
        summary={"equipmentDensityWPerM2": v["density"], "occupancyWPerPerson": v["occupancy"]},
        tables=[
            table(
                "Load settings",
                [("item", "Value", "W/m²"), ("density", "Density", "W")],
                [
                    {"item": "Equipment", "density": v["density"]},
                    {"item": "Occupancy", "density": v["occupancy"]},
                ],
            )
        ],
        notes=["Load assumptions feed room gain calculations."],
    )


@feature(
    "mepHvac.weatherData",
    "Weather Data",
    part="mep",
    fields=[
        text("location", "Location", ""),
        number("summerDb", "Summer dry bulb", 35, unit="°C"),
        number("winterDb", "Winter dry bulb", 10, unit="°C"),
    ],
    requires_project=False,
)
def weather_data(ctx, v):
    return result(
        summary={"location": v["location"], "summerDbC": v["summerDb"], "winterDbC": v["winterDb"]},
        tables=[
            table(
                "Weather",
                [("season", "Season"), ("dryBulbC", "Dry bulb", "°C")],
                [
                    {"season": "Summer", "dryBulbC": v["summerDb"]},
                    {"season": "Winter", "dryBulbC": v["winterDb"]},
                ],
            )
        ],
        notes=["Use location-specific design weather data; values are direct inputs."],
    )


@feature(
    "mepHvac.internalGains",
    "Internal Gains",
    part="mep",
    fields=[
        number("area", "Area", 100, unit="m²", min=0.1),
        number("people", "People", 10, unit="people", min=0),
        number("equipment", "Equipment load", 15, unit="W/m²", min=0),
        number("lighting", "Lighting load", 10, unit="W/m²", min=0),
    ],
    requires_project=False,
)
def internal_gains(ctx, v):
    sensible = v["area"] * (v["equipment"] + v["lighting"]) / 1000 + v["people"] * 70 / 1000
    return result(
        summary={"sensibleGainKw": sensible},
        tables=[
            table(
                "Internal gains",
                [("source", "Source"), ("gainKw", "Gain", "kW")],
                [
                    {"source": "Equipment", "gainKw": v["area"] * v["equipment"] / 1000},
                    {"source": "Lighting", "gainKw": v["area"] * v["lighting"] / 1000},
                    {"source": "People", "gainKw": v["people"] * 70 / 1000},
                ],
            )
        ],
        notes=["People sensible gain assumed 70 W/person; latent gain requires occupancy type."],
    )


@feature(
    "mepHvacAnalysis.ductSizing",
    "Duct Sizing",
    part="mep",
    fields=[
        number("flow", "Air flow", 1000, unit="l/s", min=1),
        number("friction", "Design friction rate", 1.0, unit="Pa/m", min=0.1),
        number("roughnessMm", "Duct roughness", 0.09, unit="mm", min=0.0),
        number("aspect", "Rectangular aspect ratio a/b", 2.0, min=1.0, max=8.0),
    ],
    requires_project=False,
)
def duct_sizing(ctx, v):
    """Equal-friction duct size: the round diameter whose Darcy-Weisbach friction loss equals
    the design rate, and the rectangular duct of the same loss (Huebscher)."""
    q = v["flow"] / 1000.0  # m³/s
    rho, nu = 1.2, 1.5e-5  # air at about 20 °C: kg/m³, m²/s
    eps = v["roughnessMm"] / 1000.0

    def loss(d: float) -> tuple[float, float]:
        area = math.pi * d * d / 4
        vel = q / area
        re = vel * d / nu
        f = 0.25 / math.log10(eps / (3.7 * d) + 5.74 / re**0.9) ** 2  # Swamee-Jain
        return f / d * rho * vel * vel / 2, vel

    lo, hi = 0.02, 5.0
    for _ in range(80):  # the loss falls as the diameter grows: bisect on it
        mid = (lo + hi) / 2
        if loss(mid)[0] > v["friction"]:
            lo = mid
        else:
            hi = mid
    d = hi
    dp, vel = loss(d)
    # Rectangular a × b with the same equivalent diameter De = 1.30 (ab)^0.625 / (a + b)^0.25.
    r = v["aspect"]
    b = d / (1.30 * r**0.625 / (1 + r) ** 0.25)
    a = r * b
    return result(
        summary={
            "roundDiameterMm": d * 1000,
            "velocityMPerS": vel,
            "frictionPaPerM": dp,
            "rectWidthMm": a * 1000,
            "rectHeightMm": b * 1000,
        },
        tables=[
            table(
                "Equal-friction duct size",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Round diameter [mm]", "value": round(d * 1000)},
                    {"item": "Velocity [m/s]", "value": vel},
                    {"item": "Rectangular a × b [mm]", "value": f"{a * 1000:.0f} × {b * 1000:.0f}"},
                ],
            )
        ],
        notes=[
            "Darcy-Weisbach with the Swamee-Jain friction factor, standard air; round up to the "
            "next stock size and check velocity and noise limits for the space."
        ],
    )

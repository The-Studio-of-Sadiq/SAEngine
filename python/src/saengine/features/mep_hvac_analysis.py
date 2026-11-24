"""HVAC calculation and reporting features."""

from saengine.features import feature, number, result, select, table, text


def _load(ctx):
    raw = ctx.raw("mep")
    return raw.get("hvac", {}) if raw else {}


@feature(
    "mepHvacAnalysis.ductFittings",
    "Duct Fittings",
    part="mep",
    fields=[
        number("velocity", "Velocity", 6, unit="m/s", min=0),
        select(
            "fitting",
            "Fitting",
            [("elbow", "Elbow"), ("tee", "Branch tee"), ("damper", "Damper")],
            "elbow",
        ),
        number("coefficient", "Loss coefficient", 0.3, min=0),
    ],
    requires_project=False,
)
def duct_fittings(ctx, v):
    from saengine.hvac.air import fitting_loss

    out = fitting_loss(v["coefficient"], v["velocity"])
    return result(
        summary={"pressureLossPa": out["dp"], "coefficient": v["coefficient"]},
        tables=[
            table(
                "Duct fitting",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Fitting", "value": v["fitting"]}, {"item": "Loss", "value": out["dp"]}],
            )
        ],
        notes=["Uses dynamic pressure 0.5ρv² and the entered loss coefficient."],
    )


@feature(
    "mepHvacAnalysis.dampers",
    "Dampers",
    part="mep",
    fields=[
        number("flow", "Flow", 500, unit="l/s", min=0),
        number("diameter", "Equivalent diameter", 500, unit="mm", min=50),
    ],
    requires_project=False,
)
def dampers(ctx, v):
    q = v["flow"] / 1000
    d = v["diameter"] / 1000
    velocity = q / (3.14159 * d * d / 4)
    return result(
        summary={"velocityMs": velocity, "damperCount": 1},
        tables=[
            table(
                "Damper",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Velocity", "value": velocity}],
            )
        ],
        notes=["Damper face velocity from flow divided by circular equivalent area."],
    )


@feature(
    "mepHvacAnalysis.uValues",
    "U-Values",
    part="mep",
    fields=[
        number("surface", "Surface resistance", 0.17, unit="m²K/W", min=0),
        number("insulation", "Insulation resistance", 2.5, unit="m²K/W", min=0),
        number("air", "Air resistance", 0.04, unit="m²K/W", min=0),
    ],
    requires_project=False,
)
def u_values(ctx, v):
    u = 1 / (v["surface"] + v["insulation"] + v["air"])
    return result(
        summary={"uValueWPerM2K": u},
        tables=[
            table(
                "U-value",
                [("layer", "Layer"), ("r", "Resistance", "m²K/W")],
                [
                    {"layer": "Surface", "r": v["surface"]},
                    {"layer": "Insulation", "r": v["insulation"]},
                    {"layer": "Air", "r": v["air"]},
                ],
            )
        ],
        notes=["U = 1 / sum of thermal resistances."],
    )


@feature(
    "mepHvacAnalysis.infiltration",
    "Infiltration",
    part="mep",
    fields=[
        number("volume", "Zone volume", 300, unit="m³", min=0),
        number("ach", "Air changes", 0.5, unit="ACH", min=0),
    ],
    requires_project=False,
)
def infiltration(ctx, v):
    flow = v["volume"] * v["ach"] / 3600
    return result(
        summary={"flowM3PerS": flow, "flowLPerS": flow * 1000, "ach": v["ach"]},
        tables=[
            table(
                "Infiltration",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Flow", "value": flow * 1000}],
            )
        ],
        notes=["Flow = volume × ACH / 3600."],
    )


@feature(
    "mepHvacAnalysis.shading",
    "Shading",
    part="mep",
    fields=[
        number("unshaded", "Unshaded solar gain", 1000, unit="W", min=0),
        number("coefficient", "Shading coefficient", 0.5, min=0, max=1),
    ],
    requires_project=False,
)
def shading(ctx, v):
    gain = v["unshaded"] * v["coefficient"]
    return result(
        summary={"solarGainW": gain, "coefficient": v["coefficient"]},
        tables=[
            table(
                "Shading",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Shaded gain", "value": gain}],
            )
        ],
        notes=["Solar gain = unshaded gain × shading coefficient."],
    )


@feature(
    "mepHvacAnalysis.loadReport",
    "Load Report",
    part="mep",
    fields=[text("name", "Report name", "hvac-loads")],
    requires_project=True,
)
def load_report(ctx, v):
    hvac = _load(ctx)
    zones = hvac.get("zones", []) if isinstance(hvac, dict) else []
    return result(
        summary={"zoneCount": len(zones), "report": v["name"]},
        tables=[
            table(
                "Load report",
                [("zone", "Zone"), ("count", "Count")],
                [{"zone": "Zones", "count": len(zones)}],
            )
        ],
        notes=["Room-by-room load data comes from the HVAC project section."],
    )


@feature(
    "mepHvacAnalysis.peakLoads",
    "Peak Loads",
    part="mep",
    fields=[
        number("cooling", "Peak cooling", 100, unit="kW", min=0),
        number("heating", "Peak heating", 60, unit="kW", min=0),
    ],
    requires_project=False,
)
def peak_loads(ctx, v):
    return result(
        summary={"peakCoolingKw": v["cooling"], "peakHeatingKw": v["heating"]},
        tables=[
            table(
                "Peak loads",
                [("load", "Load"), ("value", "Value", "kW")],
                [
                    {"load": "Cooling", "value": v["cooling"]},
                    {"load": "Heating", "value": v["heating"]},
                ],
            )
        ],
        notes=["Peak values are direct calculation inputs."],
    )


@feature(
    "mepHvacAnalysis.zoneSummary", "Zone Summary", part="mep", fields=[], requires_project=True
)
def zone_summary(ctx, v):
    hvac = _load(ctx)
    zones = hvac.get("zones", []) if isinstance(hvac, dict) else []
    rows = [
        {
            "id": z.get("id", ""),
            "area": z.get("area", 0),
            "cooling": z.get("cooling", 0),
            "heating": z.get("heating", 0),
        }
        for z in zones
    ]
    return result(
        summary={"zones": len(rows)},
        tables=[
            table(
                "HVAC zone summary",
                [
                    ("id", "Zone"),
                    ("area", "Area", "m²"),
                    ("cooling", "Cooling", "kW"),
                    ("heating", "Heating", "kW"),
                ],
                rows,
            )
        ],
        notes=["Zone summary is read from the MEP HVAC model."],
    )

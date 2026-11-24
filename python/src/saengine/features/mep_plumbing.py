"""MEP plumbing supply, drainage and fixture features."""

from __future__ import annotations

import json
import math

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
)


def _mep(ctx: FeatureContext):
    raw = ctx.raw("mep")
    if raw is None:
        raise FeatureInputError("Add 07 MEP/mep.json to the project.")
    from saengine.library.mep import parse

    return parse(json.dumps(raw))


@feature(
    "mepPlumbing.coldWaterSizing",
    "Cold Water Sizing",
    part="mep",
    fields=[
        number("flow", "Probable demand", 30, unit="l/min", min=0),
        number("units", "Fixture units", 20, unit="FU", min=0),
        select(
            "material",
            "Pipe material",
            [("uPVC", "uPVC"), ("PPR", "PPR"), ("HDPE", "HDPE"), ("GI", "GI"), ("CI", "CI")],
            "uPVC",
        ),
    ],
    requires_project=False,
)
def cold_water_sizing(ctx, v):
    from saengine.plumbing.supply import size_pipe

    flow = max(v["flow"], 0.0)
    out = size_pipe(flow, v["material"])
    if out["diameter"] is None:
        raise FeatureInputError("The flow exceeds the 200 mm supply-pipe sizing table.")
    return result(
        summary={
            "diameterMm": out["diameter"],
            "velocityMs": out["velocity"],
            "headLossMPer100m": out["headLoss"],
        },
        tables=[
            table(
                "Cold-water pipe",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Probable flow", "value": flow},
                    {"item": "Diameter", "value": out["diameter"]},
                    {"item": "Velocity", "value": round(out["velocity"], 3)},
                ],
            )
        ],
        notes=[
            "Sized with the existing Hazen-Williams and probable-velocity plumbing sizing engine.",
            "Fixture units should be converted by Hunter/fixture-unit tables where a project riser is available.",
        ],
    )


@feature(
    "mepPlumbing.hotWaterDemand",
    "Hot Water Demand",
    part="mep",
    fields=[
        number("occupants", "Occupants", 100, unit="people", min=0),
        number("litresPerPerson", "Hot-water allowance", 50, unit="L/person/day", min=0),
        number("peakFactor", "Peak factor", 1.25, min=1),
    ],
    requires_project=False,
)
def hot_water_demand(ctx, v):
    daily = v["occupants"] * v["litresPerPerson"]
    peak = daily / 24 * v["peakFactor"]
    storage = daily * 0.25
    return result(
        summary={"dailyDemandL": daily, "peakDemandLPerH": peak, "storageVolumeL": storage},
        tables=[
            table(
                "Hot-water demand",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Daily demand", "value": daily},
                    {"item": "Peak demand", "value": peak},
                    {"item": "Storage", "value": storage},
                ],
            )
        ],
        notes=[
            "Storage is 25 percent of daily demand as a transparent planning assumption; confirm recovery and occupancy profiles."
        ],
    )


@feature(
    "mepPlumbing.pressureZones",
    "Pressure Zones",
    part="mep",
    fields=[
        number("topHeight", "Highest fixture level", 45, unit="m", min=0),
        number("bottomHeight", "Lowest fixture level", 0, unit="m", min=0),
        number("maxStatic", "Maximum static head", 35, unit="m", min=1),
    ],
    requires_project=False,
)
def pressure_zones(ctx, v):
    span = v["topHeight"] - v["bottomHeight"]
    zones = max(1, math.ceil(span / v["maxStatic"]))
    return result(
        summary={"zones": zones, "staticSpanM": span, "maxStaticHeadM": v["maxStatic"]},
        tables=[
            table(
                "Pressure zones",
                [("zone", "Zone"), ("lowerM", "Lower level", "m"), ("upperM", "Upper level", "m")],
                [
                    {
                        "zone": i + 1,
                        "lowerM": i * v["maxStatic"],
                        "upperM": min((i + 1) * v["maxStatic"], span),
                    }
                    for i in range(zones)
                ],
            )
        ],
        notes=[
            "Zones are determined by equal static-head bands; intermediate tanks or pressure-reducing valves are required where zones are more than one."
        ],
    )


@feature(
    "mepPlumbing.pipeMaterials",
    "Pipe Materials",
    part="mep",
    fields=[
        select(
            "service",
            "Service",
            [
                ("cold", "Domestic cold"),
                ("hot", "Domestic hot"),
                ("soil", "Soil"),
                ("rain", "Rainwater"),
            ],
            "cold",
        ),
        select(
            "material",
            "Material",
            [("uPVC", "uPVC"), ("PPR", "PPR"), ("HDPE", "HDPE"), ("GI", "GI"), ("CI", "CI")],
            "uPVC",
        ),
    ],
    requires_project=True,
)
def pipe_materials(ctx, v):
    mep = _mep(ctx)
    risers = getattr(mep.plumbing, "risers", []) if mep.plumbing else []
    return result(
        summary={"service": v["service"], "material": v["material"], "risers": len(risers)},
        tables=[
            table(
                "Pipe material assignment",
                [("id", "Riser"), ("system", "System"), ("material", "Material")],
                [{"id": r.id, "system": r.system, "material": v["material"]} for r in risers],
            )
        ],
        notes=[
            "Assignment is a schedule decision; compatibility and temperature limits require the selected pipe standard."
        ],
    )


@feature(
    "mepPlumbing.fixtureUnits",
    "Fixture Units",
    part="mep",
    fields=[
        select(
            "fixture",
            "Fixture",
            [
                ("wc", "Water closet"),
                ("urinal", "Urinal"),
                ("basin", "Basin"),
                ("shower", "Shower"),
                ("kitchenSink", "Kitchen sink"),
                ("washingMachine", "Washing machine"),
            ],
            "wc",
        ),
        number("count", "Fixture count", 10, unit="fixtures", min=0),
        checkbox("flushValves", "Flush valves", False),
    ],
    requires_project=False,
)
def fixture_units(ctx, v):
    from types import SimpleNamespace

    from saengine.plumbing.demand import FIXTURES, supply_units

    data = {k: 0 for k in FIXTURES}
    data[v["fixture"]] = int(v["count"])
    fixture = SimpleNamespace(**data, other=[])
    units, minimum, _ = supply_units(fixture, "total", v["flushValves"])
    return result(
        summary={"fixtureUnits": units, "minimumPipeMm": minimum, "count": int(v["count"])},
        tables=[
            table(
                "Fixture-unit result",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Fixture units", "value": units},
                    {"item": "Minimum supply pipe", "value": minimum},
                ],
            )
        ],
        notes=["Uses the existing plumbing fixture-unit and minimum-pipe tables."],
    )


@feature(
    "mepPlumbing.fixtureSchedule", "Fixture Schedule", part="mep", fields=[], requires_project=True
)
def fixture_schedule(ctx, v):
    mep = _mep(ctx)
    stories = getattr(mep.plumbing, "stories", []) if mep.plumbing else []
    rows = [
        {
            "story": s.story,
            "wc": getattr(s.fixtures, "wc", 0),
            "basins": getattr(s.fixtures, "basin", 0),
            "showers": getattr(s.fixtures, "shower", 0),
            "sinks": getattr(s.fixtures, "kitchenSink", 0),
        }
        for s in stories
    ]
    return result(
        summary={
            "floorEntries": len(rows),
            "fixtures": sum(r["wc"] + r["basins"] + r["showers"] + r["sinks"] for r in rows),
        },
        tables=[
            table(
                "Fixture schedule",
                [
                    ("story", "Story"),
                    ("wc", "WCs"),
                    ("basins", "Basins"),
                    ("showers", "Showers"),
                    ("sinks", "Kitchen sinks"),
                ],
                rows,
            )
        ],
        notes=["Counts fixtures on each 07 MEP plumbing story."],
    )


@feature(
    "mepPlumbing.tapPoints",
    "Tap Points",
    part="mep",
    fields=[
        number("count", "Tap points", 1, unit="points", min=1),
        number("distance", "Spacing", 300, unit="mm", min=100),
    ],
    requires_project=True,
)
def tap_points(ctx, v):
    mep = _mep(ctx)
    stories = getattr(mep.plumbing, "stories", []) if mep.plumbing else []
    rows = [{"story": s.story, "count": int(v["count"]), "spacing": v["distance"]} for s in stories]
    return result(
        summary={"tapPoints": len(rows) * int(v["count"]), "spacingMm": v["distance"]},
        tables=[
            table(
                "Tap-point schedule",
                [("story", "Story"), ("count", "Points"), ("spacing", "Spacing", "mm")],
                rows,
            )
        ],
        notes=["Placement points are schematic and require a room or wall coordinate set."],
    )


@feature(
    "mepPlumbing.wasteBranchSizing",
    "Waste Branch Sizing",
    part="mep",
    fields=[
        number("units", "Drainage fixture units", 30, unit="DFU", min=0),
        number("outlet", "Largest outlet", 50, unit="mm", min=25),
    ],
    requires_project=False,
)
def waste_branch_sizing(ctx, v):
    from saengine.plumbing.drainage import branch_size

    d = branch_size(v["units"], v["outlet"])
    if d is None:
        raise FeatureInputError("The fixture units exceed the drainage stack table.")
    return result(
        summary={"diameterMm": d, "dfu": v["units"]},
        tables=[
            table(
                "Waste branch",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Diameter", "value": d}, {"item": "Fixture units", "value": v["units"]}],
            )
        ],
        notes=["Uses the existing drainage fixture-unit table."],
    )


@feature(
    "mepPlumbing.stackOffsets",
    "Stack Offsets",
    part="mep",
    fields=[
        number("length", "Offset length", 1000, unit="mm", min=0),
        number("angle", "Offset angle", 45, unit="°", min=0, max=90),
    ],
    requires_project=False,
)
def stack_offsets(ctx, v):
    a = math.radians(v["angle"])
    horizontal = v["length"] * math.cos(a)
    vertical = v["length"] * math.sin(a)
    return result(
        summary={"offsetLengthMm": v["length"], "horizontalMm": horizontal, "verticalMm": vertical},
        tables=[
            table(
                "Stack offset",
                [("component", "Component"), ("value", "Value", "mm")],
                [
                    {"component": "Horizontal", "value": horizontal},
                    {"component": "Vertical", "value": vertical},
                ],
            )
        ],
        notes=[
            "Right-triangle resolution of an offset; fitting losses require separate equivalent-length checks."
        ],
    )


@feature(
    "mepPlumbing.floorDrainLayout",
    "Floor Drain Layout",
    part="mep",
    fields=[
        number("area", "Drainage area", 100, unit="m²", min=0.1),
        number("areaPerDrain", "Area per drain", 50, unit="m²/drain", min=1),
    ],
    requires_project=True,
)
def floor_drain_layout(ctx, v):
    count = max(1, math.ceil(v["area"] / v["areaPerDrain"]))
    return result(
        summary={"drainCount": count, "spacingEstimateM": math.sqrt(v["area"] / count)},
        tables=[
            table(
                "Floor drain layout",
                [("drain", "Drain"), ("zoneAreaM2", "Area", "m²")],
                [{"drain": i + 1, "zoneAreaM2": v["area"] / count} for i in range(count)],
            )
        ],
        notes=[
            "Equal-area estimate only; coordinate floor falls and local outlet positions explicitly."
        ],
    )


@feature(
    "mepPlumbing.drainGradient",
    "Drain Gradient",
    part="mep",
    fields=[
        number("length", "Run length", 20, unit="m", min=0.1),
        number("fall", "Vertical fall", 0.2, unit="m", min=0),
    ],
    requires_project=False,
)
def drain_gradient(ctx, v):
    gradient = v["fall"] / v["length"]
    percent = gradient * 100
    return result(
        summary={"gradient": gradient, "fallPercent": percent, "lengthM": v["length"]},
        tables=[
            table(
                "Drain gradient",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Gradient", "value": gradient}, {"item": "Fall", "value": percent}],
            )
        ],
        notes=[
            "Gradient = fall / length. Use a practical self-cleansing slope and verify minimum/maximum velocity."
        ],
    )


@feature(
    "mepPlumbing.pipeVelocityCheck",
    "Pipe Velocity Check",
    part="mep",
    fields=[
        number("flow", "Flow", 30, unit="l/min", min=0),
        number("diameter", "Bore", 40, unit="mm", min=1),
        number("limit", "Velocity limit", 2.5, unit="m/s", min=0.1),
    ],
    requires_project=False,
)
def pipe_velocity_check(ctx, v):
    from saengine.plumbing.supply import velocity

    vel = velocity(v["flow"], v["diameter"])
    return result(
        summary={"velocityMs": vel, "limitMs": v["limit"], "ok": vel <= v["limit"]},
        tables=[
            table(
                "Velocity check",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Calculated", "value": round(vel, 3)},
                    {"item": "Limit", "value": v["limit"]},
                    {"item": "Pass", "value": vel <= v["limit"]},
                ],
            )
        ],
        notes=["Uses flow area Q/(πD²/4)."],
    )


@feature(
    "mepPlumbing.pressureDropCalc",
    "Pressure Drop Calc",
    part="mep",
    fields=[
        number("flow", "Flow", 30, unit="l/min", min=0),
        number("diameter", "Bore", 40, unit="mm", min=1),
        number("length", "Pipe length", 20, unit="m", min=0),
        select(
            "material",
            "Material",
            [("uPVC", "uPVC"), ("PPR", "PPR"), ("HDPE", "HDPE"), ("GI", "GI"), ("CI", "CI")],
            "uPVC",
        ),
    ],
    requires_project=False,
)
def pressure_drop_calc(ctx, v):
    from saengine.plumbing.supply import head_loss

    loss = (
        head_loss(
            v["flow"],
            v["diameter"],
            {"uPVC": 150, "PPR": 150, "HDPE": 150, "GI": 120, "CI": 100}[v["material"]],
        )
        * v["length"]
        / 100
    )
    return result(
        summary={"pressureLossM": loss, "pressureLossKpa": loss * 9.807, "lengthM": v["length"]},
        tables=[
            table(
                "Pressure drop",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Head loss", "value": loss},
                    {"item": "Pressure loss", "value": loss * 9.807},
                ],
            )
        ],
        notes=["Uses Hazen-Williams friction head loss with material roughness coefficients."],
    )


@feature(
    "mepPlumbing.waterMeterSize",
    "Water Meter Size",
    part="mep",
    fields=[
        number("flow", "Peak flow", 30, unit="l/min", min=0),
        number("nominalRate", "Meter rated flow", 60, unit="l/min", min=1),
    ],
    requires_project=False,
)
def water_meter_size(ctx, v):
    ratios = [(15, 30), (20, 50), (25, 100), (40, 250), (50, 500)]
    fit = next((d for d, r in ratios if r >= v["flow"]), ratios[-1][0])
    ratio = v["flow"] / v["nominalRate"]
    return result(
        summary={"suggestedNominalMm": fit, "flowRatio": ratio, "ok": ratio <= 1},
        tables=[
            table(
                "Water meter",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Suggested nominal", "value": fit},
                    {"item": "Peak/rated", "value": ratio},
                ],
            )
        ],
        notes=[
            "Selection is preliminary; verify the meter pressure loss curve and maximum continuous flow."
        ],
    )


@feature(
    "mepPlumbing.pumpHeadEstimate",
    "Pump Head Estimate",
    part="mep",
    fields=[
        number("static", "Static lift", 30, unit="m", min=0),
        number("friction", "Friction head", 8, unit="m", min=0),
        number("residual", "Residual fixture head", 10, unit="m", min=0),
    ],
    requires_project=False,
)
def pump_head_estimate(ctx, v):
    head = v["static"] + v["friction"] + v["residual"]
    return result(
        summary={
            "totalHeadM": head,
            "staticM": v["static"],
            "frictionM": v["friction"],
            "residualM": v["residual"],
        },
        tables=[
            table(
                "Pump head",
                [("component", "Component"), ("headM", "Head", "m")],
                [
                    {"component": "Static", "headM": v["static"]},
                    {"component": "Friction", "headM": v["friction"]},
                    {"component": "Residual", "headM": v["residual"]},
                    {"component": "Total", "headM": head},
                ],
            )
        ],
        notes=["Total required head = static lift + friction loss + required residual head."],
    )


@feature(
    "mepPlumbing.waterClosetFlow",
    "Water Closet Flow",
    part="mep",
    fields=[
        number("count", "Water closets", 10, unit="fixtures", min=0),
        checkbox("flushValves", "Flush valves", False),
    ],
    requires_project=False,
)
def water_closet_flow(ctx, v):
    from saengine.plumbing.demand import hunter_flow

    units = v["count"] * (2.5 if v["flushValves"] else 2.0)
    flow = hunter_flow(units, v["flushValves"])
    return result(
        summary={"fixtureUnits": units, "probableFlowLPerMin": flow},
        tables=[
            table(
                "WC demand",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Units", "value": units}, {"item": "Probable flow", "value": flow}],
            )
        ],
        notes=["Uses existing probable-demand Hunter calculation and fixture unit estimate."],
    )


@feature(
    "mepPlumbing.urinalFlowRate",
    "Urinal Flow Rate",
    part="mep",
    fields=[
        number("count", "Urinals", 5, unit="fixtures", min=0),
        number("flowEach", "Flow per urinal", 4, unit="l/min", min=0),
        select(
            "type", "Type", [("manual", "Manual"), ("sensor", "Sensor"), ("tank", "Tank")], "sensor"
        ),
    ],
    requires_project=False,
)
def urinal_flow_rate(ctx, v):
    flow = v["count"] * v["flowEach"]
    return result(
        summary={"totalFlowLPerMin": flow, "count": int(v["count"])},
        tables=[
            table(
                "Urinal flow",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Type", "value": v["type"]}, {"item": "Flow", "value": flow}],
            )
        ],
        notes=["Coincident demand is not assumed; apply diversity for a riser."],
    )


@feature(
    "mepPlumbing.basinFlowRate",
    "Basin Flow Rate",
    part="mep",
    fields=[
        number("count", "Basins", 10, unit="fixtures", min=0),
        number("flowEach", "Flow per basin", 6, unit="l/min", min=0),
    ],
    requires_project=False,
)
def basin_flow_rate(ctx, v):
    flow = v["count"] * v["flowEach"]
    return result(
        summary={"totalFlowLPerMin": flow, "count": int(v["count"])},
        tables=[
            table(
                "Basin flow",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Concurrent demand", "value": flow}],
            )
        ],
        notes=[
            "Coincident flow is entered by the user; a design diversity factor can be applied separately."
        ],
    )


@feature(
    "mepPlumbing.showerFlowRate",
    "Shower Flow Rate",
    part="mep",
    fields=[
        number("count", "Showers", 10, unit="fixtures", min=0),
        number("flowEach", "Flow per shower", 9, unit="l/min", min=0),
    ],
    requires_project=False,
)
def shower_flow_rate(ctx, v):
    flow = v["count"] * v["flowEach"]
    return result(
        summary={"totalFlowLPerMin": flow, "count": int(v["count"])},
        tables=[
            table(
                "Shower flow",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Flow", "value": flow}],
            )
        ],
        notes=["Coincident flow is proportional to count and the specified flow per shower."],
    )


@feature(
    "mepPlumbing.roofDrainSizing",
    "Roof Drain Sizing",
    part="mep",
    fields=[
        number("area", "Roof area", 500, unit="m²", min=0.1),
        number("rainfall", "Rainfall intensity", 100, unit="mm/h", min=0),
        number("runoff", "Runoff coefficient", 0.9, min=0, max=1),
    ],
    requires_project=False,
)
def roof_drain_sizing(ctx, v):
    flow = v["area"] / 3600 * v["rainfall"] * v["runoff"] * 1000
    diameter = next(
        (
            d
            for d in (75, 100, 150, 200, 250, 300)
            if math.pi * (d / 2000) ** 2 * 2 * 1000 >= flow / 1000
        ),
        300,
    )
    return result(
        summary={"flowLPerS": flow, "nominalDiameterMm": diameter},
        tables=[
            table(
                "Roof drainage",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Flow", "value": flow}, {"item": "Diameter", "value": diameter}],
            )
        ],
        notes=["Uses rational-method flow Q = C i A/3600 converted to litres/second."],
    )


@feature(
    "mepPlumbing.downpipeSizing",
    "Downpipe Sizing",
    part="mep",
    fields=[
        number("flow", "Flow", 5, unit="l/s", min=0),
        number("velocity", "Target velocity", 2.0, unit="m/s", min=0.1),
    ],
    requires_project=False,
)
def downpipe_sizing(ctx, v):
    d = math.sqrt(4 * (v["flow"] / 1000) / (math.pi * v["velocity"])) * 1000
    standard = next((x for x in (75, 100, 150, 200, 250, 300) if x >= d), 300)
    return result(
        summary={"requiredBoreMm": d, "suggestedNominalMm": standard},
        tables=[
            table(
                "Downpipe size",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Required bore", "value": d},
                    {"item": "Suggested nominal", "value": standard},
                ],
            )
        ],
        notes=["Diameter from continuity Q=vA."],
    )


@feature(
    "mepPlumbing.gutterSizing",
    "Gutter Sizing",
    part="mep",
    fields=[
        number("flow", "Flow", 5, unit="l/s", min=0),
        number("width", "Gutter width", 300, unit="mm", min=50),
        number("depth", "Water depth", 50, unit="mm", min=10),
    ],
    requires_project=False,
)
def gutter_sizing(ctx, v):
    area = v["width"] * v["depth"] / 1e6
    velocity = v["flow"] / 1000 / area
    return result(
        summary={"flowLPerS": v["flow"], "velocityMs": velocity, "areaMm2": area * 1e6},
        tables=[
            table(
                "Gutter sizing",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Cross-sectional area", "value": area * 1e6},
                    {"item": "Velocity", "value": velocity},
                ],
            )
        ],
        notes=[
            "Continuity sizing with rectangular section; add fall, outlet and surcharge checks."
        ],
    )


@feature(
    "mepPlumbing.overflowCheck",
    "Overflow Check",
    part="mep",
    fields=[
        number("inflow", "Design inflow", 5, unit="l/s", min=0),
        number("outflow", "Drainage outflow", 5, unit="l/s", min=0),
    ],
    requires_project=False,
)
def overflow_check(ctx, v):
    margin = v["outflow"] - v["inflow"]
    ok = margin >= 0
    return result(
        summary={"capacityMarginLPerS": margin, "ok": ok},
        tables=[
            table(
                "Overflow check",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Inflow", "value": v["inflow"]},
                    {"item": "Outflow", "value": v["outflow"]},
                    {"item": "Pass", "value": ok},
                ],
            )
        ],
        notes=["Fail if inflow exceeds the independently sized drainage capacity."],
    )

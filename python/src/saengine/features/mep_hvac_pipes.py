"""Hydronic piping, distribution losses and expansion features."""

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
)


@feature(
    "mepHvacPipes.pipeSize",
    "Pipe Size",
    part="mep",
    fields=[
        number("flowLs", "Water flow", 3, unit="L/s", min=0),
        number("velocityMs", "Target velocity", 1.5, unit="m/s", min=0.1),
    ],
    requires_project=False,
)
def pipe_size(ctx: FeatureContext, v: dict) -> dict:
    """Estimate internal hydronic pipe diameter from flow and velocity."""
    d = math.sqrt(4 * v["flowLs"] / 1000 / (math.pi * v["velocityMs"])) * 1000
    return result(
        {"minimumInternalDiameterMm": d},
        notes=[
            "Continuity estimate; choose standard bore and check pressure gradient, noise and erosion."
        ],
    )


@feature(
    "mepHvacPipes.velocityLimit",
    "Velocity Limit",
    part="mep",
    fields=[
        number("flowLs", "Water flow", 2, unit="L/s", min=0),
        number("diameterMm", "Internal diameter", 50, unit="mm", min=1),
        number("maximumVelocityMs", "Maximum velocity", 2, unit="m/s", min=0.1),
    ],
    requires_project=False,
)
def velocity_limit(ctx: FeatureContext, v: dict) -> dict:
    """Check actual pipe velocity against an entered design limit."""
    velocity = v["flowLs"] / 1000 / (math.pi * (v["diameterMm"] / 1000) ** 2 / 4)
    return result(
        {
            "velocityMs": velocity,
            "maximumVelocityMs": v["maximumVelocityMs"],
            "pass": velocity <= v["maximumVelocityMs"],
        }
    )


@feature(
    "mepHvacPipes.frictionLimit",
    "Friction Limit",
    part="mep",
    fields=[
        number("flowLs", "Water flow", 1.5, unit="L/s", min=0),
        number("diameterMm", "Internal diameter", 50, unit="mm", min=1),
        number("darcyFactor", "Darcy friction factor", 0.025, min=0.001),
        number("maximumKpaPerM", "Maximum pressure gradient", 0.3, unit="kPa/m", min=0),
    ],
    requires_project=False,
)
def friction_limit(ctx: FeatureContext, v: dict) -> dict:
    """Calculate Darcy-Weisbach pressure gradient and compare with its limit."""
    d, q = v["diameterMm"] / 1000, v["flowLs"] / 1000
    speed = q / (math.pi * d**2 / 4)
    gradient = v["darcyFactor"] / d * 1000 * speed**2 / 2 / 1000
    return result(
        {
            "velocityMs": speed,
            "pressureGradientKpaPerM": gradient,
            "pass": gradient <= v["maximumKpaPerM"],
        },
        notes=["Water density is 1000 kg/m³; straight pipe only, with fittings excluded."],
    )


@feature(
    "mepHvacPipes.autoRoute",
    "Auto Route",
    part="mep",
    fields=[
        number("startXM", "Start X", 0, unit="m"),
        number("startYM", "Start Y", 0, unit="m"),
        number("endXM", "End X", 10, unit="m"),
        number("endYM", "End Y", 5, unit="m"),
        select("firstLeg", "First leg", ["x", "y"]),
    ],
    requires_project=False,
)
def auto_route(ctx: FeatureContext, v: dict) -> dict:
    """Construct an orthogonal two-leg route between entered endpoints."""
    mid = [v["endXM"], v["startYM"]] if v["firstLeg"] == "x" else [v["startXM"], v["endYM"]]
    points = [[v["startXM"], v["startYM"]], mid, [v["endXM"], v["endYM"]]]
    length = sum(math.dist(points[i], points[i + 1]) for i in range(2))
    return result(
        {"routeLengthM": length},
        [
            table(
                "Route coordinates",
                [("sequence", "Sequence"), ("xM", "X", "m"), ("yM", "Y", "m")],
                [{"sequence": i + 1, "xM": p[0], "yM": p[1]} for i, p in enumerate(points)],
            )
        ],
        ["Geometric route only; it does not avoid structure or other services."],
    )


@feature(
    "mepHvacPipes.insulationType",
    "Insulation Type",
    part="mep",
    fields=[
        select(
            "material", "Insulation material", ["mineral wool", "elastomeric foam", "polyethylene"]
        ),
        number("conductivityWmK", "Thermal conductivity", 0.035, unit="W/(m·K)", min=0.001),
        number("pipeDiameterMm", "Pipe outside diameter", 50, unit="mm", min=1),
    ],
    requires_project=False,
)
def insulation_type(ctx: FeatureContext, v: dict) -> dict:
    """Report the selected insulation material and cylindrical resistance basis."""
    return result(
        {
            "material": v["material"],
            "conductivityWmK": v["conductivityWmK"],
            "pipeDiameterMm": v["pipeDiameterMm"],
        },
        notes=[
            "Material conductivity is an input; thickness and operating temperature are needed to calculate heat transfer."
        ],
    )


@feature(
    "mepHvacPipes.insulationThickness",
    "Insulation Thickness",
    part="mep",
    fields=[
        number("pipeDiameterMm", "Pipe outside diameter", 50, unit="mm", min=1),
        number("innerTemperatureC", "Pipe temperature", 6, unit="°C"),
        number("ambientTemperatureC", "Ambient temperature", 30, unit="°C"),
        number("conductivityWmK", "Insulation conductivity", 0.035, unit="W/(m·K)", min=0.001),
        number("heatLossWPerM", "Allowed heat transfer", 10, unit="W/m", min=0.1),
    ],
    requires_project=False,
)
def insulation_thickness(ctx: FeatureContext, v: dict) -> dict:
    """Solve cylindrical insulation thickness for the entered heat-transfer limit."""
    r1 = v["pipeDiameterMm"] / 2000
    delta = abs(v["ambientTemperatureC"] - v["innerTemperatureC"])
    r2 = r1 * math.exp(2 * math.pi * v["conductivityWmK"] * delta / v["heatLossWPerM"])
    return result(
        {"requiredThicknessMm": (r2 - r1) * 1000},
        notes=[
            "Steady radial conduction in insulation only; surface films, fittings and condensation control are excluded."
        ],
    )


@feature(
    "mepHvacPipes.vapourBarrier",
    "Vapour Barrier",
    part="mep",
    fields=[
        number("surfaceTemperatureC", "Insulated surface temperature", 12, unit="°C"),
        number("dewPointC", "Ambient dew point", 18, unit="°C"),
        number("safetyMarginC", "Required margin", 2, unit="°C", min=0),
    ],
    requires_project=False,
)
def vapour_barrier(ctx: FeatureContext, v: dict) -> dict:
    """Check whether the surface remains above dew point plus the selected margin."""
    margin = v["surfaceTemperatureC"] - v["dewPointC"]
    return result(
        {"surfaceDewPointMarginC": margin, "barrierRequired": margin < v["safetyMarginC"]},
        notes=[
            "Vapour sealing is required where condensation risk exists; verify continuity at joints and supports."
        ],
    )


@feature(
    "mepHvacPipes.condensationCheck",
    "Condensation Check",
    part="mep",
    fields=[
        number("airTemperatureC", "Room air temperature", 26, unit="°C"),
        number("relativeHumidityPercent", "Relative humidity", 60, unit="%", min=1, max=100),
        number("surfaceTemperatureC", "Pipe surface temperature", 12, unit="°C"),
    ],
    requires_project=False,
)
def condensation_check(ctx: FeatureContext, v: dict) -> dict:
    """Estimate room dew point and check a pipe surface for condensation."""
    gamma = math.log(v["relativeHumidityPercent"] / 100) + 17.62 * v["airTemperatureC"] / (
        243.12 + v["airTemperatureC"]
    )
    dewpoint = 243.12 * gamma / (17.62 - gamma)
    return result(
        {
            "dewPointC": dewpoint,
            "surfaceMarginC": v["surfaceTemperatureC"] - dewpoint,
            "condensationRisk": v["surfaceTemperatureC"] <= dewpoint,
        },
        notes=[
            "Magnus approximation for ordinary indoor conditions; local humidity at the pipe may differ from room conditions."
        ],
    )


@feature(
    "mepHvacPipes.elbowFitting",
    "Elbow Fitting",
    part="mep",
    fields=[
        number("pipeDiameterMm", "Pipe diameter", 50, unit="mm", min=1),
        number("centerlineRadiusMm", "Elbow centerline radius", 75, unit="mm", min=1),
        number("turnAngleDeg", "Turn angle", 90, unit="deg", min=1, max=180),
    ],
    requires_project=False,
)
def elbow_fitting(ctx: FeatureContext, v: dict) -> dict:
    """Calculate elbow centerline arc length and bend-radius ratio."""
    arc = math.radians(v["turnAngleDeg"]) * v["centerlineRadiusMm"]
    return result(
        {
            "centerlineArcLengthMm": arc,
            "radiusToDiameterRatio": v["centerlineRadiusMm"] / v["pipeDiameterMm"],
        }
    )


@feature(
    "mepHvacPipes.valveInsert",
    "Valve Insert",
    part="mep",
    fields=[
        number("flowLs", "Design flow", 2, unit="L/s", min=0),
        number("valveKv", "Valve Kv", 12, min=0.01),
    ],
    requires_project=False,
)
def valve_insert(ctx: FeatureContext, v: dict) -> dict:
    """Estimate pressure drop through a water valve using its Kv coefficient."""
    drop = (v["flowLs"] * 3.6 / v["valveKv"]) ** 2 * 100
    return result(
        {"valvePressureDropKpa": drop, "flowLs": v["flowLs"]},
        notes=[
            "Metric Kv relation for water near ambient temperature; use manufacturer data at the operating position."
        ],
    )


@feature(
    "mepHvacPipes.pipeSupport",
    "Pipe Support",
    part="mep",
    fields=[
        number("runLengthM", "Run length", 30, unit="m", min=0),
        number("supportSpacingM", "Maximum support spacing", 2.5, unit="m", min=0.1),
        number("endOffsetM", "End offset", 0.3, unit="m", min=0),
    ],
    requires_project=False,
)
def pipe_support(ctx: FeatureContext, v: dict) -> dict:
    """Estimate support count for a straight pipe run and end offsets."""
    span = max(0, v["runLengthM"] - 2 * v["endOffsetM"])
    return result(
        {
            "supportCount": max(2, math.ceil(span / v["supportSpacingM"]) + 1),
            "runLengthM": v["runLengthM"],
        },
        notes=[
            "Simple straight-run layout; support spacing depends on pipe material, size, temperature and contents."
        ],
    )


@feature(
    "mepHvacPipes.fittingSchedule",
    "Fitting Schedule",
    part="mep",
    fields=[
        number("elbows", "Elbow count", 12, min=0),
        number("tees", "Tee count", 4, min=0),
        number("valves", "Valve count", 3, min=0),
        number("reducers", "Reducer count", 2, min=0),
    ],
    requires_project=False,
)
def fitting_schedule(ctx: FeatureContext, v: dict) -> dict:
    """Compile entered hydronic fitting counts into a schedule."""
    rows = [
        {"fitting": name, "quantity": int(v[key])}
        for key, name in [
            ("elbows", "Elbow"),
            ("tees", "Tee"),
            ("valves", "Valve"),
            ("reducers", "Reducer"),
        ]
    ]
    return result(
        {"fittingCount": sum(row["quantity"] for row in rows)},
        [table("Pipe fitting schedule", [("fitting", "Fitting"), ("quantity", "Quantity")], rows)],
    )


@feature(
    "mepHvacPipes.primarySecondaryLoop",
    "Primary Secondary Loop",
    part="mep",
    fields=[
        number("primaryFlowLs", "Primary flow", 12, unit="L/s", min=0),
        number("secondaryFlowLs", "Secondary flow", 10, unit="L/s", min=0),
        number("primarySupplyC", "Primary supply temperature", 6, unit="°C"),
        number("secondaryReturnC", "Secondary return temperature", 12, unit="°C"),
    ],
    requires_project=False,
)
def primary_secondary_loop(ctx: FeatureContext, v: dict) -> dict:
    """Calculate the decoupler flow direction and magnitude for two loops."""
    difference = v["primaryFlowLs"] - v["secondaryFlowLs"]
    direction = (
        "primary-to-secondary"
        if difference > 0
        else "secondary-to-primary"
        if difference < 0
        else "balanced"
    )
    return result(
        {
            "decouplerFlowLs": abs(difference),
            "flowDirection": direction,
            "temperatureDifferenceC": v["secondaryReturnC"] - v["primarySupplyC"],
        },
        notes=[
            "Steady flow comparison at the common pipe; thermal mixing depends on connection arrangement."
        ],
    )


@feature(
    "mepHvacPipes.expansionTankSize",
    "Expansion Tank Size",
    part="mep",
    fields=[
        number("systemVolumeL", "System water volume", 1500, unit="L", min=0),
        number("temperatureRiseC", "Temperature rise", 50, unit="°C", min=0),
        number("coldPressureKpa", "Cold fill pressure", 150, unit="kPa", min=1),
        number("maximumPressureKpa", "Maximum pressure", 400, unit="kPa", min=1),
    ],
    requires_project=False,
)
def expansion_tank_size(ctx: FeatureContext, v: dict) -> dict:
    """Estimate expansion vessel acceptance volume and nominal size."""
    expansion = v["systemVolumeL"] * 0.00021 * v["temperatureRiseC"]
    p1, p2 = v["coldPressureKpa"] + 101.325, v["maximumPressureKpa"] + 101.325
    if p2 <= p1:
        raise FeatureInputError("Maximum pressure must exceed cold fill pressure.")
    acceptance = 1 - p1 / p2
    nominal = expansion / acceptance
    return result(
        {"waterExpansionL": expansion, "minimumVesselVolumeL": nominal},
        notes=[
            "Water expansion coefficient is approximated as 0.00021/K; includes absolute-pressure correction but not reserve volume or manufacturer factors."
        ],
    )


@feature(
    "mepHvacPipes.airSeparatorLocation",
    "Air Separator Location",
    part="mep",
    fields=[
        number("systemPressureKpa", "System pressure", 200, unit="kPa", min=0),
        number("temperatureC", "Water temperature", 60, unit="°C", min=0),
        number("separatorLocationHeightM", "Location height above reference", 5, unit="m"),
    ],
    requires_project=False,
)
def air_separator_location(ctx: FeatureContext, v: dict) -> dict:
    """Estimate local pressure at the proposed air-separator elevation."""
    local = v["systemPressureKpa"] - 9.80665 * v["separatorLocationHeightM"]
    return result(
        {
            "estimatedLocalPressureKpa": local,
            "absolutePressureKpa": local + 101.325,
            "temperatureC": v["temperatureC"],
        },
        notes=[
            "Hydrostatic pressure adjustment using water density 1000 kg/m³; compare against the pump suction and expansion-tank connection point."
        ],
    )


@feature(
    "mepHvacPipes.balancingValveSet",
    "Balancing Valve Set",
    part="mep",
    fields=[
        number("designFlowLs", "Design flow", 1.8, unit="L/s", min=0),
        number("measuredFlowLs", "Measured flow", 1.6, unit="L/s", min=0),
        number("measuredDropKpa", "Measured valve drop", 15, unit="kPa", min=0),
    ],
    requires_project=False,
)
def balancing_valve_set(ctx: FeatureContext, v: dict) -> dict:
    """Calculate flow error and valve resistance coefficient from commissioning data."""
    error = (
        (v["measuredFlowLs"] - v["designFlowLs"]) / v["designFlowLs"] * 100
        if v["designFlowLs"]
        else 0
    )
    kv = (
        v["measuredFlowLs"] * 3.6 / math.sqrt(v["measuredDropKpa"] / 100)
        if v["measuredDropKpa"]
        else None
    )
    return result(
        {"flowErrorPercent": error, "inferredKv": kv},
        notes=[
            "Inferred Kv uses measured flow and pressure drop for water; valve position is not inferred without product characteristics."
        ],
    )


@feature(
    "mepHvacPipes.pumpHeadCalculation",
    "Pump Head Calculation",
    part="mep",
    fields=[
        number("staticHeadM", "Static head", 8, unit="m", min=0),
        number("criticalPathLossM", "Critical-path loss", 18, unit="m", min=0),
        number("terminalPressureM", "Required terminal pressure", 3, unit="m", min=0),
    ],
    requires_project=False,
)
def pump_head_calculation(ctx: FeatureContext, v: dict) -> dict:
    """Sum static head, critical-path loss and terminal pressure requirement."""
    return result(
        {"totalDynamicHeadM": v["staticHeadM"] + v["criticalPathLossM"] + v["terminalPressureM"]},
        notes=[
            "Open-system head sum; closed-loop hydronic static head cancels and should not be included."
        ],
    )


@feature(
    "mepHvacPipes.systemCurveOverlay",
    "System Curve Overlay",
    part="mep",
    fields=[
        number("designFlowLs", "Design flow", 4, unit="L/s", min=0.1),
        number("designHeadM", "Design head", 22, unit="m", min=0),
        number("maximumFlowLs", "Maximum plotted flow", 6, unit="L/s", min=0.1),
    ],
    requires_project=False,
)
def system_curve_overlay(ctx: FeatureContext, v: dict) -> dict:
    """Generate a quadratic system curve through the entered design duty."""
    coefficient = v["designHeadM"] / v["designFlowLs"] ** 2
    points = [
        {
            "flowLs": v["maximumFlowLs"] * i / 10,
            "headM": coefficient * (v["maximumFlowLs"] * i / 10) ** 2,
        }
        for i in range(11)
    ]
    return result(
        {"systemCurveCoefficient": coefficient},
        [table("System curve", [("flowLs", "Flow", "L/s"), ("headM", "Head", "m")], points)],
        [
            "Quadratic friction-only curve through the design point; static lift and pump curve are excluded."
        ],
    )


@feature(
    "mepHvacPipes.variableSpeedDrive",
    "Variable Speed Drive",
    part="mep",
    fields=[
        number("designSpeedRpm", "Design speed", 1450, unit="rpm", min=1),
        number("newSpeedRpm", "New speed", 1100, unit="rpm", min=1),
        number("designPowerKw", "Design input power", 7.5, unit="kW", min=0),
    ],
    requires_project=False,
)
def variable_speed_drive(ctx: FeatureContext, v: dict) -> dict:
    """Apply pump affinity laws to estimate reduced flow, head and power."""
    ratio = v["newSpeedRpm"] / v["designSpeedRpm"]
    return result(
        {
            "flowRatio": ratio,
            "headRatio": ratio**2,
            "powerRatio": ratio**3,
            "estimatedPowerKw": v["designPowerKw"] * ratio**3,
        },
        notes=[
            "Ideal affinity laws for a geometrically fixed centrifugal pump; system resistance, motor efficiency and minimum speed are not considered."
        ],
    )


@feature(
    "mepHvacPipes.thermalExpansionLoop",
    "Thermal Expansion Loop",
    part="mep",
    fields=[
        number("runLengthM", "Straight run length", 30, unit="m", min=0),
        number("temperatureRiseC", "Temperature change", 50, unit="°C"),
        number(
            "expansionCoefficientPerC", "Linear expansion coefficient", 0.000012, unit="1/°C", min=0
        ),
    ],
    requires_project=False,
)
def thermal_expansion_loop(ctx: FeatureContext, v: dict) -> dict:
    """Calculate free thermal growth of a straight pipe run."""
    growth = v["runLengthM"] * v["temperatureRiseC"] * v["expansionCoefficientPerC"]
    return result(
        {"freeExpansionMm": growth * 1000},
        notes=[
            "Linear free expansion; loop leg sizing requires pipe stiffness, anchors, guides and allowable stress."
        ],
    )


@feature(
    "mepHvacPipes.pipeAnchorForce",
    "Pipe Anchor Force",
    part="mep",
    fields=[
        number("elasticModulusGpa", "Elastic modulus", 200, unit="GPa", min=0.1),
        number("areaMm2", "Pipe metal area", 800, unit="mm²", min=0.1),
        number("thermalStrain", "Restrained thermal strain", 0.0006, min=0),
    ],
    requires_project=False,
)
def pipe_anchor_force(ctx: FeatureContext, v: dict) -> dict:
    """Estimate fully restrained axial thermal force in a pipe."""
    force = v["elasticModulusGpa"] * 1e9 * v["areaMm2"] * 1e-6 * v["thermalStrain"]
    return result(
        {"restrainedAxialForceKn": force / 1000},
        notes=[
            "Elastic fully restrained estimate; flexibility, pressure thrust, friction and support interaction are excluded."
        ],
    )


@feature(
    "mepHvacPipes.flexibleConnection",
    "Flexible Connection",
    part="mep",
    fields=[
        number("pumpFlowLs", "Pump flow", 5, unit="L/s", min=0),
        number("connectionDiameterMm", "Connection bore", 65, unit="mm", min=1),
        number("maximumVelocityMs", "Maximum velocity", 2, unit="m/s", min=0.1),
    ],
    requires_project=False,
)
def flexible_connection(ctx: FeatureContext, v: dict) -> dict:
    """Check flexible-connector bore velocity at the pump design flow."""
    velocity = v["pumpFlowLs"] / 1000 / (math.pi * (v["connectionDiameterMm"] / 1000) ** 2 / 4)
    return result(
        {
            "connectorVelocityMs": velocity,
            "maximumVelocityMs": v["maximumVelocityMs"],
            "pass": velocity <= v["maximumVelocityMs"],
        },
        notes=[
            "Velocity check only; connector pressure rating, movement and fatigue life require product selection."
        ],
    )

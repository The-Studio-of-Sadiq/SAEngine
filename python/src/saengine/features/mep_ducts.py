"""Duct routing, sizing and schedules for mechanical systems."""

from __future__ import annotations

import math
from itertools import pairwise

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


def _ducts(ctx: FeatureContext) -> list[dict]:
    raw = ctx.raw("mep")
    hvac = raw.get("hvac") if raw else None
    ducts = hvac.get("ducts", []) if isinstance(hvac, dict) else []
    if not ducts:
        raise FeatureInputError("Add duct runs to the HVAC model in 07 MEP/mep.json first.")
    return ducts


@feature(
    "mepDucts.drawDuct",
    "Draw Duct",
    part="mep",
    fields=[
        number("flowLs", "Duct airflow", 0.8, unit="m³/s", min=0.001),
        number("widthMm", "Duct width", 500, unit="mm", min=50),
        number("heightMm", "Duct height", 300, unit="mm", min=50),
        select("system", "Duct system", ["supply", "return", "exhaust", "outsideAir"]),
    ],
    requires_project=False,
)
def draw_duct(ctx: FeatureContext, values: dict) -> dict:
    """Calculate area and velocity for the proposed duct cross-section."""
    area = values["widthMm"] * values["heightMm"] / 1e6
    velocity = values["flowLs"] / area
    return result(
        summary={"areaM2": area, "velocityMs": velocity, "system": values["system"]},
        notes=[
            "Cross-section velocity is airflow divided by the entered clear duct area; fittings and lining reduce the effective area."
        ],
    )


@feature(
    "mepDucts.autoRoute",
    "Auto Route",
    part="mep",
    fields=[
        number("startXM", "Start X", 0, unit="m"),
        number("startYM", "Start Y", 0, unit="m"),
        number("endXM", "End X", 10, unit="m"),
        number("endYM", "End Y", 5, unit="m"),
        select("firstLeg", "First routing direction", ["x", "y"]),
    ],
    requires_project=False,
)
def auto_route(ctx: FeatureContext, values: dict) -> dict:
    """Construct a deterministic orthogonal route between two points."""
    a = [values["startXM"], values["startYM"]]
    b = [values["endXM"], values["endYM"]]
    corner = [b[0], a[1]] if values["firstLeg"] == "x" else [a[0], b[1]]
    length = math.hypot(corner[0] - a[0], corner[1] - a[1]) + math.hypot(
        b[0] - corner[0], b[1] - corner[1]
    )
    return result(
        summary={"routeLengthM": length, "bendCount": int(a != corner) + int(corner != b)},
        tables=[
            table(
                "Orthogonal route points",
                [("sequence", "Sequence"), ("xM", "X", "m"), ("yM", "Y", "m")],
                [{"sequence": i, "xM": p[0], "yM": p[1]} for i, p in enumerate([a, corner, b], 1)],
            )
        ],
        notes=[
            "This single-corner geometric route is a layout proposal and does not avoid beams, walls or other services."
        ],
    )


@feature(
    "mepDucts.ductSystems",
    "Duct Systems",
    part="mep",
    fields=[
        select("system", "System type", ["supply", "return", "exhaust", "outsideAir", "smoke"]),
        number("designFlowM3s", "Design flow", 1.0, unit="m³/s", min=0),
        number("pressureClassPa", "Pressure class", 500, unit="Pa", min=0),
        text("systemTag", "System tag", "SA-1"),
    ],
    requires_project=False,
)
def duct_systems(ctx: FeatureContext, values: dict) -> dict:
    """Record the selected air-system design basis."""
    return result(
        summary={
            "system": values["system"],
            "designFlowM3s": values["designFlowM3s"],
            "pressureClassPa": values["pressureClassPa"],
        },
        tables=[
            table(
                "System configuration",
                [
                    ("tag", "Tag"),
                    ("system", "System"),
                    ("flowM3s", "Design flow", "m³/s"),
                    ("pressurePa", "Pressure class", "Pa"),
                ],
                [
                    {
                        "tag": values["systemTag"],
                        "system": values["system"],
                        "flowM3s": values["designFlowM3s"],
                        "pressurePa": values["pressureClassPa"],
                    }
                ],
            )
        ],
        notes=["Configuration values describe the proposed system and do not alter project ducts."],
    )


@feature(
    "mepDucts.risers",
    "Risers",
    part="mep",
    fields=[
        number("flowM3s", "Riser airflow", 1.5, unit="m³/s", min=0.01),
        number("widthMm", "Riser clear width", 800, unit="mm", min=100),
        number("depthMm", "Riser clear depth", 600, unit="mm", min=100),
        number("storyHeightM", "Story height", 3.2, unit="m", min=0.1),
    ],
    requires_project=False,
)
def risers(ctx: FeatureContext, values: dict) -> dict:
    """Check proposed riser velocity and geometric aspect ratio."""
    area = values["widthMm"] * values["depthMm"] / 1e6
    return result(
        summary={
            "areaM2": area,
            "velocityMs": values["flowM3s"] / area,
            "aspectRatio": values["widthMm"] / values["depthMm"],
            "storyHeightM": values["storyHeightM"],
        },
        notes=[
            "Riser velocity uses its clear rectangular area; fire stopping, access panels and structural openings are not included."
        ],
    )


@feature(
    "mepDucts.placeDiffuser",
    "Place Diffuser",
    part="mep",
    fields=[
        number("zoneFlowLs", "Zone supply airflow", 300, unit="L/s", min=0),
        number("diffuserFlowLs", "Selected diffuser flow", 50, unit="L/s", min=0.1),
        number("maximumThrowM", "Maximum throw", 4, unit="m", min=0.1),
    ],
    requires_project=False,
)
def place_diffuser(ctx: FeatureContext, values: dict) -> dict:
    """Determine diffuser count and residual airflow for a zone."""
    count = math.ceil(values["zoneFlowLs"] / values["diffuserFlowLs"])
    return result(
        summary={
            "diffuserCount": count,
            "scheduledFlowLs": count * values["diffuserFlowLs"],
            "excessFlowLs": count * values["diffuserFlowLs"] - values["zoneFlowLs"],
        },
        notes=[
            f"Each diffuser is assigned {values['diffuserFlowLs']:g} L/s; verify the selected unit's throw, NC and neck pressure drop for the room."
        ],
    )


@feature(
    "mepDucts.placeVav",
    "Place VAV",
    part="mep",
    fields=[
        number("maximumFlowLs", "Maximum airflow", 250, unit="L/s", min=0.1),
        number("minimumFlowLs", "Minimum airflow", 80, unit="L/s", min=0),
        number("designFlowLs", "Current design airflow", 180, unit="L/s", min=0),
    ],
    requires_project=False,
)
def place_vav(ctx: FeatureContext, values: dict) -> dict:
    """Check VAV minimum, design and maximum airflow setpoints."""
    valid_range = values["minimumFlowLs"] <= values["designFlowLs"] <= values["maximumFlowLs"]
    return result(
        summary={
            "controlRangeLs": values["maximumFlowLs"] - values["minimumFlowLs"],
            "setpointPasses": valid_range,
        },
        tables=[
            table(
                "VAV airflow setpoints",
                [("setpoint", "Setpoint"), ("flowLs", "Flow", "L/s")],
                [
                    {"setpoint": "Minimum", "flowLs": values["minimumFlowLs"]},
                    {"setpoint": "Design", "flowLs": values["designFlowLs"]},
                    {"setpoint": "Maximum", "flowLs": values["maximumFlowLs"]},
                ],
            )
        ],
        notes=[
            "Confirm minimum airflow against ventilation requirements and the selected terminal's controllable turndown."
        ],
    )


@feature(
    "mepDucts.ductAccessories",
    "Duct Accessories",
    part="mep",
    fields=[
        number("velocityMs", "Duct velocity", 5.0, unit="m/s", min=0),
        number("dynamicPressurePa", "Duct dynamic pressure", 15, unit="Pa", min=0),
        number("damperLossCoefficient", "Damper loss coefficient", 2.0, min=0),
        number("filterLossPa", "Filter pressure loss", 80, unit="Pa", min=0),
        number("silencerLossPa", "Silencer pressure loss", 25, unit="Pa", min=0),
    ],
    requires_project=False,
)
def duct_accessories(ctx: FeatureContext, values: dict) -> dict:
    """Sum accessory pressure losses at the stated design condition."""
    damper = values["damperLossCoefficient"] * values["dynamicPressurePa"]
    total = damper + values["filterLossPa"] + values["silencerLossPa"]
    return result(
        summary={
            "damperLossPa": damper,
            "totalAccessoryLossPa": total,
            "velocityMs": values["velocityMs"],
        },
        notes=[
            "Damper loss is K times dynamic pressure; filter and silencer losses are entered values at the design airflow."
        ],
    )


@feature(
    "mepDucts.ductClearance",
    "Duct Clearance",
    part="mep",
    fields=[
        number("ductWidthMm", "Duct width", 800, unit="mm", min=1),
        number("ductHeightMm", "Duct height", 400, unit="mm", min=1),
        number("requiredClearanceMm", "Required service clearance", 150, unit="mm", min=0),
        number("availableClearanceMm", "Available clearance", 200, unit="mm", min=0),
    ],
    requires_project=False,
)
def duct_clearance(ctx: FeatureContext, values: dict) -> dict:
    """Compare available maintenance clearance with the specified requirement."""
    return result(
        summary={
            "passes": values["availableClearanceMm"] >= values["requiredClearanceMm"],
            "overallEnvelopeMm": values["ductHeightMm"] + values["requiredClearanceMm"],
        },
        notes=[
            "The available clearance is a user-measured project dimension; provide extra room for insulation, access doors and adjacent services as required."
        ],
    )


@feature(
    "mepDucts.velocityCheck",
    "Velocity Check",
    part="mep",
    fields=[
        number("flowM3s", "Airflow", 0.8, unit="m³/s", min=0.001),
        number("widthMm", "Duct width", 500, unit="mm", min=50),
        number("heightMm", "Duct height", 300, unit="mm", min=50),
        number("maximumVelocityMs", "Project maximum velocity", 6.0, unit="m/s", min=0.1),
    ],
    requires_project=False,
)
def velocity_check(ctx: FeatureContext, values: dict) -> dict:
    """Check duct velocity against the stated project limit."""
    area = values["widthMm"] * values["heightMm"] / 1e6
    velocity = values["flowM3s"] / area
    return result(
        summary={
            "velocityMs": velocity,
            "maximumVelocityMs": values["maximumVelocityMs"],
            "passes": velocity <= values["maximumVelocityMs"],
        },
        notes=[
            "Velocity is computed from actual clear dimensions; the maximum is an explicit project criterion."
        ],
    )


@feature(
    "mepDucts.insulationCheck",
    "Insulation Check",
    part="mep",
    fields=[
        number("ductSurfaceM2", "Duct surface area", 12, unit="m²", min=0),
        number("insulationThicknessMm", "Insulation thickness", 25, unit="mm", min=0),
        number("conductivityWmK", "Insulation conductivity", 0.035, unit="W/(m·K)", min=0.001),
        number(
            "temperatureDifferenceC", "Air-to-space temperature difference", 15, unit="°C", min=0
        ),
        number("requiredThicknessMm", "Project minimum thickness", 20, unit="mm", min=0),
    ],
    requires_project=False,
)
def insulation_check(ctx: FeatureContext, values: dict) -> dict:
    """Check duct insulation thickness and estimate conductive heat transfer."""
    heat_loss = (
        values["conductivityWmK"]
        * values["ductSurfaceM2"]
        * values["temperatureDifferenceC"]
        / (values["insulationThicknessMm"] / 1000)
    )
    return result(
        summary={
            "heatTransferW": heat_loss,
            "thicknessPasses": values["insulationThicknessMm"] >= values["requiredThicknessMm"],
        },
        notes=[
            "Plane-wall conduction estimate excludes surface films, seams, supports and thermal bridges; thickness requirement is project-entered."
        ],
    )


@feature(
    "mepDucts.elbowRadius",
    "Elbow Radius",
    part="mep",
    fields=[
        number("ductWidthMm", "Duct width", 500, unit="mm", min=50),
        number("centrelineRadiusMm", "Elbow centreline radius", 500, unit="mm", min=1),
        number("velocityMs", "Air velocity", 5, unit="m/s", min=0),
        number("lossCoefficient", "Elbow loss coefficient", 0.3, min=0),
    ],
    requires_project=False,
)
def elbow_radius(ctx: FeatureContext, values: dict) -> dict:
    """Check elbow radius ratio and calculate fitting pressure loss."""
    ratio = values["centrelineRadiusMm"] / values["ductWidthMm"]
    loss = values["lossCoefficient"] * 1.2 * values["velocityMs"] ** 2 / 2
    return result(
        summary={"radiusRatio": ratio, "pressureLossPa": loss},
        notes=[
            "Pressure loss uses the entered elbow coefficient and air density of 1.2 kg/m³; confirm the coefficient for the actual turning-vane and radius geometry."
        ],
    )


@feature(
    "mepDucts.reducerSize",
    "Reducer Size",
    part="mep",
    fields=[
        number("upstreamAreaM2", "Upstream duct area", 0.4, unit="m²", min=0.001),
        number("downstreamAreaM2", "Downstream duct area", 0.25, unit="m²", min=0.001),
        number("transitionLengthM", "Transition length", 0.6, unit="m", min=0.01),
    ],
    requires_project=False,
)
def reducer_size(ctx: FeatureContext, values: dict) -> dict:
    """Compute reducer area ratio and equivalent transition angle."""
    ratio = values["downstreamAreaM2"] / values["upstreamAreaM2"]
    radial_change = (
        math.sqrt(values["upstreamAreaM2"]) - math.sqrt(values["downstreamAreaM2"])
    ) / 2
    angle = math.degrees(math.atan(radial_change / values["transitionLengthM"]))
    return result(
        summary={
            "areaRatio": ratio,
            "includedAngleDeg": 2 * angle,
            "areaReductionPercent": 100 * (1 - ratio),
        },
        notes=[
            "Equivalent circular-section transition angle is a screening approximation; design rectangular transitions from actual side dimensions and flow direction."
        ],
    )


@feature(
    "mepDucts.takeoffFitting",
    "Takeoff Fitting",
    part="mep",
    fields=[
        number("mainFlowM3s", "Main flow", 1.0, unit="m³/s", min=0.001),
        number("branchFlowM3s", "Branch flow", 0.3, unit="m³/s", min=0),
        number("mainAreaM2", "Main duct area", 0.3, unit="m²", min=0.001),
        number("branchAreaM2", "Branch duct area", 0.1, unit="m²", min=0.001),
        number("lossCoefficient", "Takeoff loss coefficient", 0.6, min=0),
    ],
    requires_project=False,
)
def takeoff_fitting(ctx: FeatureContext, values: dict) -> dict:
    """Evaluate branch flow fraction and takeoff pressure loss."""
    branch_velocity = values["branchFlowM3s"] / values["branchAreaM2"]
    loss = values["lossCoefficient"] * 1.2 * branch_velocity**2 / 2
    return result(
        summary={
            "branchFlowFraction": values["branchFlowM3s"] / values["mainFlowM3s"],
            "branchVelocityMs": branch_velocity,
            "takeoffLossPa": loss,
        },
        notes=[
            "Loss is based on branch velocity pressure and an entered fitting coefficient; confirm the value for the takeoff geometry and flow ratio."
        ],
    )


@feature(
    "mepDucts.transitionPiece",
    "Transition Piece",
    part="mep",
    fields=[
        number("upstreamWidthMm", "Upstream width", 500, unit="mm", min=1),
        number("downstreamWidthMm", "Downstream width", 300, unit="mm", min=1),
        number("upstreamHeightMm", "Upstream height", 300, unit="mm", min=1),
        number("downstreamHeightMm", "Downstream height", 250, unit="mm", min=1),
        number("maximumWallAngleDeg", "Maximum wall angle", 15, unit="°", min=1, max=45),
    ],
    requires_project=False,
)
def transition_piece(ctx: FeatureContext, values: dict) -> dict:
    """Estimate minimum transition length from cross-section changes."""
    dw = abs(values["upstreamWidthMm"] - values["downstreamWidthMm"]) / 2
    dh = abs(values["upstreamHeightMm"] - values["downstreamHeightMm"]) / 2
    max_delta = max(dw, dh)
    length_mm = max_delta / math.tan(math.radians(values["maximumWallAngleDeg"]))
    return result(
        summary={
            "minimumLengthMm": length_mm,
            "upstreamAreaMm2": values["upstreamWidthMm"] * values["upstreamHeightMm"],
            "downstreamAreaMm2": values["downstreamWidthMm"] * values["downstreamHeightMm"],
        },
        notes=[
            "Length assumes symmetric wall transitions and the entered maximum side-wall angle; unequal offsets require geometry-specific detailing."
        ],
    )


@feature(
    "mepDucts.flexDuct",
    "Flex Duct",
    part="mep",
    fields=[
        number("flowM3s", "Airflow", 0.08, unit="m³/s", min=0.001),
        number("diameterMm", "Flex duct inside diameter", 200, unit="mm", min=50),
        number("lengthM", "Flex duct length", 2.0, unit="m", min=0.1),
        number("frictionPaPerM", "Design friction rate", 1.2, unit="Pa/m", min=0),
        number("maximumLengthM", "Project maximum length", 3.0, unit="m", min=0.1),
    ],
    requires_project=False,
)
def flex_duct(ctx: FeatureContext, values: dict) -> dict:
    """Check flexible duct length and estimate straight-run pressure loss."""
    area = math.pi * (values["diameterMm"] / 1000) ** 2 / 4
    velocity = values["flowM3s"] / area
    return result(
        summary={
            "velocityMs": velocity,
            "straightLossPa": values["frictionPaPerM"] * values["lengthM"],
            "lengthPasses": values["lengthM"] <= values["maximumLengthM"],
        },
        notes=[
            "Straight-run friction uses the entered rate; compression, sag, bends and terminal losses increase actual flexible-duct resistance."
        ],
    )


@feature(
    "mepDucts.sizingMethod",
    "Sizing Method",
    part="mep",
    fields=[
        select(
            "method",
            "Duct sizing method",
            [
                ("equalFriction", "Equal friction"),
                ("staticRegain", "Static regain"),
                ("velocity", "Velocity"),
            ],
        ),
        number("frictionRatePaM", "Friction rate", 1.0, unit="Pa/m", min=0.01),
        number("maximumVelocityMs", "Maximum velocity", 6, unit="m/s", min=0.1),
    ],
    requires_project=False,
)
def sizing_method(ctx: FeatureContext, values: dict) -> dict:
    """Record duct sizing strategy and its controlling limits."""
    return result(
        summary={
            "method": values["method"],
            "frictionRatePaM": values["frictionRatePaM"],
            "maximumVelocityMs": values["maximumVelocityMs"],
        },
        notes=[
            "Equal friction controls pressure gradient, static regain balances recovered velocity pressure, and velocity method limits section speed."
        ],
    )


@feature(
    "mepDucts.frictionRate",
    "Friction Rate",
    part="mep",
    fields=[
        number("flowM3s", "Duct airflow", 0.5, unit="m³/s", min=0.001),
        number("frictionRatePaM", "Target friction rate", 1.0, unit="Pa/m", min=0.01),
        select("system", "Air system", ["supply", "return", "exhaust"]),
        select("shape", "Section shape", ["rect", "round"]),
    ],
    requires_project=False,
)
def friction_rate(ctx: FeatureContext, values: dict) -> dict:
    """Size a duct using the engine equal-friction method."""
    from saengine.hvac.air import equivalent_diameter, size_duct

    sizing = size_duct(
        values["flowM3s"], values["system"], values["shape"], values["frictionRatePaM"]
    )
    eq_d = sizing.get("diameter")
    if eq_d is None and "width" in sizing and "height" in sizing:
        eq_d = equivalent_diameter(sizing["width"], sizing["height"])
    return result(
        summary={
            "equivalentDiameterMm": eq_d,
            "velocityMs": sizing.get("velocity"),
            "frictionRatePaM": values["frictionRatePaM"],
        },
        tables=[
            table(
                "Equal-friction section",
                [("key", "Parameter"), ("value", "Value")],
                [{"key": key, "value": value} for key, value in sizing.items()],
            )
        ],
        notes=[
            "Duct section is selected with the engine's friction calculation and the specified system, shape and pressure gradient."
        ],
    )


@feature(
    "mepDucts.ductGauge",
    "Duct Gauge",
    part="mep",
    fields=[
        number("largestSideMm", "Largest duct side", 600, unit="mm", min=1),
        number("pressureClassPa", "Positive or negative pressure class", 500, unit="Pa", min=0),
        number("sheetThicknessMm", "Selected sheet thickness", 0.8, unit="mm", min=0.1),
        number("minimumThicknessMm", "Project minimum thickness", 0.6, unit="mm", min=0.1),
    ],
    requires_project=False,
)
def duct_gauge(ctx: FeatureContext, values: dict) -> dict:
    """Screen selected sheet thickness against a project criterion."""
    return result(
        summary={
            "sheetThicknessMm": values["sheetThicknessMm"],
            "passes": values["sheetThicknessMm"] >= values["minimumThicknessMm"],
            "largestSideMm": values["largestSideMm"],
        },
        notes=[
            "Sheet thickness is checked against the entered project minimum only; pressure-class reinforcement and fabrication standards must be verified for the actual duct."
        ],
    )


@feature(
    "mepDucts.staticRegain",
    "Static Regain",
    part="mep",
    fields=[
        number("upstreamVelocityMs", "Upstream velocity", 8, unit="m/s", min=0),
        number("downstreamVelocityMs", "Downstream velocity", 5, unit="m/s", min=0),
        number("recoveryFactor", "Static regain factor", 0.75, min=0, max=1),
        number("airDensityKgM3", "Air density", 1.2, unit="kg/m³", min=0.1),
    ],
    requires_project=False,
)
def static_regain(ctx: FeatureContext, values: dict) -> dict:
    """Estimate static pressure recovered across a reducing main section."""
    q_change = (
        values["airDensityKgM3"]
        * (values["upstreamVelocityMs"] ** 2 - values["downstreamVelocityMs"] ** 2)
        / 2
    )
    regain = max(q_change, 0) * values["recoveryFactor"]
    return result(
        summary={"availableRegainPa": regain, "staticRegainFactor": values["recoveryFactor"]},
        notes=[
            "Recovered pressure is a fraction of the decrease in velocity pressure; branch losses and fitting geometry are not included."
        ],
    )


@feature("mepDucts.ductSchedule", "Duct Schedule", part="mep", requires_project=True)
def duct_schedule(ctx: FeatureContext, values: dict) -> dict:
    """Schedule modeled duct runs with cross-section and route length."""
    rows = []
    for duct in _ducts(ctx):
        points = duct.get("path", [])
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in pairwise(points)) / 1000
        rows.append(
            {
                "id": duct.get("id", ""),
                "system": duct.get("system", ""),
                "story": duct.get("story", ""),
                "shape": duct.get("shape", ""),
                "widthMm": duct.get("width"),
                "heightMm": duct.get("height"),
                "lengthM": length,
            }
        )
    return result(
        summary={"ductRunCount": len(rows), "totalLengthM": sum(row["lengthM"] for row in rows)},
        tables=[
            table(
                "Duct schedule",
                [
                    ("id", "Run"),
                    ("system", "System"),
                    ("story", "Story"),
                    ("shape", "Shape"),
                    ("widthMm", "Width", "mm"),
                    ("heightMm", "Height", "mm"),
                    ("lengthM", "Length", "m"),
                ],
                rows,
            )
        ],
        notes=[
            "Lengths are plan-path lengths converted from project millimetres; vertical offsets, fittings and insulation are excluded."
        ],
    )


@feature(
    "mepDucts.ductLabel",
    "Duct Label",
    part="mep",
    fields=[select("labelMode", "Label content", ["size", "flow", "system", "sizeAndFlow"])],
    requires_project=True,
)
def duct_label(ctx: FeatureContext, values: dict) -> dict:
    """Prepare duct annotation content from modeled runs."""
    rows = []
    for duct in _ducts(ctx):
        rows.append(
            {
                "id": duct.get("id", ""),
                "system": duct.get("system", ""),
                "label": {
                    "size": f"{duct.get('width', '?')} × {duct.get('height', '?')} mm",
                    "flow": str(duct.get("flow", "not specified")),
                    "system": str(duct.get("system", "unassigned")),
                    "sizeAndFlow": f"{duct.get('width', '?')} × {duct.get('height', '?')} mm; {duct.get('flow', 'flow not specified')}",
                }[values["labelMode"]],
            }
        )
    return result(
        summary={"labelCount": len(rows), "labelMode": values["labelMode"]},
        tables=[
            table(
                "Duct annotation data",
                [("id", "Run"), ("system", "System"), ("label", "Label text")],
                rows,
            )
        ],
        notes=[
            "Annotation strings are derived from existing duct attributes; missing airflow is shown explicitly rather than inferred."
        ],
    )


@feature("mepDucts.ductTag", "Duct Tag", part="mep", requires_project=True)
def duct_tag(ctx: FeatureContext, values: dict) -> dict:
    """List duct runs with their project system and story tag fields."""
    rows = [
        {
            "id": d.get("id", ""),
            "systemTag": d.get("system", "unassigned"),
            "story": d.get("story", "unassigned"),
        }
        for d in _ducts(ctx)
    ]
    return result(
        summary={
            "taggedRunCount": len(rows),
            "untaggedRunCount": sum(row["systemTag"] == "unassigned" for row in rows),
        },
        tables=[
            table(
                "Duct coordination tags",
                [("id", "Run"), ("systemTag", "System tag"), ("story", "Story")],
                rows,
            )
        ],
        notes=["Tags are reported from model attributes; no project data is rewritten."],
    )


@feature("mepDucts.ductQuantities", "Duct Quantities", part="mep", requires_project=True)
def duct_quantities(ctx: FeatureContext, values: dict) -> dict:
    """Calculate plan length and surface area quantities for modeled ducts."""
    rows = []
    for duct in _ducts(ctx):
        points = duct.get("path", [])
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in pairwise(points)) / 1000
        width = float(duct.get("width", 0)) / 1000
        height = float(duct.get("height", 0)) / 1000
        perimeter = 2 * (width + height) if duct.get("shape") == "rect" else math.pi * width
        rows.append(
            {"id": duct.get("id", ""), "lengthM": length, "surfaceAreaM2": length * perimeter}
        )
    return result(
        summary={
            "totalLengthM": sum(row["lengthM"] for row in rows),
            "totalSurfaceAreaM2": sum(row["surfaceAreaM2"] for row in rows),
        },
        tables=[
            table(
                "Duct takeoff",
                [
                    ("id", "Run"),
                    ("lengthM", "Plan length", "m"),
                    ("surfaceAreaM2", "Surface area", "m²"),
                ],
                rows,
            )
        ],
        notes=[
            "Rectangular perimeter or circular circumference is multiplied by plan-path length; fittings, seams, insulation and vertical risers are excluded."
        ],
    )

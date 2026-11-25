"""Sprinkler layout, hydraulics, schedules and commissioning checks."""

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


def _heads(ctx: FeatureContext) -> list[dict]:
    raw = ctx.raw("mep")
    fire = raw.get("fireProtection", {}) if isinstance(raw, dict) else {}
    heads = fire.get("sprinklers", []) if isinstance(fire, dict) else []
    if not isinstance(heads, list) or not heads:
        raise FeatureInputError(
            "Add sprinkler heads to fireProtection.sprinklers in 07 MEP/mep.json."
        )
    return [head for head in heads if isinstance(head, dict)]


@feature(
    "mepSprinkler.sprinklerLayout",
    "Sprinkler Layout",
    part="mep",
    fields=[
        number("areaM2", "Protected area", 240, unit="m²", min=0.1),
        number("spacingXM", "Head spacing X", 4, unit="m", min=0.1),
        number("spacingYM", "Head spacing Y", 4, unit="m", min=0.1),
    ],
    requires_project=False,
)
def sprinkler_layout(ctx: FeatureContext, v: dict) -> dict:
    """Estimate sprinkler count on a regular orthogonal grid."""
    nx, ny = (
        math.ceil(math.sqrt(v["areaM2"]) / v["spacingXM"]),
        math.ceil(math.sqrt(v["areaM2"]) / v["spacingYM"]),
    )
    return result(
        {
            "estimatedHeadCount": nx * ny,
            "gridX": nx,
            "gridY": ny,
            "coveragePerHeadM2": v["spacingXM"] * v["spacingYM"],
        },
        notes=[
            "Rectangular grid estimate; perimeter, obstructions, hazard limitations and actual room geometry require layout review."
        ],
    )


@feature(
    "mepSprinkler.hazardClass",
    "Hazard Class",
    part="mep",
    fields=[
        text("room", "Room name", "Storage room"),
        select("hazard", "Selected hazard basis", ["light", "ordinary", "extra"]),
        number("areaM2", "Room area", 120, unit="m²", min=0),
    ],
    requires_project=False,
)
def hazard_class(ctx: FeatureContext, v: dict) -> dict:
    """Record the selected hazard category and area for design calculations."""
    return result(
        {"room": v["room"], "hazard": v["hazard"], "areaM2": v["areaM2"]},
        notes=[
            "Hazard selection is an engineering input; verify the occupancy, commodity and applicable project criteria."
        ],
    )


@feature(
    "mepSprinkler.coverageCheck",
    "Coverage Check",
    part="mep",
    fields=[
        number("spacingXM", "Head spacing X", 4, unit="m", min=0),
        number("spacingYM", "Head spacing Y", 4, unit="m", min=0),
        number("maxCoverageM2", "Maximum area per head", 12, unit="m²", min=0.1),
    ],
    requires_project=False,
)
def coverage_check(ctx: FeatureContext, v: dict) -> dict:
    """Check individual sprinkler coverage area against the selected limit."""
    area = v["spacingXM"] * v["spacingYM"]
    return result(
        {"coverageM2": area, "maximumM2": v["maxCoverageM2"], "pass": area <= v["maxCoverageM2"]},
        notes=["Area test only; spacing limits and obstruction rules must also be checked."],
    )


@feature(
    "mepSprinkler.pipeSizing",
    "Pipe Sizing",
    part="mep",
    fields=[
        number("flowLs", "Design flow", 12, unit="L/s", min=0),
        number("velocityMs", "Maximum velocity", 3, unit="m/s", min=0.1),
    ],
    requires_project=False,
)
def pipe_sizing(ctx: FeatureContext, v: dict) -> dict:
    """Estimate internal sprinkler pipe diameter from flow and velocity."""
    diameter = math.sqrt(4 * v["flowLs"] / 1000 / (math.pi * v["velocityMs"])) * 1000
    return result(
        {
            "minimumInternalDiameterMm": diameter,
            "flowLs": v["flowLs"],
            "velocityMs": v["velocityMs"],
        },
        notes=[
            "Continuity sizing is preliminary; use listed pipe bores and verify hydraulic losses."
        ],
    )


@feature(
    "mepSprinkler.remoteArea",
    "Remote Area",
    part="mep",
    fields=[
        number("densityMmPerMin", "Design density", 5, unit="mm/min", min=0),
        number("areaM2", "Operating area", 140, unit="m²", min=0.1),
    ],
    requires_project=False,
)
def remote_area(ctx: FeatureContext, v: dict) -> dict:
    """Calculate required discharge from density over the operating area."""
    return result(
        {
            "requiredFlowLs": v["densityMmPerMin"] * v["areaM2"] / 60,
            "densityMmPerMin": v["densityMmPerMin"],
            "areaM2": v["areaM2"],
        },
        notes=[
            "Uniform density is applied across the entered remote area; hose allowance is excluded."
        ],
    )


@feature(
    "mepSprinkler.demandPoint",
    "Demand Point",
    part="mep",
    fields=[
        number("flowLs", "Required flow", 20, unit="L/s", min=0),
        number("pressureKpa", "Required pressure", 350, unit="kPa", min=0),
    ],
    requires_project=False,
)
def demand_point(ctx: FeatureContext, v: dict) -> dict:
    """Report the fire-system demand point and corresponding hydraulic power."""
    return result(
        {
            "flowLs": v["flowLs"],
            "pressureKpa": v["pressureKpa"],
            "hydraulicPowerKw": v["flowLs"] * v["pressureKpa"] / 1000,
        },
        notes=["Hydraulic power is Q×p; pump efficiency and elevation are not included."],
    )


@feature(
    "mepSprinkler.pressureLoss",
    "Pressure Loss",
    part="mep",
    fields=[
        number("lengthM", "Equivalent pipe length", 80, unit="m", min=0),
        number("flowLs", "Water flow", 15, unit="L/s", min=0),
        number("diameterMm", "Internal diameter", 100, unit="mm", min=1),
        number("frictionFactor", "Darcy friction factor", 0.02, min=0.001),
    ],
    requires_project=False,
)
def pressure_loss(ctx: FeatureContext, v: dict) -> dict:
    """Estimate straight-pipe friction loss using Darcy-Weisbach."""
    d, q = v["diameterMm"] / 1000, v["flowLs"] / 1000
    velocity = q / (math.pi * d**2 / 4)
    loss = v["frictionFactor"] * v["lengthM"] / d * velocity**2 / (2 * 9.80665)
    return result(
        {"velocityMs": velocity, "lossHeadM": loss, "pressureLossKpa": loss * 9.80665},
        notes=["Darcy-Weisbach for a full circular pipe; fittings and elevation are excluded."],
    )


@feature(
    "mepSprinkler.sprinklerSchedule",
    "Sprinkler Schedule",
    part="mep",
    fields=[],
    requires_project=True,
)
def sprinkler_schedule(ctx: FeatureContext, v: dict) -> dict:
    """List project sprinkler heads with type, location and discharge factor."""
    heads = _heads(ctx)
    return result(
        {"headCount": len(heads)},
        [
            table(
                "Sprinkler heads",
                [("tag", "Tag"), ("type", "Type"), ("room", "Room"), ("kFactor", "K-factor")],
                [
                    {
                        "tag": x.get("tag", ""),
                        "type": x.get("type", ""),
                        "room": x.get("room", ""),
                        "kFactor": x.get("kFactor"),
                    }
                    for x in heads
                ],
            )
        ],
    )


@feature(
    "mepSprinkler.hydraulicReport",
    "Hydraulic Report",
    part="mep",
    fields=[
        number("flowLs", "Remote area flow", 20, unit="L/s", min=0),
        number("pressureKpa", "Base pressure", 450, unit="kPa", min=0),
        text("systemTag", "System tag", "SP-01"),
    ],
    requires_project=False,
)
def hydraulic_report(ctx: FeatureContext, v: dict) -> dict:
    """Write a concise sprinkler hydraulic calculation report to project exports."""
    if ctx.root is None:
        raise FeatureInputError("Choose a project to save the hydraulic report.")
    destination = ctx.path("07 MEP/exports/sprinkler-hydraulic-report.md")
    assert destination is not None
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        f"# Sprinkler hydraulic report\n\nSystem: {v['systemTag']}\n\nFlow: {v['flowLs']:.3f} L/s\n\nBase pressure: {v['pressureKpa']:.3f} kPa\n",
        encoding="utf-8",
    )
    return result(
        {"flowLs": v["flowLs"], "pressureKpa": v["pressureKpa"], "reportPath": str(destination)},
        notes=[
            "Report records entered demand values; a network calculation is needed for path losses."
        ],
    )


@feature(
    "mepSprinkler.shopDrawings",
    "Shop Drawings",
    part="mep",
    fields=[
        number("scale", "Drawing scale denominator", 100, min=1),
        text("sheet", "Sheet identifier", "FP-01"),
    ],
    requires_project=True,
)
def shop_drawings(ctx: FeatureContext, v: dict) -> dict:
    """Export a coordinate register of sprinkler heads for shop drawing production."""
    heads = _heads(ctx)
    rows = [
        {
            "tag": x.get("tag", ""),
            "xM": x.get("xM"),
            "yM": x.get("yM"),
            "zM": x.get("zM"),
            "type": x.get("type", ""),
        }
        for x in heads
    ]
    return result(
        {"sheet": v["sheet"], "scaleDenominator": v["scale"], "headCount": len(rows)},
        [
            table(
                "Sprinkler head coordinates",
                [
                    ("tag", "Tag"),
                    ("xM", "X", "m"),
                    ("yM", "Y", "m"),
                    ("zM", "Z", "m"),
                    ("type", "Type"),
                ],
                rows,
            )
        ],
        [
            "Coordinate register only; confirm dimensions, ceiling grid and construction details on issued drawings."
        ],
    )


@feature(
    "mepSprinkler.pumpDutyPoint",
    "Pump Duty Point",
    part="mep",
    fields=[
        number("flowLs", "System demand", 25, unit="L/s", min=0),
        number("staticHeadM", "Static head", 20, unit="m", min=0),
        number("frictionHeadM", "Friction head", 15, unit="m", min=0),
        number("residualPressureKpa", "Residual pressure", 300, unit="kPa", min=0),
    ],
    requires_project=False,
)
def pump_duty_point(ctx: FeatureContext, v: dict) -> dict:
    """Combine static, friction and residual-pressure requirements at the pump."""
    head = v["staticHeadM"] + v["frictionHeadM"] + v["residualPressureKpa"] / 9.80665
    return result(
        {
            "dutyFlowLs": v["flowLs"],
            "requiredHeadM": head,
            "hydraulicPowerKw": v["flowLs"] / 1000 * 1000 * 9.80665 * head / 1000,
        },
        notes=[
            "Residual pressure is converted to water head; verify suction pressure and pump curve at the required duty."
        ],
    )


@feature(
    "mepSprinkler.tankCapacity",
    "Tank Capacity",
    part="mep",
    fields=[
        number("flowLs", "Design demand", 25, unit="L/s", min=0),
        number("durationMin", "Duration", 60, unit="min", min=0.1),
    ],
    requires_project=False,
)
def tank_capacity(ctx: FeatureContext, v: dict) -> dict:
    """Calculate usable water volume for the entered flow and duration."""
    return result(
        {
            "usableVolumeM3": v["flowLs"] * v["durationMin"] * 60 / 1000,
            "flowLs": v["flowLs"],
            "durationMin": v["durationMin"],
        },
        notes=[
            "Does not include unusable tank volume, refill, or additional simultaneous demands."
        ],
    )


@feature(
    "mepSprinkler.supplyCurve",
    "Supply Curve",
    part="mep",
    fields=[
        number("staticKpa", "Static pressure", 600, unit="kPa", min=0),
        number("flowLs", "Test flow", 25, unit="L/s", min=0),
        number("residualKpa", "Residual pressure", 450, unit="kPa", min=0),
    ],
    requires_project=False,
)
def supply_curve(ctx: FeatureContext, v: dict) -> dict:
    """Calculate the two-point supply curve coefficient from a flow test."""
    if v["staticKpa"] <= v["residualKpa"] and v["flowLs"] > 0:
        raise FeatureInputError(
            "Static pressure must exceed residual pressure at a positive test flow."
        )
    k = v["flowLs"] / math.sqrt(v["staticKpa"] - v["residualKpa"]) if v["flowLs"] else 0
    return result(
        {
            "testFlowLs": v["flowLs"],
            "staticKpa": v["staticKpa"],
            "residualKpa": v["residualKpa"],
            "curveCoefficient": k,
        },
        notes=[
            "Two-point approximation P=Pstatic-(Q/K)²; validate with a measured water-supply test."
        ],
    )


@feature(
    "mepSprinkler.suctionLayout",
    "Suction Layout",
    part="mep",
    fields=[
        number("flowLs", "Pump flow", 25, unit="L/s", min=0),
        number("velocityMs", "Suction velocity", 1.5, unit="m/s", min=0.1),
    ],
    requires_project=False,
)
def suction_layout(ctx: FeatureContext, v: dict) -> dict:
    """Estimate suction pipe bore at the entered maximum velocity."""
    d = math.sqrt(4 * v["flowLs"] / 1000 / (math.pi * v["velocityMs"])) * 1000
    return result(
        {"minimumInternalDiameterMm": d, "flowLs": v["flowLs"], "velocityMs": v["velocityMs"]},
        notes=[
            "Continuity sizing only; provide adequate straight length, eccentric reducers and submergence to prevent air entrainment."
        ],
    )


@feature(
    "mepSprinkler.jockeyPumpSet",
    "Jockey Pump Set",
    part="mep",
    fields=[
        number("systemVolumeM3", "System volume", 8, unit="m³", min=0),
        number("allowableDropKpa", "Pressure drop before start", 50, unit="kPa", min=0.1),
        number("recoveryMin", "Recovery time", 10, unit="min", min=0.1),
    ],
    requires_project=False,
)
def jockey_pump_set(ctx: FeatureContext, v: dict) -> dict:
    """Estimate a makeup flow for pressure recovery over the selected interval."""
    flow = (
        v["systemVolumeM3"]
        * v["allowableDropKpa"]
        / (1000 * 9.80665)
        / (v["recoveryMin"] * 60)
        * 1000
    )
    return result(
        {
            "estimatedMakeupFlowLs": flow,
            "pressureDropKpa": v["allowableDropKpa"],
            "recoveryMin": v["recoveryMin"],
        },
        notes=[
            "Uses water compressibility only as a rough screening proxy; leakage rate and system elasticity govern actual jockey flow."
        ],
    )


@feature(
    "mepSprinkler.headSpacing",
    "Head Spacing",
    part="mep",
    fields=[
        number("spacingXM", "Spacing X", 4, unit="m", min=0),
        number("spacingYM", "Spacing Y", 4, unit="m", min=0),
        number("limitM", "Maximum spacing", 4, unit="m", min=0.1),
    ],
    requires_project=False,
)
def head_spacing(ctx: FeatureContext, v: dict) -> dict:
    """Check orthogonal head spacing against a selected maximum."""
    return result(
        {
            "spacingXPass": v["spacingXM"] <= v["limitM"],
            "spacingYPass": v["spacingYM"] <= v["limitM"],
            "coverageM2": v["spacingXM"] * v["spacingYM"],
        },
        notes=[
            "Spacing limit is an explicit design input; boundary distances and obstructions are not evaluated."
        ],
    )


@feature(
    "mepSprinkler.branchLines",
    "Branch Lines",
    part="mep",
    fields=[
        number("roomLengthM", "Room length", 24, unit="m", min=0.1),
        number("branchSpacingM", "Branch spacing", 4, unit="m", min=0.1),
        number("headSpacingM", "Head spacing along branch", 4, unit="m", min=0.1),
    ],
    requires_project=False,
)
def branch_lines(ctx: FeatureContext, v: dict) -> dict:
    """Estimate branch count and heads per branch for a rectangular room."""
    branches = math.ceil(v["roomLengthM"] / v["branchSpacingM"])
    heads = math.ceil(v["roomLengthM"] / v["headSpacingM"])
    return result(
        {"branchCount": branches, "headsPerBranch": heads, "estimatedHeadCount": branches * heads},
        notes=["Regular-grid count with edge coverage not checked against room boundaries."],
    )


@feature(
    "mepSprinkler.crossMainLayout",
    "Cross Main Layout",
    part="mep",
    fields=[
        number("buildingWidthM", "Building width", 30, unit="m", min=0),
        number("mainSpacingM", "Cross-main spacing", 12, unit="m", min=0.1),
        number("mainLengthM", "Main length", 40, unit="m", min=0),
    ],
    requires_project=False,
)
def cross_main_layout(ctx: FeatureContext, v: dict) -> dict:
    """Estimate the number and total length of cross mains."""
    count = math.ceil(v["buildingWidthM"] / v["mainSpacingM"])
    return result(
        {
            "crossMainCount": count,
            "totalLengthM": count * v["mainLengthM"],
            "spacingM": v["mainSpacingM"],
        },
        notes=[
            "Geometric estimate; coordinate with riser positions, branch takeoffs and actual ceiling geometry."
        ],
    )


@feature(
    "mepSprinkler.dropNipples",
    "Drop Nipples",
    part="mep",
    fields=[
        number("headCount", "Sprinkler head count", 40, min=0),
        number("dropLengthMm", "Drop length", 300, unit="mm", min=0),
        number("allowanceMm", "Cutting allowance per drop", 25, unit="mm", min=0),
    ],
    requires_project=False,
)
def drop_nipples(ctx: FeatureContext, v: dict) -> dict:
    """Calculate aggregate nipple procurement length."""
    total = v["headCount"] * (v["dropLengthMm"] + v["allowanceMm"])
    return result(
        {"dropCount": int(v["headCount"]), "totalLengthM": total / 1000},
        notes=["Straight cut length estimate; thread engagement and fittings are excluded."],
    )


@feature(
    "mepSprinkler.spareHeads",
    "Spare Heads",
    part="mep",
    fields=[
        number("installedCount", "Installed sprinkler count", 300, min=0),
        number("spareFraction", "Spare fraction", 0.02, min=0, max=1),
    ],
    requires_project=False,
)
def spare_heads(ctx: FeatureContext, v: dict) -> dict:
    """Calculate a spare-head quantity from the specified stock fraction."""
    return result(
        {
            "spareHeadCount": math.ceil(v["installedCount"] * v["spareFraction"]),
            "installedCount": int(v["installedCount"]),
        },
        notes=[
            "Use project-specific minimum stock and temperature/type separation where required."
        ],
    )


@feature(
    "mepSprinkler.balancingValveSet",
    "Balancing Valve Set",
    part="mep",
    fields=[
        number("designFlowLs", "Design flow", 5, unit="L/s", min=0),
        number("measuredFlowLs", "Measured flow", 4.5, unit="L/s", min=0),
        number("valveCv", "Valve coefficient", 10, min=0.01),
    ],
    requires_project=False,
)
def balancing_valve_set(ctx: FeatureContext, v: dict) -> dict:
    """Estimate the valve pressure drop at measured flow using a metric Kv relation."""
    drop = (v["measuredFlowLs"] * 3.6 / v["valveCv"]) ** 2 * 100
    return result(
        {
            "flowErrorPercent": (v["measuredFlowLs"] - v["designFlowLs"]) / v["designFlowLs"] * 100
            if v["designFlowLs"]
            else 0,
            "estimatedValveDropKpa": drop,
        },
        notes=[
            "Metric Kv approximation for water; valve coefficient convention must match the product data."
        ],
    )


@feature(
    "mepSprinkler.flowTest",
    "Flow Test",
    part="mep",
    fields=[
        number("staticKpa", "Static pressure", 600, unit="kPa", min=0),
        number("residualKpa", "Residual pressure", 450, unit="kPa", min=0),
        number("flowLs", "Measured flow", 25, unit="L/s", min=0),
    ],
    requires_project=False,
)
def flow_test(ctx: FeatureContext, v: dict) -> dict:
    """Record measured static and residual pressures with test flow."""
    return result(
        {
            "pressureDropKpa": v["staticKpa"] - v["residualKpa"],
            "flowLs": v["flowLs"],
            "staticKpa": v["staticKpa"],
            "residualKpa": v["residualKpa"],
        },
        notes=[
            "Record gauge elevations, test date and hydrant configuration alongside this result."
        ],
    )


@feature(
    "mepSprinkler.designDensityCheck",
    "Design Density Check",
    part="mep",
    fields=[
        number("deliveredFlowLs", "Delivered sprinkler flow", 18, unit="L/s", min=0),
        number("remoteAreaM2", "Remote area", 140, unit="m²", min=0.1),
        number("designDensityMmMin", "Design density", 5, unit="mm/min", min=0),
    ],
    requires_project=False,
)
def design_density_check(ctx: FeatureContext, v: dict) -> dict:
    """Compare delivered discharge with the specified remote-area density."""
    actual = v["deliveredFlowLs"] * 60 / v["remoteAreaM2"]
    return result(
        {
            "deliveredDensityMmPerMin": actual,
            "designDensityMmPerMin": v["designDensityMmMin"],
            "pass": actual >= v["designDensityMmMin"],
        },
        notes=[
            "Flow is uniformly distributed over the remote area; verify operating head count and discharge coefficients."
        ],
    )


@feature(
    "mepSprinkler.asBuiltSprinkler",
    "As-Built Sprinkler",
    part="mep",
    fields=[
        number("designXM", "Design X", 0, unit="m"),
        number("designYM", "Design Y", 0, unit="m"),
        number("installedXM", "Installed X", 0.05, unit="m"),
        number("installedYM", "Installed Y", 0, unit="m"),
        number("toleranceMm", "Position tolerance", 50, unit="mm", min=0),
    ],
    requires_project=False,
)
def as_built_sprinkler(ctx: FeatureContext, v: dict) -> dict:
    """Calculate installed-to-design sprinkler position deviation."""
    error = math.hypot(v["installedXM"] - v["designXM"], v["installedYM"] - v["designYM"])
    return result(
        {"deviationMm": error * 1000, "withinTolerance": error * 1000 <= v["toleranceMm"]},
        notes=[
            "Plan-position tolerance check only; elevation, orientation and obstruction clearance are not included."
        ],
    )

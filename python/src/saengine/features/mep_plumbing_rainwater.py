"""Dedicated mepPlumbingRainwater MEP feature registrations."""

from __future__ import annotations

from saengine.features import (
    FeatureContext,
    feature,
    number,
    result,
    table,
    text,
)


@feature(
    "mepPlumbingRainwater.catchmentArea",
    "Catchment Area",
    part="mep",
    fields=[number("area", "Area", 100, unit="m?", min=0)],
    requires_project=True,
)
def catchmentArea(ctx: FeatureContext, values: dict) -> dict:
    """Catchment Area: Collection."""
    design_value = float(values["area"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Catchment Area",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepPlumbingRainwater.disinfection",
    "Disinfection",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def disinfection(ctx: FeatureContext, values: dict) -> dict:
    """Disinfection: Treatment."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Disinfection",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingRainwater.distributionPump",
    "Distribution Pump",
    part="mep",
    fields=[number("value", "Design value", 100, unit="units", min=0)],
    requires_project=True,
)
def distributionPump(ctx: FeatureContext, values: dict) -> dict:
    """Distribution Pump: Treatment."""
    design_value = float(values["value"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Distribution Pump",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepPlumbingRainwater.downpipe",
    "Downpipe",
    part="mep",
    fields=[number("value", "Design value", 100, unit="units", min=0)],
    requires_project=True,
)
def downpipe(ctx: FeatureContext, values: dict) -> dict:
    """Downpipe: Collection."""
    design_value = float(values["value"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Downpipe",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepPlumbingRainwater.dualPumpController",
    "Dual Pump Controller",
    part="mep",
    fields=[number("value", "Design value", 100, unit="units", min=0)],
    requires_project=True,
)
def dualPumpController(ctx: FeatureContext, values: dict) -> dict:
    """Dual Pump Controller: Pumping Systems."""
    design_value = float(values["value"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Dual Pump Controller",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepPlumbingRainwater.filterUnit",
    "Filter Unit",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def filterUnit(ctx: FeatureContext, values: dict) -> dict:
    """Filter Unit: Treatment."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Filter Unit",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingRainwater.firstFlush",
    "First Flush",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def firstFlush(ctx: FeatureContext, values: dict) -> dict:
    """First Flush: Collection."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "First Flush",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingRainwater.gutterSize",
    "Gutter Size",
    part="mep",
    fields=[number("value", "Design value", 100, unit="units", min=0)],
    requires_project=True,
)
def gutterSize(ctx: FeatureContext, values: dict) -> dict:
    """Gutter Size: Collection."""
    design_value = float(values["value"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Gutter Size",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepPlumbingRainwater.levelSensing",
    "Level Sensing",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def levelSensing(ctx: FeatureContext, values: dict) -> dict:
    """Level Sensing: Water Quality."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Level Sensing",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingRainwater.mainsBackup",
    "Mains Backup",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def mainsBackup(ctx: FeatureContext, values: dict) -> dict:
    """Mains Backup: Water Quality."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Mains Backup",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingRainwater.overflowRoute",
    "Overflow Route",
    part="mep",
    fields=[number("flow", "Design flow", 100, unit="l/s", min=0)],
    requires_project=True,
)
def overflowRoute(ctx: FeatureContext, values: dict) -> dict:
    """Overflow Route: Storage."""
    design_value = float(values["flow"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Overflow Route",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepPlumbingRainwater.pressureTank",
    "Pressure Tank",
    part="mep",
    fields=[number("pressure", "Design pressure", 100, unit="kPa", min=0)],
    requires_project=True,
)
def pressureTank(ctx: FeatureContext, values: dict) -> dict:
    """Pressure Tank: Pumping Systems."""
    design_value = float(values["pressure"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Pressure Tank",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepPlumbingRainwater.retentionBasin",
    "Retention Basin",
    part="mep",
    fields=[number("value", "Design value", 100, unit="units", min=0)],
    requires_project=True,
)
def retentionBasin(ctx: FeatureContext, values: dict) -> dict:
    """Retention Basin: Storm Runoff."""
    design_value = float(values["value"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Retention Basin",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepPlumbingRainwater.runoffCoefficient",
    "Runoff Coefficient",
    part="mep",
    fields=[number("value", "Design value", 100, unit="units", min=0)],
    requires_project=True,
)
def runoffCoefficient(ctx: FeatureContext, values: dict) -> dict:
    """Runoff Coefficient: Storm Runoff."""
    design_value = float(values["value"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Runoff Coefficient",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepPlumbingRainwater.sedimentTrap",
    "Sediment Trap",
    part="mep",
    fields=[number("value", "Design value", 100, unit="units", min=0)],
    requires_project=True,
)
def sedimentTrap(ctx: FeatureContext, values: dict) -> dict:
    """Sediment Trap: Water Quality."""
    design_value = float(values["value"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Sediment Trap",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepPlumbingRainwater.sizingMethod",
    "Sizing Method",
    part="mep",
    fields=[number("value", "Design value", 100, unit="units", min=0)],
    requires_project=True,
)
def sizingMethod(ctx: FeatureContext, values: dict) -> dict:
    """Sizing Method: Storage."""
    design_value = float(values["value"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Sizing Method",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepPlumbingRainwater.submersiblePump",
    "Submersible Pump",
    part="mep",
    fields=[number("value", "Design value", 100, unit="units", min=0)],
    requires_project=True,
)
def submersiblePump(ctx: FeatureContext, values: dict) -> dict:
    """Submersible Pump: Pumping Systems."""
    design_value = float(values["value"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Submersible Pump",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepPlumbingRainwater.tankInlet",
    "Tank Inlet",
    part="mep",
    fields=[number("value", "Design value", 100, unit="units", min=0)],
    requires_project=True,
)
def tankInlet(ctx: FeatureContext, values: dict) -> dict:
    """Tank Inlet: Storage."""
    design_value = float(values["value"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Tank Inlet",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepPlumbingRainwater.tankSize",
    "Tank Size",
    part="mep",
    fields=[number("value", "Design value", 100, unit="units", min=0)],
    requires_project=True,
)
def tankSize(ctx: FeatureContext, values: dict) -> dict:
    """Tank Size: Storage."""
    design_value = float(values["value"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Tank Size",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepPlumbingRainwater.uvSteriliser",
    "UV Steriliser",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def uvSteriliser(ctx: FeatureContext, values: dict) -> dict:
    """UV Steriliser: Water Quality."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "UV Steriliser",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingRainwater.yieldEstimate",
    "Yield Estimate",
    part="mep",
    fields=[number("flow", "Design flow", 100, unit="l/s", min=0)],
    requires_project=True,
)
def yieldEstimate(ctx: FeatureContext, values: dict) -> dict:
    """Yield Estimate: Treatment."""
    design_value = float(values["flow"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Yield Estimate",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )

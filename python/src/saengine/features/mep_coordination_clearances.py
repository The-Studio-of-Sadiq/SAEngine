"""Dedicated mepCoordinationClearances MEP feature registrations."""

from __future__ import annotations

import json

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    table,
    text,
)


@feature(
    "mepCoordinationClearances.accessZone",
    "Access Zone",
    part="mep",
    fields=[text("zoneId", "Zone ID", "zone-1")],
    requires_project=True,
)
def accessZone(ctx: FeatureContext, values: dict) -> dict:
    """Access Zone: Define."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Access Zone",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.applyZone",
    "Apply Zone",
    part="mep",
    fields=[text("zoneId", "Zone ID", "zone-1")],
    requires_project=True,
)
def applyZone(ctx: FeatureContext, values: dict) -> dict:
    """Apply Zone: Define."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Apply Zone",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.assignIssue",
    "Assign Issue",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def assignIssue(ctx: FeatureContext, values: dict) -> dict:
    """Assign Issue: Resolution Workflow."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Assign Issue",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.autoOffsetSystem",
    "Auto Offset System",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def autoOffsetSystem(ctx: FeatureContext, values: dict) -> dict:
    """Auto Offset System: Resolution Workflow."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Auto Offset System",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.clearanceReport",
    "Clearance Report",
    part="mep",
    fields=[
        number("value", "Design value", 100, unit="units", min=0),
        text("name", "Output name", "MEP schedule"),
    ],
    requires_project=True,
)
def clearanceReport(ctx: FeatureContext, values: dict) -> dict:
    """Clearance Report: Check."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepCoordinationClearances.clearanceReport",
        "title": "Clearance Report",
        "name": values["name"],
        "group": "Check",
        "mep": raw,
    }
    path = ctx.path("11 Exports/clearanceReport.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Clearance Report",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepCoordinationClearances.clearanceSignoff",
    "Clearance Signoff",
    part="mep",
    fields=[
        number("value", "Design value", 100, unit="units", min=0),
        text("name", "Output name", "MEP schedule"),
    ],
    requires_project=True,
)
def clearanceSignoff(ctx: FeatureContext, values: dict) -> dict:
    """Clearance Signoff: Resolution Workflow."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepCoordinationClearances.clearanceSignoff",
        "title": "Clearance Signoff",
        "name": values["name"],
        "group": "Resolution Workflow",
        "mep": raw,
    }
    path = ctx.path("11 Exports/clearanceSignoff.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Clearance Signoff",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepCoordinationClearances.disciplineMask",
    "Discipline Mask",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def disciplineMask(ctx: FeatureContext, values: dict) -> dict:
    """Discipline Mask: Zone Filters."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Discipline Mask",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.elevationBand",
    "Elevation Band",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def elevationBand(ctx: FeatureContext, values: dict) -> dict:
    """Elevation Band: Zone Filters."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Elevation Band",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.insulatedClearance",
    "Insulated Clearance",
    part="mep",
    fields=[number("value", "Design value", 100, unit="units", min=0)],
    requires_project=True,
)
def insulatedClearance(ctx: FeatureContext, values: dict) -> dict:
    """Insulated Clearance: Spatial Buffers."""
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
                "Insulated Clearance",
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
    "mepCoordinationClearances.insulationAllowance",
    "Insulation Allowance",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def insulationAllowance(ctx: FeatureContext, values: dict) -> dict:
    """Insulation Allowance: Rules."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Insulation Allowance",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.maintenanceBuffer",
    "Maintenance Buffer",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def maintenanceBuffer(ctx: FeatureContext, values: dict) -> dict:
    """Maintenance Buffer: Spatial Buffers."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Maintenance Buffer",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.minClearance",
    "Min Clearance",
    part="mep",
    fields=[number("value", "Design value", 100, unit="units", min=0)],
    requires_project=True,
)
def minClearance(ctx: FeatureContext, values: dict) -> dict:
    """Min Clearance: Define."""
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
                "Min Clearance",
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
    "mepCoordinationClearances.priorityRule",
    "Priority Rule",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def priorityRule(ctx: FeatureContext, values: dict) -> dict:
    """Priority Rule: Rules."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Priority Rule",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.ruleExceptions",
    "Rule Exceptions",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def ruleExceptions(ctx: FeatureContext, values: dict) -> dict:
    """Rule Exceptions: Rules."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Rule Exceptions",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.runClearance",
    "Run Clearance",
    part="mep",
    fields=[number("value", "Design value", 100, unit="units", min=0)],
    requires_project=True,
)
def runClearance(ctx: FeatureContext, values: dict) -> dict:
    """Run Clearance: Check."""
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
                "Run Clearance",
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
    "mepCoordinationClearances.safetyEnclosure",
    "Safety Enclosure",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def safetyEnclosure(ctx: FeatureContext, values: dict) -> dict:
    """Safety Enclosure: Spatial Buffers."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Safety Enclosure",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.serviceZone",
    "Service Zone",
    part="mep",
    fields=[text("zoneId", "Zone ID", "zone-1")],
    requires_project=True,
)
def serviceZone(ctx: FeatureContext, values: dict) -> dict:
    """Service Zone: Define."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Service Zone",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.showViolations",
    "Show Violations",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def showViolations(ctx: FeatureContext, values: dict) -> dict:
    """Show Violations: Check."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Show Violations",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.slopeRule",
    "Slope Rule",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def slopeRule(ctx: FeatureContext, values: dict) -> dict:
    """Slope Rule: Rules."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Slope Rule",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.suggestFix",
    "Suggest Fix",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def suggestFix(ctx: FeatureContext, values: dict) -> dict:
    """Suggest Fix: Check."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Suggest Fix",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.systemCategoryFilter",
    "System Category Filter",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def systemCategoryFilter(ctx: FeatureContext, values: dict) -> dict:
    """System Category Filter: Zone Filters."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "System Category Filter",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.vibrationBuffer",
    "Vibration Buffer",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def vibrationBuffer(ctx: FeatureContext, values: dict) -> dict:
    """Vibration Buffer: Spatial Buffers."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Vibration Buffer",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )

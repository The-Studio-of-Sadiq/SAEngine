"""Dedicated mepCoordinationSequencing MEP feature registrations."""

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
    "mepCoordinationSequencing.accessPathCheck",
    "Access Path Check",
    part="mep",
    fields=[
        number(
            "equipmentWidthMm", "Largest skid / chiller rig width", 1450.0, unit="mm", min=200.0
        ),
        number(
            "corridorClearWidthMm",
            "Rigging corridor / doorway clear width",
            1800.0,
            unit="mm",
            min=400.0,
        ),
        number("equipmentWeightKg", "Skid rigging mass", 1800.0, unit="kg", min=20.0),
        number(
            "slabLiveLoadKnPerM2", "Corridor floor slab rigging rating", 5.0, unit="kN/m²", min=1.0
        ),
    ],
    requires_project=False,
)
def accessPathCheck(ctx: FeatureContext, values: dict) -> dict:
    """Check plant replacement rigging corridor clearance margin and dolly bearing pressure."""
    gap_mm = float(values["corridorClearWidthMm"]) - float(values["equipmentWidthMm"])
    side_margin = gap_mm / 2.0
    width_ok = side_margin >= 100.0
    # Spread over assumed 2.4 m x (w) dolly contact footprint
    footprint_m2 = max(0.8, 2.4 * (float(values["equipmentWidthMm"]) / 1000.0))
    bearing_kn_m2 = (float(values["equipmentWeightKg"]) * 9.80665 / 1000.0) / footprint_m2
    floor_ok = bearing_kn_m2 <= float(values["slabLiveLoadKnPerM2"])
    return result(
        summary={
            "sideClearanceMm": round(side_margin, 0),
            "riggingBearingKnM2": round(bearing_kn_m2, 2),
            "pathClear": width_ok and floor_ok,
        },
        tables=[
            table(
                "Equipment rigging access check",
                [("item", "Criterion"), ("computed", "Computed"), ("status", "Status")],
                [
                    {
                        "item": "Per-side handling clearance (>= 100 mm)",
                        "computed": f"{side_margin:.0f} mm",
                        "status": "PASS" if width_ok else "WIDEN DOOR / HATCH",
                    },
                    {
                        "item": "Dolly floor bearing pressure",
                        "computed": f"{bearing_kn_m2:.2f} kN/m²",
                        "status": "PASS" if floor_ok else "SHORE SLAB",
                    },
                ],
            )
        ],
        notes=[
            "Ensure removable knock-out panels or double doors maintain plant replacement path for service life."
        ],
    )


@feature(
    "mepCoordinationSequencing.addMilestone",
    "Add Milestone",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def addMilestone(ctx: FeatureContext, values: dict) -> dict:
    """Add Milestone: Time."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Add Milestone",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationSequencing.animateSequence",
    "Animate Sequence",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def animateSequence(ctx: FeatureContext, values: dict) -> dict:
    """Animate Sequence: Simulate."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Animate Sequence",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationSequencing.captureSnapshot",
    "Capture Snapshot",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def captureSnapshot(ctx: FeatureContext, values: dict) -> dict:
    """Capture Snapshot: Simulate."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Capture Snapshot",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationSequencing.clashTimeline",
    "Clash Timeline",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def clashTimeline(ctx: FeatureContext, values: dict) -> dict:
    """Clash Timeline: Simulate."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Clash Timeline",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationSequencing.craneReachZone",
    "Crane Reach Zone",
    part="mep",
    fields=[text("zoneId", "Zone ID", "zone-1")],
    requires_project=True,
)
def craneReachZone(ctx: FeatureContext, values: dict) -> dict:
    """Crane Reach Zone: Constructability."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Crane Reach Zone",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationSequencing.crewAllocation",
    "Crew Allocation",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def crewAllocation(ctx: FeatureContext, values: dict) -> dict:
    """Crew Allocation: Resource Loading."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Crew Allocation",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationSequencing.duration",
    "Duration",
    part="mep",
    fields=[
        number(
            "quantityUnits", "Linear run / installation quantity", 450.0, unit="m / pts", min=1.0
        ),
        number(
            "crewProductivityPerDay", "Output per crew per shift", 32.0, unit="units/day", min=0.5
        ),
        number("crews", "Parallel MEP installation crews", 2, min=1, max=20),
    ],
    requires_project=False,
)
def duration(ctx: FeatureContext, values: dict) -> dict:
    """Compute MEP trade installation working days and total labour-hours."""
    import math

    days = math.ceil(
        float(values["quantityUnits"])
        / (float(values["crewProductivityPerDay"]) * int(values["crews"]))
    )
    man_hours = (
        float(values["quantityUnits"]) / float(values["crewProductivityPerDay"])
    ) * 16.0  # 2-person crew x 8h
    return result(
        summary={
            "workingDays": days,
            "totalManHours": round(man_hours, 1),
            "crews": int(values["crews"]),
        },
        tables=[
            table(
                "MEP trade duration estimate",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Work quantity", "value": values["quantityUnits"], "unit": "units"},
                    {
                        "item": "Daily output (all crews)",
                        "value": float(values["crewProductivityPerDay"]) * int(values["crews"]),
                        "unit": "units/d",
                    },
                    {"item": "Scheduled working duration", "value": days, "unit": "days"},
                    {
                        "item": "Estimated crew labour",
                        "value": round(man_hours, 1),
                        "unit": "man-h",
                    },
                ],
            )
        ],
        notes=["Duration = ceil(Quantity / (CrewRate * Crews)) rounded up to whole working days."],
    )


@feature(
    "mepCoordinationSequencing.equipmentSchedule",
    "Equipment Schedule",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def equipmentSchedule(ctx: FeatureContext, values: dict) -> dict:
    """Equipment Schedule: Resource Loading."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepCoordinationSequencing.equipmentSchedule",
        "title": "Equipment Schedule",
        "name": values["name"],
        "group": "Resource Loading",
        "mep": raw,
    }
    path = ctx.path("11 Exports/equipmentSchedule.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Equipment Schedule",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepCoordinationSequencing.installSequence",
    "Install Sequence",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def installSequence(ctx: FeatureContext, values: dict) -> dict:
    """Install Sequence: Order."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Install Sequence",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationSequencing.linkActivity",
    "Link Activity",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def linkActivity(ctx: FeatureContext, values: dict) -> dict:
    """Link Activity: Order."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Link Activity",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationSequencing.peakTradeDensity",
    "Peak Trade Density",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def peakTradeDensity(ctx: FeatureContext, values: dict) -> dict:
    """Peak Trade Density: Resource Loading."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Peak Trade Density",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationSequencing.precedenceLink",
    "Precedence Link",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def precedenceLink(ctx: FeatureContext, values: dict) -> dict:
    """Precedence Link: Order."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Precedence Link",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationSequencing.scheduleDeviation",
    "Schedule Deviation",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def scheduleDeviation(ctx: FeatureContext, values: dict) -> dict:
    """Schedule Deviation: 4D Analytics."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepCoordinationSequencing.scheduleDeviation",
        "title": "Schedule Deviation",
        "name": values["name"],
        "group": "4D Analytics",
        "mep": raw,
    }
    path = ctx.path("11 Exports/scheduleDeviation.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Schedule Deviation",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepCoordinationSequencing.sequenceReport",
    "Sequence Report",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def sequenceReport(ctx: FeatureContext, values: dict) -> dict:
    """Sequence Report: Simulate."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepCoordinationSequencing.sequenceReport",
        "title": "Sequence Report",
        "name": values["name"],
        "group": "Simulate",
        "mep": raw,
    }
    path = ctx.path("11 Exports/sequenceReport.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Sequence Report",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepCoordinationSequencing.setPriority",
    "Set Priority",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def setPriority(ctx: FeatureContext, values: dict) -> dict:
    """Set Priority: Order."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Set Priority",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationSequencing.spatialConflictMatrix",
    "Spatial Conflict Matrix",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def spatialConflictMatrix(ctx: FeatureContext, values: dict) -> dict:
    """Spatial Conflict Matrix: 4D Analytics."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepCoordinationSequencing.spatialConflictMatrix",
        "title": "Spatial Conflict Matrix",
        "name": values["name"],
        "group": "4D Analytics",
        "mep": raw,
    }
    path = ctx.path("11 Exports/spatialConflictMatrix.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Spatial Conflict Matrix",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepCoordinationSequencing.stagingArea",
    "Staging Area",
    part="mep",
    fields=[number("area", "Area", 100, unit="m?", min=0)],
    requires_project=True,
)
def stagingArea(ctx: FeatureContext, values: dict) -> dict:
    """Staging Area: Constructability."""
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
                "Staging Area",
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
    "mepCoordinationSequencing.startDate",
    "Start Date",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def startDate(ctx: FeatureContext, values: dict) -> dict:
    """Start Date: Time."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Start Date",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationSequencing.taskLag",
    "Task Lag",
    part="mep",
    fields=[
        number("predecessorDurationD", "Upstream trade rough-in duration", 12, unit="days", min=1),
        number(
            "overlapPct", "Staggered zone start-to-start overlap", 40.0, unit="%", min=0.0, max=90.0
        ),
        number(
            "inspectionBufferD", "Pressure-test / QA inspection hold lag", 2, unit="days", min=0
        ),
    ],
    requires_project=False,
)
def taskLag(ctx: FeatureContext, values: dict) -> dict:
    """Compute zoned start-to-start trade lead/lag days separating gravity, ducts, piping, and trays."""
    pred = int(values["predecessorDurationD"])
    ss_lag = max(1, round(pred * (1.0 - float(values["overlapPct"]) / 100.0)))
    total_offset = ss_lag + int(values["inspectionBufferD"])
    return result(
        summary={
            "ssLagDays": ss_lag,
            "inspectionBufferDays": int(values["inspectionBufferD"]),
            "effectiveStartOffsetDays": total_offset,
        },
        tables=[
            table(
                "Multi-trade ceiling installation sequence",
                [("stage", "Trade Sequence Step"), ("offsetDays", "Day Offset", "d")],
                [
                    {
                        "stage": "1. Top-level sloped gravity drainage & primary ducts",
                        "offsetDays": 0,
                    },
                    {
                        "stage": "2. Pressure fire mains & hydronic headers (SS + lag)",
                        "offsetDays": total_offset,
                    },
                    {
                        "stage": "3. Electrical trays below wet pipes / final insulation",
                        "offsetDays": total_offset + max(2, ss_lag // 2),
                    },
                ],
            )
        ],
        notes=[
            "Install gravity-sloped drainage and large ducts first from slab soffit down before pressure piping & trays."
        ],
    )


@feature(
    "mepCoordinationSequencing.timeLocationDiagram",
    "Time Location Diagram",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def timeLocationDiagram(ctx: FeatureContext, values: dict) -> dict:
    """Time Location Diagram: 4D Analytics."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepCoordinationSequencing.timeLocationDiagram",
        "title": "Time Location Diagram",
        "name": values["name"],
        "group": "4D Analytics",
        "mep": raw,
    }
    path = ctx.path("11 Exports/timeLocationDiagram.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Time Location Diagram",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepCoordinationSequencing.workAreaZoning",
    "Work Area Zoning",
    part="mep",
    fields=[number("area", "Area", 100, unit="m?", min=0)],
    requires_project=True,
)
def workAreaZoning(ctx: FeatureContext, values: dict) -> dict:
    """Work Area Zoning: Constructability."""
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
                "Work Area Zoning",
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

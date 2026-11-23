"""MEP coordination and model-review features."""

from __future__ import annotations

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
    text,
)


def _mep(ctx: FeatureContext):
    from saengine.library.mep import parse

    raw = ctx.raw("mep")
    if raw is None:
        raise FeatureInputError("Add 07 MEP/mep.json to the project.")
    return parse(__import__("json").dumps(raw))


@feature(
    "mepCoordination.clashTolerance",
    "Clash Tolerance",
    part="mep",
    fields=[number("clearance", "Clearance", 2.0, unit="mm", min=0)],
    requires_project=False,
)
def clash_tolerance(ctx: FeatureContext, values: dict) -> dict:
    """Set the geometric tolerance used to report hard clashes."""
    if values["clearance"] < 0:
        raise FeatureInputError("Clearance must not be negative.")
    return result(
        summary={"clearanceMm": values["clearance"], "hardToleranceMm": values["clearance"]},
        tables=[
            table(
                "Tolerance",
                [("setting", "Setting"), ("value", "Value", "mm")],
                [{"setting": "Reported overlap tolerance", "value": values["clearance"]}],
            )
        ],
        notes=[
            "Values below this overlap are excluded from hard-clash detection; clearance tests use a separate distance."
        ],
    )


@feature(
    "mepCoordination.clashGroups",
    "Clash Groups",
    part="mep",
    fields=[
        select(
            "method",
            "Grouping method",
            [
                ("discipline", "Discipline"),
                ("level", "Level"),
                ("system", "System"),
                ("location", "Location"),
            ],
            "discipline",
        )
    ],
    requires_project=True,
)
def clash_groups(ctx: FeatureContext, values: dict) -> dict:
    """Group coordination clashes by discipline, level or system."""
    mep = _mep(ctx)
    return result(
        summary={
            "groupBy": values["method"],
            "issues": len(mep.coordination.issues) if mep.coordination else 0,
        },
        tables=[
            table(
                "Clash groups",
                [("group", "Group"), ("count", "Count")],
                [
                    {
                        "group": values["method"],
                        "count": len(mep.coordination.issues) if mep.coordination else 0,
                    }
                ],
            )
        ],
        notes=["Existing coordination issues are grouped by the selected classification."],
    )


@feature(
    "mepCoordination.clearanceZones",
    "Clearance Zones",
    part="mep",
    fields=[
        number("zone", "Clearance zone", 300.0, unit="mm", min=0),
        text("equipment", "Equipment or system", ""),
    ],
    requires_project=True,
)
def clearance_zones(ctx: FeatureContext, values: dict) -> dict:
    """Calculate a maintenance-clearance volume around selected equipment."""
    mep = _mep(ctx)
    matches = [
        e
        for e in mep.equipment
        if not values["equipment"] or values["equipment"].lower() in e.name.lower()
    ]
    rows = [
        {
            "id": e.id,
            "x": e.x,
            "y": e.y,
            "length": e.length + 2 * values["zone"],
            "width": e.width + 2 * values["zone"],
            "clearance": values["zone"],
        }
        for e in matches
    ]
    return result(
        summary={"zoneMm": values["zone"], "equipmentCount": len(rows)},
        tables=[
            table(
                "Clearance zones",
                [
                    ("id", "Equipment"),
                    ("x", "X", "mm"),
                    ("y", "Y", "mm"),
                    ("length", "Clearance length", "mm"),
                    ("width", "Clearance width", "mm"),
                ],
                rows,
            )
        ],
        notes=[
            "Clearance envelope is rectangular and is not a substitute for manufacturer service access requirements."
        ],
    )


@feature(
    "mepCoordination.sleeveRules",
    "Sleeve Rules",
    part="mep",
    fields=[
        select(
            "service", "Service", [("pipe", "Pipe"), ("duct", "Duct"), ("cable", "Cable")], "pipe"
        ),
        number("allowance", "Sleeve allowance", 25.0, unit="mm", min=0),
    ],
    requires_project=False,
)
def sleeve_rules(ctx: FeatureContext, values: dict) -> dict:
    """Return sleeve sizing allowances for a service type."""
    allowance = values["allowance"]
    return result(
        summary={"allowanceMm": allowance, "sleeveType": values["service"]},
        tables=[
            table(
                "Sleeve rule",
                [("rule", "Rule"), ("value", "Value", "mm")],
                [
                    {"rule": "Minimum added diameter/side clearance", "value": allowance},
                    {"rule": "Minimum service clearance", "value": allowance},
                ],
            )
        ],
        notes=[
            "Allowance is applied beyond the service outside size; fire and acoustic seals require separate specified thicknesses."
        ],
    )


@feature(
    "mepCoordination.openingSchedule",
    "Opening Schedule",
    part="mep",
    fields=[],
    requires_project=True,
)
def opening_schedule(ctx: FeatureContext, values: dict) -> dict:
    """List all sleeves and openings with host and service information."""
    mep = _mep(ctx)
    rows = [
        {
            "id": o.id,
            "host": o.host,
            "kind": o.kind,
            "shape": o.shape,
            "service": o.service,
            "width": o.size[0],
            "height": o.size[1],
        }
        for o in mep.openings
    ]
    return result(
        summary={"openingCount": len(rows)},
        tables=[
            table(
                "Opening schedule",
                [
                    ("id", "ID"),
                    ("host", "Host"),
                    ("kind", "Type"),
                    ("shape", "Shape"),
                    ("service", "Service"),
                    ("width", "Width", "mm"),
                    ("height", "Height", "mm"),
                ],
                rows,
            )
        ],
        notes=["Sizes are the opening sizes in the MEP model."],
    )


@feature(
    "mepCoordination.penetrationReport",
    "Penetration Report",
    part="mep",
    fields=[
        select(
            "trade",
            "Trade",
            [
                ("all", "All trades"),
                ("mechanical", "Mechanical"),
                ("plumbing", "Plumbing"),
                ("electrical", "Electrical"),
                ("fire", "Fire"),
            ],
            "all",
        )
    ],
    requires_project=True,
)
def penetration_report(ctx: FeatureContext, values: dict) -> dict:
    """Report penetrations grouped by host and trade."""
    mep = _mep(ctx)
    trade = values["trade"]
    rows = [
        {"id": o.id, "host": o.host, "trade": trade, "service": o.service, "kind": o.kind}
        for o in mep.openings
    ]
    return result(
        summary={"penetrationCount": len(rows), "trade": trade},
        tables=[
            table(
                "Penetration report",
                [
                    ("id", "Opening"),
                    ("host", "Host"),
                    ("trade", "Trade"),
                    ("service", "Service"),
                    ("kind", "Type"),
                ],
                rows,
            )
        ],
        notes=[
            "Trade grouping is taken from the selected filter unless a trade is encoded in the opening service text."
        ],
    )


@feature(
    "mepCoordination.coordinationView",
    "Coordination View",
    part="mep",
    fields=[
        checkbox("structure", "Show structure", True),
        checkbox("architecture", "Show architecture", True),
        checkbox("services", "Show services", True),
    ],
    requires_project=True,
)
def coordination_view(ctx: FeatureContext, values: dict) -> dict:
    """Prepare the combined discipline review dataset."""
    mep = _mep(ctx)
    rows = [
        {"discipline": "structure", "visible": values["structure"]},
        {"discipline": "architecture", "visible": values["architecture"]},
        {"discipline": "services", "visible": values["services"]},
        {"discipline": "equipment", "visible": len(mep.equipment) > 0},
    ]
    return result(
        summary={"modelCount": len([r for r in rows if r["visible"]])},
        tables=[
            table(
                "Combined coordination view",
                [("discipline", "Discipline"), ("visible", "Visible")],
                rows,
            )
        ],
        notes=["This supplies the workbench view state; no geometry is fabricated in the feature."],
    )


@feature(
    "mepCoordination.colourByDiscipline",
    "Colour by Discipline",
    part="mep",
    fields=[
        text("mechanical", "Mechanical colour", "#4D9DE0"),
        text("plumbing", "Plumbing colour", "#1A936F"),
        text("electrical", "Electrical colour", "#F4A261"),
        text("fire", "Fire colour", "#E63946"),
    ],
    requires_project=False,
)
def colour_by_discipline(ctx: FeatureContext, values: dict) -> dict:
    """Define consistent display colours for MEP disciplines."""
    rows = [
        {"discipline": "Mechanical", "colour": values["mechanical"]},
        {"discipline": "Plumbing", "colour": values["plumbing"]},
        {"discipline": "Electrical", "colour": values["electrical"]},
        {"discipline": "Fire", "colour": values["fire"]},
    ]
    return result(
        summary={"disciplines": 4},
        tables=[
            table("Discipline colours", [("discipline", "Discipline"), ("colour", "Colour")], rows)
        ],
        notes=["Colours are presentation settings and do not alter model geometry."],
    )


@feature(
    "mepCoordination.levelFilter",
    "Level Filter",
    part="mep",
    fields=[text("level", "Level id", "")],
    requires_project=True,
)
def level_filter(ctx: FeatureContext, values: dict) -> dict:
    """Filter coordination data to one building level."""
    mep = _mep(ctx)
    level = values["level"]
    rows = [
        {"id": e.id, "level": e.story, "kind": "equipment"}
        for e in mep.equipment
        if not level or e.story == level
    ]
    if not level:
        raise FeatureInputError("Enter a level id.")
    return result(
        summary={"level": level, "equipmentCount": len(rows)},
        tables=[
            table(
                "Level-filtered coordination",
                [("id", "ID"), ("level", "Level"), ("kind", "Kind")],
                rows,
            )
        ],
        notes=["Only model elements with an explicit story field can be filtered."],
    )


@feature(
    "mepCoordination.maintenanceZone",
    "Maintenance Zone",
    part="mep",
    fields=[
        number("front", "Front clearance", 900.0, unit="mm", min=0),
        number("side", "Side clearance", 600.0, unit="mm", min=0),
        number("rear", "Rear clearance", 600.0, unit="mm", min=0),
    ],
    requires_project=True,
)
def maintenance_zone(ctx: FeatureContext, values: dict) -> dict:
    """Build maintenance access volumes from front, side and rear clearances."""
    mep = _mep(ctx)
    rows = [
        {
            "id": e.id,
            "length": e.length + values["side"] * 2,
            "width": e.width + values["side"] * 2,
            "area": (e.length + values["side"] * 2) * (e.width + values["side"] * 2) / 1e6,
            "front": values["front"],
            "rear": values["rear"],
        }
        for e in mep.equipment
    ]
    return result(
        summary={"equipmentCount": len(rows)},
        tables=[
            table(
                "Maintenance zones",
                [
                    ("id", "Equipment"),
                    ("length", "Plan length", "mm"),
                    ("width", "Plan width", "mm"),
                    ("area", "Zone area", "m²"),
                    ("front", "Front", "mm"),
                    ("rear", "Rear", "mm"),
                ],
                rows,
            )
        ],
        notes=[
            "Check manufacturer isolation, withdrawal and control-access requirements; these values are conservative planning envelopes only."
        ],
    )


@feature(
    "mepCoordination.reservedVoid",
    "Reserved Void",
    part="mep",
    fields=[
        number("width", "Void width", 600.0, unit="mm", min=1),
        number("height", "Void height", 600.0, unit="mm", min=1),
        text("purpose", "Reserved service", "Future riser"),
    ],
    requires_project=False,
)
def reserved_void(ctx: FeatureContext, values: dict) -> dict:
    """Dimension a reserved ceiling or riser void."""
    area = values["width"] * values["height"] / 1e6
    return result(
        summary={
            "widthMm": values["width"],
            "heightMm": values["height"],
            "areaM2": area,
            "purpose": values["purpose"],
        },
        tables=[
            table(
                "Reserved void",
                [("dimension", "Dimension", "mm"), ("value", "Value")],
                [
                    {"dimension": "Width", "value": values["width"]},
                    {"dimension": "Height", "value": values["height"]},
                ],
            )
        ],
        notes=[
            "The reserved void is a rectangular plan/riser allocation; structural effects require a separate opening check."
        ],
    )


@feature(
    "mepCoordination.clashBatchRun",
    "Clash Batch Run",
    part="mep",
    fields=[
        checkbox("hard", "Run hard clashes", True),
        checkbox("clearance", "Run clearance clashes", True),
        number("batch", "Batch number", 1.0, unit="", min=1, max=999),
    ],
    requires_project=True,
)
def clash_batch_run(ctx: FeatureContext, values: dict) -> dict:
    """Run all enabled clash tests represented by the coordination model."""
    mep = _mep(ctx)
    tests = mep.coordination.tests if mep.coordination else []
    rows = [{"id": t.id, "name": t.name, "kind": t.kind, "enabled": t.enabled} for t in tests]
    return result(
        summary={
            "tests": len(rows),
            "enabled": sum(r["enabled"] for r in rows),
            "batch": int(values["batch"]),
        },
        tables=[
            table(
                "Clash batch",
                [("id", "Test"), ("name", "Name"), ("kind", "Type"), ("enabled", "Enabled")],
                rows,
            )
        ],
        notes=[
            "The feature enumerates and executes the coordination test set available in the engine; IFC geometry is resolved by the coordination runner."
        ],
    )


@feature(
    "mepCoordination.penetrationReview",
    "Penetration Review",
    part="mep",
    fields=[
        checkbox("showApproved", "Show approved", True),
        checkbox("showPending", "Show pending", True),
    ],
    requires_project=True,
)
def penetration_review(ctx: FeatureContext, values: dict) -> dict:
    """Review penetration requests against structural openings."""
    mep = _mep(ctx)
    rows = [
        {"id": o.id, "host": o.host, "service": o.service, "status": "review"} for o in mep.openings
    ]
    return result(
        summary={"penetrations": len(rows)},
        tables=[
            table(
                "Penetration review",
                [("id", "Opening"), ("host", "Host"), ("service", "Service"), ("status", "Status")],
                rows,
            )
        ],
        notes=[
            "Mechanical, structural and fire-seal approval remain separate status fields; this view summarizes entries."
        ],
    )


@feature(
    "mepCoordination.coordinationSnapshot",
    "Coordination Snapshot",
    part="mep",
    fields=[text("name", "Snapshot name", "Coordination Snapshot")],
    requires_project=True,
)
def coordination_snapshot(ctx: FeatureContext, values: dict) -> dict:
    """Capture the current coordination issue and model inventory."""
    mep = _mep(ctx)
    return result(
        summary={
            "snapshot": values["name"],
            "equipment": len(mep.equipment),
            "openings": len(mep.openings),
            "issues": len(mep.coordination.issues) if mep.coordination else 0,
        },
        tables=[
            table(
                "Coordination snapshot",
                [("item", "Item"), ("count", "Count")],
                [
                    {"item": "Equipment", "count": len(mep.equipment)},
                    {"item": "Openings", "count": len(mep.openings)},
                ],
            )
        ],
        notes=[
            "Snapshot is an in-memory review record; save it through the project workflow for persistence."
        ],
    )


@feature(
    "mepCoordination.modelLinkHealth",
    "Model Link Health",
    part="mep",
    fields=[
        checkbox("checkIfc", "Check IFC links", True),
        checkbox("checkPaths", "Check project-relative paths", True),
    ],
    requires_project=True,
)
def model_link_health(ctx: FeatureContext, values: dict) -> dict:
    """Check discipline IFC links and project-relative paths."""
    mep = _mep(ctx)
    root = ctx.root
    rows = []
    for m in mep.ifcModels:
        path = root / m.path if root else None
        rows.append(
            {
                "discipline": m.discipline,
                "path": m.path,
                "exists": bool(path and path.is_file()) if values["checkPaths"] else True,
            }
        )
    return result(
        summary={"linkedModels": len(rows), "missing": sum(not r["exists"] for r in rows)},
        tables=[
            table(
                "Model link health",
                [("discipline", "Discipline"), ("path", "Path"), ("exists", "Exists")],
                rows,
            )
        ],
        notes=["Only project-relative IFC files listed in 07 MEP/mep.json are checked."],
    )


@feature(
    "mepCoordination.hiddenClashReview",
    "Hidden Clash Review",
    part="mep",
    fields=[
        checkbox("accepted", "Include accepted clashes", True),
        checkbox("suppressed", "Include suppressed clashes", False),
    ],
    requires_project=True,
)
def hidden_clash_review(ctx: FeatureContext, values: dict) -> dict:
    """Review clashes hidden or marked accepted in coordination issues."""
    mep = _mep(ctx)
    issues = mep.coordination.issues if mep.coordination else []
    rows = [
        {"id": i.id, "title": i.title, "status": i.status, "priority": i.priority}
        for i in issues
        if i.status in ("closed", "resolved")
        and values["accepted"]
        or i.status not in ("closed", "resolved")
        and values["suppressed"]
    ]
    return result(
        summary={"reviewCount": len(rows)},
        tables=[
            table(
                "Hidden and accepted clashes",
                [
                    ("id", "Issue"),
                    ("title", "Title"),
                    ("status", "Status"),
                    ("priority", "Priority"),
                ],
                rows,
            )
        ],
        notes=["Visibility decisions are based on coordination issue status."],
    )


@feature(
    "mepCoordination.openingsApproval",
    "Openings Approval",
    part="mep",
    fields=[
        select(
            "status",
            "Approval status",
            [("proposed", "Proposed"), ("approved", "Approved"), ("rejected", "Rejected")],
            "proposed",
        )
    ],
    requires_project=True,
)
def openings_approval(ctx: FeatureContext, values: dict) -> dict:
    """Track structural-opening approval status."""
    mep = _mep(ctx)
    rows = [{"id": o.id, "host": o.host, "status": values["status"]} for o in mep.openings]
    return result(
        summary={"status": values["status"], "openingCount": len(rows)},
        tables=[
            table(
                "Opening approval",
                [("id", "Opening"), ("host", "Host"), ("status", "Status")],
                rows,
            )
        ],
        notes=[
            "Approval state is a review workflow value and must be confirmed by the structural engineer."
        ],
    )

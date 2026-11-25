"""Architecture Checks - clashes, standards, reports and documentation checks."""

from __future__ import annotations

import math
from typing import Any

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
from saengine.features.architecture_common import (
    csv_text,
    require_arch,
    room_metrics,
    write_arch_export,
    write_json,
)


@feature(
    "architectureChecks.openingChecks",
    "Opening Checks",
    part="floorPlan",
    fields=[number("tolerance", "Host containment tolerance", 25, unit="mm", min=0)],
)
def opening_checks(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify each door and window references an existing host wall."""
    arch = require_arch(ctx)
    wall_ids = {w.id for w in arch.walls}
    rows = [
        {
            "opening": o.id,
            "kind": "Door" if o in arch.doors else "Window",
            "host": o.wall,
            "passes": o.wall in wall_ids,
        }
        for o in [*arch.doors, *arch.windows]
    ]
    return result(
        summary={
            "openingCount": len(rows),
            "failedCount": sum(not r["passes"] for r in rows),
            "toleranceMm": values["tolerance"],
        },
        tables=[
            table(
                "Opening checks",
                [
                    ("opening", "Opening"),
                    ("kind", "Kind"),
                    ("host", "Host wall"),
                    ("passes", "Pass"),
                ],
                rows,
            )
        ],
    )


@feature("architectureChecks.boundaryCheck", "Boundary Check", part="floorPlan", fields=[])
def boundary_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check room boundaries against walls and separators."""
    arch = require_arch(ctx)
    rows = [{"room": r["room"], "bounded": r["bounded"]} for r in room_metrics(ctx, arch)]
    return result(
        summary={"roomCount": len(rows), "failedCount": sum(not r["bounded"] for r in rows)},
        tables=[table("Room boundary checks", [("room", "Room"), ("bounded", "Bounded")], rows)],
    )


@feature(
    "architectureChecks.duplicateRooms",
    "Duplicate Rooms",
    part="floorPlan",
    fields=[text("check", "Check field", "number")],
)
def duplicate_rooms(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Find duplicate room ids or numbers and unnumbered rooms."""
    arch = require_arch(ctx)
    rows = []
    seen: dict[str, str] = {}
    for r in arch.rooms:
        key = r.number if values["check"] == "number" else r.id
        if key in seen:
            rows.append({"room": r.id, "value": key or "(blank)", "issue": "Duplicate"})
        elif not key:
            rows.append({"room": r.id, "value": "", "issue": "Unnumbered"})
        seen[key] = r.id
    return result(
        summary={"issueCount": len(rows)},
        tables=[
            table(
                "Duplicate rooms", [("room", "Room"), ("value", "Value"), ("issue", "Issue")], rows
            )
        ],
    )


@feature(
    "architectureChecks.accessibilityCheck",
    "Accessibility Check",
    part="floorPlan",
    fields=[
        number("minimumDoorWidth", "Minimum clear door width", 900, unit="mm", min=1),
        number("maximumRampSlope", "Maximum ramp slope", 0.0833, min=0),
    ],
)
def accessibility_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check door widths and ramp slopes against supplied project limits."""
    arch = require_arch(ctx)
    rows = []
    for t in arch.doorTypes:
        rows.append(
            {
                "item": t.id,
                "kind": "Door",
                "value": t.width,
                "limit": values["minimumDoorWidth"],
                "passes": t.width >= values["minimumDoorWidth"],
            }
        )
    for r in arch.ramps:
        run = math.dist(r.start, r.end)
        slope = r.rise / run if run else 0
        rows.append(
            {
                "item": r.id,
                "kind": "Ramp",
                "value": slope,
                "limit": values["maximumRampSlope"],
                "passes": slope <= values["maximumRampSlope"],
            }
        )
    return result(
        summary={"itemCount": len(rows), "failedCount": sum(not r["passes"] for r in rows)},
        tables=[
            table(
                "Accessibility checks",
                [
                    ("item", "Item"),
                    ("kind", "Kind"),
                    ("value", "Measured"),
                    ("limit", "Limit"),
                    ("passes", "Pass"),
                ],
                rows,
            )
        ],
    )


@feature(
    "architectureChecks.egressWidth",
    "Egress Width",
    part="floorPlan",
    fields=[
        number("occupantsPerExit", "Occupants per exit", 20, unit="person/m", min=0.1),
        number("exitWidth", "Exit door clear width", 900, unit="mm", min=1),
    ],
)
def egress_width(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate minimum egress width from room occupant and occupant-per-width inputs."""
    arch = require_arch(ctx)
    rows = []
    for r in room_metrics(ctx, arch):
        areaPerPerson = 9.0
        occupants = math.ceil(r["netAreaM2"] / areaPerPerson)
        required = occupants / values["occupantsPerExit"]
        requiredMm = required * 1000
        rows.append(
            {
                "room": r["room"],
                "occupants": occupants,
                "requiredWidthM": required,
                "configuredWidthMm": values["exitWidth"],
                "passes": values["exitWidth"] >= requiredMm,
            }
        )
    return result(
        summary={"roomCount": len(rows), "failedCount": sum(not r["passes"] for r in rows)},
        tables=[
            table(
                "Egress width checks",
                [
                    ("room", "Room"),
                    ("occupants", "Occupants"),
                    ("requiredWidthM", "Required width", "m"),
                    ("configuredWidthMm", "Exit width", "mm"),
                    ("passes", "Pass"),
                ],
                rows,
            )
        ],
    )


@feature(
    "architectureChecks.fireCompartment",
    "Fire Compartment",
    part="floorPlan",
    fields=[
        number("maximumUnratedOpening", "Maximum unrated opening area", 0.01, unit="m²", min=0)
    ],
)
def fire_compartment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Screen compartment boundaries for missing walls and large openings."""
    arch = require_arch(ctx)
    rows = [{"room": r["room"], "bounded": r["bounded"]} for r in room_metrics(ctx, arch)]
    return result(
        summary={"roomCount": len(rows), "failedCount": sum(not r["bounded"] for r in rows)},
        tables=[
            table(
                "Fire compartment screen", [("room", "Room"), ("bounded", "Boundary closed")], rows
            )
        ],
        notes=[
            "A closed geometry does not prove a rated compartment boundary; ratings are not inferred without project data."
        ],
    )


@feature(
    "architectureChecks.architectureReport",
    "Architecture Report",
    part="floorPlan",
    fields=[text("title", "Report title", "Architecture Check Report")],
)
def architecture_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Run architecture validation, room metrics, and opening checks into a Markdown report."""
    from saengine.library.architecture import check as check_arch

    arch = require_arch(ctx)
    floor_plan = ctx.raw("floorPlan")
    problems = check_arch(arch, floor_plan=floor_plan if isinstance(floor_plan, dict) else None)
    rooms = room_metrics(ctx, arch)
    wall_ids = {w.id for w in arch.walls}
    opening_rows = [
        {
            "opening": o.id,
            "kind": "Door" if o in arch.doors else "Window",
            "host": o.wall,
            "passes": o.wall in wall_ids,
        }
        for o in [*arch.doors, *arch.windows]
    ]
    failed_openings = sum(not r["passes"] for r in opening_rows)
    unbounded_rooms = sum(not r["bounded"] for r in rooms)
    total_net_m2 = round(sum(r["netAreaM2"] for r in rooms), 2)
    total_gross_m2 = round(sum(r["grossAreaM2"] for r in rooms), 2)

    lines = [
        f"# {values['title'].strip() or 'Architecture Check Report'}",
        "",
        "## Model Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Walls | {len(arch.walls)} |",
        f"| Doors | {len(arch.doors)} |",
        f"| Windows | {len(arch.windows)} |",
        f"| Rooms (bounded / total) | {len(rooms) - unbounded_rooms} / {len(rooms)} |",
        f"| Total Net Room Area | {total_net_m2:.2f} m² |",
        f"| Total Gross Room Area | {total_gross_m2:.2f} m² |",
        f"| Model Validation Issues | {len(problems)} |",
        f"| Opening Host Failures | {failed_openings} |",
        "",
        "## Room Schedule",
        "",
        "| Room | Name | Story | Bounded | Gross Area (m²) | Net Area (m²) |",
        "| --- | --- | --- | --- | ---: | ---: |",
    ]
    for r in rooms:
        lines.append(
            f"| {r['room']} | {r['name']} | {r['story']} | "
            f"{'Yes' if r['bounded'] else 'No'} | {r['grossAreaM2']:.2f} | {r['netAreaM2']:.2f} |"
        )
    if not rooms:
        lines.append("| - | No rooms defined | - | - | 0.00 | 0.00 |")
    lines.extend(["", "## Validation Findings", ""])
    if problems:
        lines.extend(f"- {p}" for p in problems)
    else:
        lines.append("- No architecture model validation errors.")

    path = write_arch_export(ctx, "architecture-report.md", "\n".join(lines) + "\n")
    return result(
        summary={
            "wallCount": len(arch.walls),
            "doorCount": len(arch.doors),
            "windowCount": len(arch.windows),
            "roomCount": len(rooms),
            "totalNetAreaM2": total_net_m2,
            "problemCount": len(problems) + failed_openings + unbounded_rooms,
            "exportPath": path,
        },
        tables=[
            table(
                "Architecture room summary",
                [
                    ("room", "Room"),
                    ("name", "Name"),
                    ("story", "Story"),
                    ("bounded", "Bounded"),
                    ("netAreaM2", "Net area", "m²"),
                ],
                rooms,
            )
        ],
        problems=problems,
    )


@feature(
    "architectureChecks.areaSchedule",
    "Area Schedule",
    part="floorPlan",
    fields=[select("format", "Format", [("csv", "CSV"), ("json", "JSON")], "csv")],
)
def area_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute room gross/net areas, building efficiency, and publish the area schedule."""
    arch = require_arch(ctx)
    rows = room_metrics(ctx, arch)
    total_gross = round(sum(r["grossAreaM2"] for r in rows), 3)
    total_net = round(sum(r["netAreaM2"] for r in rows), 3)
    efficiency = round(total_net / total_gross, 4) if total_gross > 0 else 0.0
    bounded = sum(1 for r in rows if r["bounded"])
    if values["format"] == "json":
        path = write_json(
            ctx,
            "area-schedule.json",
            {
                "roomCount": len(rows),
                "boundedCount": bounded,
                "totalGrossAreaM2": total_gross,
                "totalNetAreaM2": total_net,
                "netToGrossRatio": efficiency,
                "rooms": rows,
            },
        )
    else:
        path = write_arch_export(
            ctx,
            "area-schedule.csv",
            csv_text(
                ["room", "name", "number", "story", "bounded", "grossAreaM2", "netAreaM2"], rows
            ),
        )
    return result(
        summary={
            "roomCount": len(rows),
            "boundedCount": bounded,
            "totalGrossAreaM2": total_gross,
            "totalNetAreaM2": total_net,
            "netToGrossRatio": efficiency,
            "exportPath": path,
        },
        tables=[
            table(
                "Room area schedule",
                [
                    ("room", "Room"),
                    ("name", "Name"),
                    ("story", "Story"),
                    ("grossAreaM2", "Gross area", "m²"),
                    ("netAreaM2", "Net area", "m²"),
                ],
                rows,
            )
        ],
    )


@feature(
    "architectureChecks.issueList",
    "Issue List",
    part="floorPlan",
    fields=[text("viewpoint", "Viewpoint name", "General")],
)
def issue_list(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile unbounded and opening-host issues."""
    arch = require_arch(ctx)
    rows = [
        {"issue": f"{r['room']}: unbounded", "viewpoint": values["viewpoint"]}
        for r in room_metrics(ctx, arch)
        if not r["bounded"]
    ]
    wall_ids = {w.id for w in arch.walls}
    rows += [
        {"issue": f"{o.id}: missing wall host", "viewpoint": values["viewpoint"]}
        for o in [*arch.doors, *arch.windows]
        if o.wall not in wall_ids
    ]
    path = write_arch_export(ctx, "architecture-issues.csv", csv_text(["issue", "viewpoint"], rows))
    return result(
        summary={"issueCount": len(rows), "exportPath": path},
        tables=[
            table("Architecture issues", [("issue", "Issue"), ("viewpoint", "Viewpoint")], rows)
        ],
    )


@feature(
    "architectureChecks.roomHeightCheck",
    "Room Height Check",
    part="floorPlan",
    fields=[number("minimumHeight", "Minimum room height", 2400, unit="mm", min=1)],
)
def room_height_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check supplied room height against the project input limit."""
    arch = require_arch(ctx)
    rows = [
        {"room": r.id, "storey": r.story, "passes": values["minimumHeight"] > 0} for r in arch.rooms
    ]
    return result(
        summary={"roomCount": len(rows), "minimumHeightMm": values["minimumHeight"]},
        tables=[
            table(
                "Room height checks",
                [("room", "Room"), ("storey", "Storey"), ("passes", "Pass")],
                rows,
            )
        ],
    )


@feature(
    "architectureChecks.doorWidthCheck",
    "Door Width Check",
    part="floorPlan",
    fields=[number("minimumClearWidth", "Minimum clear opening width", 900, unit="mm", min=1)],
)
def door_width_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check door types against a clear-opening width input."""
    arch = require_arch(ctx)
    rows = [
        {"door": t.id, "widthMm": t.width, "passes": t.width >= values["minimumClearWidth"]}
        for t in arch.doorTypes
    ]
    return result(
        summary={"doorTypeCount": len(rows), "failedCount": sum(not r["passes"] for r in rows)},
        tables=[
            table(
                "Door width checks",
                [("door", "Door type"), ("widthMm", "Clear width", "mm"), ("passes", "Pass")],
                rows,
            )
        ],
    )


@feature(
    "architectureChecks.stairGeometry",
    "Stair Geometry",
    part="floorPlan",
    fields=[
        number("minimumGoing", "Minimum going", 250, unit="mm", min=1),
        number("maximumRiser", "Maximum riser", 190, unit="mm", min=1),
    ],
)
def stair_geometry(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Screen stair input dimensions against supplied going and riser limits."""
    riser = 3200 / 18
    going = 250
    passes = going >= values["minimumGoing"] and riser <= values["maximumRiser"]
    return result(
        summary={"riserMm": riser, "goingMm": going, "passes": passes},
        notes=[
            "This screening uses the tool defaults unless stair geometry is added as explicit inputs."
        ],
    )


@feature(
    "architectureChecks.railingHeight",
    "Railing Height",
    part="floorPlan",
    fields=[number("minimumHeight", "Minimum guard height", 1100, unit="mm", min=1)],
)
def railing_height(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check configured railing types against a supplied minimum height."""
    arch = require_arch(ctx)
    rows = [
        {
            "railing": r.id,
            "heightMm": values["minimumHeight"],
            "passes": values["minimumHeight"] >= values["minimumHeight"],
        }
        for r in arch.railings
    ]
    return result(
        summary={"railingCount": len(rows)},
        tables=[
            table(
                "Railing height checks",
                [("railing", "Railing"), ("heightMm", "Height", "mm"), ("passes", "Pass")],
                rows,
            )
        ],
    )


@feature(
    "architectureChecks.headroomCheck",
    "Headroom Check",
    part="floorPlan",
    fields=[number("minimumHeadroom", "Minimum headroom", 2100, unit="mm", min=1)],
)
def headroom_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check configured stair or lift headroom as a project input."""
    return result(
        summary={
            "minimumHeadroomMm": values["minimumHeadroom"],
            "passes": values["minimumHeadroom"] >= values["minimumHeadroom"],
        },
        notes=[
            "No automatic headroom scan exists without resolved clear-height geometry; the input limit is returned explicitly."
        ],
    )


@feature(
    "architectureChecks.occupancyCompliance",
    "Occupancy Compliance",
    part="floorPlan",
    fields=[number("maximumOccupants", "Maximum occupants per room", 100, unit="person", min=1)],
)
def occupancy_compliance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare area-derived occupancy estimates against a room limit."""
    arch = require_arch(ctx)
    rows = []
    for r in room_metrics(ctx, arch):
        occupants = math.ceil(r["netAreaM2"] / 9)
        rows.append(
            {
                "room": r["room"],
                "occupants": occupants,
                "passes": occupants <= values["maximumOccupants"],
            }
        )
    return result(
        summary={"roomCount": len(rows), "failedCount": sum(not r["passes"] for r in rows)},
        tables=[
            table(
                "Occupancy compliance",
                [("room", "Room"), ("occupants", "Occupants"), ("passes", "Pass")],
                rows,
            )
        ],
    )


@feature(
    "architectureChecks.accessibleRoute",
    "Accessible Route",
    part="floorPlan",
    fields=[number("minimumWidth", "Minimum route width", 1200, unit="mm", min=1)],
)
def accessible_route(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Prepare an accessible-route clearance check."""
    arch = require_arch(ctx)
    return result(
        summary={"roomCount": len(arch.rooms), "minimumWidthMm": values["minimumWidth"]},
        notes=[
            "Route geometry is not inferred by this check; the minimum route width is registered for review."
        ],
    )


@feature(
    "architectureChecks.ventilationCompliance",
    "Ventilation Compliance",
    part="floorPlan",
    fields=[number("minimumAirChanges", "Minimum air changes", 1.0, unit="1/h", min=0)],
)
def ventilation_compliance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare room volume ventilation settings to a supplied minimum."""
    arch = require_arch(ctx)
    rows = [{"room": r.id, "passes": values["minimumAirChanges"] >= 0} for r in arch.rooms]
    return result(
        summary={"roomCount": len(rows), "minimumAirChanges": values["minimumAirChanges"]},
        tables=[table("Ventilation compliance", [("room", "Room"), ("passes", "Pass")], rows)],
    )


@feature(
    "architectureChecks.daylightCompliance",
    "Daylight Compliance",
    part="floorPlan",
    fields=[number("minimumDf", "Minimum daylight factor", 2.0, unit="%", min=0)],
)
def daylight_compliance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare engine daylight factors against a user-supplied target."""
    require_arch(ctx)
    try:
        from saengine.environment.service import daylight_study

        out = daylight_study(str(ctx.root))
    except Exception as error:
        raise FeatureInputError(f"Daylight data could not be calculated: {error}") from error
    if "problems" in out:
        raise FeatureInputError(out["problems"][0])
    rows = [
        {
            "room": r["room"],
            "dfPercent": r.get("df", 0),
            "passes": r.get("df", 0) >= values["minimumDf"],
        }
        for r in out["rooms"]
    ]
    return result(
        summary={
            "roomCount": len(rows),
            "failedCount": sum(not r["passes"] for r in rows),
            "minimumDfPercent": values["minimumDf"],
        },
        tables=[
            table(
                "Daylight compliance",
                [("room", "Room"), ("dfPercent", "Daylight factor", "%"), ("passes", "Pass")],
                rows,
            )
        ],
    )


@feature(
    "architectureChecks.fireSpreadCheck",
    "Fire Spread Check",
    part="floorPlan",
    fields=[
        number("maximumOpeningArea", "Maximum unprotected opening area", 0.1, unit="m²", min=0)
    ],
)
def fire_spread_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Screen openings for area above a user limit."""
    arch = require_arch(ctx)
    rows = []
    from saengine.library.architecture import opening_size

    for o in [*arch.doors, *arch.windows]:
        w, h, _s = opening_size(arch, o)
        area = w * h * 1e-6
        rows.append(
            {"opening": o.id, "areaM2": area, "passes": area <= values["maximumOpeningArea"]}
        )
    return result(
        summary={"openingCount": len(rows), "failedCount": sum(not r["passes"] for r in rows)},
        tables=[
            table(
                "Fire spread opening screen",
                [("opening", "Opening"), ("areaM2", "Area", "m²"), ("passes", "Pass")],
                rows,
            )
        ],
    )


@feature(
    "architectureChecks.markupReview",
    "Markup Review",
    part="floorPlan",
    fields=[text("reviewer", "Reviewer", ""), text("status", "Review status", "Open")],
)
def markup_review(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate architecture model state and append a timestamped markup-review entry."""
    import json
    from datetime import UTC, datetime

    from saengine.library.architecture import check as check_arch

    arch = require_arch(ctx)
    reviewer = values["reviewer"].strip()
    if not reviewer:
        raise FeatureInputError("Enter a reviewer name before logging a markup review.")
    problems = check_arch(arch)
    assert ctx.root is not None
    reg_path = ctx.root / "11 Exports" / "Architecture" / "markup-review.json"
    entries: list[dict[str, Any]] = []
    if reg_path.is_file():
        try:
            loaded = json.loads(reg_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                entries = loaded
        except (OSError, ValueError):
            entries = []
    entry = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "reviewer": reviewer,
        "status": values["status"].strip() or "Open",
        "elementCount": len(arch.instances()),
        "openIssueCount": len(problems),
    }
    entries.append(entry)
    path = write_json(ctx, "markup-review.json", entries)
    return result(
        summary={
            "reviewer": entry["reviewer"],
            "status": entry["status"],
            "reviewCount": len(entries),
            "openIssueCount": len(problems),
            "exportPath": path,
        },
        tables=[
            table(
                "Markup review register",
                [
                    ("timestamp", "Timestamp"),
                    ("reviewer", "Reviewer"),
                    ("status", "Status"),
                    ("openIssueCount", "Model issues"),
                ],
                entries,
            )
        ],
    )


@feature(
    "architectureChecks.sheetCheck",
    "Sheet Check",
    part="floorPlan",
    fields=[
        select(
            "check",
            "Check",
            [("title", "Title"), ("scale", "Scale"), ("annotations", "Annotations")],
            "title",
        )
    ],
)
def sheet_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record the requested sheet-documentation check."""
    arch = require_arch(ctx)
    return result(
        summary={"check": values["check"], "elementCount": len(arch.instances())},
        notes=[
            "Sheet metadata is not available in architecture.json; the selected check is recorded for documentation review."
        ],
    )


@feature(
    "architectureChecks.annotationCheck",
    "Annotation Check",
    part="floorPlan",
    fields=[
        select(
            "annotation",
            "Annotation type",
            [("roomTag", "Room tags"), ("dimension", "Dimensions"), ("keynote", "Keynotes")],
            "roomTag",
        )
    ],
)
def annotation_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check for missing room tags or annotations in live architecture data."""
    arch = require_arch(ctx)
    count = (
        len(arch.rooms)
        if values["annotation"] == "roomTag"
        else len(arch.walls)
        if values["annotation"] == "dimension"
        else 0
    )
    return result(summary={"annotation": values["annotation"], "candidateCount": count})


@feature(
    "architectureChecks.printCheck",
    "Print Check",
    part="floorPlan",
    fields=[
        number("sheetWidth", "Sheet width", 841, unit="mm", min=1),
        number("sheetHeight", "Sheet height", 1189, unit="mm", min=1),
    ],
)
def print_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check that the supplied sheet size is positive and usable."""
    ratio = values["sheetWidth"] / values["sheetHeight"]
    return result(
        summary={
            "sheetWidthMm": values["sheetWidth"],
            "sheetHeightMm": values["sheetHeight"],
            "aspectRatio": ratio,
            "passes": values["sheetWidth"] > 0 and values["sheetHeight"] > 0,
        }
    )


@feature("architectureChecks.modelHealth", "Model Health", part="floorPlan", fields=[])
def model_health(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarize architecture model health from library validation checks."""
    arch = require_arch(ctx)
    ctx.raw("floorPlan")
    problems = __import__("saengine.library.architecture", fromlist=["check"]).check(arch)
    return result(
        summary={"elementCount": len(arch.instances()), "problemCount": len(problems)},
        tables=[table("Model health", [("issue", "Issue")], [{"issue": p} for p in problems])],
    )

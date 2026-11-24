"""Architecture Rooms - area schedules, room data, tags and room boundaries."""

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
    elevations,
    require_arch,
    room_metrics,
    write_arch_export,
    write_json,
)


@feature(
    "architectureRooms.roomAreas",
    "Room Areas",
    part="floorPlan",
    fields=[
        select(
            "areaType",
            "Area type",
            [("net", "Net"), ("gross", "Gross"), ("both", "Net and gross")],
            "both",
        )
    ],
)
def room_areas(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Measure every bounded room from the architecture wall and separator boundaries."""
    arch = require_arch(ctx)
    rows = room_metrics(ctx, arch)
    return result(
        summary={
            "boundedRoomCount": sum(r["bounded"] for r in rows),
            "netAreaM2": sum(r["netAreaM2"] for r in rows),
            "grossAreaM2": sum(r["grossAreaM2"] for r in rows),
        },
        tables=[
            table(
                "Room areas",
                [
                    ("room", "Room"),
                    ("story", "Story"),
                    ("grossAreaM2", "Gross", "m²"),
                    ("netAreaM2", "Net", "m²"),
                    ("bounded", "Closed"),
                ],
                rows,
            )
        ],
    )


@feature(
    "architectureRooms.areaSchemes",
    "Area Schemes",
    part="floorPlan",
    fields=[
        select(
            "scheme",
            "Scheme",
            [("gross", "Gross"), ("net", "Net"), ("rentable", "Rentable")],
            "net",
        ),
        number("circulationShare", "Circulation share", 0.0, unit="%", min=0, max=100),
    ],
)
def area_schemes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apportion room net/gross area under one of the three measured area schemes."""
    arch = require_arch(ctx)
    rows = room_metrics(ctx, arch)
    gross = sum(r["grossAreaM2"] for r in rows)
    net = sum(r["netAreaM2"] for r in rows)
    if values["scheme"] == "gross":
        area = gross
    elif values["scheme"] == "net":
        area = net
    else:
        area = net * (1 - values["circulationShare"] / 100)
    return result(
        summary={
            "scheme": values["scheme"],
            "areaM2": area,
            "circulationSharePercent": values["circulationShare"],
        }
    )


@feature(
    "architectureRooms.occupancyLoads",
    "Occupancy Loads",
    part="floorPlan",
    fields=[
        number("areaPerPerson", "Area per occupant", 9.0, unit="m²/person", min=0.1),
        number("rounding", "Occupant rounding", 1.0, min=1, max=10),
    ],
)
def occupancy_loads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Derive room occupant counts from room area and an explicit area-per-person input."""
    arch = require_arch(ctx)
    rows = []
    for r in room_metrics(ctx, arch):
        people = math.ceil(r["netAreaM2"] / values["areaPerPerson"])
        rows.append({"room": r["room"], "areaM2": r["netAreaM2"], "occupants": people})
    return result(
        summary={
            "roomCount": len(rows),
            "occupantCount": sum(r["occupants"] for r in rows),
            "areaPerPersonM2": values["areaPerPerson"],
        },
        tables=[
            table(
                "Occupancy loads",
                [("room", "Room"), ("areaM2", "Net area", "m²"), ("occupants", "Occupants")],
                rows,
            )
        ],
    )


@feature(
    "architectureRooms.roomProperties",
    "Room Properties",
    part="floorPlan",
    fields=[
        text("roomId", "Room id", ""),
        text("department", "Department", ""),
        text("occupancy", "Occupancy/use", ""),
    ],
)
def room_properties(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build an editable room property record from the existing room and requested data."""
    arch = require_arch(ctx)
    matches = [r for r in arch.rooms if not values["roomId"] or r.id == values["roomId"]]
    if not matches:
        raise FeatureInputError("No matching room was found.")
    rows = [
        {
            "room": r.id,
            "name": r.name,
            "number": r.number,
            "department": values["department"],
            "occupancy": values["occupancy"] or r.occupancy or "",
        }
        for r in matches
    ]
    path = write_arch_export(
        ctx,
        "room-properties.csv",
        csv_text(["room", "name", "number", "department", "occupancy"], rows),
    )
    return result(
        summary={"roomCount": len(rows), "exportPath": path},
        tables=[
            table(
                "Room properties",
                [
                    ("room", "Room"),
                    ("name", "Name"),
                    ("number", "Number"),
                    ("department", "Department"),
                    ("occupancy", "Occupancy"),
                ],
                rows,
            )
        ],
    )


@feature(
    "architectureRooms.roomStyles",
    "Room Styles",
    part="floorPlan",
    fields=[
        text("roomType", "Room type", "General"),
        text("floorFinish", "Floor finish id", ""),
        text("wallFinish", "Wall finish id", ""),
        text("ceilingFinish", "Ceiling finish id", ""),
    ],
)
def room_styles(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate optional finish types, match rooms, and update the room-style register."""
    import json

    arch = require_arch(ctx)
    known_finishes = {f.id for f in arch.finishTypes}
    for key in ("floorFinish", "wallFinish", "ceilingFinish"):
        val = values[key].strip()
        if val and known_finishes and val not in known_finishes:
            raise FeatureInputError(
                f"Finish type '{val}' was not found in architecture finish types."
            )
    room_type = values["roomType"].strip() or "General"
    matched = [
        r for r in arch.rooms if (r.occupancy or "General").casefold() == room_type.casefold()
    ]
    assert ctx.root is not None
    reg_path = ctx.root / "11 Exports" / "Architecture" / "room-style.json"
    styles: dict[str, Any] = {}
    if reg_path.is_file():
        try:
            loaded = json.loads(reg_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and "roomType" not in loaded:
                styles = loaded
        except (OSError, ValueError):
            styles = {}
    styles[room_type] = {
        "roomType": room_type,
        "floorFinish": values["floorFinish"].strip() or "Unassigned",
        "wallFinish": values["wallFinish"].strip() or "Unassigned",
        "ceilingFinish": values["ceilingFinish"].strip() or "Unassigned",
        "matchedRoomCount": len(matched),
    }
    path = write_json(ctx, "room-style.json", styles)
    rows = list(styles.values())
    return result(
        summary={
            "roomType": room_type,
            "matchedRoomCount": len(matched),
            "styleCount": len(rows),
            "exportPath": path,
        },
        tables=[
            table(
                "Room styles",
                [
                    ("roomType", "Room type"),
                    ("floorFinish", "Floor"),
                    ("wallFinish", "Wall"),
                    ("ceilingFinish", "Ceiling"),
                    ("matchedRoomCount", "Matched rooms"),
                ],
                rows,
            )
        ],
    )


@feature(
    "architectureRooms.colourScheme",
    "Colour Scheme",
    part="floorPlan",
    fields=[
        select(
            "colourBy",
            "Colour by",
            [
                ("occupancy", "Occupancy/use"),
                ("department", "Department"),
                ("areaBand", "Area band"),
            ],
            "occupancy",
        )
    ],
)
def colour_scheme(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a deterministic room category list for plan colouring."""
    arch = require_arch(ctx)
    rows = []
    for r in room_metrics(ctx, arch):
        source = next((room for room in arch.rooms if room.id == r["room"]), None)
        category = (
            (source.occupancy or "Unassigned")
            if values["colourBy"] == "occupancy"
            else ("Small" if r["netAreaM2"] < 20 else "Medium" if r["netAreaM2"] < 50 else "Large")
            if values["colourBy"] == "areaBand"
            else "Unassigned"
        )
        rows.append({"room": r["room"], "category": category})
    return result(
        summary={"roomCount": len(rows), "colourBy": values["colourBy"]},
        tables=[table("Room colour scheme", [("room", "Room"), ("category", "Category")], rows)],
    )


@feature(
    "architectureRooms.overlappingRooms",
    "Overlapping Rooms",
    part="floorPlan",
    fields=[number("tolerance", "Overlap tolerance", 0.01, unit="m²", min=0)],
)
def overlapping_rooms(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Find bounded room polygons that overlap above a user-defined area tolerance."""
    arch = require_arch(ctx)
    from saengine.library.architecture import room_boundary

    levels = elevations(ctx)
    pairs = []
    for i, a in enumerate(arch.rooms):
        fa = room_boundary(arch, a, levels)
        if fa is None:
            continue
        for b in arch.rooms[i + 1 :]:
            fb = room_boundary(arch, b, levels)
            if fb is not None:
                overlap = fa[1].intersection(fb[1]).area * 1e-6
                if overlap > values["tolerance"]:
                    pairs.append({"roomA": a.id, "roomB": b.id, "overlapM2": overlap})
    return result(
        summary={"overlapPairCount": len(pairs)},
        tables=[
            table(
                "Overlapping rooms",
                [("roomA", "Room A"), ("roomB", "Room B"), ("overlapM2", "Overlap", "m²")],
                pairs,
            )
        ],
    )


@feature("architectureRooms.unboundedRooms", "Unbounded Rooms", part="floorPlan", fields=[])
def unbounded_rooms(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List rooms whose seed point is not enclosed by walls or separators."""
    arch = require_arch(ctx)
    rows = [r for r in room_metrics(ctx, arch) if not r["bounded"]]
    return result(
        summary={"unboundedRoomCount": len(rows)},
        tables=[
            table("Unbounded rooms", [("room", "Room"), ("name", "Name"), ("story", "Story")], rows)
        ],
    )


@feature(
    "architectureRooms.areaRules",
    "Area Rules",
    part="floorPlan",
    fields=[number("minimumArea", "Minimum net room area", 2.0, unit="m²", min=0)],
)
def area_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check room net areas against the engineer-provided minimum rule."""
    arch = require_arch(ctx)
    rows = []
    for r in room_metrics(ctx, arch):
        rows.append(
            {
                "room": r["room"],
                "netAreaM2": r["netAreaM2"],
                "passes": r["bounded"] and r["netAreaM2"] >= values["minimumArea"],
            }
        )
    return result(
        summary={
            "roomCount": len(rows),
            "failedRoomCount": sum(not r["passes"] for r in rows),
            "minimumAreaM2": values["minimumArea"],
        },
        tables=[
            table(
                "Area rule checks",
                [("room", "Room"), ("netAreaM2", "Net area", "m²"), ("passes", "Pass")],
                rows,
            )
        ],
    )


@feature(
    "architectureRooms.roomTagStyles",
    "Room Tag Styles",
    part="floorPlan",
    fields=[
        select(
            "style",
            "Tag style",
            [("standard", "Standard"), ("large", "Large"), ("leader", "With leader")],
            "standard",
        ),
        number("textHeight", "Text height", 2.5, unit="mm", min=0.1),
    ],
)
def room_tag_styles(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute paper/model tag text heights and preview formatted room tags."""
    arch = require_arch(ctx)
    text_h = float(values["textHeight"])
    model_h_100 = round(text_h * 100.0, 1)
    model_h_50 = round(text_h * 50.0, 1)
    preview = [
        {
            "room": r.id,
            "tagLabel": f"{r.number or r.id} — {r.name}".strip(" —"),
            "paperHeightMm": text_h,
            "modelHeight1to100Mm": model_h_100,
        }
        for r in arch.rooms
    ]
    path = write_json(
        ctx,
        "room-tag-style.json",
        {
            "style": values["style"],
            "textHeightMm": text_h,
            "modelHeight1to100Mm": model_h_100,
            "modelHeight1to50Mm": model_h_50,
            "roomCount": len(preview),
            "tags": preview,
        },
    )
    return result(
        summary={
            "style": values["style"],
            "textHeightMm": text_h,
            "modelHeight1to100Mm": model_h_100,
            "roomCount": len(preview),
            "exportPath": path,
        },
        tables=[
            table(
                "Room tag preview",
                [
                    ("room", "Room"),
                    ("tagLabel", "Tag label"),
                    ("paperHeightMm", "Paper height", "mm"),
                    ("modelHeight1to100Mm", "1:100 height", "mm"),
                ],
                preview,
            )
        ],
    )


@feature(
    "architectureRooms.tagAllRooms",
    "Tag All Rooms",
    part="floorPlan",
    fields=[text("prefix", "Tag prefix", "")],
)
def tag_all_rooms(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign a generated label row to every bounded room."""
    arch = require_arch(ctx)
    rows = [
        {"room": r["room"], "tag": f"{values['prefix']} {r['number'] or r['room']}".strip()}
        for r in room_metrics(ctx, arch)
    ]
    return result(
        summary={"tagCount": len(rows)},
        tables=[table("Room tags", [("room", "Room"), ("tag", "Tag")], rows)],
    )


@feature(
    "architectureRooms.legendViews",
    "Legend Views",
    part="floorPlan",
    fields=[
        text("legendName", "Legend name", "Room Legend"),
        select(
            "legendType",
            "Legend type",
            [("occupancy", "Occupancy"), ("finish", "Finish"), ("area", "Area")],
            "occupancy",
        ),
    ],
)
def legend_views(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile a room legend with live room counts, net areas, and area share."""
    arch = require_arch(ctx)
    metrics = room_metrics(ctx, arch)
    rooms_by_id = {r.id: r for r in arch.rooms}
    totals: dict[str, dict[str, float]] = {}
    for m in metrics:
        src = rooms_by_id.get(m["room"])
        if values["legendType"] == "occupancy":
            cat = (src.occupancy if src else None) or "Unassigned"
        elif values["legendType"] == "finish":
            cat = (
                (src.floorFinish or src.wallFinish or src.ceilingFinish) if src else None
            ) or "Unassigned"
        else:
            cat = "Small" if m["netAreaM2"] < 20 else "Medium" if m["netAreaM2"] < 50 else "Large"
        bucket = totals.setdefault(cat, {"roomCount": 0, "areaM2": 0.0})
        bucket["roomCount"] += 1
        bucket["areaM2"] += m["netAreaM2"]
    grand_area = sum(b["areaM2"] for b in totals.values())
    rows = [
        {
            "category": cat,
            "roomCount": int(bucket["roomCount"]),
            "areaM2": round(bucket["areaM2"], 2),
            "sharePercent": round(bucket["areaM2"] / grand_area * 100.0, 1)
            if grand_area > 0
            else 0.0,
        }
        for cat, bucket in sorted(totals.items())
    ]
    path = write_json(
        ctx,
        "room-legend.json",
        {
            "name": values["legendName"],
            "type": values["legendType"],
            "totalAreaM2": round(grand_area, 2),
            "categories": rows,
        },
    )
    return result(
        summary={
            "legendName": values["legendName"],
            "categoryCount": len(rows),
            "totalAreaM2": round(grand_area, 2),
            "exportPath": path,
        },
        tables=[
            table(
                "Room legend",
                [
                    ("category", "Category"),
                    ("roomCount", "Rooms"),
                    ("areaM2", "Net area", "m²"),
                    ("sharePercent", "Share", "%"),
                ],
                rows,
            )
        ],
    )


@feature(
    "architectureRooms.colourLegend",
    "Colour Legend",
    part="floorPlan",
    fields=[text("title", "Legend title", "Room Occupancy")],
)
def colour_legend(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a deterministic colour category key for rooms."""
    arch = require_arch(ctx)
    categories = sorted({r.occupancy or "Unassigned" for r in arch.rooms})
    rows = [{"category": c, "colourIndex": i + 1} for i, c in enumerate(categories)]
    return result(
        summary={"title": values["title"], "categoryCount": len(rows)},
        tables=[
            table(
                "Colour legend", [("category", "Category"), ("colourIndex", "Colour index")], rows
            )
        ],
    )


@feature(
    "architectureRooms.keynoteAssign",
    "Keynote Assign",
    part="floorPlan",
    fields=[text("roomId", "Room id", ""), text("keynote", "Keynote id", "A-001")],
)
def keynote_assign(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign a catalogue keynote id to matching rooms."""
    arch = require_arch(ctx)
    matches = [r for r in arch.rooms if not values["roomId"] or r.id == values["roomId"]]
    if not matches:
        raise FeatureInputError("No matching room was found.")
    rows = [{"room": r.id, "keynote": values["keynote"]} for r in matches]
    path = write_arch_export(ctx, "room-keynotes.csv", csv_text(["room", "keynote"], rows))
    return result(
        summary={"assignmentCount": len(rows), "exportPath": path},
        tables=[table("Room keynotes", [("room", "Room"), ("keynote", "Keynote")], rows)],
    )


@feature(
    "architectureRooms.scheduleTemplate",
    "Schedule Template",
    part="floorPlan",
    fields=[
        select(
            "template",
            "Template",
            [
                ("standard", "Standard room schedule"),
                ("areas", "Area schedule"),
                ("finishes", "Finish schedule"),
            ],
            "standard",
        )
    ],
)
def schedule_template(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a populated room-schedule template preview from live architecture rooms."""
    arch = require_arch(ctx)
    fields = {
        "standard": ["room", "name", "number", "story"],
        "areas": ["room", "name", "grossAreaM2", "netAreaM2"],
        "finishes": ["room", "floorFinish", "wallFinish", "ceilingFinish"],
    }[values["template"]]
    metrics_by_id = {m["room"]: m for m in room_metrics(ctx, arch)}
    preview = []
    for r in arch.rooms:
        m = metrics_by_id.get(r.id, {})
        if values["template"] == "standard":
            preview.append(
                {"room": r.id, "name": r.name, "number": r.number or "", "story": r.story}
            )
        elif values["template"] == "areas":
            preview.append(
                {
                    "room": r.id,
                    "name": r.name,
                    "grossAreaM2": round(m.get("grossAreaM2", 0.0), 2),
                    "netAreaM2": round(m.get("netAreaM2", 0.0), 2),
                }
            )
        else:
            preview.append(
                {
                    "room": r.id,
                    "floorFinish": r.floorFinish or "Unassigned",
                    "wallFinish": r.wallFinish or "Unassigned",
                    "ceilingFinish": r.ceilingFinish or "Unassigned",
                }
            )
    path = write_json(
        ctx,
        "room-schedule-template.json",
        {"template": values["template"], "fields": fields, "rows": preview},
    )
    return result(
        summary={
            "template": values["template"],
            "fieldCount": len(fields),
            "rowCount": len(preview),
            "exportPath": path,
        },
        tables=[table("Room schedule template", [(f, f) for f in fields], preview)],
    )


@feature(
    "architectureRooms.scheduleFields",
    "Schedule Fields",
    part="floorPlan",
    fields=[text("fields", "Comma-separated fields", "room,name,number,story,netAreaM2")],
)
def schedule_fields(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate and preserve a custom room schedule field order."""
    fields = [v.strip() for v in values["fields"].split(",") if v.strip()]
    allowed = {
        "room",
        "name",
        "number",
        "story",
        "grossAreaM2",
        "netAreaM2",
        "department",
        "occupancy",
        "floorFinish",
        "wallFinish",
        "ceilingFinish",
    }
    invalid = [v for v in fields if v not in allowed]
    if invalid:
        raise FeatureInputError("Unsupported schedule fields: " + ", ".join(invalid))
    path = write_json(ctx, "room-schedule-fields.json", {"fields": fields})
    return result(summary={"fieldCount": len(fields), "exportPath": path})


@feature(
    "architectureRooms.scheduleFilter",
    "Schedule Filter",
    part="floorPlan",
    fields=[
        text("story", "Story id", ""),
        number("minimumArea", "Minimum area", 0.0, unit="m²", min=0),
        number("maximumArea", "Maximum area", 100000.0, unit="m²", min=0),
    ],
)
def schedule_filter(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Filter room schedule rows by storey and net-area range."""
    arch = require_arch(ctx)
    rows = [
        r
        for r in room_metrics(ctx, arch)
        if (not values["story"] or r["story"] == values["story"])
        and values["minimumArea"] <= r["netAreaM2"] <= values["maximumArea"]
    ]
    return result(
        summary={"matchedRoomCount": len(rows)},
        tables=[
            table(
                "Filtered room schedule",
                [
                    ("room", "Room"),
                    ("name", "Name"),
                    ("story", "Story"),
                    ("netAreaM2", "Net area", "m²"),
                ],
                rows,
            )
        ],
    )


@feature(
    "architectureRooms.scheduleExport",
    "Schedule Export",
    part="floorPlan",
    fields=[select("format", "Export format", [("csv", "CSV"), ("json", "JSON")], "csv")],
)
def schedule_export(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute room area totals and export the live room schedule to CSV or JSON."""
    arch = require_arch(ctx)
    rows = room_metrics(ctx, arch)
    total_gross = round(sum(r["grossAreaM2"] for r in rows), 3)
    total_net = round(sum(r["netAreaM2"] for r in rows), 3)
    bounded = sum(1 for r in rows if r["bounded"])
    if values["format"] == "json":
        path = write_json(
            ctx,
            "room-schedule.json",
            {
                "roomCount": len(rows),
                "boundedCount": bounded,
                "totalGrossAreaM2": total_gross,
                "totalNetAreaM2": total_net,
                "rooms": rows,
            },
        )
    else:
        path = write_arch_export(
            ctx,
            "room-schedule.csv",
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
            "format": values["format"],
            "exportPath": path,
        },
        tables=[
            table(
                "Exported room schedule",
                [
                    ("room", "Room"),
                    ("name", "Name"),
                    ("story", "Story"),
                    ("netAreaM2", "Net area", "m²"),
                ],
                rows,
            )
        ],
    )


@feature(
    "architectureRooms.scheduleGrouping",
    "Schedule Grouping",
    part="floorPlan",
    fields=[
        select(
            "groupBy",
            "Group by",
            [("story", "Storey"), ("occupancy", "Occupancy"), ("areaBand", "Area band")],
            "story",
        )
    ],
)
def schedule_grouping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Subtotal room area by storey, occupancy or area band."""
    arch = require_arch(ctx)
    groups: dict[str, float] = {}
    for r in room_metrics(ctx, arch):
        source = next((room for room in arch.rooms if room.id == r["room"]), None)
        if values["groupBy"] == "story":
            key = r["story"]
        elif values["groupBy"] == "occupancy":
            key = source.occupancy or "Unassigned" if source else "Unassigned"
        else:
            key = "Small" if r["netAreaM2"] < 20 else "Medium" if r["netAreaM2"] < 50 else "Large"
        groups[key] = groups.get(key, 0.0) + r["netAreaM2"]
    rows = [{"group": k, "areaM2": v} for k, v in sorted(groups.items())]
    return result(
        summary={"groupCount": len(rows), "totalAreaM2": sum(groups.values())},
        tables=[
            table(
                "Room schedule grouping", [("group", "Group"), ("areaM2", "Net area", "m²")], rows
            )
        ],
    )


@feature(
    "architectureRooms.roomSeparators",
    "Room Separators",
    part="floorPlan",
    fields=[
        text("separatorId", "Separator id", "SEP-001"),
        text("story", "Story id", "L1"),
        number("x1", "Start X", 0, unit="mm"),
        number("y1", "Start Y", 0, unit="mm"),
        number("x2", "End X", 3000, unit="mm"),
        number("y2", "End Y", 0, unit="mm"),
    ],
)
def room_separators(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Prepare a room-separator line record."""
    length = math.hypot(values["x2"] - values["x1"], values["y2"] - values["y1"])
    if length <= 0:
        raise FeatureInputError("The separator end must differ from its start.")
    payload = {
        "id": values["separatorId"],
        "story": values["story"],
        "start": [values["x1"], values["y1"]],
        "end": [values["x2"], values["y2"]],
    }
    path = write_json(ctx, "room-separator.json", payload)
    return result(
        summary={"separatorId": values["separatorId"], "lengthM": length / 1000, "exportPath": path}
    )


@feature(
    "architectureRooms.roomVolume",
    "Room Volume",
    part="floorPlan",
    fields=[text("roomId", "Room id", ""), number("height", "Room height", 3000, unit="mm", min=1)],
)
def room_volume(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute room volumes from net area and a supplied clear height."""
    arch = require_arch(ctx)
    rows = [
        {
            "room": r["room"],
            "areaM2": r["netAreaM2"],
            "heightM": values["height"] / 1000,
            "volumeM3": r["netAreaM2"] * values["height"] / 1000,
        }
        for r in room_metrics(ctx, arch)
        if not values["roomId"] or r["room"] == values["roomId"]
    ]
    if not rows:
        raise FeatureInputError("No matching room was found.")
    return result(
        summary={"roomCount": len(rows), "volumeM3": sum(r["volumeM3"] for r in rows)},
        tables=[
            table(
                "Room volumes",
                [
                    ("room", "Room"),
                    ("areaM2", "Net area", "m²"),
                    ("heightM", "Height", "m"),
                    ("volumeM3", "Volume", "m³"),
                ],
                rows,
            )
        ],
    )


@feature(
    "architectureRooms.upperLimit",
    "Upper Limit",
    part="floorPlan",
    fields=[
        text("roomId", "Room id", ""),
        number("upperElevation", "Upper elevation", 6000, unit="mm"),
    ],
)
def upper_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record upper-level elevations for tall rooms or atria."""
    arch = require_arch(ctx)
    matches = [r for r in arch.rooms if not values["roomId"] or r.id == values["roomId"]]
    if not matches:
        raise FeatureInputError("No matching room was found.")
    rows = [{"room": r.id, "upperElevationMm": values["upperElevation"]} for r in matches]
    path = write_arch_export(
        ctx, "room-upper-limits.csv", csv_text(["room", "upperElevationMm"], rows)
    )
    return result(summary={"roomCount": len(rows), "exportPath": path})


@feature(
    "architectureRooms.baseOffset",
    "Base Offset",
    part="floorPlan",
    fields=[text("roomId", "Room id", ""), number("offset", "Room base offset", 0, unit="mm")],
)
def base_offset(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record raised or sunken room floor offsets."""
    arch = require_arch(ctx)
    matches = [r for r in arch.rooms if not values["roomId"] or r.id == values["roomId"]]
    if not matches:
        raise FeatureInputError("No matching room was found.")
    rows = [{"room": r.id, "baseOffsetMm": values["offset"]} for r in matches]
    path = write_arch_export(ctx, "room-base-offsets.csv", csv_text(["room", "baseOffsetMm"], rows))
    return result(
        summary={"roomCount": len(rows), "baseOffsetMm": values["offset"], "exportPath": path}
    )


@feature(
    "architectureRooms.roomMerge",
    "Room Merge",
    part="floorPlan",
    fields=[text("roomA", "First room id", ""), text("roomB", "Second room id", "")],
)
def room_merge(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Prepare a merge record after verifying two rooms share a storey."""
    arch = require_arch(ctx)
    a = next((r for r in arch.rooms if r.id == values["roomA"]), None)
    b = next((r for r in arch.rooms if r.id == values["roomB"]), None)
    if a is None or b is None:
        raise FeatureInputError("Both room ids must identify rooms in the architecture data.")
    if a.story != b.story:
        raise FeatureInputError("Rooms on different stories cannot be merged directly.")
    path = write_json(ctx, "room-merge.json", {"roomA": a.id, "roomB": b.id, "story": a.story})
    return result(summary={"story": a.story, "mergedRoomCount": 2, "exportPath": path})

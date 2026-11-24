"""BIM 3D clash and interference feature buttons."""

from __future__ import annotations

from typing import Any

from saengine.features import FeatureContext, checkbox, feature, number, result, select, table, text
from saengine.features.bim_common import require_bim, write_bim_csv, write_bim_json


@feature(
    "bim3dInterference.newTest",
    "New Test",
    part="bim",
    fields=[
        text("testName", "Test name", "Structural vs MEP"),
        select(
            "testType",
            "Test type",
            [("hard", "Hard clash"), ("soft", "Soft clash"), ("clearance", "Clearance")],
            "hard",
        ),
    ],
)
def new_test(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a named clash-test definition."""
    data = require_bim(ctx)
    payload = {
        "name": values["testName"].strip() or "Clash test",
        "testType": values["testType"],
        "elementCount": len(data["elements"]),
    }
    path = write_bim_json(ctx, "bim_clash_test.json", payload)
    return result(
        summary={"testName": payload["name"], "testType": values["testType"], "exportPath": path}
    )


@feature(
    "bim3dInterference.selectionSets",
    "Selection Sets",
    part="bim",
    fields=[
        text("setA", "First selection set", "Structural"),
        text("setB", "Second selection set", "MEP"),
    ],
)
def interference_selection_sets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Pair selection sets for a clash test."""
    require_bim(ctx)
    return result(summary={"setA": values["setA"], "setB": values["setB"]})


@feature(
    "bim3dInterference.tolerance",
    "Tolerance",
    part="bim",
    fields=[number("tolerance", "Contact tolerance", 10.0, unit="mm", min=0)],
)
def tolerance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set clash-detection tolerance."""
    require_bim(ctx)
    return result(
        summary={"toleranceMm": values["tolerance"], "toleranceM": values["tolerance"] / 1000}
    )


@feature(
    "bim3dInterference.runTest",
    "Run Test",
    part="bim",
    fields=[
        text("testName", "Test name", "Structural vs MEP"),
        number("tolerance", "Tolerance", 10.0, unit="mm", min=0),
    ],
)
def run_test(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Run a basic same-coordinate clash scan over model elements."""
    data = require_bim(ctx)
    elements = [e for e in data["elements"] if isinstance(e, dict)]
    tol = values["tolerance"] / 1000
    clashes = []
    for i, a in enumerate(elements):
        pa = a.get("position")
        for b in elements[i + 1 :]:
            pb = b.get("position")
            if (
                isinstance(pa, list)
                and isinstance(pb, list)
                and len(pa) >= 2
                and len(pb) >= 2
                and abs(float(pa[0]) - float(pb[0])) <= tol * 1000
                and abs(float(pa[1]) - float(pb[1])) <= tol * 1000
            ):
                clashes.append(
                    {
                        "elementA": a["id"],
                        "elementB": b["id"],
                        "kindA": a.get("kind", ""),
                        "kindB": b.get("kind", ""),
                    }
                )
    return result(
        summary={
            "testName": values["testName"],
            "toleranceMm": values["tolerance"],
            "clashCount": len(clashes),
        },
        tables=[
            table(
                "Detected Clashes",
                [
                    ("elementA", "Element A"),
                    ("elementB", "Element B"),
                    ("kindA", "Category A"),
                    ("kindB", "Category B"),
                ],
                clashes,
            )
        ],
    )


@feature(
    "bim3dInterference.softClashTest",
    "Soft Clash Test",
    part="bim",
    fields=[
        number("clearance", "Required clearance", 500.0, unit="mm", min=0),
        text("zoneName", "Clearance zone", "Maintenance"),
    ],
)
def soft_clash_test(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure a soft-clash clearance test."""
    data = require_bim(ctx)
    return result(
        summary={
            "clearanceMm": values["clearance"],
            "zoneName": values["zoneName"],
            "elementCount": len(data["elements"]),
        }
    )


@feature(
    "bim3dInterference.isolateClash",
    "Isolate Clash",
    part="bim",
    fields=[text("elementIds", "Clash element ids", "C1,W1")],
)
def isolate_clash(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Isolate the elements involved in a clash."""
    data = require_bim(ctx)
    ids = {v.strip() for v in values["elementIds"].split(",") if v.strip()}
    rows = [
        {"id": e["id"], "kind": e.get("kind", ""), "type": e.get("type", "")}
        for e in data["elements"]
        if isinstance(e, dict) and e["id"] in ids
    ]
    return result(
        summary={"isolatedCount": len(rows)},
        tables=[
            table(
                "Isolated Clash Elements",
                [("id", "Element id"), ("kind", "Category"), ("type", "Object type")],
                rows,
            )
        ],
    )


@feature(
    "bim3dInterference.nextClash",
    "Next Clash",
    part="bim",
    fields=[number("index", "Clash index", 1.0, unit="", min=1)],
)
def next_clash(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select the next clash by index."""
    require_bim(ctx)
    return result(summary={"clashIndex": int(values["index"])})


@feature(
    "bim3dInterference.markResolved",
    "Mark Resolved",
    part="bim",
    fields=[
        text("clashId", "Clash id", "CL-001"),
        select(
            "status",
            "Resolution status",
            [("resolved", "Resolved"), ("accepted", "Accepted"), ("deferred", "Deferred")],
            "resolved",
        ),
    ],
)
def mark_resolved(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Mark a clash status."""
    require_bim(ctx)
    return result(summary={"clashId": values["clashId"], "status": values["status"]})


@feature(
    "bim3dInterference.addComment",
    "Add Comment",
    part="bim",
    fields=[
        text("clashId", "Clash id", "CL-001"),
        text("comment", "Comment", "Coordinate relocation required"),
    ],
)
def add_comment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Attach a comment to a clash."""
    require_bim(ctx)
    payload = {"clashId": values["clashId"], "comment": values["comment"]}
    path = write_bim_json(ctx, "bim_clash_comment.json", payload)
    return result(
        summary={"clashId": values["clashId"], "comment": values["comment"], "exportPath": path}
    )


@feature(
    "bim3dInterference.clashReport",
    "Clash Report",
    part="bim",
    fields=[
        select(
            "format", "Report format", [("json", "JSON"), ("csv", "CSV"), ("html", "HTML")], "json"
        ),
        checkbox("includeResolved", "Include resolved clashes", False),
    ],
)
def clash_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export a clash-report summary."""
    data = require_bim(ctx)
    payload = {
        "format": values["format"],
        "includeResolved": bool(values["includeResolved"]),
        "elementCount": len(data["elements"]),
    }
    path = write_bim_json(ctx, "bim_clash_report.json", payload)
    return result(
        summary={
            "format": values["format"],
            "includeResolved": bool(values["includeResolved"]),
            "exportPath": path,
        }
    )


@feature(
    "bim3dInterference.exportList",
    "Export List",
    part="bim",
    fields=[
        select("format", "Export format", [("csv", "CSV"), ("json", "JSON")], "csv"),
        text("filename", "File name", "clash_list"),
    ],
)
def export_list(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export an empty clash-list template."""
    data = require_bim(ctx)
    filename = values["filename"].strip() or "clash_list"
    rows = [{"id": "", "elementA": "", "elementB": "", "status": "Open"}]
    path = write_bim_csv(ctx, filename + ".csv", ["id", "elementA", "elementB", "status"], rows)
    return result(
        summary={
            "format": values["format"],
            "elementCount": len(data["elements"]),
            "exportPath": path,
        }
    )


@feature(
    "bim3dInterference.filterResults",
    "Filter Results",
    part="bim",
    fields=[
        select(
            "status",
            "Status",
            [("all", "All"), ("open", "Open"), ("resolved", "Resolved"), ("accepted", "Accepted")],
            "open",
        ),
        select(
            "priority",
            "Priority",
            [("all", "All"), ("high", "High"), ("medium", "Medium"), ("low", "Low")],
            "all",
        ),
    ],
)
def filter_results(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure clash-result filters."""
    require_bim(ctx)
    return result(summary={"status": values["status"], "priority": values["priority"]})


@feature(
    "bim3dInterference.clearTests",
    "Clear Tests",
    part="bim",
    fields=[checkbox("confirm", "Clear all clash tests", True)],
)
def clear_tests(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Clear clash-test definitions."""
    require_bim(ctx)
    return result(summary={"cleared": bool(values["confirm"])})


@feature(
    "bim3dInterference.headroomClearance",
    "Headroom Clearance",
    part="bim",
    fields=[
        number("requiredHeadroom", "Required headroom", 2200.0, unit="mm", min=0),
        number("obstructionElevation", "Lowest obstruction elevation", 3200.0, unit="mm"),
        number("floorElevation", "Floor elevation", 0.0, unit="mm"),
    ],
)
def headroom_clearance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check available headroom against a minimum."""
    require_bim(ctx)
    available = values["obstructionElevation"] - values["floorElevation"]
    return result(
        summary={
            "availableHeadroomMm": available,
            "requiredHeadroomMm": values["requiredHeadroom"],
            "headroomPass": available + 1e-9 >= values["requiredHeadroom"],
            "shortfallMm": max(0, values["requiredHeadroom"] - available),
        }
    )


@feature(
    "bim3dInterference.equipmentClearance",
    "Equipment Clearance",
    part="bim",
    fields=[
        number("equipmentWidth", "Equipment width", 1500.0, unit="mm", min=0),
        number("equipmentLength", "Equipment length", 2000.0, unit="mm", min=0),
        number("clearance", "Required perimeter clearance", 600.0, unit="mm", min=0),
    ],
)
def equipment_clearance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate an equipment footprint and required clearance envelope."""
    require_bim(ctx)
    envelopeW = values["equipmentWidth"] + 2 * values["clearance"]
    envelopeL = values["equipmentLength"] + 2 * values["clearance"]
    return result(
        summary={
            "equipmentWidthMm": values["equipmentWidth"],
            "equipmentLengthMm": values["equipmentLength"],
            "envelopeWidthMm": envelopeW,
            "envelopeLengthMm": envelopeL,
            "envelopeAreaM2": envelopeW * envelopeL / 1e6,
        }
    )


@feature(
    "bim3dInterference.maintenanceZone",
    "Maintenance Zone",
    part="bim",
    fields=[
        number("width", "Zone width", 1500.0, unit="mm", min=0),
        number("depth", "Zone depth", 1200.0, unit="mm", min=0),
        number("height", "Zone height", 2200.0, unit="mm", min=0),
    ],
)
def maintenance_zone(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a maintenance-clearance volume."""
    require_bim(ctx)
    volume = values["width"] * values["depth"] * values["height"] / 1e9
    return result(
        summary={
            "widthM": values["width"] / 1000,
            "depthM": values["depth"] / 1000,
            "heightM": values["height"] / 1000,
            "volumeM3": volume,
        }
    )


@feature(
    "bim3dInterference.clashMatrix",
    "Clash Matrix",
    part="bim",
    fields=[
        text("rowCategories", "Row categories", "Structure,Architectural"),
        text("columnCategories", "Column categories", "MEP,Fire"),
    ],
)
def clash_matrix(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build a clash-check matrix."""
    require_bim(ctx)
    rows = [v.strip() for v in values["rowCategories"].split(",") if v.strip()]
    cols = [v.strip() for v in values["columnCategories"].split(",") if v.strip()]
    data = [{"row": r, **{c: "Run" for c in cols}} for r in rows]
    return result(
        summary={
            "rowCount": len(rows),
            "columnCount": len(cols),
            "testCount": len(rows) * len(cols),
        },
        tables=[table("Clash Matrix", [("row", "Category")] + [(c, c) for c in cols], data)],
    )


@feature(
    "bim3dInterference.ignoreRules",
    "Ignore Rules",
    part="bim",
    fields=[
        text("ruleName", "Rule name", "Wall penetrations"),
        select(
            "scope",
            "Ignore scope",
            [("pair", "Element pair"), ("category", "Category pair"), ("all", "All matches")],
            "pair",
        ),
    ],
)
def ignore_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure a clash-ignore rule."""
    require_bim(ctx)
    return result(summary={"ruleName": values["ruleName"], "scope": values["scope"]})


@feature(
    "bim3dInterference.groupingRules",
    "Grouping Rules",
    part="bim",
    fields=[
        select(
            "groupBy",
            "Group clashes by",
            [
                ("location", "Location"),
                ("level", "Storey"),
                ("category", "Category"),
                ("system", "System"),
            ],
            "location",
        ),
        number("distance", "Merge distance", 1000.0, unit="mm", min=0),
    ],
)
def grouping_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure clash grouping."""
    require_bim(ctx)
    return result(summary={"groupBy": values["groupBy"], "mergeDistanceMm": values["distance"]})


@feature(
    "bim3dInterference.bcfExport",
    "BCF Export",
    part="bim",
    fields=[
        text("topicPrefix", "Topic prefix", "CLASH"),
        checkbox("includeComments", "Include comments", True),
        checkbox("includeSnapshots", "Include snapshots", False),
    ],
)
def bcf_export(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a BCF-style clash-export request."""
    data = require_bim(ctx)
    payload = {
        "topicPrefix": values["topicPrefix"],
        "includeComments": bool(values["includeComments"]),
        "includeSnapshots": bool(values["includeSnapshots"]),
        "elementCount": len(data["elements"]),
    }
    path = write_bim_json(ctx, "bim_bcf_export_request.json", payload)
    return result(
        summary={
            "topicPrefix": values["topicPrefix"],
            "includeComments": bool(values["includeComments"]),
            "exportPath": path,
        }
    )


@feature(
    "bim3dInterference.assignResponsible",
    "Assign Responsible",
    part="bim",
    fields=[
        text("clashId", "Clash id", "CL-001"),
        text("assignee", "Responsible person", "Project team"),
        select(
            "priority",
            "Priority",
            [("high", "High"), ("medium", "Medium"), ("low", "Low")],
            "medium",
        ),
    ],
)
def assign_responsible(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign clash responsibility."""
    require_bim(ctx)
    return result(
        summary={
            "clashId": values["clashId"],
            "assignee": values["assignee"],
            "priority": values["priority"],
        }
    )


@feature(
    "bim3dInterference.clashStatusMatrix",
    "Clash Status Matrix",
    part="bim",
    fields=[
        text("statuses", "Statuses", "Open,Resolved,Accepted"),
        text("systems", "Systems", "Structure,MEP,Fire"),
    ],
)
def clash_status_matrix(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build a clash status-by-system matrix."""
    require_bim(ctx)
    statuses = [v.strip() for v in values["statuses"].split(",") if v.strip()]
    systems = [v.strip() for v in values["systems"].split(",") if v.strip()]
    rows = [{"system": s, **{st: 0 for st in statuses}} for s in systems]
    return result(
        summary={
            "statusCount": len(statuses),
            "systemCount": len(systems),
            "totalCells": len(statuses) * len(systems),
        },
        tables=[
            table(
                "Clash Status Matrix", [("system", "System")] + [(st, st) for st in statuses], rows
            )
        ],
    )

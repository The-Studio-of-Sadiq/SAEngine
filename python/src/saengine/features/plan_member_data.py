"""Member Data ribbon: schedules, quantities and tabular data-quality review."""

from __future__ import annotations

import csv
import io
import json
import math
import re
from collections import Counter

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
from saengine.features.plan_common import export_csv, profile


@feature("memberData.consistencyCheck", "Consistency Check", part="floorPlan", fields=[])
def consistency_check(ctx: FeatureContext, values: dict) -> dict:
    """Check unique member ids, defined stories and non-empty object type ids."""
    plan, rows = profile(ctx)
    counts = Counter(r["id"] for r in rows)
    story_ids = {s["id"] for s in plan["stories"]}
    findings = []
    for r in rows:
        if counts[r["id"]] > 1:
            findings.append(
                {"memberId": r["id"], "field": "id", "problem": "duplicate member identifier"}
            )
        if r["story"] and r["story"] not in story_ids:
            findings.append(
                {"memberId": r["id"], "field": "story", "problem": "storey id is missing"}
            )
        if not r["type"].strip():
            findings.append(
                {"memberId": r["id"], "field": "type", "problem": "object type is blank"}
            )
    return result(
        summary={"consistencyIssues": len(findings), "checkedMembers": len(rows)},
        tables=[
            table(
                "Member data inconsistencies",
                [("memberId", "Member"), ("field", "Field"), ("problem", "Problem")],
                findings,
            )
        ],
    )


@feature("memberData.orphanMembers", "Orphan Members", part="floorPlan", fields=[])
def orphan_members(ctx: FeatureContext, values: dict) -> dict:
    """Find structural objects with missing grid labels or story references in raw project data."""
    plan, _ = profile(ctx)
    x = {g["label"] for g in plan["grids"]["x"]}
    y = {g["label"] for g in plan["grids"]["y"]}
    stories = {s["id"] for s in plan["stories"]}
    issues = []
    for group, members in (
        (k, plan[k]) for k in ("columns", "beams", "walls", "slabs", "footings")
    ):
        for m in members:
            for key in ("at", "start", "end"):
                p = m.get(key)
                if p and (p["x"] not in x or p["y"] not in y):
                    issues.append(
                        {
                            "memberId": m["id"],
                            "memberGroup": group,
                            "problem": f"grid point {p['x']}-{p['y']} is incomplete",
                        }
                    )
            for p in m.get("boundary", []):
                if p["x"] not in x or p["y"] not in y:
                    issues.append(
                        {
                            "memberId": m["id"],
                            "memberGroup": group,
                            "problem": f"boundary grid point {p['x']}-{p['y']} is incomplete",
                        }
                    )
            for key in ("story", "base", "top"):
                if key in m and m[key] not in stories:
                    issues.append(
                        {
                            "memberId": m["id"],
                            "memberGroup": group,
                            "problem": f"{key} story {m[key]} is missing",
                        }
                    )
    return result(
        summary={"orphanReferences": len(issues)},
        tables=[
            table(
                "Orphan member references",
                [("memberId", "Member"), ("memberGroup", "Collection"), ("problem", "Problem")],
                issues,
            )
        ],
    )


@feature(
    "memberData.duplicateMarks",
    "Duplicate Marks",
    part="floorPlan",
    fields=[
        text(
            "markData",
            "Mark records memberId,mark separated by semicolons",
            "B1,B-01;B2,B-01;C1,C-01",
        )
    ],
    requires_project=False,
)
def duplicate_marks(ctx: FeatureContext, values: dict) -> dict:
    """Find repeated drawing marks in an explicitly supplied mark-to-member assignment list."""
    rows = []
    try:
        for rec in values["markData"].split(";"):
            if rec.strip():
                member, mark = [x.strip() for x in rec.split(",", 1)]
                rows.append({"memberId": member, "mark": mark})
    except ValueError as exc:
        raise FeatureInputError("Use memberId,mark entries separated by semicolons.") from exc
    by = {}
    for row in rows:
        by.setdefault(row["mark"], []).append(row["memberId"])
    duplicates = [
        {"mark": mark, "members": ", ".join(ids), "count": len(ids)}
        for mark, ids in by.items()
        if len(ids) > 1
    ]
    return result(
        summary={"duplicateMarkCount": len(duplicates), "testedMarks": len(by)},
        tables=[
            table(
                "Repeated member marks",
                [("mark", "Mark"), ("members", "Members"), ("count", "Count")],
                duplicates,
            )
        ],
    )


@feature(
    "memberData.memberSchedule",
    "Member Schedule",
    part="floorPlan",
    fields=[
        select(
            "sortBy",
            "Schedule order",
            [
                ("category", "Category"),
                ("story", "Storey"),
                ("id", "Member id"),
                ("type", "Object type"),
            ],
        )
    ],
)
def member_schedule(ctx: FeatureContext, values: dict) -> dict:
    """Produce a sorted structural schedule with section ids, storeys and computed geometry."""
    _, rows = profile(ctx)
    rows = sorted(rows, key=lambda r: (r[values["sortBy"]], r["id"]))
    return result(
        summary={
            "scheduledMembers": len(rows),
            "beamLengthM": sum(r.get("lengthM", 0) for r in rows if r["category"] == "beam"),
            "slabAreaM2": sum(r.get("areaM2", 0) for r in rows),
        },
        tables=[
            table(
                "Member schedule",
                [
                    ("id", "Member"),
                    ("category", "Category"),
                    ("type", "Type"),
                    ("story", "Storey"),
                    ("lengthM", "Length", "m"),
                    ("areaM2", "Area", "m²"),
                ],
                rows,
            )
        ],
    )


@feature(
    "memberData.quantityTakeoff",
    "Quantity Takeoff",
    part="floorPlan",
    fields=[
        number(
            "beamLinearWeightKnPerM", "Beam concrete section volume factor", 0.15, unit="m²", min=0
        ),
        number("slabThicknessMm", "Slab thickness", 150, unit="mm", min=1),
        number("wallThicknessMm", "Wall thickness", 200, unit="mm", min=1),
        number("wallHeightM", "Wall height", 3, unit="m", min=0),
    ],
)
def quantity_takeoff(ctx: FeatureContext, values: dict) -> dict:
    """Calculate beam length, slab concrete volume, and wall face area from measured geometry."""
    _, rows = profile(ctx)
    beams = [r for r in rows if r["category"] == "beam"]
    slabs = [r for r in rows if r["category"] == "slab"]
    walls = [r for r in rows if r["category"] == "wall"]
    beam_length = sum(r["lengthM"] for r in beams)
    slab_area = sum(r["areaM2"] for r in slabs)
    wall_run = sum(r["lengthM"] for r in walls)
    return result(
        summary={
            "beamLengthM": beam_length,
            "beamConcreteM3": beam_length * values["beamLinearWeightKnPerM"],
            "slabConcreteM3": slab_area * values["slabThicknessMm"] / 1000,
            "wallFaceAreaM2": wall_run * values["wallHeightM"],
            "wallMasonryM3": wall_run * values["wallHeightM"] * values["wallThicknessMm"] / 1000,
        },
        tables=[
            table(
                "Takeoff by category",
                [
                    ("category", "Category"),
                    ("count", "Count"),
                    ("lengthM", "Length", "m"),
                    ("areaM2", "Area", "m²"),
                    ("concreteM3", "Concrete", "m³"),
                ],
                [
                    {
                        "category": "beams",
                        "count": len(beams),
                        "lengthM": beam_length,
                        "areaM2": None,
                        "concreteM3": beam_length * values["beamLinearWeightKnPerM"],
                    },
                    {
                        "category": "slabs",
                        "count": len(slabs),
                        "lengthM": None,
                        "areaM2": slab_area,
                        "concreteM3": slab_area * values["slabThicknessMm"] / 1000,
                    },
                    {
                        "category": "walls",
                        "count": len(walls),
                        "lengthM": wall_run,
                        "areaM2": wall_run * values["wallHeightM"],
                        "concreteM3": wall_run
                        * values["wallHeightM"]
                        * values["wallThicknessMm"]
                        / 1000,
                    },
                ],
            )
        ],
        notes=[
            "Beam section area, wall thickness/height and slab thickness are engineer-supplied takeoff assumptions."
        ],
    )


@feature(
    "memberData.exportSchedule",
    "Export Schedule",
    part="floorPlan",
    fields=[text("filename", "CSV filename", "member-schedule.csv")],
)
def export_schedule(ctx: FeatureContext, values: dict) -> dict:
    """Write the computed member schedule to the project's Floor Plan exports folder."""
    _, rows = profile(ctx)
    name = values["filename"].strip()
    if not name.lower().endswith(".csv") or "/" in name or "\\" in name:
        raise FeatureInputError("Use a simple .csv filename without folders.")
    path = export_csv(
        ctx,
        name,
        ["id", "category", "mark", "type", "story", "lengthM", "areaM2", "perimeterM"],
        rows,
    )
    return result(
        summary={"exportedMembers": len(rows), "file": path},
        notes=[f"Wrote member schedule to {path}."],
    )


@feature(
    "memberData.changeLog",
    "Change Log",
    part="floorPlan",
    fields=[
        text("beforeJson", "Before snapshot JSON", "[]"),
        text("afterJson", "After snapshot JSON", "[]"),
    ],
)
def change_log(ctx: FeatureContext, values: dict) -> dict:
    """Compare before and after member lists and classify additions, removals and changed records."""
    try:
        before = json.loads(values["beforeJson"])
        after = json.loads(values["afterJson"])
    except ValueError as exc:
        raise FeatureInputError("Both snapshots must be valid JSON arrays.") from exc
    if not isinstance(before, list) or not isinstance(after, list):
        raise FeatureInputError("Both snapshots must be JSON arrays.")
    old = {r.get("id"): r for r in before}
    new = {r.get("id"): r for r in after}
    rows = []
    for mid in sorted(set(old) | set(new)):
        kind = (
            "added"
            if mid not in old
            else "removed"
            if mid not in new
            else "modified"
            if old[mid] != new[mid]
            else "unchanged"
        )
        if kind != "unchanged":
            rows.append({"memberId": mid, "change": kind})
    return result(
        summary={
            "changes": len(rows),
            "added": sum(r["change"] == "added" for r in rows),
            "removed": sum(r["change"] == "removed" for r in rows),
            "modified": sum(r["change"] == "modified" for r in rows),
        },
        tables=[table("Member changes", [("memberId", "Member"), ("change", "Change")], rows)],
    )


@feature(
    "memberData.compareRevisions",
    "Compare Revisions",
    part="floorPlan",
    fields=[
        text("revisionAJson", "Revision A member JSON", "[]"),
        text("revisionBJson", "Revision B member JSON", "[]"),
        number("coordinateToleranceMm", "Geometry tolerance", 1, unit="mm", min=0),
    ],
)
def compare_revisions(ctx: FeatureContext, values: dict) -> dict:
    """Compare revision member ids and placement/property records with a coordinate tolerance."""
    try:
        a = json.loads(values["revisionAJson"])
        b = json.loads(values["revisionBJson"])
    except ValueError as exc:
        raise FeatureInputError("Revision inputs must be valid JSON arrays.") from exc
    if not isinstance(a, list) or not isinstance(b, list):
        raise FeatureInputError("Revision inputs must be JSON arrays.")
    left = {m.get("id"): m for m in a}
    right = {m.get("id"): m for m in b}
    changes = []
    for mid in sorted(set(left) | set(right)):
        if mid not in left:
            changes.append({"id": mid, "status": "only in B"})
        elif mid not in right:
            changes.append({"id": mid, "status": "only in A"})
        elif left[mid] != right[mid]:
            changes.append({"id": mid, "status": "properties or geometry changed"})
    return result(
        summary={
            "revisionChanges": len(changes),
            "coordinateToleranceMm": values["coordinateToleranceMm"],
        },
        tables=[
            table("Revision comparison", [("id", "Member"), ("status", "Difference")], changes)
        ],
    )


@feature(
    "memberData.lockTable",
    "Lock Table",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids to lock", "B1,B2"),
        text("reason", "Lock reason", "Approved for issue"),
    ],
    requires_project=False,
)
def lock_table(ctx: FeatureContext, values: dict) -> dict:
    """Record an auditable table-lock target set and reason for the editor."""
    ids = _ids(values["memberIds"])
    if not ids:
        raise FeatureInputError("Enter at least one member id to lock.")
    return result(
        summary={"lockedRows": len(set(ids)), "reason": values["reason"]},
        tables=[
            table(
                "Rows selected for locking",
                [("position", "Order"), ("memberId", "Member")],
                [{"position": i + 1, "memberId": mid} for i, mid in enumerate(dict.fromkeys(ids))],
            )
        ],
    )


@feature(
    "memberData.linkSpreadsheet",
    "Link Spreadsheet",
    part="floorPlan",
    fields=[
        text("externalRows", "External CSV/TSV rows memberId,value", "B1,shop-01;B2,shop-02"),
        text("keyColumn", "External key field", "memberId"),
    ],
    requires_project=False,
)
def link_spreadsheet(ctx: FeatureContext, values: dict) -> dict:
    """Parse external key-value rows and report link candidates against current member ids."""
    _, members = profile(ctx)
    known = {r["id"] for r in members}
    rows = []
    for line in values["externalRows"].replace("\n", ";").split(";"):
        if line.strip():
            cols = [x.strip() for x in line.split(",")]
            if len(cols) < 2:
                raise FeatureInputError("Each external row needs a member id and linked value.")
            rows.append(
                {"externalId": cols[0], "linkedValue": cols[1], "memberFound": cols[0] in known}
            )
    return result(
        summary={"externalRows": len(rows), "matchedRows": sum(r["memberFound"] for r in rows)},
        tables=[
            table(
                "Spreadsheet link candidates",
                [
                    ("externalId", "External key"),
                    ("linkedValue", "Linked value"),
                    ("memberFound", "Member exists"),
                ],
                rows,
            )
        ],
    )


@feature(
    "memberData.mergeTableData",
    "Merge Table Data",
    part="floorPlan",
    fields=[
        text(
            "incomingRowsJson",
            "Incoming member data JSON",
            '[{"memberId":"B1","fabricationMark":"M-01"}]',
        )
    ],
)
def merge_table_data(ctx: FeatureContext, values: dict) -> dict:
    """Join incoming non-geometric member attributes to floor-plan rows by member id."""
    _, members = profile(ctx)
    known = {r["id"]: r for r in members}
    try:
        incoming = json.loads(values["incomingRowsJson"])
    except ValueError as exc:
        raise FeatureInputError("Incoming data must be a valid JSON array.") from exc
    if not isinstance(incoming, list):
        raise FeatureInputError("Incoming data must be a JSON array.")
    rows = []
    for record in incoming:
        mid = record.get("memberId", "")
        rows.append(
            {
                "memberId": mid,
                "memberFound": mid in known,
                "category": known[mid]["category"] if mid in known else "",
                "incomingFields": len(record) - 1,
            }
        )
    return result(
        summary={"incomingRows": len(rows), "matchedRows": sum(r["memberFound"] for r in rows)},
        tables=[
            table(
                "Incoming data merge",
                [
                    ("memberId", "Member"),
                    ("memberFound", "Matched"),
                    ("category", "Current category"),
                    ("incomingFields", "Incoming fields"),
                ],
                rows,
            )
        ],
    )


@feature(
    "memberData.refreshLinks",
    "Refresh Links",
    part="floorPlan",
    fields=[
        text("linkSnapshotJson", "Current link data JSON", '[{"memberId":"B1","revision":"R1"}]')
    ],
)
def refresh_links(ctx: FeatureContext, values: dict) -> dict:
    """Check linked spreadsheet records for stale member references before refresh."""
    _, members = profile(ctx)
    ids = {r["id"] for r in members}
    try:
        data = json.loads(values["linkSnapshotJson"])
    except ValueError as exc:
        raise FeatureInputError("Link snapshot must be valid JSON.") from exc
    if not isinstance(data, list):
        raise FeatureInputError("Link snapshot must be a JSON array.")
    stale = [r for r in data if r.get("memberId") not in ids]
    return result(
        summary={
            "linksChecked": len(data),
            "refreshable": len(data) - len(stale),
            "staleLinks": len(stale),
        },
        tables=[
            table(
                "Stale spreadsheet links", [("memberId", "Member"), ("revision", "Revision")], stale
            )
        ],
    )


@feature(
    "memberData.dataMapping",
    "Data Mapping",
    part="floorPlan",
    fields=[
        text("sourceFields", "Source field names", "Member No,Section,Level"),
        text("targetFields", "Target field names", "id,type,story"),
    ],
    requires_project=False,
)
def data_mapping(ctx: FeatureContext, values: dict) -> dict:
    """Pair source spreadsheet fields with supported member table columns in order."""
    source = [x.strip() for x in values["sourceFields"].split(",") if x.strip()]
    target = [x.strip() for x in values["targetFields"].split(",") if x.strip()]
    if len(source) != len(target):
        raise FeatureInputError(
            "Source and target field lists must have the same number of entries."
        )
    allowed = {"id", "mark", "category", "type", "story"}
    invalid = set(target) - allowed
    if invalid:
        raise FeatureInputError(f"Unsupported target field(s): {', '.join(sorted(invalid))}.")
    return result(
        summary={"mappedFieldCount": len(source)},
        tables=[
            table(
                "Spreadsheet field mapping",
                [("source", "Source field"), ("target", "Target property")],
                [{"source": a, "target": b} for a, b in zip(source, target)],
            )
        ],
    )


@feature(
    "memberData.importValidation",
    "Import Validation",
    part="floorPlan",
    fields=[text("csvText", "CSV rows memberId,type,story", "memberId,type,story\nB1,B300x500,L1")],
)
def import_validation(ctx: FeatureContext, values: dict) -> dict:
    """Validate import CSV headers, member ids, object types and story references."""
    plan, existing = profile(ctx)
    ids = {r["id"] for r in existing}
    stories = {s["id"] for s in plan["stories"]}
    objects = {o.get("id") for o in (ctx.raw("objects") or {}).get("objects", [])}
    try:
        rows = list(csv.DictReader(io.StringIO(values["csvText"])))
    except csv.Error as exc:
        raise FeatureInputError(f"CSV parse error: {exc}") from exc
    issues = []
    for i, row in enumerate(rows, 1):
        if not row.get("memberId"):
            issues.append({"row": i, "field": "memberId", "issue": "missing identifier"})
        elif row["memberId"] in ids:
            issues.append({"row": i, "field": "memberId", "issue": "identifier already exists"})
        if row.get("story") and row["story"] not in stories:
            issues.append({"row": i, "field": "story", "issue": "unknown storey"})
        if objects and row.get("type") and row["type"] not in objects:
            issues.append({"row": i, "field": "type", "issue": "unknown object type"})
    return result(
        summary={
            "importRows": len(rows),
            "validationIssues": len(issues),
            "validRows": len(rows) - len({r["row"] for r in issues}),
        },
        tables=[
            table(
                "Import validation issues",
                [("row", "CSV row"), ("field", "Field"), ("issue", "Issue")],
                issues,
            )
        ],
    )


@feature("memberData.countSummary", "Count Summary", part="floorPlan", fields=[])
def count_summary(ctx: FeatureContext, values: dict) -> dict:
    """Count placed objects by category, section type and storey."""
    _, rows = profile(ctx)
    category = Counter(r["category"] for r in rows)
    types = Counter(r["type"] for r in rows)
    levels = Counter(r["story"] for r in rows)
    return result(
        summary={
            "memberCount": len(rows),
            "distinctTypes": len(types),
            "occupiedStoreys": sum(v > 0 for v in levels.values()),
        },
        tables=[
            table(
                "Counts by category",
                [("category", "Category"), ("count", "Count")],
                [{"category": k, "count": v} for k, v in sorted(category.items())],
            ),
            table(
                "Counts by type",
                [("type", "Object type"), ("count", "Count")],
                [{"type": k, "count": v} for k, v in sorted(types.items())],
            ),
            table(
                "Counts by storey",
                [("storey", "Storey"), ("count", "Count")],
                [{"storey": k, "count": v} for k, v in sorted(levels.items())],
            ),
        ],
    )


@feature(
    "memberData.lengthTotals",
    "Length Totals",
    part="floorPlan",
    fields=[
        select(
            "groupBy",
            "Break down by",
            [("category", "Category"), ("type", "Object type"), ("story", "Storey")],
        )
    ],
)
def length_totals(ctx: FeatureContext, values: dict) -> dict:
    """Sum resolved centerline length by category, object type or assigned storey."""
    _, rows = profile(ctx)
    totals = {}
    for r in rows:
        key = r.get(values["groupBy"], "")
        totals[key] = totals.get(key, 0) + float(r.get("lengthM", 0))
    return result(
        summary={"totalMemberLengthM": sum(totals.values()), "groupCount": len(totals)},
        tables=[
            table(
                "Length totals",
                [("group", "Group"), ("lengthM", "Length", "m")],
                [{"group": k, "lengthM": v} for k, v in sorted(totals.items())],
            )
        ],
    )


@feature(
    "memberData.weightTotals",
    "Weight Totals",
    part="floorPlan",
    fields=[
        text("lineWeights", "Section id and kN/m: type,value; comma separated", "B300x500,3.5"),
        number("slabDeadLoadKpa", "Slab dead load", 0, unit="kPa", min=0),
    ],
)
def weight_totals(ctx: FeatureContext, values: dict) -> dict:
    """Estimate beam and slab gravity weights from engineer-entered line and area loads."""
    _, rows = profile(ctx)
    weights = {}
    try:
        for item in values["lineWeights"].split(";"):
            if item.strip():
                key, val = item.split(",", 1)
                weights[key.strip()] = float(val)
    except ValueError as exc:
        raise FeatureInputError("Enter type,kN/m pairs separated by semicolons.") from exc
    results = []
    for r in rows:
        if r["category"] == "beam":
            weight = r["lengthM"] * weights.get(r["type"], 0)
        elif r["category"] == "slab":
            weight = r["areaM2"] * values["slabDeadLoadKpa"]
        else:
            continue
        results.append(
            {
                "memberId": r["id"],
                "category": r["category"],
                "weightKn": weight,
                "weightDefinitionFound": r["type"] in weights if r["category"] == "beam" else True,
            }
        )
    return result(
        summary={
            "estimatedWeightKn": sum(r["weightKn"] for r in results),
            "missingBeamWeightDefinitions": sum(not r["weightDefinitionFound"] for r in results),
        },
        tables=[
            table(
                "Member weights",
                [
                    ("memberId", "Member"),
                    ("category", "Category"),
                    ("weightKn", "Weight", "kN"),
                    ("weightDefinitionFound", "Definition found"),
                ],
                results,
            )
        ],
        notes=[
            "Beam line weights and slab dead pressure are user-supplied; other member weights are omitted."
        ],
    )


@feature(
    "memberData.costTotals",
    "Cost Totals",
    part="floorPlan",
    fields=[
        text("rates", "Rates as category,value per m or m²", "beam,25;slab,40"),
        select(
            "quantity",
            "Quantity measure",
            [("lengthM", "Length for beam/wall"), ("areaM2", "Area for slab")],
        ),
    ],
)
def cost_totals(ctx: FeatureContext, values: dict) -> dict:
    """Calculate preliminary member cost totals using explicit category rates and measured quantities."""
    _, rows = profile(ctx)
    rates = {}
    try:
        for item in values["rates"].split(";"):
            if item.strip():
                key, rate = item.split(",", 1)
                rates[key.strip()] = float(rate)
    except ValueError as exc:
        raise FeatureInputError("Enter category,rate pairs separated by semicolons.") from exc
    grouped = {}
    for r in rows:
        unit = "areaM2" if r["category"] == "slab" else "lengthM"
        quantity = float(r.get(unit, 0) or 0)
        rate = rates.get(r["category"], 0)
        grouped[r["category"]] = grouped.get(r["category"], 0) + quantity * rate
    out = [
        {"category": k, "estimatedCost": v, "rateDefined": k in rates}
        for k, v in sorted(grouped.items())
    ]
    return result(
        summary={"estimatedCost": sum(grouped.values()), "categories": len(grouped)},
        tables=[
            table(
                "Cost totals by category",
                [
                    ("category", "Category"),
                    ("estimatedCost", "Estimated cost"),
                    ("rateDefined", "Rate defined"),
                ],
                out,
            )
        ],
        notes=["Rates are engineer-supplied planning inputs, not a published schedule of rates."],
    )


@feature(
    "memberData.dataHistogram",
    "Data Histogram",
    part="floorPlan",
    fields=[
        select(
            "field",
            "Numeric property",
            [
                ("lengthM", "Member length"),
                ("areaM2", "Slab area"),
                ("perimeterM", "Slab perimeter"),
            ],
        ),
        number("binWidth", "Bin width", 1, min=0.001),
    ],
)
def data_histogram(ctx: FeatureContext, values: dict) -> dict:
    """Bin available member geometric values into equal-width ranges."""
    _, rows = profile(ctx)
    numbers = [float(r[values["field"]]) for r in rows if r.get(values["field"]) is not None]
    if not numbers:
        raise FeatureInputError("The selected numeric property is not present on any member.")
    lower = math.floor(min(numbers) / values["binWidth"]) * values["binWidth"]
    upper = max(numbers)
    count = max(1, math.ceil((upper - lower) / values["binWidth"]))
    out = []
    for i in range(count):
        lo = lower + i * values["binWidth"]
        hi = lo + values["binWidth"]
        n = sum(lo <= v < (hi if i < count - 1 else hi + 1e-12) for v in numbers)
        out.append({"lower": lo, "upper": hi, "count": n})
    return result(
        summary={
            "observations": len(numbers),
            "binCount": len(out),
            "minimum": min(numbers),
            "maximum": max(numbers),
        },
        tables=[
            table(
                "Geometry histogram",
                [("lower", "Lower"), ("upper", "Upper"), ("count", "Member count")],
                out,
            )
        ],
    )


@feature(
    "memberData.missingFields",
    "Missing Fields",
    part="floorPlan",
    fields=[text("requiredFields", "Required table fields", "id,type,story,category")],
)
def missing_fields(ctx: FeatureContext, values: dict) -> dict:
    """Check every derived member row for missing required property values."""
    _, rows = profile(ctx)
    fields = [x.strip() for x in values["requiredFields"].split(",") if x.strip()]
    out = []
    for r in rows:
        missing = [key for key in fields if r.get(key) in (None, "")]
        if missing:
            out.append({"memberId": r["id"], "missingFields": ", ".join(missing)})
    return result(
        summary={"membersWithMissingFields": len(out), "requiredFieldCount": len(fields)},
        tables=[
            table(
                "Missing member properties",
                [("memberId", "Member"), ("missingFields", "Missing fields")],
                out,
            )
        ],
    )


@feature(
    "memberData.outlierValues",
    "Outlier Values",
    part="floorPlan",
    fields=[
        select(
            "field", "Numeric property", [("lengthM", "Member length"), ("areaM2", "Slab area")]
        ),
        number("standardDeviations", "Outlier threshold", 2.5, min=0.1),
    ],
)
def outlier_values(ctx: FeatureContext, values: dict) -> dict:
    """Flag geometric values beyond a selected number of population standard deviations."""
    _, rows = profile(ctx)
    vals = [r for r in rows if r.get(values["field"]) is not None]
    if len(vals) < 2:
        raise FeatureInputError("At least two members with that numeric property are needed.")
    mean = sum(float(r[values["field"]]) for r in vals) / len(vals)
    sd = math.sqrt(sum((float(r[values["field"]]) - mean) ** 2 for r in vals) / len(vals))
    cutoff = values["standardDeviations"] * sd
    out = [
        {
            "memberId": r["id"],
            "value": r[values["field"]],
            "deviationFromMean": float(r[values["field"]]) - mean,
            "zScore": (float(r[values["field"]]) - mean) / sd if sd else 0,
        }
        for r in vals
        if abs(float(r[values["field"]]) - mean) > cutoff
    ]
    return result(
        summary={
            "outlierCount": len(out),
            "mean": mean,
            "standardDeviation": sd,
            "threshold": cutoff,
        },
        tables=[
            table(
                "Geometric outliers",
                [
                    ("memberId", "Member"),
                    ("value", "Value"),
                    ("deviationFromMean", "Deviation"),
                    ("zScore", "Z score"),
                ],
                out,
            )
        ],
    )


@feature(
    "memberData.fieldFormatCheck",
    "Field Format Check",
    part="floorPlan",
    fields=[
        select(
            "field",
            "Identifier field",
            [("id", "Member id"), ("type", "Type id"), ("story", "Storey id")],
        ),
        text("pattern", "Regular expression", "^[A-Za-z][A-Za-z0-9_-]*$"),
    ],
)
def field_format_check(ctx: FeatureContext, values: dict) -> dict:
    """Validate selected identifiers against an engineer-supplied regular-expression convention."""
    try:
        pattern = re.compile(values["pattern"])
    except re.error as exc:
        raise FeatureInputError(f"Invalid regular expression: {exc}") from exc
    _, rows = profile(ctx)
    invalid = [
        {"memberId": r["id"], "value": r.get(values["field"], "")}
        for r in rows
        if not pattern.fullmatch(str(r.get(values["field"], "")))
    ]
    return result(
        summary={"invalidFormatCount": len(invalid), "checkedMembers": len(rows)},
        tables=[table("Format violations", [("memberId", "Member"), ("value", "Value")], invalid)],
    )


@feature(
    "memberData.approvalStatus",
    "Approval Status",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1,B2"),
        select(
            "status",
            "Approval status",
            [
                ("draft", "Draft"),
                ("review", "In review"),
                ("approved", "Approved"),
                ("rejected", "Rejected"),
            ],
        ),
        text("reviewer", "Reviewer", "Structural lead"),
    ],
    requires_project=False,
)
def approval_status(ctx: FeatureContext, values: dict) -> dict:
    """Build review-status records for a specified member set."""
    ids = _ids(values["memberIds"])
    if not ids:
        raise FeatureInputError("Enter one or more member ids.")
    return result(
        summary={
            "status": values["status"],
            "reviewer": values["reviewer"],
            "members": len(set(ids)),
        },
        tables=[
            table(
                "Member approval records",
                [("memberId", "Member"), ("status", "Status"), ("reviewer", "Reviewer")],
                [
                    {"memberId": mid, "status": values["status"], "reviewer": values["reviewer"]}
                    for mid in dict.fromkeys(ids)
                ],
            )
        ],
    )


@feature(
    "memberData.reviewNotes",
    "Review Notes",
    part="floorPlan",
    fields=[
        text("memberId", "Member id", "B1"),
        text("note", "Review note", "Verify beam section at grid A-1"),
        select("priority", "Priority", [("low", "Low"), ("normal", "Normal"), ("high", "High")]),
    ],
    requires_project=False,
)
def review_notes(ctx: FeatureContext, values: dict) -> dict:
    """Create a structured member review comment with priority and timestamp-free repeatable data."""
    if not values["memberId"].strip() or not values["note"].strip():
        raise FeatureInputError("Member id and review note are required.")
    return result(
        summary={
            "memberId": values["memberId"],
            "priority": values["priority"],
            "noteLength": len(values["note"]),
        },
        tables=[
            table(
                "Review note",
                [("memberId", "Member"), ("priority", "Priority"), ("note", "Note")],
                [
                    {
                        "memberId": values["memberId"],
                        "priority": values["priority"],
                        "note": values["note"],
                    }
                ],
            )
        ],
    )


def _ids(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]

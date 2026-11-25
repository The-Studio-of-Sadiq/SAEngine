"""Members ribbon: review, filter, edit and export a derived floor-plan member table."""

from __future__ import annotations

import csv
import io

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
from saengine.features.plan_common import (
    export_csv,
    plan_data,
    profile,
    selected_members,
)

_COLS = [
    ("id", "Member id"),
    ("category", "Category"),
    ("mark", "Mark"),
    ("type", "Object type"),
    ("story", "Storey"),
    ("lengthM", "Length"),
    ("areaM2", "Area"),
    ("perimeterM", "Perimeter"),
]


@feature(
    "members.memberTable",
    "Member Table",
    part="floorPlan",
    fields=[
        select(
            "category",
            "Category filter",
            [
                ("all", "All"),
                ("beam", "Beam"),
                ("column", "Column"),
                ("wall", "Wall"),
                ("slab", "Slab"),
                ("footing", "Footing"),
            ],
            "all",
        )
    ],
)
def member_table(ctx: FeatureContext, values: dict) -> dict:
    """List model members with current type, storey, resolved centerline length and slab area."""
    _, rows = profile(ctx)
    shown = [r for r in rows if values["category"] == "all" or r["category"] == values["category"]]
    return result(
        summary={"visibleRows": len(shown), "totalMembers": len(rows)},
        tables=[table("Member table", _COLS, shown)],
    )


@feature(
    "members.editInline",
    "Edit Inline",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated)", "B1"),
        select(
            "field",
            "Editable field",
            [("type", "Object type"), ("story", "Storey"), ("mark", "Mark")],
        ),
        text("newValue", "New value", "B350x550"),
    ],
)
def edit_inline(ctx: FeatureContext, values: dict) -> dict:
    """Preview one field edit per selected row and identify each member's current value."""
    plan, rows = profile(ctx)
    selected = selected_members(rows, values["memberIds"])
    raw = {m["id"]: m for g in ("columns", "beams", "walls", "slabs", "footings") for m in plan[g]}
    out = [
        {
            "memberId": r["id"],
            "field": values["field"],
            "currentValue": raw[r["id"]].get(values["field"], r.get(values["field"], "")),
            "newValue": values["newValue"],
        }
        for r in selected
    ]
    return result(
        summary={"editedRows": len(out), "field": values["field"]},
        tables=[
            table(
                "Inline edit preview",
                [
                    ("memberId", "Member"),
                    ("field", "Field"),
                    ("currentValue", "Current"),
                    ("newValue", "Proposed"),
                ],
                out,
            )
        ],
    )


@feature(
    "members.columnChooser",
    "Column Chooser",
    part="floorPlan",
    fields=[text("columns", "Visible member table columns", "id,category,type,story,lengthM")],
    requires_project=False,
)
def column_chooser(ctx: FeatureContext, values: dict) -> dict:
    """Validate visible columns against the derived member schedule's available properties."""
    requested = [x.strip() for x in values["columns"].split(",") if x.strip()]
    available = {key for key, _ in _COLS}
    unknown = sorted(set(requested) - available)
    if unknown:
        raise FeatureInputError(f"Unknown member-table column(s): {', '.join(unknown)}.")
    return result(
        summary={"visibleColumnCount": len(requested)},
        tables=[
            table(
                "Visible columns",
                [("order", "Order"), ("key", "Property"), ("title", "Column")],
                [
                    {"order": i + 1, "key": key, "title": dict(_COLS)[key]}
                    for i, key in enumerate(requested)
                ],
            )
        ],
    )


@feature(
    "members.sortGroup",
    "Sort & Group",
    part="floorPlan",
    fields=[
        select(
            "sortBy",
            "Sort by",
            [
                ("id", "Member id"),
                ("category", "Category"),
                ("type", "Type"),
                ("story", "Storey"),
                ("lengthM", "Length"),
            ],
        ),
        checkbox("descending", "Descending", False),
        select(
            "groupBy",
            "Group rows by",
            [
                ("none", "No grouping"),
                ("category", "Category"),
                ("story", "Storey"),
                ("type", "Type"),
            ],
        ),
    ],
)
def sort_group(ctx: FeatureContext, values: dict) -> dict:
    """Sort the member table on a selected key and optionally count rows by a second key."""
    _, rows = profile(ctx)
    ordered = sorted(
        rows,
        key=lambda r: (r.get(values["sortBy"]) is None, r.get(values["sortBy"], "")),
        reverse=values["descending"],
    )
    grouped = {}
    if values["groupBy"] != "none":
        for r in ordered:
            grouped[r.get(values["groupBy"], "")] = grouped.get(r.get(values["groupBy"], ""), 0) + 1
    return result(
        summary={"sortedMemberCount": len(ordered), "groupCount": len(grouped)},
        tables=[
            table("Sorted members", _COLS, ordered),
            table(
                "Group counts",
                [("group", "Group"), ("memberCount", "Members")],
                [{"group": key, "memberCount": count} for key, count in sorted(grouped.items())],
            ),
        ],
    )


@feature(
    "members.bulkEdit",
    "Bulk Edit",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated)", "B1,B2"),
        select("field", "Property", [("type", "Object type"), ("story", "Storey")]),
        text("value", "New value", "B350x550"),
    ],
)
def bulk_edit(ctx: FeatureContext, values: dict) -> dict:
    """Prepare a consistent property update for multiple selected member rows."""
    _, rows = profile(ctx)
    selected = selected_members(rows, values["memberIds"])
    if values["field"] == "story":
        plan = plan_data(ctx)
        if values["value"] not in {s["id"] for s in plan["stories"]}:
            raise FeatureInputError("The target storey id does not exist.")
    edits = [
        {"memberId": r["id"], "oldValue": r.get(values["field"], ""), "newValue": values["value"]}
        for r in selected
    ]
    return result(
        summary={"editedMembers": len(edits), "field": values["field"]},
        tables=[
            table(
                "Bulk edit schedule",
                [("memberId", "Member"), ("oldValue", "Current"), ("newValue", "Proposed")],
                edits,
            )
        ],
    )


@feature(
    "members.findReplace",
    "Find & Replace",
    part="floorPlan",
    fields=[
        select(
            "field",
            "Text field",
            [("id", "Member id"), ("type", "Object type"), ("story", "Storey")],
        ),
        text("find", "Find", "B300"),
        text("replace", "Replace with", "B350"),
    ],
)
def find_replace(ctx: FeatureContext, values: dict) -> dict:
    """Find literal text matches in one member-table field and calculate proposed replacements."""
    _, rows = profile(ctx)
    if not values["find"]:
        raise FeatureInputError("Enter non-empty find text.")
    matches = []
    for r in rows:
        current = str(r.get(values["field"], ""))
        if values["find"] in current:
            matches.append(
                {
                    "memberId": r["id"],
                    "current": current,
                    "replacement": current.replace(values["find"], values["replace"]),
                }
            )
    return result(
        summary={"matches": len(matches), "field": values["field"]},
        tables=[
            table(
                "Find and replace preview",
                [
                    ("memberId", "Member"),
                    ("current", "Current value"),
                    ("replacement", "Proposed value"),
                ],
                matches,
            )
        ],
    )


@feature(
    "members.renumberMarks",
    "Renumber Marks",
    part="floorPlan",
    fields=[
        text("prefix", "Mark prefix", "BM"),
        number("firstNumber", "First number", 1, min=0),
        number("increment", "Increment", 1, min=1),
        select(
            "category",
            "Member category",
            [
                ("all", "All"),
                ("beam", "Beams"),
                ("column", "Columns"),
                ("wall", "Walls"),
                ("slab", "Slabs"),
                ("footing", "Footings"),
            ],
            "all",
        ),
    ],
)
def renumber_marks(ctx: FeatureContext, values: dict) -> dict:
    """Assign sequential display marks to the selected category in stable member-id order."""
    _, rows = profile(ctx)
    selected = sorted(
        (r for r in rows if values["category"] == "all" or r["category"] == values["category"]),
        key=lambda r: r["id"],
    )
    out = [
        {
            "memberId": r["id"],
            "oldMark": r.get("mark", r["id"]),
            "newMark": f"{values['prefix']}{int(values['firstNumber']) + i * int(values['increment'])}",
        }
        for i, r in enumerate(selected)
    ]
    return result(
        summary={"renumberedMarks": len(out)},
        tables=[
            table(
                "Member marks",
                [("memberId", "Member"), ("oldMark", "Current mark"), ("newMark", "New mark")],
                out,
            )
        ],
    )


@feature(
    "members.pasteFromExcel",
    "Paste From Excel",
    part="floorPlan",
    fields=[
        text(
            "tabSeparatedRows",
            "Pasted columns: memberId,field,value",
            "B1\ttype\tB350x550\nB2\ttype\tB350x550",
        )
    ],
)
def paste_from_excel(ctx: FeatureContext, values: dict) -> dict:
    """Parse pasted tab-separated edit rows and validate member and property names."""
    _, members = profile(ctx)
    known = {r["id"] for r in members}
    parsed = []
    for index, line in enumerate(values["tabSeparatedRows"].splitlines(), 1):
        if not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) != 3:
            raise FeatureInputError(
                f"Pasted row {index} must have member id, field and value columns."
            )
        if cols[0] not in known:
            raise FeatureInputError(f"Pasted row {index} references unknown member '{cols[0]}'.")
        if cols[1] not in {"type", "story", "mark"}:
            raise FeatureInputError(f"Pasted row {index} uses unsupported field '{cols[1]}'.")
        parsed.append({"memberId": cols[0], "field": cols[1], "value": cols[2]})
    return result(
        summary={"acceptedEditRows": len(parsed)},
        tables=[
            table(
                "Pasted edits",
                [("memberId", "Member"), ("field", "Field"), ("value", "Value")],
                parsed,
            )
        ],
    )


@feature(
    "members.importCsv",
    "Import CSV",
    part="floorPlan",
    fields=[text("csvText", "CSV memberId,field,value", "memberId,field,value\nB1,type,B350x550")],
)
def import_csv(ctx: FeatureContext, values: dict) -> dict:
    """Read a CSV edit payload and verify each row maps to a known member and supported field."""
    _, members = profile(ctx)
    known = {r["id"] for r in members}
    parsed = []
    try:
        records = list(csv.DictReader(io.StringIO(values["csvText"])))
    except csv.Error as exc:
        raise FeatureInputError(f"CSV could not be parsed: {exc}") from exc
    for index, row in enumerate(records, 1):
        mid = row.get("memberId", "")
        field = row.get("field", "")
        if mid not in known:
            raise FeatureInputError(f"CSV row {index} references unknown member '{mid}'.")
        if field not in {"type", "story", "mark"}:
            raise FeatureInputError(f"CSV row {index} uses unsupported field '{field}'.")
        parsed.append({"memberId": mid, "field": field, "value": row.get("value", "")})
    return result(
        summary={"acceptedRows": len(parsed)},
        tables=[
            table(
                "CSV member edits",
                [("memberId", "Member"), ("field", "Field"), ("value", "Value")],
                parsed,
            )
        ],
    )


@feature(
    "members.exportTable",
    "Export Table",
    part="floorPlan",
    fields=[
        text("filename", "CSV filename", "members.csv"),
        select(
            "category",
            "Category filter",
            [
                ("all", "All"),
                ("beam", "Beams"),
                ("column", "Columns"),
                ("wall", "Walls"),
                ("slab", "Slabs"),
                ("footing", "Footings"),
            ],
            "all",
        ),
    ],
)
def export_table(ctx: FeatureContext, values: dict) -> dict:
    """Write the filtered member schedule and geometry fields to a comma-separated file."""
    _, rows = profile(ctx)
    selected = [
        r for r in rows if values["category"] == "all" or r["category"] == values["category"]
    ]
    name = values["filename"].strip()
    if not name.lower().endswith(".csv") or "/" in name or "\\" in name:
        raise FeatureInputError("Use a simple CSV filename without folders.")
    path = export_csv(ctx, name, [key for key, _ in _COLS], selected)
    return result(
        summary={"exportedMembers": len(selected), "file": path},
        notes=[f"Wrote member table to {path}."],
    )


@feature(
    "members.showColumns",
    "Show Columns",
    part="floorPlan",
    fields=[text("columns", "Columns to show", "id,category,type,story,lengthM")],
    requires_project=False,
)
def show_columns(ctx: FeatureContext, values: dict) -> dict:
    """Return an ordered column visibility definition for the member schedule."""
    keys = [x.strip() for x in values["columns"].split(",") if x.strip()]
    known = dict(_COLS)
    unknown = set(keys) - known.keys()
    if unknown:
        raise FeatureInputError(f"Unknown member column(s): {', '.join(sorted(unknown))}.")
    return result(
        summary={"visibleColumns": len(keys)},
        tables=[
            table(
                "Member table column layout",
                [("position", "Position"), ("key", "Property"), ("label", "Column label")],
                [
                    {"position": i + 1, "key": key, "label": known[key]}
                    for i, key in enumerate(keys)
                ],
            )
        ],
    )


@feature(
    "members.freezeColumns",
    "Freeze Columns",
    part="floorPlan",
    fields=[text("keys", "Column keys to freeze", "id,mark")],
    requires_project=False,
)
def freeze_columns(ctx: FeatureContext, values: dict) -> dict:
    """Validate frozen identifier columns against member table properties."""
    requested = [x.strip() for x in values["keys"].split(",") if x.strip()]
    known = {key for key, _ in _COLS}
    missing = set(requested) - known
    if missing:
        raise FeatureInputError(f"Unknown freeze column(s): {', '.join(sorted(missing))}.")
    return result(
        summary={"frozenColumnCount": len(requested)},
        tables=[
            table(
                "Frozen columns",
                [("order", "Position"), ("key", "Key"), ("title", "Column")],
                [
                    {"order": i + 1, "key": k, "title": dict(_COLS)[k]}
                    for i, k in enumerate(requested)
                ],
            )
        ],
    )


@feature(
    "members.resizeColumns",
    "Resize Columns",
    part="floorPlan",
    fields=[
        text("keys", "Columns to resize", "id,type,story"),
        number("minimumWidthPx", "Minimum width", 80, unit="px", min=1),
        checkbox("fitContent", "Fit content", True),
    ],
)
def resize_columns(ctx: FeatureContext, values: dict) -> dict:
    """Estimate column widths from headers and current member values, subject to a minimum."""
    _, rows = profile(ctx)
    keys = [x.strip() for x in values["keys"].split(",") if x.strip()]
    known = dict(_COLS)
    missing = set(keys) - known.keys()
    if missing:
        raise FeatureInputError(f"Unknown member column(s): {', '.join(sorted(missing))}.")
    out = []
    for key in keys:
        content = (
            max((len(str(row.get(key, ""))) for row in rows), default=0)
            if values["fitContent"]
            else 0
        )
        out.append(
            {
                "key": key,
                "title": known[key],
                "widthPx": max(values["minimumWidthPx"], 8 * (max(len(known[key]), content) + 2)),
            }
        )
    return result(
        summary={"resizedColumns": len(out)},
        tables=[
            table(
                "Column widths",
                [("key", "Key"), ("title", "Header"), ("widthPx", "Width", "px")],
                out,
            )
        ],
    )


@feature(
    "members.columnPresets",
    "Column Presets",
    part="floorPlan",
    fields=[
        text("presetName", "Preset name", "Design review"),
        text("keys", "Columns in order", "id,category,type,story,lengthM,areaM2"),
    ],
    requires_project=False,
)
def column_presets(ctx: FeatureContext, values: dict) -> dict:
    """Validate and package a named member-table column layout."""
    keys = [x.strip() for x in values["keys"].split(",") if x.strip()]
    unknown = set(keys) - {k for k, _ in _COLS}
    if unknown:
        raise FeatureInputError(f"Unknown member column(s): {', '.join(sorted(unknown))}.")
    return result(
        summary={"presetName": values["presetName"], "columnCount": len(keys)},
        tables=[
            table(
                "Preset columns",
                [("position", "Position"), ("key", "Property"), ("label", "Label")],
                [
                    {"position": i + 1, "key": key, "label": dict(_COLS)[key]}
                    for i, key in enumerate(keys)
                ],
            )
        ],
    )


@feature(
    "members.columnTotals",
    "Column Totals",
    part="floorPlan",
    fields=[
        select(
            "measure",
            "Numeric measure",
            [
                ("lengthM", "Member length"),
                ("areaM2", "Slab area"),
                ("perimeterM", "Slab perimeter"),
            ],
        ),
        select(
            "groupBy",
            "Group totals by",
            [
                ("none", "All members"),
                ("category", "Category"),
                ("story", "Storey"),
                ("type", "Object type"),
            ],
        ),
    ],
)
def column_totals(ctx: FeatureContext, values: dict) -> dict:
    """Total a chosen geometric measure overall or by member category, storey or type."""
    _, rows = profile(ctx)
    groups = {}
    for r in rows:
        key = "All members" if values["groupBy"] == "none" else str(r.get(values["groupBy"], ""))
        groups[key] = groups.get(key, 0) + float(r.get(values["measure"], 0) or 0)
    return result(
        summary={
            "groupCount": len(groups),
            "total": sum(groups.values()),
            "measure": values["measure"],
        },
        tables=[
            table(
                "Member table totals",
                [("group", "Group"), ("total", "Total")],
                [{"group": k, "total": v} for k, v in sorted(groups.items())],
            )
        ],
    )


@feature(
    "members.addRow",
    "Add Row",
    part="floorPlan",
    fields=[
        select(
            "category",
            "Category",
            [
                ("beam", "Beam"),
                ("column", "Column"),
                ("wall", "Wall"),
                ("slab", "Slab"),
                ("footing", "Footing"),
            ],
        ),
        text("memberId", "New member id", "B99"),
        text("type", "Object type id", "B300x500"),
        text("story", "Storey id", "L1"),
    ],
)
def add_row(ctx: FeatureContext, values: dict) -> dict:
    """Validate a proposed member-table row against the current ids and storeys."""
    plan, rows = profile(ctx)
    if values["memberId"] in {r["id"] for r in rows}:
        raise FeatureInputError("Member id already exists.")
    if values["story"] not in {s["id"] for s in plan["stories"]}:
        raise FeatureInputError("Storey id does not exist.")
    return result(
        summary={"newRows": 1, "memberId": values["memberId"], "category": values["category"]},
        tables=[
            table(
                "Proposed member row",
                [("id", "Member"), ("category", "Category"), ("type", "Type"), ("story", "Storey")],
                [
                    {
                        "id": values["memberId"],
                        "category": values["category"],
                        "type": values["type"],
                        "story": values["story"],
                    }
                ],
            )
        ],
        notes=[
            "This table preview does not create the geometry required by floor-plan member placement."
        ],
    )


@feature(
    "members.deleteRows",
    "Delete Rows",
    part="floorPlan",
    fields=[text("memberIds", "Member ids to delete", "B1")],
)
def delete_rows(ctx: FeatureContext, values: dict) -> dict:
    """List selected member rows and their associated load records for a deletion review."""
    _, rows = profile(ctx)
    selected = selected_members(rows, values["memberIds"])
    from saengine.features.plan_common import loads_data

    loads = loads_data(ctx).get("loads", [])
    return result(
        summary={
            "memberRowsToDelete": len(selected),
            "loadRecordsAffected": sum(
                item.get("member") in {r["id"] for r in selected} for item in loads
            ),
        },
        tables=[
            table(
                "Rows selected for deletion",
                [("id", "Member"), ("category", "Category"), ("type", "Type"), ("story", "Storey")],
                selected,
            )
        ],
    )


@feature(
    "members.duplicateRow",
    "Duplicate Row",
    part="floorPlan",
    fields=[
        text("memberId", "Member id to duplicate", "B1"),
        text("newMemberId", "New id", "B1-copy"),
    ],
)
def duplicate_row(ctx: FeatureContext, values: dict) -> dict:
    """Prepare a duplicate member-table record and verify its new identifier is unused."""
    _plan, rows = profile(ctx)
    source = next((r for r in rows if r["id"] == values["memberId"]), None)
    if source is None:
        raise FeatureInputError("Source member id was not found.")
    if values["newMemberId"] in {r["id"] for r in rows}:
        raise FeatureInputError("New member id already exists.")
    return result(
        summary={
            "sourceId": source["id"],
            "newMemberId": values["newMemberId"],
            "category": source["category"],
        },
        tables=[
            table(
                "Duplicated row preview",
                [
                    ("sourceId", "Source"),
                    ("newId", "New id"),
                    ("type", "Type"),
                    ("story", "Storey"),
                ],
                [
                    {
                        "sourceId": source["id"],
                        "newId": values["newMemberId"],
                        "type": source["type"],
                        "story": source["story"],
                    }
                ],
            )
        ],
        notes=["Geometry is not duplicated by a table-row-only preview."],
    )


@feature(
    "members.moveRow",
    "Move Row",
    part="floorPlan",
    fields=[text("memberId", "Member id", "B2"), number("newOrder", "New row position", 1, min=1)],
)
def move_row(ctx: FeatureContext, values: dict) -> dict:
    """Return a stable member table order with one selected id moved to the requested row index."""
    _, rows = profile(ctx)
    source = next((r for r in rows if r["id"] == values["memberId"]), None)
    if source is None:
        raise FeatureInputError("Member id was not found.")
    ordered = [r for r in rows if r["id"] != source["id"]]
    index = min(int(values["newOrder"]) - 1, len(ordered))
    ordered.insert(index, source)
    return result(
        summary={"rowCount": len(ordered), "movedMemberId": source["id"], "newPosition": index + 1},
        tables=[
            table(
                "Reordered member rows",
                [("position", "Position"), ("id", "Member"), ("category", "Category")],
                [
                    {"position": i + 1, "id": r["id"], "category": r["category"]}
                    for i, r in enumerate(ordered)
                ],
            )
        ],
    )


@feature(
    "members.hideRows",
    "Hide Rows",
    part="floorPlan",
    fields=[
        select(
            "category",
            "Category to hide",
            [
                ("beam", "Beams"),
                ("column", "Columns"),
                ("wall", "Walls"),
                ("slab", "Slabs"),
                ("footing", "Footings"),
            ],
        ),
        text("storey", "Storey id to hide (blank for any)", ""),
    ],
)
def hide_rows(ctx: FeatureContext, values: dict) -> dict:
    """Separate hidden member table rows from those remaining visible under the category filter."""
    _, rows = profile(ctx)
    hidden = [
        r
        for r in rows
        if r["category"] == values["category"]
        and (not values["storey"] or r["story"] == values["storey"])
    ]
    visible = [r for r in rows if r not in hidden]
    return result(
        summary={"hiddenRows": len(hidden), "visibleRows": len(visible)},
        tables=[
            table(
                "Hidden rows",
                [("id", "Member"), ("category", "Category"), ("story", "Storey")],
                hidden,
            )
        ],
    )


@feature(
    "members.fillDown",
    "Fill Down",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids in fill order", "B1,B2,B3"),
        select("field", "Field", [("type", "Object type"), ("story", "Storey")]),
        text("value", "Value to fill", "B300x500"),
    ],
)
def fill_down(ctx: FeatureContext, values: dict) -> dict:
    """Create ordered per-row assignments for a fill-down edit and validate story values."""
    _, rows = profile(ctx)
    selected = selected_members(rows, values["memberIds"])
    if values["field"] == "story" and values["value"] not in {
        s["id"] for s in plan_data(ctx)["stories"]
    }:
        raise FeatureInputError("Target storey id does not exist.")
    return result(
        summary={"filledRows": len(selected), "field": values["field"]},
        tables=[
            table(
                "Fill-down values",
                [("row", "Row"), ("memberId", "Member"), ("value", "Value")],
                [
                    {"row": i + 1, "memberId": r["id"], "value": values["value"]}
                    for i, r in enumerate(selected)
                ],
            )
        ],
    )


@feature(
    "members.formulaColumn",
    "Formula Column",
    part="floorPlan",
    fields=[
        text("columnName", "Computed column name", "Estimated concrete volume"),
        select(
            "formula",
            "Formula",
            [
                ("beamLength", "Beam length total"),
                ("slabArea", "Slab area total"),
                ("slabPerimeter", "Slab perimeter total"),
            ],
        ),
    ],
)
def formula_column(ctx: FeatureContext, values: dict) -> dict:
    """Evaluate a defined geometric aggregate into a new computed member-table column."""
    _, rows = profile(ctx)
    if values["formula"] == "beamLength":
        selected = [r for r in rows if r["category"] == "beam"]
        values_sum = sum(r["lengthM"] for r in selected)
        unit = "m"
    elif values["formula"] == "slabArea":
        selected = [r for r in rows if r["category"] == "slab"]
        values_sum = sum(r["areaM2"] for r in selected)
        unit = "m²"
    else:
        selected = [r for r in rows if r["category"] == "slab"]
        values_sum = sum(r["perimeterM"] for r in selected)
        unit = "m"
    return result(
        summary={
            "columnName": values["columnName"],
            "formula": values["formula"],
            "value": values_sum,
            "unit": unit,
            "sourceRows": len(selected),
        }
    )


@feature(
    "members.valueValidation",
    "Value Validation",
    part="floorPlan",
    fields=[
        select(
            "field",
            "Numeric field",
            [
                ("lengthM", "Member length"),
                ("areaM2", "Slab area"),
                ("perimeterM", "Slab perimeter"),
            ],
        ),
        number("minimum", "Minimum allowed", 0, min=0),
        number("maximum", "Maximum allowed", 100, min=0),
    ],
)
def value_validation(ctx: FeatureContext, values: dict) -> dict:
    """Flag member rows whose selected geometric value falls outside the entered range."""
    if values["maximum"] < values["minimum"]:
        raise FeatureInputError("Maximum must be at least minimum.")
    _, rows = profile(ctx)
    bad = [
        {"id": r["id"], "category": r["category"], "value": r.get(values["field"])}
        for r in rows
        if r.get(values["field"]) is not None
        and not values["minimum"] <= float(r[values["field"]]) <= values["maximum"]
    ]
    return result(
        summary={
            "invalidRows": len(bad),
            "validatedRows": sum(r.get(values["field"]) is not None for r in rows),
            "range": f"{values['minimum']}–{values['maximum']}",
        },
        tables=[
            table(
                "Values outside range",
                [("id", "Member"), ("category", "Category"), ("value", "Value")],
                bad,
            )
        ],
    )


@feature(
    "members.undoTableEdit",
    "Undo Table Edit",
    part="floorPlan",
    fields=[
        text("beforeJson", "Before-edit member rows JSON", "[]"),
        text("afterJson", "After-edit member rows JSON", "[]"),
    ],
)
def undo_table_edit(ctx: FeatureContext, values: dict) -> dict:
    """Compare before and after table snapshots to produce a reversible edit record."""
    import json

    try:
        before = json.loads(values["beforeJson"])
        after = json.loads(values["afterJson"])
    except ValueError as exc:
        raise FeatureInputError("Before and after snapshots must be valid JSON arrays.") from exc
    if not isinstance(before, list) or not isinstance(after, list):
        raise FeatureInputError("Before and after snapshots must be JSON arrays.")
    old = {r.get("id"): r for r in before}
    new = {r.get("id"): r for r in after}
    changes = []
    for mid in sorted(set(old) | set(new)):
        if mid not in old:
            changes.append({"id": mid, "change": "remove added row"})
        elif mid not in new:
            changes.append({"id": mid, "change": "restore deleted row"})
        elif old[mid] != new[mid]:
            changes.append({"id": mid, "change": "restore prior values"})
    return result(
        summary={"undoRecords": len(changes)},
        tables=[table("Undo operations", [("id", "Member"), ("change", "Undo action")], changes)],
    )

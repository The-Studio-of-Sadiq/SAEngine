"""Drawing schedules, keynote tables and takeoffs in Documents."""

from __future__ import annotations

import json
import re
from pathlib import Path

from saengine.drawings.sheets.schedule_builder import build_schedule
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
from saengine.features.documents_common import (
    document_state,
    project_fields,
    read_json,
    require_root,
    save_document_state,
)
from saengine.features.plan_common import grid_rows, member_rows, plan_data


def _state(ctx: FeatureContext) -> dict:
    state = document_state(ctx, "scheduleBuilder")
    state.setdefault("schedules", [])
    state.setdefault("keynotes", {})
    state.setdefault("memberKeynotes", {})
    state.setdefault("templates", [])
    return state


def _save(ctx: FeatureContext, state: dict) -> str:
    return save_document_state(ctx, "scheduleBuilder", state)


def _categories(ctx: FeatureContext) -> dict:
    plan = plan_data(ctx)
    members = member_rows(plan)
    grids = grid_rows(plan)
    stories = [
        {"id": s["id"], "name": s["name"], "elevationMm": s["elevation"], "order": index + 1}
        for index, s in enumerate(sorted(plan["stories"], key=lambda s: float(s["elevation"])))
    ]
    return {"members": members, "grids": grids, "stories": stories}


def _definition(state: dict, schedule_id: str) -> dict:
    found = next((row for row in state["schedules"] if row["id"] == schedule_id), None)
    if not found:
        raise FeatureInputError(f"Schedule {schedule_id!r} does not exist; create it first.")
    return found


def _build(ctx: FeatureContext, definition: dict):
    try:
        return build_schedule(definition, _categories(ctx))
    except (ValueError, TypeError, KeyError) as exc:
        raise FeatureInputError(f"Schedule could not be built: {exc}") from exc


def _summary(schedule, title: str | None = None) -> dict:
    return {
        "title": title or schedule.title,
        "rowCount": len(schedule.rows),
        "columns": schedule.columns,
        "rows": [dict(zip(schedule.columns, row, strict=True)) for row in schedule.rows],
    }


@feature(
    "documentsSchedules.newSchedule",
    "New Schedule",
    part="documents",
    fields=[
        text("scheduleId", "Schedule id", "member-schedule"),
        text("name", "Schedule name", "Member Schedule"),
        select(
            "category",
            "Source category",
            [("members", "Floor plan members"), ("grids", "Grid lines"), ("stories", "Stories")],
            "members",
        ),
    ],
)
def new_schedule(ctx: FeatureContext, values: dict) -> dict:
    """Create a persistent user schedule definition against one available project category."""
    sid = values["scheduleId"].strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", sid):
        raise FeatureInputError("Schedule id must use lowercase letters, digits and hyphens.")
    state = _state(ctx)
    if any(row["id"] == sid for row in state["schedules"]):
        raise FeatureInputError("That schedule id already exists.")
    category_rows = _categories(ctx)[values["category"]]
    if not category_rows:
        raise FeatureInputError(f"Project has no {values['category']} records to schedule.")
    definition = {
        "id": sid,
        "title": values["name"].strip(),
        "category": values["category"],
        "fields": [{"key": key, "title": key} for key in category_rows[0]],
        "filters": [],
        "sort": [],
        "groupBy": [],
        "totals": [],
        "itemize": True,
    }
    state["schedules"].append(definition)
    _save(ctx, state)
    return result(
        summary={
            "scheduleId": sid,
            "title": definition["title"],
            "category": definition["category"],
            "availableFields": [field["key"] for field in definition["fields"]],
        }
    )


@feature(
    "documentsSchedules.fieldsColumns",
    "Fields Columns",
    part="documents",
    fields=[
        text("scheduleId", "Schedule id", "member-schedule"),
        text("fields", "Field keys, comma separated", "mark,type,story,lengthM"),
        text("titles", "Column titles, comma separated", "Mark,Type,Story,Length"),
    ],
)
def fields_columns(ctx: FeatureContext, values: dict) -> dict:
    """Choose and order source fields and set visible headings for a schedule."""
    state = _state(ctx)
    definition = _definition(state, values["scheduleId"])
    available = {row for record in _categories(ctx)[definition["category"]] for row in record}
    keys = [v.strip() for v in values["fields"].split(",") if v.strip()]
    titles = [v.strip() for v in values["titles"].split(",") if v.strip()]
    if not keys or len(set(keys)) != len(keys):
        raise FeatureInputError("Choose one or more unique field keys.")
    missing = set(keys) - available
    if missing:
        raise FeatureInputError(f"Unknown schedule field(s): {', '.join(sorted(missing))}.")
    if titles and len(titles) != len(keys):
        raise FeatureInputError("Enter one title for each selected field.")
    definition["fields"] = [
        {"key": key, "title": titles[index] if titles else key} for index, key in enumerate(keys)
    ]
    _save(ctx, state)
    return result(
        summary={
            "scheduleId": definition["id"],
            "columnCount": len(keys),
            "columns": definition["fields"],
        }
    )


@feature(
    "documentsSchedules.filters",
    "Schedule Filters",
    part="documents",
    fields=[
        text("scheduleId", "Schedule id", "member-schedule"),
        text("field", "Filter field", "story"),
        select(
            "operator",
            "Comparison",
            [
                ("==", "Equals"),
                ("!=", "Not equals"),
                ("contains", "Contains"),
                (">", "Greater than"),
                ("<", "Less than"),
            ],
            "==",
        ),
        text("value", "Filter value", "Level 1"),
        checkbox("append", "Add to existing filters", True),
    ],
)
def schedule_filters(ctx: FeatureContext, values: dict) -> dict:
    """Add or replace a typed record filter in a schedule definition."""
    state = _state(ctx)
    definition = _definition(state, values["scheduleId"])
    keys = {item["key"] for item in definition["fields"]}
    if values["field"] not in keys:
        raise FeatureInputError("Filter field must be included as a schedule column.")
    rule = {"field": values["field"], "operator": values["operator"], "value": values["value"]}
    if not values["append"]:
        definition["filters"] = []
    definition["filters"].append(rule)
    built = _build(ctx, definition)
    _save(ctx, state)
    return result(
        summary={
            "filterCount": len(definition["filters"]),
            "matchingRows": len(built.rows),
            "filter": rule,
        }
    )


@feature(
    "documentsSchedules.sorting",
    "Schedule Sorting",
    part="documents",
    fields=[
        text("scheduleId", "Schedule id", "member-schedule"),
        text("field", "Sort field", "mark"),
        select("order", "Sort order", [("asc", "Ascending"), ("desc", "Descending")], "asc"),
    ],
)
def schedule_sorting(ctx: FeatureContext, values: dict) -> dict:
    """Set the stable sort field and direction used when building a schedule."""
    state = _state(ctx)
    definition = _definition(state, values["scheduleId"])
    if values["field"] not in {item["key"] for item in definition["fields"]}:
        raise FeatureInputError("Sort field must be a selected schedule column.")
    definition["sort"] = [{"field": values["field"], "order": values["order"]}]
    built = _build(ctx, definition)
    _save(ctx, state)
    return result(
        summary={
            "sortField": values["field"],
            "order": values["order"],
            "rowCount": len(built.rows),
        }
    )


@feature(
    "documentsSchedules.calculatedFields",
    "Calculated Fields",
    part="documents",
    fields=[
        text("scheduleId", "Schedule id", "member-schedule"),
        text("key", "New field key", "weightKN"),
        text("title", "Column title", "Weight [kN]"),
        text("expression", "Arithmetic expression", "areaM2*25"),
    ],
)
def calculated_fields(ctx: FeatureContext, values: dict) -> dict:
    """Add a safe arithmetic calculated column to a user-defined schedule."""
    state = _state(ctx)
    definition = _definition(state, values["scheduleId"])
    key = values["key"].strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key) or key in {
        f["key"] for f in definition["fields"]
    }:
        raise FeatureInputError(
            "Calculated field key must be new and use letters, digits or underscores."
        )
    definition["fields"].append(
        {"key": key, "title": values["title"], "expression": values["expression"]}
    )
    built = _build(ctx, definition)
    _save(ctx, state)
    return result(summary={"calculatedField": key, "rowCount": len(built.rows)})


@feature(
    "documentsSchedules.groupingRules",
    "Grouping Rules",
    part="documents",
    fields=[
        text("scheduleId", "Schedule id", "member-schedule"),
        text("fields", "Group field keys", "story"),
        checkbox("itemize", "Keep individual rows", True),
    ],
)
def grouping_rules(ctx: FeatureContext, values: dict) -> dict:
    """Group schedule entries by one or more listed fields and choose itemized or summarized rows."""
    state = _state(ctx)
    definition = _definition(state, values["scheduleId"])
    fields = [x.strip() for x in values["fields"].split(",") if x.strip()]
    if any(key not in {f["key"] for f in definition["fields"]} for key in fields):
        raise FeatureInputError("Group fields must be selected schedule columns.")
    definition["groupBy"] = fields
    definition["itemize"] = values["itemize"]
    built = _build(ctx, definition)
    _save(ctx, state)
    return result(
        summary={"groupFields": fields, "itemized": values["itemize"], "rowCount": len(built.rows)}
    )


@feature(
    "documentsSchedules.keynoteFile",
    "Keynote File",
    part="documents",
    fields=[
        text("csvPath", "Project-relative JSON or CSV keynote file", "11 Exports/keynotes.json")
    ],
)
def keynote_file(ctx: FeatureContext, values: dict) -> dict:
    """Load a project keynote mapping from JSON or a key,description CSV file."""
    root = require_root(ctx)
    path = (root / values["csvPath"]).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Keynote file must stay inside the project folder.") from exc
    if not path.is_file():
        raise FeatureInputError("Select an existing keynote file.")
    try:
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            import csv

            with path.open(encoding="utf-8-sig", newline="") as stream:
                data = {row["key"]: row["description"] for row in csv.DictReader(stream)}
    except (OSError, ValueError, KeyError) as exc:
        raise FeatureInputError(f"Keynote file could not be read: {exc}") from exc
    if (
        not isinstance(data, dict)
        or not data
        or any(not str(k).strip() or not str(v).strip() for k, v in data.items())
    ):
        raise FeatureInputError("Keynote data must map non-empty keys to descriptions.")
    state = _state(ctx)
    state["keynotes"] = {str(k): str(v) for k, v in data.items()}
    state["keynoteSource"] = path.relative_to(root).as_posix()
    _save(ctx, state)
    return result(summary={"keynoteCount": len(data), "source": state["keynoteSource"]})


@feature(
    "documentsSchedules.keynoteLegend",
    "Keynote Legend",
    part="documents",
    fields=[checkbox("usedOnly", "Include only assigned keynotes", True)],
)
def keynote_legend(ctx: FeatureContext, values: dict) -> dict:
    """Build a keynote legend from loaded descriptions and optionally limit it to keys used by members."""
    state = _state(ctx)
    keynotes = state["keynotes"]
    if not keynotes:
        try:
            from saengine.drawings.sheets.keynotes import STARTER_KEYNOTES, load_keynotes

            keynotes = load_keynotes(STARTER_KEYNOTES)
        except (OSError, ValueError) as exc:
            raise FeatureInputError(f"Starter keynote library could not be read: {exc}") from exc
    used = set(state.get("memberKeynotes", {}).values())
    if values["usedOnly"]:
        rows = [
            {"key": key, "description": keynotes[key]} for key in sorted(used) if key in keynotes
        ]
    else:
        rows = [
            {"key": key, "description": description}
            for key, description in sorted(keynotes.items())
        ]
    missing = sorted(used - set(keynotes))
    _save(ctx, state)
    return result(
        summary={"legendCount": len(rows), "missingDescriptions": missing},
        tables=[table("Keynote legend", [("key", "Key"), ("description", "Description")], rows)],
    )


@feature(
    "documentsSchedules.autoNumber",
    "Auto Number",
    part="documents",
    fields=[
        text("worksheetId", "Schedule id", "member-schedule"),
        text("prefix", "Mark prefix", "M"),
        number("start", "Starting number", 1, min=1),
        number("digits", "Zero-padded digits", 3, min=1, max=8),
    ],
)
def auto_number(ctx: FeatureContext, values: dict) -> dict:
    """Assign deterministic marks to the model's member records and save the mapping for schedules."""
    state = _state(ctx)
    prefix = values["prefix"].strip()
    records = sorted(member_rows(plan_data(ctx)), key=lambda row: (row["category"], row["id"]))
    mapping = {
        row["id"]: f"{prefix}{int(values['start']) + index:0{int(values['digits'])}d}"
        for index, row in enumerate(records)
    }
    state["memberMarks"] = mapping
    _save(ctx, state)
    return result(
        summary={
            "numberedMembers": len(mapping),
            "prefix": prefix,
            "firstMark": next(iter(mapping.values()), None),
            "lastMark": next(reversed(mapping.values()), None),
        }
    )


@feature(
    "documentsSchedules.scheduleOnSheet",
    "Schedule on Sheet",
    part="documents",
    fields=[
        text("scheduleId", "Schedule id", "member-schedule"),
        text("sheet", "Sheet number", "S-101"),
        number("startXmm", "Placement X", 20, unit="mm"),
        number("startYmm", "Placement Y", 20, unit="mm"),
    ],
)
def schedule_on_sheet(ctx: FeatureContext, values: dict) -> dict:
    """Place a built schedule table in the Drawing Preview workspace with a sheet anchor."""
    state = _state(ctx)
    definition = _definition(state, values["scheduleId"])
    built = _build(ctx, definition)
    drawing = document_state(ctx, "drawingPreview")
    sheets = drawing.setdefault("sheets", [])
    if not any(row.get("number") == values["sheet"] for row in sheets):
        raise FeatureInputError(
            f"Sheet {values['sheet']} is not in Drawing Preview; create the sheet first."
        )
    placed = drawing.setdefault("scheduleTables", [])
    placed.append(
        {
            "scheduleId": definition["id"],
            "title": definition["title"],
            "sheet": values["sheet"],
            "anchorMm": [values["startXmm"], values["startYmm"]],
            "columns": built.columns,
            "rows": built.rows,
        }
    )
    save_document_state(ctx, "drawingPreview", drawing)
    _save(ctx, state)
    return result(
        summary={
            "scheduleId": definition["id"],
            "sheet": values["sheet"],
            "rowCount": len(built.rows),
            "anchorMm": [values["startXmm"], values["startYmm"]],
        }
    )


@feature(
    "documentsSchedules.splitSchedule",
    "Split Schedule",
    part="documents",
    fields=[
        text("scheduleId", "Schedule id", "member-schedule"),
        number("rowsPerPage", "Rows per sheet", 25, min=1, max=500),
    ],
)
def split_schedule(ctx: FeatureContext, values: dict) -> dict:
    """Split a built schedule into page-sized row blocks while preserving the same column headings."""
    state = _state(ctx)
    definition = _definition(state, values["scheduleId"])
    built = _build(ctx, definition)
    size = int(values["rowsPerPage"])
    pages = [built.rows[i : i + size] for i in range(0, len(built.rows), size)]
    state.setdefault("splitSchedules", {})[definition["id"]] = {
        "rowsPerPage": size,
        "pages": pages,
        "columns": built.columns,
    }
    _save(ctx, state)
    return result(
        summary={
            "pageCount": len(pages),
            "rowsPerPage": size,
            "rowCounts": [len(page) for page in pages],
        }
    )


@feature(
    "documentsSchedules.totals",
    "Schedule Totals",
    part="documents",
    fields=[
        text("scheduleId", "Schedule id", "member-schedule"),
        text("fields", "Numeric fields to total", "lengthM,areaM2"),
    ],
)
def schedule_totals(ctx: FeatureContext, values: dict) -> dict:
    """Configure numeric schedule totals and calculate their current values."""
    state = _state(ctx)
    definition = _definition(state, values["scheduleId"])
    fields = [x.strip() for x in values["fields"].split(",") if x.strip()]
    definition["totals"] = fields
    built = _build(ctx, definition)
    _save(ctx, state)
    return result(
        summary={
            "totals": fields,
            "scheduleRows": len(built.rows),
            "summaryRow": built.rows[-1] if built.rows else None,
        }
    )


@feature(
    "documentsSchedules.columnWidths",
    "Column Widths",
    part="documents",
    fields=[
        text("scheduleId", "Schedule id", "member-schedule"),
        text("widthsMm", "Widths in mm, comma separated", "22,30,30,25"),
    ],
)
def column_widths(ctx: FeatureContext, values: dict) -> dict:
    """Set validated per-column widths for the selected schedule."""
    state = _state(ctx)
    definition = _definition(state, values["scheduleId"])
    try:
        widths = [float(item.strip()) for item in values["widthsMm"].split(",")]
    except ValueError as exc:
        raise FeatureInputError("Column widths must be numeric millimetres.") from exc
    if len(widths) != len(definition["fields"]) or any(width <= 0 for width in widths):
        raise FeatureInputError("Provide one positive width per schedule column.")
    definition["columnWidthsMm"] = widths
    _save(ctx, state)
    return result(summary={"scheduleId": definition["id"], "columnWidthsMm": widths})


@feature(
    "documentsSchedules.headerStyles",
    "Header Styles",
    part="documents",
    fields=[
        text("scheduleId", "Schedule id", "member-schedule"),
        checkbox("bold", "Bold headings", True),
        text("fill", "Header fill colour", "#DDEBF7"),
        number("fontSizePt", "Font size", 9, min=6, max=24),
    ],
)
def header_styles(ctx: FeatureContext, values: dict) -> dict:
    """Set validated heading typography and fill for a schedule table."""
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", values["fill"]):
        raise FeatureInputError("Header fill must be a six-digit hexadecimal colour.")
    state = _state(ctx)
    definition = _definition(state, values["scheduleId"])
    definition["headerStyle"] = {
        "bold": values["bold"],
        "fill": values["fill"],
        "fontSizePt": values["fontSizePt"],
    }
    _save(ctx, state)
    return result(
        summary={"scheduleId": definition["id"], "headerStyle": definition["headerStyle"]}
    )


@feature(
    "documentsSchedules.rowHeight",
    "Row Height",
    part="documents",
    fields=[
        text("scheduleId", "Schedule id", "member-schedule"),
        number("heightMm", "Row height", 7, unit="mm", min=2, max=50),
        checkbox("wrapText", "Wrap long values", True),
    ],
)
def row_height(ctx: FeatureContext, values: dict) -> dict:
    """Set schedule row height and text wrapping preferences."""
    state = _state(ctx)
    definition = _definition(state, values["scheduleId"])
    definition["rowStyle"] = {"heightMm": values["heightMm"], "wrapText": values["wrapText"]}
    _save(ctx, state)
    return result(
        summary={
            "scheduleId": definition["id"],
            "rowHeightMm": values["heightMm"],
            "wrapText": values["wrapText"],
        }
    )


@feature(
    "documentsSchedules.gridlines",
    "Schedule Gridlines",
    part="documents",
    fields=[
        text("scheduleId", "Schedule id", "member-schedule"),
        select(
            "style",
            "Gridline style",
            [("none", "None"), ("horizontal", "Horizontal only"), ("full", "Full grid")],
            "full",
        ),
        text("colour", "Gridline colour", "#808080"),
    ],
)
def schedule_gridlines(ctx: FeatureContext, values: dict) -> dict:
    """Set schedule row and column gridline style with a validated line colour."""
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", values["colour"]):
        raise FeatureInputError("Gridline colour must be a six-digit hexadecimal colour.")
    state = _state(ctx)
    definition = _definition(state, values["scheduleId"])
    definition["gridlines"] = {"style": values["style"], "colour": values["colour"]}
    _save(ctx, state)
    return result(summary={"scheduleId": definition["id"], "gridlines": values["style"]})


@feature(
    "documentsSchedules.materialTakeoff",
    "Material Takeoff",
    part="documents",
    fields=[checkbox("groupByType", "Group members by type", True)],
)
def material_takeoff(ctx: FeatureContext, values: dict) -> dict:
    """Calculate floor-plan member counts and slab areas by member type from the active project model."""
    rows = member_rows(plan_data(ctx))
    groups = {}
    for row in rows:
        key = row["type"]
        entry = groups.setdefault(
            key, {"type": key, "memberCount": 0, "slabAreaM2": 0.0, "beamLengthM": 0.0}
        )
        entry["memberCount"] += 1
        entry["slabAreaM2"] += row.get("areaM2", 0)
        entry["beamLengthM"] += row.get("lengthM", 0) if row["category"] == "beam" else 0
    out = (
        list(groups.values())
        if values["groupByType"]
        else [
            {
                "type": row["mark"],
                "memberCount": 1,
                "slabAreaM2": row.get("areaM2", 0),
                "beamLengthM": row.get("lengthM", 0) if row["category"] == "beam" else 0,
            }
            for row in rows
        ]
    )
    return result(
        summary={"memberCount": len(rows), "materialTypeCount": len(out)},
        tables=[
            table(
                "Floor plan material takeoff",
                [
                    ("type", "Member type"),
                    ("memberCount", "Count"),
                    ("slabAreaM2", "Slab area", "m²"),
                    ("beamLengthM", "Beam length", "m"),
                ],
                out,
            )
        ],
    )


@feature(
    "documentsSchedules.rebarSchedule",
    "Rebar Schedule",
    part="documents",
    fields=[text("barSize", "Bar size filter", ""), text("markPrefix", "Mark prefix", "RB")],
)
def rebar_schedule(ctx: FeatureContext, values: dict) -> dict:
    """Schedule explicit reinforcement records from the BIM model and calculate bar lengths by mark."""
    bim = project_fields(ctx).get("bim") or {}
    bars = bim.get("reinforcement", bim.get("bars", []))
    if not bars:
        raise FeatureInputError("The project BIM has no reinforcement records to schedule.")
    rows = []
    for bar in bars:
        diameter = bar.get("diameterMm", bar.get("barSizeMm"))
        length = bar.get("lengthMm")
        if values["barSize"] and str(diameter) != values["barSize"]:
            continue
        if length is None:
            continue
        rows.append(
            {
                "mark": values["markPrefix"] + str(bar.get("mark", bar.get("id", ""))),
                "barSizeMm": diameter,
                "quantity": int(bar.get("quantity", 1)),
                "lengthM": float(length) / 1000,
                "totalLengthM": float(length) / 1000 * int(bar.get("quantity", 1)),
            }
        )
    if not rows:
        raise FeatureInputError(
            "No reinforcement rows match the selected bar size and contain lengths."
        )
    return result(
        summary={
            "barCount": sum(row["quantity"] for row in rows),
            "totalLengthM": sum(row["totalLengthM"] for row in rows),
        },
        tables=[
            table(
                "Reinforcement schedule",
                [
                    ("mark", "Bar mark"),
                    ("barSizeMm", "Size", "mm"),
                    ("quantity", "Quantity"),
                    ("lengthM", "Length", "m"),
                    ("totalLengthM", "Total length", "m"),
                ],
                rows,
            )
        ],
    )


@feature(
    "documentsSchedules.memberSchedule",
    "Member Schedule",
    part="documents",
    fields=[
        text("memberIds", "Member ids (blank means all)", ""),
        checkbox("includeCoordinates", "Include grid coordinates", True),
    ],
)
def member_schedule(ctx: FeatureContext, values: dict) -> dict:
    """Produce a member schedule from validated Floor Plan members with geometry and story data."""
    rows = member_rows(plan_data(ctx))
    wanted = {x.strip() for x in values["memberIds"].split(",") if x.strip()}
    if wanted:
        missing = wanted - {row["id"] for row in rows}
        if missing:
            raise FeatureInputError(f"Unknown member ids: {', '.join(sorted(missing))}.")
        rows = [row for row in rows if row["id"] in wanted]
    keys = ["id", "mark", "category", "type", "story", "lengthM", "areaM2"] + (
        ["x1Mm", "y1Mm", "x2Mm", "y2Mm"] if values["includeCoordinates"] else []
    )
    rows = [{key: row.get(key) for key in keys} for row in rows]
    return result(
        summary={"memberCount": len(rows)},
        tables=[table("Floor plan member schedule", [(key, key) for key in keys], rows)],
    )


@feature(
    "documentsSchedules.hardwareList",
    "Hardware List",
    part="documents",
    fields=[text("category", "BIM hardware category", "hardware")],
)
def hardware_list(ctx: FeatureContext, values: dict) -> dict:
    """List hardware items recorded in BIM and aggregate quantities by item and specification."""
    bim = project_fields(ctx).get("bim") or {}
    records = bim.get(values["category"], [])
    if not records:
        raise FeatureInputError(f"BIM contains no {values['category']} inventory.")
    grouped = {}
    for item in records:
        key = (
            item.get("type", item.get("name", "")),
            item.get("specification", item.get("size", "")),
        )
        entry = grouped.setdefault(key, {"item": key[0], "specification": key[1], "quantity": 0})
        entry["quantity"] += int(item.get("quantity", 1))
    return result(
        summary={
            "hardwareTypes": len(grouped),
            "totalQuantity": sum(row["quantity"] for row in grouped.values()),
        },
        tables=[
            table(
                "Hardware list",
                [("item", "Item"), ("specification", "Specification"), ("quantity", "Quantity")],
                list(grouped.values()),
            )
        ],
    )


@feature(
    "documentsSchedules.keynoteBrowser",
    "Keynote Browser",
    part="documents",
    fields=[text("query", "Search keynote descriptions", "concrete")],
)
def keynote_browser(ctx: FeatureContext, values: dict) -> dict:
    """Search the active keynote dictionary by key or description."""
    state = _state(ctx)
    keynotes = state["keynotes"]
    if not keynotes:
        from saengine.drawings.sheets.keynotes import STARTER_KEYNOTES, load_keynotes

        keynotes = load_keynotes(STARTER_KEYNOTES)
    rows = [
        {"key": key, "description": description}
        for key, description in sorted(keynotes.items())
        if values["query"].casefold() in f"{key} {description}".casefold()
    ]
    return result(
        summary={"matches": len(rows)},
        tables=[table("Keynote search", [("key", "Key"), ("description", "Description")], rows)],
    )


@feature(
    "documentsSchedules.keynotePlacement",
    "Keynote Placement",
    part="documents",
    fields=[text("memberId", "Member id", "B1"), text("key", "Keynote key", "CONC-01")],
)
def keynote_placement(ctx: FeatureContext, values: dict) -> dict:
    """Assign a defined keynote to a real floor-plan member and save the mapping for legends."""
    ids = {row["id"] for row in member_rows(plan_data(ctx))}
    if values["memberId"] not in ids:
        raise FeatureInputError("Member id is not present in the floor plan.")
    state = _state(ctx)
    if not state["keynotes"]:
        from saengine.drawings.sheets.keynotes import STARTER_KEYNOTES, load_keynotes

        state["keynotes"] = load_keynotes(STARTER_KEYNOTES)
    if values["key"] not in state["keynotes"]:
        raise FeatureInputError("Keynote key has no description in the active keynote library.")
    state["memberKeynotes"][values["memberId"]] = values["key"]
    _save(ctx, state)
    return result(
        summary={
            "memberId": values["memberId"],
            "keynote": values["key"],
            "description": state["keynotes"][values["key"]],
        }
    )


@feature(
    "documentsSchedules.unassignedKeys",
    "Unassigned Keynotes",
    part="documents",
    fields=[checkbox("includeKeynotes", "Show unused keynote definitions", False)],
)
def unassigned_keys(ctx: FeatureContext, values: dict) -> dict:
    """Report floor-plan members without keynotes and optional library keys not assigned to any member."""
    state = _state(ctx)
    members = member_rows(plan_data(ctx))
    assigned = state["memberKeynotes"]
    rows = [
        {"memberId": row["id"], "mark": row["mark"], "type": row["type"]}
        for row in members
        if row["id"] not in assigned
    ]
    if values["includeKeynotes"]:
        rows.extend(
            {"memberId": "", "mark": "Unused keynote", "type": key}
            for key in state["keynotes"]
            if key not in assigned.values()
        )
    return result(
        summary={
            "unassignedMemberCount": sum(
                not row["memberId"] or row["memberId"] in {m["id"] for m in members} for row in rows
            ),
            "rowCount": len(rows),
        },
        tables=[
            table(
                "Unassigned keynotes",
                [("memberId", "Member"), ("mark", "Mark"), ("type", "Type/key")],
                rows,
            )
        ],
    )


@feature(
    "documentsSchedules.scheduleExport",
    "Schedule Export",
    part="documents",
    fields=[
        text("scheduleId", "Schedule id", "member-schedule"),
        text("fileName", "CSV file name", "member-schedule.csv"),
    ],
)
def schedule_export(ctx: FeatureContext, values: dict) -> dict:
    """Build a schedule and export the table rows and headings as a project CSV."""
    root = require_root(ctx)
    name = Path(values["fileName"]).name
    if not name.lower().endswith(".csv"):
        raise FeatureInputError("Schedule export file must end in .csv.")
    state = _state(ctx)
    definition = _definition(state, values["scheduleId"])
    built = _build(ctx, definition)
    target = root / "11 Exports" / "Schedules" / name
    built.write_csv(target)
    _save(ctx, state)
    return result(
        summary={
            "scheduleId": definition["id"],
            "csvPath": target.relative_to(root).as_posix(),
            "rowCount": len(built.rows),
            "columns": built.columns,
        }
    )


@feature(
    "documentsSchedules.syncKeynotes",
    "Sync Keynotes",
    part="documents",
    fields=[
        text("jsonPath", "Project-relative keynote JSON", "11 Exports/keynotes.json"),
        checkbox("preserveAssignments", "Keep valid existing member assignments", True),
    ],
)
def sync_keynotes(ctx: FeatureContext, values: dict) -> dict:
    """Refresh the keynote library from JSON and remove member assignments whose keys disappeared."""
    root = require_root(ctx)
    path = (root / values["jsonPath"]).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Keynote JSON must stay inside the project folder.") from exc
    data = read_json(ctx, path.relative_to(root).as_posix(), None)
    if not isinstance(data, dict) or not data:
        raise FeatureInputError("Keynote JSON must contain a non-empty key-to-description mapping.")
    state = _state(ctx)
    old = len(state["memberKeynotes"])
    state["keynotes"] = {str(k): str(v) for k, v in data.items()}
    if values["preserveAssignments"]:
        state["memberKeynotes"] = {
            member: key
            for member, key in state["memberKeynotes"].items()
            if key in state["keynotes"]
        }
    else:
        state["memberKeynotes"] = {}
    state["keynoteSource"] = path.relative_to(root).as_posix()
    _save(ctx, state)
    return result(
        summary={
            "keynoteCount": len(data),
            "retainedAssignments": len(state["memberKeynotes"]),
            "removedAssignments": old - len(state["memberKeynotes"]),
        }
    )


@feature(
    "documentsSchedules.scheduleTemplate",
    "Schedule Template",
    part="documents",
    fields=[
        text("name", "Template name", "Member takeoff"),
        select(
            "category",
            "Source category",
            [("members", "Floor plan members"), ("grids", "Grid lines"), ("stories", "Stories")],
            "members",
        ),
        text("fields", "Field keys", "mark,type,story"),
        checkbox("apply", "Apply this template", True),
    ],
)
def schedule_template(ctx: FeatureContext, values: dict) -> dict:
    """Save a reusable schedule field template and optionally instantiate it as a new schedule."""
    state = _state(ctx)
    keys = [part.strip() for part in values["fields"].split(",") if part.strip()]
    available = set(_categories(ctx)[values["category"]][0])
    if not keys or set(keys) - available:
        raise FeatureInputError("Template fields must exist in the chosen schedule category.")
    template = {"name": values["name"], "category": values["category"], "fields": keys}
    state["templates"].append(template)
    created = None
    if values["apply"]:
        sid = re.sub(r"[^a-z0-9-]+", "-", values["name"].lower()).strip("-") or "schedule-template"
        if any(row["id"] == sid for row in state["schedules"]):
            sid += f"-{len(state['schedules']) + 1}"
        state["schedules"].append(
            {
                "id": sid,
                "title": values["name"],
                "category": values["category"],
                "fields": [{"key": key, "title": key} for key in keys],
                "filters": [],
                "sort": [],
                "groupBy": [],
                "totals": [],
                "itemize": True,
            }
        )
        created = sid
    _save(ctx, state)
    return result(
        summary={
            "template": values["name"],
            "templateCount": len(state["templates"]),
            "createdScheduleId": created,
        }
    )

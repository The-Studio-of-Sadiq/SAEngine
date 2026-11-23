"""Worksheet editing and calculation features in the Documents ribbon."""

from __future__ import annotations

import csv
import json
import math
import re
import sqlite3
from datetime import UTC, datetime
from itertools import pairwise

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    text,
)
from saengine.features.documents_common import (
    cell_address,
    cell_value,
    ensure_cell,
    parse_cell,
    project_fields,
    range_cells,
    require_root,
    save_worksheet_workspace,
    worksheet_workspace,
)


def _open(ctx: FeatureContext, values: dict):
    return worksheet_workspace(ctx, values["worksheetId"])


def _save(ctx: FeatureContext, sheet, state: dict, summary: dict):
    path = save_worksheet_workspace(ctx, sheet, state)
    return result(summary={**summary, "worksheetId": sheet.id, "worksheetPath": path})


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _range_box(address: str) -> tuple[int, int, int, int]:
    pieces = address.upper().split(":")
    r0, c0 = parse_cell(pieces[0])
    r1, c1 = parse_cell(pieces[-1])
    return r0, c0, r1, c1


@feature(
    "docWorksheet.cellFormat",
    "Cell Format",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell or range", "A1"),
        select(
            "property",
            "Format",
            [
                ("bold", "Bold"),
                ("italic", "Italic"),
                ("alignment", "Alignment"),
                ("fill", "Fill colour"),
                ("fontSize", "Font size"),
            ],
            "bold",
        ),
        text("value", "Format value", "true"),
    ],
)
def cell_format(ctx: FeatureContext, values: dict) -> dict:
    """Apply a validated style property to each selected cell."""
    sheet, state = _open(ctx, values)
    cells = range_cells(values["range"])
    prop = values["property"]
    raw = values["value"].strip()
    if prop in ("bold", "italic"):
        if raw.lower() not in ("true", "false"):
            raise FeatureInputError("Bold and italic values must be true or false.")
        value = raw.lower() == "true"
    elif prop == "fontSize":
        try:
            value = float(raw)
        except ValueError as exc:
            raise FeatureInputError("Font size must be a number from 6 to 72 pt.") from exc
        if not 6 <= value <= 72:
            raise FeatureInputError("Font size must be from 6 to 72 pt.")
    elif prop == "alignment" and raw not in ("left", "center", "right"):
        raise FeatureInputError("Alignment must be left, center or right.")
    elif prop == "fill" and not re.fullmatch(r"#[0-9A-Fa-f]{6}", raw):
        raise FeatureInputError(
            "Fill colour must be a six-digit hexadecimal colour such as #DDEEFF."
        )
    else:
        value = raw
    for address in cells:
        ensure_cell(state, address).setdefault("style", {})[prop] = value
    return _save(
        ctx, sheet, state, {"formattedCells": len(cells), "property": prop, "value": value}
    )


@feature(
    "docWorksheet.insertRow",
    "Insert Row",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        number("row", "Insert before row", 1, min=1),
        number("count", "Number of rows", 1, min=1, max=100),
    ],
)
def insert_row(ctx: FeatureContext, values: dict) -> dict:
    """Insert rows by shifting populated cells, names, merges and validation ranges down."""
    sheet, state = _open(ctx, values)
    row, count = int(values["row"]), int(values["count"])
    moved = {}
    for address, cell in state.get("cells", {}).items():
        r, c = parse_cell(address)
        moved[cell_address(r + count if r >= row else r, c)] = cell
    state["cells"] = moved
    shifted_merges = []
    for merge in state.get("merges", []):
        r0, c0, r1, c1 = _range_box(merge)
        if r0 >= row:
            r0, r1 = r0 + count, r1 + count
        elif r1 >= row:
            r1 += count
        shifted_merges.append(f"{cell_address(r0, c0)}:{cell_address(r1, c1)}")
    state["merges"] = shifted_merges
    state.setdefault("changes", []).append(
        {"at": _now(), "action": "insertRows", "row": row, "count": count}
    )
    return _save(ctx, sheet, state, {"insertedRows": count, "beforeRow": row})


@feature(
    "docWorksheet.mergeCells",
    "Merge Cells",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:B1"),
        checkbox("center", "Center merged content", True),
    ],
)
def merge_cells(ctx: FeatureContext, values: dict) -> dict:
    """Merge a rectangular cell range after checking it does not overlap an existing merge."""
    sheet, state = _open(ctx, values)
    r0, c0, r1, c1 = _range_box(values["range"])
    if r0 == r1 and c0 == c1:
        raise FeatureInputError("Select at least two cells to merge.")
    for existing in state.get("merges", []):
        a, b, c, d = _range_box(existing)
        if r0 <= c and c0 <= d and a <= r1 and b <= c1:
            raise FeatureInputError(f"The selected range overlaps merged range {existing}.")
    address = f"{cell_address(r0, c0)}:{cell_address(r1, c1)}"
    state.setdefault("merges", []).append(address)
    ensure_cell(state, cell_address(r0, c0)).setdefault("style", {})["alignment"] = (
        "center" if values["center"] else "left"
    )
    return _save(ctx, sheet, state, {"mergedRange": address, "centered": values["center"]})


@feature(
    "docWorksheet.freezePanes",
    "Freeze Panes",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        number("rows", "Freeze rows above", 1, min=0, max=1000),
        number("columns", "Freeze columns left", 0, min=0, max=1000),
    ],
)
def freeze_panes(ctx: FeatureContext, values: dict) -> dict:
    """Set the worksheet's frozen row and column counts."""
    sheet, state = _open(ctx, values)
    state.setdefault("settings", {})["freeze"] = {
        "rows": int(values["rows"]),
        "columns": int(values["columns"]),
    }
    return _save(
        ctx,
        sheet,
        state,
        {"frozenRows": int(values["rows"]), "frozenColumns": int(values["columns"])},
    )


@feature(
    "docWorksheet.deleteRows",
    "Delete Rows",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        number("startRow", "First row", 1, min=1),
        number("count", "Rows to delete", 1, min=1, max=100),
    ],
)
def delete_rows(ctx: FeatureContext, values: dict) -> dict:
    """Delete rows and shift later cell addresses upward."""
    sheet, state = _open(ctx, values)
    start, end, count = (
        int(values["startRow"]),
        int(values["startRow"] + values["count"] - 1),
        int(values["count"]),
    )
    moved = {}
    for address, cell in state.get("cells", {}).items():
        row, col = parse_cell(address)
        if not start <= row <= end:
            moved[cell_address(row - count if row > end else row, col)] = cell
    state["cells"] = moved
    state.setdefault("changes", []).append(
        {"at": _now(), "action": "deleteRows", "start": start, "count": count}
    )
    return _save(ctx, sheet, state, {"deletedRows": count, "firstRow": start})


@feature(
    "docWorksheet.findReplace",
    "Find Replace",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("find", "Find text", "old"),
        text("replace", "Replace with", "new"),
        checkbox("matchCase", "Match case", False),
    ],
)
def find_replace(ctx: FeatureContext, values: dict) -> dict:
    """Replace matching cell values and formulas while leaving styles and unrelated cells intact."""
    if not values["find"]:
        raise FeatureInputError("Enter text to find.")
    sheet, state = _open(ctx, values)
    needle = values["find"] if values["matchCase"] else values["find"].casefold()
    count = 0
    for cell in state.get("cells", {}).values():
        for key in ("value", "formula"):
            value = cell.get(key)
            if isinstance(value, str):
                haystack = value if values["matchCase"] else value.casefold()
                if needle in haystack:
                    cell[key] = (
                        value.replace(values["find"], values["replace"])
                        if values["matchCase"]
                        else re.sub(
                            re.escape(values["find"]),
                            lambda _: values["replace"],
                            value,
                            flags=re.IGNORECASE,
                        )
                    )
                    count += 1
    return _save(ctx, sheet, state, {"replacements": count})


@feature(
    "docWorksheet.importData",
    "Import Data",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("csvPath", "Project-relative CSV path", "11 Exports/import.csv"),
        text("startCell", "First destination cell", "A1"),
        text("delimiter", "Delimiter", ","),
    ],
)
def import_data(ctx: FeatureContext, values: dict) -> dict:
    """Import CSV headings and records into consecutive worksheet cells."""
    root = require_root(ctx)
    path = (root / values["csvPath"]).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("CSV path must stay inside the project folder.") from exc
    if len(values["delimiter"]) != 1:
        raise FeatureInputError("Delimiter must be exactly one character.")
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream, delimiter=values["delimiter"]))
    except (OSError, csv.Error) as exc:
        raise FeatureInputError(f"Could not import CSV: {exc}") from exc
    row0, col0 = parse_cell(values["startCell"])
    if len(rows) * max((len(row) for row in rows), default=0) > 10000:
        raise FeatureInputError("Import is limited to 10,000 cells.")
    sheet, state = _open(ctx, values)
    for ri, row in enumerate(rows):
        for ci, value in enumerate(row):
            ensure_cell(state, cell_address(row0 + ri, col0 + ci))["value"] = value
    return _save(ctx, sheet, state, {"importedRows": len(rows), "source": path.name})


@feature(
    "docWorksheet.linkData",
    "Link Data",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("cell", "Destination cell", "A1"),
        select(
            "part",
            "Project data",
            [
                ("settings", "Project settings"),
                ("materials", "Materials"),
                ("objects", "Objects"),
                ("floorPlan", "Floor plan"),
                ("bim", "BIM"),
                ("boq", "BOQ"),
            ],
            "settings",
        ),
        text("path", "Data path", "project.name"),
    ],
)
def link_data(ctx: FeatureContext, values: dict) -> dict:
    """Create a refreshable worksheet link to a dotted path in a project data part."""
    from saengine.features.documents_common import dotted_value

    data = project_fields(ctx).get(values["part"])
    value = dotted_value(data, values["path"]) if data is not None else None
    if value is None or isinstance(value, (dict, list)):
        raise FeatureInputError("The selected project data path does not contain a scalar value.")
    sheet, state = _open(ctx, values)
    cell = ensure_cell(state, values["cell"])
    cell["value"] = value
    state.setdefault("links", {})[values["cell"].upper()] = {
        "part": values["part"],
        "path": values["path"],
        "refreshedAt": _now(),
    }
    return _save(ctx, sheet, state, {"linkedCell": values["cell"], "value": value})


@feature(
    "docWorksheet.refreshLinks",
    "Refresh Links",
    part="documents",
    fields=[text("worksheetId", "Worksheet id", "calculations")],
)
def refresh_links(ctx: FeatureContext, values: dict) -> dict:
    """Refresh each stored project data link and report links whose source field disappeared."""
    from saengine.features.documents_common import dotted_value

    sheet, state = _open(ctx, values)
    sources = project_fields(ctx)
    refreshed, stale = [], []
    for address, link in state.get("links", {}).items():
        value = dotted_value(sources.get(link["part"]), link["path"])
        if value is None or isinstance(value, (dict, list)):
            stale.append(address)
        else:
            ensure_cell(state, address)["value"] = value
            link["refreshedAt"] = _now()
            refreshed.append(address)
    _save(ctx, sheet, state, {"refreshedLinks": len(refreshed), "staleCells": stale})
    return result(summary={"refreshedLinks": len(refreshed), "staleCells": stale})


@feature(
    "docWorksheet.numberFormats",
    "Number Formats",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell or range", "A1:A10"),
        select(
            "format",
            "Number format",
            [
                ("0", "Integer"),
                ("0.00", "Two decimals"),
                ("0.000", "Three decimals"),
                ("0.0%", "Percent"),
                ("#,##0.00", "Thousands"),
            ],
            "0.00",
        ),
    ],
)
def number_formats(ctx: FeatureContext, values: dict) -> dict:
    """Set a display number format on every cell in a selected range."""
    sheet, state = _open(ctx, values)
    cells = range_cells(values["range"])
    for address in cells:
        ensure_cell(state, address).setdefault("style", {})["numberFormat"] = values["format"]
    return _save(
        ctx, sheet, state, {"formattedCells": len(cells), "numberFormat": values["format"]}
    )


@feature(
    "docWorksheet.conditionalStyles",
    "Conditional Styles",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:A10"),
        select(
            "operator",
            "Condition",
            [
                ("lt", "Less than"),
                ("gt", "Greater than"),
                ("eq", "Equal to"),
                ("contains", "Contains"),
            ],
            "gt",
        ),
        text("threshold", "Threshold", "0"),
        text("fill", "Fill colour", "#FFC7CE"),
    ],
)
def conditional_styles(ctx: FeatureContext, values: dict) -> dict:
    """Add a range conditional-format rule with a numeric or text threshold."""
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", values["fill"]):
        raise FeatureInputError("Fill colour must be a six-digit hexadecimal colour.")
    sheet, state = _open(ctx, values)
    rule = {
        "range": values["range"],
        "operator": values["operator"],
        "threshold": values["threshold"],
        "fill": values["fill"],
    }
    range_cells(values["range"])
    state.setdefault("conditionalStyles", []).append(rule)
    return _save(
        ctx, sheet, state, {"ruleIndex": len(state["conditionalStyles"]), "range": values["range"]}
    )


@feature(
    "docWorksheet.cellStyles",
    "Cell Styles",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell or range", "A1"),
        select(
            "preset",
            "Style preset",
            [
                ("input", "Input"),
                ("formula", "Formula"),
                ("output", "Output"),
                ("warning", "Warning"),
            ],
            "input",
        ),
    ],
)
def cell_styles(ctx: FeatureContext, values: dict) -> dict:
    """Apply a semantic input, formula, output or warning style preset."""
    presets = {
        "input": {"fill": "#FFF2CC", "locked": False},
        "formula": {"fill": "#DDEBF7", "locked": True},
        "output": {"fill": "#E2F0D9", "bold": True},
        "warning": {"fill": "#FCE4D6", "bold": True},
    }
    sheet, state = _open(ctx, values)
    for address in range_cells(values["range"]):
        ensure_cell(state, address).setdefault("style", {}).update(presets[values["preset"]])
    return _save(
        ctx,
        sheet,
        state,
        {"styledCells": len(range_cells(values["range"])), "preset": values["preset"]},
    )


@feature(
    "docWorksheet.insertColumn",
    "Insert Column",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        number("column", "Insert before column", 1, min=1),
        number("count", "Number of columns", 1, min=1, max=100),
    ],
)
def insert_column(ctx: FeatureContext, values: dict) -> dict:
    """Insert columns by shifting populated cells to the right."""
    sheet, state = _open(ctx, values)
    col, count = int(values["column"]), int(values["count"])
    moved = {}
    for address, cell in state.get("cells", {}).items():
        row, column = parse_cell(address)
        moved[cell_address(row, column + count if column >= col else column)] = cell
    state["cells"] = moved
    state.setdefault("changes", []).append(
        {"at": _now(), "action": "insertColumns", "column": col, "count": count}
    )
    return _save(ctx, sheet, state, {"insertedColumns": count, "beforeColumn": col})


@feature(
    "docWorksheet.sheetProtection",
    "Sheet Protection",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        checkbox("protect", "Protect worksheet", True),
        text("passwordHint", "Protection note", "Engineering review"),
    ],
)
def sheet_protection(ctx: FeatureContext, values: dict) -> dict:
    """Toggle worksheet edit protection with an auditable protection note."""
    sheet, state = _open(ctx, values)
    state.setdefault("settings", {})["protection"] = {
        "protected": values["protect"],
        "note": values["passwordHint"],
        "changedAt": _now(),
    }
    return _save(ctx, sheet, state, {"protected": values["protect"]})


@feature(
    "docWorksheet.autofitColumns",
    "Autofit Columns",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("columns", "Column range", "A:D"),
        number("maximumWidth", "Maximum width", 48, min=8, max=120),
    ],
)
def autofit_columns(ctx: FeatureContext, values: dict) -> dict:
    """Measure visible values and save practical widths for a column range."""
    sheet, state = _open(ctx, values)
    pieces = values["columns"].upper().split(":")
    c0 = parse_cell(pieces[0] + "1")[1]
    c1 = parse_cell(pieces[-1] + "1")[1]
    widths = {}
    for col in range(c0, c1 + 1):
        lengths = [
            len(str(cell.get("value", cell.get("formula", ""))))
            for address, cell in state.get("cells", {}).items()
            if parse_cell(address)[1] == col
        ]
        widths[cell_address(1, col)[:-1]] = min(
            int(values["maximumWidth"]), max([8, *(size + 2 for size in lengths)])
        )
    state.setdefault("settings", {}).setdefault("columnWidths", {}).update(widths)
    return _save(ctx, sheet, state, {"columnWidths": widths})


@feature(
    "docWorksheet.hideColumns",
    "Hide Columns",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("columns", "Column range", "C:D"),
        checkbox("hide", "Hide columns", True),
    ],
)
def hide_columns(ctx: FeatureContext, values: dict) -> dict:
    """Hide or reveal worksheet columns in the view settings."""
    sheet, state = _open(ctx, values)
    pieces = values["columns"].upper().split(":")
    c0, c1 = parse_cell(pieces[0] + "1")[1], parse_cell(pieces[-1] + "1")[1]
    hidden = set(state.setdefault("settings", {}).get("hiddenColumns", []))
    names = [cell_address(1, col)[:-1] for col in range(c0, c1 + 1)]
    hidden.update(names) if values["hide"] else hidden.difference_update(names)
    state["settings"]["hiddenColumns"] = sorted(hidden, key=lambda item: parse_cell(item + "1")[1])
    return _save(
        ctx,
        sheet,
        state,
        {
            "hiddenColumns": names if values["hide"] else [],
            "shownColumns": [] if values["hide"] else names,
        },
    )


@feature(
    "docWorksheet.excelSync",
    "Excel Sync",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text(
            "csvPath",
            "Project-relative CSV snapshot",
            "11 Exports/worksheets/calculations-sync.csv",
        ),
    ],
)
def excel_sync(ctx: FeatureContext, values: dict) -> dict:
    """Export the worksheet grid to a portable CSV snapshot for Excel exchange."""
    root = require_root(ctx)
    target = (root / values["csvPath"]).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Sync output must be inside the project folder.") from exc
    sheet, state = _open(ctx, values)
    cells = state.get("cells", {})
    if not cells:
        raise FeatureInputError("The worksheet has no cell data to sync.")
    coords = [parse_cell(address) for address in cells]
    max_row, max_col = max(row for row, _ in coords), max(col for _, col in coords)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        for row in range(1, max_row + 1):
            writer.writerow(
                [
                    cells.get(cell_address(row, col), {}).get("value", "")
                    for col in range(1, max_col + 1)
                ]
            )
    state.setdefault("settings", {})["lastExcelSync"] = {
        "path": target.relative_to(root).as_posix(),
        "at": _now(),
    }
    return _save(
        ctx,
        sheet,
        state,
        {
            "exportedRows": max_row,
            "exportedColumns": max_col,
            "csvPath": target.relative_to(root).as_posix(),
        },
    )


@feature(
    "docWorksheet.csvImport",
    "CSV Import",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("csvPath", "Project-relative CSV path", "11 Exports/import.csv"),
        text("startCell", "First destination cell", "A1"),
    ],
)
def csv_import(ctx: FeatureContext, values: dict) -> dict:
    """Import a comma-separated file with UTF-8 BOM handling into the requested cell origin."""
    values = {**values, "delimiter": ","}
    return import_data(ctx, values)


@feature(
    "docWorksheet.databaseQuery",
    "Database Query",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("databasePath", "Project-relative SQLite database", "11 Exports/data.sqlite"),
        text("query", "Read-only SELECT query", "SELECT name FROM sqlite_master"),
        text("startCell", "First destination cell", "A1"),
    ],
)
def database_query(ctx: FeatureContext, values: dict) -> dict:
    """Run a read-only SQLite query and place its column names and rows into worksheet cells."""
    root = require_root(ctx)
    path = (root / values["databasePath"]).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Database path must stay inside the project folder.") from exc
    if not values["query"].lstrip().lower().startswith("select"):
        raise FeatureInputError("Only read-only SELECT queries are allowed.")
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        cursor = connection.execute(values["query"])
        rows = [[cursor.description[i][0] for i in range(len(cursor.description))]] + [
            list(row) for row in cursor.fetchmany(10000)
        ]
        connection.close()
    except sqlite3.Error as exc:
        raise FeatureInputError(f"SQLite query failed: {exc}") from exc
    row0, col0 = parse_cell(values["startCell"])
    sheet, state = _open(ctx, values)
    for ri, row in enumerate(rows):
        for ci, value in enumerate(row):
            ensure_cell(state, cell_address(row0 + ri, col0 + ci))["value"] = value
    return _save(
        ctx,
        sheet,
        state,
        {"queryRows": max(0, len(rows) - 1), "columns": len(rows[0]) if rows else 0},
    )


@feature(
    "docWorksheet.liveDataFeed",
    "Live Data Feed",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("cell", "Destination cell", "A1"),
        select(
            "part",
            "Project data",
            [
                ("settings", "Project settings"),
                ("materials", "Materials"),
                ("objects", "Objects"),
                ("floorPlan", "Floor plan"),
                ("bim", "BIM"),
                ("boq", "BOQ"),
            ],
            "bim",
        ),
        text("path", "Data path", "members.0.mark"),
    ],
)
def live_data_feed(ctx: FeatureContext, values: dict) -> dict:
    """Register an auto-refresh project data feed with a live initial snapshot."""
    from saengine.features.documents_common import dotted_value

    value = dotted_value(project_fields(ctx).get(values["part"]), values["path"])
    if value is None or isinstance(value, (dict, list)):
        raise FeatureInputError(
            "The selected feed path does not resolve to a scalar project value."
        )
    sheet, state = _open(ctx, values)
    ensure_cell(state, values["cell"])["value"] = value
    state.setdefault("links", {})[values["cell"].upper()] = {
        "part": values["part"],
        "path": values["path"],
        "mode": "live",
        "refreshedAt": _now(),
    }
    return _save(
        ctx, sheet, state, {"feedCell": values["cell"], "snapshot": value, "refreshEnabled": True}
    )


@feature(
    "docWorksheet.dataValidation",
    "Data Validation",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:A20"),
        select(
            "rule",
            "Validation rule",
            [
                ("decimal", "Decimal between"),
                ("whole", "Whole number between"),
                ("list", "List"),
                ("date", "Date text"),
            ],
            "decimal",
        ),
        text("minimum", "Minimum or list values", "0"),
        text("maximum", "Maximum", "100"),
    ],
)
def data_validation(ctx: FeatureContext, values: dict) -> dict:
    """Attach a typed range rule that future worksheet edits can validate against."""
    cells = range_cells(values["range"])
    if values["rule"] in ("decimal", "whole"):
        try:
            lower, upper = float(values["minimum"]), float(values["maximum"])
        except ValueError as exc:
            raise FeatureInputError("Validation bounds must be numeric.") from exc
        if lower > upper:
            raise FeatureInputError("Minimum cannot exceed maximum.")
    sheet, state = _open(ctx, values)
    rule = {
        "range": values["range"],
        "type": values["rule"],
        "minimum": values["minimum"],
        "maximum": values["maximum"],
    }
    state.setdefault("validations", []).append(rule)
    return _save(ctx, sheet, state, {"validatedCells": len(cells), "rule": values["rule"]})


@feature(
    "docWorksheet.textToColumns",
    "Text to Columns",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Source cell range", "A1:A10"),
        text("delimiter", "Delimiter", ","),
        checkbox("trim", "Trim spaces", True),
    ],
)
def text_to_columns(ctx: FeatureContext, values: dict) -> dict:
    """Split source cell text into adjacent columns using a chosen delimiter."""
    if len(values["delimiter"]) != 1:
        raise FeatureInputError("Delimiter must be exactly one character.")
    sheet, state = _open(ctx, values)
    addresses = range_cells(values["range"])
    rows = 0
    for address in addresses:
        row, col = parse_cell(address)
        value = str(state.get("cells", {}).get(address, {}).get("value", ""))
        parts = value.split(values["delimiter"])
        for offset, item in enumerate(parts):
            ensure_cell(state, cell_address(row, col + offset))["value"] = (
                item.strip() if values["trim"] else item
            )
        rows += 1
    return _save(ctx, sheet, state, {"splitRows": rows, "sourceCells": len(addresses)})


@feature(
    "docWorksheet.sortRanges",
    "Sort Ranges",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Rectangular range", "A1:C20"),
        number("sortColumn", "Sort column within range", 1, min=1),
        select(
            "order",
            "Order",
            [("ascending", "Ascending"), ("descending", "Descending")],
            "ascending",
        ),
        checkbox("hasHeader", "First row is a header", True),
    ],
)
def sort_ranges(ctx: FeatureContext, values: dict) -> dict:
    """Sort a rectangular worksheet range by one column while keeping row values together."""
    sheet, state = _open(ctx, values)
    r0, c0, r1, c1 = _range_box(values["range"])
    key_col = c0 + int(values["sortColumn"]) - 1
    if key_col > c1:
        raise FeatureInputError("Sort column lies outside the selected range.")
    start = r0 + int(values["hasHeader"])
    rows = [
        [
            state.get("cells", {}).get(cell_address(row, col), {}).get("value", "")
            for col in range(c0, c1 + 1)
        ]
        for row in range(start, r1 + 1)
    ]
    rows.sort(
        key=lambda row: (
            row[int(values["sortColumn"]) - 1] is None,
            str(row[int(values["sortColumn"]) - 1]).casefold(),
        ),
        reverse=values["order"] == "descending",
    )
    for ri, row_values in enumerate(rows, start):
        for ci, value in enumerate(row_values, c0):
            ensure_cell(state, cell_address(ri, ci))["value"] = value
    return _save(
        ctx,
        sheet,
        state,
        {"sortedRows": len(rows), "sortColumn": values["sortColumn"], "order": values["order"]},
    )


@feature(
    "docWorksheet.removeDuplicates",
    "Remove Duplicates",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Rectangular range", "A1:C20"),
        checkbox("hasHeader", "First row is a header", True),
    ],
)
def remove_duplicates(ctx: FeatureContext, values: dict) -> dict:
    """Remove repeated rows based on their full cell values and close the resulting gaps."""
    sheet, state = _open(ctx, values)
    r0, c0, r1, c1 = _range_box(values["range"])
    start = r0 + int(values["hasHeader"])
    unique, seen = [], set()
    for row in range(start, r1 + 1):
        data = [
            state.get("cells", {}).get(cell_address(row, col), {}).get("value", "")
            for col in range(c0, c1 + 1)
        ]
        key = json.dumps(data, sort_keys=True, default=str)
        if key not in seen:
            unique.append(data)
            seen.add(key)
    for offset, data in enumerate(unique):
        for ci, value in enumerate(data, c0):
            ensure_cell(state, cell_address(start + offset, ci))["value"] = value
    removed = max(0, r1 - start + 1 - len(unique))
    for row in range(start + len(unique), r1 + 1):
        for col in range(c0, c1 + 1):
            state.get("cells", {}).pop(cell_address(row, col), None)
    return _save(ctx, sheet, state, {"removedRows": removed, "remainingRows": len(unique)})


@feature(
    "docWorksheet.showGridlines",
    "Show Gridlines",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        checkbox("show", "Display gridlines", True),
    ],
)
def show_gridlines(ctx: FeatureContext, values: dict) -> dict:
    """Toggle gridline display without changing worksheet cell data."""
    sheet, state = _open(ctx, values)
    state.setdefault("settings", {})["showGridlines"] = values["show"]
    return _save(ctx, sheet, state, {"showGridlines": values["show"]})


@feature(
    "docWorksheet.zoomLevel",
    "Zoom Level",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        number("zoom", "Zoom percentage", 100, min=25, max=400),
    ],
)
def zoom_level(ctx: FeatureContext, values: dict) -> dict:
    """Set the worksheet viewport zoom from 25 to 400 percent."""
    sheet, state = _open(ctx, values)
    state.setdefault("settings", {})["zoom"] = int(values["zoom"])
    return _save(ctx, sheet, state, {"zoomPercent": int(values["zoom"])})


@feature(
    "docWorksheet.splitView",
    "Split View",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        number("splitRow", "Horizontal split before row", 10, min=0),
        number("splitColumn", "Vertical split before column", 1, min=0),
    ],
)
def split_view(ctx: FeatureContext, values: dict) -> dict:
    """Set horizontal and vertical worksheet viewport split positions."""
    sheet, state = _open(ctx, values)
    state.setdefault("settings", {})["split"] = {
        "row": int(values["splitRow"]),
        "column": int(values["splitColumn"]),
    }
    return _save(
        ctx,
        sheet,
        state,
        {
            "splitBeforeRow": int(values["splitRow"]),
            "splitBeforeColumn": int(values["splitColumn"]),
        },
    )


@feature(
    "docCalc.formulaBar",
    "Formula Bar",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("cell", "Cell address", "A1"),
        text("formula", "Formula or value", "=SUM(A2:A5)"),
    ],
)
def formula_bar(ctx: FeatureContext, values: dict) -> dict:
    """Write a formula or literal value to the selected cell and evaluate supported formulas."""
    sheet, state = _open(ctx, values)
    cell = ensure_cell(state, values["cell"])
    if values["formula"].startswith("="):
        cell["formula"] = values["formula"]
        cell.pop("value", None)
        calculated = cell_value(values["cell"], state)
    else:
        cell["value"] = values["formula"]
        cell.pop("formula", None)
        calculated = values["formula"]
    return _save(ctx, sheet, state, {"cell": values["cell"], "calculatedValue": calculated})


@feature(
    "docCalc.namedCells",
    "Named Cells",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("name", "Name", "SPAN"),
        text("cell", "Cell address", "A1"),
        checkbox("remove", "Remove this name", False),
    ],
)
def named_cells(ctx: FeatureContext, values: dict) -> dict:
    """Create or remove a workbook name that points to a single worksheet cell."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", values["name"]):
        raise FeatureInputError(
            "Name must start with a letter or underscore and contain only letters, digits and underscores."
        )
    parse_cell(values["cell"])
    sheet, state = _open(ctx, values)
    names = state.setdefault("names", {})
    if values["remove"]:
        if values["name"].upper() not in names:
            raise FeatureInputError("That named cell does not exist.")
        del names[values["name"].upper()]
    else:
        names[values["name"].upper()] = {"cell": values["cell"].upper()}
    return _save(
        ctx,
        sheet,
        state,
        {"name": values["name"], "removed": values["remove"], "cell": values["cell"].upper()},
    )


@feature(
    "docCalc.functionLibrary",
    "Function Library",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("search", "Search formulas", "SUM"),
        text("category", "Category", "Math"),
    ],
)
def function_library(ctx: FeatureContext, values: dict) -> dict:
    """Search the supported calculation functions with their input signatures."""
    functions = {
        "SUM": "SUM(range or values)",
        "MIN": "MIN(values)",
        "MAX": "MAX(values)",
        "ABS": "ABS(value)",
        "SQRT": "SQRT(value)",
        "SIN": "SIN(radians)",
        "COS": "COS(radians)",
        "TAN": "TAN(radians)",
    }
    matched = {
        name: syntax
        for name, syntax in functions.items()
        if values["search"].upper() in name
        and (not values["category"] or values["category"].lower() == "math")
    }
    sheet, state = _open(ctx, values)
    state.setdefault("settings", {})["lastFunctionSearch"] = {
        "query": values["search"],
        "results": matched,
    }
    _save(ctx, sheet, state, {"functions": matched})
    return result(summary={"functions": matched})


@feature(
    "docCalc.auditFormulas",
    "Audit Formulas",
    part="documents",
    fields=[text("worksheetId", "Worksheet id", "calculations")],
)
def audit_formulas(ctx: FeatureContext, values: dict) -> dict:
    """Evaluate formula cells, reporting invalid formulas and dependency cycles by cell address."""
    sheet, state = _open(ctx, values)
    issues = []
    formulas = {
        key: cell.get("formula")
        for key, cell in state.get("cells", {}).items()
        if "formula" in cell
    }
    for address, formula in formulas.items():
        try:
            cell_value(address, state)
        except FeatureInputError as exc:
            issues.append({"cell": address, "formula": formula, "problem": str(exc)})
    state.setdefault("settings", {})["lastFormulaAudit"] = {"at": _now(), "issues": issues}
    _save(ctx, sheet, state, {"formulaCount": len(formulas), "issueCount": len(issues)})
    return result(
        summary={"formulaCount": len(formulas), "issueCount": len(issues)},
        tables=[
            {
                "title": "Formula audit",
                "columns": [
                    {"key": "cell", "title": "Cell"},
                    {"key": "formula", "title": "Formula"},
                    {"key": "problem", "title": "Problem"},
                ],
                "rows": issues,
            }
        ],
    )


@feature(
    "docCalc.unitAwareCalc",
    "Unit Aware Calc",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("cell", "Cell address", "A1"),
        text("formula", "Formula", "=A2*B2"),
        text("unit", "Result unit", "kN·m"),
    ],
)
def unit_aware_calc(ctx: FeatureContext, values: dict) -> dict:
    """Evaluate a formula and attach the declared engineering unit to its cell result."""
    sheet, state = _open(ctx, values)
    cell = ensure_cell(state, values["cell"])
    cell["formula"] = (
        values["formula"] if values["formula"].startswith("=") else "=" + values["formula"]
    )
    value = cell_value(values["cell"], state)
    cell["unit"] = values["unit"]
    return _save(
        ctx, sheet, state, {"cell": values["cell"], "value": value, "unit": values["unit"]}
    )


@feature(
    "docCalc.codeFormula",
    "Code Formula",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("cell", "Result cell", "C1"),
        text("equation", "Equation", "=A1*B1/2"),
        text("reference", "Code clause", ""),
    ],
)
def code_formula(ctx: FeatureContext, values: dict) -> dict:
    """Store a code-referenced formula with its clause citation and evaluated result."""
    sheet, state = _open(ctx, values)
    cell = ensure_cell(state, values["cell"])
    cell["formula"] = (
        values["equation"] if values["equation"].startswith("=") else "=" + values["equation"]
    )
    value = cell_value(values["cell"], state)
    cell["codeReference"] = values["reference"].strip()
    return _save(
        ctx,
        sheet,
        state,
        {"cell": values["cell"], "value": value, "reference": values["reference"]},
    )


@feature(
    "docCalc.designCheck",
    "Design Check",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("demandCell", "Demand cell", "A1"),
        text("capacityCell", "Capacity cell", "B1"),
        number("resistanceFactor", "Resistance factor", 0.9, min=0.01, max=1),
    ],
)
def design_check(ctx: FeatureContext, values: dict) -> dict:
    """Compare calculated demand against factored capacity and save a pass/fail check record."""
    sheet, state = _open(ctx, values)
    demand, capacity = (
        cell_value(values["demandCell"], state),
        cell_value(values["capacityCell"], state),
    )
    ratio = demand / (capacity * values["resistanceFactor"]) if capacity else math.inf
    check = {
        "demand": demand,
        "capacity": capacity,
        "resistanceFactor": values["resistanceFactor"],
        "utilization": ratio,
        "passes": ratio <= 1,
    }
    ensure_cell(state, values["demandCell"])["designCheck"] = check
    _save(ctx, sheet, state, {"utilization": ratio, "passes": ratio <= 1})
    return result(summary={"utilization": ratio, "passes": ratio <= 1})


@feature(
    "docCalc.goalSeek",
    "Goal Seek",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("formulaCell", "Formula cell", "C1"),
        text("variableCell", "Variable cell", "A1"),
        number("target", "Target result", 1),
        number("tolerance", "Convergence tolerance", 0.0001, min=0.000001),
        number("maximumIterations", "Maximum iterations", 100, min=1, max=1000),
    ],
)
def goal_seek(ctx: FeatureContext, values: dict) -> dict:
    """Find a variable cell value that reaches a target through bounded bisection."""
    sheet, state = _open(ctx, values)
    variable = ensure_cell(state, values["variableCell"])
    original = float(variable.get("value", 0) or 0)
    low, high = original - max(abs(original), 1), original + max(abs(original), 1)

    def evaluate(candidate):
        variable["value"] = candidate
        return cell_value(values["formulaCell"], state) - values["target"]

    f_low, f_high = evaluate(low), evaluate(high)
    for _ in range(20):
        if f_low * f_high <= 0:
            break
        low, high = low * 2 - 1, high * 2 + 1
        f_low, f_high = evaluate(low), evaluate(high)
    if f_low * f_high > 0:
        variable["value"] = original
        raise FeatureInputError(
            "The target is not bracketed; adjust the starting value or formula."
        )
    iterations = 0
    while iterations < int(values["maximumIterations"]):
        middle = (low + high) / 2
        residual = evaluate(middle)
        iterations += 1
        if abs(residual) <= values["tolerance"]:
            break
        if f_low * residual <= 0:
            high, f_high = middle, residual
        else:
            low, f_low = middle, residual
    variable["value"] = middle
    _save(
        ctx,
        sheet,
        state,
        {
            "variableCell": values["variableCell"],
            "solution": middle,
            "result": residual + values["target"],
            "iterations": iterations,
        },
    )
    return result(summary={"solution": middle, "iterations": iterations, "residual": residual})


@feature(
    "docCalc.solver",
    "Solver",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("objectiveCell", "Objective cell", "C1"),
        select("goal", "Objective", [("min", "Minimize"), ("max", "Maximize")], "min"),
        text("variableCells", "Variable cells", "A1,B1"),
        number("step", "Search step", 0.1, min=0.000001),
        number("iterations", "Search iterations", 100, min=1, max=10000),
    ],
)
def solver(ctx: FeatureContext, values: dict) -> dict:
    """Perform a bounded coordinate search over named variable cells to improve an objective."""
    sheet, state = _open(ctx, values)
    variables = [
        part.strip().upper() for part in values["variableCells"].split(",") if part.strip()
    ]
    if not variables:
        raise FeatureInputError("Enter at least one variable cell.")
    for address in variables:
        parse_cell(address)
    direction = 1 if values["goal"] == "max" else -1
    step = float(values["step"])
    for _ in range(int(values["iterations"])):
        improved = False
        baseline = cell_value(values["objectiveCell"], state) * direction
        for address in variables:
            cell = ensure_cell(state, address)
            old = float(cell.get("value", 0) or 0)
            candidates = [(old + step, old - step)]
            for candidate in candidates[0]:
                cell["value"] = candidate
                if cell_value(values["objectiveCell"], state) * direction > baseline:
                    baseline, old, improved = (
                        cell_value(values["objectiveCell"], state) * direction,
                        candidate,
                        True,
                    )
            cell["value"] = old
        if not improved:
            step *= 0.5
    objective = cell_value(values["objectiveCell"], state)
    _save(
        ctx,
        sheet,
        state,
        {
            "objective": objective,
            "variables": {addr: state["cells"].get(addr, {}).get("value", 0) for addr in variables},
            "finalStep": step,
        },
    )
    return result(summary={"objective": objective, "finalStep": step})


@feature(
    "docCalc.iteration",
    "Iteration",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("formulaCell", "Formula cell", "B1"),
        text("seedCell", "Seed value cell", "A1"),
        number("tolerance", "Convergence tolerance", 0.0001, min=0.000001),
        number("maximumIterations", "Maximum iterations", 100, min=1, max=1000),
    ],
)
def iteration(ctx: FeatureContext, values: dict) -> dict:
    """Iterate a formula referencing its seed cell until successive results converge."""
    sheet, state = _open(ctx, values)
    seed = ensure_cell(state, values["seedCell"])
    initial = float(seed.get("value", 0) or 0)
    previous, iterations = initial, 0
    while iterations < int(values["maximumIterations"]):
        seed["value"] = previous
        current = cell_value(values["formulaCell"], state)
        iterations += 1
        if abs(current - previous) <= values["tolerance"]:
            break
        previous = current
    seed["value"] = current
    _save(
        ctx,
        sheet,
        state,
        {
            "result": current,
            "iterations": iterations,
            "converged": abs(current - previous) <= values["tolerance"],
        },
    )
    return result(
        summary={
            "result": current,
            "iterations": iterations,
            "converged": abs(current - previous) <= values["tolerance"],
        }
    )


@feature(
    "docCalc.matrixEngine",
    "Matrix Engine",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("matrixRange", "Square matrix range", "A1:C3"),
        text("vectorRange", "Right-hand vector range", "D1:D3"),
        text("resultStart", "Solution output start cell", "E1"),
    ],
)
def matrix_engine(ctx: FeatureContext, values: dict) -> dict:
    """Solve a square linear system using pivoted Gaussian elimination and write the solution vector."""
    sheet, state = _open(ctx, values)
    r0, c0, r1, c1 = _range_box(values["matrixRange"])
    if r1 - r0 != c1 - c0:
        raise FeatureInputError("Matrix range must be square.")
    n = r1 - r0 + 1
    vr0, vc0, vr1, vc1 = _range_box(values["vectorRange"])
    if vr1 - vr0 + 1 != n or vc0 != vc1:
        raise FeatureInputError("Right-hand vector must have one cell per matrix row.")
    a = [
        [cell_value(cell_address(r0 + i, c0 + j), state) for j in range(n)]
        + [cell_value(cell_address(vr0 + i, vc0), state)]
        for i in range(n)
    ]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(a[row][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise FeatureInputError("Matrix is singular and has no unique solution.")
        a[col], a[pivot] = a[pivot], a[col]
        scale = a[col][col]
        a[col] = [value / scale for value in a[col]]
        for row in range(n):
            if row != col:
                factor = a[row][col]
                a[row] = [a[row][j] - factor * a[col][j] for j in range(n + 1)]
    rr, rc = parse_cell(values["resultStart"])
    solution = [a[i][-1] for i in range(n)]
    for i, value in enumerate(solution):
        ensure_cell(state, cell_address(rr + i, rc))["value"] = value
    _save(
        ctx,
        sheet,
        state,
        {
            "solution": solution,
            "resultRange": f"{values['resultStart']}:{cell_address(rr + n - 1, rc)}",
        },
    )
    return result(summary={"solution": solution})


@feature(
    "docCalc.unitConverter",
    "Unit Converter",
    part="documents",
    fields=[
        number("value", "Value", 1),
        select(
            "kind",
            "Quantity kind",
            [
                ("length", "Length"),
                ("force", "Force"),
                ("stress", "Stress"),
                ("pressure", "Pressure"),
                ("moment", "Moment"),
                ("area", "Area"),
            ],
            "length",
        ),
        text("fromUnit", "From unit", "m"),
        text("toUnit", "To unit", "ft"),
    ],
)
def unit_converter(ctx: FeatureContext, values: dict) -> dict:
    """Convert an entered quantity using SAEngine's registered engineering unit definitions."""
    from saengine.units import KINDS

    try:
        kind = KINDS[values["kind"]]
        source, target = kind.factor(values["fromUnit"]), kind.factor(values["toUnit"])
        offset = dict(kind.offsets)
        si_value = (values["value"] + offset.get(values["fromUnit"], 0)) / source
        converted = si_value * target - offset.get(values["toUnit"], 0)
    except KeyError as exc:
        raise FeatureInputError(f"Unit is not registered for {values['kind']}.") from exc
    return result(
        summary={
            "input": values["value"],
            "output": converted,
            "fromUnit": values["fromUnit"],
            "toUnit": values["toUnit"],
        }
    )


@feature(
    "docCalc.polynomialSolver",
    "Polynomial Solver",
    part="documents",
    fields=[
        text("coefficients", "Coefficients, highest power first", "1,0,-4"),
        text("worksheetId", "Worksheet id", "calculations"),
        text("resultStart", "Result start cell", "A1"),
    ],
)
def polynomial_solver(ctx: FeatureContext, values: dict) -> dict:
    """Find real roots of linear or quadratic polynomials and write them to worksheet cells."""
    try:
        coeffs = [float(part.strip()) for part in values["coefficients"].split(",")]
    except ValueError as exc:
        raise FeatureInputError("Enter numeric coefficients separated by commas.") from exc
    roots = []
    if len(coeffs) == 2 and coeffs[0] != 0:
        roots = [-coeffs[1] / coeffs[0]]
    elif len(coeffs) == 3 and coeffs[0] != 0:
        disc = coeffs[1] ** 2 - 4 * coeffs[0] * coeffs[2]
        if disc >= 0:
            roots = [
                (-coeffs[1] - math.sqrt(disc)) / (2 * coeffs[0]),
                (-coeffs[1] + math.sqrt(disc)) / (2 * coeffs[0]),
            ]
    else:
        raise FeatureInputError(
            "Polynomial solver accepts a non-zero linear or quadratic polynomial."
        )
    if not roots:
        raise FeatureInputError("The polynomial has no real roots.")
    sheet, state = _open(ctx, values)
    row, col = parse_cell(values["resultStart"])
    for index, root in enumerate(roots):
        ensure_cell(state, cell_address(row + index, col))["value"] = root
    _save(ctx, sheet, state, {"realRoots": roots})
    return result(summary={"realRoots": roots})


@feature(
    "docCalc.interpolation",
    "Interpolation",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("xRange", "Known x values", "A1:A4"),
        text("yRange", "Known y values", "B1:B4"),
        number("targetX", "Target x", 2.5),
    ],
)
def interpolation(ctx: FeatureContext, values: dict) -> dict:
    """Linearly interpolate between the bracketing data points in two worksheet ranges."""
    sheet, state = _open(ctx, values)
    xs = [cell_value(a, state) for a in range_cells(values["xRange"])]
    ys = [cell_value(a, state) for a in range_cells(values["yRange"])]
    if len(xs) != len(ys) or len(xs) < 2:
        raise FeatureInputError("X and Y ranges need the same number of at least two values.")
    pairs = sorted(zip(xs, ys, strict=True))
    x = values["targetX"]
    for (x0, y0), (x1, y1) in pairwise(pairs):
        if x0 <= x <= x1:
            if x1 == x0:
                raise FeatureInputError("X values must be distinct.")
            y = y0 + (y1 - y0) * (x - x0) / (x1 - x0)
            state.setdefault("settings", {})["lastInterpolation"] = {"x": x, "y": y}
            _save(ctx, sheet, state, {"x": x, "interpolatedY": y})
            return result(summary={"x": x, "interpolatedY": y})
    raise FeatureInputError("Target x lies outside the table; extrapolation is disabled.")


@feature(
    "docCalc.sectionModulus",
    "Section Modulus",
    part="documents",
    fields=[
        select(
            "shape",
            "Section shape",
            [
                ("rectangle", "Rectangle"),
                ("circle", "Solid circle"),
                ("hollowRectangle", "Hollow rectangle"),
            ],
            "rectangle",
        ),
        number("width", "Width or diameter", 300, unit="mm", min=0.001),
        number("depth", "Depth", 500, unit="mm", min=0.001),
        number("thickness", "Wall thickness", 10, unit="mm", min=0.001),
    ],
)
def section_modulus(ctx: FeatureContext, values: dict) -> dict:
    """Calculate elastic section modulus for a rectangle, solid circle or hollow rectangle."""
    b, d, t = values["width"], values["depth"], values["thickness"]
    if values["shape"] == "rectangle":
        i = b * d**3 / 12
    elif values["shape"] == "circle":
        i = math.pi * d**4 / 64
    else:
        if 2 * t >= min(b, d):
            raise FeatureInputError("Wall thickness must leave a positive hollow core.")
        i = (b * d**3 - (b - 2 * t) * (d - 2 * t) ** 3) / 12
    return result(summary={"inertiaMm4": i, "sectionModulusMm3": i / (d / 2)})


@feature(
    "docCalc.momentCapacity",
    "Moment Capacity",
    part="documents",
    fields=[
        number("yieldStress", "Yield stress", 345, unit="MPa", min=0.001),
        number("sectionModulus", "Section modulus", 100000, unit="mm³", min=0.001),
        number("resistanceFactor", "Resistance factor", 0.9, min=0.01, max=1),
    ],
)
def moment_capacity(ctx: FeatureContext, values: dict) -> dict:
    """Calculate factored elastic yield moment capacity from stress and section modulus."""
    capacity = values["yieldStress"] * values["sectionModulus"] / 1e6 * values["resistanceFactor"]
    return result(
        summary={
            "momentCapacityKNm": capacity,
            "yieldStressMPa": values["yieldStress"],
            "resistanceFactor": values["resistanceFactor"],
        }
    )


@feature(
    "docCalc.shearCapacity",
    "Shear Capacity",
    part="documents",
    fields=[
        number("yieldStress", "Yield stress", 345, unit="MPa", min=0.001),
        number("webArea", "Effective web area", 5000, unit="mm²", min=0.001),
        number("resistanceFactor", "Resistance factor", 0.9, min=0.01, max=1),
    ],
)
def shear_capacity(ctx: FeatureContext, values: dict) -> dict:
    """Calculate a nominal von Mises web shear yield capacity and apply the entered factor."""
    capacity = (
        values["yieldStress"]
        * values["webArea"]
        / (math.sqrt(3) * 1000)
        * values["resistanceFactor"]
    )
    return result(
        summary={"shearCapacityKN": capacity, "resistanceFactor": values["resistanceFactor"]}
    )


@feature(
    "docCalc.deflectionCalc",
    "Deflection Calc",
    part="documents",
    fields=[
        number("load", "Uniform load", 5, unit="kN/m", min=0),
        number("span", "Simple span", 5, unit="m", min=0.001),
        number("elasticModulus", "Elastic modulus", 200000, unit="MPa", min=0.001),
        number("inertia", "Second moment of area", 100000000, unit="mm⁴", min=0.001),
    ],
)
def deflection_calc(ctx: FeatureContext, values: dict) -> dict:
    """Calculate maximum elastic deflection of a simply supported beam under uniform load."""
    delta = (
        5
        * (values["load"] * 1e3)
        * (values["span"] * 1e3) ** 4
        / (384 * values["elasticModulus"] * values["inertia"])
    )
    return result(
        summary={
            "maximumDeflectionMm": delta,
            "spanMm": values["span"] * 1000,
            "deflectionRatio": values["span"] * 1000 / delta if delta else None,
        }
    )


@feature(
    "docCalc.symbolicMath",
    "Symbolic Math",
    part="documents",
    fields=[
        text("expression", "Expression", "2*(a+b)"),
        text("variables", "Variable values as name=value", "a=2,b=3"),
    ],
)
def symbolic_math(ctx: FeatureContext, values: dict) -> dict:
    """Evaluate a safe arithmetic expression using explicitly supplied named variables."""
    sheet, state = _open(ctx, {"worksheetId": "calculations"})
    for pair in values["variables"].split(","):
        if not pair.strip():
            continue
        name, sep, raw = pair.partition("=")
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name.strip()):
            raise FeatureInputError("Variables must be written as name=value pairs.")
        try:
            state.setdefault("names", {})[name.strip().upper()] = float(raw)
        except ValueError as exc:
            raise FeatureInputError(f"Variable {name.strip()} must be numeric.") from exc
    from saengine.features.documents_common import _safe_eval

    try:
        tree = __import__("ast").parse(values["expression"].replace("^", "**"), mode="eval")
    except SyntaxError as exc:
        raise FeatureInputError("Expression syntax is invalid.") from exc
    value = _safe_eval(tree.body, state, set())
    state.setdefault("settings", {})["lastSymbolicEvaluation"] = {
        "expression": values["expression"],
        "value": value,
        "at": _now(),
    }
    _save(ctx, sheet, state, {"value": value})
    return result(summary={"value": value})


@feature(
    "docCalc.expressionParser",
    "Expression Parser",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("expression", "Expression", "A1+B1*2"),
    ],
)
def expression_parser(ctx: FeatureContext, values: dict) -> dict:
    """Parse an expression without executing it and report referenced cells and operators."""
    import ast

    expression = values["expression"].replace("^", "**")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise FeatureInputError("Expression syntax is invalid.") from exc
    allowed = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Pow,
        ast.Mod,
        ast.UAdd,
        ast.USub,
        ast.Name,
        ast.Constant,
        ast.Call,
        ast.Load,
    )
    if any(not isinstance(node, allowed) for node in ast.walk(tree)):
        raise FeatureInputError("Expression includes an unsupported operation.")
    refs = sorted(
        {
            node.id.upper()
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
            and re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]*", node.id.upper())
        }
    )
    funcs = sorted(
        {
            node.func.id.upper()
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
    )
    return result(
        summary={
            "valid": True,
            "cellReferences": refs,
            "functions": funcs,
            "nodeCount": sum(1 for _ in ast.walk(tree)),
        }
    )


@feature(
    "docCalc.variableManager",
    "Variable Manager",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("name", "Variable name", "SPAN"),
        number("value", "Numeric value", 1),
        text("unit", "Unit", "mm"),
        checkbox("remove", "Remove variable", False),
    ],
)
def variable_manager(ctx: FeatureContext, values: dict) -> dict:
    """Create, update or remove a named numerical formula variable with a unit annotation."""
    sheet, state = _open(ctx, values)
    name = values["name"].strip().upper()
    if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name):
        raise FeatureInputError("Variable name must contain letters, digits and underscores.")
    variables = state.setdefault("variables", {})
    if values["remove"]:
        if name not in variables:
            raise FeatureInputError("That variable is not defined.")
        del variables[name]
        state.setdefault("names", {}).pop(name, None)
    else:
        variables[name] = {"value": values["value"], "unit": values["unit"]}
        state.setdefault("names", {})[name] = values["value"]
    return _save(
        ctx,
        sheet,
        state,
        {
            "variable": name,
            "removed": values["remove"],
            "value": None if values["remove"] else values["value"],
        },
    )


@feature(
    "docCalc.parameterOptimizer",
    "Parameter Optimizer",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("objectiveCell", "Objective cell", "C1"),
        text("variableCell", "Variable cell", "A1"),
        number("minimum", "Minimum", 0),
        number("maximum", "Maximum", 10),
        number("samples", "Sample count", 101, min=2, max=10001),
        select("goal", "Objective", [("min", "Minimum"), ("max", "Maximum")], "min"),
    ],
)
def parameter_optimizer(ctx: FeatureContext, values: dict) -> dict:
    """Sample a bounded parameter interval and select the value that optimizes a worksheet objective."""
    if values["minimum"] >= values["maximum"]:
        raise FeatureInputError("Minimum must be below maximum.")
    sheet, state = _open(ctx, values)
    cell = ensure_cell(state, values["variableCell"])
    original = cell.get("value", 0)
    samples = int(values["samples"])
    best = None
    for index in range(samples):
        candidate = values["minimum"] + (values["maximum"] - values["minimum"]) * index / (
            samples - 1
        )
        cell["value"] = candidate
        objective = cell_value(values["objectiveCell"], state)
        if best is None or (
            objective < best[1] if values["goal"] == "min" else objective > best[1]
        ):
            best = (candidate, objective)
    cell["value"] = best[0]
    _save(
        ctx,
        sheet,
        state,
        {
            "optimalParameter": best[0],
            "objective": best[1],
            "samples": samples,
            "originalValue": original,
        },
    )
    return result(summary={"optimalParameter": best[0], "objective": best[1], "samples": samples})


@feature(
    "docCalc.tradeoffAnalysis",
    "Tradeoff Analysis",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("metricCells", "Metric cells, label=cell", "Strength=A1,Weight=B1,Cost=C1"),
        text("weights", "Weights, label=value", "Strength=0.5,Weight=-0.2,Cost=-0.3"),
    ],
)
def tradeoff_analysis(ctx: FeatureContext, values: dict) -> dict:
    """Normalize selected worksheet metrics and calculate a weighted tradeoff score."""
    sheet, state = _open(ctx, values)
    metrics = {}
    for pair in values["metricCells"].split(","):
        name, sep, address = pair.partition("=")
        if not sep:
            raise FeatureInputError("Metrics must use label=cell pairs.")
        metrics[name.strip()] = cell_value(address.strip(), state)
    weights = {}
    for pair in values["weights"].split(","):
        name, sep, raw = pair.partition("=")
        if not sep:
            raise FeatureInputError("Weights must use label=value pairs.")
        weights[name.strip()] = float(raw)
    score = sum(metrics[name] * weights[name] for name in metrics if name in weights)
    if not score and not metrics:
        raise FeatureInputError("Enter at least one metric.")
    state.setdefault("settings", {})["lastTradeoff"] = {
        "metrics": metrics,
        "weights": weights,
        "score": score,
    }
    _save(ctx, sheet, state, {"weightedScore": score, "metrics": metrics})
    return result(summary={"weightedScore": score, "metrics": metrics})


@feature(
    "docCalc.sensitivityAnalysis",
    "Sensitivity Analysis",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("objectiveCell", "Objective cell", "C1"),
        text("variableCell", "Variable cell", "A1"),
        number("baseValue", "Base value", 1),
        number("variationPercent", "Variation", 10, unit="%", min=0.01, max=99),
        number("samples", "Samples", 11, min=3, max=101),
    ],
)
def sensitivity_analysis(ctx: FeatureContext, values: dict) -> dict:
    """Evaluate objective response across a symmetric range around one base input value."""
    sheet, state = _open(ctx, values)
    cell = ensure_cell(state, values["variableCell"])
    original = cell.get("value", 0)
    n = int(values["samples"])
    half = values["variationPercent"] / 100
    rows = []
    for index in range(n):
        ratio = -half + 2 * half * index / (n - 1)
        candidate = values["baseValue"] * (1 + ratio)
        cell["value"] = candidate
        rows.append(
            {
                "variationPercent": ratio * 100,
                "input": candidate,
                "objective": cell_value(values["objectiveCell"], state),
            }
        )
    cell["value"] = original
    _save(ctx, sheet, state, {"sampleCount": len(rows), "objectiveCell": values["objectiveCell"]})
    return result(
        summary={"sampleCount": len(rows)},
        tables=[
            {
                "title": "Sensitivity",
                "columns": [
                    {"key": "variationPercent", "title": "Variation [%]"},
                    {"key": "input", "title": "Input"},
                    {"key": "objective", "title": "Objective"},
                ],
                "rows": rows,
            }
        ],
    )

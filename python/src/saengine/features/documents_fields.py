"""Report data fields, bindings and table-layout controls."""

from __future__ import annotations

import ast
import re

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
    document_state,
    dotted_value,
    project_fields,
    save_document_state,
)


def _state(ctx):
    state = document_state(ctx, "reportFields")
    state.setdefault("bindings", {})
    state.setdefault("parameters", {})
    state.setdefault("computed", {})
    state.setdefault("tables", {})
    return state


def _save(ctx, state):
    return save_document_state(ctx, "reportFields", state)


def _flatten(data, prefix=""):
    rows = []
    if isinstance(data, dict):
        for key, value in data.items():
            rows.extend(_flatten(value, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(data, list):
        for index, value in enumerate(data[:100]):
            rows.extend(_flatten(value, f"{prefix}.{index}"))
    else:
        rows.append({"path": prefix, "value": data, "type": type(data).__name__})
    return rows


@feature(
    "docFields.fieldBrowser",
    "Field Browser",
    part="documents",
    fields=[text("search", "Search project fields", "project.name")],
)
def field_browser(ctx: FeatureContext, values: dict) -> dict:
    """Browse available scalar values from project parts by their dotted field path."""
    rows = [
        row
        for row in _flatten(project_fields(ctx))
        if values["search"].casefold() in row["path"].casefold()
    ]
    return result(
        summary={"fieldCount": len(rows)},
        tables=[
            {
                "title": "Available project fields",
                "columns": [
                    {"key": "path", "title": "Field path"},
                    {"key": "type", "title": "Type"},
                    {"key": "value", "title": "Current value"},
                ],
                "rows": rows[:500],
            }
        ],
    )


@feature(
    "docFields.dataBindings",
    "Data Bindings",
    part="documents",
    fields=[
        text("placeholder", "Template placeholder", "project.name"),
        text("sourcePath", "Project source path", "settings.project.name"),
        text("fallback", "Fallback", "Untitled project"),
    ],
)
def data_bindings(ctx: FeatureContext, values: dict) -> dict:
    """Bind a document placeholder to a live project data path and set its missing-value fallback."""
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", values["placeholder"]):
        raise FeatureInputError("Placeholder must be a simple dotted identifier.")
    state = _state(ctx)
    current = dotted_value(project_fields(ctx), values["sourcePath"])
    state["bindings"][values["placeholder"]] = {
        "sourcePath": values["sourcePath"],
        "fallback": values["fallback"],
        "currentValue": values["fallback"] if current is None else current,
    }
    _save(ctx, state)
    return result(
        summary={
            "placeholder": values["placeholder"],
            "resolvedValue": state["bindings"][values["placeholder"]]["currentValue"],
        }
    )


@feature(
    "docFields.formulaField",
    "Formula Field",
    part="documents",
    fields=[
        text("name", "Formula field name", "totalWeight"),
        text("expression", "Arithmetic expression", "beamCount*5"),
        text("unit", "Output unit", "kN"),
    ],
)
def formula_field(ctx: FeatureContext, values: dict) -> dict:
    """Create a formula field from numeric named parameters using the safe worksheet expression evaluator."""
    import ast

    from saengine.features.documents_common import _safe_eval

    state = _state(ctx)
    scope = {
        **state["parameters"],
        **{
            key: item.get("value")
            for key, item in state["computed"].items()
            if isinstance(item, dict)
        },
    }
    try:
        tree = ast.parse(values["expression"].replace("^", "**"), mode="eval")
    except SyntaxError as exc:
        raise FeatureInputError("Formula expression has invalid syntax.") from exc
    value = _safe_eval(tree.body, {"names": scope, "cells": {}}, set())
    state["computed"][values["name"]] = {
        "expression": values["expression"],
        "value": value,
        "unit": values["unit"],
        "kind": "formula",
    }
    _save(ctx, state)
    return result(summary={"field": values["name"], "value": value, "unit": values["unit"]})


@feature(
    "docFields.modelProperties",
    "Model Properties",
    part="documents",
    fields=[text("query", "Search model properties", "column"), text("part", "Model part", "bim")],
)
def model_properties(ctx: FeatureContext, values: dict) -> dict:
    """List matching scalar model properties in BIM, objects or Floor Plan project data."""
    if values["part"] not in ("bim", "objects", "floorPlan"):
        raise FeatureInputError("Choose BIM, objects or floorPlan as the model data part.")
    rows = [
        row
        for row in _flatten({values["part"]: project_fields(ctx).get(values["part"], {})})
        if values["query"].casefold() in row["path"].casefold()
    ]
    return result(
        summary={"propertyCount": len(rows)},
        tables=[
            {
                "title": "Model properties",
                "columns": [
                    {"key": "path", "title": "Property"},
                    {"key": "type", "title": "Type"},
                    {"key": "value", "title": "Value"},
                ],
                "rows": rows[:500],
            }
        ],
    )


@feature(
    "docFields.projectParameters",
    "Project Parameters",
    part="documents",
    fields=[
        text("name", "Parameter name", "DesignLiveLoad"),
        text("sourcePath", "Project settings path", "settings.loading.liveLoadKNm2"),
        text("unit", "Parameter unit", "kN/m²"),
    ],
)
def project_parameters(ctx: FeatureContext, values: dict) -> dict:
    """Capture a live project parameter in the report data context with its engineering unit."""
    state = _state(ctx)
    value = dotted_value(project_fields(ctx), values["sourcePath"])
    if value is None:
        raise FeatureInputError("Project parameter path is not present in the current project.")
    state["parameters"][values["name"]] = {
        "value": value,
        "unit": values["unit"],
        "sourcePath": values["sourcePath"],
    }
    _save(ctx, state)
    return result(summary={"parameter": values["name"], "value": value, "unit": values["unit"]})


@feature(
    "docFields.resultTables",
    "Result Tables",
    part="documents",
    fields=[text("search", "Search result field", "utilization")],
)
def result_tables(ctx: FeatureContext, values: dict) -> dict:
    """Find available analysis or design result records and return matching report rows."""
    rows = []
    for part in ("bim", "objects", "boq"):
        rows.extend(
            row
            for row in _flatten({part: project_fields(ctx).get(part, {})})
            if values["search"].casefold() in row["path"].casefold()
        )
    return result(
        summary={"resultFieldCount": len(rows)},
        tables=[
            {
                "title": "Result fields",
                "columns": [
                    {"key": "path", "title": "Field"},
                    {"key": "type", "title": "Type"},
                    {"key": "value", "title": "Value"},
                ],
                "rows": rows[:500],
            }
        ],
    )


@feature(
    "docFields.scheduleTables",
    "Schedule Tables",
    part="documents",
    fields=[
        text("scheduleId", "Schedule id", "member-schedule"),
        text("tableName", "Report table name", "Members"),
    ],
)
def schedule_tables(ctx: FeatureContext, values: dict) -> dict:
    """Build a saved drawing schedule and register its rows as a named report data table."""
    from saengine.features.documents_schedules import _build, _definition
    from saengine.features.documents_schedules import _state as schedule_state

    schedules = schedule_state(ctx)
    definition = _definition(schedules, values["scheduleId"])
    built = _build(ctx, definition)
    state = _state(ctx)
    rows = [dict(zip(built.columns, row, strict=True)) for row in built.rows]
    state["tables"][values["tableName"]] = {
        "columns": built.columns,
        "rows": rows,
        "scheduleId": definition["id"],
    }
    _save(ctx, state)
    return result(
        summary={
            "tableName": values["tableName"],
            "rowCount": len(rows),
            "columnCount": len(built.columns),
        }
    )


@feature(
    "docFields.quantityTables",
    "Quantity Tables",
    part="documents",
    fields=[
        text("part", "Quantity data part", "boq"),
        text("collection", "Collection key", "items"),
    ],
)
def quantity_tables(ctx: FeatureContext, values: dict) -> dict:
    """Create a report table from real quantity rows stored in the requested project part."""
    data = project_fields(ctx).get(values["part"])
    if not isinstance(data, dict) or not isinstance(data.get(values["collection"]), list):
        raise FeatureInputError(
            "The selected project part does not contain that quantity collection."
        )
    rows = data[values["collection"]]
    if not rows:
        raise FeatureInputError("Quantity collection is empty.")
    state = _state(ctx)
    state["tables"][f"{values['part']}.{values['collection']}"] = {
        "columns": sorted({key for row in rows if isinstance(row, dict) for key in row}),
        "rows": rows,
    }
    _save(ctx, state)
    return result(
        summary={
            "quantityRows": len(rows),
            "columns": len(state["tables"][f"{values['part']}.{values['collection']}"]["columns"]),
        }
    )


@feature(
    "docFields.conditionalFormat",
    "Conditional Format",
    part="documents",
    fields=[
        text("tableName", "Report table", "Members"),
        text("column", "Numeric column", "utilization"),
        select(
            "operator",
            "Rule",
            [("gt", "Greater than"), ("lt", "Less than"), ("eq", "Equal to")],
            "gt",
        ),
        number("threshold", "Threshold", 1),
        text("colour", "Highlight colour", "#FFC7CE"),
    ],
)
def conditional_format(ctx: FeatureContext, values: dict) -> dict:
    """Save a report-table conditional format and count current rows that meet its threshold."""
    import operator

    ops = {"gt": operator.gt, "lt": operator.lt, "eq": operator.eq}
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", values["colour"]):
        raise FeatureInputError("Highlight colour must be #RRGGBB.")
    state = _state(ctx)
    table = state["tables"].get(values["tableName"])
    if not table:
        raise FeatureInputError("Named report table does not exist.")
    if values["column"] not in table["columns"]:
        raise FeatureInputError("Selected table column does not exist.")
    matched = []
    for row in table["rows"]:
        try:
            flag = ops[values["operator"]](float(row[values["column"]]), values["threshold"])
        except (KeyError, TypeError, ValueError):
            continue
        if flag:
            row.setdefault("_format", {})[values["column"]] = {"fill": values["colour"]}
            matched.append(row)
    table.setdefault("conditionalFormats", []).append(
        {
            "column": values["column"],
            "operator": values["operator"],
            "threshold": values["threshold"],
            "colour": values["colour"],
        }
    )
    _save(ctx, state)
    return result(
        summary={
            "formattedRows": len(matched),
            "tableName": values["tableName"],
            "column": values["column"],
        }
    )


@feature(
    "docFields.hideEmpty",
    "Hide Empty",
    part="documents",
    fields=[
        text("tableName", "Report table", "Members"),
        text("columns", "Columns to inspect", "name,mark"),
        checkbox("removeRow", "Remove rows with blank fields", True),
    ],
)
def hide_empty(ctx: FeatureContext, values: dict) -> dict:
    """Remove empty rows or blank-valued columns from a named report table."""
    state = _state(ctx)
    table = state["tables"].get(values["tableName"])
    if not table:
        raise FeatureInputError("Named report table does not exist.")
    columns = [part.strip() for part in values["columns"].split(",") if part.strip()]
    if set(columns) - set(table["columns"]):
        raise FeatureInputError("A selected empty-check column is not in the table.")
    before = len(table["rows"])
    if values["removeRow"]:
        table["rows"] = [
            row for row in table["rows"] if any(row.get(col) not in (None, "") for col in columns)
        ]
    else:
        blank = {col for col in columns if all(row.get(col) in (None, "") for row in table["rows"])}
        table["columns"] = [col for col in table["columns"] if col not in blank]
        table["rows"] = [
            {key: value for key, value in row.items() if key not in blank} for row in table["rows"]
        ]
    _save(ctx, state)
    return result(
        summary={
            "removedRows": before - len(table["rows"]),
            "remainingRows": len(table["rows"]),
            "columns": table["columns"],
        }
    )


@feature(
    "docFields.pageBreaks",
    "Page Breaks",
    part="documents",
    fields=[
        text("tableName", "Report table", "Members"),
        number("rowsPerPage", "Maximum rows per page", 25, min=1, max=1000),
        checkbox("repeatHeader", "Repeat header on each page", True),
    ],
)
def page_breaks(ctx: FeatureContext, values: dict) -> dict:
    """Paginate a report table into repeat-header row blocks and store the resulting break map."""
    state = _state(ctx)
    table = state["tables"].get(values["tableName"])
    if not table:
        raise FeatureInputError("Named report table does not exist.")
    size = int(values["rowsPerPage"])
    chunks = [table["rows"][i : i + size] for i in range(0, len(table["rows"]), size)]
    table["pagination"] = {
        "rowsPerPage": size,
        "repeatHeader": values["repeatHeader"],
        "pages": chunks,
    }
    _save(ctx, state)
    return result(
        summary={
            "pageCount": len(chunks),
            "rowCounts": [len(chunk) for chunk in chunks],
            "repeatHeader": values["repeatHeader"],
        }
    )


@feature(
    "docFields.userParameters",
    "User Parameters",
    part="documents",
    fields=[
        text("name", "Parameter name", "DesignCase"),
        text("value", "Value", "ULS"),
        text("unit", "Unit", ""),
        text("description", "Description", "Governing load case"),
    ],
)
def user_parameters(ctx: FeatureContext, values: dict) -> dict:
    """Define a user-owned report parameter that can be referenced by formulas and placeholders."""
    state = _state(ctx)
    state["parameters"][values["name"]] = {
        "value": values["value"],
        "unit": values["unit"],
        "description": values["description"],
        "owner": "user",
    }
    _save(ctx, state)
    return result(
        summary={"parameter": values["name"], "value": values["value"], "unit": values["unit"]}
    )


@feature(
    "docFields.calculatedField",
    "Calculated Field",
    part="documents",
    fields=[
        text("name", "Field name", "utilizationRatio"),
        text("expression", "Expression", "demand/capacity"),
        text("unit", "Unit", ""),
    ],
)
def calculated_field(ctx: FeatureContext, values: dict) -> dict:
    """Add an evaluated report calculation field using available user and project scalar values."""
    from saengine.features.documents_common import _safe_eval

    namespace = {}
    for row in _flatten(project_fields(ctx)):
        if isinstance(row["value"], (int, float)) and re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", row["path"].split(".")[-1]
        ):
            namespace[row["path"].split(".")[-1].upper()] = row["value"]
    state = _state(ctx)
    namespace.update(
        {
            key.upper(): item["value"]
            for key, item in state["parameters"].items()
            if isinstance(item.get("value"), (int, float))
        }
    )
    try:
        tree = ast.parse(values["expression"].replace("^", "**"), mode="eval")
    except SyntaxError as exc:
        raise FeatureInputError("Calculation expression is invalid.") from exc
    value = _safe_eval(tree.body, {"names": namespace, "cells": {}}, set())
    state["computed"][values["name"]] = {
        "expression": values["expression"],
        "value": value,
        "unit": values["unit"],
        "kind": "calculated",
    }
    _save(ctx, state)
    return result(summary={"field": values["name"], "value": value, "unit": values["unit"]})


@feature(
    "docFields.scriptedField",
    "Scripted Field",
    part="documents",
    fields=[
        text("name", "Field name", "projectTitle"),
        text("sourcePath", "Project data path", "settings.project.name"),
        text("transform", "Text transform", "upper"),
    ],
)
def scripted_field(ctx: FeatureContext, values: dict) -> dict:
    """Create a non-executable scripted field with a supported text transformation on project data."""
    value = dotted_value(project_fields(ctx), values["sourcePath"])
    if value is None:
        raise FeatureInputError("The project data path has no value.")
    transforms = {
        "upper": lambda x: str(x).upper(),
        "lower": lambda x: str(x).lower(),
        "title": lambda x: str(x).title(),
        "trim": lambda x: str(x).strip(),
    }
    if values["transform"] not in transforms:
        raise FeatureInputError("Transform must be upper, lower, title or trim.")
    computed = transforms[values["transform"]](value)
    state = _state(ctx)
    state["computed"][values["name"]] = {
        "kind": "scriptedText",
        "sourcePath": values["sourcePath"],
        "transform": values["transform"],
        "value": computed,
    }
    _save(ctx, state)
    return result(summary={"field": values["name"], "value": computed})


@feature(
    "docFields.tableAutoFit",
    "Table Auto Fit",
    part="documents",
    fields=[
        text("tableName", "Report table", "Members"),
        number("maximumWidthMm", "Maximum table width", 175, unit="mm", min=20),
        number("minimumColumnWidthMm", "Minimum column width", 12, unit="mm", min=3),
    ],
)
def table_auto_fit(ctx: FeatureContext, values: dict) -> dict:
    """Estimate report-table column widths from headings and cell content within page constraints."""
    state = _state(ctx)
    table = state["tables"].get(values["tableName"])
    if not table:
        raise FeatureInputError("Named report table does not exist.")
    raw = [
        max([len(str(col)), *(len(str(row.get(col, ""))) for row in table["rows"])])
        for col in table["columns"]
    ]
    total = sum(raw) or 1
    widths = [
        max(values["minimumColumnWidthMm"], values["maximumWidthMm"] * item / total) for item in raw
    ]
    if sum(widths) > values["maximumWidthMm"]:
        widths = [values["maximumWidthMm"] * item / sum(widths) for item in widths]
    table["columnWidthsMm"] = dict(zip(table["columns"], widths, strict=True))
    _save(ctx, state)
    return result(
        summary={
            "tableName": values["tableName"],
            "columnWidthsMm": table["columnWidthsMm"],
            "totalWidthMm": sum(widths),
        }
    )


@feature(
    "docFields.subtotals",
    "Subtotals",
    part="documents",
    fields=[
        text("tableName", "Report table", "Members"),
        text("groupColumn", "Group by column", "story"),
        text("totalColumn", "Numeric column", "weightKN"),
    ],
)
def subtotals(ctx: FeatureContext, values: dict) -> dict:
    """Calculate numeric subtotals for each unique value in a report table grouping column."""
    state = _state(ctx)
    table = state["tables"].get(values["tableName"])
    if (
        not table
        or values["groupColumn"] not in table["columns"]
        or values["totalColumn"] not in table["columns"]
    ):
        raise FeatureInputError("Select an existing report table and columns.")
    totals = {}
    for row in table["rows"]:
        try:
            value = float(row[values["totalColumn"]])
        except (TypeError, ValueError):
            continue
        key = row.get(values["groupColumn"])
        totals[key] = totals.get(key, 0) + value
    table["subtotals"] = {
        "groupColumn": values["groupColumn"],
        "totalColumn": values["totalColumn"],
        "values": totals,
    }
    _save(ctx, state)
    return result(summary={"groupCount": len(totals), "totals": totals})


@feature(
    "docFields.repeatingHeaders",
    "Repeating Headers",
    part="documents",
    fields=[
        text("tableName", "Report table", "Members"),
        checkbox("repeatColumnHeader", "Repeat column headings", True),
        checkbox("repeatGroupHeader", "Repeat group labels", False),
    ],
)
def repeating_headers(ctx: FeatureContext, values: dict) -> dict:
    """Set table header and grouping label repetition across page breaks."""
    state = _state(ctx)
    table = state["tables"].get(values["tableName"])
    if not table:
        raise FeatureInputError("Named report table does not exist.")
    table["repeatingHeaders"] = {
        "columns": values["repeatColumnHeader"],
        "groups": values["repeatGroupHeader"],
    }
    _save(ctx, state)
    return result(
        summary={"tableName": values["tableName"], "repeatingHeaders": table["repeatingHeaders"]}
    )


@feature(
    "docFields.blankRows",
    "Blank Rows",
    part="documents",
    fields=[
        text("tableName", "Report table", "Members"),
        number("blankRows", "Insert blank rows between groups", 1, min=0, max=10),
    ],
)
def blank_rows(ctx: FeatureContext, values: dict) -> dict:
    """Insert a configured number of blank presentation rows where adjacent table groups change."""
    state = _state(ctx)
    table = state["tables"].get(values["tableName"])
    if not table or not table.get("rows"):
        raise FeatureInputError("Named report table has no rows.")
    grouping = table.get("groupBy") or table["columns"][0]
    output = []
    count = int(values["blankRows"])
    previous = None
    for row in table["rows"]:
        current = row.get(grouping)
        if previous is not None and current != previous:
            output.extend({} for _ in range(count))
        output.append(row)
        previous = current
    table["displayRows"] = output
    _save(ctx, state)
    return result(
        summary={
            "dataRows": len(table["rows"]),
            "displayRows": len(output),
            "blankRowsInserted": len(output) - len(table["rows"]),
        }
    )


@feature(
    "docFields.linkParameter",
    "Link Parameter",
    part="documents",
    fields=[
        text("parameter", "Parameter name", "DesignLoad"),
        text("sourcePath", "Project path", "settings.loads.live"),
        text("unit", "Unit", "kN/m²"),
    ],
)
def link_parameter(ctx: FeatureContext, values: dict) -> dict:
    """Refresh a named report parameter directly from a project field and save its source link."""
    state = _state(ctx)
    value = dotted_value(project_fields(ctx), values["sourcePath"])
    if value is None:
        raise FeatureInputError("Project parameter source path does not exist.")
    state["parameters"][values["parameter"]] = {
        "value": value,
        "unit": values["unit"],
        "sourcePath": values["sourcePath"],
        "linked": True,
    }
    _save(ctx, state)
    return result(
        summary={"parameter": values["parameter"], "value": value, "unit": values["unit"]}
    )


@feature(
    "docFields.dynamicReference",
    "Dynamic Reference",
    part="documents",
    fields=[
        text("name", "Reference name", "governingMember"),
        text("selector", "Part collection path", "floorPlan.beams"),
        number("index", "Record index", 0, min=0),
        text("property", "Record property", "mark"),
    ],
)
def dynamic_reference(ctx: FeatureContext, values: dict) -> dict:
    """Create a project-linked reference to a selected record property by collection path and index."""
    data = project_fields(ctx)
    collection = dotted_value(data, values["selector"])
    idx = int(values["index"])
    if not isinstance(collection, list) or idx >= len(collection):
        raise FeatureInputError("Collection path or record index does not exist.")
    value = collection[idx].get(values["property"]) if isinstance(collection[idx], dict) else None
    if value is None:
        raise FeatureInputError("Selected record property was not found.")
    state = _state(ctx)
    state["bindings"][values["name"]] = {
        "sourcePath": f"{values['selector']}.{idx}.{values['property']}",
        "currentValue": value,
        "dynamic": True,
    }
    _save(ctx, state)
    return result(summary={"reference": values["name"], "value": value})


@feature(
    "docFields.fieldMapping",
    "Field Mapping",
    part="documents",
    fields=[
        text("sourcePath", "Source field", "bim.members.0.mark"),
        text("target", "Report field", "memberMark"),
        text("unit", "Target unit", ""),
    ],
)
def field_mapping(ctx: FeatureContext, values: dict) -> dict:
    """Map one source path to a report field and record its resolved value and unit."""
    value = dotted_value(project_fields(ctx), values["sourcePath"])
    if value is None:
        raise FeatureInputError("Source field path does not resolve in the project.")
    state = _state(ctx)
    state["bindings"][values["target"]] = {
        "sourcePath": values["sourcePath"],
        "value": value,
        "unit": values["unit"],
    }
    _save(ctx, state)
    return result(summary={"target": values["target"], "value": value, "unit": values["unit"]})


@feature(
    "docFields.fieldChecks",
    "Field Checks",
    part="documents",
    fields=[
        text(
            "requiredPlaceholders",
            "Required placeholders, comma separated",
            "project.name,revision,issueDate",
        )
    ],
)
def field_checks(ctx: FeatureContext, values: dict) -> dict:
    """Check all required template placeholders against the project's available scalar data paths."""
    available = {row["path"] for row in _flatten(project_fields(ctx))}
    state = _state(ctx)
    available |= set(state["bindings"])
    required = [part.strip() for part in values["requiredPlaceholders"].split(",") if part.strip()]
    missing = [name for name in required if name not in available]
    state["lastFieldCheck"] = {"required": required, "missing": missing}
    _save(ctx, state)
    return result(
        summary={"requiredCount": len(required), "missing": missing, "valid": not missing}
    )


@feature(
    "docFields.expressionError",
    "Expression Error",
    part="documents",
    fields=[
        text("expression", "Expression", "memberCount*25"),
        text("names", "Available names", "memberCount=10"),
    ],
)
def expression_error(ctx: FeatureContext, values: dict) -> dict:
    """Parse and evaluate a safe arithmetic report expression to return a precise formula diagnostic."""
    from saengine.features.documents_common import _safe_eval

    names = {}
    for pair in values["names"].split(","):
        name, sep, value = pair.partition("=")
        if not sep:
            raise FeatureInputError("Names must be entered as name=value pairs.")
        try:
            names[name.strip().upper()] = float(value)
        except ValueError as exc:
            raise FeatureInputError(f"Value for {name.strip()} must be numeric.") from exc
    try:
        tree = ast.parse(values["expression"].replace("^", "**"), mode="eval")
        value = _safe_eval(tree.body, {"names": names, "cells": {}}, set())
    except (SyntaxError, FeatureInputError) as exc:
        raise FeatureInputError(f"Expression error: {exc}") from exc
    return result(summary={"valid": True, "value": value})


@feature("docFields.evaluateFields", "Evaluate Fields", part="documents", fields=[])
def evaluate_fields(ctx: FeatureContext, values: dict) -> dict:
    """Refresh all bound project fields and return current values for computed and source-linked report placeholders."""
    state = _state(ctx)
    data = project_fields(ctx)
    rows = []
    for name, binding in state["bindings"].items():
        value = dotted_value(data, binding.get("sourcePath", ""))
        value = binding.get("fallback") if value is None else value
        binding["currentValue"] = value
        rows.append({"field": name, "value": value, "unit": binding.get("unit", "")})
    rows.extend(
        {"field": name, "value": item.get("value"), "unit": item.get("unit", "")}
        for name, item in state["computed"].items()
    )
    _save(ctx, state)
    return result(
        summary={"evaluatedFields": len(rows)},
        tables=[
            {
                "title": "Report data fields",
                "columns": [
                    {"key": "field", "title": "Field"},
                    {"key": "value", "title": "Value"},
                    {"key": "unit", "title": "Unit"},
                ],
                "rows": rows,
            }
        ],
    )

"""Calculation worksheet validation, formula inspection and protection."""

from __future__ import annotations

import ast
import math
import re
from datetime import UTC, datetime

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
    range_cells,
    save_worksheet_workspace,
    worksheet_workspace,
)


def _open(ctx: FeatureContext, values: dict):
    return worksheet_workspace(ctx, values["worksheetId"])


def _save(ctx: FeatureContext, sheet, state, summary):
    path = save_worksheet_workspace(ctx, sheet, state)
    return result(summary={**summary, "worksheetId": sheet.id, "worksheetPath": path})


def _time():
    return datetime.now(UTC).isoformat(timespec="seconds")


@feature(
    "documentsWorksheetValidation.checkCell",
    "Check Cell",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("cell", "Cell address", "A1"),
        select(
            "type",
            "Expected content",
            [
                ("numeric", "Numeric"),
                ("formula", "Formula"),
                ("nonempty", "Non-empty"),
                ("positive", "Positive numeric"),
            ],
            "numeric",
        ),
    ],
)
def check_cell(ctx: FeatureContext, values: dict) -> dict:
    """Validate a cell against a selected content rule and store a cell-scoped diagnostic."""
    sheet, state = _open(ctx, values)
    address = values["cell"].upper()
    cell = state.get("cells", {}).get(address, {})
    problem = None
    if values["type"] == "nonempty" and not cell:
        problem = "Cell is empty."
    elif values["type"] == "formula" and "formula" not in cell:
        problem = "Cell does not contain a formula."
    elif values["type"] in ("numeric", "positive"):
        try:
            number = cell_value(address, state)
        except FeatureInputError as exc:
            problem = str(exc)
        else:
            if values["type"] == "positive" and number <= 0:
                problem = "Value must be greater than zero."
    state.setdefault("validationResults", {})[address] = {
        "valid": problem is None,
        "problem": problem,
        "checkedAt": _time(),
    }
    _save(ctx, sheet, state, {"cell": address, "valid": problem is None, "problem": problem})
    return result(summary={"cell": address, "valid": problem is None, "problem": problem})


@feature(
    "documentsWorksheetValidation.checkRange",
    "Check Range",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:A10"),
        select(
            "type",
            "Check",
            [("numeric", "All numeric"), ("nonempty", "No blanks"), ("formula", "All formulas")],
            "numeric",
        ),
    ],
)
def check_range(ctx: FeatureContext, values: dict) -> dict:
    """Check each cell in a range and list the addresses that do not satisfy the selected rule."""
    sheet, state = _open(ctx, values)
    errors = []
    for address in range_cells(values["range"]):
        cell = state.get("cells", {}).get(address, {})
        problem = None
        if values["type"] == "nonempty" and not cell:
            problem = "blank"
        elif values["type"] == "formula" and "formula" not in cell:
            problem = "notFormula"
        elif values["type"] == "numeric":
            try:
                cell_value(address, state)
            except FeatureInputError:
                problem = "notNumeric"
        state.setdefault("validationResults", {})[address] = {
            "valid": problem is None,
            "problem": problem,
            "checkedAt": _time(),
        }
        if problem:
            errors.append({"cell": address, "problem": problem})
    _save(
        ctx,
        sheet,
        state,
        {"checkedCells": len(range_cells(values["range"])), "invalidCells": len(errors)},
    )
    return result(
        summary={"checkedCells": len(range_cells(values["range"])), "invalidCells": len(errors)},
        tables=[
            {
                "title": "Invalid cells",
                "columns": [
                    {"key": "cell", "title": "Cell"},
                    {"key": "problem", "title": "Problem"},
                ],
                "rows": errors,
            }
        ],
    )


@feature(
    "documentsWorksheetValidation.flagErrors",
    "Flag Errors",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:Z100"),
        text("label", "Flag label", "Review"),
    ],
)
def flag_errors(ctx: FeatureContext, values: dict) -> dict:
    """Mark formula cells that fail evaluation or validation with an explicit review flag."""
    sheet, state = _open(ctx, values)
    flagged = []
    for address in range_cells(values["range"]):
        cell = state.get("cells", {}).get(address, {})
        if "formula" in cell:
            try:
                cell_value(address, state)
            except FeatureInputError as exc:
                ensure_cell(state, address)["errorFlag"] = {
                    "label": values["label"],
                    "problem": str(exc),
                }
                flagged.append(address)
    return _save(ctx, sheet, state, {"flaggedCells": flagged, "count": len(flagged)})


@feature(
    "documentsWorksheetValidation.ignoreCell",
    "Ignore Cell",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("cell", "Cell address", "A1"),
        text("reason", "Reason", "Intentional blank"),
    ],
)
def ignore_cell(ctx: FeatureContext, values: dict) -> dict:
    """Record a reason why a cell should be excluded from validation summaries."""
    sheet, state = _open(ctx, values)
    ensure_cell(state, values["cell"])["validationIgnore"] = {
        "reason": values["reason"].strip(),
        "at": _time(),
    }
    return _save(
        ctx, sheet, state, {"ignoredCell": values["cell"], "reason": values["reason"].strip()}
    )


@feature(
    "documentsWorksheetValidation.tracePrecedents",
    "Trace Precedents",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("cell", "Formula cell", "B1"),
    ],
)
def trace_precedents(ctx: FeatureContext, values: dict) -> dict:
    """Find direct cell references used by a formula and save an upstream dependency trace."""
    sheet, state = _open(ctx, values)
    formula = state.get("cells", {}).get(values["cell"].upper(), {}).get("formula")
    if not formula:
        raise FeatureInputError("Selected cell has no formula to trace.")
    refs = sorted(
        set(re.findall(r"\b[A-Z]{1,3}[1-9][0-9]*\b", formula.upper())) - {values["cell"].upper()}
    )
    state.setdefault("formulaTraces", {})[values["cell"].upper()] = {
        "precedents": refs,
        "at": _time(),
    }
    _save(ctx, sheet, state, {"cell": values["cell"], "precedents": refs})
    return result(summary={"cell": values["cell"], "precedents": refs})


@feature(
    "documentsWorksheetValidation.traceDependents",
    "Trace Dependents",
    part="documents",
    fields=[text("worksheetId", "Worksheet id", "calculations"), text("cell", "Source cell", "A1")],
)
def trace_dependents(ctx: FeatureContext, values: dict) -> dict:
    """Find formula cells that directly depend on a selected source cell."""
    sheet, state = _open(ctx, values)
    target = values["cell"].upper()
    dependents = []
    for address, cell in state.get("cells", {}).items():
        if "formula" in cell and target in re.findall(
            r"\b[A-Z]{1,3}[1-9][0-9]*\b", cell["formula"].upper()
        ):
            dependents.append(address)
    state.setdefault("formulaTraces", {})[target] = {
        "dependents": sorted(dependents),
        "at": _time(),
    }
    _save(ctx, sheet, state, {"sourceCell": target, "dependentCells": sorted(dependents)})
    return result(summary={"sourceCell": target, "dependentCells": sorted(dependents)})


@feature(
    "documentsWorksheetValidation.showFormula",
    "Show Formula",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("cell", "Cell address", "B1"),
    ],
)
def show_formula(ctx: FeatureContext, values: dict) -> dict:
    """Return the selected cell's formula, evaluated value and its direct cell references."""
    _sheet, state = _open(ctx, values)
    cell = state.get("cells", {}).get(values["cell"].upper(), {})
    formula = cell.get("formula")
    if formula is None:
        raise FeatureInputError("Selected cell contains a literal value rather than a formula.")
    value = cell_value(values["cell"], state)
    refs = sorted(set(re.findall(r"\b[A-Z]{1,3}[1-9][0-9]*\b", formula.upper())))
    return result(
        summary={"cell": values["cell"], "formula": formula, "value": value, "precedents": refs}
    )


@feature(
    "documentsWorksheetValidation.breakLink",
    "Break Link",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Linked cell range", "A1:A10"),
    ],
)
def break_link(ctx: FeatureContext, values: dict) -> dict:
    """Freeze current values for linked cells and remove their refreshable project data links."""
    sheet, state = _open(ctx, values)
    removed = []
    for address in range_cells(values["range"]):
        link = state.get("links", {}).pop(address, None)
        if link:
            cell = ensure_cell(state, address)
            cell.pop("formula", None)
            removed.append(address)
    return _save(ctx, sheet, state, {"brokenLinks": removed, "count": len(removed)})


@feature(
    "documentsWorksheetValidation.changeLog",
    "Change Log",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        number("limit", "Recent changes", 50, min=1, max=500),
    ],
)
def change_log(ctx: FeatureContext, values: dict) -> dict:
    """List timestamped worksheet edit records, newest first."""
    _sheet, state = _open(ctx, values)
    rows = list(reversed(state.get("changes", [])[-int(values["limit"]) :]))
    return result(
        summary={"changeCount": len(rows)},
        tables=[
            {
                "title": "Worksheet changes",
                "columns": [
                    {"key": "at", "title": "Changed at"},
                    {"key": "action", "title": "Action"},
                    {"key": "cell", "title": "Cell"},
                    {"key": "actor", "title": "Actor"},
                ],
                "rows": rows,
            }
        ],
    )


@feature(
    "documentsWorksheetValidation.lockSheet",
    "Lock Sheet",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        checkbox("lock", "Lock worksheet", True),
        text("actor", "Changed by", "Engineer"),
    ],
)
def lock_sheet(ctx: FeatureContext, values: dict) -> dict:
    """Lock or unlock a worksheet and record the responsible engineer and timestamp."""
    sheet, state = _open(ctx, values)
    state.setdefault("settings", {})["sheetLock"] = {
        "locked": values["lock"],
        "actor": values["actor"],
        "at": _time(),
    }
    return _save(ctx, sheet, state, {"locked": values["lock"], "actor": values["actor"]})


@feature(
    "documentsWorksheetValidation.protectCells",
    "Protect Cells",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:B10"),
        checkbox("protected", "Protect selected cells", True),
    ],
)
def protect_cells(ctx: FeatureContext, values: dict) -> dict:
    """Set per-cell edit protection without changing the protection state of other cells."""
    sheet, state = _open(ctx, values)
    cells = range_cells(values["range"])
    for address in cells:
        ensure_cell(state, address)["protected"] = values["protected"]
    return _save(
        ctx,
        sheet,
        state,
        {
            "protectedCells": len(cells) if values["protected"] else 0,
            "unprotectedCells": 0 if values["protected"] else len(cells),
        },
    )


@feature(
    "documentsWorksheetValidation.restoreVersion",
    "Restore Version",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        number("versionIndex", "Version index (0 is oldest)", 0, min=0),
    ],
)
def restore_version(ctx: FeatureContext, values: dict) -> dict:
    """Restore worksheet cell and view data from a recorded version snapshot."""
    sheet, state = _open(ctx, values)
    versions = state.get("versions", [])
    index = int(values["versionIndex"])
    if index >= len(versions):
        raise FeatureInputError("That worksheet version does not exist.")
    current = {key: value for key, value in state.items() if key != "versions"}
    snapshot = versions[index].get("snapshot", {})
    state.clear()
    state.update(snapshot)
    state["versions"] = versions
    state.setdefault("changes", []).append(
        {
            "at": _time(),
            "action": "restoreVersion",
            "versionIndex": index,
            "restoredKeys": sorted(current),
        }
    )
    return _save(ctx, sheet, state, {"restoredVersion": index, "versionCount": len(versions)})


@feature(
    "documentsWorksheetValidation.rangeRule",
    "Range Rule",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:A10"),
        number("minimum", "Minimum", 0),
        number("maximum", "Maximum", 100),
    ],
)
def range_rule(ctx: FeatureContext, values: dict) -> dict:
    """Add a numeric lower and upper bound for every cell in a selected range."""
    if values["minimum"] > values["maximum"]:
        raise FeatureInputError("Minimum cannot exceed maximum.")
    sheet, state = _open(ctx, values)
    cells = range_cells(values["range"])
    rule = {
        "range": values["range"],
        "type": "numberBetween",
        "min": values["minimum"],
        "max": values["maximum"],
    }
    state.setdefault("validations", []).append(rule)
    return _save(
        ctx,
        sheet,
        state,
        {"ruleIndex": len(state["validations"]) - 1, "validatedCells": len(cells)},
    )


@feature(
    "documentsWorksheetValidation.typeRule",
    "Type Rule",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:A10"),
        select(
            "type",
            "Required type",
            [
                ("number", "Number"),
                ("text", "Text"),
                ("formula", "Formula"),
                ("boolean", "Boolean"),
            ],
            "number",
        ),
    ],
)
def type_rule(ctx: FeatureContext, values: dict) -> dict:
    """Attach a required data type rule and immediately report existing cells that violate it."""
    sheet, state = _open(ctx, values)
    bad = []
    for address in range_cells(values["range"]):
        cell = state.get("cells", {}).get(address, {})
        if values["type"] == "number":
            ok = isinstance(cell.get("value"), (int, float)) or "formula" in cell
        elif values["type"] == "text":
            ok = isinstance(cell.get("value"), str)
        elif values["type"] == "formula":
            ok = "formula" in cell
        else:
            ok = isinstance(cell.get("value"), bool)
        if not ok:
            bad.append(address)
    state.setdefault("validations", []).append({"range": values["range"], "type": values["type"]})
    return _save(ctx, sheet, state, {"type": values["type"], "invalidExistingCells": bad})


@feature(
    "documentsWorksheetValidation.customExpression",
    "Custom Expression",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cells to check", "A1:A10"),
        text("expression", "Boolean expression", "A1>0"),
    ],
)
def custom_expression(ctx: FeatureContext, values: dict) -> dict:
    """Validate each row in a range against a safe arithmetic comparison expression."""
    import operator

    sheet, state = _open(ctx, values)
    bad = []
    ops = {
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
    }
    try:
        tree = ast.parse(values["expression"], mode="eval").body
    except SyntaxError as exc:
        raise FeatureInputError("Expression syntax is invalid.") from exc
    if not isinstance(tree, ast.Compare) or len(tree.ops) != 1 or type(tree.ops[0]) not in ops:
        raise FeatureInputError("Use a single comparison such as A1>0.")
    cells = range_cells(values["range"])
    for address in cells:
        row, _ = parse_cell(address)

        def val(node, current_row=row):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return float(node.value)
            if isinstance(node, ast.Name) and re.fullmatch(
                r"[A-Z]{1,3}[1-9][0-9]*", node.id.upper()
            ):
                _, cc = parse_cell(node.id)
                return cell_value(cell_address(current_row, cc), state)
            raise FeatureInputError(
                "Expression can use cell references and numeric constants only."
            )

        if not ops[type(tree.ops[0])](val(tree.left), val(tree.comparators[0])):
            bad.append(address)
    state.setdefault("validations", []).append(
        {"range": values["range"], "expression": values["expression"]}
    )
    return _save(ctx, sheet, state, {"checkedCells": len(cells), "invalidCells": bad})


@feature(
    "documentsWorksheetValidation.clearRules",
    "Clear Rules",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:A10"),
    ],
)
def clear_rules(ctx: FeatureContext, values: dict) -> dict:
    """Remove validation and conditional-style rules that overlap a selected cell range."""
    sheet, state = _open(ctx, values)
    selected = set(range_cells(values["range"]))
    kept = []
    removed = 0
    for rule in state.get("validations", []):
        if selected.intersection(range_cells(rule.get("range", values["range"]))):
            removed += 1
        else:
            kept.append(rule)
    state["validations"] = kept
    conditional = []
    for rule in state.get("conditionalStyles", []):
        if selected.intersection(range_cells(rule.get("range", values["range"]))):
            removed += 1
        else:
            conditional.append(rule)
    state["conditionalStyles"] = conditional
    return _save(
        ctx, sheet, state, {"removedRules": removed, "remainingRules": len(kept) + len(conditional)}
    )


@feature(
    "documentsWorksheetValidation.stressTest",
    "Stress Test",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("formulaCell", "Result formula cell", "C1"),
        text("variableCell", "Input cell", "A1"),
        number("minimum", "Minimum input", 0),
        number("maximum", "Maximum input", 10),
        number("steps", "Test points", 101, min=2, max=5001),
    ],
)
def stress_test(ctx: FeatureContext, values: dict) -> dict:
    """Evaluate a formula across a bounded input sweep and report minimum, maximum and non-finite results."""
    sheet, state = _open(ctx, values)
    cell = ensure_cell(state, values["variableCell"])
    original = cell.get("value", 0)
    rows = []
    steps = int(values["steps"])
    for i in range(steps):
        x = values["minimum"] + (values["maximum"] - values["minimum"]) * i / (steps - 1)
        cell["value"] = x
        try:
            y = cell_value(values["formulaCell"], state)
            rows.append({"input": x, "result": y, "valid": math.isfinite(y)})
        except (FeatureInputError, OverflowError) as exc:
            rows.append({"input": x, "result": None, "valid": False, "problem": str(exc)})
    cell["value"] = original
    valid = [r["result"] for r in rows if r["valid"]]
    _save(
        ctx,
        sheet,
        state,
        {"testPoints": steps, "validPoints": len(valid), "invalidPoints": steps - len(valid)},
    )
    return result(
        summary={
            "testPoints": steps,
            "validPoints": len(valid),
            "minimumResult": min(valid) if valid else None,
            "maximumResult": max(valid) if valid else None,
        },
        tables=[
            {
                "title": "Stress test",
                "columns": [
                    {"key": "input", "title": "Input"},
                    {"key": "result", "title": "Result"},
                    {"key": "valid", "title": "Valid"},
                ],
                "rows": rows,
            }
        ],
    )


@feature(
    "documentsWorksheetValidation.nanScanner",
    "NaN Scanner",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:Z100"),
    ],
)
def nan_scanner(ctx: FeatureContext, values: dict) -> dict:
    """Find cells containing non-finite numeric values or formulas that evaluate to them."""
    sheet, state = _open(ctx, values)
    found = []
    for address in range_cells(values["range"]):
        try:
            value = cell_value(address, state)
        except FeatureInputError:
            continue
        if not math.isfinite(value):
            found.append({"cell": address, "value": str(value)})
    state.setdefault("settings", {})["nanScan"] = {"at": _time(), "cells": found}
    return _save(ctx, sheet, state, {"nonFiniteCells": found, "count": len(found)})


@feature(
    "documentsWorksheetValidation.circularCheck",
    "Circular Check",
    part="documents",
    fields=[text("worksheetId", "Worksheet id", "calculations")],
)
def circular_check(ctx: FeatureContext, values: dict) -> dict:
    """Detect formula dependency cycles across the worksheet and list the involved cells."""
    sheet, state = _open(ctx, values)
    cycles = []
    for address, cell in state.get("cells", {}).items():
        if "formula" not in cell:
            continue
        try:
            cell_value(address, state)
        except FeatureInputError as exc:
            if "cycle" in str(exc).lower():
                cycles.append({"cell": address, "problem": str(exc)})
    state.setdefault("settings", {})["circularCheck"] = {"at": _time(), "cycles": cycles}
    return _save(
        ctx, sheet, state, {"cycleCount": len(cycles), "cells": [item["cell"] for item in cycles]}
    )


@feature(
    "documentsWorksheetValidation.validationSummary",
    "Validation Summary",
    part="documents",
    fields=[text("worksheetId", "Worksheet id", "calculations")],
)
def validation_summary(ctx: FeatureContext, values: dict) -> dict:
    """Summarize validation flags, ignored cells, rules and last formula audit results."""
    _sheet, state = _open(ctx, values)
    results = state.get("validationResults", {})
    invalid = [
        {"cell": a, **v}
        for a, v in results.items()
        if not v.get("valid") and a not in state.get("ignoredCells", [])
    ]
    return result(
        summary={
            "ruleCount": len(state.get("validations", [])),
            "checkedCells": len(results),
            "invalidCells": len(invalid),
            "ignoredCells": len(state.get("ignoredCells", [])),
        },
        tables=[
            {
                "title": "Validation failures",
                "columns": [
                    {"key": "cell", "title": "Cell"},
                    {"key": "problem", "title": "Problem"},
                ],
                "rows": invalid,
            }
        ],
    )


@feature(
    "documentsWorksheetValidation.errorHeatmap",
    "Error Heatmap",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:Z100"),
    ],
)
def error_heatmap(ctx: FeatureContext, values: dict) -> dict:
    """Create a row and column density map of formula and validation errors for a selected range."""
    sheet, state = _open(ctx, values)
    heat = {}
    bad = []
    for address in range_cells(values["range"]):
        cell = state.get("cells", {}).get(address, {})
        invalid = not state.get("validationResults", {}).get(address, {}).get("valid", True)
        if "formula" in cell:
            try:
                cell_value(address, state)
            except FeatureInputError:
                invalid = True
        if invalid:
            row, col = parse_cell(address)
            heat.setdefault(str(row), {})[cell_address(1, col)[:-1]] = (
                heat.setdefault(str(row), {}).get(cell_address(1, col)[:-1], 0) + 1
            )
            bad.append(address)
    state.setdefault("settings", {})["errorHeatmap"] = {
        "range": values["range"],
        "density": heat,
        "at": _time(),
    }
    return _save(ctx, sheet, state, {"errorCells": len(bad), "rowColumnDensity": heat})

"""User-defined schedules over project drawing data.

Definitions are JSON-compatible mappings. Calculated fields are arithmetic expressions with
numeric literals, field names, and +, -, *, / only; expressions are interpreted from their AST
and never evaluated as Python code.
"""

from __future__ import annotations

import ast
import csv
import io
import operator
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from saengine.drawings.sheets.model import Table

_ARITHMETIC = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_COMPARISONS = {
    "=": operator.eq,
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}


@dataclass
class ScheduleResult:
    """A user schedule in the forms used by sheets, CSV and the Excel table exporter."""

    title: str
    columns: list[str]
    rows: list[list[Any]]
    table: Table
    notes: list[str]

    def csv_text(self) -> str:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(self.columns)
        writer.writerows(self.rows)
        return stream.getvalue()

    def write_csv(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.csv_text(), encoding="utf-8-sig", newline="")
        return target

    def add_to_sheet(self, sheet: Any) -> list[Any]:
        """Render this table on a sheet with the existing table layout and text standards."""
        from saengine.drawings.sheets.schedules import table_specs

        specs = table_specs(
            self.table,
            sheet.area[3] - sheet.area[1],
            key=f"user-schedule:{self.title}",
            max_width=sheet.area[2] - sheet.area[0],
        )
        return [sheet.view(spec, *sheet.area[:2]) for spec in specs]

    def write_xlsx(self, path: str | Path) -> dict[str, Any]:
        from saengine.fem.table_export import write_xlsx

        return write_xlsx(
            path,
            [{"name": self.title, "columns": self.columns, "rows": self.rows, "notes": self.notes}],
        )


def _eval_node(node: ast.AST, values: Mapping[str, Any]) -> float:
    if (
        isinstance(node, ast.Constant)
        and not isinstance(node.value, bool)
        and isinstance(node.value, (int, float))
    ):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise ValueError(f"unknown calculated-field name '{node.id}'")
        value = values[node.id]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"calculated-field name '{node.id}' is not numeric")
        return float(value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand, values)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and type(node.op) in _ARITHMETIC:
        left, right = _eval_node(node.left, values), _eval_node(node.right, values)
        if isinstance(node.op, ast.Div) and right == 0:
            raise ValueError("division by zero in calculated field")
        return _ARITHMETIC[type(node.op)](left, right)
    raise ValueError(
        "calculated fields allow only numbers, field names, +, -, *, / and parentheses"
    )


def evaluate_expression(expression: str, values: Mapping[str, Any]) -> float:
    """Evaluate one arithmetic field expression without executing Python."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as error:
        raise ValueError(f"invalid calculated-field expression: {expression!r}") from error
    return _eval_node(tree.body, values)


def _passes(record: Mapping[str, Any], filters: Sequence[Mapping[str, Any]]) -> bool:
    for rule in filters:
        field = str(rule.get("field") or "")
        if field not in record:
            raise ValueError(f"schedule filter field '{field}' is missing from a category record")
        op = str(rule.get("operator") or "==").lower()
        actual, expected = record[field], rule.get("value")
        if op == "contains":
            passed = str(expected) in str(actual)
        elif op == "in":
            try:
                passed = actual in expected
            except TypeError as error:
                raise ValueError(
                    f"schedule filter '{field}' requires a collection value"
                ) from error
        else:
            comparison = _COMPARISONS.get(op)
            if comparison is None:
                raise ValueError(f"unsupported schedule filter operator '{op}'")
            try:
                passed = comparison(actual, expected)
            except TypeError as error:
                raise ValueError(f"incompatible filter values for '{field}'") from error
        if not passed:
            return False
    return True


def _display(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return "" if value is None else value


def _total(records: Sequence[Mapping[str, Any]], field: str) -> Any:
    if field == "count":
        return sum(record.get("count", 1) for record in records)
    values = [record.get(field) for record in records]
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        return sum(values)
    raise ValueError(f"schedule total '{field}' must be numeric or 'count'")


def build_schedule(
    definition: Mapping[str, Any],
    categories: Mapping[str, Sequence[Mapping[str, Any]]] | Sequence[Mapping[str, Any]],
) -> ScheduleResult:
    """Build a table from the named category, applying filters, calculations, groups and totals.

    Definition keys: ``category``, ``fields``, optional ``filters``, ``sort``, ``groupBy``,
    ``totals``, and ``itemize``. Filters are ANDed. With itemize disabled, identical displayed
    rows become one row with a Count column.
    """
    category = str(definition.get("category") or "")
    if not category:
        raise ValueError("schedule definition requires a category")
    if isinstance(categories, Mapping):
        if category not in categories:
            raise ValueError(f"schedule category '{category}' is not available")
        source = categories[category]
    else:
        source = categories
    fields = [dict(item) for item in definition.get("fields") or []]
    if not fields:
        raise ValueError("schedule definition requires at least one field")
    keys = [str(field.get("key") or "") for field in fields]
    if any(not key for key in keys) or len(set(keys)) != len(keys):
        raise ValueError("schedule fields require unique, non-empty keys")
    filters = [dict(item) for item in definition.get("filters") or []]
    records = [dict(row) for row in source if _passes(row, filters)]
    for field in fields:
        if field.get("expression") is not None:
            key = str(field["key"])
            for record in records:
                record[key] = evaluate_expression(str(field["expression"]), record)
    for field in fields:
        if field.get("expression") is None:
            missing = [row for row in records if str(field["key"]) not in row]
            if missing:
                raise ValueError(
                    f"schedule field '{field['key']}' is missing from a category record"
                )

    sort_fields = definition.get("sort") or []
    for item in reversed(sort_fields):
        if isinstance(item, str):
            field, descending = item, False
        else:
            field = str(item.get("field") or "")
            order = str(item.get("order") or "asc").lower()
            if order not in ("asc", "desc"):
                raise ValueError(f"unsupported schedule sort order '{order}'")
            descending = order == "desc"
        if field not in keys:
            raise ValueError(f"unknown schedule sort field '{field}'")
        records.sort(key=lambda row: (row.get(field) is None, row.get(field)), reverse=descending)

    group_by = [str(value) for value in definition.get("groupBy") or []]
    if any(field not in keys for field in group_by):
        raise ValueError("schedule group fields must be listed in fields")
    totals = [str(value) for value in definition.get("totals") or []]
    if any(field != "count" and field not in keys for field in totals):
        raise ValueError("schedule total fields must be listed in fields or be 'count'")
    itemize = bool(definition.get("itemize", True))
    titles = [str(field.get("title") or field["key"]) for field in fields]
    count_column = not itemize or "count" in totals
    columns = titles + (["Count"] if count_column else [])
    row_items = [[_display(record.get(key)) for key in keys] for record in records]
    if itemize and count_column:
        row_items = [row + [1] for row in row_items]
    if not itemize:
        grouped: dict[tuple[Any, ...], int] = {}
        for row in row_items:
            grouped[tuple(row)] = grouped.get(tuple(row), 0) + 1
        row_items = [list(row) + [count] for row, count in grouped.items()]
        records = []
        for row, count in grouped.items():
            record = dict(zip(keys, row, strict=True))
            record["count"] = count
            records.append(record)

    table_rows: list[list[str]] = []
    row_groups: list[dict[str, int]] = []
    if group_by:
        groups: dict[tuple[Any, ...], list[int]] = {}
        for index, record in enumerate(records):
            groups.setdefault(tuple(record[field] for field in group_by), []).append(index)
        field_titles = {
            str(field["key"]): str(field.get("title") or field["key"]) for field in fields
        }
        for group_values, indexes in sorted(
            groups.items(), key=lambda item: tuple(str(value).casefold() for value in item[0])
        ):
            group_start = len(table_rows)
            label = " / ".join(
                f"{field_titles[field]}: {_display(value)}"
                for field, value in zip(group_by, group_values, strict=True)
            )
            table_rows.append([label, *("" for _ in range(len(columns) - 1))])
            table_rows.extend([str(value) for value in row_items[index]] for index in indexes)
            if totals:
                footer = ["TOTAL", *("" for _ in range(len(columns) - 1))]
                for field in totals:
                    value = _total([records[index] for index in indexes], field)
                    column_index = keys.index(field) if field in keys else len(keys)
                    if column_index < len(footer):
                        footer[column_index] = str(_display(value))
                table_rows.append(footer)
            row_groups.append({"first": group_start, "count": len(table_rows) - group_start})
    else:
        table_rows = [[str(value) for value in row] for row in row_items]
    if totals:
        total_row = ["GRAND TOTAL", *("" for _ in range(len(columns) - 1))]
        for field in totals:
            value = _total(records, field)
            column_index = keys.index(field) if field in keys else len(keys)
            if column_index < len(total_row):
                total_row[column_index] = str(_display(value))
        table_rows.append(total_row)

    title = str(definition.get("name") or f"{category.title()} schedule")
    table = Table(
        title,
        [
            {
                "key": str(field["key"]),
                "title": titles[index],
                **({"align": "right"} if field.get("align") == "right" else {}),
            }
            for index, field in enumerate(fields)
        ]
        + ([{"key": "count", "title": "Count", "align": "right"}] if count_column else []),
        table_rows,
        row_groups,
    )
    return ScheduleResult(title, columns, table_rows, table, [])


__all__ = ["ScheduleResult", "build_schedule", "evaluate_expression"]

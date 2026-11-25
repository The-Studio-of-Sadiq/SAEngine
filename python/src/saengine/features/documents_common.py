"""Shared document workspace IO and worksheet mechanics for Documents features."""

from __future__ import annotations

import ast
import copy
import csv
import json
import math
import operator
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from saengine.features import FeatureContext, FeatureInputError

DOCUMENTS_FOLDER = "11 Exports/documents"
CELL_PATTERN = re.compile(r"^\$?([A-Z]{1,3})\$?([1-9][0-9]*)$", re.IGNORECASE)


def require_root(ctx: FeatureContext) -> Path:
    if ctx.root is None:
        raise FeatureInputError("Open a project to edit its documents.")
    return ctx.root


def read_json(ctx: FeatureContext, relative: str, default: Any) -> Any:
    root = require_root(ctx)
    path = root / relative
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FeatureInputError(f"The document data file {relative} is unreadable JSON.") from exc


def write_json(ctx: FeatureContext, relative: str, data: Any) -> str:
    root = require_root(ctx)
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    return path.relative_to(root).as_posix()


def document_state(ctx: FeatureContext, domain: str) -> dict[str, Any]:
    relative = f"{DOCUMENTS_FOLDER}/{domain}.json"
    state = read_json(ctx, relative, {"schema": f"saengine.documents.{domain}/1"})
    if not isinstance(state, dict) or state.get("schema") != f"saengine.documents.{domain}/1":
        raise FeatureInputError(f"The {domain} workspace has an unsupported schema.")
    return state


def save_document_state(ctx: FeatureContext, domain: str, state: dict[str, Any]) -> str:
    state["schema"] = f"saengine.documents.{domain}/1"
    return write_json(ctx, f"{DOCUMENTS_FOLDER}/{domain}.json", state)


def parse_cell(address: str) -> tuple[int, int]:
    match = CELL_PATTERN.fullmatch(address.strip())
    if not match:
        raise FeatureInputError("Use a cell reference such as A1 or BC24.")
    col = 0
    for char in match.group(1).upper():
        col = col * 26 + ord(char) - 64
    return int(match.group(2)), col


def cell_address(row: int, col: int) -> str:
    if row < 1 or col < 1:
        raise FeatureInputError("Worksheet row and column numbers start at 1.")
    letters = ""
    while col:
        col, remainder = divmod(col - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row}"


def worksheet_workspace(ctx: FeatureContext, worksheet_id: str) -> tuple[Any, dict[str, Any]]:
    root = require_root(ctx)
    safe_id = worksheet_id.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", safe_id):
        raise FeatureInputError("Worksheet id must use lowercase letters, digits and hyphens.")
    from saengine.library.worksheet import Worksheet, read_worksheet, worksheet_path

    path = worksheet_path(root, safe_id)
    if path.is_file():
        sheet, problem = read_worksheet(path)
        if sheet is None:
            raise FeatureInputError(str(problem))
    else:
        sheet = Worksheet(id=safe_id, kind="calculation", title=safe_id.replace("-", " ").title())
    state_path = f"11 Exports/worksheets/{safe_id}.workspace.json"
    state = read_json(
        ctx,
        state_path,
        {
            "schema": "saengine.worksheetWorkspace/1",
            "id": safe_id,
            "cells": {},
            "names": {},
            "merges": [],
            "validations": [],
            "comments": [],
            "changes": [],
            "links": {},
            "charts": [],
            "settings": {"showGridlines": True, "zoom": 100, "freeze": {"rows": 0, "columns": 0}},
        },
    )
    if not isinstance(state, dict) or state.get("schema") != "saengine.worksheetWorkspace/1":
        raise FeatureInputError("The worksheet workspace has an unsupported schema.")
    return sheet, state


def save_worksheet_workspace(ctx: FeatureContext, sheet: Any, state: dict[str, Any]) -> str:
    from saengine.library.worksheet import save_worksheet

    snapshot = {key: copy.deepcopy(value) for key, value in state.items() if key != "versions"}
    versions = state.setdefault("versions", [])
    versions.append(
        {
            "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
            "snapshot": snapshot,
        }
    )
    del versions[:-50]
    sheet_path = save_worksheet(require_root(ctx), sheet)
    state["schema"] = "saengine.worksheetWorkspace/1"
    write_json(ctx, f"11 Exports/worksheets/{sheet.id}.workspace.json", state)
    return sheet_path.relative_to(require_root(ctx)).as_posix()


def ensure_cell(state: dict[str, Any], address: str) -> dict[str, Any]:
    parse_cell(address)
    return state.setdefault("cells", {}).setdefault(address.upper().replace("$", ""), {})


def range_cells(address: str) -> list[str]:
    pieces = address.strip().upper().split(":")
    if len(pieces) == 1:
        parse_cell(pieces[0])
        return [pieces[0].replace("$", "")]
    if len(pieces) != 2:
        raise FeatureInputError("Use one cell such as A1 or a range such as A1:C8.")
    r0, c0 = parse_cell(pieces[0])
    r1, c1 = parse_cell(pieces[1])
    if r1 < r0 or c1 < c0 or (r1 - r0 + 1) * (c1 - c0 + 1) > 10000:
        raise FeatureInputError("Select a forward range containing no more than 10,000 cells.")
    return [cell_address(row, col) for row in range(r0, r1 + 1) for col in range(c0, c1 + 1)]


def _safe_eval(node: ast.AST, state: dict[str, Any], visiting: set[str]) -> float:
    binary = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
    }
    unary = {ast.UAdd: operator.pos, ast.USub: operator.neg}
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return float(node.value)
    if isinstance(node, ast.Name):
        name = node.id.upper()
        if name.startswith("RANGE_"):
            return float(
                sum(
                    cell_value(ref, state, visiting)
                    for ref in range_cells(name[6:].replace("_", ":", 1))
                )
            )
        if CELL_PATTERN.fullmatch(name):
            return cell_value(name, state, visiting)
        if name in state.get("names", {}):
            return float(state["names"][name])
        raise FeatureInputError(f"Formula variable {node.id} is not defined.")
    if isinstance(node, ast.BinOp) and type(node.op) in binary:
        try:
            return float(
                binary[type(node.op)](
                    _safe_eval(node.left, state, visiting), _safe_eval(node.right, state, visiting)
                )
            )
        except (ArithmeticError, OverflowError) as exc:
            raise FeatureInputError(
                "The formula has a zero divisor or an invalid numeric result."
            ) from exc
    if isinstance(node, ast.UnaryOp) and type(node.op) in unary:
        return float(unary[type(node.op)](_safe_eval(node.operand, state, visiting)))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = node.func.id.upper()
        if fn == "SUM":
            values = []
            for arg in node.args:
                if isinstance(arg, ast.Name) and ":" in arg.id:
                    values.extend(cell_value(ref, state, visiting) for ref in range_cells(arg.id))
                else:
                    values.append(_safe_eval(arg, state, visiting))
            return float(sum(values))
        functions = {
            "ABS": abs,
            "SQRT": math.sqrt,
            "SIN": math.sin,
            "COS": math.cos,
            "TAN": math.tan,
            "MIN": min,
            "MAX": max,
        }
        if fn in functions:
            return float(functions[fn](*[_safe_eval(arg, state, visiting) for arg in node.args]))
    raise FeatureInputError(
        "Formula supports numbers, cell references, + - * / ^, SUM, MIN, MAX, ABS, SQRT, SIN, COS and TAN."
    )


def cell_value(address: str, state: dict[str, Any], visiting: set[str] | None = None) -> float:
    key = address.upper().replace("$", "")
    visiting = visiting or set()
    if key in visiting:
        raise FeatureInputError(f"Formula dependency cycle includes {key}.")
    cell = state.get("cells", {}).get(key, {})
    if "formula" not in cell:
        try:
            return float(cell.get("value", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise FeatureInputError(f"Cell {key} does not contain a numeric value.") from exc
    expression = str(cell["formula"]).strip().lstrip("=").replace("^", "**")
    expression = re.sub(
        r"([A-Z]{1,3}[0-9]+):([A-Z]{1,3}[0-9]+)", r"RANGE_\1_\2", expression, flags=re.IGNORECASE
    )
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise FeatureInputError(f"The formula in {key} has invalid syntax.") from exc
    return _safe_eval(tree.body, state, visiting | {key})


def project_fields(ctx: FeatureContext) -> dict[str, Any]:
    if ctx.root is None:
        return {}
    fields: dict[str, Any] = {}
    for part in ctx.PART_FILES:
        data = ctx.raw(part)
        if data is not None:
            fields[part] = data
    return fields


def dotted_value(data: Any, path: str) -> Any:
    current = data
    for bit in path.split("."):
        if isinstance(current, dict):
            current = current.get(bit)
        elif isinstance(current, list) and bit.isdigit() and int(bit) < len(current):
            current = current[int(bit)]
        else:
            return None
    return current


def read_csv_rows(path: Path, delimiter: str = ",") -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream, delimiter=delimiter))
    except (OSError, csv.Error) as exc:
        raise FeatureInputError(f"Could not read tabular file {path.name}: {exc}") from exc


def write_csv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

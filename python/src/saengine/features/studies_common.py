"""Shared data parsing and file writing for project study tools."""

from __future__ import annotations

import csv
import io
import json
import math
import re
from typing import Any

from saengine.features import FeatureContext, FeatureInputError


def records(value: str, label: str) -> list[dict[str, Any]]:
    """Read a JSON list of records or a CSV table supplied in a panel text field."""
    raw = value.strip()
    if not raw:
        raise FeatureInputError(f"Enter {label} as a JSON list or CSV table.")
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        rows = list(csv.DictReader(io.StringIO(raw)))
        if not rows:
            raise FeatureInputError(
                f"{label.capitalize()} must include a header and at least one row."
            )
        return rows
    if not isinstance(decoded, list) or any(not isinstance(row, dict) for row in decoded):
        raise FeatureInputError(f"{label.capitalize()} must be a list of objects.")
    return decoded


def numbers(value: str, label: str) -> list[float]:
    """Read a comma, semicolon, or whitespace separated series of finite values."""
    try:
        output = [float(item) for item in re.split(r"[,;\s]+", value.strip()) if item]
    except ValueError as error:
        raise FeatureInputError(f"{label.capitalize()} must contain numbers only.") from error
    if not output or any(not math.isfinite(item) for item in output):
        raise FeatureInputError(f"Enter at least one finite value for {label}.")
    return output


def points(value: str, label: str = "survey points") -> list[tuple[float, float, float]]:
    """Read x,y,z point triples, either JSON or delimited text."""
    raw = value.strip()
    try:
        decoded = json.loads(raw)
        found = [(float(p[0]), float(p[1]), float(p[2])) for p in decoded]
    except (ValueError, TypeError, IndexError, json.JSONDecodeError):
        found = []
        for line in raw.splitlines():
            fields = re.split(r"[,;\s]+", line.strip())
            if not fields or not fields[0]:
                continue
            try:
                if len(fields) >= 3:
                    found.append((float(fields[0]), float(fields[1]), float(fields[2])))
            except ValueError as error:
                raise FeatureInputError(
                    f"Each {label} row needs numeric x, y and elevation values."
                ) from error
    if len(found) < 3 or any(not all(math.isfinite(v) for v in row) for row in found):
        raise FeatureInputError(f"Provide at least three finite {label} with x, y and elevation.")
    return found


def write_json(ctx: FeatureContext, relative: str, value: Any) -> str:
    """Write a readable UTF-8 JSON result inside this project's study folder."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to save this study output.")
    root = ctx.root.resolve()
    target = (root / relative).resolve()
    if root not in target.parents:
        raise FeatureInputError("The output path must stay inside the project folder.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target.relative_to(root).as_posix()


def write_text(ctx: FeatureContext, relative: str, value: str) -> str:
    """Write a UTF-8 text deliverable inside the project folder."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to save this output.")
    root = ctx.root.resolve()
    target = (root / relative).resolve()
    if root not in target.parents:
        raise FeatureInputError("The output path must stay inside the project folder.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")
    return target.relative_to(root).as_posix()


def study_path(name: str) -> str:
    """Return a normalized studies output path."""
    slug = re.sub(r"[^a-z0-9-]+", "-", name.casefold()).strip("-") or "study"
    return f"12 Automation/studies/outputs/{slug}.json"


def project_records(ctx: FeatureContext, part: str, key: str) -> list[dict[str, Any]]:
    """Read a named record collection from one project part."""
    data = ctx.raw(part)
    rows = data.get(key) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise FeatureInputError(f"The project's {part} data has no {key} collection.")
    return [row for row in rows if isinstance(row, dict)]


def interpolated_levels(low: float, high: float, count: int) -> list[float]:
    """Inclusive, evenly spaced levels for a deterministic study matrix."""
    if count < 2 or count > 1000 or high < low:
        raise FeatureInputError(
            "Use 2–1000 steps and an upper limit no smaller than the lower limit."
        )
    return [low + (high - low) * i / (count - 1) for i in range(count)]

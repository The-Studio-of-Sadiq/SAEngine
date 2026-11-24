"""Shared read/write helpers for overview project commands."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

from saengine.features import FeatureContext, FeatureInputError


def require_project(ctx: FeatureContext, purpose: str) -> Path:
    if ctx.root is None:
        raise FeatureInputError(f"Open a project before {purpose}.")
    if not ctx.root.is_dir():
        raise FeatureInputError(f"The project folder for {purpose} does not exist.")
    return ctx.root


def list_objects(ctx: FeatureContext) -> list[dict[str, Any]]:
    raw = ctx.raw("objects")
    if not isinstance(raw, dict):
        return []
    objects = raw.get("objects")
    return [item for item in objects if isinstance(item, dict)] if isinstance(objects, list) else []


def list_bim(ctx: FeatureContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw = ctx.raw("bim")
    if not isinstance(raw, dict):
        return [], []
    elements = raw.get("elements")
    stories = raw.get("stories")
    return (
        [item for item in elements if isinstance(item, dict)] if isinstance(elements, list) else [],
        [item for item in stories if isinstance(item, dict)] if isinstance(stories, list) else [],
    )


def boq_items(ctx: FeatureContext) -> list[dict[str, Any]]:
    raw = ctx.raw("boq")
    if not isinstance(raw, dict):
        return []
    items = raw.get("items")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def settings_dict(ctx: FeatureContext) -> dict[str, Any]:
    raw = ctx.raw("settings")
    return raw if isinstance(raw, dict) else {}


def project_name(ctx: FeatureContext) -> str:
    settings = settings_dict(ctx)
    project = settings.get("project")
    if isinstance(project, dict) and isinstance(project.get("name"), str):
        return project["name"]
    return ctx.root.name if ctx.root else "Untitled project"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def write_export(
    ctx: FeatureContext,
    folder: str,
    filename: str,
    content: str,
) -> Path:
    root = require_project(ctx, "writing an export")
    target = root / folder
    target.mkdir(parents=True, exist_ok=True)
    path = target / filename
    path.write_text(content, encoding="utf-8")
    return path


def csv_text(columns: list[str], rows: list[dict[str, Any]]) -> str:
    stream = StringIO()
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def json_text(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def load_export_json(ctx: FeatureContext, folder: str, filename: str, default: Any) -> Any:
    root = require_project(ctx, f"reading {filename}")
    path = root / folder / filename
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise FeatureInputError(f"{filename} is not valid JSON: {error}") from error


def save_export_json(ctx: FeatureContext, folder: str, filename: str, data: Any) -> Path:
    return write_export(ctx, folder, filename, json_text(data))


def project_kpis(ctx: FeatureContext) -> dict[str, Any]:
    elements, stories = list_bim(ctx)
    items = boq_items(ctx)
    amount = round(
        sum(float(i.get("quantity", 0) or 0) * float(i.get("rate", 0) or 0) for i in items), 2
    )
    return {
        "objects": len(list_objects(ctx)),
        "bimElements": len(elements),
        "stories": len(stories),
        "boqItems": len(items),
        "boqAmount": amount,
    }

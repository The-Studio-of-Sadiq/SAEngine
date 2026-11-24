"""Shared architecture feature data and export helpers."""

from __future__ import annotations

import csv
import json
from io import StringIO
from typing import Any

from saengine.features import FeatureContext, FeatureInputError


def require_arch(ctx: FeatureContext) -> Any:
    if ctx.root is None:
        raise FeatureInputError("Open a project before running this architecture feature.")
    path = ctx.root / "05 Floor Plan" / "architecture.json"
    if not path.is_file():
        raise FeatureInputError("Add 05 Floor Plan/architecture.json with architecture data first.")
    try:
        from saengine.library.architecture import parse

        return parse(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise FeatureInputError(f"The architecture data cannot be read: {error}") from error


def elevations(ctx: FeatureContext) -> dict[str, float]:
    raw = ctx.raw("floorPlan")
    if isinstance(raw, dict) and isinstance(raw.get("stories"), list):
        return {
            str(story["id"]): float(story["elevation"])
            for story in raw["stories"]
            if isinstance(story, dict) and "id" in story and "elevation" in story
        }
    bim = ctx.raw("bim")
    if isinstance(bim, dict) and isinstance(bim.get("stories"), list):
        return {
            str(story["id"]): float(story["elevation"])
            for story in bim["stories"]
            if isinstance(story, dict) and "id" in story and "elevation" in story
        }
    return {}


def room_metrics(ctx: FeatureContext, arch: Any) -> list[dict[str, Any]]:
    from saengine.library.architecture import room_boundary

    levels = elevations(ctx)
    rows: list[dict[str, Any]] = []
    for room in arch.rooms:
        found = room_boundary(arch, room, levels)
        if found is None:
            rows.append(
                {
                    "room": room.id,
                    "name": room.name,
                    "number": room.number,
                    "story": room.story,
                    "bounded": False,
                    "grossAreaM2": 0.0,
                    "netAreaM2": 0.0,
                }
            )
        else:
            gross, net = found
            rows.append(
                {
                    "room": room.id,
                    "name": room.name,
                    "number": room.number,
                    "story": room.story,
                    "bounded": True,
                    "grossAreaM2": gross.area * 1e-6,
                    "netAreaM2": net.area * 1e-6,
                }
            )
    return rows


def write_arch_export(
    ctx: FeatureContext, filename: str, content: str, folder: str = "11 Exports/Architecture"
) -> str:
    if ctx.root is None:
        raise FeatureInputError("Open a project before writing an architecture export.")
    target = ctx.root / folder
    target.mkdir(parents=True, exist_ok=True)
    path = target / filename
    path.write_text(content, encoding="utf-8")
    return path.relative_to(ctx.root).as_posix()


def write_json(ctx: FeatureContext, filename: str, payload: Any) -> str:
    return write_arch_export(
        ctx, filename, json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    )


def csv_text(columns: list[str], rows: list[dict[str, Any]]) -> str:
    stream = StringIO()
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()

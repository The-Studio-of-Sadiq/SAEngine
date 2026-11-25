"""Shared BIM feature data and export helpers."""

from __future__ import annotations

import csv
import json
from io import StringIO
from typing import Any

from saengine.features import FeatureContext, FeatureInputError


def require_bim(ctx: FeatureContext) -> dict[str, Any]:
    if ctx.root is None:
        raise FeatureInputError("Open a project before running this BIM feature.")
    data = ctx.raw("bim")
    if not isinstance(data, dict):
        raise FeatureInputError("Generate 06 BIM/bim.json from the floor plan first.")
    if not isinstance(data.get("elements"), list):
        raise FeatureInputError("The building model has no element list.")
    return data


def element_story(data: dict[str, Any], element: dict[str, Any]) -> str:
    if element.get("story"):
        return str(element["story"])
    stories = [s for s in (data.get("stories") or []) if isinstance(s, dict)]
    elev = element.get("elevation", element.get("top", element.get("bottom")))
    if isinstance(elev, (int, float)):
        for story in stories:
            s_elev = story.get("elevation")
            if isinstance(s_elev, (int, float)) and abs(float(s_elev) - float(elev)) < 1.0:
                return str(story.get("id") or story.get("name") or "Unassigned")
    return "Unassigned"


def element_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for element in data["elements"]:
        if not isinstance(element, dict):
            continue
        rows.append(
            {
                "id": str(element.get("id", "")),
                "kind": str(element.get("kind", "")),
                "type": str(element.get("type", "")),
                "source": str(element.get("source", "")),
                "story": element_story(data, element),
            }
        )
    return rows


def slab_area_m2(data: dict[str, Any]) -> float:
    total = 0.0
    for element in data.get("elements") or []:
        if not isinstance(element, dict) or element.get("kind") != "slab":
            continue
        pts = element.get("boundary") or element.get("polygon")
        if isinstance(pts, list):
            total += polygon_area(pts) / 1e6
    return round(total, 2)


def kind_counts(data: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for element in data["elements"]:
        if isinstance(element, dict):
            kind = str(element.get("kind", "unknown"))
            counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))


def material_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for element in data["elements"]:
        if isinstance(element, dict):
            type_id = str(element.get("type", "unclassified"))
            counts[type_id] = counts.get(type_id, 0) + 1
    return [{"type": type_id, "elementCount": count} for type_id, count in sorted(counts.items())]


def write_bim_export(
    ctx: FeatureContext,
    filename: str,
    content: str,
    folder: str = "11 Exports/BIM",
) -> str:
    if ctx.root is None:
        raise FeatureInputError("Open a project before writing a BIM export.")
    target = ctx.root / folder
    target.mkdir(parents=True, exist_ok=True)
    path = target / filename
    path.write_text(content, encoding="utf-8")
    return path.relative_to(ctx.root).as_posix()


def write_bim_json(ctx: FeatureContext, filename: str, payload: Any) -> str:
    return write_bim_export(ctx, filename, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def write_bim_csv(
    ctx: FeatureContext, filename: str, columns: list[str], rows: list[dict[str, Any]]
) -> str:
    stream = StringIO()
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return write_bim_export(ctx, filename, stream.getvalue())


def polygon_area(points: list[list[float]]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    for index, point in enumerate(points):
        following = points[(index + 1) % len(points)]
        area += point[0] * following[1] - following[0] * point[1]
    return abs(area) * 0.5


def element_extent(data: dict[str, Any]) -> dict[str, float]:
    coordinates: list[list[float]] = []
    elevations: list[float] = []
    for element in data["elements"]:
        if not isinstance(element, dict):
            continue
        for key in ("position", "start", "end"):
            point = element.get(key)
            if isinstance(point, list) and len(point) >= 2:
                coordinates.append([float(point[0]), float(point[1])])
        for key in ("bottom", "elevation", "top"):
            value = element.get(key)
            if isinstance(value, (int, float)):
                elevations.append(float(value))
        boundary = element.get("boundary")
        if isinstance(boundary, list):
            coordinates.extend(
                [float(point[0]), float(point[1])]
                for point in boundary
                if isinstance(point, list) and len(point) >= 2
            )
    if not coordinates:
        return {"minXMm": 0.0, "minYMm": 0.0, "maxXMm": 0.0, "maxYMm": 0.0}
    xs = [point[0] for point in coordinates]
    ys = [point[1] for point in coordinates]
    return {
        "minXMm": min(xs),
        "minYMm": min(ys),
        "maxXMm": max(xs),
        "maxYMm": max(ys),
        "minElevMm": min(elevations) if elevations else 0.0,
        "maxElevMm": max(elevations) if elevations else 0.0,
    }

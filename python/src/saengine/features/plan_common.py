"""Shared readers and geometry helpers for Floor Plan ribbon features.

The floor plan stores grid coordinates and member locations in millimetres. These helpers only
parse that common representation; each ribbon feature keeps its own inputs and engineering
operation in its tab module.
"""

from __future__ import annotations

import json
import math
from typing import Any

from saengine.features import FeatureContext, FeatureInputError


def plan_data(ctx: FeatureContext) -> dict[str, Any]:
    """Read and validate the project's floor plan, with a useful feature-panel error."""
    raw = ctx.raw("floorPlan")
    if raw is None:
        raise FeatureInputError("Open a project with a valid 05 Floor Plan/floor-plan.json first.")
    from saengine.library.floorplan import FloorPlan

    try:
        return FloorPlan.model_validate(raw).model_dump(mode="json", by_alias=True)
    except ValueError as exc:
        raise FeatureInputError(f"The floor plan is invalid: {exc}") from exc


def point_xy(plan: dict[str, Any], point: dict[str, Any]) -> tuple[float, float]:
    """Resolve a grid point, including its millimetre offsets, to plan coordinates (on any grid
    system: see :mod:`saengine.library.grid_geometry`)."""
    from saengine.library.grid_geometry import GridError, GridGeometry

    try:
        return GridGeometry(plan.get("grids")).point(point)
    except GridError as exc:
        raise FeatureInputError(
            f"Grid point {point.get('x')}-{point.get('y')} is not defined ({exc})."
        ) from exc


def parse_point(value: str) -> dict[str, Any]:
    """Parse a grid reference such as ``A-1`` or ``A-1+100,-50``."""
    ref = value.strip().replace(" ", "")
    if not ref:
        raise FeatureInputError("Enter a grid reference such as A-1.")
    try:
        grid, *offsets = ref.split("+")
        x_label, y_label = grid.split("-", 1)
        point: dict[str, Any] = {"x": x_label, "y": y_label, "dx": 0.0, "dy": 0.0}
        if offsets:
            dx, dy = offsets[0].split(",", 1)
            point["dx"], point["dy"] = float(dx), float(dy)
        return point
    except (ValueError, TypeError) as exc:
        raise FeatureInputError(
            "Use a grid reference like A-1 or A-1+100,-50 (offsets in mm)."
        ) from exc


def point_text(point: dict[str, Any]) -> str:
    """Format a resolved point as a readable grid coordinate."""
    dx, dy = float(point.get("dx", 0)), float(point.get("dy", 0))
    suffix = f" + ({dx:.0f}, {dy:.0f}) mm" if dx or dy else ""
    return f"{point['x']}-{point['y']}{suffix}"


def story_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {story["id"]: story for story in plan["stories"]}


def ordered_stories(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(plan["stories"], key=lambda story: float(story["elevation"]))


def member_groups(plan: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    """The member collections in their schema order."""
    return [(key, plan.get(key, [])) for key in ("columns", "beams", "walls", "slabs", "footings")]


def member_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """A normalized member schedule with resolved lengths and plan coordinates."""
    stories = story_map(plan)
    rows: list[dict[str, Any]] = []
    for group, members in member_groups(plan):
        for member in members:
            row: dict[str, Any] = {
                "id": member["id"],
                "category": group[:-1],
                "type": member["type"],
                "story": member.get("story", member.get("base", "")),
                "mark": member.get("mark", member["id"]),
            }
            if group == "beams":
                x1, y1 = point_xy(plan, member["start"])
                x2, y2 = point_xy(plan, member["end"])
                row.update(
                    x1Mm=x1,
                    y1Mm=y1,
                    x2Mm=x2,
                    y2Mm=y2,
                    lengthM=math.hypot(x2 - x1, y2 - y1) / 1000,
                    angleDeg=math.degrees(math.atan2(y2 - y1, x2 - x1)),
                    start=point_text(member["start"]),
                    end=point_text(member["end"]),
                )
            elif group in ("columns", "walls"):
                p1 = member.get("at", member.get("start"))
                x1, y1 = point_xy(plan, p1)
                if "end" in member:
                    x2, y2 = point_xy(plan, member["end"])
                    horizontal = math.hypot(x2 - x1, y2 - y1)
                else:
                    x2, y2, horizontal = x1, y1, 0.0
                z1 = float(stories.get(member.get("base", ""), {}).get("elevation", 0))
                z2 = float(stories.get(member.get("top", ""), {}).get("elevation", z1))
                row.update(
                    x1Mm=x1,
                    y1Mm=y1,
                    x2Mm=x2,
                    y2Mm=y2,
                    heightM=(z2 - z1) / 1000,
                    lengthM=math.hypot(horizontal, z2 - z1) / 1000,
                    angleDeg=math.degrees(math.atan2(y2 - y1, x2 - x1)) if horizontal else 0.0,
                    start=point_text(p1),
                    end=point_text(member["end"]) if "end" in member else point_text(p1),
                )
            elif group == "slabs":
                corners = [point_xy(plan, p) for p in member["boundary"]]
                area = (
                    abs(
                        sum(
                            corners[i][0] * corners[(i + 1) % len(corners)][1]
                            - corners[(i + 1) % len(corners)][0] * corners[i][1]
                            for i in range(len(corners))
                        )
                    )
                    / 2_000_000
                )
                perimeter = (
                    sum(
                        math.hypot(
                            corners[(i + 1) % len(corners)][0] - corners[i][0],
                            corners[(i + 1) % len(corners)][1] - corners[i][1],
                        )
                        for i in range(len(corners))
                    )
                    / 1000
                )
                row.update(areaM2=area, perimeterM=perimeter, cornerCount=len(corners))
            else:
                x, y = point_xy(plan, member["at"])
                row.update(x1Mm=x, y1Mm=y, x2Mm=x, y2Mm=y, lengthM=0.0, angleDeg=0.0)
            rows.append(row)
    return rows


def grid_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for axis in ("x", "y"):
        lines = sorted(plan["grids"].get(axis, []), key=lambda line: float(line["position"]))
        for index, line in enumerate(lines):
            previous = float(lines[index - 1]["position"]) if index else None
            position = float(line["position"])
            rows.append(
                {
                    "axis": axis.upper(),
                    "label": line["label"],
                    "positionMm": position,
                    "spacingMm": position - previous if previous is not None else None,
                }
            )
    return rows


def loads_data(ctx: FeatureContext) -> dict[str, Any]:
    """Read the optional member-load file without making older floor plans invalid."""
    path = ctx.path("05 Floor Plan/loads.json")
    if path is None or not path.is_file():
        return {"wallTypes": [], "loads": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FeatureInputError("The member-load file is unreadable JSON.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("loads", []), list):
        raise FeatureInputError("The member-load file must contain a loads list.")
    return data


def selected_members(rows: list[dict[str, Any]], ids: str) -> list[dict[str, Any]]:
    """Select explicit comma-separated member ids; blank means all members."""
    wanted = {part.strip() for part in ids.split(",") if part.strip()}
    if not wanted:
        return rows
    selected = [row for row in rows if row["id"] in wanted]
    missing = sorted(wanted - {row["id"] for row in selected})
    if missing:
        raise FeatureInputError(f"Unknown member id(s): {', '.join(missing)}.")
    return selected


def profile(ctx: FeatureContext) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    plan = plan_data(ctx)
    return plan, member_rows(plan)


def export_csv(
    ctx: FeatureContext, name: str, headers: list[str], rows: list[dict[str, Any]]
) -> str:
    """Write a deterministic CSV beneath the Floor Plan exports folder."""
    if ctx.root is None:
        raise FeatureInputError("Open a project folder to write the export.")
    import csv

    path = ctx.root / "05 Floor Plan" / "exports" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path.relative_to(ctx.root).as_posix()


def intersection(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
    tolerance: float = 1e-6,
) -> bool:
    """Return whether two non-collinear plan segments cross in their interiors."""

    def orient(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return o1 * o2 < -tolerance and o3 * o4 < -tolerance


def segment_distance(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    """Shortest point-to-segment distance in millimetres."""
    vx, vy = end[0] - start[0], end[1] - start[1]
    denominator = vx * vx + vy * vy
    if denominator <= 1e-12:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    t = max(0.0, min(1.0, ((point[0] - start[0]) * vx + (point[1] - start[1]) * vy) / denominator))
    return math.hypot(point[0] - (start[0] + t * vx), point[1] - (start[1] + t * vy))

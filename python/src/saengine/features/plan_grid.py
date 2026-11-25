"""Grids ribbon: build, dimension, transform and review structural setting-out grids."""

from __future__ import annotations

import itertools
import math

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.plan_common import plan_data, profile


def _spacings(raw: str) -> list[float]:
    try:
        values = [float(part.strip()) for part in raw.split(",") if part.strip()]
    except ValueError as exc:
        raise FeatureInputError("Enter comma-separated positive spacings in millimetres.") from exc
    if not values or any(value <= 0 for value in values):
        raise FeatureInputError("Enter at least one positive spacing in millimetres.")
    return values


@feature(
    "grid.drawGridLine",
    "Draw Grid Line",
    part="floorPlan",
    fields=[
        select("axis", "Grid axis", [("x", "X"), ("y", "Y")]),
        text("label", "Grid label", "D"),
        number("positionMm", "Position", 6000, unit="mm"),
        number("extentMm", "Visible extent", 20000, unit="mm", min=1),
    ],
)
def draw_grid_line(ctx: FeatureContext, values: dict) -> dict:
    """Define one grid axis and report the line endpoints implied by its extent."""
    plan = plan_data(ctx)
    existing = plan["grids"][values["axis"]]
    if any(g["label"] == values["label"] for g in plan["grids"]["x"] + plan["grids"]["y"]):
        raise FeatureInputError("Grid labels must be unique across both axes.")
    return result(
        summary={
            "axis": values["axis"].upper(),
            "label": values["label"],
            "positionMm": values["positionMm"],
            "startMm": -values["extentMm"] / 2,
            "endMm": values["extentMm"] / 2,
            "existingLineCount": len(existing),
        }
    )


@feature(
    "grid.orthogonalGrid",
    "Orthogonal Grid",
    part="floorPlan",
    fields=[
        text("xSpacingsMm", "X bay spacings", "6000,6000,6000"),
        text("ySpacingsMm", "Y bay spacings", "5000,5000"),
        text("xStartLabel", "First X label", "A"),
        number("yStartNumber", "First Y number", 1, min=0),
    ],
)
def orthogonal_grid(ctx: FeatureContext, values: dict) -> dict:
    """Expand bay spacings into cumulative orthogonal grid coordinates."""
    xs, ys = _spacings(values["xSpacingsMm"]), _spacings(values["ySpacingsMm"])
    start = values["xStartLabel"].strip()
    if len(start) != 1 or not start.isalpha():
        raise FeatureInputError("First X label must be one letter.")
    xlines = [
        {"label": chr(ord(start.upper()) + i), "positionMm": sum(xs[:i])}
        for i in range(len(xs) + 1)
    ]
    ylines = [
        {"label": str(int(values["yStartNumber"]) + i), "positionMm": sum(ys[:i])}
        for i in range(len(ys) + 1)
    ]
    rows = [{"axis": "X", **line} for line in xlines] + [{"axis": "Y", **line} for line in ylines]
    return result(
        summary={
            "xLineCount": len(xlines),
            "yLineCount": len(ylines),
            "bayCount": len(xs) * len(ys),
            "widthMm": sum(xs),
            "depthMm": sum(ys),
        },
        tables=[
            table(
                "Orthogonal grid coordinates",
                [("axis", "Axis"), ("label", "Label"), ("positionMm", "Position", "mm")],
                rows,
            )
        ],
        notes=[
            "Positions are cumulative sums from the local origin at the first grid line on each axis."
        ],
    )


@feature(
    "grid.radialGrid",
    "Radial Grid",
    part="floorPlan",
    fields=[
        number("centerXmm", "Centre X", 0, unit="mm"),
        number("centerYmm", "Centre Y", 0, unit="mm"),
        number("radiusMm", "Outer radius", 15000, unit="mm", min=1),
        number("radialCount", "Radial divisions", 8, min=3, max=360),
        number("ringSpacingMm", "Ring spacing", 3000, unit="mm", min=1),
    ],
)
def radial_grid(ctx: FeatureContext, values: dict) -> dict:
    """Generate radial ray directions and concentric ring radii for a circular layout."""
    count = int(values["radialCount"])
    interval = 360 / count
    rays = [
        {
            "ray": i + 1,
            "angleDeg": i * interval,
            "endXmm": values["centerXmm"]
            + values["radiusMm"] * math.cos(math.radians(i * interval)),
            "endYmm": values["centerYmm"]
            + values["radiusMm"] * math.sin(math.radians(i * interval)),
        }
        for i in range(count)
    ]
    rings = [
        {"ring": i, "radiusMm": min(i * values["ringSpacingMm"], values["radiusMm"])}
        for i in range(1, math.ceil(values["radiusMm"] / values["ringSpacingMm"]) + 1)
    ]
    return result(
        summary={
            "radialCount": count,
            "ringCount": len(rings),
            "outerRadiusMm": values["radiusMm"],
        },
        tables=[
            table(
                "Radial axes",
                [
                    ("ray", "Ray"),
                    ("angleDeg", "Angle", "°"),
                    ("endXmm", "End X", "mm"),
                    ("endYmm", "End Y", "mm"),
                ],
                rays,
            ),
            table("Concentric rings", [("ring", "Ring"), ("radiusMm", "Radius", "mm")], rings),
        ],
    )


@feature(
    "grid.editGrid",
    "Edit Grid",
    part="floorPlan",
    fields=[
        select("axis", "Grid axis", [("x", "X"), ("y", "Y")]),
        text("label", "Grid label", "B"),
        select("operation", "Edit", [("move", "Move"), ("add", "Add"), ("remove", "Remove")]),
        number("positionMm", "New position", 6000, unit="mm"),
    ],
)
def edit_grid(ctx: FeatureContext, values: dict) -> dict:
    """Preview one explicit grid-line add, move or removal and enforce unique coordinates."""
    plan = plan_data(ctx)
    lines = plan["grids"][values["axis"]]
    target = next((g for g in lines if g["label"] == values["label"]), None)
    if values["operation"] == "move" and target is None:
        raise FeatureInputError("The grid label to move was not found.")
    if values["operation"] == "remove" and target is None:
        raise FeatureInputError("The grid label to remove was not found.")
    if values["operation"] == "add" and any(
        g["label"] == values["label"] for g in plan["grids"]["x"] + plan["grids"]["y"]
    ):
        raise FeatureInputError("The new grid label already exists.")
    proposed = [dict(g) for g in lines]
    if values["operation"] == "remove":
        proposed = [g for g in proposed if g["label"] != values["label"]]
    elif values["operation"] == "move":
        next(g for g in proposed if g["label"] == values["label"])["position"] = values[
            "positionMm"
        ]
    else:
        proposed.append({"label": values["label"], "position": values["positionMm"]})
    positions = [float(g["position"]) for g in proposed]
    if len(positions) != len(set(positions)):
        raise FeatureInputError("Two grid lines would occupy the same position.")
    return result(
        summary={
            "operation": values["operation"],
            "axis": values["axis"].upper(),
            "lineCountAfter": len(proposed),
        },
        tables=[
            table(
                "Proposed grid coordinates",
                [("label", "Label"), ("positionMm", "Position", "mm")],
                [
                    {"label": g["label"], "positionMm": g["position"]}
                    for g in sorted(proposed, key=lambda g: g["position"])
                ],
            )
        ],
    )


@feature(
    "grid.gridSpacing",
    "Grid Spacing",
    part="floorPlan",
    fields=[
        select("axis", "Grid axis", [("x", "X"), ("y", "Y")]),
        text("labels", "Grid labels in order (blank for all)", ""),
    ],
)
def grid_spacing(ctx: FeatureContext, values: dict) -> dict:
    """Report consecutive bay spacings and the total dimension of one grid axis."""
    plan = plan_data(ctx)
    lines = sorted(plan["grids"][values["axis"]], key=lambda g: float(g["position"]))
    requested = {x.strip() for x in values["labels"].split(",") if x.strip()}
    if requested:
        lines = [g for g in lines if g["label"] in requested]
        if len(lines) != len(requested):
            raise FeatureInputError("One or more requested grid labels were not found.")
    rows = [
        {
            "from": lines[i - 1]["label"],
            "to": lines[i]["label"],
            "spacingMm": float(lines[i]["position"]) - float(lines[i - 1]["position"]),
        }
        for i in range(1, len(lines))
    ]
    return result(
        summary={
            "axis": values["axis"].upper(),
            "bayCount": len(rows),
            "totalSpanMm": sum(r["spacingMm"] for r in rows),
        },
        tables=[
            table(
                "Grid bay dimensions",
                [("from", "From"), ("to", "To"), ("spacingMm", "Spacing", "mm")],
                rows,
            )
        ],
    )


@feature(
    "grid.dimensionLine",
    "Dimension Line",
    part="floorPlan",
    fields=[
        select("axis", "Grid axis", [("x", "X"), ("y", "Y")]),
        text("labels", "Grid labels to dimension", "A,B,C"),
    ],
)
def dimension_line(ctx: FeatureContext, values: dict) -> dict:
    """Build dimension segments between the entered adjacent grid labels."""
    plan = plan_data(ctx)
    lines = {g["label"]: float(g["position"]) for g in plan["grids"][values["axis"]]}
    labels = [x.strip() for x in values["labels"].split(",") if x.strip()]
    if len(labels) < 2 or any(label not in lines for label in labels):
        raise FeatureInputError("Enter at least two existing labels on the selected axis.")
    rows = [
        {
            "from": a,
            "to": b,
            "distanceMm": abs(lines[b] - lines[a]),
            "direction": "increasing" if lines[b] >= lines[a] else "decreasing",
        }
        for a, b in itertools.pairwise(labels)
    ]
    return result(
        summary={
            "dimensionCount": len(rows),
            "overallDistanceMm": abs(lines[labels[-1]] - lines[labels[0]]),
        },
        tables=[
            table(
                "Grid dimensions",
                [
                    ("from", "From"),
                    ("to", "To"),
                    ("distanceMm", "Distance", "mm"),
                    ("direction", "Direction"),
                ],
                rows,
            )
        ],
    )


@feature(
    "grid.bubbleSize",
    "Bubble Size",
    part="floorPlan",
    fields=[
        number("bubbleDiameterMm", "Bubble diameter", 300, unit="mm", min=1),
        number("textHeightMm", "Label text height", 150, unit="mm", min=1),
        number("lineGapMm", "Line-to-bubble gap", 100, unit="mm", min=0),
    ],
)
def bubble_size(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the grid label bubble envelope and its drawing clearance."""
    return result(
        summary={
            "bubbleDiameterMm": values["bubbleDiameterMm"],
            "textToBubbleRatio": values["textHeightMm"] / values["bubbleDiameterMm"],
            "overallCalloutMm": values["bubbleDiameterMm"] + values["lineGapMm"],
            "textFitsBubble": values["textHeightMm"] <= values["bubbleDiameterMm"] * 0.8,
        },
        notes=[
            "The text fit ratio is a graphic legibility check; it does not change structural grid geometry."
        ],
    )


@feature(
    "grid.gridLabels",
    "Grid Labels",
    part="floorPlan",
    fields=[
        select("axis", "Grid axis", [("x", "X"), ("y", "Y")]),
        text("labels", "Comma-separated labels", "A,B,C"),
    ],
)
def grid_labels(ctx: FeatureContext, values: dict) -> dict:
    """Check a proposed axis label sequence for blank or repeated labels."""
    labels = [x.strip() for x in values["labels"].split(",") if x.strip()]
    repeated = sorted({x for x in labels if labels.count(x) > 1})
    plan = plan_data(ctx)
    used = {g["label"] for g in plan["grids"]["x"] + plan["grids"]["y"]}
    clashes = [x for x in labels if x in used]
    return result(
        summary={
            "labelCount": len(labels),
            "unique": len(repeated) == 0,
            "conflictsWithCurrentGrid": len(clashes),
        },
        tables=[
            table(
                "Proposed grid labels",
                [("sequence", "Sequence"), ("label", "Label"), ("alreadyUsed", "Already used")],
                [
                    {"sequence": i + 1, "label": label, "alreadyUsed": label in used}
                    for i, label in enumerate(labels)
                ],
            )
        ],
        notes=[
            f"Repeated labels: {', '.join(repeated) if repeated else 'none'}; current grid conflicts: {', '.join(clashes) if clashes else 'none'}."
        ],
    )


@feature(
    "grid.renumberGrid",
    "Renumber Grid",
    part="floorPlan",
    fields=[
        select("axis", "Grid axis", [("x", "X"), ("y", "Y")]),
        text("startLabel", "First label", "A"),
        checkbox("skipI", "Skip letter I", True),
    ],
)
def renumber_grid(ctx: FeatureContext, values: dict) -> dict:
    """Create a sorted replacement label sequence while preserving line positions."""
    plan = plan_data(ctx)
    lines = sorted(plan["grids"][values["axis"]], key=lambda g: float(g["position"]))
    start = values["startLabel"].strip()
    if values["axis"] == "y":
        try:
            labels = [str(int(start) + i) for i in range(len(lines))]
        except ValueError as exc:
            raise FeatureInputError("Y grid numbering must start with an integer.") from exc
    else:
        if len(start) != 1 or not start.isalpha():
            raise FeatureInputError("X grid renumbering must start with one letter.")
        code = ord(start.upper())
        labels = []
        while len(labels) < len(lines):
            letter = chr(code)
            code += 1
            if values["skipI"] and letter == "I":
                continue
            labels.append(letter)
    return result(
        summary={"renumberedLines": len(lines), "axis": values["axis"].upper()},
        tables=[
            table(
                "Grid renumbering",
                [
                    ("oldLabel", "Current label"),
                    ("newLabel", "New label"),
                    ("positionMm", "Position", "mm"),
                ],
                [
                    {"oldLabel": line["label"], "newLabel": label, "positionMm": line["position"]}
                    for line, label in zip(lines, labels)
                ],
            )
        ],
    )


@feature(
    "grid.gridExtents",
    "Grid Extents",
    part="floorPlan",
    fields=[number("marginMm", "Extension beyond building", 3000, unit="mm", min=0)],
)
def grid_extents(ctx: FeatureContext, values: dict) -> dict:
    """Find member plan bounds and calculate grid display endpoints with a margin."""
    _plan, rows = profile(ctx)
    xs = [r[k] for r in rows for k in ("x1Mm", "x2Mm") if k in r]
    ys = [r[k] for r in rows for k in ("y1Mm", "y2Mm") if k in r]
    if not xs or not ys:
        raise FeatureInputError("Add plan members before deriving grid extents.")
    return result(
        summary={
            "minXmm": min(xs) - values["marginMm"],
            "maxXmm": max(xs) + values["marginMm"],
            "minYmm": min(ys) - values["marginMm"],
            "maxYmm": max(ys) + values["marginMm"],
            "marginMm": values["marginMm"],
        }
    )


@feature(
    "grid.trimGrid",
    "Trim Grid",
    part="floorPlan",
    fields=[number("marginMm", "Grid margin beyond member extents", 500, unit="mm", min=0)],
)
def trim_grid(ctx: FeatureContext, values: dict) -> dict:
    """Compute trimmed display extents for every grid line from the member bounding box."""
    plan, rows = profile(ctx)
    xs = [r[k] for r in rows for k in ("x1Mm", "x2Mm") if k in r]
    ys = [r[k] for r in rows for k in ("y1Mm", "y2Mm") if k in r]
    if not xs or not ys:
        raise FeatureInputError("Member geometry is needed to trim grid lines.")
    xmin, xmax, ymin, ymax = (
        min(xs) - values["marginMm"],
        max(xs) + values["marginMm"],
        min(ys) - values["marginMm"],
        max(ys) + values["marginMm"],
    )
    out = [
        {"axis": "X", "label": g["label"], "startMm": ymin, "endMm": ymax}
        for g in plan["grids"]["x"]
    ] + [
        {"axis": "Y", "label": g["label"], "startMm": xmin, "endMm": xmax}
        for g in plan["grids"]["y"]
    ]
    return result(
        summary={"trimmedLineCount": len(out), "marginMm": values["marginMm"]},
        tables=[
            table(
                "Trimmed grid extents",
                [
                    ("axis", "Axis"),
                    ("label", "Grid"),
                    ("startMm", "Start", "mm"),
                    ("endMm", "End", "mm"),
                ],
                out,
            )
        ],
    )


@feature(
    "grid.offsetGrid",
    "Offset Grid",
    part="floorPlan",
    fields=[
        number("offsetXmm", "X offset", 0, unit="mm"),
        number("offsetYmm", "Y offset", 0, unit="mm"),
    ],
)
def offset_grid(ctx: FeatureContext, values: dict) -> dict:
    """Translate every grid-line coordinate and report its shifted global position."""
    plan = plan_data(ctx)
    rows = [
        {"axis": "X", "label": g["label"], "positionMm": float(g["position"]) + values["offsetXmm"]}
        for g in plan["grids"]["x"]
    ] + [
        {"axis": "Y", "label": g["label"], "positionMm": float(g["position"]) + values["offsetYmm"]}
        for g in plan["grids"]["y"]
    ]
    return result(
        summary={
            "gridLineCount": len(rows),
            "offsetXmm": values["offsetXmm"],
            "offsetYmm": values["offsetYmm"],
        },
        tables=[
            table(
                "Offset grid coordinates",
                [("axis", "Axis"), ("label", "Grid"), ("positionMm", "New position", "mm")],
                rows,
            )
        ],
    )


@feature(
    "grid.rotateGrid",
    "Rotate Grid",
    part="floorPlan",
    fields=[
        number("angleDeg", "Rotation", 15, unit="°"),
        number("originXmm", "Origin X", 0, unit="mm"),
        number("originYmm", "Origin Y", 0, unit="mm"),
    ],
)
def rotate_grid(ctx: FeatureContext, values: dict) -> dict:
    """Transform axis grid points through a planar rotation about the selected origin."""
    plan = plan_data(ctx)
    theta = math.radians(values["angleDeg"])
    c, s = math.cos(theta), math.sin(theta)
    points = []
    for axis in ("x", "y"):
        for line in plan["grids"][axis]:
            x, y = (float(line["position"]), 0) if axis == "x" else (0, float(line["position"]))
            dx, dy = x - values["originXmm"], y - values["originYmm"]
            points.append(
                {
                    "axis": axis.upper(),
                    "label": line["label"],
                    "xMm": values["originXmm"] + c * dx - s * dy,
                    "yMm": values["originYmm"] + s * dx + c * dy,
                }
            )
    return result(
        summary={"rotatedGridLines": len(points), "angleDeg": values["angleDeg"]},
        tables=[
            table(
                "Rotated grid reference points",
                [("axis", "Axis"), ("label", "Grid"), ("xMm", "X", "mm"), ("yMm", "Y", "mm")],
                points,
            )
        ],
        notes=[
            "Each grid line is represented by its point on the corresponding local axis; the orientation is the rotation angle."
        ],
    )


@feature(
    "grid.mirrorGrid",
    "Mirror Grid",
    part="floorPlan",
    fields=[
        select("axis", "Mirror axis", [("x", "X axis"), ("y", "Y axis")]),
        number("coordinateMm", "Axis coordinate", 0, unit="mm"),
    ],
)
def mirror_grid(ctx: FeatureContext, values: dict) -> dict:
    """Reflect grid reference coordinates through a selected global axis."""
    plan = plan_data(ctx)
    axis = values["axis"]
    rows = []
    for line in plan["grids"]["x"]:
        rows.append(
            {
                "gridAxis": "X",
                "label": line["label"],
                "xMm": 2 * values["coordinateMm"] - line["position"]
                if axis == "y"
                else line["position"],
                "yMm": 0 if axis == "y" else 2 * values["coordinateMm"],
            }
        )
    for line in plan["grids"]["y"]:
        rows.append(
            {
                "gridAxis": "Y",
                "label": line["label"],
                "xMm": 0 if axis == "y" else 2 * values["coordinateMm"],
                "yMm": line["position"]
                if axis == "y"
                else 2 * values["coordinateMm"] - line["position"],
            }
        )
    return result(
        summary={"reflectedGridLines": len(rows), "mirrorAxis": axis},
        tables=[
            table(
                "Reflected grid coordinates",
                [
                    ("gridAxis", "Grid axis"),
                    ("label", "Label"),
                    ("xMm", "X", "mm"),
                    ("yMm", "Y", "mm"),
                ],
                rows,
            )
        ],
    )


@feature(
    "grid.gridSnapping",
    "Grid Snapping",
    part="floorPlan",
    fields=[
        number("xMm", "Pick X", 5800, unit="mm"),
        number("yMm", "Pick Y", 2400, unit="mm"),
        number("maximumDistanceMm", "Maximum snap distance", 500, unit="mm", min=0),
    ],
)
def grid_snapping(ctx: FeatureContext, values: dict) -> dict:
    """Snap an entered plan point to the nearest X/Y grid intersection within tolerance."""
    plan = plan_data(ctx)
    pairs = [(x, y) for x in plan["grids"]["x"] for y in plan["grids"]["y"]]
    if not pairs:
        raise FeatureInputError("The floor plan has no grid intersections to snap to.")
    nearest = min(
        pairs,
        key=lambda p: math.hypot(
            float(p[0]["position"]) - values["xMm"], float(p[1]["position"]) - values["yMm"]
        ),
    )
    distance = math.hypot(
        float(nearest[0]["position"]) - values["xMm"], float(nearest[1]["position"]) - values["yMm"]
    )
    if distance > values["maximumDistanceMm"]:
        raise FeatureInputError(
            f"Nearest grid intersection is {distance:.1f} mm away, beyond the snap tolerance."
        )
    return result(
        summary={
            "gridPoint": f"{nearest[0]['label']}-{nearest[1]['label']}",
            "snappedXmm": nearest[0]["position"],
            "snappedYmm": nearest[1]["position"],
            "snapDistanceMm": distance,
        }
    )


@feature(
    "grid.gridSectionView",
    "Grid Section View",
    part="floorPlan",
    fields=[
        select("axis", "Section axis", [("x", "X grid lines"), ("y", "Y grid lines")]),
        text("label", "Section grid label", "A"),
    ],
)
def grid_section_view(ctx: FeatureContext, values: dict) -> dict:
    """Return an elevation-section coordinate table for one selected grid line."""
    plan = plan_data(ctx)
    line = next((g for g in plan["grids"][values["axis"]] if g["label"] == values["label"]), None)
    if line is None:
        raise FeatureInputError("The selected section grid line was not found.")
    stories = sorted(plan["stories"], key=lambda s: float(s["elevation"]))
    return result(
        summary={
            "axis": values["axis"].upper(),
            "gridLabel": values["label"],
            "gridPositionMm": line["position"],
        },
        tables=[
            table(
                "Section levels",
                [
                    ("story", "Storey"),
                    ("elevationMm", "Elevation", "mm"),
                    ("heightToNextMm", "Height to next", "mm"),
                ],
                [
                    {
                        "story": s["id"],
                        "elevationMm": s["elevation"],
                        "heightToNextMm": float(stories[i + 1]["elevation"]) - float(s["elevation"])
                        if i + 1 < len(stories)
                        else None,
                    }
                    for i, s in enumerate(stories)
                ],
            )
        ],
    )


@feature(
    "grid.grid3dView",
    "Grid 3D View",
    part="floorPlan",
    fields=[
        number("bottomElevationMm", "Bottom elevation", 0, unit="mm"),
        number("topElevationMm", "Top elevation", 10000, unit="mm"),
    ],
)
def grid_3d_view(ctx: FeatureContext, values: dict) -> dict:
    """Produce end coordinates for every vertical grid axis through the requested elevation range."""
    plan = plan_data(ctx)
    if values["topElevationMm"] <= values["bottomElevationMm"]:
        raise FeatureInputError("Top elevation must be above bottom elevation.")
    rows = [
        {
            "axis": "X",
            "label": g["label"],
            "xMm": g["position"],
            "yMm": 0,
            "z0Mm": values["bottomElevationMm"],
            "z1Mm": values["topElevationMm"],
        }
        for g in plan["grids"]["x"]
    ] + [
        {
            "axis": "Y",
            "label": g["label"],
            "xMm": 0,
            "yMm": g["position"],
            "z0Mm": values["bottomElevationMm"],
            "z1Mm": values["topElevationMm"],
        }
        for g in plan["grids"]["y"]
    ]
    return result(
        summary={
            "verticalGridLines": len(rows),
            "heightM": (values["topElevationMm"] - values["bottomElevationMm"]) / 1000,
        },
        tables=[
            table(
                "3D grid line coordinates",
                [
                    ("axis", "Axis"),
                    ("label", "Grid"),
                    ("xMm", "X", "mm"),
                    ("yMm", "Y", "mm"),
                    ("z0Mm", "Bottom", "mm"),
                    ("z1Mm", "Top", "mm"),
                ],
                rows,
            )
        ],
    )


@feature(
    "grid.gridTemplate",
    "Grid Template",
    part="floorPlan",
    fields=[
        text("xSpacingsMm", "Template X spacings", "6000,6000"),
        text("ySpacingsMm", "Template Y spacings", "5000,5000"),
        text("templateName", "Template name", "Typical office"),
    ],
    requires_project=False,
)
def grid_template(ctx: FeatureContext, values: dict) -> dict:
    """Package selected bay dimensions and resultant footprint as a reusable grid template."""
    xs, ys = _spacings(values["xSpacingsMm"]), _spacings(values["ySpacingsMm"])
    return result(
        summary={
            "templateName": values["templateName"],
            "xBayCount": len(xs),
            "yBayCount": len(ys),
            "overallWidthM": sum(xs) / 1000,
            "overallDepthM": sum(ys) / 1000,
            "gridAreaM2": sum(xs) * sum(ys) / 1_000_000,
        },
        tables=[
            table(
                "Template bay spacings",
                [("axis", "Axis"), ("bay", "Bay"), ("spacingMm", "Spacing", "mm")],
                [
                    {"axis": axis, "bay": i + 1, "spacingMm": v}
                    for axis, vals in (("X", xs), ("Y", ys))
                    for i, v in enumerate(vals)
                ],
            )
        ],
    )


@feature(
    "grid.gridVisibility",
    "Grid Visibility",
    part="floorPlan",
    fields=[
        text("storeys", "Visible storey ids (comma-separated)", "L1,L2"),
        checkbox("showX", "Show X grids", True),
        checkbox("showY", "Show Y grids", True),
        checkbox("showLabels", "Show bubbles", True),
    ],
)
def grid_visibility(ctx: FeatureContext, values: dict) -> dict:
    """Resolve visible grid axes and validate storey filters against the current project."""
    plan = plan_data(ctx)
    chosen = {s.strip() for s in values["storeys"].split(",") if s.strip()}
    known = {s["id"] for s in plan["stories"]}
    missing = chosen - known
    if missing:
        raise FeatureInputError(f"Unknown storey id(s): {', '.join(sorted(missing))}.")
    rows = [
        {"axis": "X", "visible": values["showX"], "lineCount": len(plan["grids"]["x"])},
        {"axis": "Y", "visible": values["showY"], "lineCount": len(plan["grids"]["y"])},
    ]
    return result(
        summary={"visibleStoreyCount": len(chosen), "labelsVisible": values["showLabels"]},
        tables=[
            table(
                "Grid visibility settings",
                [("axis", "Axis"), ("visible", "Visible"), ("lineCount", "Lines")],
                rows,
            )
        ],
    )


@feature(
    "grid.gridReference",
    "Grid Reference",
    part="floorPlan",
    fields=[
        text("linkedModel", "Linked model name", "Architecture"),
        number("offsetXmm", "X alignment offset", 0, unit="mm"),
        number("offsetYmm", "Y alignment offset", 0, unit="mm"),
        number("rotationDeg", "Rotation", 0, unit="°"),
    ],
)
def grid_reference(ctx: FeatureContext, values: dict) -> dict:
    """Transform current grid origin and axes into the linked-model coordinate frame."""
    plan = plan_data(ctx)
    theta = math.radians(values["rotationDeg"])
    c, s = math.cos(theta), math.sin(theta)
    rows = []
    for g in plan["grids"]["x"]:
        rows.append(
            {
                "axis": "X",
                "label": g["label"],
                "xMm": values["offsetXmm"] + c * float(g["position"]),
                "yMm": values["offsetYmm"] + s * float(g["position"]),
            }
        )
    for g in plan["grids"]["y"]:
        rows.append(
            {
                "axis": "Y",
                "label": g["label"],
                "xMm": values["offsetXmm"] - s * float(g["position"]),
                "yMm": values["offsetYmm"] + c * float(g["position"]),
            }
        )
    return result(
        summary={
            "linkedModel": values["linkedModel"],
            "referenceLineCount": len(rows),
            "rotationDeg": values["rotationDeg"],
        },
        tables=[
            table(
                "Linked grid references",
                [("axis", "Axis"), ("label", "Grid"), ("xMm", "X", "mm"), ("yMm", "Y", "mm")],
                rows,
            )
        ],
    )


@feature(
    "grid.gridClash",
    "Grid Clash",
    part="floorPlan",
    fields=[number("toleranceMm", "Maximum grid offset", 50, unit="mm", min=0)],
)
def grid_clash(ctx: FeatureContext, values: dict) -> dict:
    """Flag column centerlines outside the nearest pair of grid lines by more than tolerance."""
    plan, rows = profile(ctx)
    xs = [float(g["position"]) for g in plan["grids"]["x"]]
    ys = [float(g["position"]) for g in plan["grids"]["y"]]
    findings = []
    for r in rows:
        if r["category"] != "column":
            continue
        dx = min((abs(r["x1Mm"] - x) for x in xs), default=math.inf)
        dy = min((abs(r["y1Mm"] - y) for y in ys), default=math.inf)
        if math.hypot(dx, dy) > values["toleranceMm"]:
            findings.append(
                {
                    "memberId": r["id"],
                    "gridOffsetMm": math.hypot(dx, dy),
                    "nearestXOffsetMm": dx,
                    "nearestYOffsetMm": dy,
                }
            )
    return result(
        summary={"gridClashCount": len(findings), "toleranceMm": values["toleranceMm"]},
        tables=[
            table(
                "Columns off structural grid",
                [
                    ("memberId", "Column"),
                    ("gridOffsetMm", "Offset", "mm"),
                    ("nearestXOffsetMm", "X difference", "mm"),
                    ("nearestYOffsetMm", "Y difference", "mm"),
                ],
                findings,
            )
        ],
    )


@feature(
    "grid.gridLock",
    "Grid Lock",
    part="floorPlan",
    fields=[text("labels", "Grid labels to lock (blank for all)", "")],
)
def grid_lock(ctx: FeatureContext, values: dict) -> dict:
    """Resolve a grid-lock selection and report the coordinate records it covers."""
    plan = plan_data(ctx)
    requested = {x.strip() for x in values["labels"].split(",") if x.strip()}
    lines = plan["grids"]["x"] + plan["grids"]["y"]
    missing = requested - {g["label"] for g in lines}
    if missing:
        raise FeatureInputError(f"Unknown grid label(s): {', '.join(sorted(missing))}.")
    selected = [g for g in lines if not requested or g["label"] in requested]
    return result(
        summary={"lockedGridCount": len(selected)},
        tables=[
            table(
                "Grid lines selected for locking",
                [("label", "Label"), ("positionMm", "Position", "mm")],
                [{"label": g["label"], "positionMm": g["position"]} for g in selected],
            )
        ],
        notes=[
            "This result identifies the lock target set; lock state is a view/editor property, not stored in floor-plan.json."
        ],
    )


@feature(
    "grid.gridCompare",
    "Grid Compare",
    part="floorPlan",
    fields=[text("comparisonJson", "Comparison grids JSON", '{"x":[],"y":[]}')],
)
def grid_compare(ctx: FeatureContext, values: dict) -> dict:
    """Compare current axis labels and positions with a supplied linked or saved grid JSON."""
    plan = plan_data(ctx)
    try:
        other = __import__("json").loads(values["comparisonJson"])
    except ValueError as exc:
        raise FeatureInputError("Comparison grids must be valid JSON with x and y arrays.") from exc
    changes = []
    for axis in ("x", "y"):
        old = {g["label"]: float(g["position"]) for g in other.get(axis, [])}
        new = {g["label"]: float(g["position"]) for g in plan["grids"][axis]}
        for label in sorted(set(old) | set(new)):
            kind = (
                "added"
                if label not in old
                else "removed"
                if label not in new
                else "moved"
                if abs(new[label] - old[label]) > 1e-6
                else "unchanged"
            )
            changes.append(
                {
                    "axis": axis.upper(),
                    "label": label,
                    "change": kind,
                    "currentMm": new.get(label),
                    "comparisonMm": old.get(label),
                    "deltaMm": new.get(label) - old[label]
                    if label in new and label in old
                    else None,
                }
            )
    return result(
        summary={
            "changedGridLines": sum(row["change"] != "unchanged" for row in changes),
            "comparedGridLines": len(changes),
        },
        tables=[
            table(
                "Grid comparison",
                [
                    ("axis", "Axis"),
                    ("label", "Label"),
                    ("change", "Change"),
                    ("currentMm", "Current", "mm"),
                    ("comparisonMm", "Comparison", "mm"),
                    ("deltaMm", "Delta", "mm"),
                ],
                changes,
            )
        ],
    )


@feature(
    "grid.gridOverlay",
    "Grid Overlay",
    part="floorPlan",
    fields=[
        text("linkedGridJson", "Linked grid axes JSON", '{"x":[],"y":[]}'),
        number("translationXmm", "Linked X offset", 0, unit="mm"),
        number("translationYmm", "Linked Y offset", 0, unit="mm"),
    ],
)
def grid_overlay(ctx: FeatureContext, values: dict) -> dict:
    """Translate linked grid axes into local coordinates and tabulate nearest structural-grid offsets."""
    plan = plan_data(ctx)
    try:
        linked = __import__("json").loads(values["linkedGridJson"])
    except ValueError as exc:
        raise FeatureInputError("Linked grid input must be valid JSON.") from exc
    local = {
        axis: {g["label"]: float(g["position"]) for g in plan["grids"][axis]} for axis in ("x", "y")
    }
    rows = []
    for axis in ("x", "y"):
        for g in linked.get(axis, []):
            position = float(g["position"]) + (
                values["translationXmm"] if axis == "x" else values["translationYmm"]
            )
            nearest = min(
                local[axis].items(), key=lambda item: abs(item[1] - position), default=("", 0.0)
            )
            rows.append(
                {
                    "axis": axis.upper(),
                    "linkedLabel": g["label"],
                    "linkedPositionMm": position,
                    "nearestLocalLabel": nearest[0],
                    "differenceMm": position - nearest[1],
                }
            )
    return result(
        summary={
            "overlaidLineCount": len(rows),
            "maximumAlignmentDifferenceMm": max((abs(r["differenceMm"]) for r in rows), default=0),
        },
        tables=[
            table(
                "Linked grid overlay",
                [
                    ("axis", "Axis"),
                    ("linkedLabel", "Linked label"),
                    ("linkedPositionMm", "Linked position", "mm"),
                    ("nearestLocalLabel", "Nearest local label"),
                    ("differenceMm", "Difference", "mm"),
                ],
                rows,
            )
        ],
    )

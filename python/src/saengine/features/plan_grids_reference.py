"""Reference Lines ribbon: reference geometry, work planes and annotation data."""

from __future__ import annotations

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
from saengine.features.plan_common import plan_data


def _point(raw: str) -> tuple[float, float]:
    try:
        x, y = [float(v.strip()) for v in raw.split(",")[:2]]
    except (ValueError, TypeError) as exc:
        raise FeatureInputError("Enter a 2D point as x,y in millimetres.") from exc
    return x, y


def _reference_line(values: dict) -> tuple[float, float, float, float]:
    x1, y1 = _point(values["startMm"])
    x2, y2 = _point(values["endMm"])
    if math.hypot(x2 - x1, y2 - y1) <= 1e-8:
        raise FeatureInputError("Reference line endpoints must differ.")
    return x1, y1, x2, y2


@feature(
    "planGridsReference.drawLine",
    "Draw Line",
    part="floorPlan",
    fields=[
        text("name", "Line name", "Ref-A"),
        text("startMm", "Start x,y", "0,0"),
        text("endMm", "End x,y", "10000,0"),
    ],
    requires_project=False,
)
def draw_line(ctx: FeatureContext, values: dict) -> dict:
    """Calculate length, bearing and midpoint for a proposed reference line."""
    x1, y1, x2, y2 = _reference_line(values)
    return result(
        summary={
            "name": values["name"],
            "lengthM": math.hypot(x2 - x1, y2 - y1) / 1000,
            "bearingDeg": math.degrees(math.atan2(y2 - y1, x2 - x1)) % 360,
            "midpointXMm": (x1 + x2) / 2,
            "midpointYMm": (y1 + y2) / 2,
        }
    )


@feature(
    "planGridsReference.offsetLine",
    "Offset Line",
    part="floorPlan",
    fields=[
        text("startMm", "Line start x,y", "0,0"),
        text("endMm", "Line end x,y", "10000,0"),
        number("offsetMm", "Signed normal offset", 1000, unit="mm"),
    ],
    requires_project=False,
)
def offset_line(ctx: FeatureContext, values: dict) -> dict:
    """Create a parallel line at a signed normal distance from the reference line."""
    x1, y1, x2, y2 = _reference_line(values)
    length = math.hypot(x2 - x1, y2 - y1)
    nx = -(y2 - y1) / length
    ny = (x2 - x1) / length
    d = values["offsetMm"]
    return result(
        summary={
            "startXMm": x1 + nx * d,
            "startYMm": y1 + ny * d,
            "endXMm": x2 + nx * d,
            "endYMm": y2 + ny * d,
            "offsetMm": d,
        }
    )


@feature(
    "planGridsReference.fromGrid",
    "From Grid",
    part="floorPlan",
    fields=[
        select("axis", "Grid axis", [("x", "X"), ("y", "Y")]),
        text("label", "Grid label", "A"),
        number("startMm", "Line start station", -10000, unit="mm"),
        number("endMm", "Line end station", 10000, unit="mm"),
    ],
)
def from_grid(ctx: FeatureContext, values: dict) -> dict:
    """Construct reference-line endpoints on a selected structural grid axis."""
    plan = plan_data(ctx)
    line = next((g for g in plan["grids"][values["axis"]] if g["label"] == values["label"]), None)
    if line is None:
        raise FeatureInputError("Grid label does not exist on the selected axis.")
    if values["endMm"] <= values["startMm"]:
        raise FeatureInputError("End station must be greater than start station.")
    pos = float(line["position"])
    ends = (
        {"startXMm": pos, "startYMm": values["startMm"], "endXMm": pos, "endYMm": values["endMm"]}
        if values["axis"] == "x"
        else {
            "startXMm": values["startMm"],
            "startYMm": pos,
            "endXMm": values["endMm"],
            "endYMm": pos,
        }
    )
    return result(
        summary={
            "gridLabel": values["label"],
            "lengthM": (values["endMm"] - values["startMm"]) / 1000,
            **ends,
        }
    )


@feature(
    "planGridsReference.copyLine",
    "Copy Line",
    part="floorPlan",
    fields=[
        text("startMm", "Line start x,y", "0,0"),
        text("endMm", "Line end x,y", "10000,0"),
        number("copies", "Copies", 2, min=1, max=100),
        number("spacingMm", "Parallel spacing", 1000, unit="mm", min=1),
    ],
)
def copy_line(ctx: FeatureContext, values: dict) -> dict:
    """Create a parallel reference-line array with constant normal spacing."""
    x1, y1, x2, y2 = _reference_line(values)
    length = math.hypot(x2 - x1, y2 - y1)
    nx = -(y2 - y1) / length
    ny = (x2 - x1) / length
    rows = [
        {
            "copy": i,
            "startXMm": x1 + nx * i * values["spacingMm"],
            "startYMm": y1 + ny * i * values["spacingMm"],
            "endXMm": x2 + nx * i * values["spacingMm"],
            "endYMm": y2 + ny * i * values["spacingMm"],
        }
        for i in range(1, int(values["copies"]) + 1)
    ]
    return result(
        summary={"copiedLineCount": len(rows), "normalSpacingMm": values["spacingMm"]},
        tables=[
            table(
                "Parallel reference lines",
                [
                    ("copy", "Copy"),
                    ("startXMm", "Start X", "mm"),
                    ("startYMm", "Start Y", "mm"),
                    ("endXMm", "End X", "mm"),
                    ("endYMm", "End Y", "mm"),
                ],
                rows,
            )
        ],
    )


@feature(
    "planGridsReference.lockLine",
    "Lock Line",
    part="floorPlan",
    fields=[
        text("lineName", "Reference line name", "Ref-A"),
        checkbox("lockPosition", "Lock position", True),
        checkbox("lockDirection", "Lock direction", True),
    ],
    requires_project=False,
)
def lock_line(ctx: FeatureContext, values: dict) -> dict:
    """Describe line constraint flags for position and direction."""
    if not values["lockPosition"] and not values["lockDirection"]:
        raise FeatureInputError("Select a position or direction constraint to lock.")
    return result(
        summary={
            "lineName": values["lineName"],
            "positionLocked": values["lockPosition"],
            "directionLocked": values["lockDirection"],
        }
    )


@feature(
    "planGridsReference.addDimension",
    "Add Dimension",
    part="floorPlan",
    fields=[
        text("startMm", "First point x,y", "0,0"),
        text("endMm", "Second point x,y", "6000,0"),
        number("textOffsetMm", "Dimension text offset", 500, unit="mm"),
    ],
    requires_project=False,
)
def add_dimension(ctx: FeatureContext, values: dict) -> dict:
    """Measure a reference dimension between two points and compute its annotation offset."""
    x1, y1 = _point(values["startMm"])
    x2, y2 = _point(values["endMm"])
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        raise FeatureInputError("Dimension points must differ.")
    nx, ny = -dy / length, dx / length
    mid = ((x1 + x2) / 2, (y1 + y2) / 2)
    return result(
        summary={
            "dimensionMm": length,
            "dimensionM": length / 1000,
            "textXMm": mid[0] + nx * values["textOffsetMm"],
            "textYMm": mid[1] + ny * values["textOffsetMm"],
        }
    )


@feature(
    "planGridsReference.parametricLink",
    "Parametric Link",
    part="floorPlan",
    fields=[
        text("sourceGridLabel", "Source grid label", "A"),
        text("targetLineName", "Target reference line", "Facade datum"),
        number("offsetMm", "Maintained offset", 0, unit="mm"),
    ],
)
def parametric_link(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the target coordinate that maintains a parametric offset from a grid line."""
    plan = plan_data(ctx)
    line = next(
        (
            g
            for g in plan["grids"]["x"] + plan["grids"]["y"]
            if g["label"] == values["sourceGridLabel"]
        ),
        None,
    )
    if line is None:
        raise FeatureInputError("Source grid label does not exist.")
    return result(
        summary={
            "sourceGridLabel": line["label"],
            "sourceCoordinateMm": line["position"],
            "targetLineName": values["targetLineName"],
            "linkedCoordinateMm": float(line["position"]) + values["offsetMm"],
            "offsetMm": values["offsetMm"],
        }
    )


@feature(
    "planGridsReference.groupLines",
    "Group Lines",
    part="floorPlan",
    fields=[
        text("lineNames", "Reference line names", "Ref-A,Ref-B,Ref-C"),
        text("groupName", "Group name", "Facade datums"),
    ],
    requires_project=False,
)
def group_lines(ctx: FeatureContext, values: dict) -> dict:
    """Create a named group definition from ordered reference-line names."""
    names = [x.strip() for x in values["lineNames"].split(",") if x.strip()]
    if not names:
        raise FeatureInputError("Enter at least one reference line name.")
    return result(
        summary={"groupName": values["groupName"], "lineCount": len(names)},
        tables=[
            table(
                "Reference line group",
                [("order", "Order"), ("lineName", "Line")],
                [{"order": i + 1, "lineName": name} for i, name in enumerate(names)],
            )
        ],
    )


@feature(
    "planGridsReference.toggleVisibility",
    "Toggle Visibility",
    part="floorPlan",
    fields=[
        text("lineNames", "Reference line names", "Ref-A,Ref-B"),
        select("visibility", "Set visibility", [("visible", "Visible"), ("hidden", "Hidden")]),
    ],
    requires_project=False,
)
def toggle_visibility(ctx: FeatureContext, values: dict) -> dict:
    """Set a visibility state for the named reference line set."""
    names = [x.strip() for x in values["lineNames"].split(",") if x.strip()]
    return result(
        summary={"lineCount": len(names), "visibility": values["visibility"]},
        tables=[
            table(
                "Reference visibility",
                [("lineName", "Line"), ("visibility", "Visibility")],
                [{"lineName": name, "visibility": values["visibility"]} for name in names],
            )
        ],
    )


@feature(
    "planGridsReference.extendLine",
    "Extend Line",
    part="floorPlan",
    fields=[
        text("startMm", "Line start x,y", "0,0"),
        text("endMm", "Line end x,y", "6000,0"),
        number("extensionStartMm", "Start extension", 500, unit="mm"),
        number("extensionEndMm", "End extension", 1000, unit="mm"),
    ],
    requires_project=False,
)
def extend_line(ctx: FeatureContext, values: dict) -> dict:
    """Extend reference endpoints along the line's unit direction."""
    x1, y1, x2, y2 = _reference_line(values)
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    return result(
        summary={
            "startXMm": x1 - ux * values["extensionStartMm"],
            "startYMm": y1 - uy * values["extensionStartMm"],
            "endXMm": x2 + ux * values["extensionEndMm"],
            "endYMm": y2 + uy * values["extensionEndMm"],
            "resultLengthMm": length + values["extensionStartMm"] + values["extensionEndMm"],
        }
    )


@feature(
    "planGridsReference.lineColour",
    "Line Colour",
    part="floorPlan",
    fields=[
        text("lineName", "Reference line name", "Ref-A"),
        text("colourHex", "Line colour", "#336699"),
    ],
    requires_project=False,
)
def line_colour(ctx: FeatureContext, values: dict) -> dict:
    """Validate and report a hexadecimal display colour for a reference line."""
    color = values["colourHex"]
    if (
        len(color) != 7
        or not color.startswith("#")
        or any(c not in "0123456789abcdefABCDEF" for c in color[1:])
    ):
        raise FeatureInputError("Enter a six-digit hexadecimal colour such as #336699.")
    return result(summary={"lineName": values["lineName"], "colourHex": color.upper()})


@feature(
    "planGridsReference.deleteLine",
    "Delete Line",
    part="floorPlan",
    fields=[
        text("lineNames", "Reference line names to delete", "Ref-A,Ref-B"),
        text("referencedNames", "Names referenced by dimensions or grids", ""),
    ],
    requires_project=False,
)
def delete_line(ctx: FeatureContext, values: dict) -> dict:
    """Identify downstream references that should be reviewed before deleting named lines."""
    names = {x.strip() for x in values["lineNames"].split(",") if x.strip()}
    referenced = {x.strip() for x in values["referencedNames"].split(",") if x.strip()}
    return result(
        summary={"deleteCandidates": len(names), "referencedLines": len(names & referenced)},
        tables=[
            table(
                "Reference-line deletion review",
                [("lineName", "Line"), ("hasReferences", "Has references")],
                [{"lineName": n, "hasReferences": n in referenced} for n in sorted(names)],
            )
        ],
    )


@feature(
    "planGridsReference.setWorkPlane",
    "Set Work Plane",
    part="floorPlan",
    fields=[
        number("elevationMm", "Work plane elevation", 3200, unit="mm"),
        text("referenceName", "Reference name", "Level 1"),
        number("rotationDeg", "Work plane rotation", 0, unit="°"),
    ],
    requires_project=False,
)
def set_work_plane(ctx: FeatureContext, values: dict) -> dict:
    """Define a horizontal work-plane origin, elevation and local X orientation."""
    return result(
        summary={
            "referenceName": values["referenceName"],
            "elevationM": values["elevationMm"] / 1000,
            "xAxisBearingDeg": values["rotationDeg"] % 360,
            "normal": "+Z",
        }
    )


@feature(
    "planGridsReference.gridPlane",
    "Grid Plane",
    part="floorPlan",
    fields=[
        select("axis", "Grid axis", [("x", "X"), ("y", "Y")]),
        text("label", "Grid label", "A"),
    ],
)
def grid_plane(ctx: FeatureContext, values: dict) -> dict:
    """Resolve a named vertical grid plane and report its constant coordinate."""
    plan = plan_data(ctx)
    line = next((g for g in plan["grids"][values["axis"]] if g["label"] == values["label"]), None)
    if line is None:
        raise FeatureInputError("Grid label was not found on the selected axis.")
    return result(
        summary={
            "plane": "X constant" if values["axis"] == "x" else "Y constant",
            "gridLabel": line["label"],
            "coordinateMm": line["position"],
        }
    )


@feature(
    "planGridsReference.planeOffset",
    "Plane Offset",
    part="floorPlan",
    fields=[
        number("sourceCoordinateMm", "Source plane coordinate", 0, unit="mm"),
        number("offsetMm", "Signed plane offset", 1000, unit="mm"),
        select("axis", "Plane normal", [("x", "X"), ("y", "Y")]),
    ],
    requires_project=False,
)
def plane_offset(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the coordinate of a parallel plane at a signed normal offset."""
    return result(
        summary={
            "axis": values["axis"].upper(),
            "sourceCoordinateMm": values["sourceCoordinateMm"],
            "targetCoordinateMm": values["sourceCoordinateMm"] + values["offsetMm"],
            "offsetMm": values["offsetMm"],
        }
    )


@feature(
    "planGridsReference.addReferencePoint",
    "Add Reference Point",
    part="floorPlan",
    fields=[text("name", "Point name", "Datum P1"), text("coordinateMm", "Point x,y", "1200,2400")],
    requires_project=False,
)
def add_reference_point(ctx: FeatureContext, values: dict) -> dict:
    """Parse a reference point coordinate and report its radial distance from local origin."""
    x, y = _point(values["coordinateMm"])
    return result(
        summary={
            "name": values["name"],
            "xMm": x,
            "yMm": y,
            "distanceFromOriginMm": math.hypot(x, y),
        }
    )


@feature(
    "planGridsReference.snapGrid",
    "Snap Grid",
    part="floorPlan",
    fields=[
        text("coordinateMm", "Point x,y", "5950,120"),
        number("toleranceMm", "Snap tolerance", 250, unit="mm", min=0),
    ],
)
def snap_grid(ctx: FeatureContext, values: dict) -> dict:
    """Snap a free point to the nearest grid intersection within the entered tolerance."""
    plan = plan_data(ctx)
    x, y = _point(values["coordinateMm"])
    candidates = [(gx, gy) for gx in plan["grids"]["x"] for gy in plan["grids"]["y"]]
    if not candidates:
        raise FeatureInputError("No grid intersections are available.")
    gx, gy = min(
        candidates,
        key=lambda pair: math.hypot(float(pair[0]["position"]) - x, float(pair[1]["position"]) - y),
    )
    d = math.hypot(float(gx["position"]) - x, float(gy["position"]) - y)
    if d > values["toleranceMm"]:
        raise FeatureInputError(f"Nearest intersection is {d:.1f} mm away, outside tolerance.")
    return result(
        summary={
            "gridPoint": f"{gx['label']}-{gy['label']}",
            "snappedXMm": gx["position"],
            "snappedYMm": gy["position"],
            "offsetMm": d,
        }
    )


@feature(
    "planGridsReference.pointCoordinates",
    "Point Coordinates",
    part="floorPlan",
    fields=[text("coordinateMm", "Point x,y", "1250,2500")],
    requires_project=False,
)
def point_coordinates(ctx: FeatureContext, values: dict) -> dict:
    """Report point X/Y coordinates, radial distance and bearing from the local origin."""
    x, y = _point(values["coordinateMm"])
    return result(
        summary={
            "xMm": x,
            "yMm": y,
            "radiusM": math.hypot(x, y) / 1000,
            "bearingDeg": math.degrees(math.atan2(y, x)) % 360,
        }
    )


@feature(
    "planGridsReference.subcategorySetup",
    "Subcategory Setup",
    part="floorPlan",
    fields=[
        text("names", "Reference line categories", "Axes,Setback,Datum"),
        text("defaultColour", "Default colour", "#666666"),
    ],
    requires_project=False,
)
def subcategory_setup(ctx: FeatureContext, values: dict) -> dict:
    """Create named reference-line subcategory definitions with a validated default colour."""
    names = [x.strip() for x in values["names"].split(",") if x.strip()]
    colour = values["defaultColour"]
    if (
        len(colour) != 7
        or not colour.startswith("#")
        or any(c not in "0123456789abcdefABCDEF" for c in colour[1:])
    ):
        raise FeatureInputError("Default colour must be a six-digit hexadecimal value.")
    return result(
        summary={"subcategoryCount": len(names), "defaultColour": colour.upper()},
        tables=[
            table(
                "Reference subcategories",
                [("name", "Subcategory"), ("colour", "Colour")],
                [{"name": name, "colour": colour.upper()} for name in names],
            )
        ],
    )


@feature(
    "planGridsReference.lockGeometry",
    "Lock Geometry",
    part="floorPlan",
    fields=[
        text("lineNames", "Line names to lock", "Ref-A,Ref-B"),
        checkbox("lockEndpoints", "Lock endpoints", True),
        checkbox("lockDirection", "Lock direction", True),
    ],
    requires_project=False,
)
def lock_geometry(ctx: FeatureContext, values: dict) -> dict:
    """Resolve the geometry constraints selected for a group of reference lines."""
    names = [x.strip() for x in values["lineNames"].split(",") if x.strip()]
    if not (values["lockEndpoints"] or values["lockDirection"]):
        raise FeatureInputError("Choose at least one geometry constraint.")
    return result(
        summary={
            "lineCount": len(names),
            "endpointsLocked": values["lockEndpoints"],
            "directionLocked": values["lockDirection"],
        },
        tables=[
            table(
                "Locked geometry",
                [
                    ("lineName", "Line"),
                    ("endpointsLocked", "Lock endpoints"),
                    ("directionLocked", "Lock direction"),
                ],
                [
                    {
                        "lineName": name,
                        "endpointsLocked": values["lockEndpoints"],
                        "directionLocked": values["lockDirection"],
                    }
                    for name in names
                ],
            )
        ],
    )


@feature(
    "planGridsReference.cleanUnused",
    "Clean Unused",
    part="floorPlan",
    fields=[
        text("allNames", "Defined reference line names", "Ref-A,Ref-B,Ref-C"),
        text("usedNames", "Names referenced by model annotations", "Ref-A,Ref-C"),
    ],
    requires_project=False,
)
def clean_unused(ctx: FeatureContext, values: dict) -> dict:
    """Find reference-line names that are not used by any supplied annotation or model link."""
    all_names = {x.strip() for x in values["allNames"].split(",") if x.strip()}
    used = {x.strip() for x in values["usedNames"].split(",") if x.strip()}
    unused = sorted(all_names - used)
    return result(
        summary={"definedLines": len(all_names), "unusedLines": len(unused)},
        tables=[
            table(
                "Unused reference lines",
                [("lineName", "Line")],
                [{"lineName": name} for name in unused],
            )
        ],
    )


@feature(
    "planGridsReference.referenceSchedule",
    "Reference Schedule",
    part="floorPlan",
    fields=[
        text(
            "lineRecords",
            "name,start x,y,end x,y; semicolon separated",
            "Ref-A,0,0,10000,0;Ref-B,0,0,0,8000",
        )
    ],
    requires_project=False,
)
def reference_schedule(ctx: FeatureContext, values: dict) -> dict:
    """Build a measurable schedule of named reference lines from their endpoint records."""
    rows = []
    try:
        for rec in values["lineRecords"].split(";"):
            if rec.strip():
                name, x1, y1, x2, y2 = [x.strip() for x in rec.split(",")[:5]]
                length = math.hypot(float(x2) - float(x1), float(y2) - float(y1))
                rows.append(
                    {
                        "name": name,
                        "lengthM": length / 1000,
                        "bearingDeg": math.degrees(
                            math.atan2(float(y2) - float(y1), float(x2) - float(x1))
                        )
                        % 360,
                    }
                )
    except (ValueError, IndexError) as exc:
        raise FeatureInputError("Use name,x1,y1,x2,y2 records separated by semicolons.") from exc
    return result(
        summary={"referenceLines": len(rows), "totalLengthM": sum(r["lengthM"] for r in rows)},
        tables=[
            table(
                "Reference line schedule",
                [("name", "Line"), ("lengthM", "Length", "m"), ("bearingDeg", "Bearing", "°")],
                rows,
            )
        ],
    )

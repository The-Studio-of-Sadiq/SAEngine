"""BIM 3D navigation, selection and measurement feature buttons."""

from __future__ import annotations

from typing import Any

from saengine.features import FeatureContext, checkbox, feature, number, result, select, table, text
from saengine.features.bim_common import element_rows, require_bim, write_bim_json


@feature(
    "bimNavigation.selectAllInstances",
    "Select All Instances",
    part="bim",
    fields=[text("familyType", "Family or object type", "C400x600")],
)
def select_all_instances(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select every model instance of a family or object type."""
    data = require_bim(ctx)
    target = str(values["familyType"]).strip()
    rows = [row for row in element_rows(data) if row["type"] == target]
    return result(
        summary={"familyType": target, "selectedCount": len(rows)},
        tables=[table("Selected Instances", [("id", "Element id"), ("kind", "Category")], rows)],
    )


@feature(
    "bimNavigation.selectByFilter",
    "Select by Filter",
    part="bim",
    fields=[
        select(
            "kind",
            "Element category",
            [
                ("column", "Columns"),
                ("beam", "Beams"),
                ("wall", "Walls"),
                ("slab", "Slabs"),
                ("footing", "Footings"),
            ],
            "column",
        ),
        text("typeFilter", "Object type contains", ""),
    ],
)
def select_by_filter(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select elements matching category and object-type filters."""
    data = require_bim(ctx)
    needle = str(values["typeFilter"]).strip().lower()
    rows = [
        row
        for row in element_rows(data)
        if row["kind"] == values["kind"] and (not needle or needle in row["type"].lower())
    ]
    return result(
        summary={"kind": values["kind"], "selectedCount": len(rows)},
        tables=[table("Filtered Selection", [("id", "Element id"), ("type", "Object type")], rows)],
    )


@feature(
    "bimNavigation.selectionSets",
    "Selection Sets",
    part="bim",
    fields=[
        text("setName", "Selection set name", "Review set"),
        text("elementIds", "Element ids", "C1,C2,B1"),
    ],
)
def selection_sets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Save a named selection set."""
    data = require_bim(ctx)
    ids = {item.strip() for item in str(values["elementIds"]).split(",") if item.strip()}
    present = [row["id"] for row in element_rows(data) if row["id"] in ids]
    payload = {"name": values["setName"].strip() or "Review set", "elementIds": present}
    path = write_bim_json(ctx, "selection_set.json", payload)
    return result(
        summary={"setName": payload["name"], "selectedCount": len(present), "savedPath": path},
        notes=[f"Selection set written to {path}."],
    )


@feature(
    "bimNavigation.tapeMeasure",
    "Tape Measure",
    part="bim",
    fields=[
        number("x1", "Start X", 0.0, unit="mm"),
        number("y1", "Start Y", 0.0, unit="mm"),
        number("z1", "Start Z", 0.0, unit="mm"),
        number("x2", "End X", 6000.0, unit="mm"),
        number("y2", "End Y", 0.0, unit="mm"),
        number("z2", "End Z", 0.0, unit="mm"),
    ],
)
def tape_measure(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Measure the 3D distance between two coordinates."""
    require_bim(ctx)
    dx = values["x2"] - values["x1"]
    dy = values["y2"] - values["y1"]
    dz = values["z2"] - values["z1"]
    return result(
        summary={
            "distanceMm": (dx * dx + dy * dy + dz * dz) ** 0.5,
            "distanceM": ((dx * dx + dy * dy + dz * dz) ** 0.5) / 1000,
        }
    )


@feature(
    "bimNavigation.measureAngle",
    "Measure Angle",
    part="bim",
    fields=[
        number("startAzimuth", "Start edge azimuth", 0.0, unit="°"),
        number("endAzimuth", "End edge azimuth", 90.0, unit="°"),
    ],
)
def measure_angle(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate an included angle between two edge directions."""
    require_bim(ctx)
    angle = abs((values["endAzimuth"] - values["startAzimuth"] + 180) % 360 - 180)
    return result(summary={"includedAngleDeg": angle})


@feature(
    "bimNavigation.snapToVertex",
    "Snap to Vertex",
    part="bim",
    fields=[
        checkbox("enabled", "Enable vertex snapping", True),
        number("tolerance", "Snap tolerance", 50.0, unit="mm", min=0),
    ],
)
def snap_to_vertex(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure snap-to-element-vertex behavior."""
    require_bim(ctx)
    return result(summary={"enabled": bool(values["enabled"]), "toleranceMm": values["tolerance"]})


@feature(
    "bimNavigation.walkthroughPath",
    "Walkthrough Path",
    part="bim",
    fields=[
        text("pathName", "Path name", "Entrance tour"),
        number("duration", "Duration", 60.0, unit="s", min=1),
        number("eyeHeight", "Camera eye height", 1.6, unit="m", min=0.5),
    ],
)
def walkthrough_path(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a walkthrough-path definition."""
    data = require_bim(ctx)
    payload = {
        "name": values["pathName"].strip() or "Entrance tour",
        "durationS": values["duration"],
        "eyeHeightM": values["eyeHeight"],
        "elementCount": len(data["elements"]),
    }
    path = write_bim_json(ctx, "walkthrough_path.json", payload)
    return result(
        summary={"pathName": payload["name"], "durationS": values["duration"], "exportPath": path}
    )


@feature(
    "bimNavigation.animation",
    "Animation",
    part="bim",
    fields=[
        select("format", "Export format", [("mp4", "MP4"), ("webm", "WebM")], "mp4"),
        number("framesPerSecond", "Frame rate", 30.0, unit="fps", min=1, max=120),
        number("duration", "Duration", 60.0, unit="s", min=1),
    ],
)
def animation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure walkthrough animation export."""
    require_bim(ctx)
    return result(
        summary={
            "format": values["format"],
            "framesPerSecond": values["framesPerSecond"],
            "durationS": values["duration"],
            "frameCount": int(values["framesPerSecond"] * values["duration"]),
        }
    )


@feature(
    "bimNavigation.flyMode",
    "Fly Mode",
    part="bim",
    fields=[
        number("speed", "Fly speed", 3.0, unit="m/s", min=0.1),
        checkbox("gravity", "Apply gravity", False),
    ],
)
def fly_mode(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure unrestricted 3D fly navigation."""
    require_bim(ctx)
    return result(summary={"flySpeedMPerS": values["speed"], "gravity": bool(values["gravity"])})


@feature(
    "bimNavigation.panTool",
    "Pan Tool",
    part="bim",
    fields=[
        select(
            "axis",
            "Pan axis",
            [("both", "Both"), ("horizontal", "Horizontal"), ("vertical", "Vertical")],
            "both",
        ),
        checkbox("reverse", "Reverse drag", False),
    ],
)
def pan_tool(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure the viewport pan tool."""
    require_bim(ctx)
    return result(summary={"panAxis": values["axis"], "reverseDrag": bool(values["reverse"])})


@feature(
    "bimNavigation.zoomWindow",
    "Zoom Window",
    part="bim",
    fields=[
        number("centerX", "Window center X", 6500.0, unit="mm"),
        number("centerY", "Window center Y", 2500.0, unit="mm"),
        number("width", "Window width", 13000.0, unit="mm", min=1),
        number("height", "Window height", 5000.0, unit="mm", min=1),
    ],
)
def zoom_window(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a rectangular zoom window."""
    require_bim(ctx)
    return result(
        summary={
            "centerXMm": values["centerX"],
            "centerYMm": values["centerY"],
            "widthMm": values["width"],
            "heightMm": values["height"],
        }
    )


@feature(
    "bimNavigation.zoomExtents",
    "Zoom Extents",
    part="bim",
    fields=[
        checkbox("includeHidden", "Include hidden elements", False),
        number("padding", "View padding", 5.0, unit="%", min=0, max=50),
    ],
)
def zoom_extents(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Fit the view to model extents."""
    data = require_bim(ctx)
    xs = []
    ys = []
    zs = []
    for e in data["elements"]:
        if isinstance(e, dict):
            for k in ("position", "start", "end"):
                p = e.get(k)
                if isinstance(p, list) and len(p) >= 2:
                    xs.append(float(p[0]))
                    ys.append(float(p[1]))
            for k in ("bottom", "elevation", "top"):
                v = e.get(k)
                if isinstance(v, (int, float)):
                    zs.append(float(v))
    extents = {
        "minXMm": min(xs) if xs else 0,
        "maxXMm": max(xs) if xs else 0,
        "minYMm": min(ys) if ys else 0,
        "maxYMm": max(ys) if ys else 0,
        "minZMm": min(zs) if zs else 0,
        "maxZMm": max(zs) if zs else 0,
    }
    return result(
        summary={
            "includeHidden": bool(values["includeHidden"]),
            "paddingPercent": values["padding"],
            **extents,
        },
        tables=[
            table(
                "Model Extents",
                [
                    ("axis", "Axis"),
                    ("minimumMm", "Minimum [mm]", "mm"),
                    ("maximumMm", "Maximum [mm]", "mm"),
                ],
                [
                    {"axis": "X", "minimumMm": extents["minXMm"], "maximumMm": extents["maxXMm"]},
                    {"axis": "Y", "minimumMm": extents["minYMm"], "maximumMm": extents["maxYMm"]},
                    {"axis": "Z", "minimumMm": extents["minZMm"], "maximumMm": extents["maxZMm"]},
                ],
            )
        ],
    )


@feature(
    "bimNavigation.spinModel",
    "Spin Model",
    part="bim",
    fields=[
        number("speed", "Spin speed", 10.0, unit="°/s", min=0, max=360),
        select(
            "direction",
            "Direction",
            [("clockwise", "Clockwise"), ("counterclockwise", "Counter-clockwise")],
            "clockwise",
        ),
    ],
)
def spin_model(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure model auto-spin."""
    require_bim(ctx)
    return result(summary={"speedDegPerS": values["speed"], "direction": values["direction"]})


@feature(
    "bimNavigation.steeringWheel",
    "Steering Wheel",
    part="bim",
    fields=[
        checkbox("enabled", "Show steering wheel", True),
        select(
            "position",
            "Wheel position",
            [("center", "Center"), ("topRight", "Top right"), ("bottomRight", "Bottom right")],
            "bottomRight",
        ),
    ],
)
def steering_wheel(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure the navigation steering wheel."""
    require_bim(ctx)
    return result(summary={"enabled": bool(values["enabled"]), "position": values["position"]})


@feature(
    "bimNavigation.snapToEdge",
    "Snap to Edge",
    part="bim",
    fields=[
        checkbox("enabled", "Enable edge snapping", True),
        number("tolerance", "Snap tolerance", 50.0, unit="mm", min=0),
    ],
)
def snap_to_edge(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure snap to element edges."""
    require_bim(ctx)
    return result(summary={"enabled": bool(values["enabled"]), "toleranceMm": values["tolerance"]})


@feature(
    "bimNavigation.snapToFace",
    "Snap to Face",
    part="bim",
    fields=[
        checkbox("enabled", "Enable face snapping", True),
        number("tolerance", "Snap tolerance", 50.0, unit="mm", min=0),
    ],
)
def snap_to_face(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure snap to element faces."""
    require_bim(ctx)
    return result(summary={"enabled": bool(values["enabled"]), "toleranceMm": values["tolerance"]})


@feature(
    "bimNavigation.snapToGrid",
    "Snap to Grid",
    part="bim",
    fields=[
        checkbox("enabled", "Enable grid snapping", True),
        number("spacing", "Grid spacing", 1000.0, unit="mm", min=1),
    ],
)
def snap_to_grid(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure snapping to a regular coordinate grid."""
    require_bim(ctx)
    return result(summary={"enabled": bool(values["enabled"]), "spacingMm": values["spacing"]})


@feature(
    "bimNavigation.snapToCenter",
    "Snap to Center",
    part="bim",
    fields=[
        checkbox("enabled", "Enable center snapping", True),
        number("tolerance", "Snap tolerance", 50.0, unit="mm", min=0),
    ],
)
def snap_to_center(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure snap to element centroids."""
    require_bim(ctx)
    return result(summary={"enabled": bool(values["enabled"]), "toleranceMm": values["tolerance"]})


@feature(
    "bimNavigation.snapToggle",
    "Snap Toggle",
    part="bim",
    fields=[checkbox("enabled", "Enable all snapping", True)],
)
def snap_toggle(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Toggle all navigation snapping modes."""
    require_bim(ctx)
    return result(summary={"snapEnabled": bool(values["enabled"])})


@feature(
    "bimNavigation.areaMeasure",
    "Area Measure",
    part="bim",
    fields=[
        number("length", "Measured length", 6000.0, unit="mm", min=0),
        number("width", "Measured width", 5000.0, unit="mm", min=0),
    ],
)
def area_measure(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate an area from measured rectangular dimensions."""
    require_bim(ctx)
    area_mm2 = values["length"] * values["width"]
    return result(summary={"areaMm2": area_mm2, "areaM2": area_mm2 / 1e6})


@feature(
    "bimNavigation.volumeMeasure",
    "Volume Measure",
    part="bim",
    fields=[
        number("length", "Measured length", 6000.0, unit="mm", min=0),
        number("width", "Measured width", 5000.0, unit="mm", min=0),
        number("height", "Measured height", 3200.0, unit="mm", min=0),
    ],
)
def volume_measure(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate a volume from three measured dimensions."""
    require_bim(ctx)
    volume = values["length"] * values["width"] * values["height"]
    return result(summary={"volumeMm3": volume, "volumeM3": volume / 1e9})


@feature(
    "bimNavigation.pointCoordinates",
    "Point Coordinates",
    part="bim",
    fields=[
        number("x", "Point X", 0.0, unit="mm"),
        number("y", "Point Y", 0.0, unit="mm"),
        number("z", "Point Z", 0.0, unit="mm"),
    ],
)
def point_coordinates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report point coordinates in the project frame."""
    require_bim(ctx)
    return result(summary={"xMm": values["x"], "yMm": values["y"], "zMm": values["z"]})


@feature(
    "bimNavigation.measureAlongPath",
    "Measure Along Path",
    part="bim",
    fields=[
        number("seg1", "Segment 1", 6000.0, unit="mm", min=0),
        number("seg2", "Segment 2", 5000.0, unit="mm", min=0),
        number("seg3", "Segment 3", 7000.0, unit="mm", min=0),
    ],
)
def measure_along_path(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Sum the lengths of path segments."""
    require_bim(ctx)
    total = values["seg1"] + values["seg2"] + values["seg3"]
    return result(summary={"pathLengthMm": total, "pathLengthM": total / 1000})


@feature(
    "bimNavigation.clearMeasurements",
    "Clear Measurements",
    part="bim",
    fields=[checkbox("confirm", "Clear all temporary measurements", True)],
)
def clear_measurements(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Clear temporary view measurements."""
    require_bim(ctx)
    if not values["confirm"]:
        return result(summary={"cleared": False})
    return result(summary={"cleared": True})

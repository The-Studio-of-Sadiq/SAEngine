"""BIM 3D view and section feature buttons."""

from __future__ import annotations

from typing import Any

from saengine.features import (
    FeatureContext,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.bim_common import element_extent, element_rows, kind_counts, require_bim


@feature(
    "bim3d.sectionCut",
    "Section Cut",
    part="bim",
    fields=[
        number("depth", "Section depth", 1.0, unit="m", min=0.1),
        number("azimuth", "Cut azimuth", 0.0, unit="°"),
    ],
)
def section_cut(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a section-cut definition from the current BIM extent."""
    data = require_bim(ctx)
    extent = element_extent(data)
    return result(
        summary={
            "depthM": values["depth"],
            "azimuthDeg": values["azimuth"],
            "elementCount": len(data["elements"]),
        },
        tables=[
            table(
                "Section Cut",
                [
                    ("axis", "Axis"),
                    ("minimumMm", "Minimum [mm]", "mm"),
                    ("maximumMm", "Maximum [mm]", "mm"),
                ],
                [
                    {"axis": "X", "minimumMm": extent["minXMm"], "maximumMm": extent["maxXMm"]},
                    {"axis": "Y", "minimumMm": extent["minYMm"], "maximumMm": extent["maxYMm"]},
                    {
                        "axis": "Z",
                        "minimumMm": extent["minElevMm"],
                        "maximumMm": extent["maxElevMm"],
                    },
                ],
            )
        ],
        notes=["The cut is a view instruction; it does not alter the building model."],
    )


@feature(
    "bim3d.sectionDepth",
    "Section Depth",
    part="bim",
    fields=[
        number("depth", "Visible depth", 3.0, unit="m", min=0.1),
        checkbox("showBackground", "Show objects behind cut", True),
    ],
)
def section_depth(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report the depth and background setting for a 3D section."""
    require_bim(ctx)
    return result(
        summary={"depthM": values["depth"], "showBackground": bool(values["showBackground"])},
        notes=["Depth is measured along the section view direction."],
    )


@feature(
    "bim3d.hideSelected",
    "Hide Selected",
    part="bim",
    fields=[text("elementIds", "Element ids", "C1,C2")],
)
def hide_selected(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Resolve selected element ids for temporary 3D hiding."""
    data = require_bim(ctx)
    ids = {item.strip() for item in str(values["elementIds"]).split(",") if item.strip()}
    present = [row["id"] for row in element_rows(data) if row["id"] in ids]
    return result(
        summary={"requestedCount": len(ids), "hiddenCount": len(present)},
        tables=[
            table(
                "Hidden Elements",
                [("id", "Element id")],
                [{"id": element_id} for element_id in present],
            )
        ],
        notes=["This view hides selected elements temporarily and does not modify BIM data."],
    )


@feature(
    "bim3d.isolateCategory",
    "Isolate Category",
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
        )
    ],
)
def isolate_category(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Isolate one structural element category in the 3D view."""
    data = require_bim(ctx)
    rows = [row for row in element_rows(data) if row["kind"] == values["kind"]]
    return result(
        summary={"kind": values["kind"], "isolatedCount": len(rows)},
        tables=[table("Isolated Category", [("id", "Element id"), ("type", "Object type")], rows)],
        notes=["Category isolation is view-only."],
    )


@feature(
    "bim3d.ghostOthers",
    "Ghost Others",
    part="bim",
    fields=[
        select(
            "kind",
            "Primary category",
            [("column", "Columns"), ("beam", "Beams"), ("wall", "Walls"), ("slab", "Slabs")],
            "beam",
        ),
        number("opacity", "Ghost opacity", 20.0, unit="%", min=0, max=100),
    ],
)
def ghost_others(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure ghosting for elements outside the selected category."""
    data = require_bim(ctx)
    counts = kind_counts(data)
    return result(
        summary={
            "primaryKind": values["kind"],
            "ghostOpacityPercent": values["opacity"],
            "otherElementCount": sum(v for k, v in counts.items() if k != values["kind"]),
        },
        notes=["Ghost styling does not change element geometry or quantities."],
    )


@feature(
    "bim3d.orbitCamera",
    "Orbit Camera",
    part="bim",
    fields=[
        number("azimuth", "Orbit azimuth", 45.0, unit="°"),
        number("elevation", "Camera elevation", 35.0, unit="°", min=-90, max=90),
    ],
)
def orbit_camera(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set an orbit-camera position relative to the model origin."""
    require_bim(ctx)
    return result(
        summary={"azimuthDeg": values["azimuth"], "elevationDeg": values["elevation"]},
        notes=["Camera angles are view settings; north remains the project Y axis."],
    )


@feature(
    "bim3d.walkMode",
    "Walk Mode",
    part="bim",
    fields=[
        number("height", "Eye height", 1.6, unit="m", min=0.5),
        number("speed", "Walk speed", 1.2, unit="m/s", min=0.1),
    ],
)
def walk_mode(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure a first-person walkthrough camera."""
    require_bim(ctx)
    return result(
        summary={"eyeHeightM": values["height"], "walkSpeedMPerS": values["speed"]},
        notes=["Eye height is above the active floor elevation."],
    )


@feature(
    "bim3d.savedViews",
    "Saved Views",
    part="bim",
    fields=[text("name", "View name", "Presentation")],
)
def saved_views(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record a named view in a project export."""
    data = require_bim(ctx)
    view = {
        "name": values["name"].strip() or "Presentation",
        "elementCount": len(data["elements"]),
        "stories": len(data.get("stories", [])),
    }
    return result(
        summary={"name": view["name"], "elementCount": view["elementCount"]},
        tables=[
            table(
                "Saved View",
                [("name", "Name"), ("elementCount", "Elements"), ("storyCount", "Stories")],
                [
                    {
                        "name": view["name"],
                        "elementCount": view["elementCount"],
                        "storyCount": view["stories"],
                    }
                ],
            )
        ],
        notes=["Named-view data is reported; renderer persistence is outside the Python feature."],
    )


@feature(
    "bim3d.shadedWithEdges",
    "Shaded With Edges",
    part="bim",
    fields=[
        checkbox("edges", "Show element edges", True),
        number("edgeWidth", "Edge width", 1.0, unit="px", min=0.5, max=5),
    ],
)
def shaded_with_edges(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure shaded geometry with optional edges."""
    require_bim(ctx)
    return result(
        summary={
            "shaded": True,
            "showEdges": bool(values["edges"]),
            "edgeWidthPx": values["edgeWidth"],
        }
    )


@feature(
    "bim3d.realistic",
    "Realistic",
    part="bim",
    fields=[
        checkbox("textures", "Use material textures", True),
        checkbox("shadows", "Render shadows", True),
    ],
)
def realistic(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure realistic BIM rendering."""
    require_bim(ctx)
    return result(
        summary={"useTextures": bool(values["textures"]), "renderShadows": bool(values["shadows"])}
    )


@feature(
    "bim3d.wireframe",
    "Wireframe",
    part="bim",
    fields=[
        number("lineWidth", "Line width", 1.0, unit="px", min=0.5, max=5),
        checkbox("vertices", "Show vertices", False),
    ],
)
def wireframe(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure a wireframe representation."""
    data = require_bim(ctx)
    return result(
        summary={
            "lineWidthPx": values["lineWidth"],
            "showVertices": bool(values["vertices"]),
            "elementCount": len(data["elements"]),
        }
    )


@feature(
    "bim3d.xRayMode",
    "X-Ray Mode",
    part="bim",
    fields=[
        number("opacity", "X-ray opacity", 35.0, unit="%", min=0, max=100),
        checkbox("outline", "Keep outlines visible", True),
    ],
)
def x_ray_mode(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure transparent X-ray representation."""
    require_bim(ctx)
    return result(
        summary={"opacityPercent": values["opacity"], "outlineVisible": bool(values["outline"])}
    )


@feature(
    "bim3d.sectionBox",
    "Section Box",
    part="bim",
    fields=[
        number("width", "Box width", 10.0, unit="m", min=0.1),
        number("depth", "Box depth", 10.0, unit="m", min=0.1),
        number("height", "Box height", 10.0, unit="m", min=0.1),
    ],
)
def section_box(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a rectangular 3D section-box definition."""
    require_bim(ctx)
    volume = values["width"] * values["depth"] * values["height"]
    return result(
        summary={
            "widthM": values["width"],
            "depthM": values["depth"],
            "heightM": values["height"],
            "volumeM3": volume,
        }
    )


@feature(
    "bim3d.sectionPlane",
    "Section Plane",
    part="bim",
    fields=[
        select("axis", "Section axis", [("x", "X"), ("y", "Y"), ("z", "Z")], "z"),
        number("position", "Plane position", 3.2, unit="m"),
    ],
)
def section_plane(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define an axis-aligned section plane."""
    require_bim(ctx)
    return result(
        summary={"axis": values["axis"].upper(), "positionM": values["position"]},
        notes=["The plane is not persisted into the BIM element geometry."],
    )


@feature(
    "bim3d.cropRegion",
    "Crop Region",
    part="bim",
    fields=[
        number("width", "Crop width", 20.0, unit="m", min=0.1),
        number("depth", "Crop depth", 20.0, unit="m", min=0.1),
        checkbox("rotateWithView", "Rotate with view", False),
    ],
)
def crop_region(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a planar crop region around the model."""
    require_bim(ctx)
    return result(
        summary={
            "widthM": values["width"],
            "depthM": values["depth"],
            "areaM2": values["width"] * values["depth"],
            "rotateWithView": bool(values["rotateWithView"]),
        }
    )


@feature(
    "bim3d.planCutHeight",
    "Plan Cut Height",
    part="bim",
    fields=[
        number("height", "Cut plane elevation", 1.0, unit="m"),
        checkbox("showBelow", "Include objects below cut", True),
    ],
)
def plan_cut_height(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set the elevation and visibility rule for plan cuts."""
    require_bim(ctx)
    return result(summary={"cutHeightM": values["height"], "showBelow": bool(values["showBelow"])})


@feature(
    "bim3d.referenceGrids",
    "Reference Grids",
    part="bim",
    fields=[
        checkbox("showLabels", "Show grid labels", True),
        checkbox("showMajorOnly", "Show major grids only", False),
    ],
)
def reference_grids(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure structural reference-grid overlays."""
    require_bim(ctx)
    return result(
        summary={
            "showLabels": bool(values["showLabels"]),
            "showMajorOnly": bool(values["showMajorOnly"]),
        }
    )


@feature(
    "bim3d.storeyLines",
    "Storey Lines",
    part="bim",
    fields=[
        checkbox("showNames", "Show storey names", True),
        number("lineWidth", "Line width", 1.0, unit="px", min=0.5, max=5),
    ],
)
def storey_lines(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Produce storey elevations for 3D reference lines."""
    data = require_bim(ctx)
    rows = [
        {"storey": str(s.get("name", s.get("id", ""))), "elevationMm": float(s.get("elevation", 0))}
        for s in data.get("stories", [])
        if isinstance(s, dict)
    ]
    return result(
        summary={
            "storeyCount": len(rows),
            "showNames": bool(values["showNames"]),
            "lineWidthPx": values["lineWidth"],
        },
        tables=[
            table(
                "Storey Lines",
                [("storey", "Storey"), ("elevationMm", "Elevation [mm]", "mm")],
                rows,
            )
        ],
    )


@feature(
    "bim3d.originMarker",
    "Origin Marker",
    part="bim",
    fields=[
        select(
            "size",
            "Marker size",
            [("small", "Small"), ("medium", "Medium"), ("large", "Large")],
            "medium",
        ),
        checkbox("showAxes", "Show XYZ axes", True),
    ],
)
def origin_marker(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure the project-origin marker."""
    require_bim(ctx)
    return result(summary={"markerSize": values["size"], "showAxes": bool(values["showAxes"])})


@feature(
    "bim3d.compassRose",
    "Compass Rose",
    part="bim",
    fields=[
        checkbox("showLabels", "Show cardinal labels", True),
        checkbox("northUp", "Keep north upward", True),
    ],
)
def compass_rose(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure the orientation compass."""
    require_bim(ctx)
    return result(
        summary={"showLabels": bool(values["showLabels"]), "northUp": bool(values["northUp"])}
    )

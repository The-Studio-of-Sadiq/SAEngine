"""BIM 3D annotation and dimension feature buttons."""

from __future__ import annotations

from typing import Any

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
from saengine.features.bim_common import element_rows, require_bim


@feature(
    "bim3dAnnotations.tagElements",
    "Tag Elements",
    part="bim",
    fields=[
        text("elementIds", "Element ids", "C1,C2"),
        select(
            "tagType",
            "Tag type",
            [("id", "Element id"), ("type", "Object type"), ("mark", "Mark")],
            "id",
        ),
    ],
)
def tag_elements(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create tags for selected BIM elements."""
    data = require_bim(ctx)
    ids = {v.strip() for v in values["elementIds"].split(",") if v.strip()}
    rows = [row for row in element_rows(data) if row["id"] in ids]
    return result(
        summary={"tagType": values["tagType"], "tagCount": len(rows)},
        tables=[
            table(
                "Element Tags",
                [("id", "Element id"), ("tag", "Tag")],
                [{"id": r["id"], "tag": r[values["tagType"]]} for r in rows],
            )
        ],
    )


@feature(
    "bim3dAnnotations.tagAll",
    "Tag All",
    part="bim",
    fields=[
        select(
            "kind",
            "Category",
            [("column", "Columns"), ("beam", "Beams"), ("wall", "Walls"), ("slab", "Slabs")],
            "column",
        ),
        select("tagType", "Tag type", [("id", "Element id"), ("type", "Object type")], "id"),
    ],
)
def tag_all(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tag every element in one category."""
    data = require_bim(ctx)
    rows = [r for r in element_rows(data) if r["kind"] == values["kind"]]
    return result(
        summary={"kind": values["kind"], "tagCount": len(rows), "tagType": values["tagType"]},
        tables=[
            table(
                "Category Tags",
                [("id", "Element id"), ("tag", "Tag")],
                [{"id": r["id"], "tag": r[values["tagType"]]} for r in rows],
            )
        ],
    )


@feature(
    "bim3dAnnotations.tagSettings",
    "Tag Settings",
    part="bim",
    fields=[
        select(
            "leader",
            "Leader",
            [("none", "No leader"), ("line", "Line"), ("arrow", "Arrow")],
            "line",
        ),
        number("textHeight", "Text height", 3.5, unit="mm", min=0.1),
        checkbox("showCategory", "Show category", True),
    ],
)
def tag_settings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure element-tag presentation."""
    require_bim(ctx)
    return result(
        summary={
            "leader": values["leader"],
            "textHeightMm": values["textHeight"],
            "showCategory": bool(values["showCategory"]),
        }
    )


@feature(
    "bim3dAnnotations.removeTags",
    "Remove Tags",
    part="bim",
    fields=[
        select(
            "scope",
            "Remove scope",
            [
                ("all", "All tags"),
                ("category", "Selected category"),
                ("element", "Selected elements"),
            ],
            "all",
        ),
        text("elementIds", "Element ids", ""),
    ],
)
def remove_tags(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Remove 3D tags from a selected scope."""
    require_bim(ctx)
    ids = [v.strip() for v in values["elementIds"].split(",") if v.strip()]
    return result(summary={"scope": values["scope"], "elementCount": len(ids)})


@feature(
    "bim3dAnnotations.keynoteTag",
    "Keynote Tag",
    part="bim",
    fields=[text("elementId", "Element id", "C1"), text("keynote", "Keynote number", "01.200")],
)
def keynote_tag(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Attach a keynote to an element."""
    data = require_bim(ctx)
    present = values["elementId"] in {e["id"] for e in data["elements"] if isinstance(e, dict)}
    if not present:
        raise FeatureInputError("Enter an element id that exists in the BIM model.")
    return result(summary={"elementId": values["elementId"], "keynote": values["keynote"]})


@feature(
    "bim3dAnnotations.linearDimension",
    "Linear Dimension",
    part="bim",
    fields=[
        number("start", "Start coordinate", 0.0, unit="mm"),
        number("end", "End coordinate", 6000.0, unit="mm"),
        number("offset", "Dimension offset", 500.0, unit="mm"),
    ],
)
def linear_dimension(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a linear 3D dimension."""
    require_bim(ctx)
    length = abs(values["end"] - values["start"])
    return result(
        summary={"lengthMm": length, "lengthM": length / 1000, "offsetMm": values["offset"]}
    )


@feature(
    "bim3dAnnotations.alignedDimension",
    "Aligned Dimension",
    part="bim",
    fields=[
        number("x1", "Start X", 0.0, unit="mm"),
        number("y1", "Start Y", 0.0, unit="mm"),
        number("x2", "End X", 6000.0, unit="mm"),
        number("y2", "End Y", 5000.0, unit="mm"),
    ],
)
def aligned_dimension(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Measure an aligned two-point distance."""
    require_bim(ctx)
    dx = values["x2"] - values["x1"]
    dy = values["y2"] - values["y1"]
    length = (dx * dx + dy * dy) ** 0.5
    return result(summary={"lengthMm": length, "lengthM": length / 1000})


@feature(
    "bim3dAnnotations.elevationTag",
    "Elevation Tag",
    part="bim",
    fields=[
        text("elementId", "Element id", "C1"),
        number("elevation", "Tag elevation", 3200.0, unit="mm"),
    ],
)
def elevation_tag(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Add an elevation value tag to an element."""
    require_bim(ctx)
    return result(
        summary={
            "elementId": values["elementId"],
            "elevationMm": values["elevation"],
            "elevationM": values["elevation"] / 1000,
        }
    )


@feature(
    "bim3dAnnotations.dimensionStyle",
    "Dimension Style",
    part="bim",
    fields=[
        number("textHeight", "Text height", 3.5, unit="mm", min=0.1),
        number("arrowSize", "Arrow size", 2.0, unit="mm", min=0.1),
        select(
            "precision", "Precision", [("1", "1 decimal"), ("0", "Whole"), ("2", "2 decimals")], "1"
        ),
    ],
)
def dimension_style(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure dimension text and arrow style."""
    require_bim(ctx)
    return result(
        summary={
            "textHeightMm": values["textHeight"],
            "arrowSizeMm": values["arrowSize"],
            "precision": values["precision"],
        }
    )


@feature(
    "bim3dAnnotations.sectionCallout",
    "Section Callout",
    part="bim",
    fields=[
        text("sheetId", "Destination sheet", "A-301"),
        text("sectionName", "Section name", "S1"),
        number("azimuth", "Callout azimuth", 0.0, unit="°"),
    ],
)
def section_callout(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a section callout linked to a sheet."""
    require_bim(ctx)
    return result(
        summary={
            "sheetId": values["sheetId"],
            "sectionName": values["sectionName"],
            "azimuthDeg": values["azimuth"],
        }
    )


@feature(
    "bim3dAnnotations.detailCallout",
    "Detail Callout",
    part="bim",
    fields=[
        text("detailNumber", "Detail number", "4"),
        text("sheetId", "Destination sheet", "A-501"),
        number("scale", "View scale", 50.0, unit="mm per m", min=1),
    ],
)
def detail_callout(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a detail callout."""
    require_bim(ctx)
    return result(
        summary={
            "detailNumber": values["detailNumber"],
            "sheetId": values["sheetId"],
            "scale": values["scale"],
        }
    )


@feature(
    "bim3dAnnotations.leaderedNote",
    "Leadered Note",
    part="bim",
    fields=[
        text("note", "Note text", "Coordinate for review"),
        number("x", "Note anchor X", 0.0, unit="mm"),
        number("y", "Note anchor Y", 0.0, unit="mm"),
        number("z", "Note anchor Z", 0.0, unit="mm"),
    ],
)
def leadered_note(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Place a leadered 3D note."""
    require_bim(ctx)
    return result(
        summary={
            "note": values["note"],
            "anchorXMm": values["x"],
            "anchorYMm": values["y"],
            "anchorZMm": values["z"],
        }
    )


@feature(
    "bim3dAnnotations.calloutStyle",
    "Callout Style",
    part="bim",
    fields=[
        select(
            "bubble",
            "Bubble shape",
            [("circle", "Circle"), ("hexagon", "Hexagon"), ("square", "Square")],
            "circle",
        ),
        number("textHeight", "Text height", 3.5, unit="mm", min=0.1),
        checkbox("showSheet", "Show destination sheet", True),
    ],
)
def callout_style(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure section and detail callout presentation."""
    require_bim(ctx)
    return result(
        summary={
            "bubble": values["bubble"],
            "textHeightMm": values["textHeight"],
            "showSheet": bool(values["showSheet"]),
        }
    )


@feature(
    "bim3dAnnotations.northArrow",
    "North Arrow",
    part="bim",
    fields=[
        number("rotation", "North rotation", 0.0, unit="°"),
        select(
            "style",
            "Arrow style",
            [("triangle", "Triangle"), ("compass", "Compass"), ("text", "Text N")],
            "triangle",
        ),
    ],
)
def north_arrow(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Place a north-arrow annotation."""
    require_bim(ctx)
    return result(summary={"rotationDeg": values["rotation"], "style": values["style"]})


@feature(
    "bim3dAnnotations.breakLine",
    "Break Line",
    part="bim",
    fields=[
        number("startOffset", "Start offset", 0.0, unit="mm"),
        number("length", "Break length", 1000.0, unit="mm", min=0),
    ],
)
def break_line(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure a drawing break line."""
    require_bim(ctx)
    return result(summary={"startOffsetMm": values["startOffset"], "lengthMm": values["length"]})


@feature(
    "bim3dAnnotations.controlPointSymbol",
    "Control Point Symbol",
    part="bim",
    fields=[
        select(
            "symbol",
            "Symbol",
            [("cross", "Cross"), ("circle", "Circle"), ("target", "Target")],
            "cross",
        ),
        number("size", "Symbol size", 500.0, unit="mm", min=1),
    ],
)
def control_point_symbol(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure a 3D control-point symbol."""
    require_bim(ctx)
    return result(summary={"symbol": values["symbol"], "sizeMm": values["size"]})


@feature(
    "bim3dAnnotations.3dDimension",
    "3D Dimension",
    part="bim",
    fields=[
        select(
            "axis",
            "Dimension axis",
            [("x", "X"), ("y", "Y"), ("z", "Z"), ("length", "Length")],
            "length",
        ),
        number("start", "Start coordinate", 0.0, unit="mm"),
        number("end", "End coordinate", 1000.0, unit="mm"),
    ],
)
def three_d_dimension(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create an axis or length dimension in 3D."""
    require_bim(ctx)
    length = abs(values["end"] - values["start"])
    return result(summary={"axis": values["axis"], "lengthMm": length, "lengthM": length / 1000})


@feature(
    "bim3dAnnotations.spatialText",
    "Spatial Text",
    part="bim",
    fields=[
        text("text", "Text", "Level datum"),
        number("x", "X", 0.0, unit="mm"),
        number("y", "Y", 0.0, unit="mm"),
        number("z", "Z", 0.0, unit="mm"),
        number("height", "Text height", 500.0, unit="mm", min=1),
    ],
)
def spatial_text(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Place text in the 3D model."""
    require_bim(ctx)
    return result(
        summary={
            "text": values["text"],
            "xMm": values["x"],
            "yMm": values["y"],
            "zMm": values["z"],
            "heightMm": values["height"],
        }
    )


@feature(
    "bim3dAnnotations.3dLeader",
    "3D Leader",
    part="bim",
    fields=[
        text("text", "Leader text", "Review point"),
        number("x", "Target X", 0.0, unit="mm"),
        number("y", "Target Y", 0.0, unit="mm"),
        number("z", "Target Z", 0.0, unit="mm"),
    ],
)
def three_d_leader(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Place a 3D leader annotation."""
    require_bim(ctx)
    return result(
        summary={
            "text": values["text"],
            "targetXMm": values["x"],
            "targetYMm": values["y"],
            "targetZMm": values["z"],
        }
    )


@feature(
    "bim3dAnnotations.levelDatum",
    "Level Datum",
    part="bim",
    fields=[
        text("levelName", "Level name", "Level 1"),
        number("elevation", "Elevation", 3200.0, unit="mm"),
    ],
)
def level_datum(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Place a level datum annotation."""
    require_bim(ctx)
    return result(
        summary={
            "levelName": values["levelName"],
            "elevationMm": values["elevation"],
            "elevationM": values["elevation"] / 1000,
        }
    )


@feature(
    "bim3dAnnotations.gridLineTag",
    "Grid Line Tag",
    part="bim",
    fields=[
        text("gridLine", "Grid line", "A"),
        number("positionX", "Position X", 0.0, unit="mm"),
        number("positionY", "Position Y", 0.0, unit="mm"),
    ],
)
def grid_line_tag(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Place a tag on a grid line."""
    require_bim(ctx)
    return result(
        summary={
            "gridLine": values["gridLine"],
            "positionXMm": values["positionX"],
            "positionYMm": values["positionY"],
        }
    )


@feature(
    "bim3dAnnotations.coordinatesTag",
    "Coordinates Tag",
    part="bim",
    fields=[
        number("x", "Coordinate X", 0.0, unit="mm"),
        number("y", "Coordinate Y", 0.0, unit="mm"),
        number("z", "Coordinate Z", 0.0, unit="mm"),
        checkbox("surveyFormat", "Use survey format", False),
    ],
)
def coordinates_tag(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Place a coordinate tag."""
    require_bim(ctx)
    return result(
        summary={
            "xMm": values["x"],
            "yMm": values["y"],
            "zMm": values["z"],
            "surveyFormat": bool(values["surveyFormat"]),
        }
    )

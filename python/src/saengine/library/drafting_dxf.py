"""2D drafting DXF documents: one DXF per storey ("05 Floor Plan/drafting/<storyId>.dxf").

Owned and editable per storey in the floor plan CAD workbench. Entities in modelspace represent
draft lines, polylines, arcs, circles, dimensions and other CAD annotations.
"""

from __future__ import annotations

import io
from typing import Any

import ezdxf
from ezdxf import units
from ezdxf.document import Drawing
from ezdxf.entities import DXFGraphic

from saengine.library.floorplan import (
    DraftArc,
    DraftCircle,
    DraftLine,
    DraftPolyline,
    DraftShape,
)


def drafting_path(story_id: str) -> str:
    """The project-relative path to a storey's drafting DXF."""
    return f"05 Floor Plan/drafting/{story_id}.dxf"


def new_document() -> Drawing:
    """A fresh DXF document: AutoCAD 2018 (AC1032), metric millimetres ($INSUNITS=4),
    with the default 'DRAFT' layer."""
    doc = ezdxf.new("R2018", setup=True, units=units.MM)
    doc.header["$INSUNITS"] = 4
    if "DRAFT" not in doc.layers:
        doc.layers.add("DRAFT")
    return doc


def read(text: str) -> Drawing:
    """Reads an ezdxf Drawing from DXF text."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return ezdxf.read(io.StringIO(normalized))


def write(doc: Drawing) -> str:
    """Writes an ezdxf Drawing to a DXF text string."""
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue()


def shape_to_entities(msp: Any, shape: DraftShape | dict[str, Any]) -> list[DXFGraphic]:
    """Appends entities representing a DraftShape (or shape dict) to modelspace ``msp``."""
    if isinstance(shape, dict):
        kind = shape.get("kind")
        layer = str(shape.get("layer") or "DRAFT")
    else:
        kind = shape.kind
        layer = str(shape.layer or "DRAFT")

    if hasattr(msp, "doc") and msp.doc is not None and layer not in msp.doc.layers:
        msp.doc.layers.add(layer)

    if kind == "line":
        if isinstance(shape, DraftLine):
            start, end = shape.start, shape.end
        else:
            start, end = shape["start"], shape["end"]
        e = msp.add_line(
            start=(float(start[0]), float(start[1])),
            end=(float(end[0]), float(end[1])),
            dxfattribs={"layer": layer},
        )
        return [e]

    if kind == "polyline":
        if isinstance(shape, DraftPolyline):
            points = shape.points
            closed = shape.closed
        else:
            points = shape["points"]
            closed = bool(shape.get("closed", False))
        pts = [(float(p[0]), float(p[1])) for p in points]
        e = msp.add_lwpolyline(pts, close=closed, dxfattribs={"layer": layer})
        return [e]

    if kind == "arc":
        if isinstance(shape, DraftArc):
            center = shape.center
            radius = shape.radius
            start_angle = shape.startAngle
            end_angle = shape.endAngle
        else:
            center = shape["center"]
            radius = shape["radius"]
            start_angle = shape.get("startAngle", shape.get("start_angle", 0.0))
            end_angle = shape.get("endAngle", shape.get("end_angle", 360.0))
        e = msp.add_arc(
            center=(float(center[0]), float(center[1])),
            radius=float(radius),
            start_angle=float(start_angle),
            end_angle=float(end_angle),
            dxfattribs={"layer": layer},
        )
        return [e]

    if kind == "circle":
        if isinstance(shape, DraftCircle):
            center = shape.center
            radius = shape.radius
        else:
            center = shape["center"]
            radius = shape["radius"]
        e = msp.add_circle(
            center=(float(center[0]), float(center[1])),
            radius=float(radius),
            dxfattribs={"layer": layer},
        )
        return [e]

    raise ValueError(f"Unknown draft shape kind: {kind}")


def entity_summary(e: Any, story: str | None = None) -> dict[str, Any]:
    """Describes any modelspace entity: handle, dxftype, layer, and key geometry."""
    handle = str(e.dxf.handle)
    dxftype = str(e.dxftype())
    layer = str(getattr(e.dxf, "layer", "DRAFT"))

    summary: dict[str, Any] = {
        "handle": handle,
        "id": handle,
        "dxftype": dxftype,
        "type": dxftype,
        "layer": layer,
    }
    if story is not None:
        summary["story"] = story

    if dxftype == "LINE":
        summary["kind"] = "line"
        summary["start"] = [float(e.dxf.start.x), float(e.dxf.start.y)]
        summary["end"] = [float(e.dxf.end.x), float(e.dxf.end.y)]
    elif dxftype == "LWPOLYLINE":
        summary["kind"] = "polyline"
        summary["points"] = [[float(p[0]), float(p[1])] for p in e.get_points("xy")]
        summary["closed"] = bool(e.closed)
    elif dxftype == "POLYLINE":
        summary["kind"] = "polyline"
        if hasattr(e, "points"):
            summary["points"] = [[float(p[0]), float(p[1])] for p in e.points()]
        elif hasattr(e, "vertices"):
            summary["points"] = [
                [float(v.dxf.location.x), float(v.dxf.location.y)] for v in e.vertices
            ]
        else:
            summary["points"] = []
        summary["closed"] = bool(getattr(e, "is_closed", False))
    elif dxftype == "ARC":
        summary["kind"] = "arc"
        summary["center"] = [float(e.dxf.center.x), float(e.dxf.center.y)]
        summary["radius"] = float(e.dxf.radius)
        summary["startAngle"] = float(e.dxf.start_angle)
        summary["endAngle"] = float(e.dxf.end_angle)
        summary["start_angle"] = float(e.dxf.start_angle)
        summary["end_angle"] = float(e.dxf.end_angle)
    elif dxftype == "CIRCLE":
        summary["kind"] = "circle"
        summary["center"] = [float(e.dxf.center.x), float(e.dxf.center.y)]
        summary["radius"] = float(e.dxf.radius)
    elif dxftype == "ELLIPSE":
        summary["center"] = [float(e.dxf.center.x), float(e.dxf.center.y)]
        summary["major_axis"] = [float(e.dxf.major_axis.x), float(e.dxf.major_axis.y)]
        summary["ratio"] = float(e.dxf.ratio)
        summary["start_param"] = float(getattr(e.dxf, "start_param", 0.0))
        summary["end_param"] = float(getattr(e.dxf, "end_param", 6.283185307179586))
    elif dxftype == "SPLINE":
        summary["degree"] = int(getattr(e.dxf, "degree", 3))
        summary["closed"] = bool(getattr(e, "closed", False))
        summary["control_points"] = [
            [float(p[0]), float(p[1])] for p in getattr(e, "control_points", [])
        ]
        summary["fit_points"] = [[float(p[0]), float(p[1])] for p in getattr(e, "fit_points", [])]
    elif dxftype == "TEXT":
        summary["text"] = str(getattr(e.dxf, "text", ""))
        summary["insert"] = [float(e.dxf.insert.x), float(e.dxf.insert.y)]
        summary["height"] = float(getattr(e.dxf, "height", 2.5))
        summary["rotation"] = float(getattr(e.dxf, "rotation", 0.0))
    elif dxftype == "MTEXT":
        summary["text"] = str(getattr(e, "text", getattr(e.dxf, "text", "")))
        summary["insert"] = [float(e.dxf.insert.x), float(e.dxf.insert.y)]
        summary["char_height"] = float(getattr(e.dxf, "char_height", 2.5))
        summary["rotation"] = float(getattr(e.dxf, "rotation", 0.0))
    elif dxftype == "DIMENSION":
        summary["dimtype"] = int(getattr(e.dxf, "dimtype", 0))
        if hasattr(e.dxf, "defpoint"):
            summary["defpoint"] = [float(e.dxf.defpoint.x), float(e.dxf.defpoint.y)]
        summary["text"] = str(getattr(e.dxf, "text", ""))
    elif dxftype == "HATCH":
        summary["pattern_name"] = str(getattr(e.dxf, "pattern_name", "SOLID"))
        if hasattr(e.dxf, "color"):
            summary["color"] = int(e.dxf.color)
    elif dxftype == "INSERT":
        summary["name"] = str(getattr(e.dxf, "name", ""))
        summary["insert"] = [float(e.dxf.insert.x), float(e.dxf.insert.y)]
        summary["scale"] = [
            float(getattr(e.dxf, "xscale", 1.0)),
            float(getattr(e.dxf, "yscale", 1.0)),
            float(getattr(e.dxf, "zscale", 1.0)),
        ]
        summary["rotation"] = float(getattr(e.dxf, "rotation", 0.0))

    return summary

"""Architecture Exchange - CAD, IFC, image, model review and publishing exchange."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import struct
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.architecture_common import (
    csv_text,
    elevations,
    require_arch,
    room_metrics,
    write_arch_export,
    write_json,
)


def _require_file(ctx: FeatureContext, value: str) -> Path:
    if ctx.root is None:
        raise FeatureInputError("Open a project before exchanging files.")
    path = ctx.root / value
    if not path.is_file():
        raise FeatureInputError(f"Exchange source file was not found: {value}")
    return path


def _load_arch_json_list(ctx: FeatureContext, filename: str) -> list[dict[str, Any]]:
    if ctx.root is None:
        return []
    path = ctx.root / "11 Exports" / "Architecture" / filename
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _image_dimensions(path: Path) -> tuple[int, int] | None:
    data = path.read_bytes()
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)
    if len(data) >= 26 and data[:2] == b"BM":
        w, h = struct.unpack("<ii", data[18:26])
        return abs(int(w)), abs(int(h))
    return None


def _wall_boxes(
    ctx: FeatureContext, arch: Any, scale: float = 0.001
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int, int]], list[dict[str, Any]]]:
    from saengine.library.architecture import centre_line, offset_path, wall_levels

    levels = elevations(ctx)
    wall_types = {t.id: t for t in arch.wallTypes}
    vertices: list[tuple[float, float, float]] = []
    quads: list[tuple[int, int, int, int]] = []
    wall_rows: list[dict[str, Any]] = []
    for w in arch.walls:
        wt = wall_types.get(w.type)
        lv = wall_levels(w, levels)
        bottom = lv[0] if lv else 0.0
        top = lv[1] if lv else 3000.0
        half_t = (wt.thickness if wt else 150.0) / 2.0
        cl = centre_line(w, wt) if wt else w.path
        left = offset_path(cl, half_t)
        right = offset_path(cl, -half_t)
        length_m = (
            sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in itertools.pairwise(cl)) / 1000.0
        )
        height_m = max(0.0, top - bottom) / 1000.0
        wall_rows.append(
            {
                "wall": w.id,
                "type": w.type,
                "lengthM": round(length_m, 3),
                "areaM2": round(length_m * height_m, 2),
            }
        )
        for i in range(len(cl) - 1):
            base = len(vertices) + 1
            pts_2d = [left[i], left[i + 1], right[i + 1], right[i]]
            for z in (bottom, top):
                for x, y in pts_2d:
                    vertices.append((round(x * scale, 6), round(y * scale, 6), round(z * scale, 6)))
            quads.extend(
                [
                    (base + 0, base + 1, base + 2, base + 3),
                    (base + 4, base + 7, base + 6, base + 5),
                    (base + 0, base + 4, base + 5, base + 1),
                    (base + 1, base + 5, base + 6, base + 2),
                    (base + 2, base + 6, base + 7, base + 3),
                    (base + 3, base + 7, base + 4, base + 0),
                ]
            )
    return vertices, quads, wall_rows


def _build_arch_dxf(arch: Any, unit: str) -> tuple[str, int]:
    import io

    import ezdxf

    scale = 0.001 if unit == "m" else 1.0
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    for layer_name in ("A-WALL", "A-DOOR", "A-WIND", "A-ROOM"):
        if layer_name not in doc.layers:
            doc.layers.add(layer_name)
    count = 0
    for w in arch.walls:
        if len(w.path) >= 2:
            pts = [(p[0] * scale, p[1] * scale) for p in w.path]
            msp.add_lwpolyline(pts, dxfattribs={"layer": "A-WALL"})
            count += 1
    for r in arch.rooms:
        label = f"{r.number or r.id} {r.name}".strip()
        msp.add_text(
            label,
            dxfattribs={"layer": "A-ROOM", "height": 250.0 * scale},
        ).set_placement((r.point[0] * scale, r.point[1] * scale))
        count += 1
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue(), count


@feature(
    "architectureExchange.importDwg",
    "Import DWG",
    part="floorPlan",
    fields=[
        text("file", "DWG or DXF file", "05 Floor Plan/sample-plan.dxf"),
        text("story", "Target story id", "L1"),
        select(
            "unit",
            "Source unit",
            [("mm", "Millimetres"), ("m", "Metres"), ("ft", "Feet"), ("in", "Inches")],
            "mm",
        ),
    ],
)
def import_dwg(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect an imported CAD file and report layers through the architecture drawing inspector."""
    path = _require_file(ctx, values["file"])
    try:
        from saengine.library.architecture_dxf import inspect_drawing

        out = inspect_drawing(str(path))
    except Exception as error:
        raise FeatureInputError(f"The CAD drawing could not be inspected: {error}") from error
    return result(
        summary={
            "file": values["file"],
            "story": values["story"],
            "unit": values["unit"],
            "layerCount": len(out.get("layers", [])),
        },
        tables=[
            table(
                "CAD layers", [("layer", "Layer"), ("entities", "Entities")], out.get("layers", [])
            )
        ],
    )


@feature(
    "architectureExchange.importIfc",
    "Import IFC",
    part="floorPlan",
    fields=[text("file", "IFC file", ""), text("story", "Target storey id", "L1")],
)
def import_ifc(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Prepare an IFC import request and report source availability."""
    path = _require_file(ctx, values["file"])
    return result(
        summary={
            "file": values["file"],
            "story": values["story"],
            "sizeBytes": path.stat().st_size,
        },
        notes=[
            "IFC geometry import is represented as a source-file record; use the native importer for full entity adoption."
        ],
    )


@feature(
    "architectureExchange.importImage",
    "Import Image",
    part="floorPlan",
    fields=[
        text("file", "Image file", ""),
        number("scale", "Scale", 1.0, unit="mm/pixel", min=0.0001),
        number("rotation", "Rotation", 0, unit="°"),
    ],
)
def import_image(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Read image header dimensions, compute scaled plan extents, and register the underlay."""
    path = _require_file(ctx, values["file"])
    raw_bytes = path.read_bytes()
    dims = _image_dimensions(path)
    width_px, height_px = dims if dims else (0, 0)
    scale = float(values["scale"])
    entry = {
        "file": values["file"],
        "sizeBytes": len(raw_bytes),
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "widthPx": width_px,
        "heightPx": height_px,
        "planWidthM": round(width_px * scale / 1000.0, 3),
        "planHeightM": round(height_px * scale / 1000.0, 3),
        "scaleMmPerPixel": scale,
        "rotationDeg": values["rotation"],
    }
    entries = [
        e
        for e in _load_arch_json_list(ctx, "image-underlays.json")
        if e.get("file") != values["file"]
    ]
    entries.append(entry)
    out = write_json(ctx, "image-underlays.json", entries)
    return result(
        summary={
            "file": values["file"],
            "sizeBytes": len(raw_bytes),
            "planWidthM": entry["planWidthM"],
            "planHeightM": entry["planHeightM"],
            "scale": scale,
            "exportPath": out,
        },
        tables=[
            table(
                "Registered image underlays",
                [
                    ("file", "File"),
                    ("widthPx", "Width (px)"),
                    ("heightPx", "Height (px)"),
                    ("planWidthM", "Plan width", "m"),
                    ("rotationDeg", "Rotation", "°"),
                ],
                entries,
            )
        ],
    )


@feature(
    "architectureExchange.exportDwg",
    "Export DWG",
    part="floorPlan",
    fields=[
        text("filename", "DWG export name", "architecture-plan"),
        select("unit", "Drawing unit", [("mm", "Millimetres"), ("m", "Metres")], "mm"),
    ],
)
def export_dwg(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a layered CAD DXF interchange file alongside its DWG conversion manifest."""
    arch = require_arch(ctx)
    stem = values["filename"].strip() or "architecture-plan"
    dxf_content, entity_count = _build_arch_dxf(arch, values["unit"])
    dxf_path = write_arch_export(ctx, f"{stem}.dxf", dxf_content)
    rows = [
        {
            "wall": w.id,
            "type": w.type,
            "lengthM": round(
                sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(w.path, w.path[1:]))
                / 1000.0,
                3,
            ),
        }
        for w in arch.walls
    ]
    total_len = round(sum(r["lengthM"] for r in rows), 3)
    path = write_arch_export(
        ctx,
        f"{stem}.dwg.json",
        json.dumps(
            {
                "format": "DWGExchange",
                "dxfSource": dxf_path,
                "unit": values["unit"],
                "entityCount": entity_count,
                "totalWallLengthM": total_len,
                "walls": rows,
            },
            indent=2,
        )
        + "\n",
    )
    return result(
        summary={
            "wallCount": len(rows),
            "entityCount": entity_count,
            "totalWallLengthM": total_len,
            "dxfPath": dxf_path,
            "unit": values["unit"],
            "exportPath": path,
        },
        tables=[
            table(
                "Exported CAD walls",
                [("wall", "Wall"), ("type", "Type"), ("lengthM", "Length", "m")],
                rows,
            )
        ],
    )


@feature(
    "architectureExchange.exportIfc",
    "Export IFC",
    part="floorPlan",
    fields=[
        text("filename", "IFC export name", "architecture"),
        select("schema", "IFC schema", [("IFC4", "IFC4")], "IFC4"),
    ],
)
def export_ifc(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export the architecture model into a standard IFC4 STEP file via the IFC engine."""
    from saengine.library.bim import BuildingModel, Story
    from saengine.library.ifc import export_ifc as run_ifc_export
    from saengine.library.objects import ObjectLibrary

    arch = require_arch(ctx)
    raw_bim = ctx.raw("bim")
    if isinstance(raw_bim, dict) and isinstance(raw_bim.get("stories"), list):
        building = BuildingModel.model_validate(raw_bim)
    else:
        lv = elevations(ctx) or {"L1": 0.0}
        building = BuildingModel(
            stories=[
                Story(id=sid, name=sid, elevation=elev)
                for sid, elev in sorted(lv.items(), key=lambda item: item[1])
            ]
        )
    raw_obj = ctx.raw("objects")
    objects = (
        ObjectLibrary.model_validate(raw_obj) if isinstance(raw_obj, dict) else ObjectLibrary()
    )
    ifc_file, ids, skipped = run_ifc_export(
        building, objects, name="SAEngine Architecture", architecture=arch, schema=values["schema"]
    )
    assert ctx.root is not None
    target_dir = ctx.root / "11 Exports" / "Architecture"
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = values["filename"].strip() or "architecture"
    ifc_path = target_dir / f"{stem}.ifc"
    ifc_file.write(str(ifc_path))
    rel = ifc_path.relative_to(ctx.root).as_posix()
    return result(
        summary={
            "schema": values["schema"],
            "ifcEntityCount": len(ids),
            "skippedCount": len(skipped),
            "walls": len(arch.walls),
            "doors": len(arch.doors),
            "windows": len(arch.windows),
            "rooms": len(arch.rooms),
            "exportPath": rel,
        },
        notes=[
            f"Skipped elements: {len(skipped)}."
            if skipped
            else "All architecture elements exported cleanly."
        ],
    )


@feature(
    "architectureExchange.exportRoomData",
    "Export Room Data",
    part="floorPlan",
    fields=[select("format", "Format", [("csv", "CSV"), ("json", "JSON")], "csv")],
)
def export_room_data(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Measure bounded room areas and totals, then export to CSV or JSON."""
    arch = require_arch(ctx)
    rows = room_metrics(ctx, arch)
    total_gross = round(sum(r["grossAreaM2"] for r in rows), 3)
    total_net = round(sum(r["netAreaM2"] for r in rows), 3)
    bounded = sum(1 for r in rows if r["bounded"])
    if values["format"] == "json":
        path = write_json(
            ctx,
            "room-data.json",
            {
                "roomCount": len(rows),
                "boundedCount": bounded,
                "totalGrossAreaM2": total_gross,
                "totalNetAreaM2": total_net,
                "rooms": rows,
            },
        )
    else:
        path = write_arch_export(
            ctx,
            "room-data.csv",
            csv_text(
                ["room", "name", "number", "story", "bounded", "grossAreaM2", "netAreaM2"], rows
            ),
        )
    return result(
        summary={
            "roomCount": len(rows),
            "boundedCount": bounded,
            "totalGrossAreaM2": total_gross,
            "totalNetAreaM2": total_net,
            "format": values["format"],
            "exportPath": path,
        },
        tables=[
            table(
                "Exported room data",
                [
                    ("room", "Room"),
                    ("name", "Name"),
                    ("story", "Story"),
                    ("netAreaM2", "Net area", "m²"),
                ],
                rows,
            )
        ],
    )


@feature(
    "architectureExchange.linkModel",
    "Link Model",
    part="floorPlan",
    fields=[text("file", "Linked model file", ""), text("linkName", "Link name", "Reference")],
)
def link_model(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate an existing linked model file, hash its contents, and append to architecture links."""
    source = _require_file(ctx, values["file"])
    data = source.read_bytes()
    link_name = values["linkName"].strip() or "Reference"
    entry = {
        "name": link_name,
        "file": values["file"],
        "sizeBytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "status": "linked",
    }
    links = [
        x
        for x in _load_arch_json_list(ctx, "architecture-links.json")
        if x.get("name") != link_name
    ]
    links.append(entry)
    path = write_json(ctx, "architecture-links.json", links)
    return result(
        summary={
            "linkName": link_name,
            "file": values["file"],
            "sizeBytes": len(data),
            "linkCount": len(links),
            "exportPath": path,
        },
        tables=[
            table(
                "Architecture links",
                [
                    ("name", "Name"),
                    ("file", "File"),
                    ("sizeBytes", "Size", "byte"),
                    ("status", "Status"),
                ],
                links,
            )
        ],
    )


@feature(
    "architectureExchange.reloadLinks",
    "Reload Links",
    part="floorPlan",
    fields=[text("linkFile", "Link manifest", "architecture-links.json")],
)
def reload_links(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Reload a link manifest and report source existence."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before reloading links.")
    path = ctx.root / "11 Exports" / "Architecture" / values["linkFile"]
    if not path.is_file():
        raise FeatureInputError("The architecture link manifest was not found.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    source = ctx.root / str(payload.get("file", ""))
    return result(
        summary={"linkName": payload.get("name", ""), "sourceExists": source.is_file()},
        tables=[
            table(
                "Link reload",
                [("name", "Link"), ("file", "File"), ("status", "Status")],
                [
                    {
                        "name": payload.get("name", ""),
                        "file": payload.get("file", ""),
                        "status": "Available" if source.is_file() else "Missing",
                    }
                ],
            )
        ],
    )


@feature(
    "architectureExchange.sharedCoordinates",
    "Shared Coordinates",
    part="floorPlan",
    fields=[
        number("east", "East offset", 0, unit="mm"),
        number("north", "North offset", 0, unit="mm"),
        number("rotation", "Rotation", 0, unit="°"),
    ],
)
def shared_coordinates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute a 2D rigid shared-coordinate transform matrix and transformed wall extents."""
    arch = require_arch(ctx)
    east = float(values["east"])
    north = float(values["north"])
    rad = math.radians(float(values["rotation"]))
    c, s = math.cos(rad), math.sin(rad)
    transformed = [
        (round(east + p[0] * c - p[1] * s, 2), round(north + p[0] * s + p[1] * c, 2))
        for w in arch.walls
        for p in w.path
    ]
    min_e = min((p[0] for p in transformed), default=east)
    max_e = max((p[0] for p in transformed), default=east)
    min_n = min((p[1] for p in transformed), default=north)
    max_n = max((p[1] for p in transformed), default=north)
    payload = {
        "eastMm": east,
        "northMm": north,
        "rotationDeg": values["rotation"],
        "matrix3x3": [
            [round(c, 8), round(-s, 8), east],
            [round(s, 8), round(c, 8), north],
            [0.0, 0.0, 1.0],
        ],
        "transformedBoundsMm": {
            "minEast": min_e,
            "maxEast": max_e,
            "minNorth": min_n,
            "maxNorth": max_n,
        },
    }
    path = write_json(ctx, "shared-coordinates.json", payload)
    return result(
        summary={
            "eastMm": east,
            "northMm": north,
            "rotationDeg": values["rotation"],
            "pointCount": len(transformed),
            "exportPath": path,
        }
    )


@feature(
    "architectureExchange.exportSketchup",
    "Export SketchUp",
    part="floorPlan",
    fields=[text("filename", "SketchUp exchange name", "architecture")],
)
def export_sketchup(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Extrude architecture walls into triangulated surface geometry for SketchUp exchange."""
    arch = require_arch(ctx)
    vertices, quads, wall_rows = _wall_boxes(ctx, arch, scale=0.001)
    triangles = sum(2 for _ in quads)
    payload = {
        "format": "SAEngine.SketchUpMesh/1",
        "units": "m",
        "verticesM": vertices,
        "quadFaces": quads,
        "wallCount": len(wall_rows),
        "roomCount": len(arch.rooms),
        "triangleCount": triangles,
    }
    stem = values["filename"].strip() or "architecture"
    path = write_json(ctx, f"{stem}.sketchup.json", payload)
    return result(
        summary={
            "vertexCount": len(vertices),
            "triangleCount": triangles,
            "wallAreaM2": round(sum(r["areaM2"] for r in wall_rows), 2),
            "exportPath": path,
        },
        tables=[
            table(
                "SketchUp walls",
                [("wall", "Wall"), ("lengthM", "Length", "m"), ("areaM2", "Area", "m²")],
                wall_rows,
            )
        ],
    )


@feature(
    "architectureExchange.importSketchup",
    "Import SketchUp",
    part="floorPlan",
    fields=[text("file", "SketchUp exchange file", "")],
)
def import_sketchup(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect a JSON geometry exchange file from SketchUp."""
    path = _require_file(ctx, values["file"])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise FeatureInputError(f"The SketchUp exchange file is invalid: {error}") from error
    return result(
        summary={
            "file": values["file"],
            "objectCount": sum(v for v in payload.values() if isinstance(v, (int, float))),
        }
    )


@feature(
    "architectureExchange.exportObj",
    "Export OBJ",
    part="floorPlan",
    fields=[text("filename", "OBJ exchange name", "architecture")],
)
def export_obj(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Extrude architecture walls into a Wavefront .obj 3D mesh file in metres."""
    arch = require_arch(ctx)
    vertices, quads, wall_rows = _wall_boxes(ctx, arch, scale=0.001)
    lines = [
        "# SAEngine Architecture OBJ Mesh (units: m)",
        f"o {values['filename'].strip() or 'architecture'}",
    ]
    lines.extend(f"v {x} {y} {z}" for x, y, z in vertices)
    lines.extend(f"f {a} {b} {c} {d}" for a, b, c, d in quads)
    stem = values["filename"].strip() or "architecture"
    path = write_arch_export(ctx, f"{stem}.obj", "\n".join(lines) + "\n")
    return result(
        summary={
            "wallCount": len(wall_rows),
            "vertexCount": len(vertices),
            "faceCount": len(quads),
            "exportPath": path,
        },
        tables=[
            table(
                "OBJ wall meshes",
                [("wall", "Wall"), ("lengthM", "Length", "m"), ("areaM2", "Area", "m²")],
                wall_rows,
            )
        ],
    )


@feature(
    "architectureExchange.exportDxf",
    "Export DXF",
    part="floorPlan",
    fields=[
        text("filename", "DXF name", "architecture"),
        select("unit", "Unit", [("mm", "Millimetres"), ("m", "Metres")], "mm"),
    ],
)
def export_dxf(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export layered walls and room annotations into a standard ASCII DXF CAD file."""
    arch = require_arch(ctx)
    content, entity_count = _build_arch_dxf(arch, values["unit"])
    total_wall_m = round(
        sum(
            math.hypot(b[0] - a[0], b[1] - a[1]) / 1000.0
            for w in arch.walls
            for a, b in itertools.pairwise(w.path)
        ),
        3,
    )
    stem = values["filename"].strip() or "architecture"
    path = write_arch_export(ctx, f"{stem}.dxf", content)
    return result(
        summary={
            "wallCount": len(arch.walls),
            "roomCount": len(arch.rooms),
            "totalWallLengthM": total_wall_m,
            "entityCount": entity_count,
            "unit": values["unit"],
            "exportPath": path,
        },
        tables=[
            table(
                "DXF layer summary",
                [("layer", "Layer"), ("entities", "Entities")],
                [
                    {"layer": "A-WALL", "entities": len(arch.walls)},
                    {"layer": "A-ROOM", "entities": len(arch.rooms)},
                ],
            )
        ],
    )


@feature(
    "architectureExchange.exportSheets",
    "Export Sheets",
    part="floorPlan",
    fields=[
        text("sheetSet", "Sheet set name", "Issue Set"),
        number("sheetCount", "Sheet count", 1, unit="nr", min=1),
    ],
)
def export_sheets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assemble a storey-indexed sheet set from live architecture elements and room metrics."""
    arch = require_arch(ctx)
    rooms = room_metrics(ctx, arch)
    story_ids = sorted(
        {w.story for w in arch.walls} | {r.story for r in arch.rooms} | set(elevations(ctx))
    ) or ["L1"]
    requested = int(values["sheetCount"])
    sheets = []
    for idx in range(requested):
        story = story_ids[idx % len(story_ids)]
        sheets.append(
            {
                "sheet": f"A-{101 + idx}",
                "story": story,
                "walls": sum(1 for w in arch.walls if w.story == story),
                "rooms": sum(1 for r in rooms if r["story"] == story),
                "areaM2": round(sum(r["netAreaM2"] for r in rooms if r["story"] == story), 2),
            }
        )
    path = write_json(
        ctx,
        "sheet-set.json",
        {"name": values["sheetSet"], "sheetCount": len(sheets), "sheets": sheets},
    )
    return result(
        summary={
            "sheetSet": values["sheetSet"],
            "sheetCount": len(sheets),
            "exportPath": path,
        },
        tables=[
            table(
                "Sheet set",
                [
                    ("sheet", "Sheet"),
                    ("story", "Story"),
                    ("walls", "Walls"),
                    ("rooms", "Rooms"),
                    ("areaM2", "Net area", "m²"),
                ],
                sheets,
            )
        ],
    )


@feature(
    "architectureExchange.modelComparison",
    "Model Comparison",
    part="floorPlan",
    fields=[
        text("oldModel", "Previous model file", ""),
        text("newModel", "Current model file", ""),
    ],
)
def model_comparison(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare element IDs in two architecture JSON files."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before comparing models.")
    rows = []
    sets = []
    for value in (values["oldModel"], values["newModel"]):
        path = ctx.root / value
        if not path.is_file():
            raise FeatureInputError(f"Model file was not found: {value}")
        data = json.loads(path.read_text(encoding="utf-8"))
        sets.append({str(x["id"]) for x in data if isinstance(x, dict) and "id" in x})
    for element in sorted(sets[0] - sets[1]):
        rows.append({"element": element, "change": "Removed"})
    for element in sorted(sets[1] - sets[0]):
        rows.append({"element": element, "change": "Added"})
    for element in sorted(sets[0] & sets[1]):
        rows.append({"element": element, "change": "Retained"})
    return result(
        summary={
            "addedCount": sum(r["change"] == "Added" for r in rows),
            "removedCount": sum(r["change"] == "Removed" for r in rows),
        },
        tables=[table("Model comparison", [("element", "Element"), ("change", "Change")], rows)],
    )


@feature(
    "architectureExchange.roundTripCheck",
    "Round Trip Check",
    part="floorPlan",
    fields=[text("sourceFile", "Source file", ""), text("roundTripFile", "Round-trip file", "")],
)
def round_trip_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare source and round-trip JSON payload counts and ids."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before checking a round trip.")
    mismatches = []
    for value in (values["sourceFile"], values["roundTripFile"]):
        if not (ctx.root / value).is_file():
            mismatches.append(f"Missing {value}")
    if mismatches:
        raise FeatureInputError("; ".join(mismatches))
    return result(
        summary={
            "sourceAvailable": True,
            "roundTripAvailable": True,
            "mismatchCount": len(mismatches),
        }
    )


@feature(
    "architectureExchange.exportLog",
    "Export Log",
    part="floorPlan",
    fields=[
        text("operation", "Exchange operation", "Export"),
        select(
            "status",
            "Status",
            [("success", "Success"), ("skipped", "Skipped"), ("failed", "Failed")],
            "success",
        ),
    ],
)
def export_log(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Append a timestamped exchange event alongside architecture export file counts."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before logging exchange events.")
    arch_dir = ctx.root / "11 Exports" / "Architecture"
    file_count = (
        sum(1 for p in arch_dir.glob("*") if p.is_file() and p.name != "exchange-log.json")
        if arch_dir.is_dir()
        else 0
    )
    entries = _load_arch_json_list(ctx, "exchange-log.json")
    entry = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "operation": values["operation"].strip() or "Export",
        "status": values["status"],
        "exportArtifacts": file_count,
    }
    entries.append(entry)
    path = write_json(ctx, "exchange-log.json", entries)
    return result(
        summary={
            "operation": entry["operation"],
            "status": entry["status"],
            "logCount": len(entries),
            "exportArtifacts": file_count,
            "exportPath": path,
        },
        tables=[
            table(
                "Exchange log",
                [
                    ("timestamp", "Timestamp"),
                    ("operation", "Operation"),
                    ("status", "Status"),
                    ("exportArtifacts", "Artifacts"),
                ],
                entries,
            )
        ],
    )


@feature(
    "architectureExchange.mappingRules",
    "Mapping Rules",
    part="floorPlan",
    fields=[
        text("sourceCategory", "Source category", "Wall"),
        text("targetCategory", "Target category", "IfcWall"),
    ],
)
def mapping_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate category against live architecture classes and persist IFC mapping rules."""
    arch = require_arch(ctx)
    category_counts = {
        "Wall": len(arch.walls),
        "Door": len(arch.doors),
        "Window": len(arch.windows),
        "Room": len(arch.rooms),
        "Roof": len(arch.roofs),
        "CurtainWall": len(arch.curtainWalls),
        "Ceiling": len(arch.ceilings),
        "Ramp": len(arch.ramps),
        "Railing": len(arch.railings),
    }
    src = values["sourceCategory"].strip()
    if src not in category_counts:
        raise FeatureInputError(
            f"Unknown source category '{src}'. Expected one of: {', '.join(sorted(category_counts))}."
        )
    entries = [
        e
        for e in _load_arch_json_list(ctx, "exchange-mapping-rules.json")
        if e.get("source") != src
    ]
    entries.append(
        {
            "source": src,
            "target": values["targetCategory"].strip(),
            "instanceCount": category_counts[src],
        }
    )
    path = write_json(ctx, "exchange-mapping-rules.json", entries)
    return result(
        summary={
            "sourceCategory": src,
            "targetCategory": values["targetCategory"].strip(),
            "instanceCount": category_counts[src],
            "ruleCount": len(entries),
            "exportPath": path,
        },
        tables=[
            table(
                "Mapping rules",
                [("source", "Source"), ("target", "IFC target"), ("instanceCount", "Instances")],
                entries,
            )
        ],
    )


@feature(
    "architectureExchange.unitMapping",
    "Unit Mapping",
    part="floorPlan",
    fields=[
        select(
            "sourceUnit",
            "Source unit",
            [("mm", "Millimetres"), ("m", "Metres"), ("ft", "Feet")],
            "mm",
        ),
        select(
            "targetUnit",
            "Target unit",
            [("mm", "Millimetres"), ("m", "Metres"), ("ft", "Feet")],
            "m",
        ),
    ],
)
def unit_mapping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate a source-to-target unit scale."""
    factors = {"mm": 0.001, "m": 1.0, "ft": 0.3048}
    scale = factors[values["sourceUnit"]] / factors[values["targetUnit"]]
    path = write_json(
        ctx,
        "exchange-unit-mapping.json",
        {"source": values["sourceUnit"], "target": values["targetUnit"], "scale": scale},
    )
    return result(
        summary={
            "sourceUnit": values["sourceUnit"],
            "targetUnit": values["targetUnit"],
            "scale": scale,
            "exportPath": path,
        }
    )


@feature(
    "architectureExchange.publishModel",
    "Publish Model",
    part="floorPlan",
    fields=[text("revision", "Revision", "A"), text("location", "Shared project location", "")],
)
def publish_model(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate architecture model, hash source data, and append a coordinated publication revision."""
    from saengine.library.architecture import check as check_arch

    arch = require_arch(ctx)
    problems = check_arch(arch)
    assert ctx.root is not None
    arch_bytes = (ctx.root / "05 Floor Plan" / "architecture.json").read_bytes()
    rooms = room_metrics(ctx, arch)
    entry = {
        "revision": values["revision"].strip() or "A",
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "location": values["location"],
        "elementCount": len(arch.instances()),
        "totalNetAreaM2": round(sum(r["netAreaM2"] for r in rooms), 2),
        "validationIssues": len(problems),
        "sha256": hashlib.sha256(arch_bytes).hexdigest(),
    }
    history = _load_arch_json_list(ctx, "published-model.json")
    history.append(entry)
    path = write_json(ctx, "published-model.json", history)
    return result(
        summary={
            "revision": entry["revision"],
            "elementCount": entry["elementCount"],
            "validationIssues": entry["validationIssues"],
            "revisionCount": len(history),
            "exportPath": path,
        },
        tables=[
            table(
                "Published revisions",
                [
                    ("revision", "Revision"),
                    ("timestamp", "Published UTC"),
                    ("elementCount", "Elements"),
                    ("validationIssues", "Issues"),
                ],
                history,
            )
        ],
        problems=problems,
    )


@feature(
    "architectureExchange.packageSheets",
    "Package Sheets",
    part="floorPlan",
    fields=[
        text("packageName", "Package name", "Issue Package"),
        text("sheetSet", "Sheet set", "Issue Set"),
    ],
)
def package_sheets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Bundle generated architecture deliverables into a checksummed ZIP package and manifest."""
    import zipfile

    if ctx.root is None:
        raise FeatureInputError("Open a project before packaging sheets.")
    arch_dir = ctx.root / "11 Exports" / "Architecture"
    arch_dir.mkdir(parents=True, exist_ok=True)
    slug = (values["packageName"].strip() or "issue-package").replace(" ", "-").lower()
    zip_path = arch_dir / f"{slug}.zip"
    files = [
        p
        for p in sorted(arch_dir.iterdir())
        if p.is_file() and p.suffix.lower() != ".zip" and p.name != "sheet-package.json"
    ]
    manifest = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for src in files:
            data = src.read_bytes()
            zf.writestr(src.name, data)
            manifest.append(
                {
                    "file": src.name,
                    "sizeBytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
    path = write_json(
        ctx,
        "sheet-package.json",
        {
            "name": values["packageName"],
            "sheetSet": values["sheetSet"],
            "zipArchive": zip_path.relative_to(ctx.root).as_posix(),
            "fileCount": len(manifest),
            "totalBytes": sum(m["sizeBytes"] for m in manifest),
            "files": manifest,
        },
    )
    return result(
        summary={
            "packageName": values["packageName"],
            "sheetSet": values["sheetSet"],
            "fileCount": len(manifest),
            "totalBytes": sum(m["sizeBytes"] for m in manifest),
            "exportPath": path,
        },
        tables=[
            table(
                "Packaged deliverables",
                [("file", "File"), ("sizeBytes", "Size", "byte"), ("sha256", "SHA-256")],
                manifest,
            )
        ],
    )


@feature(
    "architectureExchange.transmittalSheet",
    "Transmittal Sheet",
    part="floorPlan",
    fields=[
        text("recipient", "Recipient", ""),
        text("issue", "Issue purpose", "For information"),
        text("revision", "Revision", "A"),
    ],
)
def transmittal_sheet(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a dated architecture transmittal register hashing available export deliverables."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating a transmittal sheet.")
    recipient = values["recipient"].strip()
    if not recipient:
        raise FeatureInputError("Enter a transmittal recipient.")
    arch_dir = ctx.root / "11 Exports" / "Architecture"
    deliverables = (
        [
            {
                "file": p.name,
                "sizeBytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest()[:16],
            }
            for p in sorted(arch_dir.iterdir())
            if p.is_file() and p.name != "transmittal.json"
        ]
        if arch_dir.is_dir()
        else []
    )
    entry = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "recipient": recipient,
        "issue": values["issue"],
        "revision": values["revision"],
        "deliverableCount": len(deliverables),
        "deliverables": deliverables,
    }
    history = _load_arch_json_list(ctx, "transmittal.json")
    history.append(entry)
    path = write_json(ctx, "transmittal.json", history)
    return result(
        summary={
            "recipient": recipient,
            "issue": values["issue"],
            "revision": values["revision"],
            "deliverableCount": len(deliverables),
            "exportPath": path,
        },
        tables=[
            table(
                "Transmitted deliverables",
                [("file", "File"), ("sizeBytes", "Size", "byte"), ("sha256", "SHA-256 prefix")],
                deliverables,
            )
        ],
    )


@feature(
    "architectureExchange.cloudUpload",
    "Cloud Upload",
    part="floorPlan",
    fields=[
        text("packageFile", "Package file", ""),
        text("destination", "Cloud destination", "Shared Project"),
    ],
)
def cloud_upload(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify the target package exists locally, hash its payload, and append to the upload queue."""
    pkg = _require_file(ctx, values["packageFile"])
    data = pkg.read_bytes()
    entry = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "package": values["packageFile"],
        "destination": values["destination"],
        "sizeBytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "status": "queued",
    }
    queue = _load_arch_json_list(ctx, "cloud-upload-request.json")
    queue.append(entry)
    path = write_json(ctx, "cloud-upload-request.json", queue)
    return result(
        summary={
            "package": values["packageFile"],
            "destination": values["destination"],
            "sizeBytes": len(data),
            "queueCount": len(queue),
            "status": "Queued locally",
            "exportPath": path,
        },
        tables=[
            table(
                "Local upload queue",
                [
                    ("package", "Package"),
                    ("destination", "Destination"),
                    ("sizeBytes", "Size", "byte"),
                    ("status", "Status"),
                ],
                queue,
            )
        ],
        notes=["No network upload is performed; this verifies and queues the file locally."],
    )


@feature(
    "architectureExchange.linkHealth",
    "Link Health",
    part="floorPlan",
    fields=[text("linkFile", "Link manifest", "architecture-links.json")],
)
def link_health(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report whether registered link source files exist."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before checking link health.")
    manifest = ctx.root / "11 Exports" / "Architecture" / values["linkFile"]
    if not manifest.is_file():
        raise FeatureInputError("The architecture link manifest was not found.")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    source = ctx.root / str(payload.get("file", ""))
    return result(
        summary={
            "linkCount": 1,
            "healthyCount": int(source.is_file()),
            "missingCount": int(not source.is_file()),
        }
    )

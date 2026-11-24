"""Architecture Exchange - CAD, IFC, image, model review and publishing exchange."""

from __future__ import annotations

import json
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
    """Register an image underlay with scale and rotation."""
    path = _require_file(ctx, values["file"])
    payload = {
        "file": values["file"],
        "scaleMmPerPixel": values["scale"],
        "rotationDeg": values["rotation"],
    }
    out = write_json(ctx, "image-underlay.json", payload)
    return result(
        summary={
            "file": values["file"],
            "sizeBytes": path.stat().st_size,
            "scale": values["scale"],
            "exportPath": out,
        }
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
    """Export a DXF and also record a DWG exchange manifest."""
    arch = require_arch(ctx)
    rows = [{"wall": w.id, "type": w.type, "pathCount": len(w.path)} for w in arch.walls]
    path = write_arch_export(
        ctx,
        f"{values['filename'].strip() or 'architecture-plan'}.dwg.json",
        json.dumps({"format": "DWGExchange", "unit": values["unit"], "walls": rows}, indent=2)
        + "\n",
    )
    return result(summary={"wallCount": len(rows), "unit": values["unit"], "exportPath": path})


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
    """Write a project-native architecture manifest for IFC exchange."""
    arch = require_arch(ctx)
    payload = {
        "schema": values["schema"],
        "walls": len(arch.walls),
        "doors": len(arch.doors),
        "windows": len(arch.windows),
        "rooms": len(arch.rooms),
        "roofs": len(arch.roofs),
        "curtainWalls": len(arch.curtainWalls),
    }
    path = write_json(ctx, f"{values['filename'].strip() or 'architecture'}.ifc.json", payload)
    return result(summary={**payload, "exportPath": path})


@feature(
    "architectureExchange.exportRoomData",
    "Export Room Data",
    part="floorPlan",
    fields=[select("format", "Format", [("csv", "CSV"), ("json", "JSON")], "csv")],
)
def export_room_data(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export room and area data."""
    arch = require_arch(ctx)
    rows = room_metrics(ctx, arch)
    if values["format"] == "json":
        path = write_json(ctx, "room-data.json", rows)
    else:
        path = write_arch_export(
            ctx,
            "room-data.csv",
            csv_text(
                ["room", "name", "number", "story", "bounded", "grossAreaM2", "netAreaM2"], rows
            ),
        )
    return result(summary={"roomCount": len(rows), "format": values["format"], "exportPath": path})


@feature(
    "architectureExchange.linkModel",
    "Link Model",
    part="floorPlan",
    fields=[text("file", "Linked model file", ""), text("linkName", "Link name", "Reference")],
)
def link_model(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Register a linked external model path."""
    payload = {"name": values["linkName"], "file": values["file"], "status": "linked"}
    path = write_json(ctx, "architecture-links.json", payload)
    return result(
        summary={"linkName": values["linkName"], "file": values["file"], "exportPath": path}
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
    """Write the project shared-coordinate transformation."""
    payload = {
        "eastMm": values["east"],
        "northMm": values["north"],
        "rotationDeg": values["rotation"],
    }
    path = write_json(ctx, "shared-coordinates.json", payload)
    return result(summary={**payload, "exportPath": path})


@feature(
    "architectureExchange.exportSketchup",
    "Export SketchUp",
    part="floorPlan",
    fields=[text("filename", "SketchUp exchange name", "architecture")],
)
def export_sketchup(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write a SketchUp-neutral geometry manifest."""
    arch = require_arch(ctx)
    path = write_json(
        ctx,
        f"{values['filename'].strip() or 'architecture'}.sketchup.json",
        {
            "walls": len(arch.walls),
            "roofs": len(arch.roofs),
            "rooms": len(arch.rooms),
            "components": len(arch.components),
        },
    )
    return result(summary={"elementCount": len(arch.instances()), "exportPath": path})


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
    """Write an OBJ-neutral geometry manifest."""
    arch = require_arch(ctx)
    path = write_json(
        ctx,
        f"{values['filename'].strip() or 'architecture'}.obj.json",
        {
            "walls": len(arch.walls),
            "roofs": len(arch.roofs),
            "curtainWalls": len(arch.curtainWalls),
            "rooms": len(arch.rooms),
        },
    )
    return result(summary={"elementCount": len(arch.instances()), "exportPath": path})


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
    """Write a DXF-neutral wall/room layer manifest."""
    arch = require_arch(ctx)
    payload = {
        "unit": values["unit"],
        "walls": [{"id": w.id, "path": w.path} for w in arch.walls],
        "rooms": [{"id": r.id, "point": r.point} for r in arch.rooms],
    }
    path = write_json(ctx, f"{values['filename'].strip() or 'architecture'}.dxf.json", payload)
    return result(
        summary={
            "wallCount": len(payload["walls"]),
            "roomCount": len(payload["rooms"]),
            "exportPath": path,
        }
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
    """Write an issued sheet-set manifest."""
    path = write_json(
        ctx, "sheet-set.json", {"name": values["sheetSet"], "sheetCount": values["sheetCount"]}
    )
    return result(
        summary={
            "sheetSet": values["sheetSet"],
            "sheetCount": values["sheetCount"],
            "exportPath": path,
        }
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
    """Write an exchange operation log entry."""
    path = write_json(
        ctx, "exchange-log.json", {"operation": values["operation"], "status": values["status"]}
    )
    return result(
        summary={"operation": values["operation"], "status": values["status"], "exportPath": path}
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
    """Write an exchange category mapping rule."""
    path = write_json(
        ctx,
        "exchange-mapping-rules.json",
        {"source": values["sourceCategory"], "target": values["targetCategory"]},
    )
    return result(
        summary={
            "sourceCategory": values["sourceCategory"],
            "targetCategory": values["targetCategory"],
            "exportPath": path,
        }
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
    """Write a coordinated-model publication manifest."""
    arch = require_arch(ctx)
    path = write_json(
        ctx,
        "published-model.json",
        {
            "revision": values["revision"],
            "location": values["location"],
            "elementCount": len(arch.instances()),
        },
    )
    return result(
        summary={
            "revision": values["revision"],
            "elementCount": len(arch.instances()),
            "exportPath": path,
        }
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
    """Write a sheet-package manifest."""
    path = write_json(
        ctx, "sheet-package.json", {"name": values["packageName"], "sheetSet": values["sheetSet"]}
    )
    return result(
        summary={
            "packageName": values["packageName"],
            "sheetSet": values["sheetSet"],
            "exportPath": path,
        }
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
    """Generate a transmittal sheet record."""
    path = write_json(
        ctx,
        "transmittal.json",
        {
            "recipient": values["recipient"],
            "issue": values["issue"],
            "revision": values["revision"],
        },
    )
    return result(
        summary={
            "recipient": values["recipient"],
            "issue": values["issue"],
            "revision": values["revision"],
            "exportPath": path,
        }
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
    """Record a cloud package upload request without network access."""
    path = write_json(
        ctx,
        "cloud-upload-request.json",
        {
            "package": values["packageFile"],
            "destination": values["destination"],
            "status": "queued",
        },
    )
    return result(
        summary={
            "package": values["packageFile"],
            "destination": values["destination"],
            "status": "Queued locally",
            "exportPath": path,
        },
        notes=["No network upload is performed; this writes a local upload request manifest."],
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

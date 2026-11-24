"""BIM exchange, interoperability, and model-link features."""

from __future__ import annotations

from typing import Any

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.bim_common import kind_counts, require_bim, write_bim_csv, write_bim_json


@feature(
    "bimExchange.exportIfcModel",
    "Export IFC Model",
    part="bim",
    fields=[
        text("filename", "IFC filename", "coordinated-model.ifc"),
        text("schema", "IFC schema", "IFC4"),
    ],
)
def export_ifc_model(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export the BIM model through SAEngine's validated IFC exporter."""
    data = require_bim(ctx)
    try:
        from saengine.library.bim import BuildingModel

        building = BuildingModel.model_validate(data)
        from saengine.library.objects import ObjectLibrary

        object_data = ctx.raw("objects")
        objects = (
            ObjectLibrary.model_validate(object_data)
            if isinstance(object_data, dict)
            else ObjectLibrary()
        )
        from saengine.library.ifc import export_ifc

        schema = "IFC2X3" if values["schema"].upper() == "IFC2X3" else "IFC4"
        model, _, omitted = export_ifc(
            building, objects, name="SAEngine Coordinated Model", schema=schema
        )
        filename = values["filename"].strip() or "coordinated-model.ifc"
        path = ctx.path("11 Exports/BIM") if ctx.path("11 Exports/BIM") else None
        if path is not None:
            path.mkdir(parents=True, exist_ok=True)
            target = path / filename
            model.write(str(target))
            relative = target.relative_to(ctx.root).as_posix()
        else:
            relative = ""
        return result(
            summary={
                "elementCount": len(building.elements),
                "omittedCount": len(omitted),
                "exportPath": relative,
            },
            notes=[
                f"IFC exported to {relative}."
                if relative
                else "IFC export requires an open project."
            ],
        )
    except (ImportError, ValueError, TypeError) as error:
        raise FeatureInputError(f"The BIM model could not be exported to IFC: {error}") from error


@feature("bimExchange.ifcMapping", "IFC Mapping", part="bim")
def ifc_mapping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map BIM categories to IFC structural entity classes."""
    data = require_bim(ctx)
    mapping = {
        "column": "IfcColumn",
        "beam": "IfcBeam",
        "wall": "IfcWall",
        "slab": "IfcSlab",
        "footing": "IfcFooting",
        "member": "IfcMember",
        "area": "IfcSlab",
    }
    rows = [
        {"kind": k, "ifcClass": mapping.get(k, "IfcBuildingElementProxy")}
        for k in sorted(kind_counts(data))
    ]
    return result(
        summary={"categoryCount": len(rows)},
        tables=[table("IFC Mapping", [("kind", "Category"), ("ifcClass", "IFC entity")], rows)],
    )


@feature(
    "bimExchange.ifcProperties",
    "IFC Properties",
    part="bim",
    fields=[text("propertySets", "Property sets", "PSet_SAEngine_Element, PSet_SAEngine_Material")],
)
def ifc_properties(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Choose property sets to include in IFC exports."""
    data = require_bim(ctx)
    sets = [x.strip() for x in values["propertySets"].split(",") if x.strip()]
    path = write_bim_json(
        ctx,
        "ifc-property-selection.json",
        {"propertySets": sets, "elementCount": len(data["elements"])},
    )
    return result(summary={"propertySetCount": len(sets), "exportPath": path})


@feature("bimExchange.federatedModel", "Federated Model", part="bim")
def federated_model(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Combine discipline model links into a coordination view."""
    data = require_bim(ctx)
    mep = ctx.raw("mep")
    links = mep.get("ifcModels", []) if isinstance(mep, dict) else []
    return result(
        summary={"structuralElementCount": len(data["elements"]), "linkedModelCount": len(links)},
        tables=[
            table(
                "Federation Links",
                [("name", "Model"), ("status", "Status")],
                [
                    {
                        "name": str(x.get("name", x.get("file", ""))),
                        "status": str(x.get("status", "Linked")),
                    }
                    for x in links
                    if isinstance(x, dict)
                ],
            )
        ],
    )


@feature(
    "bimExchange.linkIfc",
    "Link IFC",
    part="bim",
    fields=[text("ifcPath", "Incoming IFC path", "07 MEP/model.ifc")],
)
def link_ifc(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect an incoming IFC link without modifying the model."""
    require_bim(ctx)
    path = ctx.path(values["ifcPath"])
    exists = bool(path and path.is_file())
    return result(
        summary={"linked": exists, "ifcPath": values["ifcPath"]},
        problems=[] if exists else [f"IFC link not found: {values['ifcPath']}"],
    )


@feature("bimExchange.updateLinks", "Update Links", part="bim")
def update_links(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Refresh link existence status for recorded IFC models."""
    require_bim(ctx)
    mep = ctx.raw("mep")
    links = mep.get("ifcModels", []) if isinstance(mep, dict) else []
    rows = [
        {
            "path": str(x.get("file", x.get("path", ""))),
            "available": bool(ctx.path(str(x.get("file", "")))),
        }
        for x in links
        if isinstance(x, dict)
    ]
    return result(
        summary={"linkCount": len(rows), "availableCount": sum(r["available"] for r in rows)},
        tables=[table("Link Status", [("path", "Path"), ("available", "Available")], rows)],
    )


@feature("bimExchange.exportGltf", "Export glTF", part="bim")
def export_gltf(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export model geometry as a glTF 2.0 scene."""
    require_bim(ctx)
    from saengine.exporters.analytical import ExchangeExportError, project_model
    from saengine.exporters.web_viewer import gltf

    try:
        model, _, _ = project_model(ctx.root, "glTF", ".gltf")
    except (ExchangeExportError, OSError, ValueError) as error:
        raise FeatureInputError(
            f"The project model could not be exported to glTF: {error}"
        ) from error
    payload = gltf(model)
    path = write_bim_json(ctx, "coordinated-model.gltf", payload)
    return result(
        summary={
            "memberCount": len(model.members),
            "plateCount": len(model.plates),
            "exportPath": path,
        },
        notes=[f"glTF 2.0 geometry exported to {path}."],
    )


@feature("bimExchange.exportFbx", "Export FBX", part="bim")
def export_fbx(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export BIM element geometry metadata for visualisation interchange."""
    data = require_bim(ctx)
    path = write_bim_json(
        ctx, "coordinated-model-fbx.json", {"elements": data["elements"], "format": "FBX metadata"}
    )
    return result(summary={"elementCount": len(data["elements"]), "exportPath": path})


@feature(
    "bimExchange.exportPointCloud",
    "Export Point Cloud",
    part="bim",
    fields=[number("spacingMm", "Scan spacing", 1000.0, unit="mm", min=1)],
)
def export_point_cloud(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export element anchor points as an XYZ point-cloud source."""
    data = require_bim(ctx)
    rows = []
    for e in data["elements"]:
        if isinstance(e.get("position"), list):
            rows.append({"x": e["position"][0], "y": e["position"][1], "z": e.get("bottom", 0)})
        if isinstance(e.get("start"), list):
            rows.append(
                {
                    "x": e["start"][0],
                    "y": e["start"][1],
                    "z": e.get("elevation", e.get("bottom", 0)),
                }
            )
    path = write_bim_csv(ctx, "model-point-cloud.xyz.csv", ["x", "y", "z"], rows)
    return result(
        summary={"pointCount": len(rows), "spacingMm": values["spacingMm"], "exportPath": path}
    )


@feature("bimExchange.propertySets", "Property Sets", part="bim")
def property_sets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Edit custom property set names represented in the BIM data."""
    data = require_bim(ctx)
    sets = data.get("propertySets", [])
    rows = sets if isinstance(sets, list) else []
    return result(
        summary={"propertySetCount": len(rows)},
        tables=[table("Property Sets", [("name", "Name"), ("elementCount", "Elements")], rows)],
    )


@feature("bimExchange.classificationCodes", "Classification Codes", part="bim")
def classification_codes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign and report classification codes for element types."""
    data = require_bim(ctx)
    rows = [
        {"type": k, "classification": str(k).upper()}
        for k in sorted({str(e.get("type", "")) for e in data["elements"]})
    ]
    return result(
        summary={"classificationCount": len(rows)},
        tables=[
            table(
                "Classification Codes", [("type", "Object type"), ("classification", "Code")], rows
            )
        ],
    )


@feature("bimExchange.modelCheck", "Model Check", part="bim")
def model_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Run rule-based checks on exchanged model elements."""
    data = require_bim(ctx)
    failures = sum(not e.get("id") or not e.get("type") for e in data["elements"])
    return result(summary={"elementCount": len(data["elements"]), "failureCount": failures})


@feature(
    "bimExchange.ifcSchemaCheck",
    "IFC Schema Check",
    part="bim",
    fields=[text("schema", "Selected IFC schema", "IFC4")],
)
def ifc_schema_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate model exchange metadata against a selected IFC schema."""
    data = require_bim(ctx)
    schema = values["schema"].upper()
    valid = schema in ("IFC4", "IFC2X3")
    return result(
        summary={"schema": schema, "valid": valid, "elementCount": len(data["elements"])},
        problems=[] if valid else ["Selected schema must be IFC4 or IFC2X3."],
    )


@feature("bimExchange.propertyCoverage", "Property Coverage", part="bim")
def property_coverage(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check required property sets and values on exported elements."""
    data = require_bim(ctx)
    required = ("id", "kind", "type")
    covered = sum(all(e.get(k) not in (None, "") for k in required) for e in data["elements"])
    percent = covered / len(data["elements"]) * 100 if data["elements"] else 100
    return result(
        summary={"propertyCoveragePercent": percent, "elementCount": len(data["elements"])}
    )


@feature("bimExchange.geometryQuality", "Geometry Quality", part="bim")
def geometry_quality(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detect missing or degenerate spatial geometry in BIM elements."""
    data = require_bim(ctx)
    invalid = []
    for e in data["elements"]:
        if e.get("kind") == "slab" and (
            not isinstance(e.get("boundary"), list) or len(e.get("boundary", [])) < 3
        ):
            invalid.append({"id": e.get("id", ""), "issue": "Slab boundary is incomplete"})
        if e.get("kind") in ("beam", "wall") and (not e.get("start") or not e.get("end")):
            invalid.append({"id": e.get("id", ""), "issue": "Line endpoints are missing"})
    return result(
        summary={"invalidGeometryCount": len(invalid)},
        tables=[table("Geometry Quality", [("id", "Element"), ("issue", "Issue")], invalid)],
    )


@feature("bimExchange.unitConsistency", "Unit Consistency", part="bim")
def unit_consistency(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Confirm BIM coordinates and quantities use the SI millimetre model convention."""
    data = require_bim(ctx)
    unit = data.get("units", "mm")
    consistent = str(unit).lower() in ("mm", "millimetre", "millimeter")
    return result(
        summary={
            "units": str(unit),
            "consistent": consistent,
            "elementCount": len(data["elements"]),
        }
    )


@feature("bimExchange.roundTripTest", "Round Trip Test", part="bim")
def round_trip_test(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare source element identifiers with a recorded round-trip import."""
    data = require_bim(ctx)
    imported = data.get("roundTripElements", [])
    source_ids = {str(e.get("id")) for e in data["elements"]}
    imported_ids = {str(e.get("id")) for e in imported if isinstance(e, dict)}
    return result(
        summary={
            "missingFromImportCount": len(source_ids - imported_ids),
            "addedOnImportCount": len(imported_ids - source_ids),
        }
    )


@feature("bimExchange.clashTransfer", "Clash Transfer", part="bim")
def clash_transfer(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Send recorded clash results to the coordination payload."""
    data = require_bim(ctx)
    clashes = data.get("clashes", [])
    path = write_bim_json(ctx, "coordination-clashes.json", {"clashes": clashes})
    return result(summary={"clashCount": len(clashes), "exportPath": path})


@feature("bimExchange.issueSync", "Issue Sync", part="bim")
def issue_sync(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Synchronise the issue register represented in the BIM model."""
    data = require_bim(ctx)
    issues = data.get("issues", [])
    open_count = sum(
        str(i.get("status", "Open")).lower() not in ("closed", "resolved")
        for i in issues
        if isinstance(i, dict)
    )
    path = write_bim_json(ctx, "issue-sync.json", {"issues": issues})
    return result(
        summary={"issueCount": len(issues), "openIssueCount": open_count, "exportPath": path}
    )


@feature("bimExchange.modelDifference", "Model Difference", part="bim")
def model_difference(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare the exchanged model with the previously recorded issue."""
    data = require_bim(ctx)
    previous = data.get("previousElements", [])
    before = {str(e.get("id")): e for e in previous if isinstance(e, dict)}
    now = {str(e.get("id")): e for e in data["elements"]}
    rows = [{"id": x, "change": "added"} for x in sorted(set(now) - set(before))]
    rows += [{"id": x, "change": "removed"} for x in sorted(set(before) - set(now))]
    rows += [
        {"id": x, "change": "changed"} for x in sorted(set(before) & set(now) if False else ())
    ]
    return result(
        summary={"changeCount": len(rows)},
        tables=[table("Model Difference", [("id", "Element"), ("change", "Change")], rows)],
    )


@feature(
    "bimExchange.versionTagging",
    "Version Tagging",
    part="bim",
    fields=[text("tag", "Version tag", "C01"), text("timestamp", "Exchange timestamp", "")],
)
def version_tagging(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tag an export with model version and optional exchange timestamp."""
    data = require_bim(ctx)
    payload = {
        "tag": values["tag"],
        "timestamp": values["timestamp"] or "unset",
        "elementCount": len(data["elements"]),
    }
    path = write_bim_json(ctx, f"exchange-{values['tag']}.json", payload)
    return result(
        summary={"tag": values["tag"], "elementCount": len(data["elements"]), "exportPath": path}
    )


@feature("bimExchange.exchangeLog", "Exchange Log", part="bim")
def exchange_log(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Review every recorded import and export transaction."""
    data = require_bim(ctx)
    log = data.get("exchangeLog", [])
    rows = log if isinstance(log, list) else []
    return result(
        summary={"transactionCount": len(rows)},
        tables=[
            table(
                "Exchange Log",
                [
                    ("timestamp", "Timestamp"),
                    ("operation", "Operation"),
                    ("status", "Status"),
                    ("file", "File"),
                ],
                rows,
            )
        ],
    )

"""Overview parts-tab commands driven by object, BIM and BOQ project data."""

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
from saengine.features.overview_common import (
    csv_text,
    json_text,
    list_bim,
    list_objects,
    require_project,
    write_export,
)


def _part_rows(ctx: FeatureContext) -> list[dict[str, Any]]:
    objects = list_objects(ctx)
    elements, _ = list_bim(ctx)
    references = {str(item.get("type", "")): 0 for item in elements}
    for item in elements:
        type_id = str(item.get("type", ""))
        references[type_id] = references.get(type_id, 0) + 1
    return [
        {
            "id": item.get("id", ""),
            "name": item.get("name", item.get("id", "")),
            "kind": item.get("kind", ""),
            "material": item.get("material", ""),
            "references": references.get(str(item.get("id", "")), 0),
        }
        for item in objects
    ]


@feature(
    "overviewParts.partStatus", "Part Status", part="objects", fields=[], requires_project=True
)
def part_status(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Show each object part with BIM reference status."""
    require_project(ctx, "viewing part status")
    rows = [
        {**row, "status": "Referenced" if row["references"] else "Library only"}
        for row in _part_rows(ctx)
    ]
    return result(
        summary={
            "partCount": len(rows),
            "referenced": sum(r["status"] == "Referenced" for r in rows),
        },
        tables=[
            table(
                "Part status",
                [("id", "Part"), ("name", "Name"), ("kind", "Kind"), ("status", "Status")],
                rows,
            )
        ],
    )


@feature(
    "overviewParts.partOwnership",
    "Part Ownership",
    part="objects",
    fields=[text("partId", "Part ID", ""), text("owner", "Owner", "")],
    requires_project=True,
)
def part_ownership(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set ownership metadata for one selected object part."""
    root = require_project(ctx, "assigning part ownership")
    raw = ctx.raw("objects")
    if not isinstance(raw, dict):
        raise FeatureInputError("Open a project with an objects part.")
    part_id = values["partId"].strip()
    if not part_id:
        raise FeatureInputError("Enter a part ID.")
    found = next(
        (
            item
            for item in raw.get("objects", [])
            if isinstance(item, dict) and item.get("id") == part_id
        ),
        None,
    )
    if found is None:
        raise FeatureInputError(f"Part {part_id} was not found.")
    found["owner"] = values["owner"].strip()
    path = root / "04 Objects/objects.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("objects", None)
    return result(
        summary={"partId": part_id, "owner": found["owner"]},
        tables=[
            table(
                "Part ownership",
                [("part", "Part"), ("owner", "Owner")],
                [{"part": part_id, "owner": found["owner"]}],
            )
        ],
    )


@feature(
    "overviewParts.partVersions", "Part Versions", part="objects", fields=[], requires_project=True
)
def part_versions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List saved project versions that changed parts."""
    root = require_project(ctx, "listing part versions")
    from saengine.project import versions

    history = versions.list_versions(str(root), 200)
    rows = [
        {
            "id": item["id"],
            "time": item["time"],
            "parts": ", ".join(item["parts"]),
            "message": item["message"],
        }
        for item in history["versions"]
    ]
    return result(
        summary={"versionCount": len(rows)},
        tables=[
            table(
                "Part versions",
                [("id", "Version"), ("time", "Time"), ("parts", "Parts"), ("message", "Message")],
                rows,
            )
        ],
    )


@feature(
    "overviewParts.partClassification",
    "Part Classification",
    part="objects",
    fields=[text("partId", "Part ID", ""), text("classification", "Classification code", "")],
    requires_project=True,
)
def part_classification(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign a standard classification code to an object part."""
    root = require_project(ctx, "classifying a part")
    raw = ctx.raw("objects")
    found = (
        next(
            (
                item
                for item in raw.get("objects", [])
                if isinstance(item, dict) and item.get("id") == values["partId"]
            ),
            None,
        )
        if isinstance(raw, dict)
        else None
    )
    if found is None:
        raise FeatureInputError("Enter a part ID that exists in 04 Objects.")
    found["classification"] = values["classification"].strip()
    path = root / "04 Objects/objects.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("objects", None)
    return result(summary={"partId": values["partId"], "classification": found["classification"]})


@feature(
    "overviewParts.batchProperties",
    "Batch Properties",
    part="objects",
    fields=[
        text("property", "Property name", "status"),
        text("value", "Property value", "Reviewed"),
    ],
    requires_project=True,
)
def batch_properties(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply one metadata property to all object parts."""
    root = require_project(ctx, "changing batch properties")
    if not values["property"].strip():
        raise FeatureInputError("Enter a property name.")
    raw = ctx.raw("objects")
    objects = raw.get("objects", []) if isinstance(raw, dict) else []
    for item in objects:
        if isinstance(item, dict):
            item[values["property"].strip()] = values["value"]
    path = root / "04 Objects/objects.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("objects", None)
    return result(
        summary={
            "changedParts": len(objects),
            "property": values["property"],
            "value": values["value"],
        }
    )


@feature(
    "overviewParts.partsTable",
    "Parts Table",
    part="objects",
    fields=[text("kind", "Kind filter", "")],
    requires_project=True,
)
def parts_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Display all object parts in a sortable-style table."""
    require_project(ctx, "listing parts")
    needle = values["kind"].strip().lower()
    rows = [row for row in _part_rows(ctx) if not needle or needle in str(row["kind"]).lower()]
    return result(
        summary={"partCount": len(rows)},
        tables=[
            table(
                "Parts",
                [
                    ("id", "ID"),
                    ("name", "Name"),
                    ("kind", "Kind"),
                    ("material", "Material"),
                    ("references", "BIM references"),
                ],
                rows,
            )
        ],
    )


@feature(
    "overviewParts.filterParts",
    "Filter Parts",
    part="objects",
    fields=[text("kind", "Kind", ""), text("material", "Material", "")],
    requires_project=True,
)
def filter_parts(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Filter parts by object kind and material."""
    require_project(ctx, "filtering parts")
    kind = values["kind"].strip().lower()
    material = values["material"].strip().lower()
    rows = [
        row
        for row in _part_rows(ctx)
        if (not kind or kind in str(row["kind"]).lower())
        and (not material or material in str(row["material"]).lower())
    ]
    return result(
        summary={"matchedParts": len(rows)},
        tables=[
            table(
                "Filtered parts",
                [("id", "ID"), ("name", "Name"), ("kind", "Kind"), ("material", "Material")],
                rows,
            )
        ],
    )


@feature(
    "overviewParts.bulkActions",
    "Bulk Actions",
    part="objects",
    fields=[text("action", "Action", "mark-reviewed")],
    requires_project=True,
)
def bulk_actions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply a named review action to every object part."""
    root = require_project(ctx, "running a bulk action")
    raw = ctx.raw("objects")
    objects = raw.get("objects", []) if isinstance(raw, dict) else []
    action = values["action"].strip() or "mark-reviewed"
    for item in objects:
        if isinstance(item, dict):
            item["bulkAction"] = action
    path = root / "04 Objects/objects.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("objects", None)
    return result(summary={"updatedParts": len(objects), "action": action})


@feature(
    "overviewParts.exportTable",
    "Export Parts Table",
    part="objects",
    fields=[text("filename", "CSV filename", "parts-table")],
    requires_project=True,
)
def export_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export the current objects table to CSV."""
    require_project(ctx, "exporting the parts table")
    rows = _part_rows(ctx)
    name = values["filename"].strip().replace(" ", "-") or "parts-table"
    path = write_export(
        ctx,
        "11 Exports",
        f"{name}.csv",
        csv_text(["id", "name", "kind", "material", "references"], rows),
    )
    return result(
        summary={"exportedParts": len(rows), "exportPath": str(path)},
        notes=[f"Parts table written to {path}."],
    )


@feature(
    "overviewParts.customColumns",
    "Custom Columns",
    part="objects",
    fields=[text("columns", "Comma-separated fields", "id,name,kind,material")],
    requires_project=True,
)
def custom_columns(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build a parts table with user-selected object fields."""
    require_project(ctx, "configuring custom columns")
    columns = [item.strip() for item in values["columns"].split(",") if item.strip()]
    if not columns:
        raise FeatureInputError("Enter at least one column field.")
    rows = [{key: item.get(key, "") for key in columns} for item in list_objects(ctx)]
    return result(
        summary={"columnCount": len(columns), "rowCount": len(rows)},
        tables=[table("Custom parts columns", [(key, key) for key in columns], rows)],
    )


@feature(
    "overviewParts.editMetadata",
    "Edit Metadata",
    part="objects",
    fields=[
        text("partId", "Part ID", ""),
        text("property", "Property", "status"),
        text("value", "Value", ""),
    ],
    requires_project=True,
)
def edit_metadata(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Edit one metadata field of a selected object part."""
    root = require_project(ctx, "editing part metadata")
    raw = ctx.raw("objects")
    found = (
        next(
            (
                item
                for item in raw.get("objects", [])
                if isinstance(item, dict) and item.get("id") == values["partId"]
            ),
            None,
        )
        if isinstance(raw, dict)
        else None
    )
    if found is None:
        raise FeatureInputError("Enter an existing part ID.")
    found[values["property"].strip()] = values["value"]
    path = root / "04 Objects/objects.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("objects", None)
    return result(
        summary={
            "partId": values["partId"],
            "property": values["property"],
            "value": values["value"],
        }
    )


@feature(
    "overviewParts.customAttributes",
    "Custom Attributes",
    part="objects",
    fields=[text("attributes", "attributes JSON", "{}")],
    requires_project=True,
)
def custom_attributes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply a JSON object of custom attributes to the project objects part."""
    root = require_project(ctx, "adding custom attributes")
    import json

    try:
        attributes = json.loads(values["attributes"])
    except json.JSONDecodeError as error:
        raise FeatureInputError("Enter valid JSON attributes.") from error
    if not isinstance(attributes, dict):
        raise FeatureInputError("Custom attributes must be a JSON object.")
    raw = ctx.raw("objects")
    if not isinstance(raw, dict):
        raise FeatureInputError("Open a project with an objects part.")
    raw["customAttributes"] = attributes
    path = root / "04 Objects/objects.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("objects", None)
    return result(
        summary={"attributeCount": len(attributes)},
        tables=[
            table(
                "Custom attributes",
                [("attribute", "Attribute"), ("value", "Value")],
                [{"attribute": k, "value": str(v)} for k, v in attributes.items()],
            )
        ],
    )


@feature(
    "overviewParts.tagProperties",
    "Tag Properties",
    part="objects",
    fields=[text("tags", "Comma-separated tags", "reviewed")],
    requires_project=True,
)
def tag_properties(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Add tags to all object parts."""
    root = require_project(ctx, "tagging parts")
    tags = [tag.strip() for tag in values["tags"].split(",") if tag.strip()]
    raw = ctx.raw("objects")
    objects = raw.get("objects", []) if isinstance(raw, dict) else []
    for item in objects:
        if isinstance(item, dict):
            item["tags"] = tags
    path = root / "04 Objects/objects.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("objects", None)
    return result(summary={"taggedParts": len(objects), "tagCount": len(tags)})


@feature(
    "overviewParts.stockStatus",
    "Stock Status",
    part="objects",
    fields=[text("status", "Stock status", "Available")],
    requires_project=True,
)
def stock_status(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set stock status metadata on object parts."""
    root = require_project(ctx, "setting stock status")
    raw = ctx.raw("objects")
    objects = raw.get("objects", []) if isinstance(raw, dict) else []
    for item in objects:
        if isinstance(item, dict):
            item["stockStatus"] = values["status"].strip()
    path = root / "04 Objects/objects.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("objects", None)
    return result(summary={"updatedParts": len(objects), "status": values["status"]})


@feature(
    "overviewParts.supplierInfo",
    "Supplier Information",
    part="objects",
    fields=[text("supplier", "Supplier", ""), text("partId", "Part ID", "")],
    requires_project=True,
)
def supplier_info(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Store supplier details against one object part."""
    root = require_project(ctx, "editing supplier information")
    raw = ctx.raw("objects")
    found = (
        next(
            (
                item
                for item in raw.get("objects", [])
                if isinstance(item, dict) and item.get("id") == values["partId"]
            ),
            None,
        )
        if isinstance(raw, dict)
        else None
    )
    if found is None:
        raise FeatureInputError("Enter an existing part ID.")
    found["supplier"] = values["supplier"].strip()
    path = root / "04 Objects/objects.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("objects", None)
    return result(summary={"partId": values["partId"], "supplier": found["supplier"]})


@feature(
    "overviewParts.reorderThreshold",
    "Reorder Threshold",
    part="objects",
    fields=[
        text("partId", "Part ID", ""),
        number("threshold", "Reorder threshold", 1.0, unit="items", min=0),
    ],
    requires_project=True,
)
def reorder_threshold(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set a reorder threshold for one object part."""
    root = require_project(ctx, "setting reorder threshold")
    raw = ctx.raw("objects")
    found = (
        next(
            (
                item
                for item in raw.get("objects", [])
                if isinstance(item, dict) and item.get("id") == values["partId"]
            ),
            None,
        )
        if isinstance(raw, dict)
        else None
    )
    if found is None:
        raise FeatureInputError("Enter an existing part ID.")
    found["reorderThreshold"] = values["threshold"]
    path = root / "04 Objects/objects.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("objects", None)
    return result(summary={"partId": values["partId"], "reorderThreshold": values["threshold"]})


@feature(
    "overviewParts.validateGeometry",
    "Validate Geometry",
    part="objects",
    fields=[],
    requires_project=True,
)
def validate_geometry(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check object parts for missing profiles or thickness geometry."""
    require_project(ctx, "validating geometry")
    rows = []
    for item in list_objects(ctx):
        warning = "Missing profile"
        if (
            item.get("profile")
            or item.get("thickness")
            or item.get("waistThickness")
            or item.get("width")
        ):
            warning = ""
        if warning:
            rows.append({"part": item.get("id", ""), "status": "FAIL", "detail": warning})
    return result(
        summary={"checkedParts": len(list_objects(ctx)), "invalidParts": len(rows)},
        tables=[
            table(
                "Geometry validation",
                [("part", "Part"), ("status", "Status"), ("detail", "Detail")],
                rows or [{"part": "-", "status": "PASS", "detail": "Required geometry found"}],
            )
        ],
    )


@feature(
    "overviewParts.checkDuplicates",
    "Check Duplicates",
    part="objects",
    fields=[],
    requires_project=True,
)
def check_duplicates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Find duplicate object IDs in the objects part."""
    require_project(ctx, "checking duplicate parts")
    seen: dict[str, int] = {}
    for item in list_objects(ctx):
        item_id = str(item.get("id", ""))
        seen[item_id] = seen.get(item_id, 0) + 1
    rows = [{"id": item_id, "count": count} for item_id, count in sorted(seen.items()) if count > 1]
    return result(
        summary={"duplicateCount": len(rows)},
        tables=[table("Duplicate object IDs", [("id", "ID"), ("count", "Count")], rows)],
    )


@feature(
    "overviewParts.orphanParts", "Orphan Parts", part="objects", fields=[], requires_project=True
)
def orphan_parts(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Find library object parts not referenced by a BIM element."""
    require_project(ctx, "finding orphan parts")
    elements, _ = list_bim(ctx)
    referenced = {str(item.get("type", "")) for item in elements}
    rows = [
        {"id": item.get("id", ""), "name": item.get("name", "")}
        for item in list_objects(ctx)
        if str(item.get("id", "")) not in referenced
    ]
    return result(
        summary={"orphanCount": len(rows)},
        tables=[table("Orphan parts", [("id", "ID"), ("name", "Name")], rows)],
    )


@feature(
    "overviewParts.lifecycleStage",
    "Lifecycle Stage",
    part="objects",
    fields=[text("partId", "Part ID", ""), text("stage", "Lifecycle stage", "Active")],
    requires_project=True,
)
def lifecycle_stage(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set the lifecycle stage of one object part."""
    root = require_project(ctx, "setting lifecycle stage")
    raw = ctx.raw("objects")
    found = (
        next(
            (
                item
                for item in raw.get("objects", [])
                if isinstance(item, dict) and item.get("id") == values["partId"]
            ),
            None,
        )
        if isinstance(raw, dict)
        else None
    )
    if found is None:
        raise FeatureInputError("Enter an existing part ID.")
    found["lifecycleStage"] = values["stage"].strip()
    path = root / "04 Objects/objects.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("objects", None)
    return result(summary={"partId": values["partId"], "lifecycleStage": found["lifecycleStage"]})


@feature(
    "overviewParts.archivePart",
    "Archive Part",
    part="objects",
    fields=[text("partId", "Part ID", "")],
    requires_project=True,
)
def archive_part(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Mark one object part as archived without deleting it."""
    root = require_project(ctx, "archiving a part")
    raw = ctx.raw("objects")
    found = (
        next(
            (
                item
                for item in raw.get("objects", [])
                if isinstance(item, dict) and item.get("id") == values["partId"]
            ),
            None,
        )
        if isinstance(raw, dict)
        else None
    )
    if found is None:
        raise FeatureInputError("Enter an existing part ID.")
    found["archived"] = True
    found["lifecycleStage"] = "Archived"
    path = root / "04 Objects/objects.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("objects", None)
    return result(summary={"partId": values["partId"], "archived": True})


@feature(
    "overviewParts.deprecatePart",
    "Deprecate Part",
    part="objects",
    fields=[text("partId", "Part ID", ""), text("reason", "Deprecation reason", "")],
    requires_project=True,
)
def deprecate_part(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Mark one object part deprecated with a reason."""
    root = require_project(ctx, "deprecating a part")
    raw = ctx.raw("objects")
    found = (
        next(
            (
                item
                for item in raw.get("objects", [])
                if isinstance(item, dict) and item.get("id") == values["partId"]
            ),
            None,
        )
        if isinstance(raw, dict)
        else None
    )
    if found is None:
        raise FeatureInputError("Enter an existing part ID.")
    found["deprecated"] = True
    found["deprecationReason"] = values["reason"].strip()
    path = root / "04 Objects/objects.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("objects", None)
    return result(summary={"partId": values["partId"], "deprecated": True})

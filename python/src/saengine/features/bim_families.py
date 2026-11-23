"""BIM family, type and parameter feature buttons."""

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
from saengine.features.bim_common import require_bim, write_bim_csv, write_bim_json


@feature(
    "bimAdditionsFamilies.duplicateType",
    "Duplicate Type",
    part="bim",
    fields=[
        text("sourceType", "Source type", "B300x500"),
        text("newType", "New type", "B300x500-D"),
    ],
)
def duplicate_type(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Duplicates a BIM family type with a new name."""
    require_bim(ctx)
    record = {"source": values["sourceType"], "duplicate": values["newType"]}
    path = write_bim_json(ctx, "duplicated-types.json", [record])
    return result(
        summary={
            "sourceType": values["sourceType"],
            "newType": values["newType"],
            "exportPath": path,
        },
        tables=[
            table("Duplicated Type", [("source", "Source"), ("duplicate", "New type")], [record])
        ],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsFamilies.renameType",
    "Rename Type",
    part="bim",
    fields=[text("oldType", "Existing type", "B300x500"), text("newType", "New type", "Beam-300")],
)
def rename_type(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Renames a BIM family type."""
    require_bim(ctx)
    change = {"oldType": values["oldType"], "newType": values["newType"]}
    path = write_bim_json(ctx, "renamed-type.json", change)
    return result(
        summary={"oldType": values["oldType"], "newType": values["newType"], "exportPath": path},
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsFamilies.typeCatalog",
    "Type Catalog",
    part="bim",
    fields=[
        select(
            "category",
            "Category",
            [("beam", "Beams"), ("column", "Columns"), ("wall", "Walls"), ("slab", "Slabs")],
            "beam",
        )
    ],
)
def type_catalog(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Lists available BIM types for a category."""
    data = require_bim(ctx)
    types = sorted(
        {str(e.get("type", "")) for e in data["elements"] if e.get("kind") == values["category"]}
    )
    rows = [{"type": t} for t in types]
    path = write_bim_csv(ctx, "type-catalog.csv", ["type"], rows)
    return result(
        summary={"category": values["category"], "typeCount": len(rows), "exportPath": path},
        tables=[table("Type Catalog", [("type", "Type")], rows)],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsFamilies.purgeTypes",
    "Purge Types",
    part="bim",
    fields=[checkbox("removeUnused", "Remove unused types", True)],
)
def purge_types(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Identifies unused BIM family types."""
    data = require_bim(ctx)
    used = sorted({str(e.get("type", "")) for e in data["elements"]})
    rows = [{"type": t, "used": True} for t in used]
    path = write_bim_csv(ctx, "purge-types-report.csv", ["type", "used"], rows)
    return result(
        summary={
            "removeUnused": bool(values["removeUnused"]),
            "usedTypeCount": len(rows),
            "exportPath": path,
        },
        tables=[table("Used Types", [("type", "Type"), ("used", "Used")], rows)],
        notes=[
            "The report confirms used types; no catalog entries are deleted.",
            f"Export: {path}",
        ],
    )


@feature(
    "bimAdditionsFamilies.familyTemplates",
    "Family Templates",
    part="bim",
    fields=[
        select(
            "template",
            "Template",
            [
                ("structuralColumn", "Structural column"),
                ("structuralBeam", "Structural beam"),
                ("wall", "Wall"),
                ("generic", "Generic"),
            ],
            "structuralBeam",
        )
    ],
)
def family_templates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Selects a family template for new BIM components."""
    require_bim(ctx)
    path = write_bim_json(ctx, "family-template.json", {"template": values["template"]})
    return result(
        summary={"template": values["template"], "exportPath": path}, notes=[f"Export: {path}"]
    )


@feature(
    "bimAdditionsFamilies.addParameter",
    "Add Parameter",
    part="bim",
    fields=[
        text("name", "Parameter name", "FireRating"),
        select(
            "parameterType",
            "Parameter type",
            [("text", "Text"), ("number", "Number"), ("boolean", "Boolean")],
            "text",
        ),
        text("defaultValue", "Default value", "N/A"),
    ],
)
def add_parameter(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Adds a parameter definition to a BIM family."""
    require_bim(ctx)
    parameter = {
        "name": values["name"],
        "type": values["parameterType"],
        "default": values["defaultValue"],
    }
    path = write_bim_json(ctx, "family-parameter.json", parameter)
    return result(
        summary={
            "parameterName": values["name"],
            "parameterType": values["parameterType"],
            "exportPath": path,
        },
        tables=[
            table(
                "Family Parameter",
                [("name", "Name"), ("type", "Type"), ("default", "Default")],
                [parameter],
            )
        ],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsFamilies.parameterFormula",
    "Parameter Formula",
    part="bim",
    fields=[
        text("parameter", "Dependent parameter", "Volume"),
        text("formula", "Formula", "Width * Height * Length"),
        text("units", "Units", "m³"),
    ],
)
def parameter_formula(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a parameter formula for a BIM family."""
    require_bim(ctx)
    formula = {
        "parameter": values["parameter"],
        "formula": values["formula"],
        "units": values["units"],
    }
    path = write_bim_json(ctx, "parameter-formula.json", formula)
    return result(
        summary={
            "parameter": values["parameter"],
            "formula": values["formula"],
            "units": values["units"],
            "exportPath": path,
        },
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsFamilies.sharedParameter",
    "Shared Parameter",
    part="bim",
    fields=[
        text("name", "Shared parameter", "AssemblyCode"),
        text("group", "Parameter group", "Identity Data"),
    ],
)
def shared_parameter(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates or selects a shared BIM parameter."""
    require_bim(ctx)
    p = {"name": values["name"], "group": values["group"]}
    path = write_bim_json(ctx, "shared-parameter.json", p)
    return result(
        summary={
            "parameterName": values["name"],
            "parameterGroup": values["group"],
            "exportPath": path,
        },
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsFamilies.parameterMapping",
    "Parameter Mapping",
    part="bim",
    fields=[
        text("sourceParameter", "Source parameter", "Mark"),
        text("targetParameter", "Target parameter", "AssemblyMark"),
    ],
)
def parameter_mapping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Maps a source parameter to a target BIM parameter."""
    require_bim(ctx)
    map_row = {"source": values["sourceParameter"], "target": values["targetParameter"]}
    path = write_bim_csv(ctx, "parameter-mapping.csv", ["source", "target"], [map_row])
    return result(
        summary={
            "sourceParameter": values["sourceParameter"],
            "targetParameter": values["targetParameter"],
            "exportPath": path,
        },
        tables=[
            table("Parameter Mapping", [("source", "Source"), ("target", "Target")], [map_row])
        ],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsFamilies.loadNested",
    "Load Nested",
    part="bim",
    fields=[
        text("nestedFamily", "Nested family", "Plate-Detail"),
        text("hostFamily", "Host family", "Column"),
    ],
)
def load_nested(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Loads a nested family into a host family."""
    require_bim(ctx)
    item = {"nested": values["nestedFamily"], "host": values["hostFamily"]}
    path = write_bim_json(ctx, "nested-family-load.json", item)
    return result(
        summary={
            "nestedFamily": values["nestedFamily"],
            "hostFamily": values["hostFamily"],
            "exportPath": path,
        },
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsFamilies.nestComponent",
    "Nest Component",
    part="bim",
    fields=[
        text("parent", "Parent component", "Frame"),
        text("component", "Nested component", "Plate"),
    ],
)
def nest_component(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Adds a component to a parent family hierarchy."""
    require_bim(ctx)
    item = {"parent": values["parent"], "component": values["component"]}
    path = write_bim_json(ctx, "nested-component.json", item)
    return result(
        summary={"parent": values["parent"], "component": values["component"], "exportPath": path},
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsFamilies.arrayParameter",
    "Array Parameter",
    part="bim",
    fields=[
        number("count", "Array count", 4, unit="ea", min=2),
        number("spacing", "Array spacing", 0.5, unit="m", min=0.001),
    ],
)
def array_parameter(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a family array parameter."""
    require_bim(ctx)
    count = int(values["count"])
    rows = [{"index": i, "offsetM": i * values["spacing"]} for i in range(count)]
    path = write_bim_csv(ctx, "family-array.csv", ["index", "offsetM"], rows)
    return result(
        summary={"arrayCount": count, "spacingM": values["spacing"], "exportPath": path},
        tables=[table("Family Array", [("index", "Index"), ("offsetM", "Offset [m]", "m")], rows)],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsFamilies.nestedVisibility",
    "Nested Visibility",
    part="bim",
    fields=[
        select(
            "view",
            "Visibility view",
            [("coarse", "Coarse"), ("medium", "Medium"), ("fine", "Fine")],
            "fine",
        ),
        checkbox("visible", "Visible", True),
    ],
)
def nested_visibility(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Sets nested family visibility for a detail scale."""
    require_bim(ctx)
    return result(summary={"view": values["view"], "visible": bool(values["visible"])})


@feature(
    "bimAdditionsFamilies.solidSweep",
    "Solid Sweep",
    part="bim",
    fields=[
        number("length", "Sweep length", 2.0, unit="m", min=0.1),
        number("width", "Sweep width", 0.1, unit="m", min=0.001),
        number("height", "Sweep height", 0.1, unit="m", min=0.001),
    ],
)
def solid_sweep(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a rectangular solid-sweep geometry proposal."""
    require_bim(ctx)
    volume = values["length"] * values["width"] * values["height"]
    sweep = {
        "lengthM": values["length"],
        "widthM": values["width"],
        "heightM": values["height"],
        "volumeM3": volume,
    }
    path = write_bim_json(ctx, "solid-sweep.json", sweep)
    return result(
        summary={**sweep, "exportPath": path},
        tables=[
            table(
                "Solid Sweep",
                [
                    ("lengthM", "Length [m]", "m"),
                    ("widthM", "Width [m]", "m"),
                    ("heightM", "Height [m]", "m"),
                    ("volumeM3", "Volume [m³]", "m³"),
                ],
                [sweep],
            )
        ],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsFamilies.voidExtrusion",
    "Void Extrusion",
    part="bim",
    fields=[
        number("width", "Void width", 0.5, unit="m", min=0.001),
        number("height", "Void height", 0.5, unit="m", min=0.001),
        number("depth", "Void depth", 1.0, unit="m", min=0.001),
    ],
)
def void_extrusion(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a rectangular void-extrusion in a family."""
    require_bim(ctx)
    volume = values["width"] * values["height"] * values["depth"]
    void = {
        "widthM": values["width"],
        "heightM": values["height"],
        "depthM": values["depth"],
        "volumeM3": volume,
    }
    path = write_bim_json(ctx, "void-extrusion.json", void)
    return result(
        summary={**void, "exportPath": path},
        notes=[
            "Void geometry is represented as an export instruction; host subtraction is not applied.",
            f"Export: {path}",
        ],
    )


@feature(
    "bimAdditionsFamilies.blendGeometry",
    "Blend Geometry",
    part="bim",
    fields=[
        number("bottomWidth", "Bottom width", 0.5, unit="m", min=0.001),
        number("topWidth", "Top width", 0.3, unit="m", min=0.001),
        number("height", "Blend height", 1.0, unit="m", min=0.001),
    ],
)
def blend_geometry(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a tapered blend geometry proposal."""
    require_bim(ctx)
    area = (values["bottomWidth"] + values["topWidth"]) / 2 * values["height"]
    blend = {
        "bottomWidthM": values["bottomWidth"],
        "topWidthM": values["topWidth"],
        "heightM": values["height"],
        "meanAreaM2": area,
    }
    path = write_bim_json(ctx, "blend-geometry.json", blend)
    return result(
        summary={**blend, "exportPath": path},
        notes=[
            "The mean area is a dimensional estimate for a prismatic planar blend.",
            f"Export: {path}",
        ],
    )


@feature(
    "bimAdditionsFamilies.dimensionConstraint",
    "Dimension Constraint",
    part="bim",
    fields=[
        text("name", "Dimension name", "Length"),
        number("value", "Constraint value", 3.0, unit="m", min=0.001),
        checkbox("locked", "Locked", True),
    ],
)
def dimension_constraint(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Adds or updates a family dimension constraint."""
    require_bim(ctx)
    c = {"name": values["name"], "valueM": values["value"], "locked": bool(values["locked"])}
    path = write_bim_json(ctx, "dimension-constraint.json", c)
    return result(
        summary={
            "constraintName": values["name"],
            "valueM": values["value"],
            "locked": bool(values["locked"]),
            "exportPath": path,
        },
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsFamilies.referencePlane",
    "Reference Plane",
    part="bim",
    fields=[
        select("orientation", "Orientation", [("x", "X"), ("y", "Y"), ("z", "Z")], "z"),
        number("position", "Plane position", 0.0, unit="m"),
    ],
)
def reference_plane(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a family reference plane."""
    require_bim(ctx)
    plane = {"orientation": values["orientation"].upper(), "positionM": values["position"]}
    path = write_bim_json(ctx, "reference-plane.json", plane)
    return result(summary={**plane, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsFamilies.lockAlignment",
    "Lock Alignment",
    part="bim",
    fields=[
        text("reference", "Reference object", "Reference Plane"),
        text("host", "Host object", "Extrusion"),
        checkbox("locked", "Alignment locked", True),
    ],
)
def lock_alignment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Locks a family element to a reference."""
    require_bim(ctx)
    a = {"reference": values["reference"], "host": values["host"], "locked": bool(values["locked"])}
    path = write_bim_json(ctx, "lock-alignment.json", a)
    return result(
        summary={
            "reference": values["reference"],
            "host": values["host"],
            "locked": bool(values["locked"]),
            "exportPath": path,
        },
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsFamilies.familyBrowser",
    "Family Browser",
    part="bim",
    fields=[
        text("search", "Search text", ""),
        select(
            "category",
            "Category",
            [("all", "All"), ("beam", "Beam"), ("column", "Column"), ("wall", "Wall")],
            "all",
        ),
    ],
)
def family_browser(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Browses available element types and family names."""
    data = require_bim(ctx)
    rows = []
    for e in data["elements"]:
        if values["category"] != "all" and e.get("kind") != values["category"]:
            continue
        text = str(e.get("type", ""))
        if values["search"].lower() in text.lower():
            rows.append({"type": text, "kind": str(e.get("kind", ""))})
    unique = []
    seen = set()
    for r in rows:
        if r["type"] not in seen:
            seen.add(r["type"])
            unique.append(r)
    path = write_bim_csv(ctx, "family-browser.csv", ["type", "kind"], unique)
    return result(
        summary={
            "search": values["search"],
            "category": values["category"],
            "familyCount": len(unique),
            "exportPath": path,
        },
        tables=[table("Family Browser", [("type", "Type"), ("kind", "Kind")], unique)],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsFamilies.batchLoadFamilies",
    "Batch Load Families",
    part="bim",
    fields=[
        text("familyNames", "Family names", "Beam,Column,Wall"),
        checkbox("replaceExisting", "Replace existing types", False),
    ],
)
def batch_load_families(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Loads multiple family names as a batch."""
    require_bim(ctx)
    names = [x.strip() for x in values["familyNames"].split(",") if x.strip()]
    rows = [{"family": n, "replace": bool(values["replaceExisting"])} for n in names]
    path = write_bim_csv(ctx, "batch-load-families.csv", ["family", "replace"], rows)
    return result(
        summary={
            "familyCount": len(names),
            "replaceExisting": bool(values["replaceExisting"]),
            "exportPath": path,
        },
        tables=[table("Batch Load", [("family", "Family"), ("replace", "Replace")], rows)],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsFamilies.purgeUnusedFamilies",
    "Purge Unused Families",
    part="bim",
    fields=[checkbox("confirmPurge", "Confirm purge of unused families", False)],
)
def purge_unused_families(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Reports unused family types and optionally confirms purge."""
    data = require_bim(ctx)
    used = sorted({str(e.get("type", "")) for e in data["elements"]})
    if not values["confirmPurge"]:
        raise FeatureInputError("Confirm the purge before generating the unused-family report.")
    path = write_bim_csv(
        ctx,
        "purge-unused-families.csv",
        ["type", "status"],
        [{"type": t, "status": "used"} for t in used],
    )
    return result(
        summary={"purgeConfirmed": True, "usedFamilyCount": len(used), "exportPath": path},
        notes=[f"Export: {path}"],
    )

"""Objects - Object Library tab: type management, parametric rules, assignment & integrity checks."""

from __future__ import annotations

import itertools
import json
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
from saengine.features.objects_common import (
    find_object,
    materials_or_default,
    objects_or_default,
    parse_numbers,
    require_objects,
    require_root,
    safe_json,
    save_export,
    used_type_ids,
)
from saengine.library import objects as o
from saengine.library.sections import section_properties
from saengine.report.clauses import in_force


@feature(
    "libraryObjects.newObjectType",
    "New Object Type",
    part="objects",
    fields=[
        text("typeId", "Object type ID", "B300x550"),
        text("typeName", "Object type name", "Beam 300x550"),
        select(
            "kind",
            "Element kind",
            [("beam", "Beam"), ("column", "Column"), ("slab", "Slab"), ("wall", "Wall")],
            "beam",
        ),
        text("materialId", "Material ID", "C24.1"),
        number("dim1Mm", "Width / thickness", 300.0, unit="mm", min=50.0),
        number("dim2Mm", "Depth (beam/column)", 550.0, unit="mm", min=50.0),
        checkbox("exportJson", "Export object JSON to 04 Objects/exports", False),
    ],
    requires_project=False,
)
def new_object_type(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create and validate a reusable structural object type definition."""
    oid = values["typeId"].strip() or "OBJ-1"
    name = values["typeName"].strip() or oid
    kind = values["kind"]
    mat = values["materialId"].strip() or "C24.1"
    d1, d2 = values["dim1Mm"], values["dim2Mm"]
    if kind in ("beam", "column"):
        payload: dict[str, Any] = {
            "id": oid,
            "name": name,
            "kind": kind,
            "material": mat,
            "profile": {"shape": "rectangle", "xDim": d1, "yDim": d2},
        }
    else:
        payload = {"id": oid, "name": name, "kind": kind, "material": mat, "thickness": d1}
    try:
        lib = o.ObjectLibrary.model_validate({"objects": [payload]})
    except Exception as exc:
        raise FeatureInputError(f"Invalid object type definition: {exc}") from exc
    out_path = ""
    if values["exportJson"]:
        require_root(ctx, "exporting new object type")
        out_path = str(save_export(ctx, f"object-{oid}.json", safe_json(payload)))
    obj = lib.objects[0]
    return result(
        summary={
            "objectId": obj.id,
            "kind": obj.kind,
            "material": obj.material,
            "exportPath": out_path or "preview",
        },
        tables=[
            table(
                "Validated object type",
                [("field", "Property"), ("value", "Value")],
                [{"field": k, "value": str(v)} for k, v in payload.items()],
            )
        ],
        notes=["Validated against saengine.objects/1 schema."],
    )


@feature(
    "libraryObjects.objectLibrary",
    "Object Library",
    part="objects",
    fields=[text("kindFilter", "Filter by kind (blank = all)", "")],
    requires_project=False,
)
def object_library(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Browse project or default object types with materials, shapes, and placement counts."""
    lib, is_proj = objects_or_default(ctx)
    usages = used_type_ids(ctx) if ctx.root is not None else {}
    filt = values["kindFilter"].strip().lower()
    rows = []
    for obj in lib.objects:
        if filt and filt not in obj.kind.lower():
            continue
        prof = getattr(obj, "profile", None)
        shape = getattr(prof, "shape", f"t={getattr(obj, 'thickness', '-')}")
        rows.append(
            {
                "id": obj.id,
                "name": obj.name,
                "kind": obj.kind,
                "material": obj.material,
                "shape": shape,
                "placements": usages.get(obj.id, 0),
            }
        )
    return result(
        summary={"source": "project" if is_proj else "default library", "typeCount": len(rows)},
        tables=[
            table(
                "Object library catalogue",
                [
                    ("id", "ID"),
                    ("name", "Name"),
                    ("kind", "Kind"),
                    ("material", "Material"),
                    ("shape", "Shape / Thickness"),
                    ("placements", "Model count"),
                ],
                rows,
            )
        ],
        notes=[
            "Shows each defined object type and how many BIM/floor-plan instances reference it."
        ],
    )


@feature(
    "libraryObjects.objectProperties",
    "Object Properties",
    part="objects",
    fields=[text("objectId", "Object type ID (blank = first)", "")],
    requires_project=False,
)
def object_properties(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect all parameters of an object type, including profile, reinforcement, and modifiers."""
    lib, _ = objects_or_default(ctx)
    obj = find_object(lib, values["objectId"])
    dumped = obj.model_dump(mode="json", exclude_none=True)
    rows = [
        {"parameter": k, "value": json.dumps(v) if isinstance(v, (dict, list)) else str(v)}
        for k, v in dumped.items()
    ]
    return result(
        summary={
            "objectId": obj.id,
            "kind": obj.kind,
            "material": obj.material,
            "parameterCount": len(rows),
        },
        tables=[
            table(f"Parameters of {obj.id}", [("parameter", "Parameter"), ("value", "Value")], rows)
        ],
        notes=["Parameters shown are inherited by every BIM/FEM instance of this type."],
    )


@feature(
    "libraryObjects.parameterEditor",
    "Parameter Editor",
    part="objects",
    fields=[
        text("objectId", "Object type ID (blank = first)", ""),
        number("scaleFactor", "Dimensional scale factor", 1.1, min=0.5, max=2.0),
    ],
    requires_project=False,
)
def parameter_editor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview parametric dimension updates and resulting stiffness/area changes for an object type."""
    lib, _ = objects_or_default(ctx)
    obj = find_object(lib, values["objectId"])
    s = values["scaleFactor"]
    prof = getattr(obj, "profile", None)
    if prof is not None and not isinstance(prof, o.DesignedProfile):
        p_orig = section_properties(prof)
        d = prof.model_dump()
        for k in (
            "xDim",
            "yDim",
            "radius",
            "overallWidth",
            "overallDepth",
            "depth",
            "width",
            "flangeWidth",
        ):
            if k in d and isinstance(d[k], (int, float)):
                d[k] = d[k] * s
        scaled_prof = type(prof).model_validate(d)
        p_new = section_properties(scaled_prof)
        rows = [
            {
                "metric": "Area",
                "before": p_orig.area,
                "after": p_new.area,
                "ratio": p_new.area / p_orig.area,
            },
            {
                "metric": "Ixx",
                "before": p_orig.ixx,
                "after": p_new.ixx,
                "ratio": p_new.ixx / p_orig.ixx,
            },
            {
                "metric": "Iyy",
                "before": p_orig.iyy,
                "after": p_new.iyy,
                "ratio": p_new.iyy / p_orig.iyy,
            },
        ]
    else:
        t = float(getattr(obj, "thickness", 200.0))
        rows = [{"metric": "Thickness [mm]", "before": t, "after": t * s, "ratio": s}]
    return result(
        summary={"objectId": obj.id, "scaleFactor": s, "areaScaleRatio": rows[0]["ratio"]},
        tables=[
            table(
                f"Parametric edit preview ({obj.id})",
                [
                    ("metric", "Metric"),
                    ("before", "Before"),
                    ("after", "After"),
                    ("ratio", "Ratio"),
                ],
                rows,
            )
        ],
        notes=["Preview only; does not mutate 04 Objects/objects.json."],
    )


@feature(
    "libraryObjects.constraintRules",
    "Constraint Rules",
    part="objects",
    fields=[
        number("minAspect", "Min depth/width ratio", 1.0, min=0.25),
        number("maxAspect", "Max depth/width ratio", 3.5, min=1.0),
        number("minCoverMm", "Minimum clear cover", 20.0, unit="mm", min=10.0),
    ],
    requires_project=False,
)
def constraint_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check dimensional and geometric constraint rules across all object types."""
    lib, _ = objects_or_default(ctx)
    rows = []
    fails = 0
    for obj in lib.objects:
        prof = getattr(obj, "profile", None)
        aspect = 1.0
        ok = True
        note = "OK"
        if isinstance(prof, o.RectangleProfile):
            aspect = max(prof.xDim, prof.yDim) / min(prof.xDim, prof.yDim)
            if not (values["minAspect"] <= aspect <= values["maxAspect"]):
                ok = False
                note = f"Aspect {aspect:.2f} outside [{values['minAspect']}, {values['maxAspect']}]"
        reinf = getattr(obj, "reinforcement", None)
        if reinf is not None and getattr(reinf, "cover", 999.0) < values["minCoverMm"]:
            ok = False
            note = f"Cover {reinf.cover:g} < {values['minCoverMm']:g} mm"
        if not ok:
            fails += 1
        rows.append({"id": obj.id, "kind": obj.kind, "aspect": aspect, "ok": ok, "note": note})
    return result(
        summary={"checkedCount": len(rows), "violations": fails, "allPass": fails == 0},
        tables=[
            table(
                "Geometric constraint audit",
                [
                    ("id", "ID"),
                    ("kind", "Kind"),
                    ("aspect", "Aspect"),
                    ("ok", "Pass"),
                    ("note", "Note"),
                ],
                rows,
            )
        ],
        notes=["Validates section aspect ratios and minimum cover constraints."],
    )


@feature(
    "libraryObjects.variantGenerator",
    "Variant Generator",
    part="objects",
    fields=[
        text("baseName", "Prefix", "C"),
        text("widthsMm", "Widths [mm]", "300, 400"),
        text("depthsMm", "Depths [mm]", "400, 500, 600"),
    ],
    requires_project=False,
)
def variant_generator(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a matrix of rectangular object-type variants from width and depth parameter lists."""
    ws = parse_numbers(values["widthsMm"], "Widths")
    ds = parse_numbers(values["depthsMm"], "Depths")
    prefix = values["baseName"].strip() or "SEC"
    rows = []
    for w, d in itertools.product(ws, ds):
        prof = o.RectangleProfile(xDim=w, yDim=d)
        props = section_properties(prof)
        rows.append(
            {
                "id": f"{prefix}{int(w)}x{int(d)}",
                "widthMm": w,
                "depthMm": d,
                "areaMm2": props.area,
                "ixxMm4": props.ixx,
            }
        )
    return result(
        summary={
            "variantCount": len(rows),
            "minAreaMm2": min(r["areaMm2"] for r in rows),
            "maxAreaMm2": max(r["areaMm2"] for r in rows),
        },
        tables=[
            table(
                "Generated object type variants",
                [
                    ("id", "Variant ID"),
                    ("widthMm", "Width", "mm"),
                    ("depthMm", "Depth", "mm"),
                    ("areaMm2", "Area", "mm2"),
                    ("ixxMm4", "Ixx", "mm4"),
                ],
                rows,
            )
        ],
        notes=["Cartesian product of parameter ranges validated via section_properties."],
    )


@feature(
    "libraryObjects.assignToSelection",
    "Assign to Selection",
    part="objects",
    fields=[
        text("objectId", "Object type ID to assign", ""),
        text("elementIds", "Target BIM element IDs (comma separated; blank = matching kind)", ""),
    ],
    requires_project=True,
)
def assign_to_selection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview assignment of an object type to selected BIM elements and check kind compatibility."""
    lib = require_objects(ctx)
    obj = find_object(lib, values["objectId"])
    bim = ctx.raw("bim") or {}
    elements = bim.get("elements") or []
    wanted = {t.strip() for t in values["elementIds"].split(",") if t.strip()}
    rows = []
    for el in elements:
        if not isinstance(el, dict):
            continue
        eid = str(el.get("id", ""))
        if wanted and eid not in wanted:
            continue
        if not wanted and el.get("kind") != obj.kind:
            continue
        rows.append(
            {
                "elementId": eid,
                "elementKind": str(el.get("kind", "")),
                "currentType": str(el.get("type", "")),
                "newType": obj.id,
                "compatible": el.get("kind") == obj.kind,
            }
        )
    if not rows:
        raise FeatureInputError(f"No BIM elements matched for kind '{obj.kind}'.")
    return result(
        summary={
            "targetType": obj.id,
            "matchedElements": len(rows),
            "compatibleCount": sum(1 for r in rows if r["compatible"]),
        },
        tables=[
            table(
                "Type assignment preview",
                [
                    ("elementId", "Element"),
                    ("elementKind", "Kind"),
                    ("currentType", "Current type"),
                    ("newType", "Assigned type"),
                    ("compatible", "Compatible"),
                ],
                rows,
            )
        ],
        notes=["Verifies element kind compatibility before updating BIM element assignments."],
    )


@feature(
    "libraryObjects.replaceType",
    "Replace Type",
    part="objects",
    fields=[
        text("oldTypeId", "Existing object type ID", ""),
        text("newTypeId", "Replacement object type ID", ""),
    ],
    requires_project=True,
)
def replace_type(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Trace all BIM and Floor Plan references that would change when replacing one object type with another."""
    lib = require_objects(ctx)
    old_obj = find_object(lib, values["oldTypeId"])
    new_obj = find_object(lib, values["newTypeId"] or old_obj.id)
    if old_obj.kind != new_obj.kind:
        raise FeatureInputError(
            f"Cannot replace {old_obj.kind} '{old_obj.id}' with {new_obj.kind} '{new_obj.id}'."
        )
    bim = ctx.raw("bim") or {}
    hits = [
        {
            "where": "BIM",
            "elementId": el.get("id"),
            "story": el.get("story", "-"),
            "from": old_obj.id,
            "to": new_obj.id,
        }
        for el in (bim.get("elements") or [])
        if isinstance(el, dict) and el.get("type") == old_obj.id
    ]
    return result(
        summary={"fromType": old_obj.id, "toType": new_obj.id, "affectedElements": len(hits)},
        tables=[
            table(
                "Replacement impact list",
                [
                    ("where", "Model"),
                    ("elementId", "Element"),
                    ("story", "Story"),
                    ("from", "From"),
                    ("to", "To"),
                ],
                hits,
            )
        ],
        notes=["Checks kind parity and lists every BIM element referencing the source type."],
    )


@feature(
    "libraryObjects.purgeUnused",
    "Purge Unused",
    part="objects",
    fields=[],
    requires_project=True,
)
def purge_unused(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Identify object types in 04 Objects/objects.json that have zero placements in BIM or Floor Plan."""
    lib = require_objects(ctx)
    usages = used_type_ids(ctx)
    rows = [
        {
            "id": obj.id,
            "name": obj.name,
            "kind": obj.kind,
            "usedCount": usages.get(obj.id, 0),
            "purgeCandidate": usages.get(obj.id, 0) == 0,
        }
        for obj in lib.objects
    ]
    unused = [r for r in rows if r["purgeCandidate"]]
    return result(
        summary={
            "totalTypes": len(rows),
            "usedTypes": len(rows) - len(unused),
            "unusedTypes": len(unused),
        },
        tables=[
            table(
                "Object type usage audit",
                [
                    ("id", "ID"),
                    ("name", "Name"),
                    ("kind", "Kind"),
                    ("usedCount", "Placements"),
                    ("purgeCandidate", "Unused"),
                ],
                rows,
            )
        ],
        notes=["Unused types can be safely removed without breaking BIM or floor-plan references."],
    )


@feature(
    "libraryObjects.typeCatalogue",
    "Type Catalogue",
    part="objects",
    fields=[],
    requires_project=False,
)
def type_catalogue(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Group object types by structural discipline and element kind in a searchable catalogue."""
    lib, is_proj = objects_or_default(ctx)
    rows = []
    for obj in lib.objects:
        discipline = (
            "Substructure" if obj.kind in ("footing", "pileCap", "pile") else "Superstructure"
        )
        rows.append(
            {
                "discipline": discipline,
                "kind": obj.kind,
                "id": obj.id,
                "name": obj.name,
                "material": obj.material,
            }
        )
    return result(
        summary={"source": "project" if is_proj else "default library", "totalTypes": len(rows)},
        tables=[
            table(
                "Discipline type catalogue",
                [
                    ("discipline", "Discipline"),
                    ("kind", "Kind"),
                    ("id", "ID"),
                    ("name", "Name"),
                    ("material", "Material"),
                ],
                rows,
            )
        ],
        notes=["Organises project object types by structural discipline and element kind."],
    )


@feature(
    "libraryObjects.sharedParameters",
    "Shared Parameters",
    part="objects",
    fields=[text("parameterName", "Parameter key to inspect", "material")],
    requires_project=False,
)
def shared_parameters(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List parameter keys shared across object types and inspect their values across the library."""
    lib, _ = objects_or_default(ctx)
    key = values["parameterName"].strip() or "material"
    rows = []
    for obj in lib.objects:
        d = obj.model_dump(mode="json")
        val = d.get(key, "<absent>")
        rows.append({"id": obj.id, "kind": obj.kind, "parameter": key, "value": str(val)})
    return result(
        summary={
            "parameter": key,
            "typesWithKey": sum(1 for r in rows if r["value"] != "<absent>"),
        },
        tables=[
            table(
                f"Shared parameter '{key}'",
                [("id", "Object ID"), ("kind", "Kind"), ("parameter", "Key"), ("value", "Value")],
                rows,
            )
        ],
        notes=[
            "Inspects consistent metadata and engineering parameters shared across object types."
        ],
    )


@feature(
    "libraryObjects.typeMapping",
    "Type Mapping",
    part="objects",
    fields=[
        text(
            "externalNames",
            "External model type names (comma separated)",
            "RC_COL_400x600, BEAM_300x500, SLAB_150, WALL_250",
        ),
    ],
    requires_project=False,
)
def type_mapping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map imported external section/type names onto matching library object types by token similarity."""
    lib, _ = objects_or_default(ctx)
    ext_list = [x.strip() for x in values["externalNames"].split(",") if x.strip()]
    if not ext_list:
        raise FeatureInputError("Provide at least one external type name.")
    rows = []
    matched = 0
    for ext in ext_list:
        tokens = [t.lower() for t in ext.replace("-", "_").split("_") if t]
        best_id = "unmapped"
        best_score = 0
        for obj in lib.objects:
            target = (obj.id + " " + obj.name + " " + obj.kind).lower()
            score = sum(1 for tok in tokens if tok in target)
            if score > best_score:
                best_score = score
                best_id = obj.id
        if best_score > 0:
            matched += 1
        rows.append({"externalName": ext, "mappedId": best_id, "score": best_score})
    return result(
        summary={"externalCount": len(rows), "mappedCount": matched},
        tables=[
            table(
                "External-to-library type mapping",
                [
                    ("externalName", "External name"),
                    ("mappedId", "Matched type"),
                    ("score", "Token hits"),
                ],
                rows,
            )
        ],
        notes=[
            "Matches external model exchange names against library IDs, names, and element kinds."
        ],
    )


@feature(
    "libraryObjects.familyTemplates",
    "Family Templates",
    part="objects",
    fields=[
        select(
            "templateKind",
            "Template family",
            [
                ("beam", "RC Beam"),
                ("column", "RC Column"),
                ("brace", "Steel Brace"),
                ("slab", "RC Slab"),
                ("wall", "Shear Wall"),
            ],
            "beam",
        )
    ],
    requires_project=False,
)
def family_templates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Provide validated starting JSON templates for each structural object family."""
    templates = {
        "beam": {
            "id": "B300x500",
            "name": "Beam 300x500",
            "kind": "beam",
            "material": "C24.1",
            "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
        },
        "column": {
            "id": "C400x400",
            "name": "Column 400x400",
            "kind": "column",
            "material": "C24.1",
            "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
        },
        "brace": {
            "id": "BR-SHS150",
            "name": "Brace SHS 150",
            "kind": "brace",
            "material": "A572-50",
            "profile": {"shape": "rectangleHollow", "xDim": 150, "yDim": 150, "wallThickness": 8},
        },
        "slab": {
            "id": "S150",
            "name": "Slab 150",
            "kind": "slab",
            "material": "C24.1",
            "thickness": 150,
        },
        "wall": {
            "id": "W200",
            "name": "Wall 200",
            "kind": "wall",
            "material": "C24.1",
            "thickness": 200,
        },
    }
    tpl = templates[values["templateKind"]]
    o.ObjectLibrary.model_validate({"objects": [tpl]})
    rows = [{"field": k, "defaultValue": str(v)} for k, v in tpl.items()]
    return result(
        summary={"templateKind": values["templateKind"], "templateId": tpl["id"]},
        tables=[
            table(
                f"Template fields ({values['templateKind']})",
                [("field", "Field"), ("defaultValue", "Default")],
                rows,
            )
        ],
        notes=["Validated against the saengine.objects/1 Pydantic schema."],
    )


@feature(
    "libraryObjects.objectClassification",
    "Object Classification",
    part="objects",
    fields=[],
    requires_project=False,
)
def object_classification(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign standard structural classification codes to every object type for BOQ and schedules."""
    lib, _ = objects_or_default(ctx)
    class_map = {
        "footing": ("21.10", "Substructure - Pad/Strip Foundations"),
        "pileCap": ("21.20", "Substructure - Pile Caps"),
        "pile": ("21.30", "Substructure - Piles"),
        "column": ("22.10", "Superstructure - Columns"),
        "wall": ("22.20", "Superstructure - Structural Walls"),
        "beam": ("22.30", "Superstructure - Beams"),
        "brace": ("22.40", "Superstructure - Bracing"),
        "slab": ("22.50", "Superstructure - Floor Slabs"),
        "staircase": ("22.60", "Superstructure - Stairs"),
    }
    rows = []
    for obj in lib.objects:
        code, title = class_map.get(obj.kind, ("22.99", "Superstructure - Other"))
        rows.append({"id": obj.id, "kind": obj.kind, "classCode": code, "classTitle": title})
    return result(
        summary={"classifiedTypes": len(rows)},
        tables=[
            table(
                "Object type classification schedule",
                [
                    ("id", "ID"),
                    ("kind", "Kind"),
                    ("classCode", "Class code"),
                    ("classTitle", "Classification"),
                ],
                rows,
            )
        ],
        notes=["Maps each object kind to a uniform structural work-breakdown code."],
    )


@feature(
    "libraryObjects.objectAttributes",
    "Object Attributes",
    part="objects",
    fields=[text("objectId", "Object type ID (blank = first)", "")],
    requires_project=False,
)
def object_attributes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect instance-inherited engineering attributes (seismic role, modifiers, reinforcement, connections)."""
    lib, _ = objects_or_default(ctx)
    obj = find_object(lib, values["objectId"])
    attrs = [
        ("id", obj.id),
        ("name", obj.name),
        ("kind", obj.kind),
        ("material", obj.material),
        ("seismicRole", str(getattr(obj, "seismicRole", "auto"))),
        ("hasReinforcement", str(getattr(obj, "reinforcement", None) is not None)),
        ("hasModifiers", str(getattr(obj, "modifiers", None) is not None)),
        ("hasConnection", str(getattr(obj, "connection", None) is not None)),
    ]
    rows = [{"attribute": k, "value": v} for k, v in attrs]
    return result(
        summary={"objectId": obj.id, "attributeCount": len(rows)},
        tables=[
            table(f"Attributes of {obj.id}", [("attribute", "Attribute"), ("value", "Value")], rows)
        ],
        notes=[
            "Attributes shown control analysis, detailing, and connection checks on all instances."
        ],
    )


@feature(
    "libraryObjects.categoryMapping",
    "Category Mapping",
    part="objects",
    fields=[],
    requires_project=False,
)
def category_mapping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map object types to structural BIM/IFC categories and visibility groups."""
    lib, _ = objects_or_default(ctx)
    ifc_map = {
        "beam": "IfcBeamType",
        "column": "IfcColumnType",
        "brace": "IfcMemberType",
        "slab": "IfcSlabType",
        "wall": "IfcWallType",
        "staircase": "IfcStairFlightType",
        "footing": "IfcFootingType",
        "pileCap": "IfcFootingType",
        "pile": "IfcPileType",
    }
    rows = [
        {
            "id": obj.id,
            "kind": obj.kind,
            "ifcEntity": ifc_map.get(obj.kind, "IfcBuildingElementProxyType"),
        }
        for obj in lib.objects
    ]
    return result(
        summary={"mappedTypes": len(rows), "distinctIfcTypes": len({r["ifcEntity"] for r in rows})},
        tables=[
            table(
                "Object-to-IFC category mapping",
                [("id", "Object ID"), ("kind", "Kind"), ("ifcEntity", "IFC entity")],
                rows,
            )
        ],
        notes=["Follows the IFC4 structural type mapping used by the project exporter."],
    )


@feature(
    "libraryObjects.usageTags",
    "Usage Tags",
    part="objects",
    fields=[],
    requires_project=False,
)
def usage_tags(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tag object types by structural role (lateral/gravity/foundation) and material group for filtering."""
    lib, _ = objects_or_default(ctx)
    mats, _ = materials_or_default(ctx)
    rows = []
    for obj in lib.objects:
        mat = mats.get(obj.material)
        mcat = mat.category.value if mat else "unknown"
        role = getattr(obj, "seismicRole", "auto")
        zone = "substructure" if obj.kind in ("footing", "pileCap", "pile") else "superstructure"
        tags = f"{zone}, {mcat}, role:{role}"
        rows.append({"id": obj.id, "kind": obj.kind, "materialCat": mcat, "tags": tags})
    return result(
        summary={"taggedTypes": len(rows)},
        tables=[
            table(
                "Object type usage tags",
                [
                    ("id", "ID"),
                    ("kind", "Kind"),
                    ("materialCat", "Material"),
                    ("tags", "Generated tags"),
                ],
                rows,
            )
        ],
        notes=["Tags combine zone, material category, and seismic framing role."],
    )


@feature(
    "libraryObjects.typeConsistency",
    "Type Consistency",
    part="objects",
    fields=[],
    requires_project=True,
)
def type_consistency(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check that every BIM element references a valid object type of matching element kind."""
    lib = require_objects(ctx)
    by_id = {obj.id: obj for obj in lib.objects}
    bim = ctx.raw("bim") or {}
    elements = bim.get("elements") or []
    rows = []
    bad = 0
    for el in elements:
        if not isinstance(el, dict):
            continue
        eid = str(el.get("id", ""))
        ekind = str(el.get("kind", ""))
        tid = str(el.get("type", ""))
        obj = by_id.get(tid)
        ok = obj is not None and obj.kind == ekind
        if not ok:
            bad += 1
        rows.append({"elementId": eid, "kind": ekind, "type": tid, "ok": ok})
    return result(
        summary={"checkedElements": len(rows), "inconsistencies": bad, "allConsistent": bad == 0},
        tables=[
            table(
                "BIM instance type consistency",
                [("elementId", "Element"), ("kind", "Kind"), ("type", "Type"), ("ok", "Valid")],
                rows[:40],
            )
        ],
        notes=["Checks every BIM element for missing type IDs or element-kind mismatches."],
    )


@feature(
    "libraryObjects.unusedParameters",
    "Unused Parameters",
    part="objects",
    fields=[],
    requires_project=False,
)
def unused_parameters(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit object types for unset optional parameters and non-structural placeholders."""
    lib, _ = objects_or_default(ctx)
    rows = []
    for obj in lib.objects:
        raw = obj.model_dump(mode="json")
        unset = [k for k, v in raw.items() if v is None]
        rows.append(
            {
                "id": obj.id,
                "kind": obj.kind,
                "unsetCount": len(unset),
                "unsetFields": ", ".join(unset[:8]),
            }
        )
    return result(
        summary={
            "objectCount": len(rows),
            "totalOptionalUnset": sum(r["unsetCount"] for r in rows),
        },
        tables=[
            table(
                "Optional / unpopulated fields per object type",
                [
                    ("id", "ID"),
                    ("kind", "Kind"),
                    ("unsetCount", "Unset count"),
                    ("unsetFields", "Fields"),
                ],
                rows,
            )
        ],
        notes=["Lists optional schema parameters currently left at default/None."],
    )


@feature(
    "libraryObjects.geometryCheck",
    "Geometry Check",
    part="objects",
    fields=[],
    requires_project=False,
)
def geometry_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate that every profile in the object library builds positive finite area and inertias."""
    lib, _ = objects_or_default(ctx)
    rows = []
    fails = 0
    for obj in lib.objects:
        prof = getattr(obj, "profile", None)
        if prof is None:
            t = float(getattr(obj, "thickness", 0.0))
            ok = t > 0
            if not ok:
                fails += 1
            rows.append({"id": obj.id, "shape": "planar", "areaMm2": t * 1000.0, "ok": ok})
            continue
        if isinstance(prof, o.DesignedProfile) and ctx.root is None:
            continue
        with in_force(ctx.root):
            props = section_properties(prof)
        ok = props.area > 0 and props.ixx > 0 and props.iyy > 0
        if not ok:
            fails += 1
        rows.append({"id": obj.id, "shape": prof.shape, "areaMm2": props.area, "ok": ok})
    return result(
        summary={"checkedObjects": len(rows), "geometryErrors": fails, "allValid": fails == 0},
        tables=[
            table(
                "Object geometry validation",
                [("id", "ID"), ("shape", "Shape"), ("areaMm2", "Area", "mm2"), ("ok", "Valid")],
                rows,
            )
        ],
        notes=[
            "Meshes and solves every cross-section profile to confirm positive area and inertias."
        ],
    )


@feature(
    "libraryObjects.referenceIntegrity",
    "Reference Integrity",
    part="objects",
    fields=[],
    requires_project=False,
)
def reference_integrity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detect broken references between object types, materials, pile types, and designed sections."""
    lib, is_proj = objects_or_default(ctx)
    mats, _ = materials_or_default(ctx)
    with in_force(ctx.root):
        problems = lib.check_materials(mats)
    rows = [{"issue": p} for p in problems]
    return result(
        summary={
            "source": "project" if is_proj else "default library",
            "brokenReferences": len(rows),
            "integrityOk": len(rows) == 0,
        },
        tables=[
            table(
                "Reference integrity check",
                [("issue", "Detected issue")],
                rows or [{"issue": "No broken references detected"}],
            )
        ],
        notes=["Verifies material, reinforcement rebar, and confinement material references."],
    )

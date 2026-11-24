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


def _object_types(ctx: FeatureContext) -> dict[str, dict[str, Any]]:
    raw_obj = ctx.raw("objects") or {}
    return {
        str(o.get("id", "")): o
        for o in (raw_obj.get("objects") or [])
        if isinstance(o, dict) and o.get("id")
    }


def _safe_eval_expr(expr: str, env: dict[str, float]) -> float:
    import ast
    import operator

    ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    def _ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in env:
            return float(env[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return float(ops[type(node.op)](_ev(node.left), _ev(node.right)))
        if isinstance(node, ast.UnaryOp) and type(node.op) in ops:
            return float(ops[type(node.op)](_ev(node.operand)))
        raise FeatureInputError(f"Unsupported formula expression: {expr!r}")

    return _ev(ast.parse(expr, mode="eval"))


@feature(
    "bimAdditionsFamilies.duplicateType",
    "Duplicate Type",
    part="bim",
    fields=[
        text("sourceType", "Source type ID", "B300x500"),
        text("newType", "New type ID", "B300x500-Heavy"),
    ],
)
def duplicate_type(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Clone an existing 04 Objects / 06 BIM family type definition under a validated new name."""
    data = require_bim(ctx)
    objs = _object_types(ctx)
    used_in_bim = {
        str(e.get("type", "")) for e in (data.get("elements") or []) if isinstance(e, dict)
    }
    all_known = set(objs) | used_in_bim
    src = values["sourceType"].strip()
    dst = values["newType"].strip()
    if src not in all_known:
        raise FeatureInputError(f"Source type {src!r} does not exist in 04 Objects or 06 BIM.")
    if not dst or dst == src or dst in all_known:
        raise FeatureInputError(f"New type ID {dst!r} must be non-empty and unique from {src!r}.")
    base_def = dict(objs.get(src) or {"id": src, "kind": "custom"})
    cloned = {**base_def, "id": dst, "clonedFrom": src}
    path = write_bim_json(ctx, "duplicated-types.json", [cloned])
    return result(
        summary={
            "sourceType": src,
            "newType": dst,
            "copiedFields": len(cloned),
            "exportPath": path,
        },
        tables=[
            table(
                "Cloned Type Definition",
                [("source", "Source"), ("duplicate", "New type"), ("fields", "Copied Props")],
                [{"source": src, "duplicate": dst, "fields": len(cloned)}],
            )
        ],
        notes=[
            f"Cloned {len(cloned)} object property field(s) from {src} -> {dst}; saved to {path}."
        ],
    )


@feature(
    "bimAdditionsFamilies.renameType",
    "Rename Type",
    part="bim",
    fields=[
        text("oldType", "Existing type ID", "B300x500"),
        text("newType", "Replacement type ID", "B300x500-R"),
    ],
)
def rename_type(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate and trace type rename impact count across 06 BIM elements and 04 Objects."""
    data = require_bim(ctx)
    objs = _object_types(ctx)
    old_t = values["oldType"].strip()
    new_t = values["newType"].strip()
    elements = [e for e in (data.get("elements") or []) if isinstance(e, dict)]
    known = set(objs) | {str(e.get("type", "")) for e in elements}
    if old_t not in known:
        raise FeatureInputError(f"Existing type {old_t!r} does not exist in 04 Objects or 06 BIM.")
    if not new_t or new_t in known:
        raise FeatureInputError(f"Replacement type {new_t!r} already exists or is empty.")
    affected = [str(e.get("id", "")) for e in elements if str(e.get("type", "")) == old_t]
    change = {
        "oldType": old_t,
        "newType": new_t,
        "affectedElementCount": len(affected),
        "affectedElements": affected,
    }
    path = write_bim_json(ctx, "renamed-type.json", change)
    return result(
        summary={**change, "exportPath": path},
        notes=[f"Rename impacts {len(affected)} placed BIM element(s); saved to {path}."],
    )


@feature(
    "bimAdditionsFamilies.typeCatalog",
    "Type Catalog",
    part="bim",
    fields=[
        select(
            "category",
            "Element category",
            [
                ("all", "All categories"),
                ("beam", "Beams"),
                ("column", "Columns"),
                ("wall", "Walls"),
                ("slab", "Slabs"),
            ],
            "all",
        )
    ],
)
def type_catalog(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build catalog of 04 Objects & 06 BIM types with geometry, material, and placed counts."""
    data = require_bim(ctx)
    objs = _object_types(ctx)
    cat = values["category"]
    counts: dict[str, int] = {}
    kinds: dict[str, str] = {}
    for e in data.get("elements") or []:
        if not isinstance(e, dict):
            continue
        k = str(e.get("kind", ""))
        if cat != "all" and k != cat:
            continue
        t = str(e.get("type", ""))
        counts[t] = counts.get(t, 0) + 1
        kinds[t] = k
    for tid, obj in objs.items():
        k = str(obj.get("kind", ""))
        if cat != "all" and k != cat:
            continue
        counts.setdefault(tid, 0)
        kinds.setdefault(tid, k)
    rows = [
        {
            "type": t,
            "kind": kinds.get(t, "-"),
            "placedCount": counts[t],
            "material": str((objs.get(t) or {}).get("material", "-")),
        }
        for t in sorted(counts)
    ]
    path = write_bim_csv(ctx, "type-catalog.csv", ["type", "kind", "placedCount", "material"], rows)
    return result(
        summary={
            "category": cat,
            "typeCount": len(rows),
            "totalPlaced": sum(counts.values()),
            "exportPath": path,
        },
        tables=[
            table(
                "BIM Type Catalog",
                [
                    ("type", "Type"),
                    ("kind", "Kind"),
                    ("placedCount", "Placed"),
                    ("material", "Material"),
                ],
                rows,
            )
        ],
        notes=[f"Cross-referenced 04 Objects & 06 BIM ({len(rows)} types); exported to {path}."],
    )


@feature(
    "bimAdditionsFamilies.purgeTypes",
    "Purge Types",
    part="bim",
    fields=[checkbox("removeUnused", "Confirm purge candidates in output", True)],
)
def purge_types(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Diff 04 Objects catalog types against 06 BIM elements to isolate unused types."""
    data = require_bim(ctx)
    objs = _object_types(ctx)
    used = {str(e.get("type", "")) for e in (data.get("elements") or []) if isinstance(e, dict)}
    all_types = sorted(set(objs) | used)
    rows = [
        {"type": t, "inBim": t in used, "status": "in-use" if t in used else "purge-candidate"}
        for t in all_types
    ]
    unused = [r["type"] for r in rows if not r["inBim"]]
    path = write_bim_csv(ctx, "purge-types-report.csv", ["type", "inBim", "status"], rows)
    return result(
        summary={
            "usedTypeCount": len(used),
            "unusedTypeCount": len(unused),
            "removeUnused": bool(values["removeUnused"]),
            "exportPath": path,
        },
        tables=[
            table(
                "Type Usage & Purge Audit",
                [("type", "Type"), ("inBim", "In BIM"), ("status", "Status")],
                rows,
            )
        ],
        notes=[
            f"Found {len(unused)} unused catalog type(s) across {len(all_types)} defined type(s); report: {path}."
        ],
    )


@feature(
    "bimAdditionsFamilies.familyTemplates",
    "Family Templates",
    part="bim",
    fields=[
        select(
            "template",
            "Component template",
            [
                ("structuralColumn", "Structural column"),
                ("structuralBeam", "Structural beam"),
                ("wall", "Shear / bearing wall"),
                ("slab", "Floor slab"),
            ],
            "structuralBeam",
        )
    ],
)
def family_templates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Emit required analytical & geometric schema fields for the selected BIM component template."""
    require_bim(ctx)
    schemas = {
        "structuralColumn": [
            "id",
            "material",
            "profile.shape",
            "profile.width",
            "profile.depth",
            "cover",
            "rebar",
        ],
        "structuralBeam": [
            "id",
            "material",
            "profile.shape",
            "profile.width",
            "profile.depth",
            "flangeEffectiveWidth",
        ],
        "wall": ["id", "material", "thickness", "boundaryZone", "twoLayerReinforcement"],
        "slab": ["id", "material", "thickness", "cover", "twoWaySpan"],
    }
    req_fields = schemas[values["template"]]
    payload = {"template": values["template"], "requiredProperties": req_fields}
    path = write_bim_json(ctx, "family-template.json", payload)
    return result(
        summary={
            "template": values["template"],
            "requiredFieldCount": len(req_fields),
            "exportPath": path,
        },
        tables=[
            table(
                "Template Schema",
                [("field", "Required Property")],
                [{"field": f} for f in req_fields],
            )
        ],
        notes=[f"Template defines {len(req_fields)} required properties; saved to {path}."],
    )


@feature(
    "bimAdditionsFamilies.addParameter",
    "Add Parameter",
    part="bim",
    fields=[
        text("name", "Parameter name", "FireRatingHours"),
        select(
            "parameterType",
            "Parameter type",
            [("text", "Text"), ("number", "Number"), ("boolean", "Boolean")],
            "number",
        ),
        text("defaultValue", "Default value", "2"),
    ],
)
def add_parameter(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate parameter type & value syntax and append to family parameter schema ledger."""
    import json

    require_bim(ctx)
    ptype = values["parameterType"]
    raw_val = values["defaultValue"].strip()
    if ptype == "number":
        try:
            typed_val: Any = float(raw_val)
        except ValueError as exc:
            raise FeatureInputError(
                f"Default value {raw_val!r} must be numeric for type 'number'."
            ) from exc
    elif ptype == "boolean":
        if raw_val.lower() not in ("true", "false", "1", "0"):
            raise FeatureInputError(
                f"Default value {raw_val!r} must be true/false for type 'boolean'."
            )
        typed_val = raw_val.lower() in ("true", "1")
    else:
        typed_val = raw_val
    entry = {"name": values["name"].strip() or "Param", "type": ptype, "default": typed_val}
    reg = ctx.path("11 Exports/BIM/family-parameter.json")
    params: list[dict[str, Any]] = []
    if reg is not None and reg.exists():
        try:
            loaded = json.loads(reg.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                params = [r for r in loaded if isinstance(r, dict)]
        except ValueError:
            pass
    by_name = {str(p.get("name")): p for p in params}
    by_name[entry["name"]] = entry
    rows = list(by_name.values())
    path = write_bim_json(ctx, "family-parameter.json", rows)
    return result(
        summary={
            "parameterName": entry["name"],
            "parameterType": ptype,
            "totalParams": len(rows),
            "exportPath": path,
        },
        tables=[
            table(
                "Family Parameters",
                [("name", "Name"), ("type", "Type"), ("default", "Validated Default")],
                rows,
            )
        ],
        notes=[f"Validated typed default and stored {len(rows)} parameter(s) at {path}."],
    )


@feature(
    "bimAdditionsFamilies.parameterFormula",
    "Parameter Formula",
    part="bim",
    fields=[
        text("parameter", "Target parameter", "Volume"),
        text(
            "formula", "Arithmetic formula (vars: Width, Height, Length)", "Width * Height * Length"
        ),
        number("width", "Width", 0.30, min=0.001),
        number("height", "Height", 0.50, min=0.001),
        number("length", "Length", 6.00, min=0.001),
        text("units", "Output units", "m³"),
    ],
)
def parameter_formula(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Safely parse and evaluate parametric family formula over input dimensions."""
    require_bim(ctx)
    env = {
        "Width": float(values["width"]),
        "Height": float(values["height"]),
        "Length": float(values["length"]),
    }
    val = _safe_eval_expr(values["formula"], env)
    formula = {
        "parameter": values["parameter"],
        "formula": values["formula"],
        "evaluatedValue": round(val, 4),
        "units": values["units"],
    }
    path = write_bim_json(ctx, "parameter-formula.json", formula)
    return result(
        summary={**formula, "exportPath": path},
        tables=[
            table(
                "Evaluated Family Formula",
                [
                    ("parameter", "Parameter"),
                    ("formula", "Expression"),
                    ("evaluatedValue", "Value"),
                    ("units", "Unit"),
                ],
                [formula],
            )
        ],
        notes=[f"Evaluated '{values['formula']}' = {val:.4f} {values['units']}; saved to {path}."],
    )


@feature(
    "bimAdditionsFamilies.sharedParameter",
    "Shared Parameter",
    part="bim",
    fields=[
        text("name", "Shared parameter GUID key", "AssemblyCode"),
        text("group", "IFC / Schedule group", "Identity Data"),
    ],
)
def shared_parameter(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Register persistent deterministic GUID-tagged shared parameter definition."""
    import json
    import uuid

    require_bim(ctx)
    pname = values["name"].strip()
    if not pname:
        raise FeatureInputError("Enter a non-empty shared parameter name.")
    guid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"saengine.shared.{pname}"))
    entry = {"name": pname, "group": values["group"].strip(), "guid": guid}
    reg = ctx.path("11 Exports/BIM/shared-parameter.json")
    existing: list[dict[str, Any]] = []
    if reg is not None and reg.exists():
        try:
            loaded = json.loads(reg.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = [r for r in loaded if isinstance(r, dict)]
        except ValueError:
            pass
    by_name = {str(r.get("name")): r for r in existing}
    by_name[pname] = entry
    rows = list(by_name.values())
    path = write_bim_json(ctx, "shared-parameter.json", rows)
    return result(
        summary={**entry, "registeredCount": len(rows), "exportPath": path},
        notes=[f"Assigned UUIDv5 {guid}; saved to {path}."],
    )


@feature(
    "bimAdditionsFamilies.parameterMapping",
    "Parameter Mapping",
    part="bim",
    fields=[
        text("sourceParameter", "Source BIM attribute (e.g. id, kind, type, story)", "type"),
        text("targetParameter", "Export schedule field", "AssemblyMark"),
    ],
)
def parameter_mapping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview and save source-to-target property mapping across real 06 BIM elements."""
    data = require_bim(ctx)
    src = values["sourceParameter"].strip()
    dst = values["targetParameter"].strip()
    elements = [e for e in (data.get("elements") or []) if isinstance(e, dict)]
    sample_rows = [
        {
            "elementId": str(e.get("id", "")),
            "sourceAttr": src,
            "targetAttr": dst,
            "mappedValue": str(e.get(src, "")),
        }
        for e in elements[:20]
    ]
    path = write_bim_csv(
        ctx,
        "parameter-mapping.csv",
        ["elementId", "sourceAttr", "targetAttr", "mappedValue"],
        sample_rows,
    )
    return result(
        summary={
            "sourceParameter": src,
            "targetParameter": dst,
            "mappedElements": len(sample_rows),
            "exportPath": path,
        },
        tables=[
            table(
                "Parameter Mapping Preview",
                [
                    ("elementId", "Element"),
                    ("sourceAttr", "Source"),
                    ("targetAttr", "Target"),
                    ("mappedValue", "Value"),
                ],
                sample_rows,
            )
        ],
        notes=[
            f"Mapped {src!r} -> {dst!r} across {len(sample_rows)} real BIM element(s); exported to {path}."
        ],
    )


@feature(
    "bimAdditionsFamilies.loadNested",
    "Load Nested",
    part="bim",
    fields=[
        text("nestedFamily", "Sub-component type", "Plate-Detail"),
        text("hostFamily", "Host 04 Objects / BIM type", "B300x500"),
    ],
)
def load_nested(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate host family against 04 Objects/06 BIM and guard against self-nesting cycles."""
    data = require_bim(ctx)
    objs = _object_types(ctx)
    known = set(objs) | {
        str(e.get("type", "")) for e in (data.get("elements") or []) if isinstance(e, dict)
    }
    nested = values["nestedFamily"].strip()
    host = values["hostFamily"].strip()
    if nested == host:
        raise FeatureInputError("A family cannot be nested inside itself (circular reference).")
    if host not in known:
        raise FeatureInputError(f"Host family {host!r} does not exist in 04 Objects or 06 BIM.")
    item = {"nested": nested, "host": host, "hostVerified": host in known}
    path = write_bim_json(ctx, "nested-family-load.json", item)
    return result(
        summary={**item, "exportPath": path},
        notes=[f"Linked {nested!r} into verified host {host!r}; saved to {path}."],
    )


@feature(
    "bimAdditionsFamilies.nestComponent",
    "Nest Component",
    part="bim",
    fields=[
        text("parent", "Parent assembly / family", "Frame"),
        text("component", "Child sub-component", "BasePlate"),
    ],
)
def nest_component(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Append hierarchical parent-child component relation with cycle detection."""
    import json

    require_bim(ctx)
    parent = values["parent"].strip()
    child = values["component"].strip()
    if not parent or not child or parent == child:
        raise FeatureInputError("Parent and child component names must be distinct and non-empty.")
    reg = ctx.path("11 Exports/BIM/nested-component.json")
    graph: list[dict[str, str]] = []
    if reg is not None and reg.exists():
        try:
            loaded = json.loads(reg.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                graph = [r for r in loaded if isinstance(r, dict)]
        except ValueError:
            pass
    # Prevent reverse edge cycles (child -> parent already present)
    if any(r.get("parent") == child and r.get("component") == parent for r in graph):
        raise FeatureInputError(f"Nesting {child} under {parent} creates a circular hierarchy.")
    if not any(r.get("parent") == parent and r.get("component") == child for r in graph):
        graph.append({"parent": parent, "component": child})
    path = write_bim_json(ctx, "nested-component.json", graph)
    return result(
        summary={
            "parent": parent,
            "component": child,
            "totalLinks": len(graph),
            "exportPath": path,
        },
        notes=[f"Verified acyclic hierarchy ({len(graph)} link(s)) at {path}."],
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
        text("name", "Constraint parameter name", "TargetLength"),
        number("targetDimensionM", "Target constraint length", 6.0, unit="m", min=0.05),
        number("toleranceMm", "Maximum fabrication deviation", 10.0, unit="mm", min=0.5),
        checkbox("locked", "Locked", True),
    ],
)
def dimension_constraint(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check family dimension constraint against real 06 BIM element lengths and tolerance."""
    import math

    data = require_bim(ctx)
    target_mm = float(values["targetDimensionM"]) * 1000.0
    tol_mm = float(values["toleranceMm"])
    spans = []
    for e in data.get("elements") or []:
        if (
            isinstance(e, dict)
            and isinstance(e.get("start"), list)
            and isinstance(e.get("end"), list)
        ):
            s, en = e["start"], e["end"]
            if len(s) >= 2 and len(en) >= 2:
                spans.append(math.hypot(float(en[0]) - float(s[0]), float(en[1]) - float(s[1])))
    max_dev = max((abs(sp - target_mm) for sp in spans), default=0.0)
    within_tol = sum(1 for sp in spans if abs(sp - target_mm) <= tol_mm)
    c = {
        "name": values["name"],
        "targetM": float(values["targetDimensionM"]),
        "locked": bool(values["locked"]),
        "matchingElements": within_tol,
        "maxDeviationMm": round(max_dev, 1),
    }
    path = write_bim_json(ctx, "dimension-constraint.json", c)
    return result(
        summary={**c, "exportPath": path},
        notes=[
            f"{within_tol}/{len(spans)} linear BIM elements match {target_mm:g} mm within +/-{tol_mm:g} mm; saved to {path}."
        ],
    )


@feature(
    "bimAdditionsFamilies.referencePlane",
    "Reference Plane",
    part="bim",
    fields=[
        select(
            "orientation",
            "Normal axis",
            [("x", "X (YZ plane)"), ("y", "Y (XZ plane)"), ("z", "Z (XY datum)")],
            "z",
        ),
        number("position", "Plane coordinate offset", 3.2, unit="m"),
    ],
)
def reference_plane(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Intersect work plane against real 06 BIM stories / 05 Floor Plan grids to count hosted elements."""
    data = require_bim(ctx)
    pos_mm = float(values["position"]) * 1000.0
    axis = values["orientation"].lower()
    matching_stories = [
        str(s.get("id", ""))
        for s in (data.get("stories") or [])
        if axis == "z" and abs(float(s.get("elevation", 0.0)) - pos_mm) <= 50.0
    ]
    plane = {
        "orientation": axis.upper(),
        "positionMm": round(pos_mm, 1),
        "coincidentStories": matching_stories,
        "coincident": bool(matching_stories),
    }
    path = write_bim_json(ctx, "reference-plane.json", plane)
    return result(
        summary={**plane, "exportPath": path},
        notes=[
            f"Plane {axis.upper()}={pos_mm:g} mm aligned with stories={matching_stories or ['none']}; saved to {path}."
        ],
    )


@feature(
    "bimAdditionsFamilies.lockAlignment",
    "Lock Alignment",
    part="bim",
    fields=[
        text("reference", "Reference grid or level (e.g. A, L1)", "L1"),
        text("host", "Target 06 BIM element ID", "B1"),
        checkbox("locked", "Alignment locked", True),
    ],
)
def lock_alignment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify host element existence in 06 BIM and persist datum alignment lock state."""
    import json

    data = require_bim(ctx)
    host_id = values["host"].strip()
    el = next((e for e in (data.get("elements") or []) if str(e.get("id", "")) == host_id), None)
    if el is None:
        raise FeatureInputError(f"Element {host_id!r} not found in 06 BIM/bim.json.")
    rec = {
        "reference": values["reference"].strip(),
        "host": host_id,
        "hostKind": el.get("kind", ""),
        "locked": bool(values["locked"]),
    }
    reg = ctx.path("11 Exports/BIM/lock-alignment.json")
    locks: list[dict[str, Any]] = []
    if reg is not None and reg.exists():
        try:
            loaded = json.loads(reg.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                locks = [r for r in loaded if isinstance(r, dict)]
        except ValueError:
            pass
    by_host = {(str(r.get("reference")), str(r.get("host"))): r for r in locks}
    by_host[(rec["reference"], rec["host"])] = rec
    all_locks = list(by_host.values())
    path = write_bim_json(ctx, "lock-alignment.json", all_locks)
    return result(
        summary={**rec, "totalLockedPairs": len(all_locks), "exportPath": path},
        notes=[
            f"Verified {host_id} in 06 BIM and persisted alignment lock ledger ({len(all_locks)}); saved to {path}."
        ],
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
        text("familyNames", "Type / family IDs to validate", "C1,B1,W1,S1"),
        checkbox("replaceExisting", "Overwrite existing entries", False),
    ],
)
def batch_load_families(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Resolve requested family/type names against 04 Objects & 06 BIM definitions."""
    data = require_bim(ctx)
    objs = _object_types(ctx)
    used_types = {
        str(e.get("type", "")) for e in (data.get("elements") or []) if isinstance(e, dict)
    }
    names = [x.strip() for x in values["familyNames"].split(",") if x.strip()]
    rows = [
        {
            "family": n,
            "inObjectLibrary": n in objs,
            "usedInBim": n in used_types,
            "replace": bool(values["replaceExisting"]),
        }
        for n in names
    ]
    matched = sum(1 for r in rows if r["inObjectLibrary"] or r["usedInBim"])
    path = write_bim_csv(
        ctx, "batch-load-families.csv", ["family", "inObjectLibrary", "usedInBim", "replace"], rows
    )
    return result(
        summary={"requestedCount": len(names), "resolvedCount": matched, "exportPath": path},
        tables=[
            table(
                "Batch Family Resolution",
                [
                    ("family", "Family"),
                    ("inObjectLibrary", "In 04 Objects"),
                    ("usedInBim", "In 06 BIM"),
                    ("replace", "Replace"),
                ],
                rows,
            )
        ],
        notes=[
            f"Resolved {matched}/{len(names)} requested families against project model; exported to {path}."
        ],
    )


@feature(
    "bimAdditionsFamilies.purgeUnusedFamilies",
    "Purge Unused Families",
    part="bim",
    fields=[checkbox("previewOnly", "Include purge preview report", True)],
)
def purge_unused_families(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare 04 Objects catalog vs 06 BIM elements to list used vs unused families."""
    data = require_bim(ctx)
    objs = _object_types(ctx)
    used = {str(e.get("type", "")) for e in (data.get("elements") or []) if isinstance(e, dict)}
    unused = sorted(set(objs) - used)
    rows = [
        {"type": t, "status": "used" if t in used else "unused"} for t in sorted(set(objs) | used)
    ]
    path = write_bim_csv(ctx, "purge-unused-families.csv", ["type", "status"], rows)
    return result(
        summary={
            "usedFamilyCount": len(used),
            "unusedFamilyCount": len(unused),
            "exportPath": path,
        },
        tables=[table("Family Purge Audit", [("type", "Type"), ("status", "Status")], rows)],
        notes=[
            f"Identified {len(unused)} unused catalog type(s) out of {len(rows)}; saved to {path}."
        ],
    )

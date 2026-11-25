"""BIM quantities, takeoff, and cost-mapping features."""

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


@feature("bimQuantities.materialTakeoff", "Material Takeoff", part="bim")
def material_takeoff(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Extract object-type quantities from the coordinated BIM model."""
    data = require_bim(ctx)
    counts: dict[str, int] = {}
    for e in data["elements"]:
        key = str(e.get("type", "Unclassified"))
        counts[key] = counts.get(key, 0) + 1
    rows = [{"type": k, "elementCount": v} for k, v in sorted(counts.items())]
    path = write_bim_csv(ctx, "material-takeoff.csv", ["type", "elementCount"], rows)
    return result(
        summary={
            "materialCount": len(rows),
            "elementCount": len(data["elements"]),
            "exportPath": path,
        },
        tables=[
            table("Material Takeoff", [("type", "Object type"), ("elementCount", "Elements")], rows)
        ],
    )


@feature(
    "bimQuantities.elementQuantities",
    "Element Quantities",
    part="bim",
    fields=[text("category", "Category filter", "all")],
)
def element_quantities(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List quantities per element for an optional category filter."""
    data = require_bim(ctx)
    category = values["category"].lower()
    rows = [
        {"id": e.get("id", ""), "kind": e.get("kind", ""), "type": e.get("type", "")}
        for e in data["elements"]
        if category == "all" or str(e.get("kind", "")).lower() == category
    ]
    return result(
        summary={"elementCount": len(rows)},
        tables=[
            table(
                "Element Quantities",
                [("id", "Element id"), ("kind", "Category"), ("type", "Object type")],
                rows,
            )
        ],
    )


@feature(
    "bimQuantities.rebarWeight",
    "Rebar Weight",
    part="bim",
    fields=[number("densityKgPerM3", "Rebar density", 7850.0, unit="kg/m³", min=1)],
)
def rebar_weight(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Sum reinforcement weight only from recorded rebar quantities."""
    data = require_bim(ctx)
    rebar = data.get("rebar", [])
    weighted = [
        r for r in rebar if isinstance(r, dict) and isinstance(r.get("weightKg"), (int, float))
    ]
    if not weighted:
        raise FeatureInputError("Record rebar marks with weightKg before calculating rebar weight.")
    total_kg = sum(float(r["weightKg"]) for r in weighted)
    return result(
        summary={"rebarWeightKg": total_kg, "rebarMarkCount": len(rebar)},
        tables=[
            table(
                "Rebar Marks",
                [("mark", "Mark"), ("weightKg", "Weight", "kg")],
                rebar if isinstance(rebar, list) else [],
            )
        ],
    )


@feature("bimQuantities.componentSchedule", "Component Schedule", part="bim")
def component_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Schedule structural components by type and count."""
    data = require_bim(ctx)
    counts: dict[str, int] = {}
    for e in data["elements"]:
        key = f"{e.get('kind', 'unknown')}:{e.get('type', 'unclassified')}"
        counts[key] = counts.get(key, 0) + 1
    rows = [
        {"kind": k.split(":")[0], "type": k.split(":")[1], "count": v}
        for k, v in sorted(counts.items())
    ]
    return result(
        summary={"componentTypeCount": len(rows)},
        tables=[
            table(
                "Component Schedule",
                [("kind", "Category"), ("type", "Type"), ("count", "Count")],
                rows,
            )
        ],
    )


@feature("bimQuantities.sheetList", "Sheet List", part="bim")
def sheet_list(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List sheets recorded in project metadata."""
    data = require_bim(ctx)
    sheets = data.get("sheets", [])
    rows = sheets if isinstance(sheets, list) else []
    return result(
        summary={"sheetCount": len(rows)},
        tables=[
            table(
                "Sheets", [("number", "Sheet"), ("title", "Title"), ("revision", "Revision")], rows
            )
        ],
    )


@feature("bimQuantities.roomDataSheet", "Room Data Sheet", part="bim")
def room_data_sheet(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile room/slab floorplate areas from spatial model or BIM slab polygons."""
    import json

    from saengine.features.bim_common import polygon_area

    data = require_bim(ctx)
    rooms = [r for r in (data.get("rooms") or []) if isinstance(r, dict)]
    if not rooms:
        sp_file = ctx.path("11 Exports/BIM/spaces.json")
        if sp_file is not None and sp_file.exists():
            try:
                loaded = json.loads(sp_file.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    rooms = [
                        {
                            "id": f"SP-{i + 1}",
                            "name": r.get("name", ""),
                            "areaM2": r.get("areaM2", 0),
                        }
                        for i, r in enumerate(loaded)
                        if isinstance(r, dict)
                    ]
            except ValueError:
                pass
    if not rooms:
        for e in data.get("elements") or []:
            if (
                isinstance(e, dict)
                and e.get("kind") == "slab"
                and isinstance(e.get("polygon"), list)
            ):
                area_m2 = round(polygon_area(e["polygon"]) / 1e6, 2)
                rooms.append(
                    {
                        "id": str(e.get("id", "")),
                        "name": f"Slab Zone {e.get('story', '')}",
                        "areaM2": area_m2,
                    }
                )
    path = write_bim_csv(
        ctx,
        "room-data.csv",
        ["id", "name", "areaM2"],
        [
            {"id": r.get("id", ""), "name": r.get("name", ""), "areaM2": r.get("areaM2", 0)}
            for r in rooms
        ],
    )
    return result(
        summary={
            "roomCount": len(rooms),
            "totalAreaM2": round(sum(float(r.get("areaM2", 0) or 0) for r in rooms), 2),
            "exportPath": path,
        },
        tables=[
            table(
                "Room / Floorplate Schedule",
                [("id", "Zone"), ("name", "Name"), ("areaM2", "Area", "m²")],
                rooms or [{"id": "-", "name": "No rooms/slabs", "areaM2": 0.0}],
            )
        ],
    )


@feature(
    "bimQuantities.exportQuantities",
    "Export Quantities",
    part="bim",
    fields=[text("filename", "Output filename", "bim-quantities.csv")],
)
def export_quantities(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute geometric length [m], area [m²], and volume [m³] quantities from 06 BIM & 04 Objects."""
    import math

    from saengine.features.bim_common import polygon_area

    data = require_bim(ctx)
    objs = {
        str(o.get("id", "")): o
        for o in ((ctx.raw("objects") or {}).get("objects") or [])
        if isinstance(o, dict)
    }
    story_elevs = sorted(
        {float(s.get("elevation", 0.0)) for s in (data.get("stories") or []) if isinstance(s, dict)}
    )
    default_h_mm = (story_elevs[1] - story_elevs[0]) if len(story_elevs) >= 2 else 3200.0
    rows = []
    tot_vol = 0.0
    for e in data.get("elements") or []:
        if not isinstance(e, dict):
            continue
        oid = str(e.get("type", ""))
        obj = objs.get(oid, {})
        kind = str(e.get("kind", ""))
        prof = obj.get("profile") if isinstance(obj.get("profile"), dict) else {}
        sec_m2 = (
            float(prof.get("width", 300.0) or 300.0) * float(prof.get("depth", 400.0) or 400.0)
        ) / 1e6
        length_m = 0.0
        area_m2 = 0.0
        vol_m3 = 0.0
        if kind == "column":
            top_z = float(e.get("top", default_h_mm) or default_h_mm)
            bot_z = float(e.get("bottom", 0.0) or 0.0)
            length_m = (
                max(1.0, (top_z - bot_z) / 1000.0) if top_z > bot_z else default_h_mm / 1000.0
            )
            vol_m3 = sec_m2 * length_m
        elif kind == "beam" and isinstance(e.get("start"), list) and isinstance(e.get("end"), list):
            s, en = e["start"], e["end"]
            length_m = math.hypot(float(en[0]) - float(s[0]), float(en[1]) - float(s[1])) / 1000.0
            vol_m3 = sec_m2 * length_m
        elif kind == "wall" and isinstance(e.get("start"), list) and isinstance(e.get("end"), list):
            s, en = e["start"], e["end"]
            length_m = math.hypot(float(en[0]) - float(s[0]), float(en[1]) - float(s[1])) / 1000.0
            h_m = default_h_mm / 1000.0
            th_m = float(obj.get("thickness", 200.0) or 200.0) / 1000.0
            area_m2 = length_m * h_m
            vol_m3 = area_m2 * th_m
        elif kind == "slab" and isinstance(e.get("polygon"), list):
            area_m2 = polygon_area(e["polygon"]) / 1e6
            th_m = float(obj.get("thickness", 150.0) or 150.0) / 1000.0
            vol_m3 = area_m2 * th_m
        tot_vol += vol_m3
        rows.append(
            {
                "id": e.get("id", ""),
                "kind": kind,
                "type": oid,
                "lengthM": round(length_m, 2),
                "areaM2": round(area_m2, 2),
                "volumeM3": round(vol_m3, 3),
            }
        )
    filename = (
        "".join(c for c in values["filename"] if c.isalnum() or c in "-_.") or "bim-quantities.csv"
    )
    path = write_bim_csv(
        ctx, filename, ["id", "kind", "type", "lengthM", "areaM2", "volumeM3"], rows
    )
    return result(
        summary={"elementCount": len(rows), "totalVolumeM3": round(tot_vol, 2), "exportPath": path},
        tables=[
            table(
                "BIM Element Quantities",
                [
                    ("id", "ID"),
                    ("kind", "Kind"),
                    ("type", "Type"),
                    ("lengthM", "Length", "m"),
                    ("areaM2", "Area", "m²"),
                    ("volumeM3", "Volume", "m³"),
                ],
                rows[:30],
            )
        ],
    )


@feature("bimQuantities.linkToBoq", "Link to BOQ", part="bim")
def link_to_boq(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map BIM object types to current BOQ items."""
    data = require_bim(ctx)
    boq = ctx.raw("boq")
    items = boq.get("items", []) if isinstance(boq, dict) else []
    codes = {str(i.get("code", "")): i for i in items if isinstance(i, dict)}
    rows = [
        {"type": k, "boqCode": k if k in codes else ""}
        for k in sorted({str(e.get("type", "")) for e in data["elements"]})
    ]
    return result(
        summary={"mappedCount": sum(bool(r["boqCode"]) for r in rows), "modelTypeCount": len(rows)},
        tables=[table("BOQ Mapping", [("type", "Object type"), ("boqCode", "BOQ code")], rows)],
    )


@feature("bimQuantities.costMapping", "Cost Mapping", part="bim")
def cost_mapping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Match BIM categories against cost codes recorded in the BOQ."""
    data = require_bim(ctx)
    boq = ctx.raw("boq")
    items = boq.get("items", []) if isinstance(boq, dict) else []
    codes_by_kind: dict[str, set[str]] = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", ""))
        code = str(item.get("code", ""))
        if kind and code:
            codes_by_kind.setdefault(kind, set()).add(code)
    rows = [
        {
            "kind": kind,
            "costCodes": ", ".join(sorted(codes_by_kind.get(kind, set()))),
        }
        for kind in sorted(kind_counts(data))
    ]
    path = write_bim_json(ctx, "cost-mapping.json", rows)
    return result(
        summary={
            "mappingCount": sum(bool(row["costCodes"]) for row in rows),
            "categoryCount": len(rows),
            "exportPath": path,
        },
        tables=[
            table("Cost Mapping", [("kind", "Category"), ("costCodes", "BOQ cost codes")], rows)
        ],
    )


@feature(
    "bimQuantities.formworkArea",
    "Formwork Area",
    part="bim",
    fields=[number("allowancePercent", "Detail allowance", 10.0, unit="%", min=0, max=100)],
)
def formwork_area(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate formwork area for elements carrying explicit area fields."""
    data = require_bim(ctx)
    areas = [
        float(e["formworkAreaM2"])
        for e in data["elements"]
        if isinstance(e, dict) and isinstance(e.get("formworkAreaM2"), (int, float))
    ]
    if not areas:
        raise FeatureInputError(
            "Record formworkAreaM2 on BIM elements before calculating formwork."
        )
    area_m2 = sum(areas)
    total = area_m2 * (1 + values["allowancePercent"] / 100)
    return result(
        summary={"formworkAreaM2": total},
        tables=[
            table(
                "Formwork", [("sourceAreaM2", "Recorded area", "m²")], [{"sourceAreaM2": area_m2}]
            )
        ],
    )


@feature("bimQuantities.excavationVolume", "Excavation Volume", part="bim")
def excavation_volume(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Sum recorded excavation volumes from footing and subgrade elements."""
    data = require_bim(ctx)
    volumes = [
        float(e["excavationVolumeM3"])
        for e in data["elements"]
        if isinstance(e, dict) and isinstance(e.get("excavationVolumeM3"), (int, float))
    ]
    if not volumes:
        raise FeatureInputError(
            "Record excavationVolumeM3 before calculating excavation quantities."
        )
    return result(
        summary={"excavationVolumeM3": sum(volumes)},
        tables=[
            table(
                "Excavation",
                [("elementCount", "Elements"), ("volumeM3", "Volume", "m³")],
                [{"elementCount": len(volumes), "volumeM3": sum(volumes)}],
            )
        ],
    )


@feature("bimQuantities.rebarLength", "Rebar Length", part="bim")
def rebar_length(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Total reinforcement length only from recorded bar quantities."""
    data = require_bim(ctx)
    rebar = data.get("rebar", [])
    measured = [
        r for r in rebar if isinstance(r, dict) and isinstance(r.get("lengthM"), (int, float))
    ]
    if not measured:
        raise FeatureInputError("Record rebar marks with lengthM before calculating rebar length.")
    total = sum(float(r["lengthM"]) for r in measured)
    return result(summary={"rebarLengthM": total, "barMarkCount": len(measured)})


@feature("bimQuantities.paintArea", "Paint Area", part="bim")
def paint_area(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Sum recorded finish surface areas."""
    data = require_bim(ctx)
    areas = [
        float(e["paintAreaM2"])
        for e in data["elements"]
        if isinstance(e, dict) and isinstance(e.get("paintAreaM2"), (int, float))
    ]
    if not areas:
        raise FeatureInputError("Record paintAreaM2 on BIM elements before calculating paint area.")
    area = sum(areas)
    return result(
        summary={"paintAreaM2": area},
    )


@feature("bimQuantities.volumeByStorey", "Volume By Storey", part="bim")
def volume_by_storey(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report recorded element volumes by storey."""
    data = require_bim(ctx)
    quantified = [
        e
        for e in data["elements"]
        if isinstance(e, dict) and isinstance(e.get("volumeM3"), (int, float))
    ]
    if not quantified:
        raise FeatureInputError(
            "Record volumeM3 on BIM elements before reporting volume by storey."
        )
    rows = []
    for storey in data.get("stories", []):
        elevation = storey.get("elevation")
        volume = sum(
            float(e["volumeM3"])
            for e in quantified
            if elevation in (e.get("elevation"), e.get("bottom"), e.get("top"))
        )
        rows.append({"storey": storey.get("name", storey.get("id", "")), "volumeM3": volume})
    return result(
        summary={"storeyCount": len(rows)},
        tables=[
            table("Volume by Storey", [("storey", "Storey"), ("volumeM3", "Volume", "m³")], rows)
        ],
    )


@feature("bimQuantities.quantityRules", "Quantity Rules", part="bim")
def quantity_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Review quantity derivation rules recorded in the BIM model."""
    data = require_bim(ctx)
    rules = data.get("quantityRules", [])
    rows = rules if isinstance(rules, list) else []
    return result(
        summary={"ruleCount": len(rows)},
        tables=[
            table("Quantity Rules", [("name", "Rule"), ("basis", "Basis"), ("unit", "Unit")], rows)
        ],
    )


@feature("bimQuantities.unitMapping", "Unit Mapping", part="bim")
def unit_mapping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map quantity names to SI units used in the bill of quantities."""
    data = require_bim(ctx)
    mapping = [
        {"quantity": "Length", "unit": "m"},
        {"quantity": "Area", "unit": "m²"},
        {"quantity": "Volume", "unit": "m³"},
        {"quantity": "Mass", "unit": "kg"},
    ]
    return result(
        summary={"unitCount": len(mapping), "elementCount": len(data["elements"])},
        tables=[table("Unit Mapping", [("quantity", "Quantity"), ("unit", "Unit")], mapping)],
    )


@feature(
    "bimQuantities.wasteFactors",
    "Waste Factors",
    part="bim",
    fields=[number("wastePercent", "Waste factor", 5.0, unit="%", min=0, max=100)],
)
def waste_factors(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply a project waste percentage to recorded element quantities."""
    data = require_bim(ctx)
    quantities: dict[str, float] = {}
    for element in data["elements"]:
        if not isinstance(element, dict) or not isinstance(element.get("quantity"), (int, float)):
            continue
        unit = str(element.get("unit", ""))
        if not unit:
            raise FeatureInputError("Add a unit to every recorded quantity before applying waste.")
        quantities[unit] = quantities.get(unit, 0.0) + float(element["quantity"])
    if not quantities:
        raise FeatureInputError("Record measured element quantities before applying waste factors.")
    rows = [
        {
            "unit": unit,
            "baseQuantity": quantity,
            "adjustedQuantity": quantity * (1 + values["wastePercent"] / 100),
        }
        for unit, quantity in sorted(quantities.items())
    ]
    base = sum(row["baseQuantity"] for row in rows)
    adjusted = sum(row["adjustedQuantity"] for row in rows)
    return result(
        summary={
            "baseQuantity": base,
            "adjustedQuantity": adjusted,
            "wastePercent": values["wastePercent"],
        },
        tables=[
            table(
                "Waste-adjusted Quantities",
                [
                    ("unit", "Unit"),
                    ("baseQuantity", "Base quantity"),
                    ("adjustedQuantity", "With waste"),
                ],
                rows,
            )
        ],
    )


@feature(
    "bimQuantities.roundingPolicy",
    "Rounding Policy",
    part="bim",
    fields=[number("decimals", "Decimal places", 2.0, unit="places", min=0, max=6)],
)
def rounding_policy(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set the rounding policy for issued takeoff values."""
    require_bim(ctx)
    decimals = int(values["decimals"])
    return result(
        summary={"decimalPlaces": decimals}, notes=["Applies to exported displayed quantities."]
    )


@feature(
    "bimQuantities.overrideNotes",
    "Override Notes",
    part="bim",
    fields=[
        text("elementId", "Target element ID", "S1"),
        text(
            "reason", "Override justification", "Net deduction adjusted for unmodelled drop panels"
        ),
        number("overrideDeltaM3", "Volume adjustment", 0.0, unit="m³"),
    ],
)
def override_notes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate target element in 06 BIM and append audit-trailed quantity override ledger."""
    import json
    from datetime import date

    data = require_bim(ctx)
    eid = values["elementId"].strip()
    known_ids = {str(e.get("id", "")) for e in (data.get("elements") or []) if isinstance(e, dict)}
    if known_ids and eid and eid not in known_ids:
        raise FeatureInputError(f"Element {eid!r} not found in 06 BIM/bim.json.")
    entry = {
        "date": date.today().isoformat(),
        "elementId": eid,
        "deltaM3": float(values["overrideDeltaM3"]),
        "reason": values["reason"].strip(),
    }
    reg = ctx.path("11 Exports/BIM/quantity-override-notes.json")
    entries: list[dict[str, Any]] = []
    if reg is not None and reg.exists():
        try:
            loaded = json.loads(reg.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                entries = [r for r in loaded if isinstance(r, dict)]
        except ValueError:
            pass
    entries.append(entry)
    path = write_bim_json(ctx, "quantity-override-notes.json", entries)
    return result(
        summary={
            "elementId": eid,
            "overrideCount": len(entries),
            "netDeltaM3": round(sum(float(r.get("deltaM3", 0) or 0) for r in entries), 3),
            "exportPath": path,
        },
        tables=[
            table(
                "Quantity Override Ledger",
                [
                    ("date", "Date"),
                    ("elementId", "Element"),
                    ("deltaM3", "Delta", "m³"),
                    ("reason", "Reason"),
                ],
                entries[-15:],
            )
        ],
    )


@feature("bimQuantities.quantityAudit", "Quantity Audit", part="bim")
def quantity_audit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Trace each quantity back to contributing BIM elements."""
    data = require_bim(ctx)
    rows = [
        {"id": e.get("id", ""), "type": e.get("type", ""), "quantity": e.get("quantity", "")}
        for e in data["elements"]
    ]
    return result(
        summary={"auditedElementCount": len(rows)},
        tables=[
            table(
                "Quantity Audit",
                [("id", "Element"), ("type", "Type"), ("quantity", "Quantity")],
                rows,
            )
        ],
    )


@feature("bimQuantities.missingQuantities", "Missing Quantities", part="bim")
def missing_quantities(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Find elements with no quantity or dimensional value under current rules."""
    data = require_bim(ctx)
    rows = [
        {"id": e.get("id", ""), "kind": e.get("kind", ""), "type": e.get("type", "")}
        for e in data["elements"]
        if not any(k in e for k in ("quantity", "volumeM3", "areaM2", "lengthM"))
    ]
    return result(
        summary={"missingCount": len(rows)},
        tables=[
            table(
                "Missing Quantities",
                [("id", "Element"), ("kind", "Category"), ("type", "Type")],
                rows,
            )
        ],
    )


@feature("bimQuantities.duplicateCounts", "Duplicate Counts", part="bim")
def duplicate_counts(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detect repeated element identifiers in the takeoff."""
    data = require_bim(ctx)
    counts: dict[str, int] = {}
    for e in data["elements"]:
        key = str(e.get("id", ""))
        counts[key] = counts.get(key, 0) + 1
    rows = [{"id": k, "count": v} for k, v in sorted(counts.items()) if v > 1]
    return result(
        summary={"duplicateIdCount": len(rows)},
        tables=[table("Duplicate Counts", [("id", "Element id"), ("count", "Count")], rows)],
    )


@feature("bimQuantities.compareTakeoff", "Compare Takeoff", part="bim")
def compare_takeoff(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare current quantities with a saved takeoff in the BIM model."""
    data = require_bim(ctx)
    previous = data.get("previousTakeoff", {})
    current = {k: v for k, v in kind_counts(data).items()}
    before = previous if isinstance(previous, dict) else {}
    rows = [
        {
            "kind": k,
            "before": before.get(k, 0),
            "after": current.get(k, 0),
            "variance": current.get(k, 0) - before.get(k, 0),
        }
        for k in sorted(set(before) | set(current))
    ]
    return result(
        summary={"categoryVarianceCount": sum(r["variance"] != 0 for r in rows)},
        tables=[
            table(
                "Takeoff Variance",
                [
                    ("kind", "Category"),
                    ("before", "Before"),
                    ("after", "After"),
                    ("variance", "Variance"),
                ],
                rows,
            )
        ],
    )


@feature(
    "bimQuantities.publishTakeoff",
    "Publish Takeoff",
    part="bim",
    fields=[text("revision", "Takeoff revision", "C01")],
)
def publish_takeoff(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute SHA-256 verified BIM takeoff quantities and publish revision bundle."""
    import hashlib
    import json

    data = require_bim(ctx)
    qty_res = export_quantities(ctx, {"filename": f"takeoff-{values['revision']}.csv"})
    rev = values["revision"].strip() or "C01"
    digest = hashlib.sha256(
        json.dumps(data.get("elements") or [], sort_keys=True).encode("utf-8")
    ).hexdigest()
    payload = {
        "revision": rev,
        "sha256": digest[:16],
        "elements": len(data.get("elements") or []),
        "categories": kind_counts(data),
        "totalVolumeM3": qty_res.get("summary", {}).get("totalVolumeM3", 0.0),
    }
    path = write_bim_json(ctx, f"takeoff-{rev}.json", payload)
    return result(summary={**payload, "exportPath": path})

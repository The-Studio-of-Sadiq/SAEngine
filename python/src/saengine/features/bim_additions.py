"""BIM additions, placement and coordinated element feature buttons."""

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
from saengine.features.bim_common import element_rows, require_bim, write_bim_csv, write_bim_json


@feature(
    "bimAdditions.addStructuralMember",
    "Add Structural Member",
    part="bim",
    fields=[
        select(
            "kind",
            "Member kind",
            [("beam", "Beam"), ("column", "Column"), ("brace", "Brace")],
            "beam",
        ),
        text("type", "Member type / profile", "B300x500"),
        number("length", "Clear member length", 6.0, unit="m", min=0.2),
    ],
)
def add_structural_member(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate member profile against 04 Objects, compute section mass & self-weight, and queue proposal."""
    import json
    import re

    data = require_bim(ctx)
    raw_obj = ctx.raw("objects") or {}
    obj_ids = {str(o.get("id", "")) for o in (raw_obj.get("objects") or []) if isinstance(o, dict)}
    type_name = values["type"].strip()
    in_catalog = type_name in obj_ids
    dims = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", type_name)]
    b_mm, h_mm = (dims[0], dims[1]) if len(dims) >= 2 else (300.0, 500.0)
    area_m2 = (b_mm * h_mm) / 1e6
    vol_m3 = area_m2 * float(values["length"])
    density = 2400.0  # kg/m3 RC default
    mass_kg = vol_m3 * density
    member = {
        "id": f"M{len(element_rows(data)) + 1}",
        "kind": values["kind"],
        "type": type_name,
        "inObjectLibrary": in_catalog,
        "lengthM": float(values["length"]),
        "volumeM3": round(vol_m3, 3),
        "estimatedMassKg": round(mass_kg, 0),
        "selfWeightKnPerM": round(area_m2 * 24.0, 2),
    }
    reg_file = ctx.path("11 Exports/BIM/structural-member.json")
    existing: list[dict[str, Any]] = []
    if reg_file is not None and reg_file.exists():
        try:
            loaded = json.loads(reg_file.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = [r for r in loaded if isinstance(r, dict)]
        except ValueError:
            pass
    existing.append(member)
    path = write_bim_json(ctx, "structural-member.json", existing)
    return result(
        summary={
            "memberId": member["id"],
            "memberKind": values["kind"],
            "volumeM3": member["volumeM3"],
            "selfWeightKnPerM": member["selfWeightKnPerM"],
            "exportPath": path,
        },
        tables=[
            table(
                "Proposed Structural Member",
                [
                    ("id", "ID"),
                    ("kind", "Kind"),
                    ("type", "Type"),
                    ("volumeM3", "Vol", "m³"),
                    ("selfWeightKnPerM", "SW", "kN/m"),
                ],
                existing[-10:],
            )
        ],
        notes=[
            f"Profile {b_mm:g}x{h_mm:g} mm ({'in 04 Objects' if in_catalog else 'parametric'}); saved to {path}."
        ],
    )


@feature(
    "bimAdditions.addOpening",
    "Add Opening",
    part="bim",
    fields=[
        select("hostKind", "Host", [("slab", "Slab"), ("wall", "Wall")], "slab"),
        number("width", "Opening width", 1.0, unit="m", min=0.1),
        number("height", "Opening height", 1.0, unit="m", min=0.1),
    ],
)
def add_opening(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Cuts a coordinated opening through host elements."""
    require_bim(ctx)
    opening = {
        "id": "O_NEW",
        "hostKind": values["hostKind"],
        "widthMm": values["width"] * 1000,
        "heightMm": values["height"] * 1000,
    }
    path = write_bim_json(ctx, "opening-proposal.json", opening)
    return result(
        summary={
            "openingId": opening["id"],
            "widthM": values["width"],
            "heightM": values["height"],
            "exportPath": path,
        },
        tables=[
            table(
                "Opening Proposal",
                [
                    ("id", "Opening id"),
                    ("hostKind", "Host"),
                    ("widthMm", "Width [mm]", "mm"),
                    ("heightMm", "Height [mm]", "mm"),
                ],
                [opening],
            )
        ],
        notes=[
            "A coordinated proposal is exported; source geometry is unchanged.",
            f"Export: {path}",
        ],
    )


@feature(
    "bimAdditions.addEquipment",
    "Add Equipment",
    part="bim",
    fields=[
        text("name", "Equipment name", "Pump P1"),
        number("clearance", "Required clearance", 0.75, unit="m", min=0),
        number("load", "Equipment load", 2.0, unit="kN", min=0),
    ],
)
def add_equipment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Places plant or equipment with clearances."""
    require_bim(ctx)
    item = {
        "name": values["name"],
        "clearanceMm": values["clearance"] * 1000,
        "loadKn": values["load"],
    }
    path = write_bim_json(ctx, "equipment-proposal.json", item)
    return result(
        summary={
            "equipmentName": values["name"],
            "clearanceM": values["clearance"],
            "loadKn": values["load"],
            "exportPath": path,
        },
        notes=["Clearance is a spatial reservation, not a collision result.", f"Export: {path}"],
    )


@feature(
    "bimAdditions.addRebarSet",
    "Add Rebar Set",
    part="bim",
    fields=[
        select(
            "host",
            "Concrete host",
            [("beam", "Beam"), ("column", "Column"), ("slab", "Slab"), ("wall", "Wall")],
            "beam",
        ),
        number("diameter", "Bar diameter", 16.0, unit="mm", min=6.0),
        number("spacing", "Bar centre-to-centre spacing", 150.0, unit="mm", min=40.0),
        number(
            "concreteThicknessMm", "Member section depth / thickness", 250.0, unit="mm", min=100.0
        ),
    ],
)
def add_rebar_set(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute reinforcement area As per metre, steel mass/m², clear bar gap, and ratio."""
    import math

    require_bim(ctx)
    d = float(values["diameter"])
    s = float(values["spacing"])
    h = float(values["concreteThicknessMm"])
    bar_area = math.pi * (d / 2.0) ** 2
    as_per_m = bar_area * (1000.0 / s)
    mass_per_m2 = (as_per_m / 1e6) * 7850.0
    clear_gap = s - d
    rho_pct = (as_per_m / (1000.0 * h)) * 100.0
    gap_ok = clear_gap >= max(25.0, d)
    proposal = {
        "host": values["host"],
        "diameterMm": d,
        "spacingMm": s,
        "asMm2PerM": round(as_per_m, 1),
        "massKgPerM2": round(mass_per_m2, 2),
        "clearSpacingMm": round(clear_gap, 1),
        "steelRatioPct": round(rho_pct, 2),
        "spacingOk": gap_ok,
    }
    path = write_bim_json(ctx, "rebar-set.json", proposal)
    return result(
        summary={**proposal, "exportPath": path},
        tables=[
            table(
                "Reinforcement Rebar Set Calculation",
                [
                    ("host", "Host"),
                    ("diameterMm", "Dia", "mm"),
                    ("spacingMm", "Spacing", "mm"),
                    ("asMm2PerM", "As/m", "mm²/m"),
                    ("massKgPerM2", "Mass", "kg/m²"),
                    ("steelRatioPct", "ρ", "%"),
                ],
                [proposal],
            )
        ],
        notes=[
            f"Clear bar gap={clear_gap:.0f} mm ({'OK' if gap_ok else 'TIGHT < max(d, 25mm)'}); saved to {path}."
        ],
    )


@feature(
    "bimAdditions.createAssembly",
    "Create Assembly",
    part="bim",
    fields=[
        text("name", "Assembly name", "Frame Assembly"),
        text("elementIds", "Element ids", "C1,C2,B1"),
    ],
)
def create_assembly(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Groups selected elements into a named assembly."""
    data = require_bim(ctx)
    ids = [x.strip() for x in values["elementIds"].split(",") if x.strip()]
    selected = [r for r in element_rows(data) if r["id"] in set(ids)]
    assembly = {"name": values["name"], "elementIds": [r["id"] for r in selected]}
    path = write_bim_json(ctx, "assembly.json", assembly)
    return result(
        summary={
            "assemblyName": values["name"],
            "selectedElementCount": len(selected),
            "exportPath": path,
        },
        tables=[
            table(
                "Assembly Members",
                [("id", "Element id"), ("kind", "Kind"), ("type", "Type")],
                selected,
            )
        ],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditions.assemblyTypes",
    "Assembly Types",
    part="bim",
    fields=[
        text("typeName", "Assembly group prefix", "Modular-Frame"),
        select(
            "memberKind",
            "Group BIM elements by kind",
            [("all", "All elements"), ("beam", "Beams"), ("column", "Columns"), ("slab", "Slabs")],
            "all",
        ),
    ],
)
def assembly_types(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Group real 06 BIM elements by structural type and story to define prefab assembly types."""
    data = require_bim(ctx)
    rows = element_rows(data)
    grouped: dict[tuple[str, str], list[str]] = {}
    for r in rows:
        if values["memberKind"] != "all" and r["kind"] != values["memberKind"]:
            continue
        grouped.setdefault((str(r["kind"]), str(r["type"])), []).append(str(r["id"]))
    summary_rows = [
        {
            "assemblyType": f"{values['typeName']}-{k}-{t}",
            "kind": k,
            "profile": t,
            "count": len(ids),
            "members": ",".join(ids[:6]),
        }
        for (k, t), ids in sorted(grouped.items())
    ]
    path = write_bim_json(ctx, "assembly-types.json", summary_rows)
    return result(
        summary={
            "assemblyTypeCount": len(summary_rows),
            "totalElements": sum(r["count"] for r in summary_rows),
            "exportPath": path,
        },
        tables=[
            table(
                "Derived Assembly Types",
                [
                    ("assemblyType", "Assembly"),
                    ("kind", "Kind"),
                    ("profile", "Type"),
                    ("count", "Count"),
                ],
                summary_rows,
            )
        ],
        notes=[
            f"Grouped real BIM elements into {len(summary_rows)} assembly type(s); saved to {path}."
        ],
    )


@feature(
    "bimAdditions.explodeAssembly",
    "Explode Assembly",
    part="bim",
    fields=[text("storyFilter", "Story filter (blank = all assemblies)", "")],
)
def explode_assembly(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Disaggregate structural assemblies into individual tracked element instances by story."""
    import json

    data = require_bim(ctx)
    filt = values["storyFilter"].strip().lower()
    assembly_ids: set[str] | None = None
    reg = ctx.path("11 Exports/BIM/assembly.json")
    if reg is not None and reg.is_file():
        try:
            saved = json.loads(reg.read_text(encoding="utf-8"))
            if (
                isinstance(saved, dict)
                and isinstance(saved.get("elementIds"), list)
                and saved["elementIds"]
            ):
                assembly_ids = {str(x) for x in saved["elementIds"]}
        except ValueError:
            assembly_ids = None
    rows = [
        {"id": r["id"], "kind": r["kind"], "type": r["type"], "story": r["story"]}
        for r in element_rows(data)
        if (assembly_ids is None or r["id"] in assembly_ids)
        and (not filt or filt in str(r["story"]).lower())
    ]
    by_story: dict[str, int] = {}
    for r in rows:
        by_story[r["story"]] = by_story.get(r["story"], 0) + 1
    path = write_bim_json(
        ctx,
        "exploded-assembly.json",
        {"filter": values["storyFilter"], "storyCounts": by_story, "elements": rows},
    )
    return result(
        summary={
            "resultingElementCount": len(rows),
            "storyCount": len(by_story),
            "exportPath": path,
        },
        tables=[
            table(
                "Exploded Assembly Elements",
                [("id", "Element"), ("kind", "Kind"), ("type", "Type"), ("story", "Story")],
                rows,
            )
        ],
        notes=[
            f"Disaggregated {len(rows)} individual BIM element(s) across {len(by_story)} story level(s); saved to {path}."
        ],
    )


@feature(
    "bimAdditions.placeOnFace",
    "Place on Face",
    part="bim",
    fields=[
        text("elementId", "Host element ID", "C1"),
        select(
            "face",
            "Target face normal",
            [("top", "Top (+Z)"), ("side", "Side (+X/+Y)"), ("bottom", "Bottom (-Z)")],
            "top",
        ),
    ],
)
def place_on_face(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute host element face plane coordinates and normal vector from real 06 BIM geometry."""
    data = require_bim(ctx)
    eid = values["elementId"].strip()
    raw_el = next((e for e in (data.get("elements") or []) if str(e.get("id", "")) == eid), None)
    if raw_el is None:
        raise FeatureInputError(f"Element id {eid!r} is not in 06 BIM/bim.json.")
    z_top = float(raw_el.get("topElevation", raw_el.get("elevation", 3200.0)) or 3200.0)
    z_base = float(raw_el.get("baseElevation", 0.0) or 0.0)
    normals = {"top": [0, 0, 1], "side": [1, 0, 0], "bottom": [0, 0, -1]}
    face_z = (
        z_top
        if values["face"] == "top"
        else (z_base if values["face"] == "bottom" else 0.5 * (z_top + z_base))
    )
    payload = {
        "elementId": eid,
        "kind": raw_el.get("kind", ""),
        "targetFace": values["face"],
        "normal": normals[values["face"]],
        "planeElevationMm": round(face_z, 1),
    }
    path = write_bim_json(ctx, "face-placement.json", payload)
    return result(
        summary={**payload, "exportPath": path},
        notes=[f"Computed host {eid} {values['face']} plane z={face_z:g} mm; saved to {path}."],
    )


@feature(
    "bimAdditions.placeByGrid",
    "Place by Grid",
    part="bim",
    fields=[
        text("gridX", "Grid X label", "A"),
        text("gridY", "Grid Y label", "1"),
        number("offsetX", "Local offset X", 0.0, unit="m"),
        number("offsetY", "Local offset Y", 0.0, unit="m"),
    ],
)
def place_by_grid(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Resolve real world (X, Y) coordinates from 05 Floor Plan grids plus placement offsets."""
    require_bim(ctx)
    plan = ctx.raw("floorPlan") or {}
    grids = plan.get("grids") or {}
    gx_label = values["gridX"].strip()
    gy_label = values["gridY"].strip()
    from saengine.library.grid_geometry import GridError, GridGeometry

    try:
        gx_pos, gy_pos = GridGeometry(grids if isinstance(grids, dict) else {}).intersection(
            gx_label, gy_label
        )
    except GridError as exc:
        raise FeatureInputError(
            f"Grid intersection ({gx_label}, {gy_label}) not found in 05 Floor Plan/floor-plan.json "
            f"({exc})."
        ) from exc
    world_x_mm = gx_pos + float(values["offsetX"]) * 1000.0
    world_y_mm = gy_pos + float(values["offsetY"]) * 1000.0
    point = {
        "gridX": gx_label,
        "gridY": gy_label,
        "gridIntersectionMm": [gx_pos, gy_pos],
        "worldCoordinateMm": [round(world_x_mm, 1), round(world_y_mm, 1)],
    }
    path = write_bim_json(ctx, "grid-placement.json", point)
    return result(
        summary={
            "gridIntersection": f"{gx_label}-{gy_label}",
            "worldXMm": point["worldCoordinateMm"][0],
            "worldYMm": point["worldCoordinateMm"][1],
            "exportPath": path,
        },
        notes=[
            f"Resolved world coordinates ({world_x_mm:g}, {world_y_mm:g}) mm from 05 Floor Plan grids; saved to {path}."
        ],
    )


@feature(
    "bimAdditions.array",
    "Array",
    part="bim",
    fields=[
        text("elementId", "Source element id", "C1"),
        number("count", "Copies", 3, unit="ea", min=2),
        number("dx", "X spacing", 1.0, unit="m"),
        number("dy", "Y spacing", 0.0, unit="m"),
    ],
)
def array(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a rectangular array of a selected BIM element."""
    data = require_bim(ctx)
    ids = {r["id"] for r in element_rows(data)}
    if values["elementId"] not in ids:
        raise FeatureInputError("The source element id is not in the BIM model.")
    copies = [
        {"copy": i, "offsetXM": values["dx"] * i, "offsetYM": values["dy"] * i}
        for i in range(1, int(values["count"]))
    ]
    path = write_bim_csv(ctx, "array-copies.csv", ["copy", "offsetXM", "offsetYM"], copies)
    return result(
        summary={
            "sourceElementId": values["elementId"],
            "copyCount": len(copies),
            "exportPath": path,
        },
        tables=[
            table(
                "Array Copies",
                [
                    ("copy", "Copy"),
                    ("offsetXM", "X offset [m]", "m"),
                    ("offsetYM", "Y offset [m]", "m"),
                ],
                copies,
            )
        ],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditions.addSpace",
    "Add Space",
    part="bim",
    fields=[
        text("name", "Space name", "Room 101"),
        text("story", "Host story ID", "L1"),
        number("area", "Net floor area", 24.0, unit="m²", min=0.5),
        number("ceilingHeightM", "Clear floor-to-ceiling height", 3.0, unit="m", min=2.0),
    ],
)
def add_space(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate host story in 06 BIM, compute space volume, and accumulate space schedule."""
    import json

    data = require_bim(ctx)
    story_ids = {str(s.get("id", "")) for s in (data.get("stories") or [])}
    st = values["story"].strip()
    if story_ids and st not in story_ids:
        raise FeatureInputError(
            f"Story {st!r} does not exist in 06 BIM/bim.json ({sorted(story_ids)})."
        )
    area = float(values["area"])
    vol = area * float(values["ceilingHeightM"])
    entry = {
        "name": values["name"].strip() or "Space",
        "story": st,
        "areaM2": area,
        "volumeM3": round(vol, 1),
    }
    reg = ctx.path("11 Exports/BIM/spaces.json")
    spaces: list[dict[str, Any]] = []
    if reg is not None and reg.exists():
        try:
            loaded = json.loads(reg.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                spaces = [r for r in loaded if isinstance(r, dict)]
        except ValueError:
            pass
    by_name = {str(r.get("name")): r for r in spaces}
    by_name[entry["name"]] = entry
    all_spaces = list(by_name.values())
    path = write_bim_json(ctx, "spaces.json", all_spaces)
    return result(
        summary={
            **entry,
            "totalSpaces": len(all_spaces),
            "totalAreaM2": round(sum(float(r.get("areaM2", 0)) for r in all_spaces), 1),
            "exportPath": path,
        },
        tables=[
            table(
                "BIM Spaces Register",
                [
                    ("name", "Name"),
                    ("story", "Story"),
                    ("areaM2", "Area", "m²"),
                    ("volumeM3", "Volume", "m³"),
                ],
                all_spaces,
            )
        ],
        notes=[f"Validated host story {st}; accumulated {len(all_spaces)} space(s) at {path}."],
    )


@feature(
    "bimAdditions.spaceBoundaries",
    "Space Boundaries",
    part="bim",
    fields=[
        text("storyFilter", "Story level filter (blank = all)", ""),
        checkbox("includeSecondLevel", "Include slab/ceiling thermal boundaries", True),
    ],
)
def space_boundaries(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Extract architectural/structural bounding walls, columns, and slabs from 06 BIM."""
    data = require_bim(ctx)
    filt = values["storyFilter"].strip().lower()
    kinds = ("wall", "slab", "column") if values["includeSecondLevel"] else ("wall", "column")
    rows = [
        {"id": r["id"], "kind": r["kind"], "type": r["type"], "story": r["story"]}
        for r in element_rows(data)
        if r["kind"] in kinds and (not filt or filt in str(r["story"]).lower())
    ]
    path = write_bim_csv(ctx, "space-boundaries.csv", ["id", "kind", "type", "story"], rows)
    return result(
        summary={
            "includeSecondLevel": bool(values["includeSecondLevel"]),
            "boundaryCount": len(rows),
            "exportPath": path,
        },
        tables=[
            table(
                "Space Boundaries",
                [("id", "Element"), ("kind", "Kind"), ("type", "Type"), ("story", "Story")],
                rows,
            )
        ],
        notes=[f"Extracted {len(rows)} real bounding element(s); exported to {path}."],
    )


@feature(
    "bimAdditions.addZone",
    "Add Zone",
    part="bim",
    fields=[
        text("name", "Zone name", "Office Zone"),
        text("spaceNames", "Member spaces (comma-separated)", "Room 101, Room 102"),
        number("coolingWPerM2", "Zone design cooling density", 110.0, unit="W/m²", min=10.0),
    ],
)
def add_zone(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Group named BIM spaces into a persistent thermal/fire zone register."""
    import json

    require_bim(ctx)
    names = [x.strip() for x in values["spaceNames"].split(",") if x.strip()]
    if not names:
        raise FeatureInputError("Enter at least one space name for the zone.")
    reg_sp = ctx.path("11 Exports/BIM/spaces.json")
    area_map: dict[str, float] = {}
    if reg_sp is not None and reg_sp.exists():
        try:
            loaded = json.loads(reg_sp.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                area_map = {
                    str(r.get("name")): float(r.get("areaM2", 24.0))
                    for r in loaded
                    if isinstance(r, dict)
                }
        except ValueError:
            pass
    zone_area = sum(area_map.get(n, 24.0) for n in names)
    load_kw = zone_area * float(values["coolingWPerM2"]) / 1000.0
    zone = {
        "name": values["name"].strip() or "Zone",
        "spaces": names,
        "zoneAreaM2": round(zone_area, 1),
        "coolingLoadKw": round(load_kw, 2),
    }
    reg_z = ctx.path("11 Exports/BIM/zones.json")
    zones: list[dict[str, Any]] = []
    if reg_z is not None and reg_z.exists():
        try:
            lz = json.loads(reg_z.read_text(encoding="utf-8"))
            if isinstance(lz, list):
                zones = [r for r in lz if isinstance(r, dict)]
        except ValueError:
            pass
    by_z = {str(z.get("name")): z for z in zones}
    by_z[zone["name"]] = zone
    all_zones = list(by_z.values())
    path = write_bim_json(ctx, "zones.json", all_zones)
    return result(
        summary={
            "zoneName": zone["name"],
            "spaceCount": len(names),
            "zoneAreaM2": zone["zoneAreaM2"],
            "coolingLoadKw": zone["coolingLoadKw"],
            "exportPath": path,
        },
        tables=[
            table(
                "BIM Zones Register",
                [("name", "Zone"), ("zoneAreaM2", "Area", "m²"), ("coolingLoadKw", "Load", "kW")],
                all_zones,
            )
        ],
        notes=[f"Saved {len(all_zones)} zone(s) to {path}."],
    )


@feature(
    "bimAdditions.zoneEquipment",
    "Zone Equipment",
    part="bim",
    fields=[
        text("zoneName", "Zone name", "Office Zone"),
        text("equipmentNames", "Equipment IDs (blank = read 07 MEP plant)", ""),
    ],
)
def zone_equipment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign real 07 MEP plant or specified terminal units to a BIM zone and export schedule."""
    require_bim(ctx)
    mep = ctx.raw("mep") or {}
    plant_ids = [
        str(u.get("id", ""))
        for u in ((mep.get("hvac") or {}).get("plant") or [])
        if isinstance(u, dict) and u.get("id")
    ]
    entered = [x.strip() for x in values["equipmentNames"].split(",") if x.strip()]
    names = entered if entered else plant_ids
    if not names:
        raise FeatureInputError(
            "No HVAC plant units found in 07 MEP/mep.json; enter equipment IDs."
        )
    rows = [
        {"zone": values["zoneName"].strip(), "equipment": n, "inMepModel": n in plant_ids}
        for n in names
    ]
    path = write_bim_csv(ctx, "zone-equipment.csv", ["zone", "equipment", "inMepModel"], rows)
    return result(
        summary={"zoneName": values["zoneName"], "equipmentCount": len(rows), "exportPath": path},
        tables=[
            table(
                "Zone Equipment Schedule",
                [("zone", "Zone"), ("equipment", "Equipment"), ("inMepModel", "In 07 MEP")],
                rows,
            )
        ],
        notes=[f"Linked {len(rows)} unit(s) to zone; exported to {path}."],
    )


@feature(
    "bimAdditions.spaceTags",
    "Space Tags",
    part="bim",
    fields=[
        checkbox("showArea", "Show space area", True),
        checkbox("showName", "Show space name", True),
    ],
)
def space_tags(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates view tags for BIM spaces."""
    require_bim(ctx)
    return result(
        summary={"showArea": bool(values["showArea"]), "showName": bool(values["showName"])},
        notes=["Tag formatting is reported as a view setting; geometry is unchanged."],
    )


@feature(
    "bimAdditions.addTerrain",
    "Add Terrain",
    part="bim",
    fields=[
        number("length", "Terrain extent X", 100.0, unit="m", min=1),
        number("width", "Terrain extent Y", 100.0, unit="m", min=1),
        number("spacing", "Survey spacing", 5.0, unit="m", min=0.1),
    ],
)
def add_terrain(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Adds a terrain surface from surveyed points."""
    require_bim(ctx)
    spacing = values["spacing"]
    nx = max(2, int(values["length"] / spacing) + 1)
    ny = max(2, int(values["width"] / spacing) + 1)
    rows = [
        {"x": i * spacing, "y": j * spacing, "elevationMm": 0.0}
        for i in range(nx)
        for j in range(ny)
    ]
    path = write_bim_csv(ctx, "terrain-grid.csv", ["x", "y", "elevationMm"], rows)
    return result(
        summary={
            "lengthM": values["length"],
            "widthM": values["width"],
            "spacingM": spacing,
            "gridPointCount": len(rows),
            "exportPath": path,
        },
        tables=[
            table(
                "Terrain Grid",
                [("x", "X [m]", "m"), ("y", "Y [m]", "m"), ("elevationMm", "Elevation [mm]", "mm")],
                rows[:100],
            )
        ],
        notes=[
            "Grid elevations default to the supplied project datum; surveyed heights are not fabricated.",
            "The BIM terrain grid is exported as a coordinate table.",
            f"Export: {path}",
        ],
    )


@feature(
    "bimAdditions.addPaving",
    "Add Paving",
    part="bim",
    fields=[
        number("length", "Paving length", 20.0, unit="m", min=0.1),
        number("width", "Paving width", 5.0, unit="m", min=0.1),
        number("thickness", "Paving thickness", 100, unit="mm", min=20),
    ],
)
def add_paving(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a paving or hardscape surface."""
    require_bim(ctx)
    area = values["length"] * values["width"]
    volume = area * values["thickness"] / 1000
    paving = {
        "lengthM": values["length"],
        "widthM": values["width"],
        "thicknessMm": values["thickness"],
        "areaM2": area,
        "volumeM3": volume,
    }
    path = write_bim_json(ctx, "paving.json", paving)
    return result(
        summary={**paving, "exportPath": path},
        tables=[
            table(
                "Paving",
                [
                    ("lengthM", "Length [m]", "m"),
                    ("widthM", "Width [m]", "m"),
                    ("thicknessMm", "Thickness [mm]", "mm"),
                    ("areaM2", "Area [m²]", "m²"),
                    ("volumeM3", "Volume [m³]", "m³"),
                ],
                [paving],
            )
        ],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditions.addPlanting",
    "Add Planting",
    part="bim",
    fields=[
        text("species", "Plant species", "Native shrub"),
        number("spacing", "Plant centre spacing", 1.2, unit="m", min=0.2),
        number("quantity", "Plant quantity", 20, unit="ea", min=1),
        select(
            "pattern",
            "Planting pattern",
            [("square", "Square grid"), ("triangular", "Triangular staggered")],
            "triangular",
        ),
    ],
)
def add_planting(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute landscape bed area, soil topsoil depth volume, and irrigation demand."""
    require_bim(ctx)
    s = float(values["spacing"])
    n = int(values["quantity"])
    area_per_plant = (s**2) * (0.866 if values["pattern"] == "triangular" else 1.0)
    bed_area = area_per_plant * n
    topsoil_m3 = bed_area * 0.45  # 450 mm prepared planter bed depth
    peak_water_lpd = bed_area * 4.5  # ~4.5 L/(m2·day) evapotranspiration irrigation allowance
    planting = {
        "species": values["species"],
        "pattern": values["pattern"],
        "spacingM": s,
        "quantity": n,
        "bedAreaM2": round(bed_area, 1),
        "topsoilVolumeM3": round(topsoil_m3, 1),
        "irrigationLPerDay": round(peak_water_lpd, 0),
    }
    path = write_bim_json(ctx, "planting.json", planting)
    return result(
        summary={**planting, "exportPath": path},
        tables=[
            table(
                "Site Planting & Irrigation Estimate",
                [
                    ("species", "Species"),
                    ("quantity", "Count"),
                    ("bedAreaM2", "Bed Area", "m²"),
                    ("topsoilVolumeM3", "Topsoil", "m³"),
                    ("irrigationLPerDay", "Irrigation", "L/d"),
                ],
                [planting],
            )
        ],
        notes=[
            f"{values['pattern'].capitalize()} spacing ({s:g} m) requires {bed_area:.1f} m2 planter area; saved to {path}."
        ],
    )


@feature(
    "bimAdditions.addFence",
    "Add Fence",
    part="bim",
    fields=[
        number("length", "Fence length", 30.0, unit="m", min=0.1),
        number("height", "Fence height", 1.8, unit="m", min=0.1),
        number("postSpacing", "Post spacing", 3.0, unit="m", min=0.5),
    ],
)
def add_fence(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a fence segment in the site model."""
    require_bim(ctx)
    posts = max(2, int(values["length"] / values["postSpacing"]) + 1)
    fence = {
        "lengthM": values["length"],
        "heightM": values["height"],
        "postSpacingM": values["postSpacing"],
        "postCount": posts,
    }
    path = write_bim_json(ctx, "fence.json", fence)
    return result(
        summary={**fence, "exportPath": path},
        tables=[
            table(
                "Fence",
                [
                    ("lengthM", "Length [m]", "m"),
                    ("heightM", "Height [m]", "m"),
                    ("postSpacingM", "Post spacing [m]", "m"),
                    ("postCount", "Post count"),
                ],
                [fence],
            )
        ],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditions.addSiteFurniture",
    "Add Site Furniture",
    part="bim",
    fields=[
        text("name", "Furniture name", "Bench"),
        number("quantity", "Quantity", 2, unit="ea", min=1),
        number("weight", "Unit weight", 25.0, unit="kg", min=0),
    ],
)
def add_site_furniture(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Places furniture or small site elements."""
    require_bim(ctx)
    quantity = int(values["quantity"])
    item = {
        "name": values["name"],
        "quantity": quantity,
        "weightKg": values["weight"],
        "totalWeightKg": quantity * values["weight"],
    }
    path = write_bim_json(ctx, "site-furniture.json", item)
    return result(
        summary={
            "furnitureName": values["name"],
            "quantity": quantity,
            "totalWeightKg": item["totalWeightKg"],
            "exportPath": path,
        },
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditions.insertPreview",
    "Insert Preview",
    part="bim",
    fields=[
        text("sourcePath", "Source file", "06 BIM/model.ifc"),
        checkbox("showWireframe", "Preview in wireframe", True),
    ],
)
def insert_preview(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Displays a preview of an external BIM component before insertion."""
    require_bim(ctx)
    path = str(ctx.path(values["sourcePath"]) if ctx.root else "")
    return result(
        summary={
            "sourcePath": values["sourcePath"],
            "showWireframe": bool(values["showWireframe"]),
            "sourceExists": bool(
                ctx.path(values["sourcePath"]) and ctx.path(values["sourcePath"]).is_file()
            ),
        },
        notes=["Preview is read-only; no component is inserted.", f"Resolved source: {path}"],
    )


@feature(
    "bimAdditions.hostVerification",
    "Host Verification",
    part="bim",
    fields=[
        text("elementId", "Element id", "C1"),
        checkbox("verifyHost", "Require valid host", True),
    ],
)
def host_verification(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verifies that an added element has a valid BIM host."""
    data = require_bim(ctx)
    matches = [r for r in element_rows(data) if r["id"] == values["elementId"]]
    valid = bool(matches)
    host = matches[0] if matches else None
    if values["verifyHost"] and not valid:
        raise FeatureInputError("The selected element id has no matching host in the BIM model.")
    return result(
        summary={
            "elementId": values["elementId"],
            "validHost": valid,
            "hostKind": host["kind"] if host else "none",
        },
        tables=[
            table(
                "Host Verification",
                [("id", "Element id"), ("kind", "Kind"), ("type", "Type")],
                [host] if host else [],
            )
        ],
    )


@feature(
    "bimAdditions.levelConstraint",
    "Level Constraint",
    part="bim",
    fields=[
        text("elementId", "Element id", "C1"),
        text("levelName", "Level name", "Level 1"),
        number("elevation", "Level elevation", 3200, unit="mm"),
    ],
)
def level_constraint(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Constrains an element to a BIM level."""
    data = require_bim(ctx)
    ids = {r["id"] for r in element_rows(data)}
    if values["elementId"] not in ids:
        raise FeatureInputError("The element id is not present in the BIM model.")
    constraint = {
        "elementId": values["elementId"],
        "levelName": values["levelName"],
        "elevationMm": values["elevation"],
    }
    path = write_bim_json(ctx, "level-constraint.json", constraint)
    return result(
        summary={
            "elementId": values["elementId"],
            "levelName": values["levelName"],
            "elevationMm": values["elevation"],
            "exportPath": path,
        },
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditions.duplicateGuard",
    "Duplicate Guard",
    part="bim",
    fields=[
        checkbox("blockDuplicateIds", "Block duplicate element ids", True),
        number("tolerance", "Coincident position tolerance", 1.0, unit="mm", min=0),
    ],
)
def duplicate_guard(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Checks proposed additions for duplicate ids or coincident elements."""
    data = require_bim(ctx)
    rows = element_rows(data)
    seen = set()
    duplicates = []
    for r in rows:
        if r["id"] in seen:
            duplicates.append(r["id"])
        seen.add(r["id"])
    return result(
        summary={
            "blockDuplicateIds": bool(values["blockDuplicateIds"]),
            "toleranceMm": values["tolerance"],
            "duplicateIdCount": len(set(duplicates)),
            "elementCount": len(rows),
        },
        tables=[
            table(
                "Duplicate IDs",
                [("id", "Duplicate id")],
                [{"id": x} for x in sorted(set(duplicates))],
            )
        ],
        notes=[
            "Coincident positions require geometry coordinates; duplicate ids are checked directly.",
            "No data is modified.",
        ],
    )

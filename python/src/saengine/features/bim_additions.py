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
        text("type", "Member type", "B300x500"),
        number("length", "Length", 6.0, unit="m", min=0.1),
    ],
)
def add_structural_member(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Adds a structural member to the federated model."""
    data = require_bim(ctx)
    member = {
        "id": f"M{len(element_rows(data)) + 1}",
        "kind": values["kind"],
        "type": values["type"],
        "lengthM": values["length"],
    }
    path = write_bim_json(ctx, "structural-member.json", member)
    return result(
        summary={
            "memberId": member["id"],
            "memberKind": values["kind"],
            "lengthM": values["length"],
            "exportPath": path,
        },
        tables=[
            table(
                "Structural Member",
                [
                    ("id", "Member id"),
                    ("kind", "Kind"),
                    ("type", "Type"),
                    ("lengthM", "Length [m]", "m"),
                ],
                [member],
            )
        ],
        notes=[
            "Member proposal is exported without modifying the source BIM element list.",
            f"Export: {path}",
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
        number("diameter", "Bar diameter", 16, unit="mm", min=6),
        number("spacing", "Bar spacing", 150, unit="mm", min=25),
    ],
)
def add_rebar_set(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Adds a reinforcement set to a concrete element."""
    require_bim(ctx)
    from saengine.library.ifc_rebar import export_rebar

    proposal = {
        "host": values["host"],
        "diameterMm": values["diameter"],
        "spacingMm": values["spacing"],
    }
    path = write_bim_json(ctx, "rebar-set.json", proposal)
    return result(
        summary={
            "host": values["host"],
            "barDiameterMm": values["diameter"],
            "barSpacingMm": values["spacing"],
            "exportPath": path,
        },
        tables=[
            table(
                "Rebar Set",
                [
                    ("host", "Host"),
                    ("diameterMm", "Diameter [mm]", "mm"),
                    ("spacingMm", "Spacing [mm]", "mm"),
                ],
                [proposal],
            )
        ],
        notes=[
            "Rebar set is represented as a validated reinforcement proposal.",
            f"Reuse available: {export_rebar.__module__}",
            f"Export: {path}",
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
        text("typeName", "Assembly type", "Modular-Frame"),
        number("quantity", "Typical quantity", 1, unit="ea", min=1),
    ],
)
def assembly_types(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines reusable assembly templates."""
    require_bim(ctx)
    record = {"type": values["typeName"], "quantity": int(values["quantity"])}
    path = write_bim_json(ctx, "assembly-types.json", [record])
    return result(
        summary={
            "typeName": values["typeName"],
            "quantity": int(values["quantity"]),
            "exportPath": path,
        },
        tables=[table("Assembly Types", [("type", "Type"), ("quantity", "Quantity")], [record])],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditions.explodeAssembly",
    "Explode Assembly",
    part="bim",
    fields=[text("assemblyName", "Assembly name", "Frame Assembly")],
)
def explode_assembly(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Breaks an assembly back into single elements."""
    data = require_bim(ctx)
    rows = element_rows(data)
    path = write_bim_json(
        ctx,
        "exploded-assembly.json",
        {"name": values["assemblyName"], "elements": [r["id"] for r in rows]},
    )
    return result(
        summary={
            "assemblyName": values["assemblyName"],
            "resultingElementCount": len(rows),
            "exportPath": path,
        },
        tables=[table("Exploded Elements", [("id", "Element id"), ("kind", "Kind")], rows)],
        notes=[
            "Assembly grouping is removed in the exported view only.",
            "Source BIM data is unchanged.",
            f"Export: {path}",
        ],
    )


@feature(
    "bimAdditions.placeOnFace",
    "Place on Face",
    part="bim",
    fields=[
        text("elementId", "Component element id", "C1"),
        select(
            "face", "Target face", [("top", "Top"), ("side", "Side"), ("bottom", "Bottom")], "top"
        ),
    ],
)
def place_on_face(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Places the active component on a picked face."""
    data = require_bim(ctx)
    matches = [r for r in element_rows(data) if r["id"] == values["elementId"]]
    if not matches:
        raise FeatureInputError("The requested element id is not in the BIM model.")
    path = write_bim_json(
        ctx, "face-placement.json", {"elementId": values["elementId"], "face": values["face"]}
    )
    return result(
        summary={
            "elementId": values["elementId"],
            "targetFace": values["face"],
            "exportPath": path,
        },
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditions.placeByGrid",
    "Place by Grid",
    part="bim",
    fields=[
        text("gridX", "Grid X", "A"),
        text("gridY", "Grid Y", "1"),
        number("offsetX", "Offset X", 0, unit="m"),
        number("offsetY", "Offset Y", 0, unit="m"),
    ],
)
def place_by_grid(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Places a component at a grid intersection."""
    require_bim(ctx)
    point = {
        "gridX": values["gridX"],
        "gridY": values["gridY"],
        "offsetXM": values["offsetX"],
        "offsetYM": values["offsetY"],
    }
    path = write_bim_json(ctx, "grid-placement.json", point)
    return result(
        summary={
            "gridX": values["gridX"],
            "gridY": values["gridY"],
            "offsetXM": values["offsetX"],
            "offsetYM": values["offsetY"],
            "exportPath": path,
        },
        notes=[f"Export: {path}"],
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
        number("area", "Net area", 24.0, unit="m²", min=0),
    ],
)
def add_space(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Adds a BIM space to the building model."""
    require_bim(ctx)
    space = {"name": values["name"], "areaM2": values["area"]}
    path = write_bim_json(ctx, "spaces.json", [space])
    return result(
        summary={"spaceName": values["name"], "areaM2": values["area"], "exportPath": path},
        tables=[table("Space", [("name", "Name"), ("areaM2", "Area [m²]", "m²")], [space])],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditions.spaceBoundaries",
    "Space Boundaries",
    part="bim",
    fields=[
        text("spaceName", "Space name", "Room 101"),
        checkbox("includeSecondLevel", "Include secondary boundaries", False),
    ],
)
def space_boundaries(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculates and lists boundaries for a building space."""
    data = require_bim(ctx)
    rows = [r for r in element_rows(data) if r["kind"] in ("wall", "slab", "column")]
    path = write_bim_csv(ctx, "space-boundaries.csv", ["id", "kind", "type"], rows)
    return result(
        summary={
            "spaceName": values["spaceName"],
            "includeSecondLevel": bool(values["includeSecondLevel"]),
            "boundaryCount": len(rows),
            "exportPath": path,
        },
        tables=[
            table(
                "Space Boundaries", [("id", "Element id"), ("kind", "Kind"), ("type", "Type")], rows
            )
        ],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditions.addZone",
    "Add Zone",
    part="bim",
    fields=[
        text("name", "Zone name", "Office Zone"),
        text("spaceNames", "Space names", "Room 101, Room 102"),
    ],
)
def add_zone(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Groups spaces into a named thermal or usage zone."""
    require_bim(ctx)
    names = [x.strip() for x in values["spaceNames"].split(",") if x.strip()]
    zone = {"name": values["name"], "spaces": names}
    path = write_bim_json(ctx, "zones.json", [zone])
    return result(
        summary={"zoneName": values["name"], "spaceCount": len(names), "exportPath": path},
        tables=[table("Zone Spaces", [("name", "Space")], [{"name": n} for n in names])],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditions.zoneEquipment",
    "Zone Equipment",
    part="bim",
    fields=[
        text("zoneName", "Zone name", "Office Zone"),
        text("equipmentNames", "Equipment names", "FCU-1, FCU-2"),
    ],
)
def zone_equipment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assigns equipment to a building zone."""
    require_bim(ctx)
    names = [x.strip() for x in values["equipmentNames"].split(",") if x.strip()]
    path = write_bim_csv(
        ctx,
        "zone-equipment.csv",
        ["zone", "equipment"],
        [{"zone": values["zoneName"], "equipment": n} for n in names],
    )
    return result(
        summary={"zoneName": values["zoneName"], "equipmentCount": len(names), "exportPath": path},
        tables=[
            table(
                "Zone Equipment",
                [("zone", "Zone"), ("equipment", "Equipment")],
                [{"zone": values["zoneName"], "equipment": n} for n in names],
            )
        ],
        notes=[f"Export: {path}"],
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
        number("spacing", "Plant spacing", 1.5, unit="m", min=0.1),
        number("quantity", "Plant quantity", 10, unit="ea", min=1),
    ],
)
def add_planting(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Places planting elements in the site model."""
    require_bim(ctx)
    planting = {
        "species": values["species"],
        "spacingM": values["spacing"],
        "quantity": int(values["quantity"]),
    }
    path = write_bim_json(ctx, "planting.json", planting)
    return result(
        summary={
            "species": values["species"],
            "spacingM": values["spacing"],
            "quantity": int(values["quantity"]),
            "exportPath": path,
        },
        tables=[
            table(
                "Planting",
                [
                    ("species", "Species"),
                    ("spacingM", "Spacing [m]", "m"),
                    ("quantity", "Quantity"),
                ],
                [planting],
            )
        ],
        notes=[f"Export: {path}"],
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

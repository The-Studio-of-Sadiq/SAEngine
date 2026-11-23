"""Architecture Finishes - surfaces, fixtures, schedules and external works."""

from __future__ import annotations

import math
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
)


def _room_finish_rows(ctx: FeatureContext, kind: str) -> list[dict[str, Any]]:
    arch = require_arch(ctx)
    rows = []
    for r in room_metrics(ctx, arch):
        room = next((x for x in arch.rooms if x.id == r["room"]), None)
        finish = getattr(room, kind + "Finish", None) if room else None
        area = r["netAreaM2"]
        rows.append({"room": r["room"], "finish": finish or "Unassigned", "areaM2": area})
    return rows


@feature(
    "architectureFinishes.floorFinish",
    "Floor Finish",
    part="floorPlan",
    fields=[text("roomId", "Room id", ""), text("finishId", "Finish type id", "")],
)
def floor_finish(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Schedule floor finish assignment and net room area."""
    require_arch(ctx)
    rows = [
        r
        for r in _room_finish_rows(ctx, "floor")
        if not values["roomId"] or r["room"] == values["roomId"]
    ]
    if not rows:
        raise FeatureInputError("No matching room was found.")
    for r in rows:
        r["finish"] = values["finishId"] or r["finish"]
    return result(
        summary={"roomCount": len(rows), "areaM2": sum(r["areaM2"] for r in rows)},
        tables=[
            table(
                "Floor finishes",
                [("room", "Room"), ("finish", "Finish"), ("areaM2", "Area", "m²")],
                rows,
            )
        ],
    )


@feature(
    "architectureFinishes.ceilingFinish",
    "Ceiling Finish",
    part="floorPlan",
    fields=[text("roomId", "Room id", ""), text("finishId", "Ceiling finish id", "")],
)
def ceiling_finish(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Schedule ceiling finish assignment over net room areas."""
    require_arch(ctx)
    rows = [
        r
        for r in _room_finish_rows(ctx, "ceiling")
        if not values["roomId"] or r["room"] == values["roomId"]
    ]
    if not rows:
        raise FeatureInputError("No matching room was found.")
    for r in rows:
        r["finish"] = values["finishId"] or r["finish"]
    return result(
        summary={"roomCount": len(rows), "areaM2": sum(r["areaM2"] for r in rows)},
        tables=[
            table(
                "Ceiling finishes",
                [("room", "Room"), ("finish", "Finish"), ("areaM2", "Area", "m²")],
                rows,
            )
        ],
    )


@feature(
    "architectureFinishes.wallFinish",
    "Wall Finish",
    part="floorPlan",
    fields=[text("roomId", "Room id", ""), text("finishId", "Wall finish id", "")],
)
def wall_finish(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Schedule internal or external wall finish assignment."""
    require_arch(ctx)
    rows = [
        r
        for r in _room_finish_rows(ctx, "wall")
        if not values["roomId"] or r["room"] == values["roomId"]
    ]
    if not rows:
        raise FeatureInputError("No matching room was found.")
    for r in rows:
        r["finish"] = values["finishId"] or r["finish"]
    return result(
        summary={"roomCount": len(rows)},
        tables=[table("Wall finishes", [("room", "Room"), ("finish", "Finish")], rows)],
    )


@feature(
    "architectureFinishes.skirting",
    "Skirting",
    part="floorPlan",
    fields=[
        number("height", "Skirting height", 100, unit="mm", min=1),
        number("thickness", "Thickness", 15, unit="mm", min=1),
    ],
)
def skirting(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate skirting run and gross area from room net boundaries."""
    arch = require_arch(ctx)
    from saengine.library.architecture import room_boundary

    levels = elevations(ctx)
    length = 0.0
    for r in arch.rooms:
        found = room_boundary(arch, r, levels)
        if found:
            length += found[1].length * 1e-3
    area = length * values["height"] / 1000
    return result(summary={"lengthM": length, "areaM2": area, "thicknessMm": values["thickness"]})


@feature(
    "architectureFinishes.plumbingFixtures",
    "Plumbing Fixtures",
    part="mep",
    fields=[
        text("roomId", "Room id", ""),
        select(
            "fixture",
            "Fixture",
            [("basin", "Basin"), ("wc", "Water closet"), ("shower", "Shower"), ("sink", "Sink")],
            "basin",
        ),
        number("count", "Fixture count", 1, unit="nr", min=1),
    ],
)
def plumbing_fixtures(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record plumbing fixture counts by room."""
    arch = require_arch(ctx)
    rooms = [r for r in arch.rooms if not values["roomId"] or r.id == values["roomId"]]
    if not rooms:
        raise FeatureInputError("No matching room was found.")
    rows = [{"room": r.id, "fixture": values["fixture"], "count": values["count"]} for r in rooms]
    return result(
        summary={"fixtureCount": sum(r["count"] for r in rows)},
        tables=[
            table(
                "Plumbing fixtures",
                [("room", "Room"), ("fixture", "Fixture"), ("count", "Count")],
                rows,
            )
        ],
    )


@feature(
    "architectureFinishes.furniture",
    "Furniture",
    part="floorPlan",
    fields=[
        text("roomId", "Room id", ""),
        text("item", "Furniture item", "Desk"),
        number("count", "Count", 1, unit="nr", min=1),
    ],
)
def furniture(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Count furniture items in matching rooms."""
    arch = require_arch(ctx)
    rooms = [r for r in arch.rooms if not values["roomId"] or r.id == values["roomId"]]
    if not rooms:
        raise FeatureInputError("No matching room was found.")
    rows = [{"room": r.id, "item": values["item"], "count": values["count"]} for r in rooms]
    return result(
        summary={"itemCount": sum(r["count"] for r in rows)},
        tables=[table("Furniture", [("room", "Room"), ("item", "Item"), ("count", "Count")], rows)],
    )


@feature(
    "architectureFinishes.casework",
    "Casework",
    part="floorPlan",
    fields=[
        text("roomId", "Room id", ""),
        text("caseworkId", "Casework id", "CW-001"),
        number("length", "Length", 3000, unit="mm", min=1),
        number("count", "Count", 1, unit="nr", min=1),
    ],
)
def casework(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate casework length and count."""
    arch = require_arch(ctx)
    rooms = [r for r in arch.rooms if not values["roomId"] or r.id == values["roomId"]]
    if not rooms:
        raise FeatureInputError("No matching room was found.")
    return result(
        summary={
            "caseworkId": values["caseworkId"],
            "lengthM": values["length"] / 1000,
            "count": values["count"] * len(rooms),
        },
        tables=[
            table(
                "Casework",
                [
                    ("room", "Room"),
                    ("id", "Casework"),
                    ("lengthM", "Length", "m"),
                    ("count", "Count"),
                ],
                [
                    {
                        "room": r.id,
                        "id": values["caseworkId"],
                        "lengthM": values["length"] / 1000,
                        "count": values["count"],
                    }
                    for r in rooms
                ],
            )
        ],
    )


@feature(
    "architectureFinishes.finishSchedule",
    "Finish Schedule",
    part="floorPlan",
    fields=[text("roomId", "Room id", "")],
)
def finish_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Schedule floor, wall and ceiling finishes from room properties."""
    arch = require_arch(ctx)
    rows = [
        {
            "room": r.id,
            "floor": r.floorFinish or "Unassigned",
            "wall": r.wallFinish or "Unassigned",
            "ceiling": r.ceilingFinish or "Unassigned",
        }
        for r in arch.rooms
        if not values["roomId"] or r.id == values["roomId"]
    ]
    if not rows:
        raise FeatureInputError("No matching room was found.")
    path = write_arch_export(
        ctx, "finish-schedule.csv", csv_text(["room", "floor", "wall", "ceiling"], rows)
    )
    return result(
        summary={"roomCount": len(rows), "exportPath": path},
        tables=[
            table(
                "Finish schedule",
                [("room", "Room"), ("floor", "Floor"), ("wall", "Wall"), ("ceiling", "Ceiling")],
                rows,
            )
        ],
    )


@feature(
    "architectureFinishes.fixtureCount",
    "Fixture Count",
    part="floorPlan",
    fields=[
        select(
            "kind",
            "Fixture kind",
            [("doors", "Doors"), ("windows", "Windows"), ("rooms", "Rooms")],
            "doors",
        )
    ],
)
def fixture_count(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Count architectural fixtures by kind."""
    arch = require_arch(ctx)
    count = (
        len(arch.doors)
        if values["kind"] == "doors"
        else len(arch.windows)
        if values["kind"] == "windows"
        else len(arch.rooms)
    )
    return result(summary={"kind": values["kind"], "count": count})


@feature(
    "architectureFinishes.materialTakeoff",
    "Material Takeoff",
    part="floorPlan",
    fields=[
        select(
            "category",
            "Category",
            [
                ("walls", "Wall layers"),
                ("roofs", "Roof types"),
                ("ceilings", "Ceiling types"),
                ("openings", "Doors and windows"),
            ],
            "walls",
        )
    ],
)
def material_takeoff(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarize architectural material and component quantities."""
    arch = require_arch(ctx)
    if values["category"] == "walls":
        rows = [
            {"category": "Walls", "id": t.id, "count": sum(1 for w in arch.walls if w.type == t.id)}
            for t in arch.wallTypes
        ]
    elif values["category"] == "roofs":
        rows = [
            {"category": "Roofs", "id": t.id, "count": sum(1 for r in arch.roofs if r.type == t.id)}
            for t in arch.roofTypes
        ]
    elif values["category"] == "ceilings":
        rows = [
            {
                "category": "Ceilings",
                "id": t.id,
                "count": sum(1 for c in arch.ceilings if c.type == t.id),
            }
            for t in arch.ceilingTypes
        ]
    else:
        rows = [
            {"category": "Doors", "id": t.id, "count": sum(1 for d in arch.doors if d.type == t.id)}
            for t in arch.doorTypes
        ] + [
            {
                "category": "Windows",
                "id": t.id,
                "count": sum(1 for w in arch.windows if w.type == t.id),
            }
            for t in arch.windowTypes
        ]
    return result(
        summary={"category": values["category"], "lineCount": len(rows)},
        tables=[
            table(
                "Architectural material takeoff",
                [("category", "Category"), ("id", "Type"), ("count", "Count")],
                rows,
            )
        ],
    )


@feature(
    "architectureFinishes.tileLayout",
    "Tile Layout",
    part="floorPlan",
    fields=[
        number("length", "Surface length", 3000, unit="mm", min=1),
        number("width", "Surface width", 2000, unit="mm", min=1),
        number("tileLength", "Tile length", 300, unit="mm", min=1),
        number("tileWidth", "Tile width", 300, unit="mm", min=1),
        number("grout", "Grout width", 3, unit="mm", min=0),
    ],
)
def tile_layout(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate tile modules and waste from gross surface and tile dimensions."""
    pitchX = values["tileLength"] + values["grout"]
    pitchY = values["tileWidth"] + values["grout"]
    x = math.ceil(values["length"] / pitchX)
    y = math.ceil(values["width"] / pitchY)
    tiles = x * y
    return result(
        summary={"columnCount": x, "rowCount": y, "tileCount": tiles, "groutMm": values["grout"]}
    )


@feature(
    "architectureFinishes.stoneCladding",
    "Stone Cladding",
    part="floorPlan",
    fields=[
        text("panelId", "Panel id", "S-001"),
        number("width", "Panel width", 600, unit="mm", min=1),
        number("height", "Panel height", 1200, unit="mm", min=1),
        number("thickness", "Panel thickness", 30, unit="mm", min=1),
        number("joint", "Joint width", 8, unit="mm", min=0),
    ],
)
def stone_cladding(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate stone-panel area and volume."""
    area = values["width"] * values["height"] * 1e-6
    volume = area * values["thickness"] / 1000
    return result(
        summary={
            "panelId": values["panelId"],
            "areaM2": area,
            "volumeM3": volume,
            "jointWidthMm": values["joint"],
        }
    )


@feature(
    "architectureFinishes.paintSchedule",
    "Paint Schedule",
    part="floorPlan",
    fields=[
        text("roomId", "Room id", ""),
        text("paintSystem", "Paint system", "Washable emulsion"),
        number("coats", "Number of coats", 2, unit="coat", min=1),
    ],
)
def paint_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Schedule paint systems and coat counts for matching rooms."""
    arch = require_arch(ctx)
    rows = [
        {"room": r.id, "paintSystem": values["paintSystem"], "coats": values["coats"]}
        for r in arch.rooms
        if not values["roomId"] or r.id == values["roomId"]
    ]
    if not rows:
        raise FeatureInputError("No matching room was found.")
    return result(
        summary={"roomCount": len(rows)},
        tables=[
            table(
                "Paint schedule",
                [("room", "Room"), ("paintSystem", "System"), ("coats", "Coats")],
                rows,
            )
        ],
    )


@feature(
    "architectureFinishes.wallpaperPattern",
    "Wallpaper Pattern",
    part="floorPlan",
    fields=[
        number("length", "Surface length", 10000, unit="mm", min=1),
        number("height", "Surface height", 2700, unit="mm", min=1),
        number("repeat", "Pattern repeat", 500, unit="mm", min=1),
        number("rollWidth", "Roll width", 530, unit="mm", min=1),
    ],
)
def wallpaper_pattern(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate wallpaper drop count and pattern repeat."""
    drops = math.ceil(values["length"] / values["rollWidth"])
    repeatCount = math.ceil(values["height"] / values["repeat"])
    return result(
        summary={
            "dropCount": drops,
            "patternRepeatCount": repeatCount,
            "repeatHeightMm": values["repeat"],
        }
    )


@feature(
    "architectureFinishes.raisedFloor",
    "Raised Floor",
    part="floorPlan",
    fields=[
        number("area", "Raised-floor area", 100, unit="m²", min=0.01),
        number("pedestalHeight", "Pedestal height", 300, unit="mm", min=1),
        number("panelSize", "Panel side", 600, unit="mm", min=1),
    ],
)
def raised_floor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate raised-floor panel count and panel area."""
    panelArea = (values["panelSize"] / 1000) ** 2
    panels = math.ceil(values["area"] / panelArea)
    return result(
        summary={
            "areaM2": values["area"],
            "panelCount": panels,
            "pedestalHeightMm": values["pedestalHeight"],
        }
    )


@feature(
    "architectureFinishes.suspendedCeiling",
    "Suspended Ceiling",
    part="floorPlan",
    fields=[
        number("area", "Ceiling area", 100, unit="m²", min=0.01),
        number("drop", "Suspension drop", 300, unit="mm", min=0),
        number("gridSize", "Grid module", 600, unit="mm", min=1),
    ],
)
def suspended_ceiling(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate suspended ceiling panel count and suspension drop."""
    panelArea = (values["gridSize"] / 1000) ** 2
    return result(
        summary={
            "areaM2": values["area"],
            "panelCount": math.ceil(values["area"] / panelArea),
            "dropMm": values["drop"],
        }
    )


@feature(
    "architectureFinishes.ceilingTiles",
    "Ceiling Tiles",
    part="floorPlan",
    fields=[
        number("area", "Ceiling area", 100, unit="m²", min=0.01),
        number("tileSize", "Tile side", 600, unit="mm", min=1),
        number("acousticRating", "User acoustic rating", 0.75, min=0, max=1),
    ],
)
def ceiling_tiles(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate ceiling tile count and report supplied absorption coefficient."""
    panelArea = (values["tileSize"] / 1000) ** 2
    return result(
        summary={
            "areaM2": values["area"],
            "tileCount": math.ceil(values["area"] / panelArea),
            "absorptionCoefficient": values["acousticRating"],
        }
    )


@feature(
    "architectureFinishes.ceilingGrid",
    "Ceiling Grid",
    part="floorPlan",
    fields=[
        number("length", "Room length", 10, unit="m", min=0.1),
        number("width", "Room width", 10, unit="m", min=0.1),
        number("module", "Grid module", 600, unit="mm", min=1),
    ],
)
def ceiling_grid(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate primary grid divisions and grid line count."""
    module = values["module"] / 1000
    linesX = math.ceil(values["length"] / module)
    linesY = math.ceil(values["width"] / module)
    return result(summary={"lengthLines": linesX + 1, "widthLines": linesY + 1, "moduleM": module})


@feature(
    "architectureFinishes.coveLighting",
    "Cove Lighting",
    part="floorPlan",
    fields=[
        number("length", "Cove length", 20, unit="m", min=0.1),
        number("luminousFlux", "Light source luminous flux", 800, unit="lm/m", min=0),
    ],
)
def cove_lighting(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate total cove-light luminous output."""
    return result(
        summary={
            "lengthM": values["length"],
            "luminousFluxLm": values["length"] * values["luminousFlux"],
        }
    )


@feature(
    "architectureFinishes.accessPanel",
    "Access Panel",
    part="floorPlan",
    fields=[
        text("panelId", "Access panel id", "AP-001"),
        number("width", "Width", 600, unit="mm", min=1),
        number("height", "Height", 600, unit="mm", min=1),
    ],
)
def access_panel(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate access panel area."""
    area = values["width"] * values["height"] * 1e-6
    return result(summary={"panelId": values["panelId"], "areaM2": area})


@feature(
    "architectureFinishes.pavingPattern",
    "Paving Pattern",
    part="floorPlan",
    fields=[
        number("length", "Paved length", 20, unit="m", min=0.1),
        number("width", "Paved width", 5, unit="m", min=0.1),
        number("unitLength", "Unit length", 300, unit="mm", min=1),
        number("unitWidth", "Unit width", 300, unit="mm", min=1),
        number("joint", "Joint width", 5, unit="mm", min=0),
    ],
)
def paving_pattern(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate external paving unit count."""
    pitchX = values["unitLength"] + values["joint"]
    pitchY = values["unitWidth"] + values["joint"]
    count = math.ceil(values["length"] * 1000 / pitchX) * math.ceil(values["width"] * 1000 / pitchY)
    return result(
        summary={
            "unitCount": count,
            "areaM2": values["length"] * values["width"],
            "jointWidthMm": values["joint"],
        }
    )


@feature(
    "architectureFinishes.kerbDetail",
    "Kerb Detail",
    part="floorPlan",
    fields=[
        number("length", "Kerb length", 20, unit="m", min=0.1),
        number("width", "Kerb width", 150, unit="mm", min=1),
        number("height", "Kerb height", 300, unit="mm", min=1),
    ],
)
def kerb_detail(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate kerb volume and plan area."""
    volume = values["length"] * values["width"] * values["height"] * 1e-9
    area = values["length"] * values["width"] * 1e-3
    return result(summary={"lengthM": values["length"], "volumeM3": volume, "planAreaM2": area})


@feature(
    "architectureFinishes.landscapeFinish",
    "Landscape Finish",
    part="floorPlan",
    fields=[
        select(
            "surface",
            "Landscape surface",
            [("grass", "Grass"), ("gravel", "Gravel"), ("planting", "Planting bed")],
            "grass",
        ),
        number("area", "Area", 100, unit="m²", min=0.01),
        number("depth", "Surface depth", 100, unit="mm", min=0),
    ],
)
def landscape_finish(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate landscape surface volume and area."""
    volume = values["area"] * values["depth"] / 1000
    return result(
        summary={
            "surface": values["surface"],
            "areaM2": values["area"],
            "depthMm": values["depth"],
            "volumeM3": volume,
        }
    )


@feature(
    "architectureFinishes.facadeCladding",
    "Facade Cladding",
    part="floorPlan",
    fields=[
        text("wallId", "Wall id", ""),
        number("height", "Cladding height", 3000, unit="mm", min=1),
        number("panelWidth", "Panel width", 600, unit="mm", min=1),
    ],
)
def facade_cladding(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate cladding area and panel count for selected walls."""
    arch = require_arch(ctx)
    rows = []
    for w in arch.walls:
        if values["wallId"] and w.id != values["wallId"]:
            continue
        length = sum(math.dist(a, b) for a, b in zip(w.path, w.path[1:])) / 1000
        area = length * values["height"] / 1000
        rows.append(
            {
                "wall": w.id,
                "areaM2": area,
                "panelCount": math.ceil(length * 1000 / values["panelWidth"]),
            }
        )
    if not rows:
        raise FeatureInputError("No matching wall was found.")
    return result(
        summary={"wallCount": len(rows), "areaM2": sum(r["areaM2"] for r in rows)},
        tables=[
            table(
                "Facade cladding",
                [("wall", "Wall"), ("areaM2", "Area", "m²"), ("panelCount", "Panels")],
                rows,
            )
        ],
    )

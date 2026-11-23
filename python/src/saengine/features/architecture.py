"""Architecture - walls, doors, windows, rooms and vertical circulation tools."""

from __future__ import annotations

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


@feature(
    "architecture.addRoom",
    "Add Room",
    part="floorPlan",
    fields=[
        text("roomId", "Room id", "R-001"),
        text("name", "Room name", "Room"),
        text("number", "Room number", "001"),
        text("story", "Story id", "L1"),
        number("x", "X coordinate", 1000, unit="mm"),
        number("y", "Y coordinate", 1000, unit="mm"),
    ],
)
def add_room(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a room seed and list the resolved room boundary from the architecture model."""
    arch = require_arch(ctx)
    room = next((r for r in arch.rooms if r.id == values["roomId"]), None)
    if room is not None:
        raise FeatureInputError(f"Room id '{values['roomId']}' already exists.")

    payload = {
        "id": values["roomId"],
        "story": values["story"],
        "point": [values["x"], values["y"]],
        "name": values["name"],
        "number": values["number"],
    }
    row = {
        "room": values["roomId"],
        "name": values["name"],
        "story": values["story"],
        "x": values["x"],
        "y": values["y"],
        "bounded": False,
    }
    return result(
        summary={"roomId": values["roomId"], "story": values["story"], "bounded": False},
        tables=[
            table(
                "Room placement",
                [
                    ("room", "Room"),
                    ("name", "Name"),
                    ("story", "Story"),
                    ("x", "X", "mm"),
                    ("y", "Y", "mm"),
                ],
                [row],
            )
        ],
        notes=[
            "This prepares a room seed for the model. The existing project data is not modified.",
            write_json(ctx, "room-placement.json", payload),
        ],
    )


@feature(
    "architecture.roomBoundaries",
    "Room Boundaries",
    part="floorPlan",
    fields=[
        select(
            "boundaryMode",
            "Boundary mode",
            [
                ("walls", "Walls"),
                ("separators", "Room separators"),
                ("both", "Walls and separators"),
            ],
            "both",
        )
    ],
)
def room_boundaries(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List gross and net room boundary metrics found from walls and separators."""
    arch = require_arch(ctx)
    rows = room_metrics(ctx, arch)
    return result(
        summary={
            "roomCount": len(rows),
            "boundedCount": sum(r["bounded"] for r in rows),
            "boundaryMode": values["boundaryMode"],
        },
        tables=[
            table(
                "Room boundaries",
                [
                    ("room", "Room"),
                    ("story", "Story"),
                    ("bounded", "Closed"),
                    ("grossAreaM2", "Gross area", "m²"),
                    ("netAreaM2", "Net area", "m²"),
                ],
                rows,
            )
        ],
        notes=[
            "Net area removes wall footprints; missing room boundaries are reported rather than guessed."
        ],
    )


@feature(
    "architecture.roomTags",
    "Room Tags",
    part="floorPlan",
    fields=[
        select(
            "fields",
            "Tag fields",
            [
                ("nameNumberArea", "Name, number and area"),
                ("nameNumber", "Name and number"),
                ("area", "Area only"),
            ],
            "nameNumberArea",
        )
    ],
)
def room_tags(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build room tag text rows for name, number and area."""
    arch = require_arch(ctx)
    rows = []
    for row in room_metrics(ctx, arch):
        text_value = {
            "nameNumberArea": f"{row['name']} {row['number']} — {row['netAreaM2']:.2f} m²",
            "nameNumber": f"{row['name']} {row['number']}",
            "area": f"{row['netAreaM2']:.2f} m²",
        }[values["fields"]]
        rows.append({"room": row["room"], "tag": text_value})
    return result(
        summary={"tagCount": len(rows), "tagFields": values["fields"]},
        tables=[table("Room tags", [("room", "Room"), ("tag", "Tag text")], rows)],
        notes=["Tag rows are generated from the live architecture data."],
    )


@feature(
    "architecture.roomSchedule",
    "Room Schedule",
    part="floorPlan",
    fields=[
        select("areaBasis", "Area basis", [("net", "Net area"), ("gross", "Gross area")], "net")
    ],
)
def room_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a live room schedule with the selected area basis."""
    arch = require_arch(ctx)
    rows = room_metrics(ctx, arch)
    key = "netAreaM2" if values["areaBasis"] == "net" else "grossAreaM2"
    schedule = [
        {
            "room": r["room"],
            "name": r["name"],
            "number": r["number"],
            "story": r["story"],
            "areaM2": r[key],
        }
        for r in rows
    ]
    path = write_arch_export(
        ctx, "room-schedule.csv", csv_text(["room", "name", "number", "story", "areaM2"], schedule)
    )
    return result(
        summary={"roomCount": len(schedule), "areaBasis": values["areaBasis"], "exportPath": path},
        tables=[
            table(
                "Room schedule",
                [
                    ("room", "Room"),
                    ("name", "Name"),
                    ("number", "Number"),
                    ("story", "Story"),
                    ("areaM2", "Area", "m²"),
                ],
                schedule,
            )
        ],
        notes=[f"Room schedule written to {path}."],
    )


@feature(
    "architecture.drawWall",
    "Draw Wall",
    part="floorPlan",
    fields=[
        text("wallId", "Wall id", "W-001"),
        text("wallType", "Wall type id", ""),
        number("x1", "Start X", 0, unit="mm"),
        number("y1", "Start Y", 0, unit="mm"),
        number("x2", "End X", 3000, unit="mm"),
        number("y2", "End Y", 0, unit="mm"),
    ],
)
def draw_wall(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Prepare a wall centre-line segment and resolve its horizontal length."""
    import math

    require_arch(ctx)
    length = math.hypot(values["x2"] - values["x1"], values["y2"] - values["y1"])
    if length <= 0:
        raise FeatureInputError("The wall end must differ from its start.")
    payload = {
        "id": values["wallId"],
        "type": values["wallType"],
        "path": [[values["x1"], values["y1"]], [values["x2"], values["y2"]]],
        "base": "L1",
    }
    path = write_json(ctx, "wall-placement.json", payload)
    return result(
        summary={"wallId": values["wallId"], "lengthM": length / 1000, "exportPath": path},
        tables=[
            table(
                "Wall placement",
                [
                    ("id", "Wall"),
                    ("startX", "Start X", "mm"),
                    ("startY", "Start Y", "mm"),
                    ("endX", "End X", "mm"),
                    ("endY", "End Y", "mm"),
                    ("lengthM", "Length", "m"),
                ],
                [
                    {
                        "id": values["wallId"],
                        "startX": values["x1"],
                        "startY": values["y1"],
                        "endX": values["x2"],
                        "endY": values["y2"],
                        "lengthM": length / 1000,
                    }
                ],
            )
        ],
        notes=[
            f"Wall placement payload written to {path}; project geometry is not replaced automatically."
        ],
    )


@feature(
    "architecture.wallTypes",
    "Wall Types",
    part="floorPlan",
    fields=[text("wallTypeId", "Wall type id", "")],
)
def wall_types(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List compound wall types and their layer build-ups."""
    arch = require_arch(ctx)
    rows = []
    for t in arch.wallTypes:
        if values["wallTypeId"] and t.id != values["wallTypeId"]:
            continue
        rows.append(
            {
                "id": t.id,
                "name": t.name,
                "thicknessMm": t.thickness,
                "weightKnM2": t.weight,
                "layers": len(t.layers),
            }
        )
    if not rows:
        raise FeatureInputError("No matching wall type was found in the architecture data.")
    return result(
        summary={
            "wallTypeCount": len(rows),
            "maximumThicknessMm": max(r["thicknessMm"] for r in rows),
        },
        tables=[
            table(
                "Wall types",
                [
                    ("id", "Type"),
                    ("name", "Name"),
                    ("thicknessMm", "Thickness", "mm"),
                    ("weightKnM2", "Area weight", "kN/m²"),
                    ("layers", "Layers"),
                ],
                rows,
            )
        ],
    )


@feature(
    "architecture.wallJoins",
    "Wall Joins",
    part="floorPlan",
    fields=[number("tolerance", "Join tolerance", 25, unit="mm", min=0)],
)
def wall_joins(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Find wall endpoints within a supplied join tolerance."""
    import math

    arch = require_arch(ctx)
    pairs = []
    for i, a in enumerate(arch.walls):
        for b in arch.walls[i + 1 :]:
            pa, pb = a.path[-1], b.path[0]
            gap = math.dist(pa, pb)
            if gap <= values["tolerance"]:
                pairs.append({"wallA": a.id, "wallB": b.id, "gapMm": gap})
    return result(
        summary={"joinCount": len(pairs), "toleranceMm": values["tolerance"]},
        tables=[
            table(
                "Wall join candidates",
                [("wallA", "Wall A"), ("wallB", "Wall B"), ("gapMm", "Gap", "mm")],
                pairs,
            )
        ],
        notes=[
            "Candidates use end-to-start geometry at the configured tolerance; intersecting wall bodies are not merged."
        ],
    )


@feature(
    "architecture.wallLayerWrap",
    "Wall Layer Wrap",
    part="floorPlan",
    fields=[
        text("wallTypeId", "Wall type id", ""),
        number("wrapDepth", "Finish wrap depth", 50, unit="mm", min=0),
    ],
)
def wall_layer_wrap(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report finish wrap settings for wall ends and openings."""
    arch = require_arch(ctx)
    rows = [
        {
            "wallType": t.id,
            "thicknessMm": t.thickness,
            "wrapDepthMm": values["wrapDepth"],
            "layers": len(t.layers),
        }
        for t in arch.wallTypes
        if not values["wallTypeId"] or t.id == values["wallTypeId"]
    ]
    if not rows:
        raise FeatureInputError("No matching wall type was found.")
    return result(
        summary={"wallTypeCount": len(rows), "wrapDepthMm": values["wrapDepth"]},
        tables=[
            table(
                "Wall layer wraps",
                [
                    ("wallType", "Wall type"),
                    ("thicknessMm", "Thickness", "mm"),
                    ("wrapDepthMm", "Wrap depth", "mm"),
                    ("layers", "Layers"),
                ],
                rows,
            )
        ],
    )


@feature(
    "architecture.placeDoor",
    "Place Door",
    part="floorPlan",
    fields=[
        text("doorId", "Door id", "D-001"),
        text("doorType", "Door type id", ""),
        text("hostWall", "Host wall id", ""),
        number("offset", "Centre offset", 1500, unit="mm", min=0),
        select(
            "swing",
            "Swing side",
            [("left", "Left"), ("right", "Right"), ("both", "Both"), ("none", "None")],
            "left",
        ),
    ],
)
def place_door(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate a door host and write a placement record."""
    arch = require_arch(ctx)
    wall = next((w for w in arch.walls if w.id == values["hostWall"]), None)
    dtype = next((t for t in arch.doorTypes if t.id == values["doorType"]), None)
    if wall is None:
        raise FeatureInputError(f"Host wall '{values['hostWall']}' was not found.")
    if dtype is None:
        raise FeatureInputError(f"Door type '{values['doorType']}' was not found.")
    payload = {
        "id": values["doorId"],
        "type": values["doorType"],
        "wall": values["hostWall"],
        "offset": values["offset"],
        "swing": values["swing"],
    }
    path = write_json(ctx, "door-placement.json", payload)
    return result(
        summary={
            "doorId": values["doorId"],
            "widthMm": dtype.width,
            "heightMm": dtype.height,
            "offsetMm": values["offset"],
            "exportPath": path,
        },
        notes=[f"Door placement written to {path}; existing walls and openings are unchanged."],
    )


@feature(
    "architecture.placeWindow",
    "Place Window",
    part="floorPlan",
    fields=[
        text("windowId", "Window id", "WIN-001"),
        text("windowType", "Window type id", ""),
        text("hostWall", "Host wall id", ""),
        number("offset", "Centre offset", 1500, unit="mm", min=0),
        number("sill", "Sill height", 900, unit="mm", min=0),
    ],
)
def place_window(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate a window host and write a placement record."""
    arch = require_arch(ctx)
    wall = next((w for w in arch.walls if w.id == values["hostWall"]), None)
    wtype = next((t for t in arch.windowTypes if t.id == values["windowType"]), None)
    if wall is None:
        raise FeatureInputError(f"Host wall '{values['hostWall']}' was not found.")
    if wtype is None:
        raise FeatureInputError(f"Window type '{values['windowType']}' was not found.")
    payload = {
        "id": values["windowId"],
        "type": values["windowType"],
        "wall": values["hostWall"],
        "offset": values["offset"],
        "sill": values["sill"],
    }
    path = write_json(ctx, "window-placement.json", payload)
    return result(
        summary={
            "windowId": values["windowId"],
            "widthMm": wtype.width,
            "heightMm": wtype.height,
            "sillMm": values["sill"],
            "exportPath": path,
        }
    )


@feature(
    "architecture.openingCut",
    "Opening Cut",
    part="floorPlan",
    fields=[
        text("hostId", "Wall, floor or roof id", ""),
        number("width", "Opening width", 1000, unit="mm", min=1),
        number("height", "Opening height", 2100, unit="mm", min=1),
    ],
)
def opening_cut(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Prepare a free-opening cut record and report opening area."""
    require_arch(ctx)
    area = values["width"] * values["height"] * 1e-6
    payload = {"host": values["hostId"], "width": values["width"], "height": values["height"]}
    path = write_json(ctx, "opening-cut.json", payload)
    return result(
        summary={
            "openingAreaM2": area,
            "widthMm": values["width"],
            "heightMm": values["height"],
            "exportPath": path,
        },
        notes=[f"Opening cut prepared in {path}; host geometry is unchanged."],
    )


@feature(
    "architecture.architecturalColumns",
    "Architectural Columns",
    part="floorPlan",
    fields=[
        text("componentId", "Column component id", "COL-001"),
        number("width", "Width", 300, unit="mm", min=1),
        number("depth", "Depth", 300, unit="mm", min=1),
        number("height", "Height", 3000, unit="mm", min=1),
    ],
)
def architectural_columns(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute the plan and volume measures for an architectural column component."""
    require_arch(ctx)
    plan_area = values["width"] * values["depth"] * 1e-6
    volume = plan_area * values["height"] / 1000
    return result(
        summary={"componentId": values["componentId"], "planAreaM2": plan_area, "volumeM3": volume},
        tables=[
            table(
                "Architectural column",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Width", "value": f"{values['width']} mm"},
                    {"property": "Depth", "value": f"{values['depth']} mm"},
                    {"property": "Height", "value": f"{values['height']} mm"},
                ],
            )
        ],
    )


@feature(
    "architecture.stairs",
    "Stairs",
    part="floorPlan",
    fields=[
        text("stairId", "Stair id", "ST-001"),
        number("rise", "Total rise", 3200, unit="mm", min=1),
        number("numberOfRises", "Number of rises", 18, unit="riser", min=2),
        number("going", "Going", 250, unit="mm", min=100),
    ],
)
def stairs(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check stair rise, number of treads and individual riser height."""
    if values["numberOfRises"] < 2:
        raise FeatureInputError("A stair needs at least two rises.")
    riser = values["rise"] / values["numberOfRises"]
    tread_count = values["numberOfRises"] - 1
    run = tread_count * values["going"]
    return result(
        summary={
            "stairId": values["stairId"],
            "riserMm": riser,
            "treadCount": tread_count,
            "goingMm": values["going"],
            "runMm": run,
        },
        notes=[
            "Riser height is total rise divided by the number of rises; this does not apply a code comfort target."
        ],
    )


@feature(
    "architecture.railings",
    "Railings",
    part="floorPlan",
    fields=[
        text("railingId", "Railing id", "RG-001"),
        number("length", "Path length", 3000, unit="mm", min=1),
        number("height", "Railing height", 1100, unit="mm", min=1),
    ],
)
def railings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Prepare railing path length and height measures."""
    require_arch(ctx)
    return result(
        summary={
            "railingId": values["railingId"],
            "lengthM": values["length"] / 1000,
            "heightMm": values["height"],
        },
        tables=[
            table(
                "Railing",
                [
                    ("railingId", "Railing"),
                    ("lengthM", "Length", "m"),
                    ("heightMm", "Height", "mm"),
                ],
                [
                    {
                        "railingId": values["railingId"],
                        "lengthM": values["length"] / 1000,
                        "heightMm": values["height"],
                    }
                ],
            )
        ],
    )


@feature(
    "architecture.drawFloor",
    "Draw Floor",
    part="floorPlan",
    fields=[
        text("floorId", "Floor id", "F-001"),
        number("area", "Floor plan area", 20, unit="m²", min=0.01),
        number("thickness", "Slab thickness", 150, unit="mm", min=1),
    ],
)
def draw_floor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate floor slab volume and areal thickness."""
    require_arch(ctx)
    volume = values["area"] * values["thickness"] / 1000
    return result(
        summary={
            "floorId": values["floorId"],
            "areaM2": values["area"],
            "thicknessMm": values["thickness"],
            "volumeM3": volume,
        }
    )


@feature(
    "architecture.floorTypes",
    "Floor Types",
    part="floorPlan",
    fields=[
        text("floorTypeId", "Floor type id", "FLOOR-01"),
        number("thickness", "Build-up thickness", 250, unit="mm", min=1),
    ],
)
def floor_types(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Prepare a floor build-up definition for slab, screed and finish layers."""
    payload = {"id": values["floorTypeId"], "thickness": values["thickness"], "kind": "floor"}
    path = write_json(ctx, "floor-type.json", payload)
    return result(
        summary={
            "floorTypeId": values["floorTypeId"],
            "thicknessMm": values["thickness"],
            "exportPath": path,
        }
    )


@feature(
    "architecture.ceilingPlan",
    "Ceiling Plan",
    part="floorPlan",
    fields=[
        text("roomId", "Room id", ""),
        number("soffitHeight", "Soffit height", 2700, unit="mm", min=1),
    ],
)
def ceiling_plan(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a reflected-ceiling-plan data row for a room."""
    arch = require_arch(ctx)
    rows = [
        r for r in room_metrics(ctx, arch) if not values["roomId"] or r["room"] == values["roomId"]
    ]
    if not rows:
        raise FeatureInputError("No matching room was found.")
    plan = [
        {"room": r["room"], "areaM2": r["netAreaM2"], "soffitHeightMm": values["soffitHeight"]}
        for r in rows
    ]
    return result(
        summary={"roomCount": len(plan), "soffitHeightMm": values["soffitHeight"]},
        tables=[
            table(
                "Ceiling plan",
                [
                    ("room", "Room"),
                    ("areaM2", "Ceiling area", "m²"),
                    ("soffitHeightMm", "Soffit height", "mm"),
                ],
                plan,
            )
        ],
    )


@feature(
    "architecture.shaftOpening",
    "Shaft Opening",
    part="floorPlan",
    fields=[
        text("shaftId", "Shaft id", "S-001"),
        number("width", "Width", 1500, unit="mm", min=1),
        number("length", "Length", 1500, unit="mm", min=1),
        number("floors", "Number of floors", 3, unit="floor", min=1),
    ],
)
def shaft_opening(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate shaft area and the number of floor openings."""
    area = values["width"] * values["length"] * 1e-6
    if values["floors"] < 1:
        raise FeatureInputError("The number of floors must be at least one.")
    return result(
        summary={
            "shaftId": values["shaftId"],
            "shaftAreaM2": area,
            "floorOpeningCount": values["floors"],
            "cumulativeOpeningAreaM2": area * values["floors"],
        }
    )


@feature(
    "architecture.ramps",
    "Ramps",
    part="floorPlan",
    fields=[
        text("rampId", "Ramp id", "RP-001"),
        number("rise", "Rise", 600, unit="mm", min=1),
        number("run", "Run", 10000, unit="mm", min=1),
        number("width", "Width", 1200, unit="mm", min=1),
    ],
)
def ramps(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute ramp slope and sloped plan length."""
    import math

    if values["run"] <= 0:
        raise FeatureInputError("Ramp run must be positive.")
    slope = values["rise"] / values["run"]
    sloped = math.hypot(values["rise"], values["run"])
    return result(
        summary={
            "rampId": values["rampId"],
            "slope": slope,
            "slopePercent": slope * 100,
            "slopedLengthM": sloped / 1000,
            "widthMm": values["width"],
        },
        notes=[
            "Slope is rise/run. Comfort and maximum-slope requirements must be checked against the chosen user-input limits."
        ],
    )


@feature(
    "architecture.escalators",
    "Escalators",
    part="floorPlan",
    fields=[
        text("escalatorId", "Escalator id", "ESC-001"),
        number("rise", "Rise", 3200, unit="mm", min=1),
        number("run", "Run", 4000, unit="mm", min=1),
        number("width", "Width", 1000, unit="mm", min=1),
    ],
)
def escalators(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute escalator travel length and inclination angle."""
    import math

    length = math.hypot(values["rise"], values["run"])
    angle = math.degrees(math.atan2(values["rise"], values["run"]))
    return result(
        summary={
            "escalatorId": values["escalatorId"],
            "travelLengthM": length / 1000,
            "inclinationDeg": angle,
            "widthMm": values["width"],
        }
    )


@feature(
    "architecture.lifts",
    "Lifts",
    part="floorPlan",
    fields=[
        text("liftId", "Lift id", "LT-001"),
        number("width", "Car width", 1100, unit="mm", min=1),
        number("depth", "Car depth", 1400, unit="mm", min=1),
        number("capacity", "Rated capacity", 630, unit="kg", min=1),
    ],
)
def lifts(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute lift car plan area and installation envelope."""
    require_arch(ctx)
    area = values["width"] * values["depth"] * 1e-6
    return result(
        summary={"liftId": values["liftId"], "carAreaM2": area, "capacityKg": values["capacity"]}
    )


@feature(
    "architecture.liftShaft",
    "Lift Shaft",
    part="floorPlan",
    fields=[
        text("shaftId", "Lift shaft id", "LS-001"),
        number("width", "Shaft width", 2100, unit="mm", min=1),
        number("depth", "Shaft depth", 2200, unit="mm", min=1),
        number("pit", "Pit depth", 1500, unit="mm", min=0),
        number("headroom", "Headroom", 4200, unit="mm", min=0),
    ],
)
def lift_shaft(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate lift shaft plan area and pit/headroom envelope values."""
    require_arch(ctx)
    area = values["width"] * values["depth"] * 1e-6
    return result(
        summary={
            "shaftId": values["shaftId"],
            "shaftAreaM2": area,
            "pitMm": values["pit"],
            "headroomMm": values["headroom"],
        }
    )

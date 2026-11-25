"""Plan ribbon: create and transform structural layout geometry."""

from __future__ import annotations

import math

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
from saengine.features.plan_common import (
    member_rows,
    parse_point,
    plan_data,
    point_xy,
    profile,
    selected_members,
    story_map,
)

_KIND = [("beam", "Beam"), ("column", "Column"), ("wall", "Wall"), ("slab", "Slab")]


@feature(
    "plan.drawBeam",
    "Draw Beam",
    part="floorPlan",
    fields=[
        text("start", "Start grid point", "A-1"),
        text("end", "End grid point", "B-1"),
        text("story", "Storey id", "L1"),
        text("section", "Section type id", "B300x500"),
    ],
)
def draw_beam(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the plan span and direction for a beam between two grid points."""
    plan = plan_data(ctx)
    a, b = parse_point(values["start"]), parse_point(values["end"])
    x1, y1 = point_xy(plan, a)
    x2, y2 = point_xy(plan, b)
    if math.hypot(x2 - x1, y2 - y1) <= 1e-6:
        raise FeatureInputError("Beam start and end must be different points.")
    if values["story"] not in story_map(plan):
        raise FeatureInputError(f"Storey '{values['story']}' is not defined.")
    return result(
        summary={
            "story": values["story"],
            "spanM": math.hypot(x2 - x1, y2 - y1) / 1000,
            "angleDeg": math.degrees(math.atan2(y2 - y1, x2 - x1)),
            "sectionType": values["section"],
        },
        tables=[
            table(
                "Beam placement",
                [("end", "End"), ("xMm", "X", "mm"), ("yMm", "Y", "mm")],
                [{"end": "start", "xMm": x1, "yMm": y1}, {"end": "end", "xMm": x2, "yMm": y2}],
            )
        ],
        notes=["Geometry is resolved from the current grid, including entered point offsets."],
    )


@feature(
    "plan.drawColumn",
    "Draw Column",
    part="floorPlan",
    fields=[
        text("at", "Grid point", "A-1"),
        text("base", "Base storey id", "BASE"),
        text("top", "Top storey id", "L1"),
        text("section", "Section type id", "C400x600"),
    ],
)
def draw_column(ctx: FeatureContext, values: dict) -> dict:
    """Calculate a column's vertical storey interval and plan position."""
    plan = plan_data(ctx)
    stories, point = story_map(plan), parse_point(values["at"])
    if values["base"] not in stories or values["top"] not in stories:
        raise FeatureInputError("Choose existing base and top storeys.")
    height = float(stories[values["top"]]["elevation"]) - float(
        stories[values["base"]]["elevation"]
    )
    if height <= 0:
        raise FeatureInputError("The column top storey must be above its base storey.")
    x, y = point_xy(plan, point)
    return result(
        summary={
            "heightM": height / 1000,
            "sectionType": values["section"],
            "base": values["base"],
            "top": values["top"],
        },
        tables=[
            table(
                "Column placement",
                [("gridPoint", "Grid point"), ("xMm", "X", "mm"), ("yMm", "Y", "mm")],
                [{"gridPoint": values["at"], "xMm": x, "yMm": y}],
            )
        ],
    )


@feature(
    "plan.drawSlab",
    "Draw Slab",
    part="floorPlan",
    fields=[
        text("boundary", "Boundary grid points", "A-1,B-1,B-2,A-2"),
        text("story", "Storey id", "L1"),
        text("thickness", "Slab type id", "S150"),
    ],
)
def draw_slab(ctx: FeatureContext, values: dict) -> dict:
    """Compute polygon area and perimeter for a proposed slab panel."""
    plan = plan_data(ctx)
    if values["story"] not in story_map(plan):
        raise FeatureInputError(f"Storey '{values['story']}' is not defined.")
    points = [parse_point(v) for v in values["boundary"].split(",") if v.strip()]
    if len(points) < 3:
        raise FeatureInputError("A slab boundary needs at least three grid points.")
    xy = [point_xy(plan, p) for p in points]
    area = (
        abs(
            sum(
                xy[i][0] * xy[(i + 1) % len(xy)][1] - xy[(i + 1) % len(xy)][0] * xy[i][1]
                for i in range(len(xy))
            )
        )
        / 2_000_000
    )
    perimeter = (
        sum(
            math.hypot(xy[(i + 1) % len(xy)][0] - xy[i][0], xy[(i + 1) % len(xy)][1] - xy[i][1])
            for i in range(len(xy))
        )
        / 1000
    )
    if area <= 0:
        raise FeatureInputError("The slab boundary has zero enclosed area.")
    return result(
        summary={
            "areaM2": area,
            "perimeterM": perimeter,
            "cornerCount": len(points),
            "story": values["story"],
            "slabType": values["thickness"],
        },
        tables=[
            table(
                "Slab corners",
                [
                    ("order", "Order"),
                    ("gridPoint", "Grid point"),
                    ("xMm", "X", "mm"),
                    ("yMm", "Y", "mm"),
                ],
                [
                    {
                        "order": i + 1,
                        "gridPoint": values["boundary"].split(",")[i].strip(),
                        "xMm": xy[i][0],
                        "yMm": xy[i][1],
                    }
                    for i in range(len(xy))
                ],
            )
        ],
    )


@feature(
    "plan.drawWall",
    "Draw Wall",
    part="floorPlan",
    fields=[
        text("start", "Start grid point", "A-1"),
        text("end", "End grid point", "A-2"),
        text("base", "Base storey id", "BASE"),
        text("top", "Top storey id", "L1"),
        number("thicknessMm", "Wall thickness", 200, unit="mm", min=1),
    ],
)
def draw_wall(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the wall's plan run and vertical extent from the chosen levels."""
    plan = plan_data(ctx)
    stories = story_map(plan)
    if values["base"] not in stories or values["top"] not in stories:
        raise FeatureInputError("Choose existing base and top storeys.")
    z = float(stories[values["top"]]["elevation"]) - float(stories[values["base"]]["elevation"])
    a, b = point_xy(plan, parse_point(values["start"])), point_xy(plan, parse_point(values["end"]))
    run = math.hypot(b[0] - a[0], b[1] - a[1])
    if run <= 0 or z <= 0:
        raise FeatureInputError("Wall needs a positive plan run and a top level above its base.")
    return result(
        summary={
            "runM": run / 1000,
            "heightM": z / 1000,
            "faceAreaM2": run * z / 1_000_000,
            "thicknessMm": values["thicknessMm"],
        },
        notes=[
            "Face area is the run times the storey-to-storey height; openings are not deducted."
        ],
    )


@feature(
    "plan.trimExtend",
    "Trim/Extend",
    part="floorPlan",
    fields=[
        text("memberId", "Beam id", "B1"),
        number("startTrimMm", "Start trim (+) or extension (-)", 0, unit="mm"),
        number("endTrimMm", "End trim (+) or extension (-)", 0, unit="mm"),
    ],
)
def trim_extend(ctx: FeatureContext, values: dict) -> dict:
    """Compute the remaining beam span after trimming or extending its ends."""
    _, rows = profile(ctx)
    beam = next(
        (r for r in rows if r["id"] == values["memberId"] and r["category"] == "beam"), None
    )
    if beam is None:
        raise FeatureInputError("Choose an existing beam member id.")
    before = beam["lengthM"] * 1000
    after = before - float(values["startTrimMm"]) - float(values["endTrimMm"])
    if after <= 0:
        raise FeatureInputError("The proposed trims remove the entire beam length.")
    return result(
        summary={
            "memberId": values["memberId"],
            "originalLengthMm": before,
            "resultLengthMm": after,
            "changeMm": after - before,
        }
    )


@feature(
    "plan.splitMember",
    "Split Member",
    part="floorPlan",
    fields=[
        text("memberId", "Beam id", "B1"),
        number("splitRatio", "Split ratio from start", 0.5, min=0.01, max=0.99),
    ],
)
def split_member(ctx: FeatureContext, values: dict) -> dict:
    """Locate an interior split and report the two resulting beam lengths."""
    _, rows = profile(ctx)
    beam = next(
        (r for r in rows if r["id"] == values["memberId"] and r["category"] == "beam"), None
    )
    if beam is None:
        raise FeatureInputError("Choose an existing beam member id.")
    first = beam["lengthM"] * values["splitRatio"]
    return result(
        summary={
            "memberId": beam["id"],
            "splitDistanceM": first,
            "firstLengthM": first,
            "secondLengthM": beam["lengthM"] - first,
        },
        notes=[
            "The split point is interpolated along the member centerline; member ids and connectivity are not changed by this preview."
        ],
    )


@feature(
    "plan.moveMember",
    "Move Member",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated)", "B1"),
        number("dxMm", "Move X", 0, unit="mm"),
        number("dyMm", "Move Y", 0, unit="mm"),
    ],
)
def move_member(ctx: FeatureContext, values: dict) -> dict:
    """Translate selected member plan coordinates and show the proposed endpoints."""
    _, rows = profile(ctx)
    chosen = selected_members(rows, values["memberIds"])
    moved = [
        {
            "id": r["id"],
            "startXmm": r.get("x1Mm", 0) + values["dxMm"],
            "startYmm": r.get("y1Mm", 0) + values["dyMm"],
            "endXmm": r.get("x2Mm", 0) + values["dxMm"],
            "endYmm": r.get("y2Mm", 0) + values["dyMm"],
        }
        for r in chosen
    ]
    return result(
        summary={"movedMemberCount": len(moved), "dxMm": values["dxMm"], "dyMm": values["dyMm"]},
        tables=[
            table(
                "Translated member endpoints",
                [
                    ("id", "Member"),
                    ("startXmm", "Start X", "mm"),
                    ("startYmm", "Start Y", "mm"),
                    ("endXmm", "End X", "mm"),
                    ("endYmm", "End Y", "mm"),
                ],
                moved,
            )
        ],
    )


@feature(
    "plan.copyMember",
    "Copy Member",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated)", "B1"),
        number("copies", "Number of copies", 1, min=1, max=100),
        number("spacingMm", "Copy spacing", 3000, unit="mm", min=1),
        select("direction", "Direction", [("x", "X"), ("y", "Y")]),
    ],
)
def copy_member(ctx: FeatureContext, values: dict) -> dict:
    """Lay out a linear array of translated member coordinates."""
    _, rows = profile(ctx)
    chosen = selected_members(rows, values["memberIds"])
    axis = values["direction"]
    copies = int(values["copies"])
    generated = [
        {
            "sourceId": row["id"],
            "copyIndex": n,
            "offsetMm": values["spacingMm"] * n,
            "startXmm": row.get("x1Mm", 0) + (values["spacingMm"] * n if axis == "x" else 0),
            "startYmm": row.get("y1Mm", 0) + (values["spacingMm"] * n if axis == "y" else 0),
            "endXmm": row.get("x2Mm", 0) + (values["spacingMm"] * n if axis == "x" else 0),
            "endYmm": row.get("y2Mm", 0) + (values["spacingMm"] * n if axis == "y" else 0),
        }
        for row in chosen
        for n in range(1, copies + 1)
    ]
    return result(
        summary={
            "sourceCount": len(chosen),
            "copyCount": len(generated),
            "direction": axis,
            "spacingMm": values["spacingMm"],
        },
        tables=[
            table(
                "Copy placement preview",
                [
                    ("sourceId", "Source"),
                    ("copyIndex", "Copy"),
                    ("offsetMm", "Offset", "mm"),
                    ("startXmm", "Start X", "mm"),
                    ("startYmm", "Start Y", "mm"),
                    ("endXmm", "End X", "mm"),
                    ("endYmm", "End Y", "mm"),
                ],
                generated,
            )
        ],
    )


@feature(
    "plan.loadDisplay",
    "Load Display",
    part="floorPlan",
    fields=[
        checkbox("showValues", "Show load values", True),
        checkbox("showArrows", "Show load arrows", True),
        select(
            "case",
            "Load case",
            [
                ("all", "All cases"),
                ("D", "Dead"),
                ("SD", "Superimposed dead"),
                ("L", "Live"),
                ("Lr", "Roof live"),
            ],
            "all",
        ),
    ],
)
def load_display(ctx: FeatureContext, values: dict) -> dict:
    """Prepare a display table of actual member loads by case and target member."""
    plan_data(ctx)
    from saengine.features.plan_common import loads_data

    data = loads_data(ctx)
    members = {row["id"]: row for row in member_rows(plan_data(ctx))}
    loads = [
        load
        for load in data.get("loads", [])
        if values["case"] == "all" or load.get("case", "SD") == values["case"]
    ]
    rows = [
        {
            "loadId": load.get("id"),
            "member": load.get("member"),
            "kind": load.get("kind", "line"),
            "case": load.get("case", "SD"),
            "memberExists": load.get("member") in members,
            "value": load.get("value"),
        }
        for load in loads
    ]
    return result(
        summary={
            "loadCount": len(rows),
            "showValues": values["showValues"],
            "showArrows": values["showArrows"],
        },
        tables=[
            table(
                "Displayed member loads",
                [
                    ("loadId", "Load"),
                    ("member", "Member"),
                    ("kind", "Kind"),
                    ("case", "Case"),
                    ("memberExists", "Member exists"),
                    ("value", "Value"),
                ],
                rows,
            )
        ],
    )


@feature(
    "plan.clearLoads",
    "Clear Loads",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated)", "B1"),
        select(
            "case",
            "Load case",
            [
                ("all", "All cases"),
                ("D", "Dead"),
                ("SD", "Superimposed dead"),
                ("L", "Live"),
                ("Lr", "Roof live"),
            ],
            "all",
        ),
    ],
)
def clear_loads(ctx: FeatureContext, values: dict) -> dict:
    """List the load records that match the requested clear operation."""
    plan_data(ctx)
    from saengine.features.plan_common import loads_data

    data = loads_data(ctx)
    members = {row["id"] for row in member_rows(plan_data(ctx))}
    ids = {part.strip() for part in values["memberIds"].split(",") if part.strip()}
    if ids - members:
        raise FeatureInputError(f"Unknown member id(s): {', '.join(sorted(ids - members))}.")
    matched = [
        load
        for load in data.get("loads", [])
        if (not ids or load.get("member") in ids)
        and (values["case"] == "all" or load.get("case", "SD") == values["case"])
    ]
    return result(
        summary={"loadsToClear": len(matched), "case": values["case"]},
        tables=[
            table(
                "Matching load records",
                [("id", "Load"), ("member", "Member"), ("case", "Case"), ("kind", "Kind")],
                [
                    {
                        "id": item.get("id"),
                        "member": item.get("member"),
                        "case": item.get("case", "SD"),
                        "kind": item.get("kind", "line"),
                    }
                    for item in matched
                ],
            )
        ],
        notes=[
            "This preview identifies records in loads.json; the report does not alter the source file."
        ],
    )


@feature(
    "plan.selectSimilar",
    "Select Similar",
    part="floorPlan",
    fields=[
        text("memberId", "Reference member id", "B1"),
        checkbox("matchStorey", "Also match storey", False),
    ],
)
def select_similar(ctx: FeatureContext, values: dict) -> dict:
    """Find members with the same object type and category as the reference member."""
    _, rows = profile(ctx)
    source = next((r for r in rows if r["id"] == values["memberId"]), None)
    if source is None:
        raise FeatureInputError("Choose an existing member id.")
    matches = [
        r
        for r in rows
        if r["category"] == source["category"]
        and r["type"] == source["type"]
        and (not values["matchStorey"] or r["story"] == source["story"])
    ]
    return result(
        summary={"referenceId": source["id"], "similarCount": len(matches)},
        tables=[
            table(
                "Similar members",
                [
                    ("id", "Member"),
                    ("category", "Category"),
                    ("type", "Section type"),
                    ("story", "Storey"),
                ],
                matches,
            )
        ],
    )


@feature(
    "plan.filterSelection",
    "Filter Selection",
    part="floorPlan",
    fields=[
        select(
            "category",
            "Member category",
            [
                ("all", "All"),
                ("beam", "Beams"),
                ("column", "Columns"),
                ("wall", "Walls"),
                ("slab", "Slabs"),
                ("footing", "Footings"),
            ],
            "all",
        ),
        text("story", "Storey id (blank for any)", ""),
        text("type", "Object type id (blank for any)", ""),
    ],
)
def filter_selection(ctx: FeatureContext, values: dict) -> dict:
    """Filter current model members by category, storey and object type."""
    _, rows = profile(ctx)
    matches = [
        r
        for r in rows
        if (values["category"] == "all" or r["category"] == values["category"])
        and (not values["story"] or r["story"] == values["story"])
        and (not values["type"] or r["type"] == values["type"])
    ]
    return result(
        summary={"matchedCount": len(matches), "totalCount": len(rows)},
        tables=[
            table(
                "Filtered selection",
                [
                    ("id", "Member"),
                    ("category", "Category"),
                    ("type", "Object type"),
                    ("story", "Storey"),
                ],
                matches,
            )
        ],
    )


@feature(
    "plan.isolateSelection",
    "Isolate Selection",
    part="floorPlan",
    fields=[text("memberIds", "Member ids to isolate", "B1")],
)
def isolate_selection(ctx: FeatureContext, values: dict) -> dict:
    """Separate the listed members from the rest of the model for a view isolation."""
    _, rows = profile(ctx)
    kept = selected_members(rows, values["memberIds"])
    hidden = [row for row in rows if row["id"] not in {item["id"] for item in kept}]
    return result(
        summary={"visibleMemberCount": len(kept), "hiddenMemberCount": len(hidden)},
        tables=[
            table(
                "Visible members",
                [("id", "Member"), ("category", "Category"), ("story", "Storey")],
                kept,
            )
        ],
        notes=[
            "The returned sets describe the isolated view; they do not change the floor-plan model."
        ],
    )


@feature(
    "plan.copyToStorey",
    "Copy to Storey",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated)", "B1"),
        text("targetStorey", "Target storey id", "L2"),
    ],
)
def copy_to_storey(ctx: FeatureContext, values: dict) -> dict:
    """Resolve copied member locations at another existing floor level."""
    plan, rows = profile(ctx)
    stories = story_map(plan)
    if values["targetStorey"] not in stories:
        raise FeatureInputError("Target storey does not exist.")
    chosen = selected_members(rows, values["memberIds"])
    source_story = {story["id"]: float(story["elevation"]) for story in plan["stories"]}
    target_z = source_story[values["targetStorey"]]
    copied = [
        {
            "sourceId": row["id"],
            "targetStorey": values["targetStorey"],
            "targetElevationMm": target_z,
            "category": row["category"],
            "type": row["type"],
        }
        for row in chosen
        if row["category"] in {"beam", "slab", "footing"}
    ]
    return result(
        summary={
            "requestedCount": len(chosen),
            "copyablePlanMembers": len(copied),
            "targetElevationMm": target_z,
        },
        tables=[
            table(
                "Storey copy preview",
                [
                    ("sourceId", "Source"),
                    ("category", "Category"),
                    ("type", "Type"),
                    ("targetStorey", "Target"),
                    ("targetElevationMm", "Elevation", "mm"),
                ],
                copied,
            )
        ],
        notes=["Columns and walls span storeys and are omitted from a plan-level copy preview."],
    )


@feature(
    "plan.assignStorey",
    "Assign Storey",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated)", "B1"),
        text("targetStorey", "Target storey id", "L2"),
    ],
)
def assign_storey(ctx: FeatureContext, values: dict) -> dict:
    """Preview reassignment of plan-level beams, slabs and footings to one storey."""
    plan, rows = profile(ctx)
    if values["targetStorey"] not in story_map(plan):
        raise FeatureInputError("Target storey does not exist.")
    chosen = selected_members(rows, values["memberIds"])
    eligible = [r for r in chosen if r["category"] in {"beam", "slab", "footing"}]
    return result(
        summary={
            "targetStorey": values["targetStorey"],
            "eligibleCount": len(eligible),
            "skippedMultiStoreyCount": len(chosen) - len(eligible),
        },
        tables=[
            table(
                "Storey assignments",
                [
                    ("id", "Member"),
                    ("category", "Category"),
                    ("previousStorey", "Current storey"),
                    ("targetStorey", "Target storey"),
                ],
                [
                    {
                        "id": r["id"],
                        "category": r["category"],
                        "previousStorey": r["story"],
                        "targetStorey": values["targetStorey"],
                    }
                    for r in eligible
                ],
            )
        ],
    )


@feature(
    "plan.referencePlane",
    "Reference Plane",
    part="floorPlan",
    fields=[
        text("name", "Plane name", "Grid A"),
        select("orientation", "Orientation", [("x", "Constant X"), ("y", "Constant Y")]),
        number("offsetMm", "Offset from origin", 0, unit="mm"),
    ],
    requires_project=False,
)
def reference_plane(ctx: FeatureContext, values: dict) -> dict:
    """Describe the reference plane coordinate used to align members."""
    return result(
        summary={
            "name": values["name"],
            "orientation": values["orientation"],
            "coordinateMm": values["offsetMm"],
        },
        notes=["A constant-X plane is parallel to Y; a constant-Y plane is parallel to X."],
    )


@feature(
    "plan.drawBrace",
    "Draw Brace",
    part="floorPlan",
    fields=[
        text("start", "Start grid point", "A-1"),
        text("end", "End grid point", "B-2"),
        number("storeyHeightMm", "Storey height", 3200, unit="mm", min=1),
        number("sectionAreaMm2", "Brace area", 2500, unit="mm²", min=1),
    ],
)
def draw_brace(ctx: FeatureContext, values: dict) -> dict:
    """Calculate brace diagonal length and inclination for a selected bay."""
    plan = plan_data(ctx)
    a, b = point_xy(plan, parse_point(values["start"])), point_xy(plan, parse_point(values["end"]))
    bay = math.hypot(b[0] - a[0], b[1] - a[1])
    if bay <= 0:
        raise FeatureInputError("Brace endpoints must be distinct.")
    length = math.hypot(bay, values["storeyHeightMm"])
    return result(
        summary={
            "bayWidthM": bay / 1000,
            "diagonalLengthM": length / 1000,
            "angleFromHorizontalDeg": math.degrees(math.atan2(values["storeyHeightMm"], bay)),
            "areaMm2": values["sectionAreaMm2"],
        }
    )


@feature(
    "plan.drawCantilever",
    "Draw Cantilever",
    part="floorPlan",
    fields=[
        text("supportPoint", "Support grid point", "A-1"),
        text("tipPoint", "Tip grid point", "B-1"),
        number("lineLoadKnPerM", "Uniform service load", 0, unit="kN/m", min=0),
    ],
)
def draw_cantilever(ctx: FeatureContext, values: dict) -> dict:
    """Estimate cantilever root shear and moment from a uniform line load."""
    plan = plan_data(ctx)
    a, b = (
        point_xy(plan, parse_point(values["supportPoint"])),
        point_xy(plan, parse_point(values["tipPoint"])),
    )
    length = math.hypot(b[0] - a[0], b[1] - a[1]) / 1000
    if length <= 0:
        raise FeatureInputError("Cantilever support and tip must be different points.")
    q = values["lineLoadKnPerM"]
    return result(
        summary={"lengthM": length, "rootShearKn": q * length, "rootMomentKnM": q * length**2 / 2},
        notes=[
            "Uniform load on a prismatic cantilever; the supplied service load is not factored."
        ],
    )


@feature(
    "plan.drawOpening",
    "Draw Opening",
    part="floorPlan",
    fields=[
        number("widthMm", "Opening width", 1200, unit="mm", min=1),
        number("lengthMm", "Opening length", 1800, unit="mm", min=1),
        number("edgeDistanceMm", "Nearest slab edge distance", 600, unit="mm", min=0),
        number("slabThicknessMm", "Slab thickness", 150, unit="mm", min=1),
    ],
)
def draw_opening(ctx: FeatureContext, values: dict) -> dict:
    """Calculate opening area and remaining edge ligament for a slab cutout."""
    area = values["widthMm"] * values["lengthMm"] / 1_000_000
    ligament = values["edgeDistanceMm"] - values["slabThicknessMm"]
    return result(
        summary={
            "openingAreaM2": area,
            "perimeterM": 2 * (values["widthMm"] + values["lengthMm"]) / 1000,
            "edgeLigamentMm": ligament,
            "nearEdge": ligament < values["slabThicknessMm"],
        },
        notes=[
            "Edge ligament is a geometric screen only; reinforcement and punching checks are separate design checks."
        ],
    )


@feature(
    "plan.mirrorMembers",
    "Mirror Members",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated)", "B1"),
        select("axis", "Mirror axis", [("x", "X axis"), ("y", "Y axis")]),
        number("axisCoordinateMm", "Axis coordinate", 0, unit="mm"),
    ],
)
def mirror_members(ctx: FeatureContext, values: dict) -> dict:
    """Reflect selected member endpoints through the requested global plan axis."""
    _, rows = profile(ctx)
    chosen = selected_members(rows, values["memberIds"])
    key = "y1Mm" if values["axis"] == "x" else "x1Mm"
    endkey = "y2Mm" if values["axis"] == "x" else "x2Mm"
    new_start = lambda r: 2 * values["axisCoordinateMm"] - r.get(key, 0)
    new_end = lambda r: 2 * values["axisCoordinateMm"] - r.get(endkey, 0)
    out = [
        {
            "id": r["id"],
            "axis": values["axis"],
            "mirroredStartMm": new_start(r),
            "mirroredEndMm": new_end(r),
        }
        for r in chosen
    ]
    return result(
        summary={"mirroredCount": len(out), "axisCoordinateMm": values["axisCoordinateMm"]},
        tables=[
            table(
                "Reflected coordinates",
                [
                    ("id", "Member"),
                    ("axis", "Axis"),
                    ("mirroredStartMm", "Start coordinate", "mm"),
                    ("mirroredEndMm", "End coordinate", "mm"),
                ],
                out,
            )
        ],
    )


@feature(
    "plan.rotateMembers",
    "Rotate Members",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated)", "B1"),
        number("angleDeg", "Rotation", 90, unit="°"),
        number("originXmm", "Origin X", 0, unit="mm"),
        number("originYmm", "Origin Y", 0, unit="mm"),
    ],
)
def rotate_members(ctx: FeatureContext, values: dict) -> dict:
    """Rotate selected member endpoints about an explicit plan origin."""
    _, rows = profile(ctx)
    chosen = selected_members(rows, values["memberIds"])
    angle = math.radians(values["angleDeg"])
    c, s = math.cos(angle), math.sin(angle)

    def rotate(x: float, y: float) -> tuple[float, float]:
        dx, dy = x - values["originXmm"], y - values["originYmm"]
        return values["originXmm"] + c * dx - s * dy, values["originYmm"] + s * dx + c * dy

    rotated = []
    for member in chosen:
        a, b = (
            rotate(member.get("x1Mm", 0), member.get("y1Mm", 0)),
            rotate(member.get("x2Mm", 0), member.get("y2Mm", 0)),
        )
        rotated.append(
            {"id": member["id"], "startXmm": a[0], "startYmm": a[1], "endXmm": b[0], "endYmm": b[1]}
        )
    return result(
        summary={"rotatedCount": len(rotated), "angleDeg": values["angleDeg"]},
        tables=[
            table(
                "Rotated member endpoints",
                [
                    ("id", "Member"),
                    ("startXmm", "Start X", "mm"),
                    ("startYmm", "Start Y", "mm"),
                    ("endXmm", "End X", "mm"),
                    ("endYmm", "End Y", "mm"),
                ],
                rotated,
            )
        ],
    )


@feature(
    "plan.arrayMembers",
    "Array Members",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated)", "B1"),
        select("pattern", "Array pattern", [("linear", "Linear"), ("radial", "Radial")]),
        number("count", "Number of copies", 3, min=1, max=100),
        number("spacingMm", "Linear spacing", 3000, unit="mm", min=1),
        number("angleDeg", "Radial increment", 90, unit="°"),
    ],
)
def array_members(ctx: FeatureContext, values: dict) -> dict:
    """Calculate linear offsets or radial rotations for a selected member set."""
    _, rows = profile(ctx)
    chosen = selected_members(rows, values["memberIds"])
    placed = []
    for item in chosen:
        for index in range(1, int(values["count"]) + 1):
            if values["pattern"] == "linear":
                placed.append(
                    {
                        "sourceId": item["id"],
                        "copyIndex": index,
                        "dxMm": index * values["spacingMm"],
                        "dyMm": 0.0,
                        "rotationDeg": 0.0,
                    }
                )
            else:
                placed.append(
                    {
                        "sourceId": item["id"],
                        "copyIndex": index,
                        "dxMm": 0.0,
                        "dyMm": 0.0,
                        "rotationDeg": index * values["angleDeg"],
                    }
                )
    return result(
        summary={"pattern": values["pattern"], "copyCount": len(placed)},
        tables=[
            table(
                "Array transforms",
                [
                    ("sourceId", "Source"),
                    ("copyIndex", "Copy"),
                    ("dxMm", "X offset", "mm"),
                    ("dyMm", "Y offset", "mm"),
                    ("rotationDeg", "Rotation", "°"),
                ],
                placed,
            )
        ],
    )

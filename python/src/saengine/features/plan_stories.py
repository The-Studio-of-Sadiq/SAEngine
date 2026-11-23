"""Stories ribbon: levels, floor-to-floor geometry and storey templates."""

from __future__ import annotations

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
    ordered_stories,
    plan_data,
    profile,
    story_map,
)


@feature(
    "stories.addStorey",
    "Add Storey",
    part="floorPlan",
    fields=[
        text("id", "New storey id", "L4"),
        text("name", "Storey name", "Level 4"),
        number("heightMm", "Height above current top", 3000, unit="mm", min=1),
    ],
)
def add_storey(ctx: FeatureContext, values: dict) -> dict:
    """Propose one new level above the current roof and report its elevation."""
    plan = plan_data(ctx)
    stories = ordered_stories(plan)
    if any(s["id"] == values["id"] for s in stories):
        raise FeatureInputError("Storey id already exists.")
    elevation = (
        float(stories[-1]["elevation"]) + values["heightMm"] if stories else values["heightMm"]
    )
    return result(
        summary={
            "newStoreyId": values["id"],
            "elevationMm": elevation,
            "heightMm": values["heightMm"],
        },
        tables=[
            table(
                "New storey",
                [("id", "Id"), ("name", "Name"), ("elevationMm", "Elevation", "mm")],
                [{"id": values["id"], "name": values["name"], "elevationMm": elevation}],
            )
        ],
    )


@feature(
    "stories.insertStoreys",
    "Insert Storeys",
    part="floorPlan",
    fields=[
        text("baseId", "First new storey id", "L4"),
        text("namePrefix", "Storey name prefix", "Level "),
        number("count", "Number of storeys", 3, min=1, max=100),
        number("heightMm", "Storey height", 3000, unit="mm", min=1),
        select("location", "Insert relative to", [("above", "Above current top")], "above"),
    ],
)
def insert_storeys(ctx: FeatureContext, values: dict) -> dict:
    """Generate a consecutive run of new storey ids and elevations above the current roof."""
    plan = plan_data(ctx)
    stories = ordered_stories(plan)
    base = float(stories[-1]["elevation"]) if stories else 0
    try:
        prefix, suffix = (
            values["baseId"].rstrip("0123456789"),
            int(values["baseId"][len(values["baseId"].rstrip("0123456789")) :]),
        )
    except ValueError as exc:
        raise FeatureInputError("First new storey id must end with a number, such as L4.") from exc
    existing = {s["id"] for s in stories}
    rows = []
    for i in range(int(values["count"])):
        sid = f"{prefix}{suffix + i}"
        if sid in existing:
            raise FeatureInputError(f"Storey id '{sid}' already exists.")
        rows.append(
            {
                "id": sid,
                "name": f"{values['namePrefix']}{suffix + i}",
                "elevationMm": base + (i + 1) * values["heightMm"],
            }
        )
    return result(
        summary={"storeysToInsert": len(rows), "topElevationMm": rows[-1]["elevationMm"]},
        tables=[
            table(
                "Inserted storeys",
                [("id", "Id"), ("name", "Name"), ("elevationMm", "Elevation", "mm")],
                rows,
            )
        ],
    )


@feature(
    "stories.deleteStorey",
    "Delete Storey",
    part="floorPlan",
    fields=[
        text("storeyId", "Storey id", "L3"),
        checkbox("includeElementImpact", "Report associated elements", True),
    ],
)
def delete_storey(ctx: FeatureContext, values: dict) -> dict:
    """Identify references and member counts that would be affected by deleting a level."""
    plan, rows = profile(ctx)
    story = next((s for s in plan["stories"] if s["id"] == values["storeyId"]), None)
    if story is None:
        raise FeatureInputError("Storey id was not found.")
    affected = [r for r in rows if r["story"] == story["id"]]
    vertical = [
        m
        for g in ("columns", "walls")
        for m in plan[g]
        if m.get("base") == story["id"] or m.get("top") == story["id"]
    ]
    return result(
        summary={
            "storeyId": story["id"],
            "membersAtLevel": len(affected) if values["includeElementImpact"] else 0,
            "verticalMembersReferencingLevel": len(vertical),
            "deletionBlockedByReferences": bool(vertical),
        },
        tables=[
            table(
                "Members using this level",
                [("id", "Member"), ("category", "Category"), ("type", "Type")],
                affected
                + [
                    {"id": m["id"], "category": "vertical reference", "type": m["type"]}
                    for m in vertical
                ],
            )
        ],
    )


@feature("stories.storeyTable", "Storey Table", part="floorPlan", fields=[])
def storey_table(ctx: FeatureContext, values: dict) -> dict:
    """Tabulate levels, floor-to-floor heights and direct member counts."""
    plan, rows = profile(ctx)
    stories = ordered_stories(plan)
    out = []
    for i, s in enumerate(stories):
        next_elev = float(stories[i + 1]["elevation"]) if i + 1 < len(stories) else None
        out.append(
            {
                "id": s["id"],
                "name": s["name"],
                "elevationMm": s["elevation"],
                "heightToNextMm": next_elev - float(s["elevation"])
                if next_elev is not None
                else None,
                "memberCount": sum(r["story"] == s["id"] for r in rows),
                "similarTo": s.get("similarTo"),
            }
        )
    return result(
        summary={
            "storeyCount": len(out),
            "buildingHeightM": (float(stories[-1]["elevation"]) - float(stories[0]["elevation"]))
            / 1000
            if len(stories) > 1
            else 0,
        },
        tables=[
            table(
                "Storey schedule",
                [
                    ("id", "Id"),
                    ("name", "Name"),
                    ("elevationMm", "Elevation", "mm"),
                    ("heightToNextMm", "Height to next", "mm"),
                    ("memberCount", "Members"),
                    ("similarTo", "Similar to"),
                ],
                out,
            )
        ],
    )


@feature(
    "stories.setBaseLevel",
    "Set Base Level",
    part="floorPlan",
    fields=[
        text("storeyId", "Base storey id", "BASE"),
        number("targetElevationMm", "Target elevation", 0, unit="mm"),
    ],
)
def set_base_level(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the datum shift needed to move the selected lowest level to a target elevation."""
    plan = plan_data(ctx)
    stories = ordered_stories(plan)
    if not stories or stories[0]["id"] != values["storeyId"]:
        raise FeatureInputError("Choose the lowest defined storey as the base.")
    shift = values["targetElevationMm"] - float(stories[0]["elevation"])
    return result(
        summary={
            "baseStorey": values["storeyId"],
            "currentElevationMm": stories[0]["elevation"],
            "targetElevationMm": values["targetElevationMm"],
            "modelDatumShiftMm": shift,
        },
        notes=[
            "Applying a base datum shift requires moving all story elevations and retaining the same relative heights."
        ],
    )


@feature(
    "stories.levelHeight",
    "Level Height",
    part="floorPlan",
    fields=[text("storeyId", "Lower storey id", "L1")],
)
def level_height(ctx: FeatureContext, values: dict) -> dict:
    """Calculate floor-to-floor height from one story to the next level above."""
    plan = plan_data(ctx)
    stories = ordered_stories(plan)
    index = next((i for i, s in enumerate(stories) if s["id"] == values["storeyId"]), None)
    if index is None or index + 1 >= len(stories):
        raise FeatureInputError("Choose a storey that has a defined level above it.")
    low, high = stories[index], stories[index + 1]
    return result(
        summary={
            "lowerStorey": low["id"],
            "upperStorey": high["id"],
            "heightMm": float(high["elevation"]) - float(low["elevation"]),
            "heightM": (float(high["elevation"]) - float(low["elevation"])) / 1000,
        }
    )


@feature(
    "stories.masterLevel",
    "Master Level",
    part="floorPlan",
    fields=[
        text("masterId", "Master storey id", "L1"),
        text("similarIds", "Similar storey ids", "L2,L3"),
    ],
)
def master_level(ctx: FeatureContext, values: dict) -> dict:
    """Validate a master floor and list the requested similar-story relationships."""
    plan = plan_data(ctx)
    ids = {s["id"] for s in plan["stories"]}
    similar = [x.strip() for x in values["similarIds"].split(",") if x.strip()]
    if values["masterId"] not in ids or any(x not in ids for x in similar):
        raise FeatureInputError("Master and similar storeys must exist in the current floor plan.")
    if values["masterId"] in similar:
        raise FeatureInputError("A storey cannot be similar to itself.")
    return result(
        summary={"masterStorey": values["masterId"], "similarStoreyCount": len(similar)},
        tables=[
            table(
                "Typical floor relationships",
                [("master", "Master storey"), ("similar", "Similar storey")],
                [{"master": values["masterId"], "similar": x} for x in similar],
            )
        ],
    )


@feature(
    "stories.storeyPlan",
    "Storey Plan",
    part="floorPlan",
    fields=[text("storeyId", "Storey id", "L1")],
)
def storey_plan(ctx: FeatureContext, values: dict) -> dict:
    """Summarise plan members and slab area for the selected floor plan."""
    plan, rows = profile(ctx)
    if values["storeyId"] not in {s["id"] for s in plan["stories"]}:
        raise FeatureInputError("Storey id was not found.")
    shown = [r for r in rows if r["story"] == values["storeyId"]]
    return result(
        summary={
            "storey": values["storeyId"],
            "memberCount": len(shown),
            "slabAreaM2": sum(r.get("areaM2", 0) for r in shown),
        },
        tables=[
            table(
                "Floor plan members",
                [
                    ("id", "Member"),
                    ("category", "Category"),
                    ("type", "Type"),
                    ("lengthM", "Length", "m"),
                    ("areaM2", "Area", "m²"),
                ],
                shown,
            )
        ],
    )


@feature(
    "stories.isolateStorey",
    "Isolate Storey",
    part="floorPlan",
    fields=[
        text("storeyId", "Storey id", "L1"),
        checkbox("showWallsThrough", "Show walls spanning this storey", True),
    ],
)
def isolate_storey(ctx: FeatureContext, values: dict) -> dict:
    """Select plan members assigned to a level plus vertical members that pass through it."""
    plan, rows = profile(ctx)
    story = next((s for s in plan["stories"] if s["id"] == values["storeyId"]), None)
    if story is None:
        raise FeatureInputError("Storey id was not found.")
    z = float(story["elevation"])
    selected = []
    raw = {m["id"]: m for group in ("columns", "walls") for m in plan[group]}
    for row in rows:
        if row["story"] == values["storeyId"]:
            selected.append(row)
        elif values["showWallsThrough"] and row["category"] in {"column", "wall"}:
            member = raw[row["id"]]
            levels = story_map(plan)
            lo = float(levels[member["base"]]["elevation"])
            hi = float(levels[member["top"]]["elevation"])
            if lo <= z <= hi:
                selected.append(row)
    return result(
        summary={"visibleMemberCount": len(selected), "storey": values["storeyId"]},
        tables=[
            table(
                "Isolated storey members",
                [
                    ("id", "Member"),
                    ("category", "Category"),
                    ("type", "Type"),
                    ("story", "Assigned storey"),
                ],
                selected,
            )
        ],
    )


@feature(
    "stories.showBelow",
    "Show Below",
    part="floorPlan",
    fields=[
        text("storeyId", "Current storey id", "L2"),
        number("opacityPercent", "Ghost opacity", 30, unit="%", min=0, max=100),
    ],
)
def show_below(ctx: FeatureContext, values: dict) -> dict:
    """Find the immediately lower storey and its members for an underlay ghost view."""
    plan, rows = profile(ctx)
    stories = ordered_stories(plan)
    index = next((i for i, s in enumerate(stories) if s["id"] == values["storeyId"]), None)
    if index is None:
        raise FeatureInputError("Storey id was not found.")
    if index == 0:
        return result(
            summary={
                "lowerStorey": None,
                "ghostOpacityPercent": values["opacityPercent"],
                "memberCount": 0,
            },
            notes=["The selected storey is the lowest defined level."],
        )
    lower = stories[index - 1]
    matches = [r for r in rows if r["story"] == lower["id"]]
    return result(
        summary={
            "currentStorey": values["storeyId"],
            "lowerStorey": lower["id"],
            "verticalGapMm": float(stories[index]["elevation"]) - float(lower["elevation"]),
            "ghostOpacityPercent": values["opacityPercent"],
            "memberCount": len(matches),
        },
        tables=[
            table(
                "Members from storey below",
                [("id", "Member"), ("category", "Category"), ("type", "Type")],
                matches,
            )
        ],
    )


@feature(
    "stories.copyStorey",
    "Copy Storey",
    part="floorPlan",
    fields=[
        text("sourceStorey", "Source storey id", "L1"),
        text("targetStorey", "Target storey id", "L2"),
        checkbox("includeVertical", "Include vertical members", False),
    ],
)
def copy_storey(ctx: FeatureContext, values: dict) -> dict:
    """Map source-level plan members to an existing target level, keeping plan coordinates."""
    plan, rows = profile(ctx)
    ids = {s["id"] for s in plan["stories"]}
    if values["sourceStorey"] not in ids or values["targetStorey"] not in ids:
        raise FeatureInputError("Source and target storeys must exist.")
    selected = [
        r
        for r in rows
        if r["story"] == values["sourceStorey"]
        and (values["includeVertical"] or r["category"] not in {"column", "wall"})
    ]
    return result(
        summary={
            "sourceStorey": values["sourceStorey"],
            "targetStorey": values["targetStorey"],
            "memberCopies": len(selected),
        },
        tables=[
            table(
                "Storey copy mapping",
                [
                    ("sourceId", "Source member"),
                    ("category", "Category"),
                    ("type", "Type"),
                    ("targetStorey", "Target storey"),
                ],
                [
                    {
                        "sourceId": r["id"],
                        "category": r["category"],
                        "type": r["type"],
                        "targetStorey": values["targetStorey"],
                    }
                    for r in selected
                ],
            )
        ],
        notes=[
            "The mapping preserves each source member's grid references; vertical members need explicit base/top remapping."
        ],
    )


@feature(
    "stories.splitStorey",
    "Split Storey",
    part="floorPlan",
    fields=[
        text("storeyId", "Storey id to split", "L1"),
        number("splitElevationMm", "New intermediate elevation", 1600, unit="mm"),
        text("newStoreyId", "New storey id", "L1M"),
    ],
)
def split_storey(ctx: FeatureContext, values: dict) -> dict:
    """Validate a proposed intermediate level inside an existing storey interval."""
    plan = plan_data(ctx)
    stories = ordered_stories(plan)
    i = next((i for i, s in enumerate(stories) if s["id"] == values["storeyId"]), None)
    if i is None or i + 1 >= len(stories):
        raise FeatureInputError("Choose a storey interval with a level above it.")
    lo, hi = float(stories[i]["elevation"]), float(stories[i + 1]["elevation"])
    if not lo < values["splitElevationMm"] < hi:
        raise FeatureInputError(
            "Split elevation must lie strictly between this level and the next."
        )
    if values["newStoreyId"] in {s["id"] for s in stories}:
        raise FeatureInputError("New storey id already exists.")
    return result(
        summary={
            "lowerHeightMm": values["splitElevationMm"] - lo,
            "upperHeightMm": hi - values["splitElevationMm"],
            "newStoreyId": values["newStoreyId"],
        }
    )


@feature(
    "stories.mergeStoreys",
    "Merge Storeys",
    part="floorPlan",
    fields=[
        text("lowerStorey", "Lower storey id", "L1"),
        checkbox("combineMemberLists", "Combine member schedules", True),
    ],
)
def merge_storeys(ctx: FeatureContext, values: dict) -> dict:
    """Measure the combined vertical interval of a lower storey and its immediate successor."""
    plan, rows = profile(ctx)
    stories = ordered_stories(plan)
    i = next((i for i, s in enumerate(stories) if s["id"] == values["lowerStorey"]), None)
    if i is None or i + 1 >= len(stories):
        raise FeatureInputError("Choose a storey with an adjacent storey above it.")
    lower, upper = stories[i], stories[i + 1]
    count = sum(r["story"] in {lower["id"], upper["id"]} for r in rows)
    return result(
        summary={
            "lowerStorey": lower["id"],
            "upperStorey": upper["id"],
            "combinedHeightMm": float(upper["elevation"]) - float(lower["elevation"]),
            "combinedMemberCount": count if values["combineMemberLists"] else None,
        },
        notes=[
            "Vertical members that terminate on the shared level require endpoint remapping before the levels can be merged."
        ],
    )


@feature(
    "stories.storeyRenumber",
    "Storey Renumber",
    part="floorPlan",
    fields=[text("prefix", "New id prefix", "L"), number("firstNumber", "First number", 1, min=0)],
)
def storey_renumber(ctx: FeatureContext, values: dict) -> dict:
    """Assign sequential ids in increasing elevation order without changing level heights."""
    stories = ordered_stories(plan_data(ctx))
    start = int(values["firstNumber"])
    return result(
        summary={"renumberedStoreys": len(stories)},
        tables=[
            table(
                "Storey ids",
                [("oldId", "Current id"), ("newId", "New id"), ("elevationMm", "Elevation", "mm")],
                [
                    {
                        "oldId": s["id"],
                        "newId": f"{values['prefix']}{start + i}",
                        "elevationMm": s["elevation"],
                    }
                    for i, s in enumerate(stories)
                ],
            )
        ],
    )


@feature(
    "stories.storeyOffset",
    "Storey Offset",
    part="floorPlan",
    fields=[
        text("storeyId", "Storey id", "L1"),
        number("offsetMm", "Elevation offset", 100, unit="mm"),
    ],
)
def storey_offset(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the shifted elevation for a storey and its vertical clearances to neighbours."""
    stories = ordered_stories(plan_data(ctx))
    i = next((i for i, s in enumerate(stories) if s["id"] == values["storeyId"]), None)
    if i is None:
        raise FeatureInputError("Storey id was not found.")
    current = float(stories[i]["elevation"])
    shifted = current + values["offsetMm"]
    low = shifted - float(stories[i - 1]["elevation"]) if i else None
    high = float(stories[i + 1]["elevation"]) - shifted if i + 1 < len(stories) else None
    if (low is not None and low <= 0) or (high is not None and high <= 0):
        raise FeatureInputError("The offset would cross an adjacent storey elevation.")
    return result(
        summary={
            "storey": values["storeyId"],
            "newElevationMm": shifted,
            "heightAboveLowerMm": low,
            "heightBelowUpperMm": high,
        }
    )


@feature(
    "stories.levelMarker",
    "Level Marker",
    part="floorPlan",
    fields=[
        text("storeyId", "Storey id", "L1"),
        number("datumMm", "Display datum", 0, unit="mm"),
        number("precisionMm", "Rounding increment", 1, unit="mm", min=0.01),
    ],
)
def level_marker(ctx: FeatureContext, values: dict) -> dict:
    """Format a level-marker elevation relative to the selected display datum."""
    plan = plan_data(ctx)
    story = next((s for s in plan["stories"] if s["id"] == values["storeyId"]), None)
    if story is None:
        raise FeatureInputError("Storey id was not found.")
    relative = float(story["elevation"]) - values["datumMm"]
    rounded = round(relative / values["precisionMm"]) * values["precisionMm"]
    return result(
        summary={
            "storey": story["id"],
            "name": story["name"],
            "elevationMm": relative,
            "labelElevationMm": rounded,
            "roundingMm": values["precisionMm"],
        }
    )


@feature(
    "stories.elevationDatum",
    "Elevation Datum",
    part="floorPlan",
    fields=[
        number("datumElevationMm", "Datum elevation", 0, unit="mm"),
        text("datumName", "Datum name", "Project 0.000"),
    ],
    requires_project=False,
)
def elevation_datum(ctx: FeatureContext, values: dict) -> dict:
    """Convert project elevations to a named display datum by subtracting its elevation."""
    plan = plan_data(ctx)
    rows = [
        {
            "storey": s["id"],
            "projectElevationMm": s["elevation"],
            "datumElevationMm": float(s["elevation"]) - values["datumElevationMm"],
        }
        for s in ordered_stories(plan)
    ]
    return result(
        summary={
            "datumName": values["datumName"],
            "datumElevationMm": values["datumElevationMm"],
            "convertedLevels": len(rows),
        },
        tables=[
            table(
                "Levels relative to datum",
                [
                    ("storey", "Storey"),
                    ("projectElevationMm", "Project elevation", "mm"),
                    ("datumElevationMm", "Datum elevation", "mm"),
                ],
                rows,
            )
        ],
    )


@feature(
    "stories.groundLevel",
    "Ground Level",
    part="floorPlan",
    fields=[
        text("storeyId", "Ground storey id", "BASE"),
        number("finishedGroundElevationMm", "Finished ground elevation", 0, unit="mm"),
    ],
)
def ground_level(ctx: FeatureContext, values: dict) -> dict:
    """Compare the selected structural level with the finished ground elevation."""
    plan = plan_data(ctx)
    story = next((s for s in plan["stories"] if s["id"] == values["storeyId"]), None)
    if story is None:
        raise FeatureInputError("Ground storey id was not found.")
    return result(
        summary={
            "storey": story["id"],
            "structuralElevationMm": story["elevation"],
            "finishedGroundElevationMm": values["finishedGroundElevationMm"],
            "structuralLevelAboveGroundMm": float(story["elevation"])
            - values["finishedGroundElevationMm"],
        }
    )


@feature(
    "stories.roofLevel",
    "Roof Level",
    part="floorPlan",
    fields=[
        text("storeyId", "Roof storey id", "L3"),
        number("parapetHeightMm", "Parapet height", 1000, unit="mm", min=0),
    ],
)
def roof_level(ctx: FeatureContext, values: dict) -> dict:
    """Calculate roof and parapet top elevations from the selected level."""
    plan = plan_data(ctx)
    story = next((s for s in plan["stories"] if s["id"] == values["storeyId"]), None)
    if story is None:
        raise FeatureInputError("Roof storey id was not found.")
    if float(story["elevation"]) != max(float(s["elevation"]) for s in plan["stories"]):
        raise FeatureInputError("Roof level should be the highest defined storey.")
    return result(
        summary={
            "roofStorey": story["id"],
            "roofElevationMm": story["elevation"],
            "parapetTopElevationMm": float(story["elevation"]) + values["parapetHeightMm"],
            "windReferenceHeightM": (float(story["elevation"]) + values["parapetHeightMm"]) / 1000,
        }
    )


@feature(
    "stories.levelTolerance",
    "Level Tolerance",
    part="floorPlan",
    fields=[number("toleranceMm", "Assignment tolerance", 100, unit="mm", min=0)],
)
def level_tolerance(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the nearest storey assignment for each member within an elevation tolerance."""
    plan, rows = profile(ctx)
    stories = ordered_stories(plan)
    suggestions = []
    for r in rows:
        if r["category"] not in {"column", "wall"}:
            continue
        raw = next(m for g in ("columns", "walls") for m in plan[g] if m["id"] == r["id"])
        base = story_map(plan).get(raw.get("base"), {}).get("elevation")
        if base is None:
            continue
        nearest = min(stories, key=lambda s: abs(float(s["elevation"]) - float(base)))
        difference = abs(float(nearest["elevation"]) - float(base))
        if difference <= values["toleranceMm"]:
            suggestions.append(
                {
                    "memberId": r["id"],
                    "nearestStorey": nearest["id"],
                    "elevationDifferenceMm": difference,
                }
            )
    return result(
        summary={
            "verticalMembersWithinTolerance": len(suggestions),
            "toleranceMm": values["toleranceMm"],
        },
        tables=[
            table(
                "Nearest level assignments",
                [
                    ("memberId", "Member"),
                    ("nearestStorey", "Nearest storey"),
                    ("elevationDifferenceMm", "Difference", "mm"),
                ],
                suggestions,
            )
        ],
    )


@feature(
    "stories.storeyCompare",
    "Storey Compare",
    part="floorPlan",
    fields=[text("comparisonJson", "Other model storeys JSON", '[{"id":"L1","elevation":3200}]')],
)
def storey_compare(ctx: FeatureContext, values: dict) -> dict:
    """Compare story ids and elevations with a supplied linked-model storey array."""
    import json

    plan = plan_data(ctx)
    try:
        other = json.loads(values["comparisonJson"])
    except ValueError as exc:
        raise FeatureInputError("Comparison storeys must be a JSON array.") from exc
    if not isinstance(other, list):
        raise FeatureInputError("Comparison storeys must be a JSON array.")
    old = {s["id"]: float(s["elevation"]) for s in other}
    current = {s["id"]: float(s["elevation"]) for s in plan["stories"]}
    rows = []
    for sid in sorted(set(old) | set(current)):
        rows.append(
            {
                "storey": sid,
                "change": "added"
                if sid not in old
                else "removed"
                if sid not in current
                else "matched",
                "currentMm": current.get(sid),
                "otherMm": old.get(sid),
                "deltaMm": current[sid] - old[sid] if sid in old and sid in current else None,
            }
        )
    return result(
        summary={
            "changedStoreys": sum(
                r["change"] != "matched" or (r["deltaMm"] is not None and abs(r["deltaMm"]) > 1)
                for r in rows
            )
        },
        tables=[
            table(
                "Storey comparison",
                [
                    ("storey", "Storey"),
                    ("change", "Status"),
                    ("currentMm", "Current", "mm"),
                    ("otherMm", "Other model", "mm"),
                    ("deltaMm", "Delta", "mm"),
                ],
                rows,
            )
        ],
    )


@feature(
    "stories.storeyLock",
    "Storey Lock",
    part="floorPlan",
    fields=[text("storeyIds", "Storey ids to lock (blank for all)", "")],
)
def storey_lock(ctx: FeatureContext, values: dict) -> dict:
    """Resolve requested storeys for elevation lock after checking each id exists."""
    plan = plan_data(ctx)
    requested = {x.strip() for x in values["storeyIds"].split(",") if x.strip()}
    stories = plan["stories"]
    ids = {s["id"] for s in stories}
    missing = requested - ids
    if missing:
        raise FeatureInputError(f"Unknown storey id(s): {', '.join(sorted(missing))}.")
    locked = [s for s in stories if not requested or s["id"] in requested]
    return result(
        summary={"lockedStoreyCount": len(locked)},
        tables=[
            table(
                "Storey elevations selected for locking",
                [("id", "Storey"), ("elevationMm", "Elevation", "mm")],
                [{"id": s["id"], "elevationMm": s["elevation"]} for s in locked],
            )
        ],
        notes=["Lock state is an editor property; this output identifies the levels to lock."],
    )


@feature(
    "stories.storeyTemplate",
    "Storey Template",
    part="floorPlan",
    fields=[
        text("namePrefix", "Name prefix", "Level "),
        number("typicalHeightMm", "Typical height", 3000, unit="mm", min=1),
        number("count", "Storey count", 4, min=1, max=100),
        number("baseElevationMm", "Base elevation", 0, unit="mm"),
    ],
    requires_project=False,
)
def storey_template(ctx: FeatureContext, values: dict) -> dict:
    """Expand a uniform storey-height template into named elevations."""
    rows = [
        {
            "sequence": i + 1,
            "name": f"{values['namePrefix']}{i + 1}",
            "elevationMm": values["baseElevationMm"] + i * values["typicalHeightMm"],
            "heightMm": values["typicalHeightMm"],
        }
        for i in range(int(values["count"]))
    ]
    return result(
        summary={
            "storeys": len(rows),
            "buildingHeightM": (values["count"] - 1) * values["typicalHeightMm"] / 1000,
        },
        tables=[
            table(
                "Storey template",
                [
                    ("sequence", "Sequence"),
                    ("name", "Name"),
                    ("elevationMm", "Elevation", "mm"),
                    ("heightMm", "Height", "mm"),
                ],
                rows,
            )
        ],
    )


@feature(
    "stories.massPerStorey",
    "Mass Per Storey",
    part="floorPlan",
    fields=[
        number("slabThicknessMm", "Slab thickness", 150, unit="mm", min=1),
        number("concreteDensityKnPerM3", "Concrete unit weight", 24, unit="kN/m³", min=1),
        number("deadLoadKpa", "Additional dead load", 0.5, unit="kPa", min=0),
        number("liveMassFraction", "Live load mass fraction", 0, min=0, max=1),
    ],
)
def mass_per_storey(ctx: FeatureContext, values: dict) -> dict:
    """Estimate slab and explicit area-load gravity mass assigned to each storey."""
    plan, rows = profile(ctx)
    settings = ctx.raw("settings") or {}
    defs = {x.get("id"): x for x in settings.get("areaLoads", [])}
    raw_slabs = {s["id"]: s for s in plan["slabs"]}
    out = []
    for story in ordered_stories(plan):
        slabs = [r for r in rows if r["category"] == "slab" and r["story"] == story["id"]]
        area = sum(r["areaM2"] for r in slabs)
        dead = area * (
            values["slabThicknessMm"] / 1000 * values["concreteDensityKnPerM3"]
            + values["deadLoadKpa"]
        )
        live = sum(
            r["areaM2"]
            * float(defs.get(raw_slabs[r["id"]].get("areaLoad"), {}).get("live", 0) or 0)
            * values["liveMassFraction"]
            for r in slabs
        )
        out.append(
            {
                "storey": story["id"],
                "slabAreaM2": area,
                "deadWeightKn": dead,
                "liveMassWeightKn": live,
                "estimatedSeismicWeightKn": dead + live,
            }
        )
    return result(
        summary={
            "storeyCount": len(out),
            "estimatedTotalWeightKn": sum(r["estimatedSeismicWeightKn"] for r in out),
        },
        tables=[
            table(
                "Estimated floor mass",
                [
                    ("storey", "Storey"),
                    ("slabAreaM2", "Slab area", "m²"),
                    ("deadWeightKn", "Dead weight", "kN"),
                    ("liveMassWeightKn", "Live mass share", "kN"),
                    ("estimatedSeismicWeightKn", "Total", "kN"),
                ],
                out,
            )
        ],
        notes=[
            "Estimate covers slab self-weight, entered additional dead pressure and the entered live-mass fraction; framing and wall weights are excluded."
        ],
    )

"""Level Templates ribbon: reusable storey sequences and grid propagation."""

from __future__ import annotations

import json

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
from saengine.features.plan_common import ordered_stories, plan_data, profile


def _heights(raw: str) -> list[float]:
    try:
        values = [float(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError as exc:
        raise FeatureInputError(
            "Enter comma-separated positive storey heights in millimetres."
        ) from exc
    if not values or any(x <= 0 for x in values):
        raise FeatureInputError("Enter at least one positive storey height.")
    return values


@feature(
    "planGridsLevelTemplates.createTemplate",
    "Create Template",
    part="floorPlan",
    fields=[
        text("name", "Template name", "Typical office"),
        number("baseElevationMm", "Base elevation", 0, unit="mm"),
    ],
)
def create_template(ctx: FeatureContext, values: dict) -> dict:
    """Capture current storey names and relative heights as a reusable level template."""
    stories = ordered_stories(plan_data(ctx))
    rows = []
    for i, s in enumerate(stories):
        h = (
            float(stories[i + 1]["elevation"]) - float(s["elevation"])
            if i + 1 < len(stories)
            else None
        )
        rows.append(
            {
                "id": s["id"],
                "name": s["name"],
                "heightMm": h,
                "relativeElevationMm": float(s["elevation"]) - values["baseElevationMm"],
            }
        )
    return result(
        summary={
            "templateName": values["name"],
            "levelCount": len(rows),
            "baseElevationMm": values["baseElevationMm"],
        },
        tables=[
            table(
                "Template levels",
                [
                    ("id", "Storey id"),
                    ("name", "Name"),
                    ("heightMm", "Height to next", "mm"),
                    ("relativeElevationMm", "Relative elevation", "mm"),
                ],
                rows,
            )
        ],
    )


@feature(
    "planGridsLevelTemplates.nameTemplate",
    "Name Template",
    part="floorPlan",
    fields=[
        text("templateName", "Template name", "Podium and tower"),
        text("description", "Template description", "Typical storey sequence"),
        text("prefix", "Storey id prefix", "L"),
    ],
    requires_project=False,
)
def name_template(ctx: FeatureContext, values: dict) -> dict:
    """Validate and package a named level-template descriptor."""
    if not values["templateName"].strip():
        raise FeatureInputError("Template name cannot be blank.")
    return result(
        summary={
            "templateName": values["templateName"],
            "description": values["description"],
            "idPrefix": values["prefix"],
        }
    )


@feature(
    "planGridsLevelTemplates.assignTemplate",
    "Assign Template",
    part="floorPlan",
    fields=[
        text(
            "templateJson",
            "Template levels JSON",
            '[{"name":"Level 1","heightMm":3200},{"name":"Typical","heightMm":3000}]',
        )
    ],
)
def assign_template(ctx: FeatureContext, values: dict) -> dict:
    """Assign template heights from the base level and show the resulting target elevations."""
    try:
        levels = json.loads(values["templateJson"])
    except ValueError as exc:
        raise FeatureInputError("Template levels must be valid JSON.") from exc
    if not isinstance(levels, list) or not levels:
        raise FeatureInputError("Template must be a non-empty JSON array.")
    plan = plan_data(ctx)
    elevation = float(ordered_stories(plan)[0]["elevation"]) if plan["stories"] else 0
    rows = []
    for i, level in enumerate(levels):
        height = float(level.get("heightMm", 0))
        if height <= 0:
            raise FeatureInputError("Each template level needs a positive heightMm.")
        elevation += height
        rows.append(
            {
                "sequence": i + 1,
                "name": level.get("name", f"Level {i + 1}"),
                "elevationMm": elevation,
                "heightMm": height,
            }
        )
    return result(
        summary={"assignedLevelCount": len(rows), "topElevationMm": elevation},
        tables=[
            table(
                "Assigned template elevations",
                [
                    ("sequence", "Sequence"),
                    ("name", "Name"),
                    ("heightMm", "Height", "mm"),
                    ("elevationMm", "Elevation", "mm"),
                ],
                rows,
            )
        ],
    )


@feature(
    "planGridsLevelTemplates.matchTemplate",
    "Match Template",
    part="floorPlan",
    fields=[
        text("templateHeightsMm", "Expected heights (comma-separated)", "3200,3200,3600"),
        number("heightToleranceMm", "Match tolerance", 5, unit="mm", min=0),
    ],
)
def match_template(ctx: FeatureContext, values: dict) -> dict:
    """Compare current storey intervals against an ordered template height sequence."""
    expected = _heights(values["templateHeightsMm"])
    stories = ordered_stories(plan_data(ctx))
    actual = [
        float(stories[i + 1]["elevation"]) - float(stories[i]["elevation"])
        for i in range(len(stories) - 1)
    ]
    rows = []
    for i in range(max(len(expected), len(actual))):
        a = actual[i] if i < len(actual) else None
        e = expected[i] if i < len(expected) else None
        rows.append(
            {
                "interval": i + 1,
                "actualMm": a,
                "templateMm": e,
                "differenceMm": a - e if a is not None and e is not None else None,
                "matches": a is not None
                and e is not None
                and abs(a - e) <= values["heightToleranceMm"],
            }
        )
    return result(
        summary={
            "matchedIntervals": sum(r["matches"] for r in rows),
            "comparedIntervals": min(len(expected), len(actual)),
        },
        tables=[
            table(
                "Storey template comparison",
                [
                    ("interval", "Interval"),
                    ("actualMm", "Actual", "mm"),
                    ("templateMm", "Template", "mm"),
                    ("differenceMm", "Difference", "mm"),
                    ("matches", "Within tolerance"),
                ],
                rows,
            )
        ],
    )


@feature(
    "planGridsLevelTemplates.copyLevels",
    "Copy Levels",
    part="floorPlan",
    fields=[
        text("sourceIds", "Source storey ids", "L1,L2"),
        number("elevationOffsetMm", "Copy elevation offset", 3000, unit="mm"),
    ],
)
def copy_levels(ctx: FeatureContext, values: dict) -> dict:
    """Calculate copied storey records at a uniform elevation offset."""
    plan = plan_data(ctx)
    selected = {x.strip() for x in values["sourceIds"].split(",") if x.strip()}
    stories = [s for s in plan["stories"] if s["id"] in selected]
    if len(stories) != len(selected):
        raise FeatureInputError("One or more source storey ids were not found.")
    return result(
        summary={"copiedLevels": len(stories), "offsetMm": values["elevationOffsetMm"]},
        tables=[
            table(
                "Level copies",
                [
                    ("sourceId", "Source"),
                    ("sourceElevationMm", "Current elevation", "mm"),
                    ("targetElevationMm", "Copied elevation", "mm"),
                ],
                [
                    {
                        "sourceId": s["id"],
                        "sourceElevationMm": s["elevation"],
                        "targetElevationMm": float(s["elevation"]) + values["elevationOffsetMm"],
                    }
                    for s in stories
                ],
            )
        ],
    )


@feature(
    "planGridsLevelTemplates.copyGrids",
    "Copy Grids",
    part="floorPlan",
    fields=[
        number("offsetXmm", "Grid offset X", 0, unit="mm"),
        number("offsetYmm", "Grid offset Y", 0, unit="mm"),
        text("labelSuffix", "New label suffix", "-T"),
    ],
)
def copy_grids(ctx: FeatureContext, values: dict) -> dict:
    """Create offset grid-line copies with explicit label suffixes."""
    plan = plan_data(ctx)
    rows = []
    for line in plan["grids"]["x"]:
        rows.append(
            {
                "axis": "X",
                "sourceLabel": line["label"],
                "newLabel": line["label"] + values["labelSuffix"],
                "newPositionMm": float(line["position"]) + values["offsetXmm"],
            }
        )
    for line in plan["grids"]["y"]:
        rows.append(
            {
                "axis": "Y",
                "sourceLabel": line["label"],
                "newLabel": line["label"] + values["labelSuffix"],
                "newPositionMm": float(line["position"]) + values["offsetYmm"],
            }
        )
    return result(
        summary={"copiedGridLines": len(rows)},
        tables=[
            table(
                "Copied grids",
                [
                    ("axis", "Axis"),
                    ("sourceLabel", "Source"),
                    ("newLabel", "New label"),
                    ("newPositionMm", "Position", "mm"),
                ],
                rows,
            )
        ],
    )


@feature(
    "planGridsLevelTemplates.propagateDown",
    "Propagate Down",
    part="floorPlan",
    fields=[
        text("sourceStorey", "Source storey id", "L3"),
        number("levelsDown", "Levels to propagate", 2, min=1, max=100),
        checkbox("includeSlabs", "Include slab panels", True),
    ],
)
def propagate_down(ctx: FeatureContext, values: dict) -> dict:
    """Map members on a source storey onto the specified lower storeys."""
    plan, rows = profile(ctx)
    stories = ordered_stories(plan)
    i = next((i for i, s in enumerate(stories) if s["id"] == values["sourceStorey"]), None)
    if i is None:
        raise FeatureInputError("Source storey id was not found.")
    targets = list(reversed(stories[max(0, i - int(values["levelsDown"])) : i]))
    source = [
        r
        for r in rows
        if r["story"] == values["sourceStorey"]
        and (values["includeSlabs"] or r["category"] != "slab")
    ]
    out = [
        {"memberId": r["id"], "targetStorey": s["id"], "category": r["category"]}
        for r in source
        for s in targets
    ]
    return result(
        summary={"sourceMembers": len(source), "propagatedInstances": len(out)},
        tables=[
            table(
                "Downward propagation",
                [
                    ("memberId", "Source member"),
                    ("targetStorey", "Target storey"),
                    ("category", "Category"),
                ],
                out,
            )
        ],
    )


@feature(
    "planGridsLevelTemplates.mirrorLevels",
    "Mirror Levels",
    part="floorPlan",
    fields=[
        number("datumElevationMm", "Mirror datum elevation", 0, unit="mm"),
        text("storeyIds", "Storey ids to reflect (blank for all)", ""),
    ],
)
def mirror_levels(ctx: FeatureContext, values: dict) -> dict:
    """Reflect selected level elevations about a horizontal elevation datum."""
    stories = ordered_stories(plan_data(ctx))
    ids = {x.strip() for x in values["storeyIds"].split(",") if x.strip()}
    selected = [s for s in stories if not ids or s["id"] in ids]
    return result(
        summary={"reflectedStoreys": len(selected), "datumElevationMm": values["datumElevationMm"]},
        tables=[
            table(
                "Mirrored elevations",
                [
                    ("id", "Storey"),
                    ("currentMm", "Current", "mm"),
                    ("mirroredMm", "Mirrored", "mm"),
                ],
                [
                    {
                        "id": s["id"],
                        "currentMm": s["elevation"],
                        "mirroredMm": 2 * values["datumElevationMm"] - float(s["elevation"]),
                    }
                    for s in selected
                ],
            )
        ],
    )


@feature(
    "planGridsLevelTemplates.defaultHeight",
    "Default Height",
    part="floorPlan",
    fields=[
        number("heightMm", "Default storey height", 3000, unit="mm", min=1),
        text("missingIds", "Missing level ids to create", "L4,L5"),
    ],
    requires_project=False,
)
def default_height(ctx: FeatureContext, values: dict) -> dict:
    """Apply one entered default height to a sequence of proposed missing storey ids."""
    ids = [x.strip() for x in values["missingIds"].split(",") if x.strip()]
    if not ids:
        raise FeatureInputError("Enter at least one storey id to receive the default height.")
    return result(
        summary={"defaultHeightMm": values["heightMm"], "createdLevelCount": len(ids)},
        tables=[
            table(
                "Default height assignments",
                [("id", "Storey id"), ("heightMm", "Height", "mm")],
                [{"id": sid, "heightMm": values["heightMm"]} for sid in ids],
            )
        ],
    )


@feature(
    "planGridsLevelTemplates.defaultNaming",
    "Default Naming",
    part="floorPlan",
    fields=[
        text("prefix", "Name prefix", "Level "),
        number("firstNumber", "First number", 1, min=0),
        number("count", "Number of levels", 5, min=1, max=100),
    ],
    requires_project=False,
)
def default_naming(ctx: FeatureContext, values: dict) -> dict:
    """Generate sequential display names from a prefix, start number and level count."""
    rows = [
        {"sequence": i, "name": f"{values['prefix']}{int(values['firstNumber']) + i - 1}"}
        for i in range(1, int(values["count"]) + 1)
    ]
    return result(
        summary={"generatedNames": len(rows)},
        tables=[table("Default storey names", [("sequence", "Sequence"), ("name", "Name")], rows)],
    )


@feature(
    "planGridsLevelTemplates.levelPrefix",
    "Level Prefix",
    part="floorPlan",
    fields=[text("prefix", "Storey id prefix", "L"), text("storeyIds", "Storey ids", "L1,L2,L3")],
    requires_project=False,
)
def level_prefix(ctx: FeatureContext, values: dict) -> dict:
    """Extract storey number suffixes and apply a common level-id prefix."""
    old = [x.strip() for x in values["storeyIds"].split(",") if x.strip()]
    rows = []
    for sid in old:
        suffix = "".join(ch for ch in sid if ch.isdigit())
        if not suffix:
            raise FeatureInputError(f"Storey id '{sid}' has no number to preserve.")
        rows.append({"oldId": sid, "newId": values["prefix"] + suffix})
    return result(
        summary={"renamedLevels": len(rows)},
        tables=[table("Prefixed level ids", [("oldId", "Current id"), ("newId", "New id")], rows)],
    )


@feature(
    "planGridsLevelTemplates.applyDefaults",
    "Apply Defaults",
    part="floorPlan",
    fields=[
        text("namePrefix", "Name prefix", "Level "),
        number("heightMm", "Default height", 3000, unit="mm", min=1),
        text("firstId", "First storey id", "L1"),
    ],
)
def apply_defaults(ctx: FeatureContext, values: dict) -> dict:
    """Create a default level sequence above the current highest floor."""
    plan = plan_data(ctx)
    stories = ordered_stories(plan)
    base = float(stories[-1]["elevation"]) if stories else 0
    prefix = values["firstId"].rstrip("0123456789")
    digits = values["firstId"][len(prefix) :]
    try:
        start = int(digits)
    except ValueError as exc:
        raise FeatureInputError("First storey id must end with a number.") from exc
    row = {
        "id": values["firstId"],
        "name": f"{values['namePrefix']}{start}",
        "elevationMm": base + values["heightMm"],
    }
    return result(
        summary={"defaultHeightMm": values["heightMm"], "firstElevationMm": row["elevationMm"]},
        tables=[
            table(
                "Default level",
                [("id", "Storey id"), ("name", "Name"), ("elevationMm", "Elevation", "mm")],
                [row],
            )
        ],
    )


@feature(
    "planGridsLevelTemplates.typicalStorey",
    "Typical Storey",
    part="floorPlan",
    fields=[
        text("masterId", "Typical master storey id", "L1"),
        text("similarIds", "Similar storey ids", "L2,L3"),
    ],
)
def typical_storey(ctx: FeatureContext, values: dict) -> dict:
    """Define a typical floor family and compare their elevations and member counts."""
    plan, rows = profile(ctx)
    ids = {s["id"] for s in plan["stories"]}
    similar = [x.strip() for x in values["similarIds"].split(",") if x.strip()]
    if values["masterId"] not in ids or any(x not in ids for x in similar):
        raise FeatureInputError("Typical master and similar storeys must exist.")
    return result(
        summary={"masterStorey": values["masterId"], "similarFloorCount": len(similar)},
        tables=[
            table(
                "Typical floor family",
                [
                    ("storey", "Storey"),
                    ("role", "Role"),
                    ("memberCount", "Members"),
                    ("slabAreaM2", "Slab area", "m²"),
                ],
                [
                    {
                        "storey": sid,
                        "role": "master" if sid == values["masterId"] else "similar",
                        "memberCount": sum(r["story"] == sid for r in rows),
                        "slabAreaM2": sum(r.get("areaM2", 0) for r in rows if r["story"] == sid),
                    }
                    for sid in [values["masterId"], *similar]
                ],
            )
        ],
    )


@feature(
    "planGridsLevelTemplates.elevationLock",
    "Elevation Lock",
    part="floorPlan",
    fields=[
        text("storeyIds", "Storey ids to lock", "L1,L2"),
        checkbox("lockHeights", "Lock floor-to-floor heights", True),
    ],
)
def elevation_lock(ctx: FeatureContext, values: dict) -> dict:
    """Validate selected storey ids and report their absolute and relative elevation constraints."""
    plan = plan_data(ctx)
    ids = {x.strip() for x in values["storeyIds"].split(",") if x.strip()}
    stories = ordered_stories(plan)
    known = {s["id"] for s in stories}
    if ids - known:
        raise FeatureInputError(f"Unknown storey id(s): {', '.join(sorted(ids - known))}.")
    selected = [s for s in stories if not ids or s["id"] in ids]
    return result(
        summary={"lockedElevations": len(selected), "lockHeights": values["lockHeights"]},
        tables=[
            table(
                "Elevation locks",
                [("id", "Storey"), ("elevationMm", "Elevation", "mm")],
                [{"id": s["id"], "elevationMm": s["elevation"]} for s in selected],
            )
        ],
    )


@feature(
    "planGridsLevelTemplates.levelScope",
    "Level Scope",
    part="floorPlan",
    fields=[
        text("storeyIds", "Storey ids to scope", "L1,L2"),
        select(
            "scope",
            "Scope mode",
            [
                ("selected", "Selected levels"),
                ("below", "Selected and below"),
                ("above", "Selected and above"),
            ],
        ),
    ],
)
def level_scope(ctx: FeatureContext, values: dict) -> dict:
    """Expand a selected set of levels according to an above or below elevation scope."""
    stories = ordered_stories(plan_data(ctx))
    ids = {x.strip() for x in values["storeyIds"].split(",") if x.strip()}
    index = {s["id"]: i for i, s in enumerate(stories)}
    if not ids or ids - set(index):
        raise FeatureInputError("Choose one or more existing storey ids.")
    bounds = [index[x] for x in ids]
    lo, hi = min(bounds), max(bounds)
    chosen = (
        stories
        if values["scope"] == "selected" and len(ids) == len(stories)
        else stories[lo:]
        if values["scope"] == "above"
        else stories[: hi + 1]
        if values["scope"] == "below"
        else [s for s in stories if s["id"] in ids]
    )
    return result(
        summary={"scopedStoreys": len(chosen), "scope": values["scope"]},
        tables=[
            table(
                "Level scope",
                [("id", "Storey"), ("elevationMm", "Elevation", "mm")],
                [{"id": s["id"], "elevationMm": s["elevation"]} for s in chosen],
            )
        ],
    )


@feature(
    "planGridsLevelTemplates.multiLevelCopy",
    "Multi Level Copy",
    part="floorPlan",
    fields=[
        text("sourceStorey", "Source storey id", "L1"),
        number("count", "Copy count", 3, min=1, max=100),
        number("heightMm", "Copy interval", 3000, unit="mm", min=1),
        text("idPrefix", "Target id prefix", "L"),
    ],
)
def multi_level_copy(ctx: FeatureContext, values: dict) -> dict:
    """Generate repeated storey elevations from one source level and a uniform vertical interval."""
    plan = plan_data(ctx)
    story = next((s for s in plan["stories"] if s["id"] == values["sourceStorey"]), None)
    if story is None:
        raise FeatureInputError("Source storey id does not exist.")
    base = float(story["elevation"])
    rows = [
        {
            "sequence": i,
            "id": f"{values['idPrefix']}{i}",
            "elevationMm": base + i * values["heightMm"],
        }
        for i in range(1, int(values["count"]) + 1)
    ]
    occupied = {s["id"] for s in plan["stories"]}
    clashes = [r["id"] for r in rows if r["id"] in occupied]
    if clashes:
        raise FeatureInputError(f"Generated storey id(s) already exist: {', '.join(clashes)}.")
    return result(
        summary={"newLevels": len(rows), "topElevationMm": rows[-1]["elevationMm"]},
        tables=[
            table(
                "Multi-level copy",
                [("sequence", "Sequence"), ("id", "Storey id"), ("elevationMm", "Elevation", "mm")],
                rows,
            )
        ],
    )


@feature(
    "planGridsLevelTemplates.storyArray",
    "Story Array",
    part="floorPlan",
    fields=[
        text("baseStorey", "Base storey id", "L1"),
        number("count", "Array levels", 4, min=1, max=100),
        number("typicalHeightMm", "Typical height", 3000, unit="mm", min=1),
        text("idPrefix", "Id prefix", "L"),
    ],
)
def story_array(ctx: FeatureContext, values: dict) -> dict:
    """Calculate a uniform vertical story array from an existing base elevation."""
    plan = plan_data(ctx)
    base = next((s for s in plan["stories"] if s["id"] == values["baseStorey"]), None)
    if base is None:
        raise FeatureInputError("Base storey id does not exist.")
    rows = [
        {
            "level": i,
            "id": f"{values['idPrefix']}{i}",
            "elevationMm": float(base["elevation"]) + i * values["typicalHeightMm"],
        }
        for i in range(1, int(values["count"]) + 1)
    ]
    return result(
        summary={
            "arrayLevelCount": len(rows),
            "arrayHeightM": values["count"] * values["typicalHeightMm"] / 1000,
        },
        tables=[
            table(
                "Story array",
                [("level", "Level"), ("id", "Storey id"), ("elevationMm", "Elevation", "mm")],
                rows,
            )
        ],
    )


@feature(
    "planGridsLevelTemplates.copySelected",
    "Copy Selected",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1,S1"),
        text("targetStoreys", "Target storey ids", "L2,L3"),
    ],
)
def copy_selected(ctx: FeatureContext, values: dict) -> dict:
    """Replicate explicitly selected plan members to multiple verified target storeys."""
    plan, rows = profile(ctx)
    selected = {x.strip() for x in values["memberIds"].split(",") if x.strip()}
    targets = [x.strip() for x in values["targetStoreys"].split(",") if x.strip()]
    ids = {r["id"] for r in rows}
    known = {s["id"] for s in plan["stories"]}
    if selected - ids or set(targets) - known:
        raise FeatureInputError("All selected members and target storeys must exist.")
    source = [r for r in rows if r["id"] in selected]
    out = [
        {"sourceId": r["id"], "targetStorey": s, "category": r["category"], "type": r["type"]}
        for r in source
        for s in targets
    ]
    return result(
        summary={
            "sourceMembers": len(source),
            "targetStoreys": len(targets),
            "copyInstances": len(out),
        },
        tables=[
            table(
                "Selected member copies",
                [
                    ("sourceId", "Source"),
                    ("targetStorey", "Target storey"),
                    ("category", "Category"),
                    ("type", "Type"),
                ],
                out,
            )
        ],
    )


@feature(
    "planGridsLevelTemplates.exportTemplate",
    "Export Template",
    part="floorPlan",
    fields=[
        text("templateName", "Template name", "Typical floor"),
        text("filename", "JSON filename", "levels-template.json"),
    ],
)
def export_template(ctx: FeatureContext, values: dict) -> dict:
    """Write current storey ids, names and relative heights as a JSON level template."""
    if ctx.root is None:
        raise FeatureInputError("Open a project folder to write the template export.")
    stories = ordered_stories(plan_data(ctx))
    data = []
    for i, s in enumerate(stories):
        data.append(
            {
                "id": s["id"],
                "name": s["name"],
                "elevationMm": float(s["elevation"]),
                "heightToNextMm": float(stories[i + 1]["elevation"]) - float(s["elevation"])
                if i + 1 < len(stories)
                else None,
            }
        )
    name = values["filename"].strip()
    if not name.lower().endswith(".json") or "/" in name or "\\" in name:
        raise FeatureInputError("Use a simple .json filename without folders.")
    path = ctx.root / "05 Floor Plan" / "exports" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"name": values["templateName"], "stories": data}, indent=2), encoding="utf-8"
    )
    return result(
        summary={"templateLevels": len(data), "file": path.relative_to(ctx.root).as_posix()},
        notes=[f"Wrote storey template to {path.relative_to(ctx.root).as_posix()}."],
    )


@feature(
    "planGridsLevelTemplates.importTemplate",
    "Import Template",
    part="floorPlan",
    fields=[
        text(
            "templateJson",
            "Template JSON",
            '{"name":"Typical","stories":[{"name":"Level 1","heightToNextMm":3000}]}',
        )
    ],
)
def import_template(ctx: FeatureContext, values: dict) -> dict:
    """Parse and validate imported level-template heights and names."""
    try:
        data = json.loads(values["templateJson"])
    except ValueError as exc:
        raise FeatureInputError("Template input must be valid JSON.") from exc
    stories = data.get("stories") if isinstance(data, dict) else None
    if not isinstance(stories, list) or not stories:
        raise FeatureInputError("Template JSON must contain a non-empty stories array.")
    rows = []
    for i, s in enumerate(stories):
        h = s.get("heightToNextMm", s.get("heightMm"))
        if h is not None and float(h) <= 0:
            raise FeatureInputError(f"Template level {i + 1} has non-positive height.")
        rows.append({"sequence": i + 1, "name": s.get("name", f"Level {i + 1}"), "heightMm": h})
    return result(
        summary={"templateName": data.get("name", "Imported template"), "levelCount": len(rows)},
        tables=[
            table(
                "Imported levels",
                [("sequence", "Sequence"), ("name", "Name"), ("heightMm", "Height", "mm")],
                rows,
            )
        ],
    )


@feature(
    "planGridsLevelTemplates.templateLibrary",
    "Template Library",
    part="floorPlan",
    fields=[
        text(
            "templatesJson",
            "Available template descriptors JSON",
            '[{"name":"Office","levels":12},{"name":"Podium","levels":4}]',
        )
    ],
    requires_project=False,
)
def template_library(ctx: FeatureContext, values: dict) -> dict:
    """Validate template descriptors and tabulate available named level sequences."""
    try:
        templates = json.loads(values["templatesJson"])
    except ValueError as exc:
        raise FeatureInputError("Template library must be valid JSON.") from exc
    if not isinstance(templates, list):
        raise FeatureInputError("Template library must be a JSON array.")
    rows = [
        {
            "name": item.get("name", ""),
            "levels": int(item.get("levels", 0)),
            "description": item.get("description", ""),
        }
        for item in templates
    ]
    if any(r["levels"] < 1 for r in rows):
        raise FeatureInputError("Every template descriptor needs at least one level.")
    return result(
        summary={"availableTemplates": len(rows)},
        tables=[
            table(
                "Level template library",
                [("name", "Template"), ("levels", "Levels"), ("description", "Description")],
                rows,
            )
        ],
    )


@feature(
    "planGridsLevelTemplates.auditLevels",
    "Audit Levels",
    part="floorPlan",
    fields=[
        number("minimumHeightMm", "Minimum storey height", 2000, unit="mm", min=0),
        number("maximumHeightMm", "Maximum storey height", 6000, unit="mm", min=1),
    ],
)
def audit_levels(ctx: FeatureContext, values: dict) -> dict:
    """Audit consecutive story intervals for non-monotonicity and heights outside a supplied range."""
    stories = ordered_stories(plan_data(ctx))
    rows = []
    if values["maximumHeightMm"] < values["minimumHeightMm"]:
        raise FeatureInputError("Maximum storey height must not be below minimum.")
    for i in range(len(stories) - 1):
        h = float(stories[i + 1]["elevation"]) - float(stories[i]["elevation"])
        rows.append(
            {
                "lowerStorey": stories[i]["id"],
                "upperStorey": stories[i + 1]["id"],
                "heightMm": h,
                "withinRange": values["minimumHeightMm"] <= h <= values["maximumHeightMm"],
            }
        )
    return result(
        summary={
            "auditedIntervals": len(rows),
            "outOfRange": sum(not r["withinRange"] for r in rows),
        },
        tables=[
            table(
                "Storey height audit",
                [
                    ("lowerStorey", "Lower level"),
                    ("upperStorey", "Upper level"),
                    ("heightMm", "Height", "mm"),
                    ("withinRange", "Within range"),
                ],
                rows,
            )
        ],
    )

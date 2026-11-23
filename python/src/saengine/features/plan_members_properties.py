"""Member Properties ribbon: section orientation, material attributes and stiffness modifiers."""

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
from saengine.features.plan_common import profile, selected_members


def _members(ctx: FeatureContext, ids: str) -> list[dict]:
    _, rows = profile(ctx)
    return selected_members(rows, ids)


@feature(
    "planMembersProperties.assignSection",
    "Assign Section",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1,B2"),
        text("sectionType", "Section type id", "B350x550"),
    ],
)
def assign_section(ctx: FeatureContext, values: dict) -> dict:
    """Validate a section-type request against selected member categories and current object definitions."""
    rows = _members(ctx, values["memberIds"])
    objects = {o.get("id"): o for o in (ctx.raw("objects") or {}).get("objects", [])}
    definition = objects.get(values["sectionType"])
    incompatible = [
        r["id"]
        for r in rows
        if definition
        and definition.get("kind")
        and definition["kind"] not in {r["category"], "frame"}
    ]
    return result(
        summary={
            "sectionType": values["sectionType"],
            "targetCount": len(rows),
            "typeFound": definition is not None,
            "incompatibleCount": len(incompatible),
        },
        tables=[
            table(
                "Section assignment",
                [
                    ("memberId", "Member"),
                    ("category", "Category"),
                    ("previousType", "Current type"),
                    ("requestedType", "Requested type"),
                ],
                [
                    {
                        "memberId": r["id"],
                        "category": r["category"],
                        "previousType": r["type"],
                        "requestedType": values["sectionType"],
                    }
                    for r in rows
                ],
            )
        ],
        notes=[
            f"Member categories incompatible with this object definition: {', '.join(incompatible) if incompatible else 'none detected'}."
        ],
    )


@feature(
    "planMembersProperties.assignMaterial",
    "Assign Material",
    part="floorPlan",
    fields=[text("memberIds", "Member ids", "B1,B2"), text("materialId", "Material id", "C30")],
)
def assign_material(ctx: FeatureContext, values: dict) -> dict:
    """Check a material id against the project library and prepare member assignments."""
    rows = _members(ctx, values["memberIds"])
    raw = ctx.raw("materials") or {}
    materials = raw.get("materials", [])
    ids = {m.get("id") for m in materials}
    return result(
        summary={
            "materialId": values["materialId"],
            "materialFound": values["materialId"] in ids,
            "targetCount": len(rows),
        },
        tables=[
            table(
                "Material assignment targets",
                [("memberId", "Member"), ("category", "Category"), ("materialId", "Material")],
                [
                    {
                        "memberId": r["id"],
                        "category": r["category"],
                        "materialId": values["materialId"],
                    }
                    for r in rows
                ],
            )
        ],
    )


@feature(
    "planMembersProperties.memberRotation",
    "Member Rotation",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1,C1"),
        number("rotationDeg", "Local section rotation", 0, unit="°"),
    ],
)
def member_rotation(ctx: FeatureContext, values: dict) -> dict:
    """Normalize selected section rotations to the 0-to-360 degree range."""
    rows = _members(ctx, values["memberIds"])
    angle = values["rotationDeg"] % 360
    return result(
        summary={"rotatedMembers": len(rows), "rotationDeg": angle},
        tables=[
            table(
                "Section rotation assignments",
                [
                    ("memberId", "Member"),
                    ("category", "Category"),
                    ("rotationDeg", "Rotation", "°"),
                ],
                [
                    {"memberId": r["id"], "category": r["category"], "rotationDeg": angle}
                    for r in rows
                ],
            )
        ],
    )


@feature(
    "planMembersProperties.mirrorSection",
    "Mirror Section",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1"),
        select("mirrorAxis", "Local mirror axis", [("y", "Local Y axis"), ("z", "Local Z axis")]),
        number("currentRotationDeg", "Current section rotation", 0, unit="°"),
    ],
)
def mirror_section(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the mirrored section orientation and local-axis sign changes."""
    rows = _members(ctx, values["memberIds"])
    new = (
        (180 - values["currentRotationDeg"]) % 360
        if values["mirrorAxis"] == "y"
        else (-values["currentRotationDeg"]) % 360
    )
    return result(
        summary={
            "mirroredMembers": len(rows),
            "axis": values["mirrorAxis"],
            "resultRotationDeg": new,
            "localAxis1Reversed": values["mirrorAxis"] == "z",
        }
    )


@feature(
    "planMembersProperties.localAxis",
    "Local Axis",
    part="floorPlan",
    fields=[
        text("memberId", "Member id", "B1"),
        number("rotationDeg", "Local axis rotation", 0, unit="°"),
    ],
)
def local_axis(ctx: FeatureContext, values: dict) -> dict:
    """Resolve local 1-2 axes and direction cosines from a member's plan azimuth and rotation."""
    rows = _members(ctx, values["memberId"])
    r = rows[0]
    a = math.radians(float(r.get("angleDeg", 0)) + values["rotationDeg"])
    return result(
        summary={
            "memberId": r["id"],
            "local1X": math.cos(a),
            "local1Y": math.sin(a),
            "local2X": -math.sin(a),
            "local2Y": math.cos(a),
            "globalAzimuthDeg": (math.degrees(a) % 360),
        }
    )


@feature(
    "planMembersProperties.cardinalPoint",
    "Cardinal Point",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1"),
        select(
            "point",
            "Section cardinal point",
            [
                ("center", "Centroid"),
                ("topCenter", "Top centre"),
                ("bottomCenter", "Bottom centre"),
                ("leftCenter", "Left centre"),
                ("rightCenter", "Right centre"),
            ],
        ),
        number("sectionWidthMm", "Section width", 300, unit="mm", min=1),
        number("sectionDepthMm", "Section depth", 500, unit="mm", min=1),
    ],
)
def cardinal_point(ctx: FeatureContext, values: dict) -> dict:
    """Calculate section insertion offsets from centroid for the chosen cardinal point."""
    dx = {"center": 0, "topCenter": 0, "bottomCenter": 0, "leftCenter": -0.5, "rightCenter": 0.5}[
        values["point"]
    ] * values["sectionWidthMm"]
    dy = {"center": 0, "topCenter": 0.5, "bottomCenter": -0.5, "leftCenter": 0, "rightCenter": 0}[
        values["point"]
    ] * values["sectionDepthMm"]
    rows = _members(ctx, values["memberIds"])
    return result(
        summary={
            "memberCount": len(rows),
            "offsetXmm": dx,
            "offsetYmm": dy,
            "cardinalPoint": values["point"],
        }
    )


@feature(
    "planMembersProperties.memberOffset",
    "Member Offset",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1"),
        number("offsetXmm", "Offset X", 0, unit="mm"),
        number("offsetYmm", "Offset Y", 0, unit="mm"),
        number("offsetZmm", "Offset Z", 0, unit="mm"),
    ],
)
def member_offset(ctx: FeatureContext, values: dict) -> dict:
    """Create per-member analytical eccentricity vectors and report resultant offset length."""
    rows = _members(ctx, values["memberIds"])
    magnitude = math.sqrt(
        values["offsetXmm"] ** 2 + values["offsetYmm"] ** 2 + values["offsetZmm"] ** 2
    )
    return result(
        summary={"offsetMembers": len(rows), "resultantOffsetMm": magnitude},
        tables=[
            table(
                "Member eccentricities",
                [
                    ("memberId", "Member"),
                    ("offsetXmm", "X", "mm"),
                    ("offsetYmm", "Y", "mm"),
                    ("offsetZmm", "Z", "mm"),
                ],
                [
                    {
                        "memberId": r["id"],
                        "offsetXmm": values["offsetXmm"],
                        "offsetYmm": values["offsetYmm"],
                        "offsetZmm": values["offsetZmm"],
                    }
                    for r in rows
                ],
            )
        ],
    )


@feature(
    "planMembersProperties.alignMembers",
    "Align Members",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "C1,C2,C3"),
        select("axis", "Alignment", [("x", "X coordinate"), ("y", "Y coordinate")]),
        select(
            "reference",
            "Reference coordinate",
            [("average", "Average"), ("median", "Median"), ("first", "First member")],
        ),
    ],
)
def align_members(ctx: FeatureContext, values: dict) -> dict:
    """Find a common centerline coordinate for selected members and quantify individual shifts."""
    rows = _members(ctx, values["memberIds"])
    key = "x1Mm" if values["axis"] == "x" else "y1Mm"
    coords = [float(r.get(key, 0)) for r in rows]
    if not coords:
        raise FeatureInputError("Select at least one member.")
    target = (
        coords[0]
        if values["reference"] == "first"
        else sorted(coords)[len(coords) // 2]
        if values["reference"] == "median"
        else sum(coords) / len(coords)
    )
    return result(
        summary={
            "targetCoordinateMm": target,
            "maximumShiftMm": max(abs(x - target) for x in coords),
            "alignedMembers": len(rows),
        },
        tables=[
            table(
                "Alignment shifts",
                [
                    ("memberId", "Member"),
                    ("currentCoordinateMm", "Current", "mm"),
                    ("targetCoordinateMm", "Target", "mm"),
                    ("shiftMm", "Shift", "mm"),
                ],
                [
                    {
                        "memberId": r["id"],
                        "currentCoordinateMm": r.get(key, 0),
                        "targetCoordinateMm": target,
                        "shiftMm": target - r.get(key, 0),
                    }
                    for r in rows
                ],
            )
        ],
    )


@feature(
    "planMembersProperties.copyProperties",
    "Copy Properties",
    part="floorPlan",
    fields=[
        text("sourceMember", "Source member id", "B1"),
        text("targetIds", "Target member ids", "B2,B3"),
        checkbox("copySection", "Copy section type", True),
        checkbox("copyStorey", "Copy storey", False),
    ],
)
def copy_properties(ctx: FeatureContext, values: dict) -> dict:
    """Copy selected tabular attributes from a source member to target members."""
    _, rows = profile(ctx)
    source = next((r for r in rows if r["id"] == values["sourceMember"]), None)
    if source is None:
        raise FeatureInputError("Source member id was not found.")
    targets = selected_members(rows, values["targetIds"])
    out = [
        {
            "targetId": r["id"],
            "sourceId": source["id"],
            "sectionType": source["type"] if values["copySection"] else r["type"],
            "storey": source["story"] if values["copyStorey"] else r["story"],
        }
        for r in targets
    ]
    return result(
        summary={"sourceMember": source["id"], "targetCount": len(out)},
        tables=[
            table(
                "Property copy preview",
                [
                    ("sourceId", "Source"),
                    ("targetId", "Target"),
                    ("sectionType", "Section type"),
                    ("storey", "Storey"),
                ],
                out,
            )
        ],
    )


@feature(
    "planMembersProperties.matchFormat",
    "Match Format",
    part="floorPlan",
    fields=[
        text("sourceMember", "Format source member", "B1"),
        text("targetIds", "Target member ids", "B2,B3"),
        checkbox("copyRotation", "Copy section rotation", True),
    ],
)
def match_format(ctx: FeatureContext, values: dict) -> dict:
    """Match target type identifiers to a source type and preview section identity changes."""
    plan, _ = profile(ctx)
    raw = {m["id"]: m for g in ("columns", "beams", "walls", "slabs", "footings") for m in plan[g]}
    source = raw.get(values["sourceMember"])
    if source is None:
        raise FeatureInputError("Format source member id was not found.")
    rows = selected_members(profile(ctx)[1], values["targetIds"])
    return result(
        summary={"matchedTargets": len(rows), "referenceType": source["type"]},
        tables=[
            table(
                "Matched member format",
                [
                    ("targetId", "Target"),
                    ("currentType", "Current type"),
                    ("sourceType", "Source type"),
                    ("rotationCopied", "Rotation copied"),
                ],
                [
                    {
                        "targetId": r["id"],
                        "currentType": r["type"],
                        "sourceType": source["type"],
                        "rotationCopied": values["copyRotation"],
                    }
                    for r in rows
                ],
            )
        ],
    )


@feature(
    "planMembersProperties.propagateProperties",
    "Propagate Properties",
    part="floorPlan",
    fields=[
        text("sourceIds", "Source member ids", "B1,B2"),
        text("targetStories", "Target storey ids", "L2,L3"),
        select(
            "attribute",
            "Property to propagate",
            [("type", "Section type"), ("category", "Member category")],
        ),
    ],
)
def propagate_properties(ctx: FeatureContext, values: dict) -> dict:
    """Propagate property values from source members to members with the same category at target storeys."""
    plan, rows = profile(ctx)
    sources = selected_members(rows, values["sourceIds"])
    targets = {x.strip() for x in values["targetStories"].split(",") if x.strip()}
    story_ids = {s["id"] for s in plan["stories"]}
    if targets - story_ids:
        raise FeatureInputError("One or more target storeys are not defined.")
    out = []
    for source in sources:
        for r in rows:
            if r["story"] in targets and r["category"] == source["category"]:
                out.append(
                    {
                        "sourceId": source["id"],
                        "targetId": r["id"],
                        "property": values["attribute"],
                        "value": source["type"]
                        if values["attribute"] == "type"
                        else source["category"],
                    }
                )
    return result(
        summary={"propagatedAssignments": len(out), "targetStoreyCount": len(targets)},
        tables=[
            table(
                "Property propagation",
                [
                    ("sourceId", "Source"),
                    ("targetId", "Target"),
                    ("property", "Property"),
                    ("value", "Value"),
                ],
                out,
            )
        ],
    )


@feature(
    "planMembersProperties.resetProperties",
    "Reset Properties",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1,B2"),
        select(
            "property",
            "Property to reset",
            [("section", "Section type"), ("material", "Material"), ("offset", "Offset")],
        ),
        text("defaultValue", "Reset value", "default"),
    ],
)
def reset_properties(ctx: FeatureContext, values: dict) -> dict:
    """Prepare an explicit selected-property reset while retaining the source member identities."""
    rows = _members(ctx, values["memberIds"])
    return result(
        summary={
            "resetMembers": len(rows),
            "property": values["property"],
            "resetValue": values["defaultValue"],
        },
        tables=[
            table(
                "Property reset plan",
                [("memberId", "Member"), ("property", "Property"), ("newValue", "Reset value")],
                [
                    {
                        "memberId": r["id"],
                        "property": values["property"],
                        "newValue": values["defaultValue"],
                    }
                    for r in rows
                ],
            )
        ],
    )


@feature(
    "planMembersProperties.memberType",
    "Member Type",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1"),
        select(
            "classification",
            "Structural classification",
            [
                ("beam", "Beam"),
                ("column", "Column"),
                ("brace", "Brace"),
                ("collector", "Collector"),
                ("wall", "Wall"),
            ],
        ),
    ],
)
def member_type(ctx: FeatureContext, values: dict) -> dict:
    """Classify selected members by structural function and report category compatibility."""
    rows = _members(ctx, values["memberIds"])
    compatible = all(
        r["category"] == values["classification"]
        or values["classification"] in {"brace", "collector"}
        and r["category"] == "beam"
        for r in rows
    )
    return result(
        summary={
            "classifiedMembers": len(rows),
            "classification": values["classification"],
            "matchesGeometricCategory": compatible,
        }
    )


@feature(
    "planMembersProperties.exposureClass",
    "Exposure Class",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1,C1"),
        select(
            "exposure",
            "Exposure environment",
            [
                ("interior", "Interior dry"),
                ("exterior", "Exterior weather"),
                ("ground", "Buried or ground contact"),
                ("marine", "Marine splash"),
            ],
        ),
    ],
)
def exposure_class(ctx: FeatureContext, values: dict) -> dict:
    """Prepare environmental exposure assignments for selected members."""
    rows = _members(ctx, values["memberIds"])
    return result(
        summary={"assignedCount": len(rows), "exposure": values["exposure"]},
        tables=[
            table(
                "Exposure classifications",
                [("memberId", "Member"), ("category", "Category"), ("exposure", "Exposure")],
                [
                    {"memberId": r["id"], "category": r["category"], "exposure": values["exposure"]}
                    for r in rows
                ],
            )
        ],
    )


@feature(
    "planMembersProperties.fireRating",
    "Fire Rating",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1,C1"),
        number("fireDurationMin", "Required fire resistance", 120, unit="min", min=0),
    ],
)
def fire_rating(ctx: FeatureContext, values: dict) -> dict:
    """Assign a structural fire exposure duration to selected member records."""
    rows = _members(ctx, values["memberIds"])
    return result(
        summary={
            "ratedMemberCount": len(rows),
            "fireDurationH": values["fireDurationMin"] / 60,
            "fireDurationMin": values["fireDurationMin"],
        },
        tables=[
            table(
                "Fire rating assignments",
                [
                    ("memberId", "Member"),
                    ("category", "Category"),
                    ("durationMin", "Duration", "min"),
                ],
                [
                    {
                        "memberId": r["id"],
                        "category": r["category"],
                        "durationMin": values["fireDurationMin"],
                    }
                    for r in rows
                ],
            )
        ],
        notes=[
            "This records the required duration; member fire resistance and protection design are separate checks."
        ],
    )


@feature(
    "planMembersProperties.taperedSection",
    "Tapered Section",
    part="floorPlan",
    fields=[
        text("memberId", "Beam id", "B1"),
        number("depthStartMm", "Start depth", 500, unit="mm", min=1),
        number("depthEndMm", "End depth", 700, unit="mm", min=1),
        number("widthMm", "Section width", 300, unit="mm", min=1),
    ],
)
def tapered_section(ctx: FeatureContext, values: dict) -> dict:
    """Calculate a linear beam-depth taper ratio, mean area and prism volume."""
    rows = _members(ctx, values["memberId"])
    member = rows[0]
    if member["category"] != "beam":
        raise FeatureInputError("Tapered sections are defined for beam members.")
    avg = (values["depthStartMm"] + values["depthEndMm"]) / 2
    volume = values["widthMm"] * avg * member["lengthM"] / 1e9
    return result(
        summary={
            "beamId": member["id"],
            "depthChangeMm": values["depthEndMm"] - values["depthStartMm"],
            "taperRatio": (values["depthEndMm"] - values["depthStartMm"])
            / (member["lengthM"] * 1000),
            "meanAreaM2": values["widthMm"] * avg / 1e6,
            "volumeM3": volume,
        }
    )


@feature(
    "planMembersProperties.haunchDetail",
    "Haunch Detail",
    part="floorPlan",
    fields=[
        number("haunchLengthMm", "Haunch length", 1000, unit="mm", min=1),
        number("haunchDepthMm", "Additional haunch depth", 200, unit="mm", min=1),
        number("beamWidthMm", "Beam width", 300, unit="mm", min=1),
        number("endCount", "Haunched ends", 2, min=1, max=2),
    ],
)
def haunch_detail(ctx: FeatureContext, values: dict) -> dict:
    """Estimate triangular haunch concrete volume for the selected number of beam ends."""
    volume = (
        0.5
        * values["haunchLengthMm"]
        * values["haunchDepthMm"]
        * values["beamWidthMm"]
        * int(values["endCount"])
        / 1e9
    )
    return result(
        summary={
            "haunchedEnds": int(values["endCount"]),
            "haunchVolumeM3": volume,
            "haunchLengthMm": values["haunchLengthMm"],
            "additionalDepthMm": values["haunchDepthMm"],
        }
    )


@feature(
    "planMembersProperties.depthVariation",
    "Depth Variation",
    part="floorPlan",
    fields=[
        number("startDepthMm", "Start depth", 500, unit="mm", min=1),
        number("midDepthMm", "Midspan depth", 700, unit="mm", min=1),
        number("endDepthMm", "End depth", 500, unit="mm", min=1),
        number("stationCount", "Profile stations", 5, min=2, max=101),
    ],
)
def depth_variation(ctx: FeatureContext, values: dict) -> dict:
    """Interpolate a symmetric three-point depth profile along a member."""
    n = int(values["stationCount"])
    rows = []
    for i in range(n):
        x = i / (n - 1)
        depth = (
            (values["startDepthMm"] + (values["midDepthMm"] - values["startDepthMm"]) * 2 * x)
            if x <= 0.5
            else values["midDepthMm"]
            + (values["endDepthMm"] - values["midDepthMm"]) * 2 * (x - 0.5)
        )
        rows.append({"stationRatio": x, "depthMm": depth})
    return result(
        summary={"profileStations": n, "maximumDepthMm": max(r["depthMm"] for r in rows)},
        tables=[
            table(
                "Variable-depth profile",
                [("stationRatio", "Station from start"), ("depthMm", "Depth", "mm")],
                rows,
            )
        ],
    )


@feature(
    "planMembersProperties.modifierTable",
    "Modifier Table",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1,B2"),
        number("axialFactor", "Axial stiffness factor", 1, min=0, max=2),
        number("shearFactor", "Shear stiffness factor", 1, min=0, max=2),
        number("torsionFactor", "Torsional stiffness factor", 1, min=0, max=2),
        number("bendingFactor", "Bending stiffness factor", 0.7, min=0, max=2),
    ],
)
def modifier_table(ctx: FeatureContext, values: dict) -> dict:
    """Apply explicit dimensionless stiffness modifier factors to selected member rows."""
    rows = _members(ctx, values["memberIds"])
    factors = {
        key: values[key] for key in ("axialFactor", "shearFactor", "torsionFactor", "bendingFactor")
    }
    return result(
        summary={"modifiedMembers": len(rows), "factorCount": len(factors)},
        tables=[
            table(
                "Stiffness modifiers",
                [
                    ("memberId", "Member"),
                    ("axialFactor", "Axial"),
                    ("shearFactor", "Shear"),
                    ("torsionFactor", "Torsion"),
                    ("bendingFactor", "Bending"),
                ],
                [{"memberId": r["id"], **factors} for r in rows],
            )
        ],
        notes=[
            "Factors are user-entered analysis-property modifiers; no code-dependent cracked-section factors are assumed."
        ],
    )


@feature(
    "planMembersProperties.shearAreaFactor",
    "Shear Area Factor",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1"),
        number("grossShearAreaMm2", "Gross shear area", 90000, unit="mm²", min=1),
        number("factor", "Effective area factor", 0.8, min=0, max=1),
    ],
)
def shear_area_factor(ctx: FeatureContext, values: dict) -> dict:
    """Calculate effective shear area from gross area and an explicit modifier."""
    rows = _members(ctx, values["memberIds"])
    return result(
        summary={
            "memberCount": len(rows),
            "factor": values["factor"],
            "effectiveShearAreaMm2": values["grossShearAreaMm2"] * values["factor"],
        }
    )


@feature(
    "planMembersProperties.momentInertiaFactor",
    "Moment Inertia Factor",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1"),
        number("grossInertiaMm4", "Gross moment of inertia", 1e9, unit="mm⁴", min=1),
        number("factor", "Effective inertia factor", 0.7, min=0, max=1),
    ],
)
def moment_inertia_factor(ctx: FeatureContext, values: dict) -> dict:
    """Calculate effective bending inertia using an engineer-entered stiffness multiplier."""
    rows = _members(ctx, values["memberIds"])
    return result(
        summary={
            "memberCount": len(rows),
            "factor": values["factor"],
            "effectiveInertiaMm4": values["grossInertiaMm4"] * values["factor"],
        }
    )


@feature(
    "planMembersProperties.propertySummary",
    "Property Summary",
    part="floorPlan",
    fields=[text("memberIds", "Member ids (blank for all)", "")],
)
def property_summary(ctx: FeatureContext, values: dict) -> dict:
    """Summarise current member categories, type ids, lengths and available slab areas."""
    _, all_rows = profile(ctx)
    rows = selected_members(all_rows, values["memberIds"])
    counts = {}
    for r in rows:
        counts[(r["category"], r["type"])] = counts.get((r["category"], r["type"]), 0) + 1
    return result(
        summary={
            "summarisedMembers": len(rows),
            "totalLengthM": sum(r.get("lengthM", 0) for r in rows),
            "totalSlabAreaM2": sum(r.get("areaM2", 0) for r in rows),
        },
        tables=[
            table(
                "Member properties",
                [("category", "Category"), ("type", "Type"), ("count", "Count")],
                [{"category": k[0], "type": k[1], "count": v} for k, v in sorted(counts.items())],
            )
        ],
    )

"""Modelling ribbon: describe member properties, connectivity and analytical constraints."""

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
    plan_data,
    profile,
    selected_members,
    story_map,
)


def _targets(ctx: FeatureContext, ids: str) -> list[dict]:
    _, rows = profile(ctx)
    return selected_members(rows, ids)


def _assignment(rows: list[dict], prop: str, value: object) -> list[dict]:
    return [
        {
            "memberId": row["id"],
            "category": row["category"],
            "property": prop,
            "proposedValue": value,
        }
        for row in rows
    ]


@feature(
    "planModelling.memberProperties",
    "Member Properties",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated)", "B1"),
        text("section", "Section type id", "B300x500"),
        text("material", "Material id", "C30"),
        number("offsetMm", "Analytical offset", 0, unit="mm"),
    ],
)
def member_properties(ctx: FeatureContext, values: dict) -> dict:
    """Prepare a combined section, material and offset property edit for selected members."""
    rows = _targets(ctx, values["memberIds"])
    changes = [
        {
            "memberId": r["id"],
            "oldType": r["type"],
            "newSection": values["section"],
            "material": values["material"],
            "offsetMm": values["offsetMm"],
        }
        for r in rows
    ]
    return result(
        summary={
            "memberCount": len(changes),
            "section": values["section"],
            "material": values["material"],
        },
        tables=[
            table(
                "Member property changes",
                [
                    ("memberId", "Member"),
                    ("oldType", "Current type"),
                    ("newSection", "Section"),
                    ("material", "Material"),
                    ("offsetMm", "Offset", "mm"),
                ],
                changes,
            )
        ],
    )


@feature(
    "planModelling.sectionAssign",
    "Section Assign",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated)", "B1"),
        text("section", "Section type id", "B300x500"),
    ],
)
def section_assign(ctx: FeatureContext, values: dict) -> dict:
    """List selected members with their proposed object type assignment."""
    rows = _targets(ctx, values["memberIds"])
    return result(
        summary={"assignedCount": len(rows), "sectionType": values["section"]},
        tables=[
            table(
                "Section assignments",
                [
                    ("memberId", "Member"),
                    ("category", "Category"),
                    ("previousType", "Current type"),
                    ("sectionType", "Requested type"),
                ],
                [
                    {
                        "memberId": r["id"],
                        "category": r["category"],
                        "previousType": r["type"],
                        "sectionType": values["section"],
                    }
                    for r in rows
                ],
            )
        ],
        notes=["The requested type id should be present in 04 Objects/objects.json."],
    )


@feature(
    "planModelling.materialAssign",
    "Material Assign",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated)", "B1"),
        text("material", "Material id", "C30"),
    ],
)
def material_assign(ctx: FeatureContext, values: dict) -> dict:
    """Create a material-assignment schedule for the selected model members."""
    rows = _targets(ctx, values["memberIds"])
    return result(
        summary={"materialId": values["material"], "memberCount": len(rows)},
        tables=[
            table(
                "Material assignment preview",
                [("memberId", "Member"), ("category", "Category"), ("materialId", "Material")],
                [
                    {
                        "memberId": r["id"],
                        "category": r["category"],
                        "materialId": values["material"],
                    }
                    for r in rows
                ],
            )
        ],
    )


@feature(
    "planModelling.offsetMember",
    "Offset Member",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated)", "B1"),
        number("offsetXmm", "Physical offset X", 0, unit="mm"),
        number("offsetYmm", "Physical offset Y", 0, unit="mm"),
        number("offsetZmm", "Physical offset Z", 0, unit="mm"),
    ],
)
def offset_member(ctx: FeatureContext, values: dict) -> dict:
    """Resolve physical offset vectors and their three-dimensional magnitudes."""
    rows = _targets(ctx, values["memberIds"])
    magnitude = math.sqrt(
        values["offsetXmm"] ** 2 + values["offsetYmm"] ** 2 + values["offsetZmm"] ** 2
    )
    changes = [
        {
            "memberId": r["id"],
            "dxMm": values["offsetXmm"],
            "dyMm": values["offsetYmm"],
            "dzMm": values["offsetZmm"],
            "magnitudeMm": magnitude,
        }
        for r in rows
    ]
    return result(
        summary={"memberCount": len(changes), "offsetMagnitudeMm": magnitude},
        tables=[
            table(
                "Member offset vectors",
                [
                    ("memberId", "Member"),
                    ("dxMm", "X", "mm"),
                    ("dyMm", "Y", "mm"),
                    ("dzMm", "Z", "mm"),
                    ("magnitudeMm", "Magnitude", "mm"),
                ],
                changes,
            )
        ],
    )


@feature(
    "planModelling.rigidDiaphragm",
    "Rigid Diaphragm",
    part="floorPlan",
    fields=[
        text("storey", "Storey id", "L1"),
        select(
            "behavior", "Diaphragm behaviour", [("rigid", "Rigid"), ("semiRigid", "Semi-rigid")]
        ),
        number("eccentricityPercent", "Accidental eccentricity", 0, unit="%", min=0, max=20),
    ],
)
def rigid_diaphragm(ctx: FeatureContext, values: dict) -> dict:
    """Summarise slab areas at a storey and calculate the requested accidental eccentricity distance."""
    plan = plan_data(ctx)
    if values["storey"] not in story_map(plan):
        raise FeatureInputError("Choose an existing storey id.")
    slabs = [
        r for r in member_rows(plan) if r["category"] == "slab" and r["story"] == values["storey"]
    ]
    xs = [r["x1Mm"] for r in slabs]
    ys = [r["y1Mm"] for r in slabs]
    width, depth = (max(xs) - min(xs)) / 1000 if xs else 0, (max(ys) - min(ys)) / 1000 if ys else 0
    return result(
        summary={
            "storey": values["storey"],
            "behavior": values["behavior"],
            "slabCount": len(slabs),
            "floorAreaM2": sum(r["areaM2"] for r in slabs),
            "accidentalOffsetXM": width * values["eccentricityPercent"] / 100,
            "accidentalOffsetYM": depth * values["eccentricityPercent"] / 100,
        },
        notes=[
            "The slab envelope is used as a dimensional reference; diaphragm stiffness is not inferred from slab area."
        ],
    )


@feature(
    "planModelling.releases",
    "Releases",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated)", "B1"),
        checkbox("releaseStartMoment", "Release start bending moment", False),
        checkbox("releaseEndMoment", "Release end bending moment", False),
        checkbox("releaseShear", "Release shear at ends", False),
    ],
)
def releases(ctx: FeatureContext, values: dict) -> dict:
    """Create an explicit member-end release schedule from the selected freedom flags."""
    rows = _targets(ctx, values["memberIds"])
    release = {k: values[k] for k in ("releaseStartMoment", "releaseEndMoment", "releaseShear")}
    if not any(release.values()):
        raise FeatureInputError("Select at least one released action.")
    return result(
        summary={"memberCount": len(rows), "releasedActionCount": sum(release.values())},
        tables=[
            table(
                "End release assignment",
                [
                    ("memberId", "Member"),
                    ("startMomentFree", "Start moment free"),
                    ("endMomentFree", "End moment free"),
                    ("shearFree", "Shear free"),
                ],
                [
                    {
                        "memberId": r["id"],
                        "startMomentFree": release["releaseStartMoment"],
                        "endMomentFree": release["releaseEndMoment"],
                        "shearFree": release["releaseShear"],
                    }
                    for r in rows
                ],
            )
        ],
    )


@feature(
    "planModelling.supports",
    "Supports",
    part="floorPlan",
    fields=[
        text("supportPoint", "Support grid point", "A-1"),
        select(
            "restraint",
            "Support restraint",
            [
                ("pinned", "Pinned"),
                ("fixed", "Fixed"),
                ("rollerX", "Roller along X"),
                ("rollerY", "Roller along Y"),
            ],
        ),
        number("springKnPerM", "Translational spring stiffness", 0, unit="kN/m", min=0),
    ],
)
def supports(ctx: FeatureContext, values: dict) -> dict:
    """Translate support restraint choice into restrained and free translational directions."""
    plan = plan_data(ctx)
    from saengine.features.plan_common import parse_point, point_xy

    point = parse_point(values["supportPoint"])
    x, y = point_xy(plan, point)
    restraint = values["restraint"]
    restrained = {
        "pinned": ["X", "Y", "Z"],
        "fixed": ["X", "Y", "Z", "RX", "RY", "RZ"],
        "rollerX": ["Y", "Z"],
        "rollerY": ["X", "Z"],
    }[restraint]
    return result(
        summary={
            "restraint": restraint,
            "supportXmm": x,
            "supportYmm": y,
            "springKnPerM": values["springKnPerM"],
        },
        tables=[
            table(
                "Support degrees of freedom",
                [("restrained", "Restrained directions")],
                [{"restrained": ", ".join(restrained)}],
            )
        ],
    )


@feature(
    "planModelling.endLengthOffset",
    "End Length Offset",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated)", "B1"),
        number("startOffsetRatio", "Start offset / length", 0.05, min=0, max=0.49),
        number("endOffsetRatio", "End offset / length", 0.05, min=0, max=0.49),
    ],
)
def end_length_offset(ctx: FeatureContext, values: dict) -> dict:
    """Calculate rigid end-zone lengths as fractions of each selected member span."""
    rows = _targets(ctx, values["memberIds"])
    offsets = [
        {
            "memberId": r["id"],
            "startOffsetM": r.get("lengthM", 0) * values["startOffsetRatio"],
            "endOffsetM": r.get("lengthM", 0) * values["endOffsetRatio"],
            "clearLengthM": r.get("lengthM", 0)
            * (1 - values["startOffsetRatio"] - values["endOffsetRatio"]),
        }
        for r in rows
    ]
    return result(
        summary={
            "memberCount": len(offsets),
            "clearLengthM": sum(row["clearLengthM"] for row in offsets),
        },
        tables=[
            table(
                "Rigid end zones",
                [
                    ("memberId", "Member"),
                    ("startOffsetM", "Start offset", "m"),
                    ("endOffsetM", "End offset", "m"),
                    ("clearLengthM", "Clear length", "m"),
                ],
                offsets,
            )
        ],
    )


@feature(
    "planModelling.alignMembers",
    "Align Members",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated)", "C1,C2"),
        select(
            "alignment",
            "Alignment axis",
            [("x", "X coordinate"), ("y", "Y coordinate"), ("both", "Common point")],
        ),
        select(
            "method",
            "Target method",
            [
                ("mean", "Mean coordinate"),
                ("median", "Median coordinate"),
                ("first", "First member"),
            ],
        ),
    ],
)
def align_members(ctx: FeatureContext, values: dict) -> dict:
    """Find the target alignment coordinate for selected member centrelines."""
    rows = _targets(ctx, values["memberIds"])
    if not rows:
        raise FeatureInputError("Select at least one member.")
    out = []
    for axis, key in (("x", "x1Mm"), ("y", "y1Mm")):
        if values["alignment"] not in {axis, "both"}:
            continue
        coords = sorted(r.get(key, 0.0) for r in rows)
        target = (
            coords[0]
            if values["method"] == "first"
            else (
                coords[len(coords) // 2]
                if values["method"] == "median"
                else sum(coords) / len(coords)
            )
        )
        out.append(
            {
                "axis": axis.upper(),
                "targetCoordinateMm": target,
                "maxAdjustmentMm": max(abs(c - target) for c in coords),
            }
        )
    return result(
        summary={"memberCount": len(rows), "alignedAxes": len(out)},
        tables=[
            table(
                "Alignment target",
                [
                    ("axis", "Axis"),
                    ("targetCoordinateMm", "Target", "mm"),
                    ("maxAdjustmentMm", "Maximum move", "mm"),
                ],
                out,
            )
        ],
    )


@feature(
    "planModelling.snapSettings",
    "Snap Settings",
    part="floorPlan",
    fields=[
        checkbox("grid", "Snap to grid lines", True),
        checkbox("nodes", "Snap to member nodes", True),
        checkbox("midpoints", "Snap to member midpoints", False),
        number("toleranceMm", "Snap tolerance", 10, unit="mm", min=0),
    ],
)
def snap_settings(ctx: FeatureContext, values: dict) -> dict:
    """Report the active snap sources and the near-point tolerance."""
    enabled = [name for name in ("grid", "nodes", "midpoints") if values[name]]
    if not enabled:
        raise FeatureInputError("Enable at least one snap source.")
    return result(
        summary={"enabledSnapSources": len(enabled), "toleranceMm": values["toleranceMm"]},
        tables=[
            table(
                "Snap sources",
                [("source", "Source"), ("enabled", "Enabled")],
                [{"source": name, "enabled": True} for name in enabled],
            )
        ],
    )


@feature(
    "planModelling.autoSplit",
    "Auto Split",
    part="floorPlan",
    fields=[
        text("memberIds", "Beam ids (blank for all)", ""),
        number("toleranceMm", "Intersection tolerance", 1, unit="mm", min=0.01),
    ],
)
def auto_split(ctx: FeatureContext, values: dict) -> dict:
    """Find member crossings that are candidate beam split points."""
    from saengine.features.plan_common import intersection

    _plan, rows = profile(ctx)
    beams = [r for r in rows if r["category"] == "beam"]
    if values["memberIds"]:
        selected = {x.strip() for x in values["memberIds"].split(",") if x.strip()}
        beams = [r for r in beams if r["id"] in selected]
    crossings = []
    for i, a in enumerate(beams):
        for b in beams[i + 1 :]:
            if a["story"] != b["story"]:
                continue
            if intersection(
                (a["x1Mm"], a["y1Mm"]),
                (a["x2Mm"], a["y2Mm"]),
                (b["x1Mm"], b["y1Mm"]),
                (b["x2Mm"], b["y2Mm"]),
            ):
                crossings.append(
                    {
                        "memberA": a["id"],
                        "memberB": b["id"],
                        "story": a["story"],
                        "splitCandidate": True,
                    }
                )
    return result(
        summary={"candidateIntersections": len(crossings), "memberCount": len(beams)},
        tables=[
            table(
                "Interior beam crossings",
                [
                    ("memberA", "First beam"),
                    ("memberB", "Second beam"),
                    ("story", "Storey"),
                    ("splitCandidate", "Split candidate"),
                ],
                crossings,
            )
        ],
        notes=["Collinear overlaps and crossings between different storeys are excluded."],
    )


@feature(
    "planModelling.mergeMembers",
    "Merge Members",
    part="floorPlan",
    fields=[
        text("memberIds", "Beam ids (comma-separated)", "B1,B2"),
        number("collinearToleranceMm", "Collinearity tolerance", 1, unit="mm", min=0.01),
    ],
)
def merge_members(ctx: FeatureContext, values: dict) -> dict:
    """Check selected beams for common storey, orientation and endpoint continuity before merging."""
    rows = [r for r in _targets(ctx, values["memberIds"]) if r["category"] == "beam"]
    pairs = []
    for i, a in enumerate(rows):
        for b in rows[i + 1 :]:
            cross = abs(
                (a["x2Mm"] - a["x1Mm"]) * (b["y2Mm"] - b["y1Mm"])
                - (a["y2Mm"] - a["y1Mm"]) * (b["x2Mm"] - b["x1Mm"])
            )
            same_line = (
                cross <= values["collinearToleranceMm"] * max(a["lengthM"], b["lengthM"]) * 1000
            )
            touching = (
                min(
                    math.hypot(a["x2Mm"] - b["x1Mm"], a["y2Mm"] - b["y1Mm"]),
                    math.hypot(a["x1Mm"] - b["x2Mm"], a["y1Mm"] - b["y2Mm"]),
                )
                <= values["collinearToleranceMm"]
            )
            pairs.append(
                {
                    "memberA": a["id"],
                    "memberB": b["id"],
                    "sameStorey": a["story"] == b["story"],
                    "collinear": same_line,
                    "touching": touching,
                    "mergeCandidate": same_line and touching and a["story"] == b["story"],
                }
            )
    return result(
        summary={
            "candidatePairCount": sum(p["mergeCandidate"] for p in pairs),
            "testedPairCount": len(pairs),
        },
        tables=[
            table(
                "Beam merge candidates",
                [
                    ("memberA", "Beam A"),
                    ("memberB", "Beam B"),
                    ("sameStorey", "Same storey"),
                    ("collinear", "Collinear"),
                    ("touching", "Touching"),
                    ("mergeCandidate", "Candidate"),
                ],
                pairs,
            )
        ],
    )


@feature(
    "planModelling.copyDown",
    "Copy Down",
    part="floorPlan",
    fields=[
        text("memberIds", "Plan member ids", "B1,S1"),
        number("storeys", "Number of lower storeys", 1, min=1, max=100),
        checkbox("copyLoads", "Include associated loads", False),
    ],
)
def copy_down(ctx: FeatureContext, values: dict) -> dict:
    """Enumerate lower storeys available for copying the selected plan members."""
    plan, rows = profile(ctx)
    chosen = selected_members(rows, values["memberIds"])
    ordered = sorted(plan["stories"], key=lambda s: float(s["elevation"]))
    story_ids = {r["story"] for r in chosen}
    current = min(
        (
            ordered.index(next(s for s in ordered if s["id"] == st))
            for st in story_ids
            if any(s["id"] == st for s in ordered)
        ),
        default=0,
    )
    targets = ordered[max(0, current - int(values["storeys"])) : current]
    rows_out = [
        {
            "sourceId": row["id"],
            "targetStorey": s["id"],
            "targetElevationMm": s["elevation"],
            "loadsIncluded": values["copyLoads"],
        }
        for row in chosen
        for s in targets
        if row["category"] in {"beam", "slab", "footing"}
    ]
    return result(
        summary={"memberCount": len(chosen), "copyInstances": len(rows_out)},
        tables=[
            table(
                "Lower-storey copies",
                [
                    ("sourceId", "Source"),
                    ("targetStorey", "Storey"),
                    ("targetElevationMm", "Elevation", "mm"),
                    ("loadsIncluded", "Include loads"),
                ],
                rows_out,
            )
        ],
    )


@feature(
    "planModelling.mirrorPlan",
    "Mirror Plan",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated)", "B1"),
        select("axis", "Mirror axis", [("x", "X axis"), ("y", "Y axis")]),
        number("axisCoordinateMm", "Axis coordinate", 0, unit="mm"),
    ],
)
def mirror_plan(ctx: FeatureContext, values: dict) -> dict:
    """Calculate mirrored centerline coordinates for selected plan members."""
    rows = _targets(ctx, values["memberIds"])
    if values["axis"] == "x":
        output = [
            {
                "id": r["id"],
                "startCoordinateMm": 2 * values["axisCoordinateMm"] - r.get("y1Mm", 0),
                "endCoordinateMm": 2 * values["axisCoordinateMm"] - r.get("y2Mm", 0),
            }
            for r in rows
        ]
    else:
        output = [
            {
                "id": r["id"],
                "startCoordinateMm": 2 * values["axisCoordinateMm"] - r.get("x1Mm", 0),
                "endCoordinateMm": 2 * values["axisCoordinateMm"] - r.get("x2Mm", 0),
            }
            for r in rows
        ]
    return result(
        summary={"mirroredMembers": len(output), "axis": values["axis"]},
        tables=[
            table(
                "Mirrored plan coordinates",
                [
                    ("id", "Member"),
                    ("startCoordinateMm", "Start coordinate", "mm"),
                    ("endCoordinateMm", "End coordinate", "mm"),
                ],
                output,
            )
        ],
    )


@feature(
    "planModelling.rotatePlan",
    "Rotate Plan",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated)", "B1"),
        number("angleDeg", "Rotation", 90, unit="°"),
        number("originXmm", "Origin X", 0, unit="mm"),
        number("originYmm", "Origin Y", 0, unit="mm"),
    ],
)
def rotate_plan(ctx: FeatureContext, values: dict) -> dict:
    """Calculate rotated plan endpoints and preserve member lengths."""
    rows = _targets(ctx, values["memberIds"])
    angle, c, s = (
        math.radians(values["angleDeg"]),
        math.cos(math.radians(values["angleDeg"])),
        math.sin(math.radians(values["angleDeg"])),
    )
    del angle
    output = []
    for r in rows:

        def point(x: float, y: float) -> tuple[float, float]:
            dx, dy = x - values["originXmm"], y - values["originYmm"]
            return values["originXmm"] + c * dx - s * dy, values["originYmm"] + s * dx + c * dy

        a, b = point(r.get("x1Mm", 0), r.get("y1Mm", 0)), point(r.get("x2Mm", 0), r.get("y2Mm", 0))
        output.append(
            {
                "id": r["id"],
                "startXmm": a[0],
                "startYmm": a[1],
                "endXmm": b[0],
                "endYmm": b[1],
                "lengthM": r.get("lengthM", 0),
            }
        )
    return result(
        summary={"rotatedCount": len(output), "angleDeg": values["angleDeg"]},
        tables=[
            table(
                "Rotated plan members",
                [
                    ("id", "Member"),
                    ("startXmm", "Start X", "mm"),
                    ("startYmm", "Start Y", "mm"),
                    ("endXmm", "End X", "mm"),
                    ("endYmm", "End Y", "mm"),
                    ("lengthM", "Length", "m"),
                ],
                output,
            )
        ],
    )


@feature(
    "planModelling.dropPanel",
    "Drop Panel",
    part="floorPlan",
    fields=[
        text("slabId", "Slab id", "S1"),
        number("dropLengthMm", "Drop panel length", 2400, unit="mm", min=1),
        number("dropWidthMm", "Drop panel width", 2400, unit="mm", min=1),
        number("additionalThicknessMm", "Additional thickness", 75, unit="mm", min=1),
    ],
)
def drop_panel(ctx: FeatureContext, values: dict) -> dict:
    """Compute the drop-panel footprint and added concrete volume."""
    _, rows = profile(ctx)
    slab = next((r for r in rows if r["id"] == values["slabId"] and r["category"] == "slab"), None)
    if slab is None:
        raise FeatureInputError("Choose an existing slab id.")
    area = values["dropLengthMm"] * values["dropWidthMm"] / 1_000_000
    if area > slab["areaM2"]:
        raise FeatureInputError("Drop panel footprint exceeds the slab area.")
    return result(
        summary={
            "dropAreaM2": area,
            "addedConcreteM3": area * values["additionalThicknessMm"] / 1000,
            "slabAreaM2": slab["areaM2"],
        }
    )


@feature(
    "planModelling.columnHead",
    "Column Head",
    part="floorPlan",
    fields=[
        text("columnId", "Column id", "C1"),
        number("headDepthMm", "Head depth below slab", 300, unit="mm", min=1),
        number("headWidthMm", "Head width", 800, unit="mm", min=1),
    ],
)
def column_head(ctx: FeatureContext, values: dict) -> dict:
    """Calculate column-head volume per column from the entered head dimensions."""
    _, rows = profile(ctx)
    col = next(
        (r for r in rows if r["id"] == values["columnId"] and r["category"] == "column"), None
    )
    if col is None:
        raise FeatureInputError("Choose an existing column id.")
    plan = plan_data(ctx)
    raw = next(m for m in plan["columns"] if m["id"] == col["id"])
    obj = ctx.raw("objects") or {}
    section = next((o for o in obj.get("objects", []) if o.get("id") == raw["type"]), {})
    width = float(section.get("width", values["headWidthMm"]))
    volume = width * values["headWidthMm"] * values["headDepthMm"] / 1_000_000_000
    return result(
        summary={
            "columnId": col["id"],
            "headDepthMm": values["headDepthMm"],
            "headWidthMm": values["headWidthMm"],
            "additionalConcreteM3": volume,
        },
        notes=[
            "The section width is read from the object library when available; otherwise the entered head width is used for both plan dimensions."
        ],
    )


@feature(
    "planModelling.slabOpeningPerimeter",
    "Slab Opening Perimeter",
    part="floorPlan",
    fields=[
        number("widthMm", "Opening width", 1200, unit="mm", min=1),
        number("lengthMm", "Opening length", 1800, unit="mm", min=1),
        number("trimWidthMm", "Trim width", 200, unit="mm", min=0),
    ],
)
def slab_opening_perimeter(ctx: FeatureContext, values: dict) -> dict:
    """Calculate opening edge length and trim-material takeoff perimeter."""
    edge = 2 * (values["widthMm"] + values["lengthMm"]) / 1000
    return result(
        summary={
            "openingPerimeterM": edge,
            "trimCenterlineM": edge,
            "trimMaterialAreaM2": edge * values["trimWidthMm"] / 1000,
        }
    )


@feature(
    "planModelling.edgeBeamStiffener",
    "Edge Beam Stiffener",
    part="floorPlan",
    fields=[
        text("beamId", "Edge beam id", "B1"),
        number("stiffenerSpacingMm", "Stiffener spacing", 600, unit="mm", min=1),
        number("beamLengthM", "Beam length if not in plan", 0, unit="m", min=0),
    ],
)
def edge_beam_stiffener(ctx: FeatureContext, values: dict) -> dict:
    """Estimate the number of regularly spaced web stiffener pairs along an edge beam."""
    _, rows = profile(ctx)
    beam = next((r for r in rows if r["id"] == values["beamId"] and r["category"] == "beam"), None)
    length = beam["lengthM"] if beam else values["beamLengthM"]
    if length <= 0:
        raise FeatureInputError("Provide an existing beam id or a positive beam length.")
    count = max(0, math.ceil(length * 1000 / values["stiffenerSpacingMm"]) - 1)
    return result(
        summary={
            "beamLengthM": length,
            "stiffenerPairs": count,
            "actualEqualSpacingMm": length * 1000 / (count + 1),
        }
    )


@feature(
    "planModelling.extendToEdge",
    "Extend To Edge",
    part="floorPlan",
    fields=[
        text("memberId", "Beam id", "B1"),
        number("edgeDistanceMm", "Distance to target edge", 250, unit="mm", min=0),
    ],
)
def extend_to_edge(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the resulting beam length after extending its end to the target boundary."""
    _, rows = profile(ctx)
    beam = next(
        (r for r in rows if r["id"] == values["memberId"] and r["category"] == "beam"), None
    )
    if beam is None:
        raise FeatureInputError("Choose an existing beam id.")
    return result(
        summary={
            "currentLengthM": beam["lengthM"],
            "extendedLengthM": beam["lengthM"] + values["edgeDistanceMm"] / 1000,
            "extensionMm": values["edgeDistanceMm"],
        }
    )


@feature(
    "planModelling.trimToFace",
    "Trim To Face",
    part="floorPlan",
    fields=[
        text("memberId", "Beam id", "B1"),
        number("supportWidthMm", "Supporting member width", 300, unit="mm", min=1),
        number("trimSide", "Trim side fraction", 0.5, min=0, max=1),
    ],
)
def trim_to_face(ctx: FeatureContext, values: dict) -> dict:
    """Trim a beam end by the projected half-width of its support face."""
    _, rows = profile(ctx)
    beam = next(
        (r for r in rows if r["id"] == values["memberId"] and r["category"] == "beam"), None
    )
    if beam is None:
        raise FeatureInputError("Choose an existing beam id.")
    trim = values["supportWidthMm"] * values["trimSide"]
    remaining = beam["lengthM"] * 1000 - trim
    if remaining <= 0:
        raise FeatureInputError("Support face trim is longer than the beam.")
    return result(
        summary={"memberId": beam["id"], "faceTrimMm": trim, "clearLengthM": remaining / 1000}
    )


@feature(
    "planModelling.alignElevation",
    "Align Elevation",
    part="floorPlan",
    fields=[
        text("memberIds", "Column or wall ids", "C1"),
        select("reference", "Elevation reference", [("top", "Top"), ("base", "Base")]),
        number("targetElevationMm", "Target elevation", 3200, unit="mm"),
    ],
)
def align_elevation(ctx: FeatureContext, values: dict) -> dict:
    """Calculate elevation changes needed to align selected vertical member ends."""
    plan = plan_data(ctx)
    chosen = selected_members(member_rows(plan), values["memberIds"])
    stories = story_map(plan)
    output = []
    raw = {m["id"]: m for group in ("columns", "walls") for m in plan.get(group, [])}
    for row in chosen:
        item = raw.get(row["id"])
        if item is None:
            continue
        key = "top" if values["reference"] == "top" else "base"
        current = float(stories[item[key]]["elevation"])
        output.append(
            {
                "memberId": row["id"],
                "currentElevationMm": current,
                "targetElevationMm": values["targetElevationMm"],
                "requiredShiftMm": values["targetElevationMm"] - current,
            }
        )
    return result(
        summary={"alignedMemberCount": len(output), "reference": values["reference"]},
        tables=[
            table(
                "Vertical alignment changes",
                [
                    ("memberId", "Member"),
                    ("currentElevationMm", "Current", "mm"),
                    ("targetElevationMm", "Target", "mm"),
                    ("requiredShiftMm", "Shift", "mm"),
                ],
                output,
            )
        ],
    )

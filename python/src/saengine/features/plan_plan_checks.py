"""Checks ribbon: geometry, connectivity, assignments and load hygiene."""

from __future__ import annotations

import json
import math
from collections import Counter

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.plan_common import (
    export_csv,
    intersection,
    loads_data,
    member_groups,
    member_rows,
    plan_data,
    profile,
    segment_distance,
    story_map,
)


def _line_rows(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["category"] == "beam"]


@feature(
    "planChecks.duplicateMembers",
    "Duplicate Members",
    part="floorPlan",
    fields=[number("toleranceMm", "Endpoint tolerance", 1, unit="mm", min=0.01)],
)
def duplicate_members(ctx: FeatureContext, values: dict) -> dict:
    """Find same-type members with matching category, storey and endpoints, including reversed endpoints."""
    _plan, rows = profile(ctx)
    pairs = []
    for i, a in enumerate(rows):
        for b in rows[i + 1 :]:
            if a["category"] != b["category"] or a["type"] != b["type"] or a["story"] != b["story"]:
                continue
            direct = (
                math.hypot(a.get("x1Mm", 0) - b.get("x1Mm", 0), a.get("y1Mm", 0) - b.get("y1Mm", 0))
                <= values["toleranceMm"]
                and math.hypot(
                    a.get("x2Mm", 0) - b.get("x2Mm", 0), a.get("y2Mm", 0) - b.get("y2Mm", 0)
                )
                <= values["toleranceMm"]
            )
            reverse = (
                math.hypot(a.get("x1Mm", 0) - b.get("x2Mm", 0), a.get("y1Mm", 0) - b.get("y2Mm", 0))
                <= values["toleranceMm"]
                and math.hypot(
                    a.get("x2Mm", 0) - b.get("x1Mm", 0), a.get("y2Mm", 0) - b.get("y1Mm", 0)
                )
                <= values["toleranceMm"]
            )
            if direct or reverse:
                pairs.append(
                    {
                        "memberA": a["id"],
                        "memberB": b["id"],
                        "category": a["category"],
                        "storey": a["story"],
                        "reversed": reverse,
                    }
                )
    return result(
        summary={"duplicatePairs": len(pairs), "memberCount": len(rows)},
        tables=[
            table(
                "Duplicate member pairs",
                [
                    ("memberA", "Member A"),
                    ("memberB", "Member B"),
                    ("category", "Category"),
                    ("storey", "Storey"),
                    ("reversed", "Endpoint order reversed"),
                ],
                pairs,
            )
        ],
    )


@feature(
    "planChecks.overlapCheck",
    "Overlap Check",
    part="floorPlan",
    fields=[number("minimumOverlapMm", "Minimum overlap to report", 10, unit="mm", min=0)],
)
def overlap_check(ctx: FeatureContext, values: dict) -> dict:
    """Detect interior crossings and collinear overlap lengths among beams on the same storey."""
    _, rows = profile(ctx)
    beams = _line_rows(rows)
    findings = []
    for i, a in enumerate(beams):
        for b in beams[i + 1 :]:
            if a["story"] != b["story"]:
                continue
            crosses = intersection(
                (a["x1Mm"], a["y1Mm"]),
                (a["x2Mm"], a["y2Mm"]),
                (b["x1Mm"], b["y1Mm"]),
                (b["x2Mm"], b["y2Mm"]),
            )
            if crosses:
                findings.append(
                    {
                        "memberA": a["id"],
                        "memberB": b["id"],
                        "story": a["story"],
                        "kind": "interior crossing",
                        "overlapLengthM": 0.0,
                    }
                )
    return result(
        summary={"crossingPairs": len(findings)},
        tables=[
            table(
                "Beam crossings",
                [
                    ("memberA", "Member A"),
                    ("memberB", "Member B"),
                    ("story", "Storey"),
                    ("kind", "Finding"),
                    ("overlapLengthM", "Overlap", "m"),
                ],
                findings,
            )
        ],
        notes=[
            "Interior line crossings are reported; face-to-face physical overlap needs section dimensions and is not inferred from centerlines."
        ],
    )


@feature(
    "planChecks.zeroLengthCheck",
    "Zero-Length Check",
    part="floorPlan",
    fields=[number("minimumLengthMm", "Minimum member length", 1, unit="mm", min=0)],
)
def zero_length_check(ctx: FeatureContext, values: dict) -> dict:
    """Flag beams and vertical members whose computed centerline length is below tolerance."""
    _, rows = profile(ctx)
    flagged = [
        {"id": r["id"], "category": r["category"], "lengthMm": r.get("lengthM", 0) * 1000}
        for r in rows
        if r.get("lengthM", 0) * 1000 <= values["minimumLengthMm"]
    ]
    return result(
        summary={"shortMemberCount": len(flagged), "toleranceMm": values["minimumLengthMm"]},
        tables=[
            table(
                "Short members",
                [("id", "Member"), ("category", "Category"), ("lengthMm", "Length", "mm")],
                flagged,
            )
        ],
    )


@feature(
    "planChecks.unconnectedNodes",
    "Unconnected Nodes",
    part="floorPlan",
    fields=[number("toleranceMm", "Node merge tolerance", 1, unit="mm", min=0.01)],
)
def unconnected_nodes(ctx: FeatureContext, values: dict) -> dict:
    """List grid intersections not used by any beam, column, wall or slab boundary."""
    plan = plan_data(ctx)
    used = set()
    for group, members in member_groups(plan):
        for member in members:
            for key in ("at", "start", "end"):
                if key in member:
                    p = member[key]
                    used.add((p["x"], p["y"], float(p.get("dx", 0)), float(p.get("dy", 0))))
            for p in member.get("boundary", []):
                used.add((p["x"], p["y"], float(p.get("dx", 0)), float(p.get("dy", 0))))
    points = [
        {"gridPoint": f"{x['label']}-{y['label']}", "xMm": x["position"], "yMm": y["position"]}
        for x in plan["grids"]["x"]
        for y in plan["grids"]["y"]
    ]
    rows = [
        p
        for p in points
        if not any(
            math.hypot(
                p["xMm"]
                - (next(g["position"] for g in plan["grids"]["x"] if g["label"] == u[0]) + u[2]),
                p["yMm"]
                - (next(g["position"] for g in plan["grids"]["y"] if g["label"] == u[1]) + u[3]),
            )
            <= values["toleranceMm"]
            for u in used
        )
    ]
    return result(
        summary={"unconnectedGridIntersections": len(rows), "testedIntersections": len(points)},
        tables=[
            table(
                "Unused grid intersections",
                [("gridPoint", "Grid point"), ("xMm", "X", "mm"), ("yMm", "Y", "mm")],
                rows,
            )
        ],
    )


@feature(
    "planChecks.danglingMembers",
    "Dangling Members",
    part="floorPlan",
    fields=[text("memberCategories", "Categories to check", "beam,wall")],
)
def dangling_members(ctx: FeatureContext, values: dict) -> dict:
    """Identify beam and wall endpoints with no coincident member endpoint or vertical support."""
    _plan, rows = profile(ctx)
    cats = {x.strip() for x in values["memberCategories"].split(",")}
    endpoints = []
    for r in rows:
        if r["category"] in cats and r["category"] in {"beam", "wall"}:
            endpoints += [(r, "start", r["x1Mm"], r["y1Mm"]), (r, "end", r["x2Mm"], r["y2Mm"])]
    findings = []
    for r, end, x, y in endpoints:
        attached = any(
            other["id"] != r["id"]
            and other["story"] == r["story"]
            and math.hypot(x - other.get(kx, 0), y - other.get(ky, 0)) < 1
            for other in rows
            for kx, ky in (("x1Mm", "y1Mm"), ("x2Mm", "y2Mm"))
            if other["category"] in {"beam", "column", "wall"}
        )
        if not attached:
            findings.append(
                {"memberId": r["id"], "end": end, "xMm": x, "yMm": y, "storey": r["story"]}
            )
    return result(
        summary={"freeEndCount": len(findings)},
        tables=[
            table(
                "Unconnected member ends",
                [
                    ("memberId", "Member"),
                    ("end", "End"),
                    ("xMm", "X", "mm"),
                    ("yMm", "Y", "mm"),
                    ("storey", "Storey"),
                ],
                findings,
            )
        ],
    )


@feature(
    "planChecks.nodeMerge",
    "Node Merge",
    part="floorPlan",
    fields=[number("toleranceMm", "Merge tolerance", 10, unit="mm", min=0.01)],
)
def node_merge(ctx: FeatureContext, values: dict) -> dict:
    """Cluster distinct member endpoint coordinates that fall within the merge tolerance."""
    _, rows = profile(ctx)
    coords = []
    for r in rows:
        if r["category"] in {"beam", "column", "wall"}:
            coords += [
                (r["id"], "start", r.get("x1Mm", 0), r.get("y1Mm", 0)),
                (r["id"], "end", r.get("x2Mm", 0), r.get("y2Mm", 0)),
            ]
    pairs = []
    for i, a in enumerate(coords):
        for b in coords[i + 1 :]:
            distance = math.hypot(a[2] - b[2], a[3] - b[3])
            if a[0] != b[0] and 1e-6 < distance <= values["toleranceMm"]:
                pairs.append(
                    {
                        "memberA": a[0],
                        "endA": a[1],
                        "memberB": b[0],
                        "endB": b[1],
                        "distanceMm": distance,
                    }
                )
    return result(
        summary={"mergeCandidatePairs": len(pairs), "toleranceMm": values["toleranceMm"]},
        tables=[
            table(
                "Near-coincident member ends",
                [
                    ("memberA", "Member A"),
                    ("endA", "End A"),
                    ("memberB", "Member B"),
                    ("endB", "End B"),
                    ("distanceMm", "Distance", "mm"),
                ],
                pairs,
            )
        ],
    )


@feature(
    "planChecks.unloadedSlabs",
    "Unloaded Slabs",
    part="floorPlan",
    fields=[checkbox("includeDefaultLoad", "Count project default floor load", True)],
)
def unloaded_slabs(ctx: FeatureContext, values: dict) -> dict:
    """List slabs without an explicit area-load id when no project default floor load applies."""
    plan = plan_data(ctx)
    settings = ctx.raw("settings") or {}
    default = settings.get("floorLoad") if values["includeDefaultLoad"] else None
    slabs = [s for s in plan.get("slabs", []) if not s.get("areaLoad") and not default]
    return result(
        summary={"unloadedSlabCount": len(slabs), "defaultFloorLoadAvailable": bool(default)},
        tables=[
            table(
                "Slabs without an assigned area load",
                [("id", "Slab"), ("type", "Type"), ("story", "Storey")],
                [{"id": s["id"], "type": s["type"], "story": s["story"]} for s in slabs],
            )
        ],
        notes=[
            "This check uses the explicit areaLoad id and the project default floorLoad id only."
        ],
    )


@feature(
    "planChecks.loadSanity",
    "Load Sanity",
    part="floorPlan",
    fields=[
        number("referenceKpa", "Expected area load", 2.0, unit="kPa", min=0),
        number("relativeTolerance", "Difference tolerance", 0.5, min=0, max=1),
    ],
)
def load_sanity(ctx: FeatureContext, values: dict) -> dict:
    """Compare explicit slab area loads in project settings with an engineer-entered benchmark."""
    settings = ctx.raw("settings") or {}
    definitions = settings.get("areaLoads", [])
    plan = plan_data(ctx)
    by_id = {item.get("id"): item for item in definitions}
    rows = []
    for slab in plan.get("slabs", []):
        area_load = by_id.get(slab.get("areaLoad"), {})
        actual = area_load.get("live", area_load.get("value"))
        if actual is None:
            continue
        actual = float(actual)
        diff = (
            (actual - values["referenceKpa"]) / values["referenceKpa"]
            if values["referenceKpa"]
            else 0
        )
        rows.append(
            {
                "slabId": slab["id"],
                "loadId": slab.get("areaLoad"),
                "intensityKpa": actual,
                "referenceKpa": values["referenceKpa"],
                "outsideTolerance": abs(diff) > values["relativeTolerance"],
            }
        )
    return result(
        summary={
            "comparedSlabs": len(rows),
            "outsideToleranceCount": sum(r["outsideTolerance"] for r in rows),
        },
        tables=[
            table(
                "Slab load comparison",
                [
                    ("slabId", "Slab"),
                    ("loadId", "Load definition"),
                    ("intensityKpa", "Load", "kPa"),
                    ("referenceKpa", "Reference", "kPa"),
                    ("outsideTolerance", "Out of tolerance"),
                ],
                rows,
            )
        ],
        notes=["The comparison is a screening benchmark, not a prescribed occupancy load."],
    )


@feature(
    "planChecks.massCheck",
    "Mass Check",
    part="floorPlan",
    fields=[
        number("slabThicknessMm", "Slab thickness", 150, unit="mm", min=1),
        number("concreteDensityKnPerM3", "Concrete unit weight", 24, unit="kN/m³", min=1),
        number("seismicLiveFraction", "Live-load mass fraction", 0, min=0, max=1),
    ],
)
def mass_check(ctx: FeatureContext, values: dict) -> dict:
    """Estimate floor slab mass weight and compare it with the included takeoff inputs."""
    _, rows = profile(ctx)
    slabs = [r for r in rows if r["category"] == "slab"]
    floor_area = sum(r["areaM2"] for r in slabs)
    self_weight = floor_area * values["slabThicknessMm"] / 1000 * values["concreteDensityKnPerM3"]
    settings = ctx.raw("settings") or {}
    area_loads = {l.get("id"): l for l in settings.get("areaLoads", [])}
    live = (
        sum(
            r["areaM2"]
            * float(
                area_loads.get(
                    next(
                        (
                            s.get("areaLoad")
                            for s in (ctx.raw("floorPlan") or {}).get("slabs", [])
                            if s.get("id") == r["id"]
                        ),
                        None,
                    ),
                    {},
                ).get("live", 0)
                or 0
            )
            for r in slabs
        )
        * values["seismicLiveFraction"]
    )
    return result(
        summary={
            "slabAreaM2": floor_area,
            "slabSelfWeightKn": self_weight,
            "includedLiveMassKn": live,
            "estimatedSeismicWeightKn": self_weight + live,
        },
        notes=[
            "Only slab concrete self-weight and the entered fraction of explicit slab live loads are included; beam, wall and equipment mass are omitted."
        ],
    )


@feature("planChecks.modelStatistics", "Model Statistics", part="floorPlan", fields=[])
def model_statistics(ctx: FeatureContext, values: dict) -> dict:
    """Count floor-plan grids, storeys, members, slab area and underlays."""
    plan, rows = profile(ctx)
    counts = Counter(r["category"] for r in rows)
    return result(
        summary={
            "gridLines": len(plan["grids"]["x"]) + len(plan["grids"]["y"]),
            "storeys": len(plan["stories"]),
            "members": len(rows),
            "slabAreaM2": sum(r.get("areaM2", 0) for r in rows),
            "underlays": len(plan.get("underlays", [])),
        },
        tables=[
            table(
                "Counts by member category",
                [("category", "Category"), ("count", "Count")],
                [
                    {"category": key, "count": counts.get(key, 0)}
                    for key in ("column", "beam", "wall", "slab", "footing")
                ],
            )
        ],
    )


@feature(
    "planChecks.exportModelLog",
    "Export Model Log",
    part="floorPlan",
    fields=[text("filename", "Export filename", "model-log.csv")],
)
def export_model_log(ctx: FeatureContext, values: dict) -> dict:
    """Write member identity, category, storey, section and geometric length to a CSV log."""
    _, rows = profile(ctx)
    name = values["filename"].strip() or "model-log.csv"
    if "/" in name or "\\" in name or not name.lower().endswith(".csv"):
        raise FeatureInputError("Use a simple .csv filename without folders.")
    path = export_csv(
        ctx, name, ["id", "category", "type", "story", "lengthM", "areaM2", "perimeterM"], rows
    )
    return result(
        summary={"memberCount": len(rows), "file": path}, notes=[f"Wrote model log to {path}."]
    )


@feature(
    "planChecks.issueList",
    "Issue List",
    part="floorPlan",
    fields=[number("toleranceMm", "Geometry tolerance", 1, unit="mm", min=0.01)],
)
def issue_list(ctx: FeatureContext, values: dict) -> dict:
    """Create actionable findings for duplicate IDs, very short members and unresolved sections."""
    _plan, rows = profile(ctx)
    issues = []
    counts = Counter(r["id"] for r in rows)
    for r in rows:
        if counts[r["id"]] > 1:
            issues.append(
                {"severity": "error", "memberId": r["id"], "issue": "duplicate member id"}
            )
        if r.get("lengthM", 0) * 1000 <= values["toleranceMm"]:
            issues.append(
                {
                    "severity": "warning",
                    "memberId": r["id"],
                    "issue": "member length at or below tolerance",
                }
            )
    objects = {o.get("id") for o in (ctx.raw("objects") or {}).get("objects", [])}
    for r in rows:
        if objects and r["type"] not in objects:
            issues.append(
                {"severity": "error", "memberId": r["id"], "issue": "object type id not found"}
            )
    return result(
        summary={
            "issueCount": len(issues),
            "errorCount": sum(i["severity"] == "error" for i in issues),
            "warningCount": sum(i["severity"] == "warning" for i in issues),
        },
        tables=[
            table(
                "Model issues",
                [("severity", "Severity"), ("memberId", "Member"), ("issue", "Issue")],
                issues,
            )
        ],
    )


@feature(
    "planChecks.memberAlignment",
    "Member Alignment",
    part="floorPlan",
    fields=[number("toleranceMm", "Grid alignment tolerance", 5, unit="mm", min=0)],
)
def member_alignment(ctx: FeatureContext, values: dict) -> dict:
    """Find vertical supports with offsets that exceed the nearest-grid alignment tolerance."""
    plan, rows = profile(ctx)
    findings = []
    xs = [float(g["position"]) for g in plan["grids"]["x"]]
    ys = [float(g["position"]) for g in plan["grids"]["y"]]
    for r in rows:
        if r["category"] not in {"column", "wall"}:
            continue
        dx = min((abs(r.get("x1Mm", 0) - x) for x in xs), default=math.inf)
        dy = min((abs(r.get("y1Mm", 0) - y) for y in ys), default=math.inf)
        if dx > values["toleranceMm"] or dy > values["toleranceMm"]:
            findings.append(
                {
                    "memberId": r["id"],
                    "nearestGridOffsetXMm": dx,
                    "nearestGridOffsetYMm": dy,
                    "story": r["story"],
                }
            )
    return result(
        summary={"misalignedCount": len(findings), "toleranceMm": values["toleranceMm"]},
        tables=[
            table(
                "Supports away from grid lines",
                [
                    ("memberId", "Member"),
                    ("nearestGridOffsetXMm", "X offset", "mm"),
                    ("nearestGridOffsetYMm", "Y offset", "mm"),
                    ("story", "Storey"),
                ],
                findings,
            )
        ],
    )


@feature(
    "planChecks.supportOffsetCheck",
    "Support Offset Check",
    part="floorPlan",
    fields=[number("maximumOffsetMm", "Maximum support eccentricity", 50, unit="mm", min=0)],
)
def support_offset_check(ctx: FeatureContext, values: dict) -> dict:
    """Flag column and wall base points offset from every beam endpoint by more than the limit."""
    _, rows = profile(ctx)
    ends = [(r.get("x1Mm", 0), r.get("y1Mm", 0)) for r in rows if r["category"] == "beam"] + [
        (r.get("x2Mm", 0), r.get("y2Mm", 0)) for r in rows if r["category"] == "beam"
    ]
    findings = []
    for r in rows:
        if r["category"] not in {"column", "wall"}:
            continue
        d = min(
            (math.hypot(r.get("x1Mm", 0) - x, r.get("y1Mm", 0) - y) for x, y in ends),
            default=math.inf,
        )
        if d > values["maximumOffsetMm"]:
            findings.append({"memberId": r["id"], "nearestBeamEndDistanceMm": d})
    return result(
        summary={"unsupportedOffsetCount": len(findings), "limitMm": values["maximumOffsetMm"]},
        tables=[
            table(
                "Support offsets",
                [("memberId", "Support"), ("nearestBeamEndDistanceMm", "Nearest beam end", "mm")],
                findings,
            )
        ],
    )


@feature(
    "planChecks.memberOverlapLength",
    "Member Overlap Length",
    part="floorPlan",
    fields=[number("toleranceMm", "Collinearity tolerance", 1, unit="mm", min=0.01)],
)
def member_overlap_length(ctx: FeatureContext, values: dict) -> dict:
    """Measure collinear shared projection between beam centerlines on the same storey."""
    _, rows = profile(ctx)
    beams = _line_rows(rows)
    findings = []
    for i, a in enumerate(beams):
        for b in beams[i + 1 :]:
            if a["story"] != b["story"]:
                continue
            va = (a["x2Mm"] - a["x1Mm"], a["y2Mm"] - a["y1Mm"])
            length = math.hypot(*va)
            if length == 0:
                continue
            distance = (
                abs(va[0] * (b["y1Mm"] - a["y1Mm"]) - va[1] * (b["x1Mm"] - a["x1Mm"])) / length
            )
            if distance > values["toleranceMm"]:
                continue
            unit = (va[0] / length, va[1] / length)
            pa = (0.0, length)
            pb = sorted(
                (
                    (b["x1Mm"] - a["x1Mm"]) * unit[0] + (b["y1Mm"] - a["y1Mm"]) * unit[1],
                    (b["x2Mm"] - a["x1Mm"]) * unit[0] + (b["y2Mm"] - a["y1Mm"]) * unit[1],
                )
            )
            overlap = max(0, min(pa[1], pb[1]) - max(pa[0], pb[0]))
            if overlap > 0:
                findings.append(
                    {
                        "memberA": a["id"],
                        "memberB": b["id"],
                        "overlapLengthM": overlap / 1000,
                        "offsetMm": distance,
                    }
                )
    return result(
        summary={"overlappingPairs": len(findings)},
        tables=[
            table(
                "Collinear beam overlaps",
                [
                    ("memberA", "Member A"),
                    ("memberB", "Member B"),
                    ("overlapLengthM", "Overlap", "m"),
                    ("offsetMm", "Centerline offset", "mm"),
                ],
                findings,
            )
        ],
    )


@feature(
    "planChecks.sectionOrientation",
    "Section Orientation",
    part="floorPlan",
    fields=[
        number("expectedRotationDeg", "Expected rotation", 0, unit="°"),
        number("toleranceDeg", "Angular tolerance", 1, unit="°", min=0),
    ],
)
def section_orientation(ctx: FeatureContext, values: dict) -> dict:
    """Find columns whose stored section rotation differs from the expected orientation."""
    plan = plan_data(ctx)
    findings = []
    for col in plan["columns"]:
        delta = abs(
            (float(col.get("rotation", 0)) - values["expectedRotationDeg"] + 180) % 360 - 180
        )
        if delta > values["toleranceDeg"]:
            findings.append(
                {
                    "memberId": col["id"],
                    "rotationDeg": col.get("rotation", 0),
                    "differenceDeg": delta,
                }
            )
    return result(
        summary={"misorientedColumns": len(findings), "toleranceDeg": values["toleranceDeg"]},
        tables=[
            table(
                "Column section rotations",
                [
                    ("memberId", "Column"),
                    ("rotationDeg", "Rotation", "°"),
                    ("differenceDeg", "Difference", "°"),
                ],
                findings,
            )
        ],
    )


@feature(
    "planChecks.memberCollinearity",
    "Member Collinearity",
    part="floorPlan",
    fields=[number("toleranceMm", "Line deviation tolerance", 5, unit="mm", min=0)],
)
def member_collinearity(ctx: FeatureContext, values: dict) -> dict:
    """Report intermediate beam endpoints that drift off the best-fit line of an ordered chain."""
    _, rows = profile(ctx)
    beams = _line_rows(rows)
    findings = []
    for a in beams:
        for b in beams:
            if a["id"] >= b["id"] or a["story"] != b["story"]:
                continue
            for a_end in ((a["x1Mm"], a["y1Mm"]), (a["x2Mm"], a["y2Mm"])):
                for b_end in ((b["x1Mm"], b["y1Mm"]), (b["x2Mm"], b["y2Mm"])):
                    if (
                        math.hypot(a_end[0] - b_end[0], a_end[1] - b_end[1])
                        > values["toleranceMm"] * 2
                    ):
                        continue
                    others = [
                        p
                        for p in (
                            (a["x1Mm"], a["y1Mm"]),
                            (a["x2Mm"], a["y2Mm"]),
                            (b["x1Mm"], b["y1Mm"]),
                            (b["x2Mm"], b["y2Mm"]),
                        )
                        if p not in (a_end, b_end)
                    ]
                    if len(others) == 2:
                        deviation = segment_distance(a_end, others[0], others[1])
                        if deviation > values["toleranceMm"]:
                            findings.append(
                                {
                                    "memberA": a["id"],
                                    "memberB": b["id"],
                                    "jointDeviationMm": deviation,
                                }
                            )
    return result(
        summary={"noncollinearJoints": len(findings)},
        tables=[
            table(
                "Beam-chain alignment",
                [
                    ("memberA", "Member A"),
                    ("memberB", "Member B"),
                    ("jointDeviationMm", "Deviation", "mm"),
                ],
                findings,
            )
        ],
    )


@feature(
    "planChecks.hangingNode",
    "Hanging Node",
    part="floorPlan",
    fields=[number("loadThresholdKn", "Minimum joint load", 0, unit="kN", min=0)],
)
def hanging_node(ctx: FeatureContext, values: dict) -> dict:
    """Find endpoint coordinates incident to one beam only and compare with supports and point loads."""
    _, rows = profile(ctx)
    nodes = Counter()
    for r in _line_rows(rows):
        for p in ((r["x1Mm"], r["y1Mm"]), (r["x2Mm"], r["y2Mm"])):
            nodes[p] += 1
    supported = {
        (r.get("x1Mm", 0), r.get("y1Mm", 0)) for r in rows if r["category"] in {"column", "wall"}
    }
    dangling = [
        {
            "xMm": p[0],
            "yMm": p[1],
            "incidentBeams": count,
            "supportPresent": p in supported,
            "jointLoadKn": 0.0,
        }
        for p, count in nodes.items()
        if count == 1 and p not in supported and 0 >= values["loadThresholdKn"]
    ]
    return result(
        summary={"hangingNodeCount": len(dangling)},
        tables=[
            table(
                "Potential hanging beam nodes",
                [
                    ("xMm", "X", "mm"),
                    ("yMm", "Y", "mm"),
                    ("incidentBeams", "Incident beams"),
                    ("supportPresent", "Support present"),
                    ("jointLoadKn", "Known point load", "kN"),
                ],
                dangling,
            )
        ],
        notes=[
            "The floor-plan file has no nodal point-load records; jointLoadKn is zero for this geometry-only screen."
        ],
    )


@feature(
    "planChecks.missingSections",
    "Missing Sections",
    part="floorPlan",
    fields=[checkbox("flagGenericTypes", "Flag types without object definitions", True)],
)
def missing_sections(ctx: FeatureContext, values: dict) -> dict:
    """List members whose type id is absent from the project object library or is a generic default."""
    _, rows = profile(ctx)
    object_ids = {o.get("id") for o in (ctx.raw("objects") or {}).get("objects", [])}
    bad = []
    for r in rows:
        if (object_ids and r["type"] not in object_ids) or (
            values["flagGenericTypes"]
            and r["type"].lower() in {"default", "generic", "unspecified"}
        ):
            bad.append(
                {
                    "memberId": r["id"],
                    "category": r["category"],
                    "type": r["type"],
                    "missingFromLibrary": bool(object_ids and r["type"] not in object_ids),
                }
            )
    return result(
        summary={"membersWithoutResolvedSection": len(bad), "objectTypesLoaded": len(object_ids)},
        tables=[
            table(
                "Missing section assignments",
                [
                    ("memberId", "Member"),
                    ("category", "Category"),
                    ("type", "Type id"),
                    ("missingFromLibrary", "Missing type"),
                ],
                bad,
            )
        ],
    )


@feature(
    "planChecks.missingMaterials",
    "Missing Materials",
    part="floorPlan",
    fields=[text("materialField", "Material property name", "material")],
)
def missing_materials(ctx: FeatureContext, values: dict) -> dict:
    """Find object definitions and members that do not resolve a material grade."""
    _plan, rows = profile(ctx)
    objects = {o.get("id"): o for o in (ctx.raw("objects") or {}).get("objects", [])}
    known = {m.get("id") for m in (ctx.raw("materials") or {}).get("materials", [])}
    findings = []
    for r in rows:
        definition = objects.get(r["type"], {})
        material = definition.get(values["materialField"])
        if not material or (known and material not in known):
            findings.append(
                {
                    "memberId": r["id"],
                    "type": r["type"],
                    "material": material or "",
                    "materialFound": bool(material and (not known or material in known)),
                }
            )
    return result(
        summary={"unresolvedMaterialCount": len(findings), "materialsLoaded": len(known)},
        tables=[
            table(
                "Members without a resolved material",
                [
                    ("memberId", "Member"),
                    ("type", "Type"),
                    ("material", "Material"),
                    ("materialFound", "Resolved"),
                ],
                findings,
            )
        ],
    )


@feature("planChecks.unassignedLoads", "Unassigned Loads", part="floorPlan", fields=[])
def unassigned_loads(ctx: FeatureContext, values: dict) -> dict:
    """List load records whose member id no longer exists in the current floor plan."""
    plan = plan_data(ctx)
    known = {r["id"] for r in member_rows(plan)}
    data = loads_data(ctx)
    bad = [
        {"loadId": item.get("id"), "memberId": item.get("member"), "case": item.get("case", "SD")}
        for item in data.get("loads", [])
        if item.get("member") not in known
    ]
    return result(
        summary={"unassignedLoadCount": len(bad), "loadRecordCount": len(data.get("loads", []))},
        tables=[
            table(
                "Loads with deleted targets",
                [("loadId", "Load"), ("memberId", "Member id"), ("case", "Case")],
                bad,
            )
        ],
    )


@feature(
    "planChecks.storeyMismatch",
    "Storey Mismatch",
    part="floorPlan",
    fields=[number("levelToleranceMm", "Level tolerance", 100, unit="mm", min=0)],
)
def storey_mismatch(ctx: FeatureContext, values: dict) -> dict:
    """Check member storey references and vertical extents against the defined story elevations."""
    plan, _rows = profile(ctx)
    stories = story_map(plan)
    issues = []
    for group, members in member_groups(plan):
        for m in members:
            for field in ("story", "base", "top"):
                if field in m and m[field] not in stories:
                    issues.append(
                        {
                            "memberId": m["id"],
                            "reference": field,
                            "storeyId": m[field],
                            "issue": "storey does not exist",
                        }
                    )
            if (
                group == "columns"
                and m.get("base") in stories
                and m.get("top") in stories
                and float(stories[m["top"]]["elevation"]) - float(stories[m["base"]]["elevation"])
                <= values["levelToleranceMm"]
            ):
                issues.append(
                    {
                        "memberId": m["id"],
                        "reference": "vertical span",
                        "storeyId": m.get("base"),
                        "issue": "vertical span is within level tolerance",
                    }
                )
    return result(
        summary={"storeyIssues": len(issues), "storeyCount": len(stories)},
        tables=[
            table(
                "Storey reference issues",
                [
                    ("memberId", "Member"),
                    ("reference", "Reference"),
                    ("storeyId", "Storey id"),
                    ("issue", "Issue"),
                ],
                issues,
            )
        ],
    )


@feature(
    "planChecks.unitConsistency",
    "Unit Consistency",
    part="floorPlan",
    fields=[
        number("maximumCoordinateMm", "Plausible maximum coordinate", 1_000_000, unit="mm", min=1)
    ],
)
def unit_consistency(ctx: FeatureContext, values: dict) -> dict:
    """Screen grid, story and member offsets for values outside the floor plan's millimetre convention."""
    plan = plan_data(ctx)
    findings = []
    for axis in ("x", "y"):
        for line in plan["grids"][axis]:
            if abs(float(line["position"])) > values["maximumCoordinateMm"]:
                findings.append(
                    {
                        "element": line["label"],
                        "field": f"grid.{axis}.position",
                        "value": line["position"],
                        "expectedUnit": "mm",
                    }
                )
    for story in plan["stories"]:
        if abs(float(story["elevation"])) > values["maximumCoordinateMm"]:
            findings.append(
                {
                    "element": story["id"],
                    "field": "story.elevation",
                    "value": story["elevation"],
                    "expectedUnit": "mm",
                }
            )
    return result(
        summary={
            "unitAnomalies": len(findings),
            "maximumCoordinateMm": values["maximumCoordinateMm"],
        },
        tables=[
            table(
                "Coordinate unit outliers",
                [
                    ("element", "Element"),
                    ("field", "Field"),
                    ("value", "Value"),
                    ("expectedUnit", "Expected unit"),
                ],
                findings,
            )
        ],
        notes=["Floor-plan coordinates and elevations are stored in millimetres by schema."],
    )


@feature(
    "planChecks.modelDiff",
    "Model Diff",
    part="floorPlan",
    fields=[text("snapshotJson", "Snapshot JSON (optional)", "")],
)
def model_diff(ctx: FeatureContext, values: dict) -> dict:
    """Compare current member identities and geometry with a supplied saved model snapshot."""
    plan, _rows = profile(ctx)
    if not values["snapshotJson"].strip():
        snapshot_path = ctx.path("05 Floor Plan/floor-plan.snapshot.json")
        if snapshot_path is None or not snapshot_path.is_file():
            raise FeatureInputError(
                "Supply snapshot JSON or add 05 Floor Plan/floor-plan.snapshot.json."
            )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    else:
        try:
            snapshot = json.loads(values["snapshotJson"])
        except ValueError as exc:
            raise FeatureInputError("Snapshot input must be valid JSON.") from exc
    old = {
        m["id"]: m
        for group in ("columns", "beams", "walls", "slabs", "footings")
        for m in snapshot.get(group, [])
    }
    now = {
        m["id"]: m
        for group in ("columns", "beams", "walls", "slabs", "footings")
        for m in plan.get(group, [])
    }
    diffs = []
    for mid in sorted(set(old) | set(now)):
        if mid not in old:
            diffs.append({"memberId": mid, "change": "added"})
        elif mid not in now:
            diffs.append({"memberId": mid, "change": "removed"})
        elif old[mid] != now[mid]:
            diffs.append({"memberId": mid, "change": "modified"})
    return result(
        summary={
            "changedMemberCount": len(diffs),
            "currentMembers": len(now),
            "snapshotMembers": len(old),
        },
        tables=[table("Model differences", [("memberId", "Member"), ("change", "Change")], diffs)],
    )

"""Floor Openings ribbon: opening geometry, trimming quantities and coordination checks."""

from __future__ import annotations

import math

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.plan_common import (
    export_csv,
    plan_data,
    profile,
    segment_distance,
)


@feature(
    "planGridsOpenings.slabOpening",
    "Slab Opening",
    part="floorPlan",
    fields=[
        text("slabId", "Slab id", "S1"),
        number("widthMm", "Opening width", 1200, unit="mm", min=1),
        number("lengthMm", "Opening length", 1800, unit="mm", min=1),
        number("slabThicknessMm", "Slab thickness", 150, unit="mm", min=1),
    ],
)
def slab_opening(ctx: FeatureContext, values: dict) -> dict:
    """Calculate opening area, perimeter and the remaining gross slab area."""
    _, rows = profile(ctx)
    slab = next((r for r in rows if r["id"] == values["slabId"] and r["category"] == "slab"), None)
    if slab is None:
        raise FeatureInputError("Choose an existing slab id.")
    area = values["widthMm"] * values["lengthMm"] / 1e6
    if area >= slab["areaM2"]:
        raise FeatureInputError("Opening must be smaller than the selected slab panel.")
    return result(
        summary={
            "openingAreaM2": area,
            "openingPerimeterM": 2 * (values["widthMm"] + values["lengthMm"]) / 1000,
            "remainingGrossAreaM2": slab["areaM2"] - area,
            "slabThicknessMm": values["slabThicknessMm"],
        }
    )


@feature(
    "planGridsOpenings.shaftOpening",
    "Shaft Opening",
    part="floorPlan",
    fields=[
        text("storeys", "Storey ids, bottom to top", "L1,L2,L3"),
        number("shaftWidthMm", "Shaft width", 1500, unit="mm", min=1),
        number("shaftLengthMm", "Shaft length", 2000, unit="mm", min=1),
    ],
)
def shaft_opening(ctx: FeatureContext, values: dict) -> dict:
    """Calculate repeated shaft cutout area and vertical height across selected storeys."""
    plan = plan_data(ctx)
    ids = [x.strip() for x in values["storeys"].split(",") if x.strip()]
    stories = {s["id"]: s for s in plan["stories"]}
    if not ids or any(i not in stories for i in ids):
        raise FeatureInputError("Enter existing storey ids in vertical order.")
    heights = (
        (float(stories[ids[-1]]["elevation"]) - float(stories[ids[0]]["elevation"])) / 1000
        if len(ids) > 1
        else 0
    )
    area = values["shaftWidthMm"] * values["shaftLengthMm"] / 1e6
    return result(
        summary={
            "shaftAreaM2PerFloor": area,
            "affectedStoreys": len(ids),
            "aggregateOpeningAreaM2": area * len(ids),
            "verticalExtentM": heights,
        }
    )


@feature(
    "planGridsOpenings.stairOpening",
    "Stair Opening",
    part="floorPlan",
    fields=[
        text("slabId", "Slab id", "S1"),
        number("stairWidthMm", "Stair width", 1200, unit="mm", min=1),
        number("wellLengthMm", "Stairwell length", 3000, unit="mm", min=1),
        number("landingLengthMm", "Landing length", 1200, unit="mm", min=0),
    ],
)
def stair_opening(ctx: FeatureContext, values: dict) -> dict:
    """Measure stairwell void area and compare its dimensions with the selected slab area."""
    _, rows = profile(ctx)
    slab = next((r for r in rows if r["id"] == values["slabId"] and r["category"] == "slab"), None)
    if slab is None:
        raise FeatureInputError("Choose an existing slab id.")
    area = values["stairWidthMm"] * (values["wellLengthMm"] + values["landingLengthMm"]) / 1e6
    return result(
        summary={
            "stairVoidAreaM2": area,
            "slabAreaM2": slab["areaM2"],
            "voidAreaFraction": area / slab["areaM2"],
            "fitsGrossArea": area < slab["areaM2"],
        }
    )


@feature(
    "planGridsOpenings.serviceHole",
    "Service Hole",
    part="floorPlan",
    fields=[
        number("diameterMm", "Hole diameter", 150, unit="mm", min=1),
        number("slabThicknessMm", "Slab thickness", 150, unit="mm", min=1),
        number("edgeDistanceMm", "Distance to free edge", 500, unit="mm", min=0),
    ],
)
def service_hole(ctx: FeatureContext, values: dict) -> dict:
    """Calculate round penetration area and a simple edge-ligament screen."""
    radius = values["diameterMm"] / 2
    area = math.pi * radius**2 / 1e6
    ligament = values["edgeDistanceMm"] - radius
    return result(
        summary={
            "holeAreaM2": area,
            "circumferenceM": math.pi * values["diameterMm"] / 1000,
            "edgeLigamentMm": ligament,
            "edgeLigamentToThickness": ligament / values["slabThicknessMm"],
        },
        notes=[
            "Edge ligament ratio is a geometric coordination check, not a slab strength design."
        ],
    )


@feature(
    "planGridsOpenings.edgeOffset",
    "Edge Offset",
    part="floorPlan",
    fields=[
        number("openingWidthMm", "Opening width", 1000, unit="mm", min=1),
        number("openingLengthMm", "Opening length", 1500, unit="mm", min=1),
        number("offsetMm", "Offset from slab edge", 300, unit="mm", min=0),
        number("edgeClearanceMm", "Required clear cover zone", 50, unit="mm", min=0),
    ],
)
def edge_offset(ctx: FeatureContext, values: dict) -> dict:
    """Check whether a rectangular opening offset leaves the required clear edge ligament."""
    remaining = values["offsetMm"] - values["edgeClearanceMm"]
    return result(
        summary={
            "openingAreaM2": values["openingWidthMm"] * values["openingLengthMm"] / 1e6,
            "edgeLigamentMm": remaining,
            "meetsClearance": remaining >= 0,
        }
    )


@feature(
    "planGridsOpenings.beamTrim",
    "Beam Trim",
    part="floorPlan",
    fields=[
        text("beamId", "Beam id", "B1"),
        number("openingWidthMm", "Opening width along beam", 1200, unit="mm", min=1),
        number("trimEachSideMm", "Additional end trim", 100, unit="mm", min=0),
    ],
)
def beam_trim(ctx: FeatureContext, values: dict) -> dict:
    """Calculate a beam segment removed by an opening and report the remaining beam length."""
    _, rows = profile(ctx)
    beam = next((r for r in rows if r["id"] == values["beamId"] and r["category"] == "beam"), None)
    if beam is None:
        raise FeatureInputError("Choose an existing beam id.")
    trimmed = values["openingWidthMm"] + 2 * values["trimEachSideMm"]
    remaining = beam["lengthM"] * 1000 - trimmed
    if remaining < 0:
        raise FeatureInputError("Opening and trim length exceed the selected beam span.")
    return result(
        summary={
            "beamLengthMm": beam["lengthM"] * 1000,
            "removedLengthMm": trimmed,
            "remainingLengthMm": remaining,
        }
    )


@feature(
    "planGridsOpenings.openingBoundary",
    "Opening Boundary",
    part="floorPlan",
    fields=[
        text("points", "Boundary x,y coordinates in mm", "1000,1000;2200,1000;2200,2800;1000,2800")
    ],
    requires_project=False,
)
def opening_boundary(ctx: FeatureContext, values: dict) -> dict:
    """Measure a polygonal opening boundary and tabulate its vertices."""
    pts = []
    try:
        for p in values["points"].split(";"):
            if p.strip():
                x, y = [float(v.strip()) for v in p.split(",")[:2]]
                pts.append((x, y))
    except ValueError as exc:
        raise FeatureInputError("Boundary coordinates must be x,y pairs in millimetres.") from exc
    if len(pts) < 3:
        raise FeatureInputError("An opening boundary needs at least three vertices.")
    area = (
        abs(
            sum(
                pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                for i in range(len(pts))
            )
        )
        / 2e6
    )
    perimeter = (
        sum(
            math.hypot(
                pts[(i + 1) % len(pts)][0] - pts[i][0], pts[(i + 1) % len(pts)][1] - pts[i][1]
            )
            for i in range(len(pts))
        )
        / 1000
    )
    return result(
        summary={"boundaryAreaM2": area, "perimeterM": perimeter, "vertexCount": len(pts)},
        tables=[
            table(
                "Opening vertices",
                [("order", "Order"), ("xMm", "X", "mm"), ("yMm", "Y", "mm")],
                [{"order": i + 1, "xMm": x, "yMm": y} for i, (x, y) in enumerate(pts)],
            )
        ],
    )


@feature(
    "planGridsOpenings.groupOpenings",
    "Group Openings",
    part="floorPlan",
    fields=[
        text("openingIds", "Opening ids", "O1,O2,O3"),
        text("groupName", "Opening group", "MEP risers"),
    ],
    requires_project=False,
)
def group_openings(ctx: FeatureContext, values: dict) -> dict:
    """Group opening identifiers and report unique membership count."""
    ids = [x.strip() for x in values["openingIds"].split(",") if x.strip()]
    duplicates = sorted({x for x in ids if ids.count(x) > 1})
    return result(
        summary={
            "groupName": values["groupName"],
            "openingCount": len(set(ids)),
            "duplicateIds": len(duplicates),
        },
        tables=[
            table(
                "Opening group",
                [("sequence", "Order"), ("openingId", "Opening")],
                [{"sequence": i + 1, "openingId": x} for i, x in enumerate(dict.fromkeys(ids))],
            )
        ],
        notes=[f"Repeated ids: {', '.join(duplicates) if duplicates else 'none'}."],
    )


@feature(
    "planGridsOpenings.tagOpening",
    "Tag Opening",
    part="floorPlan",
    fields=[
        text("openingId", "Opening id", "O1"),
        number("widthMm", "Opening width", 1200, unit="mm", min=1),
        number("lengthMm", "Opening length", 1800, unit="mm", min=1),
        text("tagPrefix", "Tag prefix", "OP"),
    ],
    requires_project=False,
)
def tag_opening(ctx: FeatureContext, values: dict) -> dict:
    """Create a stable opening tag and formatted dimension label."""
    area = values["widthMm"] * values["lengthMm"] / 1e6
    return result(
        summary={
            "tag": f"{values['tagPrefix']}-{values['openingId']}",
            "dimensionLabel": f"{values['widthMm']:.0f} × {values['lengthMm']:.0f} mm",
            "areaM2": area,
        }
    )


@feature(
    "planGridsOpenings.openingSchedule",
    "Opening Schedule",
    part="floorPlan",
    fields=[
        text(
            "records",
            "id,storey,widthMm,lengthMm; semicolon separated",
            "O1,L1,1200,1800;O2,L2,1500,2200",
        )
    ],
    requires_project=False,
)
def opening_schedule(ctx: FeatureContext, values: dict) -> dict:
    """Generate an area and perimeter schedule for supplied rectangular openings."""
    rows = []
    try:
        for rec in values["records"].split(";"):
            if rec.strip():
                oid, story, w, l = [x.strip() for x in rec.split(",")[:4]]
                w, l = float(w), float(l)
                rows.append(
                    {
                        "id": oid,
                        "storey": story,
                        "widthMm": w,
                        "lengthMm": l,
                        "areaM2": w * l / 1e6,
                        "perimeterM": 2 * (w + l) / 1000,
                    }
                )
    except (ValueError, IndexError) as exc:
        raise FeatureInputError(
            "Use id,storey,widthMm,lengthMm records separated by semicolons."
        ) from exc
    return result(
        summary={
            "openingCount": len(rows),
            "totalAreaM2": sum(r["areaM2"] for r in rows),
            "totalPerimeterM": sum(r["perimeterM"] for r in rows),
        },
        tables=[
            table(
                "Opening schedule",
                [
                    ("id", "Opening"),
                    ("storey", "Storey"),
                    ("widthMm", "Width", "mm"),
                    ("lengthMm", "Length", "mm"),
                    ("areaM2", "Area", "m²"),
                    ("perimeterM", "Perimeter", "m"),
                ],
                rows,
            )
        ],
    )


@feature(
    "planGridsOpenings.openingArea",
    "Opening Area",
    part="floorPlan",
    fields=[
        number("widthMm", "Opening width", 1200, unit="mm", min=1),
        number("lengthMm", "Opening length", 1800, unit="mm", min=1),
        number("count", "Number of identical openings", 1, min=1, max=1000),
    ],
)
def opening_area(ctx: FeatureContext, values: dict) -> dict:
    """Calculate aggregate removed area and edge perimeter for identical rectangular voids."""
    area = values["widthMm"] * values["lengthMm"] / 1e6
    perimeter = 2 * (values["widthMm"] + values["lengthMm"]) / 1000
    return result(
        summary={
            "areaPerOpeningM2": area,
            "totalOpeningAreaM2": area * values["count"],
            "totalEdgeLengthM": perimeter * values["count"],
            "openingCount": int(values["count"]),
        }
    )


@feature(
    "planGridsOpenings.exportOpenings",
    "Export Openings",
    part="floorPlan",
    fields=[
        text("records", "id,storey,widthMm,lengthMm; semicolon separated", "O1,L1,1200,1800"),
        text("filename", "CSV filename", "openings.csv"),
    ],
    requires_project=False,
)
def export_openings(ctx: FeatureContext, values: dict) -> dict:
    """Write a verified rectangular opening schedule to a CSV file."""
    rows = []
    try:
        for rec in values["records"].split(";"):
            if rec.strip():
                oid, story, w, l = [x.strip() for x in rec.split(",")[:4]]
                w, l = float(w), float(l)
                rows.append(
                    {"id": oid, "storey": story, "widthMm": w, "lengthMm": l, "areaM2": w * l / 1e6}
                )
    except (ValueError, IndexError) as exc:
        raise FeatureInputError(
            "Use id,storey,widthMm,lengthMm records separated by semicolons."
        ) from exc
    name = values["filename"].strip()
    if not name.lower().endswith(".csv") or "/" in name or "\\" in name:
        raise FeatureInputError("Use a simple .csv filename without folders.")
    path = export_csv(ctx, name, ["id", "storey", "widthMm", "lengthMm", "areaM2"], rows)
    return result(
        summary={"exportedOpenings": len(rows), "file": path},
        notes=[f"Wrote opening schedule to {path}."],
    )


@feature(
    "planGridsOpenings.edgeTrimmers",
    "Edge Trimmers",
    part="floorPlan",
    fields=[
        number("openingWidthMm", "Opening width", 1200, unit="mm", min=1),
        number("openingLengthMm", "Opening length", 1800, unit="mm", min=1),
        number("trimmerCount", "Trimmer members", 2, min=1),
        number("trimmerAreaMm2", "Trimmer section area", 50000, unit="mm²", min=1),
    ],
)
def edge_trimmers(ctx: FeatureContext, values: dict) -> dict:
    """Calculate trimmer member total length, steel area-length quantity and perimeter coverage."""
    perimeter = 2 * (values["openingWidthMm"] + values["openingLengthMm"]) / 1000
    total_length = perimeter * values["trimmerCount"]
    return result(
        summary={
            "openingPerimeterM": perimeter,
            "trimmerLengthM": total_length,
            "sectionAreaLengthM3": values["trimmerAreaMm2"] * total_length / 1e6,
            "trimmerCount": int(values["trimmerCount"]),
        },
        notes=[
            "Trimmer count and section area are explicit inputs; connection forces and member strength are not checked."
        ],
    )


@feature(
    "planGridsOpenings.extraRebar",
    "Extra Rebar",
    part="floorPlan",
    fields=[
        number("openingPerimeterM", "Opening perimeter", 6, unit="m", min=0.01),
        number("barAreaMm2", "Bar area", 200, unit="mm²", min=1),
        number("barsPerEdge", "Bars per edge", 2, min=1),
        number("developmentLengthM", "Development each end", 0.6, unit="m", min=0),
    ],
)
def extra_rebar(ctx: FeatureContext, values: dict) -> dict:
    """Estimate additional opening edge reinforcement bar length and steel volume."""
    count = int(values["barsPerEdge"])
    length = values["openingPerimeterM"] * count + 2 * values["developmentLengthM"] * 4 * count
    return result(
        summary={
            "barCountEquivalent": 4 * count,
            "totalBarLengthM": length,
            "steelVolumeM3": values["barAreaMm2"] * length / 1e6,
            "developmentLengthM": values["developmentLengthM"],
        },
        notes=[
            "Reinforcement count, area and development length are user inputs; anchorage and strength are not designed here."
        ],
    )


@feature(
    "planGridsOpenings.closureStrip",
    "Closure Strip",
    part="floorPlan",
    fields=[
        number("stripLengthM", "Strip length", 6, unit="m", min=0),
        number("stripWidthM", "Strip width", 0.8, unit="m", min=0),
        number("slabThicknessMm", "Slab thickness", 150, unit="mm", min=1),
    ],
)
def closure_strip(ctx: FeatureContext, values: dict) -> dict:
    """Calculate closure-strip area and concrete volume from its plan dimensions."""
    area = values["stripLengthM"] * values["stripWidthM"]
    return result(
        summary={
            "stripAreaM2": area,
            "concreteVolumeM3": area * values["slabThicknessMm"] / 1000,
            "perimeterM": 2 * (values["stripLengthM"] + values["stripWidthM"]),
        }
    )


@feature(
    "planGridsOpenings.pipeSleeve",
    "Pipe Sleeve",
    part="floorPlan",
    fields=[
        number("pipeDiameterMm", "Pipe outside diameter", 100, unit="mm", min=1),
        number("sleeveClearanceMm", "Radial clearance", 25, unit="mm", min=0),
        number("slabThicknessMm", "Slab thickness", 150, unit="mm", min=1),
    ],
)
def pipe_sleeve(ctx: FeatureContext, values: dict) -> dict:
    """Size a sleeve opening from pipe diameter and radial clearance, then calculate cutout area."""
    diameter = values["pipeDiameterMm"] + 2 * values["sleeveClearanceMm"]
    return result(
        summary={
            "sleeveDiameterMm": diameter,
            "openingAreaM2": math.pi * (diameter / 2) ** 2 / 1e6,
            "slabThicknessMm": values["slabThicknessMm"],
            "holeAspectRatio": values["slabThicknessMm"] / diameter,
        }
    )


@feature(
    "planGridsOpenings.ductPenetration",
    "Duct Penetration",
    part="floorPlan",
    fields=[
        number("ductWidthMm", "Duct width", 600, unit="mm", min=1),
        number("ductHeightMm", "Duct height", 300, unit="mm", min=1),
        number("clearanceMm", "Clearance each side", 50, unit="mm", min=0),
        number("slabThicknessMm", "Slab thickness", 150, unit="mm", min=1),
    ],
)
def duct_penetration(ctx: FeatureContext, values: dict) -> dict:
    """Calculate rectangular duct opening dimensions and lost slab area."""
    w = values["ductWidthMm"] + 2 * values["clearanceMm"]
    h = values["ductHeightMm"] + 2 * values["clearanceMm"]
    return result(
        summary={
            "openingWidthMm": w,
            "openingLengthMm": h,
            "openingAreaM2": w * h / 1e6,
            "openingPerimeterM": 2 * (w + h) / 1000,
            "slabThicknessMm": values["slabThicknessMm"],
        }
    )


@feature(
    "planGridsOpenings.firestopDetail",
    "Firestop Detail",
    part="floorPlan",
    fields=[
        number("openingPerimeterM", "Opening perimeter", 4, unit="m", min=0.01),
        number("sealDepthMm", "Seal depth", 100, unit="mm", min=1),
        number("sealDensityKgPerM3", "Seal density", 1200, unit="kg/m³", min=0),
    ],
)
def firestop_detail(ctx: FeatureContext, values: dict) -> dict:
    """Calculate seal volume and mass around the perimeter of an opening."""
    volume = values["openingPerimeterM"] * values["sealDepthMm"] / 1000 * 0.02
    return result(
        summary={
            "sealVolumeM3": volume,
            "sealMassKg": volume * values["sealDensityKgPerM3"],
            "perimeterM": values["openingPerimeterM"],
        },
        notes=["A 20 mm nominal seal width is used as an editable detailing assumption."],
    )


@feature(
    "planGridsOpenings.interferenceCheck",
    "Interference Check",
    part="floorPlan",
    fields=[
        number("centerXMm", "Opening centre X", 6000, unit="mm"),
        number("centerYMm", "Opening centre Y", 2500, unit="mm"),
        number("widthMm", "Opening width", 1200, unit="mm", min=1),
        number("lengthMm", "Opening length", 1800, unit="mm", min=1),
        number("clearanceMm", "Required beam clearance", 100, unit="mm", min=0),
    ],
)
def interference_check(ctx: FeatureContext, values: dict) -> dict:
    """Check a rectangular opening footprint against beam centerlines on the floor plan."""
    _, rows = profile(ctx)
    hx, hy = values["widthMm"] / 2, values["lengthMm"] / 2
    issues = []
    for beam in (r for r in rows if r["category"] == "beam"):
        a = (beam["x1Mm"], beam["y1Mm"])
        b = (beam["x2Mm"], beam["y2Mm"])
        d = segment_distance((values["centerXMm"], values["centerYMm"]), a, b)
        expanded = math.hypot(hx, hy) + values["clearanceMm"]
        if d <= expanded:
            issues.append(
                {
                    "beamId": beam["id"],
                    "centerlineDistanceMm": d,
                    "envelopeRadiusMm": expanded,
                    "potentialClash": True,
                }
            )
    return result(
        summary={"potentialClashes": len(issues), "clearanceMm": values["clearanceMm"]},
        tables=[
            table(
                "Opening and beam proximity",
                [
                    ("beamId", "Beam"),
                    ("centerlineDistanceMm", "Distance", "mm"),
                    ("envelopeRadiusMm", "Opening envelope", "mm"),
                    ("potentialClash", "Potential clash"),
                ],
                issues,
            )
        ],
        notes=[
            "The rectangular opening is screened by its circumscribed radius; exact corner-to-segment distances need a full polygon geometry check."
        ],
    )


@feature(
    "planGridsOpenings.minimumDistance",
    "Minimum Distance",
    part="floorPlan",
    fields=[
        text(
            "openingCentersMm",
            "Opening centres x,y; semicolon separated",
            "1000,1000;3000,1000;3000,4000",
        ),
        number("minimumMm", "Minimum clear centre spacing", 1000, unit="mm", min=0),
    ],
)
def minimum_distance(ctx: FeatureContext, values: dict) -> dict:
    """Find close opening-center pairs under a minimum distance threshold."""
    pts = []
    try:
        for item in values["openingCentersMm"].split(";"):
            if item.strip():
                x, y = [float(v.strip()) for v in item.split(",")[:2]]
                pts.append((x, y))
    except ValueError as exc:
        raise FeatureInputError("Opening centres must be x,y pairs in millimetres.") from exc
    pairs = []
    for i, a in enumerate(pts):
        for j, b in enumerate(pts[i + 1 :], i + 1):
            d = math.hypot(a[0] - b[0], a[1] - b[1])
            if d < values["minimumMm"]:
                pairs.append(
                    {
                        "openingA": i + 1,
                        "openingB": j + 1,
                        "centerDistanceMm": d,
                        "belowMinimum": True,
                    }
                )
    return result(
        summary={"openingCount": len(pts), "pairsBelowMinimum": len(pairs)},
        tables=[
            table(
                "Opening spacing check",
                [
                    ("openingA", "Opening A"),
                    ("openingB", "Opening B"),
                    ("centerDistanceMm", "Centre distance", "mm"),
                    ("belowMinimum", "Below minimum"),
                ],
                pairs,
            )
        ],
    )


@feature(
    "planGridsOpenings.openingSymbol",
    "Opening Symbol",
    part="floorPlan",
    fields=[
        text("openingId", "Opening id", "O1"),
        number("widthMm", "Opening width", 1200, unit="mm", min=1),
        number("lengthMm", "Opening length", 1800, unit="mm", min=1),
        number("symbolScale", "Symbol scale", 1, min=0.01),
    ],
)
def opening_symbol(ctx: FeatureContext, values: dict) -> dict:
    """Generate the plan symbol extents and dimension label for a rectangular opening."""
    return result(
        summary={
            "openingId": values["openingId"],
            "symbolWidthMm": values["widthMm"] * values["symbolScale"],
            "symbolLengthMm": values["lengthMm"] * values["symbolScale"],
            "label": f"{values['widthMm']:.0f} × {values['lengthMm']:.0f}",
        }
    )


@feature(
    "planGridsOpenings.openingSummary",
    "Opening Summary",
    part="floorPlan",
    fields=[
        text(
            "records",
            "id,storey,widthMm,lengthMm; semicolon separated",
            "O1,L1,1200,1800;O2,L1,900,900",
        )
    ],
    requires_project=False,
)
def opening_summary(ctx: FeatureContext, values: dict) -> dict:
    """Summarise supplied opening records by storey and total area."""
    rows = []
    try:
        for rec in values["records"].split(";"):
            if rec.strip():
                oid, story, w, l = [x.strip() for x in rec.split(",")[:4]]
                rows.append({"id": oid, "storey": story, "areaM2": float(w) * float(l) / 1e6})
    except (ValueError, IndexError) as exc:
        raise FeatureInputError(
            "Use id,storey,widthMm,lengthMm records separated by semicolons."
        ) from exc
    by = {}
    for r in rows:
        by[r["storey"]] = by.get(r["storey"], 0) + r["areaM2"]
    return result(
        summary={
            "openingCount": len(rows),
            "totalAreaM2": sum(r["areaM2"] for r in rows),
            "affectedStoreys": len(by),
        },
        tables=[
            table(
                "Opening area by storey",
                [("storey", "Storey"), ("openingCount", "Openings"), ("areaM2", "Area", "m²")],
                [
                    {
                        "storey": s,
                        "openingCount": sum(r["storey"] == s for r in rows),
                        "areaM2": area,
                    }
                    for s, area in sorted(by.items())
                ],
            )
        ],
    )

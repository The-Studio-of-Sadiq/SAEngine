"""Bracing ribbon: bay geometry, cable behaviour and link-beam checks."""

from __future__ import annotations

import json
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


def _bay(width: float, height: float) -> dict:
    diagonal = math.hypot(width, height)
    return {
        "bayWidthM": width,
        "storeyHeightM": height,
        "diagonalLengthM": diagonal,
        "angleDeg": math.degrees(math.atan2(height, width)),
        "diagonalToBayRatio": diagonal / width,
    }


@feature(
    "planMembersBracing.xBrace",
    "X Brace",
    part="floorPlan",
    fields=[
        number("bayWidthM", "Bay width", 6, unit="m", min=0.1),
        number("storeyHeightM", "Storey height", 3, unit="m", min=0.1),
        number("sectionAreaMm2", "Brace area", 2500, unit="mm²", min=1),
    ],
)
def x_brace(ctx: FeatureContext, values: dict) -> dict:
    """Calculate both X-brace diagonal lengths, angles and combined brace axial area."""
    geom = _bay(values["bayWidthM"], values["storeyHeightM"])
    return result(
        summary={
            **geom,
            "braceCount": 2,
            "totalBraceLengthM": 2 * geom["diagonalLengthM"],
            "totalAxialAreaMm2": 2 * values["sectionAreaMm2"],
        }
    )


@feature(
    "planMembersBracing.chevronBrace",
    "Chevron Brace",
    part="floorPlan",
    fields=[
        number("bayWidthM", "Bay width", 6, unit="m", min=0.1),
        number("storeyHeightM", "Storey height", 3, unit="m", min=0.1),
        number("braceTopSeparationM", "Top joint separation", 0, unit="m", min=0),
    ],
)
def chevron_brace(ctx: FeatureContext, values: dict) -> dict:
    """Calculate chevron brace lengths from the two top-joint offsets and storey geometry."""
    half = (values["bayWidthM"] - values["braceTopSeparationM"]) / 2
    if half <= 0:
        raise FeatureInputError("Top-joint separation must be smaller than the bay width.")
    length = math.hypot(half, values["storeyHeightM"])
    return result(
        summary={
            "braceLengthM": length,
            "braceAngleDeg": math.degrees(math.atan2(values["storeyHeightM"], half)),
            "unbracedBeamSegmentM": values["braceTopSeparationM"],
            "braceCount": 2,
        }
    )


@feature(
    "planMembersBracing.singleDiagonal",
    "Single Diagonal",
    part="floorPlan",
    fields=[
        number("bayWidthM", "Bay width", 6, unit="m", min=0.1),
        number("storeyHeightM", "Storey height", 3, unit="m", min=0.1),
        select(
            "orientation",
            "Diagonal orientation",
            [("rising", "Bottom left to top right"), ("falling", "Bottom right to top left")],
        ),
    ],
)
def single_diagonal(ctx: FeatureContext, values: dict) -> dict:
    """Calculate one diagonal brace's direction and length in a rectangular bay."""
    geom = _bay(values["bayWidthM"], values["storeyHeightM"])
    return result(
        summary={
            **geom,
            "orientation": values["orientation"],
            "signedAngleDeg": geom["angleDeg"]
            if values["orientation"] == "rising"
            else 180 - geom["angleDeg"],
        }
    )


@feature(
    "planMembersBracing.kBrace",
    "K Brace",
    part="floorPlan",
    fields=[
        number("bayWidthM", "Bay width", 6, unit="m", min=0.1),
        number("storeyHeightM", "Storey height", 3, unit="m", min=0.1),
        number("columnMidpointHeightRatio", "Column joint height ratio", 0.5, min=0.01, max=0.99),
    ],
)
def k_brace(ctx: FeatureContext, values: dict) -> dict:
    """Calculate K-brace leg lengths and intersection elevation relative to the storey."""
    h = values["storeyHeightM"]
    x = values["bayWidthM"]
    z = h * values["columnMidpointHeightRatio"]
    left = math.hypot(x / 2, z)
    right = math.hypot(x / 2, h - z)
    return result(
        summary={
            "lowerBraceLengthM": left,
            "upperBraceLengthM": right,
            "columnJointElevationM": z,
            "totalBraceLengthM": left + right,
        }
    )


@feature(
    "planMembersBracing.selectBraceBay",
    "Select Brace Bay",
    part="floorPlan",
    fields=[
        text("cornerA", "First bay corner grid point", "A-1"),
        text("cornerB", "Opposite bay corner grid point", "B-2"),
    ],
)
def select_brace_bay(ctx: FeatureContext, values: dict) -> dict:
    """Resolve the dimensions and member count of the selected grid-bounded brace bay."""
    plan, rows = profile(ctx)

    def point(raw: str) -> tuple[float, float]:
        try:
            x, y = raw.split("-", 1)
        except ValueError as exc:
            raise FeatureInputError("Use grid points in X-Y form, such as A-1.") from exc
        gx = next((g for g in plan["grids"]["x"] if g["label"] == x), None)
        gy = next((g for g in plan["grids"]["y"] if g["label"] == y), None)
        if gx is None or gy is None:
            raise FeatureInputError("Brace bay corners must be existing grid intersections.")
        return float(gx["position"]), float(gy["position"])

    a, b = point(values["cornerA"]), point(values["cornerB"])
    width, depth = abs(b[0] - a[0]) / 1000, abs(b[1] - a[1]) / 1000
    return result(
        summary={
            "cornerA": values["cornerA"],
            "cornerB": values["cornerB"],
            "bayWidthM": width,
            "bayDepthM": depth,
            "existingMembersInBay": sum(
                min(a[0], b[0]) <= r.get("x1Mm", 0) <= max(a[0], b[0])
                and min(a[1], b[1]) <= r.get("y1Mm", 0) <= max(a[1], b[1])
                for r in rows
            ),
        }
    )


@feature(
    "planMembersBracing.bracePattern",
    "Brace Pattern",
    part="floorPlan",
    fields=[
        text("bayNames", "Bay labels, comma-separated", "A1,B1,C1"),
        select(
            "pattern",
            "Pattern",
            [
                ("x", "X brace"),
                ("chevron", "Chevron"),
                ("single", "Single diagonal"),
                ("k", "K brace"),
            ],
        ),
        checkbox("alternate", "Alternate orientation", True),
    ],
)
def brace_pattern(ctx: FeatureContext, values: dict) -> dict:
    """Assign a brace configuration and alternating orientation across a sequence of bays."""
    bays = [x.strip() for x in values["bayNames"].split(",") if x.strip()]
    rows = [
        {
            "bay": name,
            "pattern": values["pattern"],
            "orientation": "rising" if not values["alternate"] or i % 2 == 0 else "falling",
        }
        for i, name in enumerate(bays)
    ]
    return result(
        summary={"configuredBays": len(rows), "pattern": values["pattern"]},
        tables=[
            table(
                "Bracing pattern layout",
                [("bay", "Bay"), ("pattern", "Pattern"), ("orientation", "Orientation")],
                rows,
            )
        ],
    )


@feature(
    "planMembersBracing.storyRange",
    "Story Range",
    part="floorPlan",
    fields=[
        text("firstStorey", "First storey id", "L1"),
        text("lastStorey", "Last storey id", "L3"),
    ],
)
def story_range(ctx: FeatureContext, values: dict) -> dict:
    """Resolve a continuous vertical brace range between two existing levels."""
    plan = __import__("saengine.features.plan_common", fromlist=["plan_data"]).plan_data(ctx)
    stories = sorted(plan["stories"], key=lambda s: float(s["elevation"]))
    ids = [s["id"] for s in stories]
    if values["firstStorey"] not in ids or values["lastStorey"] not in ids:
        raise FeatureInputError("Both brace range storeys must exist.")
    i, j = ids.index(values["firstStorey"]), ids.index(values["lastStorey"])
    if j < i:
        raise FeatureInputError("Last storey must be at or above the first storey.")
    selected = stories[i : j + 1]
    return result(
        summary={
            "storeysInRange": len(selected),
            "verticalRangeM": (float(selected[-1]["elevation"]) - float(selected[0]["elevation"]))
            / 1000,
        },
        tables=[
            table(
                "Brace story range",
                [("storey", "Storey"), ("elevationMm", "Elevation", "mm")],
                [{"storey": s["id"], "elevationMm": s["elevation"]} for s in selected],
            )
        ],
    )


@feature(
    "planMembersBracing.mirrorBracing",
    "Mirror Bracing",
    part="floorPlan",
    fields=[
        text("braceIds", "Brace member ids", "BR1,BR2"),
        number("mirrorAxisXMm", "Mirror axis X", 0, unit="mm"),
    ],
)
def mirror_bracing(ctx: FeatureContext, values: dict) -> dict:
    """Reflect selected brace endpoints through a vertical X-coordinate plane."""
    rows = selected_members(profile(ctx)[1], values["braceIds"])
    out = [
        {
            "id": r["id"],
            "startXmm": 2 * values["mirrorAxisXMm"] - r.get("x1Mm", 0),
            "endXmm": 2 * values["mirrorAxisXMm"] - r.get("x2Mm", 0),
            "startYmm": r.get("y1Mm", 0),
            "endYmm": r.get("y2Mm", 0),
        }
        for r in rows
    ]
    return result(
        summary={"mirroredBraces": len(out)},
        tables=[
            table(
                "Mirrored brace coordinates",
                [
                    ("id", "Member"),
                    ("startXmm", "Start X", "mm"),
                    ("startYmm", "Start Y", "mm"),
                    ("endXmm", "End X", "mm"),
                    ("endYmm", "End Y", "mm"),
                ],
                out,
            )
        ],
    )


@feature(
    "planMembersBracing.slendernessLimit",
    "Slenderness Limit",
    part="floorPlan",
    fields=[
        text("braceIds", "Brace member ids", "BR1,BR2"),
        number("effectiveLengthFactor", "Effective length factor", 1, min=0.1),
        number("radiusOfGyrationMm", "Radius of gyration", 40, unit="mm", min=0.1),
        number("maximumSlenderness", "Maximum permitted slenderness", 200, min=1),
    ],
)
def slenderness_limit(ctx: FeatureContext, values: dict) -> dict:
    """Compute brace KL/r and compare with the engineer-entered slenderness limit."""
    rows = selected_members(profile(ctx)[1], values["braceIds"])
    out = []
    for r in rows:
        ratio = (
            values["effectiveLengthFactor"]
            * r.get("lengthM", 0)
            * 1000
            / values["radiusOfGyrationMm"]
        )
        out.append(
            {
                "memberId": r["id"],
                "effectiveLengthM": values["effectiveLengthFactor"] * r.get("lengthM", 0),
                "slenderness": ratio,
                "withinLimit": ratio <= values["maximumSlenderness"],
            }
        )
    return result(
        summary={
            "checkedBraces": len(out),
            "exceedingLimit": sum(not r["withinLimit"] for r in out),
        },
        tables=[
            table(
                "Brace slenderness",
                [
                    ("memberId", "Brace"),
                    ("effectiveLengthM", "Effective length", "m"),
                    ("slenderness", "KL/r"),
                    ("withinLimit", "Within limit"),
                ],
                out,
            )
        ],
        notes=[
            "Limit and radius of gyration are explicit analysis inputs; the result does not select a design rule."
        ],
    )


@feature(
    "planMembersBracing.connectionType",
    "Connection Type",
    part="floorPlan",
    fields=[
        text("braceIds", "Brace member ids", "BR1,BR2"),
        select(
            "connection",
            "Connection",
            [
                ("gusset", "Gusset plate"),
                ("knifePlate", "Knife plate"),
                ("bolted", "Bolted end plate"),
                ("welded", "Welded end plate"),
            ],
        ),
        number("eccentricityMm", "Connection eccentricity", 0, unit="mm", min=0),
    ],
)
def connection_type(ctx: FeatureContext, values: dict) -> dict:
    """Prepare brace-end connection type assignments and estimate the connection eccentric moment arm."""
    rows = selected_members(profile(ctx)[1], values["braceIds"])
    return result(
        summary={
            "braceCount": len(rows),
            "connection": values["connection"],
            "eccentricityMm": values["eccentricityMm"],
        },
        tables=[
            table(
                "Brace connections",
                [
                    ("memberId", "Brace"),
                    ("connection", "Connection type"),
                    ("eccentricityMm", "Eccentricity", "mm"),
                ],
                [
                    {
                        "memberId": r["id"],
                        "connection": values["connection"],
                        "eccentricityMm": values["eccentricityMm"],
                    }
                    for r in rows
                ],
            )
        ],
    )


@feature(
    "planMembersBracing.tensionOnly",
    "Tension Only",
    part="floorPlan",
    fields=[
        text("braceIds", "Brace member ids", "BR1,BR2"),
        number("tensionDemandKn", "Tension demand", 100, unit="kN", min=0),
        number("grossAreaMm2", "Gross area", 2500, unit="mm²", min=1),
        number("netAreaMm2", "Net area", 2000, unit="mm²", min=1),
        number("yieldStrengthMpa", "Yield stress", 355, unit="MPa", min=1),
    ],
)
def tension_only(ctx: FeatureContext, values: dict) -> dict:
    """Calculate gross-yield and net-section tension stresses for tension-only braces."""
    rows = selected_members(profile(ctx)[1], values["braceIds"])
    gross = values["tensionDemandKn"] * 1000 / values["grossAreaMm2"]
    net = values["tensionDemandKn"] * 1000 / values["netAreaMm2"]
    return result(
        summary={
            "braceCount": len(rows),
            "grossStressMpa": gross,
            "netStressMpa": net,
            "yieldStressMpa": values["yieldStrengthMpa"],
            "netStressToYieldRatio": net / values["yieldStrengthMpa"],
        },
        notes=[
            "Elastic tensile stresses are compared with the entered material yield stress; member resistance factors, holes and connection limit states require separate checks."
        ],
    )


@feature(
    "planMembersBracing.bracingChecks",
    "Bracing Checks",
    part="floorPlan",
    fields=[
        text(
            "braceDataJson",
            "Brace check rows JSON",
            '[{"id":"BR1","demandKn":100,"capacityKn":150}]',
        )
    ],
)
def bracing_checks(ctx: FeatureContext, values: dict) -> dict:
    """Check each supplied brace demand against its provided axial capacity."""
    try:
        rows = json.loads(values["braceDataJson"])
    except ValueError as exc:
        raise FeatureInputError("Brace data must be valid JSON.") from exc
    if not isinstance(rows, list):
        raise FeatureInputError("Brace data must be a JSON array.")
    out = []
    for r in rows:
        demand = float(r.get("demandKn", 0))
        capacity = float(r.get("capacityKn", 0))
        if capacity <= 0:
            raise FeatureInputError(f"Brace {r.get('id', '?')} needs a positive capacity.")
        out.append(
            {
                "id": r.get("id", ""),
                "demandKn": demand,
                "capacityKn": capacity,
                "demandCapacityRatio": demand / capacity,
                "withinCapacity": demand <= capacity,
            }
        )
    return result(
        summary={
            "checkedBraces": len(out),
            "overstressed": sum(not r["withinCapacity"] for r in out),
        },
        tables=[
            table(
                "Brace demand and capacity",
                [
                    ("id", "Brace"),
                    ("demandKn", "Demand", "kN"),
                    ("capacityKn", "Capacity", "kN"),
                    ("demandCapacityRatio", "D/C"),
                    ("withinCapacity", "Within capacity"),
                ],
                out,
            )
        ],
    )


@feature(
    "planMembersBracing.linkBeam",
    "Link Beam",
    part="floorPlan",
    fields=[
        number("linkLengthM", "Link length", 1.5, unit="m", min=0.1),
        number("linkShearKn", "Link shear", 300, unit="kN", min=0),
        number("linkMomentKnM", "Link moment", 100, unit="kN·m", min=0),
    ],
)
def link_beam(ctx: FeatureContext, values: dict) -> dict:
    """Calculate normalized link demand and characteristic shear-to-moment balance."""
    shear_moment_length = values["linkShearKn"] * values["linkLengthM"]
    return result(
        summary={
            "linkLengthM": values["linkLengthM"],
            "shearKn": values["linkShearKn"],
            "momentKnM": values["linkMomentKnM"],
            "shearMomentRatio": shear_moment_length / values["linkMomentKnM"]
            if values["linkMomentKnM"]
            else None,
            "shearMomentTransitionLengthM": values["linkMomentKnM"] / values["linkShearKn"]
            if values["linkShearKn"]
            else None,
        }
    )


@feature(
    "planMembersBracing.linkStiffeners",
    "Link Stiffeners",
    part="floorPlan",
    fields=[
        number("linkLengthMm", "Link length", 1500, unit="mm", min=1),
        number("stiffenerSpacingMm", "Stiffener spacing", 300, unit="mm", min=1),
        number("endDistanceMm", "End distance", 100, unit="mm", min=0),
    ],
)
def link_stiffeners(ctx: FeatureContext, values: dict) -> dict:
    """Lay out equally spaced web-stiffener pairs within an eccentric brace link."""
    usable = values["linkLengthMm"] - 2 * values["endDistanceMm"]
    if usable < 0:
        raise FeatureInputError("End distances exceed link length.")
    count = max(0, math.floor(usable / values["stiffenerSpacingMm"]))
    rows = [
        {"pair": i + 1, "stationMm": values["endDistanceMm"] + (i + 1) * usable / (count + 1)}
        for i in range(count)
    ]
    return result(
        summary={
            "stiffenerPairs": count,
            "usableLengthMm": usable,
            "actualSpacingMm": usable / (count + 1) if count >= 0 else None,
        },
        tables=[
            table(
                "Link stiffener stations",
                [("pair", "Pair"), ("stationMm", "Station from end", "mm")],
                rows,
            )
        ],
    )


@feature(
    "planMembersBracing.rotationPlastic",
    "Rotation Plastic",
    part="floorPlan",
    fields=[
        number("linkLengthM", "Link length", 1.5, unit="m", min=0.1),
        number("plasticRotationRad", "Plastic rotation demand", 0.02, unit="rad", min=0),
        number("rotationCapacityRad", "Rotation capacity input", 0.08, unit="rad", min=0.001),
    ],
)
def rotation_plastic(ctx: FeatureContext, values: dict) -> dict:
    """Compare link plastic rotation demand with an entered rotation capacity."""
    ratio = values["plasticRotationRad"] / values["rotationCapacityRad"]
    return result(
        summary={
            "linkLengthM": values["linkLengthM"],
            "plasticRotationRad": values["plasticRotationRad"],
            "capacityRad": values["rotationCapacityRad"],
            "demandCapacityRatio": ratio,
            "withinCapacity": ratio <= 1,
        }
    )


@feature(
    "planMembersBracing.outriggerTruss",
    "Outrigger Truss",
    part="floorPlan",
    fields=[
        number("coreToPerimeterM", "Core-to-perimeter distance", 15, unit="m", min=0.1),
        number("trussDepthM", "Truss depth", 3, unit="m", min=0.1),
        number("storeyHeightM", "Storey height", 3, unit="m", min=0.1),
    ],
)
def outrigger_truss(ctx: FeatureContext, values: dict) -> dict:
    """Calculate diagonal lengths and slopes of a core-to-perimeter outrigger truss panel."""
    geom = _bay(values["coreToPerimeterM"], values["trussDepthM"])
    return result(
        summary={
            "coreToPerimeterM": values["coreToPerimeterM"],
            "trussDepthM": values["trussDepthM"],
            "diagonalLengthM": geom["diagonalLengthM"],
            "diagonalAngleDeg": geom["angleDeg"],
            "storeyHeightM": values["storeyHeightM"],
        }
    )


@feature(
    "planMembersBracing.beltTruss",
    "Belt Truss",
    part="floorPlan",
    fields=[
        number("perimeterWidthM", "Building perimeter width", 30, unit="m", min=0.1),
        number("perimeterDepthM", "Building perimeter depth", 20, unit="m", min=0.1),
        number("beltDepthM", "Belt truss depth", 3, unit="m", min=0.1),
    ],
)
def belt_truss(ctx: FeatureContext, values: dict) -> dict:
    """Estimate belt-truss perimeter length and four corner diagonal lengths."""
    perimeter = 2 * (values["perimeterWidthM"] + values["perimeterDepthM"])
    diagonal = math.hypot(values["perimeterDepthM"], values["beltDepthM"])
    return result(
        summary={
            "perimeterChordLengthM": perimeter,
            "cornerDiagonalLengthM": diagonal,
            "beltDepthM": values["beltDepthM"],
            "totalCornerDiagonalLengthM": 4 * diagonal,
        }
    )


@feature(
    "planMembersBracing.outriggerLocation",
    "Outrigger Location",
    part="floorPlan",
    fields=[
        number("buildingHeightM", "Building height", 60, unit="m", min=1),
        text("candidateHeightsM", "Candidate storey elevations", "15,30,45"),
        number("targetRatio", "Preferred height ratio", 0.5, min=0, max=1),
    ],
)
def outrigger_location(ctx: FeatureContext, values: dict) -> dict:
    """Rank candidate outrigger levels by distance from a target fraction of building height."""
    try:
        heights = [float(x.strip()) for x in values["candidateHeightsM"].split(",") if x.strip()]
    except ValueError as exc:
        raise FeatureInputError("Candidate heights must be comma-separated metres.") from exc
    if any(h < 0 or h > values["buildingHeightM"] for h in heights):
        raise FeatureInputError("Candidate heights must fall between base and roof.")
    target = values["targetRatio"] * values["buildingHeightM"]
    rows = sorted(
        (
            {
                "heightM": h,
                "heightRatio": h / values["buildingHeightM"],
                "distanceFromTargetM": abs(h - target),
            }
            for h in heights
        ),
        key=lambda r: r["distanceFromTargetM"],
    )
    return result(
        summary={
            "candidateLevels": len(rows),
            "preferredHeightM": target,
            "bestCandidateM": rows[0]["heightM"] if rows else None,
        },
        tables=[
            table(
                "Outrigger level candidates",
                [
                    ("heightM", "Level", "m"),
                    ("heightRatio", "Height ratio"),
                    ("distanceFromTargetM", "Distance", "m"),
                ],
                rows,
            )
        ],
    )


@feature(
    "planMembersBracing.cablePrestress",
    "Cable Prestress",
    part="floorPlan",
    fields=[
        number("prestressKn", "Initial cable tension", 100, unit="kN", min=0),
        number("areaMm2", "Cable steel area", 500, unit="mm²", min=1),
        number("elasticModulusMpa", "Elastic modulus", 200000, unit="MPa", min=1),
        number("lengthM", "Unstressed length", 10, unit="m", min=0.1),
    ],
)
def cable_prestress(ctx: FeatureContext, values: dict) -> dict:
    """Calculate cable prestress stress and elastic strain from entered section and material data."""
    stress = values["prestressKn"] * 1000 / values["areaMm2"]
    strain = stress / values["elasticModulusMpa"]
    return result(
        summary={
            "prestressKn": values["prestressKn"],
            "stressMpa": stress,
            "elasticStrain": strain,
            "elasticExtensionMm": strain * values["lengthM"] * 1000,
        }
    )


@feature(
    "planMembersBracing.cableSag",
    "Cable Sag",
    part="floorPlan",
    fields=[
        number("spanM", "Horizontal span", 20, unit="m", min=0.1),
        number("sagLoadKnPerM", "Cable self-weight", 0.5, unit="kN/m", min=0),
        number("horizontalTensionKn", "Horizontal tension", 100, unit="kN", min=0.01),
    ],
)
def cable_sag(ctx: FeatureContext, values: dict) -> dict:
    """Estimate parabolic cable sag and arc length under uniform self-weight."""
    sag = values["sagLoadKnPerM"] * values["spanM"] ** 2 / (8 * values["horizontalTensionKn"])
    arc = values["spanM"] + 8 * sag**2 / (3 * values["spanM"])
    return result(
        summary={
            "midspanSagM": sag,
            "spanM": values["spanM"],
            "approximateCableLengthM": arc,
            "sagToSpanRatio": sag / values["spanM"],
        },
        notes=[
            "Small-sag parabolic approximation under uniform vertical load; cable stiffness and geometric nonlinearity are not iterated."
        ],
    )


@feature(
    "planMembersBracing.turnbuckle",
    "Turnbuckle",
    part="floorPlan",
    fields=[
        number("adjustmentRangeMm", "Turnbuckle adjustment range", 50, unit="mm", min=0),
        number("threadPitchMm", "Thread pitch", 2, unit="mm", min=0.1),
        number("requiredAdjustmentMm", "Required length adjustment", 20, unit="mm", min=0),
    ],
)
def turnbuckle(ctx: FeatureContext, values: dict) -> dict:
    """Calculate turnbuckle turns required for a length adjustment and check available range."""
    turns = values["requiredAdjustmentMm"] / values["threadPitchMm"]
    return result(
        summary={
            "requiredTurns": turns,
            "requiredAdjustmentMm": values["requiredAdjustmentMm"],
            "availableRangeMm": values["adjustmentRangeMm"],
            "withinRange": values["requiredAdjustmentMm"] <= values["adjustmentRangeMm"],
        }
    )


@feature(
    "planMembersBracing.bracingSummary",
    "Bracing Summary",
    part="floorPlan",
    fields=[
        text(
            "bracesJson",
            "Brace records JSON",
            '[{"id":"BR1","storey":"L1","lengthM":6.7,"type":"X"}]',
        )
    ],
)
def bracing_summary(ctx: FeatureContext, values: dict) -> dict:
    """Summarise supplied brace geometry by storey and system type."""
    try:
        rows = json.loads(values["bracesJson"])
    except ValueError as exc:
        raise FeatureInputError("Brace records must be valid JSON.") from exc
    if not isinstance(rows, list):
        raise FeatureInputError("Brace records must be a JSON array.")
    groups = {}
    for r in rows:
        key = (r.get("storey", ""), r.get("type", ""))
        groups[key] = groups.get(key, 0) + 1
    return result(
        summary={
            "braceCount": len(rows),
            "totalBraceLengthM": sum(float(r.get("lengthM", 0)) for r in rows),
            "groupCount": len(groups),
        },
        tables=[
            table(
                "Bracing by storey and type",
                [("storey", "Storey"), ("type", "System"), ("count", "Count")],
                [{"storey": k[0], "type": k[1], "count": v} for k, v in sorted(groups.items())],
            )
        ],
    )

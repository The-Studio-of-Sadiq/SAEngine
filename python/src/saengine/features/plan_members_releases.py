"""End Releases ribbon: member-end constraints, springs, offsets and clear spans."""

from __future__ import annotations

import functools
import itertools
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

#: #303: the releases and springs the analysis uses live in one place (no duplication): the
#: building model's additions, edited in 8 FEM (Analyze > End Releases..., Point Spring...) or
#: 6 BIM's Additions. These buttons only work values out; they say where to apply them.
_APPLIED_IN_FEM = (
    "To apply end releases or springs in the analysis, pick the member or joint in 8 FEM and "
    "use Analyze > End Releases... or Point Spring... (stored in 6 BIM, Additions)."
)


def _points_to_fem(function):
    """Adds :data:`_APPLIED_IN_FEM` to the result's notes."""

    @functools.wraps(function)
    def wrapped(ctx: FeatureContext, values: dict) -> dict:
        out = function(ctx, values)
        out["notes"] = [*out.get("notes", []), _APPLIED_IN_FEM]
        return out

    return wrapped


def _selected(ctx: FeatureContext, ids: str) -> list[dict]:
    return selected_members(profile(ctx)[1], ids)


@feature(
    "planMembersReleases.releaseStart",
    "Release Start",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1"),
        checkbox("axial", "Release axial force", False),
        checkbox("shear", "Release shear force", False),
        checkbox("moment", "Release bending moment", True),
        checkbox("torsion", "Release torsion", False),
    ],
)
@_points_to_fem
def release_start(ctx: FeatureContext, values: dict) -> dict:
    """Prepare start-end force release assignments for selected members."""
    rows = _selected(ctx, values["memberIds"])
    flags = {k: values[k] for k in ("axial", "shear", "moment", "torsion")}
    return result(
        summary={"members": len(rows), "releasedActions": sum(flags.values()), "end": "start"},
        tables=[
            table(
                "Start release flags",
                [
                    ("memberId", "Member"),
                    ("axialReleased", "Axial"),
                    ("shearReleased", "Shear"),
                    ("momentReleased", "Moment"),
                    ("torsionReleased", "Torsion"),
                ],
                [
                    {
                        "memberId": r["id"],
                        "axialReleased": flags["axial"],
                        "shearReleased": flags["shear"],
                        "momentReleased": flags["moment"],
                        "torsionReleased": flags["torsion"],
                    }
                    for r in rows
                ],
            )
        ],
    )


@feature(
    "planMembersReleases.releaseEnd",
    "Release End",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1"),
        checkbox("axial", "Release axial force", False),
        checkbox("shear", "Release shear force", False),
        checkbox("moment", "Release bending moment", True),
        checkbox("torsion", "Release torsion", False),
    ],
)
@_points_to_fem
def release_end(ctx: FeatureContext, values: dict) -> dict:
    """Prepare end-end force release assignments for selected members."""
    rows = _selected(ctx, values["memberIds"])
    flags = {k: values[k] for k in ("axial", "shear", "moment", "torsion")}
    return result(
        summary={"members": len(rows), "releasedActions": sum(flags.values()), "end": "end"},
        tables=[
            table(
                "End release flags",
                [
                    ("memberId", "Member"),
                    ("axialReleased", "Axial"),
                    ("shearReleased", "Shear"),
                    ("momentReleased", "Moment"),
                    ("torsionReleased", "Torsion"),
                ],
                [
                    {
                        "memberId": r["id"],
                        "axialReleased": flags["axial"],
                        "shearReleased": flags["shear"],
                        "momentReleased": flags["moment"],
                        "torsionReleased": flags["torsion"],
                    }
                    for r in rows
                ],
            )
        ],
    )


@feature(
    "planMembersReleases.partialFixity",
    "Partial Fixity",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1"),
        number(
            "rotationalStiffnessKnMPerRad", "Rotational stiffness", 10000, unit="kN·m/rad", min=0
        ),
        number(
            "referenceStiffnessKnMPerRad",
            "Reference member stiffness",
            20000,
            unit="kN·m/rad",
            min=0.001,
        ),
    ],
)
@_points_to_fem
def partial_fixity(ctx: FeatureContext, values: dict) -> dict:
    """Calculate a dimensionless end-restraint ratio for each selected member."""
    rows = _selected(ctx, values["memberIds"])
    ratio = values["rotationalStiffnessKnMPerRad"] / values["referenceStiffnessKnMPerRad"]
    return result(
        summary={
            "members": len(rows),
            "fixityRatio": ratio,
            "connectionBehavior": "pinned-like"
            if ratio < 0.1
            else "semi-rigid"
            if ratio < 10
            else "rigid-like",
        }
    )


@feature(
    "planMembersReleases.momentRelease",
    "Moment Release",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1"),
        select("end", "Member end", [("start", "Start"), ("end", "End"), ("both", "Both")]),
        checkbox("releaseMy", "Release major-axis bending", True),
        checkbox("releaseMz", "Release minor-axis bending", False),
    ],
)
@_points_to_fem
def moment_release(ctx: FeatureContext, values: dict) -> dict:
    """Select major and minor-axis moment releases at specified member ends."""
    rows = _selected(ctx, values["memberIds"])
    if not (values["releaseMy"] or values["releaseMz"]):
        raise FeatureInputError("Enable at least one bending release.")
    return result(
        summary={
            "releasedMembers": len(rows),
            "end": values["end"],
            "releasedMomentAxes": sum((values["releaseMy"], values["releaseMz"])),
        },
        tables=[
            table(
                "Moment release schedule",
                [
                    ("memberId", "Member"),
                    ("end", "End"),
                    ("releaseMy", "Release My"),
                    ("releaseMz", "Release Mz"),
                ],
                [
                    {
                        "memberId": r["id"],
                        "end": values["end"],
                        "releaseMy": values["releaseMy"],
                        "releaseMz": values["releaseMz"],
                    }
                    for r in rows
                ],
            )
        ],
    )


@feature(
    "planMembersReleases.pinSupport",
    "Pin Support",
    part="floorPlan",
    fields=[text("supportName", "Support name", "P1"), text("pointMm", "Support point x,y", "0,0")],
    requires_project=False,
)
def pin_support(ctx: FeatureContext, values: dict) -> dict:
    """Define a translationally restrained and rotationally free point support."""
    try:
        x, y = [float(v.strip()) for v in values["pointMm"].split(",")[:2]]
    except ValueError as exc:
        raise FeatureInputError("Support point must be x,y coordinates in millimetres.") from exc
    return result(
        summary={
            "supportName": values["supportName"],
            "xMm": x,
            "yMm": y,
            "translationsRestrained": 3,
            "rotationsRestrained": 0,
        }
    )


@feature(
    "planMembersReleases.fixedSupport",
    "Fixed Support",
    part="floorPlan",
    fields=[text("supportName", "Support name", "F1"), text("pointMm", "Support point x,y", "0,0")],
    requires_project=False,
)
def fixed_support(ctx: FeatureContext, values: dict) -> dict:
    """Define a point support with all three translations and rotations restrained."""
    try:
        x, y = [float(v.strip()) for v in values["pointMm"].split(",")[:2]]
    except ValueError as exc:
        raise FeatureInputError("Support point must be x,y coordinates in millimetres.") from exc
    return result(
        summary={
            "supportName": values["supportName"],
            "xMm": x,
            "yMm": y,
            "translationsRestrained": 3,
            "rotationsRestrained": 3,
        }
    )


@feature(
    "planMembersReleases.rollerSupport",
    "Roller Support",
    part="floorPlan",
    fields=[
        text("supportName", "Support name", "R1"),
        text("pointMm", "Support point x,y", "0,0"),
        select("freeDirection", "Free translation", [("x", "X"), ("y", "Y")]),
    ],
    requires_project=False,
)
def roller_support(ctx: FeatureContext, values: dict) -> dict:
    """Define a roller support with one free in-plane translation and vertical restraint."""
    try:
        x, y = [float(v.strip()) for v in values["pointMm"].split(",")[:2]]
    except ValueError as exc:
        raise FeatureInputError("Support point must be x,y coordinates in millimetres.") from exc
    return result(
        summary={
            "supportName": values["supportName"],
            "xMm": x,
            "yMm": y,
            "freeTranslation": values["freeDirection"],
            "verticalTranslationRestrained": True,
        }
    )


@feature(
    "planMembersReleases.springSupport",
    "Spring Support",
    part="floorPlan",
    fields=[
        text("supportName", "Support name", "S1"),
        number("verticalStiffnessKnPerM", "Vertical spring stiffness", 10000, unit="kN/m", min=0),
        number("horizontalStiffnessKnPerM", "Horizontal spring stiffness", 0, unit="kN/m", min=0),
    ],
)
@_points_to_fem
def spring_support(ctx: FeatureContext, values: dict) -> dict:
    """Report translational support spring constants and stiffness ratio."""
    ratio = (
        values["horizontalStiffnessKnPerM"] / values["verticalStiffnessKnPerM"]
        if values["verticalStiffnessKnPerM"]
        else None
    )
    return result(
        summary={
            "supportName": values["supportName"],
            "verticalStiffnessKnPerM": values["verticalStiffnessKnPerM"],
            "horizontalStiffnessKnPerM": values["horizontalStiffnessKnPerM"],
            "horizontalToVerticalRatio": ratio,
        }
    )


@feature(
    "planMembersReleases.rigidOffset",
    "Rigid Offset",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1"),
        number("startOffsetMm", "Start rigid offset", 150, unit="mm", min=0),
        number("endOffsetMm", "End rigid offset", 150, unit="mm", min=0),
    ],
)
def rigid_offset(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the remaining flexible length after rigid offsets at both member ends."""
    rows = _selected(ctx, values["memberIds"])
    out = []
    for r in rows:
        clear = r.get("lengthM", 0) - (values["startOffsetMm"] + values["endOffsetMm"]) / 1000
        if clear <= 0:
            raise FeatureInputError(f"Rigid offsets consume the full length of member {r['id']}.")
        out.append(
            {"memberId": r["id"], "grossLengthM": r.get("lengthM", 0), "flexibleLengthM": clear}
        )
    return result(
        summary={"members": len(out), "flexibleLengthM": sum(r["flexibleLengthM"] for r in out)},
        tables=[
            table(
                "Rigid offset lengths",
                [
                    ("memberId", "Member"),
                    ("grossLengthM", "Gross length", "m"),
                    ("flexibleLengthM", "Flexible length", "m"),
                ],
                out,
            )
        ],
    )


@feature(
    "planMembersReleases.endOffset",
    "End Offset",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1"),
        number("offsetMm", "End offset", 100, unit="mm"),
        select("end", "Member end", [("start", "Start"), ("end", "End")]),
    ],
)
def end_offset(ctx: FeatureContext, values: dict) -> dict:
    """Assign an explicit one-end offset to selected members and check it against member length."""
    rows = _selected(ctx, values["memberIds"])
    out = []
    for r in rows:
        length = r.get("lengthM", 0) * 1000
        if values["offsetMm"] >= length > 0:
            raise FeatureInputError(f"End offset exceeds member {r['id']} length.")
        out.append(
            {
                "memberId": r["id"],
                "end": values["end"],
                "offsetMm": values["offsetMm"],
                "remainingLengthMm": length - values["offsetMm"],
            }
        )
    return result(
        summary={"offsetMembers": len(out)},
        tables=[
            table(
                "Member end offsets",
                [
                    ("memberId", "Member"),
                    ("end", "End"),
                    ("offsetMm", "Offset", "mm"),
                    ("remainingLengthMm", "Remaining length", "mm"),
                ],
                out,
            )
        ],
    )


@feature(
    "planMembersReleases.physicalGap",
    "Physical Gap",
    part="floorPlan",
    fields=[
        text("memberId", "Member id", "B1"),
        number("gapMm", "Physical gap", 10, unit="mm", min=0),
        number("thermalMovementMm", "Expected thermal movement", 5, unit="mm", min=0),
    ],
)
def physical_gap(ctx: FeatureContext, values: dict) -> dict:
    """Compare a physical separation gap with an entered movement demand."""
    rows = _selected(ctx, values["memberId"])
    return result(
        summary={
            "memberId": rows[0]["id"],
            "gapMm": values["gapMm"],
            "movementMm": values["thermalMovementMm"],
            "clearanceRemainingMm": values["gapMm"] - values["thermalMovementMm"],
            "contactExpected": values["thermalMovementMm"] >= values["gapMm"],
        }
    )


@feature(
    "planMembersReleases.applyOffsets",
    "Apply Offsets",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1,B2"),
        number("supportWidthMm", "Support width", 300, unit="mm", min=1),
        number("supportDepthMm", "Support depth", 500, unit="mm", min=1),
        number("offsetFraction", "Offset fraction of support size", 0.5, min=0, max=1),
    ],
)
def apply_offsets(ctx: FeatureContext, values: dict) -> dict:
    """Calculate analytical end offsets from support dimensions and an explicit fraction."""
    rows = _selected(ctx, values["memberIds"])
    end = values["offsetFraction"] * values["supportDepthMm"]
    return result(
        summary={
            "offsetMembers": len(rows),
            "offsetMm": end,
            "supportWidthMm": values["supportWidthMm"],
            "remainingLengthM": sum(r.get("lengthM", 0) for r in rows) - len(rows) * end / 1000,
        }
    )


@feature(
    "planMembersReleases.translationalSpring",
    "Translational Spring",
    part="floorPlan",
    fields=[
        text("jointName", "Joint name", "J1"),
        number("kxKnPerM", "X spring stiffness", 10000, unit="kN/m", min=0),
        number("kyKnPerM", "Y spring stiffness", 10000, unit="kN/m", min=0),
        number("kzKnPerM", "Z spring stiffness", 10000, unit="kN/m", min=0),
    ],
)
@_points_to_fem
def translational_spring(ctx: FeatureContext, values: dict) -> dict:
    """Prepare directional translational spring constants and identify restrained directions."""
    ks = [values[k] for k in ("kxKnPerM", "kyKnPerM", "kzKnPerM")]
    return result(
        summary={
            "jointName": values["jointName"],
            "nonzeroSpringDirections": sum(k > 0 for k in ks),
            "resultantStiffnessKnPerM": math.sqrt(sum(k * k for k in ks)),
        },
        tables=[
            table(
                "Translational spring constants",
                [("direction", "Direction"), ("stiffnessKnPerM", "Stiffness", "kN/m")],
                [{"direction": axis, "stiffnessKnPerM": k} for axis, k in zip(("X", "Y", "Z"), ks)],
            )
        ],
    )


@feature(
    "planMembersReleases.rotationalSpring",
    "Rotational Spring",
    part="floorPlan",
    fields=[
        text("jointName", "Joint name", "J1"),
        number("krxKnMPerRad", "X rotation stiffness", 1000, unit="kN·m/rad", min=0),
        number("kryKnMPerRad", "Y rotation stiffness", 1000, unit="kN·m/rad", min=0),
        number("krzKnMPerRad", "Z rotation stiffness", 1000, unit="kN·m/rad", min=0),
    ],
)
@_points_to_fem
def rotational_spring(ctx: FeatureContext, values: dict) -> dict:
    """Prepare directional rotational spring constants at a structural joint."""
    ks = [values[k] for k in ("krxKnMPerRad", "kryKnMPerRad", "krzKnMPerRad")]
    return result(
        summary={
            "jointName": values["jointName"],
            "activeRotationalDirections": sum(k > 0 for k in ks),
        },
        tables=[
            table(
                "Rotational stiffness",
                [("axis", "Rotation axis"), ("stiffnessKnMPerRad", "Stiffness", "kN·m/rad")],
                [
                    {"axis": axis, "stiffnessKnMPerRad": k}
                    for axis, k in zip(("RX", "RY", "RZ"), ks)
                ],
            )
        ],
    )


@feature(
    "planMembersReleases.nonlinearSpring",
    "Nonlinear Spring",
    part="floorPlan",
    fields=[
        text("curvePoints", "Displacement mm, force kN; semicolon separated", "0,0;5,50;10,80"),
        number("queryDisplacementMm", "Evaluate at displacement", 7, unit="mm"),
    ],
)
def nonlinear_spring(ctx: FeatureContext, values: dict) -> dict:
    """Interpolate force on a monotonic piecewise-linear spring force-displacement curve."""
    points = []
    try:
        for item in values["curvePoints"].split(";"):
            if item.strip():
                d, f = [float(x.strip()) for x in item.split(",")[:2]]
                points.append((d, f))
    except ValueError as exc:
        raise FeatureInputError(
            "Curve points must be displacement,force pairs separated by semicolons."
        ) from exc
    points.sort()
    if len(points) < 2 or any(points[i][0] >= points[i + 1][0] for i in range(len(points) - 1)):
        raise FeatureInputError("Enter at least two strictly increasing displacement points.")
    q = values["queryDisplacementMm"]
    if q < points[0][0] or q > points[-1][0]:
        raise FeatureInputError("Query displacement lies outside the entered spring curve.")
    force = next(
        (
            f0 + (q - d0) * (f1 - f0) / (d1 - d0)
            for (d0, f0), (d1, f1) in itertools.pairwise(points)
            if d0 <= q <= d1
        ),
        points[-1][1],
    )
    return result(
        summary={
            "queryDisplacementMm": q,
            "interpolatedForceKn": force,
            "secantStiffnessKnPerMm": force / q if q else None,
        },
        tables=[
            table(
                "Spring curve",
                [("displacementMm", "Displacement", "mm"), ("forceKn", "Force", "kN")],
                [{"displacementMm": d, "forceKn": f} for d, f in points],
            )
        ],
    )


@feature(
    "planMembersReleases.shearConnection",
    "Shear Connection",
    part="floorPlan",
    fields=[
        text("memberIds", "Beam ids", "B1,B2"),
        number("shearKn", "Design shear input", 100, unit="kN", min=0),
        number("boltCount", "Bolt count", 4, min=1),
        number("boltShearCapacityKn", "Capacity per bolt", 25, unit="kN", min=0.01),
    ],
)
def shear_connection(ctx: FeatureContext, values: dict) -> dict:
    """Check the entered shear force against the sum of supplied per-bolt shear capacities."""
    rows = _selected(ctx, values["memberIds"])
    capacity = values["boltCount"] * values["boltShearCapacityKn"]
    return result(
        summary={
            "connectedMembers": len(rows),
            "inputShearKn": values["shearKn"],
            "nominalBoltCapacityKn": capacity,
            "demandCapacityRatio": values["shearKn"] / capacity,
            "passesEnteredCapacity": values["shearKn"] <= capacity,
        },
        notes=[
            "Bolt capacity is an engineer-entered value; bolt group eccentricity, bearing, block shear and code factors are not included."
        ],
    )


@feature(
    "planMembersReleases.momentConnection",
    "Moment Connection",
    part="floorPlan",
    fields=[
        text("memberIds", "Beam ids", "B1"),
        number("momentKnM", "Connection moment input", 50, unit="kN·m"),
        number(
            "connectionStiffnessKnMPerRad", "Rotational stiffness", 50000, unit="kN·m/rad", min=0
        ),
    ],
)
def moment_connection(ctx: FeatureContext, values: dict) -> dict:
    """Calculate connection rotation from moment and a supplied rotational stiffness."""
    rows = _selected(ctx, values["memberIds"])
    if values["connectionStiffnessKnMPerRad"] <= 0:
        raise FeatureInputError("A moment connection needs positive rotational stiffness.")
    rotation = values["momentKnM"] / values["connectionStiffnessKnMPerRad"]
    return result(
        summary={
            "connectedMembers": len(rows),
            "rotationRad": rotation,
            "rotationDeg": math.degrees(rotation),
            "stiffnessKnMPerRad": values["connectionStiffnessKnMPerRad"],
        }
    )


@feature(
    "planMembersReleases.semiRigidJoint",
    "Semi Rigid Joint",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1"),
        text(
            "curvePoints", "Rotation rad,moment kN·m; semicolon separated", "0,0;0.01,100;0.02,150"
        ),
    ],
)
def semi_rigid_joint(ctx: FeatureContext, values: dict) -> dict:
    """Derive initial and secant rotational stiffness from a supplied moment-rotation curve."""
    rows = _selected(ctx, values["memberIds"])
    points = []
    try:
        for item in values["curvePoints"].split(";"):
            if item.strip():
                t, m = [float(x.strip()) for x in item.split(",")[:2]]
                points.append((t, m))
    except ValueError as exc:
        raise FeatureInputError(
            "Curve data must be rotation,moment pairs separated by semicolons."
        ) from exc
    points.sort()
    if len(points) < 2 or points[1][0] <= points[0][0]:
        raise FeatureInputError("At least two increasing rotation points are required.")
    initial = (points[1][1] - points[0][1]) / (points[1][0] - points[0][0])
    secant = points[-1][1] / points[-1][0] if points[-1][0] else 0
    return result(
        summary={
            "members": len(rows),
            "initialStiffnessKnMPerRad": initial,
            "terminalSecantKnMPerRad": secant,
        },
        tables=[
            table(
                "Moment-rotation points",
                [("rotationRad", "Rotation", "rad"), ("momentKnM", "Moment", "kN·m")],
                [{"rotationRad": t, "momentKnM": m} for t, m in points],
            )
        ],
    )


@feature(
    "planMembersReleases.zoneOffset",
    "Zone Offset",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1"),
        number("supportDepthMm", "Support depth", 500, unit="mm", min=1),
        number("offsetFraction", "Rigid zone fraction", 0.5, min=0, max=1),
    ],
)
def zone_offset(ctx: FeatureContext, values: dict) -> dict:
    """Calculate rigid-zone end offsets from support depth and a selected fraction."""
    rows = _selected(ctx, values["memberIds"])
    each = values["supportDepthMm"] * values["offsetFraction"] / 1000
    output = []
    for r in rows:
        clear = r.get("lengthM", 0) - 2 * each
        if clear < 0:
            raise FeatureInputError(f"Rigid zones exceed member {r['id']} length.")
        output.append({"memberId": r["id"], "zoneEachEndM": each, "clearSpanM": clear})
    return result(
        summary={"zoneOffsetMembers": len(output)},
        tables=[
            table(
                "Rigid zone offsets",
                [
                    ("memberId", "Member"),
                    ("zoneEachEndM", "Each end", "m"),
                    ("clearSpanM", "Clear span", "m"),
                ],
                output,
            )
        ],
    )


@feature(
    "planMembersReleases.eccentricity",
    "Eccentricity",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids", "B1"),
        number("eccentricityXmm", "Eccentricity X", 0, unit="mm"),
        number("eccentricityYmm", "Eccentricity Y", 100, unit="mm"),
        number("axialForceKn", "Axial force", 100, unit="kN"),
    ],
)
def eccentricity(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the additional moment caused by an axial force acting eccentrically."""
    rows = _selected(ctx, values["memberIds"])
    moment = (
        values["axialForceKn"]
        * math.hypot(values["eccentricityXmm"], values["eccentricityYmm"])
        / 1000
    )
    return result(
        summary={
            "affectedMembers": len(rows),
            "eccentricityMm": math.hypot(values["eccentricityXmm"], values["eccentricityYmm"]),
            "secondaryMomentKnM": moment,
        }
    )


@feature(
    "planMembersReleases.clearSpan",
    "Clear Span",
    part="floorPlan",
    fields=[
        text("memberIds", "Beam ids", "B1"),
        number("supportWidthStartMm", "Start support width", 300, unit="mm", min=0),
        number("supportWidthEndMm", "End support width", 300, unit="mm", min=0),
    ],
)
def clear_span(ctx: FeatureContext, values: dict) -> dict:
    """Calculate clear beam length between support faces using half-width offsets."""
    rows = _selected(ctx, values["memberIds"])
    out = []
    for r in rows:
        clear = r["lengthM"] - (values["supportWidthStartMm"] + values["supportWidthEndMm"]) / 2000
        if clear < 0:
            raise FeatureInputError(f"Support face offsets exceed member {r['id']} length.")
        out.append(
            {
                "memberId": r["id"],
                "centerlineSpanM": r["lengthM"],
                "clearSpanM": clear,
                "endFaceOffsetsMm": (values["supportWidthStartMm"] + values["supportWidthEndMm"])
                / 2,
            }
        )
    return result(
        summary={"beamCount": len(out), "totalClearSpanM": sum(r["clearSpanM"] for r in out)},
        tables=[
            table(
                "Beam clear spans",
                [
                    ("memberId", "Beam"),
                    ("centerlineSpanM", "Centerline span", "m"),
                    ("clearSpanM", "Clear span", "m"),
                    ("endFaceOffsetsMm", "Total face offsets", "mm"),
                ],
                out,
            )
        ],
    )


@feature(
    "planMembersReleases.releaseReport",
    "Release Report",
    part="floorPlan",
    fields=[
        text(
            "releaseDataJson",
            "Release data JSON",
            '[{"memberId":"B1","startMoment":true,"endMoment":false}]',
        )
    ],
)
def release_report(ctx: FeatureContext, values: dict) -> dict:
    """Summarise a supplied member release table by end and released action."""
    try:
        rows = json.loads(values["releaseDataJson"])
    except ValueError as exc:
        raise FeatureInputError("Release data must be valid JSON.") from exc
    if not isinstance(rows, list):
        raise FeatureInputError("Release data must be a JSON array.")
    return result(
        summary={
            "reportedMembers": len(rows),
            "startMomentReleases": sum(bool(r.get("startMoment")) for r in rows),
            "endMomentReleases": sum(bool(r.get("endMoment")) for r in rows),
            "shearReleases": sum(bool(r.get("shear")) for r in rows),
        },
        tables=[
            table(
                "Member release summary",
                [
                    ("memberId", "Member"),
                    ("startMoment", "Start moment"),
                    ("endMoment", "End moment"),
                    ("shear", "Shear"),
                ],
                rows,
            )
        ],
    )

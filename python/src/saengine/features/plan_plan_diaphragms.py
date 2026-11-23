"""Diaphragms ribbon: floor-plane lateral load transfer and mesh parameters."""

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
from saengine.features.plan_common import member_rows, plan_data, profile


def _floor(ctx: FeatureContext, story: str) -> tuple[dict, list[dict]]:
    plan = plan_data(ctx)
    if story not in {s["id"] for s in plan["stories"]}:
        raise FeatureInputError("Storey id was not found.")
    return plan, [r for r in member_rows(plan) if r["category"] == "slab" and r["story"] == story]


@feature(
    "planPlanDiaphragms.semiRigid",
    "Semi Rigid",
    part="floorPlan",
    fields=[
        text("storey", "Storey id", "L1"),
        number("meshSizeMm", "Membrane mesh size", 1000, unit="mm", min=1),
        number("elasticModulusMpa", "In-plane modulus", 25000, unit="MPa", min=1),
        number("slabThicknessMm", "Slab thickness", 150, unit="mm", min=1),
        number("poissonRatio", "Poisson ratio", 0.2, min=-0.99, max=0.49),
    ],
)
def semi_rigid(ctx: FeatureContext, values: dict) -> dict:
    """Estimate floor membrane stiffness and mesh element counts for semi-rigid analysis."""
    _, slabs = _floor(ctx, values["storey"])
    area = sum(r["areaM2"] for r in slabs)
    membrane = values["elasticModulusMpa"] * values["slabThicknessMm"]
    return result(
        summary={
            "storey": values["storey"],
            "slabPanels": len(slabs),
            "floorAreaM2": area,
            "membraneAxialStiffnessNPerMm": membrane,
            "meshSizeMm": values["meshSizeMm"],
            "approximateElementCount": math.ceil(area / (values["meshSizeMm"] / 1000) ** 2),
        },
        notes=[
            "Membrane extensional stiffness E·t is reported; bending, openings and cracked properties are not included."
        ],
    )


@feature(
    "planPlanDiaphragms.rigidDiaphragm",
    "Rigid Diaphragm",
    part="floorPlan",
    fields=[
        text("storey", "Storey id", "L1"),
        number("floorShearKn", "Applied floor shear", 500, unit="kN", min=0),
        number("eccentricityMm", "Accidental eccentricity", 0, unit="mm"),
    ],
)
def rigid_diaphragm(ctx: FeatureContext, values: dict) -> dict:
    """Summarise rigid-floor geometry and the torsional moment produced by entered eccentricity."""
    _, slabs = _floor(ctx, values["storey"])
    area = sum(r["areaM2"] for r in slabs)
    return result(
        summary={
            "storey": values["storey"],
            "slabAreaM2": area,
            "panelCount": len(slabs),
            "floorShearKn": values["floorShearKn"],
            "torsionalMomentKnM": values["floorShearKn"] * values["eccentricityMm"] / 1000,
        }
    )


@feature(
    "planPlanDiaphragms.flexibleDiaphragm",
    "Flexible Diaphragm",
    part="floorPlan",
    fields=[
        text("storey", "Storey id", "L1"),
        number(
            "inPlaneShearRigidityKnPerM", "In-plane shear rigidity", 10000, unit="kN/m", min=0.001
        ),
        number("floorShearKn", "Applied floor shear", 500, unit="kN", min=0),
        number("collectorSpacingM", "Collector spacing", 6, unit="m", min=0.1),
    ],
)
def flexible_diaphragm(ctx: FeatureContext, values: dict) -> dict:
    """Estimate diaphragm shear deformation from floor shear, panel spacing and entered rigidity."""
    _, slabs = _floor(ctx, values["storey"])
    deformation = (
        values["floorShearKn"] * values["collectorSpacingM"] / values["inPlaneShearRigidityKnPerM"]
    )
    return result(
        summary={
            "storey": values["storey"],
            "slabPanelCount": len(slabs),
            "shearDeformationM": deformation,
            "shearDeformationMm": deformation * 1000,
            "rigidityKnPerM": values["inPlaneShearRigidityKnPerM"],
        },
        notes=[
            "One-way shear deformation estimate across the collector spacing; distributed diaphragm behaviour needs a model analysis."
        ],
    )


@feature(
    "planPlanDiaphragms.assignDiaphragm",
    "Assign Diaphragm",
    part="floorPlan",
    fields=[
        text("storeys", "Storey ids", "L1,L2,L3"),
        select(
            "behavior",
            "Diaphragm behavior",
            [("rigid", "Rigid"), ("semiRigid", "Semi-rigid"), ("flexible", "Flexible")],
        ),
        text("name", "Diaphragm assignment name", "D1"),
    ],
)
def assign_diaphragm(ctx: FeatureContext, values: dict) -> dict:
    """Validate storey ids and prepare diaphragm behaviour assignments."""
    plan = plan_data(ctx)
    ids = [x.strip() for x in values["storeys"].split(",") if x.strip()]
    known = {s["id"] for s in plan["stories"]}
    if set(ids) - known:
        raise FeatureInputError("One or more target storeys are not defined.")
    return result(
        summary={
            "assignmentName": values["name"],
            "storeysAssigned": len(set(ids)),
            "behavior": values["behavior"],
        },
        tables=[
            table(
                "Diaphragm assignments",
                [("storey", "Storey"), ("diaphragm", "Name"), ("behavior", "Behavior")],
                [
                    {"storey": sid, "diaphragm": values["name"], "behavior": values["behavior"]}
                    for sid in dict.fromkeys(ids)
                ],
            )
        ],
    )


@feature(
    "planPlanDiaphragms.diaphragmOpening",
    "Diaphragm Opening",
    part="floorPlan",
    fields=[
        text("storey", "Storey id", "L1"),
        number("openingWidthMm", "Opening width", 1200, unit="mm", min=1),
        number("openingLengthMm", "Opening length", 1800, unit="mm", min=1),
    ],
)
def diaphragm_opening(ctx: FeatureContext, values: dict) -> dict:
    """Calculate diaphragm net area and gross opening ratio for a floor."""
    _, slabs = _floor(ctx, values["storey"])
    gross = sum(r["areaM2"] for r in slabs)
    opening = values["openingWidthMm"] * values["openingLengthMm"] / 1e6
    if opening > gross:
        raise FeatureInputError("Opening area exceeds the total modelled slab area at this storey.")
    return result(
        summary={
            "grossFloorAreaM2": gross,
            "openingAreaM2": opening,
            "netDiaphragmAreaM2": gross - opening,
            "openingRatio": opening / gross if gross else None,
        }
    )


@feature(
    "planPlanDiaphragms.openingTrim",
    "Opening Trim",
    part="floorPlan",
    fields=[
        number("openingWidthMm", "Opening width", 1200, unit="mm", min=1),
        number("openingLengthMm", "Opening length", 1800, unit="mm", min=1),
        number("trimWidthMm", "Trim width", 200, unit="mm", min=1),
        number("trimThicknessMm", "Trim thickness", 150, unit="mm", min=1),
    ],
)
def opening_trim(ctx: FeatureContext, values: dict) -> dict:
    """Estimate the perimeter trim frame length and concrete volume around a diaphragm opening."""
    p = 2 * (values["openingWidthMm"] + values["openingLengthMm"]) / 1000
    volume = p * values["trimWidthMm"] * values["trimThicknessMm"] / 1e6
    return result(
        summary={
            "openingPerimeterM": p,
            "trimConcreteM3": volume,
            "trimWidthMm": values["trimWidthMm"],
            "trimThicknessMm": values["trimThicknessMm"],
        }
    )


@feature(
    "planPlanDiaphragms.openingBoundary",
    "Opening Boundary",
    part="floorPlan",
    fields=[text("points", "Opening vertices x,y mm", "1000,1000;2200,1000;2200,2800;1000,2800")],
    requires_project=False,
)
def opening_boundary(ctx: FeatureContext, values: dict) -> dict:
    """Compute diaphragm opening polygon area and edge perimeter."""
    pts = []
    try:
        for pair in values["points"].split(";"):
            if pair.strip():
                x, y = [float(v.strip()) for v in pair.split(",")[:2]]
                pts.append((x, y))
    except ValueError as exc:
        raise FeatureInputError(
            "Enter x,y vertex pairs in millimetres separated by semicolons."
        ) from exc
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
        summary={"openingAreaM2": area, "openingPerimeterM": perimeter, "vertexCount": len(pts)}
    )


@feature(
    "planPlanDiaphragms.groupOpenings",
    "Group Openings",
    part="floorPlan",
    fields=[
        text("openingIds", "Opening ids", "O1,O2"),
        text("groupName", "Group name", "D1 openings"),
    ],
    requires_project=False,
)
def group_openings(ctx: FeatureContext, values: dict) -> dict:
    """Create a named diaphragm opening group and preserve its ordered ids."""
    ids = [x.strip() for x in values["openingIds"].split(",") if x.strip()]
    return result(
        summary={"groupName": values["groupName"], "openingCount": len(set(ids))},
        tables=[
            table(
                "Grouped openings",
                [("position", "Order"), ("openingId", "Opening")],
                [
                    {"position": i + 1, "openingId": item}
                    for i, item in enumerate(dict.fromkeys(ids))
                ],
            )
        ],
    )


@feature(
    "planPlanDiaphragms.diaphragmCheck",
    "Diaphragm Check",
    part="floorPlan",
    fields=[
        text("storey", "Storey id", "L1"),
        number("floorShearKn", "Floor shear", 500, unit="kN", min=0),
        number("effectiveDepthM", "Effective diaphragm depth", 20, unit="m", min=0.1),
        number(
            "designShearCapacityKnPerM",
            "Entered diaphragm shear capacity",
            100,
            unit="kN/m",
            min=0.01,
        ),
    ],
)
def diaphragm_check(ctx: FeatureContext, values: dict) -> dict:
    """Compare average in-plane diaphragm shear demand with an entered capacity per unit depth."""
    _, slabs = _floor(ctx, values["storey"])
    demand = values["floorShearKn"] / values["effectiveDepthM"]
    ratio = demand / values["designShearCapacityKnPerM"]
    return result(
        summary={
            "storey": values["storey"],
            "slabAreaM2": sum(r["areaM2"] for r in slabs),
            "averageShearKnPerM": demand,
            "capacityKnPerM": values["designShearCapacityKnPerM"],
            "demandCapacityRatio": ratio,
            "withinEnteredCapacity": ratio <= 1,
        },
        notes=[
            "Uniform average in-plane shear flow; collector, chord, opening and connection forces are not included."
        ],
    )


@feature(
    "planPlanDiaphragms.torsionCheck",
    "Torsion Check",
    part="floorPlan",
    fields=[
        number("floorShearKn", "Floor shear", 500, unit="kN", min=0),
        number("massCenterXM", "Mass centre X", 10, unit="m"),
        number("stiffnessCenterXM", "Stiffness centre X", 9, unit="m"),
        number("massCenterYM", "Mass centre Y", 10, unit="m"),
        number("stiffnessCenterYM", "Stiffness centre Y", 11, unit="m"),
    ],
)
def torsion_check(ctx: FeatureContext, values: dict) -> dict:
    """Calculate plan eccentricity between mass and stiffness centres and its torsional moment."""
    dx = values["massCenterXM"] - values["stiffnessCenterXM"]
    dy = values["massCenterYM"] - values["stiffnessCenterYM"]
    eccentricity = math.hypot(dx, dy)
    return result(
        summary={
            "eccentricityM": eccentricity,
            "eccentricityXM": dx,
            "eccentricityYM": dy,
            "torsionalMomentKnM": values["floorShearKn"] * eccentricity,
        }
    )


@feature(
    "planPlanDiaphragms.loadTransfer",
    "Load Transfer",
    part="floorPlan",
    fields=[
        number("floorShearKn", "Floor shear", 500, unit="kN", min=0),
        text(
            "collectorCapacities",
            "Collector ids and stiffness shares id,share; semicolon separated",
            "B1,0.6;B2,0.4",
        ),
    ],
    requires_project=False,
)
def load_transfer(ctx: FeatureContext, values: dict) -> dict:
    """Distribute floor shear to collectors in proportion to explicit stiffness shares."""
    collectors = []
    try:
        for rec in values["collectorCapacities"].split(";"):
            if rec.strip():
                cid, share = [x.strip() for x in rec.split(",")[:2]]
                collectors.append({"id": cid, "share": float(share)})
    except ValueError as exc:
        raise FeatureInputError("Collector records must be id,share pairs.") from exc
    total = sum(r["share"] for r in collectors)
    if total <= 0 or any(r["share"] < 0 for r in collectors):
        raise FeatureInputError("Collector shares must be nonnegative with a positive total.")
    rows = [
        {
            "collector": r["id"],
            "normalizedShare": r["share"] / total,
            "shearKn": values["floorShearKn"] * r["share"] / total,
        }
        for r in collectors
    ]
    return result(
        summary={"collectors": len(rows), "transferredShearKn": sum(r["shearKn"] for r in rows)},
        tables=[
            table(
                "Collector shear distribution",
                [
                    ("collector", "Collector"),
                    ("normalizedShare", "Share"),
                    ("shearKn", "Shear", "kN"),
                ],
                rows,
            )
        ],
    )


@feature(
    "planPlanDiaphragms.diaphragmReport",
    "Diaphragm Report",
    part="floorPlan",
    fields=[
        text("storey", "Storey id", "L1"),
        number("floorShearKn", "Floor shear", 500, unit="kN", min=0),
        number("floorMassKg", "Floor mass", 150000, unit="kg", min=0),
    ],
)
def diaphragm_report(ctx: FeatureContext, values: dict) -> dict:
    """Report floor area, floor shear and mass for one diaphragm level."""
    _, slabs = _floor(ctx, values["storey"])
    area = sum(r["areaM2"] for r in slabs)
    return result(
        summary={
            "storey": values["storey"],
            "panelCount": len(slabs),
            "floorAreaM2": area,
            "floorShearKn": values["floorShearKn"],
            "floorMassKg": values["floorMassKg"],
            "averageShearKpa": values["floorShearKn"] / area if area else None,
        }
    )


@feature(
    "planPlanDiaphragms.collectorBeam",
    "Collector Beam",
    part="floorPlan",
    fields=[
        text("beamIds", "Collector beam ids", "B1,B2"),
        number("floorShearKn", "Transferred floor shear", 500, unit="kN", min=0),
        number("collectorCount", "Parallel collectors", 2, min=1),
    ],
)
def collector_beam(ctx: FeatureContext, values: dict) -> dict:
    """Assign equal diaphragm shear transfer to selected collector beams."""
    rows = profile(ctx)[1]
    ids = {x.strip() for x in values["beamIds"].split(",") if x.strip()}
    beams = [r for r in rows if r["id"] in ids and r["category"] == "beam"]
    if len(beams) != len(ids):
        raise FeatureInputError("Each collector id must identify a current beam.")
    force = values["floorShearKn"] / values["collectorCount"]
    return result(
        summary={
            "collectorCount": len(beams),
            "assumedLoadShareCount": int(values["collectorCount"]),
            "shearPerShareKn": force,
        },
        tables=[
            table(
                "Collector members",
                [
                    ("beamId", "Beam"),
                    ("spanM", "Span", "m"),
                    ("assignedShearKn", "Shear per collector", "kN"),
                ],
                [
                    {"beamId": b["id"], "spanM": b["lengthM"], "assignedShearKn": force}
                    for b in beams
                ],
            )
        ],
        notes=[
            "Equal load sharing is used; stiffness-based distribution needs diaphragm and collector analysis."
        ],
    )


@feature(
    "planPlanDiaphragms.dragForce",
    "Drag Force",
    part="floorPlan",
    fields=[
        number("storeyShearKn", "Storey shear", 500, unit="kN", min=0),
        number("tributaryFraction", "Collector tributary fraction", 0.25, min=0, max=1),
        number("collectorCount", "Collectors sharing force", 2, min=1),
    ],
)
def drag_force(ctx: FeatureContext, values: dict) -> dict:
    """Calculate total drag force for a collector tributary region and force per collector."""
    total = values["storeyShearKn"] * values["tributaryFraction"]
    return result(
        summary={
            "dragForceKn": total,
            "collectors": int(values["collectorCount"]),
            "forcePerCollectorKn": total / values["collectorCount"],
            "tributaryFraction": values["tributaryFraction"],
        }
    )


@feature(
    "planPlanDiaphragms.spliceDetail",
    "Splice Detail",
    part="floorPlan",
    fields=[
        number("collectorTensionKn", "Collector tension", 200, unit="kN", min=0),
        number("spliceCapacityPerBoltKn", "Bolt tension capacity", 40, unit="kN", min=0.01),
        number("boltCount", "Bolt count", 6, min=1),
        number("eccentricityMm", "Splice eccentricity", 0, unit="mm", min=0),
    ],
)
def splice_detail(ctx: FeatureContext, values: dict) -> dict:
    """Check collector splice tension against total supplied bolt capacity and report eccentricity moment."""
    capacity = values["boltCount"] * values["spliceCapacityPerBoltKn"]
    return result(
        summary={
            "collectorTensionKn": values["collectorTensionKn"],
            "nominalBoltCapacityKn": capacity,
            "demandCapacityRatio": values["collectorTensionKn"] / capacity,
            "eccentricityMomentKnM": values["collectorTensionKn"] * values["eccentricityMm"] / 1000,
            "withinEnteredCapacity": values["collectorTensionKn"] <= capacity,
        },
        notes=[
            "Bolt capacity is a supplied nominal value; connection limit states and design factors are not applied."
        ],
    )


@feature(
    "planPlanDiaphragms.diaphragmMesh",
    "Diaphragm Mesh",
    part="floorPlan",
    fields=[
        text("storey", "Storey id", "L1"),
        number("targetElementSizeM", "Target element size", 1, unit="m", min=0.01),
    ],
)
def diaphragm_mesh(ctx: FeatureContext, values: dict) -> dict:
    """Estimate square shell element count from the floor slab area and target edge length."""
    _, slabs = _floor(ctx, values["storey"])
    area = sum(r["areaM2"] for r in slabs)
    count = math.ceil(area / values["targetElementSizeM"] ** 2)
    return result(
        summary={
            "storey": values["storey"],
            "floorAreaM2": area,
            "targetElementSizeM": values["targetElementSizeM"],
            "estimatedElements": count,
        }
    )


@feature(
    "planPlanDiaphragms.rigidLink",
    "Rigid Link",
    part="floorPlan",
    fields=[
        text("masterNode", "Master node label", "M1"),
        text("slaveNodes", "Slave node labels", "N1,N2,N3"),
        select(
            "constraintPlane",
            "Constraint plane",
            [("xy", "In-plane XY"), ("xyz", "All translations")],
        ),
    ],
    requires_project=False,
)
def rigid_link(ctx: FeatureContext, values: dict) -> dict:
    """Define rigid master-slave kinematic links in a selected translation plane."""
    slaves = [x.strip() for x in values["slaveNodes"].split(",") if x.strip()]
    if values["masterNode"] in slaves:
        raise FeatureInputError("The master node cannot also be a slave node.")
    return result(
        summary={
            "masterNode": values["masterNode"],
            "slaveCount": len(set(slaves)),
            "restrainedPlane": values["constraintPlane"],
        },
        tables=[
            table(
                "Rigid-link constraints",
                [("master", "Master"), ("slave", "Slave"), ("plane", "Constraint plane")],
                [
                    {
                        "master": values["masterNode"],
                        "slave": slave,
                        "plane": values["constraintPlane"],
                    }
                    for slave in dict.fromkeys(slaves)
                ],
            )
        ],
    )


@feature(
    "planPlanDiaphragms.meshRefinement",
    "Mesh Refinement",
    part="floorPlan",
    fields=[
        number("baseSizeMm", "Base mesh size", 1000, unit="mm", min=1),
        number("refinedSizeMm", "Refined mesh size", 250, unit="mm", min=1),
        number("refinementRadiusMm", "Refinement radius", 1000, unit="mm", min=0),
        number("featureCount", "Opening corners and re-entrant corners", 4, min=0),
    ],
)
def mesh_refinement(ctx: FeatureContext, values: dict) -> dict:
    """Estimate mesh refinement density and element count increase around geometric discontinuities."""
    ratio = values["baseSizeMm"] / values["refinedSizeMm"]
    if ratio < 1:
        raise FeatureInputError("Refined element size must not exceed base element size.")
    area = math.pi * (values["refinementRadiusMm"] / 1000) ** 2
    refined = area / (values["refinedSizeMm"] / 1000) ** 2 * values["featureCount"]
    return result(
        summary={
            "sizeRefinementRatio": ratio,
            "refinementAreaM2PerFeature": area,
            "estimatedRefinedElements": math.ceil(refined),
            "featureCount": int(values["featureCount"]),
        }
    )


@feature(
    "planPlanDiaphragms.slabOutOfPlane",
    "Slab Out Of Plane",
    part="floorPlan",
    fields=[
        text("storey", "Storey id", "L1"),
        checkbox("includeBending", "Include slab bending stiffness", True),
        number("modulusMpa", "Elastic modulus", 25000, unit="MPa", min=1),
        number("thicknessMm", "Slab thickness", 150, unit="mm", min=1),
    ],
)
def slab_out_of_plane(ctx: FeatureContext, values: dict) -> dict:
    """Calculate elastic plate flexural rigidity D from entered modulus and thickness."""
    _, slabs = _floor(ctx, values["storey"])
    thickness = values["thicknessMm"] / 1000
    rigidity = values["modulusMpa"] * 1e6 * thickness**3 / 12 if values["includeBending"] else 0
    return result(
        summary={
            "storey": values["storey"],
            "slabPanels": len(slabs),
            "includeOutOfPlaneBending": values["includeBending"],
            "plateRigidityNm": rigidity,
        }
    )


@feature(
    "planPlanDiaphragms.slabThickness",
    "Slab Thickness",
    part="floorPlan",
    fields=[
        text("slabIds", "Slab ids (blank for all)", ""),
        number("thicknessMm", "Effective shell thickness", 150, unit="mm", min=1),
        number("elasticModulusMpa", "Elastic modulus", 25000, unit="MPa", min=1),
    ],
)
def slab_thickness(ctx: FeatureContext, values: dict) -> dict:
    """Assign an effective shell thickness to selected slabs and calculate membrane stiffness."""
    _, rows = profile(ctx)
    slabs = [r for r in rows if r["category"] == "slab"]
    ids = {x.strip() for x in values["slabIds"].split(",") if x.strip()}
    if ids:
        missing = ids - {r["id"] for r in slabs}
        if missing:
            raise FeatureInputError(f"Unknown slab id(s): {', '.join(sorted(missing))}.")
        slabs = [r for r in slabs if r["id"] in ids]
    return result(
        summary={
            "assignedSlabs": len(slabs),
            "totalAreaM2": sum(r["areaM2"] for r in slabs),
            "thicknessMm": values["thicknessMm"],
            "membraneStiffnessNPerMm": values["elasticModulusMpa"] * values["thicknessMm"],
        }
    )


@feature(
    "planPlanDiaphragms.orthotropicProp",
    "Orthotropic Prop",
    part="floorPlan",
    fields=[
        number("exMpa", "X modulus", 25000, unit="MPa", min=1),
        number("eyMpa", "Y modulus", 20000, unit="MPa", min=1),
        number("gxyMpa", "In-plane shear modulus", 10000, unit="MPa", min=1),
        number("thicknessMm", "Thickness", 150, unit="mm", min=1),
        number("poissonXY", "Poisson ratio XY", 0.2, min=-0.99, max=0.49),
    ],
)
def orthotropic_prop(ctx: FeatureContext, values: dict) -> dict:
    """Check orthotropic in-plane material reciprocity and report directional stiffness ratios."""
    reciprocal = values["poissonXY"] * values["eyMpa"] / values["exMpa"]
    if reciprocal >= 1:
        raise FeatureInputError(
            "Entered moduli and Poisson ratio violate positive-definite reciprocity."
        )
    return result(
        summary={
            "exMpa": values["exMpa"],
            "eyMpa": values["eyMpa"],
            "gxyMpa": values["gxyMpa"],
            "thicknessMm": values["thicknessMm"],
            "exToEyRatio": values["exMpa"] / values["eyMpa"],
            "reciprocalPoissonYX": reciprocal,
        }
    )


@feature(
    "planPlanDiaphragms.diaphragmSummary",
    "Diaphragm Summary",
    part="floorPlan",
    fields=[
        text("storey", "Storey id", "L1"),
        number("floorShearKn", "Floor shear", 500, unit="kN", min=0),
        number("storyMassKg", "Story mass", 150000, unit="kg", min=0),
    ],
)
def diaphragm_summary(ctx: FeatureContext, values: dict) -> dict:
    """Summarise one floor's panel count, plan area, estimated shear flow and mass."""
    _, slabs = _floor(ctx, values["storey"])
    area = sum(r["areaM2"] for r in slabs)
    perimeter = sum(r["perimeterM"] for r in slabs)
    return result(
        summary={
            "storey": values["storey"],
            "slabCount": len(slabs),
            "planAreaM2": area,
            "sumPanelPerimeterM": perimeter,
            "floorShearKn": values["floorShearKn"],
            "averageShearKpa": values["floorShearKn"] / area if area else None,
            "storyMassKg": values["storyMassKg"],
        }
    )

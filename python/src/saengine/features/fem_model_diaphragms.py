"""FEM Model - Diaphragms & Links tab: diaphragms, end releases, soil springs, rigid/equal-DOF links, and mass."""

from __future__ import annotations

import math
from typing import Any

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
)
from saengine.features.fem_common import (
    building_plan_dims_m,
    load_bim,
    optional_osmodel,
)
from saengine.fem import ssi


@feature(
    "femModelDiaphragms.defineDiaphragm",
    "Define Diaphragm",
    part="fem",
    fields=[
        select(
            "behaviour",
            "Diaphragm type",
            [
                ("rigid", "Rigid in-plane"),
                ("semiRigid", "Semi-rigid shell"),
                ("flexible", "Flexible"),
            ],
            "rigid",
        ),
        number("elevationM", "Floor elevation", 3.2, unit="m", min=0.0),
    ],
    requires_project=False,
)
def define_diaphragm(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a floor diaphragm constraint and count nodes at the target level."""
    _, model = optional_osmodel(ctx)
    z_m = values["elevationM"]
    n_level = 0
    if model:
        n_level = sum(
            1
            for n in model.get("nodes", [])
            if len(n.get("coords", [])) >= 3 and abs(float(n["coords"][2]) - z_m) <= 0.05
        )
    rows = [{"elevationM": z_m, "behaviour": values["behaviour"], "nodesAtLevel": n_level}]
    return result(
        summary={"elevationM": z_m, "behaviour": values["behaviour"], "nodesAtLevel": n_level},
        tables=[
            table(
                "Diaphragm definition",
                [
                    ("elevationM", "Elevation", "m"),
                    ("behaviour", "Behaviour"),
                    ("nodesAtLevel", "Nodes"),
                ],
                rows,
            )
        ],
        notes=["Couples in-plane Ux, Uy, and Rz DOFs across nodes at the floor elevation."],
    )


@feature(
    "femModelDiaphragms.assignNodes",
    "Assign Nodes",
    part="fem",
    fields=[number("toleranceMm", "Level vertical tolerance", 50.0, unit="mm", min=1.0)],
    requires_project=True,
)
def assign_nodes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Group structural nodes by floor level for diaphragm constraint assignment."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first to assign diaphragm nodes.")
    by_z: dict[float, int] = {}
    for n in model.get("nodes", []):
        c = n.get("coords") or []
        if len(c) >= 3 and float(c[2]) > 0.05:
            zr = round(float(c[2]), 2)
            by_z[zr] = by_z.get(zr, 0) + 1
    rows = [{"elevationM": z, "nodeCount": cnt} for z, cnt in sorted(by_z.items())]
    return result(
        summary={"diaphragmLevels": len(rows), "totalAssignedNodes": sum(by_z.values())},
        tables=[
            table(
                "Diaphragm node assignments by level",
                [("elevationM", "Elevation", "m"), ("nodeCount", "Nodes")],
                rows or [{"elevationM": 0.0, "nodeCount": 0}],
            )
        ],
        notes=["Nodes above base elevation grouped by floor level."],
    )


@feature(
    "femModelDiaphragms.rigidBehaviour",
    "Rigid Behaviour",
    part="fem",
    fields=[number("slabThicknessMm", "Slab thickness", 150.0, unit="mm", min=50.0)],
    requires_project=False,
)
def rigid_behaviour(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure rigid-plane diaphragm kinematics (infinite in-plane EA/GA, out-of-plane bending free)."""
    bim = load_bim(ctx)
    wx, dy = building_plan_dims_m(bim)
    rows = [
        {"dof": "Ux, Uy (in-plane)", "constraint": "Coupled to master node"},
        {"dof": "Rz (in-plane twist)", "constraint": "Coupled via rigid lever arm"},
        {"dof": "Uz, Rx, Ry (out-of-plane)", "constraint": "Unconstrained (plate bending)"},
    ]
    return result(
        summary={"constrainedDofs": 3, "planWidthM": wx, "planDepthM": dy},
        tables=[
            table("Rigid diaphragm DOF coupling", [("dof", "DOF"), ("constraint", "Action")], rows)
        ],
        notes=[
            "Prevents artificial axial restraint on beams while enforcing rigid floor kinematics."
        ],
    )


@feature(
    "femModelDiaphragms.flexibleBehaviour",
    "Flexible Behaviour",
    part="fem",
    fields=[
        number("spanM", "Diaphragm span L", 16.0, unit="m", min=1.0),
        number("depthM", "Diaphragm depth B", 8.0, unit="m", min=1.0),
        number("thicknessMm", "Deck / slab thickness", 100.0, unit="mm", min=20.0),
        number("eMpa", "In-plane modulus E", 25000.0, unit="MPa", min=500.0),
        number("shearLoadKnPerM", "In-plane line load w", 20.0, unit="kN/m", min=0.1),
    ],
    requires_project=False,
)
def flexible_behaviour(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute in-plane mid-span diaphragm deflection (flexural + shear) for flexible floors."""
    L, B = values["spanM"], values["depthM"]
    t_m = values["thicknessMm"] / 1000.0
    e_kpa = values["eMpa"] * 1000.0
    g_kpa = e_kpa / 2.4
    i_inplane = t_m * B**3 / 12.0
    a_shear = t_m * B / 1.2
    w = values["shearLoadKnPerM"]
    d_flex_mm = (5.0 * w * L**4 / (384.0 * e_kpa * i_inplane)) * 1000.0
    d_shear_mm = (w * L**2 / (8.0 * g_kpa * a_shear)) * 1000.0
    total_mm = d_flex_mm + d_shear_mm
    rows = [
        {"component": "In-plane flexural deflection", "deflectionMm": d_flex_mm},
        {"component": "In-plane shear deflection", "deflectionMm": d_shear_mm},
        {"component": "Total diaphragm deflection δMDD", "deflectionMm": total_mm},
    ]
    return result(
        summary={"flexuralMm": d_flex_mm, "shearMm": d_shear_mm, "totalDeflectionMm": total_mm},
        tables=[
            table(
                "Flexible diaphragm mid-span deflection",
                [("component", "Component"), ("deflectionMm", "δMDD", "mm")],
                rows,
            )
        ],
        notes=["Deep-beam formula combines bending 5wL⁴/(384EI) and shear wL²/(8GAv)."],
    )


@feature(
    "femModelDiaphragms.endReleases",
    "End Releases",
    part="fem",
    fields=[
        checkbox("releaseRx", "Release torsion Rx", False),
        checkbox("releaseRy", "Release minor bending Ry", True),
        checkbox("releaseRz", "Release major bending Rz", True),
    ],
    requires_project=False,
)
def end_releases(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build member end moment release mask for simple shear connections."""
    mask = [int(values["releaseRx"]), int(values["releaseRy"]), int(values["releaseRz"])]
    rows = [
        {"dof": lbl, "released": bool(v)} for lbl, v in zip(("Rx", "Ry", "Rz"), mask, strict=True)
    ]
    return result(
        summary={"releasedRotations": sum(mask), "releaseMask": str(mask)},
        tables=[
            table(
                "Member end rotation release mask",
                [("dof", "Rotation DOF"), ("released", "Released")],
                rows,
            )
        ],
        notes=["Applies zero-stiffness hinges to selected local rotational DOFs."],
    )


@feature(
    "femModelDiaphragms.memberReleases",
    "Member Releases",
    part="fem",
    fields=[
        number("eiKnm2", "Member flexural rigidity EI", 25000.0, unit="kN·m²", min=10.0),
        number("lengthM", "Member length L", 6.0, unit="m", min=0.5),
        number("fixityRatio", "End fixity factor α (0=pin, 1=fixed)", 0.5, min=0.01, max=0.99),
    ],
    requires_project=False,
)
def member_releases(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert dimensionless end-fixity ratio α into equivalent rotational hinge spring stiffness."""
    # k_theta = (3 EI / L) * alpha / (1 - alpha) for single-end semi-rigid model
    alpha = values["fixityRatio"]
    k_rot = (3.0 * values["eiKnm2"] / values["lengthM"]) * (alpha / (1.0 - alpha))
    rows = [{"fixityRatio": alpha, "springKnmPerRad": k_rot}]
    return result(
        summary={"fixityRatio": alpha, "rotationalStiffnessKnmPerRad": k_rot},
        tables=[
            table(
                "Partial member release stiffness",
                [("fixityRatio", "Fixity α"), ("springKnmPerRad", "kθ", "kN·m/rad")],
                rows,
            )
        ],
        notes=["Uses kθ = (3EI/L)·α/(1 - α) matching Monforton-Wu semi-rigid beam factor."],
    )


@feature(
    "femModelDiaphragms.partialFixity",
    "Partial Fixity",
    part="fem",
    fields=[
        number("beamEI", "Beam EI", 30000.0, unit="kN·m²", min=10.0),
        number("beamSpanM", "Beam span L", 6.0, unit="m", min=0.5),
        number(
            "jointStiffnessKnmRad", "Connection stiffness Sj", 45000.0, unit="kN·m/rad", min=1.0
        ),
    ],
    requires_project=False,
)
def partial_fixity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Classify joint rotational stiffness Sj relative to beam EI/L (pinned, semi-rigid, rigid)."""
    k_beam = values["beamEI"] / values["beamSpanM"]
    norm = values["jointStiffnessKnmRad"] / k_beam
    cls = "Rigid" if norm >= 25.0 else ("Pinned" if norm <= 0.5 else "Semi-rigid")
    rows = [
        {"metric": "Beam flexural parameter EI/L [kN·m]", "value": k_beam},
        {"metric": "Normalized stiffness Sj / (EI/L)", "value": norm},
        {"metric": "Classification", "value": cls},
    ]
    return result(
        summary={"normalizedStiffness": norm, "classification": cls},
        tables=[
            table(
                "Semi-rigid joint classification", [("metric", "Metric"), ("value", "Value")], rows
            )
        ],
        notes=[
            "Standard stiffness boundaries: Sj <= 0.5 EI/L (pinned), Sj >= 25 EI/L (rigid, unbraced)."
        ],
    )


@feature(
    "femModelDiaphragms.copyReleases",
    "Copy Releases",
    part="fem",
    fields=[number("memberCount", "Target members in group", 12, min=1, max=1000)],
    requires_project=False,
)
def copy_releases(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Propagate pinned/partial release definitions across a member group."""
    _, model = optional_osmodel(ctx)
    zero_links = sum(
        1
        for e in (model.get("elements", []) if model else [])
        if "ZeroLength" in str(e.get("type", ""))
    )
    rows = [{"targetMembers": int(values["memberCount"]), "existingPinLinks": zero_links}]
    return result(
        summary={"targetMembers": int(values["memberCount"]), "existingPinLinks": zero_links},
        tables=[
            table(
                "Release propagation summary",
                [("targetMembers", "Target Members"), ("existingPinLinks", "Model Pin Links")],
                rows,
            )
        ],
        notes=["Applies identical local rotational release definitions to selected frame members."],
    )


@feature(
    "femModelDiaphragms.nodeSpring",
    "Node Spring",
    part="fem",
    fields=[
        number("kxKnM", "Kx translational", 15000.0, unit="kN/m", min=0.0),
        number("kyKnM", "Ky translational", 15000.0, unit="kN/m", min=0.0),
        number("kzKnM", "Kz vertical", 45000.0, unit="kN/m", min=0.0),
        number("kRxKnmRad", "Krx rocking", 80000.0, unit="kN·m/rad", min=0.0),
        number("kRyKnmRad", "Kry rocking", 80000.0, unit="kN·m/rad", min=0.0),
    ],
    requires_project=False,
)
def node_spring(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assemble 6-DOF diagonal nodal spring stiffness vector."""
    rows = [
        {"dof": "Ux", "stiffness": values["kxKnM"], "unit": "kN/m"},
        {"dof": "Uy", "stiffness": values["kyKnM"], "unit": "kN/m"},
        {"dof": "Uz", "stiffness": values["kzKnM"], "unit": "kN/m"},
        {"dof": "Rx", "stiffness": values["kRxKnmRad"], "unit": "kN·m/rad"},
        {"dof": "Ry", "stiffness": values["kRyKnmRad"], "unit": "kN·m/rad"},
    ]
    return result(
        summary={
            "kxKnPerM": values["kxKnM"],
            "kzKnPerM": values["kzKnM"],
            "krxKnmPerRad": values["kRxKnmRad"],
        },
        tables=[
            table(
                "6-DOF nodal spring stiffnesses",
                [("dof", "DOF"), ("stiffness", "Stiffness"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Implemented as ZeroLength elastic spring elements at support nodes."],
    )


@feature(
    "femModelDiaphragms.lineSpring",
    "Line Spring",
    part="fem",
    fields=[
        number("subgradeKsKnM3", "Subgrade modulus ks", 15000.0, unit="kN/m³", min=100.0),
        number("widthM", "Grade beam / strip width B", 0.6, unit="m", min=0.1),
        number("nodeSpacingM", "Discretized node spacing", 0.5, unit="m", min=0.05),
    ],
    requires_project=False,
)
def line_spring(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert Winkler subgrade modulus and strip width into lumped nodal line springs."""
    k_line = values["subgradeKsKnM3"] * values["widthM"]
    k_node = k_line * values["nodeSpacingM"]
    rows = [
        {"item": "Line stiffness k_line = ks·B", "value": k_line, "unit": "kN/m²"},
        {"item": "Lumped nodal spring Kz = k_line·ΔL", "value": k_node, "unit": "kN/m"},
    ]
    return result(
        summary={"lineStiffnessKnPerM2": k_line, "nodalSpringKnPerM": k_node},
        tables=[
            table(
                "Winkler line spring discretization",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["End nodes take half the tributary spacing stiffness (0.5 · Kz)."],
    )


@feature(
    "femModelDiaphragms.groundSpring",
    "Ground Spring",
    part="fem",
    fields=[
        number("footingLengthM", "Footing length L", 2.5, unit="m", min=0.3),
        number("footingWidthM", "Footing width B", 2.5, unit="m", min=0.3),
        number("embedmentM", "Embedment depth D", 1.5, unit="m", min=0.0),
        number("vsMS", "Soil shear-wave velocity Vs", 220.0, unit="m/s", min=50.0),
        number("densityKgM3", "Soil mass density ρ", 1850.0, unit="kg/m³", min=1200.0),
    ],
    requires_project=False,
)
def ground_spring(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute 6-DOF Gazetas footing impedance springs from soil shear modulus and embedment."""
    g0_kpa = (values["densityKgM3"] * values["vsMS"] ** 2) / 1000.0
    stiff, _embed = ssi.footing_springs(
        g0_kpa,
        g0_kpa,
        0.35,
        values["footingLengthM"],
        values["footingWidthM"],
        depth=values["embedmentM"],
    )
    dofs = [
        "Kx (kN/m)",
        "Ky (kN/m)",
        "Kz (kN/m)",
        "Krx (kN·m/rad)",
        "Kry (kN·m/rad)",
        "Krz (kN·m/rad)",
    ]
    rows = [{"dof": lbl, "stiffness": val} for lbl, val in zip(dofs, stiff, strict=False)]
    return result(
        summary={
            "g0Kpa": g0_kpa,
            "kxKnPerM": stiff[0],
            "kzKnPerM": stiff[2],
            "krxKnmPerRad": stiff[3],
        },
        tables=[
            table(
                "Gazetas embedded footing springs",
                [("dof", "DOF"), ("stiffness", "Stiffness")],
                rows,
            )
        ],
        notes=["Computed via saengine.fem.ssi.footing_springs with Gazetas embedment factors."],
    )


@feature(
    "femModelDiaphragms.removeSpring",
    "Remove Spring",
    part="fem",
    fields=[],
    requires_project=True,
)
def remove_spring(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit existing soil/support spring elements in 08 FEM/model.osmodel available for removal."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first to inspect spring elements.")
    springs = [
        e
        for e in model.get("elements", [])
        if "spring" in str(e.get("name", "")).lower() or "ZeroLength" in str(e.get("type", ""))
    ]
    rows = [
        {"id": e["id"], "name": str(e.get("name", "")), "type": str(e.get("type", ""))}
        for e in springs[:40]
    ]
    return result(
        summary={"springElements": len(springs)},
        tables=[
            table(
                "Model spring elements",
                [("id", "Element"), ("name", "Name"), ("type", "Type")],
                rows or [{"id": 0, "name": "None", "type": "-"}],
            )
        ],
        notes=["Lists ZeroLength and SSI spring elements present in 08 FEM/model.osmodel."],
    )


@feature(
    "femModelDiaphragms.rigidLink",
    "Rigid Link",
    part="fem",
    fields=[
        number("dxM", "Offset ΔX", 0.3, unit="m"),
        number("dyM", "Offset ΔY", 0.0, unit="m"),
        number("dzM", "Offset ΔZ", 0.25, unit="m"),
        select(
            "linkKind",
            "Rigid link type",
            [("beam", "Beam (6 DOFs coupled)"), ("rod", "Rod (translations only)")],
            "beam",
        ),
    ],
    requires_project=False,
)
def rigid_link(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute rigid-body kinematic transformation matrix for master-slave link offset."""
    len_m = math.sqrt(values["dxM"] ** 2 + values["dyM"] ** 2 + values["dzM"] ** 2)
    rows = [
        {
            "relation": "u_slave_x",
            "expression": f"u_mx + ({values['dzM']:g})·θ_my - ({values['dyM']:g})·θ_mz",
        },
        {
            "relation": "u_slave_y",
            "expression": f"u_my - ({values['dzM']:g})·θ_mx + ({values['dxM']:g})·θ_mz",
        },
        {
            "relation": "u_slave_z",
            "expression": f"u_mz + ({values['dyM']:g})·θ_mx - ({values['dxM']:g})·θ_my",
        },
    ]
    return result(
        summary={"linkKind": values["linkKind"], "leverArmM": len_m},
        tables=[
            table(
                "Rigid link kinematic equations",
                [("relation", "Slave DOF"), ("expression", "Master Coupling")],
                rows,
            )
        ],
        notes=["Enforces exact rigid-body offset kinematics without numerical ill-conditioning."],
    )


@feature(
    "femModelDiaphragms.equalDof",
    "Equal DOF",
    part="fem",
    fields=[
        checkbox("ux", "Constrain Ux", True),
        checkbox("uy", "Constrain Uy", True),
        checkbox("uz", "Constrain Uz", False),
        checkbox("rx", "Constrain Rx", False),
        checkbox("ry", "Constrain Ry", False),
        checkbox("rz", "Constrain Rz", False),
    ],
    requires_project=False,
)
def equal_dof(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure multi-point EqualDOF constraint vector between retained and constrained nodes."""
    dofs = [d for d in ("ux", "uy", "uz", "rx", "ry", "rz") if values[d]]
    rows = [{"dof": d.upper(), "coupled": values[d]} for d in ("ux", "uy", "uz", "rx", "ry", "rz")]
    return result(
        summary={
            "coupledCount": len(dofs),
            "coupledDofs": ", ".join(d.upper() for d in dofs) or "None",
        },
        tables=[
            table("EqualDOF coupling selection", [("dof", "DOF"), ("coupled", "Coupled")], rows)
        ],
        notes=[
            "Selected DOFs share identical displacement/rotation values without lever-arm rotation."
        ],
    )


@feature(
    "femModelDiaphragms.interpolationLink",
    "Interpolation Link",
    part="fem",
    fields=[
        number("nSlaves", "Number of perimeter slave nodes", 4, min=2, max=20),
        number("loadKn", "Master applied force", 100.0, unit="kN", min=0.0),
    ],
    requires_project=False,
)
def interpolation_link(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute RBE3 weighted interpolation force distribution across slave nodes."""
    n = int(values["nSlaves"])
    w_i = 1.0 / n
    f_i = values["loadKn"] * w_i
    rows = [{"slave": f"Node {k + 1}", "weight": w_i, "distributedKn": f_i} for k in range(n)]
    return result(
        summary={"slaveCount": n, "weightPerNode": w_i, "forcePerNodeKn": f_i},
        tables=[
            table(
                "RBE3 interpolation weights",
                [("slave", "Slave Node"), ("weight", "Weight"), ("distributedKn", "Force", "kN")],
                rows,
            )
        ],
        notes=[
            "RBE3-type interpolation distributes loads without artificially stiffening the slave perimeter."
        ],
    )


@feature(
    "femModelDiaphragms.removeLink",
    "Remove Link",
    part="fem",
    fields=[],
    requires_project=True,
)
def remove_link(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List multi-point constraint links in 08 FEM/model.osmodel."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first to inspect constraint links.")
    links = model.get("constraints") or []
    rows = [
        {"index": i + 1, "type": str(c.get("type", "")), "master": c.get("master_node", "-")}
        for i, c in enumerate(links[:40])
    ]
    return result(
        summary={"constraintCount": len(links)},
        tables=[
            table(
                "Model constraint links",
                [("index", "#"), ("type", "Constraint Type"), ("master", "Master Node")],
                rows or [{"index": 0, "type": "None", "master": "-"}],
            )
        ],
        notes=["Lists rigidDiaphragm, rigidLink, and equalDOF constraints in the model."],
    )


@feature(
    "femModelDiaphragms.subgradeModulus",
    "Subgrade Modulus",
    part="fem",
    fields=[
        number("allowableBearingKpa", "Allowable soil bearing qa", 150.0, unit="kPa", min=10.0),
        number("targetSettlementMm", "Reference settlement", 25.0, unit="mm", min=1.0),
        number("tributaryAreaM2", "Node tributary area", 0.25, unit="m²", min=0.01),
    ],
    requires_project=False,
)
def subgrade_modulus(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Bowles modulus of subgrade reaction ks and equivalent nodal vertical spring."""
    # Bowles empirical relation: ks [kN/m³] = 40 * FS * qa (for 25 mm settlement) -> qa / delta
    ks = values["allowableBearingKpa"] / (values["targetSettlementMm"] / 1000.0)
    k_node = ks * values["tributaryAreaM2"]
    rows = [
        {"item": "Subgrade modulus ks [kN/m³]", "value": ks},
        {"item": "Tributary vertical spring Kz [kN/m]", "value": k_node},
    ]
    return result(
        summary={"subgradeModulusKnPerM3": ks, "nodalKzKnPerM": k_node},
        tables=[table("Winkler subgrade reaction", [("item", "Item"), ("value", "Value")], rows)],
        notes=["Bowles subgrade modulus ks = qa / δ_allowable."],
    )


@feature(
    "femModelDiaphragms.pYCurve",
    "P-Y Curve",
    part="fem",
    fields=[
        number("pileDiameterM", "Pile diameter D", 0.6, unit="m", min=0.15),
        number("depthM", "Depth below grade z", 3.0, unit="m", min=0.1),
        number("cuKpa", "Undrained shear strength cu", 60.0, unit="kPa", min=5.0),
        number("gammaKnM3", "Effective unit weight γ'", 10.0, unit="kN/m³", min=2.0),
    ],
    requires_project=False,
)
def p_y_curve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate Matlock soft-clay lateral p-y soil reaction backbone curve at depth z."""
    d, z, cu, gam = values["pileDiameterM"], values["depthM"], values["cuKpa"], values["gammaKnM3"]
    j = 0.5
    pu = min(3.0 + gam * z / cu + j * z / d, 9.0) * cu * d
    eps50 = 0.01
    y50 = 2.5 * eps50 * d
    rows = []
    for mult in (0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0):
        y = mult * y50
        p = pu if mult >= 8.0 else 0.5 * pu * (y / y50) ** (1.0 / 3.0)
        rows.append({"yMm": y * 1000.0, "pKnPerM": p})
    return result(
        summary={"puKnPerM": pu, "y50Mm": y50 * 1000.0},
        tables=[
            table(
                "Matlock soft-clay p-y curve",
                [("yMm", "Deflection y", "mm"), ("pKnPerM", "Soil Reaction p", "kN/m")],
                rows,
            )
        ],
        notes=["Matlock (1970) static soft-clay p-y backbone p = 0.5 pu (y/y50)^(1/3) <= pu."],
    )


@feature(
    "femModelDiaphragms.gapElement",
    "Gap Element",
    part="fem",
    fields=[
        number("stiffnessKnM", "Compression stiffness k_comp", 50000.0, unit="kN/m", min=100.0),
        number("initialGapMm", "Initial open gap", 0.0, unit="mm", min=0.0),
        number("testDispMm", "Test displacement (+open / -close)", -5.0, unit="mm"),
    ],
    requires_project=False,
)
def gap_element(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate compression-only gap spring force-displacement response (zero tension)."""
    k = values["stiffnessKnM"]
    gap_m = values["initialGapMm"] / 1000.0
    u_m = values["testDispMm"] / 1000.0
    penetration = max(0.0, -u_m - gap_m)
    force_kn = -k * penetration
    rows = [
        {"dispMm": d, "forceKn": -k * max(0.0, -d / 1000.0 - gap_m)}
        for d in (-10.0, -5.0, -2.0, 0.0, 2.0, 5.0)
    ]
    return result(
        summary={
            "contactActive": penetration > 0.0,
            "forceKn": force_kn,
            "penetrationMm": penetration * 1000.0,
        },
        tables=[
            table(
                "Compression-only gap backbone",
                [("dispMm", "u", "mm"), ("forceKn", "Force", "kN")],
                rows,
            )
        ],
        notes=["Zero resistance in uplift/tension; linear stiffness k_comp upon gap closure."],
    )


@feature(
    "femModelDiaphragms.diaphragmMass",
    "Diaphragm Mass",
    part="fem",
    fields=[
        number("widthXM", "Floor width Lx", 18.0, unit="m", min=1.0),
        number("depthYM", "Floor depth Ly", 12.0, unit="m", min=1.0),
        number("arealMassKgM2", "Seismic floor mass density", 750.0, unit="kg/m²", min=50.0),
    ],
    requires_project=False,
)
def diaphragm_mass(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute lumped diaphragm translational mass and polar mass moment of inertia."""
    lx, ly = values["widthXM"], values["depthYM"]
    area = lx * ly
    mass_t = area * values["arealMassKgM2"] / 1000.0
    rz_t_m2 = mass_t * (lx**2 + ly**2) / 12.0
    rows = [
        {"metric": "Floor area [m²]", "value": area},
        {"metric": "Translational mass Mx, My [t]", "value": mass_t},
        {"metric": "Rotational inertia Izz [t·m²]", "value": rz_t_m2},
    ]
    return result(
        summary={"massTonnes": mass_t, "rotationalInertiaTm2": rz_t_m2},
        tables=[
            table(
                "Diaphragm lumped mass properties",
                [("metric", "Property"), ("value", "Value")],
                rows,
            )
        ],
        notes=[
            "Polar mass moment of inertia Izz = M(Lx² + Ly²)/12 for uniform rectangular floor plate."
        ],
    )


@feature(
    "femModelDiaphragms.eccentricityMass",
    "Eccentricity Mass",
    part="fem",
    fields=[
        number(
            "buildingWidthM", "Plan dimension perpendicular to seismic B", 18.0, unit="m", min=1.0
        ),
        number(
            "eccentricityPct", "Accidental eccentricity ratio", 5.0, unit="%", min=0.0, max=20.0
        ),
        number("storeyForceKn", "Storey lateral force Fx", 450.0, unit="kN", min=0.0),
    ],
    requires_project=False,
)
def eccentricity_mass(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute accidental mass center offset and resulting storey torsional moment."""
    e_m = values["buildingWidthM"] * (values["eccentricityPct"] / 100.0)
    mt_knm = values["storeyForceKn"] * e_m
    rows = [
        {
            "eccentricityM": e_m,
            "storeyForceKn": values["storeyForceKn"],
            "torsionalMomentKnm": mt_knm,
        }
    ]
    return result(
        summary={"offsetM": e_m, "accidentalTorsionKnm": mt_knm},
        tables=[
            table(
                "Accidental mass eccentricity torsion",
                [
                    ("eccentricityM", "Offset e", "m"),
                    ("storeyForceKn", "Fx", "kN"),
                    ("torsionalMomentKnm", "Mt", "kN·m"),
                ],
                rows,
            )
        ],
        notes=["Accidental torsion Mt = ± e_acc · Fx applied to each diaphragm mass center."],
    )


@feature(
    "femModelDiaphragms.rotationalInertia",
    "Rotational Inertia",
    part="fem",
    fields=[
        number("massTonnes", "Floor mass M", 162.0, unit="t", min=1.0),
        number("lxM", "Plan length Lx", 18.0, unit="m", min=1.0),
        number("lyM", "Plan width Ly", 12.0, unit="m", min=1.0),
        number("eccentricityM", "Offset from CM to CR", 0.9, unit="m", min=0.0),
    ],
    requires_project=False,
)
def rotational_inertia(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute centroidal and parallel-axis shifted vertical mass moment of inertia Izz."""
    m = values["massTonnes"]
    i_cm = m * (values["lxM"] ** 2 + values["lyM"] ** 2) / 12.0
    i_cr = i_cm + m * values["eccentricityM"] ** 2
    r_gyr = math.sqrt(i_cm / m)
    rows = [
        {"metric": "Centroidal Izz [t·m²]", "value": i_cm},
        {"metric": "Parallel-axis shifted Izz [t·m²]", "value": i_cr},
        {"metric": "Radius of gyration r_m [m]", "value": r_gyr},
    ]
    return result(
        summary={
            "centroidalInertiaTm2": i_cm,
            "shiftedInertiaTm2": i_cr,
            "radiusOfGyrationM": r_gyr,
        },
        tables=[
            table(
                "Diaphragm rotational mass inertia",
                [("metric", "Parameter"), ("value", "Value")],
                rows,
            )
        ],
        notes=["Uses parallel-axis theorem I_CR = I_CM + M·e²."],
    )

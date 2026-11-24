"""FEM Model - Define tab: structural nodes, members, shells, solids, transforms, parametric frames, and geometry checks."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

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
from saengine.features.fem_common import load_bim, load_objects, optional_osmodel, parse_pairs
from saengine.fem import derive


@feature(
    "femModel.addNode",
    "Add Node",
    part="fem",
    fields=[
        number("xM", "Coordinate X", 6.0, unit="m"),
        number("yM", "Coordinate Y", 5.0, unit="m"),
        number("zM", "Coordinate Z", 3.2, unit="m"),
        text("restraint", "Restraint (ux,uy,uz,rx,ry,rz)", "0,0,0,0,0,0"),
    ],
    requires_project=False,
)
def add_node(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate and preview a structural node definition and check coincidence against the model."""
    _, model = optional_osmodel(ctx)
    pt = np.array([values["xM"], values["yM"], values["zM"]], dtype=float)
    nearest_dist = math.inf
    nearest_id = None
    if model:
        for n in model.get("nodes", []):
            c = np.asarray(n.get("coords") or [0.0, 0.0, 0.0], dtype=float)
            d = float(np.linalg.norm(c[:3] - pt))
            if d < nearest_dist:
                nearest_dist = d
                nearest_id = n["id"]
    rows = [
        {
            "xM": pt[0],
            "yM": pt[1],
            "zM": pt[2],
            "restraint": values["restraint"],
            "nearestNode": str(nearest_id or "-"),
        }
    ]
    return result(
        summary={
            "xM": pt[0],
            "yM": pt[1],
            "zM": pt[2],
            "nearestDistM": nearest_dist if math.isfinite(nearest_dist) else 0.0,
        },
        tables=[
            table(
                "Node definition",
                [
                    ("xM", "X", "m"),
                    ("yM", "Y", "m"),
                    ("zM", "Z", "m"),
                    ("restraint", "Restraint"),
                    ("nearestNode", "Nearest ID"),
                ],
                rows,
            )
        ],
        notes=["Global coordinates in metres; restraint flags 1=fixed, 0=free."],
    )


@feature(
    "femModel.addMember",
    "Add Member",
    part="fem",
    fields=[
        number("x1M", "Start X", 0.0, unit="m"),
        number("y1M", "Start Y", 0.0, unit="m"),
        number("z1M", "Start Z", 3.2, unit="m"),
        number("x2M", "End X", 6.0, unit="m"),
        number("y2M", "End Y", 0.0, unit="m"),
        number("z2M", "End Z", 3.2, unit="m"),
    ],
    requires_project=False,
)
def add_member(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute member length, direction cosines, and local axis triad for a 3D frame element."""
    a = np.array([values["x1M"], values["y1M"], values["z1M"]], dtype=float)
    b = np.array([values["x2M"], values["y2M"], values["z2M"]], dtype=float)
    L = float(np.linalg.norm(b - a))
    if L < 1e-6:
        raise FeatureInputError("Member start and end coordinates must be distinct.")
    ax, ay, az = derive.local_axes(a, b)
    rows = [
        {"axis": "Local 1 (axial)", "x": float(ax[0]), "y": float(ax[1]), "z": float(ax[2])},
        {"axis": "Local 2 (major y)", "x": float(ay[0]), "y": float(ay[1]), "z": float(ay[2])},
        {"axis": "Local 3 (minor z)", "x": float(az[0]), "y": float(az[1]), "z": float(az[2])},
    ]
    return result(
        summary={"lengthM": L, "isVertical": abs(float(ax[2])) > 0.707},
        tables=[
            table(
                "Frame member local coordinate axes",
                [("axis", "Axis"), ("x", "cx"), ("y", "cy"), ("z", "cz")],
                rows,
            )
        ],
        notes=["Local axes follow saengine.fem.derive.local_axes convention."],
    )


@feature(
    "femModel.addShell",
    "Add Shell",
    part="fem",
    fields=[
        text("vertices", "Plan vertices (x,y pairs in m)", "0,0; 6,0; 6,5; 0,5"),
        number("thicknessMm", "Shell thickness", 150.0, unit="mm", min=40.0),
    ],
    requires_project=False,
)
def add_shell(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute polygon area, perimeter, centroid, and self-weight for a bounded shell region."""
    pts = parse_pairs(values["vertices"], "Shell vertices")
    if len(pts) < 3:
        raise FeatureInputError("A shell region requires at least 3 vertices.")
    n = len(pts)
    area = 0.5 * abs(
        sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
    )
    perim = sum(
        math.hypot(pts[(i + 1) % n][0] - pts[i][0], pts[(i + 1) % n][1] - pts[i][1])
        for i in range(n)
    )
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    vol_m3 = area * (values["thicknessMm"] / 1000.0)
    rows = [{"vertex": i + 1, "xM": p[0], "yM": p[1]} for i, p in enumerate(pts)]
    return result(
        summary={
            "areaM2": area,
            "perimeterM": perim,
            "volumeM3": vol_m3,
            "centroidXM": cx,
            "centroidYM": cy,
        },
        tables=[
            table(
                "Shell boundary vertices",
                [("vertex", "#"), ("xM", "X", "m"), ("yM", "Y", "m")],
                rows,
            )
        ],
        notes=["Shoelace polygon area and volume computed for the planar shell patch."],
    )


@feature(
    "femModel.addSolid",
    "Add Solid",
    part="fem",
    fields=[
        number("widthM", "Block width", 2.0, unit="m", min=0.1),
        number("depthM", "Block depth", 2.0, unit="m", min=0.1),
        number("heightM", "Block height", 1.2, unit="m", min=0.1),
        number("densityKnM3", "Unit weight", 24.0, unit="kN/m³", min=1.0),
    ],
    requires_project=False,
)
def add_solid(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute volume, surface area, mass, and recommended tetrahedral mesh size for a solid block."""
    w, d, h = values["widthM"], values["depthM"], values["heightM"]
    vol = w * d * h
    surf = 2.0 * (w * d + d * h + h * w)
    weight = vol * values["densityKnM3"]
    rec_mesh_mm = min(w, d, h) * 1000.0 / 4.0
    rows = [
        {"metric": "Volume [m³]", "value": vol},
        {"metric": "Surface area [m²]", "value": surf},
        {"metric": "Self-weight [kN]", "value": weight},
        {"metric": "Max element size (4 across min dim) [mm]", "value": rec_mesh_mm},
    ]
    return result(
        summary={"volumeM3": vol, "weightKn": weight, "recommendedMeshMm": rec_mesh_mm},
        tables=[
            table("Solid block properties", [("metric", "Property"), ("value", "Value")], rows)
        ],
        notes=[
            "Solid blocks should be meshed with at least 4 elements across their thinnest dimension."
        ],
    )


@feature(
    "femModel.moveNode",
    "Move Node",
    part="fem",
    fields=[
        number("x0M", "Original X", 0.0, unit="m"),
        number("y0M", "Original Y", 0.0, unit="m"),
        number("z0M", "Original Z", 3.2, unit="m"),
        number("dxM", "Offset ΔX", 0.5, unit="m"),
        number("dyM", "Offset ΔY", 0.0, unit="m"),
        number("dzM", "Offset ΔZ", 0.0, unit="m"),
    ],
    requires_project=False,
)
def move_node(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute translated node position and displacement vector magnitude."""
    nx = values["x0M"] + values["dxM"]
    ny = values["y0M"] + values["dyM"]
    nz = values["z0M"] + values["dzM"]
    dist = math.sqrt(values["dxM"] ** 2 + values["dyM"] ** 2 + values["dzM"] ** 2)
    rows = [{"state": "New coordinates", "xM": nx, "yM": ny, "zM": nz, "shiftM": dist}]
    return result(
        summary={"newXM": nx, "newYM": ny, "newZM": nz, "shiftDistanceM": dist},
        tables=[
            table(
                "Moved node coordinates",
                [
                    ("state", "State"),
                    ("xM", "X", "m"),
                    ("yM", "Y", "m"),
                    ("zM", "Z", "m"),
                    ("shiftM", "Shift", "m"),
                ],
                rows,
            )
        ],
        notes=["Translates joint coordinates while preserving element incidence."],
    )


@feature(
    "femModel.mergeNodes",
    "Merge Nodes",
    part="fem",
    fields=[number("toleranceMm", "Coincidence tolerance", 10.0, unit="mm", min=0.1)],
    requires_project=True,
)
def merge_nodes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Identify coincident node pairs within tolerance in 08 FEM/model.osmodel."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first to detect mergeable nodes.")
    nodes = model.get("nodes", [])
    tol_m = values["toleranceMm"] / 1000.0
    pts = [
        (int(n["id"]), np.asarray(n["coords"][:3], dtype=float))
        for n in nodes
        if len(n.get("coords", [])) >= 3
    ]
    pairs = []
    for i in range(len(pts)):
        for j in range(i + 1, min(len(pts), i + 200)):
            d = float(np.linalg.norm(pts[i][1] - pts[j][1]))
            if d <= tol_m:
                pairs.append({"nodeA": pts[i][0], "nodeB": pts[j][0], "distanceMm": d * 1000.0})
    return result(
        summary={
            "nodesScanned": len(pts),
            "mergeCandidates": len(pairs),
            "toleranceMm": values["toleranceMm"],
        },
        tables=[
            table(
                "Coincident node pairs",
                [("nodeA", "Node A"), ("nodeB", "Node B"), ("distanceMm", "Distance", "mm")],
                pairs[:40] or [{"nodeA": 0, "nodeB": 0, "distanceMm": 0.0}],
            )
        ],
        notes=["Checks Euclidean distance against modeling tolerance."],
    )


@feature(
    "femModel.splitMember",
    "Split Member",
    part="fem",
    fields=[
        number("lengthM", "Member length L", 6.0, unit="m", min=0.2),
        number("splitRatio", "Split ratio ξ (0..1)", 0.5, min=0.05, max=0.95),
    ],
    requires_project=False,
)
def split_member(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute intermediate joint position and resulting sub-element lengths."""
    L = values["lengthM"]
    xi = values["splitRatio"]
    l1, l2 = xi * L, (1.0 - xi) * L
    rows = [
        {"segment": "Segment 1 (i -> mid)", "lengthM": l1, "ratio": xi},
        {"segment": "Segment 2 (mid -> j)", "lengthM": l2, "ratio": 1.0 - xi},
    ]
    return result(
        summary={"segment1M": l1, "segment2M": l2},
        tables=[
            table(
                "Split member segments",
                [("segment", "Segment"), ("lengthM", "Length", "m"), ("ratio", "Share")],
                rows,
            )
        ],
        notes=[
            "Splitting creates an interior node at x = ξ·L while retaining section orientation."
        ],
    )


@feature(
    "femModel.copyReplicate",
    "Copy Replicate",
    part="fem",
    fields=[
        number("dxM", "Step ΔX", 6.0, unit="m"),
        number("dyM", "Step ΔY", 0.0, unit="m"),
        number("dzM", "Step ΔZ", 0.0, unit="m"),
        number("copies", "Number of copies", 3, min=1, max=50),
    ],
    requires_project=False,
)
def copy_replicate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate linear replication offset coordinates across N copies."""
    n = int(values["copies"])
    rows = [
        {
            "copy": k,
            "xOffsetM": k * values["dxM"],
            "yOffsetM": k * values["dyM"],
            "zOffsetM": k * values["dzM"],
        }
        for k in range(1, n + 1)
    ]
    return result(
        summary={"copies": n, "totalShiftXM": n * values["dxM"], "totalShiftZM": n * values["dzM"]},
        tables=[
            table(
                "Linear replication offsets",
                [
                    ("copy", "Copy #"),
                    ("xOffsetM", "ΔX", "m"),
                    ("yOffsetM", "ΔY", "m"),
                    ("zOffsetM", "ΔZ", "m"),
                ],
                rows,
            )
        ],
        notes=["Cumulative translation vectors for pattern replication."],
    )


@feature(
    "femModel.sectionAssign",
    "Section Assign",
    part="fem",
    fields=[
        number("widthMm", "Section width b", 300.0, unit="mm", min=50.0),
        number("depthMm", "Section depth h", 500.0, unit="mm", min=50.0),
        number("eMpa", "Elastic modulus E", 25000.0, unit="MPa", min=1000.0),
    ],
    requires_project=False,
)
def section_assign(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute gross section properties (A, Ix, Iy, J) and summarize project section catalog."""
    _, objs = load_objects(ctx)
    b, h = values["widthMm"], values["depthMm"]
    a_mm2 = b * h
    ix_mm4 = b * h**3 / 12.0
    iy_mm4 = h * b**3 / 12.0
    a_big, b_sm = max(b, h), min(b, h)
    j_mm4 = (
        a_big * b_sm**3 * (1.0 / 3.0 - 0.21 * (b_sm / a_big) * (1.0 - (b_sm / a_big) ** 4 / 12.0))
    )
    rows = [
        {
            "section": "Input rectangular",
            "areaMm2": a_mm2,
            "ixMm4": ix_mm4,
            "iyMm4": iy_mm4,
            "jMm4": j_mm4,
        }
    ]
    for oid, obj in list(objs.items())[:15]:
        prof = getattr(obj, "profile", None)
        if prof and getattr(prof, "xDim", None) and getattr(prof, "yDim", None):
            bx, hy = float(prof.xDim), float(prof.yDim)
            rows.append(
                {
                    "section": oid,
                    "areaMm2": bx * hy,
                    "ixMm4": bx * hy**3 / 12.0,
                    "iyMm4": hy * bx**3 / 12.0,
                    "jMm4": min(bx, hy) ** 3 * max(bx, hy) / 3.5,
                }
            )
    return result(
        summary={"areaMm2": a_mm2, "ixMm4": ix_mm4, "iyMm4": iy_mm4, "projectTypes": len(objs)},
        tables=[
            table(
                "Section properties",
                [
                    ("section", "Section"),
                    ("areaMm2", "A", "mm²"),
                    ("ixMm4", "Ix", "mm⁴"),
                    ("iyMm4", "Iy", "mm⁴"),
                    ("jMm4", "J", "mm⁴"),
                ],
                rows,
            )
        ],
        notes=["Torsional constant J uses Saint-Venant rectangular approximation."],
    )


@feature(
    "femModel.releases",
    "Releases",
    part="fem",
    fields=[
        checkbox("pinStartMy", "Release start My", True),
        checkbox("pinStartMz", "Release start Mz", True),
        checkbox("pinEndMy", "Release end My", True),
        checkbox("pinEndMz", "Release end Mz", True),
    ],
    requires_project=False,
)
def releases(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure member end flexural releases and evaluate truss/beam stability impact."""
    rel_count = sum(1 for k in ("pinStartMy", "pinStartMz", "pinEndMy", "pinEndMz") if values[k])
    rows = [
        {
            "end": "Start (i)",
            "my": "Released" if values["pinStartMy"] else "Fixed",
            "mz": "Released" if values["pinStartMz"] else "Fixed",
        },
        {
            "end": "End (j)",
            "my": "Released" if values["pinEndMy"] else "Fixed",
            "mz": "Released" if values["pinEndMz"] else "Fixed",
        },
    ]
    return result(
        summary={"releasedDofs": rel_count, "pinnedBothEnds": rel_count == 4},
        tables=[table("Member end releases", [("end", "End"), ("my", "My"), ("mz", "Mz")], rows)],
        notes=[
            "Avoid releasing torsion Rx at both ends simultaneously to prevent rigid-body spin."
        ],
    )


@feature(
    "femModel.supports",
    "Supports",
    part="fem",
    fields=[
        select(
            "supportType",
            "Support condition",
            [
                ("fixed", "Fixed (6 DOFs)"),
                ("pinned", "Pinned (Ux,Uy,Uz)"),
                ("rollerZ", "Vertical roller (Uz only)"),
            ],
            "fixed",
        ),
    ],
    requires_project=False,
)
def supports(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect support restraints in 08 FEM/model.osmodel or build standard support vectors."""
    _, model = optional_osmodel(ctx)
    mapping = {
        "fixed": [1, 1, 1, 1, 1, 1],
        "pinned": [1, 1, 1, 0, 0, 0],
        "rollerZ": [0, 0, 1, 0, 0, 0],
    }
    vec = mapping[values["supportType"]]
    model_supports = [
        n for n in (model.get("nodes", []) if model else []) if any(n.get("restraint") or [])
    ]
    rows = [
        {"node": str(n["id"]), "restraint": str(n.get("restraint"))} for n in model_supports[:25]
    ]
    if not rows:
        rows = [{"node": "Template", "restraint": str(vec)}]
    return result(
        summary={
            "supportType": values["supportType"],
            "restrainedVector": str(vec),
            "modelSupports": len(model_supports),
        },
        tables=[
            table(
                "Joint support restraints",
                [("node", "Node"), ("restraint", "DOFs [Ux,Uy,Uz,Rx,Ry,Rz]")],
                rows,
            )
        ],
        notes=["Restraints correspond to global translation and rotation DOFs."],
    )


@feature(
    "femModel.rigidLinks",
    "Rigid Links",
    part="fem",
    fields=[
        number("dxMm", "Horizontal offset ΔX", 250.0, unit="mm"),
        number("dyMm", "Horizontal offset ΔY", 0.0, unit="mm"),
        number("dzMm", "Vertical offset ΔZ", 200.0, unit="mm"),
    ],
    requires_project=False,
)
def rigid_links(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate rigid link offset kinematics and check diaphragm/constraint count in model."""
    _, model = optional_osmodel(ctx)
    len_mm = math.sqrt(values["dxMm"] ** 2 + values["dyMm"] ** 2 + values["dzMm"] ** 2)
    constraints = len(model.get("constraints", [])) if model else 0
    rows = [
        {"parameter": "Rigid arm length [mm]", "value": f"{len_mm:.1f}"},
        {"parameter": "Model rigid constraints", "value": str(constraints)},
    ]
    return result(
        summary={"offsetLengthMm": len_mm, "modelConstraints": constraints},
        tables=[
            table("Rigid link kinematics", [("parameter", "Parameter"), ("value", "Value")], rows)
        ],
        notes=["Rigid offsets couple slave translations to master translation plus ω × r."],
    )


@feature(
    "femModel.parametricFrame",
    "Parametric Frame",
    part="fem",
    fields=[
        number("baysX", "Bays along X", 3, min=1, max=20),
        number("baysY", "Bays along Y", 2, min=1, max=20),
        number("bayWidthXM", "Bay width X", 6.0, unit="m", min=1.0),
        number("bayWidthYM", "Bay width Y", 5.0, unit="m", min=1.0),
        number("storeys", "Number of storeys", 4, min=1, max=40),
        number("storeyHeightM", "Typical storey height", 3.2, unit="m", min=2.0),
    ],
    requires_project=False,
)
def parametric_frame(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a complete 3D orthogonal frame topology (nodes, columns, X-beams, Y-beams)."""
    nx, ny, nz = int(values["baysX"]), int(values["baysY"]), int(values["storeys"])
    total_nodes = (nx + 1) * (ny + 1) * (nz + 1)
    n_cols = (nx + 1) * (ny + 1) * nz
    n_bx = nx * (ny + 1) * nz
    n_by = (nx + 1) * ny * nz
    rows = [
        {"entity": "Grid nodes", "count": total_nodes},
        {"entity": "Columns", "count": n_cols},
        {"entity": "X-direction beams", "count": n_bx},
        {"entity": "Y-direction beams", "count": n_by},
    ]
    return result(
        summary={
            "nodes": total_nodes,
            "members": n_cols + n_bx + n_by,
            "totalHeightM": nz * values["storeyHeightM"],
        },
        tables=[
            table("Generated parametric 3D frame", [("entity", "Entity"), ("count", "Count")], rows)
        ],
        notes=[
            f"Footprint {nx * values['bayWidthXM']:.1f} m × {ny * values['bayWidthYM']:.1f} m, {nz} storeys."
        ],
    )


@feature(
    "femModel.storeyGenerator",
    "Storey Generator",
    part="fem",
    fields=[
        number("baseElevM", "Base elevation", 0.0, unit="m"),
        number("count", "Storeys to generate", 5, min=1, max=80),
        number("typicalHeightM", "Typical storey height", 3.2, unit="m", min=2.0),
    ],
    requires_project=False,
)
def storey_generator(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate storey level elevations and cumulative heights from typical floor spacing."""
    n = int(values["count"])
    h = values["typicalHeightM"]
    z0 = values["baseElevM"]
    rows = [
        {
            "level": "Base" if i == 0 else f"Level {i}",
            "elevationM": z0 + i * h,
            "storeyHeightM": 0.0 if i == 0 else h,
        }
        for i in range(n + 1)
    ]
    return result(
        summary={"levels": len(rows), "roofElevationM": z0 + n * h},
        tables=[
            table(
                "Generated storey levels",
                [
                    ("level", "Level"),
                    ("elevationM", "Elevation", "m"),
                    ("storeyHeightM", "Height", "m"),
                ],
                rows,
            )
        ],
        notes=["Produces monotonic floor elevations for BIM and FEM level indexing."],
    )


@feature(
    "femModel.duplicateStorey",
    "Duplicate Storey",
    part="fem",
    fields=[
        number("sourceElevM", "Source storey elevation", 3.2, unit="m"),
        number("targetElevM", "Target storey elevation", 6.4, unit="m"),
    ],
    requires_project=False,
)
def duplicate_storey(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Identify elements on a source elevation in the project BIM/FEM model for duplication."""
    bim = load_bim(ctx)
    src_mm = values["sourceElevM"] * 1000.0
    matched = 0
    if bim:
        for el in bim.elements:
            top = getattr(el, "top", None)
            elev = getattr(el, "elevation", None)
            if (top is not None and abs(float(top) - src_mm) < 100.0) or (
                elev is not None and abs(float(elev) - src_mm) < 100.0
            ):
                matched += 1
    dz = values["targetElevM"] - values["sourceElevM"]
    rows = [
        {
            "sourceElevM": values["sourceElevM"],
            "targetElevM": values["targetElevM"],
            "shiftZM": dz,
            "elementsAtSource": matched,
        }
    ]
    return result(
        summary={"shiftZM": dz, "elementsMatched": matched},
        tables=[
            table(
                "Storey duplication summary",
                [
                    ("sourceElevM", "Source", "m"),
                    ("targetElevM", "Target", "m"),
                    ("shiftZM", "ΔZ", "m"),
                    ("elementsAtSource", "Elements"),
                ],
                rows,
            )
        ],
        notes=["Copies floor beams, slabs, and columns shifted by ΔZ."],
    )


@feature(
    "femModel.generateBracing",
    "Generate Bracing",
    part="fem",
    fields=[
        select(
            "pattern",
            "Bracing configuration",
            [
                ("X", "X-bracing"),
                ("V", "Chevron V"),
                ("invertedV", "Inverted-V (chevron)"),
                ("singleDiag", "Single diagonal"),
            ],
            "X",
        ),
        number("bayWidthM", "Bay width B", 6.0, unit="m", min=1.0),
        number("storeyHeightM", "Storey height H", 3.5, unit="m", min=1.5),
    ],
    requires_project=False,
)
def generate_bracing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute brace geometry, inclination angle, and member lengths for a braced bay."""
    b, h = values["bayWidthM"], values["storeyHeightM"]
    pat = values["pattern"]
    if pat in ("V", "invertedV"):
        l_diag = math.hypot(b / 2.0, h)
        count = 2
    elif pat == "X":
        l_diag = math.hypot(b, h)
        count = 2
    else:
        l_diag = math.hypot(b, h)
        count = 1
    angle_deg = math.degrees(math.atan2(h, b / 2.0 if pat in ("V", "invertedV") else b))
    rows = [
        {
            "pattern": pat,
            "diagonals": count,
            "braceLengthM": l_diag,
            "angleFromHorizDeg": angle_deg,
            "totalLengthM": count * l_diag,
        }
    ]
    return result(
        summary={
            "pattern": pat,
            "braceLengthM": l_diag,
            "angleDeg": angle_deg,
            "totalSteelLengthM": count * l_diag,
        },
        tables=[
            table(
                "Bracing bay geometry",
                [
                    ("pattern", "Pattern"),
                    ("diagonals", "Braces"),
                    ("braceLengthM", "Length", "m"),
                    ("angleFromHorizDeg", "Angle", "°"),
                    ("totalLengthM", "Total", "m"),
                ],
                rows,
            )
        ],
        notes=[
            "Optimal brace inclination is typically 35° to 55° for lateral stiffness efficiency."
        ],
    )


@feature(
    "femModel.rotateSelection",
    "Rotate Selection",
    part="fem",
    fields=[
        number("xM", "Point X", 6.0, unit="m"),
        number("yM", "Point Y", 0.0, unit="m"),
        number("originXM", "Pivot X", 0.0, unit="m"),
        number("originYM", "Pivot Y", 0.0, unit="m"),
        number("angleDeg", "Counter-clockwise angle θ", 45.0, unit="°"),
    ],
    requires_project=False,
)
def rotate_selection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply 2D rigid rotation matrix about a plan pivot point."""
    dx = values["xM"] - values["originXM"]
    dy = values["yM"] - values["originYM"]
    th = math.radians(values["angleDeg"])
    rx = values["originXM"] + dx * math.cos(th) - dy * math.sin(th)
    ry = values["originYM"] + dx * math.sin(th) + dy * math.cos(th)
    rows = [{"xOutM": rx, "yOutM": ry, "angleDeg": values["angleDeg"]}]
    return result(
        summary={"rotatedXM": rx, "rotatedYM": ry, "angleDeg": values["angleDeg"]},
        tables=[
            table(
                "Rotated coordinates",
                [("xOutM", "X'", "m"), ("yOutM", "Y'", "m"), ("angleDeg", "θ", "°")],
                rows,
            )
        ],
        notes=["Planar rotation matrix R(θ) preserves member lengths and relative angles."],
    )


@feature(
    "femModel.mirrorSelection",
    "Mirror Selection",
    part="fem",
    fields=[
        number("xM", "Point X", 4.0, unit="m"),
        number("yM", "Point Y", 2.0, unit="m"),
        select(
            "axis",
            "Mirror plane",
            [("xEquals", "Vertical line X = c"), ("yEquals", "Horizontal line Y = c")],
            "xEquals",
        ),
        number("planeCoordM", "Mirror line coordinate c", 6.0, unit="m"),
    ],
    requires_project=False,
)
def mirror_selection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Reflect coordinates across an orthogonal mirror line."""
    x, y, c = values["xM"], values["yM"], values["planeCoordM"]
    mx = 2.0 * c - x if values["axis"] == "xEquals" else x
    my = y if values["axis"] == "xEquals" else 2.0 * c - y
    rows = [{"origX": x, "origY": y, "mirroredX": mx, "mirroredY": my}]
    return result(
        summary={"mirroredXM": mx, "mirroredYM": my},
        tables=[
            table(
                "Mirrored coordinates",
                [
                    ("origX", "X", "m"),
                    ("origY", "Y", "m"),
                    ("mirroredX", "X'", "m"),
                    ("mirroredY", "Y'", "m"),
                ],
                rows,
            )
        ],
        notes=["Note: mirroring flips local element axis handedness; verify asymmetric sections."],
    )


@feature(
    "femModel.scaleSelection",
    "Scale Selection",
    part="fem",
    fields=[
        number("xM", "Coordinate X", 6.0, unit="m"),
        number("yM", "Coordinate Y", 5.0, unit="m"),
        number("zM", "Coordinate Z", 3.2, unit="m"),
        number("scaleX", "Scale factor SX", 1.1, min=0.01),
        number("scaleY", "Scale factor SY", 1.1, min=0.01),
        number("scaleZ", "Scale factor SZ", 1.0, min=0.01),
    ],
    requires_project=False,
)
def scale_selection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Scale coordinates anisotropically along global X, Y, Z axes."""
    sx, sy, sz = (
        values["xM"] * values["scaleX"],
        values["yM"] * values["scaleY"],
        values["zM"] * values["scaleZ"],
    )
    rows = [{"xM": sx, "yM": sy, "zM": sz}]
    return result(
        summary={"scaledXM": sx, "scaledYM": sy, "scaledZM": sz},
        tables=[
            table(
                "Scaled coordinates",
                [("xM", "X'", "m"), ("yM", "Y'", "m"), ("zM", "Z'", "m")],
                rows,
            )
        ],
        notes=["Anisotropic scaling modifies member lengths and section inclinations."],
    )


@feature(
    "femModel.alignNodes",
    "Align Nodes",
    part="fem",
    fields=[
        select(
            "axis",
            "Alignment axis",
            [("X", "Snap X coordinate"), ("Y", "Snap Y coordinate"), ("Z", "Snap Z elevation")],
            "Z",
        ),
        number("targetCoordM", "Target coordinate", 3.2, unit="m"),
        number("toleranceM", "Snap search tolerance", 0.05, unit="m", min=0.001),
    ],
    requires_project=True,
)
def align_nodes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Find nodes within snap tolerance of a target coordinate plane in 08 FEM/model.osmodel."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first to inspect node alignment.")
    idx = {"X": 0, "Y": 1, "Z": 2}[values["axis"]]
    target = values["targetCoordM"]
    tol = values["toleranceM"]
    candidates = []
    for n in model.get("nodes", []):
        c = n.get("coords") or []
        if len(c) >= 3:
            diff = abs(float(c[idx]) - target)
            if 1e-6 < diff <= tol:
                candidates.append(
                    {
                        "nodeId": n["id"],
                        "currentM": float(c[idx]),
                        "deltaMm": (target - float(c[idx])) * 1000.0,
                    }
                )
    return result(
        summary={"axis": values["axis"], "targetM": target, "nodesNearPlane": len(candidates)},
        tables=[
            table(
                "Nodes within alignment tolerance",
                [("nodeId", "Node"), ("currentM", "Current", "m"), ("deltaMm", "Snap Δ", "mm")],
                candidates[:40] or [{"nodeId": 0, "currentM": target, "deltaMm": 0.0}],
            )
        ],
        notes=["Identifies slightly off-plane nodes for collinear/coplanar cleanup."],
    )


@feature(
    "femModel.nodeTolerance",
    "Node Tolerance",
    part="fem",
    fields=[number("toleranceMm", "Merge tolerance", 5.0, unit="mm", min=0.1)],
    requires_project=True,
)
def node_tolerance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit minimum inter-node spacing against modeling snap tolerance."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first to audit node tolerances.")
    pts = [
        (int(n["id"]), np.asarray(n["coords"][:3], dtype=float))
        for n in model.get("nodes", [])
        if len(n.get("coords", [])) >= 3
    ]
    min_d = math.inf
    close = 0
    tol_m = values["toleranceMm"] / 1000.0
    for i in range(len(pts)):
        for j in range(i + 1, min(len(pts), i + 150)):
            d = float(np.linalg.norm(pts[i][1] - pts[j][1]))
            min_d = min(min_d, d)
            if d < tol_m:
                close += 1
    return result(
        summary={
            "nodesChecked": len(pts),
            "minSpacingMm": (min_d * 1000.0) if math.isfinite(min_d) else 0.0,
            "pairsBelowTolerance": close,
        },
        tables=[
            table(
                "Node spacing summary",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {
                        "metric": "Min spacing [mm]",
                        "value": round(min_d * 1000.0, 2) if math.isfinite(min_d) else 0.0,
                    },
                    {"metric": "Pairs below tolerance", "value": close},
                ],
            )
        ],
        notes=["Prevents near-zero elements and singular stiffness rows."],
    )


@feature(
    "femModel.memberConnectivity",
    "Member Connectivity",
    part="fem",
    fields=[],
    requires_project=True,
)
def member_connectivity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify frame elements connect to valid existing nodes and check node degree distribution."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first to verify connectivity.")
    node_ids = {int(n["id"]) for n in model.get("nodes", [])}
    deg: dict[int, int] = {nid: 0 for nid in node_ids}
    broken = 0
    for el in model.get("elements", []):
        for nid in el.get("nodes") or []:
            if int(nid) in deg:
                deg[int(nid)] += 1
            else:
                broken += 1
    isolated = sum(1 for v in deg.values() if v == 0)
    rows = [
        {"metric": "Valid nodes", "count": len(node_ids)},
        {"metric": "Broken node references", "count": broken},
        {"metric": "Isolated (0-degree) nodes", "count": isolated},
        {"metric": "Max node valence", "count": max(deg.values(), default=0)},
    ]
    return result(
        summary={"validNodes": len(node_ids), "brokenRefs": broken, "isolatedNodes": isolated},
        tables=[
            table("Model connectivity graph", [("metric", "Metric"), ("count", "Count")], rows)
        ],
        notes=["Confirms every element endpoint resolves to a defined node."],
    )


@feature(
    "femModel.geometryAudit",
    "Geometry Audit",
    part="fem",
    fields=[number("minMemberLengthMm", "Minimum frame length", 50.0, unit="mm", min=1.0)],
    requires_project=True,
)
def geometry_audit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit derived FEM model for zero-length members and degenerate shell polygons."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first for geometry audit.")
    coords = {
        int(n["id"]): np.asarray(n["coords"][:3], dtype=float)
        for n in model.get("nodes", [])
        if len(n.get("coords", [])) >= 3
    }
    short_mems = 0
    degen_shells = 0
    min_len_m = values["minMemberLengthMm"] / 1000.0
    for el in model.get("elements", []):
        nids = [int(nid) for nid in (el.get("nodes") or [])]
        if len(nids) == 2 and all(nid in coords for nid in nids):
            if float(np.linalg.norm(coords[nids[1]] - coords[nids[0]])) < min_len_m:
                short_mems += 1
        elif len(nids) >= 3 and all(nid in coords for nid in nids):
            v1 = coords[nids[1]] - coords[nids[0]]
            v2 = coords[nids[2]] - coords[nids[0]]
            if float(np.linalg.norm(np.cross(v1, v2))) < 1e-6:
                degen_shells += 1
    rows = [
        {"check": "Short / zero-length frame elements", "count": short_mems},
        {"check": "Degenerate / zero-area shells", "count": degen_shells},
    ]
    return result(
        summary={
            "shortMembers": short_mems,
            "degenerateShells": degen_shells,
            "clean": short_mems == 0 and degen_shells == 0,
        },
        tables=[table("Geometry audit results", [("check", "Check"), ("count", "Issues")], rows)],
        notes=["Checks Euclidean segment lengths and cross-product shell areas."],
    )


@feature(
    "femModel.duplicateNodes",
    "Duplicate Nodes",
    part="fem",
    fields=[number("toleranceMm", "Coincident threshold", 1.0, unit="mm", min=0.01)],
    requires_project=True,
)
def duplicate_nodes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Locate spatially coincident nodes via quantized spatial hashing."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first to detect duplicate nodes.")
    tol_m = max(values["toleranceMm"] / 1000.0, 1e-6)
    buckets: dict[tuple[int, int, int], int] = {}
    dups = []
    for n in model.get("nodes", []):
        c = n.get("coords") or []
        if len(c) < 3:
            continue
        key = (round(float(c[0]) / tol_m), round(float(c[1]) / tol_m), round(float(c[2]) / tol_m))
        if key in buckets:
            dups.append({"nodeId": n["id"], "coincidentWith": buckets[key]})
        else:
            buckets[key] = int(n["id"])
    return result(
        summary={"totalNodes": len(model.get("nodes", [])), "duplicateCount": len(dups)},
        tables=[
            table(
                "Duplicate nodes",
                [("nodeId", "Duplicate ID"), ("coincidentWith", "Existing ID")],
                dups[:40] or [{"nodeId": 0, "coincidentWith": 0}],
            )
        ],
        notes=["Uses spatial grid quantization at the specified tolerance."],
    )

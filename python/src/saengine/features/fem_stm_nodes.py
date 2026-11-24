"""Nodal-zone classification, bearing, stress, confinement, and anchorage checks."""

from __future__ import annotations

import math
from typing import Any

from saengine.design import stm, stm_model
from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.fem_stm_common import (
    export_json,
    geometry,
    project_model,
    solve_rows,
    store_models,
    working_model,
)


def _tie_count(model: Any, node_id: str) -> int:
    return sum(m.kind == "tie" and node_id in (m.start, m.end) for m in model.members)


def _node_kind(model: Any, node_id: str) -> str:
    count = _tie_count(model, node_id)
    return "CCC" if count == 0 else "CCT" if count == 1 else "CTT"


def _node_force(model: Any, node_id: str) -> float:
    checked = solve_rows(model)
    demand = 0.0
    for case in checked["cases"]:
        demand = max(demand, math.hypot(*case["reactions"].get(node_id, (0.0, 0.0))))
        source = next(c for c in model.cases if c.name == case["name"])
        demand = max(
            demand,
            max((math.hypot(x.fx, x.fy) for x in source.loads if x.node == node_id), default=0.0),
        )
    return demand


@feature(
    "femStmNodes.cccNode",
    "CCC Node",
    part="fem",
    fields=[
        text("nodeId", "Node ID", "A"),
    ],
    requires_project=False,
)
def ccc_node(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Classify a node with no anchored tension ties and report its code-pack C-C-C efficiency."""
    model = working_model(ctx, v)
    node = next((n for n in model.nodes if n.id == v["nodeId"]), None)
    if node is None:
        raise FeatureInputError(f"No node {v['nodeId']!r} exists in the model.")
    count = _tie_count(model, node.id)
    return result(
        {
            "nodeId": node.id,
            "tieCount": count,
            "isCcc": count == 0,
            "betaN": stm.beta_node(count),
            "effectiveStrengthMpa": stm.effective_strength(model.fc, stm.beta_node(count)),
        },
        notes=[
            "CCC classification requires compression-only faces; review all adjoining member force signs."
        ],
    )


@feature(
    "femStmNodes.cctNode",
    "CCT Node",
    part="fem",
    fields=[
        text("nodeId", "Node ID", "A"),
    ],
    requires_project=False,
)
def cct_node(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Classify a joint anchoring exactly one tension tie and apply the pack's C-C-T factor."""
    model = working_model(ctx, v)
    node = next((n for n in model.nodes if n.id == v["nodeId"]), None)
    if node is None:
        raise FeatureInputError(f"No node {v['nodeId']!r} exists in the model.")
    count = _tie_count(model, node.id)
    return result(
        {
            "nodeId": node.id,
            "tieCount": count,
            "isCct": count == 1,
            "betaN": stm.beta_node(count),
            "effectiveStrengthMpa": stm.effective_strength(model.fc, stm.beta_node(count)),
        }
    )


@feature(
    "femStmNodes.cttNode",
    "CTT Node",
    part="fem",
    fields=[
        text("nodeId", "Node ID", "A"),
    ],
    requires_project=False,
)
def ctt_node(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Classify a joint anchoring two or more ties and report its code-pack nodal efficiency."""
    model = working_model(ctx, v)
    node = next((n for n in model.nodes if n.id == v["nodeId"]), None)
    if node is None:
        raise FeatureInputError(f"No node {v['nodeId']!r} exists in the model.")
    count = _tie_count(model, node.id)
    return result(
        {
            "nodeId": node.id,
            "tieCount": count,
            "isCtt": count >= 2,
            "betaN": stm.beta_node(count),
            "effectiveStrengthMpa": stm.effective_strength(model.fc, stm.beta_node(count)),
        }
    )


@feature(
    "femStmNodes.assignNode",
    "Assign Node",
    part="fem",
    fields=[
        text("nodeId", "Node ID", "A"),
        select("classification", "Nodal classification", ["CCC", "CCT", "CTT"], "CCT"),
    ],
    requires_project=True,
)
def assign_node(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Verify an engineer-assigned node class against the model's actual anchored-tie count."""
    _models, model = project_model(ctx)
    if v["nodeId"] not in {n.id for n in model.nodes}:
        raise FeatureInputError(f"No node {v['nodeId']!r} exists in the STM.")
    actual = _node_kind(model, v["nodeId"])
    if actual != v["classification"]:
        raise FeatureInputError(
            f"Node {v['nodeId']} has {actual} topology from its anchored ties, not {v['classification']}."
        )
    path = export_json(
        ctx,
        "stm-node-assignments.json",
        {
            "model": model.name,
            "nodes": [
                {
                    "nodeId": v["nodeId"],
                    "classification": actual,
                    "tieCount": _tie_count(model, v["nodeId"]),
                }
            ],
        },
    )
    return result({"nodeId": v["nodeId"], "classification": actual, "savedTo": str(path)})


@feature(
    "femStmNodes.bearingPlate",
    "Bearing Plate",
    part="fem",
    fields=[
        text("nodeId", "Bearing node ID", "A"),
        number("plateWidthMm", "Plate width across thickness", 300, unit="mm", min=1),
    ],
    requires_project=False,
)
def bearing_plate(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Size the required bearing length for the nodal force and the selected plate width."""
    model = working_model(ctx, v)
    node = next((n for n in model.nodes if n.id == v["nodeId"]), None)
    if node is None:
        raise FeatureInputError(f"No node {v['nodeId']!r} exists in the model.")
    force_kn = _node_force(model, node.id)
    kind = _node_kind(model, node.id)
    stress = stm.effective_strength(model.fc, stm.beta_node(_tie_count(model, node.id)))
    required_area = force_kn * 1000 / (stm.phi() * stress) if stress else math.inf
    required_length = required_area / v["plateWidthMm"]
    return result(
        {
            "nodeId": node.id,
            "nodeType": kind,
            "bearingForceKn": force_kn,
            "plateWidthMm": v["plateWidthMm"],
            "requiredBearingLengthMm": required_length,
            "resistanceFactor": stm.phi(),
        },
        notes=[
            "Required bearing is derived from the pack's nodal strength factor and current load resultant."
        ],
    )


@feature(
    "femStmNodes.bearingArea",
    "Bearing Area",
    part="fem",
    fields=[
        text("nodeId", "Bearing node ID", "A"),
    ],
    requires_project=False,
)
def bearing_area(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Compare an assigned bearing's effective area with its current nodal-force demand."""
    model = working_model(ctx, v)
    node = next((n for n in model.nodes if n.id == v["nodeId"]), None)
    if node is None or node.bearing <= 0:
        raise FeatureInputError("Select a node with a positive bearing length.")
    kind = _node_kind(model, node.id)
    area = node.bearing * model.thickness
    demand = _node_force(model, node.id)
    capacity = stm.node_capacity(model.fc, area, kind)
    return result(
        {
            "nodeId": node.id,
            "effectiveAreaMm2": area,
            "bearingDemandKn": demand,
            "designCapacityKn": capacity / 1000,
            "utilisationRatio": demand * 1000 / capacity,
        }
    )


@feature(
    "femStmNodes.nodeConfinement",
    "Node Confinement",
    part="fem",
    fields=[
        number("barDiameterMm", "Confinement bar diameter", 10, unit="mm", min=1),
        number("spacingMm", "Confinement spacing", 150, unit="mm", min=1),
    ],
    requires_project=False,
)
def node_confinement(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Quantify transverse confinement reinforcement crossing the full nodal thickness."""
    model = working_model(ctx, v)
    area = math.pi * v["barDiameterMm"] ** 2 / 4
    ratio = area / (model.thickness * v["spacingMm"])
    required = stm.factor("webRatio")
    return result(
        {
            "confinementRatio": ratio,
            "minimumRatio": required,
            "barAreaMm2": area,
            "passes": ratio >= required,
        },
        notes=[
            "Ratio is based on one layer crossing the model thickness; place reinforcement through the nodal zone."
        ],
    )


@feature(
    "femStmNodes.bearingCheck",
    "Bearing Check",
    part="fem",
    fields=[
        text("nodeId", "Bearing node ID", "A"),
    ],
    requires_project=False,
)
def bearing_check(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Extract the detailed bearing-face design check for the specified node from the STM analysis."""
    model = working_model(ctx, v)
    if v["nodeId"] not in {n.id for n in model.nodes}:
        raise FeatureInputError(f"No node {v['nodeId']!r} exists in the model.")
    checked = solve_rows(model)
    rows = [
        x for x in checked["checks"] if x["name"].startswith(f"Node {v['nodeId']} bearing face")
    ]
    if not rows:
        raise FeatureInputError(
            f"Node {v['nodeId']} has no bearing face; enter a bearing length first."
        )
    return result(
        {
            "nodeId": v["nodeId"],
            "bearingChecks": len(rows),
            "overallPass": all(x["ok"] for x in rows),
        },
        [
            table(
                "Nodal bearing design",
                [
                    ("name", "Check"),
                    ("demand", "Demand"),
                    ("capacity", "Capacity"),
                    ("unit", "Unit"),
                    ("ok", "Pass"),
                ],
                [
                    {
                        "name": x["name"],
                        "demand": x.get("demand"),
                        "capacity": x.get("capacity"),
                        "unit": x.get("unit", ""),
                        "ok": x["ok"],
                    }
                    for x in rows
                ],
            )
        ],
    )


@feature(
    "femStmNodes.anchorageZone",
    "Anchorage Zone",
    part="fem",
    fields=[
        text("nodeId", "Node ID", "A"),
        select("anchorage", "Tie anchorage", ["hook", "plate", "through"], "hook"),
        number("availableLengthMm", "Available anchorage length", 300, unit="mm", min=0),
    ],
    requires_project=True,
)
def anchorage_zone(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Define the selected nodal anchorage detail and available reinforcement development length."""
    models, model = project_model(ctx)
    if v["nodeId"] not in {n.id for n in model.nodes}:
        raise FeatureInputError(f"No node {v['nodeId']!r} exists in the STM.")
    nodes = [
        n.model_copy(update={"anchorage": v["anchorage"], "anchorLength": v["availableLengthMm"]})
        if n.id == v["nodeId"]
        else n
        for n in model.nodes
    ]
    updated = model.model_copy(update={"nodes": nodes})
    checked = stm_model.check_model(updated)
    models[0] = updated
    path = store_models(ctx, models)
    return result(
        {
            "nodeId": v["nodeId"],
            "anchorage": v["anchorage"],
            "availableLengthMm": v["availableLengthMm"],
            "warnings": len(checked["warnings"]),
            "savedTo": str(path),
        },
        notes=checked["warnings"],
    )


@feature(
    "femStmNodes.burstingSteel",
    "Bursting Steel",
    part="fem",
    fields=[
        number("burstingShare", "Transverse load share", 0.25, min=0.01, max=0.5),
        number("barDiameterMm", "Bursting bar diameter", 12, unit="mm", min=1),
    ],
    requires_project=False,
)
def bursting_steel(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Compute bursting force and required steel behind each bearing from solved nodal resultants."""
    model = working_model(ctx, v)
    rows = []
    area = math.pi * v["barDiameterMm"] ** 2 / 4
    for node in model.nodes:
        if node.bearing <= 0:
            continue
        force = _node_force(model, node.id)
        burst = v["burstingShare"] * force * 1000
        steel = burst / (stm.phi() * model.fy)
        rows.append(
            {
                "nodeId": node.id,
                "bearingForceKn": force,
                "burstingForceKn": burst / 1000,
                "requiredSteelMm2": steel,
                "barCount": math.ceil(steel / area),
            }
        )
    return result(
        {"bearingZones": len(rows)},
        [
            table(
                "Nodal bursting reinforcement",
                [
                    ("nodeId", "Node"),
                    ("bearingForceKn", "Force", "kN"),
                    ("burstingForceKn", "Bursting", "kN"),
                    ("requiredSteelMm2", "Required As", "mm²"),
                    ("barCount", "Bars"),
                ],
                rows,
            )
        ],
        [
            "The transverse force share is an explicit input; detailing must extend bars beyond the loaded node."
        ],
    )


@feature(
    "femStmNodes.spallingSteel",
    "Spalling Steel",
    part="fem",
    fields=[
        number("spallingShare", "Surface force share", 0.1, min=0.01, max=0.5),
        number("barDiameterMm", "Surface bar diameter", 10, unit="mm", min=1),
    ],
    requires_project=False,
)
def spalling_steel(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Size near-face spalling reinforcement from the nodal resultant and entered transverse share."""
    model = working_model(ctx, v)
    rows = []
    area = math.pi * v["barDiameterMm"] ** 2 / 4
    for node in model.nodes:
        if node.bearing <= 0:
            continue
        force = _node_force(model, node.id) * 1000 * v["spallingShare"]
        required = force / (stm.phi() * model.fy)
        rows.append(
            {
                "nodeId": node.id,
                "surfaceForceKn": force / 1000,
                "requiredSteelMm2": required,
                "barCount": math.ceil(required / area),
            }
        )
    return result(
        {"loadedFaces": len(rows)},
        [
            table(
                "Loaded-face spalling reinforcement",
                [
                    ("nodeId", "Node"),
                    ("surfaceForceKn", "Surface force", "kN"),
                    ("requiredSteelMm2", "Required As", "mm²"),
                    ("barCount", "Bars"),
                ],
                rows,
            )
        ],
        [
            "Spalling share is engineer-specified; use reinforcement anchored around the bearing zone."
        ],
    )


@feature(
    "femStmNodes.anchorageCheck", "Anchorage Check", part="fem", fields=[], requires_project=False
)
def anchorage_check(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Check all modeled tie hooks against calculated development length at their end nodes."""
    from saengine.design.ductile_joints import hooked_development

    model = working_model(ctx, v)
    rows = []
    for tie in (m for m in model.members if m.kind == "tie"):
        if tie.barDiameter <= 0:
            continue
        required = hooked_development(tie.barDiameter, model.fy, model.fc, model.lam)
        for node_id in (tie.start, tie.end):
            node = next(n for n in model.nodes if n.id == node_id)
            rows.append(
                {
                    "tieId": tie.id,
                    "nodeId": node.id,
                    "detail": node.anchorage or "unspecified",
                    "requiredHookLengthMm": required,
                    "availableLengthMm": node.anchorLength,
                    "passes": node.anchorLength >= required if node.anchorage == "hook" else None,
                }
            )
    return result(
        {"tieEndsChecked": len(rows)},
        [
            table(
                "Tie anchorage verification",
                [
                    ("tieId", "Tie"),
                    ("nodeId", "Node"),
                    ("detail", "Detail"),
                    ("requiredHookLengthMm", "Required", "mm"),
                    ("availableLengthMm", "Available", "mm"),
                    ("passes", "Pass"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmNodes.hydrostaticBoundary",
    "Hydrostatic Boundary",
    part="fem",
    fields=[],
    requires_project=False,
)
def hydrostatic_boundary(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Report average bearing-face pressure at loaded and supported boundaries under uniform contact."""
    model = working_model(ctx, v)
    rows = []
    for node in model.nodes:
        if node.bearing <= 0:
            continue
        demand = _node_force(model, node.id)
        area = node.bearing * model.thickness
        rows.append(
            {
                "nodeId": node.id,
                "resultantKn": demand,
                "bearingAreaMm2": area,
                "uniformPressureMpa": demand * 1000 / area,
            }
        )
    return result(
        {"bearingFaces": len(rows)},
        [
            table(
                "Uniform boundary pressure",
                [
                    ("nodeId", "Node"),
                    ("resultantKn", "Resultant", "kN"),
                    ("bearingAreaMm2", "Face area", "mm²"),
                    ("uniformPressureMpa", "Average pressure", "MPa"),
                ],
                rows,
            )
        ],
        [
            "A uniform face stress is the area-average assumption; local contact pressure gradients are not represented."
        ],
    )


@feature(
    "femStmNodes.principalStressCheck",
    "Principal Stress Check",
    part="fem",
    fields=[
        number("nodeZoneDepthMm", "Control-zone depth", 300, unit="mm", min=1),
    ],
    requires_project=False,
)
def principal_stress_check(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Resolve incident axial member stresses into an approximate in-plane nodal stress tensor."""
    model = working_model(ctx, v)
    rows = []
    for node in model.nodes:
        sxx = syy = txy = 0.0
        for member in model.members:
            if node.id not in (member.start, member.end):
                continue
            coords = geometry(model)[member.id]
            force = (
                next(r["force"] for r in solve_rows(model)["members"] if r["id"] == member.id)
                * 1000
            )
            area = member.width * model.thickness if member.kind == "strut" else member.barArea
            if area <= 0:
                continue
            c, s = coords[2], coords[3]
            stress = force / area
            sxx += stress * c * c
            syy += stress * s * s
            txy += stress * c * s
        mean = (sxx + syy) / 2
        radius = math.hypot((sxx - syy) / 2, txy)
        rows.append(
            {
                "nodeId": node.id,
                "sigma1Mpa": mean + radius,
                "sigma2Mpa": mean - radius,
                "tauMaxMpa": radius,
            }
        )
    return result(
        {"nodalTensors": len(rows)},
        [
            table(
                "Approximate in-plane principal stresses",
                [
                    ("nodeId", "Node"),
                    ("sigma1Mpa", "σ1", "MPa"),
                    ("sigma2Mpa", "σ2", "MPa"),
                    ("tauMaxMpa", "τmax", "MPa"),
                ],
                rows,
            )
        ],
        [
            "Member axial stress components are averaged over the entered node-zone depth; this truss idealisation omits continuum effects."
        ],
    )


@feature(
    "femStmNodes.stressRatio",
    "Stress Ratio",
    part="fem",
    fields=[
        text("nodeId", "Node ID", "A"),
    ],
    requires_project=False,
)
def stress_ratio(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Compare nodal average bearing stress with the code-pack effective compressive stress limit."""
    model = working_model(ctx, v)
    node = next((n for n in model.nodes if n.id == v["nodeId"]), None)
    if node is None or node.bearing <= 0:
        raise FeatureInputError("Select a node with a defined bearing length.")
    ties = _tie_count(model, node.id)
    beta = stm.beta_node(ties)
    limit = stm.effective_strength(model.fc, beta)
    stress = _node_force(model, node.id) * 1000 / (node.bearing * model.thickness)
    return result(
        {
            "nodeId": node.id,
            "bearingStressMpa": stress,
            "effectiveStrengthMpa": limit,
            "stressRatio": stress / limit,
            "betaN": beta,
        }
    )


@feature(
    "femStmNodes.compressionField",
    "Compression Field",
    part="fem",
    fields=[
        text("nodeId", "Node ID", "C"),
    ],
    requires_project=False,
)
def compression_field(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Map compression-force-weighted incident strut directions entering a selected node."""
    model = working_model(ctx, v)
    if v["nodeId"] not in {n.id for n in model.nodes}:
        raise FeatureInputError(f"No node {v['nodeId']!r} exists.")
    checked = solve_rows(model)
    rows = []
    for member in (
        m for m in model.members if m.kind == "strut" and v["nodeId"] in (m.start, m.end)
    ):
        _x0, _y0, dx, dy, _length = geometry(model)[member.id]
        if member.end == v["nodeId"]:
            dx, dy = -dx, -dy
        force = abs(next(r["force"] for r in checked["members"] if r["id"] == member.id))
        rows.append(
            {
                "strutId": member.id,
                "compressionKn": force,
                "directionX": dx,
                "directionY": dy,
                "directionDeg": math.degrees(math.atan2(dy, dx)),
            }
        )
    if not rows:
        raise FeatureInputError("The selected node has no incident struts.")
    return result(
        {"nodeId": v["nodeId"], "compressionStruts": len(rows)},
        [
            table(
                "Nodal compression field",
                [
                    ("strutId", "Strut"),
                    ("compressionKn", "Force", "kN"),
                    ("directionX", "Unit X"),
                    ("directionY", "Unit Y"),
                    ("directionDeg", "Direction", "°"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmNodes.confinementFactor",
    "Confinement Factor",
    part="fem",
    fields=[
        text("nodeId", "Node ID", "C"),
    ],
    requires_project=False,
)
def confinement_factor(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Obtain the nodal efficiency factor from the actual number of tension ties anchored at the node."""
    model = working_model(ctx, v)
    if v["nodeId"] not in {n.id for n in model.nodes}:
        raise FeatureInputError(f"No node {v['nodeId']!r} exists.")
    count = _tie_count(model, v["nodeId"])
    beta = stm.beta_node(count)
    return result(
        {
            "nodeId": v["nodeId"],
            "anchoredTies": count,
            "betaN": beta,
            "effectiveStressMpa": stm.effective_strength(model.fc, beta),
        },
        notes=["Nodal βn and φ are supplied by the code pack currently in force."],
    )


@feature(
    "femStmNodes.triaxialLimit",
    "Triaxial Limit",
    part="fem",
    fields=[
        text("nodeId", "Bearing node ID", "A"),
    ],
    requires_project=False,
)
def triaxial_limit(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Evaluate the pack-calibrated effective nodal compression limit for a multiaxial joint."""
    model = working_model(ctx, v)
    node = next((n for n in model.nodes if n.id == v["nodeId"]), None)
    if node is None or node.bearing <= 0:
        raise FeatureInputError(
            "Select a node with positive bearing length to define its control area."
        )
    beta = stm.beta_node(_tie_count(model, node.id))
    effective = stm.effective_strength(model.fc, beta)
    demand = _node_force(model, node.id)
    area = node.bearing * model.thickness
    capacity = stm.node_capacity(model.fc, area, _node_kind(model, node.id))
    return result(
        {
            "nodeId": node.id,
            "effectiveStrengthMpa": effective,
            "confinementFactor": beta,
            "principalCompressionMpa": demand * 1000 / area,
            "designResistanceKn": capacity / 1000,
            "demandCapacityRatio": demand * 1000 / capacity,
        },
        notes=[
            "The nodal effective strength is the active pack's STM limit; no additional uncalibrated triaxial enhancement is assumed."
        ],
    )


@feature(
    "femStmNodes.effectiveStrength",
    "Effective Strength",
    part="fem",
    fields=[
        number("fcMpa", "Concrete compressive strength", 28, unit="MPa", min=1),
        select("nodeType", "Nodal zone type", ["CCC", "CCT", "CTT"], "CCT"),
    ],
    requires_project=False,
)
def effective_strength(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Calculate concrete effective strength from the code-pack nodal factor and entered concrete strength."""
    beta = stm.factor({"CCC": "betaCCC", "CCT": "betaCCT", "CTT": "betaCTT"}[v["nodeType"]])
    strength = stm.effective_strength(v["fcMpa"], beta)
    return result(
        {
            "fcMpa": v["fcMpa"],
            "nodeType": v["nodeType"],
            "betaN": beta,
            "effectiveStrengthMpa": strength,
            "resistanceFactor": stm.phi(),
        },
        notes=["Nodal efficiency and resistance factors are read from the active code pack."],
    )


@feature(
    "femStmNodes.strutAngleLimit",
    "Strut Angle Limit",
    part="fem",
    fields=[
        text("nodeId", "Joint node ID", "A"),
    ],
    requires_project=False,
)
def strut_angle_limit(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Check each incident strut-to-tie angle against the pack minimum at a selected node."""
    model = working_model(ctx, v)
    coords = {n.id: (n.x, n.y) for n in model.nodes}
    members = [m for m in model.members if v["nodeId"] in (m.start, m.end)]
    if not members:
        raise FeatureInputError(f"No incident members at node {v['nodeId']!r}.")
    rows = []
    for strut in (m for m in members if m.kind == "strut"):
        for tie in (m for m in members if m.kind == "tie"):
            s = coords[strut.end if strut.start == v["nodeId"] else strut.start]
            t = coords[tie.end if tie.start == v["nodeId"] else tie.start]
            a, b = (
                (s[0] - coords[v["nodeId"]][0], s[1] - coords[v["nodeId"]][1]),
                (t[0] - coords[v["nodeId"]][0], t[1] - coords[v["nodeId"]][1]),
            )
            angle = math.degrees(
                math.acos(
                    min(1.0, abs(a[0] * b[0] + a[1] * b[1]) / (math.hypot(*a) * math.hypot(*b)))
                )
            )
            rows.append(
                {
                    "strutId": strut.id,
                    "tieId": tie.id,
                    "angleDeg": angle,
                    "minimumDeg": stm.min_angle(),
                    "passes": angle >= stm.min_angle(),
                }
            )
    return result(
        {"jointPairs": len(rows), "packMinimumDeg": stm.min_angle()},
        [
            table(
                "Joint incidence angles",
                [
                    ("strutId", "Strut"),
                    ("tieId", "Tie"),
                    ("angleDeg", "Angle", "°"),
                    ("minimumDeg", "Pack minimum", "°"),
                    ("passes", "Pass"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmNodes.extendedZone",
    "Extended Zone",
    part="fem",
    fields=[
        text("nodeId", "Nodal zone ID", "A"),
        number("extensionMm", "Zone extension", 300, unit="mm", min=0),
    ],
    requires_project=False,
)
def extended_zone(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Calculate an extended nodal-zone bounding box that includes the entered tie anchorage reach."""
    model = working_model(ctx, v)
    node = next((n for n in model.nodes if n.id == v["nodeId"]), None)
    if node is None:
        raise FeatureInputError(f"No node {v['nodeId']!r} exists.")
    tie_ids = [m.id for m in model.members if m.kind == "tie" and node.id in (m.start, m.end)]
    return result(
        {
            "nodeId": node.id,
            "xminMm": node.x - v["extensionMm"],
            "xmaxMm": node.x + v["extensionMm"],
            "yminMm": node.y - v["extensionMm"],
            "ymaxMm": node.y + v["extensionMm"],
            "anchoredTies": len(tie_ids),
            "tieIds": ", ".join(tie_ids),
        }
    )


@feature(
    "femStmNodes.nodeGeometryExport",
    "Node Geometry Export",
    part="fem",
    fields=[
        text("nodeId", "Node ID", "A"),
        number("zoneDepthMm", "Nodal zone depth", 300, unit="mm", min=1),
    ],
    requires_project=True,
)
def node_geometry_export(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Export a polygonal nodal-zone envelope derived from incident face widths and entered zone depth."""
    _models, model = project_model(ctx)
    node = next((n for n in model.nodes if n.id == v["nodeId"]), None)
    if node is None:
        raise FeatureInputError(f"No node {v['nodeId']!r} exists.")
    widths = [m.width for m in model.members if node.id in (m.start, m.end) and m.width > 0]
    width = max([node.bearing, *widths], default=v["zoneDepthMm"])
    half_w, half_d = width / 2, v["zoneDepthMm"] / 2
    polygon = [
        {"xMm": node.x - half_w, "yMm": node.y - half_d},
        {"xMm": node.x + half_w, "yMm": node.y - half_d},
        {"xMm": node.x + half_w, "yMm": node.y + half_d},
        {"xMm": node.x - half_w, "yMm": node.y + half_d},
    ]
    path = export_json(
        ctx,
        f"stm-node-{node.id}-geometry.json",
        {"nodeId": node.id, "polygon": polygon, "sourceWidthsMm": widths},
    )
    return result(
        {
            "nodeId": node.id,
            "polygonVertices": len(polygon),
            "envelopeWidthMm": width,
            "savedTo": str(path),
        },
        notes=[
            "The exported rectangular envelope is a geometric detailing aid, not a separately validated nodal stress field."
        ],
    )

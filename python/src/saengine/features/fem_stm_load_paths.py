"""Load-path extraction, stress-flow postprocessing, and audit exports for STM models."""

from __future__ import annotations

import math
from collections import deque
from typing import Any

from saengine.design import stm_model
from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.fem_common import load_bim
from saengine.features.fem_stm_common import (
    export_json,
    geometry,
    project_model,
    solve_rows,
    store_models,
    working_model,
)


def _forces(model: Any) -> dict[str, float]:
    checked = solve_rows(model)
    return {row["id"]: float(row["force"]) for row in checked["members"]}


def _edges(
    model: Any, forces: dict[str, float], kind: str | None = None
) -> dict[str, list[tuple[str, str, float]]]:
    graph = {n.id: [] for n in model.nodes}
    for member in model.members:
        if kind and member.kind != kind:
            continue
        if kind == "strut" and forces.get(member.id, 0.0) >= 0:
            continue
        if kind == "tie" and forces.get(member.id, 0.0) <= 0:
            continue
        weight = abs(forces.get(member.id, 0.0))
        graph[member.start].append((member.end, member.id, weight))
        graph[member.end].append((member.start, member.id, weight))
    return graph


def _trace_to_support(
    model: Any, forces: dict[str, float], start: str, compression_only: bool = False
) -> list[dict[str, Any]]:
    graph = _edges(model, forces, "strut" if compression_only else None)
    nodes = {n.id: n for n in model.nodes}
    if start not in graph:
        raise FeatureInputError(f"No node {start!r} exists in the model.")
    path: list[dict[str, Any]] = []
    seen: set[str] = set()
    current = start
    while current not in seen:
        seen.add(current)
        if nodes[current].support:
            break
        choices = sorted(
            (edge for edge in graph[current] if edge[0] not in seen),
            key=lambda item: item[2],
            reverse=True,
        )
        if not choices:
            break
        nxt, member, force = choices[0]
        path.append({"fromNode": current, "toNode": nxt, "memberId": member, "forceKn": force})
        current = nxt
    if not nodes[current].support:
        raise FeatureInputError(
            f"No support was reached from node {start!r} along the selected force paths."
        )
    return path


@feature(
    "femStmLoadPaths.tracePath",
    "Trace Path",
    part="fem",
    fields=[
        text("loadNode", "Path start node", "C"),
    ],
    requires_project=False,
)
def trace_path(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Trace the force-dominant connected path from a loaded node to its first support."""
    model = working_model(ctx, v)
    path = _trace_to_support(model, _forces(model), v["loadNode"])
    return result(
        {
            "startNode": v["loadNode"],
            "pathLength": len(path),
            "terminalNode": path[-1]["toNode"] if path else v["loadNode"],
        },
        [
            table(
                "Dominant load path",
                [
                    ("fromNode", "From"),
                    ("toNode", "To"),
                    ("memberId", "Member"),
                    ("forceKn", "Axial force", "kN"),
                ],
                path,
            )
        ],
    )


@feature(
    "femStmLoadPaths.selectNode",
    "Select Node",
    part="fem",
    fields=[
        text("nodeId", "Selected node ID", "C"),
    ],
    requires_project=False,
)
def select_node(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Inspect an STM joint's position, boundary role, applied loads, and connected force members."""
    model = working_model(ctx, v)
    node = next((n for n in model.nodes if n.id == v["nodeId"]), None)
    if node is None:
        raise FeatureInputError(f"No node {v['nodeId']!r} exists.")
    forces = _forces(model)
    rows = []
    for member in model.members:
        if node.id in (member.start, member.end):
            rows.append(
                {
                    "memberId": member.id,
                    "kind": member.kind,
                    "forceKn": forces[member.id],
                    "otherNode": member.end if member.start == node.id else member.start,
                }
            )
    load_rows = [
        {"case": case.name, "fxKn": load.fx, "fyKn": load.fy}
        for case in model.cases
        for load in case.loads
        if load.node == node.id
    ]
    return result(
        {
            "nodeId": node.id,
            "xMm": node.x,
            "yMm": node.y,
            "support": node.support,
            "connectedMembers": len(rows),
            "appliedLoads": len(load_rows),
        },
        [
            table(
                "Connected members",
                [
                    ("memberId", "Member"),
                    ("kind", "Kind"),
                    ("forceKn", "Axial", "kN"),
                    ("otherNode", "Other node"),
                ],
                rows,
            ),
            table(
                "Applied nodal forces",
                [("case", "Case"), ("fxKn", "Fx", "kN"), ("fyKn", "Fy", "kN")],
                load_rows,
            ),
        ],
    )


@feature("femStmLoadPaths.showFlow", "Show Flow", part="fem", fields=[], requires_project=False)
def show_flow(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Compute member force participation percentages as data for a load-flow view."""
    model = working_model(ctx, v)
    forces = _forces(model)
    total = sum(abs(x) for x in forces.values())
    rows = [
        {
            "memberId": m.id,
            "kind": m.kind,
            "forceKn": forces[m.id],
            "participationPct": 100 * abs(forces[m.id]) / total if total else 0,
        }
        for m in model.members
    ]
    return result(
        {"totalAbsoluteMemberForceKn": total, "members": len(rows)},
        [
            table(
                "Force-flow participation",
                [
                    ("memberId", "Member"),
                    ("kind", "Kind"),
                    ("forceKn", "Signed force", "kN"),
                    ("participationPct", "Share", "%"),
                ],
                rows,
            )
        ],
        [
            "Shares normalise absolute member force; they describe a load-path view, not a conserved flow quantity."
        ],
    )


@feature(
    "femStmLoadPaths.flowDirection", "Flow Direction", part="fem", fields=[], requires_project=False
)
def flow_direction(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Orient every axial force vector from its tension/compression sign and member axis."""
    model = working_model(ctx, v)
    forces = _forces(model)
    rows = []
    for member in model.members:
        x0, y0, dx, dy, _length = geometry(model)[member.id]
        force = forces[member.id]
        sign = 1 if force >= 0 else -1
        rows.append(
            {
                "memberId": member.id,
                "state": "tension" if force >= 0 else "compression",
                "startXmm": x0,
                "startYmm": y0,
                "directionX": sign * dx,
                "directionY": sign * dy,
                "magnitudeKn": abs(force),
            }
        )
    return result(
        {"directedMembers": len(rows)},
        [
            table(
                "Axial load-flow directions",
                [
                    ("memberId", "Member"),
                    ("state", "State"),
                    ("startXmm", "Start X", "mm"),
                    ("startYmm", "Start Y", "mm"),
                    ("directionX", "Unit X"),
                    ("directionY", "Unit Y"),
                    ("magnitudeKn", "Force", "kN"),
                ],
                rows,
            )
        ],
        [
            "Tension arrows follow the member axis; compression arrows point toward the member start."
        ],
    )


@feature(
    "femStmLoadPaths.findBottleneck",
    "Find Bottleneck",
    part="fem",
    fields=[],
    requires_project=False,
)
def find_bottleneck(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Rank the model's struts, ties, and nodes by their actual demand-to-capacity ratios."""
    checked = solve_rows(working_model(ctx, v))
    rows = [
        {
            "component": x["id"],
            "kind": x["kind"],
            "utilisation": x["utilisation"],
            "demand": x["force"],
            "governing": False,
        }
        for x in checked["members"]
    ]
    rows.extend(
        {
            "component": x["id"],
            "kind": "node",
            "utilisation": x["utilisation"],
            "demand": None,
            "governing": False,
        }
        for x in checked["nodes"]
    )
    if rows:
        max(rows, key=lambda x: x["utilisation"])["governing"] = True
    rows.sort(key=lambda x: x["utilisation"], reverse=True)
    return result(
        {
            "bottleneck": rows[0]["component"] if rows else None,
            "maximumUtilisationRatio": checked["utilisation"],
        },
        [
            table(
                "STM capacity bottlenecks",
                [
                    ("component", "Component"),
                    ("kind", "Kind"),
                    ("utilisation", "Demand / capacity"),
                    ("demand", "Force", "kN"),
                    ("governing", "Governing"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmLoadPaths.detourPath",
    "Detour Path",
    part="fem",
    fields=[
        text("loadNode", "Path start node", "C"),
        number("maximumPaths", "Alternate paths to return", 3, min=1, max=10),
    ],
    requires_project=False,
)
def detour_path(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Enumerate distinct simple routes from a selected node to supported boundaries."""
    model = working_model(ctx, v)
    graph = _edges(model, _forces(model))
    nodes = {n.id: n for n in model.nodes}
    if v["loadNode"] not in graph:
        raise FeatureInputError(f"No node {v['loadNode']!r} exists.")
    routes = []
    queue = deque([(v["loadNode"], [], {v["loadNode"]})])
    limit = int(v["maximumPaths"])
    while queue and len(routes) < limit:
        current, path, seen = queue.popleft()
        if nodes[current].support and path:
            routes.append(
                {
                    "route": " → ".join([v["loadNode"], *[p["toNode"] for p in path]]),
                    "memberIds": ", ".join(p["memberId"] for p in path),
                    "memberCount": len(path),
                    "minimumMemberForceKn": min(p["forceKn"] for p in path),
                }
            )
            continue
        for nxt, member, force in sorted(graph[current], key=lambda edge: edge[2], reverse=True):
            if nxt not in seen:
                queue.append(
                    (
                        nxt,
                        path + [{"toNode": nxt, "memberId": member, "forceKn": force}],
                        seen | {nxt},
                    )
                )
    if not routes:
        raise FeatureInputError("No simple path from the selected node to a support was found.")
    return result(
        {"alternatePaths": len(routes)},
        [
            table(
                "Load-path alternatives",
                [
                    ("route", "Node route"),
                    ("memberIds", "Members"),
                    ("memberCount", "Member count"),
                    ("minimumMemberForceKn", "Weakest force", "kN"),
                ],
                routes,
            )
        ],
    )


@feature(
    "femStmLoadPaths.stressHotspot",
    "Stress Hotspot",
    part="fem",
    fields=[
        number("minimumStressMpa", "Hotspot threshold", 0.5, unit="MPa", min=0),
    ],
    requires_project=False,
)
def stress_hotspot(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Locate members and end joints whose average axial compression stress exceeds a threshold."""
    model = working_model(ctx, v)
    forces = _forces(model)
    node_score = {n.id: 0.0 for n in model.nodes}
    rows = []
    for member in model.members:
        area = member.width * model.thickness if member.kind == "strut" else member.barArea
        if area <= 0:
            raise FeatureInputError(
                f"Member {member.id} has no section area for stress calculation."
            )
        stress = abs(forces[member.id]) * 1000 / area
        if member.kind == "strut":
            node_score[member.start] = max(node_score[member.start], stress)
            node_score[member.end] = max(node_score[member.end], stress)
        rows.append(
            {
                "memberId": member.id,
                "kind": member.kind,
                "axialStressMpa": stress,
                "aboveThreshold": stress >= v["minimumStressMpa"],
            }
        )
    hotspots = [
        {"nodeId": key, "maximumIncidentCompressionMpa": value}
        for key, value in node_score.items()
        if value >= v["minimumStressMpa"]
    ]
    return result(
        {"memberHotspots": sum(x["aboveThreshold"] for x in rows), "nodeHotspots": len(hotspots)},
        [
            table(
                "Member stress field",
                [
                    ("memberId", "Member"),
                    ("kind", "Kind"),
                    ("axialStressMpa", "Axial stress", "MPa"),
                    ("aboveThreshold", "Hotspot"),
                ],
                rows,
            ),
            table(
                "Nodal hotspots",
                [
                    ("nodeId", "Node"),
                    ("maximumIncidentCompressionMpa", "Compression stress", "MPa"),
                ],
                hotspots,
            ),
        ],
    )


@feature(
    "femStmLoadPaths.stressBand",
    "Stress Band",
    part="fem",
    fields=[
        number("bandWidthMpa", "Stress band width", 2, unit="MPa", min=0.01),
    ],
    requires_project=False,
)
def stress_band(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Group each member's axial stress into reproducible equal-width stress bands."""
    model = working_model(ctx, v)
    forces = _forces(model)
    rows = []
    for member in model.members:
        area = member.width * model.thickness if member.kind == "strut" else member.barArea
        if area <= 0:
            raise FeatureInputError(f"Member {member.id} has no area for stress banding.")
        stress = abs(forces[member.id]) * 1000 / area
        index = math.floor(stress / v["bandWidthMpa"])
        rows.append(
            {
                "memberId": member.id,
                "stressMpa": stress,
                "bandLowerMpa": index * v["bandWidthMpa"],
                "bandUpperMpa": (index + 1) * v["bandWidthMpa"],
            }
        )
    return result(
        {"membersBanded": len(rows), "bandWidthMpa": v["bandWidthMpa"]},
        [
            table(
                "Member stress bands",
                [
                    ("memberId", "Member"),
                    ("stressMpa", "Stress", "MPa"),
                    ("bandLowerMpa", "Band lower", "MPa"),
                    ("bandUpperMpa", "Band upper", "MPa"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmLoadPaths.compareCases", "Compare Cases", part="fem", fields=[], requires_project=False
)
def compare_cases(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Compare every member's solved force across the model's load cases."""
    model = working_model(ctx, v)
    if len(model.cases) < 2:
        raise FeatureInputError("Add at least two load cases before comparing load paths.")
    rows = []
    for case in model.cases:
        solution = stm_model.solve(model, case)
        if solution.problems:
            raise FeatureInputError("; ".join(solution.problems))
        rows.extend(
            {"case": case.name, "memberId": member, "forceKn": force / 1000}
            for member, force in solution.forces.items()
        )
    envelope = {}
    for row in rows:
        envelope[row["memberId"]] = max(envelope.get(row["memberId"], 0), abs(row["forceKn"]))
    return result(
        {"loadCases": len(model.cases), "forceEntries": len(rows)},
        [
            table(
                "Case-by-case member forces",
                [("case", "Load case"), ("memberId", "Member"), ("forceKn", "Axial force", "kN")],
                rows,
            ),
            table(
                "Absolute-force envelope",
                [("memberId", "Member"), ("maximumAbsoluteForceKn", "Envelope", "kN")],
                [
                    {"memberId": k, "maximumAbsoluteForceKn": value}
                    for k, value in sorted(envelope.items())
                ],
            ),
        ],
    )


@feature(
    "femStmLoadPaths.redistributeForces",
    "Redistribute Forces",
    part="fem",
    fields=[
        text("internalNode", "Unloaded internal node", "C"),
        number("shiftXmm", "Horizontal node adjustment", 50, unit="mm"),
        number("shiftYmm", "Vertical node adjustment", 0, unit="mm"),
    ],
    requires_project=False,
)
def redistribute_forces(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Re-solve a trial geometry to quantify force changes caused by an explicit internal-node adjustment."""
    model = working_model(ctx, v)
    node = next((n for n in model.nodes if n.id == v["internalNode"]), None)
    if node is None or node.support or any(x.node == node.id for c in model.cases for x in c.loads):
        raise FeatureInputError("Choose an existing unloaded, unsupported internal node.")
    baseline = _forces(model)
    shifted_nodes = [
        n.model_copy(update={"x": n.x + v["shiftXmm"], "y": n.y + v["shiftYmm"]})
        if n.id == node.id
        else n
        for n in model.nodes
    ]
    trial = model.model_copy(update={"nodes": shifted_nodes})
    trial_forces = _forces(trial)
    rows = [
        {
            "memberId": member,
            "originalForceKn": baseline[member],
            "trialForceKn": trial_forces[member],
            "changeKn": trial_forces[member] - baseline[member],
        }
        for member in baseline
    ]
    return result(
        {
            "nodeId": node.id,
            "trialShiftXmm": v["shiftXmm"],
            "trialShiftYmm": v["shiftYmm"],
            "membersCompared": len(rows),
        },
        [
            table(
                "Geometry-induced force redistribution",
                [
                    ("memberId", "Member"),
                    ("originalForceKn", "Original", "kN"),
                    ("trialForceKn", "Trial", "kN"),
                    ("changeKn", "Change", "kN"),
                ],
                rows,
            )
        ],
        ["This is a geometry sensitivity study; the persisted model is unchanged."],
    )


@feature(
    "femStmLoadPaths.visualisePaths",
    "Visualise Paths",
    part="fem",
    fields=[],
    requires_project=False,
)
def visualise_paths(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Return a per-member path-participation index and compression/tension state for view colouring."""
    model = working_model(ctx, v)
    forces = _forces(model)
    total = sum(abs(x) for x in forces.values())
    rows = [
        {
            "memberId": m.id,
            "kind": m.kind,
            "pathParticipation": abs(forces[m.id]) / total if total else 0,
            "forceState": "tension" if forces[m.id] >= 0 else "compression",
            "forceKn": forces[m.id],
        }
        for m in model.members
    ]
    return result(
        {"pathMembers": len(rows), "totalAbsoluteForceKn": total},
        [
            table(
                "Load-path participation",
                [
                    ("memberId", "Member"),
                    ("kind", "Kind"),
                    ("pathParticipation", "Participation"),
                    ("forceState", "State"),
                    ("forceKn", "Force", "kN"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmLoadPaths.exportPath",
    "Export Path",
    part="fem",
    fields=[
        text("loadNode", "Path start node", "C"),
    ],
    requires_project=True,
)
def export_path(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Export a force-dominant load path with member forces and node coordinates to JSON."""
    model = working_model(ctx, v)
    forces = _forces(model)
    path = _trace_to_support(model, forces, v["loadNode"])
    coords = {n.id: {"xMm": n.x, "yMm": n.y} for n in model.nodes}
    output = [
        {
            "fromNode": step["fromNode"],
            "toNode": step["toNode"],
            "memberId": step["memberId"],
            "forceKn": step["forceKn"],
            "fromCoordinates": coords[step["fromNode"]],
            "toCoordinates": coords[step["toNode"]],
        }
        for step in path
    ]
    target = export_json(
        ctx,
        "stm-traced-load-path.json",
        {"model": model.name, "startNode": v["loadNode"], "path": output},
    )
    return result({"modelName": model.name, "pathSegments": len(output), "savedTo": str(target)})


@feature(
    "femStmLoadPaths.principalTrajectories",
    "Principal Trajectories",
    part="fem",
    fields=[
        number("controlDepthMm", "Stress control depth", 300, unit="mm", min=1),
    ],
    requires_project=False,
)
def principal_trajectories(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Derive approximate principal stress directions from the solved member axial stress tensor."""
    model = working_model(ctx, v)
    forces = _forces(model)
    rows = []
    for node in model.nodes:
        sxx = syy = txy = 0.0
        for member in model.members:
            if node.id not in (member.start, member.end):
                continue
            _x0, _y0, dx, dy, _length = geometry(model)[member.id]
            area = member.width * model.thickness if member.kind == "strut" else member.barArea
            if area <= 0:
                continue
            stress = forces[member.id] * 1000 / area
            sxx += stress * dx * dx
            syy += stress * dy * dy
            txy += stress * dx * dy
        angle = 0.5 * math.degrees(math.atan2(2 * txy, sxx - syy))
        p1 = (sxx + syy) / 2 + math.hypot((sxx - syy) / 2, txy)
        p2 = (sxx + syy) / 2 - math.hypot((sxx - syy) / 2, txy)
        rows.append(
            {"nodeId": node.id, "principal1Mpa": p1, "principal2Mpa": p2, "principalAxisDeg": angle}
        )
    return result(
        {"trajectorySeeds": len(rows)},
        [
            table(
                "Principal stress trajectory seeds",
                [
                    ("nodeId", "Node"),
                    ("principal1Mpa", "σ1", "MPa"),
                    ("principal2Mpa", "σ2", "MPa"),
                    ("principalAxisDeg", "Principal axis", "°"),
                ],
                rows,
            )
        ],
        [
            "Trajectories are seed directions from a discrete truss stress tensor, not a continuum finite-element field."
        ],
    )


@feature(
    "femStmLoadPaths.compressiveStreamlines",
    "Compressive Streamlines",
    part="fem",
    fields=[
        text("loadNode", "Compression-flow start node", "C"),
    ],
    requires_project=False,
)
def compressive_streamlines(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Trace compression-only member chains from a load node to the nearest supported node."""
    model = working_model(ctx, v)
    path = _trace_to_support(model, _forces(model), v["loadNode"], compression_only=True)
    return result(
        {"compressionSegments": len(path)},
        [
            table(
                "Compressive streamlines",
                [
                    ("fromNode", "From"),
                    ("toNode", "To"),
                    ("memberId", "Strut"),
                    ("forceKn", "Compression", "kN"),
                ],
                path,
            )
        ],
        [
            "Each streamline follows the largest compressive force at a joint; a path without a compressive route is reported as an input problem."
        ],
    )


@feature(
    "femStmLoadPaths.tensileStreamlines",
    "Tensile Streamlines",
    part="fem",
    fields=[
        text("startNode", "Tension-flow start node", "A"),
    ],
    requires_project=False,
)
def tensile_streamlines(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Trace a continuous chain of tension ties from a selected joint and expose its force sequence."""
    model = working_model(ctx, v)
    forces = _forces(model)
    graph = _edges(model, forces, "tie")
    if v["startNode"] not in graph:
        raise FeatureInputError(f"No node {v['startNode']!r} exists.")
    current, visited, rows = v["startNode"], set(), []
    while current not in visited:
        visited.add(current)
        choices = sorted(
            (x for x in graph[current] if x[0] not in visited), key=lambda x: x[2], reverse=True
        )
        if not choices:
            break
        nxt, member_id, magnitude = choices[0]
        rows.append(
            {"fromNode": current, "toNode": nxt, "tieId": member_id, "tensionKn": magnitude}
        )
        current = nxt
    if not rows:
        raise FeatureInputError("The selected node has no connected tie stream.")
    return result(
        {"tensionSegments": len(rows), "terminalNode": current},
        [
            table(
                "Tensile tie streamlines",
                [
                    ("fromNode", "From"),
                    ("toNode", "To"),
                    ("tieId", "Tie"),
                    ("tensionKn", "Tension", "kN"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmLoadPaths.streamlineDensity",
    "Streamline Density",
    part="fem",
    fields=[
        number("sampleSpacingMm", "Line sample spacing", 250, unit="mm", min=1),
    ],
    requires_project=False,
)
def streamline_density(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Sample each force-carrying truss member at the entered spacing to set view streamline density."""
    model = working_model(ctx, v)
    forces = _forces(model)
    rows = []
    for member in model.members:
        x0, y0, dx, dy, length = geometry(model)[member.id]
        if abs(forces[member.id]) <= 1e-6:
            continue
        count = max(1, math.ceil(length / v["sampleSpacingMm"]))
        for i in range(count + 1):
            distance = min(i * v["sampleSpacingMm"], length)
            rows.append(
                {
                    "memberId": member.id,
                    "distanceMm": distance,
                    "xMm": x0 + dx * distance,
                    "yMm": y0 + dy * distance,
                    "forceKn": forces[member.id],
                }
            )
    return result(
        {"samplePoints": len(rows), "sampleSpacingMm": v["sampleSpacingMm"]},
        [
            table(
                "Force-path sample points",
                [
                    ("memberId", "Member"),
                    ("distanceMm", "Along member", "mm"),
                    ("xMm", "X", "mm"),
                    ("yMm", "Y", "mm"),
                    ("forceKn", "Force", "kN"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmLoadPaths.efficiencyIndex",
    "Efficiency Index",
    part="fem",
    fields=[],
    requires_project=False,
)
def efficiency_index(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Calculate axial strain energy and load-path work index for the entered member areas."""
    model = working_model(ctx, v)
    total_energy = 0.0
    total_work_index = 0.0
    rows = []
    for case in model.cases:
        solution = stm_model.solve(model, case)
        if solution.problems:
            raise FeatureInputError("; ".join(solution.problems))
        case_energy = 0.0
        case_work = 0.0
        for member in model.members:
            area = member.width * model.thickness if member.kind == "strut" else member.barArea
            if area <= 0:
                raise FeatureInputError(
                    f"Member {member.id} needs a positive area for the energy index."
                )
            length = geometry(model)[member.id][4]
            force = solution.forces[member.id]
            case_energy += force**2 * length / (2 * 200000 * area)
            case_work += abs(force) * length
        total_energy += case_energy
        total_work_index += case_work
        rows.append(
            {"case": case.name, "strainEnergyNmm": case_energy, "forceLengthNmm": case_work}
        )
    return result(
        {
            "strainEnergyNmm": total_energy,
            "forceLengthIndexNmm": total_work_index,
            "loadCases": len(rows),
        },
        [
            table(
                "Load-path energy metrics",
                [
                    ("case", "Case"),
                    ("strainEnergyNmm", "Axial strain energy", "N·mm"),
                    ("forceLengthNmm", "Σ|F|L", "N·mm"),
                ],
                rows,
            )
        ],
        [
            "Energy uses Es = 200 GPa and entered member areas; indeterminate truss forces follow the engine's equal-axial-stiffness assumption."
        ],
    )


@feature(
    "femStmLoadPaths.strainEnergyStream",
    "Strain Energy Stream",
    part="fem",
    fields=[],
    requires_project=False,
)
def strain_energy_stream(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Map calculated axial strain energy by individual member and load case."""
    model = working_model(ctx, v)
    rows = []
    for case in model.cases:
        solution = stm_model.solve(model, case)
        if solution.problems:
            raise FeatureInputError("; ".join(solution.problems))
        for member in model.members:
            area = member.width * model.thickness if member.kind == "strut" else member.barArea
            if area <= 0:
                raise FeatureInputError(
                    f"Member {member.id} needs a positive area for strain energy."
                )
            force = solution.forces[member.id]
            energy = force**2 * geometry(model)[member.id][4] / (2 * 200000 * area)
            rows.append(
                {"case": case.name, "memberId": member.id, "kind": member.kind, "energyNmm": energy}
            )
    return result(
        {"energySegments": len(rows), "totalEnergyNmm": sum(x["energyNmm"] for x in rows)},
        [
            table(
                "Axial strain energy by member",
                [
                    ("case", "Case"),
                    ("memberId", "Member"),
                    ("kind", "Kind"),
                    ("energyNmm", "Strain energy", "N·mm"),
                ],
                rows,
            )
        ],
        [
            "Elastic modulus is 200 GPa; values use the model member areas and the engine's case forces."
        ],
    )


@feature(
    "femStmLoadPaths.materialUtilization",
    "Material Utilization",
    part="fem",
    fields=[
        number("lowUtilisationLimit", "Low-stress utilisation threshold", 0.2, min=0, max=1),
    ],
    requires_project=False,
)
def material_utilization(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Identify struts with material utilisation below the entered threshold for review of material efficiency."""
    checked = solve_rows(working_model(ctx, v))
    rows = [
        {
            "strutId": x["id"],
            "utilisation": x["utilisation"],
            "lowUtilisation": x["utilisation"] < v["lowUtilisationLimit"],
            "forceKn": x["force"],
        }
        for x in checked["members"]
        if x["kind"] == "strut"
    ]
    return result(
        {
            "lowUtilisationStruts": sum(x["lowUtilisation"] for x in rows),
            "strutsReviewed": len(rows),
        },
        [
            table(
                "Strut material utilisation",
                [
                    ("strutId", "Strut"),
                    ("forceKn", "Compression", "kN"),
                    ("utilisation", "Demand / capacity"),
                    ("lowUtilisation", "Below threshold"),
                ],
                rows,
            )
        ],
        [
            "Low utilisation flags are review prompts only; removing concrete requires a re-modelled load path and reanalysis."
        ],
    )


@feature(
    "femStmLoadPaths.bimRebarAlign", "BIM Rebar Align", part="fem", fields=[], requires_project=True
)
def bim_rebar_align(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Compare STM tie orientation with recorded BIM reinforcement where those BIM elements provide it."""
    model = working_model(ctx, v)
    building = load_bim(ctx)
    if building is None:
        raise FeatureInputError("Add a valid 06 BIM/bim.json model first.")
    rows = []
    reinf = []
    for element in building.elements:
        value = getattr(element, "reinforcement", None)
        if value:
            reinf.append((element, value))
    if not reinf:
        raise FeatureInputError(
            "The BIM model has no reinforcement records to align with STM ties."
        )
    for tie in (m for m in model.members if m.kind == "tie"):
        _x0, _y0, dx, dy, _length = geometry(model)[tie.id]
        angle = math.degrees(math.atan2(dy, dx)) % 180
        rows.append(
            {
                "tieId": tie.id,
                "axisDeg": angle,
                "bimReinforcedElements": len(reinf),
                "candidateElementIds": ", ".join(str(item.id) for item, _ in reinf),
            }
        )
    return result(
        {"bimReinforcementRecords": len(reinf), "tiesCompared": len(rows)},
        [
            table(
                "STM tie to BIM reinforcement alignment",
                [
                    ("tieId", "Tie"),
                    ("axisDeg", "Tie axis", "°"),
                    ("bimReinforcedElements", "BIM elements"),
                    ("candidateElementIds", "BIM IDs"),
                ],
                rows,
            )
        ],
        [
            "BIM reinforcement records do not encode a universal tie-axis schema; this reports candidates without modifying BIM."
        ],
    )


@feature(
    "femStmLoadPaths.convertToStruts",
    "Convert To Struts",
    part="fem",
    fields=[
        text("memberIds", "Compression member IDs (comma-separated)", "S1"),
    ],
    requires_project=True,
)
def convert_to_struts(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Convert selected members only when every solved load case puts them in compression."""
    models, model = project_model(ctx)
    selected = {x.strip() for x in v["memberIds"].split(",") if x.strip()}
    if not selected:
        raise FeatureInputError("Enter at least one member ID.")
    cases = [stm_model.solve(model, case) for case in model.cases]
    if any(s.problems for s in cases):
        raise FeatureInputError("; ".join(p for s in cases for p in s.problems))
    converted = []
    members = []
    for member in model.members:
        if member.id not in selected:
            members.append(member)
            continue
        if any(s.forces.get(member.id, 0) >= 0 for s in cases):
            raise FeatureInputError(f"Member {member.id} is not in compression in every load case.")
        members.append(
            member.model_copy(
                update={
                    "kind": "strut",
                    "width": max(member.width, 1),
                    "shape": "bottle",
                    "barArea": 0,
                }
            )
        )
        converted.append(member.id)
    if selected - set(converted):
        raise FeatureInputError(
            f"Unknown member IDs: {', '.join(sorted(selected - set(converted)))}."
        )
    updated = model.model_copy(update={"members": members})
    solve_rows(updated)
    models[0] = updated
    path = store_models(ctx, models)
    return result(
        {"convertedMembers": converted, "savedTo": str(path)},
        notes=[
            "Only members with compressive force in every case were converted; review the new strut width and web steel."
        ],
    )


@feature(
    "femStmLoadPaths.pathAuditLog", "Path Audit Log", part="fem", fields=[], requires_project=True
)
def path_audit_log(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Write nodal residuals and support reactions by load case as a traceable path audit log."""
    _models, model = project_model(ctx)
    checked = solve_rows(model)
    coords = {n.id: (n.x, n.y) for n in model.nodes}
    rows = []
    for case in model.cases:
        solved = stm_model.solve(model, case)
        if solved.problems:
            raise FeatureInputError("; ".join(solved.problems))
        for node in model.nodes:
            fx = sum(x.fx for x in case.loads if x.node == node.id)
            fy = sum(x.fy for x in case.loads if x.node == node.id)
            rx, ry = solved.reactions.get(node.id, (0.0, 0.0))
            fx += rx / 1000
            fy += ry / 1000
            for member in model.members:
                force = solved.forces[member.id] / 1000
                start = coords[member.start]
                end = coords[member.end]
                length = math.hypot(end[0] - start[0], end[1] - start[1])
                direction = ((end[0] - start[0]) / length, (end[1] - start[1]) / length)
                sign = 1 if node.id == member.start else -1 if node.id == member.end else 0
                fx += sign * force * direction[0]
                fy += sign * force * direction[1]
            rows.append(
                {
                    "case": case.name,
                    "nodeId": node.id,
                    "residualXKn": fx,
                    "residualYKn": fy,
                    "residualKn": math.hypot(fx, fy),
                }
            )
    path = export_json(
        ctx,
        "stm-path-audit.json",
        {
            "model": model.name,
            "checksPassed": checked["ok"],
            "nodeEquilibrium": rows,
            "memberForces": checked["cases"],
            "source": checked["source"],
        },
    )
    return result(
        {
            "nodesAudited": len(rows),
            "maximumResidualKn": max((x["residualKn"] for x in rows), default=0),
            "savedTo": str(path),
        }
    )

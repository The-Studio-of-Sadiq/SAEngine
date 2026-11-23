"""Strut-and-tie model editing and code-pack capacity checks."""

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
    geometry,
    next_id,
    project_model,
    solve_rows,
    store_models,
    working_model,
)
from saengine.library.strut_and_tie import StmMember


@feature(
    "femStrutTie.createStm",
    "Create STM",
    part="fem",
    fields=[
        select("templateKind", "D-region template", list(stm_model.TEMPLATES), "deepBeam"),
        number("spanMm", "Region span", 3000, unit="mm", min=100),
        number("depthMm", "Region depth", 1500, unit="mm", min=100),
        number("thicknessMm", "Region thickness", 300, unit="mm", min=50),
        number("loadKn", "Factored vertical load", 1000, unit="kN", min=0.1),
        text("name", "Model name", "Strut-and-tie model"),
    ],
    requires_project=True,
)
def create_stm(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Create and save an analysis-ready D-region model from a named structural template."""
    params = {
        "span": v["spanMm"],
        "depth": v["depthMm"],
        "thickness": v["thicknessMm"],
        "load": v["loadKn"],
    }
    model = stm_model.template(v["templateKind"], params).model_copy(update={"name": v["name"]})
    models = []
    if ctx.root is not None:
        from saengine.features.fem_common import load_stm_file

        models = load_stm_file(ctx)
    models.append(model)
    path = store_models(ctx, models)
    checked = solve_rows(model)
    return result(
        {
            "modelName": model.name,
            "nodes": len(model.nodes),
            "members": len(model.members),
            "savedTo": str(path),
            "utilisationRatio": checked["utilisation"],
        },
        notes=[
            "Loads, supports, and member geometry come from the selected STM template; review them before design."
        ],
    )


@feature(
    "femStrutTie.addStrut",
    "Add Strut",
    part="fem",
    fields=[
        text("startNode", "Start node ID", "A"),
        text("endNode", "End node ID", "C"),
        number("widthMm", "Strut width", 200, unit="mm", min=1),
        select("shape", "Strut shape", ["prism", "bottle", "tension", "other"], "bottle"),
    ],
    requires_project=True,
)
def add_strut(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Add a compression member between two existing model nodes and persist the topology."""
    models, model = project_model(ctx)
    if v["startNode"] == v["endNode"] or {v["startNode"], v["endNode"]} - {
        n.id for n in model.nodes
    }:
        raise FeatureInputError("Choose two distinct node IDs that exist in the STM.")
    member = StmMember(
        id=next_id("S", {m.id for m in model.members}),
        start=v["startNode"],
        end=v["endNode"],
        kind="strut",
        width=v["widthMm"],
        shape=v["shape"],
    )
    updated = model.model_copy(update={"members": [*model.members, member]})
    models[0] = updated
    path = store_models(ctx, models)
    return result(
        {
            "memberId": member.id,
            "lengthMm": geometry(updated)[member.id][4],
            "memberCount": len(updated.members),
            "savedTo": str(path),
        }
    )


@feature(
    "femStrutTie.addTie",
    "Add Tie",
    part="fem",
    fields=[
        text("startNode", "Start node ID", "A"),
        text("endNode", "End node ID", "B"),
        number("barAreaMm2", "Provided tie steel area", 1000, unit="mm²", min=0),
        number("barDiameterMm", "Tie bar diameter", 20, unit="mm", min=0),
        number("widthMm", "Effective tie width", 200, unit="mm", min=0),
    ],
    requires_project=True,
)
def add_tie(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Add a tension tie with its provided reinforcement and effective nodal face width."""
    models, model = project_model(ctx)
    if v["startNode"] == v["endNode"] or {v["startNode"], v["endNode"]} - {
        n.id for n in model.nodes
    }:
        raise FeatureInputError("Choose two distinct node IDs that exist in the STM.")
    tie = StmMember(
        id=next_id("T", {m.id for m in model.members}),
        start=v["startNode"],
        end=v["endNode"],
        kind="tie",
        width=v["widthMm"],
        barArea=v["barAreaMm2"],
        barDiameter=v["barDiameterMm"],
    )
    models[0] = model.model_copy(update={"members": [*model.members, tie]})
    path = store_models(ctx, models)
    return result(
        {
            "tieId": tie.id,
            "tieLengthMm": geometry(models[0])[tie.id][4],
            "providedSteelMm2": tie.barArea,
            "savedTo": str(path),
        }
    )


@feature(
    "femStrutTie.nodePlacement",
    "Node Placement",
    part="fem",
    fields=[
        text("nodeId", "Node ID", "C"),
        number("xMm", "Horizontal coordinate", 1500, unit="mm"),
        number("yMm", "Vertical coordinate", 1425, unit="mm"),
    ],
    requires_project=True,
)
def node_placement(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Move a selected STM node and re-solve the affected member geometry."""
    models, model = project_model(ctx)
    if v["nodeId"] not in {n.id for n in model.nodes}:
        raise FeatureInputError(f"No node {v['nodeId']!r} exists in the STM.")
    nodes = [
        n.model_copy(update={"x": v["xMm"], "y": v["yMm"]}) if n.id == v["nodeId"] else n
        for n in model.nodes
    ]
    moved = model.model_copy(update={"nodes": nodes})
    solved = solve_rows(moved)
    models[0] = moved
    path = store_models(ctx, models)
    return result(
        {
            "nodeId": v["nodeId"],
            "xMm": v["xMm"],
            "yMm": v["yMm"],
            "utilisationRatio": solved["utilisation"],
            "savedTo": str(path),
        }
    )


@feature(
    "femStrutTie.loadPath",
    "Load Path",
    part="fem",
    fields=[
        text("loadNode", "Loaded node ID", "C"),
    ],
    requires_project=False,
)
def load_path(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Trace the strongest connected force route from the selected load node to a support."""
    model = working_model(ctx, v)
    checked = solve_rows(model)
    connected = {n.id: [] for n in model.nodes}
    for member in model.members:
        row = next((r for r in checked["members"] if r["id"] == member.id), None)
        connected[member.start].append(
            (member.end, member.id, abs(float(row["force"])) if row else 0)
        )
        connected[member.end].append(
            (member.start, member.id, abs(float(row["force"])) if row else 0)
        )
    if v["loadNode"] not in connected:
        raise FeatureInputError(f"No node {v['loadNode']!r} exists in the selected model.")
    path, visited, current = [], set(), v["loadNode"]
    while current not in visited:
        visited.add(current)
        node = next(n for n in model.nodes if n.id == current)
        if node.support:
            break
        options = sorted(
            (edge for edge in connected[current] if edge[0] not in visited),
            key=lambda edge: edge[2],
            reverse=True,
        )
        if not options:
            break
        nxt, member_id, force = options[0]
        path.append({"fromNode": current, "toNode": nxt, "memberId": member_id, "forceKn": force})
        current = nxt
    return result(
        {
            "loadNode": v["loadNode"],
            "supportReached": bool(next(n for n in model.nodes if n.id == current).support),
            "pathMembers": len(path),
        },
        [
            table(
                "Dominant load path",
                [
                    ("fromNode", "From node"),
                    ("toNode", "To node"),
                    ("memberId", "Member"),
                    ("forceKn", "Axial force", "kN"),
                ],
                path,
            )
        ],
        [
            "The route follows the largest solved axial force at each joint; inspect the full truss for alternate paths."
        ],
    )


@feature(
    "femStrutTie.bearingAreas",
    "Bearing Areas",
    part="fem",
    fields=[
        text("nodeId", "Bearing node ID", "A"),
        number("bearingMm", "Bearing length", 300, unit="mm", min=0),
    ],
    requires_project=True,
)
def bearing_areas(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Set the loaded/support face length used by the STM nodal bearing check."""
    models, model = project_model(ctx)
    if v["nodeId"] not in {n.id for n in model.nodes}:
        raise FeatureInputError(f"No node {v['nodeId']!r} exists in the STM.")
    nodes = [
        n.model_copy(update={"bearing": v["bearingMm"]}) if n.id == v["nodeId"] else n
        for n in model.nodes
    ]
    models[0] = model.model_copy(update={"nodes": nodes})
    path = store_models(ctx, models)
    return result(
        {
            "nodeId": v["nodeId"],
            "bearingLengthMm": v["bearingMm"],
            "bearingAreaMm2": v["bearingMm"] * model.thickness,
            "savedTo": str(path),
        }
    )


@feature(
    "femStrutTie.boundary",
    "Boundary",
    part="fem",
    fields=[
        text("nodeId", "Support node ID", "A"),
        select(
            "support",
            "Restraint",
            [
                ("", "Free"),
                ("pin", "Pin"),
                ("rollerX", "Roller along X"),
                ("rollerY", "Roller along Y"),
            ],
            "pin",
        ),
    ],
    requires_project=True,
)
def boundary(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Assign the selected planar support restraint and reject a resulting unstable truss."""
    models, model = project_model(ctx)
    if v["nodeId"] not in {n.id for n in model.nodes}:
        raise FeatureInputError(f"No node {v['nodeId']!r} exists in the STM.")
    nodes = [
        n.model_copy(update={"support": v["support"]}) if n.id == v["nodeId"] else n
        for n in model.nodes
    ]
    updated = model.model_copy(update={"nodes": nodes})
    checked = solve_rows(updated)
    models[0] = updated
    path = store_models(ctx, models)
    return result(
        {
            "nodeId": v["nodeId"],
            "support": v["support"],
            "modelStable": not checked["problems"],
            "savedTo": str(path),
        }
    )


@feature(
    "femStrutTie.strutCapacity",
    "Strut Capacity",
    part="fem",
    fields=[
        text("memberId", "Strut member ID", "S1"),
    ],
    requires_project=False,
)
def strut_capacity(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Calculate the code-pack design resistance and governing demand of a selected strut."""
    model = working_model(ctx, v)
    member = next((m for m in model.members if m.id == v["memberId"]), None)
    if member is None or member.kind != "strut":
        raise FeatureInputError(f"{v['memberId']!r} is not a strut in the selected model.")
    checked = solve_rows(model)
    row = next(r for r in checked["members"] if r["id"] == member.id)
    capacity = stm.strut_capacity(
        model.fc, member.width * model.thickness, member.shape, bool(model.web)
    )
    return result(
        {
            "memberId": member.id,
            "demandKn": abs(row["force"]),
            "designCapacityKn": capacity / 1000,
            "utilisationRatio": row["utilisation"],
            "resistanceFactor": stm.phi(),
        },
        notes=[
            "Resistance uses the active code pack's strut/node efficiency factors and resistance factor."
        ],
    )


@feature(
    "femStrutTie.tieCapacity",
    "Tie Capacity",
    part="fem",
    fields=[
        text("memberId", "Tie member ID", "T1"),
    ],
    requires_project=False,
)
def tie_capacity(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Check a tie's steel and prestressing resistance against its solved tensile force."""
    model = working_model(ctx, v)
    member = next((m for m in model.members if m.id == v["memberId"]), None)
    if member is None or member.kind != "tie":
        raise FeatureInputError(f"{v['memberId']!r} is not a tie in the selected model.")
    checked = solve_rows(model)
    row = next(r for r in checked["members"] if r["id"] == member.id)
    resistance = stm.phi() * stm.tie_nominal(
        member.barArea, model.fy, member.prestressArea, member.fse, member.fpy, member.bonded
    )
    needed = max(
        (
            abs(row["force"]) * 1000 / stm.phi()
            - (resistance / stm.phi() - member.barArea * model.fy)
        )
        / model.fy,
        0,
    )
    return result(
        {
            "memberId": member.id,
            "demandKn": abs(row["force"]),
            "designCapacityKn": resistance / 1000,
            "requiredSteelMm2": needed,
            "providedSteelMm2": member.barArea,
            "resistanceFactor": stm.phi(),
        }
    )


@feature(
    "femStrutTie.nodeCapacity",
    "Node Capacity",
    part="fem",
    fields=[
        text("nodeId", "Node ID", "A"),
    ],
    requires_project=False,
)
def node_capacity(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Check the selected nodal bearing face using its tie count and entered bearing area."""
    model = working_model(ctx, v)
    node = next((n for n in model.nodes if n.id == v["nodeId"]), None)
    if node is None:
        raise FeatureInputError(f"No node {v['nodeId']!r} exists in the selected model.")
    ties = sum(m.kind == "tie" and node.id in (m.start, m.end) for m in model.members)
    kind = "CCC" if ties == 0 else "CCT" if ties == 1 else "CTT"
    area = node.bearing * model.thickness
    if area <= 0:
        raise FeatureInputError(f"Give node {node.id} a non-zero bearing length first.")
    checked = solve_rows(model)
    forces = [
        math.hypot(*pair)
        for case in checked["cases"]
        for key, pair in case["reactions"].items()
        if key == node.id
    ]
    demand = max(forces, default=0.0)
    capacity = stm.node_capacity(model.fc, area, kind)
    return result(
        {
            "nodeId": node.id,
            "nodeType": kind,
            "demandKn": demand,
            "designCapacityKn": capacity / 1000,
            "utilisationRatio": demand * 1000 / capacity,
        }
    )


@feature(
    "femStrutTie.topologyOptimise",
    "Topology Optimise",
    part="fem",
    fields=[
        number("maxMoveMm", "Maximum internal-node movement", 50, unit="mm", min=1),
    ],
    requires_project=False,
)
def topology_optimise(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Evaluate small admissible internal-node shifts and select the lowest-energy stable layout."""
    model = working_model(ctx, v)
    base = solve_rows(model)
    movable = [
        n
        for n in model.nodes
        if not n.support
        and not any(load.node == n.id for case in model.cases for load in case.loads)
    ]
    if not movable:
        raise FeatureInputError(
            "The model has no unloaded, unsupported internal nodes to optimise."
        )
    candidates = []
    for node in movable:
        for dx, dy in (
            (v["maxMoveMm"], 0),
            (-v["maxMoveMm"], 0),
            (0, v["maxMoveMm"]),
            (0, -v["maxMoveMm"]),
        ):
            nodes = [
                n.model_copy(update={"x": n.x + dx, "y": n.y + dy}) if n.id == node.id else n
                for n in model.nodes
            ]
            candidate = model.model_copy(update={"nodes": nodes})
            try:
                check = solve_rows(candidate)
            except FeatureInputError:
                continue
            energy = sum(
                abs(float(mr["force"])) * geometry(candidate)[mr["id"]][4]
                for mr in check["members"]
            )
            candidates.append((energy, node.id, dx, dy, check))
    best = min(candidates, default=None, key=lambda item: item[0])
    if best is None:
        raise FeatureInputError("No stable layout was found among the tested node shifts.")
    return result(
        {
            "baselineUtilisationRatio": base["utilisation"],
            "candidateEnergyNmm": best[0],
            "movedNode": best[1],
            "deltaXmm": best[2],
            "deltaYmm": best[3],
            "candidateUtilisationRatio": best[4]["utilisation"],
        },
        notes=[
            "One-step coordinate search evaluates four axis-aligned shifts per internal node; review before adopting."
        ],
    )


@feature("femStrutTie.strutAngles", "Strut Angles", part="fem", fields=[], requires_project=False)
def strut_angles(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Compare every incident strut/tie angle with the active code pack's minimum."""
    model = working_model(ctx, v)
    coords = {n.id: (n.x, n.y) for n in model.nodes}
    minimum = stm.min_angle()
    rows = []
    for node in model.nodes:
        incident = [m for m in model.members if node.id in (m.start, m.end)]
        for a in incident:
            for b in incident:
                if a.kind != "strut" or b.kind != "tie":
                    continue
                vectors = []
                for member in (a, b):
                    other = member.end if member.start == node.id else member.start
                    dx, dy = coords[other][0] - node.x, coords[other][1] - node.y
                    vectors.append((dx / math.hypot(dx, dy), dy / math.hypot(dx, dy)))
                angle = math.degrees(
                    math.acos(
                        min(1.0, abs(vectors[0][0] * vectors[1][0] + vectors[0][1] * vectors[1][1]))
                    )
                )
                rows.append(
                    {
                        "nodeId": node.id,
                        "strutId": a.id,
                        "tieId": b.id,
                        "angleDeg": angle,
                        "minimumDeg": minimum,
                        "passes": angle >= minimum,
                    }
                )
    return result(
        {"checkedAngles": len(rows), "minimumAngleDeg": minimum},
        [
            table(
                "Strut-to-tie joint angles",
                [
                    ("nodeId", "Node"),
                    ("strutId", "Strut"),
                    ("tieId", "Tie"),
                    ("angleDeg", "Angle", "°"),
                    ("minimumDeg", "Minimum", "°"),
                    ("passes", "Pass"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStrutTie.tieTuning",
    "Tie Tuning",
    part="fem",
    fields=[
        text("nodeId", "Internal node ID", "C"),
        number("verticalShiftMm", "Vertical adjustment", 25, unit="mm"),
    ],
    requires_project=True,
)
def tie_tuning(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Test a tie-node vertical adjustment and save it only when the resulting truss remains stable."""
    models, model = project_model(ctx)
    node = next((n for n in model.nodes if n.id == v["nodeId"]), None)
    if (
        node is None
        or node.support
        or any(load.node == node.id for c in model.cases for load in c.loads)
    ):
        raise FeatureInputError("Choose an existing unloaded, unsupported internal node.")
    nodes = [
        n.model_copy(update={"y": n.y + v["verticalShiftMm"]}) if n.id == node.id else n
        for n in model.nodes
    ]
    updated = model.model_copy(update={"nodes": nodes})
    checked = solve_rows(updated)
    models[0] = updated
    path = store_models(ctx, models)
    return result(
        {
            "nodeId": node.id,
            "newYmm": node.y + v["verticalShiftMm"],
            "utilisationRatio": checked["utilisation"],
            "savedTo": str(path),
        }
    )


@feature("femStrutTie.forceBalance", "Force Balance", part="fem", fields=[], requires_project=False)
def force_balance(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Sum applied, member, and support forces at each node for every load case."""
    model = working_model(ctx, v)
    coords = {n.id: (n.x, n.y) for n in model.nodes}
    rows = []
    for case in model.cases:
        solution = stm_model.solve(model, case)
        if solution.problems:
            raise FeatureInputError("; ".join(solution.problems))
        for node in model.nodes:
            fx = sum(load.fx for load in case.loads if load.node == node.id)
            fy = sum(load.fy for load in case.loads if load.node == node.id)
            rx, ry = solution.reactions.get(node.id, (0.0, 0.0))
            fx += rx / 1000
            fy += ry / 1000
            for member in model.members:
                force = solution.forces[member.id] / 1000
                x0, y0 = coords[member.start]
                x1, y1 = coords[member.end]
                length = math.hypot(x1 - x0, y1 - y0)
                direction = ((x1 - x0) / length, (y1 - y0) / length)
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
    worst = max((r["residualKn"] for r in rows), default=0)
    return result(
        {"maxResidualKn": worst, "nodeCaseChecks": len(rows)},
        [
            table(
                "Nodal equilibrium residuals",
                [
                    ("case", "Load case"),
                    ("nodeId", "Node"),
                    ("residualXKn", "ΣFx", "kN"),
                    ("residualYKn", "ΣFy", "kN"),
                    ("residualKn", "Resultant", "kN"),
                ],
                rows,
            )
        ],
        [
            "Residuals include the solver's support reactions; report is numerical equilibrium verification."
        ],
    )


@feature(
    "femStrutTie.tieAnchorage",
    "Tie Anchorage",
    part="fem",
    fields=[
        text("memberId", "Tie member ID", "T1"),
    ],
    requires_project=False,
)
def tie_anchorage(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Calculate hook development for the selected reinforced tie at both end nodes."""
    from saengine.design.ductile_joints import hooked_development

    model = working_model(ctx, v)
    tie = next((m for m in model.members if m.id == v["memberId"] and m.kind == "tie"), None)
    if tie is None or tie.barDiameter <= 0:
        raise FeatureInputError("Select a tie with its reinforcing-bar diameter specified.")
    required = hooked_development(tie.barDiameter, model.fy, model.fc, model.lam)
    ends = [next(n for n in model.nodes if n.id == node_id) for node_id in (tie.start, tie.end)]
    rows = [
        {
            "nodeId": n.id,
            "anchorage": n.anchorage or "unspecified",
            "requiredLengthMm": required,
            "availableLengthMm": n.anchorLength,
            "passes": n.anchorLength >= required if n.anchorage == "hook" else None,
        }
        for n in ends
    ]
    return result(
        {"requiredHookLengthMm": required, "tieId": tie.id},
        [
            table(
                "Tie end anchorage",
                [
                    ("nodeId", "Node"),
                    ("anchorage", "Anchorage"),
                    ("requiredLengthMm", "Required", "mm"),
                    ("availableLengthMm", "Available", "mm"),
                    ("passes", "Pass"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStrutTie.strutConfinement",
    "Strut Confinement",
    part="fem",
    fields=[
        number("barAreaMm2", "Web bar area per layer", 157, unit="mm²", min=1),
        number("spacingMm", "Web bar spacing", 150, unit="mm", min=1),
    ],
    requires_project=True,
)
def strut_confinement(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Add a transverse web layer only when it meets the code-pack crack-control ratio."""
    models, model = project_model(ctx)
    required = stm.factor("webRatio")
    supplied = v["barAreaMm2"] / (model.thickness * v["spacingMm"])
    if supplied < required:
        raise FeatureInputError(
            f"Web layer ratio {supplied:.4f} is below the code-pack requirement {required:.4f}."
        )
    from saengine.library.strut_and_tie import StmWebLayer

    layer = StmWebLayer(area=v["barAreaMm2"], spacing=v["spacingMm"], angle=90)
    models[0] = model.model_copy(update={"web": [*model.web, layer]})
    path = store_models(ctx, models)
    return result(
        {
            "providedRatio": supplied,
            "requiredRatio": required,
            "webLayerCount": len(models[0].web),
            "savedTo": str(path),
        },
        notes=["The required web ratio is supplied by the active code pack."],
    )


@feature(
    "femStrutTie.reinforcementLayout",
    "Reinforcement Layout",
    part="fem",
    fields=[
        text("tieId", "Tie member ID", "T1"),
        number("barDiameterMm", "Candidate bar diameter", 20, unit="mm", min=1),
    ],
    requires_project=False,
)
def reinforcement_layout(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Select the smallest whole-bar count of the chosen diameter that resists a tie demand."""
    model = working_model(ctx, v)
    tie = next((m for m in model.members if m.id == v["tieId"] and m.kind == "tie"), None)
    if tie is None:
        raise FeatureInputError(f"{v['tieId']!r} is not a tie in the selected model.")
    checked = solve_rows(model)
    demand = abs(next(r["force"] for r in checked["members"] if r["id"] == tie.id)) * 1000
    area = math.pi * v["barDiameterMm"] ** 2 / 4
    count = max(1, math.ceil(demand / (stm.phi() * area * model.fy)))
    provided = count * area
    return result(
        {
            "tieId": tie.id,
            "requiredSteelMm2": demand / (stm.phi() * model.fy),
            "barDiameterMm": v["barDiameterMm"],
            "barCount": count,
            "providedSteelMm2": provided,
            "designCapacityKn": stm.tie_capacity(provided, model.fy) / 1000,
        }
    )


@feature(
    "femStrutTie.crackReinforcement",
    "Crack Reinforcement",
    part="fem",
    fields=[
        number("barDiameterMm", "Crack-control bar diameter", 12, unit="mm", min=1),
        number("maxSpacingMm", "Maximum proposed spacing", 200, unit="mm", min=1),
    ],
    requires_project=False,
)
def crack_reinforcement(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Calculate distributed web reinforcement and its code-pack ratio for the region thickness."""
    model = working_model(ctx, v)
    area = math.pi * v["barDiameterMm"] ** 2 / 4
    ratio = area / (model.thickness * v["maxSpacingMm"])
    need = stm.factor("webRatio")
    return result(
        {
            "providedRatio": ratio,
            "requiredRatio": need,
            "barsPerMetrePerFace": 1000 / v["maxSpacingMm"],
            "passesRatio": ratio >= need,
            "barAreaMm2": area,
        },
        notes=[
            "Ratio is As/(region thickness × spacing); actual crack widths depend on restraint and exposure."
        ],
    )


@feature(
    "femStrutTie.equilibriumCheck",
    "Equilibrium Check",
    part="fem",
    fields=[],
    requires_project=False,
)
def equilibrium_check(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Report global applied-load and support-reaction balance by load case."""
    model = working_model(ctx, v)
    rows = []
    for case in model.cases:
        solution = stm_model.solve(model, case)
        if solution.problems:
            raise FeatureInputError("; ".join(solution.problems))
        fx = (
            sum(load.fx for load in case.loads)
            + sum(r[0] for r in solution.reactions.values()) / 1000
        )
        fy = (
            sum(load.fy for load in case.loads)
            + sum(r[1] for r in solution.reactions.values()) / 1000
        )
        rows.append(
            {
                "case": case.name,
                "appliedFxKn": sum(x.fx for x in case.loads),
                "appliedFyKn": sum(x.fy for x in case.loads),
                "residualKn": math.hypot(fx, fy),
            }
        )
    return result(
        {
            "loadCases": len(rows),
            "maximumResidualKn": max((r["residualKn"] for r in rows), default=0),
        },
        [
            table(
                "Global equilibrium",
                [
                    ("case", "Load case"),
                    ("appliedFxKn", "Applied ΣFx", "kN"),
                    ("appliedFyKn", "Applied ΣFy", "kN"),
                    ("residualKn", "Reaction residual", "kN"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStrutTie.capacityRatio", "Capacity Ratio", part="fem", fields=[], requires_project=False
)
def capacity_ratio(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Tabulate demand-to-resistance ratios for every strut, tie and nodal-zone check."""
    checked = solve_rows(working_model(ctx, v))
    rows = [
        {
            "component": x["id"],
            "type": x["kind"],
            "utilisationRatio": x["utilisation"],
            "passes": x["ok"],
        }
        for x in checked["members"]
    ]
    rows.extend(
        {
            "component": x["id"],
            "type": "node",
            "utilisationRatio": x["utilisation"],
            "passes": x["ok"],
        }
        for x in checked["nodes"]
    )
    return result(
        {"maximumUtilisationRatio": checked["utilisation"], "components": len(rows)},
        [
            table(
                "STM component capacity ratios",
                [
                    ("component", "Component"),
                    ("type", "Type"),
                    ("utilisationRatio", "Demand / capacity"),
                    ("passes", "Pass"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStrutTie.serviceabilityCheck",
    "Serviceability Check",
    part="fem",
    fields=[
        number("serviceLoadFactor", "Service-to-factored force ratio", 0.65, min=0.01, max=1),
    ],
    requires_project=False,
)
def serviceability_check(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Scale solved forces to the entered service level and report reinforcement stress and strain."""
    model = working_model(ctx, v)
    checked = solve_rows(model)
    rows = []
    for member in model.members:
        if member.kind != "tie":
            continue
        force = abs(next(r["force"] for r in checked["members"] if r["id"] == member.id)) * 1000
        stress = force * v["serviceLoadFactor"] / member.barArea if member.barArea > 0 else None
        rows.append(
            {
                "tieId": member.id,
                "serviceStressMpa": stress,
                "steelStrain": stress / 200000 if stress is not None else None,
            }
        )
    return result(
        {"serviceLoadFactor": v["serviceLoadFactor"], "tiesChecked": len(rows)},
        [
            table(
                "Tie service response",
                [
                    ("tieId", "Tie"),
                    ("serviceStressMpa", "Steel stress", "MPa"),
                    ("steelStrain", "Elastic strain"),
                ],
                rows,
            )
        ],
        [
            "Linear-elastic steel strain uses Es = 200 GPa; crack width and member deflection require service analysis data."
        ],
    )


@feature("femStrutTie.modelExport", "Model Export", part="fem", fields=[], requires_project=True)
def model_export(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Export the checked STM input model and calculated forces to a reviewable JSON file."""
    from saengine.features.fem_stm_common import export_json

    _models, model = project_model(ctx)
    checked = solve_rows(model)
    path = export_json(
        ctx, "stm-model-export.json", {"model": model.model_dump(mode="json"), "analysis": checked}
    )
    return result(
        {
            "modelName": model.name,
            "savedTo": str(path),
            "members": len(model.members),
            "loadCases": len(model.cases),
        }
    )

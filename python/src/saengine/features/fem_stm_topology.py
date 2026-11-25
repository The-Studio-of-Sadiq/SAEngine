"""STM topology generation, geometric editing, optimisation, and CAD exchange."""

from __future__ import annotations

import json
import math
from typing import Any

from saengine.design import stm_model
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
from saengine.features.fem_common import load_stm_file
from saengine.features.fem_stm_common import (
    geometry,
    next_id,
    project_model,
    solve_rows,
    store_models,
    working_model,
)
from saengine.library.strut_and_tie import StmLoad, StmLoadCase, StmMember, StmNode


def _strain_energy(model: Any) -> float:
    """Estimate axial strain energy in N mm for the stated member sections."""
    total = 0.0
    for case in model.cases:
        solution = stm_model.solve(model, case)
        if solution.problems:
            raise FeatureInputError("; ".join(solution.problems))
        lengths = geometry(model)
        for member in model.members:
            area = member.width * model.thickness if member.kind == "strut" else member.barArea
            if area <= 0:
                raise FeatureInputError(
                    f"Give member {member.id} a non-zero design area before energy optimisation."
                )
            force = solution.forces[member.id]
            total += force**2 * lengths[member.id][4] / (2 * 200000 * area)
    return total


@feature(
    "femStmTopology.autoGenerate",
    "Auto Generate",
    part="fem",
    fields=[
        select("templateKind", "Initial load-path template", list(stm_model.TEMPLATES), "deepBeam"),
        number("spanMm", "Region span", 3000, unit="mm", min=100),
        number("depthMm", "Region depth", 1500, unit="mm", min=100),
        number("loadKn", "Factored load", 1000, unit="kN", min=0.1),
    ],
    requires_project=True,
)
def auto_generate(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Generate an initial solvable topology from region dimensions and a factored load."""
    model = stm_model.template(
        v["templateKind"], {"span": v["spanMm"], "depth": v["depthMm"], "load": v["loadKn"]}
    )
    from saengine.features.fem_common import load_stm_file

    models = load_stm_file(ctx) if ctx.root else []
    models.append(model)
    path = store_models(ctx, models)
    checked = stm_model.check_model(model)
    return result(
        {
            "modelName": model.name,
            "generatedNodes": len(model.nodes),
            "generatedMembers": len(model.members),
            "utilisationRatio": checked["utilisation"],
            "savedTo": str(path),
        }
    )


@feature(
    "femStmTopology.startTruss",
    "Start Truss",
    part="fem",
    fields=[
        select("templateKind", "Truss archetype", list(stm_model.TEMPLATES), "deepBeam"),
        number("depthMm", "Member depth", 1500, unit="mm", min=100),
    ],
    requires_project=True,
)
def start_truss(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Start an editable plane-truss skeleton from the selected archetype at the entered depth."""
    model = stm_model.template(v["templateKind"], {"depth": v["depthMm"]})
    from saengine.features.fem_common import load_stm_file

    models = load_stm_file(ctx) if ctx.root else []
    models.append(model)
    path = store_models(ctx, models)
    return result(
        {
            "modelName": model.name,
            "nodeCount": len(model.nodes),
            "memberCount": len(model.members),
            "savedTo": str(path),
        }
    )


@feature(
    "femStmTopology.addNode",
    "Add Node",
    part="fem",
    fields=[
        text("nodeId", "New node ID", "N4"),
        number("xMm", "X coordinate", 1000, unit="mm"),
        number("yMm", "Y coordinate", 750, unit="mm"),
    ],
    requires_project=True,
)
def add_node(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Insert a uniquely named free node at the entered region coordinates."""
    models, model = project_model(ctx)
    if v["nodeId"] in {n.id for n in model.nodes}:
        raise FeatureInputError(f"Node ID {v['nodeId']!r} is already in use.")
    node = StmNode(id=v["nodeId"], x=v["xMm"], y=v["yMm"])
    models[0] = model.model_copy(update={"nodes": [*model.nodes, node]})
    path = store_models(ctx, models)
    return result(
        {
            "nodeId": node.id,
            "xMm": node.x,
            "yMm": node.y,
            "nodeCount": len(models[0].nodes),
            "savedTo": str(path),
        },
        notes=["A new node must be connected and the resulting truss re-solved before design use."],
    )


@feature(
    "femStmTopology.addMember",
    "Add Member",
    part="fem",
    fields=[
        text("memberId", "New member ID", "M4"),
        text("startNode", "Start node", "A"),
        text("endNode", "End node", "B"),
        select(
            "kind",
            "Member force type",
            [("strut", "Compression strut"), ("tie", "Tension tie")],
            "strut",
        ),
        number("effectiveWidthMm", "Member width", 150, unit="mm", min=0),
        number("tieAreaMm2", "Tie steel area", 800, unit="mm²", min=0),
    ],
    requires_project=True,
)
def add_member(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Connect two existing nodes using the specified compression or tension member properties."""
    models, model = project_model(ctx)
    ids = {n.id for n in model.nodes}
    if v["memberId"] in {m.id for m in model.members}:
        raise FeatureInputError(f"Member ID {v['memberId']!r} is already in use.")
    if v["startNode"] == v["endNode"] or {v["startNode"], v["endNode"]} - ids:
        raise FeatureInputError("Select two different node IDs in the current model.")
    member = StmMember(
        id=v["memberId"],
        start=v["startNode"],
        end=v["endNode"],
        kind=v["kind"],
        width=v["effectiveWidthMm"],
        barArea=v["tieAreaMm2"],
    )
    updated = model.model_copy(update={"members": [*model.members, member]})
    length = geometry(updated)[member.id][4]
    models[0] = updated
    path = store_models(ctx, models)
    return result({"memberId": member.id, "lengthMm": length, "savedTo": str(path)})


@feature(
    "femStmTopology.optimiseLayout",
    "Optimise Layout",
    part="fem",
    fields=[
        number("searchStepMm", "Node search step", 50, unit="mm", min=1),
    ],
    requires_project=True,
)
def optimise_layout(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Test axis-aligned internal-node shifts and save the stable layout with least estimated strain energy."""
    models, model = project_model(ctx)
    base = _strain_energy(model)
    loaded = {load.node for case in model.cases for load in case.loads}
    movable = [n for n in model.nodes if not n.support and n.id not in loaded]
    if not movable:
        raise FeatureInputError("No unloaded, unsupported internal nodes are available to move.")
    best = (base, model, None, 0.0, 0.0)
    for node in movable:
        for dx, dy in (
            (v["searchStepMm"], 0),
            (-v["searchStepMm"], 0),
            (0, v["searchStepMm"]),
            (0, -v["searchStepMm"]),
        ):
            nodes = [
                n.model_copy(update={"x": n.x + dx, "y": n.y + dy}) if n.id == node.id else n
                for n in model.nodes
            ]
            candidate = model.model_copy(update={"nodes": nodes})
            try:
                energy = _strain_energy(candidate)
                solve_rows(candidate)
            except FeatureInputError:
                continue
            if energy < best[0]:
                best = (energy, candidate, node.id, dx, dy)
    if best[1] is model:
        raise FeatureInputError("No stable one-step layout reduced the estimated strain energy.")
    models[0] = best[1]
    path = store_models(ctx, models)
    return result(
        {
            "initialEnergyNmm": base,
            "optimisedEnergyNmm": best[0],
            "movedNode": best[2],
            "deltaXmm": best[3],
            "deltaYmm": best[4],
            "savedTo": str(path),
        },
        notes=[
            "Energy uses 200 GPa elastic modulus and entered axial member areas; the truss solver's force distribution is reviewed with model checks."
        ],
    )


@feature(
    "femStmTopology.volumeTarget",
    "Volume Target",
    part="fem",
    fields=[
        number("targetVolumeM3", "Target material volume", 0.25, unit="m³", min=0.001),
    ],
    requires_project=False,
)
def volume_target(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Compare actual strut concrete and tie steel volumes with the engineer's material target."""
    model = working_model(ctx, v)
    lengths = geometry(model)
    concrete_mm3 = sum(
        m.width * model.thickness * lengths[m.id][4] for m in model.members if m.kind == "strut"
    )
    steel_mm3 = sum(m.barArea * lengths[m.id][4] for m in model.members if m.kind == "tie")
    volume = (concrete_mm3 + steel_mm3) * 1e-9
    return result(
        {
            "modelMaterialVolumeM3": volume,
            "targetVolumeM3": v["targetVolumeM3"],
            "excessVolumeM3": volume - v["targetVolumeM3"],
            "targetSatisfied": volume <= v["targetVolumeM3"],
        },
        notes=[
            "Concrete and longitudinal tie steel volumes are separated in the table; web bars are not included."
        ],
    )


@feature(
    "femStmTopology.runIterations",
    "Run Iterations",
    part="fem",
    fields=[
        number("iterations", "Coordinate-search iterations", 4, min=1, max=20),
        number("initialStepMm", "Initial movement step", 40, unit="mm", min=1),
    ],
    requires_project=True,
)
def run_iterations(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Run deterministic coordinate descent on unloaded internal joints while retaining solvable layouts."""
    models, model = project_model(ctx)
    current = model
    energy = _strain_energy(current)
    history = [{"iteration": 0, "energyNmm": energy}]
    step = v["initialStepMm"]
    for iteration in range(1, int(v["iterations"]) + 1):
        improved = False
        loaded = {x.node for c in current.cases for x in c.loads}
        for node in list(current.nodes):
            if node.support or node.id in loaded:
                continue
            best = (energy, current)
            for dx, dy in ((step, 0), (-step, 0), (0, step), (0, -step)):
                nodes = [
                    n.model_copy(update={"x": n.x + dx, "y": n.y + dy}) if n.id == node.id else n
                    for n in current.nodes
                ]
                candidate = current.model_copy(update={"nodes": nodes})
                try:
                    candidate_energy = _strain_energy(candidate)
                    solve_rows(candidate)
                except FeatureInputError:
                    continue
                if candidate_energy < best[0]:
                    best = (candidate_energy, candidate)
            if best[1] is not current:
                energy, current = best
                improved = True
        history.append({"iteration": iteration, "energyNmm": energy})
        if not improved:
            step *= 0.5
    if current is model:
        raise FeatureInputError("The iteration search found no lower-energy stable layout.")
    models[0] = current
    path = store_models(ctx, models)
    return result(
        {
            "iterationsRun": int(v["iterations"]),
            "initialEnergyNmm": history[0]["energyNmm"],
            "finalEnergyNmm": energy,
            "savedTo": str(path),
        },
        [
            table(
                "Coordinate-search convergence",
                [("iteration", "Iteration"), ("energyNmm", "Estimated strain energy", "N·mm")],
                history,
            )
        ],
    )


@feature(
    "femStmTopology.smoothTopology",
    "Smooth Topology",
    part="fem",
    fields=[
        number("smoothingShare", "Move toward neighbour centroid", 0.25, min=0.01, max=0.9),
    ],
    requires_project=True,
)
def smooth_topology(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Smooth free joint coordinates toward their connected-member centroid and retain a stable layout."""
    models, model = project_model(ctx)
    loaded = {x.node for c in model.cases for x in c.loads}
    nodes = {n.id: n for n in model.nodes}
    proposed = []
    for node in model.nodes:
        neighbours = []
        if not node.support and node.id not in loaded:
            for member in model.members:
                if member.start == node.id:
                    neighbours.append(nodes[member.end])
                elif member.end == node.id:
                    neighbours.append(nodes[member.start])
        if neighbours:
            x = sum(n.x for n in neighbours) / len(neighbours)
            y = sum(n.y for n in neighbours) / len(neighbours)
            share = v["smoothingShare"]
            proposed.append(
                node.model_copy(
                    update={"x": node.x + share * (x - node.x), "y": node.y + share * (y - node.y)}
                )
            )
        else:
            proposed.append(node)
    updated = model.model_copy(update={"nodes": proposed})
    checked = solve_rows(updated)
    models[0] = updated
    path = store_models(ctx, models)
    return result(
        {
            "smoothedNodes": sum(
                a.x != b.x or a.y != b.y for a, b in zip(model.nodes, proposed, strict=True)
            ),
            "utilisationRatio": checked["utilisation"],
            "savedTo": str(path),
        }
    )


@feature(
    "femStmTopology.pruneMembers",
    "Prune Members",
    part="fem",
    fields=[
        number("forceThresholdKn", "Negligible force threshold", 1, unit="kN", min=0),
    ],
    requires_project=True,
)
def prune_members(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Remove only below-threshold members whose removal leaves every load case stable."""
    models, model = project_model(ctx)
    checked = solve_rows(model)
    candidates = [m.id for m in checked["members"] if abs(m["force"]) <= v["forceThresholdKn"]]
    removed = []
    current = model
    for member_id in candidates:
        trial = current.model_copy(
            update={"members": [m for m in current.members if m.id != member_id]}
        )
        try:
            solve_rows(trial)
        except FeatureInputError:
            continue
        current = trial
        removed.append(member_id)
    if not removed:
        raise FeatureInputError(
            "No negligible-force member can be removed without destabilising the truss."
        )
    models[0] = current
    path = store_models(ctx, models)
    return result(
        {"removedMembers": removed, "remainingMembers": len(current.members), "savedTo": str(path)},
        notes=["Each proposed deletion was re-solved before it was accepted."],
    )


@feature(
    "femStmTopology.mergeNodes",
    "Merge Nodes",
    part="fem",
    fields=[
        text("keepNode", "Node ID to keep", "N1"),
        text("mergeNode", "Coincident node ID", "N2"),
        number("toleranceMm", "Maximum merge distance", 5, unit="mm", min=0),
    ],
    requires_project=True,
)
def merge_nodes(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Merge a pair of geometrically coincident nodes, preserving restraints and loads."""
    models, model = project_model(ctx)
    a = next((n for n in model.nodes if n.id == v["keepNode"]), None)
    b = next((n for n in model.nodes if n.id == v["mergeNode"]), None)
    if a is None or b is None or a.id == b.id:
        raise FeatureInputError("Choose two distinct existing nodes.")
    distance = math.hypot(a.x - b.x, a.y - b.y)
    if distance > v["toleranceMm"]:
        raise FeatureInputError(f"Nodes are {distance:.2f} mm apart, beyond the merge tolerance.")
    support = a.support or b.support
    if a.support and b.support and a.support != b.support:
        raise FeatureInputError("Coincident nodes have conflicting support restraints.")
    merged = a.model_copy(
        update={
            "support": support,
            "bearing": max(a.bearing, b.bearing),
            "anchorage": a.anchorage or b.anchorage,
            "anchorLength": max(a.anchorLength, b.anchorLength),
        }
    )
    new_nodes = [merged if n.id == a.id else n for n in model.nodes if n.id != b.id]
    members = []
    for member in model.members:
        start = a.id if member.start == b.id else member.start
        end = a.id if member.end == b.id else member.end
        if start != end:
            members.append(member.model_copy(update={"start": start, "end": end}))
    cases = []
    for case in model.cases:
        loads: dict[str, list[float]] = {}
        for load in case.loads:
            node_id = a.id if load.node == b.id else load.node
            force = loads.setdefault(node_id, [0.0, 0.0])
            force[0] += load.fx
            force[1] += load.fy
        cases.append(
            case.model_copy(
                update={
                    "loads": [StmLoad(node=node, fx=f[0], fy=f[1]) for node, f in loads.items()]
                }
            )
        )
    updated = model.model_copy(update={"nodes": new_nodes, "members": members, "cases": cases})
    checked = solve_rows(updated)
    models[0] = updated
    path = store_models(ctx, models)
    return result(
        {
            "keptNode": a.id,
            "removedNode": b.id,
            "mergeDistanceMm": distance,
            "utilisationRatio": checked["utilisation"],
            "savedTo": str(path),
        }
    )


@feature(
    "femStmTopology.applySymmetry",
    "Apply Symmetry",
    part="fem",
    fields=[
        number("axisXmm", "Vertical symmetry axis X", 1500, unit="mm"),
        checkbox("duplicateLoads", "Mirror applied loads", True),
    ],
    requires_project=True,
)
def apply_symmetry(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Mirror an entire truss, including geometry, support nodes, and optionally load vectors."""
    models, model = project_model(ctx)
    node_map = {n.id: f"{n.id}_M" for n in model.nodes}
    existing = {n.id for n in model.nodes}
    if set(node_map.values()) & existing:
        raise FeatureInputError(
            "Mirrored node IDs would collide with existing IDs; rename the existing joints first."
        )
    reflected_nodes = [
        n.model_copy(update={"id": node_map[n.id], "x": 2 * v["axisXmm"] - n.x})
        for n in model.nodes
    ]
    member_map = {m.id: next_id(f"{m.id}_M", {x.id for x in model.members}) for m in model.members}
    reflected_members = [
        m.model_copy(
            update={"id": member_map[m.id], "start": node_map[m.start], "end": node_map[m.end]}
        )
        for m in model.members
    ]
    cases = []
    for case in model.cases:
        loads = list(case.loads)
        if v["duplicateLoads"]:
            loads += [StmLoad(node=node_map[x.node], fx=-x.fx, fy=x.fy) for x in case.loads]
        cases.append(case.model_copy(update={"loads": loads}))
    updated = model.model_copy(
        update={
            "nodes": [*model.nodes, *reflected_nodes],
            "members": [*model.members, *reflected_members],
            "cases": cases,
        }
    )
    for candidate in updated.cases:
        solution = stm_model.solve(updated, candidate)
        if solution.problems:
            raise FeatureInputError("; ".join(solution.problems))
    models[0] = updated
    path = store_models(ctx, models)
    return result(
        {
            "mirroredNodes": len(reflected_nodes),
            "mirroredMembers": len(reflected_members),
            "axisXmm": v["axisXmm"],
            "savedTo": str(path),
        }
    )


@feature("femStmTopology.undoLayout", "Undo Layout", part="fem", fields=[], requires_project=True)
def undo_layout(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Restore the immediately previous STM file snapshot recorded by topology edits."""
    from saengine.library.strut_and_tie import StrutAndTieFile

    if ctx.root is None:
        raise FeatureInputError("Open a project folder before undoing STM edits.")
    target = next(
        (
            ctx.root / folder / "strut-and-tie.json"
            for folder in ("08 FEM", "08 Analysis")
            if (ctx.root / folder / "strut-and-tie.json").is_file()
        ),
        None,
    )
    if target is None:
        raise FeatureInputError("No project STM file exists to undo.")
    history_path = target.with_name("strut-and-tie-history.json")
    if not history_path.is_file():
        raise FeatureInputError("No saved STM edit snapshot is available to undo.")
    history = json.loads(history_path.read_text(encoding="utf-8"))
    if not history:
        raise FeatureInputError("The STM edit history is empty.")
    previous = StrutAndTieFile.model_validate(history.pop())
    target.write_text(previous.model_dump_json(indent=2, by_alias=True) + "\n", encoding="utf-8")
    history_path.write_text(
        json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result(
        {
            "restoredModels": len(previous.models),
            "savedTo": str(target),
            "historyEntriesRemaining": len(history),
        }
    )


@feature(
    "femStmTopology.supportAnchorage",
    "Support Anchorage",
    part="fem",
    fields=[
        text("nodeId", "Support node ID", "A"),
        select("support", "Support restraint", ["pin", "rollerX", "rollerY"], "pin"),
        select("anchorage", "Tie anchorage", ["", "hook", "plate", "through"], "through"),
        number("bearingMm", "Bearing length", 300, unit="mm", min=0),
    ],
    requires_project=True,
)
def support_anchorage(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Set support restraint, bearing face, and tie-end anchorage together at a boundary joint."""
    models, model = project_model(ctx)
    if v["nodeId"] not in {n.id for n in model.nodes}:
        raise FeatureInputError(f"No node {v['nodeId']!r} exists in the STM.")
    nodes = [
        n.model_copy(
            update={"support": v["support"], "anchorage": v["anchorage"], "bearing": v["bearingMm"]}
        )
        if n.id == v["nodeId"]
        else n
        for n in model.nodes
    ]
    updated = model.model_copy(update={"nodes": nodes})
    solved = solve_rows(updated)
    models[0] = updated
    path = store_models(ctx, models)
    return result(
        {
            "nodeId": v["nodeId"],
            "support": v["support"],
            "bearingMm": v["bearingMm"],
            "utilisationRatio": solved["utilisation"],
            "savedTo": str(path),
        }
    )


@feature(
    "femStmTopology.tieConstraints",
    "Tie Constraints",
    part="fem",
    fields=[
        text("tieIds", "Constrained tie IDs (comma-separated)", "T1"),
        number("orientationDeg", "Required reinforcement orientation", 0, unit="°"),
        number("toleranceDeg", "Orientation tolerance", 10, unit="°", min=0, max=90),
    ],
    requires_project=False,
)
def tie_constraints(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Check selected tie axes against the specified reinforcement orientation envelope."""
    model = working_model(ctx, v)
    selected = {x.strip() for x in v["tieIds"].split(",") if x.strip()}
    if not selected:
        raise FeatureInputError("Enter at least one tie ID.")
    rows = []
    for tie in (m for m in model.members if m.id in selected and m.kind == "tie"):
        _x0, _y0, dx, dy, _length = geometry(model)[tie.id]
        angle = math.degrees(math.atan2(dy, dx)) % 180
        delta = abs((angle - v["orientationDeg"] + 90) % 180 - 90)
        rows.append(
            {
                "tieId": tie.id,
                "axisDeg": angle,
                "requiredDeg": v["orientationDeg"],
                "deviationDeg": delta,
                "withinTolerance": delta <= v["toleranceDeg"],
            }
        )
    unknown = selected - {x["tieId"] for x in rows}
    if unknown:
        raise FeatureInputError(f"Unknown tension tie IDs: {', '.join(sorted(unknown))}.")
    return result(
        {"tiesChecked": len(rows)},
        [
            table(
                "Tie orientation constraints",
                [
                    ("tieId", "Tie"),
                    ("axisDeg", "Axis", "°"),
                    ("requiredDeg", "Required", "°"),
                    ("deviationDeg", "Deviation", "°"),
                    ("withinTolerance", "Within tolerance"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmTopology.strutBoundaries",
    "Strut Boundaries",
    part="fem",
    fields=[
        number("xMinMm", "Allowed X minimum", 0, unit="mm"),
        number("xMaxMm", "Allowed X maximum", 3000, unit="mm"),
        number("yMinMm", "Allowed Y minimum", 0, unit="mm"),
        number("yMaxMm", "Allowed Y maximum", 1500, unit="mm"),
    ],
    requires_project=False,
)
def strut_boundaries(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Screen the geometry of every compression strut against allowed region boundaries."""
    model = working_model(ctx, v)
    rows = []
    for member in (m for m in model.members if m.kind == "strut"):
        ends = [next(n for n in model.nodes if n.id == key) for key in (member.start, member.end)]
        inside = all(
            v["xMinMm"] <= n.x <= v["xMaxMm"] and v["yMinMm"] <= n.y <= v["yMaxMm"] for n in ends
        )
        rows.append(
            {
                "strutId": member.id,
                "startXmm": ends[0].x,
                "startYmm": ends[0].y,
                "endXmm": ends[1].x,
                "endYmm": ends[1].y,
                "insideBounds": inside,
            }
        )
    return result(
        {"strutsScreened": len(rows), "outsideBounds": sum(not r["insideBounds"] for r in rows)},
        [
            table(
                "Compression strut boundary screen",
                [
                    ("strutId", "Strut"),
                    ("startXmm", "Start X", "mm"),
                    ("startYmm", "Start Y", "mm"),
                    ("endXmm", "End X", "mm"),
                    ("endYmm", "End Y", "mm"),
                    ("insideBounds", "Inside bounds"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmTopology.fixityEnvelope",
    "Fixity Envelope",
    part="fem",
    fields=[
        text("nodeId", "Internal node ID", "C"),
        number("xMinMm", "Permitted X minimum", 1000, unit="mm"),
        number("xMaxMm", "Permitted X maximum", 2000, unit="mm"),
        number("yMinMm", "Permitted Y minimum", 500, unit="mm"),
        number("yMaxMm", "Permitted Y maximum", 1400, unit="mm"),
    ],
    requires_project=False,
)
def fixity_envelope(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Evaluate whether an internal joint remains inside its allowed positional envelope."""
    models = load_stm_file(ctx)
    model = models[0] if models else working_model(ctx, v, kind="dappedEnd")
    node = next((n for n in model.nodes if n.id == v["nodeId"]), None)
    if node is None:
        raise FeatureInputError(f"No node {v['nodeId']!r} exists.")
    if node.support or any(load.node == node.id for case in model.cases for load in case.loads):
        raise FeatureInputError(
            "Fixity envelope applies to an unloaded, unsupported internal node."
        )
    within = v["xMinMm"] <= node.x <= v["xMaxMm"] and v["yMinMm"] <= node.y <= v["yMaxMm"]
    return result(
        {
            "nodeId": node.id,
            "xMm": node.x,
            "yMm": node.y,
            "withinEnvelope": within,
            "movementAllowedXmm": v["xMaxMm"] - v["xMinMm"],
            "movementAllowedYmm": v["yMaxMm"] - v["yMinMm"],
        }
    )


@feature(
    "femStmTopology.concentratedForce",
    "Concentrated Force",
    part="fem",
    fields=[
        text("caseName", "Load case name", "Factored"),
        text("nodeId", "Loaded node ID", "C"),
        number("fxKn", "Horizontal force", 0, unit="kN"),
        number("fyKn", "Vertical force", -1000, unit="kN"),
    ],
    requires_project=True,
)
def concentrated_force(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Assign or replace a concentrated force vector at an existing node and re-solve the case."""
    models, model = project_model(ctx)
    if v["nodeId"] not in {n.id for n in model.nodes}:
        raise FeatureInputError(f"No load node {v['nodeId']!r} exists in the STM.")
    cases = list(model.cases)
    target = next((c for c in cases if c.name == v["caseName"]), None)
    load = StmLoad(node=v["nodeId"], fx=v["fxKn"], fy=v["fyKn"])
    if target is None:
        cases.append(StmLoadCase(name=v["caseName"], loads=[load]))
    else:
        updated_loads = [x for x in target.loads if x.node != v["nodeId"]] + [load]
        cases[cases.index(target)] = target.model_copy(update={"loads": updated_loads})
    updated = model.model_copy(update={"cases": cases})
    solved = solve_rows(updated)
    models[0] = updated
    path = store_models(ctx, models)
    return result(
        {
            "caseName": v["caseName"],
            "nodeId": v["nodeId"],
            "resultingCases": len(updated.cases),
            "utilisationRatio": solved["utilisation"],
            "savedTo": str(path),
        }
    )


@feature(
    "femStmTopology.distributedTransfer",
    "Distributed Transfer",
    part="fem",
    fields=[
        text("caseName", "Load case name", "Factored"),
        text("startNode", "Transfer start node", "A"),
        text("endNode", "Transfer end node", "B"),
        number("loadKnPerM", "Distributed load", 100, unit="kN/m"),
    ],
    requires_project=True,
)
def distributed_transfer(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Convert a uniform line load into equal tributary nodal forces at the member endpoints."""
    models, model = project_model(ctx)
    if v["startNode"] == v["endNode"] or {v["startNode"], v["endNode"]} - {
        n.id for n in model.nodes
    }:
        raise FeatureInputError("Choose two distinct existing transfer nodes.")
    a = next(n for n in model.nodes if n.id == v["startNode"])
    b = next(n for n in model.nodes if n.id == v["endNode"])
    length_m = math.hypot(b.x - a.x, b.y - a.y) / 1000
    total = v["loadKnPerM"] * length_m
    cases = list(model.cases)
    case = next((c for c in cases if c.name == v["caseName"]), None)
    loads = list(case.loads) if case else []
    loads += [StmLoad(node=a.id, fy=-total / 2), StmLoad(node=b.id, fy=-total / 2)]
    updated_case = StmLoadCase(name=v["caseName"], loads=loads)
    cases = [c for c in cases if c.name != v["caseName"]] + [updated_case]
    updated = model.model_copy(update={"cases": cases})
    checked = solve_rows(updated)
    models[0] = updated
    path = store_models(ctx, models)
    return result(
        {
            "lineLengthM": length_m,
            "equivalentLoadKn": total,
            "loadPerNodeKn": total / 2,
            "utilisationRatio": checked["utilisation"],
            "savedTo": str(path),
        },
        notes=[
            "For a uniform line load, each endpoint receives half the total resultant; signs use the model's positive-up Y axis."
        ],
    )


@feature(
    "femStmTopology.directStrut",
    "Direct Strut",
    part="fem",
    fields=[
        text("loadNode", "Load node ID", "C"),
        text("supportNode", "Support node ID", "A"),
        number("widthMm", "Direct strut width", 200, unit="mm", min=1),
    ],
    requires_project=True,
)
def direct_strut(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Connect a concentrated load node directly to a support node with a compression strut."""
    models, model = project_model(ctx)
    if v["loadNode"] == v["supportNode"]:
        raise FeatureInputError("The load and support nodes must be distinct.")
    nodes = {n.id: n for n in model.nodes}
    if (
        v["loadNode"] not in nodes
        or v["supportNode"] not in nodes
        or not nodes[v["supportNode"]].support
    ):
        raise FeatureInputError("Select an existing loaded node and an existing support node.")
    member = StmMember(
        id=next_id("S", {m.id for m in model.members}),
        start=v["loadNode"],
        end=v["supportNode"],
        kind="strut",
        width=v["widthMm"],
        shape="prism",
    )
    updated = model.model_copy(update={"members": [*model.members, member]})
    solved = solve_rows(updated)
    models[0] = updated
    path = store_models(ctx, models)
    return result(
        {
            "strutId": member.id,
            "lengthMm": geometry(updated)[member.id][4],
            "utilisationRatio": solved["utilisation"],
            "savedTo": str(path),
        }
    )


@feature(
    "femStmTopology.nodeAlignment",
    "Node Alignment",
    part="fem",
    fields=[
        text("nodeId", "Internal node ID", "C"),
        number("axisAngleDeg", "Projection-axis angle", 0, unit="°"),
        number("axisOffsetMm", "Axis offset", 0, unit="mm"),
    ],
    requires_project=True,
)
def node_alignment(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Project a free internal node onto a specified construction axis and verify the resulting truss."""
    models, model = project_model(ctx)
    node = next((n for n in model.nodes if n.id == v["nodeId"]), None)
    if node is None or node.support or any(x.node == node.id for c in model.cases for x in c.loads):
        raise FeatureInputError("Choose an existing unloaded, unsupported internal node.")
    theta = math.radians(v["axisAngleDeg"])
    normal = (-math.sin(theta), math.cos(theta))
    distance = node.x * normal[0] + node.y * normal[1] - v["axisOffsetMm"]
    x, y = node.x - distance * normal[0], node.y - distance * normal[1]
    nodes = [n.model_copy(update={"x": x, "y": y}) if n.id == node.id else n for n in model.nodes]
    updated = model.model_copy(update={"nodes": nodes})
    checked = solve_rows(updated)
    models[0] = updated
    path = store_models(ctx, models)
    return result(
        {
            "nodeId": node.id,
            "xMm": x,
            "yMm": y,
            "movementMm": abs(distance),
            "utilisationRatio": checked["utilisation"],
            "savedTo": str(path),
        }
    )


@feature(
    "femStmTopology.angleEnvelope",
    "Angle Envelope",
    part="fem",
    fields=[
        number("minimumAngleDeg", "Minimum strut-tie angle", 25, unit="°", min=0, max=90),
        number("maximumAngleDeg", "Maximum strut-tie angle", 75, unit="°", min=0, max=90),
    ],
    requires_project=False,
)
def angle_envelope(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Check all strut-to-tie joint angles against user-defined constructability limits."""
    model = working_model(ctx, v)
    if v["maximumAngleDeg"] < v["minimumAngleDeg"]:
        raise FeatureInputError("Maximum angle must be no smaller than minimum angle.")
    coords = {n.id: (n.x, n.y) for n in model.nodes}
    rows = []
    for node in model.nodes:
        members = [m for m in model.members if node.id in (m.start, m.end)]
        for s in (m for m in members if m.kind == "strut"):
            for t in (m for m in members if m.kind == "tie"):
                sv = coords[s.end if s.start == node.id else s.start]
                tv = coords[t.end if t.start == node.id else t.start]
                a = (sv[0] - node.x, sv[1] - node.y)
                b = (tv[0] - node.x, tv[1] - node.y)
                angle = math.degrees(
                    math.acos(
                        min(1, abs(a[0] * b[0] + a[1] * b[1]) / (math.hypot(*a) * math.hypot(*b)))
                    )
                )
                rows.append(
                    {
                        "nodeId": node.id,
                        "strutId": s.id,
                        "tieId": t.id,
                        "angleDeg": angle,
                        "withinEnvelope": v["minimumAngleDeg"] <= angle <= v["maximumAngleDeg"],
                    }
                )
    return result(
        {"jointAngles": len(rows)},
        [
            table(
                "Strut-to-tie angle envelope",
                [
                    ("nodeId", "Node"),
                    ("strutId", "Strut"),
                    ("tieId", "Tie"),
                    ("angleDeg", "Angle", "°"),
                    ("withinEnvelope", "Within limits"),
                ],
                rows,
            )
        ],
    )


@feature("femStmTopology.exportTruss", "Export Truss", part="fem", fields=[], requires_project=True)
def export_truss(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Export truss vertices and member connectivity as a standards-based DXF line drawing."""
    import ezdxf

    _models, model = project_model(ctx)
    document = ezdxf.new("R2010")
    space = document.modelspace()
    for node in model.nodes:
        space.add_circle(
            (node.x, node.y), max(5, model.thickness * 0.02), dxfattribs={"layer": "STM-NODES"}
        )
        space.add_text(node.id, dxfattribs={"height": 20, "insert": (node.x, node.y)})
    for member in model.members:
        start = next(n for n in model.nodes if n.id == member.start)
        end = next(n for n in model.nodes if n.id == member.end)
        space.add_line(
            (start.x, start.y), (end.x, end.y), dxfattribs={"layer": "STM-" + member.kind.upper()}
        )
    target = ctx.root / "08 FEM" / "exports" / "stm-truss.dxf"
    target.parent.mkdir(parents=True, exist_ok=True)
    document.saveas(target)
    return result(
        {
            "nodesExported": len(model.nodes),
            "membersExported": len(model.members),
            "savedTo": str(target),
        }
    )

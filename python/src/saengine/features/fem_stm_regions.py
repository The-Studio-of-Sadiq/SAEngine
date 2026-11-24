"""D-region definition, member archetypes, reinforcement, and validation."""

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
    table,
    text,
)
from saengine.features.fem_stm_common import (
    export_json,
    next_id,
    project_model,
    solve_rows,
    store_models,
    working_model,
)
from saengine.library.strut_and_tie import StmLoad, StmLoadCase, StmMember, StmModel, StmNode


@feature(
    "femStmRegions.discontinuityRegion",
    "Discontinuity Region",
    part="fem",
    fields=[
        number("regionDepthMm", "D-region depth", 1000, unit="mm", min=1),
    ],
    requires_project=False,
)
def discontinuity_region(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Relate a region's entered depth to the active pack's D-region extent."""
    model = working_model(ctx, v)
    extent = stm.factor("dRegionDepth") * model.depth
    requested = v["regionDepthMm"]
    return result(
        {
            "modelDepthMm": model.depth,
            "packExtentMm": extent,
            "enteredRegionDepthMm": requested,
            "coveredByPackExtent": requested <= extent,
        },
        notes=[
            "The pack depth factor defines a geometric extent from the discontinuity; the engineer must identify all load disturbances."
        ],
    )


@feature(
    "femStmRegions.deepBeamRegion",
    "Deep Beam Region",
    part="fem",
    fields=[
        number("spanMm", "Clear span", 3000, unit="mm", min=100),
        number("depthMm", "Overall depth", 1500, unit="mm", min=100),
        number("widthMm", "Thickness", 300, unit="mm", min=50),
        number("loadKn", "Factored point load", 1000, unit="kN", min=0.1),
    ],
    requires_project=True,
)
def deep_beam_region(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Create a point-loaded deep-beam STM and persist its actual truss geometry and support conditions."""
    model = stm_model.template(
        "deepBeam",
        {
            "span": v["spanMm"],
            "depth": v["depthMm"],
            "thickness": v["widthMm"],
            "load": v["loadKn"],
        },
    )
    models = []
    from saengine.features.fem_common import load_stm_file

    if ctx.root is not None:
        models = load_stm_file(ctx)
    models.append(model)
    path = store_models(ctx, models)
    checked = stm_model.check_model(model)
    return result(
        {
            "modelName": model.name,
            "spanMm": v["spanMm"],
            "depthMm": v["depthMm"],
            "nodes": len(model.nodes),
            "members": len(model.members),
            "savedTo": str(path),
            "utilisationRatio": checked["utilisation"],
        }
    )


@feature(
    "femStmRegions.corbelRegion",
    "Corbel Region",
    part="fem",
    fields=[
        number("depthMm", "Corbel depth", 500, unit="mm", min=100),
        number("thicknessMm", "Corbel width", 400, unit="mm", min=50),
        number("shearSpanMm", "Shear span", 250, unit="mm", min=10),
        number("loadKn", "Factored vertical load", 400, unit="kN", min=0.1),
        number("horizontalKn", "Horizontal load", 80, unit="kN", min=0),
    ],
    requires_project=True,
)
def corbel_region(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Create and save a corbel strut-tie model with independent vertical and horizontal load inputs."""
    model = stm_model.template(
        "corbel",
        {
            "depth": v["depthMm"],
            "thickness": v["thicknessMm"],
            "shearSpan": v["shearSpanMm"],
            "load": v["loadKn"],
            "horizontal": v["horizontalKn"],
        },
    )
    from saengine.features.fem_common import load_stm_file

    models = load_stm_file(ctx) if ctx.root else []
    models.append(model)
    path = store_models(ctx, models)
    checked = stm_model.check_model(model)
    return result(
        {
            "modelName": model.name,
            "loadKn": v["loadKn"],
            "horizontalKn": v["horizontalKn"],
            "utilisationRatio": checked["utilisation"],
            "savedTo": str(path),
        }
    )


@feature(
    "femStmRegions.splitStrut",
    "Split Strut",
    part="fem",
    fields=[
        text("memberId", "Member ID to split", "S1"),
    ],
    requires_project=True,
)
def split_strut(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Split a selected member at its midpoint and preserve its axial design properties."""
    models, model = project_model(ctx)
    member = next((m for m in model.members if m.id == v["memberId"]), None)
    if member is None:
        raise FeatureInputError(f"No member {v['memberId']!r} exists in the STM.")
    if member.kind != "strut":
        raise FeatureInputError(
            "Select a compression strut; tie splitting needs an explicit bar-curtailment design."
        )
    nodes = {n.id: n for n in model.nodes}
    a, b = nodes[member.start], nodes[member.end]
    node_id = next_id("N", set(nodes))
    middle = StmNode(id=node_id, x=(a.x + b.x) / 2, y=(a.y + b.y) / 2)
    first = member.model_copy(update={"end": node_id})
    second = member.model_copy(
        update={"id": next_id("S", {m.id for m in model.members}), "start": node_id}
    )
    members = [x for x in model.members if x.id != member.id] + [first, second]
    models[0] = model.model_copy(update={"nodes": [*model.nodes, middle], "members": members})
    path = store_models(ctx, models)
    return result(
        {
            "splitMember": member.id,
            "newNode": node_id,
            "resultingMembers": [first.id, second.id],
            "savedTo": str(path),
        }
    )


@feature(
    "femStmRegions.mergeStruts",
    "Merge Struts",
    part="fem",
    fields=[
        text("firstMember", "First member ID", "S1"),
        text("secondMember", "Second member ID", "S2"),
    ],
    requires_project=True,
)
def merge_struts(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Merge two collinear members sharing a node, only when kind, shape, and steel match."""
    models, model = project_model(ctx)
    first = next((m for m in model.members if m.id == v["firstMember"]), None)
    second = next((m for m in model.members if m.id == v["secondMember"]), None)
    if not first or not second or first.id == second.id:
        raise FeatureInputError("Choose two distinct existing members.")
    if first.kind != "strut" or second.kind != "strut":
        raise FeatureInputError("Only compression struts can be merged by this operation.")
    shared = {first.start, first.end} & {second.start, second.end}
    if len(shared) != 1 or first.shape != second.shape or first.steelArea != second.steelArea:
        raise FeatureInputError(
            "The struts must share exactly one node and have matching shape and compression steel."
        )
    joint = next(iter(shared))
    outer_a = next(x for x in (first.start, first.end) if x != joint)
    outer_b = next(x for x in (second.start, second.end) if x != joint)
    pts = {n.id: (n.x, n.y) for n in model.nodes}
    u = (pts[joint][0] - pts[outer_a][0], pts[joint][1] - pts[outer_a][1])
    w = (pts[outer_b][0] - pts[joint][0], pts[outer_b][1] - pts[joint][1])
    if abs(u[0] * w[1] - u[1] * w[0]) > 1e-6 * max(math.hypot(*u) * math.hypot(*w), 1):
        raise FeatureInputError("The shared-node struts are not collinear.")
    merged = first.model_copy(
        update={
            "start": outer_a,
            "end": outer_b,
            "width": min(x for x in (first.width, second.width) if x > 0),
        }
    )
    members = [m for m in model.members if m.id not in (first.id, second.id)] + [merged]
    models[0] = model.model_copy(update={"members": members})
    path = store_models(ctx, models)
    return result(
        {"mergedMember": merged.id, "removedMembers": [first.id, second.id], "savedTo": str(path)},
        notes=["The shared node remains in the model for auditability."],
    )


@feature(
    "femStmRegions.fanDetailing",
    "Fan Detailing",
    part="fem",
    fields=[
        number("availableWidthMm", "Available reinforcement width", 500, unit="mm", min=1),
        number("coverMm", "Clear cover", 40, unit="mm", min=0),
        number("barDiameterMm", "Tie bar diameter", 16, unit="mm", min=1),
    ],
    requires_project=False,
)
def fan_detailing(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Distribute fan-zone tie bars by force share and check the available clear bar width."""
    model = working_model(ctx, v)
    checked = solve_rows(model)
    ties = [m for m in model.members if m.kind == "tie"]
    if not ties:
        raise FeatureInputError("The model has no ties to detail as a reinforcement fan.")
    forces = {
        m.id: abs(next(x["force"] for x in checked["members"] if x["id"] == m.id)) for m in ties
    }
    total = sum(forces.values())
    area = math.pi * v["barDiameterMm"] ** 2 / 4
    clear = v["availableWidthMm"] - 2 * v["coverMm"]
    rows = [
        {
            "tieId": m.id,
            "forceShare": forces[m.id] / total if total else 0,
            "barCount": max(1, math.ceil(forces[m.id] * 1000 / (stm.phi() * model.fy * area))),
            "availableWidthMm": clear,
        }
        for m in ties
    ]
    for row in rows:
        row["fits"] = row["barCount"] * v["barDiameterMm"] <= clear
    return result(
        {"fanTies": len(rows), "totalTieForceKn": total},
        [
            table(
                "Fan bar distribution",
                [
                    ("tieId", "Tie"),
                    ("forceShare", "Force share"),
                    ("barCount", "Bars"),
                    ("availableWidthMm", "Clear width", "mm"),
                    ("fits", "Fits"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmRegions.pileCapRegion",
    "Pile Cap Region",
    part="fem",
    fields=[
        number("pileSpacingMm", "Pile centre spacing", 1800, unit="mm", min=100),
        number("effectiveDepthMm", "Effective depth", 600, unit="mm", min=100),
        number("thicknessMm", "Cap thickness", 800, unit="mm", min=100),
        number("columnLoadKn", "Factored column load", 1500, unit="kN", min=0.1),
        number("fcMpa", "Concrete strength", 35, unit="MPa", min=1),
        number("fyMpa", "Rebar yield strength", 420, unit="MPa", min=1),
    ],
    requires_project=True,
)
def pile_cap_region(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Build a symmetric two-pile cap load path with column load, pile supports, diagonal struts, and bottom tie."""
    half = v["pileSpacingMm"] / 2
    top = v["effectiveDepthMm"]
    nodes = [
        StmNode(id="P1", x=0, y=0, support="pin", bearing=300, anchorage="through"),
        StmNode(id="P2", x=2 * half, y=0, support="rollerX", bearing=300, anchorage="through"),
        StmNode(id="C", x=half, y=top, bearing=400),
    ]
    members = [
        StmMember(id="S1", start="P1", end="C", width=250),
        StmMember(id="S2", start="P2", end="C", width=250),
        StmMember(id="T1", start="P1", end="P2", kind="tie", barArea=2000, barDiameter=20),
    ]
    model = StmModel(
        name="Two-pile cap",
        template="pileCap",
        thickness=v["thicknessMm"],
        depth=top,
        fc=v["fcMpa"],
        fy=v["fyMpa"],
        nodes=nodes,
        members=members,
        cases=[
            StmLoadCase(
                name="Factored column load", loads=[StmLoad(node="C", fy=-v["columnLoadKn"])]
            )
        ],
    )
    from saengine.features.fem_common import load_stm_file

    models = load_stm_file(ctx) if ctx.root else []
    models.append(model)
    path = store_models(ctx, models)
    checked = stm_model.check_model(model)
    if checked["problems"]:
        raise FeatureInputError("; ".join(checked["problems"]))
    return result(
        {
            "modelName": model.name,
            "pileSpacingMm": v["pileSpacingMm"],
            "columnLoadKn": v["columnLoadKn"],
            "utilisationRatio": checked["utilisation"],
            "savedTo": str(path),
        }
    )


@feature(
    "femStmRegions.openingRegion",
    "Opening Region",
    part="fem",
    fields=[
        number("openingXmm", "Opening centre X", 1500, unit="mm"),
        number("openingYmm", "Opening centre Y", 600, unit="mm"),
        number("openingWidthMm", "Opening width", 400, unit="mm", min=1),
        number("openingHeightMm", "Opening height", 300, unit="mm", min=1),
    ],
    requires_project=False,
)
def opening_region(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Identify STM members crossing an entered opening rectangle and report their axis clearance."""
    model = working_model(ctx, v)
    xlo, xhi = v["openingXmm"] - v["openingWidthMm"] / 2, v["openingXmm"] + v["openingWidthMm"] / 2
    ylo, yhi = (
        v["openingYmm"] - v["openingHeightMm"] / 2,
        v["openingYmm"] + v["openingHeightMm"] / 2,
    )
    rows = []
    for member in model.members:
        a = next(n for n in model.nodes if n.id == member.start)
        b = next(n for n in model.nodes if n.id == member.end)
        crosses = (
            min(a.x, b.x) < xhi
            and max(a.x, b.x) > xlo
            and min(a.y, b.y) < yhi
            and max(a.y, b.y) > ylo
        )
        rows.append({"memberId": member.id, "kind": member.kind, "crossesOpening": crosses})
    return result(
        {"openingMembers": sum(x["crossesOpening"] for x in rows), "reviewedMembers": len(rows)},
        [
            table(
                "Members at opening",
                [
                    ("memberId", "Member"),
                    ("kind", "Kind"),
                    ("crossesOpening", "Intersects entered bounds"),
                ],
                rows,
            )
        ],
        [
            "This axis-aligned bounding-box screening identifies load-path conflicts; it does not replace a perimeter STM."
        ],
    )


@feature(
    "femStmRegions.bracketRegion",
    "Bracket Region",
    part="fem",
    fields=[
        number("projectionMm", "Bracket projection / shear span", 250, unit="mm", min=10),
        number("depthMm", "Bracket depth", 500, unit="mm", min=100),
        number("widthMm", "Bracket thickness", 400, unit="mm", min=50),
        number("verticalLoadKn", "Vertical load", 400, unit="kN", min=0.1),
        number("horizontalLoadKn", "Horizontal load", 80, unit="kN", min=0),
    ],
    requires_project=True,
)
def bracket_region(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Generate a bracket-region STM using the entered projection, section, and load components."""
    model = stm_model.template(
        "corbel",
        {
            "shearSpan": v["projectionMm"],
            "depth": v["depthMm"],
            "thickness": v["widthMm"],
            "load": v["verticalLoadKn"],
            "horizontal": v["horizontalLoadKn"],
        },
    )
    from saengine.features.fem_common import load_stm_file

    models = load_stm_file(ctx) if ctx.root else []
    models.append(model)
    path = store_models(ctx, models)
    checked = stm_model.check_model(model)
    return result(
        {
            "bracketProjectionMm": v["projectionMm"],
            "utilisationRatio": checked["utilisation"],
            "modelName": model.name,
            "savedTo": str(path),
        }
    )


@feature(
    "femStmRegions.beamColumnJoint",
    "Beam Column Joint",
    part="fem",
    fields=[
        number("jointDepthMm", "Joint depth", 500, unit="mm", min=100),
        number("closingMomentKnM", "Closing moment", 200, unit="kN·m", min=0.1),
        number("thicknessMm", "Joint thickness", 300, unit="mm", min=50),
    ],
    requires_project=True,
)
def beam_column_joint(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Construct a closing-moment frame-corner truss to represent a beam-column joint discontinuity."""
    model = stm_model.template(
        "frameCorner",
        {
            "depth": v["jointDepthMm"],
            "moment": v["closingMomentKnM"],
            "thickness": v["thicknessMm"],
        },
    )
    from saengine.features.fem_common import load_stm_file

    models = load_stm_file(ctx) if ctx.root else []
    models.append(model)
    path = store_models(ctx, models)
    checked = stm_model.check_model(model)
    return result(
        {
            "jointDepthMm": v["jointDepthMm"],
            "closingMomentKnM": v["closingMomentKnM"],
            "utilisationRatio": checked["utilisation"],
            "savedTo": str(path),
        }
    )


@feature(
    "femStmRegions.supportRegion",
    "Support Region",
    part="fem",
    fields=[
        text("nodeId", "Support node ID", "A"),
        number("bearingMm", "Effective bearing length", 300, unit="mm", min=1),
    ],
    requires_project=True,
)
def support_region(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Define the bearing-face length of a project support node for nodal capacity checking."""
    models, model = project_model(ctx)
    if v["nodeId"] not in {n.id for n in model.nodes}:
        raise FeatureInputError(f"No support node {v['nodeId']!r} exists.")
    nodes = [
        n.model_copy(update={"bearing": v["bearingMm"]}) if n.id == v["nodeId"] else n
        for n in model.nodes
    ]
    models[0] = model.model_copy(update={"nodes": nodes})
    path = store_models(ctx, models)
    return result(
        {
            "nodeId": v["nodeId"],
            "bearingAreaMm2": v["bearingMm"] * model.thickness,
            "savedTo": str(path),
        }
    )


@feature(
    "femStmRegions.bRegionLimit", "B-Region Limit", part="fem", fields=[], requires_project=False
)
def b_region_limit(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Locate the onset of the adjacent B-region from the pack's D-region depth proportion."""
    model = working_model(ctx, v)
    depth = model.depth * stm.factor("dRegionDepth")
    return result(
        {"dRegionExtentMm": depth, "bRegionStartsAtMm": depth, "memberDepthMm": model.depth},
        notes=[
            "The boundary is measured from the discontinuity; conventional beam theory applies outside the disturbed region."
        ],
    )


@feature(
    "femStmRegions.dRegionLimit",
    "D-Region Limit",
    part="fem",
    fields=[
        number("discontinuityXmm", "Discontinuity coordinate X", 0, unit="mm"),
    ],
    requires_project=False,
)
def d_region_limit(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Mark the longitudinal D-region interval using the code-pack depth extent."""
    model = working_model(ctx, v)
    extent = model.depth * stm.factor("dRegionDepth")
    return result(
        {
            "startXmm": v["discontinuityXmm"],
            "endXmm": v["discontinuityXmm"] + extent,
            "extentMm": extent,
            "depthFactor": stm.factor("dRegionDepth"),
        }
    )


@feature(
    "femStmRegions.boundaryTrimming",
    "Boundary Trimming",
    part="fem",
    fields=[
        number("xMinMm", "Boundary minimum X", 0, unit="mm"),
        number("xMaxMm", "Boundary maximum X", 3000, unit="mm"),
        number("yMinMm", "Boundary minimum Y", 0, unit="mm"),
        number("yMaxMm", "Boundary maximum Y", 1500, unit="mm"),
    ],
    requires_project=False,
)
def boundary_trimming(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Screen region nodes and members against the actual entered member boundary without deleting data."""
    model = working_model(ctx, v)
    if v["xMaxMm"] <= v["xMinMm"] or v["yMaxMm"] <= v["yMinMm"]:
        raise FeatureInputError("Each maximum boundary coordinate must exceed its minimum.")
    inside = {
        n.id
        for n in model.nodes
        if v["xMinMm"] <= n.x <= v["xMaxMm"] and v["yMinMm"] <= n.y <= v["yMaxMm"]
    }
    rows = [
        {
            "memberId": m.id,
            "bothEndsInside": m.start in inside and m.end in inside,
            "crossesBoundary": (m.start in inside) != (m.end in inside),
        }
        for m in model.members
    ]
    return result(
        {
            "nodesInside": len(inside),
            "nodesOutside": len(model.nodes) - len(inside),
            "membersCrossingBoundary": sum(r["crossesBoundary"] for r in rows),
        },
        [
            table(
                "Boundary screening",
                [
                    ("memberId", "Member"),
                    ("bothEndsInside", "Inside"),
                    ("crossesBoundary", "Crosses boundary"),
                ],
                rows,
            )
        ],
        [
            "Geometry is reported before trimming; members are not silently deleted from the project."
        ],
    )


@feature(
    "femStmRegions.regionLabels", "Region Labels", part="fem", fields=[], requires_project=False
)
def region_labels(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Label model components by region role, node support, load, and member type."""
    model = working_model(ctx, v)
    loaded = {load.node for case in model.cases for load in case.loads}
    rows = [
        {
            "entity": n.id,
            "regionRole": "load and support"
            if n.id in loaded and n.support
            else "load"
            if n.id in loaded
            else "support"
            if n.support
            else "internal joint",
        }
        for n in model.nodes
    ]
    rows.extend(
        {
            "entity": m.id,
            "regionRole": f"{m.kind} ({m.shape})" if m.kind == "strut" else "tension tie",
        }
        for m in model.members
    )
    return result(
        {"labelledEntities": len(rows)},
        [table("D-region component labels", [("entity", "Entity"), ("regionRole", "Role")], rows)],
    )


@feature(
    "femStmRegions.regionRebar",
    "Region Rebar",
    part="fem",
    fields=[
        number("tieBarDiameterMm", "Tie bar diameter", 20, unit="mm", min=1),
    ],
    requires_project=False,
)
def region_rebar(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Design tie-bar quantities for the region's envelope tie forces."""
    model = working_model(ctx, v)
    checked = solve_rows(model)
    bar_area = math.pi * v["tieBarDiameterMm"] ** 2 / 4
    rows = []
    for tie in (m for m in model.members if m.kind == "tie"):
        force = abs(next(r["force"] for r in checked["members"] if r["id"] == tie.id)) * 1000
        req = force / (stm.phi() * model.fy)
        rows.append(
            {
                "tieId": tie.id,
                "requiredAreaMm2": req,
                "barCount": math.ceil(req / bar_area),
                "barDiameterMm": v["tieBarDiameterMm"],
            }
        )
    return result(
        {"tiesDesigned": len(rows)},
        [
            table(
                "D-region tie reinforcement",
                [
                    ("tieId", "Tie"),
                    ("requiredAreaMm2", "Required As", "mm²"),
                    ("barCount", "Bar count"),
                    ("barDiameterMm", "Bar diameter", "mm"),
                ],
                rows,
            )
        ],
        ["Tie strength uses the pack's strut-and-tie resistance factor."],
    )


@feature(
    "femStmRegions.fanReinforcement",
    "Fan Reinforcement",
    part="fem",
    fields=[
        number("barAreaMm2", "Bar area per fan leg", 157, unit="mm²", min=1),
    ],
    requires_project=False,
)
def fan_reinforcement(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Allocate fan reinforcement by each tension tie's share of the total fan force."""
    model = working_model(ctx, v)
    checked = solve_rows(model)
    rows = []
    ties = [m for m in model.members if m.kind == "tie"]
    total = sum(abs(next(r["force"] for r in checked["members"] if r["id"] == m.id)) for m in ties)
    for tie in ties:
        force = abs(next(r["force"] for r in checked["members"] if r["id"] == tie.id)) * 1000
        required = force / (stm.phi() * model.fy)
        rows.append(
            {
                "tieId": tie.id,
                "forceShare": force / 1000 / total if total else 0,
                "requiredSteelMm2": required,
                "barLegs": math.ceil(required / v["barAreaMm2"]),
                "providedSteelMm2": math.ceil(required / v["barAreaMm2"]) * v["barAreaMm2"],
            }
        )
    return result(
        {"fanComponents": len(rows), "totalTieForceKn": total},
        [
            table(
                "Fan reinforcement demand",
                [
                    ("tieId", "Tie"),
                    ("forceShare", "Force share"),
                    ("requiredSteelMm2", "Required As", "mm²"),
                    ("barLegs", "Legs"),
                    ("providedSteelMm2", "Provided As", "mm²"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmRegions.confinementLayout",
    "Confinement Layout",
    part="fem",
    fields=[
        number("barDiameterMm", "Transverse bar diameter", 10, unit="mm", min=1),
        number("spacingMm", "Transverse bar spacing", 150, unit="mm", min=1),
    ],
    requires_project=False,
)
def confinement_layout(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Calculate provided transverse steel ratio and compare it with the pack crack-control requirement."""
    model = working_model(ctx, v)
    area = math.pi * v["barDiameterMm"] ** 2 / 4
    provided = area / (model.thickness * v["spacingMm"])
    required = stm.factor("webRatio")
    return result(
        {
            "providedRatio": provided,
            "requiredRatio": required,
            "passes": provided >= required,
            "barAreaMm2": area,
            "spacingMm": v["spacingMm"],
        },
        notes=[
            "This web ratio screens confinement across bottle-shaped struts; full anchorage and distribution still require detailing."
        ],
    )


@feature(
    "femStmRegions.edgeReinforcement",
    "Edge Reinforcement",
    part="fem",
    fields=[
        number("perimeterBarSpacingMm", "Perimeter bar spacing", 200, unit="mm", min=1),
        number("barDiameterMm", "Perimeter bar diameter", 12, unit="mm", min=1),
    ],
    requires_project=False,
)
def edge_reinforcement(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Estimate perimeter bar count for the model's rectangular depth and projected node span."""
    model = working_model(ctx, v)
    xs = [n.x for n in model.nodes]
    ys = [n.y for n in model.nodes]
    span, depth = max(xs) - min(xs), max(ys) - min(ys)
    perimeter = 2 * (span + depth)
    count = math.ceil(perimeter / v["perimeterBarSpacingMm"])
    return result(
        {
            "perimeterMm": perimeter,
            "barCount": count,
            "barAreaMm2": math.pi * v["barDiameterMm"] ** 2 / 4,
            "totalSteelMm2": count * math.pi * v["barDiameterMm"] ** 2 / 4,
        },
        notes=[
            "Perimeter bars are an edge-detailing quantity only; they are not credited toward strut or tie strength."
        ],
    )


@feature(
    "femStmRegions.regionValidation",
    "Region Validation",
    part="fem",
    fields=[],
    requires_project=False,
)
def region_validation(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Validate region topology, load cases, equilibrium solvability, and all code-pack component checks."""
    model = working_model(ctx, v)
    checked = stm_model.check_model(model)
    return result(
        {
            "isSolvable": not checked["problems"],
            "overallPass": checked["ok"],
            "utilisationRatio": checked["utilisation"],
            "problems": len(checked["problems"]),
            "warnings": len(checked["warnings"]),
        },
        [
            table(
                "Model checks",
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
                    for x in checked["checks"]
                ],
            )
        ],
        [*checked["problems"], *checked["warnings"]],
    )


@feature(
    "femStmRegions.regionReport", "Region Report", part="fem", fields=[], requires_project=True
)
def region_report(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Publish region geometry, solved force envelopes, code-pack checks, assumptions, and warnings."""
    _models, model = project_model(ctx)
    checked = stm_model.check_model(model)
    path = export_json(
        ctx,
        "stm-region-report.json",
        {"region": model.model_dump(mode="json"), "analysis": checked},
    )
    return result(
        {
            "regionName": model.name,
            "checks": len(checked["checks"]),
            "overallPass": checked["ok"],
            "savedTo": str(path),
        }
    )


@feature(
    "femStmRegions.regionSnapshot", "Region Snapshot", part="fem", fields=[], requires_project=True
)
def region_snapshot(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Save a geometric and force snapshot suitable for comparing region schemes."""
    _models, model = project_model(ctx)
    checked = solve_rows(model)
    path = export_json(
        ctx,
        "stm-region-snapshot.json",
        {
            "name": model.name,
            "nodes": [{"id": n.id, "xMm": n.x, "yMm": n.y} for n in model.nodes],
            "members": checked["members"],
            "utilisationRatio": checked["utilisation"],
        },
    )
    return result(
        {
            "regionName": model.name,
            "nodeCount": len(model.nodes),
            "savedTo": str(path),
            "utilisationRatio": checked["utilisation"],
        }
    )


@feature(
    "femStmRegions.designNotes",
    "Design Notes",
    part="fem",
    fields=[
        text(
            "assumptions",
            "Region assumptions",
            "Planar load path; bearing faces act over entered dimensions.",
        ),
        text("reviewer", "Author", ""),
    ],
    requires_project=True,
)
def design_notes(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Record project-specific region assumptions with the checked model identity."""
    _models, model = project_model(ctx)
    if not v["assumptions"].strip():
        raise FeatureInputError("Enter at least one region-specific design assumption.")
    path = export_json(
        ctx,
        "stm-region-notes.json",
        {
            "model": model.name,
            "member": model.member,
            "author": v["reviewer"].strip(),
            "assumptions": [line.strip() for line in v["assumptions"].splitlines() if line.strip()],
            "fcMpa": model.fc,
            "fyMpa": model.fy,
            "thicknessMm": model.thickness,
        },
    )
    return result(
        {
            "modelName": model.name,
            "assumptionCount": len(v["assumptions"].splitlines()),
            "savedTo": str(path),
        }
    )

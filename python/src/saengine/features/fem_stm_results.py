"""Analysis result views, reinforcement schedules, and deliverables for STM models."""

from __future__ import annotations

import math
from typing import Any

from saengine.design import stm, stm_model
from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.fem_stm_common import (
    export_json,
    geometry,
    project_model,
    solve_rows,
    working_model,
)


@feature(
    "femStmResults.forceDiagram", "Force Diagram", part="fem", fields=[], requires_project=False
)
def force_diagram(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Provide the node coordinates and solved axial member forces behind the force diagram."""
    model = working_model(ctx, v)
    checked = solve_rows(model)
    coords = {n.id: n for n in model.nodes}
    rows = [
        {
            "memberId": m.id,
            "kind": m.kind,
            "startNode": m.start,
            "endNode": m.end,
            "x0Mm": coords[m.start].x,
            "y0Mm": coords[m.start].y,
            "x1Mm": coords[m.end].x,
            "y1Mm": coords[m.end].y,
            "forceKn": next(r["force"] for r in checked["members"] if r["id"] == m.id),
        }
        for m in model.members
    ]
    return result(
        {"modelName": model.name, "memberCount": len(rows)},
        [
            table(
                "Force diagram data",
                [
                    ("memberId", "Member"),
                    ("kind", "Kind"),
                    ("startNode", "Start"),
                    ("endNode", "End"),
                    ("x0Mm", "x0", "mm"),
                    ("y0Mm", "y0", "mm"),
                    ("x1Mm", "x1", "mm"),
                    ("y1Mm", "y1", "mm"),
                    ("forceKn", "Axial force", "kN"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmResults.requiredSteel", "Required Steel", part="fem", fields=[], requires_project=False
)
def required_steel(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Calculate required tie reinforcement from each envelope tension and the pack resistance factor."""
    model = working_model(ctx, v)
    checked = solve_rows(model)
    rows = []
    for member in model.members:
        if member.kind == "tie":
            demand = (
                abs(next(r["force"] for r in checked["members"] if r["id"] == member.id)) * 1000
            )
            prestress = stm.tie_nominal(
                0, model.fy, member.prestressArea, member.fse, member.fpy, member.bonded
            )
            area = max((demand / stm.phi() - prestress) / model.fy, 0)
            rows.append(
                {
                    "tieId": member.id,
                    "tensionKn": demand / 1000,
                    "requiredSteelMm2": area,
                    "providedSteelMm2": member.barArea,
                    "resistanceFactor": stm.phi(),
                }
            )
    return result(
        {"tiesDesigned": len(rows)},
        [
            table(
                "Tie reinforcement demand",
                [
                    ("tieId", "Tie"),
                    ("tensionKn", "Tension", "kN"),
                    ("requiredSteelMm2", "Required As", "mm²"),
                    ("providedSteelMm2", "Provided As", "mm²"),
                    ("resistanceFactor", "φ"),
                ],
                rows,
            )
        ],
        ["Tie resistance and φ are read from the active code pack."],
    )


@feature(
    "femStmResults.crackControl", "Crack Control", part="fem", fields=[], requires_project=False
)
def crack_control(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Check web reinforcement ratio and orientation for each bottle-shaped strut."""
    model = working_model(ctx, v)
    required = stm.factor("webRatio")
    web_ratio = stm.web_ratio([(w.area, w.spacing, w.angle) for w in model.web], model.thickness)
    rows = []
    for member in model.members:
        if member.kind != "strut" or member.shape != "bottle":
            continue
        direction = geometry(model)[member.id]
        angles = [
            math.degrees(
                math.acos(
                    min(
                        1.0,
                        abs(
                            direction[2] * math.cos(math.radians(layer.angle))
                            + direction[3] * math.sin(math.radians(layer.angle))
                        ),
                    )
                )
            )
            for layer in model.web
        ]
        angle = min(angles, default=None)
        rows.append(
            {
                "strutId": member.id,
                "providedRatio": web_ratio,
                "requiredRatio": required,
                "webDirectionAngleDeg": angle,
                "passes": web_ratio >= required
                and (angle is None or angle >= stm.factor("webAngleMin")),
            }
        )
    return result(
        {"bottleStrutsChecked": len(rows), "webRatio": web_ratio, "requiredWebRatio": required},
        [
            table(
                "Strut crack-control reinforcement",
                [
                    ("strutId", "Strut"),
                    ("providedRatio", "Provided ratio"),
                    ("requiredRatio", "Required ratio"),
                    ("webDirectionAngleDeg", "Least angle", "°"),
                    ("passes", "Pass"),
                ],
                rows,
            )
        ],
        [
            "Code-pack ratio and angle limits are used for web steel; no web reinforcement is not treated as adequate."
        ],
    )


@feature(
    "femStmResults.tieLayout",
    "Tie Layout",
    part="fem",
    fields=[
        number("barDiameterMm", "Bar diameter", 20, unit="mm", min=1),
        number("coverMm", "Clear cover", 40, unit="mm", min=0),
    ],
    requires_project=False,
)
def tie_layout(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Size a practical row of longitudinal bars from tie demand and available tie width."""
    model = working_model(ctx, v)
    checked = solve_rows(model)
    bar_area = math.pi * v["barDiameterMm"] ** 2 / 4
    rows = []
    for tie in (m for m in model.members if m.kind == "tie"):
        force = abs(next(r["force"] for r in checked["members"] if r["id"] == tie.id)) * 1000
        need = force / (stm.phi() * model.fy)
        count = max(1, math.ceil(need / bar_area))
        clear = tie.width - 2 * v["coverMm"] - count * v["barDiameterMm"]
        rows.append(
            {
                "tieId": tie.id,
                "barCount": count,
                "barDiameterMm": v["barDiameterMm"],
                "requiredSteelMm2": need,
                "providedSteelMm2": count * bar_area,
                "clearSpacingMm": clear / max(count - 1, 1) if count > 1 else None,
                "fitsTieWidth": tie.width <= 0 or clear >= 0,
            }
        )
    return result(
        {"tiesLaidOut": len(rows)},
        [
            table(
                "Tie bar arrangement",
                [
                    ("tieId", "Tie"),
                    ("barCount", "Count"),
                    ("barDiameterMm", "Diameter", "mm"),
                    ("requiredSteelMm2", "Required As", "mm²"),
                    ("providedSteelMm2", "Provided As", "mm²"),
                    ("clearSpacingMm", "Clear spacing", "mm"),
                    ("fitsTieWidth", "Fits given width"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmResults.anchorageZones", "Anchorage Zones", part="fem", fields=[], requires_project=False
)
def anchorage_zones(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """List each tie end's anchorage method, available length, and hook development demand."""
    from saengine.design.ductile_joints import hooked_development

    model = working_model(ctx, v)
    rows = []
    for tie in (m for m in model.members if m.kind == "tie" and m.barDiameter > 0):
        length = hooked_development(tie.barDiameter, model.fy, model.fc, model.lam)
        for node_id in (tie.start, tie.end):
            node = next(n for n in model.nodes if n.id == node_id)
            rows.append(
                {
                    "tieId": tie.id,
                    "nodeId": node.id,
                    "anchorage": node.anchorage or "unspecified",
                    "hookLengthRequiredMm": length,
                    "lengthAvailableMm": node.anchorLength,
                    "hookPass": node.anchorLength >= length if node.anchorage == "hook" else None,
                }
            )
    return result(
        {"tieEndsReviewed": len(rows)},
        [
            table(
                "Tie anchorage zones",
                [
                    ("tieId", "Tie"),
                    ("nodeId", "Node"),
                    ("anchorage", "Detail"),
                    ("hookLengthRequiredMm", "Hook length", "mm"),
                    ("lengthAvailableMm", "Available", "mm"),
                    ("hookPass", "Hook check"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmResults.burstingSteel",
    "Bursting Steel",
    part="fem",
    fields=[
        number("loadShare", "Transverse bursting force share", 0.25, min=0.01, max=0.5),
    ],
    requires_project=False,
)
def bursting_steel(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Estimate reinforcement to resist the entered elastic bursting-force share behind bearings."""
    model = working_model(ctx, v)
    checked = solve_rows(model)
    rows = []
    for node in model.nodes:
        if node.bearing <= 0:
            continue
        demand = 0.0
        for case in checked["cases"]:
            demand = max(demand, math.hypot(*case["reactions"].get(node.id, (0, 0))))
            load_case = next(c for c in model.cases if c.name == case["name"])
            demand = max(
                demand,
                max(
                    (math.hypot(x.fx, x.fy) for x in load_case.loads if x.node == node.id),
                    default=0,
                ),
            )
        transverse = v["loadShare"] * demand * 1000
        area = transverse / (stm.phi() * model.fy)
        rows.append(
            {
                "nodeId": node.id,
                "bearingForceKn": demand,
                "burstingForceKn": transverse / 1000,
                "requiredSteelMm2": area,
            }
        )
    return result(
        {"bearingZones": len(rows)},
        [
            table(
                "Bearing bursting reinforcement",
                [
                    ("nodeId", "Node"),
                    ("bearingForceKn", "Bearing force", "kN"),
                    ("burstingForceKn", "Transverse force", "kN"),
                    ("requiredSteelMm2", "Required steel", "mm²"),
                ],
                rows,
            )
        ],
        [
            "Bursting force share is an explicit design input; arrange the calculated steel behind the loaded face."
        ],
    )


@feature("femStmResults.stmReport", "STM Report", part="fem", fields=[], requires_project=True)
def stm_report(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Publish a structured design report with load cases, checks, assumptions, and code-pack citations."""
    _models, model = project_model(ctx)
    report = stm_model.check_model(model)
    path = export_json(ctx, "stm-design-report.json", report)
    return result(
        {
            "modelName": model.name,
            "overallPass": report["ok"],
            "utilisationRatio": report["utilisation"],
            "savedTo": str(path),
            "checks": len(report["checks"]),
        }
    )


@feature(
    "femStmResults.exportDxf",
    "Export DXF",
    part="fem",
    fields=[
        number("memberLabelHeightMm", "Member-label text height", 25, unit="mm", min=1),
    ],
    requires_project=True,
)
def export_dxf(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Export model nodes, force-labelled members, and supports as a DXF drawing."""
    import ezdxf

    _models, model = project_model(ctx)
    checked = solve_rows(model)
    document = ezdxf.new("R2010")
    drawing = document.modelspace()
    forces = {r["id"]: r["force"] for r in checked["members"]}
    for node in model.nodes:
        drawing.add_circle(
            (node.x, node.y), max(model.thickness * 0.025, 5), dxfattribs={"layer": "NODES"}
        )
        drawing.add_text(
            node.id, dxfattribs={"height": v["memberLabelHeightMm"], "insert": (node.x, node.y)}
        )
    for member in model.members:
        start = next(n for n in model.nodes if n.id == member.start)
        end = next(n for n in model.nodes if n.id == member.end)
        drawing.add_line(
            (start.x, start.y), (end.x, end.y), dxfattribs={"layer": member.kind.upper()}
        )
        drawing.add_text(
            f"{member.id} {forces[member.id]:.1f} kN",
            dxfattribs={
                "height": v["memberLabelHeightMm"],
                "insert": ((start.x + end.x) / 2, (start.y + end.y) / 2),
            },
        )
    if ctx.root is None:
        raise FeatureInputError("Open a project folder before exporting DXF.")
    target = ctx.root / "08 FEM" / "exports" / "stm-model.dxf"
    target.parent.mkdir(parents=True, exist_ok=True)
    document.saveas(target)
    return result(
        {
            "modelName": model.name,
            "nodes": len(model.nodes),
            "members": len(model.members),
            "savedTo": str(target),
        }
    )


@feature(
    "femStmResults.compareModels", "Compare Models", part="fem", fields=[], requires_project=True
)
def compare_models(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Compare solved utilisation and load-path size across all project STM alternatives."""
    from saengine.features.fem_stm_common import project_models

    models = project_models(ctx)
    if len(models) < 2:
        raise FeatureInputError("Save at least two STM alternatives to compare them.")
    rows = []
    for model in models:
        checked = solve_rows(model)
        rows.append(
            {
                "model": model.name,
                "nodes": len(model.nodes),
                "members": len(model.members),
                "loadCases": len(model.cases),
                "utilisationRatio": checked["utilisation"],
                "checksPassed": checked["ok"],
            }
        )
    return result(
        {"alternatives": len(rows)},
        [
            table(
                "Alternative STM comparison",
                [
                    ("model", "Model"),
                    ("nodes", "Nodes"),
                    ("members", "Members"),
                    ("loadCases", "Load cases"),
                    ("utilisationRatio", "Utilisation"),
                    ("checksPassed", "Pass"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmResults.strutColours", "Strut Colours", part="fem", fields=[], requires_project=False
)
def strut_colours(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Map member utilisation into deterministic result-view colour bands."""
    checked = solve_rows(working_model(ctx, v))
    rows = []
    for item in checked["members"]:
        ratio = float(item["utilisation"])
        band = "green" if ratio <= 0.6 else "amber" if ratio <= 0.85 else "red"
        rows.append(
            {
                "memberId": item["id"],
                "kind": item["kind"],
                "utilisationRatio": ratio,
                "viewColour": band,
            }
        )
    return result(
        {"membersColoured": len(rows)},
        [
            table(
                "Member result colours",
                [
                    ("memberId", "Member"),
                    ("kind", "Kind"),
                    ("utilisationRatio", "Utilisation"),
                    ("viewColour", "Colour band"),
                ],
                rows,
            )
        ],
        ["Bands are view thresholds (≤0.60, ≤0.85, >0.85), not design acceptance limits."],
    )


@feature(
    "femStmResults.forceVectors", "Force Vectors", part="fem", fields=[], requires_project=False
)
def force_vectors(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Return vector components and endpoint coordinates for drawing member force arrows."""
    model = working_model(ctx, v)
    coords = {n.id: (n.x, n.y) for n in model.nodes}
    checked = solve_rows(model)
    rows = []
    for member in model.members:
        x0, y0 = coords[member.start]
        x1, y1 = coords[member.end]
        length = math.hypot(x1 - x0, y1 - y0)
        force = next(r["force"] for r in checked["members"] if r["id"] == member.id)
        rows.append(
            {
                "memberId": member.id,
                "forceKn": force,
                "fxKn": force * (x1 - x0) / length,
                "fyKn": force * (y1 - y0) / length,
                "xMidMm": (x0 + x1) / 2,
                "yMidMm": (y0 + y1) / 2,
            }
        )
    return result(
        {"vectors": len(rows)},
        [
            table(
                "Axial force vectors",
                [
                    ("memberId", "Member"),
                    ("forceKn", "Axial", "kN"),
                    ("fxKn", "Fx", "kN"),
                    ("fyKn", "Fy", "kN"),
                    ("xMidMm", "Arrow x", "mm"),
                    ("yMidMm", "Arrow y", "mm"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmResults.deformationScale",
    "Deformation Scale",
    part="fem",
    fields=[
        number("displayScale", "Display multiplier", 10, min=0),
    ],
    requires_project=False,
)
def deformation_scale(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Return scaled coordinates for supplied nodal displacement results without inventing deformation."""
    model = working_model(ctx, v)
    rows = [
        {
            "nodeId": n.id,
            "xMm": n.x,
            "yMm": n.y,
            "scaledXmm": n.x,
            "scaledYmm": n.y,
            "displayScale": v["displayScale"],
        }
        for n in model.nodes
    ]
    return result(
        {"nodes": len(rows), "displayScale": v["displayScale"], "displacementsAvailable": False},
        [
            table(
                "STM view coordinates",
                [
                    ("nodeId", "Node"),
                    ("xMm", "X", "mm"),
                    ("yMm", "Y", "mm"),
                    ("scaledXmm", "Scaled X", "mm"),
                    ("scaledYmm", "Scaled Y", "mm"),
                    ("displayScale", "Multiplier"),
                ],
                rows,
            )
        ],
        [
            "The STM solver provides member forces and reactions, not displacements; no deformation shape is fabricated."
        ],
    )


@feature(
    "femStmResults.resultLegend", "Result Legend", part="fem", fields=[], requires_project=False
)
def result_legend(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Describe utilisation colour bands with the project model's actual maximum ratio."""
    checked = solve_rows(working_model(ctx, v))
    rows = [
        {"colour": "green", "lowerRatio": 0.0, "upperRatio": 0.6},
        {"colour": "amber", "lowerRatio": 0.6, "upperRatio": 0.85},
        {"colour": "red", "lowerRatio": 0.85, "upperRatio": None},
    ]
    return result(
        {"maximumModelUtilisation": checked["utilisation"], "bands": len(rows)},
        [
            table(
                "Utilisation legend",
                [("colour", "Colour"), ("lowerRatio", "From"), ("upperRatio", "To")],
                rows,
            )
        ],
        ["The colour limits are display thresholds only; acceptance remains the component checks."],
    )


@feature(
    "femStmResults.utilisationRatio",
    "Utilisation Ratio",
    part="fem",
    fields=[],
    requires_project=False,
)
def utilisation_ratio(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """List the code-pack demand/capacity ratio for each solved STM member and node."""
    checked = solve_rows(working_model(ctx, v))
    rows = [
        {"id": x["id"], "component": x["kind"], "ratio": x["utilisation"], "ok": x["ok"]}
        for x in checked["members"]
    ]
    rows.extend(
        {"id": x["id"], "component": x["type"], "ratio": x["utilisation"], "ok": x["ok"]}
        for x in checked["nodes"]
    )
    return result(
        {"governingRatio": checked["utilisation"], "components": len(rows)},
        [
            table(
                "STM utilisation",
                [
                    ("id", "ID"),
                    ("component", "Component"),
                    ("ratio", "Demand / capacity"),
                    ("ok", "Pass"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmResults.serviceLoadCheck",
    "Service Load Check",
    part="fem",
    fields=[
        number("serviceFactor", "Service-to-factored force ratio", 0.65, min=0.01, max=1),
        number("steelStressLimitMpa", "Service steel stress limit", 250, unit="MPa", min=1),
    ],
    requires_project=False,
)
def service_load_check(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Check service-scaled tie stresses against the engineer-entered service stress limit."""
    model = working_model(ctx, v)
    checked = solve_rows(model)
    rows = []
    for tie in (m for m in model.members if m.kind == "tie"):
        force = abs(next(r["force"] for r in checked["members"] if r["id"] == tie.id)) * 1000
        stress = force * v["serviceFactor"] / tie.barArea if tie.barArea > 0 else None
        rows.append(
            {
                "tieId": tie.id,
                "serviceStressMpa": stress,
                "limitMpa": v["steelStressLimitMpa"],
                "passes": stress is not None and stress <= v["steelStressLimitMpa"],
            }
        )
    return result(
        {"tiesChecked": len(rows), "serviceFactor": v["serviceFactor"]},
        [
            table(
                "Service tie stress",
                [
                    ("tieId", "Tie"),
                    ("serviceStressMpa", "Stress", "MPa"),
                    ("limitMpa", "Limit", "MPa"),
                    ("passes", "Pass"),
                ],
                rows,
            )
        ],
        [
            "The engineer-entered service limit is not a code-pack cracking check; concrete crack width needs service analysis data."
        ],
    )


@feature(
    "femStmResults.detailingCheck",
    "Detailing Check",
    part="fem",
    fields=[
        number("coverMm", "Clear cover", 40, unit="mm", min=0),
        number("minimumClearSpacingMm", "Minimum clear bar spacing", 25, unit="mm", min=0),
    ],
    requires_project=False,
)
def detailing_check(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Check tie bar widths, end anchorage data, and reinforcement fit for detailing conflicts."""
    model = working_model(ctx, v)
    rows = []
    for tie in (m for m in model.members if m.kind == "tie"):
        count = (
            math.ceil(tie.barArea / (math.pi * tie.barDiameter**2 / 4)) if tie.barDiameter else 0
        )
        inside = tie.width - 2 * v["coverMm"] - count * tie.barDiameter
        enough_width = tie.width <= 0 or inside >= max(count - 1, 0) * v["minimumClearSpacingMm"]
        ends = [next(n for n in model.nodes if n.id == k) for k in (tie.start, tie.end)]
        anchorage_given = all(n.anchorage for n in ends)
        rows.append(
            {
                "tieId": tie.id,
                "barCount": count,
                "clearWidthMm": inside,
                "barFitPass": enough_width,
                "bothAnchorsSpecified": anchorage_given,
            }
        )
    return result(
        {"tiesReviewed": len(rows)},
        [
            table(
                "Tie detailing fit",
                [
                    ("tieId", "Tie"),
                    ("barCount", "Bars"),
                    ("clearWidthMm", "Width after cover", "mm"),
                    ("barFitPass", "Fit"),
                    ("bothAnchorsSpecified", "Anchors specified"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmResults.forceConsistency",
    "Force Consistency",
    part="fem",
    fields=[],
    requires_project=False,
)
def force_consistency(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Re-solve each load case and compare its member force outputs with the reported envelope."""
    model = working_model(ctx, v)
    checked = solve_rows(model)
    rows = []
    for case in model.cases:
        solved = stm_model.solve(model, case)
        if solved.problems:
            raise FeatureInputError("; ".join(solved.problems))
        for member, force_n in solved.forces.items():
            reported = next(x["force"] for x in checked["members"] if x["id"] == member)
            rows.append(
                {
                    "case": case.name,
                    "memberId": member,
                    "caseForceKn": force_n / 1000,
                    "envelopeForceKn": reported,
                    "forceSolved": math.isfinite(force_n),
                }
            )
    return result(
        {"forceEntriesVerified": len(rows)},
        [
            table(
                "Force consistency",
                [
                    ("case", "Case"),
                    ("memberId", "Member"),
                    ("caseForceKn", "Case force", "kN"),
                    ("envelopeForceKn", "Envelope", "kN"),
                    ("forceSolved", "Finite"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmResults.acceptanceReview",
    "Acceptance Review",
    part="fem",
    fields=[
        text("reviewer", "Reviewer", ""),
        checkbox("accepted", "Accept this design", False),
        text("comments", "Review comments", ""),
    ],
    requires_project=True,
)
def acceptance_review(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Save an auditable reviewer decision alongside the checked project STM."""
    _models, model = project_model(ctx)
    checked = solve_rows(model)
    if v["accepted"] and not checked["ok"]:
        raise FeatureInputError(
            "The STM has failed checks; resolve them before recording acceptance."
        )
    if not v["reviewer"].strip():
        raise FeatureInputError("Enter the responsible reviewer before recording a review.")
    path = export_json(
        ctx,
        "stm-review.json",
        {
            "model": model.name,
            "reviewer": v["reviewer"].strip(),
            "accepted": v["accepted"],
            "comments": v["comments"],
            "utilisationRatio": checked["utilisation"],
            "checkedComponents": len(checked["checks"]),
        },
    )
    return result(
        {
            "accepted": v["accepted"],
            "reviewer": v["reviewer"].strip(),
            "savedTo": str(path),
            "utilisationRatio": checked["utilisation"],
        }
    )


@feature(
    "femStmResults.resultTables", "Result Tables", part="fem", fields=[], requires_project=False
)
def result_tables(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Provide separate tabulations for solved members, nodal checks, and case reactions."""
    checked = solve_rows(working_model(ctx, v))
    member_rows = [
        {
            "id": x["id"],
            "kind": x["kind"],
            "forceKn": x["force"],
            "utilisation": x["utilisation"],
            "ok": x["ok"],
        }
        for x in checked["members"]
    ]
    node_rows = [
        {
            "id": x["id"],
            "type": x["type"],
            "betaN": x["betaN"],
            "utilisation": x["utilisation"],
            "ok": x["ok"],
        }
        for x in checked["nodes"]
    ]
    reaction_rows = [
        {"case": case["name"], "nodeId": node, "rxKn": pair[0], "ryKn": pair[1]}
        for case in checked["cases"]
        for node, pair in case["reactions"].items()
    ]
    return result(
        {"members": len(member_rows), "nodes": len(node_rows), "reactions": len(reaction_rows)},
        [
            table(
                "Members",
                [
                    ("id", "ID"),
                    ("kind", "Kind"),
                    ("forceKn", "Force", "kN"),
                    ("utilisation", "Ratio"),
                    ("ok", "Pass"),
                ],
                member_rows,
            ),
            table(
                "Nodal zones",
                [
                    ("id", "ID"),
                    ("type", "Node type"),
                    ("betaN", "βn"),
                    ("utilisation", "Ratio"),
                    ("ok", "Pass"),
                ],
                node_rows,
            ),
            table(
                "Support reactions",
                [("case", "Case"), ("nodeId", "Node"), ("rxKn", "Rx", "kN"), ("ryKn", "Ry", "kN")],
                reaction_rows,
            ),
        ],
    )


@feature(
    "femStmResults.calculationNote",
    "Calculation Note",
    part="fem",
    fields=[],
    requires_project=True,
)
def calculation_note(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Write a calculation note containing model assumptions, checks, and solved load cases."""
    _models, model = project_model(ctx)
    checked = stm_model.check_model(model)
    lines = [
        f"# {model.name}",
        "",
        f"Member: {model.member or 'not assigned'}",
        f"Concrete: {model.fc:g} MPa; reinforcement: {model.fy:g} MPa",
        f"Thickness: {model.thickness:g} mm; nodes: {len(model.nodes)}; members: {len(model.members)}",
        "",
        "## Assumptions",
        *[f"- {x}" for x in checked["assumptions"]],
        "",
        "## Component checks",
    ]
    lines.extend(
        f"- {x['name']}: {x['demand']} / {x['capacity']} {x['unit']} ({'pass' if x['ok'] else 'fail'})"
        for x in checked["checks"]
    )
    path = ctx.root / "08 FEM" / "exports" / "stm-calculation-note.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result(
        {
            "modelName": model.name,
            "checks": len(checked["checks"]),
            "savedTo": str(path),
            "overallPass": checked["ok"],
        }
    )


@feature(
    "femStmResults.comparisonChart",
    "Comparison Chart",
    part="fem",
    fields=[],
    requires_project=True,
)
def comparison_chart(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Return aligned per-member utilisation series for graphical comparison of STM alternatives."""
    from saengine.features.fem_stm_common import project_models

    models = project_models(ctx)
    if len(models) < 2:
        raise FeatureInputError("Save at least two STM alternatives to build a comparison chart.")
    rows = []
    for model in models:
        checked = solve_rows(model)
        rows.extend(
            {
                "model": model.name,
                "component": x["id"],
                "kind": x["kind"],
                "utilisation": x["utilisation"],
            }
            for x in checked["members"]
        )
    return result(
        {"alternatives": len(models), "seriesPoints": len(rows)},
        [
            table(
                "Alternative member utilisation series",
                [
                    ("model", "Model"),
                    ("component", "Member"),
                    ("kind", "Kind"),
                    ("utilisation", "Demand / capacity"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmResults.modelSnapshot", "Model Snapshot", part="fem", fields=[], requires_project=True
)
def model_snapshot(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Capture a portable, deterministic snapshot of model geometry and current results."""
    _models, model = project_model(ctx)
    checked = solve_rows(model)
    path = export_json(
        ctx,
        "stm-model-snapshot.json",
        {
            "model": model.model_dump(mode="json"),
            "coordinatesMm": [{"id": n.id, "x": n.x, "y": n.y} for n in model.nodes],
            "memberResults": checked["members"],
            "nodeResults": checked["nodes"],
        },
    )
    return result(
        {
            "modelName": model.name,
            "nodes": len(model.nodes),
            "savedTo": str(path),
            "utilisationRatio": checked["utilisation"],
        }
    )


@feature(
    "femStmResults.deliverablePack",
    "Deliverable Pack",
    part="fem",
    fields=[],
    requires_project=True,
)
def deliverable_pack(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Assemble model, solved checks, drawing exchange, and report data into a deliverable directory."""
    import ezdxf

    _models, model = project_model(ctx)
    checked = solve_rows(model)
    base = ctx.root / "08 FEM" / "exports" / "stm-deliverable"
    base.mkdir(parents=True, exist_ok=True)
    (base / "model.json").write_text(
        model.model_dump_json(indent=2, by_alias=True) + "\n", encoding="utf-8"
    )
    (base / "checks.json").write_text(
        __import__("json").dumps(checked, indent=2) + "\n", encoding="utf-8"
    )
    drawing = ezdxf.new("R2010")
    space = drawing.modelspace()
    for node in model.nodes:
        space.add_circle((node.x, node.y), 8, dxfattribs={"layer": "NODES"})
    for member in model.members:
        start = next(n for n in model.nodes if n.id == member.start)
        end = next(n for n in model.nodes if n.id == member.end)
        space.add_line(
            (start.x, start.y), (end.x, end.y), dxfattribs={"layer": member.kind.upper()}
        )
    drawing.saveas(base / "model.dxf")
    return result(
        {"modelName": model.name, "files": 3, "savedTo": str(base), "overallPass": checked["ok"]}
    )

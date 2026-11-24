"""Reinforcement geometry, anchorage, strength, and schedules for STM tension ties."""

from __future__ import annotations

import math
from typing import Any

from saengine.design import bar_rules, stm
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
    store_models,
    working_model,
)


def _tie(model: Any, tie_id: str) -> Any:
    found = next((m for m in model.members if m.id == tie_id and m.kind == "tie"), None)
    if found is None:
        raise FeatureInputError(f"{tie_id!r} is not a tension tie in the selected model.")
    return found


def _tie_demand_kn(model: Any, tie_id: str) -> float:
    row = next(r for r in solve_rows(model)["members"] if r["id"] == tie_id)
    return abs(float(row["force"]))


@feature(
    "femStmTies.tieWidth",
    "Tie Width",
    part="fem",
    fields=[
        text("tieId", "Tie member ID", "T1"),
        number("widthMm", "Effective tie width", 250, unit="mm", min=1),
    ],
    requires_project=True,
)
def tie_width(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Set the effective tie width used to check the tension face of adjacent nodes."""
    models, model = project_model(ctx)
    tie = _tie(model, v["tieId"])
    changed = tie.model_copy(update={"width": v["widthMm"]})
    members = [changed if x.id == tie.id else x for x in model.members]
    models[0] = model.model_copy(update={"members": members})
    path = store_models(ctx, models)
    return result(
        {
            "tieId": tie.id,
            "effectiveWidthMm": changed.width,
            "nodalFaceAreaMm2": changed.width * model.thickness,
            "savedTo": str(path),
        }
    )


@feature(
    "femStmTies.tieDepth",
    "Tie Depth",
    part="fem",
    fields=[
        text("tieId", "Tie member ID", "T1"),
        number("depthMm", "Tie reinforcement depth", 300, unit="mm", min=1),
        number("coverMm", "Clear cover", 40, unit="mm", min=0),
    ],
    requires_project=False,
)
def tie_depth(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Calculate the tie reinforcement centroid depth and available lever arm after cover."""
    model = working_model(ctx, v, kind="auto")
    tie = _tie(model, v["tieId"])
    if v["depthMm"] <= 2 * v["coverMm"]:
        raise FeatureInputError("Tie depth must exceed twice the clear cover.")
    return result(
        {
            "tieId": tie.id,
            "overallDepthMm": v["depthMm"],
            "effectiveDepthMm": v["depthMm"] - v["coverMm"],
            "centroidFromFaceMm": v["coverMm"] + tie.barDiameter / 2,
            "barDiameterMm": tie.barDiameter,
        },
        notes=[
            "Centroid depth is measured from the entered tension face; confirm the local section orientation."
        ],
    )


@feature(
    "femStmTies.barSize",
    "Bar Size",
    part="fem",
    fields=[
        text("tieId", "Tie member ID", "T1"),
        text("candidateDiametersMm", "Candidate bar diameters", "12,16,20,25,32"),
    ],
    requires_project=False,
)
def bar_size(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Enumerate bar diameters and integer bar counts that provide the tie's calculated steel demand."""
    model = working_model(ctx, v, kind="auto")
    tie = _tie(model, v["tieId"])
    demand = _tie_demand_kn(model, tie.id) * 1000
    tokens = [
        x.strip() for x in v["candidateDiametersMm"].replace(";", ",").split(",") if x.strip()
    ]
    try:
        diameters = [float(x) for x in tokens]
    except ValueError as exc:
        raise FeatureInputError(
            "Candidate diameters must be comma-separated numbers in millimetres."
        ) from exc
    if not diameters or any(x <= 0 for x in diameters):
        raise FeatureInputError("Enter positive candidate bar diameters.")
    required = demand / (stm.phi() * model.fy)
    rows = []
    for diameter in diameters:
        area = math.pi * diameter**2 / 4
        count = math.ceil(required / area)
        rows.append(
            {
                "diameterMm": diameter,
                "barCount": count,
                "barAreaMm2": area,
                "providedAreaMm2": count * area,
                "areaExcessMm2": count * area - required,
            }
        )
    return result(
        {"tieId": tie.id, "requiredAreaMm2": required, "options": len(rows)},
        [
            table(
                "Candidate bar groups",
                [
                    ("diameterMm", "Diameter", "mm"),
                    ("barCount", "Count"),
                    ("barAreaMm2", "Single-bar area", "mm²"),
                    ("providedAreaMm2", "Provided area", "mm²"),
                    ("areaExcessMm2", "Area excess", "mm²"),
                ],
                rows,
            )
        ],
        ["The resistance factor and tie force are taken from the active model/code pack."],
    )


@feature(
    "femStmTies.tieCover",
    "Tie Cover",
    part="fem",
    fields=[
        text("tieId", "Tie member ID", "T1"),
        number("clearCoverMm", "Clear cover", 40, unit="mm", min=0),
    ],
    requires_project=False,
)
def tie_cover(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Report steel centroid cover and the remaining room within the tie's effective width."""
    model = working_model(ctx, v, kind="auto")
    tie = _tie(model, v["tieId"])
    centroid = v["clearCoverMm"] + tie.barDiameter / 2
    width_room = tie.width - 2 * v["clearCoverMm"] if tie.width else None
    return result(
        {
            "tieId": tie.id,
            "clearCoverMm": v["clearCoverMm"],
            "barCentroidCoverMm": centroid,
            "availableWidthMm": width_room,
            "coverRatio": centroid / model.thickness,
        }
    )


@feature(
    "femStmTies.developmentLength",
    "Development Length",
    part="fem",
    fields=[
        text("tieId", "Tie member ID", "T1"),
        number("barDiameterMm", "Bar diameter", 20, unit="mm", min=1),
        number("barStressMpa", "Bar design stress", 420, unit="MPa", min=1),
    ],
    requires_project=False,
)
def development_length(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Calculate the pack's straight and bent-bar anchorage length for a tie bar."""
    model = working_model(ctx, v, kind="auto")
    tie = _tie(model, v["tieId"])
    length = bar_rules.anchorage_length(
        v["barDiameterMm"], model.fc, model.fy, sigma_sd=v["barStressMpa"], cd=tie.width or None
    )
    return result(
        {
            "tieId": tie.id,
            "basicLengthMm": length["lbrqd"],
            "minimumLengthMm": length["lbmin"],
            "requiredLengthMm": length["lbd"],
            "barDiameterMm": v["barDiameterMm"],
        },
        notes=[
            "Bond, minimum length, and detailing coefficients are supplied by the active code pack."
        ],
    )


@feature(
    "femStmTies.endHooks",
    "End Hooks",
    part="fem",
    fields=[
        text("tieId", "Tie member ID", "T1"),
        number("barDiameterMm", "Hook bar diameter", 20, unit="mm", min=1),
    ],
    requires_project=True,
)
def end_hooks(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Set both tie-end anchorage details to hooks and calculate required development allowance."""
    models, model = project_model(ctx)
    tie = _tie(model, v["tieId"])
    from saengine.design.ductile_joints import hooked_development

    required = hooked_development(v["barDiameterMm"], model.fy, model.fc, model.lam)
    nodes = [
        n.model_copy(update={"anchorage": "hook", "anchorLength": max(n.anchorLength, required)})
        if n.id in (tie.start, tie.end)
        else n
        for n in model.nodes
    ]
    updated = model.model_copy(update={"nodes": nodes})
    models[0] = updated
    path = store_models(ctx, models)
    return result(
        {
            "tieId": tie.id,
            "requiredHookLengthMm": required,
            "updatedEndNodes": [tie.start, tie.end],
            "savedTo": str(path),
        }
    )


@feature(
    "femStmTies.endAnchorage",
    "End Anchorage",
    part="fem",
    fields=[
        text("tieId", "Tie member ID", "T1"),
        text("anchorage", "End detail (hook, plate, through)", "plate"),
        number("availableLengthMm", "Available tie extension", 300, unit="mm", min=0),
    ],
    requires_project=True,
)
def end_anchorage(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Assign a selected end anchorage device and available development distance to both tie nodes."""
    models, model = project_model(ctx)
    tie = _tie(model, v["tieId"])
    detail = v["anchorage"].strip()
    if detail not in ("hook", "plate", "through"):
        raise FeatureInputError("Anchorage must be hook, plate, or through.")
    nodes = [
        n.model_copy(update={"anchorage": detail, "anchorLength": v["availableLengthMm"]})
        if n.id in (tie.start, tie.end)
        else n
        for n in model.nodes
    ]
    models[0] = model.model_copy(update={"nodes": nodes})
    path = store_models(ctx, models)
    return result(
        {
            "tieId": tie.id,
            "anchorage": detail,
            "availableLengthMm": v["availableLengthMm"],
            "savedTo": str(path),
        }
    )


@feature(
    "femStmTies.curtailmentPoint",
    "Curtailment Point",
    part="fem",
    fields=[
        text("tieId", "Tie member ID", "T1"),
        number("barDiameterMm", "Bar diameter", 20, unit="mm", min=1),
    ],
    requires_project=False,
)
def curtailment_point(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Locate end development zones and identify whether a constant-force STM tie has curtailment room."""
    model = working_model(ctx, v, kind="auto")
    tie = _tie(model, v["tieId"])
    length = geometry(model)[tie.id][4]
    anchorage = bar_rules.anchorage_length(v["barDiameterMm"], model.fc, model.fy)["lbd"]
    remaining = length - 2 * anchorage
    return result(
        {
            "tieId": tie.id,
            "tieLengthMm": length,
            "developmentEachEndMm": anchorage,
            "availableBetweenAnchorageZonesMm": max(remaining, 0),
            "curtailmentPermittedByGeometry": remaining > 0,
        },
        notes=[
            "The truss tie force is constant along its member; no interior force drop is assumed for curtailment."
        ],
    )


@feature(
    "femStmTies.tieStrength",
    "Tie Strength",
    part="fem",
    fields=[
        text("tieId", "Tie member ID", "T1"),
    ],
    requires_project=False,
)
def tie_strength(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Check nominal and design tension resistance including any prestress in the tie."""
    model = working_model(ctx, v, kind="auto")
    tie = _tie(model, v["tieId"])
    force = _tie_demand_kn(model, tie.id)
    nominal = stm.tie_nominal(
        tie.barArea, model.fy, tie.prestressArea, tie.fse, tie.fpy, tie.bonded
    )
    design = stm.phi() * nominal
    return result(
        {
            "tieId": tie.id,
            "tensionDemandKn": force,
            "nominalResistanceKn": nominal / 1000,
            "designResistanceKn": design / 1000,
            "utilisationRatio": force * 1000 / design if design else None,
            "resistanceFactor": stm.phi(),
        }
    )


@feature(
    "femStmTies.crackWidth",
    "Crack Width",
    part="fem",
    fields=[
        text("tieId", "Tie member ID", "T1"),
        number("serviceFactor", "Service-to-factored force ratio", 0.65, min=0.01, max=1),
        number("barSpacingMm", "Tie bar spacing", 100, unit="mm", min=1),
    ],
    requires_project=False,
)
def crack_width(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Estimate tie-zone crack spacing and width from elastic steel strain and bar spacing."""
    model = working_model(ctx, v, kind="auto")
    tie = _tie(model, v["tieId"])
    if tie.barArea <= 0:
        raise FeatureInputError("Assign non-zero tie steel area before estimating crack width.")
    service_force = _tie_demand_kn(model, tie.id) * 1000 * v["serviceFactor"]
    steel_stress = service_force / tie.barArea
    strain = max(steel_stress / 200000, 0.0)
    width = strain * v["barSpacingMm"]
    return result(
        {
            "tieId": tie.id,
            "serviceStressMpa": steel_stress,
            "steelStrain": strain,
            "assumedCrackSpacingMm": v["barSpacingMm"],
            "estimatedCrackWidthMm": width,
        },
        notes=[
            "Elastic strain times entered crack spacing is a screening estimate, not the code-pack reinforced-concrete crack-width calculation."
        ],
    )


@feature(
    "femStmTies.spacingCheck",
    "Spacing Check",
    part="fem",
    fields=[
        text("tieId", "Tie member ID", "T1"),
        number("barDiameterMm", "Bar diameter", 20, unit="mm", min=1),
        number("barCount", "Number of bars", 4, min=1),
        number("clearWidthMm", "Available clear width", 250, unit="mm", min=1),
        number("minimumClearSpacingMm", "Minimum clear spacing", 25, unit="mm", min=0),
    ],
    requires_project=False,
)
def spacing_check(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Verify clear spacing of a specified tie bar group within its available width."""
    model = working_model(ctx, v, kind="auto")
    tie = _tie(model, v["tieId"])
    count = int(v["barCount"])
    clear = (v["clearWidthMm"] - count * v["barDiameterMm"]) / max(count - 1, 1)
    return result(
        {
            "tieId": tie.id,
            "barCount": count,
            "barDiameterMm": v["barDiameterMm"],
            "clearSpacingMm": clear,
            "minimumClearSpacingMm": v["minimumClearSpacingMm"],
            "passes": clear >= v["minimumClearSpacingMm"],
        },
        notes=[
            "Clear spacing is checked across the entered width, excluding cover and aggregate constraints."
        ],
    )


@feature("femStmTies.tieReport", "Tie Report", part="fem", fields=[], requires_project=False)
def tie_report(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Report each tie's solved envelope, design capacity, steel requirement, and end anchorage."""
    model = working_model(ctx, v, kind="auto")
    checked = solve_rows(model)
    rows = []
    for tie in (m for m in model.members if m.kind == "tie"):
        force = abs(next(x["force"] for x in checked["members"] if x["id"] == tie.id))
        area = max(force * 1000 / (stm.phi() * model.fy), 0)
        rows.append(
            {
                "tieId": tie.id,
                "forceKn": force,
                "requiredAreaMm2": area,
                "providedAreaMm2": tie.barArea,
                "startAnchorage": next(n.anchorage for n in model.nodes if n.id == tie.start)
                or "unspecified",
                "endAnchorage": next(n.anchorage for n in model.nodes if n.id == tie.end)
                or "unspecified",
            }
        )
    return result(
        {"tieMembers": len(rows)},
        [
            table(
                "Tie design report",
                [
                    ("tieId", "Tie"),
                    ("forceKn", "Tension", "kN"),
                    ("requiredAreaMm2", "Required As", "mm²"),
                    ("providedAreaMm2", "Provided As", "mm²"),
                    ("startAnchorage", "Start detail"),
                    ("endAnchorage", "End detail"),
                ],
                rows,
            )
        ],
    )


@feature(
    "femStmTies.barBundle",
    "Bar Bundle",
    part="fem",
    fields=[
        text("tieId", "Tie member ID", "T1"),
        number("barsPerBundle", "Bars in each bundle", 2, min=1),
    ],
    requires_project=False,
)
def bar_bundle(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Group the provided tie area into equal reinforcement bundles and report bundle spacing limits."""
    model = working_model(ctx, v, kind="auto")
    tie = _tie(model, v["tieId"])
    if tie.barArea <= 0 or tie.barDiameter <= 0:
        raise FeatureInputError("Assign the tie bar area and diameter before arranging bundles.")
    single = math.pi * tie.barDiameter**2 / 4
    total_bars = math.ceil(tie.barArea / single)
    bundles = math.ceil(total_bars / int(v["barsPerBundle"]))
    return result(
        {
            "tieId": tie.id,
            "totalBars": total_bars,
            "barsPerBundle": int(v["barsPerBundle"]),
            "bundleCount": bundles,
            "bundleAreaMm2": int(v["barsPerBundle"]) * single,
            "residualBars": total_bars % int(v["barsPerBundle"]),
        },
        notes=[
            "Bundle area is nominal bar area; verify aggregate passage, cover, and bundle detailing separately."
        ],
    )


@feature(
    "femStmTies.layerDistribution",
    "Layer Distribution",
    part="fem",
    fields=[
        text("tieId", "Tie member ID", "T1"),
        number("layers", "Number of reinforcement layers", 2, min=1),
        number("barsPerLayer", "Bars in each layer", 2, min=1),
    ],
    requires_project=False,
)
def layer_distribution(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Distribute the provided tie steel uniformly across the entered number of reinforcement layers."""
    model = working_model(ctx, v, kind="auto")
    tie = _tie(model, v["tieId"])
    count = int(v["layers"])
    bars = int(v["barsPerLayer"])
    if count * bars <= 0 or tie.barArea <= 0:
        raise FeatureInputError("Tie steel area and positive layer/bar counts are required.")
    area_each = tie.barArea / (count * bars)
    dia_each = math.sqrt(4 * area_each / math.pi)
    return result(
        {
            "tieId": tie.id,
            "layers": count,
            "barsPerLayer": bars,
            "areaPerBarMm2": area_each,
            "equivalentDiameterMm": dia_each,
            "steelPerLayerMm2": area_each * bars,
        },
        notes=["Equivalent diameter assumes equal round bars sharing the recorded tie area."],
    )


@feature(
    "femStmTies.stirrupLeg",
    "Stirrup Leg",
    part="fem",
    fields=[
        number("barDiameterMm", "Transverse leg diameter", 10, unit="mm", min=1),
        number("legCount", "Active legs across the node", 2, min=1),
        number("spacingMm", "Leg spacing", 150, unit="mm", min=1),
    ],
    requires_project=False,
)
def stirrup_leg(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Calculate total transverse tie steel per spacing and its ratio across the STM thickness."""
    model = working_model(ctx, v, kind="auto")
    one = math.pi * v["barDiameterMm"] ** 2 / 4
    total = int(v["legCount"]) * one
    return result(
        {
            "barAreaPerLegMm2": one,
            "totalLegAreaMm2": total,
            "steelPerSpacingMm2PerMm": total / v["spacingMm"],
            "ratioAcrossThickness": total / (model.thickness * v["spacingMm"]),
            "packWebRatio": stm.factor("webRatio"),
        }
    )


@feature(
    "femStmTies.couplerAssignment",
    "Coupler Assignment",
    part="fem",
    fields=[
        text("tieId", "Tie member ID", "T1"),
        number("positionFraction", "Along-tie position", 0.5, min=0, max=1),
        text("couplerType", "Coupler specification", "Mechanical tension coupler"),
    ],
    requires_project=True,
)
def coupler_assignment(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Record a specified mechanical coupler at a measured fraction of the tie run."""
    _models, model = project_model(ctx)
    tie = _tie(model, v["tieId"])
    length = geometry(model)[tie.id][4]
    position = length * v["positionFraction"]
    path = export_json(
        ctx,
        "stm-couplers.json",
        {
            "model": model.name,
            "assignments": [
                {
                    "tieId": tie.id,
                    "type": v["couplerType"],
                    "distanceFromStartMm": position,
                    "distanceFromEndMm": length - position,
                    "tieForceKn": _tie_demand_kn(model, tie.id),
                    "tieBarDiameterMm": tie.barDiameter,
                }
            ],
        },
    )
    return result(
        {"tieId": tie.id, "positionMm": position, "tieLengthMm": length, "savedTo": str(path)},
        notes=[
            "Confirm the selected coupler's certified tensile resistance is at least the tie design force."
        ],
    )


@feature(
    "femStmTies.effectiveTension",
    "Effective Tension",
    part="fem",
    fields=[
        text("tieId", "Tie member ID", "T1"),
        number("serviceFactor", "Service force factor", 0.65, min=0.01, max=1),
    ],
    requires_project=False,
)
def effective_tension(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Evaluate service steel stress and strain from the solved tension in a reinforced tie."""
    model = working_model(ctx, v, kind="auto")
    tie = _tie(model, v["tieId"])
    if tie.barArea <= 0:
        raise FeatureInputError("Assign a positive tie steel area before evaluating steel tension.")
    force = _tie_demand_kn(model, tie.id) * 1000 * v["serviceFactor"]
    stress = force / tie.barArea
    return result(
        {
            "tieId": tie.id,
            "effectiveTensionKn": force / 1000,
            "steelStressMpa": stress,
            "elasticStrain": stress / 200000,
            "yieldStressMpa": model.fy,
            "stressRatio": stress / model.fy,
        }
    )


@feature(
    "femStmTies.softeningFactor",
    "Softening Factor",
    part="fem",
    fields=[
        text("strutId", "Bottle-shaped strut ID", "S1"),
        checkbox(
            "webReinforcementProvided", "Pack-required crack-control web steel provided", True
        ),
    ],
    requires_project=False,
)
def softening_factor(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Return the active pack's bottle-strut softening factor and resulting effective concrete stress."""
    model = working_model(ctx, v, kind="auto")
    strut = next((m for m in model.members if m.id == v["strutId"] and m.kind == "strut"), None)
    if strut is None:
        raise FeatureInputError(f"{v['strutId']!r} is not a strut.")
    beta = stm.beta_strut(strut.shape, bool(v["webReinforcementProvided"]), model.lam)
    return result(
        {
            "strutId": strut.id,
            "shape": strut.shape,
            "softeningFactor": beta,
            "effectiveStressMpa": stm.effective_strength(model.fc, beta),
            "packResistanceFactor": stm.phi(),
        },
        notes=[
            "Bottle-strut and concrete efficiency factors are resolved from the active code pack."
        ],
    )


@feature(
    "femStmTies.strainCompatibility",
    "Strain Compatibility",
    part="fem",
    fields=[
        text("tieId", "Tie member ID", "T1"),
        number("serviceFactor", "Service force factor", 0.65, min=0.01, max=1),
    ],
    requires_project=False,
)
def strain_compatibility(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Check elastic tie-bar strain against yield strain under the entered service force level."""
    model = working_model(ctx, v, kind="auto")
    tie = _tie(model, v["tieId"])
    if tie.barArea <= 0:
        raise FeatureInputError(
            "Assign tie reinforcement before calculating compatible steel strain."
        )
    stress = _tie_demand_kn(model, tie.id) * 1000 * v["serviceFactor"] / tie.barArea
    steel_strain = stress / 200000
    yield_strain = model.fy / 200000
    return result(
        {
            "tieId": tie.id,
            "steelStressMpa": stress,
            "steelStrain": steel_strain,
            "yieldStrain": yield_strain,
            "elasticCompatibility": steel_strain <= yield_strain,
        },
        notes=[
            "Perfect bond is assumed; concrete tension stiffening and post-yield response are outside this elastic check."
        ],
    )


@feature(
    "femStmTies.bendRadius",
    "Bend Radius",
    part="fem",
    fields=[
        number("barDiameterMm", "Tie bar diameter", 20, unit="mm", min=1),
        number("barStressMpa", "Bar stress at bend", 420, unit="MPa", min=1),
        number("bendCoverMm", "Cover to bend", 50, unit="mm", min=0),
        number("innerBendDiameterMm", "Specified inside bend diameter", 80, unit="mm", min=0),
    ],
    requires_project=False,
)
def bend_radius(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Evaluate bent-bar anchorage reduction using the code pack and compare an entered mandrel diameter."""
    model = working_model(ctx, v, kind="auto")
    anchorage = bar_rules.anchorage_length(
        v["barDiameterMm"],
        model.fc,
        model.fy,
        sigma_sd=v["barStressMpa"],
        cd=v["bendCoverMm"],
        bent=True,
    )
    ratio = v["innerBendDiameterMm"] / v["barDiameterMm"]
    return result(
        {
            "barDiameterMm": v["barDiameterMm"],
            "insideBendDiameterMm": v["innerBendDiameterMm"],
            "bendDiameterRatio": ratio,
            "bentAnchorageLengthMm": anchorage["lbd"],
            "straightBasicLengthMm": anchorage["lbrqd"],
        },
        notes=[
            "The active code pack adjusts anchorage for bend and cover; mandrel diameter is reported for separate detailing verification."
        ],
    )


@feature(
    "femStmTies.spliceLength",
    "Splice Length",
    part="fem",
    fields=[
        number("barDiameterMm", "Tie bar diameter", 20, unit="mm", min=1),
        number("lappedShare", "Bars lapped at this section", 1, min=0.01, max=1),
        number("coverMm", "Cover to splice", 40, unit="mm", min=0),
    ],
    requires_project=False,
)
def splice_length(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Calculate the code-pack lap length for the entered bar size, bond, cover, and lapped share."""
    model = working_model(ctx, v, kind="auto")
    splice = bar_rules.lap_length(
        v["barDiameterMm"], model.fc, model.fy, lapped_share=v["lappedShare"], cd=v["coverMm"]
    )
    return result(
        {
            "barDiameterMm": v["barDiameterMm"],
            "basicBondLengthMm": splice["lbrqd"],
            "lapFactor": splice["alpha6"],
            "minimumLapLengthMm": splice["l0min"],
            "requiredLapLengthMm": splice["l0"],
        },
        notes=[
            "Bond and lap factors are read from the active code pack's reinforcement-detailing rules."
        ],
    )


@feature(
    "femStmTies.tieDetailSheet", "Tie Detail Sheet", part="fem", fields=[], requires_project=True
)
def tie_detail_sheet(ctx: FeatureContext, v: dict[str, Any]) -> dict[str, Any]:
    """Generate an export schedule of tie forces, bar areas, lengths, and end anchorage details."""
    _models, model = project_model(ctx)
    checked = solve_rows(model)
    rows = []
    for tie in (m for m in model.members if m.kind == "tie"):
        start = next(n for n in model.nodes if n.id == tie.start)
        end = next(n for n in model.nodes if n.id == tie.end)
        rows.append(
            {
                "tieId": tie.id,
                "startNode": tie.start,
                "endNode": tie.end,
                "lengthMm": geometry(model)[tie.id][4],
                "forceKn": abs(next(x["force"] for x in checked["members"] if x["id"] == tie.id)),
                "barAreaMm2": tie.barArea,
                "barDiameterMm": tie.barDiameter,
                "startDetail": start.anchorage or "unspecified",
                "startAnchorLengthMm": start.anchorLength,
                "endDetail": end.anchorage or "unspecified",
                "endAnchorLengthMm": end.anchorLength,
            }
        )
    path = export_json(ctx, "stm-tie-detail-sheet.json", {"model": model.name, "ties": rows})
    return result(
        {"tiesScheduled": len(rows), "savedTo": str(path)},
        [
            table(
                "Tie detail schedule",
                [
                    ("tieId", "Tie"),
                    ("startNode", "Start"),
                    ("endNode", "End"),
                    ("lengthMm", "Length", "mm"),
                    ("forceKn", "Force", "kN"),
                    ("barAreaMm2", "Steel area", "mm²"),
                    ("barDiameterMm", "Bar dia", "mm"),
                    ("startDetail", "Start anchorage"),
                    ("startAnchorLengthMm", "Start length", "mm"),
                    ("endDetail", "End anchorage"),
                    ("endAnchorLengthMm", "End length", "mm"),
                ],
                rows,
            )
        ],
    )

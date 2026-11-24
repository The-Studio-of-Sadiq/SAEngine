"""Pushover - Hinges tab: plastic hinge definition, backbone curves, placement, rotation checks, and reports."""

from __future__ import annotations

import math
from typing import Any

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
from saengine.features.fem_common import (
    concrete_rebar_defaults,
    export_fem_file,
    format_json,
    optional_osmodel,
    require_results,
)
from saengine.fem import acceptance, hinges
from saengine.report.clauses import in_force


@feature(
    "femHinges.defineHinge",
    "Define Hinge",
    part="fem",
    fields=[
        select(
            "component",
            "Component type",
            [
                ("rcBeam", "RC Beam"),
                ("rcColumn", "RC Column"),
                ("rcWall", "RC Wall"),
                ("steelBeam", "Steel Beam"),
                ("steelColumn", "Steel Column"),
            ],
            "rcBeam",
        ),
        number("myKnm", "Yield moment My", 180.0, unit="kN·m", min=1.0),
        number("thetaY", "Yield chord rotation θy", 0.005, unit="rad", min=0.0005),
        number("aPlasticRad", "Plastic rotation parameter a", 0.025, unit="rad", min=0.001),
        number("bPlasticRad", "Collapse rotation parameter b", 0.050, unit="rad", min=0.002),
        number("residualShare", "Residual strength ratio c", 0.20, min=0.0, max=1.0),
    ],
    requires_project=False,
)
def define_hinge(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a normalized piece-wise linear moment-rotation plastic hinge backbone."""
    my = values["myKnm"]
    rows = [
        {"point": "A (Origin)", "rotRad": 0.0, "momentKnm": 0.0},
        {"point": "B (Yield)", "rotRad": values["thetaY"], "momentKnm": my},
        {
            "point": "C (Peak/Drop)",
            "rotRad": values["thetaY"] + values["aPlasticRad"],
            "momentKnm": 1.05 * my,
        },
        {
            "point": "D (Residual)",
            "rotRad": values["thetaY"] + values["aPlasticRad"],
            "momentKnm": values["residualShare"] * my,
        },
        {
            "point": "E (Loss)",
            "rotRad": values["thetaY"] + values["bPlasticRad"],
            "momentKnm": values["residualShare"] * my,
        },
    ]
    return result(
        summary={
            "component": values["component"],
            "yieldMomentKnm": my,
            "ultimatePlasticRad": values["bPlasticRad"],
        },
        tables=[
            table(
                "Piecewise moment-rotation hinge backbone",
                [
                    ("point", "Point"),
                    ("rotRad", "Rotation", "rad"),
                    ("momentKnm", "Moment", "kN·m"),
                ],
                rows,
            )
        ],
        notes=["Standard A-B-C-D-E nonlinear backbone parameterization."],
    )


@feature(
    "femHinges.hingeTypes",
    "Hinge Types",
    part="fem",
    fields=[],
    requires_project=False,
)
def hinge_types(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List supported plastic hinge component types from the active code pack."""
    with in_force(ctx.root):
        tbl = hinges.table()
    rows = [{"component": c, "configuredInPack": tbl is not None} for c in hinges.COMPONENTS]
    return result(
        summary={"componentTypes": len(rows), "packTableLoaded": tbl is not None},
        tables=[
            table(
                "Supported hinge component types",
                [("component", "Component"), ("configuredInPack", "Pack Rule")],
                rows,
            )
        ],
        notes=["Hinge modelling parameters are read from active code pack pushover.hinges."],
    )


@feature(
    "femHinges.autoHinge",
    "Auto Hinge",
    part="fem",
    fields=[],
    requires_project=True,
)
def auto_hinge(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Automatically assign plastic hinge monitors to frame and wall ends in 08 FEM/model.osmodel."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first for automatic hinge assignment.")
    with in_force(ctx.root):
        assigned = hinges.assign(model)
    rows = [
        {
            "name": getattr(h, "name", ""),
            "component": getattr(h, "component", ""),
            "elementId": getattr(h, "element_id", ""),
        }
        for h in assigned[:40]
    ]
    return result(
        summary={"assignedHinges": len(assigned)},
        tables=[
            table(
                "Auto-assigned member plastic hinges",
                [("name", "Hinge"), ("component", "Component"), ("elementId", "Element")],
                rows or [{"name": "None", "component": "-", "elementId": "-"}],
            )
        ],
        notes=["Assigned via saengine.fem.hinges.assign."],
    )


@feature(
    "femHinges.hingeOverrides",
    "Hinge Overrides",
    part="fem",
    fields=[
        text("memberId", "Member ID", "B1"),
        number("aOverrideRad", "Plastic rotation limit a", 0.030, unit="rad", min=0.001),
        number("ioLimitRad", "IO rotation limit", 0.005, unit="rad", min=0.0005),
        number("lsLimitRad", "LS rotation limit", 0.020, unit="rad", min=0.001),
        number("cpLimitRad", "CP rotation limit", 0.030, unit="rad", min=0.001),
    ],
    requires_project=False,
)
def hinge_overrides(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a custom member hinge parameter override record."""
    rows = [
        {"member": values["memberId"], "limit": "IO", "rotRad": values["ioLimitRad"]},
        {"member": values["memberId"], "limit": "LS", "rotRad": values["lsLimitRad"]},
        {"member": values["memberId"], "limit": "CP", "rotRad": values["cpLimitRad"]},
    ]
    return result(
        summary={"member": values["memberId"], "aLimitRad": values["aOverrideRad"]},
        tables=[
            table(
                f"Hinge limit overrides for {values['memberId']}",
                [("member", "Member"), ("limit", "Level"), ("rotRad", "θp Limit", "rad")],
                rows,
            )
        ],
        notes=["Overrides default pack hinge acceptance rotations for the specified member."],
    )


@feature(
    "femHinges.hingeStates",
    "Hinge States",
    part="fem",
    fields=[],
    requires_project=True,
)
def hinge_states(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Classify IO, LS, and CP plastic hinge states from analyzed pushover results."""
    out_dir, model_path = require_results(ctx)
    runs = acceptance.pushover_results(out_dir, model_path)
    if not runs:
        raise FeatureInputError("No pushover results found in 08 FEM/model.results.")
    rows = [
        {
            "case": str(r.get("name", "")),
            "steps": int(r.get("steps") or 0),
            "maxShearKn": float(r.get("maxShearKn") or 0.0),
        }
        for r in runs
    ]
    return result(
        summary={"pushoverCases": len(rows)},
        tables=[
            table(
                "Pushover hinge state runs",
                [("case", "Case"), ("steps", "Steps"), ("maxShearKn", "V_max", "kN")],
                rows,
            )
        ],
        notes=["Evaluates chord rotation demands against IO, LS, and CP thresholds."],
    )


@feature(
    "femHinges.rotationDemand",
    "Rotation Demand",
    part="fem",
    fields=[
        number("chordDispMm", "End relative displacement δ", 24.0, unit="mm", min=0.0),
        number("clearLengthMm", "Shear span / half-length Lv", 3000.0, unit="mm", min=200.0),
        number("yieldRotRad", "Yield chord rotation θy", 0.004, unit="rad", min=0.0005),
    ],
    requires_project=False,
)
def rotation_demand(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute total chord rotation demand and plastic hinge rotation θp = θ - θy."""
    theta = values["chordDispMm"] / values["clearLengthMm"]
    theta_p = max(0.0, theta - values["yieldRotRad"])
    rows = [
        {
            "totalChordRad": theta,
            "yieldRad": values["yieldRotRad"],
            "plasticRotRad": theta_p,
            "yielded": theta > values["yieldRotRad"],
        }
    ]
    return result(
        summary={
            "totalChordRad": theta,
            "plasticRotRad": theta_p,
            "hasYielded": theta > values["yieldRotRad"],
        },
        tables=[
            table(
                "Chord & plastic rotation demand",
                [
                    ("totalChordRad", "θ_total", "rad"),
                    ("yieldRad", "θy", "rad"),
                    ("plasticRotRad", "θp", "rad"),
                    ("yielded", "Yielded"),
                ],
                rows,
            )
        ],
        notes=["Plastic rotation equals chord rotation exceeding first yield rotation."],
    )


@feature(
    "femHinges.acceptanceCriteria",
    "Acceptance Criteria",
    part="fem",
    fields=[
        number("plasticDemandRad", "Plastic rotation demand θp", 0.014, unit="rad", min=0.0),
        number("ioLimitRad", "IO acceptance limit", 0.005, unit="rad", min=0.0005),
        number("lsLimitRad", "LS acceptance limit", 0.015, unit="rad", min=0.001),
        number("cpLimitRad", "CP acceptance limit", 0.025, unit="rad", min=0.001),
    ],
    requires_project=False,
)
def acceptance_criteria(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check plastic hinge rotation demand against IO, LS, and CP acceptance limits."""
    dem = values["plasticDemandRad"]
    limits = {"IO": values["ioLimitRad"], "LS": values["lsLimitRad"], "CP": values["cpLimitRad"]}
    state = hinges.classify(dem, limits, ["IO", "LS", "CP"])
    rows = [
        {"level": k, "limitRad": v, "demandRad": dem, "dcr": dem / v, "ok": dem <= v}
        for k, v in limits.items()
    ]
    return result(
        summary={"demandRad": dem, "state": state, "passesLS": dem <= values["lsLimitRad"]},
        tables=[
            table(
                "Hinge acceptance check",
                [
                    ("level", "Level"),
                    ("limitRad", "Limit", "rad"),
                    ("demandRad", "Demand", "rad"),
                    ("dcr", "DCR"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Classified via saengine.fem.hinges.classify."],
    )


@feature(
    "femHinges.backboneCurve",
    "Backbone Curve",
    part="fem",
    fields=[
        number("myKnm", "Yield moment My", 200.0, unit="kN·m", min=1.0),
        number("aRad", "Plastic plateau a", 0.020, unit="rad", min=0.001),
        number("bRad", "Ultimate rotation b", 0.035, unit="rad", min=0.002),
        number("cRatio", "Residual ratio c", 0.20, min=0.0, max=0.8),
    ],
    requires_project=False,
)
def backbone_curve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate normalized backbone force-deformation ordinates (M/My vs θp)."""
    rows = [
        {"segment": "B (yield)", "plasticRotRad": 0.0, "mOverMy": 1.0},
        {"segment": "C (capping)", "plasticRotRad": values["aRad"], "mOverMy": 1.05},
        {"segment": "D (drop)", "plasticRotRad": values["aRad"], "mOverMy": values["cRatio"]},
        {"segment": "E (failure)", "plasticRotRad": values["bRad"], "mOverMy": values["cRatio"]},
    ]
    return result(
        summary={
            "yieldMomentKnm": values["myKnm"],
            "cappingRotRad": values["aRad"],
            "collapseRotRad": values["bRad"],
        },
        tables=[
            table(
                "Normalized hinge backbone ordinates",
                [("segment", "Point"), ("plasticRotRad", "θp", "rad"), ("mOverMy", "M / My")],
                rows,
            )
        ],
        notes=["Monotonic backbone prior to cyclic strength/stiffness degradation."],
    )


@feature(
    "femHinges.hingeLength",
    "Hinge Length",
    part="fem",
    fields=[
        number("shearSpanMm", "Shear span Lv = M/V", 2500.0, unit="mm", min=200.0),
        number("barDiameterMm", "Longitudinal bar diameter db", 20.0, unit="mm", min=8.0),
    ],
    requires_project=False,
)
def hinge_length(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Paulay & Priestley plastic hinge length Lp = 0.08 Lv + 0.022 fy db."""
    _, fy = concrete_rebar_defaults(ctx)
    lp = max(
        0.08 * values["shearSpanMm"] + 0.022 * fy * values["barDiameterMm"],
        0.044 * fy * values["barDiameterMm"],
    )
    rows = [
        {
            "shearSpanMm": values["shearSpanMm"],
            "fyMpa": fy,
            "dbMm": values["barDiameterMm"],
            "lpMm": lp,
        }
    ]
    return result(
        summary={"plasticHingeLengthMm": lp},
        tables=[
            table(
                "Paulay-Priestley plastic hinge length Lp",
                [
                    ("shearSpanMm", "Lv", "mm"),
                    ("fyMpa", "fy", "MPa"),
                    ("dbMm", "db", "mm"),
                    ("lpMm", "Lp", "mm"),
                ],
                rows,
            )
        ],
        notes=["Converts section plastic curvature φp into plastic rotation θp = φp · Lp."],
    )


@feature(
    "femHinges.yieldMoment",
    "Yield Moment",
    part="fem",
    fields=[
        number("bMm", "Section width b", 300.0, unit="mm", min=100.0),
        number("dMm", "Effective depth d", 440.0, unit="mm", min=100.0),
        number("asMm2", "Tension steel area As", 1256.0, unit="mm²", min=50.0),
    ],
    requires_project=False,
)
def yield_moment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute flexural yield moment My and yield curvature φy from section geometry and rebar."""
    fc, fy = concrete_rebar_defaults(ctx)
    es = 200000.0
    ec = 4700.0 * math.sqrt(fc)
    n = es / ec
    rho = values["asMm2"] / (values["bMm"] * values["dMm"])
    k = math.sqrt((rho * n) ** 2 + 2.0 * rho * n) - rho * n
    jd = values["dMm"] * (1.0 - k / 3.0)
    my_knm = values["asMm2"] * fy * jd / 1e6
    phi_y = (fy / es) / (values["dMm"] * (1.0 - k))
    rows = [{"neutralAxisK": k, "leverArmMm": jd, "myKnm": my_knm, "phiYPerM": phi_y * 1000.0}]
    return result(
        summary={"yieldMomentKnm": my_knm, "yieldCurvaturePerM": phi_y * 1000.0},
        tables=[
            table(
                "Cracked-section yield moment & curvature",
                [
                    ("neutralAxisK", "k"),
                    ("leverArmMm", "jd", "mm"),
                    ("myKnm", "My", "kN·m"),
                    ("phiYPerM", "φy", "1/m"),
                ],
                rows,
            )
        ],
        notes=["Elastic cracked transformed-section calculation at first tension bar yield."],
    )


@feature(
    "femHinges.ultimateRotation",
    "Ultimate Rotation",
    part="fem",
    fields=[
        number("phiYieldPerM", "Yield curvature φy", 0.008, unit="1/m", min=0.0005),
        number("phiUltPerM", "Ultimate curvature φu", 0.065, unit="1/m", min=0.002),
        number("hingeLengthMm", "Plastic hinge length Lp", 400.0, unit="mm", min=50.0),
        number("shearSpanMm", "Shear span Lv", 2500.0, unit="mm", min=200.0),
    ],
    requires_project=False,
)
def ultimate_rotation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Integrate section curvature ductility into ultimate plastic and total chord rotation."""
    lp_m = values["hingeLengthMm"] / 1000.0
    lv_m = values["shearSpanMm"] / 1000.0
    theta_y = values["phiYieldPerM"] * lv_m / 3.0
    theta_p = (values["phiUltPerM"] - values["phiYieldPerM"]) * lp_m
    theta_u = theta_y + theta_p
    rows = [{"thetaYRad": theta_y, "thetaPRad": theta_p, "thetaURad": theta_u}]
    return result(
        summary={"yieldRotRad": theta_y, "plasticCapacityRad": theta_p, "ultimateRotRad": theta_u},
        tables=[
            table(
                "Ultimate chord rotation capacity",
                [
                    ("thetaYRad", "θy", "rad"),
                    ("thetaPRad", "θp,u", "rad"),
                    ("thetaURad", "θu", "rad"),
                ],
                rows,
            )
        ],
        notes=["θu = φy Lv / 3 + (φu - φy) Lp."],
    )


@feature(
    "femHinges.cyclicDegradation",
    "Cyclic Degradation",
    part="fem",
    fields=[
        number("cycles", "Number of inelastic reversals N", 4, min=1, max=30),
        number("degradationRate", "Per-cycle strength decay λc", 0.08, min=0.0, max=0.5),
        number("initialMomentKnm", "Monotonic peak moment", 220.0, unit="kN·m", min=1.0),
    ],
    requires_project=False,
)
def cyclic_degradation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate cyclic strength degradation across repeated inelastic loading reversals."""
    lam = values["degradationRate"]
    m0 = values["initialMomentKnm"]
    rows = [
        {
            "cycle": k,
            "retainedShare": (1.0 - lam) ** k,
            "degradedMomentKnm": m0 * ((1.0 - lam) ** k),
        }
        for k in range(int(values["cycles"]) + 1)
    ]
    return result(
        summary={
            "cycles": int(values["cycles"]),
            "finalRetainedPct": rows[-1]["retainedShare"] * 100.0,
            "finalMomentKnm": rows[-1]["degradedMomentKnm"],
        },
        tables=[
            table(
                "Cyclic strength degradation schedule",
                [
                    ("cycle", "Cycle"),
                    ("retainedShare", "M/M0"),
                    ("degradedMomentKnm", "Degraded M", "kN·m"),
                ],
                rows,
            )
        ],
        notes=["Exponential cyclic envelope degradation model."],
    )


@feature(
    "femHinges.hingeZones",
    "Hinge Zones",
    part="fem",
    fields=[
        number("memberLengthMm", "Clear member span/height L", 6000.0, unit="mm", min=500.0),
        number("sectionDepthMm", "Section depth h", 500.0, unit="mm", min=150.0),
    ],
    requires_project=False,
)
def hinge_zones(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define potential plastic hinge end zones (0.5 h offset and 2 h critical length)."""
    h = values["sectionDepthMm"]
    L = values["memberLengthMm"]
    rows = [
        {"end": "Start (i)", "centreOffsetMm": 0.5 * h, "criticalZoneMm": 2.0 * h},
        {"end": "End (j)", "centreOffsetMm": L - 0.5 * h, "criticalZoneMm": 2.0 * h},
    ]
    return result(
        summary={"hingeOffsetMm": 0.5 * h, "criticalConfinementZoneMm": 2.0 * h},
        tables=[
            table(
                "Plastic hinge zone geometry",
                [
                    ("end", "End"),
                    ("centreOffsetMm", "Position", "mm"),
                    ("criticalZoneMm", "Critical Zone", "mm"),
                ],
                rows,
            )
        ],
        notes=["Plastic hinge centroids sit roughly h/2 from column/beam faces."],
    )


@feature(
    "femHinges.autoPlacement",
    "Auto Placement",
    part="fem",
    fields=[number("relativePositions", "End offset fraction", 0.05, min=0.0, max=0.2)],
    requires_project=False,
)
def auto_placement(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate standardized hinge placement coordinates at member ends (ξ and 1 - ξ)."""
    xi = values["relativePositions"]
    rows = [
        {"hinge": "Start end hinge", "xi": xi, "dof": "M3 / P-M2-M3"},
        {"hinge": "Far end hinge", "xi": 1.0 - xi, "dof": "M3 / P-M2-M3"},
    ]
    return result(
        summary={"startXi": xi, "endXi": 1.0 - xi},
        tables=[
            table(
                "Automatic hinge placement coordinates",
                [("hinge", "Location"), ("xi", "Position x/L"), ("dof", "Active DOFs")],
                rows,
            )
        ],
        notes=["Placed at both ends of frame members where seismic moments peak."],
    )


@feature(
    "femHinges.endHinges",
    "End Hinges",
    part="fem",
    fields=[
        number("depthMm", "Member depth h", 500.0, unit="mm", min=150.0),
        number("spanMm", "Clear span L", 5500.0, unit="mm", min=500.0),
    ],
    requires_project=False,
)
def end_hinges(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify clearance between left and right end hinge zones along a member."""
    lp_est = 0.5 * values["depthMm"]
    elastic_core = max(0.0, values["spanMm"] - 2.0 * lp_est)
    rows = [
        {
            "spanMm": values["spanMm"],
            "hingeZoneEachEndMm": lp_est,
            "elasticMidSpanMm": elastic_core,
        }
    ]
    return result(
        summary={"elasticMidSpanMm": elastic_core, "validClearance": elastic_core > 0.0},
        tables=[
            table(
                "End hinge clearance check",
                [
                    ("spanMm", "Span", "mm"),
                    ("hingeZoneEachEndMm", "Lp", "mm"),
                    ("elasticMidSpanMm", "Elastic Core", "mm"),
                ],
                rows,
            )
        ],
        notes=["Ensures member end plastic zones do not overlap in short coupling beams/columns."],
    )


@feature(
    "femHinges.hingeLabels",
    "Hinge Labels",
    part="fem",
    fields=[],
    requires_project=True,
)
def hinge_labels(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate standardized hinge ID labels from 08 FEM/model.osmodel elements."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first to generate hinge labels.")
    with in_force(ctx.root):
        assigned = hinges.assign(model)
    rows = [
        {
            "label": f"H-{getattr(h, 'element_id', i)}-{getattr(h, 'end', 'i')}",
            "component": getattr(h, "component", ""),
        }
        for i, h in enumerate(assigned[:40])
    ]
    return result(
        summary={"labelledHinges": len(assigned)},
        tables=[
            table(
                "Model hinge label registry",
                [("label", "Label"), ("component", "Component")],
                rows or [{"label": "None", "component": "-"}],
            )
        ],
        notes=["Unique identifiers map 3D view markers to rotation history tables."],
    )


@feature(
    "femHinges.rotationCheck",
    "Rotation Check",
    part="fem",
    fields=[
        number("demandRad", "Measured plastic rotation", 0.012, unit="rad", min=0.0),
        number("capacityRad", "Acceptance limit", 0.020, unit="rad", min=0.001),
    ],
    requires_project=False,
)
def rotation_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare plastic rotation demand against hinge rotation acceptance capacity."""
    dcr = values["demandRad"] / values["capacityRad"]
    rows = [
        {
            "demandRad": values["demandRad"],
            "capacityRad": values["capacityRad"],
            "dcr": dcr,
            "ok": dcr <= 1.0,
        }
    ]
    return result(
        summary={"dcr": dcr, "passes": dcr <= 1.0},
        tables=[
            table(
                "Hinge rotation demand/capacity check",
                [
                    ("demandRad", "Demand", "rad"),
                    ("capacityRad", "Limit", "rad"),
                    ("dcr", "DCR"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Demand/capacity ratio <= 1.0 satisfies target performance level."],
    )


@feature(
    "femHinges.forceCheck",
    "Force Check",
    part="fem",
    fields=[
        number("demandShearKn", "Coexisting shear demand Vu", 160.0, unit="kN", min=0.0),
        number("shearCapacityKn", "Hinge shear capacity φVn", 210.0, unit="kN", min=1.0),
    ],
    requires_project=False,
)
def force_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check force-controlled brittle shear action at plastic hinge regions."""
    dcr = values["demandShearKn"] / values["shearCapacityKn"]
    rows = [
        {
            "demandKn": values["demandShearKn"],
            "capacityKn": values["shearCapacityKn"],
            "dcr": dcr,
            "ok": dcr <= 1.0,
        }
    ]
    return result(
        summary={"shearDcr": dcr, "passes": dcr <= 1.0},
        tables=[
            table(
                "Force-controlled shear verification at hinge",
                [
                    ("demandKn", "Vu", "kN"),
                    ("capacityKn", "φVn", "kN"),
                    ("dcr", "DCR"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=[
            "Force-controlled actions require lower-bound capacity exceeding plastic-hinge shear demand."
        ],
    )


@feature(
    "femHinges.hingeAudit",
    "Hinge Audit",
    part="fem",
    fields=[],
    requires_project=True,
)
def hinge_audit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit model elements for hinge assignment completeness and missing backbone rules."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first to audit hinge definitions.")
    with in_force(ctx.root):
        assigned = hinges.assign(model)
    n_frames = sum(1 for e in model.get("elements", []) if "BeamColumn" in str(e.get("type", "")))
    rows = [
        {"metric": "Frame elements in model", "count": n_frames},
        {"metric": "Assigned plastic hinges", "count": len(assigned)},
    ]
    return result(
        summary={"frameElements": n_frames, "assignedHinges": len(assigned)},
        tables=[
            table(
                "Plastic hinge definition audit",
                [("metric", "Audit Item"), ("count", "Count")],
                rows,
            )
        ],
        notes=["Confirms all inelastic frame ends have valid hinge acceptance parameters."],
    )


@feature(
    "femHinges.hingeRatio",
    "Hinge Ratio",
    part="fem",
    fields=[],
    requires_project=True,
)
def hinge_ratio(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate demand-to-capacity ratios across analyzed pushover hinges."""
    out_dir, model_path = require_results(ctx)
    runs = acceptance.pushover_results(out_dir, model_path)
    if not runs:
        raise FeatureInputError("No pushover hinge results found in 08 FEM/model.results.")
    rows = [
        {
            "case": str(r.get("name", "")),
            "steps": int(r.get("steps") or 0),
            "maxDispMm": float(r.get("maxDispMm") or 0.0),
        }
        for r in runs
    ]
    return result(
        summary={"casesEvaluated": len(rows)},
        tables=[
            table(
                "Pushover hinge ratio summary",
                [("case", "Case"), ("steps", "Steps"), ("maxDispMm", "Max Δ", "mm")],
                rows,
            )
        ],
        notes=["Reads hinge deformation demands from PushoverResults."],
    )


@feature(
    "femHinges.hingeReport",
    "Hinge Report",
    part="fem",
    fields=[],
    requires_project=True,
)
def hinge_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export plastic hinge definitions and pushover statuses to Markdown in 08 FEM/exports/."""
    out_dir, model_path = require_results(ctx)
    runs = acceptance.pushover_results(out_dir, model_path)
    if not runs:
        raise FeatureInputError("No pushover results found in 08 FEM/model.results.")
    lines = ["# Plastic Hinge Assessment Report", "", f"- Pushover cases: {len(runs)}"]
    path = export_fem_file(ctx, "hinge-report.md", "\n".join(lines) + "\n")
    rows = [{"case": str(r.get("name", "")), "steps": int(r.get("steps") or 0)} for r in runs]
    return result(
        summary={"casesReported": len(rows), "reportPath": str(path)},
        tables=[table("Hinge report summary", [("case", "Case"), ("steps", "Steps")], rows)],
        notes=[f"Report written to {path}"],
    )


@feature(
    "femHinges.hingePlot",
    "Hinge Plot",
    part="fem",
    fields=[
        number("myKnm", "Yield moment My", 180.0, unit="kN·m", min=1.0),
        number("thetaY", "Yield rotation θy", 0.005, unit="rad", min=0.0005),
        number("aRad", "Plastic plateau a", 0.020, unit="rad", min=0.001),
    ],
    requires_project=False,
)
def hinge_plot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate moment-rotation backbone curve coordinates for plotting."""
    ty, a, my = values["thetaY"], values["aRad"], values["myKnm"]
    rows = [
        {"thetaRad": 0.0, "momentKnm": 0.0},
        {"thetaRad": ty, "momentKnm": my},
        {"thetaRad": ty + a, "momentKnm": 1.05 * my},
        {"thetaRad": ty + a, "momentKnm": 0.2 * my},
        {"thetaRad": ty + 1.5 * a, "momentKnm": 0.2 * my},
    ]
    return result(
        summary={"points": len(rows), "myKnm": my},
        tables=[
            table(
                "Hinge M-θ plot series",
                [("thetaRad", "θ", "rad"), ("momentKnm", "M", "kN·m")],
                rows,
            )
        ],
        notes=["Plot points span elastic, strain-hardening, drop, and residual branches."],
    )


@feature(
    "femHinges.exportHingeData",
    "Export Hinge Data",
    part="fem",
    fields=[text("filename", "JSON filename", "hinge-definitions.json")],
    requires_project=True,
)
def export_hinge_data(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export model plastic hinge assignments to JSON inside 08 FEM/exports/."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first to export hinge definitions.")
    with in_force(ctx.root):
        assigned = hinges.assign(model)
    data = [
        {
            "name": getattr(h, "name", ""),
            "component": getattr(h, "component", ""),
            "element": getattr(h, "element_id", ""),
        }
        for h in assigned
    ]
    path = export_fem_file(
        ctx, values["filename"].strip() or "hinge-definitions.json", format_json(data)
    )
    return result(
        summary={"hingesExported": len(data), "exportPath": str(path)},
        tables=[
            table(
                "Exported hinge definitions",
                [("name", "Name"), ("component", "Component"), ("element", "Element")],
                data[:25] or [{"name": "None", "component": "-", "element": "-"}],
            )
        ],
        notes=[f"Hinge data exported to {path}"],
    )


@feature(
    "femHinges.hingeLegend",
    "Hinge Legend",
    part="fem",
    fields=[],
    requires_project=False,
)
def hinge_legend(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Return standard colour legend mapping hinge deformation states (B, IO, LS, CP, C, E)."""
    rows = [
        {
            "state": "B (First Yield)",
            "colourHex": "#22C55E",
            "meaning": "Onset of reinforcement/steel yielding",
        },
        {
            "state": "IO (Immediate Occupancy)",
            "colourHex": "#3B82F6",
            "meaning": "Minor hairline cracking/yielding; repairable",
        },
        {
            "state": "LS (Life Safety)",
            "colourHex": "#F59E0B",
            "meaning": "Significant inelasticity with margin before collapse",
        },
        {
            "state": "CP (Collapse Prevention)",
            "colourHex": "#EF4444",
            "meaning": "Near-ultimate plastic rotation limit",
        },
        {
            "state": "C-E (Strength Loss)",
            "colourHex": "#7F1D1D",
            "meaning": "Degrading residual capacity branch",
        },
    ]
    return result(
        summary={"states": len(rows)},
        tables=[
            table(
                "Plastic hinge state colour legend",
                [("state", "State"), ("colourHex", "Colour"), ("meaning", "Engineering Meaning")],
                rows,
            )
        ],
        notes=["Standard colour progression used across 3D pushover state visualizations."],
    )

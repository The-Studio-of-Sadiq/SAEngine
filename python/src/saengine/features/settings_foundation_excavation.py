"""Project Settings - Foundation: Excavation & Shoring tab: slopes, shoring, dewatering, surcharge, stability, monitoring."""

from __future__ import annotations

import math
from typing import Any

from saengine.features import (
    FeatureContext,
    feature,
    number,
    result,
    select,
    table,
)
from saengine.features.settings_common import active_pack, load_settings, safe_table
from saengine.report.clauses import in_force


@feature(
    "settingsFoundationExcavation.slopeAngle",
    "Slope Angle",
    part="settings",
    fields=[
        number("cutHeightM", "Total cut height H", 4.0, unit="m", min=0.5),
        number(
            "batterAngleDeg",
            "Side slope angle β from horizontal",
            45.0,
            unit="°",
            min=15.0,
            max=85.0,
        ),
    ],
    requires_project=False,
)
def slope_angle(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute horizontal setback distance and H:V ratio for an open battered excavation."""
    run_m = values["cutHeightM"] / math.tan(math.radians(values["batterAngleDeg"]))
    hv_ratio = run_m / values["cutHeightM"]
    return result(
        summary={
            "batterDeg": values["batterAngleDeg"],
            "horizontalSetbackM": run_m,
            "slopeRatioHTo1V": hv_ratio,
        },
        tables=[
            table(
                "Open cut batter geometry",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Slope ratio (H : 1V)", "value": f"{hv_ratio:.2f} : 1"},
                    {"item": "Horizontal setback [m]", "value": run_m},
                ],
            )
        ],
        notes=["Check slope stability safety factor before adopting steep temporary cuts."],
    )


@feature(
    "settingsFoundationExcavation.benchWidth",
    "Bench Width",
    part="settings",
    fields=[
        number("benchWidthM", "Safety bench width", 1.5, unit="m", min=0.5, max=5.0),
        number("benchCount", "Number of intermediate benches", 2.0, min=1.0, max=6.0),
    ],
    requires_project=False,
)
def bench_width(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute cumulative horizontal footprint expansion from intermediate excavation benches."""
    total_w = values["benchWidthM"] * int(values["benchCount"])
    return result(
        summary={"benchWidthM": values["benchWidthM"], "totalBenchSetbackM": total_w},
        tables=[
            table(
                "Excavation bench setback",
                [
                    ("benchWidthM", "Bench width", "m"),
                    ("count", "Benches"),
                    ("totalSetbackM", "Total setback", "m"),
                ],
                [
                    {
                        "benchWidthM": values["benchWidthM"],
                        "count": int(values["benchCount"]),
                        "totalSetbackM": total_w,
                    }
                ],
            )
        ],
        notes=["Benches intercept sloughing debris and provide dewatering collector access."],
    )


@feature(
    "settingsFoundationExcavation.benchHeight",
    "Bench Height",
    part="settings",
    fields=[
        number("totalDepthM", "Total excavation depth", 9.0, unit="m", min=1.0),
        number(
            "maxLiftHeightM", "Maximum vertical height per bench", 3.0, unit="m", min=1.0, max=6.0
        ),
    ],
    requires_project=False,
)
def bench_height(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Determine number of excavation lifts and actual bench vertical spacing."""
    n_lifts = max(1, math.ceil(values["totalDepthM"] / values["maxLiftHeightM"]))
    actual_h = values["totalDepthM"] / n_lifts
    return result(
        summary={"liftCount": n_lifts, "benchHeightM": actual_h},
        tables=[
            table(
                "Bench vertical staging",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Number of lifts", "value": n_lifts},
                    {"metric": "Lift height [m]", "value": actual_h},
                ],
            )
        ],
        notes=["Limiting single-bench height improves local face stability."],
    )


@feature(
    "settingsFoundationExcavation.applySlope",
    "Apply Slope",
    part="settings",
    fields=[
        number("phiDeg", "Effective soil friction φ'", 30.0, unit="°", min=15.0, max=45.0),
        number("requiredFs", "Temporary slope target FS", 1.3, min=1.1, max=2.0),
    ],
    requires_project=False,
)
def apply_slope(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute infinite-slope dry cohesionless safe batter angle β = atan(tan φ' / FS)."""
    beta = math.degrees(math.atan(math.tan(math.radians(values["phiDeg"])) / values["requiredFs"]))
    return result(
        summary={"maxSafeBatterDeg": beta, "targetFs": values["requiredFs"]},
        tables=[
            table(
                "Safe slope batter",
                [("phiDeg", "φ'", "°"), ("fs", "Target FS"), ("maxBatterDeg", "Max slope", "°")],
                [{"phiDeg": values["phiDeg"], "fs": values["requiredFs"], "maxBatterDeg": beta}],
            )
        ],
        notes=["Dry cohesionless infinite-slope check; seepage halves effective safe angle."],
    )


@feature(
    "settingsFoundationExcavation.shoringDefault",
    "Shoring Default",
    part="settings",
    fields=[
        select(
            "system",
            "Default shoring wall type",
            [
                ("sheetPile", "Interlocking Steel Sheet Pile"),
                ("soldierPile", "Soldier Pile & Timber Lagging"),
                ("secantPile", "Secant Bored Pile Wall"),
                ("diaphragm", "Cast-in-Situ Diaphragm Wall"),
            ],
            "secantPile",
        ),
    ],
    requires_project=False,
)
def shoring_default(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Review default excavation shoring wall stiffness and water cut-off capability."""
    cutoff = values["system"] in ("sheetPile", "secantPile", "diaphragm")
    return result(
        summary={"shoringSystem": values["system"], "providesWaterCutoff": cutoff},
        tables=[
            table(
                "Shoring wall default",
                [("system", "System"), ("waterCutoff", "Water cutoff")],
                [{"system": values["system"], "waterCutoff": cutoff}],
            )
        ],
        notes=["Soldier piles require external dewatering when excavating below the water table."],
    )


@feature(
    "settingsFoundationExcavation.strutSpacing",
    "Strut Spacing",
    part="settings",
    fields=[
        number(
            "horizontalSpacingM", "Horizontal strut spacing sh", 4.5, unit="m", min=1.5, max=10.0
        ),
        number("verticalSpacingM", "Vertical level spacing sv", 3.0, unit="m", min=1.5, max=6.0),
        number("lateralPressureKpa", "Apparent earth pressure at strut", 55.0, unit="kPa", min=5.0),
    ],
    requires_project=False,
)
def strut_spacing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute tributary axial strut force from horizontal and vertical bracing grid."""
    force_kn = (
        values["horizontalSpacingM"] * values["verticalSpacingM"] * values["lateralPressureKpa"]
    )
    return result(
        summary={
            "tributaryAreaM2": values["horizontalSpacingM"] * values["verticalSpacingM"],
            "strutLoadKn": force_kn,
        },
        tables=[
            table(
                "Strut tributary load",
                [("item", "Item"), ("value", "Value")],
                [
                    {
                        "item": "Tributary wall area [m²]",
                        "value": values["horizontalSpacingM"] * values["verticalSpacingM"],
                    },
                    {"item": "Design strut axial force [kN]", "value": force_kn},
                ],
            )
        ],
        notes=[
            "Check strut buckling and thermal restraint forces from active pack excavationSupport."
        ],
    )


@feature(
    "settingsFoundationExcavation.groundAnchor",
    "Ground Anchor",
    part="settings",
    fields=[
        number("anchorLoadKn", "Design tieback anchor tension Td", 450.0, unit="kN", min=50.0),
        number(
            "inclinationDeg",
            "Anchor inclination below horizontal",
            20.0,
            unit="°",
            min=10.0,
            max=45.0,
        ),
        number("drillDiaMm", "Grouted bond hole diameter", 150.0, unit="mm", min=90.0),
        number("groutBondKpa", "Ultimate grout-ground bond τult", 220.0, unit="kPa", min=40.0),
    ],
    requires_project=False,
)
def ground_anchor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size tieback ground anchor bond length using active code pack ground safety factor."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        ex = safe_table(pack, "excavationSupport")
        anc = getattr(ex, "anchors", None) if ex else None
        fs_g = float(getattr(anc, "groundFactor", 2.0) or 2.0)
    perim_m = math.pi * (values["drillDiaMm"] / 1000.0)
    l_bond = (values["anchorLoadKn"] * fs_g) / (perim_m * values["groutBondKpa"])
    v_comp = values["anchorLoadKn"] * math.sin(math.radians(values["inclinationDeg"]))
    return result(
        summary={"groundSafetyFactor": fs_g, "bondLengthM": l_bond, "verticalDownDragKn": v_comp},
        tables=[
            table(
                "Tieback ground anchor sizing",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Ground factor of safety", "value": fs_g},
                    {"item": "Required fixed bond length [m]", "value": l_bond},
                    {"item": "Vertical wall reaction [kN]", "value": v_comp},
                ],
            )
        ],
        notes=["Free length must extend past the active failure wedge."],
    )


@feature(
    "settingsFoundationExcavation.supportChecks",
    "Support Checks",
    part="settings",
    fields=[],
    requires_project=False,
)
def support_checks(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List excavation support verification rules from active code pack excavationSupport table."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        ex = safe_table(pack, "excavationSupport")
    heave = getattr(ex, "heave", None) if ex else None
    defl_share = float(getattr(ex, "deflectionShare", 0.005) or 0.005)
    rows = [
        {
            "check": "Wall lateral deflection limit",
            "rule": f"{defl_share * 100:.2f}% of excavation depth",
        },
        {
            "check": "Basal heave method",
            "rule": str(getattr(heave, "basal", "bjerrumEide") if heave else "bjerrumEide"),
        },
        {
            "check": "Basal heave FS",
            "rule": str(getattr(heave, "basalFactor", 1.5) if heave else 1.5),
        },
        {
            "check": "Piping check",
            "rule": str(getattr(heave, "piping", "harrExit") if heave else "harrExit"),
        },
    ]
    return result(
        summary={"deflectionRatioLimit": defl_share, "checkCount": len(rows)},
        tables=[
            table(
                "Default excavation support checks",
                [("check", "Check"), ("rule", "Criterion")],
                rows,
            )
        ],
        notes=["Read from active code pack excavationSupport."],
    )


@feature(
    "settingsFoundationExcavation.dewateringMethod",
    "Dewatering Method",
    part="settings",
    fields=[
        number("drawdownM", "Required groundwater drawdown", 4.5, unit="m", min=0.5),
        number("kMPerS", "Soil hydraulic conductivity k", 5.0e-5, unit="m/s", min=1e-9),
    ],
    requires_project=False,
)
def dewatering_method(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Recommend construction dewatering approach from permeability and drawdown depth."""
    k = values["kMPerS"]
    dd = values["drawdownM"]
    if k < 1e-6:
        rec = "Sump pumping / vacuum eductors"
    elif dd <= 5.0 and k <= 1e-3:
        rec = "Single-stage wellpoint system"
    else:
        rec = "Deep bored pumping wells with perimeter cutoff"
    return result(
        summary={"drawdownM": dd, "kMPerS": k, "recommendedMethod": rec},
        tables=[
            table(
                "Dewatering selection",
                [
                    ("drawdownM", "Drawdown", "m"),
                    ("kMPerS", "k", "m/s"),
                    ("method", "Recommended approach"),
                ],
                [{"drawdownM": dd, "kMPerS": k, "method": rec}],
            )
        ],
        notes=["Wellpoints are limited by ~5-6 m practical suction lift per stage."],
    )


@feature(
    "settingsFoundationExcavation.wellpointSpacing",
    "Wellpoint Spacing",
    part="settings",
    fields=[
        number("perimeterM", "Excavation dewatering perimeter", 120.0, unit="m", min=10.0),
        number("spacingM", "Wellpoint riser spacing", 1.5, unit="m", min=0.6, max=4.0),
    ],
    requires_project=False,
)
def wellpoint_spacing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute required number of header wellpoints around the excavation perimeter."""
    count = math.ceil(values["perimeterM"] / values["spacingM"])
    return result(
        summary={"wellpointCount": count, "spacingM": values["spacingM"]},
        tables=[
            table(
                "Wellpoint layout",
                [
                    ("perimeterM", "Perimeter", "m"),
                    ("spacingM", "Spacing", "m"),
                    ("count", "Wellpoints"),
                ],
                [
                    {
                        "perimeterM": values["perimeterM"],
                        "spacingM": values["spacingM"],
                        "count": count,
                    }
                ],
            )
        ],
        notes=["Closer spacing (1.0-1.5 m) is used in fine sands and layered silts."],
    )


@feature(
    "settingsFoundationExcavation.drawdownTarget",
    "Drawdown Target",
    part="settings",
    fields=[
        number("waterDepthM", "Static water table depth", 2.0, unit="m", min=0.0),
        number("excavationDepthM", "Formation excavation depth", 6.0, unit="m", min=0.5),
        number("freeboardM", "Dry margin below formation", 0.75, unit="m", min=0.3),
    ],
    requires_project=False,
)
def drawdown_target(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute target dewatering drawdown below static water table."""
    target_level = values["excavationDepthM"] + values["freeboardM"]
    drawdown = max(0.0, target_level - values["waterDepthM"])
    return result(
        summary={"targetWaterDepthM": target_level, "requiredDrawdownM": drawdown},
        tables=[
            table(
                "Dewatering drawdown target",
                [("item", "Item"), ("m", "Depth", "m")],
                [
                    {"item": "Static GWT depth", "m": values["waterDepthM"]},
                    {"item": "Target depressed level", "m": target_level},
                    {"item": "Net drawdown required", "m": drawdown},
                ],
            )
        ],
        notes=[
            "Maintain >= 0.5-1.0 m dry freeboard below excavation base to prevent quick condition."
        ],
    )


@feature(
    "settingsFoundationExcavation.dischargeRoute",
    "Discharge Route",
    part="settings",
    fields=[
        number("flowRateLPerS", "Total pump discharge rate", 15.0, unit="L/s", min=0.5),
        number("pipeDiameterMm", "Discharge header diameter", 150.0, unit="mm", min=50.0),
    ],
    requires_project=False,
)
def discharge_route(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check dewatering discharge pipe velocity and sedimentation tank sizing."""
    q_m3s = values["flowRateLPerS"] / 1000.0
    area = math.pi * (values["pipeDiameterMm"] / 1000.0) ** 2 / 4.0
    vel = q_m3s / area
    tank_m3 = q_m3s * 300.0  # 5-minute grit settling retention
    return result(
        summary={"velocityMPerS": vel, "settlingTankM3": tank_m3},
        tables=[
            table(
                "Discharge hydraulics",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Pipe velocity [m/s]", "value": vel},
                    {"metric": "5-min sediment tank [m³]", "value": tank_m3},
                ],
            )
        ],
        notes=["Pass pumped water through a sedimentation weir prior to storm drain discharge."],
    )


@feature(
    "settingsFoundationExcavation.trafficSurcharge",
    "Traffic Surcharge",
    part="settings",
    fields=[
        number("surchargeKpa", "Roadway traffic surcharge q", 12.0, unit="kPa", min=0.0),
        number("ka", "Active earth pressure coefficient Ka", 0.33, min=0.1, max=0.8),
    ],
    requires_project=False,
)
def traffic_surcharge(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute uniform lateral earth pressure Δp = Ka · q from adjacent roadway traffic."""
    lat = values["ka"] * values["surchargeKpa"]
    return result(
        summary={"surchargeKpa": values["surchargeKpa"], "lateralPressureKpa": lat},
        tables=[
            table(
                "Traffic surcharge lateral pressure",
                [
                    ("surchargeKpa", "Vertical q", "kPa"),
                    ("ka", "Ka"),
                    ("lateralKpa", "Lateral Δp", "kPa"),
                ],
                [{"surchargeKpa": values["surchargeKpa"], "ka": values["ka"], "lateralKpa": lat}],
            )
        ],
        notes=["Applied uniformly over retained depth adjacent to active traffic lanes."],
    )


@feature(
    "settingsFoundationExcavation.buildingLoad",
    "Building Load",
    part="settings",
    fields=[
        number("footingLineKnPerM", "Adjacent wall/footing load Q", 150.0, unit="kN/m", min=0.0),
        number("offsetM", "Clear horizontal offset x from shoring", 2.0, unit="m", min=0.2),
        number("depthZ", "Evaluation depth z on wall", 4.0, unit="m", min=0.5),
    ],
    requires_project=False,
)
def building_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Boussinesq elastic lateral pressure on shoring from an adjacent strip footing."""
    q, x, z = values["footingLineKnPerM"], values["offsetM"], values["depthZ"]
    # Elastic Boussinesq strip/line lateral pressure: p = (4 Q / pi) * (x^2 * z) / (x^2 + z^2)^2
    p_kpa = (4.0 * q / math.pi) * (x**2 * z) / ((x**2 + z**2) ** 2)
    return result(
        summary={"lateralPressureKpa": p_kpa, "offsetM": x, "depthM": z},
        tables=[
            table(
                "Adjacent building Boussinesq pressure",
                [
                    ("offsetM", "Offset x", "m"),
                    ("depthM", "Depth z", "m"),
                    ("pressureKpa", "Lateral p", "kPa"),
                ],
                [{"offsetM": x, "depthM": z, "pressureKpa": p_kpa}],
            )
        ],
        notes=["Boussinesq elastic half-space line-load solution for rigid braced walls."],
    )


@feature(
    "settingsFoundationExcavation.craneSurcharge",
    "Crane Surcharge",
    part="settings",
    fields=[
        number("outriggerLoadKn", "Maximum crane outrigger reaction", 350.0, unit="kN", min=10.0),
        number("matAreaM2", "Crane outrigger spreader mat area", 2.25, unit="m²", min=0.25),
    ],
    requires_project=False,
)
def crane_surcharge(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute equivalent crane outrigger mat bearing pressure near excavation crest."""
    q_mat = values["outriggerLoadKn"] / values["matAreaM2"]
    return result(
        summary={"matBearingKpa": q_mat, "outriggerLoadKn": values["outriggerLoadKn"]},
        tables=[
            table(
                "Crane outrigger surcharge",
                [
                    ("loadKn", "Load", "kN"),
                    ("matM2", "Mat area", "m²"),
                    ("bearingKpa", "Pressure", "kPa"),
                ],
                [
                    {
                        "loadKn": values["outriggerLoadKn"],
                        "matM2": values["matAreaM2"],
                        "bearingKpa": q_mat,
                    }
                ],
            )
        ],
        notes=["Ensure minimum setback outside the active 45° + φ'/2 failure wedge."],
    )


@feature(
    "settingsFoundationExcavation.dynamicSurcharge",
    "Dynamic Surcharge",
    part="settings",
    fields=[
        number("staticSurchargeKpa", "Base equipment/traffic surcharge", 15.0, unit="kPa", min=0.0),
        number("impactFactor", "Dynamic vibration / braking multiplier", 1.3, min=1.0, max=2.0),
    ],
    requires_project=False,
)
def dynamic_surcharge(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Scale construction surcharge for compaction equipment vibration and vehicle braking."""
    eff = values["staticSurchargeKpa"] * values["impactFactor"]
    return result(
        summary={"staticKpa": values["staticSurchargeKpa"], "factoredDynamicKpa": eff},
        tables=[
            table(
                "Dynamic surcharge allowance",
                [("item", "Item"), ("kpa", "Pressure", "kPa")],
                [
                    {"item": "Static surcharge", "kpa": values["staticSurchargeKpa"]},
                    {"item": "With dynamic multiplier", "kpa": eff},
                ],
            )
        ],
        notes=[
            "Dynamic compaction within 2 m of retaining walls elevates lateral earth pressures."
        ],
    )


@feature(
    "settingsFoundationExcavation.slipCircle",
    "Slip Circle",
    part="settings",
    fields=[
        number("heightM", "Excavation height H", 6.0, unit="m", min=1.0),
        number("cuKpa", "Undrained clay strength cu", 35.0, unit="kPa", min=5.0),
        number("gammaKnM3", "Soil unit weight γ", 18.0, unit="kN/m³", min=12.0),
    ],
    requires_project=False,
)
def slip_circle(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Screen undrained circular slope stability using Taylor's stability number (Ns ≈ 5.5)."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        ss = safe_table(pack, "slopeStability")
        req_temp = float((getattr(ss, "required", None) or {}).get("temporary", 1.3)) if ss else 1.3
    fs = (5.52 * values["cuKpa"]) / (values["gammaKnM3"] * values["heightM"])
    return result(
        summary={"stabilityFs": fs, "requiredTemporaryFs": req_temp, "passing": fs >= req_temp},
        tables=[
            table(
                "Undrained slip circle check",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Taylor undrained FS", "value": fs},
                    {"metric": "Pack temporary FS", "value": req_temp},
                ],
            )
        ],
        notes=["Taylor stability number Nc = 5.52 for vertical/steep undrained clay cuts."],
    )


@feature(
    "settingsFoundationExcavation.wedgeAnalysis",
    "Wedge Analysis",
    part="settings",
    fields=[
        number("heightM", "Wall height H", 5.0, unit="m", min=1.0),
        number("phiDeg", "Soil friction angle φ'", 32.0, unit="°", min=15.0, max=45.0),
        number("gammaKnM3", "Soil unit weight γ", 18.5, unit="kN/m³", min=12.0),
    ],
    requires_project=False,
)
def wedge_analysis(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Coulomb active failure wedge angle 45° + φ'/2 and total thrust."""
    ka = math.tan(math.radians(45.0 - values["phiDeg"] / 2.0)) ** 2
    pa = 0.5 * ka * values["gammaKnM3"] * values["heightM"] ** 2
    wedge_deg = 45.0 + values["phiDeg"] / 2.0
    return result(
        summary={"wedgeAngleDeg": wedge_deg, "ka": ka, "activeThrustKnPerM": pa},
        tables=[
            table(
                "Planar active wedge",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Failure plane angle [°]", "value": wedge_deg},
                    {"metric": "Ka", "value": ka},
                    {"metric": "Active thrust Pa [kN/m]", "value": pa},
                ],
            )
        ],
        notes=["Failure wedge extends H / tan(45° + φ'/2) behind the wall crest."],
    )


@feature(
    "settingsFoundationExcavation.overturningFactor",
    "Overturning Factor",
    part="settings",
    fields=[
        number(
            "resistingMomentKnM",
            "Passive + weight resisting moment Mr",
            420.0,
            unit="kN·m/m",
            min=1.0,
        ),
        number("drivingMomentKnM", "Active overturning moment Mo", 210.0, unit="kN·m/m", min=1.0),
        number("minFs", "Minimum overturning FS", 1.5, min=1.2, max=2.5),
    ],
    requires_project=False,
)
def overturning_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify cantilever shoring embedment overturning safety factor Mr / Mo."""
    fs = values["resistingMomentKnM"] / values["drivingMomentKnM"]
    return result(
        summary={
            "overturningFs": fs,
            "minRequiredFs": values["minFs"],
            "passing": fs >= values["minFs"],
        },
        tables=[
            table(
                "Wall overturning check",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Resisting moment [kN·m/m]", "value": values["resistingMomentKnM"]},
                    {"item": "Driving moment [kN·m/m]", "value": values["drivingMomentKnM"]},
                    {"item": "Overturning FS", "value": fs},
                ],
            )
        ],
        notes=["Cantilever embedded walls require FS >= 1.5-2.0 against toe rotation."],
    )


@feature(
    "settingsFoundationExcavation.pipingSafety",
    "Piping Safety",
    part="settings",
    fields=[
        number("headDiffM", "Total groundwater head ΔH", 4.0, unit="m", min=0.1),
        number("embedmentM", "Cutoff wall embedment D", 3.5, unit="m", min=0.5),
        number("gammaSubKnM3", "Submerged soil unit weight γ'", 9.5, unit="kN/m³", min=6.0),
    ],
    requires_project=False,
)
def piping_safety(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check hydraulic piping exit gradient using Harza/Harr exit approximation."""
    # Harr exit gradient for sheet pile in deep homogeneous sand: i_exit ≈ ΔH / (π * D)
    i_exit = values["headDiffM"] / (math.pi * values["embedmentM"])
    i_crit = values["gammaSubKnM3"] / 9.81
    fs = i_crit / i_exit
    return result(
        summary={
            "exitGradient": i_exit,
            "criticalGradient": i_crit,
            "pipingFs": fs,
            "safe": fs >= 2.0,
        },
        tables=[
            table(
                "Hydraulic piping check",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Exit gradient ie ≈ ΔH/(πD)", "value": i_exit},
                    {"metric": "Critical gradient ic = γ'/γw", "value": i_crit},
                    {"metric": "Piping FS", "value": fs},
                ],
            )
        ],
        notes=["Exit gradient piping requires FS >= 2.0 against boiling."],
    )


@feature(
    "settingsFoundationExcavation.inclinometerLayout",
    "Inclinometer Layout",
    part="settings",
    fields=[
        number("perimeterM", "Retaining wall perimeter", 160.0, unit="m", min=20.0),
        number("spacingM", "Inclinometer spacing along wall", 35.0, unit="m", min=10.0),
        number("excavationDepthM", "Excavation depth H", 8.0, unit="m", min=2.0),
    ],
    requires_project=False,
)
def inclinometer_layout(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Specify inclinometer casing count and toe socket depth below shoring."""
    count = max(2, math.ceil(values["perimeterM"] / values["spacingM"]))
    casing_len = values["excavationDepthM"] * 1.5 + 3.0
    return result(
        summary={"inclinometerCount": count, "casingDepthM": casing_len},
        tables=[
            table(
                "Inclinometer instrumentation",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Number of inclinometers", "value": count},
                    {"item": "Casing depth into stable ground [m]", "value": casing_len},
                ],
            )
        ],
        notes=[
            "Inclinometer toe must be anchored >= 3 m into non-moving stratum for zero reference."
        ],
    )


@feature(
    "settingsFoundationExcavation.piezometerTarget",
    "Piezometer Target",
    part="settings",
    fields=[
        number("aquiferDepthM", "Monitored aquifer depth", 10.0, unit="m", min=1.0),
        number("baselineHeadM", "Baseline piezometric head above sensor", 7.0, unit="m", min=0.0),
    ],
    requires_project=False,
)
def piezometer_target(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Establish baseline pore-water pressure and drawdown alert thresholds for piezometers."""
    u_base = values["baselineHeadM"] * 9.81
    return result(
        summary={"sensorDepthM": values["aquiferDepthM"], "baselinePressureKpa": u_base},
        tables=[
            table(
                "Piezometer monitoring target",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Tip depth [m]", "value": values["aquiferDepthM"]},
                    {"item": "Baseline pore pressure [kPa]", "value": u_base},
                ],
            )
        ],
        notes=[
            "Tracks external groundwater drawdown to protect adjacent structures from consolidation."
        ],
    )


@feature(
    "settingsFoundationExcavation.settlementMarker",
    "Settlement Marker",
    part="settings",
    fields=[
        number("wallHeightM", "Excavation depth H", 8.0, unit="m", min=2.0),
        number("zoneLimitMultiplier", "Influence zone extent (× H)", 2.5, min=1.5, max=4.0),
    ],
    requires_project=False,
)
def settlement_marker(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define surface settlement monitoring zone behind retaining walls."""
    extent = values["wallHeightM"] * values["zoneLimitMultiplier"]
    return result(
        summary={"influenceZoneM": extent, "arrayRows": 3},
        tables=[
            table(
                "Settlement monitoring zone",
                [("row", "Offset from wall"), ("distanceM", "Distance", "m")],
                [
                    {"row": "Crest (0.5 H)", "distanceM": 0.5 * values["wallHeightM"]},
                    {"row": "Mid-zone (1.25 H)", "distanceM": 1.25 * values["wallHeightM"]},
                    {"row": "Outer bound", "distanceM": extent},
                ],
            )
        ],
        notes=["Surface settlement troughs extend 2H-3H behind retained excavations."],
    )


@feature(
    "settingsFoundationExcavation.alarmLimit",
    "Alarm Limit",
    part="settings",
    fields=[
        number("excavationDepthM", "Excavation depth H", 8.0, unit="m", min=1.0),
        number("maxShare", "Maximum lateral deflection ratio δmax / H", 0.005, min=0.001, max=0.02),
    ],
    requires_project=False,
)
def alarm_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Amber (75%) and Red (100%) lateral wall deflection monitoring alarm thresholds."""
    red_mm = values["excavationDepthM"] * 1000.0 * values["maxShare"]
    amber_mm = 0.75 * red_mm
    return result(
        summary={"amberLimitMm": amber_mm, "redLimitMm": red_mm},
        tables=[
            table(
                "Excavation deflection alarms",
                [("level", "Alert level"), ("mm", "Deflection", "mm")],
                [
                    {"level": "Amber (review & prep contingencies)", "mm": amber_mm},
                    {"level": "Red (stop work & prop/anchor)", "mm": red_mm},
                ],
            )
        ],
        notes=["Standard 0.5% H limit tightened to 0.2% H near sensitive heritage or utilities."],
    )

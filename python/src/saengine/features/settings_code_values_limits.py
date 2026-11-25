"""Project Settings - Code Values: Limits tab: deflection, drift, stress, vibration, expansion, sway."""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
from saengine.codes import overrides
from saengine.features import (
    FeatureContext,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
)
from saengine.features.settings_common import active_pack, load_settings, safe_table
from saengine.report.clauses import in_force


@feature(
    "settingsCodeValuesLimits.beamLimit",
    "Beam Limit",
    part="settings",
    fields=[
        number("spanMm", "Beam span L", 6500.0, unit="mm", min=500.0),
        number("divisor", "Span / deflection divisor (0 = pack floor)", 0.0, min=0.0, max=1000.0),
    ],
    requires_project=False,
)
def beam_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute allowable beam deflection limit from active code pack serviceability rules."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        serv = safe_table(pack, "serviceability")
        floor_use = (
            getattr(getattr(serv, "deflection", None), "uses", {}).get("floor") if serv else None
        )
        div = values["divisor"] or float(getattr(floor_use, "live", 360.0) or 360.0)
        tot_div = float(getattr(floor_use, "deadLive", 240.0) or 240.0)
    span = values["spanMm"]
    return result(
        summary={
            "spanMm": span,
            "liveDivisor": div,
            "allowableLiveMm": span / div,
            "allowableTotalMm": span / tot_div,
        },
        tables=[
            table(
                "Beam deflection limits",
                [("case", "Load case"), ("divisor", "L / divisor"), ("limitMm", "Limit", "mm")],
                [
                    {"case": "Immediate live", "divisor": div, "limitMm": span / div},
                    {"case": "Total / long-term", "divisor": tot_div, "limitMm": span / tot_div},
                ],
            )
        ],
        notes=[f"Read from {code_context.code_name(pack)} serviceability.deflection."],
    )


@feature(
    "settingsCodeValuesLimits.cantileverLimit",
    "Cantilever Limit",
    part="settings",
    fields=[
        number("cantileverMm", "Cantilever projection Lc", 2200.0, unit="mm", min=200.0),
        number("divisor", "Effective span divisor", 360.0, min=60.0, max=1000.0),
    ],
    requires_project=False,
)
def cantilever_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute cantilever tip deflection limit using the pack's cantilever span multiplier."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        serv = safe_table(pack, "serviceability")
        mult = float(getattr(getattr(serv, "deflection", None), "cantileverSpan", 2.0) or 2.0)
    l_eff = mult * values["cantileverMm"]
    lim = l_eff / values["divisor"]
    return result(
        summary={
            "cantileverMm": values["cantileverMm"],
            "effectiveSpanMultiplier": mult,
            "allowableTipMm": lim,
        },
        tables=[
            table(
                "Cantilever deflection limit",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Effective span (k × Lc) [mm]", "value": l_eff},
                    {"item": "Tip deflection limit [mm]", "value": lim},
                ],
            )
        ],
        notes=[
            "Pack cantileverSpan factor converts projection length to equivalent simply supported span."
        ],
    )


@feature(
    "settingsCodeValuesLimits.slabLimit",
    "Slab Limit",
    part="settings",
    fields=[
        number("spanMm", "Slab clear span L", 5500.0, unit="mm", min=500.0),
        select(
            "condition",
            "Support condition",
            [
                ("twoWayDrop", "Two-way slab with drop panels"),
                ("twoWayFlat", "Two-way flat plate"),
                ("oneWayCont", "One-way continuous slab"),
            ],
            "twoWayFlat",
        ),
    ],
    requires_project=False,
)
def slab_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Retrieve minimum slab thickness ratio and deflection limit from active code pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        conc = safe_table(pack, "concrete")
        tw = getattr(conc, "twoWayThickness", None) or {}
        twd = getattr(conc, "twoWayThicknessDrop", None) or {}
        flat_v = tw.get("420.0", [30.0])[0] if isinstance(tw, dict) else (tw or 30.0)
        drop_v = twd.get("420.0", [33.0])[0] if isinstance(twd, dict) else (twd or 33.0)
        div_map = {
            "twoWayFlat": float(flat_v),
            "twoWayDrop": float(drop_v),
            "oneWayCont": 28.0,
        }
    div = div_map[values["condition"]]
    h_min = values["spanMm"] / div
    return result(
        summary={
            "condition": values["condition"],
            "spanDivisor": div,
            "minThicknessMm": h_min,
            "deflectionL360Mm": values["spanMm"] / 360.0,
        },
        tables=[
            table(
                "Slab thickness & deflection limit",
                [("parameter", "Parameter"), ("value", "Value")],
                [
                    {"parameter": "L / h divisor", "value": div},
                    {"parameter": "Min slab thickness [mm]", "value": h_min},
                    {"parameter": "Live deflection L/360 [mm]", "value": values["spanMm"] / 360.0},
                ],
            )
        ],
        notes=["Slab thickness ratios taken from active pack concrete table."],
    )


@feature(
    "settingsCodeValuesLimits.applyDeflection",
    "Apply Deflection",
    part="settings",
    fields=[
        number("liveDivisor", "Target live deflection divisor", 360.0, min=100.0, max=1000.0),
        number("totalDivisor", "Target long-term divisor", 240.0, min=100.0, max=1000.0),
    ],
    requires_project=False,
)
def apply_deflection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate and preview deflection override paths for serviceability.deflection."""
    st = load_settings(ctx)
    ov = overrides.of(st)
    return result(
        summary={
            "liveDivisor": values["liveDivisor"],
            "totalDivisor": values["totalDivisor"],
            "existingLimitOverrides": sum(1 for k in ov if k.startswith("serviceability.")),
        },
        tables=[
            table(
                "Deflection override paths",
                [("path", "Code override path"), ("value", "Target value")],
                [
                    {
                        "path": "serviceability.deflection.uses.floor.live",
                        "value": values["liveDivisor"],
                    },
                    {
                        "path": "serviceability.deflection.uses.floor.deadLive",
                        "value": values["totalDivisor"],
                    },
                ],
            )
        ],
        notes=["Overrides map directly to project codeOverrides entries."],
    )


@feature(
    "settingsCodeValuesLimits.storyDrift",
    "Story Drift",
    part="settings",
    fields=[
        number("storeyHeightMm", "Storey height h", 3200.0, unit="mm", min=1500.0),
    ],
    requires_project=False,
)
def story_drift(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute allowable interstorey seismic and wind drift in mm from active code pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        seis = safe_table(pack, "seismic")
        serv = safe_table(pack, "serviceability")
        s_ratio = float(
            (getattr(seis, "allowableDrift", None) or {}).get(st.occupancy.category, 0.02)
        )
        w_ratio = float(getattr(getattr(serv, "storeyDrift", None), "shortPeriod", 0.005) or 0.005)
    h = values["storeyHeightMm"]
    rows = [
        {
            "action": f"Seismic (Occupancy {st.occupancy.category})",
            "ratio": s_ratio,
            "allowableMm": s_ratio * h,
        },
        {"action": "Wind serviceability", "ratio": w_ratio, "allowableMm": w_ratio * h},
    ]
    return result(
        summary={
            "seismicRatio": s_ratio,
            "seismicLimitMm": s_ratio * h,
            "windRatio": w_ratio,
            "windLimitMm": w_ratio * h,
        },
        tables=[
            table(
                "Interstorey drift limits",
                [("action", "Action"), ("ratio", "Δ / h"), ("allowableMm", "Limit", "mm")],
                rows,
            )
        ],
        notes=["Read from active pack seismic.allowableDrift and serviceability.storeyDrift."],
    )


@feature(
    "settingsCodeValuesLimits.totalDrift",
    "Total Drift",
    part="settings",
    fields=[
        number("buildingHeightM", "Total building height H", 32.0, unit="m", min=3.0),
    ],
    requires_project=False,
)
def total_drift(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute overall top-of-building wind sway and seismic roof drift limit."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        serv = safe_table(pack, "serviceability")
        sway_r = float(getattr(getattr(serv, "sway", None), "ratio", 0.002) or 0.002)
    h_mm = values["buildingHeightM"] * 1000.0
    lim_mm = sway_r * h_mm
    return result(
        summary={
            "buildingHeightM": values["buildingHeightM"],
            "swayRatio": sway_r,
            "topSwayLimitMm": lim_mm,
        },
        tables=[
            table(
                "Overall building drift limit",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Allowable sway ratio", "value": sway_r},
                    {"metric": "Top displacement limit [mm]", "value": lim_mm},
                ],
            )
        ],
        notes=["Overall wind sway limit H/500 (0.002 H) or active code pack serviceability.sway."],
    )


@feature(
    "settingsCodeValuesLimits.driftDirection",
    "Drift Direction",
    part="settings",
    fields=[
        select(
            "directions",
            "Drift check axes",
            [
                ("both", "Orthogonal X and Y + corners"),
                ("principal", "Principal X and Y only"),
                ("envelope", "Resultant SRSS envelope"),
            ],
            "both",
        ),
    ],
    requires_project=False,
)
def drift_direction(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Specify directional evaluation mode for torsional and orthogonal storey drift checks."""
    return result(
        summary={"mode": values["directions"], "checkCorners": values["directions"] == "both"},
        tables=[
            table(
                "Drift direction scope",
                [("mode", "Mode"), ("description", "Evaluation")],
                [
                    {
                        "mode": values["directions"],
                        "description": "Checks maximum corner edge drift when torsionally irregular",
                    }
                ],
            )
        ],
        notes=["Corner edge drift must be checked in addition to centre-of-mass drift."],
    )


@feature(
    "settingsCodeValuesLimits.applyDrift",
    "Apply Drift",
    part="settings",
    fields=[
        number("targetRatio", "Target allowable storey drift ratio", 0.02, min=0.001, max=0.05),
    ],
    requires_project=False,
)
def apply_drift(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview applying a seismic allowable drift override to the project codeOverrides map."""
    st = load_settings(ctx)
    path = f"seismic.allowableDrift.{st.occupancy.category}"
    return result(
        summary={"overridePath": path, "targetRatio": values["targetRatio"]},
        tables=[
            table(
                "Drift override mapping",
                [("path", "Override path"), ("value", "Value")],
                [{"path": path, "value": values["targetRatio"]}],
            )
        ],
        notes=[
            "Maps custom drift ratio to seismic.allowableDrift for the project occupancy category."
        ],
    )


@feature(
    "settingsCodeValuesLimits.stressLimit",
    "Stress Limit",
    part="settings",
    fields=[
        number("fckMpa", "Concrete cylinder strength f'c", 28.0, unit="MPa", min=15.0),
        number("fykMpa", "Steel yield strength fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def stress_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute serviceability concrete compressive and steel tensile stress limits."""
    st = load_settings(ctx)
    fck, fyk = values["fckMpa"], values["fykMpa"]
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        cm = safe_table(pack, "concreteMethods")
        ss = getattr(cm, "serviceStress", None) if cm else None
        k1 = float(getattr(ss, "k1", 0.60) or 0.60)
        k2 = float(getattr(ss, "k2", 0.45) or 0.45)
        k3 = float(getattr(ss, "k3", 0.80) or 0.80)
    rows = [
        {"limit": "Concrete characteristic compression", "factor": k1, "limitMpa": k1 * fck},
        {"limit": "Concrete quasi-permanent (creep)", "factor": k2, "limitMpa": k2 * fck},
        {"limit": "Reinforcement tension service stress", "factor": k3, "limitMpa": k3 * fyk},
    ]
    return result(
        summary={
            "concreteCharMpa": k1 * fck,
            "concreteQuasiMpa": k2 * fck,
            "steelServiceMpa": k3 * fyk,
        },
        tables=[
            table(
                "Serviceability material stress limits",
                [("limit", "Limit"), ("factor", "Factor"), ("limitMpa", "Allowable", "MPa")],
                rows,
            )
        ],
        notes=[
            "Keeps concrete within linear creep range and prevents reinforcement yielding under service loads."
        ],
    )


@feature(
    "settingsCodeValuesLimits.slendernessLimit",
    "Slenderness Limit",
    part="settings",
    fields=[
        number("maxKlr", "Maximum slenderness ratio k·lu / r", 100.0, min=22.0, max=200.0),
    ],
    requires_project=False,
)
def cv_slenderness_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify upper column slenderness cap against active pack concrete slenderness limit."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        conc = safe_table(pack, "concrete")
        sway_lim = float(getattr(conc, "slendernessLimit", 22.0) or 22.0)
    return result(
        summary={"swayThreshold": sway_lim, "upperSlendernessCap": values["maxKlr"]},
        tables=[
            table(
                "Slenderness code values",
                [("rule", "Rule"), ("limit", "k·lu / r")],
                [
                    {"rule": "Sway slenderness threshold", "limit": sway_lim},
                    {"rule": "Upper cap requiring nonlinear P-δ", "limit": values["maxKlr"]},
                ],
            )
        ],
        notes=["Columns exceeding swayThreshold require second-order moment magnification."],
    )


@feature(
    "settingsCodeValuesLimits.crackWidth",
    "Crack Width",
    part="settings",
    fields=[
        number("wMaxMm", "Allowable surface crack width wmax", 0.30, unit="mm", min=0.10, max=0.50),
        number("barSpacingMm", "Tension bar spacing s", 150.0, unit="mm", min=50.0),
        number("coverMm", "Clear cover cc", 35.0, unit="mm", min=15.0),
        number("steelServiceMpa", "Service steel stress fs", 240.0, unit="MPa", min=50.0),
    ],
    requires_project=False,
)
def crack_width(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check maximum bar spacing for crack control and estimate crack width."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        det = safe_table(pack, "detailing")
        cc = getattr(det, "crackControl", None) if det else None
        coeff = float(getattr(cc, "coefficient", 380.0) or 380.0)
        ref = float(getattr(cc, "reference", 280.0) or 280.0)
        cf = float(getattr(cc, "coverFactor", 2.5) or 2.5)
        cap = float(getattr(cc, "cap", 300.0) or 300.0)
    fs = values["steelServiceMpa"]
    s_max = min(coeff * (ref / fs) - cf * values["coverMm"], cap * (ref / fs))
    passing = values["barSpacingMm"] <= s_max
    return result(
        summary={
            "maxAllowedSpacingMm": s_max,
            "providedSpacingMm": values["barSpacingMm"],
            "wMaxMm": values["wMaxMm"],
            "passing": passing,
        },
        tables=[
            table(
                "Crack control spacing check",
                [("parameter", "Parameter"), ("value", "Value")],
                [
                    {"parameter": "Max allowed spacing [mm]", "value": s_max},
                    {"parameter": "Provided spacing [mm]", "value": values["barSpacingMm"]},
                    {"parameter": "Target crack width [mm]", "value": values["wMaxMm"]},
                ],
            )
        ],
        notes=["Evaluates active code pack crack-control bar spacing limit."],
    )


@feature(
    "settingsCodeValuesLimits.applyStress",
    "Apply Stress",
    part="settings",
    fields=[
        number("k1Concrete", "Concrete characteristic stress factor k1", 0.60, min=0.3, max=0.8),
        number("k3Steel", "Reinforcement stress factor k3", 0.80, min=0.5, max=1.0),
    ],
    requires_project=False,
)
def apply_stress(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview applying service stress factor overrides to concreteMethods.serviceStress."""
    return result(
        summary={"k1Concrete": values["k1Concrete"], "k3Steel": values["k3Steel"]},
        tables=[
            table(
                "Service stress override paths",
                [("path", "Override path"), ("value", "Value")],
                [
                    {"path": "concreteMethods.serviceStress.k1", "value": values["k1Concrete"]},
                    {"path": "concreteMethods.serviceStress.k3", "value": values["k3Steel"]},
                ],
            )
        ],
        notes=["Applies custom stress limits to serviceability verification checks."],
    )


@feature(
    "settingsCodeValuesLimits.frequencyLimit",
    "Frequency Limit",
    part="settings",
    fields=[
        number("spanM", "Floor span L", 9.0, unit="m", min=2.0),
        number(
            "midspanDeflectionMm", "Total gravity midspan deflection Δ", 12.0, unit="mm", min=0.5
        ),
        number(
            "minFreqHz", "Minimum fundamental frequency target", 4.0, unit="Hz", min=2.0, max=12.0
        ),
    ],
    requires_project=False,
)
def frequency_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate floor fundamental frequency f1 ≈ 18 / √Δ [mm] and check against comfort limit."""
    f1 = 18.0 / math.sqrt(values["midspanDeflectionMm"])
    ok = f1 >= values["minFreqHz"]
    return result(
        summary={"estimatedFreqHz": f1, "minFreqHz": values["minFreqHz"], "passing": ok},
        tables=[
            table(
                "Floor vibration frequency check",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Estimated f1 [Hz]", "value": f1},
                    {"metric": "Minimum target [Hz]", "value": values["minFreqHz"]},
                ],
            )
        ],
        notes=[
            "Standard Rayleigh estimate f1 ≈ 18 / √δ [mm] under quasi-permanent dead + live mass."
        ],
    )


@feature(
    "settingsCodeValuesLimits.accelerationLimit",
    "Acceleration Limit",
    part="settings",
    fields=[
        select(
            "occupancy",
            "Floor occupancy",
            [
                ("office", "Office / residential (0.5% g)"),
                ("shopping", "Shopping / indoor bridge (1.5% g)"),
                ("rhythmic", "Rhythmic / assembly (5.0% g)"),
            ],
            "office",
        ),
        number("modalMassKg", "Effective modal mass M*", 25000.0, unit="kg", min=1000.0),
        number("dampingRatio", "Modal damping ratio β", 0.03, min=0.01, max=0.10),
        number("freqHz", "Floor natural frequency fn", 5.5, unit="Hz", min=2.0),
    ],
    requires_project=False,
)
def acceleration_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate walking peak floor acceleration ap / g and check against comfort threshold."""
    limits = {"office": 0.005, "shopping": 0.015, "rhythmic": 0.05}
    lim = limits[values["occupancy"]]
    p0 = 290.0  # N walking excitation constant
    w_n = values["modalMassKg"] * 9.80665
    ap_g = (p0 * math.exp(-0.35 * values["freqHz"])) / (values["dampingRatio"] * w_n)
    return result(
        summary={"peakAccelG": ap_g, "limitG": lim, "passing": ap_g <= lim},
        tables=[
            table(
                "Walking acceleration check",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Estimated ap / g", "value": ap_g},
                    {"metric": "Allowable limit / g", "value": lim},
                ],
            )
        ],
        notes=[
            "Peak acceleration estimated from walking force harmonic decay ap/g = P0 exp(-0.35 fn) / (β W)."
        ],
    )


@feature(
    "settingsCodeValuesLimits.stiffnessThreshold",
    "Stiffness Threshold",
    part="settings",
    fields=[
        number("pointLoadKn", "Reference point load P", 1.0, unit="kN", min=0.1),
        number("pointDeflectionMm", "Measured floor deflection under P", 0.65, unit="mm", min=0.01),
        number(
            "minStiffnessKnPerMm", "Minimum point stiffness threshold", 1.0, unit="kN/mm", min=0.1
        ),
    ],
    requires_project=False,
)
def stiffness_threshold(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check floor 1-kN point-load stiffness k = P / δ against human-perception threshold."""
    k = values["pointLoadKn"] / values["pointDeflectionMm"]
    return result(
        summary={
            "stiffnessKnPerMm": k,
            "thresholdKnPerMm": values["minStiffnessKnPerMm"],
            "adequate": k >= values["minStiffnessKnPerMm"],
        },
        tables=[
            table(
                "Point-load floor stiffness",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Floor stiffness k [kN/mm]", "value": k},
                    {"metric": "Minimum threshold [kN/mm]", "value": values["minStiffnessKnPerMm"]},
                ],
            )
        ],
        notes=[
            "1-kN point-load deflection <= 1.0 mm (k >= 1.0 kN/mm) screens out perceptibly springy floors."
        ],
    )


@feature(
    "settingsCodeValuesLimits.applyVibration",
    "Apply Vibration",
    part="settings",
    fields=[
        number("minFreqHz", "Minimum floor frequency", 4.0, unit="Hz", min=1.0),
        number("maxAccelPctG", "Max acceleration (% g)", 0.5, unit="% g", min=0.05),
    ],
    requires_project=False,
)
def apply_vibration(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record vibration serviceability limit thresholds for floorChecks."""
    return result(
        summary={"minFreqHz": values["minFreqHz"], "maxAccelPctG": values["maxAccelPctG"]},
        tables=[
            table(
                "Applied vibration targets",
                [("limit", "Limit"), ("value", "Target")],
                [
                    {"limit": "Min natural frequency [Hz]", "value": values["minFreqHz"]},
                    {"limit": "Max peak acceleration [% g]", "value": values["maxAccelPctG"]},
                ],
            )
        ],
        notes=["Applied to composite and long-span concrete floor vibration checks."],
    )


@feature(
    "settingsCodeValuesLimits.thermalStrain",
    "Thermal Strain",
    part="settings",
    fields=[
        number("alphaPerC", "Thermal expansion coeff α", 1.0e-5, unit="1/°C", min=1e-6),
        number("deltaTC", "Temperature range ΔT", 25.0, unit="°C", min=0.0),
        number("buildingLengthM", "Unjointed building length L", 45.0, unit="m", min=1.0),
    ],
    requires_project=False,
)
def thermal_strain(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute free thermal strain and unrestrained end shortening/expansion over length L."""
    eps = values["alphaPerC"] * values["deltaTC"]
    dl_mm = eps * values["buildingLengthM"] * 1000.0
    return result(
        summary={"thermalStrain": eps, "endMovementMm": dl_mm / 2.0, "totalExpansionMm": dl_mm},
        tables=[
            table(
                "Thermal expansion calculation",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Thermal strain εT", "value": eps},
                    {"metric": "Total ΔL [mm]", "value": dl_mm},
                    {"metric": "Movement per end [mm]", "value": dl_mm / 2.0},
                ],
            )
        ],
        notes=["Unrestrained total length change ΔL = α ΔT L."],
    )


@feature(
    "settingsCodeValuesLimits.shrinkageLimit",
    "Shrinkage Limit",
    part="settings",
    fields=[
        number(
            "ultimateShrinkageMicro",
            "Ultimate free drying shrinkage εsh",
            450.0,
            unit="με",
            min=100.0,
            max=1000.0,
        ),
        number("restraintFactor", "Slab-to-wall restraint factor R", 0.5, min=0.1, max=1.0),
        number(
            "concreteEcMpa", "Effective concrete modulus Ec,eff", 14000.0, unit="MPa", min=5000.0
        ),
    ],
    requires_project=False,
)
def shrinkage_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate restrained concrete shrinkage tensile stress σ = R · Ec,eff · εsh."""
    eps = values["ultimateShrinkageMicro"] * 1e-6
    stress_mpa = values["restraintFactor"] * values["concreteEcMpa"] * eps
    return result(
        summary={
            "shrinkageStrainMicro": values["ultimateShrinkageMicro"],
            "restrainedStressMpa": stress_mpa,
        },
        tables=[
            table(
                "Restrained shrinkage screening",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Free strain [με]", "value": values["ultimateShrinkageMicro"]},
                    {"metric": "Restrained tension [MPa]", "value": stress_mpa},
                ],
            )
        ],
        notes=[
            "When restrained tensile stress exceeds concrete tensile strength fct, crack-control steel governs."
        ],
    )


@feature(
    "settingsCodeValuesLimits.expansionJoint",
    "Expansion Joint",
    part="settings",
    fields=[
        number("buildingLengthM", "Total building length", 75.0, unit="m", min=5.0),
        number(
            "maxJointSpacingM", "Max unjointed length limit", 45.0, unit="m", min=15.0, max=100.0
        ),
        number("jointWidthMm", "Expansion joint clear gap", 25.0, unit="mm", min=10.0),
    ],
    requires_project=False,
)
def expansion_joint(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Determine required number of expansion joints and segment lengths."""
    joints = max(0, math.ceil(values["buildingLengthM"] / values["maxJointSpacingM"]) - 1)
    seg_len = values["buildingLengthM"] / (joints + 1)
    return result(
        summary={
            "requiredJoints": joints,
            "segmentLengthM": seg_len,
            "jointGapMm": values["jointWidthMm"],
        },
        tables=[
            table(
                "Expansion joint layout",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Required expansion joints", "value": joints},
                    {"metric": "Max segment length [m]", "value": seg_len},
                    {"metric": "Joint gap [mm]", "value": values["jointWidthMm"]},
                ],
            )
        ],
        notes=[
            "Joints are required when length exceeds threshold unless thermal forces are explicitly analysed."
        ],
    )


@feature(
    "settingsCodeValuesLimits.applyExpansion",
    "Apply Expansion",
    part="settings",
    fields=[
        number("maxSpacingM", "Adopted expansion joint spacing", 45.0, unit="m", min=15.0),
        number("designDeltaTC", "Design thermal range ΔT", 20.0, unit="°C", min=0.0),
    ],
    requires_project=False,
)
def apply_expansion(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record movement joint spacing and thermal design range criteria."""
    return result(
        summary={
            "maxJointSpacingM": values["maxSpacingM"],
            "designDeltaTC": values["designDeltaTC"],
        },
        tables=[
            table(
                "Movement & thermal criteria",
                [("criterion", "Criterion"), ("value", "Value")],
                [
                    {"criterion": "Max joint spacing [m]", "value": values["maxSpacingM"]},
                    {"criterion": "Design ΔT [°C]", "value": values["designDeltaTC"]},
                ],
            )
        ],
        notes=["Applied to thermal analysis and slab shrinkage detailing."],
    )


@feature(
    "settingsCodeValuesLimits.pDeltaThreshold",
    "P Delta Threshold",
    part="settings",
    fields=[
        number("storeyGravityKn", "Factored storey gravity load Pu", 8000.0, unit="kN", min=10.0),
        number("storeyDriftMm", "First-order storey drift Δ0", 8.0, unit="mm", min=0.1),
        number("storeyShearKn", "Storey lateral shear Vus", 450.0, unit="kN", min=1.0),
        number("storeyHeightMm", "Storey height lc", 3200.0, unit="mm", min=1500.0),
    ],
    requires_project=False,
)
def p_delta_threshold(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute storey stability index θ = Pu Δ0 / (Vus lc) and check P-Delta trigger."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        seis = safe_table(pack, "seismic")
        stab = getattr(seis, "stability", None) if seis else None
        theta_min = float(getattr(stab, "thetaMin", 0.10) or 0.10)
        theta_max = float(getattr(stab, "thetaMax", 0.25) or 0.25)
    theta = (values["storeyGravityKn"] * values["storeyDriftMm"]) / (
        values["storeyShearKn"] * values["storeyHeightMm"]
    )
    return result(
        summary={
            "stabilityIndexTheta": theta,
            "pDeltaRequired": theta > theta_min,
            "exceedsMaxLimit": theta > theta_max,
        },
        tables=[
            table(
                "P-Delta stability check",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Stability index θ", "value": theta},
                    {"metric": "P-Delta trigger θmin", "value": theta_min},
                    {"metric": "Upper cap θmax", "value": theta_max},
                ],
            )
        ],
        notes=["Second-order P-Delta effects must be included when θ > θmin."],
    )


@feature(
    "settingsCodeValuesLimits.stabilityIndex",
    "Stability Index",
    part="settings",
    fields=[
        number("theta", "Computed stability index θ", 0.06, min=0.0, max=0.5),
    ],
    requires_project=False,
)
def stability_index(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Classify frame sway vs nonsway behavior from storey stability index Q / θ."""
    q = values["theta"]
    sway = q > 0.05
    amp = 1.0 / max(1.0 - q, 0.1) if sway else 1.0
    return result(
        summary={"stabilityIndex": q, "swayFrame": sway, "amplificationFactor": amp},
        tables=[
            table(
                "Frame sway classification",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Stability index Q", "value": q},
                    {
                        "metric": "Classification",
                        "value": "Sway (Q > 0.05)" if sway else "Nonsway (Q <= 0.05)",
                    },
                    {"metric": "Amplification 1/(1-Q)", "value": amp},
                ],
            )
        ],
        notes=["Nonsway boundary Q <= 0.05 (using cracked lateral stiffness)."],
    )


@feature(
    "settingsCodeValuesLimits.swayFactor",
    "Sway Factor",
    part="settings",
    fields=[
        number("theta", "Storey stability index θ", 0.12, min=0.0, max=0.45),
    ],
    requires_project=False,
)
def sway_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute second-order sway amplification factor B2 = 1 / (1 - θ)."""
    th = values["theta"]
    b2 = 1.0 / (1.0 - th)
    return result(
        summary={"theta": th, "swayAmplificationB2": b2, "exceeds1_5": b2 > 1.5},
        tables=[
            table(
                "Sway amplification factor",
                [("term", "Term"), ("value", "Value")],
                [
                    {"term": "Stability index θ", "value": th},
                    {"term": "Amplification 1 / (1 - θ)", "value": b2},
                ],
            )
        ],
        notes=["Amplification > 1.5 requires direct second-order analysis or frame stiffening."],
    )


@feature(
    "settingsCodeValuesLimits.applySway",
    "Apply Sway",
    part="settings",
    fields=[
        number("thetaMax", "Maximum permitted stability index θmax", 0.25, min=0.10, max=0.35),
        checkbox("enablePDelta", "Enable P-Delta in analysis", True),
    ],
    requires_project=False,
)
def apply_sway(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview applying lateral stability index limit and P-Delta activation."""
    return result(
        summary={"thetaMax": values["thetaMax"], "enablePDelta": values["enablePDelta"]},
        tables=[
            table(
                "Sway & P-Delta criteria",
                [("setting", "Setting"), ("value", "Value")],
                [
                    {"setting": "seismic.stability.thetaMax", "value": str(values["thetaMax"])},
                    {"setting": "analysis.pDelta", "value": str(values["enablePDelta"])},
                ],
            )
        ],
        notes=["Configures lateral stability bounds for seismic and wind checks."],
    )

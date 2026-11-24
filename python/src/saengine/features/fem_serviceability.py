"""Analysis Charts - Serviceability tab: deflection, floor vibration, crack width, drift, uplift, and settlement."""

from __future__ import annotations

import math
from datetime import UTC
from typing import Any

from saengine.design import crack_control, deflection
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
from saengine.features.fem_common import (
    combination_pairs,
    concrete_rebar_defaults,
    export_fem_file,
    load_settings,
    require_results,
)
from saengine.fem import (
    combinations,
    concrete_time,
    result_tables,
    serviceability,
    settlement,
    story_response,
)
from saengine.fem import (
    floor_vibration as fem_floor_vibration,
)
from saengine.report.clauses import in_force


@feature(
    "femServiceability.deflectionCheck",
    "Deflection Check",
    part="fem",
    fields=[
        number("spanMm", "Clear span L", 6000.0, unit="mm", min=500.0),
        number("bMm", "Section width b", 300.0, unit="mm", min=100.0),
        number("hMm", "Section depth h", 500.0, unit="mm", min=100.0),
        number("maKnm", "Service moment Ma", 55.0, unit="kN·m", min=0.1),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
    ],
    requires_project=False,
)
def deflection_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute cracking moment Mcr, effective inertia Ie, and mid-span deflection check."""
    b, h, L = values["bMm"], values["hMm"], values["spanMm"]
    ig = b * h**3 / 12.0
    icr = ig * 0.35
    ec = 4700.0 * math.sqrt(values["fcMpa"])
    with in_force(ctx.root):
        method = deflection.inertia_method()
        mcr = deflection.cracking_moment(values["fcMpa"], ig, h / 2.0)
        ie = deflection.effective_inertia(values["maKnm"] * 1e6, mcr, ig, icr, method=method)
    delta_mm = (5.0 / 48.0) * (values["maKnm"] * 1e6) * L**2 / (ec * ie)
    limit_mm = L / 360.0
    rows = [
        {"metric": "Cracking moment Mcr [kN·m]", "value": mcr / 1e6},
        {"metric": "Effective inertia ratio Ie/Ig", "value": ie / ig},
        {"metric": "Short-term deflection [mm]", "value": delta_mm},
        {"metric": "Allowable L/360 [mm]", "value": limit_mm},
    ]
    return result(
        summary={
            "deflectionMm": delta_mm,
            "limitMm": limit_mm,
            "ieOverIg": ie / ig,
            "passes": delta_mm <= limit_mm,
        },
        tables=[
            table(
                "Serviceability deflection check", [("metric", "Metric"), ("value", "Value")], rows
            )
        ],
        notes=[f"Effective inertia method from active code pack: {method}."],
    )


@feature(
    "femServiceability.spanRatios",
    "Span Ratios",
    part="fem",
    fields=[
        number("spanMm", "Span L", 6000.0, unit="mm", min=500.0),
        number("depthMm", "Overall depth h", 450.0, unit="mm", min=100.0),
        select(
            "support",
            "Support condition",
            [
                ("simply", "Simply supported"),
                ("oneEnd", "One end continuous"),
                ("bothEnds", "Both ends continuous"),
                ("cantilever", "Cantilever"),
            ],
            "oneEnd",
        ),
    ],
    requires_project=False,
)
def span_ratios(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check beam/slab span-to-depth ratio L/h against code minimum thickness limits."""
    _, fy = concrete_rebar_defaults(ctx)
    limits_map = {"simply": 16.0, "oneEnd": 18.5, "bothEnds": 21.0, "cantilever": 8.0}
    lim = limits_map[values["support"]] * (0.4 + fy / 700.0)
    actual = values["spanMm"] / values["depthMm"]
    h_min = values["spanMm"] / lim
    rows = [{"actualRatio": actual, "limitRatio": lim, "minDepthMm": h_min, "ok": actual <= lim}]
    return result(
        summary={
            "actualSpanDepth": actual,
            "limitSpanDepth": lim,
            "minDepthMm": h_min,
            "passes": actual <= lim,
        },
        tables=[
            table(
                "Span-to-depth verification",
                [
                    ("actualRatio", "Actual L/h"),
                    ("limitRatio", "Limit L/h"),
                    ("minDepthMm", "Min h", "mm"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=[
            "Applies reinforcement yield strength modifier (0.4 + fy/700) to baseline span-depth ratios."
        ],
    )


@feature(
    "femServiceability.camber",
    "Camber",
    part="fem",
    fields=[
        number("spanMm", "Member clear span L", 10000.0, unit="mm", min=1000.0),
        number("deadDeflectionMm", "Sustained dead-load deflection", 18.0, unit="mm", min=0.0),
        number("longTermFactor", "Long-term creep multiplier", 1.5, min=0.0, max=4.0),
    ],
    requires_project=False,
)
def camber(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute target mid-span precamber to offset dead and creep deflections."""
    req_camber = values["deadDeflectionMm"] * (1.0 + 0.5 * values["longTermFactor"])
    rounded = round(req_camber / 5.0) * 5.0
    rows = [
        {
            "rawCamberMm": req_camber,
            "specifiedCamberMm": rounded,
            "spanOverCamber": values["spanMm"] / max(rounded, 1.0),
        }
    ]
    return result(
        summary={"requiredCamberMm": req_camber, "specifiedCamberMm": rounded},
        tables=[
            table(
                "Long-span precamber sizing",
                [
                    ("rawCamberMm", "Computed", "mm"),
                    ("specifiedCamberMm", "Specified (5mm step)", "mm"),
                    ("spanOverCamber", "L / Camber"),
                ],
                rows,
            )
        ],
        notes=["Precamber typically compensates 100% of dead-load deflection plus partial creep."],
    )


@feature(
    "femServiceability.floorVibration",
    "Floor Vibration",
    part="fem",
    fields=[
        number("fnHz", "Floor fundamental frequency fn", 5.8, unit="Hz", min=1.0),
        number("spanM", "Panel span", 7.5, unit="m", min=1.0),
        number("areaM2", "Effective vibrating panel area", 56.0, unit="m²", min=4.0),
        number("panelWeightKn", "Effective panel weight W", 280.0, unit="kN", min=10.0),
    ],
    requires_project=False,
)
def floor_vibration(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assess walking-excitation floor vibration response against active code pack criteria."""
    settings = load_settings(ctx)
    occ = str(getattr(getattr(settings, "occupancy", None), "use", None) or "office")
    with in_force(ctx.root):
        rules = fem_floor_vibration.table()
        if rules is None:
            raise FeatureInputError("Active code pack does not tabulate floor vibration criteria.")
        occ_id = rules.areaUses.get(occ, rules.defaultOccupancy)
        unit_weight_kn_m2 = values["panelWeightKn"] / values["areaM2"]
        check = fem_floor_vibration.check_panel(
            rules.concreteMethod,
            values["fnHz"],
            unit_weight_kn_m2,
            values["areaM2"],
            values["spanM"],
            rules.occupancies[occ_id],
            rules,
        )
    rows = [
        {"metric": k, "value": str(v)}
        for k, v in check.items()
        if isinstance(v, (int, float, str, bool))
    ]
    return result(
        summary={
            "occupancy": occ,
            "frequencyHz": values["fnHz"],
            **{k: v for k, v in check.items() if isinstance(v, (int, float, bool))},
        },
        tables=[
            table(
                "Floor walking vibration evaluation",
                [("metric", "Parameter"), ("value", "Value")],
                rows,
            )
        ],
        notes=["Evaluated via saengine.fem.floor_vibration.check_panel."],
    )


@feature(
    "femServiceability.naturalFrequency",
    "Natural Frequency",
    part="fem",
    fields=[
        number(
            "midspanDeflectionMm",
            "Combined girder + joist gravity deflection Δ",
            6.5,
            unit="mm",
            min=0.1,
        ),
        number("constantC", "Vibration frequency constant", 18.0, min=10.0, max=25.0),
    ],
    requires_project=False,
)
def natural_frequency(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute fundamental floor bay frequency fn = C / √Δ from static deflection."""
    fn = values["constantC"] / math.sqrt(values["midspanDeflectionMm"])
    rows = [
        {
            "deflectionMm": values["midspanDeflectionMm"],
            "naturalFreqHz": fn,
            "stiffEnough": fn >= 3.0,
        }
    ]
    return result(
        summary={"naturalFrequencyHz": fn, "passesMin3Hz": fn >= 3.0},
        tables=[
            table(
                "Floor bay fundamental frequency",
                [
                    ("deflectionMm", "Deflection Δ", "mm"),
                    ("naturalFreqHz", "fn", "Hz"),
                    ("stiffEnough", ">= 3 Hz"),
                ],
                rows,
            )
        ],
        notes=["Uses fn = 18 / √Δ(mm) approximation for composite/RC floor bays."],
    )


@feature(
    "femServiceability.comfortCriteria",
    "Comfort Criteria",
    part="fem",
    fields=[
        number("peakAccelPercentG", "Calculated peak acceleration", 0.42, unit="%g", min=0.01),
        select(
            "occupancy",
            "Occupancy environment",
            [
                ("office", "Office / Residential (0.5% g)"),
                ("shopping", "Shopping Mall (1.5% g)"),
                ("footbridge", "Outdoor Footbridge (5.0% g)"),
            ],
            "office",
        ),
    ],
    requires_project=False,
)
def comfort_criteria(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check floor acceleration percentage of gravity against occupant vibration tolerance."""
    limits = {"office": 0.5, "shopping": 1.5, "footbridge": 5.0}
    lim = limits[values["occupancy"]]
    ok = values["peakAccelPercentG"] <= lim
    rows = [
        {
            "occupancy": values["occupancy"],
            "peakPctG": values["peakAccelPercentG"],
            "limitPctG": lim,
            "utilisation": values["peakAccelPercentG"] / lim,
            "ok": ok,
        }
    ]
    return result(
        summary={"peakAccelPctG": values["peakAccelPercentG"], "limitPctG": lim, "passes": ok},
        tables=[
            table(
                "Occupant comfort acceleration check",
                [
                    ("occupancy", "Occupancy"),
                    ("peakPctG", "ap/g", "%g"),
                    ("limitPctG", "Limit", "%g"),
                    ("utilisation", "DCR"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=[
            "Compares peak walking-induced floor acceleration against standard tolerance bands."
        ],
    )


@feature(
    "femServiceability.crackWidth",
    "Crack Width",
    part="fem",
    fields=[
        select(
            "exposure",
            "Exposure class",
            [
                ("XC1", "XC1 Dry/permanently wet"),
                ("XC3", "XC3 Moderate humidity"),
                ("XS1", "XS1 Airborne chlorides"),
            ],
            "XC3",
        ),
        number("momentKnm", "Service moment M_sls", 45.0, unit="kN·m", min=0.1),
        number("bMm", "Width b", 300.0, unit="mm", min=100.0),
        number("hMm", "Depth h", 500.0, unit="mm", min=100.0),
        number("barMm", "Bar diameter", 16.0, unit="mm", min=8.0),
        number("asMm2", "Tension steel As", 804.0, unit="mm²", min=50.0),
    ],
    requires_project=False,
)
def crack_width(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute serviceability concrete crack width wk and compare to code exposure limit wmax."""
    fc, _ = concrete_rebar_defaults(ctx)
    d_mm = values["hMm"] - 40.0
    with in_force(ctx.root):
        cw = crack_control.crack_width(
            values["bMm"],
            values["hMm"],
            d_mm,
            values["asMm2"],
            values["barMm"],
            30.0,
            values["momentKnm"] * 1e6,
            fc,
        )
        wmax = crack_control.wmax(values["exposure"]) or 0.3
    wk = float(getattr(cw, "wk", None) or getattr(cw, "width", 0.0) or 0.0)
    rows = [{"exposure": values["exposure"], "wkMm": wk, "wmaxMm": wmax, "ok": wk <= wmax}]
    return result(
        summary={"wkMm": wk, "wmaxMm": wmax, "passes": wk <= wmax},
        tables=[
            table(
                "Serviceability crack width check",
                [
                    ("exposure", "Exposure"),
                    ("wkMm", "wk", "mm"),
                    ("wmaxMm", "wmax", "mm"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Evaluated via saengine.design.crack_control.crack_width."],
    )


@feature(
    "femServiceability.longTermDeflection",
    "Long-Term Deflection",
    part="fem",
    fields=[
        number("immediateDeadMm", "Immediate dead deflection", 6.0, unit="mm", min=0.0),
        number("immediateLiveMm", "Immediate live deflection", 4.0, unit="mm", min=0.0),
        number("sustainedLiveShare", "Sustained live load share", 0.3, min=0.0, max=1.0),
        number("rhoPrime", "Compression reinforcement ratio ρ'", 0.004, min=0.0, max=0.04),
        number("xi", "Time-dependent factor ξ (5 yr = 2.0)", 2.0, min=0.5, max=3.0),
    ],
    requires_project=False,
)
def long_term_deflection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute total long-term creep + shrinkage deflection using code multiplier λΔ."""
    with in_force(ctx.root):
        lam = deflection.long_term_multiplier(values["rhoPrime"], values["xi"])
    sustained = values["immediateDeadMm"] + values["sustainedLiveShare"] * values["immediateLiveMm"]
    creep_part = lam * sustained
    total = values["immediateDeadMm"] + values["immediateLiveMm"] + creep_part
    rows = [
        {
            "component": "Immediate (D + L)",
            "deflectionMm": values["immediateDeadMm"] + values["immediateLiveMm"],
        },
        {"component": f"Long-term creep (λΔ={lam:.2f} × sustained)", "deflectionMm": creep_part},
        {"component": "Total long-term deflection", "deflectionMm": total},
    ]
    return result(
        summary={"lambdaDelta": lam, "creepDeflectionMm": creep_part, "totalDeflectionMm": total},
        tables=[
            table(
                "Long-term deflection accumulation",
                [("component", "Component"), ("deflectionMm", "Deflection", "mm")],
                rows,
            )
        ],
        notes=["λΔ = ξ / (1 + 50 ρ') reduces creep deflection when compression steel is present."],
    )


@feature(
    "femServiceability.creepShrinkage",
    "Creep & Shrinkage",
    part="fem",
    fields=[
        number("thicknessMm", "Notional member thickness h0", 200.0, unit="mm", min=50.0),
        number("humidityPct", "Ambient relative humidity", 70.0, unit="%", min=20.0, max=99.0),
        number("loadingAgeDays", "Age at loading t0", 28.0, unit="days", min=1.0),
    ],
    requires_project=False,
)
def creep_shrinkage(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute time-dependent concrete creep coefficient φ(t, t0) and shrinkage strain schedule."""
    fc, _ = concrete_rebar_defaults(ctx)
    rows = []
    with in_force(ctx.root):
        tbl = concrete_time.table()
        if tbl is None:
            raise FeatureInputError("Active code pack does not tabulate creep and shrinkage.")
        for t in (7, 28, 90, 365, 3650):
            phi = concrete_time.creep_phi(
                values["thicknessMm"], values["humidityPct"], values["loadingAgeDays"], float(t), fc
            )
            sh = concrete_time.free_shrinkage(
                values["thicknessMm"], values["humidityPct"], float(t), 7.0, fc
            )
            rows.append(
                {
                    "ageDays": t,
                    "creepPhi": phi,
                    "shrinkageMicrostrain": sh * 1e6 if abs(sh) < 0.01 else sh,
                }
            )
    return result(
        summary={
            "finalCreepPhi": rows[-1]["creepPhi"],
            "finalShrinkageMicrostrain": rows[-1]["shrinkageMicrostrain"],
        },
        tables=[
            table(
                "Concrete creep & shrinkage schedule",
                [
                    ("ageDays", "Age", "days"),
                    ("creepPhi", "Creep φ"),
                    ("shrinkageMicrostrain", "Shrinkage", "με"),
                ],
                rows,
            )
        ],
        notes=["Evaluated via saengine.fem.concrete_time under active code pack."],
    )


@feature(
    "femServiceability.storeyDriftRatio",
    "Storey Drift Ratio",
    part="fem",
    fields=[],
    requires_project=True,
)
def storey_drift_ratio(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute inter-storey drift ratio per level from 08 FEM/model.results and flag governing value."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    rows = []
    peak = 0.0
    gov = "-"
    for c in resp.get("cases", []):
        for lv in c.get("levels", []):
            dr = max(abs(float(lv.get("driftX", 0.0))), abs(float(lv.get("driftY", 0.0))))
            if dr > peak:
                peak = dr
                gov = f"{c.get('label')} @ {lv.get('name')}"
            rows.append(
                {
                    "case": str(c.get("label", "")),
                    "level": str(lv.get("name", "")),
                    "driftRatio": dr,
                }
            )
    if not rows:
        raise FeatureInputError("No storey drift results found in 08 FEM/model.results.")
    return result(
        summary={"peakDriftRatio": peak, "governingLocation": gov},
        tables=[
            table(
                "Storey drift ratios",
                [("case", "Case"), ("level", "Storey"), ("driftRatio", "Drift Ratio")],
                rows[:40],
            )
        ],
        notes=["Highlights the maximum inter-storey drift ratio across all solved cases."],
    )


@feature(
    "femServiceability.interStoreyDrift",
    "Inter-Storey Drift",
    part="fem",
    fields=[text("caseFilter", "Case filter", "")],
    requires_project=True,
)
def inter_storey_drift(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report relative horizontal displacement δ_i - δ_{i-1} [mm] between consecutive floors."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    filt = values["caseFilter"].strip().lower()
    rows = []
    for c in resp.get("cases", []):
        if filt and filt not in str(c.get("label", "")).lower():
            continue
        levels = c.get("levels", [])
        for i in range(1, len(levels)):
            prev, curr = levels[i - 1], levels[i]
            rel_x = float(curr.get("maxUxMm", 0.0)) - float(prev.get("maxUxMm", 0.0))
            rel_y = float(curr.get("maxUyMm", 0.0)) - float(prev.get("maxUyMm", 0.0))
            rows.append(
                {
                    "case": str(c.get("label", "")),
                    "storey": str(curr.get("name", "")),
                    "deltaXMm": rel_x,
                    "deltaYMm": rel_y,
                }
            )
    if not rows:
        raise FeatureInputError("No inter-storey drift results found in 08 FEM/model.results.")
    return result(
        summary={"storeysEvaluated": len(rows)},
        tables=[
            table(
                "Relative inter-storey displacements",
                [
                    ("case", "Case"),
                    ("storey", "Storey"),
                    ("deltaXMm", "ΔX", "mm"),
                    ("deltaYMm", "ΔY", "mm"),
                ],
                rows[:40],
            )
        ],
        notes=["Relative floor-to-floor drift Δ_i = u_i - u_{i-1}."],
    )


@feature(
    "femServiceability.swayCheck",
    "Sway Check",
    part="fem",
    fields=[],
    requires_project=True,
)
def sway_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assess global roof sway sensitivity and code serviceability limits."""
    out_dir, model_path = require_results(ctx)
    settings = load_settings(ctx)
    with in_force(ctx.root):
        sway = serviceability.sway_basis()
        lim, basis = serviceability.storey_drift_limit(0.6)
    resp = story_response.story_response(out_dir, model_path)
    cases = resp.get("cases", [])
    max_roof = max(
        (
            max(
                abs(float((c.get("levels") or [{}])[-1].get("maxUxMm", 0.0))),
                abs(float((c.get("levels") or [{}])[-1].get("maxUyMm", 0.0))),
            )
            for c in cases
        ),
        default=0.0,
    )
    rows = [
        {"parameter": "Sway limit basis", "value": sway[2] if sway else "H/400 - H/500"},
        {"parameter": "Peak roof sway [mm]", "value": f"{max_roof:.2f}"},
        {"parameter": "Service drift limit", "value": f"{lim:g} ({basis})"},
    ]
    return result(
        summary={
            "maxRoofSwayMm": max_roof,
            "serviceDriftLimit": lim,
            "group": str(getattr(settings.seismic, "system", "rcSmf")),
        },
        tables=[
            table(
                "Global sway sensitivity check",
                [("parameter", "Criterion"), ("value", "Value")],
                rows,
            )
        ],
        notes=["Evaluated using saengine.fem.serviceability and solved roof displacements."],
    )


@feature(
    "femServiceability.horizontalDisplacement",
    "Horizontal Displacement",
    part="fem",
    fields=[],
    requires_project=True,
)
def horizontal_displacement(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List absolute lateral displacement Ux, Uy [mm] at every floor level."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    rows = []
    for c in resp.get("cases", [])[:8]:
        for lv in c.get("levels", []):
            rows.append(
                {
                    "case": str(c.get("label", "")),
                    "level": str(lv.get("name", "")),
                    "elevM": float(lv.get("z", 0.0)),
                    "uxMm": float(lv.get("maxUxMm", 0.0)),
                    "uyMm": float(lv.get("maxUyMm", 0.0)),
                }
            )
    if not rows:
        raise FeatureInputError("Run the analysis first.")
    return result(
        summary={"rows": len(rows)},
        tables=[
            table(
                "Absolute floor lateral displacements",
                [
                    ("case", "Case"),
                    ("level", "Level"),
                    ("elevM", "Elev", "m"),
                    ("uxMm", "Ux", "mm"),
                    ("uyMm", "Uy", "mm"),
                ],
                rows[:45],
            )
        ],
        notes=["Peak absolute floor translations from 08 FEM/model.results."],
    )


@feature(
    "femServiceability.windDrift",
    "Wind Drift",
    part="fem",
    fields=[
        number("limitDenominator", "Wind sway denominator H / N", 500.0, min=100.0, max=1000.0)
    ],
    requires_project=True,
)
def wind_drift(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check serviceability wind-load drift against H/N criterion."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    w_cases = [c for c in resp.get("cases", []) if str(c.get("label", "")).upper().startswith("W")]
    if not w_cases:
        raise FeatureInputError("No wind analysis results found in 08 FEM/model.results.")
    allow = 1.0 / values["limitDenominator"]
    rows = []
    worst = 0.0
    for c in w_cases:
        for lv in c.get("levels", []):
            dr = max(abs(float(lv.get("driftX", 0.0))), abs(float(lv.get("driftY", 0.0))))
            worst = max(worst, dr)
            rows.append(
                {
                    "case": str(c.get("label", "")),
                    "level": str(lv.get("name", "")),
                    "windDrift": dr,
                    "ok": dr <= allow,
                }
            )
    return result(
        summary={"maxWindDrift": worst, "allowable": allow, "passes": worst <= allow},
        tables=[
            table(
                "Wind serviceability drift check",
                [("case", "Case"), ("level", "Level"), ("windDrift", "Drift"), ("ok", "OK")],
                rows[:40],
            )
        ],
        notes=[f"Limit = 1 / {values['limitDenominator']:.0f}."],
    )


@feature(
    "femServiceability.supportSettlement",
    "Support Settlement",
    part="fem",
    fields=[checkbox("includeThermal", "Include thermal case T", False)],
    requires_project=False,
)
def support_settlement(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List code load combinations including differential support settlement ST."""
    with in_force(ctx.root):
        cl = settlement.clause()
        combos = settlement.strength_combinations_with_st(thermal=values["includeThermal"])
    rows = [
        {"combo": name, "factors": ", ".join(f"{v:g}{k}" for k, v in fac.items())}
        for name, fac in combos
    ]
    return result(
        summary={"clause": cl, "combinationCount": len(rows)},
        tables=[
            table(
                "Differential settlement load combinations",
                [("combo", "Combination"), ("factors", "Factors")],
                rows,
            )
        ],
        notes=["Evaluated via saengine.fem.settlement."],
    )


@feature(
    "femServiceability.rotationCheck",
    "Rotation Check",
    part="fem",
    fields=[number("limitRad", "Allowable bearing rotation limit", 0.005, unit="rad", min=0.0005)],
    requires_project=True,
)
def rotation_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check support joint rotations Rx, Ry [rad] against bearing rotation capacity."""
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    target = next(
        (
            e
            for e in idx.get("results", [])
            if any(t["id"] == "displacements" for t in e.get("tables", []))
        ),
        None,
    )
    if target is None:
        raise FeatureInputError(
            "No nodal displacement/rotation tables found in 08 FEM/model.results."
        )
    tbl = result_tables.result_table(out_dir, model_path, target["key"], "displacements")
    cols = [c["key"] for c in tbl.get("columns", [])]
    rxi = cols.index("Rx") if "Rx" in cols else 4
    ryi = cols.index("Ry") if "Ry" in cols else 5
    lim = values["limitRad"]
    rows = []
    worst = 0.0
    for r in tbl.get("rows", [])[:40]:
        rot = max(abs(float(r[rxi])), abs(float(r[ryi])))
        worst = max(worst, rot)
        rows.append({"node": str(r[0]), "maxRotRad": rot, "ok": rot <= lim})
    return result(
        summary={"maxRotationRad": worst, "limitRad": lim, "passes": worst <= lim},
        tables=[
            table(
                "Support/joint rotation check",
                [("node", "Node"), ("maxRotRad", "Max |θ|", "rad"), ("ok", "OK")],
                rows,
            )
        ],
        notes=["Compares maximum flexural nodal rotations against bearing rotation tolerance."],
    )


@feature(
    "femServiceability.baseUplift",
    "Base Uplift",
    part="fem",
    fields=[],
    requires_project=True,
)
def base_uplift(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detect support nodes experiencing net vertical tension (uplift Rz < 0) in service/strength combinations."""
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    rx_cases = [
        e
        for e in idx.get("results", [])
        if any(t["id"] == "reactions" for t in e.get("tables", []))
    ]
    if not rx_cases:
        raise FeatureInputError("No support reaction tables found in 08 FEM/model.results.")
    uplift_rows = []
    for e in rx_cases[:10]:
        tbl = result_tables.result_table(out_dir, model_path, e["key"], "reactions")
        cols = [c["key"] for c in tbl.get("columns", [])]
        fzi = cols.index("Fz") if "Fz" in cols else 3
        for r in tbl.get("rows", []):
            fz = float(r[fzi])
            if fz < -0.5:
                uplift_rows.append({"case": str(e["label"]), "support": str(r[0]), "fzKn": fz})
    return result(
        summary={"casesChecked": min(len(rx_cases), 10), "upliftDetections": len(uplift_rows)},
        tables=[
            table(
                "Detected base support uplift (tension)",
                [("case", "Case"), ("support", "Support"), ("fzKn", "Fz", "kN")],
                uplift_rows[:40] or [{"case": "All checked", "support": "None", "fzKn": 0.0}],
            )
        ],
        notes=["Negative vertical reaction Fz indicates net uplift tension at the support."],
    )


@feature(
    "femServiceability.settlementInfluence",
    "Settlement Influence",
    part="fem",
    fields=[
        number("spanM", "Frame bay span L", 6.0, unit="m", min=1.0),
        number("eiKnm2", "Beam flexural rigidity EI", 25000.0, unit="kN·m²", min=100.0),
        number("deltaMm", "Differential support settlement Δ", 15.0, unit="mm", min=0.1),
    ],
    requires_project=False,
)
def settlement_influence(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute fixed-end moment 6EIΔ/L² and shear 12EIΔ/L³ induced by differential settlement."""
    d_m = values["deltaMm"] / 1000.0
    L = values["spanM"]
    ei = values["eiKnm2"]
    m_ind = 6.0 * ei * d_m / L**2
    v_ind = 12.0 * ei * d_m / L**3
    rows = [
        {
            "spanM": L,
            "settlementMm": values["deltaMm"],
            "inducedMomentKnm": m_ind,
            "inducedShearKn": v_ind,
        }
    ]
    return result(
        summary={"inducedMomentKnm": m_ind, "inducedShearKn": v_ind},
        tables=[
            table(
                "Differential settlement induced member forces",
                [
                    ("spanM", "Span", "m"),
                    ("settlementMm", "Δ", "mm"),
                    ("inducedMomentKnm", "M = 6EIΔ/L²", "kN·m"),
                    ("inducedShearKn", "V = 12EIΔ/L³", "kN"),
                ],
                rows,
            )
        ],
        notes=[
            "Stiff short-span beams experience sharply higher induced moments from differential settlement."
        ],
    )


@feature(
    "femServiceability.limitCheckTable",
    "Limit Check Table",
    part="fem",
    fields=[],
    requires_project=True,
)
def limit_check_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile storey drift, sway, and serviceability demands against allowable limits."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    with in_force(ctx.root):
        lim, basis = serviceability.storey_drift_limit(0.6)
    rows = []
    for c in resp.get("cases", []):
        peak_dr = max(
            (
                max(abs(float(lv.get("driftX", 0.0))), abs(float(lv.get("driftY", 0.0))))
                for lv in c.get("levels", [])
            ),
            default=0.0,
        )
        rows.append(
            {
                "check": f"Drift ({c.get('label')})",
                "demand": peak_dr,
                "limit": lim,
                "ratio": peak_dr / lim,
                "ok": peak_dr <= lim,
            }
        )
    if not rows:
        raise FeatureInputError("Run the analysis first.")
    return result(
        summary={"checks": len(rows), "basis": basis, "allPass": all(r["ok"] for r in rows)},
        tables=[
            table(
                "Serviceability limit check summary",
                [
                    ("check", "Check"),
                    ("demand", "Demand"),
                    ("limit", "Limit"),
                    ("ratio", "Ratio"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=[f"Allowable service drift basis: {basis}."],
    )


@feature(
    "femServiceability.serviceCombination",
    "Service Combination",
    part="fem",
    fields=[],
    requires_project=False,
)
def service_combination(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List serviceability load combinations from the active code pack."""
    present = {"D", "SD", "L", "Lr", "WX", "WY"}
    with in_force(ctx.root):
        combos = combinations.service_combinations(present)
    rows = [
        {"name": n, "factors": ", ".join(f"{v:g}{k}" for k, v in f.items())}
        for n, f in combination_pairs(combos)
    ]
    return result(
        summary={"serviceCombinations": len(rows)},
        tables=[
            table(
                "Serviceability (SLS) load combinations",
                [("name", "Combination"), ("factors", "Factors")],
                rows,
            )
        ],
        notes=["Used for deflection, crack width, foundation bearing, and drift checks."],
    )


@feature(
    "femServiceability.longTermFactors",
    "Long-Term Factors",
    part="fem",
    fields=[number("months", "Sustained load duration", 60.0, unit="months", min=1.0)],
    requires_project=False,
)
def long_term_factors(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate time-dependent sustained deflection factor ξ(t) across loading durations."""
    curve = [(3.0, 1.0), (6.0, 1.2), (12.0, 1.4), (60.0, 2.0)]
    m = values["months"]
    xi = 1.0 if m <= 3 else (2.0 if m >= 60 else 1.0 + 1.0 * ((m - 3.0) / 57.0) ** 0.5)
    rows = [{"months": mo, "xi": x} for mo, x in curve] + [{"months": m, "xi": xi}]
    return result(
        summary={"durationMonths": m, "xiFactor": xi},
        tables=[
            table(
                "Long-term deflection duration factor ξ",
                [("months", "Duration", "months"), ("xi", "ξ")],
                rows,
            )
        ],
        notes=["Standard 5-year (60+ month) asymptotic factor ξ = 2.0."],
    )


@feature(
    "femServiceability.acceptanceReview",
    "Acceptance Review",
    part="fem",
    fields=[
        text("reviewer", "Reviewer initials / name", "Lead Structural Engineer"),
        number("driftLimit", "Allowable inter-storey drift ratio", 0.005, min=0.001, max=0.05),
        select(
            "decision",
            "Disposition",
            [
                ("Accepted", "Accepted"),
                ("Conditional", "Conditional"),
                ("Revise", "Revise Required"),
            ],
        ),
    ],
    requires_project=True,
)
def acceptance_review(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify story drift ratios against limit and log serviceability QA sign-off."""
    import json
    from datetime import datetime

    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    cases = resp.get("cases", [])
    peak_drift = 0.0
    for c in cases:
        for st_row in c.get("storeys", []):
            peak_drift = max(
                peak_drift,
                abs(float(st_row.get("driftX", 0.0) or 0.0)),
                abs(float(st_row.get("driftY", 0.0) or 0.0)),
                abs(float(st_row.get("drift", 0.0) or 0.0)),
            )
    within_limit = peak_drift <= float(values["driftLimit"])
    row = {
        "reviewer": values["reviewer"].strip() or "Reviewer",
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "casesReviewed": len(cases),
        "peakDrift": round(peak_drift, 5),
        "driftLimit": float(values["driftLimit"]),
        "withinLimit": within_limit,
        "decision": values["decision"],
    }
    export_fem_file(ctx, "serviceability-acceptance.json", json.dumps(row, indent=2) + "\n")
    path = export_fem_file(
        ctx,
        "serviceability-acceptance.md",
        f"# Serviceability Acceptance\n\n- Reviewer: {row['reviewer']}\n- Date: {row['date']}\n- Cases: {row['casesReviewed']}\n- Peak Drift: {row['peakDrift']:.5f} (limit {row['driftLimit']:.5f}, pass={within_limit})\n- Decision: {row['decision']}\n",
    )
    return result(
        summary={
            "reviewer": row["reviewer"],
            "casesReviewed": row["casesReviewed"],
            "peakDrift": row["peakDrift"],
            "withinLimit": within_limit,
            "logPath": str(path),
        },
        tables=[
            table(
                "Serviceability QA sign-off",
                [
                    ("reviewer", "Reviewer"),
                    ("casesReviewed", "Cases"),
                    ("peakDrift", "Peak Drift"),
                    ("withinLimit", "Pass"),
                    ("decision", "Decision"),
                ],
                [row],
            )
        ],
        notes=[
            f"Acceptance verified against drift <= {row['driftLimit']:.4f} and written to {path}."
        ],
    )


@feature(
    "femServiceability.serviceabilityReport",
    "Serviceability Report",
    part="fem",
    fields=[],
    requires_project=True,
)
def serviceability_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export formatted Markdown serviceability summary report from 08 FEM/model.results."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    lines = [
        "# FEM Serviceability Verification Report",
        "",
        "| Case | Peak Ux [mm] | Peak Uy [mm] | Peak Drift |",
        "|---|---|---|---|",
    ]
    rows = []
    for c in resp.get("cases", []):
        lvs = c.get("levels", [])
        ux = max((abs(float(lv.get("maxUxMm", 0.0))) for lv in lvs), default=0.0)
        uy = max((abs(float(lv.get("maxUyMm", 0.0))) for lv in lvs), default=0.0)
        dr = max(
            (
                max(abs(float(lv.get("driftX", 0.0))), abs(float(lv.get("driftY", 0.0))))
                for lv in lvs
            ),
            default=0.0,
        )
        rows.append({"case": str(c.get("label", "")), "uxMm": ux, "uyMm": uy, "drift": dr})
        lines.append(f"| {c.get('label')} | {ux:.2f} | {uy:.2f} | {dr:.5f} |")
    path = export_fem_file(ctx, "serviceability-report.md", "\n".join(lines) + "\n")
    return result(
        summary={"casesReported": len(rows), "reportPath": str(path)},
        tables=[
            table(
                "Serviceability summary",
                [
                    ("case", "Case"),
                    ("uxMm", "Peak Ux", "mm"),
                    ("uyMm", "Peak Uy", "mm"),
                    ("drift", "Peak Drift"),
                ],
                rows,
            )
        ],
        notes=[f"Report written to {path}"],
    )

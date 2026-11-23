"""Project Settings - Hazard: Return Periods & Importance tab: return periods, exceedance, gust duration, extremes."""

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
    "settingsHazardReturn.returnPeriod",
    "Return Period",
    part="settings",
    fields=[
        number(
            "returnPeriodYears",
            "Design seismic return period TR",
            475.0,
            unit="yr",
            min=10.0,
            max=10000.0,
        ),
        number("designLifeYears", "Building design life TL", 50.0, unit="yr", min=1.0, max=200.0),
    ],
    requires_project=False,
)
def return_period(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute annual and design-life exceedance probabilities from seismic return period."""
    tr, tl = values["returnPeriodYears"], values["designLifeYears"]
    p_ann = 1.0 - math.exp(-1.0 / tr)
    p_life = 1.0 - math.exp(-tl / tr)
    return result(
        summary={
            "returnPeriodYears": tr,
            "annualExceedancePct": p_ann * 100.0,
            "lifetimeExceedancePct": p_life * 100.0,
        },
        tables=[
            table(
                "Seismic return period statistics",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Return period TR [yr]", "value": tr},
                    {"metric": "Annual exceedance [%]", "value": p_ann * 100.0},
                    {"metric": f"{tl:g}-yr exceedance [%]", "value": p_life * 100.0},
                ],
            )
        ],
        notes=["Poisson exceedance model P = 1 - exp(-TL / TR)."],
    )


@feature(
    "settingsHazardReturn.annualProbability",
    "Annual Probability",
    part="settings",
    fields=[
        number(
            "annualProbPct",
            "Target annual exceedance probability",
            0.21,
            unit="%",
            min=0.001,
            max=50.0,
        ),
    ],
    requires_project=False,
)
def annual_probability(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert annual exceedance probability into equivalent return period TR."""
    p = values["annualProbPct"] / 100.0
    tr = -1.0 / math.log(1.0 - p)
    return result(
        summary={"annualProbabilityPct": values["annualProbPct"], "impliedReturnPeriodYears": tr},
        tables=[
            table(
                "Probability-to-return conversion",
                [("annualPct", "Annual P", "%"), ("returnYears", "Return period TR", "yr")],
                [{"annualPct": values["annualProbPct"], "returnYears": tr}],
            )
        ],
        notes=["TR = -1 / ln(1 - P_annual)."],
    )


@feature(
    "settingsHazardReturn.exposureTime",
    "Exposure Time",
    part="settings",
    fields=[
        number("exposureYears", "Service exposure time TL", 100.0, unit="yr", min=1.0, max=250.0),
        number(
            "targetExceedancePct",
            "Allowable lifetime exceedance",
            10.0,
            unit="%",
            min=0.5,
            max=50.0,
        ),
    ],
    requires_project=False,
)
def exposure_time(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Solve required hazard return period TR for a given exposure duration and risk target."""
    p = values["targetExceedancePct"] / 100.0
    tr = -values["exposureYears"] / math.log(1.0 - p)
    return result(
        summary={
            "exposureYears": values["exposureYears"],
            "targetExceedancePct": values["targetExceedancePct"],
            "requiredReturnPeriodYears": tr,
        },
        tables=[
            table(
                "Exposure-based return period",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Exposure duration [yr]", "value": values["exposureYears"]},
                    {"metric": "Required TR [yr]", "value": tr},
                ],
            )
        ],
        notes=["Longer design working lives require longer hazard return periods for fixed risk."],
    )


@feature(
    "settingsHazardReturn.applySeismic",
    "Apply Seismic",
    part="settings",
    fields=[
        number("targetReturnYears", "Target seismic return period", 475.0, unit="yr", min=50.0),
        number("baselineReturnYears", "Pack baseline return period", 475.0, unit="yr", min=50.0),
    ],
    requires_project=False,
)
def apply_seismic(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute hazard scaling ratio between target seismic return period and baseline pack."""
    # Power-law hazard curve approximation: PGA ~ (TR / TR0)^0.38
    scale = (values["targetReturnYears"] / values["baselineReturnYears"]) ** 0.38
    return result(
        summary={
            "targetReturnYears": values["targetReturnYears"],
            "impliedHazardMultiplier": scale,
        },
        tables=[
            table(
                "Seismic return scaling",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Target TR [yr]", "value": values["targetReturnYears"]},
                    {"item": "Hazard ratio (TR/TR0)^0.38", "value": scale},
                ],
            )
        ],
        notes=["Power-law hazard slope ~ 0.38 is representative of moderate seismicity regions."],
    )


@feature(
    "settingsHazardReturn.windReturn",
    "Wind Return",
    part="settings",
    fields=[
        number(
            "returnYears", "Target wind return period TR", 100.0, unit="yr", min=1.0, max=2000.0
        ),
        number("baseSpeedMPerS", "50-yr basic wind speed V50", 50.0, unit="m/s", min=15.0),
    ],
    requires_project=False,
)
def wind_return(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Scale 50-year basic wind speed to an arbitrary return period using Gumbel probability."""
    tr = values["returnYears"]
    p = 1.0 - math.exp(-1.0 / tr)
    k_tr = (1.0 - 0.138 * math.log(-math.log(1.0 - p))) / (1.0 - 0.138 * math.log(-math.log(0.98)))
    v_tr = values["baseSpeedMPerS"] * math.sqrt(max(0.1, k_tr))
    return result(
        summary={
            "returnPeriodYears": tr,
            "speedMultiplier": v_tr / values["baseSpeedMPerS"],
            "scaledWindMPerS": v_tr,
        },
        tables=[
            table(
                "Wind return period conversion",
                [
                    ("returnYears", "Return", "yr"),
                    ("speedMPerS", "Wind V", "m/s"),
                    ("pressureFactor", "q / q50"),
                ],
                [
                    {
                        "returnYears": tr,
                        "speedMPerS": v_tr,
                        "pressureFactor": (v_tr / values["baseSpeedMPerS"]) ** 2,
                    }
                ],
            )
        ],
        notes=["Gumbel extreme wind distribution conversion relative to 50-year mean recurrence."],
    )


@feature(
    "settingsHazardReturn.gustDuration",
    "Gust Duration",
    part="settings",
    fields=[
        number("gust3sMPerS", "3-second gust wind speed", 60.0, unit="m/s", min=10.0),
        select(
            "targetDuration",
            "Target averaging duration",
            [
                ("10min", "10-minute mean (Durst ≈ 0.698)"),
                ("1hr", "1-hour mean (Durst ≈ 0.654)"),
                ("60s", "60-second sustained (Durst ≈ 0.806)"),
            ],
            "10min",
        ),
    ],
    requires_project=False,
)
def gust_duration(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert 3-second gust wind speed to longer averaging durations via Durst curve."""
    durst = {"10min": 0.698, "1hr": 0.654, "60s": 0.806}[values["targetDuration"]]
    v_out = values["gust3sMPerS"] * durst
    return result(
        summary={
            "gust3sMPerS": values["gust3sMPerS"],
            "durstFactor": durst,
            "convertedSpeedMPerS": v_out,
        },
        tables=[
            table(
                "Durst averaging duration conversion",
                [
                    ("duration", "Averaging window"),
                    ("factor", "Ratio to 3s"),
                    ("speedMPerS", "Speed", "m/s"),
                ],
                [{"duration": values["targetDuration"], "factor": durst, "speedMPerS": v_out}],
            )
        ],
        notes=["Durst open-terrain standard gust-duration ratios."],
    )


@feature(
    "settingsHazardReturn.windDirection",
    "Wind Direction",
    part="settings",
    fields=[
        select(
            "mode",
            "Directional wind treatment",
            [
                ("omni", "Omnidirectional envelope (Kd = 1.0)"),
                ("directional", "Directional sectors (pack Kd)"),
            ],
            "directional",
        ),
    ],
    requires_project=False,
)
def wind_direction(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare omnidirectional vs directional wind sector treatment using active pack Kd."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        kd = float(getattr(safe_table(pack, "wind"), "directionality", 0.85) or 0.85)
    eff_kd = 1.0 if values["mode"] == "omni" else kd
    return result(
        summary={"mode": values["mode"], "effectiveKd": eff_kd},
        tables=[
            table(
                "Wind directional mode",
                [("mode", "Mode"), ("kd", "Effective Kd")],
                [{"mode": values["mode"], "kd": eff_kd}],
            )
        ],
        notes=["Omnidirectional treatment applies Kd = 1.0 across all wind azimuths."],
    )


@feature(
    "settingsHazardReturn.applyWind",
    "Apply Wind",
    part="settings",
    fields=[
        number("returnYears", "Adopted wind return period", 50.0, unit="yr", min=10.0),
    ],
    requires_project=False,
)
def apply_wind(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise active wind climate return settings and derived project wind speed."""
    st = load_settings(ctx)
    from saengine.features.settings_common import project_derived

    d = project_derived(ctx, st)
    return result(
        summary={
            "returnPeriodYears": values["returnYears"],
            "derivedWindMPerS": float(d.get("windSpeed") or 0.0),
            "windImportance": float(d.get("windImportance") or 1.0),
        },
        tables=[
            table(
                "Applied wind climate settings",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Return period [yr]", "value": str(values["returnYears"])},
                    {"item": "Derived basic wind [m/s]", "value": str(d.get("windSpeed") or "-")},
                    {"item": "Wind importance I", "value": str(d.get("windImportance"))},
                ],
            )
        ],
        notes=["Wind importance factor adjusts return-period risk by occupancy category."],
    )


@feature(
    "settingsHazardReturn.snowReturn",
    "Snow Return",
    part="settings",
    fields=[
        number("snow50Kpa", "50-yr ground snow load sk50", 1.5, unit="kN/m²", min=0.1),
        number("targetReturnYears", "Target return period", 100.0, unit="yr", min=10.0),
    ],
    requires_project=False,
)
def snow_return(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Scale ground snow load between return periods using log-normal / Gumbel ratio."""
    # Standard Gumbel snow conversion (COV ~ 0.30)
    k = 1.0 + 0.23 * math.log(values["targetReturnYears"] / 50.0)
    s_tr = values["snow50Kpa"] * max(0.5, k)
    return result(
        summary={"snow50Kpa": values["snow50Kpa"], "scaleFactor": k, "scaledSnowKpa": s_tr},
        tables=[
            table(
                "Snow return period scaling",
                [("returnYears", "Return", "yr"), ("loadKpa", "Ground snow", "kN/m²")],
                [
                    {"returnYears": 50.0, "loadKpa": values["snow50Kpa"]},
                    {"returnYears": values["targetReturnYears"], "loadKpa": s_tr},
                ],
            )
        ],
        notes=["Logarithmic return-period scaling assuming 30% annual snow COV."],
    )


@feature(
    "settingsHazardReturn.rainReturn",
    "Rain Return",
    part="settings",
    fields=[
        number("rain100MmHr", "100-yr 1-hr rainfall intensity", 85.0, unit="mm/hr", min=5.0),
        number("targetReturnYears", "Target storm return period", 50.0, unit="yr", min=2.0),
    ],
    requires_project=False,
)
def rain_return(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Scale design storm rainfall intensity by return period ratio."""
    ratio = (values["targetReturnYears"] / 100.0) ** 0.16
    i_tr = values["rain100MmHr"] * ratio
    return result(
        summary={"targetReturnYears": values["targetReturnYears"], "intensityMmPerHr": i_tr},
        tables=[
            table(
                "Rainfall return scaling",
                [("returnYears", "Return", "yr"), ("mmPerHr", "Intensity", "mm/hr")],
                [
                    {"returnYears": 100.0, "mmPerHr": values["rain100MmHr"]},
                    {"returnYears": values["targetReturnYears"], "mmPerHr": i_tr},
                ],
            )
        ],
        notes=["IDF power-law return scaling exponent 0.16."],
    )


@feature(
    "settingsHazardReturn.floodReturn",
    "Flood Return",
    part="settings",
    fields=[],
    requires_project=False,
)
def flood_return(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Retrieve flood and storm-surge return periods by occupancy category from active pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        fl = safe_table(pack, "flood")
        rps = dict(getattr(fl, "returnPeriod", None) or {})
    rows = [
        {"category": k, "returnYears": v, "active": k == st.occupancy.category}
        for k, v in rps.items()
    ]
    return result(
        summary={
            "projectCategory": st.occupancy.category,
            "floodReturnYears": int(rps.get(st.occupancy.category, 100)),
        },
        tables=[
            table(
                "Flood return periods by occupancy",
                [
                    ("category", "Occupancy"),
                    ("returnYears", "Return period", "yr"),
                    ("active", "Project"),
                ],
                rows or [{"category": st.occupancy.category, "returnYears": 100, "active": True}],
            )
        ],
        notes=["Read from active code pack flood.returnPeriod."],
    )


@feature(
    "settingsHazardReturn.applyOther",
    "Apply Other",
    part="settings",
    fields=[
        number("snowReturnYears", "Snow return period", 50.0, unit="yr", min=10.0),
        number("rainReturnYears", "Rain return period", 100.0, unit="yr", min=10.0),
        number("floodReturnYears", "Flood return period", 100.0, unit="yr", min=10.0),
    ],
    requires_project=False,
)
def apply_other(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Consolidate return period targets for snow, rain, and flood actions."""
    rows = [
        {"action": "Snow", "returnYears": values["snowReturnYears"]},
        {"action": "Rain ponding", "returnYears": values["rainReturnYears"]},
        {"action": "Flood & surge", "returnYears": values["floodReturnYears"]},
    ]
    return result(
        summary={
            "snowReturnYears": values["snowReturnYears"],
            "rainReturnYears": values["rainReturnYears"],
            "floodReturnYears": values["floodReturnYears"],
        },
        tables=[
            table(
                "Environmental action return periods",
                [("action", "Action"), ("returnYears", "Return", "yr")],
                rows,
            )
        ],
        notes=["Applied to environmental load derivations."],
    )


@feature(
    "settingsHazardReturn.riskCategory",
    "Risk Category",
    part="settings",
    fields=[],
    requires_project=False,
)
def risk_category(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report project occupancy / risk category and its active pack description."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        occ = safe_table(pack, "occupancyCategories")
        cat = occ.categories.get(st.occupancy.category) if occ else None
    return result(
        summary={
            "riskCategory": st.occupancy.category,
            "seismicImportance": float(cat.seismicImportance) if cat else 1.0,
        },
        tables=[
            table(
                "Project risk category",
                [("category", "Category"), ("description", "Description")],
                [
                    {
                        "category": st.occupancy.category,
                        "description": cat.description if cat else "-",
                    }
                ],
            )
        ],
        notes=["Governs seismic, wind, snow, and flood importance multipliers."],
    )


@feature(
    "settingsHazardReturn.importanceFactor",
    "Importance Factor",
    part="settings",
    fields=[],
    requires_project=False,
)
def hr_importance_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate seismic and wind importance factors across all occupancy categories in active pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        occ = safe_table(pack, "occupancyCategories")
        cats = getattr(occ, "categories", None) or {}
    rows = [
        {
            "category": k,
            "seismicI": v.seismicImportance,
            "windI": v.windImportance,
            "selected": k == st.occupancy.category,
        }
        for k, v in cats.items()
    ]
    return result(
        summary={"selectedCategory": st.occupancy.category, "categoryCount": len(rows)},
        tables=[
            table(
                "Importance factors by category",
                [
                    ("category", "Cat"),
                    ("seismicI", "Seismic I"),
                    ("windI", "Wind I"),
                    ("selected", "Active"),
                ],
                rows,
            )
        ],
        notes=["Read from active code pack occupancyCategories."],
    )


@feature(
    "settingsHazardReturn.occupancyClass",
    "Occupancy Class",
    part="settings",
    fields=[],
    requires_project=False,
)
def hr_occupancy_class(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Review building occupancy function and cyclone-shelter non-reduction flag."""
    st = load_settings(ctx)
    return result(
        summary={
            "use": st.occupancy.use,
            "category": st.occupancy.category,
            "cycloneShelter": st.occupancy.cycloneShelter,
        },
        tables=[
            table(
                "Occupancy classification",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Building use", "value": st.occupancy.use},
                    {"field": "Risk category", "value": st.occupancy.category},
                    {"field": "Cyclone shelter", "value": str(st.occupancy.cycloneShelter)},
                ],
            )
        ],
        notes=["Cyclone shelter buildings prohibit live load reduction."],
    )


@feature(
    "settingsHazardReturn.structureCategory",
    "Structure Category",
    part="settings",
    fields=[
        select(
            "facilityTier",
            "Facility resilience tier",
            [
                ("standard", "Standard occupancy"),
                ("highOccupancy", "Substantial hazard / assembly"),
                ("essential", "Essential / post-disaster facility"),
            ],
            "standard",
        ),
    ],
    requires_project=False,
)
def structure_category(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map facility resilience tier to target seismic drift limit and importance category."""
    tier_map = {
        "standard": ("II", 0.020),
        "highOccupancy": ("III", 0.015),
        "essential": ("IV", 0.010),
    }
    cat, drift = tier_map[values["facilityTier"]]
    return result(
        summary={
            "facilityTier": values["facilityTier"],
            "recommendedCategory": cat,
            "typicalDriftLimit": drift,
        },
        tables=[
            table(
                "Facility resilience mapping",
                [("tier", "Tier"), ("category", "Occupancy Cat"), ("drift", "Drift limit")],
                [{"tier": values["facilityTier"], "category": cat, "drift": drift}],
            )
        ],
        notes=[
            "Essential facilities require stricter interstorey drift control to preserve operational continuity."
        ],
    )


@feature(
    "settingsHazardReturn.frequentReturn",
    "Frequent Return",
    part="settings",
    fields=[
        number(
            "frequentYears",
            "Frequent serviceability return period",
            10.0,
            unit="yr",
            min=1.0,
            max=50.0,
        ),
    ],
    requires_project=False,
)
def frequent_return(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute frequent SLS wind/seismic reduction factor relative to 50-year ULS wind."""
    # Pressure ratio (V_T / V_50)^2 for frequent 10-yr wind ~ 0.72
    v_ratio = math.sqrt(
        (1.0 - 0.14 * math.log(-math.log(1.0 - 1.0 / values["frequentYears"]))) / 1.54
    )
    return result(
        summary={
            "frequentReturnYears": values["frequentYears"],
            "speedRatio": v_ratio,
            "pressureRatio": v_ratio**2,
        },
        tables=[
            table(
                "Frequent SLS return scaling",
                [
                    ("returnYears", "Return", "yr"),
                    ("speedRatio", "V / V50"),
                    ("pressureRatio", "q / q50"),
                ],
                [
                    {
                        "returnYears": values["frequentYears"],
                        "speedRatio": v_ratio,
                        "pressureRatio": v_ratio**2,
                    }
                ],
            )
        ],
        notes=[
            "Frequent return periods govern human comfort acceleration and reversible cracking."
        ],
    )


@feature(
    "settingsHazardReturn.occasionalReturn",
    "Occasional Return",
    part="settings",
    fields=[
        number(
            "occasionalYears",
            "Operational / immediate-occupancy return period",
            72.0,
            unit="yr",
            min=20.0,
            max=200.0,
        ),
    ],
    requires_project=False,
)
def occasional_return(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute operational-level seismic scaling ratio relative to 475-yr DBE."""
    scale = (values["occasionalYears"] / 475.0) ** 0.38
    return result(
        summary={"occasionalReturnYears": values["occasionalYears"], "hazardRatioVs475": scale},
        tables=[
            table(
                "Operational earthquake scaling",
                [("returnYears", "Return", "yr"), ("ratio", "Sa / Sa,475")],
                [{"returnYears": values["occasionalYears"], "ratio": scale}],
            )
        ],
        notes=[
            "72-year event (~50% probability in 50 years) represents frequent operational shaking."
        ],
    )


@feature(
    "settingsHazardReturn.driftReturn",
    "Drift Return",
    part="settings",
    fields=[
        number(
            "windDriftReturnYears",
            "Wind drift check return period",
            10.0,
            unit="yr",
            min=1.0,
            max=100.0,
        ),
        number(
            "seismicDriftReturnYears",
            "Seismic drift return period",
            475.0,
            unit="yr",
            min=50.0,
            max=2500.0,
        ),
    ],
    requires_project=False,
)
def drift_return(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define return periods for serviceability wind and inelastic seismic storey drift checks."""
    return result(
        summary={
            "windDriftReturnYears": values["windDriftReturnYears"],
            "seismicDriftReturnYears": values["seismicDriftReturnYears"],
        },
        tables=[
            table(
                "Drift check return periods",
                [("action", "Action"), ("returnYears", "Return period", "yr")],
                [
                    {
                        "action": "Wind serviceability drift",
                        "returnYears": values["windDriftReturnYears"],
                    },
                    {
                        "action": "Seismic inelastic drift",
                        "returnYears": values["seismicDriftReturnYears"],
                    },
                ],
            )
        ],
        notes=[
            "Wind drift uses unfactored serviceability wind; seismic drift uses amplified elastic drift."
        ],
    )


@feature(
    "settingsHazardReturn.serviceFactor",
    "Service Factor",
    part="settings",
    fields=[
        number(
            "windServiceFactor", "Wind serviceability combination factor", 0.70, min=0.3, max=1.0
        ),
    ],
    requires_project=False,
)
def service_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare wind serviceability factor with active pack service combination row."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        comb = safe_table(pack, "combinations")
        serv_w = [
            r.factors.get("W") for r in (getattr(comb, "service", None) or []) if r.factors.get("W")
        ]
    pack_w = float(serv_w[0]) if serv_w else 0.70
    return result(
        summary={"packWindServiceFactor": pack_w, "targetFactor": values["windServiceFactor"]},
        tables=[
            table(
                "Serviceability wind factor",
                [("source", "Source"), ("factor", "W factor")],
                [
                    {"source": "Active code pack", "factor": pack_w},
                    {"source": "Input target", "factor": values["windServiceFactor"]},
                ],
            )
        ],
        notes=["Sourced from active pack combinations.service."],
    )


@feature(
    "settingsHazardReturn.maximumConsidered",
    "Maximum Considered",
    part="settings",
    fields=[
        number("mceReturnYears", "MCE return period", 2475.0, unit="yr", min=475.0, max=10000.0),
        number("dbeScale", "DBE / MCE design ratio (typically 2/3)", 0.6667, min=0.5, max=1.0),
    ],
    requires_project=False,
)
def maximum_considered(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute 50-year exceedance probability of MCE event and DBE/MCE ratio."""
    p50 = 1.0 - math.exp(-50.0 / values["mceReturnYears"])
    return result(
        summary={
            "mceReturnYears": values["mceReturnYears"],
            "exceedance50YrPct": p50 * 100.0,
            "dbeToMceRatio": values["dbeScale"],
        },
        tables=[
            table(
                "Maximum Considered Earthquake",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "MCE return period [yr]", "value": values["mceReturnYears"]},
                    {"metric": "50-yr exceedance [%]", "value": p50 * 100.0},
                    {"metric": "DBE / MCE ratio", "value": values["dbeScale"]},
                ],
            )
        ],
        notes=["2475-year return corresponds to 2% probability of exceedance in 50 years."],
    )


@feature(
    "settingsHazardReturn.rareEvent",
    "Rare Event",
    part="settings",
    fields=[
        number(
            "rareReturnYears",
            "Rare earthquake / collapse return period",
            2475.0,
            unit="yr",
            min=475.0,
        ),
        number("rareRatio", "Rare / design spectrum ratio", 1.5, min=1.0, max=3.0),
    ],
    requires_project=False,
)
def rare_event(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate rare-earthquake elasto-plastic drift scaling ratio."""
    return result(
        summary={
            "rareReturnYears": values["rareReturnYears"],
            "rareToDesignRatio": values["rareRatio"],
        },
        tables=[
            table(
                "Rare event parameters",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Return period [yr]", "value": values["rareReturnYears"]},
                    {"item": "Spectrum multiplier", "value": values["rareRatio"]},
                ],
            )
        ],
        notes=["Governs collapse-prevention drift and pushover target displacement checks."],
    )


@feature(
    "settingsHazardReturn.envelopeMultiplier",
    "Envelope Multiplier",
    part="settings",
    fields=[
        number("baseHazard", "Nominal hazard ordinate", 0.28),
        number("envMultiplier", "Statistical extreme envelope multiplier", 1.15, min=1.0, max=2.0),
    ],
    requires_project=False,
)
def envelope_multiplier(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply statistical upper-bound multiplier to extreme environmental hazard scenarios."""
    scaled = values["baseHazard"] * values["envMultiplier"]
    return result(
        summary={
            "baseHazard": values["baseHazard"],
            "multiplier": values["envMultiplier"],
            "envelopedHazard": scaled,
        },
        tables=[
            table(
                "Extreme envelope scaling",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Baseline hazard", "value": values["baseHazard"]},
                    {"item": "Multiplier", "value": values["envMultiplier"]},
                    {"item": "Enveloped hazard", "value": scaled},
                ],
            )
        ],
        notes=["Accounts for epistemic hazard uncertainty in critical infrastructure."],
    )


@feature(
    "settingsHazardReturn.extremeScaling",
    "Extreme Scaling",
    part="settings",
    fields=[
        number("scaleFactor", "Response spectrum scale factor", 1.25, min=0.5, max=3.0),
        number("saAtT1G", "Baseline Sa(T1)", 0.32, unit="g", min=0.01),
    ],
    requires_project=False,
)
def extreme_scaling(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Scale baseline spectral acceleration for extreme displacement/extension checks."""
    scaled = values["saAtT1G"] * values["scaleFactor"]
    return result(
        summary={
            "baselineSaG": values["saAtT1G"],
            "scaleFactor": values["scaleFactor"],
            "scaledSaG": scaled,
        },
        tables=[
            table(
                "Extreme spectral scaling",
                [("item", "Item"), ("g", "Sa", "g")],
                [
                    {"item": "Baseline Sa(T1)", "g": values["saAtT1G"]},
                    {"item": "Scaled extreme Sa(T1)", "g": scaled},
                ],
            )
        ],
        notes=["Used for base-isolation moat clearance and seismic joint gap verification."],
    )

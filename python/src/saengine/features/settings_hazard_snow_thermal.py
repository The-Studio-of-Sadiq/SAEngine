"""Project Settings - Hazard: Snow, Rain, Thermal & Ice tab: snow, rain, thermal, ice, microclimate, ponding."""

from __future__ import annotations

import math
from typing import Any

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
from saengine.fem import snow_load, thermal
from saengine.report.clauses import in_force


@feature(
    "settingsHazardSnowThermal.groundLoad",
    "Ground Load",
    part="settings",
    fields=[
        number(
            "groundSnowKpa",
            "Ground snow load sk / pg (0 = from settings)",
            0.0,
            unit="kN/m²",
            min=0.0,
        ),
    ],
    requires_project=False,
)
def ground_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report ground snow load from project settings or location table."""
    st = load_settings(ctx)
    val = values["groundSnowKpa"] or float(st.site.snow.groundLoad or 0.0)
    return result(
        summary={"groundSnowKnPerM2": val, "location": st.site.location},
        tables=[
            table(
                "Ground snow load",
                [("source", "Source"), ("kpa", "sk / pg", "kN/m²")],
                [{"source": "Effective site ground snow", "kpa": val}],
            )
        ],
        notes=["Stored in site.snow.groundLoad."],
    )


@feature(
    "settingsHazardSnowThermal.roofShape",
    "Roof Shape",
    part="settings",
    fields=[
        number("pitchDeg", "Roof slope angle α", 20.0, unit="°", min=0.0, max=75.0),
        checkbox("slippery", "Slippery metal/glass roof surface", False),
    ],
    requires_project=False,
)
def roof_shape(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute snow roof shape / slope reduction factor across pitch angles."""
    st = load_settings(ctx)
    pitch = values["pitchDeg"]
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        snow_tbl = safe_table(pack, "snow")
        if snow_tbl and getattr(snow_tbl, "shape", None):
            mu = snow_load.shape_coefficient(pitch, snow_tbl.shape)
        elif snow_tbl and getattr(snow_tbl, "slope", None):
            mu = snow_load.slope_factor(snow_tbl, 1.0, pitch, values["slippery"])
        else:
            start = 15.0 if values["slippery"] else 30.0
            mu = (
                1.0
                if pitch <= start
                else (0.0 if pitch >= 70.0 else (70.0 - pitch) / (70.0 - start))
            )
    return result(
        summary={"pitchDeg": pitch, "shapeOrSlopeFactor": mu},
        tables=[
            table(
                "Roof snow shape factor",
                [("pitchDeg", "Pitch", "°"), ("factor", "Factor μ / Cs")],
                [{"pitchDeg": pitch, "factor": mu}],
            )
        ],
        notes=["Steeper roofs shed snow above the threshold pitch angle."],
    )


@feature(
    "settingsHazardSnowThermal.snowDrift",
    "Snow Drift",
    part="settings",
    fields=[
        number("parapetHeightM", "Parapet height hp", 0.9, unit="m", min=0.1),
        number("groundSnowKpa", "Ground snow load", 1.5, unit="kN/m²", min=0.1),
    ],
    requires_project=False,
)
def snow_drift(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate snow drift surcharge against roof parapets."""
    gamma_s = 2.0
    hd = min(values["parapetHeightM"], values["groundSnowKpa"] / gamma_s * 1.5)
    pd = hd * gamma_s
    ls = min(15.0, max(5.0, 2.0 * values["parapetHeightM"]))
    return result(
        summary={"driftHeightM": hd, "driftLengthM": ls, "driftSurchargeKpa": pd},
        tables=[
            table(
                "Parapet snow drift",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Drift height hd [m]", "value": hd},
                    {"metric": "Drift width ls [m]", "value": ls},
                    {"metric": "Peak drift surcharge [kN/m²]", "value": pd},
                ],
            )
        ],
        notes=["Triangular drift load tapers from peak at parapet to zero at distance ls."],
    )


@feature(
    "settingsHazardSnowThermal.applySnow",
    "Apply Snow",
    part="settings",
    fields=[
        number("groundSnowKpa", "Ground snow sk", 1.2, unit="kN/m²", min=0.0),
        number("ce", "Exposure factor Ce", 1.0, min=0.7, max=1.3),
        number("ct", "Thermal factor Ct", 1.0, min=0.8, max=1.3),
    ],
    requires_project=False,
)
def apply_snow(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute flat-roof design snow load pf = 0.7 Ce Ct Is pg."""
    pf = 0.7 * values["ce"] * values["ct"] * values["groundSnowKpa"]
    return result(
        summary={"groundSnowKpa": values["groundSnowKpa"], "flatRoofSnowKpa": pf},
        tables=[
            table(
                "Applied roof snow summary",
                [("term", "Term"), ("kpa", "Load", "kN/m²")],
                [
                    {"term": "Ground snow", "kpa": values["groundSnowKpa"]},
                    {"term": "Flat roof design snow", "kpa": pf},
                ],
            )
        ],
        notes=["Flat roof conversion factor 0.7 (0.8 for shape-coefficient packs)."],
    )


@feature(
    "settingsHazardSnowThermal.rainIntensity",
    "Rain Intensity",
    part="settings",
    fields=[
        number("intensityMmHr", "Design 100-yr rainfall intensity i", 100.0, unit="mm/hr", min=5.0),
        number("roofAreaM2", "Drained roof catchment area A", 600.0, unit="m²", min=10.0),
    ],
    requires_project=False,
)
def rain_intensity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute peak roof rainwater runoff flow Q = i · A / 3.6e6 [m³/s]."""
    q_ls = (values["intensityMmHr"] * values["roofAreaM2"]) / 3600.0
    return result(
        summary={"intensityMmPerHr": values["intensityMmHr"], "runoffLPerS": q_ls},
        tables=[
            table(
                "Roof rainfall runoff",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Rainfall intensity [mm/hr]", "value": values["intensityMmHr"]},
                    {"item": "Peak roof runoff [L/s]", "value": q_ls},
                ],
            )
        ],
        notes=["100% roof impermeability assumed (runoff coefficient C = 1.0)."],
    )


@feature(
    "settingsHazardSnowThermal.rainDuration",
    "Rain Duration",
    part="settings",
    fields=[
        number("durationMin", "Design storm duration", 60.0, unit="min", min=5.0, max=1440.0),
        number("intensity60MmHr", "60-minute reference intensity", 90.0, unit="mm/hr", min=5.0),
    ],
    requires_project=False,
)
def rain_duration(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Adjust rainfall intensity for storm duration using standard IDF exponent."""
    i_t = values["intensity60MmHr"] * (60.0 / values["durationMin"]) ** 0.55
    depth_mm = i_t * (values["durationMin"] / 60.0)
    return result(
        summary={
            "durationMin": values["durationMin"],
            "adjustedIntensityMmHr": i_t,
            "totalDepthMm": depth_mm,
        },
        tables=[
            table(
                "Storm duration IDF scaling",
                [
                    ("durationMin", "Duration", "min"),
                    ("intensityMmHr", "Intensity", "mm/hr"),
                    ("depthMm", "Total depth", "mm"),
                ],
                [{"durationMin": values["durationMin"], "intensityMmHr": i_t, "depthMm": depth_mm}],
            )
        ],
        notes=["Short 5-15 min durations govern scupper peak flow; 60-min governs detention."],
    )


@feature(
    "settingsHazardSnowThermal.roofDrainage",
    "Roof Drainage",
    part="settings",
    fields=[
        number("roofAreaM2", "Roof area", 800.0, unit="m²", min=20.0),
        number("drainCapacityLPerS", "Single primary drain capacity", 12.0, unit="L/s", min=1.0),
        number("runoffLPerS", "Design peak runoff", 28.0, unit="L/s", min=1.0),
    ],
    requires_project=False,
)
def roof_drainage(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Determine minimum number of primary roof drains and redundant secondary scuppers."""
    n_pri = max(2, math.ceil(values["runoffLPerS"] / values["drainCapacityLPerS"]))
    return result(
        summary={
            "primaryDrains": n_pri,
            "secondaryScuppers": n_pri,
            "areaPerDrainM2": values["roofAreaM2"] / n_pri,
        },
        tables=[
            table(
                "Roof drainage layout",
                [("system", "System"), ("count", "Count")],
                [
                    {"system": "Primary roof drains", "count": n_pri},
                    {"system": "Secondary overflow scuppers", "count": n_pri},
                ],
            )
        ],
        notes=["Minimum 2 independent roof drains required per roof bay."],
    )


@feature(
    "settingsHazardSnowThermal.applyRain",
    "Apply Rain",
    part="settings",
    fields=[
        number("waterDepthMm", "Design impounded depth ds + dh", 90.0, unit="mm", min=0.0),
    ],
    requires_project=False,
)
def apply_rain(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute applied roof rain load R = 9.81 × depth [m]."""
    r_kpa = 9.81 * (values["waterDepthMm"] / 1000.0)
    return result(
        summary={"waterDepthMm": values["waterDepthMm"], "rainLoadKpa": r_kpa},
        tables=[
            table(
                "Applied rain load",
                [("depthMm", "Water depth", "mm"), ("rainKpa", "Rain load R", "kN/m²")],
                [{"depthMm": values["waterDepthMm"], "rainKpa": r_kpa}],
            )
        ],
        notes=["Applied to flat/low-slope roofs with parapet ponding potential."],
    )


@feature(
    "settingsHazardSnowThermal.temperatureRange",
    "Temperature Range",
    part="settings",
    fields=[
        number("tMinC", "Minimum design shade air temperature", 5.0, unit="°C"),
        number("tMaxC", "Maximum design shade air temperature", 42.0, unit="°C"),
        number("tInstallC", "Construction tie-in temperature T0", 22.0, unit="°C"),
    ],
    requires_project=False,
)
def temperature_range(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute positive expansion (+ΔTu) and negative contraction (-ΔTu) thermal load cases."""
    dt_pos = values["tMaxC"] - values["tInstallC"]
    dt_neg = values["tMinC"] - values["tInstallC"]
    return result(
        summary={
            "expansionDeltaTC": dt_pos,
            "contractionDeltaTC": dt_neg,
            "totalSwingC": values["tMaxC"] - values["tMinC"],
        },
        tables=[
            table(
                "Design uniform temperature range",
                [("case", "Case"), ("deltaC", "ΔTu", "°C")],
                [
                    {"case": "Summer expansion", "deltaC": dt_pos},
                    {"case": "Winter contraction", "deltaC": dt_neg},
                ],
            )
        ],
        notes=["Relative to construction closure temperature T0."],
    )


@feature(
    "settingsHazardSnowThermal.temperatureGradient",
    "Temperature Gradient",
    part="settings",
    fields=[
        number("topTempC", "Sun-exposed top face temperature", 52.0, unit="°C"),
        number("bottomTempC", "Interior soffit temperature", 24.0, unit="°C"),
        number("slabDepthMm", "Roof slab thickness", 200.0, unit="mm", min=80.0),
    ],
    requires_project=False,
)
def temperature_gradient(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute thermal curvature κT = α ΔTg / h for sun-exposed roof slabs."""
    dtg = values["topTempC"] - values["bottomTempC"]
    alpha = thermal.DEFAULT_ALPHA["concrete"]
    kappa = (alpha * dtg) / (values["slabDepthMm"] / 1000.0)
    return result(
        summary={"deltaTgC": dtg, "thermalCurvaturePerM": kappa},
        tables=[
            table(
                "Through-depth thermal gradient",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Gradient ΔTg [°C]", "value": dtg},
                    {"item": "Free thermal curvature [1/m]", "value": kappa},
                ],
            )
        ],
        notes=[
            "Top hotter than bottom induces hogging restraint moments in continuous roof slabs."
        ],
    )


@feature(
    "settingsHazardSnowThermal.thermalMovement",
    "Thermal Movement",
    part="settings",
    fields=[
        number("lengthM", "Expansion length from neutral point", 30.0, unit="m", min=1.0),
        number("deltaTC", "Design temperature change ΔT", 25.0, unit="°C", min=0.0),
        select("material", "Material", [("concrete", "Concrete"), ("steel", "Steel")], "concrete"),
    ],
    requires_project=False,
)
def thermal_movement(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute unrestrained thermal displacement ΔL = α L ΔT for sliding bearings and joints."""
    alpha = thermal.DEFAULT_ALPHA[values["material"]]
    dl_mm = alpha * (values["lengthM"] * 1000.0) * values["deltaTC"]
    return result(
        summary={"material": values["material"], "movementMm": dl_mm},
        tables=[
            table(
                "Unrestrained thermal movement",
                [("lengthM", "Length", "m"), ("deltaTC", "ΔT", "°C"), ("movementMm", "ΔL", "mm")],
                [{"lengthM": values["lengthM"], "deltaTC": values["deltaTC"], "movementMm": dl_mm}],
            )
        ],
        notes=["Joint widths and slotted bolt holes must accommodate ±ΔL."],
    )


@feature(
    "settingsHazardSnowThermal.applyThermal",
    "Apply Thermal",
    part="settings",
    fields=[],
    requires_project=False,
)
def apply_thermal(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect active thermal analysis configuration in project settings."""
    th = load_settings(ctx).analysis.thermal
    return result(
        summary={
            "thermalEnabled": th.enabled,
            "uniformC": th.uniform,
            "gradientC": th.gradient,
            "scope": th.scope,
        },
        tables=[
            table(
                "Project thermal analysis settings",
                [("field", "Setting"), ("value", "Value")],
                [
                    {"field": "Enabled", "value": str(th.enabled)},
                    {"field": "Uniform ΔTu [°C]", "value": str(th.uniform)},
                    {"field": "Gradient ΔTg [°C]", "value": str(th.gradient)},
                    {"field": "Scope", "value": th.scope},
                ],
            )
        ],
        notes=["Read from analysis.thermal in 02 Project Settings."],
    )


@feature(
    "settingsHazardSnowThermal.freezingRain",
    "Freezing Rain",
    part="settings",
    fields=[
        number(
            "iceThicknessMm", "Radial glaze ice thickness ti", 15.0, unit="mm", min=0.0, max=75.0
        ),
        number(
            "memberDiameterMm", "Exposed circular member diameter D", 100.0, unit="mm", min=10.0
        ),
    ],
    requires_project=False,
)
def freezing_rain(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute glaze ice cross-sectional area and linear weight on exposed circular members."""
    ti = values["iceThicknessMm"] / 1000.0
    dc = values["memberDiameterMm"] / 1000.0
    a_ice = math.pi * ti * (dc + ti)
    w_kn_m = a_ice * 9.0  # 9.0 kN/m3 glaze ice
    return result(
        summary={
            "iceThicknessMm": values["iceThicknessMm"],
            "iceAreaMm2": a_ice * 1e6,
            "iceWeightKnPerM": w_kn_m,
        },
        tables=[
            table(
                "Glaze ice accretion",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Ice area [mm²]", "value": a_ice * 1e6},
                    {"item": "Ice weight [kN/m]", "value": w_kn_m},
                ],
            )
        ],
        notes=["Uniform radial glaze ice thickness assuming 9.0 kN/m³ ice density."],
    )


@feature(
    "settingsHazardSnowThermal.radialIce",
    "Radial Ice",
    part="settings",
    fields=[
        number("baseIceMm", "Reference 10 m radial ice thickness t0", 12.5, unit="mm", min=0.0),
        number("heightM", "Structure elevation z", 45.0, unit="m", min=1.0),
    ],
    requires_project=False,
)
def radial_ice(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Scale radial ice thickness with height above ground via fz = (z / 10)^0.10."""
    fz = min(1.4, max(0.8, (values["heightM"] / 10.0) ** 0.10))
    td = values["baseIceMm"] * fz
    return result(
        summary={"heightFactor": fz, "designIceMm": td},
        tables=[
            table(
                "Height-adjusted radial ice",
                [("heightM", "Height", "m"), ("fz", "Factor"), ("iceMm", "Design ti", "mm")],
                [{"heightM": values["heightM"], "fz": fz, "iceMm": td}],
            )
        ],
        notes=["Ice accretion increases mildly with elevation above ground."],
    )


@feature(
    "settingsHazardSnowThermal.combinedWindIce",
    "Combined Wind Ice",
    part="settings",
    fields=[
        number("memberWidthMm", "Bare member width b", 120.0, unit="mm", min=10.0),
        number("iceThicknessMm", "Design radial ice ti", 15.0, unit="mm", min=0.0),
        number("concurrentWindMPerS", "Concurrent wind-on-ice speed Vi", 22.0, unit="m/s", min=5.0),
        number("cf", "Force coefficient Cf", 1.2, min=0.5, max=2.2),
    ],
    requires_project=False,
)
def combined_wind_ice(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute wind-on-ice drag force accounting for ice-enlarged projected width."""
    b_ice_m = (values["memberWidthMm"] + 2.0 * values["iceThicknessMm"]) / 1000.0
    qi_kpa = 0.5 * 1.225 * values["concurrentWindMPerS"] ** 2 / 1000.0
    fw_kn_m = values["cf"] * qi_kpa * b_ice_m
    return result(
        summary={
            "icedWidthMm": b_ice_m * 1000.0,
            "iceWindPressureKpa": qi_kpa,
            "windForceKnPerM": fw_kn_m,
        },
        tables=[
            table(
                "Wind-on-ice line force",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Iced projected width [mm]", "value": b_ice_m * 1000.0},
                    {"item": "Concurrent pressure qi [kPa]", "value": qi_kpa},
                    {"item": "Wind force [kN/m]", "value": fw_kn_m},
                ],
            )
        ],
        notes=["Ice increases projected wind area by 2 ti while concurrent wind speed is reduced."],
    )


@feature(
    "settingsHazardSnowThermal.iceDensity",
    "Ice Density",
    part="settings",
    fields=[
        select(
            "iceType",
            "Atmospheric ice form",
            [
                ("glaze", "Glaze ice (900 kg/m³)"),
                ("hardRime", "Hard rime (600 kg/m³)"),
                ("softRime", "Soft rime (300 kg/m³)"),
            ],
            "glaze",
        ),
    ],
    requires_project=False,
)
def ice_density(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report mass density and unit weight for glaze and rime atmospheric ice."""
    rho = {"glaze": 900.0, "hardRime": 600.0, "softRime": 300.0}[values["iceType"]]
    uw = rho * 9.80665e-3
    return result(
        summary={"iceType": values["iceType"], "densityKgPerM3": rho, "unitWeightKnPerM3": uw},
        tables=[
            table(
                "Atmospheric ice density",
                [("type", "Form"), ("kgM3", "Density", "kg/m³"), ("knM3", "Unit weight", "kN/m³")],
                [{"type": values["iceType"], "kgM3": rho, "knM3": uw}],
            )
        ],
        notes=["Freezing rain forms high-density glaze ice (~900 kg/m³)."],
    )


@feature(
    "settingsHazardSnowThermal.urbanThermal",
    "Urban Thermal",
    part="settings",
    fields=[
        number("ruralTempC", "Baseline rural air temperature", 36.0, unit="°C"),
        number("urbanHeatIslandC", "Urban heat island offset", 3.5, unit="Δ°C", min=0.0, max=10.0),
    ],
    requires_project=False,
)
def urban_thermal(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Adjust peak design ambient temperature for urban heat-island microclimate."""
    t_eff = values["ruralTempC"] + values["urbanHeatIslandC"]
    return result(
        summary={
            "ruralTempC": values["ruralTempC"],
            "urbanOffsetC": values["urbanHeatIslandC"],
            "effectiveMaxTempC": t_eff,
        },
        tables=[
            table(
                "Urban thermal adjustment",
                [("item", "Item"), ("c", "Temperature", "°C")],
                [
                    {"item": "Rural baseline", "c": values["ruralTempC"]},
                    {"item": "Effective urban peak", "c": t_eff},
                ],
            )
        ],
        notes=["Dense urban cores elevate peak summer ambient temperatures by 2-5 °C."],
    )


@feature(
    "settingsHazardSnowThermal.elevationFactor",
    "Elevation Factor",
    part="settings",
    fields=[
        number("altitudeM", "Site altitude A", 650.0, unit="m", min=0.0, max=4000.0),
        number("baseSnowKpa", "Sea-level regional snow s0", 1.0, unit="kN/m²", min=0.1),
    ],
    requires_project=False,
)
def elevation_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Adjust ground snow load for site elevation above mean sea level."""
    alt = values["altitudeM"]
    fac = 1.0 if alt <= 300.0 else 1.0 + 0.0008 * (alt - 300.0)
    s_alt = values["baseSnowKpa"] * fac
    return result(
        summary={"altitudeM": alt, "elevationMultiplier": fac, "adjustedSnowKpa": s_alt},
        tables=[
            table(
                "Altitude snow adjustment",
                [
                    ("altitudeM", "Altitude", "m"),
                    ("factor", "Factor"),
                    ("snowKpa", "Ground snow", "kN/m²"),
                ],
                [{"altitudeM": alt, "factor": fac, "snowKpa": s_alt}],
            )
        ],
        notes=["Higher altitudes accumulate heavier ground snowpack."],
    )


@feature(
    "settingsHazardSnowThermal.exposureFactor",
    "Exposure Factor",
    part="settings",
    fields=[
        select(
            "terrain",
            "Roof wind exposure",
            [
                ("windswept", "Windswept / open (Ce = 0.8)"),
                ("normal", "Normal / suburban (Ce = 1.0)"),
                ("sheltered", "Sheltered / wooded (Ce = 1.2)"),
            ],
            "normal",
        ),
    ],
    requires_project=False,
)
def exposure_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select snow exposure coefficient Ce based on wind sheltering around the roof."""
    ce = {"windswept": 0.8, "normal": 1.0, "sheltered": 1.2}[values["terrain"]]
    return result(
        summary={"terrain": values["terrain"], "ceFactor": ce},
        tables=[
            table(
                "Snow exposure factor Ce",
                [("terrain", "Terrain"), ("ce", "Ce")],
                [{"terrain": values["terrain"], "ce": ce}],
            )
        ],
        notes=["Windswept roofs experience scouring; sheltered roofs retain snow."],
    )


@feature(
    "settingsHazardSnowThermal.solarRadiation",
    "Solar Radiation",
    part="settings",
    fields=[
        number("absorptance", "Surface solar absorptance αs", 0.65, min=0.2, max=0.95),
        number("irradianceWPerM2", "Peak solar irradiance I", 900.0, unit="W/m²", min=100.0),
        number("hConvWPerM2K", "Surface convective coeff hc", 20.0, unit="W/(m²·K)", min=5.0),
    ],
    requires_project=False,
)
def solar_radiation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute sol-air surface temperature rise ΔT_sol = αs I / hc for exposed roof decks."""
    dt_sol = (values["absorptance"] * values["irradianceWPerM2"]) / values["hConvWPerM2K"]
    return result(
        summary={"solAirRiseC": dt_sol},
        tables=[
            table(
                "Solar heating temperature rise",
                [("item", "Item"), ("value", "Value")],
                [
                    {
                        "item": "Absorbed flux [W/m²]",
                        "value": values["absorptance"] * values["irradianceWPerM2"],
                    },
                    {"item": "Sol-air rise ΔT [°C]", "value": dt_sol},
                ],
            )
        ],
        notes=["Dark waterproofing membranes (αs ~ 0.85) experience higher top-surface gradients."],
    )


@feature(
    "settingsHazardSnowThermal.deflectionPonding",
    "Deflection Ponding",
    part="settings",
    fields=[
        number("initialDeflectionMm", "Dead-load midspan camber/sag δ0", 12.0, unit="mm", min=0.0),
        number("flexibilityIndex", "Framing ponding flexibility Cp", 0.12, min=0.0, max=0.6),
    ],
    requires_project=False,
)
def deflection_ponding(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute progressive rainwater ponding amplification factor 1 / (1 - Cp)."""
    cp = values["flexibilityIndex"]
    amp = 1.0 / (1.0 - cp) if cp < 0.99 else 99.0
    final_mm = values["initialDeflectionMm"] * amp
    return result(
        summary={"pondingAmplification": amp, "finalDeflectionMm": final_mm, "stable": cp <= 0.25},
        tables=[
            table(
                "Progressive ponding amplification",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Flexibility index Cp", "value": cp},
                    {"metric": "Amplification 1/(1-Cp)", "value": amp},
                    {"metric": "Amplified sag [mm]", "value": final_mm},
                ],
            )
        ],
        notes=["Roofs must be cambered or sloped >= 2% to drain positively."],
    )


@feature(
    "settingsHazardSnowThermal.overflowScupper",
    "Overflow Scupper",
    part="settings",
    fields=[
        number("scupperWidthMm", "Rectangular scupper width b", 300.0, unit="mm", min=100.0),
        number("headMm", "Hydraulic head above scupper sill h", 75.0, unit="mm", min=10.0),
    ],
    requires_project=False,
)
def overflow_scupper(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate rectangular weir overflow discharge Q = 1.84 b h^1.5 through parapet scuppers."""
    b_m = values["scupperWidthMm"] / 1000.0
    h_m = values["headMm"] / 1000.0
    q_m3s = 1.84 * b_m * (h_m**1.5)
    return result(
        summary={"scupperFlowLPerS": q_m3s * 1000.0, "headMm": values["headMm"]},
        tables=[
            table(
                "Parapet scupper weir capacity",
                [
                    ("widthMm", "Width", "mm"),
                    ("headMm", "Head", "mm"),
                    ("flowLPerS", "Capacity", "L/s"),
                ],
                [
                    {
                        "widthMm": values["scupperWidthMm"],
                        "headMm": values["headMm"],
                        "flowLPerS": q_m3s * 1000.0,
                    }
                ],
            )
        ],
        notes=["Broad-crested rectangular weir formula Q = 1.84 b h^1.5 [m³/s]."],
    )


@feature(
    "settingsHazardSnowThermal.drainClogging",
    "Drain Clogging",
    part="settings",
    fields=[
        number("scupperSillMm", "Secondary scupper sill height ds", 50.0, unit="mm", min=10.0),
        number("hydraulicHeadMm", "Flow head dh at full runoff", 55.0, unit="mm", min=5.0),
    ],
    requires_project=False,
)
def drain_clogging(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Simulate primary drain blockage and compute total roof ponding depth and load."""
    tot_mm = values["scupperSillMm"] + values["hydraulicHeadMm"]
    load_kpa = 9.81 * (tot_mm / 1000.0)
    return result(
        summary={"totalWaterMm": tot_mm, "pondingLoadKpa": load_kpa},
        tables=[
            table(
                "Blocked-drain ponding depth",
                [("component", "Component"), ("mm", "Head", "mm")],
                [
                    {"component": "Static depth ds", "mm": values["scupperSillMm"]},
                    {"component": "Hydraulic head dh", "mm": values["hydraulicHeadMm"]},
                    {"component": "Total ponding depth", "mm": tot_mm},
                ],
            )
        ],
        notes=["Assumes all primary interior drains are 100% clogged by debris."],
    )


@feature(
    "settingsHazardSnowThermal.waterHead",
    "Water Head",
    part="settings",
    fields=[
        number("depthMm", "Impounded water depth", 100.0, unit="mm", min=0.0),
    ],
    requires_project=False,
)
def water_head(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert flat-roof static water head depth into uniform hydrostatic pressure."""
    p_kpa = 9.81 * (values["depthMm"] / 1000.0)
    return result(
        summary={"waterHeadMm": values["depthMm"], "pressureKpa": p_kpa},
        tables=[
            table(
                "Static hydraulic head",
                [("depthMm", "Head", "mm"), ("pressureKpa", "Pressure", "kN/m²")],
                [{"depthMm": values["depthMm"], "pressureKpa": p_kpa}],
            )
        ],
        notes=["100 mm of standing water exerts 0.981 kN/m² vertical load."],
    )

"""Project Settings - Seismic & Wind Hazard tab: SDC, R/q factors, site class, wind exposure, snow, thermal, site hazards."""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
from saengine.features import (
    FeatureContext,
    feature,
    number,
    result,
    select,
    table,
)
from saengine.features.settings_common import (
    active_pack,
    effective_site_class,
    load_settings,
    project_derived,
    safe_table,
)
from saengine.fem import loads as fem_loads
from saengine.fem import peak_velocity_pressure, snow_load, thermal, wind_speed_factors
from saengine.library.settings import (
    category_site_class,
    design_category,
    site_specific_warning,
    system_values,
)
from saengine.report.clauses import in_force


@feature(
    "settingsHazard.seismicDesignCategory",
    "Seismic Design Category",
    part="settings",
    fields=[],
    requires_project=False,
)
def seismic_design_category(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Seismic Design Category, system permission, height limit, and detailing requirements."""
    st = load_settings(ctx)
    resolved_st, site_info = effective_site_class(ctx, st)
    with in_force(ctx.root, resolved_st):
        pack = active_pack(ctx, resolved_st)
        soil_flags = list((site_info.get("soil") or {}).get("flags") or [])
        cat_site = category_site_class(resolved_st, site_info["class"], soil_flags)
        sdc_info = design_category(resolved_st, cat_site)
        warn = site_specific_warning(resolved_st, soil_flags, site_info["class"])

    rows = [
        {
            "item": "Effective site class",
            "value": str(sdc_info.get("siteClass") or site_info["class"]),
        },
        {"item": "Seismic zone", "value": str(sdc_info.get("zone") or "-")},
        {"item": "Seismic Design Category", "value": str(sdc_info.get("sdc") or "-")},
        {"item": "Selected system permitted", "value": str(bool(sdc_info.get("permitted", True)))},
        {
            "item": "System height limit [m]",
            "value": str(sdc_info.get("heightLimit") or "No limit"),
        },
        {"item": "Required detailing", "value": str(sdc_info.get("required") or "-")},
    ]
    notes = [
        f"Site class source: {site_info.get('label', 'entered')}. Active pack: {code_context.code_name(pack)}."
    ]
    if warn:
        notes.append(warn)
    return result(
        summary={
            "sdc": str(sdc_info.get("sdc") or "N/A"),
            "siteClass": str(sdc_info.get("siteClass") or site_info["class"]),
            "permitted": bool(sdc_info.get("permitted", True)),
            "heightLimitM": float(sdc_info["heightLimit"]) if sdc_info.get("heightLimit") else 0.0,
        },
        tables=[
            table(
                "Seismic Design Category summary", [("item", "Parameter"), ("value", "Value")], rows
            )
        ],
        notes=notes,
    )


@feature(
    "settingsHazard.behaviourFactor",
    "Behaviour Factor",
    part="settings",
    fields=[],
    requires_project=False,
)
def behaviour_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report R / q, overstrength Ω0, and deflection amplification Cd along X and Y from active pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        sys_vals = system_values(st, pack)
    rows = [
        {
            "axis": axis,
            "primarySystem": ", ".join(data["names"]),
            "R": data["R"],
            "Omega0": data["Omega0"],
            "Cd": data["Cd"],
            "momentFramesOnly": data["momentFramesOnly"],
        }
        for axis, data in sys_vals.items()
    ]
    return result(
        summary={
            "rx": float(sys_vals["X"]["R"]),
            "ry": float(sys_vals["Y"]["R"]),
            "omegaX": float(sys_vals["X"]["Omega0"]),
            "cdX": float(sys_vals["X"]["Cd"]),
        },
        tables=[
            table(
                "Directional seismic system factors",
                [
                    ("axis", "Axis"),
                    ("primarySystem", "System(s)"),
                    ("R", "R / q"),
                    ("Omega0", "Ω0"),
                    ("Cd", "Cd"),
                    ("momentFramesOnly", "Moment frame"),
                ],
                rows,
            )
        ],
        notes=[
            "Combined directional values follow the active pack's seismic.systemCombination rules."
        ],
    )


@feature(
    "settingsHazard.siteClassAssign",
    "Site Class Assign",
    part="settings",
    fields=[],
    requires_project=False,
)
def site_class_assign(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Resolve the governing soil site class from borehole logs or project settings."""
    st = load_settings(ctx)
    _resolved_st, info = effective_site_class(ctx, st)
    soil = info.get("soil") or {}
    rows = [
        {"field": "Configured source", "value": st.site.siteClassSource},
        {"field": "Entered class", "value": info.get("entered", st.site.siteClass)},
        {"field": "Effective class", "value": info["class"]},
        {"field": "Boreholes evaluated", "value": str(soil.get("boreholes", 0))},
        {"field": "Governing borehole", "value": str(soil.get("borehole") or "-")},
    ]
    return result(
        summary={
            "effectiveClass": str(info["class"]),
            "sourceUsed": str(info["source"]),
            "boreholeCount": int(soil.get("boreholes", 0)),
        },
        tables=[table("Site class assignment", [("field", "Field"), ("value", "Value")], rows)],
        notes=[
            str(info.get("note") or "Resolved using saengine.library.settings.resolve_site_class.")
        ],
    )


@feature(
    "settingsHazard.windExposure",
    "Wind Exposure",
    part="settings",
    fields=[
        number("heightM", "Reference height z", 15.0, unit="m", min=1.0, max=400.0),
    ],
    requires_project=False,
)
def wind_exposure(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate active wind exposure categories and roughness parameters at height z."""
    st = load_settings(ctx)
    z = values["heightM"]
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        wind_tbl = safe_table(pack, "wind")
        exps = getattr(wind_tbl, "exposures", None) or {}
        rows = []
        for k, exp in exps.items():
            alpha = getattr(exp, "alpha", None)
            zg = getattr(exp, "zg", None)
            z0 = getattr(exp, "z0", None)
            if getattr(wind_tbl, "method", "") == "peakVelocityPressure" and z0 is not None:
                kz = peak_velocity_pressure.roughness_terms(z, k, wind_tbl)["cr"]
            elif getattr(wind_tbl, "method", "") == "speedFactors":
                kz = wind_speed_factors.height_factor(z, k)
            elif alpha and zg:
                z_eff = max(z, float(getattr(wind_tbl, "kzMinHeight", 4.5) or 4.5))
                kz = float(getattr(wind_tbl, "kzFactor", 2.01) or 2.01) * (z_eff / float(zg)) ** (
                    2.0 / float(alpha)
                )
            else:
                kz = 1.0
            rows.append(
                {
                    "id": k,
                    "description": exp.description,
                    "alphaOrZ0": float(alpha) if alpha else (float(z0) if z0 else 0.0),
                    "factorAtZ": kz,
                    "active": k == st.wind.exposure,
                }
            )
    return result(
        summary={"activeExposure": st.wind.exposure, "heightM": z, "exposureCount": len(rows)},
        tables=[
            table(
                "Wind exposure categories",
                [
                    ("id", "Category"),
                    ("description", "Terrain description"),
                    ("alphaOrZ0", "α or z0"),
                    ("factorAtZ", "Exposure factor at z"),
                    ("active", "Selected"),
                ],
                rows,
            )
        ],
        notes=[
            f"Factors evaluated at z = {z:g} m under {code_context.code_name(pack)} ({getattr(wind_tbl, 'method', 'standard')})."
        ],
    )


@feature(
    "settingsHazard.gustFactor",
    "Gust Factor",
    part="settings",
    fields=[
        number("heightM", "Building height H", 36.0, unit="m", min=3.0),
        number("widthM", "Building width B across wind", 24.0, unit="m", min=2.0),
        number("depthM", "Building depth L along wind", 18.0, unit="m", min=2.0),
        number("frequencyHz", "Fundamental frequency n1", 1.2, unit="Hz", min=0.05, max=20.0),
        number("dampingRatio", "Structural damping ratio β", 0.02, min=0.002, max=0.15),
    ],
    requires_project=False,
)
def gust_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute rigid or flexible dynamic gust-effect factor using the active code pack."""
    st = load_settings(ctx)
    d = project_derived(ctx, st)
    speed = float(d.get("windSpeed") or 50.0)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        wind_tbl = safe_table(pack, "wind")
        g_rigid = float(getattr(wind_tbl, "gust", 0.85) or 0.85)
        n1 = values["frequencyHz"]
        try:
            g_flex = fem_loads.gust_factor(
                values["heightM"],
                values["widthM"],
                values["depthM"],
                st.wind.exposure,
                speed,
                frequency=n1,
                damping=values["dampingRatio"],
            )
        except Exception:  # noqa: BLE001
            g_flex = g_rigid
    is_flex = n1 < 1.0
    g_used = g_flex if is_flex else g_rigid
    rows = [
        {"mode": "Rigid structure (n1 >= 1 Hz)", "gustFactor": g_rigid},
        {"mode": "Flexible / dynamic calculation", "gustFactor": g_flex},
        {"mode": "Governing gust factor", "gustFactor": g_used},
    ]
    return result(
        summary={
            "frequencyHz": n1,
            "flexible": is_flex,
            "rigidGustFactor": g_rigid,
            "dynamicGustFactor": g_flex,
            "governingGustFactor": g_used,
        },
        tables=[
            table(
                "Gust-effect factor comparison",
                [("mode", "Mode"), ("gustFactor", "Gust factor G / Gf")],
                rows,
            )
        ],
        notes=["Evaluates active pack rigid gust factor vs modal frequency dynamic gust response."],
    )


@feature(
    "settingsHazard.terrainCategories",
    "Terrain Categories",
    part="settings",
    fields=[
        number("maxHeightM", "Top height for profile", 60.0, unit="m", min=5.0, max=300.0),
    ],
    requires_project=False,
)
def terrain_categories(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate wind velocity pressure exposure profile across heights for the selected terrain."""
    st = load_settings(ctx)
    hmax = values["maxHeightM"]
    heights = [5.0, 10.0, 15.0, 20.0, 30.0, 45.0, hmax]
    heights = sorted({round(min(z, hmax), 2) for z in heights if z <= hmax + 1e-9})
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        wind_tbl = safe_table(pack, "wind")
        method = getattr(wind_tbl, "method", "powerLaw")
        exp = (getattr(wind_tbl, "exposures", None) or {}).get(st.wind.exposure)
        rows = []
        for z in heights:
            if method == "peakVelocityPressure":
                kz = peak_velocity_pressure.roughness_terms(z, st.wind.exposure, wind_tbl)["cr"]
            elif method == "speedFactors":
                kz = wind_speed_factors.height_factor(z, st.wind.exposure)
            elif exp and getattr(exp, "alpha", None) and getattr(exp, "zg", None):
                z_eff = max(z, float(getattr(wind_tbl, "kzMinHeight", 4.5) or 4.5))
                kz = float(getattr(wind_tbl, "kzFactor", 2.01) or 2.01) * (
                    z_eff / float(exp.zg)
                ) ** (2.0 / float(exp.alpha))
            else:
                kz = 1.0
            rows.append({"heightM": z, "exposure": st.wind.exposure, "kz": kz})
    return result(
        summary={
            "exposure": st.wind.exposure,
            "method": method,
            "topFactor": rows[-1]["kz"] if rows else 1.0,
        },
        tables=[
            table(
                "Terrain exposure height profile",
                [("heightM", "Height z", "m"), ("exposure", "Exposure"), ("kz", "Factor")],
                rows,
            )
        ],
        notes=[f"Computed via {code_context.code_name(pack)} wind exposure method ({method})."],
    )


@feature(
    "settingsHazard.snowLoadMap",
    "Snow Load Map",
    part="settings",
    fields=[
        number(
            "groundSnowKnPerM2",
            "Reference ground snow sk (0 = from location)",
            0.0,
            unit="kN/m²",
            min=0.0,
        ),
        number("altitudeM", "Site altitude A", 250.0, unit="m", min=0.0, max=4000.0),
        number("roofPitchDeg", "Roof pitch θ", 15.0, unit="°", min=0.0, max=75.0),
    ],
    requires_project=False,
)
def snow_load_map(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Derive roof snow load from mapped/altitude ground snow and active pack shape/slope factors."""
    st = load_settings(ctx)
    alt = values["altitudeM"]
    pitch = values["roofPitchDeg"]
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        locs = safe_table(pack, "locations")
        loc = locs.locations.get(st.site.location) if locs else None
        sk = values["groundSnowKnPerM2"] or float(
            getattr(loc, "groundSnow", None) or st.site.snow.groundLoad or 0.5
        )
        snow_tbl = safe_table(pack, "snow")
        if snow_tbl is not None and getattr(snow_tbl, "shape", None):
            mu = snow_load.shape_coefficient(pitch, snow_tbl.shape)
            roof_s = 0.8 * mu * sk
        elif snow_tbl is not None and getattr(snow_tbl, "slope", None):
            cs = snow_load.slope_factor(snow_tbl, 1.0, pitch, False)
            roof_s = 0.7 * cs * sk
        else:
            mu = 0.8 if pitch <= 30.0 else max(0.0, 0.8 * (60.0 - pitch) / 30.0)
            roof_s = mu * sk
            # Elevation correction when altitude > 500 m
            if alt > 500.0:
                roof_s *= 1.0 + 0.0005 * (alt - 500.0)
    rows = [
        {"parameter": "Ground snow sk", "value": sk, "unit": "kN/m²"},
        {"parameter": "Site altitude", "value": alt, "unit": "m"},
        {"parameter": "Roof pitch", "value": pitch, "unit": "°"},
        {"parameter": "Design roof snow load", "value": roof_s, "unit": "kN/m²"},
    ]
    return result(
        summary={"groundSnowKnPerM2": sk, "roofSnowKnPerM2": roof_s, "altitudeM": alt},
        tables=[
            table(
                "Roof snow load derivation",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Uses active code pack snow table when defined, else standard pitched-roof snow reduction."
        ],
    )


@feature(
    "settingsHazard.thermalActions",
    "Thermal Actions",
    part="settings",
    fields=[
        number("deltaTuC", "Uniform temperature change ΔTu", 20.0, unit="°C", min=-60.0, max=60.0),
        number("deltaTgC", "Through-depth gradient ΔTg", 10.0, unit="°C", min=-40.0, max=40.0),
        select(
            "material",
            "Frame material",
            [("concrete", "Concrete"), ("steel", "Structural steel"), ("masonry", "Masonry")],
            "concrete",
        ),
        number("modulusMpa", "Elastic modulus E", 25000.0, unit="MPa", min=1000.0),
    ],
    requires_project=False,
)
def thermal_actions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute free thermal strain and fully restrained axial thermal stress for ΔTu and ΔTg."""
    alpha = thermal.DEFAULT_ALPHA[values["material"]]
    dtu = values["deltaTuC"]
    dtg = values["deltaTgC"]
    e = values["modulusMpa"]
    strain_u = alpha * dtu
    stress_u = e * strain_u
    rows = [
        {"item": "Coefficient of thermal expansion α", "value": alpha * 1e6, "unit": "×10⁻⁶ /°C"},
        {"item": "Free uniform thermal strain εT", "value": strain_u * 1e6, "unit": "με"},
        {"item": "Restrained uniform stress σT", "value": stress_u, "unit": "MPa"},
        {"item": "Through-depth gradient ΔTg", "value": dtg, "unit": "°C"},
    ]
    return result(
        summary={
            "alphaPerC": alpha,
            "freeStrainMicro": strain_u * 1e6,
            "restrainedStressMpa": stress_u,
        },
        tables=[
            table(
                "Thermal action parameters",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Free strain εT = α ΔTu; restrained stress σT = E α ΔTu (saengine.fem.thermal.DEFAULT_ALPHA)."
        ],
    )


@feature(
    "settingsHazard.constructionLoads",
    "Construction Loads",
    part="settings",
    fields=[
        number(
            "windReturnFactor",
            "Temporary construction wind reduction factor",
            0.78,
            min=0.5,
            max=1.0,
        ),
        number("erectionLiveKnPerM2", "Temporary erection live load", 1.5, unit="kN/m²", min=0.2),
        number("materialStackKnPerM2", "Material staging allowance", 2.0, unit="kN/m²", min=0.0),
    ],
    requires_project=False,
)
def construction_loads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate temporary construction wind reduction and staging load defaults."""
    st = load_settings(ctx)
    d = project_derived(ctx, st)
    v_full = float(d.get("windSpeed") or 50.0)
    v_temp = v_full * values["windReturnFactor"]
    p_ratio = (v_temp / v_full) ** 2 if v_full > 0 else 1.0
    total_const_live = values["erectionLiveKnPerM2"] + values["materialStackKnPerM2"]
    rows = [
        {"parameter": "Design wind speed V", "value": v_full, "unit": "m/s"},
        {"parameter": "Temporary construction wind speed", "value": v_temp, "unit": "m/s"},
        {"parameter": "Wind pressure ratio", "value": p_ratio, "unit": "-"},
        {
            "parameter": "Combined staging + erection live",
            "value": total_const_live,
            "unit": "kN/m²",
        },
    ]
    return result(
        summary={
            "constructionWindMPerS": v_temp,
            "pressureRatio": p_ratio,
            "stagingLiveKnPerM2": total_const_live,
        },
        tables=[
            table(
                "Construction stage hazard defaults",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Reduced return-period wind factor scales wind velocity before squaring to pressure."
        ],
    )


@feature(
    "settingsHazard.pgaValue",
    "PGA Value",
    part="settings",
    fields=[
        number(
            "pgaOverrideG",
            "PGA override (0 = use active code pack)",
            0.0,
            unit="g",
            min=0.0,
            max=3.0,
        ),
    ],
    requires_project=False,
)
def pga_value(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare site design PGA from the active code pack with any project override."""
    st = load_settings(ctx)
    d = project_derived(ctx, st)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        seis = safe_table(pack, "seismic")
        pga_factor = float(getattr(seis, "pgaFactor", 2.0 / 3.0) or (2.0 / 3.0))
        z_raw = d.get("Z")
        z_val = float(getattr(z_raw, "sds", z_raw) or 0.2) if z_raw is not None else 0.2
    design_pga = values["pgaOverrideG"] if values["pgaOverrideG"] > 0 else z_val * pga_factor
    rows = [
        {"metric": "Zone / hazard coefficient Z", "value": z_val, "unit": "g"},
        {"metric": "Code pack PGA factor", "value": pga_factor, "unit": "-"},
        {"metric": "Effective design PGA", "value": design_pga, "unit": "g"},
    ]
    return result(
        summary={"zoneCoefficient": z_val, "pgaFactor": pga_factor, "effectivePgaG": design_pga},
        tables=[
            table(
                "Ground acceleration parameters",
                [("metric", "Metric"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Design PGA = Z × pgaFactor unless explicitly overridden."],
    )


@feature(
    "settingsHazard.spectralAcceleration",
    "Spectral Acceleration",
    part="settings",
    fields=[
        number("dampingRatio", "Viscous damping ratio ξ", 0.05, min=0.01, max=0.3),
    ],
    requires_project=False,
)
def spectral_acceleration(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Sample normalized and design response spectrum ordinates across periods 0..4 s."""
    st = load_settings(ctx)
    resolved_st, site_info = effective_site_class(ctx, st)
    d = project_derived(ctx, resolved_st)
    z_val = d["Z"]
    imp = float(d["seismicImportance"])
    r_val = float(d["RX"])
    sc = site_info["class"]
    periods = [0.0, 0.1, 0.2, 0.4, 0.6, 1.0, 1.5, 2.0, 3.0, 4.0]
    rows = []
    with in_force(ctx.root, resolved_st):
        for t in periods:
            try:
                cs = fem_loads.normalized_spectrum(
                    t, sc, damping=values["dampingRatio"], hazard=z_val
                )
                sa = fem_loads.design_acceleration(
                    t, sc, z_val, imp, r_val, damping=values["dampingRatio"]
                )
            except Exception:  # noqa: BLE001
                cs, sa = 1.0, 0.1
            rows.append({"periodS": t, "cs": cs, "saDesignG": sa})
    return result(
        summary={
            "siteClass": sc,
            "peakCs": max(r["cs"] for r in rows),
            "peakDesignSaG": max(r["saDesignG"] for r in rows),
        },
        tables=[
            table(
                "Response spectrum ordinates",
                [
                    ("periodS", "Period T", "s"),
                    ("cs", "Normalized Cs"),
                    ("saDesignG", "Design Sa", "g"),
                ],
                rows,
            )
        ],
        notes=[
            "Ordinates evaluated directly via saengine.fem.loads.normalized_spectrum and design_acceleration."
        ],
    )


@feature(
    "settingsHazard.magnitudeDistance",
    "Magnitude Distance",
    part="settings",
    fields=[
        number("magnitudeMw", "Design moment magnitude Mw", 6.8, min=4.0, max=9.5),
        number(
            "distanceKm", "Joyner-Boore / rupture distance Rjb", 25.0, unit="km", min=1.0, max=300.0
        ),
        number(
            "vs30MPerS", "Site shear-wave velocity Vs30", 300.0, unit="m/s", min=100.0, max=1500.0
        ),
    ],
    requires_project=False,
)
def magnitude_distance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate deterministic ground motion PGA from magnitude-distance attenuation and site Vs30."""
    mw = values["magnitudeMw"]
    r_km = values["distanceKm"]
    vs30 = values["vs30MPerS"]
    # Standard rock attenuation (Cornell/Boore-Joyner parametric scaling) with Vs30 site amplification
    r_eff = math.sqrt(r_km**2 + 7.5**2)
    ln_pga_rock = -2.1 + 0.85 * mw - 1.35 * math.log(r_eff)
    pga_rock = math.exp(ln_pga_rock)
    site_amp = (760.0 / vs30) ** 0.3
    pga_site = pga_rock * site_amp
    rows = [
        {"parameter": "Effective distance √(R² + h²)", "value": r_eff, "unit": "km"},
        {"parameter": "Reference rock PGA (Vs30=760)", "value": pga_rock, "unit": "g"},
        {"parameter": "Site amplification (760/Vs30)^0.3", "value": site_amp, "unit": "-"},
        {"parameter": "Estimated site PGA", "value": pga_site, "unit": "g"},
    ]
    return result(
        summary={"magnitudeMw": mw, "distanceKm": r_km, "rockPgaG": pga_rock, "sitePgaG": pga_site},
        tables=[
            table(
                "Deterministic magnitude-distance attenuation",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Empirical attenuation screening with Vs30 site amplification; verify with probabilistic seismic hazard study."
        ],
    )


@feature(
    "settingsHazard.faultDistance",
    "Fault Distance",
    part="settings",
    fields=[
        number(
            "faultDistanceKm",
            "Closest distance to active fault",
            8.0,
            unit="km",
            min=0.5,
            max=200.0,
        ),
        select(
            "sourceType",
            "Seismic source type",
            [
                ("A", "Type A - High slip rate / M >= 7.0"),
                ("B", "Type B - Moderate slip rate"),
                ("C", "Type C - Low slip rate"),
            ],
            "B",
        ),
    ],
    requires_project=False,
)
def fault_distance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate near-source short-period (Na) and velocity-period (Nv) amplification factors."""
    dist = values["faultDistanceKm"]
    src = values["sourceType"]
    if src == "A":
        na = (
            1.5
            if dist <= 2.0
            else (
                1.5 - 0.3 * (dist - 2.0) / 8.0
                if dist <= 10.0
                else max(1.0, 1.2 - 0.2 * (dist - 10.0) / 5.0)
            )
        )
        nv = (
            2.0
            if dist <= 2.0
            else (
                2.0 - 0.4 * (dist - 2.0) / 8.0
                if dist <= 10.0
                else max(1.0, 1.6 - 0.6 * (dist - 10.0) / 5.0)
            )
        )
    elif src == "B":
        na = 1.3 if dist <= 2.0 else (1.3 - 0.3 * (dist - 2.0) / 8.0 if dist <= 10.0 else 1.0)
        nv = (
            1.6
            if dist <= 2.0
            else (
                1.6 - 0.4 * (dist - 2.0) / 8.0
                if dist <= 10.0
                else max(1.0, 1.2 - 0.2 * (dist - 10.0) / 5.0)
            )
        )
    else:
        na, nv = 1.0, 1.0
    na = min(1.5, max(1.0, na))
    nv = min(2.0, max(1.0, nv))
    rows = [
        {"factor": "Short-period near-source Na", "value": na},
        {"factor": "1-second near-source Nv", "value": nv},
    ]
    return result(
        summary={
            "faultDistanceKm": dist,
            "sourceType": src,
            "na": na,
            "nv": nv,
            "nearFaultActive": na > 1.0 or nv > 1.0,
        },
        tables=[table("Near-source factors", [("factor", "Factor"), ("value", "Value")], rows)],
        notes=["Near-fault amplification applies within 15 km of active Type A/B seismic sources."],
    )


@feature(
    "settingsHazard.basicWindSpeed",
    "Basic Wind Speed",
    part="settings",
    fields=[
        number("altitudeM", "Site altitude above MSL", 0.0, unit="m", min=0.0, max=4000.0),
    ],
    requires_project=False,
)
def basic_wind_speed(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute site basic wind speed and 10 m reference dynamic velocity pressure."""
    st = load_settings(ctx)
    d = project_derived(ctx, st)
    v_base = float(d.get("windSpeed") or 50.0)
    calt = float(
        d.get("windAltitudeFactor")
        or (1.0 + 0.001 * values["altitudeM"] if values["altitudeM"] > 0 else 1.0)
    )
    v_site = v_base * (calt if "windAltitudeFactor" not in d else 1.0)
    q10_kpa = 0.5 * 1.225 * v_site**2 / 1000.0
    rows = [
        {"item": "Location", "value": st.site.location, "unit": "-"},
        {"item": "Basic wind speed V", "value": v_site, "unit": "m/s"},
        {"item": "Altitude factor", "value": calt, "unit": "-"},
        {"item": "Reference velocity pressure q10", "value": q10_kpa, "unit": "kN/m²"},
    ]
    return result(
        summary={"windSpeedMPerS": v_site, "altitudeFactor": calt, "referencePressureKpa": q10_kpa},
        tables=[
            table(
                "Basic wind climate",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Dynamic pressure q10 = ½ ρ V² using standard air density ρ = 1.225 kg/m³."],
    )


@feature(
    "settingsHazard.directionalityFactor",
    "Directionality Factor",
    part="settings",
    fields=[
        number("kdOverride", "Directionality factor Kd (0 = from pack)", 0.0, min=0.0, max=1.0),
    ],
    requires_project=False,
)
def directionality_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate wind directionality factor Kd from the active code pack vs override."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        wind_tbl = safe_table(pack, "wind")
        kd_pack = float(getattr(wind_tbl, "directionality", 0.85) or 0.85)
    kd_used = (
        values["kdOverride"] if values["kdOverride"] > 0 else (st.wind.directionality or kd_pack)
    )
    rows = [
        {"source": "Active code pack", "kd": kd_pack},
        {"source": "Project setting override", "kd": st.wind.directionality or kd_pack},
        {"source": "Applied factor", "kd": kd_used},
    ]
    return result(
        summary={
            "packKd": kd_pack,
            "appliedKd": kd_used,
            "pressureRatio": kd_used / kd_pack if kd_pack > 0 else 1.0,
        },
        tables=[table("Wind directionality factor Kd", [("source", "Source"), ("kd", "Kd")], rows)],
        notes=[
            "Directionality factor applies only in wind load combinations containing directional wind."
        ],
    )


@feature(
    "settingsHazard.upwindFetch",
    "Upwind Fetch",
    part="settings",
    fields=[
        number("fetchLengthM", "Upwind fetch distance x", 1000.0, unit="m", min=50.0, max=20000.0),
        number("roughnessUpstreamM", "Upstream roughness z0,1", 0.03, unit="m", min=0.003, max=2.0),
        number("roughnessSiteM", "Site roughness z0,2", 0.30, unit="m", min=0.003, max=2.0),
        number("buildingHeightM", "Building height H", 30.0, unit="m", min=3.0),
    ],
    requires_project=False,
)
def upwind_fetch(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate internal boundary layer height over a terrain roughness transition."""
    x = values["fetchLengthM"]
    z0_max = max(values["roughnessUpstreamM"], values["roughnessSiteM"])
    # Elliott/ESD boundary layer transition height: delta_i = 0.28 * z0 * (x / z0)^0.8
    delta_i = 0.28 * z0_max * (x / z0_max) ** 0.8
    h = values["buildingHeightM"]
    fully_developed = delta_i >= h
    rows = [
        {"parameter": "Fetch distance x", "value": x, "unit": "m"},
        {"parameter": "Internal boundary layer height δi", "value": delta_i, "unit": "m"},
        {"parameter": "Building height H", "value": h, "unit": "m"},
    ]
    return result(
        summary={
            "boundaryHeightM": delta_i,
            "buildingHeightM": h,
            "fullyAdaptedToSite": fully_developed,
        },
        tables=[
            table(
                "Upwind terrain fetch transition",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Internal boundary layer δi = 0.28 z0 (x / z0)^0.8; if δi < H, upper storeys see upstream exposure."
        ],
    )


@feature(
    "settingsHazard.annualExceedance",
    "Annual Exceedance",
    part="settings",
    fields=[
        number("returnPeriodYears", "Wind return period T", 50.0, unit="yr", min=1.0, max=2000.0),
        number("exposureYears", "Service exposure duration L", 50.0, unit="yr", min=1.0, max=200.0),
    ],
    requires_project=False,
)
def annual_exceedance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert wind return period to annual/lifetime exceedance probabilities and speed factor."""
    t_ret = values["returnPeriodYears"]
    t_exp = values["exposureYears"]
    p_ann = 1.0 - math.exp(-1.0 / t_ret)
    p_life = 1.0 - (1.0 - p_ann) ** t_exp
    # Standard Type I extreme value scaling relative to 50-year mean wind speed
    c_prob = (
        (1.0 - 0.2 * math.log(-math.log(1.0 - p_ann))) / (1.0 - 0.2 * math.log(-math.log(0.98)))
    ) ** 0.5
    rows = [
        {"metric": "Annual exceedance probability", "value": p_ann * 100.0, "unit": "%"},
        {"metric": "Exposure-period exceedance", "value": p_life * 100.0, "unit": "%"},
        {"metric": "Speed ratio vs 50-yr reference", "value": c_prob, "unit": "-"},
    ]
    return result(
        summary={
            "annualProbabilityPct": p_ann * 100.0,
            "lifetimeProbabilityPct": p_life * 100.0,
            "speedMultiplierVs50Yr": c_prob,
        },
        tables=[
            table(
                "Wind exceedance statistics",
                [("metric", "Metric"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Gumbel Type I probability scaling relative to a 50-year reference return period."],
    )


@feature(
    "settingsHazard.tsunamiZone",
    "Tsunami Zone",
    part="settings",
    fields=[
        number("inundationDepthM", "Design inundation depth h", 2.5, unit="m", min=0.0),
        number("flowVelocityMPerS", "Flow velocity u", 4.0, unit="m/s", min=0.0),
        number("columnWidthM", "Exposed element width b", 0.6, unit="m", min=0.1),
        number("dragCoeff", "Drag coefficient Cd", 2.0, min=1.0, max=2.5),
    ],
    requires_project=False,
)
def tsunami_zone(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute coastal tsunami hydrodynamic drag force and hydrostatic pressure on structural members."""
    h = values["inundationDepthM"]
    u = values["flowVelocityMPerS"]
    b = values["columnWidthM"]
    cd = values["dragCoeff"]
    rho_sw = 1025.0  # kg/m3 seawater
    gamma_sw = rho_sw * 9.80665 / 1000.0  # kN/m3
    p_hydrostatic = gamma_sw * h
    q_dyn = 0.5 * rho_sw * u**2 / 1000.0  # kPa
    fd_per_m = cd * q_dyn * b
    fd_total = fd_per_m * h
    rows = [
        {"action": "Hydrostatic base pressure", "value": p_hydrostatic, "unit": "kPa"},
        {"action": "Stagnation dynamic pressure", "value": q_dyn, "unit": "kPa"},
        {"action": "Hydrodynamic drag per unit height", "value": fd_per_m, "unit": "kN/m"},
        {"action": "Total drag force on element", "value": fd_total, "unit": "kN"},
    ]
    return result(
        summary={
            "hydrostaticBaseKpa": p_hydrostatic,
            "dynamicPressureKpa": q_dyn,
            "totalDragKn": fd_total,
        },
        tables=[
            table(
                "Tsunami hydrodynamic screening",
                [("action", "Action"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Drag force Fd = ½ ρsw Cd b h u² using seawater density 1025 kg/m³."],
    )


@feature(
    "settingsHazard.frostDepth",
    "Frost Depth",
    part="settings",
    fields=[
        number(
            "airFreezingIndexDegDays", "Design air freezing index FI", 400.0, unit="°C·day", min=0.0
        ),
        number(
            "soilThermalCondWPerMK",
            "Soil thermal conductivity k",
            1.8,
            unit="W/(m·K)",
            min=0.3,
            max=4.0,
        ),
        number(
            "moistureContentPct",
            "Soil gravimetric water content w",
            18.0,
            unit="%",
            min=1.0,
            max=60.0,
        ),
        number(
            "dryDensityKgPerM3", "Soil dry density ρd", 1700.0, unit="kg/m³", min=1000.0, max=2200.0
        ),
        number("footingDepthM", "Planned footing depth Df", 1.2, unit="m", min=0.2),
    ],
    requires_project=False,
)
def frost_depth(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate maximum frost penetration depth using Stefan's equation and check footing embedment."""
    fi_sec = values["airFreezingIndexDegDays"] * 86400.0
    k = values["soilThermalCondWPerMK"]
    w = values["moistureContentPct"] / 100.0
    rho_d = values["dryDensityKgPerM3"]
    latent_heat = 334000.0 * rho_d * w  # J/m3
    zf = math.sqrt((2.0 * k * fi_sec) / max(latent_heat, 1.0))
    df = values["footingDepthM"]
    rows = [
        {"metric": "Volumetric latent heat L", "value": latent_heat / 1e6, "unit": "MJ/m³"},
        {"metric": "Estimated frost depth zf", "value": zf, "unit": "m"},
        {"metric": "Planned footing depth Df", "value": df, "unit": "m"},
    ]
    return result(
        summary={"frostDepthM": zf, "footingDepthM": df, "adequateEmbedment": df >= zf},
        tables=[
            table(
                "Frost penetration check",
                [("metric", "Metric"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Stefan equation: zf = √(2 k FI / L) where L is soil pore-water latent heat of fusion."
        ],
    )


@feature(
    "settingsHazard.expansiveSoilZone",
    "Expansive Soil Zone",
    part="settings",
    fields=[
        number("liquidLimitPct", "Liquid limit LL", 58.0, unit="%", min=10.0, max=150.0),
        number("plasticityIndexPct", "Plasticity index PI", 32.0, unit="%", min=0.0, max=120.0),
        number("freeSwellPct", "Free swell index", 65.0, unit="%", min=0.0, max=300.0),
    ],
    requires_project=False,
)
def expansive_soil_zone(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Classify soil expansion potential from Atterberg limits and free swell."""
    ll = values["liquidLimitPct"]
    pi = values["plasticityIndexPct"]
    fs = values["freeSwellPct"]
    if pi >= 35.0 or ll >= 60.0 or fs >= 100.0:
        degree = "High / Very High"
    elif pi >= 20.0 or ll >= 45.0 or fs >= 50.0:
        degree = "Moderate"
    else:
        degree = "Low"
    # Seed-Woodward-Lundgren swell % approximation: S = 0.00216 * PI^2.44
    est_swell_pct = 0.00216 * (pi**2.44)
    rows = [
        {"indicator": "Liquid limit LL", "value": ll, "unit": "%"},
        {"indicator": "Plasticity index PI", "value": pi, "unit": "%"},
        {"indicator": "Free swell", "value": fs, "unit": "%"},
        {"indicator": "Estimated 1D swell potential", "value": est_swell_pct, "unit": "%"},
    ]
    return result(
        summary={
            "expansionClass": degree,
            "estimatedSwellPct": est_swell_pct,
            "requiresMitigation": degree != "Low",
        },
        tables=[
            table(
                "Expansive soil screening",
                [("indicator", "Indicator"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Screening based on LL, PI, free swell, and empirical swell potential S = 0.00216 PI^2.44."
        ],
    )


@feature(
    "settingsHazard.radonZone",
    "Radon Zone",
    part="settings",
    fields=[
        select(
            "radonClass",
            "Site radon potential",
            [
                ("low", "Low (< 1% above action level)"),
                ("moderate", "Moderate (1-10%)"),
                ("high", "High (> 10%)"),
            ],
            "moderate",
        ),
        number("footprintAreaM2", "Ground-contact slab footprint area", 450.0, unit="m²", min=10.0),
    ],
    requires_project=False,
)
def radon_zone(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Specify sub-slab radon protection barrier and passive/active ventilation stack sizing."""
    rc = values["radonClass"]
    area = values["footprintAreaM2"]
    stacks = max(1, math.ceil(area / 250.0)) if rc != "low" else 0
    membrane_mm = 0.30 if rc == "low" else (0.40 if rc == "moderate" else 0.50)
    mitigation = {
        "low": "Standard damp-proof membrane",
        "moderate": "Sealed radon barrier + passive sump",
        "high": "Full radon barrier + active sub-slab depressurization",
    }[rc]
    rows = [
        {"requirement": "Protection class", "value": mitigation},
        {"requirement": "Minimum barrier thickness [mm]", "value": f"{membrane_mm:.2f}"},
        {"requirement": "Recommended ventilation stacks", "value": str(stacks)},
    ]
    return result(
        summary={"radonClass": rc, "barrierThicknessMm": membrane_mm, "ventStackCount": stacks},
        tables=[
            table(
                "Sub-slab radon mitigation defaults",
                [("requirement", "Requirement"), ("value", "Specification")],
                rows,
            )
        ],
        notes=[
            "One sub-slab suction point / vent stack allocated per 250 m² of ground-contact footprint."
        ],
    )

"""Project Settings - Foundation: Soil Profile & Strata tab: layers, water, strength, CPT/SPT, permeability."""

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
from saengine.features.settings_common import load_settings, parse_csv_rows
from saengine.report.clauses import in_force
from saengine.soil import site_class as soil_sc
from saengine.soil.profile import Profile


@feature(
    "settingsFoundationSoil.addLayer",
    "Add Layer",
    part="settings",
    fields=[
        text("layerName", "Stratum name", "Medium Dense Sand"),
        number("thicknessM", "Layer thickness", 4.0, unit="m", min=0.2),
        select(
            "soilType",
            "Soil type",
            [
                ("sand", "Sand (granular)"),
                ("clay", "Clay (cohesive)"),
                ("silt", "Silt"),
                ("rock", "Rock"),
            ],
            "sand",
        ),
        number("gammaKnM3", "Unit weight γ", 18.5, unit="kN/m³", min=10.0),
    ],
    requires_project=False,
)
def add_layer(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview adding a soil stratum and compute its vertical overburden increment."""
    overburden = values["thicknessM"] * values["gammaKnM3"]
    return result(
        summary={
            "layerName": values["layerName"],
            "thicknessM": values["thicknessM"],
            "overburdenKpa": overburden,
        },
        tables=[
            table(
                "New soil layer definition",
                [
                    ("name", "Stratum"),
                    ("type", "Type"),
                    ("thicknessM", "Thickness", "m"),
                    ("gammaKnM3", "γ", "kN/m³"),
                    ("overburdenKpa", "Δσv", "kPa"),
                ],
                [
                    {
                        "name": values["layerName"],
                        "type": values["soilType"],
                        "thicknessM": values["thicknessM"],
                        "gammaKnM3": values["gammaKnM3"],
                        "overburdenKpa": overburden,
                    }
                ],
            )
        ],
        notes=["Overburden stress increment Δσv = γ × thickness."],
    )


@feature(
    "settingsFoundationSoil.layerThickness",
    "Layer Thickness",
    part="settings",
    fields=[
        number("topDepthM", "Top depth", 2.0, unit="m", min=0.0),
        number("bottomDepthM", "Bottom depth", 6.5, unit="m", min=0.2),
    ],
    requires_project=False,
)
def layer_thickness(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate stratum depth interval and compute layer thickness."""
    t = values["bottomDepthM"] - values["topDepthM"]
    if t <= 0:
        raise FeatureInputError("Bottom depth must be greater than top depth.")
    return result(
        summary={
            "topDepthM": values["topDepthM"],
            "bottomDepthM": values["bottomDepthM"],
            "thicknessM": t,
        },
        tables=[
            table(
                "Layer depth interval",
                [
                    ("topM", "Top", "m"),
                    ("bottomM", "Bottom", "m"),
                    ("thicknessM", "Thickness", "m"),
                ],
                [{"topM": values["topDepthM"], "bottomM": values["bottomDepthM"], "thicknessM": t}],
            )
        ],
        notes=["Layer thicknesses must sum monotonically from ground surface."],
    )


@feature(
    "settingsFoundationSoil.layerMaterial",
    "Layer Material",
    part="settings",
    fields=[],
    requires_project=False,
)
def layer_material(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect soil layer classifications from the project's 1 Soil Report boreholes."""
    rep = ctx.soil()
    rows = []
    if rep is not None and rep.boreholes:
        for lyr in rep.boreholes[0].layers:
            rows.append(
                {
                    "depthToM": lyr.bottom,
                    "type": str(lyr.soilType),
                    "gamma": lyr.unitWeight,
                    "phi": lyr.phi or "-",
                    "cu": lyr.cu or "-",
                }
            )
    return result(
        summary={"layerCount": len(rows), "fromProject": rep is not None},
        tables=[
            table(
                "First borehole layer materials",
                [
                    ("depthToM", "Bottom", "m"),
                    ("type", "Type"),
                    ("gamma", "γ", "kN/m³"),
                    ("phi", "φ'"),
                    ("cu", "cu", "kPa"),
                ],
                rows or [{"depthToM": 10.0, "type": "sand", "gamma": 18.0, "phi": 30.0, "cu": "-"}],
            )
        ],
        notes=["Reads stratigraphy from 01 Soil Report/soil-report.json when available."],
    )


@feature(
    "settingsFoundationSoil.layerOrder",
    "Layer Order",
    part="settings",
    fields=[],
    requires_project=False,
)
def layer_order(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify top-to-bottom continuity of soil profile layers across project boreholes."""
    rep = ctx.soil()
    if rep is None or not rep.boreholes:
        return result(
            summary={"boreholeCount": 0, "continuous": True},
            tables=[
                table(
                    "Layer order audit",
                    [("borehole", "Borehole"), ("layers", "Layers"), ("continuous", "Continuous")],
                    [{"borehole": "(none)", "layers": 0, "continuous": True}],
                )
            ],
            notes=[
                "Open a project with 01 Soil Report boreholes to verify stratigraphy continuity."
            ],
        )
    rows = []
    for bh in rep.boreholes:
        prev = 0.0
        ok = True
        for lyr in bh.layers:
            if lyr.bottom <= prev:
                ok = False
            prev = lyr.bottom
        rows.append(
            {"borehole": bh.id, "layers": len(bh.layers), "maxDepthM": prev, "continuous": ok}
        )
    return result(
        summary={"boreholeCount": len(rows), "allContinuous": all(r["continuous"] for r in rows)},
        tables=[
            table(
                "Borehole layer order audit",
                [
                    ("borehole", "Borehole"),
                    ("layers", "Layers"),
                    ("maxDepthM", "Max depth", "m"),
                    ("continuous", "Ordered"),
                ],
                rows,
            )
        ],
        notes=["Confirms strictly increasing layer bottom depths."],
    )


@feature(
    "settingsFoundationSoil.strataName",
    "Strata Name",
    part="settings",
    fields=[
        text("uscsSymbol", "USCS symbol", "SP"),
        text("stratumLabel", "Stratum label", "Alluvial Fine-to-Medium Sand"),
    ],
    requires_project=False,
)
def strata_name(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign standardized USCS symbol and engineering stratum name."""
    return result(
        summary={"uscs": values["uscsSymbol"], "label": values["stratumLabel"]},
        tables=[
            table(
                "Stratum naming",
                [("uscs", "USCS"), ("label", "Engineering description")],
                [{"uscs": values["uscsSymbol"], "label": values["stratumLabel"]}],
            )
        ],
        notes=["Displayed on foundation borehole logs and geotechnical summaries."],
    )


@feature(
    "settingsFoundationSoil.strataDescription",
    "Strata Description",
    part="settings",
    fields=[
        select(
            "consistency",
            "Density / consistency",
            [
                ("loose", "Loose / Soft"),
                ("medium", "Medium Dense / Firm"),
                ("dense", "Dense / Stiff"),
                ("veryDense", "Very Dense / Hard"),
            ],
            "medium",
        ),
        text("origin", "Geological origin", "Holocene alluvial deposit"),
    ],
    requires_project=False,
)
def strata_description(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Format standardized geotechnical stratum description text."""
    desc = f"{values['consistency'].title()} - {values['origin']}"
    return result(
        summary={"consistency": values["consistency"], "description": desc},
        tables=[
            table(
                "Stratum description",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Consistency", "value": values["consistency"]},
                    {"field": "Full description", "value": desc},
                ],
            )
        ],
        notes=["Combines relative density/consistency with depositional origin."],
    )


@feature(
    "settingsFoundationSoil.strataColour",
    "Strata Colour",
    part="settings",
    fields=[
        select(
            "soilType",
            "Soil group",
            [
                ("sand", "Sand (amber)"),
                ("clay", "Clay (blue-grey)"),
                ("silt", "Silt (olive)"),
                ("peat", "Organic/Peat (brown)"),
                ("rock", "Bedrock (slate)"),
            ],
            "sand",
        ),
    ],
    requires_project=False,
)
def strata_colour(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign standard CAD/report display color codes per soil stratum type."""
    palette = {
        "sand": "#E6B86A",
        "clay": "#7D9AB5",
        "silt": "#9AA67B",
        "peat": "#6E4F3A",
        "rock": "#6C727A",
    }
    return result(
        summary={"soilType": values["soilType"], "hexColor": palette[values["soilType"]]},
        tables=[
            table(
                "Strata display palette",
                [("soilType", "Soil type"), ("hexColor", "Hex color")],
                [{"soilType": k, "hexColor": v} for k, v in palette.items()],
            )
        ],
        notes=["Provides consistent visual stratigraphy across borehole section plots."],
    )


@feature(
    "settingsFoundationSoil.groupStrata",
    "Group Strata",
    part="settings",
    fields=[],
    requires_project=False,
)
def group_strata(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Group soil layers across project boreholes by soil type to compute average thickness."""
    rep = ctx.soil()
    groups: dict[str, list[float]] = {}
    if rep is not None:
        for bh in rep.boreholes:
            top = 0.0
            for lyr in bh.layers:
                groups.setdefault(str(lyr.soilType), []).append(lyr.bottom - top)
                top = lyr.bottom
    rows = [
        {"soilType": k, "occurrences": len(v), "meanThicknessM": sum(v) / len(v)}
        for k, v in groups.items()
    ]
    return result(
        summary={"groupCount": len(rows)},
        tables=[
            table(
                "Grouped soil strata summary",
                [
                    ("soilType", "Type"),
                    ("occurrences", "Count"),
                    ("meanThicknessM", "Mean thickness", "m"),
                ],
                rows or [{"soilType": "No boreholes", "occurrences": 0, "meanThicknessM": 0.0}],
            )
        ],
        notes=["Aggregates layers by soil type across all project boreholes."],
    )


@feature(
    "settingsFoundationSoil.waterTable",
    "Water Table",
    part="settings",
    fields=[
        number("waterDepthM", "Water table depth below ground", 2.5, unit="m", min=0.0),
        number("evalDepthM", "Evaluation depth z", 8.0, unit="m", min=0.5),
        number("gammaSoilKnM3", "Total soil unit weight γ", 19.0, unit="kN/m³", min=12.0),
    ],
    requires_project=False,
)
def water_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute hydrostatic pore pressure u and effective vertical stress σ'v at depth z."""
    z = values["evalDepthM"]
    zw = values["waterDepthM"]
    u = max(0.0, z - zw) * 9.81
    sv = values["gammaSoilKnM3"] * z
    sv_eff = sv - u
    return result(
        summary={"waterDepthM": zw, "porePressureKpa": u, "effectiveStressKpa": sv_eff},
        tables=[
            table(
                "Pore pressure & effective stress",
                [("item", "Item"), ("kpa", "Stress", "kPa")],
                [
                    {"item": "Total vertical σv", "kpa": sv},
                    {"item": "Pore water u", "kpa": u},
                    {"item": "Effective vertical σ'v", "kpa": sv_eff},
                ],
            )
        ],
        notes=["Effective stress principle: σ'v = σv - u."],
    )


@feature(
    "settingsFoundationSoil.seasonalVariation",
    "Seasonal Variation",
    part="settings",
    fields=[
        number("drySeasonDepthM", "Dry-season water depth", 4.0, unit="m", min=0.0),
        number("wetSeasonDepthM", "Wet-season water depth", 1.2, unit="m", min=0.0),
    ],
    requires_project=False,
)
def seasonal_variation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate seasonal water table fluctuation amplitude and worst-case buoyancy depth."""
    fluct = abs(values["drySeasonDepthM"] - values["wetSeasonDepthM"])
    gov_high = min(values["drySeasonDepthM"], values["wetSeasonDepthM"])
    gov_low = max(values["drySeasonDepthM"], values["wetSeasonDepthM"])
    return result(
        summary={"fluctuationM": fluct, "governingHighGwtM": gov_high, "governingLowGwtM": gov_low},
        tables=[
            table(
                "Seasonal groundwater envelope",
                [("condition", "Design check"), ("gwtDepthM", "Governing GWT depth", "m")],
                [
                    {"condition": "Bearing / liquefaction / uplift", "gwtDepthM": gov_high},
                    {"condition": "Consolidation settlement", "gwtDepthM": gov_low},
                ],
            )
        ],
        notes=[
            "Use highest seasonal GWT for bearing and uplift; lowest for effective overburden consolidation."
        ],
    )


@feature(
    "settingsFoundationSoil.artesianCondition",
    "Artesian Condition",
    part="settings",
    fields=[
        number("clayBlanketM", "Confining clay thickness H", 4.0, unit="m", min=0.5),
        number("gammaClayKnM3", "Clay unit weight γ", 18.0, unit="kN/m³", min=12.0),
        number("artesianHeadM", "Piezometric head above clay base", 6.5, unit="m", min=0.0),
    ],
    requires_project=False,
)
def artesian_condition(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check basal hydraulic uplift factor of safety against confined artesian groundwater."""
    overburden = values["clayBlanketM"] * values["gammaClayKnM3"]
    uplift = values["artesianHeadM"] * 9.81
    fs = overburden / uplift if uplift > 0 else 99.0
    return result(
        summary={
            "overburdenKpa": overburden,
            "artesianUpliftKpa": uplift,
            "safetyFactor": fs,
            "safe": fs >= 1.2,
        },
        tables=[
            table(
                "Artesian basal heave check",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Confining weight [kPa]", "value": overburden},
                    {"item": "Artesian pressure [kPa]", "value": uplift},
                    {"item": "Factor of safety", "value": fs},
                ],
            )
        ],
        notes=["FS < 1.2 requires pressure relief wells prior to excavation."],
    )


@feature(
    "settingsFoundationSoil.applyProfile",
    "Apply Profile",
    part="settings",
    fields=[],
    requires_project=False,
)
def apply_profile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate active borehole profiles and report governing seismic site class."""
    rep = ctx.soil()
    st = load_settings(ctx)
    if rep is None or not rep.boreholes:
        return result(
            summary={"boreholes": 0, "governingSiteClass": st.site.siteClass},
            tables=[
                table(
                    "Applied ground profile",
                    [("item", "Item"), ("value", "Value")],
                    [{"item": "Entered site class", "value": st.site.siteClass}],
                )
            ],
            notes=[
                "No boreholes in 01 Soil Report; foundation checks fall back to Project Settings."
            ],
        )
    with in_force(ctx.root, st):
        sites = {b.id: soil_sc.site_class(Profile(rep, b)) for b in rep.boreholes}
        gov = soil_sc.governing(sites)
    rows = [
        {"borehole": k, "siteClass": v.get("class", "-"), "nBar": v.get("N") or 0.0}
        for k, v in sites.items()
    ]
    return result(
        summary={
            "boreholes": len(rows),
            "governingSiteClass": str(gov.get("class") or st.site.siteClass),
        },
        tables=[
            table(
                "Borehole profile classification",
                [("borehole", "Borehole"), ("siteClass", "Site class"), ("nBar", "N̄30")],
                rows,
            )
        ],
        notes=[str(gov.get("note", "Profile applied across foundation design checks."))],
    )


@feature(
    "settingsFoundationSoil.frictionAngle",
    "Friction Angle",
    part="settings",
    fields=[
        number("phiDeg", "Effective friction angle φ'", 32.0, unit="°", min=10.0, max=48.0),
    ],
    requires_project=False,
)
def friction_angle(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Rankine active/passive and Jaky at-rest lateral earth pressure coefficients from φ'."""
    phi = values["phiDeg"]
    rad = math.radians(phi)
    ka = math.tan(math.radians(45.0 - phi / 2.0)) ** 2
    kp = math.tan(math.radians(45.0 + phi / 2.0)) ** 2
    k0 = 1.0 - math.sin(rad)
    return result(
        summary={"phiDeg": phi, "ka": ka, "k0": k0, "kp": kp},
        tables=[
            table(
                "Earth pressure coefficients",
                [("coeff", "Coefficient"), ("value", "Value")],
                [
                    {"coeff": "Ka (Active Rankine)", "value": ka},
                    {"coeff": "K0 (At-rest Jaky)", "value": k0},
                    {"coeff": "Kp (Passive Rankine)", "value": kp},
                ],
            )
        ],
        notes=["Smooth vertical wall and level backfill assumptions (Rankine & Jaky)."],
    )


@feature(
    "settingsFoundationSoil.cohesionValue",
    "Cohesion Value",
    part="settings",
    fields=[
        number("cohesionKpa", "Effective/undrained cohesion c", 35.0, unit="kPa", min=0.0),
        number("gammaKnM3", "Soil unit weight γ", 18.0, unit="kN/m³", min=12.0),
        number("phiDeg", "Friction angle φ'", 0.0, unit="°", min=0.0, max=40.0),
    ],
    requires_project=False,
)
def cohesion_value(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute theoretical tension crack depth zc and unconfined compressive strength qu."""
    ka = math.tan(math.radians(45.0 - values["phiDeg"] / 2.0)) ** 2
    zc = (2.0 * values["cohesionKpa"]) / (values["gammaKnM3"] * math.sqrt(ka))
    qu = 2.0 * values["cohesionKpa"] / math.sqrt(ka)
    return result(
        summary={
            "cohesionKpa": values["cohesionKpa"],
            "tensionCrackDepthM": zc,
            "unconfinedStrengthKpa": qu,
        },
        tables=[
            table(
                "Cohesion parameters",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Theoretical tension crack zc [m]", "value": zc},
                    {"metric": "Unconfined strength qu [kPa]", "value": qu},
                ],
            )
        ],
        notes=["Tension cracks should be assumed water-filled or ignored in active thrust design."],
    )


@feature(
    "settingsFoundationSoil.modulusElasticity",
    "Modulus Elasticity",
    part="settings",
    fields=[
        number("sptN60", "Corrected SPT N60", 20.0, min=1.0, max=100.0),
        select(
            "soilKind",
            "Soil type",
            [
                ("sand", "Clean sand (Es ≈ 500(N+15) kPa)"),
                ("clayeySand", "Clayey sand (Es ≈ 320(N+15) kPa)"),
                ("gravel", "Gravelly sand (Es ≈ 1200(N+6) kPa)"),
            ],
            "sand",
        ),
    ],
    requires_project=False,
)
def modulus_elasticity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate drained soil elastic modulus Es from SPT N60 using Bowles correlations."""
    n = values["sptN60"]
    if values["soilKind"] == "sand":
        es_kpa = 500.0 * (n + 15.0)
    elif values["soilKind"] == "clayeySand":
        es_kpa = 320.0 * (n + 15.0)
    else:
        es_kpa = 1200.0 * (n + 6.0)
    return result(
        summary={"sptN60": n, "esMpa": es_kpa / 1000.0, "esKpa": es_kpa},
        tables=[
            table(
                "Soil elastic modulus estimate",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Es [kPa]", "value": es_kpa},
                    {"metric": "Es [MPa]", "value": es_kpa / 1000.0},
                ],
            )
        ],
        notes=["Bowles SPT-Es empirical correlation for immediate elastic settlement."],
    )


@feature(
    "settingsFoundationSoil.poissonRatio",
    "Poisson Ratio",
    part="settings",
    fields=[
        select(
            "drainage",
            "Drainage condition",
            [
                ("undrainedClay", "Saturated clay (undrained ν = 0.50)"),
                ("drainedClay", "Stiff clay (drained ν = 0.25)"),
                ("sandDense", "Dense sand (ν = 0.35)"),
                ("sandLoose", "Loose sand (ν = 0.25)"),
            ],
            "sandDense",
        ),
    ],
    requires_project=False,
)
def poisson_ratio(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Derive at-rest elastic K0 = ν / (1 - ν) and shear-to-elastic modulus ratio G / E."""
    nu_map = {"undrainedClay": 0.495, "drainedClay": 0.25, "sandDense": 0.35, "sandLoose": 0.25}
    nu = nu_map[values["drainage"]]
    k0_el = nu / (1.0 - nu)
    g_over_e = 1.0 / (2.0 * (1.0 + nu))
    return result(
        summary={"poissonRatio": nu, "elasticK0": k0_el, "shearModulusRatio": g_over_e},
        tables=[
            table(
                "Soil Poisson ratio relationships",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "ν", "value": nu},
                    {"property": "Elastic K0 = ν/(1-ν)", "value": k0_el},
                    {"property": "G / E = 1/(2(1+ν))", "value": g_over_e},
                ],
            )
        ],
        notes=["Constant-volume undrained clay approaches ν = 0.5."],
    )


@feature(
    "settingsFoundationSoil.cptData",
    "CPT Data",
    part="settings",
    fields=[
        text(
            "cptCsv",
            "CPT log CSV (depth_m,qc_mpa,fs_kpa)",
            "depth_m,qc_mpa,fs_kpa\n2.0,4.5,45\n5.0,8.2,70\n8.0,12.5,95",
        ),
    ],
    requires_project=False,
)
def cpt_data(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Parse CPT soundings (qc, fs) and compute friction ratio Rf = fs / qc."""
    raw = parse_csv_rows(values["cptCsv"], "CPT CSV")
    rows = []
    for r in raw:
        try:
            z = float(r["depth_m"])
            qc = float(r["qc_mpa"])
            fs = float(r["fs_kpa"])
        except (KeyError, ValueError) as exc:
            raise FeatureInputError("CPT CSV requires depth_m, qc_mpa, fs_kpa.") from exc
        rf_pct = (fs / (qc * 1000.0)) * 100.0 if qc > 0 else 0.0
        rows.append({"depthM": z, "qcMpa": qc, "fsKpa": fs, "frictionRatioPct": rf_pct})
    return result(
        summary={"pointCount": len(rows), "maxQcMpa": max(r["qcMpa"] for r in rows)},
        tables=[
            table(
                "CPT sounding summary",
                [
                    ("depthM", "Depth", "m"),
                    ("qcMpa", "qc", "MPa"),
                    ("fsKpa", "fs", "kPa"),
                    ("frictionRatioPct", "Rf", "%"),
                ],
                rows,
            )
        ],
        notes=[
            "Friction ratio Rf = (fs / qc) × 100%; higher Rf (> 2%) indicates cohesive/silty soils."
        ],
    )


@feature(
    "settingsFoundationSoil.sptNValue",
    "SPT N Value",
    part="settings",
    fields=[
        number("nRaw", "Field blow count N", 18.0, min=0.0, max=100.0),
        number("energyRatioPct", "Hammer energy ratio Er", 60.0, unit="%", min=30.0, max=100.0),
        number("sigmaVeffKpa", "Effective overburden σ'v", 100.0, unit="kPa", min=10.0),
    ],
    requires_project=False,
)
def spt_n_value(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute energy-corrected N60 and overburden-normalized (N1)60 via Liao-Whitman CN."""
    n60 = values["nRaw"] * (values["energyRatioPct"] / 60.0)
    cn = min(1.7, math.sqrt(100.0 / values["sigmaVeffKpa"]))
    n1_60 = n60 * cn
    return result(
        summary={"n60": n60, "cnFactor": cn, "n1_60": n1_60},
        tables=[
            table(
                "SPT N corrections",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "N60 (energy corrected)", "value": n60},
                    {"metric": "Overburden CN = √(100/σ'v)", "value": cn},
                    {"metric": "(N1)60", "value": n1_60},
                ],
            )
        ],
        notes=["Liao & Whitman overburden factor CN capped at 1.7."],
    )


@feature(
    "settingsFoundationSoil.boreholeProfile",
    "Borehole Profile",
    part="settings",
    fields=[],
    requires_project=False,
)
def borehole_profile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate stratigraphic borehole logs from 01 Soil Report/soil-report.json."""
    rep = ctx.soil()
    if rep is None or not rep.boreholes:
        return result(
            summary={"boreholeCount": 0},
            tables=[
                table(
                    "Borehole profile",
                    [("borehole", "BH"), ("bottomM", "Bottom", "m"), ("type", "Type")],
                    [{"borehole": "(none)", "bottomM": 0.0, "type": "No soil report"}],
                )
            ],
            notes=["Add boreholes in 01 Soil Report to view stratigraphic columns."],
        )
    rows = []
    for bh in rep.boreholes:
        for lyr in bh.layers:
            rows.append(
                {
                    "borehole": bh.id,
                    "bottomM": lyr.bottom,
                    "type": str(lyr.soilType),
                    "gammaKnM3": lyr.unitWeight,
                }
            )
    return result(
        summary={"boreholeCount": len(rep.boreholes), "totalLayers": len(rows)},
        tables=[
            table(
                "Project borehole stratigraphy",
                [
                    ("borehole", "BH"),
                    ("bottomM", "Bottom", "m"),
                    ("type", "Soil type"),
                    ("gammaKnM3", "γ", "kN/m³"),
                ],
                rows,
            )
        ],
        notes=["Stratigraphy read from 01 Soil Report/soil-report.json."],
    )


@feature(
    "settingsFoundationSoil.coreSample",
    "Core Sample",
    part="settings",
    fields=[
        number("runLengthMm", "Core run length", 1500.0, unit="mm", min=100.0),
        number("recoveredMm", "Total core recovered", 1280.0, unit="mm", min=0.0),
        number("piecesOver100Mm", "Sum of sound pieces >= 100 mm", 960.0, unit="mm", min=0.0),
    ],
    requires_project=False,
)
def core_sample(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Total Core Recovery (TCR) and Rock Quality Designation (RQD)."""
    run = values["runLengthMm"]
    tcr = min(100.0, (values["recoveredMm"] / run) * 100.0)
    rqd = min(100.0, (values["piecesOver100Mm"] / run) * 100.0)
    quality = (
        "Excellent"
        if rqd >= 90
        else (
            "Good"
            if rqd >= 75
            else ("Fair" if rqd >= 50 else ("Poor" if rqd >= 25 else "Very Poor"))
        )
    )
    return result(
        summary={"tcrPct": tcr, "rqdPct": rqd, "rockQuality": quality},
        tables=[
            table(
                "Rock core recovery",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "TCR [%]", "value": f"{tcr:.1f}"},
                    {"metric": "RQD [%]", "value": f"{rqd:.1f}"},
                    {"metric": "Deere quality", "value": quality},
                ],
            )
        ],
        notes=["RQD sums intact core sticks >= 100 mm divided by total core run length."],
    )


@feature(
    "settingsFoundationSoil.seepageCoefficient",
    "Seepage Coefficient",
    part="settings",
    fields=[
        number("kMPerS", "Hydraulic conductivity k", 1.0e-5, unit="m/s", min=1e-11, max=1.0),
        number("headDiffM", "Hydraulic head difference ΔH", 4.0, unit="m", min=0.0),
        number("flowPathM", "Flow path length L", 10.0, unit="m", min=0.5),
    ],
    requires_project=False,
)
def seepage_coefficient(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate Darcy seepage velocity v = k · i across hydraulic gradient i = ΔH / L."""
    grad = values["headDiffM"] / values["flowPathM"]
    v_darcy = values["kMPerS"] * grad
    q_day_m2 = v_darcy * 86400.0
    return result(
        summary={
            "hydraulicGradient": grad,
            "darcyVelocityMPerS": v_darcy,
            "fluxM3PerM2Day": q_day_m2,
        },
        tables=[
            table(
                "Darcy seepage parameters",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Hydraulic gradient i", "value": grad},
                    {"metric": "Darcy velocity v [m/s]", "value": v_darcy},
                    {"metric": "Daily unit flux [m³/(m²·day)]", "value": q_day_m2},
                ],
            )
        ],
        notes=["Darcy's law q = k · i · A."],
    )


@feature(
    "settingsFoundationSoil.voidRatio",
    "Void Ratio",
    part="settings",
    fields=[
        number("specificGravity", "Grain specific gravity Gs", 2.68, min=2.4, max=2.9),
        number("waterContentPct", "Natural moisture content w", 28.0, unit="%", min=1.0),
        number("saturationPct", "Degree of saturation Sr", 100.0, unit="%", min=10.0, max=100.0),
    ],
    requires_project=False,
)
def void_ratio(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute void ratio e, porosity n, and saturated unit weight from phase relations."""
    e = (values["specificGravity"] * (values["waterContentPct"] / 100.0)) / (
        values["saturationPct"] / 100.0
    )
    n = e / (1.0 + e)
    gamma_sat = ((values["specificGravity"] + e) / (1.0 + e)) * 9.81
    return result(
        summary={"voidRatio": e, "porosity": n, "saturatedUnitWeightKnM3": gamma_sat},
        tables=[
            table(
                "Soil phase relations",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Void ratio e = Gs·w/Sr", "value": e},
                    {"property": "Porosity n = e/(1+e)", "value": n},
                    {"property": "Saturated unit weight [kN/m³]", "value": gamma_sat},
                ],
            )
        ],
        notes=["Standard geotechnical three-phase volume-mass relationships."],
    )


@feature(
    "settingsFoundationSoil.consolidationIndex",
    "Consolidation Index",
    part="settings",
    fields=[
        number("liquidLimitPct", "Liquid limit LL", 48.0, unit="%", min=15.0, max=150.0),
        number("recompressionRatio", "Cr / Cc ratio", 0.18, min=0.05, max=0.40),
    ],
    requires_project=False,
)
def consolidation_index(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate Terzaghi-Peck compression index Cc = 0.009(LL - 10) and recompression index Cr."""
    cc = max(0.05, 0.009 * (values["liquidLimitPct"] - 10.0))
    cr = cc * values["recompressionRatio"]
    return result(
        summary={"compressionIndexCc": cc, "recompressionIndexCr": cr},
        tables=[
            table(
                "Oedometer compression indices",
                [("index", "Index"), ("value", "Value")],
                [
                    {"index": "Compression index Cc", "value": cc},
                    {"index": "Recompression index Cr", "value": cr},
                ],
            )
        ],
        notes=[
            "Skempton/Terzaghi-Peck correlation Cc ≈ 0.009 (LL - 10) for normally consolidated clays."
        ],
    )


@feature(
    "settingsFoundationSoil.permeabilityClass",
    "Permeability Class",
    part="settings",
    fields=[
        number("kMPerS", "Hydraulic conductivity k", 5.0e-7, unit="m/s", min=1e-12, max=1.0),
    ],
    requires_project=False,
)
def permeability_class(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Classify soil drainage and permeability class from hydraulic conductivity k."""
    k = values["kMPerS"]
    if k >= 1e-2:
        cls_name, drainage = "High (Clean gravel)", "Free-draining"
    elif k >= 1e-5:
        cls_name, drainage = "Medium (Clean sand)", "Good drainage"
    elif k >= 1e-7:
        cls_name, drainage = "Low (Silty sand / silt)", "Poor drainage"
    else:
        cls_name, drainage = "Practically impermeable (Clay)", "Undrained short-term"
    return result(
        summary={"kMPerS": k, "permeabilityClass": cls_name, "drainageBehavior": drainage},
        tables=[
            table(
                "Permeability classification",
                [("kMPerS", "k", "m/s"), ("class", "Class"), ("drainage", "Drainage")],
                [{"kMPerS": k, "class": cls_name, "drainage": drainage}],
            )
        ],
        notes=["Terzaghi & Peck permeability classification bands."],
    )

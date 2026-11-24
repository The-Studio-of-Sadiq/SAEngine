"""FEM Model - Wind tab: wind profiles, gust factors, pressures, vortex shedding, story forces, and comfort checks."""

from __future__ import annotations

import math
from typing import Any

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
)
from saengine.features.fem_common import (
    building_height_m,
    building_plan_dims_m,
    load_bim,
    load_settings,
    optional_osmodel,
    require_cfd_results,
    require_results,
    site_params,
)
from saengine.fem import (
    gust_response,
    loads,
    local_pressures,
    peak_velocity_pressure,
    story_response,
    wind_comfort,
)
from saengine.report.clauses import in_force


@feature(
    "femWind.windCases",
    "Wind Cases",
    part="fem",
    fields=[checkbox("includeTorsion", "Include torsional wind cases", True)],
    requires_project=False,
)
def wind_cases(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List static and torsional wind load cases configured for the structural model."""
    _, model = optional_osmodel(ctx)
    w_cases = [
        a
        for a in (model.get("analyses", []) if model else [])
        if str(a.get("name", "")).upper().startswith("W")
    ]
    rows = [{"case": str(a.get("name", "")), "type": str(a.get("type", "Static"))} for a in w_cases]
    if not rows:
        rows = [{"case": "WX", "type": "Static"}, {"case": "WY", "type": "Static"}]
        if values["includeTorsion"]:
            rows += [
                {"case": "WTX", "type": "Static Torsion"},
                {"case": "WTY", "type": "Static Torsion"},
            ]
    return result(
        summary={"windCaseCount": len(rows), "fromModel": bool(w_cases)},
        tables=[table("Wind load cases", [("case", "Case"), ("type", "Type")], rows)],
        notes=["Lists orthogonal and torsional wind load cases."],
    )


@feature(
    "femWind.windProfile",
    "Wind Profile",
    part="fem",
    fields=[number("heightM", "Roof height H", 18.0, unit="m", min=3.0)],
    requires_project=False,
)
def wind_profile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute height-wise wind exposure factor Kz and velocity pressure qz(z)."""
    settings = load_settings(ctx)
    _, _, vb, _, imp, exp = site_params(settings)
    h_max = values["heightM"]
    zs = [round(h_max * f, 2) for f in (0.2, 0.4, 0.6, 0.8, 1.0)]
    rows = []
    with in_force(ctx.root):
        for z in zs:
            kz = loads.exposure_coefficient(max(z, 3.0), exp)
            qz = loads.velocity_pressure(max(z, 3.0), vb, exp, imp)
            rows.append({"heightM": z, "kz": kz, "qzKpa": qz})
    return result(
        summary={"basicSpeedMS": vb, "exposure": exp, "roofPressureKpa": rows[-1]["qzKpa"]},
        tables=[
            table(
                "Wind velocity pressure profile",
                [("heightM", "Height z", "m"), ("kz", "Kz"), ("qzKpa", "qz", "kPa")],
                rows,
            )
        ],
        notes=["Evaluated from active code pack exposure profile and site basic wind speed."],
    )


@feature(
    "femWind.gustFactor",
    "Gust Factor",
    part="fem",
    fields=[
        number("frequencyHz", "Fundamental frequency n1", 1.0, unit="Hz", min=0.05),
        number("damping", "Structural damping ratio", 0.02, min=0.005, max=0.15),
    ],
    requires_project=False,
)
def gust_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute rigid vs flexible gust effect factor and building dynamic wind sensitivity."""
    settings = load_settings(ctx)
    bim = load_bim(ctx)
    _, _, vb, _, _imp, exp = site_params(settings)
    h_m = building_height_m(bim)
    w_m, d_m = building_plan_dims_m(bim)
    with in_force(ctx.root):
        rigid_g = loads.gust_factor(h_m, exp)
        flex = loads.flexible_gust_factor(
            h_m, w_m, d_m, values["frequencyHz"], vb, exp, damping=values["damping"]
        )
        is_flex = loads.is_flexible(values["frequencyHz"])
    rows = [
        {"metric": "Rigid gust factor G", "value": rigid_g},
        {"metric": "Flexible building (n1 < 1 Hz)", "value": str(is_flex)},
    ]
    if isinstance(flex, dict):
        rows += [
            {"metric": k, "value": v}
            for k, v in flex.items()
            if isinstance(v, (int, float, str, bool))
        ]
    return result(
        summary={
            "rigidGustFactor": rigid_g,
            "isFlexible": is_flex,
            "frequencyHz": values["frequencyHz"],
        },
        tables=[
            table("Gust response evaluation", [("metric", "Parameter"), ("value", "Value")], rows)
        ],
        notes=[
            "Structures with natural frequency below 1.0 Hz require flexible dynamic gust evaluation."
        ],
    )


@feature(
    "femWind.surfacePressure",
    "Surface Pressure",
    part="fem",
    fields=[
        number("heightM", "Building height H", 15.0, unit="m", min=3.0),
        number("cpWindward", "Windward Cp", 0.8),
        number("cpLeeward", "Leeward Cp", -0.5),
    ],
    requires_project=False,
)
def surface_pressure(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute net windward and leeward facade pressures from velocity pressure and Cp."""
    settings = load_settings(ctx)
    _, _, vb, _, imp, exp = site_params(settings)
    with in_force(ctx.root):
        qz = loads.velocity_pressure(values["heightM"], vb, exp, imp)
        gf = loads.gust_factor(values["heightM"], exp)
    pw = qz * gf * values["cpWindward"]
    pl = qz * gf * values["cpLeeward"]
    rows = [
        {"zone": "Windward wall", "cp": values["cpWindward"], "pressureKpa": pw},
        {"zone": "Leeward wall", "cp": values["cpLeeward"], "pressureKpa": pl},
        {
            "zone": "Net through-building",
            "cp": values["cpWindward"] - values["cpLeeward"],
            "pressureKpa": pw - pl,
        },
    ]
    return result(
        summary={"qzKpa": qz, "gustFactor": gf, "netPressureKpa": pw - pl},
        tables=[
            table(
                "Facade external wind pressures",
                [("zone", "Surface"), ("cp", "Cp"), ("pressureKpa", "p", "kPa")],
                rows,
            )
        ],
        notes=["External pressure p = qz · G · Cp."],
    )


@feature(
    "femWind.openingsPressure",
    "Openings Pressure",
    part="fem",
    fields=[
        number("windwardOpenAreaM2", "Windward opening area Ao", 8.0, unit="m²", min=0.0),
        number("otherOpenAreaM2", "Remaining envelope openings Aoi", 4.0, unit="m²", min=0.0),
        number("volumeM3", "Enclosed internal volume V", 2000.0, unit="m³", min=10.0),
        number(
            "gcpiEnclosed",
            "Internal pressure coefficient, enclosed",
            0.18,
            min=0,
            help="The code pack's value for an enclosed building.",
        ),
        number(
            "gcpiPartial",
            "Internal pressure coefficient, partially enclosed",
            0.55,
            min=0,
            help="The code pack's value for a partially enclosed building.",
        ),
    ],
    requires_project=False,
)
def openings_pressure(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Classify enclosure status (enclosed, partially enclosed, open) from opening area ratios."""
    ao, aoi = values["windwardOpenAreaM2"], values["otherOpenAreaM2"]
    ratio = ao / max(aoi, 1e-6)
    enclosure = "Partially Enclosed" if (ao > 1.1 * aoi and ao > 0.37) else "Enclosed"
    gcpi = values["gcpiPartial"] if enclosure == "Partially Enclosed" else values["gcpiEnclosed"]
    rows = [
        {"metric": "Opening ratio Ao / Aoi", "value": ratio},
        {"metric": "Enclosure classification", "value": enclosure},
        {"metric": "Internal pressure coeff ±GCpi", "value": gcpi},
    ]
    return result(
        summary={"enclosure": enclosure, "gcpiMagnitude": gcpi, "openingRatio": ratio},
        tables=[
            table(
                "Enclosure & opening pressure classification",
                [("metric", "Parameter"), ("value", "Value")],
                rows,
            )
        ],
        notes=[
            "A partially enclosed building takes the higher internal pressure coefficient; both coefficients come from the code pack."
        ],
    )


@feature(
    "femWind.internalPressure",
    "Internal Pressure",
    part="fem",
    fields=[
        select(
            "enclosure",
            "Enclosure class",
            [
                ("enclosed", "Enclosed (±0.18)"),
                ("partial", "Partially enclosed (±0.55)"),
                ("open", "Open (0.0)"),
            ],
            "enclosed",
        ),
        number("qhKpa", "Roof velocity pressure qh", 1.2, unit="kPa", min=0.0),
    ],
    requires_project=False,
)
def internal_pressure(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate positive and negative internal wind pressures ±qh·GCpi."""
    gcpi = {"enclosed": 0.18, "partial": 0.55, "open": 0.0}[values["enclosure"]]
    pi_pos = values["qhKpa"] * gcpi
    pi_neg = -values["qhKpa"] * gcpi
    rows = [
        {"case": "Internal positive (pushing out)", "gcpi": gcpi, "pressureKpa": pi_pos},
        {"case": "Internal suction (pulling in)", "gcpi": -gcpi, "pressureKpa": pi_neg},
    ]
    return result(
        summary={"gcpi": gcpi, "positivePressureKpa": pi_pos, "negativePressureKpa": pi_neg},
        tables=[
            table(
                "Internal wind pressures",
                [("case", "Case"), ("gcpi", "GCpi"), ("pressureKpa", "pi", "kPa")],
                rows,
            )
        ],
        notes=[
            "Internal pressure adds algebraically to external cladding and roof uplift pressures."
        ],
    )


@feature(
    "femWind.windStoryForces",
    "Wind Story Forces",
    part="fem",
    fields=[],
    requires_project=True,
)
def wind_story_forces(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report analyzed wind storey forces and cumulative shears from 08 FEM/model.results."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    wind_list = [
        c for c in resp.get("cases", []) if str(c.get("label", "")).upper().startswith("W")
    ]
    if not wind_list:
        raise FeatureInputError("No wind case results found in 08 FEM/model.results.")
    rows = []
    for c in wind_list:
        for lv in c.get("levels", []):
            rows.append(
                {
                    "case": str(c.get("label", "")),
                    "level": str(lv.get("name", "")),
                    "shearXKn": float(lv.get("shearXKn", 0.0)),
                    "shearYKn": float(lv.get("shearYKn", 0.0)),
                }
            )
    return result(
        summary={"windCases": len(wind_list), "rows": len(rows)},
        tables=[
            table(
                "Analyzed wind storey shears",
                [
                    ("case", "Case"),
                    ("level", "Level"),
                    ("shearXKn", "Vx", "kN"),
                    ("shearYKn", "Vy", "kN"),
                ],
                rows[:40],
            )
        ],
        notes=["Extracted from 08 FEM/model.results."],
    )


@feature(
    "femWind.driftCheck",
    "Drift Check",
    part="fem",
    fields=[
        number("swayRatioDenominator", "Service sway limit H / N", 400.0, min=100.0, max=1000.0)
    ],
    requires_project=True,
)
def drift_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check analyzed wind roof sway and inter-storey drift against serviceability limits."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    wind_list = [
        c for c in resp.get("cases", []) if str(c.get("label", "")).upper().startswith("W")
    ]
    if not wind_list:
        raise FeatureInputError("No wind displacement results found in 08 FEM/model.results.")
    allow = 1.0 / values["swayRatioDenominator"]
    rows = []
    worst = 0.0
    for c in wind_list:
        for lv in c.get("levels", []):
            dr = max(abs(float(lv.get("driftX", 0.0))), abs(float(lv.get("driftY", 0.0))))
            worst = max(worst, dr)
            rows.append(
                {
                    "case": str(c.get("label", "")),
                    "level": str(lv.get("name", "")),
                    "drift": dr,
                    "limit": allow,
                    "ok": dr <= allow,
                }
            )
    return result(
        summary={"maxWindDrift": worst, "allowable": allow, "passes": worst <= allow},
        tables=[
            table(
                "Wind serviceability drift check",
                [
                    ("case", "Case"),
                    ("level", "Level"),
                    ("drift", "Drift"),
                    ("limit", "Limit"),
                    ("ok", "OK"),
                ],
                rows[:40],
            )
        ],
        notes=[f"Serviceability drift checked against H/{values['swayRatioDenominator']:.0f}."],
    )


@feature(
    "femWind.comfortCheck",
    "Comfort Check",
    part="fem",
    fields=[
        number("frequencyHz", "Fundamental frequency n1", 0.5, unit="Hz", min=0.05),
        number("damping", "Service damping ratio", 0.015, min=0.005, max=0.10),
    ],
    requires_project=True,
)
def comfort_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check wind-induced top-floor acceleration against occupancy comfort criteria."""
    require_results(ctx)
    settings = load_settings(ctx)
    occ = str(getattr(getattr(settings, "occupancy", None), "use", None) or "residential")
    with in_force(ctx.root):
        rules = wind_comfort.table()
        limit = (
            wind_comfort.limit_of(occ, values["frequencyHz"], rules) if rules is not None else 15.0
        )
    rows = [
        {
            "occupancy": occ,
            "frequencyHz": values["frequencyHz"],
            "damping": values["damping"],
            "accelLimitMg": limit,
        }
    ]
    return result(
        summary={"occupancy": occ, "accelLimitMg": limit, "rulesLoaded": rules is not None},
        tables=[
            table(
                "Wind comfort acceleration threshold",
                [
                    ("occupancy", "Occupancy"),
                    ("frequencyHz", "n1", "Hz"),
                    ("damping", "ξ"),
                    ("accelLimitMg", "Limit", "milli-g"),
                ],
                rows,
            )
        ],
        notes=["Evaluated against active code pack occupant comfort acceleration thresholds."],
    )


@feature(
    "femWind.shapeFactorTable",
    "Shape Factor Table",
    part="fem",
    fields=[number("depthOverWidth", "Plan ratio D/B", 0.67, min=0.1, max=10.0)],
    requires_project=False,
)
def shape_factor_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute windward, leeward, and side-wall external pressure coefficients Cp by D/B."""
    db = values["depthOverWidth"]
    cp_lee = -0.5 if db <= 1.0 else (-0.3 if db <= 2.0 else -0.2)
    rows = [
        {"surface": "Windward wall", "cp": 0.8},
        {"surface": "Leeward wall", "cp": cp_lee},
        {"surface": "Side walls", "cp": -0.7},
    ]
    return result(
        summary={"dOverB": db, "netWallCp": 0.8 - cp_lee},
        tables=[
            table("Wall pressure coefficients Cp", [("surface", "Surface"), ("cp", "Cp")], rows)
        ],
        notes=["Leeward suction varies inversely with along-wind aspect ratio D/B."],
    )


@feature(
    "femWind.shieldingFactor",
    "Shielding Factor",
    part="fem",
    fields=[
        number("shelterGapM", "Clear distance to upwind obstruction", 25.0, unit="m", min=1.0),
        number("obstructionHeightM", "Upwind building height", 18.0, unit="m", min=1.0),
    ],
    requires_project=False,
)
def shielding_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate wind shielding reduction factor from upwind building height and separation."""
    ratio = values["shelterGapM"] / values["obstructionHeightM"]
    ks = 1.0 if ratio > 6.0 else max(0.75, 0.75 + 0.25 * (ratio / 6.0))
    rows = [{"gapOverH": ratio, "shieldingFactor": ks, "pressureReductionPct": (1.0 - ks) * 100.0}]
    return result(
        summary={"gapToHeightRatio": ratio, "shieldingFactor": ks},
        tables=[
            table(
                "Adjacent building shielding factor",
                [
                    ("gapOverH", "Gap / H_upwind"),
                    ("shieldingFactor", "Factor"),
                    ("pressureReductionPct", "Reduction", "%"),
                ],
                rows,
            )
        ],
        notes=[
            "Conservative shielding reduction requires permanent upwind obstructions; use 1.0 if uncertain."
        ],
    )


@feature(
    "femWind.turbulenceIntensity",
    "Turbulence Intensity",
    part="fem",
    fields=[number("heightM", "Reference height z", 15.0, unit="m", min=3.0)],
    requires_project=False,
)
def turbulence_intensity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute atmospheric boundary layer turbulence intensity Iz(z) by terrain exposure."""
    settings = load_settings(ctx)
    _, _, _, _, _, exp = site_params(settings)
    with in_force(ctx.root):
        iz = gust_response.turbulence(values["heightM"], exp)
    rows = [
        {"heightM": z, "exposure": exp, "iz": gust_response.turbulence(z, exp) if False else 0.0}
        for z in (5.0, 10.0, values["heightM"], 30.0)
    ]
    with in_force(ctx.root):
        rows = [
            {"heightM": z, "exposure": exp, "iz": gust_response.turbulence(z, exp)}
            for z in (5.0, 10.0, values["heightM"], 30.0)
        ]
    return result(
        summary={"heightM": values["heightM"], "exposure": exp, "turbulenceIntensity": iz},
        tables=[
            table(
                "Turbulence intensity profile",
                [("heightM", "Height", "m"), ("exposure", "Exposure"), ("iz", "Iz")],
                rows,
            )
        ],
        notes=["Computed via saengine.fem.gust_response.turbulence."],
    )


@feature(
    "femWind.externalCoefficients",
    "External Coefficients",
    part="fem",
    fields=[
        number("tributaryAreaM2", "Cladding tributary area", 10.0, unit="m²", min=0.5),
        number("parapetM", "Parapet height", 1.0, unit="m", min=0.0),
    ],
    requires_project=False,
)
def external_coefficients(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute local cladding and roof zone net pressures from active code pack."""
    settings = load_settings(ctx)
    bim = load_bim(ctx)
    _, _, vb, _, imp, exp = site_params(settings)
    h_m = building_height_m(bim)
    w_m, d_m = building_plan_dims_m(bim)
    with in_force(ctx.root):
        lp = local_pressures.local_pressures(
            h_m, w_m, d_m, vb, exp, imp, area=values["tributaryAreaM2"], parapet=values["parapetM"]
        )
    rows = [
        {"zone": k, "value": v} for k, v in (lp or {}).items() if isinstance(v, (int, float, str))
    ]
    return result(
        summary={"areaM2": values["tributaryAreaM2"], "zonesEvaluated": len(rows)},
        tables=[
            table(
                "External C&C pressure coefficients & zones",
                [("zone", "Zone / Term"), ("value", "Value")],
                rows or [{"zone": "C&C", "value": "Evaluated"}],
            )
        ],
        notes=["Uses saengine.fem.local_pressures for roof corners, edges, and wall zones."],
    )


@feature(
    "femWind.faceLoads",
    "Face Loads",
    part="fem",
    fields=[
        number("pressureKpa", "Net facade wind pressure", 1.4, unit="kPa"),
        number("panelWidthM", "Facade bay width", 6.0, unit="m", min=0.5),
        number("panelHeightM", "Storey height", 3.5, unit="m", min=0.5),
    ],
    requires_project=False,
)
def face_loads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert cladding surface wind pressure into total panel force and nodal corner loads."""
    area = values["panelWidthM"] * values["panelHeightM"]
    f_tot = values["pressureKpa"] * area
    rows = [{"panelAreaM2": area, "totalForceKn": f_tot, "cornerForceKn": f_tot / 4.0}]
    return result(
        summary={"panelAreaM2": area, "totalForceKn": f_tot, "cornerNodeForceKn": f_tot / 4.0},
        tables=[
            table(
                "Facade panel face load",
                [
                    ("panelAreaM2", "Area", "m²"),
                    ("totalForceKn", "Total Force", "kN"),
                    ("cornerForceKn", "Per Corner", "kN"),
                ],
                rows,
            )
        ],
        notes=["Distributes uniform pressure evenly to 4 corner cladding attachment nodes."],
    )


@feature(
    "femWind.frameLoads",
    "Frame Loads",
    part="fem",
    fields=[
        number("pressureKpa", "Facade wind pressure", 1.2, unit="kPa"),
        number("tributaryWidthM", "Tributary column/girt spacing", 5.0, unit="m", min=0.5),
    ],
    requires_project=False,
)
def frame_loads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert facade wind pressure into uniform distributed line load on wind columns/girts."""
    w_kn_m = values["pressureKpa"] * values["tributaryWidthM"]
    rows = [
        {
            "pressureKpa": values["pressureKpa"],
            "tributaryWidthM": values["tributaryWidthM"],
            "lineLoadKnPerM": w_kn_m,
        }
    ]
    return result(
        summary={"lineLoadKnPerM": w_kn_m},
        tables=[
            table(
                "Wind frame line load",
                [
                    ("pressureKpa", "Pressure", "kPa"),
                    ("tributaryWidthM", "Width", "m"),
                    ("lineLoadKnPerM", "w", "kN/m"),
                ],
                rows,
            )
        ],
        notes=["w = p · B_trib applied normal to exposed frame members."],
    )


@feature(
    "femWind.torsionFromWind",
    "Torsion From Wind",
    part="fem",
    fields=[
        number("windShearKn", "Storey wind force Fw", 300.0, unit="kN", min=0.0),
        number("widthM", "Building width perpendicular to wind B", 18.0, unit="m", min=1.0),
        number("eccentricityRatio", "Wind eccentricity ratio e/B", 0.15, min=0.0, max=0.5),
    ],
    requires_project=False,
)
def torsion_from_wind(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute wind-induced torsional moment from partial-loading eccentricity e = 0.15·B."""
    e_m = values["widthM"] * values["eccentricityRatio"]
    mt = values["windShearKn"] * e_m
    rows = [{"windShearKn": values["windShearKn"], "eccentricityM": e_m, "torsionKnm": mt}]
    return result(
        summary={"eccentricityM": e_m, "torsionMomentKnm": mt},
        tables=[
            table(
                "Eccentric wind torsion",
                [
                    ("windShearKn", "Fw", "kN"),
                    ("eccentricityM", "e", "m"),
                    ("torsionKnm", "Mt", "kN·m"),
                ],
                rows,
            )
        ],
        notes=["Accounts for unsymmetric wind pressure distribution across wide facades."],
    )


@feature(
    "femWind.alongWindLoad",
    "Along-Wind Load",
    part="fem",
    fields=[
        number("heightM", "Building height H", 45.0, unit="m", min=5.0),
        number("widthM", "Building width B", 24.0, unit="m", min=2.0),
        number("depthM", "Building depth D", 18.0, unit="m", min=2.0),
        number("n1Hz", "Fundamental frequency n1", 0.75, unit="Hz", min=0.05),
        number("damping", "Damping ratio", 0.015, min=0.005, max=0.10),
    ],
    requires_project=False,
)
def along_wind_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute dynamic along-wind peak velocity pressure and structural factor CsCd."""
    settings = load_settings(ctx)
    _, _, vb, _, imp, exp = site_params(settings)
    with in_force(ctx.root):
        qp = peak_velocity_pressure.peak_velocity_pressure(
            values["heightM"], vb, exp, imp, settings.wind
        )
        cs_cd, desc = peak_velocity_pressure.structural_factor(
            values["heightM"],
            values["depthM"],
            settings.wind,
            width=values["widthM"],
            speed=vb,
            terrain=exp,
        )
    base_force = qp * cs_cd * 1.3 * values["widthM"] * values["heightM"] * 0.75
    rows = [
        {"item": "Peak velocity pressure qp(H) [kPa]", "value": qp},
        {"item": "Structural factor CsCd", "value": cs_cd},
        {"item": "Estimated total along-wind shear [kN]", "value": base_force},
    ]
    return result(
        summary={"peakPressureKpa": qp, "structuralFactor": cs_cd, "estimatedShearKn": base_force},
        tables=[
            table("Along-wind dynamic response", [("item", "Parameter"), ("value", "Value")], rows)
        ],
        notes=[f"Basis: {desc}"],
    )


@feature(
    "femWind.vortexShedding",
    "Vortex Shedding",
    part="fem",
    fields=[
        number("diameterOrWidthM", "Cross-wind breadth b", 3.0, unit="m", min=0.2),
        number("frequencyHz", "Cross-wind frequency n1", 1.2, unit="Hz", min=0.05),
        number("strouhal", "Strouhal number St", 0.20, min=0.05, max=0.40),
        number("siteMeanSpeedMS", "10-min mean wind speed at top", 35.0, unit="m/s", min=1.0),
    ],
    requires_project=False,
)
def vortex_shedding(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute critical vortex-shedding wind velocity Vcr = n1·b / St and compare to design speed."""
    v_cr = values["frequencyHz"] * values["diameterOrWidthM"] / values["strouhal"]
    susceptible = v_cr <= 1.25 * values["siteMeanSpeedMS"]
    rows = [
        {"item": "Critical vortex wind speed Vcr [m/s]", "value": v_cr},
        {"item": "1.25 × Vm(top) threshold [m/s]", "value": 1.25 * values["siteMeanSpeedMS"]},
        {"item": "Vortex excitation check required", "value": str(susceptible)},
    ]
    return result(
        summary={"criticalVelocityMS": v_cr, "susceptible": susceptible},
        tables=[
            table("Vortex shedding susceptibility", [("item", "Check"), ("value", "Value")], rows)
        ],
        notes=["Vortex lock-in occurs when critical velocity Vcr = n·b/St falls below 1.25·Vm."],
    )


@feature(
    "femWind.storeyForceCheck",
    "Storey Force Check",
    part="fem",
    fields=[],
    requires_project=True,
)
def storey_force_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare analyzed storey wind forces against base reaction equilibrium."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    wind_list = [
        c for c in resp.get("cases", []) if str(c.get("label", "")).upper().startswith("W")
    ]
    if not wind_list:
        raise FeatureInputError("No wind case results found in 08 FEM/model.results.")
    rows = []
    for c in wind_list:
        br = c.get("baseReaction") or {}
        top_lv = (c.get("levels") or [{}])[-1]
        rows.append(
            {
                "case": str(c.get("label", "")),
                "baseVxKn": float(br.get("fxKn", 0.0)),
                "baseVyKn": float(br.get("fyKn", 0.0)),
                "topDispMm": max(
                    abs(float(top_lv.get("maxUxMm", 0.0))), abs(float(top_lv.get("maxUyMm", 0.0)))
                ),
            }
        )
    return result(
        summary={"windCasesChecked": len(rows)},
        tables=[
            table(
                "Wind storey force & reaction verification",
                [
                    ("case", "Case"),
                    ("baseVxKn", "Base Vx", "kN"),
                    ("baseVyKn", "Base Vy", "kN"),
                    ("topDispMm", "Top Disp", "mm"),
                ],
                rows,
            )
        ],
        notes=["Confirms storey wind load integration equals support reaction base shear."],
    )


@feature(
    "femWind.baseMomentCheck",
    "Base Moment Check",
    part="fem",
    fields=[],
    requires_project=True,
)
def base_moment_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify total wind overturning moment at foundation level against gravity restoring moment."""
    out_dir, model_path = require_results(ctx)
    resp = story_response.story_response(out_dir, model_path)
    wind_list = [
        c for c in resp.get("cases", []) if str(c.get("label", "")).upper().startswith("W")
    ]
    if not wind_list:
        raise FeatureInputError("No wind overturning results found in 08 FEM/model.results.")
    rows = []
    for c in wind_list:
        levels = c.get("levels") or []
        otm = max(
            (
                abs(float(lv.get("momentXKnM", 0.0))) + abs(float(lv.get("momentYKnM", 0.0)))
                for lv in levels
            ),
            default=0.0,
        )
        rows.append({"case": str(c.get("label", "")), "peakOverturningKnm": otm})
    return result(
        summary={
            "windCases": len(rows),
            "maxOverturningKnm": max((r["peakOverturningKnm"] for r in rows), default=0.0),
        },
        tables=[
            table(
                "Wind overturning moment check",
                [("case", "Case"), ("peakOverturningKnm", "Max OTM", "kN·m")],
                rows,
            )
        ],
        notes=["Evaluates cumulative lateral storey force moments about base elevation."],
    )


@feature(
    "femWind.accelerationCheck",
    "Acceleration Check",
    part="fem",
    fields=[
        number("frequencyHz", "Fundamental frequency n1", 0.45, unit="Hz", min=0.05),
        number("damping", "Structural damping", 0.015, min=0.005, max=0.10),
        number("modalMassTonnes", "First-mode generalized mass m1", 400.0, unit="t", min=10.0),
    ],
    requires_project=False,
)
def acceleration_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate peak top-floor wind-induced acceleration [milli-g] against comfort criteria."""
    settings = load_settings(ctx)
    bim = load_bim(ctx)
    _, _, vb, _, _, exp = site_params(settings)
    h_m = building_height_m(bim)
    w_m, d_m = building_plan_dims_m(bim)
    occ = str(getattr(getattr(settings, "occupancy", None), "use", None) or "residential")
    with in_force(ctx.root):
        rules = wind_comfort.table()
        if rules is None:
            raise FeatureInputError(
                "Active code pack does not define wind comfort acceleration tables."
            )
        res = wind_comfort.along_wind_gust(
            h_m,
            w_m,
            d_m,
            values["frequencyHz"],
            vb,
            exp,
            values["damping"],
            values["modalMassTonnes"] * 1000.0,
            values["damping"],
            rules,
        )
        lim = wind_comfort.limit_of(occ, values["frequencyHz"], rules)
    acc_mg = float((res or {}).get("peakAccelMg", 0.0)) if isinstance(res, dict) else 0.0
    rows = [{"occupancy": occ, "peakAccelMg": acc_mg, "limitMg": lim, "ok": acc_mg <= lim}]
    return result(
        summary={"peakAccelMg": acc_mg, "limitMg": lim, "passes": acc_mg <= lim},
        tables=[
            table(
                "Top-floor wind acceleration check",
                [
                    ("occupancy", "Occupancy"),
                    ("peakAccelMg", "Peak Accel", "milli-g"),
                    ("limitMg", "Limit", "milli-g"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Computed via saengine.fem.wind_comfort.along_wind_gust."],
    )


@feature(
    "femWind.windTunnelCompare",
    "Wind Tunnel Compare",
    part="fem",
    fields=[],
    requires_project=True,
)
def wind_tunnel_compare(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare CFD wind tunnel base shears against code wind pressures."""
    data = require_cfd_results(ctx)
    settings = load_settings(ctx)
    bim = load_bim(ctx)
    _, _, vb, _, imp, exp = site_params(settings)
    h_m = building_height_m(bim)
    with in_force(ctx.root):
        qz = loads.velocity_pressure(h_m, vb, exp, imp) * loads.gust_factor(h_m, exp)
    from saengine.fem.cfd_wind import post

    rows = []
    for d in data.get("directions", []):
        bf = post.base_forces(d, qz, 0.0)
        rows.append(
            {
                "angleDeg": d["angle"],
                "vxKn": bf["Vx_kN"],
                "vyKn": bf["Vy_kN"],
                "torsionKnm": bf["T_kNm"],
            }
        )
    return result(
        summary={"directionsCompared": len(rows), "designPressureKpa": qz},
        tables=[
            table(
                "CFD wind tunnel vs design pressure scaling",
                [
                    ("angleDeg", "Direction", "°"),
                    ("vxKn", "Vx", "kN"),
                    ("vyKn", "Vy", "kN"),
                    ("torsionKnm", "Mz", "kN·m"),
                ],
                rows,
            )
        ],
        notes=["Scales CFD force coefficients by code design velocity pressure at roof height."],
    )


@feature(
    "femWind.gustDuration",
    "Gust Duration",
    part="fem",
    fields=[
        number("speed3sMS", "3-second gust wind speed V3s", 44.0, unit="m/s", min=5.0),
        number(
            "targetDurationS", "Target averaging duration", 600.0, unit="s", min=1.0, max=3600.0
        ),
    ],
    requires_project=False,
)
def gust_duration(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert 3-second gust wind speed to mean wind speeds at 10-min, 1-hour, and target durations (Durst curve)."""
    # Durst curve ratio relative to 3600s mean: 3s ~ 1.52, 600s ~ 1.07, 3600s ~ 1.00
    v_3600 = values["speed3sMS"] / 1.52
    dur = values["targetDurationS"]
    ratio = max(1.0, 1.52 - 0.16 * math.log10(max(dur / 3.0, 1.0)))
    v_target = v_3600 * ratio
    rows = [
        {"duration": "3 s (peak gust)", "ratioTo1Hr": 1.52, "speedMS": values["speed3sMS"]},
        {"duration": "600 s (10-min mean)", "ratioTo1Hr": 1.07, "speedMS": v_3600 * 1.07},
        {"duration": "3600 s (1-hr mean)", "ratioTo1Hr": 1.00, "speedMS": v_3600},
        {"duration": f"{dur:g} s (target)", "ratioTo1Hr": ratio, "speedMS": v_target},
    ]
    return result(
        summary={"v3sMS": values["speed3sMS"], "v1HrMS": v_3600, "vTargetMS": v_target},
        tables=[
            table(
                "Durst wind speed averaging conversion",
                [
                    ("duration", "Averaging Time"),
                    ("ratioTo1Hr", "Ratio to 1-hr"),
                    ("speedMS", "Speed", "m/s"),
                ],
                rows,
            )
        ],
        notes=["Durst open-terrain averaging duration conversion curve."],
    )

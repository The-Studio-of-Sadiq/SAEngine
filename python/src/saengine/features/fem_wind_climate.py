"""CFD Wind - Wind Climate tab (`femWindClimate`): wind rose, Gumbel fit, return periods, and directional load cases."""

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
    export_fem_file,
    format_json,
    load_settings,
    parse_numbers,
    site_params,
)
from saengine.fem import loads
from saengine.fem.cfd_wind import loads as cfd_loads
from saengine.fem.cfd_wind import service as cfd_service
from saengine.report.clauses import in_force


def _return_period_factor(return_period_years: float) -> float:
    """V_T / V_50 from the Gumbel form of the extreme wind climate (Cook; the probability
    factor used by most codes): ((1 - K·ln(-ln(1 - 1/T))) / (1 - K·ln(-ln(0.98))))^n with
    K = 0.2, n = 0.5. The code pack's own factor, where it gives one, governs design."""
    t = max(float(return_period_years), 1.01)
    k, n = 0.2, 0.5
    return ((1 - k * math.log(-math.log(1 - 1 / t))) / (1 - k * math.log(-math.log(0.98)))) ** n


@feature(
    "femWindClimate.windRose",
    "Directional Wind Rose",
    part="fem",
    fields=[
        text(
            "sectorFreqPct",
            "Sector frequencies (%) starting N clockwise",
            "10, 8, 6, 9, 14, 18, 20, 15",
        ),
        text("sectorMeanMs", "Sector mean speeds (m/s)", "4.2, 3.8, 3.5, 4.0, 5.1, 5.8, 5.4, 4.6"),
    ],
    requires_project=False,
)
def wind_rose(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Analyze directional wind rose sectors and identify prevailing wind direction."""
    freqs = parse_numbers(values["sectorFreqPct"], "sectorFreqPct")
    speeds = parse_numbers(values["sectorMeanMs"], "sectorMeanMs")
    n = min(len(freqs), len(speeds))
    step = 360.0 / n
    rows = [
        {"sectorDeg": i * step, "frequencyPct": freqs[i], "meanSpeedMs": speeds[i]}
        for i in range(n)
    ]
    prev = max(rows, key=lambda r: r["frequencyPct"])
    return result(
        summary={
            "sectors": n,
            "prevailingAngleDeg": prev["sectorDeg"],
            "prevailingFreqPct": prev["frequencyPct"],
        },
        tables=[
            table(
                "Site directional wind rose",
                [
                    ("sectorDeg", "Azimuth", "°"),
                    ("frequencyPct", "Freq", "%"),
                    ("meanSpeedMs", "Mean U", "m/s"),
                ],
                rows,
            )
        ],
        notes=["Use prevailing high-speed sectors to prioritize refined CFD azimuth runs."],
    )


@feature(
    "femWindClimate.terrainCategories",
    "Terrain Categories",
    part="fem",
    fields=[number("heightM", "Evaluation height z", 30.0, unit="m", min=2.0)],
    requires_project=False,
)
def terrain_categories(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare aerodynamic exposure velocity pressure coefficients across standard terrain categories."""
    rows = []
    for cat in ("A", "B", "C", "D"):
        try:
            kz = loads.exposure_coefficient(values["heightM"], cat)
        except KeyError:
            continue  # an exposure the code pack does not define
        rows.append(
            {"exposure": cat, "heightM": values["heightM"], "kz": kz, "speedRatio": math.sqrt(kz)}
        )
    return result(
        summary={"heightM": values["heightM"], "categories": len(rows)},
        tables=[
            table(
                "Exposure velocity pressure factor Kz",
                [
                    ("exposure", "Category"),
                    ("heightM", "z", "m"),
                    ("kz", "Kz"),
                    ("speedRatio", "√Kz"),
                ],
                rows,
            )
        ],
        notes=["Computed via saengine.fem.wind_exposure.exposure_kz."],
    )


@feature(
    "femWindClimate.returnPeriods",
    "Return Period Scaling",
    part="fem",
    fields=[number("v50Ms", "50-year basic wind speed V50", 45.0, unit="m/s", min=10.0)],
    requires_project=False,
)
def return_periods(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Scale 50-year wind speed across 1, 10, 50, 100, 300, 700, and 1700 year return periods."""
    v50 = values["v50Ms"]
    rows = []
    for rp in [1, 10, 50, 100, 300, 700, 1700]:
        factor = _return_period_factor(rp)
        v_rp = v50 * factor
        rows.append({"returnPeriodYr": rp, "factor": factor, "speedMs": v_rp, "qRatio": factor**2})
    return result(
        summary={"v50Ms": v50, "v100Ms": rows[3]["speedMs"], "v700Ms": rows[5]["speedMs"]},
        tables=[
            table(
                "Extreme wind return-period table",
                [
                    ("returnPeriodYr", "MRI (yr)"),
                    ("factor", "Factor"),
                    ("speedMs", "V_MRI", "m/s"),
                    ("qRatio", "(V/V50)²"),
                ],
                rows,
            )
        ],
        notes=["Scaled via saengine.fem.wind_climate.return_period_factor."],
    )


@feature(
    "femWindClimate.applyToFacades",
    "Apply Climate Speed to Facades",
    part="fem",
    fields=[
        number("heightM", "Facade elevation z", 24.0, unit="m", min=2.0),
        select(
            "exposure",
            "Terrain exposure",
            [("B", "B Urban/Suburban"), ("C", "C Open"), ("D", "D Coastal")],
            "B",
        ),
    ],
    requires_project=False,
)
def apply_to_facades(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute elevation-dependent external velocity pressure qz for structural facade zones."""
    _, _, wind_ms, _, imp, _ = site_params(load_settings(ctx))
    rows = []
    for z in [5.0, 10.0, 15.0, 20.0, values["heightM"]]:
        qz = cfd_loads.design_pressure(z, wind_ms, values["exposure"], imp)
        rows.append({"elevationM": z, "basicWindMs": wind_ms, "qzKpa": qz})
    return result(
        summary={"roofQzKpa": rows[-1]["qzKpa"], "windMs": wind_ms, "exposure": values["exposure"]},
        tables=[
            table(
                "Facade design dynamic pressure profile",
                [("elevationM", "z", "m"), ("basicWindMs", "V", "m/s"), ("qzKpa", "q(z)", "kPa")],
                rows,
            )
        ],
        notes=["Computed via saengine.fem.cfd_wind.loads.design_pressure."],
    )


@feature(
    "femWindClimate.loadGeneration",
    "Climate Wind Load Profile",
    part="fem",
    fields=[
        number("heightM", "Building height H", 24.0, unit="m", min=4.0),
        number("widthM", "Loaded facade width B", 18.0, unit="m", min=2.0),
    ],
    requires_project=False,
)
def load_generation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate story-level net wind pressures from active project wind climate parameters."""
    _, _, wind_ms, _, imp, exp = site_params(load_settings(ctx))
    n_st = max(2, round(values["heightM"] / 3.5))
    dz = values["heightM"] / n_st
    rows = []
    total_v = 0.0
    for i in range(1, n_st + 1):
        z = i * dz
        qz = cfd_loads.design_pressure(z, wind_ms, exp, imp)
        force_kn = qz * 1.3 * values["widthM"] * dz
        total_v += force_kn
        rows.append({"story": f"S{i}", "zM": z, "qzKpa": qz, "storyShearKn": force_kn})
    return result(
        summary={"baseShearKn": total_v, "windSpeedMs": wind_ms},
        tables=[
            table(
                "Climate-based lateral wind story forces",
                [
                    ("story", "Level"),
                    ("zM", "z", "m"),
                    ("qzKpa", "q(z)", "kPa"),
                    ("storyShearKn", "F_w", "kN"),
                ],
                rows,
            )
        ],
        notes=[
            "Uses net Cp = 1.3 baseline until CFD surface Cp replaces quasi-steady coefficients."
        ],
    )


@feature(
    "femWindClimate.compareStandards",
    "Compare Climate Methods",
    part="fem",
    fields=[
        number("v50Ms", "Basic 50-yr 3s gust wind speed", 45.0, unit="m/s", min=10.0),
        number("heightM", "Target height z", 30.0, unit="m", min=2.0),
    ],
    requires_project=False,
)
def compare_standards(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare boundary-layer velocity pressure across open, suburban, and rough exposure profiles."""
    rows = []
    for label, cat in [("Coastal Flat", "D"), ("Open Grassland", "C"), ("Suburban / Urban", "B")]:
        try:
            kz = loads.exposure_coefficient(values["heightM"], cat)
            qz = loads.velocity_pressure(values["heightM"], values["v50Ms"], cat, 1.0)
        except KeyError:
            continue  # an exposure the code pack does not define
        rows.append({"exposureClass": label, "kz": kz, "qzKpa": qz})
    return result(
        summary={
            "terrainClasses": len(rows),
            "maxQzKpa": max((r["qzKpa"] for r in rows), default=0.0),
        },
        tables=[
            table(
                "Boundary-layer pressure comparison across terrain classes",
                [("exposureClass", "Terrain Class"), ("kz", "Kz"), ("qzKpa", "q(z)", "kPa")],
                rows,
            )
        ],
        notes=["Sensitivity across terrain classes illustrates exposure importance."],
    )


@feature(
    "femWindClimate.annualMaxima",
    "Annual Maxima Series",
    part="fem",
    fields=[
        text(
            "maximaMs",
            "Annual maximum gust speeds (m/s) CSV",
            "32.1, 35.4, 29.8, 38.2, 41.0, 33.7, 36.5, 31.2, 39.4, 34.0",
        )
    ],
    requires_project=False,
)
def annual_maxima(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute sample mean, standard deviation, and plotting positions of annual wind maxima."""
    vals = sorted(parse_numbers(values["maximaMs"], "maximaMs"))
    n = len(vals)
    mean_v = sum(vals) / n
    std_v = math.sqrt(sum((v - mean_v) ** 2 for v in vals) / max(1, n - 1))
    rows = [
        {"yearRank": i + 1, "speedMs": v, "gringortenP": (i + 1 - 0.44) / (n + 0.12)}
        for i, v in enumerate(vals)
    ]
    return result(
        summary={
            "years": n,
            "meanAnnualMaxMs": mean_v,
            "stdDevMs": std_v,
            "observedPeakMs": vals[-1],
        },
        tables=[
            table(
                "Annual maximum wind series",
                [
                    ("yearRank", "Rank"),
                    ("speedMs", "U_max", "m/s"),
                    ("gringortenP", "Non-Exceed P"),
                ],
                rows,
            )
        ],
        notes=["Gringorten plotting positions prepare data for Type-I Gumbel regression."],
    )


@feature(
    "femWindClimate.directionalAnalysis",
    "Directional Climate Speeds",
    part="fem",
    fields=[
        number("omnidirectionalMs", "Omnidirectional V50 speed", 45.0, unit="m/s", min=10.0),
        text(
            "dirFactors",
            "8-sector directional reduction factors CSV",
            "0.85, 0.88, 0.92, 1.00, 0.95, 0.86, 0.82, 0.84",
        ),
    ],
    requires_project=False,
)
def directional_analysis(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply directional climate multipliers to derive sector-specific design speeds."""
    facs = parse_numbers(values["dirFactors"], "dirFactors")
    step = 360.0 / len(facs)
    rows = [
        {
            "azimuthDeg": i * step,
            "factor": f,
            "speedMs": values["omnidirectionalMs"] * f,
            "qRatio": f**2,
        }
        for i, f in enumerate(facs)
    ]
    return result(
        summary={"sectors": len(rows), "peakSectorSpeedMs": max(r["speedMs"] for r in rows)},
        tables=[
            table(
                "Directional design wind speeds",
                [
                    ("azimuthDeg", "Azimuth", "°"),
                    ("factor", "Kd_θ"),
                    ("speedMs", "V_θ", "m/s"),
                    ("qRatio", "(Kd)²"),
                ],
                rows,
            )
        ],
        notes=["Supports non-uniform directional risk weighting for tall/slender towers."],
    )


@feature(
    "femWindClimate.gumbelFit",
    "Gumbel Extreme-Value Fit",
    part="fem",
    fields=[
        number("sampleMeanMs", "Annual-maxima sample mean", 35.1, unit="m/s", min=5.0),
        number("sampleStdMs", "Annual-maxima sample std dev", 3.8, unit="m/s", min=0.2),
        number("returnPeriodYr", "Target return period", 50.0, unit="yr", min=2.0),
    ],
    requires_project=False,
)
def gumbel_fit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Fit Type-I Extreme Value (Gumbel) distribution by method of moments and predict V_T."""
    alpha_scale = (values["sampleStdMs"] * math.sqrt(6.0)) / math.pi
    u_mode = values["sampleMeanMs"] - 0.57721566 * alpha_scale
    y_t = -math.log(-math.log(1.0 - 1.0 / values["returnPeriodYr"]))
    v_t = u_mode + alpha_scale * y_t
    rows = [
        {
            "modeUMs": u_mode,
            "dispersionAlpha": alpha_scale,
            "reducedVariateYt": y_t,
            "predictedSpeedMs": v_t,
        }
    ]
    return result(
        summary={"predictedSpeedMs": v_t, "modeMs": u_mode, "scaleAlpha": alpha_scale},
        tables=[
            table(
                "Gumbel Type-I extreme wind fit",
                [
                    ("modeUMs", "Mode u", "m/s"),
                    ("dispersionAlpha", "Scale α"),
                    ("reducedVariateYt", "y_T"),
                    ("predictedSpeedMs", "V_T", "m/s"),
                ],
                rows,
            )
        ],
        notes=["Gumbel CDF F(V) = exp(-exp(-(V - u)/α))."],
    )


@feature(
    "femWindClimate.confidenceBands",
    "Return-Period Confidence Bands",
    part="fem",
    fields=[
        number("vTM", "Predicted Gumbel quantile V_T", 45.0, unit="m/s", min=5.0),
        number("sampleStdMs", "Sample std dev s", 3.8, unit="m/s", min=0.2),
        number("nYears", "Record length N", 25.0, unit="yr", min=5.0),
        number("returnPeriodYr", "Target return period T", 50.0, unit="yr", min=2.0),
    ],
    requires_project=False,
)
def confidence_bands(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate ±95% sampling uncertainty interval on fitted extreme wind quantiles."""
    y_t = -math.log(-math.log(1.0 - 1.0 / values["returnPeriodYr"]))
    k_t = (y_t - 0.57721566) * math.sqrt(6.0) / math.pi
    se = values["sampleStdMs"] * math.sqrt((1.0 + 1.14 * k_t + 1.1 * (k_t**2)) / values["nYears"])
    lo = values["vTM"] - 1.96 * se
    hi = values["vTM"] + 1.96 * se
    rows = [{"estimateMs": values["vTM"], "stdErrMs": se, "lower95Ms": lo, "upper95Ms": hi}]
    return result(
        summary={"stdErrorMs": se, "lower95Ms": lo, "upper95Ms": hi},
        tables=[
            table(
                "Extreme wind 95% confidence bounds",
                [
                    ("estimateMs", "V_T", "m/s"),
                    ("stdErrMs", "SE", "m/s"),
                    ("lower95Ms", "Lower 95%", "m/s"),
                    ("upper95Ms", "Upper 95%", "m/s"),
                ],
                rows,
            )
        ],
        notes=["Short station records (< 20 yr) exhibit wide uncertainty bands at high MRI."],
    )


@feature(
    "femWindClimate.stormDuration",
    "Averaging Duration Conversion",
    part="fem",
    fields=[
        number("gust3sMs", "3-second gust wind speed", 45.0, unit="m/s", min=5.0),
        select(
            "targetAvg",
            "Target averaging time",
            [("60s", "1-minute sustained"), ("600s", "10-minute mean"), ("3600s", "Hourly mean")],
            "600s",
        ),
    ],
    requires_project=False,
)
def storm_duration(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert 3-second peak gust speed to 1-min, 10-min, or hourly mean using Durst curve."""
    durst = {"3s": 1.53, "60s": 1.24, "600s": 1.07, "3600s": 1.00}
    target_speed = values["gust3sMs"] * (durst[values["targetAvg"]] / durst["3s"])
    rows = [
        {"duration": k, "durstRatio": r, "speedMs": values["gust3sMs"] * (r / durst["3s"])}
        for k, r in durst.items()
    ]
    return result(
        summary={"convertedSpeedMs": target_speed, "targetDuration": values["targetAvg"]},
        tables=[
            table(
                "Durst averaging-period wind speed curve",
                [("duration", "Period"), ("durstRatio", "V_t/V_3600"), ("speedMs", "Speed", "m/s")],
                rows,
            )
        ],
        notes=["Steady CFD inlet profiles require hourly or 10-min mean meteorological speed."],
    )


@feature(
    "femWindClimate.roughnessLength",
    "Site Roughness Classification",
    part="fem",
    fields=[
        number(
            "z0M", "Specified aerodynamic roughness length z0", 0.3, unit="m", min=0.001, max=3.0
        )
    ],
    requires_project=False,
)
def roughness_length(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Classify aerodynamic surface roughness length z0 into WMO Davenport roughness classes."""
    z0 = values["z0M"]
    if z0 <= 0.01:
        cls = "Sea / Open smooth"
    elif z0 <= 0.05:
        cls = "Open terrain"
    elif z0 <= 0.15:
        cls = "Roughly open"
    elif z0 <= 0.5:
        cls = "Suburban / wooded"
    else:
        cls = "Dense urban / forest"
    if ctx.root is not None:
        proj_z0, src = cfd_service.roughness(load_settings(ctx))
    else:
        proj_z0, src = z0, "user"
    rows = [{"inputZ0M": z0, "projectZ0M": proj_z0, "source": src, "wmoClass": cls}]
    return result(
        summary={"z0M": z0, "projectZ0M": proj_z0, "wmoClass": cls},
        tables=[
            table(
                "Davenport-WMO roughness classification",
                [
                    ("inputZ0M", "z0", "m"),
                    ("projectZ0M", "Project z0", "m"),
                    ("source", "Source"),
                    ("wmoClass", "Class"),
                ],
                rows,
            )
        ],
        notes=["Matches saengine.fem.cfd_wind.service.roughness project resolution."],
    )


@feature(
    "femWindClimate.fetchDistance",
    "Upstream Fetch Transition",
    part="fem",
    fields=[
        number(
            "fetchKm", "Distance from terrain roughness change X_fetch", 1.5, unit="km", min=0.05
        ),
        number("z0NewM", "Downstream roughness z02", 0.3, unit="m", min=0.005),
    ],
    requires_project=False,
)
def fetch_distance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute internal boundary-layer equilibrium height h_IBL after terrain roughness change."""
    x_m = values["fetchKm"] * 1000.0
    h_ibl = 0.28 * values["z0NewM"] * ((x_m / values["z0NewM"]) ** 0.8)
    rows = [{"fetchKm": values["fetchKm"], "z0NewM": values["z0NewM"], "iblHeightM": h_ibl}]
    return result(
        summary={"iblHeightM": h_ibl, "fetchKm": values["fetchKm"]},
        tables=[
            table(
                "Internal boundary-layer growth height",
                [
                    ("fetchKm", "Fetch", "km"),
                    ("z0NewM", "z0_new", "m"),
                    ("iblHeightM", "h_IBL", "m"),
                ],
                rows,
            )
        ],
        notes=["Buildings taller than h_IBL experience upwind smoother-terrain winds aloft."],
    )


@feature(
    "femWindClimate.topographicFactor",
    "Topographic Escarpment Factor",
    part="fem",
    fields=[
        select(
            "featureType",
            "Topographic feature",
            [("ridge", "Ridge"), ("escarpment", "Escarpment"), ("hill", "Hill")],
            "escarpment",
        ),
        number("hillHeightM", "Hill/ridge height H", 25.0, unit="m", min=0.0),
        number("halfLengthM", "Upwind half-height distance Lh", 100.0, unit="m", min=5.0),
        number("distanceM", "Distance from the crest x", 0.0, unit="m"),
        number("evalHeightM", "Evaluation height z", 15.0, unit="m", min=1.0),
        select("exposure", "Exposure", [("A", "A"), ("B", "B"), ("C", "C")], "B"),
    ],
    requires_project=False,
)
def topographic_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute topographic wind speed-up multiplier Kzt at hill crest or escarpment."""
    topo = loads.Topography(
        feature=values["featureType"],
        height=values["hillHeightM"],
        length=values["halfLengthM"],
        distance=abs(values["distanceM"]),
        downwind=values["distanceM"] > 0,
    )
    with in_force(ctx.root):
        terms = loads.topographic_terms(values["evalHeightM"], values["exposure"], topo)
    if terms is None:
        raise FeatureInputError("The code pack has no topographic factor table for this feature.")
    kzt = float(terms["Kzt"])
    rows = [
        {
            "hillHeightM": values["hillHeightM"],
            "halfLengthM": values["halfLengthM"],
            "kzt": kzt,
            "speedGainPct": 100.0 * (math.sqrt(kzt) - 1.0),
        }
    ]
    return result(
        summary={"kzt": kzt, "speedGainPercent": 100.0 * (math.sqrt(kzt) - 1.0)},
        tables=[
            table(
                "Topographic factor Kzt",
                [
                    ("hillHeightM", "H_hill", "m"),
                    ("halfLengthM", "Lh", "m"),
                    ("kzt", "Kzt"),
                    ("speedGainPct", "Speed Gain", "%"),
                ],
                rows,
            )
        ],
        notes=["Computed via saengine.fem.wind_exposure.topographic_kzt."],
    )


@feature(
    "femWindClimate.shelterFactor",
    "Adjacent Shielding Factor",
    part="fem",
    fields=[
        number("buildingHeightM", "Target building height H", 24.0, unit="m", min=2.0),
        number("blockerHeightM", "Upwind shielding building height Hs", 20.0, unit="m", min=0.0),
        number("spacingM", "Clear horizontal gap s", 30.0, unit="m", min=1.0),
    ],
    requires_project=False,
)
def shelter_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate conservative nearby-obstacle aerodynamic shielding ratio (note wake interference)."""
    gap_ratio = values["spacingM"] / max(1.0, values["blockerHeightM"])
    h_ratio = min(1.0, values["blockerHeightM"] / values["buildingHeightM"])
    shelter = max(0.75, 1.0 - 0.25 * h_ratio * math.exp(-0.25 * gap_ratio))
    rows = [{"gapOverHs": gap_ratio, "heightRatio": h_ratio, "shelterFactor": shelter}]
    return result(
        summary={"shelterFactor": shelter, "gapOverBlockerHeight": gap_ratio},
        tables=[
            table(
                "Neighboring obstacle shielding assessment",
                [("gapOverHs", "s/Hs"), ("heightRatio", "Hs/H"), ("shelterFactor", "Ms")],
                rows,
            )
        ],
        notes=[
            "Verify via explicit surrounding massing in CFD, as tall neighbors can also cause Venturi channeling."
        ],
    )


@feature(
    "femWindClimate.directionalCases",
    "Generate Directional Cases",
    part="fem",
    fields=[number("stepDeg", "Azimuth angular step", 22.5, unit="°", min=5.0, max=90.0)],
    requires_project=False,
)
def directional_cases(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate CFD azimuth angle list from step size or project wind configuration."""
    if ctx.root is not None:
        angles, src = cfd_service.directions(load_settings(ctx))
    else:
        n = max(1, round(360.0 / values["stepDeg"]))
        angles = [i * (360.0 / n) for i in range(n)]
        src = "uniformStep"
    rows = [{"caseId": f"dir_{a:05.1f}", "azimuthDeg": a} for a in angles]
    return result(
        summary={"directions": len(angles), "source": src},
        tables=[
            table(
                "Generated CFD directional wind cases",
                [("caseId", "Case"), ("azimuthDeg", "Angle", "°")],
                rows,
            )
        ],
        notes=["Matches directional list generated by saengine.fem.cfd_wind.service.directions."],
    )


@feature(
    "femWindClimate.envelopeCases",
    "Directional Envelope Cases",
    part="fem",
    fields=[
        text(
            "sectorBaseShearsKn",
            "Sector base shears (kN) CSV",
            "420, 510, 640, 590, 480, 390, 530, 610",
        )
    ],
    requires_project=False,
)
def envelope_cases(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Identify governing maximum positive/negative and orthogonal wind envelope directions."""
    vals = parse_numbers(values["sectorBaseShearsKn"], "sectorBaseShearsKn")
    step = 360.0 / len(vals)
    rows = [
        {"angleDeg": i * step, "baseShearKn": v, "ratioToMax": v / max(vals)}
        for i, v in enumerate(vals)
    ]
    gov = max(rows, key=lambda r: r["baseShearKn"])
    return result(
        summary={"governingAngleDeg": gov["angleDeg"], "governingShearKn": gov["baseShearKn"]},
        tables=[
            table(
                "Directional load envelope summary",
                [
                    ("angleDeg", "Angle", "°"),
                    ("baseShearKn", "Base Shear", "kN"),
                    ("ratioToMax", "Ratio"),
                ],
                rows,
            )
        ],
        notes=["Governing CFD sectors drive structural MWFRS load combinations."],
    )


@feature(
    "femWindClimate.fatigueWind",
    "Wind Fatigue Cycle Count",
    part="fem",
    fields=[
        number("designLifeYr", "Cladding / connection design life", 50.0, unit="yr", min=5.0),
        number("weibullScaleMs", "Site Weibull scale c", 5.2, unit="m/s", min=1.0),
        number("thresholdMs", "Fatigue-significant threshold U_th", 12.0, unit="m/s", min=2.0),
    ],
    requires_project=False,
)
def fatigue_wind(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate high-cycle wind fatigue loading hours above stress threshold over design life."""
    p_exc = math.exp(-((values["thresholdMs"] / values["weibullScaleMs"]) ** 1.9))
    hours_life = values["designLifeYr"] * 8760.0 * p_exc
    cycles_est = hours_life * 3600.0 * 0.25
    rows = [{"exceedProb": p_exc, "activeHours": hours_life, "estStressCycles": cycles_est}]
    return result(
        summary={"activeHours": hours_life, "estimatedCycles": int(cycles_est)},
        tables=[
            table(
                "Wind fatigue exposure estimate",
                [
                    ("exceedProb", "P(U>U_th)"),
                    ("activeHours", "Hours"),
                    ("estStressCycles", "Est Cycles (0.25 Hz)"),
                ],
                rows,
            )
        ],
        notes=["Important for facade mullion brackets and vortex-excited slender masts."],
    )


@feature(
    "femWindClimate.serviceWind",
    "Serviceability Wind Speed",
    part="fem",
    fields=[
        number("v50Ms", "50-year ultimate wind speed V50", 45.0, unit="m/s", min=10.0),
        number(
            "serviceMriYr",
            "Serviceability return period (1 or 10 yr)",
            10.0,
            unit="yr",
            min=1.0,
            max=25.0,
        ),
    ],
    requires_project=False,
)
def service_wind(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute frequent serviceability return-period wind speed for drift and acceleration checks."""
    fac = _return_period_factor(round(values["serviceMriYr"]))
    v_sls = values["v50Ms"] * fac
    rows = [
        {
            "mriYr": round(values["serviceMriYr"]),
            "factor": fac,
            "vSlsMs": v_sls,
            "qRatio": fac**2,
        }
    ]
    return result(
        summary={"serviceWindMs": v_sls, "qRatioVs50Yr": fac**2},
        tables=[
            table(
                "Serviceability return-period wind parameters",
                [
                    ("mriYr", "MRI (yr)"),
                    ("factor", "V_SLS/V50"),
                    ("vSlsMs", "V_SLS", "m/s"),
                    ("qRatio", "q_SLS/q50"),
                ],
                rows,
            )
        ],
        notes=["Computed via saengine.fem.wind_climate.return_period_factor."],
    )


@feature(
    "femWindClimate.climateReport",
    "Wind Climate Summary Report",
    part="fem",
    fields=[],
    requires_project=False,
)
def climate_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarize project site wind speed, exposure, roughness z0, and CFD direction schedule."""
    settings = load_settings(ctx)
    _, _, wind_ms, _, imp, exp = site_params(settings)
    z0, z0_src = cfd_service.roughness(settings)
    angles, dir_src = cfd_service.directions(settings)
    rows = [
        {"parameter": "Basic wind speed", "value": f"{wind_ms:.2f} m/s"},
        {"parameter": "Exposure category", "value": str(exp)},
        {"parameter": "Importance factor", "value": str(imp)},
        {"parameter": "Roughness length z0", "value": f"{z0:.3f} m ({z0_src})"},
        {"parameter": "CFD directions", "value": f"{len(angles)} ({dir_src})"},
    ]
    return result(
        summary={"windSpeedMs": wind_ms, "z0M": z0, "directions": len(angles)},
        tables=[
            table(
                "Project wind climate report",
                [("parameter", "Parameter"), ("value", "Setting")],
                rows,
            )
        ],
        notes=["Aggregated directly from project settings and saengine.fem.cfd_wind.service."],
    )


@feature(
    "femWindClimate.windDataExport",
    "Export Wind Climate Table",
    part="fem",
    fields=[text("fileName", "Export filename", "wind_climate_summary.json")],
    requires_project=False,
)
def wind_data_export(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export project site wind climate parameters and return-period table to 08 FEM/exports."""
    settings = load_settings(ctx)
    _, _, wind_ms, _, imp, exp = site_params(settings)
    z0, src = cfd_service.roughness(settings)
    angles, _ = cfd_service.directions(settings)
    payload = {
        "windSpeedMs": wind_ms,
        "exposure": exp,
        "importance": imp,
        "z0M": z0,
        "roughnessSource": src,
        "directions": angles,
    }
    msg = "Preview (no project open)"
    if ctx.root is not None:
        out = export_fem_file(ctx, values["fileName"], format_json(payload))
        msg = str(out)
    return result(
        summary={"exportPath": msg, "directions": len(angles)},
        tables=[
            table(
                "Wind climate export",
                [("key", "Field"), ("value", "Value")],
                [
                    {"key": "Destination", "value": msg},
                    {"key": "Wind Speed (m/s)", "value": f"{wind_ms:.2f}"},
                ],
            )
        ],
        notes=["Written as UTF-8 JSON inside 08 FEM/exports when a project is open."],
    )


@feature(
    "femWindClimate.siteSummary",
    "Site Terrain Summary",
    part="fem",
    fields=[number("roofHeightM", "Building roof height", 24.0, unit="m", min=2.0)],
    requires_project=False,
)
def site_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarize site wind velocity pressure qz at building roof height from project settings."""
    settings = load_settings(ctx)
    _, _, wind_ms, _, imp, exp = site_params(settings)
    qz = loads.velocity_pressure(values["roofHeightM"], wind_ms, str(exp), float(imp))
    rows = [
        {
            "windSpeedMs": wind_ms,
            "exposure": exp,
            "importance": imp,
            "roofHeightM": values["roofHeightM"],
            "qzKpa": qz,
        }
    ]
    return result(
        summary={"roofQzKpa": qz, "windSpeedMs": wind_ms},
        tables=[
            table(
                "Site wind pressure summary",
                [
                    ("windSpeedMs", "V", "m/s"),
                    ("exposure", "Exp"),
                    ("importance", "Iw"),
                    ("roofHeightM", "H", "m"),
                    ("qzKpa", "qz", "kPa"),
                ],
                rows,
            )
        ],
        notes=["Evaluated via saengine.fem.wind.velocity_pressure_qz."],
    )


@feature(
    "femWindClimate.assumptionLog",
    "Climate Assumption Log",
    part="fem",
    fields=[
        text(
            "stationNote",
            "Meteorological source / assumption note",
            "Airport anemometer at 10 m open terrain, adjusted to site z0.",
        )
    ],
    requires_project=False,
)
def assumption_log(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Document meteorological station reference assumptions used for CFD climate scaling."""
    settings = load_settings(ctx)
    z0, src = cfd_service.roughness(settings)
    rows = [
        {"item": "Station adjustment", "detail": values["stationNote"]},
        {"item": "Site z0", "detail": f"{z0:.3f} m ({src})"},
    ]
    return result(
        summary={"z0M": z0, "logged": True},
        tables=[
            table("Climate basis assumption log", [("item", "Topic"), ("detail", "Record")], rows)
        ],
        notes=[values["stationNote"]],
    )


@feature(
    "femWindClimate.sectorTable",
    "Sector Climate Matrix",
    part="fem",
    fields=[number("nSectors", "Number of wind sectors", 12.0, min=4.0, max=36.0)],
    requires_project=False,
)
def sector_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate directional azimuth sector boundaries, midpoints, and baseline dynamic pressures."""
    n = round(values["nSectors"])
    step = 360.0 / n
    _, _, wind_ms, _, imp, exp = site_params(load_settings(ctx))
    q_ref = cfd_loads.design_pressure(20.0, wind_ms, exp, imp)
    rows = [
        {
            "sector": i + 1,
            "startDeg": (i - 0.5) * step % 360.0,
            "midDeg": i * step,
            "endDeg": (i + 0.5) * step % 360.0,
            "qRefKpa": q_ref,
        }
        for i in range(n)
    ]
    return result(
        summary={"sectors": n, "stepDeg": step, "qRefKpa": q_ref},
        tables=[
            table(
                "Directional climate sector matrix",
                [
                    ("sector", "#"),
                    ("startDeg", "From", "°"),
                    ("midDeg", "Center", "°"),
                    ("endDeg", "To", "°"),
                    ("qRefKpa", "q_ref", "kPa"),
                ],
                rows,
            )
        ],
        notes=["Each sector spans ±0.5 angular increment around its nominal CFD inflow azimuth."],
    )

"""CFD Wind - Pollutant Dispersion tab (`femCfdDispersion`): plume source, decay, intake, and exceedance."""

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
    text,
)


def _pasquill_sigma(dist_m: float, stability: str) -> tuple[float, float]:
    """Approximate urban/open Pasquill-Gifford dispersion sigmas (m)."""
    coeffs = {
        "A": (0.22, 0.20),
        "B": (0.16, 0.12),
        "C": (0.11, 0.08),
        "D": (0.08, 0.06),
        "E": (0.06, 0.03),
        "F": (0.04, 0.016),
    }
    ay, az = coeffs.get(stability, (0.08, 0.06))
    x = max(10.0, dist_m)
    return ay * x / math.sqrt(1.0 + 0.0001 * x), az * x / math.sqrt(1.0 + 0.0002 * x)


@feature(
    "femCfdDispersion.addSource",
    "Add Emission Source",
    part="fem",
    fields=[
        text("sourceName", "Source label", "Stack-01"),
        number("xM", "Coordinate X", 0.0, unit="m"),
        number("yM", "Coordinate Y", 0.0, unit="m"),
        number("heightM", "Release elevation z_s", 18.0, unit="m", min=0.0),
        number("rateGs", "Mass emission rate Q", 5.0, unit="g/s", min=0.001),
    ],
    requires_project=False,
)
def add_source(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define passive or buoyant contaminant point source metadata."""
    rows = [
        {
            "source": values["sourceName"],
            "xM": values["xM"],
            "yM": values["yM"],
            "zM": values["heightM"],
            "rateGs": values["rateGs"],
        }
    ]
    return result(
        summary={
            "source": values["sourceName"],
            "rateGs": values["rateGs"],
            "heightM": values["heightM"],
        },
        tables=[
            table(
                "Registered pollutant source",
                [
                    ("source", "Source"),
                    ("xM", "X", "m"),
                    ("yM", "Y", "m"),
                    ("zM", "H", "m"),
                    ("rateGs", "Q", "g/s"),
                ],
                rows,
            )
        ],
        notes=["Ready for scalar transport equation injection."],
    )


@feature(
    "femCfdDispersion.emissionRate",
    "Emission Rate",
    part="fem",
    fields=[
        number("volFlowM3s", "Exhaust volumetric flow rate V_dot", 8.0, unit="m³/s", min=0.01),
        number("exhaustConcMgM3", "Exhaust concentration C_exh", 450.0, unit="mg/m³", min=0.01),
    ],
    requires_project=False,
)
def emission_rate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert exhaust volumetric flow and concentration to mass emission rate Q."""
    q_gs = values["volFlowM3s"] * values["exhaustConcMgM3"] / 1000.0
    q_kghr = q_gs * 3.6
    rows = [
        {
            "volFlowM3s": values["volFlowM3s"],
            "concMgM3": values["exhaustConcMgM3"],
            "massRateGs": q_gs,
            "massRateKghr": q_kghr,
        }
    ]
    return result(
        summary={"massRateGs": q_gs, "massRateKghr": q_kghr},
        tables=[
            table(
                "Emission source strength",
                [
                    ("volFlowM3s", "Flow", "m³/s"),
                    ("concMgM3", "C_exh", "mg/m³"),
                    ("massRateGs", "Q", "g/s"),
                    ("massRateKghr", "Q", "kg/hr"),
                ],
                rows,
            )
        ],
        notes=["Q = V_dot · C_exh used as inlet scalar mass source."],
    )


@feature(
    "femCfdDispersion.sourceHeight",
    "Effective Source Height",
    part="fem",
    fields=[
        number("stackHeightM", "Physical stack height hs", 16.0, unit="m", min=0.5),
        number("stackDiameterM", "Internal stack diameter d", 0.8, unit="m", min=0.05),
        number("exitSpeedMs", "Plume exit velocity vs", 12.0, unit="m/s", min=0.1),
        number("windSpeedMs", "Wind speed at stack top u", 6.0, unit="m/s", min=0.5),
    ],
    requires_project=False,
)
def source_height(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute momentum plume rise Δh and effective release height H_eff."""
    dh = 3.0 * values["stackDiameterM"] * values["exitSpeedMs"] / values["windSpeedMs"]
    h_eff = values["stackHeightM"] + dh
    rows = [{"stackM": values["stackHeightM"], "momentumRiseM": dh, "effectiveHeightM": h_eff}]
    return result(
        summary={"effectiveHeightM": h_eff, "plumeRiseM": dh},
        tables=[
            table(
                "Effective stack height calculation",
                [
                    ("stackM", "hs", "m"),
                    ("momentumRiseM", "Δh", "m"),
                    ("effectiveHeightM", "H_eff", "m"),
                ],
                rows,
            )
        ],
        notes=["Briggs momentum rise Δh = 3 d (vs / u)."],
    )


@feature(
    "femCfdDispersion.releaseTiming",
    "Release Timing",
    part="fem",
    fields=[
        select(
            "mode",
            "Release temporal mode",
            [
                ("continuous", "Continuous steady"),
                ("puff", "Instantaneous puff"),
                ("intermittent", "Finite duration pulse"),
            ],
            "continuous",
        ),
        number("durationS", "Release duration T_rel", 600.0, unit="s", min=1.0),
        number("totalMassKg", "Total released mass M", 25.0, unit="kg", min=0.01),
    ],
    requires_project=False,
)
def release_timing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate average release rate Q_avg across release mode and duration."""
    q_gs = (values["totalMassKg"] * 1000.0) / values["durationS"]
    rows = [
        {
            "mode": values["mode"],
            "durationS": values["durationS"],
            "massKg": values["totalMassKg"],
            "avgRateGs": q_gs,
        }
    ]
    return result(
        summary={"mode": values["mode"], "averageRateGs": q_gs},
        tables=[
            table(
                "Temporal emission schedule",
                [
                    ("mode", "Mode"),
                    ("durationS", "Duration", "s"),
                    ("massKg", "Mass", "kg"),
                    ("avgRateGs", "Q_avg", "g/s"),
                ],
                rows,
            )
        ],
        notes=["Instantaneous puffs require transient scalar transport with Courant control."],
    )


@feature(
    "femCfdDispersion.windDriven",
    "Wind-Driven Dispersion",
    part="fem",
    fields=[
        number("rateGs", "Emission rate Q", 10.0, unit="g/s", min=0.001),
        number("windSpeedMs", "Wind speed u", 5.0, unit="m/s", min=0.5),
        number("effectiveHeightM", "Effective source height H", 18.0, unit="m", min=0.0),
        select(
            "stability",
            "Pasquill stability class",
            [
                ("B", "B Unstable"),
                ("C", "C Slightly unstable"),
                ("D", "D Neutral"),
                ("E", "E Stable"),
            ],
            "D",
        ),
    ],
    requires_project=False,
)
def wind_driven(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute centerline ground-level plume concentration across downwind distances."""
    q_mg = values["rateGs"] * 1000.0
    u = values["windSpeedMs"]
    h = values["effectiveHeightM"]
    rows = []
    peak_c = 0.0
    for x in [50.0, 100.0, 200.0, 400.0, 800.0]:
        sy, sz = _pasquill_sigma(x, values["stability"])
        c_mgm3 = (q_mg / (2.0 * math.pi * u * sy * sz)) * 2.0 * math.exp(-0.5 * (h / sz) ** 2)
        peak_c = max(peak_c, c_mgm3)
        rows.append({"distM": x, "sigmaYM": sy, "sigmaZM": sz, "groundConcMgM3": c_mgm3})
    return result(
        summary={"peakGroundMgM3": peak_c, "stability": values["stability"]},
        tables=[
            table(
                "Gaussian plume downwind centerline concentration",
                [
                    ("distM", "x", "m"),
                    ("sigmaYM", "σy", "m"),
                    ("sigmaZM", "σz", "m"),
                    ("groundConcMgM3", "C(x,0,0)", "mg/m³"),
                ],
                rows,
            )
        ],
        notes=["Evaluated with ground-reflection Gaussian plume model."],
    )


@feature(
    "femCfdDispersion.buoyantPlume",
    "Buoyant Plume Rise",
    part="fem",
    fields=[
        number("heatFluxKw", "Stack sensible heat release Qh", 450.0, unit="kW", min=1.0),
        number("windSpeedMs", "Wind speed u", 5.0, unit="m/s", min=0.5),
        number("distanceM", "Downwind distance x", 200.0, unit="m", min=10.0),
    ],
    requires_project=False,
)
def buoyant_plume(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate Briggs thermal buoyancy flux parameter F_b and buoyant plume rise Δh."""
    fb = 0.0089 * values["heatFluxKw"]
    dh = 1.6 * (fb ** (1.0 / 3.0)) * (values["distanceM"] ** (2.0 / 3.0)) / values["windSpeedMs"]
    rows = [{"buoyancyFluxM4s3": fb, "plumeRiseM": dh, "distanceM": values["distanceM"]}]
    return result(
        summary={"buoyancyFluxM4s3": fb, "plumeRiseM": dh},
        tables=[
            table(
                "Thermal plume rise calculation",
                [
                    ("buoyancyFluxM4s3", "Fb", "m⁴/s³"),
                    ("plumeRiseM", "Δh", "m"),
                    ("distanceM", "x", "m"),
                ],
                rows,
            )
        ],
        notes=["Briggs neutral-atmosphere buoyant rise formula."],
    )


@feature(
    "femCfdDispersion.speciesDecay",
    "Species Decay",
    part="fem",
    fields=[
        number("halfLifeS", "Species atmospheric half-life t1/2", 1800.0, unit="s", min=1.0),
        number("distanceM", "Travel distance x", 500.0, unit="m", min=1.0),
        number("windSpeedMs", "Advective wind speed u", 5.0, unit="m/s", min=0.5),
    ],
    requires_project=False,
)
def species_decay(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute first-order chemical or radioactive decay survival fraction along wind path."""
    t_travel = values["distanceM"] / values["windSpeedMs"]
    k_decay = math.log(2.0) / values["halfLifeS"]
    surv = math.exp(-k_decay * t_travel)
    rows = [{"travelTimeS": t_travel, "decayRate1s": k_decay, "remainingFraction": surv}]
    return result(
        summary={"remainingFraction": surv, "decayRatePerS": k_decay, "travelTimeS": t_travel},
        tables=[
            table(
                "First-order species decay",
                [
                    ("travelTimeS", "t_adv", "s"),
                    ("decayRate1s", "λ", "1/s"),
                    ("remainingFraction", "C/C0"),
                ],
                rows,
            )
        ],
        notes=["Exponential attenuation C/C0 = exp(-λ t)."],
    )


@feature(
    "femCfdDispersion.terrainEffects",
    "Terrain Effects",
    part="fem",
    fields=[
        number("hillHeightM", "Hill or ridge height H", 30.0, unit="m", min=0.0),
        number("hillSlope", "Upwind hill slope H/L", 0.2, min=0.0, max=1.0),
        number("baseSigmaZM", "Flat-terrain vertical spread σz", 12.0, unit="m", min=0.5),
    ],
    requires_project=False,
)
def terrain_effects(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate plume trajectory compression and turbulence-enhanced dispersion over topography."""
    speedup = 1.0 + 1.6 * values["hillSlope"]
    eff_sigma_z = values["baseSigmaZM"] * (1.0 + 0.5 * values["hillSlope"])
    rows = [
        {
            "speedupFactor": speedup,
            "effectiveSigmaZM": eff_sigma_z,
            "ridgeClearanceFactor": max(0.5, 1.0 - 0.5 * values["hillSlope"]),
        }
    ]
    return result(
        summary={"windSpeedup": speedup, "effectiveSigmaZM": eff_sigma_z},
        tables=[
            table(
                "Topographic plume modification",
                [
                    ("speedupFactor", "U/U0"),
                    ("effectiveSigmaZM", "σz_eff", "m"),
                    ("ridgeClearanceFactor", "H_eff Ratio"),
                ],
                rows,
            )
        ],
        notes=["Slope-induced speed-up decreases streamline height over crests."],
    )


@feature(
    "femCfdDispersion.concentrationMap",
    "Concentration Map",
    part="fem",
    fields=[
        number("rateGs", "Emission rate Q", 5.0, unit="g/s", min=0.001),
        number("windSpeedMs", "Wind speed u", 4.0, unit="m/s", min=0.5),
        number("receptorHeightM", "Receptor height z", 1.5, unit="m", min=0.0),
        number("sourceHeightM", "Source height H", 12.0, unit="m", min=0.5),
    ],
    requires_project=False,
)
def concentration_map(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a downwind (x, y) horizontal concentration grid at breathing height."""
    q_mg = values["rateGs"] * 1000.0
    rows = []
    for x in [50.0, 100.0, 200.0]:
        sy, sz = _pasquill_sigma(x, "D")
        for y in [0.0, 10.0, 25.0]:
            vert = math.exp(
                -0.5 * ((values["receptorHeightM"] - values["sourceHeightM"]) / sz) ** 2
            ) + math.exp(-0.5 * ((values["receptorHeightM"] + values["sourceHeightM"]) / sz) ** 2)
            c = (
                (q_mg / (2.0 * math.pi * values["windSpeedMs"] * sy * sz))
                * math.exp(-0.5 * (y / sy) ** 2)
                * vert
            )
            rows.append({"xM": x, "yM": y, "concMgM3": c})
    max_c = max(r["concMgM3"] for r in rows)
    return result(
        summary={"gridPoints": len(rows), "maxConcMgM3": max_c},
        tables=[
            table(
                "Horizontal concentration contour grid",
                [("xM", "x", "m"), ("yM", "y", "m"), ("concMgM3", "C", "mg/m³")],
                rows,
            )
        ],
        notes=["Evaluated at neutral stability class D."],
    )


@feature(
    "femCfdDispersion.doseEstimate",
    "Dose Estimate",
    part="fem",
    fields=[
        number("concMgM3", "Ambient concentration C", 12.0, unit="mg/m³", min=0.0),
        number("exposureMin", "Exposure duration", 30.0, unit="min", min=0.1),
        number("inhalationLmin", "Inhalation rate", 20.0, unit="L/min", min=1.0),
    ],
    requires_project=False,
)
def dose_estimate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute cumulative time-integrated concentration exposure and inhaled mass dose."""
    dose_mg = values["concMgM3"] * (values["inhalationLmin"] / 1000.0) * values["exposureMin"]
    ct_mgmin = values["concMgM3"] * values["exposureMin"]
    rows = [{"concMgM3": values["concMgM3"], "ctMgMinM3": ct_mgmin, "inhaledMg": dose_mg}]
    return result(
        summary={"inhaledDoseMg": dose_mg, "ctIndexMgMinM3": ct_mgmin},
        tables=[
            table(
                "Receptor exposure dose summary",
                [
                    ("concMgM3", "C", "mg/m³"),
                    ("ctMgMinM3", "C·t", "mg·min/m³"),
                    ("inhaledMg", "Dose", "mg"),
                ],
                rows,
            )
        ],
        notes=["Accounts for ventilation breathing rate over incident window."],
    )


@feature(
    "femCfdDispersion.exceedanceCheck",
    "Exceedance Check",
    part="fem",
    fields=[
        number("predictedMgM3", "Predicted receptor concentration", 8.5, unit="mg/m³", min=0.0),
        number("twaLimitMgM3", "Allowable exposure threshold", 10.0, unit="mg/m³", min=0.01),
    ],
    requires_project=False,
)
def exceedance_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check predicted ambient concentration against occupational or ambient threshold."""
    ratio = values["predictedMgM3"] / values["twaLimitMgM3"]
    ok = ratio <= 1.0
    rows = [
        {
            "predictedMgM3": values["predictedMgM3"],
            "limitMgM3": values["twaLimitMgM3"],
            "ratio": ratio,
            "ok": ok,
        }
    ]
    return result(
        summary={"utilisation": ratio, "passes": ok},
        tables=[
            table(
                "Dispersion threshold compliance check",
                [
                    ("predictedMgM3", "Predicted", "mg/m³"),
                    ("limitMgM3", "Limit", "mg/m³"),
                    ("ratio", "C/C_lim"),
                    ("ok", "Compliant"),
                ],
                rows,
            )
        ],
        notes=["Verify sensitive receptors including fresh-air HVAC intakes."],
    )


@feature(
    "femCfdDispersion.dispersionReport",
    "Dispersion Report",
    part="fem",
    fields=[
        number("rateGs", "Emission rate Q", 6.0, unit="g/s", min=0.01),
        number("windSpeedMs", "Design wind speed u", 4.5, unit="m/s", min=0.5),
        number("limitMgM3", "Allowable concentration limit", 5.0, unit="mg/m³", min=0.01),
    ],
    requires_project=False,
)
def dispersion_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Synthesize downwind concentration attenuation and safe setback summary."""
    rows = []
    safe_x = None
    for x in [25.0, 50.0, 100.0, 200.0, 500.0]:
        sy, sz = _pasquill_sigma(x, "D")
        c = (values["rateGs"] * 1000.0) / (math.pi * values["windSpeedMs"] * sy * sz)
        ok = c <= values["limitMgM3"]
        if ok and safe_x is None:
            safe_x = x
        rows.append({"distanceM": x, "concMgM3": c, "withinLimit": ok})
    return result(
        summary={"safeSetbackM": safe_x or 500.0, "maxConcMgM3": rows[0]["concMgM3"]},
        tables=[
            table(
                "Dispersion impact assessment table",
                [
                    ("distanceM", "Distance", "m"),
                    ("concMgM3", "Peak C", "mg/m³"),
                    ("withinLimit", "OK"),
                ],
                rows,
            )
        ],
        notes=["Ground-level centerline worst-case summary (H_eff = 0 conservative screening)."],
    )


@feature(
    "femCfdDispersion.gasProperties",
    "Gas Properties",
    part="fem",
    fields=[
        number("molarMassGmol", "Gas molecular weight M", 44.01, unit="g/mol", min=2.0),
        number("tempC", "Gas temperature T", 25.0, unit="°C", min=-50.0),
        number("schmidtNumber", "Turbulent Schmidt number Sc_t", 0.7, min=0.2, max=1.5),
    ],
    requires_project=False,
)
def gas_properties(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute ideal-gas density and relative buoyancy density ratio against ambient air."""
    t_k = values["tempC"] + 273.15
    rho_g = (101325.0 * (values["molarMassGmol"] / 1000.0)) / (8.3145 * t_k)
    rho_air = 1.184
    rel = rho_g / rho_air
    regime = (
        "Dense gas (negatively buoyant)"
        if rel > 1.05
        else ("Buoyant" if rel < 0.95 else "Neutrally buoyant")
    )
    rows = [
        {
            "densityKgM3": rho_g,
            "relativeToAir": rel,
            "schmidt": values["schmidtNumber"],
            "regime": regime,
        }
    ]
    return result(
        summary={"gasDensityKgM3": rho_g, "relativeDensity": rel, "regime": regime},
        tables=[
            table(
                "Tracer gas physical properties",
                [
                    ("densityKgM3", "ρ_gas", "kg/m³"),
                    ("relativeToAir", "ρ/ρ_air"),
                    ("schmidt", "Sc_t"),
                    ("regime", "Behavior"),
                ],
                rows,
            )
        ],
        notes=["Dense gases slump along ground terrain rather than dispersing upward."],
    )


@feature(
    "femCfdDispersion.particulateSize",
    "Particulate Size",
    part="fem",
    fields=[
        number(
            "diameterUm", "Aerodynamic particle diameter d_p", 10.0, unit="μm", min=0.1, max=500.0
        ),
        number("particleDensityKgM3", "Particle density ρ_p", 2500.0, unit="kg/m³", min=200.0),
    ],
    requires_project=False,
)
def particulate_size(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Stokes gravitational terminal settling velocity for suspended particulates."""
    d_m = values["diameterUm"] * 1e-6
    mu_air = 1.81e-5
    vs = (values["particleDensityKgM3"] * (d_m**2) * 9.81) / (18.0 * mu_air)
    rows = [
        {
            "diameterUm": values["diameterUm"],
            "settlingVelMs": vs,
            "pmClass": "PM2.5"
            if values["diameterUm"] <= 2.5
            else ("PM10" if values["diameterUm"] <= 10.0 else "Coarse"),
        }
    ]
    return result(
        summary={"settlingVelocityMs": vs, "diameterUm": values["diameterUm"]},
        tables=[
            table(
                "Particulate Stokes settling velocity",
                [("diameterUm", "dp", "μm"), ("settlingVelMs", "vs", "m/s"), ("pmClass", "Class")],
                rows,
            )
        ],
        notes=[
            "Sub-10 μm aerosols follow fluid streamlines closely with minimal gravitational drift."
        ],
    )


@feature(
    "femCfdDispersion.depositionVelocity",
    "Deposition Velocity",
    part="fem",
    fields=[
        number("settlingVelMs", "Gravitational settling velocity vs", 0.008, unit="m/s", min=0.0),
        number("aerodynamicResSm", "Aerodynamic resistance ra", 45.0, unit="s/m", min=1.0),
        number("surfaceResSm", "Canopy/surface resistance rc", 120.0, unit="s/m", min=1.0),
    ],
    requires_project=False,
)
def deposition_velocity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute dry-deposition transfer velocity vd using resistance-in-series model."""
    vd = values["settlingVelMs"] + 1.0 / (values["aerodynamicResSm"] + values["surfaceResSm"])
    rows = [
        {"raSm": values["aerodynamicResSm"], "rcSm": values["surfaceResSm"], "depositionVelMs": vd}
    ]
    return result(
        summary={"depositionVelocityMs": vd},
        tables=[
            table(
                "Dry surface deposition velocity",
                [("raSm", "ra", "s/m"), ("rcSm", "rc", "s/m"), ("depositionVelMs", "vd", "m/s")],
                rows,
            )
        ],
        notes=["Flux to ground surface equals vd · C(z=0)."],
    )


@feature(
    "femCfdDispersion.chemicalReaction",
    "Chemical Reaction",
    part="fem",
    fields=[
        number("rateConstantPerS", "Reaction rate constant k1", 0.002, unit="1/s", min=0.0),
        number("ozonePpb", "Background oxidant level", 40.0, unit="ppb", min=0.0),
        number("residenceS", "Plume travel time", 180.0, unit="s", min=1.0),
    ],
    requires_project=False,
)
def chemical_reaction(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate reactive pollutant conversion ratio via Damköhler number."""
    da = values["rateConstantPerS"] * values["residenceS"]
    converted_pct = 100.0 * (1.0 - math.exp(-da))
    rows = [{"damkohler": da, "convertedPct": converted_pct, "remainingPct": 100.0 - converted_pct}]
    return result(
        summary={"damkohlerNumber": da, "convertedPercent": converted_pct},
        tables=[
            table(
                "Atmospheric reaction conversion",
                [
                    ("damkohler", "Da"),
                    ("convertedPct", "Converted", "%"),
                    ("remainingPct", "Unreacted", "%"),
                ],
                rows,
            )
        ],
        notes=["Damköhler number Da = k · τ quantifies reaction vs transport timescales."],
    )


@feature(
    "femCfdDispersion.hvacIntake",
    "HVAC Intake Dilution",
    part="fem",
    fields=[
        number("exhaustRateGs", "Exhaust contaminant mass rate Q", 2.5, unit="g/s", min=0.001),
        number(
            "distanceM",
            "Stretched-string distance S from exhaust to intake",
            12.0,
            unit="m",
            min=1.0,
        ),
        number("exhaustFlowM3s", "Exhaust airflow V_exh", 4.0, unit="m³/s", min=0.1),
        number("windSpeedMs", "Reference wind speed U", 4.0, unit="m/s", min=0.5),
    ],
    requires_project=False,
)
def hvac_intake(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate rooftop HVAC intake minimum dilution factor D using Wilson-Chui separation formula."""
    c_exh = (values["exhaustRateGs"] * 1000.0) / values["exhaustFlowM3s"]
    d_min = (
        math.sqrt(values["windSpeedMs"] / values["exhaustFlowM3s"]) * values["distanceM"] + 1.0
    ) ** 2
    c_intake = c_exh / d_min
    rows = [{"exhaustConcMgM3": c_exh, "dilutionFactor": d_min, "intakeConcMgM3": c_intake}]
    return result(
        summary={"dilutionFactor": d_min, "intakeConcMgM3": c_intake},
        tables=[
            table(
                "HVAC fresh-air intake re-entrainment check",
                [
                    ("exhaustConcMgM3", "C_exh", "mg/m³"),
                    ("dilutionFactor", "D_min"),
                    ("intakeConcMgM3", "C_intake", "mg/m³"),
                ],
                rows,
            )
        ],
        notes=["Higher dilution factors prevent exhaust re-ingestion into ventilation intakes."],
    )


@feature(
    "femCfdDispersion.facadeLeakage",
    "Facade Leakage",
    part="fem",
    fields=[
        number("deltaPPa", "Wind-driven facade ΔP", 45.0, unit="Pa", min=0.0),
        number("leakageAreaCm2M2", "Effective leakage area per m²", 1.5, unit="cm²/m²", min=0.1),
        number("facadeAreaM2", "Envelope facade area", 400.0, unit="m²", min=1.0),
        number("outdoorConcMgM3", "Exterior plume concentration", 10.0, unit="mg/m³", min=0.0),
    ],
    requires_project=False,
)
def facade_leakage(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate wind-driven contaminant infiltration airflow across porous building envelope."""
    a_eff = (values["leakageAreaCm2M2"] * 1e-4) * values["facadeAreaM2"]
    q_in = 0.65 * a_eff * math.sqrt(2.0 * values["deltaPPa"] / 1.225)
    mass_in_mgs = q_in * values["outdoorConcMgM3"]
    rows = [{"effectiveAreaM2": a_eff, "infiltrationM3s": q_in, "ingressMgS": mass_in_mgs}]
    return result(
        summary={"infiltrationFlowM3s": q_in, "pollutantIngressMgS": mass_in_mgs},
        tables=[
            table(
                "Wind-driven envelope infiltration",
                [
                    ("effectiveAreaM2", "A_eff", "m²"),
                    ("infiltrationM3s", "Q_in", "m³/s"),
                    ("ingressMgS", "Mass Flux", "mg/s"),
                ],
                rows,
            )
        ],
        notes=["Orifice equation Q = Cd A √(2ΔP/ρ) with discharge coefficient Cd = 0.65."],
    )


@feature(
    "femCfdDispersion.airExchange",
    "Air Exchange (ACH)",
    part="fem",
    fields=[
        number("infiltrationM3s", "Air exchange flow rate Q", 0.45, unit="m³/s", min=0.001),
        number("roomVolumeM3", "Zone interior volume V", 1200.0, unit="m³", min=10.0),
    ],
    requires_project=False,
)
def air_exchange(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert zone infiltration flow rate to air changes per hour (ACH) and purge time."""
    ach = 3600.0 * values["infiltrationM3s"] / values["roomVolumeM3"]
    tau_hr = 1.0 / ach
    rows = [
        {
            "flowM3s": values["infiltrationM3s"],
            "volumeM3": values["roomVolumeM3"],
            "ach": ach,
            "timeConstantHr": tau_hr,
        }
    ]
    return result(
        summary={"ach": ach, "timeConstantHr": tau_hr},
        tables=[
            table(
                "Zone air exchange metrics",
                [
                    ("flowM3s", "Q", "m³/s"),
                    ("volumeM3", "Volume", "m³"),
                    ("ach", "ACH", "1/hr"),
                    ("timeConstantHr", "τ", "hr"),
                ],
                rows,
            )
        ],
        notes=["95% indoor purge requires roughly 3τ time constants."],
    )


@feature(
    "femCfdDispersion.thresholdLimits",
    "Threshold Limits",
    part="fem",
    fields=[
        number("twa8hMgM3", "8-hr TWA limit", 2.0, unit="mg/m³", min=0.001),
        number("stel15mMgM3", "15-min STEL limit", 6.0, unit="mg/m³", min=0.001),
        number("idlhMgM3", "Acute IDLH ceiling", 50.0, unit="mg/m³", min=0.01),
    ],
    requires_project=False,
)
def threshold_limits(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate tiered toxicological concentration alarm thresholds."""
    rows = [
        {"tier": "Chronic / 8-hr TWA", "limitMgM3": values["twa8hMgM3"]},
        {"tier": "Short-term / 15-min STEL", "limitMgM3": values["stel15mMgM3"]},
        {"tier": "Emergency / IDLH", "limitMgM3": values["idlhMgM3"]},
    ]
    return result(
        summary={
            "twaMgM3": values["twa8hMgM3"],
            "stelMgM3": values["stel15mMgM3"],
            "idlhMgM3": values["idlhMgM3"],
        },
        tables=[
            table(
                "Configured exposure threshold bands",
                [("tier", "Band"), ("limitMgM3", "Threshold", "mg/m³")],
                rows,
            )
        ],
        notes=["Threshold hierarchy drives automated exceedance zone mapping."],
    )


@feature(
    "femCfdDispersion.evacuationZone",
    "Evacuation Zone",
    part="fem",
    fields=[
        number("rateGs", "Accidental release rate Q", 50.0, unit="g/s", min=0.1),
        number("windSpeedMs", "Wind speed u", 4.0, unit="m/s", min=0.5),
        number("thresholdMgM3", "Evacuation action threshold", 15.0, unit="mg/m³", min=0.01),
    ],
    requires_project=False,
)
def evacuation_zone(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Determine maximum downwind hazard setback distance for emergency isolation perimeter."""
    limit_x = 0.0
    max_half_w = 0.0
    q_mg = values["rateGs"] * 1000.0
    for x in range(25, 2001, 25):
        sy, sz = _pasquill_sigma(float(x), "D")
        c0 = q_mg / (math.pi * values["windSpeedMs"] * sy * sz)
        if c0 >= values["thresholdMgM3"]:
            limit_x = float(x)
            hw = sy * math.sqrt(2.0 * math.log(c0 / values["thresholdMgM3"]))
            max_half_w = max(max_half_w, hw)
    rows = [
        {
            "downwindReachM": limit_x,
            "maxHalfWidthM": max_half_w,
            "plumeFootprintHa": (math.pi * 0.5 * limit_x * max_half_w) / 10000.0,
        }
    ]
    return result(
        summary={"downwindSetbackM": limit_x, "maxHalfWidthM": max_half_w},
        tables=[
            table(
                "Emergency plume exclusion zone",
                [
                    ("downwindReachM", "Downwind Reach", "m"),
                    ("maxHalfWidthM", "Half Width", "m"),
                    ("plumeFootprintHa", "Area", "ha"),
                ],
                rows,
            )
        ],
        notes=["Neutral-stability ground-release bounding contour."],
    )

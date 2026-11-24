"""CFD Wind - Turbulence tab (`femCfdTurbulence`): RANS/LES/DES parameters, wall y+, k/ε/ω, and thermal."""

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
from saengine.fem.cfd_wind import case as cfd_case


@feature(
    "femCfdTurbulence.modelSelect",
    "Turbulence Model Selection",
    part="fem",
    fields=[
        select(
            "model",
            "Turbulence closure",
            [
                ("kOmegaSST", "k-ω SST"),
                ("realizableKE", "Realizable k-ε"),
                ("SA", "Spalart-Allmaras"),
                ("DDES", "k-ω SST DDES"),
            ],
            "kOmegaSST",
        ),
    ],
    requires_project=False,
)
def model_select(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure turbulence model equations and default model constant Cμ / a1."""
    info = {
        "kOmegaSST": (2, 0.31, "Captures adverse pressure gradient & corner separation"),
        "realizableKE": (2, 0.09, "Broad urban flow transport"),
        "SA": (1, 0.41, "Fast single-equation eddy viscosity"),
        "DDES": (2, 0.31, "Hybrid RANS wall / LES detached wake"),
    }
    eqns, coeff, role = info[values["model"]]
    rows = [
        {"model": values["model"], "transportEqns": eqns, "structCoeff": coeff, "strength": role}
    ]
    return result(
        summary={"model": values["model"], "transportEquations": eqns},
        tables=[
            table(
                "Selected turbulence closure",
                [
                    ("model", "Model"),
                    ("transportEqns", "Eqns"),
                    ("structCoeff", "Coeff"),
                    ("strength", "Role"),
                ],
                rows,
            )
        ],
        notes=["k-ω SST balances near-wall ω robustness with free-stream k-ε insensitivity."],
    )


@feature(
    "femCfdTurbulence.blendFactor",
    "SST Blending F1 / F2",
    part="fem",
    fields=[
        number("wallDistM", "Wall distance d", 0.25, unit="m", min=1e-4),
        number("kM2s2", "Turbulent kinetic energy k", 1.2, unit="m²/s²", min=1e-5),
        number("omega1s", "Specific dissipation ω", 18.0, unit="1/s", min=0.01),
    ],
    requires_project=False,
)
def blend_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Menter SST blending argument arg2 and F2 shear-stress limiter factor."""
    arg2 = max(
        2.0 * math.sqrt(values["kM2s2"]) / (0.09 * values["omega1s"] * values["wallDistM"]),
        500.0 * cfd_case.NU / ((values["wallDistM"] ** 2) * values["omega1s"]),
    )
    f2 = math.tanh(arg2**2)
    rows = [
        {
            "wallDistM": values["wallDistM"],
            "arg2": arg2,
            "f2": f2,
            "regime": "Near-wall k-ω" if f2 > 0.5 else "Free-stream k-ε",
        }
    ]
    return result(
        summary={"f2Blend": f2, "arg2": arg2},
        tables=[
            table(
                "Menter SST F2 blending evaluation",
                [
                    ("wallDistM", "y", "m"),
                    ("arg2", "arg2"),
                    ("f2", "F2"),
                    ("regime", "Active Branch"),
                ],
                rows,
            )
        ],
        notes=["F2 transitions smoothly from 1 at the wall to 0 in outer free stream."],
    )


@feature(
    "femCfdTurbulence.curvatureCorrection",
    "Curvature Correction",
    part="fem",
    fields=[
        number("strainRate1s", "Strain rate magnitude S", 12.0, unit="1/s", min=0.01),
        number("vorticity1s", "Vorticity magnitude Ω", 18.0, unit="1/s", min=0.01),
        checkbox("enabled", "Enable Spalart-Shur rotation/curvature correction", True),
    ],
    requires_project=False,
)
def curvature_correction(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate Spalart-Shur streamline curvature production multiplier fr1."""
    r_star = values["strainRate1s"] / values["vorticity1s"]
    fr1 = min(1.25, max(0.0, 2.0 * r_star / (1.0 + r_star))) if values["enabled"] else 1.0
    rows = [{"sOverOmega": r_star, "fr1Multiplier": fr1, "active": values["enabled"]}]
    return result(
        summary={"fr1Multiplier": fr1, "strainOverVorticity": r_star},
        tables=[
            table(
                "Streamline curvature production modifier",
                [("sOverOmega", "S/Ω"), ("fr1Multiplier", "fr1"), ("active", "Enabled")],
                rows,
            )
        ],
        notes=["Improves prediction of curved vortex cores separating from curved roofs."],
    )


@feature(
    "femCfdTurbulence.transitionModel",
    "Laminar-Turbulent Transition",
    part="fem",
    fields=[
        number(
            "turbulenceIntensityPct",
            "Free-stream turbulence intensity Tu",
            8.0,
            unit="%",
            min=0.1,
            max=40.0,
        ),
        number("reynoldsNumber", "Local characteristic Reynolds Re", 5.0e6, min=100.0),
    ],
    requires_project=False,
)
def transition_model(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute critical momentum-thickness transition Reynolds number Re_θc."""
    tu = values["turbulenceIntensityPct"]
    re_theta_c = (
        1173.51 - 589.428 * tu + 0.2196 / (tu**2) if tu <= 1.3 else 331.5 / ((tu - 0.5658) ** 0.671)
    )
    re_theta_c = max(40.0, re_theta_c)
    rows = [
        {"tuPct": tu, "reThetaCrit": re_theta_c, "fullyTurbulent": values["reynoldsNumber"] > 1e5}
    ]
    return result(
        summary={"reThetaCrit": re_theta_c, "tuPercent": tu},
        tables=[
            table(
                "Langtry-Menter transition onset criterion",
                [
                    ("tuPct", "Tu", "%"),
                    ("reThetaCrit", "Re_θc"),
                    ("fullyTurbulent", "High-Re Regime"),
                ],
                rows,
            )
        ],
        notes=["Building Reynolds numbers > 1e6 are predominantly turbulent at upwind corners."],
    )


@feature(
    "femCfdTurbulence.inletProfile",
    "Inlet Turbulence Profile",
    part="fem",
    fields=[
        number("z0M", "Roughness length z0", 0.3, unit="m", min=0.001),
        number("heightM", "Reference height H_ref", 10.0, unit="m", min=1.0),
        number("uRefMs", "Reference wind speed U_ref", cfd_case.UREF, unit="m/s", min=1.0),
    ],
    requires_project=False,
)
def inlet_profile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute inflow ABL turbulence parameters u*, k, ε, and ω using engine helper."""
    bl = cfd_case.boundary_layer(values["z0M"], values["heightM"], uref=values["uRefMs"])
    rows = [{"parameter": k, "value": v} for k, v in bl.items()]
    return result(
        summary=bl,
        tables=[
            table(
                "Inlet ABL turbulence boundary values",
                [("parameter", "Parameter"), ("value", "Value")],
                rows,
            )
        ],
        notes=["Computed via saengine.fem.cfd_wind.case.boundary_layer."],
    )


@feature(
    "femCfdTurbulence.turbulenceIntensity",
    "Turbulence Intensity Setup",
    part="fem",
    fields=[
        number("uMeanMs", "Mean wind speed U", 18.0, unit="m/s", min=0.5),
        number(
            "intensityPct", "Longitudinal turbulence intensity I", 16.0, unit="%", min=0.5, max=60.0
        ),
    ],
    requires_project=False,
)
def turbulence_intensity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert turbulence intensity I (%) and mean speed U into turbulent kinetic energy k."""
    i_frac = values["intensityPct"] / 100.0
    k = 1.5 * ((values["uMeanMs"] * i_frac) ** 2)
    rows = [{"uMeanMs": values["uMeanMs"], "intensityPct": values["intensityPct"], "kM2s2": k}]
    return result(
        summary={"kM2s2": k, "intensityPct": values["intensityPct"]},
        tables=[
            table(
                "TKE from isotropic turbulence intensity",
                [
                    ("uMeanMs", "U", "m/s"),
                    ("intensityPct", "I", "%"),
                    ("kM2s2", "k = 1.5(UI)²", "m²/s²"),
                ],
                rows,
            )
        ],
        notes=["Assumes isotropic fluctuations u' ≈ v' ≈ w'."],
    )


@feature(
    "femCfdTurbulence.lengthScale",
    "Turbulence Length Scale",
    part="fem",
    fields=[
        number("heightM", "Reference elevation z", 24.0, unit="m", min=1.0),
        number("z0M", "Roughness length z0", 0.3, unit="m", min=0.001),
        number("kM2s2", "Turbulent kinetic energy k", 3.5, unit="m²/s²", min=0.01),
    ],
    requires_project=False,
)
def length_scale(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute atmospheric mixing length scale l_mix = κ (z + z0) and derived ε, ω."""
    l_mix = cfd_case.KAPPA * (values["heightM"] + values["z0M"])
    eps = (cfd_case.CMU**0.75) * (values["kM2s2"] ** 1.5) / l_mix
    omega = math.sqrt(values["kM2s2"]) / ((cfd_case.CMU**0.25) * l_mix)
    rows = [{"lMixM": l_mix, "epsilonM2s3": eps, "omega1s": omega}]
    return result(
        summary={"mixingLengthM": l_mix, "epsilonM2s3": eps, "omega1s": omega},
        tables=[
            table(
                "Turbulence length scale conversions",
                [("lMixM", "l_mix", "m"), ("epsilonM2s3", "ε", "m²/s³"), ("omega1s", "ω", "1/s")],
                rows,
            )
        ],
        notes=["Uses von Karman constant κ = 0.41 and Cμ = 0.09."],
    )


@feature(
    "femCfdTurbulence.gustProfile",
    "Inflow Gust Turbulence",
    part="fem",
    fields=[
        number("sigmaUMs", "Longitudinal RMS velocity σ_u", 2.8, unit="m/s", min=0.1),
        number("sigmaVMs", "Lateral RMS velocity σ_v", 2.1, unit="m/s", min=0.1),
        number("sigmaWMs", "Vertical RMS velocity σ_w", 1.4, unit="m/s", min=0.1),
    ],
    requires_project=False,
)
def gust_profile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute anisotropic atmospheric kinetic energy k = 0.5 (σu² + σv² + σw²)."""
    k_aniso = 0.5 * (values["sigmaUMs"] ** 2 + values["sigmaVMs"] ** 2 + values["sigmaWMs"] ** 2)
    rows = [
        {
            "sigmaUMs": values["sigmaUMs"],
            "sigmaVMs": values["sigmaVMs"],
            "sigmaWMs": values["sigmaWMs"],
            "kM2s2": k_aniso,
        }
    ]
    return result(
        summary={"kAnisotropicM2s2": k_aniso},
        tables=[
            table(
                "Anisotropic wind fluctuation TKE",
                [
                    ("sigmaUMs", "σu", "m/s"),
                    ("sigmaVMs", "σv", "m/s"),
                    ("sigmaWMs", "σw", "m/s"),
                    ("kM2s2", "k", "m²/s²"),
                ],
                rows,
            )
        ],
        notes=["Neutral ABL typically follows σu : σv : σw ≈ 1.0 : 0.75 : 0.52."],
    )


@feature(
    "femCfdTurbulence.wallFunction",
    "Wall Function Assignment",
    part="fem",
    fields=[
        select(
            "surface",
            "Boundary patch type",
            [("building", "Smooth concrete/glass facade"), ("ground", "Rough ABL ground")],
            "building",
        ),
        number("yPlus", "Wall first-cell y+", 55.0, min=0.5),
    ],
    requires_project=False,
)
def wall_function(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select OpenFOAM nut/k/omega wall functions matched to patch roughness and y+."""
    if values["surface"] == "ground":
        nut_bc = "nutkAtmRoughWallFunction"
    elif values["yPlus"] < 5.0:
        nut_bc = "nutLowReWallFunction"
    else:
        nut_bc = "nutkWallFunction"
    rows = [
        {
            "patch": values["surface"],
            "nutBC": nut_bc,
            "omegaBC": "omegaWallFunction",
            "kBC": "kqRWallFunction",
        }
    ]
    return result(
        summary={"patch": values["surface"], "nutBC": nut_bc},
        tables=[
            table(
                "Wall function patch assignment",
                [
                    ("patch", "Surface"),
                    ("nutBC", "nut BC"),
                    ("omegaBC", "omega BC"),
                    ("kBC", "k BC"),
                ],
                rows,
            )
        ],
        notes=["Use nutkAtmRoughWallFunction on ground patches to prevent horizontal ABL decay."],
    )


@feature(
    "femCfdTurbulence.wallRoughness",
    "Wall Roughness Height",
    part="fem",
    fields=[
        number("z0M", "Ground aerodynamic roughness z0", 0.3, unit="m", min=0.001),
        number("firstCellHeightM", "Ground first-cell height Δz1", 0.5, unit="m", min=0.02),
        number("cs", "Roughness constant Cs", 0.5, min=0.1, max=1.0),
    ],
    requires_project=False,
)
def wall_roughness(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify Blocken wall-function consistency condition zp > ks on rough terrain."""
    ks = (9.793 * values["z0M"]) / values["cs"]
    zp = 0.5 * values["firstCellHeightM"]
    ok = zp >= ks
    rows = [{"ksM": ks, "zpM": zp, "consistencyMet": ok, "minRequiredDz1M": 2.0 * ks}]
    return result(
        summary={"ksM": ks, "zpM": zp, "passesBlockenCheck": ok},
        tables=[
            table(
                "Rough-wall zp >= ks consistency check",
                [
                    ("ksM", "ks", "m"),
                    ("zpM", "zp = Δz1/2", "m"),
                    ("consistencyMet", "zp >= ks"),
                    ("minRequiredDz1M", "Min Δz1", "m"),
                ],
                rows,
            )
        ],
        notes=["Maintain zp >= ks or use a modified ABL k-ε/SST formulation to avoid speed decay."],
    )


@feature(
    "femCfdTurbulence.yPlusTarget",
    "Target y+ Solver Sizing",
    part="fem",
    fields=[
        number("targetYPlus", "Desired wall y+", 50.0, min=0.5, max=300.0),
        number("uTauMs", "Friction velocity uτ", 0.85, unit="m/s", min=0.05),
    ],
    requires_project=False,
)
def y_plus_target(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Solve required first prism-cell thickness Δy1 from target y+ and friction velocity."""
    zp = values["targetYPlus"] * cfd_case.NU / values["uTauMs"]
    dy1_mm = 2.0 * zp * 1000.0
    rows = [
        {"targetYPlus": values["targetYPlus"], "uTauMs": values["uTauMs"], "firstLayerMm": dy1_mm}
    ]
    return result(
        summary={"requiredFirstLayerMm": dy1_mm, "targetYPlus": values["targetYPlus"]},
        tables=[
            table(
                "First-cell thickness for target y+",
                [
                    ("targetYPlus", "Target y+"),
                    ("uTauMs", "uτ", "m/s"),
                    ("firstLayerMm", "Δy1", "mm"),
                ],
                rows,
            )
        ],
        notes=["Δy1 = 2 · y+ · ν / uτ."],
    )


@feature(
    "femCfdTurbulence.boundaryLayers",
    "Near-Wall Turbulence Layers",
    part="fem",
    fields=[
        number("delta99M", "Expected boundary layer thickness δ", 1.2, unit="m", min=0.02),
        number("firstCellMm", "First prism thickness", 3.0, unit="mm", min=0.05),
        number("nLayers", "Prism layer count", 10.0, min=1.0, max=30.0),
    ],
    requires_project=False,
)
def boundary_layers(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check prism stack coverage against aerodynamic wall boundary-layer thickness δ."""
    n = round(values["nLayers"])
    r = 1.2
    h_prism_m = (values["firstCellMm"] / 1000.0) * (r**n - 1.0) / (r - 1.0)
    cov_pct = 100.0 * h_prism_m / values["delta99M"]
    rows = [{"prismHeightM": h_prism_m, "delta99M": values["delta99M"], "coveragePct": cov_pct}]
    return result(
        summary={"prismHeightM": h_prism_m, "coveragePercent": cov_pct},
        tables=[
            table(
                "Boundary-layer prism coverage",
                [
                    ("prismHeightM", "H_prism", "m"),
                    ("delta99M", "δ99", "m"),
                    ("coveragePct", "Coverage", "%"),
                ],
                rows,
            )
        ],
        notes=["Prism stack should avoid abrupt volume jumps > 3x to outer hex cells."],
    )


@feature(
    "femCfdTurbulence.dissipationRate",
    "Dissipation Rate (ε / ω)",
    part="fem",
    fields=[
        number("kM2s2", "Turbulent kinetic energy k", 2.4, unit="m²/s²", min=1e-4),
        number("eddyViscosityRatio", "Turbulent viscosity ratio νt/ν", 500.0, min=1.0),
    ],
    requires_project=False,
)
def dissipation_rate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute consistent ε and ω from TKE k and ambient eddy viscosity ratio νt/ν."""
    nu_t = values["eddyViscosityRatio"] * cfd_case.NU
    eps = cfd_case.CMU * (values["kM2s2"] ** 2) / nu_t
    omega = values["kM2s2"] / nu_t
    rows = [{"nuTM2s": nu_t, "epsilonM2s3": eps, "omega1s": omega}]
    return result(
        summary={"epsilonM2s3": eps, "omega1s": omega, "nuTM2s": nu_t},
        tables=[
            table(
                "Turbulence dissipation rate conversion",
                [("nuTM2s", "νt", "m²/s"), ("epsilonM2s3", "ε", "m²/s³"), ("omega1s", "ω", "1/s")],
                rows,
            )
        ],
        notes=["Consistent initialization ensures smooth initial residual slope."],
    )


@feature(
    "femCfdTurbulence.viscosityRatio",
    "Eddy Viscosity Ratio",
    part="fem",
    fields=[
        number("kM2s2", "Turbulent kinetic energy k", 2.5, unit="m²/s²", min=1e-4),
        number("epsilonM2s3", "Dissipation rate ε", 0.35, unit="m²/s³", min=1e-6),
    ],
    requires_project=False,
)
def viscosity_ratio(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate turbulent-to-molecular kinematic viscosity ratio νt / ν."""
    nu_t = cfd_case.CMU * (values["kM2s2"] ** 2) / values["epsilonM2s3"]
    ratio = nu_t / cfd_case.NU
    rows = [{"nuTM2s": nu_t, "nuM2s": cfd_case.NU, "viscosityRatio": ratio}]
    return result(
        summary={"viscosityRatio": ratio, "eddyViscosityM2s": nu_t},
        tables=[
            table(
                "Turbulent viscosity ratio νt/ν",
                [("nuTM2s", "νt", "m²/s"), ("nuM2s", "ν", "m²/s"), ("viscosityRatio", "νt/ν")],
                rows,
            )
        ],
        notes=["Outdoor ABL winds typically exhibit νt/ν between 10² and 10⁵."],
    )


@feature(
    "femCfdTurbulence.productionLimiter",
    "Stagnation Production Limiter",
    part="fem",
    fields=[
        number("kM2s2", "Local TKE k", 2.0, unit="m²/s²", min=1e-4),
        number("omega1s", "Local ω", 10.0, unit="1/s", min=0.01),
        number("rawPk", "Unclipped production Pk", 120.0, unit="m²/s³", min=0.0),
    ],
    requires_project=False,
)
def production_limiter(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply Menter SST stagnation production cap Pk <= 10 · β* · k · ω."""
    cap = 10.0 * cfd_case.CMU * values["kM2s2"] * values["omega1s"]
    clipped = min(values["rawPk"], cap)
    rows = [
        {
            "rawPk": values["rawPk"],
            "sstCap": cap,
            "appliedPk": clipped,
            "clipped": values["rawPk"] > cap,
        }
    ]
    return result(
        summary={"appliedPk": clipped, "capPk": cap},
        tables=[
            table(
                "Menter SST stagnation production limiter",
                [
                    ("rawPk", "Raw Pk"),
                    ("sstCap", "10 β* k ω"),
                    ("appliedPk", "Limited Pk"),
                    ("clipped", "Active"),
                ],
                rows,
            )
        ],
        notes=["Prevents unphysical TKE build-up at windward stagnation points."],
    )


@feature(
    "femCfdTurbulence.kineticEnergy",
    "Turbulent Kinetic Energy Check",
    part="fem",
    fields=[
        number("z0M", "Roughness length z0", 0.3, unit="m", min=0.001),
        number("ustarMs", "ABL friction velocity u*", 1.1, unit="m/s", min=0.05),
    ],
    requires_project=False,
)
def kinetic_energy(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate equilibrium ABL turbulent kinetic energy k = u*² / √Cμ."""
    k_eq = (values["ustarMs"] ** 2) / math.sqrt(cfd_case.CMU)
    rows = [{"ustarMs": values["ustarMs"], "cMu": cfd_case.CMU, "kEqM2s2": k_eq}]
    return result(
        summary={"equilibriumKM2s2": k_eq},
        tables=[
            table(
                "Equilibrium ABL TKE",
                [("ustarMs", "u*", "m/s"), ("cMu", "Cμ"), ("kEqM2s2", "k_eq", "m²/s²")],
                rows,
            )
        ],
        notes=["Richards-Hoxey constant-shear TKE identity matches cfd_wind.case.boundary_layer."],
    )


@feature(
    "femCfdTurbulence.lesSetup",
    "LES Subgrid-Scale Setup",
    part="fem",
    fields=[
        select(
            "sgsModel",
            "Subgrid-scale SGS closure",
            [
                ("WALE", "WALE (Wall-Adapting Local Eddy)"),
                ("Smagorinsky", "Dynamic Smagorinsky"),
                ("kEqn", "One-equation kEqn"),
            ],
            "WALE",
        ),
        number("cellSizeM", "Wake cell size Δ", 0.3, unit="m", min=0.02),
    ],
    requires_project=False,
)
def les_setup(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure Large Eddy Simulation SGS model constants and cutoff wavenumber."""
    c_map = {"WALE": 0.325, "Smagorinsky": 0.168, "kEqn": 0.094}
    cw = c_map[values["sgsModel"]]
    cutoff = math.pi / values["cellSizeM"]
    rows = [{"sgsModel": values["sgsModel"], "modelConstant": cw, "cutoffWavenumber": cutoff}]
    return result(
        summary={"sgsModel": values["sgsModel"], "modelConstant": cw, "cutoffWavenumber": cutoff},
        tables=[
            table(
                "LES subgrid model parameters",
                [
                    ("sgsModel", "SGS Model"),
                    ("modelConstant", "Constant"),
                    ("cutoffWavenumber", "κ_c", "1/m"),
                ],
                rows,
            )
        ],
        notes=["WALE reproduces proper zero eddy viscosity at laminar walls without damping."],
    )


@feature(
    "femCfdTurbulence.desDetached",
    "DES / DDES Hybrid Switch",
    part="fem",
    fields=[
        number("lRansM", "RANS length scale l_RANS = √k/(β*ω)", 2.2, unit="m", min=0.05),
        number("maxCellM", "Max local grid spacing Δ_max", 0.5, unit="m", min=0.02),
        number("cDes", "DES constant C_DES", 0.61, min=0.4, max=0.8),
    ],
    requires_project=False,
)
def des_detached(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate DES hybrid length scale min(l_RANS, C_DES · Δ_max) switching between RANS and LES."""
    l_les = values["cDes"] * values["maxCellM"]
    l_des = min(values["lRansM"], l_les)
    branch = "LES Mode (Wake)" if l_les < values["lRansM"] else "RANS Mode (Boundary Layer)"
    rows = [{"lRansM": values["lRansM"], "cDesDeltaM": l_les, "lDesM": l_des, "activeMode": branch}]
    return result(
        summary={"lDesM": l_des, "activeMode": branch},
        tables=[
            table(
                "Detached Eddy Simulation mode switch",
                [
                    ("lRansM", "l_RANS", "m"),
                    ("cDesDeltaM", "C_DES·Δ", "m"),
                    ("lDesM", "l_DES", "m"),
                    ("activeMode", "Mode"),
                ],
                rows,
            )
        ],
        notes=["DDES shielding prevents grid-induced premature separation inside wall layers."],
    )


@feature(
    "femCfdTurbulence.filterWidth",
    "LES Filter Width",
    part="fem",
    fields=[
        number("dxM", "Cell Δx", 0.25, unit="m", min=0.01),
        number("dyM", "Cell Δy", 0.25, unit="m", min=0.01),
        number("dzM", "Cell Δz", 0.40, unit="m", min=0.01),
    ],
    requires_project=False,
)
def filter_width(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute cubic-root volume filter width Δ = (Δx Δy Δz)^(1/3) and max-edge Δ_max."""
    delta_vol = (values["dxM"] * values["dyM"] * values["dzM"]) ** (1.0 / 3.0)
    delta_max = max(values["dxM"], values["dyM"], values["dzM"])
    aspect = delta_max / min(values["dxM"], values["dyM"], values["dzM"])
    rows = [{"cubeRootM": delta_vol, "maxEdgeM": delta_max, "aspectRatio": aspect}]
    return result(
        summary={"cubeRootFilterM": delta_vol, "maxEdgeFilterM": delta_max, "aspectRatio": aspect},
        tables=[
            table(
                "Subgrid filter width metrics",
                [
                    ("cubeRootM", "Δ_vol", "m"),
                    ("maxEdgeM", "Δ_max", "m"),
                    ("aspectRatio", "Aspect Ratio"),
                ],
                rows,
            )
        ],
        notes=["Keep wake cells nearly isotropic (aspect < 3) for accurate LES energy cascade."],
    )


@feature(
    "femCfdTurbulence.realizabilityConstraint",
    "Realizability Constraint",
    part="fem",
    fields=[
        number("kM2s2", "Turbulent kinetic energy k", 3.0, unit="m²/s²", min=1e-4),
        number("strainRate1s", "Local strain invariant S", 25.0, unit="1/s", min=0.1),
        number("epsilonM2s3", "Dissipation rate ε", 2.5, unit="m²/s³", min=1e-5),
    ],
    requires_project=False,
)
def realizability_constraint(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Durbin realizable time-scale bound suppressing stagnation eddy-viscosity spike."""
    t_std = values["kM2s2"] / values["epsilonM2s3"]
    t_real = 1.0 / (math.sqrt(6.0) * cfd_case.CMU * values["strainRate1s"])
    t_bound = min(t_std, t_real)
    rows = [
        {
            "standardTimeS": t_std,
            "realizableCapS": t_real,
            "boundedTimeS": t_bound,
            "capped": t_real < t_std,
        }
    ]
    return result(
        summary={"boundedTimeScaleS": t_bound, "isCapped": t_real < t_std},
        tables=[
            table(
                "Durbin realizability time-scale bound",
                [
                    ("standardTimeS", "k/ε", "s"),
                    ("realizableCapS", "T_cap", "s"),
                    ("boundedTimeS", "Applied T", "s"),
                    ("capped", "Limited"),
                ],
                rows,
            )
        ],
        notes=["Eliminates excessive windward roof turbulence viscosity in k-ε simulations."],
    )


@feature(
    "femCfdTurbulence.thermalTransport",
    "Buoyant Thermal Stratification",
    part="fem",
    fields=[
        number("prandtlTurb", "Turbulent Prandtl number Pr_t", 0.85, min=0.5, max=1.2),
        number("deltaTC", "Air-surface temperature difference ΔT", 4.0, unit="°C"),
        number("heightScaleM", "Boundary-layer height scale H", 50.0, unit="m", min=1.0),
        number("windSpeedMs", "Mean wind speed U", 3.0, unit="m/s", min=0.5),
    ],
    requires_project=False,
)
def thermal_transport(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate bulk Richardson number Ri_b quantifying thermal vs mechanical turbulence."""
    ri_b = (9.81 * (values["deltaTC"] / 298.15) * values["heightScaleM"]) / (
        values["windSpeedMs"] ** 2
    )
    regime = (
        "Forced convection (neutral)"
        if abs(ri_b) < 0.1
        else ("Mixed convection" if abs(ri_b) < 1.0 else "Buoyancy dominated")
    )
    rows = [{"riBulk": ri_b, "prandtlT": values["prandtlTurb"], "regime": regime}]
    return result(
        summary={"bulkRichardson": ri_b, "regime": regime},
        tables=[
            table(
                "Atmospheric thermal stratification check",
                [("riBulk", "Ri_b"), ("prandtlT", "Pr_t"), ("regime", "Convection Regime")],
                rows,
            )
        ],
        notes=["Design wind storms (high U) typically yield |Ri_b| << 0.1 (neutrally stratified)."],
    )

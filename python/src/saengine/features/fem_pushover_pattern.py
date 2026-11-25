"""Pushover - Lateral Pattern tab: uniform, triangular, modal, custom, adaptive, and vector export patterns."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.fem_common import (
    export_fem_file,
    load_bim,
    load_settings,
    optional_osmodel,
    parse_numbers,
    site_params,
)
from saengine.fem import loads
from saengine.report.clauses import in_force


def _level_heights(ctx: FeatureContext, n_fallback: int = 4) -> list[tuple[str, float]]:
    bim = load_bim(ctx)
    if bim and getattr(bim, "stories", None):
        pts = [
            (str(s.name), float(s.elevation) / 1000.0)
            for s in bim.stories
            if float(s.elevation) > 0
        ]
        if pts:
            return pts
    return [(f"Level {i + 1}", 3.2 * (i + 1)) for i in range(n_fallback)]


@feature(
    "femPushoverPattern.uniformPattern",
    "Uniform Pattern",
    part="fem",
    fields=[
        number("baseShearKn", "Reference total base shear", 500.0, unit="kN", min=1.0),
        number("storeys", "Storeys", 4, min=1, max=60),
    ],
    requires_project=False,
)
def uniform_pattern(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Distribute lateral pushover forces uniformly proportional to floor mass."""
    levels = _level_heights(ctx, int(values["storeys"]))
    f_each = values["baseShearKn"] / len(levels)
    rows = [
        {"level": nm, "elevM": z, "weightShare": 1.0 / len(levels), "forceKn": f_each}
        for nm, z in levels
    ]
    return result(
        summary={"levels": len(rows), "forcePerFloorKn": f_each},
        tables=[
            table(
                "Uniform lateral load pattern",
                [
                    ("level", "Level"),
                    ("elevM", "Elev", "m"),
                    ("weightShare", "Share"),
                    ("forceKn", "Fx", "kN"),
                ],
                rows,
            )
        ],
        notes=["Uniform acceleration pattern proportional to floor seismic weights mi."],
    )


@feature(
    "femPushoverPattern.triangularPattern",
    "Triangular Pattern",
    part="fem",
    fields=[
        number("baseShearKn", "Reference base shear", 500.0, unit="kN", min=1.0),
        number("storeys", "Storeys", 4, min=1, max=60),
    ],
    requires_project=False,
)
def triangular_pattern(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Distribute lateral pushover forces linearly with floor height above base."""
    levels = _level_heights(ctx, int(values["storeys"]))
    denom = sum(z for _, z in levels) or 1.0
    rows = [
        {"level": nm, "elevM": z, "share": z / denom, "forceKn": values["baseShearKn"] * z / denom}
        for nm, z in levels
    ]
    return result(
        summary={"levels": len(rows), "roofForceKn": rows[-1]["forceKn"]},
        tables=[
            table(
                "Inverted-triangular pushover pattern",
                [
                    ("level", "Level"),
                    ("elevM", "Elev", "m"),
                    ("share", "Share"),
                    ("forceKn", "Fx", "kN"),
                ],
                rows,
            )
        ],
        notes=["Linear height distribution k = 1.0."],
    )


@feature(
    "femPushoverPattern.firstModePattern",
    "First Mode Pattern",
    part="fem",
    fields=[
        number("baseShearKn", "Reference base shear", 500.0, unit="kN", min=1.0),
        number("storeys", "Storeys", 4, min=1, max=60),
    ],
    requires_project=False,
)
def first_mode_pattern(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Distribute lateral pushover load in proportion to first-mode shape m·φ1."""
    levels = _level_heights(ctx, int(values["storeys"]))
    h_top = max(z for _, z in levels) or 1.0
    phis = [math.sin(0.5 * math.pi * z / h_top) for _, z in levels]
    denom = sum(phis) or 1.0
    rows = [
        {"level": nm, "elevM": z, "phi1": p, "forceKn": values["baseShearKn"] * p / denom}
        for (nm, z), p in zip(levels, phis, strict=True)
    ]
    return result(
        summary={"levels": len(rows), "roofForceKn": rows[-1]["forceKn"]},
        tables=[
            table(
                "First-mode shape pushover pattern",
                [
                    ("level", "Level"),
                    ("elevM", "Elev", "m"),
                    ("phi1", "φ1"),
                    ("forceKn", "Fx", "kN"),
                ],
                rows,
            )
        ],
        notes=["Uses quarter-sine fundamental shear-flexure mode shape φ1(z) = sin(πz/2H)."],
    )


@feature(
    "femPushoverPattern.customPattern",
    "Custom Pattern",
    part="fem",
    fields=[
        text("weights", "Floor force weights (bottom to top)", "1, 2, 3, 4"),
        number("baseShearKn", "Total base shear", 500.0, unit="kN", min=1.0),
    ],
    requires_project=False,
)
def custom_pattern(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Normalize a user-defined storey force pattern vector to the target base shear."""
    ws = parse_numbers(values["weights"], "Pattern weights")
    tot = sum(ws) or 1.0
    rows = [
        {
            "storey": f"Level {i + 1}",
            "rawWeight": w,
            "normShare": w / tot,
            "forceKn": values["baseShearKn"] * w / tot,
        }
        for i, w in enumerate(ws)
    ]
    return result(
        summary={"levels": len(rows), "totalForceKn": sum(r["forceKn"] for r in rows)},
        tables=[
            table(
                "Custom normalized pushover pattern",
                [
                    ("storey", "Level"),
                    ("rawWeight", "Weight"),
                    ("normShare", "Share"),
                    ("forceKn", "Fx", "kN"),
                ],
                rows,
            )
        ],
        notes=["User weights normalized so Σ Fx = V_base."],
    )


@feature(
    "femPushoverPattern.storyForce",
    "Story Force",
    part="fem",
    fields=[
        number("storeyMassTonnes", "Floor mass mi", 150.0, unit="t", min=1.0),
        number("modeOrdinate", "Mode shape ordinate φi", 0.75, min=0.0, max=1.5),
        number("accelG", "Spectral acceleration", 0.30, unit="g", min=0.01),
    ],
    requires_project=False,
)
def story_force(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute modal lateral storey force Fi = mi · φi · Sa."""
    f_kn = values["storeyMassTonnes"] * 9.80665 * values["modeOrdinate"] * values["accelG"]
    rows = [
        {
            "massT": values["storeyMassTonnes"],
            "phi": values["modeOrdinate"],
            "saG": values["accelG"],
            "forceKn": f_kn,
        }
    ]
    return result(
        summary={"storeyForceKn": f_kn},
        tables=[
            table(
                "Modal storey force",
                [
                    ("massT", "Mass", "t"),
                    ("phi", "φi"),
                    ("saG", "Sa", "g"),
                    ("forceKn", "Fi", "kN"),
                ],
                rows,
            )
        ],
        notes=["Fi = m_i · φ_i · Sa · g."],
    )


@feature(
    "femPushoverPattern.massFactor",
    "Mass Factor",
    part="fem",
    fields=[
        text("massesTonnes", "Storey masses [t] (bottom to top)", "180, 180, 175, 140"),
        text("heightsM", "Storey heights [m]", "3.2, 6.4, 9.6, 12.8"),
    ],
    requires_project=False,
)
def mass_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Weight lateral pushover vector by storey seismic mass × elevation."""
    ms = parse_numbers(values["massesTonnes"], "Masses")
    hs = parse_numbers(values["heightsM"], "Heights")
    n = min(len(ms), len(hs))
    mh = [ms[i] * hs[i] for i in range(n)]
    tot = sum(mh) or 1.0
    rows = [
        {"level": f"Level {i + 1}", "massT": ms[i], "elevM": hs[i], "factor": mh[i] / tot}
        for i in range(n)
    ]
    return result(
        summary={"levels": n, "totalMassTonnes": sum(ms[:n])},
        tables=[
            table(
                "Mass-weighted pushover factors",
                [
                    ("level", "Level"),
                    ("massT", "Mass", "t"),
                    ("elevM", "z", "m"),
                    ("factor", "Factor"),
                ],
                rows,
            )
        ],
        notes=["Distributes lateral load proportional to m_i · h_i."],
    )


@feature(
    "femPushoverPattern.heightExponent",
    "Height Exponent",
    part="fem",
    fields=[
        number("periodS", "Fundamental period T1", 0.9, unit="s", min=0.05),
        number("storeys", "Storeys", 5, min=1, max=60),
    ],
    requires_project=False,
)
def height_exponent(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute height distribution exponent k(T1) and resulting normalized lateral profile."""
    t = values["periodS"]
    k = 1.0 if t <= 0.5 else (2.0 if t >= 2.5 else 1.0 + 0.5 * (t - 0.5))
    levels = _level_heights(ctx, int(values["storeys"]))
    whk = [z**k for _, z in levels]
    tot = sum(whk) or 1.0
    rows = [
        {"level": nm, "elevM": z, "share": w / tot} for (nm, z), w in zip(levels, whk, strict=True)
    ]
    return result(
        summary={"periodS": t, "exponentK": k},
        tables=[
            table(
                f"Height-exponent distribution (k = {k:.2f})",
                [("level", "Level"), ("elevM", "Elev", "m"), ("share", "Share")],
                rows,
            )
        ],
        notes=["k varies linearly from 1.0 at T<=0.5 s to 2.0 at T>=2.5 s for higher-mode whip."],
    )


@feature(
    "femPushoverPattern.patternScale",
    "Pattern Scale",
    part="fem",
    fields=[
        number("referenceBaseShearKn", "Reference base shear Vref", 1000.0, unit="kN", min=1.0),
        text("rawVector", "Unscaled floor forces [kN]", "50, 100, 150, 200"),
    ],
    requires_project=False,
)
def pattern_scale(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Scale any lateral force vector uniformly to match a target reference base shear."""
    vec = parse_numbers(values["rawVector"], "Force vector")
    tot = sum(vec) or 1.0
    sf = values["referenceBaseShearKn"] / tot
    rows = [{"level": f"Level {i + 1}", "rawKn": v, "scaledKn": v * sf} for i, v in enumerate(vec)]
    return result(
        summary={"scaleFactor": sf, "scaledTotalKn": sum(r["scaledKn"] for r in rows)},
        tables=[
            table(
                "Scaled pushover load vector",
                [("level", "Level"), ("rawKn", "Raw", "kN"), ("scaledKn", "Scaled", "kN")],
                rows,
            )
        ],
        notes=["Applies uniform multiplier Vref / ΣFi to the lateral pattern."],
    )


@feature(
    "femPushoverPattern.stepSize",
    "Step Size",
    part="fem",
    fields=[
        number("targetRoofDispMm", "Target roof displacement", 240.0, unit="mm", min=5.0),
        number("stepIncrementMm", "Step increment Δu", 4.0, unit="mm", min=0.2),
    ],
    requires_project=False,
)
def step_size(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate total displacement-control steps and drift resolution per step."""
    steps = math.ceil(values["targetRoofDispMm"] / values["stepIncrementMm"])
    rows = [
        {
            "targetDispMm": values["targetRoofDispMm"],
            "incrementMm": values["stepIncrementMm"],
            "steps": steps,
        }
    ]
    return result(
        summary={"steps": steps, "incrementMm": values["stepIncrementMm"]},
        tables=[
            table(
                "Pushover increment sizing",
                [
                    ("targetDispMm", "Target", "mm"),
                    ("incrementMm", "Δu", "mm"),
                    ("steps", "Total Steps"),
                ],
                rows,
            )
        ],
        notes=["Smaller increments resolve initial concrete cracking and yield knees cleanly."],
    )


@feature(
    "femPushoverPattern.maxSteps",
    "Max Steps",
    part="fem",
    fields=[
        number("maxSteps", "Maximum solver steps", 250, min=10, max=5000),
        number("stepMm", "Displacement step", 2.0, unit="mm", min=0.1),
    ],
    requires_project=False,
)
def max_steps(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute maximum travelable roof displacement within the step budget."""
    max_disp = int(values["maxSteps"]) * values["stepMm"]
    rows = [
        {"maxSteps": int(values["maxSteps"]), "stepMm": values["stepMm"], "maxTravelMm": max_disp}
    ]
    return result(
        summary={"maxSteps": int(values["maxSteps"]), "maxTravelMm": max_disp},
        tables=[
            table(
                "Maximum pushover step envelope",
                [
                    ("maxSteps", "Max Steps"),
                    ("stepMm", "Δu", "mm"),
                    ("maxTravelMm", "Max Travel", "mm"),
                ],
                rows,
            )
        ],
        notes=["Run terminates cleanly when step limit or target drift is reached."],
    )


@feature(
    "femPushoverPattern.monitorNode",
    "Monitor Node",
    part="fem",
    fields=[],
    requires_project=True,
)
def monitor_node(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Identify top roof control nodes in 08 FEM/model.osmodel for displacement control."""
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel first to identify control nodes.")
    nodes = model.get("nodes", [])
    z_max = max(
        (float(n["coords"][2]) for n in nodes if len(n.get("coords", [])) >= 3), default=0.0
    )
    roof = [
        n
        for n in nodes
        if len(n.get("coords", [])) >= 3 and abs(float(n["coords"][2]) - z_max) < 0.05
    ]
    rows = [
        {"nodeId": n["id"], "xM": n["coords"][0], "yM": n["coords"][1], "zM": n["coords"][2]}
        for n in roof[:20]
    ]
    return result(
        summary={"roofElevationM": z_max, "candidateControlNodes": len(roof)},
        tables=[
            table(
                "Roof control node candidates",
                [("nodeId", "Node ID"), ("xM", "X", "m"), ("yM", "Y", "m"), ("zM", "Z", "m")],
                rows or [{"nodeId": 0, "xM": 0.0, "yM": 0.0, "zM": 0.0}],
            )
        ],
        notes=[
            "Displacement-controlled pushover tracks horizontal translation of the roof center of mass."
        ],
    )


@feature(
    "femPushoverPattern.stopCriteria",
    "Stop Criteria",
    part="fem",
    fields=[
        number("buildingHeightM", "Building height H", 12.0, unit="m", min=3.0),
        number("maxDriftRatio", "Stop drift limit", 0.05, min=0.01, max=0.15),
        number("minShearShare", "Strength drop stop share", 0.80, min=0.2, max=0.98),
    ],
    requires_project=False,
)
def stop_criteria(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define displacement and post-peak strength drop stopping criteria for pushover runs."""
    stop_mm = values["buildingHeightM"] * values["maxDriftRatio"] * 1000.0
    rows = [
        {
            "criterion": "Max roof drift",
            "limit": f"{values['maxDriftRatio'] * 100:.1f}% ({stop_mm:.1f} mm)",
        },
        {
            "criterion": "Post-peak strength drop",
            "limit": f"V < {values['minShearShare']:.2f} V_peak",
        },
    ]
    return result(
        summary={"stopRoofDispMm": stop_mm, "minShearRetention": values["minShearShare"]},
        tables=[
            table(
                "Pushover termination criteria",
                [("criterion", "Criterion"), ("limit", "Threshold")],
                rows,
            )
        ],
        notes=["Prevents unnecessary integration after global collapse mechanism formation."],
    )


@feature(
    "femPushoverPattern.adaptiveDistribution",
    "Adaptive Distribution",
    part="fem",
    fields=[text("stiffnesses", "Storey secant stiffnesses [kN/m]", "120000, 95000, 80000, 60000")],
    requires_project=False,
)
def adaptive_distribution(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Recompute instantaneous adaptive lateral load distribution from degraded storey stiffness."""
    ks = parse_numbers(values["stiffnesses"], "Storey stiffnesses")
    # Approximate deflected profile from cumulative inverse stiffness
    drifts = [1.0 / max(k, 1.0) for k in ks]
    phis = np.cumsum(drifts)
    phis = phis / phis[-1]
    shares = phis / np.sum(phis)
    rows = [
        {
            "storey": f"Level {i + 1}",
            "stiffnessKnM": ks[i],
            "phiAdaptive": float(phis[i]),
            "loadShare": float(shares[i]),
        }
        for i in range(len(ks))
    ]
    return result(
        summary={"storeys": len(rows), "roofLoadShare": float(shares[-1])},
        tables=[
            table(
                "Adaptive displacement-based pushover distribution",
                [
                    ("storey", "Storey"),
                    ("stiffnessKnM", "K_sec", "kN/m"),
                    ("phiAdaptive", "φ_inst"),
                    ("loadShare", "Share"),
                ],
                rows,
            )
        ],
        notes=[
            "Updates load vector as soft storeys yield and shift the instantaneous deflection shape."
        ],
    )


@feature(
    "femPushoverPattern.instantaneousVector",
    "Instantaneous Vector",
    part="fem",
    fields=[
        text("displacementsMm", "Current floor displacements [mm]", "8, 22, 38, 52"),
        number("totalShearKn", "Current base shear", 420.0, unit="kN", min=1.0),
    ],
    requires_project=False,
)
def instantaneous_vector(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate instantaneous proportional lateral force vector from current floor displacements."""
    ds = parse_numbers(values["displacementsMm"], "Displacements")
    tot = sum(abs(d) for d in ds) or 1.0
    rows = [
        {"level": f"Level {i + 1}", "dispMm": d, "forceKn": values["totalShearKn"] * abs(d) / tot}
        for i, d in enumerate(ds)
    ]
    return result(
        summary={"levels": len(rows), "totalShearKn": values["totalShearKn"]},
        tables=[
            table(
                "Instantaneous adaptive load vector",
                [("level", "Level"), ("dispMm", "Δ_i", "mm"), ("forceKn", "F_i", "kN")],
                rows,
            )
        ],
        notes=["F_i proportional to m_i · Δ_i at the active pushover increment."],
    )


@feature(
    "femPushoverPattern.updateSpectrum",
    "Update Spectrum",
    part="fem",
    fields=[
        number("initialPeriodS", "Elastic period T0", 0.65, unit="s", min=0.05),
        number("stiffnessRatio", "Secant stiffness ratio Ke/K0", 0.45, min=0.05, max=1.0),
    ],
    requires_project=False,
)
def update_spectrum(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Recompute elongated effective period Te and corresponding design spectral demand."""
    te = values["initialPeriodS"] / math.sqrt(values["stiffnessRatio"])
    settings = load_settings(ctx)
    sc, z_val, _, _, _, _ = site_params(settings)
    with in_force(ctx.root):
        sa0 = loads.normalized_spectrum(values["initialPeriodS"], sc) * max(z_val, 0.1)
        sae = loads.normalized_spectrum(te, sc) * max(z_val, 0.1)
    rows = [
        {"state": "Initial elastic", "periodS": values["initialPeriodS"], "saG": sa0},
        {"state": "Degraded secant", "periodS": te, "saG": sae},
    ]
    return result(
        summary={
            "initialPeriodS": values["initialPeriodS"],
            "elongatedPeriodS": te,
            "updatedSaG": sae,
        },
        tables=[
            table(
                "Period elongation & spectrum update",
                [("state", "State"), ("periodS", "Period", "s"), ("saG", "Sa", "g")],
                rows,
            )
        ],
        notes=["Te = T0 / √(Ke/K0) captures period lengthening due to cracking and yielding."],
    )


@feature(
    "femPushoverPattern.inelasticDisplacement",
    "Inelastic Displacement",
    part="fem",
    fields=[
        number("elasticDispMm", "Elastic spectral displacement Sd,el", 65.0, unit="mm", min=0.1),
        number("c1", "Inelastic ratio C1", 1.15, min=0.5, max=2.5),
        number("c2", "Pinching factor C2", 1.05, min=0.8, max=2.0),
    ],
    requires_project=False,
)
def inelastic_displacement(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute inelastic roof displacement demand Δ_inel = C1 · C2 · Δ_el across increments."""
    d_in = values["c1"] * values["c2"] * values["elasticDispMm"]
    rows = [
        {
            "elasticDispMm": values["elasticDispMm"],
            "c1": values["c1"],
            "c2": values["c2"],
            "inelasticDispMm": d_in,
        }
    ]
    return result(
        summary={"inelasticDispMm": d_in, "amplification": values["c1"] * values["c2"]},
        tables=[
            table(
                "Inelastic displacement demand",
                [
                    ("elasticDispMm", "Δ_el", "mm"),
                    ("c1", "C1"),
                    ("c2", "C2"),
                    ("inelasticDispMm", "Δ_inel", "mm"),
                ],
                rows,
            )
        ],
        notes=["Short-period structures experience C1 > 1 inelastic displacement amplification."],
    )


@feature(
    "femPushoverPattern.srssCombination",
    "SRSS Combination",
    part="fem",
    fields=[
        text("mode1ForcesKn", "Mode 1 storey forces [kN]", "60, 120, 180, 240"),
        text("mode2ForcesKn", "Mode 2 storey forces [kN]", "-50, -30, 40, 80"),
    ],
    requires_project=False,
)
def srss_combination(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Combine multi-mode lateral pushover force vectors using SRSS."""
    f1 = parse_numbers(values["mode1ForcesKn"], "Mode 1 forces")
    f2 = parse_numbers(values["mode2ForcesKn"], "Mode 2 forces")
    n = min(len(f1), len(f2))
    rows = [
        {
            "level": f"Level {i + 1}",
            "mode1Kn": f1[i],
            "mode2Kn": f2[i],
            "srssKn": math.hypot(f1[i], f2[i]),
        }
        for i in range(n)
    ]
    return result(
        summary={"levels": n, "totalSrssKn": sum(r["srssKn"] for r in rows)},
        tables=[
            table(
                "SRSS multi-mode pushover load vector",
                [
                    ("level", "Level"),
                    ("mode1Kn", "Mode 1", "kN"),
                    ("mode2Kn", "Mode 2", "kN"),
                    ("srssKn", "SRSS", "kN"),
                ],
                rows,
            )
        ],
        notes=[
            "Note: SRSS produces non-negative magnitudes; use sign-preserving option for reversals."
        ],
    )


@feature(
    "femPushoverPattern.cqcCombination",
    "CQC Combination",
    part="fem",
    fields=[
        number("t1S", "Mode 1 period T1", 1.10, unit="s", min=0.05),
        number("t2S", "Mode 2 period T2", 0.95, unit="s", min=0.05),
        number("damping", "Modal damping ξ", 0.05, min=0.01, max=0.25),
        number("r1Kn", "Mode 1 force", 200.0, unit="kN"),
        number("r2Kn", "Mode 2 force", 110.0, unit="kN"),
    ],
    requires_project=False,
)
def cqc_combination(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Der Kiureghian CQC cross-modal correlation coefficient ρ12 and combined force."""
    r = min(values["t1S"], values["t2S"]) / max(values["t1S"], values["t2S"])
    xi = values["damping"]
    rho12 = (8.0 * xi**2 * (1.0 + r) * r**1.5) / (
        (1.0 - r**2) ** 2 + 4.0 * xi**2 * r * (1.0 + r) ** 2
    )
    comb = math.sqrt(
        values["r1Kn"] ** 2 + values["r2Kn"] ** 2 + 2.0 * rho12 * values["r1Kn"] * values["r2Kn"]
    )
    rows = [{"periodRatio": r, "rho12": rho12, "cqcForceKn": comb}]
    return result(
        summary={"periodRatio": r, "correlationRho12": rho12, "cqcForceKn": comb},
        tables=[
            table(
                "CQC modal force combination",
                [("periodRatio", "T2/T1"), ("rho12", "ρ12"), ("cqcForceKn", "F_CQC", "kN")],
                rows,
            )
        ],
        notes=[
            "Der Kiureghian correlation coefficient ρ12 captures closely spaced torsional/lateral modes."
        ],
    )


@feature(
    "femPushoverPattern.signPreserving",
    "Sign Preserving",
    part="fem",
    fields=[
        text("mode1Kn", "Mode 1 vector [kN]", "60, 120, 180, 240"),
        text("mode2Kn", "Mode 2 vector [kN]", "-50, -30, 40, 80"),
    ],
    requires_project=False,
)
def sign_preserving(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preserve fundamental-mode sign on SRSS-combined lateral force vectors."""
    f1 = parse_numbers(values["mode1Kn"], "Mode 1")
    f2 = parse_numbers(values["mode2Kn"], "Mode 2")
    n = min(len(f1), len(f2))
    rows = [
        {"level": f"Level {i + 1}", "signedForceKn": math.copysign(math.hypot(f1[i], f2[i]), f1[i])}
        for i in range(n)
    ]
    return result(
        summary={"levels": n, "netBaseShearKn": sum(r["signedForceKn"] for r in rows)},
        tables=[
            table(
                "Sign-preserving multi-mode vector",
                [("level", "Level"), ("signedForceKn", "Signed Fx", "kN")],
                rows,
            )
        ],
        notes=["Retains sign of the dominant contributing mode at every floor."],
    )


@feature(
    "femPushoverPattern.vectorOverlay",
    "Vector Overlay",
    part="fem",
    fields=[number("baseShearKn", "Base shear", 500.0, unit="kN", min=1.0)],
    requires_project=False,
)
def vector_overlay(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate lateral force arrow coordinates per floor for 3D model overlay."""
    levels = _level_heights(ctx, 4)
    denom = sum(z for _, z in levels) or 1.0
    rows = [
        {
            "level": nm,
            "elevM": z,
            "fxKn": values["baseShearKn"] * z / denom,
            "arrowLengthM": 2.0 * z / max(z_ for _, z_ in levels),
        }
        for nm, z in levels
    ]
    return result(
        summary={"vectors": len(rows)},
        tables=[
            table(
                "3D pushover force vector overlay",
                [
                    ("level", "Level"),
                    ("elevM", "z", "m"),
                    ("fxKn", "Fx", "kN"),
                    ("arrowLengthM", "Arrow Scale", "m"),
                ],
                rows,
            )
        ],
        notes=["Normalized arrow lengths scaled relative to roof force magnitude."],
    )


@feature(
    "femPushoverPattern.normalizePattern",
    "Normalize Pattern",
    part="fem",
    fields=[text("forcesKn", "Storey forces [kN]", "80, 160, 240, 320")],
    requires_project=False,
)
def normalize_pattern(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Normalize lateral load vector so sum equals 1.0 (and peak equals 1.0)."""
    fs = parse_numbers(values["forcesKn"], "Forces")
    tot = sum(abs(x) for x in fs) or 1.0
    peak = max(abs(x) for x in fs) or 1.0
    rows = [
        {"level": f"Level {i + 1}", "rawKn": f, "unitSumShare": f / tot, "unitPeakRatio": f / peak}
        for i, f in enumerate(fs)
    ]
    return result(
        summary={"levels": len(rows), "rawTotalKn": tot},
        tables=[
            table(
                "Normalized pushover load vector",
                [
                    ("level", "Level"),
                    ("rawKn", "Raw", "kN"),
                    ("unitSumShare", "f / Σ|f|"),
                    ("unitPeakRatio", "f / max|f|"),
                ],
                rows,
            )
        ],
        notes=["Provides unit-base-shear and unit-roof-force normalized shapes."],
    )


@feature(
    "femPushoverPattern.exportVector",
    "Export Vector",
    part="fem",
    fields=[
        text("forcesKn", "Storey forces [kN]", "80, 160, 240, 320"),
        text("filename", "Output filename", "pushover-pattern.txt"),
    ],
    requires_project=True,
)
def export_vector(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export lateral load pattern vector to a tabular text file in 08 FEM/exports/."""
    fs = parse_numbers(values["forcesKn"], "Forces")
    tot = sum(fs) or 1.0
    lines = ["level\tforce_kN\tshare"] + [
        f"Level_{i + 1}\t{f:.3f}\t{f / tot:.6f}" for i, f in enumerate(fs)
    ]
    path = export_fem_file(
        ctx, values["filename"].strip() or "pushover-pattern.txt", "\n".join(lines) + "\n"
    )
    return result(
        summary={"levels": len(fs), "exportPath": str(path)},
        tables=[
            table(
                "Exported pattern vector",
                [("level", "Level"), ("forceKn", "Force", "kN")],
                [{"level": f"Level {i + 1}", "forceKn": f} for i, f in enumerate(fs)],
            )
        ],
        notes=[f"Vector written to {path}"],
    )

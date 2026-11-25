"""Design Reinforcement - Fire Design tab: fire curves, heat transfer, section factors, reduced strength, and insulation."""

from __future__ import annotations

import math
from typing import Any

from saengine.design import fire_resistance
from saengine.design.steel import fire as steel_fire
from saengine.features import (
    FeatureContext,
    feature,
    number,
    result,
    select,
    table,
)
from saengine.features.fem_common import export_fem_file, load_settings, steel_defaults
from saengine.report.clauses import in_force


def _iso_temp(t_min: float) -> float:
    return 20.0 + 345.0 * math.log10(8.0 * max(t_min, 0.0) + 1.0)


def _hydrocarbon_temp(t_min: float) -> float:
    return 20.0 + 1080.0 * (1.0 - 0.325 * math.exp(-0.167 * t_min) - 0.675 * math.exp(-2.5 * t_min))


@feature(
    "femDesignFire.fireCurve",
    "Fire Curve",
    part="fem",
    fields=[
        select(
            "curve",
            "Time-temperature curve",
            [
                ("standard", "Standard cellulosic ISO-834"),
                ("hydrocarbon", "Hydrocarbon pool fire"),
                ("external", "External facade fire"),
            ],
            "standard",
        ),
        number("durationMin", "Fire exposure duration", 90.0, unit="min", min=15.0, max=240.0),
    ],
    requires_project=False,
)
def fire_curve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate gas time-temperature history θg(t) for standard or hydrocarbon fire exposure."""
    dur = values["durationMin"]
    steps = [0.0, 15.0, 30.0, 45.0, 60.0, 90.0, 120.0, 180.0, 240.0]
    ts = [t for t in steps if t <= dur] or [0.0, dur]
    if ts[-1] < dur:
        ts.append(dur)
    rows = []
    for t in ts:
        if values["curve"] == "hydrocarbon":
            tg = _hydrocarbon_temp(t)
        elif values["curve"] == "external":
            tg = 20.0 + 660.0 * (1.0 - 0.687 * math.exp(-0.32 * t) - 0.313 * math.exp(-3.8 * t))
        else:
            tg = _iso_temp(t)
        rows.append({"timeMin": t, "gasTempC": tg})
    return result(
        summary={
            "curve": values["curve"],
            "durationMin": dur,
            "peakGasTempC": rows[-1]["gasTempC"],
        },
        tables=[
            table(
                "Fire compartment gas temperature curve",
                [("timeMin", "Time", "min"), ("gasTempC", "θg", "°C")],
                rows,
            )
        ],
        notes=["Cellulosic standard curve θg = 20 + 345·log10(8t + 1)."],
    )


@feature(
    "femDesignFire.fireDuration",
    "Fire Duration",
    part="fem",
    fields=[number("buildingHeightM", "Building height", 18.0, unit="m", min=3.0)],
    requires_project=False,
)
def fire_duration(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Read required fire resistance ratings (hours) per member kind from active code pack."""
    settings = load_settings(ctx)
    with in_force(ctx.root):
        constr = fire_resistance.construction_summary(settings, height=values["buildingHeightM"])
        ratings = fire_resistance.ratings_of(settings)
    rows = [
        {"kind": str(k), "hours": float(v[0]), "basis": str(v[1])}
        for k, v in (ratings or {}).items()
    ]
    return result(
        summary={"covered": fire_resistance.covered(), "ratingsCount": len(rows)},
        tables=[
            table(
                "Required fire resistance durations",
                [("kind", "Member Kind"), ("hours", "Rating", "hr"), ("basis", "Source")],
                rows or [{"kind": "All", "hours": 1.0, "basis": str(constr)}],
            )
        ],
        notes=["Resolved from Project Settings construction type and active code pack."],
    )


@feature(
    "femDesignFire.compartmentSize",
    "Compartment Size",
    part="fem",
    fields=[
        number("floorAreaM2", "Compartment floor area Af", 400.0, unit="m²", min=10.0),
        number("fuelLoadMjM2", "Design fire load density qf,d", 420.0, unit="MJ/m²", min=50.0),
        number("openingAreaM2", "Window opening area Av", 24.0, unit="m²", min=1.0),
        number("openingHeightM", "Opening height hv", 2.0, unit="m", min=0.5),
    ],
    requires_project=False,
)
def compartment_size(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute parametric compartment opening factor O and ventilation-controlled peak fire duration."""
    at_total = 2.0 * values["floorAreaM2"] + 4.0 * math.sqrt(values["floorAreaM2"]) * 3.5
    o_fac = min(
        0.20, max(0.02, values["openingAreaM2"] * math.sqrt(values["openingHeightM"]) / at_total)
    )
    t_lim_min = max(
        15.0, (0.2e-3 * values["fuelLoadMjM2"] * values["floorAreaM2"] / (at_total * o_fac)) * 60.0
    )
    rows = [{"totalEnclosureM2": at_total, "openingFactor": o_fac, "burningDurationMin": t_lim_min}]
    return result(
        summary={"openingFactor": o_fac, "burningDurationMin": t_lim_min},
        tables=[
            table(
                "Parametric compartment fire ventilation",
                [
                    ("totalEnclosureM2", "At", "m²"),
                    ("openingFactor", "Factor O", "m^0.5"),
                    ("burningDurationMin", "t_max", "min"),
                ],
                rows,
            )
        ],
        notes=["Opening factor O = Av √hv / At governs ventilation-controlled fire severity."],
    )


@feature(
    "femDesignFire.protectedZone",
    "Protected Zone",
    part="fem",
    fields=[
        select(
            "exposure",
            "Fire exposure perimeter",
            [
                ("fourSided", "4-sided (column / hanger)"),
                ("threeSided", "3-sided (beam supporting slab)"),
            ],
            "threeSided",
        ),
        number("perimeterMm", "Section total perimeter", 1400.0, unit="mm", min=100.0),
        number("topFlangeWidthMm", "Protected top flange width", 200.0, unit="mm", min=0.0),
    ],
    requires_project=False,
)
def protected_zone(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute fire-exposed heated perimeter Am relative to total perimeter."""
    exposed = (
        values["perimeterMm"]
        if values["exposure"] == "fourSided"
        else max(100.0, values["perimeterMm"] - values["topFlangeWidthMm"])
    )
    rows = [
        {
            "exposure": values["exposure"],
            "totalPerimMm": values["perimeterMm"],
            "heatedPerimMm": exposed,
        }
    ]
    return result(
        summary={"heatedPerimeterMm": exposed, "exposure": values["exposure"]},
        tables=[
            table(
                "Heated perimeter calculation",
                [
                    ("exposure", "Exposure"),
                    ("totalPerimMm", "Total P", "mm"),
                    ("heatedPerimMm", "Heated Am", "mm"),
                ],
                rows,
            )
        ],
        notes=["Top flange shielded by concrete slab reduces 3-sided beam heating rate."],
    )


@feature(
    "femDesignFire.reducedStrength",
    "Reduced Strength",
    part="fem",
    fields=[number("steelTempC", "Steel temperature θa", 550.0, unit="°C", min=20.0, max=1100.0)],
    requires_project=False,
)
def reduced_strength(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute elevated-temperature steel yield ky,θ and modulus kE,θ retention factors."""
    th = values["steelTempC"]
    # Eurocode 3 / ASCE smooth retention approximation if pack table absent
    with in_force(ctx.root):
        t = steel_fire.table()
    if t is not None:
        ky, ke = steel_fire.retention(th, t)
    else:
        ky = 1.0 if th <= 400.0 else max(0.0, 1.0 - (th - 400.0) / 800.0)
        ke = 1.0 if th <= 100.0 else max(0.0, 1.0 - (th - 100.0) / 900.0)
    fy, _ = steel_defaults(ctx)
    rows = [{"tempC": th, "ky": ky, "ke": ke, "effectiveFyMpa": ky * fy}]
    return result(
        summary={"temperatureC": th, "kyTheta": ky, "keTheta": ke, "effectiveFyMpa": ky * fy},
        tables=[
            table(
                "Elevated-temperature steel strength retention",
                [
                    ("tempC", "θa", "°C"),
                    ("ky", "ky,θ"),
                    ("ke", "kE,θ"),
                    ("effectiveFyMpa", "fy,θ", "MPa"),
                ],
                rows,
            )
        ],
        notes=[
            "Evaluated via saengine.design.steel.fire.retention when covered by active code pack."
        ],
    )


@feature(
    "femDesignFire.thermalExpansion",
    "Thermal Expansion",
    part="fem",
    fields=[
        number("tempRiseC", "Average temperature rise ΔT", 500.0, unit="°C", min=0.0, max=1100.0),
        number("memberLengthM", "Member length L", 8.0, unit="m", min=0.5),
        select(
            "material",
            "Material",
            [
                ("steel", "Structural Steel (α ≈ 1.2e-5/°C)"),
                ("concrete", "Concrete (α ≈ 1.0e-5/°C)"),
            ],
            "steel",
        ),
    ],
    requires_project=False,
)
def thermal_expansion(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute free thermal strain ε_th and unrestrained axial elongation ΔL at fire temperature."""
    alpha = 1.2e-5 if values["material"] == "steel" else 1.0e-5
    eps_th = alpha * values["tempRiseC"]
    dl_mm = eps_th * values["memberLengthM"] * 1000.0
    rows = [
        {
            "material": values["material"],
            "tempRiseC": values["tempRiseC"],
            "thermalStrain": eps_th,
            "elongationMm": dl_mm,
        }
    ]
    return result(
        summary={"thermalStrain": eps_th, "elongationMm": dl_mm},
        tables=[
            table(
                "Fire thermal elongation",
                [
                    ("material", "Material"),
                    ("tempRiseC", "ΔT", "°C"),
                    ("thermalStrain", "ε_th"),
                    ("elongationMm", "ΔL", "mm"),
                ],
                rows,
            )
        ],
        notes=[
            "Restrained thermal expansion induces significant compressive axial forces before yielding."
        ],
    )


@feature(
    "femDesignFire.insulationLayer",
    "Insulation Layer",
    part="fem",
    fields=[
        number("thicknessMm", "Protection thickness dp", 20.0, unit="mm", min=0.5, max=100.0),
        number(
            "conductivityWmK", "Thermal conductivity λp", 0.12, unit="W/(m·K)", min=0.02, max=2.0
        ),
        number("specificHeatJKgK", "Specific heat cp", 1200.0, unit="J/(kg·K)", min=200.0),
        number("densityKgM3", "Dry density ρp", 350.0, unit="kg/m³", min=50.0),
    ],
    requires_project=False,
)
def insulation_layer(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute thermal resistance R = dp/λp and thermal capacitance of fire protection cladding."""
    dp_m = values["thicknessMm"] / 1000.0
    r_val = dp_m / values["conductivityWmK"]
    c_areal = values["densityKgM3"] * values["specificHeatJKgK"] * dp_m
    rows = [{"rValueM2KW": r_val, "arealHeatCapacityJm2K": c_areal}]
    return result(
        summary={"thermalResistanceM2KW": r_val, "arealHeatCapacityJm2K": c_areal},
        tables=[
            table(
                "Fire protection insulation properties",
                [
                    ("rValueM2KW", "R = dp/λp", "m²K/W"),
                    ("arealHeatCapacityJm2K", "ρp·cp·dp", "J/(m²K)"),
                ],
                rows,
            )
        ],
        notes=["Higher R-value and moisture/heat capacity slow steel heating in standard fire."],
    )


@feature(
    "femDesignFire.sectionFactor",
    "Section Factor",
    part="fem",
    fields=[
        number("exposedPerimeterMm", "Heated perimeter Am", 1100.0, unit="mm", min=50.0),
        number("steelAreaMm2", "Cross-sectional area V (A)", 6800.0, unit="mm²", min=100.0),
    ],
    requires_project=False,
)
def section_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute steel section factor Am/V [1/m] governing lumped-capacitance heating speed."""
    am_v = (values["exposedPerimeterMm"] / values["steelAreaMm2"]) * 1000.0
    rows = [
        {
            "exposedPerimeterMm": values["exposedPerimeterMm"],
            "areaMm2": values["steelAreaMm2"],
            "sectionFactorPerM": am_v,
        }
    ]
    return result(
        summary={"sectionFactorPerM": am_v},
        tables=[
            table(
                "Steel section factor Am/V",
                [
                    ("exposedPerimeterMm", "Am", "mm"),
                    ("areaMm2", "V", "mm²"),
                    ("sectionFactorPerM", "Am/V", "1/m"),
                ],
                rows,
            )
        ],
        notes=["Massive heavy sections (low Am/V) heat much more slowly than thin light sections."],
    )


@feature(
    "femDesignFire.temperatureCheck",
    "Temperature Check",
    part="fem",
    fields=[
        number("sectionFactorPerM", "Section factor Am/V", 160.0, unit="1/m", min=20.0, max=400.0),
        number("durationMin", "Fire rating duration", 60.0, unit="min", min=15.0, max=240.0),
        number(
            "protectionThicknessMm",
            "Spray protection thickness (0 = bare)",
            15.0,
            unit="mm",
            min=0.0,
        ),
        number(
            "criticalTempC",
            "Critical steel temperature θcr",
            580.0,
            unit="°C",
            min=250.0,
            max=900.0,
        ),
    ],
    requires_project=False,
)
def temperature_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Simulate lumped-heat-capacity steel temperature θa(t) and verify θa <= θcr."""
    dt = 10.0  # seconds
    steps = int(values["durationMin"] * 60.0 / dt)
    ta = 20.0
    ca, rho_a = 600.0, 7850.0
    am_v = values["sectionFactorPerM"]
    dp = values["protectionThicknessMm"] / 1000.0
    lam_p = 0.12
    for s in range(1, steps + 1):
        tg = _iso_temp((s * dt) / 60.0)
        if dp <= 0.0:
            h_net = 25.0 * (tg - ta) + 0.7 * 5.67e-8 * ((tg + 273.15) ** 4 - (ta + 273.15) ** 4)
            ta += (am_v * h_net / (ca * rho_a)) * dt
        else:
            ta += ((lam_p / dp) * am_v / (ca * rho_a)) * (tg - ta) * dt
    ok = ta <= values["criticalTempC"]
    rows = [
        {
            "finalGasTempC": _iso_temp(values["durationMin"]),
            "steelTempC": ta,
            "criticalTempC": values["criticalTempC"],
            "ok": ok,
        }
    ]
    return result(
        summary={"steelTempC": ta, "criticalTempC": values["criticalTempC"], "passes": ok},
        tables=[
            table(
                "Steel temperature verification",
                [
                    ("finalGasTempC", "θg", "°C"),
                    ("steelTempC", "θa", "°C"),
                    ("criticalTempC", "θcr", "°C"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Lumped-capacitance Euler time integration under standard fire curve."],
    )


@feature(
    "femDesignFire.capacityCheck",
    "Capacity Check",
    part="fem",
    fields=[
        number("loadRatioMu0", "Fire load ratio μ0 = Ed,fi / Rd,20", 0.55, min=0.05, max=1.0),
        number(
            "steelTempC", "Calculated steel temperature θa", 540.0, unit="°C", min=20.0, max=1100.0
        ),
    ],
    requires_project=False,
)
def capacity_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check reduced fire resistance ky,θ against fire load ratio μ0."""
    with in_force(ctx.root):
        t = steel_fire.table()
    if t is not None:
        ky, _ = steel_fire.retention(values["steelTempC"], t)
        t_cr = steel_fire.critical_temperature(values["loadRatioMu0"], t)
    else:
        ky = (
            1.0
            if values["steelTempC"] <= 400.0
            else max(0.0, 1.0 - (values["steelTempC"] - 400.0) / 800.0)
        )
        t_cr = 400.0 + (1.0 - values["loadRatioMu0"]) * 400.0
    dcr = values["loadRatioMu0"] / max(ky, 1e-4)
    rows = [
        {
            "loadRatio": values["loadRatioMu0"],
            "kyTheta": ky,
            "criticalTempC": t_cr,
            "dcr": dcr,
            "ok": dcr <= 1.0,
        }
    ]
    return result(
        summary={"kyTheta": ky, "criticalTempC": t_cr, "utilisation": dcr, "passes": dcr <= 1.0},
        tables=[
            table(
                "Fire capacity check",
                [
                    ("loadRatio", "μ0"),
                    ("kyTheta", "ky,θ"),
                    ("criticalTempC", "θcr", "°C"),
                    ("dcr", "DCR"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Compares demand ratio μ0 against elevated-temperature yield retention ky,θ."],
    )


@feature(
    "femDesignFire.insulationThickness",
    "Insulation Thickness",
    part="fem",
    fields=[
        number("sectionFactorPerM", "Section factor Am/V", 160.0, unit="1/m", min=20.0),
        number("durationMin", "Required fire rating", 90.0, unit="min", min=15.0),
        number("criticalTempC", "Critical temperature θcr", 550.0, unit="°C", min=300.0),
        number("conductivityWmK", "Insulation λp", 0.12, unit="W/(m·K)", min=0.02),
    ],
    requires_project=False,
)
def insulation_thickness(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Solve minimum fireproofing thickness dp so θa(duration) <= θcr."""
    am_v, lam_p, t_cr = (
        values["sectionFactorPerM"],
        values["conductivityWmK"],
        values["criticalTempC"],
    )
    steps = int(values["durationMin"] * 60.0 / 15.0)

    def end_temp(dp_mm: float) -> float:
        ta, dp = 20.0, dp_mm / 1000.0
        for s in range(1, steps + 1):
            tg = _iso_temp((s * 15.0) / 60.0)
            ta += ((lam_p / max(dp, 1e-4)) * am_v / (600.0 * 7850.0)) * (tg - ta) * 15.0
        return ta

    lo, hi = 1.0, 100.0
    for _ in range(25):
        mid = 0.5 * (lo + hi)
        if end_temp(mid) > t_cr:
            lo = mid
        else:
            hi = mid
    dp_sol = math.ceil(hi)
    rows = [{"solvedThicknessMm": dp_sol, "achievedTempC": end_temp(dp_sol), "targetTempC": t_cr}]
    return result(
        summary={"requiredThicknessMm": dp_sol, "achievedTempC": rows[0]["achievedTempC"]},
        tables=[
            table(
                "Solved insulation thickness",
                [
                    ("solvedThicknessMm", "dp,req", "mm"),
                    ("achievedTempC", "θa", "°C"),
                    ("targetTempC", "θcr", "°C"),
                ],
                rows,
            )
        ],
        notes=["Binary-searched minimum dry film/spray thickness meeting target fire duration."],
    )


@feature(
    "femDesignFire.fireReport",
    "Fire Report",
    part="fem",
    fields=[number("ratingHours", "Fire rating duration", 1.5, unit="hr", min=0.5, max=4.0)],
    requires_project=True,
)
def fire_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export fire resistance ratings and minimum concrete dimensions report to Markdown."""
    settings = load_settings(ctx)
    with in_force(ctx.root):
        slab_min = fire_resistance.required("slabThickness", values["ratingHours"]) or 100.0
        col_min = fire_resistance.required("columnSize", values["ratingHours"]) or 250.0
        constr = fire_resistance.construction_summary(settings)
    md = f"# Structural Fire Resistance Report\n\n- Rating: {values['ratingHours']:g} hr\n- Min slab thickness: {slab_min} mm\n- Min column size: {col_min} mm\n"
    path = export_fem_file(ctx, "fire-design-report.md", md)
    rows = [
        {"item": "Min slab thickness [mm]", "val": slab_min},
        {"item": "Min column dimension [mm]", "val": col_min},
        {"item": "Construction summary", "val": str(constr.get("type", "-"))},
    ]
    return result(
        summary={"minSlabMm": slab_min, "minColumnMm": col_min, "reportPath": str(path)},
        tables=[
            table("Fire resistance criteria", [("item", "Requirement"), ("val", "Value")], rows)
        ],
        notes=[f"Fire report exported to {path}"],
    )


@feature(
    "femDesignFire.heatTransfer",
    "Heat Transfer",
    part="fem",
    fields=[
        number("slabThicknessMm", "Concrete slab depth", 200.0, unit="mm", min=80.0),
        number("durationMin", "Exposure duration", 90.0, unit="min", min=15.0),
    ],
    requires_project=False,
)
def heat_transfer(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Solve 1D transient heat conduction temperature profile across concrete slab depth."""
    # Explicit 1D finite-difference with alpha_c ~ 0.6e-6 m²/s
    n_nodes = 9
    dx = (values["slabThicknessMm"] / 1000.0) / (n_nodes - 1)
    alpha = 0.55e-6
    dt = min(5.0, 0.4 * dx**2 / alpha)
    temps = [20.0] * n_nodes
    steps = int(values["durationMin"] * 60.0 / dt)
    for s in range(1, steps + 1):
        temps[0] = _iso_temp((s * dt) / 60.0)
        nxt = list(temps)
        r = alpha * dt / (dx**2)
        for i in range(1, n_nodes - 1):
            nxt[i] = temps[i] + r * (temps[i + 1] - 2.0 * temps[i] + temps[i - 1])
        nxt[-1] = temps[-1] + r * (temps[-2] - temps[-1])
        temps = nxt
    rows = [{"depthMm": i * dx * 1000.0, "tempC": temps[i]} for i in range(n_nodes)]
    return result(
        summary={"fireFaceTempC": temps[0], "unexposedFaceTempC": temps[-1]},
        tables=[
            table(
                "1D concrete cross-section thermal profile",
                [("depthMm", "Depth from fire face", "mm"), ("tempC", "Temp", "°C")],
                rows,
            )
        ],
        notes=["1D explicit finite-difference heat conduction (α = 0.55×10⁻⁶ m²/s)."],
    )


@feature(
    "femDesignFire.thermalProfile",
    "Thermal Profile",
    part="fem",
    fields=[
        number("fireFaceC", "Heated face temperature", 950.0, unit="°C", min=20.0),
        number("depthMm", "Section depth", 300.0, unit="mm", min=50.0),
    ],
    requires_project=False,
)
def thermal_profile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute thermal gradient, mean temperature, and curvature gradient across section."""
    t_back = 45.0
    t_mean = 0.5 * (values["fireFaceC"] + t_back)
    grad_c_mm = (values["fireFaceC"] - t_back) / values["depthMm"]
    rows = [
        {
            "fireFaceC": values["fireFaceC"],
            "backFaceC": t_back,
            "meanC": t_mean,
            "gradientCPerM": grad_c_mm * 1000.0,
        }
    ]
    return result(
        summary={"meanTempC": t_mean, "gradientCPerM": grad_c_mm * 1000.0},
        tables=[
            table(
                "Cross-section thermal gradient",
                [
                    ("fireFaceC", "Hot Face", "°C"),
                    ("backFaceC", "Cool Face", "°C"),
                    ("meanC", "Mean", "°C"),
                    ("gradientCPerM", "∇T", "°C/m"),
                ],
                rows,
            )
        ],
        notes=["Thermal gradient induces bowing curvature κ_th = α · ∇T."],
    )


@feature(
    "femDesignFire.conductivityMap",
    "Conductivity Map",
    part="fem",
    fields=[number("temperatureC", "Material temperature", 400.0, unit="°C", min=20.0, max=1200.0)],
    requires_project=False,
)
def conductivity_map(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate temperature-dependent thermal conductivity λ(θ) for steel and concrete."""
    t = values["temperatureC"]
    lam_steel = max(27.3, 54.0 - 3.33e-2 * t)
    lam_conc = max(0.7, 1.36 - 0.136 * (t / 100.0) + 0.0057 * (t / 100.0) ** 2)
    rows = [
        {"material": "Structural Steel", "lambdaWmK": lam_steel},
        {"material": "Siliceous Concrete", "lambdaWmK": lam_conc},
    ]
    return result(
        summary={"steelLambdaWmK": lam_steel, "concreteLambdaWmK": lam_conc},
        tables=[
            table(
                f"Thermal conductivity at {t:g} °C",
                [("material", "Material"), ("lambdaWmK", "λ", "W/(m·K)")],
                rows,
            )
        ],
        notes=["Thermal conductivity decreases with rising temperature."],
    )


@feature(
    "femDesignFire.coolingPhase",
    "Cooling Phase",
    part="fem",
    fields=[
        number("peakGasTempC", "Peak gas temperature at burnout", 945.0, unit="°C", min=100.0),
        number("coolingRateCMin", "Linear cooling rate", 10.0, unit="°C/min", min=1.0),
    ],
    requires_project=False,
)
def cooling_phase(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate gas temperature decay during fire burnout/cooling and tensile contraction risk."""
    rows = []
    for dt_min in (0.0, 15.0, 30.0, 45.0, 60.0):
        tg = max(20.0, values["peakGasTempC"] - values["coolingRateCMin"] * dt_min)
        rows.append({"afterPeakMin": dt_min, "gasTempC": tg})
    return result(
        summary={"peakTempC": values["peakGasTempC"], "tempAfter60MinC": rows[-1]["gasTempC"]},
        tables=[
            table(
                "Fire cooling-phase gas decay",
                [("afterPeakMin", "Burnout +", "min"), ("gasTempC", "θg", "°C")],
                rows,
            )
        ],
        notes=[
            "Cooling induces tensile contraction forces on connections heated during the peak phase."
        ],
    )


@feature(
    "femDesignFire.intumescentPaint",
    "Intumescent Paint",
    part="fem",
    fields=[
        number("sectionFactorPerM", "Section factor Am/V", 180.0, unit="1/m", min=20.0),
        number("durationMin", "Fire rating", 60.0, unit="min", min=30.0, max=120.0),
    ],
    requires_project=False,
)
def intumescent_paint(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size dry-film intumescent coating thickness (DFT) from section factor and rating."""
    # Typical reactive intumescent DFT correlation [mm]
    dft_mm = max(
        0.4, min(6.0, 0.005 * values["sectionFactorPerM"] * (values["durationMin"] / 60.0) ** 1.3)
    )
    rows = [
        {
            "sectionFactorPerM": values["sectionFactorPerM"],
            "durationMin": values["durationMin"],
            "dftMm": dft_mm,
            "dftMicrons": dft_mm * 1000.0,
        }
    ]
    return result(
        summary={"dryFilmThicknessMm": dft_mm, "dftMicrons": dft_mm * 1000.0},
        tables=[
            table(
                "Intumescent coating thickness estimate",
                [
                    ("sectionFactorPerM", "Am/V", "1/m"),
                    ("durationMin", "Rating", "min"),
                    ("dftMm", "DFT", "mm"),
                    ("dftMicrons", "DFT", "μm"),
                ],
                rows,
            )
        ],
        notes=[
            "Verify reactive intumescent DFT against manufacturer's certified furnace test tables."
        ],
    )


@feature(
    "femDesignFire.boardEncasement",
    "Board Encasement",
    part="fem",
    fields=[
        number("boardThicknessMm", "Calcium-silicate board thickness", 25.0, unit="mm", min=6.0),
        number("boxPerimeterMm", "Boxed section perimeter", 1000.0, unit="mm", min=100.0),
        number("steelAreaMm2", "Steel area", 6800.0, unit="mm²", min=100.0),
    ],
    requires_project=False,
)
def board_encasement(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute boxed section factor [Am/V]_box and thermal resistance of fire protective boards."""
    am_v_box = (values["boxPerimeterMm"] / values["steelAreaMm2"]) * 1000.0
    r_board = (values["boardThicknessMm"] / 1000.0) / 0.15
    rows = [
        {
            "boxedSectionFactorPerM": am_v_box,
            "boardThicknessMm": values["boardThicknessMm"],
            "rValue": r_board,
        }
    ]
    return result(
        summary={"boxedAmVPerM": am_v_box, "boardRValue": r_board},
        tables=[
            table(
                "Boxed board encasement properties",
                [
                    ("boxedSectionFactorPerM", "[Am/V]b", "1/m"),
                    ("boardThicknessMm", "Thickness", "mm"),
                    ("rValue", "R", "m²K/W"),
                ],
                rows,
            )
        ],
        notes=["Hollow boxing reduces heated perimeter relative to profile contour."],
    )


@feature(
    "femDesignFire.sprayInsulation",
    "Spray Insulation",
    part="fem",
    fields=[
        number("thicknessMm", "Mineral spray thickness", 22.0, unit="mm", min=5.0),
        number("memberPerimeterM", "Heated perimeter", 1.1, unit="m", min=0.2),
        number("lengthM", "Member length", 6.0, unit="m", min=0.5),
    ],
    requires_project=False,
)
def spray_insulation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate spray-applied fireproofing volume, mass, and effective thermal resistance."""
    area_m2 = values["memberPerimeterM"] * values["lengthM"]
    vol_m3 = area_m2 * (values["thicknessMm"] / 1000.0)
    mass_kg = vol_m3 * 300.0
    rows = [{"coatedAreaM2": area_m2, "volumeM3": vol_m3, "dryMassKg": mass_kg}]
    return result(
        summary={"coatedAreaM2": area_m2, "dryMassKg": mass_kg},
        tables=[
            table(
                "Spray fireproofing quantity & mass",
                [
                    ("coatedAreaM2", "Surface Area", "m²"),
                    ("volumeM3", "Volume", "m³"),
                    ("dryMassKg", "Mass", "kg"),
                ],
                rows,
            )
        ],
        notes=["Contoured mineral fiber spray follows profile perimeter closely."],
    )


@feature(
    "femDesignFire.thermalDeflection",
    "Thermal Deflection",
    part="fem",
    fields=[
        number("spanMm", "Beam span L", 8000.0, unit="mm", min=1000.0),
        number("depthMm", "Beam depth h", 400.0, unit="mm", min=100.0),
        number("tempGradientC", "Top-to-bottom ΔT", 450.0, unit="°C", min=0.0),
    ],
    requires_project=False,
)
def thermal_deflection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute mid-span thermal bowing deflection Δ_th = α·ΔT·L² / (8h)."""
    alpha = 1.2e-5
    delta_mm = alpha * values["tempGradientC"] * (values["spanMm"] ** 2) / (8.0 * values["depthMm"])
    rows = [
        {
            "spanMm": values["spanMm"],
            "deltaTempC": values["tempGradientC"],
            "thermalDeflectionMm": delta_mm,
            "spanRatio": values["spanMm"] / max(delta_mm, 0.1),
        }
    ]
    return result(
        summary={"thermalDeflectionMm": delta_mm, "spanOverDefl": rows[0]["spanRatio"]},
        tables=[
            table(
                "High-temperature thermal bowing deflection",
                [
                    ("spanMm", "Span", "mm"),
                    ("deltaTempC", "ΔT", "°C"),
                    ("thermalDeflectionMm", "δ_th", "mm"),
                    ("spanRatio", "L / δ"),
                ],
                rows,
            )
        ],
        notes=["Thermal gradient from 3-sided heating causes downward bowing."],
    )


@feature(
    "femDesignFire.catenaryAction",
    "Catenary Action",
    part="fem",
    fields=[
        number("udlKnPerM", "Fire-state floor UDL w", 25.0, unit="kN/m", min=0.5),
        number("spanM", "Beam span L", 8.0, unit="m", min=1.0),
        number("sagMm", "Large-deflection mid-span sag", 400.0, unit="mm", min=20.0),
    ],
    requires_project=False,
)
def catenary_action(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute tension catenary cable force T = w·L² / (8·δ) at large fire deflections."""
    sag_m = values["sagMm"] / 1000.0
    t_cat_kn = values["udlKnPerM"] * (values["spanM"] ** 2) / (8.0 * sag_m)
    rows = [{"spanM": values["spanM"], "sagMm": values["sagMm"], "catenaryTensionKn": t_cat_kn}]
    return result(
        summary={"catenaryTensionKn": t_cat_kn},
        tables=[
            table(
                "Fire catenary tension demand",
                [
                    ("spanM", "Span", "m"),
                    ("sagMm", "Sag δ", "mm"),
                    ("catenaryTensionKn", "Catenary T", "kN"),
                ],
                rows,
            )
        ],
        notes=[
            "End connections must carry catenary tension T after flexural plastic capacity drops."
        ],
    )


@feature(
    "femDesignFire.restraintForce",
    "Restraint Force",
    part="fem",
    fields=[
        number("steelAreaMm2", "Beam area A", 6800.0, unit="mm²", min=100.0),
        number("eThetaMpa", "Modulus at fire temp E(θ)", 110000.0, unit="MPa", min=1000.0),
        number("tempRiseC", "Mean temperature rise ΔT", 300.0, unit="°C", min=0.0),
        number("restraintRatio", "Axial restraint stiffness factor", 0.35, min=0.0, max=1.0),
    ],
    requires_project=False,
)
def restraint_force(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate axial thermal restraint compression P_th = kr · E(θ) · A · α · ΔT."""
    p_kn = (
        values["restraintRatio"]
        * values["eThetaMpa"]
        * values["steelAreaMm2"]
        * 1.2e-5
        * values["tempRiseC"]
        / 1000.0
    )
    rows = [
        {
            "restraintRatio": values["restraintRatio"],
            "tempRiseC": values["tempRiseC"],
            "restraintForceKn": p_kn,
        }
    ]
    return result(
        summary={"thermalRestraintForceKn": p_kn},
        tables=[
            table(
                "Axial thermal expansion restraint force",
                [
                    ("restraintRatio", "Restraint kr"),
                    ("tempRiseC", "ΔT", "°C"),
                    ("restraintForceKn", "P_th", "kN"),
                ],
                rows,
            )
        ],
        notes=[
            "Restraint compression can trigger early lateral-torsional or local flange buckling."
        ],
    )

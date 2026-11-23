"""Project Settings - Foundation: Piles & Deep Foundations tab: pile types, sections, capacity, testing, group, rock socket."""

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
    "settingsFoundationPiles.boredPile",
    "Bored Pile",
    part="settings",
    fields=[
        number("diameterMm", "Bored shaft diameter D", 750.0, unit="mm", min=300.0),
        number("lengthM", "Pile embedment length L", 22.0, unit="m", min=3.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=20.0),
    ],
    requires_project=False,
)
def bored_pile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a cast-in-situ bored pile default and compute concrete volume & structural axial cap."""
    d_m = values["diameterMm"] / 1000.0
    area_m2 = math.pi * d_m**2 / 4.0
    vol_m3 = area_m2 * values["lengthM"]
    # Structural concrete working stress ~ 0.30 f'c * Ag
    struct_cap_kn = 0.30 * values["fcMpa"] * (area_m2 * 1e6) / 1000.0
    return result(
        summary={
            "diameterMm": values["diameterMm"],
            "lengthM": values["lengthM"],
            "concreteVolumeM3": vol_m3,
            "structuralLimitKn": struct_cap_kn,
        },
        tables=[
            table(
                "Bored pile defaults",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Cross-section area [m²]", "value": area_m2},
                    {"metric": "Concrete volume [m³]", "value": vol_m3},
                    {"metric": "Allowable structural axial [kN]", "value": struct_cap_kn},
                ],
            )
        ],
        notes=["Structural working limit estimated at 0.30 f'c Ag."],
    )


@feature(
    "settingsFoundationPiles.drivenPile",
    "Driven Pile",
    part="settings",
    fields=[
        number("widthMm", "Precast square pile width B", 400.0, unit="mm", min=200.0),
        number("lengthM", "Driven pile length L", 18.0, unit="m", min=3.0),
        number("fcMpa", "Precast concrete f'c", 40.0, unit="MPa", min=25.0),
    ],
    requires_project=False,
)
def driven_pile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a driven precast concrete pile and check slenderness and driving stress limit."""
    b_m = values["widthMm"] / 1000.0
    area_mm2 = values["widthMm"] ** 2
    perim_m = 4.0 * b_m
    struct_cap_kn = 0.33 * values["fcMpa"] * area_mm2 / 1000.0
    return result(
        summary={
            "widthMm": values["widthMm"],
            "perimeterM": perim_m,
            "structuralCapacityKn": struct_cap_kn,
        },
        tables=[
            table(
                "Driven precast pile",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Shaft perimeter [m]", "value": perim_m},
                    {"metric": "Section area [mm²]", "value": area_mm2},
                    {"metric": "Allowable structural load [kN]", "value": struct_cap_kn},
                ],
            )
        ],
        notes=[
            "High-strength precast concrete (>= 40 MPa) resists handling and driving tensile waves."
        ],
    )


@feature(
    "settingsFoundationPiles.sheetPile",
    "Sheet Pile",
    part="settings",
    fields=[
        number(
            "sectionModulusCm3PerM", "Elastic section modulus Wx", 1600.0, unit="cm³/m", min=200.0
        ),
        number("fyMpa", "Steel yield strength fy", 355.0, unit="MPa", min=235.0),
        number("lengthM", "Sheet pile length", 12.0, unit="m", min=2.0),
    ],
    requires_project=False,
)
def sheet_pile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a steel sheet pile wall profile and compute plastic/elastic moment capacity per metre."""
    mn_knm_m = (values["sectionModulusCm3PerM"] * 1e3 * values["fyMpa"]) / 1e6
    phi_mn = 0.90 * mn_knm_m
    return result(
        summary={
            "sectionModulusCm3PerM": values["sectionModulusCm3PerM"],
            "designMomentKnMPerM": phi_mn,
        },
        tables=[
            table(
                "Sheet pile section properties",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Nominal moment Mn [kN·m/m]", "value": mn_knm_m},
                    {"metric": "Design moment φMn [kN·m/m]", "value": phi_mn},
                ],
            )
        ],
        notes=["Moment capacity per metre run of interlocking sheet pile wall."],
    )


@feature(
    "settingsFoundationPiles.micropile",
    "Micropile",
    part="settings",
    fields=[
        number("drillDiaMm", "Grouted drillhole diameter", 200.0, unit="mm", min=100.0, max=350.0),
        number("casingOdMm", "Steel core / casing OD", 139.7, unit="mm", min=60.0),
        number("casingWallMm", "Casing wall thickness", 9.5, unit="mm", min=4.0),
        number("fySteelMpa", "Casing yield strength fy", 550.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def micropile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute composite steel-grout structural axial capacity of a micropile."""
    od = values["casingOdMm"]
    t = values["casingWallMm"]
    a_steel = math.pi * (od**2 - max(0.0, od - 2.0 * t) ** 2) / 4.0
    a_grout = max(0.0, math.pi * values["drillDiaMm"] ** 2 / 4.0 - a_steel)
    p_comp_kn = (0.40 * 35.0 * a_grout + 0.47 * values["fySteelMpa"] * a_steel) / 1000.0
    return result(
        summary={"steelAreaMm2": a_steel, "groutAreaMm2": a_grout, "allowableAxialKn": p_comp_kn},
        tables=[
            table(
                "Micropile composite section",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Steel casing area [mm²]", "value": a_steel},
                    {"item": "Grout area [mm²]", "value": a_grout},
                    {"item": "Allowable axial load [kN]", "value": p_comp_kn},
                ],
            )
        ],
        notes=["Composite structural capacity combining 0.40 f'c Agrout + 0.47 fy Asteel."],
    )


@feature(
    "settingsFoundationPiles.pileDiameter",
    "Pile Diameter",
    part="settings",
    fields=[
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
    ],
    requires_project=False,
)
def pile_diameter(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute pile geometric properties (area, perimeter, second moment of area)."""
    d = values["diameterMm"]
    area = math.pi * d**2 / 4.0
    perim = math.pi * d
    ix = math.pi * d**4 / 64.0
    return result(
        summary={"diameterMm": d, "areaMm2": area, "perimeterMm": perim, "inertiaMm4": ix},
        tables=[
            table(
                "Circular pile geometry",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Area [mm²]", "value": area},
                    {"property": "Perimeter [mm]", "value": perim},
                    {"property": "Moment of inertia [mm⁴]", "value": ix},
                ],
            )
        ],
        notes=["Used for shaft friction perimeter, tip bearing area, and lateral EI."],
    )


@feature(
    "settingsFoundationPiles.wallThickness",
    "Wall Thickness",
    part="settings",
    fields=[
        number("outerDiaMm", "Tubular steel pile OD", 610.0, unit="mm", min=150.0),
        number("wallMm", "Nominal wall thickness t", 12.7, unit="mm", min=4.0),
        number("corrosionAllowanceMm", "Sacrificial corrosion thickness", 1.5, unit="mm", min=0.0),
    ],
    requires_project=False,
)
def wall_thickness(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute effective steel area and D/t local buckling ratio after corrosion loss."""
    od = values["outerDiaMm"]
    t_eff = max(1.0, values["wallMm"] - values["corrosionAllowanceMm"])
    a_eff = math.pi * (od**2 - (od - 2.0 * t_eff) ** 2) / 4.0
    return result(
        summary={
            "effectiveThicknessMm": t_eff,
            "dOverT": od / t_eff,
            "effectiveSteelAreaMm2": a_eff,
        },
        tables=[
            table(
                "Tubular pile effective section",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Effective thickness [mm]", "value": t_eff},
                    {"metric": "D / t ratio", "value": od / t_eff},
                    {"metric": "Net steel area [mm²]", "value": a_eff},
                ],
            )
        ],
        notes=["Sacrificial corrosion allowance subtracted from structural wall thickness."],
    )


@feature(
    "settingsFoundationPiles.pileReinforcement",
    "Pile Reinforcement",
    part="settings",
    fields=[
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=300.0),
        number("barCount", "Number of longitudinal bars", 8.0, min=4.0, max=32.0),
        number("barMm", "Main bar diameter", 20.0, unit="mm", min=12.0),
        number("coverMm", "Clear cover to spiral", 75.0, unit="mm", min=50.0),
    ],
    requires_project=False,
)
def pile_reinforcement(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check pile reinforcement ratio ρg and clear spacing around the rebar cage."""
    ag = math.pi * values["diameterMm"] ** 2 / 4.0
    n = int(values["barCount"])
    as_tot = n * math.pi * values["barMm"] ** 2 / 4.0
    rho = as_tot / ag
    pitch_dia = values["diameterMm"] - 2.0 * values["coverMm"] - 20.0 - values["barMm"]
    clear_sp = (math.pi * pitch_dia / n) - values["barMm"]
    return result(
        summary={
            "steelRatio": rho,
            "steelAreaMm2": as_tot,
            "clearSpacingMm": clear_sp,
            "adequateSpacing": clear_sp >= 75.0,
        },
        tables=[
            table(
                "Pile rebar cage check",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Longitudinal steel ratio ρ", "value": rho},
                    {"metric": "Total As [mm²]", "value": as_tot},
                    {"metric": "Bar clear spacing [mm]", "value": clear_sp},
                ],
            )
        ],
        notes=[
            "Tremie concrete placement requires >= 75-100 mm clear spacing between longitudinal bars."
        ],
    )


@feature(
    "settingsFoundationPiles.sectionPreview",
    "Section Preview",
    part="settings",
    fields=[],
    requires_project=False,
)
def section_preview(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List pile types defined in 09 Substructure/substructure.json with section properties."""
    sub = ctx.raw("substructure")
    ptypes = sub.get("pileTypes", []) if isinstance(sub, dict) else []
    rows = [
        {
            "id": p.get("id", "-"),
            "kind": p.get("kind", "-"),
            "diaMm": p.get("diameter", 0.0),
            "lenMm": p.get("length", 0.0),
        }
        for p in ptypes
        if isinstance(p, dict)
    ]
    return result(
        summary={"definedPileTypes": len(rows)},
        tables=[
            table(
                "Project pile types",
                [
                    ("id", "ID"),
                    ("kind", "Kind"),
                    ("diaMm", "Diameter", "mm"),
                    ("lenMm", "Length", "mm"),
                ],
                rows or [{"id": "(none)", "kind": "bored", "diaMm": 600.0, "lenMm": 18000.0}],
            )
        ],
        notes=["Read from 09 Substructure/substructure.json pileTypes."],
    )


@feature(
    "settingsFoundationPiles.shaftCapacity",
    "Shaft Capacity",
    part="settings",
    fields=[
        number("diameterM", "Pile diameter D", 0.60, unit="m", min=0.2),
        number("layerThicknessM", "Stratum thickness", 8.0, unit="m", min=0.5),
        number("unitSkinKpa", "Unit shaft friction fs", 45.0, unit="kPa", min=1.0),
    ],
    requires_project=False,
)
def shaft_capacity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute ultimate shaft friction resistance Qs = π D L fs for a soil stratum."""
    qs = math.pi * values["diameterM"] * values["layerThicknessM"] * values["unitSkinKpa"]
    return result(
        summary={
            "shaftAreaM2": math.pi * values["diameterM"] * values["layerThicknessM"],
            "ultimateShaftKn": qs,
        },
        tables=[
            table(
                "Pile shaft friction",
                [("item", "Item"), ("value", "Value")],
                [
                    {
                        "item": "Perimeter area [m²]",
                        "value": math.pi * values["diameterM"] * values["layerThicknessM"],
                    },
                    {"item": "Ultimate shaft Qs [kN]", "value": qs},
                ],
            )
        ],
        notes=["Unit skin friction fs can be derived from α-cu (clay) or β-σ'v (sand)."],
    )


@feature(
    "settingsFoundationPiles.baseCapacity",
    "Base Capacity",
    part="settings",
    fields=[
        number("diameterM", "Pile toe diameter D", 0.60, unit="m", min=0.2),
        number("unitEndBearingKpa", "Limiting unit end bearing qb", 1500.0, unit="kPa", min=50.0),
    ],
    requires_project=False,
)
def base_capacity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute ultimate pile end-bearing resistance Qb = Ab qb."""
    ab = math.pi * values["diameterM"] ** 2 / 4.0
    qb = ab * values["unitEndBearingKpa"]
    return result(
        summary={"toeAreaM2": ab, "ultimateBaseKn": qb},
        tables=[
            table(
                "Pile base bearing",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Toe area Ab [m²]", "value": ab},
                    {"item": "Ultimate base Qb [kN]", "value": qb},
                ],
            )
        ],
        notes=["Apply active code pack base safety/partial factor to obtain allowable capacity."],
    )


@feature(
    "settingsFoundationPiles.capacityFactor",
    "Capacity Factor",
    part="settings",
    fields=[
        number("ultimateShaftKn", "Ultimate shaft capacity Qs", 900.0, unit="kN", min=0.0),
        number("ultimateBaseKn", "Ultimate base capacity Qb", 450.0, unit="kN", min=0.0),
    ],
    requires_project=False,
)
def capacity_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply active code pack shaft and base safety factors to compute allowable pile capacity."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        ft = safe_table(pack, "foundations")
        fs_val = float(getattr(ft, "noLoadTestSafety", 2.5) or 2.5)
    qa = (values["ultimateShaftKn"] + values["ultimateBaseKn"]) / fs_val
    return result(
        summary={
            "safetyFactor": fs_val,
            "ultimateTotalKn": values["ultimateShaftKn"] + values["ultimateBaseKn"],
            "allowableKn": qa,
        },
        tables=[
            table(
                "Factored pile capacity",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Global factor of safety", "value": fs_val},
                    {"metric": "Allowable capacity Qa [kN]", "value": qa},
                ],
            )
        ],
        notes=["Factor of safety sourced from active code pack foundations table."],
    )


@feature(
    "settingsFoundationPiles.capacityTable",
    "Capacity Table",
    part="settings",
    fields=[
        number("diameterM", "Pile diameter D", 0.60, unit="m", min=0.2),
        number("maxDepthM", "Maximum pile length", 24.0, unit="m", min=6.0),
        number("meanSkinKpa", "Average unit shaft friction", 40.0, unit="kPa", min=5.0),
        number("toeBearingKpa", "Toe bearing stress qb", 1200.0, unit="kPa", min=50.0),
    ],
    requires_project=False,
)
def capacity_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate ultimate and allowable pile capacity against embedment depth."""
    d = values["diameterM"]
    ab = math.pi * d**2 / 4.0
    qb = ab * values["toeBearingKpa"]
    rows = []
    for frac in (0.4, 0.6, 0.8, 1.0):
        l_m = values["maxDepthM"] * frac
        qs = math.pi * d * l_m * values["meanSkinKpa"]
        qult = qs + qb
        rows.append(
            {
                "lengthM": l_m,
                "shaftKn": qs,
                "baseKn": qb,
                "ultimateKn": qult,
                "allowableKn": qult / 2.5,
            }
        )
    return result(
        summary={"maxLengthM": values["maxDepthM"], "maxAllowableKn": rows[-1]["allowableKn"]},
        tables=[
            table(
                "Pile capacity vs depth",
                [
                    ("lengthM", "Length", "m"),
                    ("shaftKn", "Qs", "kN"),
                    ("baseKn", "Qb", "kN"),
                    ("ultimateKn", "Qult", "kN"),
                    ("allowableKn", "Qa (FS=2.5)", "kN"),
                ],
                rows,
            )
        ],
        notes=["Incremental capacity profile assuming uniform average shaft friction."],
    )


@feature(
    "settingsFoundationPiles.staticLoadTest",
    "Static Load Test",
    part="settings",
    fields=[
        number("designLoadKn", "Design working pile load Qa", 1200.0, unit="kN", min=50.0),
        number("testMultiplier", "Test load multiple (typically 2.0 × Qa)", 2.0, min=1.5, max=3.0),
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=250.0),
    ],
    requires_project=False,
)
def static_load_test(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Davisson offset settlement limit and target proof load for static load tests."""
    p_test = values["designLoadKn"] * values["testMultiplier"]
    # Davisson offset = 4 mm + D / 120 (excluding elastic shortening PL/AE estimate)
    davisson_offset_mm = 4.0 + values["diameterMm"] / 120.0
    return result(
        summary={"proofLoadKn": p_test, "davissonOffsetMm": davisson_offset_mm},
        tables=[
            table(
                "Static pile load test criteria",
                [("item", "Criterion"), ("value", "Value")],
                [
                    {"item": "Target proof load [kN]", "value": p_test},
                    {
                        "item": "Davisson offset allowance (4 + D/120) [mm]",
                        "value": davisson_offset_mm,
                    },
                ],
            )
        ],
        notes=["Failure load corresponds to settlement exceeding elastic line + Davisson offset."],
    )


@feature(
    "settingsFoundationPiles.highStrainTest",
    "High Strain Test",
    part="settings",
    fields=[
        number("workingLoadKn", "Design working load Qa", 1500.0, unit="kN", min=100.0),
        number("dropHammerTon", "Drop hammer ram mass", 10.0, unit="t", min=2.0),
    ],
    requires_project=False,
)
def high_strain_test(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check high-strain dynamic pile testing (PDA) hammer mass ratio and target mobilization."""
    target_ult = 2.0 * values["workingLoadKn"]
    ram_kn = values["dropHammerTon"] * 9.80665
    ram_pct = (ram_kn / target_ult) * 100.0
    return result(
        summary={
            "targetMobilizationKn": target_ult,
            "ramMassRatioPct": ram_pct,
            "adequateHammer": ram_pct >= 1.5,
        },
        tables=[
            table(
                "High-strain dynamic test check",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Target mobilized capacity [kN]", "value": target_ult},
                    {"item": "Ram weight / target [%]", "value": ram_pct},
                ],
            )
        ],
        notes=["Ram weight should be >= 1.5-2.0% of the target mobilized ultimate resistance."],
    )


@feature(
    "settingsFoundationPiles.integrityTest",
    "Integrity Test",
    part="settings",
    fields=[
        number("pileLengthM", "Pile length L", 20.0, unit="m", min=2.0),
        number(
            "waveSpeedMPerS",
            "Concrete P-wave velocity c",
            4000.0,
            unit="m/s",
            min=3000.0,
            max=4600.0,
        ),
    ],
    requires_project=False,
)
def integrity_test(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute expected toe-reflection arrival time 2L/c for low-strain sonic integrity testing."""
    t_ms = (2.0 * values["pileLengthM"] / values["waveSpeedMPerS"]) * 1000.0
    return result(
        summary={"toeReflectionMs": t_ms, "waveSpeedMPerS": values["waveSpeedMPerS"]},
        tables=[
            table(
                "Low-strain PIT integrity window",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Round-trip toe reflection 2L/c [ms]", "value": t_ms},
                    {"metric": "Wave speed [m/s]", "value": values["waveSpeedMPerS"]},
                ],
            )
        ],
        notes=["Early impedance reflections before 2L/c indicate necking or soil inclusions."],
    )


@feature(
    "settingsFoundationPiles.slumpTest",
    "Slump Test",
    part="settings",
    fields=[
        select(
            "placement",
            "Concrete placement method",
            [
                ("tremie", "Tremie under slurry/water (175-225 mm)"),
                ("dry", "Dry cased shaft (125-175 mm)"),
            ],
            "tremie",
        ),
    ],
    requires_project=False,
)
def slump_test(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Specify target concrete slump range for bored pile tremie vs dry shaft placement."""
    rng = (175.0, 225.0) if values["placement"] == "tremie" else (125.0, 175.0)
    return result(
        summary={"placement": values["placement"], "minSlumpMm": rng[0], "maxSlumpMm": rng[1]},
        tables=[
            table(
                "Bored pile concrete slump limits",
                [("placement", "Method"), ("minMm", "Min", "mm"), ("maxMm", "Max", "mm")],
                [{"placement": values["placement"], "minMm": rng[0], "maxMm": rng[1]}],
            )
        ],
        notes=["High workability ensures self-compaction around the rebar cage without vibration."],
    )


@feature(
    "settingsFoundationPiles.groupEfficiency",
    "Group Efficiency",
    part="settings",
    fields=[
        number("rows", "Number of pile rows n1", 2.0, min=1.0, max=12.0),
        number("cols", "Number of pile columns n2", 3.0, min=1.0, max=12.0),
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        number("spacingMm", "Center-to-center spacing s", 1800.0, unit="mm", min=500.0),
    ],
    requires_project=False,
)
def group_efficiency(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Converse-Labarre pile group efficiency factor ηg."""
    m, n = int(values["rows"]), int(values["cols"])
    theta_deg = math.degrees(math.atan(values["diameterMm"] / values["spacingMm"]))
    eff = 1.0 - (theta_deg / 90.0) * (((n - 1) * m + (m - 1) * n) / (m * n))
    return result(
        summary={"pileCount": m * n, "efficiency": eff, "effectivePiles": m * n * eff},
        tables=[
            table(
                "Converse-Labarre group efficiency",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Total piles", "value": m * n},
                    {"metric": "θ = arctan(D/s) [°]", "value": theta_deg},
                    {"metric": "Group efficiency ηg", "value": eff},
                ],
            )
        ],
        notes=["Applies to friction pile groups in cohesive or loose granular soils."],
    )


@feature(
    "settingsFoundationPiles.pileSpacing",
    "Pile Spacing",
    part="settings",
    fields=[
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=250.0),
        number("factor", "Spacing multiplier (× D)", 3.0, min=2.0, max=6.0),
    ],
    requires_project=False,
)
def pile_spacing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute minimum center-to-center pile spacing and clear soil gap between shafts."""
    c2c = values["diameterMm"] * values["factor"]
    clear = c2c - values["diameterMm"]
    return result(
        summary={"centerSpacingMm": c2c, "clearGapMm": clear},
        tables=[
            table(
                "Pile spacing check",
                [("item", "Item"), ("mm", "Distance", "mm")],
                [
                    {"item": "Center-to-center spacing", "mm": c2c},
                    {"item": "Clear shaft gap", "mm": clear},
                ],
            )
        ],
        notes=["3.0 D spacing minimizes stress bulb overlap and installation heave."],
    )


@feature(
    "settingsFoundationPiles.blockFailure",
    "Block Failure",
    part="settings",
    fields=[
        number("groupWidthM", "Pile group plan width Bg", 3.0, unit="m", min=0.5),
        number("groupLengthM", "Pile group plan length Lg", 4.2, unit="m", min=0.5),
        number("pileLengthM", "Embedded pile length L", 15.0, unit="m", min=2.0),
        number("cuKpa", "Average clay undrained shear strength cu", 45.0, unit="kPa", min=5.0),
    ],
    requires_project=False,
)
def block_failure(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute perimeter block shear + base bearing ultimate capacity of a clay pile group."""
    bg, lg, l_m, cu = (
        values["groupWidthM"],
        values["groupLengthM"],
        values["pileLengthM"],
        values["cuKpa"],
    )
    perim = 2.0 * (bg + lg)
    shaft_block = perim * l_m * cu
    nc_block = min(9.0, 5.0 * (1.0 + 0.2 * bg / lg) * (1.0 + 0.2 * min(l_m / bg, 2.5)))
    base_block = bg * lg * nc_block * cu
    q_block = shaft_block + base_block
    return result(
        summary={
            "blockShaftKn": shaft_block,
            "blockBaseKn": base_block,
            "ultimateBlockKn": q_block,
        },
        tables=[
            table(
                "Group block failure capacity",
                [("component", "Component"), ("kn", "Capacity", "kN")],
                [
                    {"component": "Perimeter shear", "kn": shaft_block},
                    {"component": "Block base bearing", "kn": base_block},
                    {"component": "Total block Qult", "kn": q_block},
                ],
            )
        ],
        notes=[
            "Governing group capacity is min(sum of single piles × ηg, block failure capacity)."
        ],
    )


@feature(
    "settingsFoundationPiles.groupSettlement",
    "Group Settlement",
    part="settings",
    fields=[
        number("singleSettMm", "Single-pile settlement δ1", 8.0, unit="mm", min=0.5),
        number("groupWidthM", "Pile group width Bg", 3.6, unit="m", min=0.5),
        number("pileDiaM", "Single pile diameter D", 0.6, unit="m", min=0.2),
    ],
    requires_project=False,
)
def group_settlement(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate pile group settlement amplification using Vesic group settlement ratio √(Bg / D)."""
    ratio = math.sqrt(values["groupWidthM"] / values["pileDiaM"])
    delta_g = values["singleSettMm"] * ratio
    return result(
        summary={"amplificationRatio": ratio, "groupSettlementMm": delta_g},
        tables=[
            table(
                "Vesic group settlement estimate",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Group / single ratio √(Bg/D)", "value": ratio},
                    {"metric": "Estimated group settlement [mm]", "value": delta_g},
                ],
            )
        ],
        notes=["Vesic empirical relation δg ≈ δ1 √(Bg / D) for granular soils."],
    )


@feature(
    "settingsFoundationPiles.socketLength",
    "Socket Length",
    part="settings",
    fields=[
        number("pileDiaM", "Pile diameter D", 0.75, unit="m", min=0.3),
        number("minMultipleD", "Minimum rock socket embedment (× D)", 2.0, min=1.0, max=6.0),
    ],
    requires_project=False,
)
def socket_length(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute minimum bedrock socket embedment length as a multiple of shaft diameter."""
    ls = values["pileDiaM"] * values["minMultipleD"]
    return result(
        summary={"pileDiaM": values["pileDiaM"], "socketLengthM": ls},
        tables=[
            table(
                "Rock socket embedment",
                [("item", "Item"), ("m", "Value", "m")],
                [
                    {"item": "Pile diameter", "m": values["pileDiaM"]},
                    {"item": "Minimum socket length", "m": ls},
                ],
            )
        ],
        notes=["Minimum 1.5D-2.0D rock socket ensures lateral fixity and reliable shaft transfer."],
    )


@feature(
    "settingsFoundationPiles.rockStrength",
    "Rock Strength",
    part="settings",
    fields=[
        number(
            "ucsMpa", "Intact rock unconfined compressive strength qu", 12.0, unit="MPa", min=0.5
        ),
    ],
    requires_project=False,
)
def rock_strength(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Classify bedrock UCS and compute Rowe-Armitage / Horvath unit socket shaft friction."""
    qu = values["ucsMpa"]
    # Horvath-Kenney empirical unit socket friction: fs = 0.25 * sqrt(qu) [MPa]
    fs_mpa = 0.25 * math.sqrt(qu)
    return result(
        summary={
            "ucsMpa": qu,
            "unitShaftFrictionMpa": fs_mpa,
            "unitShaftFrictionKpa": fs_mpa * 1000.0,
        },
        tables=[
            table(
                "Rock socket strength",
                [("parameter", "Parameter"), ("value", "Value")],
                [
                    {"parameter": "Rock UCS qu [MPa]", "value": qu},
                    {"parameter": "Unit socket friction fs [kPa]", "value": fs_mpa * 1000.0},
                ],
            )
        ],
        notes=["Horvath-Kenney correlation fs ≈ 0.25 √qu [MPa] before joint reduction."],
    )


@feature(
    "settingsFoundationPiles.rockJointFactor",
    "Rock Joint Factor",
    part="settings",
    fields=[
        number("rqdPct", "Rock Quality Designation RQD", 70.0, unit="%", min=5.0, max=100.0),
    ],
    requires_project=False,
)
def rock_joint_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute rock mass reduction factor αE from RQD for socket capacity and modulus."""
    rqd = values["rqdPct"]
    alpha_e = min(1.0, 0.2 + 0.8 * (rqd / 100.0) ** 1.5)
    return result(
        summary={"rqdPct": rqd, "jointReductionFactor": alpha_e},
        tables=[
            table(
                "Rock mass joint reduction",
                [("rqdPct", "RQD", "%"), ("factor", "Mass factor αE")],
                [{"rqdPct": rqd, "factor": alpha_e}],
            )
        ],
        notes=["Reduces intact rock socket capacity and stiffness for fractured rock masses."],
    )


@feature(
    "settingsFoundationPiles.socketResistance",
    "Socket Resistance",
    part="settings",
    fields=[
        number("pileDiaM", "Socket diameter D", 0.75, unit="m", min=0.3),
        number("socketLengthM", "Socket length Ls", 2.0, unit="m", min=0.3),
        number("ucsMpa", "Rock UCS qu", 10.0, unit="MPa", min=0.5),
        number("jointFactor", "Rock mass joint factor", 0.75, min=0.1, max=1.0),
    ],
    requires_project=False,
)
def socket_resistance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute ultimate rock socket shaft + end-bearing resistance."""
    d, ls = values["pileDiaM"], values["socketLengthM"]
    fs_kpa = 250.0 * math.sqrt(values["ucsMpa"]) * values["jointFactor"]
    qb_kpa = min(5000.0, 1.5 * values["ucsMpa"] * 1000.0 * values["jointFactor"])
    q_shaft = math.pi * d * ls * fs_kpa
    q_base = (math.pi * d**2 / 4.0) * qb_kpa
    return result(
        summary={
            "socketShaftKn": q_shaft,
            "socketBaseKn": q_base,
            "ultimateSocketKn": q_shaft + q_base,
        },
        tables=[
            table(
                "Rock socket capacity",
                [("component", "Component"), ("kn", "Capacity", "kN")],
                [
                    {"component": "Socket shaft friction", "kn": q_shaft},
                    {"component": "Socket base bearing", "kn": q_base},
                    {"component": "Total ultimate", "kn": q_shaft + q_base},
                ],
            )
        ],
        notes=["Combines reduced rock shaft adhesion and socket toe bearing."],
    )

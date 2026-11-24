"""Materials Steel Properties tab: grades, toughness, weldability, fasteners, nonlinear & fatigue models."""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
from saengine.design import steel_connections as SC
from saengine.design.steel import fatigue as SF
from saengine.design.steel import seismic as SS
from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.materials_common import materials_or_default, require_materials
from saengine.library.materials import Category
from saengine.report.clauses import in_force

_STEEL_GRADES = [
    ("A36", 250.0, 400.0, 200000.0),
    ("A572-50", 345.0, 450.0, 200000.0),
    ("A992", 345.0, 450.0, 200000.0),
    ("S235", 235.0, 360.0, 210000.0),
    ("S275", 275.0, 430.0, 210000.0),
    ("S355", 355.0, 510.0, 210000.0),
    ("S460", 460.0, 540.0, 210000.0),
]

_THERMAL_CURVE = [
    (20.0, 1.000, 1.000),
    (100.0, 1.000, 1.000),
    (200.0, 1.000, 0.900),
    (300.0, 1.000, 0.800),
    (400.0, 1.000, 0.700),
    (500.0, 0.780, 0.600),
    (600.0, 0.470, 0.310),
    (700.0, 0.230, 0.130),
    (800.0, 0.110, 0.090),
    (900.0, 0.060, 0.0675),
    (1000.0, 0.040, 0.045),
]


@feature(
    "materialsSteel.gradeLibrary",
    "Grade Library",
    part="materials",
    fields=[text("filterText", "Filter grade name (blank = all)", "")],
    requires_project=False,
)
def grade_library(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Browse project steel/rebar grades alongside common structural steel grades."""
    lib, is_project = materials_or_default(ctx)
    flt = values["filterText"].strip().lower()
    rows = []
    seen = set()
    for m in lib.materials:
        if m.category in (Category.STEEL, Category.REBAR) and m.steel:
            if flt and flt not in m.id.lower() and flt not in m.name.lower():
                continue
            seen.add(m.id)
            rows.append(
                {
                    "grade": m.id,
                    "source": "Project" if is_project else "Default",
                    "category": m.category.value,
                    "fyMpa": m.steel.fy,
                    "fuMpa": m.steel.fu,
                    "modulusMpa": m.mechanical.E,
                }
            )
    for gid, fy, fu, e_val in _STEEL_GRADES:
        if gid in seen:
            continue
        if flt and flt not in gid.lower():
            continue
        rows.append(
            {
                "grade": gid,
                "source": "Catalog",
                "category": "steel",
                "fyMpa": fy,
                "fuMpa": fu,
                "modulusMpa": e_val,
            }
        )
    return result(
        summary={"gradeCount": len(rows)},
        tables=[
            table(
                "Structural steel & rebar grades",
                [
                    ("grade", "Grade"),
                    ("source", "Source"),
                    ("category", "Category"),
                    ("fyMpa", "fy", "MPa"),
                    ("fuMpa", "fu", "MPa"),
                    ("modulusMpa", "E", "MPa"),
                ],
                rows,
            )
        ],
        notes=[
            "Combines active project steel/rebar materials with standard structural steel reference grades."
        ],
    )


@feature(
    "materialsSteel.yieldStrength",
    "Yield Strength",
    part="materials",
    fields=[
        number(
            "nominalFyMpa", "Nominal yield strength fy", 345.0, unit="MPa", min=150.0, max=1000.0
        ),
        text("grade", "Steel grade designation", "A992"),
        number("millFyMpa", "Actual mill test yield (0 = unknown)", 0.0, unit="MPa", min=0.0),
    ],
    requires_project=False,
)
def yield_strength(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate nominal, expected overstrength (Ry * fy), and mill-test yield strengths."""
    fy = values["nominalFyMpa"]
    with in_force(ctx.root):
        try:
            ry = SS.expected_yield_ratio(values["grade"].strip(), "rolled")
        except (KeyError, ValueError, TypeError, AttributeError):
            ry = 1.15 if fy <= 275 else 1.10
    expected_fy = ry * fy
    actual = values["millFyMpa"] if values["millFyMpa"] > 0 else expected_fy
    return result(
        summary={
            "nominalFyMpa": fy,
            "expectedFactorRy": ry,
            "expectedFyMpa": expected_fy,
            "actualOrExpectedMpa": actual,
        },
        tables=[
            table(
                "Steel yield strength summary",
                [
                    ("basis", "Strength basis"),
                    ("fyMpa", "Yield stress", "MPa"),
                    ("ratioToNominal", "Ratio"),
                ],
                [
                    {"basis": "Nominal specified fy", "fyMpa": fy, "ratioToNominal": 1.0},
                    {"basis": "Expected yield Ry * fy", "fyMpa": expected_fy, "ratioToNominal": ry},
                    {
                        "basis": "Mill / effective value",
                        "fyMpa": actual,
                        "ratioToNominal": actual / fy,
                    },
                ],
            )
        ],
        notes=[
            "Expected yield factor Ry queried from saengine.design.steel.seismic under the active code pack."
        ],
    )


@feature(
    "materialsSteel.ultimateStrength",
    "Ultimate Strength",
    part="materials",
    fields=[
        number("fyMpa", "Yield strength fy", 345.0, unit="MPa", min=150.0),
        number("fuMpa", "Ultimate tensile strength fu", 450.0, unit="MPa", min=200.0),
        number("elongationPct", "Fracture elongation", 21.0, unit="%", min=1.0),
    ],
    requires_project=False,
)
def ultimate_strength(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check ultimate tensile strength and fu/fy ductility ratio against limits."""
    fy, fu = values["fyMpa"], values["fuMpa"]
    if fu < fy:
        raise FeatureInputError(
            "Ultimate tensile strength fu cannot be lower than yield strength fy."
        )
    ratio = fu / fy
    with in_force(ctx.root):
        min_ratio = float(code_context.table("materials").fuFyMin)
    return result(
        summary={
            "fyMpa": fy,
            "fuMpa": fu,
            "fuFyRatio": ratio,
            "ductilityOk": ratio >= min_ratio and values["elongationPct"] >= 15.0,
        },
        tables=[
            table(
                "Tensile ductility check",
                [("check", "Check"), ("actual", "Actual"), ("limit", "Minimum"), ("ok", "Pass")],
                [
                    {
                        "check": "fu / fy ratio",
                        "actual": ratio,
                        "limit": min_ratio,
                        "ok": ratio >= min_ratio,
                    },
                    {
                        "check": "Elongation at fracture [%]",
                        "actual": values["elongationPct"],
                        "limit": 15.0,
                        "ok": values["elongationPct"] >= 15.0,
                    },
                ],
            )
        ],
        notes=["Minimum fu/fy ratio read from the active code pack materials table."],
    )


@feature(
    "materialsSteel.thicknessEffect",
    "Thickness Effect",
    part="materials",
    fields=[
        number(
            "baseFyMpa", "Base nominal yield strength (t <= 16 mm)", 355.0, unit="MPa", min=150.0
        ),
        number("thicknessMm", "Plate / flange thickness t", 45.0, unit="mm", min=1.0, max=200.0),
    ],
    requires_project=False,
)
def thickness_effect(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute thickness-dependent yield strength reduction for heavy steel plates/flanges."""
    t = values["thicknessMm"]
    fy0 = values["baseFyMpa"]
    bands = [
        (16.0, 0.0),
        (40.0, 10.0),
        (63.0, 20.0),
        (80.0, 30.0),
        (100.0, 40.0),
        (150.0, 60.0),
        (200.0, 70.0),
    ]
    rows = []
    eff_fy = fy0
    for limit_t, drop in bands:
        fy_band = max(0.75 * fy0, fy0 - drop * (fy0 / 355.0))
        rows.append({"maxThicknessMm": limit_t, "reducedFyMpa": fy_band, "factor": fy_band / fy0})
    for limit_t, drop in bands:
        if t <= limit_t:
            eff_fy = max(0.75 * fy0, fy0 - drop * (fy0 / 355.0))
            break
    else:
        eff_fy = rows[-1]["reducedFyMpa"]
    return result(
        summary={
            "thicknessMm": t,
            "baseFyMpa": fy0,
            "effectiveFyMpa": eff_fy,
            "reductionFactor": eff_fy / fy0,
        },
        tables=[
            table(
                "Plate thickness yield reduction schedule",
                [
                    ("maxThicknessMm", "Max t", "mm"),
                    ("reducedFyMpa", "Effective fy", "MPa"),
                    ("factor", "Factor"),
                ],
                rows,
            )
        ],
        notes=["Applies stepped yield reduction for thicker hot-rolled plates."],
    )


@feature(
    "materialsSteel.charpyValue",
    "Charpy Value",
    part="materials",
    fields=[
        number("measuredEnergyJ", "Measured Charpy V-notch energy", 34.0, unit="J", min=1.0),
        number("requiredEnergyJ", "Specified minimum CVN energy", 27.0, unit="J", min=10.0),
        number("testTempC", "Charpy test temperature", -20.0, unit="C"),
        checkbox("seismicDemand", "Seismic primary structural member", False),
    ],
    requires_project=False,
)
def charpy_value(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify Charpy V-notch impact toughness energy against project and seismic thresholds."""
    req = max(values["requiredEnergyJ"], 27.0 if values["seismicDemand"] else 0.0)
    ok = values["measuredEnergyJ"] >= req
    return result(
        summary={
            "measuredEnergyJ": values["measuredEnergyJ"],
            "requiredEnergyJ": req,
            "testTempC": values["testTempC"],
            "toughnessOk": ok,
        },
        tables=[
            table(
                "Impact toughness check",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "parameter": "Measured CVN energy",
                        "value": values["measuredEnergyJ"],
                        "unit": "J",
                    },
                    {"parameter": "Required minimum energy", "value": req, "unit": "J"},
                    {"parameter": "Test temperature", "value": values["testTempC"], "unit": "C"},
                ],
            )
        ],
        notes=[
            "Standard minimum Charpy V-notch energy threshold is 27 J (40 J for high-restraint thick plates)."
        ],
    )


@feature(
    "materialsSteel.testTemperature",
    "Test Temperature",
    part="materials",
    fields=[
        number("serviceTempC", "Lowest service metal temperature", -10.0, unit="C"),
        number("thicknessMm", "Plate thickness", 32.0, unit="mm", min=4.0),
        number("stressRatio", "Applied stress / fy", 0.75, min=0.2, max=1.0),
    ],
    requires_project=False,
)
def test_temperature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Determine required Charpy impact test temperature from service temp, thickness, and stress."""
    t_serv = values["serviceTempC"]
    # Fracture mechanics thickness + stress shift approximation
    shift_t = -0.7 * max(0.0, values["thicknessMm"] - 12.0) - 25.0 * max(
        0.0, values["stressRatio"] - 0.5
    )
    t_req = t_serv + shift_t
    if t_req >= 20.0:
        grade = "JR (+20 C)"
    elif t_req >= 0.0:
        grade = "J0 (0 C)"
    elif t_req >= -20.0:
        grade = "J2 (-20 C)"
    else:
        grade = "K2 / ML (-40 C)"
    return result(
        summary={
            "serviceTempC": t_serv,
            "requiredTestTempC": t_req,
            "recommendedSubgrade": grade,
        },
        tables=[
            table(
                "Toughness temperature shift",
                [("term", "Term"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"term": "Lowest service temperature", "value": t_serv, "unit": "C"},
                    {"term": "Thickness & stress temperature shift", "value": shift_t, "unit": "C"},
                    {"term": "Required T_27J test temperature", "value": t_req, "unit": "C"},
                ],
            )
        ],
        notes=[f"Recommended steel toughness subgrade: {grade}."],
    )


@feature(
    "materialsSteel.zQuality",
    "Z Quality",
    part="materials",
    fields=[
        number("plateThicknessMm", "Through-thickness plate thickness", 40.0, unit="mm", min=6.0),
        number("weldThroatMm", "Cruciform/T-joint weld leg or throat", 14.0, unit="mm", min=3.0),
        select(
            "restraint",
            "Weld shrinkage restraint",
            [("low", "Low"), ("medium", "Medium"), ("high", "High")],
            "high",
        ),
        number("sulfurPct", "Steel sulfur content S", 0.015, unit="%", min=0.001, max=0.05),
    ],
    requires_project=False,
)
def z_quality(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assess lamellar tearing risk and select required through-thickness Z-quality class."""
    z_a = min(15.0, 0.25 * values["weldThroatMm"])
    z_b = min(8.0, 0.25 * values["plateThicknessMm"])
    z_d = {"low": 0.0, "medium": 5.0, "high": 10.0}[values["restraint"]]
    z_ed = z_a + z_b + z_d
    if z_ed <= 10.0:
        z_class = "Normal (no Z requirement)"
    elif z_ed <= 20.0:
        z_class = "Z15"
    elif z_ed <= 30.0:
        z_class = "Z25"
    else:
        z_class = "Z35"
    return result(
        summary={
            "zDemandIndex": z_ed,
            "requiredZClass": z_class,
            "sulfurLimitOk": values["sulfurPct"] <= 0.010 if z_ed > 10 else True,
        },
        tables=[
            table(
                "Through-thickness lamellar tearing assessment",
                [("factor", "Contribution"), ("points", "Z_Ed points")],
                [
                    {"factor": "Weld size", "points": z_a},
                    {"factor": "Plate thickness", "points": z_b},
                    {"factor": "Joint restraint", "points": z_d},
                    {"factor": "Total Z_Ed demand", "points": z_ed},
                ],
            )
        ],
        notes=[f"Required through-thickness reduction of area class: {z_class}."],
    )


@feature(
    "materialsSteel.weldability",
    "Weldability",
    part="materials",
    fields=[
        number("carbonPct", "Carbon C", 0.18, unit="%", min=0.02, max=0.6),
        number("manganesePct", "Manganese Mn", 1.35, unit="%", min=0.1, max=2.5),
        number("crMoVPct", "Cr + Mo + V", 0.10, unit="%", min=0.0, max=2.0),
        number("niCuPct", "Ni + Cu", 0.20, unit="%", min=0.0, max=3.0),
        number("siliconPct", "Silicon Si", 0.30, unit="%", min=0.0, max=1.0),
    ],
    requires_project=False,
)
def weldability(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute IIW Carbon Equivalent Value (CEV) and Pcm against weldability preheat limits."""
    c, mn = values["carbonPct"], values["manganesePct"]
    cev = c + mn / 6.0 + values["crMoVPct"] / 5.0 + values["niCuPct"] / 15.0
    pcm = (
        c
        + values["siliconPct"] / 30.0
        + mn / 20.0
        + values["niCuPct"] / 60.0
        + values["crMoVPct"] / 15.0
    )
    if cev <= 0.40:
        rating, preheat = "Good weldability", 20.0
    elif cev <= 0.45:
        rating, preheat = "Fair (controlled hydrogen / light preheat)", 75.0
    elif cev <= 0.50:
        rating, preheat = "Moderate (preheat required)", 125.0
    else:
        rating, preheat = "Low (strict preheat & PWHT)", 175.0
    return result(
        summary={
            "cevPercent": cev,
            "pcmPercent": pcm,
            "weldabilityRating": rating,
            "suggestedPreheatC": preheat,
        },
        tables=[
            table(
                "Carbon equivalent weldability check",
                [("index", "Index"), ("value", "Value"), ("limit", "Typical limit")],
                [
                    {"index": "IIW CEV", "value": cev, "limit": 0.45},
                    {"index": "Ito-Bessyo Pcm", "value": pcm, "limit": 0.28},
                ],
            )
        ],
        notes=["CEV = C + Mn/6 + (Cr+Mo+V)/5 + (Ni+Cu)/15."],
    )


@feature(
    "materialsSteel.boltGrades",
    "Bolt Grades",
    part="materials",
    fields=[number("boltDiaMm", "Bolt nominal diameter", 20.0, unit="mm", min=10.0, max=42.0)],
    requires_project=False,
)
def bolt_grades(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List bolt grades and single-bolt shear/tension capacities from the active code pack."""
    dia = values["boltDiaMm"]
    with in_force(ctx.root):
        tbl = code_context.table("steel")
        grades = tbl.connections.boltGrades
        rows = []
        for g in grades:
            v_kn = SC.bolt_shear_capacity(g, dia) / 1000.0
            t_kn, _ = SC.bolt_tension_capacity(g, dia)
            rows.append({"grade": g, "shearKn": v_kn, "tensionKn": t_kn / 1000.0})
    return result(
        summary={"boltDiameterMm": dia, "gradeCount": len(rows)},
        tables=[
            table(
                f"Bolt grade capacities (M{dia:g})",
                [
                    ("grade", "Bolt grade"),
                    ("shearKn", "Design shear", "kN"),
                    ("tensionKn", "Design tension", "kN"),
                ],
                rows,
            )
        ],
        notes=["Computed by saengine.design.steel_connections under the active code pack."],
    )


@feature(
    "materialsSteel.weldStrength",
    "Weld Strength",
    part="materials",
    fields=[
        number("legMm", "Fillet weld leg size w", 8.0, unit="mm", min=3.0, max=25.0),
        number("electrodeMpa", "Electrode tensile strength FEXX", 480.0, unit="MPa", min=360.0),
        number("lengthMm", "Effective weld length", 200.0, unit="mm", min=20.0),
    ],
    requires_project=False,
)
def weld_strength(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute fillet weld design resistance per mm and total weld capacity."""
    with in_force(ctx.root):
        cap_per_mm = SC.fillet_capacity_per_mm(values["legMm"], values["electrodeMpa"])
    total_kn = cap_per_mm * values["lengthMm"] / 1000.0
    return result(
        summary={
            "throatMm": 0.707 * values["legMm"],
            "capacityKnPerMm": cap_per_mm / 1000.0,
            "totalCapacityKn": total_kn,
        },
        tables=[
            table(
                "Fillet weld design strength",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Leg size w", "value": values["legMm"], "unit": "mm"},
                    {
                        "parameter": "Effective throat 0.707 w",
                        "value": 0.707 * values["legMm"],
                        "unit": "mm",
                    },
                    {"parameter": "Design resistance per mm", "value": cap_per_mm, "unit": "N/mm"},
                    {"parameter": "Total weld capacity", "value": total_kn, "unit": "kN"},
                ],
            )
        ],
        notes=["Computed via saengine.design.steel_connections.fillet_capacity_per_mm."],
    )


@feature(
    "materialsSteel.shearPlane",
    "Shear Plane",
    part="materials",
    fields=[
        text("boltGrade", "Bolt grade", "A325N"),
        number("boltDiaMm", "Bolt diameter", 20.0, unit="mm", min=10.0),
        select(
            "planes",
            "Shear planes",
            [("1", "Single shear (1 plane)"), ("2", "Double shear (2 planes)")],
            "1",
        ),
        number("boltCount", "Number of bolts", 4.0, min=1.0),
    ],
    requires_project=False,
)
def shear_plane(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate bolt group shear resistance in single or double shear."""
    planes = int(values["planes"])
    n_bolts = round(values["boltCount"])
    with in_force(ctx.root):
        try:
            v_one = SC.bolt_shear_capacity(values["boltGrade"], values["boltDiaMm"])
        except Exception as exc:
            raise FeatureInputError(str(exc)) from exc
    total_kn = v_one * planes * n_bolts / 1000.0
    return result(
        summary={
            "singlePlaneKn": v_one / 1000.0,
            "perBoltKn": v_one * planes / 1000.0,
            "groupCapacityKn": total_kn,
        },
        tables=[
            table(
                "Bolt shear plane summary",
                [("item", "Item"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Per-plane capacity", "value": v_one / 1000.0, "unit": "kN"},
                    {"item": "Shear planes", "value": planes, "unit": "-"},
                    {"item": "Group shear capacity", "value": total_kn, "unit": "kN"},
                ],
            )
        ],
        notes=["Uses active code pack bolt shear strength via saengine.design.steel_connections."],
    )


@feature(
    "materialsSteel.bearingStrength",
    "Bearing Strength",
    part="materials",
    fields=[
        number("boltDiaMm", "Bolt diameter d", 20.0, unit="mm", min=10.0),
        number("plateThicknessMm", "Connected plate thickness t", 12.0, unit="mm", min=3.0),
        number("plateFuMpa", "Plate ultimate strength fu", 450.0, unit="MPa", min=250.0),
        number("edgeDistanceMm", "End/edge distance e1", 35.0, unit="mm", min=15.0),
        number("spacingMm", "Bolt pitch p1", 60.0, unit="mm", min=25.0),
    ],
    requires_project=False,
)
def bearing_strength(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute bolt hole bearing capacity on connected steel plate."""
    with in_force(ctx.root):
        hole = SC.hole_diameter(values["boltDiaMm"])
        lc_edge = values["edgeDistanceMm"] - hole / 2.0
        lc_inner = values["spacingMm"] - hole
        cap_edge = SC.bearing_capacity(
            values["boltDiaMm"],
            values["plateThicknessMm"],
            values["plateFuMpa"],
            lc_edge,
            "end",
        )
        cap_inner = SC.bearing_capacity(
            values["boltDiaMm"],
            values["plateThicknessMm"],
            values["plateFuMpa"],
            lc_inner,
            "pitch",
        )
    return result(
        summary={
            "endBoltBearingKn": cap_edge / 1000.0,
            "innerBoltBearingKn": cap_inner / 1000.0,
            "holeDiameterMm": hole,
        },
        tables=[
            table(
                "Plate bearing capacity per bolt",
                [
                    ("location", "Bolt position"),
                    ("clearDistMm", "Clear distance lc", "mm"),
                    ("capacityKn", "Bearing capacity", "kN"),
                ],
                [
                    {
                        "location": "End / edge bolt",
                        "clearDistMm": lc_edge,
                        "capacityKn": cap_edge / 1000.0,
                    },
                    {
                        "location": "Inner bolt",
                        "clearDistMm": lc_inner,
                        "capacityKn": cap_inner / 1000.0,
                    },
                ],
            )
        ],
        notes=[
            "Computed via saengine.design.steel_connections.bearing_capacity under the active code pack."
        ],
    )


@feature(
    "materialsSteel.stressStrainCurve",
    "Stress Strain Curve",
    part="materials",
    fields=[
        number("fyMpa", "Yield strength fy", 345.0, unit="MPa", min=150.0),
        number("fuMpa", "Ultimate tensile strength fu", 450.0, unit="MPa", min=200.0),
        number("modulusMpa", "Elastic modulus E", 200000.0, unit="MPa", min=100000.0),
        number(
            "hardeningStrain", "Strain at onset of hardening eps_sh", 0.015, min=0.003, max=0.05
        ),
        number("ultimateStrain", "Ultimate uniform strain eps_u", 0.15, min=0.05, max=0.30),
    ],
    requires_project=False,
)
def steel_stress_strain_curve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate quad-linear structural steel constitutive stress-strain backbone."""
    fy, fu, e0 = values["fyMpa"], values["fuMpa"], values["modulusMpa"]
    eps_y = fy / e0
    eps_sh = max(values["hardeningStrain"], eps_y * 1.5)
    eps_u = max(values["ultimateStrain"], eps_sh * 2.0)
    pts = [
        (0.0, 0.0, e0),
        (eps_y, fy, e0),
        (eps_sh, fy, 0.0),
        (0.5 * (eps_sh + eps_u), 0.5 * (fy + fu), (fu - fy) / (eps_u - eps_sh)),
        (eps_u, fu, (fu - fy) / (eps_u - eps_sh)),
    ]
    rows = [{"strain": round(e, 6), "stressMpa": s, "tangentMpa": et} for e, s, et in pts]
    return result(
        summary={
            "yieldStrain": eps_y,
            "hardeningModulusMpa": (fu - fy) / (eps_u - eps_sh),
            "ductilityRatio": eps_u / eps_y,
        },
        tables=[
            table(
                "Steel quad-linear stress-strain model",
                [
                    ("strain", "Strain", "-"),
                    ("stressMpa", "Stress", "MPa"),
                    ("tangentMpa", "Tangent E", "MPa"),
                ],
                rows,
            )
        ],
        notes=["Elastic -> yield plateau -> linear strain hardening to (eps_u, fu)."],
    )


@feature(
    "materialsSteel.strainHardening",
    "Strain Hardening",
    part="materials",
    fields=[
        number("modulusMpa", "Elastic modulus E0", 200000.0, unit="MPa", min=100000.0),
        number("fyMpa", "Yield strength fy", 345.0, unit="MPa", min=150.0),
        number(
            "hardeningRatioB", "Post-yield stiffness ratio b = Esh/E0", 0.015, min=0.001, max=0.10
        ),
        number("targetStrain", "Target total strain", 0.025, min=0.002, max=0.20),
    ],
    requires_project=False,
)
def strain_hardening(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute plastic hardening modulus, tangent slope, and hardened stress at target strain."""
    e0, fy, b = values["modulusMpa"], values["fyMpa"], values["hardeningRatioB"]
    eps_y = fy / e0
    e_sh = b * e0
    eps_p = max(0.0, values["targetStrain"] - eps_y)
    sigma = fy + e_sh * eps_p if values["targetStrain"] > eps_y else e0 * values["targetStrain"]
    return result(
        summary={
            "hardeningModulusMpa": e_sh,
            "plasticStrain": eps_p,
            "stressAtTargetMpa": sigma,
            "overstrengthRatio": sigma / fy,
        },
        tables=[
            table(
                "Bilinear kinematic/isotropic hardening",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Yield strain eps_y", "value": round(eps_y, 6), "unit": "-"},
                    {"parameter": "Hardening modulus E_sh = b*E0", "value": e_sh, "unit": "MPa"},
                    {"parameter": "Plastic strain eps_p", "value": round(eps_p, 6), "unit": "-"},
                    {"parameter": "Hardened stress", "value": sigma, "unit": "MPa"},
                ],
            )
        ],
        notes=["Consistent with Steel02 bilinear strain-hardening parameter b."],
    )


@feature(
    "materialsSteel.thermalSoftening",
    "Thermal Softening",
    part="materials",
    fields=[
        number("fyMpa", "Ambient yield strength fy (20 C)", 345.0, unit="MPa", min=150.0),
        number(
            "modulusMpa", "Ambient elastic modulus E (20 C)", 200000.0, unit="MPa", min=100000.0
        ),
        number("steelTempC", "Elevated steel temperature", 550.0, unit="C", min=20.0, max=1000.0),
    ],
    requires_project=False,
)
def thermal_softening(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Interpolate elevated-temperature steel strength and stiffness reduction factors."""
    t_target = values["steelTempC"]
    ky = ke = 1.0
    for i in range(1, len(_THERMAL_CURVE)):
        t1, ky1, ke1 = _THERMAL_CURVE[i - 1]
        t2, ky2, ke2 = _THERMAL_CURVE[i]
        if t1 <= t_target <= t2:
            w = (t_target - t1) / (t2 - t1)
            ky = ky1 + w * (ky2 - ky1)
            ke = ke1 + w * (ke2 - ke1)
            break
    rows = [
        {
            "tempC": t,
            "ky": y,
            "ke": e,
            "fyThetaMpa": y * values["fyMpa"],
            "eThetaMpa": e * values["modulusMpa"],
        }
        for t, y, e in _THERMAL_CURVE
    ]
    return result(
        summary={
            "steelTempC": t_target,
            "yieldRetentionKy": ky,
            "modulusRetentionKe": ke,
            "reducedFyMpa": ky * values["fyMpa"],
            "reducedModulusMpa": ke * values["modulusMpa"],
        },
        tables=[
            table(
                "Elevated temperature steel retention",
                [
                    ("tempC", "Temp", "C"),
                    ("ky", "ky"),
                    ("ke", "kE"),
                    ("fyThetaMpa", "fy(T)", "MPa"),
                    ("eThetaMpa", "E(T)", "MPa"),
                ],
                rows,
            )
        ],
        notes=["Standard structural carbon steel elevated-temperature retention curve."],
    )


@feature(
    "materialsSteel.bauschingerEffect",
    "Bauschinger Effect",
    part="materials",
    fields=[
        number("fyMpa", "Yield strength fy", 345.0, unit="MPa", min=150.0),
        number("modulusMpa", "Elastic modulus E0", 200000.0, unit="MPa", min=100000.0),
        number("bRatio", "Hardening ratio b", 0.01, min=0.001, max=0.1),
        number("r0", "Menegotto-Pinto curvature R0", 18.0, min=10.0, max=25.0),
        number("xiPlastic", "Max prior plastic strain excursion xi", 0.02, min=0.0, max=0.15),
    ],
    requires_project=False,
)
def bauschinger_effect(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Menegotto-Pinto (Steel02) cyclic curvature transition and Bauschinger softening."""
    cr1, cr2 = 0.925, 0.15
    xi = values["xiPlastic"] / (values["fyMpa"] / values["modulusMpa"])
    r_eff = values["r0"] - (cr1 * xi) / (cr2 + xi)
    rows = []
    for i in range(1, 11):
        eps_star = i / 10.0 * 2.0
        b = values["bRatio"]
        sig_star = b * eps_star + (1.0 - b) * eps_star / ((1.0 + eps_star**r_eff) ** (1.0 / r_eff))
        rows.append({"normalizedStrain": eps_star, "normalizedStress": sig_star})
    return result(
        summary={
            "initialR0": values["r0"],
            "degradedR": r_eff,
            "hardeningRatioB": values["bRatio"],
        },
        tables=[
            table(
                "Menegotto-Pinto cyclic transition curve",
                [("normalizedStrain", "eps*"), ("normalizedStress", "sigma*")],
                rows,
            )
        ],
        notes=[
            "Matches Steel02 formulation in saengine.fem.nonlinear (R0=18, cR1=0.925, cR2=0.15)."
        ],
    )


@feature(
    "materialsSteel.snCurve",
    "SN Curve",
    part="materials",
    fields=[text("category", "Fatigue detail category", "C")],
    requires_project=False,
)
def sn_curve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate design stress range F_SR across cycle counts using the active code pack."""
    cat = values["category"].strip() or "C"
    cycle_pts = [20_000, 50_000, 100_000, 500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000]
    rows = []
    with in_force(ctx.root):
        try:
            for n in cycle_pts:
                fsr = SF.design_stress_range(cat, float(n))
                rows.append({"cycles": n, "designStressRangeMpa": fsr})
        except KeyError as exc:
            raise FeatureInputError(str(exc)) from exc
    return result(
        summary={
            "category": cat,
            "fsrAt2MillionMpa": next(
                r["designStressRangeMpa"] for r in rows if r["cycles"] == 2_000_000
            ),
            "thresholdMpa": rows[-1]["designStressRangeMpa"],
        },
        tables=[
            table(
                f"S-N curve for category {cat}",
                [("cycles", "Cycles N"), ("designStressRangeMpa", "Design stress range", "MPa")],
                rows,
            )
        ],
        notes=[
            "Computed via saengine.design.steel.fatigue.design_stress_range under the code pack in force."
        ],
    )


@feature(
    "materialsSteel.enduranceLimit",
    "Endurance Limit",
    part="materials",
    fields=[
        number(
            "appliedRangeMpa", "Applied constant-amplitude stress range", 65.0, unit="MPa", min=1.0
        )
    ],
    requires_project=False,
)
def endurance_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List constant-amplitude fatigue threshold (endurance limit) for every code pack category."""
    applied = values["appliedRangeMpa"]
    rows = []
    with in_force(ctx.root):
        tbl = code_context.table("fatigue")
        for cat, row in tbl.categories.items():
            fth = float(row.threshold)
            rows.append(
                {
                    "category": cat,
                    "cf": float(row.Cf),
                    "thresholdMpa": fth,
                    "infiniteLife": applied < fth,
                }
            )
    return result(
        summary={
            "appliedRangeMpa": applied,
            "categoriesPassingThreshold": sum(1 for r in rows if r["infiniteLife"]),
            "totalCategories": len(rows),
        },
        tables=[
            table(
                "Constant-amplitude fatigue thresholds",
                [
                    ("category", "Category"),
                    ("cf", "Constant Cf"),
                    ("thresholdMpa", "Threshold F_TH", "MPa"),
                    ("infiniteLife", "Below threshold"),
                ],
                rows,
            )
        ],
        notes=[
            "Categories with stress range below F_TH are exempt from finite-life fatigue degradation."
        ],
    )


@feature(
    "materialsSteel.fatigueCategory",
    "Fatigue Category",
    part="materials",
    fields=[
        text("category", "Fatigue detail category", "C"),
        number("cyclesPerDay", "Stress cycles per day", 150.0, min=1.0),
        number("designLifeYears", "Design service life", 50.0, unit="years", min=1.0),
        number("stressRangeMpa", "Applied stress range", 85.0, unit="MPa", min=1.0),
        number("maxServiceStressMpa", "Max unfactored service stress", 180.0, unit="MPa", min=1.0),
        number("fyMpa", "Steel yield strength fy", 345.0, unit="MPa", min=150.0),
    ],
    requires_project=False,
)
def fatigue_category(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Run the code pack fatigue stress-range check for a selected steel detail category."""
    n_tot = SF.cycles(values["cyclesPerDay"], values["designLifeYears"])
    with in_force(ctx.root):
        try:
            res = SF.check(
                values["category"].strip() or "C",
                n_tot,
                values["stressRangeMpa"],
                values["maxServiceStressMpa"],
                values["fyMpa"],
            )
        except KeyError as exc:
            raise FeatureInputError(str(exc)) from exc
    d = res.as_dict()
    return result(
        summary={
            "category": res.category,
            "totalCycles": round(res.cycles),
            "designRangeMpa": res.design_range if res.design_range is not None else 0.0,
            "utilisation": d["ratio"] if d["ratio"] is not None else 0.0,
            "ok": res.ok,
        },
        tables=[
            table(
                "Fatigue category check",
                [("parameter", "Parameter"), ("value", "Value")],
                [{"parameter": k, "value": v} for k, v in d.items()],
            )
        ],
        notes=["Evaluated using saengine.design.steel.fatigue.check under the project code pack."],
    )


@feature(
    "materialsSteel.sectionMaterial",
    "Section Material",
    part="materials",
    fields=[],
    requires_project=True,
)
def section_material(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map structural steel and rebar grades in 03 Materials to object types in 04 Objects."""
    lib = require_materials(ctx)
    objects = (ctx.raw("objects") or {}).get("objects") or []
    mat_map = {m.id: m for m in lib.materials}
    rows = []
    steel_count = 0
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        mid = obj.get("material", "")
        mat = mat_map.get(mid)
        prof = (obj.get("profile") or {}).get("shape", obj.get("kind", "-"))
        is_steel = mat is not None and mat.category in (Category.STEEL, Category.REBAR)
        if is_steel:
            steel_count += 1
        fy = mat.steel.fy if (mat and mat.steel) else None
        rows.append(
            {
                "objectId": obj.get("id", ""),
                "kind": obj.get("kind", ""),
                "profile": prof,
                "materialId": mid,
                "category": mat.category.value if mat else "missing",
                "fyMpa": fy,
            }
        )
    return result(
        summary={"objectTypeCount": len(rows), "steelObjectCount": steel_count},
        tables=[
            table(
                "Object type material assignments",
                [
                    ("objectId", "Object type"),
                    ("kind", "Kind"),
                    ("profile", "Profile"),
                    ("materialId", "Material"),
                    ("category", "Category"),
                    ("fyMpa", "fy", "MPa"),
                ],
                rows,
            )
        ],
        notes=[
            "Reads 04 Objects/objects.json and resolves materials against 03 Materials/materials.json."
        ],
    )


@feature(
    "materialsSteel.coldFormedModulus",
    "Cold Formed Modulus",
    part="materials",
    fields=[
        number("virginFyMpa", "Virgin sheet yield strength fyb", 300.0, unit="MPa", min=150.0),
        number("virginFuMpa", "Virgin sheet tensile strength fub", 400.0, unit="MPa", min=200.0),
        number("thicknessMm", "Sheet thickness t", 2.0, unit="mm", min=0.5, max=12.0),
        number("bendRadiusMm", "Internal bend radius r", 3.0, unit="mm", min=0.5),
        number("cornerCount", "Number of 90-degree bends m", 4.0, min=0.0, max=20.0),
        number("grossAreaMm2", "Gross section area Ag", 650.0, unit="mm2", min=50.0),
    ],
    requires_project=False,
)
def cold_formed_modulus(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute cold-formed steel corner-enhanced average yield strength fya."""
    fyb, fub, t, r = (
        values["virginFyMpa"],
        values["virginFuMpa"],
        values["thicknessMm"],
        values["bendRadiusMm"],
    )
    # Corner area for m 90-degree bends: Ac = m * (pi/2) * t * (r + t/2)
    ac = values["cornerCount"] * (math.pi / 2.0) * t * (r + t / 2.0)
    k = min(7.0, 7.0)  # cold-forming coefficient
    # Corner yield strength increase (Karren / standard cold-formed formula)
    bc = 3.69 * (fub / fyb) - 0.819 * (fub / fyb) ** 2 - 1.79
    m_exp = 0.192 * (fub / fyb) - 0.068
    fyc = min(fub, bc * fyb / ((r / t) ** m_exp))
    fya = fyb + (fyc - fyb) * min(1.0, ac / values["grossAreaMm2"]) * (k / 7.0)
    return result(
        summary={
            "virginFyMpa": fyb,
            "cornerFyMpa": fyc,
            "averageFyMpa": fya,
            "enhancementPercent": (fya - fyb) / fyb * 100.0,
        },
        tables=[
            table(
                "Cold-formed corner enhancement",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Total corner area", "value": ac, "unit": "mm2"},
                    {"parameter": "Corner yield strength fyc", "value": fyc, "unit": "MPa"},
                    {"parameter": "Average section yield fya", "value": fya, "unit": "MPa"},
                ],
            )
        ],
        notes=["Karren cold-work corner enhancement model for 90-degree formed bends."],
    )


@feature(
    "materialsSteel.residualStressProfile",
    "Residual Stress Profile",
    part="materials",
    fields=[
        select(
            "fabrication",
            "Section fabrication",
            [("rolled", "Hot-rolled I/H section"), ("welded", "Welded built-up I/H section")],
            "rolled",
        ),
        number("depthWidthRatio", "Section aspect h/b", 1.5, min=0.8, max=4.0),
        number("fyMpa", "Nominal yield fy", 345.0, unit="MPa", min=150.0),
    ],
    requires_project=False,
)
def residual_stress_profile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute representative residual stress distribution across hot-rolled or welded I-sections."""
    fy = values["fyMpa"]
    if values["fabrication"] == "rolled":
        frac = 0.50 if values["depthWidthRatio"] <= 1.2 else 0.30
        sigma_rc = -frac * fy
        sigma_rt = 0.30 * fy
        curve_note = "Moderate residual stress (curves a/b for major, b/c for minor)"
    else:
        sigma_rc = -0.50 * fy
        sigma_rt = 1.00 * fy
        curve_note = "High weld-zone tensile residual stress (curves b/c for major, c/d for minor)"
    rows = [
        {
            "location": "Flange tips",
            "stressMpa": sigma_rc,
            "ratioToFy": sigma_rc / fy,
            "state": "Compression",
        },
        {
            "location": "Flange-web junction",
            "stressMpa": sigma_rt,
            "ratioToFy": sigma_rt / fy,
            "state": "Tension",
        },
        {
            "location": "Web mid-depth",
            "stressMpa": -0.25 * fy,
            "ratioToFy": -0.25,
            "state": "Compression",
        },
    ]
    return result(
        summary={
            "fabrication": values["fabrication"],
            "peakCompressiveMpa": sigma_rc,
            "peakTensileMpa": sigma_rt,
        },
        tables=[
            table(
                "Residual stress pattern",
                [
                    ("location", "Location"),
                    ("stressMpa", "Residual stress", "MPa"),
                    ("ratioToFy", "sigma_r / fy"),
                    ("state", "Sign"),
                ],
                rows,
            )
        ],
        notes=[curve_note],
    )

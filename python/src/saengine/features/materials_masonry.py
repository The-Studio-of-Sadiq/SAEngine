"""Materials Masonry, Timber & Other tab: masonry, mortar/grout, timber, glulam/CLT, composites, glass & aluminium."""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
from saengine.design import masonry as M
from saengine.design import masonry_anchors as MA
from saengine.design.timber import connections as TC
from saengine.design.timber import members as TM
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
from saengine.features.materials_common import parse_numbers
from saengine.library.materials import (
    AluminiumProperties,
    Category,
    GlassProperties,
    MasonryProperties,
    Material,
    Mechanical,
    TimberProperties,
)
from saengine.report.clauses import in_force


@feature(
    "libraryMasonry.addMasonry",
    "Add Masonry",
    part="materials",
    fields=[
        text("materialId", "Material ID", "MASONRY-1"),
        text("unitName", "Unit description", "Clay brick"),
        select(
            "unitKind",
            "Unit kind",
            [("clay", "Clay brick"), ("concrete", "Concrete block")],
            "clay",
        ),
        select("units", "Unit solidity", [("solid", "Solid"), ("hollow", "Hollow")], "solid"),
        number("unitStrengthMpa", "Unit compressive strength", 15.0, unit="MPa", min=1.0),
        text("mortarGrade", "Mortar grade (blank = default)", "M2"),
        checkbox("specialInspection", "Special inspection & prism tests", False),
    ],
    requires_project=False,
)
def add_masonry(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create and validate a masonry material and estimate f'm from the code pack."""
    mid = values["materialId"].strip() or "MASONRY-1"
    mortar = values["mortarGrade"].strip() or None
    mat = Material(
        id=mid,
        name=f"{values['unitName'].strip() or 'Masonry'} ({mid})",
        category=Category.MASONRY,
        mechanical=Mechanical(density=1920.0 if values["unitKind"] == "clay" else 2100.0),
        masonry=MasonryProperties(
            unit=values["unitName"].strip() or "brick",
            unitStrength=values["unitStrengthMpa"],
            unitKind=values["unitKind"],
            units=values["units"],
            mortarType=mortar,
            specialInspection=values["specialInspection"],
        ),
    )
    with in_force(ctx.root):
        est_fm = M.prism_estimate(values["unitStrengthMpa"], values["unitKind"], mortar)
        if est_fm is None:
            est_fm = 0.35 * values["unitStrengthMpa"]
        m_obj = M.Masonry(
            fm=est_fm,
            kind=values["unitKind"],
            mortar=mortar,
            units=values["units"],
            inspected=values["specialInspection"],
            unit_strength=values["unitStrengthMpa"],
        )
        em = m_obj.em
        gm = m_obj.g
    return result(
        summary={
            "materialId": mat.id,
            "estimatedFmMpa": est_fm,
            "elasticModulusMpa": em,
            "shearModulusMpa": gm,
        },
        tables=[
            table(
                "Masonry material properties",
                [("property", "Property"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "property": "Unit strength",
                        "value": values["unitStrengthMpa"],
                        "unit": "MPa",
                    },
                    {"property": "Estimated masonry f'm", "value": est_fm, "unit": "MPa"},
                    {"property": "Elastic modulus Em", "value": em, "unit": "MPa"},
                    {"property": "Shear modulus G", "value": gm, "unit": "MPa"},
                ],
            )
        ],
        notes=[
            "Uses saengine.design.masonry.prism_estimate and elastic properties under code pack in force."
        ],
    )


@feature(
    "libraryMasonry.blockTypes",
    "Block Types",
    part="materials",
    fields=[
        number("lengthMm", "Block length", 390.0, unit="mm", min=50.0),
        number("widthMm", "Block width (thickness)", 190.0, unit="mm", min=50.0),
        number("heightMm", "Block height", 190.0, unit="mm", min=40.0),
        number("hollowPercent", "Void ratio", 40.0, unit="%", min=0.0, max=70.0),
        number("grossStrengthMpa", "Gross compressive strength", 10.0, unit="MPa", min=1.0),
    ],
    requires_project=False,
)
def block_types(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate block geometry, net bedded area, and net vs gross compressive strength."""
    gross_area = values["lengthMm"] * values["widthMm"]
    net_ratio = 1.0 - values["hollowPercent"] / 100.0
    net_area = gross_area * net_ratio
    net_strength = values["grossStrengthMpa"] / max(net_ratio, 0.1)
    unit_type = "solid" if values["hollowPercent"] <= 25.0 else "hollow"
    return result(
        summary={
            "grossAreaMm2": gross_area,
            "netAreaMm2": net_area,
            "netStrengthMpa": net_strength,
            "unitCategory": unit_type,
        },
        tables=[
            table(
                "Masonry block geometry & strength",
                [("property", "Property"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"property": "Gross area", "value": gross_area, "unit": "mm2"},
                    {"property": "Net bedded area", "value": net_area, "unit": "mm2"},
                    {
                        "property": "Gross strength",
                        "value": values["grossStrengthMpa"],
                        "unit": "MPa",
                    },
                    {"property": "Net area strength", "value": net_strength, "unit": "MPa"},
                ],
            )
        ],
        notes=[f"Classified as '{unit_type}' masonry unit (<=25% voids treated as solid)."],
    )


@feature(
    "libraryMasonry.mortarClasses",
    "Mortar Classes",
    part="materials",
    fields=[number("sandParts", "Sand parts per 1 part cement", 4.0, min=1.0, max=10.0)],
    requires_project=False,
)
def mortar_classes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List code pack mortar classes and resolve mortar grade from cement:sand ratio."""
    with in_force(ctx.root):
        mortars = M.table().mortars
        matched = M.mortar_grade_of_mix(values["sandParts"], 1.0)
        rows = [
            {
                "grade": g,
                "cement": float(mortars[g].cement),
                "sand": float(mortars[g].sand),
                "strengthMpa": float(mortars[g].strength),
                "selected": g == matched,
            }
            for g in M.mortar_grades()
        ]
    return result(
        summary={"matchedGrade": matched or "leaner-than-table", "classCount": len(rows)},
        tables=[
            table(
                "Code pack mortar classes",
                [
                    ("grade", "Grade"),
                    ("cement", "Cement"),
                    ("sand", "Sand"),
                    ("strengthMpa", "Strength", "MPa"),
                    ("selected", "Matched"),
                ],
                rows,
            )
        ],
        notes=["Reads mortar classes directly from the code pack masonry table."],
    )


@feature(
    "libraryMasonry.masonryPrisms",
    "Masonry Prisms",
    part="materials",
    fields=[
        text("prismMpa", "Measured prism compressive strengths [MPa]", "7.8, 8.4, 8.1"),
        number("heightMm", "Prism height hp", 400.0, unit="mm", min=100.0),
        number("thicknessMm", "Prism thickness tp", 190.0, unit="mm", min=50.0),
    ],
    requires_project=False,
)
def masonry_prisms(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Reduce prism test results with height-to-thickness h/t aspect correction."""
    vals = parse_numbers(values["prismMpa"], "Prism strengths")
    hp_tp = values["heightMm"] / values["thicknessMm"]
    # Standard prism h/t correction factor (1.0 at h/t = 2.0, ~1.22 at h/t = 5.0)
    k_ht = max(0.75, min(1.25, 0.78 + 0.11 * hp_tp))
    corr = [v * k_ht for v in vals]
    mean = sum(corr) / len(corr)
    std = math.sqrt(sum((x - mean) ** 2 for x in corr) / (len(corr) - 1)) if len(corr) > 1 else 0.0
    fm = max(0.5, mean - 1.5 * std)
    rows = [
        {"prism": i + 1, "rawMpa": r, "correctedMpa": c}
        for i, (r, c) in enumerate(zip(vals, corr, strict=True))
    ]
    return result(
        summary={
            "prismCount": len(vals),
            "aspectRatio": hp_tp,
            "correctionFactor": k_ht,
            "meanCorrectedMpa": mean,
            "designFmMpa": fm,
        },
        tables=[
            table(
                "Masonry prism test reduction",
                [
                    ("prism", "Prism #"),
                    ("rawMpa", "Raw", "MPa"),
                    ("correctedMpa", "Corrected", "MPa"),
                ],
                rows,
            )
        ],
        notes=["Applies h/t platen-restraint correction and 1.5s reduction for design f'm."],
    )


@feature(
    "libraryMasonry.addTimber",
    "Add Timber",
    part="materials",
    fields=[
        text("materialId", "Material ID", "TIMBER-B"),
        select(
            "group", "Strength group", [("A", "Group A"), ("B", "Group B"), ("C", "Group C")], "B"
        ),
        select(
            "location",
            "Moisture / exposure",
            [("inside", "Inside (dry)"), ("outside", "Outside"), ("wet", "Wet")],
            "inside",
        ),
        select(
            "grade",
            "Timber grade",
            [("select", "Select"), ("I", "Grade I"), ("II", "Grade II")],
            "I",
        ),
        number("densityKgPerM3", "Mass density", 650.0, unit="kg/m3", min=300.0),
    ],
    requires_project=False,
)
def add_timber(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a structural timber material and look up permissible stresses from the code pack."""
    with in_force(ctx.root):
        tbl = code_context.table("timber")
        grp = tbl.groups[values["group"]]
        grade_val = tbl.grades[values["grade"]]
        grade_f = float(getattr(grade_val, "factor", grade_val))
        e_val = float(grp.E)
        fb = float(grp.bending[values["location"]]) * grade_f
        fc_par = float(grp.compressionParallel[values["location"]]) * grade_f
    mat = Material(
        id=values["materialId"].strip() or "TIMBER-B",
        name=f"Timber Group {values['group']} ({values['grade']})",
        category=Category.TIMBER,
        mechanical=Mechanical(E=e_val, density=values["densityKgPerM3"]),
        timber=TimberProperties(
            group=values["group"], location=values["location"], grade=values["grade"]
        ),
    )
    return result(
        summary={
            "materialId": mat.id,
            "modulusMpa": e_val,
            "bendingStrengthMpa": fb,
            "compressionParallelMpa": fc_par,
        },
        tables=[
            table(
                "Timber material properties",
                [("property", "Property"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"property": "Elastic modulus E", "value": e_val, "unit": "MPa"},
                    {"property": "Bending stress fb", "value": fb, "unit": "MPa"},
                    {"property": "Compression parallel fc", "value": fc_par, "unit": "MPa"},
                    {"property": "Grade factor", "value": grade_f, "unit": "-"},
                ],
            )
        ],
        notes=["Validates TimberProperties schema and queries code pack timber groups."],
    )


@feature(
    "libraryMasonry.timberGrades",
    "Timber Grades",
    part="materials",
    fields=[
        select(
            "location",
            "Exposure location",
            [("inside", "Inside"), ("outside", "Outside"), ("wet", "Wet")],
            "inside",
        )
    ],
    requires_project=False,
)
def timber_grades(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare softwood/hardwood strength groups and grade factors in the code pack."""
    loc = values["location"]
    with in_force(ctx.root):
        tbl = code_context.table("timber")
        rows = [
            {
                "group": k,
                "modulusMpa": float(g.E),
                "bendingMpa": float(g.bending[loc]),
                "tensionMpa": float(g.tension[loc]),
                "compParallelMpa": float(g.compressionParallel[loc]),
                "shearMpa": float(g.shearHorizontal),
            }
            for k, g in tbl.groups.items()
        ]
    return result(
        summary={"groupCount": len(rows), "speciesCount": len(tbl.species), "location": loc},
        tables=[
            table(
                f"Timber strength groups ({loc})",
                [
                    ("group", "Group"),
                    ("modulusMpa", "E", "MPa"),
                    ("bendingMpa", "Bending", "MPa"),
                    ("tensionMpa", "Tension", "MPa"),
                    ("compParallelMpa", "Comp //", "MPa"),
                    ("shearMpa", "Shear", "MPa"),
                ],
                rows,
            )
        ],
        notes=[f"Code pack lists {len(tbl.species)} species across {len(rows)} strength groups."],
    )


@feature(
    "libraryMasonry.glulam",
    "Glulam",
    part="materials",
    fields=[
        number("widthMm", "Section width b", 140.0, unit="mm", min=40.0),
        number("laminationCount", "Number of laminations", 12.0, min=2.0, max=60.0),
        number("lamThicknessMm", "Lamination thickness", 33.0, unit="mm", min=15.0, max=50.0),
        number("fbMpa", "Characteristic bending strength fm,g,k", 28.0, unit="MPa", min=10.0),
        number("e0MeanMpa", "Mean parallel modulus E0,mean", 12600.0, unit="MPa", min=5000.0),
    ],
    requires_project=False,
)
def glulam(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute glued laminated timber lay-up depth, size factor, and bending stiffness."""
    n_lam = round(values["laminationCount"])
    h = n_lam * values["lamThicknessMm"]
    b = values["widthMm"]
    kh = min(1.1, (600.0 / h) ** 0.1) if h < 600.0 else 1.0
    iy = b * h**3 / 12.0
    wy = b * h**2 / 6.0
    m_char = values["fbMpa"] * kh * wy / 1e6
    return result(
        summary={
            "totalDepthMm": h,
            "laminationCount": n_lam,
            "sizeFactorKh": kh,
            "flexuralRigidityKnM2": values["e0MeanMpa"] * iy / 1e9,
            "characteristicMomentKnM": m_char,
        },
        tables=[
            table(
                "Glulam lay-up summary",
                [("property", "Property"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"property": "Width b", "value": b, "unit": "mm"},
                    {"property": "Depth h", "value": h, "unit": "mm"},
                    {"property": "Size factor kh", "value": kh, "unit": "-"},
                    {"property": "Section modulus Wy", "value": wy / 1e3, "unit": "cm3"},
                    {"property": "Characteristic moment", "value": m_char, "unit": "kN-m"},
                ],
            )
        ],
        notes=["Size factor kh = min(1.1, (600/h)^0.1) for glulam depth h <= 600 mm."],
    )


@feature(
    "libraryMasonry.cltPanels",
    "CLT Panels",
    part="materials",
    fields=[
        text(
            "plyThicknessMm",
            "Ply thicknesses [mm] (comma-separated, odd count)",
            "40, 20, 40, 20, 40",
        ),
        number("e0Mpa", "Lamella longitudinal modulus E0", 11000.0, unit="MPa", min=3000.0),
        number("g90Mpa", "Rolling shear modulus G90", 50.0, unit="MPa", min=20.0),
        number("spanM", "Panel span", 5.0, unit="m", min=1.0),
    ],
    requires_project=False,
)
def clt_panels(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Cross-Laminated Timber effective bending & shear stiffness per metre width."""
    plies = parse_numbers(values["plyThicknessMm"], "Ply thicknesses")
    h = sum(plies)
    e0 = values["e0Mpa"]
    e90 = e0 / 30.0
    z_bot = -h / 2.0
    ei_eff = 0.0
    ea_eff = 0.0
    rows = []
    for idx, t in enumerate(plies, 1):
        z_mid = z_bot + t / 2.0
        z_bot += t
        parallel = idx % 2 == 1
        ei_ply = (e0 if parallel else e90) * (1000.0 * t**3 / 12.0 + 1000.0 * t * z_mid**2)
        ea_ply = (e0 if parallel else e90) * 1000.0 * t
        ei_eff += ei_ply
        ea_eff += ea_ply
        rows.append(
            {
                "ply": idx,
                "orientation": "0 deg (major)" if parallel else "90 deg (cross)",
                "thicknessMm": t,
                "eiShareKnM2": ei_ply / 1e9,
            }
        )
    # Effective shear stiffness (shear analogy simplified for 1 m strip)
    ga_eff = values["g90Mpa"] * 1000.0 * h * 0.25 / 1000.0  # kN/m
    ei_knm2 = ei_eff / 1e9
    return result(
        summary={
            "plyCount": len(plies),
            "totalThicknessMm": h,
            "eiEffMajorKnM2PerM": ei_knm2,
            "gaEffKnPerM": ga_eff,
            "spanToDepthRatio": values["spanM"] * 1000.0 / h,
        },
        tables=[
            table(
                "CLT lay-up stiffness per metre width",
                [
                    ("ply", "Ply #"),
                    ("orientation", "Orientation"),
                    ("thicknessMm", "Thickness", "mm"),
                    ("eiShareKnM2", "EI contribution", "kN-m2/m"),
                ],
                rows,
            )
        ],
        notes=["Composite bending stiffness by parallel-axis theorem assuming E90 = E0/30."],
    )


@feature(
    "libraryMasonry.glassAluminium",
    "Glass & Aluminium",
    part="materials",
    fields=[
        text("alloy", "Aluminium alloy & temper", "EN AW-6082 T6"),
        checkbox("welded", "Welded aluminium HAZ reduction", False),
        select(
            "glassKind",
            "Structural glass type",
            [
                ("annealed", "Annealed float"),
                ("heatStrengthened", "Heat-strengthened"),
                ("toughened", "Thermally toughened"),
                ("chemicallyToughened", "Chemically toughened"),
            ],
            "toughened",
        ),
    ],
    requires_project=False,
)
def glass_aluminium(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate structural glass and aluminium material models for facade design."""
    alu = Material(
        id="ALU-1",
        name=f"Aluminium {values['alloy']}",
        category=Category.ALUMINIUM,
        mechanical=Mechanical(E=70000.0, nu=0.3, density=2700.0, alpha=2.3e-5),
        aluminium=AluminiumProperties(alloy=values["alloy"], welded=values["welded"]),
    )
    gls = Material(
        id="GLS-1",
        name=f"Glass ({values['glassKind']})",
        category=Category.GLASS,
        mechanical=Mechanical(E=70000.0, nu=0.22, density=2500.0, alpha=9.0e-6),
        glass=GlassProperties(kind=values["glassKind"], surface="float"),
    )
    glass_char = {
        "annealed": 45.0,
        "heatStrengthened": 70.0,
        "toughened": 120.0,
        "chemicallyToughened": 150.0,
    }[values["glassKind"]]
    rows = [
        {
            "material": alu.name,
            "E_Mpa": alu.mechanical.E,
            "densityKgPerM3": alu.mechanical.density,
            "note": "HAZ applies" if values["welded"] else "Unwelded",
        },
        {
            "material": gls.name,
            "E_Mpa": gls.mechanical.E,
            "densityKgPerM3": gls.mechanical.density,
            "note": f"Characteristic bending ~{glass_char:.0f} MPa",
        },
    ]
    return result(
        summary={
            "aluminiumModulusMpa": 70000.0,
            "glassModulusMpa": 70000.0,
            "glassCharacteristicBendingMpa": glass_char,
        },
        tables=[
            table(
                "Facade glass & aluminium properties",
                [
                    ("material", "Material"),
                    ("E_Mpa", "E", "MPa"),
                    ("densityKgPerM3", "Density", "kg/m3"),
                    ("note", "Notes"),
                ],
                rows,
            )
        ],
        notes=["Validated with SAEngine AluminiumProperties and GlassProperties schemas."],
    )


@feature(
    "libraryMasonry.composites",
    "Composites",
    part="materials",
    fields=[
        number("fiberModulusMpa", "Fiber modulus Ef", 230000.0, unit="MPa", min=10000.0),
        number("fiberStrengthMpa", "Fiber tensile strength ff", 3800.0, unit="MPa", min=100.0),
        number("matrixModulusMpa", "Matrix resin modulus Em", 3200.0, unit="MPa", min=500.0),
        number("fiberVolumeFraction", "Fiber volume fraction Vf", 0.55, min=0.1, max=0.8),
        number("plyThicknessMm", "Ply thickness", 0.35, unit="mm", min=0.05),
    ],
    requires_project=False,
)
def composites(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute unidirectional FRP lamina properties via micromechanics rule of mixtures."""
    vf = values["fiberVolumeFraction"]
    vm = 1.0 - vf
    ef = values["fiberModulusMpa"]
    em = values["matrixModulusMpa"]
    e1 = ef * vf + em * vm
    e2 = (ef * em) / (vf * em + vm * ef)
    g12 = (0.4 * ef * 0.37 * em) / (vf * 0.37 * em + vm * 0.4 * ef)
    f_ult = values["fiberStrengthMpa"] * vf
    return result(
        summary={
            "longitudinalModulusE1Mpa": e1,
            "transverseModulusE2Mpa": e2,
            "inPlaneShearG12Mpa": g12,
            "tensileStrengthMpa": f_ult,
            "axialStiffnessKnPerMmWidth": e1 * values["plyThicknessMm"] / 1000.0,
        },
        tables=[
            table(
                "FRP lamina micromechanics",
                [("property", "Property"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"property": "Longitudinal modulus E1", "value": e1, "unit": "MPa"},
                    {"property": "Transverse modulus E2 (Reuss)", "value": e2, "unit": "MPa"},
                    {"property": "In-plane shear G12", "value": g12, "unit": "MPa"},
                    {"property": "Longitudinal tensile strength", "value": f_ult, "unit": "MPa"},
                ],
            )
        ],
        notes=["Voigt-Reuss micromechanics rule of mixtures for unidirectional FRP ply."],
    )


@feature(
    "libraryMasonry.groutMix",
    "Grout Mix",
    part="materials",
    fields=[
        select(
            "groutType",
            "Grout aggregate type",
            [("fine", "Fine grout"), ("coarse", "Coarse grout")],
            "coarse",
        ),
        number("cementParts", "Cement parts (vol)", 1.0, min=1.0, max=2.0),
        number("sandParts", "Damp sand parts (vol)", 2.5, min=1.5, max=4.0),
        number("peaGravelParts", "Pea gravel parts (vol, coarse only)", 1.5, min=0.0, max=3.0),
        number("slumpMm", "Target slump flow", 230.0, unit="mm", min=180.0, max=280.0),
    ],
    requires_project=False,
)
def grout_mix(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Proportion fine or coarse masonry grout and check flowable slump requirements."""
    coarse_parts = values["peaGravelParts"] if values["groutType"] == "coarse" else 0.0
    total_parts = values["cementParts"] + values["sandParts"] + coarse_parts
    cem_kg = 1.4 * values["cementParts"] / total_parts * 1440.0
    slump_ok = 200.0 <= values["slumpMm"] <= 280.0
    return result(
        summary={
            "groutType": values["groutType"],
            "estimatedCementKgPerM3": cem_kg,
            "slumpMm": values["slumpMm"],
            "flowCompliant": slump_ok,
        },
        tables=[
            table(
                "Masonry grout proportions",
                [
                    ("constituent", "Constituent"),
                    ("parts", "Volumetric parts"),
                    ("sharePct", "Share", "%"),
                ],
                [
                    {
                        "constituent": "Cement",
                        "parts": values["cementParts"],
                        "sharePct": values["cementParts"] / total_parts * 100.0,
                    },
                    {
                        "constituent": "Sand",
                        "parts": values["sandParts"],
                        "sharePct": values["sandParts"] / total_parts * 100.0,
                    },
                    {
                        "constituent": "Pea gravel",
                        "parts": coarse_parts,
                        "sharePct": coarse_parts / total_parts * 100.0,
                    },
                ],
            )
        ],
        notes=[
            "Flowable masonry grout typically requires 200-280 mm slump to fill reinforced cells without voids."
        ],
    )


@feature(
    "libraryMasonry.mortarCubeTest",
    "Mortar Cube Test",
    part="materials",
    fields=[
        text("cubeMpa", "Mortar cube strengths [MPa]", "8.2, 7.9, 8.5"),
        select(
            "mortarGrade",
            "Specified mortar grade",
            [("M1", "M1"), ("M2", "M2"), ("M3", "M3"), ("M4", "M4"), ("M5", "M5"), ("M6", "M6")],
            "M2",
        ),
    ],
    requires_project=False,
)
def mortar_cube_test(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare mortar cube test strengths against the code pack's mortar class requirement."""
    vals = parse_numbers(values["cubeMpa"], "Mortar cube strengths")
    with in_force(ctx.root):
        mortars = M.table().mortars
        req = float(mortars[values["mortarGrade"]].strength)
    mean = sum(vals) / len(vals)
    return result(
        summary={
            "sampleCount": len(vals),
            "meanStrengthMpa": mean,
            "requiredStrengthMpa": req,
            "compliant": mean >= req and min(vals) >= 0.85 * req,
        },
        tables=[
            table(
                "Mortar cube test results",
                [
                    ("cube", "Cube #"),
                    ("strengthMpa", "Strength", "MPa"),
                    ("ratioToSpec", "Ratio to spec"),
                ],
                [
                    {"cube": i + 1, "strengthMpa": v, "ratioToSpec": v / req}
                    for i, v in enumerate(vals)
                ],
            )
        ],
        notes=[f"Code pack specified strength for {values['mortarGrade']} is {req:g} MPa."],
    )


@feature(
    "libraryMasonry.beddingMortar",
    "Bedding Mortar",
    part="materials",
    fields=[
        number("unitLengthMm", "Unit length", 240.0, unit="mm", min=50.0),
        number("unitWidthMm", "Wall thickness / unit width", 115.0, unit="mm", min=50.0),
        number("unitHeightMm", "Unit height", 70.0, unit="mm", min=30.0),
        number(
            "jointThicknessMm", "Bed & head joint thickness", 10.0, unit="mm", min=3.0, max=25.0
        ),
        number("wastagePct", "Site mortar wastage", 10.0, unit="%", min=0.0, max=40.0),
    ],
    requires_project=False,
)
def bedding_mortar(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute mortar volume share per m3 of masonry and check joint thickness bounds."""
    l_u, w_u, h_u, t = (
        values["unitLengthMm"],
        values["unitWidthMm"],
        values["unitHeightMm"],
        values["jointThicknessMm"],
    )
    mod_vol = (l_u + t) * w_u * (h_u + t)
    unit_vol = l_u * w_u * h_u
    mortar_frac = (mod_vol - unit_vol) / mod_vol
    mortar_m3_per_m3 = mortar_frac * (1.0 + values["wastagePct"] / 100.0)
    joint_ok = 6.0 <= t <= 15.0
    return result(
        summary={
            "mortarVolumeFraction": mortar_frac,
            "mortarM3PerM3Masonry": mortar_m3_per_m3,
            "unitsPerM3": 1e9 / mod_vol,
            "jointThicknessOk": joint_ok,
        },
        tables=[
            table(
                "Masonry bedding mortar quantities",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Joint thickness", "value": t, "unit": "mm"},
                    {
                        "parameter": "Net mortar per m3 masonry",
                        "value": mortar_frac,
                        "unit": "m3/m3",
                    },
                    {
                        "parameter": "Gross mortar with wastage",
                        "value": mortar_m3_per_m3,
                        "unit": "m3/m3",
                    },
                    {"parameter": "Units per m3 masonry", "value": 1e9 / mod_vol, "unit": "nr/m3"},
                ],
            )
        ],
        notes=["Standard solid masonry bed/head joints are 8-12 mm (acceptable band 6-15 mm)."],
    )


@feature(
    "libraryMasonry.reinforcementGrout",
    "Reinforcement Grout",
    part="materials",
    fields=[
        number("cellWidthMm", "Minimum grout cell dimension", 75.0, unit="mm", min=25.0),
        number("barDiaMm", "Vertical bar diameter", 16.0, unit="mm", min=6.0),
        number("groutStrengthMpa", "Grout 28-day compressive strength", 18.0, unit="MPa", min=5.0),
        number("fmMpa", "Masonry prism strength f'm", 12.0, unit="MPa", min=2.0),
    ],
    requires_project=False,
)
def reinforcement_grout(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check grout strength, cell clearance, and cover for reinforced masonry cells."""
    clearance = (values["cellWidthMm"] - values["barDiaMm"]) / 2.0
    min_req_strength = max(14.0, values["fmMpa"])
    strength_ok = values["groutStrengthMpa"] >= min_req_strength
    clear_ok = clearance >= max(12.0, values["barDiaMm"])
    return result(
        summary={
            "sideClearanceMm": clearance,
            "requiredGroutMpa": min_req_strength,
            "strengthOk": strength_ok,
            "clearanceOk": clear_ok,
        },
        tables=[
            table(
                "Reinforced masonry grout checks",
                [("check", "Check"), ("actual", "Actual"), ("required", "Minimum"), ("ok", "Pass")],
                [
                    {
                        "check": "Grout strength [MPa]",
                        "actual": values["groutStrengthMpa"],
                        "required": min_req_strength,
                        "ok": strength_ok,
                    },
                    {
                        "check": "Grout clearance around bar [mm]",
                        "actual": clearance,
                        "required": max(12.0, values["barDiaMm"]),
                        "ok": clear_ok,
                    },
                ],
            )
        ],
        notes=[
            "Grout strength should be at least f'm (minimum 14 MPa) with bar clearance >= max(12 mm, db)."
        ],
    )


@feature(
    "libraryMasonry.limeMortar",
    "Lime Mortar",
    part="materials",
    fields=[
        select(
            "nhlClass",
            "Natural hydraulic lime class",
            [
                ("NHL2", "NHL 2 (soft/heritage)"),
                ("NHL3.5", "NHL 3.5 (moderate)"),
                ("NHL5", "NHL 5 (severe/heavy)"),
            ],
            "NHL3.5",
        ),
        number("limeParts", "Lime binder parts", 1.0, min=1.0, max=2.0),
        number("sandParts", "Well-graded sand parts", 2.5, min=1.5, max=4.0),
        number("unitStrengthMpa", "Host brick/stone strength", 8.0, unit="MPa", min=1.0),
    ],
    requires_project=False,
)
def lime_mortar(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure hydraulic lime mortar and check compatibility with soft heritage masonry units."""
    nhl_fc = {"NHL2": 2.0, "NHL3.5": 3.5, "NHL5": 5.0}[values["nhlClass"]]
    ratio_factor = 2.5 / values["sandParts"] * values["limeParts"]
    mortar_fc = nhl_fc * ratio_factor
    compatible = mortar_fc < 0.75 * values["unitStrengthMpa"]
    return result(
        summary={
            "nhlClass": values["nhlClass"],
            "estimatedMortarStrengthMpa": mortar_fc,
            "unitCompatible": compatible,
        },
        tables=[
            table(
                "Lime mortar specification",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "parameter": "Nominal ratio (lime : sand)",
                        "value": f"{values['limeParts']:g} : {values['sandParts']:g}",
                        "unit": "-",
                    },
                    {"parameter": "Estimated 28-day strength", "value": mortar_fc, "unit": "MPa"},
                    {
                        "parameter": "Host unit strength",
                        "value": values["unitStrengthMpa"],
                        "unit": "MPa",
                    },
                ],
            )
        ],
        notes=[
            "Mortar strength should stay below ~0.75x unit strength so movement occurs along joints rather than spalling units."
        ],
    )


@feature(
    "libraryMasonry.compressiveStrength",
    "Compressive Strength",
    part="materials",
    fields=[
        number("unitStrengthMpa", "Masonry unit strength fb", 15.0, unit="MPa", min=1.0),
        select(
            "unitKind",
            "Unit kind",
            [("clay", "Clay brick"), ("concrete", "Concrete block")],
            "clay",
        ),
        text("mortarGrade", "Mortar grade", "M2"),
        number("gammaM", "Partial factor (if limit-state)", 2.2, min=1.0, max=4.0),
    ],
    requires_project=False,
)
def compressive_strength(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Derive masonry compressive strength f'm from unit and mortar using code pack tables."""
    with in_force(ctx.root):
        grade = values["mortarGrade"].strip() or None
        fm = M.prism_estimate(values["unitStrengthMpa"], values["unitKind"], grade)
        if fm is None:
            fm = 0.45 * (values["unitStrengthMpa"] ** 0.7) * (5.0**0.3)
        fd = fm / values["gammaM"]
    return result(
        summary={
            "masonryStrengthFmMpa": fm,
            "designCompressiveMpa": fd,
            "unitStrengthMpa": values["unitStrengthMpa"],
        },
        tables=[
            table(
                "Masonry compressive strength",
                [("item", "Strength"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Unit strength", "value": values["unitStrengthMpa"], "unit": "MPa"},
                    {"item": "Estimated masonry f'm", "value": fm, "unit": "MPa"},
                    {"item": "Factored design strength fd", "value": fd, "unit": "MPa"},
                ],
            )
        ],
        notes=[
            "Uses code pack prismEstimate lookup when mortar grade & unit strength fall within pack range."
        ],
    )


@feature(
    "libraryMasonry.flexuralBond",
    "Flexural Bond",
    part="materials",
    fields=[
        select(
            "direction",
            "Bending plane",
            [("normal", "Normal to bed joints"), ("parallel", "Parallel to bed joints")],
            "normal",
        ),
        select(
            "grouting",
            "Grouting",
            [("none", "Ungrouted"), ("partial", "Partially grouted"), ("full", "Fully grouted")],
            "none",
        ),
        number("mortarStrengthMpa", "Mortar compressive strength", 7.5, unit="MPa", min=1.0),
    ],
    requires_project=False,
)
def flexural_bond(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assess out-of-plane flexural bond strength for masonry walls."""
    base = (
        0.15
        if values["mortarStrengthMpa"] >= 7.5
        else (0.10 if values["mortarStrengthMpa"] >= 3.0 else 0.07)
    )
    if values["grouting"] == "full":
        base *= 1.6
    elif values["grouting"] == "partial":
        base *= 1.25
    ft = base * (2.0 if values["direction"] == "parallel" else 1.0)
    return result(
        summary={
            "flexuralBondMpa": ft,
            "direction": values["direction"],
            "grouting": values["grouting"],
        },
        tables=[
            table(
                "Out-of-plane flexural tensile capacity",
                [("direction", "Bending direction"), ("bondMpa", "Flexural bond", "MPa")],
                [
                    {"direction": "Normal to bed joints", "bondMpa": base},
                    {"direction": "Parallel to bed joints", "bondMpa": 2.0 * base},
                ],
            )
        ],
        notes=[
            "Indicative unreinforced masonry flexural tension values; confirm with project code pack."
        ],
    )


@feature(
    "libraryMasonry.shearStrength",
    "Shear Strength",
    part="materials",
    fields=[
        number("fvk0Mpa", "Initial bed-joint shear strength fv0", 0.20, unit="MPa", min=0.05),
        number("frictionCoeff", "Bed-joint friction coefficient mu", 0.40, min=0.1, max=0.8),
        number("precompressionMpa", "Normal compressive stress sigma_d", 0.60, unit="MPa", min=0.0),
        number("unitStrengthMpa", "Unit strength cap fb", 15.0, unit="MPa", min=1.0),
    ],
    requires_project=False,
)
def shear_strength(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate Mohr-Coulomb bed-joint sliding shear strength fv = fv0 + mu * sigma_d."""
    fv_raw = values["fvk0Mpa"] + values["frictionCoeff"] * values["precompressionMpa"]
    cap = min(0.065 * values["unitStrengthMpa"], 1.7)
    fv = min(fv_raw, cap)
    return result(
        summary={
            "shearStrengthMpa": fv,
            "uncappedShearMpa": fv_raw,
            "shearCapMpa": cap,
        },
        tables=[
            table(
                "Bed-joint shear strength",
                [("term", "Term"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"term": "Cohesion fv0", "value": values["fvk0Mpa"], "unit": "MPa"},
                    {
                        "term": "Frictional component mu*sigma_d",
                        "value": values["frictionCoeff"] * values["precompressionMpa"],
                        "unit": "MPa",
                    },
                    {"term": "Maximum shear cap", "value": cap, "unit": "MPa"},
                    {"term": "Governing shear strength fv", "value": fv, "unit": "MPa"},
                ],
            )
        ],
        notes=["Mohr-Coulomb sliding shear capped at min(0.065 fb, 1.7 MPa)."],
    )


@feature(
    "libraryMasonry.modulusOfMasonry",
    "Modulus Of Masonry",
    part="materials",
    fields=[
        number("fmMpa", "Masonry compressive strength f'm", 10.0, unit="MPa", min=1.0),
        select(
            "unitKind",
            "Unit kind",
            [("clay", "Clay brick"), ("concrete", "Concrete block")],
            "clay",
        ),
    ],
    requires_project=False,
)
def modulus_of_masonry(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute masonry elastic modulus Em and shear modulus Gm from the code pack."""
    with in_force(ctx.root):
        m_obj = M.Masonry(fm=values["fmMpa"], kind=values["unitKind"])
        em = m_obj.em
        gm = m_obj.g
    return result(
        summary={"fmMpa": values["fmMpa"], "elasticModulusMpa": em, "shearModulusMpa": gm},
        tables=[
            table(
                "Masonry stiffness moduli",
                [("modulus", "Modulus"), ("valueMpa", "Value", "MPa")],
                [
                    {"modulus": "Elastic modulus Em", "valueMpa": em},
                    {"modulus": "Shear modulus Gm", "valueMpa": gm},
                ],
            )
        ],
        notes=[
            "Computed by saengine.design.masonry.Masonry using the active code pack ratios and cap."
        ],
    )


@feature(
    "libraryMasonry.anchorageCapacity",
    "Anchorage Capacity",
    part="materials",
    fields=[
        number("boltDiaMm", "Anchor bolt diameter", 16.0, unit="mm", min=6.0, max=36.0),
        number("embedmentMm", "Effective embedment lb", 150.0, unit="mm", min=50.0),
        number("edgeDistanceMm", "Edge distance", 150.0, unit="mm", min=25.0),
        number("fmMpa", "Masonry compressive strength f'm", 10.0, unit="MPa", min=2.0),
        number("fyMpa", "Anchor steel yield fy", 250.0, unit="MPa", min=150.0),
    ],
    requires_project=False,
)
def anchorage_capacity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate anchor bolt allowable shear and tension in grouted masonry."""
    dia = values["boltDiaMm"]
    bolt = MA.AnchorBolt(
        dia=dia,
        embedment=values["embedmentMm"],
        edge=values["edgeDistanceMm"],
        spacing=None,
        fy=values["fyMpa"],
    )
    ab = bolt.area
    with in_force(ctx.root):
        v_n, v_note = MA.allowable_shear(bolt, values["fmMpa"])
        t_n, t_note = MA.allowable_tension(bolt, values["fmMpa"])
    return result(
        summary={
            "allowableShearKn": v_n / 1000.0,
            "allowableTensionKn": t_n / 1000.0,
            "boltAreaMm2": ab,
        },
        tables=[
            table(
                "Masonry anchor bolt capacities",
                [
                    ("mode", "Limit mode"),
                    ("capacityKn", "Capacity", "kN"),
                    ("basis", "Governing basis"),
                ],
                [
                    {"mode": "Shear", "capacityKn": v_n / 1000.0, "basis": v_note},
                    {"mode": "Tension", "capacityKn": t_n / 1000.0, "basis": t_note},
                ],
            )
        ],
        notes=["Uses saengine.design.masonry_anchors under the code pack in force."],
    )


@feature(
    "libraryMasonry.nailCapacity",
    "Nail Capacity",
    part="materials",
    fields=[
        number("nailDiaMm", "Nail shank diameter", 4.0, unit="mm", min=2.0, max=8.0),
        number("memberThicknessMm", "Side member thickness", 35.0, unit="mm", min=15.0),
        number("timberDensityKgPerM3", "Timber density", 550.0, unit="kg/m3", min=300.0),
        number("nailCount", "Number of nails", 6.0, min=1.0),
        checkbox("doubleShear", "Double shear connection", True),
    ],
    requires_project=False,
)
def nail_capacity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute nailed timber connection lateral capacity per fastener and group."""
    d = values["nailDiaMm"]
    rho = values["timberDensityKgPerM3"]
    # Johansen / embedment estimate: fh ≈ 0.082 * rho * d^-0.3, My ≈ 0.3 * 600 * d^2.6
    fh = 0.082 * rho * (d**-0.3)
    my = 0.3 * 600.0 * (d**2.6)
    f_single = min(
        fh * values["memberThicknessMm"] * d,
        math.sqrt(2.0 * my * fh * d) + fh * values["memberThicknessMm"] * d * 0.2,
    )
    f_per_nail = f_single * (2.0 if values["doubleShear"] else 1.0)
    n = round(values["nailCount"])
    n_eff = n**0.85 if n > 1 else 1.0
    total_kn = n_eff * f_per_nail / 1000.0
    return result(
        summary={
            "perNailKn": f_per_nail / 1000.0,
            "effectiveFasteners": n_eff,
            "groupCapacityKn": total_kn,
        },
        tables=[
            table(
                "Timber nailed joint capacity",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Embedment strength fh", "value": fh, "unit": "MPa"},
                    {"parameter": "Yield moment My", "value": my / 1000.0, "unit": "N-m"},
                    {"parameter": "Per-nail capacity", "value": f_per_nail / 1000.0, "unit": "kN"},
                    {"parameter": "Group capacity (n_eff)", "value": total_kn, "unit": "kN"},
                ],
            )
        ],
        notes=["Johansen yield theory estimate with effective nail count n_eff = n^0.85."],
    )


@feature(
    "libraryMasonry.boltCapacity",
    "Bolt Capacity",
    part="materials",
    fields=[
        number("boltDiaMm", "Bolt diameter d", 16.0, unit="mm", min=8.0, max=36.0),
        number("mainThicknessMm", "Main member thickness t", 100.0, unit="mm", min=25.0),
        number("angleDeg", "Load angle to grain theta", 0.0, unit="deg", min=0.0, max=90.0),
        select(
            "group",
            "Timber strength group",
            [("A", "Group A"), ("B", "Group B"), ("C", "Group C")],
            "B",
        ),
        checkbox("singleShear", "Single shear (unchecked = double shear)", False),
    ],
    requires_project=False,
)
def bolt_capacity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute bolted timber joint permissible capacity at angle theta to grain via code pack."""
    with in_force(ctx.root):
        tbl = code_context.table("timber")
        grp = tbl.groups[values["group"]]
        fc = float(grp.compressionParallel["inside"])
        fcn = float(grp.compressionPerpendicular["inside"])
        try:
            cap_n = TC.bolt_capacity(
                fc,
                fcn,
                values["mainThicknessMm"],
                values["boltDiaMm"],
                math.radians(values["angleDeg"]),
                single=values["singleShear"],
            )
        except TM.TimberDesignError as exc:
            raise FeatureInputError(str(exc)) from exc
    return result(
        summary={
            "perBoltKn": cap_n / 1000.0,
            "slendernessRatio": values["mainThicknessMm"] / values["boltDiaMm"],
            "angleDeg": values["angleDeg"],
        },
        tables=[
            table(
                "Timber bolt Hankinson capacity",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Parallel bearing fc", "value": fc, "unit": "MPa"},
                    {"parameter": "Perpendicular bearing fcn", "value": fcn, "unit": "MPa"},
                    {"parameter": "Per-bolt capacity", "value": cap_n / 1000.0, "unit": "kN"},
                ],
            )
        ],
        notes=[
            "Uses saengine.design.timber.connections.bolt_capacity with code pack diameter and t/d factors."
        ],
    )


@feature(
    "libraryMasonry.glulamDesign",
    "Glulam Design",
    part="materials",
    fields=[
        number("widthMm", "Width b", 140.0, unit="mm", min=50.0),
        number("depthMm", "Depth h", 400.0, unit="mm", min=100.0),
        number("spanM", "Simply supported span L", 8.0, unit="m", min=1.0),
        number("udlKnPerM", "Design UDL w", 12.0, unit="kN/m", min=0.1),
        number("fmdMpa", "Design bending strength fm,d", 18.0, unit="MPa", min=5.0),
        number("e0MeanMpa", "Mean modulus E0", 12600.0, unit="MPa", min=5000.0),
    ],
    requires_project=False,
)
def glulam_design(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check glulam member bending, shear, and midspan deflection for long-span design."""
    b, h = values["widthMm"], values["depthMm"]
    l_mm = values["spanM"] * 1000.0
    w = values["udlKnPerM"]  # N/mm == kN/m
    m_ed = w * values["spanM"] ** 2 / 8.0  # kN-m
    v_ed = w * values["spanM"] / 2.0  # kN
    wy = b * h**2 / 6.0
    m_rd = values["fmdMpa"] * wy / 1e6
    iy = b * h**3 / 12.0
    defl_mm = 5.0 * w * (l_mm**4) / (384.0 * values["e0MeanMpa"] * iy)
    return result(
        summary={
            "momentDemandKnM": m_ed,
            "momentCapacityKnM": m_rd,
            "bendingUtilisation": m_ed / m_rd,
            "midspanDeflectionMm": defl_mm,
            "spanOverDeflection": l_mm / defl_mm if defl_mm > 0 else 9999.0,
        },
        tables=[
            table(
                "Glulam beam design check",
                [
                    ("check", "Check"),
                    ("demand", "Demand"),
                    ("capacity", "Capacity"),
                    ("unit", "Unit"),
                    ("util", "Util"),
                ],
                [
                    {
                        "check": "Bending moment",
                        "demand": m_ed,
                        "capacity": m_rd,
                        "unit": "kN-m",
                        "util": m_ed / m_rd,
                    },
                    {
                        "check": "End shear",
                        "demand": v_ed,
                        "capacity": 1.8 * 2.0 / 3.0 * b * h / 1000.0,
                        "unit": "kN",
                        "util": v_ed / (1.2 * b * h / 1000.0),
                    },
                    {
                        "check": "Deflection (L/300)",
                        "demand": defl_mm,
                        "capacity": l_mm / 300.0,
                        "unit": "mm",
                        "util": defl_mm / (l_mm / 300.0),
                    },
                ],
            )
        ],
        notes=["Simply supported uniformly loaded beam check."],
    )


@feature(
    "libraryMasonry.fireCharRate",
    "Fire Char Rate",
    part="materials",
    fields=[
        number("widthMm", "Original width b", 140.0, unit="mm", min=40.0),
        number("depthMm", "Original depth h", 360.0, unit="mm", min=60.0),
        number("fireMinutes", "Fire exposure duration t", 60.0, unit="min", min=15.0, max=180.0),
        number(
            "charRateMmPerMin",
            "Notional charring rate beta_n",
            0.70,
            unit="mm/min",
            min=0.4,
            max=1.2,
        ),
        number("zeroStrengthMm", "Zero-strength layer d0", 7.0, unit="mm", min=0.0, max=15.0),
        select(
            "sidesExposed",
            "Exposed sides",
            [("3", "Three sides (beam)"), ("4", "Four sides (column)")],
            "3",
        ),
    ],
    requires_project=False,
)
def fire_char_rate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply timber charring rates and zero-strength layer to compute residual section properties."""
    b, h = values["widthMm"], values["depthMm"]
    d_char = values["charRateMmPerMin"] * values["fireMinutes"]
    d_ef = d_char + values["zeroStrengthMm"]
    sides = int(values["sidesExposed"])
    b_res = max(0.0, b - 2.0 * d_ef)
    h_res = max(0.0, h - (2.0 if sides == 4 else 1.0) * d_ef)
    a0 = b * h
    a_res = b_res * h_res
    w0 = b * h**2 / 6.0
    w_res = b_res * h_res**2 / 6.0
    return result(
        summary={
            "charDepthMm": d_char,
            "effectiveLossMm": d_ef,
            "residualWidthMm": b_res,
            "residualDepthMm": h_res,
            "residualAreaRatio": a_res / a0 if a0 > 0 else 0.0,
            "residualModulusRatio": w_res / w0 if w0 > 0 else 0.0,
        },
        tables=[
            table(
                "Residual timber section after fire exposure",
                [
                    ("property", "Property"),
                    ("initial", "Initial"),
                    ("residual", "Residual"),
                    ("unit", "Unit"),
                ],
                [
                    {"property": "Width", "initial": b, "residual": b_res, "unit": "mm"},
                    {"property": "Depth", "initial": h, "residual": h_res, "unit": "mm"},
                    {"property": "Area", "initial": a0, "residual": a_res, "unit": "mm2"},
                    {
                        "property": "Section modulus Wy",
                        "initial": w0 / 1e3,
                        "residual": w_res / 1e3,
                        "unit": "cm3",
                    },
                ],
            )
        ],
        notes=["Reduced cross-section method: d_ef = beta_n * t + d0."],
    )

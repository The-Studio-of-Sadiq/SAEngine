"""Materials Library tab: material creation, mix design, properties, constitutive curves and validation."""

from __future__ import annotations

import math
from typing import Any

from saengine.boq.quantities import CEMENT_DENSITY, SAND_DENSITY, STONE_DENSITY
from saengine.design.rc_detailing import concrete_modulus as code_concrete_modulus
from saengine.design.rc_detailing import current_aggregate
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
from saengine.features.materials_common import (
    find_material,
    load_materials,
    material_strength_mpa,
    materials_or_default,
    parse_numbers,
    parse_pairs,
    project_material_usage,
    require_materials,
    safe_json,
    save_export,
)
from saengine.library.check import check_library
from saengine.library.materials import (
    Admixture,
    AluminiumProperties,
    Category,
    ConcreteProperties,
    DesignMix,
    GlassProperties,
    MasonryProperties,
    Material,
    Mechanical,
    NominalMix,
    Source,
    SteelProperties,
    TimberProperties,
    concrete_modulus,
    modulus_of_rupture,
    plausibility,
)
from saengine.report.clauses import in_force

_CATEGORY_GROUP = {
    "concrete": "Concrete",
    "rebar": "Reinforcement",
    "steel": "Structural Steel",
    "masonry": "Masonry",
    "mortar": "Masonry & Mortar",
    "timber": "Timber",
    "bamboo": "Timber & Bio-based",
    "ferrocement": "Cementitious",
    "aluminium": "Metals & Facade",
    "glass": "Facade & Glazing",
    "other": "Custom",
}


@feature(
    "library.newMaterial",
    "New Material",
    part="materials",
    fields=[
        text("materialId", "Material ID", "C30"),
        text("name", "Material name", "Concrete f'c 30 MPa"),
        select(
            "category",
            "Category",
            [
                ("concrete", "Concrete"),
                ("rebar", "Reinforcing steel"),
                ("steel", "Structural steel"),
                ("masonry", "Masonry"),
                ("timber", "Timber"),
                ("mortar", "Mortar"),
                ("aluminium", "Aluminium"),
                ("glass", "Glass"),
                ("other", "Custom"),
            ],
            "concrete",
        ),
        number("strengthMpa", "Primary strength (f'c, fy, or f'm)", 30.0, unit="MPa", min=0.5),
        number("ultimateMpa", "Ultimate strength fu (steel)", 450.0, unit="MPa", min=1.0),
        number("elasticModulusMpa", "Elastic modulus E (0 = auto)", 0.0, unit="MPa", min=0.0),
        number("poisson", "Poisson ratio", 0.2, min=0.0, max=0.49),
        number("densityKgPerM3", "Mass density", 2400.0, unit="kg/m3", min=100.0),
        number("alphaPerC", "Thermal expansion coefficient", 1.0e-5, unit="1/C", min=0.0),
        checkbox("exportDraft", "Write draft JSON to exports", False),
    ],
    requires_project=False,
)
def new_material(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build and validate a concrete, steel, timber, masonry, or custom material record."""
    mid = values["materialId"].strip() or "MAT-1"
    name = values["name"].strip() or mid
    cat = Category(values["category"])
    strength = values["strengthMpa"]
    e_val = values["elasticModulusMpa"]
    nu = values["poisson"]
    rho = values["densityKgPerM3"]
    alpha = values["alphaPerC"]

    if e_val <= 0:
        if cat == Category.CONCRETE:
            e_val = concrete_modulus(strength)
        elif cat in (Category.REBAR, Category.STEEL):
            e_val = 200000.0
        elif cat == Category.TIMBER:
            e_val = 11000.0
        elif cat in (Category.ALUMINIUM, Category.GLASS):
            e_val = 70000.0
        elif cat == Category.MASONRY:
            e_val = min(750.0 * strength, 15000.0)
        else:
            e_val = 25000.0

    kwargs: dict[str, Any] = {}
    if cat == Category.CONCRETE:
        kwargs["concrete"] = ConcreteProperties(
            fc=strength, ft=modulus_of_rupture(strength), maxAggregate=20.0
        )
    elif cat in (Category.REBAR, Category.STEEL):
        fu = max(values["ultimateMpa"], strength)
        kwargs["steel"] = SteelProperties(grade=mid, fy=strength, fu=fu)
    elif cat == Category.MASONRY:
        kwargs["masonry"] = MasonryProperties(unit="masonry unit", fm=strength)
    elif cat == Category.TIMBER:
        kwargs["timber"] = TimberProperties(group="B", location="inside")
    elif cat == Category.MORTAR:
        kwargs["composition"] = NominalMix(ratio=[1.0, 4.0], cementType="OPC")
    elif cat == Category.ALUMINIUM:
        kwargs["aluminium"] = AluminiumProperties(alloy="EN AW-6082 T6")
    elif cat == Category.GLASS:
        kwargs["glass"] = GlassProperties(kind="toughened")

    try:
        mat = Material(
            id=mid,
            name=name,
            category=cat,
            mechanical=Mechanical(E=e_val, nu=nu, density=rho, alpha=alpha),
            source=Source(note="Created via Materials New Material calculator."),
            **kwargs,
        )
    except Exception as exc:
        raise FeatureInputError(f"Material definition failed validation: {exc}") from exc

    with in_force(ctx.root):
        warnings = plausibility(mat)

    export_path = ""
    if values["exportDraft"] and ctx.root is not None:
        out = save_export(
            ctx,
            f"material-{mid}.json",
            safe_json(mat.model_dump(mode="json", by_alias=True, exclude_none=True)),
        )
        export_path = str(out)

    rows = [
        {"property": "ID", "value": mat.id, "unit": "-"},
        {"property": "Name", "value": mat.name, "unit": "-"},
        {"property": "Category", "value": mat.category.value, "unit": "-"},
        {"property": "Elastic modulus E", "value": mat.mechanical.E, "unit": "MPa"},
        {"property": "Poisson ratio", "value": mat.mechanical.nu, "unit": "-"},
        {"property": "Density", "value": mat.mechanical.density, "unit": "kg/m3"},
        {"property": "Primary strength", "value": strength, "unit": "MPa"},
    ]
    notes = [
        "Validated against the SAEngine material schema and plausibility guardrails.",
        *(f"Warning ({path}): {msg}" for path, msg in warnings),
    ]
    if export_path:
        notes.append(f"Draft written to {export_path}.")
    return result(
        summary={
            "materialId": mat.id,
            "category": mat.category.value,
            "modulusMpa": float(mat.mechanical.E or 0.0),
            "densityKgPerM3": float(mat.mechanical.density or 0.0),
            "warningCount": len(warnings),
        },
        tables=[
            table(
                "Validated material definition",
                [("property", "Property"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=notes,
    )


@feature(
    "library.materialGroups",
    "Material Groups",
    part="materials",
    fields=[
        select(
            "groupBy",
            "Grouping scheme",
            [("practice", "Practice group"), ("category", "Material category")],
            "practice",
        )
    ],
    requires_project=True,
)
def material_groups(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Organise project materials into project and practice groups with usage counts."""
    lib = require_materials(ctx)
    usage = project_material_usage(ctx)
    grouped: dict[str, list[Material]] = {}
    for mat in lib.materials:
        key = (
            _CATEGORY_GROUP.get(mat.category.value, "Custom")
            if values["groupBy"] == "practice"
            else mat.category.value
        )
        grouped.setdefault(key, []).append(mat)

    rows = []
    for grp, mats in sorted(grouped.items()):
        rows.append(
            {
                "group": grp,
                "count": len(mats),
                "ids": ", ".join(m.id for m in mats),
                "inUseCount": sum(1 for m in mats if usage.get(m.id, 0) > 0),
            }
        )
    return result(
        summary={
            "groupCount": len(grouped),
            "materialCount": len(lib.materials),
            "defaultConcrete": lib.default_concrete() or "none",
            "defaultRebar": lib.default_rebar() or "none",
        },
        tables=[
            table(
                "Material groups",
                [
                    ("group", "Group"),
                    ("count", "Materials"),
                    ("inUseCount", "Used in model"),
                    ("ids", "Material IDs"),
                ],
                rows,
            )
        ],
        notes=["Counts model usage from 04 Objects and 10 BOQ when present."],
    )


@feature(
    "library.findMaterial",
    "Find Material",
    part="materials",
    fields=[
        text("query", "Search query (name, ID, grade, or standard)", ""),
        select(
            "category",
            "Filter category",
            [
                ("all", "All categories"),
                ("concrete", "Concrete"),
                ("rebar", "Rebar"),
                ("steel", "Structural steel"),
                ("masonry", "Masonry"),
                ("mortar", "Mortar"),
                ("timber", "Timber"),
            ],
            "all",
        ),
    ],
    requires_project=False,
)
def find_material_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Search the project (or default) library by name, ID, grade, or standard."""
    lib, is_project = materials_or_default(ctx)
    query = values["query"].strip().lower()
    cat_filter = values["category"]
    rows = []
    for mat in lib.materials:
        if cat_filter != "all" and mat.category.value != cat_filter:
            continue
        haystack = " ".join(
            filter(
                None,
                [
                    mat.id,
                    mat.name,
                    mat.category.value,
                    mat.steel.grade if mat.steel else None,
                    mat.source.standard if mat.source else None,
                ],
            )
        ).lower()
        if query and query not in haystack:
            continue
        rows.append(
            {
                "id": mat.id,
                "name": mat.name,
                "category": mat.category.value,
                "strengthMpa": material_strength_mpa(mat),
                "modulusMpa": mat.mechanical.E,
                "densityKgPerM3": mat.mechanical.density,
                "standard": (mat.source.standard if mat.source else "") or "-",
            }
        )
    if not rows:
        raise FeatureInputError(f"No materials matched query {values['query']!r}.")
    return result(
        summary={
            "matchCount": len(rows),
            "source": "project" if is_project else "built-in default",
        },
        tables=[
            table(
                "Matching materials",
                [
                    ("id", "ID"),
                    ("name", "Name"),
                    ("category", "Category"),
                    ("strengthMpa", "Strength", "MPa"),
                    ("modulusMpa", "E", "MPa"),
                    ("densityKgPerM3", "Density", "kg/m3"),
                    ("standard", "Standard"),
                ],
                rows,
            )
        ],
        notes=["Searches ID, name, category, steel grade, and source standard fields."],
    )


@feature(
    "library.favourites",
    "Favourites",
    part="materials",
    fields=[text("pinnedIds", "Pinned material IDs (comma-separated)", "C24.1, B500DWR, A992")],
    requires_project=False,
)
def favourites(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Rank project default, heavily used, and pinned materials at the top of the library."""
    lib, is_project = materials_or_default(ctx)
    usage = project_material_usage(ctx) if is_project else {}
    pinned = {tok.strip() for tok in values["pinnedIds"].split(",") if tok.strip()}
    defaults = {lib.default_concrete(), lib.default_rebar()}
    rows = []
    for mat in lib.materials:
        is_pin = mat.id in pinned
        is_def = mat.id in defaults
        use_cnt = usage.get(mat.id, 0)
        score = (100 if is_def else 0) + (50 if is_pin else 0) + use_cnt * 10
        rows.append(
            {
                "id": mat.id,
                "name": mat.name,
                "category": mat.category.value,
                "pinned": is_pin,
                "projectDefault": is_def,
                "usageCount": use_cnt,
                "priorityScore": score,
            }
        )
    rows.sort(key=lambda r: (-r["priorityScore"], r["id"]))
    return result(
        summary={
            "pinnedCount": sum(1 for r in rows if r["pinned"]),
            "defaultConcrete": lib.default_concrete() or "none",
            "defaultRebar": lib.default_rebar() or "none",
        },
        tables=[
            table(
                "Prioritised materials",
                [
                    ("id", "ID"),
                    ("name", "Name"),
                    ("category", "Category"),
                    ("pinned", "Pinned"),
                    ("projectDefault", "Default"),
                    ("usageCount", "Model refs"),
                    ("priorityScore", "Priority"),
                ],
                rows,
            )
        ],
        notes=["Priority combines project default status, pinned list, and model reference count."],
    )


@feature(
    "library.mixDesign",
    "Mix Design",
    part="materials",
    fields=[
        number("fcMpa", "Characteristic strength f'c", 30.0, unit="MPa", min=10.0, max=100.0),
        number("stdDevMpa", "Control standard deviation s", 4.0, unit="MPa", min=1.0, max=12.0),
        number("waterKgPerM3", "Free mixing water", 185.0, unit="kg/m3", min=120.0, max=250.0),
        number("maxWc", "Maximum water/cement ratio", 0.5, min=0.25, max=0.75),
        number("coarseFraction", "Coarse share of total aggregate", 0.62, min=0.4, max=0.75),
        number("airPercent", "Entrapped/entrained air", 2.0, unit="%", min=0.5, max=8.0),
    ],
    requires_project=False,
)
def mix_design(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Proportion a concrete mix by target mean strength and absolute volume method."""
    fc = values["fcMpa"]
    fcm = fc + 1.645 * values["stdDevMpa"]
    # Abrams-type strength relation calibrated for ordinary Portland cement (28-day cylinder):
    # fcm ≈ 98 * 0.045^(w/c) -> w/c = ln(fcm/98)/ln(0.045)
    wc_strength = max(0.28, min(0.70, math.log(max(fcm, 10.0) / 98.0) / math.log(0.045)))
    wc = min(wc_strength, values["maxWc"])
    water = values["waterKgPerM3"]
    cement = water / wc

    # Specific gravities: cement 3.15, water 1.00, SSD aggregates 2.65
    v_paste = cement / 3150.0 + water / 1000.0 + values["airPercent"] / 100.0
    v_agg = max(0.1, 1.0 - v_paste)
    mass_agg = v_agg * 2650.0
    coarse = mass_agg * values["coarseFraction"]
    fine = mass_agg - coarse
    mix = DesignMix(
        cement=round(cement, 1),
        water=round(water, 1),
        fineAggregate=round(fine, 1),
        coarseAggregate=round(coarse, 1),
        cementType="OPC",
    )
    wet_density = mix.cement + mix.water + mix.fineAggregate + (mix.coarseAggregate or 0.0)
    rows = [
        {
            "constituent": "Cement",
            "massKgPerM3": mix.cement,
            "volumeLPerM3": mix.cement / 3.15,
            "looseCftPerM3": mix.cement / CEMENT_DENSITY * 35.3147,
        },
        {
            "constituent": "Water",
            "massKgPerM3": mix.water,
            "volumeLPerM3": mix.water,
            "looseCftPerM3": 0.0,
        },
        {
            "constituent": "Fine aggregate",
            "massKgPerM3": mix.fineAggregate,
            "volumeLPerM3": mix.fineAggregate / 2.65,
            "looseCftPerM3": mix.fineAggregate / SAND_DENSITY * 35.3147,
        },
        {
            "constituent": "Coarse aggregate",
            "massKgPerM3": mix.coarseAggregate or 0.0,
            "volumeLPerM3": (mix.coarseAggregate or 0.0) / 2.65,
            "looseCftPerM3": (mix.coarseAggregate or 0.0) / STONE_DENSITY * 35.3147,
        },
    ]
    return result(
        summary={
            "targetMeanStrengthMpa": fcm,
            "waterCementRatio": wc,
            "cementKgPerM3": mix.cement,
            "wetDensityKgPerM3": wet_density,
        },
        tables=[
            table(
                "Concrete mix proportions per m3",
                [
                    ("constituent", "Constituent"),
                    ("massKgPerM3", "Mass", "kg/m3"),
                    ("volumeLPerM3", "Absolute volume", "L/m3"),
                    ("looseCftPerM3", "Loose volume", "cft/m3"),
                ],
                rows,
            )
        ],
        notes=[
            "Target mean fcm = f'c + 1.645 s; w/c governed by min(Abrams strength relation, max w/c).",
            "Absolute volume assumes SG_cement = 3.15 and SSD aggregate SG = 2.65; verify by trial mixes.",
        ],
    )


_CEMENT_CATALOG = {
    "OPC-42.5N": ("Ordinary Portland Cement 42.5N", 1.00, 0.72, 1.08, 320.0, "Normal hydration"),
    "OPC-52.5N": ("Ordinary Portland Cement 52.5N", 1.15, 0.78, 1.06, 370.0, "High early strength"),
    "PCC-FA25": (
        "Portland Pozzolana (25% Fly Ash)",
        0.94,
        0.62,
        1.18,
        250.0,
        "Lower heat, better durability",
    ),
    "PSC-GGBS50": (
        "Portland Slag Cement (50% GGBS)",
        0.92,
        0.56,
        1.22,
        210.0,
        "Low heat, marine/sulfate",
    ),
    "SRPC": ("Sulfate Resisting Portland Cement", 0.98, 0.70, 1.06, 290.0, "Low C3A for sulfates"),
}


@feature(
    "library.cementTypes",
    "Cement Types",
    part="materials",
    fields=[
        select(
            "cementType",
            "Cement class",
            [(k, v[0]) for k, v in _CEMENT_CATALOG.items()],
            "OPC-42.5N",
        ),
        number("refStrengthMpa", "Reference 28-day strength", 30.0, unit="MPa", min=10.0),
        number("binderKgPerM3", "Total binder content", 360.0, unit="kg/m3", min=150.0),
    ],
    requires_project=False,
)
def cement_types(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare cement classes, strength gain rates, and hydration heat."""
    sel = values["cementType"]
    fc28_ref = values["refStrengthMpa"]
    binder = values["binderKgPerM3"]
    rows = []
    chosen = _CEMENT_CATALOG[sel]
    for code, (desc, f28, r7, r90, heat, note) in _CEMENT_CATALOG.items():
        fc28 = fc28_ref * f28
        rows.append(
            {
                "code": code,
                "description": desc,
                "fc7Mpa": fc28 * r7,
                "fc28Mpa": fc28,
                "fc90Mpa": fc28 * r90,
                "heatKjPerM3": heat * binder,
                "profile": note,
            }
        )
    return result(
        summary={
            "selectedCement": sel,
            "strength7DayMpa": fc28_ref * chosen[1] * chosen[2],
            "strength28DayMpa": fc28_ref * chosen[1],
            "hydrationHeatKjPerM3": chosen[4] * binder,
        },
        tables=[
            table(
                "Cement class comparison",
                [
                    ("code", "Class"),
                    ("description", "Description"),
                    ("fc7Mpa", "7-day", "MPa"),
                    ("fc28Mpa", "28-day", "MPa"),
                    ("fc90Mpa", "90-day", "MPa"),
                    ("heatKjPerM3", "Total heat", "kJ/m3"),
                    ("profile", "Characteristics"),
                ],
                rows,
            )
        ],
        notes=["Indicative hydration heat and 7/28/90-day strength ratios for equal w/b ratio."],
    )


@feature(
    "library.admixtures",
    "Admixtures",
    part="materials",
    fields=[
        select(
            "admixtureType",
            "Admixture function",
            [
                ("superplasticizer", "High-range water reducer (superplasticizer)"),
                ("waterReducer", "Normal water reducer"),
                ("airEntrainer", "Air-entraining agent"),
                ("retarder", "Set retarder"),
                ("accelerator", "Set accelerator"),
            ],
            "superplasticizer",
        ),
        number("cementKgPerM3", "Cement content", 360.0, unit="kg/m3", min=100.0),
        number("waterKgPerM3", "Base water content", 195.0, unit="kg/m3", min=100.0),
        number("dosagePercent", "Dosage (% of cement mass)", 1.0, unit="%", min=0.05, max=5.0),
    ],
    requires_project=False,
)
def admixtures(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record admixture dosage and compute adjusted mixing water and w/c ratio."""
    kind = values["admixtureType"]
    cement = values["cementKgPerM3"]
    water = values["waterKgPerM3"]
    dosage = values["dosagePercent"]

    adm = Admixture(name=kind, amount=dosage, unit="% of cement")
    mass_kg = cement * dosage / 100.0
    if kind == "superplasticizer":
        water_red = min(0.28, 0.14 * dosage)
    elif kind == "waterReducer":
        water_red = min(0.12, 0.08 * dosage)
    else:
        water_red = 0.0
    adj_water = water * (1.0 - water_red)
    wc_base = water / cement
    wc_adj = adj_water / cement
    rows = [
        {"parameter": "Admixture", "value": adm.name, "unit": "-"},
        {"parameter": "Dosage", "value": adm.amount, "unit": "% of cement"},
        {"parameter": "Admixture mass", "value": mass_kg, "unit": "kg/m3"},
        {"parameter": "Water reduction", "value": water_red * 100.0, "unit": "%"},
        {"parameter": "Adjusted water", "value": adj_water, "unit": "kg/m3"},
        {"parameter": "Base w/c", "value": wc_base, "unit": "-"},
        {"parameter": "Effective w/c", "value": wc_adj, "unit": "-"},
    ]
    return result(
        summary={
            "admixtureMassKgPerM3": mass_kg,
            "waterReductionPercent": water_red * 100.0,
            "effectiveWaterKgPerM3": adj_water,
            "effectiveWaterCementRatio": wc_adj,
        },
        tables=[
            table(
                "Admixture dosage and mix impact",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Dosage modelled with SAEngine Admixture schema; confirm compatibility by trial mix."
        ],
    )


@feature(
    "library.curingClass",
    "Curing Class",
    part="materials",
    fields=[
        select(
            "exposure",
            "Exposure severity",
            [
                ("mild", "Mild indoor"),
                ("moderate", "Moderate outdoor"),
                ("severe", "Severe / marine"),
            ],
            "moderate",
        ),
        select(
            "strengthGain",
            "Binder strength development rate",
            [
                ("rapid", "Rapid (r >= 0.50)"),
                ("medium", "Medium (0.30 <= r < 0.50)"),
                ("slow", "Slow (r < 0.30)"),
            ],
            "medium",
        ),
        number("ambientTempC", "Mean ambient temperature", 25.0, unit="C", min=2.0, max=45.0),
        number("actualDays", "Planned wet curing duration", 7.0, unit="days", min=1.0, max=28.0),
    ],
    requires_project=False,
)
def curing_class(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign curing duration requirements based on exposure, binder rate, and temperature."""
    base_days = {"mild": 3.0, "moderate": 7.0, "severe": 10.0}[values["exposure"]]
    rate_mult = {"rapid": 0.75, "medium": 1.0, "slow": 1.35}[values["strengthGain"]]
    temp = values["ambientTempC"]
    # Nurse-Saul equivalent age factor relative to 20 C (datum -10 C)
    temp_factor = (20.0 + 10.0) / max(temp + 10.0, 5.0)
    req_days = math.ceil(base_days * rate_mult * temp_factor)
    equiv_20c_days = values["actualDays"] * (temp + 10.0) / 30.0
    surface_factor = min(1.0, 0.55 + 0.45 * (equiv_20c_days / max(req_days, 1.0)))
    return result(
        summary={
            "requiredCuringDays": float(req_days),
            "equivalent20CDays": equiv_20c_days,
            "surfaceStrengthFactor": surface_factor,
            "adequate": values["actualDays"] >= req_days,
        },
        tables=[
            table(
                "Curing assessment",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "parameter": "Required curing duration",
                        "value": float(req_days),
                        "unit": "days",
                    },
                    {
                        "parameter": "Planned curing duration",
                        "value": values["actualDays"],
                        "unit": "days",
                    },
                    {
                        "parameter": "20 C equivalent maturity duration",
                        "value": equiv_20c_days,
                        "unit": "days",
                    },
                    {
                        "parameter": "Estimated cover-zone quality factor",
                        "value": surface_factor,
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=[
            "Required duration scales with exposure severity, binder hydration rate, and Nurse-Saul temperature factor (T0 = -10 C)."
        ],
    )


@feature(
    "library.elasticModulus",
    "Elastic Modulus",
    part="materials",
    fields=[
        number("fcMpa", "Concrete compressive strength f'c", 25.0, unit="MPa", min=5.0, max=120.0),
        number("densityKgPerM3", "Unit mass density", 2400.0, unit="kg/m3", min=1200.0, max=2800.0),
        select(
            "aggregate",
            "Concrete aggregate type",
            [
                ("siliceous", "Siliceous (normal weight)"),
                ("carbonate", "Carbonate (normal weight)"),
                ("brick", "Brick aggregate"),
                ("sandLightweight", "Sand-lightweight"),
                ("lightweight", "All-lightweight"),
            ],
            "siliceous",
        ),
        number("testStressMpa", "Optional chord test stress", 10.0, unit="MPa", min=0.0),
        number("testStrainMicro", "Optional chord test strain", 0.0, unit="microstrain", min=0.0),
    ],
    requires_project=False,
)
def elastic_modulus(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute concrete elastic modulus from the code pack aggregate rule and optional test strain."""
    fc = values["fcMpa"]
    density = values["densityKgPerM3"]
    agg = values["aggregate"]
    with in_force(ctx.root):
        ec_pack, ec_formula = code_concrete_modulus(fc, density, agg)
        proj_agg = current_aggregate()

    ec_test = None
    if values["testStrainMicro"] > 0 and values["testStressMpa"] > 0:
        ec_test = values["testStressMpa"] / (values["testStrainMicro"] * 1e-6)

    rows = [
        {"source": f"Code pack ({agg})", "modulusMpa": ec_pack, "formula": ec_formula},
        {
            "source": "Normal-weight default",
            "modulusMpa": concrete_modulus(fc),
            "formula": "Default pack Ec",
        },
    ]
    if ec_test is not None:
        rows.append(
            {
                "source": "Measured chord test",
                "modulusMpa": ec_test,
                "formula": "delta_sigma / delta_eps",
            }
        )

    return result(
        summary={
            "modulusMpa": ec_pack,
            "measuredModulusMpa": ec_test if ec_test is not None else ec_pack,
            "projectAggregate": proj_agg,
        },
        tables=[
            table(
                "Elastic modulus comparison",
                [("source", "Basis"), ("modulusMpa", "Modulus E", "MPa"), ("formula", "Relation")],
                rows,
            )
        ],
        notes=[f"Code pack modulus for {agg} aggregate: {ec_formula}."],
    )


@feature(
    "library.poissonRatio",
    "Poisson Ratio",
    part="materials",
    fields=[
        text("materialId", "Project material ID (optional)", ""),
        number("elasticModulusMpa", "Elastic modulus E", 25000.0, unit="MPa", min=100.0),
        number("poisson", "Poisson ratio nu", 0.2, min=0.0, max=0.49),
    ],
    requires_project=False,
)
def poisson_ratio(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute shear modulus G, bulk modulus K, and Lame parameter from E and Poisson ratio."""
    e_val = values["elasticModulusMpa"]
    nu = values["poisson"]
    lib = load_materials(ctx)
    chosen_id = values["materialId"].strip()
    if lib is not None and chosen_id:
        mat = find_material(lib, chosen_id)
        if mat is not None:
            e_val = float(mat.mechanical.E or e_val)
            nu = float(mat.mechanical.nu if mat.mechanical.nu is not None else nu)
            chosen_id = mat.id
    g_mod = e_val / (2.0 * (1.0 + nu))
    k_mod = e_val / (3.0 * (1.0 - 2.0 * nu))
    lame = e_val * nu / ((1.0 + nu) * (1.0 - 2.0 * nu))
    rows = [
        {"constant": "Elastic modulus E", "value": e_val, "unit": "MPa"},
        {"constant": "Poisson ratio nu", "value": nu, "unit": "-"},
        {"constant": "Shear modulus G = E / (2(1+nu))", "value": g_mod, "unit": "MPa"},
        {"constant": "Bulk modulus K = E / (3(1-2nu))", "value": k_mod, "unit": "MPa"},
        {"constant": "Lame first parameter lambda", "value": lame, "unit": "MPa"},
    ]
    return result(
        summary={
            "materialId": chosen_id or "custom",
            "poissonRatio": nu,
            "shearModulusMpa": g_mod,
            "bulkModulusMpa": k_mod,
        },
        tables=[
            table(
                "Isotropic elastic constants",
                [("constant", "Constant"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Isotropic linear elasticity relations: G = E/[2(1+nu)] and K = E/[3(1-2nu)]."],
    )


@feature(
    "library.densityTable",
    "Density Table",
    part="materials",
    fields=[
        number("gravityMPerS2", "Gravitational acceleration g", 9.81, unit="m/s2", min=9.7, max=9.9)
    ],
    requires_project=False,
)
def density_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate mass density and self-weight unit weight across the material library."""
    lib, is_project = materials_or_default(ctx)
    g = values["gravityMPerS2"]
    rows = []
    for mat in lib.materials:
        rho = mat.mechanical.density
        gamma = (rho * g / 1000.0) if rho is not None else None
        rows.append(
            {
                "id": mat.id,
                "name": mat.name,
                "category": mat.category.value,
                "densityKgPerM3": rho,
                "unitWeightKnPerM3": gamma,
            }
        )
    densities = [r["densityKgPerM3"] for r in rows if r["densityKgPerM3"] is not None]
    return result(
        summary={
            "materialCount": len(rows),
            "source": "project" if is_project else "built-in default",
            "minDensityKgPerM3": min(densities) if densities else 0.0,
            "maxDensityKgPerM3": max(densities) if densities else 0.0,
        },
        tables=[
            table(
                "Material density and self-weight table",
                [
                    ("id", "ID"),
                    ("name", "Material"),
                    ("category", "Category"),
                    ("densityKgPerM3", "Density", "kg/m3"),
                    ("unitWeightKnPerM3", "Unit weight", "kN/m3"),
                ],
                rows,
            )
        ],
        notes=["Self-weight unit weight computed as gamma = rho * g / 1000."],
    )


@feature(
    "library.thermalExpansion",
    "Thermal Expansion",
    part="materials",
    fields=[
        number("alphaPerC", "Coefficient of thermal expansion alpha", 1.0e-5, unit="1/C", min=1e-7),
        number("deltaTC", "Temperature change delta T", 30.0, unit="C"),
        number("lengthM", "Member length", 10.0, unit="m", min=0.1),
        number("modulusMpa", "Elastic modulus E", 25000.0, unit="MPa", min=100.0),
    ],
    requires_project=False,
)
def thermal_expansion(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute free thermal strain, length change, and fully restrained thermal stress."""
    alpha = values["alphaPerC"]
    dt = values["deltaTC"]
    length_mm = values["lengthM"] * 1000.0
    e_val = values["modulusMpa"]
    strain = alpha * dt
    delta_l_mm = strain * length_mm
    restrained_mpa = -e_val * strain
    rows = [
        {"quantity": "Thermal strain (alpha * dT)", "value": strain * 1e6, "unit": "microstrain"},
        {"quantity": "Unrestrained expansion/contraction", "value": delta_l_mm, "unit": "mm"},
        {"quantity": "Fully restrained axial stress", "value": restrained_mpa, "unit": "MPa"},
    ]
    return result(
        summary={
            "alphaPerC": alpha,
            "thermalStrainMicro": strain * 1e6,
            "freeDisplacementMm": delta_l_mm,
            "restrainedStressMpa": restrained_mpa,
        },
        tables=[
            table(
                "Thermal response",
                [("quantity", "Quantity"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Assumes linear elastic uncracked section and uniform temperature change delta T."],
    )


@feature(
    "library.characteristicStrength",
    "Characteristic Strength",
    part="materials",
    fields=[
        text(
            "samplesMpa",
            "Sample strengths [MPa] (comma/space separated)",
            "28.4, 31.2, 29.8, 33.1, 30.5, 27.9",
        ),
        number("fractileK", "Tolerance factor k (1.645 for large n)", 1.645, min=0.5, max=4.0),
    ],
    requires_project=False,
)
def characteristic_strength(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute sample statistics and 5th-percentile characteristic strength fk = mean - k * s."""
    vals = parse_numbers(values["samplesMpa"], "Sample strengths")
    n = len(vals)
    mean = sum(vals) / n
    std = math.sqrt(sum((x - mean) ** 2 for x in vals) / (n - 1)) if n > 1 else 0.0
    cov = (std / mean * 100.0) if mean > 0 else 0.0
    fk = mean - values["fractileK"] * std
    rows = [
        {"sampleIndex": i + 1, "strengthMpa": v, "deviationMpa": v - mean}
        for i, v in enumerate(vals)
    ]
    return result(
        summary={
            "sampleCount": n,
            "meanStrengthMpa": mean,
            "stdDevMpa": std,
            "covPercent": cov,
            "characteristicStrengthMpa": fk,
        },
        tables=[
            table(
                "Test sample strength deviations",
                [
                    ("sampleIndex", "Sample #"),
                    ("strengthMpa", "Strength", "MPa"),
                    ("deviationMpa", "Deviation from mean", "MPa"),
                ],
                rows,
            )
        ],
        notes=[
            "Normal distribution lower fractile fk = mean - k * s using Bessel-corrected sample std dev."
        ],
    )


@feature(
    "library.designStrengths",
    "Design Strengths",
    part="materials",
    fields=[
        number("characteristicMpa", "Characteristic strength fk", 30.0, unit="MPa", min=0.5),
        number("partialFactorGamma", "Partial material factor gamma_m", 1.5, min=1.0, max=4.0),
        number("sustainedFactor", "Sustained / long-term factor alpha", 0.85, min=0.4, max=1.2),
        number(
            "resistancePhi",
            "Strength reduction factor phi (for comparison)",
            0.65,
            min=0.3,
            max=1.0,
        ),
    ],
    requires_project=False,
)
def design_strengths(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute design strength fd = alpha * fk / gamma_m and factored equivalent phi * fk."""
    fk = values["characteristicMpa"]
    gamma = values["partialFactorGamma"]
    alpha = values["sustainedFactor"]
    phi = values["resistancePhi"]
    fd = alpha * fk / gamma
    phi_fk = phi * fk
    rows = [
        {
            "method": "Partial factor fd = alpha * fk / gamma_m",
            "designMpa": fd,
            "ratioToFk": fd / fk,
        },
        {"method": "Resistance factor phi * fk", "designMpa": phi_fk, "ratioToFk": phi},
    ]
    return result(
        summary={
            "characteristicMpa": fk,
            "designStrengthMpa": fd,
            "phiStrengthMpa": phi_fk,
        },
        tables=[
            table(
                "Design strength conversion",
                [
                    ("method", "Method"),
                    ("designMpa", "Design strength", "MPa"),
                    ("ratioToFk", "Ratio to fk"),
                ],
                rows,
            )
        ],
        notes=[
            "Applies sustained load factor alpha and partial factor gamma_m from user or code pack inputs."
        ],
    )


@feature(
    "library.stressStrainCurve",
    "Stress-Strain Curve",
    part="materials",
    fields=[
        select(
            "modelKind",
            "Material curve model",
            [
                ("concrete", "Concrete (parabolic-rectangular)"),
                ("steel", "Steel (elastic-plastic)"),
            ],
            "concrete",
        ),
        number("strengthMpa", "Peak/yield strength (f'c or fy)", 30.0, unit="MPa", min=1.0),
        number("modulusMpa", "Initial modulus E0", 25740.0, unit="MPa", min=500.0),
        number("ultimateStrain", "Ultimate strain", 0.0035, min=0.001, max=0.2),
    ],
    requires_project=False,
)
def stress_strain_curve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate constitutive uniaxial stress-strain points for nonlinear section analysis."""
    kind = values["modelKind"]
    f0 = values["strengthMpa"]
    e0 = values["modulusMpa"]
    eps_u = values["ultimateStrain"]
    rows = []
    if kind == "concrete":
        eps_c2 = 0.002
        steps = 14
        for i in range(steps + 1):
            eps = eps_u * i / steps
            if eps <= eps_c2:
                sigma = f0 * (1.0 - (1.0 - eps / eps_c2) ** 2)
            else:
                sigma = f0
            rows.append({"strain": round(eps, 6), "stressMpa": sigma})
    else:
        eps_y = f0 / e0
        pts = [0.0, 0.5 * eps_y, eps_y, 2.0 * eps_y, 5.0 * eps_y, eps_u]
        for eps in sorted({p for p in pts if p <= eps_u + 1e-9}):
            sigma = e0 * eps if eps <= eps_y else f0 + 0.01 * e0 * (eps - eps_y)
            rows.append({"strain": round(eps, 6), "stressMpa": sigma})
    return result(
        summary={
            "model": kind,
            "peakStressMpa": max(r["stressMpa"] for r in rows),
            "ultimateStrain": eps_u,
            "pointCount": len(rows),
        },
        tables=[
            table(
                "Uniaxial stress-strain curve",
                [("strain", "Strain", "-"), ("stressMpa", "Stress", "MPa")],
                rows,
            )
        ],
        notes=["Positive compression convention for concrete; elastic-hardening (1%) for steel."],
    )


@feature(
    "library.manderConcrete",
    "Mander Concrete",
    part="materials",
    fields=[
        number("fcMpa", "Unconfined concrete strength f'c", 30.0, unit="MPa", min=10.0, max=100.0),
        number("ecMpa", "Initial tangent modulus Ec (0 = auto)", 0.0, unit="MPa", min=0.0),
        number("epsC0", "Unconfined peak strain eps_c0", 0.002, min=0.001, max=0.005),
        number("flEffMpa", "Effective confining stress f'l", 2.5, unit="MPa", min=0.0, max=25.0),
        number("rhoS", "Volumetric transverse steel ratio rho_s", 0.012, min=0.0, max=0.1),
        number("fyhMpa", "Transverse steel yield strength fyh", 420.0, unit="MPa", min=200.0),
    ],
    requires_project=False,
)
def mander_concrete(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Mander, Priestley & Park (1988) confined concrete stress-strain model."""
    fc = values["fcMpa"]
    ec = values["ecMpa"] if values["ecMpa"] > 0 else concrete_modulus(fc)
    eps_c0 = values["epsC0"]
    fl = values["flEffMpa"]

    # Mander (1988) Eq. 4-6
    fcc = fc * (-1.254 + 2.254 * math.sqrt(1.0 + 7.94 * fl / fc) - 2.0 * fl / fc)
    eps_cc = eps_c0 * (1.0 + 5.0 * (fcc / fc - 1.0))
    e_sec = fcc / eps_cc
    r = ec / max(ec - e_sec, 1e-6)
    eps_cu = 0.004 + 1.4 * values["rhoS"] * values["fyhMpa"] * 0.09 / max(fcc, 1.0)
    eps_cu = max(eps_cu, eps_cc * 1.2)

    rows = []
    steps = 16
    for i in range(steps + 1):
        eps = eps_cu * i / steps
        x = eps / eps_cc
        sigma = fcc * x * r / (r - 1.0 + x**r) if x > 0 else 0.0
        rows.append({"strain": round(eps, 6), "stressMpa": sigma})

    return result(
        summary={
            "confinedStrengthMpa": fcc,
            "confinementRatio": fcc / fc,
            "confinedPeakStrain": eps_cc,
            "ultimateStrain": eps_cu,
        },
        tables=[
            table(
                "Mander (1988) confined concrete curve",
                [("strain", "Strain", "-"), ("stressMpa", "Stress", "MPa")],
                rows,
            )
        ],
        notes=[
            "Mander, Priestley & Park (1988) unified stress-strain model with Popovics backbone.",
            f"Ec = {ec:.0f} MPa, Esec = {e_sec:.0f} MPa, r = {r:.3f}.",
        ],
    )


@feature(
    "library.kentParkModel",
    "Kent-Park Model",
    part="materials",
    fields=[
        number("fcMpa", "Unconfined concrete strength f'c", 30.0, unit="MPa", min=10.0, max=100.0),
        number("rhoS", "Volumetric stirrup ratio rho_s", 0.012, min=0.0, max=0.1),
        number("fyhMpa", "Stirrup yield strength fyh", 420.0, unit="MPa", min=200.0),
        number("hoopWidthMm", "Confined core width b''", 320.0, unit="mm", min=50.0),
        number("spacingMm", "Tie spacing s_h", 150.0, unit="mm", min=25.0),
    ],
    requires_project=False,
)
def kent_park_model(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Modified Kent-Park (1971) / Scott, Park & Priestley (1982) confined concrete curve."""
    fc = values["fcMpa"]
    rho_s = values["rhoS"]
    fyh = values["fyhMpa"]
    k = 1.0 + rho_s * fyh / fc
    fcc = k * fc
    eps_c0 = 0.002 * k
    eps_50u = (3.0 + 0.29 * fc) / max(145.0 * fc - 1000.0, 100.0)
    eps_50h = 0.75 * rho_s * math.sqrt(values["hoopWidthMm"] / values["spacingMm"])
    z_m = 0.5 / max(eps_50u + eps_50h - eps_c0, 1e-4)
    eps_cu = max(0.004 + 0.9 * rho_s * fyh / 300.0, 0.006)

    rows = []
    steps = 16
    for i in range(steps + 1):
        eps = eps_cu * i / steps
        if eps <= eps_c0:
            x = eps / eps_c0
            sigma = fcc * (2.0 * x - x * x)
        else:
            sigma = max(0.2 * fcc, fcc * (1.0 - z_m * (eps - eps_c0)))
        rows.append({"strain": round(eps, 6), "stressMpa": sigma})

    return result(
        summary={
            "enhancementK": k,
            "confinedStrengthMpa": fcc,
            "peakStrain": eps_c0,
            "ultimateStrain": eps_cu,
            "softeningSlopeZm": z_m,
        },
        tables=[
            table(
                "Modified Kent-Park stress-strain curve",
                [("strain", "Strain", "-"), ("stressMpa", "Stress", "MPa")],
                rows,
            )
        ],
        notes=[
            "Matches SAEngine nonlinear fiber core model (K = 1 + rho_s*fyh/f'c, residual 0.2*K*f'c)."
        ],
    )


@feature(
    "library.rambergOsgoodSteel",
    "Ramberg-Osgood Steel",
    part="materials",
    fields=[
        number("modulusMpa", "Initial elastic modulus E0", 200000.0, unit="MPa", min=10000.0),
        number("proofStressMpa", "0.2% proof stress sigma_0.2", 345.0, unit="MPa", min=50.0),
        number("exponentN", "Hardening exponent n", 12.0, min=2.0, max=60.0),
        number("maxStressRatio", "Max stress ratio (sigma / sigma_0.2)", 1.35, min=0.5, max=2.0),
    ],
    requires_project=False,
)
def ramberg_osgood_steel(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Ramberg-Osgood (1943) nonlinear stress-strain model for metals."""
    e0 = values["modulusMpa"]
    sy = values["proofStressMpa"]
    n = values["exponentN"]
    s_max = sy * values["maxStressRatio"]

    rows = []
    steps = 15
    for i in range(steps + 1):
        sig = s_max * i / steps
        eps_el = sig / e0
        eps_pl = 0.002 * (sig / sy) ** n if sig > 0 else 0.0
        eps = eps_el + eps_pl
        e_tan = 1.0 / (1.0 / e0 + 0.002 * n / sy * (sig / sy) ** (n - 1.0)) if sig > 0 else e0
        rows.append(
            {
                "stressMpa": sig,
                "elasticStrain": round(eps_el, 6),
                "plasticStrain": round(eps_pl, 6),
                "totalStrain": round(eps, 6),
                "tangentModulusMpa": e_tan,
            }
        )
    return result(
        summary={
            "proofStressMpa": sy,
            "exponentN": n,
            "maxStressMpa": s_max,
            "maxStrain": rows[-1]["totalStrain"],
        },
        tables=[
            table(
                "Ramberg-Osgood stress-strain curve",
                [
                    ("stressMpa", "Stress", "MPa"),
                    ("elasticStrain", "Elastic strain", "-"),
                    ("plasticStrain", "Plastic strain", "-"),
                    ("totalStrain", "Total strain", "-"),
                    ("tangentModulusMpa", "Et", "MPa"),
                ],
                rows,
            )
        ],
        notes=["eps = sigma/E0 + 0.002*(sigma/sigma_0.2)^n."],
    )


@feature(
    "library.multilinearPlasticity",
    "Multilinear Plasticity",
    part="materials",
    fields=[
        text(
            "backbonePairs",
            "Strain, stress [MPa] control points",
            "0, 0\n0.001725, 345\n0.015, 345\n0.10, 450\n0.18, 410",
        )
    ],
    requires_project=False,
)
def multilinear_plasticity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute segment tangent moduli and energy toughness for a multilinear plasticity curve."""
    pts = sorted(parse_pairs(values["backbonePairs"], "Backbone pairs"), key=lambda p: p[0])
    if len(pts) < 2:
        raise FeatureInputError("Provide at least two (strain, stress) backbone points.")
    rows = []
    energy = 0.0
    for i in range(1, len(pts)):
        e1, s1 = pts[i - 1]
        e2, s2 = pts[i]
        de = e2 - e1
        if de <= 0:
            raise FeatureInputError("Strains must be strictly increasing.")
        et = (s2 - s1) / de
        seg_energy = 0.5 * (s1 + s2) * de
        energy += seg_energy
        rows.append(
            {
                "segment": i,
                "strainEnd": round(e2, 6),
                "stressEndMpa": s2,
                "tangentModulusMpa": et,
                "segmentEnergyMjPerM3": seg_energy,
            }
        )
    return result(
        summary={
            "segmentCount": len(rows),
            "peakStressMpa": max(p[1] for p in pts),
            "ultimateStrain": pts[-1][0],
            "toughnessEnergyMjPerM3": energy,
        },
        tables=[
            table(
                "Multilinear plasticity segments",
                [
                    ("segment", "Segment"),
                    ("strainEnd", "End strain", "-"),
                    ("stressEndMpa", "End stress", "MPa"),
                    ("tangentModulusMpa", "Tangent modulus", "MPa"),
                    ("segmentEnergyMjPerM3", "Strain energy", "MJ/m3"),
                ],
                rows,
            )
        ],
        notes=[
            "Piecewise linear backbone; strain energy integrated by trapezoidal rule (MPa * strain = MJ/m3)."
        ],
    )


@feature(
    "library.materialUnits",
    "Material Units",
    part="materials",
    fields=[
        number("stressMpa", "Strength / stress", 30.0, unit="MPa", min=0.0),
        number("modulusMpa", "Elastic modulus", 25000.0, unit="MPa", min=0.0),
        number("densityKgPerM3", "Mass density", 2400.0, unit="kg/m3", min=0.0),
        number("alphaPerC", "Thermal expansion", 1.0e-5, unit="1/C", min=0.0),
    ],
    requires_project=False,
)
def material_units(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert material mechanical properties across SI and US customary unit systems."""
    s = values["stressMpa"]
    e = values["modulusMpa"]
    rho = values["densityKgPerM3"]
    alpha = values["alphaPerC"]
    rows = [
        {
            "property": "Stress / strength",
            "siBase": f"{s:.3f} MPa",
            "siEng": f"{s * 1000:.1f} kPa",
            "us": f"{s * 145.0377:.1f} psi",
        },
        {
            "property": "Elastic modulus",
            "siBase": f"{e:.1f} MPa",
            "siEng": f"{e / 1000:.3f} GPa",
            "us": f"{e * 0.1450377:.2f} ksi",
        },
        {
            "property": "Density / unit weight",
            "siBase": f"{rho:.1f} kg/m3",
            "siEng": f"{rho * 9.81 / 1000:.2f} kN/m3",
            "us": f"{rho * 0.062428:.2f} pcf",
        },
        {
            "property": "Thermal expansion",
            "siBase": f"{alpha:.2e} 1/C",
            "siEng": f"{alpha * 1e6:.2f} ueps/C",
            "us": f"{alpha / 1.8:.2e} 1/F",
        },
    ]
    return result(
        summary={
            "stressPsi": s * 145.0377,
            "modulusKsi": e * 0.1450377,
            "unitWeightKnPerM3": rho * 9.81 / 1000.0,
            "densityPcf": rho * 0.062428,
        },
        tables=[
            table(
                "Material unit conversions",
                [
                    ("property", "Property"),
                    ("siBase", "SI Base"),
                    ("siEng", "SI Engineering"),
                    ("us", "US Customary"),
                ],
                rows,
            )
        ],
        notes=["Internal SAEngine storage always uses MPa, mm, kg/m3, and 1/C."],
    )


@feature(
    "library.standardDesignations",
    "Standard Designations",
    part="materials",
    fields=[text("materialId", "Project material ID (blank = all)", "")],
    requires_project=False,
)
def standard_designations(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map library materials to recognised generic strength classes and grade designations."""
    lib, is_project = materials_or_default(ctx)
    target = values["materialId"].strip()
    mats = [m for m in lib.materials if not target or m.id.lower() == target.lower()]
    if not mats:
        raise FeatureInputError(f"Material {target!r} not found.")
    rows = []
    for m in mats:
        if m.category == Category.CONCRETE and m.concrete:
            fc = m.concrete.fc
            equiv = f"C{round(fc)}/{round(fc * 1.22)}"
        elif m.category in (Category.REBAR, Category.STEEL) and m.steel:
            equiv = m.steel.grade or f"Grade {m.steel.fy:g}"
        elif m.category == Category.MASONRY and m.masonry:
            equiv = m.masonry.mortarType or m.masonry.unit
        else:
            equiv = m.id
        rows.append(
            {
                "id": m.id,
                "name": m.name,
                "category": m.category.value,
                "designation": equiv,
                "documentedStandard": (m.source.standard if m.source else "") or "Unspecified",
            }
        )
    return result(
        summary={"mappedCount": len(rows), "source": "project" if is_project else "default"},
        tables=[
            table(
                "Standard designations",
                [
                    ("id", "ID"),
                    ("name", "Name"),
                    ("category", "Category"),
                    ("designation", "Equivalent class"),
                    ("documentedStandard", "Source standard"),
                ],
                rows,
            )
        ],
        notes=[
            "Cylinder-to-cube conversion approximated as f_cube ≈ 1.22 f'c for normal-weight concrete."
        ],
    )


@feature(
    "library.batchValidation",
    "Batch Validation",
    part="materials",
    fields=[checkbox("includeWarnings", "Include plausibility warnings", True)],
    requires_project=True,
)
def batch_validation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate every material in 03 Materials/materials.json against schema and guardrails."""
    lib = require_materials(ctx)
    raw_text = safe_json(lib.model_dump(mode="json", by_alias=True, exclude_none=True))
    with in_force(ctx.root):
        problems = check_library("materials", raw_text)
    rows = []
    errors = 0
    warnings = 0
    for p in problems:
        sev = p.get("severity", "error")
        if sev == "warning":
            if not values["includeWarnings"]:
                continue
            warnings += 1
        else:
            errors += 1
        idx = p.get("index")
        mid = (
            lib.materials[idx].id
            if isinstance(idx, int) and 0 <= idx < len(lib.materials)
            else "library"
        )
        rows.append(
            {
                "materialId": mid,
                "severity": sev,
                "path": p.get("path", ""),
                "message": p.get("message", ""),
            }
        )
    return result(
        summary={
            "materialCount": len(lib.materials),
            "errorCount": errors,
            "warningCount": warnings,
            "passed": errors == 0,
        },
        tables=[
            table(
                "Batch validation findings",
                [
                    ("materialId", "Material"),
                    ("severity", "Severity"),
                    ("path", "Field"),
                    ("message", "Finding"),
                ],
                rows,
            )
        ],
        notes=[
            "Uses saengine.library.check.check_library('materials') with the project code pack in force."
        ],
    )

"""Project Settings - Occupancy & Space Use tab: occupancy classes, live loads, people density, ventilation."""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
from saengine.features import (
    FeatureContext,
    checkbox,
    feature,
    number,
    result,
    table,
)
from saengine.features.settings_common import (
    active_pack,
    export_file,
    json_dumps_clean,
    load_settings,
    safe_table,
)
from saengine.report.clauses import in_force


@feature(
    "settingsOccupancy.occupancyClass",
    "Occupancy Class",
    part="settings",
    fields=[],
    requires_project=False,
)
def occupancy_class(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect project building use, occupancy category, and code pack category definitions."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        occ = safe_table(pack, "occupancyCategories")
        cats = getattr(occ, "categories", None) or {}
    rows = [
        {
            "category": k,
            "description": v.description,
            "seismicImportance": v.seismicImportance,
            "windImportance": v.windImportance,
            "selected": k == st.occupancy.category,
        }
        for k, v in cats.items()
    ]
    return result(
        summary={
            "buildingUse": st.occupancy.use,
            "category": st.occupancy.category,
            "cycloneShelter": st.occupancy.cycloneShelter,
            "categoryCount": len(rows),
        },
        tables=[
            table(
                "Occupancy categories",
                [
                    ("category", "Cat"),
                    ("description", "Description"),
                    ("seismicImportance", "I_seismic"),
                    ("windImportance", "I_wind"),
                    ("selected", "Selected"),
                ],
                rows,
            )
        ],
        notes=[f"Occupancy categories defined by {code_context.code_name(pack)}."],
    )


@feature(
    "settingsOccupancy.importanceFactor",
    "Importance Factor",
    part="settings",
    fields=[],
    requires_project=False,
)
def importance_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report seismic, wind, snow, and flood importance factors derived from occupancy category."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        occ = safe_table(pack, "occupancyCategories")
        cat = occ.categories.get(st.occupancy.category) if occ else None
        snow = safe_table(pack, "snow")
        flood = safe_table(pack, "flood")
    i_seis = float(cat.seismicImportance) if cat else 1.0
    i_wind = float(cat.windImportance) if cat else 1.0
    i_snow = (
        float((getattr(snow, "importance", None) or {}).get(st.occupancy.category, 1.0))
        if snow
        else 1.0
    )
    t_flood = (
        int((getattr(flood, "returnPeriod", None) or {}).get(st.occupancy.category, 50))
        if flood
        else 50
    )
    rows = [
        {"hazard": "Seismic", "factor": i_seis, "unit": "-"},
        {"hazard": "Wind", "factor": i_wind, "unit": "-"},
        {"hazard": "Snow", "factor": i_snow, "unit": "-"},
        {"hazard": "Flood return period", "factor": float(t_flood), "unit": "yr"},
    ]
    return result(
        summary={
            "category": st.occupancy.category,
            "seismicI": i_seis,
            "windI": i_wind,
            "snowI": i_snow,
            "floodReturnYears": t_flood,
        },
        tables=[
            table(
                "Derived importance factors",
                [("hazard", "Hazard"), ("factor", "Factor / period"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Derived directly from active code pack occupancyCategories, snow, and flood tables."
        ],
    )


@feature(
    "settingsOccupancy.occupantLoad",
    "Occupant Load",
    part="settings",
    fields=[
        number("floorAreaM2", "Gross floor area", 1200.0, unit="m²", min=10.0),
        number("areaPerPersonM2", "Occupant load factor", 9.3, unit="m²/person", min=0.5),
    ],
    requires_project=False,
)
def occupant_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate design occupant count for egress width and building services sizing."""
    occ_count = math.ceil(values["floorAreaM2"] / values["areaPerPersonM2"])
    egress_width_mm = occ_count * 5.0  # 5 mm/person stair/door guideline
    rows = [
        {"metric": "Gross floor area", "value": values["floorAreaM2"], "unit": "m²"},
        {"metric": "Area per person", "value": values["areaPerPersonM2"], "unit": "m²/person"},
        {"metric": "Design occupant load", "value": float(occ_count), "unit": "persons"},
        {"metric": "Minimum exit width (5 mm/person)", "value": egress_width_mm, "unit": "mm"},
    ]
    return result(
        summary={"occupantCount": occ_count, "egressWidthMm": egress_width_mm},
        tables=[
            table(
                "Occupant load calculation",
                [("metric", "Metric"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Occupant count = ceil(Area / Area-per-person)."],
    )


@feature(
    "settingsOccupancy.exposureCategory",
    "Exposure Category",
    part="settings",
    fields=[],
    requires_project=False,
)
def exposure_category(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Review building wind exposure and concrete aggregate durability settings."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        wind_tbl = safe_table(pack, "wind")
        exp = (getattr(wind_tbl, "exposures", None) or {}).get(st.wind.exposure)
    rows = [
        {
            "aspect": "Wind exposure category",
            "setting": st.wind.exposure,
            "detail": exp.description if exp else "-",
        },
        {
            "aspect": "Envelope enclosure",
            "setting": st.wind.enclosure,
            "detail": "Internal pressure classification",
        },
        {
            "aspect": "Concrete aggregate",
            "setting": st.construction.aggregate,
            "detail": "Durability & modulus basis",
        },
    ]
    return result(
        summary={
            "windExposure": st.wind.exposure,
            "enclosure": st.wind.enclosure,
            "aggregate": st.construction.aggregate,
        },
        tables=[
            table(
                "Environmental exposure summary",
                [("aspect", "Aspect"), ("setting", "Setting"), ("detail", "Detail")],
                rows,
            )
        ],
        notes=[
            "Combines wind terrain exposure, building enclosure, and concrete aggregate settings."
        ],
    )


@feature(
    "settingsOccupancy.corrosionClass",
    "Corrosion Class",
    part="settings",
    fields=[
        number(
            "soilResistivityOhmCm", "Soil electrical resistivity", 2500.0, unit="Ω·cm", min=100.0
        ),
        number("chloridePpm", "Soil/groundwater chloride Cl-", 250.0, unit="ppm", min=0.0),
        number("sulfatePpm", "Soil/groundwater sulfate SO4", 400.0, unit="ppm", min=0.0),
        number("designLifeYears", "Buried steel design life", 50.0, unit="yr", min=10.0),
    ],
    requires_project=False,
)
def corrosion_class(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Classify buried steel corrosion aggressiveness and sacrificial steel thickness allowance."""
    res = values["soilResistivityOhmCm"]
    cl = values["chloridePpm"]
    so4 = values["sulfatePpm"]
    life = values["designLifeYears"]
    if res < 1000.0 or cl > 500.0 or so4 > 1500.0:
        cls_name, rate_mm_yr = "Severe / Aggressive", 0.050
    elif res < 3000.0 or cl > 150.0 or so4 > 500.0:
        cls_name, rate_mm_yr = "Moderate", 0.025
    else:
        cls_name, rate_mm_yr = "Mild / Non-aggressive", 0.012
    sacrificial_mm = rate_mm_yr * life
    rows = [
        {"parameter": "Corrosion class", "value": cls_name},
        {"parameter": "Estimated loss rate [mm/yr/face]", "value": f"{rate_mm_yr:.3f}"},
        {
            "parameter": f"Sacrificial thickness over {life:g} yr [mm/face]",
            "value": f"{sacrificial_mm:.2f}",
        },
    ]
    return result(
        summary={
            "corrosionClass": cls_name,
            "lossRateMmPerYr": rate_mm_yr,
            "sacrificialThicknessMm": sacrificial_mm,
        },
        tables=[
            table(
                "Buried steel corrosion screening",
                [("parameter", "Parameter"), ("value", "Value")],
                rows,
            )
        ],
        notes=[
            "Resistivity < 1000 Ω·cm or high chlorides/sulfates requires coating or cathodic protection."
        ],
    )


@feature(
    "settingsOccupancy.fireRating",
    "Fire Rating",
    part="settings",
    fields=[
        number("ratingHours", "Required fire resistance rating", 2.0, unit="hr", min=0.5, max=4.0),
    ],
    requires_project=False,
)
def fire_rating(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Look up minimum concrete slab thickness and column dimension for required fire rating."""
    st = load_settings(ctx)
    hrs = values["ratingHours"]
    agg = st.construction.aggregate
    with in_force(ctx.root, st):
        from saengine.design import fire_resistance

        if fire_resistance.covered():
            slab_t = fire_resistance.required("thickness", hrs, agg)
            col_d = fire_resistance.required("columnSize", hrs, agg)
            ctype = st.construction.constructionType
            rows = [
                {"element": "Slab / wall min equivalent thickness", "mm": slab_t or 0.0},
                {"element": "Column min dimension", "mm": col_d or 0.0},
            ]
        else:
            ctype = st.construction.constructionType
            slab_t, col_d = 125.0, 250.0
            rows = [{"element": "Fire table not applicable in pack", "mm": 0.0}]
    return result(
        summary={
            "constructionType": ctype,
            "aggregate": agg,
            "ratingHours": hrs,
            "minSlabThicknessMm": float(slab_t or 0.0),
            "minColumnSizeMm": float(col_d or 0.0),
        },
        tables=[
            table(
                "Fire resistance minimum member sizes",
                [("element", "Element"), ("mm", "Minimum size", "mm")],
                rows,
            )
        ],
        notes=["Read from active code pack fireResistance table using project concrete aggregate."],
    )


@feature(
    "settingsOccupancy.floorLiveLoad",
    "Floor Live Load",
    part="settings",
    fields=[],
    requires_project=False,
)
def floor_live_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List floor live loads from the active code pack areaLoads table and check project areas."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        area_tbl = safe_table(pack, "areaLoads")
        uses = getattr(area_tbl, "uses", None) or {}
    rows = [
        {
            "areaId": a.id,
            "name": a.name,
            "use": a.use,
            "projectLiveKnPerM2": a.live,
            "packMinKnPerM2": uses[a.use].live if a.use in uses else 0.0,
            "compliant": (a.live >= uses[a.use].live) if a.use in uses else True,
        }
        for a in st.areaLoads
    ]
    return result(
        summary={"areaLoadCount": len(rows), "allCompliant": all(r["compliant"] for r in rows)},
        tables=[
            table(
                "Project floor live loads vs pack minimums",
                [
                    ("areaId", "ID"),
                    ("name", "Name"),
                    ("use", "Use"),
                    ("projectLiveKnPerM2", "Project", "kN/m²"),
                    ("packMinKnPerM2", "Code min", "kN/m²"),
                    ("compliant", "OK"),
                ],
                rows,
            )
        ],
        notes=["Compares project areaLoads against the active code pack areaLoads.uses minimums."],
    )


@feature(
    "settingsOccupancy.roofLiveLoad",
    "Roof Live Load",
    part="settings",
    fields=[
        number("tributaryAreaM2", "Roof member tributary area At", 25.0, unit="m²", min=1.0),
        number("roofSlopePct", "Roof slope F (%)", 5.0, unit="%", min=0.0, max=100.0),
        number("baseRoofLiveKnPerM2", "Unreduced roof live load Lr0", 1.0, unit="kN/m²", min=0.2),
    ],
    requires_project=False,
)
def roof_live_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute reduced ordinary roof live load Lr = L0 × R1 × R2 from area and slope."""
    st = load_settings(ctx)
    at = values["tributaryAreaM2"]
    slope = values["roofSlopePct"]
    lr0 = values["baseRoofLiveKnPerM2"]
    with in_force(ctx.root, st):
        from saengine.design import live_reduction

        try:
            res = live_reduction.roof_reduction(at, lr0, slope=slope)
            lr_red = res.reduced if hasattr(res, "reduced") else lr0
            factor = res.factor if hasattr(res, "factor") else 1.0
        except Exception:  # noqa: BLE001
            r1 = 1.0 if at <= 18.58 else (0.6 if at >= 55.74 else 1.2 - 0.0108 * at)
            r2 = 1.0 if slope <= 33.3 else (0.6 if slope >= 100.0 else 1.2 - 0.006 * slope)
            factor = max(0.6, min(1.0, r1 * r2))
            lr_red = lr0 * factor
    rows = [
        {"metric": "Base roof live load Lr0", "value": lr0, "unit": "kN/m²"},
        {"metric": "Reduction factor R1·R2", "value": factor, "unit": "-"},
        {"metric": "Reduced roof live load Lr", "value": lr_red, "unit": "kN/m²"},
    ]
    return result(
        summary={
            "baseRoofLiveKnPerM2": lr0,
            "reductionFactor": factor,
            "reducedRoofLiveKnPerM2": lr_red,
        },
        tables=[
            table(
                "Roof live load reduction",
                [("metric", "Metric"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Evaluates roof live load reduction from tributary area and roof pitch."],
    )


@feature(
    "settingsOccupancy.storageLoad",
    "Storage Load",
    part="settings",
    fields=[
        number("bulkDensityKnPerM3", "Stored goods bulk unit weight", 6.5, unit="kN/m³", min=1.0),
        number("stackHeightM", "Stacking height", 2.4, unit="m", min=0.3),
        number("aisleUtilization", "Floor plan net storage ratio", 0.75, min=0.2, max=1.0),
    ],
    requires_project=False,
)
def storage_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute equivalent storage floor load from bulk density, stack height, and aisle ratio."""
    gross_kpa = values["bulkDensityKnPerM3"] * values["stackHeightM"]
    net_kpa = gross_kpa * values["aisleUtilization"]
    rows = [
        {"case": "Localized rack/stack footprint", "loadKnPerM2": gross_kpa},
        {"case": "Bay-averaged with aisles", "loadKnPerM2": net_kpa},
    ]
    return result(
        summary={"stackFootprintKnPerM2": gross_kpa, "bayAverageKnPerM2": net_kpa},
        tables=[
            table(
                "Storage live load estimate",
                [("case", "Basis"), ("loadKnPerM2", "Load", "kN/m²")],
                rows,
            )
        ],
        notes=[
            "Localized slab checks should use full stack footprint intensity without aisle averaging."
        ],
    )


@feature(
    "settingsOccupancy.concentratedLoad",
    "Concentrated Load",
    part="settings",
    fields=[
        number("pointLoadKn", "Design concentrated point load P", 9.0, unit="kN", min=0.5),
        number("patchSizeMm", "Load contact patch dimension", 300.0, unit="mm", min=50.0),
        number("slabThicknessMm", "Slab thickness h", 180.0, unit="mm", min=80.0),
    ],
    requires_project=False,
)
def concentrated_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check local slab bearing and punching perimeter demand under concentrated equipment loads."""
    p = values["pointLoadKn"]
    a = values["patchSizeMm"]
    d = max(50.0, values["slabThicknessMm"] - 30.0)
    bo = 4.0 * (a + d)
    v_stress_mpa = (p * 1000.0) / (bo * d)
    bearing_mpa = (p * 1000.0) / (a * a)
    rows = [
        {"metric": "Contact patch pressure", "value": bearing_mpa, "unit": "MPa"},
        {"metric": "Critical punching perimeter bo", "value": bo, "unit": "mm"},
        {"metric": "Nominal punching shear stress", "value": v_stress_mpa, "unit": "MPa"},
    ]
    return result(
        summary={
            "pointLoadKn": p,
            "contactPressureMpa": bearing_mpa,
            "punchingStressMpa": v_stress_mpa,
        },
        tables=[
            table(
                "Concentrated load local check",
                [("metric", "Metric"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Evaluates punching perimeter at d/2 from the concentrated contact patch."],
    )


@feature(
    "settingsOccupancy.loadReductionRule",
    "Load Reduction Rule",
    part="settings",
    fields=[
        number("tributaryAreaM2", "Tributary area At", 60.0, unit="m²", min=1.0),
        number("floorsSupported", "Number of floors supported", 4.0, min=1.0, max=100.0),
        number("baseLiveKnPerM2", "Unreduced live load L0", 2.5, unit="kN/m²", min=0.5),
    ],
    requires_project=False,
)
def load_reduction_rule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute live load reduction factor for columns/beams using active code pack rules."""
    st = load_settings(ctx)
    at = values["tributaryAreaM2"]
    floors = int(values["floorsSupported"])
    l0 = values["baseLiveKnPerM2"]
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        lr_tbl = safe_table(pack, "liveReduction")
        kll = float(getattr(getattr(lr_tbl, "kll", None), "interiorColumn", 4.0) or 4.0)
        inf_min = float(getattr(lr_tbl, "influenceMin", 37.16) or 37.16)
        c0 = float(getattr(lr_tbl, "constant", 0.25) or 0.25)
        c1 = float(getattr(lr_tbl, "coefficient", 4.57) or 4.57)
        min_one = float(getattr(lr_tbl, "minOneFloor", 0.5) or 0.5)
        min_multi = float(getattr(lr_tbl, "minFloors", 0.4) or 0.4)
    ai = kll * at
    if st.occupancy.cycloneShelter:
        factor = 1.0
        reason = "Cyclone shelter: live load not reduced"
    elif ai < inf_min:
        factor = 1.0
        reason = f"Influence area {ai:.1f} m² < {inf_min:.1f} m²"
    else:
        raw = c0 + c1 / math.sqrt(ai)
        floor_min = min_one if floors == 1 else min_multi
        factor = min(1.0, max(floor_min, raw))
        reason = f"Influence area {ai:.1f} m²"
    rows = [
        {"parameter": "Influence area KLL·At", "value": ai, "unit": "m²"},
        {"parameter": "Reduction factor L / L0", "value": factor, "unit": "-"},
        {"parameter": "Reduced live load L", "value": l0 * factor, "unit": "kN/m²"},
    ]
    return result(
        summary={
            "influenceAreaM2": ai,
            "reductionFactor": factor,
            "reducedLiveKnPerM2": l0 * factor,
        },
        tables=[
            table(
                "Live load reduction",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[f"{reason} (active pack {code_context.code_name(pack)})."],
    )


@feature(
    "settingsOccupancy.peopleDensity",
    "People Density",
    part="settings",
    fields=[
        number("areaM2", "Space net floor area", 250.0, unit="m²", min=1.0),
        number("m2PerPerson", "Floor area per occupant", 1.5, unit="m²/person", min=0.25),
        number("avgPersonMassKg", "Mean occupant mass", 75.0, unit="kg", min=40.0, max=120.0),
    ],
    requires_project=False,
)
def people_density(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Derive occupant count and equivalent static crowd pressure from occupant density."""
    n_people = values["areaM2"] / values["m2PerPerson"]
    static_kpa = (values["avgPersonMassKg"] * 9.80665e-3) / values["m2PerPerson"]
    rows = [
        {"metric": "Occupant density", "value": 1.0 / values["m2PerPerson"], "unit": "persons/m²"},
        {"metric": "Estimated occupants", "value": n_people, "unit": "persons"},
        {"metric": "Static occupant weight", "value": static_kpa, "unit": "kN/m²"},
    ]
    return result(
        summary={"occupants": n_people, "staticLoadKnPerM2": static_kpa},
        tables=[
            table(
                "Occupant density load",
                [("metric", "Metric"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Dynamic crowd amplification applies to assembly/jumping spaces."],
    )


@feature(
    "settingsOccupancy.seatedOccupancy",
    "Seated Occupancy",
    part="settings",
    fields=[
        number("seatCount", "Number of fixed seats", 400.0, min=1.0),
        number("hallAreaM2", "Auditorium / seating hall area", 350.0, unit="m²", min=10.0),
        number("seatWeightKn", "Fixed seat unit weight", 0.35, unit="kN", min=0.0),
    ],
    requires_project=False,
)
def seated_occupancy(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute distributed live and fixed-seating dead load for fixed-seat auditoriums."""
    n = values["seatCount"]
    area = values["hallAreaM2"]
    seat_dl = (n * values["seatWeightKn"]) / area
    occ_ll = (n * 0.75) / area  # 75 kg/person static baseline
    rows = [
        {"component": "Fixed seat dead load", "loadKnPerM2": seat_dl},
        {"component": "Static seated occupant load", "loadKnPerM2": occ_ll},
    ]
    return result(
        summary={"seatsPerM2": n / area, "seatDeadKnPerM2": seat_dl, "occupantLiveKnPerM2": occ_ll},
        tables=[
            table(
                "Fixed-seat hall loads",
                [("component", "Component"), ("loadKnPerM2", "Load", "kN/m²")],
                rows,
            )
        ],
        notes=["Check active pack areaLoads.uses for minimum fixed-seat assembly load."],
    )


@feature(
    "settingsOccupancy.assemblyLoads",
    "Assembly Loads",
    part="settings",
    fields=[
        number("staticCrowdKnPerM2", "Static crowd load", 4.0, unit="kN/m²", min=1.0),
        number("dynamicFactor", "Rhythmic crowd dynamic factor", 1.5, min=1.0, max=2.5),
    ],
    requires_project=False,
)
def assembly_loads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate movable-seat assembly and dynamic crowd loading."""
    eff = values["staticCrowdKnPerM2"] * values["dynamicFactor"]
    return result(
        summary={"staticKnPerM2": values["staticCrowdKnPerM2"], "effectiveDynamicKnPerM2": eff},
        tables=[
            table(
                "Assembly crowd load",
                [("mode", "Mode"), ("loadKnPerM2", "Load", "kN/m²")],
                [
                    {"mode": "Static", "loadKnPerM2": values["staticCrowdKnPerM2"]},
                    {"mode": "With rhythmic factor", "loadKnPerM2": eff},
                ],
            )
        ],
        notes=[
            "Assembly areas with movable seating are normally excluded from live load reduction."
        ],
    )


@feature(
    "settingsOccupancy.mercantileLoad",
    "Mercantile Load",
    part="settings",
    fields=[
        number("retailAreaM2", "Retail / display floor area", 800.0, unit="m²", min=10.0),
        number(
            "displayRackAllowanceKnPerM2", "Display shelving allowance", 1.2, unit="kN/m²", min=0.0
        ),
    ],
    requires_project=False,
)
def mercantile_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Retrieve retail/mercantile live load from active pack and evaluate total floor load."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        uses = getattr(safe_table(pack, "areaLoads"), "uses", None) or {}
        retail = uses.get("retail") or uses.get("mercantile")
        base_live = float(retail.live) if retail else 4.8
    total_live = base_live + values["displayRackAllowanceKnPerM2"]
    return result(
        summary={
            "packRetailLiveKnPerM2": base_live,
            "totalLiveKnPerM2": total_live,
            "totalForceKn": total_live * values["retailAreaM2"],
        },
        tables=[
            table(
                "Mercantile floor loading",
                [("item", "Item"), ("loadKnPerM2", "Load", "kN/m²")],
                [
                    {"item": "Code pack retail live", "loadKnPerM2": base_live},
                    {"item": "With display racks", "loadKnPerM2": total_live},
                ],
            )
        ],
        notes=["Retail/mercantile base live load taken from active pack areaLoads.uses."],
    )


@feature(
    "settingsOccupancy.egressOccupancy",
    "Egress Occupancy",
    part="settings",
    fields=[
        number("assemblyM2", "Assembly zone area", 200.0, unit="m²", min=0.0),
        number("officeM2", "Office zone area", 800.0, unit="m²", min=0.0),
        number("storageM2", "Storage zone area", 150.0, unit="m²", min=0.0),
    ],
    requires_project=False,
)
def egress_occupancy(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute mixed-use building egress occupant counts and required exit stair units."""
    zones = [
        ("Assembly (1.4 m²/person)", values["assemblyM2"], 1.4),
        ("Office (9.3 m²/person)", values["officeM2"], 9.3),
        ("Storage (27.9 m²/person)", values["storageM2"], 27.9),
    ]
    rows = []
    total_occ = 0
    for name, area, factor in zones:
        cnt = math.ceil(area / factor) if area > 0 else 0
        total_occ += cnt
        rows.append({"zone": name, "areaM2": area, "occupants": cnt})
    stair_width_mm = max(1100.0, total_occ * 7.6)
    return result(
        summary={"totalOccupants": total_occ, "requiredStairWidthMm": stair_width_mm},
        tables=[
            table(
                "Mixed-use egress count",
                [("zone", "Space type"), ("areaM2", "Area", "m²"), ("occupants", "Occupants")],
                rows,
            )
        ],
        notes=["Stair capacity sized at 7.6 mm per occupant with 1100 mm minimum clear width."],
    )


@feature(
    "settingsOccupancy.hospitalOccupancy",
    "Hospital Occupancy",
    part="settings",
    fields=[
        number("wardAreaM2", "Patient ward area", 600.0, unit="m²", min=0.0),
        number("imagingEquipmentKn", "Heavy imaging / MRI unit weight", 65.0, unit="kN", min=0.0),
    ],
    requires_project=False,
)
def hospital_occupancy(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure healthcare occupancy loads and essential facility seismic importance."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        occ = safe_table(pack, "occupancyCategories")
        cat4 = occ.categories.get("IV") if occ else None
        uses = getattr(safe_table(pack, "areaLoads"), "uses", None) or {}
        ward_live = float(uses["hospital"].live) if "hospital" in uses else 2.0
    return result(
        summary={
            "wardLiveKnPerM2": ward_live,
            "essentialSeismicI": float(cat4.seismicImportance) if cat4 else 1.5,
            "imagingLoadKn": values["imagingEquipmentKn"],
        },
        tables=[
            table(
                "Hospital design parameters",
                [("item", "Parameter"), ("value", "Value")],
                [
                    {"item": "Ward live load [kN/m²]", "value": ward_live},
                    {
                        "item": "Category IV seismic I",
                        "value": float(cat4.seismicImportance) if cat4 else 1.5,
                    },
                    {"item": "Equipment load [kN]", "value": values["imagingEquipmentKn"]},
                ],
            )
        ],
        notes=[
            "Essential healthcare facilities map to Occupancy Category IV for seismic/wind importance."
        ],
    )


@feature(
    "settingsOccupancy.laboratoryLoad",
    "Laboratory Load",
    part="settings",
    fields=[
        number("benchLoadKnPerM2", "Laboratory bench & fume hood UDL", 3.0, unit="kN/m²", min=0.5),
        number(
            "vibrationLimitMmPerS",
            "Peak velocity vibration threshold",
            0.05,
            unit="mm/s",
            min=0.005,
        ),
    ],
    requires_project=False,
)
def laboratory_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set laboratory equipment loading and sensitive optical/microscope floor vibration limits."""
    return result(
        summary={
            "benchLiveKnPerM2": values["benchLoadKnPerM2"],
            "vibrationLimitMmPerS": values["vibrationLimitMmPerS"],
        },
        tables=[
            table(
                "Laboratory design targets",
                [("criterion", "Criterion"), ("value", "Value")],
                [
                    {"criterion": "Design UDL [kN/m²]", "value": values["benchLoadKnPerM2"]},
                    {
                        "criterion": "Vibration velocity limit [mm/s]",
                        "value": values["vibrationLimitMmPerS"],
                    },
                ],
            )
        ],
        notes=[
            "Sensitive laboratory floors should also be checked for fundamental frequency >= 8 Hz."
        ],
    )


@feature(
    "settingsOccupancy.parkingLoad",
    "Parking Load",
    part="settings",
    fields=[
        number("vehicleGrossKn", "Design passenger vehicle weight", 22.0, unit="kN", min=10.0),
        number("rampSlopePct", "Parking ramp gradient", 12.0, unit="%", min=0.0, max=20.0),
    ],
    requires_project=False,
)
def parking_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Retrieve garage vehicle/wheel loads from active code pack and check ramp barrier demand."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        area_tbl = safe_table(pack, "areaLoads")
        veh = getattr(area_tbl, "vehicles", None)
        wheel_kn = float(getattr(veh, "wheel", 9.0) or 9.0)
        uses = getattr(area_tbl, "uses", None) or {}
        garage_live = float(uses["parking"].live) if "parking" in uses else 2.5
    rows = [
        {"parameter": "Garage distributed live load", "value": garage_live, "unit": "kN/m²"},
        {"parameter": "Code concentrated wheel load", "value": wheel_kn, "unit": "kN"},
        {"parameter": "Ramp grade", "value": values["rampSlopePct"], "unit": "%"},
    ]
    return result(
        summary={
            "garageLiveKnPerM2": garage_live,
            "wheelLoadKn": wheel_kn,
            "vehicleWeightKn": values["vehicleGrossKn"],
        },
        tables=[
            table(
                "Parking structure load parameters",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Parking deck wheel load and UDL sourced from active pack areaLoads.vehicles."],
    )


@feature(
    "settingsOccupancy.storageRacking",
    "Storage Racking",
    part="settings",
    fields=[
        number("uprightLoadKn", "Single rack leg vertical load", 65.0, unit="kN", min=1.0),
        number("baseplateWidthMm", "Rack baseplate dimension", 150.0, unit="mm", min=50.0),
        number("slabThicknessMm", "Slab-on-grade thickness", 200.0, unit="mm", min=100.0),
    ],
    requires_project=False,
)
def storage_racking(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check rack post baseplate bearing stress and punching shear demand on warehouse slabs."""
    p = values["uprightLoadKn"]
    b = values["baseplateWidthMm"]
    bearing_mpa = (p * 1000.0) / (b * b)
    d = max(50.0, values["slabThicknessMm"] - 40.0)
    punch_mpa = (p * 1000.0) / (4.0 * (b + d) * d)
    return result(
        summary={"uprightLoadKn": p, "bearingMpa": bearing_mpa, "punchingStressMpa": punch_mpa},
        tables=[
            table(
                "Rack leg slab check",
                [("check", "Check"), ("stressMpa", "Demand", "MPa")],
                [
                    {"check": "Baseplate bearing", "stressMpa": bearing_mpa},
                    {"check": "Slab punching shear", "stressMpa": punch_mpa},
                ],
            )
        ],
        notes=[
            "Adjacent back-to-back rack legs should be checked as combined punching perimeters."
        ],
    )


@feature(
    "settingsOccupancy.ventilationRate",
    "Ventilation Rate",
    part="settings",
    fields=[
        number("lPerSecPerson", "Outdoor air per person Rp", 2.5, unit="L/s·person", min=0.5),
        number("lPerSecM2", "Outdoor air per area Ra", 0.3, unit="L/s·m²", min=0.0),
    ],
    requires_project=False,
)
def ventilation_rate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define minimum fresh air ventilation rates per occupant and per unit floor area."""
    return result(
        summary={"rpLPerSecPerson": values["lPerSecPerson"], "raLPerSecM2": values["lPerSecM2"]},
        tables=[
            table(
                "Ventilation rate basis",
                [("parameter", "Rate"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "parameter": "Per person Rp",
                        "value": values["lPerSecPerson"],
                        "unit": "L/(s·person)",
                    },
                    {
                        "parameter": "Per floor area Ra",
                        "value": values["lPerSecM2"],
                        "unit": "L/(s·m²)",
                    },
                ],
            )
        ],
        notes=["Outdoor air breathing zone requirement Vbz = Rp·Pz + Ra·Az."],
    )


@feature(
    "settingsOccupancy.freshAirDemand",
    "Fresh Air Demand",
    part="settings",
    fields=[
        number("floorAreaM2", "Conditioned floor area Az", 1500.0, unit="m²", min=10.0),
        number("occupants", "Design occupant count Pz", 120.0, min=1.0),
        number("rpLPerSecPerson", "Rp per person", 2.5, unit="L/s·person", min=0.5),
        number("raLPerSecM2", "Ra per area", 0.3, unit="L/s·m²", min=0.0),
    ],
    requires_project=False,
)
def fresh_air_demand(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate total building outdoor fresh-air flow demand Vbz = Rp Pz + Ra Az."""
    vbz_ls = (
        values["rpLPerSecPerson"] * values["occupants"]
        + values["raLPerSecM2"] * values["floorAreaM2"]
    )
    vbz_m3h = vbz_ls * 3.6
    return result(
        summary={"freshAirLPerS": vbz_ls, "freshAirM3PerHr": vbz_m3h},
        tables=[
            table(
                "Total outdoor air demand",
                [("metric", "Metric"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"metric": "Flow rate", "value": vbz_ls, "unit": "L/s"},
                    {"metric": "Hourly flow", "value": vbz_m3h, "unit": "m³/h"},
                ],
            )
        ],
        notes=["Sum of occupant-based and floor-area-based outdoor air components."],
    )


@feature(
    "settingsOccupancy.occupancySchedule",
    "Occupancy Schedule",
    part="settings",
    fields=[],
    requires_project=False,
)
def occupancy_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile a full schedule of project area uses, live loads, finishes, and partitions."""
    st = load_settings(ctx)
    rows = [
        {
            "id": a.id,
            "name": a.name,
            "use": a.use,
            "liveKnPerM2": a.live,
            "finishKnPerM2": a.finish,
            "partitionsKnPerM2": a.partitions,
        }
        for a in st.areaLoads
    ]
    return result(
        summary={"scheduleRows": len(rows), "primaryUse": st.occupancy.use},
        tables=[
            table(
                "Project occupancy & area load schedule",
                [
                    ("id", "ID"),
                    ("name", "Name"),
                    ("use", "Use"),
                    ("liveKnPerM2", "Live", "kN/m²"),
                    ("finishKnPerM2", "Finish", "kN/m²"),
                    ("partitionsKnPerM2", "Partitions", "kN/m²"),
                ],
                rows,
            )
        ],
        notes=["Lists all area load definitions currently stored in 02 Project Settings."],
    )


@feature(
    "settingsOccupancy.loadExport",
    "Load Export",
    part="settings",
    fields=[
        checkbox("writeJson", "Write JSON schedule to exports", True),
    ],
    requires_project=False,
)
def load_export(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export project occupancy-derived area loads to 02 Project Settings/exports/occupancy-loads.json."""
    st = load_settings(ctx)
    payload = {
        "buildingUse": st.occupancy.use,
        "category": st.occupancy.category,
        "areaLoads": [a.model_dump(mode="json") for a in st.areaLoads],
    }
    out_path = None
    if values["writeJson"] and ctx.root is not None:
        out_path = export_file(ctx, "occupancy-loads.json", json_dumps_clean(payload))
    return result(
        summary={"exportedAreaCount": len(st.areaLoads), "exported": out_path is not None},
        tables=[
            table(
                "Exported occupancy loads",
                [("id", "ID"), ("name", "Name"), ("live", "Live", "kN/m²")],
                [{"id": a.id, "name": a.name, "live": a.live} for a in st.areaLoads],
            )
        ],
        notes=[
            f"Saved to {out_path}"
            if out_path
            else "Open a project folder to save occupancy-loads.json."
        ],
    )

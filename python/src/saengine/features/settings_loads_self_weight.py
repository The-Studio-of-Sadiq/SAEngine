"""Project Settings - Loads: Self Weight & Mass tab: densities, inclusion toggles, storey weight, exports."""

from __future__ import annotations

from typing import Any

from saengine.features import (
    FeatureContext,
    checkbox,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.settings_common import (
    export_file,
    json_dumps_clean,
    list_bim_elements,
    list_materials,
    load_settings,
)
from saengine.library.defaults import default_material_library
from saengine.library.settings import seismic_weight_rule
from saengine.report.clauses import in_force


@feature(
    "settingsLoadsSelfWeight.materialDensity",
    "Material Density",
    part="settings",
    fields=[],
    requires_project=False,
)
def material_density(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate mass densities across project materials (or built-in defaults)."""
    mats = list_materials(ctx)
    if not mats:
        mats = [m.model_dump(mode="json") for m in default_material_library().materials]
    rows = [
        {
            "id": m.get("id", "-"),
            "category": m.get("category", "-"),
            "densityKgM3": float((m.get("mechanical") or {}).get("density") or 2400.0),
        }
        for m in mats[:25]
    ]
    return result(
        summary={"materialCount": len(rows)},
        tables=[
            table(
                "Material mass densities",
                [("id", "ID"), ("category", "Category"), ("densityKgM3", "Density", "kg/m³")],
                rows,
            )
        ],
        notes=["Mass density converts to unit weight via γ = ρ × 9.80665 m/s²."],
    )


@feature(
    "settingsLoadsSelfWeight.unitWeight",
    "Unit Weight",
    part="settings",
    fields=[
        number("densityKgM3", "Material mass density ρ", 2400.0, unit="kg/m³", min=100.0),
    ],
    requires_project=False,
)
def unit_weight(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert mass density kg/m³ to structural unit weight kN/m³."""
    uw = values["densityKgM3"] * 9.80665e-3
    return result(
        summary={"densityKgM3": values["densityKgM3"], "unitWeightKnPerM3": uw},
        tables=[
            table(
                "Unit weight conversion",
                [("densityKgM3", "Density", "kg/m³"), ("unitWeightKnM3", "Unit weight", "kN/m³")],
                [{"densityKgM3": values["densityKgM3"], "unitWeightKnM3": uw}],
            )
        ],
        notes=["Standard gravitational acceleration g = 9.80665 m/s²."],
    )


@feature(
    "settingsLoadsSelfWeight.densityOverride",
    "Density Override",
    part="settings",
    fields=[
        text("materialId", "Target material ID", "C30"),
        number("overrideDensityKgM3", "Override mass density", 2450.0, unit="kg/m³", min=500.0),
    ],
    requires_project=False,
)
def density_override(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview a material density override and resulting unit weight change."""
    uw = values["overrideDensityKgM3"] * 9.80665e-3
    return result(
        summary={
            "materialId": values["materialId"],
            "overrideDensityKgM3": values["overrideDensityKgM3"],
            "unitWeightKnPerM3": uw,
        },
        tables=[
            table(
                "Material density override",
                [
                    ("material", "Material"),
                    ("densityKgM3", "Density", "kg/m³"),
                    ("unitWeightKnM3", "γ", "kN/m³"),
                ],
                [
                    {
                        "material": values["materialId"],
                        "densityKgM3": values["overrideDensityKgM3"],
                        "unitWeightKnM3": uw,
                    }
                ],
            )
        ],
        notes=["Heavier reinforced concrete (2450-2500 kg/m³) accounts for embedded rebar mass."],
    )


@feature(
    "settingsLoadsSelfWeight.applyDensity",
    "Apply Density",
    part="settings",
    fields=[
        number(
            "rebarAllowanceKgM3",
            "Embedded rebar mass allowance for RC",
            100.0,
            unit="kg/m³",
            min=0.0,
            max=300.0,
        ),
    ],
    requires_project=False,
)
def apply_density(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate effective reinforced concrete density including embedded steel reinforcement."""
    eff_rho = 2350.0 + values["rebarAllowanceKgM3"]
    return result(
        summary={
            "plainConcreteKgM3": 2350.0,
            "effectiveRcDensityKgM3": eff_rho,
            "unitWeightKnPerM3": eff_rho * 9.80665e-3,
        },
        tables=[
            table(
                "Reinforced concrete effective density",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Effective density [kg/m³]", "value": eff_rho},
                    {"item": "Effective unit weight [kN/m³]", "value": eff_rho * 9.80665e-3},
                ],
            )
        ],
        notes=["Plain concrete + embedded steel reinforcement mass."],
    )


@feature(
    "settingsLoadsSelfWeight.includeMembers",
    "Include Members",
    part="settings",
    fields=[
        checkbox("include", "Include frame member self-weight in D", True),
    ],
    requires_project=False,
)
def include_members(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Count frame members in 06 BIM and toggle automatic self-weight generation."""
    elems, _ = list_bim_elements(ctx)
    frame_n = sum(1 for e in elems if e.get("kind") in ("column", "beam", "brace"))
    return result(
        summary={"includeMembers": values["include"], "frameElementCount": frame_n},
        tables=[
            table(
                "Frame member self-weight",
                [("kind", "Elements"), ("count", "Count"), ("included", "Active")],
                [
                    {
                        "kind": "Columns, beams & braces",
                        "count": frame_n,
                        "included": values["include"],
                    }
                ],
            )
        ],
        notes=["Reads frame elements from 06 BIM/bim.json."],
    )


@feature(
    "settingsLoadsSelfWeight.includeSlabs",
    "Include Slabs",
    part="settings",
    fields=[
        checkbox("include", "Include slab self-weight in D", True),
    ],
    requires_project=False,
)
def include_slabs(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Count slab elements in 06 BIM and toggle automatic slab self-weight."""
    elems, _ = list_bim_elements(ctx)
    slab_n = sum(1 for e in elems if e.get("kind") == "slab")
    return result(
        summary={"includeSlabs": values["include"], "slabCount": slab_n},
        tables=[
            table(
                "Slab self-weight inclusion",
                [("kind", "Elements"), ("count", "Count"), ("included", "Active")],
                [{"kind": "Slabs", "count": slab_n, "included": values["include"]}],
            )
        ],
        notes=["Slab self-weight uses thickness × material unit weight."],
    )


@feature(
    "settingsLoadsSelfWeight.includeFinishes",
    "Include Finishes",
    part="settings",
    fields=[
        checkbox("include", "Include floor finishes & partitions in SD", True),
    ],
    requires_project=False,
)
def include_finishes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect configured floor and roof finish superimposed dead loads."""
    st = load_settings(ctx)
    rows = [
        {"id": a.id, "finishKpa": a.finish, "included": values["include"]} for a in st.areaLoads
    ]
    return result(
        summary={"includeFinishes": values["include"], "areaCount": len(rows)},
        tables=[
            table(
                "Superimposed finish inclusion",
                [("id", "Area ID"), ("finishKpa", "Finish", "kN/m²"), ("included", "Active")],
                rows,
            )
        ],
        notes=["Finishes are assigned to load case SD."],
    )


@feature(
    "settingsLoadsSelfWeight.toggleInclusion",
    "Toggle Inclusion",
    part="settings",
    fields=[],
    requires_project=False,
)
def toggle_inclusion(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise element category self-weight inclusion matrix across the project."""
    elems, _ = list_bim_elements(ctx)
    counts = {}
    for e in elems:
        k = str(e.get("kind", "other"))
        counts[k] = counts.get(k, 0) + 1
    rows = [{"category": k, "count": v, "includedInD": True} for k, v in sorted(counts.items())]
    return result(
        summary={"totalElements": len(elems), "categoryCount": len(rows)},
        tables=[
            table(
                "Element self-weight inclusion",
                [("category", "Element type"), ("count", "Count"), ("includedInD", "In D")],
                rows or [{"category": "all", "count": 0, "includedInD": True}],
            )
        ],
        notes=["All primary structural elements are included in dead load case D by default."],
    )


@feature(
    "settingsLoadsSelfWeight.selfWeightSummary",
    "Self Weight Summary",
    part="settings",
    fields=[],
    requires_project=False,
)
def self_weight_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate project dead self-weight summary across BIM elements."""
    elems, stories = list_bim_elements(ctx)
    by_kind: dict[str, int] = {}
    for e in elems:
        k = str(e.get("kind", "other"))
        by_kind[k] = by_kind.get(k, 0) + 1
    rows = [{"kind": k, "count": v} for k, v in sorted(by_kind.items())]
    return result(
        summary={"bimElements": len(elems), "storeys": len(stories)},
        tables=[
            table(
                "BIM self-weight element breakdown",
                [("kind", "Category"), ("count", "Element count")],
                rows or [{"kind": "(no BIM elements)", "count": 0}],
            )
        ],
        notes=["Counts structural elements present in 06 BIM/bim.json."],
    )


@feature(
    "settingsLoadsSelfWeight.weightByStorey",
    "Weight By Storey",
    part="settings",
    fields=[],
    requires_project=False,
)
def weight_by_storey(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Break down BIM element counts and elevations by project storey."""
    elems, stories = list_bim_elements(ctx)
    counts: dict[str, int] = {}
    for e in elems:
        sid = str(e.get("storyId") or e.get("storey") or "Base")
        counts[sid] = counts.get(sid, 0) + 1
    rows = [
        {
            "storey": s.get("name") or s.get("id", "-"),
            "elevationM": float(s.get("elevation", 0.0)) / 1000.0,
            "elements": counts.get(str(s.get("id", "")), 0),
        }
        for s in stories
    ]
    return result(
        summary={"storeyCount": len(stories), "totalElements": len(elems)},
        tables=[
            table(
                "Storey breakdown",
                [("storey", "Storey"), ("elevationM", "Elevation", "m"), ("elements", "Elements")],
                rows or [{"storey": "L1", "elevationM": 0.0, "elements": len(elems)}],
            )
        ],
        notes=["Grouped by storyId from 06 BIM/bim.json."],
    )


@feature(
    "settingsLoadsSelfWeight.compareEstimate",
    "Compare Estimate",
    part="settings",
    fields=[
        number(
            "preliminaryWeightKn",
            "Preliminary rule-of-thumb building weight",
            18000.0,
            unit="kN",
            min=100.0,
        ),
        number("floorAreaPerStoreyM2", "Typical floor area", 400.0, unit="m²", min=10.0),
        number("storeys", "Number of storeys", 5.0, min=1.0),
        number(
            "unitBuildingWeightKpa", "Estimated dead + SD intensity", 8.5, unit="kN/m²", min=2.0
        ),
    ],
    requires_project=False,
)
def compare_estimate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare preliminary gravity dead weight estimate against area-based building weight."""
    area_wt = values["floorAreaPerStoreyM2"] * values["storeys"] * values["unitBuildingWeightKpa"]
    diff_pct = ((area_wt - values["preliminaryWeightKn"]) / values["preliminaryWeightKn"]) * 100.0
    return result(
        summary={
            "preliminaryKn": values["preliminaryWeightKn"],
            "areaBasedKn": area_wt,
            "differencePct": diff_pct,
        },
        tables=[
            table(
                "Weight estimate comparison",
                [("basis", "Basis"), ("weightKn", "Total dead", "kN")],
                [
                    {"basis": "Preliminary estimate", "weightKn": values["preliminaryWeightKn"]},
                    {"basis": "Area-intensity check", "weightKn": area_wt},
                ],
            )
        ],
        notes=["Sanity check before seismic base shear calculation."],
    )


@feature(
    "settingsLoadsSelfWeight.exportWeight",
    "Export Weight",
    part="settings",
    fields=[
        checkbox("writeJson", "Save weight summary JSON to exports", True),
    ],
    requires_project=False,
)
def export_weight(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export project self-weight and seismic mass settings summary to 02 Project Settings/exports."""
    st = load_settings(ctx)
    elems, stories = list_bim_elements(ctx)
    payload = {
        "project": st.project.name,
        "storeys": len(stories),
        "bimElements": len(elems),
        "areaLoads": [a.model_dump(mode="json") for a in st.areaLoads],
    }
    out_path = None
    if values["writeJson"] and ctx.root is not None:
        out_path = export_file(ctx, "self-weight-summary.json", json_dumps_clean(payload))
    return result(
        summary={"bimElements": len(elems), "exported": out_path is not None},
        tables=[
            table(
                "Exported weight metadata",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Storeys", "value": str(len(stories))},
                    {"field": "Elements", "value": str(len(elems))},
                ],
            )
        ],
        notes=[
            f"Saved to {out_path}"
            if out_path
            else "Open a project folder to save self-weight-summary.json."
        ],
    )


@feature(
    "settingsLoadsSelfWeight.includeWalls",
    "Include Walls",
    part="settings",
    fields=[checkbox("include", "Include wall self-weight", True)],
    requires_project=False,
)
def include_walls(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Toggle structural shear/bearing wall self-weight inclusion."""
    elems, _ = list_bim_elements(ctx)
    n = sum(1 for e in elems if e.get("kind") == "wall")
    return result(
        summary={"includeWalls": values["include"], "wallCount": n},
        tables=[
            table(
                "Wall self-weight",
                [("elements", "Count"), ("included", "Active")],
                [{"elements": n, "included": values["include"]}],
            )
        ],
        notes=["Includes structural RC and masonry walls from 06 BIM."],
    )


@feature(
    "settingsLoadsSelfWeight.includeColumns",
    "Include Columns",
    part="settings",
    fields=[checkbox("include", "Include column self-weight", True)],
    requires_project=False,
)
def include_columns(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Toggle structural column self-weight inclusion."""
    elems, _ = list_bim_elements(ctx)
    n = sum(1 for e in elems if e.get("kind") == "column")
    return result(
        summary={"includeColumns": values["include"], "columnCount": n},
        tables=[
            table(
                "Column self-weight",
                [("elements", "Count"), ("included", "Active")],
                [{"elements": n, "included": values["include"]}],
            )
        ],
        notes=["Includes column axial self-weight from 06 BIM."],
    )


@feature(
    "settingsLoadsSelfWeight.includeBeams",
    "Include Beams",
    part="settings",
    fields=[checkbox("include", "Include beam self-weight", True)],
    requires_project=False,
)
def include_beams(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Toggle structural framing beam self-weight inclusion."""
    elems, _ = list_bim_elements(ctx)
    n = sum(1 for e in elems if e.get("kind") == "beam")
    return result(
        summary={"includeBeams": values["include"], "beamCount": n},
        tables=[
            table(
                "Beam self-weight",
                [("elements", "Count"), ("included", "Active")],
                [{"elements": n, "included": values["include"]}],
            )
        ],
        notes=["Includes beam distributed self-weight from 06 BIM."],
    )


@feature(
    "settingsLoadsSelfWeight.includeFootings",
    "Include Footings",
    part="settings",
    fields=[checkbox("include", "Include footing self-weight in bearing check", True)],
    requires_project=False,
)
def include_footings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Toggle foundation pad/raft self-weight inclusion for substructure bearing checks."""
    sub = ctx.raw("substructure")
    f_cnt = (
        len(sub.get("footings", []))
        if isinstance(sub, dict) and isinstance(sub.get("footings"), list)
        else 0
    )
    return result(
        summary={"includeFootings": values["include"], "footingCount": f_cnt},
        tables=[
            table(
                "Footing self-weight",
                [("footings", "Count"), ("included", "Active")],
                [{"footings": f_cnt, "included": values["include"]}],
            )
        ],
        notes=["Footing concrete weight adds to service soil bearing pressure."],
    )


@feature(
    "settingsLoadsSelfWeight.mepWeight",
    "MEP Weight",
    part="settings",
    fields=[
        number("mepKpa", "Distributed MEP utility dead load", 0.35, unit="kN/m²", min=0.0),
    ],
    requires_project=False,
)
def mep_weight(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Specify continuous floor/ceiling MEP services self-weight allowance."""
    return result(
        summary={"mepAllowanceKpa": values["mepKpa"]},
        tables=[
            table(
                "MEP services allowance",
                [("item", "Item"), ("kpa", "Load", "kN/m²")],
                [{"item": "Suspended ductwork, pipes & cable trays", "kpa": values["mepKpa"]}],
            )
        ],
        notes=["Included in superimposed dead load case SD."],
    )


@feature(
    "settingsLoadsSelfWeight.claddingWeight",
    "Cladding Weight",
    part="settings",
    fields=[
        number(
            "curtainWallKpa", "Facade cladding weight per facade m²", 0.65, unit="kN/m²", min=0.1
        ),
        number("storeyHeightM", "Typical storey height", 3.2, unit="m", min=2.0),
    ],
    requires_project=False,
)
def cladding_weight(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert exterior facade cladding area weight into perimeter edge beam line load."""
    line_kn_m = values["curtainWallKpa"] * values["storeyHeightM"]
    return result(
        summary={"claddingKpa": values["curtainWallKpa"], "perimeterLineLoadKnPerM": line_kn_m},
        tables=[
            table(
                "Facade cladding line load",
                [
                    ("claddingKpa", "Facade", "kN/m²"),
                    ("heightM", "Storey h", "m"),
                    ("lineKnPerM", "Edge beam load", "kN/m"),
                ],
                [
                    {
                        "claddingKpa": values["curtainWallKpa"],
                        "heightM": values["storeyHeightM"],
                        "lineKnPerM": line_kn_m,
                    }
                ],
            )
        ],
        notes=["Applied as uniform line load along exterior perimeter spandrel beams."],
    )


@feature(
    "settingsLoadsSelfWeight.toppingThickness",
    "Topping Thickness",
    part="settings",
    fields=[
        number(
            "toppingMm",
            "Non-structural leveling screed/topping",
            50.0,
            unit="mm",
            min=0.0,
            max=200.0,
        ),
        number("unitWeightKnM3", "Topping unit weight", 22.0, unit="kN/m³", min=15.0),
    ],
    requires_project=False,
)
def topping_thickness(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute non-structural floor leveling screed weight per m²."""
    kpa = (values["toppingMm"] / 1000.0) * values["unitWeightKnM3"]
    return result(
        summary={"toppingMm": values["toppingMm"], "toppingLoadKpa": kpa},
        tables=[
            table(
                "Floor topping dead load",
                [
                    ("thicknessMm", "Thickness", "mm"),
                    ("unitWeightKnM3", "γ", "kN/m³"),
                    ("loadKpa", "SD load", "kN/m²"),
                ],
                [
                    {
                        "thicknessMm": values["toppingMm"],
                        "unitWeightKnM3": values["unitWeightKnM3"],
                        "loadKpa": kpa,
                    }
                ],
            )
        ],
        notes=["Non-structural topping adds dead load without increasing slab effective depth."],
    )


@feature(
    "settingsLoadsSelfWeight.loadMultiplier",
    "Load Multiplier",
    part="settings",
    fields=[
        number(
            "selfWeightFactor", "Global generated self-weight multiplier", 1.0, min=0.0, max=2.0
        ),
    ],
    requires_project=False,
)
def load_multiplier(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set global scale multiplier applied to generated structural self-weight."""
    return result(
        summary={"selfWeightMultiplier": values["selfWeightFactor"]},
        tables=[
            table(
                "Self-weight scale multiplier",
                [("case", "Load case"), ("multiplier", "Multiplier")],
                [{"case": "D (Structural self-weight)", "multiplier": values["selfWeightFactor"]}],
            )
        ],
        notes=["1.05-1.10 accounts for joints, gussets, and splice plates in steel frames."],
    )


@feature(
    "settingsLoadsSelfWeight.deadLoadFactor",
    "Dead Load Factor",
    part="settings",
    fields=[
        number("gammaD", "Upper dead load ULS factor", 1.4, min=0.9, max=2.0),
    ],
    requires_project=False,
)
def dead_load_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect dead load factors across active project load combinations."""
    st = load_settings(ctx)
    d_factors = [c.D for c in st.combinations]
    return result(
        summary={
            "minDeadFactor": min(d_factors) if d_factors else 0.9,
            "maxDeadFactor": max(d_factors) if d_factors else 1.4,
            "targetGammaD": values["gammaD"],
        },
        tables=[
            table(
                "Dead load factors in combinations",
                [("combination", "Combination"), ("D", "Dead factor")],
                [{"combination": c.name, "D": c.D} for c in st.combinations[:12]],
            )
        ],
        notes=["D factor applies equally to structural dead (D) and superimposed dead (SD)."],
    )


@feature(
    "settingsLoadsSelfWeight.massConversion",
    "Mass Conversion",
    part="settings",
    fields=[],
    requires_project=False,
)
def mass_conversion(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report active seismic mass source composition (dead + live share + partition rule)."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        rule = seismic_weight_rule(st)
    rows = [
        {"component": "Dead & Superimposed Dead (D + SD)", "share": 1.0},
        {"component": "Floor Live Load (standard)", "share": rule.live(2.0)},
        {"component": "Heavy Live Load (> threshold)", "share": rule.live(6.0)},
        {"component": "Partition allowance", "share": rule.partitions.share()},
    ]
    return result(
        summary={
            "standardLiveShare": rule.live(2.0),
            "heavyLiveShare": rule.live(6.0),
            "partitionMode": rule.partitions.mode,
        },
        tables=[
            table(
                "Seismic mass source weights",
                [("component", "Load component"), ("share", "Mass share")],
                rows,
            )
        ],
        notes=[f"Partition rule: {rule.partitions.words()}."],
    )


@feature(
    "settingsLoadsSelfWeight.gravityMultiplier",
    "Gravity Multiplier",
    part="settings",
    fields=[
        number("gMPerS2", "Gravitational acceleration g", 9.80665, unit="m/s²", min=9.75, max=9.85),
    ],
    requires_project=False,
)
def gravity_multiplier(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute gravity-to-mass conversion factor 1 / g for dynamic modal analysis."""
    g = values["gMPerS2"]
    return result(
        summary={"gravityMPerS2": g, "massFactorKgPerN": 1.0 / g},
        tables=[
            table(
                "Gravitational constant",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Gravity g [m/s²]", "value": g},
                    {"item": "Mass per kN [t / kN]", "value": 1.0 / g},
                ],
            )
        ],
        notes=["Standard international gravity g = 9.80665 m/s²."],
    )

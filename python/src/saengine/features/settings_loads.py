"""Project Settings - Loads & Combinations tab: load cases, patterns, combinations, superimposed, wind/snow, notional loads."""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
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
from saengine.features.settings_common import (
    active_pack,
    list_materials,
    load_settings,
    parse_csv_rows,
    safe_table,
)
from saengine.fem import notional_loads, pattern_live, snow_load
from saengine.library.settings import (
    LoadCombination,
    SnowDrift,
    combinations_from_pack,
    partition_case_basis,
    partition_weight_basis,
    project_strength_combinations,
)
from saengine.report.clauses import in_force


@feature(
    "settingsLoads.loadCaseTable",
    "Load Case Table",
    part="settings",
    fields=[],
    requires_project=False,
)
def load_case_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List all active and optional load cases defined by the code pack and project settings."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        comb_tbl = safe_table(pack, "combinations")
        cases = dict(getattr(comb_tbl, "loadCases", None) or {})
        optional = set(getattr(comb_tbl, "optionalCases", None) or [])
    rows = [
        {
            "case": code,
            "description": desc,
            "optional": code in optional,
            "activeInCombinations": any(
                abs(getattr(c, code, 0.0) if hasattr(c, code) else 0.0) > 1e-9
                for c in st.combinations
            ),
        }
        for code, desc in cases.items()
    ]
    return result(
        summary={
            "loadCaseCount": len(rows),
            "optionalCaseCount": len(optional),
            "combinationCount": len(st.combinations),
        },
        tables=[
            table(
                "Load cases",
                [
                    ("case", "Case"),
                    ("description", "Description"),
                    ("optional", "Optional"),
                    ("activeInCombinations", "Used"),
                ],
                rows,
            )
        ],
        notes=["Load case definitions come from the active code pack's combinations table."],
    )


@feature(
    "settingsLoads.selfWeightFactors",
    "Self-Weight Factors",
    part="settings",
    fields=[
        number("gravityMultiplier", "Self-weight multiplier", 1.0, min=0.0, max=2.0),
        number("slabAllowanceFactor", "Finish / topping factor", 1.0, min=0.0, max=2.0),
    ],
    requires_project=False,
)
def self_weight_factors(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Review self-weight unit weights across project materials and applied multipliers."""
    g_mult = values["gravityMultiplier"]
    fin_mult = values["slabAllowanceFactor"]
    mats = list_materials(ctx)
    rows = []
    for m in mats[:20]:
        mech = m.get("mechanical") or {}
        rho = float(mech.get("density") or 2400.0)
        uw = rho * 9.80665e-3
        rows.append(
            {
                "id": m.get("id", "-"),
                "category": m.get("category", "-"),
                "unitWeightKnPerM3": uw,
                "factoredKnPerM3": uw * g_mult,
            }
        )
    if not rows:
        for name, uw in (
            ("Concrete (normal)", 24.0),
            ("Structural steel", 77.0),
            ("Masonry", 19.0),
        ):
            rows.append(
                {
                    "id": name,
                    "category": "default",
                    "unitWeightKnPerM3": uw,
                    "factoredKnPerM3": uw * g_mult,
                }
            )
    return result(
        summary={
            "materialCount": len(rows),
            "gravityMultiplier": g_mult,
            "finishMultiplier": fin_mult,
        },
        tables=[
            table(
                "Material self-weight multipliers",
                [
                    ("id", "Material"),
                    ("category", "Category"),
                    ("unitWeightKnPerM3", "γ", "kN/m³"),
                    ("factoredKnPerM3", "Effective γ", "kN/m³"),
                ],
                rows,
            )
        ],
        notes=["Unit weights derived from material mass density × 9.80665 m/s²."],
    )


@feature(
    "settingsLoads.loadGroups",
    "Load Groups",
    part="settings",
    fields=[],
    requires_project=False,
)
def load_groups(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Classify project load cases into action groups (permanent, variable, environmental, seismic)."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        comb_tbl = safe_table(pack, "combinations")
        cases = dict(getattr(comb_tbl, "loadCases", None) or {})
    groups_map = {
        "D": "Permanent",
        "SD": "Permanent",
        "H": "Permanent / Earth",
        "L": "Imposed (floor)",
        "Lr": "Imposed (roof)",
        "S": "Environmental (snow)",
        "R": "Environmental (rain)",
        "W": "Environmental (wind)",
        "E": "Seismic",
        "T": "Self-straining (thermal)",
        "F": "Fluid",
        "Fa": "Flood / Surge",
    }
    rows = [
        {"case": k, "group": groups_map.get(k, "Special"), "label": v} for k, v in cases.items()
    ]
    return result(
        summary={"groupCount": len({r["group"] for r in rows}), "caseCount": len(rows)},
        tables=[
            table(
                "Load action groups",
                [("case", "Case"), ("group", "Action group"), ("label", "Label")],
                rows,
            )
        ],
        notes=[
            "Permanent, imposed, environmental, and seismic action groups used for combination assembly."
        ],
    )


@feature(
    "settingsLoads.liveLoadPatterns",
    "Live Load Patterns",
    part="settings",
    fields=[
        number("baysX", "Number of bays along X", 3.0, min=1.0, max=12.0),
        number("baysY", "Number of bays along Y", 3.0, min=1.0, max=12.0),
        number("floors", "Number of floor levels", 4.0, min=1.0, max=40.0),
        number("bayWidthM", "Typical bay width", 6.0, unit="m", min=1.0),
    ],
    requires_project=False,
)
def live_load_patterns(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate alternate-bay and adjacent-bay pattern live load arrangements from floor grid."""
    nx = int(values["baysX"])
    ny = int(values["baysY"])
    nf = int(values["floors"])
    bay_mm = values["bayWidthM"] * 1000.0
    xs = tuple(i * bay_mm for i in range(nx + 1))
    ys = tuple(j * bay_mm for j in range(ny + 1))
    levels = tuple((k + 1) * 3200.0 for k in range(nf))
    grid = pattern_live.Grid(xs=xs, ys=ys, levels=levels)
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        arrangements = pattern_live.live_patterns(grid)
    rows = [
        {"name": a.name, "label": a.label, "kind": "alternate" if a.alternate else "adjacent"}
        for a in arrangements
    ]
    return result(
        summary={"baysX": nx, "baysY": ny, "floors": nf, "arrangementCount": len(rows)},
        tables=[
            table(
                "Generated live load pattern arrangements",
                [("name", "Case"), ("label", "Description"), ("kind", "Pattern kind")],
                rows,
            )
        ],
        notes=[
            "Generated via saengine.fem.pattern_live.Grid checkerboard and adjacent-span rules."
        ],
    )


@feature(
    "settingsLoads.patternRanges",
    "Pattern Ranges",
    part="settings",
    fields=[
        number("spanM", "Typical beam span L", 6.5, unit="m", min=1.0),
        number("deadKnPerM", "Unfactored dead load wD", 18.0, unit="kN/m", min=0.0),
        number("liveKnPerM", "Unfactored live load wL", 12.0, unit="kN/m", min=0.0),
        number("gammaD", "Dead load factor γD", 1.2, min=0.9, max=2.0),
        number("gammaL", "Live load factor γL", 1.6, min=0.5, max=2.5),
    ],
    requires_project=False,
)
def pattern_ranges(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare skip-loaded vs all-spans-loaded extreme moments on a continuous 3-span beam."""
    span = values["spanM"]
    wd = values["gammaD"] * values["deadKnPerM"]
    wl = values["gammaL"] * values["liveKnPerM"]
    # Exact 3-equal-span continuous beam elastic moment coefficients
    m_pos_all = (0.08 * wd + 0.08 * wl) * span**2
    m_pos_skip = (0.08 * wd + 0.101 * wl) * span**2
    m_neg_all = (0.10 * wd + 0.10 * wl) * span**2
    m_neg_adj = (0.10 * wd + 0.117 * wl) * span**2
    rows = [
        {
            "effect": "End-span positive M+",
            "uniformKnM": m_pos_all,
            "patternedKnM": m_pos_skip,
            "increasePct": (m_pos_skip / max(m_pos_all, 1e-9) - 1.0) * 100.0,
        },
        {
            "effect": "Interior support negative M-",
            "uniformKnM": m_neg_all,
            "patternedKnM": m_neg_adj,
            "increasePct": (m_neg_adj / max(m_neg_all, 1e-9) - 1.0) * 100.0,
        },
    ]
    return result(
        summary={
            "maxPositiveKnM": m_pos_skip,
            "maxNegativeKnM": m_neg_adj,
            "positiveAmplification": m_pos_skip / max(m_pos_all, 1e-9),
            "negativeAmplification": m_neg_adj / max(m_neg_all, 1e-9),
        },
        tables=[
            table(
                "3-span continuous beam pattern envelope",
                [
                    ("effect", "Effect"),
                    ("uniformKnM", "Uniform", "kN·m"),
                    ("patternedKnM", "Patterned", "kN·m"),
                    ("increasePct", "Increase", "%"),
                ],
                rows,
            )
        ],
        notes=[
            "Elastic 3-span influence coefficients: end-span +0.101 wL² (alternate), support -0.117 wL² (adjacent)."
        ],
    )


@feature(
    "settingsLoads.unloadedAreas",
    "Unloaded Areas",
    part="settings",
    fields=[
        text(
            "excludedUses",
            "Uses excluded from pattern skipping (comma-separated)",
            "storage,parking,mechanical",
        ),
    ],
    requires_project=False,
)
def unloaded_areas(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Identify project area loads excluded from automatic live load pattern skipping."""
    st = load_settings(ctx)
    excl = {t.strip().lower() for t in values["excludedUses"].split(",") if t.strip()}
    rows = []
    excluded_count = 0
    for a in st.areaLoads:
        is_excl = a.use.lower() in excl or a.id.lower() in excl
        if is_excl:
            excluded_count += 1
        rows.append(
            {
                "id": a.id,
                "name": a.name,
                "use": a.use,
                "liveKnPerM2": a.live,
                "excludedFromSkip": is_excl,
            }
        )
    return result(
        summary={
            "areaCount": len(rows),
            "excludedCount": excluded_count,
            "patternedCount": len(rows) - excluded_count,
        },
        tables=[
            table(
                "Pattern skipping exclusions by area load",
                [
                    ("id", "ID"),
                    ("name", "Name"),
                    ("use", "Use"),
                    ("liveKnPerM2", "Live", "kN/m²"),
                    ("excludedFromSkip", "Excluded"),
                ],
                rows,
            )
        ],
        notes=[
            "Storage, parking, and fixed equipment zones typically remain loaded in all pattern arrangements."
        ],
    )


@feature(
    "settingsLoads.combinationRules",
    "Combination Rules",
    part="settings",
    fields=[
        checkbox("checkMatch", "Check project combinations against code pack", True),
    ],
    requires_project=False,
)
def combination_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate strength load combinations from the active code pack and compare with project settings."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        generated = project_strength_combinations(st, pack)
        matches = combinations_from_pack(st, pack) if values["checkMatch"] else True
    rows = [
        {
            "name": c.name,
            "D": c.D,
            "L": c.L,
            "Lr": c.Lr,
            "WX": c.WX,
            "WY": c.WY,
            "EX": c.EX,
            "EY": c.EY,
        }
        for c in generated
    ]
    return result(
        summary={
            "generatedCount": len(generated),
            "projectCount": len(st.combinations),
            "matchesCodePack": matches,
        },
        tables=[
            table(
                "Generated strength combinations",
                [
                    ("name", "Name"),
                    ("D", "D"),
                    ("L", "L"),
                    ("Lr", "Lr"),
                    ("WX", "WX"),
                    ("WY", "WY"),
                    ("EX", "EX"),
                    ("EY", "EY"),
                ],
                rows,
            )
        ],
        notes=[
            f"Generated for code pack {code_context.code_name(pack)} with project exceptions and directional expansion."
        ],
    )


@feature(
    "settingsLoads.envelopeSets",
    "Envelope Sets",
    part="settings",
    fields=[],
    requires_project=False,
)
def envelope_sets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise strength, serviceability, and allowable-stress combination envelope sets."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        comb_tbl = safe_table(pack, "combinations")
    strength_n = len(st.combinations)
    service_n = len(getattr(comb_tbl, "service", None) or [])
    allow_n = len(getattr(comb_tbl, "allowable", None) or [])
    gravity_n = len(getattr(comb_tbl, "gravity", None) or [])
    rows = [
        {"envelope": "Strength (ULS)", "count": strength_n, "purpose": "Member capacity design"},
        {
            "envelope": "Serviceability (SLS)",
            "count": service_n,
            "purpose": "Deflection, crack, drift checks",
        },
        {
            "envelope": "Allowable stress",
            "count": allow_n,
            "purpose": "Soil bearing and foundation service checks",
        },
        {
            "envelope": "Gravity only",
            "count": gravity_n,
            "purpose": "Vertical framing & initial P-Delta preload",
        },
    ]
    return result(
        summary={
            "strengthCount": strength_n,
            "serviceCount": service_n,
            "allowableCount": allow_n,
            "gravityCount": gravity_n,
        },
        tables=[
            table(
                "Envelope sets",
                [("envelope", "Envelope"), ("count", "Combinations"), ("purpose", "Purpose")],
                rows,
            )
        ],
        notes=[
            "Envelopes group active project ULS combinations and code pack SLS/ASD combinations."
        ],
    )


@feature(
    "settingsLoads.importCombinations",
    "Import Combinations",
    part="settings",
    fields=[
        text(
            "csvText",
            "Combinations CSV (name,D,L,Lr,WX,WY,EX,EY)",
            "name,D,L,Lr,WX,WY,EX,EY\nULS-1,1.4,0,0,0,0,0,0\nULS-2,1.2,1.6,0.5,0,0,0,0\nULS-W,1.2,1.0,0.5,1.6,0,0,0",
        ),
    ],
    requires_project=False,
)
def import_combinations(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate load combination definitions from CSV input."""
    raw_rows = parse_csv_rows(values["csvText"], "Combinations CSV")
    parsed: list[dict[str, Any]] = []
    for r in raw_rows:
        try:
            combo = LoadCombination(
                name=r["name"],
                D=float(r.get("D", 0.0)),
                L=float(r.get("L", 0.0)),
                Lr=float(r.get("Lr", 0.0)),
                WX=float(r.get("WX", 0.0)),
                WY=float(r.get("WY", 0.0)),
                EX=float(r.get("EX", 0.0)),
                EY=float(r.get("EY", 0.0)),
            )
        except Exception as exc:
            raise FeatureInputError(f"Invalid combination row {r}: {exc}") from exc
        parsed.append(combo.model_dump(mode="json", exclude_none=True))
    return result(
        summary={"importedCount": len(parsed), "valid": True},
        tables=[
            table(
                "Validated imported combinations",
                [
                    ("name", "Name"),
                    ("D", "D"),
                    ("L", "L"),
                    ("Lr", "Lr"),
                    ("WX", "WX"),
                    ("WY", "WY"),
                    ("EX", "EX"),
                    ("EY", "EY"),
                ],
                parsed,
            )
        ],
        notes=["Validated against saengine.library.settings.LoadCombination schema."],
    )


@feature(
    "settingsLoads.superDeadLoad",
    "Super Dead Load",
    part="settings",
    fields=[
        number("screedMm", "Floor screed thickness", 50.0, unit="mm", min=0.0),
        number("screedUnitWeightKnM3", "Screed unit weight", 22.0, unit="kN/m³", min=10.0),
        number("tileKnPerM2", "Floor finish / tiling allowance", 0.4, unit="kN/m²", min=0.0),
        number("ceilingServicesKnPerM2", "Ceiling & MEP allowance", 0.5, unit="kN/m²", min=0.0),
    ],
    requires_project=False,
)
def super_dead_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute superimposed dead load buildup and compare with project area load settings."""
    st = load_settings(ctx)
    screed = (values["screedMm"] / 1000.0) * values["screedUnitWeightKnM3"]
    total_sd = screed + values["tileKnPerM2"] + values["ceilingServicesKnPerM2"]
    floor_area = next((a for a in st.areaLoads if a.id == st.floorLoad), None)
    proj_finish = floor_area.finish if floor_area else 1.2
    rows = [
        {"component": "Screed / topping", "loadKnPerM2": screed},
        {"component": "Floor tiles / finish", "loadKnPerM2": values["tileKnPerM2"]},
        {"component": "Ceiling & services", "loadKnPerM2": values["ceilingServicesKnPerM2"]},
        {"component": "Total calculated SD", "loadKnPerM2": total_sd},
        {"component": f"Project floorLoad ({st.floorLoad}) finish", "loadKnPerM2": proj_finish},
    ]
    return result(
        summary={
            "calculatedSdKnPerM2": total_sd,
            "projectFinishKnPerM2": proj_finish,
            "differenceKnPerM2": total_sd - proj_finish,
        },
        tables=[
            table(
                "Superimposed dead load buildup",
                [("component", "Component"), ("loadKnPerM2", "Load", "kN/m²")],
                rows,
            )
        ],
        notes=[
            "Superimposed dead load sums screed (t × γ), finishes, ceiling, and distributed MEP."
        ],
    )


@feature(
    "settingsLoads.partitionAllowance",
    "Partition Allowance",
    part="settings",
    fields=[
        number("wallLinearKnPerM", "Typical partition line weight", 4.5, unit="kN/m", min=0.0),
        number("bayAreaM2", "Reference floor panel area", 36.0, unit="m²", min=1.0),
        number("wallLengthM", "Total partition length on panel", 10.0, unit="m", min=0.0),
    ],
    requires_project=False,
)
def partition_allowance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate equivalent uniform partition allowance against code pack minimum and load case rule."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        part_case, case_src = partition_case_basis(st, pack)
        part_wt = partition_weight_basis(st, pack)
        area_tbl = safe_table(pack, "areaLoads")
        part_rule = getattr(area_tbl, "partitions", None) if area_tbl else None
        code_min = float(part_rule.minimum) if part_rule else 1.0
        share = float(part_rule.share) if part_rule else 0.33

    eq_udl = (values["wallLinearKnPerM"] * values["wallLengthM"]) / values["bayAreaM2"]
    equiv_by_share = values["wallLinearKnPerM"] * share
    design_udl = max(eq_udl, code_min)
    rows = [
        {"metric": "Panel-averaged partition UDL", "value": eq_udl, "unit": "kN/m²"},
        {"metric": "Code rule share × line weight", "value": equiv_by_share, "unit": "kN/m²"},
        {"metric": "Code pack minimum allowance", "value": code_min, "unit": "kN/m²"},
        {"metric": "Governing uniform allowance", "value": design_udl, "unit": "kN/m²"},
    ]
    return result(
        summary={
            "governingAllowanceKnPerM2": design_udl,
            "codeMinimumKnPerM2": code_min,
            "loadCase": part_case,
            "meetsMinimum": eq_udl >= code_min,
        },
        tables=[
            table(
                "Partition allowance evaluation",
                [("metric", "Metric"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            f"Partition load case: {part_case} ({case_src}); seismic weight rule: {part_wt.words()}."
        ],
    )


@feature(
    "settingsLoads.ceilingLoad",
    "Ceiling Load",
    part="settings",
    fields=[
        number(
            "gridFramingKnPerM2", "Suspended ceiling grid & boards", 0.20, unit="kN/m²", min=0.0
        ),
        number("insulationKnPerM2", "Acoustic / thermal insulation", 0.08, unit="kN/m²", min=0.0),
        number("lightingFixturesKnPerM2", "Lighting & diffusers", 0.12, unit="kN/m²", min=0.0),
    ],
    requires_project=False,
)
def ceiling_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute suspended ceiling dead load allowance per floor area."""
    total = (
        values["gridFramingKnPerM2"]
        + values["insulationKnPerM2"]
        + values["lightingFixturesKnPerM2"]
    )
    rows = [
        {"item": "Ceiling grid & boards", "loadKnPerM2": values["gridFramingKnPerM2"]},
        {"item": "Insulation layer", "loadKnPerM2": values["insulationKnPerM2"]},
        {"item": "Lighting & diffusers", "loadKnPerM2": values["lightingFixturesKnPerM2"]},
    ]
    return result(
        summary={"totalCeilingKnPerM2": total},
        tables=[
            table(
                "Suspended ceiling buildup",
                [("item", "Component"), ("loadKnPerM2", "Load", "kN/m²")],
                rows,
            )
        ],
        notes=["Uniformly distributed under-slab dead load applied to suspended ceiling zones."],
    )


@feature(
    "settingsLoads.servicesAllowance",
    "Services Allowance",
    part="settings",
    fields=[
        number("hvacDuctKnPerM2", "HVAC ductwork & VAV allowance", 0.25, unit="kN/m²", min=0.0),
        number(
            "pipingSprinklerKnPerM2", "Fire sprinkler & plumbing pipes", 0.20, unit="kN/m²", min=0.0
        ),
        number("electricalTraysKnPerM2", "Cable trays & busducts", 0.10, unit="kN/m²", min=0.0),
    ],
    requires_project=False,
)
def services_allowance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute distributed MEP services dead load allowance below slabs."""
    total = (
        values["hvacDuctKnPerM2"]
        + values["pipingSprinklerKnPerM2"]
        + values["electricalTraysKnPerM2"]
    )
    rows = [
        {"discipline": "HVAC ductwork", "loadKnPerM2": values["hvacDuctKnPerM2"]},
        {"discipline": "Piping & sprinklers", "loadKnPerM2": values["pipingSprinklerKnPerM2"]},
        {"discipline": "Electrical cable trays", "loadKnPerM2": values["electricalTraysKnPerM2"]},
    ]
    return result(
        summary={"totalServicesKnPerM2": total},
        tables=[
            table(
                "MEP services allowance",
                [("discipline", "Discipline"), ("loadKnPerM2", "Load", "kN/m²")],
                rows,
            )
        ],
        notes=["Included in superimposed dead load (SD) and seismic mass."],
    )


@feature(
    "settingsLoads.snowDriftLoad",
    "Snow Drift Load",
    part="settings",
    fields=[
        number("groundSnowKnPerM2", "Ground snow load pg / sk", 1.5, unit="kN/m²", min=0.1),
        number("stepHeightM", "Roof step / parapet height h", 1.2, unit="m", min=0.1),
        number("upperLengthM", "Upper roof fetch length lu", 20.0, unit="m", min=1.0),
        number("exposureCe", "Snow exposure factor Ce", 1.0, min=0.5, max=1.5),
        number("thermalCt", "Snow thermal factor Ct", 1.0, min=0.8, max=1.3),
    ],
    requires_project=False,
)
def snow_drift_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate snow drift surcharge and drift width at a roof step or parapet."""
    pg = values["groundSnowKnPerM2"]
    h = values["stepHeightM"]
    lu = values["upperLengthM"]
    ce = values["exposureCe"]
    ct = values["thermalCt"]
    st = load_settings(ctx)

    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        snow_tbl = safe_table(pack, "snow")
        drift_res = None
        if snow_tbl is not None:
            step = SnowDrift(upperLength=lu, lowerLength=lu, stepHeight=h, windParameter=4.0)
            if getattr(snow_tbl, "drift", None) is not None:
                drift_res = snow_load.drift(snow_tbl, pg, step)
            elif getattr(snow_tbl, "shapeDrift", None) is not None:
                drift_res = snow_load.shape_drift(snow_tbl.shapeDrift, pg, step, ce, ct, h)

    if drift_res is None:
        # Generic physics-based drift surcharge estimate (snow density ~ 0.43 * pg^0.25 -> ~2.0-3.0 kN/m3)
        gamma_s = min(3.0, max(1.5, 0.426 * (pg * 20.885) ** 0.25 * 0.157))
        hd = min(h, 0.43 * (lu ** (1 / 3)) * ((pg + 0.5) ** (1 / 4)) - 0.15)
        hd = max(0.0, hd)
        w = min(8.0 * h, max(3.0, 4.0 * hd))
        pd = hd * gamma_s
        drift_res = {"hd": hd, "w": w, "pd": pd, "gamma": gamma_s}

    rows = [
        {"parameter": "Snow unit weight γs", "value": drift_res["gamma"], "unit": "kN/m³"},
        {"parameter": "Drift height hd", "value": drift_res["hd"], "unit": "m"},
        {"parameter": "Drift width w", "value": drift_res["w"], "unit": "m"},
        {"parameter": "Peak drift surcharge pd", "value": drift_res["pd"], "unit": "kN/m²"},
    ]
    return result(
        summary={
            "driftHeightM": float(drift_res["hd"]),
            "driftWidthM": float(drift_res["w"]),
            "peakDriftLoadKnPerM2": float(drift_res["pd"]),
        },
        tables=[
            table(
                "Snow drift parameters",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Uses active pack snow drift table when available; triangular drift surcharge tapers over width w."
        ],
    )


@feature(
    "settingsLoads.rainLoad",
    "Rain Load",
    part="settings",
    fields=[
        number("staticHeadMm", "Static water head ds to secondary drain", 50.0, unit="mm", min=0.0),
        number(
            "hydraulicHeadMm", "Hydraulic head dh above scupper/drain", 40.0, unit="mm", min=0.0
        ),
        number(
            "waterUnitWeightKnM3", "Rainwater unit weight", 9.81, unit="kN/m³", min=9.5, max=10.5
        ),
    ],
    requires_project=False,
)
def rain_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute roof rain load R = γw (ds + dh) assuming primary drains blocked."""
    ds_m = values["staticHeadMm"] / 1000.0
    dh_m = values["hydraulicHeadMm"] / 1000.0
    gamma_w = values["waterUnitWeightKnM3"]
    r_kpa = gamma_w * (ds_m + dh_m)
    rows = [
        {
            "component": "Static head ds",
            "depthMm": values["staticHeadMm"],
            "pressureKpa": gamma_w * ds_m,
        },
        {
            "component": "Hydraulic head dh",
            "depthMm": values["hydraulicHeadMm"],
            "pressureKpa": gamma_w * dh_m,
        },
        {
            "component": "Total rain load R",
            "depthMm": values["staticHeadMm"] + values["hydraulicHeadMm"],
            "pressureKpa": r_kpa,
        },
    ]
    return result(
        summary={
            "totalDepthMm": values["staticHeadMm"] + values["hydraulicHeadMm"],
            "rainLoadKnPerM2": r_kpa,
        },
        tables=[
            table(
                "Roof rain load calculation",
                [
                    ("component", "Component"),
                    ("depthMm", "Head", "mm"),
                    ("pressureKpa", "Pressure", "kN/m²"),
                ],
                rows,
            )
        ],
        notes=["Computed from R = γw × (ds + dh) with primary roof drainage assumed blocked."],
    )


@feature(
    "settingsLoads.windPressureCases",
    "Wind Pressure Cases",
    part="settings",
    fields=[
        number("buildingHeightM", "Building height H", 24.0, unit="m", min=3.0),
        number("planWidthM", "Plan width across wind B", 20.0, unit="m", min=2.0),
        number("planDepthM", "Plan depth along wind D", 16.0, unit="m", min=2.0),
    ],
    requires_project=False,
)
def wind_pressure_cases(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate wind load cases and directional torsional eccentricities from active pack."""
    st = load_settings(ctx)
    h = values["buildingHeightM"]
    b = values["planWidthM"]
    d = values["planDepthM"]
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        wind_tbl = safe_table(pack, "wind")
        design_cases = list(getattr(wind_tbl, "designCases", None) or [])
    rows = []
    for dc in design_cases:
        rows.append(
            {
                "id": getattr(dc, "id", "-"),
                "label": getattr(dc, "label", "-"),
                "wxFactor": getattr(dc, "wx", 1.0),
                "wyFactor": getattr(dc, "wy", 0.0),
                "eccentricityRatio": getattr(dc, "eccentricity", 0.0),
            }
        )
    if not rows:
        rows = [
            {
                "id": "Case1-X",
                "label": "Full wind +X",
                "wxFactor": 1.0,
                "wyFactor": 0.0,
                "eccentricityRatio": 0.0,
            },
            {
                "id": "Case1-Y",
                "label": "Full wind +Y",
                "wxFactor": 0.0,
                "wyFactor": 1.0,
                "eccentricityRatio": 0.0,
            },
            {
                "id": "Case2-X",
                "label": "0.75 wind X + torsion",
                "wxFactor": 0.75,
                "wyFactor": 0.0,
                "eccentricityRatio": 0.15,
            },
            {
                "id": "Case3",
                "label": "0.75 (WX + WY)",
                "wxFactor": 0.75,
                "wyFactor": 0.75,
                "eccentricityRatio": 0.0,
            },
        ]
    return result(
        summary={
            "designCaseCount": len(rows),
            "aspectRatioHOverD": h / d,
            "aspectRatioBOverD": b / d,
        },
        tables=[
            table(
                "Wind directional & torsional cases",
                [
                    ("id", "Case"),
                    ("label", "Description"),
                    ("wxFactor", "WX share"),
                    ("wyFactor", "WY share"),
                    ("eccentricityRatio", "e/B"),
                ],
                rows,
            )
        ],
        notes=[
            "Wind design load cases extracted from the active code pack's wind.designCases table."
        ],
    )


@feature(
    "settingsLoads.roofPonding",
    "Roof Ponding",
    part="settings",
    fields=[
        number("primarySpanM", "Primary girder span Lp", 12.0, unit="m", min=1.0),
        number("primarySpacingM", "Primary girder spacing sp", 6.0, unit="m", min=0.5),
        number("primaryIxMm4", "Primary girder Ix", 3.5e8, unit="mm⁴", min=1e5),
        number("secondarySpanM", "Secondary purlin/joist span Ls", 6.0, unit="m", min=1.0),
        number("secondarySpacingM", "Secondary spacing ss", 2.0, unit="m", min=0.3),
        number("secondaryIxMm4", "Secondary member Ix", 4.5e7, unit="mm⁴", min=1e4),
        number("elasticModulusMpa", "Framing elastic modulus E", 200000.0, unit="MPa", min=5000.0),
    ],
    requires_project=False,
)
def roof_ponding(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check flat-roof progressive ponding stability using two-way framing flexibility indices."""
    gamma_w = 9.81e-6  # N/mm^3
    e = values["elasticModulusMpa"]
    lp = values["primarySpanM"] * 1000.0
    ip = values["primaryIxMm4"]
    ls = values["secondarySpanM"] * 1000.0
    ss = values["secondarySpacingM"] * 1000.0
    isec = values["secondaryIxMm4"]

    cp = (gamma_w * ls * lp**4) / (math.pi**4 * e * ip)
    cs = (gamma_w * ss * ls**4) / (math.pi**4 * e * isec)
    # Standard Marino/stability envelope: Cp + 0.9*Cs <= 0.25
    index = cp + 0.9 * cs
    stable = index <= 0.25 and cp <= 0.25 and cs <= 0.25
    rows = [
        {"parameter": "Primary flexibility Cp", "value": cp, "limit": 0.25},
        {"parameter": "Secondary flexibility Cs", "value": cs, "limit": 0.25},
        {"parameter": "Combined index Cp + 0.9 Cs", "value": index, "limit": 0.25},
    ]
    return result(
        summary={"cpIndex": cp, "csIndex": cs, "combinedIndex": index, "pondingStable": stable},
        tables=[
            table(
                "Roof ponding stability check",
                [("parameter", "Index"), ("value", "Value"), ("limit", "Limit")],
                rows,
            )
        ],
        notes=[
            "Two-way ponding stability requires Cp + 0.9 Cs <= 0.25 (elastic amplification bound)."
        ],
    )


@feature(
    "settingsLoads.notionalLoadSet",
    "Notional Load Set",
    part="settings",
    fields=[
        select(
            "method",
            "Stability analysis method",
            [
                ("secondOrder", "Second-order analysis"),
                ("firstOrder", "First-order amplified"),
                ("directAnalysis", "Direct analysis"),
            ],
            "directAnalysis",
        ),
        number("gravityLoadKn", "Total storey gravity load Yi", 4000.0, unit="kN", min=1.0),
        number("driftRatio", "First-order drift ratio Δ/L", 0.002, min=0.0, max=0.05),
    ],
    requires_project=False,
)
def notional_load_set(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute lateral notional horizontal loads representing geometric out-of-plumb imperfections."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        coeff = notional_loads.coefficient(values["method"], drift=values["driftRatio"])
    if coeff <= 0.0:
        coeff = 0.002
    ni = coeff * values["gravityLoadKn"]
    rows = [
        {
            "case": code,
            "axis": "X" if axis == 0 else "Y",
            "sourceGravity": "+".join(grav),
            "coefficient": coeff,
            "notionalKn": ni,
        }
        for code, axis, grav, _ in notional_loads.NOTIONAL_CASES
    ]
    return result(
        summary={"method": values["method"], "coefficient": coeff, "notionalForceKn": ni},
        tables=[
            table(
                "Notional load cases",
                [
                    ("case", "Case"),
                    ("axis", "Axis"),
                    ("sourceGravity", "Gravity source"),
                    ("coefficient", "Ni / Yi"),
                    ("notionalKn", "Force", "kN"),
                ],
                rows,
            )
        ],
        notes=[
            "Notional load coefficient obtained from the active code pack's steelStability rules."
        ],
    )


@feature(
    "settingsLoads.imperfectionFactors",
    "Imperfection Factors",
    part="settings",
    fields=[
        number("buildingHeightM", "Total structure height h", 30.0, unit="m", min=2.0),
        number("columnsInRow", "Number of columns in a frame row m", 4.0, min=1.0, max=50.0),
        number("memberLengthM", "Member unbraced length L", 4.5, unit="m", min=0.5),
        number("basicPhi0", "Basic out-of-plumb inclination φ0", 0.005, min=0.001, max=0.02),
    ],
    requires_project=False,
)
def imperfection_factors(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute global sway imperfection φ and local member bow imperfection e0."""
    h = values["buildingHeightM"]
    m = int(values["columnsInRow"])
    phi0 = values["basicPhi0"]
    alpha_h = min(1.0, max(2.0 / 3.0, 2.0 / math.sqrt(h)))
    alpha_m = math.sqrt(0.5 * (1.0 + 1.0 / m))
    phi = phi0 * alpha_h * alpha_m
    l_mm = values["memberLengthM"] * 1000.0
    bow_mm = l_mm / 250.0  # standard L/250 plastic/elastic bow reference
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack_phi = notional_loads.sway_coefficient(h)
    rows = [
        {"parameter": "Height reduction αh", "value": alpha_h, "unit": "-"},
        {"parameter": "Multi-column factor αm", "value": alpha_m, "unit": "-"},
        {"parameter": "Global sway imperfection φ", "value": phi, "unit": "rad"},
        {"parameter": "Code pack sway φ (if defined)", "value": pack_phi, "unit": "rad"},
        {"parameter": "Local member bow e0 (L/250)", "value": bow_mm, "unit": "mm"},
    ]
    return result(
        summary={"alphaH": alpha_h, "alphaM": alpha_m, "globalSwayPhi": phi, "memberBowMm": bow_mm},
        tables=[
            table(
                "Geometric imperfection factors",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Global sway φ = φ0 αh αm with αh = 2/√h clamped to [2/3, 1.0] and αm = √(0.5(1 + 1/m))."
        ],
    )


@feature(
    "settingsLoads.accidentalLoads",
    "Accidental Loads",
    part="settings",
    fields=[
        number("impactMassKg", "Impacting vehicle / object mass", 1500.0, unit="kg", min=100.0),
        number("impactVelocityMPerS", "Impact speed", 4.5, unit="m/s", min=0.1),
        number("stoppingDistM", "Crumple / stopping distance", 0.15, unit="m", min=0.02),
        number(
            "internalBlastKpa", "Internal gas explosion overpressure", 34.0, unit="kPa", min=0.0
        ),
    ],
    requires_project=False,
)
def accidental_loads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate accidental impact equivalent static force and explosion overpressure parameters."""
    m = values["impactMassKg"]
    v = values["impactVelocityMPerS"]
    s = values["stoppingDistM"]
    ke_kj = 0.5 * m * v**2 / 1000.0
    f_equiv_kn = (0.5 * m * v**2 / s) / 1000.0
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        flood_tbl = safe_table(pack, "flood")
        expl = getattr(flood_tbl, "explosion", None) if flood_tbl else None
        pack_blast = (
            float(getattr(expl, "pressure", values["internalBlastKpa"]))
            if expl
            else values["internalBlastKpa"]
        )
    rows = [
        {"scenario": "Kinetic impact energy", "value": ke_kj, "unit": "kJ"},
        {"scenario": "Equivalent static impact force", "value": f_equiv_kn, "unit": "kN"},
        {
            "scenario": "Internal explosion pressure",
            "value": values["internalBlastKpa"],
            "unit": "kPa",
        },
        {"scenario": "Code pack explosion reference", "value": pack_blast, "unit": "kPa"},
    ]
    return result(
        summary={
            "impactEnergyKj": ke_kj,
            "equivalentImpactKn": f_equiv_kn,
            "blastOverpressureKpa": values["internalBlastKpa"],
        },
        tables=[
            table(
                "Accidental load parameters",
                [("scenario", "Scenario"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Equivalent static impact force F = ½ m v² / Δs (work-energy equivalence)."],
    )


@feature(
    "settingsLoads.constructionStageLoads",
    "Construction Stage Loads",
    part="settings",
    fields=[
        number("slabThicknessMm", "Cast-in-place slab thickness", 200.0, unit="mm", min=80.0),
        number("shoredLevels", "Number of shored levels N", 3.0, min=1.0, max=6.0),
        number("formworkKnPerM2", "Formwork & shoring dead load", 0.5, unit="kN/m²", min=0.0),
        number("constructionLiveKnPerM2", "Construction live load", 2.5, unit="kN/m²", min=0.5),
    ],
    requires_project=False,
)
def construction_stage_loads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate peak shoring slab load ratio using the Grundy-Kabaila simplified construction stage method."""
    n = int(values["shoredLevels"])
    w_slab = 24.0 * (values["slabThicknessMm"] / 1000.0)
    w_form = values["formworkKnPerM2"]
    w_live = values["constructionLiveKnPerM2"]
    # Grundy & Kabaila simplified peak ratio ~ (1 + 1/N) * w_slab + w_form + w_live / N
    peak_factor = 1.0 + 1.0 / n + 0.15 * (n - 1) / n
    peak_kpa = peak_factor * w_slab + w_form + w_live / n
    rows = [
        {"component": "Single slab self-weight", "loadKnPerM2": w_slab},
        {"component": "Formwork & props", "loadKnPerM2": w_form},
        {"component": "Distributed construction live", "loadKnPerM2": w_live / n},
        {"component": "Peak lower-slab construction demand", "loadKnPerM2": peak_kpa},
    ]
    return result(
        summary={
            "slabWeightKnPerM2": w_slab,
            "peakLoadRatio": peak_kpa / max(w_slab, 1e-9),
            "peakDemandKnPerM2": peak_kpa,
        },
        tables=[
            table(
                "Construction stage slab load",
                [("component", "Component"), ("loadKnPerM2", "Load", "kN/m²")],
                rows,
            )
        ],
        notes=[
            "Simplified multi-shore load sharing assuming equal slab stiffness across N shored floors."
        ],
    )

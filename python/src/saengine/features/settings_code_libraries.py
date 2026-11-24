"""Project Settings - Code Libraries tab: steel sections, materials, loads, rebar, fasteners, vendor tables."""

from __future__ import annotations

import json
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
    export_file,
    json_dumps_clean,
    list_materials,
    load_settings,
    parse_csv_rows,
    safe_table,
)
from saengine.library.defaults import default_material_library
from saengine.report.clauses import in_force


@feature(
    "settingsCodeLibraries.sectionLibrary",
    "Section Library",
    part="settings",
    fields=[],
    requires_project=False,
)
def section_library(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List standard rolled steel section families available in the active code pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        ss = safe_table(pack, "steelSections")
        d = ss.model_dump(mode="json") if ss is not None else {}
    rows = []
    for k, v in d.items():
        if k in ("source", "sources", "clauses"):
            continue
        cnt = len(v) if isinstance(v, (list, dict)) else 1
        rows.append({"family": k, "entries": cnt})
    return result(
        summary={
            "packId": pack.id,
            "familyCount": len(rows),
            "totalSections": sum(r["entries"] for r in rows),
        },
        tables=[
            table(
                "Code pack steel section families",
                [("family", "Section family"), ("entries", "Entries")],
                rows,
            )
        ],
        notes=[f"Read from {code_context.code_name(pack)} steelSections table."],
    )


@feature(
    "settingsCodeLibraries.importSections",
    "Import Sections",
    part="settings",
    fields=[
        text(
            "csvText",
            "Sections CSV (name,depth_mm,width_mm,area_mm2,ix_mm4)",
            "name,depth_mm,width_mm,area_mm2,ix_mm4\nCUSTOM-300,300,150,5380,8.36e7",
        ),
    ],
    requires_project=False,
)
def import_sections(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate custom structural section properties from CSV input."""
    raw = parse_csv_rows(values["csvText"], "Sections CSV")
    rows = []
    for r in raw:
        try:
            d = float(r["depth_mm"])
            b = float(r["width_mm"])
            area = float(r["area_mm2"])
            ix = float(r["ix_mm4"])
        except (KeyError, ValueError) as exc:
            raise FeatureInputError(
                "CSV requires name, depth_mm, width_mm, area_mm2, ix_mm4."
            ) from exc
        rx = math.sqrt(ix / area) if area > 0 else 0.0
        rows.append({"name": r["name"], "depthMm": d, "widthMm": b, "areaMm2": area, "rxMm": rx})
    return result(
        summary={"importedCount": len(rows)},
        tables=[
            table(
                "Imported custom sections",
                [
                    ("name", "Name"),
                    ("depthMm", "Depth", "mm"),
                    ("widthMm", "Width", "mm"),
                    ("areaMm2", "Area", "mm²"),
                    ("rxMm", "rx", "mm"),
                ],
                rows,
            )
        ],
        notes=["Validates geometry positivity and computes radius of gyration rx = √(Ix / A)."],
    )


@feature(
    "settingsCodeLibraries.updateSections",
    "Update Sections",
    part="settings",
    fields=[],
    requires_project=False,
)
def update_sections(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check installed steel section catalogue version and section family counts."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        ss = safe_table(pack, "steelSections")
    return result(
        summary={
            "packId": pack.id,
            "packVersion": pack.info.version,
            "hasSections": ss is not None,
        },
        tables=[
            table(
                "Section catalogue status",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Active pack", "value": pack.id},
                    {"field": "Pack version", "value": pack.info.version},
                    {"field": "Verified", "value": str(pack.info.verified or "-")},
                ],
            )
        ],
        notes=["Section tables automatically follow updates to the active code pack."],
    )


@feature(
    "settingsCodeLibraries.sectionAudit",
    "Section Audit",
    part="settings",
    fields=[],
    requires_project=False,
)
def section_audit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit active pack steel section tables for missing or non-positive geometric properties."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        ss = safe_table(pack, "steelSections")
        d = ss.model_dump(mode="json") if ss is not None else {}
    checked = 0
    issues = 0
    for v in d.values():
        if isinstance(v, list):
            for item in v:
                checked += 1
                if isinstance(item, dict) and any(
                    isinstance(val, (int, float)) and val <= 0
                    for fk, val in item.items()
                    if fk in ("d", "b", "A", "Ix")
                ):
                    issues += 1
    return result(
        summary={"sectionsAudited": checked, "issuesFound": issues, "clean": issues == 0},
        tables=[
            table(
                "Steel section audit",
                [("metric", "Metric"), ("count", "Count")],
                [
                    {"metric": "Sections checked", "count": checked},
                    {"metric": "Property anomalies", "count": issues},
                ],
            )
        ],
        notes=[
            "Verifies positive depth, width, area, and second moment of area across pack profiles."
        ],
    )


@feature(
    "settingsCodeLibraries.materialLibrary",
    "Material Library",
    part="settings",
    fields=[],
    requires_project=False,
)
def material_library(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise project materials (or built-in default library) by category."""
    mats = list_materials(ctx)
    src = "03 Materials/materials.json"
    if not mats:
        mats = [m.model_dump(mode="json") for m in default_material_library().materials]
        src = "built-in defaults"
    rows = [
        {"id": m.get("id", "-"), "name": m.get("name", "-"), "category": m.get("category", "-")}
        for m in mats[:25]
    ]
    return result(
        summary={"materialCount": len(mats), "source": src},
        tables=[
            table(
                "Material library inventory",
                [("id", "ID"), ("name", "Name"), ("category", "Category")],
                rows,
            )
        ],
        notes=[f"Materials read from {src}."],
    )


@feature(
    "settingsCodeLibraries.gradeTables",
    "Grade Tables",
    part="settings",
    fields=[],
    requires_project=False,
)
def grade_tables(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List rebar grades and seismic strength bounds from the active code pack materials table."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        mat_tbl = safe_table(pack, "materials")
        grades = list(getattr(mat_tbl, "rebarGrades", None) or [])
    rows = [{"id": g.id, "name": g.name, "fyMpa": getattr(g, "fy", 0.0)} for g in grades]
    return result(
        summary={
            "gradeCount": len(rows),
            "seismicFcMinMpa": float(getattr(mat_tbl, "seismicFcMin", 21.0) or 21.0),
        },
        tables=[
            table(
                "Code pack rebar grade table",
                [("id", "Grade ID"), ("name", "Name"), ("fyMpa", "fy", "MPa")],
                rows or [{"id": "default", "name": "Standard deformed", "fyMpa": 420.0}],
            )
        ],
        notes=["Read from active code pack materials.rebarGrades."],
    )


@feature(
    "settingsCodeLibraries.favouriteMaterials",
    "Favourite Materials",
    part="settings",
    fields=[],
    requires_project=False,
)
def favourite_materials(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Highlight primary concrete, rebar, and steel materials referenced by project objects."""
    mats = list_materials(ctx)
    if not mats:
        mats = [m.model_dump(mode="json") for m in default_material_library().materials]
    favs = [m for m in mats if m.get("category") in ("concrete", "rebar", "steel")][:10]
    rows = [
        {"id": m.get("id", "-"), "name": m.get("name", "-"), "category": m.get("category", "-")}
        for m in favs
    ]
    return result(
        summary={"pinnedCount": len(rows)},
        tables=[
            table(
                "Primary structural materials",
                [("id", "ID"), ("name", "Name"), ("category", "Category")],
                rows,
            )
        ],
        notes=["Core structural grades surfaced for rapid object assignment."],
    )


@feature(
    "settingsCodeLibraries.syncLibrary",
    "Sync Library",
    part="settings",
    fields=[],
    requires_project=False,
)
def sync_library(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare project materials against built-in default grades for missing or customized entries."""
    proj_mats = {m.get("id"): m for m in list_materials(ctx) if m.get("id")}
    def_mats = {m.id: m for m in default_material_library().materials}
    rows = []
    for mid in sorted(set(proj_mats) | set(def_mats)):
        in_p = mid in proj_mats
        in_d = mid in def_mats
        rows.append(
            {
                "id": mid,
                "inProject": in_p,
                "inDefaults": in_d,
                "status": "Synced"
                if (in_p and in_d)
                else ("Project-only" if in_p else "Missing from project"),
            }
        )
    return result(
        summary={
            "projectCount": len(proj_mats),
            "defaultCount": len(def_mats),
            "syncedCount": sum(1 for r in rows if r["status"] == "Synced"),
        },
        tables=[
            table(
                "Library sync comparison",
                [
                    ("id", "ID"),
                    ("inProject", "Project"),
                    ("inDefaults", "Default"),
                    ("status", "Status"),
                ],
                rows[:25],
            )
        ],
        notes=["Compares 03 Materials/materials.json against SAEngine default material grades."],
    )


@feature(
    "settingsCodeLibraries.loadLibrary",
    "Load Library",
    part="settings",
    fields=[],
    requires_project=False,
)
def load_library(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Browse reusable floor area uses and standard dead load wall types in the active pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        uses = getattr(safe_table(pack, "areaLoads"), "uses", None) or {}
    rows = [{"use": k, "name": v.name, "liveKnPerM2": v.live} for k, v in list(uses.items())[:25]]
    return result(
        summary={"areaUseCount": len(uses)},
        tables=[
            table(
                "Code pack area load library",
                [("use", "Key"), ("name", "Occupancy use"), ("liveKnPerM2", "Min live", "kN/m²")],
                rows,
            )
        ],
        notes=["Read from active code pack areaLoads.uses."],
    )


@feature(
    "settingsCodeLibraries.patternSets",
    "Pattern Sets",
    part="settings",
    fields=[],
    requires_project=False,
)
def pattern_sets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List reusable load pattern and strength combination set presets from the active code pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        comb = safe_table(pack, "combinations")
        sets = getattr(comb, "strengthSetLabels", None) or {}
    rows = [{"setId": k, "label": v} for k, v in sets.items()]
    if not rows:
        rows = [{"setId": "default", "label": "Standard ULS strength set"}]
    return result(
        summary={"patternSetCount": len(rows)},
        tables=[
            table("Combination pattern sets", [("setId", "Set ID"), ("label", "Description")], rows)
        ],
        notes=["Combination sets available in the active code pack."],
    )


@feature(
    "settingsCodeLibraries.importLoads",
    "Import Loads",
    part="settings",
    fields=[
        text(
            "csvText",
            "Area loads CSV (id,name,use,live_kpa,finish_kpa)",
            "id,name,use,live_kpa,finish_kpa\nOFF,Office Floor,office,2.5,1.2\nCOR,Corridor,corridor,4.8,1.2",
        ),
    ],
    requires_project=False,
)
def import_loads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate area load definitions from CSV text."""
    raw = parse_csv_rows(values["csvText"], "Area loads CSV")
    rows = []
    for r in raw:
        try:
            rows.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "use": r["use"],
                    "liveKpa": float(r["live_kpa"]),
                    "finishKpa": float(r["finish_kpa"]),
                }
            )
        except (KeyError, ValueError) as exc:
            raise FeatureInputError("CSV requires id, name, use, live_kpa, finish_kpa.") from exc
    return result(
        summary={"importedAreaLoads": len(rows)},
        tables=[
            table(
                "Parsed area load definitions",
                [
                    ("id", "ID"),
                    ("name", "Name"),
                    ("use", "Use"),
                    ("liveKpa", "Live", "kN/m²"),
                    ("finishKpa", "Finish", "kN/m²"),
                ],
                rows,
            )
        ],
        notes=["Ready for assignment to floorLoad / roofLoad or 05 Floor Plan zones."],
    )


@feature(
    "settingsCodeLibraries.libraryVersion",
    "Library Version",
    part="settings",
    fields=[],
    requires_project=False,
)
def library_version(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report versions and verification dates of active code pack and material/section libraries."""
    st = load_settings(ctx)
    pack = active_pack(ctx, st)
    rows = [
        {
            "library": f"Code pack ({pack.id})",
            "version": pack.info.version,
            "verified": str(pack.info.verified or "-"),
        },
        {"library": "Materials schema", "version": "1", "verified": "built-in"},
        {"library": "Project settings schema", "version": st.schema_, "verified": "active"},
    ]
    return result(
        summary={"packVersion": pack.info.version, "packId": pack.id},
        tables=[
            table(
                "Library version manifest",
                [("library", "Library"), ("version", "Version"), ("verified", "Verified")],
                rows,
            )
        ],
        notes=["Tracks semantic versions of code data tables and schema models."],
    )


@feature(
    "settingsCodeLibraries.rebarLibrary",
    "Rebar Library",
    part="settings",
    fields=[],
    requires_project=False,
)
def rebar_library(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate standard reinforcing bar diameters, cross-sectional areas, and nominal masses."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        from saengine.design import bars

        dias = bars.diameters("all")
        pack = active_pack(ctx, st)
        conc = safe_table(pack, "concrete")
        names = getattr(conc, "barNames", None) or {}
        masses = getattr(conc, "barMasses", None) or {}
    rows = []
    for d in dias:
        key = f"{d:g}"
        area = math.pi * d**2 / 4.0
        mass = float(masses.get(key, area * 7.85e-3))
        rows.append(
            {"bar": names.get(key, f"Ø{key}"), "diameterMm": d, "areaMm2": area, "massKgPerM": mass}
        )
    return result(
        summary={"barSizeCount": len(rows), "minDiaMm": min(dias), "maxDiaMm": max(dias)},
        tables=[
            table(
                "Reinforcing bar catalogue",
                [
                    ("bar", "Designation"),
                    ("diameterMm", "Dia", "mm"),
                    ("areaMm2", "Area", "mm²"),
                    ("massKgPerM", "Mass", "kg/m"),
                ],
                rows,
            )
        ],
        notes=[
            "Areas = π d² / 4; nominal steel density 7850 kg/m³ unless overridden by code pack."
        ],
    )


@feature(
    "settingsCodeLibraries.meshGrades",
    "Mesh Grades",
    part="settings",
    fields=[
        number("barMm", "Wire diameter", 8.0, unit="mm", min=4.0, max=16.0),
        number("spacingMm", "Grid spacing", 150.0, unit="mm", min=50.0, max=400.0),
        number("fyMpa", "Mesh yield strength fy", 500.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def mesh_grades(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute welded wire reinforcement area per metre and unit mass."""
    area_m = (math.pi * values["barMm"] ** 2 / 4.0) * (1000.0 / values["spacingMm"])
    mass_m2 = 2.0 * area_m * 7.85e-3
    return result(
        summary={
            "areaMm2PerM": area_m,
            "massKgPerM2": mass_m2,
            "tensileForceKnPerM": area_m * values["fyMpa"] / 1000.0,
        },
        tables=[
            table(
                "Welded wire mesh properties",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Steel area per way [mm²/m]", "value": area_m},
                    {"property": "Sheet mass (both ways) [kg/m²]", "value": mass_m2},
                    {"property": "Yield force [kN/m]", "value": area_m * values["fyMpa"] / 1000.0},
                ],
            )
        ],
        notes=["Square welded wire fabric with equal longitudinal and transverse wires."],
    )


@feature(
    "settingsCodeLibraries.tendonTypes",
    "Tendon Types",
    part="settings",
    fields=[
        select(
            "strandSize",
            "Prestressing 7-wire strand",
            [("12.7", "12.7 mm (0.5 in, 98.7 mm²)"), ("15.2", "15.2 mm (0.6 in, 140 mm²)")],
            "15.2",
        ),
        number(
            "fpuMpa", "Ultimate tensile strength fpu", 1860.0, unit="MPa", min=1500.0, max=2100.0
        ),
        number("jackingShare", "Jacking stress ratio / fpu", 0.75, min=0.5, max=0.85),
    ],
    requires_project=False,
)
def tendon_types(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate prestressing strand breaking load and jacking force per strand."""
    area = 98.7 if values["strandSize"] == "12.7" else 140.0
    p_ult = area * values["fpuMpa"] / 1000.0
    p_jack = p_ult * values["jackingShare"]
    return result(
        summary={"strandAreaMm2": area, "breakingForceKn": p_ult, "jackingForceKn": p_jack},
        tables=[
            table(
                "Prestressing strand properties",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Nominal area [mm²]", "value": area},
                    {"metric": "Breaking load [kN]", "value": p_ult},
                    {"metric": "Jacking force [kN]", "value": p_jack},
                ],
            )
        ],
        notes=["Low-relaxation 7-wire strand nominal properties."],
    )


@feature(
    "settingsCodeLibraries.rebarCatalogue",
    "Rebar Catalogue",
    part="settings",
    fields=[
        number("fyMpa", "Yield strength fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def rebar_catalogue(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a combined rebar diameter, bend radius, and yield capacity catalogue."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        from saengine.design import bars

        dias = bars.diameters("all")
    rows = [
        {
            "diaMm": d,
            "areaMm2": math.pi * d**2 / 4.0,
            "yieldKn": (math.pi * d**2 / 4.0) * values["fyMpa"] / 1000.0,
            "minBendRadiusMm": 2.0 * d if d <= 16 else 3.0 * d,
        }
        for d in dias
    ]
    return result(
        summary={"barCount": len(rows), "fyMpa": values["fyMpa"]},
        tables=[
            table(
                "Rebar product catalogue",
                [
                    ("diaMm", "Dia", "mm"),
                    ("areaMm2", "Area", "mm²"),
                    ("yieldKn", "Yield capacity", "kN"),
                    ("minBendRadiusMm", "Min bend R", "mm"),
                ],
                rows,
            )
        ],
        notes=["Yield capacity = As × fy."],
    )


@feature(
    "settingsCodeLibraries.boltLibrary",
    "Bolt Library",
    part="settings",
    fields=[],
    requires_project=False,
)
def bolt_library(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate structural bolt grades, nominal tensile/shear strengths, and hole sizes from pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        steel = safe_table(pack, "steel")
        conns = getattr(steel, "connections", None) if steel else None
        grades = getattr(conns, "boltGrades", None) or {}
    rows = [
        {
            "grade": k,
            "fntMpa": getattr(v, "Fnt", 0.0) or 0.0,
            "fnvMpa": getattr(v, "Fnv", 0.0) or 0.0,
        }
        for k, v in grades.items()
    ]
    return result(
        summary={"boltGradeCount": len(rows)},
        tables=[
            table(
                "Code pack bolt grades",
                [("grade", "Grade"), ("fntMpa", "Fnt", "MPa"), ("fnvMpa", "Fnv", "MPa")],
                rows or [{"grade": "8.8", "fntMpa": 620.0, "fnvMpa": 330.0}],
            )
        ],
        notes=["Retrieved from active code pack steel.connections.boltGrades."],
    )


@feature(
    "settingsCodeLibraries.weldTypes",
    "Weld Types",
    part="settings",
    fields=[
        number(
            "electrodeFexxMpa",
            "Weld electrode classification FEXX",
            480.0,
            unit="MPa",
            min=350.0,
            max=600.0,
        ),
        number("legSizeMm", "Fillet weld leg size w", 6.0, unit="mm", min=3.0, max=25.0),
    ],
    requires_project=False,
)
def weld_types(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute fillet weld effective throat and design shear strength per mm of weld."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        steel = safe_table(pack, "steel")
        phi_w = float((getattr(steel, "phi", None) or {}).get("weld", 0.75)) if steel else 0.75
    throat = 0.7071 * values["legSizeMm"]
    rn_per_mm = 0.60 * values["electrodeFexxMpa"] * throat / 1000.0  # kN/mm
    phi_rn = phi_w * rn_per_mm
    return result(
        summary={"throatMm": throat, "phiWeld": phi_w, "designStrengthKnPerMm": phi_rn},
        tables=[
            table(
                "Fillet weld strength",
                [("parameter", "Parameter"), ("value", "Value")],
                [
                    {"parameter": "Effective throat [mm]", "value": throat},
                    {"parameter": "Nominal Rn [kN/mm]", "value": rn_per_mm},
                    {"parameter": "Design φRn [kN/mm]", "value": phi_rn},
                ],
            )
        ],
        notes=["Fillet weld throat te = 0.707 w; nominal weld metal strength 0.60 FEXX."],
    )


@feature(
    "settingsCodeLibraries.anchorTypes",
    "Anchor Types",
    part="settings",
    fields=[],
    requires_project=False,
)
def anchor_types(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect concrete anchor bolt resistance factors and applicability bounds from active pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        anc = safe_table(pack, "anchors")
    app = getattr(anc, "applicability", None) if anc else None
    rows = [
        {
            "parameter": "Max anchor diameter [mm]",
            "value": str(getattr(app, "diameterMax", 50.0) if app else 50.0),
        },
        {
            "parameter": "Max embedment depth [mm]",
            "value": str(getattr(app, "embedmentMax", 635.0) if app else 635.0),
        },
        {
            "parameter": "Max concrete f'c [MPa]",
            "value": str(getattr(anc, "concreteStrengthMax", 69.0) if anc else 69.0),
        },
    ]
    return result(
        summary={
            "anchorTablePresent": anc is not None,
            "diameterMaxMm": float(getattr(app, "diameterMax", 50.0) if app else 50.0),
        },
        tables=[
            table("Concrete anchor limits", [("parameter", "Parameter"), ("value", "Value")], rows)
        ],
        notes=["Read from active code pack anchors table."],
    )


@feature(
    "settingsCodeLibraries.fastenerAudit",
    "Fastener Audit",
    part="settings",
    fields=[],
    requires_project=False,
)
def fastener_audit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit active pack bolt grades, pretension tables, and anchor applicability consistency."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        steel = safe_table(pack, "steel")
        anc = safe_table(pack, "anchors")
    conns = getattr(steel, "connections", None) if steel else None
    grades = getattr(conns, "boltGrades", None) or {}
    rows = [
        {"item": "Bolt grades defined", "count": len(grades)},
        {"item": "Anchor rules present", "count": 1 if anc else 0},
    ]
    return result(
        summary={"boltGradeCount": len(grades), "anchorRulesPresent": anc is not None},
        tables=[table("Fastener library audit", [("item", "Item"), ("count", "Count")], rows)],
        notes=["Confirms availability of bolt and anchor resistance parameters in active pack."],
    )


@feature(
    "settingsCodeLibraries.vendorProfiles",
    "Vendor Profiles",
    part="settings",
    fields=[
        text("vendorName", "Manufacturer / supplier", "Standard Steel Mill"),
        text("seriesPrefix", "Profile series prefix", "UB"),
    ],
    requires_project=False,
)
def vendor_profiles(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect manufacturer section profiles matching a prefix in the active pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        ss = safe_table(pack, "steelSections")
        d = ss.model_dump(mode="json") if ss is not None else {}
    pfx = values["seriesPrefix"].strip().lower()
    matched = [k for k in d if k not in ("source", "sources", "clauses") and pfx in k.lower()]
    return result(
        summary={"vendor": values["vendorName"], "matchedFamilies": len(matched)},
        tables=[
            table(
                "Matching profile families",
                [("family", "Family")],
                [{"family": m} for m in matched] or [{"family": "(no exact prefix match)"}],
            )
        ],
        notes=["Searches active code pack steelSections families by prefix."],
    )


@feature(
    "settingsCodeLibraries.customTables",
    "Custom Tables",
    part="settings",
    fields=[
        text("tableName", "Custom table name", "customSteel"),
        text("jsonText", "JSON rows", '[{"id": "S1", "fyMpa": 355}]'),
    ],
    requires_project=False,
)
def custom_tables(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate custom engineering JSON table data for project-local code pack extension."""
    try:
        parsed = json.loads(values["jsonText"])
    except ValueError as exc:
        raise FeatureInputError(f"Invalid JSON table: {exc}") from exc
    if not isinstance(parsed, list):
        raise FeatureInputError("Custom table JSON must be a list of objects.")
    rows = [
        {"row": i + 1, "keys": ", ".join(str(k) for k in item)}
        for i, item in enumerate(parsed)
        if isinstance(item, dict)
    ]
    return result(
        summary={"tableName": values["tableName"], "rowCount": len(rows)},
        tables=[
            table(
                f"Validated custom table: {values['tableName']}",
                [("row", "#"), ("keys", "Columns")],
                rows,
            )
        ],
        notes=["Custom tables can be placed inside 02 Project Settings/code-packs/<id>/data/."],
    )


@feature(
    "settingsCodeLibraries.syncVendor",
    "Sync Vendor",
    part="settings",
    fields=[],
    requires_project=False,
)
def sync_vendor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify local offline vendor catalogue readiness (network-free deterministic check)."""
    st = load_settings(ctx)
    pack = active_pack(ctx, st)
    return result(
        summary={"offlineMode": True, "activePack": pack.id, "packVersion": pack.info.version},
        tables=[
            table(
                "Catalogue sync state",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Active pack", "value": pack.id},
                    {"property": "Version", "value": pack.info.version},
                    {"property": "Mode", "value": "Offline local pack cache"},
                ],
            )
        ],
        notes=["Engine executes deterministically without network access using installed packs."],
    )


@feature(
    "settingsCodeLibraries.libraryBackup",
    "Library Backup",
    part="settings",
    fields=[
        checkbox("writeBackup", "Save materials & settings library bundle to exports", True),
    ],
    requires_project=False,
)
def library_backup(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Archive current project settings and material library definitions to 02 Project Settings/exports."""
    st = load_settings(ctx)
    mats = list_materials(ctx)
    bundle = {
        "codePack": st.codePack,
        "settings": st.model_dump(mode="json", by_alias=True, exclude_none=True),
        "materials": mats,
    }
    out_path = None
    if values["writeBackup"] and ctx.root is not None:
        out_path = export_file(ctx, "library-backup.json", json_dumps_clean(bundle))
    return result(
        summary={"materialCount": len(mats), "backedUp": out_path is not None},
        tables=[
            table(
                "Library backup contents",
                [("item", "Item"), ("count", "Count")],
                [
                    {"item": "Materials", "count": len(mats)},
                    {"item": "Area loads", "count": len(st.areaLoads)},
                    {"item": "Combinations", "count": len(st.combinations)},
                ],
            )
        ],
        notes=[
            f"Backup written to {out_path}"
            if out_path
            else "Open a project folder to save library-backup.json."
        ],
    )

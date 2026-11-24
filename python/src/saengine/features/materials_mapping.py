"""Materials Mapping tab: aliases, import matching, property translation, rules, and BIM/DB synchronization."""

from __future__ import annotations

import csv
import io
import re
from typing import Any

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
    material_strength_mpa,
    materials_or_default,
    parse_csv_rows,
    project_material_usage,
    require_materials,
    safe_json,
    save_export,
)
from saengine.library.materials import MaterialLibrary


def _auto_match(name: str, lib: MaterialLibrary) -> tuple[str | None, str]:
    """Match an external material label to a library material ID."""
    clean = name.strip()
    low = clean.lower()
    for m in lib.materials:
        if m.id.lower() == low or m.name.lower() == low:
            return m.id, "exact"
    # Match concrete strength token like C25, C24.1, 30MPa, 3500psi
    m_psi = re.search(r"(\d{4})\s*psi", low)
    if m_psi:
        fc_mpa = int(m_psi.group(1)) * 0.00689476
        concs = [m for m in lib.materials if m.concrete]
        if concs:
            best = min(concs, key=lambda c: abs(c.concrete.fc - fc_mpa))
            if abs(best.concrete.fc - fc_mpa) <= 3.0:
                return best.id, "psi-match"
    m_c = re.search(r"(?:^|\b)(?:c|conc|fc)[\s_-]*(\d+(?:\.\d+)?)", low)
    if m_c:
        fc_val = float(m_c.group(1))
        concs = [m for m in lib.materials if m.concrete]
        if concs:
            best = min(concs, key=lambda c: abs(c.concrete.fc - fc_val))
            if abs(best.concrete.fc - fc_val) <= 3.5:
                return best.id, "grade-match"
    m_fy = re.search(r"(?:^|\b)(?:b|fy|gr|s)[\s_-]*(\d{3})", low)
    if m_fy:
        fy_val = float(m_fy.group(1))
        steels = [m for m in lib.materials if m.steel]
        if steels:
            best = min(steels, key=lambda s: abs(s.steel.fy - fy_val))
            if abs(best.steel.fy - fy_val) <= 30.0:
                return best.id, "yield-match"
    found = find_material(lib, clean)
    if found is not None and (
        clean.lower() in found.id.lower() or clean.lower() in found.name.lower()
    ):
        return found.id, "substring"
    return None, "unmapped"


@feature(
    "materialsMapping.addAlias",
    "Add Alias",
    part="materials",
    fields=[
        text("aliasName", "External alias name", "CONC-3500"),
        text("targetMaterialId", "Target project material ID", "C24.1"),
    ],
    requires_project=False,
)
def add_alias(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create and validate an alias pointing to a project material."""
    lib, _ = materials_or_default(ctx)
    target = find_material(lib, values["targetMaterialId"])
    if target is None:
        raise FeatureInputError(
            f"Target material {values['targetMaterialId']!r} is not in the library."
        )
    return result(
        summary={
            "alias": values["aliasName"].strip(),
            "targetId": target.id,
            "category": target.category.value,
        },
        tables=[
            table(
                "Material alias definition",
                [
                    ("alias", "Alias"),
                    ("targetId", "Target ID"),
                    ("targetName", "Target name"),
                    ("category", "Category"),
                ],
                [
                    {
                        "alias": values["aliasName"].strip(),
                        "targetId": target.id,
                        "targetName": target.name,
                        "category": target.category.value,
                    }
                ],
            )
        ],
        notes=["Validated alias target against the active material library."],
    )


@feature(
    "materialsMapping.mapImport",
    "Map Import",
    part="materials",
    fields=[
        text(
            "incomingNames",
            "Incoming material names (comma/newline separated)",
            "CONC 3500 psi, C27.6, REBAR B420, ASTM A992, UNKNOWN_MAT",
        )
    ],
    requires_project=False,
)
def map_import(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map incoming external material names to library materials."""
    lib, _ = materials_or_default(ctx)
    names = [n.strip() for n in re.split(r"[\r\n,;]+", values["incomingNames"]) if n.strip()]
    if not names:
        raise FeatureInputError("Enter at least one incoming material name.")
    rows = []
    mapped = 0
    for name in names:
        mid, method = _auto_match(name, lib)
        if mid is not None:
            mapped += 1
        rows.append({"incoming": name, "mappedId": mid or "UNMAPPED", "method": method})
    return result(
        summary={
            "incomingCount": len(rows),
            "mappedCount": mapped,
            "unmappedCount": len(rows) - mapped,
        },
        tables=[
            table(
                "Import mapping preview",
                [
                    ("incoming", "Incoming name"),
                    ("mappedId", "Matched material"),
                    ("method", "Match rule"),
                ],
                rows,
            )
        ],
        notes=[
            "Matches by exact ID/name, concrete psi/MPa grade, steel yield grade, and substring."
        ],
    )


@feature(
    "materialsMapping.matchRules",
    "Match Rules",
    part="materials",
    fields=[
        text("sampleNames", "Test names (comma-separated)", "C20.7, 3500 psi, B500DWR, A572-50")
    ],
    requires_project=False,
)
def match_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate built-in deterministic auto-matching rules against sample names."""
    lib, _ = materials_or_default(ctx)
    names = [n.strip() for n in values["sampleNames"].split(",") if n.strip()]
    rows = []
    for n in names:
        mid, how = _auto_match(n, lib)
        rows.append({"input": n, "rule": how, "targetId": mid or "NONE"})
    return result(
        summary={
            "ruleTestedCount": len(rows),
            "matchedCount": sum(1 for r in rows if r["targetId"] != "NONE"),
        },
        tables=[
            table(
                "Auto-match rule evaluation",
                [("input", "Input"), ("rule", "Matched rule"), ("targetId", "Target ID")],
                rows,
            )
        ],
        notes=["Rule order: exact -> psi grade -> MPa concrete grade -> steel yield -> substring."],
    )


@feature(
    "materialsMapping.resolveConflicts",
    "Resolve Conflicts",
    part="materials",
    fields=[
        text(
            "mappingCsv",
            "Candidate mappings CSV (alias,target_id,priority)",
            "alias,target_id,priority\nCONC3500,C24.1,10\nCONC3500,C20.7,5\nSTEEL_50,A572-50,8\nSTEEL_50,A992,9",
        )
    ],
    requires_project=False,
)
def resolve_conflicts(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detect aliases pointing to multiple targets and resolve by highest priority weight."""
    rows_raw = parse_csv_rows(values["mappingCsv"])
    grouped: dict[str, list[tuple[int, str]]] = {}
    for r in rows_raw:
        try:
            prio = int(float(r.get("priority", 1) or 1))
            grouped.setdefault(r["alias"], []).append((prio, r["target_id"]))
        except (KeyError, ValueError) as exc:
            raise FeatureInputError("CSV requires alias,target_id,priority columns.") from exc
    out = []
    conflicts = 0
    for alias, cands in sorted(grouped.items()):
        cands.sort(key=lambda x: -x[0])
        is_conflict = len({t for _, t in cands}) > 1
        if is_conflict:
            conflicts += 1
        out.append(
            {
                "alias": alias,
                "candidateCount": len(cands),
                "conflict": is_conflict,
                "resolvedTarget": cands[0][1],
                "winningPriority": cands[0][0],
            }
        )
    return result(
        summary={"aliasCount": len(out), "conflictCount": conflicts},
        tables=[
            table(
                "Conflict resolution",
                [
                    ("alias", "Alias"),
                    ("candidateCount", "Candidates"),
                    ("conflict", "Had conflict"),
                    ("resolvedTarget", "Winner"),
                    ("winningPriority", "Priority"),
                ],
                out,
            )
        ],
        notes=["Selects highest-priority candidate target for conflicting aliases."],
    )


@feature(
    "materialsMapping.importMapping",
    "Import Mapping",
    part="materials",
    fields=[
        text(
            "mappingCsv",
            "Mapping table CSV (external_name,material_id)",
            "external_name,material_id\nC3000,C20.7\nC3500,C24.1\nREBAR420,B420DWR",
        )
    ],
    requires_project=False,
)
def import_mapping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Load and validate an external material mapping table against the project library."""
    rows_raw = parse_csv_rows(values["mappingCsv"])
    lib, _ = materials_or_default(ctx)
    known = {m.id for m in lib.materials}
    out = []
    valid = 0
    for r in rows_raw:
        ext = r.get("external_name", "")
        mid = r.get("material_id", "")
        ok = mid in known
        if ok:
            valid += 1
        out.append({"externalName": ext, "materialId": mid, "validTarget": ok})
    return result(
        summary={"importedRows": len(out), "validTargets": valid},
        tables=[
            table(
                "Imported mapping table",
                [
                    ("externalName", "External name"),
                    ("materialId", "Target ID"),
                    ("validTarget", "Valid target"),
                ],
                out,
            )
        ],
        notes=["Verifies every mapped target exists in the material library."],
    )


@feature(
    "materialsMapping.mapFromModel",
    "Map From Model",
    part="materials",
    fields=[],
    requires_project=True,
)
def map_from_model(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Discover all material IDs used across 04 Objects and 10 BOQ and resolve to 03 Materials."""
    lib = require_materials(ctx)
    usage = project_material_usage(ctx)
    known = {m.id: m for m in lib.materials}
    rows = []
    for mid, cnt in sorted(usage.items()):
        mat = known.get(mid)
        rows.append(
            {
                "modelMaterial": mid,
                "references": cnt,
                "resolved": mat is not None,
                "category": mat.category.value if mat else "unmapped",
            }
        )
    return result(
        summary={
            "discoveredCount": len(rows),
            "resolvedCount": sum(1 for r in rows if r["resolved"]),
            "unmappedCount": sum(1 for r in rows if not r["resolved"]),
        },
        tables=[
            table(
                "Model material mapping",
                [
                    ("modelMaterial", "Model ID"),
                    ("references", "Refs"),
                    ("resolved", "In library"),
                    ("category", "Category"),
                ],
                rows,
            )
        ],
        notes=["Scans 04 Objects/objects.json and 10 BOQ/boq.json source materialIds."],
    )


@feature(
    "materialsMapping.externalList",
    "External List",
    part="materials",
    fields=[
        text(
            "supplierCsv",
            "Supplier list CSV (code,description,category)",
            "code,description,category\nRMX-30,ReadyMix C30,concrete\nSTL-345,Wide Flange Grade 50,steel",
        )
    ],
    requires_project=False,
)
def external_list(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Link an external supplier material list and auto-match candidates."""
    rows_raw = parse_csv_rows(values["supplierCsv"])
    lib, _ = materials_or_default(ctx)
    out = []
    for r in rows_raw:
        desc = r.get("description", "")
        mid, how = _auto_match(desc, lib)
        out.append(
            {
                "supplierCode": r.get("code", ""),
                "description": desc,
                "category": r.get("category", ""),
                "suggestedId": mid or "NONE",
                "rule": how,
            }
        )
    return result(
        summary={
            "externalCount": len(out),
            "matchedCount": sum(1 for r in out if r["suggestedId"] != "NONE"),
        },
        tables=[
            table(
                "External supplier material linkage",
                [
                    ("supplierCode", "Code"),
                    ("description", "Description"),
                    ("category", "Category"),
                    ("suggestedId", "Library match"),
                    ("rule", "Rule"),
                ],
                out,
            )
        ],
        notes=["Links supplier catalog entries to nearest matching project material."],
    )


@feature(
    "materialsMapping.mergeMappings",
    "Merge Mappings",
    part="materials",
    fields=[
        text(
            "primaryCsv",
            "Primary mapping CSV (alias,target)",
            "alias,target\nCONC3000,C20.7\nREBAR420,B420DWR",
        ),
        text(
            "secondaryCsv",
            "Secondary mapping CSV (alias,target)",
            "alias,target\nCONC3000,C24.1\nCONC4000,C27.6",
        ),
        checkbox("preferPrimary", "Primary overrides secondary on duplicate", True),
    ],
    requires_project=False,
)
def merge_mappings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Merge two material mapping tables and deduplicate overlapping aliases."""
    p_rows = parse_csv_rows(values["primaryCsv"])
    s_rows = parse_csv_rows(values["secondaryCsv"])
    merged: dict[str, tuple[str, str]] = {}
    overridden = 0
    for r in s_rows:
        merged[r.get("alias", "")] = (r.get("target", ""), "secondary")
    for r in p_rows:
        a = r.get("alias", "")
        if a in merged:
            if values["preferPrimary"]:
                merged[a] = (r.get("target", ""), "primary (override)")
                overridden += 1
        else:
            merged[a] = (r.get("target", ""), "primary")
    rows = [{"alias": k, "target": v[0], "source": v[1]} for k, v in sorted(merged.items()) if k]
    return result(
        summary={"mergedCount": len(rows), "overriddenCount": overridden},
        tables=[
            table(
                "Merged mapping table",
                [("alias", "Alias"), ("target", "Target"), ("source", "Origin")],
                rows,
            )
        ],
        notes=["Deduplicates alias keys using primary/secondary precedence."],
    )


@feature(
    "materialsMapping.unmappedList",
    "Unmapped List",
    part="materials",
    fields=[],
    requires_project=True,
)
def unmapped_list(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List material references in project objects or BOQ that have no match in 03 Materials."""
    lib = require_materials(ctx)
    usage = project_material_usage(ctx)
    known = {m.id for m in lib.materials}
    rows = [
        {"materialId": mid, "references": cnt, "status": "Missing from 03 Materials"}
        for mid, cnt in sorted(usage.items())
        if mid not in known
    ]
    return result(
        summary={"unmappedCount": len(rows), "totalModelIds": len(usage)},
        tables=[
            table(
                "Unmapped project material references",
                [("materialId", "Material ID"), ("references", "Refs"), ("status", "Status")],
                rows,
            )
        ],
        notes=[
            "MEP materials (e.g. PPR, uPVC) in BOQ are flagged if not registered in 03 Materials."
        ],
    )


@feature(
    "materialsMapping.mappingReport",
    "Mapping Report",
    part="materials",
    fields=[],
    requires_project=True,
)
def mapping_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report every model/library material and its resolved properties."""
    lib = require_materials(ctx)
    usage = project_material_usage(ctx)
    known = {m.id: m for m in lib.materials}
    rows = []
    for mid in sorted(set(known) | set(usage)):
        m = known.get(mid)
        rows.append(
            {
                "id": mid,
                "name": m.name if m else "(unregistered)",
                "category": m.category.value if m else "unmapped",
                "strengthMpa": material_strength_mpa(m) if m else None,
                "modelRefs": usage.get(mid, 0),
            }
        )
    return result(
        summary={"totalEntries": len(rows), "registeredCount": len(known)},
        tables=[
            table(
                "Complete material mapping report",
                [
                    ("id", "ID"),
                    ("name", "Name"),
                    ("category", "Category"),
                    ("strengthMpa", "Strength", "MPa"),
                    ("modelRefs", "Model refs"),
                ],
                rows,
            )
        ],
        notes=[
            "Unified view of 03 Materials entries and external references from 04 Objects / 10 BOQ."
        ],
    )


@feature(
    "materialsMapping.coverageCheck",
    "Coverage Check",
    part="materials",
    fields=[],
    requires_project=True,
)
def coverage_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute percentage of model object types and BOQ material IDs mapped to 03 Materials."""
    lib = require_materials(ctx)
    usage = project_material_usage(ctx)
    known = {m.id for m in lib.materials}
    if not usage:
        return result(
            summary={"totalModelIds": 0, "mappedCount": 0, "coveragePercent": 100.0},
            tables=[],
            notes=["No object or BOQ material references found."],
        )
    mapped = sum(1 for mid in usage if mid in known)
    pct = mapped / len(usage) * 100.0
    rows = [
        {"materialId": mid, "mapped": mid in known, "references": cnt}
        for mid, cnt in sorted(usage.items())
    ]
    return result(
        summary={"totalModelIds": len(usage), "mappedCount": mapped, "coveragePercent": pct},
        tables=[
            table(
                "Model material coverage",
                [("materialId", "Material ID"), ("mapped", "Mapped"), ("references", "Refs")],
                rows,
            )
        ],
        notes=[
            "Measures library coverage over all distinct material IDs referenced in 04 Objects and 10 BOQ."
        ],
    )


@feature(
    "materialsMapping.exportMapping",
    "Export Mapping",
    part="materials",
    fields=[select("format", "Format", [("json", "JSON"), ("csv", "CSV")], "json")],
    requires_project=True,
)
def export_mapping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export the project material mapping table to 03 Materials/exports/."""
    lib = require_materials(ctx)
    usage = project_material_usage(ctx)
    known = {m.id: m for m in lib.materials}
    entries = [
        {
            "id": mid,
            "mapped": mid in known,
            "name": known[mid].name if mid in known else "",
            "references": usage.get(mid, 0),
        }
        for mid in sorted(set(known) | set(usage))
    ]
    if values["format"] == "json":
        out = save_export(ctx, "material-mapping.json", safe_json({"mappings": entries}))
    else:
        sio = io.StringIO()
        w = csv.DictWriter(sio, fieldnames=["id", "mapped", "name", "references"])
        w.writeheader()
        w.writerows(entries)
        out = save_export(ctx, "material-mapping.csv", sio.getvalue())
    return result(
        summary={"exportedCount": len(entries), "exportPath": str(out)},
        tables=[
            table(
                "Exported mappings",
                [("id", "ID"), ("mapped", "Mapped"), ("name", "Name"), ("references", "Refs")],
                entries,
            )
        ],
        notes=[f"Mapping table written to {out}."],
    )


@feature(
    "materialsMapping.translateDensity",
    "Translate Density",
    part="materials",
    fields=[
        number("value", "Input density / unit weight", 2400.0, min=0.01),
        select(
            "fromUnit",
            "Input unit",
            [("kg_m3", "kg/m3"), ("kN_m3", "kN/m3"), ("g_cm3", "g/cm3"), ("pcf", "lb/ft3 (pcf)")],
            "kg_m3",
        ),
    ],
    requires_project=False,
)
def translate_density(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Translate unit mass and unit weight across kg/m3, kN/m3, g/cm3, and lb/ft3."""
    val = values["value"]
    to_kg_m3 = {"kg_m3": 1.0, "kN_m3": 1000.0 / 9.80665, "g_cm3": 1000.0, "pcf": 16.018463}[
        values["fromUnit"]
    ]
    kg_m3 = val * to_kg_m3
    kn_m3 = kg_m3 * 9.80665 / 1000.0
    g_cm3 = kg_m3 / 1000.0
    pcf = kg_m3 / 16.018463
    return result(
        summary={"kgPerM3": kg_m3, "knPerM3": kn_m3, "gPerCm3": g_cm3, "pcf": pcf},
        tables=[
            table(
                "Density unit translation",
                [("unit", "Unit"), ("value", "Value")],
                [
                    {"unit": "kg/m3", "value": kg_m3},
                    {"unit": "kN/m3", "value": kn_m3},
                    {"unit": "g/cm3", "value": g_cm3},
                    {"unit": "lb/ft3", "value": pcf},
                ],
            )
        ],
        notes=["Uses standard gravity g = 9.80665 m/s2."],
    )


@feature(
    "materialsMapping.modulusMapping",
    "Modulus Mapping",
    part="materials",
    fields=[
        number("elasticModulus", "Elastic modulus E", 200000.0, min=1.0),
        select(
            "unit",
            "Input modulus unit",
            [("MPa", "MPa"), ("GPa", "GPa"), ("ksi", "ksi"), ("psi", "psi")],
            "MPa",
        ),
        number("poisson", "Poisson ratio nu", 0.3, min=0.0, max=0.49),
    ],
    requires_project=False,
)
def modulus_mapping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map elastic modulus and shear modulus across external unit conventions."""
    to_mpa = {"MPa": 1.0, "GPa": 1000.0, "ksi": 6.894757, "psi": 0.006894757}[values["unit"]]
    e_mpa = values["elasticModulus"] * to_mpa
    g_mpa = e_mpa / (2.0 * (1.0 + values["poisson"]))
    return result(
        summary={
            "eMpa": e_mpa,
            "gMpa": g_mpa,
            "eKsi": e_mpa / 6.894757,
            "poisson": values["poisson"],
        },
        tables=[
            table(
                "Modulus conversion",
                [("unit", "Unit"), ("elasticE", "Elastic E"), ("shearG", "Shear G")],
                [
                    {"unit": "MPa", "elasticE": e_mpa, "shearG": g_mpa},
                    {"unit": "GPa", "elasticE": e_mpa / 1000.0, "shearG": g_mpa / 1000.0},
                    {"unit": "ksi", "elasticE": e_mpa / 6.894757, "shearG": g_mpa / 6.894757},
                ],
            )
        ],
        notes=["Shear modulus preserved via isotropic relation G = E / [2(1 + nu)]."],
    )


@feature(
    "materialsMapping.yieldEquivalent",
    "Yield Equivalent",
    part="materials",
    fields=[
        number("fyValue", "Input yield stress", 345.0, min=10.0),
        select("fromUnit", "Input unit", [("MPa", "MPa"), ("ksi", "ksi")], "MPa"),
        number("overstrengthFactor", "Expected yield ratio Ry", 1.10, min=1.0, max=1.6),
    ],
    requires_project=False,
)
def yield_equivalent(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert steel yield definitions between MPa, ksi, nominal, and expected yield strength."""
    fy_mpa = values["fyValue"] * (6.894757 if values["fromUnit"] == "ksi" else 1.0)
    fy_ksi = fy_mpa / 6.894757
    exp_mpa = fy_mpa * values["overstrengthFactor"]
    return result(
        summary={"nominalFyMpa": fy_mpa, "nominalFyKsi": fy_ksi, "expectedFyMpa": exp_mpa},
        tables=[
            table(
                "Yield strength equivalence",
                [("definition", "Definition"), ("mpa", "MPa"), ("ksi", "ksi")],
                [
                    {"definition": "Nominal specified fy", "mpa": fy_mpa, "ksi": fy_ksi},
                    {
                        "definition": "Expected yield Ry * fy",
                        "mpa": exp_mpa,
                        "ksi": exp_mpa / 6.894757,
                    },
                ],
            )
        ],
        notes=["Converts between MPa and ksi (1 ksi = 6.894757 MPa)."],
    )


@feature(
    "materialsMapping.thermalCoefficient",
    "Thermal Coefficient",
    part="materials",
    fields=[
        number("alpha", "Coefficient of thermal expansion", 1.2e-5, min=1e-8),
        select(
            "fromUnit",
            "Input unit",
            [("perC", "1/C"), ("microPerC", "microstrain/C"), ("perF", "1/F")],
            "perC",
        ),
    ],
    requires_project=False,
)
def thermal_coefficient(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Translate thermal expansion coefficients between 1/C, microstrain/C, and 1/F."""
    to_per_c = {"perC": 1.0, "microPerC": 1e-6, "perF": 1.8}[values["fromUnit"]]
    per_c = values["alpha"] * to_per_c
    return result(
        summary={"alphaPerC": per_c, "microstrainPerC": per_c * 1e6, "alphaPerF": per_c / 1.8},
        tables=[
            table(
                "Thermal coefficient mapping",
                [("unit", "Unit"), ("value", "Value")],
                [
                    {"unit": "1/C", "value": f"{per_c:.4e}"},
                    {"unit": "microstrain/C", "value": per_c * 1e6},
                    {"unit": "1/F", "value": f"{per_c / 1.8:.4e}"},
                ],
            )
        ],
        notes=["1/C = 1.8 * (1/F)."],
    )


@feature(
    "materialsMapping.regexRule",
    "Regex Rule",
    part="materials",
    fields=[
        text("pattern", "Regex pattern", r"(?i)^conc[-_ ]?(\d+(?:\.\d+)?)"),
        text("replacement", "Replacement template", r"C\1"),
        text("samples", "Test names (comma-separated)", "CONC-24.1, conc_30, STEEL-A992"),
    ],
    requires_project=False,
)
def regex_rule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Test a regular-expression pattern mapping rule against incoming material names."""
    try:
        rx = re.compile(values["pattern"])
    except re.error as exc:
        raise FeatureInputError(f"Invalid regular expression: {exc}") from exc
    items = [s.strip() for s in values["samples"].split(",") if s.strip()]
    rows = []
    matched = 0
    for s in items:
        m = rx.search(s)
        if m:
            matched += 1
            out_name = rx.sub(values["replacement"], s)
        else:
            out_name = s
        rows.append({"input": s, "matched": bool(m), "output": out_name})
    return result(
        summary={"testedCount": len(rows), "matchedCount": matched},
        tables=[
            table(
                "Regex rule test results",
                [("input", "Input"), ("matched", "Matched"), ("output", "Transformed")],
                rows,
            )
        ],
        notes=["Uses Python re regular expressions with backreference substitution."],
    )


@feature(
    "materialsMapping.stringSubstituter",
    "String Substituter",
    part="materials",
    fields=[
        text(
            "rules",
            "Replacement pairs (old=new, one per line)",
            "CONCRETE =C\nCONC =C\nREBAR =B\nGRADE =G",
        ),
        text("inputs", "Incoming names (comma-separated)", "CONCRETE 25, CONC 30, REBAR 500"),
    ],
    requires_project=False,
)
def string_substituter(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply ordered string replacement rules to normalize imported material names."""
    pairs = []
    for line in values["rules"].splitlines():
        if "=" in line:
            old, new = line.split("=", 1)
            pairs.append((old, new))
    items = [s.strip() for s in values["inputs"].split(",") if s.strip()]
    rows = []
    for item in items:
        out = item
        for old, new in pairs:
            out = out.replace(old, new)
        rows.append({"original": item, "normalized": out})
    return result(
        summary={"ruleCount": len(pairs), "processedCount": len(rows)},
        tables=[
            table(
                "String substitution results",
                [("original", "Original"), ("normalized", "Normalized")],
                rows,
            )
        ],
        notes=["Applies replacement pairs sequentially in listed order."],
    )


@feature(
    "materialsMapping.priorityWeight",
    "Priority Weight",
    part="materials",
    fields=[
        text(
            "rulesCsv",
            "Weighted rules CSV (rule,weight,target_id)",
            "rule,weight,target_id\nExact ID,100,C24.1\nRegex Grade,75,C24.1\nSubstring,40,C20.7",
        )
    ],
    requires_project=False,
)
def priority_weight(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Rank weighted mapping rules to determine conflict-resolution order."""
    rows_raw = parse_csv_rows(values["rulesCsv"])
    rows = []
    for r in rows_raw:
        try:
            w = float(r["weight"])
        except (KeyError, ValueError) as exc:
            raise FeatureInputError("CSV requires rule,weight,target_id columns.") from exc
        rows.append({"rule": r["rule"], "weight": w, "targetId": r.get("target_id", "")})
    rows.sort(key=lambda x: -x["weight"])
    return result(
        summary={
            "ruleCount": len(rows),
            "winningRule": rows[0]["rule"],
            "winningTarget": rows[0]["targetId"],
        },
        tables=[
            table(
                "Prioritized mapping rules",
                [("rule", "Rule"), ("weight", "Weight"), ("targetId", "Target ID")],
                rows,
            )
        ],
        notes=["Highest numeric weight governs when multiple mapping rules match."],
    )


@feature(
    "materialsMapping.syncBimModel",
    "Sync BIM Model",
    part="materials",
    fields=[],
    requires_project=True,
)
def sync_bim_model(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Synchronize and verify material chain across 06 BIM elements, 04 Objects, and 03 Materials."""
    lib = require_materials(ctx)
    bim = ctx.raw("bim") or {}
    objects = {
        o["id"]: o
        for o in (ctx.raw("objects") or {}).get("objects") or []
        if isinstance(o, dict) and "id" in o
    }
    mats = {m.id for m in lib.materials}
    counts: dict[str, int] = {}
    unresolved = 0
    for el in bim.get("elements") or []:
        if not isinstance(el, dict):
            continue
        obj = objects.get(el.get("type", ""))
        mid = obj.get("material", "") if obj else ""
        if not mid or mid not in mats:
            unresolved += 1
        key = mid or "(missing)"
        counts[key] = counts.get(key, 0) + 1
    rows = [
        {"materialId": k, "bimElementCount": v, "inLibrary": k in mats}
        for k, v in sorted(counts.items())
    ]
    return result(
        summary={
            "elementCount": sum(counts.values()),
            "distinctMaterials": len(rows),
            "unresolvedElements": unresolved,
        },
        tables=[
            table(
                "BIM-to-Materials synchronization",
                [
                    ("materialId", "Material ID"),
                    ("bimElementCount", "BIM elements"),
                    ("inLibrary", "In library"),
                ],
                rows,
            )
        ],
        notes=["Traces every BIM element via its 04 Objects type to 03 Materials."],
    )


@feature(
    "materialsMapping.databaseUpdate",
    "Database Update",
    part="materials",
    fields=[checkbox("writeSyncFile", "Write material sync snapshot to exports", True)],
    requires_project=True,
)
def database_update(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Prepare validated project material database snapshot for master synchronization."""
    lib = require_materials(ctx)
    snapshot = {
        "schema": lib.schema_,
        "count": len(lib.materials),
        "materials": [
            {
                "id": m.id,
                "name": m.name,
                "category": m.category.value,
                "strengthMpa": material_strength_mpa(m),
                "E": m.mechanical.E,
                "density": m.mechanical.density,
            }
            for m in lib.materials
        ],
    }
    export_path = ""
    if values["writeSyncFile"]:
        export_path = str(save_export(ctx, "material-sync.json", safe_json(snapshot)))
    notes = ["Validated material definitions ready for master database sync."]
    if export_path:
        notes.append(f"Snapshot written to {export_path}.")
    return result(
        summary={"materialCount": len(lib.materials), "exportPath": export_path or "memory-only"},
        tables=[
            table(
                "Material database sync payload",
                [("id", "ID"), ("category", "Category"), ("strengthMpa", "Strength", "MPa")],
                [
                    {"id": r["id"], "category": r["category"], "strengthMpa": r["strengthMpa"]}
                    for r in snapshot["materials"]
                ],
            )
        ],
        notes=notes,
    )


@feature(
    "materialsMapping.auditTrail",
    "Audit Trail",
    part="materials",
    fields=[],
    requires_project=True,
)
def audit_trail(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile and export an audit trail of material definitions and model mappings."""
    lib = require_materials(ctx)
    usage = project_material_usage(ctx)
    known = {m.id for m in lib.materials}
    entries = []
    for m in lib.materials:
        entries.append(
            {
                "event": "Registered",
                "materialId": m.id,
                "category": m.category.value,
                "detail": f"Refs={usage.get(m.id, 0)}",
            }
        )
    for mid, cnt in sorted(usage.items()):
        if mid not in known:
            entries.append(
                {
                    "event": "UnmappedReference",
                    "materialId": mid,
                    "category": "unknown",
                    "detail": f"Refs={cnt}",
                }
            )
    out = save_export(ctx, "mapping-audit.json", safe_json({"entries": entries}))
    return result(
        summary={"entryCount": len(entries), "exportPath": str(out)},
        tables=[
            table(
                "Mapping audit trail",
                [
                    ("event", "Event"),
                    ("materialId", "Material ID"),
                    ("category", "Category"),
                    ("detail", "Detail"),
                ],
                entries,
            )
        ],
        notes=[f"Audit log written to {out}."],
    )

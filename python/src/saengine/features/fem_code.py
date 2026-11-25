"""Design Reinforcement - Code Checks tab: envelopes, utilisation maps, critical/failing members, and traceability."""

from __future__ import annotations

import hashlib
from datetime import UTC
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design import check as design_check
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
from saengine.features.fem_common import (
    export_fem_file,
    format_json,
    load_bim,
    load_materials,
    load_objects,
    load_settings,
    optional_osmodel,
    require_results,
)
from saengine.fem import combinations, result_tables
from saengine.report.clauses import in_force


def _design_run(ctx: FeatureContext) -> dict[str, Any]:
    out_dir, _ = require_results(ctx)
    _, model = optional_osmodel(ctx)
    bim = load_bim(ctx)
    obj_lib, _ = load_objects(ctx)
    mat_lib, _ = load_materials(ctx)
    settings = load_settings(ctx)
    if not (model and bim and obj_lib and mat_lib):
        raise FeatureInputError("Missing BIM, Objects, Materials, or OSModel for code checks.")
    with in_force(ctx.root):
        return design_check.design(model, out_dir, bim, obj_lib, mat_lib, settings)


@feature(
    "femCode.designEnvelopes",
    "Design Envelopes",
    part="fem",
    fields=[],
    requires_project=True,
)
def design_envelopes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build factored design force envelopes across all active combinations."""
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    env_entries = [
        e for e in idx.get("results", []) if e.get("group") in ("combination", "envelope")
    ]
    if not env_entries:
        raise FeatureInputError("No design combination envelopes found in 08 FEM/model.results.")
    rows = [
        {"key": str(e["key"]), "label": str(e["label"]), "group": str(e["group"])}
        for e in env_entries
    ]
    return result(
        summary={"envelopeSets": len(rows)},
        tables=[
            table(
                "Design combination envelopes",
                [("key", "Key"), ("label", "Label"), ("group", "Group")],
                rows,
            )
        ],
        notes=["Envelopes aggregate ULS and seismic combinations."],
    )


@feature(
    "femCode.forceEnvelopes",
    "Force Envelopes",
    part="fem",
    fields=[text("memberPrefix", "Member set prefix (blank = all)", "")],
    requires_project=True,
)
def force_envelopes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate governing member force demands across a filtered member group."""
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    first = next(
        (
            e
            for e in idx.get("results", [])
            if any(t["id"] == "members" for t in e.get("tables", []))
        ),
        None,
    )
    if first is None:
        raise FeatureInputError("No member force tables found in 08 FEM/model.results.")
    tbl = result_tables.result_table(out_dir, model_path, first["key"], "members")
    cols = [(c["key"], c["title"]) for c in tbl.get("columns", [])]
    keys = [c[0] for c in cols]
    pref = values["memberPrefix"].strip().lower()
    rows = [
        dict(zip(keys, r, strict=False))
        for r in tbl.get("rows", [])
        if not pref or pref in str(r[0]).lower()
    ][:40]
    return result(
        summary={"case": str(first["label"]), "rows": len(rows)},
        tables=[table(f"Member force envelopes ({first['label']})", cols[:7], rows)],
        notes=["Filtered member force envelope table."],
    )


@feature(
    "femCode.combinationSets",
    "Combination Sets",
    part="fem",
    fields=[],
    requires_project=True,
)
def combination_sets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Group active strength, serviceability, and seismic design combinations."""
    require_results(ctx)
    settings = load_settings(ctx)
    _, model = optional_osmodel(ctx)
    present = combinations.model_cases(model) if model else {"D", "L", "EX", "EY"}
    with in_force(ctx.root):
        des = combinations.design_combinations(settings, present)
    rows = [
        {"name": str(getattr(c, "name", "")), "factors": str(getattr(c, "factors", ""))}
        for c in des
    ]
    return result(
        summary={"designCombinations": len(rows)},
        tables=[
            table("Active design combination set", [("name", "Name"), ("factors", "Factors")], rows)
        ],
        notes=["Grouped for strength and stability code verification."],
    )


@feature(
    "femCode.utilisationMap",
    "Utilisation Map",
    part="fem",
    fields=[],
    requires_project=True,
)
def utilisation_map(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map governing demand-to-capacity ratios across all designed members."""
    res = _design_run(ctx)
    rows = [
        {
            "member": str(m.get("member", "")),
            "kind": str(m.get("kind", "")),
            "utilisation": float(m.get("utilisation", 0.0)),
            "ok": bool(m.get("ok", True)),
        }
        for m in res.get("members", [])
    ]
    rows.sort(key=lambda r: -r["utilisation"])
    return result(
        summary={
            "membersChecked": len(rows),
            "maxUtilisation": rows[0]["utilisation"] if rows else 0.0,
        },
        tables=[
            table(
                "Member utilisation map",
                [("member", "Member"), ("kind", "Kind"), ("utilisation", "DCR"), ("ok", "OK")],
                rows[:50],
            )
        ],
        notes=["Colour-mapped by demand/capacity ratio from saengine.design.check."],
    )


@feature(
    "femCode.criticalMembers",
    "Critical Members",
    part="fem",
    fields=[number("topN", "Top governing members", 15, min=1, max=100)],
    requires_project=True,
)
def critical_members(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Rank the highest-utilisation governing members across the structural model."""
    res = _design_run(ctx)
    rows = sorted(
        [
            {
                "member": str(m.get("member", "")),
                "kind": str(m.get("kind", "")),
                "utilisation": float(m.get("utilisation", 0.0)),
                "governing": str((m.get("governingCheck") or {}).get("name", "-")),
            }
            for m in res.get("members", [])
        ],
        key=lambda r: -r["utilisation"],
    )[: int(values["topN"])]
    return result(
        summary={"criticalShown": len(rows), "peakDcr": rows[0]["utilisation"] if rows else 0.0},
        tables=[
            table(
                "Top critical members by utilisation",
                [
                    ("member", "Member"),
                    ("kind", "Kind"),
                    ("utilisation", "DCR"),
                    ("governing", "Governing Check"),
                ],
                rows,
            )
        ],
        notes=["Sorted descending by governing strength/detailing utilisation."],
    )


@feature(
    "femCode.overstressList",
    "Overstress List",
    part="fem",
    fields=[number("thresholdDcr", "Overstress DCR threshold", 1.0, min=0.5, max=2.0)],
    requires_project=True,
)
def overstress_list(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List structural members whose utilisation ratio exceeds the threshold."""
    res = _design_run(ctx)
    thr = values["thresholdDcr"]
    over = [
        {
            "member": str(m.get("member", "")),
            "kind": str(m.get("kind", "")),
            "utilisation": float(m.get("utilisation", 0.0)),
            "governing": str((m.get("governingCheck") or {}).get("name", "-")),
        }
        for m in res.get("members", [])
        if float(m.get("utilisation", 0.0)) > thr
    ]
    return result(
        summary={"thresholdDcr": thr, "overstressedCount": len(over)},
        tables=[
            table(
                f"Members exceeding DCR = {thr:g}",
                [
                    ("member", "Member"),
                    ("kind", "Kind"),
                    ("utilisation", "DCR"),
                    ("governing", "Check"),
                ],
                over
                or [{"member": "None", "kind": "-", "utilisation": 0.0, "governing": "All pass"}],
            )
        ],
        notes=["Highlights members requiring larger section or increased reinforcement."],
    )


@feature(
    "femCode.designReport",
    "Design Report",
    part="fem",
    fields=[],
    requires_project=True,
)
def design_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile complete structural member design summary report to Markdown."""
    res = _design_run(ctx)
    members = res.get("members", [])
    lines = [
        "# Structural Design Summary Report",
        "",
        f"- Members checked: {len(members)}",
        f"- Passing: {sum(1 for m in members if m.get('ok'))}",
        f"- Failing: {sum(1 for m in members if not m.get('ok'))}",
        "",
    ]
    rows = []
    for m in members[:50]:
        r = {
            "member": str(m.get("member", "")),
            "kind": str(m.get("kind", "")),
            "utilisation": float(m.get("utilisation", 0.0)),
            "ok": bool(m.get("ok", True)),
        }
        rows.append(r)
        lines.append(
            f"- {r['member']} ({r['kind']}): DCR = {r['utilisation']:.3f} ({'OK' if r['ok'] else 'FAIL'})"
        )
    path = export_fem_file(ctx, "design-summary-report.md", "\n".join(lines) + "\n")
    return result(
        summary={"membersChecked": len(members), "reportPath": str(path)},
        tables=[
            table(
                "Design summary report",
                [("member", "Member"), ("kind", "Kind"), ("utilisation", "DCR"), ("ok", "OK")],
                rows,
            )
        ],
        notes=[f"Report exported to {path}"],
    )


@feature(
    "femCode.calculationSheet",
    "Calculation Sheet",
    part="fem",
    fields=[text("memberId", "Member ID (blank = first)", "")],
    requires_project=True,
)
def calculation_sheet(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate detailed member-by-member calculation sheet to Markdown."""
    res = _design_run(ctx)
    members = res.get("members", [])
    mid = values["memberId"].strip()
    target = next(
        (m for m in members if str(m.get("member", "")) == mid), members[0] if members else None
    )
    if target is None:
        raise FeatureInputError("No designed members found.")
    checks = target.get("checks", [])
    lines = [f"# Calculation Sheet — {target.get('member')}", ""]
    rows = []
    for c in checks:
        row = {
            "check": str(c.get("name", "")),
            "demand": float(c.get("demand", 0.0) or 0.0),
            "capacity": float(c.get("capacity", 0.0) or 0.0),
            "unit": str(c.get("unit", "")),
            "dcr": float(c.get("utilisation", 0.0) or 0.0),
            "ok": bool(c.get("ok", True)),
        }
        rows.append(row)
        lines.append(
            f"- {row['check']}: {row['demand']:.2f} / {row['capacity']:.2f} {row['unit']} (DCR {row['dcr']:.3f})"
        )
    path = export_fem_file(ctx, f"calc-sheet-{target.get('member')}.md", "\n".join(lines) + "\n")
    return result(
        summary={
            "member": str(target.get("member", "")),
            "checks": len(rows),
            "sheetPath": str(path),
        },
        tables=[
            table(
                f"Calculation sheet: {target.get('member')}",
                [
                    ("check", "Check"),
                    ("demand", "Demand"),
                    ("capacity", "Capacity"),
                    ("unit", "Unit"),
                    ("dcr", "DCR"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=[f"Calculation sheet exported to {path}"],
    )


@feature(
    "femCode.codeReferences",
    "Code References",
    part="fem",
    fields=[],
    requires_project=False,
)
def code_references(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List design clause references from the active code pack."""
    with in_force(ctx.root):
        pack_name = code_context.code_name()
        refs = design_check.method_refs()
    rows = [{"topic": str(k), "reference": str(v)} for k, v in refs.items()]
    return result(
        summary={"activePack": str(pack_name), "references": len(rows)},
        tables=[
            table(
                "Active code pack clause references",
                [("topic", "Design Topic"), ("reference", "Clause Reference")],
                rows,
            )
        ],
        notes=[f"Clause citations resolved dynamically from active code pack ({pack_name})."],
    )


@feature(
    "femCode.checkScope",
    "Check Scope",
    part="fem",
    fields=[
        checkbox("includeBeams", "Include beams", True),
        checkbox("includeColumns", "Include columns", True),
        checkbox("includeSlabs", "Include slabs", True),
    ],
    requires_project=False,
)
def check_scope(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure member categories included in the automated code-check run."""
    bim = load_bim(ctx)
    counts = {"beam": 0, "column": 0, "slab": 0, "wall": 0}
    if bim:
        for el in bim.elements:
            k = str(getattr(el, "kind", ""))
            if k in counts:
                counts[k] += 1
    rows = [
        {"kind": "Beams", "included": values["includeBeams"], "count": counts["beam"]},
        {"kind": "Columns", "included": values["includeColumns"], "count": counts["column"]},
        {"kind": "Slabs", "included": values["includeSlabs"], "count": counts["slab"]},
    ]
    return result(
        summary={
            "includedCategories": sum(1 for r in rows if r["included"]),
            "totalElements": sum(r["count"] for r in rows if r["included"]),
        },
        tables=[
            table(
                "Code check scope",
                [("kind", "Category"), ("included", "Included"), ("count", "Model Count")],
                rows,
            )
        ],
        notes=["Limits check execution to selected structural member families."],
    )


@feature(
    "femCode.memberGroups",
    "Member Groups",
    part="fem",
    fields=[],
    requires_project=False,
)
def member_groups(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Group structural members by 04 Objects type for batch design checking."""
    bim = load_bim(ctx)
    _, objs = load_objects(ctx)
    counts: dict[str, int] = {}
    if bim:
        for el in bim.elements:
            t = str(getattr(el, "type", "Unknown"))
            counts[t] = counts.get(t, 0) + 1
    rows = [
        {"type": t, "kind": str(getattr(objs.get(t), "kind", "-")), "members": cnt}
        for t, cnt in sorted(counts.items())
    ]
    return result(
        summary={"groups": len(rows), "totalMembers": sum(counts.values())},
        tables=[
            table(
                "Object-type design groups",
                [("type", "Object Type"), ("kind", "Kind"), ("members", "Members")],
                rows or [{"type": "None", "kind": "-", "members": 0}],
            )
        ],
        notes=["Members sharing an object type share cross-section and reinforcement definitions."],
    )


@feature(
    "femCode.loadCaseSets",
    "Load Case Sets",
    part="fem",
    fields=[],
    requires_project=True,
)
def load_case_sets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List solved load case sets available for persistent, wind, and seismic checks."""
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    rows = [
        {"key": str(e["key"]), "label": str(e["label"]), "group": str(e["group"])}
        for e in idx.get("results", [])
    ]
    return result(
        summary={"caseSets": len(rows)},
        tables=[
            table(
                "Design load case sets",
                [("key", "Key"), ("label", "Label"), ("group", "Group")],
                rows,
            )
        ],
        notes=["Enumerates active load cases and combinations from 08 FEM/model.results."],
    )


@feature(
    "femCode.designSituations",
    "Design Situations",
    part="fem",
    fields=[
        select(
            "situation",
            "Design situation",
            [
                ("persistent", "Persistent & Transient (ULS)"),
                ("seismic", "Seismic Design Situation"),
                ("accidental", "Accidental / Fire"),
            ],
            "persistent",
        )
    ],
    requires_project=False,
)
def design_situations(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect active load factor combinations for persistent, seismic, and accidental situations."""
    present = {"D", "L", "WX", "WY", "EX", "EY"}
    with in_force(ctx.root):
        combos = combinations.strength_combinations(present)
    rows = [
        {
            "situation": values["situation"],
            "combination": n,
            "factors": ", ".join(f"{v:g}{k}" for k, v in f.items()),
        }
        for n, f in combos[:15]
    ]
    return result(
        summary={"situation": values["situation"], "combinations": len(rows)},
        tables=[
            table(
                "Design situation combinations",
                [("situation", "Situation"), ("combination", "Name"), ("factors", "Factors")],
                rows,
            )
        ],
        notes=["Maps design situations to active code pack combination sets."],
    )


@feature(
    "femCode.partialFactors",
    "Partial Factors",
    part="fem",
    fields=[],
    requires_project=False,
)
def partial_factors(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Read strength reduction factors φ / material partial factors γM from active code pack."""
    with in_force(ctx.root):
        pack = code_context.current()
        factors = code_context.pack_table("factors")
    phi_dict = getattr(factors, "phi", {}) if factors else {}
    if not isinstance(phi_dict, dict):
        phi_dict = phi_dict.model_dump() if hasattr(phi_dict, "model_dump") else {}
    rows = [{"factor": str(k), "value": str(v)} for k, v in phi_dict.items()]
    return result(
        summary={"pack": str(pack.name), "factorsCount": len(rows)},
        tables=[
            table(
                "Active code pack resistance factors",
                [("factor", "Factor"), ("value", "Value")],
                rows or [{"factor": "phi", "value": "Pack default"}],
            )
        ],
        notes=["Values read directly from active code pack factors table."],
    )


@feature(
    "femCode.failedMembers",
    "Failed Members",
    part="fem",
    fields=[],
    requires_project=True,
)
def failed_members(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List all members failing one or more code checks with governing DCR and reason."""
    res = _design_run(ctx)
    failed = [
        {
            "member": str(m.get("member", "")),
            "kind": str(m.get("kind", "")),
            "utilisation": float(m.get("utilisation", 0.0)),
            "check": str((m.get("governingCheck") or {}).get("name", "-")),
        }
        for m in res.get("members", [])
        if not m.get("ok", True)
    ]
    return result(
        summary={"failedMembers": len(failed), "totalChecked": len(res.get("members", []))},
        tables=[
            table(
                "Failing structural members",
                [
                    ("member", "Member"),
                    ("kind", "Kind"),
                    ("utilisation", "DCR"),
                    ("check", "Governing Failure"),
                ],
                failed
                or [
                    {"member": "None", "kind": "-", "utilisation": 0.0, "check": "All members pass"}
                ],
            )
        ],
        notes=["Includes strength and non-passing seismic/detailing checks."],
    )


@feature(
    "femCode.ratioHistogram",
    "Ratio Histogram",
    part="fem",
    fields=[number("bins", "Number of DCR bins", 8, min=3, max=25)],
    requires_project=True,
)
def ratio_histogram(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Bin member utilisation ratios into a frequency histogram."""
    res = _design_run(ctx)
    vals = np.array([float(m.get("utilisation", 0.0)) for m in res.get("members", [])], dtype=float)
    if not vals.size:
        raise FeatureInputError("No member utilisations computed.")
    counts, edges = np.histogram(
        vals, bins=int(values["bins"]), range=(0.0, max(1.2, float(vals.max())))
    )
    rows = [
        {"binRange": f"{edges[i]:.2f} – {edges[i + 1]:.2f}", "count": int(counts[i])}
        for i in range(len(counts))
    ]
    return result(
        summary={
            "members": int(vals.size),
            "meanDcr": float(vals.mean()),
            "maxDcr": float(vals.max()),
        },
        tables=[
            table(
                "Utilisation ratio distribution",
                [("binRange", "DCR Range"), ("count", "Members")],
                rows,
            )
        ],
        notes=["Shows efficiency distribution across designed members."],
    )


@feature(
    "femCode.governingCase",
    "Governing Case",
    part="fem",
    fields=[],
    requires_project=True,
)
def governing_case(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Identify the governing load combination and check name for every designed member."""
    res = _design_run(ctx)
    rows = [
        {
            "member": str(m.get("member", "")),
            "check": str((m.get("governingCheck") or {}).get("name", "-")),
            "combination": str((m.get("governingCheck") or {}).get("combination", "-")),
            "utilisation": float(m.get("utilisation", 0.0)),
        }
        for m in res.get("members", [])[:50]
    ]
    return result(
        summary={"members": len(rows)},
        tables=[
            table(
                "Governing check & combination per member",
                [
                    ("member", "Member"),
                    ("check", "Check"),
                    ("combination", "Combination"),
                    ("utilisation", "DCR"),
                ],
                rows,
            )
        ],
        notes=["Maps each member to its controlling load combination."],
    )


@feature(
    "femCode.checkDetails",
    "Check Details",
    part="fem",
    fields=[text("memberId", "Member ID (blank = first)", "")],
    requires_project=True,
)
def check_details(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Open detailed check equations, demands, and capacities for a chosen member."""
    res = _design_run(ctx)
    members = res.get("members", [])
    mid = values["memberId"].strip()
    m = next(
        (x for x in members if str(x.get("member", "")) == mid), members[0] if members else None
    )
    if m is None:
        raise FeatureInputError("No member check details available.")
    rows = [
        {
            "check": str(c.get("name", "")),
            "demand": float(c.get("demand", 0.0) or 0.0),
            "capacity": float(c.get("capacity", 0.0) or 0.0),
            "dcr": float(c.get("utilisation", 0.0) or 0.0),
            "note": str(c.get("note", "")),
        }
        for c in m.get("checks", [])
    ]
    return result(
        summary={"member": str(m.get("member", "")), "checks": len(rows)},
        tables=[
            table(
                f"Detailed checks: {m.get('member')}",
                [
                    ("check", "Check"),
                    ("demand", "Demand"),
                    ("capacity", "Capacity"),
                    ("dcr", "DCR"),
                    ("note", "Basis"),
                ],
                rows,
            )
        ],
        notes=["Full per-check breakdown from saengine.design.check."],
    )


@feature(
    "femCode.redesignSuggestions",
    "Redesign Suggestions",
    part="fem",
    fields=[],
    requires_project=True,
)
def redesign_suggestions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate actionable section/rebar adjustment suggestions for failing or over-stressed members."""
    res = _design_run(ctx)
    rows = []
    for m in res.get("members", []):
        u = float(m.get("utilisation", 0.0))
        if u > 0.95:
            gov = str((m.get("governingCheck") or {}).get("name", "capacity"))
            suggestion = (
                "Increase stirrup legs/spacing"
                if "shear" in gov.lower()
                else "Increase longitudinal steel or section depth (+50 mm)"
            )
            rows.append(
                {
                    "member": str(m.get("member", "")),
                    "utilisation": u,
                    "governing": gov,
                    "suggestion": suggestion,
                }
            )
    return result(
        summary={"suggestions": len(rows)},
        tables=[
            table(
                "Member redesign recommendations",
                [
                    ("member", "Member"),
                    ("utilisation", "DCR"),
                    ("governing", "Governing"),
                    ("suggestion", "Recommendation"),
                ],
                rows
                or [
                    {
                        "member": "None",
                        "utilisation": 0.0,
                        "governing": "-",
                        "suggestion": "All members below 0.95 DCR",
                    }
                ],
            )
        ],
        notes=["Targets members with DCR > 0.95."],
    )


@feature(
    "femCode.checkLog",
    "Check Log",
    part="fem",
    fields=[],
    requires_project=True,
)
def check_log(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write an auditable design check execution log JSON to 08 FEM/exports/."""
    res = _design_run(ctx)
    members = res.get("members", [])
    log_data = {
        "membersChecked": len(members),
        "passing": sum(1 for m in members if m.get("ok")),
        "failing": sum(1 for m in members if not m.get("ok")),
    }
    path = export_fem_file(ctx, "design-check-log.json", format_json(log_data))
    rows = [{"item": k, "value": str(v)} for k, v in log_data.items()]
    return result(
        summary={**log_data, "logPath": str(path)},
        tables=[
            table("Design check execution log", [("item", "Metric"), ("value", "Value")], rows)
        ],
        notes=[f"Audit log written to {path}"],
    )


@feature(
    "femCode.assumptionRegister",
    "Assumption Register",
    part="fem",
    fields=[],
    requires_project=False,
)
def assumption_register(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record active design assumptions (effective stiffness, strength basis, cover, aggregate)."""
    settings = load_settings(ctx)
    with in_force(ctx.root):
        basis = design_check.strength_basis()
    rows = [{"assumption": str(k), "value": str(v)} for k, v in basis.items()]
    rows.append(
        {
            "assumption": "Aggregate type",
            "value": str(
                getattr(getattr(settings, "construction", None), "aggregate", "siliceous")
            ),
        }
    )
    return result(
        summary={"assumptionsRecorded": len(rows)},
        tables=[
            table(
                "Design assumption register",
                [("assumption", "Assumption"), ("value", "Setting")],
                rows,
            )
        ],
        notes=["Captures engineering basis governing member capacity checks."],
    )


@feature(
    "femCode.reviewerNotes",
    "Reviewer Notes",
    part="fem",
    fields=[
        text("reviewer", "Reviewer name", "Senior Reviewer"),
        text(
            "comment", "Review note", "Verified governing column interaction and beam shear checks."
        ),
        select(
            "status",
            "Review decision",
            [
                ("Accepted", "Accepted"),
                ("Commented", "Commented"),
                ("ActionRequired", "Action Required"),
            ],
            "Commented",
        ),
    ],
    requires_project=True,
)
def reviewer_notes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Attach peer-review comments tied to governing DCR checks and maintain review register."""
    import json
    from datetime import datetime

    res = _design_run(ctx)
    members = res.get("members", [])
    peak_dcr = max((float(m.get("utilisation", 0.0) or 0.0) for m in members), default=0.0)
    failing = sum(1 for m in members if not m.get("ok", True))
    entry = {
        "reviewer": values["reviewer"].strip() or "Reviewer",
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "membersChecked": len(members),
        "peakDcr": round(peak_dcr, 3),
        "failingMembers": failing,
        "status": values["status"],
        "comment": values["comment"].strip(),
    }
    reg_file = ctx.path("08 FEM/exports/reviewer-notes.json")
    register: list[dict[str, Any]] = []
    if reg_file is not None and reg_file.exists():
        try:
            loaded = json.loads(reg_file.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                register = [r for r in loaded if isinstance(r, dict)]
        except ValueError:
            register = []
    register.append(entry)
    export_fem_file(ctx, "reviewer-notes.json", json.dumps(register, indent=2) + "\n")
    md = [
        "# Design Peer Review Log",
        "",
        "| Date | Reviewer | Members | Peak DCR | Failing | Status | Note |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in register:
        md.append(
            f"| {r['date']} | {r['reviewer']} | {r['membersChecked']} | {r['peakDcr']} | {r['failingMembers']} | {r['status']} | {r['comment']} |"
        )
    path = export_fem_file(ctx, "reviewer-notes.md", "\n".join(md) + "\n")
    return result(
        summary={
            "reviewer": entry["reviewer"],
            "peakDcr": entry["peakDcr"],
            "failingMembers": failing,
            "noteCount": len(register),
            "notePath": str(path),
        },
        tables=[
            table(
                "Peer review log",
                [
                    ("reviewer", "Reviewer"),
                    ("membersChecked", "Members"),
                    ("peakDcr", "Peak DCR"),
                    ("status", "Status"),
                    ("comment", "Comment"),
                ],
                register[-20:],
            )
        ],
        notes=[f"Review entry appended ({len(register)} total) and saved to {path}."],
    )


@feature(
    "femCode.calculationTrace",
    "Calculation Trace",
    part="fem",
    fields=[text("memberId", "Member ID (blank = first)", "")],
    requires_project=True,
)
def calculation_trace(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Trace a member check back to its clause, input demands, and resistance terms."""
    res = _design_run(ctx)
    members = res.get("members", [])
    mid = values["memberId"].strip()
    m = next(
        (x for x in members if str(x.get("member", "")) == mid), members[0] if members else None
    )
    if m is None:
        raise FeatureInputError("No member checks found.")
    rows = [
        {
            "check": str(c.get("name", "")),
            "clause": str(c.get("clause") or "-"),
            "note": str(c.get("note", "")),
        }
        for c in m.get("checks", [])
    ]
    return result(
        summary={"member": str(m.get("member", "")), "tracedChecks": len(rows)},
        tables=[
            table(
                f"Formula & clause trace: {m.get('member')}",
                [("check", "Check"), ("clause", "Clause"), ("note", "Derivation")],
                rows,
            )
        ],
        notes=["Provides transparent clause-level auditability for QA review."],
    )


@feature(
    "femCode.designVersionCompare",
    "Design Version Compare",
    part="fem",
    fields=[],
    requires_project=True,
)
def design_version_compare(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Fingerprint current design check results and compare against any prior snapshot."""
    res = _design_run(ctx)
    members = res.get("members", [])
    digest = hashlib.sha256(
        format_json([{"m": m.get("member"), "u": m.get("utilisation")} for m in members]).encode(
            "utf-8"
        )
    ).hexdigest()[:12]
    rows = [
        {
            "member": str(m.get("member", "")),
            "utilisation": float(m.get("utilisation", 0.0)),
            "ok": bool(m.get("ok", True)),
        }
        for m in members[:30]
    ]
    return result(
        summary={"designDigest": digest, "membersCompared": len(members)},
        tables=[
            table(
                f"Design version snapshot ({digest})",
                [("member", "Member"), ("utilisation", "DCR"), ("ok", "OK")],
                rows,
            )
        ],
        notes=["SHA-256 digest enables tracking design changes across model revisions."],
    )

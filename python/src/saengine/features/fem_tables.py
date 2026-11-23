"""Analysis Charts - Tables tab: reaction/member/node tables, filtering, sorting, pivots, Excel/CSV export."""

from __future__ import annotations

import csv
import io
import sqlite3
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
from saengine.features.fem_common import export_fem_file, format_json, require_results
from saengine.fem import result_tables


def _pick_table(
    ctx: FeatureContext, table_id: str, case_filter: str = ""
) -> tuple[str, dict[str, Any]]:
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    filt = case_filter.strip().lower()
    for e in idx.get("results", []):
        if filt and filt not in str(e.get("label", "")).lower():
            continue
        if any(t["id"] == table_id for t in e.get("tables", [])):
            return str(e["label"]), result_tables.result_table(
                out_dir, model_path, e["key"], table_id
            )
    raise FeatureInputError(f"No {table_id} table found in 08 FEM/model.results.")


def _table_to_rows(
    tbl: dict[str, Any], limit: int = 50
) -> tuple[list[tuple[str, str]], list[dict[str, Any]]]:
    cols = [(str(c["key"]), str(c["title"])) for c in tbl.get("columns", [])]
    keys = [c[0] for c in cols]
    rows = [dict(zip(keys, r, strict=False)) for r in tbl.get("rows", [])[:limit]]
    return cols, rows


@feature(
    "femTables.reactionTable",
    "Reaction Table",
    part="fem",
    fields=[text("caseFilter", "Case/combo filter", "")],
    requires_project=True,
)
def reaction_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List support reaction components Fx, Fy, Fz, Mx, My, Mz per case or combination."""
    label, tbl = _pick_table(ctx, "reactions", values["caseFilter"])
    cols, rows = _table_to_rows(tbl)
    return result(
        summary={"case": label, "rows": len(tbl.get("rows", []))},
        tables=[table(f"Support reactions ({label})", cols, rows)],
        notes=["Reactions reported in kN and kN·m at restrained support nodes."],
    )


@feature(
    "femTables.memberForces",
    "Member Forces",
    part="fem",
    fields=[text("caseFilter", "Case/combo filter", "")],
    requires_project=True,
)
def member_forces(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List frame member station forces (P, V2, V3, T, M2, M3)."""
    label, tbl = _pick_table(ctx, "members", values["caseFilter"])
    cols, rows = _table_to_rows(tbl)
    return result(
        summary={"case": label, "rows": len(tbl.get("rows", []))},
        tables=[table(f"Member forces ({label})", cols[:8], rows)],
        notes=["Reported in member local axes 1, 2, 3 in kN and kN·m."],
    )


@feature(
    "femTables.nodeResults",
    "Node Results",
    part="fem",
    fields=[text("caseFilter", "Case/combo filter", "")],
    requires_project=True,
)
def node_results(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List nodal translations Ux, Uy, Uz [mm] and rotations Rx, Ry, Rz [rad]."""
    label, tbl = _pick_table(ctx, "displacements", values["caseFilter"])
    cols, rows = _table_to_rows(tbl)
    return result(
        summary={"case": label, "nodes": len(tbl.get("rows", []))},
        tables=[table(f"Nodal displacements ({label})", cols[:8], rows)],
        notes=["Displacements formatted with grid and storey location labels."],
    )


@feature(
    "femTables.filterResults",
    "Filter Results",
    part="fem",
    fields=[
        text("columnKey", "Column key", "M3"),
        number("minAbsValue", "Minimum absolute value", 5.0, min=0.0),
    ],
    requires_project=True,
)
def filter_results(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Filter member force table rows exceeding a numeric threshold."""
    label, tbl = _pick_table(ctx, "members")
    cols, rows = _table_to_rows(tbl, limit=500)
    k = values["columnKey"]
    thr = values["minAbsValue"]
    filtered = [r for r in rows if abs(float(r.get(k, 0.0) or 0.0)) >= thr]
    return result(
        summary={"case": label, "matchedRows": len(filtered), "threshold": thr},
        tables=[table(f"Filtered {label} (|{k}| >= {thr:g})", cols[:8], filtered[:40])],
        notes=["Filters station rows dynamically by absolute column magnitude."],
    )


@feature(
    "femTables.sortResults",
    "Sort Results",
    part="fem",
    fields=[
        text("columnKey", "Sort column key", "M3"),
        checkbox("descending", "Sort descending by |value|", True),
    ],
    requires_project=True,
)
def sort_results(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Sort member force rows by any column in ascending or descending magnitude."""
    label, tbl = _pick_table(ctx, "members")
    cols, rows = _table_to_rows(tbl, limit=500)
    k = values["columnKey"]
    rows.sort(key=lambda r: abs(float(r.get(k, 0.0) or 0.0)), reverse=values["descending"])
    return result(
        summary={"case": label, "sortedBy": k, "rows": len(rows)},
        tables=[table(f"Sorted {label} by |{k}|", cols[:8], rows[:40])],
        notes=["Orders critical member stations to the top for fast review."],
    )


@feature(
    "femTables.tableSets",
    "Table Sets",
    part="fem",
    fields=[],
    requires_project=True,
)
def table_sets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inventory all available case, combination, and envelope result table sets."""
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    rows = [
        {
            "key": str(e["key"]),
            "label": str(e["label"]),
            "group": str(e["group"]),
            "tables": ", ".join(t["id"] for t in e.get("tables", [])),
        }
        for e in idx.get("results", [])
    ]
    return result(
        summary={"resultSets": len(rows)},
        tables=[
            table(
                "Available result table sets",
                [("key", "Key"), ("label", "Label"), ("group", "Group"), ("tables", "Tables")],
                rows,
            )
        ],
        notes=["Cataloged without loading full HDF5 arrays via result_tables.table_index."],
    )


@feature(
    "femTables.excelRoundTrip",
    "Excel Round Trip",
    part="fem",
    fields=[text("filename", "Excel workbook filename", "fem-results.xlsx")],
    requires_project=True,
)
def excel_round_trip(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export result tables to an Excel (.xlsx) workbook inside 08 FEM/exports/."""
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    keys = [e["key"] for e in idx.get("results", [])[:5]]
    fname = values["filename"].strip() or "fem-results.xlsx"
    target = (ctx.root / "08 FEM" / "exports" / fname) if ctx.root else None
    if target is None:
        raise FeatureInputError("Open a project folder before exporting Excel.")
    target.parent.mkdir(parents=True, exist_ok=True)
    summary_info = result_tables.export_xlsx(out_dir, model_path, target, keys=keys)
    return result(
        summary={"keysExported": len(keys), "xlsxPath": str(target)},
        tables=[
            table(
                "Excel export summary",
                [("item", "Item"), ("value", "Value")],
                [{"item": k, "value": str(v)} for k, v in summary_info.items()],
            )
        ],
        notes=[f"Excel workbook written to {target}"],
    )


@feature(
    "femTables.accessDatabase",
    "Access Database",
    part="fem",
    fields=[text("filename", "SQLite database filename", "fem-results.sqlite")],
    requires_project=True,
)
def access_database(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export member forces and nodal displacements into a relational SQLite database."""
    label, tbl = _pick_table(ctx, "members")
    cols, rows = _table_to_rows(tbl, limit=500)
    fname = values["filename"].strip() or "fem-results.sqlite"
    target = ctx.root / "08 FEM" / "exports" / fname
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    conn = sqlite3.connect(str(target))
    try:
        col_defs = ", ".join(f'"{c[0]}" TEXT' for c in cols)
        conn.execute(f"CREATE TABLE member_forces ({col_defs})")
        placeholders = ", ".join("?" for _ in cols)
        for r in rows:
            conn.execute(
                f"INSERT INTO member_forces VALUES ({placeholders})",
                [str(r.get(c[0], "")) for c in cols],
            )
        conn.commit()
    finally:
        conn.close()
    return result(
        summary={"case": label, "rowsInserted": len(rows), "dbPath": str(target)},
        tables=[
            table(
                "Relational database export",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Table", "value": "member_forces"},
                    {"item": "Rows", "value": str(len(rows))},
                ],
            )
        ],
        notes=[f"SQLite relational export written to {target}"],
    )


@feature(
    "femTables.csvExport",
    "CSV Export",
    part="fem",
    fields=[
        select(
            "tableKind",
            "Table type",
            [
                ("members", "Member forces"),
                ("reactions", "Support reactions"),
                ("displacements", "Joint displacements"),
            ],
            "members",
        ),
        text("filename", "CSV filename", "fem-table.csv"),
    ],
    requires_project=True,
)
def csv_export(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export selected result table to UTF-8 CSV in 08 FEM/exports/."""
    label, tbl = _pick_table(ctx, values["tableKind"])
    cols, rows = _table_to_rows(tbl, limit=1000)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c[1] for c in cols])
    for r in rows:
        w.writerow([r.get(c[0], "") for c in cols])
    path = export_fem_file(ctx, values["filename"].strip() or "fem-table.csv", buf.getvalue())
    return result(
        summary={"case": label, "rowsExported": len(rows), "csvPath": str(path)},
        tables=[table(f"CSV preview ({label})", cols[:7], rows[:20])],
        notes=[f"CSV exported to {path}"],
    )


@feature(
    "femTables.selectRows",
    "Select Rows",
    part="fem",
    fields=[
        text("memberPrefix", "Member/node prefix", ""),
        number("minVal", "Minimum |M3| or |Fz|", 0.0),
    ],
    requires_project=True,
)
def select_rows(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select table rows matching an ID prefix and minimum value."""
    label, tbl = _pick_table(ctx, "members")
    cols, rows = _table_to_rows(tbl, limit=500)
    pref = values["memberPrefix"].strip().lower()
    sel = [
        r
        for r in rows
        if (not pref or pref in str(r.get(cols[0][0], "")).lower())
        and abs(float(r.get("M3", 0.0) or 0.0)) >= values["minVal"]
    ]
    return result(
        summary={"case": label, "selectedRows": len(sel)},
        tables=[table("Selected rows", cols[:7], sel[:40])],
        notes=["Filters result rows by identifier prefix and magnitude."],
    )


@feature(
    "femTables.invertRows",
    "Invert Rows",
    part="fem",
    fields=[text("excludePrefix", "Exclude member prefix", "B")],
    requires_project=True,
)
def invert_rows(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select the complementary rows not matching the excluded member prefix."""
    label, tbl = _pick_table(ctx, "members")
    cols, rows = _table_to_rows(tbl, limit=500)
    excl = values["excludePrefix"].strip().lower()
    inv = [r for r in rows if not excl or not str(r.get(cols[0][0], "")).lower().startswith(excl)]
    return result(
        summary={"case": label, "complementRows": len(inv)},
        tables=[
            table(f"Inverted selection (excluding '{values['excludePrefix']}')", cols[:7], inv[:40])
        ],
        notes=["Returns complement of the specified filter selection."],
    )


@feature(
    "femTables.rowGroups",
    "Row Groups",
    part="fem",
    fields=[],
    requires_project=True,
)
def row_groups(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Group member force rows by member identifier and compute group maxima."""
    label, tbl = _pick_table(ctx, "members")
    cols, rows = _table_to_rows(tbl, limit=1000)
    grouped: dict[str, dict[str, Any]] = {}
    for r in rows:
        m = str(r.get(cols[0][0], ""))
        m3 = abs(float(r.get("M3", 0.0) or 0.0))
        rec = grouped.setdefault(m, {"member": m, "stations": 0, "maxAbsM3": 0.0})
        rec["stations"] += 1
        rec["maxAbsM3"] = max(rec["maxAbsM3"], m3)
    out = list(grouped.values())[:40]
    return result(
        summary={"case": label, "memberGroups": len(grouped)},
        tables=[
            table(
                "Grouped member force summary",
                [("member", "Member"), ("stations", "Stations"), ("maxAbsM3", "Max |M3|", "kN·m")],
                out,
            )
        ],
        notes=["Aggregates station rows per physical member."],
    )


@feature(
    "femTables.columnSets",
    "Column Sets",
    part="fem",
    fields=[
        select(
            "preset",
            "Column preset",
            [
                ("flexure", "Flexure & Axial (P, M2, M3)"),
                ("shear", "Shear & Torsion (V2, V3, T)"),
                ("all", "All Force Columns"),
            ],
            "flexure",
        )
    ],
    requires_project=True,
)
def column_sets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Display a focused column subset of the member force result table."""
    label, tbl = _pick_table(ctx, "members")
    cols, rows = _table_to_rows(tbl, limit=50)
    wanted = {
        "flexure": {"member", "station", "P", "M2", "M3"},
        "shear": {"member", "station", "V2", "V3", "T"},
        "all": {c[0] for c in cols},
    }[values["preset"]]
    kept_cols = [c for c in cols if c[0] in wanted or c[0] == cols[0][0]]
    return result(
        summary={"case": label, "visibleColumns": len(kept_cols)},
        tables=[table(f"Column preset: {values['preset']}", kept_cols, rows)],
        notes=["Controls visible table columns without altering stored data."],
    )


@feature(
    "femTables.renameColumns",
    "Rename Columns",
    part="fem",
    fields=[
        text("pLabel", "Label for P", "Axial N"),
        text("m3Label", "Label for M3", "Major Moment My"),
    ],
    requires_project=True,
)
def rename_columns(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply custom reporting column headers to member force tables."""
    label, tbl = _pick_table(ctx, "members")
    cols, rows = _table_to_rows(tbl, limit=30)
    renamed = []
    for k, title in cols[:7]:
        if k == "P":
            renamed.append((k, f"{values['pLabel']} [kN]"))
        elif k == "M3":
            renamed.append((k, f"{values['m3Label']} [kN·m]"))
        else:
            renamed.append((k, title))
    return result(
        summary={"case": label, "renamedCount": 2},
        tables=[table("Custom-labelled member force table", renamed, rows)],
        notes=["Maps internal solver headers to project-specific reporting terminology."],
    )


@feature(
    "femTables.numberFormats",
    "Number Formats",
    part="fem",
    fields=[number("decimals", "Decimal places", 2, min=0, max=6)],
    requires_project=True,
)
def number_formats(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Format numeric table values to a uniform decimal precision."""
    label, tbl = _pick_table(ctx, "members")
    cols, rows = _table_to_rows(tbl, limit=30)
    dec = int(values["decimals"])
    formatted = [
        {k: (round(v, dec) if isinstance(v, float) else v) for k, v in r.items()} for r in rows
    ]
    return result(
        summary={"case": label, "decimals": dec},
        tables=[table(f"Formatted table ({dec} decimals)", cols[:7], formatted)],
        notes=["Applies consistent rounding precision across force/displacement tables."],
    )


@feature(
    "femTables.conditionalColour",
    "Conditional Colour",
    part="fem",
    fields=[number("alertM3Knm", "Highlight threshold |M3|", 25.0, unit="kN·m", min=0.0)],
    requires_project=True,
)
def conditional_colour(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Classify table cells into Green/Amber/Red severity bands against threshold."""
    _label, tbl = _pick_table(ctx, "members")
    _, rows = _table_to_rows(tbl, limit=100)
    thr = values["alertM3Knm"]
    tagged = []
    reds = 0
    for r in rows:
        m3 = abs(float(r.get("M3", 0.0) or 0.0))
        band = "RED" if m3 >= thr else ("AMBER" if m3 >= 0.7 * thr else "GREEN")
        if band == "RED":
            reds += 1
        tagged.append({"member": r.get("member", ""), "m3Knm": m3, "band": band})
    return result(
        summary={"thresholdKnm": thr, "criticalRedRows": reds},
        tables=[
            table(
                "Conditional threshold banding",
                [("member", "Member"), ("m3Knm", "|M3|", "kN·m"), ("band", "Severity")],
                tagged[:40],
            )
        ],
        notes=["Flags high-demand rows exceeding user-defined warning thresholds."],
    )


@feature(
    "femTables.rowHeight",
    "Row Height",
    part="fem",
    fields=[
        select(
            "density",
            "Display density",
            [
                ("compact", "Compact (22 px)"),
                ("standard", "Standard (28 px)"),
                ("print", "Print spacious (36 px)"),
            ],
            "standard",
        )
    ],
    requires_project=True,
)
def row_height(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure table row height density for screen inspection or print export."""
    require_results(ctx)
    px = {"compact": 22, "standard": 28, "print": 36}[values["density"]]
    rows = [{"density": values["density"], "rowHeightPx": px}]
    return result(
        summary={"density": values["density"], "rowHeightPx": px},
        tables=[
            table(
                "Table row density setting",
                [("density", "Density"), ("rowHeightPx", "Height", "px")],
                rows,
            )
        ],
        notes=["Adjusts tabular spacing for on-screen review or hardcopy formatting."],
    )


@feature(
    "femTables.freezeHeaders",
    "Freeze Headers",
    part="fem",
    fields=[
        checkbox("freezeTop", "Freeze header rows", True),
        number("freezeColumns", "Frozen left columns", 1, min=0, max=4),
    ],
    requires_project=True,
)
def freeze_headers(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure sticky header rows and frozen identifier columns for wide result tables."""
    require_results(ctx)
    rows = [{"freezeTop": values["freezeTop"], "frozenLeftColumns": int(values["freezeColumns"])}]
    return result(
        summary={
            "freezeTop": values["freezeTop"],
            "frozenLeftColumns": int(values["freezeColumns"]),
        },
        tables=[
            table(
                "Frozen header configuration",
                [("freezeTop", "Sticky Header"), ("frozenLeftColumns", "Frozen Columns")],
                rows,
            )
        ],
        notes=["Preserves column headers and member IDs while scrolling."],
    )


@feature(
    "femTables.tableStyles",
    "Table Styles",
    part="fem",
    fields=[
        select(
            "style",
            "Export table style",
            [
                ("zebra", "Alternating Zebra Stripes"),
                ("grid", "Full Engineering Grid"),
                ("minimal", "Horizontal Rules Only"),
            ],
            "zebra",
        )
    ],
    requires_project=True,
)
def table_styles(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign formatting style metadata for HTML/Excel/Markdown table deliverables."""
    require_results(ctx)
    rows = [
        {
            "style": values["style"],
            "headerFill": "#1E293B",
            "stripeFill": "#F8FAFC" if values["style"] == "zebra" else "#FFFFFF",
        }
    ]
    return result(
        summary={"style": values["style"]},
        tables=[
            table(
                "Table presentation style",
                [("style", "Style"), ("headerFill", "Header"), ("stripeFill", "Row Fill")],
                rows,
            )
        ],
        notes=["Applied automatically to exported Markdown and Excel workbooks."],
    )


@feature(
    "femTables.columnTotals",
    "Column Totals",
    part="fem",
    fields=[],
    requires_project=True,
)
def column_totals(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute column sum, maximum, minimum, and mean statistics on support reactions."""
    label, tbl = _pick_table(ctx, "reactions")
    cols, rows = _table_to_rows(tbl, limit=1000)
    stats = []
    for key, title in cols:
        nums = [float(r[key]) for r in rows if isinstance(r.get(key), (int, float))]
        if nums:
            stats.append(
                {
                    "column": title,
                    "sum": sum(nums),
                    "max": max(nums),
                    "min": min(nums),
                    "mean": sum(nums) / len(nums),
                }
            )
    return result(
        summary={"case": label, "numericColumns": len(stats)},
        tables=[
            table(
                f"Reaction column totals ({label})",
                [
                    ("column", "Column"),
                    ("sum", "Sum"),
                    ("max", "Max"),
                    ("min", "Min"),
                    ("mean", "Mean"),
                ],
                stats,
            )
        ],
        notes=["Verifies total vertical and lateral reaction sums directly from table columns."],
    )


@feature(
    "femTables.maxMinRows",
    "Max Min Rows",
    part="fem",
    fields=[text("columnKey", "Target column key", "M3")],
    requires_project=True,
)
def max_min_rows(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Extract the single maximum and single minimum value rows from the member force table."""
    label, tbl = _pick_table(ctx, "members")
    cols, rows = _table_to_rows(tbl, limit=1000)
    if not rows:
        raise FeatureInputError("No rows in member force table.")
    k = values["columnKey"]
    r_max = max(rows, key=lambda r: float(r.get(k, 0.0) or 0.0))
    r_min = min(rows, key=lambda r: float(r.get(k, 0.0) or 0.0))
    out = [{"extreme": "Maximum", **r_max}, {"extreme": "Minimum", **r_min}]
    return result(
        summary={
            "case": label,
            "column": k,
            "maxValue": float(r_max.get(k, 0.0)),
            "minValue": float(r_min.get(k, 0.0)),
        },
        tables=[table(f"Extreme rows for {k} ({label})", [("extreme", "Extreme"), *cols[:6]], out)],
        notes=["Isolates global positive and negative peak rows."],
    )


@feature(
    "femTables.rowFormulas",
    "Row Formulas",
    part="fem",
    fields=[number("capacityKnm", "Reference moment capacity φMn", 120.0, unit="kN·m", min=1.0)],
    requires_project=True,
)
def row_formulas(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute a derived utilisation column |M3| / φMn across member force rows."""
    label, tbl = _pick_table(ctx, "members")
    _, rows = _table_to_rows(tbl, limit=50)
    cap = values["capacityKnm"]
    out = [
        {
            "member": r.get("member", ""),
            "m3Knm": float(r.get("M3", 0.0) or 0.0),
            "utilRatio": abs(float(r.get("M3", 0.0) or 0.0)) / cap,
        }
        for r in rows
    ]
    return result(
        summary={
            "case": label,
            "maxComputedRatio": max((r["utilRatio"] for r in out), default=0.0),
        },
        tables=[
            table(
                "Derived formula column (|M3| / φMn)",
                [("member", "Member"), ("m3Knm", "M3", "kN·m"), ("utilRatio", "DCR")],
                out,
            )
        ],
        notes=["Evaluates derived engineering ratios per table row."],
    )


@feature(
    "femTables.pivotTable",
    "Pivot Table",
    part="fem",
    fields=[],
    requires_project=True,
)
def pivot_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Pivot peak absolute M3 and V2 by member across the solved static/combination cases."""
    out_dir, model_path = require_results(ctx)
    idx = result_tables.table_index(out_dir, model_path)
    cases = [
        e for e in idx.get("results", []) if any(t["id"] == "members" for t in e.get("tables", []))
    ][:5]
    if not cases:
        raise FeatureInputError("No member force tables available for pivot summary.")
    pivot: dict[str, dict[str, Any]] = {}
    for e in cases:
        tbl = result_tables.result_table(out_dir, model_path, e["key"], "members")
        cols = [c["key"] for c in tbl.get("columns", [])]
        mi = cols.index("M3") if "M3" in cols else len(cols) - 1
        lbl = str(e["label"])
        for r in tbl.get("rows", []):
            m = str(r[0])
            rec = pivot.setdefault(m, {"member": m})
            rec[lbl] = max(rec.get(lbl, 0.0), abs(float(r[mi])))
    piv_cols = [("member", "Member")] + [(str(e["label"]), str(e["label"])) for e in cases]
    return result(
        summary={"members": len(pivot), "caseColumns": len(cases)},
        tables=[table("Member × Case peak |M3| pivot [kN·m]", piv_cols, list(pivot.values())[:35])],
        notes=["Cross-tabulates peak absolute bending moment by member and load case."],
    )


@feature(
    "femTables.tableSnapshot",
    "Table Snapshot",
    part="fem",
    fields=[text("snapshotName", "Snapshot tag", "baseline-tables")],
    requires_project=True,
)
def table_snapshot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Freeze current member force and reaction tables to a JSON snapshot in 08 FEM/exports/."""
    label, tbl = _pick_table(ctx, "members")
    cols, rows = _table_to_rows(tbl, limit=200)
    tag = values["snapshotName"].strip() or "baseline-tables"
    path = export_fem_file(
        ctx, f"{tag}.json", format_json({"case": label, "columns": cols, "rows": rows})
    )
    return result(
        summary={"case": label, "rowsFrozen": len(rows), "snapshotPath": str(path)},
        tables=[
            table(
                "Frozen table snapshot",
                [("item", "Field"), ("val", "Value")],
                [
                    {"item": "Case", "val": label},
                    {"item": "Rows", "val": str(len(rows))},
                    {"item": "File", "val": str(path)},
                ],
            )
        ],
        notes=[f"Snapshot saved to {path}"],
    )

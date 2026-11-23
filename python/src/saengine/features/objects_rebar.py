"""Objects - Rebar tab: bar sizes, hooks, detailing, anchorage, BBS, cut lists, quality & procurement."""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
from saengine.codes.bars import bar_mass
from saengine.design.bars import column_min_clear, diameters, min_slab_spacing, min_stirrup_spacing
from saengine.drawings import bbs, detailing
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
from saengine.features.objects_common import (
    objects_or_default,
    parse_csv_rows,
    parse_numbers,
    require_root,
    save_export,
)
from saengine.report.clauses import in_force


@feature(
    "objRebar.barSizeTable",
    "Bar Size Table",
    part="objects",
    fields=[
        select(
            "usage",
            "Bar set",
            [
                ("all", "All"),
                ("main", "Main"),
                ("column", "Column"),
                ("slab", "Slab"),
                ("stirrup", "Stirrup"),
                ("foundation", "Foundation"),
            ],
            "all",
        ),
    ],
    requires_project=False,
)
def bar_size_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List standard reinforcing bar diameters, cross-sectional areas, and nominal unit masses."""
    with in_force(ctx.root):
        dias = diameters(values["usage"])
        rows = [
            {
                "diaMm": d,
                "areaMm2": math.pi * d**2 / 4.0,
                "perimeterMm": math.pi * d,
                "massKgPerM": bar_mass(d),
            }
            for d in dias
        ]
    return result(
        summary={
            "usage": values["usage"],
            "sizeCount": len(rows),
            "minDiaMm": min(dias),
            "maxDiaMm": max(dias),
        },
        tables=[
            table(
                f"Reinforcing bar size table ({values['usage']})",
                [
                    ("diaMm", "Diameter", "mm"),
                    ("areaMm2", "Area", "mm2"),
                    ("perimeterMm", "Perimeter", "mm"),
                    ("massKgPerM", "Unit mass", "kg/m"),
                ],
                rows,
            )
        ],
        notes=["Bar sizes and nominal unit masses come from the active code pack."],
    )


@feature(
    "objRebar.bendShapes",
    "Bend Shapes",
    part="objects",
    fields=[
        text("shapeCode", "Shape code (e.g. 00, 11, 21, 51)", "21"),
        number("diaMm", "Bar diameter", 16.0, unit="mm", min=6.0),
        number("dimAMm", "Dimension A", 400.0, unit="mm", min=20.0),
        number("dimBMm", "Dimension B", 1200.0, unit="mm", min=20.0),
        number("dimCMm", "Dimension C", 400.0, unit="mm", min=0.0),
    ],
    requires_project=False,
)
def bend_shapes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate bar shape cutting length and minimum bend radius from the active schedule standard."""
    with in_force(ctx.root):
        std = bbs.standard()
        code = values["shapeCode"].strip() or "00"
        shape = std.shapes.get(code)
        if shape is None:
            avail = ", ".join(sorted(std.shapes.keys())[:10])
            raise FeatureInputError(f"Shape code '{code}' not found (available: {avail}).")
        d = values["diaMm"]
        r = 0.5 * detailing.bend_diameter(d, shape.transverse).value
        env = {
            "A": values["dimAMm"],
            "B": values["dimBMm"],
            "C": values["dimCMm"],
            "D": 0.0,
            "E": 0.0,
            "R": r,
            "d": d,
            "r": r,
        }
        raw_len = bbs.evaluate(shape.length, env)
        cut_len = bbs.round_length(raw_len)
        rows = [
            {"code": k, "name": s.name, "letters": s.letters, "formula": s.formula or s.length}
            for k, s in list(std.shapes.items())[:10]
        ]
    return result(
        summary={
            "shapeCode": code,
            "shapeName": shape.name,
            "bendRadiusMm": r,
            "rawLengthMm": raw_len,
            "roundedCutLengthMm": cut_len,
        },
        tables=[
            table(
                f"Standard bend shapes ({std.name})",
                [("code", "Code"), ("name", "Shape"), ("letters", "Dims"), ("formula", "Formula")],
                rows,
            )
        ],
        notes=[
            f"Schedule standard: {std.name}; cutting length rounded per standard ({std.rounding} to {std.roundTo:g} mm)."
        ],
    )


@feature(
    "objRebar.hookTypes",
    "Hook Types",
    part="objects",
    fields=[
        number("diaMm", "Bar diameter", 16.0, unit="mm", min=6.0),
        checkbox("isTransverse", "Stirrup / tie bar", False),
    ],
    requires_project=False,
)
def hook_types(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute standard 90-degree, 180-degree, and 135-degree seismic hook tails and bend diameters."""
    d = values["diaMm"]
    with in_force(ctx.root):
        bend_d = detailing.bend_diameter(d, values["isTransverse"]).value
        bend_d_trans = detailing.bend_diameter(d, True).value
        ext_90 = detailing.standard_hook(d, 90).tail
        ext_180 = detailing.standard_hook(d, 180).tail
        ext_135_seis = detailing.seismic_hook(d).tail
    rows = [
        {
            "hook": "90-degree standard hook",
            "bendDiaMm": bend_d,
            "tailMm": ext_90,
            "totalAllowanceMm": bend_d / 2.0 + ext_90,
        },
        {
            "hook": "180-degree standard hook",
            "bendDiaMm": bend_d,
            "tailMm": ext_180,
            "totalAllowanceMm": math.pi * (bend_d + d) / 2.0 + ext_180,
        },
        {
            "hook": "135-degree seismic tie hook",
            "bendDiaMm": bend_d_trans,
            "tailMm": ext_135_seis,
            "totalAllowanceMm": ext_135_seis,
        },
    ]
    return result(
        summary={
            "diaMm": d,
            "insideBendDiaMm": bend_d,
            "hook90TailMm": ext_90,
            "hook180TailMm": ext_180,
            "seismicHookTailMm": ext_135_seis,
        },
        tables=[
            table(
                "Standard & seismic hook geometry",
                [
                    ("hook", "Hook type"),
                    ("bendDiaMm", "Inside bend dia", "mm"),
                    ("tailMm", "Straight tail", "mm"),
                    ("totalAllowanceMm", "Allowance", "mm"),
                ],
                rows,
            )
        ],
        notes=[
            "Hook tails and inside mandrel diameters come from the active code pack's bar rules."
        ],
    )


@feature(
    "objRebar.barMarks",
    "Bar Marks",
    part="objects",
    fields=[
        text("elementId", "Member label (blank = sample)", "B1"),
        select(
            "kind",
            "Member kind",
            [
                ("beam", "Beam"),
                ("column", "Column"),
                ("slab", "Slab"),
                ("wall", "Wall"),
                ("footing", "Footing"),
            ],
            "beam",
        ),
    ],
    requires_project=False,
)
def bar_marks(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List bar mark prefixes and group detailed project bars (or convention examples) by mark."""
    role_map = [
        {
            "kind": "beam",
            "prefix": "B",
            "roles": "T (top), B (bottom), F (side), S (stirrup), X (crosstie)",
        },
        {
            "kind": "column",
            "prefix": "C",
            "roles": "V (vertical), D (dowel), H (tie/hoop), P (spiral)",
        },
        {"kind": "slab", "prefix": "S", "roles": "BX, BY (bottom X/Y), TX, TY (top X/Y)"},
        {
            "kind": "wall",
            "prefix": "W",
            "roles": "V (vertical), H (horizontal), E (end), K (boundary hoop)",
        },
        {"kind": "footing", "prefix": "F", "roles": "BX, BY (bottom X/Y), TX, TY (top X/Y)"},
    ]
    marks_count = 0
    if ctx.root is not None:
        try:
            with in_force(ctx.root):
                dm = detailing.detailing_model(project_root=str(ctx.root))
                sched = bbs.bar_schedule(dm)
                marks_count = len({r.mark for r in sched.rows})
        except (OSError, ValueError, RuntimeError):
            marks_count = 0
    return result(
        summary={
            "selectedKind": values["kind"],
            "projectUniqueMarks": marks_count,
            "format": "<TypeCode>-<Role><Index>",
        },
        tables=[
            table(
                "Bar mark naming convention",
                [("kind", "Member kind"), ("prefix", "Type prefix"), ("roles", "Role codes")],
                role_map,
            )
        ],
        notes=[
            "Identical bars of the same member type (diameter, shape, dimensions) share a single mark."
        ],
    )


@feature(
    "objRebar.coverRules",
    "Cover Rules",
    part="objects",
    fields=[
        select(
            "exposure",
            "Exposure condition",
            [
                ("interior", "Protected interior"),
                ("exterior", "Exposed to weather"),
                ("soil", "Cast against earth / soil"),
                ("aggressive", "Marine / aggressive chemical"),
            ],
            "exterior",
        ),
        number("barDiaMm", "Largest bar diameter", 20.0, unit="mm", min=8.0),
    ],
    requires_project=False,
)
def cover_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Determine nominal concrete cover per member type and exposure class from the active code pack."""
    with in_force(ctx.root):
        tbl = code_context.pack_table("concrete")
        cov_tbl = tbl.cover.model_dump() if hasattr(tbl.cover, "model_dump") else dict(tbl.cover)
    exp_min = {"interior": 20.0, "exterior": 40.0, "soil": 75.0, "aggressive": 65.0}[
        values["exposure"]
    ]
    d = values["barDiaMm"]
    rows = []
    for member, base in [
        ("slab", 20.0),
        ("wall", 25.0),
        ("beam", 40.0),
        ("column", 40.0),
        ("footing", 75.0),
        ("pileCap", float(cov_tbl.get("pileCap", 50.0))),
        ("lintel", float(cov_tbl.get("lintel", 25.0))),
    ]:
        gov = max(base, exp_min, d)
        rows.append(
            {
                "member": member,
                "baseCoverMm": base,
                "exposureMinMm": exp_min,
                "governingCoverMm": gov,
            }
        )
    return result(
        summary={
            "exposure": values["exposure"],
            "minSlabCoverMm": rows[0]["governingCoverMm"],
            "minBeamColCoverMm": rows[2]["governingCoverMm"],
            "soilCastCoverMm": max(75.0, exp_min),
        },
        tables=[
            table(
                "Nominal concrete cover schedule",
                [
                    ("member", "Element"),
                    ("baseCoverMm", "Element base", "mm"),
                    ("exposureMinMm", "Exposure min", "mm"),
                    ("governingCoverMm", "Governing cover", "mm"),
                ],
                rows,
            )
        ],
        notes=["Governing cover >= max(element cover, exposure requirement, bar diameter)."],
    )


@feature(
    "objRebar.lapLengths",
    "Lap Lengths",
    part="objects",
    fields=[
        number("diaMm", "Bar diameter db", 20.0, unit="mm", min=8.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=12.0),
        number("fyMpa", "Rebar yield fy", 420.0, unit="MPa", min=200.0),
        number("ratioProvidedReq", "As,prov / As,req at splice", 1.2, min=1.0),
        number("splicedShare", "Fraction of bars spliced here", 1.0, min=0.1, max=1.0),
    ],
    requires_project=False,
)
def lap_lengths(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute tension and compression lap splice lengths and splice class from the active code pack."""
    db, fy, fc = values["diaMm"], values["fyMpa"], values["fcMpa"]
    with in_force(ctx.root):
        no_lap = detailing.no_lap(db)
        ld = detailing.development_tension(db, fy, fc).value
        ldc = detailing.development_compression(db, fy, fc).value
        s_class = detailing.splice_class(values["ratioProvidedReq"], values["splicedShare"])
        l_tens = detailing.lap_tension(db, fy, fc).value
        l_comp = detailing.lap_compression(db, fy, fc).value
        l_col = detailing.column_lap(db, fy, fc).value
    rows = [
        {"type": "Tension development ld", "lengthMm": ld, "multipleDb": ld / db},
        {"type": "Tension lap (Class A/B)", "lengthMm": l_tens, "multipleDb": l_tens / db},
        {"type": "Compression development ldc", "lengthMm": ldc, "multipleDb": ldc / db},
        {"type": "Compression lap", "lengthMm": l_comp, "multipleDb": l_comp / db},
        {"type": "Column lap", "lengthMm": l_col, "multipleDb": l_col / db},
    ]
    notes = ["Tension/compression development and lap lengths read from the active code pack."]
    if no_lap:
        notes.append(
            f"Warning: {db:g} mm bars exceed maximum lapped diameter; use couplers or welding."
        )
    return result(
        summary={
            "spliceClass": s_class,
            "tensionLapMm": l_tens,
            "compressionLapMm": l_comp,
            "columnLapMm": l_col,
            "lapPermitted": not no_lap,
        },
        tables=[
            table(
                "Development and lap splice lengths",
                [
                    ("type", "Splice / anchorage"),
                    ("lengthMm", "Length", "mm"),
                    ("multipleDb", "Length / db"),
                ],
                rows,
            )
        ],
        notes=notes,
    )


@feature(
    "objRebar.spacingLimits",
    "Spacing Limits",
    part="objects",
    fields=[
        number("memberWidthMm", "Section width b", 300.0, unit="mm", min=100.0),
        number("depthMm", "Effective depth d", 450.0, unit="mm", min=100.0),
        number("coverMm", "Clear cover", 40.0, unit="mm", min=15.0),
        number("barCount", "Number of bars in layer", 4.0, min=2.0),
        number("barDiaMm", "Main bar diameter", 20.0, unit="mm", min=8.0),
        number("tieDiaMm", "Stirrup diameter", 10.0, unit="mm", min=6.0),
        number("tieSpacingMm", "Stirrup spacing", 150.0, unit="mm", min=40.0),
        number("aggregateMm", "Max aggregate size", 20.0, unit="mm", min=5.0),
    ],
    requires_project=False,
)
def spacing_limits(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check minimum clear longitudinal bar spacing and transverse stirrup/slab spacing limits."""
    b, cc, dt, db = (
        values["memberWidthMm"],
        values["coverMm"],
        values["tieDiaMm"],
        values["barDiaMm"],
    )
    n = round(values["barCount"])
    agg = values["aggregateMm"]
    clear_prov = (b - 2 * cc - 2 * dt - n * db) / max(1, n - 1)
    with in_force(ctx.root):
        min_col = column_min_clear(db, agg)
        min_beam = max(25.0, db, 4.0 / 3.0 * agg)
        min_slab_s = min_slab_spacing()
        min_stir_s = min_stirrup_spacing()
    max_stir_s = min(values["depthMm"] / 2.0, 600.0)
    rows = [
        {
            "check": "Beam clear bar spacing (min)",
            "providedMm": clear_prov,
            "limitMm": min_beam,
            "ok": clear_prov >= min_beam,
        },
        {
            "check": "Column clear bar spacing (min)",
            "providedMm": clear_prov,
            "limitMm": min_col,
            "ok": clear_prov >= min_col,
        },
        {
            "check": "Stirrup spacing (min practical)",
            "providedMm": values["tieSpacingMm"],
            "limitMm": min_stir_s,
            "ok": values["tieSpacingMm"] >= min_stir_s,
        },
        {
            "check": "Stirrup spacing (max code limit)",
            "providedMm": values["tieSpacingMm"],
            "limitMm": max_stir_s,
            "ok": values["tieSpacingMm"] <= max_stir_s,
        },
    ]
    return result(
        summary={
            "providedClearSpacingMm": clear_prov,
            "beamMinClearMm": min_beam,
            "colMinClearMm": min_col,
            "minSlabSpacingMm": min_slab_s,
            "beamSpacingOk": clear_prov >= min_beam and values["tieSpacingMm"] <= max_stir_s,
        },
        tables=[
            table(
                "Reinforcement spacing checks",
                [
                    ("check", "Check"),
                    ("providedMm", "Provided", "mm"),
                    ("limitMm", "Limit", "mm"),
                    ("ok", "Pass"),
                ],
                rows,
            )
        ],
        notes=["Minimum clear spacing accounts for aggregate size 4/3*d_agg and bar diameter."],
    )


@feature(
    "objRebar.curtailmentRules",
    "Curtailment Rules",
    part="objects",
    fields=[
        number("clearSpanMm", "Clear span ln", 5500.0, unit="mm", min=500.0),
        number("effDepthMm", "Effective depth d", 450.0, unit="mm", min=100.0),
        number("barDiaMm", "Main bar diameter db", 20.0, unit="mm", min=8.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=12.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=200.0),
    ],
    requires_project=False,
)
def curtailment_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute flexural bar curtailment extensions, support anchorages, and top bar extent."""
    ln, d, db = values["clearSpanMm"], values["effDepthMm"], values["barDiaMm"]
    with in_force(ctx.root):
        ld = detailing.development_tension(db, values["fyMpa"], values["fcMpa"]).value
        ext_cut = detailing.extension_beyond_cutoff(d, db).value
        neg_ext = detailing.negative_extension(d, db, ln).value
        top_ext = detailing.standard_top_extent(ln, ld).value
    rows = [
        {"rule": "Extension beyond theoretical cutoff max(d, 12*db)", "lengthMm": ext_cut},
        {"rule": "Negative steel beyond inflection max(d, 12*db, ln/16)", "lengthMm": neg_ext},
        {"rule": "Standard top bar extent from support face max(0.30*ln, ld)", "lengthMm": top_ext},
        {"rule": "Tension development length ld", "lengthMm": ld},
    ]
    return result(
        summary={
            "extensionBeyondCutoffMm": ext_cut,
            "negativeExtensionMm": neg_ext,
            "topBarExtentFromFaceMm": top_ext,
            "developmentLengthMm": ld,
        },
        tables=[
            table(
                "Flexural bar curtailment parameters",
                [("rule", "Curtailment rule"), ("lengthMm", "Length", "mm")],
                rows,
            )
        ],
        notes=[
            "Curtailment lengths ensure full development past points of zero theoretical moment demand."
        ],
    )


@feature(
    "objRebar.barBendingSchedule",
    "Bar Bending Schedule",
    part="objects",
    fields=[
        checkbox("exportCsv", "Export bbs.csv to 04 Objects/exports", True),
    ],
    requires_project=True,
)
def bar_bending_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate the full Bar Bending Schedule (BBS) from the project BIM, object types, and detailing rules."""
    root = require_root(ctx, "generating a bar bending schedule")
    with in_force(ctx.root):
        try:
            dm = detailing.detailing_model(project_root=str(root))
            sched = bbs.bar_schedule(dm)
        except Exception as exc:
            raise FeatureInputError(f"Could not generate BBS for project: {exc}") from exc
    out_path = ""
    if values["exportCsv"]:
        csv_text = bbs.schedule_csv(sched)
        out_path = str(save_export(ctx, "bbs.csv", csv_text))
    len_by_dia: dict[float, float] = {}
    for r in sched.rows:
        len_by_dia[r.dia] = len_by_dia.get(r.dia, 0.0) + r.cutting_length * r.total_count / 1000.0
    rows = [
        {
            "diaMm": dia,
            "totalLengthM": len_by_dia.get(dia, 0.0),
            "massKg": mass,
        }
        for dia, mass in sorted(sched.by_diameter.items())
    ]
    return result(
        summary={
            "barMarkRows": len(sched.rows),
            "totalMassKg": sched.total,
            "totalLengthM": sum(len_by_dia.values()),
            "exportPath": out_path or "not exported",
        },
        tables=[
            table(
                "BBS summary by bar diameter",
                [
                    ("diaMm", "Diameter", "mm"),
                    ("totalLengthM", "Total length", "m"),
                    ("massKg", "Total mass", "kg"),
                ],
                rows,
            )
        ],
        notes=[
            f"Generated {len(sched.rows)} bar mark entries. "
            + (f"Saved CSV to {out_path}." if out_path else "")
        ],
    )


@feature(
    "objRebar.cutList",
    "Cut List",
    part="objects",
    fields=[
        number("stockLengthMm", "Stock bar length", 12000.0, unit="mm", min=3000.0),
        text(
            "cutLengthsMm",
            "Required cut lengths [mm] (comma/space separated)",
            "4200, 3800, 5100, 2900, 4200, 6100, 3400, 2500",
        ),
    ],
    requires_project=False,
)
def cut_list(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Pack required bar cut lengths into standard stock lengths using First-Fit Decreasing bin packing."""
    stock = values["stockLengthMm"]
    cuts = sorted(parse_numbers(values["cutLengthsMm"], "Cut lengths"), reverse=True)
    if any(c <= 0 or c > stock for c in cuts):
        raise FeatureInputError("All cut lengths must be positive and not exceed stock length.")
    bins: list[list[float]] = []
    rem: list[float] = []
    for c in cuts:
        placed = False
        for i, r in enumerate(rem):
            if r >= c - 1e-6:
                bins[i].append(c)
                rem[i] -= c
                placed = True
                break
        if not placed:
            bins.append([c])
            rem.append(stock - c)
    rows = [
        {
            "stockBar": i + 1,
            "cutsMm": ", ".join(f"{x:g}" for x in b),
            "usedMm": stock - rem[i],
            "offcutMm": rem[i],
        }
        for i, b in enumerate(bins)
    ]
    tot_used = sum(cuts)
    tot_stock = len(bins) * stock
    waste_pct = (tot_stock - tot_used) / tot_stock * 100.0
    return result(
        summary={
            "cutPieces": len(cuts),
            "stockBarsNeeded": len(bins),
            "totalOffcutMm": sum(rem),
            "wastePercent": waste_pct,
        },
        tables=[
            table(
                f"Stock bar cutting plan ({stock:g} mm stock)",
                [
                    ("stockBar", "Stock #"),
                    ("cutsMm", "Assigned cuts [mm]"),
                    ("usedMm", "Used", "mm"),
                    ("offcutMm", "Offcut", "mm"),
                ],
                rows,
            )
        ],
        notes=["Uses First-Fit Decreasing 1D cutting-stock heuristic to minimize offcut waste."],
    )


@feature(
    "objRebar.meshSheets",
    "Mesh Sheets",
    part="objects",
    fields=[
        number("areaM2", "Slab/wall area to cover", 120.0, unit="m2", min=1.0),
        number("sheetLengthM", "Sheet length", 4.8, unit="m", min=1.0),
        number("sheetWidthM", "Sheet width", 2.4, unit="m", min=1.0),
        number("lapMm", "Side & end lap allowance", 300.0, unit="mm", min=100.0),
        number("wireDiaMm", "Mesh wire diameter", 8.0, unit="mm", min=4.0),
        number("pitchMm", "Mesh wire pitch (square)", 200.0, unit="mm", min=50.0),
    ],
    requires_project=False,
)
def mesh_sheets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate welded wire mesh sheet counts, effective coverage with laps, and steel tonnage."""
    sl, sw = values["sheetLengthM"], values["sheetWidthM"]
    lap_m = values["lapMm"] / 1000.0
    if lap_m >= min(sl, sw):
        raise FeatureInputError("Lap length must be smaller than sheet dimensions.")
    gross_sheet_area = sl * sw
    net_sheet_area = (sl - lap_m) * (sw - lap_m)
    sheets_needed = math.ceil(values["areaM2"] / net_sheet_area)
    # Unit mass of square mesh per m2: 2 * (1000 / pitch) * bar_mass
    with in_force(ctx.root):
        m_per_m = bar_mass(values["wireDiaMm"])
    kg_per_m2 = 2.0 * (1000.0 / values["pitchMm"]) * m_per_m
    total_kg = sheets_needed * gross_sheet_area * kg_per_m2
    rows = [
        {"metric": "Gross sheet area", "value": gross_sheet_area, "unit": "m2"},
        {"metric": "Net effective area per sheet", "value": net_sheet_area, "unit": "m2"},
        {"metric": "Overlap factor", "value": gross_sheet_area / net_sheet_area, "unit": "-"},
        {"metric": "Sheets required", "value": sheets_needed, "unit": "sheets"},
        {"metric": "Mesh unit weight", "value": kg_per_m2, "unit": "kg/m2"},
        {"metric": "Total order mass", "value": total_kg, "unit": "kg"},
    ]
    return result(
        summary={
            "sheetsRequired": sheets_needed,
            "netCoveragePerSheetM2": net_sheet_area,
            "meshUnitMassKgPerM2": kg_per_m2,
            "totalMassKg": total_kg,
        },
        tables=[
            table(
                "Fabric mesh sheet takeoff",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Net coverage deducts one side lap and one end lap per sheet."],
    )


@feature(
    "objRebar.couplers",
    "Couplers",
    part="objects",
    fields=[
        number("barDiaMm", "Bar diameter", 32.0, unit="mm", min=12.0),
        number("barCount", "Number of bars spliced", 12.0, min=1.0),
        number("fyMpa", "Specified yield fy", 420.0, unit="MPa", min=250.0),
        number("fuMpa", "Specified tensile fu", 550.0, unit="MPa", min=350.0),
        number("couplerCostEach", "Coupler unit cost", 450.0, min=0.0),
        number("rebarCostPerKg", "Rebar supply & fix cost per kg", 105.0, min=0.0),
    ],
    requires_project=False,
)
def couplers_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate mechanical coupler strength requirement vs tension lap splice steel weight savings."""
    db, n = values["barDiaMm"], round(values["barCount"])
    area = math.pi * db**2 / 4.0
    req_125fy_kn = 1.25 * values["fyMpa"] * area / 1e3
    req_fu_kn = values["fuMpa"] * area / 1e3
    with in_force(ctx.root):
        lap_mm = detailing.lap_tension(db, values["fyMpa"], 28.0).value
        saved_kg = n * (lap_mm / 1000.0) * bar_mass(db)
    lap_cost = saved_kg * values["rebarCostPerKg"]
    coupler_cost = n * values["couplerCostEach"]
    rows = [
        {"metric": "Coupler count", "value": n, "unit": "nr"},
        {"metric": "Type 1 strength target (1.25*fy*As)", "value": req_125fy_kn, "unit": "kN"},
        {"metric": "Type 2 strength target (fu*As)", "value": req_fu_kn, "unit": "kN"},
        {"metric": "Equivalent tension lap saved", "value": lap_mm, "unit": "mm"},
        {"metric": "Saved lap steel mass", "value": saved_kg, "unit": "kg"},
        {
            "metric": "Coupler cost vs lap steel cost",
            "value": coupler_cost - lap_cost,
            "unit": "currency",
        },
    ]
    return result(
        summary={
            "couplerCount": n,
            "type1TargetKn": req_125fy_kn,
            "type2TargetKn": req_fu_kn,
            "savedSteelKg": saved_kg,
            "netCostDelta": coupler_cost - lap_cost,
        },
        tables=[
            table(
                "Mechanical coupler design & comparison",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Type 1 couplers develop 1.25*fy; Type 2 seismic couplers develop full specified tensile strength fu."
        ],
    )


@feature(
    "objRebar.anchorageLength",
    "Anchorage Length",
    part="objects",
    fields=[
        number("diaMm", "Bar diameter db", 20.0, unit="mm", min=8.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=12.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=200.0),
        checkbox("topBar", "Top-cast bar (>300 mm fresh concrete below)", False),
    ],
    requires_project=False,
)
def anchorage_length(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute straight tension, compression, and 90-degree hooked anchorage lengths."""
    db, fy, fc = values["diaMm"], values["fyMpa"], values["fcMpa"]
    with in_force(ctx.root):
        ld_base = detailing.development_tension(db, fy, fc).value
        ld = ld_base * (detailing.psi_t(True) if values["topBar"] else 1.0)
        ldh = detailing.hook_development(db, fy, fc).value
        ldc = detailing.development_compression(db, fy, fc).value
    rows = [
        {"mode": "Straight tension ld", "lengthMm": ld, "multipleDb": ld / db},
        {"mode": "Standard hook tension ldh", "lengthMm": ldh, "multipleDb": ldh / db},
        {"mode": "Straight compression ldc", "lengthMm": ldc, "multipleDb": ldc / db},
    ]
    return result(
        summary={
            "straightTensionMm": ld,
            "hookedTensionMm": ldh,
            "compressionMm": ldc,
        },
        tables=[
            table(
                "Bar anchorage lengths",
                [
                    ("mode", "Anchorage mode"),
                    ("lengthMm", "Required length", "mm"),
                    ("multipleDb", "L / db"),
                ],
                rows,
            )
        ],
        notes=[
            "Includes top-bar casting position factor when selected; formulas read from active code pack."
        ],
    )


@feature(
    "objRebar.bendDeduction",
    "Bend Deduction",
    part="objects",
    fields=[
        number("diaMm", "Bar diameter d", 16.0, unit="mm", min=6.0),
        number("leg1Mm", "Outside leg A", 450.0, unit="mm", min=50.0),
        number("leg2Mm", "Outside leg B", 1200.0, unit="mm", min=50.0),
        number("bendAngleDeg", "Bend angle", 90.0, unit="deg", min=15.0, max=180.0),
        checkbox("isStirrup", "Stirrup / tie mandrel", False),
    ],
    requires_project=False,
)
def bend_deduction(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute bend allowance and centre-line cutting deduction from outside bar dimensions."""
    d = values["diaMm"]
    with in_force(ctx.root):
        inside_dia = detailing.bend_diameter(d, values["isStirrup"]).value
    r = inside_dia / 2.0
    theta = math.radians(values["bendAngleDeg"])
    # Outside tangent extension vs centre-line arc length:
    # Two outside tangents meet at (r + d) * tan(theta/2) from tangent point; arc = (r + d/2) * theta
    tangent_out = 2.0 * (r + d) * math.tan(theta / 2.0)
    arc_cl = (r + d / 2.0) * theta
    deduction = tangent_out - arc_cl
    sum_outside = values["leg1Mm"] + values["leg2Mm"]
    cut_len = sum_outside - deduction
    return result(
        summary={
            "insideBendDiaMm": inside_dia,
            "sumOutsideLegsMm": sum_outside,
            "bendDeductionMm": deduction,
            "trueCutLengthMm": cut_len,
        },
        tables=[
            table(
                "Bend deduction calculation",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Inside mandrel diameter", "value": inside_dia, "unit": "mm"},
                    {"item": "Sum of outside dimensions", "value": sum_outside, "unit": "mm"},
                    {"item": "Geometric bend deduction", "value": deduction, "unit": "mm"},
                    {"item": "True centre-line cut length", "value": cut_len, "unit": "mm"},
                ],
            )
        ],
        notes=[
            "Deduction = 2*(r + d)*tan(theta/2) - (r + d/2)*theta measured along bar centre-line."
        ],
    )


@feature(
    "objRebar.hookExtension",
    "Hook Extension",
    part="objects",
    fields=[
        number("diaMm", "Bar diameter d", 12.0, unit="mm", min=6.0),
        select(
            "hookAngle",
            "Hook angle",
            [("90", "90 degree"), ("135", "135 degree seismic"), ("180", "180 degree")],
            "135",
        ),
    ],
    requires_project=False,
)
def hook_extension(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute required straight hook extension beyond the bend tangent for standard and seismic hooks."""
    d = values["diaMm"]
    ang = int(values["hookAngle"])
    with in_force(ctx.root):
        if ang == 135:
            ext = detailing.seismic_hook(d).tail
            bend_d = detailing.bend_diameter(d, True).value
        else:
            ext = detailing.standard_hook(d, ang).tail
            bend_d = detailing.bend_diameter(d, False).value
    rows = [
        {"metric": "Bar diameter", "value": d, "unit": "mm"},
        {"metric": "Inside bend diameter", "value": bend_d, "unit": "mm"},
        {"metric": "Straight extension", "value": ext, "unit": "mm"},
        {"metric": "Extension / d", "value": ext / d, "unit": "-"},
    ]
    return result(
        summary={"hookAngleDeg": ang, "extensionMm": ext, "insideBendDiaMm": bend_d},
        tables=[
            table(
                "Hook extension details",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Hook extensions and inside mandrel diameters come from the active code pack."],
    )


@feature(
    "objRebar.headedBars",
    "Headed Bars",
    part="objects",
    fields=[
        number("diaMm", "Bar diameter db", 25.0, unit="mm", min=12.0),
        number("fcMpa", "Concrete f'c", 32.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=200.0),
        number("availableDepthMm", "Available joint/support depth", 450.0, unit="mm", min=100.0),
        number("tailCoverMm", "Clear cover behind head", 50.0, unit="mm", min=20.0),
    ],
    requires_project=False,
)
def headed_bars(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size mechanical anchor heads and compare headed development length against hooked anchorage."""
    db, fy, fc = values["diaMm"], values["fyMpa"], values["fcMpa"]
    # Net bearing area >= 4 * Ab => gross head area >= 5 * Ab
    head_dia = db * math.sqrt(5.0)
    extra_note = ""
    with in_force(ctx.root):
        ld_hook = detailing.hook_development(db, fy, fc).value
        try:
            ld_head = detailing.headed_development(db, fy, fc).value
        except ValueError:
            ld_head = max(8.0 * db, 150.0, 0.19 * fy * db / math.sqrt(min(fc, 41.0)))
            extra_note = (
                " Active code pack omits headed bars; used textbook headed anchorage formula."
            )
    avail = values["availableDepthMm"] - values["tailCoverMm"]
    rows = [
        {"metric": "Headed development ldt", "value": ld_head, "unit": "mm"},
        {"metric": "Hooked development ldh", "value": ld_hook, "unit": "mm"},
        {"metric": "Available embedment", "value": avail, "unit": "mm"},
        {"metric": "Minimum circular head OD (Abrg=4*Ab)", "value": head_dia, "unit": "mm"},
    ]
    return result(
        summary={
            "headedDevLengthMm": ld_head,
            "hookedDevLengthMm": ld_hook,
            "minHeadDiaMm": head_dia,
            "fitsAvailableDepth": ld_head <= avail,
        },
        tables=[
            table(
                "Headed bar sizing",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Minimum head net bearing area = 4*Ab (circular head OD >= sqrt(5)*db)." + extra_note
        ],
    )


@feature(
    "objRebar.barCongestionCheck",
    "Bar Congestion Check",
    part="objects",
    fields=[
        number("widthMm", "Beam/column width", 300.0, unit="mm", min=120.0),
        number("coverMm", "Clear cover", 40.0, unit="mm", min=15.0),
        number("stirrupDiaMm", "Stirrup diameter", 10.0, unit="mm", min=6.0),
        number("barsInLayer", "Bars per horizontal layer", 5.0, min=2.0),
        number("barDiaMm", "Main bar diameter", 25.0, unit="mm", min=10.0),
        number("aggregateMm", "Max aggregate size", 20.0, unit="mm", min=5.0),
    ],
    requires_project=False,
)
def bar_congestion_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check clear bar spacing and cross-section steel congestion against vibrator and aggregate limits."""
    w, cc, dt, db = values["widthMm"], values["coverMm"], values["stirrupDiaMm"], values["barDiaMm"]
    n = round(values["barsInLayer"])
    agg = values["aggregateMm"]
    avail_w = w - 2 * cc - 2 * dt
    clear_prov = (avail_w - n * db) / max(1, n - 1)
    min_req = max(25.0, db, 4.0 / 3.0 * agg)
    max_bars_1layer = math.floor((avail_w + min_req) / (db + min_req))
    return result(
        summary={
            "clearSpacingMm": clear_prov,
            "requiredClearMm": min_req,
            "maxBarsSingleLayer": max(1, max_bars_1layer),
            "congested": clear_prov < min_req,
        },
        tables=[
            table(
                "Layer congestion check",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Available width inside stirrup", "value": avail_w, "unit": "mm"},
                    {"item": "Provided clear spacing", "value": clear_prov, "unit": "mm"},
                    {"item": "Required minimum clear spacing", "value": min_req, "unit": "mm"},
                    {
                        "item": "Max bars fitting in single layer",
                        "value": max(1, max_bars_1layer),
                        "unit": "bars",
                    },
                ],
            )
        ],
        notes=[
            "Minimum clear spacing = max(25 mm, db, 4/3 * d_agg) to allow concrete consolidation."
        ],
    )


@feature(
    "objRebar.barClashDetection",
    "Bar Clash Detection",
    part="objects",
    fields=[
        number("widthMm", "Section width", 400.0, unit="mm", min=100.0),
        number("depthMm", "Section depth", 600.0, unit="mm", min=100.0),
        number("coverMm", "Clear cover", 40.0, unit="mm", min=15.0),
        number("barDiaMm", "Longitudinal bar dia", 20.0, unit="mm", min=10.0),
        number("barCountTop", "Top bar count", 4.0, min=2.0),
        number("openingCenterXMm", "Sleeve/embed centre X", 0.0, unit="mm"),
        number("openingCenterYMm", "Sleeve/embed centre Y", 200.0, unit="mm"),
        number("openingDiaMm", "Sleeve/embed diameter", 110.0, unit="mm", min=10.0),
    ],
    requires_project=False,
)
def bar_clash_detection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detect geometric clashes between longitudinal bars and embedded sleeves or anchor plates."""
    w, h, cc, db = values["widthMm"], values["depthMm"], values["coverMm"], values["barDiaMm"]
    n = round(values["barCountTop"])
    inset = cc + 10.0 + db / 2.0
    x_lim = max(10.0, w / 2.0 - inset)
    y_top = h / 2.0 - inset
    ox, oy, od = values["openingCenterXMm"], values["openingCenterYMm"], values["openingDiaMm"]
    rows = []
    clashes = 0
    for i in range(n):
        bx = -x_lim + 2.0 * x_lim * i / max(1, n - 1)
        dist = math.hypot(bx - ox, y_top - oy)
        clear = dist - (db / 2.0 + od / 2.0)
        is_clash = clear < 15.0
        if is_clash:
            clashes += 1
        rows.append(
            {"bar": f"T{i + 1}", "xMm": bx, "yMm": y_top, "clearanceMm": clear, "clash": is_clash}
        )
    return result(
        summary={
            "checkedBars": n,
            "clashesFound": clashes,
            "minClearanceMm": min(r["clearanceMm"] for r in rows),
        },
        tables=[
            table(
                "Bar-to-embed clearance",
                [
                    ("bar", "Bar"),
                    ("xMm", "x", "mm"),
                    ("yMm", "y", "mm"),
                    ("clearanceMm", "Clearance", "mm"),
                    ("clash", "Clash (<15mm)"),
                ],
                rows,
            )
        ],
        notes=["Flags bars within 15 mm clear distance of an embedded sleeve or opening."],
    )


@feature(
    "objRebar.coverCompliance",
    "Cover Compliance",
    part="objects",
    fields=[
        select(
            "exposure",
            "Exposure class",
            [("interior", "Interior"), ("exterior", "Exterior"), ("soil", "Earth-contact")],
            "interior",
        ),
    ],
    requires_project=False,
)
def cover_compliance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit specified cover on every reinforced object type in 04 Objects against exposure minimums."""
    lib, is_proj = objects_or_default(ctx)
    exp_min = {"interior": 20.0, "exterior": 40.0, "soil": 75.0}[values["exposure"]]
    elem_min = {
        "slab": 20.0,
        "wall": 25.0,
        "beam": 40.0,
        "column": 40.0,
        "footing": 75.0,
        "pileCap": 50.0,
        "staircase": 20.0,
    }
    rows = []
    fails = 0
    for obj in lib.objects:
        reinf = getattr(obj, "reinforcement", None)
        if reinf is None:
            continue
        cov = float(getattr(reinf, "cover", 0.0))
        req = max(
            elem_min.get(obj.kind, 25.0),
            exp_min if obj.kind not in ("footing", "pileCap") else 75.0,
        )
        ok = cov >= req - 1e-6
        if not ok:
            fails += 1
        rows.append(
            {"id": obj.id, "kind": obj.kind, "providedMm": cov, "requiredMm": req, "ok": ok}
        )
    return result(
        summary={
            "source": "project" if is_proj else "default library",
            "checkedTypes": len(rows),
            "failingTypes": fails,
            "allCompliant": fails == 0,
        },
        tables=[
            table(
                "Object library cover compliance",
                [
                    ("id", "Object ID"),
                    ("kind", "Kind"),
                    ("providedMm", "Cover", "mm"),
                    ("requiredMm", "Required", "mm"),
                    ("ok", "Pass"),
                ],
                rows,
            )
        ],
        notes=[
            "Compares declared reinforcement cover of each object type against element & exposure minimums."
        ],
    )


@feature(
    "objRebar.toleranceCheck",
    "Tolerance Check",
    part="objects",
    fields=[
        text(
            "measuredCsv",
            "Fabricated bar measurements CSV (mark,spec_mm,actual_mm)",
            "mark,spec_mm,actual_mm\nB1-T1,4850,4842\nB1-S1,1275,1282\nC1-V1,3600,3575\nS1-BX1,5400,5418",
        ),
    ],
    requires_project=False,
)
def tolerance_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare fabricated bar cutting lengths against standard fabrication tolerances."""
    raw = parse_csv_rows(values["measuredCsv"])
    rows = []
    fails = 0
    for r in raw:
        try:
            spec = float(r["spec_mm"])
            act = float(r["actual_mm"])
        except (KeyError, ValueError) as exc:
            raise FeatureInputError("CSV must contain mark, spec_mm, actual_mm columns.") from exc
        diff = act - spec
        # Standard shop tolerance: +/- 25 mm for cut lengths (or +/- 15 mm for short links <= 1500 mm)
        tol = 15.0 if spec <= 1500.0 else 25.0
        ok = abs(diff) <= tol
        if not ok:
            fails += 1
        rows.append(
            {
                "mark": r.get("mark", "?"),
                "specMm": spec,
                "actualMm": act,
                "deviationMm": diff,
                "toleranceMm": tol,
                "ok": ok,
            }
        )
    return result(
        summary={"checkedMarks": len(rows), "outOfTolerance": fails, "allPass": fails == 0},
        tables=[
            table(
                "Cutting length tolerance audit",
                [
                    ("mark", "Mark"),
                    ("specMm", "Specified", "mm"),
                    ("actualMm", "Actual", "mm"),
                    ("deviationMm", "Deviation", "mm"),
                    ("toleranceMm", "+/- Tol", "mm"),
                    ("ok", "Pass"),
                ],
                rows,
            )
        ],
        notes=["Checks +/-15 mm tolerance for bars <= 1500 mm and +/-25 mm for longer bars."],
    )


@feature(
    "objRebar.weightSummary",
    "Weight Summary",
    part="objects",
    fields=[],
    requires_project=True,
)
def weight_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise reinforcement weight by bar diameter and element kind from the project detailing/BOQ."""
    root = require_root(ctx, "summarising reinforcement weights")
    with in_force(ctx.root):
        try:
            dm = detailing.detailing_model(project_root=str(root))
            sched = bbs.bar_schedule(dm)
        except Exception as exc:
            raise FeatureInputError(f"Could not compute reinforcement weights: {exc}") from exc
    len_by_dia: dict[float, float] = {}
    for r in sched.rows:
        len_by_dia[r.dia] = len_by_dia.get(r.dia, 0.0) + r.cutting_length * r.total_count / 1000.0
    rows = [
        {
            "diaMm": dia,
            "lengthM": len_by_dia.get(dia, 0.0),
            "massKg": mass,
            "sharePercent": (mass / sched.total * 100.0) if sched.total > 0 else 0.0,
        }
        for dia, mass in sorted(sched.by_diameter.items())
    ]
    return result(
        summary={
            "totalMassKg": sched.total,
            "totalMassTonnes": sched.total / 1000.0,
            "barSizes": len(rows),
        },
        tables=[
            table(
                "Reinforcement weight by diameter",
                [
                    ("diaMm", "Diameter", "mm"),
                    ("lengthM", "Length", "m"),
                    ("massKg", "Mass", "kg"),
                    ("sharePercent", "Share", "%"),
                ],
                rows,
            )
        ],
        notes=["Derived directly from the project bar bending schedule."],
    )


@feature(
    "objRebar.wastageAllowance",
    "Wastage Allowance",
    part="objects",
    fields=[
        number(
            "netMassKg", "Net reinforcement mass (0 = read project BBS)", 0.0, unit="kg", min=0.0
        ),
        number("mainWastePct", "Main bar cutting wastage", 4.0, unit="%", min=0.0, max=25.0),
        number("linkWastePct", "Stirrup/tie wastage", 6.0, unit="%", min=0.0, max=25.0),
        number("mainSharePct", "Main bar share of total mass", 75.0, unit="%", min=0.0, max=100.0),
    ],
    requires_project=False,
)
def wastage_allowance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply cutting and offcut wastage allowances to net reinforcement quantities."""
    net_kg = values["netMassKg"]
    if net_kg <= 0:
        if ctx.root is not None:
            with in_force(ctx.root):
                dm = detailing.detailing_model(project_root=str(ctx.root))
                net_kg = bbs.bar_schedule(dm).total
        else:
            net_kg = 10000.0
    f_main = values["mainSharePct"] / 100.0
    net_main = net_kg * f_main
    net_link = net_kg * (1.0 - f_main)
    gross_main = net_main * (1.0 + values["mainWastePct"] / 100.0)
    gross_link = net_link * (1.0 + values["linkWastePct"] / 100.0)
    gross_tot = gross_main + gross_link
    return result(
        summary={
            "netMassKg": net_kg,
            "wastageMassKg": gross_tot - net_kg,
            "grossOrderKg": gross_tot,
            "weightedWastePercent": ((gross_tot - net_kg) / net_kg * 100.0) if net_kg > 0 else 0.0,
        },
        tables=[
            table(
                "Reinforcement wastage breakdown",
                [
                    ("category", "Bar category"),
                    ("netKg", "Net", "kg"),
                    ("wastePct", "Waste", "%"),
                    ("grossKg", "Gross", "kg"),
                ],
                [
                    {
                        "category": "Main longitudinal bars",
                        "netKg": net_main,
                        "wastePct": values["mainWastePct"],
                        "grossKg": gross_main,
                    },
                    {
                        "category": "Stirrups, hoops & ties",
                        "netKg": net_link,
                        "wastePct": values["linkWastePct"],
                        "grossKg": gross_link,
                    },
                ],
            )
        ],
        notes=["Uses project BBS total mass when netMassKg = 0 and a project is open."],
    )


@feature(
    "objRebar.orderList",
    "Order List",
    part="objects",
    fields=[
        number("stockLengthM", "Standard stock bar length", 12.0, unit="m", min=6.0),
        number("wastePct", "Order wastage allowance", 3.0, unit="%", min=0.0, max=20.0),
        checkbox("exportCsv", "Export order-list.csv to 04 Objects/exports", False),
    ],
    requires_project=True,
)
def order_list(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Produce a steel bar procurement order list grouped by diameter and standard stock bars."""
    root = require_root(ctx, "producing a bar order list")
    with in_force(ctx.root):
        try:
            dm = detailing.detailing_model(project_root=str(root))
            sched = bbs.bar_schedule(dm)
        except Exception as exc:
            raise FeatureInputError(f"Could not generate order list: {exc}") from exc
    stock_m = values["stockLengthM"]
    factor = 1.0 + values["wastePct"] / 100.0
    len_by_dia: dict[float, float] = {}
    for r in sched.rows:
        len_by_dia[r.dia] = len_by_dia.get(r.dia, 0.0) + r.cutting_length * r.total_count / 1000.0
    rows = []
    tot_tonnes = 0.0
    for dia, mass in sorted(sched.by_diameter.items()):
        req_len = len_by_dia.get(dia, 0.0) * factor
        bars_12m = math.ceil(req_len / stock_m)
        order_kg = bars_12m * stock_m * bar_mass(dia)
        tot_tonnes += order_kg / 1000.0
        rows.append(
            {
                "diaMm": dia,
                "netMassKg": mass,
                "grossLengthM": req_len,
                "stockBars": bars_12m,
                "orderMassKg": order_kg,
            }
        )
    out_path = ""
    if values["exportCsv"]:
        lines = ["dia_mm,net_mass_kg,gross_length_m,stock_bars,order_mass_kg"] + [
            f"{r['diaMm']:g},{r['netMassKg']:.2f},{r['grossLengthM']:.2f},{r['stockBars']},{r['orderMassKg']:.2f}"
            for r in rows
        ]
        out_path = str(save_export(ctx, "rebar-order-list.csv", "\n".join(lines) + "\n"))
    return result(
        summary={
            "barSizes": len(rows),
            "totalStockBars": sum(r["stockBars"] for r in rows),
            "totalOrderTonnes": tot_tonnes,
            "exportPath": out_path or "not exported",
        },
        tables=[
            table(
                f"Bar procurement order list ({stock_m:g} m stock)",
                [
                    ("diaMm", "Dia", "mm"),
                    ("netMassKg", "Net mass", "kg"),
                    ("grossLengthM", "Gross length", "m"),
                    ("stockBars", "Stock bars"),
                    ("orderMassKg", "Order mass", "kg"),
                ],
                rows,
            )
        ],
        notes=[
            f"Includes {values['wastePct']:g}% cutting allowance rounded up to whole {stock_m:g} m stock bars."
        ],
    )


@feature(
    "objRebar.deliveryBatch",
    "Delivery Batch",
    part="objects",
    fields=[
        number("truckCapacityTonnes", "Max payload per delivery truck", 20.0, unit="t", min=2.0),
    ],
    requires_project=True,
)
def delivery_batch(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Group project rebar quantities by storey/stage into delivery batches capped by truck payload."""
    root = require_root(ctx, "planning rebar delivery batches")
    with in_force(ctx.root):
        try:
            dm = detailing.detailing_model(project_root=str(root))
            sched = bbs.bar_schedule(dm)
        except Exception as exc:
            raise FeatureInputError(f"Could not group delivery batches: {exc}") from exc
    by_story: dict[str, float] = {}
    for r in sched.rows:
        st = r.story or "SUBSTRUCTURE"
        by_story[st] = by_story.get(st, 0.0) + r.mass
    cap_kg = values["truckCapacityTonnes"] * 1000.0
    rows = []
    tot_trucks = 0
    for idx, (st, kg) in enumerate(by_story.items(), 1):
        trucks = max(1, math.ceil(kg / cap_kg))
        tot_trucks += trucks
        rows.append(
            {
                "batch": f"DB-{idx:02d}",
                "story": st,
                "massKg": kg,
                "massTonnes": kg / 1000.0,
                "trucks": trucks,
            }
        )
    return result(
        summary={
            "batchCount": len(rows),
            "totalTrucks": tot_trucks,
            "totalMassTonnes": sum(r["massTonnes"] for r in rows),
        },
        tables=[
            table(
                "Reinforcement delivery batches by storey",
                [
                    ("batch", "Batch"),
                    ("story", "Storey / zone"),
                    ("massKg", "Mass", "kg"),
                    ("massTonnes", "Mass", "t"),
                    ("trucks", "Trucks"),
                ],
                rows,
            )
        ],
        notes=[f"Truck counts sized at {values['truckCapacityTonnes']:g} t payload per delivery."],
    )

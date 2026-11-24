"""Substructure - Loads & Combinations tab: support reactions, envelopes, schemes & load audits."""

from __future__ import annotations

import csv
import io
import math
from typing import Any

import numpy as np

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.foundations_common import (
    build_profile,
    export_file,
    load_substructure_context,
    require_loads,
)
from saengine.report.clauses import in_force
from saengine.soil import bearing as soil_bearing
from saengine.soil import settlement as soil_settlement
from saengine.substructure import earth_pressure, loads, piles, shallow
from saengine.substructure import report as sub_report


def _eval_case_combos(
    ctx: FeatureContext,
    values: dict[str, Any],
    kind: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Evaluate service or strength combinations for input static D, L, W, E base actions."""
    d_kn, l_kn, w_kn, e_kn = (
        values["deadKn"],
        values["liveKn"],
        values["windKn"],
        values["seismicKn"],
    )
    md, ml, mw, me = (
        values["mDeadKnm"],
        values["mLiveKnm"],
        values["mWindKnm"],
        values["mSeismicKnm"],
    )
    cases = {"D", "L"}
    if abs(w_kn) > 0 or abs(mw) > 0:
        cases.update({"WX", "WY"})
    if abs(e_kn) > 0 or abs(me) > 0:
        cases.update({"EX", "EY"})
    with in_force(ctx.root):
        from saengine.codes import context as code_context

        settings = ctx.settings()
        if kind == "service":
            combos = loads.service_combinations(cases)
        else:
            combos = loads.strength_combinations(settings, cases)
            if not combos:
                combos = [
                    (row.name, dict(row.factors))
                    for row in code_context.table("combinations").strength
                ]
    rows = []
    for name, fac in combos:
        p = (
            fac.get("D", 0.0) * d_kn
            + fac.get("L", 0.0) * l_kn
            + (fac.get("WX", 0.0) + fac.get("WY", 0.0)) * w_kn
            + (fac.get("EX", 0.0) + fac.get("EY", 0.0)) * e_kn
        )
        m = (
            fac.get("D", 0.0) * md
            + fac.get("L", 0.0) * ml
            + (fac.get("WX", 0.0) + fac.get("WY", 0.0)) * mw
            + (fac.get("EX", 0.0) + fac.get("EY", 0.0)) * me
        )
        rows.append({"combo": name, "axialKn": p, "momentKnm": m})
    max_p = max(r["axialKn"] for r in rows) if rows else 0.0
    min_p = min(r["axialKn"] for r in rows) if rows else 0.0
    max_m = max(abs(r["momentKnm"]) for r in rows) if rows else 0.0
    return rows, {
        "comboCount": len(rows),
        "maxAxialKn": max_p,
        "minAxialKn": min_p,
        "maxAbsMomentKnm": max_m,
    }


@feature(
    "foundationsLoads.columnReactions",
    "Column Reactions",
    part="substructure",
    fields=[
        text("caseFilter", "Load case filter (blank = all)", ""),
    ],
    requires_project=True,
)
def column_reactions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Import and tabulate column and wall base support reactions from 08 FEM results."""
    sub_ctx = load_substructure_context(ctx)
    base_loads = require_loads(sub_ctx)
    filt = values["caseFilter"].strip().lower()
    rows = []
    for case_name, node_map in sorted(base_loads.cases.items()):
        if filt and filt not in case_name.lower():
            continue
        for base_id, base in sorted(base_loads.bases.items()):
            fz = sum(float(node_map.get(nid, np.zeros(6))[2]) for nid, _ in base.nodes) / 1e3
            fx = sum(float(node_map.get(nid, np.zeros(6))[0]) for nid, _ in base.nodes) / 1e3
            fy = sum(float(node_map.get(nid, np.zeros(6))[1]) for nid, _ in base.nodes) / 1e3
            rows.append({"base": base_id, "case": case_name, "fzKn": fz, "fxKn": fx, "fyKn": fy})
    return result(
        summary={
            "baseCount": len(base_loads.bases),
            "caseCount": len(base_loads.cases),
            "rowCount": len(rows),
        },
        tables=[
            table(
                "Imported superstructure support reactions",
                [
                    ("base", "Support"),
                    ("case", "Case"),
                    ("fzKn", "Fz", "kN"),
                    ("fxKn", "Fx", "kN"),
                    ("fyKn", "Fy", "kN"),
                ],
                rows[:200],
            )
        ],
        notes=["Reactions read directly from 08 FEM/model.results."],
    )


@feature(
    "foundationsLoads.baseLoads",
    "Base Loads",
    part="substructure",
    fields=[
        text("supportId", "Support / column ID", "C1"),
        number("deadKn", "Dead axial load D", 520.0, unit="kN"),
        number("liveKn", "Live axial load L", 240.0, unit="kN"),
        number("windKn", "Wind axial load W (±)", 80.0, unit="kN"),
        number("seismicKn", "Seismic axial load E (±)", 110.0, unit="kN"),
        number("mDeadKnm", "Dead moment M_D", 15.0, unit="kN·m"),
        number("mLiveKnm", "Live moment M_L", 10.0, unit="kN·m"),
        number("mWindKnm", "Wind moment M_W", 45.0, unit="kN·m"),
        number("mSeismicKnm", "Seismic moment M_E", 65.0, unit="kN·m"),
    ],
    requires_project=False,
)
def base_loads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assemble and combine manual base loads (D, L, W, E) for a foundation support."""
    serv_rows, serv_sum = _eval_case_combos(ctx, values, "service")
    _ult_rows, ult_sum = _eval_case_combos(ctx, values, "strength")
    return result(
        summary={
            "support": values["supportId"],
            "maxServiceKn": serv_sum["maxAxialKn"],
            "maxUltimateKn": ult_sum["maxAxialKn"],
            "maxUltimateMomentKnm": ult_sum["maxAbsMomentKnm"],
        },
        tables=[
            table(
                f"Service combinations for {values['supportId']}",
                [
                    ("combo", "Combination"),
                    ("axialKn", "Axial", "kN"),
                    ("momentKnm", "Moment", "kN·m"),
                ],
                serv_rows,
            )
        ],
        notes=[
            f"Evaluated {serv_sum['comboCount']} service and {ult_sum['comboCount']} strength combinations."
        ],
    )


@feature(
    "foundationsLoads.loadCombinations",
    "Load Combinations",
    part="substructure",
    fields=[
        checkbox("includeWind", "Include wind cases (WX, WY)", True),
        checkbox("includeSeismic", "Include earthquake cases (EX, EY)", True),
        checkbox("includeEarth", "Include lateral earth case H", False),
    ],
    requires_project=False,
)
def load_combinations(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List code-pack service and strength foundation load combinations."""
    cases = {"D", "L"}
    if values["includeWind"]:
        cases.update({"WX", "WY"})
    if values["includeSeismic"]:
        cases.update({"EX", "EY"})
    if values["includeEarth"]:
        cases.add("H")
    with in_force(ctx.root):
        settings = ctx.settings()
        serv = loads.service_combinations(cases)
        ult = loads.strength_combinations(settings, cases)
    rows = [
        {"kind": "Service", "name": n, "factors": ", ".join(f"{k}:{v:g}" for k, v in f.items())}
        for n, f in serv
    ]
    rows += [
        {"kind": "Strength", "name": n, "factors": ", ".join(f"{k}:{v:g}" for k, v in f.items())}
        for n, f in ult
    ]
    return result(
        summary={"serviceCount": len(serv), "strengthCount": len(ult), "totalCount": len(rows)},
        tables=[
            table(
                "Foundation design load combinations",
                [("kind", "Limit state"), ("name", "Combination"), ("factors", "Factors")],
                rows,
            )
        ],
        notes=["Combinations generated from active Project Settings and code pack."],
    )


@feature(
    "foundationsLoads.soilPressurePlot",
    "Soil Pressure Plot",
    part="substructure",
    fields=[
        number("verticalKn", "Service vertical load V", 1000.0, unit="kN", min=1.0),
        number("mxKnm", "Service moment Mx", 75.0, unit="kN·m"),
        number("myKnm", "Service moment My", 45.0, unit="kN·m"),
        number("lengthM", "Foundation length L", 2.8, unit="m", min=0.5),
        number("widthM", "Foundation width B", 2.4, unit="m", min=0.5),
    ],
    requires_project=False,
)
def soil_pressure_plot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a 2D contact pressure grid beneath a footing or mat foundation."""
    v = values["verticalKn"]
    l_mm, b_mm = values["lengthM"] * 1e3, values["widthM"] * 1e3
    sp = shallow.soil_pressure(
        v * 1e3, (values["myKnm"] / v) * 1e3, (values["mxKnm"] / v) * 1e3, l_mm, b_mm
    )
    rows = []
    for ix in range(5):
        u = -values["lengthM"] / 2.0 + values["lengthM"] * ix / 4.0
        for iy in range(5):
            v_pos = -values["widthM"] / 2.0 + values["widthM"] * iy / 4.0
            q = max(0.0, sp.a * 1e3 + sp.gu * 1e6 * u + sp.gv * 1e6 * v_pos)
            rows.append({"xM": u, "yM": v_pos, "pressureKpa": q})
    return result(
        summary={
            "qmaxKpa": sp.qmax * 1e3,
            "qminKpa": sp.qmin * 1e3,
            "contactShare": sp.contact,
            "state": sp.state,
        },
        tables=[
            table(
                "2D contact bearing pressure grid",
                [("xM", "x", "m"), ("yM", "y", "m"), ("pressureKpa", "q", "kPa")],
                rows,
            )
        ],
        notes=[f"Contact status: {sp.state} ({sp.contact:.1%} of base in compression)."],
    )


@feature(
    "foundationsLoads.settlementPlot",
    "Settlement Plot",
    part="substructure",
    fields=[
        number("widthM", "Foundation width B", 3.0, unit="m", min=0.4),
        number("lengthM", "Foundation length L", 3.0, unit="m", min=0.4),
        number("depthM", "Founding depth Df", 1.5, unit="m", min=0.0),
        number("pressureKpa", "Net bearing pressure q", 150.0, unit="kPa", min=1.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def settlement_plot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate settlement variation across pressure levels and depth increments."""
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        rows = []
        for frac in (0.25, 0.50, 0.75, 1.00, 1.25):
            q_step = values["pressureKpa"] * frac
            res = soil_settlement.settlement(
                prof, values["widthM"], values["lengthM"], values["depthM"], q_step
            )
            rows.append(
                {
                    "pressureKpa": q_step,
                    "immediateMm": res.get("immediate", 0.0),
                    "consolMm": res.get("consolidation", 0.0),
                    "totalMm": res["total"],
                }
            )
    return result(
        summary={
            "designSettlementMm": rows[3]["totalMm"],
            "immediateMm": rows[3]["immediateMm"],
            "consolidationMm": rows[3]["consolMm"],
        },
        tables=[
            table(
                "Load-settlement response curve",
                [
                    ("pressureKpa", "Pressure q", "kPa"),
                    ("immediateMm", "Immediate", "mm"),
                    ("consolMm", "Consolidation", "mm"),
                    ("totalMm", "Total", "mm"),
                ],
                rows,
            )
        ],
        notes=[f"Soil source: {src}."],
    )


@feature(
    "foundationsLoads.reactionTable",
    "Reaction Table",
    part="substructure",
    fields=[
        checkbox("envelopeOnly", "Show peak envelope per support only", True),
    ],
    requires_project=True,
)
def reaction_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List support reactions and moments for every column and wall base in the project."""
    sub_ctx = load_substructure_context(ctx)
    base_loads = require_loads(sub_ctx)
    rows = []
    for base_id, base in sorted(base_loads.bases.items()):
        max_fz, max_mx, max_my = 0.0, 0.0, 0.0
        for case_name, node_map in base_loads.cases.items():
            vec = sum((node_map.get(nid, np.zeros(6)) for nid, _ in base.nodes), np.zeros(6))
            if values["envelopeOnly"]:
                max_fz = max(max_fz, abs(float(vec[2])) / 1e3)
                max_mx = max(max_mx, abs(float(vec[3])) / 1e6)
                max_my = max(max_my, abs(float(vec[4])) / 1e6)
            else:
                rows.append(
                    {
                        "support": base_id,
                        "case": case_name,
                        "fzKn": float(vec[2]) / 1e3,
                        "mxKnm": float(vec[3]) / 1e6,
                        "myKnm": float(vec[4]) / 1e6,
                    }
                )
        if values["envelopeOnly"]:
            rows.append(
                {
                    "support": base_id,
                    "case": "Envelope (abs)",
                    "fzKn": max_fz,
                    "mxKnm": max_mx,
                    "myKnm": max_my,
                }
            )
    return result(
        summary={"supportCount": len(base_loads.bases), "rows": len(rows)},
        tables=[
            table(
                "Support reactions & moments",
                [
                    ("support", "Support"),
                    ("case", "Case"),
                    ("fzKn", "Fz", "kN"),
                    ("mxKnm", "Mx", "kN·m"),
                    ("myKnm", "My", "kN·m"),
                ],
                rows[:200],
            )
        ],
        notes=["Extracted from 08 FEM analysis support nodes."],
    )


@feature(
    "foundationsLoads.exportReactions",
    "Export Reactions",
    part="substructure",
    fields=[
        text("filename", "CSV filename", "support-reactions.csv"),
    ],
    requires_project=True,
)
def export_reactions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export all superstructure support reactions to CSV in 09 Substructure/exports."""
    sub_ctx = load_substructure_context(ctx)
    base_loads = require_loads(sub_ctx)
    rows = []
    for base_id, base in sorted(base_loads.bases.items()):
        for case_name, node_map in sorted(base_loads.cases.items()):
            vec = sum((node_map.get(nid, np.zeros(6)) for nid, _ in base.nodes), np.zeros(6))
            rows.append(
                {
                    "support": base_id,
                    "case": case_name,
                    "fxKn": float(vec[0]) / 1e3,
                    "fyKn": float(vec[1]) / 1e3,
                    "fzKn": float(vec[2]) / 1e3,
                    "mxKnm": float(vec[3]) / 1e6,
                    "myKnm": float(vec[4]) / 1e6,
                    "mzKnm": float(vec[5]) / 1e6,
                }
            )
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf, fieldnames=["support", "case", "fxKn", "fyKn", "fzKn", "mxKnm", "myKnm", "mzKnm"]
    )
    writer.writeheader()
    writer.writerows(rows)
    fname = values["filename"].strip() or "support-reactions.csv"
    out_path = export_file(ctx, fname, buf.getvalue())
    return result(
        summary={"exportedRows": len(rows), "csvPath": str(out_path)},
        tables=[
            table(
                "Exported support reactions preview",
                [
                    ("support", "Support"),
                    ("case", "Case"),
                    ("fzKn", "Fz", "kN"),
                    ("mxKnm", "Mx", "kN·m"),
                    ("myKnm", "My", "kN·m"),
                ],
                rows[:25],
            )
        ],
        notes=[f"Full reactions table exported to {out_path}"],
    )


@feature(
    "foundationsLoads.compareSchemes",
    "Compare Schemes",
    part="substructure",
    fields=[
        number(
            "totalBuildingLoadKn",
            "Total building service gravity load",
            12000.0,
            unit="kN",
            min=100.0,
        ),
        number("footprintM2", "Building plan area", 400.0, unit="m²", min=10.0),
        number("columnCount", "Number of columns", 12.0, min=2.0, max=200.0),
        number("depthM", "Founding depth Df", 1.8, unit="m", min=0.5),
        number("pileLengthM", "Candidate pile length L", 18.0, unit="m", min=4.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def compare_schemes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare isolated pad footings, raft mat, and piled foundation schemes by concrete volume and settlement."""
    tot_v = values["totalBuildingLoadKn"]
    area_fp = values["footprintM2"]
    n_cols = max(2, round(values["columnCount"]))
    avg_p = tot_v / n_cols
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        pad_b = 2.5
        qa_pad = float(soil_bearing.allowable(prof, pad_b, pad_b, values["depthM"])["qa"])
        req_pad_area = avg_p / max(qa_pad, 10.0)
        pad_b = max(1.0, math.sqrt(req_pad_area))
        pad_settle = float(
            soil_settlement.settlement(
                prof, pad_b, pad_b, values["depthM"], avg_p / (pad_b * pad_b)
            )["total"]
        )
        pad_vol = n_cols * (pad_b**2) * 0.55

        raft_b = math.sqrt(area_fp)
        raft_q = tot_v / area_fp
        raft_settle = float(
            soil_settlement.settlement(
                prof, raft_b, raft_b, values["depthM"], raft_q, foundation="raft"
            )["total"]
        )
        raft_vol = area_fp * 0.75

        sp = piles.single_pile(
            prof, "bored", 0.6, values["pileLengthM"], values["depthM"], method="spt"
        )
        n_piles = max(n_cols, math.ceil(tot_v / max(sp["Qa"], 50.0)))
        pile_vol = (
            n_piles * (math.pi * 0.6**2 / 4.0 * values["pileLengthM"]) + n_cols * 2.2 * 2.2 * 0.9
        )
        pile_settle = max(5.0, raft_settle * 0.30)

    coverage = (n_cols * pad_b**2) / area_fp
    rows = [
        {
            "scheme": "Isolated pad footings",
            "concreteM3": pad_vol,
            "settlementMm": pad_settle,
            "note": f"{n_cols} pads ~{pad_b:.2f}m sq ({coverage:.0%} footprint)",
        },
        {
            "scheme": "Raft mat foundation",
            "concreteM3": raft_vol,
            "settlementMm": raft_settle,
            "note": f"750 mm mat, q = {raft_q:.1f} kPa",
        },
        {
            "scheme": "Piled caps (Ø600 mm)",
            "concreteM3": pile_vol,
            "settlementMm": pile_settle,
            "note": f"{n_piles} piles × {values['pileLengthM']:g} m (Qa={sp['Qa']:.0f} kN)",
        },
    ]
    rec = "Raft or Piled" if coverage > 0.50 or pad_settle > 50.0 else "Isolated Pads"
    return result(
        summary={
            "padCoverageRatio": coverage,
            "recommendedScheme": rec,
            "padSettlementMm": pad_settle,
            "raftSettlementMm": raft_settle,
            "pileSettlementMm": pile_settle,
        },
        tables=[
            table(
                "Foundation scheme comparison",
                [
                    ("scheme", "Scheme"),
                    ("concreteM3", "Concrete", "m³"),
                    ("settlementMm", "Est. settlement", "mm"),
                    ("note", "Sizing basis"),
                ],
                rows,
            )
        ],
        notes=[
            f"Soil source: {src}. Raft becomes economical when spread footings cover > 50% of building footprint."
        ],
    )


@feature(
    "foundationsLoads.loadEnvelope",
    "Load Envelope",
    part="substructure",
    fields=[
        number("deadKn", "Dead load D", 500.0, unit="kN"),
        number("liveKn", "Live load L", 220.0, unit="kN"),
        number("windKn", "Wind load W", 90.0, unit="kN"),
        number("seismicKn", "Seismic load E", 130.0, unit="kN"),
        number("mDeadKnm", "Dead moment M_D", 10.0, unit="kN·m"),
        number("mLiveKnm", "Live moment M_L", 8.0, unit="kN·m"),
        number("mWindKnm", "Wind moment M_W", 50.0, unit="kN·m"),
        number("mSeismicKnm", "Seismic moment M_E", 75.0, unit="kN·m"),
    ],
    requires_project=False,
)
def load_envelope(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build governing serviceability and ultimate load envelopes across all combinations."""
    _, serv_sum = _eval_case_combos(ctx, values, "service")
    _, ult_sum = _eval_case_combos(ctx, values, "strength")
    rows = [
        {
            "state": "Service (ASD)",
            "maxPKn": serv_sum["maxAxialKn"],
            "minPKn": serv_sum["minAxialKn"],
            "maxMKnm": serv_sum["maxAbsMomentKnm"],
        },
        {
            "state": "Ultimate (LRFD)",
            "maxPKn": ult_sum["maxAxialKn"],
            "minPKn": ult_sum["minAxialKn"],
            "maxMKnm": ult_sum["maxAbsMomentKnm"],
        },
    ]
    return result(
        summary={
            "serviceMaxPKn": serv_sum["maxAxialKn"],
            "serviceMinPKn": serv_sum["minAxialKn"],
            "ultimateMaxPKn": ult_sum["maxAxialKn"],
            "ultimateMaxMKnm": ult_sum["maxAbsMomentKnm"],
        },
        tables=[
            table(
                "Governing foundation load envelope",
                [
                    ("state", "Limit state"),
                    ("maxPKn", "Max P", "kN"),
                    ("minPKn", "Min P", "kN"),
                    ("maxMKnm", "Max |M|", "kN·m"),
                ],
                rows,
            )
        ],
        notes=["Evaluated over code-pack service and strength combinations."],
    )


@feature(
    "foundationsLoads.windReactions",
    "Wind Reactions",
    part="substructure",
    fields=[
        text("windPrefix", "Wind case prefix", "W"),
    ],
    requires_project=True,
)
def wind_reactions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Extract wind-induced base shears, axial uplift/compression, and moments from 08 FEM."""
    sub_ctx = load_substructure_context(ctx)
    base_loads = require_loads(sub_ctx)
    pref = values["windPrefix"].strip().lower()
    rows = []
    for case_name, node_map in sorted(base_loads.cases.items()):
        if pref not in case_name.lower():
            continue
        sum_fx = sum(float(v[0]) for v in node_map.values()) / 1e3
        sum_fy = sum(float(v[1]) for v in node_map.values()) / 1e3
        sum_fz = sum(float(v[2]) for v in node_map.values()) / 1e3
        rows.append(
            {
                "case": case_name,
                "baseShearXKn": sum_fx,
                "baseShearYKn": sum_fy,
                "netAxialKn": sum_fz,
            }
        )
    if not rows:
        raise FeatureInputError(
            f"No load cases matching '{values['windPrefix']}' found in 08 FEM results."
        )
    return result(
        summary={
            "windCaseCount": len(rows),
            "maxBaseShearKn": max(math.hypot(r["baseShearXKn"], r["baseShearYKn"]) for r in rows),
        },
        tables=[
            table(
                "Wind base shear & reaction summary",
                [
                    ("case", "Wind case"),
                    ("baseShearXKn", "ΣFx", "kN"),
                    ("baseShearYKn", "ΣFy", "kN"),
                    ("netAxialKn", "ΣFz", "kN"),
                ],
                rows,
            )
        ],
        notes=["Positive/negative axial wind forces contribute to overturning and uplift checks."],
    )


@feature(
    "foundationsLoads.snowReactions",
    "Snow Reactions",
    part="substructure",
    fields=[
        number("tributaryAreaM2", "Column roof tributary area", 36.0, unit="m²", min=1.0),
        number("groundSnowKpa", "Ground snow load pg", 1.5, unit="kPa", min=0.0),
        number("exposureFactor", "Exposure / roof coefficient Ce·Ct", 0.70, min=0.3, max=1.5),
        number("slopeFactor", "Roof slope factor Cs", 1.0, min=0.0, max=1.0),
    ],
    requires_project=False,
)
def snow_reactions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute flat/sloped roof snow load and resulting axial column reaction on foundations."""
    pf_kpa = values["groundSnowKpa"] * values["exposureFactor"] * values["slopeFactor"]
    reaction_kn = pf_kpa * values["tributaryAreaM2"]
    return result(
        summary={
            "roofSnowKpa": pf_kpa,
            "columnSnowReactionKn": reaction_kn,
            "factoredSnow16Kn": 1.6 * reaction_kn,
        },
        tables=[
            table(
                "Snow load foundation reaction",
                [("item", "Parameter"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"item": "Design roof snow pressure", "val": pf_kpa, "unit": "kPa"},
                    {"item": "Tributary area", "val": values["tributaryAreaM2"], "unit": "m²"},
                    {"item": "Unfactored snow reaction S", "val": reaction_kn, "unit": "kN"},
                    {"item": "Factored reaction (1.6 S)", "val": 1.6 * reaction_kn, "unit": "kN"},
                ],
            )
        ],
        notes=["Combine roof snow S with D and L/W per active project load combinations."],
    )


@feature(
    "foundationsLoads.equipmentReactions",
    "Equipment Reactions",
    part="substructure",
    fields=[
        number("emptyWeightKn", "Dry / empty equipment weight", 110.0, unit="kN", min=0.0),
        number("operatingFluidKn", "Operating fluid / contents weight", 65.0, unit="kN", min=0.0),
        number("hydroTestFluidKn", "Hydro-test water weight", 95.0, unit="kN", min=0.0),
        number("lateralWindSeismicKn", "Equipment lateral thrust", 28.0, unit="kN", min=0.0),
        number("cgHeightM", "Centre of gravity height above base", 2.2, unit="m", min=0.1),
    ],
    requires_project=False,
)
def equipment_reactions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute operating, hydro-test, and overturning reactions from heavy plant and vessels."""
    v_empty = values["emptyWeightKn"]
    v_oper = v_empty + values["operatingFluidKn"]
    v_test = v_empty + values["hydroTestFluidKn"]
    m_lat = values["lateralWindSeismicKn"] * values["cgHeightM"]
    rows = [
        {
            "condition": "Erection / empty",
            "verticalKn": v_empty,
            "shearKn": values["lateralWindSeismicKn"],
            "momentKnm": m_lat,
        },
        {
            "condition": "Normal operating",
            "verticalKn": v_oper,
            "shearKn": values["lateralWindSeismicKn"],
            "momentKnm": m_lat,
        },
        {
            "condition": "Hydrostatic test (calm wind)",
            "verticalKn": v_test,
            "shearKn": 0.25 * values["lateralWindSeismicKn"],
            "momentKnm": 0.25 * m_lat,
        },
    ]
    return result(
        summary={
            "operatingLoadKn": v_oper,
            "hydroTestLoadKn": v_test,
            "overturningMomentKnm": m_lat,
        },
        tables=[
            table(
                "Heavy equipment foundation reactions",
                [
                    ("condition", "Condition"),
                    ("verticalKn", "Vertical V", "kN"),
                    ("shearKn", "Shear H", "kN"),
                    ("momentKnm", "Moment M", "kN·m"),
                ],
                rows,
            )
        ],
        notes=[
            "Empty + full lateral load governs uplift/anchor bolts; hydro-test governs maximum soil bearing."
        ],
    )


@feature(
    "foundationsLoads.waterPressureLoads",
    "Water Pressure Loads",
    part="substructure",
    fields=[
        number("submergedDepthM", "Submerged wall/slab depth below GWT", 3.5, unit="m", min=0.0),
        number("footprintAreaM2", "Substructure plan area", 180.0, unit="m²", min=1.0),
        number("wallPerimeterM", "Buried perimeter length", 54.0, unit="m", min=1.0),
    ],
    requires_project=False,
)
def water_pressure_loads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute hydrostatic uplift pressure and lateral wall thrust on buried foundation surfaces."""
    h = values["submergedDepthM"]
    u_kpa = earth_pressure.GAMMA_W * h
    uplift_kn = u_kpa * values["footprintAreaM2"]
    lat_kn_m = 0.5 * earth_pressure.GAMMA_W * h**2
    lat_total_kn = lat_kn_m * values["wallPerimeterM"]
    return result(
        summary={
            "baseWaterPressureKpa": u_kpa,
            "totalUpliftKn": uplift_kn,
            "lateralThrustKnPerM": lat_kn_m,
            "totalLateralKn": lat_total_kn,
        },
        tables=[
            table(
                "Hydrostatic loads on buried surfaces",
                [("item", "Load component"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"item": "Base uplift pressure (γw·h)", "val": u_kpa, "unit": "kPa"},
                    {"item": "Total upward buoyancy force", "val": uplift_kn, "unit": "kN"},
                    {"item": "Lateral hydrostatic thrust per m", "val": lat_kn_m, "unit": "kN/m"},
                    {"item": "Resultant arm above base", "val": h / 3.0, "unit": "m"},
                ],
            )
        ],
        notes=[
            "Apply fluid/water load factor per active project combinations (typically 1.6 H for strength design)."
        ],
    )


@feature(
    "foundationsLoads.thermalReactions",
    "Thermal Reactions",
    part="substructure",
    fields=[
        number("lengthM", "Continuous wall / grade beam length L", 28.0, unit="m", min=2.0),
        number("sectionAreaM2", "Concrete cross-sectional area", 0.24, unit="m²", min=0.02),
        number("deltaTC", "Effective temperature change ΔT", 20.0, unit="°C", min=1.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("restraintFactor", "Soil/support restraint factor (0–1)", 0.45, min=0.05, max=1.0),
    ],
    requires_project=False,
)
def thermal_reactions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate restrained thermal axial force and strain demand on substructure beams and walls."""
    ec_kpa = 4700.0 * math.sqrt(values["fcMpa"]) * 1000.0
    alpha = 10e-6  # /°C
    free_disp_mm = alpha * values["deltaTC"] * values["lengthM"] * 1000.0
    # Cracked effective axial stiffness ~ 0.5 Ec A
    axial_force_kn = (
        values["restraintFactor"]
        * 0.5
        * ec_kpa
        * values["sectionAreaM2"]
        * alpha
        * values["deltaTC"]
    )
    stress_mpa = (axial_force_kn * 1e3) / (values["sectionAreaM2"] * 1e6)
    return result(
        summary={
            "freeExpansionMm": free_disp_mm,
            "restrainedAxialForceKn": axial_force_kn,
            "concreteThermalStressMpa": stress_mpa,
        },
        tables=[
            table(
                "Restrained thermal substructure reaction",
                [("item", "Parameter"), ("val", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Unrestrained expansion/contraction ΔL",
                        "val": free_disp_mm,
                        "unit": "mm",
                    },
                    {"item": "Restrained axial force T", "val": axial_force_kn, "unit": "kN"},
                    {"item": "Average concrete stress", "val": stress_mpa, "unit": "MPa"},
                ],
            )
        ],
        notes=["Thermal stiffness takes 0.5 Ec A for cracked/creep relaxation in buried members."],
    )


@feature(
    "foundationsLoads.serviceEnvelope",
    "Service Envelope",
    part="substructure",
    fields=[
        number("deadKn", "Dead load D", 500.0, unit="kN"),
        number("liveKn", "Live load L", 220.0, unit="kN"),
        number("windKn", "Wind load W", 90.0, unit="kN"),
        number("seismicKn", "Seismic load E", 130.0, unit="kN"),
        number("mDeadKnm", "Dead moment M_D", 10.0, unit="kN·m"),
        number("mLiveKnm", "Live moment M_L", 8.0, unit="kN·m"),
        number("mWindKnm", "Wind moment M_W", 50.0, unit="kN·m"),
        number("mSeismicKnm", "Seismic moment M_E", 75.0, unit="kN·m"),
    ],
    requires_project=False,
)
def service_envelope(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute serviceability (allowable-stress) load combinations and peak demands."""
    rows, summary_data = _eval_case_combos(ctx, values, "service")
    return result(
        summary=summary_data,
        tables=[
            table(
                "Serviceability combination envelope",
                [
                    ("combo", "Combination"),
                    ("axialKn", "Axial P", "kN"),
                    ("momentKnm", "Moment M", "kN·m"),
                ],
                rows,
            )
        ],
        notes=["Used for soil bearing pressure, pile allowable load, and settlement checks."],
    )


@feature(
    "foundationsLoads.ultimateEnvelope",
    "Ultimate Envelope",
    part="substructure",
    fields=[
        number("deadKn", "Dead load D", 500.0, unit="kN"),
        number("liveKn", "Live load L", 220.0, unit="kN"),
        number("windKn", "Wind load W", 90.0, unit="kN"),
        number("seismicKn", "Seismic load E", 130.0, unit="kN"),
        number("mDeadKnm", "Dead moment M_D", 10.0, unit="kN·m"),
        number("mLiveKnm", "Live moment M_L", 8.0, unit="kN·m"),
        number("mWindKnm", "Wind moment M_W", 50.0, unit="kN·m"),
        number("mSeismicKnm", "Seismic moment M_E", 75.0, unit="kN·m"),
    ],
    requires_project=False,
)
def ultimate_envelope(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute ultimate limit state (strength) load combinations and peak factored demands."""
    rows, summary_data = _eval_case_combos(ctx, values, "strength")
    return result(
        summary=summary_data,
        tables=[
            table(
                "Ultimate limit state combination envelope",
                [
                    ("combo", "Combination"),
                    ("axialKn", "Axial Pu", "kN"),
                    ("momentKnm", "Moment Mu", "kN·m"),
                ],
                rows,
            )
        ],
        notes=[
            "Used for concrete flexure, one-way shear, punching shear, and pile structural checks."
        ],
    )


@feature(
    "foundationsLoads.governingCase",
    "Governing Case",
    part="substructure",
    fields=[
        number("deadKn", "Dead load D", 500.0, unit="kN"),
        number("liveKn", "Live load L", 220.0, unit="kN"),
        number("windKn", "Wind load W", 90.0, unit="kN"),
        number("seismicKn", "Seismic load E", 130.0, unit="kN"),
        number("mDeadKnm", "Dead moment M_D", 10.0, unit="kN·m"),
        number("mLiveKnm", "Live moment M_L", 8.0, unit="kN·m"),
        number("mWindKnm", "Wind moment M_W", 50.0, unit="kN·m"),
        number("mSeismicKnm", "Seismic moment M_E", 75.0, unit="kN·m"),
    ],
    requires_project=False,
)
def governing_case(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Identify the governing service and strength combinations for axial compression, uplift, and bending."""
    s_rows, _ = _eval_case_combos(ctx, values, "service")
    u_rows, _ = _eval_case_combos(ctx, values, "strength")
    gov_s_comp = max(s_rows, key=lambda r: r["axialKn"])
    gov_s_uplift = min(s_rows, key=lambda r: r["axialKn"])
    gov_u_comp = max(u_rows, key=lambda r: r["axialKn"])
    gov_u_mom = max(u_rows, key=lambda r: abs(r["momentKnm"]))
    rows = [
        {
            "criterion": "Max service compression",
            "combo": gov_s_comp["combo"],
            "axialKn": gov_s_comp["axialKn"],
            "momentKnm": gov_s_comp["momentKnm"],
        },
        {
            "criterion": "Min service / uplift",
            "combo": gov_s_uplift["combo"],
            "axialKn": gov_s_uplift["axialKn"],
            "momentKnm": gov_s_uplift["momentKnm"],
        },
        {
            "criterion": "Max factored compression",
            "combo": gov_u_comp["combo"],
            "axialKn": gov_u_comp["axialKn"],
            "momentKnm": gov_u_comp["momentKnm"],
        },
        {
            "criterion": "Max factored moment",
            "combo": gov_u_mom["combo"],
            "axialKn": gov_u_mom["axialKn"],
            "momentKnm": gov_u_mom["momentKnm"],
        },
    ]
    return result(
        summary={
            "governingServiceComp": gov_s_comp["combo"],
            "governingServiceUplift": gov_s_uplift["combo"],
            "governingUltimateComp": gov_u_comp["combo"],
            "governingUltimateMoment": gov_u_mom["combo"],
        },
        tables=[
            table(
                "Governing design combinations",
                [
                    ("criterion", "Criterion"),
                    ("combo", "Combination"),
                    ("axialKn", "Axial", "kN"),
                    ("momentKnm", "Moment", "kN·m"),
                ],
                rows,
            )
        ],
        notes=["Checks both maximum downward demand and minimum/uplift overturning."],
    )


@feature(
    "foundationsLoads.loadCasesImport",
    "Load Cases Import",
    part="substructure",
    fields=[],
    requires_project=True,
)
def load_cases_import(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Import and catalog available load cases from the superstructure analysis (08 FEM)."""
    sub_ctx = load_substructure_context(ctx)
    base_loads = require_loads(sub_ctx)
    rows = [
        {
            "case": cname,
            "supportNodes": len(nmap),
            "totalFzKn": sum(float(v[2]) for v in nmap.values()) / 1e3,
        }
        for cname, nmap in sorted(base_loads.cases.items())
    ]
    return result(
        summary={"importedCaseCount": len(rows), "supportBases": len(base_loads.bases)},
        tables=[
            table(
                "Imported analysis load cases",
                [("case", "Load case"), ("supportNodes", "Nodes"), ("totalFzKn", "Sum Fz", "kN")],
                rows,
            )
        ],
        notes=["Imported from 08 FEM/model.results."],
    )


@feature(
    "foundationsLoads.loadCaseEditor",
    "Load Case Editor",
    part="substructure",
    fields=[
        text("comboName", "Combination label", "Custom ULS"),
        number("gammaD", "Factor γD (dead)", 1.2, min=0.0, max=3.0),
        number("gammaL", "Factor γL (live)", 1.6, min=0.0, max=3.0),
        number("gammaW", "Factor γW (wind)", 0.5, min=-2.0, max=3.0),
        number("gammaE", "Factor γE (seismic)", 0.0, min=-2.0, max=3.0),
        number("deadKn", "Dead load D", 500.0, unit="kN"),
        number("liveKn", "Live load L", 220.0, unit="kN"),
        number("windKn", "Wind load W", 90.0, unit="kN"),
        number("seismicKn", "Seismic load E", 130.0, unit="kN"),
    ],
    requires_project=False,
)
def load_case_editor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assemble and evaluate a custom factored foundation load combination."""
    fd = values["gammaD"] * values["deadKn"]
    fl = values["gammaL"] * values["liveKn"]
    fw = values["gammaW"] * values["windKn"]
    fe = values["gammaE"] * values["seismicKn"]
    total = fd + fl + fw + fe
    rows = [
        {
            "case": "Dead (D)",
            "unfactoredKn": values["deadKn"],
            "factor": values["gammaD"],
            "factoredKn": fd,
        },
        {
            "case": "Live (L)",
            "unfactoredKn": values["liveKn"],
            "factor": values["gammaL"],
            "factoredKn": fl,
        },
        {
            "case": "Wind (W)",
            "unfactoredKn": values["windKn"],
            "factor": values["gammaW"],
            "factoredKn": fw,
        },
        {
            "case": "Seismic (E)",
            "unfactoredKn": values["seismicKn"],
            "factor": values["gammaE"],
            "factoredKn": fe,
        },
    ]
    return result(
        summary={"combinationName": values["comboName"], "totalFactoredKn": total},
        tables=[
            table(
                f"Custom load combination: {values['comboName']}",
                [
                    ("case", "Case"),
                    ("unfactoredKn", "Unfactored", "kN"),
                    ("factor", "Factor"),
                    ("factoredKn", "Factored", "kN"),
                ],
                rows,
            )
        ],
        notes=[
            "Use custom combinations to test construction stages, equipment tests, or special load cases."
        ],
    )


@feature(
    "foundationsLoads.reactionBalance",
    "Reaction Balance",
    part="substructure",
    fields=[],
    requires_project=True,
)
def reaction_balance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Sum foundation support reactions per load case to verify global static equilibrium."""
    sub_ctx = load_substructure_context(ctx)
    base_loads = require_loads(sub_ctx)
    rows = []
    for cname, nmap in sorted(base_loads.cases.items()):
        fx = sum(float(v[0]) for v in nmap.values()) / 1e3
        fy = sum(float(v[1]) for v in nmap.values()) / 1e3
        fz = sum(float(v[2]) for v in nmap.values()) / 1e3
        rows.append({"case": cname, "sumFxKn": fx, "sumFyKn": fy, "sumFzKn": fz})
    return result(
        summary={
            "caseCount": len(rows),
            "maxVerticalKn": max((abs(r["sumFzKn"]) for r in rows), default=0.0),
        },
        tables=[
            table(
                "Global support reaction summation by case",
                [
                    ("case", "Case"),
                    ("sumFxKn", "ΣFx", "kN"),
                    ("sumFyKn", "ΣFy", "kN"),
                    ("sumFzKn", "ΣFz", "kN"),
                ],
                rows,
            )
        ],
        notes=["Compare ΣFz, ΣFx, ΣFy against total building gravity and lateral loads."],
    )


@feature(
    "foundationsLoads.loadPathCheck",
    "Load Path Check",
    part="substructure",
    fields=[],
    requires_project=True,
)
def load_path_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify continuous load path from all 6 BIM columns and walls down to 09 Substructure foundations."""
    sub_ctx = load_substructure_context(ctx)
    unsupported = sub_report.unsupported_bases(sub_ctx)
    rows = [
        {"element": eid, "kind": kind, "status": "Missing foundation"} for eid, kind in unsupported
    ]
    return result(
        summary={
            "foundationCount": len(sub_ctx.substructure.foundations),
            "unsupportedCount": len(unsupported),
            "continuousLoadPathOk": len(unsupported) == 0,
        },
        tables=[
            table(
                "Unsupported columns and walls",
                [("element", "Element ID"), ("kind", "Kind"), ("status", "Status")],
                rows or [{"element": "-", "kind": "-", "status": "All bases supported"}],
            )
        ],
        notes=[
            "Every column and wall base in 6 BIM must map to an isolated, combined, strip, pile cap, or raft foundation."
        ],
    )


@feature(
    "foundationsLoads.missingReactions",
    "Missing Reactions",
    part="substructure",
    fields=[],
    requires_project=True,
)
def missing_reactions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Identify columns and walls that lack support reactions in 08 FEM results."""
    sub_ctx = load_substructure_context(ctx)
    base_loads = require_loads(sub_ctx)
    rows = [
        {"element": eid, "issue": "No reaction node in FEM results"}
        for eid in base_loads.unsupported
    ]
    return result(
        summary={
            "totalBases": len(base_loads.bases),
            "missingReactionCount": len(rows),
            "ok": len(rows) == 0,
        },
        tables=[
            table(
                "Supports missing analysis reactions",
                [("element", "Element"), ("issue", "Finding")],
                rows or [{"element": "-", "issue": "All bases have FEM reactions"}],
            )
        ],
        notes=["Re-run structural meshing/analysis if recently added columns lack support nodes."],
    )


@feature(
    "foundationsLoads.eccentricitySummary",
    "Eccentricity Summary",
    part="substructure",
    fields=[
        number("verticalKn", "Vertical resultant V", 900.0, unit="kN", min=1.0),
        number("mxKnm", "Moment Mx", 65.0, unit="kN·m"),
        number("myKnm", "Moment My", 45.0, unit="kN·m"),
        number("lengthM", "Foundation length L", 2.6, unit="m", min=0.4),
        number("widthM", "Foundation width B", 2.2, unit="m", min=0.4),
    ],
    requires_project=False,
)
def eccentricity_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report biaxial resultant eccentricities ex, ey and middle-third kern ratio."""
    v = values["verticalKn"]
    ex = values["myKnm"] / v
    ey = values["mxKnm"] / v
    kern_ratio = 6.0 * abs(ex) / values["lengthM"] + 6.0 * abs(ey) / values["widthM"]
    return result(
        summary={
            "exM": ex,
            "eyM": ey,
            "kernInteraction": kern_ratio,
            "withinKern": kern_ratio <= 1.0,
        },
        tables=[
            table(
                "Resultant eccentricity & kern check",
                [
                    ("axis", "Axis"),
                    ("eccM", "Eccentricity", "m"),
                    ("limitM", "Middle-third limit", "m"),
                ],
                [
                    {
                        "axis": "Longitudinal X (ex = My/V)",
                        "eccM": ex,
                        "limitM": values["lengthM"] / 6.0,
                    },
                    {
                        "axis": "Transverse Y (ey = Mx/V)",
                        "eccM": ey,
                        "limitM": values["widthM"] / 6.0,
                    },
                ],
            )
        ],
        notes=[
            f"Biaxial kern check (6|ex|/L + 6|ey|/B = {kern_ratio:.3f} {'≤' if kern_ratio <= 1 else '>'} 1.0)."
        ],
    )


@feature(
    "foundationsLoads.loadAuditReport",
    "Load Audit Report",
    part="substructure",
    fields=[],
    requires_project=True,
)
def load_audit_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile a Markdown audit report of foundation load sources, BIM mapping, and FEM status."""
    sub_ctx = load_substructure_context(ctx)
    unsupported = sub_report.unsupported_bases(sub_ctx)
    lines = [
        "# Foundation Load Audit Report",
        "",
        f"- Foundations defined: {len(sub_ctx.substructure.foundations)}",
        f"- Tie beams defined: {len(sub_ctx.substructure.tieBeams)}",
        f"- Unsupported BIM columns/walls: {len(unsupported)}",
    ]
    if sub_ctx.loads is not None:
        lines.append(
            f"- FEM load cases available: {len(sub_ctx.loads.cases)} ({', '.join(sorted(sub_ctx.loads.cases))})"
        )
        lines.append(f"- Service combinations: {len(sub_ctx.loads.service)}")
        lines.append(f"- Strength combinations: {len(sub_ctx.loads.strength)}")
    else:
        lines.append(f"- FEM reactions status: {sub_ctx.no_loads or 'Not available'}")
    if unsupported:
        lines.extend(
            ["", "## Unsupported Bases", *[f"- {eid} ({kind})" for eid, kind in unsupported]]
        )
    out_path = export_file(ctx, "load-audit-report.md", "\n".join(lines) + "\n")
    return result(
        summary={
            "foundationCount": len(sub_ctx.substructure.foundations),
            "unsupportedCount": len(unsupported),
            "hasFemResults": sub_ctx.loads is not None,
            "reportPath": str(out_path),
        },
        tables=[
            table(
                "Load audit summary",
                [("item", "Audit item"), ("val", "Value")],
                [
                    {
                        "item": "Foundations in 09 Substructure",
                        "val": len(sub_ctx.substructure.foundations),
                    },
                    {"item": "Unsupported BIM bases", "val": len(unsupported)},
                    {
                        "item": "FEM analysis cases",
                        "val": len(sub_ctx.loads.cases) if sub_ctx.loads else 0,
                    },
                ],
            )
        ],
        notes=[f"Audit report saved to {out_path}"],
    )

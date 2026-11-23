"""Substructure - Pile Analysis tab: axial capacity, downdrag, group action, t-z/p-y, settlement & reports."""

from __future__ import annotations

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
    select,
    table,
    text,
)
from saengine.features.foundations_common import build_profile, export_file, parse_pairs
from saengine.report.clauses import in_force
from saengine.substructure import (
    downdrag,
    load_tests,
    pile_lateral,
    pile_lateral_soil,
    pile_settlement,
    pile_static,
    pilecap,
    piles,
)
from saengine.substructure.shallow import ColumnBase

_METHOD_OPTS = [
    ("soilReport", "Soil report"),
    ("static", "Static (alpha-beta)"),
    ("spt", "SPT correlation"),
]
_KIND_OPTS = [("bored", "Bored cast-in-situ"), ("driven", "Driven precast")]


@feature(
    "foundationsPileAnalysis.skinFriction",
    "Skin Friction",
    part="substructure",
    fields=[
        select("kind", "Pile type", _KIND_OPTS),
        select("method", "Capacity method", _METHOD_OPTS, default="spt"),
        number("diameterMm", "Diameter / side", 600.0, unit="mm", min=200.0),
        number("lengthM", "Pile length L", 18.0, unit="m", min=2.0),
        number("headDepthM", "Cut-off depth below ground", 1.5, unit="m", min=0.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def skin_friction(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute unit skin friction fs and cumulative shaft resistance Qs by soil layer."""
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        sp = piles.single_pile(
            prof,
            values["kind"],
            values["diameterMm"] / 1000.0,
            values["lengthM"],
            values["headDepthM"],
            method=values["method"],
        )
    rows = [
        {
            "layer": r["layer"] + 1,
            "soil": r["soilType"],
            "topM": r["top"] / 1000.0,
            "botM": r["bottom"] / 1000.0,
            "excludedM": r["excluded"] / 1000.0,
            "fsKpa": r["fs"],
            "fsMaxKpa": r["fsMax"],
            "qsKn": r["Qs"],
        }
        for r in sp["layers"]
    ]
    return result(
        summary={
            "totalSkinFrictionKn": sp["Qs"],
            "allowablePartialSkinKn": sp["Qs"] / sp["factors"]["skin"],
            "method": sp["method"],
        },
        tables=[
            table(
                "Shaft friction by soil layer",
                [
                    ("layer", "Layer"),
                    ("soil", "Soil"),
                    ("topM", "Top", "m"),
                    ("botM", "Bottom", "m"),
                    ("excludedM", "Excluded", "m"),
                    ("fsKpa", "Mean fs", "kPa"),
                    ("qsKn", "Qs", "kN"),
                ],
                rows,
            )
        ],
        notes=[f"Soil source: {src}. {sp['methodText']}", *sp["notes"]],
    )


@feature(
    "foundationsPileAnalysis.endBearing",
    "End Bearing",
    part="substructure",
    fields=[
        select("kind", "Pile type", _KIND_OPTS),
        select("method", "Capacity method", _METHOD_OPTS, default="spt"),
        number("diameterMm", "Diameter / side", 600.0, unit="mm", min=200.0),
        number("lengthM", "Pile length L", 18.0, unit="m", min=2.0),
        number("headDepthM", "Cut-off depth below ground", 1.5, unit="m", min=0.0),
        number(
            "softLayerDistM",
            "Distance below tip to weaker layer (0 = none)",
            0.0,
            unit="m",
            min=0.0,
        ),
        number(
            "softLayerQbKpa", "Weaker layer end bearing (if present)", 300.0, unit="kPa", min=0.0
        ),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def end_bearing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute pile tip unit end bearing qb, base force Qb, and punch-through check."""
    d_m = values["diameterMm"] / 1000.0
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        sp = piles.single_pile(
            prof,
            values["kind"],
            d_m,
            values["lengthM"],
            values["headDepthM"],
            method=values["method"],
        )
        qb = float(sp["qb"])
        qb_force = float(sp["Qb"])
        if values["softLayerDistM"] > 0:
            qb_eff = pile_static.punching_base(
                qb, values["softLayerQbKpa"], values["softLayerDistM"], d_m
            )
        else:
            qb_eff = qb
    base = sp["base"]
    return result(
        summary={
            "unitEndBearingKpa": qb,
            "punchingAdjustedQbKpa": qb_eff,
            "endBearingForceKn": qb_force,
            "tipN60": base.get("N60") if base.get("N60") is not None else 0.0,
            "allowablePartialBaseKn": qb_force / sp["factors"]["base"],
        },
        tables=[
            table(
                "Pile tip end bearing evaluation",
                [("param", "Parameter"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"param": "Tip depth below ground", "val": sp["tip"] / 1000.0, "unit": "m"},
                    {
                        "param": "Bearing stratum",
                        "val": str(base.get("soilType") or "-"),
                        "unit": "-",
                    },
                    {"param": "Design N60 at tip", "val": base.get("N60") or 0.0, "unit": "blows"},
                    {"param": "Unit end bearing qb", "val": qb, "unit": "kPa"},
                    {"param": "Punching-adjusted qb", "val": qb_eff, "unit": "kPa"},
                    {"param": "Ultimate base force Qb", "val": qb_force, "unit": "kN"},
                ],
            )
        ],
        notes=[f"Soil source: {src}. Tip method: {base.get('method', '')}."],
    )


@feature(
    "foundationsPileAnalysis.negativeSkin",
    "Negative Skin",
    part="substructure",
    fields=[
        select("kind", "Pile type", _KIND_OPTS),
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        number("lengthM", "Pile length L", 20.0, unit="m", min=3.0),
        number("headDepthM", "Cut-off depth", 1.5, unit="m", min=0.0),
        number("settlingDepthM", "Settling fill/clay depth below ground", 5.0, unit="m", min=0.5),
        number("sustainedLoadKn", "Sustained dead + permanent load", 450.0, unit="kN", min=10.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def negative_skin(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute downdrag dragload and neutral point depth in settling soil strata."""
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        sp = piles.single_pile(
            prof,
            values["kind"],
            values["diameterMm"] / 1000.0,
            values["lengthM"],
            values["headDepthM"],
            method="spt",
        )
        np_res = downdrag.neutral_point(
            prof, sp, values["sustainedLoadKn"], values["settlingDepthM"]
        )
    return result(
        summary={
            "neutralPointDepthM": np_res["neutral"] / 1000.0,
            "dragloadKn": np_res["Qn"],
            "positiveShaftKn": np_res["Qbelow"],
            "netAllowableWithDowndragKn": max(0.0, sp["Qa"] - np_res["Qn"]),
        },
        tables=[
            table(
                "Downdrag and neutral point summary",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Settling zone bottom",
                        "value": np_res["settling"] / 1000.0,
                        "unit": "m",
                    },
                    {
                        "item": "Neutral point depth",
                        "value": np_res["neutral"] / 1000.0,
                        "unit": "m",
                    },
                    {
                        "item": "Negative skin friction (dragload)",
                        "value": np_res["Qn"],
                        "unit": "kN",
                    },
                    {
                        "item": "Positive shaft friction below neutral point",
                        "value": np_res["Qbelow"],
                        "unit": "kN",
                    },
                    {
                        "item": "Max axial force at neutral point",
                        "value": values["sustainedLoadKn"] + np_res["Qn"],
                        "unit": "kN",
                    },
                ],
            )
        ],
        notes=[f"Soil source: {src}. Tip capacity Qb = {np_res.get('Qb', 0.0):.1f} kN."],
    )


@feature(
    "foundationsPileAnalysis.groupEfficiency",
    "Group Efficiency",
    part="substructure",
    fields=[
        number("nx", "Piles along X", 3.0, min=1.0, max=20.0),
        number("ny", "Piles along Y", 2.0, min=1.0, max=20.0),
        number("spacingMm", "Centre-to-centre spacing", 1500.0, unit="mm", min=400.0),
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        number("lengthM", "Pile length L", 18.0, unit="m", min=2.0),
        number("headDepthM", "Cut-off depth", 1.5, unit="m", min=0.0),
        checkbox("cohesive", "Cohesive group soil (check block failure)", True),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def group_efficiency(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Converse-Labarre group efficiency, spacing factor zeta, and block capacity."""
    nx, ny = max(1, round(values["nx"])), max(1, round(values["ny"]))
    s, d = values["spacingMm"], values["diameterMm"]
    pts = np.array(
        [
            ((i - (nx - 1) / 2.0) * s, (j - (ny - 1) / 2.0) * s)
            for i in range(nx)
            for j in range(ny)
        ],
        dtype=float,
    )
    eff, m_rows, n_cols, theta_deg = pilecap.converse_labarre(pts, d)
    bg_m = ((nx - 1) * s + d) / 1000.0
    lg_m = ((ny - 1) * s + d) / 1000.0
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        sp = piles.single_pile(
            prof, "bored", d / 1000.0, values["lengthM"], values["headDepthM"], method="spt"
        )
        zeta = pile_static.zeta(s / 1000.0, d / 1000.0, values["cohesive"])
        block_q, block_note = pilecap.block_capacity(
            prof, values["headDepthM"], values["lengthM"], bg_m, lg_m, sp["qb"]
        )
    sum_single_qa = nx * ny * sp["Qa"]
    eff_qa = eff * sum_single_qa
    block_qa = (block_q / sp["factors"]["compression"]) if block_q is not None else sum_single_qa
    gov_qa = min(eff_qa, block_qa)
    return result(
        summary={
            "pileCount": nx * ny,
            "converseLabarre": eff,
            "packZeta": zeta if zeta is not None else eff,
            "sumSingleAllowableKn": sum_single_qa,
            "blockAllowableKn": block_qa,
            "governingGroupAllowableKn": gov_qa,
        },
        tables=[
            table(
                "Pile group efficiency and block capacity",
                [("item", "Metric"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": f"Grid ({m_rows}×{n_cols}, θ={theta_deg:.1f}°)",
                        "value": eff,
                        "unit": "-",
                    },
                    {
                        "item": "Sum of single pile allowable capacities",
                        "value": sum_single_qa,
                        "unit": "kN",
                    },
                    {"item": "Efficiency-factored group capacity", "value": eff_qa, "unit": "kN"},
                    {"item": "Block failure allowable capacity", "value": block_qa, "unit": "kN"},
                ],
            )
        ],
        notes=[f"Soil source: {src}. {block_note}"],
    )


@feature(
    "foundationsPileAnalysis.pileCapStiffness",
    "Pile Cap Stiffness",
    part="substructure",
    fields=[
        number("nx", "Piles along X", 2.0, min=1.0, max=20.0),
        number("ny", "Piles along Y", 2.0, min=1.0, max=20.0),
        number("spacingMm", "Pile spacing", 1800.0, unit="mm", min=400.0),
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        number("lengthM", "Pile length L", 18.0, unit="m", min=2.0),
        number("headDepthM", "Cut-off depth", 1.5, unit="m", min=0.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def pile_cap_stiffness(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute equivalent vertical, lateral, and rocking spring stiffnesses of a pile cap for the superstructure."""
    nx, ny = max(1, round(values["nx"])), max(1, round(values["ny"]))
    s, d_mm = values["spacingMm"], values["diameterMm"]
    pts = [
        ((i - (nx - 1) / 2.0) * s, (j - (ny - 1) / 2.0) * s) for i in range(nx) for j in range(ny)
    ]
    ec = 4700.0 * math.sqrt(values["fcMpa"])
    bg_m = ((nx - 1) * s + d_mm) / 1000.0
    lg_m = ((ny - 1) * s + d_mm) / 1000.0
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        sp = piles.single_pile(
            prof, "bored", d_mm / 1000.0, values["lengthM"], values["headDepthM"], method="spt"
        )
        grp_set = pile_settlement.group_settlement(
            prof, sp, len(pts), bg_m, lg_m, len(pts) * sp["Qa"] * 0.6, ec
        )
        stiff = pile_lateral.head_stiffness(
            prof, values["headDepthM"], "bored", d_mm, values["lengthM"] * 1000.0, ec, "fixed", 1.0
        )
        rx, _ = pile_lateral.group_ratio(pts, d_mm, 0)
        ry, _ = pile_lateral.group_ratio(pts, d_mm, 1)
    settle_m = max(grp_set["total"] / 1000.0, 1e-4)
    kz_cap = (len(pts) * sp["Qa"] * 0.6) / settle_m  # kN/m
    kz_single = kz_cap / len(pts)
    k_rock_x = kz_single * sum((v / 1000.0) ** 2 for _, v in pts)
    k_rock_y = kz_single * sum((u / 1000.0) ** 2 for u, _ in pts)
    kh_single = stiff["K"] if stiff else 0.0  # N/mm = kN/m
    kh_x = len(pts) * rx * kh_single
    kh_y = len(pts) * ry * kh_single
    return result(
        summary={
            "verticalStiffnessKnM": kz_cap,
            "lateralStiffnessXKnM": kh_x,
            "lateralStiffnessYKnM": kh_y,
            "rockingStiffnessXKnmRad": k_rock_x,
            "rockingStiffnessYKnmRad": k_rock_y,
        },
        tables=[
            table(
                "Pile cap superstructure spring matrix",
                [("dof", "Degree of freedom"), ("stiffness", "Stiffness"), ("unit", "Unit")],
                [
                    {"dof": "Vertical translation Kz", "stiffness": kz_cap, "unit": "kN/m"},
                    {"dof": "Lateral translation Kx", "stiffness": kh_x, "unit": "kN/m"},
                    {"dof": "Lateral translation Ky", "stiffness": kh_y, "unit": "kN/m"},
                    {"dof": "Rocking about X (Krx)", "stiffness": k_rock_x, "unit": "kN·m/rad"},
                    {"dof": "Rocking about Y (Kry)", "stiffness": k_rock_y, "unit": "kN·m/rad"},
                ],
            )
        ],
        notes=[f"Soil source: {src}. Group settlement at 60% Qa = {grp_set['total']:.2f} mm."],
    )


@feature(
    "foundationsPileAnalysis.loadDistribution",
    "Load Distribution",
    part="substructure",
    fields=[
        number("verticalKn", "Column load V", 2200.0, unit="kN", min=0.0),
        number("hxKn", "Shear Hx", 120.0, unit="kN"),
        number("hyKn", "Shear Hy", 80.0, unit="kN"),
        number("mxKnm", "Moment Mx", 140.0, unit="kN·m"),
        number("myKnm", "Moment My", 100.0, unit="kN·m"),
        number("pileDiaMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        text(
            "pileCoordsMm",
            "Pile coordinates u,v [mm] pairs",
            "-900,-900; 900,-900; -900,900; 900,900",
        ),
    ],
    requires_project=False,
)
def load_distribution(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Distribute column axial, shear, and biaxial moment demands across the pile group."""
    coords = parse_pairs(values["pileCoordsMm"], "Pile coordinates")
    spec = pilecap.CapSpec(
        "GRP",
        4000.0,
        4000.0,
        800.0,
        125.0,
        30.0,
        420.0,
        [ColumnBase("C1", 0.0, 0.0, 400.0, 400.0)],
        coords,
        values["pileDiaMm"],
    )
    load_vec = np.array([values["verticalKn"] * 1e3, values["mxKnm"] * 1e6, values["myKnm"] * 1e6])
    rxns, _ = pilecap.pile_reactions(spec, [load_vec])
    p_kn = [float(r) / 1e3 for r in rxns]
    with in_force(ctx.root):
        rx_ratio, _ = pile_lateral.group_ratio(coords, values["pileDiaMm"], 0)
        ry_ratio, _ = pile_lateral.group_ratio(coords, values["pileDiaMm"], 1)
    hx_each = values["hxKn"] / len(coords)
    hy_each = values["hyKn"] / len(coords)
    rows = [
        {"pile": f"P{i + 1}", "uMm": u, "vMm": v, "axialKn": p, "hxKn": hx_each, "hyKn": hy_each}
        for i, ((u, v), p) in enumerate(zip(coords, p_kn, strict=True))
    ]
    return result(
        summary={
            "pileCount": len(coords),
            "maxAxialKn": max(p_kn),
            "minAxialKn": min(p_kn),
            "shearPerPileXKn": hx_each,
            "shearPerPileYKn": hy_each,
            "lateralGroupRatioX": rx_ratio,
            "lateralGroupRatioY": ry_ratio,
        },
        tables=[
            table(
                "Distributed pile head forces",
                [
                    ("pile", "Pile"),
                    ("uMm", "u", "mm"),
                    ("vMm", "v", "mm"),
                    ("axialKn", "Axial N", "kN"),
                    ("hxKn", "Hx", "kN"),
                    ("hyKn", "Hy", "kN"),
                ],
                rows,
            )
        ],
        notes=[
            "Axial reactions from rigid cap assumption; lateral shear shared equally across piles."
        ],
    )


@feature(
    "foundationsPileAnalysis.tZCurves",
    "t-z Curves",
    part="substructure",
    fields=[
        number("depthM", "Target layer depth z", 6.0, unit="m", min=0.5),
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        number("lengthM", "Pile length L", 18.0, unit="m", min=2.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def tz_curves(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate axial shaft load-transfer (t-z) and tip (q-z) curves at the target depth."""
    z = values["depthM"]
    d_m = values["diameterMm"] / 1000.0
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        sp = piles.single_pile(prof, "bored", d_m, values["lengthM"], 1.0, method="spt")
    layer = prof.layer_at(z)
    if layer is None:
        raise FeatureInputError(f"Depth {z:g} m exceeds borehole depth {prof.bottom:g} m.")
    layer_row = next((r for r in sp["layers"] if r["layer"] == layer.index), None)
    fs_ult = float(layer_row["fs"]) if layer_row else 35.0
    qb_ult = float(sp["qb"])
    is_cohesive = layer.behaviour == "cohesive"
    # API RP 2A normalized t-z (z/D or z/z_max) and Vijayvergiya / API q-z
    z_peak_mm = 0.01 * values["diameterMm"] if is_cohesive else 5.0
    ratios = [
        (0.0, 0.0),
        (0.16, 0.30),
        (0.31, 0.50),
        (0.57, 0.75),
        (0.80, 0.90),
        (1.0, 1.0),
        (2.0, 0.90 if is_cohesive else 1.0),
    ]
    rows = []
    for rz, rt in ratios:
        disp_mm = rz * z_peak_mm
        t_kpa = rt * fs_ult
        # Tip mobilization peaks near 0.10 D
        qz_ratio = min(1.0, (disp_mm / (0.10 * values["diameterMm"])) ** 0.5)
        rows.append({"dispMm": disp_mm, "tKpa": t_kpa, "qTipKpa": qz_ratio * qb_ult})
    return result(
        summary={
            "layerSoil": layer.soil_type,
            "peakFsKpa": fs_ult,
            "peakDispMm": z_peak_mm,
            "tipQbKpa": qb_ult,
        },
        tables=[
            table(
                f"Axial t-z & q-z curves at z = {z:g} m",
                [
                    ("dispMm", "Displacement z", "mm"),
                    ("tKpa", "Shaft t", "kPa"),
                    ("qTipKpa", "Tip q", "kPa"),
                ],
                rows,
            )
        ],
        notes=[
            f"Soil source: {src}. Normalized API RP 2A load-transfer shape anchored to layer fs and tip qb."
        ],
    )


@feature(
    "foundationsPileAnalysis.pYCurves",
    "P-y Curves",
    part="substructure",
    fields=[
        number("depthM", "Depth z below ground", 4.0, unit="m", min=0.2),
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def py_curves(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate lateral p-y curve coordinates for the pile at the selected depth."""
    z = values["depthM"]
    d_m = values["diameterMm"] / 1000.0
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        rules = pile_lateral_soil.py_rules()
        layer = prof.layer_at(z)
        if layer is None:
            raise FeatureInputError(f"Depth {z:g} m exceeds profile bottom {prof.bottom:g} m.")
        sigma = prof.sigma_v_eff(z)
        wet = prof.water_table is not None and z > prof.water_table
        built = pile_lateral_soil.py_curve(layer, z, d_m, sigma, wet, rules)
    if built is None:
        raise FeatureInputError("Layer lacks strength data (cu or φ') for p-y generation.")
    fn, model = built
    ys = [0.0, 1.0, 3.0, 6.0, 12.0, 25.0, 50.0, 80.0, 120.0]
    rows = [{"yMm": y, "pKnPerM": fn(y / 1000.0)} for y in ys]
    return result(
        summary={"depthM": z, "model": model, "pUltimateKnPerM": rows[-1]["pKnPerM"]},
        tables=[
            table(
                f"Lateral p-y curve at z = {z:g} m",
                [("yMm", "y", "mm"), ("pKnPerM", "p", "kN/m")],
                rows,
            )
        ],
        notes=[f"Soil source: {src}. Model: {model}."],
    )


@feature(
    "foundationsPileAnalysis.capacityReport",
    "Capacity Report",
    part="substructure",
    fields=[
        select("kind", "Pile type", _KIND_OPTS),
        select("method", "Capacity method", _METHOD_OPTS, default="spt"),
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        number("lengthM", "Pile length L", 18.0, unit="m", min=2.0),
        number("headDepthM", "Cut-off depth", 1.5, unit="m", min=0.0),
        number("workingLoadKn", "Working axial load", 500.0, unit="kN", min=10.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=True,
)
def capacity_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Publish a Markdown pile capacity calculation report into 09 Substructure/exports."""
    d_m = values["diameterMm"] / 1000.0
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        sp = piles.single_pile(
            prof,
            values["kind"],
            d_m,
            values["lengthM"],
            values["headDepthM"],
            method=values["method"],
        )
        ss = pile_settlement.single_settlement(sp, values["workingLoadKn"], prof, 28000.0)
    lines = [
        f"# Pile Capacity Calculation Report ({values['kind']} Ø{values['diameterMm']:g} × {values['lengthM']:g} m)",
        "",
        f"- Soil source: {src}",
        f"- Capacity method: {sp['method']}",
        f"- Ultimate skin friction Qs: {sp['Qs']:.1f} kN",
        f"- Ultimate end bearing Qb: {sp['Qb']:.1f} kN (qb = {sp['qb']:.1f} kPa)",
        f"- Ultimate compression Qult: {sp['Qult']:.1f} kN",
        f"- Allowable compression Qa: {sp['Qa']:.1f} kN (governs: {sp['governs']})",
        f"- Allowable uplift Ta: {sp['Ta']:.1f} kN",
        f"- Single-pile settlement at {values['workingLoadKn']:.0f} kN: {ss['total'] if ss else 0.0:.2f} mm",
        "",
        "## Layer Breakdown",
        "| Layer | Soil | Top [m] | Bottom [m] | fs [kPa] | Qs [kN] |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for r in sp["layers"]:
        lines.append(
            f"| {r['layer'] + 1} | {r['soilType']} | {r['top'] / 1000:.2f} | {r['bottom'] / 1000:.2f} | {r['fs']:.1f} | {r['Qs']:.1f} |"
        )
    out_path = export_file(ctx, "pile-capacity-report.md", "\n".join(lines) + "\n")
    return result(
        summary={
            "allowableCompressionKn": sp["Qa"],
            "allowableUpliftKn": sp["Ta"],
            "reportPath": str(out_path),
        },
        tables=[
            table(
                "Layer capacity summary",
                [("layer", "Layer"), ("soilType", "Soil"), ("fs", "fs", "kPa"), ("Qs", "Qs", "kN")],
                sp["layers"],
            )
        ],
        notes=[f"Report written to {out_path}"],
    )


@feature(
    "foundationsPileAnalysis.elasticSettlement",
    "Elastic Settlement",
    part="substructure",
    fields=[
        number("workingLoadKn", "Working axial load Q", 550.0, unit="kN", min=1.0),
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        number("lengthM", "Pile length L", 18.0, unit="m", min=2.0),
        number("headDepthM", "Cut-off depth", 1.5, unit="m", min=0.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def elastic_settlement(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute single-pile immediate settlement (axial shortening, tip, and shaft components)."""
    ec = 4700.0 * math.sqrt(values["fcMpa"])
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        sp = piles.single_pile(
            prof,
            "bored",
            values["diameterMm"] / 1000.0,
            values["lengthM"],
            values["headDepthM"],
            method="spt",
        )
        ss = pile_settlement.single_settlement(sp, values["workingLoadKn"], prof, ec)
    if ss is None:
        raise FeatureInputError("Code pack does not define single-pile settlement parameters.")
    rows = [
        {"component": "Axial elastic shortening (Sax)", "mm": ss["Sax"]},
        {"component": "Tip settlement (Spt)", "mm": ss["Spt"]},
        {"component": "Shaft load transfer (Ssf)", "mm": ss["Ssf"]},
        {"component": "Total single-pile settlement (St)", "mm": ss["total"]},
    ]
    return result(
        summary={
            "totalSettlementMm": ss["total"],
            "axialShorteningMm": ss["Sax"],
            "tipSettlementMm": ss["Spt"],
            "shaftSettlementMm": ss["Ssf"],
        },
        tables=[
            table(
                "Single-pile elastic settlement",
                [("component", "Component"), ("mm", "Settlement", "mm")],
                rows,
            )
        ],
        notes=[f"Soil source: {src}. {ss.get('method', '')}"],
    )


@feature(
    "foundationsPileAnalysis.consolidationAroundPile",
    "Consolidation Around Pile",
    part="substructure",
    fields=[
        number("groupLoadKn", "Total working load on pile group", 2800.0, unit="kN", min=10.0),
        number("nx", "Piles along X", 2.0, min=1.0, max=20.0),
        number("ny", "Piles along Y", 2.0, min=1.0, max=20.0),
        number("spacingMm", "Pile spacing", 1800.0, unit="mm", min=400.0),
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        number("lengthM", "Pile length L", 18.0, unit="m", min=2.0),
        number("headDepthM", "Cut-off depth", 1.5, unit="m", min=0.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def consolidation_around_pile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute equivalent-raft consolidation and long-term settlement around a pile group."""
    nx, ny = max(1, round(values["nx"])), max(1, round(values["ny"]))
    s, d = values["spacingMm"], values["diameterMm"]
    bg_m = ((nx - 1) * s + d) / 1000.0
    lg_m = ((ny - 1) * s + d) / 1000.0
    ec = 4700.0 * math.sqrt(values["fcMpa"])
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        sp = piles.single_pile(
            prof, "bored", d / 1000.0, values["lengthM"], values["headDepthM"], method="spt"
        )
        gs = pile_settlement.group_settlement(
            prof, sp, nx * ny, bg_m, lg_m, values["groupLoadKn"], ec
        )
    return result(
        summary={
            "totalGroupSettlementMm": gs["total"],
            "shortTermMm": gs.get("shortTerm", 0.0),
            "longTermMm": gs.get("longTerm", 0.0),
            "consolidationMm": gs.get("consolidation", 0.0),
            "janbuMm": gs.get("janbu", 0.0),
        },
        tables=[
            table(
                "Pile group consolidation & total settlement",
                [("item", "Component"), ("val", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Short-term group settlement",
                        "val": gs.get("shortTerm", 0.0),
                        "unit": "mm",
                    },
                    {
                        "item": "1D clay consolidation",
                        "val": gs.get("consolidation", 0.0),
                        "unit": "mm",
                    },
                    {
                        "item": "Janbu modulus-number settlement",
                        "val": gs.get("janbu", 0.0),
                        "unit": "mm",
                    },
                    {
                        "item": "Total long-term settlement",
                        "val": gs.get("longTerm", 0.0),
                        "unit": "mm",
                    },
                    {"item": "Total group settlement", "val": gs["total"], "unit": "mm"},
                ],
            )
        ],
        notes=[f"Soil source: {src}. Equivalent block footprint {bg_m:.2f} × {lg_m:.2f} m."],
    )


@feature(
    "foundationsPileAnalysis.timeSettlementCurve",
    "Time Settlement Curve",
    part="substructure",
    fields=[
        number("immediateMm", "Short-term immediate settlement", 12.0, unit="mm", min=0.0),
        number(
            "consolidationMm", "Ultimate primary consolidation settlement", 35.0, unit="mm", min=0.0
        ),
        number("cvM2Yr", "Coefficient of consolidation cv", 3.0, unit="m²/yr", min=0.05),
        number("drainagePathM", "Drainage path Hdr", 4.0, unit="m", min=0.2),
        number("maxYears", "Duration to plot", 20.0, unit="years", min=1.0),
    ],
    requires_project=False,
)
def time_settlement_curve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute time-settlement progression using Terzaghi 1D consolidation degree U(Tv)."""
    cv, hdr = values["cvM2Yr"], values["drainagePathM"]
    s0, sc = values["immediateMm"], values["consolidationMm"]
    times = [0.0, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, values["maxYears"]]
    rows = []
    for t in sorted(set(times)):
        tv = cv * t / (hdr**2)
        if tv <= 0:
            u = 0.0
        elif tv < 0.2827:
            u = math.sqrt(4.0 * tv / math.pi)
        else:
            u = 1.0 - (8.0 / math.pi**2) * math.exp(-(math.pi**2) * tv / 4.0)
        u = min(max(u, 0.0), 1.0)
        rows.append({"years": t, "tv": tv, "degreePct": u * 100.0, "settlementMm": s0 + u * sc})
    return result(
        summary={
            "ultimateSettlementMm": s0 + sc,
            "finalPlottedMm": rows[-1]["settlementMm"],
            "finalConsolidationPct": rows[-1]["degreePct"],
        },
        tables=[
            table(
                "Time-settlement curve",
                [
                    ("years", "Time", "yr"),
                    ("tv", "Tv"),
                    ("degreePct", "U", "%"),
                    ("settlementMm", "Settlement", "mm"),
                ],
                rows,
            )
        ],
        notes=["1D consolidation degree U(Tv) combined with immediate elastic settlement."],
    )


@feature(
    "foundationsPileAnalysis.lateralResponsePlot",
    "Lateral Response Plot",
    part="substructure",
    fields=[
        number("shearKn", "Applied lateral shear H", 80.0, unit="kN", min=0.1),
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        number("lengthM", "Pile length L", 15.0, unit="m", min=2.0),
        number("headDepthM", "Cut-off depth", 1.0, unit="m", min=0.0),
        select("fixity", "Head restraint", [("fixed", "Fixed"), ("free", "Free")]),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def lateral_response_plot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate pile lateral deflection y(z) and rotation along depth under lateral load."""
    d_m = values["diameterMm"] / 1000.0
    ec = 4700.0 * math.sqrt(values["fcMpa"])
    ei = ec * 1e3 * (math.pi * d_m**4 / 64.0)
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        py_res = pile_lateral_soil.py_analysis(
            prof,
            values["headDepthM"],
            d_m,
            values["lengthM"],
            ei,
            values["fixity"],
            values["shearKn"],
        )
        stiff = pile_lateral.head_stiffness(
            prof,
            values["headDepthM"],
            "bored",
            values["diameterMm"],
            values["lengthM"] * 1000.0,
            ec,
            values["fixity"],
            1.0,
        )
    if py_res is None:
        raise FeatureInputError("Soil profile lacks lateral p-y parameters.")
    beta_m = (stiff["beta"] * 1e3) if stiff else 0.5
    kb_kn_m2 = (stiff["kB"] * 1e3) if stiff else 5000.0
    y0_mm = py_res["y0"] * 1000.0
    rows = []
    for i in range(11):
        z = min(values["lengthM"], i * (values["lengthM"] / 10.0))
        bz = beta_m * z
        decay = math.exp(-bz)
        y_mm = (
            y0_mm * decay * (math.cos(bz) + math.sin(bz))
            if values["fixity"] == "fixed"
            else y0_mm * decay * math.cos(bz)
        )
        p_kn_m = kb_kn_m2 * (y_mm / 1000.0)
        rows.append({"depthM": z, "yMm": y_mm, "pKnPerM": p_kn_m})
    return result(
        summary={
            "headDeflectionMm": y0_mm,
            "maxMomentKnm": float(py_res["Mmax"]),
        },
        tables=[
            table(
                "Lateral deflection & soil reaction with depth",
                [
                    ("depthM", "Depth", "m"),
                    ("yMm", "Deflection y", "mm"),
                    ("pKnPerM", "Soil reaction p", "kN/m"),
                ],
                rows,
            )
        ],
        notes=[f"Soil source: {src}."],
    )


@feature(
    "foundationsPileAnalysis.soilReactionCurve",
    "Soil Reaction Curve",
    part="substructure",
    fields=[
        number("shearKn", "Applied lateral shear H", 80.0, unit="kN", min=0.1),
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        number("lengthM", "Pile length L", 15.0, unit="m", min=2.0),
        number("headDepthM", "Cut-off depth", 1.0, unit="m", min=0.0),
        select("fixity", "Head restraint", [("fixed", "Fixed"), ("free", "Free")]),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def soil_reaction_curve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute mobilised soil reaction p(z) and pressure p(z)/D along the pile length."""
    d_m = values["diameterMm"] / 1000.0
    ec = 4700.0 * math.sqrt(values["fcMpa"])
    ei = ec * 1e3 * (math.pi * d_m**4 / 64.0)
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        py_res = pile_lateral_soil.py_analysis(
            prof,
            values["headDepthM"],
            d_m,
            values["lengthM"],
            ei,
            values["fixity"],
            values["shearKn"],
        )
        stiff = pile_lateral.head_stiffness(
            prof,
            values["headDepthM"],
            "bored",
            values["diameterMm"],
            values["lengthM"] * 1000.0,
            ec,
            values["fixity"],
            1.0,
        )
    if py_res is None:
        raise FeatureInputError("Soil profile lacks p-y parameters.")
    beta_m = (stiff["beta"] * 1e3) if stiff else 0.5
    kb_kn_m2 = (stiff["kB"] * 1e3) if stiff else 5000.0
    y0_m = py_res["y0"]
    rows = []
    for i in range(11):
        z = min(values["lengthM"], i * (values["lengthM"] / 10.0))
        bz = beta_m * z
        decay = math.exp(-bz)
        y_m = (
            y0_m * decay * (math.cos(bz) + math.sin(bz))
            if values["fixity"] == "fixed"
            else y0_m * decay * math.cos(bz)
        )
        p_kn_m = kb_kn_m2 * y_m
        rows.append({"depthM": z, "pKnPerM": p_kn_m, "stressKpa": p_kn_m / d_m})
    peak_p = max(abs(r["pKnPerM"]) for r in rows)
    return result(
        summary={"peakReactionKnPerM": peak_p, "peakBearingStressKpa": peak_p / d_m},
        tables=[
            table(
                "Mobilised lateral soil reaction profile",
                [
                    ("depthM", "Depth", "m"),
                    ("pKnPerM", "p(z)", "kN/m"),
                    ("stressKpa", "p/D", "kPa"),
                ],
                rows,
            )
        ],
        notes=[f"Soil source: {src}."],
    )


@feature(
    "foundationsPileAnalysis.shearCurve",
    "Shear Curve",
    part="substructure",
    fields=[
        number("shearKn", "Applied lateral shear H", 90.0, unit="kN", min=0.1),
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        number("lengthM", "Pile length L", 15.0, unit="m", min=2.0),
        number("headDepthM", "Cut-off depth", 1.0, unit="m", min=0.0),
        select("fixity", "Head restraint", [("fixed", "Fixed"), ("free", "Free")]),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def shear_curve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute shear force V(z) along a laterally loaded pile."""
    d_m = values["diameterMm"] / 1000.0
    ec = 4700.0 * math.sqrt(values["fcMpa"])
    ei = ec * 1e3 * (math.pi * d_m**4 / 64.0)
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        py_res = pile_lateral_soil.py_analysis(
            prof,
            values["headDepthM"],
            d_m,
            values["lengthM"],
            ei,
            values["fixity"],
            values["shearKn"],
        )
        stiff = pile_lateral.head_stiffness(
            prof,
            values["headDepthM"],
            "bored",
            values["diameterMm"],
            values["lengthM"] * 1000.0,
            ec,
            values["fixity"],
            1.0,
        )
    if py_res is None:
        raise FeatureInputError("Soil profile lacks p-y parameters.")
    beta_m = (stiff["beta"] * 1e3) if stiff else 0.5
    h_kn = values["shearKn"]
    rows = []
    for i in range(11):
        z = min(values["lengthM"], i * (values["lengthM"] / 10.0))
        bz = beta_m * z
        decay = math.exp(-bz)
        v_kn = (
            h_kn * decay * math.cos(bz)
            if values["fixity"] == "fixed"
            else h_kn * decay * (math.cos(bz) - math.sin(bz))
        )
        rows.append({"depthM": z, "shearKn": v_kn})
    return result(
        summary={"headShearKn": h_kn, "maxAbsShearKn": float(py_res["Vmax"])},
        tables=[
            table(
                "Pile lateral shear diagram",
                [("depthM", "Depth", "m"), ("shearKn", "Shear V", "kN")],
                rows,
            )
        ],
        notes=[f"Soil source: {src}."],
    )


@feature(
    "foundationsPileAnalysis.capacityRatio",
    "Capacity Ratio",
    part="substructure",
    fields=[
        number("axialDemandKn", "Service axial load P", 550.0, unit="kN", min=0.0),
        number("lateralDemandKn", "Service lateral shear H", 45.0, unit="kN", min=0.0),
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        number("lengthM", "Pile length L", 18.0, unit="m", min=2.0),
        number("headDepthM", "Cut-off depth", 1.5, unit="m", min=0.0),
        select("fixity", "Head restraint", [("fixed", "Fixed"), ("free", "Free")]),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def capacity_ratio(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare axial and lateral pile demands against geotechnical allowable capacities."""
    d_m = values["diameterMm"] / 1000.0
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        sp = piles.single_pile(
            prof, "bored", d_m, values["lengthM"], values["headDepthM"], method="spt"
        )
        br = pile_lateral_soil.broms_capacity(
            prof, values["headDepthM"], d_m, values["lengthM"], values["fixity"], None
        )
    qa_ax = float(sp["Qa"])
    ha_lat = (br["Hu"] / br["factor"]) if br else 100.0
    r_ax = values["axialDemandKn"] / max(qa_ax, 1e-6)
    r_lat = values["lateralDemandKn"] / max(ha_lat, 1e-6)
    return result(
        summary={
            "axialAllowableKn": qa_ax,
            "lateralAllowableKn": ha_lat,
            "axialRatio": r_ax,
            "lateralRatio": r_lat,
            "ok": r_ax <= 1.0 and r_lat <= 1.0,
        },
        tables=[
            table(
                "Pile axial & lateral capacity utilisation",
                [
                    ("mode", "Load mode"),
                    ("demandKn", "Demand", "kN"),
                    ("allowKn", "Allowable", "kN"),
                    ("ratio", "Ratio"),
                    ("status", "Status"),
                ],
                [
                    {
                        "mode": "Axial compression",
                        "demandKn": values["axialDemandKn"],
                        "allowKn": qa_ax,
                        "ratio": r_ax,
                        "status": "PASS" if r_ax <= 1.0 else "FAIL",
                    },
                    {
                        "mode": "Lateral (Broms soil)",
                        "demandKn": values["lateralDemandKn"],
                        "allowKn": ha_lat,
                        "ratio": r_lat,
                        "status": "PASS" if r_lat <= 1.0 else "FAIL",
                    },
                ],
            )
        ],
        notes=[f"Soil source: {src}."],
    )


@feature(
    "foundationsPileAnalysis.loadTestCompare",
    "Load Test Compare",
    part="substructure",
    fields=[
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        number("lengthM", "Pile length L", 18.0, unit="m", min=2.0),
        number("headDepthM", "Cut-off depth", 1.5, unit="m", min=0.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        text(
            "loadCurve",
            "Load [kN], movement [mm] pairs",
            "0,0; 300,1.5; 600,4.0; 900,8.5; 1200,16.0; 1500,29.0",
        ),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def load_test_compare(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare theoretical pile capacity against Davisson, Butler-Hoy, and Brinch-Hansen load test interpretations."""
    pts = parse_pairs(values["loadCurve"], "Load-settlement curve")
    d_mm, l_mm = values["diameterMm"], values["lengthM"] * 1000.0
    area_mm2 = math.pi * d_mm**2 / 4.0
    ec = 4700.0 * math.sqrt(values["fcMpa"])
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        sp = piles.single_pile(
            prof, "bored", d_mm / 1000.0, values["lengthM"], values["headDepthM"], method="spt"
        )
        dav = load_tests.davisson(pts, d_mm, l_mm, area_mm2, ec)
        bh = load_tests.brinch_hansen(pts)
        but = load_tests.butler_hoy(pts)
        q12, _ = load_tests.load_at(pts, 12.0)
    rows = [
        {"method": "Theoretical Qult (soil)", "loadKn": sp["Qult"]},
        {"method": "Davisson offset limit", "loadKn": dav if dav is not None else 0.0},
        {"method": "Brinch-Hansen 90%", "loadKn": bh if bh is not None else 0.0},
        {"method": "Butler-Hoy tangent", "loadKn": but if but is not None else 0.0},
        {"method": "Load at 12 mm movement", "loadKn": q12},
    ]
    return result(
        summary={
            "calculatedQultKn": sp["Qult"],
            "davissonKn": dav or 0.0,
            "brinchHansenKn": bh or 0.0,
            "loadAt12MmKn": q12,
        },
        tables=[
            table(
                "Calculated vs interpreted load test capacity",
                [("method", "Method"), ("loadKn", "Capacity", "kN")],
                rows,
            )
        ],
        notes=[f"Soil source: {src}. Max test load = {max(p for p, _ in pts):.0f} kN."],
    )


@feature(
    "foundationsPileAnalysis.designSummary",
    "Design Summary",
    part="substructure",
    fields=[
        select("kind", "Pile type", _KIND_OPTS),
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        number("lengthM", "Pile length L", 18.0, unit="m", min=2.0),
        number("headDepthM", "Cut-off depth", 1.5, unit="m", min=0.0),
        number("workingLoadKn", "Working axial load", 500.0, unit="kN", min=1.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def design_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarize governing axial, uplift, lateral capacities, and elastic settlement for a pile."""
    d_m = values["diameterMm"] / 1000.0
    ec = 4700.0 * math.sqrt(values["fcMpa"])
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        sp = piles.single_pile(
            prof, values["kind"], d_m, values["lengthM"], values["headDepthM"], method="spt"
        )
        ss = pile_settlement.single_settlement(sp, values["workingLoadKn"], prof, ec)
        br = pile_lateral_soil.broms_capacity(
            prof, values["headDepthM"], d_m, values["lengthM"], "fixed", None
        )
    rows = [
        {"metric": "Skin friction Qs", "value": sp["Qs"], "unit": "kN"},
        {"metric": "End bearing Qb", "value": sp["Qb"], "unit": "kN"},
        {"metric": "Allowable compression Qa", "value": sp["Qa"], "unit": "kN"},
        {"metric": "Allowable uplift Ta", "value": sp["Ta"], "unit": "kN"},
        {
            "metric": "Allowable lateral Ha (Broms)",
            "value": (br["Hu"] / br["factor"]) if br else 0.0,
            "unit": "kN",
        },
        {"metric": "Settlement at working load", "value": ss["total"] if ss else 0.0, "unit": "mm"},
    ]
    return result(
        summary={
            "allowableCompressionKn": sp["Qa"],
            "allowableUpliftKn": sp["Ta"],
            "allowableLateralKn": (br["Hu"] / br["factor"]) if br else 0.0,
            "settlementMm": ss["total"] if ss else 0.0,
        },
        tables=[
            table(
                "Pile design summary",
                [("metric", "Metric"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[f"Soil source: {src}. Governing compression formula: {sp['governs']}."],
    )


@feature(
    "foundationsPileAnalysis.sensitivityRun",
    "Sensitivity Run",
    part="substructure",
    fields=[
        number("diameterMm", "Baseline diameter D", 600.0, unit="mm", min=250.0),
        number("lengthM", "Baseline length L", 18.0, unit="m", min=3.0),
        number("headDepthM", "Cut-off depth", 1.5, unit="m", min=0.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def sensitivity_run(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Vary pile diameter and length around baseline to evaluate axial capacity sensitivity."""
    d0 = values["diameterMm"] / 1000.0
    l0 = values["lengthM"]
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        cases = [
            ("Baseline", d0, l0),
            ("Length -20%", d0, max(2.0, l0 * 0.8)),
            ("Length +20%", d0, min(prof.bottom - values["headDepthM"], l0 * 1.2)),
            ("Diameter -150 mm", max(0.3, d0 - 0.15), l0),
            ("Diameter +150 mm", d0 + 0.15, l0),
        ]
        rows = []
        base_qa = None
        for label, d_m, l_m in cases:
            sp = piles.single_pile(prof, "bored", d_m, l_m, values["headDepthM"], method="spt")
            if base_qa is None:
                base_qa = sp["Qa"]
            pct = ((sp["Qa"] / base_qa) - 1.0) * 100.0 if base_qa else 0.0
            rows.append(
                {
                    "case": label,
                    "diaMm": d_m * 1000.0,
                    "lenM": l_m,
                    "qaKn": sp["Qa"],
                    "deltaPct": pct,
                }
            )
    return result(
        summary={
            "baselineQaKn": base_qa or 0.0,
            "minQaKn": min(r["qaKn"] for r in rows),
            "maxQaKn": max(r["qaKn"] for r in rows),
        },
        tables=[
            table(
                "Pile capacity sensitivity matrix",
                [
                    ("case", "Variation"),
                    ("diaMm", "D", "mm"),
                    ("lenM", "L", "m"),
                    ("qaKn", "Qa", "kN"),
                    ("deltaPct", "Change", "%"),
                ],
                rows,
            )
        ],
        notes=[f"Soil source: {src}."],
    )

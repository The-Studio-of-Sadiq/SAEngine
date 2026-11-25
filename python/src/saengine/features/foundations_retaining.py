"""Substructure - Retaining Walls tab: cantilever, counterfort, sheet pile, stability & drainage."""

from __future__ import annotations

import csv
import io
import math
from typing import Any

import numpy as np

from saengine.design.bars import diameters, mesh_for, slab_flexure_need
from saengine.design.slab import one_way_shear
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
from saengine.features.foundations_common import build_profile, build_soil_column, export_file
from saengine.report.clauses import in_force
from saengine.soil import bearing as soil_bearing
from saengine.substructure import (
    earth_pressure,
    embedded_wall,
    excavation_support,
    retaining_walls,
    slope_stability,
)


def _wall_stability_eval(
    stem_h: float,
    toe: float,
    heel: float,
    stem_bot: float,
    base_t: float,
    gamma: float,
    phi: float,
    cohesion: float,
    surcharge: float,
    water_depth: float,
    drained: bool,
    passive_on: bool,
    mu_base: float,
) -> dict[str, Any]:
    """Evaluate active thrust, resisting vertical forces, sliding, overturning, and base bearing."""
    total_h = stem_h + base_t
    b_tot = toe + stem_bot + heel
    ka = earth_pressure.ka_rankine(phi)
    kp = earth_pressure.kp_rankine(phi)

    # Vertical loads (kN/m) and arms from toe (m)
    w_stem = 24.0 * stem_bot * stem_h
    x_stem = toe + stem_bot / 2.0
    w_base = 24.0 * b_tot * base_t
    x_base = b_tot / 2.0
    w_soil = gamma * heel * stem_h
    x_soil = toe + stem_bot + heel / 2.0
    sum_v = w_stem + w_base + w_soil
    m_res = w_stem * x_stem + w_base * x_base + w_soil * x_soil

    # Active soil & surcharge lateral thrust on vertical heel plane
    zw = total_h + 10.0 if drained else water_depth
    h_dry = min(total_h, zw)
    h_wet = max(0.0, total_h - zw)
    gamma_eff = max(gamma - 9.81, 6.0)

    pa_sur = ka * surcharge * total_h
    m_sur = pa_sur * (total_h / 2.0)

    # Dry soil wedge + rectangular continuation into wet zone + submerged triangle
    p1 = ka * gamma * h_dry
    pa_dry = 0.5 * p1 * h_dry
    arm_dry = h_wet + h_dry / 3.0
    pa_rect = p1 * h_wet
    arm_rect = h_wet / 2.0
    pa_sub = 0.5 * ka * gamma_eff * h_wet**2
    arm_sub = h_wet / 3.0
    pw = 0.5 * 9.81 * h_wet**2
    arm_pw = h_wet / 3.0
    # Cohesion tension reduction
    c_red = 2.0 * cohesion * math.sqrt(ka) * total_h
    pa_soil = max(0.0, pa_dry + pa_rect + pa_sub - c_red)

    sum_h = pa_sur + pa_soil + pw
    m_ovt = m_sur + pa_dry * arm_dry + pa_rect * arm_rect + pa_sub * arm_sub + pw * arm_pw

    # Uplift under base when undrained
    uplift = 0.5 * (9.81 * h_wet) * b_tot if (not drained and h_wet > 0) else 0.0
    m_uplift = uplift * (2.0 * b_tot / 3.0)
    net_v = max(0.0, sum_v - uplift)
    m_ovt_tot = m_ovt + m_uplift

    pp = 0.5 * kp * gamma * base_t**2 if passive_on else 0.0
    r_slide = net_v * mu_base + pp / 1.5
    fs_slide = r_slide / max(sum_h, 1e-6)
    fs_ovt = m_res / max(m_ovt_tot, 1e-6)

    x_res = (m_res - m_ovt_tot) / max(net_v, 1e-6)
    ecc = b_tot / 2.0 - x_res
    qmax, qmin, _ = retaining_walls.base_pressure(net_v, m_res - m_ovt_tot, b_tot)
    return {
        "totalH": total_h,
        "width": b_tot,
        "ka": ka,
        "kp": kp,
        "sumV": net_v,
        "sumH": sum_h,
        "mRes": m_res,
        "mOvt": m_ovt_tot,
        "fsSlide": fs_slide,
        "fsOvt": fs_ovt,
        "ecc": ecc,
        "qmax": qmax,
        "qmin": qmin,
        "paSoil": pa_soil,
        "paSur": pa_sur,
        "pw": pw,
    }


@feature(
    "foundationsRetaining.cantileverWall",
    "Cantilever Wall",
    part="substructure",
    fields=[
        number("stemHeightM", "Stem height above base", 4.0, unit="m", min=1.0),
        number("toeM", "Toe width", 0.7, unit="m", min=0.2),
        number("heelM", "Heel width", 1.8, unit="m", min=0.4),
        number("stemThickMm", "Stem base thickness", 400.0, unit="mm", min=200.0),
        number("baseThickMm", "Base thickness", 450.0, unit="mm", min=250.0),
        number("gamma", "Backfill unit weight", 18.0, unit="kN/m³", min=12.0),
        number("phi", "Backfill friction angle φ'", 30.0, unit="°", min=10.0, max=45.0),
        number("surcharge", "Retained surcharge", 10.0, unit="kPa", min=0.0),
        number("qaKpa", "Allowable bearing qa", 180.0, unit="kPa", min=30.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def cantilever_wall(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Design and check a cantilever retaining wall (stability + stem bending & shear)."""
    h_stem = values["stemHeightM"]
    t_stem = values["stemThickMm"] / 1000.0
    t_base = values["baseThickMm"] / 1000.0
    res = _wall_stability_eval(
        h_stem,
        values["toeM"],
        values["heelM"],
        t_stem,
        t_base,
        values["gamma"],
        values["phi"],
        0.0,
        values["surcharge"],
        100.0,
        True,
        False,
        0.5,
    )
    # Stem factored actions at top of base
    ka = res["ka"]
    h_factor = 1.6
    m_stem_uls = h_factor * (
        ka * values["gamma"] * h_stem**3 / 6.0 + ka * values["surcharge"] * h_stem**2 / 2.0
    )
    v_stem_uls = h_factor * (
        0.5 * ka * values["gamma"] * h_stem**2 + ka * values["surcharge"] * h_stem
    )
    d_mm = values["stemThickMm"] - 50.0 - 10.0
    with in_force(ctx.root):
        flex = slab_flexure_need(m_stem_uls * 1e6, d_mm, values["fcMpa"], values["fyMpa"])
        mesh = mesh_for(
            max(flex.area, 0.0015 * 1000.0 * values["stemThickMm"]), 300.0, diameters("wall")
        )
        phi_vc = one_way_shear(1000.0, d_mm, values["fcMpa"])[0] / 1e3
    return result(
        summary={
            "baseWidthM": res["width"],
            "fsOverturning": res["fsOvt"],
            "fsSliding": res["fsSlide"],
            "qmaxKpa": res["qmax"],
            "stemMomentKnmPerM": m_stem_uls,
            "stemShearKnPerM": v_stem_uls,
            "stemRebar": f"Ø{mesh.dia:g}@{mesh.spacing:g}" if mesh else "Increase stem",
        },
        tables=[
            table(
                "Cantilever retaining wall checks",
                [("check", "Check"), ("value", "Actual"), ("limit", "Limit"), ("status", "Status")],
                [
                    {
                        "check": "Overturning FS",
                        "value": res["fsOvt"],
                        "limit": "≥ 1.50",
                        "status": "PASS" if res["fsOvt"] >= 1.5 else "FAIL",
                    },
                    {
                        "check": "Sliding FS",
                        "value": res["fsSlide"],
                        "limit": "≥ 1.50",
                        "status": "PASS" if res["fsSlide"] >= 1.5 else "FAIL",
                    },
                    {
                        "check": "Base bearing qmax [kPa]",
                        "value": res["qmax"],
                        "limit": f"≤ {values['qaKpa']:g}",
                        "status": "PASS" if res["qmax"] <= values["qaKpa"] else "FAIL",
                    },
                    {
                        "check": "Stem shear Vu [kN/m]",
                        "value": v_stem_uls,
                        "limit": f"≤ {phi_vc:.1f}",
                        "status": "PASS" if v_stem_uls <= phi_vc else "FAIL",
                    },
                ],
            )
        ],
        notes=[
            f"Stem steel required As = {flex.area:.0f} mm²/m on soil face; base width = {res['width']:.2f} m."
        ],
    )


@feature(
    "foundationsRetaining.counterfortWall",
    "Counterfort Wall",
    part="substructure",
    fields=[
        number("stemHeightM", "Wall stem height H", 7.5, unit="m", min=3.0),
        number("counterfortSpacingM", "Counterfort centre spacing s", 3.2, unit="m", min=1.5),
        number("stemThickMm", "Stem slab thickness", 350.0, unit="mm", min=200.0),
        number("counterfortWidthMm", "Counterfort web thickness bw", 450.0, unit="mm", min=250.0),
        number("heelM", "Heel projection (counterfort depth)", 3.2, unit="m", min=1.0),
        number("gamma", "Backfill unit weight", 18.5, unit="kN/m³", min=12.0),
        number("phi", "Backfill friction angle φ'", 32.0, unit="°", min=15.0, max=45.0),
        number("surcharge", "Surcharge q", 12.0, unit="kPa", min=0.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def counterfort_wall(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Design stem horizontal slab strips and counterfort T-beam tension steel."""
    h, s = values["stemHeightM"], values["counterfortSpacingM"]
    ka = earth_pressure.ka_rankine(values["phi"])
    p_bot = ka * (values["gamma"] * h + values["surcharge"])
    h_factor = 1.6
    # Continuous horizontal stem span between counterforts: M- ≈ w s^2 / 12
    m_stem_neg = h_factor * p_bot * s**2 / 12.0
    m_stem_pos = h_factor * p_bot * s**2 / 16.0
    # Counterfort cantilever moment across tributary spacing s
    m_cf = (
        h_factor * s * (ka * values["gamma"] * h**3 / 6.0 + ka * values["surcharge"] * h**2 / 2.0)
    )
    d_stem = values["stemThickMm"] - 60.0
    d_cf = values["heelM"] * 1000.0 + values["stemThickMm"] - 100.0
    with in_force(ctx.root):
        as_stem = slab_flexure_need(m_stem_neg * 1e6, d_stem, values["fcMpa"], values["fyMpa"]).area
        as_cf = slab_flexure_need(
            m_cf * 1e6 / (values["counterfortWidthMm"] / 1000.0),
            d_cf,
            values["fcMpa"],
            values["fyMpa"],
        ).area * (values["counterfortWidthMm"] / 1000.0)
    return result(
        summary={
            "baseLateralPressureKpa": p_bot,
            "stemNegMomentKnmPerM": m_stem_neg,
            "stemPosMomentKnmPerM": m_stem_pos,
            "counterfortMomentKnm": m_cf,
            "stemHorizSteelMm2PerM": as_stem,
            "counterfortTieSteelMm2": as_cf,
        },
        tables=[
            table(
                "Counterfort wall design actions",
                [
                    ("element", "Component"),
                    ("moment", "Factored moment"),
                    ("unit", "Unit"),
                    ("steelMm2", "Required steel", "mm²"),
                ],
                [
                    {
                        "element": "Stem horizontal strip (support)",
                        "moment": m_stem_neg,
                        "unit": "kN·m/m",
                        "steelMm2": as_stem,
                    },
                    {
                        "element": "Counterfort cantilever stem",
                        "moment": m_cf,
                        "unit": "kN·m",
                        "steelMm2": as_cf,
                    },
                ],
            )
        ],
        notes=[
            "Provide horizontal stirrup ties anchoring the stem slab back into the counterfort web."
        ],
    )


@feature(
    "foundationsRetaining.sheetPileWall",
    "Sheet Pile Wall",
    part="substructure",
    fields=[
        number("excavationDepthM", "Retained height H", 4.5, unit="m", min=1.0),
        select(
            "support",
            "Wall support",
            [("cantilever", "Cantilever"), ("propped", "Propped near top")],
        ),
        number("propDepthM", "Prop depth below top (if propped)", 1.0, unit="m", min=0.2),
        number("surcharge", "Surface surcharge q", 10.0, unit="kPa", min=0.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def sheet_pile_wall(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute required embedment, maximum bending moment, and prop force for a sheet pile wall."""
    with in_force(ctx.root):
        soil = build_soil_column(ctx, borehole_id=values["borehole"], surcharge=values["surcharge"])
        res = embedded_wall.design_wall(
            soil,
            values["excavationDepthM"],
            values["support"],
            "free",
            values["propDepthM"] if values["support"] == "propped" else None,
            values["surcharge"],
        )
    if not res.get("ok", False):
        raise FeatureInputError(res.get("reason", "Embedded wall embedment could not be solved."))
    embedment = float(res.get("d", 0.0))
    total_len = values["excavationDepthM"] + embedment
    m_max = float(res.get("Mmax", 0.0))
    prop_force = float(res.get("T", 0.0) or 0.0)
    return result(
        summary={
            "embedmentM": embedment,
            "totalLengthM": total_len,
            "maxMomentKnmPerM": m_max,
            "propForceKnPerM": prop_force,
        },
        tables=[
            table(
                "Sheet pile wall design summary",
                [("param", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"param": "Retained height", "value": values["excavationDepthM"], "unit": "m"},
                    {"param": "Required embedment depth", "value": embedment, "unit": "m"},
                    {"param": "Total pile length", "value": total_len, "unit": "m"},
                    {"param": "Design bending moment", "value": m_max, "unit": "kN·m/m"},
                    {"param": "Design prop force", "value": prop_force, "unit": "kN/m"},
                ],
            )
        ],
        notes=[res.get("basis", "Designed using factored soil strength limit equilibrium.")],
    )


@feature(
    "foundationsRetaining.anchorsStruts",
    "Anchors & Struts",
    part="substructure",
    fields=[
        number("propForceKnPerM", "Required horizontal prop force", 140.0, unit="kN/m", min=5.0),
        number("spacingM", "Support spacing along wall", 3.0, unit="m", min=0.5),
        number("supportDepthM", "Support depth below ground", 2.0, unit="m", min=0.3),
        number("excavationDepthM", "Excavation depth", 7.0, unit="m", min=1.5),
        number(
            "inclinationDeg",
            "Anchor inclination below horizontal",
            20.0,
            unit="°",
            min=0.0,
            max=60.0,
        ),
        number("groutDiaMm", "Anchor grout hole diameter", 150.0, unit="mm", min=75.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def anchors_struts(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size ground anchor or strut forces, free length, and grouted bond capacity."""
    f_horiz = values["propForceKnPerM"] * values["spacingM"]
    theta = values["inclinationDeg"]
    t_axial = f_horiz / max(math.cos(math.radians(theta)), 0.2)
    with in_force(ctx.root):
        soil = build_soil_column(ctx, borehole_id=values["borehole"])
        rules = excavation_support.table()
        free_l = excavation_support.free_length(
            values["supportDepthM"], values["excavationDepthM"], theta, soil, rules
        )
        bond_6m = excavation_support.bond_capacity(
            soil, values["supportDepthM"], theta, free_l, 6.0, values["groutDiaMm"] / 1000.0, rules
        )
    req_bond = 6.0 * (t_axial / max(bond_6m, 1e-6))
    return result(
        summary={
            "horizontalLoadPerSupportKn": f_horiz,
            "axialSupportForceKn": t_axial,
            "freeLengthM": free_l,
            "bondCapacity6mKn": bond_6m,
            "estimatedFixedLengthM": max(3.0, req_bond),
        },
        tables=[
            table(
                "Anchor / strut design parameters",
                [("item", "Parameter"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"item": "Horizontal reaction per support", "val": f_horiz, "unit": "kN"},
                    {"item": "Inclined axial design load", "val": t_axial, "unit": "kN"},
                    {"item": "Minimum anchor free length", "val": free_l, "unit": "m"},
                    {"item": "Grout bond capacity per 6 m", "val": bond_6m, "unit": "kN"},
                    {"item": "Estimated fixed bond length", "val": max(3.0, req_bond), "unit": "m"},
                ],
            )
        ],
        notes=["Free length extends past the active failure wedge behind the excavation toe."],
    )


@feature(
    "foundationsRetaining.overturning",
    "Overturning",
    part="substructure",
    fields=[
        number("stemHeightM", "Stem height", 4.5, unit="m", min=1.0),
        number("toeM", "Toe width", 0.8, unit="m", min=0.1),
        number("heelM", "Heel width", 2.0, unit="m", min=0.2),
        number("stemThickMm", "Stem thickness", 400.0, unit="mm", min=150.0),
        number("baseThickMm", "Base thickness", 450.0, unit="mm", min=200.0),
        number("gamma", "Backfill unit weight", 18.0, unit="kN/m³", min=12.0),
        number("phi", "Friction angle φ'", 30.0, unit="°", min=10.0, max=45.0),
        number("surcharge", "Uniform surcharge", 10.0, unit="kPa", min=0.0),
        number("waterDepthM", "Water table below retained ground", 100.0, unit="m", min=0.0),
        checkbox("drained", "Wall drained (no hydrostatic pressure)", True),
    ],
    requires_project=False,
)
def overturning(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check retaining wall overturning stability about the front toe."""
    res = _wall_stability_eval(
        values["stemHeightM"],
        values["toeM"],
        values["heelM"],
        values["stemThickMm"] / 1000.0,
        values["baseThickMm"] / 1000.0,
        values["gamma"],
        values["phi"],
        0.0,
        values["surcharge"],
        values["waterDepthM"],
        values["drained"],
        False,
        0.5,
    )
    return result(
        summary={
            "resistingMomentKnmPerM": res["mRes"],
            "overturningMomentKnmPerM": res["mOvt"],
            "factorOfSafety": res["fsOvt"],
            "ok": res["fsOvt"] >= 1.5,
        },
        tables=[
            table(
                "Overturning moment balance about toe",
                [("item", "Moment component"), ("val", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Resisting moments (wall + heel soil)",
                        "val": res["mRes"],
                        "unit": "kN·m/m",
                    },
                    {
                        "item": "Overturning moments (earth + surcharge + water)",
                        "val": res["mOvt"],
                        "unit": "kN·m/m",
                    },
                    {
                        "item": "Factor of safety against overturning",
                        "val": res["fsOvt"],
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=["Minimum overturning FS = 1.50 (2.0 recommended for cohesive backfills)."],
    )


@feature(
    "foundationsRetaining.sliding",
    "Sliding",
    part="substructure",
    fields=[
        number("stemHeightM", "Stem height", 4.5, unit="m", min=1.0),
        number("toeM", "Toe width", 0.8, unit="m", min=0.1),
        number("heelM", "Heel width", 2.0, unit="m", min=0.2),
        number("stemThickMm", "Stem thickness", 400.0, unit="mm", min=150.0),
        number("baseThickMm", "Base thickness", 450.0, unit="mm", min=200.0),
        number("gamma", "Backfill unit weight", 18.0, unit="kN/m³", min=12.0),
        number("phi", "Friction angle φ'", 30.0, unit="°", min=10.0, max=45.0),
        number("muBase", "Base friction coefficient μ", 0.50, min=0.1, max=1.0),
        number("surcharge", "Uniform surcharge", 10.0, unit="kPa", min=0.0),
        checkbox("includePassive", "Count passive resistance at toe", False),
    ],
    requires_project=False,
)
def sliding(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check horizontal sliding stability at the retaining wall base."""
    res = _wall_stability_eval(
        values["stemHeightM"],
        values["toeM"],
        values["heelM"],
        values["stemThickMm"] / 1000.0,
        values["baseThickMm"] / 1000.0,
        values["gamma"],
        values["phi"],
        0.0,
        values["surcharge"],
        100.0,
        True,
        values["includePassive"],
        values["muBase"],
    )
    resisting_h = res["sumV"] * values["muBase"]
    return result(
        summary={
            "drivingHorizontalKnPerM": res["sumH"],
            "frictionResistanceKnPerM": resisting_h,
            "factorOfSafety": res["fsSlide"],
            "ok": res["fsSlide"] >= 1.5,
        },
        tables=[
            table(
                "Sliding stability summary",
                [("term", "Term"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"term": "Net vertical load ΣV", "val": res["sumV"], "unit": "kN/m"},
                    {"term": "Base friction resistance μΣV", "val": resisting_h, "unit": "kN/m"},
                    {"term": "Total horizontal thrust ΣH", "val": res["sumH"], "unit": "kN/m"},
                    {"term": "Sliding factor of safety", "val": res["fsSlide"], "unit": "-"},
                ],
            )
        ],
        notes=["Provide a shear key beneath the base if sliding FS < 1.50."],
    )


@feature(
    "foundationsRetaining.bearing",
    "Bearing",
    part="substructure",
    fields=[
        number("stemHeightM", "Stem height", 4.5, unit="m", min=1.0),
        number("toeM", "Toe width", 0.8, unit="m", min=0.1),
        number("heelM", "Heel width", 2.0, unit="m", min=0.2),
        number("stemThickMm", "Stem thickness", 400.0, unit="mm", min=150.0),
        number("baseThickMm", "Base thickness", 450.0, unit="mm", min=200.0),
        number("gamma", "Soil unit weight", 18.0, unit="kN/m³", min=12.0),
        number("phi", "Soil friction angle φ'", 30.0, unit="°", min=10.0, max=45.0),
        number("surcharge", "Uniform surcharge", 10.0, unit="kPa", min=0.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def bearing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check base bearing pressure and middle-third kern under the retaining wall."""
    res = _wall_stability_eval(
        values["stemHeightM"],
        values["toeM"],
        values["heelM"],
        values["stemThickMm"] / 1000.0,
        values["baseThickMm"] / 1000.0,
        values["gamma"],
        values["phi"],
        0.0,
        values["surcharge"],
        100.0,
        True,
        False,
        0.5,
    )
    with in_force(ctx.root):
        prof, src = build_profile(
            ctx, borehole_id=values["borehole"], phi=values["phi"], gamma=values["gamma"]
        )
        qa_info = soil_bearing.allowable(
            prof, res["width"], 20.0, values["baseThickMm"] / 1000.0 + 0.5
        )
    if qa_info.get("qa") is None:
        raise FeatureInputError(
            "Allowable bearing pressure could not be determined at the wall base depth (check soil strength / fill layer)."
        )
    qa = float(qa_info["qa"])
    in_kern = abs(res["ecc"]) <= res["width"] / 6.0
    return result(
        summary={
            "qmaxKpa": res["qmax"],
            "qminKpa": res["qmin"],
            "allowableBearingKpa": qa,
            "eccentricityM": res["ecc"],
            "inMiddleThird": in_kern,
            "bearingOk": res["qmax"] <= qa,
        },
        tables=[
            table(
                "Retaining wall base bearing check",
                [("item", "Parameter"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"item": "Base width B", "val": res["width"], "unit": "m"},
                    {"item": "Eccentricity e", "val": res["ecc"], "unit": "m"},
                    {"item": "Middle-third limit B/6", "val": res["width"] / 6.0, "unit": "m"},
                    {"item": "Toe pressure qmax", "val": res["qmax"], "unit": "kPa"},
                    {"item": "Heel pressure qmin", "val": res["qmin"], "unit": "kPa"},
                    {"item": "Allowable bearing qa", "val": qa, "unit": "kPa"},
                ],
            )
        ],
        notes=[f"Soil source: {src}. Resultant {'within' if in_kern else 'outside'} middle third."],
    )


@feature(
    "foundationsRetaining.globalStability",
    "Global Stability",
    part="substructure",
    fields=[
        number("wallHeightM", "Wall retained height H", 5.0, unit="m", min=1.5),
        number("baseWidthM", "Wall base width B", 3.2, unit="m", min=1.0),
        number("gamma", "Soil unit weight", 18.5, unit="kN/m³", min=12.0),
        number("cohesion", "Effective cohesion c'", 8.0, unit="kPa", min=0.0),
        number("phi", "Effective friction angle φ'", 30.0, unit="°", min=10.0, max=45.0),
        number("surcharge", "Backfill surcharge", 10.0, unit="kPa", min=0.0),
    ],
    requires_project=False,
)
def global_stability(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check overall circular slip stability around the retaining wall by Bishop's simplified method."""
    h, b = values["wallHeightM"], values["baseWidthM"]
    surf_pts = np.array([[-12.0, 0.0], [0.0, 0.0], [0.5, h], [15.0, h]], dtype=float)
    soil_props = slope_stability.SoilProps(
        id="S1",
        name="Backfill/Foundation",
        gamma=values["gamma"],
        gamma_sat=values["gamma"] + 1.5,
        c=values["cohesion"],
        phi=values["phi"],
        cu=None,
        undrained=False,
    )
    sec = slope_stability.Section(
        surface=surf_pts,
        lines=[],
        soils=[soil_props],
        base=-8.0,
        surcharges=[(0.5, 10.0, values["surcharge"], False)] if values["surcharge"] > 0 else [],
    ).mirror()
    case = slope_stability.Case(name="Static", required=1.5)
    with in_force(ctx.root):
        rules = slope_stability.table()
        best_fs = 99.0
        best_c = (0.0, 0.0, 0.0)
        for xc in (-1.0, 0.0, 1.0):
            for zc in (h + 1.0, h + 3.0, h + 5.0):
                for rad in (h + 3.0, h + 5.0, h + 7.5):
                    circle_surf = slope_stability.circle(sec, xc, zc, rad, min_depth=b * 0.5)
                    if circle_surf is None:
                        continue
                    res = slope_stability.evaluate(sec, circle_surf, "bishop", case, 20, rules)
                    if res is not None and res.fs < best_fs:
                        best_fs = res.fs
                        best_c = (-xc, zc, rad)
    if best_fs > 90.0:
        raise FeatureInputError("No valid deep-seated slip circle intersected the section.")
    return result(
        summary={
            "bishopFs": best_fs,
            "criticalXcM": best_c[0],
            "criticalZcM": best_c[1],
            "criticalRadiusM": best_c[2],
            "ok": best_fs >= 1.5,
        },
        tables=[
            table(
                "Global circular slope stability (Bishop)",
                [("item", "Parameter"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"item": "Minimum Bishop factor of safety", "val": best_fs, "unit": "-"},
                    {
                        "item": "Critical circle centre (x, z)",
                        "val": f"({best_c[0]:.1f}, {best_c[1]:.1f})",
                        "unit": "m",
                    },
                    {"item": "Critical slip radius R", "val": best_c[2], "unit": "m"},
                    {"item": "Required FS", "val": 1.5, "unit": "-"},
                ],
            )
        ],
        notes=[
            "Evaluated over a grid of deep slip circles passing beneath the retaining wall base."
        ],
    )


@feature(
    "foundationsRetaining.pressureDiagram",
    "Pressure Diagram",
    part="substructure",
    fields=[
        number("heightM", "Retained wall height H", 5.0, unit="m", min=0.5),
        select(
            "state",
            "Earth pressure state",
            [("active", "Active (Ka)"), ("atRest", "At rest (K0)"), ("passive", "Passive (Kp)")],
        ),
        number("gamma", "Soil unit weight", 18.0, unit="kN/m³", min=10.0),
        number("phi", "Friction angle φ'", 30.0, unit="°", min=5.0, max=45.0),
        number("cohesion", "Effective cohesion c'", 0.0, unit="kPa", min=0.0),
        number("waterDepthM", "Water table depth below top", 10.0, unit="m", min=0.0),
        number("surcharge", "Uniform surcharge", 10.0, unit="kPa", min=0.0),
        text("borehole", "Borehole ID (blank = manual)", "__manual__"),
    ],
    requires_project=False,
)
def pressure_diagram(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute design lateral earth, water, and surcharge pressure diagram with depth."""
    soil = build_soil_column(
        ctx,
        borehole_id=values["borehole"],
        gamma=values["gamma"],
        phi=values["phi"],
        cohesion=values["cohesion"],
        water_depth=values["waterDepthM"],
        surcharge=values["surcharge"],
        depth_m=values["heightM"] + 2.0,
    )
    h = values["heightM"]
    steps = 10
    rows = []
    pts = []
    for i in range(steps + 1):
        z = h * i / steps
        sv = soil.sigma_v_eff(z)
        u = soil.u(z)
        phi_l = soil.phi(z)
        c_l = soil.cohesion(z)
        if values["state"] == "active":
            k = earth_pressure.ka_rankine(phi_l or 30.0)
            p_soil = max(0.0, k * (sv + soil.surcharge) - 2.0 * c_l * math.sqrt(k))
        elif values["state"] == "atRest":
            k = earth_pressure.k0_jaky(phi_l or 30.0)
            p_soil = max(0.0, k * (sv + soil.surcharge))
        else:
            k = earth_pressure.kp_rankine(phi_l or 30.0)
            p_soil = k * (sv + soil.surcharge) + 2.0 * c_l * math.sqrt(k)
        p_tot = p_soil + u
        pts.append((z, p_tot))
        rows.append(
            {
                "depthM": z,
                "effVerticalKpa": sv,
                "soilPressKpa": p_soil,
                "waterPressKpa": u,
                "totalKpa": p_tot,
            }
        )
    force = sum(
        0.5 * (pts[i][1] + pts[i + 1][1]) * (pts[i + 1][0] - pts[i][0]) for i in range(steps)
    )
    return result(
        summary={
            "resultantKnPerM": force,
            "maxPressureKpa": rows[-1]["totalKpa"],
            "state": values["state"],
        },
        tables=[
            table(
                "Design lateral pressure diagram",
                [
                    ("depthM", "Depth", "m"),
                    ("effVerticalKpa", "σ'v", "kPa"),
                    ("soilPressKpa", "Soil", "kPa"),
                    ("waterPressKpa", "Water", "kPa"),
                    ("totalKpa", "Total", "kPa"),
                ],
                rows,
            )
        ],
        notes=[f"Computed with soil source: {soil.source}."],
    )


@feature(
    "foundationsRetaining.surchargeEffect",
    "Surcharge Effect",
    part="substructure",
    fields=[
        number("heightM", "Wall height H", 5.0, unit="m", min=0.5),
        number("stripLoadKpa", "Adjacent strip surcharge q", 40.0, unit="kPa", min=0.0),
        number("offsetM", "Clear distance from wall to strip", 1.0, unit="m", min=0.05),
        number("stripWidthM", "Width of strip load", 2.0, unit="m", min=0.2),
    ],
    requires_project=False,
)
def surcharge_effect(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute incremental lateral earth pressure on a wall due to an adjacent strip load."""
    h, q, near, w = (
        values["heightM"],
        values["stripLoadKpa"],
        values["offsetM"],
        values["stripWidthM"],
    )
    rows = []
    pts = []
    for i in range(11):
        z = h * i / 10.0
        p = 2.0 * excavation_support.strip_pressure(z, q, near, w, 0.0)
        pts.append((z, p))
        rows.append({"depthM": z, "pressureKpa": p})
    force = sum(0.5 * (pts[i][1] + pts[i + 1][1]) * (pts[i + 1][0] - pts[i][0]) for i in range(10))
    return result(
        summary={"incrementalForceKnPerM": force, "peakPressureKpa": max(p for _, p in pts)},
        tables=[
            table(
                "Surcharge lateral pressure profile",
                [("depthM", "Depth", "m"), ("pressureKpa", "Added lateral pressure", "kPa")],
                rows,
            )
        ],
        notes=["Doubled Boussinesq elastic strip pressure for rigid/low-yielding retaining walls."],
    )


@feature(
    "foundationsRetaining.groundwaterEffect",
    "Groundwater Effect",
    part="substructure",
    fields=[
        number("heightM", "Wall height H", 5.0, unit="m", min=1.0),
        number("waterDepthM", "Water table depth below top", 2.0, unit="m", min=0.0),
        number("gamma", "Moist unit weight γ", 18.0, unit="kN/m³", min=10.0),
        number("gammaSat", "Saturated unit weight γsat", 20.0, unit="kN/m³", min=12.0),
        number("phi", "Friction angle φ'", 30.0, unit="°", min=5.0, max=45.0),
    ],
    requires_project=False,
)
def groundwater_effect(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare dry vs partially submerged lateral thrust and overturning moment behind a wall."""
    h, zw = values["heightM"], values["waterDepthM"]
    ka = earth_pressure.ka_rankine(values["phi"])
    f_dry = 0.5 * ka * values["gamma"] * h**2
    h_dry = min(h, zw)
    h_wet = max(0.0, h - zw)
    g_eff = max(values["gammaSat"] - 9.81, 5.0)
    f_soil_wet = (
        0.5 * ka * values["gamma"] * h_dry**2
        + ka * values["gamma"] * h_dry * h_wet
        + 0.5 * ka * g_eff * h_wet**2
    )
    f_water = 0.5 * 9.81 * h_wet**2
    f_tot = f_soil_wet + f_water
    increase_pct = ((f_tot / max(f_dry, 1e-6)) - 1.0) * 100.0
    return result(
        summary={
            "dryThrustKnPerM": f_dry,
            "submergedSoilThrustKnPerM": f_soil_wet,
            "hydrostaticThrustKnPerM": f_water,
            "totalWetThrustKnPerM": f_tot,
            "thrustIncreasePct": increase_pct,
        },
        tables=[
            table(
                "Groundwater effect on lateral thrust",
                [("component", "Thrust component"), ("knPerM", "Force", "kN/m")],
                [
                    {"component": "Drained baseline (active soil only)", "knPerM": f_dry},
                    {"component": "Submerged effective soil thrust", "knPerM": f_soil_wet},
                    {"component": "Hydrostatic water thrust", "knPerM": f_water},
                    {"component": "Total undrained thrust", "knPerM": f_tot},
                ],
            )
        ],
        notes=[
            f"Water table at {zw:g} m increases total thrust by {increase_pct:.1f}% compared to drained backfill."
        ],
    )


@feature(
    "foundationsRetaining.weepHoles",
    "Weep Holes",
    part="substructure",
    fields=[
        number("wallHeightM", "Retained height H", 4.5, unit="m", min=1.0),
        number("pipeDiaMm", "Weep hole pipe diameter", 75.0, unit="mm", min=40.0),
        number("horizSpacingM", "Horizontal spacing", 2.0, unit="m", min=0.5),
        number("vertSpacingM", "Vertical spacing", 1.5, unit="m", min=0.5),
        number(
            "seepageFluxLpsM2", "Design seepage inflow per m² wall", 0.02, unit="L/s/m²", min=0.0001
        ),
    ],
    requires_project=False,
)
def weep_holes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check weep hole discharge capacity and filter geotextile requirements."""
    d_m = values["pipeDiaMm"] / 1000.0
    area_hole = math.pi * d_m**2 / 4.0
    # Gravity orifice discharge under 0.1 m local head: Q = Cd * A * sqrt(2 g h)
    q_hole_lps = 0.62 * area_hole * math.sqrt(2.0 * 9.81 * 0.10) * 1000.0
    trib_area = values["horizSpacingM"] * values["vertSpacingM"]
    inflow_lps = trib_area * values["seepageFluxLpsM2"]
    rows_count = max(1, int(values["wallHeightM"] / values["vertSpacingM"]))
    return result(
        summary={
            "holeCapacityLps": q_hole_lps,
            "tributaryInflowLps": inflow_lps,
            "capacityRatio": q_hole_lps / max(inflow_lps, 1e-6),
            "verticalRows": rows_count,
            "ok": q_hole_lps >= inflow_lps,
        },
        tables=[
            table(
                "Weep hole layout & hydraulic capacity",
                [("item", "Parameter"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"item": "Tributary wall area per weep hole", "val": trib_area, "unit": "m²"},
                    {"item": "Design inflow per weep hole", "val": inflow_lps, "unit": "L/s"},
                    {"item": "Orifice capacity (100 mm head)", "val": q_hole_lps, "unit": "L/s"},
                    {"item": "Vertical rows up stem", "val": rows_count, "unit": "rows"},
                ],
            )
        ],
        notes=["Provide graded gravel pocket + non-woven geotextile wrap behind every weep hole."],
    )


@feature(
    "foundationsRetaining.filterDrain",
    "Filter Drain",
    part="substructure",
    fields=[
        number("wallLengthM", "Wall run length", 30.0, unit="m", min=2.0),
        number("pipeDiaMm", "Perforated collector pipe diameter", 150.0, unit="mm", min=75.0),
        number("slopePct", "Collector pipe longitudinal slope", 0.5, unit="%", min=0.1, max=5.0),
        number("inflowLpsPerM", "Groundwater inflow per metre wall", 0.05, unit="L/s/m", min=0.001),
    ],
    requires_project=False,
)
def filter_drain(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size perforated collector pipe and gravel filter trench at the retaining wall heel."""
    d_m = values["pipeDiaMm"] / 1000.0
    area = math.pi * d_m**2 / 4.0
    rh = d_m / 4.0
    n_manning = 0.013
    slope = values["slopePct"] / 100.0
    q_full_lps = (1.0 / n_manning) * area * (rh ** (2.0 / 3.0)) * math.sqrt(slope) * 1000.0
    q_demand_lps = values["inflowLpsPerM"] * values["wallLengthM"]
    return result(
        summary={
            "fullPipeCapacityLps": q_full_lps,
            "totalInflowLps": q_demand_lps,
            "utilisation": q_demand_lps / max(q_full_lps, 1e-6),
            "ok": q_full_lps >= q_demand_lps,
        },
        tables=[
            table(
                "Base filter drain hydraulics",
                [("param", "Parameter"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"param": "Design inflow at outlet", "val": q_demand_lps, "unit": "L/s"},
                    {
                        "param": "Manning full-bore capacity (n=0.013)",
                        "val": q_full_lps,
                        "unit": "L/s",
                    },
                    {
                        "param": "Flow utilisation",
                        "val": q_demand_lps / max(q_full_lps, 1e-6),
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=[
            "Surround perforated pipe with minimum 300 × 300 mm open-graded drainage gravel wrapped in filter fabric."
        ],
    )


@feature(
    "foundationsRetaining.anchorDesign",
    "Anchor Design",
    part="substructure",
    fields=[
        number("workingLoadKn", "Design anchor working load Tw", 350.0, unit="kN", min=10.0),
        number("fpkMpa", "Strand ultimate strength fpk", 1860.0, unit="MPa", min=500.0),
        number("strandAreaMm2", "Single 15.2 mm strand area", 140.0, unit="mm²", min=50.0),
        number("groutDiaMm", "Drilled grout body diameter", 150.0, unit="mm", min=75.0),
        number("bondStrengthKpa", "Ultimate soil-grout bond τult", 220.0, unit="kPa", min=30.0),
        number("fsGrout", "Bond factor of safety", 2.5, min=1.5, max=4.0),
    ],
    requires_project=False,
)
def anchor_design(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size prestressing strands and grouted fixed bond length for a tieback ground anchor."""
    # Typical tendon design limit ~ 0.60 fpk * Aps
    req_steel_area = (values["workingLoadKn"] * 1e3) / (0.60 * values["fpkMpa"])
    n_strands = max(1, math.ceil(req_steel_area / values["strandAreaMm2"]))
    prov_area = n_strands * values["strandAreaMm2"]
    tau_allow = values["bondStrengthKpa"] / values["fsGrout"]
    perim_m = math.pi * (values["groutDiaMm"] / 1000.0)
    req_bond_m = max(3.0, values["workingLoadKn"] / (perim_m * tau_allow))
    return result(
        summary={
            "strandCount": n_strands,
            "providedTendonAreaMm2": prov_area,
            "allowableBondKpa": tau_allow,
            "requiredBondLengthM": req_bond_m,
            "tendonUtilisation": values["workingLoadKn"]
            / (0.60 * values["fpkMpa"] * prov_area / 1e3),
        },
        tables=[
            table(
                "Ground anchor tendon and bond design",
                [("item", "Item"), ("val", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Required steel area (at 0.60 fpk)",
                        "val": req_steel_area,
                        "unit": "mm²",
                    },
                    {"item": "Selected strands", "val": n_strands, "unit": "nr"},
                    {"item": "Allowable grout-soil bond", "val": tau_allow, "unit": "kPa"},
                    {"item": "Required fixed bond length", "val": req_bond_m, "unit": "m"},
                ],
            )
        ],
        notes=[
            "Verify minimum free length (≥ 4.5 m) extends behind the active soil failure wedge."
        ],
    )


@feature(
    "foundationsRetaining.anchorTesting",
    "Anchor Testing",
    part="substructure",
    fields=[
        number("workingLoadKn", "Design working load Tw", 350.0, unit="kN", min=10.0),
        select(
            "testType",
            "Test category",
            [
                ("proof", "Routine Proof Test (1.25–1.33 Tw)"),
                ("suitability", "Suitability / Performance Test (1.50 Tw)"),
            ],
        ),
        number("lockOffShare", "Lock-off load ratio (of Tw)", 0.80, min=0.50, max=1.05),
    ],
    requires_project=False,
)
def anchor_testing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate staged load increments, proof test load, and lock-off schedule for ground anchors."""
    tw = values["workingLoadKn"]
    mult = 1.33 if values["testType"] == "proof" else 1.50
    tmax = tw * mult
    lock_off = tw * values["lockOffShare"]
    steps = [0.10, 0.25, 0.50, 0.75, 1.00, 1.20, mult]
    rows = [
        {"stage": i + 1, "factor": f, "loadKn": f * tw, "holdMin": 15 if f == mult else 5}
        for i, f in enumerate(steps)
    ]
    return result(
        summary={
            "workingLoadKn": tw,
            "maxTestLoadKn": tmax,
            "lockOffLoadKn": lock_off,
            "stagesCount": len(rows),
        },
        tables=[
            table(
                "Anchor proof testing load sequence",
                [
                    ("stage", "Stage"),
                    ("factor", "Factor × Tw"),
                    ("loadKn", "Test load", "kN"),
                    ("holdMin", "Hold time", "min"),
                ],
                rows,
            )
        ],
        notes=[
            "Monitor dial gauge creep at peak load; acceptance requires creep ≤ 1–2 mm over final log cycle."
        ],
    )


@feature(
    "foundationsRetaining.wallSchedule",
    "Wall Schedule",
    part="substructure",
    fields=[
        number(
            "defaultHeightM", "Fallback stem height (if no walls in model)", 4.0, unit="m", min=1.0
        ),
        number("defaultThickMm", "Fallback stem thickness", 350.0, unit="mm", min=150.0),
    ],
    requires_project=True,
)
def wall_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Schedule retaining walls from 09 Substructure and export CSV to 09 Substructure/exports."""
    from saengine.features.foundations_common import load_substructure_model

    sub = load_substructure_model(ctx)
    rows = []
    if sub.retainingWalls:
        for w in sub.retainingWalls:
            h_m = (w.topLevel - (w.foundingLevel + w.baseThickness)) / 1000.0
            rows.append(
                {
                    "id": w.id,
                    "kind": w.kind,
                    "lengthM": w.length() / 1000.0,
                    "stemHeightM": h_m,
                    "stemBaseMm": w.stemBottom,
                    "baseThickMm": w.baseThickness,
                    "material": w.material,
                }
            )
    else:
        rows.append(
            {
                "id": "RW-TEMPLATE",
                "kind": "cantilever",
                "lengthM": 10.0,
                "stemHeightM": values["defaultHeightM"],
                "stemBaseMm": values["defaultThickMm"],
                "baseThickMm": values["defaultThickMm"] + 50.0,
                "material": "Concrete",
            }
        )
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "id",
            "kind",
            "lengthM",
            "stemHeightM",
            "stemBaseMm",
            "baseThickMm",
            "material",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)
    out_path = export_file(ctx, "retaining-wall-schedule.csv", buf.getvalue())
    return result(
        summary={"wallCount": len(rows), "csvPath": str(out_path)},
        tables=[
            table(
                "Retaining wall schedule",
                [
                    ("id", "Wall ID"),
                    ("kind", "Kind"),
                    ("lengthM", "Length", "m"),
                    ("stemHeightM", "Stem H", "m"),
                    ("stemBaseMm", "Stem base", "mm"),
                    ("baseThickMm", "Base", "mm"),
                ],
                rows,
            )
        ],
        notes=[f"Schedule exported to {out_path}"],
    )


@feature(
    "foundationsRetaining.stabilitySummary",
    "Stability Summary",
    part="substructure",
    fields=[
        number("stemHeightM", "Stem height", 4.5, unit="m", min=1.0),
        number("toeM", "Toe width", 0.8, unit="m", min=0.1),
        number("heelM", "Heel width", 2.0, unit="m", min=0.2),
        number("stemThickMm", "Stem thickness", 400.0, unit="mm", min=150.0),
        number("baseThickMm", "Base thickness", 450.0, unit="mm", min=200.0),
        number("gamma", "Soil unit weight", 18.0, unit="kN/m³", min=12.0),
        number("phi", "Friction angle φ'", 30.0, unit="°", min=10.0, max=45.0),
        number("surcharge", "Surcharge", 10.0, unit="kPa", min=0.0),
        number("qaKpa", "Allowable bearing qa", 180.0, unit="kPa", min=30.0),
        number("khSeismic", "Seismic horizontal coefficient kh", 0.10, min=0.0, max=0.40),
    ],
    requires_project=False,
)
def stability_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarize static and seismic overturning, sliding, and bearing stability checks on one page."""
    res = _wall_stability_eval(
        values["stemHeightM"],
        values["toeM"],
        values["heelM"],
        values["stemThickMm"] / 1000.0,
        values["baseThickMm"] / 1000.0,
        values["gamma"],
        values["phi"],
        0.0,
        values["surcharge"],
        100.0,
        True,
        False,
        0.5,
    )
    kae = earth_pressure.kae_mononobe_okabe(values["phi"], values["khSeismic"])
    d_kae = max(0.0, (kae - res["ka"])) if kae is not None else 0.0
    p_ae = 0.5 * values["gamma"] * res["totalH"] ** 2 * d_kae
    m_ae = p_ae * 0.6 * res["totalH"]
    fs_slide_eq = (res["sumV"] * 0.5) / max(res["sumH"] + p_ae, 1e-6)
    fs_ovt_eq = res["mRes"] / max(res["mOvt"] + m_ae, 1e-6)
    rows = [
        {
            "check": "Overturning (static)",
            "actual": res["fsOvt"],
            "required": 1.50,
            "status": "PASS" if res["fsOvt"] >= 1.5 else "FAIL",
        },
        {
            "check": "Sliding (static)",
            "actual": res["fsSlide"],
            "required": 1.50,
            "status": "PASS" if res["fsSlide"] >= 1.5 else "FAIL",
        },
        {
            "check": "Bearing qmax [kPa]",
            "actual": res["qmax"],
            "required": values["qaKpa"],
            "status": "PASS" if res["qmax"] <= values["qaKpa"] else "FAIL",
        },
        {
            "check": "Overturning (seismic M-O)",
            "actual": fs_ovt_eq,
            "required": 1.10,
            "status": "PASS" if fs_ovt_eq >= 1.1 else "FAIL",
        },
        {
            "check": "Sliding (seismic M-O)",
            "actual": fs_slide_eq,
            "required": 1.10,
            "status": "PASS" if fs_slide_eq >= 1.1 else "FAIL",
        },
    ]
    return result(
        summary={
            "staticOvtFs": res["fsOvt"],
            "staticSlideFs": res["fsSlide"],
            "qmaxKpa": res["qmax"],
            "seismicOvtFs": fs_ovt_eq,
            "seismicSlideFs": fs_slide_eq,
            "allChecksPass": all(r["status"] == "PASS" for r in rows),
        },
        tables=[
            table(
                "One-page retaining wall stability summary",
                [
                    ("check", "Stability check"),
                    ("actual", "Actual"),
                    ("required", "Limit"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
        notes=[
            f"Seismic increment computed by Mononobe-Okabe (kh = {values['khSeismic']:g}, Kae = {kae or 0:.3f}) acting at 0.6 H."
        ],
    )

"""Substructure - Shallow Foundations & Rafts tab: pad, combined, strap, raft, grade & tie beams."""

from __future__ import annotations

import math
from typing import Any

from saengine.design import rc
from saengine.design.bars import (
    beam_flexure_need,
    beam_shear_need,
    choose_stirrups,
    diameters,
    mesh_for,
    slab_flexure_need,
)
from saengine.design.punching import footing_punching, unit_relief
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
from saengine.features.foundations_common import build_profile
from saengine.report.clauses import in_force
from saengine.soil import bearing as soil_bearing
from saengine.soil import settlement as soil_settlement
from saengine.substructure import excavation, loads, raft, shallow, sizing

_SOIL_TYPE_OPTS = (("sand", "Sand (granular)"), ("clay", "Clay (cohesive)"), ("silt", "Silt"))


@feature(
    "foundations.padFooting",
    "Pad Footing",
    part="substructure",
    fields=[
        number("serviceLoad", "Column service axial load P", 800.0, unit="kN", min=1.0),
        number("momentX", "Service moment Mx", 40.0, unit="kN·m"),
        number("momentY", "Service moment My", 20.0, unit="kN·m"),
        number("loadFactor", "Ultimate/service load factor", 1.4, min=1.0, max=2.5),
        number("colX", "Column width c1", 400.0, unit="mm", min=100.0),
        number("colY", "Column depth c2", 400.0, unit="mm", min=100.0),
        number("lengthM", "Footing length L", 2.4, unit="m", min=0.5),
        number("widthM", "Footing width B", 2.4, unit="m", min=0.5),
        number("thicknessMm", "Footing thickness h", 500.0, unit="mm", min=200.0),
        number("depthM", "Founding depth Df", 1.5, unit="m", min=0.3),
        number("qaOverride", "Allowable bearing qa (0 = from soil)", 0.0, unit="kPa", min=0.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
        number("coverMm", "Bottom clear cover", 75.0, unit="mm", min=25.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def pad_footing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Design and check an isolated pad footing for bearing, shear, punching, and flexure."""
    l_m, b_m, df_m = values["lengthM"], values["widthM"], values["depthM"]
    h_mm, cover_mm = values["thicknessMm"], values["coverMm"]
    c1, c2 = values["colX"], values["colY"]
    fc, fy = values["fcMpa"], values["fyMpa"]
    p_serv = values["serviceLoad"]
    mx_s, my_s = values["momentX"], values["momentY"]
    lf = values["loadFactor"]

    d_mm = h_mm - cover_mm - 16.0
    if d_mm <= 50.0:
        raise FeatureInputError("Footing thickness is too small for the cover and rebar diameter.")

    with in_force(ctx.root):
        if values["qaOverride"] > 0:
            qa = float(values["qaOverride"])
            bearing_src = "User-specified qa"
        else:
            prof, src = build_profile(ctx, borehole_id=values["borehole"])
            res_b = soil_bearing.allowable(prof, min(b_m, l_m), max(b_m, l_m), df_m)
            if res_b.get("qa") is None:
                raise FeatureInputError(
                    "Allowable bearing could not be determined at the founding depth (check soil strength / fill)."
                )
            qa = float(res_b["qa"])
            bearing_src = f"{src} ({res_b.get('governs', 'bearing')})"

        self_wt = 24.0 * l_m * b_m * (h_mm / 1000.0)
        total_serv = p_serv + self_wt
        sp = shallow.soil_pressure(
            total_serv * 1e3,
            (my_s / total_serv) * 1e3 if total_serv > 0 else 0.0,
            (mx_s / total_serv) * 1e3 if total_serv > 0 else 0.0,
            l_m * 1e3,
            b_m * 1e3,
        )
        qmax_kpa = sp.qmax * 1e3
        bearing_ratio = qmax_kpa / qa if qa > 0 else float("inf")

        pu_kn = p_serv * lf
        qu_kpa = pu_kn / (l_m * b_m)
        punch = footing_punching(
            0.0,
            0.0,
            c1,
            c2,
            l_m * 1e3,
            b_m * 1e3,
            d_mm,
            fc,
            [("ULS", pu_kn * 1e3, mx_s * lf * 1e6, my_s * lf * 1e6, unit_relief(qu_kpa * 1e-3))],
        )
        punch_util = punch.utilisation if punch else 0.0

        cant_x = max(0.0, (l_m * 1e3 - c1) / 2.0)
        cant_y = max(0.0, (b_m * 1e3 - c2) / 2.0)
        mu_x = qu_kpa * (cant_x / 1000.0) ** 2 / 2.0  # kN.m/m
        mu_y = qu_kpa * (cant_y / 1000.0) ** 2 / 2.0
        flex_x = slab_flexure_need(mu_x * 1e6, d_mm, fc, fy)
        flex_y = slab_flexure_need(mu_y * 1e6, d_mm, fc, fy)
        as_min = shallow.min_steel_ratio(fy) * 1000.0 * h_mm
        req_x = max(flex_x.area, as_min)
        req_y = max(flex_y.area, as_min)
        mesh_x = mesh_for(req_x, min(3.0 * h_mm, 450.0), diameters("foundation"))
        mesh_y = mesh_for(req_y, min(3.0 * h_mm, 450.0), diameters("foundation"))

        shear_arm_x = max(0.0, cant_x - d_mm) / 1000.0
        vu_x = qu_kpa * shear_arm_x  # kN/m
        rho_x = (
            (mesh_x.dia**2 * math.pi / 4.0 * 1000.0 / mesh_x.spacing) / (1000.0 * d_mm)
            if mesh_x
            else req_x / (1000.0 * d_mm)
        )
        phi_vc = shallow.one_way_shear_capacity(1000.0, d_mm, rho_x, fc) / 1e3  # kN/m
        shear_util = vu_x / phi_vc if phi_vc > 0 else float("inf")

    rows = [
        {
            "check": "Bearing pressure (service)",
            "demand": qmax_kpa,
            "capacity": qa,
            "unit": "kPa",
            "ratio": bearing_ratio,
            "status": "PASS" if bearing_ratio <= 1.0 else "FAIL",
        },
        {
            "check": "Punching shear (ULS)",
            "demand": punch.vu if punch else 0.0,
            "capacity": punch.phi_vc if punch else 0.0,
            "unit": "MPa",
            "ratio": punch_util,
            "status": "PASS" if punch_util <= 1.0 else "FAIL",
        },
        {
            "check": "One-way shear (ULS)",
            "demand": vu_x,
            "capacity": phi_vc,
            "unit": "kN/m",
            "ratio": shear_util,
            "status": "PASS" if shear_util <= 1.0 else "FAIL",
        },
        {
            "check": "Flexure X steel",
            "demand": req_x,
            "capacity": (math.pi * mesh_x.dia**2 / 4 * 1000 / mesh_x.spacing) if mesh_x else 0.0,
            "unit": "mm²/m",
            "ratio": req_x / (math.pi * mesh_x.dia**2 / 4 * 1000 / mesh_x.spacing)
            if mesh_x
            else 9.99,
            "status": "PASS" if mesh_x else "FAIL",
        },
        {
            "check": "Flexure Y steel",
            "demand": req_y,
            "capacity": (math.pi * mesh_y.dia**2 / 4 * 1000 / mesh_y.spacing) if mesh_y else 0.0,
            "unit": "mm²/m",
            "ratio": req_y / (math.pi * mesh_y.dia**2 / 4 * 1000 / mesh_y.spacing)
            if mesh_y
            else 9.99,
            "status": "PASS" if mesh_y else "FAIL",
        },
    ]
    return result(
        summary={
            "allowableBearingKpa": qa,
            "maxBearingKpa": qmax_kpa,
            "bearingRatio": bearing_ratio,
            "punchingRatio": punch_util,
            "oneWayShearRatio": shear_util,
            "rebarX": f"Ø{mesh_x.dia:g}@{mesh_x.spacing:g}" if mesh_x else "Insufficient depth",
            "rebarY": f"Ø{mesh_y.dia:g}@{mesh_y.spacing:g}" if mesh_y else "Insufficient depth",
            "overallOk": all(r["status"] == "PASS" for r in rows),
        },
        tables=[
            table(
                "Pad footing design checks",
                [
                    ("check", "Check"),
                    ("demand", "Demand"),
                    ("capacity", "Capacity"),
                    ("unit", "Unit"),
                    ("ratio", "Utilisation"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
        notes=[
            f"Bearing source: {bearing_src}. Self-weight included in service bearing ({self_wt:.1f} kN)."
        ],
    )


@feature(
    "foundations.combinedFooting",
    "Combined Footing",
    part="substructure",
    fields=[
        number("load1", "Column 1 service load P1", 700.0, unit="kN", min=1.0),
        number("load2", "Column 2 service load P2", 950.0, unit="kN", min=1.0),
        number("spacingM", "Column centre spacing", 3.6, unit="m", min=0.5),
        number("overhang1M", "Overhang beyond Col 1", 0.6, unit="m", min=0.2),
        number("overhang2M", "Overhang beyond Col 2", 1.0, unit="m", min=0.2),
        number("widthM", "Combined footing width B", 2.4, unit="m", min=0.5),
        number("thicknessMm", "Thickness h", 600.0, unit="mm", min=250.0),
        number("colSizeMm", "Square column size", 400.0, unit="mm", min=150.0),
        number("qaKpa", "Allowable bearing qa", 180.0, unit="kPa", min=20.0),
        number("loadFactor", "Load factor (ULS/SLS)", 1.4, min=1.0, max=2.5),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def combined_footing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Design a rectangular combined footing carrying two columns with linear soil pressure."""
    p1, p2, s = values["load1"], values["load2"], values["spacingM"]
    o1, o2, b = values["overhang1M"], values["overhang2M"], values["widthM"]
    h_mm, qa, lf = (
        values["thicknessMm"],
        values["qaKpa"],
        values["loadFactor"],
    )
    fc, fy = values["fcMpa"], values["fyMpa"]

    length = o1 + s + o2
    x1, x2 = o1, o1 + s
    p_tot = p1 + p2
    x_res = (p1 * x1 + p2 * x2) / p_tot
    ecc = x_res - length / 2.0
    self_wt = 24.0 * length * b * (h_mm / 1000.0)
    sp = shallow.soil_pressure((p_tot + self_wt) * 1e3, ecc * 1e3, 0.0, length * 1e3, b * 1e3)
    qmax, qmin = sp.qmax * 1e3, sp.qmin * 1e3

    # Factored uniform-equivalent line reaction w(x) [kN/m] along footing length
    pu1, pu2 = p1 * lf, p2 * lf
    pu_tot = pu1 + pu2
    q_u_avg = pu_tot / length
    # Sample shear and moment along the beam strip, plus exact column discontinuities.
    stations = 40
    max_hog = 0.0
    max_sag = 0.0
    max_v = 0.0
    rows = []
    w0 = q_u_avg * (1.0 - 6.0 * ecc / length)
    w1 = q_u_avg * (1.0 + 6.0 * ecc / length)

    def _actions(x: float, include_col1: bool, include_col2: bool) -> tuple[float, float]:
        wx = w0 + (w1 - w0) * (x / length)
        v_soil = 0.5 * (w0 + wx) * x
        m_soil = w0 * x**2 / 2.0 + (wx - w0) * x**2 / 6.0
        v_col = (pu1 if include_col1 else 0.0) + (pu2 if include_col2 else 0.0)
        m_col = (pu1 * (x - x1) if x >= x1 else 0.0) + (pu2 * (x - x2) if x >= x2 else 0.0)
        return v_soil - v_col, m_soil - m_col

    for i in range(stations + 1):
        x = length * i / stations
        vx, mx = _actions(x, x >= x1, x >= x2)
        max_hog = max(max_hog, mx)
        max_sag = max(max_sag, -mx)
        max_v = max(max_v, abs(vx))
        if i % 8 == 0:
            rows.append({"xM": x, "shearKn": vx, "momentKnm": mx})
    for x_col, c1_before, c2_before in (
        (x1, False, False),
        (x1, True, False),
        (x2, True, False),
        (x2, True, True),
    ):
        vx, mx = _actions(x_col, c1_before, c2_before)
        max_hog = max(max_hog, mx)
        max_sag = max(max_sag, -mx)
        max_v = max(max_v, abs(vx))

    d_mm = h_mm - 75.0 - 16.0
    with in_force(ctx.root):
        hog_need = slab_flexure_need(max_hog * 1e6 / b, d_mm, fc, fy)
        sag_need = slab_flexure_need(max_sag * 1e6 / b, d_mm, fc, fy)
        as_min = shallow.min_steel_ratio(fy) * 1000.0 * h_mm
        top_req = max(hog_need.area, as_min)
        bot_req = max(sag_need.area, as_min)
        rho = bot_req / (1000.0 * d_mm)
        phi_vc = shallow.one_way_shear_capacity(b * 1000.0, d_mm, rho, fc) / 1e3

    return result(
        summary={
            "footingLengthM": length,
            "eccentricityM": ecc,
            "maxPressureKpa": qmax,
            "minPressureKpa": qmin,
            "bearingRatio": qmax / qa,
            "maxHoggingKnm": max_hog,
            "maxSaggingKnm": max_sag,
            "maxShearKn": max_v,
            "shearCapacityKn": phi_vc,
            "topSteelMm2PerM": top_req,
            "bottomSteelMm2PerM": bot_req,
        },
        tables=[
            table(
                "Combined footing longitudinal actions (ULS)",
                [("xM", "x", "m"), ("shearKn", "Shear", "kN"), ("momentKnm", "Moment", "kN·m")],
                rows,
            )
        ],
        notes=[
            f"Resultant lies at x = {x_res:.2f} m (eccentricity {ecc:+.3f} m from centroid). Positive moment causes top tension (hogging)."
        ],
    )


@feature(
    "foundations.strapBeam",
    "Strap Beam",
    part="substructure",
    fields=[
        number("extLoad", "Exterior column service load P1", 600.0, unit="kN", min=1.0),
        number("intLoad", "Interior column service load P2", 900.0, unit="kN", min=1.0),
        number("spanM", "Centre-to-centre column spacing", 4.5, unit="m", min=1.0),
        number("eccentricityM", "Exterior pad eccentricity e", 0.75, unit="m", min=0.1),
        number("qaKpa", "Allowable bearing qa", 180.0, unit="kPa", min=20.0),
        number("strapWidthMm", "Strap beam width bw", 450.0, unit="mm", min=200.0),
        number("strapDepthMm", "Strap beam depth h", 800.0, unit="mm", min=300.0),
        number("loadFactor", "Ultimate load factor", 1.4, min=1.0, max=2.5),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def strap_beam(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Design a strap beam connecting an eccentric boundary footing to an interior footing."""
    p1, p2 = values["extLoad"], values["intLoad"]
    s, e = values["spanM"], values["eccentricityM"]
    if e >= s * 0.8:
        raise FeatureInputError("Eccentricity must be smaller than the column spacing.")
    qa, bw, h, lf = (
        values["qaKpa"],
        values["strapWidthMm"],
        values["strapDepthMm"],
        values["loadFactor"],
    )
    fc, fy = values["fcMpa"], values["fyMpa"]

    # Rigid strap equilibrium: R1 * (s - e) = P1 * s
    r1 = p1 * s / (s - e)
    uplift_relief = r1 - p1
    r2 = p2 - uplift_relief
    if r2 <= 0:
        raise FeatureInputError("Interior column load is insufficient to balance strap uplift.")

    area1 = r1 / qa
    area2 = r2 / qa
    m_max_uls = p1 * e * lf  # Peak hogging moment in strap at exterior pad edge
    v_max_uls = uplift_relief * lf  # Shear along strap between pads
    d_mm = h - 50.0 - 20.0

    with in_force(ctx.root):
        flex = beam_flexure_need(m_max_uls * 1e6, bw, d_mm, 60.0, fc, fy, h=h)
        shear = beam_shear_need(v_max_uls * 1e3, bw, d_mm, fc, fy)
        stirrups = choose_stirrups(shear, bw)

    rows = [
        {"item": "Exterior footing reaction R1", "value": r1, "unit": "kN"},
        {"item": "Interior footing reaction R2", "value": r2, "unit": "kN"},
        {"item": "Required exterior pad area", "value": area1, "unit": "m²"},
        {"item": "Required interior pad area", "value": area2, "unit": "m²"},
        {"item": "Design hogging moment Mu", "value": m_max_uls, "unit": "kN·m"},
        {"item": "Design strap shear Vu", "value": v_max_uls, "unit": "kN"},
        {"item": "Top longitudinal steel As", "value": flex.area, "unit": "mm²"},
    ]
    return result(
        summary={
            "extReactionKn": r1,
            "intReactionKn": r2,
            "strapMomentKnm": m_max_uls,
            "strapShearKn": v_max_uls,
            "topSteelMm2": flex.area,
            "stirrups": f"2L-Ø{stirrups.dia:g}@{stirrups.spacing:g}"
            if stirrups
            else "Increase section",
        },
        tables=[
            table(
                "Strap beam equilibrium and reinforcement",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Strap beam assumed free of direct soil bearing beneath its stem; top bars resist hogging."
        ],
    )


@feature(
    "foundations.autoSize",
    "Auto Size",
    part="substructure",
    fields=[
        number("serviceLoad", "Column service axial load P", 750.0, unit="kN", min=1.0),
        number("loadFactor", "Ultimate load factor", 1.4, min=1.0, max=2.5),
        number("colSizeMm", "Square column size", 400.0, unit="mm", min=150.0),
        number("depthM", "Founding depth Df", 1.5, unit="m", min=0.3),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def auto_size(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Automatically size a square footing (or run project footing proposal when FEM reactions exist)."""
    if ctx.root is not None and (ctx.root / "08 FEM" / "model.results").exists():
        with in_force(ctx.root):
            proposal = sizing.propose_footings(ctx.root)
        proposed = proposal.get("foundations", [])
        rows = [
            {
                "id": f.get("id"),
                "type": f.get("type"),
                "lengthMm": f.get("length"),
                "widthMm": f.get("width"),
                "thicknessMm": f.get("thickness"),
            }
            for f in proposed
        ]
        return result(
            summary={"proposedCount": len(proposed), "source": "Project FEM reactions"},
            tables=[
                table(
                    "Proposed project footings",
                    [
                        ("id", "ID"),
                        ("type", "Type"),
                        ("lengthMm", "L", "mm"),
                        ("widthMm", "B", "mm"),
                        ("thicknessMm", "h", "mm"),
                    ],
                    rows,
                )
            ],
            notes=proposal.get(
                "notes", ["Proposed using project structural reactions and soil report."]
            ),
        )

    p_serv = values["serviceLoad"]
    lf = values["loadFactor"]
    col = values["colSizeMm"]
    df_m = values["depthM"]
    fc, fy = values["fcMpa"], values["fyMpa"]

    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        chosen_b = 1.0
        chosen_qa = 150.0
        while chosen_b <= 8.0:
            res_b = soil_bearing.allowable(prof, chosen_b, chosen_b, df_m)
            if res_b.get("qa") is None:
                raise FeatureInputError(
                    "Allowable bearing could not be determined at the founding depth (check soil strength / fill)."
                )
            chosen_qa = float(res_b["qa"])
            est_h = max(0.35, 0.25 * (chosen_b - col / 1000.0))
            q_act = (p_serv + 24.0 * chosen_b * chosen_b * est_h) / (chosen_b * chosen_b)
            if q_act <= chosen_qa:
                break
            chosen_b = round(chosen_b + 0.05, 2)

        pu_kn = p_serv * lf
        qu_kpa = pu_kn / (chosen_b * chosen_b)
        h_mm = 300.0
        punch_ratio = 9.9
        while h_mm <= 2000.0:
            d_mm = h_mm - 91.0
            p_chk = footing_punching(
                0.0,
                0.0,
                col,
                col,
                chosen_b * 1000.0,
                chosen_b * 1000.0,
                d_mm,
                fc,
                [("ULS", pu_kn * 1e3, 0.0, 0.0, unit_relief(qu_kpa * 1e-3))],
            )
            punch_ratio = p_chk.utilisation if p_chk else 0.0
            if punch_ratio <= 1.0:
                break
            h_mm += 50.0

        d_mm = h_mm - 91.0
        cant_m = max(0.0, (chosen_b - col / 1000.0) / 2.0)
        mu = qu_kpa * cant_m**2 / 2.0
        flex = slab_flexure_need(mu * 1e6, d_mm, fc, fy)
        as_req = max(flex.area, shallow.min_steel_ratio(fy) * 1000.0 * h_mm)
        mesh = mesh_for(as_req, min(3.0 * h_mm, 450.0), diameters("foundation"))

    return result(
        summary={
            "widthM": chosen_b,
            "lengthM": chosen_b,
            "thicknessMm": h_mm,
            "allowableBearingKpa": chosen_qa,
            "punchingRatio": punch_ratio,
            "rebarMesh": f"Ø{mesh.dia:g}@{mesh.spacing:g}" if mesh else "Custom",
        },
        tables=[
            table(
                "Auto-sized square footing",
                [("param", "Parameter"), ("val", "Value"), ("unit", "Unit")],
                [
                    {
                        "param": "Plan size B × L",
                        "val": f"{chosen_b:.2f} × {chosen_b:.2f}",
                        "unit": "m",
                    },
                    {"param": "Thickness h", "val": h_mm, "unit": "mm"},
                    {"param": "Allowable bearing qa", "val": chosen_qa, "unit": "kPa"},
                    {"param": "Punching utilisation", "val": punch_ratio, "unit": "-"},
                    {"param": "Required steel area", "val": as_req, "unit": "mm²/m"},
                ],
            )
        ],
        notes=[f"Sized iteratively in 50 mm steps using {src} (bearing + punching + flexure)."],
    )


@feature(
    "foundations.punchingShear",
    "Punching Shear",
    part="substructure",
    fields=[
        number("puKn", "Factored column load Pu", 1200.0, unit="kN", min=1.0),
        number("muKnm", "Factored moment Mu", 60.0, unit="kN·m"),
        number("mvKnm", "Factored moment Mv", 30.0, unit="kN·m"),
        number("colX", "Column c1", 450.0, unit="mm", min=100.0),
        number("colY", "Column c2", 450.0, unit="mm", min=100.0),
        number("lengthMm", "Footing length L", 2600.0, unit="mm", min=500.0),
        number("widthMm", "Footing width B", 2600.0, unit="mm", min=500.0),
        number("thicknessMm", "Footing thickness h", 500.0, unit="mm", min=150.0),
        number("coverMm", "Clear cover", 75.0, unit="mm", min=20.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyStudsMpa", "Shear stud/stirrup fy", 350.0, unit="MPa", min=250.0),
        checkbox("designStuds", "Design shear reinforcement if needed", True),
    ],
    requires_project=False,
)
def punching_shear(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check two-way punching shear around a column and design shear studs/stirrups when required."""
    d_mm = values["thicknessMm"] - values["coverMm"] - 16.0
    if d_mm <= 40.0:
        raise FeatureInputError("Effective depth d must exceed 40 mm.")
    l_mm, b_mm = values["lengthMm"], values["widthMm"]
    qu_mpa = (values["puKn"] * 1e3) / (l_mm * b_mm)

    with in_force(ctx.root):
        res = footing_punching(
            0.0,
            0.0,
            values["colX"],
            values["colY"],
            l_mm,
            b_mm,
            d_mm,
            values["fcMpa"],
            [
                (
                    "ULS",
                    values["puKn"] * 1e3,
                    values["muKnm"] * 1e6,
                    values["mvKnm"] * 1e6,
                    unit_relief(qu_mpa),
                )
            ],
            fyt=values["fyStudsMpa"],
            thickness=values["thicknessMm"],
            covers=(values["coverMm"], 50.0),
        )
    if res is None:
        raise FeatureInputError("Critical punching perimeter lies outside the footing footprint.")

    reinf_note = "Concrete capacity alone is sufficient."
    if res.reinforcement is not None:
        reinf_note = res.reinforcement.text
    rows = [
        {"metric": "Critical perimeter b0", "value": res.b0, "unit": "mm"},
        {"metric": "Effective depth d", "value": res.d, "unit": "mm"},
        # The engine's punching values are stresses on the critical section [MPa].
        {"metric": "Shear stress demand vu", "value": res.vu, "unit": "MPa"},
        {"metric": "Direct shear stress (net of soil relief)", "value": res.direct, "unit": "MPa"},
        {"metric": "Concrete punching resistance φvc", "value": res.phi_vc, "unit": "MPa"},
        {
            "metric": "Equivalent capacity φvc·b0·d",
            "value": res.phi_vc * res.b0 * res.d / 1e3,
            "unit": "kN",
        },
        {"metric": "Concrete-only utilisation", "value": res.utilisation, "unit": "-"},
    ]
    return result(
        summary={
            "perimeterMm": res.b0,
            "demandStressMpa": res.vu,
            "capacityStressMpa": res.phi_vc,
            "capacityKn": res.phi_vc * res.b0 * res.d / 1e3,
            "utilisation": res.utilisation,
            "concreteOk": res.utilisation <= 1.0,
        },
        tables=[
            table(
                "Punching shear evaluation",
                [("metric", "Metric"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[reinf_note, *res.notes],
    )


@feature(
    "foundations.oneWayShear",
    "One-Way Shear",
    part="substructure",
    fields=[
        number("puKn", "Factored axial load Pu", 1200.0, unit="kN", min=1.0),
        number("muKnm", "Factored moment Mu", 50.0, unit="kN·m"),
        number("colX", "Column c1", 400.0, unit="mm", min=100.0),
        number("lengthMm", "Footing length L", 2600.0, unit="mm", min=500.0),
        number("widthMm", "Footing width B", 2400.0, unit="mm", min=500.0),
        number("thicknessMm", "Footing thickness h", 500.0, unit="mm", min=150.0),
        number("coverMm", "Clear cover", 75.0, unit="mm", min=20.0),
        number("barDiaMm", "Bottom bar diameter", 16.0, unit="mm", min=8.0),
        number("barSpacingMm", "Bottom bar spacing", 150.0, unit="mm", min=50.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
    ],
    requires_project=False,
)
def one_way_shear(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check one-way beam shear at distance d from the column face across the footing width."""
    h, cov, db = values["thicknessMm"], values["coverMm"], values["barDiaMm"]
    d_mm = h - cov - db / 2.0
    if d_mm <= 40.0:
        raise FeatureInputError("Effective depth d is too small.")
    l_mm, b_mm, c1 = values["lengthMm"], values["widthMm"], values["colX"]
    cant = max(0.0, (l_mm - c1) / 2.0 - d_mm)
    area_m2 = (l_mm / 1000.0) * (b_mm / 1000.0)
    sp = shallow.soil_pressure(
        values["puKn"] * 1e3, (values["muKnm"] / values["puKn"]) * 1e3, 0.0, l_mm, b_mm
    )
    q_edge = sp.qmax * 1e3  # kPa
    q_d = q_edge - (sp.qmax - sp.qmin) * 1e3 * (cant / l_mm)
    vu_kn = 0.5 * (q_edge + q_d) * (cant / 1000.0) * (b_mm / 1000.0)

    as_per_m = math.pi * db**2 / 4.0 * 1000.0 / values["barSpacingMm"]
    rho = as_per_m / (1000.0 * d_mm)
    with in_force(ctx.root):
        phi_vc_kn = shallow.one_way_shear_capacity(b_mm, d_mm, rho, values["fcMpa"]) / 1e3
        lam_s = shallow.size_factor(d_mm)

    ratio = vu_kn / phi_vc_kn if phi_vc_kn > 0 else float("inf")
    return result(
        summary={
            "criticalCantileverMm": cant,
            "demandKn": vu_kn,
            "capacityKn": phi_vc_kn,
            "sizeFactor": lam_s,
            "utilisation": ratio,
            "ok": ratio <= 1.0,
        },
        tables=[
            table(
                "One-way shear check at d from column face",
                [("param", "Parameter"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"param": "Effective depth d", "val": d_mm, "unit": "mm"},
                    {"param": "Loaded cantilever beyond d", "val": cant, "unit": "mm"},
                    {"param": "Size effect factor λs", "val": lam_s, "unit": "-"},
                    {"param": "Factored shear Vu", "val": vu_kn, "unit": "kN"},
                    {"param": "Shear capacity φVc", "val": phi_vc_kn, "unit": "kN"},
                    {"param": "Utilisation", "val": ratio, "unit": "-"},
                ],
            )
        ],
        notes=[f"Reinforcement ratio ρ = {rho:.4f} on footing area {area_m2:.2f} m²."],
    )


@feature(
    "foundations.bearingPressure",
    "Bearing Pressure",
    part="substructure",
    fields=[
        number("verticalKn", "Total service vertical load V", 900.0, unit="kN", min=1.0),
        number("mxKnm", "Service moment Mx", 60.0, unit="kN·m"),
        number("myKnm", "Service moment My", 35.0, unit="kN·m"),
        number("lengthM", "Footing length L", 2.5, unit="m", min=0.4),
        number("widthM", "Footing width B", 2.0, unit="m", min=0.4),
        number("qaKpa", "Allowable bearing qa", 180.0, unit="kPa", min=10.0),
    ],
    requires_project=False,
)
def bearing_pressure(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute biaxial no-tension bearing pressure contours and corner values under a footing."""
    v = values["verticalKn"]
    l_mm, b_mm = values["lengthM"] * 1e3, values["widthM"] * 1e3
    eu = (values["myKnm"] / v) * 1e3
    ev = (values["mxKnm"] / v) * 1e3
    sp = shallow.soil_pressure(v * 1e3, eu, ev, l_mm, b_mm)
    qmax, qmin = sp.qmax * 1e3, sp.qmin * 1e3

    grid_rows = []
    for iu in (-1.0, -0.5, 0.0, 0.5, 1.0):
        for iv in (-1.0, 0.0, 1.0):
            u = iu * (values["lengthM"] / 2.0)
            v_pos = iv * (values["widthM"] / 2.0)
            if not sp.clip:
                q_pt = sp.a * 1e3 + sp.gu * 1e6 * u + sp.gv * 1e6 * v_pos
            else:
                q_pt = sp.a * 1e3 + sp.gu * 1e6 * u + sp.gv * 1e6 * v_pos
            grid_rows.append({"uM": u, "vM": v_pos, "pressureKpa": max(0.0, q_pt)})

    return result(
        summary={
            "qmaxKpa": qmax,
            "qminKpa": qmin,
            "contactShare": sp.contact,
            "state": sp.state,
            "utilisation": qmax / values["qaKpa"],
        },
        tables=[
            table(
                "Bearing pressure distribution points",
                [("uM", "u", "m"), ("vM", "v", "m"), ("pressureKpa", "Bearing pressure", "kPa")],
                grid_rows,
            )
        ],
        notes=[f"Contact state: {sp.state} (contact area ratio {sp.contact:.2%})."],
    )


@feature(
    "foundations.soilSprings",
    "Soil Springs",
    part="substructure",
    fields=[
        number("widthM", "Foundation width B", 12.0, unit="m", min=0.5),
        number("lengthM", "Foundation length L", 16.0, unit="m", min=0.5),
        number("depthM", "Founding depth Df", 2.0, unit="m", min=0.0),
        number("pressureKpa", "Average contact pressure q", 120.0, unit="kPa", min=1.0),
        number("meshSizeM", "Tributary mesh spacing", 0.5, unit="m", min=0.1),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def soil_springs(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute modulus of subgrade reaction ks and nodal Winkler springs for rafts and slabs."""
    b, l_, df, q = values["widthM"], values["lengthM"], values["depthM"], values["pressureKpa"]
    mesh_m = values["meshSizeM"]
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        ks_info = raft.raft_ks(prof, b, l_, df, q)
    ks = float(ks_info["value"])
    trib_area = mesh_m * mesh_m
    k_interior = ks * trib_area
    rows = [
        {
            "zone": "Interior node (full tributary area)",
            "areaM2": trib_area,
            "ksKnM3": ks,
            "springKnM": k_interior,
        },
        {
            "zone": "Edge node (half tributary area)",
            "areaM2": trib_area / 2.0,
            "ksKnM3": ks,
            "springKnM": k_interior / 2.0,
        },
        {
            "zone": "Corner node (quarter tributary area)",
            "areaM2": trib_area / 4.0,
            "ksKnM3": ks,
            "springKnM": k_interior / 4.0,
        },
    ]
    return result(
        summary={
            "ksKnM3": ks,
            "interiorSpringKnM": k_interior,
            "settlementMm": ks_info.get("settlement", {}).get("total", 0.0),
        },
        tables=[
            table(
                "Subgrade spring assignments",
                [
                    ("zone", "Node zone"),
                    ("areaM2", "Tributary area", "m²"),
                    ("ksKnM3", "Subgrade ks", "kN/m³"),
                    ("springKnM", "Spring Kz", "kN/m"),
                ],
                rows,
            )
        ],
        notes=[f"Derived from {src}: {ks_info.get('method', '')}."],
    )


@feature(
    "foundations.upliftCheck",
    "Uplift Check",
    part="substructure",
    fields=[
        number("deadKn", "Dead load D (including column & footing)", 450.0, unit="kN", min=0.0),
        number("upliftKn", "Wind/seismic uplift tension T", 180.0, unit="kN", min=0.0),
        number("momentKnm", "Overturning moment M", 90.0, unit="kN·m", min=0.0),
        number("lengthM", "Footing length L", 2.4, unit="m", min=0.5),
        number("widthM", "Footing width B", 2.4, unit="m", min=0.5),
        number("soilDepthM", "Soil cover above footing", 1.0, unit="m", min=0.0),
        number("waterHeightM", "Flood/water head above base", 0.5, unit="m", min=0.0),
    ],
    requires_project=False,
)
def uplift_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check zero-tension contact, net uplift stability, and buoyant flotation at the footing base."""
    l_m, b_m = values["lengthM"], values["widthM"]
    area = l_m * b_m
    soil_wt = 18.0 * area * values["soilDepthM"]
    total_dead = values["deadKn"] + soil_wt
    net_v = total_dead - values["upliftKn"]
    with in_force(ctx.root):
        flotation = loads.flood_uplift(total_dead, area, values["waterHeightM"], below_ground=0.0)
    buoyancy_kn = flotation["U_kN"] if flotation else 9.81 * area * values["waterHeightM"]
    net_after_buoy = net_v - buoyancy_kn
    if net_after_buoy > 0:
        sp = shallow.soil_pressure(
            net_after_buoy * 1e3,
            (values["momentKnm"] / net_after_buoy) * 1e3,
            0.0,
            l_m * 1e3,
            b_m * 1e3,
        )
        contact = sp.contact
        state = sp.state
    else:
        contact = 0.0
        state = "net uplift"
    fs_uplift = total_dead / max(values["upliftKn"] + buoyancy_kn, 1e-6)
    return result(
        summary={
            "totalDeadKn": total_dead,
            "buoyancyKn": buoyancy_kn,
            "netCompressionKn": net_after_buoy,
            "contactShare": contact,
            "upliftSafetyFactor": fs_uplift,
            "zeroTensionOk": contact >= 0.999,
        },
        tables=[
            table(
                "Footing uplift & zero-tension summary",
                [("item", "Check item"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Resisting dead + soil overburden", "value": total_dead, "unit": "kN"},
                    {"item": "Hydrostatic uplift U", "value": buoyancy_kn, "unit": "kN"},
                    {"item": "Net vertical load", "value": net_after_buoy, "unit": "kN"},
                    {"item": "Base contact share", "value": contact, "unit": "-"},
                    {"item": "Overall uplift FS", "value": fs_uplift, "unit": "-"},
                ],
            )
        ],
        notes=[
            f"Contact state: {state}. Full base contact requires resultant within middle third (e ≤ L/6)."
        ],
    )


@feature(
    "foundations.raftThickness",
    "Raft Thickness",
    part="substructure",
    fields=[
        number("maxPuKn", "Heaviest factored column load Pu", 2800.0, unit="kN", min=1.0),
        number("colX", "Column width c1", 500.0, unit="mm", min=150.0),
        number("colY", "Column depth c2", 500.0, unit="mm", min=150.0),
        number("maxSpanM", "Maximum column bay span", 6.5, unit="m", min=2.0),
        number("trialThicknessMm", "Trial raft thickness h", 750.0, unit="mm", min=300.0),
        number("coverMm", "Clear cover", 75.0, unit="mm", min=25.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        select(
            "location",
            "Column location",
            [("interior", "Interior"), ("edge", "Edge"), ("corner", "Corner")],
        ),
    ],
    requires_project=False,
)
def raft_thickness(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check raft slab thickness against punching shear and span-to-depth bending stiffness."""
    pu = values["maxPuKn"]
    c1, c2 = values["colX"], values["colY"]
    fc = values["fcMpa"]
    h_trial = values["trialThicknessMm"]
    d_trial = h_trial - values["coverMm"] - 20.0
    if d_trial <= 50.0:
        raise FeatureInputError("Trial thickness too small for cover.")

    with in_force(ctx.root):
        min_punch_h = sizing.punching_depth(pu * 1e3, max(c1, c2), fc)
        b0 = (
            2.0 * (c1 + c2 + 2.0 * d_trial)
            if values["location"] == "interior"
            else (
                c1 + 2.0 * c2 + 2.0 * d_trial if values["location"] == "edge" else c1 + c2 + d_trial
            )
        )
        alpha_s = (
            40.0
            if values["location"] == "interior"
            else (30.0 if values["location"] == "edge" else 20.0)
        )
        phi_vc_stress = rc.value("PHI_SHEAR") * shallow.punching_stress(
            c1, c2, d_trial, b0, alpha_s, fc
        )
        phi_vc_kn = phi_vc_stress * b0 * d_trial / 1e3

    stiff_h = max(300.0, values["maxSpanM"] * 1000.0 / 12.0)
    gov_h = max(min_punch_h, stiff_h)
    util = pu / phi_vc_kn if phi_vc_kn > 0 else float("inf")
    return result(
        summary={
            "requiredPunchingMm": min_punch_h,
            "stiffnessGuideMm": stiff_h,
            "recommendedThicknessMm": gov_h,
            "trialPunchingRatio": util,
            "trialOk": h_trial >= gov_h and util <= 1.0,
        },
        tables=[
            table(
                "Raft thickness evaluation",
                [("criterion", "Criterion"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "criterion": "Minimum thickness (punching)",
                        "value": min_punch_h,
                        "unit": "mm",
                    },
                    {"criterion": "Rigidity guide (span / 12)", "value": stiff_h, "unit": "mm"},
                    {"criterion": "Trial punching capacity φVc", "value": phi_vc_kn, "unit": "kN"},
                    {"criterion": "Trial punching demand Pu", "value": pu, "unit": "kN"},
                    {"criterion": "Trial punching utilisation", "value": util, "unit": "-"},
                ],
            )
        ],
        notes=[f"Evaluated for {values['location']} column (αs = {alpha_s:g})."],
    )


@feature(
    "foundations.raftSettlement",
    "Raft Settlement",
    part="substructure",
    fields=[
        number("widthM", "Raft width B", 15.0, unit="m", min=1.0),
        number("lengthM", "Raft length L", 20.0, unit="m", min=1.0),
        number("depthM", "Founding depth Df", 2.0, unit="m", min=0.0),
        number("pressureKpa", "Net bearing pressure q", 125.0, unit="kPa", min=1.0),
        number("baySpanM", "Typical column spacing", 6.0, unit="m", min=1.0),
        number("years", "Consolidation period", 30.0, unit="years", min=1.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def raft_settlement(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute total, consolidation, and differential settlement across the raft footprint."""
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        res = soil_settlement.settlement(
            prof,
            values["widthM"],
            values["lengthM"],
            values["depthM"],
            values["pressureKpa"],
            years=values["years"],
            foundation="raft",
        )
    total_mm = float(res["total"])
    diff_est_mm = 0.5 * total_mm
    angular = diff_est_mm / (values["baySpanM"] * 1000.0)
    rows = [
        {"component": "Immediate (elastic)", "value": res.get("immediate", 0.0), "unit": "mm"},
        {
            "component": "Primary consolidation",
            "value": res.get("consolidation", 0.0),
            "unit": "mm",
        },
        {"component": "Secondary compression", "value": res.get("secondary", 0.0), "unit": "mm"},
        {"component": "Total raft settlement", "value": total_mm, "unit": "mm"},
        {"component": "Estimated differential (0.5 × total)", "value": diff_est_mm, "unit": "mm"},
        {
            "angular": "Angular distortion",
            "component": "Angular distortion Δ/L",
            "value": angular,
            "unit": "rad",
        },
    ]
    return result(
        summary={
            "totalSettlementMm": total_mm,
            "immediateMm": res.get("immediate", 0.0),
            "consolidationMm": res.get("consolidation", 0.0),
            "differentialMm": diff_est_mm,
            "angularDistortion": angular,
        },
        tables=[
            table(
                "Raft settlement breakdown",
                [("component", "Component"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            f"Soil source: {src}. Differential settlement estimated as 50% of total settlement for flexible-to-semi-rigid mat."
        ],
    )


@feature(
    "foundations.raftReinforcement",
    "Raft Reinforcement",
    part="substructure",
    fields=[
        number("mxBottom", "Design sagging moment Mx+ (bottom)", 280.0, unit="kN·m/m", min=0.0),
        number("myBottom", "Design sagging moment My+ (bottom)", 240.0, unit="kN·m/m", min=0.0),
        number("mxTop", "Design hogging moment Mx- (top)", 320.0, unit="kN·m/m", min=0.0),
        number("myTop", "Design hogging moment My- (top)", 260.0, unit="kN·m/m", min=0.0),
        number("thicknessMm", "Raft thickness h", 750.0, unit="mm", min=300.0),
        number("coverMm", "Clear cover", 75.0, unit="mm", min=25.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def raft_reinforcement(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size top and bottom orthogonal reinforcement meshes for raft design moments."""
    h, cov, fc, fy = values["thicknessMm"], values["coverMm"], values["fcMpa"], values["fyMpa"]
    d_outer = h - cov - 10.0
    d_inner = d_outer - 20.0
    if d_inner <= 50.0:
        raise FeatureInputError("Raft thickness too small for two reinforcement layers.")

    with in_force(ctx.root):
        as_min = shallow.min_steel_ratio(fy) * 1000.0 * h
        s_max = min(3.0 * h, 450.0)
        bars = diameters("foundation")
        specs = [
            ("Bottom X (sagging)", values["mxBottom"], d_outer),
            ("Bottom Y (sagging)", values["myBottom"], d_inner),
            ("Top X (hogging)", values["mxTop"], d_outer),
            ("Top Y (hogging)", values["myTop"], d_inner),
        ]
        rows = []
        summary: dict[str, Any] = {"minSteelMm2PerM": as_min}
        for label, m_knm, d_eff in specs:
            need = slab_flexure_need(m_knm * 1e6, d_eff, fc, fy)
            req = max(need.area, as_min)
            mesh = mesh_for(req, s_max, bars)
            prov = math.pi * mesh.dia**2 / 4.0 * 1000.0 / mesh.spacing if mesh else 0.0
            cap = shallow.strip_flexure(prov, d_eff, fc, fy).phi_mn / 1e6 if mesh else 0.0
            rows.append(
                {
                    "face": label,
                    "momentKnmPerM": m_knm,
                    "reqMm2PerM": req,
                    "mesh": f"Ø{mesh.dia:g}@{mesh.spacing:g}" if mesh else "Needs deeper section",
                    "capKnmPerM": cap,
                }
            )
            key = label.split("(")[0].strip().replace(" ", "")
            summary[f"{key[0].lower() + key[1:]}Mesh"] = rows[-1]["mesh"]
    return result(
        summary=summary,
        tables=[
            table(
                "Raft reinforcement design",
                [
                    ("face", "Layer"),
                    ("momentKnmPerM", "Mu", "kN·m/m"),
                    ("reqMm2PerM", "As,req", "mm²/m"),
                    ("mesh", "Proposed mesh"),
                    ("capKnmPerM", "φMn", "kN·m/m"),
                ],
                rows,
            )
        ],
        notes=[
            f"Minimum shrinkage/temperature steel per face = {as_min:.0f} mm²/m (half of total minimum or full per face)."
        ],
    )


@feature(
    "foundations.gradeBeamDesign",
    "Grade Beam Design",
    part="substructure",
    fields=[
        number("spanM", "Clear span L", 5.0, unit="m", min=1.0),
        number("widthMm", "Beam width bw", 350.0, unit="mm", min=150.0),
        number("depthMm", "Beam depth h", 600.0, unit="mm", min=250.0),
        number("wuKnPerM", "Factored uniform wall/slab load wu", 35.0, unit="kN/m", min=0.0),
        number("diffSettleMm", "Differential settlement Δ", 12.0, unit="mm", min=0.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def grade_beam_design(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Design a grade beam for gravity loads plus differential settlement moments and shears."""
    l_mm, bw, h = values["spanM"] * 1e3, values["widthMm"], values["depthMm"]
    fc, fy = values["fcMpa"], values["fyMpa"]
    d_mm = h - 50.0 - 10.0 - 10.0

    with in_force(ctx.root):
        ec = 4700.0 * math.sqrt(fc)
        ig = bw * h**3 / 12.0
        # Cracked stiffness 0.35 Ig for settlement demand
        m_settle = 6.0 * ec * (0.35 * ig) * values["diffSettleMm"] / (l_mm**2) / 1e6  # kN.m
        v_settle = 12.0 * ec * (0.35 * ig) * values["diffSettleMm"] / (l_mm**3) / 1e3  # kN
        m_grav = values["wuKnPerM"] * values["spanM"] ** 2 / 8.0
        v_grav = values["wuKnPerM"] * values["spanM"] / 2.0
        mu_tot = m_grav + m_settle
        vu_tot = v_grav + v_settle

        flex = beam_flexure_need(mu_tot * 1e6, bw, d_mm, 60.0, fc, fy, h=h)
        shear = beam_shear_need(vu_tot * 1e3, bw, d_mm, fc, fy)
        stir = choose_stirrups(shear, bw)

    return result(
        summary={
            "gravityMomentKnm": m_grav,
            "settlementMomentKnm": m_settle,
            "totalMomentKnm": mu_tot,
            "totalShearKn": vu_tot,
            "requiredSteelMm2": flex.area,
            "stirrups": f"2L-Ø{stir.dia:g}@{stir.spacing:g}" if stir else "Increase beam size",
        },
        tables=[
            table(
                "Grade beam design actions & steel",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Gravity moment wL²/8", "value": m_grav, "unit": "kN·m"},
                    {"item": "Settlement moment (0.35 Ig)", "value": m_settle, "unit": "kN·m"},
                    {"item": "Total design moment Mu", "value": mu_tot, "unit": "kN·m"},
                    {"item": "Total design shear Vu", "value": vu_tot, "unit": "kN"},
                    {"item": "Required longitudinal steel As", "value": flex.area, "unit": "mm²"},
                ],
            )
        ],
        notes=["Settlement moment computed with cracked flexural rigidity 0.35 Ec Ig."],
    )


@feature(
    "foundations.tieBeamDesign",
    "Tie Beam Design",
    part="substructure",
    fields=[
        number("heavierColLoadKn", "Factored heavier column load Pu", 1100.0, unit="kN", min=1.0),
        number("tieShare", "Seismic tie force share (e.g. 0.10)", 0.10, min=0.01, max=0.50),
        number("spanM", "Tie length between footings", 5.0, unit="m", min=1.0),
        number("widthMm", "Tie width bw", 300.0, unit="mm", min=150.0),
        number("depthMm", "Tie depth h", 400.0, unit="mm", min=200.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def tie_beam_design(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Design a foundation tie beam in axial tension/compression between footings."""
    pu_col = values["heavierColLoadKn"]
    tie_force_kn = pu_col * values["tieShare"]
    bw, h, fc, fy = values["widthMm"], values["depthMm"], values["fcMpa"], values["fyMpa"]
    ag = bw * h
    with in_force(ctx.root):
        phi_t = 0.90
        as_req_tension = (tie_force_kn * 1e3) / (phi_t * fy)
        as_min = 0.005 * ag  # Minimum longitudinal steel for compression/tie member
        as_req = max(as_req_tension, as_min)
        # Check axial compression capacity (tied member)
        phi_pn = 0.80 * 0.65 * (0.85 * fc * (ag - as_req) + fy * as_req) / 1e3
        slenderness = (values["spanM"] * 1000.0) / min(bw, h)

    return result(
        summary={
            "tieForceKn": tie_force_kn,
            "requiredSteelMm2": as_req,
            "compressionCapacityKn": phi_pn,
            "slendernessRatio": slenderness,
            "ok": phi_pn >= tie_force_kn,
        },
        tables=[
            table(
                "Foundation tie beam check",
                [("param", "Parameter"), ("val", "Value"), ("unit", "Unit")],
                [
                    {
                        "param": "Design axial tie force (tension/compression)",
                        "val": tie_force_kn,
                        "unit": "kN",
                    },
                    {"param": "Tension steel required", "val": as_req_tension, "unit": "mm²"},
                    {"param": "Minimum longitudinal steel (0.5% Ag)", "val": as_min, "unit": "mm²"},
                    {"param": "Design axial compression capacity φPn", "val": phi_pn, "unit": "kN"},
                    {"param": "Span / least dimension", "val": slenderness, "unit": "-"},
                ],
            )
        ],
        notes=[
            "Provide closed ties at spacing ≤ min(16 db, 48 tie dia, least dimension) along the tie beam."
        ],
    )


@feature(
    "foundations.basementTanking",
    "Basement Tanking",
    part="substructure",
    fields=[
        number("basementDepthM", "Basement slab depth below ground", 4.5, unit="m", min=0.5),
        number("waterDepthM", "Design water table below ground", 1.5, unit="m", min=0.0),
        number("perimeterM", "Basement wall perimeter", 60.0, unit="m", min=4.0),
        number("footprintM2", "Basement plan area", 220.0, unit="m²", min=4.0),
        number("slabThicknessMm", "Base slab thickness", 500.0, unit="mm", min=150.0),
        select(
            "system",
            "Tanking system",
            [
                ("externalMembrane", "External Sheet Membrane"),
                ("crystalline", "Integral Crystalline + Waterstops"),
                ("cavityDrain", "Dual Barrier + Cavity Drain"),
            ],
        ),
    ],
    requires_project=False,
)
def basement_tanking(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate hydrostatic head, uplift, and tanking membrane quantities for below-grade spaces."""
    head_m = max(0.0, values["basementDepthM"] - values["waterDepthM"])
    pressure_kpa = 9.81 * head_m
    uplift_kn = pressure_kpa * values["footprintM2"]
    wall_area_m2 = values["perimeterM"] * values["basementDepthM"]
    total_membrane_m2 = values["footprintM2"] + wall_area_m2

    with in_force(ctx.root):
        from saengine.substructure.excavation import group as exc_group

        wp_grp = exc_group("waterproofing")
        wp_note = (
            excavation.waterproofing_spec(wp_grp)
            if wp_grp is not None
            else "Watertight membrane and joint waterstops required below water table."
        )

    return result(
        summary={
            "hydrostaticHeadM": head_m,
            "baseWaterPressureKpa": pressure_kpa,
            "totalUpliftKn": uplift_kn,
            "tankingAreaM2": total_membrane_m2,
            "system": values["system"],
        },
        tables=[
            table(
                "Basement tanking & hydrostatic demands",
                [("item", "Item"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Design hydrostatic head above base", "value": head_m, "unit": "m"},
                    {"item": "Base water pressure", "value": pressure_kpa, "unit": "kPa"},
                    {"item": "Total uplift force on footprint", "value": uplift_kn, "unit": "kN"},
                    {"item": "Wall tanking area", "value": wall_area_m2, "unit": "m²"},
                    {
                        "item": "Total slab + wall tanking area",
                        "value": total_membrane_m2,
                        "unit": "m²",
                    },
                ],
            )
        ],
        notes=[wp_note],
    )


@feature(
    "foundations.drainageBlanket",
    "Drainage Blanket",
    part="substructure",
    fields=[
        number("areaM2", "Substructure plan area", 250.0, unit="m²", min=5.0),
        number("thicknessMm", "Drainage blanket thickness", 300.0, unit="mm", min=100.0),
        number("permeabilityMmS", "Aggregate permeability k", 5.0, unit="mm/s", min=0.01),
        number("gradient", "Hydraulic gradient i", 0.02, min=0.001, max=1.0),
        number("d15FilterMm", "Filter aggregate D15", 1.2, unit="mm", min=0.1),
        number("d15SoilMm", "Subgrade soil D15", 0.08, unit="mm", min=0.005),
        number("d85SoilMm", "Subgrade soil D85", 0.45, unit="mm", min=0.01),
        number("inflowLps", "Estimated groundwater inflow", 0.8, unit="L/s", min=0.0),
    ],
    requires_project=False,
)
def drainage_blanket(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size a granular drainage blanket and verify Terzaghi soil-retention and permeability filter criteria."""
    width_equiv = math.sqrt(values["areaM2"])
    flow_area_m2 = width_equiv * (values["thicknessMm"] / 1000.0)
    k_ms = values["permeabilityMmS"] / 1000.0
    darcy_lps = k_ms * values["gradient"] * flow_area_m2 * 1000.0
    retention_ratio = values["d15FilterMm"] / values["d85SoilMm"]
    permeability_ratio = values["d15FilterMm"] / values["d15SoilMm"]
    retention_ok = retention_ratio <= 5.0
    perm_ok = permeability_ratio >= 4.0
    vol_m3 = values["areaM2"] * (values["thicknessMm"] / 1000.0)

    return result(
        summary={
            "blanketVolumeM3": vol_m3,
            "darcyCapacityLps": darcy_lps,
            "retentionRatio": retention_ratio,
            "permeabilityRatio": permeability_ratio,
            "filterCriteriaOk": retention_ok and perm_ok and darcy_lps >= values["inflowLps"],
        },
        tables=[
            table(
                "Drainage blanket & Terzaghi filter checks",
                [
                    ("check", "Criterion"),
                    ("actual", "Actual"),
                    ("limit", "Limit"),
                    ("status", "Status"),
                ],
                [
                    {
                        "check": "Piping / soil retention (D15,f / D85,s)",
                        "actual": retention_ratio,
                        "limit": "≤ 5.0",
                        "status": "PASS" if retention_ok else "FAIL",
                    },
                    {
                        "check": "Permeability ratio (D15,f / D15,s)",
                        "actual": permeability_ratio,
                        "limit": "≥ 4.0",
                        "status": "PASS" if perm_ok else "FAIL",
                    },
                    {
                        "check": "Darcy flow capacity [L/s]",
                        "actual": darcy_lps,
                        "limit": f"≥ {values['inflowLps']:g}",
                        "status": "PASS" if darcy_lps >= values["inflowLps"] else "FAIL",
                    },
                ],
            )
        ],
        notes=[
            f"Gravel volume = {vol_m3:.1f} m³; wrap interface with non-woven geotextile if D15,f/D85,s > 5."
        ],
    )

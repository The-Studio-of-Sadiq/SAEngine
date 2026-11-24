"""Substructure - Piles tab: pile layout, types, pile cap design, lateral checks, testing & driving."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from saengine.design.punching import footing_punching
from saengine.design.stm import min_angle, node_capacity, strut_capacity, tie_capacity
from saengine.design.stm import phi as stm_phi
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
from saengine.features.foundations_common import build_profile, parse_floats, parse_pairs
from saengine.library.substructure import MIN_SPACING, MIN_SPACING_DIAMETERS, pile_layout_warnings
from saengine.report.clauses import in_force
from saengine.substructure import (
    pile_detailing,
    pile_lateral,
    pile_lateral_soil,
    pilecap,
    piles,
    precast,
)
from saengine.substructure.shallow import ColumnBase


@feature(
    "foundationsPiles.pileLayout",
    "Pile Layout",
    part="substructure",
    fields=[
        number("nx", "Piles along X", 2.0, min=1.0, max=20.0),
        number("ny", "Piles along Y", 2.0, min=1.0, max=20.0),
        number("spacingMm", "Centre-to-centre pile spacing", 1800.0, unit="mm", min=400.0),
        number("diameterMm", "Pile diameter", 600.0, unit="mm", min=200.0),
        number("edgeDistMm", "Cap edge distance from pile centre", 600.0, unit="mm", min=200.0),
    ],
    requires_project=False,
)
def pile_layout(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a rectangular pile group layout, cap dimensions, and Converse-Labarre efficiency."""
    nx, ny = max(1, round(values["nx"])), max(1, round(values["ny"]))
    s, d, edge = values["spacingMm"], values["diameterMm"], values["edgeDistMm"]
    pts = []
    for i in range(nx):
        for j in range(ny):
            u = (i - (nx - 1) / 2.0) * s
            v = (j - (ny - 1) / 2.0) * s
            pts.append((u, v))
    cap_l = (nx - 1) * s + 2.0 * edge
    cap_b = (ny - 1) * s + 2.0 * edge
    eff, _, _, _ = pilecap.converse_labarre(np.array(pts, dtype=float), d)
    min_s = pilecap.min_spacing(np.array(pts, dtype=float)) if len(pts) > 1 else s
    rows = [{"mark": f"PL{k + 1}", "uMm": u, "vMm": v} for k, (u, v) in enumerate(pts)]
    return result(
        summary={
            "pileCount": len(pts),
            "capLengthMm": cap_l,
            "capWidthMm": cap_b,
            "minSpacingMm": min_s,
            "converseLabarreEfficiency": eff,
        },
        tables=[
            table(
                "Generated pile layout coordinates",
                [("mark", "Pile"), ("uMm", "u", "mm"), ("vMm", "v", "mm")],
                rows,
            )
        ],
        notes=[
            f"Spacing / diameter ratio = {s / d:.2f}. Clear edge projection = {edge - d / 2.0:.0f} mm."
        ],
    )


@feature(
    "foundationsPiles.rakePiles",
    "Rake Piles",
    part="substructure",
    fields=[
        number("verticalKn", "Total vertical load V", 1800.0, unit="kN", min=1.0),
        number("horizontalKn", "Total lateral load H", 320.0, unit="kN", min=0.0),
        number("verticalPiles", "Number of vertical piles", 2.0, min=0.0, max=20.0),
        number("rakedPiles", "Number of raked piles", 2.0, min=1.0, max=20.0),
        number("rakeSlope", "Rake slope (1 horizontal in N vertical)", 4.0, min=2.0, max=12.0),
        number("pileCapKn", "Allowable axial pile capacity Qa", 700.0, unit="kN", min=10.0),
    ],
    requires_project=False,
)
def rake_piles(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Resolve axial and shear force demands in a group containing raked (batter) piles."""
    nv, nr = round(values["verticalPiles"]), round(values["rakedPiles"])
    theta = math.atan(1.0 / values["rakeSlope"])
    # Raked piles resist horizontal H via H_rake = N_rake * sin(theta)
    axial_raked = values["horizontalKn"] / (nr * math.sin(theta))
    v_by_raked = nr * axial_raked * math.cos(theta)
    v_rem = values["verticalKn"] - v_by_raked
    if nv > 0:
        axial_vert = v_rem / nv
        residual_shear = 0.0
    else:
        axial_vert = 0.0
        # All vertical load must go into raked piles; check residual horizontal
        axial_raked = values["verticalKn"] / (nr * math.cos(theta))
        residual_shear = values["horizontalKn"] - nr * axial_raked * math.sin(theta)
    max_axial = max(abs(axial_raked), abs(axial_vert))
    util = max_axial / values["pileCapKn"]
    return result(
        summary={
            "rakeAngleDeg": math.degrees(theta),
            "rakedPileAxialKn": axial_raked,
            "verticalPileAxialKn": axial_vert,
            "residualShearKn": residual_shear,
            "utilisation": util,
            "ok": util <= 1.0,
        },
        tables=[
            table(
                "Raked pile force resolution",
                [
                    ("group", "Pile group"),
                    ("count", "Count"),
                    ("axialKn", "Axial force", "kN"),
                    ("util", "Qa ratio"),
                ],
                [
                    {
                        "group": f"Raked (1:{values['rakeSlope']:g})",
                        "count": nr,
                        "axialKn": axial_raked,
                        "util": abs(axial_raked) / values["pileCapKn"],
                    },
                    {
                        "group": "Vertical",
                        "count": nv,
                        "axialKn": axial_vert,
                        "util": abs(axial_vert) / values["pileCapKn"],
                    },
                ],
            )
        ],
        notes=[
            f"Rake angle = {math.degrees(theta):.2f}° from vertical. Verify driving/boring rig reach for inclination."
        ],
    )


@feature(
    "foundationsPiles.pileSpacing",
    "Pile Spacing",
    part="substructure",
    fields=[
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=150.0),
        number("spacingMm", "Provided centre-to-centre spacing", 1500.0, unit="mm", min=200.0),
        number("edgeDistMm", "Centre-to-cap-edge distance", 500.0, unit="mm", min=100.0),
        checkbox("frictionPile", "Primarily skin-friction pile (requires ≥ 3.0 D)", False),
    ],
    requires_project=False,
)
def pile_spacing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check minimum centre-to-centre pile spacing and edge clearance against code-pack rules."""
    d, s, edge = values["diameterMm"], values["spacingMm"], values["edgeDistMm"]
    min_mult = 3.0 if values["frictionPile"] else MIN_SPACING_DIAMETERS
    req_spacing = max(min_mult * d, MIN_SPACING)
    with in_force(ctx.root):
        cap_r = pilecap.cap_rules()
        min_overhang = (
            float(cap_r.minOverhang) if cap_r and getattr(cap_r, "minOverhang", None) else 150.0
        )
    req_edge = d / 2.0 + min_overhang
    proj_warnings: list[str] = []
    if ctx.root is not None:
        raw = ctx.raw("substructure")
        if raw is not None:
            from saengine.features.foundations_common import load_substructure_model

            try:
                sub = load_substructure_model(ctx)
                proj_warnings = pile_layout_warnings(sub)
            except FeatureInputError:
                pass
    rows = [
        {
            "check": "Centre-to-centre spacing",
            "provided": s,
            "required": req_spacing,
            "status": "PASS" if s >= req_spacing else "FAIL",
        },
        {
            "check": "Pile-centre to cap-edge distance",
            "provided": edge,
            "required": req_edge,
            "status": "PASS" if edge >= req_edge else "FAIL",
        },
    ]
    return result(
        summary={
            "requiredSpacingMm": req_spacing,
            "requiredEdgeMm": req_edge,
            "spacingOk": s >= req_spacing,
            "edgeOk": edge >= req_edge,
            "projectWarningsCount": len(proj_warnings),
        },
        tables=[
            table(
                "Pile spacing & edge checks",
                [
                    ("check", "Check"),
                    ("provided", "Provided", "mm"),
                    ("required", "Required", "mm"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
        notes=proj_warnings
        or ["All spacing checks follow minimum diameter multiple and absolute floor criteria."],
    )


@feature(
    "foundationsPiles.boredPile",
    "Bored Pile",
    part="substructure",
    fields=[
        number("diameterMm", "Pile shaft diameter D", 600.0, unit="mm", min=250.0),
        number("lengthM", "Pile length L below cut-off", 18.0, unit="m", min=2.0),
        number("headDepthM", "Cut-off depth below ground", 1.5, unit="m", min=0.0),
        select(
            "method",
            "Capacity method",
            [
                ("soilReport", "Soil report"),
                ("static", "Static (alpha-beta)"),
                ("spt", "SPT correlation"),
            ],
        ),
        select(
            "placement",
            "Concrete placement",
            [("submerged", "Tremie under water/slurry"), ("dry", "Dry bore")],
        ),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def bored_pile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute axial capacity and placement concrete requirements for a bored cast-in-situ pile."""
    d_m = values["diameterMm"] / 1000.0
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        sp = piles.single_pile(
            prof, "bored", d_m, values["lengthM"], values["headDepthM"], method=values["method"]
        )
        min_fc, fc_note = pile_detailing.least_fc("bored")
        mix_note = pile_detailing.recommended_mix(values["diameterMm"], values["placement"])
    rows = [
        {
            "layer": r["layer"] + 1,
            "soil": r["soilType"],
            "topMm": r["top"],
            "botMm": r["bottom"],
            "fsKpa": r["fs"],
            "qsKn": r["Qs"],
        }
        for r in sp["layers"]
    ]
    return result(
        summary={
            "skinFrictionKn": sp["Qs"],
            "endBearingKn": sp["Qb"],
            "ultimateCompressionKn": sp["Qult"],
            "allowableCompressionKn": sp["Qa"],
            "allowableUpliftKn": sp["Ta"],
            "leastFcMpa": min_fc,
            "concreteOk": values["fcMpa"] >= min_fc,
        },
        tables=[
            table(
                "Bored pile shaft contribution by layer",
                [
                    ("layer", "Layer"),
                    ("soil", "Soil"),
                    ("topMm", "Top", "mm"),
                    ("botMm", "Bottom", "mm"),
                    ("fsKpa", "fs", "kPa"),
                    ("qsKn", "Qs", "kN"),
                ],
                rows,
            )
        ],
        notes=[f"Soil source: {src}. {fc_note}", *([mix_note] if mix_note else []), *sp["notes"]],
    )


@feature(
    "foundationsPiles.drivenPile",
    "Driven Pile",
    part="substructure",
    fields=[
        select("shape", "Section shape", [("square", "Square precast"), ("round", "Circular")]),
        number("sideMm", "Side / diameter", 400.0, unit="mm", min=200.0),
        number("lengthM", "Driven length L", 16.0, unit="m", min=2.0),
        number("headDepthM", "Cut-off depth below ground", 1.0, unit="m", min=0.0),
        number("fcMpa", "Concrete f'c", 40.0, unit="MPa", min=20.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
        checkbox("hardDriving", "Hard driving conditions", False),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def driven_pile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Analyze a driven precast pile for geotechnical capacity, handling moments, and concrete grade."""
    side = values["sideMm"]
    length = values["lengthM"]
    is_sq = values["shape"] == "square"
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        sp = piles.single_pile(
            prof,
            "driven",
            side / 1000.0,
            length,
            values["headDepthM"],
            method="spt",
            shape=values["shape"],
        )
        min_fc, fc_note = pile_detailing.least_fc("driven", hard_driving=values["hardDriving"])
        hm = precast.handling_moments(side, length * 1000.0, 24.0, square=is_sq)
        mcr = precast.cracking_moment(side, values["fcMpa"], square=is_sq)
    return result(
        summary={
            "allowableCompressionKn": sp["Qa"],
            "allowableUpliftKn": sp["Ta"],
            "handlingMomentKnm": max(hm.values()) / 1e6 if hm else 0.0,
            "crackingMomentKnm": mcr / 1e6,
            "leastFcMpa": min_fc,
            "concreteOk": values["fcMpa"] >= min_fc,
        },
        tables=[
            table(
                "Driven pile capacity & handling moments",
                [("item", "Check item"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Allowable compression Qa", "value": sp["Qa"], "unit": "kN"},
                    {"item": "Allowable uplift Ta", "value": sp["Ta"], "unit": "kN"},
                    {"item": "Cracking moment Mcr", "value": mcr / 1e6, "unit": "kN·m"},
                    *[
                        {"item": f"Handling ({k})", "value": v / 1e6, "unit": "kN·m"}
                        for k, v in hm.items()
                    ],
                ],
            )
        ],
        notes=[f"Soil source: {src}. {fc_note}"],
    )


@feature(
    "foundationsPiles.cfaPile",
    "CFA Pile",
    part="substructure",
    fields=[
        number("diameterMm", "Auger diameter D", 600.0, unit="mm", min=300.0),
        number("lengthM", "Pile length L", 15.0, unit="m", min=2.0),
        number("headDepthM", "Cut-off depth", 1.0, unit="m", min=0.0),
        number("overbreakPct", "Concrete overbreak allowance", 12.0, unit="%", min=0.0, max=50.0),
        number("augerPitchMm", "Auger flight pitch", 350.0, unit="mm", min=100.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def cfa_pile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute CFA (continuous flight auger) pile axial capacity, theoretical volume, and overbreak volume."""
    d_m = values["diameterMm"] / 1000.0
    area = math.pi * d_m**2 / 4.0
    theo_vol = area * values["lengthM"]
    actual_vol = theo_vol * (1.0 + values["overbreakPct"] / 100.0)
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        sp = piles.single_pile(
            prof, "bored", d_m, values["lengthM"], values["headDepthM"], method="spt"
        )
        min_fc, fc_note = pile_detailing.least_fc("bored")
    return result(
        summary={
            "allowableCompressionKn": sp["Qa"],
            "theoreticalVolumeM3": theo_vol,
            "targetConcreteM3": actual_vol,
            "leastFcMpa": min_fc,
            "concreteOk": values["fcMpa"] >= min_fc,
        },
        tables=[
            table(
                "CFA pile capacity and pumping quantities",
                [("metric", "Metric"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"metric": "Shaft friction Qs", "value": sp["Qs"], "unit": "kN"},
                    {"metric": "End bearing Qb", "value": sp["Qb"], "unit": "kN"},
                    {"metric": "Allowable compression Qa", "value": sp["Qa"], "unit": "kN"},
                    {"metric": "Theoretical concrete volume", "value": theo_vol, "unit": "m³"},
                    {
                        "metric": "Target pumped volume (with overbreak)",
                        "value": actual_vol,
                        "unit": "m³",
                    },
                ],
            )
        ],
        notes=[
            f"Soil source: {src}. {fc_note} Maintain positive concrete head during auger withdrawal."
        ],
    )


@feature(
    "foundationsPiles.pileCapDesign",
    "Pile Cap Design",
    part="substructure",
    fields=[
        number("puKn", "Factored column load Pu", 2400.0, unit="kN", min=1.0),
        number("colSizeMm", "Square column size", 450.0, unit="mm", min=150.0),
        select(
            "pilesCount",
            "Pile group configuration",
            [("2", "2-pile cap"), ("4", "4-pile (2×2) cap")],
        ),
        number("pileSpacingMm", "Pile centre spacing", 1800.0, unit="mm", min=500.0),
        number("pileDiaMm", "Pile diameter", 600.0, unit="mm", min=200.0),
        number("capThicknessMm", "Pile cap thickness h", 900.0, unit="mm", min=400.0),
        number("coverMm", "Bottom cover over piles", 125.0, unit="mm", min=50.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def pile_cap_design(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Design pile cap tie reinforcement and check concrete struts/nodes by Strut-and-Tie."""
    n = int(values["pilesCount"])
    s = values["pileSpacingMm"]
    c = values["colSizeMm"]
    d_pile = values["pileDiaMm"]
    d_eff = values["capThicknessMm"] - values["coverMm"] - 20.0
    fc, fy = values["fcMpa"], values["fyMpa"]
    pu_n = values["puKn"] * 1e3

    with in_force(ctx.root):
        theta_min = min_angle()
        # Horizontal offset from column load centroid to pile centroid along axis
        lever_u = s / 2.0 - c / 4.0
        angle_deg = math.degrees(math.atan2(d_eff, max(lever_u, 1.0)))
        tie_force_n = (pu_n / 2.0) * (lever_u / d_eff)
        if n == 4:
            tie_force_n = (pu_n / 4.0) * 2.0 * (lever_u / d_eff)
        as_tie_req = tie_force_n / (stm_phi() * fy)
        pile_area = math.pi * d_pile**2 / 4.0
        node_cap_n = node_capacity(fc, pile_area, kind="CCT")
        strut_demand_n = (pu_n / n) / math.sin(math.radians(max(angle_deg, 10.0)))
        strut_cap_n = strut_capacity(fc, pile_area * 0.8, shape="bottle", web=False)
        tie_cap_n = tie_capacity(as_tie_req, fy)

    return result(
        summary={
            "strutAngleDeg": angle_deg,
            "tieForceKn": tie_force_n / 1e3,
            "requiredTieSteelMm2": as_tie_req,
            "pileNodeRatio": (pu_n / n) / node_cap_n,
            "strutRatio": strut_demand_n / strut_cap_n,
            "angleOk": angle_deg >= theta_min,
        },
        tables=[
            table(
                "Strut-and-tie pile cap design",
                [
                    ("element", "STM element"),
                    ("demand", "Demand"),
                    ("capacity", "Capacity"),
                    ("unit", "Unit"),
                ],
                [
                    {
                        "element": "Strut inclination θ",
                        "demand": angle_deg,
                        "capacity": theta_min,
                        "unit": "° (min)",
                    },
                    {
                        "element": "Bottom tie force Tu",
                        "demand": tie_force_n / 1e3,
                        "capacity": tie_cap_n / 1e3,
                        "unit": "kN",
                    },
                    {
                        "element": "CCT nodal zone at pile",
                        "demand": pu_n / n / 1e3,
                        "capacity": node_cap_n / 1e3,
                        "unit": "kN",
                    },
                    {
                        "element": "Bottle-shaped strut",
                        "demand": strut_demand_n / 1e3,
                        "capacity": strut_cap_n / 1e3,
                        "unit": "kN",
                    },
                ],
            )
        ],
        notes=[
            f"Provide As ≥ {as_tie_req:.0f} mm² concentrated over pile bands with full anchorage beyond pile centres."
        ],
    )


@feature(
    "foundationsPiles.punchingCheck",
    "Punching Check",
    part="substructure",
    fields=[
        number("puKn", "Factored column load Pu", 2200.0, unit="kN", min=1.0),
        number("colSizeMm", "Column size", 450.0, unit="mm", min=150.0),
        number("capLengthMm", "Cap length L", 2800.0, unit="mm", min=600.0),
        number("capWidthMm", "Cap width B", 2800.0, unit="mm", min=600.0),
        number("capThicknessMm", "Cap thickness h", 850.0, unit="mm", min=300.0),
        number("coverMm", "Clear bottom cover", 125.0, unit="mm", min=50.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
    ],
    requires_project=False,
)
def pile_cap_punching(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check two-way punching shear around the column in a pile cap."""
    d_mm = values["capThicknessMm"] - values["coverMm"] - 20.0
    if d_mm <= 50.0:
        raise FeatureInputError("Effective depth d is too small.")
    with in_force(ctx.root):
        res = footing_punching(
            0.0,
            0.0,
            values["colSizeMm"],
            values["colSizeMm"],
            values["capLengthMm"],
            values["capWidthMm"],
            d_mm,
            values["fcMpa"],
            [("ULS", values["puKn"] * 1e3, 0.0, 0.0, lambda *_a: 0.0)],
        )
    if res is None:
        raise FeatureInputError("Punching perimeter at d/2 exceeds pile cap dimensions.")
    return result(
        summary={
            "perimeterMm": res.b0,
            "demandStressMpa": res.vu,
            "capacityStressMpa": res.phi_vc,
            "capacityKn": res.phi_vc * res.b0 * res.d / 1e3,
            "utilisation": res.utilisation,
            "ok": res.utilisation <= 1.0,
        },
        tables=[
            table(
                "Pile cap punching shear check",
                [("metric", "Metric"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"metric": "Effective depth d", "value": d_mm, "unit": "mm"},
                    {"metric": "Critical perimeter b0", "value": res.b0, "unit": "mm"},
                    {"metric": "Shear stress demand vu", "value": res.vu, "unit": "MPa"},
                    {"metric": "Concrete resistance φvc", "value": res.phi_vc, "unit": "MPa"},
                    {"metric": "Utilisation", "value": res.utilisation, "unit": "-"},
                ],
            )
        ],
        notes=["Conservative check assuming all piles sit outside the column d/2 punching cone."],
    )


@feature(
    "foundationsPiles.eccentricityCheck",
    "Eccentricity Check",
    part="substructure",
    fields=[
        number("verticalKn", "Service vertical load V", 1800.0, unit="kN", min=0.0),
        number("mxKnm", "Service moment Mx", 120.0, unit="kN·m"),
        number("myKnm", "Service moment My", 90.0, unit="kN·m"),
        number("pileCapacityKn", "Allowable pile compression Qa", 750.0, unit="kN", min=10.0),
        text(
            "pileCoordsMm",
            "Pile coordinates u,v [mm] pairs",
            "-900,-900; 900,-900; -900,900; 900,900",
        ),
    ],
    requires_project=False,
)
def eccentricity_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute rigid-cap elastic pile reactions under eccentric axial load and biaxial moments."""
    coords = parse_pairs(values["pileCoordsMm"], "Pile coordinates")
    spec = pilecap.CapSpec(
        id="CHECK",
        length=4000.0,
        width=4000.0,
        thickness=800.0,
        cover=125.0,
        fc=30.0,
        fy=420.0,
        columns=[ColumnBase("C1", 0.0, 0.0, 400.0, 400.0)],
        piles=coords,
        pile_diameter=600.0,
    )
    # Action vector [N, N·mm]: [P, Cu, Cv]
    load_vec = np.array([values["verticalKn"] * 1e3, values["mxKnm"] * 1e6, values["myKnm"] * 1e6])
    rxns, notes = pilecap.pile_reactions(spec, [load_vec])
    p_kn = [float(r) / 1e3 for r in rxns]
    max_p, min_p = max(p_kn), min(p_kn)
    rows = [
        {
            "pile": f"P{i + 1}",
            "uMm": u,
            "vMm": v,
            "reactionKn": p,
            "ratio": p / values["pileCapacityKn"],
        }
        for i, ((u, v), p) in enumerate(zip(coords, p_kn, strict=True))
    ]
    return result(
        summary={
            "maxPileLoadKn": max_p,
            "minPileLoadKn": min_p,
            "hasTension": min_p < 0.0,
            "maxUtilisation": max_p / values["pileCapacityKn"],
        },
        tables=[
            table(
                "Individual pile reactions",
                [
                    ("pile", "Pile"),
                    ("uMm", "u", "mm"),
                    ("vMm", "v", "mm"),
                    ("reactionKn", "Reaction", "kN"),
                    ("ratio", "Qa ratio"),
                ],
                rows,
            )
        ],
        notes=notes or ["Rigid-cap linear distribution: Pi = V/n ± Mx·v/Σv² ± My·u/Σu²."],
    )


@feature(
    "foundationsPiles.pYCurveGenerator",
    "p-y Curve Generator",
    part="substructure",
    fields=[
        number("depthM", "Depth z below ground", 3.0, unit="m", min=0.2),
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def py_curve_generator(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate lateral soil resistance p-y curve coordinates at a specified depth."""
    z = values["depthM"]
    d_m = values["diameterMm"] / 1000.0
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        rules = pile_lateral_soil.py_rules()
        layer = prof.layer_at(z)
        if layer is None:
            raise FeatureInputError(
                f"Depth {z:g} m is beyond the soil profile bottom ({prof.bottom:g} m)."
            )
        sigma = prof.sigma_v_eff(z)
        wet = prof.water_table is not None and z > prof.water_table
        built = pile_lateral_soil.py_curve(layer, z, d_m, sigma, wet, rules)
    if built is None:
        raise FeatureInputError(
            f"Layer at {z:g} m lacks strength parameters (cu or phi) for p-y generation."
        )
    fn, model_name = built
    ys_mm = [0.0, 2.0, 5.0, 10.0, 20.0, 35.0, 50.0, 75.0, 100.0]
    rows = [{"yMm": y, "pKnPerM": fn(y / 1000.0)} for y in ys_mm]
    return result(
        summary={"depthM": z, "soilModel": model_name, "ultimatePKnPerM": rows[-1]["pKnPerM"]},
        tables=[
            table(
                f"p-y curve at z = {z:g} m ({model_name})",
                [("yMm", "Deflection y", "mm"), ("pKnPerM", "Soil reaction p", "kN/m")],
                rows,
            )
        ],
        notes=[f"Soil source: {src}. Effective overburden σ'v = {sigma:.1f} kPa."],
    )


@feature(
    "foundationsPiles.lateralDeflectionCheck",
    "Lateral Deflection Check",
    part="substructure",
    fields=[
        number("shearKn", "Service lateral head shear H", 60.0, unit="kN", min=0.1),
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        number("lengthM", "Pile length L", 15.0, unit="m", min=2.0),
        number("headDepthM", "Cut-off depth", 1.0, unit="m", min=0.0),
        select("fixity", "Head restraint", [("fixed", "Fixed in cap"), ("free", "Pinned / free")]),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        number("allowDeflMm", "Allowable head deflection", 12.0, unit="mm", min=1.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def lateral_deflection_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check pile head lateral deflection via nonlinear p-y analysis and Winkler stiffness."""
    d_mm, l_mm = values["diameterMm"], values["lengthM"] * 1000.0
    ec = 4700.0 * math.sqrt(values["fcMpa"])
    inertia = math.pi * (d_mm / 1000.0) ** 4 / 64.0
    ei_kn_m2 = ec * 1e3 * inertia
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        stiff = pile_lateral.head_stiffness(
            prof, values["headDepthM"], "bored", d_mm, l_mm, ec, values["fixity"], 1.0
        )
        py_res = pile_lateral_soil.py_analysis(
            prof,
            values["headDepthM"],
            d_mm / 1000.0,
            values["lengthM"],
            ei_kn_m2,
            values["fixity"],
            values["shearKn"],
        )
    defl_py = py_res["y0"] * 1000.0 if py_res else 0.0
    defl_winkler = (values["shearKn"] * 1e3) / stiff["K"] if stiff and stiff["K"] > 0 else 0.0
    gov = max(defl_py, defl_winkler)
    return result(
        summary={
            "pyDeflectionMm": defl_py,
            "winklerDeflectionMm": defl_winkler,
            "allowableMm": values["allowDeflMm"],
            "utilisation": gov / values["allowDeflMm"],
            "ok": gov <= values["allowDeflMm"],
        },
        tables=[
            table(
                "Lateral head deflection summary",
                [
                    ("method", "Method"),
                    ("deflMm", "Head deflection", "mm"),
                    ("limitMm", "Limit", "mm"),
                ],
                [
                    {
                        "method": "Nonlinear p-y finite difference",
                        "deflMm": defl_py,
                        "limitMm": values["allowDeflMm"],
                    },
                    {
                        "method": "Linear Winkler spring (Khh)",
                        "deflMm": defl_winkler,
                        "limitMm": values["allowDeflMm"],
                    },
                ],
            )
        ],
        notes=[f"Soil source: {src}. {stiff['basis'] if stiff else ''}"],
    )


@feature(
    "foundationsPiles.pileHeadStiffnessMatrix",
    "Pile Head Stiffness Matrix",
    part="substructure",
    fields=[
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        number("lengthM", "Pile length L", 18.0, unit="m", min=2.0),
        number("headDepthM", "Cut-off depth", 1.0, unit="m", min=0.0),
        select("fixity", "Head restraint", [("fixed", "Fixed"), ("free", "Free")]),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        number("gRatio", "Modulus reduction G/G0", 1.0, min=0.1, max=1.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def pile_head_stiffness_matrix(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute coupled axial, lateral, and rotational stiffness coefficients at the pile head."""
    d_mm, l_mm = values["diameterMm"], values["lengthM"] * 1000.0
    ec = 4700.0 * math.sqrt(values["fcMpa"])
    d_m = d_mm / 1000.0
    area_m2 = math.pi * d_m**2 / 4.0
    inertia_m4 = math.pi * d_m**4 / 64.0
    ei_kn_m2 = ec * 1e3 * inertia_m4
    k_axial = (ec * 1e3 * area_m2) / values["lengthM"]  # kN/m

    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        stiff = pile_lateral.head_stiffness(
            prof, values["headDepthM"], "bored", d_mm, l_mm, ec, values["fixity"], values["gRatio"]
        )
    if stiff is None:
        raise FeatureInputError(
            "SPT data needed along the upper pile shaft to evaluate soil stiffness."
        )
    beta_m = stiff["beta"] * 1e3
    k_hh = 4.0 * ei_kn_m2 * beta_m**3 if values["fixity"] == "fixed" else 2.0 * ei_kn_m2 * beta_m**3
    k_hm = 2.0 * ei_kn_m2 * beta_m**2 if values["fixity"] == "fixed" else 0.0
    k_mm = 2.0 * ei_kn_m2 * beta_m if values["fixity"] == "fixed" else 0.0

    rows = [
        {"term": "Kzz (axial)", "value": k_axial, "unit": "kN/m"},
        {"term": "Khh (lateral)", "value": k_hh, "unit": "kN/m"},
        {"term": "Khm (coupled shear-rotation)", "value": k_hm, "unit": "kN/rad"},
        {"term": "Kmm (rotational)", "value": k_mm, "unit": "kN·m/rad"},
        {
            "term": "Characteristic length R = (EI/kB)^0.25",
            "value": stiff["R"] / 1000.0,
            "unit": "m",
        },
    ]
    return result(
        summary={
            "kAxialKnM": k_axial,
            "kLateralKnM": k_hh,
            "kRotationalKnmRad": k_mm,
            "fixityDepthM": (1.4 * stiff["R"]) / 1000.0,
        },
        tables=[
            table(
                "Pile head stiffness terms",
                [("term", "Stiffness term"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[f"Soil source: {src}. {stiff['basis']}"],
    )


@feature(
    "foundationsPiles.bendingMomentEnvelope",
    "Bending Moment Envelope",
    part="substructure",
    fields=[
        number("shearKn", "Factored lateral shear Hu", 90.0, unit="kN", min=0.1),
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=200.0),
        number("lengthM", "Pile length L", 15.0, unit="m", min=2.0),
        number("headDepthM", "Cut-off depth", 1.0, unit="m", min=0.0),
        select("fixity", "Head restraint", [("fixed", "Fixed in cap"), ("free", "Free head")]),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def bending_moment_envelope(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute lateral bending moment and shear distribution along the pile shaft."""
    d_m = values["diameterMm"] / 1000.0
    ec = 4700.0 * math.sqrt(values["fcMpa"])
    ei_kn_m2 = ec * 1e3 * (math.pi * d_m**4 / 64.0)
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        py_res = pile_lateral_soil.py_analysis(
            prof,
            values["headDepthM"],
            d_m,
            values["lengthM"],
            ei_kn_m2,
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
        raise FeatureInputError(
            "Unable to run p-y lateral beam analysis on the selected soil profile."
        )
    beta_m = (stiff["beta"] * 1e3) if stiff else 0.5
    h_kn = values["shearKn"]
    y0_mm = py_res["y0"] * 1000.0
    rows = []
    for i in range(11):
        z = min(values["lengthM"], i * (values["lengthM"] / 10.0))
        bz = beta_m * z
        decay = math.exp(-bz)
        if values["fixity"] == "fixed":
            y_mm = y0_mm * decay * (math.cos(bz) + math.sin(bz))
            m_knm = py_res["Mhead"] * decay * (math.cos(bz) - math.sin(bz))
            v_kn = h_kn * decay * math.cos(bz)
        else:
            y_mm = y0_mm * decay * math.cos(bz)
            m_knm = (h_kn / max(beta_m, 1e-6)) * decay * math.sin(bz)
            v_kn = h_kn * decay * (math.cos(bz) - math.sin(bz))
        rows.append({"depthM": z, "deflMm": y_mm, "momentKnm": m_knm, "shearKn": v_kn})
    return result(
        summary={
            "maxMomentKnm": float(py_res["Mmax"]),
            "depthOfMmaxM": float(py_res.get("zM", 0.0)),
            "headDeflectionMm": y0_mm,
        },
        tables=[
            table(
                "Pile bending moment & shear with depth",
                [
                    ("depthM", "Depth below head", "m"),
                    ("deflMm", "y", "mm"),
                    ("momentKnm", "Moment M", "kN·m"),
                    ("shearKn", "Shear V", "kN"),
                ],
                rows,
            )
        ],
        notes=[f"Soil source: {src}. Solved via p-y beam-on-nonlinear-Winkler-foundation."],
    )


@feature(
    "foundationsPiles.pileIntegrityTest",
    "Pile Integrity Test",
    part="substructure",
    fields=[
        number("lengthM", "Nominal pile length L", 18.0, unit="m", min=1.0),
        number("waveSpeedMs", "Stress-wave velocity c", 4000.0, unit="m/s", min=2500.0, max=5000.0),
        number("toeArrivalMs", "Measured toe reflection time", 9.0, unit="ms", min=0.1),
        number("anomalyTimeMs", "Secondary reflection time (0 = none)", 4.2, unit="ms", min=0.0),
        number("impedanceRatio", "Estimated impedance ratio β", 0.88, min=0.1, max=1.5),
    ],
    requires_project=False,
)
def pile_integrity_test(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Interpret low-strain pulse-echo Pile Integrity Test (PIT) wave reflections."""
    l_m, c = values["lengthM"], values["waveSpeedMs"]
    expected_toe_ms = 2.0 * l_m / c * 1000.0
    measured_len = c * (values["toeArrivalMs"] / 1000.0) / 2.0
    anomaly_depth = (
        c * (values["anomalyTimeMs"] / 1000.0) / 2.0 if values["anomalyTimeMs"] > 0 else 0.0
    )
    beta = values["impedanceRatio"]
    rating = (
        "Intact (Class A)"
        if beta >= 0.85
        else ("Minor necking/bulb (Class B)" if beta >= 0.65 else "Significant defect (Class C)")
    )
    return result(
        summary={
            "expectedToeMs": expected_toe_ms,
            "inferredLengthM": measured_len,
            "anomalyDepthM": anomaly_depth,
            "impedanceRatio": beta,
            "classification": rating,
        },
        tables=[
            table(
                "Low-strain PIT interpretation",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "metric": "Expected toe reflection (2L/c)",
                        "value": expected_toe_ms,
                        "unit": "ms",
                    },
                    {"metric": "Inferred length from toe echo", "value": measured_len, "unit": "m"},
                    {"metric": "Anomaly depth (if present)", "value": anomaly_depth, "unit": "m"},
                    {"metric": "Impedance ratio β", "value": beta, "unit": "-"},
                ],
            )
        ],
        notes=[f"Integrity classification: {rating}."],
    )


@feature(
    "foundationsPiles.crossHoleSonic",
    "Cross Hole Sonic",
    part="substructure",
    fields=[
        number("tubeDistMm", "Centre-to-centre tube spacing", 450.0, unit="mm", min=100.0),
        number("refVelocityMs", "Baseline concrete velocity V0", 4100.0, unit="m/s", min=2500.0),
        text("readings", "Depth [m], arrival [μs] pairs", "2,110; 5,112; 8,145; 12,111; 15,109"),
    ],
    requires_project=False,
)
def cross_hole_sonic(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Interpret Cross-Hole Sonic Logging (CSL) first-arrival times and velocity reductions."""
    pairs = parse_pairs(values["readings"], "CSL readings")
    v0 = values["refVelocityMs"]
    t0_us = (values["tubeDistMm"] / 1000.0) / v0 * 1e6
    rows = []
    worst_red = 0.0
    for depth_m, t_us in pairs:
        vel = (values["tubeDistMm"] / 1000.0) / max(t_us * 1e-6, 1e-9)
        red_pct = max(0.0, (1.0 - vel / v0) * 100.0)
        worst_red = max(worst_red, red_pct)
        status = (
            "Good" if red_pct < 10.0 else ("Questionable" if red_pct < 20.0 else "Poor / Defect")
        )
        rows.append(
            {
                "depthM": depth_m,
                "arrivalUs": t_us,
                "velocityMs": vel,
                "reductionPct": red_pct,
                "rating": status,
            }
        )
    return result(
        summary={
            "baselineArrivalUs": t0_us,
            "maxVelocityReductionPct": worst_red,
            "overallStatus": "Good" if worst_red < 10.0 else "Review required",
        },
        tables=[
            table(
                "CSL profile interpretation",
                [
                    ("depthM", "Depth", "m"),
                    ("arrivalUs", "FAT", "μs"),
                    ("velocityMs", "Velocity", "m/s"),
                    ("reductionPct", "Reduction", "%"),
                    ("rating", "Rating"),
                ],
                rows,
            )
        ],
        notes=[
            "Velocity reductions ≥ 20% indicate potential honeycombing, soil inclusion, or necking."
        ],
    )


@feature(
    "foundationsPiles.drivingRecords",
    "Driving Records",
    part="substructure",
    fields=[
        number("ramWeightKn", "Hammer ram weight W", 50.0, unit="kN", min=5.0),
        number("dropHeightM", "Hammer stroke / drop h", 1.2, unit="m", min=0.2),
        number("efficiency", "Hammer efficiency eh", 0.80, min=0.3, max=1.0),
        number("finalSetMm", "Final set per blow s", 3.5, unit="mm", min=0.2),
        number("tempCompMm", "Temporary elastic compression C", 8.0, unit="mm", min=0.5),
        text("blowCounts", "Blows per metre log", "4, 6, 9, 12, 18, 25, 34, 48"),
    ],
    requires_project=False,
)
def driving_records(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate Hiley dynamic driving resistance and log blow counts per metre."""
    blows = parse_floats(values["blowCounts"], "Blow counts")
    energy_kn_mm = values["ramWeightKn"] * (values["dropHeightM"] * 1000.0) * values["efficiency"]
    # Hiley formula: Ru = (eh * W * h) / (s + C/2)
    denom_mm = values["finalSetMm"] + values["tempCompMm"] / 2.0
    ru_kn = energy_kn_mm / denom_mm
    rows = [
        {"metre": i + 1, "blows": b, "cumulative": sum(blows[: i + 1])} for i, b in enumerate(blows)
    ]
    return result(
        summary={
            "ultimateDrivingResistanceKn": ru_kn,
            "allowableFs25Kn": ru_kn / 2.5,
            "totalBlows": sum(blows),
            "finalSetMm": values["finalSetMm"],
        },
        tables=[
            table(
                "Pile driving blow-count record",
                [
                    ("metre", "Penetration", "m"),
                    ("blows", "Blows/m"),
                    ("cumulative", "Cumulative blows"),
                ],
                rows,
            )
        ],
        notes=[
            "Dynamic capacity evaluated by Hiley energy-balance formula with temporary compression C/2."
        ],
    )


@feature(
    "foundationsPiles.pileCageLift",
    "Pile Cage Lift",
    part="substructure",
    fields=[
        number("diameterMm", "Pile diameter D", 600.0, unit="mm", min=300.0),
        number("cageLengthM", "Rebar cage length", 16.0, unit="m", min=2.0),
        number("barCount", "Longitudinal bar count", 8.0, min=4.0, max=40.0),
        number("barDiaMm", "Longitudinal bar diameter", 20.0, unit="mm", min=10.0),
        number("linkDiaMm", "Spiral/tie bar diameter", 10.0, unit="mm", min=6.0),
        number("linkSpacingMm", "Spiral pitch / tie spacing", 150.0, unit="mm", min=50.0),
        number(
            "slingAngleDeg", "Crane sling angle from horizontal", 60.0, unit="°", min=30.0, max=89.0
        ),
    ],
    requires_project=False,
)
def pile_cage_lift(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute pile reinforcement cage mass, lifting sling tensions, and two-point pick deflection."""
    d_cage_m = max(0.15, (values["diameterMm"] - 150.0) / 1000.0)
    l_m = values["cageLengthM"]
    n_bars = round(values["barCount"])
    area_main = math.pi * (values["barDiaMm"] / 1000.0) ** 2 / 4.0
    main_mass = n_bars * area_main * l_m * 7850.0
    spiral_len = (l_m / (values["linkSpacingMm"] / 1000.0)) * math.pi * d_cage_m
    spiral_mass = spiral_len * math.pi * (values["linkDiaMm"] / 1000.0) ** 2 / 4.0 * 7850.0
    total_mass_kg = (main_mass + spiral_mass) * 1.05  # 5% allowance for stiffener rings & laps
    weight_kn = total_mass_kg * 9.81 / 1000.0
    sling_tension_kn = (weight_kn / 2.0) / math.sin(math.radians(values["slingAngleDeg"]))
    # Two-point optimal pick at 0.207 L: Mmax = w L^2 / 46.6
    w_kn_m = weight_kn / l_m
    m_lift = w_kn_m * l_m**2 / 46.6
    return result(
        summary={
            "cageMassKg": total_mass_kg,
            "totalWeightKn": weight_kn,
            "pickOffsetFromEndM": 0.207 * l_m,
            "slingTensionEachKn": sling_tension_kn,
            "maxLiftMomentKnm": m_lift,
        },
        tables=[
            table(
                "Pile cage lifting summary",
                [("item", "Item"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Main bars mass", "value": main_mass, "unit": "kg"},
                    {"item": "Spiral/links mass", "value": spiral_mass, "unit": "kg"},
                    {
                        "item": "Total cage mass (incl. 5% rings)",
                        "value": total_mass_kg,
                        "unit": "kg",
                    },
                    {
                        "item": "Optimal 2-point pick offset (0.207 L)",
                        "value": 0.207 * l_m,
                        "unit": "m",
                    },
                    {"item": "Sling force per leg", "value": sling_tension_kn, "unit": "kN"},
                    {"item": "Cage bending moment at lift", "value": m_lift, "unit": "kN·m"},
                ],
            )
        ],
        notes=[
            "Provide welded stiffener rings at lifting points (0.207 L from ends) to prevent cage ovaling."
        ],
    )

"""Objects - Bolts & Welds tab: bolt grades, hole geometry, slip, welds, anchors & joint checks."""

from __future__ import annotations

import math
from typing import Any

from saengine.design import anchors as anchor_design
from saengine.design import steel_connections as sc
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
from saengine.library.objects import AnchorConcrete, FinPlateConnection
from saengine.report.clauses import in_force


@feature(
    "objectsBoltsWelds.boltGrade",
    "Bolt Grade",
    part="objects",
    fields=[
        select(
            "grade",
            "Bolt grade",
            [
                ("A325N", "A325N (threads included)"),
                ("A325X", "A325X (threads excluded)"),
                ("A490N", "A490N (threads included)"),
                ("A490X", "A490X (threads excluded)"),
                ("A307", "A307 (mild steel)"),
            ],
            "A325N",
        ),
        number("boltDiaMm", "Nominal bolt diameter d", 20.0, unit="mm", min=12.0),
    ],
    requires_project=False,
)
def bolt_grade_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect nominal shear and tensile strengths and single-bolt design capacities for a bolt grade."""
    d = values["boltDiaMm"]
    with in_force(ctx.root):
        props = sc.bolt_grade(values["grade"])
        phi_v_kn = sc.bolt_shear_capacity(values["grade"], d, planes=1) / 1e3
        phi_t_kn, _ = sc.bolt_tension_capacity(values["grade"], d, 0.0)
        phi_t_kn /= 1e3
    rows = [
        {"metric": "Nominal tensile stress Fnt", "value": props["Fnt"], "unit": "MPa"},
        {"metric": "Nominal shear stress Fnv", "value": props["Fnv"], "unit": "MPa"},
        {"metric": "Single-shear design capacity", "value": phi_v_kn, "unit": "kN"},
        {"metric": "Pure tension design capacity", "value": phi_t_kn, "unit": "kN"},
    ]
    return result(
        summary={
            "grade": values["grade"],
            "fntMpa": props["Fnt"],
            "fnvMpa": props["Fnv"],
            "singleShearKn": phi_v_kn,
            "tensionKn": phi_t_kn,
        },
        tables=[
            table(
                f"Bolt grade {values['grade']} (M{d:g})",
                [("metric", "Property"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Bolt strengths and resistance factors are read from the active code pack."],
    )


@feature(
    "objectsBoltsWelds.boltSize",
    "Bolt Size",
    part="objects",
    fields=[
        number("boltDiaMm", "Bolt diameter d", 20.0, unit="mm", min=10.0),
        number("gripMm", "Total connected ply thickness (grip)", 28.0, unit="mm", min=4.0),
        number("nutWasherMm", "Nut + washer + stickout allowance", 35.0, unit="mm", min=15.0),
    ],
    requires_project=False,
)
def bolt_size_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size bolt shank area, standard hole diameter, and required bolt length from grip thickness."""
    d = values["boltDiaMm"]
    with in_force(ctx.root):
        dh = sc.hole_diameter(d)
        dh_net = sc.net_hole(d)
    ab = math.pi * d**2 / 4.0
    raw_len = values["gripMm"] + values["nutWasherMm"]
    std_len = math.ceil(raw_len / 5.0) * 5.0
    rows = [
        {"metric": "Gross bolt shank area Ab", "value": ab, "unit": "mm2"},
        {"metric": "Standard bolt hole diameter", "value": dh, "unit": "mm"},
        {"metric": "Net-section deduction hole width", "value": dh_net, "unit": "mm"},
        {"metric": "Minimum bolt length (rounded 5 mm)", "value": std_len, "unit": "mm"},
    ]
    return result(
        summary={
            "boltDiaMm": d,
            "shankAreaMm2": ab,
            "holeDiaMm": dh,
            "netHoleMm": dh_net,
            "boltLengthMm": std_len,
        },
        tables=[
            table(
                "Bolt geometry & hole sizing",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Standard hole clearance and net-area allowance follow the active code pack."],
    )


@feature(
    "objectsBoltsWelds.holePattern",
    "Hole Pattern",
    part="objects",
    fields=[
        number("boltDiaMm", "Bolt diameter d", 20.0, unit="mm", min=12.0),
        number("rows", "Number of bolt rows (vertical)", 3.0, min=1.0),
        number("lines", "Number of bolt lines (horizontal)", 2.0, min=1.0),
        number("pitchMm", "Vertical pitch p", 70.0, unit="mm", min=25.0),
        number("gaugeMm", "Horizontal gauge g", 80.0, unit="mm", min=25.0),
        number("edgeMm", "Edge distance e", 35.0, unit="mm", min=15.0),
        checkbox("shearedEdge", "Sheared plate edge (else rolled/flame-cut)", False),
    ],
    requires_project=False,
)
def hole_pattern(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a bolt hole grid and verify pitch, gauge, and edge distances against code-pack limits."""
    d = values["boltDiaMm"]
    r, l_ = round(values["rows"]), round(values["lines"])
    p, g, e = values["pitchMm"], values["gaugeMm"], values["edgeMm"]
    with in_force(ctx.root):
        s_min = sc.min_spacing(d)
        e_min = sc.min_edge(d, values["shearedEdge"])
    plate_h = (r - 1) * p + 2.0 * e
    plate_w = (l_ - 1) * g + 2.0 * e
    pitch_ok = r == 1 or p >= s_min
    gauge_ok = l_ == 1 or g >= s_min
    edge_ok = e >= e_min
    return result(
        summary={
            "boltCount": r * l_,
            "plateHeightMm": plate_h,
            "plateWidthMm": plate_w,
            "minSpacingMm": s_min,
            "minEdgeMm": e_min,
            "patternOk": pitch_ok and gauge_ok and edge_ok,
        },
        tables=[
            table(
                "Hole pattern spacing & edge check",
                [
                    ("check", "Check"),
                    ("providedMm", "Provided", "mm"),
                    ("limitMm", "Minimum", "mm"),
                    ("ok", "Pass"),
                ],
                [
                    {"check": "Vertical pitch", "providedMm": p, "limitMm": s_min, "ok": pitch_ok},
                    {
                        "check": "Horizontal gauge",
                        "providedMm": g,
                        "limitMm": s_min,
                        "ok": gauge_ok,
                    },
                    {"check": "Edge distance", "providedMm": e, "limitMm": e_min, "ok": edge_ok},
                ],
            )
        ],
        notes=["Minimum spacing and edge distances read from the active code pack."],
    )


@feature(
    "objectsBoltsWelds.slipFactor",
    "Slip Factor",
    part="objects",
    fields=[
        select(
            "grade", "High-strength bolt grade", [("A325N", "A325"), ("A490N", "A490")], "A325N"
        ),
        number("boltDiaMm", "Bolt diameter d", 20.0, unit="mm", min=16.0),
        select(
            "fayingSurface",
            "Faying surface class",
            [
                ("A", "Class A (unpainted clean mill scale)"),
                ("B", "Class B (blast-cleaned / Class B coating)"),
            ],
            "A",
        ),
        number("slipPlanes", "Number of slip planes", 1.0, min=1.0, max=2.0),
        number("tensionKn", "Co-existing factored tension Tu", 0.0, unit="kN", min=0.0),
    ],
    requires_project=False,
)
def slip_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute slip-critical bolt resistance for Class A/B faying surfaces and tension interaction."""
    conn = FinPlateConnection(
        boltGrade=values["grade"],
        boltDiameter=values["boltDiaMm"],
        slipCritical="strength",
        surfaceClass=values["fayingSurface"],
    )
    with in_force(ctx.root):
        cap_n, slip_note = sc.slip_capacity(
            conn,
            values["boltDiaMm"],
            round(values["slipPlanes"]),
            values["tensionKn"] * 1e3,
        )
    mu_factor = 0.30 if values["fayingSurface"] == "A" else 0.50
    return result(
        summary={
            "surfaceClass": values["fayingSurface"],
            "mu": mu_factor,
            "slipCapacityKn": cap_n / 1e3,
        },
        tables=[
            table(
                "Slip-critical connection capacity",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Slip coefficient mu", "value": mu_factor, "unit": "-"},
                    {
                        "item": "Code-pack slip capacity (1 bolt)",
                        "value": cap_n / 1e3,
                        "unit": "kN",
                    },
                ],
            )
        ],
        notes=[
            slip_note or "Evaluated using engine slip_capacity with active code-pack pretension."
        ],
    )


@feature(
    "objectsBoltsWelds.weldType",
    "Weld Type",
    part="objects",
    fields=[
        select(
            "weldKind",
            "Weld type",
            [
                ("fillet", "Fillet weld"),
                ("cjp", "Complete Joint Penetration (CJP) butt"),
                ("pjp", "Partial Joint Penetration (PJP) groove"),
                ("plug", "Plug / slot weld"),
            ],
            "fillet",
        ),
        number(
            "legOrThroatMm",
            "Leg size w (fillet) or effective throat a (groove)",
            8.0,
            unit="mm",
            min=3.0,
        ),
        number("lengthMm", "Weld length", 250.0, unit="mm", min=20.0),
        number("fexxMpa", "Electrode tensile strength FEXX", 480.0, unit="MPa", min=400.0),
    ],
    requires_project=False,
)
def weld_type_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare effective throat, weld metal area, and design resistance by weld type."""
    kind = values["weldKind"]
    s = values["legOrThroatMm"]
    L = values["lengthMm"]
    if kind == "fillet":
        throat = 0.7071 * s
        with in_force(ctx.root):
            cap_per_mm = sc.fillet_capacity_per_mm(s, values["fexxMpa"])
        cap_kn = cap_per_mm * L / 1e3
    elif kind == "cjp":
        throat = s
        cap_kn = 0.90 * 0.60 * values["fexxMpa"] * throat * L / 1e3
    elif kind == "pjp":
        throat = s
        cap_kn = 0.80 * 0.60 * values["fexxMpa"] * throat * L / 1e3
    else:
        throat = s
        cap_kn = 0.75 * 0.60 * values["fexxMpa"] * (math.pi * throat**2 / 4.0) / 1e3
    return result(
        summary={"weldKind": kind, "effectiveThroatMm": throat, "designCapacityKn": cap_kn},
        tables=[
            table(
                "Weld type summary",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Weld type", "value": kind, "unit": "-"},
                    {"item": "Effective throat thickness", "value": throat, "unit": "mm"},
                    {"item": "Weld design capacity", "value": cap_kn, "unit": "kN"},
                ],
            )
        ],
        notes=[
            "Equal-leg fillet effective throat = 0.707 * leg size; fillet capacity uses active code pack."
        ],
    )


@feature(
    "objectsBoltsWelds.weldSize",
    "Weld Size",
    part="objects",
    fields=[
        number("thinnerPartMm", "Thinner connected part thickness t_min", 10.0, unit="mm", min=2.0),
        number("thickerPartMm", "Thicker connected part thickness t_max", 16.0, unit="mm", min=2.0),
        number("proposedLegMm", "Proposed fillet weld leg w", 8.0, unit="mm", min=2.0),
    ],
    requires_project=False,
)
def weld_size_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Determine minimum and maximum code-pack fillet weld leg sizes for joined plate thicknesses."""
    t1, t2, w = values["thinnerPartMm"], values["thickerPartMm"], values["proposedLegMm"]
    with in_force(ctx.root):
        w_min = sc.fillet_min_size(max(t1, t2))
        w_max = sc.fillet_max_size(min(t1, t2))
    ok = w_min <= w <= w_max
    return result(
        summary={"minLegMm": w_min, "maxLegMm": w_max, "proposedLegMm": w, "sizeOk": ok},
        tables=[
            table(
                "Fillet weld size limits",
                [("item", "Check"), ("valueMm", "Size", "mm"), ("ok", "Status")],
                [
                    {"item": "Minimum weld leg (thicker part)", "valueMm": w_min, "ok": w >= w_min},
                    {"item": "Maximum weld leg (thinner edge)", "valueMm": w_max, "ok": w <= w_max},
                    {"item": "Proposed weld leg", "valueMm": w, "ok": ok},
                ],
            )
        ],
        notes=["Minimum and maximum fillet weld leg limits read from the active code pack."],
    )


@feature(
    "objectsBoltsWelds.effectiveLength",
    "Effective Length",
    part="objects",
    fields=[
        number("weldLengthMm", "Nominal weld run length L", 220.0, unit="mm", min=15.0),
        number("legSizeMm", "Fillet weld leg size w", 8.0, unit="mm", min=3.0),
        checkbox("endReturns", "Returns/craters present (deduct 2*w)", True),
    ],
    requires_project=False,
)
def effective_length(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute effective weld design length accounting for end returns, minimum length, and long-weld beta."""
    L, w = values["weldLengthMm"], values["legSizeMm"]
    l_eff = L - (2.0 * w if values["endReturns"] else 0.0)
    if l_eff <= 0:
        raise FeatureInputError("Weld length must exceed 2*w when end deductions apply.")
    beta_lw = 1.0 if l_eff <= 100.0 * w else max(0.6, 1.2 - 0.002 * (l_eff / w))
    min_len = 4.0 * w
    return result(
        summary={
            "effectiveLengthMm": l_eff,
            "longWeldBeta": beta_lw,
            "designLengthMm": l_eff * beta_lw,
            "meetsMinLength": l_eff >= min_len,
        },
        tables=[
            table(
                "Weld effective length reduction",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Nominal length", "value": L, "unit": "mm"},
                    {"item": "Net effective length", "value": l_eff, "unit": "mm"},
                    {"item": "Minimum 4*w length", "value": min_len, "unit": "mm"},
                    {"item": "Long-weld reduction factor beta", "value": beta_lw, "unit": "-"},
                ],
            )
        ],
        notes=["Applies end crater deduction (2*w) and long-weld reduction for L > 100*w."],
    )


@feature(
    "objectsBoltsWelds.weldStrength",
    "Weld Strength",
    part="objects",
    fields=[
        number("legSizeMm", "Fillet weld leg size w", 8.0, unit="mm", min=3.0),
        number("fexxMpa", "Electrode tensile strength FEXX", 480.0, unit="MPa", min=380.0),
        number("angleDeg", "Load angle to weld axis theta", 0.0, unit="deg", min=0.0, max=90.0),
    ],
    requires_project=False,
)
def weld_strength(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute fillet weld unit capacity per mm including directional strength factor."""
    w, fexx = values["legSizeMm"], values["fexxMpa"]
    with in_force(ctx.root):
        base_n_mm = sc.fillet_capacity_per_mm(w, fexx)
    dir_factor = 1.0 + 0.5 * (math.sin(math.radians(values["angleDeg"])) ** 1.5)
    dir_n_mm = base_n_mm * dir_factor
    return result(
        summary={
            "baseCapacityKnPerMm": base_n_mm / 1e3,
            "directionalFactor": dir_factor,
            "directionalCapacityKnPerMm": dir_n_mm / 1e3,
        },
        tables=[
            table(
                "Fillet weld unit strength",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Longitudinal weld capacity (theta=0)",
                        "value": base_n_mm / 1e3,
                        "unit": "kN/mm",
                    },
                    {
                        "item": "Directional factor (1 + 0.5*sin^1.5)",
                        "value": dir_factor,
                        "unit": "-",
                    },
                    {"item": "Directional capacity", "value": dir_n_mm / 1e3, "unit": "kN/mm"},
                ],
            )
        ],
        notes=[
            "Base weld capacity read from active code pack; directional multiplier applies for transverse loading."
        ],
    )


@feature(
    "objectsBoltsWelds.boltCheck",
    "Bolt Check",
    part="objects",
    fields=[
        select(
            "grade",
            "Bolt grade",
            [("A325N", "A325N"), ("A325X", "A325X"), ("A490N", "A490N"), ("A490X", "A490X")],
            "A325N",
        ),
        number("boltDiaMm", "Bolt diameter d", 20.0, unit="mm", min=12.0),
        number("boltCount", "Total bolts in group", 4.0, min=1.0),
        number("shearPlanes", "Shear planes per bolt", 1.0, min=1.0, max=2.0),
        number("plateThickMm", "Connected plate thickness t", 10.0, unit="mm", min=3.0),
        number("plateFuMpa", "Plate tensile strength Fu", 450.0, unit="MPa", min=300.0),
        number("edgeDistMm", "Edge distance to load direction", 35.0, unit="mm", min=15.0),
        number("vuKn", "Factored group shear Vu", 220.0, unit="kN", min=0.0),
        number("tuKn", "Factored group tension Tu", 40.0, unit="kN", min=0.0),
    ],
    requires_project=False,
)
def bolt_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check bolt group shear, combined tension-shear interaction, and plate bearing capacity."""
    n = round(values["boltCount"])
    d = values["boltDiaMm"]
    v_per = values["vuKn"] * 1e3 / n
    t_per = values["tuKn"] * 1e3 / n
    with in_force(ctx.root):
        v_cap = sc.bolt_shear_capacity(values["grade"], d, round(values["shearPlanes"])) / 1e3
        t_cap, _ = sc.bolt_tension_capacity(values["grade"], d, v_per)
        t_cap /= 1e3
        lc = max(5.0, values["edgeDistMm"] - sc.hole_diameter(d) / 2.0)
        brg_cap = sc.bearing_capacity(d, values["plateThickMm"], values["plateFuMpa"], lc) / 1e3
    u_v = (v_per / 1e3) / v_cap
    u_t = (t_per / 1e3) / t_cap if t_cap > 0 else 99.0
    u_b = (v_per / 1e3) / brg_cap
    rows = [
        {
            "check": "Bolt shear (per bolt)",
            "demandKn": v_per / 1e3,
            "capacityKn": v_cap,
            "util": u_v,
            "ok": u_v <= 1.0,
        },
        {
            "check": "Combined tension (per bolt)",
            "demandKn": t_per / 1e3,
            "capacityKn": t_cap,
            "util": u_t,
            "ok": u_t <= 1.0,
        },
        {
            "check": "Plate bearing/tearout (per bolt)",
            "demandKn": v_per / 1e3,
            "capacityKn": brg_cap,
            "util": u_b,
            "ok": u_b <= 1.0,
        },
    ]
    return result(
        summary={
            "boltShearCapKn": v_cap * n,
            "bearingCapKn": brg_cap * n,
            "governingUtilisation": max(u_v, u_t, u_b),
            "checkOk": max(u_v, u_t, u_b) <= 1.0,
        },
        tables=[
            table(
                "Bolt group capacity checks",
                [
                    ("check", "Check"),
                    ("demandKn", "Demand", "kN"),
                    ("capacityKn", "Capacity", "kN"),
                    ("util", "Utilisation"),
                    ("ok", "Pass"),
                ],
                rows,
            )
        ],
        notes=["Evaluated per bolt with combined shear-tension interaction and edge tearout."],
    )


@feature(
    "objectsBoltsWelds.weldCheck",
    "Weld Check",
    part="objects",
    fields=[
        number("legSizeMm", "Fillet weld leg size w", 8.0, unit="mm", min=3.0),
        number("weldLengthMm", "Total weld line length L", 400.0, unit="mm", min=30.0),
        number("fexxMpa", "Electrode FEXX", 480.0, unit="MPa", min=380.0),
        number("shearKn", "Factored direct shear V", 180.0, unit="kN", min=0.0),
        number("momentKnm", "Factored in-plane moment M = V*e", 12.0, unit="kN-m", min=0.0),
    ],
    requires_project=False,
)
def weld_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify elastic weld-line capacity under combined direct shear and eccentric in-plane moment."""
    L = values["weldLengthMm"]
    # Two vertical lines of length L/2 each, or single vertical line of length L:
    l_line = L / 2.0
    fv = (values["shearKn"] * 1e3) / L  # N/mm
    # Section modulus of two vertical lines of length l_line: Z_weld = 2 * (l_line^2 / 6) = l_line^2 / 3
    fm = (values["momentKnm"] * 1e6) / (l_line**2 / 3.0)  # N/mm
    f_res = math.hypot(fv, fm)
    with in_force(ctx.root):
        cap = sc.fillet_capacity_per_mm(values["legSizeMm"], values["fexxMpa"])
    util = f_res / cap
    return result(
        summary={
            "resultantForceKnPerMm": f_res / 1e3,
            "weldCapacityKnPerMm": cap / 1e3,
            "utilisation": util,
            "checkOk": util <= 1.0,
        },
        tables=[
            table(
                "Elastic weld line check (2 vertical lines)",
                [("component", "Component"), ("valueKnMm", "Stress/Force", "kN/mm")],
                [
                    {"component": "Direct shear fv", "valueKnMm": fv / 1e3},
                    {"component": "Moment shear fm", "valueKnMm": fm / 1e3},
                    {"component": "Resultant demand", "valueKnMm": f_res / 1e3},
                    {"component": "Design capacity", "valueKnMm": cap / 1e3},
                ],
            )
        ],
        notes=["Assumes two equal vertical fillet weld lines sharing total length L."],
    )


@feature(
    "objectsBoltsWelds.combinedCheck",
    "Combined Check",
    part="objects",
    fields=[
        select("grade", "Bolt grade", [("A325N", "A325N"), ("A490N", "A490N")], "A325N"),
        number("boltDiaMm", "Bolt diameter d", 20.0, unit="mm", min=12.0),
        number("boltCount", "Bolt count", 4.0, min=2.0),
        number("weldLegMm", "Weld leg size w", 8.0, unit="mm", min=3.0),
        number("weldLengthMm", "Total weld length", 440.0, unit="mm", min=50.0),
        number("eccentricityMm", "Bolt line eccentricity a", 65.0, unit="mm", min=20.0),
        number("vuKn", "Factored end shear Vu", 200.0, unit="kN", min=0.0),
    ],
    requires_project=False,
)
def combined_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check bolt group and supporting weld group acting in series on a shear plate joint."""
    n = round(values["boltCount"])
    vu_n = values["vuKn"] * 1e3
    with in_force(ctx.root):
        bolt_cap = sc.bolt_shear_capacity(values["grade"], values["boltDiaMm"], 1) * n
        weld_cap_mm = sc.fillet_capacity_per_mm(values["weldLegMm"], 480.0)
    # Elastic weld force with eccentricity a
    l_line = values["weldLengthMm"] / 2.0
    fv = vu_n / values["weldLengthMm"]
    fm = (vu_n * values["eccentricityMm"]) / (l_line**2 / 3.0)
    f_weld = math.hypot(fv, fm)
    u_bolts = vu_n / bolt_cap
    u_weld = f_weld / weld_cap_mm
    gov = max(u_bolts, u_weld)
    return result(
        summary={
            "boltUtilisation": u_bolts,
            "weldUtilisation": u_weld,
            "governingUtilisation": gov,
            "jointOk": gov <= 1.0,
        },
        tables=[
            table(
                "Bolt + weld series joint check",
                [("element", "Component"), ("utilisation", "Utilisation"), ("ok", "Pass")],
                [
                    {"element": "Bolt group shear", "utilisation": u_bolts, "ok": u_bolts <= 1.0},
                    {
                        "element": "Weld group (shear + V*a)",
                        "utilisation": u_weld,
                        "ok": u_weld <= 1.0,
                    },
                ],
            )
        ],
        notes=[
            "Governing joint capacity is the minimum of the bolt group and weld group resistances."
        ],
    )


@feature(
    "objectsBoltsWelds.jointReport",
    "Joint Report",
    part="objects",
    fields=[
        text("jointName", "Connection mark", "J-FIN-1"),
        select("grade", "Bolt grade", [("A325N", "A325N"), ("A490N", "A490N")], "A325N"),
        number("boltDiaMm", "Bolt diameter", 20.0, unit="mm", min=12.0),
        number("rows", "Bolt rows", 3.0, min=2.0),
        number("pitchMm", "Bolt pitch", 70.0, unit="mm", min=40.0),
        number("plateThickMm", "Plate thickness", 10.0, unit="mm", min=4.0),
        number("weldLegMm", "Weld leg size", 8.0, unit="mm", min=3.0),
        number("vuKn", "Factored shear Vu", 180.0, unit="kN", min=0.0),
    ],
    requires_project=False,
)
def joint_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a comprehensive connection report covering bolts, bearing, plate block shear, and welds."""
    r = round(values["rows"])
    d = values["boltDiaMm"]
    t = values["plateThickMm"]
    p = values["pitchMm"]
    edge = 35.0
    vu_n = values["vuKn"] * 1e3
    with in_force(ctx.root):
        bolt_cap = sc.bolt_shear_capacity(values["grade"], d, 1) * r
        brg_cap = sc.bearing_line(d, t, 450.0, r, p, edge)
        agv = ((r - 1) * p + edge) * t
        anv = agv - (r - 0.5) * sc.net_hole(d) * t
        ant = (edge - 0.5 * sc.net_hole(d)) * t
        bs_cap = sc.block_shear(250.0, 450.0, agv, anv, ant)
        weld_len = 2.0 * ((r - 1) * p + 2.0 * edge)
        weld_cap = sc.fillet_capacity_per_mm(values["weldLegMm"], 480.0) * weld_len
    checks = [
        {"mode": "Bolt shear", "capacityKn": bolt_cap / 1e3, "util": vu_n / bolt_cap},
        {"mode": "Plate bearing / tearout", "capacityKn": brg_cap / 1e3, "util": vu_n / brg_cap},
        {"mode": "Plate block shear", "capacityKn": bs_cap / 1e3, "util": vu_n / bs_cap},
        {"mode": "Support fillet welds", "capacityKn": weld_cap / 1e3, "util": vu_n / weld_cap},
    ]
    gov = max(c["util"] for c in checks)
    return result(
        summary={
            "jointName": values["jointName"],
            "governingUtilisation": gov,
            "jointOk": gov <= 1.0,
        },
        tables=[
            table(
                f"Joint capacity report ({values['jointName']})",
                [
                    ("mode", "Failure mode"),
                    ("capacityKn", "Capacity", "kN"),
                    ("util", "Utilisation"),
                ],
                checks,
            )
        ],
        notes=["Combines engine bolt shear, bearing line, block shear, and fillet weld checks."],
    )


@feature(
    "objectsBoltsWelds.anchorType",
    "Anchor Type",
    part="objects",
    fields=[
        select(
            "anchorKind",
            "Anchor type",
            [
                ("headedBolt", "Cast-in headed bolt"),
                ("headedStud", "Cast-in headed stud"),
                ("hookedBolt", "Cast-in hooked J/L bolt"),
                ("expansion", "Post-installed expansion"),
                ("adhesive", "Post-installed adhesive"),
            ],
            "headedBolt",
        ),
        number("diaMm", "Anchor diameter d", 20.0, unit="mm", min=10.0),
        number("embedMm", "Effective embedment depth hef", 250.0, unit="mm", min=50.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fuMpa", "Anchor steel Fu", 450.0, unit="MPa", min=300.0),
    ],
    requires_project=False,
)
def anchor_type_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select cast-in or post-installed concrete anchor type and compute single-anchor tension/shear capacities."""
    spec = AnchorConcrete(
        kind=values["anchorKind"],
        embedment=values["embedMm"],
    )
    grp = anchor_design.Group(
        points=[(0.0, 0.0)],
        diameter=values["diaMm"],
        fu=values["fuMpa"],
        fy=0.75 * values["fuMpa"],
        concrete=values["fcMpa"],
        spec=spec,
    )
    with in_force(ctx.root):
        res = anchor_design.check_group(grp, [anchor_design.Demand(None, [40e3], 15e3)])
    checks = res.get("checks", [])
    rows = [
        {"mode": c["name"], "capacity": c["capacity"], "unit": c["unit"], "ok": c["ok"]}
        for c in checks[:6]
    ]
    steel_t = next(
        (
            c["capacity"]
            for c in checks
            if "steel" in c["name"].lower() and "tension" in c["name"].lower()
        ),
        0.0,
    )
    breakout_t = next(
        (
            c["capacity"]
            for c in checks
            if "breakout" in c["name"].lower() and "tension" in c["name"].lower()
        ),
        0.0,
    )
    steel_v = next(
        (
            c["capacity"]
            for c in checks
            if "steel" in c["name"].lower() and "shear" in c["name"].lower()
        ),
        0.0,
    )
    return result(
        summary={
            "anchorKind": values["anchorKind"],
            "steelTensionKn": steel_t,
            "breakoutTensionKn": breakout_t,
            "steelShearKn": steel_v,
        },
        tables=[
            table(
                "Anchor type capacities",
                [("mode", "Mode"), ("capacity", "Capacity"), ("unit", "Unit"), ("ok", "Pass")],
                rows,
            )
        ],
        notes=["Evaluated through the engine's concrete anchor module under the active code pack."],
    )


@feature(
    "objectsBoltsWelds.embedmentDepth",
    "Embedment Depth",
    part="objects",
    fields=[
        number("diaMm", "Anchor diameter d", 20.0, unit="mm", min=10.0),
        number("hefMm", "Effective embedment hef", 250.0, unit="mm", min=50.0),
        number("edgeDistMm", "Minimum concrete edge distance ca1", 200.0, unit="mm", min=40.0),
        number("memberThickMm", "Concrete pedestal/slab thickness ha", 450.0, unit="mm", min=100.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
    ],
    requires_project=False,
)
def embedment_depth_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate concrete tension breakout cone radius 1.5*hef and narrow-member effective hef."""
    hef, ca1, ha = values["hefMm"], values["edgeDistMm"], values["memberThickMm"]
    half_cone = 1.5 * hef
    # Narrow member check if all edges < 1.5*hef
    hef_eff = min(hef, ca1 / 1.5) if ca1 < half_cone else hef
    grp = anchor_design.Group(
        points=[(0.0, 0.0)],
        diameter=values["diaMm"],
        fu=450.0,
        fy=350.0,
        concrete=values["fcMpa"],
        spec=AnchorConcrete(kind="headedBolt", embedment=hef),
        edges=(ca1, 1e6, 1e6, 1e6),
    )
    with in_force(ctx.root):
        res = anchor_design.check_group(grp, [anchor_design.Demand(None, [50e3], 20e3)])
    checks = res.get("checks", [])
    rows = [
        {
            "check": c["name"],
            "demand": c["demand"],
            "capacity": c["capacity"],
            "unit": c["unit"],
            "ok": c["ok"],
        }
        for c in checks[:6]
    ]
    return result(
        summary={
            "hefMm": hef,
            "projectedConeRadiusMm": half_cone,
            "effectiveHefMm": hef_eff,
            "pedestalClearBelowMm": ha - hef,
        },
        tables=[
            table(
                "Embedment & edge breakout checks",
                [
                    ("check", "Check"),
                    ("demand", "Demand"),
                    ("capacity", "Capacity"),
                    ("unit", "Unit"),
                    ("ok", "Pass"),
                ],
                rows,
            )
        ],
        notes=["Tension breakout projects a 1.5*hef cone around each anchor."],
    )


@feature(
    "objectsBoltsWelds.basePlateHole",
    "Base Plate Hole",
    part="objects",
    fields=[
        number("anchorDiaMm", "Anchor rod diameter d", 24.0, unit="mm", min=12.0),
        number("plateThickMm", "Base plate thickness tp", 25.0, unit="mm", min=10.0),
        select(
            "holeType",
            "Hole sizing",
            [("oversized", "Base-plate oversized hole"), ("standard", "Standard bolt hole")],
            "oversized",
        ),
    ],
    requires_project=False,
)
def base_plate_hole(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure oversized base-plate anchor holes and washer plate dimensions."""
    d = values["anchorDiaMm"]
    if values["holeType"] == "oversized":
        # Common steel base-plate oversized anchor hole practice: d + 8..14 mm
        hole_d = d + (8.0 if d <= 24.0 else 12.0)
        washer_t = max(8.0, 0.35 * d)
        washer_size = hole_d + 2.0 * d
    else:
        with in_force(ctx.root):
            hole_d = sc.hole_diameter(d)
        washer_t = 6.0
        washer_size = hole_d + 1.5 * d
    return result(
        summary={
            "anchorDiaMm": d,
            "holeDiaMm": hole_d,
            "washerSizeMm": washer_size,
            "washerThickMm": washer_t,
        },
        tables=[
            table(
                "Base plate hole & plate-washer detail",
                [("item", "Parameter"), ("valueMm", "Dimension", "mm")],
                [
                    {"item": "Anchor rod diameter", "valueMm": d},
                    {"item": "Base plate hole diameter", "valueMm": hole_d},
                    {"item": "Plate washer square size", "valueMm": washer_size},
                    {"item": "Plate washer minimum thickness", "valueMm": washer_t},
                ],
            )
        ],
        notes=[
            "Oversized base-plate holes accommodate anchor setting tolerances when covered by plate washers."
        ],
    )


@feature(
    "objectsBoltsWelds.edgePreparation",
    "Edge Preparation",
    part="objects",
    fields=[
        select(
            "prepType",
            "Groove preparation",
            [
                ("singleV", "Single-V butt"),
                ("doubleV", "Double-V butt"),
                ("singleBevel", "Single-bevel T/corner"),
            ],
            "singleV",
        ),
        number("plateThickMm", "Plate thickness t", 20.0, unit="mm", min=4.0),
        number(
            "bevelAngleDeg", "Included groove angle alpha", 60.0, unit="deg", min=25.0, max=90.0
        ),
        number("rootGapMm", "Root opening g", 3.0, unit="mm", min=0.0, max=10.0),
        number("rootFaceMm", "Root face height", 2.0, unit="mm", min=0.0, max=6.0),
        number("weldLengthMm", "Joint length", 300.0, unit="mm", min=20.0),
    ],
    requires_project=False,
)
def edge_preparation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute groove weld cross-sectional bevel geometry and weld metal volume."""
    t, g, rf = values["plateThickMm"], values["rootGapMm"], values["rootFaceMm"]
    if rf >= t:
        raise FeatureInputError("Root face must be less than plate thickness.")
    bevel_h = t - rf
    alpha_rad = math.radians(values["bevelAngleDeg"])
    if values["prepType"] == "doubleV":
        h_half = bevel_h / 2.0
        a_groove = t * g + 2.0 * (h_half**2 * math.tan(alpha_rad / 2.0))
    elif values["prepType"] == "singleBevel":
        a_groove = t * g + 0.5 * bevel_h**2 * math.tan(alpha_rad)
    else:
        a_groove = t * g + bevel_h**2 * math.tan(alpha_rad / 2.0)
    vol_cm3 = a_groove * values["weldLengthMm"] / 1000.0
    mass_kg = vol_cm3 * 7.85 / 1000.0
    return result(
        summary={
            "prepType": values["prepType"],
            "grooveAreaMm2": a_groove,
            "weldVolumeCm3": vol_cm3,
            "weldMetalMassKg": mass_kg,
        },
        tables=[
            table(
                "Groove weld edge preparation",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Bevel depth", "value": bevel_h, "unit": "mm"},
                    {"item": "Cross-sectional weld area", "value": a_groove, "unit": "mm2"},
                    {"item": "Weld metal volume", "value": vol_cm3, "unit": "cm3"},
                    {"item": "Weld metal mass", "value": mass_kg, "unit": "kg"},
                ],
            )
        ],
        notes=["Weld metal mass assumes 7.85 g/cm3 deposited steel density."],
    )


@feature(
    "objectsBoltsWelds.ndtMethod",
    "NDT Method",
    part="objects",
    fields=[
        select(
            "jointCriticality",
            "Joint demand class",
            [
                ("moment", "Moment / seismic critical CJP"),
                ("primaryShear", "Primary shear / gusset fillet"),
                ("secondary", "Secondary bracing / purlin"),
            ],
            "moment",
        ),
        number("plateThickMm", "Plate thickness", 20.0, unit="mm", min=4.0),
        number("weldLengthM", "Total weld length to inspect", 12.0, unit="m", min=0.2),
    ],
    requires_project=False,
)
def ndt_method(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign non-destructive testing coverage (VT, MT, PT, UT/RT) by joint criticality and thickness."""
    crit = values["jointCriticality"]
    t = values["plateThickMm"]
    L = values["weldLengthM"]
    if crit == "moment":
        methods = [
            ("Visual Testing (VT)", 100.0),
            ("Ultrasonic Testing (UT)", 100.0 if t >= 8.0 else 25.0),
            ("Magnetic Particle (MT)", 25.0),
        ]
    elif crit == "primaryShear":
        methods = [
            ("Visual Testing (VT)", 100.0),
            ("Magnetic Particle (MT)", 20.0),
            ("Ultrasonic Testing (UT)", 10.0 if t >= 16.0 else 0.0),
        ]
    else:
        methods = [("Visual Testing (VT)", 100.0), ("Dye Penetrant / MT", 5.0)]
    rows = [
        {"method": m, "coveragePct": pct, "inspectLengthM": L * pct / 100.0} for m, pct in methods
    ]
    return result(
        summary={
            "jointClass": crit,
            "totalWeldLengthM": L,
            "utLengthM": sum(r["inspectLengthM"] for r in rows if "UT" in r["method"]),
        },
        tables=[
            table(
                "NDT inspection schedule",
                [
                    ("method", "NDT method"),
                    ("coveragePct", "Coverage", "%"),
                    ("inspectLengthM", "Inspect length", "m"),
                ],
                rows,
            )
        ],
        notes=["Ultrasonic testing applies to full-penetration butt welds >= 8 mm thick."],
    )


@feature(
    "objectsBoltsWelds.backingBar",
    "Backing Bar",
    part="objects",
    fields=[
        number("rootGapMm", "Groove root opening g", 6.0, unit="mm", min=2.0),
        number("plateThickMm", "Joined plate thickness t", 20.0, unit="mm", min=6.0),
        select(
            "material",
            "Backing bar material",
            [("steel", "Permanent structural steel"), ("ceramic", "Removable ceramic tile")],
            "steel",
        ),
        number("jointLengthMm", "Joint length", 300.0, unit="mm", min=50.0),
    ],
    requires_project=False,
)
def backing_bar(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size steel or ceramic backing bars for single-sided groove welds."""
    g = values["rootGapMm"]
    w = max(25.0, g + 16.0)
    t_bar = (
        max(6.0, min(10.0, values["plateThickMm"] / 3.0)) if values["material"] == "steel" else 8.0
    )
    mass_kg = (
        (w * t_bar * values["jointLengthMm"] * 1e-9 * 7850.0)
        if values["material"] == "steel"
        else 0.0
    )
    return result(
        summary={
            "material": values["material"],
            "backingWidthMm": w,
            "backingThickMm": t_bar,
            "steelMassKg": mass_kg,
        },
        tables=[
            table(
                "Backing bar specification",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Material", "value": values["material"], "unit": "-"},
                    {"item": "Backing width", "value": w, "unit": "mm"},
                    {"item": "Backing thickness", "value": t_bar, "unit": "mm"},
                    {"item": "Steel mass", "value": mass_kg, "unit": "kg"},
                ],
            )
        ],
        notes=[
            "Width provides >= 8 mm landing on each plate root edge; steel backing must be removed at cyclic tension zones if required."
        ],
    )


@feature(
    "objectsBoltsWelds.patternGenerator",
    "Pattern Generator",
    part="objects",
    fields=[
        select(
            "patternType",
            "Pattern geometry",
            [("rectangular", "Rectangular grid"), ("circular", "Circular bolt ring")],
            "rectangular",
        ),
        number("nx", "Columns (rectangular) or total bolts (circular)", 3.0, min=1.0),
        number("ny", "Rows (rectangular only)", 4.0, min=1.0),
        number("spacingXMm", "Gauge X or Ring diameter", 100.0, unit="mm", min=30.0),
        number("spacingYMm", "Pitch Y (rectangular)", 75.0, unit="mm", min=30.0),
    ],
    requires_project=False,
)
def pattern_generator(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate centred bolt hole coordinates and polar moment of inertia Ip = sum(x^2 + y^2)."""
    pts: list[tuple[float, float]] = []
    if values["patternType"] == "circular":
        n = max(3, round(values["nx"]))
        r = values["spacingXMm"] / 2.0
        for i in range(n):
            ang = 2.0 * math.pi * i / n
            pts.append((r * math.cos(ang), r * math.sin(ang)))
    else:
        nx, ny = round(values["nx"]), round(values["ny"])
        sx, sy = values["spacingXMm"], values["spacingYMm"]
        for i in range(nx):
            for j in range(ny):
                pts.append(((i - (nx - 1) / 2.0) * sx, (j - (ny - 1) / 2.0) * sy))
    ip = sum(x * x + y * y for x, y in pts)
    rows = [
        {"bolt": i + 1, "xMm": x, "yMm": y, "radiusMm": math.hypot(x, y)}
        for i, (x, y) in enumerate(pts)
    ]
    return result(
        summary={
            "boltCount": len(pts),
            "polarInertiaIpMm2": ip,
            "maxRadiusMm": max(r["radiusMm"] for r in rows),
        },
        tables=[
            table(
                "Generated bolt coordinates",
                [
                    ("bolt", "Bolt #"),
                    ("xMm", "x", "mm"),
                    ("yMm", "y", "mm"),
                    ("radiusMm", "r", "mm"),
                ],
                rows,
            )
        ],
        notes=["Polar inertia Ip = sum(x^2 + y^2) supports elastic eccentric bolt-group analysis."],
    )


@feature(
    "objectsBoltsWelds.edgeDistance",
    "Edge Distance",
    part="objects",
    fields=[
        number("boltDiaMm", "Bolt diameter d", 20.0, unit="mm", min=10.0),
        number("plateThickMm", "Connected plate thickness t", 10.0, unit="mm", min=3.0),
        number("providedEdgeMm", "Provided edge distance e", 35.0, unit="mm", min=10.0),
        checkbox("shearedEdge", "Sheared edge", False),
    ],
    requires_project=False,
)
def edge_distance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check provided bolt edge/end distance against code-pack minimum and maximum limits."""
    d, t, e = values["boltDiaMm"], values["plateThickMm"], values["providedEdgeMm"]
    with in_force(ctx.root):
        e_min = sc.min_edge(d, values["shearedEdge"])
        data = sc.connection_data()
        e_max = min(float(data.maxEdgeThickness) * t, float(data.maxEdge))
    ok = e_min <= e <= e_max
    return result(
        summary={"minEdgeMm": e_min, "maxEdgeMm": e_max, "providedEdgeMm": e, "edgeOk": ok},
        tables=[
            table(
                "Bolt edge distance limits",
                [("limit", "Limit"), ("valueMm", "Distance", "mm"), ("ok", "Pass")],
                [
                    {"limit": "Minimum edge distance", "valueMm": e_min, "ok": e >= e_min},
                    {
                        "limit": "Maximum edge distance (corrosion/buckling)",
                        "valueMm": e_max,
                        "ok": e <= e_max,
                    },
                ],
            )
        ],
        notes=["Minimum and maximum edge distance limits read from the active code pack."],
    )


@feature(
    "objectsBoltsWelds.washerType",
    "Washer Type",
    part="objects",
    fields=[
        number("boltDiaMm", "Bolt diameter d", 20.0, unit="mm", min=12.0),
        select(
            "holeKind",
            "Hole type",
            [
                ("standard", "Standard round hole"),
                ("oversized", "Oversized / short-slotted"),
                ("longSlot", "Long-slotted hole"),
            ],
            "standard",
        ),
        select(
            "flangeSlope",
            "Flange surface",
            [("flat", "Parallel / flat face"), ("sloped", "Tapered beam/channel flange")],
            "flat",
        ),
    ],
    requires_project=False,
)
def washer_type(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select hardened flat, plate, or bevelled washers for bolted structural joints."""
    d = values["boltDiaMm"]
    if values["flangeSlope"] == "sloped":
        spec = "Hardened bevelled washer (matching flange taper)"
        t_mm = 6.0
        od_mm = 2.2 * d
    elif values["holeKind"] == "longSlot":
        spec = "Structural plate washer (min 8 mm thick covering slot)"
        t_mm = 8.0
        od_mm = 3.0 * d
    elif values["holeKind"] == "oversized":
        spec = "Hardened flat washer (thickened / oversized OD)"
        t_mm = 4.5
        od_mm = 2.4 * d
    else:
        spec = "Standard hardened circular flat washer (turned side)"
        t_mm = 3.5
        od_mm = 2.0 * d
    return result(
        summary={"washerSpec": spec, "washerThickMm": t_mm, "washerOuterMm": od_mm},
        tables=[
            table(
                "Washer selection",
                [("item", "Property"), ("value", "Specification")],
                [
                    {"item": "Washer type", "value": spec},
                    {"item": "Minimum thickness [mm]", "value": t_mm},
                    {"item": "Outer width/diameter [mm]", "value": od_mm},
                ],
            )
        ],
        notes=["Bevelled washers prevent bolt bending on tapered rolled flanges."],
    )


@feature(
    "objectsBoltsWelds.staggeredPattern",
    "Staggered Pattern",
    part="objects",
    fields=[
        number("plateWidthMm", "Gross plate width b", 200.0, unit="mm", min=60.0),
        number("plateThickMm", "Plate thickness t", 10.0, unit="mm", min=3.0),
        number("boltDiaMm", "Bolt diameter d", 20.0, unit="mm", min=12.0),
        number("staggerPitchMm", "Longitudinal stagger pitch s", 40.0, unit="mm", min=0.0),
        number("gaugeMm", "Transverse gauge g", 60.0, unit="mm", min=25.0),
    ],
    requires_project=False,
)
def staggered_pattern(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate staggered fastener net-section width using the s^2 / (4g) diagonal chain rule."""
    b, t, d = values["plateWidthMm"], values["plateThickMm"], values["boltDiaMm"]
    s, g = values["staggerPitchMm"], values["gaugeMm"]
    with in_force(ctx.root):
        dh = sc.net_hole(d)
    # Compare straight 1-hole path vs staggered 2-hole path: b - 2*dh + s^2/(4g)
    w_straight = b - dh
    w_zig = b - 2.0 * dh + (s**2) / (4.0 * g)
    w_gov = min(w_straight, w_zig)
    ag = b * t
    an = w_gov * t
    return result(
        summary={
            "netHoleWidthMm": dh,
            "straightNetWidthMm": w_straight,
            "staggeredNetWidthMm": w_zig,
            "governingNetAreaMm2": an,
            "netToGrossRatio": an / ag,
        },
        tables=[
            table(
                "Staggered hole net-section comparison",
                [
                    ("path", "Failure path"),
                    ("netWidthMm", "Net width", "mm"),
                    ("netAreaMm2", "Net area", "mm2"),
                ],
                [
                    {
                        "path": "Straight (1 hole)",
                        "netWidthMm": w_straight,
                        "netAreaMm2": w_straight * t,
                    },
                    {
                        "path": "Zig-zag (2 holes, s^2/4g)",
                        "netWidthMm": w_zig,
                        "netAreaMm2": w_zig * t,
                    },
                ],
            )
        ],
        notes=[
            "Applies Cochran s^2/(4g) stagger allowance to compare straight vs diagonal fracture paths."
        ],
    )

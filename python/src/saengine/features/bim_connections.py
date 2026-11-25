"""BIM structural connection detail feature buttons."""

from __future__ import annotations

from typing import Any

from saengine.design import steel_connections as sc
from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.bim_common import element_rows, require_bim, write_bim_csv, write_bim_json
from saengine.report.clauses import in_force


def _check_member_exists(data: dict[str, Any], member_id: str) -> str:
    ids = {str(r.get("id", "")) for r in element_rows(data)}
    m = member_id.strip()
    if m and ids and m not in ids:
        raise FeatureInputError(f"Member {m!r} was not found in 06 BIM/bim.json.")
    return m


@feature(
    "bimAdditionsConnections.momentConnection",
    "Moment Connection",
    part="bim",
    fields=[
        text("memberA", "Beam member ID", "B1"),
        text("memberB", "Column member ID", "C1"),
        select(
            "joint", "Joint type", [("full", "Full moment"), ("partial", "Partial moment")], "full"
        ),
        number("momentKnm", "Factored end moment M_u", 120.0, unit="kN·m", min=1.0),
        number("beamDepthMm", "Beam overall depth d", 400.0, unit="mm", min=150.0),
        text("boltGrade", "Bolt grade", "8.8"),
        number("boltDiameterMm", "Bolt diameter", 20.0, unit="mm", min=12.0),
    ],
)
def moment_connection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check beam-column end-plate moment connection bolt tension, flange couple, and welds."""
    data = require_bim(ctx)
    m_a = _check_member_exists(data, values["memberA"])
    m_b = _check_member_exists(data, values["memberB"])
    mu_nmm = float(values["momentKnm"]) * 1e6
    arm_mm = max(100.0, float(values["beamDepthMm"]) - 30.0)
    flange_force_n = mu_nmm / arm_mm
    factor = 1.0 if values["joint"] == "full" else 0.70
    with in_force(ctx.root):
        bolt_t_n, _note = sc.bolt_tension_capacity(
            values["boltGrade"], float(values["boltDiameterMm"])
        )
        weld_cap_n_mm = sc.fillet_capacity_per_mm(8.0, 480.0)
    top_bolts = 4
    bolt_demand_each = (flange_force_n * factor) / top_bolts
    bolt_util = bolt_demand_each / bolt_t_n if bolt_t_n > 0 else 99.0
    req_weld_len = (flange_force_n * factor) / weld_cap_n_mm if weld_cap_n_mm > 0 else 0.0
    conn = {
        "memberA": m_a,
        "memberB": m_b,
        "joint": values["joint"],
        "flangeForceKn": round(flange_force_n / 1000.0, 1),
        "boltUtilisation": round(bolt_util, 3),
        "requiredWeldMm": round(req_weld_len, 0),
        "ok": bolt_util <= 1.0,
    }
    path = write_bim_json(ctx, "moment-connection.json", conn)
    return result(
        summary={**conn, "exportPath": path},
        tables=[
            table(
                "Moment connection resistance check",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Flange force couple T_f = M / (d - t_f)",
                        "value": round(flange_force_n / 1000.0, 1),
                        "unit": "kN",
                    },
                    {
                        "item": "Per-bolt tension (4 tension bolts)",
                        "value": round(bolt_demand_each / 1000.0, 1),
                        "unit": "kN",
                    },
                    {
                        "item": "Bolt tension capacity",
                        "value": round(bolt_t_n / 1000.0, 1),
                        "unit": "kN",
                    },
                    {"item": "Bolt tension utilisation", "value": round(bolt_util, 3), "unit": "-"},
                    {
                        "item": "Min 8 mm flange fillet weld length",
                        "value": round(req_weld_len, 0),
                        "unit": "mm",
                    },
                ],
            )
        ],
        notes=[
            f"Uses code-pack bolt tension & weld capacity via saengine.design.steel_connections; saved to {path}."
        ],
    )


@feature(
    "bimAdditionsConnections.shearConnection",
    "Shear Connection",
    part="bim",
    fields=[
        text("beam", "Beam ID", "B1"),
        text("column", "Column ID", "C1"),
        number("reaction", "Factored end shear V_u", 100.0, unit="kN", min=1.0),
        text("boltGrade", "Bolt grade", "8.8"),
        number("boltDiameterMm", "Bolt diameter", 20.0, unit="mm", min=12.0),
        number("plateThicknessMm", "Fin plate thickness", 10.0, unit="mm", min=6.0),
    ],
)
def shear_connection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Design fin-plate shear connection bolt count, bolt shear utilisation, and plate shear check."""
    import math

    data = require_bim(ctx)
    beam = _check_member_exists(data, values["beam"])
    col = _check_member_exists(data, values["column"])
    vu_n = float(values["reaction"]) * 1000.0
    d_b = float(values["boltDiameterMm"])
    t_p = float(values["plateThicknessMm"])
    with in_force(ctx.root):
        v_bolt_n = sc.bolt_shear_capacity(values["boltGrade"], d_b, planes=1)
        min_s = sc.min_spacing(d_b)
        min_e = sc.min_edge(d_b)
    n_bolts = max(2, math.ceil(vu_n / v_bolt_n)) if v_bolt_n > 0 else 2
    plate_depth = (n_bolts - 1) * min_s + 2.0 * min_e
    plate_gross_cap_n = 0.90 * 0.60 * 250.0 * plate_depth * t_p
    bolt_util = vu_n / (n_bolts * v_bolt_n) if v_bolt_n > 0 else 99.0
    plate_util = vu_n / plate_gross_cap_n if plate_gross_cap_n > 0 else 99.0
    conn = {
        "beam": beam,
        "column": col,
        "reactionKn": float(values["reaction"]),
        "boltsRequired": n_bolts,
        "plateDepthMm": round(plate_depth, 0),
        "boltUtilisation": round(bolt_util, 3),
        "plateUtilisation": round(plate_util, 3),
        "ok": max(bolt_util, plate_util) <= 1.0,
    }
    path = write_bim_json(ctx, "shear-connection.json", conn)
    return result(
        summary={**conn, "exportPath": path},
        tables=[
            table(
                "Fin-plate shear connection check",
                [
                    ("check", "Check"),
                    ("demandKn", "Demand", "kN"),
                    ("capacityKn", "Capacity", "kN"),
                    ("util", "Util"),
                ],
                [
                    {
                        "check": f"{n_bolts}x M{int(d_b)} bolt single shear",
                        "demandKn": values["reaction"],
                        "capacityKn": round(n_bolts * v_bolt_n / 1000.0, 1),
                        "util": round(bolt_util, 3),
                    },
                    {
                        "check": f"Plate gross shear ({plate_depth:.0f}x{t_p:g} mm)",
                        "demandKn": values["reaction"],
                        "capacityKn": round(plate_gross_cap_n / 1000.0, 1),
                        "util": round(plate_util, 3),
                    },
                ],
            )
        ],
        notes=[
            f"Detailing pitch={min_s:.0f} mm, end={min_e:.0f} mm via saengine.design.steel_connections; saved to {path}."
        ],
    )


@feature(
    "bimAdditionsConnections.bracingConnection",
    "Bracing Connection",
    part="bim",
    fields=[
        text("brace", "Brace member ID", "M2"),
        text("frame", "Frame member ID", "C1"),
        number("axialForce", "Factored brace axial force N_u", 180.0, unit="kN", min=1.0),
        number("gussetThicknessMm", "Gusset plate thickness", 12.0, unit="mm", min=6.0),
        number("boltDiameterMm", "Bolt diameter", 20.0, unit="mm", min=12.0),
    ],
)
def bracing_connection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check brace-to-gusset bolts and Whitmore effective width yield resistance."""
    import math

    data = require_bim(ctx)
    brace = _check_member_exists(data, values["brace"])
    frame = _check_member_exists(data, values["frame"])
    nu_n = float(values["axialForce"]) * 1000.0
    d_b = float(values["boltDiameterMm"])
    t_g = float(values["gussetThicknessMm"])
    with in_force(ctx.root):
        v_bolt = sc.bolt_shear_capacity("8.8", d_b, planes=1)
        pitch = sc.min_spacing(d_b)
    n_bolts = max(2, math.ceil(nu_n / v_bolt))
    conn_len = (n_bolts - 1) * pitch
    # Whitmore 30-degree spread across single line of bolts (gauge = 0)
    whitmore_w = max(80.0, 2.0 * conn_len * math.tan(math.radians(30.0)))
    whitmore_cap_n = 0.90 * 250.0 * whitmore_w * t_g
    util = max(nu_n / (n_bolts * v_bolt), nu_n / whitmore_cap_n)
    conn = {
        "brace": brace,
        "frame": frame,
        "axialKn": float(values["axialForce"]),
        "bolts": n_bolts,
        "whitmoreWidthMm": round(whitmore_w, 0),
        "utilisation": round(util, 3),
        "ok": util <= 1.0,
    }
    path = write_bim_json(ctx, "bracing-connection.json", conn)
    return result(
        summary={**conn, "exportPath": path},
        tables=[
            table(
                "Brace gusset plate & bolt check",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Required bolts (8.8 M20)", "value": n_bolts, "unit": "ea"},
                    {
                        "item": "Whitmore 30° effective width",
                        "value": round(whitmore_w, 0),
                        "unit": "mm",
                    },
                    {
                        "item": "Gusset Whitmore yield capacity",
                        "value": round(whitmore_cap_n / 1000.0, 1),
                        "unit": "kN",
                    },
                    {"item": "Governing utilisation", "value": round(util, 3), "unit": "-"},
                ],
            )
        ],
        notes=[f"Uses 30-deg Whitmore stress dispersion width and bolt shear; saved to {path}."],
    )


@feature(
    "bimAdditionsConnections.baseConnection",
    "Base Connection",
    part="bim",
    fields=[
        text("column", "Column ID", "C1"),
        number("axial", "Factored axial compression N_u", 500.0, unit="kN", min=0.0),
        number("moment", "Factored base moment M_u", 50.0, unit="kN·m", min=0.0),
        number("columnDepthMm", "Column section depth d", 300.0, unit="mm", min=100.0),
        number("columnWidthMm", "Column flange width b", 300.0, unit="mm", min=100.0),
        number("plateBmm", "Baseplate width B", 420.0, unit="mm", min=150.0),
        number("plateNmm", "Baseplate length N", 420.0, unit="mm", min=150.0),
        number("plateThickMm", "Baseplate thickness t_p", 24.0, unit="mm", min=8.0),
        number("fcMpa", "Pedestal concrete f'c", 28.0, unit="MPa", min=15.0),
    ],
)
def base_connection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check column baseplate bearing, cantilever plate bending thickness, and anchor rod tension."""
    import math

    data = require_bim(ctx)
    col = _check_member_exists(data, values["column"])
    pu = float(values["axial"]) * 1000.0
    mu = float(values["moment"]) * 1e6
    B = float(values["plateBmm"])
    N = float(values["plateNmm"])
    t_p = float(values["plateThickMm"])
    d_c = float(values["columnDepthMm"])
    b_c = float(values["columnWidthMm"])
    fc = float(values["fcMpa"])
    fp_allow = 0.65 * 0.85 * fc  # MPa
    ecc = mu / pu if pu > 1.0 else 1e6
    # Bearing & anchor tension with moment M_u and lever arm to anchor row
    m_cant = max(0.0, (N - 0.95 * d_c) / 2.0)
    n_cant = max(0.0, (B - 0.80 * b_c) / 2.0)
    cant = max(m_cant, n_cant)
    if ecc <= N / 6.0:
        fp_max = (pu / (B * N)) * (1.0 + 6.0 * ecc / N)
        anchor_tension_kn = 0.0
    else:
        fp_max = min(
            fp_allow * 1.5, (2.0 * pu) / (3.0 * B * max(25.0, N / 2.0 - min(ecc, N / 2.0 - 25.0)))
        )
        lever = max(50.0, 0.40 * N)
        anchor_tension_kn = max(0.0, (mu - pu * (0.35 * N)) / lever) / 1000.0
    m_pl = 0.5 * fp_max * (cant**2)  # N·mm / mm width
    fy_p = 250.0
    t_req = math.sqrt((4.0 * m_pl) / (0.90 * fy_p)) if m_pl > 0 else 8.0
    bearing_util = fp_max / fp_allow
    plate_util = (t_req / t_p) ** 2
    conn = {
        "column": col,
        "bearingStressMpa": round(fp_max, 2),
        "allowableBearingMpa": round(fp_allow, 2),
        "requiredPlateMm": round(t_req, 1),
        "anchorTensionKn": round(anchor_tension_kn, 1),
        "utilisation": round(max(bearing_util, plate_util), 3),
        "ok": bearing_util <= 1.0 and t_p >= t_req,
    }
    path = write_bim_json(ctx, "base-connection.json", conn)
    return result(
        summary={**conn, "exportPath": path},
        tables=[
            table(
                "Column baseplate check",
                [
                    ("check", "Check Item"),
                    ("demand", "Demand"),
                    ("capacity", "Limit"),
                    ("status", "Status"),
                ],
                [
                    {
                        "check": "Concrete bearing stress [MPa]",
                        "demand": round(fp_max, 2),
                        "capacity": round(fp_allow, 2),
                        "status": "PASS" if bearing_util <= 1.0 else "ENLARGE PLATE",
                    },
                    {
                        "check": "Plate bending thickness [mm]",
                        "demand": round(t_req, 1),
                        "capacity": t_p,
                        "status": "PASS" if t_p >= t_req else "THICKEN PLATE",
                    },
                    {
                        "check": "Tension side anchors [kN]",
                        "demand": round(anchor_tension_kn, 1),
                        "capacity": "See anchors",
                        "status": "CHECK" if anchor_tension_kn > 0 else "NO UPLIFT",
                    },
                ],
            )
        ],
        notes=[
            f"Computes cantilever m={m_cant:.0f} mm, n={n_cant:.0f} mm, bearing fp_max and required plate t={t_req:.1f} mm; saved to {path}."
        ],
    )


@feature(
    "bimAdditionsConnections.spliceConnection",
    "Splice Connection",
    part="bim",
    fields=[
        text("member", "Column / Beam ID", "C1"),
        number("axial", "Factored axial force N_u", 300.0, unit="kN", min=1.0),
        number("height", "Splice elevation above base", 3200.0, unit="mm", min=1.0),
        number("plateWidthMm", "Flange splice plate width", 220.0, unit="mm", min=80.0),
        number("plateThickMm", "Flange splice plate thickness", 12.0, unit="mm", min=6.0),
    ],
)
def splice_connection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check steel column/beam bolted flange splice bolts & plate yield across real model height."""
    import math

    data = require_bim(ctx)
    mem = _check_member_exists(data, values["member"])
    nu_n = float(values["axial"]) * 1000.0
    per_flange_n = 0.5 * nu_n
    with in_force(ctx.root):
        v_bolt = sc.bolt_shear_capacity("8.8", 20.0, planes=1)
    bolts_per_side = max(2, math.ceil(per_flange_n / v_bolt))
    plate_cap_n = 0.90 * 250.0 * float(values["plateWidthMm"]) * float(values["plateThickMm"])
    util = max(per_flange_n / (bolts_per_side * v_bolt), per_flange_n / plate_cap_n)
    conn = {
        "member": mem,
        "axialKn": float(values["axial"]),
        "heightMm": float(values["height"]),
        "boltsPerFlangePerSide": bolts_per_side,
        "utilisation": round(util, 3),
        "ok": util <= 1.0,
    }
    path = write_bim_json(ctx, "splice-connection.json", conn)
    return result(
        summary={**conn, "exportPath": path},
        tables=[
            table(
                "Splice connection sizing",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Per-flange force share (50%)",
                        "value": round(per_flange_n / 1000.0, 1),
                        "unit": "kN",
                    },
                    {
                        "item": "8.8 M20 bolts / flange / side",
                        "value": bolts_per_side,
                        "unit": "ea",
                    },
                    {
                        "item": "Flange plate gross yield cap",
                        "value": round(plate_cap_n / 1000.0, 1),
                        "unit": "kN",
                    },
                    {"item": "Governing utilisation", "value": round(util, 3), "unit": "-"},
                ],
            )
        ],
        notes=[
            f"Locate splice 600-1200 mm above finished floor level away from column plastic hinge; saved to {path}."
        ],
    )


@feature(
    "bimAdditionsConnections.basePlate",
    "Base Plate",
    part="bim",
    fields=[
        number("length", "Plate length", 500, unit="mm", min=20),
        number("width", "Plate width", 500, unit="mm", min=20),
        number("thickness", "Plate thickness", 25, unit="mm", min=3),
    ],
)
def base_plate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a rectangular column base plate."""
    require_bim(ctx)
    area = values["length"] * values["width"] / 1e6
    volume = area * values["thickness"] / 1000
    plate = {
        "lengthMm": values["length"],
        "widthMm": values["width"],
        "thicknessMm": values["thickness"],
        "areaM2": area,
        "volumeM3": volume,
    }
    path = write_bim_json(ctx, "base-plate.json", plate)
    return result(
        summary={**plate, "exportPath": path},
        tables=[
            table(
                "Base Plate",
                [
                    ("lengthMm", "Length [mm]", "mm"),
                    ("widthMm", "Width [mm]", "mm"),
                    ("thicknessMm", "Thickness [mm]", "mm"),
                    ("areaM2", "Area [m²]", "m²"),
                ],
                [plate],
            )
        ],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsConnections.gussetPlate",
    "Gusset Plate",
    part="bim",
    fields=[
        number("width", "Gusset width", 300, unit="mm", min=20),
        number("height", "Gusset height", 300, unit="mm", min=20),
        number("thickness", "Plate thickness", 12, unit="mm", min=3),
    ],
)
def gusset_plate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a triangular gusset plate estimate."""
    require_bim(ctx)
    area = 0.5 * values["width"] * values["height"] / 1e6
    plate = {
        "widthMm": values["width"],
        "heightMm": values["height"],
        "thicknessMm": values["thickness"],
        "areaM2": area,
    }
    path = write_bim_json(ctx, "gusset-plate.json", plate)
    return result(
        summary={**plate, "exportPath": path},
        notes=["Triangular area assumes perpendicular legs.", f"Export: {path}"],
    )


@feature(
    "bimAdditionsConnections.stiffenerPlate",
    "Stiffener Plate",
    part="bim",
    fields=[
        number("length", "Stiffener clear height h_s", 300.0, unit="mm", min=20.0),
        number("width", "Outstand width b_s", 100.0, unit="mm", min=20.0),
        number("thickness", "Plate thickness t_s", 10.0, unit="mm", min=3.0),
        number("fyMpa", "Plate yield fy", 250.0, unit="MPa", min=150.0),
    ],
)
def stiffenerPlate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check web stiffener plate outstand slenderness b/t and bearing capacity."""
    import math

    require_bim(ctx)
    b = float(values["width"])
    t = float(values["thickness"])
    fy = float(values["fyMpa"])
    slenderness = b / t
    lim = 0.56 * math.sqrt(200000.0 / fy)
    bearing_cap_kn = 0.75 * 1.8 * fy * (max(0.0, b - 15.0) * t) / 1000.0
    plate = {
        "lengthMm": float(values["length"]),
        "widthMm": b,
        "thicknessMm": t,
        "slendernessRatio": round(slenderness, 2),
        "compactLimit": round(lim, 2),
        "bearingCapacityKn": round(bearing_cap_kn, 1),
        "compact": slenderness <= lim,
    }
    path = write_bim_json(ctx, "stiffener-plate.json", plate)
    return result(
        summary={**plate, "exportPath": path},
        notes=[f"Checked b/t={slenderness:.1f} <= {lim:.1f}; saved to {path}."],
    )


@feature(
    "bimAdditionsConnections.cleatPlate",
    "Cleat Plate",
    part="bim",
    fields=[
        number("length", "Cleat vertical height L", 180.0, unit="mm", min=40.0),
        number("width", "Cleat outstand leg width", 100.0, unit="mm", min=40.0),
        number("thickness", "Cleat thickness t", 10.0, unit="mm", min=4.0),
        number("boltCount", "Vertical bolt rows", 2, min=1, max=12),
    ],
)
def cleat_plate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check web cleat angle/plate gross & net shear capacity with code-pack bolt shear."""
    require_bim(ctx)
    L = float(values["length"])
    t = float(values["thickness"])
    n = int(values["boltCount"])
    with in_force(ctx.root):
        dh = sc.net_hole(20.0)
        v_bolt = sc.bolt_shear_capacity("8.8", 20.0, planes=1)
    net_area = max(0.0, L - n * dh) * t
    shear_yield_kn = 0.90 * 0.60 * 250.0 * (L * t) / 1000.0
    shear_rupture_kn = 0.75 * 0.60 * 400.0 * net_area / 1000.0
    bolt_cap_kn = n * v_bolt / 1000.0
    gov_kn = min(shear_yield_kn, shear_rupture_kn, bolt_cap_kn)
    plate = {
        "lengthMm": L,
        "widthMm": float(values["width"]),
        "thicknessMm": t,
        "boltGroupKn": round(bolt_cap_kn, 1),
        "plateYieldKn": round(shear_yield_kn, 1),
        "plateRuptureKn": round(shear_rupture_kn, 1),
        "governingCapacityKn": round(gov_kn, 1),
    }
    path = write_bim_json(ctx, "cleat-plate.json", plate)
    return result(
        summary={**plate, "exportPath": path},
        notes=[
            f"Governing shear cap={gov_kn:.1f} kN (min of yield/rupture/bolts); saved to {path}."
        ],
    )


@feature(
    "bimAdditionsConnections.boltLayout",
    "Bolt Layout",
    part="bim",
    fields=[
        number("rows", "Bolt rows", 2, unit="ea", min=1),
        number("cols", "Bolt columns", 2, unit="ea", min=1),
        number("pitch", "Bolt pitch", 75, unit="mm", min=10),
        number("edge", "Edge distance", 40, unit="mm", min=5),
    ],
)
def bolt_layout(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a rectangular bolt layout."""
    require_bim(ctx)
    rows = int(values["rows"])
    cols = int(values["cols"])
    layout = [
        {
            "row": r + 1,
            "col": c + 1,
            "xMm": values["edge"] + c * values["pitch"],
            "yMm": values["edge"] + r * values["pitch"],
        }
        for r in range(rows)
        for c in range(cols)
    ]
    path = write_bim_csv(ctx, "bolt-layout.csv", ["row", "col", "xMm", "yMm"], layout)
    return result(
        summary={
            "boltCount": len(layout),
            "pitchMm": values["pitch"],
            "edgeDistanceMm": values["edge"],
            "exportPath": path,
        },
        tables=[
            table(
                "Bolt Layout",
                [
                    ("row", "Row"),
                    ("col", "Column"),
                    ("xMm", "X [mm]", "mm"),
                    ("yMm", "Y [mm]", "mm"),
                ],
                layout,
            )
        ],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsConnections.weldSymbol",
    "Weld Symbol",
    part="bim",
    fields=[
        select(
            "weld",
            "Weld type",
            [("fillet", "Fillet"), ("butt", "Complete-joint penetration butt"), ("plug", "Plug")],
            "fillet",
        ),
        number("size", "Weld leg / throat size", 8.0, unit="mm", min=2.0),
        number("length", "Effective weld length", 200.0, unit="mm", min=20.0),
        number("electrodeFexxMpa", "Electrode tensile strength FEXX", 480.0, unit="MPa", min=400.0),
    ],
)
def weld_symbol(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute weld design resistance per mm and total capacity via saengine.design.steel_connections."""
    require_bim(ctx)
    w = float(values["size"])
    L = float(values["length"])
    fexx = float(values["electrodeFexxMpa"])
    if values["weld"] == "fillet":
        with in_force(ctx.root):
            cap_per_mm = sc.fillet_capacity_per_mm(w, fexx)
        throat = 0.707 * w
    elif values["weld"] == "butt":
        throat = w
        cap_per_mm = 0.90 * 250.0 * w
    else:
        throat = w
        cap_per_mm = 0.75 * 0.60 * fexx * w
    total_kn = (cap_per_mm * L) / 1000.0
    weld = {
        "type": values["weld"],
        "sizeMm": w,
        "throatMm": round(throat, 2),
        "lengthMm": L,
        "capacityKnPerMm": round(cap_per_mm / 1000.0, 3),
        "totalDesignCapacityKn": round(total_kn, 1),
    }
    path = write_bim_json(ctx, "weld-symbol.json", weld)
    return result(
        summary={**weld, "exportPath": path},
        notes=[
            f"Design weld capacity = {total_kn:.1f} kN ({cap_per_mm / 1000.0:.3f} kN/mm); saved to {path}."
        ],
    )


@feature(
    "bimAdditionsConnections.holePattern",
    "Hole Pattern",
    part="bim",
    fields=[
        number("diameter", "Hole diameter", 22, unit="mm", min=2),
        number("countX", "X count", 3, unit="ea", min=1),
        number("countY", "Y count", 2, unit="ea", min=1),
        number("pitch", "Pitch", 75, unit="mm", min=5),
    ],
)
def hole_pattern(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a rectangular hole pattern."""
    require_bim(ctx)
    nx = int(values["countX"])
    ny = int(values["countY"])
    holes = [
        {
            "hole": i * ny + j + 1,
            "xMm": i * values["pitch"],
            "yMm": j * values["pitch"],
            "diameterMm": values["diameter"],
        }
        for i in range(nx)
        for j in range(ny)
    ]
    path = write_bim_csv(ctx, "hole-pattern.csv", ["hole", "xMm", "yMm", "diameterMm"], holes)
    return result(
        summary={
            "holeCount": len(holes),
            "holeDiameterMm": values["diameter"],
            "pitchMm": values["pitch"],
            "exportPath": path,
        },
        tables=[
            table(
                "Hole Pattern",
                [
                    ("hole", "Hole"),
                    ("xMm", "X [mm]", "mm"),
                    ("yMm", "Y [mm]", "mm"),
                    ("diameterMm", "Diameter [mm]", "mm"),
                ],
                holes,
            )
        ],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsConnections.edgeDistance",
    "Edge Distance",
    part="bim",
    fields=[
        number("provided", "Provided edge distance", 40, unit="mm", min=0),
        number("minimum", "Minimum edge distance", 30, unit="mm", min=0),
    ],
)
def edge_distance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Checks edge distance against a supplied minimum."""
    require_bim(ctx)
    passes = values["provided"] >= values["minimum"]
    return result(
        summary={
            "providedMm": values["provided"],
            "minimumMm": values["minimum"],
            "reserveMm": values["provided"] - values["minimum"],
            "passes": passes,
        }
    )


@feature(
    "bimAdditionsConnections.seatAngle",
    "Seat Angle",
    part="bim",
    fields=[
        number("length", "Seat angle width", 150.0, unit="mm", min=50.0),
        number("leg", "Horizontal outstanding leg", 100.0, unit="mm", min=50.0),
        number("thickness", "Angle leg thickness", 12.0, unit="mm", min=6.0),
        number("reactionKn", "Factored beam end reaction", 65.0, unit="kN", min=1.0),
    ],
)
def seat_angle(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check unstiffened seated-beam angle bending thickness and bolt shear demand."""
    import math

    require_bim(ctx)
    L = float(values["length"])
    t = float(values["thickness"])
    ru_n = float(values["reactionKn"]) * 1000.0
    ecc = 0.5 * float(values["leg"]) - 12.0 - t  # approximate bearing centroid ecc to root
    m_leg = ru_n * max(15.0, ecc)
    t_req = math.sqrt((4.0 * m_leg) / (0.90 * 250.0 * L))
    util = (t_req / t) ** 2
    angle = {
        "lengthMm": L,
        "legMm": float(values["leg"]),
        "thicknessMm": t,
        "requiredThickMm": round(t_req, 1),
        "bendingUtilisation": round(util, 3),
        "ok": t >= t_req,
    }
    path = write_bim_json(ctx, "seat-angle.json", angle)
    return result(
        summary={**angle, "exportPath": path},
        notes=[f"Unstiffened seat leg bending req t={t_req:.1f} mm vs {t:g} mm; saved to {path}."],
    )


@feature(
    "bimAdditionsConnections.clipAngle",
    "Clip Angle",
    part="bim",
    fields=[
        number("length", "Clip length", 220.0, unit="mm", min=60.0),
        number("legA", "Web leg A", 90.0, unit="mm", min=40.0),
        number("legB", "Support leg B", 90.0, unit="mm", min=40.0),
        number("thickness", "Angle thickness", 8.0, unit="mm", min=4.0),
        number("boltsPerLeg", "Bolts per leg row", 3, min=1, max=10),
    ],
)
def clip_angle(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check web framing clip angle net shear & bolt group resistance."""
    require_bim(ctx)
    L = float(values["length"])
    t = float(values["thickness"])
    n = int(values["boltsPerLeg"])
    with in_force(ctx.root):
        dh = sc.net_hole(20.0)
        min_e = sc.min_edge(20.0)
        v_bolt = sc.bolt_shear_capacity("8.8", 20.0, planes=2)
    net_shear_kn = 0.75 * 0.60 * 400.0 * max(0.0, L - n * dh) * (2.0 * t) / 1000.0
    bolt_cap_kn = n * v_bolt / 1000.0
    cap_kn = min(net_shear_kn, bolt_cap_kn)
    angle = {
        "lengthMm": L,
        "legAMm": float(values["legA"]),
        "legBMm": float(values["legB"]),
        "thicknessMm": t,
        "minEdgeMm": round(min_e, 1),
        "doubleClipCapacityKn": round(cap_kn, 1),
    }
    path = write_bim_json(ctx, "clip-angle.json", angle)
    return result(
        summary={**angle, "exportPath": path},
        notes=[
            f"Double clip angle capacity={cap_kn:.1f} kN; min edge={min_e:.1f} mm; saved to {path}."
        ],
    )


@feature(
    "bimAdditionsConnections.flangeStiffener",
    "Flange Stiffener",
    part="bim",
    fields=[
        number("width", "Continuity plate width", 150.0, unit="mm", min=50.0),
        number("length", "Column web depth length", 300.0, unit="mm", min=80.0),
        number("thickness", "Stiffener thickness", 12.0, unit="mm", min=6.0),
        number("beamFlangeThickMm", "Connected beam flange thickness", 16.0, unit="mm", min=5.0),
    ],
)
def flange_stiffener(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check column transverse continuity plate thickness vs beam flange and axial squash capacity."""
    require_bim(ctx)
    t_s = float(values["thickness"])
    t_bf = float(values["beamFlangeThickMm"])
    min_t_interior = t_bf
    area_mm2 = float(values["width"]) * t_s
    cap_kn = 0.90 * 250.0 * area_mm2 / 1000.0
    ok = t_s >= min_t_interior
    plate = {
        "widthMm": float(values["width"]),
        "lengthMm": float(values["length"]),
        "thicknessMm": t_s,
        "minReqThickMm": min_t_interior,
        "axialCapacityKn": round(cap_kn, 1),
        "ok": ok,
    }
    path = write_bim_json(ctx, "flange-stiffener.json", plate)
    return result(
        summary={**plate, "exportPath": path},
        notes=[f"Continuity plate capacity={cap_kn:.1f} kN (t >= beam tf); saved to {path}."],
    )


@feature(
    "bimAdditionsConnections.anchorRods",
    "Anchor Rods",
    part="bim",
    fields=[
        number("diameter", "Anchor rod diameter", 24.0, unit="mm", min=10.0),
        number("count", "Total anchor rod count", 4, unit="ea", min=2),
        number("embedment", "Effective embedment hef", 300.0, unit="mm", min=50.0),
        number("fcMpa", "Pedestal concrete f'c", 28.0, unit="MPa", min=15.0),
    ],
)
def anchor_rods(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute anchor rod steel tensile yield/rupture and concrete cone breakout capacities."""
    import math

    require_bim(ctx)
    d = float(values["diameter"])
    n = int(values["count"])
    hef = float(values["embedment"])
    fc = float(values["fcMpa"])
    ab = math.pi * (d / 2.0) ** 2
    t_steel_one_kn = 0.75 * 400.0 * (0.78 * ab) / 1000.0
    # Concrete breakout single anchor Nb = 16.8 * sqrt(fc) * hef^1.5 [N]
    t_cone_one_kn = 0.65 * (16.8 * math.sqrt(fc) * (hef**1.5)) / 1000.0
    gov_one = min(t_steel_one_kn, t_cone_one_kn)
    rows = [
        {
            "rod": i + 1,
            "diameterMm": d,
            "embedmentMm": hef,
            "steelKn": round(t_steel_one_kn, 1),
            "breakoutKn": round(t_cone_one_kn, 1),
        }
        for i in range(n)
    ]
    path = write_bim_csv(
        ctx, "anchor-rods.csv", ["rod", "diameterMm", "embedmentMm", "steelKn", "breakoutKn"], rows
    )
    return result(
        summary={
            "rodCount": n,
            "singleSteelKn": round(t_steel_one_kn, 1),
            "singleConeKn": round(t_cone_one_kn, 1),
            "groupUpperBoundKn": round(n * gov_one, 1),
            "exportPath": path,
        },
        tables=[
            table(
                "Anchor rod capacity schedule",
                [
                    ("rod", "Rod"),
                    ("diameterMm", "Dia", "mm"),
                    ("embedmentMm", "hef", "mm"),
                    ("steelKn", "Steel φNt", "kN"),
                    ("breakoutKn", "Cone φNb", "kN"),
                ],
                rows,
            )
        ],
        notes=[
            f"Steel rupture vs individual cone breakout at hef={hef:g} mm; reduce cone for close edge/spacing overlap. Saved to {path}."
        ],
    )


@feature(
    "bimAdditionsConnections.embedPlate",
    "Embed Plate",
    part="bim",
    fields=[
        number("length", "Plate length", 300.0, unit="mm", min=60.0),
        number("width", "Plate width", 300.0, unit="mm", min=60.0),
        number("thickness", "Plate thickness", 16.0, unit="mm", min=6.0),
        number("studCount", "Headed shear studs welded", 4, min=2, max=24),
        number("studDiameterMm", "Headed stud diameter", 19.0, unit="mm", min=10.0),
    ],
)
def embed_plate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check cast-in steel embed plate minimum thickness ratio and headed stud shear capacity."""
    import math

    require_bim(ctx)
    d_stud = float(values["studDiameterMm"])
    n_stud = int(values["studCount"])
    a_sa = math.pi * (d_stud / 2.0) ** 2
    v_stud_kn = 0.65 * (a_sa * 450.0) / 1000.0
    total_shear_kn = n_stud * v_stud_kn
    # Plate thickness recommended >= 0.5 * d_stud or 10 mm to mobilize stud neck yield
    min_t = max(10.0, 0.5 * d_stud)
    ok = float(values["thickness"]) >= min_t
    plate = {
        "lengthMm": float(values["length"]),
        "widthMm": float(values["width"]),
        "thicknessMm": float(values["thickness"]),
        "minPlateThickMm": round(min_t, 1),
        "totalStudShearKn": round(total_shear_kn, 1),
        "ok": ok,
    }
    path = write_bim_json(ctx, "embed-plate.json", plate)
    return result(
        summary={**plate, "exportPath": path},
        notes=[
            f"Embed plate stud shear group cap={total_shear_kn:.1f} kN (min t={min_t:.0f} mm); saved to {path}."
        ],
    )


@feature(
    "bimAdditionsConnections.chemicalAnchor",
    "Chemical Anchor",
    part="bim",
    fields=[
        number("diameter", "Anchor diameter", 16, unit="mm", min=6),
        number("embedment", "Embedment length", 160, unit="mm", min=30),
        number("count", "Anchor count", 4, unit="ea", min=1),
    ],
)
def chemical_anchor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Schedules chemical anchors."""
    require_bim(ctx)
    count = int(values["count"])
    return result(
        summary={
            "anchorCount": count,
            "diameterMm": values["diameter"],
            "embedmentMm": values["embedment"],
        },
        notes=[
            "Anchor adhesive system and substrate strength must be supplied by the anchorage design."
        ],
    )


@feature(
    "bimAdditionsConnections.feaJointCheck",
    "FEA Joint Check",
    part="bim",
    fields=[
        number("axial", "Axial force", 500, unit="kN"),
        number("shear", "Shear force", 100, unit="kN"),
        number("moment", "Bending moment", 50, unit="kN·m"),
    ],
)
def fea_joint_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarises joint actions for a finite-element check."""
    require_bim(ctx)
    demand = (values["axial"] ** 2 + values["shear"] ** 2) ** 0.5
    return result(
        summary={
            "axialForceKn": values["axial"],
            "shearForceKn": values["shear"],
            "momentKnM": values["moment"],
            "combinedPlanarDemandKn": demand,
        },
        tables=[
            table(
                "Joint Demand",
                [
                    ("axialForceKn", "Axial [kN]", "kN"),
                    ("shearForceKn", "Shear [kN]", "kN"),
                    ("momentKnM", "Moment [kN·m]", "kN·m"),
                ],
                [
                    {
                        "axialForceKn": values["axial"],
                        "shearForceKn": values["shear"],
                        "momentKnM": values["moment"],
                    }
                ],
            )
        ],
        notes=[
            "Planar resultant is a report metric; resistance and failure surfaces require an FE model."
        ],
    )


@feature(
    "bimAdditionsConnections.weldCapacity",
    "Weld Capacity",
    part="bim",
    fields=[
        number("throat", "Effective throat", 6, unit="mm", min=1),
        number("length", "Weld length", 200, unit="mm", min=1),
        number("allowableStress", "Allowable stress", 150, unit="MPa", min=1),
    ],
)
def weld_capacity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculates an explicit-user-input weld capacity."""
    require_bim(ctx)
    area = values["throat"] * values["length"]
    capacity = area * values["allowableStress"] / 1000
    return result(
        summary={
            "effectiveAreaMm2": area,
            "allowableStressMpa": values["allowableStress"],
            "capacityKn": capacity,
        },
        notes=[
            "Capacity is area × supplied stress/1000; the stress input must reflect the applicable project rules and load combination."
        ],
    )


@feature(
    "bimAdditionsConnections.boltGroupCheck",
    "Bolt Group Check",
    part="bim",
    fields=[
        number("boltCount", "Bolt count", 4, unit="ea", min=1),
        number("individualCapacity", "Capacity per bolt", 50, unit="kN", min=0),
        number("appliedForce", "Applied force", 150, unit="kN", min=0),
    ],
)
def bolt_group_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Checks a simplified equal-bolt-group capacity."""
    require_bim(ctx)
    capacity = values["boltCount"] * values["individualCapacity"]
    utilization = values["appliedForce"] / capacity if capacity > 0 else 1e9
    return result(
        summary={
            "boltCount": int(values["boltCount"]),
            "capacityKn": capacity,
            "appliedForceKn": values["appliedForce"],
            "utilization": utilization,
            "passes": utilization <= 1,
        },
        notes=[
            "Equal distribution is assumed; eccentricity and bolt-row load distribution require a dedicated connection model."
        ],
    )

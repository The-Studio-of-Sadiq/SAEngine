"""Design Reinforcement - Connections tab: bolted/welded steel connections, base plates, anchors, and timber joints."""

from __future__ import annotations

import math
from typing import Any

from saengine.design import steel_connections
from saengine.design.timber import connections as timber_conn
from saengine.drawings import detailing
from saengine.features import (
    FeatureContext,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
)
from saengine.features.fem_common import concrete_rebar_defaults, export_fem_file, steel_defaults
from saengine.report.clauses import in_force


def _resolve_bolt_grade(grade: str) -> str:
    """Resolve bare bolt grade labels (e.g. A325, A490) to threads-included pack keys."""
    return {"A325": "A325N", "A490": "A490N"}.get(grade, grade)


@feature(
    "femDesignConnections.momentConnection",
    "Moment Connection",
    part="fem",
    fields=[
        number("momentKnm", "Factored beam moment Mu", 180.0, unit="kN·m", min=1.0),
        number("beamDepthMm", "Beam depth d", 400.0, unit="mm", min=100.0),
        number("plateThicknessMm", "Flange plate thickness tp", 16.0, unit="mm", min=6.0),
        number("plateWidthMm", "Flange plate width bp", 200.0, unit="mm", min=60.0),
    ],
    requires_project=False,
)
def moment_connection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute flange-plate moment couple force and check gross/net plate tension yielding."""
    fy, _fu = steel_defaults(ctx)
    lever = (values["beamDepthMm"] + values["plateThicknessMm"]) / 1000.0
    puf_kn = values["momentKnm"] / lever
    ag = values["plateWidthMm"] * values["plateThicknessMm"]
    phi_tn_yield = 0.90 * fy * ag / 1000.0
    rows = [
        {
            "flangeForceKn": puf_kn,
            "plateYieldCapKn": phi_tn_yield,
            "utilisation": puf_kn / phi_tn_yield,
            "ok": puf_kn <= phi_tn_yield,
        }
    ]
    return result(
        summary={
            "flangeForceKn": puf_kn,
            "plateCapacityKn": phi_tn_yield,
            "utilisation": puf_kn / phi_tn_yield,
            "ok": puf_kn <= phi_tn_yield,
        },
        tables=[
            table(
                "Bolted flange-plate moment connection",
                [
                    ("flangeForceKn", "Puf", "kN"),
                    ("plateYieldCapKn", "φTn", "kN"),
                    ("utilisation", "DCR"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Flange couple force Puf = Mu / (d + tp)."],
    )


@feature(
    "femDesignConnections.shearConnection",
    "Shear Connection",
    part="fem",
    fields=[
        number("shearKn", "Beam end shear Vu", 160.0, unit="kN", min=1.0),
        number("bolts", "Number of bolts", 4, min=2, max=16),
        number("boltDiameterMm", "Bolt diameter", 20.0, unit="mm", min=12.0, max=36.0),
        select(
            "boltGrade",
            "Bolt grade",
            [("8.8", "Grade 8.8"), ("10.9", "Grade 10.9"), ("A325", "A325")],
            "8.8",
        ),
    ],
    requires_project=False,
)
def shear_connection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check simple fin-plate / end-plate shear connection bolt group capacity."""
    with in_force(ctx.root):
        v_bolt = steel_connections.bolt_shear_capacity(
            _resolve_bolt_grade(values["boltGrade"]), values["boltDiameterMm"], planes=1
        )
    v_bolt_kn = v_bolt / 1000.0 if v_bolt > 500 else v_bolt
    cap_kn = v_bolt_kn * int(values["bolts"])
    dcr = values["shearKn"] / max(cap_kn, 1e-6)
    rows = [
        {
            "bolts": int(values["bolts"]),
            "perBoltKn": v_bolt_kn,
            "groupCapKn": cap_kn,
            "demandKn": values["shearKn"],
            "dcr": dcr,
            "ok": dcr <= 1.0,
        }
    ]
    return result(
        summary={"groupCapacityKn": cap_kn, "utilisation": dcr, "passes": dcr <= 1.0},
        tables=[
            table(
                "Shear connection bolt capacity",
                [
                    ("bolts", "Bolts"),
                    ("perBoltKn", "φRn/bolt", "kN"),
                    ("groupCapKn", "Total φRn", "kN"),
                    ("demandKn", "Vu", "kN"),
                    ("dcr", "DCR"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Computed via saengine.design.steel_connections.bolt_shear_capacity."],
    )


@feature(
    "femDesignConnections.spliceConnection",
    "Splice Connection",
    part="fem",
    fields=[
        number("axialKn", "Splice axial force Pu", 600.0, unit="kN"),
        number("momentKnm", "Splice moment Mu", 80.0, unit="kN·m"),
        number("sectionDepthMm", "Member depth d", 350.0, unit="mm", min=100.0),
        number(
            "flangePlateAreaMm2", "Single flange splice plate area", 2400.0, unit="mm²", min=100.0
        ),
    ],
    requires_project=False,
)
def splice_connection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check flange cover-plate axial + moment force transfer at a column or beam splice."""
    fy, _ = steel_defaults(ctx)
    p_flange = abs(values["axialKn"]) * 0.4 + abs(values["momentKnm"]) * 1000.0 / max(
        values["sectionDepthMm"] - 15.0, 50.0
    )
    cap_kn = 0.90 * fy * values["flangePlateAreaMm2"] / 1000.0
    dcr = p_flange / cap_kn
    rows = [{"flangeDemandKn": p_flange, "plateCapKn": cap_kn, "dcr": dcr, "ok": dcr <= 1.0}]
    return result(
        summary={
            "flangeDemandKn": p_flange,
            "plateCapacityKn": cap_kn,
            "utilisation": dcr,
            "passes": dcr <= 1.0,
        },
        tables=[
            table(
                "Cover-plate splice check",
                [
                    ("flangeDemandKn", "Demand", "kN"),
                    ("plateCapKn", "φTn", "kN"),
                    ("dcr", "DCR"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Flange splice carries bending couple plus tributary axial load share."],
    )


@feature(
    "femDesignConnections.basePlate",
    "Base Plate",
    part="fem",
    fields=[
        number("axialKn", "Factored compression Pu", 950.0, unit="kN", min=1.0),
        number("plateLengthMm", "Base plate length N", 450.0, unit="mm", min=150.0),
        number("plateWidthMm", "Base plate width B", 450.0, unit="mm", min=150.0),
        number("pedestalAreaRatio", "Confinement ratio √(A2/A1)", 1.5, min=1.0, max=2.0),
    ],
    requires_project=False,
)
def base_plate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check column base plate concrete bearing strength φc·Pp and required plate thickness."""
    fc, _ = concrete_rebar_defaults(ctx)
    fy, _ = steel_defaults(ctx)
    a1 = values["plateLengthMm"] * values["plateWidthMm"]
    pp_kn = min(0.85 * fc * a1 * values["pedestalAreaRatio"], 1.7 * fc * a1) / 1000.0
    phi_pp = 0.65 * pp_kn
    q_mpa = (values["axialKn"] * 1000.0) / a1
    cant_m = 0.25 * values["plateLengthMm"]
    tp_req = cant_m * math.sqrt(2.0 * q_mpa / (0.90 * fy))
    rows = [
        {
            "bearingDemandKn": values["axialKn"],
            "bearingCapKn": phi_pp,
            "dcr": values["axialKn"] / phi_pp,
            "reqThicknessMm": tp_req,
        }
    ]
    return result(
        summary={
            "bearingCapacityKn": phi_pp,
            "utilisation": values["axialKn"] / phi_pp,
            "requiredThicknessMm": tp_req,
        },
        tables=[
            table(
                "Column base plate bearing & thickness",
                [
                    ("bearingDemandKn", "Pu", "kN"),
                    ("bearingCapKn", "φc Pp", "kN"),
                    ("dcr", "DCR"),
                    ("reqThicknessMm", "t_req", "mm"),
                ],
                rows,
            )
        ],
        notes=[
            "Evaluates concrete bearing confinement √(A2/A1) <= 2.0 and cantilever plate flexure."
        ],
    )


@feature(
    "femDesignConnections.boltCheck",
    "Bolt Check",
    part="fem",
    fields=[
        select(
            "grade",
            "Bolt grade",
            [("8.8", "8.8"), ("10.9", "10.9"), ("A325", "A325"), ("A490", "A490")],
            "8.8",
        ),
        number("diameterMm", "Bolt diameter", 20.0, unit="mm", min=10.0, max=36.0),
        number("shearDemandKn", "Factored bolt shear Vu", 45.0, unit="kN", min=0.0),
        number("tensionDemandKn", "Factored bolt tension Tu", 35.0, unit="kN", min=0.0),
    ],
    requires_project=False,
)
def bolt_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check single-bolt shear, tension, and elliptical shear-tension interaction."""
    grade = _resolve_bolt_grade(values["grade"])
    with in_force(ctx.root):
        vs = steel_connections.bolt_shear_capacity(grade, values["diameterMm"], planes=1)
        vt, _ = steel_connections.bolt_tension_capacity(grade, values["diameterMm"])
    vs_kn = vs / 1000.0 if vs > 500 else vs
    vt_kn = vt / 1000.0 if vt > 500 else vt
    rv, rt = (
        values["shearDemandKn"] / max(vs_kn, 1e-6),
        values["tensionDemandKn"] / max(vt_kn, 1e-6),
    )
    inter = rv**2 + rt**2
    rows = [
        {"check": "Shear", "demandKn": values["shearDemandKn"], "capKn": vs_kn, "dcr": rv},
        {"check": "Tension", "demandKn": values["tensionDemandKn"], "capKn": vt_kn, "dcr": rt},
        {"check": "Combined (V/φRv)² + (T/φRt)²", "demandKn": inter, "capKn": 1.0, "dcr": inter},
    ]
    return result(
        summary={
            "boltShearCapKn": vs_kn,
            "boltTensionCapKn": vt_kn,
            "interactionRatio": inter,
            "passes": inter <= 1.0,
        },
        tables=[
            table(
                "Bolt shear-tension interaction check",
                [
                    ("check", "Check"),
                    ("demandKn", "Demand"),
                    ("capKn", "Capacity"),
                    ("dcr", "Ratio"),
                ],
                rows,
            )
        ],
        notes=["Evaluated via saengine.design.steel_connections."],
    )


@feature(
    "femDesignConnections.weldCheck",
    "Weld Check",
    part="fem",
    fields=[
        number("legSizeMm", "Fillet weld leg size w", 6.0, unit="mm", min=3.0, max=25.0),
        number("electrodeFexxMpa", "Electrode tensile strength FEXX", 480.0, unit="MPa", min=350.0),
        number("weldLengthMm", "Effective weld length Lw", 250.0, unit="mm", min=20.0),
        number("appliedForceKn", "Factored force on weld", 180.0, unit="kN", min=0.0),
    ],
    requires_project=False,
)
def weld_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify fillet weld throat shear capacity against applied joint force."""
    with in_force(ctx.root):
        fw_per_mm = steel_connections.fillet_capacity_per_mm(
            values["legSizeMm"], values["electrodeFexxMpa"]
        )
    fw_kn_mm = fw_per_mm / 1000.0 if fw_per_mm > 100 else fw_per_mm
    cap_kn = fw_kn_mm * values["weldLengthMm"]
    dcr = values["appliedForceKn"] / max(cap_kn, 1e-6)
    rows = [
        {
            "legMm": values["legSizeMm"],
            "throatMm": 0.707 * values["legSizeMm"],
            "capPerMmKn": fw_kn_mm,
            "totalCapKn": cap_kn,
            "dcr": dcr,
            "ok": dcr <= 1.0,
        }
    ]
    return result(
        summary={
            "capacityKnPerMm": fw_kn_mm,
            "totalCapacityKn": cap_kn,
            "utilisation": dcr,
            "passes": dcr <= 1.0,
        },
        tables=[
            table(
                "Fillet weld throat resistance",
                [
                    ("legMm", "Leg", "mm"),
                    ("throatMm", "Throat", "mm"),
                    ("capPerMmKn", "φRn/mm", "kN/mm"),
                    ("totalCapKn", "Total φRn", "kN"),
                    ("dcr", "DCR"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Effective throat te = 0.707 · w for equal-leg fillet welds."],
    )


@feature(
    "femDesignConnections.plateBearing",
    "Plate Bearing",
    part="fem",
    fields=[
        number("boltDiameterMm", "Bolt diameter d", 20.0, unit="mm", min=10.0),
        number("plateThicknessMm", "Plate thickness t", 10.0, unit="mm", min=4.0),
        number("clearEdgeMm", "Clear edge distance lc", 28.0, unit="mm", min=10.0),
        number("boltShearKn", "Bolt bearing demand", 55.0, unit="kN", min=0.0),
    ],
    requires_project=False,
)
def plate_bearing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check bolt hole bearing and tear-out capacity in connected steel plates."""
    _, fu = steel_defaults(ctx)
    with in_force(ctx.root):
        cap = steel_connections.bearing_capacity(
            values["boltDiameterMm"], values["plateThicknessMm"], fu, values["clearEdgeMm"]
        )
    cap_kn = cap / 1000.0 if cap > 500 else cap
    dcr = values["boltShearKn"] / max(cap_kn, 1e-6)
    rows = [
        {
            "clearDistMm": values["clearEdgeMm"],
            "bearingCapKn": cap_kn,
            "demandKn": values["boltShearKn"],
            "dcr": dcr,
            "ok": dcr <= 1.0,
        }
    ]
    return result(
        summary={"bearingCapacityKn": cap_kn, "utilisation": dcr, "passes": dcr <= 1.0},
        tables=[
            table(
                "Plate hole bearing & tear-out check",
                [
                    ("clearDistMm", "lc", "mm"),
                    ("bearingCapKn", "φRn", "kN"),
                    ("demandKn", "Demand", "kN"),
                    ("dcr", "DCR"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Computed via saengine.design.steel_connections.bearing_capacity."],
    )


@feature(
    "femDesignConnections.connectionReport",
    "Connection Report",
    part="fem",
    fields=[
        number("boltDiaMm", "Reference bolt diameter", 20.0, unit="mm", min=12.0),
        number("weldMm", "Reference fillet weld", 6.0, unit="mm", min=3.0),
    ],
    requires_project=True,
)
def connection_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Issue a Markdown calculation summary sheet for standard bolt and weld connection capacities."""
    with in_force(ctx.root):
        vb = steel_connections.bolt_shear_capacity("8.8", values["boltDiaMm"], planes=1)
        tb, _ = steel_connections.bolt_tension_capacity("8.8", values["boltDiaMm"])
        fw = steel_connections.fillet_capacity_per_mm(values["weldMm"], 480.0)
    vb_kn = vb / 1000.0 if vb > 500 else vb
    tb_kn = tb / 1000.0 if tb > 500 else tb
    fw_kn = fw / 1000.0 if fw > 100 else fw
    md = f"# Steel Connection Capacity Report\n\n- Bolt M{values['boltDiaMm']:g} (8.8) Shear: {vb_kn:.2f} kN\n- Bolt Tension: {tb_kn:.2f} kN\n- Fillet Weld {values['weldMm']:g} mm: {fw_kn:.3f} kN/mm\n"
    path = export_fem_file(ctx, "connection-report.md", md)
    rows = [
        {"item": "Bolt Shear", "val": vb_kn, "unit": "kN"},
        {"item": "Bolt Tension", "val": tb_kn, "unit": "kN"},
        {"item": "Weld Capacity", "val": fw_kn, "unit": "kN/mm"},
    ]
    return result(
        summary={"boltShearKn": vb_kn, "boltTensionKn": tb_kn, "reportPath": str(path)},
        tables=[
            table(
                "Connection capacity summary",
                [("item", "Component"), ("val", "Capacity"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[f"Connection report written to {path}"],
    )


@feature(
    "femDesignConnections.edgeDistance",
    "Edge Distance",
    part="fem",
    fields=[
        number("boltDiameterMm", "Bolt diameter d", 20.0, unit="mm", min=10.0),
        number("plateThicknessMm", "Thinner connected plate t", 10.0, unit="mm", min=4.0),
        number("providedEdgeMm", "Provided edge distance e", 35.0, unit="mm", min=10.0),
    ],
    requires_project=False,
)
def edge_distance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify bolt edge and end distances against code minimum and maximum limits."""
    with in_force(ctx.root):
        e_min = steel_connections.min_edge(values["boltDiameterMm"])
    e_max = min(12.0 * values["plateThicknessMm"], 150.0)
    ok = e_min <= values["providedEdgeMm"] <= e_max
    rows = [
        {"minEdgeMm": e_min, "providedMm": values["providedEdgeMm"], "maxEdgeMm": e_max, "ok": ok}
    ]
    return result(
        summary={"minEdgeMm": e_min, "maxEdgeMm": e_max, "passes": ok},
        tables=[
            table(
                "Bolt edge distance check",
                [
                    ("minEdgeMm", "Min", "mm"),
                    ("providedMm", "Provided", "mm"),
                    ("maxEdgeMm", "Max", "mm"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Prevents hole edge tear-out (min) and moisture-ingress prying corrosion (max)."],
    )


@feature(
    "femDesignConnections.holeLayout",
    "Hole Layout",
    part="fem",
    fields=[
        number("boltDiameterMm", "Bolt diameter d", 20.0, unit="mm", min=10.0),
        number("rows", "Bolt rows", 4, min=1, max=12),
        number("columns", "Bolt lines", 2, min=1, max=6),
        number("pitchMm", "Vertical pitch p", 70.0, unit="mm", min=30.0),
    ],
    requires_project=False,
)
def hole_layout(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Lay out bolt grid coordinates with minimum spacing and edge checks."""
    with in_force(ctx.root):
        s_min = steel_connections.min_spacing(values["boltDiameterMm"])
        e_min = steel_connections.min_edge(values["boltDiameterMm"])
    plate_h = 2.0 * e_min + (int(values["rows"]) - 1) * values["pitchMm"]
    plate_w = 2.0 * e_min + (int(values["columns"]) - 1) * values["pitchMm"]
    rows = [
        {
            "minSpacingMm": s_min,
            "minEdgeMm": e_min,
            "plateHeightMm": plate_h,
            "plateWidthMm": plate_w,
            "spacingOk": values["pitchMm"] >= s_min,
        }
    ]
    return result(
        summary={
            "minPlateHeightMm": plate_h,
            "minPlateWidthMm": plate_w,
            "spacingOk": values["pitchMm"] >= s_min,
        },
        tables=[
            table(
                "Bolt hole grid layout",
                [
                    ("minSpacingMm", "Min Pitch", "mm"),
                    ("minEdgeMm", "Min Edge", "mm"),
                    ("plateHeightMm", "Plate H", "mm"),
                    ("plateWidthMm", "Plate W", "mm"),
                    ("spacingOk", "OK"),
                ],
                rows,
            )
        ],
        notes=["Minimum pitch and edge distances evaluated via saengine.design.steel_connections."],
    )


@feature(
    "femDesignConnections.stiffenerDesign",
    "Stiffener Design",
    part="fem",
    fields=[
        number("flangeForceKn", "Concentrated flange force Puf", 420.0, unit="kN", min=1.0),
        number("columnWebCapKn", "Unstiffened column web capacity", 290.0, unit="kN", min=1.0),
        number("stiffenerWidthMm", "Single stiffener outstand bs", 90.0, unit="mm", min=40.0),
    ],
    requires_project=False,
)
def stiffener_design(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size transverse continuity stiffener plates where column web capacity is exceeded."""
    fy, _ = steel_defaults(ctx)
    excess_kn = max(0.0, values["flangeForceKn"] - values["columnWebCapKn"])
    area_req = (excess_kn * 1000.0) / (0.90 * fy)
    t_req = area_req / (2.0 * values["stiffenerWidthMm"]) if excess_kn > 0 else 0.0
    rows = [
        {
            "excessForceKn": excess_kn,
            "requiredAreaMm2": area_req,
            "minThicknessMm": max(t_req, 10.0) if excess_kn > 0 else 0.0,
        }
    ]
    return result(
        summary={
            "stiffenersRequired": excess_kn > 0,
            "excessForceKn": excess_kn,
            "minThicknessMm": rows[0]["minThicknessMm"],
        },
        tables=[
            table(
                "Transverse continuity stiffener sizing",
                [
                    ("excessForceKn", "Excess Force", "kN"),
                    ("requiredAreaMm2", "Req Area", "mm²"),
                    ("minThicknessMm", "Min t_s", "mm"),
                ],
                rows,
            )
        ],
        notes=[
            "Pair of transverse stiffeners carries flange force exceeding column web local yielding/crippling."
        ],
    )


@feature(
    "femDesignConnections.connectionSchedule",
    "Connection Schedule",
    part="fem",
    fields=[],
    requires_project=False,
)
def connection_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile schedule of connection types and capacities across project steel object types."""
    from saengine.features.fem_common import load_objects

    _, objs = load_objects(ctx)
    rows = []
    for oid, obj in objs.items():
        conn = getattr(obj, "connection", None)
        if conn is not None:
            rows.append(
                {
                    "objectType": oid,
                    "connectionKind": str(getattr(conn, "kind", type(conn).__name__)),
                }
            )
    return result(
        summary={"scheduledTypes": len(rows)},
        tables=[
            table(
                "Project steel connection schedule",
                [("objectType", "Object Type"), ("connectionKind", "Connection Type")],
                rows or [{"objectType": "None configured", "connectionKind": "-"}],
            )
        ],
        notes=["Reads connection assignments from 04 Objects/objects.json."],
    )


@feature(
    "femDesignConnections.anchorBolt",
    "Anchor Bolt",
    part="fem",
    fields=[
        number("tensionDemandKn", "Factored anchor tension Nu", 65.0, unit="kN", min=0.0),
        number("embedmentMm", "Effective embedment hef", 200.0, unit="mm", min=50.0),
        number("boltDiameterMm", "Anchor diameter da", 20.0, unit="mm", min=10.0),
    ],
    requires_project=False,
)
def anchor_bolt(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check cast-in anchor bolt steel tension and concrete breakout cone capacity."""
    fc, _ = concrete_rebar_defaults(ctx)
    hef, da = values["embedmentMm"], values["boltDiameterMm"]
    nb_kn = 0.70 * 10.0 * math.sqrt(fc) * (hef**1.5) / 1000.0
    ns_kn = 0.75 * 580.0 * (0.75 * math.pi * da**2 / 4.0) / 1000.0
    gov = min(nb_kn, ns_kn)
    rows = [
        {
            "concreteBreakoutKn": nb_kn,
            "steelTensionKn": ns_kn,
            "governingCapKn": gov,
            "dcr": values["tensionDemandKn"] / gov,
            "ok": values["tensionDemandKn"] <= gov,
        }
    ]
    return result(
        summary={
            "breakoutCapKn": nb_kn,
            "steelCapKn": ns_kn,
            "utilisation": values["tensionDemandKn"] / gov,
        },
        tables=[
            table(
                "Concrete anchor bolt tension check",
                [
                    ("concreteBreakoutKn", "φNcb", "kN"),
                    ("steelTensionKn", "φNsa", "kN"),
                    ("governingCapKn", "φNn", "kN"),
                    ("dcr", "DCR"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Evaluates both concrete cone breakout (hef^1.5) and anchor rod steel tension."],
    )


@feature(
    "femDesignConnections.embedPlate",
    "Embed Plate",
    part="fem",
    fields=[
        number("shearKn", "In-plane shear Vu", 90.0, unit="kN", min=0.0),
        number("studs", "Headed shear studs", 4, min=2, max=16),
        number("studDiameterMm", "Stud diameter", 16.0, unit="mm", min=10.0),
    ],
    requires_project=False,
)
def embed_plate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate headed-stud shear capacity of concrete-embedded steel plates."""
    fc, _ = concrete_rebar_defaults(ctx)
    asa = math.pi * (values["studDiameterMm"] / 2.0) ** 2
    ec = 4700.0 * math.sqrt(fc)
    qn_kn = min(0.5 * asa * math.sqrt(fc * ec), asa * 450.0) / 1000.0
    cap_kn = 0.75 * int(values["studs"]) * qn_kn
    rows = [
        {
            "studs": int(values["studs"]),
            "perStudKn": 0.75 * qn_kn,
            "totalCapKn": cap_kn,
            "dcr": values["shearKn"] / cap_kn,
            "ok": values["shearKn"] <= cap_kn,
        }
    ]
    return result(
        summary={"totalCapacityKn": cap_kn, "utilisation": values["shearKn"] / cap_kn},
        tables=[
            table(
                "Embedded plate headed-stud shear",
                [
                    ("studs", "Studs"),
                    ("perStudKn", "φQn/stud", "kN"),
                    ("totalCapKn", "Total φVn", "kN"),
                    ("dcr", "DCR"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Checks concrete crushing around stud vs stud shank shear failure."],
    )


@feature(
    "femDesignConnections.rebarDevelopment",
    "Rebar Development",
    part="fem",
    fields=[
        number("barDiameterMm", "Joint bar diameter db", 20.0, unit="mm", min=10.0),
        number("availableDepthMm", "Available joint depth", 450.0, unit="mm", min=150.0),
    ],
    requires_project=False,
)
def rebar_development(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check beam bar hooked development length inside exterior beam-column joints."""
    fc, fy = concrete_rebar_defaults(ctx)
    with in_force(ctx.root):
        ldh = float(detailing.hook_development(values["barDiameterMm"], fy, fc).value)
    ok = ldh <= values["availableDepthMm"] - 50.0
    rows = [{"requiredLdhMm": ldh, "availableMm": values["availableDepthMm"] - 50.0, "ok": ok}]
    return result(
        summary={
            "requiredHookMm": ldh,
            "availableMm": values["availableDepthMm"] - 50.0,
            "passes": ok,
        },
        tables=[
            table(
                "Joint hooked bar anchorage check",
                [
                    ("requiredLdhMm", "Req ldh", "mm"),
                    ("availableMm", "Available", "mm"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Hooked bar must develop within confined column core."],
    )


@feature(
    "femDesignConnections.shearKey",
    "Shear Key",
    part="fem",
    fields=[
        number("shearKn", "Joint shear Vu", 120.0, unit="kN", min=0.0),
        number("keyAreaMm2", "Shear key root area", 30000.0, unit="mm²", min=1000.0),
        number("muFriction", "Interface friction μ", 0.6, min=0.2, max=1.4),
    ],
    requires_project=False,
)
def shear_key(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Design precast concrete panel joint shear key bearing and shear-friction resistance."""
    fc, _ = concrete_rebar_defaults(ctx)
    v_cap_kn = 0.75 * min(0.20 * fc * values["keyAreaMm2"], 5.5 * values["keyAreaMm2"]) / 1000.0
    dcr = values["shearKn"] / max(v_cap_kn, 1e-6)
    rows = [{"demandKn": values["shearKn"], "capacityKn": v_cap_kn, "dcr": dcr, "ok": dcr <= 1.0}]
    return result(
        summary={"shearKeyCapacityKn": v_cap_kn, "utilisation": dcr, "passes": dcr <= 1.0},
        tables=[
            table(
                "Precast panel shear key check",
                [
                    ("demandKn", "Vu", "kN"),
                    ("capacityKn", "φVn", "kN"),
                    ("dcr", "DCR"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Checks keyed concrete interface shear transfer cap."],
    )


@feature(
    "femDesignConnections.dowelledJoint",
    "Dowelled Joint",
    part="fem",
    fields=[
        number("dowelDiaMm", "Dowel/bolt diameter d", 16.0, unit="mm", min=6.0, max=30.0),
        number("memberThicknessMm", "Timber thickness t1", 90.0, unit="mm", min=25.0),
        number("timberDensityKgM3", "Characteristic density ρk", 420.0, unit="kg/m³", min=250.0),
    ],
    requires_project=False,
)
def dowelled_joint(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Johansen yield-theory timber dowel embedment and single-shear capacity."""
    # Johansen f_h,0,k = 0.082 * (1 - 0.01*d) * rho_k [MPa]
    d, t, rho = values["dowelDiaMm"], values["memberThicknessMm"], values["timberDensityKgM3"]
    fhk = 0.082 * (1.0 - 0.01 * d) * rho
    myk = 0.3 * 500.0 * (d**2.6)
    rk_kn = min(fhk * t * d, math.sqrt(2.0 * myk * fhk * d)) / 1000.0
    rows = [
        {
            "embedmentMpa": fhk,
            "yieldMomentNmm": myk,
            "charShearCapKn": rk_kn,
            "timberModuleLoaded": hasattr(timber_conn, "__name__"),
        }
    ]
    return result(
        summary={"embedmentStrengthMpa": fhk, "dowelShearCapacityKn": rk_kn},
        tables=[
            table(
                "Johansen dowelled timber joint capacity",
                [
                    ("embedmentMpa", "fh,k", "MPa"),
                    ("yieldMomentNmm", "My,Rk", "N·mm"),
                    ("charShearCapKn", "Fv,Rk/plane", "kN"),
                ],
                rows,
            )
        ],
        notes=["Evaluated using Johansen European yield equations for timber dowel connections."],
    )


@feature(
    "femDesignConnections.toothedPlate",
    "Toothed Plate",
    part="fem",
    fields=[
        number(
            "plateDiameterMm", "Toothed connector diameter dc", 62.0, unit="mm", min=35.0, max=165.0
        ),
        number("timberDensityKgM3", "Timber density ρk", 420.0, unit="kg/m³", min=250.0),
    ],
    requires_project=False,
)
def toothed_plate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate single-sided toothed-plate timber connector shear capacity."""
    dc, rho = values["plateDiameterMm"], values["timberDensityKgM3"]
    rk_kn = 18.0 * (dc**1.5) * (rho / 350.0) / 1000.0
    rows = [{"diameterMm": dc, "densityKgM3": rho, "charCapacityKn": rk_kn}]
    return result(
        summary={"connectorCapacityKn": rk_kn},
        tables=[
            table(
                "Toothed-plate timber connector capacity",
                [
                    ("diameterMm", "dc", "mm"),
                    ("densityKgM3", "ρk", "kg/m³"),
                    ("charCapacityKn", "Fv,Rk", "kN"),
                ],
                rows,
            )
        ],
        notes=["Applies empirical dc^1.5 timber connector resistance scaling."],
    )


@feature(
    "femDesignConnections.gluedSplice",
    "Glued Splice",
    part="fem",
    fields=[
        number("bondLengthMm", "Glued rod / finger bond length", 250.0, unit="mm", min=50.0),
        number("rodDiameterMm", "Threaded rod diameter", 16.0, unit="mm", min=8.0),
        number(
            "bondStrengthMpa", "Characteristic glue shear strength fvk", 4.5, unit="MPa", min=1.0
        ),
    ],
    requires_project=False,
)
def glued_splice(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check pull-out bond capacity of glued-in structural timber splices."""
    area = math.pi * values["rodDiameterMm"] * values["bondLengthMm"]
    rk_kn = area * values["bondStrengthMpa"] / 1000.0
    rows = [{"bondAreaMm2": area, "charPulloutKn": rk_kn}]
    return result(
        summary={"bondAreaMm2": area, "charPulloutKn": rk_kn},
        tables=[
            table(
                "Glued-in timber splice pull-out",
                [("bondAreaMm2", "Area", "mm²"), ("charPulloutKn", "Fax,Rk", "kN")],
                rows,
            )
        ],
        notes=["Assumes uniform shear bond distribution over effective glued perimeter."],
    )


@feature(
    "femDesignConnections.jointStiffness",
    "Joint Stiffness",
    part="fem",
    fields=[
        number(
            "sjInitialKnmRad", "Initial joint stiffness Sj,ini", 42000.0, unit="kN·m/rad", min=100.0
        ),
        number("beamEI", "Connected beam EI", 28000.0, unit="kN·m²", min=100.0),
        number("beamSpanM", "Beam span Lb", 6.0, unit="m", min=1.0),
        checkbox("bracedFrame", "Braced frame", True),
    ],
    requires_project=False,
)
def joint_stiffness(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Classify connection rotational stiffness as rigid, semi-rigid, or nominally pinned."""
    ei_l = values["beamEI"] / values["beamSpanM"]
    kb_lim = 8.0 if values["bracedFrame"] else 25.0
    norm = values["sjInitialKnmRad"] / ei_l
    cls = "Rigid" if norm >= kb_lim else ("Pinned" if norm <= 0.5 else "Semi-rigid")
    rows = [{"eiOverLM": ei_l, "sjOverBeam": norm, "rigidBound": kb_lim, "classification": cls}]
    return result(
        summary={"normalizedStiffness": norm, "classification": cls},
        tables=[
            table(
                "Rotational joint stiffness classification",
                [
                    ("eiOverLM", "EI/L", "kN·m"),
                    ("sjOverBeam", "Sj/(EI/L)"),
                    ("rigidBound", "Rigid Limit"),
                    ("classification", "Class"),
                ],
                rows,
            )
        ],
        notes=["Boundary equals 8 EI/L for braced frames and 25 EI/L for unbraced sway frames."],
    )


@feature(
    "femDesignConnections.fatigueCheck",
    "Fatigue Check",
    part="fem",
    fields=[
        number("stressRangeMpa", "Cyclic bolt tensile stress range Δσ", 45.0, unit="MPa", min=1.0),
        number("cycles", "Design stress cycles N", 2000000.0, min=1000.0),
        number(
            "detailCategoryMpa",
            "Fatigue detail category Δσc at 2M cycles",
            50.0,
            unit="MPa",
            min=20.0,
        ),
    ],
    requires_project=False,
)
def fatigue_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Perform Palmgren-Miner S-N cyclic fatigue assessment on connection bolts/welds."""
    n_allow = 2_000_000.0 * (values["detailCategoryMpa"] / values["stressRangeMpa"]) ** 3.0
    damage = values["cycles"] / n_allow
    rows = [
        {
            "stressRangeMpa": values["stressRangeMpa"],
            "appliedCycles": values["cycles"],
            "allowableCycles": n_allow,
            "minerDamageD": damage,
            "ok": damage <= 1.0,
        }
    ]
    return result(
        summary={"allowableCycles": n_allow, "minerDamage": damage, "passes": damage <= 1.0},
        tables=[
            table(
                "S-N cyclic fatigue check (slope m=3)",
                [
                    ("stressRangeMpa", "Δσ", "MPa"),
                    ("appliedCycles", "n"),
                    ("allowableCycles", "N_allow"),
                    ("minerDamageD", "D = n/N"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Uses standard cubic S-N fatigue slope m = 3."],
    )


@feature(
    "femDesignConnections.cyclicLoading",
    "Cyclic Loading",
    part="fem",
    fields=[
        number("peakMomentKnm", "Plastic moment capacity Mp", 220.0, unit="kN·m", min=1.0),
        number("plasticRotationRad", "Target cyclic drift angle θp", 0.04, unit="rad", min=0.005),
    ],
    requires_project=False,
)
def cyclic_loading(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate hysteretic energy dissipation and cumulative plastic rotation capacity under reversed seismic cycles."""
    e_cycle_kj = 4.0 * values["peakMomentKnm"] * values["plasticRotationRad"] * 0.85
    rows = [
        {
            "plasticRotationRad": values["plasticRotationRad"],
            "energyPerCycleKj": e_cycle_kj,
            "specialDuctileOk": values["plasticRotationRad"] >= 0.04,
        }
    ]
    return result(
        summary={
            "energyPerCycleKj": e_cycle_kj,
            "meetsSpecialFrame4Pct": values["plasticRotationRad"] >= 0.04,
        },
        tables=[
            table(
                "Cyclic hysteretic connection capacity",
                [
                    ("plasticRotationRad", "θp", "rad"),
                    ("energyPerCycleKj", "Loop Energy", "kJ"),
                    ("specialDuctileOk", ">= 0.04 rad"),
                ],
                rows,
            )
        ],
        notes=[
            "Special moment frame connections require stable hysteresis through 0.04 rad inter-storey drift."
        ],
    )

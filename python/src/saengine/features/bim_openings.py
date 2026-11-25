"""BIM openings, penetrations and coordination feature buttons."""

from __future__ import annotations

import math
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
from saengine.features.bim_common import require_bim, write_bim_csv, write_bim_json


@feature(
    "bimAdditionsOpenings.rectangularOpening",
    "Rectangular Opening",
    part="bim",
    fields=[
        number("width", "Opening width", 1.0, unit="m", min=0.1),
        number("height", "Opening height", 1.0, unit="m", min=0.1),
        text("host", "Host element", "W1"),
    ],
)
def rectangular_opening(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a rectangular wall or slab opening."""
    require_bim(ctx)
    opening = {
        "host": values["host"],
        "widthM": values["width"],
        "heightM": values["height"],
        "areaM2": values["width"] * values["height"],
    }
    path = write_bim_json(ctx, "rectangular-opening.json", opening)
    return result(summary={**opening, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.roundOpening",
    "Round Opening",
    part="bim",
    fields=[
        number("diameter", "Opening diameter", 300, unit="mm", min=20),
        text("host", "Host element", "S1"),
    ],
)
def round_opening(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a circular opening."""
    require_bim(ctx)

    area = math.pi * (values["diameter"] / 2000) ** 2
    opening = {"host": values["host"], "diameterMm": values["diameter"], "areaM2": area}
    path = write_bim_json(ctx, "round-opening.json", opening)
    return result(summary={**opening, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.lintelBeam",
    "Lintel Beam",
    part="bim",
    fields=[
        number("span", "Opening span", 1.5, unit="m", min=0.1),
        number("depth", "Lintel depth", 300, unit="mm", min=50),
        number("width", "Lintel width", 250, unit="mm", min=50),
    ],
)
def lintel_beam(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Sizes a lintel from geometry for detailing."""
    require_bim(ctx)
    volume = values["span"] * values["depth"] / 1000 * values["width"] / 1000
    lintel = {
        "spanM": values["span"],
        "depthMm": values["depth"],
        "widthMm": values["width"],
        "volumeM3": volume,
    }
    path = write_bim_json(ctx, "lintel-beam.json", lintel)
    return result(
        summary={**lintel, "exportPath": path},
        notes=["Geometry summary only; structural capacity is not assessed.", f"Export: {path}"],
    )


@feature(
    "bimAdditionsOpenings.openingTrim",
    "Opening Trim",
    part="bim",
    fields=[
        select(
            "trim",
            "Trim material",
            [
                ("metal", "Galv Steel C-Channel"),
                ("masonry", "Brick/Block Reveal"),
                ("timber", "Treated Timber"),
            ],
            "metal",
        ),
        number("widthMm", "Opening clear width", 900.0, unit="mm", min=100.0),
        number("heightMm", "Opening clear height", 2100.0, unit="mm", min=100.0),
        number("thickness", "Trim section thickness", 25.0, unit="mm", min=1.0),
    ],
)
def opening_trim(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute opening perimeter trim cut-length, miter waste allowance, and estimated mass."""
    require_bim(ctx)
    w = float(values["widthMm"])
    h = float(values["heightMm"])
    perim_m = 2.0 * (w + h) / 1000.0
    cut_len_m = perim_m * 1.05  # 5% corner miter allowance
    dens = {"metal": 7850.0, "masonry": 1900.0, "timber": 550.0}[values["trim"]]
    mass_kg = cut_len_m * (0.10 * float(values["thickness"]) / 1000.0) * dens
    trim = {
        "type": values["trim"],
        "perimeterM": round(perim_m, 2),
        "cutLengthWithWasteM": round(cut_len_m, 2),
        "estimatedMassKg": round(mass_kg, 1),
    }
    path = write_bim_json(ctx, "opening-trim.json", trim)
    return result(
        summary={**trim, "exportPath": path},
        notes=[
            f"Computed perimeter trim cut length & weight across 100 mm frame depth; saved to {path}."
        ],
    )


@feature(
    "bimAdditionsOpenings.shaftOpening",
    "Shaft Opening",
    part="bim",
    fields=[
        number("width", "Shaft width", 1.2, unit="m", min=0.1),
        number("length", "Shaft length", 1.8, unit="m", min=0.1),
        number("storeys", "Storey count", 3, unit="ea", min=1),
    ],
)
def shaft_opening(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a vertical shaft opening."""
    require_bim(ctx)
    area = values["width"] * values["length"]
    shaft = {
        "widthM": values["width"],
        "lengthM": values["length"],
        "areaM2": area,
        "storeyCount": int(values["storeys"]),
    }
    path = write_bim_json(ctx, "shaft-opening.json", shaft)
    return result(summary={**shaft, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.coreHole",
    "Core Hole",
    part="bim",
    fields=[
        number("diameter", "Core hole diameter", 50, unit="mm", min=10),
        number("depth", "Core depth", 300, unit="mm", min=10),
    ],
)
def core_hole(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Records a core-drilled hole."""
    require_bim(ctx)

    area = math.pi * (values["diameter"] / 2000) ** 2
    volume = area * values["depth"] / 1000
    hole = {
        "diameterMm": values["diameter"],
        "depthMm": values["depth"],
        "areaM2": area,
        "volumeM3": volume,
    }
    path = write_bim_json(ctx, "core-hole.json", hole)
    return result(summary={**hole, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.pipeSleeve",
    "Pipe Sleeve",
    part="bim",
    fields=[
        number("pipeDiameter", "Pipe outside diameter", 100, unit="mm", min=10),
        number("sleeveDiameter", "Sleeve inside diameter", 150, unit="mm", min=20),
        number("length", "Sleeve length", 300, unit="mm", min=20),
    ],
)
def pipe_sleeve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a pipe sleeve and clearance."""
    require_bim(ctx)
    clearance = (values["sleeveDiameter"] - values["pipeDiameter"]) / 2
    sleeve = {
        "pipeDiameterMm": values["pipeDiameter"],
        "sleeveDiameterMm": values["sleeveDiameter"],
        "lengthMm": values["length"],
        "radialClearanceMm": clearance,
    }
    path = write_bim_json(ctx, "pipe-sleeve.json", sleeve)
    return result(summary={**sleeve, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.sumpOpening",
    "Sump Opening",
    part="bim",
    fields=[
        number("width", "Sump width", 1.0, unit="m", min=0.1),
        number("length", "Sump length", 1.0, unit="m", min=0.1),
        number("depth", "Sump depth", 0.5, unit="m", min=0.1),
    ],
)
def sump_opening(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a sump opening in a slab."""
    require_bim(ctx)
    volume = values["width"] * values["length"] * values["depth"]
    sump = {
        "widthM": values["width"],
        "lengthM": values["length"],
        "depthM": values["depth"],
        "volumeM3": volume,
    }
    path = write_bim_json(ctx, "sump-opening.json", sump)
    return result(summary={**sump, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.penetrationTrim",
    "Penetration Trim",
    part="bim",
    fields=[
        number("diameter", "Circular penetration bore", 150.0, unit="mm", min=20.0),
        number("flangeWidth", "Escutcheon / trim flange width", 30.0, unit="mm", min=5.0),
        select(
            "material",
            "Trim material",
            [("steel", "Steel"), ("plastic", "PVC / EPDM"), ("timber", "Timber")],
            "steel",
        ),
    ],
)
def penetration_trim(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute circular penetration escutcheon ring outer diameter, area, and fastener count."""
    require_bim(ctx)
    d = float(values["diameter"])
    fw = float(values["flangeWidth"])
    outer_d = d + 2.0 * fw
    annular_area_cm2 = math.pi * ((outer_d / 2.0) ** 2 - (d / 2.0) ** 2) / 100.0
    circum_mm = math.pi * (d + fw)
    fasteners = max(4, math.ceil(circum_mm / 150.0))
    trim = {
        "diameterMm": d,
        "outerDiameterMm": outer_d,
        "ringAreaCm2": round(annular_area_cm2, 1),
        "fastenerCount": fasteners,
        "material": values["material"],
    }
    path = write_bim_json(ctx, "penetration-trim.json", trim)
    return result(
        summary={**trim, "exportPath": path},
        notes=[
            f"Outer trim ring OD={outer_d:g} mm ({fasteners} fasteners @ ~150 mm); saved to {path}."
        ],
    )


@feature(
    "bimAdditionsOpenings.clearanceCheck",
    "Clearance Check",
    part="bim",
    fields=[
        number("required", "Required clearance", 300, unit="mm", min=0),
        number("provided", "Provided clearance", 250, unit="mm", min=0),
    ],
)
def clearance_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Checks provided clearance against a required clearance."""
    require_bim(ctx)
    passes = values["provided"] >= values["required"]
    return result(
        summary={
            "requiredClearanceMm": values["required"],
            "providedClearanceMm": values["provided"],
            "reserveMm": values["provided"] - values["required"],
            "passes": passes,
        }
    )


@feature(
    "bimAdditionsOpenings.alignmentCheck",
    "Alignment Check",
    part="bim",
    fields=[
        number("north", "North/east north coordinate", 0.0, unit="mm"),
        number("south", "North/east south coordinate", 10.0, unit="mm"),
        number("tolerance", "Alignment tolerance", 5, unit="mm", min=0),
    ],
)
def alignment_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Checks two opening alignment coordinates."""
    require_bim(ctx)
    deviation = abs(values["north"] - values["south"])
    passes = deviation <= values["tolerance"]
    return result(
        summary={
            "coordinateAmm": values["north"],
            "coordinateBmm": values["south"],
            "deviationMm": deviation,
            "toleranceMm": values["tolerance"],
            "passes": passes,
        }
    )


def _all_model_openings(data: dict[str, Any], mep: dict[str, Any] | None) -> list[dict[str, Any]]:
    adds = data.get("additions") or {}
    out: list[dict[str, Any]] = []
    for k, kind in (("slabOpenings", "slabOpening"), ("wallOpenings", "wallOpening")):
        for item in adds.get(k) or []:
            if isinstance(item, dict):
                out.append({**item, "_source": "bim", "_kind": kind})
    if isinstance(mep, dict):
        for item in mep.get("openings") or []:
            if isinstance(item, dict):
                out.append(
                    {**item, "_source": "mep", "_kind": str(item.get("hostKind", "mepOpening"))}
                )
    return out


def _opening_bbox(o: dict[str, Any]) -> tuple[float, float, float, float] | None:
    pts = o.get("polygon") or o.get("outline") or []
    if isinstance(pts, list) and len(pts) >= 3:
        xs = [float(p[0]) for p in pts if isinstance(p, (list, tuple)) and len(p) >= 2]
        ys = [float(p[1]) for p in pts if isinstance(p, (list, tuple)) and len(p) >= 2]
        if xs and ys:
            return min(xs), min(ys), max(xs), max(ys)
    at = o.get("at") or o.get("center") or o.get("centre")
    if isinstance(at, (list, tuple)) and len(at) >= 2:
        w = float(o.get("width", o.get("diameter", 200.0)) or 200.0)
        h = float(o.get("depth", o.get("height", w)) or w)
        return (
            float(at[0]) - w / 2.0,
            float(at[1]) - h / 2.0,
            float(at[0]) + w / 2.0,
            float(at[1]) + h / 2.0,
        )
    return None


@feature(
    "bimAdditionsOpenings.conflictCheck",
    "Conflict Check",
    part="bim",
    fields=[
        number(
            "tolerance", "Minimum clear separation gap between openings", 150.0, unit="mm", min=0.0
        ),
    ],
)
def conflict_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detect geometric overlap or insufficient spacing between real BIM and MEP openings."""
    data = require_bim(ctx)
    mep_raw = ctx.raw("mep") if ctx.root is not None else None
    all_ops = _all_model_openings(data, mep_raw if isinstance(mep_raw, dict) else None)
    tol = float(values["tolerance"])
    rows: list[dict[str, Any]] = []
    for i in range(len(all_ops)):
        b1 = _opening_bbox(all_ops[i])
        if b1 is None:
            continue
        for j in range(i + 1, len(all_ops)):
            b2 = _opening_bbox(all_ops[j])
            if b2 is None:
                continue
            s1, s2 = (
                str(all_ops[i].get("story") or all_ops[i].get("host", "")),
                str(all_ops[j].get("story") or all_ops[j].get("host", "")),
            )
            if s1 and s2 and s1 != s2:
                continue
            dx = max(0.0, max(b1[0] - b2[2], b2[0] - b1[2]))
            dy = max(0.0, max(b1[1] - b2[3], b2[1] - b1[3]))
            gap = math.hypot(dx, dy)
            if gap < tol:
                rows.append(
                    {
                        "openingA": str(all_ops[i].get("id", f"OP-{i + 1}")),
                        "openingB": str(all_ops[j].get("id", f"OP-{j + 1}")),
                        "clearGapMm": round(gap, 1),
                        "status": "OVERLAP" if gap == 0.0 else f"TOO CLOSE (<{tol:g})",
                    }
                )
    path = write_bim_csv(
        ctx, "opening-conflicts.csv", ["openingA", "openingB", "clearGapMm", "status"], rows
    )
    return result(
        summary={
            "openingsInspected": len(all_ops),
            "conflictCount": len(rows),
            "toleranceMm": tol,
            "exportPath": path,
        },
        tables=[
            table(
                "Opening Geometric Proximity Conflicts",
                [
                    ("openingA", "Opening A"),
                    ("openingB", "Opening B"),
                    ("clearGapMm", "Gap", "mm"),
                    ("status", "Status"),
                ],
                rows
                or [{"openingA": "-", "openingB": "-", "clearGapMm": tol, "status": "ALL CLEAR"}],
            )
        ],
        notes=[
            f"Inspected {len(all_ops)} real BIM+MEP opening(s); found {len(rows)} proximity/overlap conflict(s). Export: {path}"
        ],
    )


@feature(
    "bimAdditionsOpenings.penetrationSchedule",
    "Penetration Schedule",
    part="bim",
    fields=[text("hostFilter", "Host member / slab filter (blank = all)", "")],
)
def penetration_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build real penetration schedule across 06 BIM openings and 07 MEP sleeves."""
    data = require_bim(ctx)
    mep_raw = ctx.raw("mep") if ctx.root is not None else None
    all_ops = _all_model_openings(data, mep_raw if isinstance(mep_raw, dict) else None)
    filt = values["hostFilter"].strip().lower()
    rows = []
    for o in all_ops:
        host = str(o.get("host") or o.get("slab") or o.get("wall") or o.get("story") or "-")
        if filt and filt not in host.lower():
            continue
        rows.append(
            {
                "id": str(o.get("id", "-")),
                "kind": o.get("_kind", ""),
                "source": o.get("_source", ""),
                "host": host,
                "size": str(
                    o.get("diameter")
                    or f"{o.get('width', '?')}x{o.get('depth', o.get('height', '?'))}"
                ),
            }
        )
    path = write_bim_csv(
        ctx, "penetration-schedule.csv", ["id", "kind", "source", "host", "size"], rows
    )
    return result(
        summary={"penetrationCount": len(rows), "exportPath": path},
        tables=[
            table(
                "Penetration Schedule",
                [
                    ("id", "ID"),
                    ("kind", "Kind"),
                    ("source", "Source"),
                    ("host", "Host"),
                    ("size", "Size [mm]"),
                ],
                rows or [{"id": "-", "kind": "-", "source": "-", "host": "-", "size": "-"}],
            )
        ],
        notes=[f"Compiled {len(rows)} real project penetration(s); exported to {path}."],
    )


@feature(
    "bimAdditionsOpenings.firestopCollar",
    "Firestop Collar",
    part="bim",
    fields=[
        number("pipeDiameter", "Combustible pipe OD", 110.0, unit="mm", min=20.0),
        number("collarHeight", "Intumescent collar casing depth", 50.0, unit="mm", min=20.0),
        number("coreGapMm", "Target annular gap around pipe", 15.0, unit="mm", min=5.0),
    ],
)
def firestop_collar(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size core-drilled slab/wall hole and intumescent fill volume around firestop collar."""
    require_bim(ctx)
    d = float(values["pipeDiameter"])
    gap = float(values["coreGapMm"])
    hole_d = d + 2.0 * gap
    fill_area = math.pi * ((hole_d / 2.0) ** 2 - (d / 2.0) ** 2)
    intum_vol_ml = fill_area * float(values["collarHeight"]) / 1000.0
    collar = {
        "pipeDiameterMm": d,
        "coreHoleDiameterMm": hole_d,
        "collarHeightMm": float(values["collarHeight"]),
        "sealantFillMl": round(intum_vol_ml, 1),
    }
    path = write_bim_json(ctx, "firestop-collar.json", collar)
    return result(
        summary={**collar, "exportPath": path},
        notes=[
            f"Core hole={hole_d:g} mm; intumescent annular volume={intum_vol_ml:.0f} mL; saved to {path}."
        ],
    )


@feature(
    "bimAdditionsOpenings.acousticSleeve",
    "Acoustic Sleeve",
    part="bim",
    fields=[
        number("pipeDiameter", "Pipe outer diameter", 100.0, unit="mm", min=20.0),
        number("sleeveDiameter", "Steel sleeve internal bore", 160.0, unit="mm", min=30.0),
        number("linerThickness", "Mineral-wool liner thickness", 20.0, unit="mm", min=5.0),
    ],
)
def acoustic_sleeve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify acoustic decoupling liner clearance between pipe OD and structural sleeve bore."""
    require_bim(ctx)
    d_pipe = float(values["pipeDiameter"])
    d_slv = float(values["sleeveDiameter"])
    t_lin = float(values["linerThickness"])
    avail_radial = (d_slv - d_pipe) / 2.0
    compression_mm = max(0.0, t_lin - avail_radial)
    compression_pct = (compression_mm / t_lin) * 100.0 if t_lin > 0 else 0.0
    ok = avail_radial >= 0.7 * t_lin  # Do not over-compress mineral wool >30% (acoustic bridging)
    sleeve = {
        "pipeDiameterMm": d_pipe,
        "sleeveDiameterMm": d_slv,
        "radialAnnulusMm": round(avail_radial, 1),
        "linerCompressionPct": round(compression_pct, 1),
        "decoupledOk": ok,
    }
    path = write_bim_json(ctx, "acoustic-sleeve.json", sleeve)
    return result(
        summary={**sleeve, "exportPath": path},
        notes=[
            f"Radial gap={avail_radial:.1f} mm ({compression_pct:.0f}% wool compression, <=30% prevents acoustic bridging); saved to {path}."
        ],
    )


@feature(
    "bimAdditionsOpenings.thermalBreakSleeve",
    "Thermal Break Sleeve",
    part="bim",
    fields=[
        number("pipeDiameter", "Cold/chilled pipe outer diameter", 100.0, unit="mm", min=20.0),
        number("breakThickness", "Aerogel / rigid PUR break thickness", 25.0, unit="mm", min=5.0),
        number("deltaTK", "Pipe-to-slab temperature differential", 18.0, unit="K", min=1.0),
    ],
)
def thermalBreakSleeve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute insulated thermal-break sleeve bore OD and radial conductive heat loss through slab."""
    require_bim(ctx)
    r_in = float(values["pipeDiameter"]) / 2000.0
    r_out = r_in + float(values["breakThickness"]) / 1000.0
    k_pur = 0.028  # W/(m·K)
    q_w_per_m = (2.0 * math.pi * k_pur * float(values["deltaTK"])) / math.log(r_out / r_in)
    sleeve = {
        "pipeDiameterMm": float(values["pipeDiameter"]),
        "outerSleeveMm": round(r_out * 2000.0, 1),
        "breakThicknessMm": float(values["breakThickness"]),
        "radialLossWPerM": round(q_w_per_m, 2),
    }
    path = write_bim_json(ctx, "thermal-break-sleeve.json", sleeve)
    return result(
        summary={**sleeve, "exportPath": path},
        notes=[
            f"Cylindrical conduction through sleeve={q_w_per_m:.2f} W/m; outer bore={sleeve['outerSleeveMm']} mm; saved to {path}."
        ],
    )


@feature(
    "bimAdditionsOpenings.openingFraming",
    "Opening Framing",
    part="bim",
    fields=[
        select(
            "framing",
            "Trimmer framing material",
            [
                ("steel", "Structural Steel"),
                ("timber", "Engineered Timber"),
                ("concrete", "Embedded Rebar Band"),
            ],
            "steel",
        ),
        number("openingSpanM", "Trimmed opening span", 1.8, unit="m", min=0.2),
        number(
            "tributaryLoadKnPerM", "Factored trimmed slab line load", 12.0, unit="kN/m", min=0.5
        ),
        number("width", "Trimmer flange/beam width", 100.0, unit="mm", min=40.0),
    ],
)
def opening_framing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size opening header trimmer bending moment M_u and required plastic section modulus Zx."""
    require_bim(ctx)
    L = float(values["openingSpanM"])
    w = float(values["tributaryLoadKnPerM"])
    mu_knm = w * (L**2) / 8.0
    fy = {"steel": 250.0, "timber": 24.0, "concrete": 400.0}[values["framing"]]
    req_zx_cm3 = ((mu_knm * 1e6) / (0.90 * fy)) / 1000.0
    framing = {
        "type": values["framing"],
        "spanM": L,
        "factoredMomentKnM": round(mu_knm, 2),
        "requiredSectionModulusCm3": round(req_zx_cm3, 1),
        "widthMm": float(values["width"]),
    }
    path = write_bim_json(ctx, "opening-framing.json", framing)
    return result(
        summary={**framing, "exportPath": path},
        notes=[
            f"Simply supported trimmer M={mu_knm:.2f} kN·m -> Zx_req={req_zx_cm3:.1f} cm^3; saved to {path}."
        ],
    )


@feature(
    "bimAdditionsOpenings.diagonalRebar",
    "Diagonal Rebar",
    part="bim",
    fields=[
        number("span", "Opening span", 1.0, unit="m", min=0.1),
        number("diameter", "Bar diameter", 16, unit="mm", min=6),
        number("count", "Bar count", 4, unit="ea", min=1),
    ],
)
def diagonal_rebar(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a diagonal reinforcement proposal."""
    require_bim(ctx)
    length = (values["span"] ** 2 + values["span"] ** 2) ** 0.5
    rebar = {
        "spanM": values["span"],
        "barDiameterMm": values["diameter"],
        "barCount": int(values["count"]),
        "diagonalLengthM": length,
    }
    path = write_bim_json(ctx, "diagonal-rebar.json", rebar)
    return result(
        summary={**rebar, "exportPath": path},
        notes=["Diagonal length uses a 45-degree square opening assumption.", f"Export: {path}"],
    )


@feature(
    "bimAdditionsOpenings.edgeTrimAngle",
    "Edge Trim Angle",
    part="bim",
    fields=[
        number("leg", "Angle equal leg width", 65.0, unit="mm", min=20.0),
        number("thickness", "Angle thickness", 6.0, unit="mm", min=3.0),
        number("length", "Trimmed edge length", 2.4, unit="m", min=0.2),
    ],
)
def edge_trim_angle(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute equal steel edge-trim angle cross-section area, steel weight, and anchor count."""
    require_bim(ctx)
    leg = float(values["leg"])
    t = float(values["thickness"])
    L = float(values["length"])
    area_mm2 = (2.0 * leg - t) * t
    mass_kg = area_mm2 * 7850e-6 * L
    anchors = max(2, math.ceil((L * 1000.0) / 300.0) + 1)
    trim = {
        "legMm": leg,
        "thicknessMm": t,
        "lengthM": L,
        "massKg": round(mass_kg, 2),
        "anchorsAt300Mm": anchors,
    }
    path = write_bim_json(ctx, "edge-trim-angle.json", trim)
    return result(
        summary={**trim, "exportPath": path},
        notes=[
            f"L{leg:g}x{leg:g}x{t:g} steel mass={mass_kg:.2f} kg with {anchors} anchors @ 300 mm; saved to {path}."
        ],
    )


@feature(
    "bimAdditionsOpenings.provisionForHole",
    "Provision For Hole",
    part="bim",
    fields=[
        text("openingId", "Opening id", "O1"),
        text("owner", "Responsible discipline", "Structural"),
        checkbox("reserved", "Reserved in model", True),
    ],
)
def provision_for_hole(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate opening ID against 06 BIM / 07 MEP and maintain persistent PFH reservation register."""
    import json

    data = require_bim(ctx)
    mep_raw = ctx.raw("mep") if ctx.root is not None else None
    all_ops = _all_model_openings(data, mep_raw if isinstance(mep_raw, dict) else None)
    valid_ids = {str(o.get("id", "")) for o in all_ops if o.get("id")}
    oid = values["openingId"].strip()
    if valid_ids and oid not in valid_ids:
        raise FeatureInputError(
            f"Opening {oid!r} not found in BIM/MEP openings ({sorted(valid_ids)})."
        )
    entry = {
        "openingId": oid,
        "owner": values["owner"].strip(),
        "reserved": bool(values["reserved"]),
    }
    reg_file = ctx.path("11 Exports/BIM/hole-provision.json")
    register: dict[str, dict[str, Any]] = {}
    if reg_file is not None and reg_file.exists():
        try:
            loaded = json.loads(reg_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("provisions"), list):
                register = {
                    str(r.get("openingId")): r for r in loaded["provisions"] if isinstance(r, dict)
                }
        except ValueError:
            pass
    register[oid] = entry
    rows = list(register.values())
    path = write_bim_json(ctx, "hole-provision.json", {"provisions": rows})
    return result(
        summary={**entry, "totalProvisions": len(rows), "exportPath": path},
        tables=[
            table(
                "PFH Reservation Register",
                [("openingId", "Opening"), ("owner", "Discipline"), ("reserved", "Reserved")],
                rows,
            )
        ],
        notes=[
            f"Validated opening {oid} against model and updated PFH ledger ({len(rows)} entries) at {path}."
        ],
    )


@feature(
    "bimAdditionsOpenings.approvalWorkflow",
    "Approval Workflow",
    part="bim",
    fields=[
        text("openingIds", "Opening ids", "O1,O2"),
        select(
            "stage",
            "Approval stage",
            [("draft", "Draft"), ("review", "In review"), ("approved", "Approved")],
            "draft",
        ),
    ],
)
def approval_workflow(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate model opening IDs, enforce workflow state transitions, and persist opening approval ledger."""
    import json

    data = require_bim(ctx)
    mep_raw = ctx.raw("mep") if ctx.root is not None else None
    all_ops = _all_model_openings(data, mep_raw if isinstance(mep_raw, dict) else None)
    valid_ids = {str(o.get("id", "")) for o in all_ops if o.get("id")}
    ids = [x.strip() for x in values["openingIds"].split(",") if x.strip()]
    if not ids:
        raise FeatureInputError("Enter at least one opening ID.")
    unknown = [i for i in ids if valid_ids and i not in valid_ids]
    if unknown:
        raise FeatureInputError(f"Unknown opening ID(s) not in model: {unknown}.")
    state_path = ctx.path("11 Exports/BIM/opening-approval.json")
    prior: dict[str, str] = {}
    if state_path is not None and state_path.exists():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                prior = {str(k): str(v) for k, v in loaded.items()}
        except ValueError:
            pass
    for i in ids:
        prior[i] = values["stage"]
    rows = [{"openingId": k, "stage": v} for k, v in sorted(prior.items())]
    write_bim_json(ctx, "opening-approval.json", prior)
    path = write_bim_csv(ctx, "opening-approval.csv", ["openingId", "stage"], rows)
    return result(
        summary={
            "updatedCount": len(ids),
            "totalTracked": len(rows),
            "stage": values["stage"],
            "exportPath": path,
        },
        tables=[
            table(
                "Opening Approval Ledger", [("openingId", "Opening id"), ("stage", "Stage")], rows
            )
        ],
        notes=[
            f"Validated {len(ids)} opening ID(s) against BIM/MEP models and updated ledger at {path}."
        ],
    )


@feature(
    "bimAdditionsOpenings.voidReservationList",
    "Void Reservation List",
    part="bim",
    fields=[text("serviceFilter", "Filter service / host (blank = all)", "")],
)
def void_reservation_list(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate coordinated void reservation schedule from real 06 BIM & 07 MEP openings."""
    data = require_bim(ctx)
    mep_raw = ctx.raw("mep") if ctx.root is not None else None
    all_ops = _all_model_openings(data, mep_raw if isinstance(mep_raw, dict) else None)
    filt = values["serviceFilter"].strip().lower()
    rows = []
    for o in all_ops:
        svc = str(o.get("service") or o.get("_kind") or "Structure")
        if filt and filt not in svc.lower():
            continue
        bb = _opening_bbox(o)
        area_m2 = round(((bb[2] - bb[0]) * (bb[3] - bb[1])) / 1e6, 3) if bb else 0.0
        rows.append(
            {
                "id": str(o.get("id", "-")),
                "service": svc,
                "story": str(o.get("story") or o.get("host") or "-"),
                "areaM2": area_m2,
            }
        )
    path = write_bim_csv(
        ctx, "void-reservation-list.csv", ["id", "service", "story", "areaM2"], rows
    )
    return result(
        summary={
            "reservationCount": len(rows),
            "totalAreaM2": round(sum(r["areaM2"] for r in rows), 3),
            "exportPath": path,
        },
        tables=[
            table(
                "Void Reservations",
                [
                    ("id", "ID"),
                    ("service", "Service / Type"),
                    ("story", "Story / Host"),
                    ("areaM2", "Area", "m²"),
                ],
                rows or [{"id": "-", "service": "-", "story": "-", "areaM2": 0.0}],
            )
        ],
        notes=[f"Aggregated {len(rows)} real project void reservation(s); exported to {path}."],
    )

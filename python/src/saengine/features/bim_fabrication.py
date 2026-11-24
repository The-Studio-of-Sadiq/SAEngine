"""BIM fabrication, reinforcement and delivery feature buttons."""

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
from saengine.features.bim_common import (
    kind_counts,
    require_bim,
    write_bim_csv,
    write_bim_json,
)


def _segment_clearance(
    start_a: list[float], end_a: list[float], start_b: list[float], end_b: list[float]
) -> float:
    """Shortest distance between two finite 3D bar centerline segments."""

    def dot(first: list[float], second: list[float]) -> float:
        return sum(first[i] * second[i] for i in range(3))

    u = [end_a[i] - start_a[i] for i in range(3)]
    v = [end_b[i] - start_b[i] for i in range(3)]
    w = [start_a[i] - start_b[i] for i in range(3)]
    a, b, c = dot(u, u), dot(u, v), dot(v, v)
    d, e = dot(u, w), dot(v, w)
    if a == 0 or c == 0:
        raise FeatureInputError("Each bar geometry segment must have nonzero length.")
    denominator = a * c - b * b
    s = min(1.0, max(0.0, (b * e - c * d) / denominator)) if denominator else 0.0
    t = (b * s + e) / c
    if t < 0:
        t = 0.0
        s = min(1.0, max(0.0, -d / a))
    elif t > 1:
        t = 1.0
        s = min(1.0, max(0.0, (b - d) / a))
    delta = [w[i] + s * u[i] - t * v[i] for i in range(3)]
    return math.sqrt(dot(delta, delta))


@feature(
    "bimFabrication.rebarSet",
    "Rebar Set",
    part="bim",
    fields=[
        select(
            "host",
            "Concrete host",
            [("beam", "Beam"), ("column", "Column"), ("slab", "Slab"), ("wall", "Wall")],
            "beam",
        ),
        number("diameter", "Bar diameter", 16.0, unit="mm", min=6.0),
        number("spacing", "Bar pitch spacing", 150.0, unit="mm", min=40.0),
        number("runWidthM", "Bar distribution width", 4.0, unit="m", min=0.2),
        number("barLengthM", "Individual cut length", 6.0, unit="m", min=0.3),
    ],
)
def rebar_set(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute fabricated rebar set count, As/m, unit mass, and total steel weight."""
    require_bim(ctx)
    d = float(values["diameter"])
    s = float(values["spacing"])
    w_mm = float(values["runWidthM"]) * 1000.0
    n_bars = math.floor(w_mm / s) + 1
    bar_area = math.pi * (d / 2.0) ** 2
    as_per_m = bar_area * (1000.0 / s)
    unit_mass_kg_m = bar_area * 7850e-6
    tot_len = n_bars * float(values["barLengthM"])
    tot_kg = tot_len * unit_mass_kg_m
    set_row = {
        "host": values["host"],
        "diameterMm": d,
        "spacingMm": s,
        "barCount": n_bars,
        "asMm2PerM": round(as_per_m, 1),
        "totalLengthM": round(tot_len, 1),
        "totalWeightKg": round(tot_kg, 1),
    }
    path = write_bim_json(ctx, "fabrication-rebar-set.json", set_row)
    return result(
        summary={**set_row, "exportPath": path},
        tables=[
            table(
                "Fabrication Rebar Set Takeoff",
                [
                    ("host", "Host"),
                    ("diameterMm", "Dia", "mm"),
                    ("barCount", "Bars"),
                    ("asMm2PerM", "As/m", "mm²/m"),
                    ("totalWeightKg", "Weight", "kg"),
                ],
                [set_row],
            )
        ],
        notes=[
            f"Unit weight={unit_mass_kg_m:.3f} kg/m -> {tot_kg:.1f} kg across {n_bars} bar(s); saved to {path}."
        ],
    )


@feature(
    "bimFabrication.barBending",
    "Bar Bending",
    part="bim",
    fields=[
        number("diameter", "Bar diameter", 16, unit="mm", min=6),
        number("straightLength", "Straight length", 3000, unit="mm", min=100),
        number("bendAngle", "Bend angle", 90, unit="°", min=0, max=180),
        number("insideRadius", "Inside bend radius", 64, unit="mm", min=1),
    ],
)
def bar_bending(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate bend arc length from the entered inside radius and bar diameter."""
    require_bim(ctx)
    centerline_radius = values["insideRadius"] + values["diameter"] / 2
    arc = centerline_radius * math.radians(values["bendAngle"])
    developed = values["straightLength"] + arc
    path = write_bim_json(
        ctx,
        "bar-bending.json",
        {
            "diameterMm": values["diameter"],
            "straightMm": values["straightLength"],
            "angleDeg": values["bendAngle"],
            "insideRadiusMm": values["insideRadius"],
            "centerlineRadiusMm": centerline_radius,
            "developedMm": developed,
        },
    )
    return result(
        summary={
            "diameterMm": values["diameter"],
            "bendAngleDeg": values["bendAngle"],
            "insideRadiusMm": values["insideRadius"],
            "developedLengthMm": developed,
            "exportPath": path,
        },
        notes=[
            "Developed length adds a circular centerline arc to the entered straight length; allowances for hooks and tangent points are not included.",
            f"Export: {path}",
        ],
    )


@feature(
    "bimFabrication.couplers",
    "Couplers",
    part="bim",
    fields=[
        number("diameter", "Deformed bar diameter", 20.0, unit="mm", min=10.0),
        number("count", "Scheduled coupler count", 10, unit="ea", min=1),
        number("gripLength", "Sleeve thread engagement length", 120.0, unit="mm", min=30.0),
        number("fyMpa", "Bar yield strength fy", 500.0, unit="MPa", min=250.0),
    ],
)
def couplers(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Type-1/Type-2 mechanical bar coupler tensile demand and splice schedule."""
    require_bim(ctx)
    d = float(values["diameter"])
    count = int(values["count"])
    a_bar = math.pi * (d / 2.0) ** 2
    type1_kn = 1.25 * float(values["fyMpa"]) * a_bar / 1000.0
    lap_saved_m = max(0.0, (45.0 * d - float(values["gripLength"])) / 1000.0)
    steel_saved_kg = count * lap_saved_m * (a_bar * 7850e-6)
    rows = [
        {
            "number": i,
            "diameterMm": d,
            "gripMm": values["gripLength"],
            "minCapKn": round(type1_kn, 1),
        }
        for i in range(1, count + 1)
    ]
    path = write_bim_csv(ctx, "couplers.csv", ["number", "diameterMm", "gripMm", "minCapKn"], rows)
    return result(
        summary={
            "couplerCount": count,
            "requiredStrengthKn": round(type1_kn, 1),
            "steelCongestionSavedKg": round(steel_saved_kg, 1),
            "exportPath": path,
        },
        tables=[
            table(
                "Mechanical Bar Couplers",
                [
                    ("number", "Item"),
                    ("diameterMm", "Dia", "mm"),
                    ("gripMm", "Grip", "mm"),
                    ("minCapKn", "1.25fy·As", "kN"),
                ],
                rows,
            )
        ],
        notes=[
            f"Type-1 proof load >= 1.25 fy As ({type1_kn:.1f} kN); avoids ~{steel_saved_kg:.1f} kg lap congestion -> {path}."
        ],
    )


@feature(
    "bimFabrication.meshReinforcement",
    "Mesh Reinforcement",
    part="bim",
    fields=[
        number("width", "Panel width", 10.0, unit="m", min=0.1),
        number("height", "Panel height", 10.0, unit="m", min=0.1),
        number("spacingX", "Primary spacing", 150, unit="mm", min=25),
        number("spacingY", "Secondary spacing", 150, unit="mm", min=25),
    ],
)
def mesh_reinforcement(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate orthogonal bar counts and lengths over a rectangular panel."""
    require_bim(ctx)
    width = values["width"]
    height = values["height"]
    sx = values["spacingX"] / 1000
    sy = values["spacingY"] / 1000
    rows_primary = math.ceil(height / sy) + 1
    rows_secondary = math.ceil(width / sx) + 1
    primary_length = rows_primary * width
    secondary_length = rows_secondary * height
    mesh = {
        "widthM": width,
        "heightM": height,
        "areaM2": width * height,
        "spacingXMm": values["spacingX"],
        "spacingYMm": values["spacingY"],
        "primaryCount": rows_primary,
        "secondaryCount": rows_secondary,
        "primaryLengthM": primary_length,
        "secondaryLengthM": secondary_length,
    }
    path = write_bim_json(ctx, "mesh-reinforcement.json", mesh)
    return result(
        summary={
            **mesh,
            "estimatedLineCount": rows_primary + rows_secondary,
            "totalBarLengthM": primary_length + secondary_length,
            "exportPath": path,
        },
        notes=[
            "Bars are uniformly spaced across the entered rectangular panel; perimeter cover, hooks, laps, and openings are not included.",
            f"Export: {path}",
        ],
    )


@feature(
    "bimFabrication.precastPanels",
    "Precast Panels",
    part="bim",
    fields=[
        number("width", "Panel width", 3.0, unit="m", min=0.1),
        number("height", "Panel height", 3.0, unit="m", min=0.1),
        number("thickness", "Panel thickness", 150, unit="mm", min=50),
        number("count", "Panel count", 10, unit="ea", min=1),
    ],
)
def precast_panels(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarises precast wall panel geometry."""
    require_bim(ctx)
    count = int(values["count"])
    area = values["width"] * values["height"]
    volume = area * values["thickness"] / 1000 * count
    rows = [
        {
            "panel": i + 1,
            "widthM": values["width"],
            "heightM": values["height"],
            "thicknessMm": values["thickness"],
        }
        for i in range(count)
    ]
    path = write_bim_csv(
        ctx, "precast-panels.csv", ["panel", "widthM", "heightM", "thicknessMm"], rows
    )
    return result(
        summary={
            "panelCount": count,
            "areaM2": area * count,
            "volumeM3": volume,
            "exportPath": path,
        },
        tables=[
            table(
                "Precast Panels",
                [
                    ("panel", "Panel"),
                    ("widthM", "Width [m]", "m"),
                    ("heightM", "Height [m]", "m"),
                    ("thicknessMm", "Thickness [mm]", "mm"),
                ],
                rows[:100],
            )
        ],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimFabrication.liftingPoints",
    "Lifting Points",
    part="bim",
    fields=[
        number("length", "Element length", 6.0, unit="m", min=0.1),
        number("weight", "Element weight", 20.0, unit="kN", min=0.1),
        number("factor", "Dynamic multiplier", 1.5, unit="x", min=1),
        number(
            "supportFraction",
            "Support offset from each end",
            0.2,
            unit="fraction",
            min=0.01,
            max=0.5,
        ),
    ],
)
def lifting_points(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Proposes two lifting points for a linear precast element."""
    require_bim(ctx)
    span = values["length"]
    load = values["weight"] * values["factor"] / 2
    offset = span * values["supportFraction"]
    points = [
        {"point": 1, "offsetM": offset, "loadKn": load},
        {"point": 2, "offsetM": span - offset, "loadKn": load},
    ]
    path = write_bim_csv(ctx, "lifting-points.csv", ["point", "offsetM", "loadKn"], points)
    return result(
        summary={
            "pointCount": 2,
            "designLiftLoadKn": load,
            "dynamicFactor": values["factor"],
            "supportOffsetM": offset,
            "exportPath": path,
        },
        tables=[
            table(
                "Lifting Points",
                [
                    ("point", "Point"),
                    ("offsetM", "Offset [m]", "m"),
                    ("loadKn", "Lift load [kN]", "kN"),
                ],
                points,
            )
        ],
        notes=[
            "Planning layout; final sling angles and embedded inserts require the element product method.",
            f"Export: {path}",
        ],
    )


@feature(
    "bimFabrication.jointDetails",
    "Joint Details",
    part="bim",
    fields=[
        select(
            "joint",
            "Joint type",
            [
                ("butt", "Butt splice"),
                ("lap", "Lap plate"),
                ("miter", "Miter corner"),
                ("dowel", "Precast dowel"),
            ],
            "butt",
        ),
        number("gap", "Nominal fit-up root gap", 10.0, unit="mm", min=0.0),
        number("memberSpanM", "Segment length between joints", 9.0, unit="m", min=1.0),
        number("deltaTC", "Service thermal swing ΔT", 35.0, unit="°C", min=5.0),
    ],
)
def joint_details(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute thermal expansion movement at fabrication joint and verify root/erection gap."""
    require_bim(ctx)
    dl_mm = 1.2e-5 * (float(values["memberSpanM"]) * 1000.0) * float(values["deltaTC"])
    gap_mm = float(values["gap"])
    ok = gap_mm >= dl_mm or values["joint"] != "butt"
    detail = {
        "joint": values["joint"],
        "nominalGapMm": gap_mm,
        "thermalMovementMm": round(dl_mm, 2),
        "clearanceOk": ok,
    }
    path = write_bim_json(ctx, "joint-detail.json", detail)
    return result(
        summary={**detail, "exportPath": path},
        tables=[
            table(
                "Fabrication Joint Movement Check",
                [
                    ("joint", "Joint"),
                    ("nominalGapMm", "Gap", "mm"),
                    ("thermalMovementMm", "Thermal ΔL", "mm"),
                    ("clearanceOk", "OK"),
                ],
                [detail],
            )
        ],
        notes=[
            f"Thermal delta={dl_mm:.2f} mm over {values['memberSpanM']:g} m segment; saved to {path}."
        ],
    )


@feature(
    "bimFabrication.boltsWelds",
    "Bolts & Welds",
    part="bim",
    fields=[
        select(
            "type",
            "Fastening type",
            [
                ("bolt", "M20 Grade 8.8 Bolts"),
                ("weld", "8mm E48 Fillet Weld"),
                ("hybrid", "Slip-Critical + Weld"),
            ],
            "bolt",
        ),
        number("quantity", "Bolt count / weld decimetres", 8, unit="ea", min=1),
    ],
)
def bolts_welds(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute fabrication fastener shear resistance via saengine.design.steel_connections."""
    from saengine.design import steel_connections as sc
    from saengine.report.clauses import in_force

    require_bim(ctx)
    qty = int(values["quantity"])
    with in_force(ctx.root):
        v_bolt_kn = sc.bolt_shear_capacity("8.8", 20.0, planes=1) / 1000.0
        w_cap_kn_per_100 = sc.fillet_capacity_per_mm(8.0, 480.0) * 100.0 / 1000.0
    cap_kn = (
        qty * v_bolt_kn
        if values["type"] == "bolt"
        else (
            qty * w_cap_kn_per_100
            if values["type"] == "weld"
            else qty * (v_bolt_kn + w_cap_kn_per_100)
        )
    )
    item = {"type": values["type"], "quantity": qty, "designCapacityKn": round(cap_kn, 1)}
    path = write_bim_json(ctx, "fastening-schedule.json", item)
    return result(
        summary={**item, "exportPath": path},
        notes=[
            f"Computed shop/site fastener capacity={cap_kn:.1f} kN via code pack; saved to {path}."
        ],
    )


@feature(
    "bimFabrication.cncData",
    "CNC Data",
    part="bim",
    fields=[
        select(
            "format", "Output format", [("dstv", "DSTV"), ("csv", "CSV"), ("json", "JSON")], "dstv"
        ),
        checkbox("includeHoles", "Include holes", True),
    ],
)
def cnc_data(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export project fabrication parts as DSTV or a part-list file."""
    require_bim(ctx)
    from saengine.fabrication.export import FabricationError, export_nc, fabrication_model

    try:
        model, _ = fabrication_model(ctx.root)
    except (FabricationError, ValueError, OSError) as error:
        raise FeatureInputError(
            f"The project fabrication model could not be built: {error}"
        ) from error
    rows = [
        {
            "mark": part.mark,
            "assembly": assembly,
            "name": part.name,
            "kind": part.kind,
            "lengthMm": part.length,
            "massKg": part.mass_per_m * part.length / 1000,
            "holeCount": len(part.holes) if values["includeHoles"] else 0,
        }
        for part, assembly in model.parts()
    ]
    if not rows:
        raise FeatureInputError("The project fabrication model has no parts to export.")
    if values["format"] == "dstv":
        try:
            output = export_nc(ctx.root)
        except (FabricationError, ValueError, OSError) as error:
            raise FeatureInputError(f"DSTV fabrication export failed: {error}") from error
        files = output.get("files", [])
        if not files:
            raise FeatureInputError("The fabrication exporter produced no DSTV files.")
        path = str(output["folder"])
        return result(
            summary={
                "format": "dstv",
                "partCount": len(rows),
                "fileCount": len(files),
                "exportPath": path,
            },
            tables=[
                table(
                    "CNC Parts",
                    [
                        ("mark", "Mark"),
                        ("assembly", "Assembly"),
                        ("name", "Profile"),
                        ("lengthMm", "Length", "mm"),
                        ("massKg", "Mass", "kg"),
                    ],
                    rows,
                )
            ],
            notes=[*output.get("notes", []), f"DSTV NC files written to {path}."],
        )
    columns = ["mark", "assembly", "name", "kind", "lengthMm", "massKg", "holeCount"]
    path = (
        write_bim_csv(ctx, "cnc-members.csv", columns, rows)
        if values["format"] == "csv"
        else write_bim_json(ctx, "cnc-members.json", {"parts": rows})
    )
    counts = kind_counts(require_bim(ctx))
    return result(
        summary={
            "format": values["format"],
            "includeHoles": bool(values["includeHoles"]),
            "partCount": len(rows),
            "elementCount": sum(counts.values()),
            "exportPath": path,
        },
        tables=[
            table(
                "CNC Part List",
                [
                    ("mark", "Mark"),
                    ("assembly", "Assembly"),
                    ("name", "Profile"),
                    ("kind", "Kind"),
                    ("lengthMm", "Length", "mm"),
                    ("massKg", "Mass", "kg"),
                    ("holeCount", "Hole count"),
                ],
                rows,
            )
        ],
        notes=[f"Fabrication part list written to {path}."],
    )


@feature(
    "bimFabrication.fabricationDrawings",
    "Fabrication Drawings",
    part="bim",
    fields=[
        select(
            "sheet",
            "Detail scale",
            [("1:20", "1:20"), ("1:50", "1:50"), ("1:100", "1:100")],
            "1:20",
        ),
        number("detailsPerSheet", "Max fabrication details per A1 sheet", 6, min=1, max=20),
    ],
)
def fabrication_drawings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Allocate shop-drawing sheet packages across 06 BIM element categories and stories."""
    data = require_bim(ctx)
    per_sheet = int(values["detailsPerSheet"])
    rows = []
    tot_sheets = 0
    for k, qty in sorted(kind_counts(data).items()):
        sh = max(1, math.ceil(qty / per_sheet))
        tot_sheets += sh
        rows.append({"kind": k, "elements": qty, "sheetCount": sh, "scale": values["sheet"]})
    path = write_bim_csv(
        ctx, "fabrication-drawing-list.csv", ["kind", "elements", "sheetCount", "scale"], rows
    )
    return result(
        summary={
            "sheetScale": values["sheet"],
            "totalSheetsRequired": tot_sheets,
            "categories": len(rows),
            "exportPath": path,
        },
        tables=[
            table(
                "Shop Drawing Package Allocation",
                [
                    ("kind", "Category"),
                    ("elements", "Parts"),
                    ("sheetCount", "Sheets"),
                    ("scale", "Scale"),
                ],
                rows,
            )
        ],
        notes=[
            f"Planned {tot_sheets} A1 shop-drawing sheet(s) at {values['sheet']}; exported to {path}."
        ],
    )


@feature(
    "bimFabrication.barSchedules",
    "Bar Schedules",
    part="bim",
    fields=[
        number("diameter", "Default bar diameter", 16, unit="mm", min=6),
        number("stockLength", "Stock length", 12.0, unit="m", min=1),
    ],
)
def bar_schedules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Prepare a stock-cut list from recorded reinforcement marks."""
    data = require_bim(ctx)
    marks = data.get("rebar", [])
    records = (
        [
            mark
            for mark in marks
            if isinstance(mark, dict)
            and isinstance(mark.get("lengthM"), (int, float))
            and isinstance(mark.get("quantity"), (int, float))
        ]
        if isinstance(marks, list)
        else []
    )
    if not records:
        raise FeatureInputError(
            "Record rebar marks with lengthM and quantity in the BIM model before scheduling bars."
        )
    rows = [
        {
            "mark": str(mark.get("mark", f"B{i + 1}")),
            "diameterMm": float(mark.get("diameterMm", values["diameter"])),
            "cutLengthM": float(mark["lengthM"]),
            "quantity": int(mark["quantity"]),
            "stockPiecesPerBar": math.ceil(float(mark["lengthM"]) / values["stockLength"]),
        }
        for i, mark in enumerate(records)
    ]
    path = write_bim_csv(
        ctx,
        "bar-schedule.csv",
        ["mark", "diameterMm", "cutLengthM", "quantity", "stockPiecesPerBar"],
        rows,
    )
    return result(
        summary={
            "stockLengthM": values["stockLength"],
            "barMarkCount": len(rows),
            "barCount": sum(row["quantity"] for row in rows),
            "scheduleLineCount": len(rows),
            "exportPath": path,
        },
        tables=[
            table(
                "Bar Schedule",
                [
                    ("mark", "Mark"),
                    ("diameterMm", "Diameter [mm]", "mm"),
                    ("cutLengthM", "Cut length [m]", "m"),
                    ("quantity", "Quantity"),
                    ("stockPiecesPerBar", "Stock pieces per bar"),
                ],
                rows,
            )
        ],
        notes=[
            "Piece counts are based on stock length only; lap allowances and bend deductions are not included.",
            f"Export: {path}",
        ],
    )


@feature(
    "bimFabrication.assemblyMarks",
    "Assembly Marks",
    part="bim",
    fields=[
        text("prefix", "Mark prefix", "A"),
        number("start", "Starting number", 1, unit="ea", min=1),
    ],
)
def assembly_marks(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign shared fabrication marks to identical element (kind, type, length) prototypes."""
    data = require_bim(ctx)
    raw_elems = [e for e in (data.get("elements") or []) if isinstance(e, dict)]
    proto_marks: dict[tuple[str, str], str] = {}
    nxt = int(values["start"])
    rows = []
    for e in raw_elems:
        key = (str(e.get("kind", "")), str(e.get("type", "")))
        if key not in proto_marks:
            proto_marks[key] = f"{values['prefix']}-{nxt:03d}"
            nxt += 1
        rows.append(
            {
                "id": str(e.get("id", "")),
                "kind": key[0],
                "type": key[1],
                "assemblyMark": proto_marks[key],
            }
        )
    path = write_bim_csv(ctx, "assembly-marks.csv", ["id", "kind", "type", "assemblyMark"], rows)
    return result(
        summary={
            "prefix": values["prefix"],
            "uniqueMarks": len(proto_marks),
            "markedElementCount": len(rows),
            "exportPath": path,
        },
        tables=[
            table(
                "Shared Prototype Assembly Marks",
                [("id", "Element"), ("kind", "Kind"), ("type", "Type"), ("assemblyMark", "Mark")],
                rows,
            )
        ],
        notes=[
            f"Grouped {len(rows)} elements into {len(proto_marks)} unique assembly mark(s); saved to {path}."
        ],
    )


@feature(
    "bimFabrication.barClashCheck",
    "Bar Clash Check",
    part="bim",
    fields=[
        number("tolerance", "Clash tolerance", 5, unit="mm", min=0),
        text("barIds", "Bar ids", ""),
    ],
)
def bar_clash_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Find bar centerline pairs whose measured clearance is below the tolerance."""
    data = require_bim(ctx)
    ids = [x.strip() for x in values["barIds"].split(",") if x.strip()]
    geometry = data.get("barGeometry", [])
    bars = (
        [
            row
            for row in geometry
            if isinstance(row, dict)
            and row.get("id")
            and isinstance(row.get("start"), list)
            and len(row["start"]) == 3
            and isinstance(row.get("end"), list)
            and len(row["end"]) == 3
            and all(isinstance(value, (int, float)) for value in row["start"] + row["end"])
        ]
        if isinstance(geometry, list)
        else []
    )
    if not bars:
        raise FeatureInputError(
            "Record barGeometry entries with id, start, and end coordinates in millimetres first."
        )
    if ids:
        bars = [bar for bar in bars if str(bar["id"]) in ids]
    if len(bars) < 2:
        raise FeatureInputError("Select at least two bars with recorded 3D geometry.")
    rows = []
    for index, bar_a in enumerate(bars):
        for bar_b in bars[index + 1 :]:
            clearance = _segment_clearance(
                bar_a["start"], bar_a["end"], bar_b["start"], bar_b["end"]
            )
            if clearance <= values["tolerance"]:
                rows.append(
                    {
                        "barA": str(bar_a["id"]),
                        "barB": str(bar_b["id"]),
                        "clearanceMm": clearance,
                    }
                )
    path = write_bim_csv(ctx, "bar-clash-check.csv", ["barA", "barB", "clearanceMm"], rows)
    return result(
        summary={
            "barCount": len(bars),
            "clashPairCount": len(rows),
            "toleranceMm": values["tolerance"],
            "exportPath": path,
        },
        tables=[
            table(
                "Bar Clearance Violations",
                [
                    ("barA", "Bar A"),
                    ("barB", "Bar B"),
                    ("clearanceMm", "Measured clearance", "mm"),
                ],
                rows,
            )
        ],
        notes=[f"Measured centerline clearance violations written to {path}."],
    )


@feature(
    "bimFabrication.bendFeasibility",
    "Bend Feasibility",
    part="bim",
    fields=[
        number("diameter", "Bar diameter", 16, unit="mm", min=6),
        number("insideRadius", "Inside bend radius", 64, unit="mm", min=1),
        number("stockLength", "Stock length", 12.0, unit="m", min=1),
        number("minimumRadiusRatio", "Minimum radius-to-diameter ratio", 2.0, unit="ratio", min=0),
    ],
)
def bend_feasibility(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Checks whether a bar bend fits planning limits."""
    require_bim(ctx)
    ratio = values["insideRadius"] / values["diameter"]
    feasible = ratio >= values["minimumRadiusRatio"]
    return result(
        summary={
            "diameterMm": values["diameter"],
            "insideRadiusMm": values["insideRadius"],
            "radiusToDiameter": ratio,
            "feasible": feasible,
            "stockLengthM": values["stockLength"],
        },
        notes=["The minimum radius-to-diameter ratio is supplied for the project or machine."],
    )


@feature(
    "bimFabrication.barLengthCheck",
    "Bar Length Check",
    part="bim",
    fields=[
        number("barLength", "Bar length", 12.5, unit="m", min=0.1),
        number("stockLength", "Stock length", 12.0, unit="m", min=0.1),
        number("lapLength", "Lap length", 0.5, unit="m", min=0),
    ],
)
def bar_length_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Checks a proposed bar length against stock and lap assumptions."""
    require_bim(ctx)
    if values["lapLength"] >= values["stockLength"] and values["barLength"] > values["stockLength"]:
        raise FeatureInputError("Lap length must be shorter than stock length for a spliced bar.")
    joints = (
        0
        if values["barLength"] <= values["stockLength"]
        else max(
            1,
            math.ceil(
                (values["barLength"] - values["lapLength"])
                / (values["stockLength"] - values["lapLength"])
            )
            - 1,
        )
    )
    return result(
        summary={
            "requiredLengthM": values["barLength"],
            "stockLengthM": values["stockLength"],
            "lapLengthM": values["lapLength"],
            "lapJointCount": joints,
            "stockPieceCount": joints + 1,
        },
        notes=["Stock-splicing is a geometry check; structural lap capacity is not assessed."],
    )


@feature(
    "bimFabrication.lapVerification",
    "Lap Verification",
    part="bim",
    fields=[
        number("providedLap", "Provided lap", 600, unit="mm", min=0),
        number("requiredLap", "Required lap", 500, unit="mm", min=0),
    ],
)
def lap_verification(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verifies a supplied lap length against a calculated requirement."""
    require_bim(ctx)
    pass_check = values["providedLap"] >= values["requiredLap"]
    reserve = values["providedLap"] - values["requiredLap"]
    return result(
        summary={
            "providedLapMm": values["providedLap"],
            "requiredLapMm": values["requiredLap"],
            "reserveMm": reserve,
            "passes": pass_check,
        },
        notes=[
            "Lap verification compares geometric values; the required lap must come from the project detailing rules."
        ],
    )


@feature(
    "bimFabrication.toleranceReport",
    "Tolerance Report",
    part="bim",
    fields=[
        number("positionTolerance", "Position tolerance", 10, unit="mm", min=0),
        number("measuredDeviation", "Measured deviation", 7, unit="mm", min=0),
    ],
)
def tolerance_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Reports a field tolerance check."""
    require_bim(ctx)
    pass_check = values["measuredDeviation"] <= values["positionTolerance"]
    return result(
        summary={
            "positionToleranceMm": values["positionTolerance"],
            "measuredDeviationMm": values["measuredDeviation"],
            "passes": pass_check,
        },
        notes=["Absolute deviation is compared with the supplied position tolerance."],
    )


@feature(
    "bimFabrication.deliverySequence",
    "Delivery Sequence",
    part="bim",
    fields=[
        number("itemCount", "Items", 40, unit="ea", min=1),
        number("itemsPerTrip", "Items per trip", 8, unit="ea", min=1),
    ],
)
def delivery_sequence(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Plans fabrication delivery trips."""
    require_bim(ctx)
    count = int(values["itemCount"])
    per = int(values["itemsPerTrip"])
    trips = (count + per - 1) // per
    rows = [{"trip": i + 1, "itemCount": min(per, count - i * per)} for i in range(trips)]
    path = write_bim_csv(ctx, "delivery-sequence.csv", ["trip", "itemCount"], rows)
    return result(
        summary={"itemCount": count, "itemsPerTrip": per, "tripCount": trips, "exportPath": path},
        tables=[table("Delivery Sequence", [("trip", "Trip"), ("itemCount", "Items")], rows)],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimFabrication.packagingLists",
    "Packaging Lists",
    part="bim",
    fields=[
        number("itemCount", "Item count", 100, unit="ea", min=1),
        number("itemsPerPackage", "Items per package", 20, unit="ea", min=1),
    ],
)
def packaging_lists(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates package quantities for fabrication items."""
    require_bim(ctx)
    count = int(values["itemCount"])
    per = int(values["itemsPerPackage"])
    package_count = (count + per - 1) // per
    rows = [
        {"package": i + 1, "itemCount": min(per, count - i * per)} for i in range(package_count)
    ]
    path = write_bim_csv(ctx, "packaging-list.csv", ["package", "itemCount"], rows)
    return result(
        summary={
            "itemCount": count,
            "packageCount": package_count,
            "itemsPerPackage": per,
            "exportPath": path,
        },
        tables=[table("Packaging List", [("package", "Package"), ("itemCount", "Items")], rows)],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimFabrication.siteStoragePlan",
    "Site Storage Plan",
    part="bim",
    fields=[
        number("itemCount", "Stored items", 100, unit="ea", min=1),
        number("areaPerItem", "Area per item", 0.5, unit="m²", min=0.01),
        number("reserveFactor", "Storage reserve", 1.2, unit="x", min=1),
    ],
)
def site_storage_plan(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimates site storage area."""
    require_bim(ctx)
    area = values["itemCount"] * values["areaPerItem"] * values["reserveFactor"]
    return result(
        summary={
            "itemCount": int(values["itemCount"]),
            "requiredAreaM2": area,
            "reserveFactor": values["reserveFactor"],
        },
        notes=[
            "Net storage area includes aisles only through the reserve factor; circulation and lifting zones are not otherwise checked."
        ],
    )


@feature(
    "bimFabrication.installSequence",
    "Install Sequence",
    part="bim",
    fields=[
        number("itemCount", "Installation items", 30, unit="ea", min=1),
        number("crewSize", "Crew size", 4, unit="ea", min=1),
        number("rate", "Items per crew-hour", 2.0, unit="ea/h", min=0.1),
    ],
)
def install_sequence(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimates an installation sequence duration."""
    require_bim(ctx)
    hours = values["itemCount"] / values["rate"]
    crew_hours = hours / values["crewSize"]
    return result(
        summary={
            "itemCount": int(values["itemCount"]),
            "crewSize": int(values["crewSize"]),
            "estimatedDurationH": crew_hours,
            "itemsPerCrewHour": values["rate"],
        },
        notes=[
            "Duration assumes uninterrupted work and independent item production; access constraints are excluded."
        ],
    )


@feature(
    "bimFabrication.transportLoading",
    "Transport Loading",
    part="bim",
    fields=[
        number("itemCount", "Items", 40, unit="ea", min=1),
        number("itemWeight", "Weight per item", 0.5, unit="t", min=0.01),
        number("payload", "Vehicle payload", 12.0, unit="t", min=0.1),
    ],
)
def transport_loading(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Plans vehicles from item count and payload."""
    require_bim(ctx)
    total = values["itemCount"] * values["itemWeight"]
    vehicles = (total + values["payload"] - 1) / values["payload"]
    return result(
        summary={
            "itemCount": int(values["itemCount"]),
            "totalWeightT": total,
            "vehiclePayloadT": values["payload"],
            "estimatedVehicleCount": int(vehicles),
        },
        notes=[
            "Vehicle count is rounded upward from payload only; dimensions and axle limits are not checked."
        ],
    )

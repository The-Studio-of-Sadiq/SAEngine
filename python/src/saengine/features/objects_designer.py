"""Objects - Section Designer tab: fibre canvas, bar placement, M-kappa, P-M-M, DXF & schedules."""

from __future__ import annotations

import math
from typing import Any

from saengine.codes.bars import bar_mass
from saengine.design.bars import diameters
from saengine.design.rc import InteractionSurface
from saengine.design.rc_detailing import concrete_modulus
from saengine.design.torsion import (
    TorsionSection,
    cracking_torsion,
    design_torsion,
    threshold_torsion,
)
from saengine.drawings.bbs import standard as bbs_standard
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
from saengine.features.objects_common import (
    materials_or_default,
    parse_bars_spec,
    parse_points,
    perimeter_bars_rect,
    rect_outline,
    require_root,
    resolve_or_build_section,
    safe_json,
    save_export,
)
from saengine.library.section_capacity import (
    PlasticSection,
    fibres,
    moment_curvature,
    rc_contour,
)
from saengine.library.section_designer import (
    Bar,
    DesignedRcSection,
    DesignedSection,
    Region,
    geometry_problems,
    list_sections,
    properties,
    save_section,
)
from saengine.report.clauses import in_force


@feature(
    "objDesigner.sectionCanvas",
    "Section Canvas",
    part="objects",
    fields=[
        text("sectionId", "Project section ID (blank = outline input)", ""),
        text("outlinePts", "Outline x,y [mm] (CCW)", "-200,-300\n200,-300\n200,300\n-200,300"),
        text(
            "barsSpec",
            "Bars x,y,dia [mm] (optional)",
            "-140,-240,20\n140,-240,20\n-140,240,20\n140,240,20",
        ),
    ],
    requires_project=False,
)
def section_canvas(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate and inspect arbitrary polygonal section geometry and bar coordinates on the canvas."""
    sid = values["sectionId"].strip()
    mats, _ = materials_or_default(ctx)
    conc = next((m.id for m in mats.materials if m.category.value == "concrete"), "C24.1")
    reb = next((m.id for m in mats.materials if m.category.value == "rebar"), "B420DWR")
    if sid and ctx.root is not None and sid in list_sections(ctx.root):
        sec, mats, src = resolve_or_build_section(ctx, sid)
    else:
        pts = parse_points(values["outlinePts"], "Section outline")
        bars_raw = parse_bars_spec(values["barsSpec"]) if values["barsSpec"].strip() else []
        sec = DesignedSection(
            id=sid or "CANVAS-1",
            name=sid or "Canvas Section",
            regions=[Region(outline=pts, material=conc, label="Main")],
            bars=[Bar(x=x, y=y, dia=d) for x, y, d in bars_raw],
            rebar=reb if bars_raw else None,
        )
        src = "Canvas outline"
    with in_force(ctx.root):
        props = properties(sec, mats)
    rows = [
        {"vertex": i + 1, "xMm": x, "yMm": y} for i, (x, y) in enumerate(sec.regions[0].outline)
    ]
    return result(
        summary={
            "source": src,
            "regionCount": len(sec.regions),
            "barCount": len(sec.bars),
            "areaMm2": props.area,
            "centroidXMm": props.cx,
            "centroidYMm": props.cy,
        },
        tables=[
            table(
                "Canvas primary region vertices",
                [("vertex", "Vertex"), ("xMm", "x", "mm"), ("yMm", "y", "mm")],
                rows,
            )
        ],
        notes=[
            "Validates non-overlapping regions and bar containment before property/fibre integration."
        ],
    )


@feature(
    "objDesigner.addShape",
    "Add Shape",
    part="objects",
    fields=[
        select(
            "shape",
            "Primitive shape",
            [
                ("rectangle", "Rectangle"),
                ("circle", "Circle"),
                ("hollowRect", "Rectangle with void"),
            ],
            "rectangle",
        ),
        number("widthMm", "Width / diameter", 500.0, unit="mm", min=40.0),
        number("depthMm", "Depth", 500.0, unit="mm", min=40.0),
        number("voidWidthMm", "Void width (hollowRect)", 200.0, unit="mm", min=0.0),
        number("voidDepthMm", "Void depth (hollowRect)", 200.0, unit="mm", min=0.0),
        number("offsetXMm", "Centre X", 0.0, unit="mm"),
        number("offsetYMm", "Centre Y", 0.0, unit="mm"),
    ],
    requires_project=False,
)
def add_shape(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a polygonal region (rectangle, circle, or hollow polygon) for the section canvas."""
    shape = values["shape"]
    w, d = values["widthMm"], values["depthMm"]
    cx, cy = values["offsetXMm"], values["offsetYMm"]
    holes: list[list[tuple[float, float]]] = []
    if shape == "circle":
        r = w / 2.0
        outline = [
            (
                round(cx + r * math.cos(2 * math.pi * i / 32), 2),
                round(cy + r * math.sin(2 * math.pi * i / 32), 2),
            )
            for i in range(32)
        ]
    else:
        outline = rect_outline(w, d, cx, cy)
        if shape == "hollowRect":
            vw, vd = values["voidWidthMm"], values["voidDepthMm"]
            if vw >= w or vd >= d or vw <= 0 or vd <= 0:
                raise FeatureInputError(
                    "Void dimensions must be positive and smaller than outer dimensions."
                )
            holes.append(rect_outline(vw, vd, cx, cy))

    mats, _ = materials_or_default(ctx)
    conc = next((m.id for m in mats.materials if m.category.value == "concrete"), "C24.1")
    sec = DesignedSection(
        id="SHAPE-1",
        name=f"Added {shape}",
        regions=[Region(outline=outline, holes=holes, material=conc, label=shape)],
    )
    problems = geometry_problems(sec)
    if problems:
        raise FeatureInputError("; ".join(problems))
    with in_force(ctx.root):
        props = properties(sec, mats)
    rows = [{"index": i + 1, "xMm": x, "yMm": y} for i, (x, y) in enumerate(outline[:8])]
    return result(
        summary={
            "shape": shape,
            "vertexCount": len(outline),
            "holeCount": len(holes),
            "areaMm2": props.area,
            "ixxMm4": props.ixx,
            "iyyMm4": props.iyy,
        },
        tables=[
            table(
                "Generated shape outline (first vertices)",
                [("index", "Vertex"), ("xMm", "x", "mm"), ("yMm", "y", "mm")],
                rows,
            )
        ],
        notes=["Polygon validated with Shapely/sectionproperties geometry checks."],
    )


@feature(
    "objDesigner.drawFibre",
    "Draw Fibre",
    part="objects",
    fields=[
        text("sectionId", "Project section ID (blank = parametric)", ""),
        number("widthMm", "Width", 400.0, unit="mm", min=100.0),
        number("depthMm", "Depth", 600.0, unit="mm", min=100.0),
        number("refinement", "Mesh refinement factor", 1.0, min=0.25, max=4.0),
    ],
    requires_project=False,
)
def draw_fibre(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Discretize a section into triangular concrete fibres and point steel fibres."""
    sec, mats, src = resolve_or_build_section(
        ctx, values["sectionId"], width_mm=values["widthMm"], depth_mm=values["depthMm"]
    )
    with in_force(ctx.root):
        fib = fibres(sec, mats, refine=values["refinement"])
    n_conc = int(fib.concrete.sum())
    n_steel = int(fib.steel.sum())
    a_conc = float(fib.area[fib.concrete].sum()) if n_conc else 0.0
    a_steel = float(fib.area[fib.steel].sum()) if n_steel else 0.0
    sample_rows = [
        {
            "fibre": i + 1,
            "material": "Concrete" if fib.kind[i] == 0 else "Steel",
            "xMm": float(fib.x[i]),
            "yMm": float(fib.y[i]),
            "areaMm2": float(fib.area[i]),
        }
        for i in range(min(12, len(fib.x)))
    ]
    return result(
        summary={
            "source": src,
            "totalFibres": len(fib.x),
            "concreteFibres": n_conc,
            "steelFibres": n_steel,
            "concreteNetAreaMm2": a_conc,
            "steelAreaMm2": a_steel,
        },
        tables=[
            table(
                "Sample discretised fibres",
                [
                    ("fibre", "Fibre"),
                    ("material", "Material"),
                    ("xMm", "x", "mm"),
                    ("yMm", "y", "mm"),
                    ("areaMm2", "Area", "mm2"),
                ],
                sample_rows,
            )
        ],
        notes=["Concrete displaced by embedded bars is subtracted using negative-area fibres."],
    )


@feature(
    "objDesigner.snapGrid",
    "Snap & Grid",
    part="objects",
    fields=[
        number("gridStepMm", "Snap grid step", 10.0, unit="mm", min=1.0),
        number("xMm", "Raw X coordinate", 143.7, unit="mm"),
        number("yMm", "Raw Y coordinate", -236.2, unit="mm"),
        number("widthMm", "Canvas width", 600.0, unit="mm", min=50.0),
        number("depthMm", "Canvas height", 800.0, unit="mm", min=50.0),
    ],
    requires_project=False,
)
def snap_grid(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Snap section coordinates to a regular canvas grid and report grid division counts."""
    step = values["gridStepMm"]
    sx = round(values["xMm"] / step) * step
    sy = round(values["yMm"] / step) * step
    nx = int(values["widthMm"] // step) + 1
    ny = int(values["depthMm"] // step) + 1
    rows = [
        {"axis": "X", "rawMm": values["xMm"], "snappedMm": sx, "offsetMm": sx - values["xMm"]},
        {"axis": "Y", "rawMm": values["yMm"], "snappedMm": sy, "offsetMm": sy - values["yMm"]},
    ]
    return result(
        summary={
            "gridStepMm": step,
            "snappedXMm": sx,
            "snappedYMm": sy,
            "gridLinesX": nx,
            "gridLinesY": ny,
        },
        tables=[
            table(
                "Snapped coordinates",
                [
                    ("axis", "Axis"),
                    ("rawMm", "Raw", "mm"),
                    ("snappedMm", "Snapped", "mm"),
                    ("offsetMm", "Snap delta", "mm"),
                ],
                rows,
            )
        ],
        notes=["Snaps coordinates to nearest integer multiple of the canvas grid step."],
    )


@feature(
    "objDesigner.placeBars",
    "Place Bars",
    part="objects",
    fields=[
        number("widthMm", "Section width", 400.0, unit="mm", min=100.0),
        number("depthMm", "Section depth", 600.0, unit="mm", min=100.0),
        text(
            "barsSpec",
            "Bars x,y,dia [mm]",
            "-140,-240,20\n0,-240,20\n140,-240,20\n-140,240,20\n0,240,20\n140,240,20",
        ),
    ],
    requires_project=False,
)
def place_bars(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Place longitudinal bars at exact coordinates, validate concrete cover, and compute steel centroid."""
    w, h = values["widthMm"], values["depthMm"]
    parsed = parse_bars_spec(values["barsSpec"])
    mats, _ = materials_or_default(ctx)
    conc = next((m.id for m in mats.materials if m.category.value == "concrete"), "C24.1")
    reb = next((m.id for m in mats.materials if m.category.value == "rebar"), "B420DWR")
    sec = DesignedSection(
        id="PLACE-BARS",
        name="Placed Bars Section",
        regions=[Region(outline=rect_outline(w, h), material=conc)],
        bars=[Bar(x=x, y=y, dia=d) for x, y, d in parsed],
        rebar=reb,
    )
    problems = geometry_problems(sec)
    if problems:
        raise FeatureInputError("; ".join(problems))
    rows = []
    tot_a = 0.0
    sx = sy = 0.0
    for i, b in enumerate(sec.bars, 1):
        a = math.pi * b.dia**2 / 4.0
        cov_edge = min(w / 2.0 - abs(b.x), h / 2.0 - abs(b.y)) - b.dia / 2.0
        tot_a += a
        sx += a * b.x
        sy += a * b.y
        rows.append(
            {
                "bar": i,
                "xMm": b.x,
                "yMm": b.y,
                "diaMm": b.dia,
                "areaMm2": a,
                "clearCoverMm": cov_edge,
            }
        )
    return result(
        summary={
            "barCount": len(sec.bars),
            "totalSteelMm2": tot_a,
            "steelRatio": tot_a / (w * h),
            "minClearCoverMm": min(r["clearCoverMm"] for r in rows),
            "steelCentroidXMm": sx / tot_a,
            "steelCentroidYMm": sy / tot_a,
        },
        tables=[
            table(
                "Placed reinforcing bars",
                [
                    ("bar", "Bar"),
                    ("xMm", "x", "mm"),
                    ("yMm", "y", "mm"),
                    ("diaMm", "Dia", "mm"),
                    ("areaMm2", "Area", "mm2"),
                    ("clearCoverMm", "Clear cover", "mm"),
                ],
                rows,
            )
        ],
        notes=["Clear cover is measured from the bar outer edge to the nearest concrete face."],
    )


@feature(
    "objDesigner.barLayout",
    "Bar Layout",
    part="objects",
    fields=[
        number("widthMm", "Section width", 400.0, unit="mm", min=100.0),
        number("depthMm", "Section depth", 600.0, unit="mm", min=100.0),
        number("coverMm", "Clear cover", 40.0, unit="mm", min=15.0),
        number("diaMm", "Bar diameter", 20.0, unit="mm", min=8.0),
        number("nx", "Bars along X faces", 3.0, min=2.0),
        number("ny", "Bars along Y faces", 4.0, min=2.0),
    ],
    requires_project=False,
)
def bar_layout(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Distribute longitudinal bars uniformly around the perimeter of a rectangular section."""
    pts = perimeter_bars_rect(
        values["widthMm"],
        values["depthMm"],
        values["coverMm"],
        values["diaMm"],
        round(values["nx"]),
        round(values["ny"]),
    )
    a_one = math.pi * values["diaMm"] ** 2 / 4.0
    tot_a = len(pts) * a_one
    xs = sorted({x for x, _, _ in pts})
    ys = sorted({y for _, y, _ in pts})
    clear_x = (xs[-1] - xs[0]) / max(1, round(values["nx"]) - 1) - values["diaMm"]
    clear_y = (ys[-1] - ys[0]) / max(1, round(values["ny"]) - 1) - values["diaMm"]
    rows = [{"index": i + 1, "xMm": x, "yMm": y, "diaMm": d} for i, (x, y, d) in enumerate(pts)]
    return result(
        summary={
            "barCount": len(pts),
            "totalSteelMm2": tot_a,
            "steelRatio": tot_a / (values["widthMm"] * values["depthMm"]),
            "clearSpacingXMm": clear_x,
            "clearSpacingYMm": clear_y,
        },
        tables=[
            table(
                "Perimeter bar coordinates",
                [("index", "Bar"), ("xMm", "x", "mm"), ("yMm", "y", "mm"), ("diaMm", "Dia", "mm")],
                rows,
            )
        ],
        notes=["Assumes 10 mm transverse tie allowance outside the longitudinal bars."],
    )


@feature(
    "objDesigner.stirrups",
    "Stirrups",
    part="objects",
    fields=[
        number("widthMm", "Section width b", 350.0, unit="mm", min=100.0),
        number("depthMm", "Section depth h", 500.0, unit="mm", min=100.0),
        number("coverMm", "Clear cover", 40.0, unit="mm", min=15.0),
        number("tieDiaMm", "Stirrup/tie diameter", 10.0, unit="mm", min=6.0),
        number("spacingMm", "Centre-to-centre spacing s", 150.0, unit="mm", min=40.0),
        number("legsX", "Legs resisting shear along X", 2.0, min=2.0),
        number("legsY", "Legs resisting shear along Y", 2.0, min=2.0),
    ],
    requires_project=False,
)
def stirrups_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define closed hoops, links and crossties and compute shear area ratio Av/s and confinement Ash."""
    b, h, cc = values["widthMm"], values["depthMm"], values["coverMm"]
    dt, s = values["tieDiaMm"], values["spacingMm"]
    lx, ly = round(values["legsX"]), round(values["legsY"])
    bc = b - 2.0 * cc
    hc = h - 2.0 * cc
    if bc <= 0 or hc <= 0:
        raise FeatureInputError("Cover exceeds section half-dimensions.")
    a_leg = math.pi * dt**2 / 4.0
    av_x = lx * a_leg
    av_y = ly * a_leg
    ash_x_ratio = av_x / (s * hc)
    ash_y_ratio = av_y / (s * bc)
    # Hoop centre-line + two 10*dt 135-deg hooks
    perim_len = 2.0 * (bc - dt + hc - dt) + 2.0 * max(75.0, 10.0 * dt)
    crosstie_len_x = (bc - dt) + 2.0 * max(75.0, 10.0 * dt)
    crosstie_len_y = (hc - dt) + 2.0 * max(75.0, 10.0 * dt)
    rows = [
        {"metric": "Core width bc (out-to-out)", "value": bc, "unit": "mm"},
        {"metric": "Core depth hc (out-to-out)", "value": hc, "unit": "mm"},
        {"metric": "Av/s along X", "value": av_x / s, "unit": "mm2/mm"},
        {"metric": "Av/s along Y", "value": av_y / s, "unit": "mm2/mm"},
        {"metric": "Confinement ratio Ash/(s*hc)", "value": ash_x_ratio * 100.0, "unit": "%"},
        {"metric": "Confinement ratio Ash/(s*bc)", "value": ash_y_ratio * 100.0, "unit": "%"},
        {"metric": "Outer hoop cut length", "value": perim_len, "unit": "mm"},
        {
            "metric": "Extra crosstie length (X / Y)",
            "value": max(crosstie_len_x, crosstie_len_y),
            "unit": "mm",
        },
    ]
    return result(
        summary={
            "coreAreaMm2": bc * hc,
            "avPerSX": av_x / s,
            "avPerSY": av_y / s,
            "confinementRatioX": ash_x_ratio,
            "confinementRatioY": ash_y_ratio,
            "hoopLengthMm": perim_len,
        },
        tables=[
            table(
                "Transverse tie & confinement summary",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Hook extensions take max(75 mm, 10*db) for 135-degree seismic hooks."],
    )


@feature(
    "objDesigner.barLibrary",
    "Bar Library",
    part="objects",
    fields=[
        select(
            "usage",
            "Bar usage group",
            [
                ("all", "All bars"),
                ("main", "Main beam/column"),
                ("slab", "Slab"),
                ("stirrup", "Stirrups/ties"),
            ],
            "all",
        ),
    ],
    requires_project=False,
)
def bar_library(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List standard bar sizes, areas, nominal unit masses, and available bend shapes."""
    with in_force(ctx.root):
        dias = diameters(values["usage"])
        std = bbs_standard()
        rows = [
            {
                "diaMm": d,
                "areaMm2": math.pi * d**2 / 4.0,
                "massKgPerM": bar_mass(d),
                "minBendRadiusMm": float(std.radius.bySize.get(f"{d:g}", 2.0 * d)),
            }
            for d in dias
        ]
    return result(
        summary={
            "barSizeCount": len(rows),
            "scheduleStandard": std.name,
            "shapeCodeCount": len(std.shapes),
        },
        tables=[
            table(
                f"Standard bar sizes ({values['usage']})",
                [
                    ("diaMm", "Diameter", "mm"),
                    ("areaMm2", "Area", "mm2"),
                    ("massKgPerM", "Unit mass", "kg/m"),
                    ("minBendRadiusMm", "Min radius", "mm"),
                ],
                rows,
            )
        ],
        notes=[f"Bar sizes and schedule standard ({std.name}) are read from the active code pack."],
    )


@feature(
    "objDesigner.momentCurvature",
    "Moment Curvature",
    part="objects",
    fields=[
        text("sectionId", "Project section ID (blank = parametric)", ""),
        number("widthMm", "Width", 400.0, unit="mm", min=100.0),
        number("depthMm", "Depth", 600.0, unit="mm", min=100.0),
        number("axialKn", "Axial load P (compression +)", 400.0, unit="kN"),
        number("angleDeg", "Bending angle theta", 0.0, unit="deg", min=-180.0, max=180.0),
        checkbox("includeTension", "Include concrete tension stiffening", True),
    ],
    requires_project=False,
)
def moment_curvature_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute the nonlinear moment-curvature curve and ductility using Hognestad concrete and elastic-plastic steel."""
    sec, mats, src = resolve_or_build_section(
        ctx, values["sectionId"], width_mm=values["widthMm"], depth_mm=values["depthMm"]
    )
    with in_force(ctx.root):
        mc = moment_curvature(
            sec,
            mats,
            axial=values["axialKn"] * 1e3,
            theta=math.radians(values["angleDeg"]),
            tension=values["includeTension"],
        )
    pts = mc["points"]
    step = max(1, len(pts) // 12)
    sample = [
        {
            "kappaPerM": p["kappa"] * 1e3,
            "momentKnm": p["M"] / 1e6,
            "epsC": p["epsC"],
            "epsS": p["epsS"],
            "naDepthMm": p["c"],
        }
        for p in pts[::step]
    ]
    if pts and pts[-1] not in pts[::step]:
        p = pts[-1]
        sample.append(
            {
                "kappaPerM": p["kappa"] * 1e3,
                "momentKnm": p["M"] / 1e6,
                "epsC": p["epsC"],
                "epsS": p["epsS"],
                "naDepthMm": p["c"],
            }
        )
    yld = mc.get("yield")
    ult = mc["ultimate"]
    return result(
        summary={
            "source": src,
            "endReason": mc["end"],
            "yieldMomentKnm": (yld["M"] / 1e6) if yld else 0.0,
            "peakMomentKnm": mc["peak"]["M"] / 1e6,
            "ultimateMomentKnm": ult["M"] / 1e6,
            "ultimateCurvaturePerM": ult["kappa"] * 1e3,
            "eiEffKnM2": (mc["EIeff"] / 1e9) if mc["EIeff"] else 0.0,
            "curvatureDuctility": mc["ductility"] or 0.0,
        },
        tables=[
            table(
                "Moment-curvature response",
                [
                    ("kappaPerM", "Curvature", "1/m"),
                    ("momentKnm", "Moment", "kN-m"),
                    ("epsC", "Max concrete strain"),
                    ("epsS", "Extreme steel strain"),
                    ("naDepthMm", "NA depth c", "mm"),
                ],
                sample,
            )
        ],
        notes=[
            "Uses fibre equilibrium with Hognestad parabolic-linear concrete and bilinear equal-energy ductility."
        ],
    )


@feature(
    "objDesigner.interactionDiagram",
    "Interaction Diagram",
    part="objects",
    fields=[
        text("sectionId", "Project section ID (blank = parametric)", ""),
        number("widthMm", "Width", 400.0, unit="mm", min=100.0),
        number("depthMm", "Depth", 600.0, unit="mm", min=100.0),
        select("axis", "Bending axis", [("x", "Major X (Mx)"), ("y", "Minor Y (My)")], "x"),
    ],
    requires_project=False,
)
def interaction_diagram(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute the uniaxial P-M interaction diagram for an RC or steel designed section."""
    sec, mats, src = resolve_or_build_section(
        ctx, values["sectionId"], width_mm=values["widthMm"], depth_mm=values["depthMm"]
    )
    with in_force(ctx.root):
        has_conc = any(
            mats.get(r.material) and mats.get(r.material).category.value == "concrete"
            for r in sec.regions
        )
        if has_conc:
            rc_sec = DesignedRcSection(sec, mats)
            surf = InteractionSurface(rc_sec)
            theta = 0.0 if values["axis"] == "x" else -math.pi / 2.0
            mer = rc_sec.meridian(theta, count=14)
            phi_pn_max = rc_sec.phi_pn_max
            phi_tension = rc_sec.phi_tension
            del surf
        else:
            psec = PlasticSection(sec, mats)
            uni = psec.uniaxial(values["axis"], count=14)
            mer = [
                {
                    "P": p["P"],
                    "Mx": p["M"],
                    "My": p["M"],
                    "phiPcapped": p["phiP"],
                    "phiMx": p["phiM"],
                    "phiMy": p["phiM"],
                    "phi": p["phi"],
                }
                for p in uni["points"][:14]
            ]
            phi_pn_max = uni["phiPnMax"]
            phi_tension = uni["phiTension"]

    m_key = "Mx" if values["axis"] == "x" else "My"
    phi_m_key = "phiMx" if values["axis"] == "x" else "phiMy"
    rows = [
        {
            "pnKn": r["P"] / 1e3,
            "mnKnm": r[m_key] / 1e6,
            "phiPnKn": r["phiPcapped"] / 1e3,
            "phiMnKnm": r[phi_m_key] / 1e6,
            "phi": r["phi"],
        }
        for r in mer
    ]
    return result(
        summary={
            "source": src,
            "phiPnMaxKn": phi_pn_max / 1e3,
            "phiTensionKn": phi_tension / 1e3,
            "maxDesignMomentKnm": max(abs(r["phiMnKnm"]) for r in rows),
            "pointCount": len(rows),
        },
        tables=[
            table(
                f"P-M interaction curve (axis {values['axis'].upper()})",
                [
                    ("pnKn", "Pn", "kN"),
                    ("mnKnm", "Mn", "kN-m"),
                    ("phiPnKn", "phi*Pn", "kN"),
                    ("phiMnKnm", "phi*Mn", "kN-m"),
                    ("phi", "phi"),
                ],
                rows,
            )
        ],
        notes=["Strength reduction factors phi are read from the active code pack."],
    )


@feature(
    "objDesigner.crackedSection",
    "Cracked Section",
    part="objects",
    fields=[
        number("widthMm", "Width b", 300.0, unit="mm", min=100.0),
        number("depthMm", "Depth h", 500.0, unit="mm", min=100.0),
        number("dMm", "Effective depth d", 440.0, unit="mm", min=50.0),
        number("asMm2", "Tension steel As", 1256.0, unit="mm2", min=50.0),
        number("asCompMm2", "Compression steel As'", 402.0, unit="mm2", min=0.0),
        number("dCompMm", "Compression steel depth d'", 55.0, unit="mm", min=20.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=10.0),
    ],
    requires_project=False,
)
def cracked_section(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute cracked transformed neutral axis depth kd, cracked inertia Icr, and cracking moment Mcr."""
    b, h, d = values["widthMm"], values["depthMm"], values["dMm"]
    if d >= h:
        raise FeatureInputError("Effective depth d must be less than overall depth h.")
    as_t, as_c, dc = values["asMm2"], values["asCompMm2"], values["dCompMm"]
    with in_force(ctx.root):
        ec, _ = concrete_modulus(values["fcMpa"])
    es = 200000.0
    n = es / ec
    # Quadratic: 0.5*b*c^2 + (n*As + (n-1)*As')*c - (n*As*d + (n-1)*As'*d') = 0
    a_q = 0.5 * b
    b_q = n * as_t + max(0.0, n - 1.0) * as_c
    c_q = -(n * as_t * d + max(0.0, n - 1.0) * as_c * dc)
    kd = (-b_q + math.sqrt(b_q**2 - 4.0 * a_q * c_q)) / (2.0 * a_q)
    icr = b * kd**3 / 3.0 + n * as_t * (d - kd) ** 2 + max(0.0, n - 1.0) * as_c * (kd - dc) ** 2
    ig = b * h**3 / 12.0
    fr = 0.62 * math.sqrt(values["fcMpa"])
    mcr_knm = fr * ig / (h / 2.0) / 1e6
    rows = [
        {"metric": "Modular ratio n = Es/Ec", "value": n, "unit": "-"},
        {"metric": "Gross inertia Ig", "value": ig, "unit": "mm4"},
        {"metric": "Cracked neutral axis kd", "value": kd, "unit": "mm"},
        {"metric": "Cracked inertia Icr", "value": icr, "unit": "mm4"},
        {"metric": "Stiffness ratio Icr / Ig", "value": icr / ig, "unit": "-"},
        {"metric": "Cracking moment Mcr", "value": mcr_knm, "unit": "kN-m"},
    ]
    return result(
        summary={
            "modularRatio": n,
            "neutralAxisMm": kd,
            "icrMm4": icr,
            "igMm4": ig,
            "icrOverIg": icr / ig,
            "crackingMomentKnm": mcr_knm,
        },
        tables=[
            table(
                "Cracked section stiffness properties",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Transformed-section elastic analysis neglecting concrete in tension below neutral axis."
        ],
    )


@feature(
    "objDesigner.torsionCheck",
    "Torsion Check",
    part="objects",
    fields=[
        number("widthMm", "Width b", 350.0, unit="mm", min=100.0),
        number("depthMm", "Depth h", 550.0, unit="mm", min=100.0),
        number("coverMm", "Clear cover to closed stirrup", 40.0, unit="mm", min=15.0),
        number("tuKnm", "Factored torsion Tu", 25.0, unit="kN-m", min=0.0),
        number("vuKn", "Factored shear Vu", 120.0, unit="kN", min=0.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=10.0),
        number("fyMpa", "Longitudinal steel fy", 420.0, unit="MPa", min=200.0),
        number("fytMpa", "Stirrup steel fyt", 420.0, unit="MPa", min=200.0),
    ],
    requires_project=False,
)
def torsion_check_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check torsional threshold, cracking torque, and closed-stirrup / longitudinal torsion demand."""
    b, h, cc = values["widthMm"], values["depthMm"], values["coverMm"]
    tsec = TorsionSection(b=b, h=h, cover=cc, stirrup_dia=10.0, d=h - cc - 20.0)
    with in_force(ctx.root):
        t_th = threshold_torsion(tsec, values["fcMpa"])
        t_cr = cracking_torsion(tsec, values["fcMpa"])
        des = design_torsion(
            tsec,
            values["tuKnm"] * 1e6,
            values["vuKn"] * 1e3,
            values["fcMpa"],
            values["fyMpa"],
            values["fytMpa"],
        )
    stress_ratio = des.stress / des.stress_limit if des.stress_limit > 0 else 0.0
    rows = [
        {"metric": "Threshold torsion phi*Tth", "value": t_th / 1e6, "unit": "kN-m"},
        {"metric": "Cracking torsion phi*Tcr", "value": t_cr / 1e6, "unit": "kN-m"},
        {"metric": "Closed stirrup demand At/s", "value": des.at_s, "unit": "mm2/mm"},
        {"metric": "Longitudinal steel Al", "value": des.al, "unit": "mm2"},
        {"metric": "Stress check ratio", "value": stress_ratio, "unit": "-"},
    ]
    return result(
        summary={
            "thresholdTorsionKnm": t_th / 1e6,
            "crackingTorsionKnm": t_cr / 1e6,
            "torsionStirrupAtPerSMm": des.at_s,
            "longitudinalAlMm2": des.al,
            "stressRatio": stress_ratio,
            "sectionOk": des.section_ok,
        },
        tables=[
            table(
                "Torsion design check",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Thin-walled space-truss torsion model evaluated with rules from the active code pack."
        ],
    )


@feature(
    "objDesigner.sectionReport",
    "Section Report",
    part="objects",
    fields=[
        text("sectionId", "Project section ID (blank = parametric)", ""),
        number("widthMm", "Width", 400.0, unit="mm", min=100.0),
        number("depthMm", "Depth", 600.0, unit="mm", min=100.0),
        checkbox("writeReport", "Write Markdown report to 04 Objects/exports", True),
    ],
    requires_project=False,
)
def section_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a complete geometric, rebar, and P-M summary report for a designed section."""
    sec, mats, src = resolve_or_build_section(
        ctx, values["sectionId"], width_mm=values["widthMm"], depth_mm=values["depthMm"]
    )
    with in_force(ctx.root):
        props = properties(sec, mats)
        rc_sec = DesignedRcSection(sec, mats)
        phi_pn_max = rc_sec.phi_pn_max / 1e3
        phi_tens = rc_sec.phi_tension / 1e3

    rows = [
        {"item": "Gross area", "value": props.area, "unit": "mm2"},
        {"item": "Ixx / Iyy", "value": f"{props.ixx:.2e} / {props.iyy:.2e}", "unit": "mm4"},
        {"item": "Torsion J", "value": props.j, "unit": "mm4"},
        {"item": "Bar area", "value": props.barArea, "unit": "mm2"},
        {"item": "Bar ratio", "value": props.barRatio * 100.0, "unit": "%"},
        {"item": "Max design compression phi*Pn,max", "value": phi_pn_max, "unit": "kN"},
        {"item": "Design axial tension phi*Pt", "value": phi_tens, "unit": "kN"},
    ]
    out_path = ""
    if values["writeReport"] and ctx.root is not None:
        md = [
            f"# Section Report: {sec.name} ({sec.id})",
            f"- Source: {src}",
            f"- Area: {props.area:.1f} mm2, Ixx: {props.ixx:.3e} mm4, Iyy: {props.iyy:.3e} mm4, J: {props.j:.3e} mm4",
            f"- Bars: {len(sec.bars)}, total As = {props.barArea:.1f} mm2 ({props.barRatio * 100:.2f}%)",
            f"- Max design axial compression: {phi_pn_max:.1f} kN; tension: {phi_tens:.1f} kN",
        ]
        out_path = str(save_export(ctx, f"section-report-{sec.id}.md", "\n".join(md) + "\n"))

    return result(
        summary={
            "sectionId": sec.id,
            "areaMm2": props.area,
            "barAreaMm2": props.barArea,
            "phiPnMaxKn": phi_pn_max,
            "reportPath": out_path or "preview only",
        },
        tables=[
            table(
                f"Section report: {sec.id}",
                [("item", "Item"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            f"Report saved to {out_path}."
            if out_path
            else "Open a project folder to save the Markdown report."
        ],
    )


@feature(
    "objDesigner.exportDxfSection",
    "Export DXF Section",
    part="objects",
    fields=[
        text("sectionId", "Project section ID (blank = parametric)", ""),
        number("widthMm", "Width", 400.0, unit="mm", min=100.0),
        number("depthMm", "Depth", 600.0, unit="mm", min=100.0),
        text("filename", "DXF filename", "section-outline.dxf"),
    ],
    requires_project=True,
)
def export_dxf_section(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export the designed section outline, voids, and reinforcing bars to a DXF drawing."""
    import io

    import ezdxf

    require_root(ctx, "exporting DXF")
    sec, _, src = resolve_or_build_section(
        ctx, values["sectionId"], width_mm=values["widthMm"], depth_mm=values["depthMm"]
    )
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.add("OUTLINE", color=7)
    doc.layers.add("VOIDS", color=1)
    doc.layers.add("REBAR", color=3)

    entity_count = 0
    for region in sec.regions:
        msp.add_lwpolyline(region.outline, close=True, dxfattribs={"layer": "OUTLINE"})
        entity_count += 1
        for hole in region.holes:
            msp.add_lwpolyline(hole, close=True, dxfattribs={"layer": "VOIDS"})
            entity_count += 1
    for bar in sec.bars:
        msp.add_circle((bar.x, bar.y), radius=bar.dia / 2.0, dxfattribs={"layer": "REBAR"})
        entity_count += 1

    buf = io.StringIO()
    doc.write(buf)
    fname = values["filename"].strip() or f"{sec.id}.dxf"
    if not fname.lower().endswith(".dxf"):
        fname += ".dxf"
    target = save_export(ctx, fname, buf.getvalue())
    return result(
        summary={
            "sectionId": sec.id,
            "entityCount": entity_count,
            "barCount": len(sec.bars),
            "exportPath": str(target),
        },
        tables=[
            table(
                "DXF export layers",
                [("layer", "Layer"), ("count", "Entities")],
                [
                    {"layer": "OUTLINE", "count": len(sec.regions)},
                    {"layer": "VOIDS", "count": sum(len(r.holes) for r in sec.regions)},
                    {"layer": "REBAR", "count": len(sec.bars)},
                ],
            )
        ],
        notes=[f"Source: {src}. DXF written in mm units to {target}."],
    )


@feature(
    "objDesigner.saveAsType",
    "Save as Type",
    part="objects",
    fields=[
        text("sectionId", "New section ID", "SEC-CUSTOM-1"),
        text("typeName", "Object type name", "Custom Column Type"),
        select("kind", "Object kind", [("column", "Column"), ("beam", "Beam")], "column"),
        number("widthMm", "Width", 450.0, unit="mm", min=100.0),
        number("depthMm", "Depth", 600.0, unit="mm", min=100.0),
        number("coverMm", "Clear cover", 40.0, unit="mm", min=15.0),
    ],
    requires_project=True,
)
def save_as_type(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Save a designed section to 04 Objects/sections and generate a matching object-type definition."""
    root = require_root(ctx, "saving a designed section type")
    sid = values["sectionId"].strip() or "SEC-CUSTOM-1"
    sec, mats, _ = resolve_or_build_section(
        ctx, "", width_mm=values["widthMm"], depth_mm=values["depthMm"], cover_mm=values["coverMm"]
    )
    saved = DesignedSection(
        id=sid,
        name=values["typeName"].strip() or sid,
        regions=sec.regions,
        bars=sec.bars,
        rebar=sec.rebar,
        cover=values["coverMm"],
    )
    sec_path = save_section(root, saved)
    conc_id = saved.regions[0].material
    obj_def = {
        "id": sid,
        "name": saved.name,
        "kind": values["kind"],
        "material": conc_id,
        "profile": {"shape": "designed", "section": sid},
    }
    export_path = save_export(ctx, f"type-{sid}.json", safe_json(obj_def))
    with in_force(ctx.root):
        props = properties(saved, mats)
    return result(
        summary={
            "sectionId": sid,
            "areaMm2": props.area,
            "sectionFilePath": str(sec_path),
            "typeExportPath": str(export_path),
        },
        tables=[
            table(
                "Saved section type",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Section file", "value": str(sec_path)},
                    {"field": "Type JSON export", "value": str(export_path)},
                    {"field": "Bars", "value": len(saved.bars)},
                ],
            )
        ],
        notes=[f"Saved designed section to {sec_path} and object type payload to {export_path}."],
    )


@feature(
    "objDesigner.torsionalConstantJ",
    "Torsional Constant J",
    part="objects",
    fields=[
        text("sectionId", "Project section ID (blank = parametric)", ""),
        number("widthMm", "Width", 350.0, unit="mm", min=50.0),
        number("depthMm", "Depth", 600.0, unit="mm", min=50.0),
    ],
    requires_project=False,
)
def torsional_constant_j(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute the St. Venant torsional constant J via cross-section warping FEM and compare with closed-form."""
    sec, mats, src = resolve_or_build_section(
        ctx, values["sectionId"], width_mm=values["widthMm"], depth_mm=values["depthMm"]
    )
    with in_force(ctx.root):
        props = properties(sec, mats)
    b = min(values["widthMm"], values["depthMm"])
    h = max(values["widthMm"], values["depthMm"])
    j_rect = b**3 * h * (1.0 / 3.0 - 0.21 * (b / h) * (1.0 - (b / h) ** 4 / 12.0))
    return result(
        summary={
            "source": src,
            "jFemMm4": props.j,
            "jRectApproxMm4": j_rect,
            "areaMm2": props.area,
        },
        tables=[
            table(
                "Torsional constant comparison",
                [("method", "Method"), ("jMm4", "Torsion constant J", "mm4")],
                [
                    {"method": "FEM warping solution", "jMm4": props.j},
                    {"method": "Rectangle Timoshenko formula", "jMm4": j_rect},
                ],
            )
        ],
        notes=["FEM solution handles arbitrary shapes, cutouts, and composite modular ratios."],
    )


@feature(
    "objDesigner.warpingConstantIw",
    "Warping Constant Iw",
    part="objects",
    fields=[
        number("depthMm", "Channel/I depth d", 300.0, unit="mm", min=50.0),
        number("widthMm", "Flange width bf", 150.0, unit="mm", min=30.0),
        number("twMm", "Web thickness tw", 8.0, unit="mm", min=2.0),
        number("tfMm", "Flange thickness tf", 12.0, unit="mm", min=2.0),
    ],
    requires_project=False,
)
def warping_constant_iw(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute the Vlasov warping constant Iw (Cw) and shear centre coordinates via FEM."""
    d, bf, tw, tf = values["depthMm"], values["widthMm"], values["twMm"], values["tfMm"]
    if 2.0 * tf >= d or tw >= bf:
        raise FeatureInputError("Plate thicknesses exceed section dimensions.")
    mats, _ = materials_or_default(ctx)
    steel_id = next((m.id for m in mats.materials if m.category.value == "steel"), "A572-50")
    outline = [
        (0.0, 0.0),
        (bf, 0.0),
        (bf, tf),
        (bf / 2.0 + tw / 2.0, tf),
        (bf / 2.0 + tw / 2.0, d - tf),
        (bf, d - tf),
        (bf, d),
        (0.0, d),
        (0.0, d - tf),
        (bf / 2.0 - tw / 2.0, d - tf),
        (bf / 2.0 - tw / 2.0, tf),
        (0.0, tf),
    ]
    sec = DesignedSection(
        id="WARP-I",
        name="Warping I-section",
        regions=[Region(outline=outline, material=steel_id)],
    )
    with in_force(ctx.root):
        props = properties(sec, mats)
    return result(
        summary={
            "warpingConstantCwMm6": props.cw,
            "jMm4": props.j,
            "shearCentreXMm": props.scx,
            "shearCentreYMm": props.scy,
        },
        tables=[
            table(
                "Warping & shear centre properties",
                [("metric", "Property"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"metric": "Warping constant Iw (Cw)", "value": props.cw, "unit": "mm6"},
                    {"metric": "Torsional constant J", "value": props.j, "unit": "mm4"},
                    {"metric": "Shear centre X", "value": props.scx, "unit": "mm"},
                    {"metric": "Shear centre Y", "value": props.scy, "unit": "mm"},
                ],
            )
        ],
        notes=[
            "Computed from Saint-Venant / Vlasov warping function over triangulated section mesh."
        ],
    )


@feature(
    "objDesigner.plasticModulusZxZy",
    "Plastic Modulus Zx Zy",
    part="objects",
    fields=[
        text("sectionId", "Project section ID (blank = steel I-shape)", ""),
        number("depthMm", "Depth d", 300.0, unit="mm", min=50.0),
        number("widthMm", "Flange width bf", 150.0, unit="mm", min=30.0),
        number("twMm", "Web thickness tw", 8.0, unit="mm", min=2.0),
        number("tfMm", "Flange thickness tf", 12.0, unit="mm", min=2.0),
    ],
    requires_project=False,
)
def plastic_modulus_zx_zy(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute plastic section moduli Zx and Zy and elastic-plastic shape factors."""
    mats, _ = materials_or_default(ctx)
    sid = values["sectionId"].strip()
    if sid and ctx.root is not None and sid in list_sections(ctx.root):
        sec, mats, _ = resolve_or_build_section(ctx, sid)
    else:
        d, bf, tw, tf = values["depthMm"], values["widthMm"], values["twMm"], values["tfMm"]
        if 2.0 * tf >= d or tw >= bf:
            raise FeatureInputError("Plate thicknesses exceed overall dimensions.")
        steel_id = next((m.id for m in mats.materials if m.category.value == "steel"), "A572-50")
        outline = [
            (0.0, 0.0),
            (bf, 0.0),
            (bf, tf),
            (bf / 2.0 + tw / 2.0, tf),
            (bf / 2.0 + tw / 2.0, d - tf),
            (bf, d - tf),
            (bf, d),
            (0.0, d),
            (0.0, d - tf),
            (bf / 2.0 - tw / 2.0, d - tf),
            (bf / 2.0 - tw / 2.0, tf),
            (0.0, tf),
        ]
        sec = DesignedSection(
            id="PLASTIC-I", name="I-Section", regions=[Region(outline=outline, material=steel_id)]
        )
    with in_force(ctx.root):
        props = properties(sec, mats)
    sx = min(props.sxTop, props.sxBottom)
    sy = min(props.syLeft, props.syRight)
    zx = props.zx or sx
    zy = props.zy or sy
    return result(
        summary={
            "zxMm3": zx,
            "zyMm3": zy,
            "sxMinMm3": sx,
            "syMinMm3": sy,
            "shapeFactorX": zx / sx if sx > 0 else 1.0,
            "shapeFactorY": zy / sy if sy > 0 else 1.0,
        },
        tables=[
            table(
                "Elastic and plastic moduli",
                [
                    ("axis", "Axis"),
                    ("elasticMm3", "S_min", "mm3"),
                    ("plasticMm3", "Z", "mm3"),
                    ("shapeFactor", "Z/S"),
                ],
                [
                    {
                        "axis": "Major X",
                        "elasticMm3": sx,
                        "plasticMm3": zx,
                        "shapeFactor": zx / sx if sx > 0 else 1.0,
                    },
                    {
                        "axis": "Minor Y",
                        "elasticMm3": sy,
                        "plasticMm3": zy,
                        "shapeFactor": zy / sy if sy > 0 else 1.0,
                    },
                ],
            )
        ],
        notes=["Plastic moduli split equal-area plastic neutral axes on the meshed section."],
    )


@feature(
    "objDesigner.pMMInteractionSurface",
    "P-M-M Interaction Surface",
    part="objects",
    fields=[
        text("sectionId", "Project section ID (blank = parametric)", ""),
        number("widthMm", "Width", 400.0, unit="mm", min=100.0),
        number("depthMm", "Depth", 600.0, unit="mm", min=100.0),
        number("axialKn", "Axial force Pu for M-M contour", 600.0, unit="kN"),
    ],
    requires_project=False,
)
def pmm_interaction_surface(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute the biaxial Mx-My interaction contour at a specified axial force level."""
    sec, mats, src = resolve_or_build_section(
        ctx, values["sectionId"], width_mm=values["widthMm"], depth_mm=values["depthMm"]
    )
    pu_n = values["axialKn"] * 1e3
    with in_force(ctx.root):
        has_conc = any(
            mats.get(r.material) and mats.get(r.material).category.value == "concrete"
            for r in sec.regions
        )
        if has_conc:
            rc_sec = DesignedRcSection(sec, mats)
            contour = rc_contour(rc_sec, pu_n, angles=12, count=10)
        else:
            psec = PlasticSection(sec, mats)
            contour = psec.contour(pu_n, angles=12)
    if contour is None:
        raise FeatureInputError("Specified axial force exceeds section axial capacity.")
    rows = [
        {
            "angleDeg": math.degrees(r["theta"]),
            "phiMxKnm": r["phiMx"] / 1e6,
            "phiMyKnm": r["phiMy"] / 1e6,
            "mxKnm": r["Mx"] / 1e6,
            "myKnm": r["My"] / 1e6,
        }
        for r in contour
    ]
    return result(
        summary={
            "source": src,
            "axialKn": values["axialKn"],
            "maxPhiMxKnm": max(abs(r["phiMxKnm"]) for r in rows),
            "maxPhiMyKnm": max(abs(r["phiMyKnm"]) for r in rows),
            "contourPoints": len(rows),
        },
        tables=[
            table(
                f"Biaxial M-M contour at Pu = {values['axialKn']:g} kN",
                [
                    ("angleDeg", "NA angle", "deg"),
                    ("phiMxKnm", "phi*Mx", "kN-m"),
                    ("phiMyKnm", "phi*My", "kN-m"),
                    ("mxKnm", "Mx", "kN-m"),
                    ("myKnm", "My", "kN-m"),
                ],
                rows,
            )
        ],
        notes=["Sweeps neutral axis angles around 360 degrees at constant factored axial load Pu."],
    )


@feature(
    "objDesigner.reinforcementSchedule",
    "Reinforcement Schedule",
    part="objects",
    fields=[
        text("sectionId", "Project section ID (blank = parametric)", ""),
        number("widthMm", "Width", 400.0, unit="mm", min=100.0),
        number("depthMm", "Depth", 600.0, unit="mm", min=100.0),
        number("memberLenM", "Member length", 4.0, unit="m", min=0.2),
    ],
    requires_project=False,
)
def reinforcement_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise longitudinal bars in the designed section by size, count, and total steel weight."""
    sec, _, src = resolve_or_build_section(
        ctx, values["sectionId"], width_mm=values["widthMm"], depth_mm=values["depthMm"]
    )
    by_dia: dict[float, int] = {}
    for b in sec.bars:
        by_dia[b.dia] = by_dia.get(b.dia, 0) + 1
    with in_force(ctx.root):
        rows = []
        tot_kg = 0.0
        for dia, cnt in sorted(by_dia.items()):
            unit_m = bar_mass(dia)
            kg_m = cnt * unit_m
            kg_tot = kg_m * values["memberLenM"]
            tot_kg += kg_tot
            rows.append(
                {
                    "diaMm": dia,
                    "count": cnt,
                    "areaMm2": cnt * math.pi * dia**2 / 4.0,
                    "massKgPerM": kg_m,
                    "totalKg": kg_tot,
                }
            )
    return result(
        summary={
            "source": src,
            "totalBars": len(sec.bars),
            "massPerMetreKg": sum(r["massKgPerM"] for r in rows),
            "totalMassKg": tot_kg,
        },
        tables=[
            table(
                "Section longitudinal bar schedule",
                [
                    ("diaMm", "Bar dia", "mm"),
                    ("count", "Count"),
                    ("areaMm2", "Area", "mm2"),
                    ("massKgPerM", "Mass/m", "kg/m"),
                    ("totalKg", "Total mass", "kg"),
                ],
                rows,
            )
        ],
        notes=["Unit bar masses come from the active code pack's bar mass table."],
    )


@feature(
    "objDesigner.prestressTendons",
    "Prestress Tendons",
    part="objects",
    fields=[
        number("widthMm", "Section width b", 400.0, unit="mm", min=100.0),
        number("depthMm", "Section depth h", 700.0, unit="mm", min=150.0),
        number("strands", "Number of 7-wire strands", 12.0, min=1.0),
        number("strandAreaMm2", "Area per strand", 98.7, unit="mm2", min=20.0),
        number("fpuMpa", "Ultimate tendon strength fpu", 1860.0, unit="MPa", min=1000.0),
        number("effectiveStressRatio", "Effective stress ratio fpe/fpu", 0.58, min=0.2, max=0.8),
        number("eccentricityMm", "Tendon eccentricity below centroid e", 220.0, unit="mm"),
    ],
    requires_project=False,
)
def prestress_tendons(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate prestressing tendon force, precompression, and top/bottom extreme fibre stresses."""
    b, h = values["widthMm"], values["depthMm"]
    e = values["eccentricityMm"]
    if abs(e) >= h / 2.0:
        raise FeatureInputError("Tendon eccentricity must lie within section depth.")
    aps = round(values["strands"]) * values["strandAreaMm2"]
    fpe = values["effectiveStressRatio"] * values["fpuMpa"]
    pe_n = aps * fpe
    area = b * h
    s_mod = b * h**2 / 6.0
    p_avg = pe_n / area
    f_top = p_avg - pe_n * e / s_mod
    f_bot = p_avg + pe_n * e / s_mod
    kern = h / 6.0
    rows = [
        {"metric": "Total strand area Aps", "value": aps, "unit": "mm2"},
        {"metric": "Effective prestress Pe", "value": pe_n / 1e3, "unit": "kN"},
        {"metric": "Average precompression P/A", "value": p_avg, "unit": "MPa"},
        {"metric": "Top fibre stress (comp +)", "value": f_top, "unit": "MPa"},
        {"metric": "Bottom fibre stress (comp +)", "value": f_bot, "unit": "MPa"},
        {"metric": "Section kern limit h/6", "value": kern, "unit": "mm"},
    ]
    return result(
        summary={
            "tendonAreaMm2": aps,
            "effectiveForceKn": pe_n / 1e3,
            "avgPrecompressionMpa": p_avg,
            "topStressMpa": f_top,
            "bottomStressMpa": f_bot,
            "outsideKern": abs(e) > kern,
        },
        tables=[
            table(
                "Prestress tendon section effect",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Linear elastic stress superposition f = P/A +/- P*e/S; compression positive."],
    )


@feature(
    "objDesigner.fireCoverCheck",
    "Fire Cover Check",
    part="objects",
    fields=[
        select(
            "element",
            "Member type",
            [("beam", "Beam"), ("column", "Column"), ("slab", "Slab"), ("wall", "Wall")],
            "beam",
        ),
        select(
            "fireRatingMin",
            "Required fire resistance",
            [("60", "60 min"), ("90", "90 min"), ("120", "120 min"), ("180", "180 min")],
            "120",
        ),
        number("widthMm", "Member width / thickness", 300.0, unit="mm", min=80.0),
        number("coverMm", "Clear cover to stirrup/bar", 40.0, unit="mm", min=10.0),
        number("stirrupDiaMm", "Stirrup diameter (0 if none)", 10.0, unit="mm", min=0.0),
        number("mainDiaMm", "Main bar diameter", 20.0, unit="mm", min=8.0),
    ],
    requires_project=False,
)
def fire_cover_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify concrete axis distance and minimum member thickness against tabulated fire resistance limits."""
    # Tabulated axis distances [mm] and min dimensions [mm] by element & rating (thermal mass/isotherm)
    req_table = {
        "beam": {
            "60": (25.0, 120.0),
            "90": (35.0, 150.0),
            "120": (45.0, 200.0),
            "180": (60.0, 240.0),
        },
        "column": {
            "60": (25.0, 200.0),
            "90": (35.0, 250.0),
            "120": (45.0, 300.0),
            "180": (55.0, 350.0),
        },
        "slab": {
            "60": (20.0, 80.0),
            "90": (30.0, 100.0),
            "120": (40.0, 120.0),
            "180": (55.0, 150.0),
        },
        "wall": {
            "60": (15.0, 120.0),
            "90": (25.0, 140.0),
            "120": (35.0, 160.0),
            "180": (50.0, 200.0),
        },
    }
    el = values["element"]
    rating = values["fireRatingMin"]
    req_axis, req_dim = req_table[el][rating]
    axis_dist = values["coverMm"] + values["stirrupDiaMm"] + values["mainDiaMm"] / 2.0
    axis_ok = axis_dist >= req_axis
    dim_ok = values["widthMm"] >= req_dim
    rows = [
        {
            "check": "Axis distance a",
            "providedMm": axis_dist,
            "requiredMm": req_axis,
            "ok": axis_ok,
        },
        {
            "check": "Member width/thickness",
            "providedMm": values["widthMm"],
            "requiredMm": req_dim,
            "ok": dim_ok,
        },
    ]
    return result(
        summary={
            "axisDistanceMm": axis_dist,
            "requiredAxisMm": req_axis,
            "requiredWidthMm": req_dim,
            "fireCheckOk": axis_ok and dim_ok,
        },
        tables=[
            table(
                f"Fire resistance check ({rating} min, {el})",
                [
                    ("check", "Check"),
                    ("providedMm", "Provided", "mm"),
                    ("requiredMm", "Required", "mm"),
                    ("ok", "Pass"),
                ],
                rows,
            )
        ],
        notes=[
            "Axis distance a = cover + stirrup_dia + main_dia/2 measured to centre of main reinforcement."
        ],
    )

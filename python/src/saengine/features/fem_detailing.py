"""Design Reinforcement - Detailing tab: beam/column/slab detailing, BBS, curtailment, DXF details, and cutting lists."""

from __future__ import annotations

import io
import math
from typing import Any

import ezdxf

from saengine.design import bars, development_factors, punching, rc_detailing
from saengine.drawings import bbs, detailing
from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.fem_common import (
    concrete_rebar_defaults,
    export_fem_file,
    load_bim,
    load_objects,
)
from saengine.report.clauses import in_force


def _dxf_bytes(doc: Any) -> bytes:
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


@feature(
    "femDetailing.beamDetailing",
    "Beam Detailing",
    part="fem",
    fields=[
        number("spanMm", "Beam span", 6000.0, unit="mm", min=1000.0),
        number("widthMm", "Width b", 300.0, unit="mm", min=150.0),
        number("depthMm", "Depth h", 500.0, unit="mm", min=200.0),
    ],
    requires_project=False,
)
def beam_detailing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate beam longitudinal reinforcement, stirrup zones, and skin-bar detailing summary."""
    fc, fy = concrete_rebar_defaults(ctx)
    with in_force(ctx.root):
        as_min = bars.beam_min_area(values["widthMm"], values["depthMm"] - 50.0, fc, fy)
    skin_needed = values["depthMm"] > 750.0
    rows = [
        {"parameter": "Min tension steel As,min [mm²]", "value": as_min},
        {"parameter": "Support top zone", "value": round(0.30 * values["spanMm"], 1)},
        {"parameter": "Skin reinforcement required", "value": str(skin_needed)},
    ]
    return result(
        summary={"asMinMm2": as_min, "skinBarsRequired": skin_needed},
        tables=[
            table(
                "Beam reinforcement detailing schedule",
                [("parameter", "Parameter"), ("value", "Value")],
                rows,
            )
        ],
        notes=["Includes minimum flexural reinforcement and deep-web skin bar check."],
    )


@feature(
    "femDetailing.curtailment",
    "Curtailment",
    part="fem",
    fields=[
        number("spanMm", "Clear span ln", 6000.0, unit="mm", min=1000.0),
        number("effectiveDepthMm", "Effective depth d", 440.0, unit="mm", min=100.0),
        number("barDiaMm", "Bar diameter db", 20.0, unit="mm", min=8.0),
    ],
    requires_project=False,
)
def curtailment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute bar curtailment extension max(d, 12db, ln/16) and cutoff coordinates."""
    ext = max(values["effectiveDepthMm"], 12.0 * values["barDiaMm"], values["spanMm"] / 16.0)
    top_cut = 0.25 * values["spanMm"] + ext
    rows = [{"extensionMm": ext, "topCutoffFromFaceMm": top_cut, "bottomThroughPct": 33.3}]
    return result(
        summary={"cutoffExtensionMm": ext, "topCutoffFromSupportMm": top_cut},
        tables=[
            table(
                "Flexural bar curtailment parameters",
                [
                    ("extensionMm", "Extension", "mm"),
                    ("topCutoffFromFaceMm", "Top Cutoff", "mm"),
                    ("bottomThroughPct", "Continuous Bot", "%"),
                ],
                rows,
            )
        ],
        notes=["Bars must extend at least max(d, 12db) beyond theoretical point of zero demand."],
    )


@feature(
    "femDetailing.barSpacing",
    "Bar Spacing",
    part="fem",
    fields=[
        number("beamWidthMm", "Beam width b", 300.0, unit="mm", min=150.0),
        number("coverMm", "Clear cover", 40.0, unit="mm", min=15.0),
        number("stirrupMm", "Stirrup diameter", 10.0, unit="mm", min=6.0),
        number("barDiaMm", "Main bar diameter", 20.0, unit="mm", min=10.0),
        number("barCount", "Bars in one row", 4, min=2, max=12),
    ],
    requires_project=False,
)
def bar_spacing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check clear horizontal spacing between longitudinal bars against minimum placement limits."""
    n = int(values["barCount"])
    inner = values["beamWidthMm"] - 2.0 * (values["coverMm"] + values["stirrupMm"])
    clear = (inner - n * values["barDiaMm"]) / max(n - 1, 1)
    min_req = max(25.0, values["barDiaMm"], 26.7)
    rows = [{"providedClearMm": clear, "minRequiredMm": min_req, "ok": clear >= min_req}]
    return result(
        summary={"clearSpacingMm": clear, "minRequiredMm": min_req, "passes": clear >= min_req},
        tables=[
            table(
                "Horizontal clear bar spacing check",
                [
                    ("providedClearMm", "Provided", "mm"),
                    ("minRequiredMm", "Min Req", "mm"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Split bars into a second vertical row if single-row clear spacing fails."],
    )


@feature(
    "femDetailing.columnDetailing",
    "Column Detailing",
    part="fem",
    fields=[
        number("bMm", "Column width b", 400.0, unit="mm", min=200.0),
        number("hMm", "Column depth h", 600.0, unit="mm", min=200.0),
        number("barDiaMm", "Longitudinal bar db", 20.0, unit="mm", min=12.0),
        number("tieDiaMm", "Tie diameter", 10.0, unit="mm", min=8.0),
    ],
    requires_project=False,
)
def column_detailing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check column longitudinal ratio bounds and standard tie spacing limits."""
    with in_force(ctx.root):
        rho_min, rho_max = bars.column_rho()
    s_tie = min(
        16.0 * values["barDiaMm"], 48.0 * values["tieDiaMm"], min(values["bMm"], values["hMm"])
    )
    ag = values["bMm"] * values["hMm"]
    rows = [{"minSteelMm2": rho_min * ag, "maxSteelMm2": rho_max * ag, "maxTieSpacingMm": s_tie}]
    return result(
        summary={"minSteelMm2": rho_min * ag, "maxTieSpacingMm": s_tie},
        tables=[
            table(
                "Column reinforcement detailing limits",
                [
                    ("minSteelMm2", "As,min", "mm²"),
                    ("maxSteelMm2", "As,max", "mm²"),
                    ("maxTieSpacingMm", "Max Tie s", "mm"),
                ],
                rows,
            )
        ],
        notes=["Standard tie spacing <= min(16 db, 48 dt, least column dimension)."],
    )


@feature(
    "femDetailing.confinementZones",
    "Confinement Zones",
    part="fem",
    fields=[
        number("columnDepthMm", "Larger column dimension hc", 600.0, unit="mm", min=200.0),
        number("clearHeightMm", "Clear storey height lu", 3000.0, unit="mm", min=1000.0),
    ],
    requires_project=False,
)
def confinement_zones(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute column joint confinement zone length lo at top and bottom floor connections."""
    lo = max(values["columnDepthMm"], values["clearHeightMm"] / 6.0, 450.0)
    rows = [{"zone": "Bottom end", "lengthMm": lo}, {"zone": "Top end", "lengthMm": lo}]
    return result(
        summary={"confinementLengthMm": lo},
        tables=[
            table(
                "Column end confinement zones",
                [("zone", "Location"), ("lengthMm", "lo", "mm")],
                rows,
            )
        ],
        notes=["Confined hoop spacing applies over lo above and below each beam-column joint."],
    )


@feature(
    "femDetailing.spliceDesign",
    "Splice Design",
    part="fem",
    fields=[
        number("barDiaMm", "Bar diameter db", 20.0, unit="mm", min=10.0),
        checkbox("compressionOnly", "Compression splice only", False),
    ],
    requires_project=False,
)
def splice_design(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Design tension or compression lap splice lengths and mechanical coupler options."""
    fc, fy = concrete_rebar_defaults(ctx)
    with in_force(ctx.root):
        ten = development_factors.lap_tension(values["barDiaMm"], fy, fc)
        comp = development_factors.lap_compression(values["barDiaMm"], fy, fc)
    lap = float(comp.get("length", 0.0) if values["compressionOnly"] else ten.get("length", 0.0))
    rows = [
        {
            "kind": "Compression lap" if values["compressionOnly"] else "Class B tension lap",
            "lapLengthMm": lap,
            "couplerAlternative": "Type 2 mechanical coupler (>= 1.25 fy)",
        }
    ]
    return result(
        summary={"lapLengthMm": lap, "barDiameterMm": values["barDiaMm"]},
        tables=[
            table(
                "Column/beam lap splice design",
                [
                    ("kind", "Splice Type"),
                    ("lapLengthMm", "Length", "mm"),
                    ("couplerAlternative", "Alternative"),
                ],
                rows,
            )
        ],
        notes=["Computed via saengine.design.development_factors."],
    )


@feature(
    "femDetailing.slabDetailing",
    "Slab Detailing",
    part="fem",
    fields=[
        number("thicknessMm", "Slab thickness h", 175.0, unit="mm", min=75.0),
        number("barDiaMm", "Mesh bar diameter", 12.0, unit="mm", min=8.0),
        number("providedSpacingMm", "Bar spacing s", 200.0, unit="mm", min=75.0),
    ],
    requires_project=False,
)
def slab_detailing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check slab shrinkage/temperature steel ratio and maximum bar spacing limits."""
    _, fy = concrete_rebar_defaults(ctx)
    with in_force(ctx.root):
        ratio = rc_detailing.shrinkage_ratio(fy)
        s_max = min(5.0 * values["thicknessMm"], 450.0)
    a_bar = math.pi * (values["barDiaMm"] / 2.0) ** 2
    as_prov = a_bar * (1000.0 / values["providedSpacingMm"])
    as_min = ratio * 1000.0 * values["thicknessMm"]
    rows = [
        {
            "asMinMm2PerM": as_min,
            "asProvMm2PerM": as_prov,
            "maxSpacingMm": s_max,
            "ok": as_prov >= as_min and values["providedSpacingMm"] <= s_max,
        }
    ]
    return result(
        summary={"asMinMm2PerM": as_min, "asProvidedMm2PerM": as_prov, "passes": rows[0]["ok"]},
        tables=[
            table(
                "Slab mesh minimum steel & spacing check",
                [
                    ("asMinMm2PerM", "As,min", "mm²/m"),
                    ("asProvMm2PerM", "As,prov", "mm²/m"),
                    ("maxSpacingMm", "Max s", "mm"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Minimum shrinkage/temperature steel evaluated via saengine.design.rc_detailing."],
    )


@feature(
    "femDetailing.punchingRebar",
    "Punching Rebar",
    part="fem",
    fields=[
        number("vuKn", "Factored punching shear Vu", 420.0, unit="kN", min=10.0),
        number("c1Mm", "Column c1", 400.0, unit="mm", min=150.0),
        number("c2Mm", "Column c2", 400.0, unit="mm", min=150.0),
        number("dMm", "Slab effective depth d", 180.0, unit="mm", min=80.0),
    ],
    requires_project=False,
)
def punching_rebar(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Design headed shear-stud rails around a slab-column punching perimeter."""
    fc, _ = concrete_rebar_defaults(ctx)
    boundary = [(0.0, 0.0), (6000.0, 0.0), (6000.0, 6000.0), (0.0, 6000.0)]
    dem = punching.Demand(vu=values["vuKn"] * 1000.0, combination="ULS")
    with in_force(ctx.root):
        res = punching.slab_punching(
            (3000.0, 3000.0),
            values["c1Mm"],
            values["c2Mm"],
            0.0,
            values["dMm"],
            boundary,
            [dem],
            fc,
        )
    layout = res.reinforcement.text if (res and res.reinforcement) else "No punching studs needed"
    rows = [
        {
            "perimeterMm": res.b0 if res else 0.0,
            "phiVcKn": (res.phi_vc / 1000.0) if res else 0.0,
            "utilisation": res.utilisation if res else 0.0,
            "studLayout": layout,
        }
    ]
    return result(
        summary={"utilisation": rows[0]["utilisation"], "studLayout": layout},
        tables=[
            table(
                "Punching shear stud rail design",
                [
                    ("perimeterMm", "b0", "mm"),
                    ("phiVcKn", "φVc", "kN"),
                    ("utilisation", "DCR"),
                    ("studLayout", "Reinforcement"),
                ],
                rows,
            )
        ],
        notes=["Computed via saengine.design.punching.slab_punching."],
    )


@feature(
    "femDetailing.openingsTrimBars",
    "Openings Trim Bars",
    part="fem",
    fields=[
        number("openingWidthMm", "Opening width", 1000.0, unit="mm", min=100.0),
        number("slabSteelMm2PerM", "Interrupted slab steel As/m", 565.0, unit="mm²/m", min=100.0),
        number("trimBarDiaMm", "Trim bar diameter", 16.0, unit="mm", min=10.0),
    ],
    requires_project=False,
)
def openings_trim_bars(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size trim reinforcement on each side of a slab opening to replace interrupted slab bars."""
    interrupted_as = values["slabSteelMm2PerM"] * (values["openingWidthMm"] / 1000.0)
    as_per_side = 0.5 * interrupted_as
    a_bar = math.pi * (values["trimBarDiaMm"] / 2.0) ** 2
    n_bars = max(2, math.ceil(as_per_side / a_bar))
    rows = [
        {
            "interruptedSteelMm2": interrupted_as,
            "requiredPerSideMm2": as_per_side,
            "trimBarsEachSide": f"{n_bars}Ø{values['trimBarDiaMm']:g}",
        }
    ]
    return result(
        summary={"requiredPerSideMm2": as_per_side, "barsPerSide": n_bars},
        tables=[
            table(
                "Slab opening trim bar replacement",
                [
                    ("interruptedSteelMm2", "Interrupted As", "mm²"),
                    ("requiredPerSideMm2", "As/side", "mm²"),
                    ("trimBarsEachSide", "Trim Bars"),
                ],
                rows,
            )
        ],
        notes=["Trim bars extend full development length ld past opening corners."],
    )


@feature(
    "femDetailing.rebarSchedule",
    "Rebar Schedule",
    part="fem",
    fields=[],
    requires_project=True,
)
def rebar_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate full project bar bending schedule (BBS) from detailed BIM/Objects model."""
    root = ctx.root
    if root is None:
        raise FeatureInputError("Open a project folder first.")
    with in_force(root):
        det = detailing.detailing_model(root)
        sched = bbs.bar_schedule(det)
    rows = [
        {
            "member": r.member,
            "mark": r.mark,
            "shape": r.shape,
            "diaMm": r.dia,
            "count": r.members * r.per_member,
            "cutMm": r.cutting_length,
        }
        for r in sched.rows[:50]
    ]
    return result(
        summary={"scheduleRows": len(sched.rows)},
        tables=[
            table(
                "Reinforcement bar schedule",
                [
                    ("member", "Member"),
                    ("mark", "Mark"),
                    ("shape", "Shape"),
                    ("diaMm", "Ø", "mm"),
                    ("count", "Qty"),
                    ("cutMm", "Cut Length", "mm"),
                ],
                rows
                or [
                    {
                        "member": "None",
                        "mark": "-",
                        "shape": "-",
                        "diaMm": 0,
                        "count": 0,
                        "cutMm": 0,
                    }
                ],
            )
        ],
        notes=["Generated via saengine.drawings.detailing and saengine.drawings.bbs."],
    )


@feature(
    "femDetailing.barMarking",
    "Bar Marking",
    part="fem",
    fields=[],
    requires_project=True,
)
def bar_marking(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Group identical bar diameters, shapes, and cutting lengths under unique bar marks."""
    root = ctx.root
    if root is None:
        raise FeatureInputError("Open a project folder first.")
    with in_force(root):
        det = detailing.detailing_model(root)
    marks = det.get("marks") or {}
    rows = [{"mark": str(k), "details": str(v)} for k, v in list(marks.items())[:40]]
    return result(
        summary={"uniqueMarks": len(marks)},
        tables=[
            table(
                "Unique bar mark index",
                [("mark", "Mark"), ("details", "Specification")],
                rows or [{"mark": "None", "details": "-"}],
            )
        ],
        notes=["Assigns unique fabrication marks per diameter/shape/length signature."],
    )


@feature(
    "femDetailing.rebarAnchorage",
    "Rebar Anchorage",
    part="fem",
    fields=[
        number("barDiaMm", "Bar diameter db", 16.0, unit="mm", min=8.0),
        checkbox("bentHook", "Use 90° standard hook", True),
    ],
    requires_project=False,
)
def rebar_anchorage(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute straight or hooked anchorage development length for bar detailing."""
    fc, fy = concrete_rebar_defaults(ctx)
    with in_force(ctx.root):
        res = (
            development_factors.hook_length(values["barDiaMm"], fy, fc)
            if values["bentHook"]
            else development_factors.tension_length(values["barDiaMm"], fy, fc)
        )
    length_mm = float(res.get("length", 0.0))
    rows = [
        {
            "mode": "90° Hook" if values["bentHook"] else "Straight",
            "barDiaMm": values["barDiaMm"],
            "anchorageLengthMm": length_mm,
        }
    ]
    return result(
        summary={"anchorageLengthMm": length_mm},
        tables=[
            table(
                "Rebar anchorage length",
                [("mode", "Mode"), ("barDiaMm", "db", "mm"), ("anchorageLengthMm", "Length", "mm")],
                rows,
            )
        ],
        notes=["Computed via saengine.design.development_factors."],
    )


@feature(
    "femDetailing.spliceLength",
    "Splice Length",
    part="fem",
    fields=[
        number("barDiaMm", "Bar diameter db", 20.0, unit="mm", min=8.0),
        checkbox("topBar", "Top cast bar", False),
    ],
    requires_project=False,
)
def splice_length(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Class A and Class B tension lap splice lengths by bar diameter."""
    fc, fy = concrete_rebar_defaults(ctx)
    with in_force(ctx.root):
        ten = development_factors.tension_length(values["barDiaMm"], fy, fc, top=values["topBar"])
        lap = development_factors.lap_tension(values["barDiaMm"], fy, fc, top=values["topBar"])
    ld = float(ten.get("length", 0.0))
    lap_b = float(lap.get("length", 1.3 * ld))
    rows = [{"classA": max(ld, 300.0), "classB": max(lap_b, 300.0)}]
    return result(
        summary={"classALapMm": rows[0]["classA"], "classBLapMm": rows[0]["classB"]},
        tables=[
            table(
                f"Tension lap splice lengths (Ø{values['barDiaMm']:g})",
                [("classA", "Class A (1.0 ld)", "mm"), ("classB", "Class B (1.3 ld)", "mm")],
                rows,
            )
        ],
        notes=[
            "Class B splice (1.3 ld) applies where more than 50% of bars are spliced at one section."
        ],
    )


@feature(
    "femDetailing.rebarWeight",
    "Rebar Weight",
    part="fem",
    fields=[],
    requires_project=True,
)
def rebar_weight(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Total project reinforcement tonnage grouped by bar diameter from BBS."""
    root = ctx.root
    if root is None:
        raise FeatureInputError("Open a project folder first.")
    with in_force(root):
        det = detailing.detailing_model(root)
        sched = bbs.bar_schedule(det)
    by_dia: dict[float, float] = {}
    for r in sched.rows:
        kg = bbs.bar_mass(r.dia) * (r.cutting_length / 1000.0) * r.members * r.per_member
        by_dia[r.dia] = by_dia.get(r.dia, 0.0) + kg
    rows = [
        {"diaMm": d, "massKg": kg, "massTonnes": kg / 1000.0} for d, kg in sorted(by_dia.items())
    ]
    tot_kg = sum(by_dia.values())
    return result(
        summary={"totalMassKg": tot_kg, "totalTonnes": tot_kg / 1000.0},
        tables=[
            table(
                "Reinforcement tonnage by diameter",
                [("diaMm", "Bar Ø", "mm"), ("massKg", "Mass", "kg"), ("massTonnes", "Tonnes", "t")],
                rows or [{"diaMm": 0, "massKg": 0.0, "massTonnes": 0.0}],
            )
        ],
        notes=["Includes nominal bar unit masses and cutting lengths."],
    )


@feature(
    "femDetailing.detailDrawings",
    "Detail Drawings",
    part="fem",
    fields=[
        number("beamWidthMm", "Beam width b", 300.0, unit="mm", min=150.0),
        number("beamDepthMm", "Beam depth h", 500.0, unit="mm", min=200.0),
    ],
    requires_project=True,
)
def detail_drawings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a CAD DXF beam cross-section detail drawing in 08 FEM/exports/."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    b, h = values["beamWidthMm"], values["beamDepthMm"]
    msp.add_lwpolyline([(0, 0), (b, 0), (b, h), (0, h), (0, 0)])
    msp.add_lwpolyline([(40, 40), (b - 40, 40), (b - 40, h - 40), (40, h - 40), (40, 40)])
    for x in (55, b / 2, b - 55):
        msp.add_circle((x, 55), 10)
        msp.add_circle((x, h - 55), 10)
    path = export_fem_file(ctx, "beam-detail.dxf", _dxf_bytes(doc))
    return result(
        summary={"dxfPath": str(path), "widthMm": b, "depthMm": h},
        tables=[
            table(
                "Generated detail DXF",
                [("item", "Entity"), ("val", "Value")],
                [
                    {"item": "Section", "val": f"{b:g}×{h:g} mm"},
                    {"item": "DXF Path", "val": str(path)},
                ],
            )
        ],
        notes=[f"DXF detail drawing written to {path}"],
    )


@feature(
    "femDetailing.sectionDetails",
    "Section Details",
    part="fem",
    fields=[
        number("widthMm", "Column width b", 400.0, unit="mm", min=200.0),
        number("depthMm", "Column depth h", 600.0, unit="mm", min=200.0),
        number("coverMm", "Clear cover", 40.0, unit="mm", min=20.0),
    ],
    requires_project=False,
)
def section_details(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute cross-section bar coordinates and stirrup cage centerline dimensions."""
    b, h, c = values["widthMm"], values["depthMm"], values["coverMm"]
    rows = [
        {"feature": "Concrete section", "dimsMm": f"{b:g} × {h:g}"},
        {
            "feature": "Stirrup centerline loop",
            "dimsMm": f"{b - 2 * c - 10:g} × {h - 2 * c - 10:g}",
        },
        {"feature": "Corner bar centres inset", "dimsMm": f"{c + 20:g} mm from faces"},
    ]
    return result(
        summary={"coreWidthMm": b - 2 * c, "coreDepthMm": h - 2 * c},
        tables=[
            table(
                "Cross-section detail dimensions",
                [("feature", "Element"), ("dimsMm", "Geometry")],
                rows,
            )
        ],
        notes=["Provides exact coordinate offsets for CAD section plotting."],
    )


@feature(
    "femDetailing.detailScale",
    "Detail Scale",
    part="fem",
    fields=[
        number("scaleDenominator", "Drawing scale 1 : N", 25, min=5, max=200),
        number("memberDepthMm", "Actual member depth", 500.0, unit="mm", min=100.0),
    ],
    requires_project=False,
)
def detail_scale(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute plotted sheet dimensions and text height for the chosen detail drawing scale."""
    n = values["scaleDenominator"]
    plotted_mm = values["memberDepthMm"] / n
    rows = [{"scale": f"1:{int(n)}", "plottedDepthMm": plotted_mm, "modelTextHeightMm": 2.5 * n}]
    return result(
        summary={"scale": f"1:{int(n)}", "plottedDepthMm": plotted_mm},
        tables=[
            table(
                "Detail drawing scale geometry",
                [
                    ("scale", "Scale"),
                    ("plottedDepthMm", "Paper Size", "mm"),
                    ("modelTextHeightMm", "CAD Text H", "mm"),
                ],
                rows,
            )
        ],
        notes=["Standard sheet text height 2.5 mm maps to 2.5 × scale in model space."],
    )


@feature(
    "femDetailing.detailDimensions",
    "Detail Dimensions",
    part="fem",
    fields=[
        number("spanMm", "Beam clear span", 5600.0, unit="mm", min=500.0),
        number("supportWidthMm", "Support column width", 400.0, unit="mm", min=150.0),
    ],
    requires_project=False,
)
def detail_dimensions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate dimension chain coordinates for beam elevation detailing."""
    ln = values["spanMm"]
    rows = [
        {"chain": "Left confinement zone", "startMm": 0.0, "endMm": 1000.0, "dimMm": 1000.0},
        {
            "chain": "Mid-span shear zone",
            "startMm": 1000.0,
            "endMm": max(1000.0, ln - 1000.0),
            "dimMm": max(0.0, ln - 2000.0),
        },
        {
            "chain": "Right confinement zone",
            "startMm": max(1000.0, ln - 1000.0),
            "endMm": ln,
            "dimMm": 1000.0,
        },
    ]
    return result(
        summary={"clearSpanMm": ln, "centreToCentreMm": ln + values["supportWidthMm"]},
        tables=[
            table(
                "Elevation dimension chains",
                [
                    ("chain", "Zone"),
                    ("startMm", "Start", "mm"),
                    ("endMm", "End", "mm"),
                    ("dimMm", "Length", "mm"),
                ],
                rows,
            )
        ],
        notes=["Aligns stirrup zone callouts with clear span faces."],
    )


@feature(
    "femDetailing.detailTitle",
    "Detail Title",
    part="fem",
    fields=[
        text("sheetNumber", "Sheet number", "S-301"),
        text("title", "Detail sheet title", "Reinforced Concrete Beam & Column Details"),
    ],
    requires_project=False,
)
def detail_title(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assemble standard title block notes and sheet callouts for structural details."""
    fc, fy = concrete_rebar_defaults(ctx)
    rows = [
        {"field": "Sheet", "text": values["sheetNumber"]},
        {"field": "Title", "text": values["title"]},
        {"field": "Materials Note", "text": f"Concrete f'c = {fc:g} MPa; Rebar fy = {fy:g} MPa"},
    ]
    return result(
        summary={"sheetNumber": values["sheetNumber"], "title": values["title"]},
        tables=[table("Detail sheet title block", [("field", "Field"), ("text", "Content")], rows)],
        notes=["Standardized title block metadata for automated sheet assembly."],
    )


@feature(
    "femDetailing.barShapeTable",
    "Bar Shape Table",
    part="fem",
    fields=[],
    requires_project=True,
)
def bar_shape_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List standard bar bending shape keys and segment definitions used in the BBS."""
    root = ctx.root
    if root is None:
        raise FeatureInputError("Open a project folder first.")
    with in_force(root):
        det = detailing.detailing_model(root)
        sched = bbs.bar_schedule(det)
        s_key = bbs.shape_key(sched)
    rows = [
        {"shape": str(s.get("shape", s) if isinstance(s, dict) else s), "description": str(s)}
        for s in s_key
    ]
    return result(
        summary={"shapeCodes": len(rows)},
        tables=[
            table(
                "Standard bar bending shape key",
                [("shape", "Shape"), ("description", "Definition")],
                rows or [{"shape": "00", "description": "Straight bar"}],
            )
        ],
        notes=["Generated via saengine.drawings.bbs.shape_key."],
    )


@feature(
    "femDetailing.bendingDiagram",
    "Bending Diagram",
    part="fem",
    fields=[
        number("straightLegMm", "Leg A", 1200.0, unit="mm", min=100.0),
        number("hookLegMm", "90° Hook leg B", 300.0, unit="mm", min=50.0),
        number("barDiaMm", "Bar diameter", 16.0, unit="mm", min=8.0),
    ],
    requires_project=False,
)
def bending_diagram(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute bent-bar cutting length and mandrel bend allowance for shop fabrication."""
    # Standard 90° bend deduction ~ 2*db
    cut_len = values["straightLegMm"] + values["hookLegMm"] - 2.0 * values["barDiaMm"]
    rows = [
        {
            "legAMm": values["straightLegMm"],
            "legBMm": values["hookLegMm"],
            "bendDeductionMm": 2.0 * values["barDiaMm"],
            "cuttingLengthMm": cut_len,
        }
    ]
    return result(
        summary={"cuttingLengthMm": cut_len},
        tables=[
            table(
                "Bent bar fabrication diagram",
                [
                    ("legAMm", "Leg A", "mm"),
                    ("legBMm", "Leg B", "mm"),
                    ("bendDeductionMm", "Deduction", "mm"),
                    ("cuttingLengthMm", "Cut Length", "mm"),
                ],
                rows,
            )
        ],
        notes=["Applies centerline arc length adjustment at 90-degree bends."],
    )


@feature(
    "femDetailing.cuttingList",
    "Cutting List",
    part="fem",
    fields=[],
    requires_project=True,
)
def cutting_list(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Produce rebar shop cutting list grouped by diameter and length, exported to CSV."""
    root = ctx.root
    if root is None:
        raise FeatureInputError("Open a project folder first.")
    with in_force(root):
        det = detailing.detailing_model(root)
        sched = bbs.bar_schedule(det)
    rows = [
        {"mark": r.mark, "diaMm": r.dia, "cutMm": r.cutting_length, "qty": r.members * r.per_member}
        for r in sched.rows
    ]
    csv_lines = ["mark,dia_mm,cut_mm,qty"] + [
        f"{r['mark']},{r['diaMm']},{r['cutMm']},{r['qty']}" for r in rows
    ]
    path = export_fem_file(ctx, "rebar-cutting-list.csv", "\n".join(csv_lines) + "\n")
    return result(
        summary={"items": len(rows), "csvPath": str(path)},
        tables=[
            table(
                "Shop rebar cutting list",
                [("mark", "Mark"), ("diaMm", "Ø", "mm"), ("cutMm", "Length", "mm"), ("qty", "Qty")],
                rows[:40] or [{"mark": "-", "diaMm": 0, "cutMm": 0, "qty": 0}],
            )
        ],
        notes=[f"Cutting list exported to {path}"],
    )


@feature(
    "femDetailing.assemblyDetail",
    "Assembly Detail",
    part="fem",
    fields=[
        number("cageLengthM", "Prefabricated cage length", 6.0, unit="m", min=1.0),
        number("cageMassKg", "Total cage weight", 450.0, unit="kg", min=10.0),
        number("liftingPoints", "Rigging pick points", 2, min=2, max=4),
    ],
    requires_project=False,
)
def assembly_detail(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check prefabricated rebar cage rigging pick-point loads and lifting stability."""
    load_per_pick_kn = (values["cageMassKg"] * 9.80665 / 1000.0 * 1.5) / int(
        values["liftingPoints"]
    )
    pick_offset_m = 0.207 * values["cageLengthM"]
    rows = [
        {
            "pickPoints": int(values["liftingPoints"]),
            "pickOffsetFromEndsM": pick_offset_m,
            "designLoadPerPickKn": load_per_pick_kn,
        }
    ]
    return result(
        summary={"pickOffsetM": pick_offset_m, "designLoadPerPickKn": load_per_pick_kn},
        tables=[
            table(
                "Prefabricated cage lifting & rigging",
                [
                    ("pickPoints", "Picks"),
                    ("pickOffsetFromEndsM", "0.207 L Offset", "m"),
                    ("designLoadPerPickKn", "Factored Load/Pick", "kN"),
                ],
                rows,
            )
        ],
        notes=[
            "Two-point pick at 0.207 L from ends equalizes hogging and sagging bending during lift (1.5 dynamic factor)."
        ],
    )


@feature(
    "femDetailing.deliveryMarks",
    "Delivery Marks",
    part="fem",
    fields=[],
    requires_project=False,
)
def delivery_marks(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate unique site delivery tags for prefabricated reinforcement cages from BIM."""
    bim = load_bim(ctx)
    _, objs = load_objects(ctx)
    rows = []
    if bim:
        for el in bim.elements[:35]:
            eid = str(getattr(el, "id", ""))
            t = str(getattr(el, "type", ""))
            rows.append(
                {
                    "deliveryTag": f"CAGE-{eid}",
                    "member": eid,
                    "type": t,
                    "kind": str(getattr(objs.get(t), "kind", "-")),
                }
            )
    return result(
        summary={"taggedCages": len(rows)},
        tables=[
            table(
                "Prefabricated cage delivery tags",
                [
                    ("deliveryTag", "Delivery Tag"),
                    ("member", "Member"),
                    ("type", "Type"),
                    ("kind", "Kind"),
                ],
                rows or [{"deliveryTag": "CAGE-1", "member": "B1", "type": "-", "kind": "beam"}],
            )
        ],
        notes=["Traceable delivery marks tie shop cages to erection sequence."],
    )

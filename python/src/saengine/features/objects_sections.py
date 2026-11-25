"""Objects - Library Sections tab: frame, concrete, steel, composite and parametric sections."""

from __future__ import annotations

import math
from typing import Any

from saengine.design.rc_detailing import concrete_modulus, effective_flange
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
    objects_or_default,
    parse_csv_rows,
    safe_json,
    save_export,
)
from saengine.library import objects as o
from saengine.library import steel_sections
from saengine.library.sections import section_properties
from saengine.report.clauses import in_force


def _build_profile_from_params(
    shape: str, depth: float, width: float, tw: float, tf: float, radius: float
) -> o.Profile:
    if shape == "rectangle":
        return o.RectangleProfile(xDim=width, yDim=depth)
    if shape == "circle":
        return o.CircleProfile(radius=depth / 2.0)
    if shape == "I":
        return o.IShapeProfile(
            overallWidth=width,
            overallDepth=depth,
            webThickness=tw,
            flangeThickness=tf,
            filletRadius=radius,
        )
    if shape == "T":
        return o.TShapeProfile(
            depth=depth,
            flangeWidth=width,
            webThickness=tw,
            flangeThickness=tf,
            filletRadius=radius,
        )
    if shape == "U":
        return o.UShapeProfile(
            depth=depth,
            flangeWidth=width,
            webThickness=tw,
            flangeThickness=tf,
            filletRadius=radius,
        )
    if shape == "rectangleHollow":
        return o.RectangleHollowProfile(
            xDim=width, yDim=depth, wallThickness=tw, outerFilletRadius=radius
        )
    if shape == "circleHollow":
        return o.CircleHollowProfile(radius=depth / 2.0, wallThickness=tw)
    raise FeatureInputError(f"Unsupported section shape: {shape!r}.")


@feature(
    "librarySections.newFrameSection",
    "New Frame Section",
    part="objects",
    fields=[
        text("sectionId", "Section type ID", "F-SEC-1"),
        select(
            "shape",
            "Shape template",
            [
                ("rectangle", "Rectangle"),
                ("circle", "Circle"),
                ("I", "I-Section"),
                ("T", "T-Section"),
                ("U", "Channel (U)"),
                ("rectangleHollow", "Rectangular Hollow (RHS/SHS)"),
                ("circleHollow", "Circular Hollow (CHS)"),
            ],
            "rectangle",
        ),
        number("depthMm", "Depth / Diameter", 500.0, unit="mm", min=20.0),
        number("widthMm", "Width", 300.0, unit="mm", min=20.0),
        number("webMm", "Web / wall thickness", 10.0, unit="mm", min=1.0),
        number("flangeMm", "Flange thickness", 14.0, unit="mm", min=1.0),
        number("filletMm", "Fillet / corner radius", 0.0, unit="mm", min=0.0),
        number("densityKgM3", "Material density", 2400.0, unit="kg/m3", min=100.0),
    ],
    requires_project=False,
)
def new_frame_section(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a validated frame section profile from a template and compute its section properties."""
    profile = _build_profile_from_params(
        values["shape"],
        values["depthMm"],
        values["widthMm"],
        values["webMm"],
        values["flangeMm"],
        values["filletMm"],
    )
    props = section_properties(profile)
    rx = math.sqrt(props.ixx / props.area)
    ry = math.sqrt(props.iyy / props.area)
    mass_kg_m = props.area * 1e-6 * values["densityKgM3"]
    rows = [
        {"property": "Area A", "value": props.area, "unit": "mm2"},
        {"property": "Major inertia Ixx", "value": props.ixx, "unit": "mm4"},
        {"property": "Minor inertia Iyy", "value": props.iyy, "unit": "mm4"},
        {"property": "Torsional constant J", "value": props.j, "unit": "mm4"},
        {"property": "Radius of gyration rx", "value": rx, "unit": "mm"},
        {"property": "Radius of gyration ry", "value": ry, "unit": "mm"},
        {"property": "Mass per unit length", "value": mass_kg_m, "unit": "kg/m"},
    ]
    return result(
        summary={
            "sectionId": values["sectionId"].strip() or "F-SEC-1",
            "shape": values["shape"],
            "areaMm2": props.area,
            "ixxMm4": props.ixx,
            "iyyMm4": props.iyy,
            "jMm4": props.j,
            "massKgPerM": mass_kg_m,
        },
        tables=[
            table(
                "Frame section geometric properties",
                [("property", "Property"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Geometric properties solved via finite-element cross-section analysis on the exact profile."
        ],
    )


@feature(
    "librarySections.sectionFamilies",
    "Section Families",
    part="objects",
    fields=[
        select(
            "source",
            "Section source",
            [
                ("both", "Project objects & standard steel families"),
                ("project", "Project objects only"),
                ("steel", "Standard steel catalogue only"),
            ],
            "both",
        ),
        text("familyFilter", "Filter family or kind (optional)", ""),
    ],
    requires_project=False,
)
def section_families(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Group project object sections and catalogue steel families for assignment."""
    filt = values["familyFilter"].strip().lower()
    src = values["source"]
    rows: list[dict[str, Any]] = []

    if src in ("both", "project"):
        lib, is_proj = objects_or_default(ctx)
        grouped: dict[tuple[str, str], list[str]] = {}
        for obj in lib.objects:
            prof = getattr(obj, "profile", None)
            shape = getattr(prof, "shape", obj.kind)
            key = (obj.kind, shape)
            grouped.setdefault(key, []).append(obj.id)
        for (kind, shape), ids in sorted(grouped.items()):
            label = f"{kind} ({shape})"
            if filt and filt not in label.lower():
                continue
            rows.append(
                {
                    "source": "Project" if is_proj else "Default library",
                    "family": label,
                    "count": len(ids),
                    "sampleMembers": ", ".join(ids[:6]),
                }
            )

    if src in ("both", "steel"):
        with in_force(ctx.root):
            tbl = steel_sections.table_json()
        by_fam: dict[str, list[dict[str, Any]]] = {}
        for sec in tbl["sections"]:
            by_fam.setdefault(sec["family"], []).append(sec)
        for fam in tbl["families"]:
            secs = by_fam.get(fam, [])
            if filt and filt not in fam.lower():
                continue
            if secs:
                rows.append(
                    {
                        "source": "Steel catalogue",
                        "family": fam,
                        "count": len(secs),
                        "sampleMembers": f"{secs[0]['name']} .. {secs[-1]['name']}",
                    }
                )

    return result(
        summary={"familyCount": len(rows), "totalEntries": sum(r["count"] for r in rows)},
        tables=[
            table(
                "Section families",
                [
                    ("source", "Source"),
                    ("family", "Family / Kind"),
                    ("count", "Count"),
                    ("sampleMembers", "Members"),
                ],
                rows,
            )
        ],
        notes=["Standard steel families reflect the active code pack's steel section catalogue."],
    )


@feature(
    "librarySections.importSections",
    "Import Sections",
    part="objects",
    fields=[
        text(
            "sectionsCsv",
            "Sections CSV (id,kind,shape,material,d_mm,b_mm,tw_mm,tf_mm)",
            "id,kind,shape,material,d_mm,b_mm,tw_mm,tf_mm\n"
            "B300x550,beam,rectangle,C24.1,550,300,0,0\n"
            "COL-IPE300,column,I,A572-50,300,150,7.1,10.7\n"
            "BR-SHS120,brace,rectangleHollow,A572-50,120,120,6,6",
        ),
        checkbox("writeExport", "Save validated JSON to 04 Objects/exports", False),
    ],
    requires_project=False,
)
def import_sections(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate external section table definitions into object-type profiles."""
    raw_rows = parse_csv_rows(values["sectionsCsv"])
    built_objects: list[dict[str, Any]] = []
    table_rows: list[dict[str, Any]] = []
    for r in raw_rows:
        try:
            sid = r["id"]
            kind = r.get("kind") or "beam"
            shape = r["shape"]
            mat = r.get("material") or "C24.1"
            d = float(r["d_mm"])
            b = float(r["b_mm"])
            tw = float(r.get("tw_mm") or 8.0)
            tf = float(r.get("tf_mm") or 12.0)
        except (KeyError, ValueError) as exc:
            raise FeatureInputError(
                "CSV must include id, shape, d_mm, b_mm (and tw_mm, tf_mm for steel shapes)."
            ) from exc
        prof = _build_profile_from_params(shape, d, b, max(1.0, tw), max(1.0, tf), 0.0)
        props = section_properties(prof)
        built_objects.append(
            {
                "id": sid,
                "name": sid,
                "kind": kind,
                "material": mat,
                "profile": prof.model_dump(mode="json"),
            }
        )
        table_rows.append(
            {
                "id": sid,
                "kind": kind,
                "shape": shape,
                "areaMm2": props.area,
                "ixxMm4": props.ixx,
                "iyyMm4": props.iyy,
            }
        )

    out_path = ""
    if values["writeExport"]:
        if ctx.root is None:
            raise FeatureInputError("Open a project folder before exporting imported sections.")
        p = save_export(
            ctx,
            "imported-sections.json",
            safe_json({"schema": "saengine.objects/1", "objects": built_objects}),
        )
        out_path = str(p)

    notes = ["All imported shapes were validated against the object-type profile schema."]
    if out_path:
        notes.append(f"Exported validated JSON to {out_path}.")
    return result(
        summary={"importedCount": len(table_rows), "exportPath": out_path or "not exported"},
        tables=[
            table(
                "Imported sections",
                [
                    ("id", "ID"),
                    ("kind", "Kind"),
                    ("shape", "Shape"),
                    ("areaMm2", "Area", "mm2"),
                    ("ixxMm4", "Ixx", "mm4"),
                    ("iyyMm4", "Iyy", "mm4"),
                ],
                table_rows,
            )
        ],
        notes=notes,
    )


@feature(
    "librarySections.rectangularSection",
    "Rectangular Section",
    part="objects",
    fields=[
        number("widthMm", "Width b", 300.0, unit="mm", min=100.0),
        number("depthMm", "Depth h", 500.0, unit="mm", min=100.0),
        number("coverMm", "Clear cover", 40.0, unit="mm", min=15.0),
        number("topBars", "Top bar count", 3.0, min=2.0),
        number("topDiaMm", "Top bar diameter", 16.0, unit="mm", min=8.0),
        number("botBars", "Bottom bar count", 4.0, min=2.0),
        number("botDiaMm", "Bottom bar diameter", 20.0, unit="mm", min=8.0),
        number("tieDiaMm", "Stirrup/tie diameter", 10.0, unit="mm", min=6.0),
        number("fcMpa", "Concrete strength f'c", 28.0, unit="MPa", min=10.0),
        number("fyMpa", "Rebar yield strength fy", 420.0, unit="MPa", min=200.0),
    ],
    requires_project=False,
)
def rectangular_section(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a rectangular RC section with rebar and compute gross properties and steel ratios."""
    b, h, cc = values["widthMm"], values["depthMm"], values["coverMm"]
    n_top, d_top = round(values["topBars"]), values["topDiaMm"]
    n_bot, d_bot = round(values["botBars"]), values["botDiaMm"]
    d_tie = values["tieDiaMm"]
    profile = o.RectangleProfile(xDim=b, yDim=h)
    props = section_properties(profile)

    as_top = n_top * math.pi * d_top**2 / 4.0
    as_bot = n_bot * math.pi * d_bot**2 / 4.0
    as_tot = as_top + as_bot
    d_eff = h - cc - d_tie - d_bot / 2.0
    if d_eff <= 0:
        raise FeatureInputError(
            "Effective depth is non-positive; increase section depth or reduce cover."
        )
    clear_bot = (b - 2 * cc - 2 * d_tie - n_bot * d_bot) / max(1, n_bot - 1)
    rho_bot = as_bot / (b * d_eff)
    rho_gross = as_tot / props.area

    # Balanced / nominal singly reinforced sagging moment estimate (stress block 0.85 f'c)
    a = min(d_eff, as_bot * values["fyMpa"] / (0.85 * values["fcMpa"] * b))
    mn_knm = as_bot * values["fyMpa"] * (d_eff - a / 2.0) / 1e6

    rows = [
        {"metric": "Gross area Ag", "value": props.area, "unit": "mm2"},
        {"metric": "Gross inertia Ixx", "value": props.ixx, "unit": "mm4"},
        {"metric": "Effective depth d", "value": d_eff, "unit": "mm"},
        {"metric": "Top steel As'", "value": as_top, "unit": "mm2"},
        {"metric": "Bottom steel As", "value": as_bot, "unit": "mm2"},
        {"metric": "Gross steel ratio", "value": rho_gross * 100.0, "unit": "%"},
        {"metric": "Bottom bar clear spacing", "value": clear_bot, "unit": "mm"},
        {"metric": "Nominal sagging moment Mn", "value": mn_knm, "unit": "kN-m"},
    ]
    return result(
        summary={
            "areaMm2": props.area,
            "ixxMm4": props.ixx,
            "effectiveDepthMm": d_eff,
            "totalSteelMm2": as_tot,
            "tensionSteelRatio": rho_bot,
            "clearSpacingMm": clear_bot,
            "nominalMomentKnm": mn_knm,
        },
        tables=[
            table(
                "Rectangular RC section summary",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Nominal moment uses rectangular stress block equilibrium ignoring compression steel."
        ],
    )


@feature(
    "librarySections.circularSection",
    "Circular Section",
    part="objects",
    fields=[
        number("diameterMm", "Column diameter D", 500.0, unit="mm", min=150.0),
        number("coverMm", "Clear cover", 40.0, unit="mm", min=15.0),
        number("barCount", "Longitudinal bar count", 8.0, min=4.0),
        number("barDiaMm", "Longitudinal bar diameter", 20.0, unit="mm", min=10.0),
        number("hoopDiaMm", "Hoop/spiral diameter", 10.0, unit="mm", min=6.0),
        number("pitchMm", "Hoop/spiral pitch", 125.0, unit="mm", min=40.0),
        number("fcMpa", "Concrete strength f'c", 28.0, unit="MPa", min=10.0),
        number("fyMpa", "Rebar yield strength fy", 420.0, unit="MPa", min=200.0),
    ],
    requires_project=False,
)
def circular_section(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a circular RC column section with hoop/spiral steel and compute axial & confinement metrics."""
    d_col = values["diameterMm"]
    cc = values["coverMm"]
    n_bars = round(values["barCount"])
    db = values["barDiaMm"]
    dh = values["hoopDiaMm"]
    s = values["pitchMm"]

    profile = o.CircleProfile(radius=d_col / 2.0)
    props = section_properties(profile)
    ast = n_bars * math.pi * db**2 / 4.0
    rho_g = ast / props.area
    d_core = d_col - 2.0 * cc
    if d_core <= 0:
        raise FeatureInputError("Cover exceeds column radius.")
    a_core = math.pi * d_core**2 / 4.0
    d_ring = d_col - 2.0 * cc - 2.0 * dh - db
    clear_arc = (math.pi * max(10.0, d_ring)) / n_bars - db
    ash = math.pi * dh**2 / 4.0
    rho_s = 4.0 * ash / (d_core * s)
    p0_kn = (0.85 * values["fcMpa"] * (props.area - ast) + values["fyMpa"] * ast) / 1e3

    rows = [
        {"metric": "Gross area Ag", "value": props.area, "unit": "mm2"},
        {"metric": "Core area Ach", "value": a_core, "unit": "mm2"},
        {"metric": "Moment of inertia I", "value": props.ixx, "unit": "mm4"},
        {"metric": "Longitudinal steel Ast", "value": ast, "unit": "mm2"},
        {"metric": "Reinforcement ratio", "value": rho_g * 100.0, "unit": "%"},
        {"metric": "Bar clear perimeter spacing", "value": clear_arc, "unit": "mm"},
        {"metric": "Volumetric spiral ratio rho_s", "value": rho_s * 100.0, "unit": "%"},
        {"metric": "Nominal squash load P0", "value": p0_kn, "unit": "kN"},
    ]
    return result(
        summary={
            "areaMm2": props.area,
            "inertiaMm4": props.ixx,
            "steelAreaMm2": ast,
            "steelRatio": rho_g,
            "volumetricRatio": rho_s,
            "squashLoadKn": p0_kn,
        },
        tables=[
            table(
                "Circular column section summary",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Volumetric confinement ratio rho_s = 4*Asp / (D_core * s)."],
    )


@feature(
    "librarySections.tSection",
    "T-Section",
    part="objects",
    fields=[
        number("depthMm", "Overall depth h", 600.0, unit="mm", min=100.0),
        number("flangeWidthMm", "Flange width bf", 1200.0, unit="mm", min=100.0),
        number("webWidthMm", "Web width bw", 300.0, unit="mm", min=50.0),
        number("flangeThickMm", "Flange thickness hf", 150.0, unit="mm", min=20.0),
        number("spanMm", "Beam span (for effective flange check)", 6000.0, unit="mm", min=500.0),
        select(
            "sides",
            "Slab sides",
            [("2", "Interior T-beam (2 sides)"), ("1", "Edge L-beam (1 side)")],
            "2",
        ),
    ],
    requires_project=False,
)
def t_section(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a T-beam section, compute exact section properties, and check effective flange width."""
    h = values["depthMm"]
    bf = values["flangeWidthMm"]
    bw = values["webWidthMm"]
    hf = values["flangeThickMm"]
    if bf <= bw or hf >= h:
        raise FeatureInputError("Require flangeWidth > webWidth and flangeThick < depth.")
    profile = o.TShapeProfile(depth=h, flangeWidth=bf, webThickness=bw, flangeThickness=hf)
    props = section_properties(profile)
    with in_force(ctx.root):
        beff = effective_flange(values["spanMm"], bw, hf, int(values["sides"]))
    beff_val = beff if beff is not None else bf
    rows = [
        {"metric": "Gross area A", "value": props.area, "unit": "mm2"},
        {"metric": "Centroid y from bottom", "value": props.cy, "unit": "mm"},
        {"metric": "Major inertia Ixx", "value": props.ixx, "unit": "mm4"},
        {"metric": "Minor inertia Iyy", "value": props.iyy, "unit": "mm4"},
        {"metric": "Torsional constant J", "value": props.j, "unit": "mm4"},
        {"metric": "Code-pack effective flange limit", "value": beff_val, "unit": "mm"},
    ]
    return result(
        summary={
            "areaMm2": props.area,
            "centroidYMm": props.cy,
            "ixxMm4": props.ixx,
            "iyyMm4": props.iyy,
            "effectiveFlangeLimitMm": beff_val,
            "withinEffectiveWidth": bf <= beff_val + 1e-6,
        },
        tables=[
            table(
                "T-section geometric properties",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Effective flange width limit is read from the active code pack."],
    )


@feature(
    "librarySections.boxSection",
    "Box Section",
    part="objects",
    fields=[
        number("widthMm", "Outer width B", 800.0, unit="mm", min=100.0),
        number("depthMm", "Outer depth H", 1000.0, unit="mm", min=100.0),
        number("wallThickMm", "Wall thickness t", 150.0, unit="mm", min=10.0),
        number("densityKgM3", "Material density", 2400.0, unit="kg/m3", min=100.0),
    ],
    requires_project=False,
)
def box_section(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a hollow box section with wall thickness and compute flexural and Bredt torsional properties."""
    b, h, t = values["widthMm"], values["depthMm"], values["wallThickMm"]
    if 2.0 * t >= min(b, h):
        raise FeatureInputError("Wall thickness must be less than half of both outer dimensions.")
    profile = o.RectangleHollowProfile(xDim=b, yDim=h, wallThickness=t)
    props = section_properties(profile)
    # Bredt thin-walled enclosed area A0
    a0 = (b - t) * (h - t)
    p_mid = 2.0 * ((b - t) + (h - t))
    j_bredt = 4.0 * a0**2 * t / p_mid
    mass_kg_m = props.area * 1e-6 * values["densityKgM3"]
    rows = [
        {"metric": "Net area A", "value": props.area, "unit": "mm2"},
        {"metric": "Major inertia Ixx", "value": props.ixx, "unit": "mm4"},
        {"metric": "Minor inertia Iyy", "value": props.iyy, "unit": "mm4"},
        {"metric": "FEM torsion constant J", "value": props.j, "unit": "mm4"},
        {"metric": "Bredt thin-wall J", "value": j_bredt, "unit": "mm4"},
        {"metric": "Enclosed mid-line area A0", "value": a0, "unit": "mm2"},
        {"metric": "Clear wall slenderness (H-2t)/t", "value": (h - 2 * t) / t, "unit": "-"},
        {"metric": "Mass per metre", "value": mass_kg_m, "unit": "kg/m"},
    ]
    return result(
        summary={
            "areaMm2": props.area,
            "ixxMm4": props.ixx,
            "iyyMm4": props.iyy,
            "jMm4": props.j,
            "enclosedAreaMm2": a0,
            "massKgPerM": mass_kg_m,
        },
        tables=[
            table(
                "Hollow box section properties",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Compares finite-element St. Venant torsion constant with Bredt closed-cell formula."
        ],
    )


@feature(
    "librarySections.iSection",
    "I-Section",
    part="objects",
    fields=[
        text("catalogueName", "Catalogue name (blank = custom dims)", "IPE 300"),
        number("depthMm", "Overall depth d", 300.0, unit="mm", min=50.0),
        number("widthMm", "Flange width bf", 150.0, unit="mm", min=30.0),
        number("twMm", "Web thickness tw", 7.1, unit="mm", min=2.0),
        number("tfMm", "Flange thickness tf", 10.7, unit="mm", min=2.0),
        number("filletMm", "Root fillet radius r", 15.0, unit="mm", min=0.0),
    ],
    requires_project=False,
)
def i_section_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a rolled or welded I-section from catalogue lookup or custom plate dimensions."""
    cname = values["catalogueName"].strip()
    sec: steel_sections.SteelSection | None = None
    if cname:
        with in_force(ctx.root):
            sec = steel_sections.find(cname)
    if sec is None:
        sec = steel_sections.i_section(
            cname or "Custom I",
            "I",
            values["depthMm"],
            values["widthMm"],
            values["twMm"],
            values["tfMm"],
            values["filletMm"],
        )
    flange_slenderness = (sec.b / 2.0) / sec.tf
    web_slenderness = (sec.h - 2.0 * sec.tf - 2.0 * sec.r) / sec.tw
    rows = [
        {"metric": "Depth h", "value": sec.h, "unit": "mm"},
        {"metric": "Width b", "value": sec.b, "unit": "mm"},
        {"metric": "Area A", "value": sec.A, "unit": "mm2"},
        {"metric": "Major inertia Ix", "value": sec.Ix, "unit": "mm4"},
        {"metric": "Minor inertia Iy", "value": sec.Iy, "unit": "mm4"},
        {"metric": "Elastic modulus Sx", "value": sec.Sx, "unit": "mm3"},
        {"metric": "Plastic modulus Zx", "value": sec.Zx, "unit": "mm3"},
        {"metric": "Torsional constant J", "value": sec.J, "unit": "mm4"},
        {"metric": "Warping constant Cw", "value": sec.Cw, "unit": "mm6"},
        {"metric": "Flange slenderness b/(2tf)", "value": flange_slenderness, "unit": "-"},
        {"metric": "Web slenderness hw/tw", "value": web_slenderness, "unit": "-"},
        {"metric": "Unit mass", "value": sec.mass, "unit": "kg/m"},
    ]
    return result(
        summary={
            "name": sec.name,
            "areaMm2": sec.A,
            "ixMm4": sec.Ix,
            "iyMm4": sec.Iy,
            "zxMm3": sec.Zx,
            "jMm4": sec.J,
            "cwMm6": sec.Cw,
            "massKgPerM": sec.mass,
        },
        tables=[
            table(
                f"I-section properties ({sec.name})",
                [("metric", "Property"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            f"Section source: {sec.family} ({'catalogue match' if cname and sec.family != 'I' else 'custom dims'})."
        ],
    )


@feature(
    "librarySections.hollowSection",
    "Hollow Section",
    part="objects",
    fields=[
        select(
            "kind",
            "Hollow shape",
            [("RHS", "RHS / SHS (Rectangular/Square)"), ("CHS", "CHS (Circular pipe)")],
            "RHS",
        ),
        number("depthMm", "Depth H or outside diameter D", 150.0, unit="mm", min=20.0),
        number("widthMm", "Width B (ignored for CHS)", 150.0, unit="mm", min=20.0),
        number("wallMm", "Wall thickness t", 8.0, unit="mm", min=1.5),
    ],
    requires_project=False,
)
def hollow_section_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a rectangular, square, or circular hollow steel section and compute properties."""
    kind = values["kind"]
    d, b, t = values["depthMm"], values["widthMm"], values["wallMm"]
    if kind == "CHS":
        if 2.0 * t >= d:
            raise FeatureInputError("Wall thickness must be less than pipe radius.")
        sec = steel_sections.chs_section(f"CHS {d:g}x{t:g}", d, t)
        slender = d / t
    else:
        if 2.0 * t >= min(d, b):
            raise FeatureInputError("Wall thickness must be less than half of width and depth.")
        fam = "SHS" if abs(d - b) < 0.6 else "RHS"
        sec = steel_sections.rhs_section(f"{fam} {d:g}x{b:g}x{t:g}", fam, d, b, t)
        slender = (max(d, b) - 3.0 * t) / t

    rows = [
        {"metric": "Area A", "value": sec.A, "unit": "mm2"},
        {"metric": "Major inertia Ix", "value": sec.Ix, "unit": "mm4"},
        {"metric": "Minor inertia Iy", "value": sec.Iy, "unit": "mm4"},
        {"metric": "Plastic modulus Zx", "value": sec.Zx, "unit": "mm3"},
        {"metric": "Radius of gyration rx", "value": sec.rx, "unit": "mm"},
        {"metric": "Torsional constant J", "value": sec.J, "unit": "mm4"},
        {"metric": "Wall slenderness ratio", "value": slender, "unit": "-"},
        {"metric": "Unit mass", "value": sec.mass, "unit": "kg/m"},
    ]
    return result(
        summary={
            "name": sec.name,
            "areaMm2": sec.A,
            "ixMm4": sec.Ix,
            "iyMm4": sec.Iy,
            "jMm4": sec.J,
            "wallSlenderness": slender,
            "massKgPerM": sec.mass,
        },
        tables=[
            table(
                f"Hollow section properties ({sec.name})",
                [("metric", "Property"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Corner radii and thin-walled closed-cell torsion J follow steel_sections formulas."
        ],
    )


@feature(
    "librarySections.angleSection",
    "Angle Section",
    part="objects",
    fields=[
        number("legAMm", "Vertical leg depth d", 100.0, unit="mm", min=20.0),
        number("legBMm", "Horizontal leg width b", 100.0, unit="mm", min=20.0),
        number("thickMm", "Leg thickness t", 10.0, unit="mm", min=2.0),
        number("rootRadiusMm", "Root fillet radius r1", 8.0, unit="mm", min=0.0),
        number("toeRadiusMm", "Toe radius r2", 4.0, unit="mm", min=0.0),
    ],
    requires_project=False,
)
def angle_section_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define an equal or unequal steel angle section with principal-axis properties."""
    d, b, t = values["legAMm"], values["legBMm"], values["thickMm"]
    if t >= min(d, b):
        raise FeatureInputError("Angle thickness must be smaller than both leg lengths.")
    sec = steel_sections.angle_section(
        f"L {d:g}x{b:g}x{t:g}", d, b, t, values["rootRadiusMm"], values["toeRadiusMm"]
    )
    rows = [
        {"metric": "Area A", "value": sec.A, "unit": "mm2"},
        {"metric": "Centroid cx (from back)", "value": sec.cx, "unit": "mm"},
        {"metric": "Centroid cy (from bottom)", "value": sec.cy, "unit": "mm"},
        {"metric": "Geometric inertia Ix", "value": sec.Ix, "unit": "mm4"},
        {"metric": "Geometric inertia Iy", "value": sec.Iy, "unit": "mm4"},
        {"metric": "Principal major Iu", "value": sec.Iu or 0.0, "unit": "mm4"},
        {"metric": "Principal minor Iv", "value": sec.Iv or 0.0, "unit": "mm4"},
        {"metric": "Least radius of gyration rv", "value": sec.rv or sec.r_min, "unit": "mm"},
        {"metric": "Torsional constant J", "value": sec.J, "unit": "mm4"},
        {"metric": "Unit mass", "value": sec.mass, "unit": "kg/m"},
    ]
    return result(
        summary={
            "name": sec.name,
            "areaMm2": sec.A,
            "iuMm4": sec.Iu or sec.Ix,
            "ivMm4": sec.Iv or sec.Iy,
            "rvMm": sec.rv or sec.r_min,
            "massKgPerM": sec.mass,
        },
        tables=[
            table(
                f"Angle section properties ({sec.name})",
                [("metric", "Property"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Principal moments Iu, Iv and minimum radius rv govern single-angle buckling."],
    )


@feature(
    "librarySections.channelSection",
    "Channel Section",
    part="objects",
    fields=[
        select(
            "kind",
            "Channel type",
            [("U", "Rolled parallel-flange channel (U)"), ("C", "Cold-formed lipped channel (C)")],
            "U",
        ),
        number("depthMm", "Overall depth d", 200.0, unit="mm", min=40.0),
        number("widthMm", "Flange width bf", 75.0, unit="mm", min=20.0),
        number("twMm", "Web / sheet thickness", 6.1, unit="mm", min=1.0),
        number("tfMm", "Flange thickness (U only)", 11.4, unit="mm", min=1.0),
        number("lipMm", "Lip length (C only)", 20.0, unit="mm", min=5.0),
    ],
    requires_project=False,
)
def channel_section_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define rolled U-channels or cold-formed lipped C-channels and compute properties."""
    kind = values["kind"]
    d, b, tw = values["depthMm"], values["widthMm"], values["twMm"]
    if kind == "U":
        tf = values["tfMm"]
        if 2.0 * tf >= d or tw >= b:
            raise FeatureInputError("Channel flange/web thicknesses exceed section dimensions.")
        prof: o.Profile = o.UShapeProfile(
            depth=d, flangeWidth=b, webThickness=tw, flangeThickness=tf
        )
        sec = steel_sections.channel_section(f"U {d:g}x{b:g}", "U", d, b, tw, tf, 0.0)
        cw = sec.Cw
        mass = sec.mass
        props = section_properties(prof)
    else:
        lip = values["lipMm"]
        if 2.0 * lip >= d or 2.0 * tw >= b:
            raise FeatureInputError(
                "Lipped channel lip or wall thickness exceeds overall dimensions."
            )
        prof = o.CShapeProfile(depth=d, width=b, wallThickness=tw, girth=lip)
        props = section_properties(prof)
        cw = 0.0
        mass = props.area * 1e-6 * 7850.0

    rows = [
        {"metric": "Area A", "value": props.area, "unit": "mm2"},
        {"metric": "Centroid cx from web back", "value": props.cx, "unit": "mm"},
        {"metric": "Major inertia Ixx", "value": props.ixx, "unit": "mm4"},
        {"metric": "Minor inertia Iyy", "value": props.iyy, "unit": "mm4"},
        {"metric": "Torsional constant J", "value": props.j, "unit": "mm4"},
        {"metric": "Warping constant Cw", "value": cw, "unit": "mm6"},
        {"metric": "Unit mass", "value": mass, "unit": "kg/m"},
    ]
    return result(
        summary={
            "kind": kind,
            "areaMm2": props.area,
            "ixxMm4": props.ixx,
            "iyyMm4": props.iyy,
            "jMm4": props.j,
            "massKgPerM": mass,
        },
        tables=[
            table(
                "Channel section properties",
                [("metric", "Property"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Geometric properties solved on exact channel / lipped channel profile."],
    )


@feature(
    "librarySections.compositeBeam",
    "Composite Beam",
    part="objects",
    fields=[
        number("steelDepthMm", "Steel beam depth d", 300.0, unit="mm", min=100.0),
        number("steelWidthMm", "Steel flange width bf", 150.0, unit="mm", min=50.0),
        number("twMm", "Web thickness tw", 7.1, unit="mm", min=2.0),
        number("tfMm", "Flange thickness tf", 10.7, unit="mm", min=2.0),
        number("slabThickMm", "Concrete slab thickness tc", 130.0, unit="mm", min=50.0),
        number("effWidthMm", "Effective slab width b_eff", 1500.0, unit="mm", min=200.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Steel yield fy", 345.0, unit="MPa", min=200.0),
    ],
    requires_project=False,
)
def composite_beam_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute transformed elastic and full-composite plastic flexural properties of a steel-concrete beam."""
    sec = steel_sections.i_section(
        "Beam",
        "I",
        values["steelDepthMm"],
        values["steelWidthMm"],
        values["twMm"],
        values["tfMm"],
        0.0,
    )
    with in_force(ctx.root):
        ec, ec_note = concrete_modulus(values["fcMpa"])
    es = 200000.0
    n = es / ec
    tc = values["slabThickMm"]
    beff = values["effWidthMm"]
    ac_trans = (beff / n) * tc
    ic_trans = (beff / n) * tc**3 / 12.0

    # Datum at bottom of steel beam
    ys = sec.h / 2.0
    yc = sec.h + tc / 2.0
    a_tot = sec.A + ac_trans
    y_na = (sec.A * ys + ac_trans * yc) / a_tot
    i_comp = sec.Ix + sec.A * (y_na - ys) ** 2 + ic_trans + ac_trans * (yc - y_na) ** 2
    s_bot_steel = i_comp / y_na
    s_top_conc = i_comp / (sec.h + tc - y_na)

    # Full composite plastic moment (sagging)
    c_conc = 0.85 * values["fcMpa"] * beff * tc
    t_steel = sec.A * values["fyMpa"]
    if c_conc >= t_steel:
        a_block = t_steel / (0.85 * values["fcMpa"] * beff)
        mp_knm = t_steel * (yc + tc / 2.0 - a_block / 2.0 - ys) / 1e6
        pna_loc = "Inside concrete slab"
    else:
        # PNA inside steel top flange or web (approximate steel compression force)
        c_net = (t_steel - c_conc) / 2.0
        mp_knm = (
            c_conc * (yc - ys) + sec.Zx * values["fyMpa"] * (1.0 - (c_net / t_steel) ** 2)
        ) / 1e6
        pna_loc = "Inside steel section"

    rows = [
        {"metric": "Modular ratio n = Es/Ec", "value": n, "unit": "-"},
        {"metric": "Steel area As", "value": sec.A, "unit": "mm2"},
        {"metric": "Transformed inertia I_comp", "value": i_comp, "unit": "mm4"},
        {"metric": "Elastic neutral axis from bottom", "value": y_na, "unit": "mm"},
        {"metric": "Bottom steel section modulus", "value": s_bot_steel, "unit": "mm3"},
        {"metric": "Top concrete modulus (steel eq.)", "value": s_top_conc, "unit": "mm3"},
        {"metric": "Plastic sagging capacity Mp", "value": mp_knm, "unit": "kN-m"},
    ]
    return result(
        summary={
            "modularRatio": n,
            "compositeInertiaMm4": i_comp,
            "neutralAxisMm": y_na,
            "plasticMomentKnm": mp_knm,
            "pnaLocation": pna_loc,
        },
        tables=[
            table(
                "Composite beam transformed & plastic properties",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[f"Concrete modulus: {ec_note}. Assumes full shear connection for Mp."],
    )


@feature(
    "librarySections.encasedColumn",
    "Encased Column",
    part="objects",
    fields=[
        number("colWidthMm", "Concrete width B", 450.0, unit="mm", min=200.0),
        number("colDepthMm", "Concrete depth H", 450.0, unit="mm", min=200.0),
        number("steelDepthMm", "Embedded steel depth d", 240.0, unit="mm", min=80.0),
        number("steelWidthMm", "Embedded steel width bf", 240.0, unit="mm", min=50.0),
        number("twMm", "Steel web thickness tw", 10.0, unit="mm", min=3.0),
        number("tfMm", "Steel flange thickness tf", 17.0, unit="mm", min=4.0),
        number("rebarCount", "Longitudinal rebar count", 8.0, min=4.0),
        number("rebarDiaMm", "Longitudinal rebar diameter", 16.0, unit="mm", min=10.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        number("fySteelMpa", "Steel section fy", 345.0, unit="MPa", min=200.0),
        number("fyRebarMpa", "Rebar fy", 420.0, unit="MPa", min=200.0),
    ],
    requires_project=False,
)
def encased_column_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a concrete-encased steel composite column and compute squash load and effective stiffness."""
    b, h = values["colWidthMm"], values["colDepthMm"]
    if values["steelWidthMm"] >= b or values["steelDepthMm"] >= h:
        raise FeatureInputError("Embedded steel section must fit inside the concrete dimensions.")
    sec = steel_sections.i_section(
        "Core",
        "I",
        values["steelDepthMm"],
        values["steelWidthMm"],
        values["twMm"],
        values["tfMm"],
        0.0,
    )
    a_gross = b * h
    a_rebar = round(values["rebarCount"]) * math.pi * values["rebarDiaMm"] ** 2 / 4.0
    a_conc = a_gross - sec.A - a_rebar
    with in_force(ctx.root):
        ec, _ = concrete_modulus(values["fcMpa"])
    es = 200000.0
    p0_kn = (
        0.85 * values["fcMpa"] * a_conc
        + values["fySteelMpa"] * sec.A
        + values["fyRebarMpa"] * a_rebar
    ) / 1e3
    steel_share = (values["fySteelMpa"] * sec.A) / (p0_kn * 1e3)
    ic_gross = b * h**3 / 12.0 - sec.Ix
    c1 = min(0.3, 0.1 + 2.0 * (sec.A / (a_conc + sec.A)))
    ei_eff_knm2 = (es * sec.Ix + c1 * ec * ic_gross) / 1e9

    rows = [
        {"metric": "Gross area Ag", "value": a_gross, "unit": "mm2"},
        {"metric": "Steel core area As", "value": sec.A, "unit": "mm2"},
        {"metric": "Rebar area Ar", "value": a_rebar, "unit": "mm2"},
        {"metric": "Net concrete area Ac", "value": a_conc, "unit": "mm2"},
        {"metric": "Steel ratio As / Ag", "value": sec.A / a_gross * 100.0, "unit": "%"},
        {"metric": "Steel contribution ratio delta", "value": steel_share, "unit": "-"},
        {"metric": "Squash capacity P0", "value": p0_kn, "unit": "kN"},
        {"metric": "Effective flexural stiffness EI_eff", "value": ei_eff_knm2, "unit": "kN-m2"},
    ]
    return result(
        summary={
            "steelAreaMm2": sec.A,
            "steelRatio": sec.A / a_gross,
            "squashLoadKn": p0_kn,
            "eiEffKnM2": ei_eff_knm2,
            "steelContribution": steel_share,
        },
        tables=[
            table(
                "Encased composite column properties",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Composite flexural stiffness uses EI_eff = Es*Is + c1*Ec*Ic."],
    )


@feature(
    "librarySections.filledTube",
    "Filled Tube",
    part="objects",
    fields=[
        select(
            "shape",
            "Tube shape",
            [("CHS", "Circular filled tube (CHS)"), ("RHS", "Rectangular filled tube (RHS/SHS)")],
            "CHS",
        ),
        number("depthMm", "Outer diameter D or depth H", 350.0, unit="mm", min=80.0),
        number("widthMm", "Outer width B (RHS only)", 350.0, unit="mm", min=80.0),
        number("wallMm", "Tube wall thickness t", 10.0, unit="mm", min=2.0),
        number("fcMpa", "Concrete infill f'c", 35.0, unit="MPa", min=15.0),
        number("fyMpa", "Tube yield fy", 345.0, unit="MPa", min=200.0),
    ],
    requires_project=False,
)
def filled_tube_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a concrete-filled hollow steel tube and compute composite capacity and wall compactness."""
    shape = values["shape"]
    d, b, t = values["depthMm"], values["widthMm"], values["wallMm"]
    if shape == "CHS":
        if 2.0 * t >= d:
            raise FeatureInputError("Wall thickness exceeds tube radius.")
        sec = steel_sections.chs_section(f"CFST {d:g}x{t:g}", d, t)
        a_conc = math.pi * (d - 2.0 * t) ** 2 / 4.0
        ic = math.pi * (d - 2.0 * t) ** 4 / 64.0
        slenderness = d / t
        c2 = 0.95
    else:
        if 2.0 * t >= min(d, b):
            raise FeatureInputError("Wall thickness exceeds half of tube dimensions.")
        sec = steel_sections.rhs_section(f"CFST {d:g}x{b:g}x{t:g}", "RHS", d, b, t)
        a_conc = (d - 2.0 * t) * (b - 2.0 * t)
        ic = (b - 2.0 * t) * (d - 2.0 * t) ** 3 / 12.0
        slenderness = max(d - 2.0 * t, b - 2.0 * t) / t
        c2 = 0.85
    with in_force(ctx.root):
        ec, _ = concrete_modulus(values["fcMpa"])
    es = 200000.0
    p0_kn = (c2 * values["fcMpa"] * a_conc + values["fyMpa"] * sec.A) / 1e3
    c3 = min(0.9, 0.45 + 3.0 * (sec.A / (sec.A + a_conc)))
    ei_eff_knm2 = (es * sec.Ix + c3 * ec * ic) / 1e9
    rows = [
        {"metric": "Steel tube area As", "value": sec.A, "unit": "mm2"},
        {"metric": "Concrete core area Ac", "value": a_conc, "unit": "mm2"},
        {"metric": "Tube steel ratio", "value": sec.A / (sec.A + a_conc) * 100.0, "unit": "%"},
        {"metric": "Wall slenderness D/t or b/t", "value": slenderness, "unit": "-"},
        {"metric": "Squash axial capacity P0", "value": p0_kn, "unit": "kN"},
        {"metric": "Effective stiffness EI_eff", "value": ei_eff_knm2, "unit": "kN-m2"},
    ]
    return result(
        summary={
            "steelAreaMm2": sec.A,
            "concreteAreaMm2": a_conc,
            "wallSlenderness": slenderness,
            "squashLoadKn": p0_kn,
            "eiEffKnM2": ei_eff_knm2,
        },
        tables=[
            table(
                "Concrete-filled tube properties",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Circular infill factor 0.95 accounts for triaxial confinement; rectangular uses 0.85."
        ],
    )


@feature(
    "librarySections.parametricISection",
    "Parametric I-Section",
    part="objects",
    fields=[
        number("depthMm", "Overall depth d", 450.0, unit="mm", min=80.0),
        number("topFlangeMm", "Flange width bf", 200.0, unit="mm", min=40.0),
        number("webThickMm", "Web thickness tw", 9.0, unit="mm", min=3.0),
        number("flangeThickMm", "Flange thickness tf", 14.0, unit="mm", min=4.0),
        number("filletMm", "Weld/root fillet r", 0.0, unit="mm", min=0.0),
        number("fyMpa", "Steel yield fy", 345.0, unit="MPa", min=150.0),
    ],
    requires_project=False,
)
def parametric_i_section(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build a parametric I-section and evaluate shear area, plastic shape factor, and compactness."""
    d, bf = values["depthMm"], values["topFlangeMm"]
    tw, tf = values["webThickMm"], values["flangeThickMm"]
    if 2.0 * tf >= d or tw >= bf:
        raise FeatureInputError("Flange/web thicknesses must fit within overall depth and width.")
    sec = steel_sections.i_section("Parametric I", "I", d, bf, tw, tf, values["filletMm"])
    shear_area = d * tw
    shape_factor = sec.Zx / sec.Sx
    lambda_f = (bf / 2.0) / tf
    lambda_w = (d - 2.0 * tf) / tw
    e = 200000.0
    limit_f = 0.38 * math.sqrt(e / values["fyMpa"])
    limit_w = 3.76 * math.sqrt(e / values["fyMpa"])
    rows = [
        {"metric": "Area A", "value": sec.A, "unit": "mm2"},
        {"metric": "Shear area Av = d*tw", "value": shear_area, "unit": "mm2"},
        {"metric": "Major inertia Ix", "value": sec.Ix, "unit": "mm4"},
        {"metric": "Minor inertia Iy", "value": sec.Iy, "unit": "mm4"},
        {"metric": "Elastic Sx", "value": sec.Sx, "unit": "mm3"},
        {"metric": "Plastic Zx", "value": sec.Zx, "unit": "mm3"},
        {"metric": "Shape factor Zx/Sx", "value": shape_factor, "unit": "-"},
        {"metric": "Flange ratio bf/(2tf)", "value": lambda_f, "unit": "-"},
        {"metric": "Web ratio hw/tw", "value": lambda_w, "unit": "-"},
    ]
    return result(
        summary={
            "areaMm2": sec.A,
            "shearAreaMm2": shear_area,
            "ixMm4": sec.Ix,
            "zxMm3": sec.Zx,
            "shapeFactor": shape_factor,
            "flangeCompact": lambda_f <= limit_f,
            "webCompact": lambda_w <= limit_w,
        },
        tables=[
            table(
                "Parametric I-section metrics",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            f"Compactness threshold check vs sqrt(E/fy): flange limit {limit_f:.1f}, web limit {limit_w:.1f}."
        ],
    )


@feature(
    "librarySections.taperedSection",
    "Tapered Section",
    part="objects",
    fields=[
        number("lengthMm", "Member length", 6000.0, unit="mm", min=300.0),
        number("depthStartMm", "Depth at start", 600.0, unit="mm", min=100.0),
        number("depthEndMm", "Depth at end", 300.0, unit="mm", min=100.0),
        number("flangeWidthMm", "Flange width bf", 200.0, unit="mm", min=50.0),
        number("twMm", "Web thickness tw", 8.0, unit="mm", min=3.0),
        number("tfMm", "Flange thickness tf", 12.0, unit="mm", min=4.0),
    ],
    requires_project=False,
)
def tapered_section_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a linearly tapered welded I-section haunch/rafter and integrate properties along length."""
    L = values["lengthMm"]
    d0, d1 = values["depthStartMm"], values["depthEndMm"]
    bf, tw, tf = values["flangeWidthMm"], values["twMm"], values["tfMm"]
    if 2.0 * tf >= min(d0, d1):
        raise FeatureInputError("Twice flange thickness must be less than minimum tapered depth.")
    stations = 5
    rows: list[dict[str, Any]] = []
    areas: list[float] = []
    for i in range(stations):
        frac = i / (stations - 1)
        d = d0 + (d1 - d0) * frac
        sec = steel_sections.i_section(f"x={frac:.2f}L", "I", d, bf, tw, tf, 0.0)
        areas.append(sec.A)
        rows.append(
            {
                "station": round(frac * L, 1),
                "depthMm": d,
                "areaMm2": sec.A,
                "ixMm4": sec.Ix,
                "sxMm3": sec.Sx,
                "massKgPerM": sec.mass,
            }
        )
    avg_area = sum(areas) / len(areas)
    total_mass = avg_area * 1e-6 * (L / 1000.0) * 7850.0
    taper_angle_deg = math.degrees(math.atan2(abs(d0 - d1), L))
    return result(
        summary={
            "taperAngleDeg": taper_angle_deg,
            "startIxMm4": rows[0]["ixMm4"],
            "endIxMm4": rows[-1]["ixMm4"],
            "totalMassKg": total_mass,
        },
        tables=[
            table(
                "Tapered section profile stations",
                [
                    ("station", "Position x", "mm"),
                    ("depthMm", "Depth", "mm"),
                    ("areaMm2", "Area", "mm2"),
                    ("ixMm4", "Ix", "mm4"),
                    ("sxMm3", "Sx", "mm3"),
                    ("massKgPerM", "Unit mass", "kg/m"),
                ],
                rows,
            )
        ],
        notes=[
            "Linear web depth taper; total mass integrates average cross-section area at 7850 kg/m3."
        ],
    )


@feature(
    "librarySections.propertySummaryTable",
    "Property Summary Table",
    part="objects",
    fields=[
        text("kindFilter", "Filter by object kind (optional)", ""),
    ],
    requires_project=False,
)
def property_summary_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate area, inertias, torsion constant, and radii of gyration for all library sections."""
    lib, is_proj = objects_or_default(ctx)
    mats, _ = materials_or_default(ctx)
    filt = values["kindFilter"].strip().lower()
    rows: list[dict[str, Any]] = []

    for obj in lib.objects:
        if filt and filt not in obj.kind.lower():
            continue
        prof = getattr(obj, "profile", None)
        if prof is None:
            continue
        if isinstance(prof, o.DesignedProfile) and ctx.root is None:
            continue
        with in_force(ctx.root):
            props = section_properties(prof)
        mat = mats.get(obj.material)
        density = mat.mechanical.density if mat else 2400.0
        mass_kg_m = props.area * 1e-6 * density
        rows.append(
            {
                "id": obj.id,
                "kind": obj.kind,
                "shape": prof.shape,
                "areaMm2": props.area,
                "ixxMm4": props.ixx,
                "iyyMm4": props.iyy,
                "jMm4": props.j,
                "rxMm": math.sqrt(props.ixx / props.area),
                "ryMm": math.sqrt(props.iyy / props.area),
                "massKgPerM": mass_kg_m,
            }
        )
    if not rows:
        raise FeatureInputError("No framed section profiles matched the filter.")
    return result(
        summary={
            "sectionCount": len(rows),
            "source": "project" if is_proj else "default library",
            "maxAreaMm2": max(r["areaMm2"] for r in rows),
        },
        tables=[
            table(
                "Library section property summary",
                [
                    ("id", "Object ID"),
                    ("kind", "Kind"),
                    ("shape", "Shape"),
                    ("areaMm2", "Area", "mm2"),
                    ("ixxMm4", "Ixx", "mm4"),
                    ("iyyMm4", "Iyy", "mm4"),
                    ("jMm4", "J", "mm4"),
                    ("rxMm", "rx", "mm"),
                    ("ryMm", "ry", "mm"),
                    ("massKgPerM", "Mass", "kg/m"),
                ],
                rows,
            )
        ],
        notes=[
            "Section properties computed from profile dimensions using finite-element cross-section analysis."
        ],
    )


@feature(
    "librarySections.effectiveSectionCheck",
    "Effective Section Check",
    part="objects",
    fields=[
        number("depthMm", "Section depth d", 200.0, unit="mm", min=40.0),
        number("widthMm", "Flange width b", 75.0, unit="mm", min=20.0),
        number("thickMm", "Plate/sheet thickness t", 2.0, unit="mm", min=0.5),
        number("fyMpa", "Yield strength fy", 350.0, unit="MPa", min=150.0),
        number("eMpa", "Elastic modulus E", 210000.0, unit="MPa", min=50000.0),
    ],
    requires_project=False,
)
def effective_section_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute effective widths and reduced properties for slender plates under local buckling."""
    d, b, t = values["depthMm"], values["widthMm"], values["thickMm"]
    fy, e = values["fyMpa"], values["eMpa"]
    if 2.0 * t >= min(d, b):
        raise FeatureInputError("Wall thickness exceeds half of section depth or width.")

    def _winter(plate_w: float, k_plate: float) -> tuple[float, float, float]:
        fcr = k_plate * (math.pi**2 * e) / (12.0 * (1.0 - 0.3**2)) * (t / plate_w) ** 2
        lam_p = math.sqrt(fy / fcr)
        rho = 1.0 if lam_p <= 0.673 else min(1.0, (1.0 - 0.22 / lam_p) / lam_p)
        return lam_p, rho, rho * plate_w

    # Stiffened web (k=4.0) and unstiffened flange outstand (k=0.43) under uniform compression
    hw = d - 2.0 * t
    bf = b - t
    lam_w, rho_w, hw_eff = _winter(hw, 4.0)
    lam_f, rho_f, bf_eff = _winter(bf, 0.43)

    a_gross = (hw + 2.0 * bf) * t
    a_eff = (hw_eff + 2.0 * bf_eff) * t
    i_gross = t * hw**3 / 12.0 + 2.0 * bf * t * (d / 2.0 - t / 2.0) ** 2
    i_eff = t * hw_eff**3 / 12.0 + 2.0 * bf_eff * t * (d / 2.0 - t / 2.0) ** 2

    rows = [
        {
            "element": "Web (stiffened k=4.0)",
            "grossMm": hw,
            "lambdaP": lam_w,
            "rho": rho_w,
            "effMm": hw_eff,
        },
        {
            "element": "Flange (unstiffened k=0.43)",
            "grossMm": bf,
            "lambdaP": lam_f,
            "rho": rho_f,
            "effMm": bf_eff,
        },
    ]
    return result(
        summary={
            "grossAreaMm2": a_gross,
            "effectiveAreaMm2": a_eff,
            "areaReductionRatio": a_eff / a_gross,
            "grossIxMm4": i_gross,
            "effectiveIxMm4": i_eff,
            "isSlender": a_eff < a_gross - 1e-6,
        },
        tables=[
            table(
                "Effective plate width reduction (Winter curve)",
                [
                    ("element", "Plate element"),
                    ("grossMm", "Gross width", "mm"),
                    ("lambdaP", "Slenderness lambda_p"),
                    ("rho", "Reduction rho"),
                    ("effMm", "Effective width", "mm"),
                ],
                rows,
            )
        ],
        notes=[
            "Uses Winter's effective-width formula rho = (1 - 0.22/lambda_p)/lambda_p for lambda_p > 0.673."
        ],
    )

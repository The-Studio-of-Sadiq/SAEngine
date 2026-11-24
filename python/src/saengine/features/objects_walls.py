"""Objects - Walls & Slabs tab: wall/slab types, openings, coupling beams, boundary zones & analysis."""

from __future__ import annotations

import math
from typing import Any

from saengine.design import walls as wall_design
from saengine.design.rc_detailing import concrete_modulus
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
from saengine.report.clauses import in_force


@feature(
    "objWalls.newWallType",
    "New Wall Type",
    part="objects",
    fields=[
        text("wallId", "Wall type ID", "W250"),
        number("thicknessMm", "Core structural thickness", 250.0, unit="mm", min=75.0),
        number("plasterEachSideMm", "Plaster/finish thickness per side", 15.0, unit="mm", min=0.0),
        number("coreDensityKgM3", "Core material density", 2400.0, unit="kg/m3", min=500.0),
        number("plasterDensityKgM3", "Finish density", 2000.0, unit="kg/m3", min=500.0),
    ],
    requires_project=False,
)
def new_wall_type(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a wall type layer build-up and compute total thickness and surface weight."""
    tc = values["thicknessMm"]
    tp = values["plasterEachSideMm"]
    tot_t = tc + 2.0 * tp
    w_core = (tc / 1000.0) * values["coreDensityKgM3"] * 9.81 / 1000.0
    w_fin = (2.0 * tp / 1000.0) * values["plasterDensityKgM3"] * 9.81 / 1000.0
    rows = [
        {"layer": "Core wall", "thicknessMm": tc, "weightKpa": w_core},
        {"layer": "Exterior/interior finishes (x2)", "thicknessMm": 2.0 * tp, "weightKpa": w_fin},
        {"layer": "Total assembly", "thicknessMm": tot_t, "weightKpa": w_core + w_fin},
    ]
    return result(
        summary={
            "wallId": values["wallId"].strip() or "W250",
            "totalThicknessMm": tot_t,
            "selfWeightKpa": w_core + w_fin,
        },
        tables=[
            table(
                "Wall build-up layers",
                [
                    ("layer", "Layer"),
                    ("thicknessMm", "Thickness", "mm"),
                    ("weightKpa", "Dead load", "kPa"),
                ],
                rows,
            )
        ],
        notes=["Surface weight calculated as thickness [m] * density * 9.81 / 1000."],
    )


@feature(
    "objWalls.shearWallType",
    "Shear Wall Type",
    part="objects",
    fields=[
        number("lengthMm", "Wall length lw", 3600.0, unit="mm", min=400.0),
        number("thicknessMm", "Wall thickness tw", 250.0, unit="mm", min=120.0),
        number("heightMm", "Total wall height hw", 12000.0, unit="mm", min=1000.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
        number("rhoVert", "Vertical web steel ratio", 0.0025, min=0.001, max=0.04),
        number("rhoHoriz", "Horizontal web steel ratio", 0.0025, min=0.001, max=0.04),
    ],
    requires_project=False,
)
def shear_wall_type(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a structural shear wall and compute nominal in-plane shear capacity via the engine."""
    lw, tw, hw = values["lengthMm"], values["thicknessMm"], values["heightMm"]
    fc, fy = values["fcMpa"], values["fyMpa"]
    with in_force(ctx.root):
        acv = lw * tw
        ac = wall_design.alpha_c(hw / lw)
        wgeom = wall_design.WallGeometry(
            length=lw,
            thickness=tw,
            height=hw,
            clear_height=hw,
            braced=True,
            restrained=True,
            basement=False,
            continuous=True,
        )
        bar_a10 = math.pi * 10.0**2 / 4.0
        s_h = max(50.0, 2.0 * bar_a10 / (tw * values["rhoHoriz"]))
        s_v = max(50.0, 2.0 * bar_a10 / (tw * values["rhoVert"]))
        wbars = wall_design.WallBars(
            cover=25.0,
            vertical_dia=10.0,
            vertical_spacing=s_v,
            horizontal_dia=10.0,
            horizontal_spacing=s_h,
            layers=2,
        )
        forces = wall_design.PierForces(combination=None, P=0.0, V2=0.0, M3=0.0, earthquake=False)
        res_vn = wall_design.wall_vn(wgeom, wbars, forces, fc, fy)
        vc = float(res_vn["vc"])
        vn = float(res_vn["vn"])
        phi = wall_design.wall_phi("shear")
        two_curt = wall_design.two_curtains_by_aspect(wgeom)
    rows = [
        {"metric": "Web gross area Acv", "value": acv, "unit": "mm2"},
        {"metric": "Aspect ratio hw / lw", "value": hw / lw, "unit": "-"},
        {"metric": "Shear coefficient alpha_c", "value": ac, "unit": "-"},
        {"metric": "Concrete shear contribution Vc", "value": vc / 1e3, "unit": "kN"},
        {"metric": "Nominal shear strength Vn", "value": vn / 1e3, "unit": "kN"},
        {"metric": "Design shear strength phi*Vn", "value": phi * vn / 1e3, "unit": "kN"},
    ]
    return result(
        summary={
            "alphaC": ac,
            "vcKn": vc / 1e3,
            "phiVnKn": phi * vn / 1e3,
            "twoCurtainsSuggested": bool(two_curt),
        },
        tables=[
            table(
                "Shear wall section strength",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Uses engine shear wall capacity equations and factors from the active code pack."],
    )


@feature(
    "objWalls.coreWall",
    "Core Wall",
    part="objects",
    fields=[
        number("flangeWidthMm", "Core outer width B", 4000.0, unit="mm", min=1000.0),
        number("webDepthMm", "Core outer depth D", 3000.0, unit="mm", min=1000.0),
        number("wallThickMm", "Wall thickness t", 250.0, unit="mm", min=150.0),
        number("openingWidthMm", "Door/corridor opening width", 1200.0, unit="mm", min=0.0),
    ],
    requires_project=False,
)
def core_wall(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Analyse a C-shaped lift/stair core wall group for gross area, centroid, and moments of inertia."""
    b, d, t, w_op = (
        values["flangeWidthMm"],
        values["webDepthMm"],
        values["wallThickMm"],
        values["openingWidthMm"],
    )
    if w_op >= b - 2 * t:
        raise FeatureInputError("Opening width must leave valid return flanges.")
    # Back wall (width b, thick t) + two side walls (depth d - t, thick t) + two front return nibs
    nib = (b - 2.0 * t - w_op) / 2.0
    parts = [
        (b * t, b / 2.0, t / 2.0, b * t**3 / 12.0, t * b**3 / 12.0),  # back flange
        (
            (d - t) * t,
            t / 2.0,
            t + (d - t) / 2.0,
            t * (d - t) ** 3 / 12.0,
            (d - t) * t**3 / 12.0,
        ),  # left web
        (
            (d - t) * t,
            b - t / 2.0,
            t + (d - t) / 2.0,
            t * (d - t) ** 3 / 12.0,
            (d - t) * t**3 / 12.0,
        ),  # right web
    ]
    if nib > 0:
        parts.append((nib * t, t + nib / 2.0, d - t / 2.0, nib * t**3 / 12.0, t * nib**3 / 12.0))
        parts.append(
            (nib * t, b - t - nib / 2.0, d - t / 2.0, nib * t**3 / 12.0, t * nib**3 / 12.0)
        )
    a_tot = sum(p[0] for p in parts)
    cx = sum(p[0] * p[1] for p in parts) / a_tot
    cy = sum(p[0] * p[2] for p in parts) / a_tot
    ixx = sum(p[3] + p[0] * (p[2] - cy) ** 2 for p in parts)
    iyy = sum(p[4] + p[0] * (p[1] - cx) ** 2 for p in parts)
    rows = [
        {"metric": "Net core area", "value": a_tot, "unit": "mm2"},
        {"metric": "Centroid Y from back face", "value": cy, "unit": "mm"},
        {"metric": "Major inertia Ixx", "value": ixx, "unit": "mm4"},
        {"metric": "Minor inertia Iyy", "value": iyy, "unit": "mm4"},
        {"metric": "Front return nib length", "value": nib, "unit": "mm"},
    ]
    return result(
        summary={
            "areaMm2": a_tot,
            "centroidYMm": cy,
            "ixxMm4": ixx,
            "iyyMm4": iyy,
            "nibLengthMm": nib,
        },
        tables=[
            table(
                "Core wall section properties",
                [("metric", "Property"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Parallel-axis integration over back wall, side webs, and front return piers."],
    )


@feature(
    "objWalls.retainingSection",
    "Retaining Section",
    part="objects",
    fields=[
        number("wallHeightMm", "Stem height H", 4000.0, unit="mm", min=1000.0),
        number("stemTopMm", "Stem thickness at top", 250.0, unit="mm", min=150.0),
        number("stemBaseMm", "Stem thickness at base", 400.0, unit="mm", min=150.0),
        number("baseWidthMm", "Footing base width B", 2600.0, unit="mm", min=800.0),
        number("baseThickMm", "Footing thickness", 400.0, unit="mm", min=200.0),
        number("toeMm", "Toe projection", 700.0, unit="mm", min=0.0),
    ],
    requires_project=False,
)
def retaining_section(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a cantilever retaining wall stem and base section and compute concrete volume and centroid."""
    h, t_top, t_bot = values["wallHeightMm"], values["stemTopMm"], values["stemBaseMm"]
    b, tb, toe = values["baseWidthMm"], values["baseThickMm"], values["toeMm"]
    if toe + t_bot > b:
        raise FeatureInputError("Toe + stem base thickness cannot exceed base width.")
    a_base = b * tb
    a_stem = 0.5 * (t_top + t_bot) * h
    tot_a = a_base + a_stem
    vol_per_m = tot_a * 1e-6
    heel = b - toe - t_bot
    rows = [
        {"component": "Base slab", "areaMm2": a_base, "volM3PerM": a_base * 1e-6},
        {"component": "Tapered stem", "areaMm2": a_stem, "volM3PerM": a_stem * 1e-6},
        {"component": "Total retaining section", "areaMm2": tot_a, "volM3PerM": vol_per_m},
    ]
    return result(
        summary={
            "totalAreaMm2": tot_a,
            "concreteM3PerM": vol_per_m,
            "heelLengthMm": heel,
            "selfWeightKnPerM": vol_per_m * 24.0,
        },
        tables=[
            table(
                "Retaining wall section geometry",
                [
                    ("component", "Part"),
                    ("areaMm2", "Area", "mm2"),
                    ("volM3PerM", "Volume/m", "m3/m"),
                ],
                rows,
            )
        ],
        notes=["Self-weight computed at 24 kN/m3 reinforced concrete unit weight."],
    )


@feature(
    "objWalls.wallOpenings",
    "Wall Openings",
    part="objects",
    fields=[
        number("wallLengthMm", "Wall length", 5000.0, unit="mm", min=500.0),
        number("wallHeightMm", "Storey height", 3200.0, unit="mm", min=1000.0),
        number("wallThickMm", "Wall thickness", 200.0, unit="mm", min=100.0),
        number("openWidthMm", "Opening width", 1200.0, unit="mm", min=200.0),
        number("openHeightMm", "Opening height", 2100.0, unit="mm", min=200.0),
        number("openLeftMm", "Distance from left edge", 1800.0, unit="mm", min=0.0),
    ],
    requires_project=False,
)
def wall_openings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check wall pier widths around an opening and calculate net wall area and trimmed concrete volume."""
    lw, hw, tw = values["wallLengthMm"], values["wallHeightMm"], values["wallThickMm"]
    ow, oh, x0 = values["openWidthMm"], values["openHeightMm"], values["openLeftMm"]
    if x0 + ow > lw or oh >= hw:
        raise FeatureInputError("Opening extends outside the wall panel bounds.")
    left_pier = x0
    right_pier = lw - x0 - ow
    spandrel_h = hw - oh
    gross_area = lw * hw * 1e-6
    open_area = ow * oh * 1e-6
    net_area = gross_area - open_area
    return result(
        summary={
            "leftPierMm": left_pier,
            "rightPierMm": right_pier,
            "spandrelDepthMm": spandrel_h,
            "openingRatio": open_area / gross_area,
            "netConcreteM3": net_area * tw / 1000.0,
        },
        tables=[
            table(
                "Wall panel & pier geometry",
                [("part", "Segment"), ("widthMm", "Width", "mm"), ("heightMm", "Height", "mm")],
                [
                    {"part": "Left pier", "widthMm": left_pier, "heightMm": hw},
                    {"part": "Right pier", "widthMm": right_pier, "heightMm": hw},
                    {"part": "Spandrel / lintel", "widthMm": ow, "heightMm": spandrel_h},
                ],
            )
        ],
        notes=["Net volume deducts the full opening area over wall thickness."],
    )


@feature(
    "objWalls.couplingBeams",
    "Coupling Beams",
    part="objects",
    fields=[
        number("spanMm", "Clear span ln", 1500.0, unit="mm", min=300.0),
        number("depthMm", "Beam depth h", 700.0, unit="mm", min=200.0),
        number("widthMm", "Beam width bw", 250.0, unit="mm", min=150.0),
        number("vuKn", "Factored shear Vu", 450.0, unit="kN", min=0.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        number("fyMpa", "Diagonal rebar fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def coupling_beams(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Classify coupling beam aspect ratio ln/h and size diagonal bar groups for shear resistance."""
    ln, h, bw = values["spanMm"], values["depthMm"], values["widthMm"]
    aspect = ln / h
    alpha = math.atan2(h - 150.0, ln)
    vu_n = values["vuKn"] * 1e3
    phi = 0.85
    # Vn = 2 * Avd * fy * sin(alpha)
    avd_req = vu_n / (phi * 2.0 * values["fyMpa"] * max(0.1, math.sin(alpha)))
    v_stress = vu_n / (bw * (h - 50.0))
    need_diag = aspect < 2.0 and v_stress > 0.33 * math.sqrt(values["fcMpa"])
    rows = [
        {"metric": "Clear span-to-depth ln/h", "value": aspect, "unit": "-"},
        {"metric": "Diagonal inclination angle", "value": math.degrees(alpha), "unit": "deg"},
        {"metric": "Unit shear stress vu", "value": v_stress, "unit": "MPa"},
        {"metric": "Required diagonal steel Avd per group", "value": avd_req, "unit": "mm2"},
    ]
    return result(
        summary={
            "aspectRatio": aspect,
            "diagonalAngleDeg": math.degrees(alpha),
            "requiredAvdMm2": avd_req,
            "diagonalBarsRecommended": need_diag,
        },
        tables=[
            table(
                "Coupling beam sizing",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Deep coupling beams (ln/h < 2) with high shear require intersecting diagonal reinforcement groups."
        ],
    )


@feature(
    "objWalls.boundaryZones",
    "Boundary Zones",
    part="objects",
    fields=[
        number("wallLengthMm", "Wall length lw", 4000.0, unit="mm", min=500.0),
        number("thicknessMm", "Wall thickness tw", 250.0, unit="mm", min=150.0),
        number("naDepthMm", "Neutral axis depth c", 950.0, unit="mm", min=50.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        number("fyMpa", "Transverse hoop fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def boundary_zones(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute special boundary element length and confinement reinforcement demand Ash/s."""
    lw, tw, c = values["wallLengthMm"], values["thicknessMm"], values["naDepthMm"]
    with in_force(ctx.root):
        lb = wall_design.boundary_length(c, lw)
        ash_s = wall_design.boundary_ash(tw, values["fcMpa"], values["fyMpa"])
    rows = [
        {"metric": "Boundary element length lbe = max(c - 0.1*lw, c/2)", "value": lb, "unit": "mm"},
        {"metric": "Confinement steel demand Ash/s (along wall)", "value": ash_s, "unit": "mm2/mm"},
    ]
    return result(
        summary={"boundaryLengthMm": lb, "ashPerSMm": ash_s, "boundaryRatio": lb / lw},
        tables=[
            table(
                "Boundary element extents & hoops",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=[
            "Computed using the engine's shear wall boundary-element module and active code pack."
        ],
    )


@feature(
    "objWalls.wallRebar",
    "Wall Rebar",
    part="objects",
    fields=[
        number("thicknessMm", "Wall thickness tw", 250.0, unit="mm", min=100.0),
        select(
            "curtains",
            "Curtains (layers)",
            [("2", "Two curtains (faces)"), ("1", "Single central layer")],
            "2",
        ),
        number("vertDiaMm", "Vertical bar diameter", 12.0, unit="mm", min=8.0),
        number("vertSpacingMm", "Vertical bar spacing", 200.0, unit="mm", min=75.0),
        number("horizDiaMm", "Horizontal bar diameter", 10.0, unit="mm", min=8.0),
        number("horizSpacingMm", "Horizontal bar spacing", 200.0, unit="mm", min=75.0),
    ],
    requires_project=False,
)
def wall_rebar(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute vertical and horizontal wall reinforcement ratios and steel weight per square metre."""
    tw = values["thicknessMm"]
    layers = int(values["curtains"])
    av = layers * (math.pi * values["vertDiaMm"] ** 2 / 4.0) * (1000.0 / values["vertSpacingMm"])
    ah = layers * (math.pi * values["horizDiaMm"] ** 2 / 4.0) * (1000.0 / values["horizSpacingMm"])
    rho_v = av / (1000.0 * tw)
    rho_h = ah / (1000.0 * tw)
    with in_force(ctx.root):
        min_v, min_h = wall_design.minimum_ratios(values["vertDiaMm"], values["horizDiaMm"], 420.0)
    kg_m2 = (av + ah) * 7850.0 * 1e-6
    rows = [
        {
            "direction": "Vertical",
            "areaPerMMm2": av,
            "ratio": rho_v,
            "minRatio": min_v,
            "ok": rho_v >= min_v,
        },
        {
            "direction": "Horizontal",
            "areaPerMMm2": ah,
            "ratio": rho_h,
            "minRatio": min_h,
            "ok": rho_h >= min_h,
        },
    ]
    return result(
        summary={
            "rhoVertical": rho_v,
            "rhoHorizontal": rho_h,
            "steelKgPerM2": kg_m2,
            "meetsMinimum": rho_v >= min_v and rho_h >= min_h,
        },
        tables=[
            table(
                "Wall reinforcement schedule",
                [
                    ("direction", "Direction"),
                    ("areaPerMMm2", "As / m", "mm2/m"),
                    ("ratio", "Ratio"),
                    ("minRatio", "Min ratio"),
                    ("ok", "Pass"),
                ],
                rows,
            )
        ],
        notes=["Minimum web steel ratios read from the active code pack."],
    )


@feature(
    "objWalls.confinement",
    "Confinement",
    part="objects",
    fields=[
        number("boundaryWidthMm", "Boundary zone thickness bw", 250.0, unit="mm", min=150.0),
        number("boundaryLengthMm", "Boundary zone length lbe", 600.0, unit="mm", min=200.0),
        number("coverMm", "Clear cover", 25.0, unit="mm", min=15.0),
        number("hoopDiaMm", "Hoop diameter", 10.0, unit="mm", min=8.0),
        number("spacingMm", "Vertical hoop spacing s", 100.0, unit="mm", min=50.0),
        number("legsAcross", "Legs across thickness", 4.0, min=2.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        number("fyMpa", "Hoop yield fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def wall_confinement(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check boundary element confinement hoop area Ash against code-pack requirements."""
    bw, cc = values["boundaryWidthMm"], values["coverMm"]
    s, legs = values["spacingMm"], round(values["legsAcross"])
    bc = bw - 2.0 * cc
    if bc <= 0:
        raise FeatureInputError("Cover exceeds boundary wall thickness.")
    ash_prov = legs * math.pi * values["hoopDiaMm"] ** 2 / 4.0
    with in_force(ctx.root):
        ash_per_s = wall_design.boundary_ash(bw, values["fcMpa"], values["fyMpa"])
    ash_req = ash_per_s * s
    s_max = min(bw / 3.0, 150.0)
    rows = [
        {
            "check": "Hoop area Ash",
            "provided": ash_prov,
            "required": ash_req,
            "unit": "mm2",
            "ok": ash_prov >= ash_req,
        },
        {
            "check": "Vertical spacing s",
            "provided": s,
            "required": s_max,
            "unit": "mm",
            "ok": s <= s_max,
        },
    ]
    return result(
        summary={
            "ashProvidedMm2": ash_prov,
            "ashRequiredMm2": ash_req,
            "maxSpacingMm": s_max,
            "confinementOk": ash_prov >= ash_req and s <= s_max,
        },
        tables=[
            table(
                "Boundary confinement check",
                [
                    ("check", "Check"),
                    ("provided", "Provided"),
                    ("required", "Limit"),
                    ("unit", "Unit"),
                    ("ok", "Pass"),
                ],
                rows,
            )
        ],
        notes=[
            "Compares provided hoop legs across boundary core against required Ash = s * ash_per_s."
        ],
    )


@feature(
    "objWalls.lapZones",
    "Lap Zones",
    part="objects",
    fields=[
        number("storeyHeightMm", "Storey clear height hw", 3200.0, unit="mm", min=1000.0),
        number("barDiaMm", "Vertical bar diameter", 16.0, unit="mm", min=10.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
        checkbox("staggerSplices", "Stagger splices 50% at two levels", True),
    ],
    requires_project=False,
)
def lap_zones(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Locate and verify vertical wall bar lap zones outside plastic hinge regions."""
    from saengine.drawings.detailing import lap_tension

    with in_force(ctx.root):
        ld_lap = lap_tension(values["barDiaMm"], values["fyMpa"], values["fcMpa"]).value
    hw = values["storeyHeightMm"]
    # Plastic hinge exclusion at base: max(lw, hw/6) ~ hw/4 conservative zone
    hinge_zone = max(600.0, hw * 0.25)
    avail = hw - hinge_zone
    fit_ok = avail >= (2.0 * ld_lap if values["staggerSplices"] else ld_lap)
    rows = [
        {"zone": "Base plastic hinge exclusion", "startMm": 0.0, "endMm": hinge_zone},
        {"zone": "Permitted splice zone", "startMm": hinge_zone, "endMm": hw},
        {"zone": "Required tension lap length", "startMm": 0.0, "endMm": ld_lap},
    ]
    return result(
        summary={
            "tensionLapMm": ld_lap,
            "hingeExclusionMm": hinge_zone,
            "availableZoneMm": avail,
            "spliceZoneFits": fit_ok,
        },
        tables=[
            table(
                "Wall vertical bar lap zoning",
                [("zone", "Zone"), ("startMm", "Start", "mm"), ("endMm", "End/Len", "mm")],
                rows,
            )
        ],
        notes=["Staggered splices keep at most 50% of vertical bars lapped at one section."],
    )


@feature(
    "objWalls.flatSlabType",
    "Flat Slab Type",
    part="objects",
    fields=[
        number("spanMm", "Longer panel span L1", 7200.0, unit="mm", min=2000.0),
        number("slabThickMm", "Slab thickness h", 225.0, unit="mm", min=100.0),
        number("dropThickMm", "Drop panel extra projection below soffit", 75.0, unit="mm", min=0.0),
        number("colWidthMm", "Supporting column dimension", 500.0, unit="mm", min=200.0),
        number("factoredReactionKn", "Factored column load Vu", 650.0, unit="kN", min=10.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
    ],
    requires_project=False,
)
def flat_slab_type(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a flat slab with optional drop panel and check punching shear perimeter and span/depth."""
    h, drop = values["slabThickMm"], values["dropThickMm"]
    d_eff = h + drop - 30.0
    c = values["colWidthMm"]
    b0 = 4.0 * (c + d_eff)
    vc_n = 0.33 * math.sqrt(values["fcMpa"]) * b0 * d_eff
    phi_vc_kn = 0.75 * vc_n / 1e3
    span_depth = values["spanMm"] / h
    rows = [
        {"metric": "Effective depth at column d", "value": d_eff, "unit": "mm"},
        {"metric": "Critical perimeter b0 (d/2 from face)", "value": b0, "unit": "mm"},
        {"metric": "Punching capacity phi*Vc", "value": phi_vc_kn, "unit": "kN"},
        {"metric": "Punching demand Vu", "value": values["factoredReactionKn"], "unit": "kN"},
        {"metric": "Span-to-thickness ratio L/h", "value": span_depth, "unit": "-"},
    ]
    return result(
        summary={
            "criticalPerimeterMm": b0,
            "punchingCapacityKn": phi_vc_kn,
            "punchingUtilisation": values["factoredReactionKn"] / phi_vc_kn,
            "spanToDepth": span_depth,
        },
        tables=[
            table(
                "Flat slab & drop panel check",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Two-way punching perimeter taken at d/2 from column faces."],
    )


@feature(
    "objWalls.waffleSlab",
    "Waffle Slab",
    part="objects",
    fields=[
        number("overallDepthMm", "Overall waffle depth h", 450.0, unit="mm", min=200.0),
        number("toppingThickMm", "Top flange slab thickness tf", 100.0, unit="mm", min=50.0),
        number("ribWidthMm", "Average rib width bw", 150.0, unit="mm", min=75.0),
        number("ribSpacingMm", "Centre-to-centre rib pitch", 900.0, unit="mm", min=300.0),
    ],
    requires_project=False,
)
def waffle_slab(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute equivalent thickness, concrete volume per m2, and dead load of a two-way waffle slab."""
    h, tf, bw, s = (
        values["overallDepthMm"],
        values["toppingThickMm"],
        values["ribWidthMm"],
        values["ribSpacingMm"],
    )
    if tf >= h or bw >= s:
        raise FeatureInputError(
            "Topping must be thinner than overall depth and rib width smaller than pitch."
        )
    hr = h - tf
    # In one s x s module: topping volume + 2 orthogonal ribs minus intersection
    vol_mod = (s * s * tf + 2.0 * bw * s * hr - bw * bw * hr) * 1e-9
    area_mod = (s * s) * 1e-6
    eq_thick_mm = (vol_mod / area_mod) * 1000.0
    self_weight_kpa = (eq_thick_mm / 1000.0) * 24.0
    rows = [
        {"metric": "Rib clear depth", "value": hr, "unit": "mm"},
        {"metric": "Equivalent solid thickness", "value": eq_thick_mm, "unit": "mm"},
        {"metric": "Concrete volume per m2", "value": vol_mod / area_mod, "unit": "m3/m2"},
        {"metric": "Self-weight dead load", "value": self_weight_kpa, "unit": "kPa"},
    ]
    return result(
        summary={
            "equivalentThicknessMm": eq_thick_mm,
            "concreteM3PerM2": vol_mod / area_mod,
            "selfWeightKpa": self_weight_kpa,
        },
        tables=[
            table(
                "Waffle slab module quantities",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Exact rib intersection overlap deducted from concrete volume per module."],
    )


@feature(
    "objWalls.ribbedSlab",
    "Ribbed Slab",
    part="objects",
    fields=[
        number("overallDepthMm", "Overall depth h", 350.0, unit="mm", min=150.0),
        number("toppingThickMm", "Topping thickness tf", 75.0, unit="mm", min=40.0),
        number("ribWidthMm", "Rib web width bw", 125.0, unit="mm", min=75.0),
        number("ribSpacingMm", "Rib centre-to-centre spacing", 600.0, unit="mm", min=250.0),
    ],
    requires_project=False,
)
def ribbed_slab(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a one-way ribbed joist slab and compute T-rib inertia and equivalent dead weight."""
    h, tf, bw, s = (
        values["overallDepthMm"],
        values["toppingThickMm"],
        values["ribWidthMm"],
        values["ribSpacingMm"],
    )
    if tf >= h or bw >= s:
        raise FeatureInputError("Topping must be less than depth and rib width less than spacing.")
    hr = h - tf
    a_rib = s * tf + bw * hr
    y_top = (s * tf * (tf / 2.0) + bw * hr * (tf + hr / 2.0)) / a_rib
    ixx_rib = (
        s * tf**3 / 12.0
        + s * tf * (y_top - tf / 2.0) ** 2
        + bw * hr**3 / 12.0
        + bw * hr * (tf + hr / 2.0 - y_top) ** 2
    )
    eq_t = a_rib / s
    return result(
        summary={
            "ribAreaMm2": a_rib,
            "ribInertiaMm4": ixx_rib,
            "equivalentThicknessMm": eq_t,
            "selfWeightKpa": (eq_t / 1000.0) * 24.0,
        },
        tables=[
            table(
                "One-way ribbed slab properties",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"metric": "T-rib area per pitch", "value": a_rib, "unit": "mm2"},
                    {"metric": "T-rib uncracked Ixx", "value": ixx_rib, "unit": "mm4"},
                    {"metric": "Equivalent solid thickness", "value": eq_t, "unit": "mm"},
                    {
                        "metric": "Dead weight per m2",
                        "value": (eq_t / 1000.0) * 24.0,
                        "unit": "kPa",
                    },
                ],
            )
        ],
        notes=["Neutral axis measured from top of concrete topping."],
    )


@feature(
    "objWalls.postTensionedSlab",
    "Post-Tensioned Slab",
    part="objects",
    fields=[
        number("spanMm", "Span length L", 9000.0, unit="mm", min=3000.0),
        number("slabThickMm", "Slab thickness h", 220.0, unit="mm", min=125.0),
        number("coverMm", "Cover to duct/tendon CGS", 35.0, unit="mm", min=20.0),
        number("pEffKnPerM", "Effective prestress force Pe/m", 240.0, unit="kN/m", min=50.0),
    ],
    requires_project=False,
)
def post_tensioned_slab(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute parabolic tendon drape, upward equivalent load balancing, and average precompression."""
    L, h, cc = values["spanMm"], values["slabThickMm"], values["coverMm"]
    if 2.0 * cc >= h:
        raise FeatureInputError("Cover exceeds half slab thickness.")
    drape_mm = (h / 2.0 - cc) + (h / 2.0 - cc)  # high point at support to low point at midspan
    # Parabolic upward load w_bal = 8 * Pe * drape / L^2
    pe_n_per_mm = values["pEffKnPerM"]  # kN/m == N/mm
    w_bal_kpa = 8.0 * values["pEffKnPerM"] * (drape_mm / 1000.0) / ((L / 1000.0) ** 2)
    p_avg_mpa = (pe_n_per_mm * 1000.0) / (1000.0 * h)
    self_wt = (h / 1000.0) * 24.0
    return result(
        summary={
            "tendonDrapeMm": drape_mm,
            "balancedLoadKpa": w_bal_kpa,
            "selfWeightBalancePercent": (w_bal_kpa / self_wt) * 100.0,
            "avgPrecompressionMpa": p_avg_mpa,
        },
        tables=[
            table(
                "Post-tensioned slab load balancing",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"metric": "Total parabolic drape", "value": drape_mm, "unit": "mm"},
                    {"metric": "Balanced upward load w_bal", "value": w_bal_kpa, "unit": "kPa"},
                    {"metric": "Slab self-weight", "value": self_wt, "unit": "kPa"},
                    {"metric": "Average precompression P/A", "value": p_avg_mpa, "unit": "MPa"},
                ],
            )
        ],
        notes=["Parabolic tendon load balance w_bal = 8 * Pe * a / L^2."],
    )


@feature(
    "objWalls.slabEdgeTrim",
    "Slab Edge Trim",
    part="objects",
    fields=[
        number("slabThickMm", "Slab thickness", 150.0, unit="mm", min=75.0),
        number("edgeLengthM", "Edge perimeter length", 24.0, unit="m", min=0.5),
        number(
            "upstandHeightMm",
            "Edge upstand/drop height above/below slab",
            150.0,
            unit="mm",
            min=0.0,
        ),
        number("upstandWidthMm", "Edge trim width", 150.0, unit="mm", min=50.0),
        number("chamferMm", "Edge chamfer size", 25.0, unit="mm", min=0.0),
    ],
    requires_project=False,
)
def slab_edge_trim(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate concrete and edge formwork quantities for slab perimeter upstands and chamfers."""
    l_m = values["edgeLengthM"]
    a_up = (
        values["upstandHeightMm"] * values["upstandWidthMm"] - 0.5 * values["chamferMm"] ** 2
    ) * 1e-6
    vol_m3 = max(0.0, a_up * l_m)
    form_m2 = ((values["slabThickMm"] + 2.0 * values["upstandHeightMm"]) / 1000.0) * l_m
    return result(
        summary={"edgeLengthM": l_m, "extraConcreteM3": vol_m3, "edgeFormworkM2": form_m2},
        tables=[
            table(
                "Slab edge trim quantities",
                [("item", "Item"), ("value", "Quantity"), ("unit", "Unit")],
                [
                    {"item": "Upstand / edge concrete", "value": vol_m3, "unit": "m3"},
                    {"item": "Edge & upstand formwork", "value": form_m2, "unit": "m2"},
                ],
            )
        ],
        notes=["Accounts for corner chamfer deduction in edge upstand cross-section."],
    )


@feature(
    "objWalls.linkBeamRebar",
    "Link Beam Rebar",
    part="objects",
    fields=[
        number("spanMm", "Link beam clear span", 1400.0, unit="mm", min=300.0),
        number("widthMm", "Link beam width bw", 250.0, unit="mm", min=150.0),
        number("depthMm", "Link beam depth h", 650.0, unit="mm", min=250.0),
        number("diagBarsPerGroup", "Diagonal bars per group", 4.0, min=2.0),
        number("diagDiaMm", "Diagonal bar diameter", 20.0, unit="mm", min=12.0),
        number("fyMpa", "Bar yield fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def link_beam_rebar(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detail intersecting diagonal and horizontal reinforcement in wall link/coupling beams."""
    ln, h = values["spanMm"], values["depthMm"]
    n_diag = round(values["diagBarsPerGroup"])
    db = values["diagDiaMm"]
    avd = n_diag * math.pi * db**2 / 4.0
    alpha = math.atan2(h - 140.0, ln)
    vn_kn = 2.0 * avd * values["fyMpa"] * math.sin(alpha) / 1e3
    diag_len_m = math.hypot(ln + 1200.0, h - 140.0) / 1000.0
    return result(
        summary={
            "avdPerGroupMm2": avd,
            "inclinationDeg": math.degrees(alpha),
            "nominalShearKn": vn_kn,
            "designShearKn": 0.85 * vn_kn,
            "diagonalBarLengthM": diag_len_m,
        },
        tables=[
            table(
                "Link beam diagonal reinforcement",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"metric": "Diagonal group area Avd", "value": avd, "unit": "mm2"},
                    {"metric": "Angle alpha", "value": math.degrees(alpha), "unit": "deg"},
                    {"metric": "Nominal shear Vn", "value": vn_kn, "unit": "kN"},
                    {"metric": "Design shear 0.85*Vn", "value": 0.85 * vn_kn, "unit": "kN"},
                    {
                        "metric": "Single diagonal bar cut length (incl. 600mm embed each end)",
                        "value": diag_len_m,
                        "unit": "m",
                    },
                ],
            )
        ],
        notes=["Two intersecting diagonal groups provide Vn = 2 * Avd * fy * sin(alpha)."],
    )


@feature(
    "objWalls.diagonalReinforcement",
    "Diagonal Reinforcement",
    part="objects",
    fields=[
        number("coreWidthMm", "Diagonal core width bc", 160.0, unit="mm", min=80.0),
        number("coreDepthMm", "Diagonal core depth dc", 160.0, unit="mm", min=80.0),
        number("hoopDiaMm", "Group hoop diameter", 10.0, unit="mm", min=8.0),
        number("hoopSpacingMm", "Group hoop spacing s", 100.0, unit="mm", min=50.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        number("fyMpa", "Hoop fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def diagonal_reinforcement(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure transverse confinement hoops around diagonal bar cages in deep coupling beams."""
    bc, dc, s = values["coreWidthMm"], values["coreDepthMm"], values["hoopSpacingMm"]
    a_hoop = 2.0 * math.pi * values["hoopDiaMm"] ** 2 / 4.0
    ash_req = 0.09 * s * max(bc, dc) * values["fcMpa"] / values["fyMpa"]
    return result(
        summary={
            "ashProvidedMm2": a_hoop,
            "ashRequiredMm2": ash_req,
            "confinementOk": a_hoop >= ash_req,
        },
        tables=[
            table(
                "Diagonal cage confinement",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Provided 2-leg hoop Ash", "value": a_hoop, "unit": "mm2"},
                    {"item": "Required Ash (0.09*s*bc*fc/fy)", "value": ash_req, "unit": "mm2"},
                    {"item": "Confinement utilisation", "value": ash_req / a_hoop, "unit": "-"},
                ],
            )
        ],
        notes=[
            "Checks transverse confinement of diagonal bar bundles against buckling under cyclic shear."
        ],
    )


@feature(
    "objWalls.shearKey",
    "Shear Key",
    part="objects",
    fields=[
        number("wallLengthMm", "Wall joint length", 3000.0, unit="mm", min=400.0),
        number("keyWidthMm", "Shear key width", 100.0, unit="mm", min=40.0),
        number("keyDepthMm", "Shear key depth", 40.0, unit="mm", min=15.0),
        number("keyCount", "Number of keys along joint", 4.0, min=1.0),
        number("dowelAreaMm2", "Vertical dowel steel area Avf", 1600.0, unit="mm2", min=100.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Dowel yield fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def shear_key(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute shear-friction and bearing key shear capacity across wall construction joints."""
    from saengine.design.rc_detailing import shear_friction

    a_keys = round(values["keyCount"]) * values["keyWidthMm"] * 250.0
    a_joint = values["wallLengthMm"] * 250.0
    with in_force(ctx.root):
        sf = shear_friction(
            values["dowelAreaMm2"], values["fyMpa"], values["fcMpa"], a_joint, surface="roughened"
        )
    vn_kn = sf.vn / 1e3 if sf else 0.75 * values["dowelAreaMm2"] * values["fyMpa"] / 1e3
    phi_vn_kn = (sf.phi * sf.vn / 1e3) if sf else 0.75 * vn_kn
    return result(
        summary={
            "keyCount": round(values["keyCount"]),
            "keyBearingAreaMm2": a_keys,
            "nominalShearKn": vn_kn,
            "designShearKn": phi_vn_kn,
        },
        tables=[
            table(
                "Construction joint shear key capacity",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"metric": "Joint gross area", "value": a_joint, "unit": "mm2"},
                    {"metric": "Nominal shear friction Vn", "value": vn_kn, "unit": "kN"},
                    {"metric": "Design shear phi*Vn", "value": phi_vn_kn, "unit": "kN"},
                ],
            )
        ],
        notes=[
            "Evaluated using the engine's shear-friction resistance with roughened joint coefficient."
        ],
    )


@feature(
    "objWalls.wallFootingTie",
    "Wall Footing Tie",
    part="objects",
    fields=[
        number("wallThickMm", "Wall thickness", 250.0, unit="mm", min=120.0),
        number("footingThickMm", "Footing depth", 500.0, unit="mm", min=250.0),
        number("starterDiaMm", "Starter bar diameter", 16.0, unit="mm", min=10.0),
        number("starterSpacingMm", "Starter bar spacing", 200.0, unit="mm", min=75.0),
        number("fcMpa", "Concrete f'c", 25.0, unit="MPa", min=15.0),
        number("fyMpa", "Starter fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def wall_footing_tie(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detail wall-to-footing starter dowels and check embedment depth into the footing."""
    from saengine.drawings.detailing import development_compression, hook_development, lap_tension

    db, fc, fy = values["starterDiaMm"], values["fcMpa"], values["fyMpa"]
    with in_force(ctx.root):
        ld_hook = hook_development(db, fy, fc).value
        ldc = development_compression(db, fy, fc).value
        lap = lap_tension(db, fy, fc).value
    avail_embed = values["footingThickMm"] - 75.0 - 24.0
    total_dowel = avail_embed + 250.0 + lap
    return result(
        summary={
            "availableEmbedMm": avail_embed,
            "requiredHookMm": ld_hook,
            "requiredCompMm": ldc,
            "starterTotalLengthMm": total_dowel,
            "embedmentOk": avail_embed >= max(ld_hook, ldc),
        },
        tables=[
            table(
                "Wall-footing starter bar detailing",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Available footing embedment", "value": avail_embed, "unit": "mm"},
                    {"item": "Required hooked tension ldh", "value": ld_hook, "unit": "mm"},
                    {"item": "Required compression ldc", "value": ldc, "unit": "mm"},
                    {"item": "Lap projection above footing", "value": lap, "unit": "mm"},
                    {
                        "item": "Cut length (incl. 250mm 90-deg foot)",
                        "value": total_dowel,
                        "unit": "mm",
                    },
                ],
            )
        ],
        notes=[
            "Deducts 75 mm bottom cover and two footing mesh bar layers from footing thickness."
        ],
    )


@feature(
    "objWalls.spliceLayout",
    "Splice Layout",
    part="objects",
    fields=[
        number("wallHeightMm", "Storey clear height", 3200.0, unit="mm", min=1200.0),
        number("lapLengthMm", "Tension lap length", 800.0, unit="mm", min=300.0),
        number("staggerOffsetMm", "Vertical stagger gap", 300.0, unit="mm", min=100.0),
    ],
    requires_project=False,
)
def splice_layout(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Arrange staggered 50% alternating lap splice elevations along wall height."""
    hw, lap, gap = values["wallHeightMm"], values["lapLengthMm"], values["staggerOffsetMm"]
    z1_start = max(500.0, hw * 0.25)
    z1_end = z1_start + lap
    z2_start = z1_end + gap
    z2_end = z2_start + lap
    fits = z2_end <= hw - 150.0
    rows = [
        {"group": "Odd bars (50%)", "startMm": z1_start, "endMm": z1_end, "lengthMm": lap},
        {"group": "Even bars (50%)", "startMm": z2_start, "endMm": z2_end, "lengthMm": lap},
    ]
    return result(
        summary={"fitsWithinStorey": fits, "group1TopMm": z1_end, "group2TopMm": z2_end},
        tables=[
            table(
                "Staggered wall splice elevations",
                [
                    ("group", "Bar group"),
                    ("startMm", "Start", "mm"),
                    ("endMm", "End", "mm"),
                    ("lengthMm", "Lap", "mm"),
                ],
                rows,
            )
        ],
        notes=["Alternating 50% splice stagger prevents lap congestion at a single floor level."],
    )


@feature(
    "objWalls.wallStiffness",
    "Wall Stiffness",
    part="objects",
    fields=[
        number("lengthMm", "Wall length lw", 4000.0, unit="mm", min=400.0),
        number("thicknessMm", "Wall thickness tw", 250.0, unit="mm", min=100.0),
        number("heightMm", "Storey height h", 3200.0, unit="mm", min=1000.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("crackedFactor", "Cracked flexural modifier (Ig factor)", 0.35, min=0.1, max=1.0),
    ],
    requires_project=False,
)
def wall_stiffness(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute uncracked and cracked lateral cantilever stiffness of a wall pier."""
    lw, tw, h = values["lengthMm"], values["thicknessMm"], values["heightMm"]
    with in_force(ctx.root):
        ec, _ = concrete_modulus(values["fcMpa"])
    ig = tw * lw**3 / 12.0
    icr = values["crackedFactor"] * ig
    ag = tw * lw
    av = ag / 1.2
    g = ec / (2.0 * (1.0 + 0.2))
    # Cantilever tip stiffness K = 1 / (h^3/(3*E*I) + h/(G*Av))
    k_gross = 1.0 / (h**3 / (3.0 * ec * ig) + h / (g * av))
    k_cr = 1.0 / (h**3 / (3.0 * ec * icr) + h / (g * av * 0.5))
    return result(
        summary={
            "ecMpa": ec,
            "igMm4": ig,
            "icrMm4": icr,
            "uncrackedStiffnessKnPerMm": k_gross / 1e3,
            "crackedStiffnessKnPerMm": k_cr / 1e3,
        },
        tables=[
            table(
                "Wall lateral stiffness",
                [
                    ("state", "Condition"),
                    ("inertiaMm4", "Inertia", "mm4"),
                    ("stiffnessKnMm", "Stiffness", "kN/mm"),
                ],
                [
                    {"state": "Uncracked", "inertiaMm4": ig, "stiffnessKnMm": k_gross / 1e3},
                    {"state": "Cracked", "inertiaMm4": icr, "stiffnessKnMm": k_cr / 1e3},
                ],
            )
        ],
        notes=["Includes both flexural and shear deformations of a cantilevered wall segment."],
    )


@feature(
    "objWalls.slabLoadPath",
    "Slab Load Path",
    part="objects",
    fields=[
        number("lxM", "Short panel span Lx", 4.5, unit="m", min=1.0),
        number("lyM", "Long panel span Ly", 6.0, unit="m", min=1.0),
        number("loadKpa", "Factored total slab load wu", 12.0, unit="kPa", min=0.5),
    ],
    requires_project=False,
)
def slab_load_path(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Trace two-way yield-line tributary load distribution to short and long supporting edges."""
    lx = min(values["lxM"], values["lyM"])
    ly = max(values["lxM"], values["lyM"])
    w = values["loadKpa"]
    beta = ly / lx
    # Total panel load W = w * lx * ly
    w_tot = w * lx * ly
    # Two triangular loads on short sides: 2 * (0.5 * lx * (lx/2) * w) = 0.5 * w * lx^2
    w_short_total = 0.5 * w * lx**2
    w_long_total = w_tot - w_short_total
    q_short_peak = 0.5 * w * lx
    q_long_peak = 0.5 * w * lx
    return result(
        summary={
            "aspectRatio": beta,
            "totalPanelLoadKn": w_tot,
            "shortEdgeSharePercent": (w_short_total / w_tot) * 100.0,
            "longEdgeSharePercent": (w_long_total / w_tot) * 100.0,
            "peakLineLoadKnPerM": q_long_peak,
        },
        tables=[
            table(
                "Tributary edge load distribution",
                [
                    ("edge", "Supporting edge"),
                    ("shape", "Load shape"),
                    ("peakKnPerM", "Peak intensity", "kN/m"),
                    ("totalPerEdgeKn", "Load per edge", "kN"),
                ],
                [
                    {
                        "edge": f"Short edges ({lx:g} m)",
                        "shape": "Triangular",
                        "peakKnPerM": q_short_peak,
                        "totalPerEdgeKn": w_short_total / 2.0,
                    },
                    {
                        "edge": f"Long edges ({ly:g} m)",
                        "shape": "Trapezoidal",
                        "peakKnPerM": q_long_peak,
                        "totalPerEdgeKn": w_long_total / 2.0,
                    },
                ],
            )
        ],
        notes=[
            "45-degree yield-line tributary areas partition total slab load onto perimeter beams/walls."
        ],
    )


@feature(
    "objWalls.openingEffect",
    "Opening Effect",
    part="objects",
    fields=[
        number("wallLengthMm", "Wall length lw", 4000.0, unit="mm", min=500.0),
        number("wallHeightMm", "Wall height hw", 3200.0, unit="mm", min=1000.0),
        number("openWidthMm", "Opening width", 1000.0, unit="mm", min=0.0),
        number("openHeightMm", "Opening height", 2100.0, unit="mm", min=0.0),
    ],
    requires_project=False,
)
def opening_effect(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Quantify the reduction in wall shear stiffness and strength caused by rectangular openings."""
    lw, hw = values["wallLengthMm"], values["wallHeightMm"]
    ow, oh = values["openWidthMm"], values["openHeightMm"]
    if ow > lw or oh > hw:
        raise FeatureInputError("Opening cannot exceed wall panel dimensions.")
    area_ratio = (ow * oh) / (lw * hw)
    # Empirical stiffness reduction factor r = 1 - 1.25 * sqrt(Ao / Aw) bounded [0.1, 1.0]
    stiff_factor = max(0.1, 1.0 - 1.25 * math.sqrt(area_ratio)) if area_ratio > 0 else 1.0
    shear_len_factor = (lw - ow) / lw
    return result(
        summary={
            "openingAreaRatio": area_ratio,
            "effectiveShearLengthRatio": shear_len_factor,
            "stiffnessRetentionFactor": stiff_factor,
            "strengthReductionPercent": (1.0 - shear_len_factor) * 100.0,
        },
        tables=[
            table(
                "Wall opening impact summary",
                [("metric", "Metric"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "metric": "Opening-to-wall area ratio",
                        "value": area_ratio * 100.0,
                        "unit": "%",
                    },
                    {
                        "metric": "Net horizontal shear length ratio",
                        "value": shear_len_factor * 100.0,
                        "unit": "%",
                    },
                    {
                        "metric": "Retained lateral stiffness factor",
                        "value": stiff_factor,
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=[
            "Net shear resistance scales with remaining pier length; stiffness factor accounts for frame-pier bending."
        ],
    )


@feature(
    "objWalls.crackPattern",
    "Crack Pattern",
    part="objects",
    fields=[
        number("lengthMm", "Wall length lw", 4000.0, unit="mm", min=500.0),
        number("thicknessMm", "Wall thickness tw", 250.0, unit="mm", min=100.0),
        number("heightMm", "Wall height hw", 3200.0, unit="mm", min=1000.0),
        number("axialKn", "Service axial load N", 800.0, unit="kN", min=0.0),
        number("momentKnm", "Service base moment M", 450.0, unit="kN-m", min=0.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
    ],
    requires_project=False,
)
def crack_pattern(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Predict flexural cracking moment Mcr, extreme tensile stress, and expected crack zone height."""
    lw, tw, hw = values["lengthMm"], values["thicknessMm"], values["heightMm"]
    ag = lw * tw
    s_mod = tw * lw**2 / 6.0
    fr = 0.62 * math.sqrt(values["fcMpa"])
    sigma_comp = (values["axialKn"] * 1e3) / ag
    sigma_bend = (values["momentKnm"] * 1e6) / s_mod
    sigma_tens = sigma_bend - sigma_comp
    mcr_knm = (fr + sigma_comp) * s_mod / 1e6
    cracked = sigma_tens > fr
    crack_height = (
        hw * max(0.0, 1.0 - mcr_knm / max(1e-6, values["momentKnm"]))
        if cracked and values["momentKnm"] > 0
        else 0.0
    )
    return result(
        summary={
            "crackingMomentKnm": mcr_knm,
            "extremeTensileStressMpa": sigma_tens,
            "modulusOfRuptureMpa": fr,
            "crackingExpected": cracked,
            "crackedHeightMm": crack_height,
        },
        tables=[
            table(
                "Serviceability wall cracking check",
                [("metric", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"metric": "Axial precompression N/A", "value": sigma_comp, "unit": "MPa"},
                    {"metric": "Bending stress M/S", "value": sigma_bend, "unit": "MPa"},
                    {"metric": "Net tension (+ tension)", "value": sigma_tens, "unit": "MPa"},
                    {"metric": "Modulus of rupture fr", "value": fr, "unit": "MPa"},
                    {"metric": "Cracking moment Mcr", "value": mcr_knm, "unit": "kN-m"},
                    {
                        "metric": "Estimated cracked zone height",
                        "value": crack_height,
                        "unit": "mm",
                    },
                ],
            )
        ],
        notes=[
            "Linear uncracked stress check with fr = 0.62*sqrt(f'c) and linear moment decay to zero at top."
        ],
    )

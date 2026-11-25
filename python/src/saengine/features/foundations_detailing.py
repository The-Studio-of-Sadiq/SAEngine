"""Substructure - Rebar Detailing tab: BBS, cover, development/laps, stirrups, congestion & CAD sections."""

from __future__ import annotations

import csv
import io
import math
from typing import Any

import ezdxf

from saengine.design import stm
from saengine.design.bars import (
    beam_flexure_need,
    beam_shear_need,
    choose_stirrups,
    column_min_clear,
    diameters,
    mesh_for,
    slab_flexure_need,
)
from saengine.design.rc_detailing import crack_spacing_limit, service_stress
from saengine.drawings import bbs, cages, detailing
from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
)
from saengine.features.foundations_common import export_bytes, export_file, load_substructure_model
from saengine.report.clauses import in_force
from saengine.substructure import excavation, pile_detailing, retaining_walls, shallow


@feature(
    "foundationsDetailing.footingRebar",
    "Footing Rebar",
    part="substructure",
    fields=[
        number("lengthMm", "Footing length L", 2400.0, unit="mm", min=500.0),
        number("widthMm", "Footing width B", 2400.0, unit="mm", min=500.0),
        number("thicknessMm", "Footing thickness h", 500.0, unit="mm", min=200.0),
        number("coverMm", "Clear bottom cover", 75.0, unit="mm", min=25.0),
        number("barDiaMm", "Bar diameter", 16.0, unit="mm", min=10.0),
        number("barSpacingMm", "Bar spacing", 150.0, unit="mm", min=75.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def footing_rebar(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate footing reinforcement bar counts, cutting lengths, and minimum steel checks."""
    l_mm, b_mm, h, cov = (
        values["lengthMm"],
        values["widthMm"],
        values["thicknessMm"],
        values["coverMm"],
    )
    db, sp = values["barDiaMm"], values["barSpacingMm"]
    nx = math.floor((b_mm - 2.0 * cov) / sp) + 1
    ny = math.floor((l_mm - 2.0 * cov) / sp) + 1
    hook_leg = max(12.0 * db, 150.0)
    cut_x = l_mm - 2.0 * cov + 2.0 * hook_leg
    cut_y = b_mm - 2.0 * cov + 2.0 * hook_leg
    mass_per_m = bbs.bar_mass(db)
    total_mass_kg = (nx * cut_x + ny * cut_y) / 1000.0 * mass_per_m
    as_prov = math.pi * db**2 / 4.0 * 1000.0 / sp
    with in_force(ctx.root):
        as_min = shallow.min_steel_ratio(values["fyMpa"]) * 1000.0 * h
    rows = [
        {
            "mark": "B1 (Bottom X)",
            "diaMm": db,
            "spacingMm": sp,
            "count": nx,
            "cutMm": cut_x,
            "massKg": nx * cut_x / 1000.0 * mass_per_m,
        },
        {
            "mark": "B2 (Bottom Y)",
            "diaMm": db,
            "spacingMm": sp,
            "count": ny,
            "cutMm": cut_y,
            "massKg": ny * cut_y / 1000.0 * mass_per_m,
        },
    ]
    return result(
        summary={
            "providedSteelMm2PerM": as_prov,
            "minimumSteelMm2PerM": as_min,
            "totalSteelMassKg": total_mass_kg,
            "minSteelOk": as_prov >= as_min,
        },
        tables=[
            table(
                "Footing rebar plan & cutting lengths",
                [
                    ("mark", "Mark"),
                    ("diaMm", "Dia", "mm"),
                    ("spacingMm", "Spacing", "mm"),
                    ("count", "No."),
                    ("cutMm", "Cut length", "mm"),
                    ("massKg", "Mass", "kg"),
                ],
                rows,
            )
        ],
        notes=[
            f"Includes {hook_leg:.0f} mm 90° end hooks; steel intensity = {total_mass_kg / ((l_mm * b_mm * h) / 1e9):.1f} kg/m³."
        ],
    )


@feature(
    "foundationsDetailing.barSchedule",
    "Bar Schedule",
    part="substructure",
    fields=[
        number("defaultCoverMm", "Default cover (if missing)", 75.0, unit="mm", min=25.0),
    ],
    requires_project=True,
)
def bar_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Produce a BS/ISO bar bending schedule CSV for all substructure elements in 09 Substructure."""
    sub = load_substructure_model(ctx)
    if not sub.foundations and not sub.retainingWalls:
        raise FeatureInputError(
            "No foundations or retaining walls found in 09 Substructure/substructure.json."
        )
    rows = []
    mark_idx = 1
    with in_force(ctx.root):
        for f in sub.foundations:
            l_mm = float(f.length or 2000.0)
            b_mm = float(f.width or 1500.0)
            h_mm = float(f.thickness or 500.0)
            reinf = f.reinforcement
            cov = float(reinf.cover if reinf and reinf.cover else values["defaultCoverMm"])
            for layer_name, mesh, span_len, dist_len in (
                ("Bottom X", getattr(reinf, "bottomX", None), l_mm, b_mm),
                ("Bottom Y", getattr(reinf, "bottomY", None), b_mm, l_mm),
                ("Top X", getattr(reinf, "topX", None), l_mm, b_mm),
                ("Top Y", getattr(reinf, "topY", None), b_mm, l_mm),
            ):
                if mesh is None:
                    continue
                db, sp = float(mesh.dia), float(mesh.spacing)
                count = math.floor((dist_len - 2.0 * cov) / sp) + 1
                a_len = max(200.0, span_len - 2.0 * cov)
                b_len = max(150.0, h_mm - 2.0 * cov)
                rad = bbs.bend_radius(db)
                cut_len = bbs.round_length(
                    bbs.cutting_length("21", {"A": a_len, "B": b_len, "C": b_len}, db, rad)
                    if "21" in bbs.shapes()
                    else a_len + 2.0 * b_len
                )
                mass_kg = count * (cut_len / 1000.0) * bbs.bar_mass(db)
                rows.append(
                    {
                        "member": f.id,
                        "mark": f"F{mark_idx:02d}",
                        "layer": layer_name,
                        "diaMm": db,
                        "spacingMm": sp,
                        "count": count,
                        "cutMm": cut_len,
                        "massKg": mass_kg,
                    }
                )
                mark_idx += 1
    if not rows:
        raise FeatureInputError(
            "Substructure foundations have no reinforcement meshes defined yet."
        )
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["member", "mark", "layer", "diaMm", "spacingMm", "count", "cutMm", "massKg"],
    )
    writer.writeheader()
    writer.writerows(rows)
    out_path = export_file(ctx, "footing-bar-schedule.csv", buf.getvalue())
    return result(
        summary={
            "barMarkCount": len(rows),
            "totalMassKg": sum(r["massKg"] for r in rows),
            "csvPath": str(out_path),
        },
        tables=[
            table(
                "Substructure bar bending schedule",
                [
                    ("member", "Element"),
                    ("mark", "Mark"),
                    ("layer", "Layer"),
                    ("diaMm", "Dia", "mm"),
                    ("count", "Qty"),
                    ("cutMm", "Cut", "mm"),
                    ("massKg", "Mass", "kg"),
                ],
                rows,
            )
        ],
        notes=[f"Bar schedule exported to {out_path}"],
    )


@feature(
    "foundationsDetailing.coverCheck",
    "Cover Check",
    part="substructure",
    fields=[
        select(
            "exposure",
            "Ground exposure condition",
            [
                ("earthCast", "Cast directly against earth"),
                ("formedSoil", "Formed against soil / weather"),
                ("aggressive", "Aggressive groundwater / sulfate"),
            ],
        ),
        number("providedCoverMm", "Provided clear cover", 75.0, unit="mm", min=15.0),
        number("barDiaMm", "Main bar diameter", 16.0, unit="mm", min=8.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
    ],
    requires_project=False,
)
def cover_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check nominal concrete cover against soil exposure and durability requirements."""
    with in_force(ctx.root):
        base_cov = retaining_walls.base_cover(values["providedCoverMm"])
    min_req = (
        75.0
        if values["exposure"] == "earthCast"
        else (50.0 if values["exposure"] == "formedSoil" else 75.0)
    )
    if values["exposure"] == "formedSoil" and values["barDiaMm"] <= 16.0:
        min_req = 40.0
    min_req = max(min_req, values["barDiaMm"])
    ok = values["providedCoverMm"] >= min_req
    return result(
        summary={
            "providedCoverMm": values["providedCoverMm"],
            "requiredCoverMm": min_req,
            "baseEarthCoverMm": base_cov,
            "ok": ok,
        },
        tables=[
            table(
                "Foundation concrete cover check",
                [("item", "Parameter"), ("val", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Provided clear cover",
                        "val": values["providedCoverMm"],
                        "unit": "mm",
                    },
                    {"item": "Required minimum cover", "val": min_req, "unit": "mm"},
                    {"item": "Code-pack earth-cast base cover", "val": base_cov, "unit": "mm"},
                ],
            )
        ],
        notes=[f"Exposure '{values['exposure']}': {'PASS' if ok else 'INCREASE COVER'}."],
    )


@feature(
    "foundationsDetailing.capReinforcement",
    "Cap Reinforcement",
    part="substructure",
    fields=[
        number("capLengthMm", "Cap length L", 2800.0, unit="mm", min=600.0),
        number("capWidthMm", "Cap width B", 2800.0, unit="mm", min=600.0),
        number("capThicknessMm", "Cap thickness h", 900.0, unit="mm", min=400.0),
        number("bottomSteelMm2PerM", "Required bottom main steel", 1800.0, unit="mm²/m", min=200.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def cap_reinforcement(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detail pile cap bottom main mesh, top nominal steel, and side-face shrinkage bands."""
    h, fy = values["capThicknessMm"], values["fyMpa"]
    with in_force(ctx.root):
        as_min = shallow.min_steel_ratio(fy) * 1000.0 * h
        bot_req = max(values["bottomSteelMm2PerM"], as_min)
        top_req = 0.5 * as_min
        bars = diameters("foundation")
        bot_mesh = mesh_for(bot_req, 250.0, bars)
        top_mesh = mesh_for(top_req, 300.0, bars)
        side_bars = "Ø12@200 each side face" if h >= 750.0 else "None required (h < 750 mm)"
    return result(
        summary={
            "bottomMesh": f"Ø{bot_mesh.dia:g}@{bot_mesh.spacing:g}" if bot_mesh else "Custom",
            "topMesh": f"Ø{top_mesh.dia:g}@{top_mesh.spacing:g}" if top_mesh else "Custom",
            "sideFaceSteel": side_bars,
            "minSteelMm2PerM": as_min,
        },
        tables=[
            table(
                "Pile cap reinforcement schedule",
                [
                    ("zone", "Reinforcement zone"),
                    ("reqMm2PerM", "Required", "mm²/m"),
                    ("detail", "Selected detail"),
                ],
                [
                    {
                        "zone": "Bottom X & Y main ties",
                        "reqMm2PerM": bot_req,
                        "detail": f"Ø{bot_mesh.dia:g}@{bot_mesh.spacing:g}"
                        if bot_mesh
                        else "Custom",
                    },
                    {
                        "zone": "Top X & Y nominal mat",
                        "reqMm2PerM": top_req,
                        "detail": f"Ø{top_mesh.dia:g}@{top_mesh.spacing:g}"
                        if top_mesh
                        else "Custom",
                    },
                    {"zone": "Side-face crack control", "reqMm2PerM": 0.0, "detail": side_bars},
                ],
            )
        ],
        notes=[
            "Provide full 90° hooks or U-bars at cap perimeter to anchor bottom tension ties past pile centres."
        ],
    )


@feature(
    "foundationsDetailing.trussModel",
    "Truss Model",
    part="substructure",
    fields=[
        number("puKn", "Factored column load Pu", 2600.0, unit="kN", min=10.0),
        number("pileSpacingMm", "Pile spacing s", 1800.0, unit="mm", min=600.0),
        number("capThicknessMm", "Cap thickness h", 950.0, unit="mm", min=400.0),
        number("pileDiaMm", "Pile diameter D", 600.0, unit="mm", min=250.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def truss_model(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build 3D Strut-and-Tie truss node coordinates, strut angles, and force demands for a 4-pile cap."""
    z_arm = values["capThicknessMm"] - 150.0 - 75.0
    dx = values["pileSpacingMm"] / 2.0 - 150.0
    strut_len = math.sqrt(2.0 * dx**2 + z_arm**2)
    angle_deg = math.degrees(math.atan2(z_arm, math.sqrt(2.0) * dx))
    p_pile_n = (values["puKn"] * 1e3) / 4.0
    strut_force_n = p_pile_n / math.sin(math.radians(angle_deg))
    tie_force_n = (p_pile_n * dx) / z_arm
    with in_force(ctx.root):
        theta_min = stm.min_angle()
        node_cap = stm.node_capacity(
            values["fcMpa"], math.pi * values["pileDiaMm"] ** 2 / 4.0, kind="CCT"
        )
        as_tie = tie_force_n / (stm.phi() * values["fyMpa"])
    rows = [
        {
            "member": "Diag. strut S1–S4 (Col to Pile)",
            "lengthMm": strut_len,
            "forceKn": strut_force_n / 1e3,
            "angleDeg": angle_deg,
        },
        {
            "member": "Orthogonal bottom ties T1–T4",
            "lengthMm": values["pileSpacingMm"],
            "forceKn": tie_force_n / 1e3,
            "angleDeg": 0.0,
        },
    ]
    return result(
        summary={
            "strutAngleDeg": angle_deg,
            "strutForceKn": strut_force_n / 1e3,
            "tieForceKn": tie_force_n / 1e3,
            "tieAreaMm2": as_tie,
            "nodeCapacityKn": node_cap / 1e3,
            "angleOk": angle_deg >= theta_min,
        },
        tables=[
            table(
                "3D Strut-and-tie truss members",
                [
                    ("member", "STM member"),
                    ("lengthMm", "Length", "mm"),
                    ("forceKn", "Force", "kN"),
                    ("angleDeg", "Angle", "°"),
                ],
                rows,
            )
        ],
        notes=[
            f"Minimum STM strut angle = {theta_min:g}°. Tie steel per edge band ≥ {as_tie:.0f} mm²."
        ],
    )


@feature(
    "foundationsDetailing.anchorage",
    "Anchorage",
    part="substructure",
    fields=[
        number("barDiaMm", "Starter / dowel bar diameter db", 20.0, unit="mm", min=8.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
        checkbox("topBar", "Top-cast bar (>300 mm fresh concrete below)", False),
        checkbox("hooked", "90° standard hook into footing/cap", True),
    ],
    requires_project=False,
)
def anchorage(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check straight tension, compression, and standard hook anchorage lengths of pile and column bars."""
    db, fy, fc = values["barDiaMm"], values["fyMpa"], values["fcMpa"]
    with in_force(ctx.root):
        ld_tens = detailing.development_tension(db, fy, fc, top=values["topBar"])
        ld_comp = detailing.development_compression(db, fy, fc)
        ldh = detailing.hook_development(db, fy, fc)
    rows = [
        {"mode": "Straight tension development ld", "mm": ld_tens.value},
        {"mode": "90° standard hook development ldh", "mm": ldh.value},
        {"mode": "Compression dowel development ldc", "mm": ld_comp.value},
    ]
    return result(
        summary={
            "tensionLdMm": rows[0]["mm"],
            "hookLdhMm": rows[1]["mm"],
            "compressionLdcMm": rows[2]["mm"],
        },
        tables=[
            table(
                "Anchorage & development lengths",
                [("mode", "Anchorage mode"), ("mm", "Required length", "mm")],
                rows,
            )
        ],
        notes=[f"{ld_tens.formula} ({ld_tens.clause})."],
    )


@feature(
    "foundationsDetailing.wallReinforcement",
    "Wall Reinforcement",
    part="substructure",
    fields=[
        number("stemThickMm", "Wall stem thickness", 350.0, unit="mm", min=150.0),
        number("stemHeightM", "Stem height H", 4.5, unit="m", min=1.0),
        number("soilFaceMomentKnmPerM", "Factored stem base moment", 145.0, unit="kN·m/m", min=1.0),
        number("coverMm", "Clear cover at soil face", 50.0, unit="mm", min=25.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def wall_reinforcement(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detail retaining wall vertical main bars, front face bars, and horizontal shrinkage steel."""
    h, cov, fc, fy = values["stemThickMm"], values["coverMm"], values["fcMpa"], values["fyMpa"]
    d_mm = h - cov - 10.0
    with in_force(ctx.root):
        flex = slab_flexure_need(values["soilFaceMomentKnmPerM"] * 1e6, d_mm, fc, fy)
        v_min = 0.0015 * 1000.0 * h
        h_min = 0.0025 * 1000.0 * h
        bars = diameters("wall")
        main_mesh = mesh_for(max(flex.area, v_min), 300.0, bars)
        front_mesh = mesh_for(0.5 * v_min, 300.0, bars)
        horiz_mesh = mesh_for(0.5 * h_min, 300.0, bars)
    return result(
        summary={
            "stemSoilFace": f"Ø{main_mesh.dia:g}@{main_mesh.spacing:g}" if main_mesh else "Custom",
            "stemFrontFace": f"Ø{front_mesh.dia:g}@{front_mesh.spacing:g}"
            if front_mesh
            else "Custom",
            "horizontalEachFace": f"Ø{horiz_mesh.dia:g}@{horiz_mesh.spacing:g}"
            if horiz_mesh
            else "Custom",
            "soilFaceSteelMm2PerM": max(flex.area, v_min),
        },
        tables=[
            table(
                "Retaining wall stem reinforcement",
                [
                    ("face", "Face / Direction"),
                    ("reqMm2PerM", "Required", "mm²/m"),
                    ("mesh", "Selected mesh"),
                ],
                [
                    {
                        "face": "Soil face vertical (main)",
                        "reqMm2PerM": max(flex.area, v_min),
                        "mesh": f"Ø{main_mesh.dia:g}@{main_mesh.spacing:g}"
                        if main_mesh
                        else "Custom",
                    },
                    {
                        "face": "Front face vertical",
                        "reqMm2PerM": 0.5 * v_min,
                        "mesh": f"Ø{front_mesh.dia:g}@{front_mesh.spacing:g}"
                        if front_mesh
                        else "Custom",
                    },
                    {
                        "face": "Horizontal each face",
                        "reqMm2PerM": 0.5 * h_min,
                        "mesh": f"Ø{horiz_mesh.dia:g}@{horiz_mesh.spacing:g}"
                        if horiz_mesh
                        else "Custom",
                    },
                ],
            )
        ],
        notes=[
            "Vertical main bars may be curtailed above mid-height where bending moment drops below 50% of base demand."
        ],
    )


@feature(
    "foundationsDetailing.waterBars",
    "Water Bars",
    part="substructure",
    fields=[
        number("waterHeadM", "Design groundwater head above joint", 3.5, unit="m", min=0.0),
        number("wallThickMm", "Wall / slab thickness", 350.0, unit="mm", min=150.0),
        number("jointLengthM", "Total construction/kicker joint length", 65.0, unit="m", min=1.0),
        select(
            "jointType",
            "Joint category",
            [
                ("construction", "Construction / kicker joint"),
                ("expansion", "Movement / expansion joint"),
            ],
        ),
    ],
    requires_project=False,
)
def water_bars(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select PVC/hydrophilic waterstop profile and schedule linear quantities for buried joints."""
    head = values["waterHeadM"]
    t = values["wallThickMm"]
    if values["jointType"] == "expansion":
        width_mm = min(max(200.0, t * 0.7), 320.0)
        profile_desc = f"Centre-bulb PVC waterstop {width_mm:.0f} mm wide"
    elif head <= 4.0:
        width_mm = 200.0
        profile_desc = "20×10 mm hydrophilic swellable strip + 200 mm PVC rear-guard"
    else:
        width_mm = min(250.0, t * 0.7)
        profile_desc = f"Dual system: {width_mm:.0f} mm dumbbell PVC waterstop + injectable hose"
    return result(
        summary={
            "hydrostaticPressureKpa": 9.81 * head,
            "waterstopWidthMm": width_mm,
            "totalLengthM": values["jointLengthM"] * 1.05,
            "profile": profile_desc,
        },
        tables=[
            table(
                "Waterstop selection & takeoff",
                [("item", "Item"), ("spec", "Specification"), ("qty", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Waterstop profile",
                        "spec": profile_desc,
                        "qty": width_mm,
                        "unit": "mm width",
                    },
                    {
                        "item": "Design water pressure",
                        "spec": f"Head {head:g} m",
                        "qty": 9.81 * head,
                        "unit": "kPa",
                    },
                    {
                        "item": "Order length (incl. 5% weld laps)",
                        "spec": values["jointType"],
                        "qty": values["jointLengthM"] * 1.05,
                        "unit": "m",
                    },
                ],
            )
        ],
        notes=[
            "Ensure minimum concrete cover to waterstop edges ≥ aggregate size + 25 mm (avoid honeycombing)."
        ],
    )


@feature(
    "foundationsDetailing.joints",
    "Joints",
    part="substructure",
    fields=[
        number("wallLengthM", "Retaining wall total length", 45.0, unit="m", min=2.0),
        number("contractionSpacingM", "Contraction joint spacing", 7.5, unit="m", min=3.0),
        number("expansionSpacingM", "Expansion joint spacing", 22.5, unit="m", min=10.0),
        number("wallThickMm", "Wall thickness", 350.0, unit="mm", min=150.0),
    ],
    requires_project=False,
)
def joints(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detail contraction and expansion joint count, shear keys, and compressible filler thickness."""
    l_m = values["wallLengthM"]
    n_exp = max(0, math.floor(l_m / values["expansionSpacingM"]) - 1)
    n_cont = max(0, math.floor(l_m / values["contractionSpacingM"]) - 1 - n_exp)
    key_w = round(values["wallThickMm"] / 3.0)
    key_d = round(min(50.0, values["wallThickMm"] / 6.0))
    return result(
        summary={
            "contractionJointCount": n_cont,
            "expansionJointCount": n_exp,
            "shearKeyWidthMm": key_w,
            "shearKeyDepthMm": key_d,
            "fillerThicknessMm": 20.0,
        },
        tables=[
            table(
                "Retaining wall movement joint schedule",
                [("joint", "Joint type"), ("count", "Count"), ("detail", "Key / filler detail")],
                [
                    {
                        "joint": "Contraction joint (50% bars stopped)",
                        "count": n_cont,
                        "detail": f"Shear key {key_w}×{key_d} mm, debonded face",
                    },
                    {
                        "joint": "Full expansion joint (all bars stopped)",
                        "count": n_exp,
                        "detail": "20 mm compressible filler + centre-bulb waterstop + dowels",
                    },
                ],
            )
        ],
        notes=[
            "Stop continuous longitudinal distribution steel at expansion joints; pass greased dowel sleeves if shear transfer is needed."
        ],
    )


@feature(
    "foundationsDetailing.tieBeamRebar",
    "Tie Beam Rebar",
    part="substructure",
    fields=[
        number("widthMm", "Tie beam width bw", 300.0, unit="mm", min=150.0),
        number("depthMm", "Tie beam depth h", 400.0, unit="mm", min=200.0),
        number("axialForceKn", "Design axial tie force", 120.0, unit="kN", min=1.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def tie_beam_rebar(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detail symmetric top/bottom longitudinal bars and closed seismic ties in foundation tie beams."""
    bw, h, fy = values["widthMm"], values["depthMm"], values["fyMpa"]
    as_tens = (values["axialForceKn"] * 1e3) / (0.90 * fy)
    as_min = 0.005 * bw * h
    as_req = max(as_tens, as_min)
    db = 16.0
    n_bars = max(4, math.ceil(as_req / (math.pi * db**2 / 4.0)))
    if n_bars % 2 == 1:
        n_bars += 1
    tie_spacing = min(16.0 * db, 48.0 * 10.0, min(bw, h), 300.0)
    with in_force(ctx.root):
        lap_len = detailing.lap_tension(db, fy, values["fcMpa"], top=False).value
    return result(
        summary={
            "longitudinalBars": f"{n_bars}-Ø{db:g}",
            "stirrups": f"Ø10@{tie_spacing:g}",
            "tensionLapMm": lap_len,
            "providedAreaMm2": n_bars * math.pi * db**2 / 4.0,
        },
        tables=[
            table(
                "Tie beam reinforcement detailing",
                [("item", "Detail"), ("spec", "Value")],
                [
                    {
                        "item": "Longitudinal bars (symmetric)",
                        "spec": f"{n_bars}-Ø{db:g} ({n_bars // 2} top + {n_bars // 2} bottom)",
                    },
                    {
                        "item": "Closed transverse ties",
                        "spec": f"Ø10 @ {tie_spacing:.0f} mm c/c with 135° seismic hooks",
                    },
                    {"item": "Tension lap length", "spec": f"{lap_len:.0f} mm"},
                ],
            )
        ],
        notes=[
            "Extend tie beam longitudinal bars full anchorage length into footing or column core."
        ],
    )


@feature(
    "foundationsDetailing.gradeBeamRebar",
    "Grade Beam Rebar",
    part="substructure",
    fields=[
        number("widthMm", "Beam width bw", 350.0, unit="mm", min=150.0),
        number("depthMm", "Beam depth h", 600.0, unit="mm", min=250.0),
        number("muKnm", "Design moment Mu", 160.0, unit="kN·m", min=1.0),
        number("vuKn", "Design shear Vu", 140.0, unit="kN", min=0.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def grade_beam_rebar(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detail top/bottom flexural reinforcement and shear stirrups for foundation grade beams."""
    bw, h, fc, fy = values["widthMm"], values["depthMm"], values["fcMpa"], values["fyMpa"]
    d_mm = h - 50.0 - 10.0 - 10.0
    with in_force(ctx.root):
        flex = beam_flexure_need(values["muKnm"] * 1e6, bw, d_mm, 60.0, fc, fy, h=h)
        shear = beam_shear_need(values["vuKn"] * 1e3, bw, d_mm, fc, fy)
        stir = choose_stirrups(shear, bw)
    n_main = max(2, math.ceil(flex.area / (math.pi * 20.0**2 / 4.0)))
    return result(
        summary={
            "requiredFlexSteelMm2": flex.area,
            "proposedMainBars": f"{n_main}-Ø20",
            "stirrups": f"2L-Ø{stir.dia:g}@{stir.spacing:g}" if stir else "Increase section",
        },
        tables=[
            table(
                "Grade beam reinforcement details",
                [("zone", "Zone"), ("detail", "Specification"), ("areaMm2", "Area", "mm²")],
                [
                    {
                        "zone": "Main tension face",
                        "detail": f"{n_main}-Ø20",
                        "areaMm2": n_main * math.pi * 20.0**2 / 4.0,
                    },
                    {
                        "zone": "Opposite face hanger",
                        "detail": "2-Ø16",
                        "areaMm2": 2 * math.pi * 16.0**2 / 4.0,
                    },
                    {
                        "zone": "Shear links",
                        "detail": f"2L-Ø{stir.dia:g}@{stir.spacing:g}" if stir else "Increase bw/h",
                        "areaMm2": 0.0,
                    },
                ],
            )
        ],
        notes=[
            "Provide continuous top and bottom steel across supports for reversible settlement/soil moments."
        ],
    )


@feature(
    "foundationsDetailing.strapBeamRebar",
    "Strap Beam Rebar",
    part="substructure",
    fields=[
        number("widthMm", "Strap width bw", 450.0, unit="mm", min=200.0),
        number("depthMm", "Strap depth h", 800.0, unit="mm", min=300.0),
        number("muHogKnm", "Peak hogging moment Mu", 380.0, unit="kN·m", min=1.0),
        number("vuKn", "Design strap shear Vu", 220.0, unit="kN", min=0.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def strap_beam_rebar(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detail top hogging tension bars, bottom bars, and shear stirrups for eccentric strap beams."""
    bw, h, fc, fy = values["widthMm"], values["depthMm"], values["fcMpa"], values["fyMpa"]
    d_mm = h - 50.0 - 10.0 - 12.0
    with in_force(ctx.root):
        flex = beam_flexure_need(values["muHogKnm"] * 1e6, bw, d_mm, 65.0, fc, fy, h=h)
        shear = beam_shear_need(values["vuKn"] * 1e3, bw, d_mm, fc, fy)
        stir = choose_stirrups(shear, bw)
    n_top = max(3, math.ceil(flex.area / (math.pi * 25.0**2 / 4.0)))
    return result(
        summary={
            "requiredTopSteelMm2": flex.area,
            "topBars": f"{n_top}-Ø25",
            "stirrups": f"2L-Ø{stir.dia:g}@{stir.spacing:g}" if stir else "Increase bw/h",
        },
        tables=[
            table(
                "Strap beam reinforcement schedule",
                [("zone", "Zone"), ("bars", "Detail"), ("areaMm2", "Area", "mm²")],
                [
                    {
                        "zone": "Top hogging tension",
                        "bars": f"{n_top}-Ø25",
                        "areaMm2": n_top * math.pi * 25.0**2 / 4.0,
                    },
                    {
                        "zone": "Bottom nominal/compression",
                        "bars": "3-Ø16",
                        "areaMm2": 3 * math.pi * 16.0**2 / 4.0,
                    },
                    {
                        "zone": "Closed stirrups",
                        "bars": f"2L-Ø{stir.dia:g}@{stir.spacing:g}"
                        if stir
                        else "Increase section",
                        "areaMm2": 0.0,
                    },
                ],
            )
        ],
        notes=["Hook top tension bars down into the outer face of the eccentric exterior footing."],
    )


@feature(
    "foundationsDetailing.beamLapZones",
    "Beam Lap Zones",
    part="substructure",
    fields=[
        number("spanM", "Clear span L", 5.4, unit="m", min=1.5),
        number("barDiaMm", "Main bar diameter db", 20.0, unit="mm", min=10.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def beam_lap_zones(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Identify permitted tension/compression lap zones and splice lengths along foundation beams."""
    l_mm = values["spanM"] * 1000.0
    db, fc, fy = values["barDiaMm"], values["fcMpa"], values["fyMpa"]
    with in_force(ctx.root):
        lap_bot = detailing.lap_tension(db, fy, fc, top=False)
        lap_top = detailing.lap_tension(db, fy, fc, top=True)
    lb_bot = lap_bot.value
    lb_top = lap_top.value
    rows = [
        {
            "layer": "Bottom bars",
            "zone": f"At supports / outer quarter (0 to {0.25 * l_mm:.0f} mm)",
            "lapMm": lb_bot,
            "note": "Avoid mid-span high sagging region",
        },
        {
            "layer": "Top bars",
            "zone": f"Mid-span third ({0.33 * l_mm:.0f} to {0.67 * l_mm:.0f} mm)",
            "lapMm": lb_top,
            "note": "Includes top-bar casting factor",
        },
    ]
    return result(
        summary={
            "bottomLapMm": lb_bot,
            "topLapMm": lb_top,
            "midSpanZoneStartMm": 0.33 * l_mm,
            "midSpanZoneEndMm": 0.67 * l_mm,
        },
        tables=[
            table(
                "Recommended foundation beam lap splice zones",
                [
                    ("layer", "Bar layer"),
                    ("zone", "Permitted splice zone"),
                    ("lapMm", "Lap length", "mm"),
                    ("note", "Guidance"),
                ],
                rows,
            )
        ],
        notes=[
            "Stagger laps by at least 0.3 × lap length where ≥ 50% of bars are spliced at one section."
        ],
    )


@feature(
    "foundationsDetailing.stirrupLayout",
    "Stirrup Layout",
    part="substructure",
    fields=[
        number("clearSpanMm", "Clear beam span", 4800.0, unit="mm", min=1000.0),
        number("beamDepthMm", "Beam depth h", 600.0, unit="mm", min=250.0),
        number("beamWidthMm", "Beam width bw", 350.0, unit="mm", min=150.0),
        number("endSpacingMm", "Support-zone stirrup spacing", 125.0, unit="mm", min=50.0),
        number("midSpacingMm", "Mid-span stirrup spacing", 250.0, unit="mm", min=75.0),
        number("stirrupDiaMm", "Stirrup bar diameter", 10.0, unit="mm", min=8.0),
    ],
    requires_project=False,
)
def stirrup_layout(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute variable stirrup spacing zones and cutting length for a foundation beam."""
    ln, h, bw = values["clearSpanMm"], values["beamDepthMm"], values["beamWidthMm"]
    zone_len = min(2.0 * h, ln / 3.0)
    with in_force(ctx.root):
        hook = detailing.standard_hook(values["stirrupDiaMm"], 135.0, transverse=True, closed=True)
        cut_len = detailing.stirrup_length(bw - 80.0, h - 80.0, values["stirrupDiaMm"], hook)
        spaced = detailing.space(
            0.0,
            ln,
            values["midSpacingMm"],
            [
                (0.0, zone_len, values["endSpacingMm"], "Left support"),
                (ln - zone_len, ln, values["endSpacingMm"], "Right support"),
            ],
            50.0,
        )
    total_count = sum(z["count"] for z in spaced)
    return result(
        summary={
            "totalStirrups": total_count,
            "stirrupCutLengthMm": cut_len,
            "endZoneLengthMm": zone_len,
        },
        tables=[
            table(
                "Stirrup spacing zones along span",
                [
                    ("zone", "Zone"),
                    ("start", "Start", "mm"),
                    ("end", "End", "mm"),
                    ("spacing", "Spacing", "mm"),
                    ("count", "Qty"),
                ],
                spaced,
            )
        ],
        notes=[
            f"Closed 135° stirrup cutting length = {cut_len:.0f} mm (40 mm clear cover assumed)."
        ],
    )


@feature(
    "foundationsDetailing.detailSections",
    "Detail Sections",
    part="substructure",
    fields=[
        number("lengthMm", "Section footing length L", 2400.0, unit="mm", min=600.0),
        number("thicknessMm", "Footing thickness h", 500.0, unit="mm", min=250.0),
        number("colWidthMm", "Column width c1", 400.0, unit="mm", min=150.0),
        number("coverMm", "Clear cover", 75.0, unit="mm", min=25.0),
    ],
    requires_project=True,
)
def detail_sections(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate foundation section geometry and export a CAD DXF into 09 Substructure/exports."""
    l_mm, h_mm, c1, cov = (
        values["lengthMm"],
        values["thicknessMm"],
        values["colWidthMm"],
        values["coverMm"],
    )
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    # Footing outline
    msp.add_lwpolyline(
        [(0, 0), (l_mm, 0), (l_mm, h_mm), (0, h_mm), (0, 0)], dxfattribs={"layer": "CONCRETE"}
    )
    # Column stub
    x0 = (l_mm - c1) / 2.0
    msp.add_lwpolyline(
        [(x0, h_mm), (x0, h_mm + 600.0), (x0 + c1, h_mm + 600.0), (x0 + c1, h_mm)],
        dxfattribs={"layer": "CONCRETE"},
    )
    # Bottom rebar U-hook profile
    msp.add_lwpolyline(
        [(cov, h_mm - cov), (cov, cov), (l_mm - cov, cov), (l_mm - cov, h_mm - cov)],
        dxfattribs={"layer": "REBAR"},
    )
    buf = io.StringIO()
    doc.write(buf)
    out_path = export_bytes(ctx, "foundation-detail-sections.dxf", buf.getvalue().encode("utf-8"))
    coords = [
        {"element": "Footing concrete", "x0Mm": 0.0, "y0Mm": 0.0, "x1Mm": l_mm, "y1Mm": h_mm},
        {"element": "Column stub", "x0Mm": x0, "y0Mm": h_mm, "x1Mm": x0 + c1, "y1Mm": h_mm + 600.0},
        {
            "element": "Bottom main mat",
            "x0Mm": cov,
            "y0Mm": cov,
            "x1Mm": l_mm - cov,
            "y1Mm": h_mm - cov,
        },
    ]
    return result(
        summary={"dxfPath": str(out_path), "sectionWidthMm": l_mm, "sectionHeightMm": h_mm},
        tables=[
            table(
                "Section detail coordinates",
                [
                    ("element", "Element"),
                    ("x0Mm", "x0", "mm"),
                    ("y0Mm", "y0", "mm"),
                    ("x1Mm", "x1", "mm"),
                    ("y1Mm", "y1", "mm"),
                ],
                coords,
            )
        ],
        notes=[f"DXF section drawing written to {out_path}"],
    )


@feature(
    "foundationsDetailing.barBendingDetail",
    "Bar Bending Detail",
    part="substructure",
    fields=[
        select(
            "shapeCode",
            "Shape code",
            [
                ("00", "00 - Straight"),
                ("11", "11 - L-bar (90° bend)"),
                ("21", "21 - U-bar (two 90° bends)"),
                ("51", "51 - Closed link"),
            ],
        ),
        number("dimAMm", "Dimension A", 2250.0, unit="mm", min=100.0),
        number("dimBMm", "Dimension B", 350.0, unit="mm", min=50.0),
        number("dimCMm", "Dimension C", 350.0, unit="mm", min=50.0),
        number("barDiaMm", "Bar diameter db", 16.0, unit="mm", min=8.0),
    ],
    requires_project=False,
)
def bar_bending_detail(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute bend radius, hook allowance, and total cutting length for a standard bar shape."""
    code, db = values["shapeCode"], values["barDiaMm"]
    dims = {"A": values["dimAMm"], "B": values["dimBMm"], "C": values["dimCMm"]}
    with in_force(ctx.root):
        rad = bbs.bend_radius(db, transverse=(code == "51"))
        if code in bbs.shapes():
            cut = bbs.cutting_length(code, dims, db, rad)
            shape_name = bbs.shapes()[code].name
        else:
            cut = dims["A"] + (dims["B"] if code != "00" else 0.0)
            shape_name = f"Shape {code}"
        rounded = bbs.round_length(cut)
    mass_kg = (rounded / 1000.0) * bbs.bar_mass(db)
    return result(
        summary={
            "shapeName": shape_name,
            "bendRadiusMm": rad,
            "exactLengthMm": cut,
            "roundedCutMm": rounded,
            "unitMassKg": mass_kg,
        },
        tables=[
            table(
                "Bar bending detail dimensions",
                [("param", "Parameter"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"param": "Shape", "val": shape_name, "unit": "-"},
                    {"param": "Minimum former radius R", "val": rad, "unit": "mm"},
                    {"param": "Exact calculated length", "val": cut, "unit": "mm"},
                    {"param": "Rounded cutting length", "val": rounded, "unit": "mm"},
                    {"param": "Mass per bar", "val": mass_kg, "unit": "kg"},
                ],
            )
        ],
        notes=["Bend radii and deductions follow standard bar-bending schedule rules."],
    )


@feature(
    "foundationsDetailing.reinforcementKey",
    "Reinforcement Key",
    part="substructure",
    fields=[
        number("barDiaMm", "Reference bar diameter", 16.0, unit="mm", min=8.0),
    ],
    requires_project=False,
)
def reinforcement_key(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile the standard legend of bar marks, bend radii, and shape codes for detailing drawings."""
    with in_force(ctx.root):
        all_shapes = bbs.shapes()
        rad_main = bbs.bend_radius(values["barDiaMm"], transverse=False)
        rad_link = bbs.bend_radius(10.0, transverse=True)
    rows = [
        {"code": s.code, "name": s.name, "letters": ", ".join(s.letters), "bends": s.bends}
        for s in list(all_shapes.values())[:10]
    ]
    return result(
        summary={
            "shapeCount": len(all_shapes),
            "mainFormerRadiusMm": rad_main,
            "linkFormerRadiusMm": rad_link,
        },
        tables=[
            table(
                "Standard bar shape key",
                [
                    ("code", "Code"),
                    ("name", "Shape"),
                    ("letters", "Dimensions"),
                    ("bends", "Bends"),
                ],
                rows,
            )
        ],
        notes=[
            "Notation: T1 = top outer layer, T2 = top inner layer, B1 = bottom outer layer, B2 = bottom inner layer."
        ],
    )


@feature(
    "foundationsDetailing.detailScale",
    "Detail Scale",
    part="substructure",
    fields=[
        number("buildingLengthM", "Substructure plan length", 32.0, unit="m", min=2.0),
        number("buildingWidthM", "Substructure plan width", 20.0, unit="m", min=2.0),
        select(
            "sheetSize",
            "Drawing sheet",
            [("A1", "ISO A1 (841 × 594 mm)"), ("A3", "ISO A3 (420 × 297 mm)")],
        ),
    ],
    requires_project=False,
)
def detail_scale(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Recommend standard engineering drawing scales for foundation plans, sections, and joint details."""
    avail_w = 760.0 if values["sheetSize"] == "A1" else 360.0
    avail_h = 520.0 if values["sheetSize"] == "A1" else 240.0
    raw_scale = max(
        (values["buildingLengthM"] * 1000.0) / avail_w,
        (values["buildingWidthM"] * 1000.0) / avail_h,
    )
    std_scales = [20, 25, 50, 75, 100, 150, 200, 250, 500]
    plan_scale = next((s for s in std_scales if s >= raw_scale), 500)
    rows = [
        {"view": "Foundation setting-out plan", "scale": f"1:{plan_scale}"},
        {"view": "Footing & pile cap sections", "scale": "1:20"},
        {"view": "Retaining wall stem & base sections", "scale": "1:25"},
        {"view": "Waterstop & dowel joint details", "scale": "1:10"},
    ]
    return result(
        summary={
            "recommendedPlanScale": f"1:{plan_scale}",
            "sectionScale": "1:20",
            "jointDetailScale": "1:10",
        },
        tables=[
            table(
                "Recommended foundation detail scales",
                [("view", "Drawing view"), ("scale", "Scale")],
                rows,
            )
        ],
        notes=[
            f"Sized to fit {values['buildingLengthM']:g} × {values['buildingWidthM']:g} m footprint on {values['sheetSize']} sheet with title block margins."
        ],
    )


@feature(
    "foundationsDetailing.detailNotes",
    "Detail Notes",
    part="substructure",
    fields=[
        number("blindingMm", "Lean concrete blinding thickness", 75.0, unit="mm", min=50.0),
        number("coverMm", "Minimum ground cover", 75.0, unit="mm", min=40.0),
    ],
    requires_project=False,
)
def detail_notes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assemble standard substructure construction and reinforcement detailing notes."""
    notes_list = [
        f"Provide {values['blindingMm']:.0f} mm lean concrete blinding beneath all footings, pile caps, and ground beams.",
        f"Minimum clear concrete cover to earth-cast faces = {values['coverMm']:.0f} mm; formed faces = 50 mm.",
        "Support bottom reinforcement mats on high-density concrete spacer blocks (never timber or clay brick).",
        "Roughen and clean construction joint surfaces before placing fresh concrete against hardened kickers.",
    ]
    with in_force(ctx.root):
        notes_list.extend(excavation.construction_notes(None))
        g_note = pile_detailing.guidance_note(600.0)
        if g_note:
            notes_list.append(g_note)
    rows = [{"no": i + 1, "note": txt} for i, txt in enumerate(notes_list)]
    return result(
        summary={
            "noteCount": len(rows),
            "blindingMm": values["blindingMm"],
            "earthCoverMm": values["coverMm"],
        },
        tables=[
            table(
                "Standard foundation construction & detailing notes",
                [("no", "#"), ("note", "Specification note")],
                rows,
            )
        ],
        notes=["Attach to foundation general arrangement and reinforcement detail sheets."],
    )


@feature(
    "foundationsDetailing.barSpacingCheck",
    "Bar Spacing Check",
    part="substructure",
    fields=[
        number("barDiaMm", "Main bar diameter db", 20.0, unit="mm", min=8.0),
        number("centreSpacingMm", "Provided centre-to-centre spacing", 150.0, unit="mm", min=30.0),
        number("aggregateMm", "Max coarse aggregate size", 20.0, unit="mm", min=10.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
        number("coverMm", "Clear cover", 50.0, unit="mm", min=20.0),
    ],
    requires_project=False,
)
def bar_spacing_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check minimum clear distance between bars and maximum crack-control centre spacing."""
    db, s, agg = values["barDiaMm"], values["centreSpacingMm"], values["aggregateMm"]
    clear_prov = s - db
    with in_force(ctx.root):
        clear_min = column_min_clear(db, agg)
        fs = service_stress(values["fyMpa"])
        max_s = crack_spacing_limit(fs, values["coverMm"]) or 300.0
    ok = clear_prov >= clear_min and s <= max_s
    return result(
        summary={
            "clearSpacingMm": clear_prov,
            "minClearMm": clear_min,
            "maxCrackSpacingMm": max_s,
            "ok": ok,
        },
        tables=[
            table(
                "Bar spacing & crack-control check",
                [
                    ("check", "Criterion"),
                    ("actual", "Actual", "mm"),
                    ("limit", "Limit", "mm"),
                    ("status", "Status"),
                ],
                [
                    {
                        "check": "Minimum clear gap",
                        "actual": clear_prov,
                        "limit": clear_min,
                        "status": "PASS" if clear_prov >= clear_min else "FAIL",
                    },
                    {
                        "check": "Maximum centre spacing (crack control)",
                        "actual": s,
                        "limit": max_s,
                        "status": "PASS" if s <= max_s else "FAIL",
                    },
                ],
            )
        ],
        notes=[f"Service steel stress fs = {fs:.0f} MPa; aggregate size = {agg:g} mm."],
    )


@feature(
    "foundationsDetailing.barCongestion",
    "Bar Congestion",
    part="substructure",
    fields=[
        number("colWidthMm", "Column / zone width", 450.0, unit="mm", min=150.0),
        number("colDepthMm", "Column / zone depth", 450.0, unit="mm", min=150.0),
        number("barCount", "Number of longitudinal + dowel bars in zone", 12.0, min=4.0, max=60.0),
        number("barDiaMm", "Bar diameter db", 25.0, unit="mm", min=10.0),
        number("coverMm", "Side cover + link dia", 60.0, unit="mm", min=25.0),
        number("aggregateMm", "Max aggregate size", 20.0, unit="mm", min=10.0),
    ],
    requires_project=False,
)
def bar_congestion(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate bar congestion percentage and clear concrete flow gap at column-foundation joints."""
    w_eff = max(100.0, values["colWidthMm"] - 2.0 * values["coverMm"])
    d_eff = max(100.0, values["colDepthMm"] - 2.0 * values["coverMm"])
    perim = 2.0 * (w_eff + d_eff)
    n = round(values["barCount"])
    db = values["barDiaMm"]
    rho_zone = (n * math.pi * db**2 / 4.0) / (values["colWidthMm"] * values["colDepthMm"])
    clear_gap = (perim - n * db) / max(n, 1)
    min_gap = max(1.5 * db, values["aggregateMm"] + 5.0, 25.0)
    with in_force(ctx.root):
        lim = cages.limits()
        if lim is not None:
            min_gap = max(min_gap, lim.column_min, lim.column_db * db)
    congested = clear_gap < min_gap or rho_zone > 0.04
    return result(
        summary={
            "zoneSteelRatio": rho_zone,
            "meanClearGapMm": clear_gap,
            "requiredClearGapMm": min_gap,
            "congested": congested,
        },
        tables=[
            table(
                "Joint bar congestion assessment",
                [
                    ("item", "Metric"),
                    ("val", "Value"),
                    ("limit", "Threshold"),
                    ("status", "Status"),
                ],
                [
                    {
                        "item": "Average clear gap [mm]",
                        "val": clear_gap,
                        "limit": min_gap,
                        "status": "CONGESTED" if clear_gap < min_gap else "OK",
                    },
                    {
                        "item": "Lap-zone steel ratio ρ",
                        "val": rho_zone,
                        "limit": 0.04,
                        "status": "CONGESTED" if rho_zone > 0.04 else "OK",
                    },
                ],
            )
        ],
        notes=[
            "Where ρ > 4% or clear gap is tight, bundle pairs, stagger starter laps, or use mechanical couplers."
        ],
    )


@feature(
    "foundationsDetailing.lapCheck",
    "Lap Check",
    part="substructure",
    fields=[
        number("barDiaMm", "Bar diameter db", 20.0, unit="mm", min=8.0),
        number("providedLapMm", "Provided lap length", 950.0, unit="mm", min=150.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
        checkbox("tensionLap", "Tension lap (off = compression lap)", True),
        checkbox("topCast", "Top-cast horizontal bar", False),
    ],
    requires_project=False,
)
def lap_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify provided lap splice length against concrete grade, steel yield, and casting position."""
    db, fc, fy = values["barDiaMm"], values["fcMpa"], values["fyMpa"]
    with in_force(ctx.root):
        if values["tensionLap"]:
            res = detailing.lap_tension(db, fy, fc, top=values["topCast"])
            req = res.value
        else:
            res = detailing.lap_compression(db, fy, fc)
            req = res.value
    ok = values["providedLapMm"] >= req
    return result(
        summary={
            "providedLapMm": values["providedLapMm"],
            "requiredLapMm": req,
            "ratio": values["providedLapMm"] / max(req, 1.0),
            "ok": ok,
        },
        tables=[
            table(
                "Lap splice verification",
                [("param", "Parameter"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"param": "Bar diameter db", "val": db, "unit": "mm"},
                    {"param": "Provided lap length", "val": values["providedLapMm"], "unit": "mm"},
                    {"param": "Required lap length", "val": req, "unit": "mm"},
                    {"param": "Lap / db multiple", "val": req / db, "unit": "× db"},
                ],
            )
        ],
        notes=[
            f"{'Tension' if values['tensionLap'] else 'Compression'} splice check: {'PASS' if ok else 'INCREASE LAP LENGTH'}."
        ],
    )


@feature(
    "foundationsDetailing.rebarWeightCheck",
    "Rebar Weight Check",
    part="substructure",
    fields=[
        number("concreteVolM3", "Foundation concrete volume", 45.0, unit="m³", min=0.5),
        number("detailedSteelKg", "Detailed bar-schedule steel mass", 3600.0, unit="kg", min=10.0),
        number("budgetRateKgM3", "Design estimate steel rate", 85.0, unit="kg/m³", min=10.0),
    ],
    requires_project=False,
)
def rebar_weight_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare detailed reinforcement tonnage against design budget steel-to-concrete intensity."""
    est_kg = values["concreteVolM3"] * values["budgetRateKgM3"]
    actual_rate = values["detailedSteelKg"] / values["concreteVolM3"]
    diff_kg = values["detailedSteelKg"] - est_kg
    diff_pct = (diff_kg / est_kg) * 100.0
    return result(
        summary={
            "detailedSteelKg": values["detailedSteelKg"],
            "estimatedSteelKg": est_kg,
            "actualIntensityKgM3": actual_rate,
            "variancePct": diff_pct,
        },
        tables=[
            table(
                "Foundation rebar tonnage reconciliation",
                [("item", "Metric"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"item": "Concrete volume", "val": values["concreteVolM3"], "unit": "m³"},
                    {"item": "Design estimate mass", "val": est_kg, "unit": "kg"},
                    {"item": "Detailed BBS mass", "val": values["detailedSteelKg"], "unit": "kg"},
                    {"item": "Actual steel intensity", "val": actual_rate, "unit": "kg/m³"},
                    {"item": "Variance", "val": diff_pct, "unit": "%"},
                ],
            )
        ],
        notes=[
            "Typical spread footings run 55–90 kg/m³; heavily loaded pile caps/rafts run 90–140 kg/m³."
        ],
    )


@feature(
    "foundationsDetailing.detailingAudit",
    "Detailing Audit",
    part="substructure",
    fields=[
        number("minCoverMm", "Minimum allowable earth cover", 75.0, unit="mm", min=25.0),
    ],
    requires_project=True,
)
def detailing_audit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit all substructure elements in 09 Substructure/substructure.json for missing rebar or low cover."""
    sub = load_substructure_model(ctx)
    issues: list[dict[str, Any]] = []
    for f in sub.foundations:
        if f.reinforcement is None:
            issues.append(
                {"element": f.id, "type": f.type, "issue": "Missing reinforcement definition"}
            )
        else:
            if f.reinforcement.cover < values["minCoverMm"]:
                issues.append(
                    {
                        "element": f.id,
                        "type": f.type,
                        "issue": f"Cover {f.reinforcement.cover:g} mm < {values['minCoverMm']:g} mm",
                    }
                )
            if f.reinforcement.bottomX is None or f.reinforcement.bottomY is None:
                issues.append(
                    {"element": f.id, "type": f.type, "issue": "Missing bottom X or Y mesh"}
                )
    for rw in sub.retainingWalls:
        if rw.reinforcement is None:
            issues.append(
                {"element": rw.id, "type": "retainingWall", "issue": "Missing wall reinforcement"}
            )
    return result(
        summary={
            "foundationsChecked": len(sub.foundations),
            "wallsChecked": len(sub.retainingWalls),
            "issueCount": len(issues),
            "auditClean": len(issues) == 0,
        },
        tables=[
            table(
                "Substructure detailing audit findings",
                [("element", "Element"), ("type", "Type"), ("issue", "Finding")],
                issues or [{"element": "-", "type": "-", "issue": "No detailing gaps found"}],
            )
        ],
        notes=[
            "Audits 09 Substructure/substructure.json for missing meshes, low cover, and incomplete marks."
        ],
    )

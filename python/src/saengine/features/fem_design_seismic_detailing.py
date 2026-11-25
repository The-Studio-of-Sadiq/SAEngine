"""Design Reinforcement - Seismic Detailing tab: confinement hoops, capacity shear, ductility, walls, and joints."""

from __future__ import annotations

import math
from typing import Any

from saengine.design import (
    capacity_design,
    curvature_ductility,
    ductile_members,
    overstrength,
    seismic_detailing,
    seismic_rules,
    walls,
)
from saengine.drawings import detailing
from saengine.features import (
    FeatureContext,
    feature,
    number,
    result,
    select,
    table,
)
from saengine.features.fem_common import (
    concrete_rebar_defaults,
    export_fem_file,
    load_bim,
    load_materials,
    load_objects,
    load_settings,
)
from saengine.report.clauses import in_force


@feature(
    "femDesignSeismicDetailing.confinementZones",
    "Confinement Zones",
    part="fem",
    fields=[
        number("memberDepthMm", "Column/beam depth h", 500.0, unit="mm", min=150.0),
        number("clearSpanOrHeightMm", "Clear span ln or height lu", 3000.0, unit="mm", min=500.0),
        select(
            "memberKind",
            "Member kind",
            [("column", "Seismic Column"), ("beam", "Seismic Beam")],
            "column",
        ),
    ],
    requires_project=False,
)
def confinement_zones(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define plastic hinge confinement length lo for beams and columns."""
    h, lu = values["memberDepthMm"], values["clearSpanOrHeightMm"]
    if values["memberKind"] == "column":
        lo = max(h, lu / 6.0, 450.0)
    else:
        lo = 2.0 * h
    rows = [
        {"memberKind": values["memberKind"], "depthMm": h, "clearMm": lu, "confinementLengthMm": lo}
    ]
    return result(
        summary={"confinementLengthMm": lo},
        tables=[
            table(
                "Special seismic confinement zone lo",
                [
                    ("memberKind", "Kind"),
                    ("depthMm", "h", "mm"),
                    ("clearMm", "Clear", "mm"),
                    ("confinementLengthMm", "lo", "mm"),
                ],
                rows,
            )
        ],
        notes=[
            "Columns require max(hc, lu/6, 450 mm) at both ends; beams require 2h from support face."
        ],
    )


@feature(
    "femDesignSeismicDetailing.hoopSpacing",
    "Hoop Spacing",
    part="fem",
    fields=[
        number("leastDimensionMm", "Least column dimension", 400.0, unit="mm", min=150.0),
        number("longBarDiaMm", "Smallest longitudinal bar db", 16.0, unit="mm", min=10.0),
        number("crosstieSpacingHxMm", "Max crosstie spacing hx", 250.0, unit="mm", min=100.0),
    ],
    requires_project=False,
)
def hoop_spacing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute maximum permitted transverse hoop spacing so in special seismic plastic zones."""
    so_1 = values["leastDimensionMm"] / 4.0
    so_2 = 6.0 * values["longBarDiaMm"]
    with in_force(ctx.root):
        so_3 = ductile_members.so_special(values["crosstieSpacingHxMm"])
    so_gov = min(so_1, so_2, so_3)
    rows = [
        {"criterion": "b_min / 4", "limitMm": so_1},
        {"criterion": "6 · db,min", "limitMm": so_2},
        {"criterion": "100 + (350 - hx)/3 bounded [100, 150]", "limitMm": so_3},
        {"criterion": "Governing maximum hoop spacing so", "limitMm": so_gov},
    ]
    return result(
        summary={"maxHoopSpacingMm": so_gov},
        tables=[
            table(
                "Plastic-zone transverse hoop spacing limits",
                [("criterion", "Criterion"), ("limitMm", "Limit", "mm")],
                rows,
            )
        ],
        notes=["Evaluated via saengine.design.ductile_members.so_special."],
    )


@feature(
    "femDesignSeismicDetailing.hoopSize",
    "Hoop Size",
    part="fem",
    fields=[
        number("coreWidthBcMm", "Core width out-to-out bc", 320.0, unit="mm", min=100.0),
        number("coreDepthHcMm", "Core depth out-to-out hc", 320.0, unit="mm", min=100.0),
        number("grossWidthMm", "Column width b", 400.0, unit="mm", min=150.0),
        number("grossDepthMm", "Column depth h", 400.0, unit="mm", min=150.0),
        number("spacingMm", "Hoop spacing s", 100.0, unit="mm", min=50.0),
    ],
    requires_project=False,
)
def hoop_size(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate required confinement hoop area Ash and select bar diameter/legs."""
    fc, fy = concrete_rebar_defaults(ctx)
    ag = values["grossWidthMm"] * values["grossDepthMm"]
    ach = values["coreWidthBcMm"] * values["coreDepthHcMm"]
    with in_force(ctx.root):
        ash_per_s = ductile_members.ash_per_spacing(values["coreWidthBcMm"], ag, ach, fc, fy)
    ash_req = ash_per_s * values["spacingMm"]
    rows = [
        {"ashPerSpacingMm": ash_per_s, "spacingMm": values["spacingMm"], "ashRequiredMm2": ash_req}
    ]
    return result(
        summary={"ashRequiredMm2": ash_req, "ashOverS": ash_per_s},
        tables=[
            table(
                "Required confining hoop cross-sectional area Ash",
                [
                    ("ashPerSpacingMm", "Ash / s", "mm²/mm"),
                    ("spacingMm", "s", "mm"),
                    ("ashRequiredMm2", "Ash,req", "mm²"),
                ],
                rows,
            )
        ],
        notes=["Computed via saengine.design.ductile_members.ash_per_spacing."],
    )


@feature(
    "femDesignSeismicDetailing.confinementCheck",
    "Confinement Check",
    part="fem",
    fields=[
        number("providedAshMm2", "Provided hoop area Ash (all legs)", 314.0, unit="mm²", min=25.0),
        number("requiredAshMm2", "Required hoop area Ash,req", 280.0, unit="mm²", min=10.0),
    ],
    requires_project=False,
)
def confinement_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify provided transverse confinement steel area against seismic demand."""
    dcr = values["requiredAshMm2"] / values["providedAshMm2"]
    rows = [
        {
            "requiredMm2": values["requiredAshMm2"],
            "providedMm2": values["providedAshMm2"],
            "dcr": dcr,
            "ok": dcr <= 1.0,
        }
    ]
    return result(
        summary={"dcr": dcr, "passes": dcr <= 1.0},
        tables=[
            table(
                "Confinement reinforcement adequacy",
                [
                    ("requiredMm2", "Ash,req", "mm²"),
                    ("providedMm2", "Ash,prov", "mm²"),
                    ("dcr", "DCR"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=[
            "Adequate core confinement prevents brittle axial crushing during inelastic cycling."
        ],
    )


@feature(
    "femDesignSeismicDetailing.capacityDesign",
    "Capacity Design",
    part="fem",
    fields=[],
    requires_project=False,
)
def capacity_design_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect capacity-design and ductile seismic detailing scope for the active project."""
    settings = load_settings(ctx)
    _, objs = load_objects(ctx)
    _, mats = load_materials(ctx)
    bim = load_bim(ctx)
    with in_force(ctx.root):
        cap_sel = capacity_design.selected()
        scope = seismic_detailing.scope_of(settings, mats, objs, bim, root=ctx.root)
    rows = [
        {"item": str(k), "value": str(v)}
        for k, v in (scope.items() if isinstance(scope, dict) else [("items", len(scope))])
    ]
    return result(
        summary={"capacityDesignSelected": cap_sel, "scopeEntries": len(rows)},
        tables=[
            table(
                "Seismic capacity design & detailing scope",
                [("item", "Parameter"), ("value", "Value")],
                rows[:30] or [{"item": "Scope", "value": "Default"}],
            )
        ],
        notes=["Evaluated from active code pack seismic detailing and ductility rules."],
    )


@feature(
    "femDesignSeismicDetailing.overstrengthFactor",
    "Overstrength Factor",
    part="fem",
    fields=[
        number("omega0Override", "Overstrength factor Ω0 (0 = from pack)", 0.0, min=0.0, max=5.0)
    ],
    requires_project=False,
)
def overstrength_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute amplified overstrength seismic combinations Em = Ω0·QE + 0.2·SDS·D."""
    settings = load_settings(ctx)
    om = values["omega0Override"] if values["omega0Override"] > 0 else None
    with in_force(ctx.root):
        em = overstrength.em_factors(settings, omega=om)
        combos = overstrength.omega_combinations(settings, omega=om)
    rows = [
        {"name": str(c.get("name", "")), "factors": str(c.get("factors", ""))} for c in combos[:12]
    ]
    return result(
        summary={
            "omega0": float(em.get("omega", 3.0)) if isinstance(em, dict) else 3.0,
            "combinations": len(rows),
        },
        tables=[
            table(
                "Overstrength seismic combinations (Ω0·E)",
                [("name", "Combination"), ("factors", "Factors")],
                rows or [{"name": "1.2D + Ω0 E", "factors": str(em)}],
            )
        ],
        notes=["Computed via saengine.design.overstrength."],
    )


@feature(
    "femDesignSeismicDetailing.shearDemand",
    "Shear Demand",
    part="fem",
    fields=[
        number("mprLeftKnm", "Probable hinge moment Mpr,1", 260.0, unit="kN·m", min=1.0),
        number("mprRightKnm", "Probable hinge moment Mpr,2", 260.0, unit="kN·m", min=1.0),
        number("clearSpanM", "Clear span ln", 5.5, unit="m", min=1.0),
        number("gravityShearKn", "Factored gravity shear Vg", 85.0, unit="kN", min=0.0),
    ],
    requires_project=False,
)
def shear_demand(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute capacity-design shear Ve = (Mpr,1 + Mpr,2)/ln + Vg from probable hinge moments."""
    ve_sway = (values["mprLeftKnm"] + values["mprRightKnm"]) / values["clearSpanM"]
    ve_total = ve_sway + values["gravityShearKn"]
    rows = [
        {
            "plasticShearKn": ve_sway,
            "gravityShearKn": values["gravityShearKn"],
            "capacityDesignShearKn": ve_total,
        }
    ]
    return result(
        summary={"plasticHingeShearKn": ve_sway, "designShearVeKn": ve_total},
        tables=[
            table(
                "Capacity-design beam shear Ve",
                [
                    ("plasticHingeShearKn", "(Mpr1+Mpr2)/ln", "kN"),
                    ("gravityShearKn", "Vg", "kN"),
                    ("capacityDesignShearKn", "Ve", "kN"),
                ],
                rows,
            )
        ],
        notes=["Ensures flexural plastic hinging precedes brittle diagonal shear failure."],
    )


@feature(
    "femDesignSeismicDetailing.ductilityCheck",
    "Ductility Check",
    part="fem",
    fields=[
        number("q0", "Basic behaviour factor q0", 4.5, min=1.0, max=8.0),
        number("t1S", "Fundamental period T1", 0.65, unit="s", min=0.05),
        number("tcS", "Corner period Tc", 0.50, unit="s", min=0.1),
        select(
            "ductilityClass",
            "Ductility class",
            [("DCM", "Medium Ductility"), ("DCH", "High Ductility")],
            "DCH",
        ),
    ],
    requires_project=False,
)
def ductility_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute required curvature ductility factor μ_φ from q0 and period ratio T1/Tc."""
    with in_force(ctx.root):
        if curvature_ductility.rules() is not None:
            mu_phi = curvature_ductility.curvature_ductility(
                values["q0"], values["t1S"], values["tcS"], ductility=values["ductilityClass"]
            )
        else:
            q0, t1, tc = values["q0"], values["t1S"], values["tcS"]
            mu_phi = 2.0 * q0 - 1.0 if t1 >= tc else 1.0 + 2.0 * (q0 - 1.0) * tc / t1
    rows = [
        {"ductilityClass": values["ductilityClass"], "q0": values["q0"], "muPhiRequired": mu_phi}
    ]
    return result(
        summary={"requiredCurvatureDuctility": mu_phi, "ductilityClass": values["ductilityClass"]},
        tables=[
            table(
                "Curvature ductility demand μ_φ",
                [("ductilityClass", "Class"), ("q0", "q0"), ("muPhiRequired", "μ_φ,req")],
                rows,
            )
        ],
        notes=["Evaluated via saengine.design.curvature_ductility."],
    )


@feature(
    "femDesignSeismicDetailing.hingeRegion",
    "Hinge Region",
    part="fem",
    fields=[
        number("beamDepthMm", "Beam depth h", 550.0, unit="mm", min=200.0),
        number("longBarDiaMm", "Longitudinal bar db", 20.0, unit="mm", min=10.0),
        number("effDepthMm", "Effective depth d", 490.0, unit="mm", min=150.0),
    ],
    requires_project=False,
)
def hinge_region(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detail seismic plastic hinge hoop zone length and maximum stirrup spacing."""
    zone_len = 2.0 * values["beamDepthMm"]
    s_max = min(values["effDepthMm"] / 4.0, 6.0 * values["longBarDiaMm"], 150.0)
    rows = [{"hingeZoneMm": zone_len, "maxHoopSpacingMm": s_max, "closedHoopsRequired": True}]
    return result(
        summary={"hingeZoneLengthMm": zone_len, "maxStirrupSpacingMm": s_max},
        tables=[
            table(
                "Beam plastic hinge detailing",
                [
                    ("hingeZoneMm", "2h Zone", "mm"),
                    ("maxHoopSpacingMm", "Max Spacing", "mm"),
                    ("closedHoopsRequired", "Seismic Hoops"),
                ],
                rows,
            )
        ],
        notes=["Seismic hoops require 135-degree hooks anchored into confined core."],
    )


@feature(
    "femDesignSeismicDetailing.lapSplice",
    "Lap Splice",
    part="fem",
    fields=[
        number("barDiaMm", "Bar diameter db", 20.0, unit="mm", min=10.0),
        number("clearHeightMm", "Column clear height lu", 3000.0, unit="mm", min=1000.0),
        number("loZoneMm", "Plastic hinge zone lo", 500.0, unit="mm", min=300.0),
    ],
    requires_project=False,
)
def lap_splice(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Locate column lap splices in the mid-height region outside plastic hinge zones."""
    fc, fy = concrete_rebar_defaults(ctx)
    with in_force(ctx.root):
        lap = detailing.lap_tension(values["barDiaMm"], fy, fc, cls="B")
    lap_len = float(lap.value)
    mid_avail = max(0.0, values["clearHeightMm"] - 2.0 * values["loZoneMm"])
    rows = [
        {
            "spliceLengthMm": lap_len,
            "midHeightWindowMm": mid_avail,
            "fitsOutsideHinge": lap_len <= mid_avail,
        }
    ]
    return result(
        summary={
            "lapLengthMm": lap_len,
            "midHeightWindowMm": mid_avail,
            "fitsOutsideHinge": lap_len <= mid_avail,
        },
        tables=[
            table(
                "Seismic column lap splice placement",
                [
                    ("spliceLengthMm", "Class B Lap", "mm"),
                    ("midHeightWindowMm", "Center Window", "mm"),
                    ("fitsOutsideHinge", "Fits Center"),
                ],
                rows,
            )
        ],
        notes=["Lap splices are prohibited within 2h of beam faces or column lo zones."],
    )


@feature(
    "femDesignSeismicDetailing.anchorageDetail",
    "Anchorage Detail",
    part="fem",
    fields=[
        number("barDiaMm", "Beam bar diameter db", 20.0, unit="mm", min=10.0),
        number("columnDepthMm", "Joint depth hc", 500.0, unit="mm", min=200.0),
    ],
    requires_project=False,
)
def anchorage_detail(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute seismic 90-degree standard hook development length into exterior beam-column joint."""
    fc, fy = concrete_rebar_defaults(ctx)
    with in_force(ctx.root):
        ldh = max(fy * values["barDiaMm"] / (5.4 * math.sqrt(fc)), 8.0 * values["barDiaMm"], 150.0)
    ok = ldh <= values["columnDepthMm"] - 50.0
    rows = [{"seismicHookLdhMm": ldh, "availableCoreMm": values["columnDepthMm"] - 50.0, "ok": ok}]
    return result(
        summary={"seismicHookLengthMm": ldh, "passes": ok},
        tables=[
            table(
                "Joint core hooked bar anchorage",
                [
                    ("seismicHookLdhMm", "Req ldh", "mm"),
                    ("availableCoreMm", "Core Depth", "mm"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Seismic hook bends must turn toward mid-depth of the joint."],
    )


@feature(
    "femDesignSeismicDetailing.seismicReport",
    "Seismic Report",
    part="fem",
    fields=[],
    requires_project=True,
)
def seismic_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile seismic detailing scope, SDC, and material compliance to Markdown."""
    settings = load_settings(ctx)
    _, objs = load_objects(ctx)
    _, mats = load_materials(ctx)
    bim = load_bim(ctx)
    with in_force(ctx.root):
        sdc, zone = seismic_rules.seismic_design_category(settings)
        scope = seismic_detailing.scope_of(settings, mats, objs, bim, root=ctx.root)
    md = f"# Seismic Detailing Compliance Report\n\n- SDC: {sdc}\n- Zone: {zone}\n- Scope entries: {len(scope) if isinstance(scope, (dict, list)) else 0}\n"
    path = export_fem_file(ctx, "seismic-detailing-report.md", md)
    rows = [
        {"item": "Seismic Design Category", "value": str(sdc or "-")},
        {"item": "Seismic Zone", "value": str(zone or "-")},
        {"item": "Report Path", "value": str(path)},
    ]
    return result(
        summary={"sdc": str(sdc or "-"), "reportPath": str(path)},
        tables=[table("Seismic detailing report", [("item", "Item"), ("value", "Value")], rows)],
        notes=[f"Report exported to {path}"],
    )


@feature(
    "femDesignSeismicDetailing.boundaryElements",
    "Boundary Elements",
    part="fem",
    fields=[
        number("neutralAxisDepthMm", "Extreme compression depth c", 950.0, unit="mm", min=100.0),
        number("wallLengthMm", "Wall length lw", 4000.0, unit="mm", min=500.0),
        number("wallThicknessMm", "Wall thickness tw", 300.0, unit="mm", min=150.0),
        number("designDriftRatio", "Design roof drift δu/hw", 0.012, min=0.001),
    ],
    requires_project=False,
)
def boundary_elements(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Determine special shear-wall boundary element requirement and confinement length."""
    fc, fy = concrete_rebar_defaults(ctx)
    c_limit = values["wallLengthMm"] / (600.0 * max(1.5 * values["designDriftRatio"], 0.005))
    special_needed = values["neutralAxisDepthMm"] >= c_limit
    be_len = max(
        values["neutralAxisDepthMm"] - 0.1 * values["wallLengthMm"],
        0.5 * values["neutralAxisDepthMm"],
    )
    with in_force(ctx.root):
        ash = walls.boundary_ash(values["wallThicknessMm"] - 80.0, fc, fy)
    rows = [
        {
            "cActualMm": values["neutralAxisDepthMm"],
            "cLimitMm": c_limit,
            "specialRequired": special_needed,
            "boundaryLengthMm": be_len,
            "ashPerSpacing": ash,
        }
    ]
    return result(
        summary={
            "specialBoundaryRequired": special_needed,
            "boundaryLengthMm": be_len,
            "ashOverS": ash,
        },
        tables=[
            table(
                "Shear wall special boundary element check",
                [
                    ("cActualMm", "c", "mm"),
                    ("cLimitMm", "c_limit", "mm"),
                    ("specialRequired", "Required"),
                    ("boundaryLengthMm", "Length", "mm"),
                    ("ashPerSpacing", "Ash/s"),
                ],
                rows,
            )
        ],
        notes=["Evaluated via saengine.design.walls displacement-based boundary check."],
    )


@feature(
    "femDesignSeismicDetailing.crosstieSpacing",
    "Crosstie Spacing",
    part="fem",
    fields=[
        number("boundaryLengthMm", "Boundary zone length", 650.0, unit="mm", min=150.0),
        number("wallThicknessMm", "Wall thickness tw", 300.0, unit="mm", min=150.0),
        number("longBarDiaMm", "Vertical boundary bar db", 20.0, unit="mm", min=10.0),
    ],
    requires_project=False,
)
def crosstie_spacing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Specify vertical and horizontal crosstie spacing in shear wall boundary elements."""
    s_vert = min(values["wallThicknessMm"] / 3.0, 6.0 * values["longBarDiaMm"], 150.0)
    hx_max = 350.0
    n_legs = max(2, math.ceil(values["boundaryLengthMm"] / 200.0) + 1)
    rows = [
        {
            "maxVerticalSpacingMm": s_vert,
            "maxHorizontalLegSpacingMm": hx_max,
            "requiredLegs": n_legs,
        }
    ]
    return result(
        summary={"maxVerticalSpacingMm": s_vert, "requiredCrosstieLegs": n_legs},
        tables=[
            table(
                "Boundary element crosstie layout",
                [
                    ("maxVerticalSpacingMm", "Max Vert s", "mm"),
                    ("maxHorizontalLegSpacingMm", "Max hx", "mm"),
                    ("requiredLegs", "Legs"),
                ],
                rows,
            )
        ],
        notes=["Lateral support required for every corner and alternate longitudinal bar."],
    )


@feature(
    "femDesignSeismicDetailing.couplingBeam",
    "Coupling Beam",
    part="fem",
    fields=[
        number("clearSpanMm", "Coupling beam clear span ln", 1500.0, unit="mm", min=400.0),
        number("depthMm", "Beam depth h", 750.0, unit="mm", min=250.0),
        number("widthMm", "Beam width bw", 300.0, unit="mm", min=150.0),
        number("shearVuKn", "Factored shear Vu", 650.0, unit="kN", min=10.0),
    ],
    requires_project=False,
)
def coupling_beam(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check coupling beam aspect ratio ln/h and size diagonal strut reinforcement."""
    fc, fy = concrete_rebar_defaults(ctx)
    aspect = values["clearSpanMm"] / values["depthMm"]
    d = values["depthMm"] - 60.0
    v_stress = (values["shearVuKn"] * 1000.0) / (values["widthMm"] * d)
    diag_req = aspect < 2.0 and v_stress > 0.33 * math.sqrt(fc)
    alpha = math.atan2(values["depthMm"] - 120.0, values["clearSpanMm"])
    avd_mm2 = (values["shearVuKn"] * 1000.0) / (2.0 * 0.85 * fy * max(math.sin(alpha), 0.1))
    rows = [
        {
            "aspectRatio": aspect,
            "shearStressMpa": v_stress,
            "diagonalBarsRequired": diag_req,
            "diagAngleDeg": math.degrees(alpha),
            "avdPerGroupMm2": avd_mm2,
        }
    ]
    return result(
        summary={
            "aspectRatio": aspect,
            "diagonalBarsRequired": diag_req,
            "avdPerGroupMm2": avd_mm2,
        },
        tables=[
            table(
                "Coupling beam diagonal reinforcement",
                [
                    ("aspectRatio", "ln/h"),
                    ("shearStressMpa", "vu", "MPa"),
                    ("diagonalBarsRequired", "Diag Req."),
                    ("diagAngleDeg", "α", "°"),
                    ("avdPerGroupMm2", "Avd", "mm²"),
                ],
                rows,
            )
        ],
        notes=[
            "Deep coupling beams (ln/h < 2) under high shear require intersecting diagonal rebar cages."
        ],
    )


@feature(
    "femDesignSeismicDetailing.wallWebRebar",
    "Wall Web Rebar",
    part="fem",
    fields=[
        number("wallThicknessMm", "Wall thickness tw", 250.0, unit="mm", min=120.0),
        number("barDiaMm", "Web bar diameter", 12.0, unit="mm", min=8.0),
        number("spacingMm", "Bar spacing (each face)", 200.0, unit="mm", min=75.0),
    ],
    requires_project=False,
)
def wall_web_rebar(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check shear wall minimum horizontal and vertical web reinforcement ratio (0.0025)."""
    a_bar = math.pi * (values["barDiaMm"] / 2.0) ** 2
    rho = (2.0 * a_bar) / (values["wallThicknessMm"] * values["spacingMm"])
    rho_min = 0.0025
    rows = [
        {
            "providedRho": rho,
            "minRho": rho_min,
            "maxSpacingMm": 450.0,
            "ok": rho >= rho_min and values["spacingMm"] <= 450.0,
        }
    ]
    return result(
        summary={"providedRatio": rho, "minRatio": rho_min, "passes": rows[0]["ok"]},
        tables=[
            table(
                "Shear wall web reinforcement ratio",
                [
                    ("providedRho", "ρ_prov"),
                    ("minRho", "ρ_min"),
                    ("maxSpacingMm", "Max s", "mm"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=[
            "Two curtains of orthogonal reinforcement are required when shear exceeds threshold."
        ],
    )


@feature(
    "femDesignSeismicDetailing.beamColumnJoint",
    "Beam Column Joint",
    part="fem",
    fields=[
        number("columnWidthMm", "Column width bc", 450.0, unit="mm", min=200.0),
        number("columnDepthMm", "Column depth hc", 450.0, unit="mm", min=200.0),
        number("beamTopSteelMm2", "Beam top steel As", 1600.0, unit="mm²", min=100.0),
        number("columnShearKn", "Column storey shear Vcol", 180.0, unit="kN", min=0.0),
        select(
            "confinement",
            "Joint confinement",
            [
                ("interior", "4 faces confined (γ=1.7)"),
                ("exterior", "3 faces confined (γ=1.25)"),
                ("corner", "Other / corner (γ=1.0)"),
            ],
            "interior",
        ),
    ],
    requires_project=False,
)
def beam_column_joint(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify seismic beam-column joint horizontal shear strength φVn against 1.25·As·fy - Vcol."""
    fc, fy = concrete_rebar_defaults(ctx)
    gamma = {"interior": 1.7, "exterior": 1.25, "corner": 1.0}[values["confinement"]]
    vj_kn = (1.25 * values["beamTopSteelMm2"] * fy) / 1000.0 - values["columnShearKn"]
    aj = values["columnWidthMm"] * values["columnDepthMm"]
    phi_vn_kn = 0.85 * gamma * math.sqrt(fc) * aj / 1000.0
    dcr = max(0.0, vj_kn) / max(phi_vn_kn, 1e-6)
    rows = [
        {"jointShearDemandKn": vj_kn, "jointCapacityKn": phi_vn_kn, "dcr": dcr, "ok": dcr <= 1.0}
    ]
    return result(
        summary={
            "jointShearDemandKn": vj_kn,
            "jointCapacityKn": phi_vn_kn,
            "utilisation": dcr,
            "passes": dcr <= 1.0,
        },
        tables=[
            table(
                "Seismic beam-column joint shear check",
                [
                    ("jointShearDemandKn", "Vj", "kN"),
                    ("jointCapacityKn", "φVn", "kN"),
                    ("dcr", "DCR"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Joint shear demand driven by 1.25 fy overstrength in framing beam tension bars."],
    )


@feature(
    "femDesignSeismicDetailing.jointTransverse",
    "Joint Transverse",
    part="fem",
    fields=[
        number("coreWidthMm", "Joint core width bc", 370.0, unit="mm", min=150.0),
        number("columnAreaMm2", "Column gross area Ag", 202500.0, unit="mm²", min=20000.0),
        number("hoopSpacingMm", "Joint hoop spacing s", 100.0, unit="mm", min=50.0),
    ],
    requires_project=False,
)
def joint_transverse(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate required horizontal hoop area Ash inside a seismic beam-column joint."""
    fc, fy = concrete_rebar_defaults(ctx)
    ach = values["coreWidthMm"] ** 2
    with in_force(ctx.root):
        ash_s = ductile_members.ash_per_spacing(
            values["coreWidthMm"], values["columnAreaMm2"], ach, fc, fy
        )
    ash_req = ash_s * values["hoopSpacingMm"]
    rows = [
        {"ashPerSpacing": ash_s, "spacingMm": values["hoopSpacingMm"], "requiredAshMm2": ash_req}
    ]
    return result(
        summary={"requiredJointHoopAreaMm2": ash_req},
        tables=[
            table(
                "Beam-column joint transverse hoop steel",
                [
                    ("ashPerSpacing", "Ash/s", "mm²/mm"),
                    ("spacingMm", "s", "mm"),
                    ("requiredAshMm2", "Ash,req", "mm²"),
                ],
                rows,
            )
        ],
        notes=["Full column end confinement must continue through the beam-column joint core."],
    )


@feature(
    "femDesignSeismicDetailing.barDevelopment",
    "Bar Development",
    part="fem",
    fields=[
        number("beamBarDiaMm", "Beam longitudinal bar db", 20.0, unit="mm", min=10.0),
        number("columnDepthMm", "Column depth parallel to beam", 500.0, unit="mm", min=200.0),
    ],
    requires_project=False,
)
def bar_development(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check minimum column depth hc >= 20 db for straight continuous bars through interior joints."""
    min_hc = 20.0 * values["beamBarDiaMm"]
    ok = values["columnDepthMm"] >= min_hc
    rows = [
        {
            "beamBarMm": values["beamBarDiaMm"],
            "minColumnDepthMm": min_hc,
            "providedDepthMm": values["columnDepthMm"],
            "ok": ok,
        }
    ]
    return result(
        summary={"minColumnDepthMm": min_hc, "passes": ok},
        tables=[
            table(
                "Interior joint bond slip check (hc >= 20 db)",
                [
                    ("beamBarMm", "db", "mm"),
                    ("minColumnDepthMm", "Min hc", "mm"),
                    ("providedDepthMm", "Provided hc", "mm"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Prevents excessive bond slip degradation across interior seismic joints."],
    )


@feature(
    "femDesignSeismicDetailing.frictionDamper",
    "Friction Damper",
    part="fem",
    fields=[
        number("slipLoadKn", "Design slip force F_slip", 350.0, unit="kN", min=10.0),
        number("strokeMm", "Design seismic stroke ±Δ", 45.0, unit="mm", min=5.0),
        number("boltClampKn", "Normal clamping force N", 700.0, unit="kN", min=10.0),
    ],
    requires_project=False,
)
def friction_damper(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate rectangular hysteresis energy per cycle and required friction coefficient for friction dampers."""
    mu_req = values["slipLoadKn"] / (2.0 * values["boltClampKn"])
    e_cycle_kj = 4.0 * values["slipLoadKn"] * (values["strokeMm"] / 1000.0)
    rows = [
        {"slipLoadKn": values["slipLoadKn"], "requiredMu": mu_req, "energyPerCycleKj": e_cycle_kj}
    ]
    return result(
        summary={"requiredFrictionMu": mu_req, "energyPerCycleKj": e_cycle_kj},
        tables=[
            table(
                "Slotted-bolt friction damper design",
                [
                    ("slipLoadKn", "F_slip", "kN"),
                    ("requiredMu", "μ (2 planes)"),
                    ("energyPerCycleKj", "Loop Energy", "kJ"),
                ],
                rows,
            )
        ],
        notes=["Rigid-plastic rectangular hysteresis loop E = 4 · F_slip · Δ."],
    )


@feature(
    "femDesignSeismicDetailing.bucklingRestrained",
    "Buckling Restrained",
    part="fem",
    fields=[
        number("coreAreaMm2", "Yielding steel core area Asc", 3200.0, unit="mm²", min=200.0),
        number("coreFyMpa", "Actual core yield fysc", 275.0, unit="MPa", min=180.0),
        number("omegaHardening", "Strain hardening adjustment ω", 1.35, min=1.0, max=2.0),
        number("betaComp", "Compression overstrength β", 1.15, min=1.0, max=1.5),
    ],
    requires_project=False,
)
def buckling_restrained(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute BRB yield strength and capacity-adjusted maximum tension/compression brace forces."""
    py_kn = values["coreAreaMm2"] * values["coreFyMpa"] / 1000.0
    t_max_kn = values["omegaHardening"] * py_kn
    c_max_kn = values["omegaHardening"] * values["betaComp"] * py_kn
    rows = [
        {"yieldForceKn": py_kn, "adjustedTensionKn": t_max_kn, "adjustedCompressionKn": c_max_kn}
    ]
    return result(
        summary={"yieldForceKn": py_kn, "maxTensionKn": t_max_kn, "maxCompressionKn": c_max_kn},
        tables=[
            table(
                "Buckling-restrained brace (BRB) capacity-design forces",
                [
                    ("yieldForceKn", "Pysc", "kN"),
                    ("adjustedTensionKn", "ω·Pysc", "kN"),
                    ("adjustedCompressionKn", "ω·β·Pysc", "kN"),
                ],
                rows,
            )
        ],
        notes=["Gussets, beams, and columns framing into a BRB must resist ω·β·Pysc elastically."],
    )


@feature(
    "femDesignSeismicDetailing.yieldingSteel",
    "Yielding Steel",
    part="fem",
    fields=[
        number("plateThicknessMm", "Yielding fuse plate thickness", 16.0, unit="mm", min=4.0),
        number("fuseWidthMm", "Reduced fuse width", 180.0, unit="mm", min=30.0),
        number("fuseFyMpa", "Low-yield steel fy", 235.0, unit="MPa", min=100.0),
        number("overstrengthOmega", "Material overstrength Ωm", 1.25, min=1.0),
    ],
    requires_project=False,
)
def yielding_steel(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size metallic yielding shear/flexural fuse plates and capacity-protected connection demands."""
    v_yield_kn = (
        0.60 * values["fuseFyMpa"] * values["plateThicknessMm"] * values["fuseWidthMm"] / 1000.0
    )
    v_cap_kn = values["overstrengthOmega"] * v_yield_kn
    rows = [{"nominalYieldShearKn": v_yield_kn, "capacityDesignDemandKn": v_cap_kn}]
    return result(
        summary={"nominalYieldKn": v_yield_kn, "capacityProtectedDemandKn": v_cap_kn},
        tables=[
            table(
                "Metallic yielding energy dissipator forces",
                [("nominalYieldShearKn", "Vy", "kN"), ("capacityDesignDemandKn", "Ω·Vy", "kN")],
                rows,
            )
        ],
        notes=[
            "Fuse plate yields stably in shear/flexure while bolted end connections stay elastic."
        ],
    )

"""CFD Wind - Domain & Mesh tab (`femCfd`): fluid domain sizing, blockage, ABL inlet/outlet, y+, and setup."""

from __future__ import annotations

import math
from typing import Any

from saengine.features import (
    FeatureContext,
    feature,
    number,
    result,
    select,
    table,
)
from saengine.features.fem_common import (
    building_height_m,
    building_plan_dims_m,
    load_settings,
    optional_osmodel,
)
from saengine.fem.cfd_wind import case as cfd_case
from saengine.fem.cfd_wind import service as cfd_service


def _domain_dims(
    ctx: FeatureContext, up_h: float, down_h: float, side_h: float, top_h: float
) -> tuple[float, float, float, float, float, float]:
    _, osmodel = optional_osmodel(ctx)
    h = building_height_m(None, osmodel, fallback=15.0)
    bx, by = building_plan_dims_m(None, osmodel, fallback=(18.0, 12.0))
    lx = bx + (up_h + down_h) * h
    ly = by + 2.0 * side_h * h
    lz = h * (1.0 + top_h)
    return h, bx, by, lx, ly, lz


@feature(
    "femCfd.fluidDomain",
    "Fluid Domain",
    part="fem",
    fields=[
        number("upstreamH", "Upstream fetch (× H)", cfd_case.UPSTREAM, min=2.0, max=15.0),
        number("downstreamH", "Downstream wake (× H)", cfd_case.DOWNSTREAM, min=5.0, max=30.0),
        number("sidesH", "Lateral clearance (× H)", cfd_case.SIDES, min=2.0, max=15.0),
        number("aboveH", "Top clearance above roof (× H)", cfd_case.ABOVE, min=2.0, max=15.0),
    ],
    requires_project=False,
)
def fluid_domain(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute wind-tunnel computational fluid domain bounds around the building envelope."""
    h, bx, by, lx, ly, lz = _domain_dims(
        ctx, values["upstreamH"], values["downstreamH"], values["sidesH"], values["aboveH"]
    )
    b_min = [-values["upstreamH"] * h, -(by / 2.0 + values["sidesH"] * h), 0.0]
    b_max = [bx + values["downstreamH"] * h, by / 2.0 + values["sidesH"] * h, lz]
    rows = [
        {"axis": "X (Streamwise)", "minM": b_min[0], "maxM": b_max[0], "spanM": lx},
        {"axis": "Y (Spanwise)", "minM": b_min[1], "maxM": b_max[1], "spanM": ly},
        {"axis": "Z (Vertical)", "minM": b_min[2], "maxM": b_max[2], "spanM": lz},
    ]
    return result(
        summary={
            "buildingHeightM": h,
            "lengthM": lx,
            "widthM": ly,
            "heightM": lz,
            "volumeM3": lx * ly * lz,
        },
        tables=[
            table(
                "CFD virtual wind-tunnel domain",
                [
                    ("axis", "Axis"),
                    ("minM", "Min", "m"),
                    ("maxM", "Max", "m"),
                    ("spanM", "Extent", "m"),
                ],
                rows,
            )
        ],
        notes=["Domain proportions follow best-practice urban CFD tunnel clearances."],
    )


@feature(
    "femCfd.domainSize",
    "Domain Size",
    part="fem",
    fields=[
        number("buildingHeightM", "Reference building height H", 24.0, unit="m", min=2.0),
        number("planWidthM", "Cross-wind building width W", 18.0, unit="m", min=2.0),
        number("planDepthM", "Along-wind building depth D", 14.0, unit="m", min=2.0),
    ],
    requires_project=False,
)
def domain_size(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Recommend wind-tunnel box dimensions using multiples of reference height H."""
    h = values["buildingHeightM"]
    lx = values["planDepthM"] + (cfd_case.UPSTREAM + cfd_case.DOWNSTREAM) * h
    ly = values["planWidthM"] + 2.0 * cfd_case.SIDES * h
    lz = (1.0 + cfd_case.ABOVE) * h
    rows = [
        {"parameter": "Streamwise length Lx", "valueM": lx, "multipleH": lx / h},
        {"parameter": "Lateral width Ly", "valueM": ly, "multipleH": ly / h},
        {"parameter": "Vertical height Lz", "valueM": lz, "multipleH": lz / h},
    ]
    return result(
        summary={"lengthM": lx, "widthM": ly, "heightM": lz, "tunnelVolumeM3": lx * ly * lz},
        tables=[
            table(
                "Recommended wind-tunnel dimensions",
                [("parameter", "Dimension"), ("valueM", "Size", "m"), ("multipleH", "Ratio (/H)")],
                rows,
            )
        ],
        notes=["Uses default clearances 5H upstream, 15H downstream, 5H sides, and 5H above roof."],
    )


@feature(
    "femCfd.blockageCheck",
    "Blockage Check",
    part="fem",
    fields=[
        number("projectedWidthM", "Building frontal width", 18.0, unit="m", min=1.0),
        number("buildingHeightM", "Building height H", 24.0, unit="m", min=1.0),
        number("domainWidthM", "Tunnel cross-width Ly", 258.0, unit="m", min=10.0),
        number("domainHeightM", "Tunnel height Lz", 144.0, unit="m", min=10.0),
        number("maxBlockagePct", "Allowable blockage limit", 3.0, unit="%", min=0.5, max=10.0),
    ],
    requires_project=False,
)
def blockage_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check wind-tunnel blockage ratio A_building / A_tunnel against maximum threshold."""
    a_bld = values["projectedWidthM"] * values["buildingHeightM"]
    a_dom = values["domainWidthM"] * values["domainHeightM"]
    ratio_pct = 100.0 * a_bld / a_dom
    ok = ratio_pct <= values["maxBlockagePct"]
    rows = [
        {
            "buildingAreaM2": a_bld,
            "tunnelAreaM2": a_dom,
            "blockagePct": ratio_pct,
            "limitPct": values["maxBlockagePct"],
            "ok": ok,
        }
    ]
    return result(
        summary={
            "blockagePercent": ratio_pct,
            "limitPercent": values["maxBlockagePct"],
            "passes": ok,
        },
        tables=[
            table(
                "CFD tunnel blockage ratio check",
                [
                    ("buildingAreaM2", "A_bld", "m²"),
                    ("tunnelAreaM2", "A_dom", "m²"),
                    ("blockagePct", "BR", "%"),
                    ("limitPct", "Limit", "%"),
                    ("ok", "OK"),
                ],
                rows,
            )
        ],
        notes=["Blockage <= 3% prevents artificial flow acceleration around building corners."],
    )


@feature(
    "femCfd.cfdMesh",
    "CFD Mesh",
    part="fem",
    fields=[
        number("baseCellM", "Background far-field cell size", 4.0, unit="m", min=0.5),
        number("surfaceLevel", "Building surface refinement level", 3.0, min=0.0, max=6.0),
        number("domainVolumeM3", "Total fluid volume", 5.0e6, unit="m³", min=1.0e3),
    ],
    requires_project=False,
)
def cfd_mesh(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate background hexahedral grid resolution and refined surface cell size."""
    dx_bg = values["baseCellM"]
    dx_surf = dx_bg / (2.0 ** round(values["surfaceLevel"]))
    bg_cells = values["domainVolumeM3"] / (dx_bg**3)
    est_total = bg_cells * (1.0 + 0.35 * round(values["surfaceLevel"]))
    rows = [
        {"backgroundCellM": dx_bg, "surfaceCellM": dx_surf, "estCellsMillions": est_total / 1e6}
    ]
    return result(
        summary={"surfaceCellSizeM": dx_surf, "estimatedCells": int(est_total)},
        tables=[
            table(
                "CFD snappyHexMesh sizing estimate",
                [
                    ("backgroundCellM", "Base Δx", "m"),
                    ("surfaceCellM", "Surface Δx", "m"),
                    ("estCellsMillions", "Total cells (M)"),
                ],
                rows,
            )
        ],
        notes=["Each octave level halves cell edge length and multiplies local density by 8."],
    )


@feature(
    "femCfd.boundaryLayers",
    "Boundary Layers",
    part="fem",
    fields=[
        number("firstLayerMm", "First prism layer thickness Δy1", 2.5, unit="mm", min=0.05),
        number("expansionRatio", "Layer growth ratio", 1.2, min=1.05, max=1.5),
        number("nLayers", "Number of prism layers", 8.0, min=1.0, max=25.0),
    ],
    requires_project=False,
)
def boundary_layers(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate total prism boundary-layer height and outer-to-first layer thickness ratio."""
    n = max(1, round(values["nLayers"]))
    r = values["expansionRatio"]
    y1 = values["firstLayerMm"]
    final_mm = y1 * (r ** (n - 1))
    total_mm = y1 * (r**n - 1.0) / (r - 1.0)
    rows = [
        {"nLayers": n, "firstLayerMm": y1, "finalLayerMm": final_mm, "totalThicknessMm": total_mm}
    ]
    return result(
        summary={"layers": n, "finalLayerMm": final_mm, "totalThicknessMm": total_mm},
        tables=[
            table(
                "Surface prism boundary-layer stack",
                [
                    ("nLayers", "Layers"),
                    ("firstLayerMm", "Δy1", "mm"),
                    ("finalLayerMm", "Δyn", "mm"),
                    ("totalThicknessMm", "H_total", "mm"),
                ],
                rows,
            )
        ],
        notes=["Ensure total prism height spans the viscous + buffer wall regions."],
    )


@feature(
    "femCfd.refinementZones",
    "Refinement Zones",
    part="fem",
    fields=[
        number("baseCellM", "Base cell size", 4.0, unit="m", min=0.5),
        number("nearWakeLevel", "Near-wake box refinement level", 2.0, min=1.0, max=5.0),
        number("roofEdgeLevel", "Roof-edge / corner level", 4.0, min=1.0, max=6.0),
        number("buildingHeightM", "Building height H", 24.0, unit="m", min=2.0),
    ],
    requires_project=False,
)
def refinement_zones(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define nested near-body and wake volumetric mesh refinement regions."""
    h = values["buildingHeightM"]
    rows = [
        {
            "zone": "Far Wake",
            "xExtentM": 6.0 * h,
            "level": max(1, int(values["nearWakeLevel"]) - 1),
            "cellM": values["baseCellM"] / (2 ** max(1, int(values["nearWakeLevel"]) - 1)),
        },
        {
            "zone": "Near Wake",
            "xExtentM": 2.5 * h,
            "level": int(values["nearWakeLevel"]),
            "cellM": values["baseCellM"] / (2 ** int(values["nearWakeLevel"])),
        },
        {
            "zone": "Roof / Corner Shear",
            "xExtentM": 0.4 * h,
            "level": int(values["roofEdgeLevel"]),
            "cellM": values["baseCellM"] / (2 ** int(values["roofEdgeLevel"])),
        },
    ]
    return result(
        summary={"zones": len(rows), "finestCellM": rows[-1]["cellM"]},
        tables=[
            table(
                "Volumetric mesh refinement boxes",
                [
                    ("zone", "Region"),
                    ("xExtentM", "Downstream Reach", "m"),
                    ("level", "Level"),
                    ("cellM", "Cell Size", "m"),
                ],
                rows,
            )
        ],
        notes=["Nested boxes capture separated shear layers from sharp building corners."],
    )


@feature(
    "femCfd.inletProfile",
    "Inlet Profile",
    part="fem",
    fields=[
        number("z0M", "Aerodynamic roughness length z0", 0.3, unit="m", min=0.001, max=3.0),
        number("zRefM", "Reference height H_ref", 10.0, unit="m", min=1.0),
        number("uRefMs", "Reference wind speed U_ref", cfd_case.UREF, unit="m/s", min=1.0),
    ],
    requires_project=False,
)
def inlet_profile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate Richards-Hoxey atmospheric boundary-layer log-law U, k, and ε profiles."""
    z0 = values["z0M"]
    bl = cfd_case.boundary_layer(z0, values["zRefM"], uref=values["uRefMs"])
    ustar = bl["ustar"]
    rows = []
    for z in [2.0, 5.0, 10.0, 20.0, 40.0, 80.0, 150.0]:
        u_z = (ustar / cfd_case.KAPPA) * math.log((z + z0) / z0)
        eps_z = (ustar**3) / (cfd_case.KAPPA * (z + z0))
        rows.append({"heightM": z, "speedMs": u_z, "tkeM2s2": bl["k"], "epsM2s3": eps_z})
    return result(
        summary={"ustarMs": ustar, "kM2s2": bl["k"], "epsilonAtHrefM2s3": bl["epsilon"]},
        tables=[
            table(
                "ABL inlet log-law profile",
                [
                    ("heightM", "z", "m"),
                    ("speedMs", "U(z)", "m/s"),
                    ("tkeM2s2", "k", "m²/s²"),
                    ("epsM2s3", "ε(z)", "m²/s³"),
                ],
                rows,
            )
        ],
        notes=["Consistent log-law ABL formulation via saengine.fem.cfd_wind.case.boundary_layer."],
    )


@feature(
    "femCfd.outlet",
    "Outlet Boundary",
    part="fem",
    fields=[
        number("gaugePressurePa", "Outlet static gauge pressure", 0.0, unit="Pa"),
        number("downstreamDistM", "Building-to-outlet distance", 360.0, unit="m", min=20.0),
        number("buildingHeightM", "Building height H", 24.0, unit="m", min=2.0),
    ],
    requires_project=False,
)
def outlet(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure zero-static-pressure outflow condition with backflow guard distance check."""
    ratio_h = values["downstreamDistM"] / values["buildingHeightM"]
    adequate = ratio_h >= 12.0
    rows = [
        {
            "patch": "outlet",
            "type": "inletOutlet / fixedValue p=0",
            "distanceOverH": ratio_h,
            "adequateWakeRecovery": adequate,
        }
    ]
    return result(
        summary={
            "downstreamH": ratio_h,
            "adequate": adequate,
            "outletPressurePa": values["gaugePressurePa"],
        },
        tables=[
            table(
                "Outlet boundary check",
                [
                    ("patch", "Patch"),
                    ("type", "BC Type"),
                    ("distanceOverH", "Dist/H"),
                    ("adequateWakeRecovery", "No Backflow Risk"),
                ],
                rows,
            )
        ],
        notes=["Minimum 10H–15H downstream fetch avoids pressure boundary contamination."],
    )


@feature(
    "femCfd.roughness",
    "Surface Roughness",
    part="fem",
    fields=[
        select(
            "terrain",
            "Terrain exposure class",
            [
                ("open", "Open flat (z0 = 0.03 m)"),
                ("suburban", "Suburban (z0 = 0.30 m)"),
                ("urban", "Dense urban (z0 = 1.00 m)"),
            ],
            "suburban",
        ),
        number("cs", "Nikuradse roughness constant Cs", 0.5, min=0.1, max=1.0),
    ],
    requires_project=False,
)
def roughness(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert aerodynamic roughness length z0 to sand-grain roughness ks for wall functions."""
    z0_map = {"open": 0.03, "suburban": 0.30, "urban": 1.00}
    z0 = z0_map[values["terrain"]]
    if ctx.root is not None:
        z0, src = cfd_service.roughness(load_settings(ctx))
    else:
        src = values["terrain"]
    ks = (9.793 * z0) / values["cs"]
    rows = [{"source": src, "z0M": z0, "cs": values["cs"], "ksM": ks}]
    return result(
        summary={"z0M": z0, "sandGrainKsM": ks, "cs": values["cs"]},
        tables=[
            table(
                "Ground wall roughness mapping ks = 9.793 z0 / Cs",
                [("source", "Exposure"), ("z0M", "z0", "m"), ("cs", "Cs"), ("ksM", "ks", "m")],
                rows,
            )
        ],
        notes=["Ensure ground first-cell centre zp > ks to maintain log-law validity."],
    )


@feature(
    "femCfd.turbulenceModel",
    "Turbulence Model",
    part="fem",
    fields=[
        select(
            "closure",
            "RANS / Hybrid closure",
            [
                ("kOmegaSST", "k-ω SST (bluff-body recommended)"),
                ("realizableKE", "Realizable k-ε"),
                ("rngKE", "RNG k-ε"),
                ("lesWale", "LES WALE"),
            ],
            "kOmegaSST",
        ),
    ],
    requires_project=False,
)
def turbulence_model(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select bluff-body aerodynamic turbulence closure model and model constants."""
    table_map = {
        "kOmegaSST": ("Menter SST", 0.09, "High adverse-pressure separation accuracy"),
        "realizableKE": ("Realizable k-ε", 0.09, "Moderate separation, robust convergence"),
        "rngKE": ("RNG k-ε", 0.0845, "Swirl/vortex shedding enhancement"),
        "lesWale": ("LES WALE", 0.325, "Transient peak pressure time history"),
    }
    name, c_val, strength = table_map[values["closure"]]
    rows = [{"model": name, "primaryConstant": c_val, "suitability": strength}]
    return result(
        summary={"closure": values["closure"], "constant": c_val},
        tables=[
            table(
                "Selected turbulence closure",
                [
                    ("model", "Model"),
                    ("primaryConstant", "Cμ / Cw"),
                    ("suitability", "Application"),
                ],
                rows,
            )
        ],
        notes=["k-ω SST avoids stagnation-point excessive kinetic energy distortion."],
    )


@feature(
    "femCfd.wallTreatment",
    "Wall Treatment",
    part="fem",
    fields=[
        number("yPlus", "Estimated wall y+", 45.0, min=0.2, max=1000.0),
    ],
    requires_project=False,
)
def wall_treatment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Recommend near-wall modeling strategy (low-Re resolved vs log-law wall function)."""
    yp = values["yPlus"]
    if yp < 5.0:
        regime, wf = "Viscous sublayer", "Low-Re resolved (no wall function)"
    elif yp <= 30.0:
        regime, wf = "Buffer layer (avoid)", "Automatic blended wall treatment"
    elif yp <= 300.0:
        regime, wf = "Log-law region", "Standard kqRWallFunction / nutkWallFunction"
    else:
        regime, wf = "Outer defect layer (coarse)", "Refine near-wall prism thickness"
    rows = [{"yPlus": yp, "layerRegime": regime, "recommendedCondition": wf}]
    return result(
        summary={"yPlus": yp, "regime": regime},
        tables=[
            table(
                "Near-wall treatment selection",
                [
                    ("yPlus", "y+"),
                    ("layerRegime", "Regime"),
                    ("recommendedCondition", "Recommended BC"),
                ],
                rows,
            )
        ],
        notes=["Target y+ in 30–150 for wall functions or y+ <= 1 for resolved boundary layers."],
    )


@feature(
    "femCfd.yPlusCheck",
    "y+ Check",
    part="fem",
    fields=[
        number("uRefMs", "Reference wind speed U_ref", 25.0, unit="m/s", min=1.0),
        number("charLengthM", "Characteristic wall length L", 24.0, unit="m", min=1.0),
        number("firstCellMm", "First-cell height Δy", 4.0, unit="mm", min=0.01),
    ],
    requires_project=False,
)
def y_plus_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate boundary-layer skin friction Re_L and wall y+ for first prism cell."""
    re_l = values["uRefMs"] * values["charLengthM"] / cfd_case.NU
    cf = 0.058 * (re_l**-0.2)
    tau_w = 0.5 * 1.225 * (values["uRefMs"] ** 2) * cf
    u_tau = math.sqrt(tau_w / 1.225)
    yp_center = (0.5 * values["firstCellMm"] / 1000.0) * u_tau / cfd_case.NU
    rows = [{"reynolds": re_l, "uTauMs": u_tau, "yPlusCenter": yp_center}]
    return result(
        summary={"reynoldsNumber": re_l, "uTauMs": u_tau, "yPlus": yp_center},
        tables=[
            table(
                "First-cell y+ estimation",
                [("reynolds", "Re_L"), ("uTauMs", "uτ", "m/s"), ("yPlusCenter", "y+")],
                rows,
            )
        ],
        notes=["Computed with kinematic air viscosity ν = 1.5e-5 m²/s."],
    )


@feature(
    "femCfd.convergenceCriteria",
    "Convergence Criteria",
    part="fem",
    fields=[
        number("residualTarget", "Normalized equation residual target", 1e-4, min=1e-8, max=1e-2),
        number(
            "forceDeltaPct", "Drag/lift window drift tolerance", 0.5, unit="%", min=0.05, max=5.0
        ),
    ],
    requires_project=False,
)
def convergence_criteria(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define dual residual and integrated aerodynamic force stability stopping thresholds."""
    rows = [
        {
            "criterion": "Continuity / Momentum residuals",
            "target": f"< {values['residualTarget']:.1e}",
        },
        {
            "criterion": "Integrated base force drift (last 200 iter)",
            "target": f"< {values['forceDeltaPct']:.2f}%",
        },
    ]
    return result(
        summary={
            "residualTarget": values["residualTarget"],
            "forceDriftPct": values["forceDeltaPct"],
        },
        tables=[
            table(
                "CFD steady convergence criteria",
                [("criterion", "Criterion"), ("target", "Stopping Target")],
                rows,
            )
        ],
        notes=["Force coefficient plateau is more reliable than residuals alone for bluff bodies."],
    )


@feature(
    "femCfd.relaxationFactors",
    "Relaxation Factors",
    part="fem",
    fields=[
        number("pRelax", "Pressure under-relaxation α_p", 0.3, min=0.05, max=0.9),
        number("uRelax", "Velocity under-relaxation α_U", 0.7, min=0.1, max=0.95),
        number("turbRelax", "Turbulence k/ω relaxation", 0.5, min=0.1, max=0.95),
    ],
    requires_project=False,
)
def relaxation_factors(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate SIMPLE pressure-velocity under-relaxation rule α_p + α_U ≈ 1.0."""
    sum_pu = values["pRelax"] + values["uRelax"]
    rows = [
        {
            "alphaP": values["pRelax"],
            "alphaU": values["uRelax"],
            "alphaTurb": values["turbRelax"],
            "sumPU": sum_pu,
        }
    ]
    return result(
        summary={"pRelax": values["pRelax"], "uRelax": values["uRelax"], "sumPU": sum_pu},
        tables=[
            table(
                "SIMPLE relaxation setup",
                [
                    ("alphaP", "α_p"),
                    ("alphaU", "α_U"),
                    ("alphaTurb", "α_k/ω"),
                    ("sumPU", "α_p + α_U"),
                ],
                rows,
            )
        ],
        notes=["Keeping α_p + α_U <= 1.0 helps maintain pressure-velocity stability."],
    )


@feature(
    "femCfd.solverIterations",
    "Solver Iterations",
    part="fem",
    fields=[
        number("maxIter", "Maximum outer steady iterations", 2000.0, min=100.0, max=20000.0),
        number("writeInterval", "Result checkpoint write interval", 500.0, min=10.0),
        number("averageWindow", "Averaging window (last iterations)", 400.0, min=50.0),
    ],
    requires_project=False,
)
def solver_iterations(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure maximum steady-state iteration budget and tail-averaging window."""
    m = round(values["maxIter"])
    w = round(values["writeInterval"])
    rows = [
        {
            "maxIter": m,
            "writeInterval": w,
            "checkpoints": max(1, m // w),
            "averagingSpan": round(values["averageWindow"]),
        }
    ]
    return result(
        summary={
            "maxIter": m,
            "checkpoints": max(1, m // w),
            "averageWindow": round(values["averageWindow"]),
        },
        tables=[
            table(
                "Iteration & averaging schedule",
                [
                    ("maxIter", "Max Iter"),
                    ("writeInterval", "Write Every"),
                    ("checkpoints", "Saves"),
                    ("averagingSpan", "Avg Window"),
                ],
                rows,
            )
        ],
        notes=["Ensemble average pressure coefficients over the final vortex-shedding cycles."],
    )


@feature(
    "femCfd.timeStepping",
    "Time Stepping",
    part="fem",
    fields=[
        number("cellSizeM", "Minimum wake cell size Δx", 0.5, unit="m", min=0.05),
        number("windSpeedMs", "Peak convective speed U", 35.0, unit="m/s", min=1.0),
        number("targetCfl", "Target Courant number Co", 0.8, min=0.1, max=5.0),
        number("durationS", "Physical simulation duration", 120.0, unit="s", min=1.0),
    ],
    requires_project=False,
)
def time_stepping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute transient CFD time step Δt from target Courant number and minimum cell size."""
    dt = values["targetCfl"] * values["cellSizeM"] / values["windSpeedMs"]
    steps = math.ceil(values["durationS"] / dt)
    rows = [
        {
            "dtS": dt,
            "targetCfl": values["targetCfl"],
            "totalSteps": steps,
            "simDurationS": values["durationS"],
        }
    ]
    return result(
        summary={"timeStepS": dt, "totalSteps": steps},
        tables=[
            table(
                "Transient time-step sizing",
                [
                    ("dtS", "Δt", "s"),
                    ("targetCfl", "Co_target"),
                    ("totalSteps", "Steps"),
                    ("simDurationS", "T_sim", "s"),
                ],
                rows,
            )
        ],
        notes=["Maintain Co <= 1.0 in shear-layer regions for accurate peak pressure time series."],
    )


@feature(
    "femCfd.parallelCores",
    "Parallel Cores",
    part="fem",
    fields=[
        number("totalCellsM", "Mesh cell count (millions)", 3.2, min=0.1),
        number("cores", "MPI processes / CPU cores", 16.0, min=1.0, max=512.0),
    ],
    requires_project=False,
)
def parallel_cores(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate MPI domain decomposition efficiency in cells per core."""
    n_cores = round(values["cores"])
    cells_per_core = (values["totalCellsM"] * 1e6) / n_cores
    balanced = 25000.0 <= cells_per_core <= 250000.0
    rows = [{"cores": n_cores, "cellsPerCore": int(cells_per_core), "sweetSpot": balanced}]
    return result(
        summary={"cores": n_cores, "cellsPerCore": int(cells_per_core), "inSweetSpot": balanced},
        tables=[
            table(
                "MPI parallel decomposition balance",
                [("cores", "Cores"), ("cellsPerCore", "Cells/Core"), ("sweetSpot", "Optimal Load")],
                rows,
            )
        ],
        notes=["Ideal MPI scalability occurs near 40k–150k cells per core."],
    )


@feature(
    "femCfd.initialField",
    "Initial Field",
    part="fem",
    fields=[
        number("uRefMs", "Reference wind speed U_ref", cfd_case.UREF, unit="m/s", min=1.0),
        number("z0M", "Roughness length z0", 0.3, unit="m", min=0.001),
        number("heightM", "Reference height H_ref", 10.0, unit="m", min=1.0),
    ],
    requires_project=False,
)
def initial_field(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Initialize internal domain U, k, and ε using potential-flow + ABL baseline."""
    bl = cfd_case.boundary_layer(values["z0M"], values["heightM"], uref=values["uRefMs"])
    rows = [{"field": k, "initialValue": v} for k, v in bl.items()]
    return result(
        summary=bl,
        tables=[
            table(
                "Internal field initialization parameters",
                [("field", "Variable"), ("initialValue", "Baseline Value")],
                rows,
            )
        ],
        notes=["Pre-initializing with potentialFoam prevents early divergence on bluff corners."],
    )


@feature(
    "femCfd.resultSampling",
    "Result Sampling",
    part="fem",
    fields=[
        number("nDirections", "Number of wind azimuths", 16.0, min=1.0, max=36.0),
        number("buildingHeightM", "Building height H", 24.0, unit="m", min=2.0),
        number("probesPerTier", "Facade surface pressure probes per level", 24.0, min=4.0),
    ],
    requires_project=False,
)
def result_sampling(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure facade pressure tap arrays and wind-direction sector spacing."""
    ndir = round(values["nDirections"])
    tiers = max(3, round(values["buildingHeightM"] / 4.0))
    total_taps = tiers * round(values["probesPerTier"])
    rows = [
        {
            "directions": ndir,
            "stepDeg": 360.0 / ndir,
            "elevationTiers": tiers,
            "totalTaps": total_taps,
        }
    ]
    return result(
        summary={"directions": ndir, "elevationTiers": tiers, "totalTaps": total_taps},
        tables=[
            table(
                "Surface pressure sampling plan",
                [
                    ("directions", "Dirs"),
                    ("stepDeg", "Step", "°"),
                    ("elevationTiers", "Levels"),
                    ("totalTaps", "Taps"),
                ],
                rows,
            )
        ],
        notes=["Matches surface patch sampling expected by saengine.fem.cfd_wind.post.evaluate."],
    )


@feature(
    "femCfd.profileExponent",
    "Profile Exponent",
    part="fem",
    fields=[
        number("z0M", "Roughness length z0", 0.3, unit="m", min=0.001, max=3.0),
        number("zGradientM", "Gradient height zg", 300.0, unit="m", min=150.0, max=600.0),
    ],
    requires_project=False,
)
def profile_exponent(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Relate logarithmic roughness length z0 to power-law wind profile exponent α."""
    z0 = values["z0M"]
    alpha = 0.24 + 0.096 * math.log10(z0) + 0.016 * (math.log10(z0) ** 2)
    alpha = max(0.08, min(0.45, alpha))
    rows = [{"z0M": z0, "powerLawAlpha": alpha, "gradientHeightM": values["zGradientM"]}]
    return result(
        summary={"z0M": z0, "powerLawAlpha": alpha},
        tables=[
            table(
                "ABL log-to-power-law exponent conversion",
                [
                    ("z0M", "z0", "m"),
                    ("powerLawAlpha", "Exponent α"),
                    ("gradientHeightM", "zg", "m"),
                ],
                rows,
            )
        ],
        notes=["Empirical Counihan correlation α ≈ 0.24 + 0.096 log10(z0) + 0.016 [log10(z0)]²."],
    )


@feature(
    "femCfd.referenceHeight",
    "Reference Height",
    part="fem",
    fields=[
        number("roofHeightM", "Mean roof / top height H_ref", 24.0, unit="m", min=2.0),
        number("z0M", "Roughness length z0", 0.3, unit="m", min=0.001),
        number("u10Ms", "10 m meteorological speed U10", 30.0, unit="m/s", min=1.0),
    ],
    requires_project=False,
)
def reference_height(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute reference wind speed and dynamic velocity pressure q_ref at building roof height."""
    bl10 = cfd_case.boundary_layer(values["z0M"], 10.0, uref=values["u10Ms"])
    u_href = (bl10["ustar"] / cfd_case.KAPPA) * math.log(
        (values["roofHeightM"] + values["z0M"]) / values["z0M"]
    )
    q_ref = 0.5 * 1.225 * (u_href**2) / 1000.0
    rows = [{"heightM": values["roofHeightM"], "uRefMs": u_href, "qRefKpa": q_ref}]
    return result(
        summary={"heightM": values["roofHeightM"], "uRefMs": u_href, "qRefKpa": q_ref},
        tables=[
            table(
                "Reference height speed & pressure",
                [
                    ("heightM", "z_ref", "m"),
                    ("uRefMs", "U_ref", "m/s"),
                    ("qRefKpa", "q_ref", "kPa"),
                ],
                rows,
            )
        ],
        notes=["Cp coefficients normalize wall pressure by dynamic pressure q_ref at H_ref."],
    )


@feature(
    "femCfd.gustSpectrum",
    "Gust Spectrum",
    part="fem",
    fields=[
        number("meanSpeedMs", "Mean wind speed U(z)", 28.0, unit="m/s", min=1.0),
        number("integralScaleM", "Integral turbulence length Lu", 120.0, unit="m", min=5.0),
        number("sigmaUMs", "Longitudinal RMS velocity σ_u", 4.5, unit="m/s", min=0.1),
    ],
    requires_project=False,
)
def gust_spectrum(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate von Karman longitudinal wind turbulence power spectral density across frequencies."""
    u = values["meanSpeedMs"]
    lu = values["integralScaleM"]
    var_u = values["sigmaUMs"] ** 2
    rows = []
    for f in [0.02, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0]:
        f_nd = f * lu / u
        psd = (4.0 * var_u * (lu / u)) / ((1.0 + 70.78 * (f_nd**2)) ** (5.0 / 6.0))
        rows.append({"freqHz": f, "reducedFreq": f_nd, "psdM2s": psd})
    return result(
        summary={"peakPsdM2s": rows[0]["psdM2s"], "varianceM2s2": var_u},
        tables=[
            table(
                "von Karman longitudinal gust PSD",
                [("freqHz", "f", "Hz"), ("reducedFreq", "f·Lu/U"), ("psdM2s", "Su(f)", "m²/s")],
                rows,
            )
        ],
        notes=["Used to synthesize unsteady LES inflow boundary fluctuations."],
    )


@feature(
    "femCfd.incidentTurbulence",
    "Incident Turbulence",
    part="fem",
    fields=[
        number("heightM", "Target height z", 20.0, unit="m", min=1.0),
        number("z0M", "Roughness length z0", 0.3, unit="m", min=0.001),
        number("uRefMs", "Reference wind speed U_ref", 25.0, unit="m/s", min=1.0),
    ],
    requires_project=False,
)
def incident_turbulence(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate incident atmospheric turbulence intensity Iu(z) and integral length scale."""
    iu = min(0.45, 1.0 / math.log(max(2.0, values["heightM"] / values["z0M"])))
    bl = cfd_case.boundary_layer(values["z0M"], values["heightM"], uref=values["uRefMs"])
    lu = 300.0 * ((values["heightM"] / 200.0) ** (0.67 + 0.05 * math.log(values["z0M"])))
    rows = [
        {
            "heightM": values["heightM"],
            "turbulenceIntensity": iu,
            "tkeM2s2": bl["k"],
            "lengthScaleM": max(5.0, lu),
        }
    ]
    return result(
        summary={
            "turbulenceIntensityPct": 100.0 * iu,
            "tkeM2s2": bl["k"],
            "lengthScaleM": max(5.0, lu),
        },
        tables=[
            table(
                "Incident ABL turbulence profile",
                [
                    ("heightM", "z", "m"),
                    ("turbulenceIntensity", "Iu"),
                    ("tkeM2s2", "k", "m²/s²"),
                    ("lengthScaleM", "Lu", "m"),
                ],
                rows,
            )
        ],
        notes=["High incident turbulence accelerates shear-layer reattachment on side faces."],
    )


@feature(
    "femCfd.profileLibrary",
    "ABL Profile Library",
    part="fem",
    fields=[
        number("zRefM", "Reference height H_ref", 10.0, unit="m", min=1.0),
        number("uRefMs", "Reference speed U_ref", cfd_case.UREF, unit="m/s", min=1.0),
    ],
    requires_project=False,
)
def profile_library(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare standard aerodynamic roughness exposure library profiles at H_ref."""
    rows = []
    for name, z0 in [
        ("Sea / Mudflat", 0.005),
        ("Open Terrain", 0.03),
        ("Lightly Built", 0.15),
        ("Suburban", 0.30),
        ("Dense Urban", 1.00),
        ("City Center", 2.00),
    ]:
        bl = cfd_case.boundary_layer(z0, values["zRefM"], uref=values["uRefMs"])
        rows.append(
            {
                "exposure": name,
                "z0M": z0,
                "ustarMs": bl["ustar"],
                "kM2s2": bl["k"],
                "omega1s": bl["omega"],
            }
        )
    return result(
        summary={"profiles": len(rows), "referenceHeightM": values["zRefM"]},
        tables=[
            table(
                "Standard ABL roughness library",
                [
                    ("exposure", "Exposure"),
                    ("z0M", "z0", "m"),
                    ("ustarMs", "u*", "m/s"),
                    ("kM2s2", "k", "m²/s²"),
                    ("omega1s", "ω", "1/s"),
                ],
                rows,
            )
        ],
        notes=["Computed via saengine.fem.cfd_wind.case.boundary_layer."],
    )

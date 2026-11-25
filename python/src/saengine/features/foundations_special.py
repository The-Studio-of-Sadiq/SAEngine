"""Substructure - Special Foundations tab: slabs on grade, fibre slabs, machine dynamics & anchor bolts."""

from __future__ import annotations

import math
from typing import Any

from saengine.design import anchors
from saengine.design.bars import diameters, mesh_for, slab_flexure_need
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
from saengine.features.foundations_common import build_profile
from saengine.library.objects import AnchorConcrete
from saengine.report.clauses import in_force
from saengine.soil import bearing as soil_bearing
from saengine.substructure import ground_slab, machine, shallow


@feature(
    "foundationsSpecial.slabReinforcement",
    "Slab Reinforcement",
    part="substructure",
    fields=[
        number("thicknessMm", "Slab thickness h", 180.0, unit="mm", min=100.0),
        number("fyMpa", "Rebar yield strength fy", 420.0, unit="MPa", min=250.0),
        number("fcMpa", "Concrete f'c", 25.0, unit="MPa", min=15.0),
        number(
            "edgeMomentKnmPerM",
            "Design flexural moment (0 = crack-control only)",
            0.0,
            unit="kN·m/m",
            min=0.0,
        ),
        number("coverMm", "Clear cover", 40.0, unit="mm", min=20.0),
    ],
    requires_project=False,
)
def slab_reinforcement(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Design temperature/shrinkage mesh and flexural steel for a ground-bearing slab."""
    h, fy, fc = values["thicknessMm"], values["fyMpa"], values["fcMpa"]
    d_mm = h - values["coverMm"] - 6.0
    if d_mm <= 30.0:
        raise FeatureInputError("Slab thickness is too small for the cover.")
    with in_force(ctx.root):
        ratio = ground_slab.SHRINKAGE_RATIO * (420.0 / fy if fy > 420.0 else 1.0)
        as_shrink = ratio * 1000.0 * h
        as_flex = (
            slab_flexure_need(values["edgeMomentKnmPerM"] * 1e6, d_mm, fc, fy).area
            if values["edgeMomentKnmPerM"] > 0
            else 0.0
        )
        req = max(as_shrink, as_flex)
        mesh = mesh_for(req, min(3.0 * h, 450.0), diameters("slab"))
        prov = (math.pi * mesh.dia**2 / 4.0 * 1000.0 / mesh.spacing) if mesh else 0.0
    return result(
        summary={
            "shrinkageRatio": ratio,
            "shrinkageSteelMm2PerM": as_shrink,
            "requiredSteelMm2PerM": req,
            "providedSteelMm2PerM": prov,
            "mesh": f"Ø{mesh.dia:g}@{mesh.spacing:g}" if mesh else "Increase thickness",
        },
        tables=[
            table(
                "Slab on grade reinforcement",
                [("criterion", "Criterion"), ("val", "Value"), ("unit", "Unit")],
                [
                    {
                        "criterion": "Crack-control steel (temperature & shrinkage)",
                        "val": as_shrink,
                        "unit": "mm²/m",
                    },
                    {"criterion": "Flexural demand steel", "val": as_flex, "unit": "mm²/m"},
                    {"criterion": "Governing required steel", "val": req, "unit": "mm²/m"},
                    {"criterion": "Selected mesh capacity", "val": prov, "unit": "mm²/m"},
                ],
            )
        ],
        notes=[
            "Place crack-control mesh in the upper third of the slab (35–50 mm below top surface)."
        ],
    )


@feature(
    "foundationsSpecial.jointLayout",
    "Joint Layout",
    part="substructure",
    fields=[
        number("slabLengthM", "Slab bay length L", 36.0, unit="m", min=2.0),
        number("slabWidthM", "Slab bay width B", 24.0, unit="m", min=2.0),
        number("thicknessMm", "Slab thickness h", 150.0, unit="mm", min=100.0),
        number("maxJointSpacingM", "Target saw-cut joint spacing", 4.5, unit="m", min=1.5),
        number("expansionJointM", "Isolation/expansion bay limit", 25.0, unit="m", min=6.0),
    ],
    requires_project=False,
)
def joint_layout(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Lay out saw-cut contraction and construction joint panels across a ground slab."""
    l_m, b_m = values["slabLengthM"], values["slabWidthM"]
    limit_m = (ground_slab.JOINT_SPACING * values["thicknessMm"]) / 1000.0
    s_target = min(values["maxJointSpacingM"], limit_m)
    nx = max(1, math.ceil(l_m / s_target))
    ny = max(1, math.ceil(b_m / s_target))
    sx = l_m / nx
    sy = b_m / ny
    aspect = max(sx, sy) / max(min(sx, sy), 1e-6)
    total_joint_m = (nx - 1) * b_m + (ny - 1) * l_m
    rows = [
        {"axis": "Longitudinal X", "panels": nx, "panelSizeM": sx, "jointLines": nx - 1},
        {"axis": "Transverse Y", "panels": ny, "panelSizeM": sy, "jointLines": ny - 1},
    ]
    return result(
        summary={
            "panelCount": nx * ny,
            "panelSpacingXM": sx,
            "panelSpacingYM": sy,
            "aspectRatio": aspect,
            "totalSawCutLengthM": total_joint_m,
            "aspectOk": aspect <= 1.5,
        },
        tables=[
            table(
                "Ground slab joint panel layout",
                [
                    ("axis", "Direction"),
                    ("panels", "Panels"),
                    ("panelSizeM", "Bay size", "m"),
                    ("jointLines", "Joint lines"),
                ],
                rows,
            )
        ],
        notes=[
            f"Maximum unreinforced spacing = 30 h = {limit_m:.2f} m. Saw-cut depth ≥ h/4 ({values['thicknessMm'] / 4:.0f} mm)."
        ],
    )


@feature(
    "foundationsSpecial.fibreSlab",
    "Fibre Slab",
    part="substructure",
    fields=[
        number("pointLoadKn", "Service concentrated point/wheel load P", 45.0, unit="kN", min=1.0),
        number("contactSideMm", "Contact plate/tyre width", 150.0, unit="mm", min=50.0),
        number("thicknessMm", "Slab thickness h", 180.0, unit="mm", min=100.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        number("re3Ratio", "Equivalent residual flexural ratio Re,3", 0.45, min=0.10, max=0.90),
        number("subgradeK", "Subgrade modulus k", 40000.0, unit="kN/m³", min=5000.0),
        number("fs", "Flexural factor of safety", 1.5, min=1.1, max=3.0),
    ],
    requires_project=False,
)
def fibre_slab(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Design a fibre-reinforced slab on grade using plastic yield-line and elastic Westergaard checks."""
    h, fc, k_kpa_m = values["thicknessMm"], values["fcMpa"], values["subgradeK"]
    ec = 4700.0 * math.sqrt(fc)
    with in_force(ctx.root):
        fr = ground_slab.modulus_of_rupture(fc)
        west = ground_slab.westergaard(
            values["pointLoadKn"] * 1e3, values["contactSideMm"], h, ec, 0.2, k_kpa_m * 1e-6
        )
        phi_vc_n, _b0 = ground_slab.plain_punching(values["contactSideMm"], h, fc)
        live_fac, _ = ground_slab.live_factor()
    l_rel = west["l"]
    a_eq = west["a"]
    # Yield-line plastic moment resistance: Mp = (fr * Re,3 + fr) / 6 * h^2 (Meyerhof plastic interior capacity)
    mn = (fr / values["fs"]) * (h**2) / 6.0  # N.mm/mm
    mp = values["re3Ratio"] * mn
    # Meyerhof interior yield-line ultimate load: Pu = 2 * pi * (mn + mp) / (1 - 2*a/(3*l))
    p_meyerhof_kn = 2.0 * math.pi * (mn + mp) / max(1.0 - (2.0 * a_eq) / (3.0 * l_rel), 0.25) / 1e3
    pu_punch = (live_fac or 1.6) * values["pointLoadKn"]
    return result(
        summary={
            "modulusOfRuptureMpa": fr,
            "relativeStiffnessMm": l_rel,
            "plasticCapacityKn": p_meyerhof_kn,
            "elasticEdgeStressMpa": west["edge"],
            "punchingDemandKn": pu_punch,
            "punchingCapacityKn": phi_vc_n / 1e3,
            "ok": p_meyerhof_kn >= values["pointLoadKn"] and pu_punch <= phi_vc_n / 1e3,
        },
        tables=[
            table(
                "Fibre-reinforced slab on grade check",
                [
                    ("item", "Check item"),
                    ("demand", "Demand"),
                    ("capacity", "Capacity"),
                    ("unit", "Unit"),
                ],
                [
                    {
                        "item": "Interior yield-line (Meyerhof)",
                        "demand": values["pointLoadKn"],
                        "capacity": p_meyerhof_kn,
                        "unit": "kN",
                    },
                    {
                        "item": "Punching shear around contact",
                        "demand": pu_punch,
                        "capacity": phi_vc_n / 1e3,
                        "unit": "kN",
                    },
                    {
                        "item": "Westergaard edge flexural stress",
                        "demand": west["edge"],
                        "capacity": fr / values["fs"],
                        "unit": "MPa",
                    },
                ],
            )
        ],
        notes=[
            f"Residual ratio Re,3 = {values['re3Ratio']:.2f}; radius of relative stiffness l = {l_rel:.0f} mm."
        ],
    )


@feature(
    "foundationsSpecial.dynamicLoads",
    "Dynamic Loads",
    part="substructure",
    fields=[
        number("rpm", "Operating speed", 1500.0, unit="RPM", min=60.0),
        number("rotorMassKg", "Rotating eccentric mass m_e", 120.0, unit="kg", min=1.0),
        number("eccentricityMm", "Mass eccentricity e", 0.25, unit="mm", min=0.01),
        number("machineWeightKn", "Total static machine weight", 85.0, unit="kN", min=1.0),
        number("blockWeightKn", "Concrete foundation block weight", 260.0, unit="kN", min=5.0),
    ],
    requires_project=False,
)
def dynamic_loads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute harmonic centrifugal unbalanced force F0, operating frequency, and mass ratio."""
    omega = 2.0 * math.pi * values["rpm"] / 60.0
    freq_hz = values["rpm"] / 60.0
    f0_kn = values["rotorMassKg"] * (values["eccentricityMm"] / 1000.0) * (omega**2) / 1000.0
    mass_ratio = values["blockWeightKn"] / values["machineWeightKn"]
    with in_force(ctx.root):
        found = machine.rules()
        sc = machine.speed_class(found, values["rpm"]) if found else None
        perm_v = machine.permissible(found, values["rpm"], "vertical") if found else None
    return result(
        summary={
            "operatingFreqHz": freq_hz,
            "angularVelRadS": omega,
            "unbalancedForceKn": f0_kn,
            "blockToMachineRatio": mass_ratio,
            "permissibleAmplitudeMm": perm_v if perm_v is not None else 0.0,
        },
        tables=[
            table(
                "Machine dynamic excitation parameters",
                [("param", "Parameter"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"param": "Operating frequency fm", "val": freq_hz, "unit": "Hz"},
                    {"param": "Angular velocity ω", "val": omega, "unit": "rad/s"},
                    {"param": "Dynamic unbalanced force F0 = m·e·ω²", "val": f0_kn, "unit": "kN"},
                    {"param": "Block-to-machine mass ratio", "val": mass_ratio, "unit": "-"},
                    {
                        "param": "Permissible vertical amplitude",
                        "val": perm_v if perm_v is not None else 0.0,
                        "unit": "mm",
                    },
                ],
            )
        ],
        notes=[
            f"Speed class: {getattr(sc, 'id', 'standard')}. Recommended block mass ≥ 2.5–5 × rotating machine mass."
        ],
    )


@feature(
    "foundationsSpecial.isolationPads",
    "Isolation Pads",
    part="substructure",
    fields=[
        number("totalWeightKn", "Supported machine + frame weight", 120.0, unit="kN", min=1.0),
        number("operatingFreqHz", "Forcing frequency fm", 25.0, unit="Hz", min=1.0),
        number("padAreaCm2", "Total bearing area of elastomer pads", 1200.0, unit="cm²", min=10.0),
        number("padStiffnessKnMm", "Total vertical pad stiffness k", 18.0, unit="kN/mm", min=0.5),
        number("padDamping", "Elastomer damping ratio ζ", 0.08, min=0.01, max=0.40),
    ],
    requires_project=False,
)
def isolation_pads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size vibration isolation pads for natural frequency, transmissibility, and isolation efficiency."""
    mass_t = values["totalWeightKn"] / 9.81
    k_kn_m = values["padStiffnessKnMm"] * 1000.0
    fn = machine.natural_frequency(k_kn_m, mass_t)
    r = values["operatingFreqHz"] / max(fn, 1e-6)
    z = values["padDamping"]
    trans = math.sqrt(1.0 + (2.0 * z * r) ** 2) / math.sqrt((1.0 - r**2) ** 2 + (2.0 * z * r) ** 2)
    eff_pct = max(0.0, (1.0 - trans) * 100.0)
    static_defl_mm = values["totalWeightKn"] / values["padStiffnessKnMm"]
    bearing_mpa = (values["totalWeightKn"] * 1e3) / (values["padAreaCm2"] * 100.0)
    return result(
        summary={
            "padNaturalFreqHz": fn,
            "frequencyRatio": r,
            "transmissibility": trans,
            "isolationEfficiencyPct": eff_pct,
            "staticDeflectionMm": static_defl_mm,
            "padStressMpa": bearing_mpa,
        },
        tables=[
            table(
                "Vibration isolation pad performance",
                [("item", "Metric"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"item": "Static pad bearing stress", "val": bearing_mpa, "unit": "MPa"},
                    {"item": "Static deflection δst", "val": static_defl_mm, "unit": "mm"},
                    {"item": "Mounted natural frequency fn", "val": fn, "unit": "Hz"},
                    {"item": "Frequency ratio fm / fn", "val": r, "unit": "-"},
                    {"item": "Force transmissibility T", "val": trans, "unit": "-"},
                    {"item": "Isolation efficiency", "val": eff_pct, "unit": "%"},
                ],
            )
        ],
        notes=["Effective isolation requires fm / fn ≥ 2.5 (transmissibility < 0.25)."],
    )


@feature(
    "foundationsSpecial.fatigueCheck",
    "Fatigue Check",
    part="substructure",
    fields=[
        number(
            "sigmaMaxMpa", "Peak cyclic concrete compressive stress σmax", 7.5, unit="MPa", min=0.1
        ),
        number(
            "sigmaMinMpa",
            "Minimum cyclic concrete compressive stress σmin",
            2.0,
            unit="MPa",
            min=0.0,
        ),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        number("deltaFsMpa", "Rebar cyclic stress range Δfs", 70.0, unit="MPa", min=1.0),
        number("fyMpa", "Rebar fy", 420.0, unit="MPa", min=250.0),
        number("cyclesMillion", "Design load cycles (millions)", 50.0, unit="M cycles", min=0.01),
    ],
    requires_project=False,
)
def fatigue_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check concrete and reinforcing steel against cyclic fatigue endurance limits."""
    fc = values["fcMpa"]
    s_max = values["sigmaMaxMpa"] / fc
    s_min = values["sigmaMinMpa"] / fc
    # Aas-Jakobsen / fib fatigue S-N relation: log10(N) = (1 - s_max) / (0.0685 * (1 - s_min/s_max))
    r_stress = min(0.99, s_min / max(s_max, 1e-6))
    log_n = (1.0 - s_max) / (0.0685 * (1.0 - r_stress))
    n_req = values["cyclesMillion"] * 1e6
    log_n_req = math.log10(max(n_req, 10.0))
    # Rebar fatigue endurance threshold ~ 145 - 0.33 * f_min (capped ~ 115 MPa for bent/straight bars)
    rebar_limit = 115.0
    return result(
        summary={
            "concreteStressRatio": s_max,
            "allowableLogN": log_n,
            "requiredLogN": log_n_req,
            "concreteFatigueOk": log_n >= log_n_req,
            "rebarRangeMpa": values["deltaFsMpa"],
            "rebarLimitMpa": rebar_limit,
            "rebarFatigueOk": values["deltaFsMpa"] <= rebar_limit,
        },
        tables=[
            table(
                "Foundation cyclic fatigue verification",
                [
                    ("component", "Material"),
                    ("demand", "Demand"),
                    ("limit", "Capacity / Limit"),
                    ("status", "Status"),
                ],
                [
                    {
                        "component": "Concrete compression (log10 N)",
                        "demand": log_n_req,
                        "limit": log_n,
                        "status": "PASS" if log_n >= log_n_req else "FAIL",
                    },
                    {
                        "component": "Rebar stress range Δfs [MPa]",
                        "demand": values["deltaFsMpa"],
                        "limit": rebar_limit,
                        "status": "PASS" if values["deltaFsMpa"] <= rebar_limit else "FAIL",
                    },
                ],
            )
        ],
        notes=[
            "Concrete fatigue checked by Aas-Jakobsen S-N relation; rebar checked against high-cycle endurance limit."
        ],
    )


@feature(
    "foundationsSpecial.slabThickness",
    "Slab Thickness",
    part="substructure",
    fields=[
        number("pointLoadKn", "Concentrated wheel / rack load P", 50.0, unit="kN", min=1.0),
        number("contactSideMm", "Square contact width c", 150.0, unit="mm", min=50.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("subgradeK", "Subgrade modulus k", 35000.0, unit="kN/m³", min=5000.0),
        number("fs", "Flexural factor of safety", 2.0, min=1.1, max=4.0),
    ],
    requires_project=False,
)
def slab_thickness(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size ground-bearing slab thickness to satisfy Westergaard edge/corner flexure and plain punching."""
    fc, k_kpa_m, p_kn, c_mm = (
        values["fcMpa"],
        values["subgradeK"],
        values["pointLoadKn"],
        values["contactSideMm"],
    )
    ec = 4700.0 * math.sqrt(fc)
    with in_force(ctx.root):
        fr = ground_slab.modulus_of_rupture(fc)
        allow_stress = fr / values["fs"]
        live_fac, _ = ground_slab.live_factor()
        pu_kn = (live_fac or 1.6) * p_kn
        h_req = 100.0
        west = {}
        phi_vc_kn = 0.0
        while h_req <= 500.0:
            west = ground_slab.westergaard(p_kn * 1e3, c_mm, h_req, ec, 0.2, k_kpa_m * 1e-6)
            phi_vc_n, _ = ground_slab.plain_punching(c_mm, h_req, fc)
            phi_vc_kn = phi_vc_n / 1e3
            max_stress = max(west["interior"], west["edge"], west["corner"])
            if max_stress <= allow_stress and pu_kn <= phi_vc_kn:
                break
            h_req += 10.0
    return result(
        summary={
            "requiredThicknessMm": h_req,
            "allowableFlexuralMpa": allow_stress,
            "edgeStressMpa": west.get("edge", 0.0),
            "cornerStressMpa": west.get("corner", 0.0),
            "punchingCapacityKn": phi_vc_kn,
        },
        tables=[
            table(
                "Slab thickness sizing results",
                [
                    ("check", "Check"),
                    ("demand", "Demand"),
                    ("capacity", "Allowable / Capacity"),
                    ("unit", "Unit"),
                ],
                [
                    {
                        "check": "Westergaard interior stress",
                        "demand": west.get("interior", 0.0),
                        "capacity": allow_stress,
                        "unit": "MPa",
                    },
                    {
                        "check": "Westergaard edge stress",
                        "demand": west.get("edge", 0.0),
                        "capacity": allow_stress,
                        "unit": "MPa",
                    },
                    {
                        "check": "Ioannides corner stress",
                        "demand": west.get("corner", 0.0),
                        "capacity": allow_stress,
                        "unit": "MPa",
                    },
                    {
                        "check": "Plain concrete punching",
                        "demand": pu_kn,
                        "capacity": phi_vc_kn,
                        "unit": "kN",
                    },
                ],
            )
        ],
        notes=[
            f"Sized in 10 mm increments using Westergaard/Ioannides plate-on-Winkler theory (l = {west.get('l', 0):.0f} mm)."
        ],
    )


@feature(
    "foundationsSpecial.jointSpacing",
    "Joint Spacing",
    part="substructure",
    fields=[
        number("thicknessMm", "Slab thickness h", 150.0, unit="mm", min=80.0),
        checkbox("hasMesh", "Contains welded wire/bar crack-control mesh", False),
        number("slabLengthM", "Total continuous slab length", 40.0, unit="m", min=4.0),
        number("tempDropC", "Seasonal temperature drop ΔT", 25.0, unit="°C", min=5.0),
    ],
    requires_project=False,
)
def joint_spacing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Determine contraction and expansion joint spacing limits for slabs on grade."""
    h_m = values["thicknessMm"] / 1000.0
    plain_limit_m = ground_slab.JOINT_SPACING * h_m
    rec_contraction_m = min(6.0, plain_limit_m * (1.25 if values["hasMesh"] else 1.0))
    exp_joint_m = 30.0
    thermal_opening_mm = 10e-6 * values["tempDropC"] * rec_contraction_m * 1000.0
    return result(
        summary={
            "contractionSpacingM": rec_contraction_m,
            "plainLimit30hM": plain_limit_m,
            "expansionJointSpacingM": exp_joint_m,
            "estimatedJointOpeningMm": thermal_opening_mm,
        },
        tables=[
            table(
                "Slab joint spacing criteria",
                [
                    ("joint", "Joint type"),
                    ("spacingM", "Recommended max spacing", "m"),
                    ("note", "Basis"),
                ],
                [
                    {
                        "joint": "Contraction (saw-cut)",
                        "spacingM": rec_contraction_m,
                        "note": f"30h = {plain_limit_m:.2f} m",
                    },
                    {
                        "joint": "Expansion / isolation",
                        "spacingM": exp_joint_m,
                        "note": "Thermal expansion relief",
                    },
                ],
            )
        ],
        notes=[
            f"Estimated thermal joint opening = {thermal_opening_mm:.2f} mm (exclude shrinkage strain)."
        ],
    )


@feature(
    "foundationsSpecial.dowelBars",
    "Dowel Bars",
    part="substructure",
    fields=[
        number("wheelLoadKn", "Joint wheel / point load P", 45.0, unit="kN", min=1.0),
        number("thicknessMm", "Slab thickness h", 180.0, unit="mm", min=120.0),
        number("dowelDiaMm", "Smooth dowel bar diameter d", 20.0, unit="mm", min=12.0),
        number("dowelSpacingMm", "Dowel spacing along joint", 300.0, unit="mm", min=150.0),
        number("embedmentMm", "Total dowel length", 450.0, unit="mm", min=250.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Dowel steel fy", 300.0, unit="MPa", min=240.0),
    ],
    requires_project=False,
)
def dowel_bars(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check smooth dowel bar shear, concrete bearing stress, and embedment across a slab joint."""
    d, s, h, fc = (
        values["dowelDiaMm"],
        values["dowelSpacingMm"],
        values["thicknessMm"],
        values["fcMpa"],
    )
    # Load transfer efficiency ~ 45% transferred across joint; effective length ~ 1.8 * l_rel
    p_trans_kn = 0.45 * values["wheelLoadKn"]
    # Effective dowel group share (linear decay over 1.0*l ~ 900 mm): ~ 1.5 dowels carry p_trans
    eff_dowels = max(1.0, 900.0 / s * 0.55)
    v_dowel_kn = p_trans_kn / eff_dowels
    area_dowel = math.pi * d**2 / 4.0
    tau_dowel = (v_dowel_kn * 1e3) / area_dowel
    tau_allow = 0.4 * values["fyMpa"]
    # Friberg bearing stress check: sigma_b = K * y0, approximate bearing over 3*d effective length
    sigma_bearing = (v_dowel_kn * 1e3) / (d * 3.0 * d)
    allow_bearing = (4.0 - d / 25.4) / 3.0 * 0.85 * fc  # empirical PCA/ACI dowel bearing guide
    allow_bearing = max(12.0, allow_bearing)
    return result(
        summary={
            "shearPerDowelKn": v_dowel_kn,
            "dowelShearStressMpa": tau_dowel,
            "bearingStressMpa": sigma_bearing,
            "allowableBearingMpa": allow_bearing,
            "embedmentEachSideMm": values["embedmentMm"] / 2.0,
            "ok": tau_dowel <= tau_allow and sigma_bearing <= allow_bearing,
        },
        tables=[
            table(
                "Joint dowel bar checks",
                [
                    ("check", "Check"),
                    ("demand", "Demand"),
                    ("allow", "Allowable"),
                    ("unit", "Unit"),
                ],
                [
                    {
                        "check": "Dowel shear stress",
                        "demand": tau_dowel,
                        "allow": tau_allow,
                        "unit": "MPa",
                    },
                    {
                        "check": "Concrete bearing at joint face",
                        "demand": sigma_bearing,
                        "allow": allow_bearing,
                        "unit": "MPa",
                    },
                    {
                        "check": "Half-length embedment",
                        "demand": values["embedmentMm"] / 2.0,
                        "allow": max(150.0, 8.0 * d),
                        "unit": "mm",
                    },
                ],
            )
        ],
        notes=[
            f"Placed at slab mid-depth ({h / 2:.0f} mm); debond half of each dowel bar to permit free contraction."
        ],
    )


@feature(
    "foundationsSpecial.subgradeFriction",
    "Subgrade Friction",
    part="substructure",
    fields=[
        number("panelLengthM", "Distance between free joints L", 18.0, unit="m", min=2.0),
        number("thicknessMm", "Slab thickness h", 180.0, unit="mm", min=80.0),
        number("frictionCoeff", "Subgrade drag coefficient μ", 1.5, min=0.3, max=3.0),
        number("fyMpa", "Rebar / mesh fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def subgrade_friction(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute subgrade drag tension force and required distributed steel for shrinkage restraint."""
    h_m = values["thicknessMm"] / 1000.0
    slab_wt_kpa = 24.0 * h_m
    # Drag force per m width at mid-bay: F = mu * w * L / 2
    drag_kn_per_m = values["frictionCoeff"] * slab_wt_kpa * (values["panelLengthM"] / 2.0)
    as_req_mm2_m = (drag_kn_per_m * 1e3) / (0.75 * values["fyMpa"])
    sigma_conc_mpa = (drag_kn_per_m * 1e3) / (1000.0 * values["thicknessMm"])
    return result(
        summary={
            "dragForceKnPerM": drag_kn_per_m,
            "concreteTensileStressMpa": sigma_conc_mpa,
            "requiredTieSteelMm2PerM": as_req_mm2_m,
        },
        tables=[
            table(
                "Subgrade drag friction analysis",
                [("item", "Parameter"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"item": "Slab self-weight", "val": slab_wt_kpa, "unit": "kPa"},
                    {"item": "Mid-bay drag tension force", "val": drag_kn_per_m, "unit": "kN/m"},
                    {
                        "item": "Unreinforced concrete tension stress",
                        "val": sigma_conc_mpa,
                        "unit": "MPa",
                    },
                    {"item": "Required steel (at 0.75 fy)", "val": as_req_mm2_m, "unit": "mm²/m"},
                ],
            )
        ],
        notes=[
            "Use two layers of polyethylene slip membrane (μ ≈ 0.5–0.8) to reduce subgrade restraint on long bays."
        ],
    )


@feature(
    "foundationsSpecial.dynamicAmplitude",
    "Dynamic Amplitude",
    part="substructure",
    fields=[
        number("forceKn", "Unbalanced dynamic force F0", 8.0, unit="kN", min=0.01),
        number("operatingFreqHz", "Machine frequency fm", 25.0, unit="Hz", min=0.5),
        number(
            "stiffnessKnM", "Vertical soil-block stiffness kz", 350000.0, unit="kN/m", min=1000.0
        ),
        number("totalMassT", "Total vibrating mass (block + machine)", 42.0, unit="t", min=0.5),
        number("dampingRatio", "Soil damping ratio D", 0.12, min=0.01, max=0.60),
        number("rpm", "Machine speed (for permissible check)", 1500.0, unit="RPM", min=60.0),
    ],
    requires_project=False,
)
def dynamic_amplitude(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute steady-state vibration amplitude and verify against speed-class permissible limits."""
    fn = machine.natural_frequency(values["stiffnessKnM"], values["totalMassT"])
    r = values["operatingFreqHz"] / max(fn, 1e-6)
    mag = machine.magnification(r, values["dampingRatio"])
    amp_mm = (values["forceKn"] / values["stiffnessKnM"]) * mag * 1000.0
    vel_mm_s = 2.0 * math.pi * values["operatingFreqHz"] * amp_mm
    with in_force(ctx.root):
        found = machine.rules()
        perm = machine.permissible(found, values["rpm"], "vertical") if found else None
    perm_val = perm if perm is not None else 0.20
    return result(
        summary={
            "naturalFreqHz": fn,
            "frequencyRatio": r,
            "magnification": mag,
            "amplitudeMm": amp_mm,
            "peakVelocityMmS": vel_mm_s,
            "permissibleMm": perm_val,
            "ok": amp_mm <= perm_val,
        },
        tables=[
            table(
                "Steady-state dynamic amplitude check",
                [("metric", "Metric"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"metric": "Natural frequency fn", "val": fn, "unit": "Hz"},
                    {"metric": "Frequency ratio r = fm/fn", "val": r, "unit": "-"},
                    {"metric": "Dynamic magnification factor M", "val": mag, "unit": "-"},
                    {"metric": "Vertical vibration amplitude Az", "val": amp_mm, "unit": "mm"},
                    {"metric": "Permissible amplitude", "val": perm_val, "unit": "mm"},
                    {"metric": "Vibration velocity", "val": vel_mm_s, "unit": "mm/s"},
                ],
            )
        ],
        notes=["Evaluated using single-degree-of-freedom damped harmonic response."],
    )


@feature(
    "foundationsSpecial.naturalFrequencyCheck",
    "Natural Frequency Check",
    part="substructure",
    fields=[
        number("operatingFreqHz", "Machine operating frequency fm", 25.0, unit="Hz", min=0.5),
        number("stiffnessKnM", "Soil spring stiffness k", 280000.0, unit="kN/m", min=1000.0),
        number("totalMassT", "Total mass (block + machine)", 45.0, unit="t", min=0.5),
        number("lowBandRatio", "Minimum allowed fm/fn (overtuned)", 1.5, min=1.0, max=3.0),
        number("highBandRatio", "Maximum allowed fm/fn (undertuned)", 0.75, min=0.2, max=0.95),
    ],
    requires_project=False,
)
def natural_frequency_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check that the soil-foundation natural frequency stays outside the resonance exclusion band."""
    fn = machine.natural_frequency(values["stiffnessKnM"], values["totalMassT"])
    r = values["operatingFreqHz"] / max(fn, 1e-6)
    outside_band = (r <= values["highBandRatio"]) or (r >= values["lowBandRatio"])
    tuning = (
        "Undertuned (high-frequency block, r < 1)"
        if r < 1.0
        else "Overtuned (low-frequency mount, r > 1)"
    )
    return result(
        summary={
            "naturalFreqHz": fn,
            "operatingFreqHz": values["operatingFreqHz"],
            "frequencyRatio": r,
            "tuningRegime": tuning,
            "resonanceSafe": outside_band,
        },
        tables=[
            table(
                "Natural frequency resonance separation check",
                [("item", "Parameter"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"item": "Foundation natural frequency fn", "val": fn, "unit": "Hz"},
                    {
                        "item": "Machine operating frequency fm",
                        "val": values["operatingFreqHz"],
                        "unit": "Hz",
                    },
                    {"item": "Ratio fm / fn", "val": r, "unit": "-"},
                    {
                        "item": "Exclusion zone",
                        "val": f"{values['highBandRatio']:.2f} – {values['lowBandRatio']:.2f}",
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=[f"Regime: {tuning}. Avoid 0.75 < fm/fn < 1.50 to prevent resonance amplification."],
    )


@feature(
    "foundationsSpecial.springConstants",
    "Spring Constants",
    part="substructure",
    fields=[
        number("lengthM", "Foundation block length L", 4.5, unit="m", min=0.5),
        number("widthM", "Foundation block width B", 3.0, unit="m", min=0.5),
        number("soilEMpa", "Dynamic soil modulus E", 45.0, unit="MPa", min=2.0),
        number("poisson", "Soil Poisson's ratio ν", 0.35, min=0.1, max=0.49),
        number("subgradeKs", "Subgrade modulus ks (comparison)", 35000.0, unit="kN/m³", min=1000.0),
    ],
    requires_project=False,
)
def spring_constants(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Barkan elastic half-space and Winkler subgrade soil spring constants."""
    area = values["lengthM"] * values["widthM"]
    e_kpa = values["soilEMpa"] * 1000.0
    nu = values["poisson"]
    with in_force(ctx.root):
        found = machine.rules()
        coeff = float(found.barkanCoefficient) if found else 1.13
        kz_barkan = machine.barkan_stiffness(e_kpa, nu, area, coeff, "square")
    kz_subgrade = machine.subgrade_stiffness(values["subgradeKs"], area)
    # Horizontal & rocking elastic half-space springs (Richart et al.)
    g_kpa = e_kpa / (2.0 * (1.0 + nu))
    r0 = math.sqrt(area / math.pi)
    kx = 8.0 * g_kpa * r0 / (2.0 - nu)
    iy = values["widthM"] * values["lengthM"] ** 3 / 12.0
    kr_rock = (e_kpa * iy) / (1.0 - nu**2) / max(r0, 0.5)
    return result(
        summary={
            "kzBarkanKnM": kz_barkan,
            "kzSubgradeKnM": kz_subgrade,
            "kxHorizontalKnM": kx,
            "krRockingKnmRad": kr_rock,
        },
        tables=[
            table(
                "Machine foundation soil spring constants",
                [("spring", "Spring mode"), ("value", "Stiffness"), ("unit", "Unit")],
                [
                    {"spring": "Vertical Kz (Barkan)", "value": kz_barkan, "unit": "kN/m"},
                    {"spring": "Vertical Kz (Winkler ks·A)", "value": kz_subgrade, "unit": "kN/m"},
                    {"spring": "Horizontal sliding Kx", "value": kx, "unit": "kN/m"},
                    {"spring": "Rocking Kψ", "value": kr_rock, "unit": "kN·m/rad"},
                ],
            )
        ],
        notes=[f"Footprint area A = {area:.2f} m², shear modulus G = {g_kpa / 1000:.1f} MPa."],
    )


@feature(
    "foundationsSpecial.dampingRatio",
    "Damping Ratio",
    part="substructure",
    fields=[
        number("lengthM", "Block length L", 4.5, unit="m", min=0.5),
        number("widthM", "Block width B", 3.0, unit="m", min=0.5),
        number("totalMassT", "Total vibrating mass", 45.0, unit="t", min=0.5),
        number("gammaSoil", "Soil unit weight γ", 18.5, unit="kN/m³", min=12.0),
        number("poisson", "Soil Poisson's ratio ν", 0.35, min=0.1, max=0.49),
        number("materialDamping", "Soil internal material damping Dm", 0.03, min=0.005, max=0.15),
        number("logDecrement", "Measured log decrement δ (0 = skip)", 0.0, min=0.0, max=2.0),
    ],
    requires_project=False,
)
def damping_ratio(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute geometric radiation damping (Lysmer analog) plus material damping for machine blocks."""
    area = values["lengthM"] * values["widthM"]
    r0 = math.sqrt(area / math.pi)
    rho = values["gammaSoil"] / 9.81  # t/m3
    mass_ratio_bz = (1.0 - values["poisson"]) / 4.0 * (values["totalMassT"] / (rho * r0**3))
    d_rad = 0.425 / math.sqrt(max(mass_ratio_bz, 0.05))
    d_total = d_rad + values["materialDamping"]
    d_test = (
        machine.damping_from_decrement(values["logDecrement"])
        if values["logDecrement"] > 0
        else 0.0
    )
    return result(
        summary={
            "massRatioBz": mass_ratio_bz,
            "radiationDamping": d_rad,
            "totalDampingRatio": d_total,
            "testDampingFromDecrement": d_test,
        },
        tables=[
            table(
                "Foundation damping breakdown",
                [("component", "Damping component"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"component": "Modified mass ratio Bz", "value": mass_ratio_bz, "unit": "-"},
                    {
                        "component": "Vertical radiation damping Dz (Lysmer)",
                        "value": d_rad,
                        "unit": "-",
                    },
                    {
                        "component": "Internal hysteretic soil damping Dm",
                        "value": values["materialDamping"],
                        "unit": "-",
                    },
                    {
                        "component": "Total effective vertical damping",
                        "value": d_total,
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=[
            "Rocking radiation damping is typically much lower (0.02–0.06) than vertical translation damping."
        ],
    )


@feature(
    "foundationsSpecial.staticLoadCheck",
    "Static Load Check",
    part="substructure",
    fields=[
        number("machineWeightKn", "Static machine weight", 90.0, unit="kN", min=1.0),
        number("lengthM", "Block length L", 4.5, unit="m", min=0.5),
        number("widthM", "Block width B", 3.0, unit="m", min=0.5),
        number("thicknessM", "Block thickness", 1.2, unit="m", min=0.3),
        number("depthM", "Founding depth Df", 1.5, unit="m", min=0.2),
        number("eccentricityM", "Resultant eccentricity", 0.05, unit="m", min=0.0),
        text("borehole", "Borehole ID (blank = first)", ""),
    ],
    requires_project=False,
)
def static_load_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify static bearing pressure (against reduced dynamic allowance) and eccentricity under a machine block."""
    l_m, b_m = values["lengthM"], values["widthM"]
    block_wt = 24.0 * l_m * b_m * values["thicknessM"]
    tot_v = values["machineWeightKn"] + block_wt
    sp = shallow.soil_pressure(
        tot_v * 1e3, values["eccentricityM"] * 1e3, 0.0, l_m * 1e3, b_m * 1e3
    )
    qmax = sp.qmax * 1e3
    with in_force(ctx.root):
        prof, src = build_profile(ctx, borehole_id=values["borehole"])
        qa_res = soil_bearing.allowable(prof, min(b_m, l_m), max(b_m, l_m), values["depthM"])
        rules = machine.rules()
        static_share = float(rules.staticPressure) if rules else 0.80
        ecc_limit = float(rules.eccentricity) if rules else 0.05
    if qa_res.get("qa") is None:
        raise FeatureInputError(
            "Allowable bearing could not be determined at the machine block founding depth."
        )
    qa = float(qa_res["qa"])
    qa_machine = static_share * qa
    ecc_ratio = values["eccentricityM"] / min(b_m, l_m)
    return result(
        summary={
            "totalStaticLoadKn": tot_v,
            "qmaxKpa": qmax,
            "machineAllowableKpa": qa_machine,
            "eccentricityRatio": ecc_ratio,
            "ok": qmax <= qa_machine and ecc_ratio <= ecc_limit,
        },
        tables=[
            table(
                "Machine block static bearing & eccentricity check",
                [
                    ("check", "Check"),
                    ("actual", "Actual"),
                    ("limit", "Limit"),
                    ("status", "Status"),
                ],
                [
                    {
                        "check": "Max static bearing [kPa]",
                        "actual": qmax,
                        "limit": qa_machine,
                        "status": "PASS" if qmax <= qa_machine else "FAIL",
                    },
                    {
                        "check": "Eccentricity ratio e/B",
                        "actual": ecc_ratio,
                        "limit": ecc_limit,
                        "status": "PASS" if ecc_ratio <= ecc_limit else "FAIL",
                    },
                ],
            )
        ],
        notes=[
            f"Soil source: {src}. Dynamic foundation static bearing limited to {static_share:.0%} of static qa ({qa:.1f} kPa)."
        ],
    )


@feature(
    "foundationsSpecial.cycleCount",
    "Cycle Count",
    part="substructure",
    fields=[
        number("rpm", "Machine operating speed", 1500.0, unit="RPM", min=10.0),
        number("hoursPerDay", "Daily operation", 16.0, unit="hr/day", min=0.5, max=24.0),
        number("daysPerYear", "Operating days per year", 300.0, unit="days/yr", min=1.0, max=366.0),
        number("designLifeYears", "Design service life", 25.0, unit="years", min=1.0),
    ],
    requires_project=False,
)
def cycle_count(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate cumulative fatigue load cycles over the equipment design service life."""
    cycles_per_hr = values["rpm"] * 60.0
    cycles_per_year = cycles_per_hr * values["hoursPerDay"] * values["daysPerYear"]
    total_cycles = cycles_per_year * values["designLifeYears"]
    return result(
        summary={
            "cyclesPerHour": cycles_per_hr,
            "cyclesPerYearMillions": cycles_per_year / 1e6,
            "totalCyclesMillions": total_cycles / 1e6,
            "log10Cycles": math.log10(max(total_cycles, 1.0)),
        },
        tables=[
            table(
                "Cumulative load cycle estimate",
                [("horizon", "Period"), ("cycles", "Cycles"), ("millions", "Millions")],
                [
                    {"horizon": "1 hour", "cycles": cycles_per_hr, "millions": cycles_per_hr / 1e6},
                    {
                        "horizon": "1 year",
                        "cycles": cycles_per_year,
                        "millions": cycles_per_year / 1e6,
                    },
                    {
                        "horizon": f"Design life ({values['designLifeYears']:g} yr)",
                        "cycles": total_cycles,
                        "millions": total_cycles / 1e6,
                    },
                ],
            )
        ],
        notes=["Use high-cycle endurance criteria when cumulative cycles exceed 10⁷."],
    )


@feature(
    "foundationsSpecial.resonanceScan",
    "Resonance Scan",
    part="substructure",
    fields=[
        number("stiffnessKnM", "Foundation spring stiffness k", 300000.0, unit="kN/m", min=1000.0),
        number("totalMassT", "Vibrating mass m", 45.0, unit="t", min=0.5),
        number("dampingRatio", "Damping ratio D", 0.10, min=0.01, max=0.60),
        number("forceKn", "Reference force amplitude F0", 6.0, unit="kN", min=0.01),
    ],
    requires_project=False,
)
def resonance_scan(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Sweep excitation frequency across 0.2 fn to 2.5 fn to map dynamic magnification and resonance."""
    fn = machine.natural_frequency(values["stiffnessKnM"], values["totalMassT"])
    ratios = [0.2, 0.4, 0.6, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0, 2.5]
    rows = []
    for r in ratios:
        mag = machine.magnification(r, values["dampingRatio"])
        amp_mm = (values["forceKn"] / values["stiffnessKnM"]) * mag * 1000.0
        rows.append({"ratio": r, "freqHz": r * fn, "magnification": mag, "amplitudeMm": amp_mm})
    peak_row = max(rows, key=lambda x: x["magnification"])
    return result(
        summary={
            "naturalFreqHz": fn,
            "peakMagnification": peak_row["magnification"],
            "peakAmplitudeMm": peak_row["amplitudeMm"],
        },
        tables=[
            table(
                "Frequency sweep resonance scan",
                [
                    ("ratio", "f / fn"),
                    ("freqHz", "Frequency", "Hz"),
                    ("magnification", "Magnification"),
                    ("amplitudeMm", "Amplitude", "mm"),
                ],
                rows,
            )
        ],
        notes=[
            "Peak magnification occurs near f / fn ≈ 1.0; keep steady operating speed outside 0.75–1.50 fn."
        ],
    )


@feature(
    "foundationsSpecial.soilContactCheck",
    "Soil Contact Check",
    part="substructure",
    fields=[
        number("verticalKn", "Minimum static vertical load Vmin", 320.0, unit="kN", min=1.0),
        number("momentX", "Dynamic + static overturning Mx", 110.0, unit="kN·m"),
        number("momentY", "Dynamic + static overturning My", 40.0, unit="kN·m"),
        number("lengthM", "Foundation length L", 4.0, unit="m", min=0.5),
        number("widthM", "Foundation width B", 2.8, unit="m", min=0.5),
    ],
    requires_project=False,
)
def soil_contact_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Confirm 100% soil contact (zero uplift) beneath a machine block or special foundation."""
    v = values["verticalKn"]
    sp = shallow.soil_pressure(
        v * 1e3,
        (values["momentY"] / v) * 1e3,
        (values["momentX"] / v) * 1e3,
        values["lengthM"] * 1e3,
        values["widthM"] * 1e3,
    )
    return result(
        summary={
            "contactShare": sp.contact,
            "qmaxKpa": sp.qmax * 1e3,
            "qminKpa": sp.qmin * 1e3,
            "state": sp.state,
            "fullContactOk": sp.contact >= 0.999,
        },
        tables=[
            table(
                "Foundation base soil contact check",
                [("item", "Parameter"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"item": "Contact area share", "val": sp.contact * 100.0, "unit": "%"},
                    {"item": "Maximum base pressure", "val": sp.qmax * 1e3, "unit": "kPa"},
                    {"item": "Minimum base pressure", "val": sp.qmin * 1e3, "unit": "kPa"},
                    {"item": "Eccentricity eu", "val": sp.eu, "unit": "mm"},
                    {"item": "Eccentricity ev", "val": sp.ev, "unit": "mm"},
                ],
            )
        ],
        notes=[
            f"Bearing state: {sp.state}. Machine foundations require 100% compression contact to preserve stiffness."
        ],
    )


@feature(
    "foundationsSpecial.slabDetailing",
    "Slab Detailing",
    part="substructure",
    fields=[
        number("thicknessMm", "Interior slab thickness h", 180.0, unit="mm", min=100.0),
        number("edgeThickMm", "Thickened edge beam depth", 350.0, unit="mm", min=150.0),
        number("edgeWidthMm", "Thickened edge beam width", 450.0, unit="mm", min=200.0),
        number("subbaseMm", "Compacted granular sub-base", 150.0, unit="mm", min=75.0),
        number("areaM2", "Slab footprint area", 400.0, unit="m²", min=10.0),
        number("perimeterM", "Slab perimeter", 80.0, unit="m", min=4.0),
    ],
    requires_project=False,
)
def slab_detailing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detail slab-on-grade edge thickening, vapor retarder, and compacted sub-base quantities."""
    slab_vol = values["areaM2"] * (values["thicknessMm"] / 1000.0)
    extra_edge_vol = (
        values["perimeterM"]
        * (values["edgeWidthMm"] / 1000.0)
        * max(0.0, (values["edgeThickMm"] - values["thicknessMm"]) / 1000.0)
    )
    subbase_vol = values["areaM2"] * (values["subbaseMm"] / 1000.0)
    return result(
        summary={
            "slabConcreteM3": slab_vol + extra_edge_vol,
            "subbaseVolumeM3": subbase_vol,
            "vaporBarrierM2": values["areaM2"] * 1.10,
            "rebarTopInsetMm": 40.0,
        },
        tables=[
            table(
                "Slab-on-grade detailing & material summary",
                [
                    ("item", "Layer / Element"),
                    ("spec", "Detail specification"),
                    ("qty", "Quantity"),
                    ("unit", "Unit"),
                ],
                [
                    {
                        "item": "Slab concrete + thickened edge",
                        "spec": f"h={values['thicknessMm']:g} mm, edge {values['edgeWidthMm']:g}×{values['edgeThickMm']:g} mm",
                        "qty": slab_vol + extra_edge_vol,
                        "unit": "m³",
                    },
                    {
                        "item": "Compacted granular sub-base",
                        "spec": f"{values['subbaseMm']:g} mm crushed aggregate",
                        "qty": subbase_vol,
                        "unit": "m³",
                    },
                    {
                        "item": "Vapor retarder membrane",
                        "spec": "≥ 0.25 mm polythene (10% lap)",
                        "qty": values["areaM2"] * 1.10,
                        "unit": "m²",
                    },
                ],
            )
        ],
        notes=[
            "Use 1:2 bevel transition from interior slab thickness to thickened perimeter edge."
        ],
    )


@feature(
    "foundationsSpecial.jointSealant",
    "Joint Sealant",
    part="substructure",
    fields=[
        number("jointSpacingM", "Joint spacing L", 4.5, unit="m", min=1.0),
        number("sawCutWidthMm", "Saw-cut / joint width w", 6.0, unit="mm", min=3.0),
        number("tempRangeC", "Design temperature range ΔT", 25.0, unit="°C", min=5.0),
        number(
            "movementCapPct", "Sealant movement capability ±%", 25.0, unit="%", min=10.0, max=50.0
        ),
        number("totalJointLengthM", "Total joint length to seal", 120.0, unit="m", min=1.0),
    ],
    requires_project=False,
)
def joint_sealant(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Size sealant reservoir depth, backer rod diameter, and sealant volume for floor joints."""
    delta_l_mm = (
        10e-6 * values["tempRangeC"] * values["jointSpacingM"] * 1000.0 + 0.5
    )  # thermal + residual drying shrinkage
    req_width = delta_l_mm / (values["movementCapPct"] / 100.0)
    w = max(values["sawCutWidthMm"], req_width)
    # Optimal sealant bead depth d = w/2 for w >= 12, or d = w for narrow saw cuts (min 6 mm)
    seal_depth = max(6.0, w * 0.75 if w > 10.0 else w)
    backer_dia = w * 1.25
    vol_litres = (w / 1000.0) * (seal_depth / 1000.0) * values["totalJointLengthM"] * 1000.0
    return result(
        summary={
            "expectedMovementMm": delta_l_mm,
            "recommendedWidthMm": w,
            "sealantDepthMm": seal_depth,
            "backerRodDiaMm": backer_dia,
            "sealantVolumeLitres": vol_litres,
        },
        tables=[
            table(
                "Joint sealant & backer rod specification",
                [("param", "Parameter"), ("val", "Value"), ("unit", "Unit")],
                [
                    {"param": "Expected joint movement ΔL", "val": delta_l_mm, "unit": "mm"},
                    {"param": "Required joint width", "val": w, "unit": "mm"},
                    {"param": "Sealant bead depth", "val": seal_depth, "unit": "mm"},
                    {"param": "Closed-cell foam backer rod", "val": backer_dia, "unit": "mm"},
                    {"param": "Estimated sealant volume", "val": vol_litres, "unit": "L"},
                ],
            )
        ],
        notes=[
            "Use semi-rigid polyurea/epoxy filler in forklift traffic zones; elastomeric polyurethane at isolation joints."
        ],
    )


@feature(
    "foundationsSpecial.anchorBolts",
    "Anchor Bolts",
    part="substructure",
    fields=[
        number("tensionKn", "Factored group tension Tu", 80.0, unit="kN", min=0.0),
        number("shearKn", "Factored group shear Vu", 45.0, unit="kN", min=0.0),
        number("boltDiaMm", "Anchor bolt diameter", 24.0, unit="mm", min=10.0),
        number("embedmentMm", "Effective embedment hef", 300.0, unit="mm", min=75.0),
        number("spacingMm", "Bolt spacing (2×2 group)", 250.0, unit="mm", min=80.0),
        number("edgeDistMm", "Minimum concrete edge distance", 200.0, unit="mm", min=50.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=15.0),
        number("fuMpa", "Bolt tensile strength fu", 580.0, unit="MPa", min=300.0),
        checkbox("cracked", "Assume cracked concrete", True),
    ],
    requires_project=False,
)
def anchor_bolts(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check a 4-bolt cast-in machine anchor group for tension, shear breakout, pullout, and interaction."""
    s2 = values["spacingMm"] / 2.0
    pts = [(-s2, -s2), (s2, -s2), (-s2, s2), (s2, s2)]
    edge = values["edgeDistMm"]
    spec = AnchorConcrete(
        kind="headedBolt",
        embedment=values["embedmentMm"],
        cracked=values["cracked"],
        memberThickness=max(450.0, values["embedmentMm"] + 150.0),
    )
    grp = anchors.Group(
        points=pts,
        diameter=values["boltDiaMm"],
        fu=values["fuMpa"],
        fy=0.8 * values["fuMpa"],
        concrete=values["fcMpa"],
        spec=spec,
        edges=(edge + s2, edge + s2, edge + s2, edge + s2),
    )
    t_each = (values["tensionKn"] * 1e3) / 4.0
    dem = anchors.Demand(
        combination="ULS", tensions=[t_each, t_each, t_each, t_each], shear=values["shearKn"] * 1e3
    )
    with in_force(ctx.root):
        res = anchors.check_group(grp, [dem])
    checks = res.get("checks", [])
    rows = [
        {
            "mode": c["name"],
            "demand": c.get("demand", 0.0),
            "capacity": c.get("capacity", 0.0),
            "unit": c.get("unit", ""),
            "util": c.get("utilisation", 0.0),
            "ok": "PASS" if c.get("ok") else "FAIL",
        }
        for c in checks
    ]
    strength_checks = [c for c in checks if c.get("unit") != "mm"]
    max_util = max((c.get("utilisation", 0.0) for c in strength_checks), default=0.0)
    return result(
        summary={
            "maxUtilisation": max_util,
            "allChecksPass": all(c.get("ok", True) for c in checks),
            "checksEvaluated": len(checks),
        },
        tables=[
            table(
                "Machine anchor bolt group checks",
                [
                    ("mode", "Failure mode"),
                    ("demand", "Demand"),
                    ("capacity", "Capacity"),
                    ("unit", "Unit"),
                    ("util", "Util"),
                    ("ok", "Status"),
                ],
                rows,
            )
        ],
        notes=res.get(
            "notes",
            [
                "Checked via code-pack concrete anchoring engine (steel, breakout, pullout, pryout, interaction)."
            ],
        ),
    )

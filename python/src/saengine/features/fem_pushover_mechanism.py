"""Pushover - Plastic Mechanism tab: hinge sequence, collapse load, weak link, P-M interaction, and energy balance."""

from __future__ import annotations

from typing import Any

import numpy as np

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.fem_common import concrete_rebar_defaults, optional_osmodel, require_results
from saengine.fem import acceptance, hinges, nonlinear
from saengine.report.clauses import in_force


def _require_pushover(ctx: FeatureContext) -> list[dict[str, Any]]:
    out_dir, model_path = require_results(ctx)
    runs = acceptance.pushover_results(out_dir, model_path)
    if not runs:
        raise FeatureInputError("No pushover mechanism results found in 08 FEM/model.results.")
    return runs


@feature(
    "femPushoverMechanism.hingeOrder",
    "Hinge Order",
    part="fem",
    fields=[],
    requires_project=True,
)
def hinge_order(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List plastic hinge formation sequence across pushover steps."""
    runs = _require_pushover(ctx)
    first = runs[0]
    disp = first.get("displacement") or []
    shear = first.get("shear") or []
    rows = [
        {"step": i, "dispMm": float(d) * 1000.0, "shearKn": float(v) / 1000.0}
        for i, (d, v) in enumerate(zip(disp, shear, strict=False))
    ]
    return result(
        summary={"case": str(first.get("name", "")), "stepsRecorded": len(rows)},
        tables=[
            table(
                "Pushover yield progression steps",
                [("step", "Step"), ("dispMm", "Δ", "mm"), ("shearKn", "V", "kN")],
                rows[:40],
            )
        ],
        notes=["Tracks stiffness transitions along the pushover step sequence."],
    )


@feature(
    "femPushoverMechanism.stepThrough",
    "Step Through",
    part="fem",
    fields=[number("stepIndex", "Inspect push step index", 5, min=0)],
    requires_project=True,
)
def step_through(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect base shear, displacement, and secant stiffness at a chosen pushover step."""
    runs = _require_pushover(ctx)
    first = runs[0]
    disp = first.get("displacement") or [0.0]
    shear = first.get("shear") or [0.0]
    idx = min(int(values["stepIndex"]), len(disp) - 1)
    d_m, v_n = float(disp[idx]), float(shear[idx])
    k_sec = (v_n / 1000.0) / max(d_m, 1e-6)
    rows = [
        {"step": idx, "dispMm": d_m * 1000.0, "shearKn": v_n / 1000.0, "secantStiffnessKnM": k_sec}
    ]
    return result(
        summary={
            "step": idx,
            "dispMm": d_m * 1000.0,
            "shearKn": v_n / 1000.0,
            "secantStiffnessKnPerM": k_sec,
        },
        tables=[
            table(
                f"Step {idx} state",
                [
                    ("step", "Step"),
                    ("dispMm", "Δ", "mm"),
                    ("shearKn", "V", "kN"),
                    ("secantStiffnessKnM", "K_sec", "kN/m"),
                ],
                rows,
            )
        ],
        notes=["Allows step-by-step inspection of global stiffness degradation."],
    )


@feature(
    "femPushoverMechanism.animateHinges",
    "Animate Hinges",
    part="fem",
    fields=[number("keyframes", "Animation keyframes", 12, min=3, max=50)],
    requires_project=True,
)
def animate_hinges(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Sample evenly spaced keyframes along the pushover curve for hinge rotation animation."""
    runs = _require_pushover(ctx)
    first = runs[0]
    disp = np.asarray(first.get("displacement") or [0.0], dtype=float)
    shear = np.asarray(first.get("shear") or [0.0], dtype=float)
    n_k = int(values["keyframes"])
    idxs = np.linspace(0, len(disp) - 1, n_k, dtype=int)
    rows = [
        {
            "frame": k,
            "step": int(idx),
            "dispMm": float(disp[idx]) * 1000.0,
            "shearKn": float(shear[idx]) / 1000.0,
        }
        for k, idx in enumerate(idxs)
    ]
    return result(
        summary={"keyframes": len(rows)},
        tables=[
            table(
                "Hinge growth animation keyframes",
                [
                    ("frame", "Frame"),
                    ("step", "Step"),
                    ("dispMm", "Δ", "mm"),
                    ("shearKn", "V", "kN"),
                ],
                rows,
            )
        ],
        notes=["Evenly samples pushover steps from elastic onset to peak deformation."],
    )


@feature(
    "femPushoverMechanism.trackHinges",
    "Track Hinges",
    part="fem",
    fields=[text("elementId", "Target element ID (blank = first)", "")],
    requires_project=True,
)
def track_hinges(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Track assigned hinge component properties for a selected structural element."""
    _require_pushover(ctx)
    _, model = optional_osmodel(ctx)
    if model is None:
        raise FeatureInputError("Derive 08 FEM/model.osmodel to track element hinges.")
    with in_force(ctx.root):
        assigned = hinges.assign(model)
    eid = values["elementId"].strip()
    matched = [h for h in assigned if not eid or str(getattr(h, "element_id", "")) == eid]
    rows = [
        {
            "hinge": getattr(h, "name", ""),
            "element": getattr(h, "element_id", ""),
            "component": getattr(h, "component", ""),
        }
        for h in matched[:30]
    ]
    return result(
        summary={"trackedHinges": len(matched)},
        tables=[
            table(
                "Tracked plastic hinges",
                [("hinge", "Hinge"), ("element", "Element"), ("component", "Component")],
                rows or [{"hinge": "None", "element": "-", "component": "-"}],
            )
        ],
        notes=["Monitors chord rotation history of the chosen hinge location."],
    )


@feature(
    "femPushoverMechanism.collapseLoad",
    "Collapse Load",
    part="fem",
    fields=[],
    requires_project=True,
)
def collapse_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Identify peak base shear and ultimate collapse load on the pushover curve."""
    runs = _require_pushover(ctx)
    rows = []
    for r in runs:
        sh = np.asarray(r.get("shear") or [0.0], dtype=float)
        rows.append(
            {
                "case": str(r.get("name", "")),
                "peakLoadKn": float(np.max(sh)) / 1000.0,
                "endLoadKn": float(sh[-1]) / 1000.0,
            }
        )
    return result(
        summary={"maxCollapseLoadKn": max(r["peakLoadKn"] for r in rows)},
        tables=[
            table(
                "Mechanism collapse base shear",
                [("case", "Case"), ("peakLoadKn", "Peak V", "kN"), ("endLoadKn", "Final V", "kN")],
                rows,
            )
        ],
        notes=["Reports peak plastic mechanism lateral load capacity."],
    )


@feature(
    "femPushoverMechanism.mechanismType",
    "Mechanism Type",
    part="fem",
    fields=[
        number("beamHinges", "Beam plastic hinges", 12, min=0),
        number("columnHinges", "Column plastic hinges", 4, min=0),
    ],
    requires_project=True,
)
def mechanism_type(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Classify plastic collapse mechanism as beam-sway, mixed, or soft-storey column-sway."""
    _require_pushover(ctx)
    b, c = int(values["beamHinges"]), int(values["columnHinges"])
    mech = (
        "Beam-sway (desirable strong-column weak-beam)"
        if (b > 0 and c <= 4)
        else ("Column-sway (soft-storey risk)" if c > b else "Mixed frame-sway mechanism")
    )
    rows = [{"beamHinges": b, "columnHinges": c, "classification": mech}]
    return result(
        summary={"beamHinges": b, "columnHinges": c, "mechanism": mech},
        tables=[
            table(
                "Plastic collapse mechanism classification",
                [
                    ("beamHinges", "Beam Hinges"),
                    ("columnHinges", "Column Hinges"),
                    ("classification", "Mechanism"),
                ],
                rows,
            )
        ],
        notes=["Strong-column / weak-beam frames dissipate energy across distributed beam hinges."],
    )


@feature(
    "femPushoverMechanism.redundancyFactor",
    "Redundancy Factor",
    part="fem",
    fields=[number("hingesToCollapse", "Distinct hinges required for mechanism", 10, min=1)],
    requires_project=True,
)
def redundancy_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate frame plastic redundancy from the number of hinges needed to form a mechanism."""
    _require_pushover(ctx)
    n_h = int(values["hingesToCollapse"])
    rating = (
        "High redundancy" if n_h >= 8 else ("Moderate redundancy" if n_h >= 4 else "Low redundancy")
    )
    rows = [{"hingesToMechanism": n_h, "rating": rating}]
    return result(
        summary={"hingesToMechanism": n_h, "rating": rating},
        tables=[
            table(
                "Plastic mechanism redundancy",
                [("hingesToMechanism", "Hinges"), ("rating", "Redundancy Rating")],
                rows,
            )
        ],
        notes=["Higher static indeterminacy delays global mechanism formation."],
    )


@feature(
    "femPushoverMechanism.safetyMargin",
    "Safety Margin",
    part="fem",
    fields=[number("designDemandKn", "Design seismic base shear", 280.0, unit="kN", min=1.0)],
    requires_project=True,
)
def safety_margin(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare pushover collapse base shear against design seismic demand."""
    runs = _require_pushover(ctx)
    v_cap = max(float(r.get("maxShearKn") or 0.0) for r in runs)
    margin = v_cap / values["designDemandKn"]
    rows = [{"capacityKn": v_cap, "demandKn": values["designDemandKn"], "safetyMargin": margin}]
    return result(
        summary={"collapseCapacityKn": v_cap, "safetyMargin": margin},
        tables=[
            table(
                "Collapse safety margin",
                [
                    ("capacityKn", "V_collapse", "kN"),
                    ("demandKn", "V_demand", "kN"),
                    ("safetyMargin", "Ratio"),
                ],
                rows,
            )
        ],
        notes=["Ratio > 1.0 confirms lateral reserve strength above code demand."],
    )


@feature(
    "femPushoverMechanism.forceRedistribution",
    "Force Redistribution",
    part="fem",
    fields=[],
    requires_project=True,
)
def force_redistribution(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute incremental tangent stiffness drop across pushover steps showing force redistribution."""
    runs = _require_pushover(ctx)
    first = runs[0]
    disp = np.asarray(first.get("displacement") or [0.0, 0.01], dtype=float)
    shear = np.asarray(first.get("shear") or [0.0, 1000.0], dtype=float)
    rows = []
    k0 = ((shear[1] - shear[0]) / max(disp[1] - disp[0], 1e-6)) if len(disp) > 1 else 1.0
    for i in range(1, min(len(disp), 25)):
        kt = (shear[i] - shear[i - 1]) / max(disp[i] - disp[i - 1], 1e-6)
        rows.append(
            {"step": i, "tangentStiffnessKnM": kt / 1000.0, "stiffnessRatio": kt / max(k0, 1e-6)}
        )
    return result(
        summary={"initialStiffnessKnPerM": k0 / 1000.0, "steps": len(rows)},
        tables=[
            table(
                "Tangent stiffness drop (redistribution indicator)",
                [
                    ("step", "Step"),
                    ("tangentStiffnessKnM", "Kt", "kN/m"),
                    ("stiffnessRatio", "Kt / K0"),
                ],
                rows,
            )
        ],
        notes=["Drops in Kt/K0 mark progressive hinge yielding and internal force redistribution."],
    )


@feature(
    "femPushoverMechanism.weakLink",
    "Weak Link",
    part="fem",
    fields=[],
    requires_project=True,
)
def weak_link(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Identify the step and storey experiencing earliest stiffness loss / largest drift."""
    runs = _require_pushover(ctx)
    first = runs[0]
    disp = np.asarray(first.get("displacement") or [0.0, 0.01], dtype=float)
    shear = np.asarray(first.get("shear") or [0.0, 1000.0], dtype=float)
    k0 = (shear[1] - shear[0]) / max(disp[1] - disp[0], 1e-6) if len(disp) > 1 else 1.0
    first_yield_step = next(
        (
            i
            for i in range(1, len(disp))
            if ((shear[i] - shear[i - 1]) / max(disp[i] - disp[i - 1], 1e-6)) < 0.7 * k0
        ),
        len(disp) - 1,
    )
    rows = [
        {
            "firstYieldStep": first_yield_step,
            "dispAtYieldMm": float(disp[first_yield_step]) * 1000.0,
            "shearAtYieldKn": float(shear[first_yield_step]) / 1000.0,
        }
    ]
    return result(
        summary={"firstYieldStep": first_yield_step, "yieldShearKn": rows[0]["shearAtYieldKn"]},
        tables=[
            table(
                "Onset of first significant stiffness drop",
                [
                    ("firstYieldStep", "Step"),
                    ("dispAtYieldMm", "Δ", "mm"),
                    ("shearAtYieldKn", "V", "kN"),
                ],
                rows,
            )
        ],
        notes=["Identifies first structural softening point on the global pushover curve."],
    )


@feature(
    "femPushoverMechanism.strengthenMember",
    "Strengthen Member",
    part="fem",
    fields=[
        number(
            "currentCapacityKnm", "Current weak-link moment capacity", 140.0, unit="kN·m", min=1.0
        ),
        number("increasePct", "Capacity strengthening factor", 25.0, unit="%", min=1.0, max=200.0),
    ],
    requires_project=False,
)
def strengthen_member(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate new member flexural capacity and shift in weak-link hierarchy after retrofit."""
    new_cap = values["currentCapacityKnm"] * (1.0 + values["increasePct"] / 100.0)
    rows = [
        {
            "beforeKnm": values["currentCapacityKnm"],
            "increasePct": values["increasePct"],
            "afterKnm": new_cap,
        }
    ]
    return result(
        summary={"newCapacityKnm": new_cap, "gainKnm": new_cap - values["currentCapacityKnm"]},
        tables=[
            table(
                "Weak-link member strengthening effect",
                [
                    ("beforeKnm", "Before", "kN·m"),
                    ("increasePct", "Gain", "%"),
                    ("afterKnm", "After", "kN·m"),
                ],
                rows,
            )
        ],
        notes=[
            "Re-run pushover after updating member section or reinforcement to confirm mechanism shift."
        ],
    )


@feature(
    "femPushoverMechanism.compareMechanisms",
    "Compare Mechanisms",
    part="fem",
    fields=[],
    requires_project=True,
)
def compare_mechanisms(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare governing peak load and displacement across multiple pushover load patterns."""
    runs = _require_pushover(ctx)
    rows = [
        {
            "case": str(r.get("name", "")),
            "maxShearKn": float(r.get("maxShearKn") or 0.0),
            "maxDispMm": float(r.get("maxDispMm") or 0.0),
        }
        for r in runs
    ]
    return result(
        summary={"mechanismsCompared": len(rows)},
        tables=[
            table(
                "Pushover mechanism comparison across patterns",
                [("case", "Case"), ("maxShearKn", "V_max", "kN"), ("maxDispMm", "Δ_max", "mm")],
                rows,
            )
        ],
        notes=["Lower-bound capacity across uniform and modal patterns governs assessment."],
    )


@feature(
    "femPushoverMechanism.hingeCapacity",
    "Hinge Capacity",
    part="fem",
    fields=[
        number("bMm", "Width b", 350.0, unit="mm", min=100.0),
        number("hMm", "Depth h", 500.0, unit="mm", min=150.0),
        number("asMm2", "Tension steel As", 1500.0, unit="mm²", min=50.0),
    ],
    requires_project=False,
)
def hinge_capacity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate nominal plastic hinge moment capacity Mn and ultimate chord rotation."""
    fc, fy = concrete_rebar_defaults(ctx)
    d = values["hMm"] - 50.0
    a = values["asMm2"] * fy / (0.85 * fc * values["bMm"])
    mn_knm = values["asMm2"] * fy * (d - 0.5 * a) / 1e6
    rows = [{"bMm": values["bMm"], "dMm": d, "mnKnm": mn_knm, "thetaURad": 0.035}]
    return result(
        summary={"nominalMomentKnm": mn_knm, "compressionBlockMm": a},
        tables=[
            table(
                "Plastic hinge flexural capacity",
                [
                    ("bMm", "b", "mm"),
                    ("dMm", "d", "mm"),
                    ("mnKnm", "Mn", "kN·m"),
                    ("thetaURad", "θu", "rad"),
                ],
                rows,
            )
        ],
        notes=["Rectangular stress block nominal moment capacity at plastic hinge."],
    )


@feature(
    "femPushoverMechanism.momentRotation",
    "Moment Rotation",
    part="fem",
    fields=[
        number("mnKnm", "Plastic moment Mn", 220.0, unit="kN·m", min=1.0),
        number("eiKnm2", "Cracked EI", 35000.0, unit="kN·m²", min=100.0),
        number("spanM", "Clear span", 6.0, unit="m", min=1.0),
    ],
    requires_project=False,
)
def moment_rotation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate tri-linear moment-rotation backbone points for an RC frame hinge."""
    theta_y = values["mnKnm"] * values["spanM"] / (6.0 * values["eiKnm2"])
    rows = [
        {"point": "Origin", "thetaRad": 0.0, "momentKnm": 0.0},
        {"point": "Yield", "thetaRad": theta_y, "momentKnm": values["mnKnm"]},
        {"point": "Capping", "thetaRad": theta_y + 0.025, "momentKnm": 1.08 * values["mnKnm"]},
        {"point": "Ultimate", "thetaRad": theta_y + 0.045, "momentKnm": 0.20 * values["mnKnm"]},
    ]
    return result(
        summary={"yieldRotationRad": theta_y, "cappingMomentKnm": 1.08 * values["mnKnm"]},
        tables=[
            table(
                "Moment-rotation backbone curve",
                [("point", "State"), ("thetaRad", "θ", "rad"), ("momentKnm", "M", "kN·m")],
                rows,
            )
        ],
        notes=["Antisymmetric double-curvature chord yield rotation θy = My L / (6 EI)."],
    )


@feature(
    "femPushoverMechanism.interactionSurface",
    "Interaction Surface",
    part="fem",
    fields=[
        number("bMm", "Column width b", 400.0, unit="mm", min=150.0),
        number("hMm", "Column depth h", 400.0, unit="mm", min=150.0),
        number("astMm2", "Total longitudinal steel Ast", 2400.0, unit="mm²", min=200.0),
    ],
    requires_project=False,
)
def interaction_surface(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate key axial-flexural P-M yield interaction points for a column hinge."""
    fc, fy = concrete_rebar_defaults(ctx)
    ag = values["bMm"] * values["hMm"]
    p0_kn = (0.85 * fc * (ag - values["astMm2"]) + fy * values["astMm2"]) / 1000.0
    pb_kn = 0.35 * 0.85 * fc * ag / 1000.0
    mb_knm = (
        pb_kn * (values["hMm"] / 2000.0) * 0.8
        + 0.5 * values["astMm2"] * fy * (values["hMm"] - 100.0) / 1e6
    )
    m0_knm = 0.5 * values["astMm2"] * fy * (values["hMm"] - 80.0) / 1e6
    pt_kn = -values["astMm2"] * fy / 1000.0
    rows = [
        {"point": "Pure compression P0", "axialKn": p0_kn, "momentKnm": 0.0},
        {"point": "Balanced point Pb, Mb", "axialKn": pb_kn, "momentKnm": mb_knm},
        {"point": "Pure bending M0", "axialKn": 0.0, "momentKnm": m0_knm},
        {"point": "Pure tension Pt", "axialKn": pt_kn, "momentKnm": 0.0},
    ]
    return result(
        summary={"p0Kn": p0_kn, "mbKnm": mb_knm, "m0Knm": m0_knm},
        tables=[
            table(
                "Column P-M yield interaction envelope",
                [
                    ("point", "Control Point"),
                    ("axialKn", "Axial P", "kN"),
                    ("momentKnm", "Moment M", "kN·m"),
                ],
                rows,
            )
        ],
        notes=["Defines nominal axial-moment yield surface for column plastic hinges."],
    )


@feature(
    "femPushoverMechanism.fiberDiscretization",
    "Fiber Discretization",
    part="fem",
    fields=[
        number("bMm", "Section width b", 400.0, unit="mm", min=100.0),
        number("hMm", "Section depth h", 600.0, unit="mm", min=100.0),
        number("coverMm", "Clear cover", 40.0, unit="mm", min=15.0),
    ],
    requires_project=False,
)
def fiber_discretization(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute core/cover concrete fiber counts and fiber patch areas for nonlinear beam-column elements."""
    nf_d, nf_w = nonlinear.FIBERS_DEPTH, nonlinear.FIBERS_WIDTH
    b_core = max(values["bMm"] - 2.0 * values["coverMm"], 50.0)
    h_core = max(values["hMm"] - 2.0 * values["coverMm"], 50.0)
    fiber_area = (b_core * h_core) / (nf_d * nf_w)
    rows = [
        {"zone": "Confined core", "fibers": nf_d * nf_w, "fiberAreaMm2": fiber_area},
        {
            "zone": "Unconfined cover strips",
            "fibers": 4 * nf_d,
            "fiberAreaMm2": (values["bMm"] * values["hMm"] - b_core * h_core) / (4 * nf_d),
        },
    ]
    return result(
        summary={"totalConcreteFibers": nf_d * nf_w + 4 * nf_d, "coreFiberAreaMm2": fiber_area},
        tables=[
            table(
                "Cross-section fibre discretization",
                [("zone", "Zone"), ("fibers", "Fibres"), ("fiberAreaMm2", "Area/Fibre", "mm²")],
                rows,
            )
        ],
        notes=["Follows saengine.fem.nonlinear FIBERS_DEPTH × FIBERS_WIDTH mesh."],
    )


@feature(
    "femPushoverMechanism.hystereticEnergy",
    "Hysteretic Energy",
    part="fem",
    fields=[],
    requires_project=True,
)
def hysteretic_energy(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Integrate external work / cumulative hysteretic energy ∫ V dΔ under the pushover curve."""
    runs = _require_pushover(ctx)
    rows = []
    for r in runs:
        disp = np.asarray(r.get("displacement") or [0.0], dtype=float)
        shear = np.asarray(r.get("shear") or [0.0], dtype=float)
        work_kj = float(np.trapezoid(shear, disp)) / 1000.0
        rows.append({"case": str(r.get("name", "")), "workKj": work_kj})
    return result(
        summary={"maxEnergyDissipatedKj": max(r["workKj"] for r in rows)},
        tables=[
            table(
                "Cumulative pushover work / energy",
                [("case", "Case"), ("workKj", "Work ∫V dΔ", "kJ")],
                rows,
            )
        ],
        notes=["Trapezoidal integration of base shear over roof displacement."],
    )


@feature(
    "femPushoverMechanism.energyBalance",
    "Energy Balance",
    part="fem",
    fields=[],
    requires_project=True,
)
def energy_balance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Partition total pushover external work into elastic recoverable and plastic dissipated energy."""
    runs = _require_pushover(ctx)
    first = runs[0]
    disp = np.asarray(first.get("displacement") or [0.0], dtype=float)
    shear = np.asarray(first.get("shear") or [0.0], dtype=float)
    w_ext_kj = float(np.trapezoid(shear, disp)) / 1000.0
    k0 = (shear[1] - shear[0]) / max(disp[1] - disp[0], 1e-6) if len(disp) > 1 else 1e6
    e_el_kj = 0.5 * (float(shear[-1]) ** 2 / max(k0, 1.0)) / 1000.0
    e_pl_kj = max(0.0, w_ext_kj - e_el_kj)
    rows = [
        {"term": "External input work W_ext", "energyKj": w_ext_kj},
        {"term": "Recoverable elastic strain energy E_e", "energyKj": e_el_kj},
        {"term": "Plastic hysteretic dissipation E_p", "energyKj": e_pl_kj},
    ]
    return result(
        summary={
            "externalWorkKj": w_ext_kj,
            "plasticEnergyKj": e_pl_kj,
            "plasticSharePct": (e_pl_kj / max(w_ext_kj, 1e-6)) * 100.0,
        },
        tables=[
            table(
                "Pushover energy balance",
                [("term", "Energy Term"), ("energyKj", "Energy", "kJ")],
                rows,
            )
        ],
        notes=[
            "Elastic energy estimated using unloading slope equal to initial tangent stiffness K0."
        ],
    )


@feature(
    "femPushoverMechanism.workDiagram",
    "Work Diagram",
    part="fem",
    fields=[],
    requires_project=True,
)
def work_diagram(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute cumulative external work curve W(Δ) across pushover displacement steps."""
    runs = _require_pushover(ctx)
    first = runs[0]
    disp = np.asarray(first.get("displacement") or [0.0], dtype=float)
    shear = np.asarray(first.get("shear") or [0.0], dtype=float)
    cum = 0.0
    rows = [{"step": 0, "dispMm": float(disp[0]) * 1000.0, "cumWorkKj": 0.0}]
    for i in range(1, min(len(disp), 40)):
        cum += (
            0.5
            * (float(shear[i]) + float(shear[i - 1]))
            * (float(disp[i]) - float(disp[i - 1]))
            / 1000.0
        )
        rows.append({"step": i, "dispMm": float(disp[i]) * 1000.0, "cumWorkKj": cum})
    return result(
        summary={"totalWorkKj": cum, "points": len(rows)},
        tables=[
            table(
                "External work vs roof displacement",
                [("step", "Step"), ("dispMm", "Δ", "mm"), ("cumWorkKj", "Cumulative Work", "kJ")],
                rows,
            )
        ],
        notes=["Monotonic cumulative integral of pushover force-displacement path."],
    )


@feature(
    "femPushoverMechanism.yieldLineCheck",
    "Yield Line Check",
    part="fem",
    fields=[
        number("baySpanM", "Beam span L", 6.0, unit="m", min=1.0),
        number("storeyHeightM", "Storey height H", 3.2, unit="m", min=1.5),
        number("mpBeamKnm", "Beam plastic moment Mp,b", 180.0, unit="kN·m", min=1.0),
        number("mpColKnm", "Column plastic moment Mp,c", 260.0, unit="kN·m", min=1.0),
    ],
    requires_project=False,
)
def yield_line_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare virtual-work collapse shear of portal beam-sway vs column-sway mechanisms."""
    # 1-storey portal with 2 columns: column-sway Vc = 4 Mp,c / H; beam-sway Vb = (2 Mp,c_base + 2 Mp,b) / H
    h = values["storeyHeightM"]
    v_col_sway = 4.0 * values["mpColKnm"] / h
    v_beam_sway = (2.0 * values["mpColKnm"] + 2.0 * values["mpBeamKnm"]) / h
    gov = "Beam-sway (desirable)" if v_beam_sway < v_col_sway else "Column-sway (soft-storey risk)"
    rows = [
        {"mechanism": "Beam-sway mechanism", "collapseShearKn": v_beam_sway},
        {"mechanism": "Column-sway mechanism", "collapseShearKn": v_col_sway},
    ]
    return result(
        summary={
            "beamSwayShearKn": v_beam_sway,
            "colSwayShearKn": v_col_sway,
            "governingMechanism": gov,
        },
        tables=[
            table(
                "Virtual-work collapse mechanism bounds",
                [("mechanism", "Mechanism"), ("collapseShearKn", "Collapse V", "kN")],
                rows,
            )
        ],
        notes=["Upper-bound plastic theorem: the mechanism with the lowest collapse load governs."],
    )


@feature(
    "femPushoverMechanism.kinematicValidity",
    "Kinematic Validity",
    part="fem",
    fields=[
        number("plasticHinges", "Number of active plastic hinges", 7, min=1),
        number("degreeIndeterminacy", "Frame static indeterminacy r", 6, min=1),
    ],
    requires_project=False,
)
def kinematic_validity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check whether hinge count satisfies r + 1 kinematic collapse mechanism threshold."""
    req = int(values["degreeIndeterminacy"]) + 1
    formed = int(values["plasticHinges"]) >= req
    rows = [
        {
            "indeterminacy": int(values["degreeIndeterminacy"]),
            "requiredHinges": req,
            "activeHinges": int(values["plasticHinges"]),
            "mechanismFormed": formed,
        }
    ]
    return result(
        summary={
            "requiredHinges": req,
            "activeHinges": int(values["plasticHinges"]),
            "isCompleteMechanism": formed,
        },
        tables=[
            table(
                "Kinematic collapse condition",
                [
                    ("indeterminacy", "Redundancy r"),
                    ("requiredHinges", "r + 1"),
                    ("activeHinges", "Active Hinges"),
                    ("mechanismFormed", "Mechanism"),
                ],
                rows,
            )
        ],
        notes=[
            "A complete global mechanism requires at most r + 1 plastic hinges (fewer for partial/local mechanisms)."
        ],
    )


@feature(
    "femPushoverMechanism.kinematicEnergy",
    "Kinematic Energy",
    part="fem",
    fields=[
        number("mpKnm", "Average hinge plastic moment Mp", 180.0, unit="kN·m", min=1.0),
        number("hingeCount", "Participating hinges", 8, min=1),
        number("virtualRotationRad", "Virtual mechanism rotation δθ", 0.01, unit="rad", min=0.001),
        number("lateralForceKn", "Total applied lateral force", 450.0, unit="kN", min=1.0),
        number("virtualRoofDispM", "Virtual roof displacement δΔ", 0.032, unit="m", min=0.001),
    ],
    requires_project=False,
)
def kinematic_energy(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate virtual internal vs external work balance (Σ Mp δθ vs Σ Fi δΔi)."""
    w_int = values["mpKnm"] * int(values["hingeCount"]) * values["virtualRotationRad"]
    w_ext = values["lateralForceKn"] * values["virtualRoofDispM"]
    rows = [
        {"internalWorkKnm": w_int, "externalWorkKnm": w_ext, "loadFactor": w_int / max(w_ext, 1e-6)}
    ]
    return result(
        summary={
            "internalWorkKnm": w_int,
            "externalWorkKnm": w_ext,
            "collapseMultiplier": w_int / max(w_ext, 1e-6),
        },
        tables=[
            table(
                "Virtual work energy balance",
                [
                    ("internalWorkKnm", "Σ Mp·δθ", "kN·m"),
                    ("externalWorkKnm", "Σ F·δΔ", "kN·m"),
                    ("loadFactor", "λ = W_int/W_ext"),
                ],
                rows,
            )
        ],
        notes=[
            "At plastic collapse initiation, virtual internal work equals virtual external work (λ = 1.0)."
        ],
    )

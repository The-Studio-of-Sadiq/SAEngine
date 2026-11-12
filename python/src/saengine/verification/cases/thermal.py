"""Temperature benchmarks: the temperature case T (:mod:`saengine.fem.thermal`) against theory.

Each case draws its structure as a Part 5 structural model, derives the analysis model with
:func:`saengine.fem.derive.derive_fem`, adds the temperature case with
:func:`saengine.fem.thermal.add_thermal_case` (as the derivation does when Project Settings ask
for it), runs it with OpenSees Studio's runner and adds the fixed-end forces back to the
analysis forces, as the result views and the design do.

Synthetic data: C24.1 concrete of the default material library, α = 10 × 10⁻⁶ /°C.
Units: the structural model in mm, the analysis model in m, N, Pa.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from saengine.fem.display import _elements, element_section_forces
from saengine.fem.thermal import (
    CASE,
    ThermalOptions,
    ThermalSection,
    add_thermal_case,
    end_force_corrections,
    shell_force_corrections,
    shell_normal,
)
from saengine.verification.cases.common import (
    BY_ID,
    MATERIALS,
    Case,
    Outcome,
    Quantity,
    Reference,
    building,
    derive,
    fmt,
    node_at,
    objects,
    point,
    run_model,
    settings,
    structure,
)

CONCRETE = BY_ID["C24.1"]
E_C = CONCRETE.mechanical.E * 1e6  # Pa
NU_C = CONCRETE.mechanical.nu or 0.2
ALPHA = 10e-6  # 1/°C

BEAM = {
    "id": "BM",
    "name": "Beam 300x500",
    "kind": "beam",
    "material": CONCRETE.id,
    "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
}
COLUMN = {
    "id": "COL",
    "name": "Column 400x400",
    "kind": "column",
    "material": CONCRETE.id,
    "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
}
B_BM, H_BM = 0.3, 0.5
A_BM, I_BM = B_BM * H_BM, B_BM * H_BM**3 / 12
A_COL, I_COL = 0.16, 0.4**4 / 12

#: Exact element formulations (linear frames): closed forms within 1 %.
FRAME = 0.01


def _sections(project: dict[str, Any]) -> dict[int, ThermalSection]:
    """α and depth per analysis section, for the synthetic types of these cases (beams 500 mm
    deep, columns, plates)."""
    result = {}
    for s in project["sections"]:
        depth = H_BM if s["name"].startswith("BM") else None
        result[s["id"]] = ThermalSection(alpha=ALPHA, depth=depth)
    return result


def _frame_forces(project: dict[str, Any], result: Any, case: Any) -> dict[str, np.ndarray]:
    """Section forces at the stations of each frame element (analysis + fixed-end forces)."""
    fixed_end = end_force_corrections(case.corrections, CASE)
    forces = {}
    for e in _elements(project):
        end = np.asarray(result.element_forces[e.id][-1], dtype=float)[:12]
        forces[e.name] = element_section_forces(e, end + fixed_end.get(e.id, 0.0), np.zeros(3))
    return forces


def _run(project: dict[str, Any], case: Any, folder: Path) -> Any:
    _, _, results = run_model(project, folder, [case.analysis_id])
    return results[case.analysis_id]


# ─────────────────────────────── restrained beam ───────────────────────────────


def restrained_beam(folder: Path) -> Outcome:
    d_tu, d_tg = 20.0, 10.0
    model = structure(
        members=[
            {"id": "M1", "type": "BM", "start": point(0, 0, 0), "end": point(3000, 0, 0)},
            {"id": "M2", "type": "BM", "start": point(3000, 0, 0), "end": point(6000, 0, 0)},
        ],
        supports=[{"id": "S1", "at": point(0, 0, 0)}, {"id": "S2", "at": point(6000, 0, 0)}],
    )
    project = derive(building(model), objects(BEAM), MATERIALS, settings()).project
    case = add_thermal_case(
        project, _sections(project), ThermalOptions(uniform=d_tu, gradient=d_tg)
    )
    result = _run(project, case, folder)
    forces = _frame_forces(project, result, case)
    support = node_at(project, (0, 0, 0))
    reaction = float(result.node_reaction[support][-1][0])
    axial = float(np.mean([f[:, 0].mean() for f in forces.values()]))
    moment = float(np.mean([f[:, 4].mean() for f in forces.values()]))

    n_ref = -E_C * A_BM * ALPHA * d_tu
    m_ref = -E_C * I_BM * ALPHA * d_tg / H_BM
    reference = Reference(
        source="Fixed-end beam under a temperature change (e.g. Ghali, Neville & Brown, "
        "Structural Analysis: A Unified Classical and Matrix Approach, temperature effects): "
        "a member held at both ends keeps its length and stays straight",
        formula="N = -E A α ΔTu;  M = -E I α ΔTg / h (hotter top in compression);  R = -N",
        steps=[
            f"E = {fmt(E_C)} Pa, A = 0.3 × 0.5 = {fmt(A_BM)} m², I = {fmt(I_BM)} m⁴, h = 0.5 m",
            f"N = -{fmt(E_C)} × {fmt(A_BM)} × 10⁻⁵ × {d_tu:g} = {fmt(n_ref / 1e3)} kN",
            f"M = -{fmt(E_C)} × {fmt(I_BM)} × 10⁻⁵ × {d_tg:g} / 0.5 = {fmt(m_ref / 1e3)} kN·m",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Axial force (compression)", "kN", n_ref / 1e3, axial / 1e3, FRAME),
            Quantity("Bending moment (constant)", "kN·m", m_ref / 1e3, moment / 1e3, FRAME),
            Quantity("Support reaction (pushing in)", "kN", -n_ref / 1e3, reaction / 1e3, FRAME),
        ],
        notes=[
            (
                "Beam 6 m between two fixed supports, drawn as two members; ΔTu = +20 °C and "
                "ΔTg = +10 °C (top hotter): the beam is the highest horizontal member, so the "
                "roof scope applies both. The reaction is the one OpenSees reports: it includes "
                "the equivalent loads applied at the supports."
            )
        ],
    )


# ─────────────────────────────── portal frame ───────────────────────────────


def portal(folder: Path) -> Outcome:
    height, span, d_tu = 3.5, 6.0, 20.0
    model = structure(
        members=[
            {"id": "C1", "type": "COL", "start": point(0, 0, 0), "end": point(0, 0, 3500)},
            {"id": "C2", "type": "COL", "start": point(6000, 0, 0), "end": point(6000, 0, 3500)},
            {"id": "B1", "type": "BM", "start": point(0, 0, 3500), "end": point(6000, 0, 3500)},
        ],
        supports=[{"id": "S1", "at": point(0, 0, 0)}, {"id": "S2", "at": point(6000, 0, 0)}],
    )
    project = derive(building(model), objects(BEAM, COLUMN), MATERIALS, settings()).project
    case = add_thermal_case(project, _sections(project), ThermalOptions(uniform=d_tu))
    result = _run(project, case, folder)
    forces = _frame_forces(project, result, case)
    left, right = node_at(project, (0, 0, height)), node_at(project, (span, 0, height))
    sway = (result.node_disp[right][-1][0] - result.node_disp[left][-1][0]) / 2
    column = [f for name, f in forces.items() if name.startswith("C1")]
    base = abs(float(column[0][0, 4]))
    top = abs(float(column[-1][-1, 4]))
    axial = -float(np.mean([f[:, 0].mean() for n, f in forces.items() if n.startswith("B1")]))

    kc, kb = E_C * I_COL / height, E_C * I_BM / span
    theta_per_psi = 3 * kc / (2 * kc + kb)
    k_s = 6 * kc / height**2 * (2 - theta_per_psi)
    ref_sway = ALPHA * d_tu * span / (2 + k_s * span / (E_C * A_BM))
    psi = ref_sway / height
    theta = theta_per_psi * psi
    ref_v = k_s * ref_sway
    ref_top = 2 * kc * abs(2 * theta - 3 * psi)
    ref_base = 2 * kc * abs(theta - 3 * psi)
    reference = Reference(
        source="Slope-deflection method (e.g. Hibbeler, Structural Analysis, slope-deflection "
        "equations for frames with sidesway), symmetric fixed-base portal whose beam expands; "
        "Euler-Bernoulli members, the beam axially flexible, no axial force in the columns by "
        "symmetry",
        formula="M_BA = 2kc(2θ - 3ψ), M_AB = 2kc(θ - 3ψ), M_BC = 2kb θ (θ_C = -θ_B);  "
        "ΣM_B = 0;  V = (M_AB + M_BA)/H;  2Δ = α ΔT L - V L/(E A_b)",
        steps=[
            f"kc = E Ic / H = {fmt(kc)} N·m, kb = E Ib / L = {fmt(kb)} N·m",
            f"θ = 3 kc ψ / (2kc + kb) = {fmt(theta_per_psi)} ψ",
            f"V = 6kc/H² (2 - {fmt(theta_per_psi)}) Δ = {fmt(k_s)} N/m × Δ",
            (
                f"Δ = α ΔT L / (2 + {fmt(k_s)} L / (E A_b)) = {fmt(ref_sway * 1e3)} mm "
                f"(free expansion α ΔT L / 2 = {fmt(ALPHA * d_tu * span / 2 * 1e3)} mm)"
            ),
            (
                f"V = {fmt(ref_v / 1e3)} kN (beam compression), M_top = {fmt(ref_top / 1e3)} kN·m, "
                f"M_base = {fmt(ref_base / 1e3)} kN·m"
            ),
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Column top movement", "mm", ref_sway * 1e3, sway * 1e3, FRAME),
            Quantity("Beam axial force (compression)", "kN", ref_v / 1e3, axial / 1e3, FRAME),
            Quantity("Column moment at the top", "kN·m", ref_top / 1e3, top / 1e3, FRAME),
            Quantity("Column moment at the base", "kN·m", ref_base / 1e3, base / 1e3, FRAME),
        ],
        notes=[
            (
                "Columns 400 × 400 mm, 3.5 m high, 6 m apart, fixed at the base; roof beam "
                "300 × 500 mm warmed by ΔTu = +20 °C (scope: roof; the columns stay at the "
                "construction temperature)."
            )
        ],
    )


# ─────────────────────────────── slab with a gradient ───────────────────────────────


def _membrane_centre(terms: int = 199) -> float:
    """Centre value of w for ∇²w = -1 on the unit square with w = 0 on its edges (series)."""
    total = 0.0
    for m in range(1, terms + 1, 2):
        for n in range(1, terms + 1, 2):
            sign = (-1) ** ((m - 1) // 2 + (n - 1) // 2)
            total += sign * 16 / (math.pi**4 * m * n * (m**2 + n**2))
    return total


def slab_gradient(folder: Path) -> Outcome:
    side, thickness, d_tg, mesh = 4.0, 0.15, 10.0, 200  # m, m, °C, mm
    slab = {
        "id": "SL",
        "name": "Slab 150",
        "kind": "slab",
        "material": CONCRETE.id,
        "thickness": thickness * 1000,
    }
    half = side * 1000 / 2
    model = structure(
        areas=[
            {
                "id": f"P{i}{j}",
                "type": "SL",
                "outline": [
                    point(i * half, j * half, 0),
                    point((i + 1) * half, j * half, 0),
                    point((i + 1) * half, (j + 1) * half, 0),
                    point(i * half, (j + 1) * half, 0),
                ],
            }
            for i in (0, 1)
            for j in (0, 1)
        ]
    )
    project = derive(building(model), objects(slab), MATERIALS, settings(meshSize=mesh)).project
    # Hard simple supports (Kirchhoff's): held in translation and in the rotation that would
    # tilt the edge along itself (about the axis across the edge); free to turn about the edge.
    for node in project["nodes"]:
        x, y, _ = node["coords"]
        across_x = min(x, side - x) < 1e-9  # an edge x = const: hold the rotation about X
        across_y = min(y, side - y) < 1e-9
        if across_x or across_y:
            node["restraint"] = [True, True, True, across_x, across_y, False]
    case = add_thermal_case(project, _sections(project), ThermalOptions(gradient=d_tg))
    result = _run(project, case, folder)
    centre = node_at(project, (side / 2, side / 2, 0))
    rise = float(result.node_disp[centre][-1][2])
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project["nodes"]}
    add_back = shell_force_corrections(case.corrections, CASE)
    around = [e for e in project["elements"] if e.get("type") == "Shell" and centre in e["nodes"]]
    # Moments in each shell's own axes: positive about its normal, turned to "up".
    moments = [
        (
            np.asarray(result.shell_forces[e["id"]][-1], dtype=float).reshape(-1, 8).mean(axis=0)
            + add_back[e["id"]]
        )
        * float(np.sign(shell_normal([coords[n] for n in e["nodes"]])[2]))
        for e in around
    ]
    moment = float(np.mean([m[3] for m in moments] + [m[4] for m in moments]))
    shells = sum(1 for e in project["elements"] if e["type"] == "Shell")

    kappa = ALPHA * d_tg / thickness
    c = _membrane_centre()
    ref_w = c * (1 + NU_C) * kappa * side**2
    ref_m = -E_C * thickness**3 * kappa / 24
    reference = Reference(
        source="Timoshenko & Woinowsky-Krieger, Theory of Plates and Shells, bending of plates "
        "due to a temperature gradient: a simply supported plate deflects as a membrane, "
        "∇²w = -(1 + ν) κT with w = 0 on the edges, κT = α ΔTg / t; at the centre of a square, "
        "w_xx = w_yy, so Mx = My = -D (1 - ν²) κT / 2",
        formula="w_c = c (1 + ν) κT a²,  c = Σ 16 (-1)^((m+n)/2-1) / (π⁴ m n (m² + n²)) "
        "(m, n odd);  Mx = My = -E t³ κT / 24",
        steps=[
            f"κT = α ΔTg / t = 10⁻⁵ × {d_tg:g} / {thickness:g} = {fmt(kappa)} 1/m",
            f"c = {fmt(c, 5)} (series, m, n ≤ 199)",
            (
                f"w_c = {fmt(c, 5)} × {1 + NU_C:g} × {fmt(kappa)} × {side:g}² = "
                f"{fmt(ref_w * 1e3)} mm (up)"
            ),
            (
                f"Mx = My = -{fmt(E_C)} × {thickness:g}³ × {fmt(kappa)} / 24 = {fmt(ref_m)} N·m/m "
                "(top in compression)"
            ),
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Centre rise", "mm", ref_w * 1e3, rise * 1e3, 0.02),
            Quantity("Centre moment Mx = My", "N·m/m", ref_m, moment, 0.03),
        ],
        notes=[
            (
                f"Slab {side:g} m × {side:g} m × {thickness * 1000:g} mm of C24.1 (ν = {NU_C:g}) "
                f"drawn as four quarter areas, meshed at {mesh} mm ({shells} ASDShellQ4 elements); "
                "every edge node held in translation and in the rotation that would tilt the edge "
                "along itself, free to turn about the edge (hard simple supports, as Kirchhoff "
                "theory assumes; the case adds the line supports). With soft supports (all "
                "rotations free) the shear-deformable shells give about 4 % more rise and 5 % less "
                "moment, the Reissner-Mindlin boundary layer. Top face 10 °C hotter than the bottom; "
                "no uniform change. The moment is the mean over the four elements at the centre, "
                "read at their centroids, in the slab's upward axes."
            )
        ],
    )


CASES = [
    Case(
        "AT1",
        "Temperature: beam held at both ends",
        "analysis",
        "Axial force and bending moment of a fixed-end beam warmed uniformly and with its top "
        "hotter than its bottom (the temperature case T).",
        "Beam 300 × 500 mm of C24.1 (α = 10⁻⁵ /°C), 6 m between two fixed supports, drawn as "
        "two members. Temperature case: ΔTu = +20 °C, ΔTg = +10 °C through the depth.",
        restrained_beam,
    ),
    Case(
        "AT2",
        "Temperature: portal frame whose roof beam expands",
        "analysis",
        "Column bending and beam compression of a fixed-base portal frame when its roof beam "
        "warms, against the slope-deflection method.",
        "Columns 400 × 400 mm, 3.5 m high, 6 m apart, fixed bases; roof beam 300 × 500 mm; all "
        "C24.1 (α = 10⁻⁵ /°C). Temperature case: ΔTu = +20 °C on the roof beam only.",
        portal,
    ),
    Case(
        "AT3",
        "Temperature: simply supported slab with its top hotter",
        "analysis",
        "Centre rise and moments of a simply supported square slab whose top face is hotter "
        "than its bottom, against the plate theory of thermal bending.",
        "Slab 4 m × 4 m × 150 mm of C24.1 (α = 10⁻⁵ /°C) meshed into shells at 200 mm, hard "
        "simple supports on all edges. Temperature case: ΔTg = +10 °C through the thickness.",
        slab_gradient,
    ),
]

"""Seismic design from the response spectrum: scaling, member forces and drift, by hand.

The one-mass oscillator of the analysis benchmarks (a 400 × 400 column, 3 m, fixed at its base,
one mass in X at its top) runs its modal and response spectrum X cases; the equivalent static
case EX is given a known storey force at the top. :func:`saengine.fem.seismic_design.
seismic_design` then scales the response spectrum to 85 % of that base shear, finds the column
forces from the modal-force run and the design drift Cd·δ/I.
"""

from __future__ import annotations

import math
from pathlib import Path

from saengine.fem import seismic_design as sd
from saengine.fem.display import _elements
from saengine.verification.cases.analysis import E_C, I_COL, MASS, _oscillator
from saengine.verification.cases.common import (
    Case,
    G,
    Outcome,
    Quantity,
    Reference,
    fmt,
    run_model,
    settings,
)

#: Tolerance: the column is an exact elastic element; the spectrum is tabulated.
TOLERANCE = 0.01
#: The equivalent static base shear given, as a multiple of the dynamic one.
STATIC_OVER_DYNAMIC = 2.0


def scaled_column(folder: Path) -> Outcome:
    project, top, k_gross, model_dir = _oscillator(folder, False)
    # The response spectrum case is solved on its own sections (cracked lateral sections,
    # ACI 318-19 6.6.3.1.1 through the analysis settings): the column's I as it overrides it.
    rs_case = next(a for a in project["analyses"] if a["name"] == "RX: Response spectrum X")
    cracked = next(iter(rs_case.get("section_overrides") or []), {})
    ratio = float(cracked.get("Iz", I_COL)) / I_COL
    k = ratio * k_gross
    omega = math.sqrt(k / MASS)
    t = 2 * math.pi / omega
    # BNBC 2020 Part 6 2.5.4.3, on the plateau: Sa = (2/3)(Z I / R)·2.5·S·η·g, Dhaka (Z = 0.20),
    # I = 1.0, RC intermediate moment frame (R = 5, Cd = 4.5), site class SD (S = 1.35).
    sa = 2 / 3 * 0.20 * 1.0 / 5.0 * 2.5 * 1.35 * G
    v_rs = MASS * sa
    v_static = STATIC_OVER_DYNAMIC * v_rs
    pattern = next(p for p in project["load_patterns"] if p["name"] == "EX")
    pattern["nodal_loads"] = [{"node_id": top, "forces": [v_static, 0, 0, 0, 0, 0]}]
    # X only: the model keeps no RY case (a model whose RY case has no results is taken as an
    # unfinished run, and the design then uses the static cases).
    project["analyses"] = [a for a in project["analyses"] if a["name"] != "RY: Response spectrum Y"]
    ids = {a["name"]: a["id"] for a in project["analyses"]}
    model, out, _ = run_model(project, model_dir, [ids["Modal"], ids["RX: Response spectrum X"]])
    s = settings(system="rcImf")  # R = 5, Cd = 4.5, as the reference
    summary = sd.seismic_design(out, model, s)
    forces = sd.load_seismic_forces(out)
    assert forces is not None
    column = _elements(project)[0]
    base = forces.frame(column)["RX"][0]
    shear, moment = max(base[1], base[2]), max(base[4], base[5])
    drift = next(d for d in summary["drift"] if d["direction"] == "X")

    scale = 0.85 * v_static / v_rs
    u = sa / omega**2
    reference = Reference(
        source="BNBC 2020 Part 6 Sec 2.5.9.4 (p. 635): forces scaled to 0.85 V where V_rs < "
        "0.85 V, drifts not, design drifts x Cd/I (Sec 2.5.7.7); cantilever statics",
        formula="scale = 0.85 V / V_rs, V_rs = m·Sa; base shear = scale·m·Sa, base moment = "
        "scale·m·Sa·L; drift = (Cd/I)·(Sa/ω²)/h, ω² = k/m on the response spectrum case's "
        "(cracked) section",
        steps=[
            (
                f"k = 3E(rI)/L³ = 3 × {fmt(ratio)} × {fmt(E_C * I_COL)} / 3³ = {fmt(k)} N/m "
                f"(r = {fmt(ratio)}: the response spectrum case's column section), m = {MASS:g} kg, "
                f"ω = {fmt(omega)} rad/s, T = {fmt(t)} s (on the plateau)"
            ),
            f"Sa = (2/3)(0.20 × 1.0 / 5) × 2.5 × 1.35 × g = {fmt(sa)} m/s²",
            (
                f"V_rs = m·Sa = {fmt(v_rs / 1e3)} kN (one mode, all the mass); V = {fmt(v_static / 1e3)}"
                " kN given to EX"
            ),
            f"scale = 0.85 × {fmt(v_static / 1e3)} / {fmt(v_rs / 1e3)} = {fmt(scale)}",
            (
                f"base shear = {fmt(scale * v_rs / 1e3)} kN, base moment = × 3 m = "
                f"{fmt(scale * v_rs * 3 / 1e3)} kN·m"
            ),
            (
                f"u = Sa/ω² = {fmt(u * 1e3)} mm; Cd·u/I = 4.5 × u = {fmt(4.5 * u * 1e3)} mm; "
                f"drift ratio = {fmt(100 * 4.5 * u / 3.0)} %"
            ),
        ],
    )
    return Outcome(
        reference,
        [
            Quantity(
                "Dynamic base shear V_rs",
                "kN",
                v_rs / 1e3,
                summary["scale"]["vDynamic"]["x"],
                TOLERANCE,
            ),
            Quantity("Scale factor", "-", scale, summary["scale"]["x"], TOLERANCE),
            Quantity("Column base shear", "kN", scale * v_rs / 1e3, shear / 1e3, TOLERANCE),
            Quantity("Column base moment", "kN·m", scale * v_rs * 3 / 1e3, moment / 1e3, TOLERANCE),
            Quantity(
                "Design drift Cd·δ/I", "mm", 4.5 * u * 1e3, drift["designDrift"] * 1e3, TOLERANCE
            ),
        ],
        notes=[
            (
                "The derived masses are replaced by one mass in X at the top, and the static case EX "
                "by one storey force of twice the dynamic base shear, so the 85 % rule scales the "
                "forces by 1.7. The drift stays unscaled (Sec 2.5.9.4). The column has no extent "
                "across X, so the accidental torsion is zero."
            )
        ],
    )


CASES = [
    Case(
        "DQ1",
        "Response spectrum design: scaling, member forces and drift",
        "design",
        "The response spectrum of a one-mass column scaled to 85 % of the equivalent static base "
        "shear (BNBC 2020 Part 6 Sec 2.5.9.4), its base shear and moment from the modal-force "
        "run, and the design drift Cd·δ/I from the unscaled response.",
        "Column 400 × 400 mm, 3 m, fixed base, 20 t at the top in X; Dhaka, site class SD, RC "
        "IMF; V = 2·V_rs given to EX; saengine.fem.seismic_design.",
        scaled_column,
    ),
]

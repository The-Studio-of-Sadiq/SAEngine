"""RC wall benchmarks: BNBC 2020 Part 6 Sec 6.4.8 and 6.6 (pp. 935-937, 968-970) and Sec 8.3.6
(pp. 1100-1107) in :mod:`saengine.design.walls`, against hand calculations.

The walls are synthetic (f'c = 28 MPa unless stated, fy = 420 MPa, 25 mm clear cover to the
horizontal bars): no analysis is run, the forces are written in, and the references are plain
arithmetic of the code's equations, none of SAEngine's helpers used for them. Units: mm, MPa,
N, N·mm; reported in kN, kN·m, mm, mm².
"""

from __future__ import annotations

import math
from pathlib import Path

from saengine.verification.cases.common import Case, Outcome, Quantity, Reference, fmt

FC, FY = 28.0, 420.0
EXACT = 1e-3


def special_shear(_: Path) -> Outcome:
    from saengine.design import walls as w

    acv = 4000.0 * 250.0
    fc = 30.0
    rho_t = 0.0025
    cases = [("squat", 4000.0, 0.25), ("transition", 7000.0, None), ("slender", 12000.0, 0.17)]
    quantities = []
    steps = []
    for label, hw, alpha in cases:
        ratio = hw / 4000.0
        if alpha is None:
            alpha = 0.25 + (0.17 - 0.25) * (ratio - 1.5) / 0.5
        vn = acv * (alpha * math.sqrt(fc) + rho_t * FY)
        steps.append(
            f"{label}: hw/lw = {ratio:g}, αc = {fmt(alpha)}, Vn = 1e6 ({fmt(alpha)} √30 + "
            f"0.0025 x 420) = {fmt(vn / 1e3)} kN"
        )
        g = w.WallGeometry(4000.0, 250.0, hw, 3000.0)
        got = w.special_vn(g, rho_t, fc, FY)
        quantities.append(Quantity(f"αc, {label}", "", alpha, got["alpha"], EXACT))
        quantities.append(Quantity(f"Vn, {label}", "kN", vn / 1e3, got["vn"] / 1e3, EXACT))
    reference = Reference(
        source="BNBC 2020 Part 6 Sec 8.3.6.4(a), Eq. 6.8.9 (p. 1101)",
        formula="Vn = Acv (αc λ √f'c + ρt fy); αc = 0.25 (hw/lw <= 1.5), 0.17 (>= 2.0), linear "
        "between",
        steps=["lw = 4000, t = 250 mm: Acv = 1e6 mm², f'c = 30 MPa, ρt = 0.0025", *steps],
    )
    return Outcome(reference, quantities)


def ordinary_shear(_: Path) -> Outcome:
    from saengine.design import walls as w

    lw, h = 3000.0, 200.0
    d = 0.8 * lw
    nu, vu, mu = 1000e3, 500e3, 1500e6
    root = math.sqrt(FC)
    e68 = 0.27 * root * h * d + nu * d / (4 * lw)
    e69 = (0.05 * root + lw * (0.1 * root + 0.2 * nu / (lw * h)) / (mu / vu - lw / 2)) * h * d
    vc = max(0.17 * root * h * d, min(e68, e69))
    vs = 2 * math.pi * 10**2 / 4 * FY * d / 200
    vn = min(vc + vs, 0.83 * root * h * d)
    g = w.WallGeometry(lw, h, 9000.0, 3000.0)
    f = w.PierForces("C1", nu, vu, mu)
    got = w.wall_vn(g, w.WallBars(25.0, 12.0, 200.0, 10.0, 200.0, 2), f, FC, FY)
    reference = Reference(
        source="BNBC 2020 Part 6 Sec 6.4.8.4-6.4.8.9 (pp. 935-937), Eq. 6.6.68-6.6.70",
        formula="d = 0.8 lw; Vc = lesser of 0.27 λ √f'c h d + Nu d / 4lw and [0.05 λ √f'c + lw "
        "(0.1 λ √f'c + 0.2 Nu/(lw h)) / (Mu/Vu - lw/2)] h d (or 0.17 λ √f'c h d); Vs = Av fy d/s; "
        "Vn <= 0.83 √f'c h d",
        steps=[
            "lw = 3000, h = 200 mm, Nu = 1000 kN, Vu = 500 kN, Mu = 1500 kN·m, 2 layers Ø10 @ 200",
            (
                f"Eq. 6.6.68 = {fmt(e68 / 1e3)} kN, Eq. 6.6.69 = {fmt(e69 / 1e3)} kN: Vc = "
                f"{fmt(vc / 1e3)} kN"
            ),
            f"Vs = 2 x 78.54 x 420 x 2400 / 200 = {fmt(vs / 1e3)} kN; Vn = {fmt(vn / 1e3)} kN",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Vc", "kN", vc / 1e3, float(got["vc"]) / 1e3, EXACT),
            Quantity("Vs", "kN", vs / 1e3, float(got["vs"]) / 1e3, EXACT),
            Quantity("Vn", "kN", vn / 1e3, float(got["vn"]) / 1e3, EXACT),
        ],
    )


def pm_point(_: Path) -> Outcome:
    from saengine.design import walls as w

    # Bars: Ø12 pairs at y = ±459, ±275.4, ±91.8 mm (lw = 1000, cover 25, Ø10 outside).
    c = 300.0
    a = 0.85 * c
    area = 2 * math.pi * 12**2 / 4
    depths = [41.0, 224.6, 408.2, 591.8, 775.4, 959.0]
    pn = 0.85 * FC * 200 * a
    mn = pn * (500 - a / 2)
    for d in depths:
        stress = max(-FY, min(FY, 200_000 * 0.003 * (c - d) / c))
        if d < a:
            stress -= 0.85 * FC
        pn += stress * area
        mn += stress * area * (500 - d)
    g = w.WallGeometry(1000.0, 200.0, 3000.0, 3000.0)
    pier = w.PierInteraction(
        w.pier_section(g, w.WallBars(25.0, 12.0, 200.0, 10.0, 200.0, 2), FC, FY)
    )
    p, m, _ = pier.actions("M3", 1, c)
    mn2, c2 = pier.nominal(float(p[0]))
    reference = Reference(
        source="BNBC 2020 Part 6 Sec 6.3.2 (strain compatibility, rectangular stress block), "
        "as Sec 6.6.4 asks for walls",
        formula="εs = 0.003 (c - d)/c, fs = Es εs within ±fy (less 0.85 f'c in the block); C = "
        "0.85 f'c t β1 c; Pn = C + Σ As fs, Mn = C (lw/2 - a/2) + Σ As fs (lw/2 - d)",
        steps=[
            "lw = 1000, t = 200, 2 layers Ø12 @ 200 (6 pairs), f'c = 28, fy = 420, c = 300 mm",
            f"Pn = {fmt(pn / 1e3)} kN, Mn = {fmt(mn / 1e6)} kN·m",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Pn at c = 300 mm", "kN", pn / 1e3, float(p[0]) / 1e3, EXACT),
            Quantity("Mn at c = 300 mm", "kN·m", mn / 1e6, float(m[0]) / 1e6, EXACT),
            Quantity("c at Pn (inverse)", "mm", c, c2, EXACT),
            Quantity("Mn at Pn (inverse)", "kN·m", mn / 1e6, mn2 / 1e6, EXACT),
        ],
    )


def boundary_elements(_: Path) -> Outcome:
    from saengine.design import walls as w

    lw, t = 3000.0, 200.0
    trigger = lw / (600 * max(0.005, 0.007))
    stress = 1.5e6 / (lw * t) + 3e9 * (lw / 2) / (t * lw**3 / 12)
    length = max(612.0 - 0.1 * lw, 612.0 / 2)
    bc = 300.0 - 25.0
    ash = 0.09 * 100 * bc * FC / FY
    g = w.WallGeometry(lw, t, 15000.0, 3000.0)
    reference = Reference(
        source="BNBC 2020 Part 6 Sec 8.3.6.6(b)-(d) (pp. 1103-1104), Eq. 6.8.10, Eq. 6.8.8 "
        "(p. 1097)",
        formula="c >= lw / (600 max(δu/hw, 0.007)); σ = Pu/Ag + Mu (lw/2)/I > 0.2 f'c; length >= "
        "max(c - 0.1 lw, c/2); Ash >= 0.09 s bc f'c / fyt",
        steps=[
            f"lw = 3000, δu/hw = 0.005 (floored to 0.007): trigger c = {fmt(trigger)} mm",
            f"Pu = 1500 kN, Mu = 3000 kN·m, t = 200: σ = 2.5 + 10.0 = {fmt(stress)} MPa > 5.6",
            f"c = 612 mm: length >= {fmt(length)} mm",
            f"boundary 300 mm long, s = 100: Ash >= 0.09 x 100 x 275 x 28 / 420 = {fmt(ash)} mm²",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("trigger c", "mm", trigger, w.displacement_trigger(lw, 0.005), EXACT),
            Quantity("extreme stress", "MPa", stress, w.extreme_stress(g, 1.5e6, 3e9), EXACT),
            Quantity("boundary length", "mm", length, w.boundary_length(612.0, lw), EXACT),
            Quantity("Ash at s = 100", "mm²", ash, w.boundary_ash(bc, FC, FY) * 100, EXACT),
        ],
    )


def coupling_beam(_: Path) -> Outcome:
    from saengine.design import walls as w

    ln, h, bw = 1000.0, 600.0, 300.0
    alpha = math.atan(400.0 / 1000.0)
    avd = 4 * math.pi * 25**2 / 4
    vn = min(2 * avd * FY * math.sin(alpha), 0.83 * bw * h * math.sqrt(FC))
    got = w.coupling_beam_checks(
        ln, h, bw, 500e3, FC, FY, diagonal=w.Diagonal(4, 25.0, angle=alpha)
    )
    reference = Reference(
        source="BNBC 2020 Part 6 Sec 8.3.6.7(b), (d)(i), Eq. 6.8.11 (pp. 1105-1106); φ = 0.85 by "
        "Sec 6.2.3.3(c) (p. 898)",
        formula="Vn = 2 Avd fy sin α <= 0.83 Acw √f'c",
        steps=[
            (
                "ln = 1000, h = 600, bw = 300; ln/h = 1.67 < 2 and Vu = 500 kN > 0.33 Acw √28 = "
                "314.3 kN: diagonal bars required"
            ),
            (
                f"4 Ø25 per group, α = atan(400/1000) = {fmt(math.degrees(alpha))}°: Vn = "
                f"{fmt(vn / 1e3)} kN, φVn = {fmt(0.85 * vn / 1e3)} kN"
            ),
        ],
    )
    return Outcome(
        reference,
        [Quantity("φVn", "kN", 0.85 * vn / 1e3, got.checks[0]["capacity"], 1e-3)],
    )


CASES = [
    Case(
        "DV1",
        "Walls: special structural wall shear strength",
        "design",
        "Vn of a special wall with αc by hw/lw: squat, in the linear transition, slender.",
        "Wall 4000 x 250 mm, f'c = 30 MPa, ρt = 0.0025; hw = 4, 7 and 12 m; walls.special_vn.",
        special_shear,
    ),
    Case(
        "DV2",
        "Walls: ordinary wall in-plane shear",
        "design",
        "Vc by the detailed Eq. 6.6.68 / 6.6.69, Vs of the horizontal bars and the 0.83 √f'c h d "
        "limit.",
        "Wall 3000 x 200 mm, Nu = 1000 kN, Vu = 500 kN, Mu = 1500 kN·m, 2 x Ø10 @ 200; "
        "walls.wall_vn.",
        ordinary_shear,
    ),
    Case(
        "DV3",
        "Walls: a P-M point of a wall section",
        "design",
        "Pn and Mn of a wall with distributed bars at a given neutral-axis depth, and back.",
        "Wall 1000 x 200 mm, 2 layers Ø12 @ 200, c = 300 mm; walls.PierInteraction.",
        pm_point,
    ),
    Case(
        "DV4",
        "Walls: boundary elements of special walls",
        "design",
        "The displacement and stress triggers, the boundary element length and its hoops.",
        "Wall 3000 x 200 mm, δu/hw = 0.005, Pu = 1500 kN, Mu = 3000 kN·m; walls.boundary_*.",
        boundary_elements,
    ),
    Case(
        "DV5",
        "Walls: diagonally reinforced coupling beam",
        "design",
        "Vn = 2 Avd fy sin α of a short, heavily loaded coupling beam.",
        "Beam 300 x 600 mm, ln = 1000 mm, 4 Ø25 per diagonal group, Vu = 500 kN; "
        "walls.coupling_beam_checks.",
        coupling_beam,
    ),
]

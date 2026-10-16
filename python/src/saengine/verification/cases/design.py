"""Design benchmarks: SAEngine's design functions against hand calculations to ACI 318-19.

Each case calls the design function the design checks use (:mod:`saengine.design.rc`,
:mod:`saengine.design.slab`, :mod:`saengine.design.footing`) and works the same quantity out
by hand, step by step, with plain arithmetic: none of SAEngine's helpers are used for the
reference. BNBC 2020 Part 6 Chapter 6 adopts ACI 318-19, so the clauses are the same.

Units: mm, MPa, N, N·mm; reported in kN, kN·m, kN·m/m, kPa, MPa.
"""

from __future__ import annotations

import math
from pathlib import Path

from saengine.design import rc
from saengine.design import slab as slab_design
from saengine.design.footing import ColumnBase, FootingSpec, design_footing
from saengine.library.objects import (
    BarMesh,
    LinearReinforcement,
    PlanarReinforcement,
    RectangleProfile,
)
from saengine.library.settings import Foundation
from saengine.verification.cases.common import Case, Outcome, Quantity, Reference, fmt

FC, FY = 28.0, 420.0  # MPa: β1 = 0.85 at f'c = 28 MPa
ES = 200_000.0
ROOT = math.sqrt(FC)

#: Tolerance of a hand calculation the code reproduces in closed form.
EXACT = 0.005


def _area(dia: float) -> float:
    return math.pi * dia**2 / 4


# ─────────────────────────────── beam flexure ───────────────────────────────


def _beam_section(bottom: int = 3, dia: float = 20) -> rc.RcSection:
    reinforcement = LinearReinforcement.model_validate(
        {
            "material": "B420DWR",
            "cover": 40,
            "longitudinal": [{"position": "bottom", "count": bottom, "dia": dia}],
            "transverse": {"type": "stirrup", "dia": 10, "spacing": 150, "legs": 2},
        }
    )
    return rc.section_of(RectangleProfile(xDim=300, yDim=500), reinforcement, FC, FY)


def beam_flexure(_: Path) -> Outcome:
    section = _beam_section()
    result = rc.flexure(section, hogging=False)

    b, h = 300.0, 500.0
    d = h - 40 - 10 - 20 / 2
    a_s = 3 * _area(20)
    a = a_s * FY / (0.85 * FC * b)
    c = a / 0.85
    eps_t = 0.003 * (d - c) / c
    eps_ty = FY / ES
    phi = 0.90 if eps_t >= eps_ty + 0.003 else float("nan")
    mn = a_s * FY * (d - a / 2)
    reference = Reference(
        source="ACI 318-19 22.2 (rectangular stress block, 22.2.2.4.3: β1 = 0.85 for f'c <= 28 "
        "MPa) and 21.2.2 (φ by the net tensile strain); textbook procedure e.g. Wight & "
        "MacGregor, Reinforced Concrete, ch. 4",
        formula="a = As fy / (0.85 f'c b);  c = a/β1;  εt = 0.003 (d - c)/c;  Mn = As fy (d - a/2)",
        steps=[
            (
                "b × h = 300 × 500 mm, 3 Ø20 bottom, cover 40 mm to Ø10 stirrups, f'c = 28 MPa, "
                "fy = 420 MPa"
            ),
            f"d = 500 - 40 - 10 - 20/2 = {d:g} mm;  As = 3 × π 20²/4 = {fmt(a_s)} mm²",
            f"a = {fmt(a_s)} × 420 / (0.85 × 28 × 300) = {fmt(a)} mm;  c = a / 0.85 = {fmt(c)} mm",
            (
                f"εt = 0.003 ({d:g} - {fmt(c)}) / {fmt(c)} = {fmt(eps_t)} >= εty + 0.003 = "
                f"{fmt(eps_ty + 0.003)}: tension-controlled, φ = 0.90"
            ),
            f"Mn = {fmt(a_s)} × 420 × ({d:g} - {fmt(a)}/2) = {fmt(mn / 1e6)} kN·m",
            f"φMn = {fmt(phi * mn / 1e6)} kN·m",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Net tensile strain εt", "-", eps_t, result.eps_t, 0.01),
            Quantity("φ", "-", phi, result.phi, EXACT),
            Quantity("φMn", "kN·m", phi * mn / 1e6, result.phi_mn / 1e6, EXACT),
        ],
        notes=[
            (
                "SAEngine integrates the section with concreteproperties (strain compatibility); "
                "the hand calculation takes the bars at one depth, which they are."
            )
        ],
    )


# ─────────────────────────────── beam shear ───────────────────────────────


def beam_shear(_: Path) -> Outcome:
    section = _beam_section()
    with_stirrups = rc.shear(section, 10, 2, 150)
    without = rc.shear(section, None, 0, None)

    b = 300.0
    d = 500 - 40 - 10 - 10
    a_s = 3 * _area(20)
    rho = a_s / (b * d)
    av = 2 * _area(10)
    s = 150.0
    av_min = max(0.062 * ROOT, 0.35) * b * s / FY
    vc_a = 0.17 * ROOT * b * d
    vs = av * FY * d / s
    vs_max = 0.66 * ROOT * b * d
    phi_vn_a = 0.75 * (vc_a + vs)
    lam_s = math.sqrt(2 / (1 + 0.004 * d))
    vc_c = 0.66 * lam_s * rho ** (1 / 3) * ROOT * b * d
    vc_max = 0.42 * ROOT * b * d
    phi_vn_c = 0.75 * min(vc_c, vc_max)
    reference = Reference(
        source="ACI 318-19 Table 22.5.5.1 (a) and (c), 22.5.5.1.3 (size effect λs), 22.5.8.5.3 "
        "(Vs), 9.6.3.4 (Av,min), 22.5.1.2 (section limit); φ = 0.75 (21.2.1)",
        formula="Av >= Av,min: Vc = 0.17 λ √f'c bw d (a);  Av < Av,min: Vc = 0.66 λs λ "
        "ρw^(1/3) √f'c bw d (c);  Vs = Av fyt d / s;  φVn = 0.75 (Vc + Vs)",
        steps=[
            f"bw = 300 mm, d = {d:g} mm, √f'c = {fmt(ROOT)} MPa, λ = 1",
            (
                f"With Ø10 two-leg stirrups at 150: Av = {fmt(av)} mm² >= Av,min = max(0.062 √f'c, "
                f"0.35) bw s / fyt = {fmt(av_min)} mm²: expression (a)"
            ),
            f"Vc = 0.17 × {fmt(ROOT)} × 300 × {d:g} = {fmt(vc_a / 1e3)} kN",
            (
                f"Vs = {fmt(av)} × 420 × {d:g} / 150 = {fmt(vs / 1e3)} kN <= 0.66 √f'c bw d = "
                f"{fmt(vs_max / 1e3)} kN"
            ),
            f"φVn = 0.75 ({fmt(vc_a / 1e3)} + {fmt(vs / 1e3)}) = {fmt(phi_vn_a / 1e3)} kN",
            (
                f"Without stirrups: ρw = {fmt(a_s)} / (300 × {d:g}) = {fmt(rho)}, λs = √(2 / (1 + "
                f"0.004 × {d:g})) = {fmt(lam_s)}: expression (c)"
            ),
            (
                f"Vc = 0.66 × {fmt(lam_s)} × {fmt(rho)}^(1/3) × {fmt(ROOT)} × 300 × {d:g} = "
                f"{fmt(vc_c / 1e3)} kN <= 0.42 √f'c bw d = {fmt(vc_max / 1e3)} kN"
            ),
            f"φVn = 0.75 × {fmt(vc_c / 1e3)} = {fmt(phi_vn_c / 1e3)} kN",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Vc, expression (a)", "kN", vc_a / 1e3, with_stirrups.vc / 1e3, EXACT),
            Quantity("Vs", "kN", vs / 1e3, with_stirrups.vs / 1e3, EXACT),
            Quantity("φVn with stirrups", "kN", phi_vn_a / 1e3, with_stirrups.phi_vn / 1e3, EXACT),
            Quantity("Vc, expression (c)", "kN", vc_c / 1e3, without.vc / 1e3, EXACT),
            Quantity("φVn without stirrups", "kN", phi_vn_c / 1e3, without.phi_vn / 1e3, EXACT),
        ],
    )


# ─────────────────────────────── tied column ───────────────────────────────


def _column_section() -> rc.RcSection:
    reinforcement = LinearReinforcement.model_validate(
        {
            "material": "B420DWR",
            "cover": 40,
            "longitudinal": [{"position": "perimeter", "count": 8, "dia": 20}],
            "transverse": {"type": "tie", "dia": 10, "spacing": 200, "legs": 2},
        }
    )
    return rc.section_of(RectangleProfile(xDim=400, yDim=400), reinforcement, FC, FY)


def column(_: Path) -> Outcome:
    section = _column_section()
    surface = rc.InteractionSurface(section)

    h = 400.0
    a_g = h * h
    a_st = 8 * _area(20)
    p0 = 0.85 * FC * (a_g - a_st) + FY * a_st
    phi_pn_max = 0.80 * 0.65 * p0
    # Balanced point: the extreme tension bars just yield (εt = εy) when the concrete reaches
    # 0.003; φ = 0.65 (compression-controlled limit).
    d_top = 40 + 10 + 10  # bar centres 60 mm from each face
    d = h - d_top
    eps_y = FY / ES
    c = 0.003 / (0.003 + eps_y) * d
    a = 0.85 * c
    as_row = 3 * _area(20)  # three bars in each outer row, two in the middle row
    eps_top = 0.003 * (c - d_top) / c
    f_top = min(ES * eps_top, FY)
    eps_mid = 0.003 * (c - h / 2) / c
    f_mid = ES * eps_mid
    cc = 0.85 * FC * a * h
    top_force = as_row * (f_top - 0.85 * FC)  # bars inside the block displace concrete
    bottom_force = -as_row * FY
    mid_force = 2 * _area(20) * (f_mid - (0.85 * FC if h / 2 < a else 0.0))
    pnb = cc + top_force + bottom_force + mid_force
    arm = h / 2 - d_top
    mnb = cc * (h / 2 - a / 2) + top_force * arm - bottom_force * arm
    phi = 0.65
    capacity = surface.moment_capacity(phi * pnb, 0.0)
    reference = Reference(
        source="ACI 318-19 22.4.2 (P0, Table 22.4.2.1: φPn,max = 0.80 φ P0 for ties), 22.2 "
        "(strain compatibility, rectangular stress block), 21.2.2 (φ = 0.65 at εt = εy); "
        "balanced point as in Wight & MacGregor, ch. 11",
        formula="P0 = 0.85 f'c (Ag - Ast) + fy Ast;  c_b = 0.003 d / (0.003 + εy);  "
        "Pn = 0.85 f'c a b + Σ As fs;  Mn = Σ forces × lever about the centroid",
        steps=[
            (
                "400 × 400 mm, 8 Ø20 (corners and mid-sides), cover 40 mm to Ø10 ties, f'c = 28, "
                "fy = 420 MPa; bar centres 60 mm from the faces"
            ),
            (
                f"Ast = {fmt(a_st)} mm²;  P0 = 0.85 × 28 × ({a_g:g} - {fmt(a_st)}) + 420 × "
                f"{fmt(a_st)} = {fmt(p0 / 1e3)} kN"
            ),
            f"φPn,max = 0.80 × 0.65 × P0 = {fmt(phi_pn_max / 1e3)} kN",
            (
                f"Balanced: d = {d:g} mm, εy = {eps_y:g}, c = 0.003 × {d:g} / (0.003 + {eps_y:g}) = "
                f"{fmt(c)} mm, a = 0.85 c = {fmt(a)} mm"
            ),
            (
                f"Top row (3 Ø20, 60 mm): εs = {fmt(eps_top)} -> fs = {fmt(f_top)} MPa, less 0.85 "
                f"f'c displaced: {fmt(top_force / 1e3)} kN"
            ),
            (
                f"Middle row (2 Ø20 at c = h/2): εs = {fmt(eps_mid)}, force {fmt(mid_force / 1e3)} kN; "
                f"bottom row yields in tension: {fmt(bottom_force / 1e3)} kN"
            ),
            f"Concrete: 0.85 × 28 × {fmt(a)} × 400 = {fmt(cc / 1e3)} kN",
            (
                f"Pnb = {fmt(pnb / 1e3)} kN;  Mnb = {fmt(cc / 1e3)} × ({h / 2:g} - {fmt(a / 2)}) + "
                f"({fmt(top_force / 1e3)} + {fmt(-bottom_force / 1e3)}) × {arm:g} = "
                f"{fmt(mnb / 1e6)} kN·m"
            ),
            f"φ = 0.65: φPnb = {fmt(phi * pnb / 1e3)} kN, φMnb = {fmt(phi * mnb / 1e6)} kN·m",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("P0", "kN", p0 / 1e3, section.p0 / 1e3, EXACT),
            Quantity("φPn,max", "kN", phi_pn_max / 1e3, section.phi_pn_max / 1e3, EXACT),
            Quantity(
                "φMn at φPn = φPnb (balanced)", "kN·m", phi * mnb / 1e6, capacity / 1e6, EXACT
            ),
        ],
        notes=[
            (
                "rc.InteractionSurface reads the moment capacity at a given axial force from "
                "points of every meridian joined by straight chords. At the balanced point φ "
                "starts to rise above 0.65, so the φ-factored diagram has an inward corner there "
                "(and another at εt = εy + 0.003, where φ reaches 0.90). Every meridian now has a "
                "point at each corner and 11 between them; before, the chord across the balanced "
                "corner overstated φMn at φPnb by 1.1 %. The balanced point is now a computed "
                "point, so this case checks the corner itself; the chords between points, on "
                "and between meridians, are checked against exact points by "
                "tests/test_design.py (at most 0.2 % above on the meridians and 0.4 % between "
                "them)."
            ),
        ],
    )


# ─────────────────────────────── slab layer ───────────────────────────────


def slab_layer(_: Path) -> Outcome:
    h = 150.0
    reinforcement = PlanarReinforcement(
        material="B420DWR",
        cover=20,
        bottomX=BarMesh(dia=12, spacing=150),
        bottomY=BarMesh(dia=10, spacing=200),
    )
    layers = slab_design.layers_of(reinforcement, h)
    outer, inner = layers["bottomX"], layers["bottomY"]
    assert outer is not None and inner is not None
    cap_x = slab_design.layer_capacity(outer.area, outer.d, FC, FY)
    cap_y = slab_design.layer_capacity(inner.area, inner.d, FC, FY)

    rows = []
    for dia, spacing, d in ((12, 150, h - 20 - 6), (10, 200, h - 20 - 12 - 5)):
        a_s = _area(dia) * 1000 / spacing
        a = a_s * FY / (0.85 * FC * 1000)
        c = a / 0.85
        eps_t = 0.003 * (d - c) / c
        phi = 0.90 if eps_t >= FY / ES + 0.003 else float("nan")
        rows.append((dia, spacing, d, a_s, a, eps_t, phi, phi * a_s * FY * (d - a / 2)))
    steps = ["h = 150 mm, cover 20 mm; X bars outer (Ø12 @ 150), Y bars inner (Ø10 @ 200)"]
    for dia, spacing, d, a_s, a, eps_t, phi, phi_mn in rows:
        steps += [
            f"Ø{dia} @ {spacing}: As = π {dia}²/4 × 1000/{spacing} = {fmt(a_s)} mm²/m, d = {d:g} mm",
            (
                f"  a = {fmt(a_s)} × 420 / (0.85 × 28 × 1000) = {fmt(a)} mm, εt = {fmt(eps_t)}: "
                f"φ = {phi:g}"
            ),
            (
                f"  φMn = {phi:g} × {fmt(a_s)} × 420 × ({d:g} - {fmt(a)}/2) = {fmt(phi_mn / 1e6)} "
                "kN·m/m"
            ),
        ]
    reference = Reference(
        source="ACI 318-19 22.2 (rectangular stress block) per metre width of a one-way strip; "
        "21.2.2 (φ); effective depths from the cover and the bar layering",
        formula="As = Ab × 1000/s;  a = As fy / (0.85 f'c × 1000);  φMn = φ As fy (d - a/2)",
        steps=steps,
    )
    return Outcome(
        reference,
        [
            Quantity("d, bottom X (outer)", "mm", rows[0][2], outer.d, EXACT),
            Quantity("φMn, bottom X", "kN·m/m", rows[0][7] / 1e6, cap_x.phi_mn / 1e6, EXACT),
            Quantity("d, bottom Y (inner)", "mm", rows[1][2], inner.d, EXACT),
            Quantity("φMn, bottom Y", "kN·m/m", rows[1][7] / 1e6, cap_y.phi_mn / 1e6, EXACT),
        ],
    )


# ─────────────────────────────── footing ───────────────────────────────

FOOTING_L = 2400.0  # mm, square
FOOTING_H = 600.0
COVER = 75.0
BAR, SPACING = 16.0, 150.0
COLUMN_SIDE = 400.0
PU, MU = 1500e3, 150e6  # N, N·mm about the footing's v axis (eccentricity along u)
PS, MS = 1050e3, 105e6  # service
QA = 300.0  # kPa
UNIT_WEIGHT = 2400 * 9.80665 * 1e-9  # N/mm³, concrete C24.1's density
SOIL = 18.0  # kN/m³


def _footing() -> tuple[dict[str, dict], list[str]]:
    mesh = BarMesh(dia=BAR, spacing=SPACING)
    spec = FootingSpec(
        id="F1",
        type="F",
        footing_type="isolated",
        length=FOOTING_L,
        width=FOOTING_L,
        thickness=FOOTING_H,
        elevation=0.0,
        cover=COVER,
        fc=FC,
        fy=FY,
        columns=[ColumnBase("C1", 0.0, 0.0, COLUMN_SIDE, COLUMN_SIDE)],
        bottom_x=mesh,
        bottom_y=mesh,
        unit_weight=UNIT_WEIGHT,
    )
    import numpy as np

    checks, notes = design_footing(
        spec,
        {"D + L": [np.array([PS, 0.0, MS])]},
        {"1.2D + 1.6L": [np.array([PU, 0.0, MU])]},
        Foundation(allowableBearing=QA, soilUnitWeight=SOIL, groundLevel=0.0),
    )
    return {c["name"]: c for c in checks}, notes


def _footing_hand() -> dict[str, float]:
    """The hand calculation of the footing, in N, mm, MPa (pressures) and N·mm."""
    big_l, h = FOOTING_L, FOOTING_H
    area = big_l * big_l
    # ACI 318-19 2.2: d is measured to the centroid of the tension bars of the direction
    # considered. The X bars are the outer (lower) layer, the Y bars sit on them (the layering
    # SAEngine's slabs use, slab.layers_of); punching uses the mean of the two (22.6.2.1).
    d_x = h - COVER - BAR / 2
    d_y = h - COVER - BAR - BAR / 2
    d = (d_x + d_y) / 2
    r: dict[str, float] = {"d": d, "d_x": d_x, "d_y": d_y}
    # Bearing, service: footing weight (top at ground level: no soil above it).
    w_f = UNIT_WEIGHT * h  # MPa
    p_tot = PS + w_f * area
    e = MS / p_tot
    r["e"] = e
    r["q_gross"] = p_tot / area * (1 + 6 * e / big_l)
    r["overburden"] = SOIL * 1e-6 * h
    r["q_net"] = r["q_gross"] - r["overburden"]
    # Strength: the footing's weight is in the soil pressure and acts down: they cancel.
    q0 = PU / area  # MPa, mean
    slope = MU / (big_l * big_l**3 / 12)  # MPa per mm along u
    r["q0"], r["slope"] = q0, slope
    # Punching at d/2.
    b1 = COLUMN_SIDE + d
    b0 = 4 * b1
    vu = PU - q0 * b1 * b1  # the linear part cancels over the symmetric area
    gamma_v = 1 - 1 / (1 + 2 / 3 * math.sqrt(b1 / b1))
    jc = d * b1**3 / 6 + b1 * d**3 / 6 + d * b1 * b1**2 / 2
    r["b0"], r["vu_force"] = b0, vu
    r["vu"] = vu / (b0 * d) + gamma_v * MU * (b1 / 2) / jc
    lam_s = math.sqrt(2 / (1 + 0.004 * d))
    factor = min(0.33, 0.17 * (1 + 2 / 1.0), 0.083 * (2 + 40 * d / b0))
    r["lam_s"], r["factor"], r["gamma_v"], r["jc"] = lam_s, factor, gamma_v, jc
    r["phi_vc"] = 0.75 * factor * lam_s * ROOT
    a_s = _area(BAR) * 1000 / SPACING
    a = a_s * FY / (0.85 * FC * 1000)
    r["a_s"], r["a"] = a_s, a
    u1 = big_l / 2
    a_f = COLUMN_SIDE / 2
    for axis, d_axis, grade in (("x", d_x, slope), ("y", d_y, 0.0)):
        # One-way shear at d from the face, on the heavier side in X (u from c/2 + d to L/2);
        # in Y the pressure is uniform (the moment acts about Y).
        u0 = COLUMN_SIDE / 2 + d_axis
        r[f"u_shear_{axis}"] = u0
        r[f"vu_one_way_{axis}"] = big_l * (q0 * (u1 - u0) + grade * (u1**2 - u0**2) / 2)
        rho = a_s / (1000 * d_axis)
        lam = min(1.0, math.sqrt(2 / (1 + 0.004 * d_axis)))
        vc = 0.66 * lam * rho ** (1 / 3) * ROOT * big_l * d_axis
        r[f"rho_{axis}"], r[f"lam_{axis}"] = rho, lam
        r[f"phi_vc_one_way_{axis}"] = 0.75 * min(vc, 0.42 * ROOT * big_l * d_axis)
        # Flexure at the face: the soil beyond it, as a cantilever, per metre width.
        m_face = q0 * (u1 - a_f) ** 2 / 2 + grade * (
            (u1**3 - a_f**3) / 3 - a_f * (u1**2 - a_f**2) / 2
        )
        r[f"mu_face_{axis}"] = m_face * 1000  # N·mm per metre
        r[f"phi_mn_{axis}"] = 0.90 * a_s * FY * (d_axis - a / 2)
        r[f"eps_t_{axis}"] = 0.003 * (d_axis - a / 0.85) / (a / 0.85)
    return r


def footing(_: Path) -> Outcome:
    checks, _notes = _footing()
    r = _footing_hand()
    punching = checks["Punching at C1"]
    bearing = checks["Bearing (service)"]
    b0d = r["b0"] * r["d"]
    steps = [
        (
            "Square footing 2400 × 2400 × 600 mm, top at ground level, column 400 × 400 at its "
            "centre; Ø16 @ 150 both ways, X bars the outer layer, Y bars on them; cover 75 mm; "
            "f'c = 28, fy = 420 MPa; γc = 23.54 kN/m³, γsoil = 18 kN/m³, qa = 300 kPa"
        ),
        (
            f"d to the centroid of each direction's bars: dX = 600 - 75 - 16/2 = {r['d_x']:g} mm "
            f"(outer), dY = 600 - 75 - 16 - 16/2 = {r['d_y']:g} mm (inner); punching uses the "
            f"mean d = {r['d']:g} mm"
        ),
        (
            f"Service: P = 1050 kN + footing {fmt(UNIT_WEIGHT * FOOTING_H * FOOTING_L**2 / 1e3)} kN, "
            f"M = 105 kN·m: e = {fmt(r['e'])} mm < L/6 = 400 mm"
        ),
        (
            f"q_gross = P/A (1 + 6e/L) = {fmt(r['q_gross'] * 1e3)} kPa; net = gross - γ Df = "
            f"{fmt(r['q_gross'] * 1e3)} - {fmt(r['overburden'] * 1e3)} = {fmt(r['q_net'] * 1e3)} kPa"
        ),
        (
            f"Factored: Pu = 1500 kN, Mu = 150 kN·m about Y: q = {fmt(r['q0'] * 1e3)} kPa ± "
            f"{fmt(r['slope'] * 1e6)} kPa/m × x (the footing's weight cancels); uniform along Y"
        ),
        (
            f"Punching: b1 = c + d = {fmt(COLUMN_SIDE + r['d'])} mm, b0 = {fmt(r['b0'])} mm, "
            f"Vu = Pu - q0 b1² = {fmt(r['vu_force'] / 1e3)} kN, γv = {fmt(r['gamma_v'])}, "
            f"Jc = {fmt(r['jc'])} mm⁴"
        ),
        (
            f"vu = {fmt(r['vu_force'])}/({fmt(r['b0'])} × {r['d']:g}) + γv Mu (b1/2)/Jc = "
            f"{fmt(r['vu'])} MPa"
        ),
        (
            f"λs = √(2/(1 + 0.004 d)) = {fmt(r['lam_s'])}; factor = min(0.33, 0.51, "
            f"{fmt(0.083 * (2 + 40 * r['d'] / r['b0']))}) = {fmt(r['factor'])}; φvc = 0.75 × "
            f"{fmt(r['factor'])} × {fmt(r['lam_s'])} × √28 = {fmt(r['phi_vc'])} MPa"
        ),
        f"As = {fmt(r['a_s'])} mm²/m in each direction, a = As fy/(0.85 f'c 1000) = {fmt(r['a'])} mm",
    ]
    for axis in ("x", "y"):
        label, d_axis = axis.upper(), r[f"d_{axis}"]
        steps += [
            (
                f"One-way shear {label} at {fmt(r[f'u_shear_{axis}'])} mm (c/2 + d{label}) from the "
                f"centre: Vu = B ∫ q to the edge = {fmt(r[f'vu_one_way_{axis}'] / 1e3)} kN; ρw = "
                f"{fmt(r[f'rho_{axis}'])}, λs = {fmt(r[f'lam_{axis}'])}; φVc = 0.75 × 0.66 λs "
                f"ρw^(1/3) √f'c B d{label} = {fmt(r[f'phi_vc_one_way_{axis}'] / 1e3)} kN"
            ),
            (
                f"Flexure {label} at the face (200 mm from the centre): Mu = ∫ q (s - 200) ds to "
                f"the edge = {fmt(r[f'mu_face_{axis}'] / 1e6)} kN·m/m; εt = "
                f"{fmt(r[f'eps_t_{axis}'])} > 0.005, φ = 0.9: φMn = 0.9 As fy (d{label} - a/2) = "
                f"0.9 × {fmt(r['a_s'])} × 420 × ({d_axis:g} - {fmt(r['a'] / 2)}) = "
                f"{fmt(r[f'phi_mn_{axis}'] / 1e6)} kN·m/m"
            ),
        ]
    reference = Reference(
        source="ACI 318-19 2.2 (d to the centroid of the tension bars), 13.2.7 (critical "
        "sections of footings), 22.6.2.1 (two-way shear: mean d), 22.6.5.2 (with λs), 8.4.4.2 "
        "(moment transfer by eccentricity of shear, γv and Jc per R8.4.4.2.3), 22.5.5.1 "
        "(one-way shear), 22.2 (flexure); linear soil pressure q = P/A ± M/S inside the kern "
        "(e.g. Bowles, Foundation Analysis and Design)",
        formula="q = P/A (1 + 6e/L);  vu = Vu/(b0 d) + γv Mu (b1/2)/Jc;  vc = min(0.33, "
        "0.17(1 + 2/β), 0.083(2 + αs d/b0)) λs √f'c;  Vu, Mu from the soil beyond the section",
        steps=steps,
    )
    quantities = [
        Quantity(
            "Net bearing pressure (service)", "kPa", r["q_net"] * 1e3, bearing["demand"], EXACT
        ),
        Quantity("Punching shear stress vu", "MPa", r["vu"], punching["demand"] * 1e3 / b0d, EXACT),
        Quantity("Punching φvc", "MPa", r["phi_vc"], punching["capacity"] * 1e3 / b0d, EXACT),
    ]
    for axis in ("x", "y"):
        label = axis.upper()
        one_way = checks[f"One-way shear {label}"]
        flexure = checks[f"Flexure {label} (bottom)"]
        quantities += [
            Quantity(
                f"One-way shear Vu, {label}",
                "kN",
                r[f"vu_one_way_{axis}"] / 1e3,
                one_way["demand"],
                EXACT,
            ),
            Quantity(
                f"One-way shear φVc, {label}",
                "kN",
                r[f"phi_vc_one_way_{axis}"] / 1e3,
                one_way["capacity"],
                EXACT,
            ),
            Quantity(
                f"Flexure Mu at the column face, {label}",
                "kN·m/m",
                r[f"mu_face_{axis}"] / 1e6,
                flexure["demand"],
                EXACT,
            ),
            Quantity(
                f"Flexure φMn, {label} (bottom)",
                "kN·m/m",
                r[f"phi_mn_{axis}"] / 1e6,
                flexure["capacity"],
                EXACT,
            ),
        ]
    return Outcome(
        reference,
        quantities,
        notes=[
            (
                "SAEngine reports these checks rounded to 0.01 in their units; the 0.5 % tolerance "
                "covers that rounding."
            ),
            (
                "design/footing.py measures d to the centroid of the bars of the direction "
                "considered: 517 mm for the outer (X) layer and 501 mm for the inner (Y) one, for "
                "flexure and one-way shear (its notes read d = 517 and 501 mm), and the mean, "
                "509 mm, for punching (22.6.2.1). Which layer is outer is not an input of a "
                "footing: X is outer, as in SAEngine's slabs. Before this was so, one d = h - "
                "cover - largest bar diameter = 509 mm served both directions, overstating the "
                "inner layer's φMn by 1.6 %."
            ),
        ],
    )


CASES = [
    Case(
        "D1",
        "RC beam flexure (singly reinforced)",
        "design",
        "Design moment φMn of a singly reinforced rectangular beam section.",
        "Beam 300 × 500 mm, 3 Ø20 bottom, Ø10 stirrups, cover 40 mm, f'c = 28 MPa, fy = 420 "
        "MPa; rc.flexure (sagging).",
        beam_flexure,
    ),
    Case(
        "D2",
        "RC beam shear, with and without stirrups",
        "design",
        "φVn of the D1 beam by ACI 318-19 Table 22.5.5.1 expression (a) with stirrups and "
        "expression (c) (size effect) without.",
        "The D1 section; rc.shear with Ø10 two-leg stirrups at 150 mm, and without stirrups.",
        beam_shear,
    ),
    Case(
        "D3",
        "Tied column: φPn,max and the balanced point",
        "design",
        "Axial capacity limit and the balanced point of the interaction diagram of a tied "
        "square column.",
        "Column 400 × 400 mm, 8 Ø20 around the perimeter, Ø10 ties, cover 40 mm, f'c = 28, fy = "
        "420 MPa; rc.RcSection.phi_pn_max and rc.InteractionSurface (uniaxial, about x).",
        column,
    ),
    Case(
        "D4",
        "Slab layer φMn per metre",
        "design",
        "Effective depths of the two bottom layers and their design moments per metre width.",
        "Slab 150 mm, cover 20 mm, bottom X Ø12 @ 150 (outer), bottom Y Ø10 @ 200 (inner), "
        "f'c = 28, fy = 420 MPa; slab.layers_of and slab.layer_capacity.",
        slab_layer,
    ),
    Case(
        "D5",
        "Isolated footing: bearing, punching, one-way shear and flexure",
        "design",
        "Checks of an isolated square footing under an eccentric column load: service bearing "
        "with eccentricity, punching with moment transfer, and one-way shear and flexure at the "
        "column face in both directions, each with the effective depth of its own bar layer.",
        "Footing 2400 × 2400 × 600 mm, top at ground level, column 400 × 400 at its centre, Ø16 "
        "@ 150 both ways, cover 75 mm. Service D + L: 1050 kN and 105 kN·m; factored: 1500 kN "
        "and 150 kN·m, both about the footing's Y axis; qa = 300 kPa. footing.design_footing.",
        footing,
    ),
]

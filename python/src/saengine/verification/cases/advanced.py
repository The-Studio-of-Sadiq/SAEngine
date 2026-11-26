"""Advanced analysis benchmarks (issue #290): linear buckling, cables, isolators, dampers, moving
loads and a two-mass time history, each against a published closed form or a hand calculation
written out in the case.

The frame cases (AX1, AX6) run SAEngine's own pipeline (structural model -> derived OpenSees
Studio project -> runner -> results), editing the derived project only where the benchmark needs
a load or a boundary condition the pipeline does not author (each says so in its model text).
The others call the engine function that does the work in the program (the elastic catenary and
its finite element check, the isolation system's equivalent linear displacement, the dampers'
added damping, the moving load influence lines and envelopes).

Units: the structural model in mm, the analysis model in m, N, kg, s.
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from saengine.library.settings import TimeHistory
from saengine.verification.cases.analysis import BEAM as BEAM_TYPE
from saengine.verification.cases.analysis import (
    COLUMN,
    E_C,
    FRAME,
    I_BM,
    I_COL,
    newmark_average_acceleration,
)
from saengine.verification.cases.common import (
    MATERIALS,
    Case,
    G,
    Outcome,
    Quantity,
    Reference,
    building,
    derive,
    fmt,
    node_at,
    objects,
    only_pattern,
    point,
    run_model,
    settings,
    structure,
)

# ─────────────────────────────── AX1: linear buckling ───────────────────────────────

#: Members each column is drawn as: one, as an engineer draws it. The buckling model splits
#: each frame element in two (fem.buckling.SUBDIVISIONS), which puts a pin-ended column's Pcr
#: 0.75 % above Euler's; before #290 one element gave 12 EI/L², 21.6 % high.
PIECES = 1


def _column_pieces(name: str, x: float, height: float, pieces: int) -> list[dict]:
    return [
        {
            "id": f"{name}{k + 1}",
            "type": "COL",
            "start": point(x, 0, height * 1000 * k / pieces),
            "end": point(x, 0, height * 1000 * (k + 1) / pieces),
        }
        for k in range(pieces)
    ]


def _axial(results, project) -> dict[int, float]:
    """Element axial forces (tension positive) of the static case: the mean of the two ends of
    the local end forces, as the results tables hand them to the buckling analysis."""
    axial = {}
    for eid, forces in results.element_forces.items():
        end = np.asarray(forces, dtype=float).reshape(-1, 12)[-1]
        axial[int(eid)] = float((-end[0] + end[6]) / 2)
    return axial


def _pieces_of(project, prefix: str) -> list[int]:
    return [
        e["id"]
        for e in project["elements"]
        if str(e.get("name", "")).startswith(prefix) and e["type"] == "ElasticBeamColumn"
    ]


def buckling(folder: Path) -> Outcome:
    from saengine.fem.buckling import linear_buckling, member_effective_lengths

    p = 1000e3  # N on each column top
    ei_c = E_C * I_COL

    # (a) Pin-ended column, 4 m: pinned base, top held laterally (a braced column).
    length = 4.0
    model = structure(
        members=_column_pieces("P", 0, length, PIECES),
        supports=[{"id": "S1", "at": point(0, 0, 0), "fixity": "pinned"}],
    )
    d = derive(building(model), objects(COLUMN), MATERIALS, settings())
    project = d.project
    top = node_at(project, (0, 0, length))
    for node in project["nodes"]:
        if node["id"] == top:
            node["restraint"] = [True, True, False, False, False, True]
        elif node["restraint"][:3] == [True, True, True]:
            node["restraint"][5] = True  # the twist (about Z) held at the base
    only_pattern(project, nodal=[{"node_id": top, "forces": [0, 0, -p, 0, 0, 0]}])
    _, _, results = run_model(project, folder / "pinned", [1])
    found = linear_buckling(project, _axial(results[1], project), modes=2)
    pcr_pinned = found.factors[0] * p
    ref_pinned = math.pi**2 * ei_c / length**2

    # (b) Fixed-base portal, sway buckling: columns 3.2 m, beam 6 m, equal loads at the tops.
    h, span = 3.2, 6.0
    model = structure(
        members=[
            *_column_pieces("L", 0, h, PIECES),
            *_column_pieces("R", 6000, h, PIECES),
            {"id": "B1", "type": "BM", "start": point(0, 0, 3200), "end": point(6000, 0, 3200)},
        ],
        supports=[{"id": "S1", "at": point(0, 0, 0)}, {"id": "S2", "at": point(6000, 0, 0)}],
    )
    d = derive(building(model), objects(BEAM_TYPE, COLUMN), MATERIALS, settings())
    project = d.project
    left, right = node_at(project, (0, 0, h)), node_at(project, (span, 0, h))
    # Out of the frame's plane the columns are held at the beam (a braced direction), so the
    # first mode is the in-plane sway the reference describes.
    for node in project["nodes"]:
        if node["id"] in (left, right):
            node["restraint"] = [False, True, False, True, False, True]
    only_pattern(
        project,
        nodal=[{"node_id": n, "forces": [0, 0, -p, 0, 0, 0]} for n in (left, right)],
    )
    _, _, results = run_model(project, folder / "portal", [1])
    found = linear_buckling(project, _axial(results[1], project), modes=2)
    pcr_portal = found.factors[0] * p
    rows = member_effective_lengths(found, [("L", _pieces_of(project, "L"))])
    k_portal = rows[0]["Kmajor"] if rows else math.nan

    # Alignment chart, sway frame (AISC 360-16 Commentary Appendix 7, Eq C-A-7-2): with the
    # base fixed (G_B = 0) it reduces to x / tan x = -6 / G_A, x = π / K.
    g_a = (I_COL / h) / (I_BM / span)

    def residual(x: float) -> float:
        return x / math.tan(x) + 6 / g_a

    lo, hi = math.pi / 2 + 1e-9, math.pi - 1e-9  # K between 1 and 2
    for _ in range(200):
        mid = (lo + hi) / 2
        if residual(lo) * residual(mid) <= 0:
            hi = mid
        else:
            lo = mid
    x = (lo + hi) / 2
    k_ref = math.pi / x
    ref_portal = math.pi**2 * ei_c / (k_ref * h) ** 2

    reference = Reference(
        source="Euler column (Timoshenko & Gere, Theory of Elastic Stability, 2nd ed., 1961, "
        "Art. 2.1-2.2); sway-frame alignment chart, exact for a symmetric portal with equal "
        "column loads (AISC 360-16 Specification Commentary, Appendix 7, Eq C-A-7-2; "
        "Galambos ed., Guide to Stability Design Criteria for Metal Structures, 5th ed., 1998, "
        "Sec 15.2)",
        formula="Pcr = π²EI/(KL)²; pinned: K = 1; sway portal: (G_A G_B (π/K)² − 36) / "
        "(6 (G_A + G_B)) = (π/K) / tan(π/K), G_B = 0 (fixed): (π/K)/tan(π/K) = −6/G_A",
        steps=[
            f"Column 400 × 400 of C24.1: EI = {fmt(E_C)} × {fmt(I_COL)} = {fmt(ei_c)} N·m²",
            f"(a) L = {length:g} m: Pcr = π² × {fmt(ei_c)} / 4² = {fmt(ref_pinned / 1e3)} kN",
            (
                f"(b) G_A = (Ic/Lc)/(Ib/Lb) = ({fmt(I_COL)}/3.2) / ({fmt(I_BM)}/6) = {fmt(g_a)} "
                "(one beam, one column at the top joint)"
            ),
            (
                f"x/tan x = −6/{fmt(g_a)} = {fmt(-6 / g_a)}: x = {fmt(x, 6)} (bisection), "
                f"K = π/x = {fmt(k_ref)}"
            ),
            f"Pcr = π² EI / (K × 3.2)² = {fmt(ref_portal / 1e3)} kN per column",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Pin-ended column Pcr", "kN", ref_pinned / 1e3, pcr_pinned / 1e3, FRAME),
            Quantity("Sway portal Pcr per column", "kN", ref_portal / 1e3, pcr_portal / 1e3, FRAME),
            Quantity("Sway portal column K", "-", k_ref, k_portal, FRAME),
        ],
        notes=[
            (
                "Each column is drawn as one member. The buckling model splits every frame "
                "element in two; with one cubic element per member it overestimated a pin-ended "
                "column's Pcr by 21.6 % (12 EI/L² for π² EI/L²), fixed with this case (#290). "
                "Two elements leave 0.75 % above Euler, inside the 1 % tolerance."
            ),
            (
                "Loads: one 1000 kN load down on each column top (the self-weight replaced). The "
                "pinned column's top is held laterally and its base and top against twist; the "
                "portal's beam joints are held out of the frame's plane."
            ),
            (
                "The reference neglects axial shortening; the analysis keeps it (the beam "
                "carries almost no axial force under the joint loads)."
            ),
        ],
    )


# ─────────────────────────────── AX2: cable under self-weight ───────────────────────────────


def _catenary_point(s: float, h_force: float, v: float, w: float, ea: float) -> tuple[float, float]:
    """x(s), z(s) of Irvine's elastic catenary (Cable Structures, 1981, Eqs 1.30-1.31 form for
    a cable from A = (0, 0); s the unstressed arc length from A, V the upward reaction at A)."""
    x = h_force * s / ea + h_force / w * (
        math.asinh((w * s - v) / h_force) + math.asinh(v / h_force)
    )
    z = (w * s * s / 2 - v * s) / ea + h_force / w * (
        math.sqrt(1 + ((w * s - v) / h_force) ** 2) - math.sqrt(1 + (v / h_force) ** 2)
    )
    return x, z


def cable(folder: Path) -> Outcome:
    from saengine.fem.cables import cable_fe, elastic_catenary

    # A 40 mm spiral strand: EA = 160 GPa × 1.0e-3 m², w = 100 N/m, unstressed length 101 m.
    ea, w, l0 = 160e9 * 1.0e-3, 100.0, 101.0
    # The reference runs the closed form forwards: take H, find the span it hangs over.
    h_ref = 5000.0  # N
    # (a) level supports: symmetric, V = w L0 / 2.
    va = w * l0 / 2
    span, rise = _catenary_point(l0, h_ref, va, w, ea)
    sag_ref = -_catenary_point(l0 / 2, h_ref, va, w, ea)[1]
    t_ref = math.hypot(h_ref, va)
    flat = elastic_catenary(span, 0.0, w, ea, l0)
    fe = cable_fe(span, 0.0, w, ea, l0, segments=40)

    # (b) inclined chord: H and V at A chosen, B found.
    h_b, v_b = 8000.0, 3000.0
    span_b, rise_b = _catenary_point(l0, h_b, v_b, w, ea)
    tb_ref = math.hypot(h_b, w * l0 - v_b)
    inclined = elastic_catenary(span_b, rise_b, w, ea, l0)

    reference = Reference(
        source="Irvine, Cable Structures, MIT Press 1981, Ch 1 (Sec 1.3, the elastic catenary, "
        "Lagrangian form)",
        formula="x(s) = Hs/EA + (H/w)[asinh((ws − V)/H) + asinh(V/H)];  "
        "z(s) = (ws²/2 − Vs)/EA + (H/w)[√(1 + ((ws − V)/H)²) − √(1 + (V/H)²)];  "
        "T = √(H² + V²)",
        steps=[
            f"EA = {fmt(ea)} N, w = {w:g} N/m, L0 = {l0:g} m (unstressed)",
            (
                f"(a) H = {h_ref:g} N, V = wL0/2 = {fmt(va)} N: span l = x(L0) = {fmt(span, 6)} m, "
                f"z(L0) = {fmt(rise)} m (level)"
            ),
            f"sag = −z(L0/2) = {fmt(sag_ref, 5)} m, T_max = √(H² + V²) = {fmt(t_ref)} N",
            (
                f"(b) H = {h_b:g} N, V_A = {v_b:g} N: B at ({fmt(span_b, 6)}, {fmt(rise_b, 6)}) m, "
                f"V_B = wL0 − V_A = {fmt(w * l0 - v_b)} N, T_B = {fmt(tb_ref)} N"
            ),
            "SAEngine is given the span, rise, w, EA and L0 and solves for H and V.",
        ],
    )
    tol = 0.005
    return Outcome(
        reference,
        [
            Quantity("Level: H (closed form)", "kN", h_ref / 1e3, flat.H / 1e3, tol),
            Quantity("Level: mid-span sag (closed form)", "m", sag_ref, flat.sag, tol),
            Quantity(
                "Level: end tension (closed form)", "kN", t_ref / 1e3, flat.tensionA / 1e3, tol
            ),
            Quantity("Level: H (40 cable elements)", "kN", h_ref / 1e3, fe["H"] / 1e3, 0.01),
            Quantity("Level: sag (40 cable elements)", "m", sag_ref, fe["sag"], 0.01),
            Quantity("Inclined: H", "kN", h_b / 1e3, inclined.H / 1e3, tol),
            Quantity("Inclined: V at A", "kN", v_b / 1e3, inclined.Va / 1e3, tol),
            Quantity("Inclined: tension at B", "kN", tb_ref / 1e3, inclined.tensionB / 1e3, tol),
        ],
        notes=[
            (
                "The finite element cable (co-rotational tension-only trusses in OpenSees, "
                "the weight lumped at the nodes) is held to 1 %: the chord of each of its 40 "
                "segments cuts the curve."
            )
        ],
    )


# ─────────────────────────────── AX3: isolation system ───────────────────────────────


def isolators(folder: Path) -> Outcome:
    from saengine.fem.isolation import Curve, solve_displacement, system_damping, system_stiffness

    # Four lead-rubber bearings under an 8000 kN building, site class SD, Dhaka (Z = 0.20).
    qd, kd, dy = 60e3, 0.8e6, 0.010  # N, N/m, m per unit
    units = 4
    weight = 8000e3
    z, site = 0.20, "SD"
    curves = [Curve(qd, kd, dy)] * units
    found = solve_displacement(curves, weight, site, z)

    # Hand: bilinear secant stiffness and loop damping (Naeim & Kelly), Eq 6.2.62 with Sa from
    # Eqs 6.2.34 and 6.2.35d (T > TD), R = I = 1, η = 1: Sa T² is then constant, so
    # D = (2/3) Z × 2.5 S TC TD × g / (4π² B) and only B depends on D.
    s_soil, tc, td = 1.35, 0.8, 2.0
    table = [(2, 0.8), (5, 1.0), (10, 1.2), (20, 1.5), (30, 1.7), (40, 1.9), (50, 2.0)]

    def b_of(beta_pct: float) -> float:
        if beta_pct <= table[0][0]:
            return table[0][1]
        for (b0, v0), (b1, v1) in itertools.pairwise(table):
            if beta_pct <= b1:
                return v0 + (v1 - v0) * (beta_pct - b0) / (b1 - b0)
        return table[-1][1]

    def k_eff(d: float) -> float:
        return units * (qd + kd * d) / d

    def beta(d: float) -> float:
        return units * 4 * qd * (d - dy) / (2 * math.pi * k_eff(d) * d * d)

    numerator = 2 / 3 * z * 2.5 * s_soil * tc * td * G / (4 * math.pi**2)
    lo, hi = 0.02, 1.0
    for _ in range(200):  # D − numerator / B(β(D)) = 0 by bisection
        mid = (lo + hi) / 2
        if (lo - numerator / b_of(100 * beta(lo))) * (mid - numerator / b_of(100 * beta(mid))) <= 0:
            hi = mid
        else:
            lo = mid
    d_ref = (lo + hi) / 2
    k_ref = k_eff(d_ref)
    beta_ref = beta(d_ref)
    t_ref = 2 * math.pi * math.sqrt(weight / (k_ref * G))
    assert t_ref > td  # the 6.2.35d branch

    # The secant stiffness and damping at a given displacement (no iteration): 150 mm.
    d150 = 0.150
    reference = Reference(
        source="Bilinear isolator, effective stiffness and damping: Naeim & Kelly, Design of "
        "Seismic Isolated Structures, Wiley 1999, Ch 4 (keff = Kd + Qd/D, "
        "βeff = 4Qd(D − Dy)/(2π keff D²)); BNBC 2020 Part 6 Sec 2.5.16, Eq 6.2.62-6.2.63 "
        "(p. 661) and Table 6.2.24 (p. 662); design spectrum Eqs 6.2.34-6.2.35 (p. 615)",
        formula="D = Sa g T² / (4π² B), T = 2π√(W/(k g)); for T > TD: Sa = (2/3) Z · 2.5 S η "
        "TC TD / T², so D = (2/3) Z · 2.5 S TC TD g / (4π² B(β(D)))",
        steps=[
            (
                f"{units} units, each Qd = {qd / 1e3:g} kN, Kd = {kd / 1e3:g} kN/m, Dy = "
                f"{dy * 1e3:g} mm; W = {weight / 1e3:g} kN; Z = {z:g}, site SD: S = 1.35, "
                "TC = 0.8 s, TD = 2.0 s"
            ),
            f"(2/3) × 0.20 × 2.5 × 1.35 × 0.8 × 2.0 × g / (4π²) = {fmt(numerator)} m (B = 1)",
            (
                "B: linear interpolation of Table 6.2.24 (2 %: 0.8, 5 %: 1.0, 10 %: 1.2, 20 %: 1.5, "
                "30 %: 1.7, 40 %: 1.9, 50 %: 2.0)"
            ),
            (
                f"Bisection on D: D = {fmt(d_ref * 1e3)} mm, k = {fmt(k_ref / 1e3)} kN/m, "
                f"β = {fmt(100 * beta_ref)} %, B = {fmt(b_of(100 * beta_ref))}, T = {fmt(t_ref)} s "
                "(> TD)"
            ),
            (
                f"At D = 150 mm: keff = 4 × ({qd / 1e3:g} + {kd / 1e3:g} × 0.15)/0.15 = "
                f"{fmt(k_eff(d150) / 1e3)} kN/m, βeff = {fmt(100 * beta(d150))} %"
            ),
        ],
    )
    return Outcome(
        reference,
        [
            Quantity(
                "keff at 150 mm",
                "kN/m",
                k_eff(d150) / 1e3,
                system_stiffness(curves, d150) / 1e3,
                0.001,
            ),
            Quantity(
                "βeff at 150 mm", "%", 100 * beta(d150), 100 * system_damping(curves, d150), 0.001
            ),
            Quantity("Design displacement D", "mm", d_ref * 1e3, found["D"] * 1e3, 0.005),
            Quantity("Effective period TD", "s", t_ref, found["T"], 0.005),
            Quantity("Effective damping βD", "%", 100 * beta_ref, 100 * found["beta"], 0.005),
        ],
        notes=[
            (
                "The equivalent linear procedure of the code is compared (the iteration on k "
                "and β). The isolators' nonlinear time history (Bouc-Wen bearings in the "
                "fibre model) needs the full nonlinear history model and is not in this case."
            )
        ],
    )


# ─────────────────────────────── AX4: viscous dampers ───────────────────────────────


def dampers(folder: Path) -> Outcome:
    from saengine.fem.dampers import DamperBrace, added_damping, modal_values

    # One storey: 3.5 m high, bay 6 m, seismic weight 2000 kN, lateral stiffness 40 MN/m; one
    # diagonal damper brace from the base of one column to the top of the other.
    h, bay, weight, k = 3.5, 6.0, 2000e3, 40e6
    m = weight / G
    omega = math.sqrt(k / m)
    period = 2 * math.pi / omega
    roof = 0.050
    cos = bay / math.hypot(bay, h)

    def brace(kind_c: float, alpha: float) -> DamperBrace:
        spec = SimpleNamespace(kind="viscous", coefficient=kind_c, exponent=alpha)
        return DamperBrace("D1", "DMP", spec, np.array([0.0, 0, 0]), np.array([bay, 0, h]))

    levels = [(0.0, 0.0), (h, weight)]
    mode = modal_values(levels)
    c_lin = 500.0  # kN·s/m
    beta_lin = added_damping([brace(c_lin, 1.0)], "X", mode, roof, period)
    ref_lin = c_lin * 1e3 * cos**2 / (2 * m * omega)

    # Nonlinear α = 0.5: E = λ C ω^α (δ cos)^(1+α), λ = 2^(2+α) Γ²(1+α/2)/Γ(2+α);
    # ζ = E / (4π · ½ k D²).
    c_nl, alpha = 300.0, 0.5  # kN·(s/m)^0.5
    beta_nl = added_damping([brace(c_nl, alpha)], "X", mode, roof, period)
    lam = 2 ** (2 + alpha) * math.gamma(1 + alpha / 2) ** 2 / math.gamma(2 + alpha)
    energy = lam * c_nl * 1e3 * omega**alpha * (roof * cos) ** (1 + alpha)
    ref_nl = energy / (4 * math.pi * 0.5 * k * roof**2)

    reference = Reference(
        source="Chopra, Dynamics of Structures, 5th ed., Pearson 2017, Sec 2.2 (ζ = c/(2mωn)) "
        "and Sec 3.8 (energy per cycle of viscous damping); nonlinear dampers: Christopoulos & "
        "Filiatrault, Principles of Passive Supplemental Damping and Seismic Isolation, IUSS "
        "Press 2006, Ch 5 (λ of F = C v^α under harmonic motion)",
        formula="linear brace at angle θ: ζ = C cos²θ / (2 m ω);  ζ = Σ E_D / (4π E_S), "
        "E_D = λ C ω^α (D cos θ)^(1+α), E_S = ½ k D²",
        steps=[
            f"m = W/g = {fmt(m)} kg, k = {fmt(k)} N/m, ω = {fmt(omega)} rad/s, T = {fmt(period)} s",
            f"cos θ = 6/√(6² + 3.5²) = {fmt(cos)}; roof displacement D = {roof * 1e3:g} mm",
            (
                f"Linear, C = {c_lin:g} kN·s/m: ζ = {fmt(c_lin * 1e3)} × {fmt(cos**2)} / (2 × "
                f"{fmt(m)} × {fmt(omega)}) = {fmt(100 * ref_lin)} %"
            ),
            (
                f"α = 0.5, C = {c_nl:g} kN·(s/m)^0.5: λ = 2^2.5 Γ²(1.25)/Γ(2.5) = {fmt(lam)}, "
                f"E_D = {fmt(energy)} J, E_S = {fmt(0.5 * k * roof**2)} J, ζ = {fmt(100 * ref_nl)} %"
            ),
        ],
    )
    tol = 0.001
    return Outcome(
        reference,
        [
            Quantity("Added damping, linear damper", "%", 100 * ref_lin, 100 * beta_lin, tol),
            Quantity("Added damping, α = 0.5 damper", "%", 100 * ref_nl, 100 * beta_nl, tol),
        ],
        notes=[
            (
                "One storey with its whole weight at the roof: the fundamental mode φ = h/hr "
                "is exact, so the code's βV equals the single-degree-of-freedom damping ratio."
            )
        ],
    )


# ─────────────────────────────── AX5: moving loads ───────────────────────────────


def moving_loads(folder: Path) -> Outcome:
    from saengine.special.moving_loads import lane_extremes, line_influence

    span = 20.0
    il = line_influence([span])
    mid = int(np.argmin(np.abs(il.x - span / 2)))
    peak_ordinate = float(il.moment[mid].max())

    # HL-93 design truck 35 / 145 / 145 kN, rear spacing 4.3-9.0 m (AASHTO LRFD Art 3.6.1.2.2),
    # design lane 9.3 kN/m (3.6.1.2.4), dynamic allowance 33 % on the truck (3.6.2.1).
    axles = [
        SimpleNamespace(load=35.0, spacing=0.0, spacingMax=None),
        SimpleNamespace(load=145.0, spacing=4.3, spacingMax=None),
        SimpleNamespace(load=145.0, spacing=4.3, spacingMax=9.0),
    ]
    table = SimpleNamespace(vehicles={"HL93": SimpleNamespace(axles=axles)})
    loading = SimpleNamespace(
        vehicle="HL93",
        vehicleFactor=1.0,
        secondGap=None,
        dynamic=True,
        lineLoad=9.3,
        areaLoad=0.0,
        lineFactor=1.0,
    )
    im = 1.33
    at_mid = lane_extremes(il.x, il.moment[mid], il.moment[mid], loading, table, im, 3.6)
    truck_only = SimpleNamespace(**{**vars(loading), "lineLoad": 0.0, "dynamic": False})
    absolute = max(
        lane_extremes(il.x, il.moment[s], il.moment[s], truck_only, table, im, 3.6).high
        for s in range(len(il.x))
    )

    # Two equal spans: hogging moment at the middle support, unit load at a in span 1:
    # M_B = −a (L² − a²) / (4 L²), least at a = L/√3: −L / (6√3).
    two = line_influence([span / 2, span / 2])
    support = two.supports[1]
    hog = float(two.moment[support].min())
    ref_hog = -(span / 2) / (6 * math.sqrt(3))

    # Hand: midspan ordinate L/4; truck at midspan, middle axle on it (rear spacing 4.3 m):
    y = span / 4
    y43 = y * (span / 2 - 4.3) / (span / 2)
    m_truck = 145 * y + 145 * y43 + 35 * y43
    m_lane = 9.3 * span**2 / 8
    ref_mid = im * m_truck + m_lane
    # Absolute maximum (Barré): mid-span bisects the middle axle and the resultant.
    resultant = 325.0
    e = (145 * 4.3 + 145 * 8.6) / resultant - 4.3  # resultant behind the middle axle
    x0 = span / 2 + e / 2  # the middle axle, the resultant on the rear axle's side
    ra = resultant * (span - (x0 - e)) / span
    m_abs = ra * x0 - 145 * 4.3  # the rear axle (145 kN) between A and the middle axle

    reference = Reference(
        source="Influence lines (Müller-Breslau; Hibbeler, Structural Analysis, 10th ed., "
        "2018, Ch 6), Barré's absolute maximum moment of a moving load group; HL-93 truck and "
        "lane load and IM = 33 % of AASHTO LRFD Bridge Design Specifications, 9th ed., 2020, "
        "Art 3.6.1.2.2, 3.6.1.2.4, 3.6.2.1",
        formula="IL of M at mid-span: peak L/4; M = (1 + IM) Σ P y + w × area; two spans: "
        "M_B(a) = −a(L² − a²)/(4L²), min −L/(6√3) at a = L/√3; Barré: M_max = R_A x0 − Σ P "
        "lever, x0 = L/2 + e/2",
        steps=[
            f"Simple span L = {span:g} m: ordinate at mid-span L/4 = {fmt(y)} m",
            (
                f"Truck middle axle at mid-span: 145 × {fmt(y)} + (145 + 35) × {fmt(y43)} = "
                f"{fmt(m_truck)} kN·m (the 4.3 m rear spacing governs)"
            ),
            (
                f"Lane: 9.3 × 20²/8 = {fmt(m_lane)} kN·m; total 1.33 × {fmt(m_truck)} + "
                f"{fmt(m_lane)} = {fmt(ref_mid)} kN·m"
            ),
            (
                f"Barré: R = 325 kN, e = {fmt(e)} m behind the middle axle, x0 = {fmt(x0)} m, "
                f"R_A = {fmt(ra)} kN, M = R_A x0 − 145 × 4.3 = {fmt(m_abs)} kN·m (truck alone)"
            ),
            f"Two spans of {span / 2:g} m: M_B,min = −10/(6√3) = {fmt(ref_hog)} kN·m per kN",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Mid-span moment influence ordinate", "kN·m/kN", y, peak_ordinate, 0.001),
            Quantity("Mid-span moment, truck × 1.33 + lane", "kN·m", ref_mid, at_mid.high, 0.005),
            Quantity("Absolute max moment, truck alone", "kN·m", m_abs, absolute, 0.005),
            Quantity("Two spans: least support moment ordinate", "kN·m/kN", ref_hog, hog, 0.005),
        ],
        notes=[
            (
                "The lane's effect is computed as SAEngine's envelope does for one loaded "
                "lane: the truck's variable rear spacing tried in 0.5 m steps, moved both ways "
                "along the influence line; no multiple presence factor (one lane)."
            ),
            (
                "Absolute maximum: the largest over the 0.5 m stations of the influence lines; "
                "Barré's point falls between stations (at most 0.1 % lower)."
            ),
        ],
    )


# ─────────────────────────────── AX6: two-mass time history ───────────────────────────────

MASS2 = 15_000.0  # kg at each level
DT2 = 0.005
TH_S = 4.0
#: The ground motion: two sines near the two modes' frequencies, in g.
WAVES = ((0.15, 1.3), (0.10, 9.0))


def two_mass_history(folder: Path) -> Outcome:
    height = 6.0
    record = folder / "02 Project Settings" / "records" / "two-sines.txt"
    record.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(0, TH_S + DT2 / 2, DT2)
    a = sum(amp * np.sin(2 * math.pi * f * t) for amp, f in WAVES)
    record.write_text("\n".join(f"{ti:.4f} {ai:.6f}" for ti, ai in zip(t, a, strict=True)) + "\n")
    model = structure(
        members=[
            {"id": "C1", "type": "COL", "start": point(0, 0, 0), "end": point(0, 0, 3000)},
            {"id": "C2", "type": "COL", "start": point(0, 0, 3000), "end": point(0, 0, 6000)},
        ],
        supports=[{"id": "S1", "at": point(0, 0, 0)}],
    )
    model_dir = folder / "08 FEM"
    model_dir.mkdir(parents=True, exist_ok=True)
    history = TimeHistory(
        name="Two sines", record="02 Project Settings/records/two-sines.txt", direction="X"
    )
    d = derive(
        building(model),
        objects(COLUMN),
        MATERIALS,
        settings(timeHistories=[history], system="rcImf"),
        None,
        model_dir,
    )
    project = d.project
    n1, n2 = node_at(project, (0, 0, 3.0)), node_at(project, (0, 0, height))
    for node in project["nodes"]:
        node["mass"] = [MASS2, 0, 0, 0, 0, 0] if node["id"] in (n1, n2) else [0.0] * 6
    th = next(an for an in project["analyses"] if an["type"] == "Transient")
    _, _, results = run_model(project, model_dir, [th["id"]])
    u1 = results[th["id"]].node_disp_history(n1)[:, 0]
    u2 = results[th["id"]].node_disp_history(n2)[:, 0]

    # Reference: the cantilever's flexibility at the two masses (beam tables), its inverse the
    # 2 × 2 lateral stiffness (rotations condensed), modes in closed form, each mode
    # integrated on its own (Newmark average acceleration, as the runner) and superposed.
    ei = E_C * I_COL
    a1, a2 = 3.0, height
    f11 = a1**3 / (3 * ei)
    f22 = a2**3 / (3 * ei)
    f12 = a1**2 * (3 * a2 - a1) / (6 * ei)
    det = f11 * f22 - f12**2
    k11, k22, k12 = f22 / det, f11 / det, -f12 / det
    m = MASS2
    # det(K − ω² m I) = 0: ω² = [(k11 + k22) ∓ √((k11 − k22)² + 4 k12²)] / (2m)
    root = math.sqrt((k11 - k22) ** 2 + 4 * k12**2)
    w2 = [((k11 + k22) - root) / (2 * m), ((k11 + k22) + root) / (2 * m)]
    omegas = [math.sqrt(v) for v in w2]
    # Mode shapes φ = [1, (ω² m − k11)/k12]
    shapes = [np.array([1.0, (v * m - k11) / k12]) for v in w2]
    ground = a * G
    ground = np.append(ground, 0.0)  # the runner steps one interval past the record's end
    ref_u = np.zeros((len(ground), 2))
    zetas = []
    for omega, phi in zip(omegas, shapes, strict=True):
        mn = m * float(phi @ phi)
        gamma = m * float(phi.sum()) / mn
        zeta = 0.05 * omega / omegas[0]  # stiffness-proportional: 5 % in mode 1
        zetas.append(zeta)
        q = newmark_average_acceleration(1.0, omega**2, zeta, gamma * ground, DT2)
        ref_u += np.outer(q, phi)
    ref1, ref2 = float(np.max(np.abs(ref_u[:, 0]))), float(np.max(np.abs(ref_u[:, 1])))
    # Time of the roof's peak (the histories line up step by step).
    reference = Reference(
        source="Modal superposition of a classically damped two-degree-of-freedom system "
        "(Chopra, Dynamics of Structures, 5th ed., 2017, Ch 12-13); cantilever flexibility "
        "coefficients from beam tables; each mode by Newmark's average acceleration "
        "(Chopra Table 5.4.2)",
        formula="F: f11 = a³/3EI, f22 = L³/3EI, f12 = a²(3L − a)/6EI; K = F⁻¹; "
        "ω² = [(k11 + k22) ∓ √((k11 − k22)² + 4k12²)]/(2m); q̈n + 2ζnωn q̇n + ωn² qn = −Γn üg; "
        "u = Σ φn qn",
        steps=[
            f"Column 400 × 400, EI = {fmt(ei)} N·m², masses {m:g} kg at 3 m and 6 m (in X)",
            f"f11 = {fmt(f11)}, f22 = {fmt(f22)}, f12 = {fmt(f12)} m/N",
            f"k11 = {fmt(k11)}, k22 = {fmt(k22)}, k12 = {fmt(k12)} N/m",
            (
                f"ω1 = {fmt(omegas[0])} rad/s (T1 = {fmt(2 * math.pi / omegas[0])} s), ω2 = "
                f"{fmt(omegas[1])} rad/s (T2 = {fmt(2 * math.pi / omegas[1])} s)"
            ),
            f"φ1 = [1, {fmt(shapes[0][1])}], φ2 = [1, {fmt(shapes[1][1])}]",
            (
                f"ζ1 = 5 %, ζ2 = 5 % × ω2/ω1 = {fmt(100 * zetas[1])} % (SAEngine's stiffness-"
                "proportional damping calibrated to mode 1)"
            ),
            (
                "üg = 0.15 g sin(2π 1.3 t) + 0.10 g sin(2π 9.0 t), 0 ≤ t ≤ 4 s, Δt = 0.005 s; "
                f"peaks |u1| = {fmt(ref1 * 1e3)} mm, |u2| = {fmt(ref2 * 1e3)} mm"
            ),
        ],
    )
    tol = FRAME
    return Outcome(
        reference,
        [
            Quantity(
                "Peak displacement, level 1", "mm", ref1 * 1e3, float(np.max(np.abs(u1))) * 1e3, tol
            ),
            Quantity(
                "Peak displacement, level 2", "mm", ref2 * 1e3, float(np.max(np.abs(u2))) * 1e3, tol
            ),
        ],
        notes=[
            (
                "The derived masses (from the self-weight) are replaced by one mass in X at each "
                "level; the column's rotations carry no mass and are condensed in the reference."
            ),
            (
                "The time history runs after the dead loads, which only shorten the column. "
                "Newmark's method is linear, so integrating the coupled equations (SAEngine) "
                "and each mode on its own (the reference) gives the same history step by step "
                "when the damping is classical, as stiffness-proportional damping is."
            ),
        ],
    )


CASES: list[Case] = [
    Case(
        "AX1",
        "Linear buckling: pin-ended column and sway portal",
        "analysis",
        "Critical loads of SAEngine's linear (eigen) buckling analysis against Euler's column "
        "and the exact sway buckling of a fixed-base portal, and the effective length factor "
        "the buckling analysis reports.",
        "(a) Column 400 × 400 of C24.1, 4 m, pinned at its base and held laterally at its top, "
        "1000 kN down on the top. (b) Portal of two 3.2 m columns 400 × 400 fixed at their bases "
        "and a 6 m beam 300 × 500, 1000 kN down on each column top, buckling in its plane. "
        "Buckling of load case D (the loads replacing the self-weight).",
        buckling,
    ),
    Case(
        "AX2",
        "Cable under its own weight: elastic catenary",
        "analysis",
        "H, sag and tensions of a cable hanging under its own weight, from SAEngine's elastic "
        "catenary and its finite element cable (OpenSees), against Irvine's closed form.",
        "A strand of EA = 160 MN, w = 100 N/m, unstressed length 101 m: (a) between level "
        "supports 88.8 m apart; (b) between supports at different levels.",
        cable,
    ),
    Case(
        "AX3",
        "Lead-rubber isolators: equivalent linear design displacement",
        "analysis",
        "The isolation system's effective stiffness and damping and its design displacement, "
        "period and damping by the code's equivalent linear iteration, against a hand "
        "iteration of the same equations.",
        "Four lead-rubber bearings (Qd = 60 kN, Kd = 800 kN/m, Dy = 10 mm each) under a "
        "building of 8000 kN on site class SD in Dhaka (Z = 0.20), default pack.",
        isolators,
    ),
    Case(
        "AX4",
        "Viscous dampers: added damping ratio",
        "analysis",
        "The added effective damping of a linear and of a nonlinear (α = 0.5) viscous damper "
        "brace against the single-degree-of-freedom damping ratio and the energy per cycle.",
        "One storey 3.5 m high and one 6 m bay, seismic weight 2000 kN, lateral stiffness "
        "40 MN/m, one diagonal damper brace; roof displacement 50 mm.",
        dampers,
    ),
    Case(
        "AX5",
        "Moving loads: influence lines and the HL-93 truck on a simple span",
        "analysis",
        "Influence ordinates and the moving load envelope of SAEngine's bridge module against "
        "influence lines by hand, the truck placed by hand and Barré's absolute maximum.",
        "Simple span 20 m: mid-span moment influence line, HL-93 truck (variable rear "
        "spacing) × 1.33 plus the 9.3 kN/m lane load in one lane, absolute maximum moment of "
        "the truck. Two equal spans of 10 m: support moment influence line.",
        moving_loads,
    ),
    Case(
        "AX6",
        "Time history of a two-mass cantilever against modal superposition",
        "analysis",
        "Peak displacements of the two levels of a column carrying two masses under a ground "
        "motion that excites both modes, against modal superposition worked by hand.",
        "Column 400 × 400 of C24.1, 6 m, fixed at its base, drawn as two members; 15 t in X at "
        "3 m and at 6 m. Time history in X of two sines (0.15 g at 1.3 Hz, 0.10 g at 9 Hz) for "
        "4 s at Δt = 0.005 s with 5 % damping.",
        two_mass_history,
    ),
]

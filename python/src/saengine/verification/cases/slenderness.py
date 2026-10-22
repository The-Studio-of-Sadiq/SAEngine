"""Column slenderness benchmarks: the moment magnification of BNBC 2020 Part 6 Sec 6.3.10
(ACI 318-19 6.2.5, 6.6.4) in :mod:`saengine.design.slender`, against hand calculations.

The column is synthetic: 500 × 500 mm, f'c = 28 MPa, 6 m from a fixed base to a floor with a
600 mm deep beam along X; its section forces are written in by hand (no analysis is run), and
the references are worked out with plain arithmetic, none of SAEngine's helpers used for them.
Units: mm, MPa, N, N·mm; reported in kN, kN·m, mm.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from saengine.verification.cases.common import Case, Outcome, Quantity, Reference, fmt

FC = 28.0
EC = 4700 * math.sqrt(FC)
SIDE = 500.0
IG = SIDE**4 / 12
HEIGHT = 6.0  # m
BEAM_DEPTH = 600.0
STATIONS = 11
EXACT = 1e-3


def _sway_k(psi_a: float, psi_b: float) -> float:
    """The sway alignment chart's equation solved by bisection, written out independently."""

    def f(k: float) -> float:
        x = math.pi / k
        return (psi_a * psi_b * x * x - 36) / (6 * (psi_a + psi_b)) - x / math.tan(x)

    lo, hi = 1.0 + 1e-9, 50.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if f(lo) * f(mid) <= 0 else (mid, hi)
    return (lo + hi) / 2


def _nonsway_k(psi_a: float, psi_b: float) -> float:
    """The nonsway chart's equation solved by bisection on 0.5 < k < 1."""

    def f(k: float) -> float:
        x = math.pi / k
        return (
            psi_a * psi_b / 4 * x * x
            + (psi_a + psi_b) / 2 * (1 - x / math.tan(x))
            + 2 * math.tan(x / 2) / x
            - 1
        )

    lo, hi = 0.5 + 1e-9, 1.0 - 1e-9
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if f(lo) * f(mid) <= 0 else (mid, hi)
    return (lo + hi) / 2


def alignment_chart(_: Path) -> Outcome:
    from saengine.design.slender import k_nonsway, k_sway

    pairs = [(1.0, 1.0), (1.0, 2.0), (0.5, 3.0)]
    quantities = []
    steps = []
    for a, b in pairs:
        ks, kn = _sway_k(a, b), _nonsway_k(a, b)
        steps.append(f"ψA = {a:g}, ψB = {b:g}: sway k = {fmt(ks)}, nonsway k = {fmt(kn)}")
        quantities.append(Quantity(f"k sway, ψ = {a:g} / {b:g}", "", ks, k_sway(a, b), EXACT))
        quantities.append(Quantity(f"k nonsway, ψ = {a:g} / {b:g}", "", kn, k_nonsway(a, b), EXACT))
    reference = Reference(
        source="BNBC 2020 Part 6 Figure 6.6.5 (Jackson and Moreland alignment charts; ACI 318 "
        "R6.2.5); the charts' equations, e.g. AISC 360 Commentary C-A-7.1 and C-A-7.2",
        formula="sway: (ψA ψB (π/k)² - 36) / (6 (ψA + ψB)) = (π/k) / tan(π/k);  nonsway: "
        "ψA ψB/4 (π/k)² + (ψA + ψB)/2 (1 - (π/k)/tan(π/k)) + 2 tan(π/2k)/(π/k) = 1",
        steps=[
            *steps,
            "Both equations solved by bisection; the charts read 1.32 and 0.77 at ψ = 1",
        ],
    )
    return Outcome(reference, quantities)


def _frame() -> tuple[dict[str, Any], Any, dict[str, Any]]:
    from saengine.library.bim import BuildingModel
    from saengine.library.objects import Beam, Column

    ic = SIDE**4 / 12 * 1e-12
    project = {
        "nodes": [
            {"id": 1, "coords": [0, 0, 0], "restraint": [True] * 6},
            {"id": 2, "coords": [0, 0, HEIGHT], "restraint": [False] * 6},
            {"id": 3, "coords": [6.0, 0, HEIGHT], "restraint": [True] * 6},
        ],
        "sections": [
            {"id": 1, "E": EC * 1e6, "A": 0.25, "Iy": ic, "Iz": ic},
            {"id": 2, "E": EC * 1e6, "A": 0.18, "Iy": 2 * ic, "Iz": ic},
        ],
        "elements": [
            {"id": 1, "name": "C1", "type": "ElasticBeamColumn", "nodes": [1, 2], "section_id": 1},
            {"id": 2, "name": "B1", "type": "ElasticBeamColumn", "nodes": [2, 3], "section_id": 2},
        ],
    }
    building = BuildingModel.model_validate(
        {
            "stories": [
                {"id": "BASE", "name": "Base", "elevation": 0},
                {"id": "L1", "name": "Level 1", "elevation": HEIGHT * 1e3},
            ],
            "elements": [
                {
                    "id": "C1",
                    "type": "COL",
                    "kind": "column",
                    "position": [0, 0],
                    "bottom": 0,
                    "top": HEIGHT * 1e3,
                },
                {
                    "id": "B1",
                    "type": "BM",
                    "kind": "beam",
                    "start": [0, 0],
                    "end": [6000, 0],
                    "elevation": HEIGHT * 1e3,
                },
            ],
        }
    )
    profile = {"shape": "rectangle", "xDim": SIDE, "yDim": SIDE}
    types = {
        "COL": Column.model_validate(
            {"id": "COL", "name": "COL", "material": "C27.6", "profile": profile}
        ),
        "BM": Beam.model_validate(
            {
                "id": "BM",
                "name": "BM",
                "material": "C27.6",
                "profile": {"shape": "rectangle", "xDim": 300, "yDim": BEAM_DEPTH},
            }
        ),
    }
    return project, building, types


def _rows(n: float, m_bottom: float, m_top: float, vz: float = 0.0) -> np.ndarray:
    rows = np.zeros((STATIONS, 6))
    rows[:, 0] = n
    rows[:, 2] = vz
    rows[:, 4] = np.linspace(m_bottom, m_top, STATIONS)
    return rows


def _column(total, sway, sustained, combination: str, disp, options=None):
    """The slenderness of the column about the axis bending it along X."""
    from saengine.design.check import _Piece
    from saengine.design.rc import section_of
    from saengine.design.slender import SlenderContext
    from saengine.library.objects import LinearReinforcement, RectangleProfile

    piece = _Piece(
        "C1",
        1,
        HEIGHT,
        depth_along_z=False,
        axes=np.array([[0, 0, 1.0], [0, -1.0, 0], [1.0, 0, 0]]),
        forces=total,
        start=np.array([0, 0, 0.0]),
        end=np.array([0, 0, HEIGHT]),
        sway=sway,
        sustained=sustained,
    )
    zero = [np.zeros((STATIONS, 6))]
    beam = _Piece(
        "B1",
        2,
        6.0,
        depth_along_z=True,
        axes=np.eye(3),
        forces=zero,
        start=np.array([0, 0, HEIGHT]),
        end=np.array([6.0, 0, HEIGHT]),
        sway=zero,
        sustained=zero,
    )
    project, building, types = _frame()
    context = SlenderContext(
        project, building, types, {}, {"C1": [piece], "B1": [beam]}, [combination], disp, options
    )
    bars = LinearReinforcement.model_validate(
        {
            "material": "B420DWR",
            "cover": 40,
            "longitudinal": [{"position": "perimeter", "count": 8, "dia": 20}],
            "transverse": {"type": "tie", "dia": 10, "spacing": 150},
        }
    )
    section = section_of(RectangleProfile(xDim=SIDE, yDim=SIDE), bars, FC, 420)
    result = context.column("C1", section, [piece], False, EC)
    return next(a for a in result.axes if a.axis == "y"), context


def braced(_: Path) -> Outcome:
    pu, sustained, m1, m2 = 3000e3, 1500e3, 60e6, 100e6
    axis, _ = _column(
        [_rows(-pu, m1 / 1e3, m2 / 1e3)],
        [np.zeros((STATIONS, 6))],
        [_rows(-sustained, 0, 0)],
        "1.4D",
        [{}],
    )
    s = axis.check["slenderness"]
    lu = HEIGHT * 1e3 - BEAM_DEPTH
    r = 0.3 * SIDE
    limit = 34 - 12 * (m1 / m2)
    beta = sustained / pu
    ei = 0.4 * EC * IG / (1 + beta)
    pc = math.pi**2 * ei / lu**2
    cm = 0.6 + 0.4 * m1 / m2
    dns = cm / (1 - pu / (0.75 * pc))
    reference = Reference(
        source="BNBC 2020 Part 6 Sec 6.3.10.1 (lu, r, Eq. 6.6.14), 6.3.10.6 (Eqs. 6.6.19, "
        "6.6.20, 6.6.22, 6.6.23); ACI 318-19 6.2.5, 6.6.4.4, 6.6.4.5",
        formula="k lu / r vs 34 - 12 M1/M2;  EI = 0.4 Ec Ig / (1 + βdns);  Pc = π² EI / (k lu)²;"
        "  Cm = 0.6 + 0.4 M1/M2;  δns = Cm / (1 - Pu / (0.75 Pc));  Mc = δns M2",
        steps=[
            (
                "Nonsway (no lateral load), k = 1.0 (BNBC 6.3.10.6.3); Pu = 3000 kN, 1500 kN "
                "sustained; M1 = 60, M2 = 100 kN·m, single curvature"
            ),
            (
                f"lu = 6000 - 600 = {fmt(lu)} mm, r = 0.3 × 500 = {fmt(r)} mm, k lu / r = "
                f"{fmt(lu / r)} > 34 - 12 × 0.6 = {fmt(limit)}: slender"
            ),
            f"Ec = 4700 √28 = {fmt(EC)} MPa, Ig = 500⁴/12 = {IG:.4g} mm⁴, βdns = {fmt(beta)}",
            f"EI = 0.4 Ec Ig / 1.5 = {ei:.4g} N·mm², Pc = π² EI / 5400² = {fmt(pc / 1e3)} kN",
            (
                f"Cm = 0.6 + 0.4 × 0.6 = {fmt(cm)}, δns = {fmt(cm)} / (1 - 3000 / (0.75 × "
                f"{fmt(pc / 1e3)})) = {fmt(dns)}"
            ),
            f"Mc = {fmt(dns)} × 100 = {fmt(dns * 100)} kN·m",
        ],
    )
    quantities = [
        Quantity("k lu / r", "", lu / r, s["klu_r"], EXACT),
        Quantity("Pc", "kN", pc / 1e3, s["Pc"], EXACT),
        Quantity("δns", "", dns, s["deltaNs"], EXACT),
        Quantity("Mc", "kN·m", dns * 100, s["M2magnified"], EXACT),
    ]
    return Outcome(reference, quantities)


def sway(_: Path) -> Outcome:
    from saengine.design.slender import SlenderOptions

    pu, vus, delta, lc = 2000e3, 100e3, 0.02, HEIGHT
    sway_rows = [_rows(0.0, 200e3, -150e3, vz=vus)]
    total = [_rows(-pu, 20e3, -10e3) + sway_rows[0]]
    disp = [{n: np.array([delta, 0, 0, 0, 0, 0]) for n in (2, 3)}]
    axis, context = _column(
        total,
        sway_rows,
        [_rows(-1200e3, 0, 0)],
        "1.2D + 1.0EX",
        disp,
        SlenderOptions(drift_factor=1.0),
    )
    s = axis.check["slenderness"]
    storey = next(st for st in context.storeys if st.direction == "X")
    q = pu * delta / (vus * lc)
    ds = 1 / (1 - q)
    k = _sway_k(1.0, 1.0)
    m_bottom = 20 + ds * 200
    reference = Reference(
        source="BNBC 2020 Part 6 Sec 6.3.10.5.2 (Eq. 6.6.17), 6.3.10.7 (Eqs. 6.6.25 to "
        "6.6.27); ACI 318-19 6.6.4.3, 6.6.4.6",
        formula="Q = ΣPu Δo / (Vus lc) > 0.05: sway;  δs = 1 / (1 - Q);  M2 = M2ns + δs M2s",
        steps=[
            "1.2D + 1.0EX: Pu = 2000 kN, Vus = 100 kN, Δo = 20 mm (taken as cracked), lc = 6 m",
            f"Q = 2000 × 0.020 / (100 × 6) = {fmt(q)} > 0.05: the storey sways",
            (
                f"ψ = 1.0 at the fixed base and {fmt(1.0)} at the beam (0.70 Ig / 6 m over 0.35 × 2 "
                f"Ig / 6 m): sway k = {fmt(k)}, k lu / r = {fmt(k * 5400 / 150)} > 22"
            ),
            f"δs = 1 / (1 - {fmt(q)}) = {fmt(ds)}",
            f"Bottom: Mns = 20, Ms = 200 kN·m: M2 = 20 + {fmt(ds)} × 200 = {fmt(m_bottom)} kN·m",
        ],
    )
    quantities = [
        Quantity("Q", "", q, storey.q[0], EXACT),
        Quantity("k (sway)", "", k, s["k"], EXACT),
        Quantity("δs", "", ds, s["deltaS"], EXACT),
        Quantity("M2 = Mns + δs Ms", "kN·m", m_bottom, s["M2magnified"], EXACT),
    ]
    return Outcome(reference, quantities)


CASES = [
    Case(
        "DL1",
        "Slenderness: effective length from the alignment charts",
        "design",
        "k of sway and nonsway columns from the end restraints ψ, the equations of the "
        "Jackson and Moreland alignment charts solved.",
        "ψA, ψB = 1 / 1, 1 / 2 and 0.5 / 3; slender.k_sway and slender.k_nonsway.",
        alignment_chart,
    ),
    Case(
        "DL2",
        "Slenderness: braced column, nonsway moment magnification",
        "design",
        "A column in a nonsway storey with end moments in single curvature, magnified by δns.",
        "Column 500 × 500 mm, 6 m, 600 mm beam, f'c = 28 MPa, Pu = 3000 kN (1500 kN sustained), "
        "M1 = 60, M2 = 100 kN·m; slender.SlenderContext.",
        braced,
    ),
    Case(
        "DL3",
        "Slenderness: sway storey, stability index and δs",
        "design",
        "A storey whose stability index Q exceeds 0.05: sway k from the chart, the sway "
        "moments magnified by δs = 1 / (1 - Q).",
        "Column 500 × 500 mm, 6 m, fixed base, 600 mm beam; Pu = 2000 kN, Vus = 100 kN, "
        "Δo = 20 mm; slender.SlenderContext.",
        sway,
    ),
]

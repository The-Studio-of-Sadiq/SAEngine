"""Substructure benchmarks (Part 9): shallow foundations against hand calculations.

Each case runs SAEngine's own design functions (:mod:`saengine.substructure.shallow`) on a
synthetic footing or tie beam and works the same quantities out by hand, by plain statics and
the code formulas, step by step; none of SAEngine's helpers are used for the reference.

Units: mm, N and MPa inside; reported in kN, kN·m, kPa and mm.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from saengine.library.objects import BarMesh
from saengine.library.settings import Foundation
from saengine.substructure.shallow import ColumnBase, FootingSpec, design_footing
from saengine.verification.cases.common import Case, Outcome, Quantity, Reference, fmt

#: Tolerance of a hand calculation the code reproduces in closed form.
EXACT = 0.005
FC, FY = 25.0, 420.0
GAMMA_C = 2400 * 9.80665 * 1e-9  # N/mm³
GAMMA_S = 18.0  # kN/m³


def _checks(checks: list[dict]) -> dict[str, dict]:
    return {c["name"]: c for c in checks}


# ─────────────────────────────── DS1: strip footing under a wall ───────────────────────────────

STRIP_B, STRIP_H, WALL_T = 1500.0, 400.0, 200.0
WU, WS = 200.0, 140.0  # kN/m, factored and service wall loads


def strip_case(_: Path) -> Outcome:
    mesh = BarMesh(dia=12, spacing=150)
    pieces = [
        ColumnBase(f"W1#{k + 1}", -1500.0 + 1000 * k, 0.0, 1000.0, WALL_T, 100.0, punching=False)
        for k in range(4)
    ]
    spec = FootingSpec(
        id="S1",
        type="strip",
        footing_type="strip",
        length=4000.0,
        width=STRIP_B,
        thickness=STRIP_H,
        elevation=-1100.0,
        cover=75.0,
        fc=FC,
        fy=FY,
        columns=pieces,
        bottom_x=mesh,
        bottom_y=mesh,
        unit_weight=GAMMA_C,
    )
    checks, _ = design_footing(
        spec,
        {"D + L": [np.array([WS * 1e3, 0.0, 0.0])] * 4},
        {"1.2D + 1.6L": [np.array([WU * 1e3, 0.0, 0.0])] * 4},
        Foundation(allowableBearing=200, soilUnitWeight=GAMMA_S, groundLevel=0.0),
    )
    c = _checks(checks)

    # By hand, per metre of wall. Factored: the strip's weight is in the soil pressure and acts
    # down, so they cancel: qu = wu / B.
    b = STRIP_B / 1000
    qu = WU / b  # kPa
    cantilever = (STRIP_B - WALL_T) / 2 / 1000  # m, wall face to edge
    mu = qu * cantilever**2 / 2  # kN·m/m
    d_y = STRIP_H - 75 - 12 - 12 / 2  # the Y bars on the X bars
    vu = qu * (cantilever - d_y / 1000)  # kN/m at d from the face
    a_s = math.pi * 12**2 / 4 * 1000 / 150
    rho = a_s / (1000 * d_y)
    lam_s = math.sqrt(2 / (1 + 0.004 * d_y))
    phi_vc = 0.75 * 0.66 * lam_s * rho ** (1 / 3) * math.sqrt(FC) * 1000 * d_y / 1e3
    # Service: the wall, the strip and the 1.1 m of soil over it (top at -1.1 m, ground at 0);
    # net of γ Df, Df = 1.5 m.
    weight = 24 * 0.980665 * STRIP_H / 1000 * b + GAMMA_S * 1.1 * b  # kN/m
    q_net = (WS + weight) / b - GAMMA_S * 1.5
    steps = [
        (
            "Strip 4.0 m long, B = 1.5 m, h = 400 mm, top at -1.1 m, ground at 0; a 200 mm wall on "
            "its centre line, 200 kN/m factored and 140 kN/m service; Ø12 @ 150 both ways, cover "
            "75 mm; f'c = 25, fy = 420 MPa"
        ),
        f"qu = wu / B = 200 / 1.5 = {fmt(qu)} kPa (the weight cancels against its own pressure)",
        (
            f"Mu at the wall face (ACI 13.2.7.1), cantilever (1.5 - 0.2)/2 = {cantilever:g} m: "
            f"qu l² / 2 = {fmt(mu)} kN·m/m"
        ),
        f"dY = 400 - 75 - 12 - 6 = {d_y:g} mm; Vu at d from the face = qu (l - d) = {fmt(vu)} kN/m",
        (
            f"ρw = {fmt(a_s)} / (1000 × {d_y:g}) = {fmt(rho)}, λs = {fmt(lam_s)}: "
            f"φVc = 0.75 × 0.66 λs ρw^(1/3) √f'c b d = {fmt(phi_vc)} kN/m"
        ),
        (
            f"Service: the wall, the strip and the 1.1 m of soil over it: "
            f"(140 + {fmt(weight)}) / 1.5 - 18 × 1.5 = {fmt(q_net)} kPa net (Df = 1.5 m)"
        ),
    ]
    return Outcome(
        Reference(
            source="Statics of a 1 m strip; ACI 318-19 13.2.7.1-2, Table 22.5.5.1 (c), 22.5.5.1.3",
            formula="Mu = qu l² / 2, Vu = qu (l - d), φVc = 0.75 · 0.66 λs ρw^(1/3) √f'c b d",
            steps=steps,
        ),
        [
            Quantity("Mu at the wall face", "kN·m/m", mu, c["Flexure Y (bottom)"]["demand"], EXACT),
            Quantity("Vu at d from the face", "kN/m", vu, c["One-way shear Y"]["demand"], EXACT),
            Quantity("φVc per metre", "kN/m", phi_vc, c["One-way shear Y"]["capacity"], EXACT),
            Quantity("Net bearing pressure", "kPa", q_net, c["Bearing (service)"]["demand"], EXACT),
        ],
    )


# ─────────────────────────────── DS2: combined footing statics ───────────────────────────────

P1, P2 = 900.0, 600.0  # kN at u = -2000 and +3000: the resultant at the centroid
COMBINED_L, COMBINED_B = 7000.0, 1800.0


def combined_case(_: Path) -> Outcome:
    mesh = BarMesh(dia=16, spacing=150)
    spec = FootingSpec(
        id="CF",
        type="combined",
        footing_type="combined",
        length=COMBINED_L,
        width=COMBINED_B,
        thickness=700.0,
        elevation=-800.0,
        cover=75.0,
        fc=FC,
        fy=FY,
        columns=[
            ColumnBase("C1", -2000.0, 0.0, 400.0, 400.0, 800.0),
            ColumnBase("C2", 3000.0, 0.0, 400.0, 400.0, 800.0),
        ],
        bottom_x=mesh,
        bottom_y=mesh,
        top_x=mesh,
        top_y=mesh,
        unit_weight=GAMMA_C,
    )
    loads = [np.array([P1 * 1e3, 0.0, 0.0]), np.array([P2 * 1e3, 0.0, 0.0])]
    checks, _ = design_footing(
        spec,
        {"D + L": loads},
        {"1.4D": loads},
        Foundation(allowableBearing=200, soilUnitWeight=GAMMA_S, groundLevel=0.0),
    )
    c = _checks(checks)

    # By hand: the resultant P1 (-2.0) + P2 (3.0) = 0 lies at the centroid: uniform pressure.
    length = COMBINED_L / 1000
    w = (P1 + P2) / length  # kN/m along the footing
    x0 = P1 / w  # m from the left end where the shear is zero (between the columns)
    hog = w * x0**2 / 2 - P1 * (x0 - 1.5)  # kN·m, C1 at 1.5 m from the left end
    sag = w * 1.3**2 / 2  # kN·m at C1's outer face, 1.3 m from the end
    per_m = 1 / (COMBINED_B / 1000)
    area = length * COMBINED_B / 1000
    weight = 24 * 0.980665 * 0.7 * area + GAMMA_S * 0.8 * area
    q_net = (P1 + P2 + weight) / area - GAMMA_S * 1.5
    steps = [
        (
            "Combined footing 7.0 × 1.8 × 0.7 m, top at -0.8 m, ground at 0; C1 900 kN at "
            "u = -2.0 m and C2 600 kN at u = +3.0 m (400 × 400 columns), the same loads factored "
            "and in service"
        ),
        (
            "Resultant: (900 × -2.0 + 600 × 3.0) / 1500 = 0: at the centroid, so the pressure is "
            f"uniform, w = 1500 / 7.0 = {fmt(w)} kN/m"
        ),
        f"Zero shear between the columns at x0 = P1 / w = {fmt(x0)} m from the left end",
        (
            f"Largest hogging moment M = w x0² / 2 - P1 (x0 - 1.5) = {fmt(hog)} kN·m = "
            f"{fmt(hog * per_m)} kN·m/m over B = 1.8 m"
        ),
        (
            f"Sagging at C1's outer face, 1.3 m from the end: w 1.3² / 2 = {fmt(sag)} kN·m = "
            f"{fmt(sag * per_m)} kN·m/m"
        ),
        f"Service: (1500 + {fmt(weight)}) / {fmt(area)} - 18 × 1.5 = {fmt(q_net)} kPa net",
    ]
    return Outcome(
        Reference(
            source="Statics of a rigid combined footing (ACI 336.2R)",
            formula="w = ΣP / L; V(x0) = 0; M(x0) = w x0² / 2 - P1 (x0 - a1)",
            steps=steps,
        ),
        [
            Quantity(
                "Hogging between the columns",
                "kN·m/m",
                -hog * per_m,
                c["Flexure between columns (top)"]["demand"],
                EXACT,
            ),
            Quantity(
                "Sagging at C1's outer face",
                "kN·m/m",
                sag * per_m,
                c["Flexure X (bottom)"]["demand"],
                EXACT,
            ),
            Quantity("Net bearing pressure", "kPa", q_net, c["Bearing (service)"]["demand"], EXACT),
        ],
    )


# ─────────────────────────────── DS3: tie beam ───────────────────────────────


def tie_beam_case(_: Path) -> Outcome:
    from saengine.library import default_material_library
    from saengine.library.bim import BuildingModel
    from saengine.library.objects import ObjectLibrary
    from saengine.library.settings import default_project_settings
    from saengine.library.substructure import Substructure
    from saengine.substructure.context import Context
    from saengine.substructure.loads import Base, BaseLoads
    from saengine.substructure.shallow import design_tie_beam

    building = BuildingModel.model_validate(
        {
            "elements": [
                {"id": f"C{k + 1}", "kind": "column", "type": "COL", "position": [x, 0],
                 "bottom": 0, "top": 3000}
                for k, x in enumerate((0, 6000))
            ]
        }
    )  # fmt: skip
    objects = ObjectLibrary.model_validate(
        {
            "objects": [
                {"id": "COL", "name": "Column 400", "kind": "column", "material": "C24.1",
                 "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400}},
                {"id": "TB", "name": "Tie beam 250x400", "kind": "beam", "material": "C24.1",
                 "profile": {"shape": "rectangle", "xDim": 250, "yDim": 400},
                 "reinforcement": {
                     "material": "B420DWR", "cover": 40,
                     "longitudinal": [{"position": "top", "count": 2, "dia": 16},
                                      {"position": "bottom", "count": 2, "dia": 16}],
                     "transverse": {"type": "stirrup", "dia": 10, "spacing": 150}}},
            ]
        }
    )  # fmt: skip
    footing = {"type": "isolated", "length": 1800, "width": 1800, "thickness": 500}
    substructure = Substructure.model_validate(
        {
            "foundations": [
                {"id": "F1", "columns": ["C1"], **footing},
                {"id": "F2", "columns": ["C2"], **footing},
            ],
            "tieBeams": [{"id": "TB1", "from": "F1", "to": "F2", "type": "TB", "settlement": 12}],
        }
    )
    elements = {e.id: e for e in building.elements}
    loads = BaseLoads(
        {"D": {1: np.array([0, 0, 900e3, 0, 0, 0]), 2: np.array([0, 0, 1300e3, 0, 0, 0])}},
        {
            "C1": Base("C1", elements["C1"], [(1, np.array([0.0, 0.0, 0.0]))]),
            "C2": Base("C2", elements["C2"], [(2, np.array([6000.0, 0.0, 0.0]))]),
        },
        [("1.0D", {"D": 1.0})],
        [("D", {"D": 1.0})],
        {"1.0D": 1.0},
        False,
    )
    materials = default_material_library()
    ctx = Context(
        substructure,
        building,
        objects,
        materials,
        default_project_settings("Verification"),
        loads=loads,
    )
    result, _ = design_tie_beam(ctx, substructure.tieBeams[0])
    c = _checks(result["checks"])

    # By hand.
    force = 0.10 * 1300  # kN, 10 % of the larger footing or column load
    a_s = 4 * math.pi * 16**2 / 4
    phi_tn = 0.90 * 420 * a_s / 1e3
    e = materials.get("C24.1").mechanical.E  # MPa
    inertia = 0.35 * 250 * 400**3 / 12  # mm⁴, cracked beam (ACI Table 6.6.3.1.1)
    moment = 6 * e * inertia * 12 / 6000**2 / 1e6  # kN·m
    shear = 2 * moment / 6.0  # kN
    size = (6000 - 400) / 20  # mm
    steps = [
        (
            "Columns C1 (900 kN) and C2 (1300 kN) 6 m apart, 400 × 400, on footings tied by a "
            "250 × 400 beam with 2 Ø16 top and bottom; C24.1 concrete, B420DWR bars"
        ),
        (
            f"BNBC 2020 Part 6 Sec 1.8.5.2 (b): T = 0.10 × 1300 = {fmt(force)} kN in tension or "
            f"compression; φTn = 0.90 × 420 × {fmt(a_s)} = {fmt(phi_tn)} kN"
        ),
        (
            f"Sec 8.3.11.3 (b): smallest side ≥ clear spacing / 20 = (6000 - 400) / 20 = "
            f"{fmt(size)} mm (250 mm provided: too small)"
        ),
        (
            f"Differential settlement 12 mm, both ends fixed: M = 6 E (0.35 Ig) Δ / L² with E = "
            f"{fmt(e)} MPa, 0.35 Ig = {fmt(inertia)} mm⁴: M = {fmt(moment)} kN·m, V = 2M / L = "
            f"{fmt(shear)} kN"
        ),
    ]
    return Outcome(
        Reference(
            source="BNBC 2020 Part 6 Sec 1.8.5.2 (b) and 8.3.11.3 (b); fixed-fixed beam under an "
            "end displacement; ACI 318-19 Table 6.6.3.1.1",
            formula="T = 0.1 Pmax; φTn = 0.9 fy As; M = 6 EI Δ / L², V = 12 EI Δ / L³",
            steps=steps,
        ),
        [
            Quantity("Tie force", "kN", force, c["Tie force (tension)"]["demand"], EXACT),
            Quantity("φTn", "kN", phi_tn, c["Tie force (tension)"]["capacity"], EXACT),
            Quantity("Least side", "mm", size, c["Least size"]["demand"], EXACT),
            Quantity(
                "Settlement moment", "kN·m", moment, c["Flexure from settlement"]["demand"], EXACT
            ),
            Quantity("Settlement shear", "kN", shear, c["Shear from settlement"]["demand"], EXACT),
        ],
    )


CASES = [
    Case(
        "DS1",
        "Strip footing under a wall, per metre",
        "design",
        "Flexure and one-way shear across a strip footing at the face of a concrete wall, and its "
        "net bearing pressure, per metre of wall.",
        "Strip 4.0 × 1.5 × 0.4 m under a 200 mm wall on its centre line, 200 kN/m factored, "
        "140 kN/m service; Ø12 @ 150; f'c = 25, fy = 420 MPa; shallow.design_footing with the "
        "wall as four 1 m pieces.",
        strip_case,
    ),
    Case(
        "DS2",
        "Combined footing statics",
        "design",
        "Uniform pressure under two columns whose resultant is at the centroid, the hogging "
        "moment between them where the shear is zero, and the sagging at the outer column face.",
        "Footing 7.0 × 1.8 × 0.7 m; 900 kN at -2.0 m and 600 kN at +3.0 m; shallow.design_footing.",
        combined_case,
    ),
    Case(
        "DS3",
        "Tie beam: strut-tie force, size and settlement",
        "design",
        "The BNBC 2020 tie force between footings (10 % of the larger footing or column "
        "load), the least size of a grade beam and the moment and shear of a differential settlement.",
        "Columns 900 and 1300 kN 6 m apart, tie beam 250 × 400 with 2 Ø16 top and bottom, "
        "12 mm differential settlement; shallow.design_tie_beam.",
        tie_beam_case,
    ),
]

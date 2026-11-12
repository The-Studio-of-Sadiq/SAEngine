"""Seismic detailing benchmarks: BNBC 2020 Part 6 Sec 8.3 (pp. 1088-1123) in
:mod:`saengine.design.ductile_members` and :mod:`saengine.design.ductile_joints`, against
hand calculations.

The members are synthetic (f'c = 28 MPa, fy = fyt = 420 MPa, 40 mm clear cover to the ties):
no analysis is run, the references are plain arithmetic of the code's equations, none of
SAEngine's helpers used for them. Units: mm, MPa, N, N·mm; reported in mm, mm², kN.
"""

from __future__ import annotations

import math
from pathlib import Path

from saengine.verification.cases.common import Case, Outcome, Quantity, Reference, fmt

FC, FY = 28.0, 420.0
COVER = 40.0
EXACT = 1e-3


def _section(width: float, depth: float, longitudinal: list[dict], tie: float):
    from saengine.design.rc import section_of
    from saengine.library.objects import LinearReinforcement, RectangleProfile

    reinforcement = LinearReinforcement.model_validate(
        {
            "material": "B420DWR",
            "cover": COVER,
            "longitudinal": longitudinal,
            "transverse": {"type": "tie", "dia": tie, "spacing": 100, "legs": 4},
        }
    )
    return section_of(RectangleProfile(xDim=width, yDim=depth), reinforcement, FC, FY)


def column_confinement(_: Path) -> Outcome:
    from saengine.design import ductile_members as dm

    b = h = 500.0
    db, dt, legs, clear = 20.0, 10.0, 4, 3600.0
    section = _section(b, h, [{"position": "perimeter", "count": 12, "dia": db}], dt)
    zones = dm.Zones("tie", dt, 150.0, legs, legs, zone_spacing=100.0)
    need = dm.column_need(section, "special", COVER, zones, clear_height=clear, axial=2.0e6)
    out = dm.column_checks(
        section, None, "special", COVER, clear_height=clear, axial=(2.0e6, "c"), zones=zones
    )
    ash_row = next(c for c in out.checks if c["name"].startswith("Confinement Ash, bc along x"))

    # By hand.
    bc = b - 2 * COVER  # 420, to the outside of the hoops
    ag, ach = b * h, bc * bc
    eq_687 = 0.3 * bc * FC / FY * (ag / ach - 1)  # Ash / s
    eq_688 = 0.09 * bc * FC / FY
    ash_s = max(eq_687, eq_688)
    hx = (bc - 2 * dt - db) / (legs - 1)
    so = min(150.0, max(100.0, 100 + (350 - hx) / 3))
    spacing = min(min(b, h) / 4, 6 * db, so)
    lo = max(max(b, h), clear / 6, 450.0)
    reference = Reference(
        source="BNBC 2020 Part 6 Sec 8.3.5.4(a)(ii), (b), (c), (d) (pp. 1097-1099), Eq. 6.8.7 "
        "and 6.8.8",
        formula="Ash/s = max(0.3 bc f'c/fyt (Ag/Ach - 1), 0.09 bc f'c/fyt); hx = (bc - 2 dt - "
        "db)/(legs - 1); so = 100 + (350 - hx)/3 within 100-150 mm; s ≤ min(b/4, 6 db, so); lo = "
        "max(h, ln/6, 450 mm)",
        steps=[
            (
                f"Column {b:g} × {h:g} mm, 12Ø{db:g}, hoops Ø{dt:g} with {legs} legs each way, "
                f"clear cover {COVER:g} mm, ln = {clear:g} mm, Pu = 2000 kN > 0.1 Ag f'c = 700 kN"
            ),
            (
                f"bc = {b:g} - 2 × {COVER:g} = {bc:g} mm; Ag/Ach - 1 = {ag:g}/{ach:g} - 1 = "
                f"{fmt(ag / ach - 1)}"
            ),
            (
                f"Eq. 6.8.7: 0.3 × {bc:g} × 28/420 × {fmt(ag / ach - 1)} = {fmt(eq_687)} mm²/mm; "
                f"Eq. 6.8.8: 0.09 × {bc:g} × 28/420 = {fmt(eq_688)} mm²/mm"
            ),
            f"Ash at s = 100 mm: {fmt(100 * ash_s)} mm² (4 legs Ø10 give {fmt(4 * math.pi * 25)})",
            (
                f"hx = ({bc:g} - 20 - {db:g}) / 3 = {fmt(hx)} mm; so = 100 + (350 - {fmt(hx)})/3 = "
                f"{fmt(100 + (350 - hx) / 3)} → {fmt(so)} mm"
            ),
            f"s ≤ min({min(b, h) / 4:g}, 6 × {db:g} = {6 * db:g}, {fmt(so)}) = {fmt(spacing)} mm",
            f"lo = max({h:g}, {clear:g}/6 = {clear / 6:g}, 450) = {fmt(lo)} mm",
        ],
    )
    quantities = [
        Quantity("Ash / s (bc along x)", "mm²/mm", ash_s, need.ash_s[0], EXACT),
        Quantity("Ash at s = 100 mm", "mm²", 100 * ash_s, ash_row["demand"], EXACT),
        Quantity("hx", "mm", hx, need.hx, EXACT),
        Quantity("so (8.3.5.4(b)(iii))", "mm", so, need.so, EXACT),
        Quantity("Largest spacing in lo", "mm", spacing, need.zone_spacing, EXACT),
        Quantity("lo", "mm", lo, need.zone_length, EXACT),
    ]
    return Outcome(reference, quantities)


def joint_shear(_: Path) -> Outcome:
    from saengine.design import ductile_joints as dj

    column = _section(500.0, 500.0, [{"position": "perimeter", "count": 12, "dia": 20}], 10.0)
    beam = _section(
        400.0,
        500.0,
        [
            {"position": "top", "count": 4, "dia": 20},
            {"position": "bottom", "count": 3, "dia": 20},
        ],
        10.0,
    )
    joint = dj.FrameJoint(
        "J1",
        (0.0, 0.0),
        3000.0,
        "C1",
        "C2",
        [
            dj.JointBeam("B1", "B400", (1.0, 0.0), 4000.0),
            dj.JointBeam("B2", "B400", (-1.0, 0.0), 4000.0),
        ],
        height_below=3000.0,
        height_above=3000.0,
    )
    below = dj.JointColumn(column, 0.0, 1.0e6, 1.5e6, COVER, 10.0)
    above = dj.JointColumn(column, 0.0, 0.5e6, 1.0e6, COVER, 10.0)
    rows, _ = dj.joint_checks(joint, {"B400": beam}, below, above, column.profile)
    shear = next(r for r in rows if r["name"].startswith("Joint shear"))

    # By hand: bar forces at 1.25 fy; Mpr of the beams singly reinforced (the compression bars
    # change Mpr by about 1 %, Vcol by a few kN of the 1000).
    area = math.pi * 20**2 / 4
    top, bottom = 4 * area, 3 * area
    d = 500.0 - COVER - 10.0 - 10.0  # 440 mm
    t1, c2 = 1.25 * FY * top, 1.25 * FY * bottom

    def mpr(force: float) -> float:
        a = force / (0.85 * FC * 400.0)
        return force * (d - a / 2)

    vcol = (mpr(t1) + mpr(c2)) / 3000.0  # contraflexure at the column mid-heights
    vj = t1 + c2 - vcol
    aj = 500.0 * min(500.0, 400.0 + 500.0)
    phi_vn = 0.85 * 1.2 * math.sqrt(FC) * aj
    reference = Reference(
        source="BNBC 2020 Part 6 Sec 8.3.7.1(a), 8.3.7.3 (pp. 1108-1110), Sec 6.2.3.3(c) "
        "(φ = 0.85); bj by ACI 318-19 18.8.4.3 (BNBC does not define it)",
        formula="Vj = 1.25 fy (As,top + As,bottom) - Vcol, Vcol = (Mpr- + Mpr+) / (storey "
        "height); φVn = 0.85 γ √f'c Aj, γ = 1.2 (two opposite faces confined, b ≥ 3/4 of the "
        "column face)",
        steps=[
            (
                "Interior joint along X: column 500 × 500 mm, beams 400 × 500 mm both sides (top "
                "4Ø20, bottom 3Ø20, d = 440 mm), storeys 3000 mm, f'c = 28, fy = 420 MPa"
            ),
            (
                f"T1 = 1.25 × 420 × {fmt(top)} = {fmt(t1 / 1e3)} kN; C2 = 1.25 × 420 × "
                f"{fmt(bottom)} = {fmt(c2 / 1e3)} kN"
            ),
            (
                f"Mpr- = {fmt(mpr(t1) / 1e6)}, Mpr+ = {fmt(mpr(c2) / 1e6)} kN·m; Vcol = "
                f"{fmt(vcol / 1e3)} kN"
            ),
            f"Vj = {fmt(t1 / 1e3)} + {fmt(c2 / 1e3)} - {fmt(vcol / 1e3)} = {fmt(vj / 1e3)} kN",
            (
                f"Aj = 500 × min(500, 400 + 500) = {aj:g} mm²; φVn = 0.85 × 1.2 × √28 × {aj:g} = "
                f"{fmt(phi_vn / 1e3)} kN"
            ),
        ],
    )
    quantities = [
        Quantity("Joint shear Vj", "kN", vj / 1e3, shear["demand"], 0.005),
        Quantity("φVn of the joint", "kN", phi_vn / 1e3, shear["capacity"], 1e-4),
    ]
    return Outcome(reference, quantities)


CASES = [
    Case(
        "DZ1",
        "Seismic detailing: special moment frame column confinement",
        "design",
        "Hoops of a special moment frame column: Ash of Eq. 6.8.7 and 6.8.8, hx, so, the largest "
        "spacing in lo and lo (BNBC Sec 8.3.5.4).",
        "Column 500 × 500 mm, 12Ø20, hoops Ø10 with 4 legs each way, ln = 3.6 m, Pu = 2000 kN; "
        "ductile_members.column_need and column_checks.",
        column_confinement,
    ),
    Case(
        "DZ2",
        "Seismic detailing: beam-column joint shear",
        "design",
        "Shear of an interior joint of a special moment frame from the beam bars at 1.25 fy "
        "against φ γ √f'c Aj (BNBC Sec 8.3.7).",
        "Column 500 × 500 mm, beams 400 × 500 mm with 4Ø20 top and 3Ø20 bottom on both sides, "
        "storeys 3 m; ductile_joints.joint_checks.",
        joint_shear,
    ),
]

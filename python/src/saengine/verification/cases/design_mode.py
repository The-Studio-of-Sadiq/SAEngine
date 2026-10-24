"""Design-mode benchmarks: the reinforcement SAEngine requires and proposes
(:mod:`saengine.design.bars`, :mod:`saengine.design.required`, :mod:`saengine.design.proposal`)
against hand calculations to ACI 318-19 (BNBC 2020 Part 6 Chapter 6 is based on an earlier ACI
318 and is the same or less strict).

Every reference is worked out with plain arithmetic, step by step; none of SAEngine's helpers
are used for it. Units: mm, MPa, N, N·mm; reported in mm², kN·m, kN, mm.
"""

from __future__ import annotations

import math
from pathlib import Path

from saengine.design import bars as B
from saengine.verification.cases.common import Case, Outcome, Quantity, Reference, fmt

FC, FY = 28.0, 420.0
ROOT = math.sqrt(FC)
EXACT = 0.005


def _area(dia: float) -> float:
    return math.pi * dia**2 / 4


def beam_required(_: Path) -> Outcome:
    from saengine.design.proposal import BeamDesigner, BeamLoads
    from saengine.design.required import Options
    from saengine.library.objects import Beam

    b, d, mu = 300.0, 440.0, 150e6
    need = B.beam_flexure_need(mu, b, d, 60.0, FC, FY)
    rn = mu / (0.9 * b * d**2)
    rho = 0.85 * FC / FY * (1 - math.sqrt(1 - 2 * rn / (0.85 * FC)))
    as_req = rho * b * d
    as_min = max(0.25 * ROOT, 1.4) / FY * b * d

    beam = Beam.model_validate(
        {
            "id": "B",
            "name": "B",
            "material": "C28",
            "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
            "reinforcement": {
                "material": "B420",
                "cover": 40,
                "longitudinal": [{"position": "bottom", "count": 2, "dia": 16}],
                "transverse": {"type": "stirrup", "dia": 10, "spacing": 150},
            },
        }
    )
    pick = BeamDesigner(beam, FC, FY, 200_000, None, Options()).propose(BeamLoads(mu, 0.0, 100e3))
    as_25 = 2 * _area(25)
    d_25 = 500 - 40 - 8 - 25 / 2
    a = as_25 * FY / (0.85 * FC * b)
    phi_mn = 0.9 * as_25 * FY * (d_25 - a / 2)
    reference = Reference(
        source="ACI 318-19 22.2 (rectangular stress block), 21.2.2 (φ = 0.90 tension-"
        "controlled), 9.6.1.2 (As,min); textbook design procedure, e.g. Wight & MacGregor, "
        "Reinforced Concrete, ch. 5",
        formula="Rn = Mu / (φ b d²);  ρ = 0.85 f'c/fy (1 - √(1 - 2 Rn / (0.85 f'c)));  "
        "As = ρ b d;  As,min = max(0.25 √f'c, 1.4) bw d / fy",
        steps=[
            (
                "b × h = 300 × 500 mm, d = 500 - 40 - 10 - 20/2 = 440 mm, f'c = 28, fy = 420 MPa, "
                "Mu = 150 kN·m"
            ),
            f"Rn = 150e6 / (0.9 × 300 × 440²) = {fmt(rn)} MPa",
            f"ρ = 0.85 × 28 / 420 × (1 - √(1 - 2 × {fmt(rn)} / 23.8)) = {fmt(rho)}",
            (
                f"As = {fmt(rho)} × 300 × 440 = {fmt(as_req)} mm² > As,min = 1.4/420 × 300 × 440 = "
                f"{fmt(as_min)} mm²"
            ),
            (
                "Proposal: Ø8 two-leg stirrups (Av,min governs), so d = 442 mm and As = 958.6 mm²; "
                "2Ø25 = 982 mm² in one row is the lightest choice with the fewest bars"
            ),
            (
                f"Check of 2Ø25: d = 500 - 40 - 8 - 12.5 = {fmt(d_25)} mm, a = 982 × 420 / "
                f"(0.85 × 28 × 300) = {fmt(a)} mm, φMn = 0.9 × 982 × 420 × ({fmt(d_25)} - "
                f"{fmt(a)}/2) = {fmt(phi_mn / 1e6)} kN·m >= 150 kN·m"
            ),
        ],
    )
    utilisation = pick.utilisation.get("sagging", math.nan)
    return Outcome(
        reference,
        [
            Quantity("As required", "mm²", as_req, need.area, EXACT),
            Quantity("As,min", "mm²", as_min, B.beam_min_area(b, d, FC, FY), EXACT),
            Quantity("Bars proposed: area", "mm²", as_25, pick.area - 2 * _area(12), EXACT),
            Quantity(
                "φMn of the bars proposed", "kN·m", phi_mn / 1e6, mu / utilisation / 1e6, 0.01
            ),
        ],
        notes=[
            (
                "SAEngine checks the proposed bars by strain compatibility (concreteproperties), "
                "with the 2Ø12 top hanger bars in compression: within 1 % of the hand φMn."
            )
        ],
    )


def beam_compression(_: Path) -> Outcome:
    b, d, d2, mu = 250.0, 340.0, 60.0, 250e6
    need = B.beam_flexure_need(mu, b, d, d2, FC, FY, h=400)
    eps_ty = FY / 200_000
    c = 0.003 * d / (0.006 + eps_ty)
    a = 0.85 * c
    as1 = 0.85 * FC * b * a / FY
    mn1 = as1 * FY * (d - a / 2)
    mn2 = mu / 0.9 - mn1
    fs = min(200_000 * 0.003 * (c - d2) / c, FY)
    as2 = mn2 / ((fs - 0.85 * FC) * (d - d2))
    total = as1 + as2 * (fs - 0.85 * FC) / FY
    reference = Reference(
        source="ACI 318-19 21.2.2 (εt >= εty + 0.003 for φ = 0.90), 22.2 (stress block, strain "
        "compatibility); doubly reinforced design as in Wight & MacGregor, ch. 5",
        formula="c = 0.003 d / (0.006 + εty);  As1 = 0.85 f'c b β1 c / fy;  Mn2 = Mu/φ - Mn1;  "
        "f's = Es 0.003 (c - d')/c <= fy;  As' = Mn2 / ((f's - 0.85 f'c)(d - d'));  "
        "As = As1 + As' (f's - 0.85 f'c) / fy",
        steps=[
            "b × h = 250 × 400 mm, d = 340, d' = 60 mm, Mu = 250 kN·m",
            f"c = 0.003 × 340 / (0.006 + {fmt(eps_ty)}) = {fmt(c)} mm, a = 0.85 c = {fmt(a)} mm",
            (
                f"As1 = 0.85 × 28 × 250 × {fmt(a)} / 420 = {fmt(as1)} mm²; Mn1 = {fmt(mn1 / 1e6)} kN·m "
                f"< Mu/φ = {fmt(mu / 0.9 / 1e6)} kN·m: compression bars"
            ),
            f"f's = 200000 × 0.003 × ({fmt(c)} - 60)/{fmt(c)} = {fmt(fs)} MPa",
            f"As' = {fmt(mn2 / 1e6)}e6 / (({fmt(fs)} - 23.8) × 280) = {fmt(as2)} mm²",
            f"As = {fmt(as1)} + {fmt(as2)} × ({fmt(fs)} - 23.8)/420 = {fmt(total)} mm²",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Compression steel As'", "mm²", as2, need.compression, EXACT),
            Quantity("Tension steel As", "mm²", total, need.area, EXACT),
        ],
    )


def beam_stirrups(_: Path) -> Outcome:
    b, d, vu = 300.0, 440.0, 200e3
    need = B.beam_shear_need(vu, b, d, FC, FY)
    pick = B.choose_stirrups(need, b)
    vc = 0.17 * ROOT * b * d
    vs = vu / 0.75 - vc
    av_s = vs / (FY * d)
    s8 = math.floor(2 * _area(8) / av_s / 25) * 25
    reference = Reference(
        source="ACI 318-19 22.5.5.1 (a), 22.5.8.5.3 (Vs = Av fyt d / s), 9.6.3.4 (Av,min), "
        "9.7.6.2.2 (largest spacing); φ = 0.75 (21.2.1)",
        formula="Vs = Vu/φ - 0.17 λ √f'c bw d;  Av/s = Vs / (fyt d) >= max(0.062 √f'c, 0.35) "
        "bw / fyt;  s <= min(d/2, 600) (Vs <= 0.33 √f'c bw d)",
        steps=[
            "bw = 300 mm, d = 440 mm, Vu = 200 kN",
            f"Vc = 0.17 × {fmt(ROOT)} × 300 × 440 = {fmt(vc / 1e3)} kN",
            f"Vs = 200/0.75 - {fmt(vc / 1e3)} = {fmt(vs / 1e3)} kN",
            f"Av/s = {fmt(vs)} / (420 × 440) = {fmt(av_s)} mm²/mm (min 0.25)",
            (
                f"Ø8 two legs: s = 100.5 / {fmt(av_s)} = {fmt(2 * _area(8) / av_s)} -> {s8:g} mm "
                "(25 mm steps) <= d/2 = 220 mm"
            ),
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Av/s required", "mm²/mm", av_s, need.av_s, EXACT),
            Quantity("Largest spacing", "mm", 220.0, need.s_max, EXACT),
            Quantity("Ø8 stirrup spacing proposed", "mm", s8, pick.spacing if pick else 0, EXACT),
        ],
    )


def slab_strip(_: Path) -> Outcome:
    h, cover, mu = 150.0, 20.0, 20e6
    as_min = 0.0018 * h * 1000
    required = {}
    for dia in B.SLAB_DIAMETERS:
        d = h - cover - dia / 2
        rn = mu / (0.9 * 1000 * d**2)
        rho = 0.85 * FC / FY * (1 - math.sqrt(1 - 2 * rn / (0.85 * FC)))
        required[dia] = max(rho * 1000 * d, as_min)
    s10 = math.floor(_area(10) * 1000 / required[10] / 25) * 25
    computed = {
        dia: max(B.slab_flexure_need(mu, h - cover - dia / 2, FC, FY).area, as_min)
        for dia in B.SLAB_DIAMETERS
    }
    mesh = B.mesh_for(0.0, min(2 * h, 450.0), B.SLAB_DIAMETERS, 100.0, computed)
    reference = Reference(
        source="ACI 318-19 22.2 (stress block), 8.6.1.1 / Table 24.4.3.2 (As,min = 0.0018 Ag "
        "for fy = 420), 8.7.2.2 (spacing <= min(2h, 450 mm))",
        formula="As = 0.85 f'c b d / fy (1 - √(1 - 2 Mu / (φ 0.85 f'c b d²))), b = 1000 mm;  "
        "s = Ab × 1000 / As rounded down to 25 mm",
        steps=[
            "Two-way slab 150 mm, cover 20 mm, Mu = 20 kN·m/m on the outer bottom layer",
            f"Ø10: d = 125 mm, As = {fmt(required[10])} mm²/m (As,min = {fmt(as_min)})",
            (
                f"s = 78.54 × 1000 / {fmt(required[10])} = {fmt(_area(10) * 1000 / required[10])} "
                f"-> {s10:g} mm, As = {fmt(_area(10) * 1000 / s10)} mm²/m"
            ),
            f"Ø12: d = 124 mm, As = {fmt(required[12])} -> 250 mm (452.4 mm²/m): more steel",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("As required (Ø10 layer)", "mm²/m", required[10], computed[10], EXACT),
            Quantity("Spacing proposed", "mm", s10, mesh.spacing if mesh else 0, EXACT),
            Quantity("Bar proposed", "mm", 10.0, mesh.dia if mesh else 0, EXACT),
        ],
    )


def column_axial(_: Path) -> Outcome:
    from saengine.design.required import ColumnSearch, Options
    from saengine.library.objects import Column

    pu = 3000e3
    ag = 400 * 400
    as_hand = (pu / (0.80 * 0.65) - 0.85 * FC * ag) / (FY - 0.85 * FC)
    column = Column.model_validate(
        {
            "id": "C",
            "name": "C",
            "material": "C28",
            "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
            "reinforcement": {
                "material": "B420",
                "cover": 40,
                "longitudinal": [{"position": "perimeter", "count": 4, "dia": 20}],
                "transverse": {"type": "tie", "dia": 10, "spacing": 150},
            },
        }
    )
    search = ColumnSearch(column, FC, FY, 200_000, None, Options())
    points = [(pu, 0.0, 0.0, "1.4D", "C")]
    index = search.smallest(points)
    required = search.required_area(index, points) or 0.0
    reference = Reference(
        source="ACI 318-19 22.4.2.1 (φPn,max = 0.80 φ P0, tied), 22.4.2.2 (P0), 21.2.2 "
        "(φ = 0.65), 10.6.1.1 (0.01 <= ρ <= 0.08)",
        formula="Pu = 0.80 × 0.65 (0.85 f'c (Ag - As) + fy As)  =>  As = (Pu / 0.52 - 0.85 f'c "
        "Ag) / (fy - 0.85 f'c)",
        steps=[
            "Tied column 400 × 400 mm, f'c = 28, fy = 420 MPa, Pu = 3000 kN, no moment",
            f"As = (3000e3 / 0.52 - 0.85 × 28 × 160000) / (420 - 23.8) = {fmt(as_hand)} mm²",
            f"ρ = {fmt(as_hand / ag)}: within 0.01 … 0.08",
        ],
    )
    return Outcome(
        reference,
        [Quantity("As required", "mm²", as_hand, required, 0.01)],
        notes=[
            (
                "SAEngine searches the practical layouts (equal bars, symmetric) on the interaction "
                "surface and interpolates the steel between the last that fails and the first that "
                "carries the load; with axial load only the utilisation is Pu / φPn,max."
            )
        ],
    )


CASES = [
    Case(
        "DR1",
        "Design mode: beam tension steel and the bars proposed",
        "design",
        "The tension steel a rectangular beam needs for a sagging moment, As,min, and the bars "
        "the proposal picks for it, checked by hand.",
        "Beam 300 × 500 mm, cover 40 mm, f'c = 28, fy = 420 MPa, Mu = 150 kN·m, Vu = 100 kN; "
        "bars.beam_flexure_need and proposal.BeamDesigner.",
        beam_required,
    ),
    Case(
        "DR2",
        "Design mode: beam compression steel",
        "design",
        "A beam whose moment exceeds the tension-controlled capacity: compression bars and the "
        "extra tension bars.",
        "Beam 250 × 400 mm, d = 340, d' = 60 mm, f'c = 28, fy = 420 MPa, Mu = 250 kN·m; "
        "bars.beam_flexure_need.",
        beam_compression,
    ),
    Case(
        "DR3",
        "Design mode: stirrups",
        "design",
        "The stirrups a beam needs for a shear force: Av/s, the largest spacing and the spacing "
        "proposed.",
        "Beam 300 × 500 mm, d = 440 mm, f'c = 28, fyt = 420 MPa, Vu = 200 kN; "
        "bars.beam_shear_need and bars.choose_stirrups.",
        beam_stirrups,
    ),
    Case(
        "DR4",
        "Design mode: slab strip As per metre and the mesh",
        "design",
        "The bars per metre a slab strip needs for its Wood-Armer moment, and the bar and "
        "spacing proposed (25 mm steps).",
        "Slab 150 mm, cover 20 mm, f'c = 28, fy = 420 MPa, Mu = 20 kN·m/m; bars.slab_flexure_need "
        "and bars.mesh_for.",
        slab_strip,
    ),
    Case(
        "DR5",
        "Design mode: column steel under axial load",
        "design",
        "The longitudinal steel a tied column needs for an axial load, found on the interaction "
        "surface.",
        "Column 400 × 400 mm, cover 40, Ø10 ties, f'c = 28, fy = 420 MPa, Pu = 3000 kN; "
        "required.ColumnSearch.",
        column_axial,
        fast=False,
    ),
]

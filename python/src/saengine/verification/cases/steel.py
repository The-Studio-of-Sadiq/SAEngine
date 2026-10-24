"""Steel member benchmarks: BNBC 2020 Part 6 Chapter 10 (LRFD, the provisions of AISC 360-05)
in :mod:`saengine.design.steel`, against hand calculations.

The sections are synthetic plate assemblies of common rolled and hollow sizes (a 308 x 305 H,
a 400 x 180 I, an SHS 150 x 8), their properties worked out here from the plates; the
references use plain arithmetic, none of SAEngine's helpers. Units: mm, MPa, N, N·mm; reported
in kN, kN·m.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from saengine.verification.cases.common import Case, Outcome, Quantity, Reference, fmt

E = 200_000.0
EXACT = 1e-6
CODE = "BNBC 2020 Part 6 Chapter 10"


def _h_plates(d: float, bf: float, tf: float, tw: float) -> dict[str, float]:
    hw = d - 2 * tf
    area = 2 * bf * tf + hw * tw
    ix = (bf * d**3 - (bf - tw) * hw**3) / 12
    iy = 2 * tf * bf**3 / 12 + hw * tw**3 / 12
    return {
        "A": area,
        "Ix": ix,
        "Iy": iy,
        "Sx": ix / (d / 2),
        "Zx": bf * tf * (d - tf) + tw * hw**2 / 4,
        "J": (2 * bf * tf**3 + hw * tw**3) / 3,
        "Cw": tf * bf**3 * (d - tf) ** 2 / 24,
        "ho": d - tf,
    }


def column(_: Path) -> Outcome:
    from saengine.design.steel.members import Steel, compression
    from saengine.design.steel.properties import i_shape

    d, bf, tf, tw, fy, length = 308.0, 305.0, 15.4, 9.9, 345.0, 4000.0
    p = _h_plates(d, bf, tf, tw)
    ry = math.sqrt(p["Iy"] / p["A"])
    kl_r = length / ry
    fe = math.pi**2 * E / kl_r**2
    fcr = 0.658 ** (fy / fe) * fy
    phi_pn = 0.9 * fcr * p["A"]
    cap = compression(i_shape(d, bf, tf, tw), Steel(fy, 450.0), length, length)
    reference = Reference(
        source=f"{CODE} Sec 10.5.3, Eqs 6.10.16-19 (Gazette p 3841)",
        formula="Fe = π² E / (KL/r)²; Fcr = 0.658^(Fy/Fe) Fy when Fe ≥ 0.44 Fy; φPn = 0.90 Fcr Ag",
        steps=[
            (
                f"H 308 x 305 x 9.9 / 15.4: Ag = {fmt(p['A'])} mm², Iy = {fmt(p['Iy'])} mm⁴, "
                f"ry = {fmt(ry)} mm"
            ),
            f"K = 1, L = 4 m: KL/r = {fmt(kl_r)}; Fe = {fmt(fe)} MPa ≥ 0.44 Fy = {fmt(0.44 * fy)}",
            f"Fcr = 0.658^({fy:g}/{fmt(fe)}) × {fy:g} = {fmt(fcr)} MPa",
            f"φPn = 0.90 × {fmt(fcr)} × {fmt(p['A'])} = {fmt(phi_pn / 1e3)} kN",
        ],
    )
    return Outcome(reference, [Quantity("φPn", "kN", phi_pn / 1e3, cap.design / 1e3, EXACT)])


def beam(_: Path) -> Outcome:
    from saengine.design.steel.members import Steel, flexure_major
    from saengine.design.steel.properties import i_shape

    d, bf, tf, tw, fy, lb = 400.0, 180.0, 13.5, 8.6, 250.0, 6000.0
    p = _h_plates(d, bf, tf, tw)
    ry = math.sqrt(p["Iy"] / p["A"])
    rts = math.sqrt(math.sqrt(p["Iy"] * p["Cw"]) / p["Sx"])
    lp = 1.76 * ry * math.sqrt(E / fy)
    jc = p["J"] / (p["Sx"] * p["ho"])
    lr = (
        1.95
        * rts
        * E
        / (0.7 * fy)
        * math.sqrt(jc)
        * math.sqrt(1 + math.sqrt(1 + 6.76 * (0.7 * fy / E / jc) ** 2))
    )
    cb = 12.5 / (2.5 + 3 * 0.75 + 4 + 3 * 0.75)  # uniform load: MA = MC = 0.75 Mmax
    mp = fy * p["Zx"]
    mn = min(mp, cb * (mp - (mp - 0.7 * fy * p["Sx"]) * (lb - lp) / (lr - lp)))
    cap = flexure_major(i_shape(d, bf, tf, tw), Steel(fy, 400.0), lb, cb)
    reference = Reference(
        source=f"{CODE} Secs 10.6.1, 10.6.2, Eqs 6.10.55-63 (Gazette pp 3852-3855)",
        formula="Cb = 12.5 Mmax / (2.5 Mmax + 3 MA + 4 MB + 3 MC); Lp = 1.76 ry √(E/Fy); "
        "Lr = 1.95 rts E/(0.7 Fy) √(J c/(Sx ho)) √(1 + √(1 + 6.76 (0.7 Fy Sx ho/(E J c))²)); "
        "Lp < Lb ≤ Lr: Mn = Cb [Mp - (Mp - 0.7 Fy Sx)(Lb - Lp)/(Lr - Lp)] ≤ Mp",
        steps=[
            (
                f"I 400 x 180 x 8.6 / 13.5, Fy = 250 MPa: Zx = {fmt(p['Zx'])} mm³, Sx = "
                f"{fmt(p['Sx'])} mm³, J = {fmt(p['J'])} mm⁴, Cw = {fmt(p['Cw'])} mm⁶"
            ),
            f"ry = {fmt(ry)} mm, rts = {fmt(rts)} mm: Lp = {fmt(lp)} mm, Lr = {fmt(lr)} mm",
            f"Simply supported under uniform load: Cb = 12.5 / 11 = {fmt(cb)}",
            (
                f"Lb = 6 m: Mn = {fmt(mn / 1e6)} kN·m (Mp = {fmt(mp / 1e6)}); φMn = "
                f"{fmt(0.9 * mn / 1e6)} kN·m"
            ),
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Lp", "mm", lp, _limit(cap.note, "Lp"), 1e-3),
            Quantity("Lr", "mm", lr, _limit(cap.note, "Lr"), 1e-3),
            Quantity("φMn", "kN·m", 0.9 * mn / 1e6, cap.design / 1e6, EXACT),
        ],
    )


def _limit(note: str, name: str) -> float:
    return float(note.split(f"{name} = ")[1].split(" ")[0])


def brace(_: Path) -> Outcome:
    from saengine.design.steel.members import Steel, compression, tension_rupture
    from saengine.design.steel.properties import rhs

    b, t, fy, fu = 150.0, 8.0, 345.0, 450.0
    area = b**2 - (b - 2 * t) ** 2
    r = math.sqrt((b**4 - (b - 2 * t) ** 4) / 12 / area)
    length = math.hypot(6000, 3200)
    fe = math.pi**2 * E / (length / r) ** 2
    fcr = 0.877 * fe  # Fe < 0.44 Fy
    xbar = (b * b + 2 * b * b) / (4 * 2 * b)
    u = 1 - xbar / b
    shape = rhs(b, b, t)
    steel = Steel(fy, fu)
    reference = Reference(
        source=f"{CODE} Secs 10.4.2, 10.4.3.3, Table 6.10.2 Case 6, Sec 10.5.3 (pp 3835-3841)",
        formula="φPn = 0.90 × 0.877 Fe Ag (Fe < 0.44 Fy); φt Pn = 0.75 Fu An U, U = 1 - x̄/l, "
        "x̄ = (B² + 2BH) / (4(B + H)), l = H",
        steps=[
            f"SHS 150 x 8 (nominal t, SAW): Ag = {fmt(area)} mm², r = {fmt(r)} mm",
            (
                f"L = √(6000² + 3200²) = {fmt(length)} mm, K = 1: KL/r = {fmt(length / r)}, "
                f"Fe = {fmt(fe)} MPa < 0.44 Fy = {fmt(0.44 * fy)}"
            ),
            f"φPn = 0.90 × 0.877 × {fmt(fe)} × {fmt(area)} = {fmt(0.9 * fcr * area / 1e3)} kN",
            (
                f"x̄ = {fmt(xbar)} mm, U = {fmt(u)}; φt Pn = 0.75 × 450 × {fmt(area)} × {fmt(u)} = "
                f"{fmt(0.75 * fu * area * u / 1e3)} kN"
            ),
        ],
    )
    return Outcome(
        reference,
        [
            Quantity(
                "φPn (compression)",
                "kN",
                0.9 * fcr * area / 1e3,
                compression(shape, steel, length, length).design / 1e3,
                EXACT,
            ),
            Quantity(
                "φPn (tensile rupture)",
                "kN",
                0.75 * fu * area * u / 1e3,
                tension_rupture(shape, steel).design / 1e3,
                EXACT,
            ),
        ],
    )


def beam_column(_: Path) -> Outcome:
    from saengine.design.steel.lengths import MemberLengths
    from saengine.design.steel.members import Stations, Steel, check_member
    from saengine.design.steel.properties import i_shape

    d, bf, tf, tw, fy, length = 308.0, 305.0, 15.4, 9.9, 345.0, 4000.0
    p = _h_plates(d, bf, tf, tw)
    pu, mu = 1500e3, 200e6
    ry = math.sqrt(p["Iy"] / p["A"])
    fe = math.pi**2 * E / (length / ry) ** 2
    pc = 0.9 * 0.658 ** (fy / fe) * fy * p["A"]
    # Lb = 4 m against Lp = 1.76 ry √(E/Fy): inelastic LTB with Cb = 1 (uniform moment).
    rts = math.sqrt(math.sqrt(p["Iy"] * p["Cw"]) / p["Sx"])
    lp = 1.76 * ry * math.sqrt(E / fy)
    jc = p["J"] / (p["Sx"] * p["ho"])
    lr = (
        1.95
        * rts
        * E
        / (0.7 * fy)
        * math.sqrt(jc)
        * math.sqrt(1 + math.sqrt(1 + 6.76 * (0.7 * fy / E / jc) ** 2))
    )
    mp = fy * p["Zx"]
    mn = mp if length <= lp else min(mp, mp - (mp - 0.7 * fy * p["Sx"]) * (length - lp) / (lr - lp))
    mc = 0.9 * mn
    pe1 = math.pi**2 * E * p["Ix"] / length**2
    b1 = 1.0 / (1 - pu / pe1)  # Cm = 1.0 (uniform moment, single curvature)
    ratio = pu / pc + 8 / 9 * b1 * mu / mc
    n = 11
    stations = Stations(
        "U",
        np.linspace(0, 4, n),
        np.full(n, pu),
        np.full(n, mu),
        np.zeros(n),
        np.zeros(n),
        np.zeros(n),
        ["C1"] * n,
    )
    checks = check_member(
        i_shape(d, bf, tf, tw), Steel(fy, 450.0), [stations], MemberLengths.simple(4.0), "column"
    )
    h1 = next(c for c in checks if c["name"].startswith("Axial force and flexure"))
    reference = Reference(
        source=f"{CODE} Secs 10.3.2.1 (Eqs 6.10.4, 6.10.6, 6.10.7), 10.8.1.1 (Eq 6.10.147a)",
        formula="B1 = Cm / (1 - Pr/Pe1), Pe1 = π² E Ix / L²; Pr/Pc ≥ 0.2: "
        "Pr/Pc + 8/9 (Mrx/Mcx + Mry/Mcy) ≤ 1",
        steps=[
            (
                f"Pu = 1500 kN, Mux = 200 kN·m uniform; φPn = {fmt(pc / 1e3)} kN, "
                f"φMn = {fmt(mc / 1e6)} kN·m (Lb = 4 m, Lp = {fmt(lp)} mm, Cb = 1)"
            ),
            f"Pe1 = {fmt(pe1 / 1e3)} kN, Cm = 1.0: B1 = {fmt(b1)}",
            f"{fmt(pu / pc)} + 8/9 × {fmt(b1 * mu / mc)} = {fmt(ratio)}",
        ],
    )
    return Outcome(reference, [Quantity("H1 ratio", "", ratio, h1["utilisation"], 2e-3)])


CASES = [
    Case(
        "DT1",
        "Steel: rolled H column in compression",
        "design",
        "Flexural buckling of a doubly symmetric H column, inelastic range (Eq 6.10.17).",
        "H 308 x 305 x 9.9 / 15.4, Fy = 345 MPa, 4 m, K = 1; steel.members.compression.",
        column,
    ),
    Case(
        "DT2",
        "Steel: lateral-torsional buckling of a beam",
        "design",
        "Lp, Lr and Mn of a compact I-beam between Lp and Lr, with Cb of a uniform load.",
        "I 400 x 180 x 8.6 / 13.5, Fy = 250 MPa, Lb = 6 m, Cb = 1.14; steel.members.flexure_major.",
        beam,
    ),
    Case(
        "DT3",
        "Steel: SHS brace in tension and compression",
        "design",
        "Elastic flexural buckling of a square hollow brace and tensile rupture with the "
        "shear lag of a single concentric gusset.",
        "SHS 150 x 8, Fy = 345, Fu = 450 MPa, 6.8 m between work points; steel.members.",
        brace,
    ),
    Case(
        "DT4",
        "Steel: beam-column interaction (H1) with B1",
        "design",
        "Axial compression with major-axis moment, the moment amplified by B1.",
        "H 308 x 305, Pu = 1500 kN, Mux = 200 kN·m, 4 m; steel.members.check_member.",
        beam_column,
    ),
]

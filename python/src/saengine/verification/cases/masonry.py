"""Benchmarks of masonry walls by allowable stress design (the code pack's ``masonry`` method
``allowableStress``; bnbc2020: Part 6 Chapter 7 Sec 7.3-7.6). Synthetic data; the references
are plain arithmetic of the code's equations with the gazette's numbers written out, none of
SAEngine's helpers used for them. Units: mm, MPa, N, N·mm.
"""

from __future__ import annotations

import math
from pathlib import Path

from saengine.verification.cases.common import Case, Outcome, Quantity, Reference, fmt

EXACT = 1e-3


def plain_wall(_: Path) -> Outcome:
    from saengine.design import masonry as M
    from saengine.design import masonry_asd as A
    from saengine.design import walls as W

    t, lw, h, fm = 250.0, 4000.0, 3000.0, 8.0
    p, v, m3 = 300e3, 30e3, 300e6
    g = W.WallGeometry(lw, t, h, h)
    forces = [W.PierForces("D + L", p, v, m3, 0.0, 0.0, False, "P1 bottom")]
    masonry = M.Masonry(fm, mortar="M2")
    found = M.masonry_wall_checks(g, None, forces, masonry, storeys=2)
    rows = {c["name"].split(" (")[0]: c for c in found.checks}
    share = 0.5  # no special inspection (Sec 7.3.5)
    fa_allow = share * fm / 5 * (1 - (h / (42 * t)) ** 3)
    fa = p / (t * lw)
    fb = m3 / (t * lw**2 / 6)
    fb_allow = share * 0.33 * fm
    interaction = fa / fa_allow + fb / fb_allow
    ft = share * 0.20  # Table 6.7.2, solid units, M2 mortar
    fv_allow = share * 0.025 * math.sqrt(fm)
    reference = Reference(
        source="BNBC 2020 Part 6 Sec 7.3.5(a)-(c), (f)(i), Eqs 6.7.1, 6.7.3, 6.7.6, 6.7.11, "
        "Table 6.7.2 (pp. 1005-1007); Sec 7.5.2-7.5.5 (p. 1022)",
        formula="Fa = (f'm/5)[1 - (h'/42t)³], Fb = 0.33 f'm, Ft = 0.20 MPa, Fv = 0.025√f'm, "
        "all × 0.5 without special inspection; fa/Fa + fb/Fb ≤ 1",
        steps=[
            "plain clay brick wall 4000 x 250 mm, h' = 3000 mm, f'm = 8 MPa, mortar M2",
            f"Fa = 0.5 × 8/5 × [1 - (3000/10500)³] = {fmt(fa_allow)} MPa; fa = {fmt(fa)} MPa",
            f"fb = M/S = {fmt(fb)} MPa, Fb = 0.5 × 0.33 × 8 = {fmt(fb_allow)} MPa",
            f"fa/Fa + fb/Fb = {fmt(interaction)}",
            f"Ft = 0.5 × 0.20 = {fmt(ft)} MPa; Fv = 0.5 × 0.025 √8 = {fmt(fv_allow)} MPa",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Fa", "MPa", fa_allow, rows["Axial stress fa ≤ Fa"]["capacity"], 0.01),
            Quantity(
                "fa/Fa + fb/Fb", "", interaction, rows["Combined fa/Fa + fb/Fb ≤ 1"]["demand"], 0.01
            ),
            Quantity("Ft", "MPa", ft, rows["Flexural tension fb - fa ≤ Ft"]["capacity"], 0.01),
            Quantity(
                "fb - fa", "MPa", fb - fa, rows["Flexural tension fb - fa ≤ Ft"]["demand"], 0.01
            ),
            # The check rows round to 0.01 MPa: Fv is compared through the method's function.
            Quantity("Fv", "MPa", fv_allow, share * A.allowable_wall_shear_plain(masonry), EXACT),
        ],
    )


def reinforced_section(_: Path) -> Outcome:
    from saengine.design import masonry_asd as A

    b, d, depth, steel, fm, moment = 1000.0, 150.0, 200.0, 500.0, 10.0, 10e6
    em = 750 * fm
    n = 200000 / em
    rho = steel / (b * d)
    k = math.sqrt((n * rho) ** 2 + 2 * n * rho) - n * rho
    j = 1 - k / 3
    fb = moment / (b * d * d) * 2 / (j * k)
    fs = moment / (steel * j * d)
    sigma, fs_found, c = A.cracked_section(depth, b, [(d, steel)], 0.0, moment, n)
    reference = Reference(
        source="BNBC 2020 Part 6 Sec 7.3.8 Eqs 6.7.12-6.7.13 (p. 1008), Sec 7.6.5.1 Eqs "
        "6.7.28-6.7.32 (pp. 1024-1025)",
        formula="n = Es/Em, Em = 750 f'm; k = √((nρ)² + 2nρ) - nρ, j = 1 - k/3; fb = (M/bd²)(2/jk), "
        "fs = M/(As j d)",
        steps=[
            f"strip 1000 x 200 mm, one layer 500 mm² at d = 150 mm, f'm = 10 MPa: n = {fmt(n)}",
            f"ρ = {fmt(rho)}, k = {fmt(k)}, j = {fmt(j)}",
            f"M = 10 kN·m: fb = {fmt(fb)} MPa, fs = {fmt(fs)} MPa",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("kd", "mm", k * d, c, EXACT),
            Quantity("fb", "MPa", fb, sigma, EXACT),
            Quantity("fs", "MPa", fs, fs_found, EXACT),
        ],
    )


CASES = [
    Case(
        "DY1",
        "Masonry: a plain brick wall by allowable stresses",
        "design",
        "Fa, the combined axial and bending ratio, the flexural tension and Ft, and Fv of a "
        "plain clay brick wall without special inspection (50 % stresses).",
        "Wall 4000 x 250 mm, 3000 mm high, f'm = 8 MPa, M2 mortar, P = 300 kN, V = 30 kN, M = "
        "300 kN·m in plane; masonry.masonry_wall_checks.",
        plain_wall,
    ),
    Case(
        "DY2",
        "Masonry: a reinforced section by working stresses",
        "design",
        "The neutral axis, the masonry and steel stresses of a reinforced masonry strip in "
        "bending on the cracked transformed section.",
        "Strip 1000 x 200 mm, 500 mm² at d = 150 mm, f'm = 10 MPa, M = 10 kN·m; "
        "masonry_asd.cracked_section.",
        reinforced_section,
    ),
]

"""Geotechnical benchmarks: the soil report's computations against hand calculations.

Each case builds a soil report (Part 1) with the borehole of the problem, runs SAEngine's own
functions (:mod:`saengine.soil`) on it, and works the same quantity out by hand, step by step,
with plain arithmetic: none of SAEngine's helpers are used for the reference.

Units: m, kPa, kN/m³; reported in kPa, mm and blows.
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path
from typing import Any

from saengine.library.soil import SoilReport
from saengine.soil import bearing, liquefaction, settlement, site_class
from saengine.soil.profile import Profile
from saengine.verification.cases.common import Case, Outcome, Quantity, Reference, fmt

#: Tolerance of a hand calculation the code reproduces in closed form.
EXACT = 0.005


def _profile(borehole: dict[str, Any], **design: Any) -> Profile:
    report = SoilReport.model_validate({"boreholes": [borehole], "design": design})
    return Profile(report, report.boreholes[0])


# ─────────────────────────────── D6: site class ───────────────────────────────

#: (depth [m], field N): one test every 3 m from 1.5 m; the borehole ends at 30 m.
D6_TESTS = [(1.5, 8), (4.5, 10), (7.5, 12), (10.5, 15), (13.5, 18), (16.5, 22), (19.5, 26),
            (22.5, 30), (25.5, 35), (28.5, 40)]  # fmt: skip


def site_class_case(_: Path) -> Outcome:
    borehole = {
        "id": "BH-1",
        "depth": 30000,
        "layers": [
            {"top": 0, "bottom": 9000, "soilType": "silt", "plasticityIndex": 4},
            {"top": 9000, "bottom": 30000, "soilType": "sand"},
        ],
        "spt": [{"depth": d * 1000, "N": n} for d, n in D6_TESTS],
    }
    result = site_class.site_class(_profile(borehole))

    # By hand: each test stands for the soil from midway to the test above to midway to the
    # one below; the first from 0, the last to 30 m.
    depths = [d for d, _ in D6_TESTS]
    bounds = [0.0] + [(a + b) / 2 for a, b in itertools.pairwise(depths)] + [30.0]
    thickness = [b - a for a, b in itertools.pairwise(bounds)]
    terms = [t / n for t, (_, n) in zip(thickness, D6_TESTS, strict=True)]
    n_bar = sum(thickness) / sum(terms)
    steps = [
        (
            "Ten tests at 1.5, 4.5, ..., 28.5 m with N = 8, 10, 12, 15, 18, 22, 26, 30, 35, 40; the "
            "borehole ends at 30 m"
        ),
        "Thicknesses each test stands for: "
        + ", ".join(f"{t:g}" for t in thickness)
        + f" m (sum {sum(thickness):g} m)",
        "di/Ni: " + ", ".join(fmt(t, 3) for t in terms) + f"; Σ = {fmt(sum(terms))}",
        f"N̄ = 30 / {fmt(sum(terms))} = {fmt(n_bar)} → 15 ≤ N̄ ≤ 50: site class SC",
    ]
    return Outcome(
        Reference(
            source="BNBC 2020 Part 6 Table 6.2.13 (N limits 15 and 50 between SD, SC and SB); "
            "the harmonic mean of ASCE 7-16 eq. 20.4-2",
            formula="N̄ = Σ di / Σ (di / Ni) over the top 30 m",
            steps=steps,
        ),
        [
            Quantity("Average N̄ over 30 m", "blows", n_bar, result["N"], 0.005),
            Quantity(
                "Site class (SC = 3 in SA..SE)",
                "-",
                3.0,
                float(site_class.ORDER.index(result["class"]) + 1),
                0.001,
            ),
        ],
        notes=["SAEngine reports N̄ rounded to 0.1; the 0.5 % tolerance covers that rounding."],
    )


# ─────────────────────────────── D7: bearing capacity ───────────────────────────────


def bearing_case(_: Path) -> Outcome:
    sand = _profile(
        {
            "id": "BH-1",
            "layers": [
                {"top": 0, "bottom": 10000, "soilType": "sand", "unitWeight": 18, "phi": 30}
            ],
        }
    )
    drained = bearing.shear(sand, 2.0, 2.0, 1.0, 3.0)
    clay = _profile(
        {
            "id": "BH-2",
            "waterTable": 0,
            "layers": [
                {
                    "top": 0,
                    "bottom": 10000,
                    "soilType": "clay",
                    "unitWeight": 18,
                    "saturatedUnitWeight": 18,
                    "cu": 50,
                }
            ],
        }
    )
    undrained = bearing.shear(clay, 2.0, 3.0, 1.5, 3.0)

    # By hand, sand: φ = 30°, c = 0, B = L = 2 m, Df = 1 m, γ = 18 kN/m³, water table deep.
    t = math.tan(math.radians(30))
    nq = math.exp(math.pi * t) * math.tan(math.radians(60)) ** 2
    ng = 2 * (nq + 1) * t
    sq, sg = 1 + t, 0.6
    dq = 1 + 2 * t * (1 - math.sin(math.radians(30))) ** 2 * (1.0 / 2.0)
    q = 18 * 1.0
    qu = q * nq * sq * dq + 0.5 * 18 * 2.0 * ng * sg
    qa = (qu - q) / 3
    # By hand, clay: cu = 50 kPa, B = 2, L = 3 m, Df = 1.5 m: qu - q = cu Nc sc dc.
    sc = 1 + (2 / 3) * (1 / 5.14)
    dc = 1 + 0.4 * (1.5 / 2.0)
    qa_clay = 50 * 5.14 * sc * dc / 3
    steps = [
        (
            "Sand: square footing B = L = 2 m at Df = 1 m, φ' = 30°, c' = 0, γ = 18 kN/m³, no water "
            "table; FS = 3"
        ),
        f"Nq = e^(π tan30°) tan²60° = {fmt(nq)}; Nγ = 2 (Nq + 1) tan30° = {fmt(ng)}",
        (
            f"sq = 1 + tan30° = {fmt(sq)}; sγ = 1 - 0.4 = 0.6; dq = 1 + 2 tan30° (1 - sin30°)² × "
            f"1/2 = {fmt(dq)}; dγ = 1"
        ),
        (
            f"q = 18 × 1 = 18 kPa; qu = q Nq sq dq + ½ γ B Nγ sγ = {fmt(q * nq * sq * dq)} + "
            f"{fmt(0.5 * 18 * 2 * ng * sg)} = {fmt(qu)} kPa"
        ),
        f"qa = (qu - γ Df)/FS = ({fmt(qu)} - 18)/3 = {fmt(qa)} kPa",
        "Clay: B = 2 m, L = 3 m at Df = 1.5 m, cu = 50 kPa (φ = 0), saturated",
        (
            f"Nc = 5.14, sc = 1 + (B/L)(Nq/Nc) = 1 + (2/3)(1/5.14) = {fmt(sc)}, dc = 1 + 0.4 Df/B "
            f"= {fmt(dc)}"
        ),
        f"qa = cu Nc sc dc / FS = 50 × 5.14 × {fmt(sc)} × {fmt(dc)} / 3 = {fmt(qa_clay)} kPa",
    ]
    return Outcome(
        Reference(
            source="General bearing capacity equation with Vesic's (1975) factors, De Beer's "
            "shape and Hansen's (1970) depth factors (Vesic 1975 in Winterkorn & Fang, "
            "Foundation Engineering Handbook; Das, Principles of Foundation Engineering)",
            formula="qu = c Nc sc dc + q Nq sq dq + ½ γ B Nγ sγ dγ;  qa = (qu - q)/FS",
            steps=steps,
        ),
        [
            Quantity("qu, sand", "kPa", qu, drained["qu"], EXACT),
            Quantity("qa (shear), sand", "kPa", qa, drained["qa"], EXACT),
            Quantity("qa (shear), undrained clay", "kPa", qa_clay, undrained["qa"], EXACT),
        ],
        notes=[
            (
                "geofound (MIT, Millen) capacity_vesic_1975 gives the same qu for the sand, 839.8 "
                "kPa; the test suite compares the two over several cases."
            )
        ],
    )


# ─────────────────────────────── D8: Schmertmann settlement ───────────────────────────────


def schmertmann_case(_: Path) -> Outcome:
    profile = _profile(
        {
            "id": "BH-1",
            "layers": [{"top": 0, "bottom": 20000, "soilType": "sand", "unitWeight": 18, "E": 20}],
        }
    )
    result = settlement.settlement(profile, 2.0, 2.0, 1.0, 150.0, years=0.1)

    # By hand: square footing, B = 2 m at Df = 1 m, net q = 150 kPa, E = 20 MPa, γ = 18.
    s0 = 18 * 1.0
    c1 = 1 - 0.5 * s0 / 150
    sigma_p = 18 * (1.0 + 1.0)
    izp = 0.5 + 0.1 * math.sqrt(150 / sigma_p)
    area = (0.1 + izp) / 2 * 1.0 + izp * 3.0 / 2
    s = c1 * 1.0 * 150 * area / 20_000 * 1000
    steps = [
        (
            "Square footing B = 2 m at Df = 1 m, net pressure q = 150 kPa; sand E = 20 MPa, γ = 18 "
            "kN/m³, no water table; t = 0.1 year (no creep, C2 = 1)"
        ),
        f"σ'v0 = 18 kPa; C1 = 1 - 0.5 × 18/150 = {fmt(c1)}",
        (
            f"Iz: 0.1 at the base, peak at B/2 = 1 m, 0 at 2B = 4 m; σ'vp = 18 × 2 = {sigma_p:g} "
            f"kPa; Izp = 0.5 + 0.1 √(150/36) = {fmt(izp)}"
        ),
        f"∫ Iz dz = (0.1 + {fmt(izp)})/2 × 1 + {fmt(izp)} × 3/2 = {fmt(area)} m",
        f"s = C1 C2 q ∫ Iz/E dz = {fmt(c1)} × 1 × 150 × {fmt(area)} / 20000 = {fmt(s)} mm",
    ]
    return Outcome(
        Reference(
            source="Schmertmann, Hartman & Brown (1978), Improved strain influence factor "
            "diagrams, J. Geotech. Eng. Div. ASCE 104(GT8)",
            formula="s = C1 C2 q Σ (Iz/Es) Δz,  C1 = 1 - 0.5 σ'v0/q,  Izp = 0.5 + 0.1 √(q/σ'vp)",
            steps=steps,
        ),
        [
            Quantity("Immediate settlement", "mm", s, result["immediate"], EXACT),
            Quantity("Peak strain influence Izp", "-", izp, result["Izp"], EXACT),
        ],
        notes=[
            (
                "The diagram is integrated in 50 mm slices at their midpoints; the peak falls on a "
                "slice boundary, so the integral of the piecewise linear Iz is exact."
            )
        ],
    )


# ─────────────────────────────── D9: liquefaction ───────────────────────────────


def liquefaction_case(_: Path) -> Outcome:
    profile = _profile(
        {
            "id": "BH-1",
            "waterTable": 2000,
            "layers": [
                {
                    "top": 0,
                    "bottom": 15000,
                    "soilType": "sand",
                    "unitWeight": 18,
                    "saturatedUnitWeight": 20,
                    "finesContent": 10,
                }
            ],
            "spt": [{"depth": 8000, "N": 15}],
        },
        hammerEnergy=60,
        liquefaction={"magnitude": 7.0, "pga": 0.3},
    )
    result = liquefaction.screen(profile, 0.3, "amax = 0.3 g")
    point = next(p for p in result["points"] if p["depth"] == 8000)
    raw = liquefaction.point(
        8.0, profile.spt[0].n60, profile.spt[0].sigma_v, profile.spt[0].sigma_v_eff, 10, 0.3, 7.0
    )

    # By hand.
    z, mw, amax, fc = 8.0, 7.0, 0.3, 10.0
    n60 = 15 * 60 / 60 * 0.95  # rod length 6-10 m: CR = 0.95
    sv = 18 * 2 + 20 * 6
    u = 9.81 * 6
    se = sv - u
    alpha = -1.012 - 1.126 * math.sin(z / 11.73 + 5.133)
    beta = 0.106 + 0.118 * math.sin(z / 11.28 + 5.142)
    r_d = math.exp(alpha + beta * mw)
    csr = 0.65 * sv / se * amax * r_d
    dn = math.exp(1.63 + 9.7 / (fc + 0.01) - (15.7 / (fc + 0.01)) ** 2)
    n = n60 + dn
    iterations = []
    for _ in range(50):
        m = 0.784 - 0.0768 * math.sqrt(n)
        cn = min(1.7, (101.325 / se) ** m)
        new = cn * n60 + dn
        iterations.append((m, cn, new))
        if abs(new - n) < 1e-9:
            break
        n = new
    crr = math.exp(n / 14.1 + (n / 126) ** 2 - (n / 23.6) ** 3 + (n / 25.4) ** 4 - 2.8)
    msf_max = min(2.2, 1.09 + (n / 31.5) ** 2)
    msf = 1 + (msf_max - 1) * (8.64 * math.exp(-mw / 4) - 1.325)
    c_sigma = min(0.3, 1 / (18.9 - 2.55 * math.sqrt(n)))
    k = min(1.1, 1 - c_sigma * math.log(se / 101.325))
    fs = crr * msf * k / csr
    steps = [
        (
            "Sand with FC = 10 %, γ = 18 kN/m³ above and γsat = 20 kN/m³ below the water table at 2 m; "
            "SPT N = 15 at 8 m, ER = 60 %; M = 7.0, amax = 0.30 g"
        ),
        f"N60 = 15 × 60/60 × CR (rod 6-10 m: 0.95) = {fmt(n60)}",
        f"σv = 18 × 2 + 20 × 6 = {fmt(sv)} kPa; u = 9.81 × 6 = {fmt(u)} kPa; σ'v = {fmt(se)} kPa",
        (
            f"α = -1.012 - 1.126 sin(8/11.73 + 5.133) = {fmt(alpha)}; β = 0.106 + 0.118 sin(8/11.28 "
            f"+ 5.142) = {fmt(beta)}; rd = exp(α + 7β) = {fmt(r_d)}"
        ),
        f"CSR = 0.65 × ({fmt(sv)}/{fmt(se)}) × 0.30 × {fmt(r_d)} = {fmt(csr)}",
        f"Δ(N1)60 = exp(1.63 + 9.7/10.01 - (15.7/10.01)²) = {fmt(dn)}",
        (
            f"Iteration on m = 0.784 - 0.0768 √(N1)60cs: {len(iterations)} rounds to m = "
            f"{fmt(iterations[-1][0])}, CN = (101.325/{fmt(se)})^m = {fmt(iterations[-1][1])}, "
            f"(N1)60cs = CN N60 + Δ = {fmt(n)}"
        ),
        f"CRR(M7.5, 1 atm) = exp(N/14.1 + (N/126)² - (N/23.6)³ + (N/25.4)⁴ - 2.8) = {fmt(crr)}",
        (
            f"MSFmax = 1.09 + (N/31.5)² = {fmt(msf_max)}; MSF = 1 + (MSFmax - 1)(8.64 e^(-7/4) - "
            f"1.325) = {fmt(msf)}"
        ),
        f"Cσ = 1/(18.9 - 2.55 √N) = {fmt(c_sigma)}; Kσ = 1 - Cσ ln(σ'v/pa) = {fmt(k)}",
        f"FS = CRR MSF Kσ / CSR = {fmt(crr)} × {fmt(msf)} × {fmt(k)} / {fmt(csr)} = {fmt(fs)}",
    ]
    return Outcome(
        Reference(
            source="Boulanger & Idriss (2014), CPT and SPT based liquefaction triggering "
            "procedures, Report UCD/CGM-14/01; SPT rod length factor of Youd et al. (2001)",
            formula="FS = CRR(M7.5, 1 atm) · MSF · Kσ / CSR,  CSR = 0.65 (σv/σ'v) amax rd",
            steps=steps,
        ),
        [
            Quantity("Stress reduction rd", "-", r_d, raw["rd"], EXACT),
            Quantity("CSR", "-", csr, raw["csr"], EXACT),
            Quantity("(N1)60cs", "blows", n, raw["N160cs"], EXACT),
            Quantity("CRR (M = 7.0, σ'v)", "-", crr * msf * k, raw["crr"], EXACT),
            Quantity("Factor of safety FS", "-", fs, raw["fs"], EXACT),
            Quantity("FS in the soil report (rounded to 0.01)", "-", fs, point["fs"], 0.01),
        ],
        notes=[
            (
                "The soil report rounds FS to 0.01; its 1 % tolerance covers that rounding. The "
                "other quantities are compared unrounded."
            ),
            (
                "liquepy (MIT, Millen) gives the same rd, CRR(M7.5) and Kσ (functions calc_rd, "
                "calc_crr_m7p5_from_n1_60cs and calc_k_sigma_w_n1_60cs); the test suite compares "
                "them."
            ),
        ],
    )


# ─────────────────────── D10: SPT corrections, Bangladesh consultant practice ───────────────────────

#: (depth [m], field N): water table at the ground; sand to 5 m (γsat 19), silt below (γsat 17).
D10_TESTS = [(1.5, 3), (4.5, 24), (7.5, 6)]


def consultant_spt_case(_: Path) -> Outcome:
    borehole = {
        "id": "BH-1",
        "waterTable": 0,
        "layers": [
            {"top": 0, "bottom": 5000, "soilType": "sand", "unitWeight": 19,
             "saturatedUnitWeight": 19},
            {"top": 5000, "bottom": 12000, "soilType": "silt", "unitWeight": 17,
             "saturatedUnitWeight": 17},
        ],
        "spt": [{"depth": d * 1000, "N": n} for d, n in D10_TESTS],
    }  # fmt: skip
    profile = _profile(borehole, practice="bdConsultant", hammerEnergy=60)

    # By hand: each row stands for the soil from the test above (or the ground) to its test;
    # σ'v at the row's mid-depth with the row's own γ' (not summed over the layers above).
    gw = 9.81
    rows = []
    above = 0.0
    for (depth, n), gamma_sat, cr in zip(
        D10_TESTS, (19.0, 19.0, 17.0), (0.75, 0.85, 0.95), strict=True
    ):
        mid = (above + depth) / 2
        sigma = mid * (gamma_sat - gw)
        cn = 0.77 * math.log10(2000 / sigma)
        n60 = n * 0.60 * 1.0 * 1.0 * cr / 0.6
        n160 = cn * n60
        n_prime = 15 + (n160 - 15) / 2 if n160 > 15 else n160
        rows.append((depth, n, mid, gamma_sat - gw, sigma, cn, cr, n60, n160, n_prime))
        above = depth
    steps = [
        (
            "Water table at the ground; sand γsat = 19 kN/m³ to 5 m, silt γsat = 17 kN/m³ "
            "below; SPT N = 3, 24, 6 at 1.5, 4.5, 7.5 m; Eh = 0.60, CB = CS = 1"
        ),
        "CR (Skempton 1986): 0.75 below 4 m, 0.85 for 4-6 m, 0.95 for 6-10 m of rod",
    ]
    for depth, n, mid, g, sigma, cn, cr, n60, n160, n_prime in rows:
        dilated = (
            f"N' = 15 + ({fmt(n160)} - 15)/2 = {fmt(n_prime)}"
            if n160 > 15
            else f"N' = (N1)60 = {fmt(n_prime)} (not above 15)"
        )
        steps.append(
            f"{depth:g} m: mid-depth {mid:g} m, σ'v = {mid:g} × {fmt(g)} = {fmt(sigma)} kPa; CN = "
            f"0.77 log10(2000/{fmt(sigma)}) = {fmt(cn)}; N60 = {n} × 0.60 × {cr:g}/0.6 = "
            f"{fmt(n60)}; (N1)60 = {fmt(cn)} × {fmt(n60)} = {fmt(n160)}; {dilated}"
        )
    quantities = []
    for (depth, _, _, _, _, cn, _, n60, n160, n_prime), test in zip(rows, profile.spt, strict=True):
        quantities += [
            Quantity(f"CN at {depth:g} m", "-", cn, test.cn, EXACT),
            Quantity(f"N60 at {depth:g} m", "blows", n60, test.n60, EXACT),
            Quantity(f"(N1)60 at {depth:g} m", "blows", n160, test.n160, EXACT),
            Quantity(f"N' at {depth:g} m", "blows", n_prime, float(test.n_prime or 0), EXACT),
        ]
    return Outcome(
        Reference(
            source="Peck, Hanson & Thornburn (1974) CN in SI units; Skempton (1986) rod length "
            "factors; Terzaghi & Peck dilatancy correction of submerged soil; as the SPT "
            "correction sheets of common Bangladesh soil reports apply them",
            formula="CN = 0.77 log10(2000/σ'v);  N60 = N Eh CR/0.6;  (N1)60 = CN N60;  "
            "N' = 15 + ((N1)60 - 15)/2 for (N1)60 > 15 below the water table",
            steps=steps,
        ),
        quantities,
        notes=[
            (
                "σ'v of each row is its mid-depth times its own effective unit weight, as the "
                "consultant sheets compute it; the cumulative σ'v at 6 m would be 5 × 9.19 + 1 × "
                "7.19 = 53.14 kPa instead of 43.14 kPa."
            )
        ],
    )


# ─────────────────────── D11: Meyerhof-Bowles with the zone-averaged N' ───────────────────────

#: (depth [m], field N): sand, γsat 19 kN/m³, water table at the ground.
D11_TESTS = [(1.5, 4), (3.0, 8), (4.5, 14), (6.0, 22), (7.5, 25), (9.0, 30)]


def consultant_bearing_case(_: Path) -> Outcome:
    borehole = {
        "id": "BH-1",
        "waterTable": 0,
        "layers": [
            {"top": 0, "bottom": 15000, "soilType": "sand", "unitWeight": 19,
             "saturatedUnitWeight": 19, "phi": 30},
        ],
        "spt": [{"depth": d * 1000, "N": n} for d, n in D11_TESTS],
    }  # fmt: skip
    profile = _profile(borehole, practice="bdConsultant", hammerEnergy=60)
    b, df = 2.0, 1.5
    result = bearing.allowable(profile, b, b, df)
    zone = bearing.zone_n_prime(profile, b, df)
    assert zone is not None
    qa_code = bearing.meyerhof_bowles_si(zone["N"], b, df, 25)

    # By hand: the N' of each row, rounded half up as the sheets print it.
    gw = 9.81
    printed = []
    above = 0.0
    lines = []
    for depth, n in D11_TESTS:
        mid = (above + depth) / 2
        sigma = mid * (19 - gw)
        cn = 0.77 * math.log10(2000 / sigma)
        cr = 0.75 if depth < 4 else 0.85 if depth < 6 else 0.95 if depth < 10 else 1.0
        n160 = cn * n * cr
        n_prime = 15 + (n160 - 15) / 2 if n160 > 15 else n160
        printed.append((above, depth, math.floor(n_prime + 0.5)))
        lines.append(f"{depth:g} m: (N1)60 = {fmt(n160)}, N' = {fmt(n_prime)} → {printed[-1][2]}")
        above = depth
    top, bottom = max(0.0, df - b / 2), df + 2 * b
    samples = []
    z = top + 0.5
    while z <= bottom + 1e-9:
        samples.append(next(v for a, d, v in printed if a < z <= d))
        z += 0.5
    n_avg = sum(samples) / len(samples)
    kd = min(1.33, 1 + 0.33 * df / b)
    qa = n_avg / 0.08 * ((b + 0.3) / b) ** 2 * kd
    steps = [
        (
            "Sand, γsat = 19 kN/m³, water table at the ground; SPT N = 4, 8, 14, 22, 25, 30 at "
            "1.5, 3, ..., 9 m (Eh = 0.60); square footing B = 2 m at Df = 1.5 m; Se = 25 mm"
        ),
        "N' per row (D10's chain: σ'v = mid-depth × 9.19, CN = 0.77 log10(2000/σ'v), CR of "
        "Skempton, dilatancy above 15), printed as a whole number: " + "; ".join(lines),
        (
            f"Influence zone max(0, Df - B/2) = {top:g} m to Df + 2B = {bottom:g} m; samples every "
            f"0.5 m from {top + 0.5:g} to {bottom:g} m, each the N' of its row (test above, "
            f"exclusive, to its test, inclusive): {', '.join(str(v) for v in samples)}"
        ),
        f"N' = {sum(samples)} / {len(samples)} = {fmt(n_avg)}",
        f"Kd = 1 + 0.33 × 1.5/2 = {fmt(kd)} (≤ 1.33)",
        (
            f"B > 1.2 m: qa = N'/0.08 ((B + 0.3)/B)² Kd = {fmt(n_avg)}/0.08 × (2.3/2)² × "
            f"{fmt(kd)} = {fmt(qa)} kPa"
        ),
    ]
    return Outcome(
        Reference(
            source="Meyerhof (1965) as modified by Bowles: Bowles (1996), Foundation Analysis and "
            "Design, 5th ed., eq. 4-12, F1 = 0.05, F2 = 0.08, F3 = 0.3 m, F4 = 1.2 m; the "
            "influence zone and the 0.5 m sampling of the Bangladesh consultant sheets",
            formula="qa = N'/F2 ((B + F3)/B)² Kd (B > F4),  Kd = 1 + 0.33 Df/B ≤ 1.33",
            steps=steps,
        ),
        [
            Quantity("Mean N' over the zone", "blows", n_avg, zone["N"], EXACT),
            Quantity("qa, 25 mm (Meyerhof-Bowles)", "kPa", qa, qa_code, EXACT),
            Quantity(
                "qa (settlement) in the bearing result (rounded to 0.1)",
                "kPa",
                qa,
                float(result["meyerhofBowles"]["qa"]),
                0.005,
            ),
        ],
        notes=[
            (
                "Bowles' SI form with N' replaces the textbook practice's 19.16 / 11.98 N60 form "
                "(Das) when the design option 'practice' is the Bangladesh consultant practice."
            )
        ],
    )


# ─────────────────────── D12: BNBC 2020 Sec 3.9.5 liquefaction ───────────────────────


def bnbc_liquefaction_case(_: Path) -> Outcome:
    profile = _profile(
        {
            "id": "BH-1",
            "waterTable": 2000,
            "layers": [
                {
                    "top": 0,
                    "bottom": 15000,
                    "soilType": "sand",
                    "unitWeight": 18,
                    "saturatedUnitWeight": 20,
                    "finesContent": 10,
                }
            ],
            "spt": [{"depth": 8000, "N": 15}],
        },
        hammerEnergy=60,
        liquefactionMethod="bnbc2020",
        liquefaction={"magnitude": 7.5},
    )
    amax_code, note = liquefaction.amax_from(None, 0.20, ["SD"])
    assert amax_code is not None
    result = liquefaction.screen(profile, amax_code, note)
    point = result["points"][0]
    test = profile.spt[0]
    raw = liquefaction.point_bnbc(
        8.0, test.n60, test.sigma_v, test.sigma_v_eff, 10.0, amax_code, 7.5
    )

    # By hand.
    z, mw = 8.0, 7.5
    amax = 2 / 3 * 0.20 * 1.35
    sv = 18 * 2 + 20 * 6
    se = sv - 9.81 * 6
    r_d = 1 - 0.015 * z
    csr = amax * r_d * sv / se
    n60 = 15 * 60 / 60 * 0.95
    cn = min(1.7, math.sqrt(101.325 / se))
    n160 = cn * n60
    alpha = math.exp(1.76 - 190 / 10**2)
    beta = 0.99 + 10**1.5 / 1000
    n = alpha + beta * n160
    crr = 1 / (34 - n) + n / 135 + 50 / (10 * n + 45) ** 2 - 1 / 200
    msf = 10**2.24 / mw**2.56
    k = min(1.0, (se / 101.325) ** (0.7 - 1))
    fs = crr * msf * k / csr
    steps = [
        (
            "Sand with FC = 10 %, γ = 18 kN/m³ above and γsat = 20 kN/m³ below the water table "
            "at 2 m; SPT N = 15 at 8 m, ER = 60 %; M = 7.5; Dhaka, zone 2, site class SD"
        ),
        (
            "amax = (2/3) Z S = (2/3) × 0.20 × 1.35 = 0.18 g, the design PGA of Sec 2.5.13.2 "
            "(Sec 2.5.3.1: liquefaction under design earthquake ground motions; Z of the zoning "
            "map, Table 6.2.14, the MCE PGA on rock, Sec 2.5.4.2; S of Table 6.2.16 for SD, the "
            "site amplification 3.9.5 asks for)"
        ),
        f"σv = 18 × 2 + 20 × 6 = {fmt(sv)} kPa; u = 9.81 × 6 = 58.86 kPa; σ'v = {fmt(se)} kPa",
        f"rd = 1 - 0.015 × 8 = {fmt(r_d)} (Eq 6.3.7b)",
        f"CSR = (amax/g) rd σv/σ'v = 0.18 × {fmt(r_d)} × {fmt(sv)}/{fmt(se)} = {fmt(csr)} (Eq 6.3.8)",
        (
            f"N60 = 15 × 60/60 × 0.95 = {fmt(n60)}; CN = (101.325/{fmt(se)})^0.5 = {fmt(cn)}; "
            f"(N1)60 = {fmt(n160)}"
        ),
        (
            f"FC = 10 %: α = exp(1.76 - 190/10²) = {fmt(alpha)}, β = 0.99 + 10^1.5/1000 = "
            f"{fmt(beta)}; (N1)60cs = α + β (N1)60 = {fmt(n)}"
        ),
        (
            f"CRR7.5 = 1/(34 - N) + N/135 + 50/(10N + 45)² - 1/200 = {fmt(crr)}; MSF = "
            f"10^2.24/7.5^2.56 = {fmt(msf)}; Kσ = 1 (σ'v < pa)"
        ),
        (
            f"FL = CRR MSF Kσ / CSR = {fmt(crr)} × {fmt(msf)} × {fmt(k)} / {fmt(csr)} = {fmt(fs)} "
            f"(Eq 6.3.6): {'< 1, liquefies' if fs < 1 else '≥ 1, does not liquefy'}"
        ),
    ]
    return Outcome(
        Reference(
            source="BNBC 2020 Part 6 Sec 3.9.5, Eqs 6.3.6, 6.3.7b and 6.3.8; CRR of Youd et al. "
            "(2001), J. Geotech. Geoenviron. Eng. 127(10), eqs. 4, 6, 7 and 9, with Idriss's MSF "
            "(permitted by BNBC 3.9.5: CRR 'can be obtained by several procedures')",
            formula="FL = CRR/CSR,  CSR = (amax/g) rd σv/σ'v,  rd = 1 - 0.015 z",
            steps=steps,
        ),
        [
            Quantity("amax = (2/3) Z S", "g", amax, amax_code, EXACT),
            Quantity("Stress reduction rd", "-", r_d, float(raw["rd"] or 0), EXACT),
            Quantity("CSR", "-", csr, float(raw["csr"] or 0), EXACT),
            Quantity("(N1)60cs", "blows", n, float(raw["N160cs"] or 0), EXACT),
            Quantity("CRR (M = 7.5, σ'v)", "-", crr * msf * k, float(raw["crr"] or 0), EXACT),
            Quantity("Factor of safety FL", "-", fs, float(raw["fs"] or 0), EXACT),
            Quantity("FL in the soil report (rounded to 0.01)", "-", fs, point["fs"], 0.01),
        ],
        notes=[
            (
                "BNBC's Eq 6.3.8 divides Eq 6.3.7a by σ'v and carries no 0.65 factor; the Youd et "
                "al. curve is calibrated against 0.65 τmax, so the code's CSR is 1.54 times that "
                "basis, on the safe side."
            )
        ],
    )


CASES = [
    Case(
        "D6",
        "Site class from an SPT profile",
        "design",
        "BNBC 2020 site class of a 30 m borehole from the harmonic mean of its field N values.",
        "Borehole 30 m deep: non-plastic silt to 9 m on sand; ten SPT tests every 3 m from 1.5 "
        "m, N from 8 to 40; site_class.site_class.",
        site_class_case,
    ),
    Case(
        "D7",
        "Allowable bearing pressure against shear failure",
        "design",
        "Net allowable pressure of a square footing on sand (drained, φ' = 30°) and of a "
        "rectangular footing on saturated clay (undrained, cu = 50 kPa), FS = 3.",
        "Sand: B = L = 2 m, Df = 1 m, γ = 18 kN/m³, water table deep. Clay: B = 2 m, L = 3 m, "
        "Df = 1.5 m, water table at the ground. bearing.shear.",
        bearing_case,
    ),
    Case(
        "D8",
        "Schmertmann settlement of a footing on sand",
        "design",
        "Immediate settlement of a square footing on sand by the strain influence factor method "
        "(Schmertmann et al. 1978).",
        "B = L = 2 m at Df = 1 m, net q = 150 kPa, E = 20 MPa, γ = 18 kN/m³, no water table, "
        "no creep; settlement.settlement.",
        schmertmann_case,
    ),
    Case(
        "D9",
        "Liquefaction factor of safety at one SPT test",
        "design",
        "Idriss & Boulanger (2014) SPT triggering: CSR, (N1)60cs with the fines correction, "
        "CRR with MSF and Kσ, and FS at one depth.",
        "Sand, FC = 10 %, water table at 2 m, N = 15 at 8 m (ER 60 %), M = 7.0, amax = 0.30 g; "
        "liquefaction.screen and liquefaction.point.",
        liquefaction_case,
    ),
    Case(
        "D10",
        "SPT corrections of the Bangladesh consultant practice",
        "design",
        "CN of Peck, Hanson & Thornburn with each row's own σ'v, N60 with Skempton's rod "
        "factors, (N1)60 and the dilatancy-corrected N' for three SPT rows.",
        "Water table at the ground; sand (γsat 19) to 5 m on silt (γsat 17); N = 3, 24, 6 at "
        "1.5, 4.5, 7.5 m, Eh 0.60; practice bdConsultant; profile.Profile.",
        consultant_spt_case,
    ),
    Case(
        "D11",
        "Meyerhof-Bowles bearing pressure with the zone-averaged N'",
        "design",
        "Settlement-controlled net allowable pressure (25 mm) of a square footing with Bowles' "
        "SI form and N' averaged every 0.5 m over max(0, Df - B/2) to Df + 2B.",
        "Sand, γsat 19, water table at the ground; N = 4 to 30 every 1.5 m to 9 m; B = 2 m, "
        "Df = 1.5 m; bearing.zone_n_prime and bearing.allowable.",
        consultant_bearing_case,
    ),
    Case(
        "D12",
        "Liquefaction factor of safety by BNBC 2020 Sec 3.9.5",
        "design",
        "FL = CRR/CSR with the code's CSR (Eq 6.3.8, rd = 1 - 0.015 z) and the CRR of Youd et "
        "al. (2001) at one depth; amax = (2/3) Z S, the design PGA from the zoning map and the site factor.",
        "Sand, FC = 10 %, water table at 2 m, N = 15 at 8 m (ER 60 %), M = 7.5, Z = 0.20, SD; "
        "liquefaction.amax_from, liquefaction.screen and liquefaction.point_bnbc.",
        bnbc_liquefaction_case,
    ),
]

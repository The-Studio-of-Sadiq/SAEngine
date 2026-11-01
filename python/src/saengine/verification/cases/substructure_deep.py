"""Deep foundation and raft benchmarks (Part 9): piles, pile caps and rafts on springs.

Each case builds a synthetic borehole or raft, runs SAEngine's own functions
(:mod:`saengine.substructure.piles`, :mod:`saengine.substructure.pilecap`,
:mod:`saengine.substructure.raft`) and works the same quantities out by hand, step by step:
closed-form integrals and plain arithmetic, none of SAEngine's helpers.

Units: m, kPa, kN; reported in kN, kPa and mm.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from saengine.library.objects import BarMesh
from saengine.library.soil import SoilReport
from saengine.soil.profile import GAMMA_W, Profile
from saengine.verification.cases.common import (
    _DERIVE,
    Case,
    Outcome,
    Quantity,
    Reference,
    fmt,
)

#: Tolerance of a hand calculation the code reproduces (rounded to 0.1 kN or integrated in
#: 0.1 m slices).
CLOSE = 0.005


def _profile(borehole: dict[str, Any], **design: Any) -> Profile:
    report = SoilReport.model_validate(
        {"boreholes": [borehole], "design": {"hammerEnergy": 60, **design}}
    )
    return Profile(report, report.boreholes[0])


#: Soft-to-firm clay (cu = 50 kPa) to 10 m on medium dense sand (N60 = 20), water at the ground.
TWO_LAYERS = {
    "id": "BH-1",
    "waterTable": 0,
    "depth": 30000,
    "layers": [
        {
            "top": 0,
            "bottom": 10000,
            "soilType": "clay",
            "unitWeight": 18,
            "saturatedUnitWeight": 18,
            "cu": 50,
        },
        {
            "top": 10000,
            "bottom": 30000,
            "soilType": "sand",
            "unitWeight": 19,
            "saturatedUnitWeight": 19,
        },
    ],
    "spt": [{"depth": d * 1000, "N": 20} for d in (12, 15, 18, 21, 24, 27)],
}


# ─────────────────────────────── DP1: bored pile, soil report method ───────────────────────────


def bored_pile_case(_: Path) -> Outcome:
    from saengine.substructure.piles import single_pile

    result = single_pile(_profile(TWO_LAYERS), "bored", 0.5, 18.0, 1.5)

    d, length, head = 0.5, 18.0, 1.5
    tip = head + length
    perimeter, area = math.pi * d, math.pi * d * d / 4
    alpha = 0.55
    qs_clay = alpha * 50 * perimeter * (10.0 - head - 1.5)
    g1, g2 = 18 - GAMMA_W, 19 - GAMMA_W
    a, b = 10 * g1 - 10 * g2, g2

    k = 0.135 / math.sqrt(0.3)  # β = 1.5 - 0.135 √(z/Br), Br = 0.3 m

    def integral(z: float) -> float:
        return 1.5 * (a * z + b * z * z / 2) - k * (a * z**1.5 / 1.5 + b * z**2.5 / 2.5)

    qs_sand = perimeter * (integral(tip) - integral(10.0))
    qs = qs_clay + qs_sand
    qb = 0.60 * 100 * 20 * area
    weight = 24 * area * length
    q_ult = qs + qb - weight
    qa = min(q_ult / 3.0, qs / 1.5 + qb / 3.0 - weight)
    ta = (0.7 * qs + weight) / 3.0
    steps = [
        (
            "Bored pile D = 0.5 m, L = 18 m, head 1.5 m below the ground (tip at 19.5 m); clay "
            "cu = 50 kPa (γ 18) to 10 m on sand N60 = 20 (γ 19), water table at the ground"
        ),
        (
            f"Clay, α = 0.55 (cu ≤ 190 kPa), no side resistance over the top 1.5 m of the shaft: "
            f"Qs = 0.55 × 50 × π 0.5 × (10 - 3) = {fmt(qs_clay)} kN"
        ),
        (
            f"Sand, β = 1.5 - 0.135 √(z/0.3) (0.72 to 0.41 here, below 1.2), σ'v = "
            f"{fmt(10 * g1)} + {fmt(g2)} (z - 10) kPa: Qs = π D ∫ β σ'v dz from 10 to 19.5 m = "
            f"{fmt(qs_sand)} kN (closed form)"
        ),
        (
            f"Qb = 0.60 σr N60 × A = 0.60 × 100 × 20 = 1200 kPa (≤ 4500; N60 the test below the "
            f"base) × {fmt(area)} = {fmt(qb)} kN; W = 24 A L = {fmt(weight)} kN"
        ),
        (
            "No load test at the site: BNBC Sec 3.10.1.18 asks an overall FS of at least 3.0 in "
            "compression (Table 6.3.10a's 2.5 for normal control assumes load test data, Table "
            "6.3.10b); uplift by analysis also at least 3.0 (Sec 3.11.3)"
        ),
        (
            f"Qult = Qs + Qb - W = {fmt(q_ult)} kN; Qa = min(Qult/3.0, Qs/1.5 + Qb/3 - W) = "
            f"min({fmt(q_ult / 3.0)}, {fmt(qs / 1.5 + qb / 3 - weight)}) = {fmt(qa)} kN"
        ),
        f"Uplift: Ta = (0.7 Qs + W)/3.0 = {fmt(ta)} kN",
    ]
    return Outcome(
        Reference(
            source="BNBC 2020 Part 6 Sec 3.10.6.7, Eqs 6.3.42, 6.3.47 and 6.3.48 (drilled "
            "shafts: α, β, qb); Eqs 6.3.11-6.3.13, Sec 3.10.1.18 (FS ≥ 3.0 without a load test; "
            "partial 1.5 and 3.0) and Sec 3.11.3 (uplift FS ≥ 3.0 by analysis)",
            formula="Qs = π D ∫ fs dz, Qb = qb A, Qult = Qs + Qb - W, Qa = min(Qult/FS, Qs/1.5 + "
            "Qb/3 - W), Ta = (0.7 Qs + W)/FS",
            steps=steps,
        ),
        [
            Quantity("Skin friction Qs", "kN", qs, result["Qs"], CLOSE),
            Quantity("End bearing Qb", "kN", qb, result["Qb"], CLOSE),
            Quantity("Allowable compression Qa", "kN", qa, result["Qa"], CLOSE),
            Quantity("Allowable uplift Ta", "kN", ta, result["Ta"], CLOSE),
        ],
        notes=[
            (
                "SAEngine integrates fs over 0.1 m slices at their midpoints (the β σ'v product is "
                "smooth, the midpoint error is below 0.01 %) and rounds to 0.1 kN."
            )
        ],
    )


# ─────────────────────────────── DP2: BNBC SPT relations ───────────────────────────────


def spt_pile_case(_: Path) -> Outcome:
    from saengine.substructure.piles import single_pile

    borehole = {
        "id": "BH-2",
        "waterTable": 0,
        "depth": 30000,
        "layers": [
            {"top": 0, "bottom": 8000, "soilType": "clay"},
            {"top": 8000, "bottom": 30000, "soilType": "sand"},
        ],
        "spt": [
            {"depth": 3000, "N": 10},
            {"depth": 6000, "N": 10},
            *({"depth": d * 1000, "N": 25} for d in (9, 12, 15, 18, 21, 24, 27)),
        ],
    }
    profile = _profile(borehole, spt={"rodLength": False})
    result = single_pile(profile, "bored", 0.6, 20.0, 1.0, "spt")
    d, area = 0.6, math.pi * 0.36 / 4
    perimeter = math.pi * d
    fs_clay = min(1.2 * 10, 70)
    fs_sand = min(1.0 * 25, 60)
    qs = perimeter * (fs_clay * 7.0 + fs_sand * 13.0)
    embed = 13.0  # tip at 21 m, 13 m into the sand
    n_tip = 25.0
    fb = min(15 * n_tip * embed / d, 150 * n_tip, 4000)
    qb = fb * area
    weight = 24 * area * 20.0
    q_ult = qs + qb - weight
    qa = min(q_ult / 3.5, qs / 1.5 + qb / 3.0 - weight)
    steps = [
        (
            "Bored pile D = 0.6 m, L = 20 m from 1 m (tip 21 m); clay N60 = 10 to 8 m on sand "
            "N60 = 25 (ER 60 %, no rod correction)"
        ),
        f"Clay, Eq 6.3.29: fs = 1.2 × 10 = {fs_clay:g} kPa (≤ 70) over 7 m",
        f"Sand, Eq 6.3.31: fs = 1.0 × 25 = {fs_sand:g} kPa (≤ 60) over 13 m",
        f"Qs = π 0.6 (12 × 7 + 25 × 13) = {fmt(qs)} kN",
        (
            f"Eq 6.3.33: fb = 15 N60 L/D = 15 × 25 × 13/0.6 = {fmt(15 * 25 * 13 / 0.6)}, ≤ 150 "
            f"N60 = 3750 and ≤ 4000 kPa → {fmt(fb)} kPa; Qb = {fmt(qb)} kN"
        ),
        (
            f"Qult = Qs + Qb - W = {fmt(qs)} + {fmt(qb)} - {fmt(weight)} = {fmt(q_ult)} kN; FS 3.5 "
            f"for the SPT relations: Qa = min(Qult/3.5, Qs/1.5 + Qb/3 - W) = {fmt(qa)} kN"
        ),
    ]
    return Outcome(
        Reference(
            source="BNBC 2020 Part 6 Secs 3.10.4.5 and 3.10.4.7, Eqs 6.3.29, 6.3.31 and 6.3.33 "
            "(FS 3.5); Eqs 6.3.11-6.3.13",
            formula="fs = 1.2 N̄60 ≤ 70 (clay), 1.0 N̄60 ≤ 60 (sand); fb = 15 N60 L/D ≤ 150 N60, "
            "≤ 4000 kPa",
            steps=steps,
        ),
        [
            Quantity("Skin friction Qs", "kN", qs, result["Qs"], CLOSE),
            Quantity("Unit end bearing fb", "kPa", fb, result["qb"], CLOSE),
            Quantity("Allowable compression Qa", "kN", qa, result["Qa"], CLOSE),
        ],
        notes=[
            (
                "L in Eq 6.3.33 is taken as the embedment in the bearing layer (Meyerhof's "
                "meaning); here 13 m, so the 150 N60 cap governs either way."
            )
        ],
    )


# ─────────────────────────────── DP5: static method ───────────────────────────────

#: TWO_LAYERS with φ' = 35° given in the sand.
STATIC_LAYERS = {
    **TWO_LAYERS,
    "layers": [TWO_LAYERS["layers"][0], {**TWO_LAYERS["layers"][1], "phi": 35}],
}


def _static_hand() -> dict[str, float]:
    """DP5 by hand: driven 0.4 m square pile, 14 m from 1 m (tip 15 m, 5 m into the sand)."""
    b, length, head = 0.4, 14.0, 1.0
    perimeter, area = 4 * b, b * b
    alpha = 1 - (50 - 25) / 70  # Eq 6.3.16, 25 < cu < 70
    qs_clay = alpha * 50 * perimeter * (10.0 - head)
    beta = 0.20  # Eq 6.3.23 at φ' 35°
    zc = 15 * b  # medium dense sand (10 ≤ N60 < 30): Dc = 15 D = 6 m
    sigma_c = zc * (18 - GAMMA_W)  # σ'v at 6 m, in the clay
    qs_sand = beta * sigma_c * perimeter * 5.0
    nq = min(12 + (40 - 12) * (20 - 10) / (30 - 10), 73.8)  # Eq 6.3.24 range; Fig 6.3.2: 73.8
    fb = min(sigma_c, 240) * nq
    qs = qs_clay + qs_sand
    qb = fb * area
    weight = 24 * area * length
    return {
        "alpha": alpha,
        "qs_clay": qs_clay,
        "sigma_c": sigma_c,
        "qs_sand": qs_sand,
        "nq": nq,
        "fb": fb,
        "Qs": qs,
        "Qb": qb,
        "W": weight,
        "Qult": qs + qb - weight,
    }


def static_pile_case(_: Path) -> Outcome:
    from saengine.substructure.piles import single_pile

    result = single_pile(_profile(STATIC_LAYERS), "driven", 0.4, 14.0, 1.0, "static")
    h = _static_hand()
    steps = [
        (
            "Driven precast pile 0.4 m square (perimeter 1.6 m, area 0.16 m²), L = 14 m from 1 m "
            "(tip at 15 m); clay cu 50 kPa (γ 18) to 10 m on sand N60 20, φ' 35° (γ 19); water "
            "at the ground"
        ),
        (
            f"Clay, Eq 6.3.16: α = 1 - (50 - 25)/70 = {h['alpha']:.4f}; Qs = α cu × 1.6 × 9 = "
            f"{fmt(h['qs_clay'])} kN"
        ),
        (
            "Sand, Eq 6.3.23: β = 0.20 at φ' 35°; medium dense (N60 20): critical depth 15 D = "
            f"6 m (Sec 3.10.1.15), so σ'v = 6 × 8.19 = {fmt(h['sigma_c'])} kPa below it; "
            f"Qs = 0.20 × σ'v × 1.6 × 5 = {fmt(h['qs_sand'])} kN"
        ),
        (
            f"Base, Eq 6.3.24: Nq = the lesser of 12 + 28 (20 - 10)/20 = 26 (medium sand) and "
            f"Fig 6.3.2 at 35° (73.8) = {fmt(h['nq'])}; fb = σ'v Nq = {fmt(h['fb'])} kPa "
            f"(σ'v ≤ 240); Qb = {fmt(h['Qb'])} kN"
        ),
        f"Qult = Qs + Qb - W = {fmt(h['Qult'])} kN",
    ]
    return Outcome(
        Reference(
            source="BNBC 2020 Part 6 Secs 3.10.1.11-3.10.1.15, Eqs 6.3.16, 6.3.23, 6.3.24, Fig "
            "6.3.2; Table 6.3.9a (sand density by N)",
            formula="fs = α cu (clay), β σ'v (sand); fb = σ'v Nq; σ'v constant below Dc",
            steps=steps,
        ),
        [
            Quantity("Skin friction Qs", "kN", h["Qs"], result["Qs"], CLOSE),
            Quantity("Unit end bearing fb", "kPa", h["fb"], result["qb"], CLOSE),
            Quantity("Ultimate capacity Qult", "kN", h["Qult"], result["Qult"], CLOSE),
        ],
        notes=[
            "The critical depth is measured from the ground; the clay above the sand is "
            "shallower than 6 m only in part, so the sand's σ'v is that at 6 m throughout."
        ],
    )


# ─────────────────────────────── DP6: pile settlement ───────────────────────────────


def settlement_case(_: Path) -> Outcome:
    from saengine.substructure import pile_settlement
    from saengine.substructure.piles import single_pile

    profile = _profile(STATIC_LAYERS)
    pile = single_pile(profile, "driven", 0.4, 14.0, 1.0, "static")
    ep = 4700 * math.sqrt(30)
    single = pile_settlement.single_settlement(pile, 300.0, profile, ep)
    h = _static_hand()
    b, length, area = 0.4, 14.0, 0.16
    qp = 300 * h["Qb"] / (h["Qs"] + h["Qb"])
    qs = 300 - qp
    share = h["qs_clay"] / h["Qs"]
    a = share * 0.5 + (1 - share) * 0.67
    s_ax = (qp + a * qs) * length / (area * ep * 1e3)
    cp = 0.04  # Table 6.3.13, driven pile, loose sand (N60 20 is below 30: not dense)
    s_pt = cp * qp / (b * h["fb"])
    cs = (0.93 + 0.16 * length / b) * cp
    s_sf = cs * qs / (length * h["fb"])
    st = (s_ax + s_pt + s_sf) * 1e3
    group = pile_settlement.group_settlement(profile, pile, 4, 2.0, 2.0, 1200.0, ep)
    short = max(st * (2.0 / b) ** 0.5, st * 4**0.5)
    steps = [
        (
            f"The DP5 pile under Q = 300 kN: Qp = Q Qb/(Qs + Qb) = {fmt(qp)} kN, Qs = "
            f"{fmt(qs)} kN; a = {a:.3f} (0.5 over the clay's share of Qs, 0.67 over the sand's)"
        ),
        (
            f"Eq 6.3.35b: Sax = (Qp + a Qs) L / (A Ep) = {fmt(s_ax * 1e3)} mm, Ep = 4700 √30 "
            f"= {fmt(ep)} MPa"
        ),
        f"Eq 6.3.35c: Spt = Cp Qp / (D qo), Cp 0.04 (loose sand, driven) = {fmt(s_pt * 1e3)} mm",
        (
            f"Eq 6.3.36: Cs = (0.93 + 0.16 L/D) Cp = {cs:.4f}; Ssf = Cs Qs / (L qo) = "
            f"{fmt(s_sf * 1e3)} mm (L for the printed D: see the code pack's note)"
        ),
        f"St = {fmt(st)} mm",
        (
            f"Group of 4, 2 × 2 m: Eq 6.3.37 St (B/D)^0.5 = {fmt(st * 5**0.5)} mm, Eq 6.3.38 "
            f"St n^0.5 = {fmt(st * 2)} mm; the larger {fmt(short)} mm"
        ),
    ]
    return Outcome(
        Reference(
            source="BNBC 2020 Part 6 Sec 3.10.5, Eqs 6.3.35a-c, 6.3.36, 6.3.37, 6.3.38, Table "
            "6.3.13",
            formula="St = Sax + Spt + Ssf; Sg = max(St (B/D)^0.5, St n^0.5)",
            steps=steps,
        ),
        [
            Quantity("Single pile settlement St", "mm", st, single["total"], 0.01),
            Quantity("Group short-term settlement", "mm", short, group["shortTerm"], 0.01),
        ],
        notes=["Settlements are rounded to 0.01 mm."],
    )


# ─────────────────────────────── DP3: pile cap ───────────────────────────────


def pile_cap_case(_: Path) -> Outcome:
    from saengine.substructure.pilecap import CapSpec, cap_checks, pile_reactions
    from saengine.substructure.shallow import ColumnBase

    mesh = BarMesh(dia=20, spacing=150)
    spec = CapSpec(
        "PC1", 2500, 2500, 900, 75, 28, 420, [ColumnBase("C1", 0, 0, 500, 500)],
        [(-750, -750), (750, -750), (750, 750), (-750, 750)], 500, mesh, mesh,
    )  # fmt: skip
    loads = [np.array([2500e3, 200e6, 300e6])]
    reactions, _ = pile_reactions(spec, loads)
    checks, _ = cap_checks(spec, {"U": loads})
    by_name = {c["name"].split(" (")[0]: c for c in checks}

    p, mu, mv, s = 2500.0, 200.0, 300.0, 0.75
    r_max = p / 4 + mv * s / (4 * s * s) + mu * s / (4 * s * s)
    # Flexure at the +u face: the two piles at u = +0.75, 0.5 m from the face.
    r_plus_u = [p / 4 + mv / (4 * s) - mu * v / (4 * s * s) for v in (-s, s)]
    moment = sum(r_plus_u) * 0.5
    d = (815 + 795) / 2
    half = 250 + d / 2
    share_inside = 1 - (750 - half + 250) / 500
    vu = p - p * share_inside  # the four reactions sum to P
    b0 = 8 * half
    lam = math.sqrt(2 / (1 + 0.004 * d))
    vc = min(0.33, 0.17 * 3, 0.083 * (2 + 40 * d / b0)) * lam * math.sqrt(28)
    steps = [
        (
            "Cap 2.5 × 2.5 × 0.9 m on four Ø500 piles at (±0.75, ±0.75) m; column 0.5 × 0.5 m; "
            "Pu = 2500 kN, Mu (about u) = 200 kN·m, Mv (about v) = 300 kN·m; Ø20 @ 150 both "
            "ways, cover 75 mm"
        ),
        (
            f"Rigid cap: R = P/4 + Mv u/Σu² - Mu v/Σv², Σu² = Σv² = 4 × 0.75² = 2.25 m²: "
            f"Rmax = 625 + 300 × 0.75/2.25 + 200 × 0.75/2.25 = {fmt(r_max)} kN"
        ),
        (
            f"Flexure at the +u face: (R(0.75, -0.75) + R(0.75, 0.75)) × (0.75 - 0.25) = "
            f"({fmt(r_plus_u[0])} + {fmt(r_plus_u[1])}) × 0.5 = {fmt(moment)} kN·m"
        ),
        (
            f"Punching: d = (815 + 795)/2 = {fmt(d)} mm, section {fmt(2 * half)} mm square; each "
            f"pile centre {fmt(750 - half)} mm outside it: ACI 13.4.2.5 takes "
            f"{fmt(1 - share_inside)} of its reaction outside; Vu = {fmt(vu)} kN"
        ),
        (
            f"b0 = {fmt(b0)} mm, λs = {fmt(lam)}, vc = min(0.33, 0.51, 0.083(2 + 40 d/b0)) λs "
            f"√f'c = {fmt(vc)} MPa; φVc = 0.75 vc b0 d = {fmt(0.75 * vc * b0 * d / 1e3)} kN"
        ),
    ]
    return Outcome(
        Reference(
            source="Rigid pile cap statics; ACI 318-19 13.4.2.5 (pile reactions on a section), "
            "22.6.4.1 and 22.6.5.2 (two-way shear), 22.5.5.1.3 (λs)",
            formula="R = P/n + Mv u/Σu² - Mu v/Σv²;  vc = min(0.33, 0.17(1 + 2/β), 0.083(2 + αs "
            "d/b0)) λs √f'c",
            steps=steps,
        ),
        [
            Quantity("Largest pile reaction", "kN", r_max, float(reactions.max()) / 1e3, 1e-6),
            Quantity(
                "Moment at the +u column face",
                "kN·m",
                moment,
                by_name["Flexure bottom X at the column face"]["demand"],
                CLOSE,
            ),
            Quantity(
                "Punching Vu at the column", "kN", vu, by_name["Punching at C1"]["demand"], CLOSE
            ),
            Quantity(
                "Punching φVc at the column",
                "kN",
                0.75 * vc * b0 * d / 1e3,
                by_name["Punching at C1"]["capacity"],
                CLOSE,
            ),
        ],
        notes=[
            (
                "The +u face carries the larger of the two face moments here: Mv adds to the +u "
                "piles; Mu adds as much to one +u pile as it takes off the other."
            )
        ],
    )


# ─────────────────────────────── DP4: raft on springs ───────────────────────────────


def raft_case(folder: Path) -> Outcome:
    from saengine.substructure.raft import RaftColumn, RaftSpec, run_raft

    h, e, nu, ks, p = 0.3, 25e9, 0.2, 20000.0, 1000e3
    stiffness = e * h**3 / (12 * (1 - nu**2))
    k = ks * 1e3
    length = (stiffness / k) ** 0.25
    w0 = p / (8 * math.sqrt(k * stiffness))
    spec = RaftSpec(
        "R1", [(-8000, -8000), (8000, -8000), (8000, 8000), (-8000, 8000)], h * 1e3, e / 1e6,
        25, 420, None, [RaftColumn("C1", 0, 0, 400, 400)], ks, nu=nu, unit_weight=0,
        surcharge=0, mesh_size=500, compression_only=False,
    )  # fmt: skip
    uniform = RaftSpec(
        "R2", [(0, 0), (6000, 0), (6000, 4000), (0, 4000)], 500, 25000, 25, 420, None, [], ks,
        unit_weight=0, surcharge=100, mesh_size=1000,
    )  # fmt: skip
    with _DERIVE:  # Gmsh: one mesh at a time
        point = run_raft(spec, {"P": ([np.array([p, 0.0, 0.0])], 1.0)}, folder / "point")
        flat = run_raft(uniform, {"q": ([], 1.0)}, folder / "uniform")
    centre = float(-point.w["P"].min())
    settle = float(-flat.w["q"].mean()) * 1e3
    steps = [
        (
            "Uniform 100 kPa on a 6 × 4 m raft on springs ks = 20000 kN/m³ (consistent nodal "
            "shares for both the springs and the load): s = q/ks = 100/20000 = 5 mm everywhere"
        ),
        (
            f"Point load P = 1000 kN at the centre of a 16 × 16 m plate, h = 0.3 m, E = 25 GPa, "
            f"ν = 0.2: D = E h³/(12(1 - ν²)) = {fmt(stiffness)} N·m, k = 2×10⁷ N/m³, l = (D/k)^¼ "
            f"= {fmt(length)} m (the plate is {fmt(16 / length)} l wide: practically infinite)"
        ),
        (
            f"Westergaard / Hetényi, infinite plate on a Winkler foundation: w(0) = P/(8 √(k D)) "
            f"= {fmt(w0 * 1e3)} mm"
        ),
    ]
    return Outcome(
        Reference(
            source="Winkler foundation; Westergaard (1926) / Hetényi (1946), Beams on Elastic "
            "Foundation: the infinite plate under a point load",
            formula="s = q/ks;  w(0) = P / (8 √(k D)),  D = E h³ / (12 (1 - ν²))",
            steps=steps,
        ),
        [
            Quantity("Uniform settlement q/ks", "mm", 5.0, settle, 1e-4),
            Quantity("Point load, deflection under the load", "mm", w0 * 1e3, centre * 1e3, 0.03),
        ],
        notes=[
            (
                "ASDShellQ4 is a thick (Mindlin) plate: under a point load it adds a shear "
                "deflection the thin-plate closed form leaves out (+1.9 % at the 0.5 m mesh, "
                "growing slowly as the mesh is refined); at a distance of l and 2 l from the load "
                "the deflections agree with Hetényi's kei solution within 2 % (test suite)."
            )
        ],
    )


CASES = [
    Case(
        "DP1",
        "Single bored pile capacity by the soil report's unit values",
        "design",
        "Skin friction integrated over the shaft (α in clay without the top 1.5 m, β in sand), "
        "end bearing, allowable compression with the overall and partial factors of safety, "
        "and uplift (BNBC 2020 Part 6 Eqs 6.3.11-6.3.13, Sec 3.10.1.18).",
        "Bored Ø0.5 m × 18 m from 1.5 m; clay cu 50 kPa to 10 m on sand N60 20, water at the "
        "ground; substructure.piles.single_pile.",
        bored_pile_case,
    ),
    Case(
        "DP2",
        "Bored pile capacity by BNBC 2020's SPT relations",
        "design",
        "Skin friction by Eqs 6.3.29 (clay) and 6.3.31 (sand), end bearing by Eq 6.3.33 with "
        "its caps, factor of safety 3.5.",
        "Bored Ø0.6 m × 20 m from 1 m; clay N60 10 to 8 m on sand N60 25; "
        "substructure.piles.single_pile (spt).",
        spt_pile_case,
    ),
    Case(
        "DP3",
        "Four-pile cap: pile loads, flexure and punching",
        "design",
        "Rigid-cap pile reactions under an axial load and biaxial moments, the moment at the "
        "column face and punching at the column with the ACI 13.4.2.5 share of the piles.",
        "Cap 2.5 × 2.5 × 0.9 m, four Ø500 piles at ±0.75 m, column 0.5 m, Pu 2500 kN, Mu 200 "
        "and Mv 300 kN·m; substructure.pilecap.pile_reactions and cap_checks.",
        pile_cap_case,
    ),
    Case(
        "DP5",
        "Driven pile capacity by the static method (α in clay, β and Nq in sand)",
        "design",
        "α of Eq 6.3.16 in clay, β of Eq 6.3.23 and Nq of Eq 6.3.24 / Fig 6.3.2 in sand with "
        "σ'v held at the critical depth (Sec 3.10.1.15).",
        "Driven 0.4 m square × 14 m from 1 m; clay cu 50 kPa to 10 m on sand N60 20, φ' 35°; "
        "substructure.piles.single_pile (static).",
        static_pile_case,
    ),
    Case(
        "DP6",
        "Settlement of a single pile and of a pile group (short term)",
        "design",
        "Eqs 6.3.35a-c and 6.3.36 (Cp of Table 6.3.13) for one pile, Eqs 6.3.37-6.3.38 for "
        "the group (the larger).",
        "The DP5 pile under 300 kN, Ep = 4700 √30; a 2 × 2 m group of 4; "
        "substructure.pile_settlement.",
        settlement_case,
    ),
    Case(
        "DP4",
        "Raft on Winkler springs: uniform and point loads",
        "design",
        "OpenSees plate on springs: settlement q/ks under a uniform load, and the deflection "
        "under a point load against Westergaard's infinite plate.",
        "6 × 4 m raft under 100 kPa; 16 × 16 m plate 0.3 m thick under 1000 kN, ks 20000 "
        "kN/m³; substructure.raft.run_raft.",
        raft_case,
    ),
]

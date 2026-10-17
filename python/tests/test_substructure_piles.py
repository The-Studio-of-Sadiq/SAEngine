"""Part 9 piles and pile caps: single pile capacity, pile groups and cap design, by hand.

Every soil profile here is synthetic; the expected values are worked out in the tests with
plain arithmetic (closed-form integrals where the code integrates in slices).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.library.objects import BarMesh, LinearReinforcement
from saengine.library.soil import SoilReport
from saengine.soil.profile import GAMMA_W, Profile
from saengine.substructure import pilecap, piles
from saengine.substructure.shallow import ColumnBase

#: Two layers, water table at the ground: clay cu = 50 kPa (γ = 18) to 10 m on sand (γ = 19)
#: with N = 20 at ER 60 % (N60 = 20 below 10 m of rod).
CLAY_ON_SAND = {
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


def profile(borehole: dict, **design) -> Profile:
    report = SoilReport.model_validate(
        {"boreholes": [borehole], "design": {"hammerEnergy": 60, **design}}
    )
    return Profile(report, report.boreholes[0])


# ─────────────────────────────── single pile ───────────────────────────────


def test_bored_pile_integrates_the_shaft_by_hand() -> None:
    p = profile(CLAY_ON_SAND)
    assert p.layers[1].n60 == pytest.approx(20.0)
    d, length, head = 0.5, 18.0, 1.5
    r = piles.single_pile(p, "bored", d, length, head)
    perimeter, area = math.pi * d, math.pi * d * d / 4

    # Clay, α = 0.55 (cu/pa < 1.5): no side resistance over the top 1.5 m of the shaft.
    qs_clay = 0.55 * 50 * perimeter * (10.0 - (head + 1.5))
    # Sand, β = 1.5 - 0.245 √z (0.25 ≤ β ≤ 1.2; N60 ≥ 15), σ'v = 10 γ'clay + (z - 10) γ'sand.
    g1, g2 = 18 - GAMMA_W, 19 - GAMMA_W
    a, b = 10 * g1 - 10 * g2, g2  # σ'v = a + b z

    def integral(z: float) -> float:  # ∫ (1.5 - 0.245 √z)(a + b z) dz
        return 1.5 * (a * z + b * z * z / 2) - 0.245 * (a * z**1.5 / 1.5 + b * z**2.5 / 2.5)

    tip = head + length
    beta_tip = 1.5 - 0.245 * math.sqrt(tip)
    assert 0.25 < beta_tip < 1.2  # β stays within its limits over the sand
    qs_sand = perimeter * (integral(tip) - integral(10.0))
    qb = 57.5 * 20 * area  # 57.5 N60 ≤ 2870 kPa
    weight = 24.0 * area * length
    q_ult = qs_clay + qs_sand + qb - weight
    assert r["Qs"] == pytest.approx(qs_clay + qs_sand, rel=1e-3)
    assert r["Qb"] == pytest.approx(qb, abs=0.1)
    assert r["W"] == pytest.approx(weight, abs=0.1)
    assert r["Qult"] == pytest.approx(q_ult, rel=1e-3)
    # No load test at the site: BNBC Sec 3.10.1.18 asks FS ≥ 3.0 (Table 6.3.10a's 2.5 is raised).
    assert r["factors"]["compression"] == 3.0
    assert any("3.10.1.18" in n for n in r["notes"])
    expected = min(q_ult / 3.0, (qs_clay + qs_sand) / 1.5 + qb / 3.0 - weight)
    assert r["Qa"] == pytest.approx(expected, rel=1e-3)
    assert r["Ta"] == pytest.approx((0.7 * (qs_clay + qs_sand) + weight) / 2.5, rel=1e-3)
    clay = r["layers"][0]
    assert clay["excluded"] == 1500 and clay["Qs"] == pytest.approx(qs_clay, abs=0.06)

    # With a load test at the site, Table 6.3.10a's 2.5 (normal control) stands.
    tested = piles.single_pile(
        p, "bored", d, length, head, factors=piles.FactorsOfSafety(load_test=True)
    )
    assert tested["factors"]["compression"] == 2.5
    expected = min(q_ult / 2.5, (qs_clay + qs_sand) / 1.5 + qb / 3.0 - weight)
    assert tested["Qa"] == pytest.approx(expected, rel=1e-3)
    assert not any("3.10.1.18" in n for n in tested["notes"])
    # The 2.0 floor with a load test; a larger factor given is kept.
    assert piles.FactorsOfSafety(1.5, load_test=True).for_method("soilReport").compression == 2.0
    assert piles.FactorsOfSafety(3.2).for_method("soilReport").compression == 3.2


def test_bored_pile_in_clay_leaves_out_the_bottom_diameter() -> None:
    p = profile(CLAY_ON_SAND)
    r = piles.single_pile(p, "bored", 0.6, 7.0, 1.0)  # tip at 8 m, in the clay
    assert r["layers"][0]["excluded"] == pytest.approx(1500 + 600)
    perimeter = math.pi * 0.6
    assert r["Qs"] == pytest.approx(0.55 * 50 * perimeter * (7.0 - 1.5 - 0.6), abs=0.06)
    # Nc* = 9 for cu ≥ 96, 8.0 at 48 and 6.5 at 24 kPa: cu = 50 → 8 + 2/48.
    nc = 8.0 + (9.0 - 8.0) * (50 - 48) / 48
    assert r["qb"] == pytest.approx(nc * 50, abs=0.1)


def test_driven_pile_end_bearing_grows_with_embedment() -> None:
    p = profile(CLAY_ON_SAND)
    short = piles.single_pile(p, "driven", 0.4, 10.0, 1.0)  # 1 m into the sand: 2.5 D
    long = piles.single_pile(p, "driven", 0.4, 14.0, 1.0)  # 5 m: beyond 10 D
    limit = 4 * 101.325 * 20  # Meyerhof: 4 pa N60
    assert long["qb"] == pytest.approx(limit, abs=0.1)
    assert short["qb"] == pytest.approx(limit * 1.0 / (10 * 0.4), abs=0.1)


def test_bnbc_spt_relations_by_hand() -> None:
    borehole = {
        "id": "BH-2",
        "waterTable": 0,
        "depth": 30000,
        "layers": [
            {"top": 0, "bottom": 8000, "soilType": "clay"},
            {"top": 8000, "bottom": 16000, "soilType": "sand"},
            {"top": 16000, "bottom": 30000, "soilType": "silt", "plasticityIndex": 2},
        ],
        "spt": [
            {"depth": 3000, "N": 10},
            {"depth": 6000, "N": 10},
            {"depth": 10500, "N": 80},  # sand: 1.0 N̄60 = 80 is capped at 60 kPa
            {"depth": 13500, "N": 80},
            {"depth": 18000, "N": 30},
            {"depth": 21000, "N": 30},
        ],
    }
    p = profile(borehole, spt={"rodLength": False})
    assert [layer.n60 for layer in p.layers] == pytest.approx([10, 80, 30])
    d, length, head = 0.5, 18.0, 1.0  # tip at 19 m in the silt, 3 m into it
    r = piles.single_pile(p, "bored", d, length, head, "bnbcSpt")
    perimeter, area = math.pi * d, math.pi * d * d / 4
    qs = perimeter * (
        min(1.2 * 10, 70) * (8 - 1)  # Eq 6.3.29 in the clay
        + min(1.0 * 80, 60) * 8  # Eq 6.3.31, capped at 60 kPa
        + min(0.9 * 30, 60) * 3  # Eq 6.3.32, non-plastic silt
    )
    # Eq 6.3.34: 10 N60 L/D ≤ 100 N60 and 4000 kPa; N60 at the tip: the tests within 3 D
    # below it (none, 19 to 20.5 m) → the next one below, 30 at 21 m; L = 3 m in the layer.
    qb = min(10 * 30 * (3.0 / d), 100 * 30, 4000)
    weight = 24 * area * length
    assert r["Qs"] == pytest.approx(qs, abs=0.06)
    assert r["qb"] == pytest.approx(qb, abs=0.1)
    assert r["factors"]["compression"] == 3.5  # BNBC asks for 3.5 with the SPT relations
    q_ult = qs + qb * area - weight
    assert r["Qa"] == pytest.approx(min(q_ult / 3.5, qs / 1.5 + qb * area / 3 - weight), rel=1e-3)

    driven = piles.single_pile(p, "driven", d, length, head, "bnbcSpt")
    qs_driven = perimeter * (
        min(1.8 * 10, 70) * 7  # Eq 6.3.21
        + min(2 * 80, 60) * 8  # Eq 6.3.25
        + min(1.7 * 30, 60) * 3  # Eq 6.3.26
    )
    assert driven["Qs"] == pytest.approx(qs_driven, abs=0.06)
    assert driven["qb"] == pytest.approx(min(30 * 30 * 6, 300 * 30, 11000), abs=0.1)  # 6.3.28


def test_fill_is_ignored_and_reported() -> None:
    borehole = {
        "id": "BH-3",
        "depth": 20000,
        "layers": [
            {"top": 0, "bottom": 3000, "soilType": "fill", "cu": 20},
            {"top": 3000, "bottom": 20000, "soilType": "clay", "cu": 60},
        ],
    }
    r = piles.single_pile(profile(borehole), "driven", 0.4, 12.0, 0.0)
    assert r["layers"][0]["Qs"] == 0 and any("fill" in n for n in r["notes"])


def test_factor_of_safety_table_and_capacity_table() -> None:
    assert piles.table_factor() == 2.5
    assert piles.table_factor("monument", "veryPoor") == 4.0
    assert piles.table_factor("temporary", "good") == 1.4
    p = profile(CLAY_ON_SAND)
    table = piles.capacity_table(p, "bored", [500, 600], [12000, 18000], 1.5)
    assert [(r["D"], r["L"]) for r in table["rows"]] == [
        (500, 12000),
        (500, 18000),
        (600, 12000),
        (600, 18000),
    ]
    one = piles.single_pile(p, "bored", 0.6, 18.0, 1.5)
    assert table["rows"][3]["Qa"] == one["Qa"]
    assert table["rows"][1]["Qa"] > table["rows"][0]["Qa"]
    sizes = piles.table_sizes(500, 18000, 24000)
    assert sizes[0] == [400, 450, 500, 600, 750] and sizes[1][0] == 6000 and 18000 in sizes[1]


def test_structural_checks_of_the_pile_section() -> None:
    bars = LinearReinforcement.model_validate(
        {
            "material": "B420",
            "cover": 75,
            "longitudinal": [{"position": "perimeter", "count": 8, "dia": 16}],
            "transverse": {"type": "tie", "dia": 8, "spacing": 200},
        }
    )
    area, steel = math.pi * 250**2, 8 * math.pi * 8**2
    checks = piles.structural_checks("bored", 500, 25, 420, bars, 1000, 100, 600)
    by_name = {c["name"]: c for c in checks}
    p0 = 0.85 * 25 * (area - steel) + 420 * steel
    assert by_name["Pile axial compression (section)"]["capacity"] == pytest.approx(
        0.80 * 0.65 * p0 / 1e3, abs=0.01
    )
    assert by_name["Pile axial tension (section)"]["capacity"] == pytest.approx(
        0.9 * 420 * steel / 1e3, abs=0.01
    )
    plain = {
        c["name"]: c for c in piles.structural_checks("driven", 400, 30, 420, None, 500, 0, 300)
    }
    assert plain["Pile axial compression (plain section)"]["capacity"] == pytest.approx(
        0.36 * 30 * math.pi * 200**2 / 1e3, abs=0.01
    )
    stress = plain["Pile service stress (driven precast)"]
    assert stress["capacity"] == pytest.approx(0.33 * 30) and stress["demand"] == pytest.approx(
        300e3 / (math.pi * 200**2), abs=0.01
    )


# ─────────────────────────────── pile groups ───────────────────────────────

MESH = BarMesh(dia=20, spacing=150)


def four_pile_cap(**changes) -> pilecap.CapSpec:
    spec = pilecap.CapSpec(
        id="PC1",
        length=2500,
        width=2500,
        thickness=900,
        cover=75,
        fc=28,
        fy=420,
        columns=[ColumnBase("C1", 0, 0, 500, 500)],
        piles=[(-750, -750), (750, -750), (750, 750), (-750, 750)],
        pile_diameter=500,
        bottom_x=MESH,
        bottom_y=MESH,
    )
    for key, value in changes.items():
        setattr(spec, key, value)
    return spec


def test_pile_loads_of_a_rigid_cap_with_moments() -> None:
    spec = four_pile_cap()
    # P = 2000 kN, Cu = 200 kN·m (about u), Cv = 300 kN·m (about v), weight 100 kN.
    loads = [np.array([2000e3, 200e6, 300e6])]
    r, notes = pilecap.pile_reactions(spec, loads, 100e3)
    sum_u2 = 4 * 750**2
    # P/n ± Mv u/Σu² ∓ Mu v/Σv² (a moment vector along +u lifts the +v side).
    expected = [2100e3 / 4 + 300e6 * u / sum_u2 - 200e6 * v / sum_u2 for u, v in spec.piles]
    assert r == pytest.approx(expected)
    assert not notes
    assert r.sum() == pytest.approx(2100e3)

    # An unsymmetric three-pile group: equilibrium of force and moments about any point.
    spec3 = four_pile_cap(piles=[(-900, -600), (900, -600), (0, 900)])
    loads = [np.array([1500e3, -50e6, 120e6])]
    r3, _ = pilecap.pile_reactions(spec3, loads)
    u = np.array([p[0] for p in spec3.piles])
    v = np.array([p[1] for p in spec3.piles])
    assert r3.sum() == pytest.approx(1500e3)
    assert (r3 * u).sum() == pytest.approx(120e6)  # Σ R u = P eu = Cv (column at the centre)
    assert (r3 * v).sum() == pytest.approx(50e6)  # Σ R v = -Cu

    # Two piles in a line take no moment across it.
    spec2 = four_pile_cap(piles=[(-750, 0), (750, 0)])
    r2, notes2 = pilecap.pile_reactions(spec2, [np.array([1000e3, 80e6, 150e6])])
    assert r2 == pytest.approx([500e3 - 100e3, 500e3 + 100e3])
    assert notes2 and "tie beams" in notes2[0]


def test_group_efficiency_block_and_settlement() -> None:
    piles_2x3 = np.array([(u, v) for u in (-1500, 0, 1500) for v in (-750, 750)], dtype=float)
    eg, m, n, s = pilecap.converse_labarre(piles_2x3, 500)
    theta = math.degrees(math.atan(500 / 1500))
    assert (m, n, s) == (2, 3, 1500)
    assert eg == pytest.approx(1 - theta * ((n - 1) * m + (m - 1) * n) / (90 * m * n))

    # Block in clay cu = 50 (to 10 m), tip in sand: base at the pile's qb.
    p = profile(CLAY_ON_SAND)
    block, _ = pilecap.block_capacity(p, 1.5, 18.0, 2.0, 3.5, qb=1150)
    assert block == pytest.approx(2 * (2.0 + 3.5) * 50 * 8.5 + 1150 * 2.0 * 3.5, rel=1e-6)
    clay = {**CLAY_ON_SAND, "layers": [{**CLAY_ON_SAND["layers"][0], "bottom": 30000}]}
    block2, _ = pilecap.block_capacity(profile(clay), 1.0, 12.0, 2.0, 2.0)
    nc = min(9.0, 5 * (1 + 0.2 * 12 / 2) * (1 + 0.2))
    assert block2 == pytest.approx(2 * 4 * 50 * 12 + nc * 50 * 4, rel=1e-6)

    settled = pilecap.group_settlement(p, 1.5, 18.0, 2.0, 2.0, 2000.0)
    assert settled["Df"] == 13500 and settled["q"] == pytest.approx(500.0)
    assert settled["total"] > 0


def test_cap_flexure_shear_and_punching_by_hand() -> None:
    spec = four_pile_cap()
    strength = {"U": [np.array([2500e3, 0.0, 0.0])]}
    checks, detail = pilecap.cap_checks(spec, strength)
    by_name = {c["name"].split(" (")[0]: c for c in checks}
    d_u, d_v = 900 - 75 - 10, 900 - 75 - 20 - 10  # X bars outer, Y bars on them
    assert spec.depths()["u"] == d_u and spec.depths()["v"] == d_v
    # Two piles of 625 kN at 750 - 250 = 500 mm from the face.
    assert by_name["Flexure bottom X at the column face"]["demand"] == pytest.approx(625.0)
    # Beam capacity: As = 5236 mm² over 2.5 m, a = As fy / (0.85 f'c b).
    steel = math.pi * 100 * 1000 / 150 * 2.5
    a = steel * 420 / (0.85 * 28 * 2500)
    assert by_name["Flexure bottom X at the column face"]["capacity"] == pytest.approx(
        0.9 * steel * 420 * (d_u - a / 2) / 1e6, rel=1e-3
    )
    # The shear section d from the face (250 + 815 = 1065 mm) lies 315 mm past the piles'
    # centres (750): more than D/2 = 250, so no pile acts on it.
    assert by_name["One-way shear across X"]["demand"] == 0
    # A shear span of 500 mm < d: a deep cap, flagged.
    assert detail["deep"] == ["u", "v"] and by_name["Flexure bottom X at the column face"]["flag"]
    # ... and the strut-and-tie model checked in its place: the tie T = M / (0.9 d), M of the
    # two piles beyond the column's quarter point (125 mm): 2 × 625 × (750 - 125) kN·mm.
    tie = next(c for c in checks if c["name"].startswith("Tie (bottom X"))
    assert not tie["flag"]
    assert tie["demand"] == pytest.approx(2 * 625 * 625 / (0.9 * d_u), abs=0.01)
    assert tie["capacity"] == pytest.approx(0.75 * steel * 420 / 1e3, abs=0.01)
    # Nodes: under the column (C-C-C, βn 1.0), over a pile (C-C-T, βn 0.8), φ 0.75.
    node = by_name["Node under C1"]
    assert node["demand"] == pytest.approx(2500.0)
    assert node["capacity"] == pytest.approx(0.75 * 0.85 * 28 * 500 * 500 / 1e3)
    node_pile = by_name["Node over a pile"]
    assert node_pile["demand"] == pytest.approx(625.0)
    assert node_pile["capacity"] == pytest.approx(0.75 * 0.85 * 0.8 * 28 * math.pi * 250**2 / 1e3)

    # Punching at the column: section at d/2 = 402.5 mm, a pile centre 97.5 mm outside it:
    # (97.5 + 250) / 500 = 69.5 % of its reaction acts outside, 30.5 % inside.
    d = (d_u + d_v) / 2
    half = 250 + d / 2
    outside = (750 - half + 250) / 500
    vu = 2500 - 4 * 625 * (1 - outside)
    punch = by_name["Punching at C1"]
    b0 = 4 * 2 * half
    lam = math.sqrt(2 / (1 + 0.004 * d))
    vc = min(0.33, 0.17 * 3, 0.083 * (2 + 40 * d / b0)) * lam * math.sqrt(28)
    assert punch["demand"] == pytest.approx(vu, abs=0.1)
    assert punch["capacity"] == pytest.approx(0.75 * vc * b0 * d / 1e3, rel=1e-3)

    # A corner pile: a 443 mm square of the same area, its section cut by both edges 500 mm
    # from its centre: two sides of 624 + 500 mm; αs = 20.
    side = math.sqrt(math.pi) / 2 * 500
    reach = side / 2 + d / 2
    b0_pile = 2 * (reach + 500)
    vc_pile = min(0.33, 0.51, 0.083 * (2 + 20 * d / b0_pile)) * lam * math.sqrt(28)
    pile = by_name["Punching round a pile"]
    assert pile["demand"] == pytest.approx(625.0)
    assert pile["capacity"] == pytest.approx(0.75 * vc_pile * b0_pile * d / 1e3, rel=1e-3)


def test_a_deep_cap_with_too_little_tie_steel_fails() -> None:
    # Cap 2.6 × 2.6 × 1.0 m, Ø20 @ 150 both ways, column 0.4 m, four Ø500 piles at ±0.75 m,
    # Pu = 5750 kN: a/d = 550/915 < 1, deep; the sectional checks are only for reference, so
    # the tie must catch the short bottom steel: T = 2 × 1437.5 × (750 - 100) / (0.9 × 915).
    spec = four_pile_cap(
        length=2600, width=2600, thickness=1000, columns=[ColumnBase("C1", 0, 0, 400, 400)]
    )
    checks, detail = pilecap.cap_checks(spec, {"U": [np.array([5750e3, 0.0, 0.0])]})
    assert detail["deep"] == ["u", "v"]
    counted = [c for c in checks if not c["flag"]]
    tie = next(c for c in counted if c["name"].startswith("Tie (bottom X"))
    steel = math.pi * 100 * 1000 / 150 * 2.6
    assert tie["demand"] == pytest.approx(2 * 1437.5 * 650 / (0.9 * 915), abs=0.01)
    assert tie["capacity"] == pytest.approx(0.75 * steel * 420 / 1e3, abs=0.01)
    assert not tie["ok"]
    assert not all(c["ok"] for c in counted)


def test_cap_cover_must_clear_the_pile_heads() -> None:
    p = profile(CLAY_ON_SAND)
    pile = piles.single_pile(p, "bored", 0.5, 18.0, 1.5)
    strength = {"U": [np.array([2500e3, 0, 0])]}
    for cover, ok in ((60, False), (75, True)):
        out = pilecap.pile_cap_design(four_pile_cap(cover=cover), {}, strength, pile)
        check = next(c for c in out["checks"] if c["name"] == "Cover of the cap's main bars")
        assert check["demand"] == 75 and check["ok"] is ok


def test_one_way_shear_takes_a_share_of_a_pile_across_the_section() -> None:
    # Cap 3.6 x 1.5 m, two piles at u = ±1200 (D 500), column 400; d = 1000 - 75 - 10 = 915:
    # the section at 200 + 915 = 1115 mm cuts the pile 85 mm before its centre: ACI 13.4.2.5
    # takes (85 + 250) / 500 = 67 % of its reaction.
    spec = pilecap.CapSpec(
        "PC2", 3600, 1500, 1000, 75, 28, 420, [ColumnBase("C1", 0, 0, 400, 400)],
        [(-1200, 0), (1200, 0)], 500, MESH, MESH,
    )  # fmt: skip
    checks, _ = pilecap.cap_checks(spec, {"U": [np.array([1600e3, 0.0, 0.0])]})
    shear = next(c for c in checks if c["name"].startswith("One-way shear across X"))
    assert shear["demand"] == pytest.approx(800 * (85 + 250) / 500, abs=0.1)
    rho = math.pi * 100 * 1000 / 150 / (1000 * 915)
    lam = math.sqrt(2 / (1 + 0.004 * 915))
    phi_vc = 0.75 * min(0.66 * lam * rho ** (1 / 3), 0.42) * math.sqrt(28) * 1500 * 915
    assert shear["capacity"] == pytest.approx(phi_vc / 1e3, rel=1e-3)


def test_pile_cap_design_puts_it_together() -> None:
    p = profile(CLAY_ON_SAND)
    pile = piles.single_pile(p, "bored", 0.5, 18.0, 1.5)
    spec = four_pile_cap(soil_above=18e-6 * 600)
    service = {"D + L": [np.array([1800e3, 0, 0])], "0.6D + WX": [np.array([600e3, 0, 600e6])]}
    strength = {"1.2D + 1.6L": [np.array([2500e3, 0, 0])]}
    out = pilecap.pile_cap_design(spec, service, strength, pile, p, None, {"0.6D + WX": 0.6})
    by_name = {c["name"]: c for c in out["checks"]}
    weight = (2400 * 9.80665e-9 * 900 + 18e-6 * 600) * 2500**2
    assert by_name["Pile load, compression"]["demand"] == pytest.approx(
        (1800e3 + weight) / 4 / 1e3, abs=0.05
    )
    # 0.6D + WX: (600 + 0.6 W)/4 - 600e6 · 750 / (4 · 750²) = 150 + 0.15 W - 200 kN: uplift.
    least = (600e3 + 0.6 * weight) / 4 - 600e6 / 3000
    assert by_name["Pile load, uplift"]["demand"] == pytest.approx(-least / 1e3, abs=0.05)
    assert by_name["Pile load, uplift"]["capacity"] == pile["Ta"]
    assert by_name["Pile spacing"]["capacity"] == 1500
    assert by_name["Cap edge beyond the piles"]["capacity"] == 250
    assert out["group"]["efficiency"] == 1.0  # skin friction mostly in the sand
    assert "Group settlement" in by_name and "Block failure (clay)" in by_name
    assert [row["index"] for row in out["piles"]] == [1, 2, 3, 4]


def test_a_cap_without_top_bars_hogs_against_plain_concrete() -> None:
    """Uplift pulls two piles up and the cap hogs: without top bars the top face is plain
    concrete (ACI 318-19 14.5.2.1), not a zero capacity; under an earthquake combination the note
    adds BNBC 2020 Part 6 Sec 8.3.11.2 (top reinforcement in pile caps)."""
    spec = four_pile_cap()
    # A small axial load and a large moment: the -u piles are in tension.
    checks, _ = pilecap.cap_checks(spec, {"1.2D + 1.0EX": [np.array([200e3, 0.0, 900e6])]})
    (hog,) = [c for c in checks if c["name"].startswith("Flexure top")]
    width = 2500
    plain = 0.60 * 0.42 * math.sqrt(28) * 1000 * (900 - 50) ** 2 / 6 * width / 1000
    assert hog["capacity"] == pytest.approx(plain / 1e6, rel=1e-3)
    assert hog["utilisation"] < 99
    assert "plain concrete" in hog["note"] and "8.3.11.2" in hog["note"]

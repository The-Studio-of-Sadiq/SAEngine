"""Pile capacity methods and pile settlement, pinned through the default code pack (bnbc2020).

Each value is the code pack's, with its clause (BNBC 2020 Part 6); the engine reads them from
``foundations.piles`` and must reproduce them.
"""

from __future__ import annotations

import math

import pytest

from saengine.codes.tables import builtin_table
from saengine.library.soil import SoilReport
from saengine.library.substructure import Design
from saengine.soil import piles as soil_piles
from saengine.soil.profile import GAMMA_W, Profile
from saengine.substructure import pile_settlement, pile_static, piles


def _profile(borehole: dict, **design) -> Profile:
    report = SoilReport.model_validate(
        {"boreholes": [borehole], "design": {"hammerEnergy": 60, **design}}
    )
    return Profile(report, report.boreholes[0])


CLAY_ON_SAND = {
    "id": "BH-1",
    "waterTable": 0,
    "depth": 30000,
    "layers": [
        {"top": 0, "bottom": 10000, "soilType": "clay", "unitWeight": 18,
         "saturatedUnitWeight": 18, "cu": 50},
        {"top": 10000, "bottom": 30000, "soilType": "sand", "unitWeight": 19,
         "saturatedUnitWeight": 19, "phi": 35},
    ],
    "spt": [{"depth": d * 1000, "N": 20} for d in (12, 15, 18, 21, 24, 27)],
}  # fmt: skip


def rules():
    return builtin_table("foundations").piles


# ─────────────────────────────── pack values ───────────────────────────────


def test_pack_values_of_the_static_method() -> None:
    r = rules()
    assert r.staticMethod == "alphaBeta"
    s = r.static
    # Sec 3.10.1.12 Eq 6.3.16: α 1.0 at cu <= 25, 0.5 at cu >= 70, 1 - (cu - 25)/70 between.
    assert s.alphaFull == (25, 1.0) and s.alphaLow == (70, 0.5) and s.alphaDivisor == 70
    # Eq 6.3.18: Nc = 6 (1 + 0.2 L/Db) <= 9; fb <= 4.0 MPa.
    assert (s.ncBase, s.ncSlope, s.ncMax, s.clayBaseMax) == (6, 0.2, 9, 4000)
    # Eq 6.3.23: β 0.10 / 0.20 / 0.35 at φ 33 / 35 / 37.
    assert s.sandBeta == [(33, 0.10), (35, 0.20), (37, 0.35)]
    # Eq 6.3.24: Nq 8-12 loose, 12-40 medium, 40 dense; σ'v <= 240 kPa.
    assert s.nqDensity == {"loose": (8, 12), "medium": (12, 40), "dense": (40, 40)}
    assert s.baseStressMax == 240
    # Sec 3.10.1.15: Dc 10 / 15 / 20 D.
    assert s.criticalDepth == {"loose": 10, "medium": 15, "dense": 20}
    # Secs 3.10.4.4, 3.10.4.6: bored 2/3 fs and 1/3 fb.
    assert s.boredSkin == pytest.approx(2 / 3, abs=1e-4)
    assert s.boredBase == pytest.approx(1 / 3, abs=1e-4)
    # Table 6.3.9a: sand loose < 10, dense >= 30; Table 6.3.9b: stiff clay from qu 100.
    assert (r.soilClasses.mediumN, r.soilClasses.denseN, r.soilClasses.stiffCu) == (10, 30, 50)


def test_fig_6_3_2_nq_digitised() -> None:
    nq = dict(rules().static.nq)
    # Fig 6.3.2 (Berezantzev): about 17 at 25°, 33 at 30°, 74 at 35°, 195 at 40°, 600 at 45°.
    assert nq[25] == pytest.approx(16.7, rel=0.05)
    assert nq[30] == pytest.approx(32.6, rel=0.05)
    assert nq[35] == pytest.approx(73.8, rel=0.05)
    assert nq[40] == pytest.approx(195, rel=0.05)
    assert nq[45] == pytest.approx(600, rel=0.05)


def test_pack_values_of_drilled_shafts() -> None:
    shaft = rules().drilledShaft
    assert shaft.minDiameter == 600  # Sec 3.10.6
    assert (shaft.alpha, shaft.alphaLimit) == (0.55, 190)  # Eq 6.3.42
    assert (shaft.sideTop, shaft.sideBottom) == (1500, 1.0)  # Sec 3.10.6.7
    assert (shaft.baseMax, shaft.clayReduceAbove) == (4000, 1900)  # Eqs 6.3.43-6.3.44
    assert shaft.omega1 == (0.0071, 0.0021, 0.0015) and shaft.omega2 == (1.59, 0.5, 1.5)
    assert (shaft.betaIntercept, shaft.betaSlope, shaft.referenceWidth) == (1.5, 0.135, 300)
    assert (shaft.sandBase, shaft.sandBaseMax, shaft.sandBaseDepth) == (0.60, 4500, 2.0)
    assert (shaft.sandReduceAbove, shaft.sandFr) == (1200, 4.17)  # Eq 6.3.49
    # Table 6.3.15.
    assert {r.id: r.value for r in shaft.lateralRatio} == {
        "openHole": 1.0, "slurryLight": 1.0, "slurryHeavy": 0.8, "permanentCasing": 0.7
    }  # fmt: skip
    assert {r.id: r.value for r in shaft.frictionRatio}["slurryPoor"] == pytest.approx(2 / 3, 1e-3)
    # Sec 3.10.6.13: ζ 0.67 at 3B, 1.0 at 6B (clay) and 8B (sand).
    assert (shaft.zetaLow, shaft.spacingLow, shaft.clayFullSpacing, shaft.sandFullSpacing) == (
        0.67, 3, 6, 8
    )  # fmt: skip


def test_pack_values_of_settlement() -> None:
    st = rules().settlement
    assert st.axialShare == {"cohesive": 0.5, "granular": 0.67}  # Eq 6.3.35b
    # Table 6.3.13.
    assert st.cp["driven"] == {
        "denseSand": 0.02, "looseSand": 0.04, "stiffClay": 0.02, "softClay": 0.03,
        "denseSilt": 0.03, "looseSilt": 0.05,
    }  # fmt: skip
    assert st.cp["bored"] == {
        "denseSand": 0.09, "looseSand": 0.18, "stiffClay": 0.03, "softClay": 0.06,
        "denseSilt": 0.09, "looseSilt": 0.12,
    }  # fmt: skip
    assert (st.csIntercept, st.csSlope) == (0.93, 0.16)  # Eq 6.3.36
    assert (st.groupWidthExponent, st.groupCountExponent) == (0.5, 0.5)  # Eqs 6.3.37-38
    # Table 6.3.14 (lower M of each range used).
    rows = {r.id: (r.M, r.j) for r in st.modulus}
    assert rows["sandDense"] == ((400, 250), 0.5)
    assert rows["siltyClaySoft"] == ((10, 5), 0.5)
    assert rows["organicClay"] == ((20, 5), 0.0)
    assert rows["till"] == ((1000, 300), 1.0)


def test_spt_relations_from_the_pack() -> None:
    spt = rules().spt
    # Eqs 6.3.21-22, 6.3.25-28 (driven), 6.3.29-34 (bored).
    assert (spt["driven"]["clay"].skin, spt["driven"]["clay"].base) == (1.8, 45)
    assert (spt["driven"]["sand"].baseCapN, spt["driven"]["sand"].baseMax) == (400, 11000)
    assert (spt["bored"]["silt"].skin, spt["bored"]["silt"].base) == (0.9, 10)
    assert spt["bored"]["clay"].baseCapN is None


# ─────────────────────────────── the static method ───────────────────────────────


def test_alpha_and_nc_of_the_static_method() -> None:
    m = pile_static.method()
    assert isinstance(m, pile_static.AlphaBeta)
    assert m.alpha(20) == 1.0
    assert m.alpha(47.5) == pytest.approx(1 - 22.5 / 70)
    assert m.alpha(70) == 0.5 and m.alpha(200) == 0.5
    assert m.nc(2.0, 1.0) == pytest.approx(8.4) and m.nc(20.0, 0.5) == 9.0


def test_driven_pile_static_by_hand() -> None:
    p = _profile(CLAY_ON_SAND)
    r = piles.single_pile(p, "driven", 0.4, 14.0, 1.0, "static")
    b = 0.4
    alpha = 1 - 25 / 70
    sigma_c = 15 * b * (18 - GAMMA_W)  # medium sand: Dc 15 D = 6 m, in the clay
    qs = 4 * b * (alpha * 50 * 9 + 0.20 * sigma_c * 5)
    nq = min(12 + 28 * 10 / 20, 73.8)  # Eq 6.3.24 range vs Fig 6.3.2
    assert r["Qs"] == pytest.approx(qs, abs=0.06)
    assert r["qb"] == pytest.approx(sigma_c * nq, abs=0.1)


def test_bored_pile_static_takes_shares_of_the_driven_values() -> None:
    p = _profile(CLAY_ON_SAND)
    driven = piles.single_pile(p, "driven", 0.5, 14.0, 1.0, "static")
    bored = piles.single_pile(p, "bored", 0.5, 14.0, 1.0, "static")
    # Same unit values times 2/3 and 1/3 (Secs 3.10.4.4, 3.10.4.6); circle against square.
    ratio_perimeter = math.pi / 4
    assert bored["Qs"] == pytest.approx(driven["Qs"] * ratio_perimeter * 0.6667, rel=1e-3)
    assert bored["qb"] == pytest.approx(driven["qb"] * 0.3333, rel=1e-3)
    # No zones excluded for small bored piles by the static method.
    assert all(row["excluded"] == 0 for row in bored["layers"])


def test_large_bored_pile_static_is_a_drilled_shaft() -> None:
    p = _profile(CLAY_ON_SAND)
    shaft = piles.single_pile(p, "bored", 1.0, 14.0, 1.0, "static")
    report = piles.single_pile(p, "bored", 1.0, 14.0, 1.0, "soilReport")
    assert shaft["Qs"] == pytest.approx(report["Qs"], abs=0.1)
    assert shaft["layers"][0]["excluded"] == 1500


def test_drilled_shaft_unit_values() -> None:
    shaft = rules().drilledShaft
    assert soil_piles.shaft_alpha(190, shaft) == 0.55
    assert soil_piles.shaft_alpha(250, shaft) == pytest.approx(0.335)  # Fig 6.3.3
    # Eq 6.3.49: Fr = 4.17 × 300 / 1500 for a 1.5 m base; 0.60 × 100 × 30 = 1800.
    qb, _ = soil_piles.shaft_sand_base(30, 1.5, shaft)
    assert qb == pytest.approx(1800 * 4.17 * 300 / 1500)
    qb, _ = soil_piles.shaft_sand_base(100, 1.0, shaft)
    assert qb == 4500  # capped
    # Eq 6.3.47 β at z = 2.7 m: 1.5 - 0.135 × 3 = 1.095.
    layer = _profile(CLAY_ON_SAND).layers[1]
    beta, _ = soil_piles.shaft_beta(layer, 2.7, shaft)
    assert beta == pytest.approx(1.095)
    # Table 6.3.15 with Eq 6.3.46: β = (K/K0) (1 - sin φ') tan((δ/φ) φ').
    beta, _ = soil_piles.shaft_beta(layer, 2.7, shaft, ("permanentCasing", "slurryPoor"))
    phi = math.radians(35)
    assert beta == pytest.approx(0.7 * (1 - math.sin(phi)) * math.tan(0.6667 * phi), rel=1e-6)


def test_zeta_and_punching() -> None:
    assert pile_static.zeta(3000, 1000, True) == 0.67
    assert pile_static.zeta(4500, 1000, True) == pytest.approx(0.67 + 0.33 * 1.5 / 3)
    assert pile_static.zeta(6000, 1000, True) == 1.0
    assert pile_static.zeta(6000, 1000, False) == pytest.approx(0.67 + 0.33 * 3 / 5)
    assert pile_static.zeta(2000, 1000, False) == 0.67
    # Eq 6.3.50 (read as qLo + H/(10 B)(qUP - qLo) <= qUP).
    assert pile_static.punching_base(3000, 1000, 2.0, 2.0) == pytest.approx(1000 + 0.1 * 2000)
    assert pile_static.punching_base(3000, 1000, 30.0, 2.0) == 3000


# ─────────────────────────────── settlement ───────────────────────────────


def test_janbu_forms() -> None:
    found = rules().settlement
    p = _profile(CLAY_ON_SAND)
    sand = p.layers[1]  # N60 20: medium, M 150, j 0.5
    strain, row = pile_settlement.janbu_strain(sand, 100, 150, found)
    assert row.id == "sandMedium"
    assert strain == pytest.approx(2 / 150 * (math.sqrt(1.5) - 1))  # Eq 6.3.41
    clay = p.layers[0]  # cu 50: stiff (Table 6.3.9b), silty clay stiff M 40, j 0.5
    strain, row = pile_settlement.janbu_strain(clay, 100, 150, found)
    assert row.id == "siltyClayStiff"
    power = 2 / 40 * (math.sqrt(1.5) - 1)
    assert strain == pytest.approx(max(power, math.log(1.5) / 40))  # the larger, Eq 6.3.40


def test_single_and_group_settlement() -> None:
    p = _profile(CLAY_ON_SAND)
    pile = piles.single_pile(p, "bored", 0.5, 18.0, 1.5)
    ep = 25000.0
    one = pile_settlement.single_settlement(pile, 400.0, p, ep)
    d, length, area = 0.5, 18.0, math.pi * 0.25 / 4
    qp = 400 * pile["Qb"] / (pile["Qs"] + pile["Qb"])
    qs = 400 - qp
    clay = pile["layers"][0]["Qs"]
    a = clay / pile["Qs"] * 0.5 + (1 - clay / pile["Qs"]) * 0.67
    cp = 0.18  # bored, sand N60 20 (not dense): loose sand
    s = (qp + a * qs) * length / (area * ep * 1e3)
    s += cp * qp / (d * pile["qb"])
    s += (0.93 + 0.16 * length / d) * cp * qs / (length * pile["qb"])
    assert one["total"] == pytest.approx(s * 1e3, abs=0.01)
    group = pile_settlement.group_settlement(p, pile, 6, 2.0, 3.5, 2400.0, ep)
    single = group["single"]["total"]
    assert group["shortTerm"] == pytest.approx(
        max(single * (2.0 / 0.5) ** 0.5, single * 6**0.5), abs=0.02
    )
    assert group["total"] >= group["shortTerm"]
    assert group["Df"] == round((1.5 + 0.6667 * 18) * 1e3)


def test_former_spt_method_name_is_read() -> None:
    assert Design.model_validate({"pileCapacity": "bnbcSpt"}).pileCapacity == "spt"
    assert Design.model_validate({"pileCapacity": "static"}).pileCapacity == "static"
    assert piles.method_id("bnbcSpt") == "spt"
    assert "static method" in piles.method_text("static")

"""The soil report's design options and BNBC 2020 checks: the Bangladesh consultant practice of
the SPT corrections and of the Meyerhof-Bowles bearing pressure, the BNBC 2020 Sec 3.9.5
liquefaction method and screening, the S1 / S2 / SE site class flags and the permissible
settlements of Table 6.3.8. Synthetic boreholes, worked by hand."""

from __future__ import annotations

import json
import math

import pytest

from saengine.library import code_data
from saengine.library.export import json_schema
from saengine.library.settings import default_project_settings
from saengine.library.soil import SoilReport
from saengine.soil import bearing, liquefaction, site_class, soil_report
from saengine.soil.profile import GAMMA_W, PA, Profile, dilatancy, peck_cn, rod_factor
from saengine.soil.report import classify, footing_settlement
from saengine.soil.settlement import permissible, settlement


def profile(borehole: dict, **design: object) -> Profile:
    r = SoilReport.model_validate({"boreholes": [borehole], "design": design})
    return Profile(r, r.boreholes[0])


def text(*boreholes: dict, **design: object) -> str:
    return json.dumps(
        {"schema": "saengine.soilReport/1", "boreholes": list(boreholes), "design": design}
    )


# ─────────────────────────────── design options ───────────────────────────────


def test_design_options_default_and_schema() -> None:
    r = SoilReport()
    assert r.design.practice == "textbook"
    assert r.design.liquefactionMethod == "idrissBoulanger2014"
    schema = json_schema(SoilReport, "SAEngine soil report")["$defs"]["Design"]["properties"]
    assert schema["practice"]["enum"] == ["textbook", "bdConsultant"]
    assert (
        schema["liquefactionMethod"]["enumDescriptions"][1] == "The code pack's procedure"
    )  # D1: no code name
    with pytest.raises(ValueError):
        SoilReport.model_validate({"design": {"practice": "other"}})


# ─────────────────────────────── consultant practice: SPT ───────────────────────────────

#: Sand to 6 m (γ 18, γsat 20) on clay (γ 17, γsat 18); water table at 1 m; ER 50 %.
CONSULTANT_HOLE = {
    "id": "BH-1",
    "waterTable": 1000,
    "layers": [
        {"top": 0, "bottom": 6000, "soilType": "sand", "unitWeight": 18, "saturatedUnitWeight": 20},
        {
            "top": 6000,
            "bottom": 12000,
            "soilType": "clay",
            "unitWeight": 17,
            "saturatedUnitWeight": 18,
        },
    ],
    "spt": [{"depth": 1500, "N": 6}, {"depth": 4500, "N": 20}, {"depth": 7500, "N": 8}],
}


def test_skempton_rod_factors_of_the_consultant_practice() -> None:
    depths = (1.5, 3.0, 3.5, 3.99, 4.0, 4.5, 5.99, 6.0, 9.0, 9.99, 10.0, 10.5)
    assert [rod_factor(d, "bdConsultant") for d in depths] == [
        0.75, 0.75, 0.75, 0.75, 0.85, 0.85, 0.85, 0.95, 0.95, 0.95, 1.0, 1.0
    ]  # fmt: skip
    # The textbook practice keeps Youd et al. 2001's 0.80 for 3-4 m.
    assert rod_factor(3.5) == 0.80


def test_consultant_spt_chain_by_hand() -> None:
    # CB = 1.05 is ignored: the consultant practice takes CB = CS = 1.
    p = profile(
        CONSULTANT_HOLE, practice="bdConsultant", hammerEnergy=50, spt={"boreholeFactor": 1.05}
    )
    first, second, third = p.spt
    # Row 1, 0-1.5 m, sand: mid-depth 0.75 m above the water table, σ' = 18 × 0.75.
    s1 = 18 * 0.75
    cn1 = 0.77 * math.log10(2000 / s1)
    n60_1 = 6 * 0.50 * 0.75 / 0.6
    assert first.sigma_cn == pytest.approx(s1)
    assert first.cn == pytest.approx(cn1)
    assert first.n60 == pytest.approx(n60_1) and first.cr == 0.75
    assert first.n160 == pytest.approx(cn1 * n60_1)
    assert first.n_prime == pytest.approx(cn1 * n60_1)  # below 15: no dilatancy correction
    # Row 2, 1.5-4.5 m, sand: mid-depth 3 m, 1 m above and 2 m below the water table.
    s2 = 18 * 1 + (20 - GAMMA_W) * 2
    cn2 = 0.77 * math.log10(2000 / s2)
    n60_2 = 20 * 0.50 * 0.85 / 0.6
    n160_2 = cn2 * n60_2
    assert second.sigma_cn == pytest.approx(s2) and second.cr == 0.85
    assert second.n160 == pytest.approx(n160_2) and n160_2 > 15
    assert second.n_prime == pytest.approx(15 + (n160_2 - 15) / 2)
    # Row 3, 4.5-7.5 m, clay: mid-depth 6 m with the clay's own weight (not cumulative).
    s3 = 17 * 1 + (18 - GAMMA_W) * 5
    cn3 = 0.77 * math.log10(2000 / s3)
    n60_3 = 8 * 0.50 * 0.95 / 0.6
    assert third.sigma_cn == pytest.approx(s3)
    assert third.n160 == pytest.approx(cn3 * n60_3)
    assert third.to_json()["rowTop"] == 4500 and third.to_json()["Nprime"] == round(cn3 * n60_3, 1)
    # The profile's own stresses stay cumulative.
    assert third.sigma_v_eff == pytest.approx(18 + 20 * 5 + 18 * 1.5 - GAMMA_W * 6.5)
    assert "Peck, Hanson & Thornburn" in p.spt_method


def test_textbook_practice_is_unchanged() -> None:
    p = profile(CONSULTANT_HOLE, hammerEnergy=50)
    second = p.spt[1]
    assert second.n_prime is None and second.cr == 0.85
    assert second.cn == pytest.approx(min(1.7, math.sqrt(PA / second.sigma_v_eff)))
    assert second.sigma_cn == second.sigma_v_eff


def test_dilatancy_and_peck_cn() -> None:
    assert dilatancy(15.0) == 15.0 and dilatancy(9.0) == 9.0
    assert dilatancy(31.0) == pytest.approx(23.0)
    assert peck_cn(2000.0) == pytest.approx(0.0)
    assert peck_cn(5.0) == pytest.approx(0.77 * math.log10(400)) and peck_cn(5.0) > 1.7  # no cap
    assert peck_cn(100.0) == pytest.approx(0.77 * math.log10(20))
    # Above the water table there is no dilatancy correction.
    dry = profile({**CONSULTANT_HOLE, "waterTable": None}, practice="bdConsultant")
    assert dry.spt[1].n_prime == pytest.approx(dry.spt[1].n160) and dry.spt[1].n160 > 15


# ─────────────────────────────── consultant practice: bearing ───────────────────────────────


def test_bowles_si_form_by_hand() -> None:
    assert bearing.meyerhof_bowles_si(10, 1.0, 1.0, 25) == pytest.approx(10 / 0.05 * 1.33)
    assert bearing.meyerhof_bowles_si(10, 1.2, 0.3, 25) == pytest.approx(
        10 / 0.05 * (1 + 0.33 * 0.25)
    )
    kd = 1 + 0.33 * 1.5 / 3
    assert bearing.meyerhof_bowles_si(10, 3.0, 1.5, 25) == pytest.approx(
        10 / 0.08 * (3.3 / 3) ** 2 * kd
    )
    assert bearing.meyerhof_bowles_si(10, 3.0, 1.5, 40) == pytest.approx(
        10 / 0.08 * (3.3 / 3) ** 2 * kd * 40 / 25
    )


def _zone_profile() -> Profile:
    hole = {
        "id": "BH",
        "layers": [{"top": 0, "bottom": 15000, "soilType": "sand"}],
        "spt": [{"depth": d, "N": 10} for d in (1500, 3000, 4500, 6000, 7500)],
    }
    p = profile(hole, practice="bdConsultant")
    # N' of the rows set by hand: 3.4 → 3, 2.6 → 3, 5.5 → 6 (half up), 7.49 → 7, 9.0 → 9.
    for test, n in zip(p.spt, (3.4, 2.6, 5.5, 7.49, 9.0), strict=True):
        test.n_prime = n
    return p


def test_zone_average_of_n_prime_by_hand() -> None:
    p = _zone_profile()
    # B = 2 m, Df = 1.5 m: zone 0.5-5.5 m, samples at 1.0, 1.5 | 2.0, 2.5, 3.0 | 3.5, 4.0, 4.5 |
    # 5.0, 5.5 (each in the row from the test above, exclusive, to its own test, inclusive).
    zone = bearing.zone_n_prime(p, 2.0, 1.5)
    assert zone is not None
    assert (zone["top"], zone["bottom"], zone["count"]) == (0.5, 5.5, 10)
    assert zone["N"] == pytest.approx((3 * 2 + 3 * 3 + 6 * 3 + 7 * 2) / 10)
    # B = 1 m: zone 1.0-3.5 m, samples 1.5 | 2.0, 2.5, 3.0 | 3.5.
    assert bearing.zone_n_prime(p, 1.0, 1.5)["N"] == pytest.approx((3 + 3 * 3 + 6) / 5)
    # B = 3 m, Df = 4.5 m: zone 3.0-10.5 m; below the last test (7.5 m) the last row's N'.
    deep = bearing.zone_n_prime(p, 3.0, 4.5)
    assert deep["count"] == 15
    assert deep["N"] == pytest.approx((6 * 3 + 7 * 3 + 9 * 3 + 9 * 6) / 15)
    # The textbook practice has no N'.
    assert (
        bearing.zone_n_prime(profile({"id": "BH", "spt": [{"depth": 1500, "N": 9}]}), 1, 1) is None
    )


def test_consultant_bearing_uses_the_zone_average() -> None:
    hole = {
        "id": "BH",
        "waterTable": 0,
        "layers": [{"top": 0, "bottom": 20000, "soilType": "sand", "phi": 32}],
        "spt": [{"depth": d, "N": 12} for d in range(1500, 15001, 1500)],
    }
    p = profile(hole, practice="bdConsultant")
    r = bearing.allowable(p, 2.0, 2.0, 1.5)
    zone = bearing.zone_n_prime(p, 2.0, 1.5)
    hand = bearing.meyerhof_bowles_si(zone["N"], 2.0, 1.5, 25)
    assert r["meyerhofBowles"]["qa"] == pytest.approx(hand, abs=0.05)
    assert r["qa_settlement"] == pytest.approx(hand, abs=0.05)
    assert r["settlement"].startswith("Meyerhof-Bowles (consultant practice), N' = ")
    textbook = bearing.allowable(profile(hole), 2.0, 2.0, 1.5)
    assert textbook["meyerhofBowles"] is None and "N60" in textbook["settlement"]
    method = bearing.method_text(p.design)
    assert "Bangladesh consultant practice" in method and "criterion of qa: 25 mm" in method
    assert "Table 6.3.8" in method


# ─────────────────────────────── settlement: Table 6.3.8 ───────────────────────────────


def test_permissible_settlements_of_table_6_3_8() -> None:
    assert permissible("isolated", "sand")["value"] == 50
    assert permissible("isolated", "sand")["framedBuilding"] == 60
    assert permissible("isolated", "plasticClay")["value"] == 75
    assert permissible("raft", "sand")["value"] == 75
    assert permissible("raft", "plasticClay")["framedBuilding"] == 125
    sand = profile(
        {"id": "BH", "layers": [{"top": 0, "bottom": 20000, "soilType": "sand", "E": 30}]}
    )
    r = settlement(sand, 2.0, 2.0, 1.0, 100.0)
    assert r["permissible"]["value"] == 50 and r["allowable"] == 25
    clay = profile(
        {
            "id": "BH",
            "layers": [
                {"top": 0, "bottom": 3000, "soilType": "sand", "E": 30},
                {"top": 3000, "bottom": 20000, "soilType": "clay", "cu": 60, "E": 30},
            ],
        }
    )
    r = settlement(clay, 2.0, 2.0, 1.0, 100.0, foundation="raft")
    assert r["permissible"]["soil"] == "plasticClay" and r["permissible"]["value"] == 100
    assert "raft foundation on plastic clay" in r["permissible"]["source"]
    # A hard clay (cu ≥ 200 kPa) is in the sand column.
    hard = profile(
        {
            "id": "BH",
            "layers": [{"top": 0, "bottom": 20000, "soilType": "clay", "cu": 250, "E": 60}],
        }
    )
    assert settlement(hard, 2.0, 2.0, 1.0, 100.0)["permissible"]["soil"] == "sand"
    soil = text({"id": "BH", "layers": [{"top": 0, "bottom": 20000, "soilType": "sand", "E": 30}]})
    assert (
        footing_settlement(soil, "BH", 2000, 2000, 1000, 100, "raft")["permissible"]["value"] == 75
    )
    assert "problems" in footing_settlement(soil, "BH", 2000, 2000, 1000, 100, "pile")


# ─────────────────────────────── liquefaction: BNBC 2020 ───────────────────────────────


def test_youd_pieces() -> None:
    assert liquefaction.rd_linear(10.0, 0.015) == pytest.approx(0.85)
    assert liquefaction.youd_fines(5) == (0.0, 1.0)
    assert liquefaction.youd_fines(35) == (5.0, 1.2)
    a, b = liquefaction.youd_fines(15)
    assert a == pytest.approx(math.exp(1.76 - 190 / 225)) and b == pytest.approx(
        0.99 + 15**1.5 / 1e3
    )
    n = 20.0
    assert liquefaction.crr_youd(n) == pytest.approx(
        1 / (34 - n) + n / 135 + 50 / (10 * n + 45) ** 2 - 1 / 200
    )
    assert liquefaction.crr_youd(30.0) is None
    assert liquefaction.msf_idriss(7.5) == pytest.approx(10**2.24 / 7.5**2.56)
    assert liquefaction.k_sigma_youd(50.0) == 1.0
    assert liquefaction.k_sigma_youd(200.0) == pytest.approx((200 / PA) ** -0.3)


def test_bnbc_factor_of_safety_by_hand() -> None:
    # Sand FC 20 %, γ 18 / γsat 20, water table at 1 m; N = 18 at 12 m (ER 60): σ'v > pa.
    hole = {
        "id": "BH",
        "waterTable": 1000,
        "layers": [
            {
                "top": 0,
                "bottom": 20000,
                "soilType": "sand",
                "unitWeight": 18,
                "saturatedUnitWeight": 20,
                "finesContent": 20,
            }
        ],
        "spt": [{"depth": 12000, "N": 18}],
    }
    p = profile(hole, liquefactionMethod="bnbc2020", liquefaction={"magnitude": 7.0})
    point = liquefaction.screen(p, 0.25, "amax = 0.25 g")["points"][0]
    sv = 18 * 1 + 20 * 11
    se = sv - GAMMA_W * 11
    csr = 0.25 * (1 - 0.015 * 12) * sv / se  # no 0.65 factor (BNBC Eq 6.3.8)
    n160 = math.sqrt(PA / se) * 18 * 1.0  # CR 1.0 beyond 10 m
    alpha, beta = math.exp(1.76 - 190 / 400), 0.99 + 20**1.5 / 1000
    n = alpha + beta * n160
    crr = (
        (1 / (34 - n) + n / 135 + 50 / (10 * n + 45) ** 2 - 1 / 200)
        * (10**2.24 / 7.0**2.56)
        * (se / PA) ** -0.3
    )
    assert point["csr"] == pytest.approx(csr, abs=5e-4)
    assert point["N160cs"] == pytest.approx(n, abs=0.05)
    assert point["fs"] == pytest.approx(min(5, crr / csr), abs=0.005)
    assert point["liquefiable"] == (crr / csr < 1)


def test_bnbc_screening_rules() -> None:
    hole = {
        "id": "BH",
        "waterTable": 0,
        "layers": [
            {"top": 0, "bottom": 6000, "soilType": "sand", "finesContent": 5},
            {"top": 6000, "bottom": 9000, "soilType": "clay", "cu": 30},
            {"top": 9000, "bottom": 12000, "soilType": "silt", "plasticityIndex": 10},
            {"top": 12000, "bottom": 20000, "soilType": "sand"},
        ],
        "spt": [
            {"depth": 3000, "N": 5},
            {"depth": 4500, "N": 35},
            {"depth": 7500, "N": 4},
            {"depth": 10500, "N": 5},
            {"depth": 15000, "N": 28},
        ],
        "samples": [
            # The silt meets all four Finn et al. (1994) criteria: LI = (30 - 20)/(34 - 20).
            {"depth": 10000, "moisture": 30, "liquidLimit": 34, "plasticLimit": 20,
             "clayFraction": 8},
            # The clay fails LL ≤ 36.
            {"depth": 7000, "moisture": 40, "liquidLimit": 55, "plasticLimit": 25},
        ],
    }  # fmt: skip
    bnbc_result = liquefaction.screen(profile(hole, liquefactionMethod="bnbc2020"), 0.3, "a")
    loose, dense, clay, silt, deep = bnbc_result["points"]
    assert loose["screened"] and loose["liquefiable"]
    assert not dense["screened"] and "rule of thumb" in dense["reason"]
    assert not clay["screened"] and "except sensitive clays" in clay["reason"]
    assert "LL 55 % > 36 %" in clay["reason"]
    assert silt["screened"] and "susceptible by Finn et al. 1994" in silt["flags"][0]
    assert deep["screened"]
    assert any("check for sensitive clay" in n for n in bnbc_result["notes"])
    assert bnbc_result["method"] == "codePack" and "FS < 1" in bnbc_result["note"]
    # Idriss & Boulanger: the N > 30 test is computed and flagged, not skipped.
    ib = liquefaction.screen(profile(hole), 0.3, "a")["points"][1]
    assert ib["screened"] and "rule of thumb" in ib["flags"][0]


def test_finn_criteria_need_the_laboratory_data() -> None:
    hole = {
        "id": "BH",
        "layers": [{"top": 0, "bottom": 5000, "soilType": "clay", "plasticityIndex": 12}],
        "samples": [{"depth": 2000, "liquidLimit": 30}],
    }
    verdict, why = liquefaction.finn(profile(hole).layers[0])
    assert verdict is None and "fraction finer than 0.005 mm" in why


def test_amax_names_z_and_the_site_amplification() -> None:
    # The design earthquake's PGA (2/3) Z S (Sec 2.5.3.1 and 2.5.13.2), not the MCE's Z S.
    amax, note = liquefaction.amax_from(None, 0.20, ["SD"])
    assert amax == pytest.approx(2 / 3 * 0.20 * 1.35) == pytest.approx(0.18)
    assert note.startswith("amax = (2/3) Z S = (2/3) × 0.2 × 1.35 = 0.180 g, the design")
    assert "(Z = 0.2, seismic zoning map" in note and "Sec 2.5.13.2" in note
    assert "S = 1.35 of Table 6.2.16 for site class SD applied" in note
    assert "the maximum considered Z S would be 0.270 g, Z alone 0.2 g" in note
    assert liquefaction.amax_from(0.15, 0.2, ["SD"]) == (0.15, "amax = 0.15 g (soil report)")


# ─────────────────────────────── site class flags ───────────────────────────────


def test_s1_flag_needs_10_m_of_soft_clay() -> None:
    def hole(bottom: int) -> dict:
        return {
            "id": "BH",
            "depth": 30000,
            "layers": [
                {"top": 0, "bottom": 2000, "soilType": "sand"},
                {"top": 2000, "bottom": 8000, "soilType": "clay", "cu": 15},
                {"top": 8000, "bottom": bottom, "soilType": "clay", "plasticityIndex": 45},
                {"top": bottom, "bottom": 30000, "soilType": "sand"},
            ],
            # N = 3 in the clays: cu = 4.5 N60 ≈ 13 kPa where the log gives none.
            "spt": [{"depth": 1500, "N": 20}]
            + [{"depth": d, "N": 3} for d in range(4500, 13501, 3000)]
            + [{"depth": d, "N": 20} for d in range(16500, 30001, 3000)],
        }

    result = site_class.site_class(profile(hole(14000)))
    s1 = [f for f in result["flags"] if f["class"] == "S1"]
    assert s1 and "12.0 m of soft clay/silt from 2.0 to 14.0 m" in s1[0]["note"]
    assert "su = 15 kPa (measured)" in s1[0]["note"] and "PI = 45" in s1[0]["note"]
    assert result["class"] in site_class.ORDER  # still SA-SE
    assert not [
        f for f in site_class.site_class(profile(hole(11000)))["flags"] if f["class"] == "S1"
    ]


def test_s2_flag_makes_the_site_sd_and_raises_amax() -> None:
    # N̄ ≈ 18.8 (SC), but the loose sand below the water table at the top liquefies.
    hole = {
        "id": "BH-1",
        "waterTable": 1000,
        "depth": 30000,
        "layers": [{"top": 0, "bottom": 30000, "soilType": "sand", "finesContent": 5}],
        "spt": [{"depth": 1500, "N": 4}, {"depth": 3000, "N": 4}]
        + [{"depth": d, "N": 40} for d in range(4500, 30001, 1500)],
    }
    settings = default_project_settings()
    settings = settings.model_copy(
        update={"site": settings.site.model_copy(update={"siteClass": "SC"})}
    )
    assert site_class.site_class(profile(hole))["class"] == "SC"
    result = soil_report(text(hole), settings.model_dump_json(by_alias=True))
    site = result["siteClass"]
    assert site["class"] == "SD" and site["flags"][0]["class"] == "S2"
    assert site["flags"][0]["boreholes"] == ["BH-1"]
    assert site["flags"][0]["note"].startswith("S2 — liquefiable layers found: BNBC Table 6.2.13")
    assert result["boreholes"][0]["siteClass"]["fromSpt"] == "SC"
    assert result["amax"] == pytest.approx(2 / 3 * 0.20 * 1.35)  # S of SD, not 1.15 of SC
    assert any(n.startswith("S2 — liquefiable layers found") for n in result["notes"])
    assert (
        result["practice"] == "textbook" and result["liquefactionMethod"] == "idrissBoulanger2014"
    )
    assert result["permissibleSettlement"]["value"] == 50
    assert (
        "Peck" not in result["methods"]["spt"] and "Table 6.3.8" in result["methods"]["settlement"]
    )
    # An SE site stays SE.
    assert site_class.flag_liquefaction({"class": "SE", "flags": []}, True)["class"] == "SE"


def _sand(bid: str, n: int) -> dict:
    """Clean sand to 10 m, water table at 1 m, the same N every 1.5 m from 1.5 to 9 m."""
    return {
        "id": bid,
        "waterTable": 1000,
        "depth": 10000,
        "layers": [{"top": 0, "bottom": 10000, "soilType": "sand", "finesContent": 0}],
        "spt": [{"depth": d, "N": n} for d in range(1500, 9001, 1500)],
    }


@pytest.mark.parametrize(("method", "n"), [("idrissBoulanger2014", 19), ("bnbc2020", 25)])
def test_s2_screens_again_until_the_liquefiable_boreholes_settle(method: str, n: int) -> None:
    # Settings SC: A (N = 15) liquefies at amax = (2/3) 0.2 × 1.15 = 0.153 g, B does not; the S2
    # flag raises amax to (2/3) 0.2 × 1.35 = 0.18 g, at which B's deepest test liquefies too.
    report = SoilReport.model_validate(
        {"boreholes": [_sand("A", 15), _sand("B", n)], "design": {"liquefactionMethod": method}}
    )
    b = Profile(report, report.boreholes[1])
    assert not liquefaction.screen(b, 2 / 3 * 0.2 * 1.15, "")["layers"]
    assert liquefaction.screen(b, 2 / 3 * 0.2 * 1.35, "")["layers"]
    settings = default_project_settings()
    settings = settings.model_copy(
        update={"site": settings.site.model_copy(update={"siteClass": "SC"})}
    )
    result = classify(report, settings)
    assert result["amax"] == pytest.approx(0.18)
    assert result["liquefiable"] == ["A", "B"]
    for bh in ("A", "B"):  # screening, class and flag agree
        assert result["screenings"][bh]["layers"]
        assert result["sites"][bh]["class"] == "SD"
        assert [f["class"] for f in result["sites"][bh]["flags"]] == ["S2"]
    s2 = [f for f in result["project"]["flags"] if f["class"] == "S2"]
    assert s2 and s2[0]["boreholes"] == ["A", "B"]


def test_lpi_stops_at_the_bottom_of_the_log() -> None:
    # 10 m of sand, water table at the ground, N = 5 at 0.3 and 1.5 m only: the deepest test
    # stands for 0.9-10 m (its layer to the end of the log), not 0.9-20 m.
    hole = {
        "id": "BH",
        "waterTable": 0,
        "depth": 10000,
        "layers": [{"top": 0, "bottom": 10000, "soilType": "sand", "finesContent": 0}],
        "spt": [{"depth": 300, "N": 5}, {"depth": 1500, "N": 5}],
    }
    result = liquefaction.screen(profile(hole), 0.18, "")
    f1, f2 = (1 - p["fs"] for p in result["points"])
    # ∫ (10 - 0.5 z) dz: 0-0.9 m = 9 - 0.2025 = 8.7975; 0.9-10 m = 91 - 0.25 (100 - 0.81) = 66.2025
    assert result["lpi"] == pytest.approx(f1 * 8.7975 + f2 * 66.2025, abs=0.5)
    # To 20 m it would be 0.9-20 m = 191 - 0.25 (400 - 0.81) = 91.2025, 25 more.
    assert result["lpi"] < f1 * 8.7975 + f2 * 91.2025 - 10


def test_site_class_descriptions_follow_table_6_2_13() -> None:
    assert code_data.SITE_CLASSES["SD"].startswith("Loose-to-medium cohesionless soil")
    assert "Vs 360-800 m/s" in code_data.SITE_CLASSES["SB"]
    assert "Vs 180-360 m/s" in code_data.SITE_CLASSES["SC"]
    assert "stiff soil" not in code_data.SITE_CLASSES["SD"].lower()
    assert set(code_data.SITE_CLASSES) == {"SA", "SB", "SC", "SD", "SE"}

"""Part 9 pile rules of the code pack (B13): structural detailing, lateral load, load tests,
downdrag and swelling. The values are pinned through the default pack (BNBC 2020 Part 6 Ch 3:
Secs 3.10.1.17, 3.10.1.21-3.10.1.23, 3.10.1.29, 3.10.1.31, 3.10.2, 3.10.3.2, 3.10.4.1-3.10.4.2,
3.10.4.9, 3.10.6.15, 3.10.6.17-3.10.6.19, 3.11; Tables 6.3.5, 6.3.11, 6.3.12, 6.3.16)."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest
from test_substructure_piles import CLAY_ON_SAND, profile
from test_substructure_shallow import REINFORCEMENT, frame, write_substructure  # noqa: F401

from saengine.fem import ssi
from saengine.library.objects import BarGroup, LinearReinforcement, Transverse, TransverseZone
from saengine.library.substructure import PileLoadTest, PileType
from saengine.soil.piles import pile_rules
from saengine.substructure import (
    downdrag,
    load_tests,
    pile_detailing,
    pile_lateral,
    piles,
    precast,
)


def _bars(count: int, dia: float, cover: float = 75, tie: Transverse | None = None):
    return LinearReinforcement(
        material="B420",
        cover=cover,
        longitudinal=[BarGroup(position="perimeter", count=count, dia=dia)],
        transverse=tie,
    )


def _checks(pile_type: PileType, fc: float = 25, fy: float = 420, **kw) -> dict[str, dict]:
    checks, _ = pile_detailing.detailing_checks(pile_type, fc, fy, **kw)
    return {c["name"]: c for c in checks}


# ─────────────────────────────── pack values ───────────────────────────────


def test_pack_values_of_the_pile_rules() -> None:
    found = pile_rules()
    bored, driven, cip = found.detailing.bored, found.detailing.driven, found.detailing.castInPlace
    # Secs 3.10.4.1-3.10.4.2, 3.10.4.9 (pp. 761-765)
    assert (bored.minFc, bored.minDiameter, bored.diameterStep) == (21, 400, 50)
    assert (bored.minBars, bored.largeDiameter, bored.largeMinBar) == (6, 600, 16)
    assert (bored.cover, bored.minHoopPitch, bored.minFy) == (75, 100, 420)
    assert bored.cement == {"dry": 350, "submerged": 400} and bored.waterCement == 0.45
    assert [m.slump for m in bored.mixes] == [125, 150, 200]  # Table 6.3.12
    # Table 6.3.11 (p. 764)
    rows = {r.diameter: (r.count, r.bar, r.hoop, r.pitch) for r in bored.guidance}
    assert rows[400] == (6, 16, 8, 200) and rows[1500] == (12, 20, 10, 400)
    assert rows[2400] == (16, 25, 12, 500)
    # Sec 3.10.1.31 (pp. 756-757); impact Sec 3.10.3.2 (p. 760)
    assert (driven.minFc, driven.hardFc, driven.maxSlenderness) == (21, 28, 50)
    assert (driven.tieEnd, driven.tieBody, driven.minTie, driven.impact) == (0.004, 0.002, 6, 0.5)
    # Sec 3.10.2 (p. 758)
    assert (cip.minButtArea, cip.minTip, cip.cover, cip.corrosiveCover) == (65000, 200, 50, 75)
    # Table 6.3.5 (p. 715)
    assert {r.id: r.fc for r in found.detailing.concrete} == {
        "footing": 20, "bored": 18, "driven": 25
    }  # fmt: skip
    # Table 6.3.16 (p. 778)
    assert found.lateral.groupRatio == [(3, 0.25), (4, 0.40), (6, 0.70), (8, 1.00)]
    assert (found.lateral.individualNormal, found.lateral.individualParallel) == (2.5, 8)


@pytest.mark.parametrize(
    ("area", "ratio"), [(0.4, 0.005), (0.5, 0.005), (0.51, 0.00375), (1.0, 0.00375), (1.1, 0.0025)]
)
def test_bored_least_steel_bands(area: float, ratio: float) -> None:
    # Sec 3.10.4.9: 0.5 % for Ac <= 0.5 m², 0.375 % for 0.5-1 m², 0.25 % above.
    assert pile_detailing.band_ratio(pile_rules().detailing.bored.minSteel, area) == ratio


@pytest.mark.parametrize(("lb", "ratio"), [(29.9, 0.01), (30, 0.015), (40, 0.015), (40.1, 0.02)])
def test_precast_least_steel_by_slenderness(lb: float, ratio: float) -> None:
    # Sec 3.10.1.31: 1 % for L < 30B, 1.5 % for 30-40B, 2 % above 40B (3a #13: was 1 %).
    assert pile_detailing.band_ratio(pile_rules().detailing.driven.steelByLength, lb) == ratio


# ─────────────────────────────── detailing ───────────────────────────────


def test_bored_pile_detailing() -> None:
    # Ø600: Ac = 0.283 m², 0.5 % = 1414 mm²; 6Ø16 = 1206 mm² is short, 8Ø16 = 1608 mm² passes.
    tie = Transverse(type="tie", dia=10, spacing=90)
    short = _checks(PileType(id="P", diameter=600, length=18000, material="C",
                             reinforcement=_bars(6, 16, tie=tie)), fc=20, fy=415)  # fmt: skip
    assert short["Pile longitudinal steel"]["demand"] == pytest.approx(0.005 * math.pi * 9e4, 0.01)
    assert not short["Pile longitudinal steel"]["ok"]
    assert not short["Pile concrete grade"]["ok"]  # 20 < 21 MPa
    assert short["Pile concrete grade"]["demand"] == 21
    assert not short["Pile bar grade"]["ok"]  # 415 < 420
    assert not short["Pile hoop pitch"]["ok"]  # 90 < 100 mm
    good = _checks(PileType(id="P", diameter=600, length=18000, material="C",
                            reinforcement=_bars(8, 16, tie=Transverse(type="tie", dia=10,
                                                                      spacing=250))))  # fmt: skip
    assert all(c["ok"] for c in good.values()), good
    # Ø620 is not a 50 mm step (reported only); Ø350 is below 400 mm.
    odd = _checks(PileType(id="P", diameter=620, length=18000, material="C",
                           reinforcement=_bars(8, 16)))  # fmt: skip
    assert odd["Pile diameter step"]["flag"]
    small = _checks(PileType(id="P", diameter=350, length=9000, material="C"))
    assert not small["Pile diameter"]["ok"] and not small["Pile longitudinal steel"]["ok"]


def test_bored_pile_bar_size_cover_and_cage() -> None:
    # Ø600 and over: bars at least 16 mm; cover 75 mm; cage 2 m past a 4 m casing.
    pile = PileType(id="P", diameter=600, length=18000, material="C",
                    reinforcement=_bars(12, 12, cover=50), reinforcedLength=5000,
                    casingDepth=4000)  # fmt: skip
    checks = _checks(pile)
    assert not checks["Pile bar size"]["ok"] and not checks["Pile cover"]["ok"]
    assert checks["Pile cage length"]["demand"] == 6000 and not checks["Pile cage length"]["ok"]


def test_bored_pile_cement_by_placement() -> None:
    from saengine.library.materials import DesignMix

    mix = DesignMix(cement=380, water=170, fineAggregate=700, coarseAggregate=1100)
    pile = PileType(id="P", diameter=500, length=12000, material="C",
                    reinforcement=_bars(8, 16))  # fmt: skip
    under = _checks(pile, composition=mix)  # tremie: 400 kg/m³
    assert not under["Pile concrete cement content"]["ok"]
    dry = _checks(pile.model_copy(update={"placement": "dry"}), composition=mix)  # 350
    assert dry["Pile concrete cement content"]["ok"]
    assert under["Pile concrete w/c"]["flag"]  # 170/380 = 0.447 <= 0.45


def test_precast_pile_grade_slenderness_and_ties() -> None:
    # Driven: f'c at least 25 MPa (Table 6.3.5 over the 21 of Sec 3.10.1.31), 28 for hard
    # driving; L/B <= 50; ties 0.4 % at the ends and 0.2 % in the body.
    tie = Transverse(type="tie", dia=8, spacing=150, zone=TransverseZone(spacing=50))
    pile = PileType(id="P", kind="driven", diameter=400, length=21000, material="C",
                    reinforcement=_bars(8, 20, cover=40, tie=tie))  # fmt: skip
    checks = _checks(pile, fc=25)
    assert checks["Pile concrete grade"]["demand"] == 25 and checks["Pile concrete grade"]["ok"]
    assert not checks["Precast pile slenderness L/B"]["ok"]  # 52.5 > 50
    # ends Ø8 @ 50: 4 (400 - 80 - 8) × 50.27 / 50 / 400² = 0.784 %; body @ 150 = 0.261 %
    assert checks["Precast pile tie volume, ends"]["capacity"] == pytest.approx(0.78, abs=0.01)
    assert checks["Precast pile tie volume, body"]["ok"]
    hard = _checks(pile.model_copy(update={"hardDriving": True}), fc=25)
    assert hard["Pile concrete grade"]["demand"] == 28 and not hard["Pile concrete grade"]["ok"]


def test_cast_in_place_pile_rules() -> None:
    # Sec 3.10.2.2: butt >= 650 cm² (Ø280 = 616 cm² fails), tip >= 200 mm.
    pile = PileType(id="P", kind="drivenCastInPlace", diameter=280, length=9000, material="C",
                    tipDiameter=180)  # fmt: skip
    checks = _checks(pile)
    assert not checks["Cast-in-place pile butt area"]["ok"]
    assert not checks["Cast-in-place pile tip"]["ok"]
    # 75 mm cover when the concrete goes in under water or slurry, 50 mm in a dry bore.
    bars = _bars(6, 16, cover=60)
    wet = _checks(pile.model_copy(update={"diameter": 400, "reinforcement": bars}))
    dry = _checks(pile.model_copy(update={"diameter": 400, "reinforcement": bars,
                                          "placement": "dry"}))  # fmt: skip
    assert not wet["Pile cover"]["ok"] and dry["Pile cover"]["ok"]


def test_corrosive_site_asks_75_mm_cover() -> None:
    pile = PileType(id="P", kind="driven", diameter=400, length=12000, material="C",
                    reinforcement=_bars(8, 20, cover=40))  # fmt: skip
    checks, notes = pile_detailing.detailing_checks(pile, 30, 420, corrosive=["pH 5.5 < 6"])
    cover = next(c for c in checks if c["name"] == "Pile cover, corrosive site")
    assert cover["demand"] == 75 and not cover["ok"]
    assert any("sulphate-resisting" in n for n in notes)


def test_precast_handling_impact_from_the_pack() -> None:
    # Sec 3.10.3.2: the weight plus 50 % (formerly cited as ACI 543R).
    factor, clause = precast.impact_factor()
    assert factor == 1.5 and "3.10.3.2" in clause


def test_service_stress_of_precast_piles_from_the_pack() -> None:
    checks = piles.structural_checks("driven", 400, 30, 420, None, 500, 0, 1000)
    stress = next(c for c in checks if c["name"] == "Pile service stress (driven precast)")
    assert stress["capacity"] == pytest.approx(0.33 * 30)


# ─────────────────────────────── lateral ───────────────────────────────


def test_group_ratio_of_in_line_piles() -> None:
    # Table 6.3.16: two piles 3B apart in line take 0.25; across the load they act alone
    # beyond 2.5B.
    d = 500
    in_line = [(0, 0), (1500, 0)]
    assert pile_lateral.group_ratio(in_line, d, 0)[0] == pytest.approx(0.25)
    assert pile_lateral.group_ratio(in_line, d, 1)[0] == pytest.approx(1.0)
    assert pile_lateral.group_ratio([(0, 0), (2500, 0)], d, 0)[0] == pytest.approx(0.55)  # 5B
    assert pile_lateral.group_ratio([(0, 0), (4500, 0)], d, 0)[0] == pytest.approx(1.0)  # 9B
    # a 2 x 2 group at 3B: every pile has an in-line neighbour at 3B
    square = [(0, 0), (1500, 0), (0, 1500), (1500, 1500)]
    assert pile_lateral.group_ratio(square, d, 0)[0] == pytest.approx(0.25)


def test_cap_springs_take_the_group_ratio() -> None:
    k = ssi.pile_group_springs([(-0.75, 0), (0.75, 0)], 1e8, 1e7, 1e6, 1.0, (0.25, 1.0))
    assert k[0] == pytest.approx(0.25 * 2e7) and k[1] == pytest.approx(2e7)


def test_head_stiffness_fixed_is_twice_free() -> None:
    p = profile(CLAY_ON_SAND)
    fixed = pile_lateral.head_stiffness(p, 1.5, "bored", 500, 18000, 25000, "fixed", 1.0)
    free = pile_lateral.head_stiffness(p, 1.5, "bored", 500, 18000, 25000, "free", 1.0)
    assert fixed["K"] == pytest.approx(2 * free["K"])
    # depth to fixity 1.4 R, R = (EI / kB)^1/4 = 1 / (√2 β)
    beta = fixed["beta"]
    assert pile_lateral.fixity_depth(fixed) == pytest.approx(1.4 / (math.sqrt(2) * beta), 1e-6)


def test_head_deflection_check() -> None:
    stiffness = {"K": 20000.0, "basis": "Winkler", "betaL": 5}  # N/mm
    checks, notes = pile_lateral.lateral_checks(
        {"S1": np.array([400e3, 0.0])}, 4, stiffness, (0.5, 1.0), None
    )
    # 100 kN per pile / (0.5 × 20 kN/mm) = 10 mm > 5 mm (the pack's)
    deflection = checks[0]
    assert deflection["demand"] == pytest.approx(10.0) and deflection["capacity"] == 5
    assert any("Broms" in n for n in notes)


def test_unbraced_pile_is_a_column() -> None:
    bars = _bars(8, 20)
    checks = pile_lateral.unbraced_checks(
        500, False, 25, 420, 23500, bars, {"U1": (1500e3, 1000e3)}, {"U1": 50e6}, 4000, 3000,
        "fixed", "test",
    )  # fmt: skip
    assert checks[0]["name"] == "Unbraced pile as a column" and "δ" in checks[0]["note"]


def test_soft_clay_below_the_head_is_unsupported() -> None:
    soft = json.loads(json.dumps(CLAY_ON_SAND))
    soft["layers"][0]["cu"] = 8
    length, why = pile_lateral.unsupported_length(profile(soft), 1.5, None)
    assert length == pytest.approx(8500) and "cu < 10" in why


# ─────────────────────────────── load tests ───────────────────────────────


CURVE = [(0, 0), (500, 2), (1000, 5), (1500, 9), (2000, 15), (2500, 30), (3000, 60)]


def _test(**kw) -> PileLoadTest:
    return PileLoadTest(**{"id": "TP1", "pileType": "P", "points": CURVE, **kw})


def test_compression_safe_load_single_pile() -> None:
    # Sec 3.10.1.17: 2/3 of the load at 12 mm (1750 kN) = 1166.7; 1/2 of the load at 10 % of
    # D = 50 mm (2833 kN) = 1416.7; failure loads / 2.0 cap it.
    pile = PileType(id="P", diameter=500, length=18000, material="C")
    out = load_tests.compression(_test(test="routine"), pile, 25000)
    assert out["safe"] == pytest.approx(1166.7, abs=0.1)
    initial = load_tests.compression(_test(), pile, 25000)
    names = {m["name"]: m["value"] for m in initial["methods"]}
    assert names["settlement 10 % of D"] == pytest.approx(2833.3, abs=0.1)
    # IS: the lesser of 10 % D and 12 mm
    assert names["lesser of 10 % of D and 12 mm"] == pytest.approx(1750.0)
    assert initial["safe"] == pytest.approx(min(1166.7, initial["ultimate"] / 2), abs=0.1)


def test_brinch_hansen_and_butler_hoy() -> None:
    plunging = load_tests.curve([(1000, 5), (2000, 12), (2200, 20), (2300, 40), (2350, 80)])
    q = load_tests.brinch_hansen(plunging)
    assert load_tests.movement_at(plunging, q) == pytest.approx(
        2 * load_tests.movement_at(plunging, 0.9 * q), rel=1e-6
    )
    assert load_tests.brinch_hansen(load_tests.curve(CURVE)) is None  # not within the test
    # Butler-Hoy: initial slope 5/1000 = 0.005 mm/kN; 1.27 mm per tonne = 0.1295 mm/kN is
    # first reached on the 2200-2300 kN segment (0.2): the tangent at (2200, 20) meets
    # s = 0.005 q.
    target = 1.27 / 9.80665
    expected = (20 - target * 2200) / (0.005 - target)
    assert load_tests.butler_hoy(plunging) == pytest.approx(expected)
    assert load_tests.butler_hoy(load_tests.curve(CURVE)) is None


def test_davisson_offset() -> None:
    # 0.15 in + D/120: 3.81 + 400/120 = 7.14 mm over PL/(AE) = 12000/(160000 × 30000) mm/N.
    points = load_tests.curve(CURVE)
    q = load_tests.davisson(points, 400, 12000, 160000, 30000)
    s = load_tests.movement_at(points, q)
    assert s == pytest.approx(12000 / (160000 * 30000) * q * 1e3 + 3.81 + 400 / 120, rel=1e-6)


def test_group_uplift_and_lateral_tests() -> None:
    pile = PileType(id="P", diameter=500, length=18000, material="C")
    group = load_tests.compression(_test(group=True), pile, 25000)
    # the load at 25 mm (2333.3) and 2/3 of the load at 40 mm (2/3 × 2666.7)
    assert group["safe"] == pytest.approx(0.6667 * (2500 + 500 * 10 / 30), abs=0.1)
    up = load_tests.uplift(_test(kind="uplift", breakLoad=2400))
    # 2/3 × 1750 = 1166.7; 1/2 × 2400 = 1200; 2400 / 2.0 = 1200
    assert up["safe"] == pytest.approx(1166.7, abs=0.1)
    lat = load_tests.lateral(_test(kind="lateral", points=[(0, 0), (50, 3), (100, 7), (150, 14)]))
    # 1/2 × the load at 12 mm (142.9) = 71.4; the load at 5 mm = 75
    assert lat["safe"] == pytest.approx(67.9, abs=0.1)


def test_criterion_not_reached_takes_the_largest_load() -> None:
    out = load_tests.lateral(_test(kind="lateral", points=[(0, 0), (60, 2), (120, 4)]))
    assert out["safe"] == pytest.approx(60.0)  # 1/2 × 120 (12 mm not reached)
    assert "not reached" in out["basis"]


def test_pile_type_tests_give_the_load_test_factor() -> None:
    pile = PileType(id="P", diameter=500, length=18000, material="C")
    found = load_tests.pile_type_tests([_test(), _test(id="L1", kind="lateral")], pile, 25000)
    assert found["loadTest"] and found["lateral"]["id"] == "L1"
    assert not load_tests.pile_type_tests([_test(kind="uplift")], pile, 25000)["loadTest"]


# ─────────────────────────────── downdrag ───────────────────────────────


FILL_ON_SAND = {
    "id": "BH-F",
    "waterTable": 0,
    "depth": 30000,
    "layers": [
        {"top": 0, "bottom": 4000, "soilType": "fill", "unitWeight": 17,
         "saturatedUnitWeight": 17, "cu": 20},
        {"top": 4000, "bottom": 30000, "soilType": "sand", "unitWeight": 19,
         "saturatedUnitWeight": 19},
    ],
    "spt": [{"depth": d * 1000, "N": 25} for d in (2, 6, 9, 12, 15, 18, 21, 24, 27)],
}  # fmt: skip


def test_settling_soil_from_the_top() -> None:
    p = profile(FILL_ON_SAND)
    depth, why = downdrag.settling_depth(p, None)
    assert depth == pytest.approx(4.0) and "fill" in why
    assert downdrag.settling_depth(profile(CLAY_ON_SAND), None)[0] is None  # cu 50: not soft
    assert downdrag.settling_depth(p, 2500)[0] == pytest.approx(2.5)


def test_neutral_point_and_dragload() -> None:
    p = profile(FILL_ON_SAND)
    single = piles.single_pile(p, "bored", 0.5, 15.0, 1.0)
    out = downdrag.neutral_point(p, single, 600, 4.0)
    # the sand below does not move: the neutral point is at most the settling soil's bottom
    assert out["neutral"] <= 4000 and out["Qn"] > 0
    assert out["Qn"] + out["Qbelow"] > single["Qs"]  # the fill now carries friction too


def test_downdrag_checks() -> None:
    from saengine.library.substructure import Design

    p = profile(FILL_ON_SAND)
    single = piles.single_pile(p, "bored", 0.5, 15.0, 1.0)
    checks, notes, detail = downdrag.checks(
        p, single, Design(), 500, 200, 450, 700, {"fc": 25, "fy": 420, "reinforcement": None}
    )
    names = {c["name"] for c in checks}
    assert {"Pile with downdrag", "Pile section at the neutral point"} <= names
    assert detail["downdrag"]["neutral"] <= 4000
    assert any("bitumen" in n for n in notes)


def test_swelling_uplift_with_a_given_zone() -> None:
    from saengine.library.substructure import Design

    p = profile(CLAY_ON_SAND)
    single = piles.single_pile(p, "bored", 0.5, 18.0, 1.0)
    checks, _, detail = downdrag.checks(
        p, single, Design(downdrag=False, swellingDepth=3000), 500, 50, 450, 700, None
    )
    swell = next(c for c in checks if c["name"] == "Pile against swelling uplift")
    assert detail["swelling"]["zone"] == 3000 and swell["demand"] > 0


# ─────────────────────────────── in the report ───────────────────────────────


def test_pile_cap_reports_the_pile_rules(frame: Path, tmp_path: Path) -> None:  # noqa: F811
    from saengine.library.settings import SOIL_FILE
    from saengine.substructure import substructure_report

    root = tmp_path / "piled"
    shutil.copytree(frame, root)
    (root / SOIL_FILE).parent.mkdir(parents=True, exist_ok=True)
    (root / SOIL_FILE).write_text(
        json.dumps({"boreholes": [{**FILL_ON_SAND, "x": 3000, "y": 2500}]}), encoding="utf-8"
    )
    x0, y0 = 5250, -750
    points = [(x0, y0), (x0 + 1500, y0), (x0 + 1500, y0 + 1500), (x0, y0 + 1500)]
    bars = {"material": "B420DWR", "cover": 75,
            "longitudinal": [{"position": "perimeter", "count": 8, "dia": 16}],
            "transverse": {"type": "tie", "dia": 10, "spacing": 200}}  # fmt: skip
    write_substructure(root, {
        "foundations": [
            {"id": "PC1", "type": "pileCap", "columns": ["C2"], "center": [x0 + 750, y0 + 750],
             "length": 2300, "width": 2300, "thickness": 900, "material": "C24.1",
             "reinforcement": REINFORCEMENT, "piles": ["PL1", "PL2", "PL3", "PL4"]},
        ],
        "pileTypes": [{"id": "BP500", "diameter": 500, "length": 18000, "material": "C24.1",
                       "reinforcement": bars}],
        "piles": [{"id": f"PL{k + 1}", "type": "BP500", "position": list(p)}
                  for k, p in enumerate(points)],
        "loadTests": [{"id": "TP1", "pileType": "BP500", "points": CURVE},
                      {"id": "LT1", "pileType": "BP500", "kind": "lateral",
                       "points": [[0, 0], [50, 3], [100, 7], [150, 14]]}],
    })  # fmt: skip
    report = substructure_report(root)
    assert not report["skipped"], report["skipped"]
    cap = report["foundations"][0]
    names = {c["name"] for c in cap["checks"]}
    assert {"Pile longitudinal steel", "Pile head deflection", "Pile with downdrag",
            "Pile lateral load (load test)"} <= names, names  # fmt: skip
    assert cap["pile"]["factors"]["loadTest"]  # the compression test: FS 2.0
    assert cap["pile"]["Qa"] <= 1166.7 + 1e-6
    assert [t["id"] for t in cap["loadTests"]] == ["TP1", "LT1"]
    assert cap["pileRules"]["groupRatio"] == [0.25, 0.25]

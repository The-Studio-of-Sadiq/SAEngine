"""Site investigation adequacy, problem soils and soil chemistry, through the BNBC 2020 pack.

Each value is pinned with its clause (BNBC 2020 Part 6, gazette pages)."""

from __future__ import annotations

import json

import pytest

from saengine.codes.tables import builtin_table
from saengine.library.soil import Investigation, Sample, SoilReport
from saengine.soil import bearing, chemistry, investigation, special_soils
from saengine.soil.report import soil_report


def table():
    return builtin_table("siteInvestigation")


def sample(**values) -> Sample:
    return Sample.model_validate({"depth": 3000, **values})


def hole(id_: str, x: float, y: float, depth: float = 12000, **extra) -> dict:
    return {
        "id": id_,
        "x": x,
        "y": y,
        "depth": depth,
        "layers": [{"top": 0, "bottom": depth, "soilType": "sand", "phi": 30}],
        "spt": [{"depth": 1500, "N": 12}],
        **extra,
    }


def checks(report: dict) -> dict[str, dict]:
    out = investigation.check(SoilReport.model_validate(report))
    assert out["covered"]
    return {c["id"]: c for c in out["checks"]}


# ─────────────────────────────── pack values ───────────────────────────────


def test_pack_values_sec_3_4_4_and_3_4_5() -> None:
    t = table()
    # Sec 3.4.4(viii) p. 702: 3 borings (small), 5 (large); spacing 60/30/15 and 45/30/15 m.
    assert t.borings.minimum == {"small": 3, "large": 5}
    assert t.borings.spacing["small"] == {"uniform": 60, "average": 30, "erratic": 15}
    assert t.borings.spacing["large"] == {"uniform": 45, "average": 30, "erratic": 15}
    # Sec 3.4.4(ix) p. 703: 67 % of the borings within the area under the building.
    assert t.borings.insideFootprint == 0.67
    # Sec 3.4.5 pp. 703-704.
    d = t.depth
    assert d.spread == [(2, 2), (5, 4)] and d.minimum == 2.0
    assert (d.buildingWidthFactor, d.buildingShare) == (1.5, 0.5)
    assert (d.belowPileTip, d.pileGroupWidths, d.rockCore, d.bedrockCore) == (6.0, 2.0, 1.5, 3.0)
    assert (d.shaftRockCoreDiameters, d.shaftGroupRockCoreWidths) == (3.0, 2.0)


def test_pack_values_chemistry() -> None:
    t = table()
    # Sec 3.10.1.29 p. 754: chloride >= 500 ppm, sulphate >= 2000 ppm, pH < 6.
    assert (t.corrosiveSite.chloride, t.corrosiveSite.sulphate, t.corrosiveSite.pHBelow) == (
        500,
        2000,
        6.0,
    )
    # Sec 3.6.2 pp. 715-717: 0.015 / 0.035 / 0.075 mm per side per year.
    rates = t.steelCorrosion
    assert rates["undisturbedSoil"] == 0.015 and rates["atmospheric"] == 0.035
    assert rates["seawaterImmersion"] == 0.035 and rates["lowWaterAndSplash"] == 0.075
    # Table 6.5.2 p. 846.
    classes = {c.id: c for c in t.sulphate.classes}
    assert (classes["moderate"].soilMin, classes["moderate"].waterMin) == (0.10, 150)
    assert (classes["severe"].soilMin, classes["severe"].waterMin) == (0.20, 1500)
    assert (classes["verySevere"].soilMin, classes["verySevere"].waterMin) == (2.00, 10000)
    assert [classes[k].maxWaterCement for k in ("moderate", "severe", "verySevere")] == [
        0.50,
        0.45,
        0.45,
    ]
    # Sec 5.5.1.1-5.5.1.2 p. 845: 0.40, or 0.45 with 12 mm more cover; 0.50 low permeability.
    c = t.chloride
    assert (c.maxWaterCement, c.maxWaterCementExtraCover, c.extraCover) == (0.40, 0.45, 12)
    assert c.lowPermeabilityWaterCement == 0.50


# ─────────────────────────────── exploration depth ───────────────────────────────


@pytest.mark.parametrize(
    ("b", "l_", "widths"),
    [(2, 2, 2.0), (2, 4, 2.0), (2, 10, 4.0), (2, 20, 4.0), (2, 7, 2 + 2 * (3.5 - 2) / 3)],
)
def test_spread_exploration_depth_sec_3_4_5_i(b: float, l_: float, widths: float) -> None:
    # 2B for L <= 2B, 4B for L >= 5B, linear between (Sec 3.4.5(i), p. 703).
    assert investigation.zone_widths(b, l_) == pytest.approx(widths)
    assert bearing.zone_widths(b, l_) == pytest.approx(widths)


def test_strip_footing_explores_deeper_in_bearing() -> None:
    from saengine.soil.profile import Profile

    report = SoilReport.model_validate(
        {
            "boreholes": [
                {
                    "id": "BH",
                    "layers": [
                        {"top": 0, "bottom": 4000, "soilType": "sand", "phi": 32},
                        {"top": 4000, "bottom": 20000, "soilType": "fill", "unitWeight": 16},
                    ],
                }
            ]
        }
    )
    p = Profile(report, report.boreholes[0])
    # The fill is 3 m below a 1 m deep, 1.2 m wide base: beyond 2B = 2.4 m; a strip
    # (L >= 5B) explores 4B = 4.8 m, so the fill without strength withholds qa.
    assert bearing.shear(p, 1.2, 1.2, 1.0, 3.0)["qa"] is not None
    assert bearing.shear(p, 1.2, 12.0, 1.0, 3.0)["qa"] is None


# ─────────────────────────────── adequacy checks ───────────────────────────────


def test_number_pattern_spacing_inside() -> None:
    five = [hole(f"BH-{i}", x, y) for i, (x, y) in enumerate(
        [(0, 0), (20000, 0), (0, 20000), (20000, 20000), (10000, 10000)], 1)]  # fmt: skip
    footprint = [[-1000, -1000], [21000, -1000], [21000, 21000], [-1000, 21000]]
    rows = checks({"boreholes": five, "investigation": {"footprint": footprint}})
    assert rows["number"]["status"] == "ok"
    assert rows["pattern"]["status"] == "ok"
    assert rows["spacing"]["status"] == "ok"  # 14.1 m <= 30 m (large, average)
    assert rows["inside"]["status"] == "ok"
    # Three borings for a large building: fewer than 5 (Sec 3.4.4(viii)).
    rows = checks({"boreholes": five[:3]})
    assert rows["number"]["status"] == "fail"
    # A small building needs 3.
    rows = checks({"boreholes": five[:3], "investigation": {"buildingSize": "small"}})
    assert rows["number"]["status"] == "ok"
    # In one line.
    line = [hole(f"L{i}", i * 10000, 0) for i in range(5)]
    assert checks({"boreholes": line})["pattern"]["status"] == "fail"
    # Erratic strata: 15 m; 20 m apart fails.
    far = [hole(f"F{i}", x, y) for i, (x, y) in enumerate([(0, 0), (20000, 0), (0, 20000)])]
    rows = checks({"boreholes": far, "investigation": {"stratification": "erratic"}})
    assert rows["spacing"]["status"] == "fail"


def test_depth_of_borings() -> None:
    # Spread footing 2 m square at 1.5 m: 1.5 + 2 x 2 = 5.5 m.
    rows = checks({"boreholes": [hole("A", 0, 0, depth=5000), hole("B", 9000, 0, depth=6000)]})
    assert "5.5 m" in rows["depth"]["required"] and rows["depth"]["status"] == "fail"
    assert "A 5.0 m" in rows["depth"]["provided"]
    # Piles: tip 20 m + max(6 m, 2 x 4 m group) = 28 m (Sec 3.4.5(iv)).
    inv = {"foundation": "pile", "pileTipDepth": 20000, "pileGroupWidth": 4000,
           "buildingSize": "small"}  # fmt: skip
    rows = checks({"boreholes": [hole("A", 0, 0, depth=28000)], "investigation": inv})
    assert rows["depth"]["status"] == "ok" and "28.0 m" in rows["depth"]["required"]
    rows = checks({"boreholes": [hole("A", 0, 0, depth=27000)], "investigation": inv})
    assert rows["depth"]["status"] == "fail"


def test_deep_borings_and_rock_core() -> None:
    footprint = [[0, 0], [20000, 0], [20000, 12000], [0, 12000]]
    # Large building 12 m wide on footings at 1.5 m: 50 % to 1.5 + 1.5 x 12 = 19.5 m.
    holes = [hole("A", 1000, 1000, 20000), hole("B", 19000, 1000, 10000)]
    rows = checks({"boreholes": holes, "investigation": {"footprint": footprint}})
    assert "19.5 m" in rows["deepBorings"]["required"]
    assert rows["deepBorings"]["status"] == "ok"  # 1 of 2 = 50 %
    # Piles on rock: 1.5 m core at each boring (Sec 3.4.5(v)).
    inv = {"foundation": "pile", "pileTipDepth": 15000, "onRock": True, "buildingSize": "small"}
    holes = [hole("A", 0, 0, 16500, rockCore=1500), hole("B", 9000, 0, 16000, rockCore=1000)]
    rows = checks({"boreholes": holes, "investigation": inv})
    assert rows["rockCore"]["status"] == "fail" and "B 1.0 m" in rows["rockCore"]["provided"]
    # Shafts: max(1.5 m, 3 x 1.2 m) = 3.6 m (Sec 3.4.5(vi)).
    inv = {**inv, "foundation": "shaft", "shaftDiameter": 1200}
    rows = checks({"boreholes": [hole("A", 0, 0, 20000, rockCore=3600)], "investigation": inv})
    assert rows["rockCore"]["status"] == "ok" and "3.60 m" in rows["rockCore"]["required"]


def test_geo_hazard_review_sec_3_21() -> None:
    holes = [hole("A", 0, 0)]
    assert checks({"boreholes": holes})["geoHazards"]["status"] == "warning"
    review = dict.fromkeys(table().geoHazards.items, "none")
    rows = checks({"boreholes": holes, "investigation": {"geoHazards": review}})
    assert rows["geoHazards"]["status"] == "ok"
    review["landslide"] = "significant"
    rows = checks({"boreholes": holes, "investigation": {"geoHazards": review}})
    assert rows["geoHazards"]["status"] == "fail"


def test_investigation_defaults_are_a_large_building_on_footings() -> None:
    inv = Investigation()
    assert (inv.buildingSize, inv.stratification, inv.foundation) == (
        "large",
        "average",
        "spread",
    )


# ─────────────────────────────── chemistry ───────────────────────────────


def test_corrosive_site_sec_3_10_1_29() -> None:
    # pH < 6 (was < 5.5), chloride >= 500 ppm, sulphate >= 2000 ppm.
    assert chemistry.corrosive_site(sample(chemistry={"pH": 5.9}))
    assert not chemistry.corrosive_site(sample(chemistry={"pH": 6.0}))
    assert chemistry.corrosive_site(sample(chemistry={"chlorideWater": 500}))
    assert not chemistry.corrosive_site(sample(chemistry={"chlorideWater": 499}))
    assert chemistry.corrosive_site(sample(chemistry={"sulphateSoil": 0.2}))  # 2000 ppm
    assert not chemistry.corrosive_site(sample(chemistry={"sulphateWater": 1999}))


def test_chloride_is_not_an_aci_class() -> None:
    flags = " ".join(chemistry.flags(sample(chemistry={"chlorideWater": 800})))
    assert "C2" not in flags and "w/c ≤ 0.4" in flags and "12 mm" in flags
    # Below the corrosive-site chloride, no brackish-water rule.
    assert not chemistry.flags(sample(chemistry={"chlorideWater": 200}))


def test_corrosivity_score_tables_6_3_6a_b() -> None:
    def rating(**chem):
        return chemistry.corrosivity(sample(chemistry=chem))

    # pH < 6: -2; resistivity 1000 or less: -4; sulphate 0.11 % = 1100 mg/kg: -3.
    r = rating(pH=5.5, resistivity=1000, sulphateSoil=0.11)
    assert r["score"] == -9 and r["rating"] == "corrosive"
    # Shared bounds of Table 6.3.6a take the more corrosive score: 5000 ohm-cm is -2.
    assert rating(resistivity=5000)["score"] == -2
    assert rating(resistivity=10000)["score"] == 0
    # Table 6.3.6b prints 0 in two bands: 0 is slightly corrosive; -10 highly corrosive.
    assert rating(pH=7)["rating"] == "slightlyCorrosive"
    assert rating(carbonate=6)["rating"] == "nonCorrosive"  # +2
    r = rating(resistivity=900, sulphide="exist", cinderCoke=False, soilComposition="clay")
    assert r["score"] == -10 and r["rating"] == "highlyCorrosive"
    assert "pH" in r["missing"]


def test_foundation_concrete_requirement() -> None:
    req = chemistry.concrete_requirement(
        [sample(chemistry={"sulphateWater": 2000}), sample(chemistry={"chlorideSoil": 0.06})]
    )
    # Severe sulphate w/c 0.45 and brackish chloride (600 ppm) 0.40: the smaller governs.
    assert req["maxWaterCement"] == 0.40 and req["sulphateClass"] == "Severe"
    assert req["noCalciumChloride"] and "CEM I" in req["cement"]
    assert req["extraCoverOption"] == {"maxWaterCement": 0.45, "extraCover": 12}
    assert chemistry.concrete_requirement([], below_water=True)["maxWaterCement"] == 0.50


# ─────────────────────────────── problem soils ───────────────────────────────


def test_organic_table_6_3_3_and_groups() -> None:
    def cls(oc):
        return special_soils.organic(sample(chemistry={"organicContent": oc}))["class"]

    assert cls(4) == "inorganic" and cls(5) == "organicMineral" and cls(20) == "organicMineral"
    assert cls(30) == "organic" and cls(75) == "peat"
    peat = special_soils.organic_group(sample(chemistry={"organicContent": 80}), None)
    assert peat["symbol"] == "PT"
    # LL oven-dried / LL < 0.75: OL below LL 50, OH above (Table 6.3.2).
    ol = sample(liquidLimit=40, plasticLimit=25, liquidLimitOvenDried=28)
    assert special_soils.organic_group(ol, "ML")["symbol"] == "OL"
    oh = sample(liquidLimit=60, plasticLimit=30, liquidLimitOvenDried=40)
    assert special_soils.organic_group(oh, "MH")["symbol"] == "OH"
    assert (
        special_soils.organic_group(sample(liquidLimit=40, liquidLimitOvenDried=35), "ML") is None
    )


def test_expansive_appendix_e() -> None:
    assert special_soils.expansive(sample(freeSwell=120))["degree"] == "high"  # IS 1948
    assert special_soils.expansive(sample(freeSwellIndex=20))["degree"] == "medium"
    assert special_soils.expansive(sample(linearShrinkage=15))["degree"] == "high"  # Hossain
    # Chen: 3 kg/cm2 is high.
    assert special_soils.expansive(sample(swellingPressure=3 * 98.0665))["degree"] == "high"
    low = special_soils.expansive(sample(liquidLimit=30, plasticLimit=22))
    assert low["degree"] == "low" and not low["expansive"]
    # USBR PI > 35 very high.
    assert special_soils.expansive(sample(liquidLimit=70, plasticLimit=30))["expansive"]


def test_collapsible_eqs_6_3_1_to_6_3_3() -> None:
    col = special_soils.collapsible(sample(collapse={"height": 20, "soakedHeight": 19.5}))
    assert col["collapsible"]  # imc 0.025 >= 0.02
    col = special_soils.collapsible(sample(collapse={"height": 20, "soakedHeight": 19.7}))
    assert not col["collapsible"]  # 0.015
    # ec = 0.85 eL + 0.15 eP with eL = 30 x 2.7/100 = 0.81, eP = 20 x 2.7/100 = 0.54: 0.7695.
    loose = sample(liquidLimit=30, plasticLimit=20, specificGravity=2.7, e0=0.9, moisture=10)
    col = special_soils.collapsible(loose)
    assert col["collapsible"] and "ec = 0.85 eL + 0.15 eP" in col["checks"][0]["text"]


def test_dispersive_sec_3_5_7() -> None:
    assert special_soils.dispersive(sample(pinhole="D1"))["class"] == "dispersive"
    assert special_soils.dispersive(sample(pinhole="ND2"))["class"] == "nonDispersive"
    # ESP 9 % with ESP + EMgP 18 %: dispersive; ESP 8 % moderate.
    d = special_soils.dispersive(
        sample(exchangeableSodium=0.9, exchangeableMagnesium=0.9, cationExchangeCapacity=10)
    )
    assert d["class"] == "dispersive"
    d = special_soils.dispersive(sample(exchangeableSodium=0.8, cationExchangeCapacity=10))
    assert d["class"] == "moderate"


def test_soft_clay_sec_3_5_8() -> None:
    assert special_soils.soft_clay("cohesive", 1, None)["consistency"] == "very soft"
    assert special_soils.soft_clay("cohesive", 4, None)["consistency"] == "soft"
    assert special_soils.soft_clay("cohesive", None, 30)["consistency"] == "soft"
    assert special_soils.soft_clay("cohesive", 8, 60) is None
    assert special_soils.soft_clay("granular", 2, None) is None


# ─────────────────────────────── the soil report ───────────────────────────────


def test_soil_report_carries_the_checks() -> None:
    report = {
        "boreholes": [
            hole("A", 0, 0, samples=[{"depth": 3000, "chemistry": {"sulphateWater": 2000}}]),
            hole("B", 15000, 0),
            hole("C", 0, 15000),
        ]
    }
    out = soil_report(json.dumps(report))
    assert out["investigation"]["covered"] and out["investigation"]["code"] == "BNBC 2020"
    assert out["chemistry"]["sulphateClass"] == "Severe"
    assert any(n.startswith("Concrete in the ground: w/c ≤ 0.45") for n in out["notes"])
    assert any("Site investigation (BNBC 2020)" in n for n in out["notes"])

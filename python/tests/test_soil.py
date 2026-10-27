"""The soil report (Part 1): the file format and the computations, against hand calculations
and, where they are installed, the independent implementations in geofound and liquepy."""

from __future__ import annotations

import itertools
import json
import math

import pytest
from pydantic import ValidationError

from saengine.library.export import json_schema
from saengine.library.settings import default_project_settings
from saengine.library.soil import SoilReport, is_placeholder
from saengine.soil import allowable_bearing, bearing, liquefaction, piles, site_class, soil_report
from saengine.soil import report as report_module
from saengine.soil.profile import GAMMA_W, PA, Profile, rod_factor
from saengine.soil.settlement import (
    influence_depth,
    settlement,
    steinbrenner_i1,
    strain_influence,
    stress_increase,
)


def report(*boreholes: dict, **design: object) -> SoilReport:
    return SoilReport.model_validate({"boreholes": list(boreholes), "design": design})


def profile(borehole: dict, **design: object) -> Profile:
    r = report(borehole, **design)
    return Profile(r, r.boreholes[0])


def sand(**extra: object) -> dict:
    return {"top": 0, "bottom": 20000, "soilType": "sand", **extra}


# ─────────────────────────────── file format ───────────────────────────────


def test_layers_must_be_contiguous_from_the_ground() -> None:
    def problems(layers: list[dict], **extra: object) -> str:
        with pytest.raises(ValidationError) as exc:
            report({"id": "BH-1", "layers": layers, **extra})
        return str(exc.value)

    clay = {"soilType": "clay"}
    assert "overlap" in problems(
        [{"top": 0, "bottom": 3000, **clay}, {"top": 2000, "bottom": 5000, **clay}]
    )
    assert "gap" in problems(
        [{"top": 0, "bottom": 3000, **clay}, {"top": 3500, "bottom": 5000, **clay}]
    )
    assert "not at 0" in problems([{"top": 500, "bottom": 3000, **clay}])
    assert "below the top" in problems([{"top": 0, "bottom": 0, **clay}])
    assert "termination depth" in problems([{"top": 0, "bottom": 5000, **clay}], depth=4000)
    assert "below the bottom" in problems(
        [{"top": 0, "bottom": 5000, **clay}], spt=[{"depth": 6000, "N": 5}]
    )
    assert "from the top down" in problems(
        [{"top": 0, "bottom": 5000, **clay}], spt=[{"depth": 3000, "N": 5}, {"depth": 1500, "N": 4}]
    )
    with pytest.raises(ValidationError, match="two boreholes"):
        report({"id": "BH-1"}, {"id": "BH-1"})
    with pytest.raises(ValidationError):
        report({"id": "BH-1", "layers": [{"top": 0, "bottom": 1000, "soilType": "loam"}]})


def test_defaults_placeholder_and_schema() -> None:
    r = SoilReport()
    assert r.design.hammerEnergy == 60 and r.design.factorOfSafety == 3
    assert r.design.allowableSettlement == 25 and r.design.liquefaction.magnitude == 7.5
    assert r.design.liquefaction.pga is None
    assert is_placeholder({"schema": 1, "part": "soil"})
    assert soil_report(json.dumps({"schema": 1, "part": "soil"}))["boreholes"] == []
    schema = json_schema(SoilReport, "SAEngine soil report")
    layer = schema["$defs"]["Layer"]["properties"]
    assert "[mm]" in layer["top"]["description"]
    assert layer["unitWeight"]["title"] == "Unit weight γ"
    assert schema["$defs"]["Layer"]["properties"]["soilType"]["enumDescriptions"][0] == "Clay"
    dumped = r.model_dump(mode="json", by_alias=True)
    assert dumped["schema"] == "saengine.soilReport/1"


def test_problems_name_the_borehole() -> None:
    text = json.dumps(
        {"schema": "saengine.soilReport/1", "boreholes": [{"id": "BH-7", "layers": [{"top": 0}]}]}
    )
    # One borehole's mistakes are warnings, the borehole left out (PR #26, S4); "problems" is
    # kept for a report that cannot be read at all.
    result = soil_report(text)
    warnings = result["warnings"]
    assert "problems" not in result and result["skipped"] == ["BH-7"]
    assert warnings and all(p.startswith("Soil report: BH-7.layers.1") for p in warnings)
    assert soil_report("{not json")["problems"][0].startswith("Soil report: not valid JSON")


# ─────────────────────────────── profile ───────────────────────────────


def test_stresses_with_the_water_table() -> None:
    p = profile(
        {
            "id": "BH-1",
            "waterTable": 2000,
            "layers": [
                {
                    "top": 0,
                    "bottom": 3000,
                    "soilType": "clay",
                    "unitWeight": 17,
                    "saturatedUnitWeight": 18,
                },
                {"top": 3000, "bottom": 10000, "soilType": "sand"},  # defaults 18 / 20
            ],
        }
    )
    assert p.sigma_v(5.0) == pytest.approx(17 * 2 + 18 * 1 + 20 * 2)
    assert p.u(5.0) == pytest.approx(GAMMA_W * 3)
    assert p.sigma_v_eff(5.0) == pytest.approx(92 - 3 * GAMMA_W)
    # Below the log the deepest layer continues.
    assert p.sigma_v(12.0) == pytest.approx(17 * 2 + 18 + 20 * 9)
    assert p.layers[1].sources["unitWeight"] == "default"


def test_spt_corrections() -> None:
    assert [rod_factor(d) for d in (2, 3.5, 5, 8, 12)] == [0.75, 0.80, 0.85, 0.95, 1.0]
    p = profile(
        {
            "id": "BH-1",
            "layers": [sand(unitWeight=18)],
            "spt": [{"depth": 1000, "N": 10}, {"depth": 12000, "N": 20, "energyRatio": 75}],
        },
        hammerEnergy=50,
        spt={"boreholeFactor": 1.05},
    )
    shallow, deep = p.spt
    assert shallow.n60 == pytest.approx(10 * 50 / 60 * 1.05 * 0.75)
    assert shallow.cn == 1.7  # (pa/18)^0.5 = 2.37, capped
    assert deep.n60 == pytest.approx(20 * 75 / 60 * 1.05)
    assert deep.cn == pytest.approx(math.sqrt(PA / (18 * 12)))
    assert deep.n160 == pytest.approx(deep.cn * deep.n60)


def test_layer_values_from_samples_and_correlations() -> None:
    p = profile(
        {
            "id": "BH-1",
            "layers": [
                {"top": 0, "bottom": 5000, "soilType": "clay"},
                {"top": 5000, "bottom": 10000, "soilType": "sand", "finesContent": 20},
            ],
            "spt": [{"depth": 3000, "N": 8}, {"depth": 7000, "N": 20}],
            "samples": [
                {
                    "depth": 2000,
                    "moisture": 30,
                    "liquidLimit": 40,
                    "plasticLimit": 20,
                    "unitWeight": 18.4,
                },
                {"depth": 4000, "moisture": 34, "liquidLimit": 44, "plasticLimit": 22},
            ],
        }
    )
    clay, sandy = p.layers
    assert clay.gamma == pytest.approx(18.4) and clay.sources["unitWeight"] == "samples (1)"
    assert clay.pi == pytest.approx(21.0) and clay.ll == pytest.approx(42.0)
    assert clay.cc == pytest.approx(0.009 * 32)
    assert clay.cr == pytest.approx(clay.cc / 5)
    assert clay.e0 == pytest.approx(0.32 * 2.70)
    assert clay.cu == pytest.approx(4.5 * clay.n60) and "Stroud" in clay.sources["cu"]
    assert clay.E == pytest.approx(500 * clay.cu / 1e3)
    assert sandy.phi == pytest.approx(math.sqrt(15.4 * sandy.n160) + 20)
    assert sandy.E == pytest.approx(5 * PA * sandy.n60 / 1e3)  # FC ≥ 15 %: α = 5


def test_silt_without_pi_or_cu_is_granular_with_a_note() -> None:
    hole = {
        "id": "BH-1",
        "layers": [
            {"top": 0, "bottom": 3000, "soilType": "silt"},
            {"top": 3000, "bottom": 6000, "soilType": "silt", "plasticityIndex": 12},
            {"top": 6000, "bottom": 9000, "soilType": "silt"},
            {"top": 9000, "bottom": 12000, "soilType": "silt"},
        ],
        # The third silt has a cu from a sample, the fourth a PI of 4 from LL - PL.
        "samples": [
            {"depth": 7000, "cu": 30},
            {"depth": 10000, "liquidLimit": 26, "plasticLimit": 22},
        ],
    }
    p = profile(hole)
    assert [layer.behaviour for layer in p.layers] == [
        "granular",
        "cohesive",
        "cohesive",
        "granular",
    ]
    note = (
        "layer 1 (silt): no PI or cu given — treated as non-plastic (granular): it counts in "
        "the liquefaction screening and the sand methods; give PI or cu if it is plastic"
    )
    assert p.notes == [note]
    # The note reaches the results' notes, which the Soil editor shows.
    result = soil_report(json.dumps({"boreholes": [hole]}), None)
    assert result["boreholes"][0]["notes"] == p.notes


# ─────────────────────────────── site class ───────────────────────────────


def _uniform(n: int, depth: float = 30000, **extra: object) -> dict:
    tests = [{"depth": d, "N": n} for d in range(1500, int(depth) + 1, 1500)]
    return {"id": "BH", "depth": depth, "layers": [sand(bottom=depth)], "spt": tests, **extra}


def test_site_class_limits() -> None:
    assert site_class.site_class(profile(_uniform(60)))["class"] == "SB"
    assert site_class.site_class(profile(_uniform(50)))["class"] == "SC"
    assert site_class.site_class(profile(_uniform(15)))["class"] == "SC"
    assert site_class.site_class(profile(_uniform(14)))["class"] == "SD"
    # N is capped at 100.
    assert site_class.site_class(profile(_uniform(300)))["N"] == 100


def test_site_class_harmonic_mean_and_extrapolation() -> None:
    # 10 m of N = 5 over N = 40 to 15 m: the last N is taken to 30 m.
    hole = {
        "id": "BH",
        "depth": 15000,
        "layers": [sand(bottom=15000)],
        "spt": [{"depth": 5000, "N": 5}, {"depth": 15000, "N": 40}],
    }
    result = site_class.site_class(profile(hole))
    # Ranges: 0-10 m N = 5, 10-30 m N = 40 (extrapolated).
    assert result["N"] == pytest.approx(30 / (10 / 5 + 20 / 40), abs=0.05)
    assert result["extrapolated"] and "30 m" in result["note"]
    assert result["class"] == "SD"  # N̄ = 12


def test_site_class_undrained_strength_and_rock() -> None:
    clay = {
        "id": "BH",
        "depth": 30000,
        "layers": [
            {"top": 0, "bottom": 8000, "soilType": "clay", "cu": 40},
            sand(top=8000, bottom=30000),
        ],
        "spt": [{"depth": d, "N": 30} for d in range(1500, 30001, 1500)],
    }
    result = site_class.site_class(profile(clay))
    assert result["byN"] == "SC" and result["bySu"] == "SD" and result["class"] == "SD"
    assert result["su"] == pytest.approx(40)
    rock = {
        "id": "BH",
        "layers": [sand(bottom=12000), {"top": 12000, "bottom": 15000, "soilType": "rock"}],
        "spt": [{"depth": d, "N": 20} for d in range(1500, 12001, 1500)],
    }
    result = site_class.site_class(profile(rock))
    # SE needs the Vs the SPT cannot give: the class stays SC (N̄ = 20) and SE is a flag.
    assert result["class"] == "SC" and [f["class"] for f in result["flags"]] == ["SE"]
    assert "rock-like material at 12.0 m" in result["flags"][0]["note"]
    sites = {"A": {"class": "SC"}, "B": {"class": "SD"}}
    assert site_class.governing(sites)["class"] == "SD"
    assert site_class.governing(sites)["governing"] == "B"


# ─────────────────────────────── bearing ───────────────────────────────


def test_bearing_factors() -> None:
    f = bearing.factors(30)
    assert f.nq == pytest.approx(18.401, abs=1e-3)
    assert f.nc == pytest.approx(30.140, abs=1e-3)
    assert f.ng == pytest.approx(22.402, abs=1e-3)
    assert bearing.factors(0).nc == 5.14


def test_bearing_against_geofound() -> None:
    gf = pytest.importorskip("geofound")
    sm = pytest.importorskip("sfsimodels")
    for phi, c, b, l_, df in [(30, 0, 2, 2, 1), (34, 5, 1.5, 3, 2), (28, 12, 3, 3, 1.5)]:
        soil = sm.Soil()
        soil.phi, soil.cohesion, soil.unit_dry_weight = phi, c * 1e3, 18e3
        fd = sm.RaftFoundation()
        fd.width, fd.length, fd.depth, fd.height = b, l_, df, 0.5
        reference = gf.capacity_vesic_1975(soil, fd) / 1e3
        assert bearing.ultimate(c, phi, 18 * df, 18, b, l_, df)["qu"] == pytest.approx(
            reference, rel=1e-6
        )


def test_bearing_water_table_and_net_value() -> None:
    hole = {
        "id": "BH",
        "waterTable": 1000,
        "layers": [sand(unitWeight=18, saturatedUnitWeight=20, phi=30)],
    }
    p = profile(hole)
    r = bearing.shear(p, 2.0, 2.0, 1.0, 3.0)
    # Water at the base: q = 18 kPa, γ' = 20 - 9.81 in the Nγ term.
    hand = bearing.ultimate(0, 30, 18, 20 - GAMMA_W, 2, 2, 1)["qu"]
    assert r["qu"] == pytest.approx(hand)
    assert r["qa"] == pytest.approx((hand - 18) / 3)
    # Water B/2 below the base: halfway between γ' and γ.
    p = profile({**hole, "waterTable": 2000})
    assert bearing.gamma_for_width(p, p.layers[0], 1.0, 2.0) == pytest.approx(
        (20 - GAMMA_W + 18) / 2
    )
    # Water at the ground, Df = 2 m: net of the total overburden is qu + u - σv = qu - σ'v.
    p = profile({**hole, "waterTable": 0})
    q_eff = 2 * (20 - GAMMA_W)
    hand = bearing.ultimate(0, 30, q_eff, 20 - GAMMA_W, 2, 2, 2)["qu"]
    r = bearing.shear(p, 2.0, 2.0, 2.0, 3.0)
    assert r["qa"] == pytest.approx((hand - q_eff) / 3)


def test_weaker_layer_below_governs_by_load_spread() -> None:
    hole = {
        "id": "BH",
        "layers": [
            {"top": 0, "bottom": 2000, "soilType": "sand", "phi": 34},
            {"top": 2000, "bottom": 10000, "soilType": "clay", "cu": 30},
        ],
    }
    p = profile(hole)
    r = bearing.shear(p, 2.0, 2.0, 1.0, 3.0)
    assert r["mode"] == "layered" and r["layer"] == 1 and r["method"] == "2:1 load spread"
    # By hand: a 3 m × 3 m equivalent footing on the clay's top (H = 1 m), undrained, no depth
    # factor: qb - q2 = cu 5.14 (1 + 0.2 B/L), spread over (3 × 3)/(2 × 2).
    q1 = p.sigma_v_eff(1.0)
    net = 30 * 5.14 * (1 + 1 / 5.14) * 9 / 4
    assert r["qu"] == pytest.approx(q1 + net)
    assert r["qa"] == pytest.approx(net / 3)


def test_clay_over_softer_clay_by_brown_and_meyerhof() -> None:
    hole = {
        "id": "BH",
        "layers": [
            {"top": 0, "bottom": 2000, "soilType": "clay", "cu": 60},
            {"top": 2000, "bottom": 10000, "soilType": "clay", "cu": 15},
        ],
    }
    p = profile(hole)
    r = bearing.shear(p, 2.0, 2.0, 1.0, 3.0)
    assert r["mode"] == "layered" and r["method"] == "Brown & Meyerhof 1969"
    # Square, H/B = 0.5: Nc = 3 × 0.5 + 6.05 × 0.25 = 3.0125 of 6.05 for one clay.
    assert bearing.two_clay_nc(60, 15, 2, 2, 1) == pytest.approx(3.0125)
    own = 60 * 5.14 * (1 + 1 / 5.14) * (1 + 0.4 * 0.5)
    assert r["qa"] == pytest.approx(own * 3.0125 / 6.05 / 3)
    # Deep enough (3 H/B + 6.05 c2/c1 ≥ 6.05): the stiff clay's own value.
    assert bearing.shear(p, 0.6, 0.6, 1.0, 3.0)["layer"] == 0


def test_soft_clay_below_a_crust_lowers_qa_smoothly() -> None:
    # S3: a 2.5 m crust (cu 60) over very soft clay (cu 12). The soft clay was missed while it
    # lay deeper than B and then counted as if the footing stood on it (90 -> 19 kPa).
    hole = {
        "id": "BH",
        "waterTable": 1500,
        "layers": [
            {"top": 0, "bottom": 2500, "soilType": "clay", "cu": 60, "unitWeight": 18},
            {"top": 2500, "bottom": 30000, "soilType": "clay", "cu": 12, "unitWeight": 16},
        ],
    }
    p = profile(hole)
    widths = [0.3 + 0.1 * i for i in range(58)]
    values = [bearing.shear(p, b, b, 1.0, 3.0)["qa"] for b in widths]
    steps = [a / b for a, b in itertools.pairwise(values)]
    assert max(steps) < 1.15 and min(steps) > 0.97  # no jump either way
    assert values[-1] < values[0] / 3
    # Never below the soft clay's own value at its top.
    clay = bearing.ultimate(12, 0, p.sigma_v_eff(2.5), 16, 6.0, 6.0, 0.0)["qu"]
    assert values[-1] > (clay - p.sigma_v_eff(2.5)) / 3


def test_strong_layer_below_does_not_raise_qa() -> None:
    hole = {
        "id": "BH",
        "layers": [
            {"top": 0, "bottom": 2000, "soilType": "clay", "cu": 30},
            {"top": 2000, "bottom": 10000, "soilType": "sand", "phi": 38},
        ],
    }
    r = bearing.shear(profile(hole), 2.0, 2.0, 1.0, 3.0)
    assert r["mode"] == "undrained" and r["layer"] == 0


def test_unknown_layer_under_the_base_withholds_qa() -> None:
    hole = {
        "id": "BH",
        "layers": [
            {"top": 0, "bottom": 1000, "soilType": "fill"},
            {"top": 1000, "bottom": 2500, "soilType": "fill", "unitWeight": 16},
            {"top": 2500, "bottom": 20000, "soilType": "sand", "unitWeight": 19},
        ],
        "spt": [{"depth": d * 1000, "N": 30} for d in (3, 4.5, 6, 7.5, 9)],
    }
    r = bearing.allowable(profile(hole), 2.0, 2.0, 1.0)
    assert r["qa"] is None and r["qa_shear"] is None
    assert any("layer 2 (fill): no strength" in n and "no qa" in n for n in r["notes"])
    # Founded below the unknown fill: the sand governs.
    assert bearing.allowable(profile(hole), 2.0, 2.0, 2.5)["qa"] is not None
    # The unknown layer counts within 2B below the base (BNBC Sec 3.4.2.3(a)), not beyond.
    deep = {
        "id": "BH",
        "layers": [
            {"top": 0, "bottom": 3000, "soilType": "sand", "phi": 32},
            {"top": 3000, "bottom": 20000, "soilType": "fill", "unitWeight": 16},
        ],
    }
    assert bearing.shear(profile(deep), 0.9, 0.9, 1.0, 3.0)["qa"] is not None  # H 2.0 > 1.8
    assert bearing.shear(profile(deep), 1.1, 1.1, 1.0, 3.0)["qa"] is None  # H 2.0 < 2.2


def test_meyerhof_bowles() -> None:
    assert bearing.meyerhof_bowles(20, 1.0, 1.0, 25) == pytest.approx(19.16 * 20 * 1.33)
    kd = 1 + 0.33 * 1.5 / 3
    assert bearing.meyerhof_bowles(20, 3.0, 1.5, 25) == pytest.approx(
        11.98 * 20 * (3.305 / 3) ** 2 * kd
    )
    assert bearing.meyerhof_bowles(20, 3.0, 1.5, 40) == pytest.approx(
        11.98 * 20 * (3.305 / 3) ** 2 * kd * 40 / 25
    )


def test_settlement_controlled_pressure_settles_the_allowable_amount() -> None:
    hole = {
        "id": "BH",
        "waterTable": 1000,
        "layers": [
            {"top": 0, "bottom": 1000, "soilType": "sand", "phi": 30},
            {
                "top": 1000,
                "bottom": 12000,
                "soilType": "clay",
                "cu": 40,
                "Cc": 0.3,
                "e0": 1.0,
                "OCR": 2,
            },
        ],
        "spt": [{"depth": 3000, "N": 6}],
    }
    p = profile(hole)
    r = bearing.allowable(p, 2.0, 2.0, 1.0)
    assert r["qa"] == r["qa_settlement"] < r["qa_shear"]
    assert settlement(p, 2.0, 2.0, 1.0, r["qa_settlement"])["total"] == pytest.approx(25, abs=0.2)
    rows = bearing.table(p)
    assert len(rows) == 5 * 4 and {row["B"] for row in rows} == {1000, 1500, 2000, 3000, 4000}


def test_settlement_check_sees_clay_stressed_by_the_adopted_pressure() -> None:
    # Dense sand over soft clay at 8 m: under 100 kPa the stressed zone (5.5 m below the base)
    # misses the clay; under the adopted pressure (the Meyerhof-Bowles value, far below the
    # shear value) it reaches it, and the computed settlement governs.
    hole = {
        "id": "BH",
        "layers": [
            {"top": 0, "bottom": 8000, "soilType": "sand", "unitWeight": 18},
            {
                "top": 8000,
                "bottom": 20000,
                "soilType": "clay",
                "unitWeight": 17,
                "cu": 20,
                "Cc": 0.6,
                "e0": 1.5,
            },
        ],
        "spt": [{"depth": d * 1000, "N": 35} for d in (1.5, 3, 4.5, 6, 7.5)]
        + [{"depth": d * 1000, "N": 4} for d in (9, 12, 15, 18)],
    }
    p = profile(hole)
    r = bearing.allowable(p, 3.0, 3.0, 1.5)
    assert r["governs"] == "settlement" and r["settlement"].startswith("computed settlement")
    assert r["qa"] < 0.5 * bearing.meyerhof_bowles(35, 3.0, 1.5, 25)
    assert settlement(p, 3.0, 3.0, 1.5, r["qa"])["total"] <= 25.2


def soft_sand_over_clay(clay_top: int, **clay: object) -> Profile:
    """Loose sand (N = 8, γ = 18) over a clay from ``clay_top`` [mm], no water table."""
    return profile(
        {
            "id": "BH",
            "layers": [
                {"top": 0, "bottom": clay_top, "soilType": "sand", "unitWeight": 18},
                {"top": clay_top, "bottom": 25000, "soilType": "clay", "unitWeight": 18, **clay},
            ],
            "spt": [{"depth": d, "N": 8} for d in (1500, 3000, 4500)],
        }
    )


def test_clay_is_checked_at_the_adopted_pressure_not_the_shear_value() -> None:
    # B = 2 m, Df = 1.5 m. N60 = 8 x 0.75 = 6 at 1.5 m (CR 0.75 below 3 m of rod), 8 x 0.80 at
    # 3 m and 8 x 0.85 at 4.5 m: mean 6.4, so Meyerhof-Bowles gives
    # 11.98 x 6.4 x (2.305/2)^2 x (1 + 0.33 x 1.5/2) = 127.0 kPa, well below the shear value.
    # Under 127 kPa the stressed zone ends 4.8 m below the base (6.3 m deep); under the shear
    # value it reaches 9 m below it.
    clay = {"cu": 25, "Cc": 0.5, "e0": 1.3}
    mb = 11.98 * 6.4 * (2.305 / 2) ** 2 * (1 + 0.33 * 1.5 / 2)
    outside = soft_sand_over_clay(6600, **clay)
    r = bearing.allowable(outside, 2.0, 2.0, 1.5)
    assert r["qa_shear"] > 3 * mb
    # Clay top 6.6 m (5.1 m below the base): Δσ = 127 x 4/(2 + 5.1)² = 10.1 kPa < 10 % of
    # σ'v0 = 0.1 x 18 x 6.6 = 11.9 kPa: outside the zone, so no computed settlement ...
    assert stress_increase(r["qa"], 2.0, 2.0, 5.1) < 0.1 * outside.sigma_v_eff(6.6)
    assert r["qa"] == pytest.approx(mb, abs=0.1) and r["settlement"].startswith("Meyerhof-Bowles")
    # ... though the zone under the shear value (the old trial pressure) would reach it.
    assert influence_depth(outside, 2.0, 2.0, 1.5, r["qa_shear"]) > 5.1
    # Clay top 6.0 m (4.5 m below the base): Δσ = 127 x 4/6.5² = 12.0 kPa > 0.1 x 18 x 6 = 10.8:
    # inside; its settlement at 127 kPa exceeds 25 mm, so the pressure drops until it is 25 mm
    # with the clay still in the zone.
    inside = soft_sand_over_clay(6000, **clay)
    assert stress_increase(mb, 2.0, 2.0, 4.5) > 0.1 * inside.sigma_v_eff(6.0)
    assert settlement(inside, 2.0, 2.0, 1.5, mb)["total"] > 25
    r = bearing.allowable(inside, 2.0, 2.0, 1.5)
    assert r["governs"] == "settlement" and r["qa"] < mb - 1
    assert r["settlement"].startswith("computed settlement (immediate + consolidation) = 25 mm")
    s = settlement(inside, 2.0, 2.0, 1.5, r["qa"])
    assert s["total"] == pytest.approx(25, abs=0.2) and s["consolidation"] > 0
    assert influence_depth(inside, 2.0, 2.0, 1.5, r["qa"]) > 4.5


def test_reduced_pressure_rechecks_the_zone_and_names_only_what_settles() -> None:
    # Clay top 6.2 m, very compressible: at 127 kPa it is in the zone and settles too much; the
    # bisection lands just below the pressure whose zone reaches it, where only the sand settles.
    p = soft_sand_over_clay(6200, cu=25, Cc=1.2, e0=1.3)
    r = bearing.allowable(p, 2.0, 2.0, 1.5)
    assert r["governs"] == "settlement" and r["settlement"].startswith("computed settlement: above")
    # The clay is 4.7 m below the base: the zone at the adopted pressure stops above it.
    assert influence_depth(p, 2.0, 2.0, 1.5, r["qa"]) <= 4.7 + 1e-9
    assert settlement(p, 2.0, 2.0, 1.5, r["qa"])["consolidation"] == 0
    # A clay with a modulus but no Cc, e0: only the immediate settlement, and the text says so.
    r = bearing.allowable(soft_sand_over_clay(6000, E=2), 2.0, 2.0, 1.5)
    assert r["settlement"].startswith("computed settlement (immediate) = 25 mm")
    assert "consolidation" not in r["settlement"]
    # A stiff clay in the zone that settles less than 25 mm at the adopted pressure does not
    # govern: the pressure where it would settle 25 mm lies above the adopted one.
    stiff = soft_sand_over_clay(6000, E=50)
    r = bearing.allowable(stiff, 2.0, 2.0, 1.5)
    assert r["settlement"].startswith("Meyerhof-Bowles") and r["qa"] == pytest.approx(127.0, 0.1)
    t = bearing.settlement_controlled(stiff, 2.0, 2.0, 1.5, 25, r["qa_shear"])
    assert t["method"].startswith("Meyerhof-Bowles")


# ─────────────────────────────── settlement ───────────────────────────────


def test_schmertmann_strip_by_hand() -> None:
    p = profile({"id": "BH", "layers": [sand(unitWeight=18, E=30)]})
    r = settlement(p, 1.5, 15.0, 1.0, 120.0, years=10)
    # L/B = 10: Iz 0.2 at the base, peak at B, 0 at 4B.
    sp = 18 * (1.0 + 1.5)
    izp = 0.5 + 0.1 * math.sqrt(120 / sp)
    area = (0.2 + izp) / 2 * 1.5 + izp * 4.5 / 2
    c1, c2 = 1 - 0.5 * 18 / 120, 1 + 0.2 * math.log10(10 / 0.1)
    assert r["immediate"] == pytest.approx(c1 * c2 * 120 * area / 30_000 * 1e3, rel=1e-3)
    d = strain_influence(1.5, 15.0, 120.0, sp)
    assert d["zp"] == pytest.approx(1.5) and d["zmax"] == pytest.approx(6.0)


def test_steinbrenner_half_space_centre() -> None:
    # Centre of a flexible square on a deep layer: s = 1.122 q B (1 - ν²)/E.
    assert 4 * 0.5 * steinbrenner_i1(1.0, 1e6) == pytest.approx(1.122, abs=1e-3)
    assert steinbrenner_i1(1.0, 0.0) == 0


def test_consolidation_of_a_thin_clay_layer_by_hand() -> None:
    hole = {
        "id": "BH",
        "waterTable": 0,
        "layers": [
            {"top": 0, "bottom": 2000, "soilType": "sand", "saturatedUnitWeight": 20, "E": 1e6},
            {
                "top": 2000,
                "bottom": 2250,
                "soilType": "clay",
                "saturatedUnitWeight": 18,
                "cu": 30,
                "Cc": 0.3,
                "e0": 1.0,
                "E": 1e6,
            },
            {"top": 2250, "bottom": 30000, "soilType": "rock"},
        ],
    }
    r = settlement(profile(hole), 2.0, 2.0, 1.0, 100.0)
    z = 2.125
    s0 = 20 * 2 + 18 * 0.125 - GAMMA_W * z
    ds = 100 * 4 / ((2 + 1.125) ** 2)
    hand = 0.3 * 0.25 / 2.0 * math.log10((s0 + ds) / s0) * 1e3
    assert r["consolidation"] == pytest.approx(hand, rel=1e-6)
    clay = next(row for row in r["layers"] if row["soilType"] == "clay")
    assert clay["consolidation"] == pytest.approx(hand, abs=0.01)


# ─────────────────────────────── liquefaction ───────────────────────────────


def test_liquefaction_against_liquepy() -> None:
    bi = pytest.importorskip("liquepy.trigger.boulanger_and_idriss_2014")
    for n in (5.0, 12.0, 20.0, 30.0):
        assert liquefaction.crr_75(n) == pytest.approx(float(bi.calc_crr_m7p5_from_n1_60cs(n)))
        assert liquefaction.k_sigma(150, n) == pytest.approx(
            float(bi.calc_k_sigma_w_n1_60cs(150, n, pa=PA))
        )
    for z in (2.0, 8.0, 15.0):
        assert liquefaction.rd(z, 7.0) == pytest.approx(float(bi.calc_rd(z, 7.0)))


def test_liquefaction_screening_and_lpi() -> None:
    hole = {
        "id": "BH",
        "waterTable": 2000,
        "layers": [
            {"top": 0, "bottom": 4000, "soilType": "clay", "cu": 30},
            {"top": 4000, "bottom": 20000, "soilType": "sand", "finesContent": 5},
        ],
        "spt": [
            {"depth": 1500, "N": 4},
            {"depth": 3000, "N": 4},
            {"depth": 6000, "N": 6},
            {"depth": 9000, "N": 40},
        ],
    }
    p = profile(hole)
    result = liquefaction.screen(p, 0.3, "amax = 0.3 g")
    points = result["points"]
    assert [x["screened"] for x in points] == [False, False, True, True]
    assert points[0]["reason"] == "above the water table"
    assert "clay" in points[1]["reason"]
    loose, dense = points[2], points[3]
    assert loose["liquefiable"] and not dense["liquefiable"]
    # The loose test stands for 4.5 to 7.5 m: midway to the tests above and below.
    hand = (1 - loose["fs"]) * (10 * 3 - 0.25 * (7.5**2 - 4.5**2))
    assert result["lpi"] == pytest.approx(hand, rel=0.01)
    assert result["layers"][0]["soilType"] == "sand"
    # S10: the range is the failing test's share (4.5 to 7.5 m), not the whole 4-20 m layer.
    assert (result["layers"][0]["top"], result["layers"][0]["bottom"]) == (4500, 7500)


def test_liquefiable_range_stops_at_the_screening_depth() -> None:
    hole = {
        "id": "BH",
        "waterTable": 1000,
        "layers": [{"top": 0, "bottom": 30000, "soilType": "sand", "finesContent": 5}],
        "spt": [{"depth": d, "N": 5} for d in range(1500, 30001, 1500)],
    }
    result = liquefaction.screen(profile(hole), 0.3, "amax = 0.3 g")
    (only,) = result["layers"]
    assert only["top"] == 1000 and only["bottom"] == 20000


def test_mean_n_fines_correction_and_iteration() -> None:
    assert liquefaction.delta_n_fines(0.0) == pytest.approx(0.0, abs=1e-6)
    assert liquefaction.delta_n_fines(35.0) == pytest.approx(5.5, abs=0.1)
    n, cn, dn = liquefaction.n160cs(10, 50, 15)
    m = 0.784 - 0.0768 * math.sqrt(n)
    assert cn == pytest.approx(min(1.7, (PA / 50) ** m), rel=1e-6)
    assert n == pytest.approx(cn * 10 + dn, rel=1e-6)
    assert liquefaction.msf(7.5, 20) == pytest.approx(1.0, abs=1e-3)


def test_amax_from_the_settings() -> None:
    assert liquefaction.amax_from(0.25, 0.2, ["SD"])[0] == 0.25
    amax, note = liquefaction.amax_from(None, 0.28, ["SC", "SD"])
    assert amax == pytest.approx(2 / 3 * 0.28 * 1.35) and "SD" in note
    settings = default_project_settings().model_dump_json(by_alias=True)
    text = json.dumps({"schema": "saengine.soilReport/1", "boreholes": [_uniform(20)]})
    assert soil_report(text, settings)["amax"] == pytest.approx(2 / 3 * 0.20 * 1.35)


# ─────────────────────────────── piles, ks ───────────────────────────────


def test_pile_parameters() -> None:
    hole = {
        "id": "BH",
        "waterTable": 0,
        "layers": [
            {"top": 0, "bottom": 10000, "soilType": "clay", "cu": 50, "saturatedUnitWeight": 18},
            {"top": 10000, "bottom": 30000, "soilType": "sand", "saturatedUnitWeight": 20},
        ],
        "spt": [{"depth": 20000, "N": 30}],
    }
    clay, sandy = piles.pile_parameters(profile(hole))
    assert clay["fs"] == pytest.approx(0.55 * 50) and clay["qb"] == pytest.approx(
        (8.0 + 1.0 * 2 / 48) * 50, rel=1e-3
    )
    z = 20.0
    se = 18 * 10 + 20 * 10 - GAMMA_W * 20
    beta = 1.5 - 0.245 * math.sqrt(z)
    assert sandy["fs"] == pytest.approx(beta * se, rel=1e-3)
    assert sandy["qb"] == pytest.approx(57.5 * 30)
    # O'Neill & Reese: no side resistance in clay over the top 1.5 m and the bottom 1 D.
    assert clay["sideExclusion"] == {"top": 1500, "bottomDiameters": 1.0, "bellDiameters": 1.0}
    assert "top 1.5 m" in clay["note"] and "sideExclusion" not in sandy
    driven = piles.pile_parameters(profile(hole, pile={"type": "driven"}))
    psi = 50 / (5 * (18 - GAMMA_W))
    assert driven[0]["fs"] == pytest.approx(min(1, 0.5 * psi**-0.25) * 50, rel=1e-3)
    assert driven[1]["fs"] == pytest.approx(60) and driven[1]["qb"] == pytest.approx(
        400 * 30, rel=0.02
    )


def test_subgrade_modulus_is_the_secant_value() -> None:
    p = profile(
        {
            "id": "BH",
            "layers": [sand(unitWeight=18, E=20, phi=32)],
            "spt": [{"depth": 3000, "N": 15}],
        }
    )
    result = piles.subgrade_modulus(p, 150.0)
    s = settlement(p, 2.0, 2.0, 1.5, 150.0)["total"]
    assert result["value"] == pytest.approx(150 / (s / 1e3), rel=1e-3)
    assert result["bowles"] == 40 * 3 * 150


# ─────────────────────────────── API ───────────────────────────────


def _two_boreholes() -> str:
    def hole(id_: str, x: float, n: int) -> dict:
        return {
            "id": id_,
            "x": x,
            "y": 0,
            "waterTable": 3000,
            "layers": [sand(bottom=15000, phi=32)],
            "spt": [{"depth": d, "N": n} for d in range(1500, 15001, 1500)],
        }

    return json.dumps(
        {
            "schema": "saengine.soilReport/1",
            "groundLevel": 0,
            "boreholes": [hole("BH-1", 0, 25), hole("BH-2", 8000, 12), hole("BH-3", 40000, 6)],
        }
    )


def test_soil_report_shape() -> None:
    result = soil_report(_two_boreholes(), None)
    assert set(result) >= {"boreholes", "siteClass", "notes", "amax"}
    first = result["boreholes"][0]
    assert set(first) >= {"id", "siteClass", "profile", "liquefaction", "bearing", "ks", "pile"}
    assert set(first["siteClass"]) >= {"class", "N", "su", "depth", "extrapolated", "note"}
    assert set(first["profile"][0]) >= {"depth", "sigma_v", "sigma_v_eff", "N60", "N160"}
    assert set(first["liquefaction"]) >= {"points", "lpi", "note"}
    assert set(first["bearing"]["table"][0]) == {
        "B",
        "Df",
        "qa_shear",
        "qa_settlement",
        "qa",
        "governs",
    }
    assert set(first["pile"][0]) >= {"top", "bottom", "fs", "qb"}
    assert result["siteClass"]["class"] == "SD" and result["siteClass"]["governing"] == "BH-3"
    json.dumps(result)  # JSON-ready


def test_one_bad_borehole_leaves_the_others_computed(monkeypatch: pytest.MonkeyPatch) -> None:
    # S4: an invalid borehole, a repeated id or a failing computation used to blank them all.
    data = json.loads(_two_boreholes())
    data["boreholes"][1]["layers"] = [sand(top=0, bottom=5000), sand(top=4000, bottom=15000)]
    data["boreholes"].append({**data["boreholes"][0]})
    result = soil_report(json.dumps(data), None)
    assert [b["id"] for b in result["boreholes"]] == ["BH-1", "BH-3"]
    assert result["skipped"] == ["BH-2", "BH-1"]
    assert any(
        p.startswith("Soil report: BH-2") and "(4 m is above 5 m)" in p for p in result["warnings"]
    )
    assert "Soil report: two boreholes are called BH-1" in result["warnings"]

    real = report_module._borehole

    def failing(profile: Profile, *args: object) -> dict:
        if profile.id == "BH-3":
            raise ZeroDivisionError("float division by zero")
        return real(profile, *args)

    monkeypatch.setattr(report_module, "_borehole", failing)
    result = soil_report(_two_boreholes(), None)
    assert [b["id"] for b in result["boreholes"]] == ["BH-1", "BH-2"]
    assert result["skipped"] == ["BH-3"]
    assert result["warnings"] == [
        "BH-3: its results could not be computed (ZeroDivisionError: float division by zero)"
    ]
    assert result["details"][0].startswith("BH-3:\nTraceback")


def test_allowable_bearing_uses_the_lowest_nearby_borehole() -> None:
    text = _two_boreholes()
    near_both = allowable_bearing(text, None, 4000, 0, -1500, 2000, 2000)
    assert near_both["borehole"] == "BH-2" and "within 10 m" in near_both["note"]
    p = Profile(
        SoilReport.model_validate_json(text), SoilReport.model_validate_json(text).boreholes[1]
    )
    assert near_both["qa_kpa"] == bearing.allowable(p, 2.0, 2.0, 1.5)["qa"]
    far = allowable_bearing(text, None, 60000, 0, -1500, 2000, 2000)
    assert far["borehole"] == "BH-3" and "nearest" in far["note"]
    empty = allowable_bearing(
        json.dumps({"schema": 1, "part": "soil"}), None, 0, 0, -1000, 1000, 1000
    )
    assert empty["qa_kpa"] is None
    # qa is net of the total overburden at Df below the borehole's ground: both are given.
    assert near_both["groundLevel"] == 0 and near_both["Df"] == 1500
    assert near_both["overburden"] == pytest.approx(p.sigma_v(1.5), abs=0.01)


def test_a_nearby_borehole_without_data_withholds_qa() -> None:
    # BH-1 (sand, N = 15) gives a value; BH-2, 5 m away, has 3 m of fill with no strength data
    # under the base. The footing between them must not take BH-1's value alone.
    sand_hole = {
        "id": "BH-1",
        "x": 0,
        "y": 0,
        "layers": [{"top": 0, "bottom": 15000, "soilType": "sand", "unitWeight": 18}],
        "spt": [{"depth": d, "N": 15} for d in range(1500, 15001, 1500)],
    }
    fill_hole = {
        "id": "BH-2",
        "x": 5000,
        "y": 0,
        "layers": [
            {"top": 0, "bottom": 3000, "soilType": "fill"},
            {"top": 3000, "bottom": 15000, "soilType": "sand", "unitWeight": 18},
        ],
        "spt": [{"depth": d, "N": 15} for d in range(4500, 15001, 1500)],
    }
    text = json.dumps({"schema": "saengine.soilReport/1", "boreholes": [sand_hole, fill_hole]})
    alone = json.dumps({"schema": "saengine.soilReport/1", "boreholes": [sand_hole]})
    assert allowable_bearing(alone, None, 2500, 0, -1500, 2000, 2000)["qa_kpa"] is not None
    found = allowable_bearing(text, None, 2500, 0, -1500, 2000, 2000)
    assert found["qa_kpa"] is None and found["borehole"] == "BH-2"
    assert found["note"].startswith("No allowable pressure: BH-2 (within 10 m) gives none: ")


def test_no_qa_without_the_strength_or_the_compressibility() -> None:
    no_strength = profile({"id": "BH", "layers": [{"top": 0, "bottom": 9000, "soilType": "clay"}]})
    r = bearing.allowable(no_strength, 2.0, 2.0, 1.0)
    assert r["qa"] is None and r["qa_shear"] is None
    assert any("no modulus, Cc or e0" in n for n in r["notes"])
    # A strength but nothing to compute the clay's settlement from: no qa either.
    hole = {"id": "BH", "layers": [{"top": 0, "bottom": 9000, "soilType": "clay", "cu": 60}]}
    p = profile(hole)
    p.layers[0].E = None
    r = bearing.allowable(p, 2.0, 2.0, 1.0)
    assert r["qa_shear"] is not None and r["qa"] is None

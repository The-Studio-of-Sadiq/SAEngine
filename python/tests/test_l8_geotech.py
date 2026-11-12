"""Alpha 9 L8: slope stability by limit equilibrium (known factors of safety), the 2D
geotechnical FE, and the AGS4 / DIGGS exchange of the soil report (round trips)."""

from __future__ import annotations

import json
import math
from types import SimpleNamespace as NS

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.library.soil import SoilReport
from saengine.library.substructure import Slope, SlopeNail
from saengine.soil import ags, diggs
from saengine.substructure import slope_stability as ss

# ─────────────────────────────── helpers ───────────────────────────────


def _ctx(**kw: object) -> NS:
    """The parts of the substructure context a slope reads (no settings: no seismic PGA)."""
    return NS(settings=None, soil_text=None, ground_level=0.0, substructure=NS(slopes=[]), **kw)


def _homogeneous(surface: list[list[float]], soil: dict, base: float | None = None, **kw) -> Slope:
    data = {
        "id": "SL1",
        "surface": surface,
        "soils": [{"id": "A", **soil}],
        "strata": [{"soil": "A"}],
        "search": {"grid": 12, "radii": 10, "minDepth": 500},
        **kw,
    }
    if base is not None:
        data["base"] = base
    return Slope.model_validate(data)


def _lowest(result: dict, method: str, case: int = 0) -> float:
    rows = result["slope"]["cases"][case]["results"]
    return next(r["fs"] for r in rows if r["method"] == method)


# ─────────────────────────────── pack values ───────────────────────────────


def test_pack_values_pinned_with_their_clauses():
    bnbc = registry.load("bnbc2020").table("slopeStability")
    # SAEngine practice where BNBC 2020 Part 6 Sec 3.21 / 3.14 give no slope method.
    assert bnbc.verification == "factorOfSafety"
    assert (bnbc.required.permanent, bnbc.required.temporary, bnbc.required.seismic) == (
        1.5,
        1.3,
        1.1,
    )
    assert bnbc.seismic.khFactor == 0.5 and bnbc.seismic.kvRatio == 0.0  # Hynes-Griffin 1984
    assert (bnbc.reinforcement.tendonFactor, bnbc.reinforcement.bondFactor) == (1.8, 2.0)
    assert bnbc.methods == ["bishop", "janbu", "spencer", "morgensternPrice"]
    en = registry.load("eurocodes").table("slopeStability")
    # EN 1997-1 Annex A Table A.14 (γR;e) and EN 1998-5 4.1.3.3 (FV = ± 0.5 FH).
    assert en.verification == "partialFactors"
    assert en.partialFactors.resistances == {"R1": 1.0, "R2": 1.1, "R3": 1.0}
    assert (en.seismic.khFactor, en.seismic.kvRatio, en.seismic.materials) == (0.5, 0.5, "M2")
    us = registry.load("aci318-asce7-22").table("slopeStability")
    assert us.verification == "factorOfSafety" and us.required.permanent == 1.5  # EM 1110-2-1902


# ─────────────────────────────── limit equilibrium ───────────────────────────────


def test_acads_homogeneous_slope_bishop():
    """ACADS (Giam and Donald 1989) problem 1(a): a 2:1 slope 10 m high, c' 3 kPa, φ' 19.6°,
    γ 20 kN/m³, no water; the referee factor of safety 1.00 (Bishop about 0.99)."""
    slope = _homogeneous(
        [[20000, 25000], [30000, 25000], [50000, 35000], [70000, 35000]],
        {"unitWeight": 20, "c": 3, "phi": 19.6},
        base=20000,
    )
    result = ss.design_slope(_ctx(), slope)
    assert result["slope"]["direction"] == "left"  # the higher end is on the right
    bishop = _lowest(result, "bishop")
    assert bishop == pytest.approx(0.99, abs=0.04)
    for method in ("spencer", "morgensternPrice"):
        assert _lowest(result, method) == pytest.approx(bishop, rel=0.03)
    # Janbu simplified (corrected) is close and on the low side.
    assert _lowest(result, "janbu") == pytest.approx(bishop, rel=0.08)
    # Required 1.5 (permanent, SAEngine practice in the default pack): it fails.
    assert not result["ok"]
    assert result["utilisation"] == pytest.approx(1.5 / bishop, rel=0.03)


def test_vertical_cut_in_clay_taylor():
    """φ = 0: the critical toe circle of a vertical cut has Ns = γ H F / cu = 3.83 (Fellenius,
    Taylor 1937)."""
    h, cu, gamma = 5.0, 20.0, 18.0
    slope = _homogeneous(
        [[0, 5000], [10000, 5000], [10001, 0], [30000, 0]],
        {"unitWeight": gamma, "cu": cu, "strength": "undrained"},
        base=-10000,
    )
    result = ss.design_slope(_ctx(), slope)
    expected = 3.83 * cu / (gamma * h)
    assert _lowest(result, "bishop") == pytest.approx(expected, rel=0.04)


def test_nails_raise_the_factor_of_safety():
    slope = _homogeneous(
        [[0, 10000], [10000, 10000], [20000, 0], [35000, 0]],
        {"unitWeight": 19, "c": 5, "phi": 28},
        base=-8000,
    )
    plain = _lowest(ss.design_slope(_ctx(), slope), "bishop")
    nail = {"inclination": 15, "length": 12000, "spacing": 1500, "capacity": 250, "bond": 100}
    nails = [
        SlopeNail.model_validate(
            {"id": f"N{i}", "x": 10000 + 2000 * i, "level": 10000 - 2000 * i, **nail}
        )
        for i in range(1, 5)
    ]
    nailed = slope.model_copy(update={"nails": nails})
    assert _lowest(ss.design_slope(_ctx(), nailed), "bishop") > plain


def test_water_and_ru_lower_the_factor():
    dry = _homogeneous(
        [[0, 10000], [10000, 10000], [25000, 0], [40000, 0]],
        {"unitWeight": 19, "saturatedUnitWeight": 20, "c": 10, "phi": 30},
        base=-8000,
    )
    wet = dry.model_copy(update={"water": [[0, 8000], [25000, 0], [40000, 0]]})
    ru = dry.model_copy(update={"ru": 0.3})
    f_dry = _lowest(ss.design_slope(_ctx(), dry), "bishop")
    assert _lowest(ss.design_slope(_ctx(), wet), "bishop") < f_dry
    assert _lowest(ss.design_slope(_ctx(), ru), "bishop") < f_dry


def test_seismic_case_with_the_given_kh():
    slope = _homogeneous(
        [[0, 10000], [10000, 10000], [25000, 0], [40000, 0]],
        {"unitWeight": 19, "c": 10, "phi": 30},
        base=-8000,
        seismic=True,
        kh=0.1,
    )
    result = ss.design_slope(_ctx(), slope)
    names = [c["name"] for c in result["slope"]["cases"]]
    assert names[0] == "Static" and names[1].startswith("Seismic")
    assert result["slope"]["cases"][1]["required"] == 1.1
    assert _lowest(result, "bishop", 1) < _lowest(result, "bishop", 0)


def test_eurocode_partial_factors_da1():
    slope = _homogeneous(
        [[0, 10000], [10000, 10000], [25000, 0], [40000, 0]],
        {"unitWeight": 19, "c": 10, "phi": 30},
        base=-8000,
    )
    with code_context.using(registry.load("eurocodes")):
        result = ss.design_slope(_ctx(), slope)
    cases = result["slope"]["cases"]
    assert [c["name"][:6] for c in cases] == ["DA1 C1", "DA1 C2"]
    c1, c2 = _lowest(result, "bishop", 0), _lowest(result, "bishop", 1)
    # C2 divides tan φ' and c' by 1.25: its factor is lower, about F(C1) / 1.25.
    assert c2 == pytest.approx(c1 / 1.25, rel=0.06)
    assert cases[1]["required"] == 1.0


def test_non_circular_search_is_not_above_the_circle():
    slope = _homogeneous(
        [[0, 10000], [10000, 10000], [25000, 0], [40000, 0]],
        {"unitWeight": 19, "c": 10, "phi": 30},
        base=-8000,
        search={"surface": "nonCircular", "grid": 8, "radii": 6},
    )
    search = slope.search.model_copy(update={"surface": "circular"})
    circular = slope.model_copy(update={"search": search})
    f_nc = _lowest(ss.design_slope(_ctx(), slope), "janbu")
    f_c = _lowest(ss.design_slope(_ctx(), circular), "janbu")
    assert f_nc <= f_c * 1.02  # optimised from the critical circle, and the best circles kept


def test_section_regions_of_a_layered_section():
    slope = Slope.model_validate(
        {
            "id": "SL2",
            "surface": [[0, 10000], [10000, 10000], [20000, 2000], [40000, 2000]],
            "soils": [
                {"id": "S", "unitWeight": 18, "c": 2, "phi": 32},
                {"id": "C", "unitWeight": 19, "cu": 40, "strength": "undrained"},
            ],
            "strata": [{"soil": "S"}, {"soil": "C", "points": [[0, 4000], [40000, 4000]]}],
            "base": -5000,
        }
    )
    sec = ss.build_section(_ctx(), slope)
    assert not isinstance(sec, str)
    from saengine.substructure.geotech_fe import regions

    found = regions(sec)
    # The sand above 4 m (where the ground is above it) and the clay below the ground / line.
    assert {k for k, _ in found} == {0, 1}
    area = sum(
        0.5 * abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(p, p[1:] + p[:1], strict=True)))
        for _, p in found
    )
    # The section's area: from the ground down to the base.
    xs = [0, 10, 20, 40]
    zs = [10, 10, 2, 2]
    expected = sum((xs[i + 1] - xs[i]) * ((zs[i] + zs[i + 1]) / 2 + 5) for i in range(3))
    assert area == pytest.approx(expected, rel=1e-6)


@pytest.mark.slow
def test_fe_strength_reduction_close_to_limit_equilibrium():
    """The 2D FE of the ACADS slope: its strength reduction factor within 15 % of Bishop's."""
    slope = _homogeneous(
        [[20000, 25000], [30000, 25000], [50000, 35000], [70000, 35000]],
        {"unitWeight": 20, "c": 3, "phi": 19.6, "E": 20},
        base=20000,
        fe={"run": True, "meshSize": 1000, "steps": 10},
    )
    result = ss.design_slope(_ctx(), slope)
    fe = result["slope"]["fe"]
    assert not fe.get("error"), fe
    assert fe["fs"] == pytest.approx(_lowest(result, "bishop"), rel=0.15)
    assert fe["mesh"]["elements"] and fe["maxDisplacement"] > 0
    assert any(c["name"] == "2D FE strength reduction" and c["flag"] for c in result["checks"])


# ─────────────────────────────── AGS4 and DIGGS ───────────────────────────────


def _report() -> SoilReport:
    return SoilReport.model_validate(
        {
            "report": {"title": "Test site", "consultant": "Lab", "reportNumber": "R-1"},
            "groundLevel": 1500,
            "boreholes": [
                {
                    "id": "BH-1",
                    "x": 1000,
                    "y": 2000,
                    "waterTable": 1500,
                    "depth": 12000,
                    "date": "2026-01-15",
                    "method": "Wash boring",
                    "layers": [
                        {
                            "top": 0,
                            "bottom": 3000,
                            "description": "Soft grey CLAY",
                            "soilType": "clay",
                            "uscs": "CL",
                        },
                        {
                            "top": 3000,
                            "bottom": 12000,
                            "description": "Medium dense SAND",
                            "soilType": "sand",
                        },
                    ],
                    "spt": [
                        {"depth": 1500, "seat": 2, "N1": 3, "N2": 4, "sampleNumber": "D-1"},
                        {"depth": 4500, "N": 18, "energyRatio": 70},
                        {"depth": 9000, "seat": 25, "refusal": {"blows": 50, "penetration": 100}},
                    ],
                    "samples": [
                        {
                            "number": "UD-1",
                            "depth": 2000,
                            "depthTo": 2450,
                            "type": "UD",
                            "moisture": 32.5,
                            "unitWeight": 18.2,
                            "liquidLimit": 45,
                            "plasticLimit": 22,
                            "cu": 25,
                            "finesContent": 88,
                            "grainSize": {
                                "sieves": [
                                    {"size": 2.0, "passing": 100},
                                    {"size": 0.075, "passing": 88},
                                ]
                            },
                        },
                        {"number": "D-2", "depth": 6000, "type": "disturbed", "c": 0, "phi": 32},
                    ],
                },
                {
                    "id": "BH-2",
                    "x": 15000,
                    "y": 2000,
                    "layers": [
                        {
                            "top": 0,
                            "bottom": 5000,
                            "description": "Firm brown silty CLAY",
                            "soilType": "clay",
                        },
                    ],
                    "spt": [{"depth": 2000, "N": 7}],
                },
            ],
        }
    )


def _same(a: SoilReport, b_holes: list[dict]) -> None:
    b = SoilReport.model_validate({"boreholes": b_holes})
    assert [h.id for h in a.boreholes] == [h.id for h in b.boreholes]
    for x, y in zip(a.boreholes, b.boreholes, strict=True):
        assert (x.x, x.y) == pytest.approx((y.x, y.y), abs=1)
        assert a.ground_level(x) == pytest.approx(y.groundLevel, abs=1)
        assert x.waterTable == (None if y.waterTable is None else pytest.approx(y.waterTable))
        assert [(lay.top, lay.bottom, lay.soilType) for lay in x.layers] == [
            (lay.top, lay.bottom, lay.soilType) for lay in y.layers
        ]
        assert [r.depth for r in x.spt] == [r.depth for r in y.spt]
        assert [r.blows for r in x.spt] == [r.blows for r in y.spt]
        assert [r.seat for r in x.spt] == [r.seat for r in y.spt]
        assert [s.depth for s in x.samples] == [s.depth for s in y.samples]


def test_ags4_round_trip():
    report = _report()
    text, _notes = ags.to_text(report)
    assert text.startswith('"GROUP","PROJ"')
    holes, problems, notes = ags.read_text(text, "test.ags")
    assert not problems, problems
    _same(report, holes)
    one = SoilReport.model_validate({"boreholes": holes}).boreholes[0]
    assert one.layers[0].uscs == "CL"
    assert one.method == "Wash boring"
    first, _, refusal = one.spt
    assert (first.N1, first.N2, first.sampleNumber) == (3, 4, "D-1")
    assert refusal.refusal.blows == 50 and refusal.refusal.penetration == 100
    ud = one.samples[0]
    assert (ud.number, ud.type, ud.depthTo) == ("UD-1", "UD", 2450)
    assert ud.moisture == 32.5 and ud.liquidLimit == 45 and ud.plasticLimit == 22
    assert ud.unitWeight == pytest.approx(18.2, abs=0.01)
    assert ud.cu == pytest.approx(25) and ud.finesContent == 88
    assert [p.size for p in ud.grainSize.sieves] == [2.0, 0.075]
    assert one.samples[1].phi == 32
    # Every group written is read: nothing is reported as not imported.
    assert not [n for n in notes if "not imported" in n]


def test_ags4_import_of_a_consultant_file_reports_the_unmapped():
    text = "\r\n".join(CONSULTANT_AGS)
    holes, problems, notes = ags.read_text(text, "site.ags")
    assert not problems, problems
    bh1, bh2 = holes
    assert (bh1["x"], bh1["y"]) == (0.0, 0.0) and (bh2["x"], bh2["y"]) == (20000.0, 10000.0)
    assert bh1["groundLevel"] == 12500 and bh1["depth"] == 15000
    assert [layer["soilType"] for layer in bh1["layers"]] == ["fill", "clay"]
    assert bh2["layers"][0]["soilType"] == "sand"
    assert bh1["spt"][0] == {"depth": 2000.0, "seat": 3, "N1": 6, "N2": 8, "N": 14}
    assert bh2["spt"][0]["refusal"] == {"blows": 50, "penetration": 150.0}
    joined = " ".join(notes)
    assert "group MOND (1 rows)" in joined
    assert "LOCA_CLNT" in joined and "GEOL_FORM" in joined


#: A consultant's AGS4 file: national grid positions, made ground, the 75 mm SPT increments, a
#: refusal, and a monitoring group the import does not read.
CONSULTANT_AGS = (
    '"GROUP","LOCA"',
    '"HEADING","LOCA_ID","LOCA_TYPE","LOCA_NATE","LOCA_NATN","LOCA_GL","LOCA_FDEP","LOCA_CLNT"',
    '"UNIT","","","m","m","m","m",""',
    '"TYPE","ID","PA","2DP","2DP","2DP","2DP","X"',
    '"DATA","BH1","CP","530000.00","180000.00","12.50","15.00","Client"',
    '"DATA","BH2","CP","530020.00","180010.00","12.80","10.00",""',
    "",
    '"GROUP","GEOL"',
    '"HEADING","LOCA_ID","GEOL_TOP","GEOL_BASE","GEOL_DESC","GEOL_FORM"',
    '"UNIT","","m","m","",""',
    '"TYPE","ID","2DP","2DP","X","X"',
    '"DATA","BH1","0.00","1.20","MADE GROUND: brown sandy gravel with brick","MG"',
    '"DATA","BH1","1.20","15.00","Firm to stiff brown slightly sandy CLAY","LC"',
    '"DATA","BH2","0.00","10.00","Medium dense grey fine to coarse SAND","RTD"',
    "",
    '"GROUP","ISPT"',
    '"HEADING","LOCA_ID","ISPT_TOP","ISPT_INC1","ISPT_INC2","ISPT_INC3","ISPT_INC4","ISPT_INC5","ISPT_INC6","ISPT_NVAL","ISPT_NPEN","ISPT_MAIN"',
    '"UNIT","","m","","","","","","","","mm",""',
    '"TYPE","ID","2DP","0DP","0DP","0DP","0DP","0DP","0DP","0DP","0DP","0DP"',
    '"DATA","BH1","2.00","1","2","3","3","4","4","14","300","14"',
    '"DATA","BH2","3.00","10","15","25","25","","","","150","50"',
    "",
    '"GROUP","MOND"',
    '"HEADING","LOCA_ID","MOND_DTIM","MOND_RDNG"',
    '"UNIT","","yyyy-mm-ddThh:mm","m"',
    '"TYPE","ID","DT","2DP"',
    '"DATA","BH1","2026-01-20T10:00","3.20"',
)


def test_diggs_round_trip():
    report = _report()
    text, _notes = diggs.to_text(report)
    assert "<Diggs" in text and "DrivenPenetrationTest" in text
    holes, problems, _ = diggs.read_text(text, "test.xml")
    assert not problems, problems
    _same(report, holes)
    one = SoilReport.model_validate({"boreholes": holes}).boreholes[0]
    assert one.layers[0].uscs == "CL"
    assert (one.spt[0].N1, one.spt[0].N2) == (3, 4)
    assert one.spt[2].refusal.blows == 50 and one.spt[2].refusal.penetration == 100


def test_import_and_export_by_extension(tmp_path):
    from saengine.soil import export_soil, import_soil
    from saengine.soil.report import dumps

    report = _report()
    for suffix in (".ags", ".xml"):
        path = tmp_path / f"site{suffix}"
        written = export_soil(str(path), dumps(report))
        assert written.get("path") == str(path), written
        found = import_soil(str(path), dumps(SoilReport()))
        assert "text" in found, found
        assert [b["id"] for b in json.loads(found["text"])["boreholes"]] == ["BH-1", "BH-2"]
    assert "problems" in export_soil(str(tmp_path / "site.txt"), dumps(report))


def test_slope_model_validation():
    with pytest.raises(ValueError, match="unknown soils"):
        Slope.model_validate({"id": "S", "soils": [], "strata": [{"soil": "X"}]})
    with pytest.raises(ValueError, match="left to right"):
        Slope.model_validate({"id": "S", "surface": [[10, 0], [0, 0]]})
    assert math.isclose(Slope.model_validate({"id": "S"}).search.minDepth, 1000)

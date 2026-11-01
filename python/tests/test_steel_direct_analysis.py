"""B17: the direct analysis method for steel frames, with the values of the bnbc2020 pack's
``steelStability`` table (BNBC 2020 Part 6 Sec 10.3.2.2 and Sec 10.14, part 2 pp. 52-53 and
187-189)."""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from saengine.codes.tables import builtin_table
from saengine.design.steel import stability as st
from saengine.design.steel.lengths import MemberLengths
from saengine.design.steel.members import Stations, Steel, SteelOptions, check_member
from saengine.design.steel.properties import shape_properties
from saengine.fem import notional_loads as nl
from saengine.fem import second_order as so
from saengine.library.objects import IShapeProfile
from saengine.library.steel_sections import find

STEEL = Steel(345.0, 450.0, 200_000.0, "A992")


def _settings(method="directAnalysis", tau="additive", notional="allCombinations"):
    return SimpleNamespace(
        analysis=SimpleNamespace(
            notionalLoads=method,
            directAnalysisTau=tau,
            directAnalysisNotional=notional,
            stiffness="gross",
        )
    )


# ── the pack ──


def test_pack_values():
    t = builtin_table("steelStability")
    da = t.directAnalysis
    assert da.effectiveLengthFactor == 1.0  # Sec 10.14.1
    assert da.notionalCoefficient == 0.002  # Sec 10.14.3(2)
    assert da.additiveNotionalCoefficient == 0.001  # Sec 10.14.3(3)
    assert da.gravityOnlyDriftRatioMax == 1.5  # Sec 10.14.3(2)
    assert da.flexuralStiffnessFactor == 0.8  # Eq 6.10.263
    assert da.axialStiffnessFactor == 0.8  # Eq 6.10.264
    assert (da.tauLimit, da.tauFactor) == (0.5, 4.0)  # Eq 6.10.263
    assert da.pSmallDeltaLimit == 0.15  # Eq 6.10.262
    assert da.asdAnalysisFactor == 1.6  # Sec 10.14.3(1)
    assert (t.alpha.lrfd, t.alpha.asd) == (1.0, 1.6)
    assert t.limits.directAnalysisRequiredAbove == 1.5  # Sec 10.3.2.2
    assert t.limits.secondOrderUnitKMax == 1.1  # Sec 10.3.2.2.1(d)
    assert t.limits.firstOrderAxialMax == 0.5  # Eq 6.10.9
    # moved from fem/notional_loads.py constants, checked against the text
    assert t.notional.secondOrder == 0.002  # Sec 10.3.2.2.1(c)
    assert (t.notional.firstOrderDriftFactor, t.notional.firstOrderMinimum) == (2.1, 0.0042)


def test_notional_coefficients():
    assert nl.coefficient("directAnalysis", tau="additive") == pytest.approx(0.003)
    assert nl.coefficient("directAnalysis", tau="checked") == pytest.approx(0.002)
    assert nl.coefficient("secondOrder") == pytest.approx(0.002)
    assert nl.coefficient("firstOrder", 0.003) == pytest.approx(0.0063)
    assert nl.coefficient("none") == 0.0


def test_tau_b():
    assert st.tau_b(0.5) == 1.0
    assert st.tau_b(0.7) == pytest.approx(4 * 0.7 * 0.3)  # Eq 6.10.263
    assert st.tau_b(0.0) == 1.0


# ── the analysis model ──


def _project():
    return {
        "nodes": [
            {"id": 1, "coords": [0.0, 0.0, 0.0]},
            {"id": 2, "coords": [0.0, 0.0, 3.0]},
            {"id": 3, "coords": [6.0, 0.0, 3.0]},
        ],
        "sections": [
            {
                "id": 1,
                "name": "W",
                "type": "ElasticSection",
                "E": 200e9,
                "A": 0.01,
                "Iz": 1e-4,
                "Iy": 5e-5,
                "G": 77e9,
                "J": 1e-6,
            },
            {
                "id": 2,
                "name": "RC",
                "type": "ElasticSection",
                "E": 25e9,
                "A": 0.09,
                "Iz": 6.75e-4,
                "Iy": 6.75e-4,
                "G": 10e9,
                "J": 1e-3,
            },
        ],
        "elements": [
            {"id": 1, "type": "ElasticBeamColumn", "nodes": [1, 2], "section_id": 1},
            {"id": 2, "type": "ElasticBeamColumn", "nodes": [2, 3], "section_id": 2},
        ],
        "time_series": [{"id": 1, "name": "", "type": "Linear", "factor": 1.0}],
        "load_patterns": [
            {
                "id": 1,
                "name": "D",
                "type": "Plain",
                "time_series_id": 1,
                "nodal_loads": [{"node_id": 2, "forces": [0, 0, -100e3, 0, 0, 0]}],
                "element_loads": [],
            },
        ],
        "analyses": [
            {"id": 1, "name": "D: Dead", "type": "Static", "pattern_ids": [1]},
            {"id": 2, "name": "MODAL: modes", "type": "Modal", "pattern_ids": []},
        ],
    }


def test_options_force_p_delta_and_references():
    opts = so.options_from_settings(_settings())
    assert opts.directAnalysis and opts.secondOrder == "pDelta" and opts.firstOrderReference
    plain = so.options_from_settings(_settings("secondOrder"))
    assert not plain.directAnalysis


def test_reduced_steel_stiffness(tmp_path):
    p = _project()
    result = so.apply_second_order(
        p, so.options_from_settings(_settings()), concrete_sections={2}, steel_sections={1}
    )
    sections = {s["id"]: s for s in result.project["sections"]}
    assert sections[1]["A"] == pytest.approx(0.8 * 0.01)  # EA* = 0.8 EA, Eq 6.10.264
    assert sections[1]["Iz"] == pytest.approx(0.8 * 1e-4)  # EI* = 0.8 τb EI, τb = 1
    assert sections[1]["Iy"] == pytest.approx(0.8 * 5e-5)
    assert sections[1]["J"] == pytest.approx(1e-6)  # torsion unchanged
    assert sections[2]["A"] == pytest.approx(0.09)  # concrete untouched
    assert so.is_direct_analysis(result.project) and not so.is_direct_analysis(p)
    modal = next(a for a in result.project["analyses"] if a["type"] == "Modal")
    assert [s["A"] for s in modal["section_overrides"]] == [pytest.approx(0.01)]  # nominal
    assert p["sections"][0]["A"] == 0.01  # input unchanged


def test_notional_cases_direct_analysis():
    p = _project()
    notes = nl.add_notional_cases(p, "directAnalysis", tau="additive")
    nxd = next(q for q in p["load_patterns"] if q["name"] == "NXD")
    assert sum(load["forces"][0] for load in nxd["nodal_loads"]) == pytest.approx(0.003 * 100e3)
    assert notes and "0.003 Yi" in notes[0]


# ── the member checks ──


def _column(p: float, length: float = 4.0, n: int = 5) -> tuple[list[Stations], MemberLengths]:
    s = np.linspace(0, length, n)
    z = np.zeros(n)
    stations = [Stations("C", s, np.full(n, p), np.full(n, 50e6), z, z, z, [""] * n)]
    return stations, MemberLengths.simple(length, k={"x": 2.0, "y": 2.0})


def _shape():
    return shape_properties(IShapeProfile.model_validate(find("HEB 300").profile()))


def _names(checks):
    return {c["name"]: c for c in checks}


def test_direct_analysis_takes_k_one_and_reduced_b1():
    shape = _shape()
    stations, lengths = _column(1000e3)
    stab = st.stability_of(_settings(), True, {"cases": [{"case": "EX", "maxRatio": 1.2}]})
    assert stab.direct and stab.unit_k == 1.0
    da = check_member(shape, STEEL, stations, lengths, "column", SteelOptions(stability=stab))
    plain = check_member(shape, STEEL, stations, lengths, "column", SteelOptions())
    c_da, c_plain = _names(da)["Compression: buckling"], _names(plain)["Compression: buckling"]
    assert c_da["capacity"] > c_plain["capacity"]  # K = 1 (Sec 10.14.1) instead of the K = 2 set
    assert (
        "K = 1 / 1 (direct analysis method)" in _names(da)["Slenderness KL/r (compression)"]["note"]
    )
    assert not any(c["name"].startswith("K = 1 by first-order") for c in da)
    pdelta = next(c for c in da if c["name"].startswith("P-δ neglected"))
    pel = math.pi**2 * 200_000.0 * min(shape.ix, shape.iy) / 4000.0**2  # Eq 6.10.262
    assert pdelta["capacity"] == pytest.approx(0.15 * pel / 1e3, rel=1e-3)
    assert pdelta["demand"] == pytest.approx(1000.0)
    # the gravity-only option is not chosen: no drift-ratio check on the member
    assert not any("Δ2nd/Δ1st" in c["name"] for c in da)


def test_tau_checked_column():
    shape = _shape()
    py = 345.0 * shape.area
    stations, lengths = _column(0.7 * py)
    stab = st.stability_of(_settings(tau="checked"), True, None)
    checks = check_member(shape, STEEL, stations, lengths, "column", SteelOptions(stability=stab))
    tau = next(c for c in checks if c["name"].startswith("τb = 1"))
    assert tau["utilisation"] == pytest.approx(0.7 / 0.5, rel=1e-3)  # αPr ≤ 0.5 Py
    assert not tau["ok"] and "τb = 0.84" in tau["note"]


def test_reduced_flexural_stiffness_for_b1():
    stab = st.stability_of(_settings(tau="checked"), True, None)
    assert stab.flexural_stiffness(0.4, 1.0) == pytest.approx(0.8)
    assert stab.flexural_stiffness(0.7, 1.0) == pytest.approx(0.8 * 0.84)
    additive = st.stability_of(_settings(), True, None)
    assert additive.flexural_stiffness(0.7, 1.0) == pytest.approx(0.8)


def test_drift_ratio_trigger():
    # other methods: Δ2nd/Δ1st > 1.5 requires the direct analysis method (Sec 10.3.2.2)
    stab = st.stability_of(
        _settings("secondOrder"), False, {"cases": [{"case": "EY", "maxRatio": 1.6}]}
    )
    assert stab.method == "secondOrder" and stab.drift_limit == 1.5
    shape = _shape()
    stations, lengths = _column(500e3)
    checks = check_member(shape, STEEL, stations, lengths, "column", SteelOptions(stability=stab))
    trigger = next(c for c in checks if c["name"].startswith("Direct analysis not required"))
    assert not trigger["ok"] and trigger["utilisation"] == pytest.approx(1.6 / 1.5, rel=1e-3)
    k1 = next(c for c in checks if c["name"].startswith("K = 1 by second-order"))
    assert k1["flag"] and k1["capacity"] == pytest.approx(1.1)  # Sec 10.3.2.2.1(d)
    # the direct analysis method with the notional loads in the gravity-only combinations
    gravity = st.stability_of(
        _settings(notional="gravityOnly"), True, {"cases": [{"case": "EX", "maxRatio": 1.4}]}
    )
    assert gravity.drift_limit == 1.5  # Sec 10.14.3(2)
    checks = check_member(
        shape, STEEL, stations, lengths, "column", SteelOptions(stability=gravity)
    )
    assert next(c for c in checks if "gravity-only" in c["name"])["ok"]


def test_design_follows_the_model():
    stab = st.stability_of(_settings("directAnalysis"), False, None)
    assert stab.method == "secondOrder" and stab.notes  # model not derived for it
    stab = st.stability_of(_settings("none"), True, None)
    assert stab.direct and stab.notes


def test_method_lines_cite_the_pack():
    stab = st.stability_of(_settings(), True, {"cases": [{"case": "EX", "maxRatio": 1.3}]})
    line = st.method_lines(stab)[0]
    assert builtin_table("steelStability").sources["method"] in line
    assert "1.30" in line

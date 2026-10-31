"""Deep beams and transfer girders (BNBC 2020 Part 6 Sec 6.4.6), corbels (Sec 6.4.7), the
shared strut-and-tie capacities (Sec 6.2.3.2, ACI 318-19 Chapter 23) and the diaphragm force
(ASCE 7-05 Sec 12.10.1.1, Sec 2.5.5.6.3)."""

from __future__ import annotations

import math

import pytest

from saengine.design import stm
from saengine.design.corbels import CorbelDemand, corbel_checks
from saengine.design.deep_beams import DeepSpan, SpanDemands, deep_span_checks, is_deep, web_steel
from saengine.design.diaphragms import _tributary, diaphragm_forces
from saengine.library.modifiers import Corbel


def _by_name(checks: list[dict]) -> dict[str, dict]:
    return {c["name"]: c for c in checks}


# ── strut-and-tie (ACI 318-19 Chapter 23, φ of BNBC Sec 6.2.3.2) ──


def test_stm_capacities():
    assert stm.phi() == pytest.approx(0.75)
    # Tie: φ As fy (23.7.2.1).
    assert stm.tie_capacity(1000, 420) == pytest.approx(0.75 * 1000 * 420)
    # Nodes: φ 0.85 βn f'c Anz, βn 1.0 / 0.8 / 0.6 (Table 23.9.2).
    assert stm.node_capacity(30, 1e5, "CCC") == pytest.approx(0.75 * 0.85 * 1.0 * 30 * 1e5)
    assert stm.node_capacity(30, 1e5, "CCT") == pytest.approx(0.75 * 0.85 * 0.8 * 30 * 1e5)
    assert stm.node_capacity(30, 1e5, "CTT") == pytest.approx(0.75 * 0.85 * 0.6 * 30 * 1e5)
    # Struts: βs 1.0 prism, 0.75 bottle with web steel, 0.6 without (Table 23.4.3).
    assert stm.strut_capacity(30, 1e5, "prism") == pytest.approx(0.75 * 0.85 * 30 * 1e5)
    assert stm.strut_capacity(30, 1e5, "bottle", True) == pytest.approx(0.75 * 0.85 * 0.75 * 3e6)
    assert stm.strut_capacity(30, 1e5, "bottle", False) == pytest.approx(0.75 * 0.85 * 0.6 * 3e6)
    assert stm.min_angle() == pytest.approx(25.0)  # 23.2.7
    # ws = lb sin θ + wt cos θ (Fig. R23.2.6b).
    theta = math.radians(45)
    assert stm.strut_width(400, 200, theta) == pytest.approx(600 * math.sqrt(0.5))


# ── deep beams (Sec 6.4.6) ──


def _span(**kw) -> DeepSpan:
    values = {
        "clear": 3000.0,
        "depth": 1200.0,
        "width": 400.0,
        "d": 1100.0,
        "fc": 30.0,
        "fy": 420.0,
        "bearings": (500.0, 500.0),
        "tie_area": 4000.0,
        "tie_height": 200.0,
        "vertical": (2 * 113.1, 200.0),
        "horizontal": (2 * 113.1, 200.0),
    }
    values.update(kw)
    return DeepSpan(**values)


def test_deep_by_span_ratio():
    # ln <= 4 h (Sec 6.4.6.1 (a)).
    assert is_deep(_span(clear=4800.0))[0]
    assert not is_deep(_span(clear=4801.0))[0]


def test_deep_by_load_near_support():
    # A concentrated load within 2 h of the face (Sec 6.4.6.1 (b)): h = 600, 2 h = 1200.
    span = _span(clear=6000.0, depth=600.0, d=540.0, loads=[(1400.0, 400.0)])
    assert is_deep(span)[0]  # its face 1200 mm from the support's
    span = _span(clear=6000.0, depth=600.0, d=540.0, loads=[(1500.0, 400.0)])
    assert not is_deep(span)[0]


def test_web_steel_ratios_and_spacing():
    web = web_steel(_span())
    # Av / (bw s) = 226.2 / (400 · 200); least 0.0025 vertical, 0.0015 horizontal (6.4.6.3-4).
    assert web["vertical"]["ratio"] == pytest.approx(226.2 / 80000)
    assert web["vertical"]["required"] == pytest.approx(0.0025)
    assert web["horizontal"]["required"] == pytest.approx(0.0015)
    # s at most d/5 and 300 mm: d = 1100 → 220 mm.
    assert web["vertical"]["allowed"] == pytest.approx(220.0)


def test_deep_span_checks():
    span = _span(loads=[(1500.0, 500.0)])
    demands = SpanDemands(
        reactions=((1.2e6, "c"), (1.2e6, "c")),
        moment=(1.5e9, "c"),
        shear=(1.2e6, "c"),
        loads=[(2.4e6, "c")],
    )
    checks = _by_name(deep_span_checks(span, demands))
    # Vn limit φ 0.83 √f'c bw d (6.4.6.2).
    limit = checks["Deep beam shear limit"]
    assert limit["capacity"] == pytest.approx(0.75 * 0.83 * math.sqrt(30) * 400 * 1100 / 1e3, 0.01)
    # Tie: a = 250 + 1500 = 1750 mm, z = 0.9 d = 990 mm, T = R a / z.
    tie = checks["Tie (bottom bars, strut-and-tie)"]
    assert tie["demand"] == pytest.approx(1.2e6 * 1750 / 990 / 1e3, 0.01)
    assert tie["capacity"] == pytest.approx(0.75 * 4000 * 420 / 1e3, 0.01)
    # θ = atan(990 / 1750) = 29.5° >= 25°.
    angle = checks["Strut angle at the left support"]
    assert angle["capacity"] == pytest.approx(math.degrees(math.atan2(990, 1750)), 0.01)
    assert angle["ok"]
    # C-C-T node at the support: φ 0.85 · 0.8 f'c lb bw.
    node = checks["Node at the left support (C-C-T)"]
    assert node["capacity"] == pytest.approx(0.75 * 0.85 * 0.8 * 30 * 500 * 400 / 1e3, 0.01)
    # C-C-C node under the landing column.
    landing = checks["Node under the landing column at 1500 mm (C-C-C)"]
    assert landing["capacity"] == pytest.approx(0.75 * 0.85 * 30 * 500 * 400 / 1e3, 0.01)


# ── corbels (Sec 6.4.7) ──


def _corbel(**kw) -> Corbel:
    values = {
        "width": 400,
        "depth": 500,
        "edgeDepth": 300,
        "projection": 350,
        "mainBars": {"count": 4, "dia": 20},
        "ties": {"count": 3, "dia": 12},
        "bearing": 150,
    }
    values.update(kw)
    return Corbel(**values)


def test_corbel_steel():
    checks = _by_name(corbel_checks(_corbel(), 30, 420, CorbelDemand(400e3, "c")))
    d = 500 - 40 - 10
    # Vn,max = min(0.2 f'c, 3.3 + 0.08 f'c, 11) bw d = 5.7 bw d at f'c 30 (6.4.7.3.2).
    assert checks["Corbel: shear limit"]["capacity"] == pytest.approx(
        0.75 * 5.7 * 400 * d / 1e3, 0.01
    )
    # As >= (2/3) Avf + An: Avf = Vu / (φ fy 1.4), An = 0.2 Vu / (φ fy) (6.4.7.3.4-5).
    avf = 400e3 / (0.75 * 420 * 1.4)
    an = 0.2 * 400e3 / (0.75 * 420)
    main = checks["Corbel: main bars As"]
    assert main["demand"] >= 2 / 3 * avf + an - 1
    assert main["demand"] >= 0.04 * 30 / 420 * 400 * d - 1  # 6.4.7.5
    # Ah >= 0.5 (As - An) (6.4.7.4).
    ties = checks["Corbel: closed ties Ah"]
    assert ties["demand"] == pytest.approx(0.5 * (4 * math.pi * 100 - an), 0.01)
    # av / d at most 1 (6.4.7.1): av = 175 mm.
    assert checks["Corbel: shear span av / d"]["demand"] == pytest.approx(175 / d, 0.01)


def test_corbel_too_long_fails():
    checks = _by_name(corbel_checks(_corbel(loadOffset=600), 30, 420, CorbelDemand(100e3, None)))
    assert not checks["Corbel: shear span av / d"]["ok"]


# ── diaphragms (ASCE 7-05 Sec 12.10.1.1; Sec 2.5.5.6.3) ──


def test_diaphragm_force_bounds():
    # Two levels; Fpx = Σ F / Σ w · wpx, between 0.2 and 0.4 SDS I wpx.
    rows = diaphragm_forces([3.0, 6.0], [100e3, 200e3], [1000e3, 1000e3], 0.5, 1.0)
    fpx0, low0, high0 = rows[0]
    assert low0 == pytest.approx(0.2 * 0.5 * 1000e3)
    assert high0 == pytest.approx(0.4 * 0.5 * 1000e3)
    assert fpx0 == pytest.approx(150e3)  # 300 / 2000 · 1000 kN
    assert rows[1][0] == pytest.approx(200e3)  # 200 / 1000 · 1000, at the upper bound


def test_tributary_width():
    lines = [0.0, 6000.0, 12000.0]
    assert _tributary(lines, 0.0, 0.0, 12000.0) == pytest.approx(3000.0)
    assert _tributary(lines, 6000.0, 0.0, 12000.0) == pytest.approx(6000.0)

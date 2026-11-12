"""BNBC completeness (T9): live load reduction (BNBC 2020 Part 6 Sec 2.3.13), the support
settlement case ST (Sec 2.7.3.1, T), the column load takedown and the fire resistance sizes
(ACI 216.1-14 for the ratings of BNBC 2020 Part 4)."""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from saengine.design.fire_resistance import member_checks, required
from saengine.design.live_reduction import LiveScope, is_live_case, reduced, reduction
from saengine.design.takedown import takedown
from saengine.fem.settlement import add_settlement_case, strength_combinations_with_st
from saengine.library.settings import strength_combinations

# ── live load reduction (Sec 2.3.13) ──


def test_reduction_formula():
    # L / L0 = 0.25 + 4.57 / √(KLL AT): KLL = 4, AT = 100 m² → 0.4785, above 0.4 (2+ floors).
    factor, _ = reduction(4, 100, 3, LiveScope(live=2.0))
    assert factor == pytest.approx(0.25 + 4.57 / math.sqrt(400))
    # One floor: at least 0.5.
    factor, _ = reduction(4, 400, 1, LiveScope(live=2.0))
    assert factor == pytest.approx(0.5)
    # Two or more floors: at least 0.4.
    factor, _ = reduction(4, 2000, 5, LiveScope(live=2.0))
    assert factor == pytest.approx(0.4)


def test_reduction_threshold_and_exclusions():
    # KLL AT below 37.16 m²: not reduced.
    assert reduction(2, 18, 1, LiveScope(live=2.0))[0] == 1.0
    assert reduction(2, 19, 1, LiveScope(live=2.0))[0] < 1.0
    # Assembly: never reduced.
    assert reduction(4, 500, 4, LiveScope(live=2.9, assembly=True))[0] == 1.0
    # Heavy live load (> 4.79 kN/m²) or parking: 20 % on members of two or more floors only.
    assert reduction(4, 500, 1, LiveScope(live=6.0, heavy=True))[0] == 1.0
    assert reduction(4, 500, 2, LiveScope(live=6.0, heavy=True))[0] == pytest.approx(0.8)
    assert reduction(4, 500, 3, LiveScope(live=1.9, garage=True))[0] == pytest.approx(0.8)


def test_live_cases_and_reduced_forces():
    assert is_live_case("L") and is_live_case("LP3")
    assert not is_live_case("Lr") and not is_live_case("LPX")
    piece = SimpleNamespace(
        forces=[np.full((2, 6), 10.0)], live=[np.full((2, 6), 4.0)], sustained=None
    )
    (twin,) = reduced([piece], 0.5)
    # 10 - (1 - 0.5) · 4 = 8; the original untouched.
    assert np.allclose(twin.forces[0], 8.0)
    assert np.allclose(piece.forces[0], 10.0)


# ── settlement (Sec 2.7.3.1: T includes differential settlement) ──


def test_settlement_combinations():
    names = [n for n, _ in strength_combinations_with_st()]
    assert names == ["1.2D + 1.2ST + 1.6L + 0.5Lr"]
    combos = [c for c in strength_combinations(thermal=True, settlement=True) if c.ST]
    assert {c.name for c in combos} == {
        "1.2D + 1.2ST + 1.6L + 0.5Lr",
        "1.2D + 1.2T + 1.2ST + 1.6L + 0.5Lr",
        "1.2D - 1.2T + 1.2ST + 1.6L + 0.5Lr",
    }
    assert all(c.ST == pytest.approx(1.2) for c in combos)


def test_settlement_case_on_the_bases():
    from saengine.library.bim import ColumnElement

    building = SimpleNamespace(
        elements=[
            ColumnElement(id="C1", type="C", position=[0, 0], bottom=0, top=3000),
            ColumnElement(id="C2", type="C", position=[6000, 0], bottom=0, top=3000),
        ]
    )
    project = {
        "nodes": [
            {"id": 1, "coords": [0, 0, 0], "restraint": [True] * 6},
            {"id": 2, "coords": [6, 0, 0], "restraint": [True] * 6},
            {"id": 3, "coords": [0, 0, 3], "restraint": [False] * 6},
        ],
        "load_patterns": [],
        "analyses": [],
        "time_series": [],
    }
    rows = [SimpleNamespace(column="C2", value=25.0), SimpleNamespace(column="CX", value=5.0)]
    analysis, notes = add_settlement_case(project, building, rows)
    assert analysis is not None
    (pattern,) = project["load_patterns"]
    assert pattern["name"] == "ST"
    # 25 mm down at C2's base node, in m.
    assert pattern["support_displacements"] == [{"node_id": 2, "dof": 3, "value": -0.025}]
    assert any("CX" in n for n in notes)


# ── takedown ──


def test_takedown_cumulative_and_storey():
    from saengine.library.bim import ColumnElement

    stories = [
        SimpleNamespace(name="1F", elevation=3000),
        SimpleNamespace(name="2F", elevation=6000),
    ]
    lower = ColumnElement(id="C1", type="C", position=[0, 0], bottom=0, top=3000)
    upper = ColumnElement(id="C1-2", type="C", position=[0, 0], bottom=3000, top=6000)
    building = SimpleNamespace(stories=stories, elements=[lower, upper])

    def piece(pid, z0, z1):
        return SimpleNamespace(id=pid, start=np.array([0, 0, z0]), end=np.array([0, 0, z1]))

    pieces = {"C1": [piece(1, 0.0, 3.0)], "C1-2": [piece(2, 3.0, 6.0)]}
    # Section forces, tension positive: compression 300 kN at the lower foot, 100 kN upper (D).
    forces = {"D": {1: np.array([[-300e3, 0, 0, 0, 0, 0]] * 2),
                    2: np.array([[-100e3, 0, 0, 0, 0, 0]] * 2)}}  # fmt: skip
    found = takedown(building, pieces, {"forces": forces})
    (line,) = found["lines"]
    top, foot = line["rows"]
    assert top["story"] == "2F" and foot["story"] == "1F"
    assert foot["cumulative"]["D"] == pytest.approx(300.0)
    assert foot["storey"]["D"] == pytest.approx(200.0)
    assert foot["factored"] == pytest.approx(360.0)  # 1.2 D


# ── fire resistance (ACI 216.1-14) ──


def test_fire_tables():
    assert required("columnSize", 2) == pytest.approx(254)  # Table 4.5.1a, 10 in
    assert required("slabThickness", 1) == pytest.approx(89)  # Table 4.2, 3.5 in
    assert required("slabThickness", 1.5) == pytest.approx(109)
    assert required("columnSize", 5) is None


def test_fire_column_checks():
    column = SimpleNamespace(
        profile=SimpleNamespace(shape="rectangle", xDim=250.0, yDim=400.0),
        reinforcement=SimpleNamespace(cover=40.0, transverse=SimpleNamespace(dia=10.0)),
    )
    rows = {r["name"]: r for r in member_checks("column", column, 2)}
    assert not rows["Fire resistance: least dimension"]["ok"]  # 250 < 254 mm
    # Cover to the main bars 40 + 10 = 50 >= min(25 · 2, 50) = 50.
    assert rows["Fire resistance: cover to the main bars"]["ok"]
    assert member_checks("column", column, 0) == []

"""Crane runway loads (the bnbc2020 pack: Part 6 Sec 2.3.12 Table 6.2.6 row 5, Sec 1.6.6(i)),
the moving crane load cases, their combinations and the runway fatigue check (Sec 10.17)."""

from __future__ import annotations

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.design.steel import fatigue
from saengine.fem import cranes
from saengine.fem.combinations import crane_combinations
from saengine.library.settings import CraneRunway, LoadCombination


def _crane(**changes: object) -> CraneRunway:
    values: dict[str, object] = {
        "id": "CR1",
        "kind": "pendantOperated",
        "capacity": 100.0,
        "bridgeWeight": 80.0,
        "trolleyWeight": 15.0,
        "span": 20000.0,
        "hookApproach": 1000.0,
        "wheels": 2,
        "wheelBase": 3000.0,
        "runwaySpan": 6000.0,
    }
    return CraneRunway.model_validate({**values, **changes})


def test_code_pack_crane_factors():
    table = code_context.table("cranes")
    # Table 6.2.6 row 5(a): electric overhead cranes 25 %, pendant and remote ones included
    # (was 10 % pendant); row 5(c) cab-operated 25 %.
    for kind in ("cabOperated", "remoteOperated", "pendantOperated", "monorail"):
        assert table.impact[kind] == 0.25
    # Row 5(b): manually operated cranes, 50 % of row 5(a) (was 0 % and exempt).
    assert table.impact["handGeared"] == 0.125
    assert table.horizontalScale["handGeared"] == 0.5
    # Row 5(a)(i)-(ii): transverse 20 %, longitudinal 10 %.
    assert table.lateral == 0.20 and table.longitudinal == 0.10
    assert "Table 6.2.6" in table.source
    assert "SAEngine practice" in table.notes["monorail"]
    assert "SAEngine practice" in table.notes["lateral"]
    assert table.combination.factorOf == "L"


def test_wheel_loads_of_a_pendant_crane():
    loads = cranes.wheel_loads(_crane())
    # Rail near the trolley: 80/2 + (100 + 15)(20 - 1)/20 = 149.25 kN on two wheels.
    assert loads.static_max == pytest.approx(149.25 / 2)
    assert loads.static_min == pytest.approx((40 + 115 * 1 / 20) / 2)
    assert loads.vertical == pytest.approx(149.25 / 2 * 1.25)
    # Transverse: 20 % of (100 + 15), half on each runway, over two wheels.
    assert loads.lateral == pytest.approx(0.20 * 115 / 2 / 2)
    # Longitudinal: 10 % of the maximum wheel loads on the rail.
    assert loads.longitudinal == pytest.approx(0.10 * 149.25)


def test_manually_operated_crane_takes_half_of_row_5a():
    loads = cranes.wheel_loads(_crane(kind="handGeared"))
    assert loads.vertical == pytest.approx(149.25 / 2 * 1.125)
    assert loads.lateral == pytest.approx(0.10 * 115 / 2 / 2)
    assert loads.longitudinal == pytest.approx(0.05 * 149.25)


def test_moving_wheel_pair_on_a_simple_span():
    # Two equal loads a apart on a span L (a < 0.586 L): M = P (L - a/2)² / (2L).
    p, a, span = 10.0, 3.0, 6.0
    assert cranes.max_moment(p, 2, a, span) == pytest.approx(
        p * (span - a / 2) ** 2 / (2 * span), rel=2e-3
    )
    # End shear: the leading wheel at the support, the other a inside.
    assert cranes.max_shear(p, 2, a, span) == pytest.approx(p * (1 + (span - a) / span))
    # Column between two spans: one wheel over it, the other a away.
    assert cranes.max_reaction(p, 2, a, span) == pytest.approx(p * (1 + (span - a) / span))
    # One wheel: P L / 4.
    assert cranes.max_moment(p, 1, 0.0, span) == pytest.approx(p * span / 4, rel=1e-3)


def test_crane_summary_without_a_beam_type():
    rows, notes = cranes.crane_summary([_crane()], {}, {})
    assert rows[0]["wheelWithImpact_kN"] == pytest.approx(93.28, abs=0.01)
    assert "runwayBeam" not in rows[0] and "Table 6.2.6" in notes[0]
    assert not rows[0]["loadCases"]


# ───────────────────────────────────── moving load cases ─────────────────────────────────────

RUNWAY = {
    "railLevel": 6000.0,
    "runwayAxis": "X",
    "columnLineA": 0.0,
    "columnLineB": 21000.0,
}
COLUMNS = [cranes.Column(f"A{i}", 6000.0 * i, 0.0, 0.0, 8000.0) for i in range(4)] + [
    cranes.Column(f"B{i}", 6000.0 * i, 21000.0, 0.0, 8000.0) for i in range(4)
]


def test_bracket_points_on_the_runway_lines():
    points = cranes.bracket_points([_crane(**RUNWAY)], COLUMNS)
    assert set(points) == {c.id for c in COLUMNS}
    assert all(levels == [6000.0] for levels in points.values())
    # No runway direction: no load cases, no brackets.
    assert cranes.bracket_points([_crane()], COLUMNS) == {}


def test_moving_cases_balance_the_wheel_loads():
    crane = _crane(**RUNWAY)
    cases, notes = cranes.crane_load_cases([crane], COLUMNS)
    loads = cranes.wheel_loads(crane)
    # 4 column positions x 2 trolley sides x (V, T, B).
    assert len(cases) == 4 * 2 * 3 and "Sec 1.6.6(i)" in notes[0]
    by_code = {c.code: c for c in cases}
    vertical = by_code["C1V2a"]
    total = sum(v[2] for v in vertical.loads.values())
    # Both wheels of each rail on the runway: impact on the maximum wheel loads only.
    assert total == pytest.approx(-(loads.vertical + loads.static_min) * 2 * 1000)
    # The largest reaction is at the target column (x = 6 m) on line A: one wheel over it, the
    # other 3 m away on a 6 m span.
    target = vertical.loads[(6000.0, 0.0, 6000.0)]
    assert -target[2] == pytest.approx(loads.vertical * (1 + 0.5) * 1000)
    # Bracket eccentricity: rails 20 m apart centred between lines 21 m apart, 0.5 m inward.
    assert target[3] == pytest.approx(0.5 * target[2])
    transverse = by_code["C1T2a"]
    assert sum(v[1] for v in transverse.loads.values()) == pytest.approx(
        loads.lateral * 2 * 2 * 1000
    )
    longitudinal = by_code["C1B2a"]
    assert sum(v[0] for v in longitudinal.loads.values()) == pytest.approx(
        loads.longitudinal * 2 * 1000
    )


def test_crane_combinations_follow_the_pack_rule():
    cases, _ = cranes.crane_load_cases([_crane(**RUNWAY)], COLUMNS)
    present = {c.code for c in cases} | {"D", "SD", "L", "WX"}
    base = [
        LoadCombination(name="1.2D + 1.6L", D=1.2, L=1.6),
        LoadCombination(name="1.2D + 1.6WX + 1.0L", D=1.2, WX=1.6, L=1.0),
        LoadCombination(name="0.9D + 1.6WX", D=0.9, WX=1.6),
    ]
    formed = crane_combinations(base, present)
    assert formed is not None
    added = formed[len(base) :]
    # Gravity row: 8 positions-sides x (V±T, V±B) = 32; wind row: V alone = 8; 0.9D: none.
    assert len(added) == 8 * 4 + 8
    first = added[0]
    assert first.cases == {"C1V1a": 1.6, "C1T1a": 1.6}
    assert any(c.cases.get("C1T1a") == -1.6 for c in added)
    windy = [c for c in added if c.name.startswith("1.2D + 1.6WX")]
    assert len(windy) == 8
    assert all(len(c.cases) == 1 and next(iter(c.cases)).startswith("C1V") for c in windy)
    assert all(next(iter(c.cases.values())) == 1.0 for c in windy)
    assert crane_combinations(base, {"D", "L"}) is None


def test_derived_model_has_the_crane_cases():
    from test_fem_derive import OBJECTS, PLAN, SETTINGS

    from saengine.fem.derive import derive_fem
    from saengine.library import default_material_library
    from saengine.library.bim import generate

    building = generate(PLAN, "s")
    columns = [e for e in building.elements if e.kind == "column"]
    xs = sorted({e.position[0] for e in columns})
    ys = sorted({e.position[1] for e in columns})
    crane = _crane(
        span=float(xs[1] - xs[0]) - 400,
        runwaySpan=float(ys[1] - ys[0]),
        railLevel=2500.0,
        runwayAxis="Y",
        columnLineA=float(xs[0]),
        columnLineB=float(xs[1]),
    )
    settings = SETTINGS.model_copy(update={"cranes": [crane]})
    derivation = derive_fem(building, OBJECTS, default_material_library(), settings, {"bim": "abc"})
    project = derivation.project
    names = [p["name"] for p in project["load_patterns"]]
    assert "C1V1a" in names and "C1T2b" in names and "C1B1a" in names
    nodes = {n["id"]: n["coords"] for n in project["nodes"]}
    pattern = next(p for p in project["load_patterns"] if p["name"] == "C1V1a")
    assert all(abs(nodes[n["node_id"]][2] - 2.5) < 1e-6 for n in pattern["nodal_loads"])
    loads = cranes.wheel_loads(crane)
    total = sum(n["forces"][2] for n in pattern["nodal_loads"])
    assert total == pytest.approx(-(loads.vertical + loads.static_min) * 2 * 1000, rel=1e-3)


# ──────────────────────────────────────── fatigue ────────────────────────────────────────


def test_fatigue_pack_values():
    table = code_context.table("fatigue")
    # Sec 10.17.1: 20,000 cycles, 0.66 Fy; Eq 6.10.276-277 constants; Table 6.10.14a.
    assert table.minCycles == 20000 and table.maxServiceStress == 0.66
    assert table.equations["default"].constant == 329
    assert table.equations["default"].exponent == 0.333
    assert table.equations["F"].constant == 11e4 and table.equations["F"].exponent == 0.167
    expected = {
        "A": (250e8, 165),
        "B": (120e8, 110),
        "B'": (61e8, 83),
        "C": (44e8, 69),
        "D": (22e8, 48),
        "E": (11e8, 31),
        "E'": (3.9e8, 18),
        "F": (150e10, 55),
    }
    for category, (cf, threshold) in expected.items():
        row = table.categories[category]
        assert row.Cf == pytest.approx(cf) and row.threshold == threshold


def test_design_stress_range():
    # Category C at 2 million cycles: (44e8 × 329 / 2e6)^0.333 = 89.4 MPa.
    assert fatigue.design_stress_range("C", 2e6) == pytest.approx((44e8 * 329 / 2e6) ** 0.333)
    # Eq 6.10.278 (category C written out) agrees: 14.4e11 = 44e8 × 329 (within rounding).
    assert fatigue.design_stress_range("C", 2e6) == pytest.approx(
        (14.4e11 / 2e6) ** 0.333, rel=2e-3
    )
    # Never below the threshold (very many cycles).
    assert fatigue.design_stress_range("C", 1e12) == 69
    with pytest.raises(KeyError):
        fatigue.design_stress_range("Z", 1e6)


def test_fatigue_check_exemptions():
    n = fatigue.cycles(2, 25)  # 18,250 < 20,000
    assert n == 18250
    result = fatigue.check("C", n, 120.0, 150.0, 250.0)
    assert result.exempt and result.ok
    result = fatigue.check("C", 1e6, 50.0, 150.0, 250.0)
    assert "threshold" in result.exempt
    result = fatigue.check("C", 1e6, 120.0, 150.0, 250.0)
    assert not result.exempt and not result.ok  # F_SR = 112.5 MPa
    assert fatigue.check("C", 1e6, 100.0, 150.0, 250.0).ok
    # 0.66 Fy under unfactored loads.
    assert not fatigue.check("C", 1e6, 100.0, 170.0, 250.0).ok


def test_runway_fatigue_details():
    crane = _crane(fatigueCategory="C", cyclesPerDay=100, designLife=50)
    out = cranes.runway_fatigue(crane, 10e6, 100e6, 5e6, 1e6, 0.1e6, 250.0)
    assert out["cycles"] == 100 * 365 * 50
    bottom = out["details"]["bottomFlange"]
    assert bottom["stressRange_MPa"] == pytest.approx(100.0)
    top = out["details"]["topFlangeTip"]
    assert top["stressRange_MPa"] == pytest.approx(150.0)
    assert np.isclose(top["maxStress_MPa"], 160.0)

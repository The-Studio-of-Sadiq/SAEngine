"""Tension-only members released per combination (saengine.fem.tension_only).

The release is the mechanics of removing a member from a linear model (BNBC 2020 gives no
procedure of its own; the released braces are then designed for tension alone, Part 6 Sec 10.4).
"""

from __future__ import annotations

import numpy as np
import pytest

from saengine.fem import tension_only as to


def test_x_pair_takes_the_whole_shear_in_the_tension_diagonal():
    # Equal diagonals of a symmetric X panel: a lateral load gives +10 / -10. Pulling the ends
    # of one diagonal apart stretches it (+0.5 per unit) and shortens the other (-0.5).
    t0 = np.array([10.0, -10.0])
    g = np.array([[0.5, -0.5], [-0.5, 0.5]])
    x, released, warnings = to.solve(t0, g, [0, 1])
    assert released.tolist() == [False, True]
    forces = t0 + g @ x
    assert forces[0] == pytest.approx(20.0)  # the tension diagonal carries the whole shear
    assert x[1] == pytest.approx(-20.0)  # the force the released one would have carried
    assert warnings == []


def test_member_in_tension_everywhere_is_not_released():
    x, released, _ = to.solve(np.array([5.0, 3.0]), np.eye(2) * 0.5, [0, 1])
    assert not released.any() and np.allclose(x, 0.0)


def test_release_factors_add_the_release_cases_and_zero_the_slack_member():
    axial = {
        "WX": {"M1": 10_000.0, "M2": -10_000.0},
        "TO1": {"M1": 0.5 * to.UNIT, "M2": -0.5 * to.UNIT},
        "TO2": {"M1": -0.5 * to.UNIT, "M2": 0.5 * to.UNIT},
    }
    release = to.release_factors({"WX": 1.0}, axial, {"TO1": "M1", "TO2": "M2"})
    assert release.members == {"M2"} and release.slack == {"M2"}
    assert release.factors == {"TO2": pytest.approx(-20_000.0 / to.UNIT)}
    assert release.forces == {"M1": pytest.approx(20_000.0), "M2": 0.0}


def test_reversed_load_releases_the_other_diagonal():
    axial = {
        "WX": {"M1": 10_000.0, "M2": -10_000.0},
        "TO1": {"M1": 0.5 * to.UNIT, "M2": -0.5 * to.UNIT},
        "TO2": {"M1": -0.5 * to.UNIT, "M2": 0.5 * to.UNIT},
    }
    release = to.release_factors({"WX": -1.0}, axial, {"TO1": "M1", "TO2": "M2"})
    assert release.members == {"M1"}
    assert release.forces["M2"] == pytest.approx(20_000.0)


def test_pieces_of_one_member_are_released_together():
    t0 = np.array([-4.0, -2.0, 6.0])
    g = np.diag([0.3, 0.3, 0.3])
    _, released, _ = to.solve(t0, g, [0, 0, 1])
    assert released.tolist() == [True, True, False]


def test_mechanism_is_reported():
    # Both diagonals compressed and the panel has nothing else: removing both is a mechanism.
    t0 = np.array([-1.0, -1.0])
    g = np.array([[1.0, 0.0], [0.0, 1.0]])
    _, released, warnings = to.solve(t0, g, [0, 1])
    assert released.all() and any("mechanism" in w for w in warnings)


def test_release_cases_pull_the_element_ends_apart():
    coords = {1: np.array([0.0, 0.0, 0.0]), 2: np.array([3.0, 0.0, 4.0])}
    elements = [
        {"type": "ElasticBeamColumn", "name": "M7/p0", "nodes": [1, 2]},
        {"type": "ZeroLength", "name": "M7/pin", "nodes": [1, 2]},
        {"type": "ElasticBeamColumn", "name": "B1", "nodes": [1, 2]},
    ]
    cases = to.tension_only_cases(elements, coords, {"M7"})
    assert [(c, n) for c, n, _ in cases] == [("TO1", "M7/p0")]
    pair = cases[0][2]
    assert pair[1][:3] == pytest.approx([-600.0, 0.0, -800.0])
    assert pair[2][:3] == pytest.approx([600.0, 0.0, 800.0])


def test_release_cases_are_read_back_from_the_analyses():
    project = {
        "analyses": [
            {"name": "D: Dead load"},
            {"name": f"TO1: {to.RELEASE_LABEL} M7/p0"},
            {"name": f"TO2: {to.RELEASE_LABEL} M8#2"},
        ]
    }
    assert to.release_cases(project) == {"TO1": "M7/p0", "TO2": "M8#2"}
    assert to.member_of("M7/p0") == "M7" and to.member_of("M8#2") == "M8"


def test_axial_force_from_local_end_forces():
    ends = np.zeros(12)
    ends[0], ends[6] = -1500.0, 1500.0  # a tension member: -N at i, +N at j
    assert to.axial_force(ends) == pytest.approx(1500.0)

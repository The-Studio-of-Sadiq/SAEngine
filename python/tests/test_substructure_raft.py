"""Part 9 rafts: a plate on Winkler springs analysed with OpenSees, against closed forms.

- a uniform load on uniform springs settles q/ks everywhere and presses q;
- a point load on a large plate: Westergaard's / Hetényi's infinite plate on a Winkler
  foundation, w(r) = P/(2π k l²) (-kei(r/l)), l = (D/k)^(1/4), w(0) = P/(8 √(k D));
- a very stiff raft lifting off under a large moment: the rigid-footing partial contact
  q_max = 2P / (3 B (L/2 - e));
- the design checks put together (slab design of the raft, punching).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from saengine.library.objects import PlanarReinforcement
from saengine.substructure import raft
from saengine.substructure.raft import RaftColumn, RaftSpec


def square(half: float) -> list[tuple[float, float]]:
    return [(-half, -half), (half, -half), (half, half), (-half, half)]


def test_uniform_load_settles_q_over_ks(tmp_path: Path) -> None:
    spec = RaftSpec(
        "R1", [(0, 0), (6000, 0), (6000, 4000), (0, 4000)], 500, 25000, 25, 420, None, [],
        20000, unit_weight=24, surcharge=30, mesh_size=1000,
    )  # fmt: skip
    results = raft.run_raft(spec, {"D": ([], 1.0), "0.6D": ([], 0.6)}, tmp_path)
    q = 24 * 0.5 + 30  # kPa
    assert results.mesh.shares.sum() == pytest.approx(24.0)
    for name, factor in (("D", 1.0), ("0.6D", 0.6)):
        w = results.w[name]
        assert w == pytest.approx(np.full(len(w), -factor * q / 20000), rel=1e-6)
        assert raft._pressure(spec, w) == pytest.approx(factor * q, rel=1e-6)
    # A flat plate under a uniform pressure on uniform springs does not bend.
    moments = np.concatenate(results.shells["D"])[:, 3:6]
    assert np.abs(moments).max() < 1e-3  # N·m/m


def test_point_load_on_a_large_plate_matches_westergaard(tmp_path: Path) -> None:
    h, e, nu, ks, p = 0.3, 25e9, 0.2, 20000.0, 1000e3
    stiffness = e * h**3 / (12 * (1 - nu**2))
    k = ks * 1e3
    length = (stiffness / k) ** 0.25  # 1.31 m: the plate is 12 l wide
    spec = RaftSpec(
        "R2", square(8000), h * 1e3, e / 1e6, 25, 420, None, [RaftColumn("C1", 0, 0, 400, 400)],
        ks, nu=nu, unit_weight=0, mesh_size=500, compression_only=False,
    )  # fmt: skip
    results = raft.run_raft(spec, {"P": ([np.array([p, 0.0, 0.0])], 1.0)}, tmp_path)
    w = results.w["P"]
    centre = p / (8 * math.sqrt(k * stiffness))
    # The thick (Mindlin) plate adds its shear deflection under the point: within 3 %.
    assert -w.min() == pytest.approx(centre, rel=0.03)
    # Equilibrium: the springs carry the load.
    assert float(-(k * results.mesh.shares * w).sum()) == pytest.approx(p, rel=1e-6)
    special = pytest.importorskip("scipy.special")
    nodes = results.mesh.nodes
    radius = np.hypot(nodes[:, 0], nodes[:, 1])
    for r in (1.0, 2.0):
        ring = np.abs(radius - r) < 0.05
        expected = -p / (2 * math.pi * k * length**2) * special.kei(r / length)
        assert float(-w[ring].mean()) == pytest.approx(expected, rel=0.03)


def test_compression_only_springs_reproduce_partial_contact(tmp_path: Path) -> None:
    # A 4 x 4 m raft 2 m thick (rigid against ks = 20000), P = 1000 kN with e = 1.0 m > L/6:
    # q_max = 2 P / (3 B (L/2 - e)) = 166.7 kPa over a contact length of 3 (L/2 - e) = 3 m.
    spec = RaftSpec(
        "R3", square(2000), 2000, 25000, 28, 420, None, [RaftColumn("C1", 0, 0, 500, 500)],
        20000, unit_weight=0, mesh_size=500,
    )  # fmt: skip
    results = raft.run_raft(spec, {"M": ([np.array([1000e3, 0.0, 1000e6])], 1.0)}, tmp_path)
    w = results.w["M"]
    pressure = raft._pressure(spec, w)
    assert float((pressure * results.mesh.shares).sum()) == pytest.approx(1000.0, rel=1e-4)
    assert pressure.max() == pytest.approx(2 * 1000 / (3 * 4 * (2 - 1)), rel=0.03)
    x = results.mesh.nodes[:, 0]
    assert pressure[x < -1.05].max() < 1.0  # off the soil beyond the contact length
    lifted = w > 0
    assert lifted.any() and np.all(x[lifted] < -0.9)


def test_neighbour_pairs() -> None:
    grid = [RaftColumn(f"C{i}", x, y, 400, 400) for i, (x, y) in enumerate(
        [(0, 0), (6000, 0), (12000, 0), (0, 5000), (6000, 5000), (12000, 5000)]
    )]  # fmt: skip
    pairs = raft.neighbour_pairs(grid)
    assert (0, 1) in pairs and (0, 3) in pairs and (1, 4) in pairs
    assert (0, 2) not in pairs  # 12 m > 1.5 x 5 m


def test_raft_design_checks(tmp_path: Path) -> None:
    columns = [
        RaftColumn(f"C{3 * i + j + 1}", 5000 * i, 5000 * j, 500, 500)
        for i in range(3)
        for j in range(3)
    ]
    mesh = {"dia": 20, "spacing": 150}
    bars = PlanarReinforcement.model_validate(
        {"material": "B420", "cover": 75, "bottomX": mesh, "bottomY": mesh, "topX": mesh,
         "topY": mesh}
    )  # fmt: skip
    spec = RaftSpec(
        "R4", [(-1000, -1000), (11000, -1000), (11000, 11000), (-1000, 11000)], 700, 25000, 28,
        420, bars, columns, 15000,
    )  # fmt: skip
    service = {"D + L": [np.array([1500e3, 0, 0])] * 9}
    strength = {"1.2D + 1.6L": [np.array([2100e3, 0, 0])] * 9}
    out = raft.raft_design(spec, service, strength, tmp_path, qa=150, overburden=30)
    by_name = {c["name"]: c for c in out["checks"]}
    # Average gross pressure: (9 x 1500 kN + the raft's weight) / 144 m².
    weight = 24 * 0.7 * 144
    average = (9 * 1500 + weight) / 144
    data = out["raft"]
    assert len(data["pressure"]) == len(data["nodes"]) == len(data["settlement"])
    assert len(data["moments"]["bottomX"]) == len(data["elements"])
    shares = raft.raft_mesh(spec.outline, spec.mesh_size).shares
    assert float(np.dot(data["pressure"], shares)) / 144 == pytest.approx(average, rel=1e-3)
    assert by_name["Contact pressure (net)"]["demand"] == pytest.approx(
        data["summary"]["maxPressure"] - 30, abs=0.02
    )
    # The springs carry the gross pressure; the settlement is the net one's: (p - 30 kPa) / ks.
    assert data["summary"]["rebound"] == pytest.approx(30 / 15000 * 1e3)
    assert by_name["Settlement (max)"]["demand"] == pytest.approx(
        (data["summary"]["maxPressure"] - 30) / 15000 * 1e3, rel=1e-3
    )
    assert by_name["Settlement (max)"]["capacity"] == 75.0  # Table 6.3.8, sand, raft
    assert "Differential settlement" in by_name and "Angular distortion" in by_name
    assert {"Flexure bottom X (Wood-Armer)", "One-way shear", "Punching at C5"} <= set(by_name)
    # Punching at the middle column: Vu = P less the soil under the critical section.
    punch = by_name["Punching at C5"]
    assert "soil" in punch["note"] and punch["demand"] > 0
    # The slab design's strips run on the column lines.
    assert any("column strip" in c["note"] for c in out["checks"] if "Wood-Armer" in c["name"])
    # A corner column has half the middle one's tributary area (3.5² vs 5² m²): it settles more.
    assert data["columns"][0]["settlement"] > data["columns"][4]["settlement"] > 0


def test_net_settlement_under_a_uniform_load_with_overburden(tmp_path: Path) -> None:
    # Uniform gross pressure q = 24 × 0.5 + 30 = 42 kPa on ks = 2000 with 27 kPa of overburden
    # removed: the soil settles under the net 15 kPa, 15 / 2000 = 7.5 mm (not 42 / 2000 = 21 mm).
    spec = RaftSpec(
        "R5", [(0, 0), (6000, 0), (6000, 4000), (0, 4000)], 500, 25000, 25, 420, None, [],
        2000, unit_weight=24, surcharge=30, mesh_size=1000,
    )  # fmt: skip
    out = raft.raft_design(spec, {"D": []}, {}, tmp_path, overburden=27)
    data = out["raft"]
    assert data["summary"]["maxPressure"] == pytest.approx(42.0, rel=1e-4)
    assert data["settlement"] == pytest.approx([7.5] * len(data["settlement"]), abs=2e-3)
    by_name = {c["name"]: c for c in out["checks"]}
    assert by_name["Settlement (max)"]["demand"] == pytest.approx(7.5, rel=1e-4)


def test_raft_punching_adds_the_weight_inside_the_section(tmp_path: Path) -> None:
    # A 6 x 6 m raft 1.5 m thick (nearly rigid on ks = 20000), 27 kPa of fill, a 600 mm column
    # with Pu = 3000 kN, dead factor 1.2: the soil presses about (3000 + 1.2 (36 + 27) 36)/36
    # under the section, and Vu = Pu + 1.2 (36 + 27) A_in - p A_in (free body inside it).
    bars = PlanarReinforcement.model_validate(
        {"material": "B420", "cover": 75, "bottomX": {"dia": 20, "spacing": 150},
         "bottomY": {"dia": 20, "spacing": 150}}
    )  # fmt: skip
    spec = RaftSpec(
        "R6", square(3000), 1500, 25000, 28, 420, bars, [RaftColumn("C1", 0, 0, 600, 600)],
        20000, unit_weight=24, surcharge=27, mesh_size=250, compression_only=False,
    )  # fmt: skip
    load = np.array([3000e3, 0.0, 0.0])
    results = raft.run_raft(spec, {"U: U": ([load], 1.2)}, tmp_path)
    (check,) = raft._punching(spec, results, {"U": [load]}, {"U": 1.2})
    d = ((1500 - 75 - 10) + (1500 - 75 - 30)) / 2
    half = 300 + d / 2
    nodes = results.mesh.nodes * 1e3
    inside = (np.abs(nodes[:, 0]) <= half) & (np.abs(nodes[:, 1]) <= half)
    area_in = float(results.mesh.shares[inside].sum())
    own = 1.2 * (24 * 1.5 + 27)  # kPa
    pressure = (3000 + own * 36) / 36
    expected = 3000 + own * area_in - pressure * area_in
    assert check["demand"] == pytest.approx(expected, rel=0.02)
    # Leaving the weight out would understate Vu by own × A_in (about 300 kN here).
    assert check["demand"] - (3000 - pressure * area_in) > 0.9 * own * area_in


def test_raft_punching_proposes_and_checks_shear_reinforcement(tmp_path: Path) -> None:
    # A 600 mm raft under a 500 mm column with Pu = 3000 kN: vu about 1.4 MPa against
    # φ vc = 0.75 × 0.33 √28 λs (λs = 0.81 for d = 505 mm) = 1.07 MPa, so the concrete alone
    # fails and studs are proposed (saengine.design.punching, as for footings and flat slabs);
    # a given layout is checked.
    bars = PlanarReinforcement.model_validate(
        {"material": "B420", "cover": 75, "bottomX": {"dia": 20, "spacing": 150},
         "bottomY": {"dia": 20, "spacing": 150}}
    )  # fmt: skip
    spec = RaftSpec(
        "R7", square(3000), 600, 25000, 28, 420, bars, [RaftColumn("C1", 0, 0, 500, 500)],
        20000, mesh_size=250, compression_only=False,
    )  # fmt: skip
    load = np.array([3000e3, 0.0, 0.0])
    results = raft.run_raft(spec, {"U: U": ([load], 1.2)}, tmp_path)
    (plain,) = raft._punching(spec, results, {"U": [load]}, {"U": 1.2})
    assert plain["name"] == "Punching at C1"
    layout = plain["shearReinforcement"]
    assert layout["kind"] == "studs" and layout["lines"] >= 1
    assert plain["ok"] and plain["utilisation"] <= 1.0
    assert "soil" in plain["note"] and "studs" in plain["note"]
    # The proposal re-checks the one layout of the raft at every column.
    assert callable(plain.recheck)
    again = plain.recheck({**layout, "dia": layout["bar"], "firstLine": layout["s0"],
                           "spacing": layout["s"]})  # fmt: skip
    assert again is not None and again["ok"]
    # A given layout too light for it is checked, failing, with a fresh proposal beside it.
    from saengine.library.objects import PunchingReinforcement

    spec.punching_reinforcement = PunchingReinforcement.model_validate(
        {"kind": "studs", "dia": 10, "perLine": 8, "lines": 1, "firstLine": 100, "spacing": 150}
    )
    (given,) = raft._punching(spec, results, {"U": [load]}, {"U": 1.2})
    assert not given["ok"]
    assert given["proposedReinforcement"] is not None


def test_rigid_raft_pressure_matches_p_over_a_and_my_over_s() -> None:
    # 10 m x 6 m: A = 60 m², S about y = B L² / 6 = 6 · 10² / 6 = 100 m³.
    outline = [[0, 0], [10000, 0], [10000, 6000], [0, 6000]]
    centre = RaftColumn("C", 5000, 3000, 400, 400)
    total, qmax, qmin = raft._rigid_pressures(outline, [centre], [np.array([6e6, 0, 0])])
    assert total == 6e6 and qmax == pytest.approx(0.1) and qmin == pytest.approx(0.1)  # 100 kPa
    # The same load 1 m off centre in X: M = 6000 kN·m, ±M/S = ±60 kPa.
    off = RaftColumn("C", 6000, 3000, 400, 400)
    _, qmax, qmin = raft._rigid_pressures(outline, [off], [np.array([6e6, 0, 0])])
    assert (qmax, qmin) == (pytest.approx(0.16), pytest.approx(0.04))
    # A moment vector about +Y (6000 kN·m) presses the +X side as the offset load does.
    _, qmax2, qmin2 = raft._rigid_pressures(outline, [centre], [np.array([6e6, 0, 6e9])])
    assert (qmax2, qmin2) == (pytest.approx(0.16), pytest.approx(0.04))


def test_governing_combinations_keep_the_gravity_and_the_extremes() -> None:
    """N-U1: a raft was solved under every one of 300+ combinations (over an hour); it is now
    solved under those that govern a rigid raft: every gravity service combination, the largest
    load and the largest and least pressure; per column its largest axial load and moment."""
    outline = [[0, 0], [12000, 0], [12000, 6000], [0, 6000]]
    columns = [RaftColumn("A", 1000, 3000, 400, 400), RaftColumn("B", 11000, 3000, 400, 400)]

    def loads(a: float, b: float, m: float = 0.0) -> list[np.ndarray]:
        return [np.array([a, 0, m]), np.array([b, 0, m])]

    service = {
        "D": loads(1e6, 1e6),
        "D + L": loads(1.5e6, 1.5e6),
        "D + WX": loads(0.8e6, 1.4e6),  # the largest pressure (at B's side)
        "D + 0.75WX": loads(0.9e6, 1.25e6),  # milder: not kept
        "0.6D + WX": loads(0.4e6, 0.9e6),  # the least pressure
        "D - WX": loads(1.3e6, 0.9e6),  # milder than D + WX: not kept
    }
    strength = {
        "1.4D": loads(1.4e6, 1.4e6),
        "1.2D + 1.6L": loads(2.0e6, 2.0e6),  # the largest load at both
        "1.2D + 1.6WX": loads(1.0e6, 2.1e6),  # the largest at B and the largest pressure
        "1.2D + 0.8WX": loads(1.5e6, 1.9e6),  # not governing
        "0.9D + 1.6WX": loads(0.5e6, 1.2e6, 3e8),  # the least pressure; the largest moment
    }
    kept_service, kept_strength = raft.governing_combinations(outline, columns, service, strength)
    assert kept_service == ["D", "D + L", "D + WX", "0.6D + WX"]
    assert kept_strength == ["1.2D + 1.6L", "1.2D + 1.6WX", "0.9D + 1.6WX"]

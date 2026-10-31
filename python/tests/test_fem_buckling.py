"""Linear buckling of frames (saengine.fem.buckling) against Euler loads and effective length
factors of textbook cases."""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.fem import buckling as bk

E = 200e9  # Pa
A = 0.01  # m²
I_STRONG = 2e-5  # m⁴
I_WEAK = 1e-5
L = 4.0  # m
PIECES = 8


def column(
    pieces: int = PIECES,
    base: tuple[bool, ...] = (True,) * 6,
    top: tuple[bool, ...] = (True, True, False, False, False, True),
    load: float = -1000.0,
    height: float = L,
) -> tuple[dict, dict[int, float], list[int]]:
    """A vertical column of ``pieces`` elements along Z, its axial forces (tension positive) and
    its element ids. Default: fixed base; pinned top, held laterally and in torsion, free to
    move along Z."""
    nodes = []
    for k in range(pieces + 1):
        restraint = base if k == 0 else top if k == pieces else (False,) * 6
        nodes.append(
            {"id": k + 1, "coords": [0.0, 0.0, height * k / pieces], "restraint": restraint}
        )
    elements = [
        {
            "id": k + 1,
            "name": f"C1#{k + 1}",
            "type": "ElasticBeamColumn",
            "nodes": [k + 1, k + 2],
            "section_id": 1,
        }
        for k in range(pieces)
    ]
    project = {
        "nodes": nodes,
        "elements": elements,
        "sections": [
            {
                "id": 1,
                "type": "ElasticSection",
                "E": E,
                "A": A,
                "Iz": I_STRONG,
                "Iy": I_WEAK,
                "G": E / 2.6,
                "J": 1e-5,
            }
        ],
        "materials": [],
        "mp_constraints": [],
    }
    axial = {e["id"]: load for e in elements}
    return project, axial, [e["id"] for e in elements]


PINNED_BASE = (True, True, True, False, False, True)  # torsion held


def test_pinned_pinned_euler_load():
    """Pcr = π² E I / L² about the weak axis: λ = Pcr / P (Euler)."""
    project, axial, _ = column(base=PINNED_BASE)
    result = bk.linear_buckling(project, axial, modes=2)
    euler = math.pi**2 * E * I_WEAK / L**2
    assert result.factors[0] == pytest.approx(euler / 1000.0, rel=1e-3)
    # The second mode: the strong axis's Euler load (below the weak axis's second, 4 x the first).
    assert result.factors[1] == pytest.approx(math.pi**2 * E * I_STRONG / L**2 / 1000.0, rel=1e-3)


def test_cantilever_effective_length_two():
    """A cantilever (fixed base, free top): K = 2, Pcr = π² E I / (2 L)²."""
    project, axial, ids = column(top=(False,) * 6)
    result = bk.linear_buckling(project, axial, modes=1)
    assert result.factors[0] == pytest.approx(
        math.pi**2 * E * I_WEAK / (2 * L) ** 2 / 1000.0, rel=1e-3
    )
    rows = bk.member_effective_lengths(result, [("C1", ids)])
    assert rows[0]["Kminor"] == pytest.approx(2.0, rel=1e-3)
    # About the strong axis at the weak axis's buckling load: K = 2 √(I_strong / I_weak).
    assert rows[0]["Kmajor"] == pytest.approx(2.0 * math.sqrt(2.0), rel=1e-3)


def test_fixed_pinned():
    """Fixed base, pinned top held laterally: K = 0.699 (Pcr = 20.19 E I / L²)."""
    project, axial, ids = column()
    result = bk.linear_buckling(project, axial, modes=1)
    rows = bk.member_effective_lengths(result, [("C1", ids)])
    assert rows[0]["Kminor"] == pytest.approx(0.6992, rel=2e-3)


def test_geometric_stiffness_matrix():
    """The consistent geometric stiffness (Przemieniecki 1968): 6/5 N/L on the lateral
    translations, 2 L N / 15 on the end rotations; symmetric."""
    f = bk._Frame(1, "x", 1, 2, 3.0, np.eye(3), E, A, I_STRONG, I_WEAK, E / 2.6, 1e-5)
    kg = bk.frame_geometric(f, 100.0)
    assert np.allclose(kg, kg.T)
    assert kg[1, 1] == pytest.approx(6 / 5 * 100 / 3)
    assert kg[5, 5] == pytest.approx(2 * 3 * 100 / 15)
    assert kg[4, 4] == pytest.approx(2 * 3 * 100 / 15)
    k = bk.frame_stiffness(f)
    assert np.allclose(k, k.T)
    assert k[1, 1] == pytest.approx(12 * E * I_STRONG / 27)
    assert k[2, 2] == pytest.approx(12 * E * I_WEAK / 27)


def test_tension_only_raises():
    project, axial, _ = column(load=+1000.0)
    with pytest.raises(bk.BucklingError):
        bk.linear_buckling(project, axial)


def test_effective_length_factor():
    assert bk.effective_length_factor(
        E * I_WEAK, L, math.pi**2 * E * I_WEAK / L**2
    ) == pytest.approx(1)
    assert bk.effective_length_factor(E * I_WEAK, L, 1e-6) is None  # far beyond 10


def test_sway_portal_with_rigid_beam_diaphragm():
    """Two fixed-base columns tied at the top by a rigid diaphragm, free to sway, top rotations
    free: each is a cantilever, K = 2 about the sway direction's axis."""
    project, axial, _ids = column(top=(False,) * 6)
    # A second column at x = 5, and a diaphragm tying both tops (node 9 and its twin) in X-Y.
    offset = len(project["nodes"])
    for n in list(project["nodes"]):
        project["nodes"].append(
            {
                "id": n["id"] + offset,
                "coords": [5.0, 0.0, n["coords"][2]],
                "restraint": n["restraint"],
            }
        )
    for e in list(project["elements"]):
        project["elements"].append(
            {
                **e,
                "id": e["id"] + 100,
                "name": f"C2#{e['id']}",
                "nodes": [e["nodes"][0] + offset, e["nodes"][1] + offset],
            }
        )
        axial[e["id"] + 100] = axial[e["id"]]
    master = 2 * offset + 1
    project["nodes"].append(
        {
            "id": master,
            "coords": [2.5, 0.0, L],
            "restraint": (False, False, True, True, True, False),
        }
    )
    project["mp_constraints"].append(
        {
            "type": "RigidDiaphragm",
            "perp_dir": 3,
            "retained_node": master,
            "constrained_nodes": [offset, 2 * offset],
        }
    )
    result = bk.linear_buckling(project, axial, modes=1)
    assert result.factors[0] == pytest.approx(
        math.pi**2 * E * I_WEAK / (2 * L) ** 2 / 1000.0, rel=2e-3
    )

"""Deflected shapes and force diagrams of analysis results (saengine.fem.display)."""

from __future__ import annotations

import numpy as np
import pytest

from saengine.fem.display import (
    STATIONS,
    _Element,
    element_displacements,
    element_section_forces,
)

L, EI, W = 6.0, 2.0e7, -10_000.0  # m, N·m², N/m (gravity, along local z)


def beam() -> _Element:
    axes = np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]])
    return _Element(id=1, name="B1", i=1, j=2, length=L, axes=axes, ei_y=EI, ei_z=EI)


def test_fixed_beam_under_uniform_load() -> None:
    load = np.array([0.0, 0.0, W])
    # Fixed ends: each support carries half the load and the fixed-end moment wL²/12.
    end_i = np.array([0, 0, -W * L / 2, 0, W * L**2 / 12, 0])
    end_j = np.array([0, 0, -W * L / 2, 0, -W * L**2 / 12, 0])
    forces = element_section_forces(beam(), np.concatenate([end_i, end_j]), load)
    mid = STATIONS // 2
    assert forces[-1] == pytest.approx(end_j)  # the cut at x = L is the end j
    assert forces[mid][2] == pytest.approx(0.0, abs=1e-6)  # no shear at midspan
    assert forces[mid][4] == pytest.approx(W * L**2 / 24)  # sagging: tension below, My < 0
    assert forces[0][4] == pytest.approx(-W * L**2 / 12)  # hogging at the support, My > 0

    shape = element_displacements(beam(), np.zeros(6), np.zeros(6), load)
    assert shape[mid] == pytest.approx([0, 0, W * L**4 / (384 * EI)])
    assert shape[0] == pytest.approx([0, 0, 0])


def test_end_displacements_and_rotations_follow_hermite() -> None:
    # A rigid rotation θ about global y: w = -θ x along the element.
    theta = 0.001
    u_i = np.array([0, 0, 0, 0, theta, 0])
    u_j = np.array([0, 0, -theta * L, 0, theta, 0])
    shape = element_displacements(beam(), u_i, u_j, np.zeros(3))
    x = np.linspace(0, L, STATIONS)
    assert shape[:, 2] == pytest.approx(-theta * x)


def test_simply_supported_beam_peaks_at_wl2_over_8() -> None:
    # Pinned ends: each support carries half the load, no end moments; the moment diagram is a
    # parabola (sampled at every station, drawn as a curve) with wL²/8 at midspan.
    load = np.array([0.0, 0.0, W])
    end_i = np.array([0, 0, -W * L / 2, 0, 0, 0])
    end_j = np.array([0, 0, -W * L / 2, 0, 0, 0])
    forces = element_section_forces(beam(), np.concatenate([end_i, end_j]), load)
    x = np.linspace(0, L, STATIONS)
    assert forces[:, 4] == pytest.approx(W * x * (L - x) / 2)
    assert forces[STATIONS // 2][4] == pytest.approx(W * L**2 / 8)


def test_cantilever_tip_load_follows_hermite_curve() -> None:
    # Fixed at i, a tip load P (down) at j: w(x) = P x² (3L - x) / 6EI, the cubic the Hermite
    # functions of the end displacements and rotations give exactly.
    p = -1000.0
    tip = p * L**3 / (3 * EI)
    slope = p * L**2 / (2 * EI)  # dw/dx at the tip; θy = -dw/dx
    u_j = np.array([0, 0, tip, 0, -slope, 0])
    shape = element_displacements(beam(), np.zeros(6), u_j, np.zeros(3))
    x = np.linspace(0, L, STATIONS)
    assert shape[:, 2] == pytest.approx(p * x**2 * (3 * L - x) / (6 * EI))
    assert shape[-1][2] == pytest.approx(tip)

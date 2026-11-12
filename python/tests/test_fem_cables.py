"""Cables (saengine.fem.cables): the elastic catenary against the inextensible catenary and the
parabola, and the tension-only co-rotational truss chain against the elastic catenary (alpha 9
L4).

Written in the week without test runs (owner, 2026-11-05): not run yet."""

from __future__ import annotations

import math

import pytest

from saengine.fem import cables

SPAN = 100.0  # m
W = 10.0  # N/m


def test_stiff_cable_is_the_catenary():
    """With EA very large the elastic catenary is the classical one: for H = 1000 N, w = 10
    N/m over 100 m, L0 = (2H/w) sinh(wl/2H) and the sag (H/w)(cosh(wl/2H) - 1)."""
    h = 1000.0
    length = 2 * h / W * math.sinh(W * SPAN / (2 * h))
    sag = h / W * (math.cosh(W * SPAN / (2 * h)) - 1)
    result = cables.elastic_catenary(SPAN, 0.0, W, 1e14, length)
    assert result.H == pytest.approx(h, rel=1e-4)
    assert result.sag == pytest.approx(sag, rel=1e-4)
    assert result.sagAt == pytest.approx(SPAN / 2, abs=0.5)
    assert result.Va == pytest.approx(W * length / 2, rel=1e-6)
    assert result.tensionA == pytest.approx(math.hypot(h, W * length / 2), rel=1e-4)


def test_shallow_cable_is_the_parabola():
    """A shallow elastic cable (sag / span about 1/50): f = w l² / (8 H) within 1 %."""
    length = SPAN * 1.0008
    result = cables.elastic_catenary(SPAN, 0.0, W, 2e8, length)
    assert result.sag == pytest.approx(cables.parabolic_sag(W, SPAN, result.H), rel=0.01)


def test_inclined_cable_reactions_add_to_the_weight():
    length = 1.02 * math.hypot(SPAN, 20.0)
    result = cables.elastic_catenary(SPAN, 20.0, W, 5e8, length)
    assert result.Va + result.Vb == pytest.approx(W * length, rel=1e-9)
    assert result.Vb > result.Va  # the higher support carries more


def test_truss_chain_matches_the_elastic_catenary():
    """40 co-rotational tension-only trusses of the same cable: H within 1 %, the sag within
    2 % of the elastic catenary (the chain's lumped weights)."""
    ea = 1e8
    length = SPAN * 1.01
    exact = cables.elastic_catenary(SPAN, 0.0, W, ea, length)
    fe = cables.cable_fe(SPAN, 0.0, W, ea, length, segments=40)
    assert fe["H"] == pytest.approx(exact.H, rel=0.01)
    assert fe["sag"] == pytest.approx(exact.sag, rel=0.02)
    assert fe["maxTension"] == pytest.approx(exact.tensionA, rel=0.02)


def test_cable_needs_pretension():
    with pytest.raises(cables.CableError):
        cables.add_cable(None, "G1", (1, 2), ((0, 0, 0), (1, 0, 0)), 1e-4, 1.6e11, 0.0, 4, {})

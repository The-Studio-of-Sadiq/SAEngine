"""The closed-form ultimate actions against concreteproperties' meshed integration."""

from __future__ import annotations

import math

import pytest
from concreteproperties.concrete_section import ConcreteSection
from concreteproperties.results import UltimateBendingResults

from saengine.design.fast_ultimate import FastConcreteSection
from saengine.design.rc import section_of
from saengine.library.objects import CircleProfile, LinearReinforcement, RectangleProfile


def _section(profile, groups):
    reinforcement = LinearReinforcement.model_validate(
        {
            "material": "B420DWR",
            "cover": 40,
            "longitudinal": groups,
            "transverse": {"type": "tie", "dia": 10, "spacing": 150},
        }
    )
    return section_of(profile, reinforcement, 28, 420)


@pytest.mark.parametrize(
    ("profile", "groups", "tolerance"),
    [
        (
            RectangleProfile(xDim=600, yDim=600),
            [{"position": "perimeter", "count": 16, "dia": 20}],
            1e-6,
        ),
        (
            RectangleProfile(xDim=350, yDim=700),
            [
                {"position": "top", "count": 3, "dia": 20},
                {"position": "bottom", "count": 5, "dia": 28},
                {"position": "sides", "count": 2, "dia": 16},
            ],
            1e-6,
        ),
        # The 48-gon is clipped exactly; the mesh's integration differs in the fifth digit.
        (CircleProfile(radius=300), [{"position": "perimeter", "count": 8, "dia": 25}], 2e-4),
    ],
)
def test_closed_form_matches_the_meshed_integration(profile, groups, tolerance) -> None:
    section = _section(profile, groups)
    fast = section.analysis
    assert isinstance(fast, FastConcreteSection) and fast._fast is not None
    meshed = ConcreteSection(fast.compound_geometry, moment_centroid=(0.0, 0.0))
    # Neutral axes all round, shallow to beyond the section (the block covering all of it).
    for k in range(-6, 7):
        theta = k * math.pi / 6
        for d_n in (20, 80, 150, 300, 500, 800, 2000, math.inf):
            a, b = (
                s.calculate_ultimate_section_actions(
                    d_n, UltimateBendingResults(default_units=s.default_units, theta=theta)
                )
                for s in (meshed, fast)
            )
            scale_m = max(math.hypot(a.m_x, a.m_y), 1e6)
            assert b.n == pytest.approx(a.n, rel=tolerance, abs=1e3 * tolerance), (theta, d_n)
            assert (
                abs(b.m_x - a.m_x) <= tolerance * scale_m
                and abs(b.m_y - a.m_y) <= tolerance * scale_m
            )
            assert b.k_u == pytest.approx(a.k_u, rel=1e-12)
    # The search for the moment at an axial force rides on it.
    for s in (meshed, fast):
        s.cap = s.ultimate_bending_capacity(theta=0.3, n=1.5e6)
    # brentq converges to its own tolerance on d_n: equal to about 1e-5.
    assert fast.cap.m_xy == pytest.approx(meshed.cap.m_xy, rel=max(tolerance, 1e-5))

"""Slab loads on beams as triangles, trapezoids and other shapes (saengine.fem.slab_load_shapes).

Checked by hand against the 45° rule (BNBC 2020 Part 6 Sec 6.5.6.8.1, Figure 6.6.21) and, for
the beam moments, against the textbook results of a triangular load: fixed-end moment
5·w·L²/96 and simple-span midspan moment W·L/6 (w the peak, W the total).
"""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

from saengine.fem.slab_load_shapes import (
    EdgeProfile,
    Piece,
    segment_loads,
    slab_load_shapes,
    tributary_regions,
    two_way_limit,
)

P = 5.0  # kN/m²


def _rectangle(a: float, b: float) -> list[tuple[float, float]]:
    return [(0.0, 0.0), (a, 0.0), (a, b), (0.0, b)]


def _area(corners: list[tuple[float, float]]) -> float:
    pairs = zip(corners, corners[1:] + corners[:1], strict=True)
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in pairs)) / 2


def test_square_two_way_panel_gives_four_equal_triangles() -> None:
    lx = 4.0
    shape = slab_load_shapes(_rectangle(lx, lx), P, "twoWay", aspect_limit=2.0)
    assert shape.method == "twoWay"
    total = P * lx * lx
    for edge in shape.edges:
        assert edge.total == pytest.approx(total / 4)
        # A triangle: zero at the corners, peak p·lx/2 at mid-edge.
        assert edge.at(0.0) == pytest.approx(0.0, abs=1e-9)
        assert edge.at(lx) == pytest.approx(0.0, abs=1e-9)
        assert edge.at(lx / 2) == pytest.approx(P * lx / 2)
        assert edge.at(lx / 4) == pytest.approx(P * lx / 4)
        assert edge.end_loads == (0.0, 0.0)
    assert shape.total == pytest.approx(total, rel=1e-12)


def test_two_to_one_panel_gives_two_trapezoids_and_two_triangles() -> None:
    lx, ly = 4.0, 8.0
    shape = slab_load_shapes(_rectangle(ly, lx), P, "twoWay", aspect_limit=2.0)
    assert shape.method == "twoWay"  # ly/lx = 2 is still two-way (one-way above 2)
    long_0, short_1, long_2, short_3 = shape.edges
    for edge in (long_0, long_2):  # trapezoids: w·lx·(2ly - lx)/4, flat at p·lx/2
        assert edge.total == pytest.approx(P * lx * (2 * ly - lx) / 4)
        assert edge.at(0.0) == pytest.approx(0.0, abs=1e-9)
        assert edge.at(lx / 2) == pytest.approx(P * lx / 2)
        assert edge.at(ly / 2) == pytest.approx(P * lx / 2)
        assert edge.at(ly - lx / 2) == pytest.approx(P * lx / 2)
        assert edge.at(ly) == pytest.approx(0.0, abs=1e-9)
    for edge in (short_1, short_3):  # triangles: w·lx²/4
        assert edge.total == pytest.approx(P * lx**2 / 4)
        assert edge.at(lx / 2) == pytest.approx(P * lx / 2)
    assert shape.total == pytest.approx(P * lx * ly, rel=1e-12)


@pytest.mark.parametrize(("system", "ly"), [("twoWay", 10.0), ("oneWay", 6.0), ("oneWay", 4.0)])
def test_one_way_panel_loads_the_long_beams_only(system: str, ly: float) -> None:
    lx = 4.0
    shape = slab_load_shapes(_rectangle(ly, lx), P, system, aspect_limit=2.0)
    assert shape.method == "oneWay"
    long_0, short_1, long_2, short_3 = shape.edges
    assert short_1.total == 0.0 and short_3.total == 0.0
    for edge in (long_0, long_2):
        # Uniform p·lx/2 along the whole long edge.
        assert len(edge.pieces) == 1
        assert edge.pieces[0].q0 == pytest.approx(P * lx / 2)
        assert edge.pieces[0].q1 == pytest.approx(P * lx / 2)
        assert edge.total == pytest.approx(P * lx * ly / 2)
    assert shape.total == pytest.approx(P * lx * ly, rel=1e-12)


def test_l_shaped_panel_follows_its_straight_skeleton() -> None:
    # Two 3 m wide arms: a 6 × 3 m one and a 3 × 3 m one on top of its left end.
    corners = [(0.0, 0.0), (6.0, 0.0), (6.0, 3.0), (3.0, 3.0), (3.0, 6.0), (0.0, 6.0)]
    shape = slab_load_shapes(corners, P, "twoWay", aspect_limit=2.0)
    assert shape.method == "skeleton"
    # The exact total, whatever the sampling.
    assert shape.total == pytest.approx(P * 27.0, rel=1e-12)
    # By hand (ridges at mid-width of each arm, 45° from every corner, the re-entrant
    # corner's bisector to (1.5, 1.5)):
    #   edge 0 (y = 0, 6 m):  trapezoid 0 -> 1.5 m -> 0, (6 + 3)/2 × 1.5 = 6.75 m²
    #   edge 1 (x = 6, 3 m):  triangle 3 × 1.5 / 2 = 2.25 m²
    #   edge 2 (y = 3, 3 m to the re-entrant corner): 4.5 m², of which the triangle
    #          (3,3)-(1.5,1.5)-(3,1.5) of 1.125 m² lies beyond the corner (a point load there)
    #   edge 3 (x = 3, from the re-entrant corner): the same by symmetry
    #   edge 4 (y = 6, 3 m):  2.25 m²;  edge 5 (x = 0, 6 m): 6.75 m²
    expected = [6.75, 2.25, 4.5, 4.5, 2.25, 6.75]
    for edge, area in zip(shape.edges, expected, strict=True):
        assert edge.total == pytest.approx(P * area, rel=0.01)
    assert shape.edges[2].end_loads[1] == pytest.approx(P * 1.125, rel=0.02)
    assert shape.edges[3].end_loads[0] == pytest.approx(P * 1.125, rel=0.02)
    # Edge 0's shape: rising to p·1.5 at 1.5 m, flat to 4.5 m, falling to zero.
    edge0 = shape.edges[0]
    assert edge0.at(3.0) == pytest.approx(P * 1.5, rel=0.02)
    assert edge0.at(0.75) == pytest.approx(P * 0.75, rel=0.1)
    assert edge0.at(5.25) == pytest.approx(P * 0.75, rel=0.1)


def test_convex_irregular_panels_total_exactly_and_match_their_regions() -> None:
    for corners in (
        [(0.0, 0.0), (6.0, 0.0), (4.0, 3.0), (1.0, 3.0)],  # trapezoid (obtuse corners)
        [(0.0, 0.0), (6.0, 0.0), (0.0, 6.0)],  # right triangle
        [(0.0, 0.0), (4.0, -1.0), (7.0, 1.0), (6.0, 4.0), (2.0, 5.0), (-1.0, 3.0)],  # hexagon
    ):
        shape = slab_load_shapes(corners, P, "twoWay", aspect_limit=2.0)
        assert shape.method == "twoWay"
        assert shape.total == pytest.approx(P * _area(corners), rel=1e-12)
        regions = tributary_regions(corners, "twoWay", aspect_limit=2.0)
        for edge in shape.edges:
            assert edge.total == pytest.approx(P * regions[edge.index].area, rel=1e-9)


def test_orientation_and_split_edges_do_not_change_the_loads() -> None:
    ccw = slab_load_shapes(_rectangle(8.0, 4.0), P, "twoWay", aspect_limit=2.0)
    cw = slab_load_shapes(
        [(0.0, 0.0), (0.0, 4.0), (8.0, 4.0), (8.0, 0.0)], P, "twoWay", aspect_limit=2.0
    )
    assert [e.total for e in cw.edges] == pytest.approx(
        [ccw.edges[3].total, ccw.edges[2].total, ccw.edges[1].total, ccw.edges[0].total]
    )
    # The 8 m edge split at a column at 4 m: its trapezoid is cut in two.
    split = slab_load_shapes(
        [(0.0, 0.0), (4.0, 0.0), (8.0, 0.0), (8.0, 4.0), (0.0, 4.0)], P, "twoWay", 2.0
    )
    first, second = split.edges[0], split.edges[1]
    assert first.total + second.total == pytest.approx(ccw.edges[0].total)
    assert first.total == pytest.approx(P * (2 * 2 / 2 + 2 * 2))  # ramp to 2 m, then flat
    assert second.at(0.0) == pytest.approx(P * 2.0)
    assert second.at(4.0) == pytest.approx(0.0, abs=1e-9)
    assert split.total == pytest.approx(P * 32.0, rel=1e-12)


def test_two_way_limit_is_the_slab_tables_max_span_ratio(monkeypatch) -> None:
    """The limit is read from the pack's ``slabCoefficients`` (twoWayLimits.maxSpanRatio, BNBC
    6.5.8.2.2), the table of the slab design; a pack without it gives 2."""
    from saengine.codes import context as code_context

    pack = code_context.current()
    if pack.has("slabCoefficients"):
        expected = float(pack.data("slabCoefficients")["twoWayLimits"]["maxSpanRatio"])
        assert two_way_limit() == pytest.approx(expected)

    class _Pack:
        def __init__(self, tables: dict) -> None:
            self.tables = tables

        def has(self, name: str) -> bool:
            return name in self.tables

        def table(self, name: str) -> dict:
            return self.tables[name]

    monkeypatch.setattr(
        code_context,
        "current",
        lambda: _Pack({"slabCoefficients": {"twoWayLimits": {"maxSpanRatio": 1.5}}}),
    )
    assert two_way_limit() == pytest.approx(1.5)
    # 1.8 : 1 is one-way under that pack, two-way under the default.
    assert slab_load_shapes(_rectangle(5.0, 9.0), P, "twoWay").method == "oneWay"
    assert slab_load_shapes(_rectangle(5.0, 9.0), P, "twoWay", aspect_limit=2.0).method != "oneWay"
    monkeypatch.setattr(code_context, "current", lambda: _Pack({}))
    assert two_way_limit() == pytest.approx(2.0)


@pytest.mark.parametrize("scale", [0.001, 1.0])
def test_panels_at_exactly_two_to_one_stay_two_way_with_rounding_noise(scale: float) -> None:
    """Exact 2 : 1 rectangles on grid offsets, in mm × 0.001 as the derivation builds them (and
    in m): never one-way, so the short beams keep their triangles p·lx²/4."""
    flipped = []
    for lx_mm in range(2400, 6001, 150):
        for x0_mm, y0_mm in ((0, 0), (0, 7950), (3175, 0), (12345, 6789), (-4550, 21300)):
            ly_mm = 2 * lx_mm
            corners = [
                (x0_mm * scale, y0_mm * scale),
                ((x0_mm + lx_mm) * scale, y0_mm * scale),
                ((x0_mm + lx_mm) * scale, (y0_mm + ly_mm) * scale),
                (x0_mm * scale, (y0_mm + ly_mm) * scale),
            ]
            shape = slab_load_shapes(corners, P, "twoWay", aspect_limit=2.0)
            lx = lx_mm * scale
            short = [shape.edges[0].total, shape.edges[2].total]
            if shape.method == "oneWay" or short != pytest.approx([P * lx**2 / 4] * 2, rel=1e-9):
                flipped.append((lx_mm, x0_mm, y0_mm))
            regions = tributary_regions(corners, "twoWay", aspect_limit=2.0)
            assert regions[0].area == pytest.approx(lx**2 / 4, rel=1e-9)
    assert flipped == []
    # Just past the limit (beyond the tolerance) it is one-way.
    # Just past the limit (beyond the tolerance) it is one-way, far from the origin too: the
    # long beams take p·lx/2 each along their length, the short beams nothing.
    for x0, y0 in ((0.0, 0.0), (-4.55, 21.3), (125.0, -310.0)):
        ly = 8.0 * (1 + 1e-4)
        corners = [(x0, y0), (x0 + 4.0, y0), (x0 + 4.0, y0 + ly), (x0, y0 + ly)]
        shape = slab_load_shapes(corners, P, "twoWay", aspect_limit=2.0)
        assert shape.method == "oneWay"
        assert [e.total for e in shape.edges] == pytest.approx(
            [0.0, P * 2.0 * ly, 0.0, P * 2.0 * ly], abs=1e-9
        )
        assert sum(e.total for e in shape.edges) == pytest.approx(P * 4.0 * ly, rel=1e-12)


def test_segment_loads_are_statically_equivalent() -> None:
    # A triangle 0 -> 10 -> 0 over 4 m; a member from 0.5 to 1.5 m.
    profile = EdgeProfile(0, 4.0, (Piece(0.0, 2.0, 0.0, 10.0), Piece(2.0, 4.0, 10.0, 0.0)))
    w, f0, f1 = segment_loads(profile, 0.5, 1.5)
    # q(s) = 5 s on it: total ∫ 5 s ds = 5 (1.5² - 0.5²)/2 = 5; centroid
    # ∫ 5 s² ds / 5 = (1.5³ - 0.5³)/3 = 1.0833 m.
    assert w == pytest.approx(5.0)
    assert f0 + f1 == pytest.approx(0.0)
    moment = w * 1.0 * 0.5 + f1 * 1.0  # about the member's start
    assert moment == pytest.approx(5.0 * (1.0833333333 - 0.5))
    # Across the peak: the symmetric part has no correction.
    w, f0, f1 = segment_loads(profile, 1.5, 2.5)
    assert f0 == pytest.approx(0.0, abs=1e-12) and f1 == pytest.approx(0.0, abs=1e-12)


def test_uniform_equivalent_moment_errors_that_the_shapes_fix() -> None:
    """The figures of the issue: a short-edge triangle of total W on span L."""
    L, w = 4.0, 10.0
    W = w * L / 2
    simple_triangle, simple_uniform = W * L / 6, W * L / 8
    fixed_triangle, fixed_uniform = 5 * w * L**2 / 96, W * L / 12
    assert 1 - simple_uniform / simple_triangle == pytest.approx(0.25)
    assert 1 - fixed_uniform / fixed_triangle == pytest.approx(0.20)


def _beam_moments(profile: EdgeProfile, members: int, fixed: bool, correct: bool = True) -> list:
    """An OpenSees 2D beam along the edge in ``members`` members under the profile (down),
    applied as the analysis model does: mean uniform load + nodal pair per member. Returns the
    bending moment at each node (sagging positive)."""
    ops = pytest.importorskip("openseespy.opensees")
    L = profile.length
    ops.wipe()
    ops.model("basic", "-ndm", 2, "-ndf", 3)
    for i in range(members + 1):
        ops.node(i + 1, L * i / members, 0.0)
    if fixed:
        ops.fix(1, 1, 1, 1)
        ops.fix(members + 1, 1, 1, 1)
    else:
        ops.fix(1, 1, 1, 0)
        ops.fix(members + 1, 0, 1, 0)
    ops.geomTransf("Linear", 1)
    for i in range(members):
        ops.element("elasticBeamColumn", i + 1, i + 1, i + 2, 0.1, 25e6, 1e-3, 1)
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    nodal = [0.0] * (members + 1)
    for i in range(members):
        s0, s1 = L * i / members, L * (i + 1) / members
        w, f0, f1 = segment_loads(profile, s0, s1)
        ops.eleLoad("-ele", i + 1, "-type", "-beamUniform", -w)
        if correct:
            nodal[i] += f0
            nodal[i + 1] += f1
    for i, f in enumerate(nodal):
        if f:
            ops.load(i + 1, 0.0, -f, 0.0)
    ops.system("UmfPack")
    ops.numberer("RCM")
    ops.constraints("Plain")
    ops.integrator("LoadControl", 1.0)
    ops.algorithm("Linear")
    ops.analysis("Static")
    assert ops.analyze(1) == 0
    # Moment at each node from the member to its right (end i), the last from the left one.
    moments = [-ops.eleForce(i + 1)[2] for i in range(members)]
    moments.append(ops.eleForce(members)[5])
    ops.wipe()
    return moments


@pytest.mark.parametrize("members", [12, 8])
def test_fixed_fixed_beam_under_the_triangle_gives_5wl2_over_96(members: int) -> None:
    # The short edge of a 6 × 6 m two-way panel: a triangle peaking at w = p·L/2.
    L = 6.0
    shape = slab_load_shapes(_rectangle(L, L), P, "twoWay", aspect_limit=2.0)
    edge = shape.edges[0]
    w = P * L / 2
    moments = _beam_moments(edge, members, fixed=True)
    by_hand = 5 * w * L**2 / 96
    assert -moments[0] == pytest.approx(by_hand, rel=1e-9)
    assert -moments[-1] == pytest.approx(by_hand, rel=1e-9)
    # Midspan: the simple-span W·L/6 less the fixed-end moment.
    W = w * L / 2
    assert moments[members // 2] == pytest.approx(W * L / 6 - by_hand, rel=1e-9)


def test_fixed_end_moment_with_and_without_the_nodal_pairs() -> None:
    """With the nodal pairs the fixed-end moment is exact on any mesh (two members already);
    the mean-per-member load alone converges as 0.8/n² (n members): -20 % at 2, -0.56 % at 12
    (500 mm members on 6 m), -0.14 % at 24."""
    L = 6.0
    edge = slab_load_shapes(_rectangle(L, L), P, "twoWay", aspect_limit=2.0).edges[0]
    by_hand = 5 * (P * L / 2) * L**2 / 96
    for members in (2, 4):
        exact = -_beam_moments(edge, members, fixed=True, correct=True)[0]
        assert exact == pytest.approx(by_hand, rel=1e-9)
    errors = []
    for members in (2, 12, 24):
        plain = -_beam_moments(edge, members, fixed=True, correct=False)[0]
        errors.append(plain / by_hand - 1)
    assert errors == pytest.approx([-0.2, -0.2 / 36, -0.2 / 144], rel=1e-6)


def test_simply_supported_beam_midspan_moment_is_wl_over_6() -> None:
    L = 5.0
    edge = slab_load_shapes(_rectangle(L, L), P, "twoWay", aspect_limit=2.0).edges[0]
    W = edge.total
    moments = _beam_moments(edge, 10, fixed=False)
    assert moments[5] == pytest.approx(W * L / 6, rel=1e-9)
    assert moments[0] == pytest.approx(0.0, abs=1e-9)
    # 25 % more than the uniform load of the same total.
    assert moments[5] / (W * L / 8) == pytest.approx(4 / 3)


def test_degenerate_outlines_give_no_load() -> None:
    assert slab_load_shapes([(0.0, 0.0), (1.0, 0.0)], P).total == 0.0
    assert slab_load_shapes(_rectangle(4.0, 4.0), 0.0).total == 0.0
    bow_tie = [(0.0, 0.0), (4.0, 4.0), (4.0, 0.0), (0.0, 4.0)]
    shape = slab_load_shapes(bow_tie, P)
    assert shape.total == 0.0 and shape.notes
    assert math.isfinite(shape.total)


def test_division_points_cut_a_beam_into_mesh_size_members() -> None:
    from saengine.fem.slab_load_shapes import division_points

    points = division_points((0.0, 0.0, 3200.0), (6000.0, 0.0, 3200.0), 500.0)
    assert len(points) == 11
    assert points[0] == pytest.approx((500.0, 0.0, 3200.0))
    assert division_points((0.0, 0.0), (5200.0, 0.0), 500.0)[0][0] == pytest.approx(5200 / 11)
    assert division_points((0.0, 0.0), (400.0, 0.0), 500.0) == []


def test_division_points_keep_the_joint_zones_whole() -> None:
    """With clearances the end members are at least that long (so the rigid zones of the end
    offsets are not capped at 45 % of a 500 mm piece); the rest is cut to the size."""
    from saengine.fem.slab_load_shapes import division_points, joint_clearance

    clear = joint_clearance(500.0, 0.5)  # a 1000 mm deep column, default factor 0.5
    assert clear == pytest.approx(250.0 / 0.45 * 1.01)
    points = division_points((0.0, 0.0), (6000.0, 0.0), 500.0, (clear, 0.0))
    xs = [0.0] + [p[0] for p in points] + [6000.0]
    pieces = [b - a for a, b in pairwise(xs)]
    assert pieces[0] == pytest.approx(clear)
    assert all(p <= 500.0 + 1e-9 for p in pieces[1:])
    assert sum(pieces) == pytest.approx(6000.0)
    # Every end member can hold its zone: 0.45 × its length >= factor × reach.
    assert 0.45 * pieces[0] >= 0.5 * 500.0
    both = division_points((0.0, 0.0), (6000.0, 0.0), 500.0, (1111.0, 1111.0))
    xs = [0.0] + [p[0] for p in both] + [6000.0]
    assert xs[1] == pytest.approx(1111.0) and 6000.0 - xs[-2] == pytest.approx(1111.0)
    assert division_points((0.0, 0.0), (2000.0, 0.0), 500.0, (1111.0, 1111.0)) == []
    assert joint_clearance(0.0, 0.5) == 0.0 and joint_clearance(300.0, 0.0) == 0.0

"""Slabs on beams designed by BNBC 2020's coefficient methods (saengine.design.slab,
``coefficient_design``): two-way panels by Sec 6.5.8 (Tables 6.6.8-6.6.11, pp. 961-965) and
one-way slabs by Sec 6.1.4.3 (p. 891), checked against hand calculations."""

from __future__ import annotations

import itertools
import math

import pytest

from saengine.design.slab import (
    EdgeBeam,
    GravityCombination,
    LineSupport,
    SlabContext,
    coefficient_design,
    coefficient_panel,
    gravity_combinations,
    one_way_span,
    plan_axes,
    two_way_case,
    two_way_coefficients,
)
from saengine.library.objects import PlanarReinforcement
from saengine.library.settings import LoadCombination

MESH = {"material": "B420DWR", "cover": 20}
H = 125.0
FC, FY, ES = 25.0, 420.0, 200_000.0
BEAM = 250.0  # width of every beam [mm]
#: 1.2D + 1.6L and 1.4D (BNBC 2020 Sec 2.7.3.1); service loads 5.0 dead, 3.0 live kN/m²:
#: w = 1.2 x 5 + 1.6 x 3 = 10.8 kN/m² governs.
COMBOS = [GravityCombination("1.2D+1.6L", 1.2, 1.6), GravityCombination("1.4D", 1.4, 0.0)]
DEAD, LIVE = 5.0, 3.0
WD, WL = 6.0, 4.8
W = WD + WL


def mesh(dia: float = 10, spacing: float = 150, top: bool = True) -> PlanarReinforcement:
    layer = {"dia": dia, "spacing": spacing}
    data = {**MESH, "bottomX": layer, "bottomY": layer}
    if top:
        data |= {"topX": layer, "topY": layer}
    return PlanarReinforcement.model_validate(data)


def grid(xs: list[float], ys: list[float]):
    """Panels between grid lines (mm), beams 250 x 500 on every line: (outlines by (i, j),
    line supports, edge beams)."""
    panels = {
        (i, j): [(xs[i], ys[j]), (xs[i + 1], ys[j]), (xs[i + 1], ys[j + 1]), (xs[i], ys[j + 1])]
        for i in range(len(xs) - 1)
        for j in range(len(ys) - 1)
    }
    supports, beams = [], []
    for k, x in enumerate(xs):
        supports.append(LineSupport(f"BX{k}", (x, ys[0]), (x, ys[-1]), BEAM))
        beams.append(EdgeBeam((x, ys[0]), (x, ys[-1]), 1e16, BEAM, 500.0))
    for k, y in enumerate(ys):
        supports.append(LineSupport(f"BY{k}", (xs[0], y), (xs[-1], y), BEAM))
        beams.append(EdgeBeam((xs[0], y), (xs[-1], y), 1e16, BEAM, 500.0))
    return panels, supports, beams


def design(panels, supports, beams, key, system="twoWay", reinforcement=None, **kw):
    context = SlabContext(boundary=panels[key], axes=plan_axes(), supports=supports)
    neighbours = [outline for k, outline in panels.items() if k != key]
    return coefficient_design(
        system, H, reinforcement or mesh(), FC, FY, ES, DEAD, LIVE, COMBOS, context,
        neighbours, beams, **kw,
    )  # fmt: skip


#: Clear spans la = 4250 - 250 = 4000 mm (X), lb = 5250 - 250 = 5000 mm: m = 0.80 exactly.
XS = [0.0, 4250.0, 8500.0, 12750.0]
YS = [0.0, 5250.0, 10500.0, 15750.0]


def test_case_numbers_follow_the_table_figures() -> None:
    # BNBC Table 6.6.8 figures (p. 961): case 2 all edges continuous, case 1 none, case 4
    # one long + one short, case 8 a long edge discontinuous, case 9 a short edge.
    assert two_way_case(2, 2) == 2
    assert two_way_case(0, 0) == 1
    assert two_way_case(1, 1) == 4
    assert two_way_case(1, 2) == 8
    assert two_way_case(2, 1) == 9
    assert two_way_case(0, 2) == 3
    assert two_way_case(2, 0) == 5


def test_coefficients_read_and_interpolated() -> None:
    c = two_way_coefficients(0.8, 2)  # Table rows m = 0.80, case 2
    assert (c.neg_a, c.neg_b, c.dead_a, c.dead_b) == pytest.approx((0.065, 0.027, 0.026, 0.011))
    assert (c.live_a, c.live_b, c.load_a, c.load_b) == pytest.approx((0.041, 0.017, 0.71, 0.29))
    # Half way between 0.80 (0.065) and 0.85 (0.060).
    assert two_way_coefficients(0.825, 2).neg_a == pytest.approx(0.0625)
    one = two_way_coefficients(1.0, 1)
    assert one.neg_a is None and one.neg_b is None and one.dead_a == pytest.approx(0.036)
    with pytest.raises(ValueError):
        two_way_coefficients(0.45, 2)


def test_interior_two_way_panel_by_hand() -> None:
    """The middle panel of a 3 x 3 grid: case 2, m = 4000/5000 = 0.80.

    Ma,neg = 0.065 x 10.8 x 4.0² = 11.232 kN·m/m      Mb,neg = 0.027 x 10.8 x 5.0² = 7.290
    Ma,pos = (0.026 x 6.0 + 0.041 x 4.8) x 4.0² = 5.6448  Mb,pos = (0.011 x 6.0 + 0.017 x 4.8)
    x 5.0² = 3.690; shear at the long edges Wa w la / 2 = 0.71 x 10.8 x 4.0 / 2 = 15.336 kN/m.
    """
    panels, supports, beams = grid(XS, YS)
    result = design(panels, supports, beams, (1, 1))
    assert result.method == "twoWay" and result.case == 2 and result.m == pytest.approx(0.8)
    env = {k: v[0] / 1e3 for k, v in result.envelope.items()}
    assert env["topX"] == pytest.approx(0.065 * W * 16)
    assert env["topY"] == pytest.approx(0.027 * W * 25)
    assert env["bottomX"] == pytest.approx((0.026 * WD + 0.041 * WL) * 16)
    assert env["bottomY"] == pytest.approx((0.011 * WD + 0.017 * WL) * 25)
    assert result.envelope["topX"][1] == "1.2D+1.6L"
    assert result.shear["topX"][0] / 1e3 == pytest.approx(0.71 * W * 4.0 / 2)
    flexure = {c["name"]: c for c in result.checks}
    # Ø10 @ 150 top X: As = 523.6 mm²/m, d = 125 - 20 - 5 = 100 mm, a = 523.6 x 420 /
    # (0.85 x 25 x 1000) = 10.35 mm, φMn = 0.9 x 523.6 x 420 x (100 - 5.17) = 18.77 kN·m/m.
    top = flexure["Flexure top X (BNBC 6.5.8 coefficients)"]
    as_ = math.pi * 25 * 1000 / 150
    a = as_ * 420 / (0.85 * 25 * 1000)
    assert top["capacity"] == pytest.approx(0.9 * as_ * 420 * (100 - a / 2) / 1e6, abs=0.01)
    assert top["demand"] == pytest.approx(11.23, abs=0.01)
    assert top["ok"]


def test_corner_panel_with_discontinuous_edges_by_hand() -> None:
    """The corner panel: x- and y- have no slab beyond (case 4: one long, one short edge
    continuous). m = 0.80: Ca,neg 0.071, Cb,neg 0.029, Ca,dl 0.039, Cb,dl 0.016, Ca,ll 0.048,
    Cb,ll 0.020.

    Ma,neg = 0.071 x 10.8 x 16 = 12.2688; Ma,pos = (0.039 x 6 + 0.048 x 4.8) x 16 = 7.4304;
    Mb,neg = 0.029 x 10.8 x 25 = 7.830;   Mb,pos = (0.016 x 6 + 0.020 x 4.8) x 25 = 4.800.
    The top bars at the discontinuous edges (1/3 Mpos, practice) are below the continuous
    edges' negative moments here."""
    panels, supports, beams = grid(XS, YS)
    result = design(panels, supports, beams, (0, 0))
    assert result.case == 4
    env = {k: v[0] / 1e3 for k, v in result.envelope.items()}
    assert env["topX"] == pytest.approx(0.071 * W * 16)
    assert env["bottomX"] == pytest.approx((0.039 * WD + 0.048 * WL) * 16)
    assert env["topY"] == pytest.approx(0.029 * W * 25)
    assert env["bottomY"] == pytest.approx((0.016 * WD + 0.020 * WL) * 25)
    sides = coefficient_panel(panels[(0, 0)], plan_axes(), supports, [panels[(1, 0)]], beams).sides
    assert not sides["x-"].continuous and sides["x+"].continuous
    assert not sides["y+"].continuous  # the slab (0, 1) beyond it is not given here


def test_isolated_panel_top_bars_at_discontinuous_edges() -> None:
    """A single panel (case 1, m = 0.8): no negative coefficient; top bars for 1/3 of
    Ma,pos = (0.056 x 6 + 0.056 x 4.8) x 16 = 9.6768 -> 3.2256 kN·m/m (SAEngine practice)."""
    panels, supports, beams = grid(XS[:2], YS[:2])
    result = design(panels, supports, beams, (0, 0))
    assert result.case == 1
    assert result.envelope["bottomX"][0] / 1e3 == pytest.approx((0.056 * WD + 0.056 * WL) * 16)
    assert result.envelope["topX"][0] / 1e3 == pytest.approx((0.056 * WD + 0.056 * WL) * 16 / 3)
    assert "not a BNBC clause" in result.envelope["topX"][2]


#: One-way strips: clear spans 3500 mm (centre 3750, beams 250) along X, 9000 mm long.
XS_ONE = [0.0, 3750.0, 7500.0, 11250.0]
YS_ONE = [0.0, 9000.0]


def test_one_way_continuous_slab_coefficients_by_hand() -> None:
    """Three equal spans, w = 10.8 kN/m², ln = 3.5 m (BNBC 6.1.4.3, p. 891):

    end span:   M+ = w ln²/14 = 10.8 x 12.25 / 14 = 9.450; exterior support (spandrel beam)
                w ln²/24 = 5.5125; first interior support, more than two spans, w ln²/10 =
                13.230; shear there 1.15 w ln / 2 = 21.735 kN/m;
    middle:     M+ = w ln²/16 = 8.26875; interior supports w ln²/11 = 12.0273.
    """
    panels, supports, beams = grid(XS_ONE, YS_ONE)
    end = design(panels, supports, beams, (0, 0), "oneWay")
    assert end.method == "oneWay" and end.span == "X"
    assert end.envelope["bottomX"][0] / 1e3 == pytest.approx(W * 3.5**2 / 14)
    assert end.envelope["topX"][0] / 1e3 == pytest.approx(W * 3.5**2 / 10)
    assert end.shear["topX"][0] / 1e3 == pytest.approx(1.15 * W * 3.5 / 2)
    assert end.envelope["topY"][0] == 0.0 and end.envelope["bottomY"][0] == 0.0
    middle = design(panels, supports, beams, (1, 0), "oneWay")
    assert middle.envelope["bottomX"][0] / 1e3 == pytest.approx(W * 3.5**2 / 16)
    assert middle.envelope["topX"][0] / 1e3 == pytest.approx(W * 3.5**2 / 11)

    panel = coefficient_panel(panels[(0, 0)], plan_axes(), supports, [panels[(1, 0)]], beams)
    others = [coefficient_panel(panels[(1, 0)], plan_axes(), supports, [panels[(2, 0)]], beams)]
    span = one_way_span(panel, "X", others, DEAD, LIVE)
    exterior = next(e for e in span.ends if e.side == "x-")
    assert exterior.divisor == 24 and "spandrel" in exterior.what
    assert W * (exterior.ln / 1e3) ** 2 / exterior.divisor == pytest.approx(5.5125)


def test_one_way_two_spans_and_a_two_way_type_longer_than_two_to_one() -> None:
    """Two spans: the first interior support takes w ln²/9 = 10.8 x 12.25 / 9 = 14.70. A
    two-way slab type on a 3750 x 9000 panel (2.4 : 1) is designed one-way (BNBC 6.5.8.2.2)."""
    panels, supports, beams = grid(XS_ONE[:3], YS_ONE)
    result = design(panels, supports, beams, (0, 0), "twoWay")
    assert result.method == "oneWay"
    assert any("6.5.8.2.2" in n for n in result.notes)
    assert result.envelope["topX"][0] / 1e3 == pytest.approx(W * 3.5**2 / 9)


def test_one_way_outside_the_limits_uses_the_bounds() -> None:
    """A single span is outside 6.1.4.3 (a): M+ = w ln²/8 = 16.5375 kN·m/m."""
    panels, supports, beams = grid(XS_ONE[:2], YS_ONE)
    result = design(panels, supports, beams, (0, 0), "oneWay")
    assert result.envelope["bottomX"][0] / 1e3 == pytest.approx(W * 3.5**2 / 8)
    assert any("6.1.4.3 (a)" in n for n in result.notes)


def test_minimum_steel_and_spacing_by_hand() -> None:
    """h = 125 mm, fy 420: As,min = 0.0018 x 125 x 1000 = 225 mm²/m (BNBC 8.1.11.2 (a)).
    Ø8 @ 250 gives 201.06 mm²/m: 225 / 201.06 = 1.119. Two-way spacing limit min(2h, 450) =
    250 mm (6.5.8.6.2); Ø10 @ 300 is 1.2 times it. With brick aggregate x 1.5: 337.5 mm²/m."""
    panels, supports, beams = grid(XS, YS)
    checks = {c["name"]: c for c in design(panels, supports, beams, (1, 1), "twoWay",
                                            mesh(8, 250)).checks}  # fmt: skip
    minimum = checks["Min. reinforcement (BNBC 8.1.11.2)"]
    assert minimum["demand"] == pytest.approx(225.0)
    assert minimum["capacity"] == pytest.approx(201.06, abs=0.01)
    assert minimum["utilisation"] == pytest.approx(1.119, abs=0.001)
    assert not minimum["ok"]
    checks = {c["name"]: c for c in design(panels, supports, beams, (1, 1), "twoWay",
                                            mesh(10, 300), brick_aggregate=True).checks}  # fmt: skip
    assert checks["Max. spacing"]["capacity"] == pytest.approx(250.0)
    assert checks["Max. spacing"]["utilisation"] == pytest.approx(1.2)
    assert checks["Min. reinforcement (BNBC 8.1.11.2)"]["demand"] == pytest.approx(337.5)
    # One-way: 3h = 375 mm along the span, min(5h, 450) = 450 mm across it.
    panels1, supports1, beams1 = grid(XS_ONE, YS_ONE)
    checks = {c["name"]: c for c in design(panels1, supports1, beams1, (1, 0), "oneWay",
                                            mesh(10, 400)).checks}  # fmt: skip
    assert checks["Max. spacing"]["capacity"] == pytest.approx(375.0)
    assert "8.1.6.5" in checks["Max. spacing"]["note"]


def test_scope_limits_raise_with_the_reason() -> None:
    panels, supports, beams = grid(XS, YS)
    shallow = [EdgeBeam(b.start, b.end, b.ei, b.width, 300.0) for b in beams]  # < 3 x 125
    with pytest.raises(ValueError, match="6.5.8.2.1"):
        design(panels, supports, shallow, (1, 1))
    with pytest.raises(ValueError, match="not supported"):
        design(panels, supports[:-1], beams, (1, 2))  # the beam on the top line removed
    l_shape = [(0, 0), (4250, 0), (4250, 2000), (2000, 2000), (2000, 5250), (0, 5250)]
    with pytest.raises(ValueError, match="rectangular"):
        coefficient_panel(l_shape, plan_axes(), supports)
    with pytest.raises(ValueError, match="flat"):
        design(panels, supports, beams, (1, 1), "flat")
    # αf l2/l1 < 1 with a very flexible beam (BNBC 6.5.8.2.3).
    soft = [EdgeBeam(b.start, b.end, 1e9, b.width, 500.0) for b in beams]
    with pytest.raises(ValueError, match="6.5.8.2.3"):
        design(panels, supports, soft, (1, 1), ec=25_000.0)


def test_gravity_parts_of_the_project_combinations() -> None:
    combos = [
        LoadCombination(name="1.4D", D=1.4),
        LoadCombination(name="1.2D+1.6L+0.5Lr", D=1.2, L=1.6, Lr=0.5),
        LoadCombination(name="0.9D+1.0E", D=0.9, EX=1.0),
    ]
    floor = gravity_combinations(combos)
    assert [(c.name, c.dead, c.live) for c in floor] == [
        ("1.4D", 1.4, 0.0),
        ("1.2D+1.6L+0.5Lr", 1.2, 1.6),
        ("0.9D+1.0E", 0.9, 0.0),
    ]
    roof = gravity_combinations(combos, roof=True)
    assert roof[1].live == 0.5


def _one_way_pair(far_cover: float, far_known: bool = True):
    """Two one-way slabs (3750 x 9000 each, beams 250 wide): the second slab's far beam at x =
    7500 covers ``far_cover`` of its side; ``far_known``: whether that beam is an EdgeBeam."""
    panels, supports, beams = grid(XS_ONE[:3], YS_ONE)
    end = far_cover * YS_ONE[-1]
    supports = [s for s in supports if s.id != "BX2"]
    supports.append(LineSupport("BX2", (7500.0, 0.0), (7500.0, end), BEAM))
    beams = [b for b in beams if b.start[0] != 7500.0 or b.end[0] != 7500.0]
    if far_known:
        beams.append(EdgeBeam((7500.0, 0.0), (7500.0, end), 1e16, BEAM, 500.0))
    return panels, supports, beams


def test_one_way_beside_a_slab_that_is_not_a_panel_is_not_taken_as_equal_spans() -> None:
    """The slab beyond x+ is not a coefficient panel. Before, its span was taken as this one's
    and the support as 'more than two spans' (w ln²/10 = 13.23, below even the two-span w
    ln²/9 = 14.70). Now BNBC 6.1.4.3 is taken as not met:

    - its far beam covers 80 % of its side; its sides across the shared beam are held by beams,
      so it spans to them and does not cantilever from the shared beam (0.0.45: a slab held on
      three edges is no cantilever; w l²/2 = 75.94 before): w ln,max²/8 with its extent
      3.75 m as its span, 10.8 x 3.75² / 8 = 18.98 kN·m/m, above w ln²/9 = 14.70;
    - its far side fully supported but by a beam of unknown stiffness: the same 18.98 kN·m/m;
      positive w ln²/8 = 16.54.
    """
    panels, supports, beams = _one_way_pair(0.8)
    result = design(panels, supports, beams, (0, 0), "oneWay")
    assert result.envelope["topX"][0] / 1e3 == pytest.approx(W * 3.75**2 / 8)
    assert result.envelope["topX"][0] / 1e3 > W * 3.5**2 / 9
    assert any("not a coefficient panel" in n and "not supported" in n for n in result.notes)
    assert "cantilever" not in result.envelope["topX"][2]

    panels, supports, beams = _one_way_pair(1.0, far_known=False)
    result = design(panels, supports, beams, (0, 0), "oneWay")
    assert result.envelope["topX"][0] / 1e3 == pytest.approx(W * 3.75**2 / 8)
    assert result.envelope["bottomX"][0] / 1e3 == pytest.approx(W * 3.5**2 / 8)
    assert any("6.1.4.3 taken as not met" in n for n in result.notes)


def test_two_way_beside_a_balcony() -> None:
    """A single 4250 x 5250 panel with a 1500 mm balcony beyond x- (its other three sides
    free): x- counts as discontinuous for the case (case 1, the isolated panel's positive
    moments), and its top bars take the larger of the negative coefficient as if continuous
    (one long edge continuous) and the balcony's w l²/2 = 10.8 x 1.5² / 2 = 12.15 kN·m/m."""
    panels, supports, beams = grid(XS[:2], YS[:2])
    balcony = [(-1500.0, 0.0), (0.0, 0.0), (0.0, 5250.0), (-1500.0, 5250.0)]
    context = SlabContext(boundary=panels[(0, 0)], axes=plan_axes(), supports=supports)
    result = coefficient_design(
        "twoWay", H, mesh(), FC, FY, ES, DEAD, LIVE, COMBOS, context, [balcony], beams
    )
    assert result.case == 1
    c1 = two_way_coefficients(0.8, 1)
    assert result.envelope["bottomX"][0] / 1e3 == pytest.approx(
        (c1.dead_a * WD + c1.live_a * WL) * 16
    )
    as_continuous = two_way_coefficients(0.8, two_way_case(1, 0)).neg_a
    expected = max(
        as_continuous * W * 16, W * 1.5**2 / 2, (c1.dead_a * WD + c1.live_a * WL) * 16 / 3
    )
    assert result.envelope["topX"][0] / 1e3 == pytest.approx(expected)
    assert any("x-" in n and "not a coefficient panel" in n for n in result.notes)


def test_sides_made_of_several_beams_and_unknown_supports() -> None:
    """Each side of an isolated panel made of two half-length beams counts as one beam line:
    300 mm deep beams (< 3 x 125) still fail BNBC 6.5.8.2.1, and deep ones give the same
    design as single beams. A side on a support that is neither a known beam nor stated to be
    a wall cannot have its scope checked; stated as a wall it passes (αf infinite)."""
    panel = [(0.0, 0.0), (4250.0, 0.0), (4250.0, 5250.0), (0.0, 5250.0)]
    corners = [panel[k] for k in (0, 1, 2, 3, 0)]

    def split(depth: float, ei: float):
        supports, beams = [], []
        for a, b in itertools.pairwise(corners):
            m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            for s, e in ((a, m), (m, b)):
                supports.append(LineSupport("B", s, e, BEAM))
                beams.append(EdgeBeam(s, e, ei, BEAM, depth))
        return supports, beams

    def run(supports, beams, **kw):
        context = SlabContext(boundary=panel, axes=plan_axes(), supports=supports)
        return coefficient_design(
            "twoWay", H, mesh(), FC, FY, ES, DEAD, LIVE, COMBOS, context, [], beams, **kw
        )

    with pytest.raises(ValueError, match="6.5.8.2.1"):
        run(*split(300.0, 1e16))
    with pytest.raises(ValueError, match="6.5.8.2.3"):
        run(*split(500.0, 1e9), ec=25_000.0)
    single = design(*grid(XS[:2], YS[:2]), (0, 0))
    halves = run(*split(500.0, 1e16), ec=25_000.0)
    assert halves.case == single.case == 1
    assert halves.envelope == pytest.approx(single.envelope)

    panels, supports, beams = grid(XS[:2], YS[:2])
    no_x0 = [b for b in beams if not (b.start[0] == 0.0 and b.end[0] == 0.0)]
    with pytest.raises(ValueError, match="not known"):
        design(panels, supports, no_x0, (0, 0), ec=25_000.0)
    walls = [
        LineSupport(s.id, s.start, s.end, s.width, "wall") if s.id == "BX0" else s for s in supports
    ]
    sides = coefficient_panel(panels[(0, 0)], plan_axes(), walls, [], no_x0).sides
    assert sides["x-"].wall and sides["x-"].beam is None and sides["x+"].beam is not None
    assert design(panels, walls, no_x0, (0, 0), ec=25_000.0).case == 1

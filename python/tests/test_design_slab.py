"""Slab design checks: Wood-Armer moments, layer capacities and punching by hand, the shell
axes against the solver, and the checks of analysed slabs (one-way on beams, flat)."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from test_design import COLUMN_REINFORCEMENT, beam_reinforcement
from test_fem_derive import OBJECTS, PLAN

from saengine.design import design_report
from saengine.design.slab import (
    ColumnJoint,
    LineSupport,
    PlanFrame,
    ShellPoint,
    SlabContext,
    Strip,
    StripSection,
    critical_section,
    design_strips,
    integration_points,
    layer_capacity,
    layers_of,
    one_way_shear,
    outline_axes,
    plan_axes,
    punching_capacity,
    punching_stress,
    shell_axes,
    slab_checks,
    slab_forces,
    strip_average,
    strip_weights,
    wood_armer,
)
from saengine.fem.derive import derive_fem
from saengine.library import FloorPlan, ObjectLibrary, default_material_library
from saengine.library.bim import AreaElement, generate
from saengine.library.objects import PlanarReinforcement
from saengine.library.settings import LoadCombination, default_project_settings

BAR10 = math.pi * 10**2 / 4
MESH = {"material": "B420DWR", "cover": 20}


def planar(top: bool = True, dia: float = 10, spacing: float = 150) -> PlanarReinforcement:
    layer = {"dia": dia, "spacing": spacing}
    data = {**MESH, "bottomX": layer, "bottomY": layer}
    if top:
        data |= {"topX": layer, "topY": layer}
    return PlanarReinforcement.model_validate(data)


# ─────────────────────────────────────── by hand ───────────────────────────────────────


def test_wood_armer_hand_cases() -> None:
    # Sagging both ways, a little twist: bottom bars only.
    assert wood_armer(10, 5, 2) == pytest.approx((12, 7, 0, 0))
    # my hogging: My*b = 5 - 3 < 0 -> 0 and Mx*b = 10 + 3²/5; top: Mx*t = 7 > 0 -> 0 and
    # My*t = -5 - 3²/10.
    assert wood_armer(10, -5, 3) == pytest.approx((11.8, 0, 0, 5.9))
    # Pure twist: |mxy| in all four layers.
    assert wood_armer(0, 0, 4) == pytest.approx((4, 4, 4, 4))
    # Hogging both ways: top bars only.
    assert wood_armer(-10, -6, 2) == pytest.approx((0, 0, 12, 8))
    # The twist's sign does not matter.
    assert wood_armer(3, 1, -2) == wood_armer(3, 1, 2)


def test_layer_capacity_per_metre_by_hand() -> None:
    # 150 slab, cover 20, T10 @ 150 every layer: X layers outer (d = 125), Y inner (d = 115).
    layers = layers_of(planar(), 150)
    assert layers["bottomX"].d == pytest.approx(125)
    assert layers["bottomY"].d == pytest.approx(115)
    assert layers["topX"].d == pytest.approx(125) and layers["topY"].d == pytest.approx(115)
    area = BAR10 * 1000 / 150
    assert layers["bottomX"].area == pytest.approx(area)
    a = area * 420 / (0.85 * 24.1 * 1000)
    mn = area * 420 * (125 - a / 2)
    capacity = layer_capacity(area, 125, 24.1, 420)
    assert capacity.mn == pytest.approx(mn, rel=0.01)
    assert capacity.phi == 0.90 and capacity.phi_mn == pytest.approx(0.9 * mn, rel=0.01)
    assert capacity.c_d == pytest.approx(a / 0.85 / 125)
    # Slabs need εt >= 0.004 (ACI 7.3.3.1, 8.3.3.1), not εty + 0.003: c/d <= 3/7.
    assert capacity.c_d_limit == pytest.approx(0.003 / (0.003 + 0.004))
    # Between εt = 0.004 and εty + 0.003 the section is allowed, with φ below 0.90.
    heavy = layer_capacity(2070, 125, 24.1, 420)  # c/d = 0.40, εt = 0.0045
    assert 0.004 < heavy.eps_t < 0.0051 and 0.81 < heavy.phi < 0.90
    assert heavy.c_d < heavy.c_d_limit
    # Without an X layer the Y layer of that face is the outer one.
    only_y = PlanarReinforcement.model_validate({**MESH, "bottomY": {"dia": 12, "spacing": 200}})
    assert layers_of(only_y, 150)["bottomY"].d == pytest.approx(150 - 20 - 6)

    # One-way shear per metre, ACI 22.5.5.1 (c): λs = 1 for d = 125 (√(2 / 1.5) > 1).
    rho = area / (1000 * 125)
    phi_vc, lambda_s = one_way_shear(rho, 125, 24.1)
    assert lambda_s == 1.0
    assert phi_vc == pytest.approx(0.75 * 0.66 * rho ** (1 / 3) * math.sqrt(24.1) * 1000 * 125)


def _one_point(mx: float, my: float, mxy: float = 0.0) -> list[ShellPoint]:
    """One shell with one integration point carrying the moments [kN·m/m] (no shear)."""
    forces = [np.array([[mx * 1e3, my * 1e3, mxy * 1e3, 0.0, 0.0]])]
    return [ShellPoint(1, "S1", [np.array([1.0, 1.0, 0.0])], forces)]


def _mesh(**layers: tuple[float, float]) -> PlanarReinforcement:
    data = {n: {"dia": dia, "spacing": s} for n, (dia, s) in layers.items()}
    return PlanarReinforcement.model_validate({**MESH, **data})


def _run(system: str, h: float, mesh: PlanarReinforcement, shells) -> dict[str, dict]:
    checks = slab_checks(system, h, mesh, 25, 420, 200000, shells, ["U"], SlabContext())
    return {c["name"]: c for c in checks}


def test_min_reinforcement_only_near_tension_faces_and_as_a_total() -> None:
    # 150 one-way slab spanning X, light top Y bars with no demand on them: As,min = 270 mm²/m
    # is needed in the tension layer of the span (bottom X: 524) and as a total each way
    # (Y: 524 + 251), not in the top Y layer alone (251).
    mesh = _mesh(bottomX=(10, 150), bottomY=(10, 150), topX=(10, 150), topY=(8, 200))
    checks = _run("oneWay", 150, mesh, _one_point(5, 0.5))
    minimum = checks["Min. reinforcement (ACI 7.6.1.1, 8.6.1.1)"]
    assert minimum["ok"] and minimum["demand"] == pytest.approx(270)
    assert minimum["capacity"] == pytest.approx(BAR10 * 1000 / 150, rel=1e-3)
    assert "one-way slab spanning X" in minimum["note"]
    # Too little in total across the span (T8 @ 400 top and bottom: 2 x 126 < 270) fails.
    thin = _mesh(bottomX=(10, 150), bottomY=(8, 400), topY=(8, 400))
    minimum = _run("oneWay", 150, thin, _one_point(5, 0.5))[
        "Min. reinforcement (ACI 7.6.1.1, 8.6.1.1)"
    ]
    assert not minimum["ok"] and "total Y" in minimum["note"]
    # A two-way slab hogging in Y needs As,min in its top Y bars.
    hogging = _run("twoWay", 150, mesh, _one_point(5, -3))
    minimum = hogging["Min. reinforcement (ACI 7.6.1.1, 8.6.1.1)"]
    assert not minimum["ok"] and "topY (tension face)" in minimum["note"]
    assert minimum["capacity"] == pytest.approx(math.pi * 16 * 1000 / 200, rel=1e-3)


def test_max_spacing_of_one_way_distribution_bars() -> None:
    # 100 one-way slab spanning X: main bars at most min(3h, 450) = 300 mm, the distribution
    # bars across the span min(5h, 450) = 450 mm (ACI 7.7.6.2.1, 24.4.3.3).
    mesh = _mesh(bottomX=(10, 200), bottomY=(8, 350))
    spacing = _run("oneWay", 100, mesh, _one_point(5, 0.3))["Max. spacing"]
    assert spacing["ok"] and spacing["capacity"] == 450 and spacing["demand"] == 350
    # The span is told by the demand: spanning Y, the 350 mm bars are the main ones.
    spacing = _run("oneWay", 100, mesh, _one_point(0.3, 5))["Max. spacing"]
    assert not spacing["ok"] and spacing["capacity"] == 300 and "bottomY" in spacing["note"]
    # Two-way: min(2h, 450) = 200 mm everywhere.
    spacing = _run("twoWay", 100, mesh, _one_point(5, 3))["Max. spacing"]
    assert not spacing["ok"] and spacing["capacity"] == 200


def _grid(size: float, step: float, field) -> list[ShellPoint]:
    """Square Q4 shells ``step`` [mm] over a ``size`` square slab, their 2 x 2 Gauss points
    carrying ``field(x, y)`` -> (mx, my, mxy) [kN·m/m] (no shear)."""
    shells = []
    count = round(size / step)
    for i in range(count):
        for j in range(count):
            corners = [
                np.array([x, y, 0.0]) * step / 1e3
                for x, y in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))
            ]
            points = integration_points(corners, 4)
            values = [[*(v * 1e3 for v in field(*p[:2] * 1e3)), 0.0, 0.0] for p in points]
            shells.append(ShellPoint(len(shells) + 1, f"S1#{len(shells) + 1}", points, [values]))
    for shell in shells:
        shell.forces = [np.asarray(f, dtype=float) for f in shell.forces]
    return shells


SQUARE = [(0.0, 0.0), (4000.0, 0.0), (4000.0, 4000.0), (0.0, 4000.0)]


def test_a_uniform_field_averages_to_its_pointwise_value() -> None:
    shells = _grid(4000, 500, lambda x, y: (10.0, -4.0, 1.5))
    context = SlabContext(boundary=SQUARE)
    checks = slab_checks("twoWay", 150, planar(), 25, 420, 200000, shells, ["U"], context)
    found = {c["name"]: c for c in checks}
    expected = wood_armer(10.0, -4.0, 1.5)  # pointwise, the same everywhere
    for k, name in enumerate(("bottom X", "bottom Y", "top X", "top Y")):
        demand = found.get(f"Flexure {name} (Wood-Armer)", {"demand": 0.0})["demand"]
        assert demand == pytest.approx(expected[k], abs=0.01)
    # No columns: no grid, so 1 m strips each way, and a note that says so.
    assert {s.kind for s in context.strips} == {"strip"}
    assert all(s.width == pytest.approx(1000) for s in context.strips)
    assert any("no column grid" in note for note in context.notes)


def test_a_narrow_spike_is_averaged_over_the_strip_width_by_hand() -> None:
    # Points 250 mm apart across a 1 m strip: each stands for 250 mm, a 20 kN·m/m spike on one
    # of them averages to 20 x 250 / 1000 = 5.
    strip = Strip("X", "strip", "test", 0.0, 1000.0, 0.0, 1000.0, 1000.0)
    across = np.array([125.0, 375.0, 625.0, 875.0] * 2)
    along = np.array([400.0] * 4 + [600.0] * 4)
    values = np.where(across == 375.0, 20.0, 0.0)[:, None]
    averages = strip_average(strip, along, across, values, 500.0)
    assert averages and all(a[1][0] == pytest.approx(5.0) for a in averages)
    # Uneven spacing: half way to the neighbours, and at most ``reach`` beyond the outermost.
    weights = strip_weights(np.array([100.0, 300.0, 800.0]), 0.0, 1000.0, 500.0)
    assert weights == pytest.approx([200.0, 350.0, 450.0])
    weights = strip_weights(np.array([300.0, 300.0, 600.0]), 0.0, 1000.0, 100.0)
    assert weights == pytest.approx([125.0, 125.0, 250.0])  # 200-450 shared, 450-700
    # Through slab_checks: a 20 kN·m/m sagging spike along one 500 mm wide row of shells of a
    # 4 m slab without a grid, in 1 m strips: 20 x 500 / 1000 = 10 kN·m/m.
    shells = _grid(4000, 500, lambda x, y: (20.0 if 1000 < y < 1500 else 0.0, 0.0, 0.0))
    found = {
        c["name"]: c
        for c in slab_checks(
            "twoWay", 150, planar(), 25, 420, 200000, shells, ["U"], SlabContext(boundary=SQUARE)
        )
    }
    assert found["Flexure bottom X (Wood-Armer)"]["demand"] == pytest.approx(10.0)
    assert "X strip y = 1.00 to 2.00 m" in found["Flexure bottom X (Wood-Armer)"]["note"]


def _columns(xs: list[float], ys: list[float]) -> list[ColumnJoint]:
    return [
        ColumnJoint(f"C{k + 1}", (x, y), 400, 400, 0.0)
        for k, (y, x) in enumerate((y, x) for y in ys for x in xs)
    ]


def test_strip_geometry_of_a_two_by_two_bay_flat_slab_by_hand() -> None:
    # Bays of 6 m along x and 4 m along y: column strips 0.25 min(l1, l2) = 1 m each side of
    # a column line both ways (only the inside half at the edges), middle strips between, and
    # bays from column face to column face (400 mm columns).
    frame = PlanFrame(plan_axes())
    columns = _columns([0, 6000, 12000], [0, 4000, 8000])
    extent = (0.0, 12000.0, 0.0, 8000.0)
    x = design_strips("X", frame, extent, columns, [], 500).strips
    assert {(s.start, s.end, s.span) for s in x} == {(200, 5800, 6000), (6200, 11800, 6000)}
    first = [(s.kind, s.lo, s.hi) for s in x if s.start == 200]
    assert first == [
        ("column", 0, 1000),
        ("middle", 1000, 3000),
        ("column", 3000, 5000),
        ("middle", 5000, 7000),
        ("column", 7000, 8000),
    ]
    assert x[2].name == "X column strip on the line of C4, C5, C6 (y = 4.00 m)"
    y = design_strips("Y", frame, extent, columns, [], 500).strips
    first = [(s.kind, s.lo, s.hi) for s in y if s.start == 200]
    assert first == [
        ("column", 0, 1000),
        ("middle", 1000, 5000),
        ("column", 5000, 7000),
        ("middle", 7000, 11000),
        ("column", 11000, 12000),
    ]
    # Square bays of 5 m (the flat slab of the analysed tests): 1.25 m each side.
    square = design_strips(
        "X", frame, (0, 10000, 0, 10000), _columns([0, 5000, 10000], [0, 5000, 10000]), [], 500
    ).strips
    assert [(s.kind, s.lo, s.hi) for s in square if s.start == 200] == [
        ("column", 0, 1250),
        ("middle", 1250, 3750),
        ("column", 3750, 6250),
        ("middle", 6250, 8750),
        ("column", 8750, 10000),
    ]
    # A slab running 1.5 m past its last column line along the strips: the overhang is a bay
    # of its own; across them (1.5 m past y = 10 m), the edge column strip reaches 1.25 m into
    # the overhang and the last 0.25 m is a middle strip.
    over = design_strips(
        "X", frame, (0, 11500, 0, 11500), _columns([0, 5000, 10000], [0, 5000, 10000]), [], 500
    ).strips
    assert {(s.start, s.end) for s in over} == {(200, 4800), (5200, 9800), (10200, 11500)}
    assert [(s.kind, s.lo, s.hi) for s in over if s.start == 200][-2:] == [
        ("column", 8750, 11250),
        ("middle", 11250, 11500),
    ]


@pytest.mark.parametrize("mesh", [500.0, 1000.0])
def test_face_stations_keep_the_shear_of_an_interior_support(mesh: float) -> None:
    # A 10 x 5 m slab on 300 mm beams along Y at x = 0, 5 and 10 m: two 5 m spans along X,
    # the exact shear of a uniform load q = 1 (per mm): 3/8 q L at the outer supports and
    # 5/8 q L either side of the inner one. Its face stations must not reach past the beam's
    # centre line into the next span, where the shear has the other sign.
    frame = PlanFrame(plan_axes())
    beams = [LineSupport(f"B{k}", (x, 0.0), (x, 5000.0), 300) for k, x in enumerate((0, 5e3, 1e4))]
    layout = design_strips("X", frame, (0, 10000, 0, 5000), [], beams, mesh)
    assert layout.note and {(s.start, s.end, s.before, s.after) for s in layout.strips} == {
        (150, 4850, 150, 150),
        (5150, 9850, 150, 150),
    }

    def shear(x: np.ndarray) -> np.ndarray:
        return np.where(x <= 5000, 1875 - x, (10000 - x) - 1875)

    # The 2 x 2 Gauss points of square shells ``mesh`` wide, all of the same area.
    g = mesh / 2 * (1 - 1 / math.sqrt(3))
    rows = np.concatenate([[k * mesh + g, (k + 1) * mesh - g] for k in range(round(1e4 / mesh))])
    cols = np.concatenate([[k * mesh + g, (k + 1) * mesh - g] for k in range(round(5e3 / mesh))])
    along, across = (a.ravel() for a in np.meshgrid(rows, cols, indexing="ij"))
    values = shear(along)[:, None]
    strip = next(s for s in layout.strips if s.start == 150 and s.lo == 0)
    averages = dict(strip_average(strip, along, across, values, mesh, areas=np.ones(len(along))))
    assert averages[150][0] == pytest.approx(1725, rel=1e-6)
    assert averages[4850][0] == pytest.approx(-2975, rel=1e-6)  # 1875 - 4850
    # Without areas (points in rows, weighted by width across) the same.
    averages = dict(strip_average(strip, along, across, values, mesh))
    assert averages[4850][0] == pytest.approx(-2975, rel=1e-6)


def test_a_row_of_shells_out_of_line_is_one_position_along() -> None:
    # The middle strip of the one-bay frame's slab on its 625 mm mesh: 600 x 625 shells, the
    # mesh estimated at 612.4 mm, rows of four shells across 600 mm apart along. The row at
    # x = 3.3 m is out of line by 4-10 mm, across the edge of a quarter-mesh step (21.5 x
    # 153.1 = 3291.6 mm): counted as two positions, a parabola through the two rows next to the
    # station at x = 3 m bent to the 1 mm scatter (20 kN·m/m from 7.5). A field constant along
    # the strip averages to its mean across at every station (the row's scatter tilts a fit by
    # 0.002 %; through two positions counted as three: 3.56 and 11.58 either side of the row).
    strip = Strip("X", "middle", "test", 1250.0, 3750.0, 200.0, 5800.0, 6000.0, 200.0, 200.0)
    across = np.tile([1562.5, 2187.5, 2812.5, 3437.5], 10)
    along = np.repeat(300.0 + 600.0 * np.arange(10), 4)
    along[20:24] += [-5.0, -9.0, -4.0, -10.0]  # 3295, 3291, 3296, 3290 mm
    values = np.where(np.isin(across, [2187.5, 2812.5]), 7.9, 7.2)[:, None]
    averages = strip_average(strip, along, across, values, 612.4, areas=np.ones(len(along)))
    assert [at for at, _ in averages] == pytest.approx(200.0 + 560.0 * np.arange(11))
    assert all(value[0] == pytest.approx(7.55, rel=1e-4) for _, value in averages)


def test_a_wall_supports_the_slabs_at_its_top_not_one_it_stands_on() -> None:
    from types import SimpleNamespace

    from saengine.design.check import _line_supports
    from saengine.library.bim import WallElement
    from saengine.library.objects import Wall

    wall = WallElement(id="W1", type="W", start=(0, 0), end=(5000, 0), bottom=3000, top=6000)
    types = {"W": Wall(id="W", name="Wall", material="C25", thickness=200)}
    found = _line_supports(SimpleNamespace(elements=[wall]), types, [3000.0, 4500.0, 6000.0])
    # Standing on the slab at 3 m (a transfer slab): no support line there.
    assert sorted(found) == [4500, 6000]
    assert found[6000][0].width == 200 and found[6000][0].id == "W1"


def test_punching_of_an_interior_and_an_edge_column_by_hand() -> None:
    big = [(-5000, -5000), (5000, -5000), (5000, 5000), (-5000, 5000)]
    section = critical_section((0, 0), 400, 400, 0, 125, big)
    assert section.location == "interior" and section.alpha_s == 40
    assert section.b0 == pytest.approx(4 * 525)
    capacity = punching_capacity(24.1, 125, section.b0, 1.0, section.alpha_s)
    root = math.sqrt(24.1)
    expected = (0.33 * root, 0.17 * 3 * root, 0.083 * (2 + 40 * 125 / 2100) * root)
    assert capacity.expressions == pytest.approx(expected)
    assert capacity.vc == pytest.approx(0.33 * root)  # (a) governs
    # Size effect for d = 300: λs = √(2 / 2.2).
    deep = punching_capacity(24.1, 300, 4 * 700, 1.0, 40)
    assert deep.lambda_s == pytest.approx(math.sqrt(2 / 2.2))
    assert deep.vc == pytest.approx(0.33 * math.sqrt(2 / 2.2) * root)

    # Moment transfer (ACI R8.4.4.2.3): Jc = d b1³/6 + b1 d³/6 + d b2 b1²/2, c = b1/2.
    b1 = b2 = 525.0
    jc, reach = section.polar(along_u=True)
    assert jc == pytest.approx(125 * b1**3 / 6 + b1 * 125**3 / 6 + 125 * b2 * b1**2 / 2)
    assert reach == pytest.approx(b1 / 2)
    vu, m = 300e3, 40e6
    stress = punching_stress(section, vu, m, 0.0)
    gamma_v = 1 - 1 / (1 + 2 / 3)
    assert stress.gamma_v[0] == pytest.approx(gamma_v)
    assert stress.vu == pytest.approx(vu / (2100 * 125) + gamma_v * m * (b1 / 2) / jc)

    # A column on the slab's edge x = 0: the outer side is cut away (three sides).
    edge = critical_section(
        (0, 0), 400, 400, 0, 125, [(0, -5000), (5000, -5000), (5000, 5000), (0, 5000)]
    )
    assert edge.location == "edge" and edge.alpha_s == 30
    assert edge.b0 == pytest.approx(525 + 2 * 262.5)


# ─────────────────────────────────── shell axes vs. the solver ───────────────────────────────────


def _imposed_bending(points: list[tuple[float, float]], formulation: str) -> np.ndarray:
    """OpenSees shell forces of one element bent to w = a x² / 2 (global; sagging: the bottom
    stretches), Poisson's ratio 0: Mxx = -D a in OpenSees' sign (the +3 face stretches)."""
    a = 1e-3
    return _imposed(points, formulation, lambda x, y: [0, 0, a * x * x / 2, 0.0, -a * x, 0.0])


def _imposed(points: list[tuple[float, float]], formulation: str, field) -> np.ndarray:
    """OpenSees shell forces (rows of 8 per integration point) of one element whose nodes
    (in the given order) are moved to ``field(x, y)`` (six global DOFs)."""
    import openseespy.opensees as ops

    ops.wipe()
    ops.model("basic", "-ndm", 3, "-ndf", 6)
    for k, (x, y) in enumerate(points, 1):
        ops.node(k, x, y, 0.0)
    ops.section("ElasticMembranePlateSection", 1, 30e9, 0.0, 0.2, 0.0)
    ops.element(formulation, 1, *range(1, len(points) + 1), 1)
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    for k, (x, y) in enumerate(points, 1):
        for dof, value in enumerate(field(x, y), 1):
            ops.sp(k, dof, value)
    ops.system("BandGeneral")
    ops.numberer("Plain")
    ops.constraints("Penalty", 1e16, 1e16)
    ops.integrator("LoadControl", 1.0)
    ops.algorithm("Linear")
    ops.analysis("Static")
    ops.analyze(1)
    rows = np.array(ops.eleResponse(1, "stresses")).reshape(-1, 8)
    ops.wipe()
    return rows


@pytest.mark.parametrize(
    ("points", "formulation"),
    [
        ([(0, 0), (1, 0.2), (1.3, 1.1), (-0.2, 0.9)], "ASDShellQ4"),
        ([(0, 0), (1, 0.364), (0.6, 1.2), (-0.3, 0.8)], "ASDShellQ4"),
        ([(0, 0), (1, 0.364), (0.2, 1)], "ASDShellT3"),
    ],
)
def test_shell_axes_and_slab_moments_follow_the_solver(
    points: list[tuple[float, float]], formulation: str
) -> None:
    rows = _imposed_bending(points, formulation)
    d = 30e9 * 0.2**3 / 12
    sagging = d * 1e-3  # N·m/m
    corners = [np.array([x, y, 0.0]) for x, y in points]
    axes = shell_axes(corners)
    # The solver's local moments are the global tensor diag(-D a, 0) turned into our axes.
    e1, e2 = axes[0][:2], axes[1][:2]
    expected = [-sagging * e1[0] ** 2, -sagging * e2[0] ** 2, -sagging * e1[0] * e2[0]]
    assert rows[:, 3:6].mean(axis=0) == pytest.approx(expected, rel=1e-3, abs=1e-6 * sagging)
    # Back in a slab's axes the moment is sagging along x, and follows the slab's local x when
    # it is turned to global Y (the bending is then about the slab's y layers).
    forces = slab_forces(rows, axes, plan_axes())
    assert forces[:, :3].mean(axis=0) == pytest.approx([sagging, 0, 0], abs=1e-6 * sagging)
    turned = outline_axes([(0, 0, 0), (0, 1000, 0), (-1000, 1000, 0)])
    assert turned is not None and turned.x == pytest.approx([0, 1, 0])
    forces = slab_forces(rows, axes, turned)
    assert forces[:, :3].mean(axis=0) == pytest.approx([0, sagging, 0], abs=1e-6 * sagging)
    # A shell whose normal points down (nodes listed clockwise): the solver reports moments of
    # the opposite sign about its flipped axes; the slab moments are the same physical state.
    order = [0, *reversed(range(1, len(points)))]
    flipped_points = [points[k] for k in order]
    flipped_rows = _imposed_bending(flipped_points, formulation)
    flipped = [corners[k] for k in order]
    assert shell_axes(flipped)[2] == pytest.approx([0, 0, -1])
    forces = slab_forces(flipped_rows, shell_axes(flipped), plan_axes())
    assert forces[:, :3].mean(axis=0) == pytest.approx([sagging, 0, 0], abs=1e-6 * sagging)
    forces = slab_forces(flipped_rows, shell_axes(flipped), turned)
    assert forces[:, :3].mean(axis=0) == pytest.approx([0, sagging, 0], abs=1e-6 * sagging)
    assert len(integration_points(corners, len(rows))) == len(rows)


def test_integration_point_order_follows_the_solver() -> None:
    # A rectangle turned 30° in plan, bent to w = a (s² t + s t²) / 2 in its own axes (s along
    # side 1-2 from node 1, t across): the curvatures κss = a t and κtt = a s vary linearly,
    # and the element's bilinear rotations reproduce them exactly, so M11 = -D a t and
    # M22 = -D a s (ν = 0, OpenSees' sign) differ at every Gauss point and tell their order.
    a = 1e-3
    d = 30e9 * 0.2**3 / 12
    turn = math.radians(30)
    ex = np.array([math.cos(turn), math.sin(turn)])
    ey = np.array([-math.sin(turn), math.cos(turn)])
    origin = np.array([1.0, 0.5])
    plan = [origin, origin + 2 * ex, origin + 2 * ex + 1.2 * ey, origin + 1.2 * ey]
    points = [(float(p[0]), float(p[1])) for p in plan]

    def field(x: float, y: float) -> list[float]:
        s, t = (np.array([x, y]) - origin) @ ex, (np.array([x, y]) - origin) @ ey
        w = a * (s * s * t + s * t * t) / 2
        grad = ex * a * (s * t + t * t / 2) + ey * a * (s * s / 2 + s * t)
        return [0, 0, w, float(grad[1]), float(-grad[0]), 0]  # rx = ∂w/∂y, ry = -∂w/∂x

    rows = _imposed(points, "ASDShellQ4", field)
    corners = [np.array([x, y, 0.0]) for x, y in points]
    e1, e2, _ = shell_axes(corners)
    assert e1[:2] == pytest.approx(ex) and e2[:2] == pytest.approx(ey)
    gauss = integration_points(corners, len(rows))
    assert len(gauss) == len(rows) == 4
    for row, p in zip(rows, gauss, strict=True):
        s, t = (p[:2] - origin) @ ex, (p[:2] - origin) @ ey
        assert row[3] == pytest.approx(-d * a * t, rel=1e-6)
        assert row[4] == pytest.approx(-d * a * s, rel=1e-6)
    # ASDShellT3's moments are constant over the element (so the order of its points does not
    # change the design); the rule: the point nearest corner k comes k-th.
    triangle = [np.array(q, float) for q in ((0, 0, 0), (3, 0, 0), (0, 3, 0))]
    assert np.array(integration_points(triangle, 3)) == pytest.approx(
        np.array([[0.5, 0.5, 0], [2, 0.5, 0], [0.5, 2, 0]])
    )


# ─────────────────────────────────────── analysed slabs ───────────────────────────────────────

#: L and Lr factored alike, so a roof slab and the same area drawn with live load compare.
COMBINATION = LoadCombination(name="1.2D + 1.6L + 1.6Lr", D=1.2, L=1.6, Lr=1.6)


def shell_settings(name: str, mesh: float = 500):
    """Shell slabs at ``mesh`` exactly (no span rule), without end offsets: the slab checks
    against hand statics (the columns' rigid-zone self-weight would be in the nodal totals)."""
    s = default_project_settings(name)
    analysis = {"slabs": "shells", "meshSize": mesh, "meshBySpan": False, "endOffsets": False}
    return s.model_copy(
        update={
            "combinations": [COMBINATION],
            "analysis": s.analysis.model_copy(update=analysis),
        }
    )


def objects(slab: dict, columns: bool = True, beam_depth: float = 500) -> ObjectLibrary:
    data = OBJECTS.model_dump(mode="json", by_alias=True)
    for o in data["objects"]:
        if o["id"] == "BM":
            o["reinforcement"] = beam_reinforcement(top=3).model_dump(mode="json")
            o["profile"]["yDim"] = beam_depth
        if o["id"] == "COL" and columns:
            o["reinforcement"] = COLUMN_REINFORCEMENT.model_dump(mode="json")
        if o["id"] == "SL":
            o.update(slab)
    return ObjectLibrary.model_validate(data)


def analyse(root: Path, building, library: ObjectLibrary, settings) -> dict:
    """Writes the project, runs the static cases and returns the design report."""
    materials = default_material_library()
    d = derive_fem(building, library, materials, settings, {"bim": "abc"})
    files = {
        "02 Project Settings/project-settings.json": settings.model_dump_json(by_alias=True),
        "03 Materials/materials.json": materials.model_dump_json(by_alias=True),
        "04 Objects/objects.json": library.model_dump_json(by_alias=True),
        "06 BIM/bim.json": building.model_dump_json(by_alias=True),
        "08 FEM/model.osmodel": json.dumps(d.project),
    }
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    static = [a["id"] for a in d.project["analyses"] if a.get("type", "Static") == "Static"]
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(root / "08 FEM" / "model.osmodel"),
            "--cases",
            *map(str, static),
            "--out",
            str(root / "08 FEM" / "model.results"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    report = design_report(root / "08 FEM" / "model.results", root / "08 FEM" / "model.osmodel")
    json.dumps(report)
    return report


def narrow_plan() -> FloorPlan:
    """The one-bay frame at 6 m along X by 2.5 m along Y: its slab spans one way, along Y."""
    data = PLAN.model_dump(mode="json", by_alias=True)
    data["grids"]["y"] = [{"label": "1", "position": 0.0}, {"label": "2", "position": 2500.0}]
    return FloorPlan.model_validate(data)


def checks_of(report: dict, element: str) -> dict[str, dict]:
    found = next(e for e in report["elements"] if e["id"] == element)
    return {c["name"]: c for c in found["checks"]}


@pytest.fixture(scope="module")
def one_way(tmp_path_factory: pytest.TempPathFactory) -> dict:
    # Deep (1 m) beams: shallow 6 m beams deflect enough to bend the slab along X with them.
    slab = {"thickness": 150, "system": "oneWay", "reinforcement": planar().model_dump(mode="json")}
    building = generate(narrow_plan(), "s")
    return analyse(
        tmp_path_factory.mktemp("oneway"),
        building,
        objects(slab, beam_depth=1000),
        shell_settings("One way"),
    )


def test_one_way_slab_sags_along_its_span(one_way: dict) -> None:
    slab = next(e for e in one_way["elements"] if e["id"] == "S1")
    assert slab["kind"] == "slab" and slab["type"] == "SL" and len(slab["members"]) > 20
    checks = checks_of(one_way, "S1")
    bottom_x, bottom_y = (
        checks["Flexure bottom X (Wood-Armer)"],
        checks["Flexure bottom Y (Wood-Armer)"],
    )
    # Spanning 2.5 m along Y: the Y bars carry the sagging, at midspan (y = 1.25 m).
    assert bottom_y["demand"] > 1.4 * bottom_x["demand"] > 0
    assert bottom_y["combination"] == COMBINATION.name
    y = float(bottom_y["note"].split("at (")[1].split(",")[1].strip(" )m"))
    assert abs(y - 1.25) < 0.5, bottom_y["note"]
    # Bounded by the simply supported and the fixed-ended strip: q l² / 8 and q l² / 24.
    # Roof: self-weight, finishes 1.5 kPa (SD) and roof live load 1 kPa (Lr).
    q = 1.2 * (2400 * 9.80665 * 0.15 / 1e3 + 1.5) + 1.6 * 1.0  # kPa
    assert q * 2.5**2 / 24 < bottom_y["demand"] < q * 2.5**2 / 8
    assert bottom_y["unit"] == "kN·m/m" and bottom_y["ok"]
    for name in ("One-way shear", "Min. reinforcement (ACI 7.6.1.1, 8.6.1.1)", "Max. spacing"):
        assert checks[name]["ok"], checks[name]
    thickness = checks["Min. thickness (Table 7.3.1.1)"]
    assert thickness["flag"] and thickness["demand"] == pytest.approx(2500 / 20)
    # 4 beams, 4 columns and the slab; the summary's own totals also count the joints and the
    # building's seismic checks (PR #30, X4).
    assert one_way["summary"]["elements"]["checked"] == 9


def test_slab_axes_follow_a_drawn_area_first_edge(
    one_way: dict, tmp_path_factory: pytest.TempPathFactory
) -> None:
    # The same slab drawn as an area whose first edge runs along global Y: its local x is
    # global Y, so the span's sagging is now on its X bars.
    slab = {"thickness": 150, "system": "oneWay", "reinforcement": planar().model_dump(mode="json")}
    settings = shell_settings("Area")
    building = generate(narrow_plan(), "s")
    plan_slab = next(e for e in building.elements if e.id == "S1")
    z = plan_slab.elevation
    (x0, y0), (x1, _), (_, y1) = plan_slab.boundary[0], plan_slab.boundary[1], plan_slab.boundary[2]
    area = AreaElement(
        id="S1",
        type="SL",
        outline=[(x0, y0, z), (x0, y1, z), (x1, y1, z), (x1, y0, z)],
        areaLoad=settings.roofLoad,
    )
    elements = [area if e.id == "S1" else e for e in building.elements]
    report = analyse(
        tmp_path_factory.mktemp("area"),
        building.model_copy(update={"elements": elements}),
        objects(slab, beam_depth=1000),
        settings,
    )
    turned = checks_of(report, "S1")
    plan = checks_of(one_way, "S1")
    span = turned["Flexure bottom X (Wood-Armer)"]["demand"]
    across = turned["Flexure bottom Y (Wood-Armer)"]["demand"]
    assert span > 1.4 * across
    assert span == pytest.approx(plan["Flexure bottom Y (Wood-Armer)"]["demand"], rel=0.05)
    assert across == pytest.approx(
        plan["Flexure bottom X (Wood-Armer)"]["demand"], rel=0.05, abs=0.2
    )


def test_slab_without_top_bars_fails_in_hogging(tmp_path_factory: pytest.TempPathFactory) -> None:
    slab = {
        "thickness": 150,
        "system": "twoWay",
        "reinforcement": planar(top=False).model_dump(mode="json"),
    }
    report = analyse(
        tmp_path_factory.mktemp("notop"),
        generate(PLAN, "s"),
        objects(slab),
        shell_settings("No top"),
    )
    checks = checks_of(report, "S1")
    hogging = [c for name, c in checks.items() if name.startswith("Flexure top")]
    assert hogging and all(not c["ok"] and c["capacity"] == 0 for c in hogging)
    assert all("top bars are needed" in c["note"] for c in hogging)
    slab_entry = next(e for e in report["elements"] if e["id"] == "S1")
    assert not slab_entry["ok"] and slab_entry["utilisation"] == 99.0
    assert checks["Flexure bottom X (Wood-Armer)"]["ok"]
    assert checks["Min. thickness (Table 8.3.1.2)"]["flag"]
    assert report["summary"]["failed"] >= 1


@pytest.mark.parametrize("slabs", ["shells", "loadsToBeams"])
def test_the_gathered_checks_tell_the_report_of_slabs_without_bars(
    slabs: str, tmp_path_factory: pytest.TempPathFactory
) -> None:
    # Run All designs the members once: the checks gathered with assumed slab bars give the
    # report design_report makes alone, the slab without bars left out of it.
    from saengine.design.required import gather

    settings = shell_settings("No bars")
    settings = settings.model_copy(
        update={"analysis": settings.analysis.model_copy(update={"slabs": slabs})}
    )
    root = tmp_path_factory.mktemp(f"nobars-{slabs}")
    report = analyse(root, generate(PLAN, "s"), objects({"reinforcement": None}), settings)
    gathered = gather(root / "08 FEM" / "model.results", root / "08 FEM" / "model.osmodel")
    assert gathered.assumed == {"SL"} and gathered.plain == report
    assert any(e["id"] == "S1" for e in gathered.report["elements"])
    assert not any(e["id"] == "S1" for e in report["elements"])
    if slabs == "shells":
        assert report["summary"]["noBars"] == ["SL"]
    else:
        assert "S1: slab not designed (no reinforcement, not analysed as shells)" in report["notes"]


def flat_plan(bays: int = 2) -> FloorPlan:
    """``bays`` by ``bays`` bays of 5 m (two by default: nine columns), 400 x 400 columns, a
    flat slab and no beams."""
    xs, ys = "ABCDE"[: bays + 1], "12345"[: bays + 1]
    data = PLAN.model_dump(mode="json", by_alias=True)
    data["grids"] = {
        "x": [{"label": k, "position": 5000.0 * i} for i, k in enumerate(xs)],
        "y": [{"label": k, "position": 5000.0 * i} for i, k in enumerate(ys)],
    }
    data["columns"] = [
        {
            "id": f"C{(bays + 1) * j + i + 1}",
            "type": "COL",
            "at": {"x": x, "y": y},
            "base": "BASE",
            "top": "L1",
        }
        for j, y in enumerate(ys)
        for i, x in enumerate(xs)
    ]
    data["beams"] = []
    first, last = (xs[0], ys[0]), (xs[-1], ys[-1])
    data["slabs"][0]["boundary"] = [
        {"x": x, "y": y} for x, y in (first, (last[0], first[1]), last, (first[0], last[1]))
    ]
    return FloorPlan.model_validate(data)


def test_flat_slab_punching_at_every_column(tmp_path_factory: pytest.TempPathFactory) -> None:
    slab = {
        "thickness": 200,
        "system": "flat",
        "reinforcement": planar(dia=12).model_dump(mode="json"),
    }
    building = generate(flat_plan(), "s")
    root = tmp_path_factory.mktemp("flat")
    report = analyse(root, building, objects(slab), shell_settings("Flat"))
    checks = checks_of(report, "S1")
    punching = {name.split()[-1]: c for name, c in checks.items() if name.startswith("Punching")}
    assert sorted(punching) == sorted(f"C{k}" for k in range(1, 10))
    assert "interior column" in punching["C5"]["note"]
    assert "corner column" in punching["C1"]["note"] and "edge column" in punching["C2"]["note"]
    # The interior column's critical section: d = 200 - 20 - 12 (mean of the top layers'
    # 174 and 162 mm) = 168 mm, b0 = 4 (400 + 168).
    assert "b0 = 2272 mm, d = 168 mm" in punching["C5"]["note"]

    # Vu of all columns together carries the whole factored slab load (no beams).
    project = json.loads((root / "08 FEM" / "model.osmodel").read_text(encoding="utf-8"))
    factors = {"D": 1.2, "SD": 1.2, "L": 1.6, "Lr": 1.6}
    total = sum(
        factors.get(p["name"], 0.0) * -sum(n["forces"][2] for n in p["nodal_loads"])
        for p in project["load_patterns"]
        if p["type"] == "Plain"
    )
    shares = [float(c["note"].split("Vu = ")[1].split(" kN")[0]) for c in punching.values()]
    assert sum(shares) * 1e3 == pytest.approx(total, rel=2e-3)
    # The interior column takes the largest share, about a quarter of the slab or more.
    assert max(shares) == pytest.approx(shares[list(punching).index("C5")])
    assert 0.2 < shares[list(punching).index("C5")] * 1e3 / total < 0.45
    thickness = checks["Min. thickness (Table 8.3.1.1)"]
    assert thickness["flag"] and thickness["demand"] == pytest.approx((5000 - 400) / 30, rel=1e-3)


def _static_moments(
    sections: list[StripSection], start: float, end: float, lo: float, hi: float
) -> tuple[float, float, float]:
    """Of the X strips of the bay from ``start`` to ``end`` [mm], over the width from ``lo`` to
    ``hi`` across: Σ width x (midspan + mean of the two face moments) [N·m], with the signed
    strip moments (sagging - mean hogging), with the Wood-Armer ones (bottom + mean top), and
    the hogging part alone (mean top)."""
    signed = designed = hogging = 0.0
    bay = [s for s in sections if s.strip.direction == "X" and s.strip.start == start]
    for strip in dict.fromkeys(s.strip for s in bay):
        width = (min(strip.hi, hi) - max(strip.lo, lo)) / 1e3  # m
        if width <= 0:
            continue
        at = {s.at: s for s in bay if s.strip == strip}
        stations = sorted(at)

        def midspan(value: str, at: dict = at, stations: list = stations) -> float:
            # Linear between the stations either side of midspan.
            return float(
                np.interp((start + end) / 2, stations, [getattr(at[k], value)[0] for k in stations])
            )

        a, b = at[start], at[end]
        signed += width * (midspan("moment") - (a.moment[0] + b.moment[0]) / 2)
        designed += width * (midspan("bottom") + (a.top[0] + b.top[0]) / 2)
        hogging += width * (a.top[0] + b.top[0]) / 2
    return signed, designed, hogging


@pytest.mark.parametrize("mesh", [500, 1000])
def test_strip_moments_of_an_interior_panel_add_up_to_the_static_moment(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch, mesh: float
) -> None:
    """Equilibrium (ACI 8.10.3.2) through the design itself (its strips, mesh estimate and
    stations), at the tests' mesh and at the default 1 m: of the interior panel of a 3 x 3 bay
    flat slab (half column strip + middle strip + half column strip across, between the column
    faces along x), the strip averages of mx times their widths give midspan sagging + the
    mean hogging at the two faces = M0 = qu l2 ln² / 8; the whole slab's width gives B ln² / 8,
    which statics of the free body between the faces requires."""
    from saengine.design import slab as slab_module

    contexts: list[SlabContext] = []
    original = slab_module.slab_checks

    def capture(*args, **kwargs):
        contexts.append(args[-1])
        return original(*args, **kwargs)

    slab = {"thickness": 200, "system": "flat", "reinforcement": planar(dia=12).model_dump()}
    root = tmp_path_factory.mktemp("static")
    building = generate(flat_plan(3), "s")
    monkeypatch.setattr(slab_module, "slab_checks", capture)
    report = analyse(root, building, objects(slab), shell_settings("Static", mesh))
    assert any(e["id"] == "S1" for e in report["elements"]) and len(contexts) == 1
    sections = contexts[0].sections

    project = json.loads((root / "08 FEM" / "model.osmodel").read_text(encoding="utf-8"))
    factors = {"D": 1.2, "SD": 1.2, "L": 1.6, "Lr": 1.6}
    load = sum(
        factors.get(p["name"], 0.0) * -sum(n["forces"][2] for n in p["nodal_loads"])
        for p in project["load_patterns"]
        if p["type"] == "Plain"
    )
    qu = load / 15.0**2  # N/m²
    m0 = qu * 5.0 * 4.6**2 / 8  # one panel
    # The whole width (three panels): a statics identity, short only by the sampling of the
    # face moments at points near (not at) the faces.
    whole, _, _ = _static_moments(sections, 5200, 9800, 0, 15000)
    signed, designed, hogging = _static_moments(sections, 5200, 9800, 5000, 10000)
    # Measured: 0.965 (mesh 500) and 0.975 (1000).
    assert 0.93 * 3 * m0 < whole < 1.03 * 3 * m0
    # The interior panel (its two half column strips at their strips' averages): 1.015, 1.021.
    assert signed == pytest.approx(m0, rel=0.07)
    # The Wood-Armer moments (pointwise |mxy| added, then averaged) are at least the signed
    # ones: the design is not short of statics; and the hogging takes its share (ACI's direct
    # design method gives 0.65 M0 at an interior support; measured 0.79 at both meshes).
    assert signed <= designed < 1.25 * m0
    assert hogging > 0.7 * m0


def test_two_way_slab_on_beams_passes_under_gravity(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    # The one-bay frame (6 x 5 m on 300 x 500 beams), 150 mm two-way slab, T10 @ 150 each layer,
    # at the tests' mesh and at the default 1 m.
    slab = {"thickness": 150, "system": "twoWay", "reinforcement": planar().model_dump()}
    reports = {
        mesh: analyse(
            tmp_path_factory.mktemp("twoway"),
            generate(PLAN, "s"),
            objects(slab),
            shell_settings("2", mesh),
        )
        for mesh in (500, 1000)
    }
    flexure = [f"Flexure {face} {d} (Wood-Armer)" for face in ("bottom", "top") for d in "XY"]
    fine, coarse = (checks_of(reports[m], "S1") for m in (500, 1000))
    for name in flexure:
        # The strip averages depend little on the mesh (shells' means, faces by a fit), and
        # are not lower at the default mesh. Measured (500 -> 1000): bottom X 7.72 -> 7.36,
        # bottom Y 7.75 -> 7.72, top X 4.40 -> 5.17, top Y 3.85 -> 4.22 kN·m/m.
        assert 0.9 < coarse[name]["demand"] / fine[name]["demand"] < 1.25, name
    # The shear of the edge column strips beside the corner columns is about twice as high at
    # 1 m (10.97 -> 21.54 kN/m: a 1 m shell next to the corner carries the corner's shear),
    # conservative and still well below φVc.
    shear = "One-way shear"
    assert coarse[shear]["demand"] >= 0.9 * fine[shear]["demand"] and coarse[shear]["ok"]
    report = reports[500]
    entry = next(e for e in report["elements"] if e["id"] == "S1")
    checks = checks_of(report, "S1")
    assert entry["ok"], [(c["name"], c["utilisation"]) for c in entry["checks"]]
    q = 1.2 * (2400 * 9.80665 * 0.15 / 1e3 + 1.5) + 1.6 * 1.0  # kPa, as in the one-way test
    for name in ("Flexure bottom X (Wood-Armer)", "Flexure bottom Y (Wood-Armer)"):
        # Between a fixed (ACI coefficient ~0.02-0.04) and a simply supported 5 m strip.
        assert 0.02 * q * 5**2 < checks[name]["demand"] < q * 5**2 / 8, checks[name]
        assert "middle strip" in checks[name]["note"]
    for name in ("Flexure top X (Wood-Armer)", "Flexure top Y (Wood-Armer)"):
        assert checks[name]["ok"] and "strip" in checks[name]["note"]
    # Column strips on the beam lines, 0.25 min(6, 5) = 1.25 m (inside half at the edges).
    strips = entry["strips"]
    edge = next(s for s in strips if s["name"].startswith("X column strip on the line of B1"))
    assert edge["kind"] == "column"
    assert edge["outline"] == [[0.2, 0.0], [5.8, 0.0], [5.8, 1.25], [0.2, 1.25]]
    assert sum(s["kind"] == "middle" for s in strips) == 2


def test_strip_moments_of_a_mesh_with_rows_out_of_line(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    # The two-way slab of the one-bay frame at 600 and 625 mm: the 625 mm shells (600 x 625,
    # 80 quads) have rows whose centres scatter by up to 10 mm along, which once counted as two
    # positions and bent a station's parabola (see the test of a row out of line).
    slab = {"thickness": 150, "system": "twoWay", "reinforcement": planar().model_dump()}
    fine, coarse = (
        checks_of(
            analyse(
                tmp_path_factory.mktemp("rows"),
                generate(PLAN, "s"),
                objects(slab),
                shell_settings("2", mesh),
            ),
            "S1",
        )
        for mesh in (600, 625)
    )
    for name in (f"Flexure {face} {d} (Wood-Armer)" for face in ("bottom", "top") for d in "XY"):
        # Measured (600 -> 625): bottom X 7.66 -> 7.74, bottom Y 7.80 -> 7.82, top X 4.68 ->
        # 4.55, top Y 3.93 -> 3.90 kN·m/m (at 625 before: 20.21, 11.35, 4.55, 10.05).
        assert coarse[name]["demand"] == pytest.approx(fine[name]["demand"], rel=0.1), name

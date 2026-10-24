"""Steel member design (saengine.design.steel) against hand calculations to BNBC 2020 Part 6
Chapter 10: a rolled H column in compression (Fcr by hand), a beam's lateral-torsional
buckling (Lp, Lr, Mn with Cb), an SHS brace in tension and compression, the H1 interaction,
slender-element sections (Q), and the bracing and Cb read from a model.

The sections are synthetic plate assemblies (no proprietary table is used); the references are
plain arithmetic written out here, none of the module's helpers used for them. Units: mm, MPa,
N, N·mm.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.design.check import _Piece
from saengine.design.steel import classify as cl
from saengine.design.steel.lengths import (
    LengthOptions,
    MemberLengths,
    cb_factor,
    cb_from_diagram,
    member_lengths,
)
from saengine.design.steel.members import (
    Stations,
    Steel,
    SteelDesignError,
    check_member,
    compression,
    design_steel_member,
    flexure_major,
    flexure_minor,
    interaction,
    moment_coefficient,
    shear_major,
    tension_rupture,
    tension_yielding,
)
from saengine.design.steel.properties import angle, channel, chs, i_shape, rhs, shape_properties
from saengine.library.materials import Material
from saengine.library.objects import Brace, IShapeProfile, RectangleHollowProfile

E = 200_000.0
A992 = Steel(345.0, 450.0, E, "A992")
A36 = Steel(250.0, 400.0, E, "A36")
REL = 1e-6


def fcr_by_hand(fe: float, fy: float, q: float = 1.0) -> float:
    return q * 0.658 ** (q * fy / fe) * fy if fe >= 0.44 * q * fy else 0.877 * fe


# ───────────────────────────────── section properties ─────────────────────────────────


def test_i_shape_properties_by_hand():
    d, bf, tf, tw = 308.0, 305.0, 15.4, 9.9
    s = i_shape(d, bf, tf, tw)
    hw = d - 2 * tf
    assert s.area == pytest.approx(2 * bf * tf + hw * tw, rel=REL)
    assert s.ix == pytest.approx((bf * d**3 - (bf - tw) * hw**3) / 12, rel=REL)
    assert s.iy == pytest.approx(2 * tf * bf**3 / 12 + hw * tw**3 / 12, rel=REL)
    assert s.zx == pytest.approx(bf * tf * (d - tf) + tw * hw**2 / 4, rel=1e-6)
    assert s.zy == pytest.approx(tf * bf**2 / 2 + hw * tw**2 / 4, rel=1e-6)
    assert s.cw == pytest.approx(tf * bf**3 * (d - tf) ** 2 / 24, rel=REL)


def test_hollow_and_open_shapes():
    box = rhs(150, 150, 8)
    assert box.area == pytest.approx(150**2 - 134**2)
    assert box.ix == pytest.approx((150**4 - 134**4) / 12)
    assert box.zx == pytest.approx((150**3 - 134**3) / 4)
    assert box.dims["b"] == pytest.approx(150 - 3 * 8)  # corner radius not known
    tube = chs(168.3, 7.1)
    inner = 168.3 - 14.2
    assert tube.ix == pytest.approx(math.pi / 64 * (168.3**4 - inner**4))
    assert tube.zx == pytest.approx((168.3**3 - inner**3) / 6)
    eq = angle(100, 100, 10)
    assert eq.area == pytest.approx(100 * 10 + 90 * 10)
    # Equal-leg angle: the principal axes are at 45°, Iz = Ix - |Ixy|.
    assert eq.iz < eq.ix and eq.ix == pytest.approx(eq.iy)
    ch = channel(200, 75, 11.5, 8.5)
    assert ch.x0 < 0  # the shear centre lies behind the web
    # ERW HSS: design wall thickness 0.93 t (Sec 10.2.3.12).
    p = RectangleHollowProfile(xDim=150, yDim=150, wallThickness=8)
    assert shape_properties(p).dims["t"] == pytest.approx(0.93 * 8)
    assert shape_properties(p, erw=False).dims["t"] == pytest.approx(8)


# ───────────────────────────────────── compression ─────────────────────────────────────


def test_rolled_h_column_flexural_buckling_by_hand():
    """A 308 x 305 H column (a UC 305x305x97 / W12 class shape), 4 m, K = 1, Fy = 345 MPa."""
    d, bf, tf, tw = 308.0, 305.0, 15.4, 9.9
    s = i_shape(d, bf, tf, tw)
    area = 2 * bf * tf + (d - 2 * tf) * tw  # 12 138 mm²
    iy = 2 * tf * bf**3 / 12 + (d - 2 * tf) * tw**3 / 12
    ry = math.sqrt(iy / area)  # 77.5 mm
    kl_r = 4000 / ry  # 51.6
    fe = math.pi**2 * E / kl_r**2  # 740 MPa
    assert fe >= 0.44 * 345
    fcr = 0.658 ** (345 / fe) * 345  # Eq 6.10.17: 284 MPa
    cap = compression(s, A992, 4000, 4000)
    assert cap.design == pytest.approx(0.9 * fcr * area, rel=1e-9)
    assert cap.design / 1e3 == pytest.approx(3101, abs=3)
    assert "flexural buckling about y" in cap.state
    assert "6.10.16" in cap.clause
    # Elastic range (Eq 6.10.18): 12 m.
    long = compression(s, A992, 12000, 12000)
    fe_long = math.pi**2 * E / (12000 / ry) ** 2
    assert fe_long < 0.44 * 345
    assert long.design == pytest.approx(0.9 * 0.877 * fe_long * area, rel=1e-9)


def test_slender_web_column_qa_by_hand():
    """A welded-like I 600 x 200, 5 mm web: h/tw = 115 > 1.49 √(E/Fy): Qa from Eq 6.10.52."""
    d, bf, tf, tw = 600.0, 200.0, 12.0, 5.0
    s = i_shape(d, bf, tf, tw)
    fy = 345.0
    h = d - 2 * tf
    area = 2 * bf * tf + h * tw
    assert h / tw > 1.49 * math.sqrt(E / fy)
    iy = 2 * tf * bf**3 / 12 + h * tw**3 / 12
    kl = 3000.0
    fe = math.pi**2 * E / (kl / math.sqrt(iy / area)) ** 2
    f = fcr_by_hand(fe, fy)  # Fcr at Q = 1
    root = math.sqrt(E / f)
    be = min(h, 1.92 * tw * root * (1 - 0.34 / (h / tw) * root))
    qa = (area - (h - be) * tw) / area
    # The flange: b/t = 8.33 < 0.56 √(E/Fy) = 13.5, Qs = 1.
    fcr = fcr_by_hand(fe, fy, qa)
    cap = compression(s, A992, kl, kl)
    assert cap.design == pytest.approx(0.9 * fcr * area, rel=1e-9)
    assert "Q = Qs Qa" in cap.note and "10.5.7" in cap.clause


def test_slender_flange_qs_by_hand():
    s = i_shape(300, 300, 8, 10)  # b/t = 18.75 > 0.56 √(E/Fy) = 13.5
    fy, r = 345.0, math.sqrt(E / 345.0)
    ratio = 150 / 8
    assert 0.56 * r < ratio < 1.03 * r
    qs = 1.415 - 0.74 * ratio / r  # Eq 6.10.40
    area = s.area
    fe = math.pi**2 * E / (2500 / s.ry) ** 2
    cap = compression(s, A992, 2500, 2500)
    assert cap.design == pytest.approx(0.9 * fcr_by_hand(fe, fy, qs) * area, rel=1e-9)


def test_slender_rhs_wall_iterates_to_eq_6_10_53():
    s = rhs(300, 300, 6)  # b/t = 47 > 1.40 √(E/Fy) = 33.7
    cap = compression(s, A992, 3000, 3000)
    # The fixed point: f = Pn / Aeff with be of Eq 6.10.53.
    q = float(cap.note.split("(iterated), Qa = ")[1].split(";")[0])
    area, t, b = s.area, 6.0, s.dims["b"]
    fe = math.pi**2 * E / (3000 / s.rx) ** 2
    fcr = fcr_by_hand(fe, 345.0, q)
    f = fcr / q
    root = math.sqrt(E / f)
    be = min(b, 1.92 * t * root * (1 - 0.38 / (b / t) * root))
    assert (area - 4 * (b - be) * t) / area == pytest.approx(q, abs=2e-3)
    assert q < 1


def test_channel_and_angle_compression():
    ch = channel(200, 75, 11.5, 8.5)
    cap = compression(ch, A36, 3000, 3000)
    flexural_y = 0.9 * fcr_by_hand(math.pi**2 * E / (3000 / ch.ry) ** 2, 250) * ch.area
    assert cap.design <= flexural_y + 1e-6
    eq = angle(75, 75, 8)
    cap = compression(eq, A36, 2000, 2000)
    lr = 2000 / eq.ry
    kl_r = 72 + 0.75 * lr if lr <= 80 else 32 + 1.25 * lr  # Eqs 6.10.31-32
    assert cap.design == pytest.approx(
        0.9 * fcr_by_hand(math.pi**2 * E / kl_r**2, 250) * eq.area, rel=1e-9
    )
    assert "10.5.5" in cap.clause


# ─────────────────────────────────────── flexure ───────────────────────────────────────


def _ipe400():
    return i_shape(400, 180, 13.5, 8.6)


def test_beam_lateral_torsional_buckling_by_hand():
    """An IPE 400 class beam, A36, Lb = 6 m: inelastic LTB (Eq 6.10.57)."""
    d, bf, tf, tw = 400.0, 180.0, 13.5, 8.6
    fy = 250.0
    hw = d - 2 * tf
    area = 2 * bf * tf + hw * tw
    ix = (bf * d**3 - (bf - tw) * hw**3) / 12
    iy = 2 * tf * bf**3 / 12 + hw * tw**3 / 12
    sx = ix / (d / 2)
    zx = bf * tf * (d - tf) + tw * hw**2 / 4
    j = (2 * bf * tf**3 + hw * tw**3) / 3
    ho = d - tf
    cw = tf * bf**3 * ho**2 / 24
    ry = math.sqrt(iy / area)
    rts = math.sqrt(math.sqrt(iy * cw) / sx)
    lp = 1.76 * ry * math.sqrt(E / fy)  # Eq 6.10.60
    jc = j / (sx * ho)
    lr = (
        1.95
        * rts
        * E
        / (0.7 * fy)
        * math.sqrt(jc)
        * math.sqrt(1 + math.sqrt(1 + 6.76 * (0.7 * fy / E / jc) ** 2))
    )  # Eq 6.10.61
    mp = fy * zx
    lb = 6000.0
    assert lp < lb < lr
    for cb in (1.0, 1.136):
        mn = min(mp, cb * (mp - (mp - 0.7 * fy * sx) * (lb - lp) / (lr - lp)))
        cap = flexure_major(_ipe400(), A36, lb, cb)
        assert cap.design == pytest.approx(0.9 * mn, rel=1e-9)
        assert cap.state == "lateral-torsional buckling"
    # Elastic LTB beyond Lr (Eq 6.10.58-59).
    lb = 1.5 * lr
    fcr = math.pi**2 * E / (lb / rts) ** 2 * math.sqrt(1 + 0.078 * jc * (lb / rts) ** 2)
    assert flexure_major(_ipe400(), A36, lb, 1.0).design == pytest.approx(0.9 * fcr * sx, rel=1e-9)
    # Braced: the plastic moment.
    assert flexure_major(_ipe400(), A36, 0.0).design == pytest.approx(0.9 * mp, rel=1e-9)


def test_cb_uniform_load():
    # Simply supported, uniform load: MA = MC = 0.75 Mmax, MB = Mmax.
    assert cb_factor(1.0, 0.75, 1.0, 0.75) == pytest.approx(12.5 / 11)
    s = np.linspace(0, 6, 61)
    m = 4 * s * (6 - s) / 36  # parabola, 1.0 at mid-span
    assert cb_from_diagram(s, m, 0, 6) == pytest.approx(12.5 / 11, rel=1e-6)
    # Uniform moment: 1.0; linear to zero: 1.67.
    assert cb_from_diagram(s, np.ones_like(s), 0, 6) == pytest.approx(1.0)
    assert cb_from_diagram(s, s / 6, 0, 6) == pytest.approx(12.5 / (2.5 + 0.75 + 2 + 2.25))


def test_noncompact_flange_flb():
    s = i_shape(300, 300, 12, 10)  # bf/2tf = 12.5 between 0.38 and 1.0 √(E/Fy) at 345 MPa
    flange = cl.flexure_elements(s, 345, E, "x")[0]
    assert flange.cls == cl.NONCOMPACT
    mp, sx = 345 * s.zx, s.sx
    mn = mp - (mp - 0.7 * 345 * sx) * (flange.ratio - flange.lambda_p) / (
        flange.lambda_r - flange.lambda_p
    )
    cap = flexure_major(s, A992, 0.0)
    assert cap.design == pytest.approx(0.9 * mn, rel=1e-9)
    assert "6.10.64" in cap.clause
    minor = flexure_minor(s, A992)
    assert "6.10.92" in minor.clause


def test_hss_flexure_and_shear():
    box = rhs(150, 150, 8)
    cap = flexure_major(box, A992, 6000)  # no LTB for HSS
    assert cap.design == pytest.approx(0.9 * 345 * box.zx, rel=1e-9)
    v = shear_major(box, A992)
    h = 150 - 3 * 8
    assert v.design == pytest.approx(0.9 * 0.6 * 345 * 2 * h * 8, rel=1e-9)
    w = shear_major(_ipe400(), A36)  # rolled, h/tw = 43 < 2.24 √(E/Fy): φv = 1.0
    assert w.phi == 1.0 and w.design == pytest.approx(0.6 * 250 * 400 * 8.6)


# ───────────────────────────────────── SHS brace ─────────────────────────────────────


def test_shs_brace_tension_and_compression_by_hand():
    """SHS 150 x 8 (SAW: nominal t) brace, 6.8 m between work points, Fy = 345, Fu = 450."""
    box = rhs(150, 150, 8)
    area = 150**2 - 134**2  # 4544 mm²
    r = math.sqrt((150**4 - 134**4) / 12 / area)  # 58.1 mm
    length = math.hypot(6000, 3200)  # 6800 mm
    fe = math.pi**2 * E / (length / r) ** 2  # 143.6 MPa < 0.44 Fy: elastic
    assert fe < 0.44 * 345
    cap = compression(box, A992, length, length)
    assert cap.design == pytest.approx(0.9 * 0.877 * fe * area, rel=1e-9)
    assert cap.design / 1e3 == pytest.approx(515.9, abs=1.5)
    assert tension_yielding(box, A992).design == pytest.approx(0.9 * 345 * area)
    xbar = (150**2 + 2 * 150 * 150) / (4 * 300)  # Table 6.10.2 Case 6
    u = 1 - xbar / 150
    assert tension_rupture(box, A992).design == pytest.approx(0.75 * 450 * area * u)


# ───────────────────────────────────── interaction ─────────────────────────────────────


def test_h1_interaction_by_hand():
    assert interaction(600, 1000, 100, 400, 0, 100) == (
        pytest.approx(0.6 + 8 / 9 * 0.25),
        "Eq 6.10.147a",
    )
    assert interaction(100, 1000, 100, 400, 20, 100)[0] == pytest.approx(0.05 + 0.25 + 0.2)


def _stations(p: float, mx: float, length: float = 4.0, n: int = 11) -> Stations:
    s = np.linspace(0, length, n)
    return Stations(
        "1.2D+1.6L",
        s,
        np.full(n, p),
        np.full(n, mx),
        np.zeros(n),
        np.zeros(n),
        np.zeros(n),
        [f"C1 at {k / (n - 1):.2f} L" for k in range(n)],
    )


def test_column_combined_with_b1_by_hand():
    d, bf, tf, tw = 308.0, 305.0, 15.4, 9.9
    s = i_shape(d, bf, tf, tw)
    lengths = MemberLengths.simple(4.0)
    p, m = 1500e3, 200e6  # uniform moment: single curvature, Cm = 1.0
    checks = {c["name"]: c for c in check_member(s, A992, [_stations(p, m)], lengths, "column")}
    pc = compression(s, A992, 4000, 4000).design
    mc = flexure_major(s, A992, 4000, 1.0).design
    pe1 = math.pi**2 * E * s.ix / 4000**2
    b1 = 1.0 / (1 - p / pe1)
    expected = p / pc + 8 / 9 * (m * b1 / mc)
    h1 = checks["Axial force and flexure (H1)"]
    assert h1["utilisation"] == pytest.approx(expected, abs=1e-3)
    assert "6.10.147a" in h1["clause"]
    assert checks["Compression: buckling"]["capacity"] == pytest.approx(pc / 1e3, abs=0.01)
    assert checks["Slenderness KL/r (compression)"]["demand"] == pytest.approx(
        4000 / s.ry, abs=0.01
    )
    assert checks["K = 1 by first-order analysis (αPr ≤ 0.5 Py)"]["flag"]


def test_moment_coefficient_sign():
    s = np.linspace(0, 4, 11)
    assert moment_coefficient(s, np.ones_like(s), 0, 4) == pytest.approx(1.0)  # single
    assert moment_coefficient(s, 1 - s / 2, 0, 4) == pytest.approx(0.2)  # reverse, equal
    assert moment_coefficient(s, s * (4 - s), 0, 4) == 1.0  # transverse load


def test_slenderness_limits_and_tension_only_member():
    box = rhs(100, 100, 4)
    lengths = MemberLengths.simple(8.0)
    checks = {c["name"]: c for c in check_member(box, A992, [_stations(-100e3, 0.0, 8.0)], lengths)}
    assert "Compression: buckling" not in checks
    lr = checks["Slenderness L/r (tension)"]
    assert lr["capacity"] == 300 and lr["demand"] == pytest.approx(8000 / box.rx, abs=0.01)
    checks = {c["name"]: c for c in check_member(box, A992, [_stations(10e3, 0.0, 8.0)], lengths)}
    assert checks["Slenderness KL/r (compression)"]["capacity"] == 150
    assert not checks["Slenderness KL/r (compression)"]["ok"]  # 8000 / 39 = 205


# ───────────────────────────────── bracing from a model ─────────────────────────────────


def _beam_project():
    """A 6 m beam B1 along X in 4 elements, columns at its ends, a cross beam B2 at mid-span
    and a slab meeting it at 1.5 m and 4.5 m."""
    xs = [0.0, 1.5, 3.0, 4.5, 6.0]
    nodes = [
        {"id": i + 1, "coords": [x, 0.0, 3.0], "restraint": [False] * 6} for i, x in enumerate(xs)
    ]
    nodes += [
        {"id": 10, "coords": [0.0, 0.0, 0.0], "restraint": [True] * 6},
        {"id": 11, "coords": [6.0, 0.0, 0.0], "restraint": [True] * 6},
        {"id": 12, "coords": [3.0, 4.0, 3.0], "restraint": [False] * 6},
        {"id": 13, "coords": [1.5, 2.0, 3.0], "restraint": [False] * 6},
        {"id": 14, "coords": [4.5, 2.0, 3.0], "restraint": [False] * 6},
    ]
    names = ["B1", "B1#2", "B1#3", "B1#4"]
    elements = [
        {"id": k + 1, "name": names[k], "type": "ElasticBeamColumn", "nodes": [k + 1, k + 2]}
        for k in range(4)
    ]
    elements += [
        {"id": 5, "name": "C1", "type": "ElasticBeamColumn", "nodes": [10, 1]},
        {"id": 6, "name": "C2", "type": "ElasticBeamColumn", "nodes": [11, 5]},
        {"id": 7, "name": "B2", "type": "ElasticBeamColumn", "nodes": [3, 12]},
        {"id": 8, "name": "S1", "type": "Shell", "nodes": [2, 13, 14, 4]},
    ]
    axes = np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]])
    pieces = [
        _Piece(
            names[k],
            k + 1,
            1.5,
            True,
            axes,
            [np.zeros((11, 6))],
            start=np.array([xs[k], 0, 3.0]),
            end=np.array([xs[k + 1], 0, 3.0]),
        )
        for k in range(4)
    ]
    return {"nodes": nodes, "elements": elements}, pieces


def test_bracing_from_the_model():
    project, pieces = _beam_project()
    lengths = member_lengths(project, pieces)
    assert lengths.length == pytest.approx(6.0)
    assert lengths.x.points == [0.0, 6.0]  # nothing braces it vertically between the columns
    # Sideways: the cross beam at 3 m, the slab at 1.5 and 4.5 m.
    assert lengths.y.points == pytest.approx([0.0, 1.5, 3.0, 4.5, 6.0])
    assert lengths.ltb_top.points == pytest.approx([0.0, 1.5, 3.0, 4.5, 6.0])
    assert lengths.ltb_bottom.points == pytest.approx([0.0, 3.0, 6.0])  # the slab braces the top
    no_slab = member_lengths(project, pieces, options=LengthOptions(slab_braces_top_flange=False))
    assert no_slab.ltb_top.points == pytest.approx([0.0, 3.0, 6.0])
    assert lengths.effective("x", 2.0) == (1.0, pytest.approx(6000.0), False)


def _cantilever(with_slab: bool):
    """A 3 m cantilever B1 along X from a column top at x = 0; optionally a slab panel meeting
    the beam at its root and its tip."""
    nodes = [
        {"id": 1, "coords": [0.0, 0.0, 3.0], "restraint": [False] * 6},
        {"id": 2, "coords": [3.0, 0.0, 3.0], "restraint": [False] * 6},
        {"id": 10, "coords": [0.0, 0.0, 0.0], "restraint": [True] * 6},
        {"id": 11, "coords": [0.0, 2.0, 3.0], "restraint": [False] * 6},
        {"id": 12, "coords": [3.0, 2.0, 3.0], "restraint": [False] * 6},
    ]
    elements = [
        {"id": 1, "name": "B1", "type": "ElasticBeamColumn", "nodes": [1, 2]},
        {"id": 2, "name": "C1", "type": "ElasticBeamColumn", "nodes": [10, 1]},
    ]
    if with_slab:
        elements.append({"id": 3, "name": "S1", "type": "Shell", "nodes": [1, 2, 12, 11]})
    piece = _Piece(
        "B1",
        1,
        3.0,
        True,
        np.eye(3),
        [np.zeros((11, 6))],
        start=np.array([0, 0, 3.0]),
        end=np.array([3.0, 0, 3.0]),
    )
    return {"nodes": nodes, "elements": elements}, [piece]


@pytest.mark.parametrize("with_slab", [False, True])
def test_cantilever_tip_with_a_slab_is_free_for_hogging_ltb(with_slab):
    """Sec 10.6.1: Cb = 1.0 where the free end is unbraced. A slab at the tip braces only the
    top (tension) flange under hogging, so the tip stays free for LTB of the bottom flange and
    about x (K = 2); it does brace the top flange and the y-axis."""
    project, pieces = _cantilever(with_slab)
    lengths = member_lengths(project, pieces)
    assert lengths.ltb_bottom.free_end and not lengths.ltb_bottom.free_start
    assert lengths.x.free_end
    assert lengths.effective("x", 1.5)[0] == 2.0
    assert lengths.ltb_top.free_end != with_slab
    assert lengths.y.free_end != with_slab
    s = np.linspace(0, 3, 11)
    m = (3 - s) ** 2 / 2 * 40e6 / 4.5  # hogging (stretches the top), 40 kN·m at the support
    z = np.zeros(11)
    st = Stations("D", s, z, m, z, z, z, ["B1"] * 11)
    shape = i_shape(300, 150, 9, 6.5)
    checks = {c["name"]: c for c in check_member(shape, A36, [st], lengths, "beam")}
    mx = next(c for n, c in checks.items() if n.startswith("Flexure about x"))
    by_hand = flexure_major(shape, A36, 3000.0, 1.0, top_compression=False).design / 1e6
    assert mx["capacity"] == pytest.approx(by_hand, abs=0.01)


def test_continuous_beam_is_braced_over_interior_columns():
    """A beam drawn as one member over three columns: the interior column braces it in every
    direction, as the end columns do."""
    nodes = [
        {"id": i + 1, "coords": [x, 0.0, 3.0], "restraint": [False] * 6}
        for i, x in enumerate([0.0, 6.0, 12.0])
    ]
    nodes += [
        {"id": 10 + i, "coords": [x, 0.0, 0.0], "restraint": [True] * 6}
        for i, x in enumerate([0.0, 6.0, 12.0])
    ]
    elements = [
        {"id": 1, "name": "B1", "type": "ElasticBeamColumn", "nodes": [1, 2]},
        {"id": 2, "name": "B1#2", "type": "ElasticBeamColumn", "nodes": [2, 3]},
    ]
    elements += [
        {"id": 3 + i, "name": f"C{i}", "type": "ElasticBeamColumn", "nodes": [10 + i, 1 + i]}
        for i in range(3)
    ]
    pieces = [
        _Piece(
            n,
            k + 1,
            6.0,
            True,
            np.eye(3),
            [np.zeros((11, 6))],
            start=np.array([6.0 * k, 0, 3.0]),
            end=np.array([6.0 * (k + 1), 0, 3.0]),
        )
        for k, n in enumerate(["B1", "B1#2"])
    ]
    lengths = member_lengths({"nodes": nodes, "elements": elements}, pieces)
    for seg in (lengths.x, lengths.y, lengths.ltb_top, lengths.ltb_bottom):
        assert seg.points == pytest.approx([0.0, 6.0, 12.0])


def test_station_at_a_brace_point_is_checked_with_both_segments():
    """Brace points at 0, 2 and 8 m; the moment peaks at 2 m and falls to 0 at 0 and 8 m.
    The 2-8 m segment (Lb = 6 m, Cb = 1.67) governs at the peak, not the 0-2 m one."""
    lengths = MemberLengths.simple(8.0, y=[2.0])
    assert lengths.ltb_top.around_all(2.0) == [(0.0, 2.0, False), (2.0, 8.0, False)]
    assert lengths.effective("y", 2.0) == (1.0, pytest.approx(6000.0), False)
    s = np.linspace(0, 8, 41)
    m = np.where(s <= 2, s / 2, (8 - s) / 6) * 150e6  # sagging: top flange in compression
    m = -m  # negative Mx compresses the top flange
    z = np.zeros_like(s)
    st = Stations("D", s, z, m, z, z, z, ["B1"] * len(s))
    shape = _ipe400()
    checks = {c["name"]: c for c in check_member(shape, A36, [st], lengths, "beam")}
    mx = next(c for n, c in checks.items() if n.startswith("Flexure about x"))
    cb = cb_from_diagram(s, m, 2.0, 8.0)
    by_hand = flexure_major(shape, A36, 6000.0, cb, top_compression=True).design
    assert mx["demand"] == pytest.approx(150.0, abs=0.01)
    assert mx["capacity"] == pytest.approx(by_hand / 1e6, abs=0.01)


def test_rhs_shear_lag_takes_the_worse_gusset_plane():
    """Table 6.10.2 Case 6 with l = H: H is in the plane of the connection. RHS 200 x 100
    (yDim 200): U = 0.79 with the gusset on the 200 mm side, 0.33 on the 100 mm side."""
    box = rhs(100, 200, 6)
    b, h = box.dims["B"], box.dims["H"]
    assert (b, h) == (100, 200)

    def u(b: float, h: float) -> float:
        return 1 - (b * b + 2 * b * h) / (4 * (b + h)) / h

    assert u(100, 200) == pytest.approx(1 - 41.667 / 200, abs=1e-4)
    assert u(200, 100) == pytest.approx(1 - 66.667 / 100, abs=1e-4)
    cap = tension_rupture(box, A992)
    assert cap.design == pytest.approx(0.75 * 450 * box.area * u(200, 100), rel=1e-9)
    assert "100 mm side" in cap.note


def test_design_steel_member_brace_entry():
    """An SHS brace from the analysis pieces: compression in one combination, tension in the
    other; the entry has the design report's keys."""
    axes = np.array([[6.0, 0, 3.2], [0, 1.0, 0], [-3.2, 0, 6.0]])
    axes[0] /= np.linalg.norm(axes[0])
    axes[2] /= np.linalg.norm(axes[2])
    forces_c = np.zeros((11, 6))
    forces_c[:, 0] = -300e3  # N: compression
    forces_t = np.zeros((11, 6))
    forces_t[:, 0] = 400e3
    piece = _Piece(
        "M2",
        1,
        6.8,
        True,
        axes,
        [forces_c, forces_t],
        start=np.array([0.0, 0, 0]),
        end=np.array([6.0, 0, 3.2]),
    )
    brace = Brace(
        id="BR",
        name="SHS",
        material="A572-50",
        profile=RectangleHollowProfile(xDim=150, yDim=150, wallThickness=8),
    )
    material = Material.model_validate(
        {
            "id": "A572-50",
            "name": "A572",
            "category": "steel",
            "mechanical": {"E": 200000},
            "steel": {"grade": "A572", "fy": 345, "fu": 450},
        }
    )
    entry = design_steel_member("M2", "brace", "BR", brace, material, [piece], ["C", "T"])
    names = [c["name"] for c in entry["checks"]]
    assert "Compression: buckling" in names and "Tension: rupture (net section)" in names
    comp = next(c for c in entry["checks"] if c["name"] == "Compression: buckling")
    assert comp["combination"] == "C" and comp["demand"] == pytest.approx(300.0)
    assert all({"clause", "flag", "ok", "utilisation"} <= set(c) for c in entry["checks"])
    assert "0.93" in comp["note"]  # ERW design wall thickness noted
    assert entry["section"]["family"] == "rhs"
    with pytest.raises(SteelDesignError):
        design_steel_member(
            "M2",
            "brace",
            "BR",
            brace.model_copy(
                update={
                    "profile": IShapeProfile(
                        overallWidth=100, overallDepth=200, webThickness=5, flangeThickness=8
                    )
                }
            ),
            None,
            [piece],
            ["C"],
        )


@pytest.mark.parametrize(
    "shape",
    [
        i_shape(400, 180, 13.5, 8.6),
        i_shape(900, 300, 16, 6),  # slender web in flexure (Sec 10.6.5)
        i_shape(900, 300, 16, 8),  # noncompact web at 345 MPa (Sec 10.6.4)
        channel(200, 75, 11.5, 8.5),
        angle(100, 75, 8),
        rhs(200, 100, 6),
        chs(168.3, 5),
    ],
    ids=lambda s: s.label,
)
def test_every_family_checks_tension_compression_and_bending(shape):
    lengths = MemberLengths.simple(4.0, y=[2.0])
    n = 11
    s = np.linspace(0, 4, n)
    m = 20e6 * np.sin(np.pi * s / 4)
    both = [
        Stations(
            "C", s, np.full(n, 200e3), m, 0.2 * m, np.full(n, 30e3), np.full(n, 5e3), ["x"] * n
        ),
        Stations(
            "T", s, np.full(n, -200e3), -m, -0.2 * m, np.full(n, -30e3), np.zeros(n), ["x"] * n
        ),
    ]
    checks = check_member(shape, A992, both, lengths, "column")
    names = {c["name"] for c in checks}
    assert {
        "Compression: buckling",
        "Tension: rupture (net section)",
        "Axial force and flexure (H1)",
    } <= names
    for c in checks:
        assert math.isfinite(c["utilisation"]) and c["capacity"] > 0, c
        assert c["clause"].startswith("BNBC 2020 Part 6"), c


def test_web_classes_pick_the_flexure_section():
    assert "10.6.5" in flexure_major(i_shape(900, 300, 16, 6), A992, 3000).clause
    assert "10.6.4" in flexure_major(i_shape(900, 300, 16, 8), A992, 0).clause

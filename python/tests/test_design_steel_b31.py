"""B31: steel member torsion and the remaining member limit states, against hand calculations
with the values of the bnbc2020 code pack (``steel.members``): HSS torsion and its interaction
(Sec 10.8.3.1-10.8.3.2), the stresses of open sections under torsion (Sec 10.8.3.3) by warping
torsion, single angles about their principal axes (Sec 10.8.2), built-up members (Sec 10.5.6),
rectangular bars and rounds (Sec 10.6.11), unsymmetrical shapes (Sec 10.6.12) and stiffened webs
with tension field action (Sec 10.7.3). Units: mm, MPa, N, N·mm.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.design.overwrites import resolve, steel_options
from saengine.design.steel import torsion as tor
from saengine.design.steel.built_up import BuiltUp, dimensional_checks, modified_slenderness
from saengine.design.steel.lengths import MemberLengths
from saengine.design.steel.members import (
    Stations,
    Steel,
    angle_principal,
    check_member,
    compression,
    flexure_major,
    flexure_minor,
    flexure_unsymmetric,
    shear_major,
    stiffener_requirements,
    unsymmetric_interaction,
    web_shear_coefficient,
)
from saengine.design.steel.properties import (
    angle,
    bar,
    chs,
    i_shape,
    rhs,
    round_bar,
    shape_properties,
)
from saengine.library.objects import CircleProfile, RectangleProfile

E = 200_000.0
G = 77_200.0
FY = 345.0
STEEL = Steel(FY, 450.0, E, "A992")


def _stations(n=21, length=6.0, p=0.0, mx=None, vy=0.0, torque=None):
    s = np.linspace(0, length, n)
    z = np.zeros(n)
    return Stations(
        "C",
        s,
        np.full(n, p),
        z if mx is None else mx,
        z,
        np.full(n, vy),
        z,
        [f"at {x:.2f} m" for x in s],
        None if torque is None else torque,
    )


# ─────────────────────────────────────── the pack ───────────────────────────────────────


def test_pack_values_with_their_clauses():
    m = code_context.table("steel").members
    # Sec 10.8.3.1 (part2 p. 103): φT 0.90; Sec 10.8.3.2: torsion neglected below 20 % of Tc.
    assert m.torsion.phi == 0.9 and m.torsion.neglect == 0.2
    # Eqs 6.10.151-154 (part2 pp. 103-104).
    assert (m.torsion.roundLong, m.torsion.roundShort) == (1.23, 0.6)
    assert (m.torsion.rectYield, m.torsion.rectInelastic, m.torsion.rectMaxRatio) == (
        2.45,
        3.07,
        260.0,
    )
    assert m.torsion.rectElastic == 0.458
    # Eqs 6.10.156-157: Fn = Fy and 0.6 Fy.
    assert (m.torsion.normalYield, m.torsion.shearYield) == (1.0, 0.6)
    # Sec 10.5.6 (part2 pp. 64-66).
    b = m.builtUp
    assert (b.welded, b.componentShare) == (0.82, 0.75)
    assert (b.plateSpacing, b.plateSpacingMax, b.plateStaggered, b.plateStaggeredMax) == (
        0.75,
        305.0,
        1.12,
        460.0,
    )
    assert (b.lacingSingle, b.lacingDouble, b.lacingShear, b.lacingDoubleLength) == (
        140.0,
        200.0,
        0.02,
        0.7,
    )
    assert b.tiePlateThickness == pytest.approx(1 / 50)
    # Sec 10.6.11 (part2 p. 88).
    assert (m.bars.yieldLimit, m.bars.ltbLimit, m.bars.ltbA, m.bars.ltbB, m.bars.elastic) == (
        0.08,
        1.9,
        1.52,
        0.274,
        1.9,
    )
    # Secs 10.7.2-10.7.3 (part2 pp. 93-96).
    k = m.tensionField
    assert (k.aspectMax, k.webLimit, k.webFlange, k.depthFlange, k.factor) == (
        3.0,
        260.0,
        2.5,
        6.0,
        1.15,
    )
    assert tuple(k.stiffenerJ) == (2.5, 2.0, 0.5) and k.stiffenerFree == 2.46
    assert k.Ds == {"pair": 1.0, "angle": 1.8, "plate": 2.4}
    assert m.clauses["torsionHss"].startswith("BNBC 2020 Part 6 Sec 10.8.3.1")


# ───────────────────────────────────── HSS torsion ─────────────────────────────────────


def test_rectangular_hss_torsion_by_hand():
    shape = rhs(200, 100, 6.0)  # flat walls 200 - 18 = 182 and 82 mm
    cap = tor.hss_torsion(shape, FY, E, 4000)
    c = 2 * (200 - 6) * (100 - 6) * 6 - 4.5 * (4 - math.pi) * 6**3
    ratio = 182 / 6
    root = math.sqrt(E / FY)
    assert ratio <= 2.45 * root  # Eq 6.10.152: torsional yielding
    assert cap.nominal == pytest.approx(0.6 * FY * c)
    assert cap.design == pytest.approx(0.9 * 0.6 * FY * c)
    # A thinner wall in the inelastic range (Eq 6.10.153).
    thin = rhs(300, 300, 4.0)
    ratio = (300 - 12) / 4
    assert 2.45 * root < ratio <= 3.07 * root
    c = 2 * (296**2) * 4 - 4.5 * (4 - math.pi) * 4**3
    expected = 0.6 * FY * (2.45 * root) / ratio * c
    assert tor.hss_torsion(thin, FY, E, 4000).nominal == pytest.approx(expected)


def test_round_hss_torsion_by_hand():
    shape = chs(168.3, 5.0)
    length = 3000.0
    cap = tor.hss_torsion(shape, FY, E, length)
    ratio = 168.3 / 5
    fcr = min(
        max(1.23 * E / (math.sqrt(length / 168.3) * ratio**1.25), 0.6 * E / ratio**1.5),
        0.6 * FY,
    )
    c = math.pi * (168.3 - 5) ** 2 * 5 / 2
    assert cap.nominal == pytest.approx(fcr * c)


def test_hss_member_torsion_rows():
    shape = rhs(200, 100, 6.0)
    tc = tor.hss_torsion(shape, FY, E, 6000).design
    lengths = MemberLengths.simple(6.0)
    small = _stations(torque=np.full(21, 0.1 * tc))
    rows = {c["name"]: c for c in check_member(shape, STEEL, [small], lengths, "beam")}
    assert rows["Torsion (HSS)"]["utilisation"] == pytest.approx(0.1, abs=1e-3)
    assert "neglected" in rows["Torsion (HSS)"]["note"]
    assert "Torsion, shear, flexure and axial force (HSS)" not in rows
    # Above 20 % of Tc: Eq 6.10.155 (Pr/Pc + Mr/Mc) + (Vr/Vc + Tr/Tc)².
    big = _stations(torque=np.full(21, 0.5 * tc), vy=50e3)
    rows = {c["name"]: c for c in check_member(shape, STEEL, [big], lengths, "beam")}
    combined = rows["Torsion, shear, flexure and axial force (HSS)"]
    vc = shear_major(shape, STEEL).design
    assert combined["utilisation"] == pytest.approx((50e3 / vc + 0.5) ** 2, abs=2e-3)
    assert "Eq 6.10.155" in combined["clause"]


# ─────────────────────────────── open sections: warping torsion ───────────────────────────────


def test_warping_solution_matches_the_closed_form():
    """A concentrated torque T0 at midspan, ends torsionally pinned and free to warp:
    φ''(L/2) = T0 / (2 GJ) λ tanh(λ L / 2), λ = √(GJ / E Cw)."""
    shape = i_shape(400, 180, 13.5, 8.6)
    length = 6000.0
    t0 = 10e6
    n = 401
    s = np.linspace(0, length / 1e3, n)
    torque = np.where(s < length / 2e3, t0 / 2, -t0 / 2)
    torque[n // 2] = 0.0  # the step's midpoint
    sol = tor.solve_warping(s, torque, G, E, shape.j, shape.cw, "free")
    lam = math.sqrt(G * shape.j / (E * shape.cw))
    expected = t0 / (2 * G * shape.j) * lam * math.tanh(lam * length / 2)
    assert abs(sol.phi2[n // 2]) == pytest.approx(expected, rel=0.02)
    # Free to warp at the supports: φ'' = 0 there; the twist closes (∫φ' = 0).
    assert abs(sol.phi2[0]) < 0.02 * expected
    assert abs(np.trapezoid(sol.phi1, s * 1e3)) < 1e-3 * np.max(np.abs(sol.phi1)) * length
    # Restraining warping at the ends lowers the warping stress at midspan.
    fixed = tor.solve_warping(s, torque, G, E, shape.j, shape.cw, "fixed")
    assert abs(fixed.phi2[n // 2]) < abs(sol.phi2[n // 2])
    assert abs(fixed.phi1[0]) < 1e-12


def test_i_shape_torsion_stresses_by_hand():
    d, bf, tf, tw = 400.0, 180.0, 13.5, 8.6
    shape = i_shape(d, bf, tf, tw)
    section = tor.section_torsion(shape)
    ho = d - tf
    assert section.wn == pytest.approx(bf * ho / 4)
    assert section.sw_flange == pytest.approx(tf * bf**2 * ho / 16)
    stress = tor.torsion_stresses(section, G, E, 1e-6, 2e-9, 3e-12)
    assert stress.normal == pytest.approx(E * bf * ho / 4 * 2e-9)
    assert stress.shear_flange == pytest.approx(
        G * tf * 1e-6 + E * tf * bf**2 * ho / 16 * 3e-12 / tf
    )
    assert stress.shear_web == pytest.approx(G * tw * 1e-6)


def test_open_member_torsion_rows():
    shape = i_shape(400, 180, 13.5, 8.6)
    n = 41
    s = np.linspace(0, 6, n)
    torque = np.where(s < 3, 2e6, -2e6)
    torque[n // 2] = 0.0
    st = _stations(n=n, mx=50e6 * np.sin(np.pi * s / 6), vy=20e3, torque=torque)
    rows = {c["name"]: c for c in check_member(shape, STEEL, [st], MemberLengths.simple(6.0))}
    normal = rows["Torsion: normal stress (yielding)"]
    assert normal["capacity"] == pytest.approx(0.9 * FY)  # φT Fy, Eq 6.10.156
    assert "6.10.156" in normal["clause"]
    assert rows["Torsion: shear stress (yielding)"]["capacity"] == pytest.approx(0.9 * 0.6 * FY)
    assert "6.10.158" in rows["Torsion: buckling"]["clause"]
    # The normal stress includes the bending stress Mx / Sx at midspan.
    assert normal["demand"] > 50e6 / shape.sx


def test_no_torque_no_torsion_rows():
    shape = i_shape(400, 180, 13.5, 8.6)
    rows = check_member(shape, STEEL, [_stations(vy=1e3)], MemberLengths.simple(6.0))
    assert not any(c["name"].startswith("Torsion") for c in rows)


# ─────────────────────────────── single angles (Sec 10.8.2) ───────────────────────────────


def test_equal_angle_principal_axes_by_hand():
    shape = angle(100, 100, 10)
    lb = 2000.0
    p = angle_principal(shape, STEEL, lb, 1.0)
    assert abs(p.cos) == pytest.approx(math.sqrt(0.5), abs=1e-6)
    # Eq 6.10.116: Me = 0.46 E b² t² Cb / L.
    me = 0.46 * E * 100**2 * 10**2 / lb
    assert f"Me = {me / 1e6:.1f}" in p.note
    # Eq 6.10.149 with the stress ratios added: Mx splits into Mw = Mz = Mx / √2.
    ratio, mw, mz = unsymmetric_interaction(0.0, 1.0, 5e6, 0.0, p)
    assert mw == pytest.approx(5e6 / math.sqrt(2)) and mz == pytest.approx(mw)
    assert ratio == pytest.approx(mw / p.mcw + mz / p.mcz)


def test_angle_member_reports_sec_10_8_2():
    shape = angle(100, 75, 8)
    n = 11
    st = _stations(n=n, length=3.0, p=60e3, mx=np.full(n, 2e6))
    rows = check_member(shape, STEEL, [st], MemberLengths.simple(3.0), "brace")
    by = {c["name"]: c for c in rows}
    h1 = by["Axial force and flexure (H1)"]
    assert h1["flag"] is True
    unsym = by["Axial force and flexure, unsymmetric (principal axes)"]
    assert "Eq 6.10.149" in unsym["clause"] and not unsym["flag"]
    assert "6.10.117" in unsym["note"]  # unequal legs


# ─────────────────────────────── built-up members (Sec 10.5.6) ───────────────────────────────


def test_modified_slenderness_by_hand():
    snug = BuiltUp(connectors="snugTight", spacing=600, ri=15.0)
    m, _note, ref = modified_slenderness(snug, 80.0)
    assert m == pytest.approx(math.sqrt(80**2 + (600 / 15) ** 2))  # Eq 6.10.34
    assert "6.10.34" in ref
    welded = BuiltUp(connectors="welded", spacing=600, rib=20.0, separation=60.0)
    m, _, ref = modified_slenderness(welded, 80.0)
    alpha = 60 / 40
    assert m == pytest.approx(
        math.sqrt(80**2 + 0.82 * alpha**2 / (1 + alpha**2) * (600 / 20) ** 2)
    )  # Eq 6.10.35
    assert "6.10.35" in ref


def test_built_up_compression_and_dimensional_limits():
    shape = i_shape(300, 300, 15, 10)
    built = BuiltUp(spacing=900, ri=20.0, outside_plate=10.0, plate_pitch=250.0)
    st = _stations(n=11, length=5.0, p=500e3)
    plain = check_member(shape, STEEL, [st], MemberLengths.simple(5.0), "column")
    rows = check_member(
        shape, STEEL, [st], MemberLengths.simple(5.0), "column", {"built_up": built}
    )
    by = {c["name"]: c for c in rows}
    before = {c["name"]: c for c in plain}["Compression: buckling"]["capacity"]
    assert by["Compression: buckling"]["capacity"] < before
    spacing = by["Built-up: connector spacing K a / ri"]
    assert spacing["demand"] == pytest.approx(900 / 20)
    assert spacing["capacity"] == pytest.approx(0.75 * 5000 / shape.ry, abs=0.01)
    plate = by["Built-up: fastener spacing along the outside plate"]
    assert plate["capacity"] == pytest.approx(min(0.75 * math.sqrt(E / FY) * 10, 305), abs=0.01)


def test_lacing_and_tie_plates():
    built = BuiltUp(
        spacing=500,
        ri=20,
        lacing="double",
        lacing_length=400,
        lacing_r=5,
        tie_distance=200,
        tie_length=180,
        tie_thickness=5,
    )
    rows = {c["name"]: c for c in dimensional_checks(built, 60.0, FY, E)}
    lacing = rows["Built-up: double lacing L/r"]
    assert lacing["demand"] == pytest.approx(0.7 * 400 / 5) and lacing["capacity"] == 200
    assert not rows["Built-up: end tie plate length"]["ok"]  # 180 < 200
    assert rows["Built-up: tie plate thickness"]["demand"] == pytest.approx(4.0)


# ─────────────────────────────── bars and rounds (Sec 10.6.11) ───────────────────────────────


def test_rectangular_bar_flexure_by_hand():
    d, t = 200.0, 12.0
    shape = bar(d, t)
    assert shape_properties(RectangleProfile(xDim=t, yDim=d)).family == "bar"
    sx = t * d**2 / 6
    my, mp = FY * sx, min(FY * t * d**2 / 4, 1.6 * FY * sx)
    # Yielding: Lb d / t² <= 0.08 E / Fy.
    lb = 0.05 * E / FY * t**2 / d
    assert flexure_major(shape, STEEL, lb).nominal == pytest.approx(mp)
    # Inelastic LTB (Eq 6.10.122).
    lb = 1.0 * E / FY * t**2 / d
    ratio = lb * d / t**2
    expected = min((1.52 - 0.274 * ratio * FY / E) * my, mp)
    cap = flexure_major(shape, STEEL, lb)
    assert cap.nominal == pytest.approx(expected) and "6.10.121-124" in cap.clause
    # Elastic LTB (Eqs 6.10.123-124).
    lb = 3.0 * E / FY * t**2 / d
    ratio = lb * d / t**2
    assert flexure_major(shape, STEEL, lb).nominal == pytest.approx(1.9 * E / ratio * sx)
    # Minor axis: yielding only.
    assert flexure_minor(shape, STEEL, 5000).nominal == pytest.approx(
        min(FY * d * t**2 / 4, 1.6 * FY * d * t**2 / 6)
    )


def test_round_bar_member():
    shape = round_bar(40)
    assert shape_properties(CircleProfile(radius=20)).family == "round"
    z = 40**3 / 6
    assert flexure_major(shape, STEEL, 3000).nominal == pytest.approx(
        min(FY * z, 1.6 * FY * math.pi * 40**3 / 32)
    )
    st = _stations(n=11, length=2.0, p=-50e3, torque=np.full(11, 0.2e6))
    rows = {c["name"]: c for c in check_member(shape, STEEL, [st], MemberLengths.simple(2.0))}
    # St. Venant shear of a round: T r / J.
    tau = 0.2e6 * 20 / (math.pi * 40**4 / 32)
    assert rows["Torsion: shear stress (yielding)"]["demand"] == pytest.approx(tau, rel=1e-3)
    assert compression(shape, STEEL, 2000, 2000).nominal > 0


# ─────────────────────────────── unsymmetrical shapes (Sec 10.6.12) ───────────────────────────────


def test_unsymmetric_flexure():
    cap = flexure_unsymmetric(100e3, FY, fcr_ltb=200.0)
    assert cap.nominal == pytest.approx(200.0 * 100e3)  # Eqs 6.10.125, 6.10.127
    assert cap.state == "lateral-torsional buckling"
    assert flexure_unsymmetric(100e3, FY).nominal == pytest.approx(FY * 100e3)  # Eq 6.10.126


# ─────────────────────────────── tension field action (Sec 10.7.3) ───────────────────────────────


def test_tension_field_shear_by_hand():
    d, bf, tf, tw = 1200.0, 400.0, 25.0, 10.0
    shape = i_shape(d, bf, tf, tw)
    h = d - 2 * tf
    a = 1500.0
    aspect = a / h
    kv = 5 + 5 / aspect**2
    cv = web_shear_coefficient(h / tw, kv, E, FY)
    aw = d * tw
    expected = 0.6 * FY * aw * (cv + (1 - cv) / (1.15 * math.sqrt(1 + aspect**2)))
    cap = shear_major(shape, STEEL, stiffeners=a, tension_field=True)
    assert cap.nominal == pytest.approx(expected)  # Eq 6.10.143
    assert "6.10.142-143" in cap.clause
    # Without tension field action (an end panel): Sec 10.7.2.1 with kv of the stiffeners.
    plain = shear_major(shape, STEEL, stiffeners=a, tension_field=False)
    assert plain.nominal == pytest.approx(0.6 * FY * aw * cv)
    # Stiffener requirements: Eq 6.10.141, j = 2.5 / (a/h)² - 2 >= 0.5; Eq 6.10.144.
    notes = stiffener_requirements(shape, STEEL, a, 0.8, True)
    j = max(2.5 / aspect**2 - 2, 0.5)
    assert any(f"{a * tw**3 * j / 1e4:.1f}" in n for n in notes)
    ast = 0.15 * 1.0 * h * tw * (1 - cv) * 0.8 - 18 * tw**2
    assert any(f"Ast >= {max(ast, 0):.0f}" in n for n in notes)


def test_tension_field_not_in_end_panels():
    shape = i_shape(1200, 400, 25, 10)
    n = 41
    st = _stations(n=n, length=12.0, vy=1500e3)
    rows = check_member(
        shape, STEEL, [st], MemberLengths.simple(12.0), "beam", {"stiffener_spacing": 1500.0}
    )
    shear = next(c for c in rows if c["name"] == "Shear along y (depth)")
    # The uniform shear governs in an end panel, without tension field action.
    assert "end panel" in shear["note"]
    assert "Ist >=" in shear["note"]


def test_tension_field_limits():
    # h / bf > 6: no tension field action (Sec 10.7.3.1).
    shape = i_shape(1300, 200, 25, 8)
    cap = shear_major(shape, STEEL, stiffeners=1000, tension_field=True)
    assert cap.state != "tension field yielding"
    assert "h / bf > 6" in cap.note


# ─────────────────────────────── overwrites ───────────────────────────────


def test_design_overwrites_reach_the_steel_options():
    resolved = resolve(
        None,
        None,
        {
            "stiffenerSpacing": 1500,
            "warping": "fixed",
            "builtUp": {"connectors": "welded", "spacing": 600, "rib": 20, "separation": 60},
        },
    )
    options = steel_options(resolved)
    assert options.stiffener_spacing == 1500.0
    assert options.warping == "fixed"
    built = BuiltUp.of(options.built_up)
    assert built.connectors == "welded" and built.rib == 20 and built.separation == 60

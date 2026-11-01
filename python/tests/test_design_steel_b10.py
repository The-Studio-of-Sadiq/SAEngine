"""Track B10: steel connections, stability bracing and ponding, each value pinned through the
bnbc2020 code pack with its clause (BNBC 2020 Part 6 Chapter 10, gazette part 2 pages)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.codes.tables import builtin_table
from saengine.design import steel_connections as sc
from saengine.design.steel import ponding
from saengine.design.steel.lengths import MemberLengths
from saengine.design.steel.members import Stations, bracing_requirements
from saengine.design.steel.properties import shape_properties
from saengine.design.steel_proposal import SteelMaterial
from saengine.library.objects import (
    EndPlateConnection,
    FinPlateConnection,
    FlangePlateConnection,
    HssCapPlate,
    HssJointConnection,
    HssMomentConnection,
    IShapeProfile,
    SteelSplice,
)
from saengine.library.steel_sections import find

A36 = SteelMaterial("A36", 250, 400)
A992 = SteelMaterial("A992", 345, 450)
STEEL = builtin_table("steel")


def by_name(result, name):
    return next(c for c in result["checks"] if c["name"] == name)


def names(result):
    return {c["name"] for c in result["checks"]}


# ── the pack values (section 3a fixes #14-15 and the moved tables) ──


def test_pack_phi_round_gapped_k_punching_as_printed():
    # Eq 6.10.217 (part2 p. 155): φ 0.90 printed for round gapped K punching; T/Y 0.95
    assert STEEL.phi.model_extra["hssPunchingRoundK"] == 0.9
    assert STEEL.phi.model_extra["hssPunching"] == 0.95
    assert "misprint" in STEEL.sources["hssPunchingRoundK"]


def test_pack_concrete_bearing_as_printed():
    # Eqs 6.10.183-184 (part2 p. 138): 0.8 f'c A1, 0.8 f'c A1 √(A2/A1) <= 1.7 f'c A1
    c = STEEL.connections
    assert (c.concreteBearingFull, c.concreteBearingPartial, c.concreteBearingMax) == (
        0.8,
        0.8,
        1.7,
    )


def test_pack_bolt_tables():
    c = STEEL.connections
    # Table 6.10.10 (p. 127)
    assert sc.bolt_grade("A325N") == {"Fnt": 620, "Fnv": 330}
    assert sc.bolt_grade("A490X") == {"Fnt": 780, "Fnv": 520}
    assert sc.bolt_grade("8.8") == sc.bolt_grade("A325N")  # practice alias, labelled
    assert "not BNBC" in STEEL.sources["boltAliases"]
    # Table 6.10.9 (p. 125)
    assert c.pretension["A325"][20] == 142 and c.pretension["A490"][24] == 257
    # Table 6.10.11, 6.10.12 (p. 128-129), Sec 10.2.3.13.2 (p. 44)
    assert sc.hole_diameter(24) == 27 and sc.hole_diameter(36) == 39
    assert sc.net_hole(20) == 24
    assert sc.min_edge(36, sheared=True) == 64 and sc.min_edge(42) == pytest.approx(52.5)
    # Table 6.10.7 (p. 116)
    assert [sc.fillet_min_size(t) for t in (6, 10, 16, 25)] == [3, 5, 6, 8]
    # Table 6.10.10 note [f]
    assert (c.longJointLength, c.longJointFactor) == (1270.0, 0.8)


# ── slip-critical bolts (Sec 10.10.3.8-10.10.3.9, p. 131-132) ──


def test_slip_resistance_serviceability_and_strength():
    c = FinPlateConnection(boltGrade="A325N", boltDiameter=20, slipCritical="serviceability")
    cap, _ = sc.slip_capacity(c, 20)
    assert cap == pytest.approx(1.0 * 0.35 * 1.13 * 1.0 * 142e3)
    b = c.model_copy(
        update={"slipCritical": "strength", "surfaceClass": "B", "holeType": "oversized"}
    )
    cap, _ = sc.slip_capacity(b, 20, planes=2)
    assert cap == pytest.approx(0.85 * 0.50 * 1.13 * 0.85 * 142e3 * 2)


def test_slip_with_applied_tension_ks():
    c = EndPlateConnection(boltDiameter=20, slipCritical="serviceability")
    cap, note = sc.slip_capacity(c, 20, 1, tension=40e3)
    ks = 1 - 40e3 / (1.13 * 142e3)  # Eq 6.10.172a
    assert cap == pytest.approx(0.35 * 1.13 * 142e3 * ks)
    assert "ks" in note


def test_slip_check_added_to_the_fin_plate():
    beam = find("IPE 300")
    c = FinPlateConnection(slipCritical="serviceability")
    r = sc.check_fin_plate(c, beam, A36, None, [("U", 80e3)])
    assert "bolt (most loaded) slip resistance" in names(r)
    plain = sc.check_fin_plate(FinPlateConnection(), beam, A36, None, [("U", 80e3)])
    assert not any("slip" in n for n in names(plain))


def test_long_tension_splice_reduces_fnv():
    # Table 6.10.10 [f]: bolt pattern 1400 mm > 1270 mm in a tension splice: Fnv × 0.8
    beam = find("IPE 400")
    c = SteelSplice(rows=15, pitch=100, lines=2)
    r = sc.check_splice(c, beam, A36, None, [("T", -800e3, 0.0, 10e3)])
    check = by_name(r, "flange plate (tension) bolt shear")
    one = 0.75 * 0.8 * 330 * math.pi * 20**2 / 4
    assert check["capacity"] == pytest.approx(one / 1e3, abs=0.01)
    assert "[f]" in check["note"]


# ── prying and bolt tension with shear (Sec 10.10.3.6-10.10.3.7, p. 130) ──


def test_bolt_tension_with_shear():
    cap, _ = sc.bolt_tension_capacity("A325N", 20, frv=100.0)
    fnt_ = min(1.3 * 620 - 620 / (0.75 * 330) * 100, 620)  # Eq 6.10.170a
    assert cap == pytest.approx(0.75 * fnt_ * math.pi * 100)


def test_prying_t_stub_by_hand():
    b_cap = 100e3
    cap, _ = sc.prying_capacity(b_cap, b=40, a=35, p=70, t=12, fu=400, d=20)
    b1, a1 = 40 - 10, 35 + 10
    rho, delta = b1 / a1, 1 - 22 / 70
    tc = math.sqrt(4 * b_cap * b1 / (0.9 * 70 * 400))
    alpha = ((tc / 12) ** 2 - 1) / (delta * (1 + rho))
    q = (12 / tc) ** 2 * (1 + delta * min(max(alpha, 0), 1))
    assert cap == pytest.approx(b_cap * min(q, 1.0))
    thick, _ = sc.prying_capacity(b_cap, b=40, a=35, p=70, t=40, fu=400, d=20)
    assert thick == pytest.approx(b_cap)  # tc < t: no prying


def test_end_plate_under_axial_tension():
    beam = find("IPE 300")
    c = EndPlateConnection(rows=3, gauge=90, edgeDistance=35, plateThickness=10)
    r = sc.check_end_plate(c, beam, A36, None, [("U", 60e3)], [("U", 60e3, 120e3)])
    assert "bolt tension with prying" in names(r)
    assert "beam web tension yielding at the welds" in names(r)
    only_shear = sc.check_end_plate(c, beam, A36, None, [("U", 60e3)])
    assert "bolt tension with prying" not in names(only_shear)


# ── concentrated forces on flanges and webs (Sec 10.10.10, p. 139-146) ──


def test_end_distance_reductions():
    col = find("HEB 300")
    k = col.tf + col.r
    cap, _ = sc.flange_local_bending(col.tf, 345, end_distance=5 * col.tf)
    assert cap == pytest.approx(0.9 * 0.5 * 6.25 * col.tf**2 * 345)  # Eq 6.10.185, 50 %
    cap, _ = sc.web_local_yielding(k, 20, col.tw, 345, col.h, end_distance=100)
    assert cap == pytest.approx((2.5 * k + 20) * 345 * col.tw)  # Eq 6.10.187
    cap, note = sc.web_crippling(20, col.h, col.tw, col.tf, 345, 200_000, end_distance=50)
    root = math.sqrt(200_000 * 345 * col.tf / col.tw)
    assert cap == pytest.approx(
        0.75 * 0.40 * col.tw**2 * (1 + 3 * (20 / col.h) * (col.tw / col.tf) ** 1.5) * root
    )  # Eq 6.10.189a
    assert "6.10.189a" in note


def test_web_sidesway_buckling():
    # Eqs 6.10.190-191, φ 0.85; Cr 6.62e6 MPa when Mu < My
    cap, _ = sc.web_sidesway_buckling(8, 12, 400, 200, 6000, restrained=True, yielded=False)
    ratio = (400 / 8) / (6000 / 200)
    assert cap == pytest.approx(0.85 * 6.62e6 * 8**3 * 12 / 400**2 * (1 + 0.4 * ratio**3))
    none, note = sc.web_sidesway_buckling(8, 12, 400, 200, 1000, restrained=True, yielded=False)
    assert none is None and "2.3" in note


def test_web_compression_buckling_and_panel_zone():
    cap, _ = sc.web_compression_buckling(10, 250, 345, 200_000, 300, None)
    assert cap == pytest.approx(0.9 * 24 * 10**3 * math.sqrt(200_000 * 345) / 250)  # 6.10.192
    cap, _ = sc.panel_zone_shear(345, 300, 11, 0.6)
    assert cap == pytest.approx(0.9 * 0.6 * 345 * 300 * 11 * (1.4 - 0.6))  # Eq 6.10.194
    cap, _ = sc.panel_zone_shear(345, 300, 11, 0.8, True, 300, 19, 400)
    boost = 1 + 3 * 300 * 19**2 / (400 * 300 * 11)
    assert cap == pytest.approx(0.9 * 0.6 * 345 * 300 * 11 * boost * (1.9 - 1.2 * 0.8))  # 6.10.196


def test_doubler_and_double_sided_joint():
    col = find("HEB 300")
    base, _ = sc.column_side_checks(400e3, "M", col, A992, 16.0, False, double_sided=True)
    assert "column web compression buckling" in names({"checks": base})
    assert by_name({"checks": base}, "column panel zone shear")["demand"] == pytest.approx(800.0)
    doubled, _ = sc.column_side_checks(400e3, "M", col, A992, 16.0, False, doubler=10)
    extra = 0.9 * 0.6 * 345 * col.h * 10 / 1e3
    plain = by_name({"checks": base}, "column panel zone shear")["capacity"]
    assert by_name({"checks": doubled}, "column panel zone shear")["capacity"] == pytest.approx(
        plain + extra, abs=0.02
    )
    assert "doubler plate edge welds" in names({"checks": doubled})


def test_stiffener_rules():
    col = find("HEB 300")
    checks, _ = sc.column_side_checks(
        900e3, "M", col, A992, 16.0, True, loaded_width=250, delivering_thickness=20
    )
    r = {"checks": checks}
    bs = (col.b - col.tw) / 2
    # Sec 10.10.10.8: width + tw/2 >= bp / 3, thickness >= tp / 2 and >= width / 15
    assert by_name(r, "stiffener width + tw / 2")["demand"] == pytest.approx(250 / 3, abs=0.01)
    assert by_name(r, "stiffener thickness")["demand"] == pytest.approx(max(10, bs / 15), abs=0.01)


# ── plates on HSS (Sec 10.11.1, p. 147-151) ──


def test_transverse_plate_on_rectangular_hss():
    hss = find("SHS 200x200x8")
    checks, _ = sc.hss_transverse_plate_checks(200e3, "M", hss, A36, 120, 15, A36)
    t = hss.tw
    rn = min(10 / (hss.b / t) * 250 * t * 120, 250 * 15 * 120)  # Eq 6.10.198
    assert by_name({"checks": checks}, "plate local yielding (uneven load)")[
        "capacity"
    ] == pytest.approx(0.95 * rn / 1e3, abs=0.01)


def test_transverse_plate_on_round_hss():
    hss = find("CHS 168.3x8")
    checks, _ = sc.hss_transverse_plate_checks(100e3, "M", hss, A36, 100, 15, A36, u=0.4)
    qf = 1 - 0.3 * 0.4 * 1.4  # Eq 6.10.209
    rn = 250 * hss.tw**2 * (5.5 / (1 - 0.81 * 100 / hss.h)) * qf  # Eq 6.10.197
    assert by_name({"checks": checks}, "HSS wall local yielding")["capacity"] == pytest.approx(
        0.9 * rn / 1e3, abs=0.01
    )


def test_flange_plate_on_hss_column():
    beam = find("IPE 300")
    c = FlangePlateConnection(columnSection="SHS 300x300x12.5")
    r = sc.check_flange_plate(
        c, beam, A36, None, [("M", 80e6, 50e3)], find("SHS 300x300x12.5"), A36
    )
    assert "plate local yielding (uneven load)" in names(r)


def test_longitudinal_plate_and_cap_plate():
    hss = find("SHS 200x200x8")
    beam = find("IPE 300")
    r = sc.check_fin_plate(FinPlateConnection(), beam, A36, None, [("U", 50e3)], hss, A36)
    check = by_name(r, "HSS wall under the plate (Fyp tp <= Fu t)")  # Eq 6.10.206
    assert (check["demand"], check["capacity"]) == (250 * 10, 400 * hss.tw)
    cap = sc.check_cap_plate(HssCapPlate(thickness=20, bearingLength=150), hss, A36, [("D", 300e3)])
    t = hss.tw
    walls = 2 if 5 * 20 + 150 < hss.b else 4  # 250 >= 200: all four walls
    assert walls == 4
    per = min(250 * t * (5 * 20 + 150), hss.b * 250 * t)  # Eq 6.10.207
    assert by_name(cap, "HSS wall local yielding")["capacity"] == pytest.approx(
        4 * per / 1e3, abs=0.01
    )


# ── HSS truss joints (Sec 10.11.2, p. 152-162) ──


def test_round_gapped_k_punching_phi_090():
    c = HssJointConnection(joint="K", angle=45, gap=30, chordCompression=False)
    chord, branch = find("CHS 168.3x8"), find("CHS 88.9x5")
    r = sc.check_hss_joint(c, branch, A36, chord, None, [("T", 50e3)])
    sin = math.sin(math.radians(45))
    pn = 0.6 * 250 * chord.tw * math.pi * branch.h * (1 + sin) / (2 * sin**2)
    assert by_name(r, "chord punching shear (tension)")["capacity"] == pytest.approx(
        0.90 * pn / 1e3, abs=0.01
    )


def test_round_overlapped_k_negative_gap():
    c = HssJointConnection(joint="KOverlap", angle=45, overlap=50, chordCompression=False)
    chord, branch = find("CHS 168.3x8"), find("CHS 88.9x5")
    r = sc.check_hss_joint(c, branch, A36, chord, None, [("C", -50e3)])
    t = chord.tw
    gamma = chord.h / (2 * t)
    sin = math.sin(math.radians(45))
    g = -0.5 * branch.h / sin  # g = -q (Sec 10.11.2.2.3)
    qg = gamma**0.2 * (1 + 0.024 * gamma**1.2 / (math.exp(0.5 * g / t - 1.33) + 1))
    pn = 250 * t**2 * (2.0 + 11.33 * branch.h / chord.h) * qg / sin
    assert by_name(r, "chord plastification (compression)")["capacity"] == pytest.approx(
        0.9 * pn / 1e3, abs=0.01
    )
    assert "chord punching shear (compression)" not in names(r)  # gapped only


def test_rectangular_overlapped_k_eq_6_10_233():
    c = HssJointConnection(joint="KOverlap", angle=45, overlap=60, chordCompression=False)
    chord, branch = find("SHS 150x150x8"), find("SHS 100x100x5")
    r = sc.check_hss_joint(c, branch, A36, chord, None, [("T", 50e3)])
    t, tb, bb = chord.tw, branch.tw, branch.b
    beoi = min(10 / (chord.b / t) * (250 * t / (250 * tb)) * bb, bb)  # Eq 6.10.235
    beov = min(10 / (bb / tb) * (250 * tb / (250 * tb)) * bb, bb)  # Eq 6.10.236
    pn = 250 * tb * (2 * branch.h - 4 * tb + beoi + beov)  # Eq 6.10.233 (50 <= Ov < 80)
    assert by_name(r, "overlapping branch yielding (uneven load) (tension)")[
        "capacity"
    ] == pytest.approx(0.95 * pn / 1e3, abs=0.01)


# ── HSS moment connections (Sec 10.11.3, p. 163-171) ──


def test_round_hss_moment_in_plane_plastification():
    c = HssMomentConnection(joint="T", angle=90, chordCompression=False)
    chord, branch = find("CHS 273x10"), find("CHS 114.3x6.3")
    r = sc.check_hss_moment(c, branch, A36, chord, None, [("M", 0.0, 5e6, 0.0)])
    t = chord.tw
    beta, gamma = branch.h / chord.h, chord.h / (2 * t)
    mn = 5.39 * 250 * t**2 * gamma**0.5 * beta * branch.h  # Eq 6.10.243
    mp = 0.6 * 250 * t * branch.h**2 * (1 + 3) / 4  # Eq 6.10.244 at θ = 90°
    assert by_name(r, "in-plane moment strength")["capacity"] == pytest.approx(
        min(0.9 * mn, 0.95 * mp) / 1e6, abs=0.01
    )
    assert "axial force and moments" in names(r)


def test_rectangular_hss_moment_runs():
    c = HssMomentConnection(joint="T", chordCompression=False)
    chord, branch = find("SHS 200x200x8"), find("SHS 100x100x5")
    r = sc.check_hss_moment(c, branch, A36, chord, None, [("M", 10e3, 4e6, 1e6)])
    assert {"in-plane moment strength", "out-of-plane moment strength"} <= names(r)


# ── stability bracing (Sec 10.19, p. 222-227) ──


def _stations(p: float, m: float, n: int = 5) -> list[Stations]:
    s = np.linspace(0, 6, n)
    return [
        Stations(
            "C",
            s,
            np.full(n, p),
            np.full(n, m),
            np.zeros(n),
            np.zeros(n),
            np.zeros(n),
            [""] * n,
        )
    ]


def test_column_nodal_and_relative_bracing():
    shape = shape_properties(IShapeProfile.model_validate(find("HEB 300").profile()))
    lengths = MemberLengths.simple(6.0, x=[3.0], y=[3.0])
    req = bracing_requirements(shape, _stations(1000e3, 0.0), lengths, "column")
    nodal = req[0]
    assert nodal["type"] == "nodal"
    assert nodal["Pbr"] == pytest.approx(0.01 * 1000)  # Eq 6.10.287, kN
    assert nodal["betaBr"] == pytest.approx(8 * 1000e3 / (0.75 * 3000) / 1e3, abs=1e-3)  # 6.10.288
    ends = bracing_requirements(shape, _stations(1000e3, 0.0), MemberLengths.simple(6.0), "column")
    assert ends[0]["type"] == "relative"
    assert ends[0]["Pbr"] == pytest.approx(0.004 * 1000)  # Eq 6.10.285


def test_beam_lateral_nodal_bracing():
    shape = shape_properties(IShapeProfile.model_validate(find("IPE 400").profile()))
    lengths = MemberLengths.simple(6.0, y=[2.0, 4.0])
    req = bracing_requirements(shape, _stations(0.0, -200e6), lengths, "beam")
    ho = shape.dims["ho"]
    assert req[0]["Pbr"] == pytest.approx(0.02 * 200e6 / ho / 1e3, abs=0.01)  # Eq 6.10.291
    assert req[0]["betaBr"] == pytest.approx(
        10 * 200e6 / (0.75 * 2000 * ho) / 1e3, abs=1e-3
    )  # Eq 6.10.292


def test_bracing_pack_values():
    b = STEEL.bracing
    assert (b.phi, b.slenderness) == (0.75, 180.0)  # Sec 10.19.4
    assert (b.columnRelative.strength, b.columnNodal.stiffness) == (0.004, 8.0)
    assert (b.beamRelative.stiffness, b.beamNodal.strength) == (4.0, 0.02)


# ── ponding (Sec 10.16, p. 194-197) ──


def test_ponding_simplified():
    # Cp = 504 Ls Lp⁴ / Ip, Cs = 504 S Ls⁴ / Is (Eq 6.10.272)
    r = ponding.simplified(lp=8.0, ls=6.0, s=1.5, ip=3.0e9, is_=2.0e8, id_=3940 * 1.5**4)
    cp = 504 * 6.0 * 8.0**4 / 3.0e9
    cs = 504 * 1.5 * 6.0**4 / 2.0e8
    assert r["Cp"] == pytest.approx(cp) and r["Cs"] == pytest.approx(cs)
    assert r["checks"][0]["demand"] == pytest.approx(round(cp + 0.9 * cs, 4))
    assert r["checks"][1]["ok"]  # Eq 6.10.273: Id >= 3940 S⁴
    truss = ponding.simplified(8.0, 6.0, 1.5, 3.0e9, 2.0e8, secondary_truss=True)
    assert truss["Cs"] == pytest.approx(cs / 0.85)


def test_ponding_improved_reads_the_figures():
    # Figure 6.10.2 (digitised): Cp = 0 curve at Us = 1.05 gives Cs about 0.51
    r = ponding.improved(None, 1.05, 0.0, 0.3)
    assert r["checks"][0]["capacity"] == pytest.approx(0.513, abs=0.01)
    assert r["ok"]
    # Figure 6.10.1: Up = 1.05 on the Cs = 0.2 curve gives Cp about 0.35
    r = ponding.improved(1.05, 1.05, 0.2, 0.2)
    assert r["checks"][0]["capacity"] == pytest.approx(0.351, abs=0.01)
    assert ponding.stress_index(250, 100) == pytest.approx((0.8 * 250 - 100) / 100)  # 6.10.274

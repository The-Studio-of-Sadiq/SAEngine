"""Connections 2 (moment connections, splices, base plates, HSS truss joints) against hand
calculations, each value pinned with its BNBC 2020 Part 6 Chapter 10 clause."""

from __future__ import annotations

import math

import pytest

from saengine.design import steel_connections as sc
from saengine.design.steel_proposal import SteelMaterial
from saengine.library.objects import (
    ColumnBasePlate,
    FlangePlateConnection,
    HssJointConnection,
    SteelSplice,
)
from saengine.library.steel_sections import find

A36 = SteelMaterial("A36", 250, 400)
A992 = SteelMaterial("A992", 345, 450)


def by_name(result, name):
    return next(c for c in result["checks"] if c["name"] == name)


def names(result):
    return {c["name"] for c in result["checks"]}


# ── column bases (Sec 10.10.8, Table 6.10.10) ──


def test_bearing_on_concrete_confined_limit():
    # Sec 10.10.8: φc 0.85 f'c A1 √(A2/A1) <= 1.7 f'c A1, φc 0.60
    c = ColumnBasePlate(length=400, width=300, concreteStrength=25)
    assert sc.bearing_on_concrete(c) == pytest.approx(0.6 * 0.85 * 25 * 120_000)
    big = c.model_copy(update={"supportLength": 900, "supportWidth": 700})  # √(A2/A1) > 2
    assert sc.bearing_on_concrete(big) == pytest.approx(0.6 * 1.7 * 25 * 120_000)
    mid = c.model_copy(update={"supportLength": 600, "supportWidth": 450})  # A2/A1 = 2.25
    assert sc.bearing_on_concrete(mid) == pytest.approx(0.6 * 0.85 * 25 * 120_000 * 1.5)


def test_anchor_rod_steel_as_threaded_parts():
    # Table 6.10.10: Fnt = 0.75 Fu, Fnv = 0.40 Fu (threads included), φ 0.75
    c = ColumnBasePlate(anchorDiameter=20, anchorFu=400)
    ab = math.pi * 20**2 / 4
    t, v, fnt, fnv = sc.anchor_capacities(c)
    assert (fnt, fnv) == (pytest.approx(300.0), pytest.approx(160.0))
    assert t == pytest.approx(0.75 * 300 * ab)
    assert v == pytest.approx(0.75 * 160 * ab)
    _, _v_x, _, fnv_x = sc.anchor_capacities(c.model_copy(update={"threadsExcluded": True}))
    assert fnv_x == pytest.approx(200.0)


def test_base_plate_checks_and_combined_tension_shear():
    c = ColumnBasePlate(anchors=4, anchorDiameter=20, anchorFu=400)
    col = find("HEB 300")
    r = sc.check_base_plate(c, col, A992, A36, [("C", 1500e3, 40e3, 10e6), ("U", -100e3, 60e3, 0)])
    assert by_name(r, "bearing on the concrete")["demand"] == pytest.approx(1500.0)
    ab = math.pi * 20**2 / 4
    frv = 60e3 / 4 / ab
    fnt_ = min(1.3 * 300 - 300 / (0.75 * 160) * frv, 300)  # Sec 10.10.3.7
    check = by_name(r, "anchor rod tension with shear")
    assert check["demand"] == pytest.approx(25.0)
    assert check["capacity"] == pytest.approx(0.75 * fnt_ * ab / 1e3, abs=0.01)
    assert "plate width B" in names(r)


# ── flange-plate moment connection and the column side (Sec 10.10.10) ──


def test_flange_force_and_bolt_shear():
    c = FlangePlateConnection(rows=4, lines=2, plateThickness=16, boltDiameter=20)
    beam = find("IPE 400")
    r = sc.check_flange_plate(c, beam, A992, A36, [("M", 150e6, 120e3)])
    puf = 150e6 / (beam.h + 16)  # M / (d + tp)
    bolt = by_name(r, "flange plate (tension) bolt shear")
    assert bolt["demand"] == pytest.approx(puf / 8 / 1e3, abs=0.01)
    assert bolt["capacity"] == pytest.approx(0.75 * 330 * math.pi * 100 / 1e3, abs=0.01)
    yielding = by_name(r, "flange plate (tension) plate tension yielding")
    bp = 100 + 2 * 35
    assert yielding["capacity"] == pytest.approx(0.9 * 250 * bp * 16 / 1e3, abs=0.01)
    assert "web: bolt shear (most loaded bolt)" in names(r)
    assert not any(n.startswith("column") for n in names(r))  # no column section given


def test_column_side_checks_by_hand():
    col = find("HEB 300")
    checks, _ = sc.column_side_checks(500e3, "M", col, A992, 16.0, False)
    k = col.tf + col.r
    assert by_name({"checks": checks}, "column flange local bending")["capacity"] == pytest.approx(
        0.9 * 6.25 * col.tf**2 * 345 / 1e3, abs=0.01
    )
    assert by_name({"checks": checks}, "column web local yielding")["capacity"] == pytest.approx(
        1.0 * (5 * k + 16) * 345 * col.tw / 1e3, abs=0.01
    )
    crip = 0.80 * col.tw**2 * (1 + 3 * (16 / col.h) * (col.tw / col.tf) ** 1.5)
    crip *= math.sqrt(200_000 * 345 * col.tf / col.tw)
    assert by_name({"checks": checks}, "column web crippling")["capacity"] == pytest.approx(
        0.75 * crip / 1e3, abs=0.01
    )
    assert by_name({"checks": checks}, "column panel zone shear")["capacity"] == pytest.approx(
        0.9 * 0.6 * 345 * col.h * col.tw / 1e3, abs=0.01
    )
    stiffened, _ = sc.column_side_checks(500e3, "M", col, A992, 16.0, True)
    assert [c["name"] for c in stiffened] == ["column panel zone shear"]


def test_flexural_rupture_at_flange_holes():
    # Sec 10.6.13.1: Mn = Fu Afn / Afg Sx when Fu Afn < Yt Fy Afg
    c = FlangePlateConnection(lines=2, boltDiameter=24)
    beam = find("IPE 300")
    r = sc.check_flange_plate(c, beam, A992, A36, [("M", 50e6, 50e3)])
    afg = beam.b * beam.tf
    afn = (beam.b - 2 * (27 + 2)) * beam.tf
    assert 450 * afn < 1.0 * 345 * afg
    check = by_name(r, "beam flexural rupture at the flange holes")
    assert check["capacity"] == pytest.approx(0.9 * 450 * afn / afg * beam.Sx / 1e6, abs=0.01)


def test_flange_plate_needs_an_i_beam():
    with pytest.raises(ValueError):
        sc.check_flange_plate(FlangePlateConnection(), find("SHS 100x100x5"), A36, None, [])


# ── splices (Sec 10.10.6, 10.10.1.4) ──


def test_column_splice_finished_to_bear_takes_no_compression():
    col = find("HEB 300")
    c = SteelSplice(plateThickness=12)
    r = sc.check_splice(c, col, A992, A36, [("P", 1000e3, 0.0, 10e3)], column=True)
    assert not any("flange plate" in n for n in names(r))  # all compression by bearing
    r2 = sc.check_splice(
        c.model_copy(update={"finishedToBear": False}),
        col,
        A992,
        A36,
        [("P", 1000e3, 0.0, 0)],
        True,
    )
    share = col.b * col.tf / col.A
    bolt = by_name(r2, "flange plate (compression) bolt shear")
    assert bolt["demand"] == pytest.approx(1000e3 * share / (c.rows * c.lines) / 1e3, abs=0.01)


def test_beam_splice_flange_force_from_moment():
    beam = find("IPE 400")
    c = SteelSplice(rows=3, lines=2)
    r = sc.check_splice(c, beam, A992, A36, [("M", 0.0, 100e6, 50e3)])
    ff = 100e6 / (beam.h - beam.tf)  # M / (d - tf)
    assert by_name(r, "flange plate (tension) bolt shear")["demand"] == pytest.approx(
        ff / 6 / 1e3, abs=0.01
    )
    web = by_name(r, "web bolt shear")
    assert web["capacity"] == pytest.approx(0.75 * 330 * math.pi * 100 * 2 / 1e3, abs=0.01)


# ── HSS truss joints (Sec 10.11.2) ──


def test_round_t_joint_chord_plastification():
    c = HssJointConnection(joint="TY", angle=90, chordCompression=False)
    chord, branch = find("CHS 168.3x8"), find("CHS 88.9x5")
    r = sc.check_hss_joint(c, branch, A36, chord, None, [("T", 100e3)])
    t = chord.tw
    beta, gamma = branch.h / chord.h, chord.h / (2 * t)
    pn = 250 * t**2 * (3.1 + 15.6 * beta**2) * gamma**0.2  # Qf = 1, sin 90° = 1
    assert by_name(r, "chord plastification (tension)")["capacity"] == pytest.approx(
        0.9 * pn / 1e3, abs=0.01
    )
    punch = 0.6 * 250 * t * math.pi * branch.h * (1 + 1) / 2
    assert by_name(r, "chord punching shear (tension)")["capacity"] == pytest.approx(
        0.95 * punch / 1e3, abs=0.01
    )


def test_round_chord_stress_factor():
    c = HssJointConnection(joint="X", angle=60, chordCompression=True, chordUtilisation=0.6)
    chord, branch = find("CHS 168.3x8"), find("CHS 88.9x5")
    r = sc.check_hss_joint(c, branch, A36, chord, None, [("C", -50e3)])
    qf = 1 - 0.3 * 0.6 * 1.6
    beta = branch.h / chord.h
    pn = 250 * chord.tw**2 * (5.7 / (1 - 0.81 * beta)) * qf / math.sin(math.radians(60))
    assert by_name(r, "chord plastification (compression)")["capacity"] == pytest.approx(
        0.9 * pn / 1e3, abs=0.01
    )


def test_rectangular_k_joint_and_limits():
    c = HssJointConnection(joint="K", angle=45, gap=40, chordCompression=False)
    chord, branch = find("SHS 150x150x8"), find("SHS 100x100x5")
    r = sc.check_hss_joint(c, branch, A36, chord, None, [("T", 100e3), ("C", -100e3)])
    t = chord.tw
    beta_eff = (branch.b + branch.h) / (2 * chord.b)
    gamma = chord.b / (2 * t)
    pn = 250 * t**2 * 9.8 * beta_eff * gamma**0.5 / math.sin(math.radians(45))
    assert by_name(r, "chord wall plastification (tension)")["capacity"] == pytest.approx(
        0.9 * pn / 1e3, abs=0.01
    )
    # square branches: no punching or branch yielding check (Sec 10.11.2)
    assert "chord punching shear (tension)" not in names(r)
    assert by_name(r, "gap g / B")["ok"]  # 40/150 >= 0.5 (1 - 0.667)
    small = sc.check_hss_joint(
        c.model_copy(update={"gap": 15}), branch, A36, chord, None, [("T", 1e3)]
    )
    assert not small["ok"]


def test_rectangular_t_joint_wall_plastification():
    c = HssJointConnection(joint="TY", angle=90, chordCompression=False)
    chord, branch = find("SHS 200x200x8"), find("SHS 100x100x5")
    r = sc.check_hss_joint(c, branch, A36, chord, None, [("T", 50e3)])
    t = chord.tw
    beta = branch.b / chord.b
    eta = branch.h / chord.b
    pn = 250 * t**2 * (2 * eta / (1 - beta) + 4 / math.sqrt(1 - beta))
    assert by_name(r, "chord wall plastification (tension)")["capacity"] == pytest.approx(
        1.0 * pn / 1e3, abs=0.01
    )


def test_mixed_hss_shapes_rejected():
    with pytest.raises(ValueError):
        sc.check_hss_joint(
            HssJointConnection(),
            find("CHS 88.9x5"),
            A36,
            find("SHS 150x150x8"),
            None,
            [("T", 1e3)],
        )


def test_simple_kinds_exclude_moment_connections():
    assert "flangePlate" not in sc.SIMPLE_KINDS
    assert {"finPlate", "endPlate", "gusset", "hssJoint"} <= sc.SIMPLE_KINDS

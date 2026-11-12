"""Simple steel connection checks against hand calculations."""

from __future__ import annotations

import math

import pytest

from saengine.design import steel_connections as sc
from saengine.design.steel_proposal import SteelMaterial
from saengine.library.steel_sections import find

A36 = SteelMaterial("A36", 250, 400)
A992 = SteelMaterial("A992", 345, 450)


def by_name(result, name):
    return next(c for c in result["checks"] if c["name"] == name)


def test_bolt_group_shear_end_plate():
    c = sc.EndPlateConnection(rows=3, boltDiameter=20, boltGrade="A325N")
    r = sc.check_end_plate(c, find("IPE 300"), A992, A36, [("1.2D+1.6L", 300e3)])
    bolt = by_name(r, "bolt shear")
    per_bolt = 0.75 * 330 * math.pi * 20**2 / 4  # Eq 6.10.168, Fnv Table 6.10.10
    assert bolt["capacity"] == pytest.approx(per_bolt / 1e3, abs=0.01)
    assert bolt["demand"] == pytest.approx(50.0)
    assert bolt["utilisation"] == pytest.approx(50e3 / per_bolt, abs=1e-3)
    assert bolt["combination"] == "1.2D+1.6L"


def test_block_shear_fin_plate_by_hand():
    c = sc.FinPlateConnection(
        rows=3, pitch=70, endDistance=35, edgeDistance=35, plateThickness=10, boltDiameter=20
    )
    r = sc.check_fin_plate(c, find("IPE 300"), A992, A36, [(None, 100e3)])
    # hp = 210; Agv = 175·10; Anv = Agv - 2.5·24·10; Ant = (35 - 12)·10 (holes 22 + 2 mm)
    agv, anv, ant = 1750.0, 1150.0, 230.0
    rn = min(0.6 * 400 * anv + 400 * ant, 0.6 * 250 * agv + 400 * ant)
    assert rn == pytest.approx(354_500)
    assert by_name(r, "plate block shear")["capacity"] == pytest.approx(0.75 * rn / 1e3, abs=0.01)
    # plate shear yielding φ 1.0 · 0.6 Fy · hp tp
    assert by_name(r, "plate shear yielding")["capacity"] == pytest.approx(315.0)
    # eccentric bolt group: most loaded bolt sqrt((V/3)² + (V a 70 / (2·70²))²)
    most = math.hypot(100 / 3, 100 * 60 * 70 / (2 * 70**2))
    assert by_name(r, "bolt shear (most loaded bolt)")["demand"] == pytest.approx(most, abs=0.01)
    assert r["ok"] is (r["utilisation"] <= 1.0)


def test_whitmore_and_gusset_checks():
    lw = sc.whitmore_width(rows=3, lines=2, pitch=70, gauge=60)
    assert lw == pytest.approx(60 + 2 * 140 * math.tan(math.radians(30)))
    c = sc.BraceGussetConnection(rows=3, lines=2, pitch=70, gauge=60, plateThickness=10)
    r = sc.check_brace_gusset(c, find("SHS 150x150x8"), A992, A36, [("T", 400e3), ("C", -350e3)])
    assert by_name(r, "gusset Whitmore yielding")["capacity"] == pytest.approx(
        0.9 * 250 * lw * 10 / 1e3, abs=0.01
    )
    buck = by_name(r, "gusset buckling (Whitmore)")
    kl_r = 0.65 * 150 / (10 / math.sqrt(12))
    assert kl_r > 25
    fe = math.pi**2 * 200_000 / kl_r**2
    fcr = 0.658 ** (250 / fe) * 250
    assert buck["capacity"] == pytest.approx(0.9 * fcr * lw * 10 / 1e3, abs=0.01)
    assert buck["combination"] == "C"
    names = {x["name"] for x in r["checks"]}
    assert "tab welds to the brace (tension)" in names  # hollow brace: welded tab
    assert "bolt shear (compression)" in names


def test_weld_and_detailing_rules():
    assert sc.fillet_capacity_per_mm(6, 480) == pytest.approx(0.75 * 0.6 * 480 * 0.707 * 6)
    assert sc.fillet_capacity_per_mm(6, 480, 90) == pytest.approx(
        1.5 * sc.fillet_capacity_per_mm(6, 480)
    )
    assert sc.fillet_min_size(10) == 5 and sc.fillet_min_size(25) == 8
    assert sc.min_edge(20) == 26 and sc.min_edge(20, sheared=True) == 34
    c = sc.FinPlateConnection(pitch=40, boltDiameter=20)  # 2⅔·20 = 53.3 > 40
    r = sc.check_fin_plate(c, find("IPE 300"), A992, A36, [(None, 10e3)])
    assert not by_name(r, "bolt pitch")["ok"]
    assert not r["ok"]


def test_angle_brace_bolted_through_its_leg_and_proposal():
    c = sc.BraceGussetConnection(rows=2, lines=1, plateThickness=10)
    angle = find("L 75x75x8")
    r = sc.check_brace_gusset(c, angle, A36, A36, [("T", 300e3)])
    assert "bearing on the brace leg/web (tension)" in {x["name"] for x in r["checks"]}
    assert not r["ok"]  # 2 M20 bolts cannot carry 300 kN
    p = sc.propose_connection(c, angle, A36, A36, [("T", 300e3)])
    assert p["status"] == "ok" and p["result"]["ok"]
    assert p["proposed"]["rows"] > 2 or p["proposed"]["boltDiameter"] > 20
    # one bolt fewer (same size) fails: the proposal is the fewest bolts
    fewer = c.model_copy(update={**p["proposed"], "rows": p["proposed"]["rows"] - 1})
    if fewer.rows >= 1:
        sizes = (16, 20, 22, 24)
        assert not any(
            sc.check_connection(
                fewer.model_copy(update={"boltDiameter": d, "plateThickness": t}),
                angle,
                A36,
                A36,
                [("T", 300e3)],
            )["ok"]
            for d in sizes
            for t in (8, 10, 12, 16, 20, 25)
        )

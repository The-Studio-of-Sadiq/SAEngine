"""Timber members and joints with the bnbc2020 code pack (BNBC 2020 Part 6 Chapter 11): the
values are pinned with their clauses (B6)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pytest

from saengine.codes.tables import builtin_table
from saengine.design import timber as T
from saengine.design.steel.members import Stations
from saengine.library.materials import Material
from saengine.library.objects import TimberMember, TimberNotch


def _table():
    return builtin_table("timber", "bnbc2020")


# ───────────────────────── stresses: Table 6.11.9, note 1 (p. 296) ─────────────────────────


def test_group_stresses_inside_outside_wet():
    g = _table().groups
    # Table 6.11.9 inside values.
    assert (g["A"].bending["inside"], g["B"].bending["inside"], g["C"].bending["inside"]) == (
        18.0,
        12.0,
        8.5,
    )
    # Note 1: outside and wet are 5/6 and 2/3 (section 3a #29-31 corrections).
    assert g["B"].bending["outside"] == pytest.approx(10.0)
    assert g["B"].bending["wet"] == pytest.approx(8.0)
    assert g["C"].bending["outside"] == pytest.approx(7.083, abs=1e-3)
    assert g["C"].bending["wet"] == pytest.approx(5.667, abs=1e-3)
    assert g["A"].compressionParallel["outside"] == pytest.approx(9.75)
    assert g["A"].compressionParallel["wet"] == pytest.approx(7.8)
    assert g["B"].compressionParallel["outside"] == pytest.approx(6.5)
    assert g["C"].compressionParallel["wet"] == pytest.approx(3.267, abs=1e-3)
    assert g["A"].compressionPerpendicular["outside"] == pytest.approx(3.333, abs=1e-3)
    assert g["C"].compressionPerpendicular["wet"] == pytest.approx(0.733, abs=1e-3)
    # Group A shear along the grain printed 15 (misprint): 1.5 kept.
    assert g["A"].shearAlong == 1.5
    assert (g["A"].E, g["B"].E, g["C"].E) == (12600.0, 9800.0, 5600.0)


def test_timber_of_group():
    t = T.Timber.of("B", "inside")
    assert (t.e, t.fb, t.fv, t.fva, t.fc, t.fcn) == (9800.0, 12.0, 0.64, 0.91, 7.8, 2.5)
    assert T.Timber.of("A", "wet").fb == pytest.approx(12.0)
    with pytest.raises(T.TimberDesignError):
        T.Timber.of("D")


def test_species_table_6_11_1():
    teak = T.Timber.of("C", "inside", species="Teak")
    assert teak.species == "tectona-grandis"
    assert (teak.e, teak.fb, teak.fc, teak.fcn) == (9970.0, 15.5, 9.4, 4.5)
    assert T.Timber.of("C", "wet", species="Tectona grandis").fb == 10.3
    # Sal has no stresses in the table: the group's, with a note.
    sal = T.Timber.of("B", species="Sal")
    assert sal.fb == 12.0 and sal.notes
    # Misprinted rows carry no stresses (Amoora spp. E printed 1.05).
    assert not _table().species["amoora-spp"].has_stresses
    with pytest.raises(T.TimberDesignError):
        T.Timber.of("B", species="Bonsum")  # two species share the trade name


def test_grade_and_durability_sec_11_5_2():
    assert T.Timber.of("B", grade="select").fb == pytest.approx(12.0 * 1.16)
    assert T.Timber.of("B", grade="II").fc == pytest.approx(7.8 * 0.84)
    assert T.Timber.of("B", grade="II").e == 9800.0  # not on E
    # Low durability outside: x 0.80; durability class III species are low durability.
    assert T.Timber.of("B", "outside", low_durability=True).fb == pytest.approx(10.0 * 0.8)
    assert T.Timber.of("B", "inside", low_durability=True).fb == pytest.approx(12.0)
    hollock = T.Timber.of("C", "outside", species="Hollock")
    assert hollock.fb == pytest.approx(9.9 * 0.8)


def test_slope_of_grain_k1_table_6_11_10():
    assert T.slope_factor(10, False) == pytest.approx(0.80)
    assert T.slope_factor(10, True) == pytest.approx(0.74)
    assert T.slope_factor(13, False) == pytest.approx(0.94)
    assert T.slope_factor(14, True) == pytest.approx(0.80)  # printed 0.8, kept
    assert T.slope_factor(20, True) == 1.0
    with pytest.raises(T.TimberDesignError):
        T.slope_factor(8, False)


def test_duration_k2_table_6_11_11():
    assert T.duration_factor({"D": 1.0}) == 1.0
    assert T.duration_factor({"D": 1.0, "L": 1.0}, "twoMonths") == 1.15
    assert T.duration_factor({"D": 1.0, "L": 1.0}, "sevenDays") == 1.25
    assert T.duration_factor({"D": 1.0, "WX": 0.75, "L": 0.75}) == 1.33
    assert T.duration_factor({"D": 1.0, "L": 1.0}, "impact") == 2.0
    assert T.duration_factor({"D": 1.0, "EX": 0.7, "L": 0.75}, "impact") == 2.0


# ─────────────────────────── flexure: Sec 11.6.6 (pp. 298-304) ───────────────────────────


def test_form_factors_eqs_6_11_2_to_6_11_4():
    assert T.depth_factor(300) == 1.0
    assert T.depth_factor(400) == pytest.approx(0.81 * (160000 + 89400) / (160000 + 55000))
    # K4 with y = p1² (6 - 8p1 + 3p1²)(1 - q1) + q1 (q1 = 1: a solid section, y = 1).
    ratio = (400**2 + 89400) / (400**2 + 55000)
    assert T.box_form_factor(400, 0.1, 1.0) == pytest.approx(0.8 + 0.8 * (ratio - 1))
    p1, q1 = 0.1, 0.2
    y = p1**2 * (6 - 8 * p1 + 3 * p1**2) * (1 - q1) + q1
    assert T.box_form_factor(400, p1, q1) == pytest.approx(0.8 + 0.8 * y * (ratio - 1))
    assert T.Section(100, 100, "circle").form_factors()[0] == 1.18
    assert T.Section(150, 150).form_factors(diagonal=True)[0] == 1.414


def test_shear_formulas_eqs_6_11_5_and_6_11_6():
    s = T.Section(100, 200)
    assert s.shear_stress(10e3) == pytest.approx(3 * 10e3 / (2 * 100 * 200))
    tension = TimberNotch(face="tension", depth=40, length=100)
    assert T.notch_shear(10e3, 100, 200, tension) == pytest.approx(
        3 * 10e3 * 200 / (2 * 100 * 160**2)
    )
    far = TimberNotch(face="compression", depth=40, length=250)
    assert T.notch_shear(10e3, 100, 200, far) == pytest.approx(3 * 10e3 / (2 * 100 * 160))
    near = TimberNotch(face="compression", depth=40, length=100)
    assert T.notch_shear(10e3, 100, 200, near) == pytest.approx(
        3 * 10e3 / (2 * 100 * (200 - 40 / 200 * 100))
    )
    assert T.uniform_shear(20e3, 4000, 200) == pytest.approx(10e3 * (1 - 400 / 4000))
    x, d, length = 300.0, 200.0, 4000.0
    r = (x / d) ** 2
    assert T.concentrated_shear(10e3, length, x, d) == pytest.approx(
        10 * 10e3 * (length - x) * r / (9 * length * (2 + r))
    )
    assert T.concentrated_reduction(1.5) == 0.6
    assert T.concentrated_reduction(2.25) == pytest.approx(0.3)
    assert T.concentrated_reduction(4) == 0.0


def test_bearing_k7_table_6_11_13_and_eq_6_11_7():
    assert T.bearing_factor(15) == 1.67
    assert T.bearing_factor(75) == 1.13
    assert T.bearing_factor(200) == 1.0
    assert T.angle_bearing(7.8, 2.5, 0.0) == pytest.approx(7.8)
    assert T.angle_bearing(7.8, 2.5, math.pi / 2) == pytest.approx(2.5)


def test_deflection_limits_sec_11_6_6_9():
    d = _table().deflection
    assert (d.brittle, d.span, d.cantilever, d.deadLoadFactor) == (360.0, 240.0, 150.0, 2.0)
    # 4 m beam: 4 mm dead and 5 mm live at midspan: 2 x 4 + 5 = 13 mm against 4000/240.
    profiles = {
        "D": [(0.0, 0.0), (2.0, 4.0), (4.0, 0.0)],
        "L": [(0.0, 0.0), (2.0, 5.0), (4.0, 0.0)],
    }
    row = T.deflection_row(profiles, 1.0)
    assert row["demand"] == pytest.approx(13.0)
    assert row["capacity"] == pytest.approx(4000 / 240, abs=0.01)
    row = T.deflection_row(profiles, 1.0, TimberMember(brittleFinishes=True))
    assert row["capacity"] == pytest.approx(4000 / 360, abs=0.01)
    tip = {"D": [(0.0, 0.0), (1.5, 3.0)]}
    row = T.deflection_row(tip, 1.0, TimberMember(freeEnd="end"))
    assert row["demand"] == pytest.approx(6.0)
    assert row["capacity"] == pytest.approx(1500 / 150)


# ─────────────────────────── columns: Sec 11.6.7 (pp. 304-307) ───────────────────────────


def test_solid_column_eqs_6_11_9_to_6_11_11():
    fc, e = 7.8, 9800.0
    assert T.compression_stress(fc, e, 10.0) == (fc, "short")
    k8 = 0.702 * math.sqrt(e / fc)  # K8 printed 0.584: 0.702 kept (owner decision)
    value, kind = T.compression_stress(fc, e, 20.0)
    assert kind == "intermediate"
    assert value == pytest.approx(fc * (1 - (20.0 / k8) ** 4 / 3))
    value, kind = T.compression_stress(fc, e, 30.0)
    assert kind == "long"
    assert value == pytest.approx(0.329 * e / 30.0**2)
    assert _table().column.maxSlenderness == 50.0


def test_box_column_eqs_6_11_12_to_6_11_14():
    assert T.plank(25) == (0.8, 1.0)
    assert T.plank(30) == (0.6, 1.0)
    with pytest.raises(T.TimberDesignError):
        T.plank(40)
    fc, e = 7.8, 9800.0
    assert T.box_compression_stress(fc, e, 7.0, 0.8, 1.0) == (fc, "short")
    k9 = math.pi / 2 * math.sqrt(0.8 * e / (5 * fc))
    value, kind = T.box_compression_stress(fc, e, 15.0, 0.8, 1.0)
    assert kind == "intermediate"
    assert value == pytest.approx(fc * (1 - (15.0 / k9) ** 4 / 3), rel=1e-3)
    value, kind = T.box_compression_stress(fc, e, 30.0, 0.8, 1.0)
    assert kind == "long"
    assert value == pytest.approx(0.329 * 0.8 * e / 30.0**2)


def test_spaced_column_eqs_6_11_15_to_6_11_16():
    s = _table().spacedColumn
    assert (s.restraint["end20"], s.restraint["end10to20"], s.maxSlenderness) == (2.5, 3.0, 80.0)
    fc, e = 7.8, 9800.0
    value, kind = T.spaced_compression_stress(fc, e, 60.0, 2.5)
    assert kind == "long"
    assert value == pytest.approx(0.329 * e * 2.5 / 60.0**2)


# ─────────────────────────────── member checks ───────────────────────────────


def _stations(p: float, mx: float, v: float, name: str = "D + L") -> Stations:
    def a(x: float) -> np.ndarray:
        return np.array([x])

    return Stations(name, a(0.0), a(p), a(mx), a(0.0), a(v), a(0.0), ["mid"])


def test_beam_checks():
    section = T.Section(100, 200)
    timber = T.Timber.of("B")
    # M = 6 kN·m: fb = 9 MPa < 12; V = 10 kN: H = 0.75 MPa > 0.64.
    checks = T.check_member(section, timber, [_stations(0.0, 6e6, 10e3)], 3000, {})
    bending = next(c for c in checks if c["name"].startswith("Bending f = M/Z about the width"))
    assert bending["demand"] == pytest.approx(9.0)
    assert bending["capacity"] == pytest.approx(12.0)
    assert "Sec 11.6.6.3" in bending["name"]
    shear = next(c for c in checks if c["name"].startswith("Horizontal shear"))
    assert shear["demand"] == pytest.approx(0.75)
    assert not shear["ok"]
    # With wind, K2 = 1.33: the shear passes.
    checks = T.check_member(
        section, timber, [_stations(0.0, 6e6, 10e3, "D + WX")], 3000, {"D + WX": 1.33}
    )
    shear = next(c for c in checks if c["name"].startswith("Horizontal shear"))
    assert shear["capacity"] == pytest.approx(0.64 * 1.33, abs=0.01)
    assert shear["ok"]
    width = next(c for c in checks if c["name"].startswith("Least width"))
    assert width["demand"] == pytest.approx(max(50, 3000 / 50))


def test_beam_shear_at_one_depth_from_the_supports():
    # A 3 m beam, uniform load: V linear from 15 kN to -15 kN; at D = 0.2 m from each end 13 kN.
    s = np.linspace(0, 3, 7)
    v = 15e3 * (1 - 2 * s / 3)
    z = np.zeros_like(s)
    st = Stations("D + L", s, z, z, z, v, z, ["x"] * 7)
    checks = T.check_member(T.Section(100, 200), T.Timber.of("A"), [st], 3000, {})
    shear = next(c for c in checks if c["name"].startswith("Horizontal shear"))
    assert shear["demand"] == pytest.approx(1.5 * 13e3 / (100 * 200), abs=0.01)


def test_column_checks():
    section = T.Section(150, 150)
    timber = T.Timber.of("B")
    checks = T.check_member(section, timber, [_stations(50e3, 0.0, 0.0)], 3000, {}, "column")
    comp = next(c for c in checks if c["name"].startswith("Compression parallel"))
    fca, kind = T.compression_stress(7.8, 9800.0, 20.0)
    assert kind in comp["name"]
    assert comp["demand"] == pytest.approx(50e3 / 150**2, abs=0.01)
    assert comp["capacity"] == pytest.approx(fca, abs=0.01)
    assert any(c["name"].startswith("Slenderness S/d") for c in checks)
    # Columns use shear along the grain (Table 6.11.9 note 2).
    checks = T.check_member(section, timber, [_stations(5e3, 0.0, 5e3)], 3000, {}, "column")
    shear = next(c for c in checks if c["name"].startswith("Shear along the grain"))
    assert shear["capacity"] == pytest.approx(0.91)


def test_timber_material_and_template():
    from saengine.library.templates import TEMPLATES

    material = Material.model_validate(TEMPLATES["Material:timber"])
    assert T.is_timber(material)
    assert T.Timber.of_material(material).group == "B"


@dataclass
class _Piece:
    id: int
    forces: list
    sway: object = None
    sustained: object = None
    live: object = None


def test_asd_pieces_combine_the_cases():
    piece = _Piece(7, [np.zeros((2, 6))])
    d = {7: np.ones((2, 6))}
    w = {7: 2 * np.ones((2, 6))}
    out = T.asd_pieces([piece], {"D": d, "WX": w}, [{"D": 1.0, "WX": 0.75}, {"D": 0.6}])
    assert np.allclose(out[0].forces[0], 2.5)
    assert np.allclose(out[0].forces[1], 0.6)


def test_allowable_combinations_expand_wind_and_earthquake():
    combos = dict(T.allowable_combinations({"D", "SD", "L", "Lr", "WX", "WY", "EX", "EY"}))
    assert combos["D + L"] == {"D": 1.0, "SD": 1.0, "L": 1.0}
    assert combos["D + WX"] == {"D": 1.0, "SD": 1.0, "WX": 1.0}


# ─────────────────────────── joints: Sec 11.7, 11.9, 11.10 ───────────────────────────


def test_nail_tables_6_11_2_and_6_11_3():
    # Sal (Shorea robusta), N x 10^2 printed.
    assert T.lateral_nail_strength("3.55", "shorea-robusta", "lengthening", False) == 2300.0
    assert T.lateral_nail_strength("3.55", "shorea-robusta", "node", False) == 1550.0
    assert T.lateral_nail_strength("4", "tectona-grandis", "node", True) == 1300.0
    assert T.lateral_nail_strength("5", "dalbergia-sissoo", "lengthening", False) == 1700.0
    with pytest.raises(T.TimberDesignError):
        T.lateral_nail_strength("5", "canarium-strictum", "node", False)
    sp = _table().nails.spacing
    assert (sp.endTension, sp.endCompression, sp.alongTension, sp.alongCompression) == (
        12.0,
        10.0,
        10.0,
        5.0,
    )
    assert (sp.edge, sp.rows) == (5.0, 5.0)


def test_bolt_tables_and_eqs_6_11_19_to_6_11_21():
    lam1, lam2 = T.bolt_factors(4.0)
    assert (lam1, lam2) == (0.96, 0.60)
    lam1, lam2 = T.bolt_factors(11.0)
    assert lam1 is None and lam2 == 0.30
    fc, fcn, t, d = 7.8, 2.5, 64.0, 16.0
    a = t * d
    p = fc * a * 0.96
    r = fcn * a * 0.60 * 3.15
    assert T.bolt_capacity(fc, fcn, t, d, 0.0) == pytest.approx(p)
    assert T.bolt_capacity(fc, fcn, t, d, math.pi / 2) == pytest.approx(r)
    theta = math.radians(30)
    assert T.bolt_capacity(fc, fcn, t, d, theta) == pytest.approx(
        p * r / (p * math.sin(theta) ** 2 + r * math.cos(theta) ** 2)
    )
    assert T.bolt_capacity(fc, fcn, t, d, 0.0, single=True) == pytest.approx(p / 2)
    assert _table().bolts.diameterFactor["6"] == 5.70


def test_disc_dowel_figure_6_11_9():
    assert T.dowel_capacity(100, 30, 1.5, 11.7) == pytest.approx(
        min(math.pi * 1e4 / 4 * 1.5, 100 * 15 * 11.7)
    )


def test_joint_rows():
    from saengine.library.objects import TimberBoltedJoint, TimberNailedJoint

    section = T.Section(64, 150)
    timber = T.Timber.of("B", species="Teak")
    stations = [_stations(-20e3, 0.0, 0.0)]
    rows, summary = T.check_joint(TimberBoltedJoint(count=4), section, timber, stations, {})
    cap = next(r for r in rows if r["name"].startswith("Joint: 4 bolts"))
    assert cap["capacity"] == pytest.approx(
        4 * T.bolt_capacity(9.4, 4.5, 64, 16, 0.0) / 1e3, abs=0.01
    )
    end = next(r for r in rows if r["name"].startswith("Bolt end distance, tension"))
    assert end["demand"] == pytest.approx(5 * 16)
    rows, summary = T.check_joint(TimberNailedJoint(count=8), section, timber, stations, {})
    cap = next(r for r in rows if r["name"].startswith("Joint: 8 nails"))
    assert cap["capacity"] == pytest.approx(8 * 800 / 1e3)
    assert summary["strength"] == 800.0

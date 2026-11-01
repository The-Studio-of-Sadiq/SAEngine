"""Timber members to BNBC 2020 Part 6 Chapter 11 (permissible stress design, IS 883:1994
provisions) and the allowable stress combinations (Sec 2.7.3.2) (T45)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pytest

from saengine.design import timber as T
from saengine.design.steel.members import Stations
from saengine.library.materials import Material


def test_group_b_inside_stresses():
    t = T.Timber.of("B", "inside")
    assert (t.e, t.fb, t.fv, t.fc, t.fcp) == (9800.0, 12.0, 0.64, 7.8, 2.5)
    assert T.Timber.of("A", "wet").fb == 12.0
    with pytest.raises(T.TimberDesignError):
        T.Timber.of("D")


def test_depth_factor_k3():
    # IS 883 Sec 6.2.1.3: 1 up to 300 mm, 0.81 (D² + 89400) / (D² + 55000) above.
    assert T.depth_factor(300) == 1.0
    assert T.depth_factor(400) == pytest.approx(0.81 * (160000 + 89400) / (160000 + 55000))


def test_column_formulas_sec_7_3():
    fc, e = 7.8, 9800.0
    assert T.compression_stress(fc, e, 10.0) == (fc, "short")
    k8 = 0.702 * math.sqrt(e / fc)
    value, kind = T.compression_stress(fc, e, 20.0)
    assert kind == "intermediate"
    assert value == pytest.approx(fc * (1 - (20.0 / k8) ** 4 / 3))
    value, kind = T.compression_stress(fc, e, 30.0)
    assert kind == "long"
    assert value == pytest.approx(0.329 * e / 30.0**2)


def test_duration_factor():
    assert T.duration_factor(False) == 1.0
    assert T.duration_factor(True) == pytest.approx(4 / 3, abs=1e-3)


def test_allowable_combinations_expand_wind_and_earthquake():
    # A model without F, H and T: Sec 2.7.2.1 combination 2, D + H + F + L + T, is D + L.
    combos = dict(T.allowable_combinations({"D", "SD", "L", "Lr", "WX", "WY", "EX", "EY"}))
    assert combos["D + L"] == {"D": 1.0, "SD": 1.0, "L": 1.0}
    assert combos["D + WX"] == {"D": 1.0, "SD": 1.0, "WX": 1.0}
    assert combos["0.6D + 0.7(-EY)"]["EY"] == pytest.approx(-0.7)


def _stations(p: float, mx: float, v: float, name: str = "D + L") -> Stations:
    def a(x: float) -> np.ndarray:
        return np.array([x])

    return Stations(name, a(0.0), a(p), a(mx), a(0.0), a(v), a(0.0), ["mid"])


def test_beam_checks():
    section = T.Section(100, 200)
    timber = T.Timber.of("B")
    # M = 6 kN·m: fb = 6e6 / (100 · 200² / 6) = 9 MPa < 12; V = 10 kN: H = 0.75 MPa > 0.64.
    checks = T.check_member(section, timber, [_stations(0.0, 6e6, 10e3)], 3000, {})
    bending = next(c for c in checks if c["name"].startswith("Bending fb = M/Z about the width"))
    assert bending["demand"] == pytest.approx(9.0)
    assert bending["capacity"] == pytest.approx(12.0)
    shear = next(c for c in checks if c["name"].startswith("Horizontal shear"))
    assert shear["demand"] == pytest.approx(0.75)
    assert not shear["ok"]
    # With wind the stresses are a third higher: the shear passes.
    checks = T.check_member(
        section, timber, [_stations(0.0, 6e6, 10e3, "D + WX")], 3000, {"D + WX": "wind"}
    )
    shear = next(c for c in checks if c["name"].startswith("Horizontal shear"))
    assert shear["ok"]


def test_column_checks():
    section = T.Section(150, 150)
    timber = T.Timber.of("B")
    checks = T.check_member(section, timber, [_stations(50e3, 0.0, 0.0)], 3000, {}, "column")
    comp = next(c for c in checks if c["name"].startswith("Compression parallel"))
    fca, kind = T.compression_stress(7.8, 9800.0, 20.0)
    assert kind in comp["name"]
    assert comp["demand"] == pytest.approx(50e3 / 150**2, abs=0.01)
    assert comp["capacity"] == pytest.approx(fca, abs=0.01)
    assert any(c["name"].startswith("Slenderness Le/d") for c in checks)


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

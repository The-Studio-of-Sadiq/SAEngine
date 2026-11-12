"""Part 9 pile heads under lateral load: shear share, head moment and the pile section, by hand.

The expected values are plain statics (equivalent cantilever to the depth to fixity) and the
ACI 318-19 shear expressions worked out in the tests.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.library.objects import BarGroup, LinearReinforcement, Transverse
from saengine.substructure import pilecap, pilehead
from saengine.substructure.shallow import ColumnBase


def _bars(count: int = 8, dia: float = 16, tie: Transverse | None = None) -> LinearReinforcement:
    return LinearReinforcement(
        material="B420",
        cover=75,
        longitudinal=[BarGroup(position="perimeter", count=count, dia=dia)],
        transverse=tie,
    )


def test_head_actions_fixed_head_is_half_the_cantilever_moment() -> None:
    # 4 piles share Hu = 200 kN: 50 kN each; Lf = 4 m, fixed head: M = H Lf / 2 = 100 kN·m.
    out = pilehead.head_actions(np.array([200e3, 0.0]), 4, "fixed", 4000)
    assert out["H"][0] == pytest.approx(50e3)
    assert out["head"][0] == pytest.approx(100e6)
    assert out["design"] == pytest.approx(100e6)


def test_head_actions_free_head_moment_at_fixity_and_none_at_head() -> None:
    # Free (pinned) head: no moment at the head, H Lf = 50 kN × 4 m = 200 kN·m at fixity.
    out = pilehead.head_actions(np.array([120e3, 160e3]), 4, "free", 4000)
    assert np.allclose(out["head"], 0.0)
    assert out["design"] == pytest.approx(math.hypot(30e3, 40e3) * 4000)


def test_head_actions_without_depth_has_no_moment() -> None:
    out = pilehead.head_actions(np.array([100e3, 0.0]), 2, "fixed", None)
    assert out["design"] == 0.0
    assert out["H"][0] == pytest.approx(50e3)


def test_head_actions_rejects_unknown_fixity() -> None:
    with pytest.raises(ValueError):
        pilehead.head_actions(np.zeros(2), 1, "rotating", 1000)


def test_shear_capacity_with_minimum_ties_uses_simplified_vc() -> None:
    # Ø600, f'c 25, fy 420, hoops Ø10 @ 150 (two legs): bw = 600, d = 480 (ACI 22.5.2.2).
    # Av = 2 × 78.54 = 157.1 mm² ≥ Av,min = max(0.062 × 5, 0.35) × 600 × 150 / 420 = 75 mm².
    # Vc = 0.17 × 5 × 600 × 480 = 244.8 kN (Table 22.5.5.1 (a));
    # Vs = 157.1 × 420 × 480 / 150 = 211.1 kN; φVn = 0.75 × 455.9 = 341.9 kN.
    tie = Transverse(type="tie", dia=10, spacing=150)
    out = pilehead.shear_capacity(600, 25, 420, _bars(tie=tie))
    assert out["minimum"]
    assert out["Vc"] == pytest.approx(244.8e3, rel=1e-3)
    assert out["Vs"] == pytest.approx(2 * math.pi * 25 * 420 * 480 / 150, rel=1e-6)
    assert out["phiVn"] == pytest.approx(0.75 * (out["Vc"] + out["Vs"]))


def test_shear_capacity_without_ties_uses_rho_form() -> None:
    # 8Ø16 = 1608.5 mm², ρw = 804.2 / (600 × 480) = 0.002793; λs = √(2 / (1 + 1.92)) = 0.8276;
    # Vc = 0.66 × 0.8276 × 0.002793^(1/3) × 5 × 600 × 480 = 110.4 kN (Table 22.5.5.1 (c)).
    out = pilehead.shear_capacity(600, 25, 420, _bars())
    rho = 8 * math.pi * 64 / 2 / (600 * 480)
    expected = 0.66 * math.sqrt(2 / (1 + 0.004 * 480)) * rho ** (1 / 3) * 5 * 600 * 480
    assert not out["minimum"]
    assert out["Vc"] == pytest.approx(expected)
    assert out["Vs"] == 0.0


def test_plain_shear_capacity() -> None:
    # ACI 318-19 14.5.5.1 (a): φVn = 0.60 × 0.11 × √25 × 500 × 500 = 82.5 kN.
    assert pilehead.plain_shear_capacity(500, 25) == pytest.approx(82.5e3)


def test_section_checks_need_a_depth_to_fixity_for_moment() -> None:
    checks, detail = pilehead.section_checks(
        600, 25, 420, _bars(), {"U1": (800e3, 200e3)}, {"U1": np.array([100e3, 0])}, 4,
        "fixed", None,
    )  # fmt: skip
    assert checks == []
    assert "depth to fixity" in detail["note"]


def test_section_checks_report_pm_and_shear() -> None:
    checks, detail = pilehead.section_checks(
        600, 25, 420, _bars(), {"U1": (800e3, 200e3)}, {"U1": np.array([100e3, 0])}, 4,
        "fixed", 3000,
    )  # fmt: skip
    names = [c["name"] for c in checks]
    assert names == ["Pile section, axial + moment", "Pile section, shear"]
    # 25 kN per pile × 3 m / 2 = 37.5 kN·m.
    assert detail["M"] == pytest.approx(37.5)
    assert checks[0]["demand"] == pytest.approx(37.5)


def test_fixed_heads_add_to_cap_face_moment() -> None:
    # Four piles at ±600 in a 2000 × 2000 cap under one 500 mm column: beyond the +u face two
    # piles; with fixed heads of 40 kN·m each the face moment grows by 80 kN·m.
    spec = pilecap.CapSpec(
        id="PC1", length=2000, width=2000, thickness=900, cover=75, fc=25, fy=420,
        columns=[ColumnBase("C1", 0, 0, 500, 500)],
        piles=[(-600, -600), (600, -600), (600, 600), (-600, 600)], pile_diameter=500,
    )  # fmt: skip
    loads = {"U1": [np.array([2000e3, 0.0, 0.0])]}
    plain, _ = pilecap.cap_checks(spec, loads)
    fixed, _ = pilecap.cap_checks(spec, loads, head_moments={"U1": np.array([40e6, 0.0])})
    name = "Flexure bottom X at the column face"
    before = next(c for c in plain if c["name"].startswith(name))["demand"]
    after = next(c for c in fixed if c["name"].startswith(name))["demand"]
    assert after - before == pytest.approx(80.0, abs=0.1)

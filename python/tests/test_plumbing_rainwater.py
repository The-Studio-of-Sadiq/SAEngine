"""Rainwater (BNBC 2020 Part 8 Chapter 7, Tables 8.7.2-8.7.4, Appendix R)."""

from __future__ import annotations

import pytest

from saengine.library.mep import MepModel
from saengine.plumbing.building import Building
from saengine.plumbing.rainwater import (
    catchments,
    gutter_size,
    harvesting,
    intensity,
    leader_size,
    rainwater,
    storm_drain,
)
from saengine.verification.cases.plumbing import six_storey, six_storey_plumbing


def test_catchments_split_by_nearest_drain() -> None:
    mep, bim = six_storey()
    areas = {a["id"]: a["area"] for a in catchments(mep.plumbing, Building.of(bim))}
    # The 14 x 10 m roof split at x = 7 m between drains at x = 3.5 and 10.5 m.
    assert areas["RD1"] == pytest.approx(70.0)
    assert areas["RD2"] == pytest.approx(70.0)


def test_leader_sizes_at_88_mm() -> None:
    # Table 8.7.2 at 25 mm/h scaled by 25/88: 50 mm 57.4 m², 65 mm 104.3 m².
    assert leader_size(57.0, 88) == 50
    assert leader_size(70.0, 88) == 65
    assert leader_size(70.0, 25) == 50
    assert leader_size(8180 * 25 / 88 + 1, 88) is None
    assert gutter_size(70.0, 88, 10) == 125  # Table 8.7.3, 10 mm/m: 125 mm 320 x 25/88 = 91
    # Table 8.7.4: 140 m² at 10 mm/m: 100 mm 668 x 25/88 = 190 m².
    assert storm_drain(140.0, 88, 0.01) == (100, 10)
    assert storm_drain(140.0, 88, 0.005) == (None, None)


def test_report_and_two_drain_rule() -> None:
    mep, bim = six_storey()
    out = rainwater(mep.plumbing, Building.of(bim), 100)
    assert out["intensity"] == 88
    leaders = {r["id"]: r for r in out["leaders"]}
    assert leaders["RW1"]["area"] == pytest.approx(70) and leaders["RW1"]["diameter"] == 65
    assert leaders["RW1"]["inlet"] == 75  # one size bigger, Sec 7.8.11
    assert all(c["ok"] for c in out["checks"])
    data = six_storey_plumbing()
    data["roof"]["drains"] = data["roof"]["drains"][:1]
    one = MepModel.model_validate({"plumbing": data})
    out = rainwater(one.plumbing, Building.of(bim), 100)
    assert not out["checks"][0]["ok"]  # Sec 7.8.10: at least two drains


def test_intensity_and_harvesting() -> None:
    mep = MepModel.model_validate({"plumbing": {}})
    assert intensity(mep.plumbing)[0] == 88  # Appendix R, Dhaka
    bim = six_storey()[1]
    small = harvesting(mep.plumbing, Building.of(bim), 100)
    assert small["required"] is None  # 140 m² footprint, plot unknown
    plot = MepModel.model_validate(
        {"plumbing": {"roof": {"plotArea": 400, "harvest": {"demand": 20}}}}
    )
    out = harvesting(plot.plumbing, Building.of(bim), 100)
    # Sec 7.4.1: 400 >= 300 m²; Sec 7.8.9: 20 lpcd x 100 x 210 days / 1000 = 420 m³.
    assert out["required"] is True
    assert out["volume"] == pytest.approx(420)

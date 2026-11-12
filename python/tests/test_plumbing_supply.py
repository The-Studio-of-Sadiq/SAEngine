"""Water risers, pump main and heads (BNBC 2020 Part 8 Sec 5.10, Appendix O)."""

from __future__ import annotations

import math

import pytest

from saengine.library.mep import MepModel
from saengine.plumbing.building import Building
from saengine.plumbing.supply import (
    capacity,
    head_loss,
    heads,
    pump,
    pump_main,
    size_pipe,
    supply_riser,
    velocity_limit,
)
from saengine.verification.cases.plumbing import six_storey


def test_velocity_limits_of_sec_5101() -> None:
    assert velocity_limit(13) == pytest.approx(0.30)
    assert velocity_limit(50) == pytest.approx(0.60)
    assert velocity_limit(75) == pytest.approx(0.75)
    assert velocity_limit(100) == pytest.approx(0.90)
    assert velocity_limit(125) == pytest.approx(1.025)
    assert velocity_limit(300) == pytest.approx(1.30)


def test_hazen_williams_head_loss() -> None:
    # 5.37 l/s in 65 mm, C = 150: 10.67 Q^1.852 / (C^1.852 d^4.87) = 3.76 m per 100 m.
    q = 0.00537
    expected = 10.67 * q**1.852 / (150**1.852 * 0.065**4.87) * 100
    assert head_loss(q * 60000, 65, 150) == pytest.approx(expected)
    assert expected == pytest.approx(3.76, rel=0.01)


def test_size_pipe() -> None:
    # 260.5 l/min = 4.342 l/s: 75 mm allows 0.75 m/s x 4.418e-3 m² = 3.31 l/s, too little;
    # 100 mm allows 0.90 x 7.854e-3 = 7.07 l/s (and 0.31 m/100 m friction).
    size = size_pipe(260.5, "uPVC")
    assert size["diameter"] == 100
    assert size["velocity"] == pytest.approx(260.5 / 60000 / (math.pi / 4 * 0.01))
    assert size_pipe(5, "uPVC", minimum=19)["diameter"] == 19  # 0.29 <= 0.35 m/s
    assert size_pipe(10, "uPVC", minimum=19)["diameter"] == 25  # 0.59 > 0.35 m/s
    assert capacity(100) == pytest.approx(0.9 * math.pi / 4 * 0.01 * 60000)


def test_riser_of_the_six_storey_building() -> None:
    mep, bim = six_storey()
    building = Building.of(bim)
    r1 = next(r for r in mep.plumbing.risers if r.id == "R1")
    out = supply_riser(r1, mep.plumbing, building)
    # Two flats of 22 wsfu a floor on R1 (R2 takes the other two), five floors: 220.
    assert out["units"] == pytest.approx(220)
    assert out["flow"] == pytest.approx(260.5)  # Table 8.5.5, flush tanks, 220 units
    assert out["diameter"] == 100 and out["ok"]
    # Down-feed: through L2's slab it carries L1 (44 units), through the roof slab all.
    segments = {s["story"]: s for s in out["segments"]}
    assert segments["L2"]["units"] == pytest.approx(44)
    assert segments["ROOF"]["units"] == pytest.approx(220)
    assert segments["L1"]["units"] == 0 and segments["L1"]["diameter"] == 19
    # A user diameter that is too small fails.
    small = r1.model_copy(update={"diameter": 50})
    checked = supply_riser(small, mep.plumbing, building)
    assert not checked["ok"] and checked["required"] == 100


def test_pump_and_pump_main() -> None:
    mep, _ = six_storey()
    result = pump(mep.plumbing, 18000)
    assert result["flow"] == pytest.approx(41.25)  # Eq 8.5.1 peak hourly
    hours = MepModel.model_validate({"plumbing": {"supply": {"pumpHours": 6}}})
    assert pump(hours.plumbing, 18000)["flow"] == pytest.approx(18000 / 6 / 60)
    main = next(r for r in mep.plumbing.risers if r.id == "P1")
    out = pump_main(main, 41.25)
    # 41.25 l/min: 38 mm allows 0.53 m/s x 1.134e-3 m² = 36 l/min; 50 mm 70.7 l/min.
    assert out["diameter"] == 50


def test_heads() -> None:
    mep, bim = six_storey()
    out = heads(mep.plumbing, Building.of(bim))
    assert out["minResidualHead"] == pytest.approx(55 / 9.807)  # Table 8.5.6, 55 kPa
    assert out["maxStaticHead"] == 35
    assert out["highestFixtureLevel"] == pytest.approx(15.0)
    assert out["zones"] == 1

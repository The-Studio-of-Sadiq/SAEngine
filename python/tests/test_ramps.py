"""Ramp checks (track B24): the code pack's ramp rules (accessibility table) and the generic
checks of saengine.design.ramps, pinned through the bnbc2020 pack.

Values: BNBC 2020 Part 3 Sec 1.2 (p. 44), 1.14.11.5 (p. 70), Appendix D Table 3.D.2 (p. 228),
D.11.1 (p. 236), Appendix F Table 3.F.5 (p. 272), F.7.3.2-F.7.3.3 (p. 273); Part 4 Sec 3.11
(p. 315)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from saengine.codes import context as code_context
from saengine.codes.tables import builtin_table
from saengine.design import ramps as ramp_checks
from saengine.library import architecture as arch_lib
from saengine.rpc import handlers


def build(ramps: list[dict], railings: list[dict] | None = None) -> arch_lib.Architecture:
    base = arch_lib.default_architecture().model_dump(mode="json", by_alias=True)
    base["ramps"] = [{"story": "L1", "start": [0, 0], **r} for r in ramps]
    base["railings"] = [{"type": "RL1", "base": "L1", **r} for r in railings or []]
    return arch_lib.Architecture.model_validate(base)


def both_rails(run: float, width: float) -> list[dict]:
    """Railings on the edges of a ramp along +x from the origin."""
    half = width / 2
    return [
        {"id": "HL", "path": [[0, half], [run, half]]},
        {"id": "HR", "path": [[0, -half], [run, -half]]},
    ]


def one(arch: arch_lib.Architecture, ramp_id: str = "RP1") -> dict:
    result = ramp_checks.check_ramps(arch)
    return next(r for r in result["ramps"] if r["id"] == ramp_id)


def status(result: dict, check: str) -> str:
    return next(c["status"] for c in result["checks"] if c["check"] == check)


# ─────────────────────────────────────── the pack's values ───────────────────────────────────────


def test_pack_values_pinned() -> None:
    table = builtin_table("accessibility")
    assert table.rampThreshold.oneIn == 20  # Part 3 Sec 1.2 'Ramp', Part 4 Sec 3.11.1
    walk, acc, exit_, vehicle, parking = (
        table.ramps[k] for k in ("walkway", "accessible", "exit", "vehicle", "parking")
    )
    assert walk.maxSlope.oneIn == 8  # Part 3 Sec 1.14.11.5 (p. 70)
    assert (walk.flight.min, walk.flight.max) == (915, 9150)  # Part 4 Sec 3.11.6
    assert walk.landing.min == 915 and walk.landing.atLeastWidth  # Part 4 Sec 3.11.7
    # Table 3.D.2 (p. 228): rise, run and slope rows.
    assert [(b.riseMax, b.runMax, b.oneIn) for b in acc.byRise] == [
        (75, 600, 8),
        (150, 1500, 10),
        (None, 9000, 12),
    ]
    assert acc.width.min == 1200 and acc.landing.min == 1500  # Sec D.11.1 (p. 236)
    assert acc.handrails.steeperThan is None
    assert exit_.maxSlope.oneIn == 8  # Part 4 Sec 3.11.3
    assert any(n.steeperThan == 10 for n in exit_.notes)  # non-slip above 1 in 10
    assert vehicle.maxSlope.oneIn == 8  # F.7.3.2: 12.5 %
    assert vehicle.transitions.oneIn == 5 and vehicle.transitions.transitionShare == 0.5  # 20 %
    assert vehicle.width.byLanes == {1: 3600, 2: 6000}  # Table 3.F.5(a)
    assert parking.maxSlope.oneIn == 20  # F.7.3.3: 5 %
    assert not vehicle.walking and not parking.walking


def test_ramp_kind_defaults_to_walkway() -> None:
    ramp = arch_lib.Ramp.model_validate({"id": "R", "story": "L1", "start": [0, 0], "end": [1, 0]})
    assert (ramp.kind, ramp.lanes, ramp.transitions) == ("walkway", 1, False)


# ───────────────────────────────────────── accessible ramps ─────────────────────────────────────────


def test_accessible_ramp_at_1_in_12_passes() -> None:
    arch = build(
        [{"id": "RP1", "kind": "accessible", "end": [7200, 0], "rise": 600, "width": 1200}],
        both_rails(7200, 1200),
    )
    result = one(arch)
    assert result["covered"] and result["ok"], result["checks"]
    assert result["slope"] == "1 in 12.0"
    assert {c["check"] for c in result["checks"]} >= {"gradient", "run", "width", "handrails"}


@pytest.mark.parametrize(
    ("rise", "run", "gradient", "run_ok"),
    [
        (50, 400, "pass", True),  # 1 in 8 up to 75 mm
        (60, 400, "fail", True),  # 1 in 6.7
        (100, 1000, "pass", True),  # 1 in 10 up to 150 mm
        (100, 900, "fail", True),  # 1 in 9
        (120, 1600, "pass", False),  # run over 1500 mm
        (600, 6000, "fail", True),  # 1 in 10 above 150 mm
        (800, 10000, "pass", False),  # run over 9000 mm: needs a landing
    ],
)
def test_accessible_gradient_by_rise(rise, run, gradient, run_ok) -> None:
    arch = build(
        [{"id": "RP1", "kind": "accessible", "end": [run, 0], "rise": rise, "width": 1500}],
        both_rails(run, 1500),
    )
    result = one(arch)
    assert status(result, "gradient") == gradient
    assert status(result, "run") == ("pass" if run_ok else "fail")


def test_accessible_width_and_handrails() -> None:
    arch = build(
        [{"id": "RP1", "kind": "accessible", "end": [7200, 0], "rise": 600, "width": 1100}],
        both_rails(7200, 1100)[:1],
    )
    result = one(arch)
    assert status(result, "width") == "fail" and status(result, "handrails") == "fail"
    assert not result["ok"] and ramp_checks.check_ramps(arch)["failing"] == ["RP1"]


def test_landing_between_flights() -> None:
    def chain(gap: float) -> arch_lib.Architecture:
        return build(
            [
                {"id": "RP1", "kind": "accessible", "end": [6000, 0], "rise": 500, "width": 1200},
                {
                    "id": "RP2",
                    "kind": "accessible",
                    "start": [6000 + gap, 0],
                    "end": [12000 + gap, 0],
                    "rise": 500,
                    "width": 1200,
                },
            ]
        )

    assert status(one(chain(1400)), "landing") == "fail"
    assert status(one(chain(1500)), "landing") == "pass"


# ─────────────────────────────────────── walkway and exit ramps ───────────────────────────────────────


def test_walkway_slope_limit_and_threshold() -> None:
    def walk(rise: float, run: float) -> dict:
        return one(build([{"id": "RP1", "end": [run, 0], "rise": rise}], both_rails(run, 1500)))

    assert status(walk(500, 4000), "gradient") == "pass"  # 1 in 8
    assert status(walk(500, 3500), "gradient") == "fail"  # 1 in 7
    level = walk(100, 2500)  # 1 in 25: not a ramp
    assert level["ok"] and [c["check"] for c in level["checks"]] == ["threshold"]


def test_exit_ramp_flight_and_non_slip_note() -> None:
    short = one(build([{"id": "RP1", "kind": "exit", "end": [800, 0], "rise": 80}]))
    assert status(short, "flight") == "fail"  # under 915 mm
    long = one(
        build(
            [{"id": "RP1", "kind": "exit", "end": [9200, 0], "rise": 1000}], both_rails(9200, 1500)
        )
    )
    assert status(long, "flight") == "fail"  # over 9150 mm between landings
    steep = one(build([{"id": "RP1", "kind": "exit", "end": [4500, 0], "rise": 500}]))
    gentle = one(build([{"id": "RP1", "kind": "exit", "end": [6000, 0], "rise": 500}]))

    def notes(result: dict) -> list[str]:
        return [c["source"] for c in result["checks"] if c["status"] == "note"]

    # Non-slip surface above 1 in 10 (Part 4 Sec 3.11.3) only.
    assert sum("3.11.3" in s for s in notes(steep)) == 1
    assert sum("3.11.3" in s for s in notes(gentle)) == 0


# ─────────────────────────────────────── vehicle and parking ramps ───────────────────────────────────────


def test_vehicle_ramp_gradient_transitions_and_width() -> None:
    def vehicle(rise: float, run: float, **extra) -> dict:
        ramp = {"id": "RP1", "kind": "vehicle", "end": [run, 0], "rise": rise, "width": 3600}
        return one(build([{**ramp, **extra}]))

    assert vehicle(1000, 8000)["ok"]  # 12.5 %
    steep = vehicle(1000, 6000)  # 16.7 %
    assert status(steep, "gradient") == "fail"
    assert any("1.10.2" in c["source"] for c in steep["checks"] if c["status"] == "note")
    assert status(vehicle(1000, 6000, transitions=True), "gradient") == "pass"  # up to 20 %
    assert status(vehicle(1000, 4500, transitions=True), "gradient") == "fail"  # 22 %
    assert status(vehicle(1000, 8000, width=3500), "width") == "fail"
    assert status(vehicle(1000, 8000, width=6000, lanes=2), "width") == "pass"
    assert status(vehicle(1000, 8000, width=5900, lanes=2), "width") == "fail"
    # No walking ramp rules on a vehicle ramp: no threshold, flight or handrails.
    assert {c["check"] for c in vehicle(100, 8000)["checks"]} <= {"gradient", "width", "note"}


def test_parking_ramp() -> None:
    def parking(run: float) -> dict:
        return one(build([{"id": "RP1", "kind": "parking", "end": [run, 0], "rise": 300}]))

    assert status(parking(6000), "gradient") == "pass"  # 5 %
    assert status(parking(4500), "gradient") == "fail"  # 6.7 %


# ─────────────────────────────────────── coverage and the backend ───────────────────────────────────────


def test_a_pack_without_ramp_rules_does_not_cover_them(monkeypatch) -> None:
    pack = SimpleNamespace(name="Stub code", has=lambda name: False)
    monkeypatch.setattr(code_context, "current", lambda: pack)
    arch = build([{"id": "RP1", "end": [3000, 0], "rise": 500}])
    result = ramp_checks.check_ramp(arch, arch.ramps[0])
    assert result["covered"] is False and result["ok"] and "Stub code" in result["message"]


def test_backend_handler() -> None:
    arch = build([{"id": "RP1", "end": [3500, 0], "rise": 500}])
    text = json.dumps(arch.model_dump(mode="json", by_alias=True))
    answer = handlers.architecture_ramps(text, None)
    assert answer["problems"] == [] and answer["failing"] == ["RP1"]
    assert answer["pack"] == "BNBC 2020"
    assert handlers.architecture_ramps("{", None)["problems"]

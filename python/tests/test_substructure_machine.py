"""Machine and generator foundations (saengine.substructure.machine): the machine group of the
bnbc2020 foundations table pinned with its clauses (BNBC 2020 Part 6 Sec 3.20, pp. 807-814),
the relations of Eqs 6.3.51-6.3.59 and the checks that read them."""

from __future__ import annotations

import math

import pytest

from saengine.codes.tables import builtin_table
from saengine.library.substructure import MachineFoundation, Substructure
from saengine.substructure import machine as mc

# ─────────────────────────────── the pack's values ───────────────────────────────


def test_machine_rules_from_the_pack() -> None:
    """Sec 3.20.1 (p. 807): impact over 50% of the dead load; Sec 3.20.2.2 (pp. 809-810):
    low speed under 300 rpm with f/fn < 0.5, high speed over 1000 rpm with f/fn >= 2,
    amplitudes 0.25 mm under 500 rpm, 0.4-0.6 / 0.7-0.9 mm at 500-1500 rpm, 0.2 / 0.5 mm to
    3000 rpm, hammers 10 mm, eccentricity 5%; Sec 3.20.2.3 (pp. 810-811): 80% of qa, water
    B/4 below the base; Sec 3.20.2.5 (pp. 812-814): ms 0 to mf, Barkan 1.13, plate 0.3 m,
    D 0.01-0.1."""
    t = builtin_table("foundations")
    r = t.machine
    assert r.method == "lumpedSdof"
    assert r.impactRatio == 0.5
    assert [(c.id, c.upTo, c.allowed) for c in r.speedClasses] == [
        ("low", 300, ["below"]),
        ("medium", 1000, ["below", "above"]),
        ("high", None, ["above"]),
    ]
    assert (r.frequencyRatioBelow, r.frequencyRatioAbove) == (0.5, 2.0)
    rows = [(a.upTo, a.horizontal, a.vertical) for a in r.amplitudes]
    assert rows == [
        (500, (0.25, 0.25), (0.25, 0.25)),
        (1500, (0.4, 0.6), (0.7, 0.9)),
        (3000, (0.2, 0.2), (0.5, 0.5)),
    ]
    assert r.hammerAmplitude == 10
    assert (r.staticPressure, r.eccentricity, r.waterDepth) == (0.8, 0.05, 0.25)
    assert r.participatingMass == (0, 1)
    assert r.damping == (0.01, 0.1)
    assert (r.barkanCoefficient, r.plateOffset) == (1.13, 0.3)
    assert r.barkanPoisson == ["linear", "square"]
    assert r.decrement == "exact"
    assert r.hysteresisDivisor == pytest.approx(4 * math.pi, abs=1e-5)
    assert "3.20.1" in t.sources["machine.impactRatio"]
    assert "6.3.53" in t.sources["machine.barkanPoisson"]
    assert "6.3.59" in t.sources["machine.hysteresisDivisor"]


def test_speed_classes_and_permissible_amplitudes() -> None:
    r = builtin_table("foundations").machine
    assert mc.speed_class(r, 299).id == "low"
    assert mc.speed_class(r, 300).id == "medium"
    assert mc.speed_class(r, 1000).id == "medium"
    assert mc.speed_class(r, 1001).id == "high"
    assert mc.permissible(r, 499, "vertical") == 0.25
    # 500-1500 rpm: the low end of the printed range.
    assert mc.permissible(r, 500, "horizontal") == 0.4
    assert mc.permissible(r, 1500, "vertical") == 0.7
    assert mc.permissible(r, 3000, "horizontal") == 0.2
    assert mc.permissible(r, 3000, "vertical") == 0.5
    assert mc.permissible(r, 3600, "vertical") is None


# ─────────────────────────────── the relations ───────────────────────────────


def test_stiffness_relations() -> None:
    """Eqs 6.3.53-6.3.57 (p. 813)."""
    # Barkan: 1.13 E √A / (1 - μ) and / (1 - μ²), E = 30 MPa, A = 12 m², μ = 0.35.
    root = 1.13 * 30000 * math.sqrt(12)
    assert mc.barkan_stiffness(30000, 0.35, 12, 1.13, "linear") == pytest.approx(root / 0.65)
    assert mc.barkan_stiffness(30000, 0.35, 12, 1.13, "square") == pytest.approx(root / 0.8775)
    # Plate: cohesive kp B/Bp; cohesionless kp ((B + 0.3)/(Bp + 0.3))².
    assert mc.plate_stiffness(20000, 3.0, 0.3, True, 0.3) == pytest.approx(200000)
    assert mc.plate_stiffness(20000, 3.0, 0.3, False, 0.3) == pytest.approx(20000 * 5.5**2)
    assert mc.subgrade_stiffness(15000, 12) == 180000
    # Resonance test: k = 4π² fn² m (the printed 4π² fn m lacks the square).
    assert mc.resonance_stiffness(10, 0.5) == pytest.approx(4 * math.pi**2 * 100 * 0.5)


def test_damping_relations() -> None:
    """Eq 6.3.58: the exact inverse is below δ/2π; Eq 6.3.59 with 4π (p. 814)."""
    exact = mc.damping_from_decrement(0.5, "exact")
    assert exact == pytest.approx(0.5 / math.sqrt(4 * math.pi**2 + 0.25))
    assert exact < mc.damping_from_decrement(0.5, "approximate") == pytest.approx(0.5 / 2 / math.pi)
    # δ = 2πD/√(1 - D²) round trip.
    assert 2 * math.pi * exact / math.sqrt(1 - exact**2) == pytest.approx(0.5)
    assert mc.damping_from_hysteresis(1.0, 2.0, 4 * math.pi) == pytest.approx(1 / (8 * math.pi))
    assert mc.natural_frequency(4 * math.pi**2, 1.0) == pytest.approx(1.0)
    assert mc.magnification(0.0, 0.05) == 1.0
    assert mc.magnification(1.0, 0.05) == pytest.approx(10.0)


# ─────────────────────────────── the checks ───────────────────────────────


def _spec(**changes: object) -> MachineFoundation:
    data: dict[str, object] = {
        "id": "MF1",
        "length": 4000,
        "width": 3000,
        "height": 1500,
        "foundingLevel": -1500,
        "machineMass": 10,
        "speed": 1500,
        "force": 2.0,
        "E": 30,
    }
    data.update(changes)
    return MachineFoundation.model_validate(data)


def _soil(**changes: object) -> mc.MachineSoil:
    soil = mc.MachineSoil(qa=150, qa_note="given", water_below_base=3.0, water_source="given")
    for key, value in changes.items():
        setattr(soil, key, value)
    return soil


def _by_name(found: dict, name: str) -> dict:
    return next(c for c in found["checks"] if c["name"] == name)


def test_high_speed_generator_passes() -> None:
    """A 1500 rpm generator on a 4 × 3 × 1.5 m block (43.2 t) on E = 30 MPa: f/fn >= 2 over
    the envelope (k by both Barkan forms, m from mf to 2 mf)."""
    found = mc.machine_checks(_spec(), _soil(), 43.2)
    dyn = found["dynamics"]
    assert dyn["mass"] == [53.2, 106.4]
    assert [s["k"] for s in dyn["springs"]] == [180666, 133827]
    stiffest = mc.natural_frequency(180666.0, 53.2)
    assert dyn["naturalFrequency"][1] == pytest.approx(stiffest, abs=0.01)
    resonance = _by_name(found, "Resonance (vertical)")
    assert resonance["ok"]
    assert resonance["utilisation"] == pytest.approx(2.0 / (25 / stiffest), abs=1e-3)
    amplitude = _by_name(found, "Amplitude (vertical)")
    assert amplitude["capacity"] == 0.7 and amplitude["ok"]
    starting = _by_name(found, "Amplitude at resonance (starting)")
    assert starting["capacity"] > 0
    # Static: 53.2 × 9.81 / 12 = 43.5 kPa ≤ 0.8 × 150.
    static = _by_name(found, "Static soil pressure")
    assert static["demand"] == pytest.approx(53.2 * 9.81 / 12, abs=0.01)
    assert static["capacity"] == 120
    assert _by_name(found, "Ground water below the base")["ok"]
    assert any("Horizontal mode not checked" in n for n in found["requirements"])


def test_low_speed_machine_needs_a_stiff_foundation() -> None:
    """A 250 rpm compressor: f/fn must stay below 0.5; on soft soil it fails."""
    soft = mc.machine_checks(_spec(speed=250, E=2, kind="periodic"), _soil(), 43.2)
    assert not _by_name(soft, "Resonance (vertical)")["ok"]
    stiff = mc.machine_checks(_spec(speed=250, E=200, kind="periodic"), _soil(), 43.2)
    assert _by_name(stiff, "Resonance (vertical)")["ok"]
    # Under 500 rpm the permissible amplitude is 0.25 mm.
    assert _by_name(stiff, "Amplitude (vertical)")["capacity"] == 0.25


def test_hammer_impact_and_rules() -> None:
    hammer = mc.machine_checks(
        _spec(kind="impact", speed=100, E=200, impulse=5.0, force=None), _soil(), 43.2
    )
    blow = _by_name(hammer, "Amplitude under a blow")
    assert blow["capacity"] == 10
    k, m = 1.13 * 200000 * math.sqrt(12) / 0.8775, 53.2
    assert blow["demand"] == pytest.approx(5.0 / (m * math.sqrt(k / m)) * 1e3, abs=0.01)
    assert any("Impact forces" in n for n in hammer["requirements"])
    # Impact rule: live load causing impact over half the dead load.
    heavy = mc.machine_checks(_spec(impactLoad=0.6 * 53.2 * 9.81), _soil(), 43.2)
    assert any("Impact forces" in n for n in heavy["requirements"])
    light = mc.machine_checks(_spec(impactLoad=0.4 * 53.2 * 9.81), _soil(), 43.2)
    assert not any("Impact forces" in n for n in light["requirements"])


def test_eccentricity_water_and_adjacent() -> None:
    # 10 t at 1.2 m off a 53.2 t system: 0.226 m = 5.6% of L = 4 m.
    found = mc.machine_checks(
        _spec(machineOffset=[1200, 0], adjacentFoundingLevel=-1000, separated=False),
        _soil(water_below_base=0.5),
        43.2,
    )
    ecc = _by_name(found, "Eccentricity")
    assert ecc["demand"] == pytest.approx(10 * 1.2 / 53.2 / 4 * 100, abs=0.01)
    assert not ecc["ok"]
    water = _by_name(found, "Ground water below the base")
    assert water["demand"] == 0.75 and not water["ok"]  # 0.25 × B = 3 m
    assert _by_name(found, "Below the adjacent foundations")["ok"]
    assert not _by_name(found, "Separated from the building")["ok"]


def test_springs_from_the_soil_report_and_tests() -> None:
    # Subgrade: k = ks A.
    found = mc.machine_checks(
        _spec(stiffnessMethod="subgrade", E=None), _soil(ks=15000, ks_source="report"), 43.2
    )
    assert found["dynamics"]["springs"][0]["k"] == 180000
    # G from a torsional test: E = 2G(1 + μ).
    found = mc.machine_checks(_spec(E=None, G=10), _soil(), 43.2)
    assert "E = 2G(1 + μ)" in found["dynamics"]["springs"][0]["note"]
    # Soil report's E when none is entered.
    found = mc.machine_checks(_spec(E=None), _soil(E=30.0, E_source="layers"), 43.2)
    assert found["dynamics"]["springs"][0]["k"] == 180666
    # No spring: a flagged check.
    found = mc.machine_checks(_spec(E=None), _soil(), 43.2)
    assert _by_name(found, "Soil spring")["flag"]
    # Damping: the low end of the range without a test; from δ with one.
    assert found["dynamics"]["damping"] == 0.01
    found = mc.machine_checks(_spec(decrement=0.5), _soil(), 43.2)
    assert found["dynamics"]["damping"] == pytest.approx(mc.damping_from_decrement(0.5), abs=1e-4)


def test_not_covered_and_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Substructure.model_validate({"machineFoundations": [_spec().model_dump(exclude_none=True)]})
    assert s.machineFoundations[0].stiffnessMethod == "barkan"
    with pytest.raises(ValueError):
        Substructure.model_validate(
            {"machineFoundations": [_spec().model_dump(), _spec().model_dump()]}
        )
    monkeypatch.setattr(mc, "rules", lambda: None)
    with pytest.raises(LookupError, match="not covered"):
        mc.machine_checks(_spec(), _soil(), 43.2)


def test_in_the_substructure_report() -> None:
    """Machine foundations are designed by the substructure report without an analysis."""
    import json

    from test_fem_derive import OBJECTS, PLAN, SETTINGS

    from saengine.library import default_material_library
    from saengine.library.bim import generate
    from saengine.substructure.context import Context
    from saengine.substructure.report import report

    substructure = Substructure.model_validate(
        {"machineFoundations": [_spec().model_dump(exclude_none=True)]}
    )
    ctx = Context(
        substructure=substructure,
        building=generate(PLAN, "s"),
        objects=OBJECTS,
        materials=default_material_library(),
        settings=SETTINGS,
    )
    data = report(ctx)
    json.dumps(data)
    (block,) = data["machineFoundations"]
    assert block["type"] == "machineFoundation"
    assert block["sizes"]["blockMass"] > 0
    assert any("3.20" in m for m in data["method"])

"""P3: pushover hinges (ASCE 41-17 in the US pack, EN 1998-3 in the Eurocodes pack) and the
target displacement methods displacementCoefficient (ASCE 41-17 Eqs 7-28 to 7-30),
equivalentLinearization (FEMA 440) and n2 (EN 1998-1 Annex B)."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.fem import hinges as H
from saengine.fem import pushover_target as pt

US, EU = "aci318-asce7-22", "eurocodes"
G = pt.G


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


def pushover(pack_id: str):
    return registry.load(pack_id).table("pushover")


def epp(k: float, vy: float, top: float, n: int = 400) -> tuple[np.ndarray, np.ndarray]:
    d = np.linspace(0.0, top, n + 1)
    return d, np.minimum(k * d, vy)


# ── the packs ──


def test_bnbc_pack_keeps_its_methods() -> None:
    table = pushover("bnbc2020")
    assert table.targetDisplacement.method == "coefficient"
    assert table.acceptance.method == "fibreStrain"
    assert table.hinges is None and table.targetDisplacement.hazards == []
    assert table.procedure.noDropToTarget == 1.25


def test_us_pack_values() -> None:
    table = pushover(US)
    target = table.targetDisplacement
    assert target.method == "displacementCoefficient"  # ASCE 41-17 Sec 7.4.3.3.2
    k = target.coefficients
    # Eq 7-29: a = 130 (A, B), 90 (C), 60 (D, E, F); C1 at 0.2 s below, 1 above 1.0 s.
    assert (k.siteFactors["SB"], k.siteFactors["SC"], k.siteFactors["SD"]) == (130, 90, 60)
    assert (k.c1PeriodMin, k.c1PeriodMax) == (0.2, 1.0)
    assert (k.c2PeriodMax, k.c2Divisor) == (0.7, 800)  # Eq 7-30
    # Sec 2.2.1, 2.4.1: LS at BSE-1N (2/3 MCER), CP at BSE-2N (MCER).
    assert [(h.id, h.spectrumScale, h.level) for h in target.hazards] == [
        ("BSE-1N", 1.0, "LS"),
        ("BSE-2N", 1.5, "CP"),
    ]
    assert table.procedure.noDropToTarget is None
    hinges = table.hinges
    assert [lv.id for lv in hinges.levels] == ["IO", "LS", "CP"]
    assert set(hinges.components) == set(H.COMPONENTS)


def test_eurocodes_pack_values() -> None:
    table = pushover(EU)
    assert table.targetDisplacement.method == "n2"  # EN 1998-1 Annex B
    assert table.targetDisplacement.n2.maxElasticMultiple == 3.0
    rule = table.hinges.components["rcColumn"].chordRotation  # EN 1998-3 Eq A.1
    assert (rule.gammaEl, rule.k, rule.axialBase) == (1.5, 0.016, 0.3)
    assert (rule.omegaExponent, rule.spanExponent, rule.confinementBase) == (0.225, 0.35, 25)
    assert rule.shares == {"SD": 0.75, "NC": 1.0} and rule.yieldLevel == "DL"


# ── the hinge models ──


def test_rc_beam_table_interpolates() -> None:
    # ASCE 41-17 Table 10-7, condition i, conforming: halfway on both variables.
    beam = pushover(US).hinges.components["rcBeam"]
    found = H.lookup(
        beam, {"control": "flexure", "conforming": "C", "rhoBalance": 0.25, "shearStress": 4.5}
    )
    assert found["a"] == pytest.approx(0.02)
    assert found["b"] == pytest.approx(0.035)
    assert found["limits"]["CP"] == pytest.approx(0.035)
    assert found["limits"]["IO"] == pytest.approx(0.00625)
    # Beyond the table the end rows hold; a shear-controlled beam with wide stirrups.
    low = H.lookup(
        beam, {"control": "flexure", "conforming": "NC", "rhoBalance": -1, "shearStress": 1}
    )
    assert (low["a"], low["b"], low["limits"]["LS"]) == (0.02, 0.03, 0.02)
    shear = H.lookup(beam, {"control": "shear", "spacing": "wide"})
    assert (shear["a"], shear["b"], shear["limits"]["CP"]) == (0.003, 0.01, 0.01)


def test_rc_column_regression() -> None:
    # ASCE 41-17 Table 10-8 with n = 0.2, ρt = 0.005, V/Vcol = 0.5, f'c/fyt = 30/420.
    rule = pushover(US).hinges.components["rcColumn"].regression
    found = H.column_regression(
        rule,
        {"axialLoadRatio": 0.2, "rhoT": 0.005, "shearRatio": 0.5, "fc": 30, "fyt": 420},
        ["IO", "LS", "CP"],
    )
    a = 0.042 - 0.043 * 0.2 + 0.63 * 0.005 - 0.023 * 0.5
    b = 0.5 / (5 + 0.2 / 0.8 / 0.005 * 30 / 420) - 0.01
    assert found["a"] == pytest.approx(a) and a == pytest.approx(0.02505)
    assert found["b"] == pytest.approx(b) and b == pytest.approx(0.0483333, rel=1e-5)
    assert found["c"] == pytest.approx(0.16)
    assert found["limits"] == pytest.approx({"IO": 0.15 * a, "LS": 0.5 * b, "CP": 0.7 * b})
    # Below the least transverse ratio: no ductility.
    none = H.column_regression(rule, {"rhoT": 0.0002, "fc": 30, "fyt": 420}, ["IO", "LS", "CP"])
    assert none["a"] == none["b"] == 0


def test_wall_and_steel_tables() -> None:
    comps = pushover(US).hinges.components
    wall = H.lookup(
        comps["rcWall"], {"boundary": "unconfined", "axialStress": 0.05, "shearStress": 3}
    )
    assert (wall["a"], wall["b"], wall["limits"]["CP"]) == (0.008, 0.015, 0.015)  # Table 10-19
    sheared = H.lookup(comps["rcWallShear"], {"axialStress": 0.1})
    assert (sheared["a"], sheared["limits"]["LS"]) == (0.0075, 0.0075)  # Table 10-20
    beam = H.lookup(comps["steelBeam"], {"slenderness": 0.5})  # Table 9-7.1, in θy
    assert beam["a"] == pytest.approx(6.5) and beam["limits"]["CP"] == pytest.approx(7.5)
    column = H.lookup(comps["steelColumn"], {"slenderness": 0.0, "axialRatio": 0.35})
    assert column["a"] == pytest.approx(11 * (1 - 5 / 3 * 0.35), rel=1e-3)
    assert H.lookup(comps["steelColumn"], {"slenderness": 0, "axialRatio": 0.6})["b"] == 0
    brace = H.lookup(comps["steelBrace"], {"action": "compression"})
    assert brace["limits"]["LS"] == 5


def test_classify_and_backbone() -> None:
    limits = {"IO": 0.005, "LS": 0.02, "CP": 0.03}
    levels = ["IO", "LS", "CP"]
    assert H.classify(0.004, limits, levels) == "IO"
    assert H.classify(0.021, limits, levels) == "CP"
    assert H.classify(0.04, limits, levels) == ">CP"
    assert H.backbone(0.0, False, 0.02, 0.03) == "B"
    assert H.backbone(0.01, True, 0.02, 0.03) == "B-C"
    assert H.backbone(0.025, True, 0.02, 0.03) == "C-E"
    assert H.backbone(0.05, True, 0.02, 0.03) == "E+"


def test_chord_rotation_capacity() -> None:
    # EN 1998-3 Eq A.1: ν = 0.2, ω = ω', fc = 30 MPa, LV/h = 3, no confinement term.
    rule = pushover(EU).hinges.components["rcColumn"].chordRotation
    section = H.Section([], [], [], [], True, 30.0, 500.0, 200_000.0, None)
    hinge = SimpleNamespace(section=section, length=3.0, component="rcColumn", object_type=None)
    values = {
        "b": 0.4,
        "h": 0.5,
        "d": 0.45,
        "N": 0.2 * 0.4 * 0.5 * 30e6,
        "rho": 0.01,
        "rhoCompression": 0.01,
        "V": 1e5,
        "M": 1.5e5,
    }
    theta = H.chord_rotation_capacity(hinge, rule, values)
    expected = 1 / 1.5 * 0.016 * 0.3**0.2 * 30**0.225 * 3**0.35
    assert theta == pytest.approx(expected, rel=1e-9) and values["LV"] == pytest.approx(1.5)
    hinge.component = "rcWall"
    assert H.chord_rotation_capacity(hinge, rule, dict(values)) == pytest.approx(0.58 * expected)


# ── the target displacement methods ──


def rule_of(pack_id: str, **change):
    target = pushover(pack_id).targetDisplacement
    return target.model_copy(update=change)


def test_displacement_coefficient_method() -> None:
    # EPP: K = 10 MN/m, Vy = 200 kN, W = 1000 kN; Te = 0.5 s, Sa = 0.6 g, site class D (a = 60).
    d, v = epp(1e7, 2e5, 0.2)
    found = pt.displacement_coefficient(
        d,
        v,
        t1=0.5,
        c0=1.3,
        weight=1e6,
        spectrum=lambda t: 0.6,
        corners={},
        rule=rule_of(US),
        site_class="SD",
    )
    mu = 0.6 / 0.2
    c1 = 1 + (mu - 1) / (60 * 0.5**2)
    c2 = 1 + ((mu - 1) / 0.5) ** 2 / 800
    assert found["mu"] == pytest.approx(3.0, rel=1e-3)
    assert found["C1"] == pytest.approx(c1, rel=1e-3) and found["C2"] == pytest.approx(c2, rel=1e-3)
    expected = 1.3 * c1 * c2 * 0.6 * (0.5 / (2 * math.pi)) ** 2 * G
    assert found["target"] == pytest.approx(expected, rel=2e-3)
    assert expected == pytest.approx(0.0560, abs=2e-4)
    # Above 1.0 s C1 = 1, above 0.7 s C2 = 1.
    assert pt.c1_site(1.2, 3.0, 60, 0.2, 1.0) == 1.0 and pt.c2_factor(0.8, 3.0, 0.7, 800) == 1.0
    assert pt.c1_site(0.1, 3.0, 60, 0.2, 1.0) == pytest.approx(1 + 2 / (60 * 0.04))


def test_fema440_effective_damping_and_period() -> None:
    lin = pushover(US).targetDisplacement.linearization
    beta, t = pt.effective_damping_period(3.0, 0.0, 1.0, lin)  # Eqs 6-5a, 6-6a
    assert beta == pytest.approx(4.9 * 4 - 1.1 * 8 + 5) and t == pytest.approx(1.496)
    beta, t = pt.effective_damping_period(5.0, 0.0, 1.0, lin)  # Eqs 6-5b, 6-6b
    assert beta == pytest.approx(20.28) and t == pytest.approx(1.8)
    beta, t = pt.effective_damping_period(8.0, 0.0, 1.0, lin)  # Eqs 6-5c, 6-6c
    assert t == pytest.approx(0.89 * (math.sqrt(7 / 1.3) - 1) + 1)
    assert beta == pytest.approx(19 * (0.64 * 7 - 1) / (0.64 * 7) ** 2 * t**2 + 5)
    assert pt.damping_reduction(15.8, lin) == pytest.approx(4 / (5.6 - math.log(15.8)))


def test_equivalent_linearization_performance_point() -> None:
    d, v = epp(1e7, 2e5, 0.3)
    first = {"weights": [1e6], "shape": [1.0]}
    found = pt.equivalent_linearization(
        d,
        v,
        t1=0.63,
        c0=1.0,
        weight=1e6,
        spectrum=lambda t: 0.6,
        corners={},
        rule=rule_of(US),
        first=first,
    )
    lin = pushover(US).targetDisplacement.linearization
    assert found["converged"] and found["alpha1"] == pytest.approx(1.0)
    # The point found gives itself back: Sd = Sa(Teff)/B(βeff)·(Teff/2π)²·g at μ = dt/dy.
    mu = found["target"] / 0.02
    t0 = 2 * math.pi * math.sqrt(0.02 / (0.2 * G))
    beta, teff = pt.effective_damping_period(mu, 0.0, t0, lin)
    back = 0.6 / pt.damping_reduction(beta, lin) * (teff / (2 * math.pi)) ** 2 * G
    assert found["target"] == pytest.approx(back, rel=1e-3)
    assert found["T0"] == pytest.approx(t0, rel=1e-3) and found["mu"] > 1


def test_n2_target() -> None:
    # EN 1998-1 Annex B: one mass, Γ = 1, m* = W/g; Fy* = 200 kN, dy* = 20 mm, Se = 0.6 g.
    d, v = epp(1e7, 2e5, 0.3)
    first = {"weights": [1e6], "shape": [1.0]}
    long = pt.n2(
        d,
        v,
        t1=0.6,
        c0=1.0,
        weight=1e6,
        spectrum=lambda t: 0.6,
        corners={"TC": 0.5},
        rule=rule_of(EU),
        first=first,
    )
    m = 1e6 / G
    t_star = 2 * math.pi * math.sqrt(m * 0.02 / 2e5)
    assert long["Tstar"] == pytest.approx(t_star, rel=1e-3) and t_star == pytest.approx(
        0.6345, abs=1e-3
    )
    assert long["target"] == pytest.approx(0.06, rel=1e-3)  # T* ≥ TC: dt* = det* (Eq B.8)
    short = pt.n2(
        d,
        v,
        t1=0.6,
        c0=1.0,
        weight=1e6,
        spectrum=lambda t: 0.6,
        corners={"TC": 1.0},
        rule=rule_of(EU),
        first=first,
    )
    qu = 0.6 * G * m / 2e5  # Eq B.11
    assert short["qu"] == pytest.approx(3.0, rel=1e-3)
    assert short["target"] == pytest.approx(0.06 / qu * (1 + (qu - 1) * 1.0 / t_star), rel=2e-3)
    # TC/T* = 5 and a large qu: the 3·det* cap holds.
    assert pt.n2_target(0.1, 5.0, 0.1, 0.5, 3.0)[0] == pytest.approx(
        3.0 * 5.0 * G * (0.1 / (2 * math.pi)) ** 2
    )


# ── a generated frame pushed over, hinges assigned ──


@pytest.fixture(scope="module")
def bay(tmp_path_factory):
    from test_fem_derive import PLAN, SETTINGS
    from test_fem_pushover import MATERIALS, OBJECTS

    from saengine.fem.derive import derive_fem
    from saengine.library.bim import generate
    from saengine.library.settings import Pushover

    tmp = tmp_path_factory.mktemp("bay")
    settings = SETTINGS.model_copy(
        update={
            "analysis": SETTINGS.analysis.model_copy(
                update={"pushover": Pushover(directions=["X"], targetDrift=2.0, steps=40)}
            )
        }
    )
    model = derive_fem(generate(PLAN, "s"), OBJECTS, MATERIALS, settings, None, tmp).pushover
    path = tmp / "pushover.osmodel"
    path.write_text(json.dumps(model), encoding="utf-8")
    out = tmp / "pushover.results"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(path),
            "--cases",
            "2",
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    from opensees_studio.services.result_store import load_manifest, load_results

    (entry,) = load_manifest(str(out))["cases"]
    push = next(a for a in model["analyses"] if a["type"] == "Pushover")
    return model, push, load_results(entry, str(out)), settings, {o.id: o for o in OBJECTS.objects}


def test_hinges_of_a_pushed_frame(bay) -> None:
    model, push, results, settings, types = bay
    target = pt.evaluate(model, push, results, settings)  # the default pack's target
    assert target["available"]
    hinge_list = H.assign(model, types)
    members = {e["name"].split("#")[0] for e in model["elements"]}
    assert {h.member for h in hinge_list} == members and len(hinge_list) == 2 * len(members)
    assert {h.component for h in hinge_list} == {"rcColumn", "rcBeam"}
    # The columns carry the gravity load in compression.
    column = next(h for h in hinge_list if h.component == "rcColumn")
    hist = H.history(column, results)
    assert hist.forces[0, 0] > 0
    # The US pack: ASCE 41 hinges at BSE-1N (LS) and BSE-2N (CP).
    last = len(results.control_disp) - 1
    step = int(target["targetStep"])
    with code_context.using(registry.load(US)):
        found = H.evaluate(
            model,
            results,
            {
                **target,
                "hazards": [
                    {"id": "BSE-1N", "level": "LS", "targetStep": step},
                    {"id": "BSE-2N", "level": "CP", "targetStep": last},
                ],
            },
            library=types,
        )
        ratios = H.step_ratios(model, results, {**target, "hazards": []}, last, library=types)
        at_end = H.evaluate_rows_at(model, results, target, last, library=types)
    assert found["available"] and found["checkedLevel"] == "LS"
    assert len(found["rows"]) == len(hinge_list) and all(r["covered"] for r in found["rows"])
    # The column ends yield by the end of the push (2 % drift), with plastic rotation.
    yielded = [r for r in at_end if r["yielded"]]
    assert {r["component"] for r in yielded} >= {"rcColumn"}
    assert all(r["demand"] > 0 for r in yielded if r["component"] == "rcColumn")
    assert all(r["demand"] >= 0 and set(r["limits"]) == {"IO", "LS", "CP"} for r in found["rows"])
    assert {r["state"] for r in found["rows"]} <= {"elastic", "IO", "LS", "CP", ">CP"}
    assert [h["id"] for h in found["hazards"]] == ["BSE-1N", "BSE-2N"]
    assert all(h["available"] for h in found["hazards"])
    # The plastic rotation only grows: the CP check at the end of the push sees at least as much.
    assert ratios and max(ratios.values()) >= 0
    assert set(ratios) <= {e["id"] for e in model["elements"]}
    # The Eurocodes pack: chord rotations against DL, SD, NC.
    with code_context.using(registry.load(EU)):
        eu = H.evaluate(model, results, {**target, "hazards": []}, library=types)
    assert eu["available"] and eu["checkedLevel"] == "SD"
    assert all("thetaUm" in r["variables"] for r in eu["rows"] if r["covered"])
    # The report's hinge section.
    from saengine.report.build import MAX_PUSHOVER_MEMBERS, _pushover_hinges

    report = _pushover_hinges(found, "PX", [])
    assert len(report["hinges"]) == min(len(found["rows"]), MAX_PUSHOVER_MEMBERS)
    assert [row[0] for row in report["hingeHazards"]] == ["BSE-1N", "BSE-2N"]


def test_report_rows_of_the_other_target_methods() -> None:
    from saengine.report.build import _pushover_target_rows

    d, v = epp(1e7, 2e5, 0.2)
    found = pt.displacement_coefficient(
        d,
        v,
        t1=0.5,
        c0=1.3,
        weight=1e6,
        spectrum=lambda t: 0.6,
        corners={},
        rule=rule_of(US),
        site_class="SD",
    )
    found.update(pt.capacity_checks(d, v, found["target"], 1.5, None))
    rows = _pushover_target_rows(found, {True: "yes", False: "no", None: "not reached"})
    assert any(r[0] == "C2" for r in rows) and not any(r[0].startswith("No drop") for r in rows)
    first = {"weights": [1e6], "shape": [1.0]}
    for method in (pt.equivalent_linearization, pt.n2):
        found = method(
            d,
            v,
            t1=0.6,
            c0=1.0,
            weight=1e6,
            spectrum=lambda t: 0.6,
            corners={"TC": 0.5},
            rule=rule_of(US if method is pt.equivalent_linearization else EU),
            first=first,
        )
        found.update(pt.capacity_checks(d, v, found["target"], 1.5, None))
        assert _pushover_target_rows(found, {True: "yes", False: "no", None: "–"})

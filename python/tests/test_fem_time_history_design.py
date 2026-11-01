"""B19: the linear time history procedure in design, with the values of the bnbc2020 pack.

BNBC 2020 Part 6 Sec 2.5.10.2 (pp. 636-637): at least three records; the mean of the 5 %-damped
spectra not below the design spectrum over 0.2T-1.5T (pairs: the mean SRSS spectrum not below
1.3 times it). Sec 2.5.10.3 (p. 637): V/Vth where Vth < V, the largest response below seven
records, the mean from seven, drifts times Cd/I. Sec 2.5.13.1(c) (p. 645): pairs applied
simultaneously. Sec 2.5.11.2 (pp. 639-640): the nonlinear target with R = 1, I = 1 (B36).
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from saengine.codes import tables
from saengine.fem import linear_time_history as lth
from saengine.fem import records as rec
from saengine.library.settings import TimeHistory, default_project_settings

DT = 0.01


def _record(path: Path, frequency: float, amplitude: float = 0.2, seconds: float = 4.0) -> None:
    """A decaying sine (time, acceleration in g) as a two-column record."""
    t = np.arange(0, seconds + DT / 2, DT)
    a = amplitude * np.sin(2 * math.pi * frequency * t) * np.exp(-0.4 * t)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"{ti:.4f} {ai:.6f}" for ti, ai in zip(t, a, strict=True)) + "\n")


def _accelerations(frequencies: list[float]) -> list[tuple[float, np.ndarray]]:
    t = np.arange(0, 4.0 + DT / 2, DT)
    return [(DT, 0.2 * np.sin(2 * math.pi * f * t) * np.exp(-0.4 * t)) for f in frequencies]


# ─────────────────────────────── the pack's values ───────────────────────────────


def test_pack_pins_the_time_history_rules() -> None:
    rules = tables.builtin_table("seismic").timeHistory
    assert rules is not None and rules.method == "periodRange"
    # Sec 2.5.10.2: at least three records; 0.2T to 1.5T; ratio 1 (2D), 1.3 (3D pairs), 5 %.
    assert rules.minimumRecords == 3
    assert (rules.periodLower, rules.periodUpper) == (0.2, 1.5)
    assert (rules.singleRatio, rules.pairRatio, rules.spectrumDamping) == (1.0, 1.3, 0.05)
    # Sec 2.5.10.3: the mean from seven records; V/Vth on every response, drifts included.
    assert rules.meanFrom == 7 and rules.baseShearShare == 1.0 and rules.scaleDrifts
    assert rules.simultaneousPairs
    # Sec 2.5.11.2: the nonlinear target spectrum with R = 1 and I = 1; the linear one is the
    # building's own design spectrum.
    assert (rules.targets["nonlinear"].R, rules.targets["nonlinear"].I) == (1.0, 1.0)
    assert (rules.targets["linear"].R, rules.targets["linear"].I) == (None, None)
    assert "2.5.10.3" in rules.clauses["response"] and "2.5.13.1(c)" in rules.clauses["pairs"]


def test_design_rule_largest_below_seven_mean_from_seven() -> None:
    assert rec.design_rule(3) == "max" and rec.design_rule(6) == "max"
    assert rec.design_rule(7) == "mean" and rec.design_rule(11) == "mean"
    peaks = [[1.0, 4.0], [3.0, 2.0], [2.0, 3.0]]
    np.testing.assert_allclose(rec.design_value(peaks), [3.0, 4.0])
    np.testing.assert_allclose(rec.design_value(peaks * 3), [2.0, 3.0])  # 9 records: mean
    np.testing.assert_allclose(rec.design_value(peaks * 3, "max"), [3.0, 4.0])
    np.testing.assert_allclose(rec.design_value([[-5.0]]), [5.0])


def test_base_shear_factor_scales_up_only() -> None:
    # Sec 2.5.10.3: Vth below V: every response times V/Vth; at or above V: unchanged.
    assert rec.base_shear_factor(1000.0, 800.0) == pytest.approx(1.25)
    assert rec.base_shear_factor(1000.0, 1200.0) == 1.0
    assert rec.base_shear_factor(0.0, 800.0) == 1.0 and rec.base_shear_factor(1000.0, 0.0) == 1.0


def test_suites_group_by_direction_and_pairs() -> None:
    histories = [
        TimeHistory(name="a", record="a.txt", direction="X"),
        TimeHistory(name="b", record="b.txt", direction="Y"),
        TimeHistory(name="c", record="c.txt", direction="X", recordOrthogonal="c2.txt"),
        TimeHistory(name="d", record="d.txt", direction="X"),
    ]
    assert rec.suites(histories) == {"X": [0, 3], "Y": [1], "XY": [2]}
    settings = default_project_settings("T")
    assert not rec.scaled_to_code(histories[0], settings)  # auto, response spectrum design
    th = settings.model_copy(
        update={"analysis": settings.analysis.model_copy(update={"seismicDesign": "timeHistory"})}
    )
    assert rec.scaled_to_code(histories[0], th)
    manual = histories[0].model_copy(update={"scaling": "manual"})
    assert not rec.scaled_to_code(manual, th)


# ─────────────────────────────── scaling ───────────────────────────────


def test_suite_scaled_meets_the_design_spectrum_over_the_range() -> None:
    settings = default_project_settings("T")
    target = rec.target_spectrum(settings, "X")
    records = _accelerations([1.0, 2.0, 3.5])
    period = 0.5
    for individual in (True, False):
        factors = rec.scale_suite(records, target, period, individual=individual)
        scaled = [(dt, k * a) for (dt, a), k in zip(records, factors, strict=True)]
        check = rec.check_suite(scaled, target, period)
        # The criterion is just met: the least mean / target over 0.1-0.75 s is 1.
        assert check.ok and check.least == pytest.approx(1.0, rel=1e-6)
        assert check.ratio == 1.0 and not check.notes
        assert check.periods[0] == pytest.approx(0.1) and check.periods[-1] == pytest.approx(0.75)
    # Unscaled it falls short, by the factor that would meet it.
    raw = rec.check_suite(records, target, period)
    if not raw.ok:
        assert raw.shortfall == pytest.approx(1 / raw.least)


def test_pairs_meet_1_3_times_the_spectrum_with_one_factor_per_pair() -> None:
    settings = default_project_settings("T")
    target = rec.target_spectrum(settings, "XY")
    records = _accelerations([1.0, 1.5, 2.0, 2.5, 3.0, 3.5])
    pairs = [(0, 1), (2, 3), (4, 5)]
    factors = rec.scale_suite(records, target, 0.6, pairs)
    for a, b in pairs:
        assert factors[a] == pytest.approx(factors[b])
    scaled = [(dt, k * acc) for (dt, acc), k in zip(records, factors, strict=True)]
    check = rec.check_suite(scaled, target, 0.6, pairs)
    assert check.paired and check.ratio == 1.3 and check.ok
    assert check.count == 3


def test_too_few_records_are_flagged() -> None:
    settings = default_project_settings("T")
    target = rec.target_spectrum(settings, "X")
    check = rec.check_suite(_accelerations([2.0, 3.0]), target, 0.5)
    assert check.count == 2 and "at least 3" in check.notes[0]


def test_nonlinear_target_uses_r_and_i_of_one() -> None:
    settings = default_project_settings("T")
    linear = rec.target_spectrum(settings, "X", "linear")
    elastic = rec.target_spectrum(settings, "X", "nonlinear")
    from saengine.library.settings import derived

    values = derived(settings)
    ratio = float(elastic.sa_at(0.5)[0] / linear.sa_at(0.5)[0])
    assert ratio == pytest.approx(values["R"] / values["seismicImportance"], rel=1e-6)


# ─────────────────────────────── combinations ───────────────────────────────


def test_history_combinations_replace_the_spectrum_parts() -> None:
    combos = [
        {"name": "1.2D ± 1.0E(RS EX + 0.3EY)", "loads": {"D": 1.2}, "envelope": {"RX": 1.0, "RY": 0.3, "AX": 1.0}, "clause": "c"},
        {"name": "0.9D", "loads": {"D": 0.9}, "envelope": {}, "clause": ""},
    ]  # fmt: skip
    out = lth.history_combinations(combos, {"HX": {}, "HY": {}})
    assert out[0]["envelope"] == {"HX": 1.0, "HY": 0.3, "AX": 1.0}
    assert out[0]["name"] == "1.2D ± 1.0E(TH EX + 0.3EY)" and "2.5.10.3" in out[0]["clause"]
    assert out[1] is combos[1]
    # Only X has a suite: Y keeps the response spectrum.
    assert lth.history_combinations(combos, {"HX": {}})[0]["envelope"] == {
        "HX": 1.0, "RY": 0.3, "AX": 1.0,
    }  # fmt: skip
    # Pairs (Sec 2.5.13.1(c)): both directions are the one simultaneous part H.
    one_way = [
        {"name": "1.2D ± 1.0E(RS EX)", "envelope": {"RX": 1.0, "AX": 1.0}},
        {"name": "1.2D ± 1.0E(RS EY)", "envelope": {"RY": 1.0, "AY": 1.0}},
    ]
    pairs = lth.history_combinations(one_way, {"H": {}})
    assert [c["envelope"] for c in pairs] == [{"H": 1.0, "AX": 1.0}, {"H": 1.0, "AY": 1.0}]


def test_shell_parts_scale_the_spectrum_by_the_base_shear_ratio() -> None:
    class Base:
        parts = ("RX", "RY")

        def shell(self, element_id):
            return {"RX": np.array([10.0, 2.0]), "RY": np.array([1.0, 20.0])}

    summary = {
        "parts": {
            "HX": {"ratio": {"x": 1.5}, "cases": [], "factor": 1.0, "rule": "max"},
            "H": {"ratio": {"x": 2.0, "y": 0.5}, "cases": [], "factor": 1.0, "rule": "max"},
        }
    }
    forces = lth.TimeHistoryForces(Base(), ".", {}, ".", summary, [], 0.3)
    shell = forces.shell(1)
    np.testing.assert_allclose(shell["HX"], [15.0, 3.0])
    # Pairs: 100 % of one direction + 30 % of the other, the larger.
    a, b = np.array([20.0, 4.0]), np.array([0.5, 10.0])
    np.testing.assert_allclose(shell["H"], np.maximum(a + 0.3 * b, 0.3 * a + b))
    assert forces.parts == ["RX", "RY", "HX", "H"]


# ─────────────────────────────── a derived bay, run ───────────────────────────────


@pytest.fixture(scope="module")
def bay(tmp_path_factory: pytest.TempPathFactory):
    from test_fem_derive import OBJECTS, PLAN, SETTINGS

    from saengine.fem import seismic_design as sd
    from saengine.fem.derive import derive_fem
    from saengine.library import default_material_library
    from saengine.library.bim import generate

    root = tmp_path_factory.mktemp("th-bay")
    histories = []
    for k, frequency in enumerate((1.5, 2.5, 4.0)):
        _record(root / "02 Project Settings" / "records" / f"r{k}.txt", frequency)
        histories.append(
            TimeHistory(name=f"R{k}", record=f"02 Project Settings/records/r{k}.txt", direction="X")
        )
    settings = SETTINGS.model_copy(
        update={
            "analysis": SETTINGS.analysis.model_copy(
                update={"timeHistories": histories, "seismicDesign": "timeHistory"}
            )
        }
    )
    folder = root / "08 FEM"
    folder.mkdir(parents=True)
    d = derive_fem(generate(PLAN, "s"), OBJECTS, default_material_library(), settings, None, folder)
    model = folder / "model.osmodel"
    model.write_text(json.dumps(d.project), encoding="utf-8")
    out = folder / "model.results"
    ids = [str(a["id"]) for a in d.project["analyses"]]
    run = subprocess.run(
        [sys.executable, "-m", "opensees_studio.run", "--project", str(model)]
        + ["--cases", *ids, "--out", str(out)],
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    summary = sd.seismic_design(out, model, settings)
    return d, model, out, settings, summary


def test_bay_records_are_scaled_to_the_code_spectrum(bay) -> None:
    from saengine.fem.derive import G

    d, *_ = bay
    series = [s for s in d.project["time_series"] if s.get("record_id")]
    assert len(series) == 3
    # Code scaling replaced the manual factor 1 (× g).
    assert all(abs(s["factor"] - G) > 1e-6 for s in series)
    assert any("time-history suite X: 3 records scaled" in n for n in d.notes)


def test_bay_time_history_design(bay) -> None:
    from saengine.fem import seismic_design as sd
    from saengine.fem.display import _elements

    d, _, out, _, summary = bay
    history = summary["timeHistory"]
    assert history["available"] and history["use"]
    (suite,) = history["suites"]
    assert suite["key"] == "X" and suite["count"] == 3 and suite["rule"] == "max"
    assert suite["enough"] and suite["complete"] and suite["used"]
    # Sec 2.5.10.3: the design base shear is the largest record's, lifted to V when below it.
    largest = max(c["baseShear"]["x"] for c in suite["cases"])
    assert suite["vHistory"]["x"] == pytest.approx(largest * suite["shortfall"], rel=1e-9)
    expected = suite["shortfall"] * rec.base_shear_factor(
        suite["vStatic"]["x"], suite["vHistory"]["x"]
    )
    assert suite["factor"] == pytest.approx(expected, rel=1e-6)
    # The factor applies to the recorded responses: the design base shear reaches V.
    design_v = largest * 1e3 * suite["factor"]
    assert design_v >= suite["vStatic"]["x"] * 1e3 * (1 - 1e-6)
    # Drifts: times Cd/I.
    rows = [r for r in history["drift"] if r["direction"] == "X"]
    assert rows and all(
        r["designDrift"] == pytest.approx(summary["amplificationByAxis"]["X"] * r["elasticDrift"])
        for r in rows
    )
    # The combinations: HX in place of RX; Y keeps the spectrum.
    envelopes = [c["envelope"] for c in summary["combinations"]]
    assert all("RX" not in e for e in envelopes) and any("HX" in e for e in envelopes)
    # Y keeps the spectrum, so the names say both.
    assert all("(TH+RS " in c["name"] for c in summary["combinations"] if "HX" in c["envelope"])

    forces = sd.load_seismic_forces(out)
    assert isinstance(forces, lth.TimeHistoryForces) and "HX" in forces.parts
    column = next(e for e in _elements(d.project) if e.name.startswith("C"))
    envelope = forces.frame(column)
    assert envelope["HX"].shape == (11, 6) and np.all(envelope["HX"] >= 0)
    # The storey shear just above the base is the design base shear of the suite.
    assert forces.storey_shear(0.01)["HX"][0] == pytest.approx(design_v, rel=1e-6)
    # Four equal columns: each takes about a quarter of it at its base.
    vx = max(envelope["HX"][0, 1], envelope["HX"][0, 2])
    assert vx == pytest.approx(design_v / 4, rel=0.1)


def test_a_pair_is_one_case_shaking_both_directions(tmp_path: Path) -> None:
    """Sec 2.5.13.1(c): the two components of a pair act simultaneously, with one factor."""
    from test_fem_derive import OBJECTS, PLAN, SETTINGS

    from saengine.fem.derive import derive_fem
    from saengine.library import default_material_library
    from saengine.library.bim import generate

    histories = []
    for k in range(3):
        for c, frequency in (("a", 1.5 + k), ("b", 2.0 + k)):
            _record(tmp_path / "02 Project Settings" / "records" / f"p{k}{c}.txt", frequency)
        histories.append(
            TimeHistory(
                name=f"P{k}",
                record=f"02 Project Settings/records/p{k}a.txt",
                recordOrthogonal=f"02 Project Settings/records/p{k}b.txt",
                direction="X",
                scaling="code",
            )
        )
    settings = SETTINGS.model_copy(
        update={"analysis": SETTINGS.analysis.model_copy(update={"timeHistories": histories})}
    )
    folder = tmp_path / "08 FEM"
    folder.mkdir()
    d = derive_fem(generate(PLAN, "s"), OBJECTS, default_material_library(), settings, None, folder)
    cases = lth.transient_cases(d.project)
    assert [c["suite"] for c in cases] == ["XY", "XY", "XY"]
    series = {s["id"]: s for s in d.project["time_series"]}
    for case in cases:
        assert sorted(direction for direction, _ in case["excitations"]) == [1, 2]
        factors = {series[s]["factor"] for _, s in case["excitations"]}
        assert len(factors) == 1  # one scale factor on both components
    assert len(d.project["ground_motions"]) == 6
    assert any("time-history suite XY: 3 pairs scaled" in n for n in d.notes)


def test_report_rows_of_the_time_history_design() -> None:
    from saengine.report.build import _time_history_report

    history = {
        "available": True,
        "use": True,
        "suites": [
            {
                "key": "X", "count": 3, "rule": "max", "used": True, "factor": 1.25,
                "vHistory": {"x": 800.0, "y": 0.0}, "vStatic": {"x": 1000.0, "y": 1000.0},
                "check": {"least": 1.0, "governing": 0.3, "period": 1.0},
            }
        ],
        "drift": [
            {"suite": "X", "direction": "X", "bottom": 0.0, "top": 3.0, "height": 3.0,
             "elasticDrift": 0.004, "designDrift": 0.02, "ratio": 0.0067,
             "allowableRatio": 0.02, "ok": True}
        ],
        "clauses": {"records": "r", "response": "s", "pairs": "p"},
    }  # fmt: skip
    report = _time_history_report(history)
    assert report["suites"] == [
        ["X", "3", "largest", "1.000 at 0.30 s (T = 1.00 s)", "800.0", "1000.0", "1.250", "yes"]
    ]
    assert report["drift"][0][-1] == "OK" and report["driftFails"] == [False]
    assert _time_history_report(None) is None

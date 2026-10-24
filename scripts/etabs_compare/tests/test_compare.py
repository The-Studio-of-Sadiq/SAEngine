"""Tests of the comparison harness's report and tolerance logic (scripts/etabs_compare).

    python -m pytest -q scripts/etabs_compare/tests

CI-safe: synthetic data only, no analysis program, no SAEngine run.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


C = load("compare")


def q(saengine, reference, kind, **kw):
    return C.judge(C.Quantity("g", "n", saengine, reference, kind, **kw), {kind: "a reason"})


def test_tolerances_pass_and_flag():
    assert q(1.0, 1.019, "period").status == "PASS"
    flagged = q(1.0, 1.021, "period")
    assert flagged.status == "FLAG" and flagged.reason == "a reason"
    assert flagged.diff_pct == pytest.approx(2.1)
    assert flagged.tol_pct == pytest.approx(2.0)
    assert q(100.0, 100.9, "reaction").status == "PASS"
    assert q(100.0, 101.1, "reaction").status == "FLAG"
    assert q(43.95, 37.16, "baseShear").status == "FLAG"
    assert q(10.0, 10.49, "faceMoment").status == "PASS"
    assert q(0.001, 0.0011, "drift").status == "FLAG"


def test_signs_are_ignored_and_floor_passes_small_values():
    assert q(-43.95, -43.95, "baseShear").status == "PASS"
    small = C.judge(C.Quantity("g", "n", 0.30, 0.22, "faceMoment"), {}, floor=0.5)
    assert small.status == "PASS" and "floor" in small.reason


def test_missing_values():
    m = q(None, 1.0, "period")
    assert m.status == "MISSING" and "SAEngine" in m.reason


def test_internal_forces_simply_supported_beam():
    # a 6 m beam, w = 10 kN/m down (local z up: wz = -10); end i reaction 30 kN up
    # forces on the element at i: Vz = +30, My = 0 (pinned)
    fi = [0.0, 0.0, 30.0, 0.0, 0.0, 0.0]
    w = [0.0, 0.0, -10.0]
    mid = C.internal_forces(fi, w, 3.0)
    assert abs(mid[4]) == pytest.approx(10 * 6**2 / 8)  # wL²/8
    assert abs(mid[2]) == pytest.approx(0.0)  # no shear at mid-span
    end = C.internal_forces(fi, w, 6.0)
    assert abs(end[4]) == pytest.approx(0.0, abs=1e-9)
    assert abs(end[2]) == pytest.approx(30.0)


def test_saengine_at_picks_the_sub_element():
    span = {
        "kind": "beam",
        "subs": [
            {
                "a": 0.0,
                "b": 1.0,
                "axes": {},
                "cases": {"D": {"fi": [0, 0, 30, 0, 0, 0], "w": [0, 0, -10]}},
            },
            {
                "a": 1.0,
                "b": 6.0,
                "axes": {},
                "cases": {"D": {"fi": [0, 0, 20, 0, -25, 0], "w": [0, 0, -10]}},
            },
        ],
    }
    at = C.saengine_at(span, "D", 3.0)
    # from the second sub-element: x = 2, My = -(-25 + 20*2 - 10*4/2) = 5
    assert abs(at["f"][4]) == pytest.approx(5.0)
    assert C.saengine_at(span, "L", 3.0) is None


def test_column_components_in_global_axes():
    # a vertical member: SAEngine local y = -Y, local z = +X
    axes = {"y": [0.0, -1.0, 0.0], "z": [1.0, 0.0, 0.0]}
    s = C.moment_components("column", [0, 0, 0, 0, 4.0, 3.0], axes)
    assert s == {"Mx": pytest.approx(3.0), "My": pytest.approx(4.0)}
    # the reference at angle 0: M2 about X, M3 about Y; at 90°, they swap
    assert C.reference_components("column", {"M2": 3.0, "M3": 4.0}, 0.0) == {
        "Mx": pytest.approx(3.0),
        "My": pytest.approx(4.0),
    }
    r90 = C.reference_components("column", {"M2": 4.0, "M3": -3.0}, 90.0)
    assert r90["Mx"] == pytest.approx(3.0) and r90["My"] == pytest.approx(4.0)
    assert C.reference_components("beam", {"M2": 1.0, "M3": 9.0}, 0.0) == {
        "Mmajor": 9.0,
        "Mminor": 1.0,
    }


def _synthetic(ref_scale: float = 1.0):
    csv_mass = "Story,UX,UY\nL1,80,80\nBase,5,5\n"
    csv_forces = "Story,Output Case,Location,VX,VY\nL1,EX,Bottom,-44,0\nL1,EY,Bottom,0,-44\n"
    csv_cm = "Story,Diaphragm,Output Case,UX,UY\nL1,D1,EX,0.0001,0\nL1,D1,EY,0,0.0003\n"
    sae = {
        "modal": {
            "periods": [0.2, 0.1, 0.05],
            "effMass_t": [[70, 1], [1, 70], [5, 5]],
            "massTotal_t": 80.0,
        },
        "baseReactions": {
            "D": [0, 0, 500, 0, 0, 0],
            "EX": [-44, 0, 0, 0, 0, 0],
            "EY": [0, -44, 0, 0, 0, 0],
        },
        "seismic": {"W_kN": 784.5, "V_kN": 44.0, "massTotal_t": 80.0},
        "stories": {
            "levels": [{"name": "L1", "z": 3.2, "h": 3.2}],
            "shear": {"EX": {"L1": 44.0}, "EY": {"L1": 44.0}},
            "cmDisp": {"EX": {"L1": [0.0001, 0.0]}, "EY": {"L1": [0.0, 0.0003]}},
        },
        "members": [
            {
                "label": "B1",
                "kind": "beam",
                "angle": 0.0,
                "length": 6.0,
                "subs": [
                    {
                        "a": 0.0,
                        "b": 6.0,
                        "axes": {"y": [0, 1, 0], "z": [0, 0, 1]},
                        "cases": {"D": {"fi": [0, 0, 30, 0, 30, 0], "w": [0, 0, -10]}},
                    }
                ],
            }
        ],
        "analysisSettings": {},
    }
    s = ref_scale
    ref = {
        "mode": "native",
        "runs": [
            {
                "cases": ["EX", "EY", "Modal"],
                "modal": [
                    {"mode": 1, "T": 0.2 * s, "UX": 70 / 80, "UY": 1 / 80},
                    {"mode": 2, "T": 0.1, "UX": 1 / 80, "UY": 70 / 80},
                    {"mode": 3, "T": 0.05, "UX": 5 / 80, "UY": 5 / 80},
                ],
                "base": [
                    {"case": "EX", "FX": -44 * s, "FY": 0, "FZ": 0},
                    {"case": "EY", "FX": 0, "FY": -44, "FZ": 0},
                ],
                "frames": {},
                "tables": {
                    "Mass Summary by Story": {"csv": csv_mass},
                    "Story Forces": {"csv": csv_forces},
                    "Diaphragm Center Of Mass Displacements": {"csv": csv_cm},
                },
            },
            {
                "cases": ["D"],
                "base": {"case": "D", "FX": 0, "FY": 0, "FZ": 500},
                # a single row serialised as an object, as PowerShell does
                "frames": {
                    "B1": {
                        "first": {
                            "case": "D",
                            "sta": 0.25,
                            "P": 0,
                            "V2": 0,
                            "V3": 0,
                            "T": 0,
                            "M2": 0,
                            "M3": 22.1875,
                        },
                        "last": [
                            {
                                "case": "D",
                                "sta": 5.75,
                                "P": 0,
                                "V2": 0,
                                "V3": 0,
                                "T": 0,
                                "M2": 0,
                                "M3": 0,
                            }
                        ],
                        "lastStart": 0.0,
                    }
                },
                "tables": {},
            },
        ],
    }
    return sae, ref


def test_compare_end_to_end(tmp_path: Path):
    sae, ref = _synthetic()
    quantities = C.compare(sae, ref, "native")
    by = {(x.name, x.case): x for x in quantities}
    assert by[("T1", "Modal")].status == "PASS"
    assert by[("mode 1 effective mass UX", "Modal")].status == "PASS"
    assert by[("base FZ", "D")].status == "PASS"
    assert by[("static base shear V", "EX")].status == "PASS"
    assert by[("storey shear L1", "EX")].status == "PASS"
    assert by[("storey drift L1 (centre of mass)", "EY")].status == "PASS"
    w = by[("seismic weight W", "")]
    assert w.reference == pytest.approx(80 * C.G) and w.status == "PASS"
    # B1 i face at 0.25 m: M = -(30 + 30*0.25 - 10*0.25²/2) -> 37.1875 vs 22.1875: FLAG
    face = by[("B1 i Mmajor", "D")]
    assert face.saengine == pytest.approx(37.1875)
    assert face.status == "FLAG" and "end zones" in face.reason
    assert face.detail["station_m"] == pytest.approx(0.25)
    doc = C.write_outputs(
        tmp_path,
        {"project": "Synthetic", "mode": "native", "members": ["B1"]},
        quantities,
        {"SAEngine": ["a note"]},
    )
    assert doc["summary"]["FLAG"] >= 1
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "| B1 i Mmajor @ 0.250 m | D |" in report and "FLAG" in report
    assert "ETABS" not in report  # public material never names the reference program
    data = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert data["schema"] == "saengine.referenceComparison/1"
    assert data["tolerances"]["period"]["rel"] == 0.02


def test_compare_flags_a_period_difference_with_the_mirror_reason():
    sae, ref = _synthetic(ref_scale=1.05)
    by = {(x.name, x.case): x for x in C.compare(sae, ref, "mirror")}
    t1 = by[("T1", "Modal")]
    assert t1.status == "FLAG" and "solver" in t1.reason
    assert by[("base FX", "EX")].status == "FLAG"
    assert math.isclose(by[("base FX", "EX")].diff_pct, 5.0, rel_tol=1e-6)

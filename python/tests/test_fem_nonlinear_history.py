"""B36: the nonlinear time history analysis, with the values of the bnbc2020 pack.

BNBC 2020 Part 6 Sec 2.5.11.2 (pp. 639-640): records scaled to the real design spectrum (R = 1,
I = 1). Sec 2.5.11.3 (p. 640): the largest response below seven records, the mean from seven,
no scaling of the results. Sec 2.5.11.4 (p. 640): member deformation at most 2/3 of the smaller
of the deformation at gravity loss and at 67 % of the peak strength. Sec 2.5.11.5 (p. 641):
independent design review. Sec 2.5.14.1 (p. 647): the drift at most 1.25 times the limit of the
linear procedures.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from saengine.codes import tables
from saengine.fem import acceptance
from saengine.fem import nonlinear_history as nh
from saengine.fem import records as rec
from saengine.library.settings import NonlinearHistory, TimeHistory

# ─────────────────────────────── the pack's values ───────────────────────────────


def test_pack_pins_the_nonlinear_history_rules() -> None:
    table = tables.builtin_table("nonlinearHistory")
    # Sec 2.5.11.2: the records are scaled to the nonlinear target, R = 1 and I = 1.
    assert table.procedure.target == "nonlinear"
    target = tables.builtin_table("seismic").timeHistory.targets["nonlinear"]
    assert (target.R, target.I) == (1.0, 1.0)
    # Sec 2.5.11.3: the mean from seven records (or pairs); the results are not scaled.
    assert table.procedure.meanFrom == 7
    assert table.procedure.scaleToStaticShear is False
    # Sec 2.5.11.5: an independent design review.
    assert table.procedure.designReview is True
    # Sec 2.5.14.1: 1.25 times the drift limit, the real drifts (no Cd/I).
    assert table.drift.limitFactor == 1.25
    assert table.drift.amplify is False
    # Sec 2.5.11.4: 2/3 of the smaller of gravity loss and 67 % strength, for every member.
    assert table.acceptance.deformationShare == pytest.approx(2 / 3, abs=1e-6)
    assert table.acceptance.residualStrengthShare == 0.67
    assert table.acceptance.gravityLossAllMembers is True
    for key, words in (
        ("groundMotion", "2.5.11.2"),
        ("response", "2.5.11.3"),
        ("acceptance", "2.5.11.4"),
        ("review", "2.5.11.5"),
        ("drift", "2.5.14.1"),
    ):
        assert words in table.sources[key]


def test_nonlinear_procedure_scales_automatic_records_to_the_code() -> None:
    history = TimeHistory(name="a", record="a.txt")  # scaling "auto"
    linear = SimpleNamespace(analysis=SimpleNamespace(seismicDesign="responseSpectrum"))
    assert rec.scaled_to_code(history, linear) is False
    assert rec.scaled_to_code(history, linear, "nonlinear") is True
    manual = TimeHistory(name="b", record="b.txt", scaling="manual")
    assert rec.scaled_to_code(manual, linear, "nonlinear") is False


def test_design_rule_of_the_procedure() -> None:
    assert rec.design_rule(6, nh.mean_from()) == "max"
    assert rec.design_rule(7, nh.mean_from()) == "mean"


# ─────────────────────────────── the pieces ───────────────────────────────


def test_drift_limit_is_one_and_a_quarter_times_the_allowable() -> None:
    drift = np.array([[0.060, 0.0], [0.020, 0.0]])  # m per storey, X and Y
    rows = nh.drift_rows("X", drift, [0.0, 3.0, 6.0], 1.25 * 0.015)
    assert [r["direction"] for r in rows] == ["X", "X"]
    assert rows[0]["ratio"] == pytest.approx(0.02) and rows[0]["ok"] is False  # > 1.875 %
    assert rows[1]["ratio"] == pytest.approx(0.02 / 3) and rows[1]["ok"] is True


def test_member_design_ratio_largest_or_mean() -> None:
    def row(member: str, ratio: float) -> dict:
        return {"member": member, "ratio": ratio, "ok": ratio <= 1}

    per_record = [[row("C1", 0.9), row("B1", 0.2)], [row("C1", 1.2)], [row("C1", 0.6)]]
    largest = {r["member"]: r for r in nh.design_ratios(per_record, "max")}
    assert largest["C1"]["ratio"] == 1.2 and largest["C1"]["record"] == 1
    assert largest["C1"]["ok"] is False
    mean = {r["member"]: r for r in nh.design_ratios(per_record, "mean")}
    assert mean["C1"]["ratio"] == pytest.approx(0.9) and mean["C1"]["ok"] is True
    assert mean["B1"]["ratio"] == pytest.approx(0.2 / 3)  # a record without it counts 0


def test_fundamental_periods_by_effective_mass() -> None:
    nodes = [{"id": 1, "mass": [1.0, 1.0, 0, 0, 0, 0]}]
    shapes = {1: {1: [0.0, 1.0, 0, 0, 0, 0]}, 2: {1: [1.0, 0.0, 0, 0, 0, 0]}}
    assert nh.fundamental_periods(nodes, [0.8, 0.5], shapes) == {"Y": 0.8, "X": 0.5}


def _fibre_model() -> dict:
    """One vertical fibre column: a confined concrete core fibre and a bar."""
    return {
        "nodes": [{"id": 1, "coords": [0, 0, 0]}, {"id": 2, "coords": [0, 0, 3]}],
        "materials": [
            {
                "id": 1,
                "name": "C25 core",
                "type": "Concrete02",
                "fpc": -30e6,
                "epsc0": -0.0024,
                "fpcu": -6e6,
                "epsU": -0.012,
            },
            {"id": 2, "name": "B420", "type": "Steel02"},
        ],
        "sections": [
            {
                "id": 1,
                "type": "FiberSection",
                "patches": [],
                "layers": [],
                "fibres": [
                    {"y": 0, "z": 0, "area": 0.01, "material_id": 1},
                    {"y": 0.1, "z": 0, "area": 3e-4, "material_id": 2},
                ],
            }
        ],
        "elements": [
            {"id": 7, "name": "C1#2", "type": "ForceBeamColumn", "nodes": [1, 2], "section_id": 1}
        ],
    }


def test_fibre_peaks_against_two_thirds_of_the_67_percent_strength() -> None:
    rule = tables.builtin_table("nonlinearHistory").acceptance
    project = _fibre_model()
    # Concrete: 67 % of the peak on the descending branch, 0.0024 + 0.33/0.8 * (0.012 - 0.0024).
    strength, crushed = acceptance.concrete_failure_strains(project["materials"][0], 0.67)
    assert strength == pytest.approx(0.0024 + 0.33 / 0.8 * 0.0096)
    assert crushed == pytest.approx(0.012)
    peaks = {
        7: {
            "start": np.array([[0, 0, 0.01, -0.006, 0.0005], [0.1, 0, 3e-4, -0.004, 0.03]]),
            "end": np.array([[0, 0, 0.01, -0.001, 0.0], [0.1, 0, 3e-4, -0.001, 0.001]]),
        }
    }
    (row,) = acceptance.fibre_strain_peaks(project, peaks.get, rule)
    assert row["member"] == "C1" and row["end"] == "i" and row["gravity"] is True
    concrete = 0.006 / (rule.deformationShare * strength)
    bar = 0.03 / (rule.deformationShare * rule.reinforcementFractureStrain)
    assert row["ratio"] == pytest.approx(max(concrete, bar))
    assert row["fibre"] == ("concrete" if concrete > bar else "bar")
    assert row["ok"] is (row["ratio"] <= 1)


def test_braces_lose_gravity_only_without_the_all_members_rule() -> None:
    project = _fibre_model()
    project["nodes"][1]["coords"] = [3, 0, 3]  # inclined: a brace
    peaks = {7: {"start": np.array([[0, 0, 0.01, -0.011, 0.0], [0.1, 0, 3e-4, 0.0, 0.0]])}}
    every = tables.builtin_table("nonlinearHistory").acceptance
    (row,) = acceptance.fibre_strain_peaks(project, peaks.get, every)
    assert row["gravity"] is True
    pushover = tables.builtin_table("pushover").acceptance
    (other,) = acceptance.fibre_strain_peaks(project, peaks.get, pushover)
    assert other["gravity"] is False


# ─────────────────────────────── the derived model, run ───────────────────────────────


def _record(path: Path, frequency: float, seconds: float = 1.5, dt: float = 0.01) -> None:
    t = np.arange(0, seconds + dt / 2, dt)
    a = 0.2 * np.sin(2 * np.pi * frequency * t) * np.exp(-0.5 * t)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"{ti:.4f} {ai:.6f}" for ti, ai in zip(t, a, strict=True)) + "\n")


@pytest.fixture(scope="module")
def bay(tmp_path_factory: pytest.TempPathFactory):
    from test_fem_derive import PLAN, SETTINGS
    from test_fem_pushover import MATERIALS, OBJECTS

    from saengine.fem.derive import derive_fem
    from saengine.library.bim import generate

    root = tmp_path_factory.mktemp("nth-bay")
    histories = []
    for k, frequency in enumerate((1.5, 2.5, 4.0)):
        _record(root / "02 Project Settings" / "records" / f"r{k}.txt", frequency)
        histories.append(
            TimeHistory(name=f"R{k}", record=f"02 Project Settings/records/r{k}.txt", direction="X")
        )
    settings = SETTINGS.model_copy(
        update={
            "analysis": SETTINGS.analysis.model_copy(
                update={"timeHistories": histories, "nonlinearHistory": NonlinearHistory()}
            )
        }
    )
    folder = root / "08 FEM"
    folder.mkdir(parents=True)
    d = derive_fem(generate(PLAN, "s"), OBJECTS, MATERIALS, settings, None, folder)
    return d, folder, settings


def test_history_model_is_derived_with_the_nonlinear_scaling(bay) -> None:
    d, _, _ = bay
    model = d.history
    assert model is not None
    assert {e["type"] for e in model["elements"]} == {"ForceBeamColumn"}
    gravity, modal, *runs = model["analyses"]
    assert gravity["name"].startswith("G: Gravity") and modal["type"] == "Modal"
    assert len(runs) == 3 and all(r["type"] == "Transient" for r in runs)
    assert all(r["record_fibre_peaks"] and r["preload_case_ids"] == [1] for r in runs)
    assert all(r["rayleigh_mode1_stiffness"] == "committed" for r in runs)
    # R = 1, I = 1: the nonlinear records are scaled above the linear ones.
    linear = {s["id"]: s["factor"] for s in d.project["time_series"] if s.get("record_id")}
    nonlinear = {s["id"]: s["factor"] for s in model["time_series"] if s.get("record_id")}
    assert linear.keys() == nonlinear.keys()
    assert all(nonlinear[k] > linear[k] for k in linear)
    assert any("nonlinear time-history suite X: 3 records scaled" in n for n in d.notes)


def test_history_model_runs_and_is_evaluated(bay, monkeypatch: pytest.MonkeyPatch) -> None:
    from opensees_studio.services.persistence import load_project

    d, folder, settings = bay
    path = folder / nh.HISTORY_FILE
    path.write_text(json.dumps(d.history), encoding="utf-8")
    load_project(str(path)).validate_references()
    out = folder / nh.RESULTS_FOLDER
    ids = [str(a["id"]) for a in d.history["analyses"]][1:]  # modal and the records
    run = subprocess.run(
        [sys.executable, "-m", "opensees_studio.run", "--project", str(path)]
        + ["--cases", *ids, "--out", str(out)],
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    monkeypatch.setattr(acceptance, "analysis_settings", lambda _path: settings)
    found = nh.evaluate(out, path)
    assert found is not None and found["available"], found
    (suite,) = found["suites"]
    assert suite["key"] == "X" and suite["count"] == 3 and suite["rule"] == "max"
    assert suite["period"] and suite["check"] is not None
    assert found["limit"]["factor"] == 1.25
    assert found["drift"] and all(
        r["limitRatio"] == found["limit"]["ratio"] for r in found["drift"]
    )
    assert found["acceptance"]["rows"], found["notes"]
    assert any("independent design review" in n for n in found["notes"])


# ─────────────────────────────── isolated buildings (B37 hook) ───────────────────────────────


def test_ground_nodes_of_zero_length_isolators_leave_the_drift_reading() -> None:
    project = {
        "nodes": [
            {"id": 1, "coords": [0, 0, 0], "restraint": [True] * 6},
            {"id": 2, "coords": [0, 0, 0], "restraint": [False] * 6},
            {"id": 3, "coords": [0, 0, 3], "restraint": [False] * 6},
        ],
        "elements": [{"id": 1, "type": "ZeroLength", "nodes": [1, 2]}],
    }
    kept = nh._without_ground_nodes(project)
    assert [n["id"] for n in kept["nodes"]] == [2, 3]
    empty = {"nodes": [], "elements": []}
    assert nh._without_ground_nodes(empty) is empty


def test_isolated_suites_need_pairs() -> None:
    isolated = {"criteria": {"clause": "Sec 2.5.16.3.2", "minRecords": 3}, "design": {}}
    found = nh._isolation_suite_check(isolated, {}, Path("."), [], None, "X")
    assert found["ok"] is False and "pairs" in found["notes"][0]

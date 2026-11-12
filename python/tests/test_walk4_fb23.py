"""Walk 4 (W4-B, a BNBC 3-storey RC frame), feedback 2-3: the pushover in Run All, its
messages, stale results, hinge states; the substructure's other checks, the dewatering action,
reported-only rows, a buckled strut and the slope's comparator."""

from __future__ import annotations

import importlib
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from saengine.pipeline import summaries as S

R = importlib.import_module("saengine.pipeline.run_all")

SAMPLE = (
    Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"
)


# ─────────────────────────────── W4B-4: non-convergence ───────────────────────────────


def test_a_pushover_that_stopped_early_is_not_told_to_raise_its_drift():
    from saengine.fem.pushover_target import stopped_early

    analysis = {"target_disp": 0.2, "step_size": 0.002}
    stopped = SimpleNamespace(n_steps=26, n_steps_requested=100)
    assert stopped_early(analysis, stopped, 0.052) == {"step": 26, "steps": 100, "requested": 0.2}
    finished = SimpleNamespace(n_steps=100, n_steps_requested=100)
    assert stopped_early(analysis, finished, 0.2) is None
    # Results kept before the step count: judged by the displacement reached.
    old = SimpleNamespace(n_steps=26, n_steps_requested=0)
    assert stopped_early(analysis, old, 0.052) == {"step": 26, "steps": 100, "requested": 0.2}
    assert stopped_early(analysis, old, 0.2) is None


# ─────────────────────────────── W4B-11: stale pushover ───────────────────────────────


def _pushover_folder(tmp_path: Path, model_newer: bool) -> Path:
    folder = tmp_path / "08 FEM"
    run = folder / "pushover.results"
    run.mkdir(parents=True)
    model, manifest = folder / "pushover.osmodel", run / "manifest.json"
    model.write_text("{}", encoding="utf-8")
    manifest.write_text('{"cases": []}', encoding="utf-8")
    early, late = 1_700_000_000, 1_700_000_100
    os.utime(model, (late, late) if model_newer else (early, early))
    os.utime(manifest, (early, early) if model_newer else (late, late))
    return folder


def test_stale_pushover_results_are_flagged_and_left_out_of_the_report(tmp_path: Path):
    from saengine.fem.display import results_stale
    from saengine.report.build import _pushover
    from saengine.report.document import _pushover_blocks

    folder = _pushover_folder(tmp_path, model_newer=True)
    assert results_stale(folder / "pushover.results", folder / "pushover.osmodel")
    warnings: list[str] = []
    sections = _pushover(folder, warnings)
    assert [s.get("stale") for s in sections] == [True]
    assert warnings and "out of date" in warnings[0]
    text = json.dumps([str(b) for b in _pushover_blocks(sections)])
    assert "out of date" in text and "Target displacement" not in text
    current = _pushover_folder(tmp_path / "current", model_newer=False)
    assert not results_stale(current / "pushover.results", current / "pushover.osmodel")


# ─────────────────────────────── W4B-3: Run All runs the pushover ───────────────────────────────


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    target = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, target)
    return target


def _ask_pushover(root: Path) -> None:
    path = next((root / "02 Project Settings").glob("*.json"))
    for candidate in (root / "02 Project Settings").glob("*.json"):
        if "analysis" in json.loads(candidate.read_text(encoding="utf-8")):
            path = candidate
    settings = json.loads(path.read_text(encoding="utf-8"))
    settings["analysis"]["pushover"] = {"directions": ["X"]}
    path.write_text(json.dumps(settings, indent="\t"), encoding="utf-8")


def test_the_pushover_step_follows_the_settings(sample: Path, monkeypatch: pytest.MonkeyPatch):
    assert R.STEP_IDS.index("pushover") == R.STEP_IDS.index("design") + 1
    assert R.STEP_NEEDS["pushover"] == ("derive",)
    project = R.open_project(sample)
    step = R.StepResult("pushover")
    R._pushover(project, step, lambda _m: None)
    assert step.status == "skipped" and "No pushover asked for" in step.message

    _ask_pushover(sample)
    fem = project.file("fem").parent
    fem.mkdir(exist_ok=True)
    (fem / "pushover.osmodel").unlink(missing_ok=True)
    (fem / "model.derivation.json").write_text(
        json.dumps(
            {
                "notes": [
                    (
                        "pushover: members of C1, B1 stay elastic (concrete without reinforcement, "
                        "or a profile or material without a fiber section)"
                    ),
                    "pushover: no frame member has a fiber section; no pushover model",
                ]
            }
        ),
        encoding="utf-8",
    )
    project = R.open_project(sample)
    step = R.StepResult("pushover")
    R._pushover(project, step, lambda _m: None)
    assert step.status == "warning"
    assert "not run" in step.message and "no frame member has a fiber section" in step.message

    # With a pushover model: run (the solver stubbed), and a case that stopped early is said.
    (fem / "model.derivation.json").write_text('{"notes": []}', encoding="utf-8")
    model = fem / "pushover.osmodel"
    model.write_text("{}", encoding="utf-8")
    ran: list[Path] = []

    def run(path: Path, report=None, python=None):
        ran.append(path)
        out = R.results_folder(path)
        out.mkdir(exist_ok=True)
        (out / "manifest.json").write_text(
            json.dumps(
                {
                    "cases": [
                        {"case_name": "G: Gravity"},
                        {
                            "case_name": "PX: Pushover X",
                            "early_stop": True,
                            "completed_steps": 26,
                            "n_steps_requested": 100,
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        return {"status": "done", "cases": 2}

    monkeypatch.setattr(R, "run_analysis", run)
    step = R.StepResult("pushover")
    R._pushover(project, step, lambda _m: None)
    assert ran == [model]
    assert step.status == "warning"
    assert "PX: Pushover X: stopped at step 26 of 100 (did not converge)" in step.message


# ─────────────────────────────── W4B-12: hinge states by fibre strain ───────────────────────────────


def test_fibre_strains_colour_the_members_of_a_pack_without_hinge_rules():
    from saengine.fem import acceptance

    rule = acceptance.table()
    assert rule is not None and rule.method == "fibreStrain"  # the default pack
    project = {
        "materials": [
            {
                "id": 1,
                "type": "Concrete02",
                "fpc": -25e6,
                "epsc0": -0.002,
                "fpcu": -5e6,
                "epsU": -0.0035,
                "name": "core",
            },
        ],
        "sections": [
            {
                "id": 1,
                "type": "FiberSection",
                "patches": [{"kind": "rect", "material_id": 1, "n_fib_y": 1, "n_fib_z": 1}],
            },
        ],
        "nodes": [{"id": 1, "coords": [0, 0, 0]}, {"id": 2, "coords": [0, 0, 3]}],
        "elements": [
            {"id": 7, "type": "ForceBeamColumn", "section_id": 1, "nodes": [1, 2], "name": "C1#1"}
        ],
    }
    fibres = np.zeros((2, 1, 5))
    fibres[1, 0, 4] = -0.0015
    results = SimpleNamespace(element_start_fibers={}, element_end_fibers={7: fibres})
    found = acceptance.hinge_ratios(project, {"id": 2}, results, None, 1)
    assert found is not None and set(found["ratios"]) == {"7"} and found["ratios"]["7"] > 0
    empty = SimpleNamespace(element_start_fibers={}, element_end_fibers={})
    assert acceptance.hinge_ratios(project, {"id": 2}, empty, None, 1) is None


# ─────────────────────────────── W4B-7, W4B-8: excavation rows ───────────────────────────────


def test_dewatering_is_an_action_and_reported_values_are_not_checked():
    from saengine.substructure import excavation as ex

    action = ex._action("Dewatering", "plan it")
    assert action["action"] and action["flag"] and action["utilisation"] is None
    reported = ex._rule("x", True, "")  # a real yes/no requirement stays as it is
    value = {"name": "S1: design axial force", "demand": 120.0, "capacity": 120.0,
             "utilisation": 1.0, "ok": True, "flag": True}  # fmt: skip
    rows = ex.reported_only([reported, value, action])
    assert rows[0] == reported
    assert rows[1]["capacity"] is None and rows[1]["utilisation"] is None and rows[1]["ok"]
    assert rows[2] is action
    from saengine.report.build import _result_label

    assert [_result_label(r) for r in rows] == ["OK", "not checked", "ACTION"]


def test_a_strut_near_its_euler_load_buckles_instead_of_an_absurd_b1():
    from saengine.design.steel import members as sm
    from saengine.design.steel.lengths import MemberLengths
    from saengine.design.steel.properties import chs

    shape = chs(323.9, 10.0, "CHS 323.9x10")
    length = 18.0
    pe = np.pi**2 * 200000 * shape.ix / (length * 1e3) ** 2  # N
    p = 0.99 * pe
    s = np.array([0.0, length / 2, length])
    stations = sm.Stations(
        "stages", s, np.full(3, p), np.array([0.0, -36.9e6, 0.0]), np.zeros(3),
        np.zeros(3), np.zeros(3), ["end", "middle", "end"],
    )  # fmt: skip
    rows = sm.check_member(
        shape, sm.Steel(250, 400, 200000), [stations], MemberLengths.simple(length), "column"
    )
    text = " ".join(str(r.get("note", "")) for r in rows)
    assert "buckles" in text and "B1 = 146" not in text
    interaction = next(r for r in rows if "(H1)" in r["name"])
    assert interaction["utilisation"] > 1.0 and not interaction["ok"]
    # The moments stay as they are (36.9 kN·m, not thousands).
    flexure = [r for r in rows if "buckles" in str(r.get("note")) and r is not interaction]
    assert flexure and all(r["demand"] < 100 for r in flexure)


# ─────────────────────────────── W4B-6: the other checks counted ───────────────────────────────


def test_the_summary_counts_the_excavations_and_slopes_apart():
    raw = {
        "foundations": [{"id": "F1", "ok": True, "checks": []}],
        "tieBeams": [],
        "excavations": [
            {"id": "EX1", "ok": False, "checks": [{"name": "Dewatering", "action": True}]}
        ],
        "slopes": [{"id": "SL1", "ok": False, "checks": []}],
        "retainingWalls": [{"id": "RW1", "ok": True, "checks": []}],
        "summary": {"maxUtilisation": 1.3, "governing": "EX1"},
    }
    document = {"foundations": [{"id": "F1"}], "tieBeams": []}
    file = S.substructure_summary_file(document, raw)
    assert (file["checked"], file["failed"], file["status"]) == (1, 0, "fail")
    assert file["others"] == {
        "checked": 3, "failed": 2, "failing": ["EX1", "SL1"], "actions": ["EX1"]}  # fmt: skip
    plain = S.substructure_summary_file(document, {**raw, "excavations": [], "slopes": []})
    assert plain["others"]["failed"] == 0 and plain["status"] != "fail"
    bare = S.substructure_summary_file(
        document, {k: v for k, v in raw.items() if k not in S.OTHER_RESULT_KEYS}
    )
    assert "others" not in bare


def test_the_slope_note_uses_the_comparator_of_its_value():
    from saengine.substructure.slope_stability import fs_note

    assert fs_note(1.235, 1.5) == "F = 1.235 < 1.5 required: fails"
    assert fs_note(1.64, 1.5) == "F = 1.640 ≥ 1.5 required"

"""Re-walk 4, track B: the pushover of shell-slab and isolated buildings, the isolated drift
rule, missing substructure input, the base diaphragm over isolators and the transient floor
response factor."""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_fem_derive import PLAN, SETTINGS
from test_fem_pushover import MATERIALS, OBJECTS

from saengine.fem import acceptance, isolation
from saengine.fem.derive import FRAME_PUSHOVER_NOTE, derive_fem
from saengine.fem.floor_vibration import response_factor
from saengine.fem.nonlinear import NONLINEAR_SOLVER
from saengine.fem.second_order import level_nodes, storey_drifts
from saengine.library.bim import BeamElement, ColumnElement, SlabElement, generate
from saengine.library.settings import Pushover
from saengine.substructure.excavation import missing_input


def _pushover_settings(slabs: str):
    analysis = SETTINGS.analysis.model_copy(
        update={"slabs": slabs, "pushover": Pushover(directions=["X", "Y"], steps=20)}
    )
    return SETTINGS.model_copy(update={"analysis": analysis})


# ── R4B-4: the pushover of a shell-slab building on its frame model ──


def test_shell_slab_pushover_runs_on_the_frame_model(tmp_path: Path) -> None:
    d = derive_fem(generate(PLAN, "s"), OBJECTS, MATERIALS, _pushover_settings("shells"))
    assert any(e["type"] == "Shell" for e in d.project["elements"])  # the linear model keeps them
    model = d.pushover
    assert model is not None
    assert not any(e["type"] == "Shell" for e in model["elements"])
    assert any(c["type"] == "RigidDiaphragm" for c in model["mp_constraints"])
    assert FRAME_PUSHOVER_NOTE in d.notes
    assert {a["system"] for a in model["analyses"]} == {NONLINEAR_SOLVER}
    names = [a["name"] for a in model["analyses"]]
    assert names[1:] == ["PX: Pushover X", "PY: Pushover Y"]


def test_loads_to_beams_pushover_is_derived_as_before() -> None:
    d = derive_fem(generate(PLAN, "s"), OBJECTS, MATERIALS, _pushover_settings("loadsToBeams"))
    assert d.pushover is not None and FRAME_PUSHOVER_NOTE not in d.notes


def test_progress_names_every_running_case(tmp_path: Path, monkeypatch) -> None:
    import importlib

    # The module, not the package's run_all function of the same name.
    run_all = importlib.import_module("saengine.pipeline.run_all")

    lines = [
        {"type": "case_started", "case_id": 2, "case_name": "PX: Pushover X", "case_type": "x"},
        {"type": "case_started", "case_id": 3, "case_name": "PY: Pushover Y", "case_type": "x"},
        {"type": "progress", "case_id": 2, "step": 8, "total": 100},
        {"type": "progress", "case_id": 3, "step": 5, "total": 100},
        {"type": "case_finished", "case_id": 2, "case_name": "PX: Pushover X"},
        {"type": "progress", "case_id": 3, "step": 6, "total": 100},
    ]

    class Child:
        def __init__(self, *args, **kwargs) -> None:
            self.stdout = iter(json.dumps(line) + "\n" for line in lines)

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def wait(self) -> int:
            return 0

    handlers = SimpleNamespace(
        validate_project=lambda path: {"ok": True, "summary": {"analyses": [{"id": 2}, {"id": 3}]}}
    )
    monkeypatch.setattr(run_all, "_handlers", lambda: handlers)
    monkeypatch.setattr(run_all.subprocess, "Popen", Child)
    shown: list[str] = []
    model = tmp_path / "pushover.osmodel"
    model.write_text("{}", encoding="utf-8")
    assert run_all.run_analysis(model, shown.append)["status"] == "done"
    assert "PX: Pushover X: step 8 of 100; PY: Pushover Y: step 5 of 100" in shown
    assert shown[-1] == "PY: Pushover Y: step 6 of 100"


# ── R4B-2: the isolators' movement is not storey drift; one drift rule ──


def _isolated_column() -> dict:
    return {
        "nodes": [
            {"id": 1, "coords": [0, 0, 0], "restraint": [False, False, False, True, True, True]},
            {"id": 2, "coords": [0, 0, 3.6], "restraint": [False] * 6},
            {"id": 3, "coords": [0, 0, 0], "restraint": [True] * 6},  # the isolator's ground
        ]
    }


def test_storey_drift_leaves_the_isolator_out() -> None:
    project = _isolated_column()
    assert level_nodes(project, [0.0, 3.6])[0] == {(0, 0): 1}
    disp = {1: [0.05, 0, 0, 0, 0, 0], 2: [0.0536, 0, 0, 0, 0, 0], 3: [0.0] * 6}
    (row,) = storey_drifts(project, disp, 0, [0.0, 3.6])
    assert row["drift"] == pytest.approx(0.0036 / 3.6)


def test_a_fixed_base_alone_stays_the_storeys_bottom() -> None:
    project = {
        "nodes": [
            {"id": 1, "coords": [0, 0, 0], "restraint": [True] * 6},
            {"id": 2, "coords": [0, 0, 3.0], "restraint": [False] * 6},
        ]
    }
    assert level_nodes(project, [0.0, 3.0]) == [{(0, 0): 1}, {(0, 0): 2}]


def _isolation_summary() -> dict:
    return {
        "schema": isolation.SCHEMA,
        "available": True,
        "drift": {"Cd": {"X": 1.6, "Y": 1.6}, "importance": 1.0, "limits": {}},
    }


def test_the_charts_take_the_isolated_drift_rule(tmp_path: Path) -> None:
    from saengine.codes import context as code_context

    with code_context.using(code_context.pack_for(SETTINGS, None)):
        rule = isolation.drift_rule(_isolation_summary())
    assert rule is not None
    assert rule["amplification"] == {"X": 1.6, "Y": 1.6}
    assert rule["allowable"] > 0.005  # the isolation limit, not the fixed-base Δa / Cd


# ── R4B-1: the pushover of an isolated building says it is fixed-base ──


def test_isolated_fixed_base_pushover_is_said(tmp_path: Path) -> None:
    (tmp_path / isolation.ISOLATION_FILE).write_text(
        json.dumps(_isolation_summary()), encoding="utf-8"
    )
    model = tmp_path / "pushover.osmodel"
    note = acceptance.isolated_fixed_base_note({"elements": []}, model)
    assert note and "fixed base" in note
    with_bearings = {"elements": [{"name": f"C1{isolation.ELEMENT_SUFFIX}"}]}
    assert acceptance.isolated_fixed_base_note(with_bearings, model) is None
    assert acceptance.isolated_fixed_base_note({"elements": []}, tmp_path / "x" / "m") is None


# ── R4B-3: missing input is not a fail ──


def test_missing_input_is_not_checked() -> None:
    from saengine.report.build import _result_label

    row = missing_input("Sheet piles above ground", "enter the height")
    assert row["ok"] is True and row["flag"] is True and row["utilisation"] is None
    assert row["demand"] is None and row["capacity"] is None
    assert _result_label(row) == "input missing"


def test_no_placeholder_rules_left() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "saengine" / "substructure"
    for name in ("excavation.py", "machine.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert '_rule(f"{post.name} diameter", False' not in text
        assert '\n                    False,\n                    "enter' not in text


# ── R4B-5: isolated column bases need a diaphragm above the isolators ──


def _column(cid: str, x: float) -> ColumnElement:
    return ColumnElement(id=cid, type="COL", position=[x, 0], bottom=0, top=3600)


def test_unframed_isolated_columns() -> None:
    columns = [_column("C1", 0), _column("C2", 6000), _column("C3", 12000)]
    upper = BeamElement(id="B1", type="BM", start=[0, 0], end=[12000, 0], elevation=3600)
    building = SimpleNamespace(elements=[*columns, upper])
    assert isolation.unframed_isolated_columns(building, {"C1", "C2", "C3"}) == ["C1", "C2", "C3"]
    base = BeamElement(id="B0", type="BM", start=[0, 0], end=[6000, 0], elevation=0)
    building = SimpleNamespace(elements=[*columns, upper, base])
    assert isolation.unframed_isolated_columns(building, {"C1", "C2", "C3"}) == ["C3"]
    slab = SlabElement(
        id="S0", type="SL", boundary=[[0, -100], [12000, -100], [12000, 100], [0, 100]], elevation=0
    )
    building = SimpleNamespace(elements=[*columns, slab])
    assert isolation.unframed_isolated_columns(building, {"C1", "C2", "C3"}) == []


# ── R4B-6: the transient response factor is the rms over one footfall period ──


def test_transient_response_factor_rms() -> None:
    rules = SimpleNamespace(
        modalShare=0.25,
        walkerWeight=746.0,
        pace=(1.8, 2.2),
        highFrequency=10.0,
        impulse=54.0,
        impulsePace=1.43,
        impulseFrequency=1.3,
        impulseWeight=700.0,
        baseAcceleration=0.005,
    )
    fn, mass, zeta = 15.0, 16_500.0, 0.02
    found = response_factor(fn, mass, 6.0, zeta, rules)
    # v(t) = v e^(-2π ζ fn t) sin(2π fn t), its rms over 1/fp by quadrature.
    fp = 2.2
    impulse = 54 * fp**1.43 / fn**1.3 * 746 / 700
    v = impulse / (0.25 * mass)
    n = 20_000
    total = 0.0
    for k in range(n):
        t = (k + 0.5) / (n * fp)
        total += (v * math.exp(-2 * math.pi * zeta * fn * t) * math.sin(2 * math.pi * fn * t)) ** 2
    v_rms = math.sqrt(total / n)
    expected = (8 / fn) * 2 * math.pi * fn * v_rms / 0.005
    assert found["kind"] == "transient"
    assert found["R"] == pytest.approx(expected, rel=0.01)

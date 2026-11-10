"""Re-walk 4, track B: the pushover of shell-slab and isolated buildings, the isolated drift
rule, missing substructure input, the base diaphragm over isolators and the transient floor
response factor."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from test_fem_derive import PLAN, SETTINGS
from test_fem_pushover import MATERIALS, OBJECTS

from saengine.fem.derive import FRAME_PUSHOVER_NOTE, derive_fem
from saengine.fem.nonlinear import NONLINEAR_SOLVER
from saengine.library.bim import generate
from saengine.library.settings import Pushover


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

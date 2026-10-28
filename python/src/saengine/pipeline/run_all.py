"""The headless Run All: the app's Run All without the workbench.

The same steps, in the same order, reading and writing the same files as the workbench's
``RunAllService`` (``contrib/saengineFem/electron-browser/runAll.ts``), so that after
``saengine run-all`` the app's part list shows the results as current:

0. ``bim``: builds ``06 BIM/bim.json`` from the floor plan (or the structural model) when it was
   never built or its source changed; a model without members stops here ("nothing to
   analyse");
1. ``derive``: derives ``08 FEM/model.osmodel`` (with ``pushover.osmodel``, ``thermal.json`` and
   ``ssi.json``) when it is not derived yet or a source changed (``deriveAnalysisModel``);
2. ``analysis``: runs every analysis case with OpenSees Studio's runner
   (``python -m opensees_studio.run``, as ``FemSolverService.startRun``) into
   ``08 FEM/model.results``, unless the results were computed from the same model (the stamp
   kept in ``analysis-inputs.json``: a model derived again from a change the analysis does not
   take, such as bars or the engineer's name, keeps them);
3. ``ssi``: on soil springs (``08 FEM/ssi.json``), the fixed-base run and the comparison;
4. ``substructure``: moves the building model's footings into a placeholder
   ``substructure.json``, gives foundations without bars the minimum mesh, designs the
   foundations (``saengine.substructure.run.design_foundations``), writes
   ``09 Substructure/substructure.results/summary.json``. Before the design checks, which read
   the substructure file too: the bars it adds would otherwise make the kept checks stale and
   the report check every member again;
5. ``design``: the RC design checks, writing ``08 FEM/model.results/design-summary.json``. A
   run that checks nothing fails the step (it is not "0 pass, 0 fail");
6. ``mep``: the coordination of 7 MEP, its plumbing, HVAC (never starting EnergyPlus: its cached
   loads when they match, else the estimate), electrical and fire checks, writing
   ``07 MEP/mep.results/summary.json``;
7. ``boq``: measures ``10 BOQ/boq.json`` when it is out of date (or waits for tank designs that
   the plumbing step has just made);
8. ``report``: builds ``11 Exports/report.pdf``;
9. ``drawings``: the structural drawings of ``11 Exports/Drawings``
   (:mod:`saengine.pipeline.drawings`), drawn again when a set was generated before and is out
   of date, with the design checks of step 4. A project whose drawings were never generated
   skips it (generating them takes from seconds to minutes: the engineer starts the first set
   from the Exports page or with ``--steps drawings``, which always draws them).

As in the app, a step that cannot be done fails, and the steps that need it are not run
(``notRun``, saying which step they wait for); the others still run. A failed step also removes
the summary it would have written, so the part list never shows the previous run's verdict as
current. The backend calls are the RPC handlers themselves (:mod:`saengine.rpc.handlers`), called in
this process; the summaries are written by :mod:`saengine.pipeline.summaries`, the Python twin of
the TypeScript writers.

What cannot be matched headlessly: the app first saves the editors' unsaved changes (the command
line reads the files as saved), and it writes the bill through the editor's text model, which
keeps the file's line endings: :func:`_write_like_text_model` does the same.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from saengine.codes import context as code_context
from saengine.fem.derive import model_stamp
from saengine.fire.summary import fire_failures, fire_summary_file, has_fire
from saengine.library.bim import source_stamp
from saengine.pipeline import summaries as S
from saengine.pipeline.design_mode import ANALYSIS_INPUTS_FILE
from saengine.pipeline.project import Project, open_project, read_text, write_text
from saengine.pipeline.status import (
    PartStatus,
    boq_source_stamp,
    fem_source_changed,
    part_statuses,
    recorded_sources,
    recorded_stamp,
)

#: The steps, in order, with the names the app's status bar gives them.
STEPS: tuple[tuple[str, str], ...] = (
    ("bim", "building model"),
    ("derive", "analysis model"),
    ("analysis", "analysis"),
    ("ssi", "fixed-base run for the soil springs"),
    ("substructure", "foundation design"),
    ("design", "design checks"),
    ("mep", "MEP coordination, plumbing, HVAC, electrical and fire checks"),
    ("boq", "bill of quantities"),
    ("report", "report"),
    ("drawings", "drawings"),
)
STEP_IDS: tuple[str, ...] = tuple(s for s, _ in STEPS)
STEP_LABELS = dict(STEPS)

#: Step statuses: done; done with something to look at (bars added, members not checked, a mesh
#: warning); nothing to do (up to date, nothing to check); could not be done; an unexpected
#: error; not run because a step it needs did not succeed.
STEP_STATUSES = ("ok", "warning", "skipped", "failed", "error", "notRun")
#: The steps each step needs (``STEP_NEEDS`` in runAll.ts): when one of them fails or is not run,
#: the step is not run either.
STEP_NEEDS: dict[str, tuple[str, ...]] = {
    "bim": (),
    "derive": ("bim",),
    "analysis": ("derive",),
    "ssi": ("analysis",),
    "substructure": ("analysis",),
    "design": ("analysis",),
    "mep": ("bim",),
    "boq": ("bim",),
    "report": ("design",),
    "drawings": ("design",),
}

#: ``DERIVATION_SOURCES``: the parts the model is derived from, their keys and labels.
DERIVATION_SOURCES = (
    ("bim", "bim", "Building Model"),
    ("settings", "settings", "Project Settings"),
    ("objects", "objects", "Object Types"),
    ("materials", "materials", "Materials"),
)
DERIVATION_INPUTS = (
    "bim",
    "settings",
    "objects",
    "materials",
    "soil",
    "mep",
    "substructure",
    "loads",
)
#: ``BOQ_SOURCES``: (part, label, required, optional).
BOQ_SOURCES = (
    ("bim", "Building Model", True, False),
    ("objects", "Object Types", True, False),
    ("materials", "Materials", True, False),
    ("substructure", "Substructure", False, False),
    ("mep", "MEP", False, False),
    ("settings", "Ground Level (Project Settings)", False, True),
)
TANK_BARS_PENDING = "its bars are not measured: it has no current design"

PUSHOVER_FILE = "pushover.osmodel"
THERMAL_FILE = "thermal.json"
SSI_FILE = "ssi.json"
FACES_FILE = "faces.json"

#: A progress callback: ``(step id, step index, step count, message or None)``.
Progress = Callable[[str, int, int, str | None], None]


@dataclass
class StepResult:
    """One step of a run: ``status`` (:data:`STEP_STATUSES`), what happened, and its counts."""

    id: str
    status: str = "skipped"
    message: str = ""
    counts: dict[str, Any] = field(default_factory=dict)
    outputs: list[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def label(self) -> str:
        return STEP_LABELS[self.id]

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "message": self.message,
            "counts": self.counts,
            "outputs": self.outputs,
            "seconds": round(self.seconds, 3),
        }


@dataclass
class RunAllResult:
    """A run: its steps (every step of :data:`STEPS` asked for, in order), where it stopped, the
    status of each part as the sidebar shows it afterwards, and the app's one-line summary."""

    project: Project
    steps: list[StepResult]
    parts: list[PartStatus]
    stopped_at: str | None = None
    summary: str = ""

    @property
    def ok(self) -> bool:
        return self.stopped_at is None

    @property
    def failed(self) -> list[StepResult]:
        """The steps that failed (``failed`` or ``error``)."""
        return [s for s in self.steps if s.status in ("failed", "error")]

    def step(self, step_id: str) -> StepResult | None:
        return next((s for s in self.steps if s.id == step_id), None)

    def to_json(self) -> dict[str, Any]:
        return {
            "project": {
                "root": str(self.project.root),
                "name": self.project.name,
                "type": self.project.type,
            },
            "ok": self.ok,
            "stoppedAt": self.stopped_at,
            "summary": self.summary,
            "steps": [s.to_json() for s in self.steps],
            "parts": [p.to_json() for p in self.parts],
        }


class StepFailure(Exception):
    """A step that could not be done: Run All stops and says which (``StepFailure``)."""


def _relative(project: Project, path: Path) -> str:
    try:
        return path.relative_to(project.root).as_posix()
    except ValueError:
        return str(path)


def _handlers():
    from saengine.rpc import handlers

    return handlers


def _problems_only(raw: Any, keys: tuple[str, ...]) -> None:
    """``problemsOrResult``: an answer of only problems is a step failure."""
    problems = S.problems_only(raw, keys)
    if problems:
        raise StepFailure(" ".join(problems))


# ─────────────────────────────── 0: building model ───────────────────────────────


def bim_members(text: str | None) -> int:
    """``bimMembers``: the elements of a building model (0 for a placeholder or an unreadable
    file)."""
    try:
        value = json.loads(text) if text else None
    except ValueError:
        return 0
    elements = value.get("elements") if isinstance(value, dict) else None
    return len(elements) if isinstance(elements, list) else 0


def _plot_checks(project: Project, floor_plan_text: str) -> list[dict[str, Any]]:
    """The floor plan's members outside the soil report's plot or in its setbacks
    (``saengine.gis.plot``), written as the floor plan's checks (each one fails) when the site
    has a plot."""
    from saengine.gis.plot import encroachments, part_check_counts
    from saengine.pipeline.status import write_part_checks
    from saengine.soil.report import parse

    soil_text = project.text("soil")
    report = parse(soil_text) if soil_text else None
    if report is None or isinstance(report, list):
        return []
    found = encroachments(report.site, floor_plan_text, project.text("objects"))
    if found["plot"] is None:
        return []
    write_part_checks(
        project, "floorPlan", part_check_counts(found), ("floorPlan", "soil", "objects")
    )
    return found["warnings"]


def _bim(project: Project, step: StepResult) -> None:
    upstream = "structure" if project.type == "structure" else "floorPlan"
    source = project.text(upstream)
    current = project.text("bim")
    try:
        document = json.loads(current) if current else None
    except ValueError:
        document = None
    recorded = recorded_stamp(document, upstream)
    if source is None:
        raise StepFailure(
            f"{'The structural model' if upstream == 'structure' else 'The floor plan'} could not be read."
        )
    if recorded is not None and recorded == source_stamp(source):
        step.status = "skipped"
        step.message = "The building model is up to date."
    else:
        handlers = _handlers()
        result = (
            handlers.generate_building_from_structure(source, current)
            if upstream == "structure"
            else handlers.generate_building(source, current)
        )
        if not result.get("text"):
            raise StepFailure(
                "; ".join(result.get("problems") or ["The building model could not be built."])
            )
        write_text(project.file("bim"), result["text"])
        step.outputs.append(_relative(project, project.file("bim")))
        current = result["text"]
        step.status = "ok"
        step.message = "Building model built."
    members = bim_members(current)
    step.counts = {"elements": members}
    if upstream == "floorPlan":
        outside = _plot_checks(project, source)
        if outside:
            step.counts["plotWarnings"] = len(outside)
            step.message += (
                f" {len(outside)} member(s) outside the plot or in its setbacks: "
                + "; ".join(w["message"].rstrip(".") for w in outside[:3])
                + ("; ..." if len(outside) > 3 else ".")
            )
    if not members:
        # G3: nothing to analyse, so nothing after it means anything ("0 pass, 0 fail").
        raise StepFailure(
            "Nothing to analyse: the building model has no members. Draw the grids, columns "
            "and beams in 5 Floor Plan first."
        )


# ─────────────────────────────── 1: derive ───────────────────────────────


def mep_has_content(text: str | None) -> bool:
    """``mepHasContent`` (femDerivationBar.ts): equipment, openings or shafts, HVAC plant or
    electrical equipment."""
    try:
        value = json.loads(text) if text else None
    except ValueError:
        return False
    if not isinstance(value, dict):
        return False

    def listed(item: Any) -> bool:
        return isinstance(item, list) and len(item) > 0

    hvac = value.get("hvac") if isinstance(value.get("hvac"), dict) else {}
    electrical = value.get("electrical") if isinstance(value.get("electrical"), dict) else {}
    fire = value.get("fire") if isinstance(value.get("fire"), dict) else {}
    return (
        any(listed(value.get(k)) for k in ("equipment", "openings", "shafts"))
        or listed(hvac.get("plant"))
        or listed(electrical.get("equipment"))
        or listed(fire.get("pumps"))
        or any(isinstance(t, dict) and t.get("kind") == "overhead" for t in fire.get("tanks") or [])
    )


def derivation_state(description: Any, texts: dict[str, str | None]) -> tuple[bool, list[str]]:
    """``derivationState``: whether the model was derived, and the labels of the sources
    changed since."""
    from saengine.fem.derive import mep_stamp

    recorded = recorded_sources(description)
    changed = [
        label
        for part, key, label in DERIVATION_SOURCES
        if fem_source_changed(texts, part, recorded.get(key))
    ]
    for part, label in (("soil", "Soil Report"), ("substructure", "Substructure")):
        if part in recorded:
            text = texts.get(part)
            if text is None or recorded[part] != source_stamp(text):
                changed.append(label)
    mep_text = texts.get("mep")
    if "mep" in recorded:
        if mep_text is None or recorded["mep"] != mep_stamp(mep_text):
            changed.append("MEP")
    elif recorded and mep_has_content(mep_text):
        changed.append("MEP")
    from saengine.pipeline.status import loads_have_content

    loads_text = texts.get("loads")
    if "loads" in recorded:
        if loads_text is None or recorded["loads"] != source_stamp(loads_text):
            changed.append("Line Loads")
    elif recorded and loads_have_content(loads_text):
        changed.append("Line Loads")
    return bool(recorded), changed


def _derive(project: Project, step: StepResult) -> bool:
    texts = project.texts(DERIVATION_INPUTS)
    model = project.file("fem")
    try:
        description = (
            json.loads(model.read_text(encoding="utf-8")).get("meta", {}).get("description")
        )
    except (OSError, ValueError, AttributeError):
        description = None
    derived, changed = derivation_state(description, texts)
    if derived and not changed:
        step.status = "skipped"
        step.message = "The analysis model is up to date."
        return False
    missing = [label for part, _, label in DERIVATION_SOURCES if texts.get(part) is None]
    if missing:
        raise StepFailure(f"{', '.join(missing)} could not be read.")
    result = _handlers().derive_fem(
        texts["bim"],
        texts["objects"],
        texts["materials"],
        texts["settings"],
        str(model.parent),
        texts.get("soil"),
        texts.get("mep"),
        texts.get("substructure"),
        texts.get("loads") or "",
    )
    if not result.get("text"):
        raise StepFailure("; ".join(result.get("problems") or []))
    folder = model.parent
    for name, text in (
        (THERMAL_FILE, result.get("thermalText")),
        (SSI_FILE, result.get("ssiText")),
        (FACES_FILE, result.get("facesText")),
    ):
        side = folder / name
        if text is not None:
            write_text(side, text)
            step.outputs.append(_relative(project, side))
        elif side.exists():
            side.unlink()
    write_text(model, result["text"])
    step.outputs.append(_relative(project, model))
    if result.get("pushoverText"):
        write_text(folder / PUSHOVER_FILE, result["pushoverText"])
        step.outputs.append(_relative(project, folder / PUSHOVER_FILE))
    summary = result.get("summary") or {}
    step.counts = {
        "nodes": summary.get("nodes", 0),
        "elements": summary.get("elements", 0),
        "baseShear": summary.get("base_shear_kN", 0),
        "weight": summary.get("weight_kN", 0),
        "changed": changed if derived else [],
        "notes": list(result.get("notes") or []),
    }
    step.status = "ok"
    step.message = (
        f"Derived {summary.get('nodes', 0)} nodes and {summary.get('elements', 0)} elements; "
        f"base shear {float(summary.get('base_shear_kN', 0)):.1f} kN, seismic weight "
        f"{float(summary.get('weight_kN', 0)):.1f} kN."
    )
    return True


# ─────────────────────────────── 2: analysis ───────────────────────────────


def results_folder(model: Path) -> Path:
    """``resultsFolder``: ``model.osmodel`` -> ``model.results`` beside it."""
    name = model.name
    stem = name[: -len(".osmodel")] if name.lower().endswith(".osmodel") else name
    return model.parent / f"{stem}.results"


def run_analysis(
    model: Path,
    report: Callable[[str], None] | None = None,
    python: str | None = None,
) -> dict[str, Any]:
    """Runs every case of ``model`` with OpenSees Studio's runner, as the app does: validates
    it, removes the previous run's results (only when they are one), runs
    ``python -P -u -m opensees_studio.run --project … --cases … --out …`` (``-P``: the project
    folder, the working folder, is not on ``sys.path``) and reads its event lines.
    Returns ``{"status": "done"|"invalid"|"empty"|"failed", "cases", "message"?}``."""
    validation = _handlers().validate_project(str(model))
    summary = validation.get("summary")
    if not validation.get("ok") or not summary:
        errors = "; ".join(validation.get("errors") or [])
        return {
            "status": "invalid",
            "cases": 0,
            "message": f"The model cannot be analyzed: {errors}",
        }
    case_ids = [case["id"] for case in summary.get("analyses", [])]
    if not case_ids:
        return {"status": "empty", "cases": 0, "message": "The model defines no analysis cases."}
    out_dir = results_folder(model)
    if (out_dir / "manifest.json").exists():
        shutil.rmtree(out_dir)
    # ``-P`` (and PYTHONSAFEPATH for any process the runner starts): the working folder is the
    # project's, which a received project or a .civil archive fills, so it must not be on
    # sys.path, or a planted ``opensees_studio`` package would run in place of the solver.
    args = [
        python or sys.executable, "-P", "-u", "-m", "opensees_studio.run",
        "--project", str(model), "--cases", *map(str, case_ids), "--out", str(out_dir),
    ]  # fmt: skip
    env = {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONSAFEPATH": "1",
    }
    last_error: str | None = None
    names: dict[int, str] = {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with subprocess.Popen(
        args,
        cwd=model.parent,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
    ) as child:
        assert child.stdout is not None
        for line in child.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue  # plain output: the app shows it in its log
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind == "error":
                last_error = str(event.get("message"))
            elif kind == "case_started":
                names[event.get("case_id")] = str(event.get("case_name", ""))
                if report:
                    report(f"{event.get('case_name')} ({_case_type(event.get('case_type'))})")
            elif kind == "progress" and report:
                name = names.get(event.get("case_id"), "")
                report(f"{name}: step {event.get('step')} of {event.get('total')}")
            elif kind == "case_finished" and report:
                report(f"{event.get('case_name')} finished")
        code = child.wait()
    if code != 0:
        message = last_error or f"The solver process exited unexpectedly (exit code {code})."
        return {"status": "failed", "cases": 0, "message": message}
    return {"status": "done", "cases": len(case_ids)}


def _case_type(value: Any) -> str:
    """``caseTypeLabel``: "Static" of "StaticCase"."""
    text = str(value or "")
    return text.removesuffix("Case")


def analysis_inputs_stamp(model: Path) -> str | None:
    """The stamp of what the solver computes from: the model without its meta
    (:func:`saengine.fem.derive.model_stamp`) and its side files (the temperature
    case, the soil springs, the support faces). None when the model cannot be read."""
    try:
        parts = [model_stamp(model.read_bytes())]
    except OSError:
        return None
    for name in (THERMAL_FILE, SSI_FILE, FACES_FILE):
        try:
            parts.append(
                f"{name}={source_stamp((model.parent / name).read_text(encoding='utf-8'))}"
            )
        except OSError:
            parts.append(f"{name}=")
    return source_stamp("\n".join(parts))


def results_current(model: Path) -> bool:
    """Whether the results beside ``model`` were computed from the same analysis: their
    manifest is there and the kept stamp (:data:`ANALYSIS_INPUTS_FILE`, written by Run All after
    the run) matches the model and its side files now."""
    out = results_folder(model)
    try:
        kept = json.loads((out / ANALYSIS_INPUTS_FILE).read_text(encoding="utf-8"))
        manifest = (out / "manifest.json").read_bytes()
    except (OSError, ValueError):
        return False
    return (
        isinstance(kept, dict)
        and kept.get("manifest") == source_stamp(manifest.decode("utf-8", errors="replace"))
        and kept.get("stamp") == analysis_inputs_stamp(model)
    )


def keep_analysis_inputs(model: Path) -> None:
    """Writes :data:`ANALYSIS_INPUTS_FILE` for the results just computed, or kept."""
    out = results_folder(model)
    manifest = (out / "manifest.json").read_bytes().decode("utf-8", errors="replace")
    write_text(
        out / ANALYSIS_INPUTS_FILE,
        json.dumps({"stamp": analysis_inputs_stamp(model), "manifest": source_stamp(manifest)})
        + "\n",
    )


def _analysis(project: Project, step: StepResult, report: Callable[[str], None]) -> None:
    model = project.file("fem")
    if results_current(model):
        # X28/X19: the model was derived again from a change the analysis does not take (bars,
        # names): the results stand. The manifest is written again, unchanged, so the part list
        # sees results as new as the model (design_mode stamps it by content).
        manifest = results_folder(model) / "manifest.json"
        manifest.write_bytes(manifest.read_bytes())
        step.status = "skipped"
        step.message = "The analysis results are current: the analysis model did not change."
        step.outputs.append(_relative(project, results_folder(model)))
        return
    outcome = run_analysis(model, report)
    if outcome["status"] != "done":
        raise StepFailure(outcome.get("message") or outcome["status"])
    keep_analysis_inputs(model)
    step.status = "ok"
    step.counts = {"cases": outcome["cases"]}
    step.message = f"Analysis complete: {outcome['cases']} case(s)."
    step.outputs.append(_relative(project, results_folder(model)))
    # The mesh convergence check (``analysis.meshCheck``, saengine.fem.mesh_check): a warning,
    # never a stop, as the app's Run All.
    report("mesh check")
    check = _handlers().mesh_check(str(project.root))
    if check.get("problems"):
        step.counts["meshCheck"] = {"problems": check["problems"]}
    elif "skipped" not in check:
        step.counts["meshCheck"] = {
            "maxChangePercent": check.get("maxChangePercent"),
            "warning": bool(check.get("warning")),
            "note": check.get("note"),
        }
        if check.get("warning"):
            step.message += f" Warning: {check.get('note')}."
            step.status = "warning"


# ─────────────────────────────── 3: soil springs ───────────────────────────────


def _ssi(project: Project, step: StepResult) -> None:
    folder = project.file("fem").parent
    if not (folder / SSI_FILE).exists():
        step.message = "The supports are not soil springs."
        return
    raw = _handlers().ssi_compare(str(project.root))
    _problems_only(raw, ("periods",))
    step.status = "ok"
    step.message = "Fixed base compared with the soil springs."
    step.outputs.append("08 FEM/ssi-compare.json")


# ─────────────────────────────── 4: design ───────────────────────────────


def _design(project: Project, step: StepResult) -> dict[str, Any]:
    model = project.file("fem")
    from saengine.pipeline import design_mode

    # The stamp is taken before the design reads the files (an edit meanwhile leaves the kept
    # checks stale); the checks are kept for the drawings (design-report.json).
    try:
        stamp: str | None = design_mode.report_stamp(results_folder(model), model)
    except Exception:  # noqa: BLE001 - the checks are made without being kept
        stamp = None
    if stamp is None:
        report = _handlers().design_report(str(results_folder(model)), str(model))
    else:
        # The checks once, for the report here and the required steel below (design_mode).
        try:
            design_mode.gathered(results_folder(model), model, stamp)
        except Exception:  # noqa: BLE001, S110 - the report is then made on its own
            pass
        report = design_mode.checks(results_folder(model), model, stamp)
    if not report:
        raise StepFailure("The design checks are not available.")
    summary = S.record(report.get("summary"))
    no_bars = [str(t) for t in summary.get("noBars") or []]
    # The members alone: the totals also count the joints and the building's seismic checks.
    elements = S.record(summary.get("elements"))
    if not (elements.get("checked") if "checked" in elements else summary.get("checked")):
        # G1: a run that checked nothing is not "0 pass, 0 fail".
        reason = (
            f"the object types {', '.join(no_bars)} have no bars (8 FEM, Design Reinforcement "
            "proposes them)"
            if no_bars
            else "; ".join(map(str, (report.get("notes") or [])[:2]))
            or "no member could be checked"
        )
        raise StepFailure(f"The design checks checked nothing: {reason}.")
    if stamp is not None:
        design_mode.keep_report(results_folder(model), model, report, stamp)
    target = results_folder(model) / S.DESIGN_SUMMARY_FILE
    file = S.design_summary_file(report)
    write_text(target, S.summary_text(file))
    step.outputs.append(_relative(project, target))
    if stamp is not None and (results_folder(model) / design_mode.REPORT_FILE).exists():
        step.outputs.append(_relative(project, results_folder(model) / design_mode.REPORT_FILE))
    step.status = "ok"
    step.counts = {
        k: file[k] for k in ("checked", "passed", "failed", "maxUtilisation", "governing")
    }
    step.message = f"{summary.get('passed')} pass, {summary.get('failed')} fail"
    if no_bars:
        # X29: members of types without bars are not checked; said, not hidden.
        step.status = "warning"
        step.counts["noBars"] = no_bars
        step.message += f"; not checked for want of bars: {', '.join(no_bars)}"
    # Design mode: the steel each element requires next to what is entered, kept beside the
    # results (design-required.json) for the Properties panel and the report. A failure here
    # is a note, not a stop: the checks above are the verdict.
    from saengine.pipeline.design_mode import REQUIRED_FILE, required_summary

    try:
        required = _handlers().design_required(str(results_folder(model)), str(model))
    except Exception as error:  # noqa: BLE001 - the checks stand without the required steel
        step.counts["requiredSteel"] = None
        step.message += f"; required steel not worked out ({str(error) or type(error).__name__})"
        return report
    steel = required_summary(required)
    step.counts["steelShort"] = steel["short"]
    step.counts["tooSmall"] = steel["tooSmall"]
    if (results_folder(model) / REQUIRED_FILE).exists():
        step.outputs.append(_relative(project, results_folder(model) / REQUIRED_FILE))
    if steel["short"]:
        step.message += f"; steel short in {len(steel['short'])} element(s)"
    if steel["tooSmall"]:
        step.message += f", {len(steel['tooSmall'])} section(s) too small"
    return report


# ─────────────────────────────── 5: substructure ───────────────────────────────


def _substructure(project: Project, step: StepResult, add_bars: bool) -> dict[str, Any] | None:
    root = str(project.root)
    migration = _handlers().substructure_ensure(root)
    problems = migration.get("problems") if isinstance(migration, dict) else None
    if problems:
        raise StepFailure(" ".join(map(str, problems)))
    resource = project.file("substructure")
    text = read_text(resource)
    if text is None:
        step.message = "There is no substructure file."
        return None
    kind, document = S.parse_substructure(text)
    if kind == "error":
        raise StepFailure(document)
    if kind == "placeholder" or not document["foundations"]:
        step.message = "There are no foundations to design."
        return None
    # U3: the whole Run All gives foundations without bars the minimum mesh before checking them
    # (``design_foundations``); a check or a chosen step only checks what is saved.
    handlers = _handlers()
    raw = handlers.substructure_design(root) if add_bars else handlers.substructure_report(root)
    if add_bars:
        text = read_text(resource) or text
        kind, document = S.parse_substructure(text)
        if kind != "document":
            raise StepFailure(document if kind == "error" else "The substructure was emptied.")
    if (
        isinstance(raw, dict)
        and isinstance(raw.get("problems"), list)
        and raw["problems"]
        and raw.get("foundations") is None
        and raw.get("substructure") is None
    ):  # orThrow
        raise StepFailure(" ".join(map(str, raw["problems"])))
    report = S.substructure_report_summary(raw)
    if report is None:
        raise StepFailure("The foundation design is not available.")
    file = S.substructure_summary_file(document, raw)
    target = resource.parent / S.SUBSTRUCTURE_SUMMARY_FILE
    write_text(target, S.summary_text(file))
    step.outputs.append(_relative(project, target))
    step.status = "ok"
    step.counts = {k: file[k] for k in ("foundations", "checked", "passed", "failed",
                                        "maxUtilisation", "governing")}  # fmt: skip
    step.message = f"foundations {report['passed']} pass, {report['failed']} fail"
    summary = S.record(raw.get("summary"))
    added = [str(f) for f in summary.get("barsAdded") or []]
    if added:
        step.status = "warning"
        step.counts["barsAdded"] = added
        step.message += f"; minimum bars given to {', '.join(added)}: review them"
    if file.get("status") == "incomplete":
        step.status = "warning"
        step.message += f"; {file['checked']} of {file['total']} checked"
        if file.get("unsupported"):
            step.message += f", no foundation under {', '.join(map(str, file['unsupported']))}"
    return report


# ─────────────────────────────── 6: MEP ───────────────────────────────


def _mep(project: Project, step: StepResult) -> dict[str, Any] | None:
    resource = project.file("mep")
    text = read_text(resource)
    if text is None:
        step.message = "There is no MEP file."
        return None
    kind, document = S.parse_mep(text)
    if kind == "error":
        raise StepFailure(document)
    with_plumbing = kind == "document" and S.has_plumbing(document)
    with_hvac = kind == "document" and S.has_hvac(document)
    with_electrical = kind == "document" and S.has_electrical(document)
    with_fire = kind == "document" and has_fire(document)
    if kind == "placeholder" or (
        not any(document[k] for k in ("equipment", "openings", "shafts", "ifcModels"))
        and not (with_plumbing or with_hvac or with_electrical or with_fire)
    ):
        step.message = "There is nothing to check in 07 MEP."
        return None
    texts = project.texts(S.MEP_SOURCE_PARTS)
    root = str(project.root)
    handlers = _handlers()
    raw = handlers.mep_report(root, None, text)
    _problems_only(raw, ("equipment", "openings", "clashes"))
    if not isinstance(raw, dict):
        raise StepFailure("The MEP coordination checks are not available.")
    checked: dict[str, Any] = {"mep": raw}
    if with_plumbing:
        plumbing = handlers.plumbing_report(root, text)
        _problems_only(plumbing, ("demand", "checks"))
        if not isinstance(plumbing, dict):
            raise StepFailure("The plumbing checks are not available.")
        checked["plumbing"] = plumbing
    if with_hvac:
        hvac = handlers.hvac_report(root, text)
        _problems_only(hvac, ("zones", "air"))
        if not isinstance(hvac, dict):
            raise StepFailure("The HVAC checks are not available.")
        checked["hvac"] = hvac
    if with_electrical:
        electrical = handlers.electrical_report(root, text)
        _problems_only(electrical, ("demand", "checks"))
        if not isinstance(electrical, dict):
            raise StepFailure("The electrical checks are not available.")
        checked["electrical"] = electrical
    if with_fire:
        fire = handlers.fire_report(root, text)
        _problems_only(fire, ("requirements", "checks"))
        if not isinstance(fire, dict):
            raise StepFailure("The fire checks are not available.")
        checked["fire"] = fire
    file = S.mep_summary_file(document, raw, text, texts)
    if "plumbing" in checked:
        file["plumbing"] = S.plumbing_summary_file(document, checked["plumbing"])
    if "hvac" in checked:
        file["hvac"] = S.hvac_summary_file(document, checked["hvac"])
    if "electrical" in checked:
        file["electrical"] = S.electrical_summary_file(document, checked["electrical"])
    if "fire" in checked:
        file["fire"] = fire_summary_file(document, checked["fire"])
    target = resource.parent / S.MEP_SUMMARY_FILE
    write_text(target, S.summary_text(file))
    step.outputs.append(_relative(project, target))
    step.status = "ok"
    counts: dict[str, Any] = {
        "openingsFailed": file["openingsFailed"],
        "openingsPartial": file["openingsPartial"],
        "clashesOpen": file["clashesOpen"],
    }
    parts = [f"MEP: failing openings {file['openingsFailed']}, open clashes {file['clashesOpen']}"]
    if "plumbing" in checked:
        failures = S.plumbing_failures(checked["plumbing"])
        counts["plumbingFailed"] = failures["items"]
        counts["floorsLow"] = failures["floorsLow"]
        parts.append(
            f"plumbing: failing checks {failures['items']}, floors below the minimum pressure "
            f"{failures['floorsLow']}"
        )
    if "hvac" in checked:
        hvac = checked["hvac"]
        missing = S.openings_to_add(S.record(hvac.get("air")))
        counts["hvacFailed"] = S.hvac_failures(hvac)
        counts["hvacOpeningsToAdd"] = missing
        counts["hvacLoadsCalculated"] = S.hvac_calculated(hvac) is not False
        line = f"HVAC: failing checks {counts['hvacFailed']}, openings to add {missing}"
        if S.hvac_calculated(hvac) is False:
            line += ", loads not calculated: run Calculate Loads"
        parts.append(line)
    if "electrical" in checked:
        missing = S.openings_to_add(checked["electrical"])
        counts["electricalFailed"] = S.electrical_failures(checked["electrical"])
        counts["electricalOpeningsToAdd"] = missing
        parts.append(
            f"electrical: failing checks {counts['electricalFailed']}, openings to add {missing}"
        )
    if "fire" in checked:
        missing = S.openings_to_add(checked["fire"])
        counts["fireFailed"] = fire_failures(checked["fire"])
        counts["fireOpeningsToAdd"] = missing
        parts.append(f"fire: failing checks {counts['fireFailed']}, sleeves to add {missing}")
    step.counts = counts
    step.message = " · ".join(parts)
    return checked


# ─────────────────────────────── 7: BOQ ───────────────────────────────


def parse_boq(text: str | None) -> dict[str, Any] | None:
    """``parseBoq``: the bill when it is a measured one."""
    try:
        value = json.loads(text) if text is not None else None
    except ValueError:
        return None
    if (
        isinstance(value, dict)
        and value.get("schema") == "saengine.boq/1"
        and isinstance(value.get("items"), list)
    ):
        return value
    return None


def changed_boq_sources(document: dict[str, Any] | None, texts: dict[str, str | None]) -> list[str]:
    """``changedSources``: the source parts whose text differs from the one the bill was
    measured from."""
    changed = []
    for part, _, required, optional in BOQ_SOURCES:
        recorded = recorded_stamp(document, part)
        if optional and recorded is None:
            continue
        text = texts.get(part)
        if text is None:
            if required or recorded is not None:
                changed.append(part)
        elif recorded != boq_source_stamp(part, text):
            changed.append(part)
    return changed


def awaits_tank_designs(document: dict[str, Any] | None) -> bool:
    notes = document.get("notes") if document else None
    return isinstance(notes, list) and any(
        isinstance(n, str) and TANK_BARS_PENDING in n for n in notes
    )


def _write_like_text_model(path: Path, text: str) -> None:
    """Writes ``text`` as the bill's editor saves it: the text model keeps the file's line
    endings (CRLF when it has more of them; for a file without line breaks, the platform's) and
    its UTF-8 BOM."""
    data = path.read_bytes() if path.exists() else b""
    bom = data.startswith(b"\xef\xbb\xbf")
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    eol = "\r\n" if (crlf > lf if (crlf or lf) else os.name == "nt") else "\n"
    normalised = text.replace("\r\n", "\n")
    if eol == "\r\n":
        normalised = normalised.replace("\n", "\r\n")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + normalised.encode("utf-8"))


def _boq(project: Project, step: StepResult, tanks_designed: bool) -> bool:
    resource = project.file("boq")
    texts = project.texts([part for part, *_ in BOQ_SOURCES])
    current_text = read_text(resource)
    if current_text is None:
        raise StepFailure(f"The bill of quantities could not be read: {resource} does not exist.")
    current = parse_boq(current_text)
    changed = changed_boq_sources(current, texts)
    if not changed and not (tanks_designed and awaits_tank_designs(current)):
        step.message = "BOQ up to date"
        return False
    missing = [
        label for part, label, required, _ in BOQ_SOURCES if required and texts.get(part) is None
    ]
    if missing:
        raise StepFailure(f"{', '.join(missing)} could not be read.")
    result = _handlers().compute_boq(
        texts["bim"],
        texts["objects"],
        texts["materials"],
        texts.get("substructure"),
        texts.get("settings"),
        texts.get("mep"),
        str(project.root),
    )
    if not isinstance(result, dict) or not result.get("text"):
        problems = (result or {}).get("problems") or []
        raise StepFailure("; ".join(problems) or "The bill could not be measured.")
    _write_like_text_model(resource, result["text"])
    step.outputs.append(_relative(project, resource))
    step.status = "ok"
    step.counts = {"changed": changed, "items": len(json.loads(result["text"]).get("items", []))}
    step.message = "BOQ updated"
    return True


# ─────────────────────────────── 8: report ───────────────────────────────


def _report(project: Project, step: StepResult) -> Path:
    result = _handlers().build_report(str(project.root))
    if not isinstance(result, dict):
        raise StepFailure("The report builder returned no result.")
    if result.get("problems"):
        raise StepFailure(" ".join(map(str, result["problems"])))
    if not isinstance(result.get("path"), str) or not result["path"]:
        raise StepFailure("The report builder did not say where it wrote the report.")
    path = Path(result["path"])
    step.outputs.append(_relative(project, path))
    step.status = "ok"
    step.counts = {"pages": result.get("pages"), "warnings": len(result.get("warnings") or [])}
    step.message = "report written"
    return path


# ─────────────────────────────── 9: drawings ───────────────────────────────


def _drawings(
    project: Project, step: StepResult, design_report: dict[str, Any] | None, asked: bool
) -> None:
    from saengine.pipeline.drawings import DrawingsError, generate, list_drawings

    if project.type != "building":
        step.message = "no drawings: a special structure has no building model"
        return
    current = list_drawings(project.root)
    if not asked and not current["sheets"]:
        step.message = "drawings not generated yet (11 Exports, Drawings; or --steps drawings)"
        return
    if not asked and not current["stale"]:
        step.message = "drawings up to date"
        return
    try:
        answer = generate(project.root, design_report=design_report)
    except DrawingsError as error:
        raise StepFailure(str(error)) from error
    for sheet in answer["sheets"]:
        if sheet.get("dxf"):
            step.outputs.append(_relative(project, Path(sheet["dxf"])))
    if answer.get("pdf"):
        step.outputs.append(_relative(project, Path(answer["pdf"])))
    step.status = "ok"
    step.counts = {
        "sheets": len(answer["sheets"]),
        "bbsKg": (answer.get("bbs") or {}).get("total"),
        "warnings": len(answer.get("problems") or []),
    }
    errors = [
        p
        for p in answer.get("problems") or []
        if isinstance(p, dict) and p.get("severity") == "error"
    ]
    step.counts["toResolve"] = len(errors)
    step.message = f"{len(answer['sheets'])} drawing sheets"
    if errors:
        step.message += f" ({len(errors)} check(s) to resolve before issue)"


# ─────────────────────────────── the run ───────────────────────────────


def _summary(result: list[StepResult]) -> str:
    """The app's one line: "Done: 13 pass, 3 fail · foundations … · BOQ updated · report
    written", or, when a step failed, which one, why, and how many steps were not run."""
    by_id = {s.id: s for s in result}
    parts = []
    for step_id in ("design", "substructure", "mep"):
        step = by_id.get(step_id)
        if step and step.status in ("ok", "warning"):
            parts.append(step.message)
    derive = by_id.get("derive")
    if derive and derive.status in ("ok", "warning"):
        parts.append("model derived")
    boq = by_id.get("boq")
    if boq and boq.status in ("ok", "skipped") and boq.message:
        parts.append(boq.message)
    report = by_id.get("report")
    if report and report.status in ("ok", "warning"):
        parts.append("report written")
    drawings = by_id.get("drawings")
    if drawings and drawings.status in ("ok", "warning"):
        parts.append(drawings.message)
    failed = [s for s in result if s.status in ("failed", "error")]
    if failed:
        not_run = sum(1 for s in result if s.status == "notRun")
        first = failed[0]
        line = (
            f"Run All failed at step {STEP_IDS.index(first.id) + 1} of {len(STEP_IDS)} "
            f"({first.label}): {first.message}"
        )
        if len(failed) > 1:
            line += f" (and {len(failed) - 1} more step(s) failed)"
        if not_run:
            line += f"; {not_run} step(s) not run"
        return line + (". Done: " + " · ".join(parts) if parts else ".")
    return "Done: " + " · ".join(parts) if parts else "Done."


def normalise_steps(steps: Iterable[str] | None) -> list[str]:
    """The steps asked for, in Run All's order; ``ValueError`` for an unknown one."""
    if steps is None:
        return list(STEP_IDS)
    wanted = {s.strip() for item in steps for s in item.split(",") if s.strip()}
    unknown = sorted(wanted - set(STEP_IDS))
    if unknown:
        raise ValueError(
            f"unknown step(s): {', '.join(unknown)} (the steps: {', '.join(STEP_IDS)})"
        )
    return [s for s in STEP_IDS if s in wanted]


#: The summary each step writes, removed when the step fails: the part list must not show the
#: previous run's verdict as the current one (G1).
STEP_SUMMARIES = {
    "design": ("fem", f"model.results/{S.DESIGN_SUMMARY_FILE}"),
    "substructure": ("substructure", S.SUBSTRUCTURE_SUMMARY_FILE),
    "mep": ("mep", S.MEP_SUMMARY_FILE),
}


def _remove_summary(project: Project, step_id: str) -> None:
    if step_id not in STEP_SUMMARIES:
        return
    part, relative = STEP_SUMMARIES[step_id]
    with contextlib.suppress(OSError):
        (project.file(part).parent / relative).unlink(missing_ok=True)


def run_all(
    root: str | Path | Project,
    steps: Iterable[str] | None = None,
    progress: Progress | None = None,
) -> RunAllResult:
    """Run All on the project at ``root`` (its folder or ``.saengine`` file): ``steps`` (ids of
    :data:`STEP_IDS`; default all) in Run All's order. ``progress`` is called at the start of
    each step and with the solver's progress. A step that cannot be done fails; the steps that
    need it (:data:`STEP_NEEDS`) are ``notRun``, the others still run, as in the app."""
    project = root if isinstance(root, Project) else open_project(root)
    # The project's own code packs (02 Project Settings/code-packs) are found while it runs.
    with code_context.project(project.root):
        return _run_all(project, steps, progress)


def _run_all(
    project: Project, steps: Iterable[str] | None, progress: Progress | None
) -> RunAllResult:
    wanted = normalise_steps(steps)
    # The drawings are drawn when asked for by name, else only to keep a generated set current.
    drawings_asked = steps is not None and "drawings" in wanted
    # The minimum foundation bars are written only by the whole Run All (not by ``check``).
    add_bars = steps is None
    results = [StepResult(step_id) for step_id in wanted]
    blocked: dict[str, str] = {}  # step id -> the failed step it waits for
    tanks_designed = False
    design_report: dict[str, Any] | None = None
    for index, step in enumerate(results):
        waits = next((blocked[n] for n in STEP_NEEDS[step.id] if n in blocked), None)
        if waits is not None:
            step.status = "notRun"
            step.message = f"Not run: it needs the {STEP_LABELS[waits]} step, which failed."
            blocked[step.id] = waits
            continue

        def report(message: str | None, step=step, index=index) -> None:
            if progress:
                progress(step.id, index, len(results), message)

        report(None)
        started = time.monotonic()
        try:
            match step.id:
                case "bim":
                    _bim(project, step)
                case "derive":
                    _derive(project, step)
                case "analysis":
                    _analysis(project, step, report)
                case "ssi":
                    _ssi(project, step)
                case "design":
                    design_report = _design(project, step)
                case "substructure":
                    _substructure(project, step, add_bars)
                case "mep":
                    checked = _mep(project, step)
                    tanks_designed = bool(checked and "plumbing" in checked)
                case "boq":
                    _boq(project, step, tanks_designed)
                case "report":
                    _report(project, step)
                case "drawings":
                    _drawings(project, step, design_report, drawings_asked)
        except StepFailure as failure:
            step.status = "failed"
            step.message = str(failure) or "failed"
        except Exception as error:  # noqa: BLE001 - reported as the step's error
            step.status = "error"
            step.message = f"{type(error).__name__}: {error}"
        if step.status in ("failed", "error"):
            blocked[step.id] = step.id
            _remove_summary(project, step.id)
        step.seconds = time.monotonic() - started
    failed = next((s.id for s in results if s.status in ("failed", "error")), None)
    return RunAllResult(project, results, part_statuses(project), failed, _summary(results))

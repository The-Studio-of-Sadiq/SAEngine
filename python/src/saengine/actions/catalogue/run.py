"""Run actions: Run All and its steps (:func:`saengine.pipeline.run_all.run_all`), Design
Reinforcement (the design proposal of :mod:`saengine.design.proposal`, applied as the app's
Apply does; never automatic: only this action applies it) and the exports
(:mod:`saengine.pipeline.exports`, the project archive). They work on the saved project."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from saengine.actions.catalogue._util import Params
from saengine.actions.errors import refuse
from saengine.actions.paths import BIM, FLOOR_PLAN, OBJECTS
from saengine.actions.registry import action
from saengine.actions.result import ActionResult
from saengine.actions.view import ProjectView


def current_should_stop() -> Any:
    from saengine.actions.run import current_should_stop as current

    return current()


def _project(view: ProjectView) -> Any:
    from saengine.pipeline.project import ProjectError, open_project

    try:
        return open_project(view.root)
    except ProjectError as error:
        refuse(f"{error}: create or save the project first.")
        raise


def _ran(result: Any, strict: bool) -> ActionResult:
    steps = [s.to_json() for s in result.steps]
    bad = [s for s in result.steps if s.status in ("failed", "error")]
    warnings = [f"{s.label}: {s.message}" for s in bad]
    warnings += [f"{s.label}: {s.message}" for s in result.steps if s.status == "warning"]
    data = {
        "summary": result.summary,
        "stoppedAt": result.stopped_at,
        "cancelled": result.cancelled,
        "steps": steps,
        "parts": [p.to_json() for p in result.parts],
    }
    if result.cancelled:
        return ActionResult(ok=False, message=result.summary, warnings=warnings, data=data)
    if bad and strict:
        return ActionResult(
            ok=False,
            message=f"{result.summary} Failed: " + "; ".join(warnings[: len(bad)]),
            warnings=warnings,
            data=data,
        )
    return ActionResult(message=result.summary or "Done.", warnings=warnings, data=data)


class RunAllParams(Params):
    strict: bool = Field(
        default=False,
        description="Fail the action when a step fails (else the failed steps are warnings and "
        "the batch goes on, as the app's Run All reports them).",
    )


@action(
    "run.all",
    summary="Run All: building model, analysis model, analysis, foundations, design checks, MEP, "
    "bill of quantities, report and drawings, as the app's Run All.",
    params=RunAllParams,
    parts=("bim", "fem", "substructure", "boq", "exports"),
    kind="run",
    example={},
)
def run_all_action(view: ProjectView, p: RunAllParams) -> ActionResult:
    from saengine.pipeline.run_all import run_all

    return _ran(run_all(_project(view), should_stop=current_should_stop()), p.strict)


#: The steps of each part of Run All (as ``saengine derive|analyse|design|report``).
STEPS: dict[str, tuple[str, ...]] = {
    "derive": ("bim", "derive"),
    "analyse": ("bim", "derive", "analysis", "ssi"),
    "design": ("design", "substructure"),
    "substructure": ("substructure",),
    "boq": ("bim", "boq"),
    "report": ("report",),
    "drawings": ("drawings",),
}


class StepParams(Params):
    step: Literal["derive", "analyse", "design", "substructure", "boq", "report", "drawings"]
    strict: bool = Field(default=True, description="Fail the action when a step fails.")


@action(
    "run.step",
    summary="Run part of Run All: derive (the analysis model), analyse, design (members and "
    "foundations), substructure, boq, report or drawings.",
    params=StepParams,
    parts=("bim", "fem", "substructure", "boq", "exports"),
    kind="run",
    example={"step": "analyse"},
)
def run_step(view: ProjectView, p: StepParams) -> ActionResult:
    from saengine.pipeline.run_all import run_all

    return _ran(
        run_all(_project(view), steps=STEPS[p.step], should_stop=current_should_stop()), p.strict
    )


class ReinforceParams(Params):
    types: Literal["all"] | list[str] = Field(
        default="all", description='Object type ids to give the proposed bars, or "all".'
    )
    members: list[str] | None = Field(
        default=None, description="Or: the types of these members (ids)."
    )
    mode: Literal["byType", "splitTypes"] = Field(
        default="byType",
        description="byType: one set of bars per type; splitTypes: members much lighter than "
        "their type's governing one get new types.",
    )


@action(
    "design.reinforcement.apply",
    summary="Design Reinforcement: propose bars for the object types from the analysis and "
    "apply them (all types, or those given); needs the analysis results. Never automatic.",
    params=ReinforceParams,
    parts=("objects", "bim", "floorPlan"),
    kind="run",
    example={"types": "all"},
)
def design_reinforcement_apply(view: ProjectView, p: ReinforceParams) -> ActionResult:
    from saengine.actions.view import json_text
    from saengine.codes import context as code_context
    from saengine.pipeline.run_all import results_folder
    from saengine.rpc.handlers import design_apply_proposal, design_proposal

    project = _project(view)
    model = project.file("fem")
    if not (results_folder(model)).is_dir():
        refuse(
            "There are no analysis results: run the analysis first (run.step analyse or run.all)."
        )
    with code_context.project(project.root):
        try:
            proposal = design_proposal(str(results_folder(model)), str(model), {"mode": p.mode})
        except (ValueError, OSError) as error:
            refuse(f"The bars could not be proposed: {error}")
            raise
    wanted: set[str] | None = None
    if p.members:
        from saengine.actions.catalogue import _plan as P

        plan = view.read(FLOOR_PLAN)
        wanted = {P.find_member(plan, m)[1]["type"] for m in p.members}
    elif p.types != "all":
        wanted = set(p.types)
    entries = list(proposal.get("types") or [])
    if wanted is not None:
        known = {e.get("type") for e in entries}
        unknown = sorted(wanted - known)
        if unknown:
            refuse(
                f"No bars are proposed for {', '.join(unknown)} (the designed types: "
                f"{', '.join(sorted(map(str, known)))}).",
                "types",
                unknown,
            )
        for e in entries:
            if e.get("type") not in wanted:
                e["apply"] = False
        for n in proposal.get("newTypes") or []:
            if n.get("from") not in wanted:
                n["apply"] = False
    objects = view.read(OBJECTS)
    bim = view.read(BIM, None)
    plan = view.read(FLOOR_PLAN, None)
    try:
        applied = design_apply_proposal(
            json_text(objects),
            json_text(bim) if bim is not None else None,
            proposal,
            json_text(plan) if plan is not None else None,
        )
    except ValueError as error:
        refuse(f"The proposal could not be applied: {error}")
        raise
    import json

    view.put(OBJECTS, json.loads(applied["objectsText"]))
    if applied.get("bimText"):
        view.put(BIM, json.loads(applied["bimText"]))
    if applied.get("floorPlanText"):
        view.put(FLOOR_PLAN, json.loads(applied["floorPlanText"]))
    changes = applied.get("changes") or []
    small = [
        e.get("type")
        for e in entries
        if e.get("status") == "tooSmall" and e.get("apply") is not False
    ]
    warnings = [str(w) for w in proposal.get("warnings") or []]
    if small:
        warnings.append(f"Too small for any bars (make them bigger): {', '.join(map(str, small))}")
    applied_types = sorted({str(c.get("id")) for c in changes if "objects" in str(c.get("file"))})
    return ActionResult(
        message=f"Bars applied to {len(applied_types)} types"
        + (f": {', '.join(applied_types)}" if applied_types else "")
        + ". Run the design again (run.step design) to check them.",
        created=[
            str(n.get("type") or n.get("id"))
            for n in proposal.get("newTypes") or []
            if n.get("apply") is not False
        ],
        warnings=warnings,
        data={"changes": changes},
    )


# ── exports ──


class ExportParams(Params):
    out: str | None = Field(
        default=None, description="Where to write (a file or folder); default: 11 Exports."
    )


def _export(view: ProjectView, fmt: str, out: str | None, **options: Any) -> ActionResult:
    from saengine.pipeline.exports import ExportError, export

    project = _project(view)
    try:
        written = export(project, fmt, Path(out) if out else None, **options)
    except (ExportError, ValueError, OSError) as error:
        refuse(f"The export could not be written: {error}")
        raise
    files = [str(p) for p in written]
    return ActionResult(message=f"Wrote {len(files)} file(s).", data={"files": files})


class DrawingsParams(ExportParams):
    size: Literal["A0", "A1", "A2", "A3", "ANSI D", "ARCH D"] | None = Field(
        default=None, description="Sheet size; default: Project Settings' drawings."
    )


@action(
    "export.drawings",
    summary="Generate the structural drawings (sheets as DXF and a PDF set) into 11 Exports.",
    params=DrawingsParams,
    parts=("exports",),
    kind="run",
    example={"size": "A1"},
)
def export_drawings(view: ProjectView, p: DrawingsParams) -> ActionResult:
    return _export(view, "drawings", p.out, size=p.size)


class ReportParams(ExportParams):
    format: Literal["pdf", "docx"] = "pdf"
    template: str | None = Field(default=None, description="Report template id.")


@action(
    "export.report",
    summary="Write the design report (PDF or Word) into 11 Exports.",
    params=ReportParams,
    parts=("exports",),
    kind="run",
    example={"format": "pdf"},
)
def export_report(view: ProjectView, p: ReportParams) -> ActionResult:
    return _export(view, p.format, p.out, template=p.template)


@action(
    "export.ifc",
    summary="Write the building model as IFC into 11 Exports.",
    params=ExportParams,
    parts=("exports",),
    kind="run",
    example={},
)
def export_ifc(view: ProjectView, p: ExportParams) -> ActionResult:
    return _export(view, "ifc", p.out)


class BoqParams(ExportParams):
    format: Literal["xlsx", "csv"] = "xlsx"


@action(
    "export.boq",
    summary="Write the bill of quantities (Excel or CSV) into 11 Exports.",
    params=BoqParams,
    parts=("exports",),
    kind="run",
    example={"format": "xlsx"},
)
def export_boq(view: ProjectView, p: BoqParams) -> ActionResult:
    return _export(view, p.format, p.out)


class ArchiveParams(ExportParams):
    includeResults: bool = Field(default=False, description="Also archive the computed results.")
    includeVersions: bool = Field(default=False, description="Also archive the version history.")


@action(
    "export.archive",
    summary="Archive the project as a .civil file (default: beside the project folder).",
    params=ArchiveParams,
    parts=(),
    kind="run",
    example={},
)
def export_archive(view: ProjectView, p: ArchiveParams) -> ActionResult:
    from saengine.pipeline.status import part_statuses
    from saengine.project.archive import ArchiveError, export_project, safe_name

    project = _project(view)
    name = f"{safe_name(project.name)}.civil"
    target = Path(p.out) if p.out else project.root.parent / name
    if target.is_dir():
        target = target / name
    statuses = {s.part: s.to_json() for s in part_statuses(project)}
    try:
        result = export_project(
            project.root,
            target,
            include_results=p.includeResults,
            include_versions=p.includeVersions,
            statuses=statuses,
        )
    except (ArchiveError, OSError) as error:
        refuse(f"The archive could not be written: {error}")
        raise
    return ActionResult(
        message=f"Wrote {result['path']} ({result['files']} files).",
        data={"files": [str(result["path"])], "archive": result},
    )

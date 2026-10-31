"""The drawings of ``11 Exports/Drawings`` (structural, and architectural when there is an
architecture): generating them and telling whether they
are current. The glue between the project and the drawing streams:
:func:`saengine.drawings.detailing.detailing_model` (bars, laps, marks),
:mod:`saengine.drawings.bbs` (the bar bending schedule) and :mod:`saengine.drawings.sheets` (the
DXF sheets, the PDF set and the PNG previews).

What a generation writes into ``11 Exports/Drawings``:

- one DXF per sheet (``S-101 General notes.dxf``, ..., then ``A-101 Architectural plan -
  Base.dxf``, ... when ``05 Floor Plan/architecture.json`` has walls), for AutoCAD, BricsCAD
  or LibreCAD;
- ``drawings.pdf``: every sheet, one page each; ``previews/S-101.png``, ...: the previews;
- ``bbs.csv``: the bar bending schedule (UTF-8 with a byte order mark, for Excel);
- ``rebar-congestion.csv``: the bar congestion checks of the beams, columns and their joints
  (:mod:`saengine.drawings.cages`); the failing ones are among the answer's warnings;
- ``drawings.json``: this module's record of the set: its sheets, the drawing settings it was
  drawn with, and the stamps of the files it was drawn from (whole set and per sheet), so that
  :func:`list_drawings` can tell when the model, the settings or the analysis changed since. The
  marks of the detailing model are kept too: a later generation keeps the bar marks.
- ``.sheet-index/``: what SAEngine drew on each sheet, so that the engineer's own additions to a
  sheet's DXF are kept when it is drawn again (:mod:`saengine.drawings.sheets.revisions`);
- after an issue (:func:`issue`): ``Issued/<rev> <date>/`` (the issued DXFs, PDF set, DWGs and
  register), ``register.json``, ``register.csv``, ``register.pdf``; the sheets changed since
  their last issue carry revision clouds of the pending revision. ``DWG/``: the sheets as DWG
  (:func:`export_dwg`, with LibreDWG's ``dxf2dwg`` run as a separate program).

Staleness: the stamps (:func:`saengine.library.bim.source_stamp`) of Project Settings,
Materials, Object Types, the floor plan, the architecture, the building model and the
substructure, and of the
analysis results' manifest when the design checks were used. Any change of one makes the
sheets drawn before it out of date. Generating some sheets only rewrites their DXF and preview
(and their stamps); the PDF set is then older than those sheets until the whole set is drawn.

Calls (also the RPC methods ``drawings/generate``, ``drawings/list``, ``drawings/progress``,
``drawings/issue`` and ``drawings/dwg``):

- :func:`generate` ``(project_root, sheets=None, size=None, design_report=None, progress=None)``
  -> the answer the Exports page reads (``{sheets, pdf, bbsCsv, generatedAt, size, stale,
  notes, problems}``, absolute paths);
- :func:`list_drawings` ``(project_root)`` -> the same for the last generation, with ``stale``,
  ``staleReason`` and ``changed`` (cheap: it reads the record and stamps the inputs);
- :func:`progress` ``(project_root)`` -> ``{running, step, index, count, message}``;
- :func:`issue` ``(project_root, code=None, date=None, description, by, purpose, sheets=None,
  force=False, dwg=False)`` -> the answer of :func:`generate` with ``issued`` (the issue);
- :func:`export_dwg` ``(project_root, sheets=None)`` -> ``{written, folder, problems}``.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from saengine.library.bim import source_stamp

SCHEMA_ID = "saengine.drawings/1"
FOLDER = "11 Exports/Drawings"
RECORD = "drawings.json"
BBS_CSV = "bbs.csv"
PDF = "drawings.pdf"
DWG_FOLDER = "DWG"
FEM_MODEL = "08 FEM/model.osmodel"
RESULTS_MANIFEST = "08 FEM/model.results/manifest.json"

#: The files the drawings are drawn from: (key, path in the project, label).
SOURCES: tuple[tuple[str, str, str], ...] = (
    ("settings", "02 Project Settings/project-settings.json", "Project Settings"),
    ("materials", "03 Materials/materials.json", "Materials"),
    ("objects", "04 Objects/objects.json", "Object Types"),
    ("floorPlan", "05 Floor Plan/floor-plan.json", "Floor Plan"),
    ("architecture", "05 Floor Plan/architecture.json", "Architecture"),
    ("bim", "06 BIM/bim.json", "Building Model"),
    ("substructure", "09 Substructure/substructure.json", "Substructure"),
)
RESULTS_LABEL = "Analysis results"

#: The steps of a generation, as :func:`progress` names them.
STEPS = (
    ("design", "design checks"),
    ("detailing", "reinforcement detailing"),
    ("bbs", "bar bending schedule"),
    ("sheets", "drawing the sheets"),
    ("files", "writing the DXF, PDF and previews"),
)

Progress = Callable[[str, int, int, str], None]


class DrawingsError(RuntimeError):
    """The drawings could not be generated: the problems."""


# ─────────────────────────────── progress and locks ───────────────────────────────

_GUARD = threading.Lock()
_RUNNING: dict[str, dict[str, Any]] = {}


def _key(root: Path) -> str:
    return os.path.normcase(os.path.abspath(root))


def progress(project_root: str | Path) -> dict[str, Any]:
    """Where the generation of the project at ``project_root`` is: ``{running: false}`` when
    none runs, else ``{running: true, step, index, count, message, seconds}``."""
    with _GUARD:
        state = _RUNNING.get(_key(Path(project_root)))
        if state is None:
            return {"running": False}
        return {**state, "running": True, "seconds": round(time.time() - state["started"], 1)}


# ─────────────────────────────────── stamps ───────────────────────────────────


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def input_stamps(root: Path) -> dict[str, str | None]:
    """The stamps of the files the drawings are drawn from, and of the analysis results'
    manifest (a new run: new design checks); None: the file is missing."""
    stamps: dict[str, str | None] = {}
    for key, relative, _ in SOURCES:
        text = _read(root / relative)
        stamps[key] = source_stamp(text) if text is not None else None
    text = _read(root / RESULTS_MANIFEST)
    stamps["results"] = source_stamp(text) if text is not None else None
    return stamps


def _labels() -> dict[str, str]:
    return {**{k: label for k, _, label in SOURCES}, "results": RESULTS_LABEL}


def changed_sources(recorded: dict[str, Any] | None, current: dict[str, str | None]) -> list[str]:
    """The labels of the sources whose stamp differs from ``recorded`` (in source order)."""
    recorded = recorded or {}
    labels = _labels()
    return [labels[k] for k in labels if k in recorded and recorded.get(k) != current.get(k)]


# ─────────────────────────────────── settings ───────────────────────────────────


def drawing_settings(settings_text: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(settings, title)``: the ``drawings`` section of Project Settings (its defaults when
    there is none) and the title block fields it gives (:class:`TitleInfo` keys)."""
    from saengine.library.settings import Drawings, ProjectSettings

    drawings = Drawings()
    project: dict[str, Any] = {}
    if settings_text:
        try:
            settings = ProjectSettings.model_validate_json(settings_text)
        except ValueError:
            # The sheets still draw; the title block then takes what is valid of the drawings
            # section, else the defaults. Project Settings shows the problem itself.
            try:
                raw = json.loads(settings_text)
            except ValueError:
                raw = {}
            raw = raw if isinstance(raw, dict) else {}
            try:
                drawings = Drawings.model_validate(raw.get("drawings") or {})
            except ValueError:
                drawings = Drawings()
            project = raw.get("project") if isinstance(raw.get("project"), dict) else {}
        else:
            drawings = settings.drawings
            project = settings.project.model_dump()
    revisions = [
        {"rev": r.code, "date": r.date or "", "description": r.description or "", "by": r.by or ""}
        for r in drawings.revisions
    ]
    title: dict[str, Any] = {
        "firm": drawings.firm,
        "engineer": drawings.engineer or project.get("engineer"),
        "drawn": drawings.drawnBy,
        "checked": drawings.checkedBy,
        "approved": drawings.approvedBy,
        "number": drawings.projectNumber or project.get("number"),
        "status": drawings.status,
        "revision": revisions[-1]["rev"] if revisions else "0",
        "revisions": revisions,
    }
    return drawings.model_dump(), {k: v for k, v in title.items() if v not in (None, "")}


def _sheet_settings(settings: dict[str, Any], size: str | None) -> dict[str, Any]:
    return {
        "size": (size or settings["sheetSize"]).upper(),
        "planScale": settings["planScale"],
        "slabScale": settings["slabScale"],
        "elevationScale": settings["elevationScale"],
        "detailScale": settings["detailScale"],
    }


# ─────────────────────────────────── the design ───────────────────────────────────


REQUIRED_MISSING = (
    "The required steel of the design is not worked out for this analysis run (Run All's design "
    "step or the Properties panel works it out): the continuous top bars of the beams follow the "
    "bars entered in 04 Objects only."
)


def _design_inputs(
    root: Path, need_report: bool = True, need_required: bool = True
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    """The design checks and the required steel of the project's last analysis run, when it
    has results: ``(design_report, required, notes)``.

    The design checks are those kept beside the results while they are current
    (:func:`saengine.pipeline.design_mode.report`: Run All's design step keeps them; else they
    are made once here, about a minute on the sample, and kept for the next generation). The
    required steel is only read when kept (working it out takes minutes): a note says when it
    is missing."""
    from saengine.pipeline import design_mode

    model = root / FEM_MODEL
    out = model.parent / f"{model.stem}.results"
    if not (out / "manifest.json").exists():
        return None, None, ["No analysis results: the frames are detailed from Project Settings."]
    notes: list[str] = []
    report = required = None
    if need_report:
        try:
            report = design_mode.report(out, model) or None
        except Exception as error:  # noqa: BLE001 - the sheets are drawn without the checks
            notes.append(f"The design checks could not be read ({error}): drawn without them.")
    if need_required:
        try:
            required = design_mode.kept(out, design_mode.inputs_stamp(out, model))
        except Exception:  # noqa: BLE001 - optional input
            required = None
        if required is None:
            notes.append(REQUIRED_MISSING)
    return report, required, notes


def kept_detailing_inputs(project_root: str | Path) -> dict[str, Any]:
    """What a generation would detail the bars with, read cheaply (nothing designed again):
    ``{design_report, required, previous}``: the kept design checks and required steel of the
    last analysis run while current, and the bar marks of the last drawing set. The bill's
    "reinforcement from the BBS" (:mod:`saengine.boq.schedule`) uses it so that its marks and
    bars are those of the sheets."""
    root = Path(project_root)
    from saengine.pipeline import design_mode

    model = root / FEM_MODEL
    out = model.parent / f"{model.stem}.results"
    report = required = None
    if (out / "manifest.json").exists():
        try:
            stamp = design_mode.inputs_stamp(out, model)
            report = design_mode.kept(out, stamp, design_mode.REPORT_FILE)
            required = design_mode.kept(out, stamp)
        except Exception:  # noqa: BLE001 - optional inputs
            report = required = None
    previous = (_record(root / FOLDER) or {}).get("marks")
    return {"design_report": report, "required": required, "previous": previous}


#: At most this many failing checks are written on the general notes sheet (all are listed in
#: the answer's problems).
SHEET_CHECKS = 8


def _number(value: Any) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def check_problems(model: dict[str, Any], design_report: dict[str, Any] | None) -> list[str]:
    """What must be resolved before the drawings are issued: every detailing check of the
    model that is not met (bars anchored or lapped too short) and the members failing the
    design checks of ``design_report``."""
    lines: list[str] = []
    for element in model.get("elements") or []:
        for check in element.get("checks") or []:
            if not isinstance(check, dict) or check.get("ok") is not False:
                continue
            unit = f" {check['unit']}" if check.get("unit") else ""
            clause = f", {check['clause']}" if check.get("clause") else ""
            lines.append(
                f"{element.get('id')}: {check.get('name')}: {_number(check.get('required'))}"
                f"{unit} needed, {_number(check.get('provided'))}{unit} provided{clause}: "
                "not met."
            )
    if design_report:
        members = [e for e in design_report.get("elements") or [] if isinstance(e, dict)]
        failed = [str(e.get("id")) for e in members if e.get("ok") is False]
        if failed:
            lines.append(
                f"Design checks: {len(failed)} of {len(members)} members fail ("
                f"{', '.join(failed)}): the sheets show the bars entered in 04 Objects."
            )
        joints = ((design_report.get("summary") or {}).get("joints") or {}).get("failed")
        if joints:
            lines.append(f"Design checks: {joints} beam-column joint(s) fail.")
    return lines


def _sheet_check_notes(problems: Sequence[str]) -> list[str]:
    """The general note that says the set is not ready to issue, with what fails."""
    if not problems:
        return []
    shown = list(problems[:SHEET_CHECKS])
    more = len(problems) - len(shown)
    tail = f" And {more} more (11 Exports, Drawings)." if more > 0 else ""
    return ["NOT FOR CONSTRUCTION until these are resolved: " + " ".join(shown) + tail]


# ─────────────────────────────────── generating ───────────────────────────────────


def _relative(folder: Path, path: str | Path | None) -> str | None:
    if not path:
        return None
    try:
        return Path(path).resolve().relative_to(folder.resolve()).as_posix()
    except ValueError:
        return str(path)


def _record(folder: Path) -> dict[str, Any] | None:
    text = _read(folder / RECORD)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("schema") == SCHEMA_ID else None


def _warning(message: str) -> dict[str, str]:
    return {"message": message, "severity": "warning"}


def _reconciliation(schedule: Any, root: Path) -> list[dict[str, Any]]:
    """The schedule against the bill of quantities (``10 BOQ/boq.json``), per bar size."""
    from saengine.drawings import bbs

    text = _read(root / "10 BOQ/boq.json")
    if not text:
        return []
    try:
        rec = bbs.reconcile(schedule, json.loads(text))
    except (ValueError, TypeError, KeyError):
        return []
    return [
        {
            "dia": r.dia,
            "bbs": round(r.bbs, 1),
            "boq": round(r.boq, 1),
            "difference": round(r.difference, 1),
            "percent": None if r.percent is None else round(r.percent, 1),
        }
        for r in rec.rows
    ]


def reconciliation_notes(rows: Sequence[dict[str, Any]]) -> list[str]:
    """One line per bar size: the schedule's and the bill's masses and the difference."""
    lines = []
    for r in rows:
        pct = "" if r.get("percent") is None else f", {r['percent']:+.1f} %"
        lines.append(
            f"Ø{r['dia']:g}: bar bending schedule {r['bbs']:.1f} kg, BOQ {r['boq']:.1f} kg "
            f"({r['difference']:+.1f} kg{pct})"
        )
    return lines


def generate(
    project_root: str | Path,
    sheets: Sequence[str] | None = None,
    size: str | None = None,
    *,
    design_report: dict[str, Any] | None = None,
    required: dict[str, Any] | None = None,
    use_design: bool = True,
    progress: Progress | None = None,
    issuing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generates the drawing set of the project at ``project_root`` into ``11 Exports/Drawings``
    (see the module notes) and returns the answer :func:`list_drawings` gives for it.

    ``sheets``: the sheet numbers to draw again (others are left as they are); all when empty.
    ``size``: A1, A2 or A3 over the drawing settings' sheet size. ``design_report`` and
    ``required``: the design checks and required steel (Run All passes those it just made);
    else, with ``use_design``, those of the last analysis run when there is one. ``progress``:
    called ``(step, index, count, message)`` as the steps start. ``issuing``: the issue being
    made (:func:`issue`; every sheet is drawn then).

    Raises :class:`DrawingsError` when nothing can be drawn (no building model, a generation of
    this project already running)."""
    root = Path(project_root)
    key = _key(root)
    with _GUARD:
        if key in _RUNNING:
            raise DrawingsError("The drawings of this project are being generated already.")
        _RUNNING[key] = {"step": "", "index": 0, "count": len(STEPS), "message": "",
                         "started": time.time()}  # fmt: skip
    try:
        return _generate(root, sheets, size, design_report, required, use_design, progress, issuing)
    finally:
        with _GUARD:
            _RUNNING.pop(key, None)


def _generate(
    root: Path,
    only: Sequence[str] | None,
    size: str | None,
    design_report: dict[str, Any] | None,
    required: dict[str, Any] | None,
    use_design: bool,
    report_progress: Progress | None,
    issuing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from saengine.drawings import bbs
    from saengine.drawings.detailing import detailing_model
    from saengine.drawings.sheets import DrawingSettings, build_sheets, drawing_set, write_drawings
    from saengine.drawings.sheets import revisions as rv

    def step(name: str) -> None:
        index = [s for s, _ in STEPS].index(name) + 1
        message = dict(STEPS)[name]
        with _GUARD:
            state = _RUNNING.get(_key(root))
            if state is not None:
                state.update(step=name, index=index, message=message)
        if report_progress is not None:
            report_progress(name, index, len(STEPS), message)

    folder = root / FOLDER
    if not (root / "06 BIM/bim.json").exists() or not (root / "04 Objects/objects.json").exists():
        raise DrawingsError(
            "The building model (06 BIM) and the object types (04 Objects) are needed for the "
            "drawings."
        )
    if size is not None and str(size).upper() not in ("A1", "A2", "A3"):
        raise DrawingsError(f"Sheet size {size!r}: A1, A2 or A3.")
    settings_text = _read(root / SOURCES[0][1])
    settings, title = drawing_settings(settings_text)
    notes: list[str] = []
    step("design")
    # Stamped before anything is read: an edit while the drawings are made leaves them stale.
    stamps = input_stamps(root)
    if use_design and (design_report is None or required is None):
        report, kept_required, design_notes = _design_inputs(
            root, need_report=design_report is None, need_required=required is None
        )
        design_report = design_report if design_report is not None else report
        required = required if required is not None else kept_required
        notes += design_notes
    earlier = _record(folder)
    step("detailing")
    try:
        model = detailing_model(
            root,
            design_report=design_report,
            required=required,
            options={"method": settings["developmentLength"], "curtail": settings["curtail"]},
            previous=(earlier or {}).get("marks"),
        )
    except ValueError as error:
        raise DrawingsError(f"The reinforcement could not be detailed: {error}") from error
    step("bbs")
    schedule = bbs.bar_schedule(model)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / BBS_CSV).write_text(bbs.schedule_csv(schedule), encoding="utf-8-sig", newline="")
    congestion = _congestion(root, model, folder)
    step("sheets")
    errors = check_problems(model, design_report)
    data = drawing_set(
        root,
        detailing=model,
        schedule=bbs.sheet_table(schedule),
        title=title,
        design_report=design_report,  # the steel connections' utilisation on their details
    )
    data.notes = [*data.notes, *_sheet_check_notes(errors)]
    sheet_size = _sheet_settings(settings, size)["size"]
    # Revisions: each sheet against its last issue (clouds, its revisions in the title block).
    register = rv.Register.load(folder)
    made: rv.Issue | None = None
    if issuing is not None:
        only = None  # an issue draws every sheet
        try:
            made = rv.new_issue(
                register,
                issuing.get("code"),
                issuing.get("date"),
                str(issuing.get("description") or ""),
                str(issuing.get("by") or data.title.drawn or ""),
                str(issuing.get("purpose") or ""),
                fallback=data.title.revision,
            )
        except rv.IssueError as error:
            raise DrawingsError(str(error)) from error
    reviser = rv.Reviser(
        folder,
        data.title,
        register,
        made,
        chosen=(issuing or {}).get("sheets") or None,
        force=bool((issuing or {}).get("force")),
    )
    all_sheets = build_sheets(
        data, DrawingSettings.from_dict(_sheet_settings(settings, size)), before_finish=reviser
    )
    if made is not None and not any(s.issued for s in reviser.states.values()):
        raise DrawingsError(
            "No sheet has changed since its last issue: nothing to issue (tick Issue every "
            "sheet to issue them again)."
        )
    page = {s.number: i + 1 for i, s in enumerate(all_sheets)}
    wanted = {s.strip() for s in (only or []) if s and s.strip()}
    # Some sheets are drawn again only into the same set: same size, same sheets (numbers and
    # titles). Else the set would mix two layouts; every sheet is drawn then.
    same_set = (
        earlier is not None
        and earlier.get("size") == sheet_size
        and [(r.get("number"), r.get("title")) for r in earlier.get("sheets") or []]
        == [(s.number, s.title) for s in all_sheets]
    )
    partial = bool(wanted) and same_set
    if wanted and earlier is not None and not same_set:
        why = (
            f"the sheet size changed from {earlier.get('size')} to {sheet_size}"
            if earlier.get("size") != sheet_size
            else "the sheets of the set changed"
        )
        notes.append(
            f"Every sheet was drawn again ({why}): drawing {', '.join(sorted(wanted))} alone "
            "would have mixed two layouts."
        )
    chosen = [s for s in all_sheets if s.number in wanted] if partial else all_sheets
    if partial and not chosen:
        raise DrawingsError(f"No sheet {', '.join(sorted(wanted))} in the drawing set.")
    step("files")
    # The engineer's own additions to the earlier DXFs are copied into the sheets drawn again;
    # the index of what SAEngine drew is taken first.
    earlier_rows = {
        str(r.get("number")): r for r in (earlier or {}).get("sheets") or [] if isinstance(r, dict)
    }
    indices = {}
    for sheet in chosen:
        indices[sheet.number] = rv.full_index(sheet, getattr(sheet, "content_index", None))
        row = earlier_rows.get(sheet.number)
        if row and row.get("dxf"):
            old_index = rv.SheetIndex.load(folder / rv.INDEX_FOLDER, sheet.number)
            carried = rv.carry_edits(sheet, folder / str(row["dxf"]), old_index)
            carried_note = carried.note(sheet.number)
            if carried_note:
                notes.append(carried_note)

    def sheet_progress(n: int, count: int) -> None:
        # In the polled progress (:func:`progress`) only: the callback has one call per step.
        with _GUARD:
            state = _RUNNING.get(_key(root))
            if state is not None:
                state.update(message=f"writing sheet {n} of {count}")

    def files_progress(message: str) -> None:
        # The PDF pages, assembling the PDF (minutes for a large set) and the previews.
        with _GUARD:
            state = _RUNNING.get(_key(root))
            if state is not None:
                state.update(message=message)

    written = write_drawings(
        chosen,
        folder,
        pdf=not partial,
        clean=not partial,
        ppi=60,
        pdf_name=PDF,
        problems=data.problems,
        on_sheet=sheet_progress,
        on_step=files_progress,
    )
    for index in indices.values():
        index.save(folder / rv.INDEX_FOLDER)
    notes += reviser.notes()
    revised = reviser.sheet_rows()
    issued = None
    if made is not None:
        by_number = {r["number"]: Path(r["dxf"]) for r in written["sheets"]}
        dwgs: dict[str, Path] = {}
        if (issuing or {}).get("dwg"):
            dwgs, dwg_problems = _write_dwgs(folder, by_number, set(by_number))
            notes.extend(dwg_problems)
        try:
            issued = rv.record_issue(
                folder, register, made, reviser, all_sheets, by_number, folder / PDF, dwgs
            )
        except rv.IssueError as error:
            raise DrawingsError(str(error)) from error
        notes.append(
            f"Issued revision {issued.code} ({issued.date}): {len(issued.sheets)} sheet(s) "
            f"into {FOLDER}/{issued.folder}."
        )
        for number in issued.numbers():
            revised[number] = {"revision": issued.code, "revised": False, "clouds": 0}
    conflicts = []
    for sheet in chosen:
        found = sheet.labels.conflicts() if hasattr(sheet, "labels") else []
        if found:
            conflicts.append(f"{sheet.number}: {len(found)} label(s) could not be placed clear")
    generated = datetime.now(UTC).isoformat(timespec="seconds")
    # The members that fail their design checks, flagged on the sheets that detail them.
    failing_ids = {
        str(e.get("id"))
        for e in (design_report or {}).get("elements", []) or []
        if isinstance(e, dict) and e.get("ok") is False
    }
    rows = {}
    for row in written["sheets"]:
        rows[row["number"]] = {
            "number": row["number"],
            "title": row["title"],
            "dxf": _relative(folder, row["dxf"]),
            "png": _relative(folder, row["png"]),
            "pdfPage": page.get(row["number"]),
            "size": row["size"],
            "scale": row["scale"],
            "source": stamps,
            "generatedAt": generated,
            "failing": sorted(failing_ids.intersection(row.get("members") or [])),
            **revised.get(row["number"], {}),
        }
    if partial:
        kept_rows = {s["number"]: s for s in earlier.get("sheets", []) if isinstance(s, dict)}
        # The sheets of the set as it is now; those not drawn again keep their earlier files.
        merged = []
        for sheet in all_sheets:
            if sheet.number in rows:
                merged.append(rows[sheet.number])
            elif sheet.number in kept_rows:
                merged.append({**kept_rows[sheet.number], "pdfPage": page[sheet.number]})
        sheet_rows = merged
        pdf = earlier.get("pdf")
        pdf_source = earlier.get("pdfSource")
        older = earlier.get("pdfSource") != stamps
        notes.append(
            f"Drawn again: {', '.join(rows)}. The PDF set was not written again"
            + (
                ": it has the earlier pages of these sheets; generate every sheet to bring it up "
                "to date."
                if older
                else " (its pages of these sheets were drawn from the same files)."
            )
        )
    else:
        sheet_rows = list(rows.values())
        pdf = _relative(folder, written.get("pdf"))
        pdf_source = stamps
    # The model's closing line says how it was detailed (a note); the rest are warnings. The
    # sheets repeat some of the model's notes in their problems: each is listed once.
    warnings: list[str] = []
    for text in [*(written.get("problems") or []), *(model.get("notes") or []), *congestion]:
        text = str(text)
        if text.startswith("Detailing to "):
            notes.append(text)
        elif text not in warnings:
            warnings.append(text)
    reconciliation = _reconciliation(schedule, root)
    record = {
        "schema": SCHEMA_ID,
        "generatedAt": generated,
        "size": sheet_size,
        "settings": settings,
        "source": stamps,
        "sheets": sheet_rows,
        "pdf": pdf,
        "pdfSource": pdf_source,
        "bbsCsv": BBS_CSV,
        "bbs": {
            "total": round(schedule.total, 1),
            "byDiameter": {f"{d:g}": round(m, 1) for d, m in schedule.by_diameter.items()},
            "rows": len(schedule.rows),
        },
        "reconciliation": reconciliation,
        "notes": [*notes, *schedule.notes, *conflicts],
        "warnings": warnings,
        "errors": errors,
        "marks": model.get("marks"),
        # Members without reinforcement: while there are any the title blocks read
        # NOT FOR CONSTRUCTION ({kind: {object type: count}}).
        "undesigned": data.undesigned,
        "status": data.title.status,
        "pendingRevision": register.pending_code(data.title.revision),
    }
    (folder / RECORD).write_text(
        json.dumps(record, indent="\t", ensure_ascii=False) + "\n", encoding="utf-8"
    )
    answer = _answer(root, record)
    if issued is not None:
        answer["issued"] = issued.to_json()
    return answer


# ─────────────────────────────────── listing ───────────────────────────────────


def _time_ms(text: Any) -> int | None:
    try:
        return int(datetime.fromisoformat(str(text)).timestamp() * 1000)
    except ValueError:
        return None


def _answer(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    """The answer of :func:`generate` and :func:`list_drawings` for ``record``."""
    folder = root / FOLDER

    def absolute(path: Any) -> str | None:
        if not path:
            return None
        full = folder / str(path)
        return str(full) if full.exists() else None

    current = input_stamps(root)
    sheets = []
    changed: list[str] = []
    missing = []
    for row in record.get("sheets") or []:
        differ = changed_sources(row.get("source"), current)
        for label in differ:
            if label not in changed:
                changed.append(label)
        dxf, png = absolute(row.get("dxf")), absolute(row.get("png"))
        if dxf is None:
            missing.append(str(row.get("number")))
        sheets.append(
            {
                "number": row.get("number"),
                "title": row.get("title"),
                "dxf": dxf,
                "png": png,
                "pdfPage": row.get("pdfPage"),
                "size": row.get("size"),
                "scale": row.get("scale"),
                "stale": bool(differ) or dxf is None,
                "generatedAt": _time_ms(row.get("generatedAt")),
                # Members on the sheet that failed their design checks when it was drawn.
                "failing": list(row.get("failing") or []),
                # The revision it was last issued at, and whether it changed since (clouded).
                "revision": row.get("revision"),
                "revised": bool(row.get("revised")),
                "clouds": int(row.get("clouds") or 0),
                "dwg": absolute(f"{DWG_FOLDER}/{Path(str(row.get('dxf'))).stem}.dwg")
                if row.get("dxf")
                else None,
            }
        )
    pdf_changed = changed_sources(record.get("pdfSource"), current)
    pdf_older = any(
        row.get("source") != record.get("pdfSource") or row.get("size") != record.get("size")
        for row in record.get("sheets") or []
    )
    notes = list(record.get("notes") or [])
    rec = record.get("reconciliation") or []
    if rec:
        notes.append("Bar bending schedule against 10 BOQ: " + "; ".join(reconciliation_notes(rec)))
    if missing:
        notes.append(f"The files of {', '.join(missing)} are missing: generate them again.")
    stale = any(s["stale"] for s in sheets) or bool(pdf_changed)
    reason = None
    if changed or pdf_changed:
        reason = "changed since: " + ", ".join(changed or pdf_changed)
    elif missing:
        reason = "files missing"
    # Failing checks are errors (the page lists them as problems to resolve before issue);
    # the rest are warnings.
    problems: list[Any] = [
        {"message": str(e), "severity": "error"} for e in record.get("errors") or []
    ]
    problems += [_warning(str(w)) for w in record.get("warnings") or []]
    return {
        "sheets": sheets,
        "failingSheets": sum(1 for s in sheets if s["failing"]),
        "pdf": absolute(record.get("pdf")),
        "pdfStale": bool(pdf_changed) or pdf_older,
        "bbsCsv": absolute(record.get("bbsCsv")),
        # The bar congestion checks of the cages (saengine.drawings.cages), when written.
        "congestionCsv": absolute("rebar-congestion.csv"),
        "generatedAt": _time_ms(record.get("generatedAt")),
        "size": record.get("size"),
        "stale": stale,
        "staleReason": reason,
        "changed": changed or pdf_changed,
        "bbs": record.get("bbs"),
        "reconciliation": rec,
        "notes": notes,
        "problems": problems,
        "register": _register_answer(folder, record),
    }


def _register_answer(folder: Path, record: dict[str, Any]) -> dict[str, Any]:
    """The issues of the set (oldest first) and the revision the next issue takes."""
    from saengine.drawings.sheets import revisions as rv

    register = rv.Register.load(folder)

    def absolute(name: str) -> str | None:
        return str(folder / name) if name and (folder / name).exists() else None

    return {
        "issues": [
            {
                "code": i.code,
                "date": i.date,
                "description": i.description,
                "purpose": i.purpose,
                "by": i.by,
                "sheets": [s.number for s in i.sheets],
                "folder": absolute(i.folder),
            }
            for i in register.issues
        ],
        "pending": record.get("pendingRevision") or register.pending_code("0"),
        "csv": absolute(rv.REGISTER_CSV),
        "pdf": absolute(rv.REGISTER_PDF),
    }


def _libraries(root: Path) -> tuple[Any, Any]:
    """The object types and materials of the project (materials None when unreadable)."""
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary

    objects = ObjectLibrary.model_validate_json(_read(root / "04 Objects/objects.json") or "{}")
    try:
        materials = MaterialLibrary.model_validate_json(
            _read(root / "03 Materials/materials.json") or ""
        )
    except ValueError:
        materials = None
    return objects, materials


def _congestion(root: Path, model: dict[str, Any], folder: Path) -> list[str]:
    """The bar congestion checks of the detailing ``model`` written as ``rebar-congestion.csv``;
    the failing ones as warnings (none when the cages cannot be built)."""
    from saengine.drawings import cages

    try:
        objects, materials = _libraries(root)
        found = cages.cage_model(model, objects, materials)
    except Exception as error:  # noqa: BLE001 - the drawings do not depend on it
        return [f"The bar congestion could not be checked: {error}"]
    (folder / cages.CSV_NAME).write_text(
        cages.congestion_csv(found), encoding="utf-8-sig", newline=""
    )
    return cages.congestion_problems(found)


def rebar_cages(project_root: str | Path, check: bool = True) -> dict[str, Any]:
    """The 3D reinforcement cages of the project's beams and columns with their congestion
    checks (:func:`saengine.drawings.cages.cage_model`), from the detailing the drawings use:
    the kept design checks and required steel of the last analysis run and the bar marks of the
    last drawing set (nothing is designed again). Raises :class:`DrawingsError` when the
    project cannot be detailed."""
    from saengine.drawings.cages import cage_model
    from saengine.drawings.detailing import detailing_model

    root = Path(project_root)
    if not (root / "06 BIM/bim.json").exists() or not (root / "04 Objects/objects.json").exists():
        raise DrawingsError("The building model (06 BIM) and the object types are needed.")
    settings, _ = drawing_settings(_read(root / SOURCES[0][1]))
    inputs = kept_detailing_inputs(root)
    try:
        model = detailing_model(
            root,
            design_report=inputs["design_report"],
            required=inputs["required"],
            options={"method": settings["developmentLength"], "curtail": settings["curtail"]},
            previous=inputs["previous"],
        )
    except ValueError as error:
        raise DrawingsError(f"The reinforcement could not be detailed: {error}") from error
    objects, materials = _libraries(root)
    return cage_model(model, objects, materials, check=check)


def list_drawings(project_root: str | Path) -> dict[str, Any]:
    """The drawing set of the last generation (see :func:`generate`), with what is out of date;
    ``{sheets: [], notes: [], problems: []}`` when none was generated."""
    root = Path(project_root)
    record = _record(root / FOLDER)
    if record is None:
        return {"sheets": [], "stale": False, "notes": [], "problems": []}
    return _answer(root, record)


# ─────────────────────────────────── issue and DWG ───────────────────────────────────


def issue(
    project_root: str | Path,
    code: str | None = None,
    date: str | None = None,
    description: str = "",
    by: str = "",
    purpose: str = "",
    sheets: Sequence[str] | None = None,
    *,
    force: bool = False,
    dwg: bool = False,
    design_report: dict[str, Any] | None = None,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Issues the drawing set: draws every sheet again with revision ``code`` (default: the
    one after the last issue) in the title block of each sheet of ``sheets`` (default: all)
    that is new or changed since its last issue (``force``: also the unchanged ones), copies
    them, the PDF set and the register into ``Issued/<code> <date>/`` (with DWGs when
    ``dwg``) and records the issue in the register. The answer is :func:`generate`'s with
    ``issued``. Raises :class:`DrawingsError` (nothing changed, the code issued already, ...)."""
    return generate(
        project_root,
        None,
        None,
        design_report=design_report,
        progress=progress,
        issuing={
            "code": code,
            "date": date,
            "description": description,
            "by": by,
            "purpose": purpose,
            "sheets": [s for s in sheets or [] if s] or None,
            "force": force,
            "dwg": dwg,
        },
    )


def _write_dwgs(
    folder: Path, dxfs: dict[str, Path], wanted: set[str]
) -> tuple[dict[str, Path], list[str]]:
    """The sheets' DXFs of ``wanted`` as DWG in ``DWG/``; what could not be written."""
    from saengine.library import dwg

    out: dict[str, Path] = {}
    problems: list[str] = []
    if dwg.find_writer() is None:
        return out, [
            (
                "No DWG was written: GNU LibreDWG's dxf2dwg (the setup's DWG component) is not "
                f"installed; add it with Help > Installer Components... or set {dwg.ENV_VAR}."
            )
        ]
    for number, dxf in dxfs.items():
        if number not in wanted:
            continue
        target = folder / DWG_FOLDER / f"{dxf.stem}.dwg"
        try:
            dwg.write_dwg(dxf, target)
            out[number] = target
        except dwg.DwgError as error:
            problems.append(f"{number}: {error}")
    return out, problems


def export_dwg(project_root: str | Path, sheets: Sequence[str] | None = None) -> dict[str, Any]:
    """Writes the current sheets (or those numbered in ``sheets``) as DWG into
    ``11 Exports/Drawings/DWG`` with LibreDWG's ``dxf2dwg`` (a separate program): ``{written:
    [{number, dwg}], folder, problems}``."""
    root = Path(project_root)
    folder = root / FOLDER
    record = _record(folder)
    if record is None:
        return {"written": [], "folder": None, "problems": ["Generate the drawings first."]}
    dxfs = {
        str(r.get("number")): folder / str(r.get("dxf"))
        for r in record.get("sheets") or []
        if isinstance(r, dict) and r.get("dxf")
    }
    wanted = {s for s in sheets or [] if s} or set(dxfs)
    missing = sorted(n for n in wanted if n in dxfs and not dxfs[n].is_file())
    present = {n: p for n, p in dxfs.items() if p.is_file()}
    written, problems = _write_dwgs(folder, present, wanted)
    if missing:
        problems.append(f"The DXF of {', '.join(missing)} is missing: generate it again.")
    return {
        "written": [{"number": n, "dwg": str(p)} for n, p in written.items()],
        "folder": str(folder / DWG_FOLDER),
        "problems": problems,
    }

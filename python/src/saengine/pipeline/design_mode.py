"""Design mode glue: the required reinforcement of a run, kept beside its results, and its
short tables for the printed report.

:func:`saengine.design.design_required` designs every member again (tens of seconds on a real
project). Its answer is kept in ``08 FEM/model.results/design-required.json`` with a stamp of
everything it was worked out from (the part files the design reads, the analysis model, the
result files, the options and the SAEngine version), so the Properties panel, Run All and the
report ask for it once per change of the project: :func:`required` returns the kept answer
while the stamp still matches and works it out again otherwise.

The design checks of a run (:func:`saengine.design.design_report`, about a minute on the
17-member sample) are kept the same way in ``design-report.json`` (:func:`report`), for the
drawings (``saengine.pipeline.drawings``) and Run All's design step.

Both come from one run of the design checks: :func:`gathered` keeps the last checks gathered in
the process (:func:`saengine.design.required.gather`, which also gives the design report) while
the stamp matches, so Run All's design step, its required steel, the report and the column
view (``saengine.fem.member_detail``) design the members once (:func:`checks`).
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import saengine
from saengine.fem.derive import model_stamp

#: The kept answer, in the results folder of the run.
REQUIRED_FILE = "design-required.json"
#: The kept design checks of the run (:func:`report`).
REPORT_FILE = "design-report.json"

#: What Run All keeps beside the results: the stamp of the model they were computed from
#: (``saengine.pipeline.run_all.ANALYSIS_INPUTS_FILE``).
ANALYSIS_INPUTS_FILE = "analysis-inputs.json"

#: Files of the results folder that are written from the results, not by the analysis: they do
#: not enter the stamp (writing them must not make the kept answer stale). The face forces
#: (``saengine.fem.end_zones.FACE_FORCES_FILE``) are written by the first design after a run,
#: after its stamp was taken; the column view's diagrams (``saengine.fem.member_detail.
#: CACHE_FILE``) when it is opened. Any other file counts, so an output of the analysis that is
#: new to this list makes the kept answers stale rather than wrongly current.
_DERIVED = frozenset(
    {
        REQUIRED_FILE,
        REPORT_FILE,
        "design-summary.json",
        "column-interaction.json",
        "face-forces.json",
        ANALYSIS_INPUTS_FILE,
    }
)
#: The same by path in the results folder: the response spectrum design's summary is written
#: again on every design (``saengine.fem.seismic_design.seismic_design`` keeps its run while
#: the model and the results do not change but rewrites the summary of it), so its time would
#: make every kept answer stale at once. The run it is made from is stamped. Its case file is
#: made from the model and the results, both stamped; a run that fails writes it again on
#: every design (on 25 storeys that made the design checks work everything out twice).
_DERIVED_PATHS = frozenset({"rs-design/seismic-design.json", "rs-design/rs-design.osmodel"})

#: The results' manifest, written by the solver at the end of a run.
RESULTS_MANIFEST = "manifest.json"
SETTINGS_FILE = "02 Project Settings/project-settings.json"


#: The part files the design checks and the foundation design read, relative to the project.
INPUT_FILES = (
    "01 Soil Report/soil-report.json",
    "02 Project Settings/project-settings.json",
    "03 Materials/materials.json",
    "04 Objects/objects.json",
    "06 BIM/bim.json",
    "09 Substructure/substructure.json",
)


def inputs_stamp(
    out_dir: str | Path, project_path: str | Path, options: dict[str, Any] | None = None
) -> str:
    """A hash of everything :func:`saengine.design.design_required` works from."""
    digest = hashlib.sha256()

    def add(*parts: object) -> None:
        for part in parts:
            digest.update(part if isinstance(part, bytes) else str(part).encode("utf-8"))
            digest.update(b"\0")

    add(saengine.__version__, json.dumps(options or {}, sort_keys=True, default=str))
    project_path = Path(project_path)
    root = project_path.resolve().parent.parent
    model = project_path.resolve().relative_to(root).as_posix()
    for relative in (*INPUT_FILES, model):
        try:
            data = (root / relative).read_bytes()
        except OSError:
            add(relative, "missing")
            continue
        # The settings without the project's details and title block, the model without its
        # meta (name and source stamps): typing the engineer's name, or deriving the same model
        # again, leaves the kept checks current (X28).
        if relative == SETTINGS_FILE:
            from saengine.fem.derive import settings_stamp

            add(relative, settings_stamp(data.decode("utf-8", errors="replace")))
        elif relative == model:
            add(relative, model_stamp(data))
        else:
            add(relative, data)
    out = Path(out_dir)
    if out.is_dir():
        for file in sorted(out.rglob("*")):
            relative = file.relative_to(out).as_posix()
            if (
                file.name in _DERIVED
                or relative in _DERIVED_PATHS
                or (file.name.startswith(".") and file.name.endswith(".tmp"))
                or not file.is_file()
            ):
                continue
            if relative == RESULTS_MANIFEST:
                # By content: Run All writes it again, unchanged, when it keeps the results of
                # a model derived again to the same analysis (``saengine.pipeline.run_all``).
                add(relative, file.read_bytes())
                continue
            stat = file.stat()
            add(relative, stat.st_size, stat.st_mtime_ns)
    return digest.hexdigest()


def kept(out_dir: str | Path, stamp: str, name: str = REQUIRED_FILE) -> dict[str, Any] | None:
    """The kept answer (``name``: :data:`REQUIRED_FILE` or :data:`REPORT_FILE`) when it was
    worked out from inputs with ``stamp``, else None."""
    try:
        data = json.loads((Path(out_dir) / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        isinstance(data, dict)
        and data.get("stamp") == stamp
        and isinstance(data.get("result"), dict)
    ):
        return data["result"]
    return None


def keep(
    out_dir: str | Path, stamp: str, result: dict[str, Any], name: str = REQUIRED_FILE
) -> None:
    """Writes the answer beside the results (whole or not at all; a failure is ignored).

    Each call writes its own temporary file (process, thread and a random part in the name), so
    two writers at once (the Properties panel's request and Run All's design step) never share
    one. On Windows the replace can still fail while another writer or a reader holds the
    target open; then this answer is simply not kept, and the cleanup never raises."""
    out = Path(out_dir)
    if not out.is_dir():
        return
    target = out / name
    unique = f"{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}"
    temporary = out / f".{name}.{unique}.tmp"
    data = {"stamp": stamp, "computed": datetime.now(UTC).isoformat(), "result": result}
    try:
        text = json.dumps(data, allow_nan=False, default=_finite)
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, target)
    except (OSError, ValueError, TypeError):
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _finite(value: Any) -> Any:
    raise TypeError(f"{type(value).__name__} is not JSON")


def _plain(value: Any) -> Any:
    """``value`` with infinite and NaN numbers as None (JSON has neither)."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    return value


def _ensure_seismic_design(out_dir: str | Path, project_path: str | Path) -> None:
    """The response spectrum design run (``<out_dir>/rs-design``) before the stamp is taken,
    so writing it does not make the kept answer stale right after
    (:func:`saengine.design.check.ensure_seismic_design`)."""
    from saengine.design.check import ensure_seismic_design
    from saengine.library.settings import ProjectSettings

    root = Path(project_path).resolve().parent.parent
    try:
        settings = ProjectSettings.model_validate_json(
            (root / "02 Project Settings/project-settings.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return
    ensure_seismic_design(out_dir, project_path, settings)


def required(
    out_dir: str | Path,
    project_path: str | Path,
    options: dict[str, Any] | None = None,
    *,
    fresh: bool = False,
) -> dict[str, Any]:
    """:func:`saengine.design.design_required` of the run, the kept answer while it is current
    (``fresh``: always work it out again). The stamp is taken before the design reads the
    files, so an edit while it runs makes the answer stale, never wrongly current."""
    from saengine.design import design_required

    _ensure_seismic_design(out_dir, project_path)
    stamp = inputs_stamp(out_dir, project_path, options)
    if not fresh:
        cached = kept(out_dir, stamp)
        if cached is not None:
            return cached
    gathering = gathered(out_dir, project_path, stamp)
    result = _plain(design_required(out_dir, project_path, options, gathering))
    keep(out_dir, stamp, result)
    return result


# ───────────────────────── the design checks, once per change ─────────────────────────

#: The checks gathered last in this process: (results folder, stamp, with the substructure,
#: the Gathered, a copy of its design report taken before anyone used it or None). One only: a
#: large building's gathered checks take hundreds of MB.
_GATHERED: tuple[str, str, bool, Any, dict[str, Any] | None] | None = None
#: The design report made last on its own (:func:`checks`): (results folder, stamp, report).
_REPORT: tuple[str, str, dict[str, Any]] | None = None
_memo_lock = threading.Lock()
#: Held while the checks are worked out: requests that arrive meanwhile (the proposal editor
#: asks for the checks and the proposal at once, the RPC server serves them in two threads) wait
#: and take the answer kept, rather than designing every member a second time.
_work_lock = threading.RLock()


def _folder(out_dir: str | Path) -> str:
    return str(Path(out_dir).resolve())


def _has_assumed_bars(project_path: str | Path) -> bool:
    """Whether some concrete object types other than slabs have no bars (the gathered checks
    then use assumed ones and differ from the design report; slabs without bars they tell
    apart, :attr:`saengine.design.required.Gathered.plain`); True when the files cannot be
    read."""
    from saengine.design.required import with_assumed_bars
    from saengine.library.materials import MaterialLibrary

    root = Path(project_path).resolve().parent.parent
    try:
        materials = MaterialLibrary.model_validate_json(
            (root / "03 Materials/materials.json").read_text(encoding="utf-8")
        )
        objects_text = (root / "04 Objects/objects.json").read_text(encoding="utf-8")
        objects, assumed = with_assumed_bars(objects_text, materials)
        kinds = {o.id: o.kind for o in objects.objects}
        return any(kinds.get(t) != "slab" for t in assumed)
    except (OSError, ValueError):
        return True


def gathered(
    out_dir: str | Path,
    project_path: str | Path,
    stamp: str | None = None,
    *,
    substructure: bool = True,
) -> Any:
    """:func:`saengine.design.required.gather` of the run: the one gathered last in this
    process while its inputs have ``stamp`` (:func:`report_stamp`, taken before the checks read
    the files; worked out here when None), else gathered again and kept in its place.
    ``substructure``: the foundations' demands are needed too (else a gathering without them
    does)."""
    from saengine.design.required import gather

    global _GATHERED
    stamp = stamp or report_stamp(out_dir, project_path)
    folder = _folder(out_dir)
    with _work_lock:
        with _memo_lock:
            memo = _GATHERED
        if memo and memo[:2] == (folder, stamp) and (memo[2] or not substructure):
            return memo[3]
        if memo and memo[:2] == (folder, stamp):
            # Gathered for the design report, without the foundations: add them rather than
            # design every member again (Run All's required steel, after its design checks).
            _add_substructure(memo[3], out_dir)
            with _memo_lock:
                _GATHERED = (folder, stamp, True, memo[3], memo[4])
            return memo[3]
        result = gather(out_dir, project_path, substructure)
        # The design report as design_report makes it, when these checks tell it.
        report_copy = None if result.plain is None else copy.deepcopy(result.plain)
        with _memo_lock:
            _GATHERED = (folder, stamp, substructure, result, report_copy)
        return result


def _add_substructure(gathering: Any, out_dir: str | Path) -> None:
    """Adds the foundations' design to checks gathered without them, as
    :func:`saengine.design.required.gather` does with ``substructure``."""
    root = Path(gathering.root)
    if not (root / "09 Substructure" / "substructure.json").exists():
        return
    from saengine.substructure.context import load_context
    from saengine.substructure.report import report as substructure_report

    try:
        gathering.context = load_context(root, out_dir)
        gathering.substructure = substructure_report(gathering.context)
    except ValueError as error:
        gathering.notes.append(f"9 Substructure not designed: {error}")


def checks(
    out_dir: str | Path, project_path: str | Path, stamp: str | None = None
) -> dict[str, Any]:
    """:func:`saengine.design.design_report` of the run (unchanged, before :func:`_plain`):
    the one this process made last while the inputs have ``stamp`` (from :func:`gathered` or
    from an earlier call), else made now. Each call returns its own copy.

    Made now, it comes from :func:`gathered` (one run of the checks then serves the design
    proposal and the required steel too), unless some object types other than slabs have no
    bars."""
    from saengine.design import design_report

    global _REPORT
    stamp = stamp or report_stamp(out_dir, project_path)
    folder = _folder(out_dir)

    def known() -> dict[str, Any] | None:
        with _memo_lock:
            memo, alone = _GATHERED, _REPORT
        if memo and memo[:2] == (folder, stamp) and memo[4] is not None:
            return copy.deepcopy(memo[4])
        if alone and alone[:2] == (folder, stamp):
            return copy.deepcopy(alone[2])
        return None

    found = known()
    if found is not None:
        return found
    with _work_lock:
        found = known()
        if found is not None:
            return found
        if not _has_assumed_bars(project_path):
            gathered(out_dir, project_path, stamp, substructure=False)
            found = known()
            if found is not None:
                return found
        result = design_report(out_dir, project_path)
        with _memo_lock:
            _REPORT = (folder, stamp, copy.deepcopy(result))
        return result


def forget() -> None:
    """Drops the checks kept in this process (:func:`gathered`, :func:`checks`)."""
    global _GATHERED, _REPORT
    with _memo_lock:
        _GATHERED = _REPORT = None


def kept_report(out_dir: str | Path, project_path: str | Path) -> dict[str, Any] | None:
    """The kept design checks of the run while they are current, else None (cheap: no design,
    no response spectrum run)."""
    return kept(out_dir, inputs_stamp(out_dir, project_path), REPORT_FILE)


def keep_report(
    out_dir: str | Path, project_path: str | Path, result: dict[str, Any], stamp: str
) -> None:
    """Keeps ``result`` (:func:`saengine.design.design_report`) as the design checks of inputs
    with ``stamp`` (:func:`inputs_stamp`, taken before the design read the files)."""
    keep(out_dir, stamp, _plain(result), REPORT_FILE)


def report_stamp(out_dir: str | Path, project_path: str | Path) -> str:
    """The stamp to keep a design report under: the response spectrum design run first (as
    :func:`required` does), so that writing it does not make the kept report stale."""
    _ensure_seismic_design(out_dir, project_path)
    return inputs_stamp(out_dir, project_path)


def report(
    out_dir: str | Path, project_path: str | Path, *, fresh: bool = False
) -> dict[str, Any] | None:
    """:func:`saengine.design.design_report` of the run, the kept one while it is current
    (``fresh``: always work it out again); None when the design checks give nothing."""
    from saengine.design import design_report

    try:
        stamp = report_stamp(out_dir, project_path)
    except Exception:  # noqa: BLE001 - not kept, but the checks are still made
        return _plain(design_report(out_dir, project_path)) or None
    if fresh:
        result = design_report(out_dir, project_path)
    else:
        cached = kept(out_dir, stamp, REPORT_FILE)
        if cached is not None:
            return cached
        result = checks(out_dir, project_path, stamp)
    if not result:
        return None
    result = _plain(result)
    keep(out_dir, stamp, result, REPORT_FILE)
    return result


# ─────────────────────────────── the report's tables ───────────────────────────────

#: Element kinds of the tables, in this order; any other kind follows alphabetically.
#: (The member order of the report's design tables, the foundations last: they are their own chapter.)
KIND_ORDER = ("column", "beam", "slab", "isolated", "combined", "strip", "pileCap", "raft")
KIND_TITLES = {
    "beam": "Beams",
    "column": "Columns",
    "slab": "Slabs",
    "isolated": "Isolated footings",
    "combined": "Combined footings",
    "strip": "Strip footings",
    "pileCap": "Pile caps",
    "raft": "Rafts",
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def is_other_failure(row: dict[str, Any]) -> bool:
    """A failing check that bars do not fix (a footing's bearing): no steel unit."""
    return not row.get("unit")


def _ratio(row: dict[str, Any]) -> float:
    """How far the provided steel is from the required (larger is worse)."""
    required_steel = _number(row.get("required")) or 0.0
    provided = _number(row.get("provided"))
    if row.get("tooSmall"):
        return math.inf
    if provided is None:
        return 1e9 + required_steel if required_steel > 0 else 0.0
    if row.get("quantity", "").lower().startswith("tie spacing") or "spacing" in str(
        row.get("unit", "")
    ):
        return provided / required_steel if required_steel else 0.0
    return required_steel / provided if provided else (1e9 if required_steel else 0.0)


def _fmt(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "–"
    return f"{number:,.0f}" if abs(number) >= 10 else f"{number:.3g}"


def required_tables(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Per member kind, one row per object type: its members, the row that governs (the
    largest required over provided), required and provided, and the members short of steel.
    ``[{kind, title, rows, bad}]`` (``bad``: the type has a member short or too small)."""
    by_type: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in result.get("elements") or []:
        if not isinstance(row, dict) or is_other_failure(row):
            continue
        key = (str(row.get("kind") or "member"), str(row.get("type") or "–"))
        by_type.setdefault(key, []).append(row)
    kinds = sorted(
        {k for k, _ in by_type},
        key=lambda k: (KIND_ORDER.index(k) if k in KIND_ORDER else len(KIND_ORDER), k),
    )
    tables = []
    for kind in kinds:
        rows, bad = [], []
        for (k, type_id), type_rows in sorted(by_type.items()):
            if k != kind:
                continue
            members = sorted({str(r.get("element")) for r in type_rows})
            short = sorted({str(r.get("element")) for r in type_rows if r.get("ok") is False})
            small = sorted({str(r.get("element")) for r in type_rows if r.get("tooSmall")})
            worst = max(type_rows, key=_ratio)
            where = str(worst.get("location") or "")
            quantity = str(worst.get("quantity") or "")
            rows.append(
                [
                    type_id,
                    str(len(members)),
                    f"{quantity} ({where}, {worst.get('element')})" if where else quantity,
                    _fmt(worst.get("required")),
                    _fmt(worst.get("provided")) if worst.get("provided") is not None else "none",
                    str(worst.get("unit") or ""),
                    ", ".join(short) if short else "–",
                    "TOO SMALL" if small else ("SHORT" if short else "OK"),
                ]
            )
            bad.append(bool(short or small))
        title = KIND_TITLES.get(kind) or kind[:1].upper() + kind[1:]
        tables.append({"kind": kind, "title": title, "rows": rows, "bad": bad})
    return tables


def required_summary(result: dict[str, Any]) -> dict[str, Any]:
    """The counts Run All and the report print: elements, short, too small, without bars."""
    summary = result.get("summary") or {}
    rows = [r for r in result.get("elements") or [] if isinstance(r, dict)]
    steel = [r for r in rows if not is_other_failure(r)]
    short = sorted({str(r.get("element")) for r in steel if r.get("ok") is False})
    other = sorted({str(r.get("element")) for r in rows if is_other_failure(r)})
    small = sorted({str(r.get("element")) for r in steel if r.get("tooSmall")})
    return {
        "elements": int(summary.get("elements") or len({r.get("element") for r in rows})),
        "short": short,
        "tooSmall": small,
        "otherFailures": other,
        "assumed": [str(t) for t in summary.get("assumed") or []],
    }

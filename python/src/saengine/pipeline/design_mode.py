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
"""

from __future__ import annotations

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

#: The kept answer, in the results folder of the run.
REQUIRED_FILE = "design-required.json"
#: The kept design checks of the run (:func:`report`).
REPORT_FILE = "design-report.json"

#: Files of the results folder that are written from the results, not by the analysis: they do
#: not enter the stamp (writing them must not make the kept answer stale).
_DERIVED = frozenset({REQUIRED_FILE, REPORT_FILE, "design-summary.json"})
#: The same by path in the results folder: the response spectrum design's summary is written
#: again on every design (``saengine.fem.seismic_design.seismic_design`` keeps its run while
#: the model and the results do not change but rewrites the summary of it), so its time would
#: make every kept answer stale at once. The run it is made from is stamped.
_DERIVED_PATHS = frozenset({"rs-design/seismic-design.json"})

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
    for relative in (*INPUT_FILES, project_path.resolve().relative_to(root).as_posix()):
        try:
            add(relative, (root / relative).read_bytes())
        except OSError:
            add(relative, "missing")
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
    result = _plain(design_required(out_dir, project_path, options))
    keep(out_dir, stamp, result)
    return result


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

    stamp = report_stamp(out_dir, project_path)
    if not fresh:
        cached = kept(out_dir, stamp, REPORT_FILE)
        if cached is not None:
            return cached
    result = design_report(out_dir, project_path)
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

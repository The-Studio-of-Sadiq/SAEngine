"""Undo and redo of the batches written to disk (the command line, the SDK, the assistant).

In the app an action's changes are applied through the part files' text models, so the editor's
own Undo and live co-editing handle them. A batch run with ``write=True`` (``saengine <action>``,
``saengine action batch``) writes the files itself; :func:`saengine.actions.run.run_actions`
records each such batch here: the texts of the files it wrote, before and after. ``edit.undo``
puts the texts before back, ``edit.redo`` the texts after.

Only the edited part files are recorded, never the results a run step computes (an undone edit
makes those out of date, as any edit does: run again). A file changed since (by the app, an
editor or another batch) is not overwritten: the undo is refused unless forced.

The journal is ``actions-undo.saengine-tmp`` in the project folder: a temporary file, so it is
neither versioned nor archived.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any

from pydantic import Field

from saengine.actions.catalogue._util import Params
from saengine.actions.errors import refuse
from saengine.actions.registry import action
from saengine.actions.result import ActionResult
from saengine.actions.view import ProjectView, normal_path

JOURNAL = "actions-undo.saengine-tmp"
#: Batches kept to undo.
LIMIT = 50


def _path(root: Path) -> Path:
    return Path(root) / JOURNAL


def load(root: str | Path) -> dict[str, list[dict[str, Any]]]:
    """The journal: ``{"undo": [...], "redo": [...]}``, the newest batch last."""
    try:
        data = json.loads(_path(Path(root)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"undo": [], "redo": []}
    if not isinstance(data, dict):
        return {"undo": [], "redo": []}
    return {k: [e for e in data.get(k) or [] if isinstance(e, dict)] for k in ("undo", "redo")}


def _save(root: Path, journal: dict[str, list[dict[str, Any]]]) -> None:
    from saengine.actions.run import write_atomic

    if not journal["undo"] and not journal["redo"]:
        with contextlib.suppress(OSError):
            os.unlink(_path(root))
        return
    write_atomic(_path(root), json.dumps(journal, ensure_ascii=False))


def record(
    root: str | Path, label: str, before: dict[str, str | None], after: dict[str, str]
) -> None:
    """Records a written batch (``label``: its actions) for undo; the redo list is cleared."""
    files = {p: {"before": before.get(p), "after": t} for p, t in after.items()}
    files = {p: f for p, f in files.items() if f["before"] != f["after"]}
    if not files:
        return
    root = Path(root)
    journal = load(root)
    journal["undo"] = [*journal["undo"], {"label": label, "files": files}][-LIMIT:]
    journal["redo"] = []
    _save(root, journal)


def _apply(view: ProjectView, entry: dict[str, Any], to: str, force: bool) -> list[str]:
    """Writes each file's ``to`` text ("before" or "after"); refused when one was changed since."""
    from saengine.actions.run import write_atomic

    other = "after" if to == "before" else "before"
    files: dict[str, dict[str, str | None]] = entry.get("files") or {}
    changed = [p for p, f in files.items() if view.saved_text(p) != f.get(other)]
    if changed and not force:
        refuse(
            f"Changed since '{entry.get('label')}' was done: {', '.join(sorted(changed))}. "
            "Give force: true to overwrite them.",
            "force",
            False,
        )
    for path, f in files.items():
        target = view.root / normal_path(path)
        text = f.get(to)
        if text is None:
            with contextlib.suppress(FileNotFoundError):
                target.unlink()
        else:
            write_atomic(target, text)
    return sorted(files)


class UndoParams(Params):
    force: bool = Field(
        default=False, description="Overwrite files changed since the batch (else refused)."
    )


def _step(view: ProjectView, p: UndoParams, source: str, target: str, to: str) -> ActionResult:
    journal = load(view.root)
    if not journal[source]:
        refuse(f"There is nothing to {source}.", "", None)
    entry = journal[source][-1]
    files = _apply(view, entry, to, p.force)
    journal[source] = journal[source][:-1]
    journal[target] = [*journal[target], entry]
    _save(view.root, journal)
    verb = "Undid" if source == "undo" else "Redid"
    return ActionResult(
        message=f"{verb} '{entry.get('label')}': {', '.join(files)}."
        + (" Run again: the results are out of date." if files else ""),
        data={"files": files, "label": entry.get("label")},
    )


@action(
    "edit.undo",
    summary="Undo the last batch of actions written to disk (the command line's or the "
    "assistant's): its part files go back to what they were.",
    params=UndoParams,
    parts=(),
    kind="run",
    example={},
)
def edit_undo(view: ProjectView, p: UndoParams) -> ActionResult:
    return _step(view, p, "undo", "redo", "before")


@action(
    "edit.redo",
    summary="Redo the last undone batch of actions.",
    params=UndoParams,
    parts=(),
    kind="run",
    example={},
)
def edit_redo(view: ProjectView, p: UndoParams) -> ActionResult:
    return _step(view, p, "redo", "undo", "after")


class HistoryParams(Params):
    pass


@action(
    "edit.history",
    summary="The batches that can be undone and redone (newest first), with their files.",
    params=HistoryParams,
    parts=(),
    kind="query",
    example={},
)
def edit_history(view: ProjectView, p: HistoryParams) -> ActionResult:
    journal = load(view.root)

    def rows(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {"label": e.get("label"), "files": sorted(e.get("files") or {})}
            for e in reversed(entries)
        ]

    data = {"undo": rows(journal["undo"]), "redo": rows(journal["redo"])}
    return ActionResult(
        message=f"{len(data['undo'])} to undo, {len(data['redo'])} to redo.", data=data
    )

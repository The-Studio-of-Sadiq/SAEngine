"""Running a batch of actions on one project (:func:`run_actions`).

The steps run in order on one :class:`~saengine.actions.view.ProjectView`, so a later step sees
what an earlier one changed. A batch is all or nothing: when a step is refused (its parameters,
a guardrail, or a changed part that no longer validates), no change is returned or written.

A ``run`` step (Run All, the design proposal, an export) works on the saved files. Before it,
with ``write=True``, the changes of the steps before it are written (a commit point: they stay
written if a later step fails, and ``BatchResult.written`` lists them); with ``write=False`` it
is refused while there are unsaved changes, since it would not see them.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from saengine.actions.errors import ActionError
from saengine.actions.paths import SETTINGS
from saengine.actions.registry import UnknownAction, get
from saengine.actions.result import ActionResult, BatchResult, Problem
from saengine.actions.validate import check_changes
from saengine.actions.view import ProjectView, normal_path


def _params_problems(error: ValidationError) -> list[Problem]:
    out = []
    for e in error.errors():
        field = ".".join(str(p) for p in e["loc"])
        out.append(
            Problem(
                field=field,
                value=e.get("input") if not isinstance(e.get("input"), dict) else None,
                reason=e["msg"].removeprefix("Value error, "),
            )
        )
    return out


@contextlib.contextmanager
def _pack(view: ProjectView) -> Iterator[None]:
    """The code pack the project's settings (as the batch has them now) choose, in force."""
    from saengine.codes import context as code_context

    settings = view.read(SETTINGS, None)
    try:
        pack = code_context.pack_for(settings if isinstance(settings, dict) else None, view.root)
    except Exception:  # noqa: BLE001 - a pack that cannot be loaded: the default pack's values
        pack = None
    with code_context.using(pack):
        yield


def write_atomic(path: Path, text: str) -> None:
    """Writes ``text`` (UTF-8, as given) to ``path`` through a temporary file and a rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(text.encode("utf-8"))
        os.replace(temp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp)
        raise


def _write(view: ProjectView, texts: dict[str, str]) -> list[str]:
    for path, text in texts.items():
        write_atomic(view.root / normal_path(path), text)
    return sorted(texts)


def _one(view: ProjectView, name: str, raw: Any, write: bool, written: list[str]) -> ActionResult:
    """One step on ``view``: refused (``ok`` False) or done; its changes stay in the view."""
    try:
        info = get(name)
    except UnknownAction as error:
        return ActionResult(
            ok=False,
            action=name,
            message=str(error),
            problems=[Problem(field="action", value=name, reason=str(error))],
        )
    try:
        params = info.params.model_validate(raw if raw is not None else {})
    except ValidationError as error:
        problems = _params_problems(error)
        return ActionResult(
            ok=False,
            action=name,
            problems=problems,
            message=f"{name}: the parameters are not valid: "
            + "; ".join(f"{p.field}: {p.reason}" if p.field else p.reason for p in problems),
        )
    if info.kind == "run":
        pending = view.pending()
        if pending:
            unsaved = [p for p in pending if p not in view.changes()]
            if unsaved or not write:
                return ActionResult(
                    ok=False,
                    action=name,
                    message=f"{name} works on the saved project, and these files are not saved: "
                    f"{', '.join(pending)}. Save them first (or run the batch with write).",
                    problems=[Problem(field="", value=pending, reason="unsaved changes")],
                )
            written += _write(view, view.change_texts())
            view.reload()
    before = view.changes()
    with _pack(view):
        try:
            result = info.fn(view, params)
        except ActionError as error:
            return ActionResult(
                ok=False, action=name, message=error.message, problems=error.problems
            )
        except Exception as error:  # noqa: BLE001 - reported as the step's failure, not raised
            return ActionResult(
                ok=False,
                action=name,
                message=f"{name} could not be done: {type(error).__name__}: {error}",
                problems=[Problem(reason=str(error) or type(error).__name__)],
            )
        if not isinstance(result, ActionResult):
            result = ActionResult(message=str(result or ""))
        result.action = name
        if not result.ok:
            return result
        changed = [p for p, d in view.changes().items() if before.get(p, object()) != d]
        if changed:
            errors, warnings = check_changes(view, before, changed)
            if errors:
                return ActionResult(
                    ok=False,
                    action=name,
                    problems=errors,
                    message=f"{name} was refused: "
                    + "; ".join(f"{p.field}: {p.reason}" if p.field else p.reason for p in errors),
                )
            result.warnings += [w for w in warnings if w not in result.warnings]
    if info.kind == "run":
        view.reload(keep_changes=True)  # what the run wrote is the project now, with its edits
    return result


def run_actions(
    root: str | Path,
    steps: list[dict[str, Any]],
    *,
    overrides: dict[str, str] | None = None,
    write: bool = False,
    stop_on_error: bool = True,
) -> BatchResult:
    """Runs ``steps`` (``[{"action": name, "params": {...}}]``) in order on the project at
    ``root`` (its folder; for ``project.create`` the folder to create it in). ``overrides``: the
    app's unsaved part texts by path. ``write``: write the changed files (atomically) and save a
    version "Actions: <names>" when the project keeps versions. ``stop_on_error``: stop at the
    first refused step (else run the others too, to report every problem; still nothing is
    changed)."""
    from saengine.codes import context as code_context

    root = Path(root)
    view = ProjectView(root, overrides)
    results: list[ActionResult] = []
    failed: int | None = None
    written: list[str] = []
    with code_context.project(root):
        for index, step in enumerate(steps):
            if not isinstance(step, dict) or not isinstance(step.get("action"), str):
                result = ActionResult(
                    ok=False,
                    message=f'Step {index + 1} is not {{"action": name, "params": {{...}}}}.',
                    problems=[Problem(field=f"steps[{index}]", value=None, reason="not a step")],
                )
            else:
                snapshot = view.snapshot()
                result = _one(view, step["action"], step.get("params"), write, written)
                if not result.ok:
                    view.restore(snapshot)
            results.append(result)
            if not result.ok and failed is None:
                failed = index
                if stop_on_error:
                    break
        if failed is not None:
            if written:
                results[failed].warnings.append(
                    "The changes of the steps before the run step were written already: "
                    + ", ".join(written)
                )
            return BatchResult(ok=False, results=results, failed_step=failed, written=written)
        texts = view.change_texts()
        version = None
        if write and texts:
            written += _write(view, texts)
        if write and written:
            version = _save_version(root, [str(s.get("action")) for s in steps])
    return BatchResult(
        ok=True,
        results=results,
        changes=texts,
        written=sorted(set(written)),
        version=version,
    )


def _save_version(root: Path, names: list[str]) -> dict[str, Any] | None:
    """A version "Actions: <names>" when the project keeps versions (its folder has one)."""
    if not (root / ".git").exists():
        return None
    from saengine.project import versions

    unique = list(dict.fromkeys(names))
    message = "Actions: " + ", ".join(unique[:6]) + (", ..." if len(unique) > 6 else "")
    try:
        return versions.save(root, message).get("version")
    except versions.VersionsError:
        return None


def run_action(
    root: str | Path, name: str, params: dict[str, Any] | None = None, **options: Any
) -> BatchResult:
    """One action as a batch of one."""
    return run_actions(root, [{"action": name, "params": params or {}}], **options)


def load_steps(text: str) -> list[dict[str, Any]]:
    """The steps of a batch file: a list of steps, or ``{"steps": [...]}``."""
    data = json.loads(text)
    if isinstance(data, dict) and isinstance(data.get("steps"), list):
        data = data["steps"]
    if not isinstance(data, list):
        raise ValueError('a batch is a list of {"action": name, "params": {...}} steps')  # noqa: TRY004
    return data

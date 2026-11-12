"""A project as the actions see it: its part files, read when first asked for, with the app's
unsaved texts (``overrides``) in place of the saved ones, and the changes the actions made.

Paths are relative to the project folder, with forward slashes ("05 Floor Plan/floor-plan.json").
An action takes a part with :meth:`ProjectView.part` (a deep copy it may edit) and records its
edit with :meth:`ProjectView.put`; later actions of the batch see it. Nothing is written here.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from saengine.actions.errors import ActionError

_MISSING = object()


def normal_path(path: str) -> str:
    """``path`` relative, with forward slashes."""
    text = str(path).replace("\\", "/").strip("/")
    parts = text.split("/")
    if not text or ".." in parts or ":" in text:
        raise ValueError(f"'{path}' is not a path inside the project")
    return text


def json_text(data: Any, like: str | None = None) -> str:
    """``data`` as the project writes JSON: indented like ``like`` (the file's own text; tabs by
    default), UTF-8 characters kept, a final newline, and ``like``'s line endings."""
    indent: str | int = "\t"
    if like:
        found = re.search(r"\n([ \t]+)\S", like)
        if found:
            lead = found.group(1)
            indent = "\t" if lead.startswith("\t") else len(lead)
    text = json.dumps(data, indent=indent, ensure_ascii=False) + "\n"
    if like and "\r\n" in like:
        text = text.replace("\n", "\r\n")
    return text


class ProjectView:
    """The part files of the project at ``root``; ``overrides`` (path -> text) are the app's
    unsaved texts, used instead of the files on disk."""

    def __init__(self, root: str | Path, overrides: dict[str, str] | None = None) -> None:
        self.root = Path(root)
        self.overrides: dict[str, str] = {
            normal_path(k): v for k, v in (overrides or {}).items() if isinstance(v, str)
        }
        self._texts: dict[str, str | None] = {}
        self._parsed: dict[str, Any] = {}
        self._changes: dict[str, Any] = {}

    # ── reading ──

    def text(self, path: str) -> str | None:
        """The current text of ``path`` (before this batch's changes): the override, else the
        file; None when there is none."""
        path = normal_path(path)
        if path not in self._texts:
            if path in self.overrides:
                self._texts[path] = self.overrides[path]
            else:
                try:
                    self._texts[path] = (self.root / path).read_bytes().decode("utf-8")
                except (OSError, UnicodeError):
                    self._texts[path] = None
        return self._texts[path]

    def saved_text(self, path: str) -> str | None:
        """The text on disk, whatever the overrides say."""
        try:
            return (self.root / normal_path(path)).read_bytes().decode("utf-8")
        except (OSError, UnicodeError):
            return None

    def _original(self, path: str) -> Any:
        if path not in self._parsed:
            text = self.text(path)
            if text is None or not text.strip():
                self._parsed[path] = _MISSING
            else:
                try:
                    self._parsed[path] = json.loads(text)
                except ValueError as error:
                    raise ActionError(
                        f"{path} is not valid JSON ({error}): fix it first."
                    ) from error
        return self._parsed[path]

    def has(self, path: str) -> bool:
        path = normal_path(path)
        if path in self._changes:
            return self._changes[path] is not None
        return self._original(path) is not _MISSING

    def read(self, path: str, default: Any = _MISSING) -> Any:
        """The current data of ``path`` (with this batch's changes), not to be edited."""
        path = normal_path(path)
        data = self._changes[path] if path in self._changes else self._original(path)
        if data is _MISSING or data is None:
            if default is _MISSING:
                raise ActionError(
                    f"The project has no {path}: create the project first (project.create)."
                )
            return default
        return data

    def part(self, path: str, default: Any = _MISSING) -> Any:
        """A deep copy of the current data of ``path`` for an action to edit and :meth:`put`."""
        found = self.read(path, default)
        return copy.deepcopy(found)

    # ── changes ──

    def put(self, path: str, data: Any) -> None:
        """Records ``data`` as the new content of ``path``."""
        self._changes[normal_path(path)] = copy.deepcopy(data)

    def changes(self) -> dict[str, Any]:
        """The changed paths and their new data, without those that came back to what they were."""
        out = {}
        for path, data in self._changes.items():
            original = self._original(path)
            if original is _MISSING or original != data:
                out[path] = data
        return out

    def change_texts(self) -> dict[str, str]:
        """:meth:`changes` as file texts in the project's formatting."""
        return {path: json_text(data, self.text(path)) for path, data in self.changes().items()}

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self._changes)

    def restore(self, snapshot: dict[str, Any]) -> None:
        self._changes = copy.deepcopy(snapshot)

    def pending(self) -> list[str]:
        """Paths whose current text differs from the saved file: this batch's changes and the
        overrides that are not saved."""
        out = set(self.changes())
        for path, text in self.overrides.items():
            if text != self.saved_text(path):
                out.add(path)
        return sorted(out)

    def reload(self, keep_changes: bool = False) -> None:
        """Forgets what was read and the overrides (and the changes, unless ``keep_changes``):
        after the changes were written, or a run step wrote files of its own, the files on disk
        are the project."""
        self.overrides.clear()
        self._texts.clear()
        self._parsed.clear()
        if not keep_changes:
            self._changes.clear()

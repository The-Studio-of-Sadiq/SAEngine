"""The clause references the report and its worksheets print (:mod:`saengine.codes.citations`),
and the code pack in force while they are built (:func:`in_force`)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from saengine.codes import context as code_context
from saengine.codes.citations import TABLE, after, code_name, paren, ref

__all__ = ["TABLE", "after", "code_name", "in_force", "paren", "ref"]


@contextmanager
def in_force(root: str | Path | None, settings: Any = None) -> Iterator[list[str]]:
    """Within the block the pack the project's settings choose is in force (its own packs
    looked for in ``root``). Yields the problems: when the pack cannot be used the default pack
    is in force and the list says so (the report prints it as a warning)."""
    problems: list[str] = []
    with code_context.project(root):
        if settings is None and root is not None:
            try:
                from saengine.report.build import _Parts

                settings = _Parts(Path(root), []).settings()
            except Exception:  # noqa: BLE001 - no settings: the default pack
                settings = None
        try:
            pack = code_context.pack_for(settings, root)
        except Exception as error:  # noqa: BLE001 - the report goes on with the default pack
            pack = None
            problems.append(
                f"The project's code pack could not be used ({error}); the report cites "
                f"{code_context.code_name(code_context.default_pack())}."
            )
        with code_context.using(pack):
            yield problems

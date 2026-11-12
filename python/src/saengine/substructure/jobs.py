"""The editor's design checks of one project, newest first.

Each save in 9 Substructure asks for the checks again; a raft check runs a solver for minutes.
Without this every save started one more solve beside the ones still running. A check of a
project that is asked for again is *superseded*: its solver process is stopped
(:func:`saengine.substructure.raft.run_raft` polls :func:`superseded`) and it ends with
:class:`Superseded`, so only the newest check of a project keeps running.

Run All's foundation step does not take part (``substructure_report(..., supersede=False)``):
an editor check never stops it, and it never stops one.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

_LOCK = threading.Lock()
_LATEST: dict[str, int] = {}
_LOCAL = threading.local()


class Superseded(ValueError):
    """A newer check of the same project was asked for: this one stopped."""

    def __init__(self) -> None:
        super().__init__("a newer check of the foundations was started; this one was stopped")


def _key(root: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(root)))


@contextmanager
def newest(root: str | os.PathLike[str]) -> Iterator[None]:
    """Runs the block as the newest check of the project at ``root``: the checks of it still
    running are superseded."""
    key = _key(root)
    with _LOCK:
        number = _LATEST.get(key, 0) + 1
        _LATEST[key] = number
    previous = getattr(_LOCAL, "token", None)
    _LOCAL.token = (key, number)
    try:
        yield
    finally:
        _LOCAL.token = previous


def superseded() -> bool:
    """Whether the check this thread runs (inside :func:`newest`) has been superseded."""
    token = getattr(_LOCAL, "token", None)
    if token is None:
        return False
    with _LOCK:
        return _LATEST.get(token[0]) != token[1]

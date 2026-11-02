"""The requests the RPC server is working on, with what each is doing (B10-21 of usability walk 3).

Each request is a job from its arrival to its answer. Long work tells what it does with
:func:`note` ("Checking the columns", "Waiting for the design checks of another request"), and
``saengine/jobs`` answers the list at once from the server's own thread, so the app tells an
engine that is working (it answers, with the jobs' notes) from one that no longer responds.

:func:`note` outside a request (the headless Run All, tests) does nothing.
"""

from __future__ import annotations

import contextvars
import itertools
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Job:
    id: int
    method: str
    since: float = field(default_factory=time.monotonic)
    note: str | None = None
    noted: float | None = None

    def to_json(self, now: float) -> dict[str, Any]:
        return {
            "id": self.id,
            "method": self.method,
            "seconds": round(now - self.since, 1),
            "note": self.note,
            "noteSeconds": None if self.noted is None else round(now - self.noted, 1),
        }


_ids = itertools.count(1)
_lock = threading.Lock()
_running: dict[int, Job] = {}
#: The job of the request being handled (the server's thread, async handlers).
_current: contextvars.ContextVar[Job | None] = contextvars.ContextVar("rpc_job", default=None)
#: The job a worker thread works for (executors do not carry the context over).
_local = threading.local()


def start(method: str) -> tuple[Job, contextvars.Token]:
    job = Job(next(_ids), method)
    with _lock:
        _running[job.id] = job
    return job, _current.set(job)


def finish(job: Job, token: contextvars.Token) -> None:
    with _lock:
        _running.pop(job.id, None)
    try:
        _current.reset(token)
    except ValueError:  # reset from another context (an async handler's last step)
        _current.set(None)


def current() -> Job | None:
    return getattr(_local, "job", None) or _current.get()


def run_as(job: Job | None, call: Callable[[Any], Any], params: Any) -> Any:
    """``call(params)`` in a worker thread, working for ``job``."""
    previous = getattr(_local, "job", None)
    _local.job = job
    try:
        return call(params)
    finally:
        _local.job = previous


def note(text: str | None) -> None:
    """Says what the current request is doing (None: nothing particular)."""
    job = current()
    if job is not None:
        job.note = text
        job.noted = time.monotonic()


def running() -> list[dict[str, Any]]:
    """The jobs in progress, oldest first."""
    now = time.monotonic()
    with _lock:
        jobs = sorted(_running.values(), key=lambda j: j.since)
    return [j.to_json(now) for j in jobs]

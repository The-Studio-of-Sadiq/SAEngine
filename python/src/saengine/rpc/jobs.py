"""The requests the RPC server is working on, with what each is doing (B10-21 of usability walk 3).

Each request is a job from its arrival to its answer. Long work tells what it does with
:func:`note` ("Checking the columns", "Waiting for the design checks of another request"), and
``saengine/jobs`` answers the list at once from the server's own thread, so the app tells an
engine that is working (it answers, with the jobs' notes) from one that no longer responds.

:func:`note` outside a request (the headless Run All, tests) does nothing.

A job can be cancelled (``saengine/cancelJobs``: Stop Waiting on Design Reinforcement, R1-1 of
re-walk 1): its work stops at the next :func:`check` (each :func:`note` checks too) and the
request answers an error. The check is cooperative, a job that never checks runs to its end.
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
    cancelled: bool = False

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


class JobCancelled(BaseException):
    """Raised by :func:`check` in a cancelled job's work. A BaseException, so the design code's
    ``except Exception`` fallbacks do not swallow it; :func:`run_as` turns it into
    :class:`CancelledRequest` at the worker's edge."""


class CancelledRequest(RuntimeError):
    """The answer of a request whose job was cancelled."""


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
    except JobCancelled:
        raise CancelledRequest("Cancelled: the engine stopped this request.") from None
    finally:
        _local.job = previous


def check() -> None:
    """Raises :class:`JobCancelled` when the current request's job was cancelled."""
    job = current()
    if job is not None and job.cancelled:
        raise JobCancelled(job.method)


def cancel(methods: list[str] | tuple[str, ...] | set[str]) -> int:
    """Cancels the running jobs of ``methods``; how many."""
    wanted = set(methods)
    count = 0
    with _lock:
        for job in _running.values():
            if job.method in wanted and not job.cancelled:
                job.cancelled = True
                count += 1
    return count


def note(text: str | None) -> None:
    """Says what the current request is doing (None: nothing particular)."""
    job = current()
    if job is not None:
        check()
        job.note = text
        job.noted = time.monotonic()


def running() -> list[dict[str, Any]]:
    """The jobs in progress, oldest first."""
    now = time.monotonic()
    with _lock:
        jobs = sorted(_running.values(), key=lambda j: j.since)
    return [j.to_json(now) for j in jobs]

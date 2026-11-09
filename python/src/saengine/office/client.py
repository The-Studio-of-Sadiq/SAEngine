"""Sending a project to the office server (:mod:`saengine.office.server`) and bringing the
results back.

:func:`submit` archives the project (no results, versions or exports), notes the SHA-256 of every
file sent, creates a job on the server, uploads the archive and starts the job. :func:`fetch`
downloads the files the run wrote and puts them into the project, except a file the engineer has
changed since it was sent (those are listed and left alone, so nothing typed meanwhile is lost),
and never a path outside the project or inside ``.git``.

The app calls these through the backend (``office/submit``, ``office/status``, ``office/fetch``,
``office/cancel`` in :mod:`saengine.rpc.server`) in a background thread per job
(:func:`start_background`); the token never touches the disk on the engineer's side here (the app
keeps it in its secret storage and passes it with each call). Only the URL the engineer
configured is contacted.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

#: The record of a submitted job in the project: what was sent and where.
JOB_FILE = ".saengine-office-job.json"
TIMEOUT = 60.0


class OfficeError(RuntimeError):
    """The server refused or could not be reached; the message says why, for the engineer."""

    def __init__(self, message: str, code: str = "office") -> None:
        super().__init__(message)
        self.code = code


def _url(base: str, path: str) -> str:
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise OfficeError(f"{base}: not an http(s) address of an office server", "badUrl")
    return base.rstrip("/") + path


def _request(
    base: str,
    token: str,
    method: str,
    path: str,
    body: bytes | None = None,
    content_type: str = "application/json",
    timeout: float = TIMEOUT,
) -> bytes:
    request = urllib.request.Request(_url(base, path), data=body, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    if body is not None:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise OfficeError("The office server refused the token.", "unauthorized") from error
        if error.code == 429:
            raise OfficeError(
                "The office server refuses this computer for a minute (too many wrong tokens).",
                "locked",
            ) from error
        detail = ""
        try:
            detail = json.loads(error.read()).get("error", "")
        except (ValueError, AttributeError, OSError):
            pass
        raise OfficeError(f"The office server answered {error.code}: {detail}", "http") from error
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise OfficeError(
            f"The office server at {base} could not be reached: {error}", "unreachable"
        ) from error


def rpc(base: str, token: str, method: str, params: dict[str, Any] | None = None) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode(
        "utf-8"
    )
    answer = json.loads(_request(base, token, "POST", "/rpc", body))
    if answer.get("error"):
        raise OfficeError(str(answer["error"].get("message")), "rpc")
    return answer.get("result")


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as data:
        for chunk in iter(lambda: data.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sent_files(root: Path) -> dict[str, str]:
    out = {}
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if path.is_file() and ".git" not in rel.parts:
            out[rel.as_posix()] = _digest(path)
    return out


def submit(
    project_root: str | Path, server: str, token: str, steps: list[str] | None = None
) -> dict[str, Any]:
    """Sends the project to ``server`` and starts the job: ``{"jobId", "server", "steps"}`` (also
    kept in the project's :data:`JOB_FILE`)."""
    from saengine.pipeline.project import open_project
    from saengine.project.archive import export_project

    project = open_project(project_root)
    root = project.root
    with tempfile.TemporaryDirectory(prefix="saengine-office-") as folder:
        archive = Path(folder) / f"{uuid.uuid4().hex}.civil"
        export_project(
            root,
            archive,
            include_results=False,
            include_versions=False,
            include_exports=False,
            note="office server job",
        )
        created = rpc(
            server,
            token,
            "office/createJob",
            {"name": project.name, **({"steps": steps} if steps else {})},
        )
        job_id = created["jobId"]
        _request(
            server,
            token,
            "PUT",
            f"/jobs/{job_id}/archive",
            archive.read_bytes(),
            "application/octet-stream",
            timeout=600,
        )
    record = {
        "jobId": job_id,
        "server": server,
        "steps": steps,
        "submitted": time.time(),
        "sent": _sent_files(root),
    }
    (root / JOB_FILE).write_text(json.dumps(record, indent="\t") + "\n", "utf-8")
    rpc(server, token, "office/startJob", {"jobId": job_id})
    return {"jobId": job_id, "server": server, "steps": steps}


def status(server: str, token: str, job_id: str) -> dict[str, Any]:
    return rpc(server, token, "office/status", {"jobId": job_id})


def cancel(server: str, token: str, job_id: str) -> dict[str, Any]:
    return rpc(server, token, "office/cancel", {"jobId": job_id})


def safe_member(name: str) -> str | None:
    """A zip entry's path when it is a plain relative path inside the project (no drive, no
    ``..``, not in ``.git``), else None."""
    path = PurePosixPath(name.replace("\\", "/"))
    if (
        not name
        or path.is_absolute()
        or ":" in name
        or any(p in ("..", "", ".git") for p in path.parts)
    ):
        return None
    return path.as_posix()


def apply_results(
    project_root: str | Path, archive: str | Path, sent: dict[str, str]
) -> dict[str, Any]:
    """Puts the files of the results zip into the project: ``{"written", "kept", "refused"}``
    (``kept``: files the engineer changed since they were sent, left as they are)."""
    root = Path(project_root).resolve()
    written, kept, refused = [], [], []
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            rel = safe_member(info.filename)
            if rel is None:
                refused.append(info.filename)
                continue
            target = (root / rel).resolve()
            if root not in target.parents:
                refused.append(info.filename)
                continue
            if target.exists() and rel in sent and _digest(target) != sent[rel]:
                kept.append(rel)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".saengine-tmp")
            with z.open(info) as source, tmp.open("wb") as out:
                while chunk := source.read(1 << 20):
                    out.write(chunk)
            tmp.replace(target)
            written.append(rel)
    return {"written": written, "kept": kept, "refused": refused}


def fetch(
    project_root: str | Path, server: str, token: str, job_id: str | None = None
) -> dict[str, Any]:
    """Downloads the job's results into the project (:func:`apply_results`)."""
    root = Path(project_root)
    record = json.loads((root / JOB_FILE).read_text("utf-8"))
    job_id = job_id or record["jobId"]
    if record.get("jobId") != job_id:
        raise OfficeError("The project's last office job is another one.", "otherJob")
    with tempfile.TemporaryDirectory(prefix="saengine-office-") as folder:
        target = Path(folder) / "results.zip"
        target.write_bytes(_request(server, token, "GET", f"/jobs/{job_id}/results", timeout=600))
        result = apply_results(root, target, record.get("sent") or {})
    record["fetched"] = time.time()
    (root / JOB_FILE).write_text(json.dumps(record, indent="\t") + "\n", "utf-8")
    return result


# ─────────────────────────────────────── background (the app) ───────────────────────────────────────


@dataclass
class _Tracked:
    project: str
    server: str
    state: str = "sending"
    job_id: str | None = None
    message: str = ""
    result: dict[str, Any] | None = None
    log: list[str] = field(default_factory=list)
    cancelled: bool = False


_TRACKED: dict[str, _Tracked] = {}
_LOCK = threading.Lock()
POLL = 5.0


def start_background(
    project_root: str, server: str, token: str, steps: list[str] | None = None
) -> dict[str, Any]:
    """Submits, waits and fetches in a thread: ``{"id"}`` of the local tracking entry; its state
    is :func:`background_status`'s."""
    key = uuid.uuid4().hex
    tracked = _Tracked(project_root, server)
    with _LOCK:
        _TRACKED[key] = tracked

    def work() -> None:
        try:
            tracked.job_id = submit(project_root, server, token, steps)["jobId"]
            tracked.state = "running"
            while not tracked.cancelled:
                answer = status(server, token, tracked.job_id)
                tracked.log = list(answer.get("log") or [])[-20:]
                if answer.get("state") in ("done", "failed", "cancelled"):
                    tracked.state = str(answer["state"])
                    tracked.message = str(answer.get("error") or "")
                    break
                time.sleep(POLL)
            if tracked.cancelled:
                cancel(server, token, tracked.job_id)
                tracked.state = "cancelled"
                return
            if tracked.state == "done":
                tracked.state = "fetching"
                tracked.result = fetch(project_root, server, token, tracked.job_id)
                tracked.state = "done"
        except OfficeError as error:
            tracked.state, tracked.message = "failed", str(error)
        except (OSError, ValueError, KeyError) as error:
            tracked.state, tracked.message = "failed", f"{type(error).__name__}: {error}"

    threading.Thread(target=work, name=f"office-client-{key[:8]}", daemon=True).start()
    return {"id": key}


def background_status(key: str) -> dict[str, Any]:
    with _LOCK:
        tracked = _TRACKED.get(key)
    if tracked is None:
        return {"state": "unknown"}
    return {
        "state": tracked.state,
        "jobId": tracked.job_id,
        "server": tracked.server,
        "message": tracked.message,
        "result": tracked.result,
        "log": tracked.log,
    }


def background_cancel(key: str) -> dict[str, Any]:
    with _LOCK:
        tracked = _TRACKED.get(key)
    if tracked is not None:
        tracked.cancelled = True
    return background_status(key)


__all__ = [
    "JOB_FILE",
    "OfficeError",
    "apply_results",
    "background_cancel",
    "background_status",
    "cancel",
    "fetch",
    "rpc",
    "safe_member",
    "start_background",
    "status",
    "submit",
]

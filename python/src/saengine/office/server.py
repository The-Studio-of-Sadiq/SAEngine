"""The office analysis server: Run All on an office machine, for the engineers of the office.

Start it on the machine that should do the work (``saengine office-server --workspace D:\\jobs``).
The first start makes a token, prints it once and keeps only its SHA-256 in
``<workspace>/office-server.json``; give the token to the engineers, who enter it in the app
(it is kept in the app's secret storage). ``--new-token`` replaces it.

Protocol (HTTP/1.1; every request needs ``Authorization: Bearer <token>``, else ``401``; repeated
failures from one address are answered ``429`` for a while):

- ``POST /rpc``: JSON-RPC 2.0 (the same envelope as the app's backend) with the methods
  ``office/info`` -> ``{server, version, steps, busy}``; ``office/createJob`` ``{name?, steps?}``
  -> ``{jobId, uploadPath}``; ``office/startJob`` ``{jobId}``; ``office/status`` ``{jobId}`` ->
  ``{state, step?, log, result?, error?}`` (``waitingForUpload``, ``queued``, ``running``,
  ``done``, ``failed``, ``cancelled``); ``office/cancel`` and ``office/deleteJob`` ``{jobId}``;
  ``office/listJobs``;
- ``PUT /jobs/<id>/archive``: the project as a ``.civil`` archive (:mod:`saengine.project.archive`,
  without results, versions or exports), at most ``--max-upload`` MB;
- ``GET /jobs/<id>/results``: a zip of the files the run wrote (each file changed since the job
  started), for :mod:`saengine.office.client` to put back.

Each job's project is extracted into ``<workspace>/<job id>/`` (checked by the archive reader:
paths, sizes, checksums) and run by ``python -m saengine.cli run-all`` in a process of its own
(so a cancel stops it); at most ``--workers`` jobs run at once, the others wait. Finished jobs
are deleted after ``--keep-days``.

Security (owner decisions, ``docs/engineering-decisions.md``): it listens on 127.0.0.1 unless
``--host`` says otherwise; on any other address without ``--certfile``/``--keyfile`` (TLS) it
warns that the token and the project travel unencrypted on the office network. The token is
compared in constant time; there is no other way in, no shell, and only the methods above.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import ssl
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

CONFIG_FILE = "office-server.json"
DEFAULT_PORT = 8737
#: The Run All steps a job may ask for (no drawings: they take long and are a deliverable).
ALLOWED_STEPS = (
    "bim",
    "derive",
    "analysis",
    "ssi",
    "substructure",
    "design",
    "mep",
    "boq",
    "report",
)
DEFAULT_STEPS = ("bim", "derive", "analysis", "ssi", "substructure", "design")
#: Failed authentications from one address before it is refused for :data:`LOCKOUT` seconds.
MAX_FAILURES = 5
LOCKOUT = 60.0
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def load_or_create_token(workspace: Path, renew: bool = False) -> tuple[str, str | None]:
    """The stored token hash, and the new token when one was made (shown once)."""
    workspace.mkdir(parents=True, exist_ok=True)
    config = workspace / CONFIG_FILE
    if not renew:
        try:
            stored = json.loads(config.read_text("utf-8")).get("tokenSha256")
            if isinstance(stored, str) and len(stored) == 64:
                return stored, None
        except (OSError, ValueError, AttributeError):
            pass
    token = new_token()
    digest = hash_token(token)
    config.write_text(json.dumps({"tokenSha256": digest}, indent="\t") + "\n", "utf-8")
    return digest, token


@dataclass
class Job:
    id: str
    name: str
    steps: list[str]
    folder: Path
    created: float = field(default_factory=time.time)
    state: str = "waitingForUpload"
    started: float | None = None
    finished: float | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    log: list[str] = field(default_factory=list)
    process: subprocess.Popen[str] | None = None
    root: Path | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "jobId": self.id,
            "name": self.name,
            "steps": self.steps,
            "state": self.state,
            "created": self.created,
            "started": self.started,
            "finished": self.finished,
            "error": self.error,
            "result": self.result,
            "log": self.log[-50:],
        }


class OfficeServer:
    """The jobs and their workers (no HTTP here: :class:`_Handler` calls :meth:`call`)."""

    def __init__(
        self,
        workspace: Path,
        token_sha256: str,
        *,
        workers: int = 1,
        max_upload_mb: int = 512,
        keep_days: float = 7.0,
        python: str | None = None,
    ) -> None:
        self.workspace = workspace
        self.token_sha256 = token_sha256
        self.workers = max(1, workers)
        self.max_upload = max_upload_mb * 1024 * 1024
        self.keep_days = keep_days
        self.python = python or sys.executable
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.queue: list[str] = []
        self.running = 0
        self.failures: dict[str, list[float]] = {}

    # ── authentication ──

    def authorised(self, header: str | None, address: str) -> str:
        """``ok``, ``refused`` (a wrong or missing token) or ``locked`` (too many failures)."""
        now = time.monotonic()
        with self.lock:
            recent = [t for t in self.failures.get(address, []) if now - t < LOCKOUT]
            self.failures[address] = recent
            if len(recent) >= MAX_FAILURES:
                return "locked"
        token = ""
        if header and header.lower().startswith("bearer "):
            token = header[7:].strip()
        if token and hmac.compare_digest(hash_token(token), self.token_sha256):
            return "ok"
        with self.lock:
            self.failures.setdefault(address, []).append(now)
        return "refused"

    # ── methods ──

    def call(self, method: str, params: dict[str, Any]) -> Any:
        if method == "office/info":
            from saengine import __version__

            with self.lock:
                busy = self.running
            return {
                "server": "SAEngine office server",
                "version": __version__,
                "steps": list(ALLOWED_STEPS),
                "busy": busy,
                "workers": self.workers,
            }
        if method == "office/createJob":
            return self.create(params)
        if method == "office/listJobs":
            with self.lock:
                return {"jobs": [j.to_json() for j in self.jobs.values()]}
        job = self.job(params.get("jobId"))
        if method == "office/startJob":
            return self.start(job)
        if method == "office/status":
            return job.to_json()
        if method == "office/cancel":
            return self.cancel(job)
        if method == "office/deleteJob":
            self.cancel(job)
            with self.lock:
                self.jobs.pop(job.id, None)
            shutil.rmtree(job.folder, ignore_errors=True)
            return {"deleted": job.id}
        raise LookupError(f"unknown method {method}")

    def job(self, job_id: Any) -> Job:
        if not isinstance(job_id, str) or not _JOB_ID.match(job_id):
            raise ValueError("jobId: not a job id")
        with self.lock:
            job = self.jobs.get(job_id)
        if job is None:
            raise LookupError(f"no job {job_id}")
        return job

    def create(self, params: dict[str, Any]) -> dict[str, Any]:
        self.sweep()
        steps = params.get("steps") or list(DEFAULT_STEPS)
        if not isinstance(steps, list) or any(s not in ALLOWED_STEPS for s in steps):
            raise ValueError(f"steps: each one of {', '.join(ALLOWED_STEPS)}")
        name = (
            re.sub(r"[^\w .-]+", "-", str(params.get("name") or "project"))[:80].strip()
            or "project"
        )
        job_id = uuid.uuid4().hex
        folder = self.workspace / job_id
        folder.mkdir(parents=True)
        job = Job(job_id, name, list(steps), folder)
        with self.lock:
            self.jobs[job_id] = job
        return {"jobId": job_id, "uploadPath": f"/jobs/{job_id}/archive"}

    def receive(self, job: Job, stream: Any, length: int) -> dict[str, Any]:
        """The archive of ``job`` from ``stream`` (``length`` bytes), checked and extracted."""
        if job.state != "waitingForUpload":
            raise ValueError("the job has its project already")
        if length <= 0 or length > self.max_upload:
            raise ValueError(f"the archive must be 1 byte to {self.max_upload // (1024 * 1024)} MB")
        target = job.folder / "upload.civil"
        remaining = length
        with target.open("wb") as out:
            while remaining > 0:
                chunk = stream.read(min(1 << 20, remaining))
                if not chunk:
                    raise ValueError("the upload ended early")
                out.write(chunk)
                remaining -= len(chunk)
        from saengine.project.archive import import_project

        try:
            imported = import_project(
                target, job.folder, name="project", overwrite=True, migrate=True
            )
        except Exception as error:
            raise ValueError(f"the archive was refused: {error}") from error
        job.root = Path(imported["root"])
        job.state = "uploaded"
        with contextlib.suppress(OSError):
            target.unlink()
        return {
            "jobId": job.id,
            "files": imported.get("files"),
            "problems": imported.get("problems"),
        }

    def start(self, job: Job) -> dict[str, Any]:
        if job.state != "uploaded":
            raise ValueError(f"the job cannot start ({job.state})")
        with self.lock:
            job.state = "queued"
            self.queue.append(job.id)
        self._next()
        return job.to_json()

    def _next(self) -> None:
        with self.lock:
            if self.running >= self.workers or not self.queue:
                return
            job = self.jobs.get(self.queue.pop(0))
            if job is None or job.state != "queued":
                return
            self.running += 1
            job.state = "running"
            job.started = time.time()
        threading.Thread(
            target=self._run, args=(job,), name=f"office-job-{job.id[:8]}", daemon=True
        ).start()

    def _run(self, job: Job) -> None:
        try:
            command = [
                self.python,
                "-m",
                "saengine.cli",
                "run-all",
                str(job.root),
                "--steps",
                *job.steps,
                "--json",
            ]
            job.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=os.environ.copy(),
            )

            def read_progress() -> None:
                assert job.process is not None and job.process.stderr is not None
                for line in job.process.stderr:
                    job.log.append(line.rstrip())
                    if len(job.log) > 500:
                        del job.log[:100]

            reader = threading.Thread(target=read_progress, daemon=True)
            reader.start()
            stdout, _ = job.process.communicate()
            reader.join(timeout=5)
            if job.state == "cancelled":
                return
            try:
                job.result = json.loads(stdout) if stdout.strip() else None
            except ValueError:
                job.result = {"output": stdout[-4000:]}
            code = job.process.returncode
            # Exit 1 is "checks fail": the run worked, its results say what fails.
            job.state = "done" if code in (0, 1) else "failed"
            if code not in (0, 1):
                job.error = f"Run All stopped (exit {code})"
        except OSError as error:
            job.state, job.error = "failed", str(error)
        finally:
            job.finished = time.time()
            with self.lock:
                self.running -= 1
            self._next()

    def cancel(self, job: Job) -> dict[str, Any]:
        with self.lock:
            if job.id in self.queue:
                self.queue.remove(job.id)
            if job.state in ("queued", "running", "uploaded", "waitingForUpload"):
                job.state = "cancelled"
        if job.process is not None and job.process.poll() is None:
            job.process.kill()
        return job.to_json()

    def results_zip(self, job: Job) -> Path:
        """A zip of the files the run wrote (changed since it started), paths relative to the
        project."""
        if job.state != "done" or job.root is None or job.started is None:
            raise ValueError(f"the job has no results ({job.state})")
        target = job.folder / "results.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
            for path in sorted(job.root.rglob("*")):
                if not path.is_file() or ".git" in path.relative_to(job.root).parts:
                    continue
                if path.stat().st_mtime + 1 >= job.started:
                    out.write(path, path.relative_to(job.root).as_posix())
        return target

    def sweep(self) -> None:
        """Deletes the jobs finished more than ``keep_days`` ago."""
        limit = time.time() - self.keep_days * 86400
        with self.lock:
            old = [j for j in self.jobs.values() if j.finished and j.finished < limit]
            for j in old:
                self.jobs.pop(j.id, None)
        for j in old:
            shutil.rmtree(j.folder, ignore_errors=True)


class _Handler(BaseHTTPRequestHandler):
    server_version = "SAEngineOffice/1"
    office: OfficeServer  # set on the subclass made by :func:`make_server`

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(f"{self.address_string()} {format % args}\n")

    def _json(self, status: int, value: Any, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _guard(self) -> bool:
        verdict = self.office.authorised(self.headers.get("Authorization"), self.client_address[0])
        if verdict == "ok":
            return True
        if verdict == "locked":
            self._json(
                HTTPStatus.TOO_MANY_REQUESTS,
                {"error": "too many failed attempts"},
                {"Retry-After": str(int(LOCKOUT))},
            )
        else:
            self._json(
                HTTPStatus.UNAUTHORIZED,
                {"error": "unauthorized"},
                {"WWW-Authenticate": 'Bearer realm="saengine-office"'},
            )
        # A refused request's body is never kept: a small one is read and dropped (so the
        # client gets the answer rather than a reset connection), a large one is not read.
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if 0 < length <= 64 * 1024:
            self.rfile.read(length)
        self.close_connection = True
        return False

    def _job_path(self) -> tuple[str, str] | None:
        m = re.fullmatch(r"/jobs/([0-9a-f]{32})/(archive|results)", self.path.split("?")[0])
        return (m.group(1), m.group(2)) if m else None

    def do_POST(self) -> None:
        if not self._guard():
            return
        if self.path.split("?")[0] != "/rpc":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 1024 * 1024:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "a JSON-RPC request of at most 1 MB"})
            return
        request_id = None
        try:
            request = json.loads(self.rfile.read(length))
            request_id = request.get("id")
            method = request.get("method")
            params = request.get("params") or {}
            if not isinstance(method, str) or not isinstance(params, dict):
                raise TypeError("method and params")
            result = self.office.call(method, params)
            self._json(HTTPStatus.OK, {"jsonrpc": "2.0", "id": request_id, "result": result})
        except LookupError as error:
            self._json(
                HTTPStatus.OK,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": str(error)},
                },
            )
        except (ValueError, TypeError, AttributeError) as error:
            self._json(
                HTTPStatus.OK,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32602, "message": str(error)},
                },
            )

    def do_PUT(self) -> None:
        if not self._guard():
            return
        target = self._job_path()
        if target is None or target[1] != "archive":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            job = self.office.job(target[0])
            answer = self.office.receive(
                job, self.rfile, int(self.headers.get("Content-Length") or 0)
            )
            self._json(HTTPStatus.OK, answer)
        except LookupError as error:
            self._json(HTTPStatus.NOT_FOUND, {"error": str(error)})
        except ValueError as error:
            self.close_connection = True
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def do_GET(self) -> None:
        if not self._guard():
            return
        target = self._job_path()
        if target is None or target[1] != "results":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            path = self.office.results_zip(self.office.job(target[0]))
        except LookupError as error:
            self._json(HTTPStatus.NOT_FOUND, {"error": str(error)})
            return
        except ValueError as error:
            self._json(HTTPStatus.CONFLICT, {"error": str(error)})
            return
        size = path.stat().st_size
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with path.open("rb") as data:
            shutil.copyfileobj(data, self.wfile)


def make_server(
    office: OfficeServer,
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    certfile: str | None = None,
    keyfile: str | None = None,
) -> ThreadingHTTPServer:
    handler = type("OfficeHandler", (_Handler,), {"office": office})
    httpd = ThreadingHTTPServer((host, port), handler)
    if certfile:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile, keyfile)
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    return httpd


def is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "::1", "localhost")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="saengine office-server",
        description="Run analyses for the office's engineers (opt-in; see docs/office-server.md).",
    )
    parser.add_argument("--workspace", required=True, help="the folder the jobs' projects go to")
    parser.add_argument(
        "--host", default="127.0.0.1", help="address to listen on (default: this machine only)"
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--workers", type=int, default=1, help="jobs run at once")
    parser.add_argument("--max-upload", type=int, default=512, help="largest project archive [MB]")
    parser.add_argument("--keep-days", type=float, default=7.0, help="days finished jobs are kept")
    parser.add_argument("--certfile", help="TLS certificate (PEM): serve HTTPS")
    parser.add_argument("--keyfile", help="the certificate's private key (PEM)")
    parser.add_argument(
        "--new-token", action="store_true", help="make a new token (the old one stops working)"
    )
    args = parser.parse_args(argv)
    workspace = Path(args.workspace).resolve()
    digest, token = load_or_create_token(workspace, renew=args.new_token)
    if token:
        print("The office server's token (shown once; give it to the engineers):", file=sys.stderr)
        print(token)
    if not is_loopback(args.host) and not args.certfile:
        print(
            "WARNING: listening on the network without TLS (--certfile/--keyfile): the token and "
            "the projects travel unencrypted on the office network.",
            file=sys.stderr,
        )
    office = OfficeServer(
        workspace,
        digest,
        workers=args.workers,
        max_upload_mb=args.max_upload,
        keep_days=args.keep_days,
    )
    httpd = make_server(office, args.host, args.port, args.certfile, args.keyfile)
    scheme = "https" if args.certfile else "http"
    print(
        f"SAEngine office server on {scheme}://{args.host}:{args.port} (workspace {workspace})",
        file=sys.stderr,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

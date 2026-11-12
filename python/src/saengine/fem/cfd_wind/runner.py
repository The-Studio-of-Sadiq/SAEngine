"""The CFD wind tunnel's background run (alpha 9 L3): a separate process, so a run of hours
neither holds the app's engine nor stops when the app closes.

``python -m saengine.fem.cfd_wind.runner <cases folder>`` runs the plan the app wrote
(``plan.json``: the directions, the installation, the envelope) one case after the other:
blockMesh, snappyHexMesh, the initial fields copied, the steady solver (decomposed with mpirun
when the settings ask for more than one process and the installation has MPI), then the
post-processing (:mod:`.post`) whose coefficients go into the results file as each direction
finishes. A failing direction is reported and the next one runs.

It reports in ``status.json`` (its state, each direction's step and iteration, a heartbeat);
:func:`status` reads it for the app (with the progress, and "stopped" when the heartbeat is
old: the computer slept or the process was killed). :func:`cancel` asks it to stop (the file
``cancel``): it stops the running OpenFOAM program and leaves.

Nothing starts by itself: only :func:`start`, which the app calls when the user presses Run.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from saengine.fem.cfd_wind import openfoam, post
from saengine.fem.cfd_wind.openfoam import Installation

PLAN = "plan.json"
STATUS = "status.json"
CANCEL = "cancel"
RUN_LOG = "run.log"
#: The runner writes its status at least this often [s].
HEARTBEAT = 5.0
#: A running status older than this is a run that stopped [s].
STALE = 120.0
#: How the progress of a direction is shared among its steps (share at the step's start).
STEP_SHARE = {
    "waiting": 0.0,
    "blockMesh": 0.02,
    "snappyHexMesh": 0.05,
    "decomposePar": 0.2,
    "solver": 0.2,
    "reconstructPar": 0.95,
    "post": 0.97,
}
_TIME = re.compile(rb"^Time = ([0-9.eE+-]+)s?\s*$", re.MULTILINE)
_RESIDUAL = re.compile(rb"Solving for p, Initial residual = ([0-9.eE+-]+)")


# ─────────────────────────────────────── status file ───────────────────────────────────────


def _write(path: Path, data: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def progress(data: dict[str, Any]) -> float:
    """The run's share done (0-1) from its status."""
    directions = data.get("directions") or []
    if not directions:
        return 0.0
    total = 0.0
    for d in directions:
        state = d.get("state")
        if state in ("done", "failed", "cancelled", "skipped"):
            total += 1.0
            continue
        step = d.get("step") or "waiting"
        share = STEP_SHARE.get(step, 0.0)
        if step == "solver" and d.get("iterations"):
            share += 0.75 * min(1.0, float(d.get("iteration") or 0) / float(d["iterations"]))
        total += share
    return total / len(directions)


def status(cases: Path) -> dict[str, Any]:
    """The run's status for the app: ``{state, progress, directions, message, ...}``;
    ``state`` "none" when no run was started, "stopped" for a run whose runner is gone."""
    data = _read(cases / STATUS)
    if data is None:
        return {"state": "none", "progress": 0.0, "directions": []}
    if data.get("state") in ("starting", "running"):
        age = time.time() - float(data.get("updated") or 0)
        if age > STALE:
            data["state"] = "stopped"
            data["message"] = (
                "the run stopped without finishing (the computer slept, or its process was "
                "ended); run it again"
            )
    data["progress"] = progress(data)
    return data


def running(cases: Path) -> bool:
    return status(cases).get("state") in ("starting", "running")


def cancel(cases: Path) -> dict[str, Any]:
    """Asks the run to stop; a run whose runner is gone is marked cancelled at once."""
    data = status(cases)
    if data.get("state") in ("starting", "running"):
        (cases / CANCEL).write_text("cancel\n", encoding="utf-8")
        return {"ok": True, "state": "cancelling"}
    if data.get("state") == "stopped":
        raw = _read(cases / STATUS) or {}
        raw["state"] = "cancelled"
        raw["updated"] = time.time()
        _write(cases / STATUS, raw)
    return {"ok": True, "state": data.get("state")}


def start(cases: Path) -> dict[str, Any]:
    """Starts the runner on the plan in ``cases`` as its own process; refuses while a run is
    on."""
    if running(cases):
        return {"ok": False, "message": "a CFD run is already running"}
    plan = _read(cases / PLAN)
    if plan is None:
        return {"ok": False, "message": "no plan: write the cases first"}
    (cases / CANCEL).unlink(missing_ok=True)
    _write(
        cases / STATUS,
        {
            "state": "starting",
            "started": time.time(),
            "updated": time.time(),
            "directions": [
                {"angle": a, "case": c, "state": "waiting", "step": "waiting"}
                for a, c in zip(plan["directions"], plan["cases"], strict=True)
            ],
        },
    )
    command = [sys.executable, "-m", "saengine.fem.cfd_wind.runner", str(cases)]
    kwargs: dict[str, Any] = {
        "cwd": str(cases),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": os.environ.copy(),
        "close_fds": True,
    }
    if os.name == "nt":
        base = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:  # out of the app's job, so closing the app does not end the run
            proc = subprocess.Popen(
                command, creationflags=base | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kwargs
            )
        except OSError:
            proc = subprocess.Popen(command, creationflags=base, **kwargs)
    else:
        proc = subprocess.Popen(command, start_new_session=True, **kwargs)
    return {"ok": True, "pid": proc.pid}


# ─────────────────────────────────────────── the run ───────────────────────────────────────────


class _Cancelled(Exception):
    pass


class _Run:
    def __init__(self, cases: Path) -> None:
        self.cases = cases
        self.plan = _read(cases / PLAN) or {}
        self.inst = Installation.from_json(self.plan.get("installation") or {})
        self.data = _read(cases / STATUS) or {}
        self.data.setdefault(
            "directions",
            [
                {"angle": a, "case": c, "state": "waiting", "step": "waiting"}
                for a, c in zip(self.plan["directions"], self.plan["cases"], strict=True)
            ],
        )
        self.data.update(state="running", pid=os.getpid())
        self.last = 0.0
        self.log = (cases / RUN_LOG).open("a", encoding="utf-8")

    def note(self, text: str) -> None:
        self.log.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
        self.log.flush()

    def save(self, force: bool = False) -> None:
        now = time.time()
        if force or now - self.last >= 1.0:
            self.data["updated"] = now
            _write(self.cases / STATUS, self.data)
            self.last = now

    def cancelled(self) -> bool:
        return (self.cases / CANCEL).exists()

    def step(self, entry: dict[str, Any], case: Path, name: str, argv: list[str]) -> None:
        """Runs one OpenFOAM program in ``case``; raises on failure or cancel."""
        entry["step"] = name
        entry["message"] = None
        self.save(force=True)
        program = argv[3] if argv[0] == "mpirun" else argv[0]  # mpirun -np N <program> ...
        log = f"log.{program}"
        script = case / ".sae-step.sh"
        script.write_text(
            openfoam.step_script(case, self.inst, argv, log), encoding="utf-8", newline="\n"
        )
        (case / ".sae-step.pid").unlink(missing_ok=True)
        command = openfoam.bash_command(script, self.inst.mode, self.inst.distribution)
        self.note(f"{entry['case']}: {' '.join(argv)}")
        proc = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **openfoam.process_flags(),
        )
        while proc.poll() is None:
            if self.cancelled():
                self._stop(proc, case)
                raise _Cancelled
            if name == "solver":
                entry["iteration"] = _last_time(case / log)
            self.save()
            time.sleep(1.0)
        if name == "solver":
            entry["iteration"] = _last_time(case / log)
        if proc.returncode != 0:
            raise RuntimeError(f"{program} failed (exit {proc.returncode}): {_error(case / log)}")

    def _stop(self, proc: subprocess.Popen, case: Path) -> None:
        try:
            pid = int((case / ".sae-step.pid").read_text().strip())
        except (OSError, ValueError):
            pid = None
        if pid is not None:
            command = openfoam.stop_command(self.inst, pid)
            try:
                if command is not None:
                    subprocess.run(command, timeout=30, check=False, **openfoam.process_flags())
                elif hasattr(os, "killpg"):
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (OSError, subprocess.SubprocessError):
                pass
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()

    def direction(self, entry: dict[str, Any]) -> None:
        case = self.cases / entry["case"]
        options = self.plan["settings"]
        entry.update(state="running", started=time.time(), iterations=options["iterations"])
        self.step(entry, case, "blockMesh", ["blockMesh"])
        self.step(entry, case, "snappyHexMesh", ["snappyHexMesh", "-overwrite"])
        target = case / "0"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(case / "0.orig", target)
        processors = int(options.get("processors") or 1)
        parallel = processors > 1 and self.inst.parallel
        if parallel:
            self.step(entry, case, "decomposePar", ["decomposePar", "-force"])
        self.step(entry, case, "solver", openfoam.solver_argv(self.inst, parallel, processors))
        if parallel:
            self.step(entry, case, "reconstructPar", ["reconstructPar", "-latestTime"])
        entry["step"] = "post"
        self.save(force=True)
        log = case / f"log.{'foamRun' if self.inst.solver == 'foamRun' else 'simpleFoam'}"
        converged, residual = _convergence(log)
        surface = post.read_surface(case)
        envelope = self.plan["envelope"]
        result = post.evaluate(
            surface,
            angle=float(entry["angle"]),
            levels=[z - envelope["base_m"] for z in envelope["levels_m"]],
            base=float(envelope["base_m"]),
            uref=float(self.plan["reference"]["uref"]),
        )
        result.update(
            converged=converged,
            residual=residual,
            iterations=entry.get("iteration"),
            case=entry["case"],
        )
        post.store_direction(Path(self.plan["results"]), result)
        entry.update(state="done", step="done", finished=time.time())
        if not converged:
            entry["message"] = (
                f"not converged in {options['iterations']} iterations (p residual "
                f"{residual if residual is not None else '?'}): check the case before using it"
            )

    def run(self) -> None:
        self.note(f"run started (pid {os.getpid()})")
        self.save(force=True)
        failures = 0
        try:
            for entry in self.data["directions"]:
                if entry.get("state") == "done":
                    continue
                if self.cancelled():
                    raise _Cancelled
                try:
                    self.direction(entry)
                except _Cancelled:
                    raise
                except Exception as error:  # noqa: BLE001 - the next direction still runs
                    failures += 1
                    entry.update(state="failed", message=str(error), finished=time.time())
                    self.note(f"{entry['case']} failed: {error}\n{traceback.format_exc()}")
                self.save(force=True)
            done = len(self.data["directions"]) - failures
            self.data["state"] = "done" if done else "failed"
            self.data["message"] = f"{done} of {len(self.data['directions'])} directions done" + (
                f", {failures} failed (see each case's log)" if failures else ""
            )
            post.finish_results(Path(self.plan["results"]), complete=failures == 0)
        except _Cancelled:
            for entry in self.data["directions"]:
                if entry.get("state") in ("waiting", "running"):
                    entry["state"] = "cancelled"
            self.data["state"] = "cancelled"
            self.data["message"] = "cancelled"
            post.finish_results(Path(self.plan["results"]), complete=False)
        except Exception as error:  # noqa: BLE001 - reported in the status
            self.data["state"] = "failed"
            self.data["message"] = str(error)
            self.note(traceback.format_exc())
        finally:
            (self.cases / CANCEL).unlink(missing_ok=True)
            self.data["finished"] = time.time()
            self.save(force=True)
            self.note(f"run ended: {self.data.get('state')}")
            self.log.close()


def _tail(path: Path, size: int = 65536) -> bytes:
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            f.seek(max(0, end - size))
            return f.read()
    except OSError:
        return b""


def _last_time(log: Path) -> int | None:
    found = _TIME.findall(_tail(log))
    try:
        return int(float(found[-1])) if found else None
    except ValueError:
        return None


def _convergence(log: Path) -> tuple[bool, float | None]:
    """Whether the solver met its residuals (SIMPLE / PIMPLE "converged in") and the last
    pressure residual."""
    tail = _tail(log, 262144)
    found = _RESIDUAL.findall(tail)
    residual = float(found[-1]) if found else None
    return b"converged in" in tail, residual


def _error(log: Path) -> str:
    """The FATAL ERROR's lines of a failed program's log, else its last lines."""
    text = _tail(log).decode("utf-8", errors="replace")
    at = text.find("FATAL")
    lines = (text[at:] if at >= 0 else text).strip().splitlines()
    return " ".join(line.strip() for line in lines[:8] if line.strip())[:600] or "see its log"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m saengine.fem.cfd_wind.runner <cases folder>", file=sys.stderr)
        return 2
    _Run(Path(args[0])).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Analysis CLI: ``python -m opensees_studio.run --project P --cases IDS --out DIR``.

The GUI runs every analysis through this entry point in a child process
(``QProcess``), so a hard exit inside OpenSees cannot take the
application down. The script loads the project (normally the pre-run
snapshot), runs the requested cases with the ordinary
:class:`~opensees_studio.services.opensees_runner.OpenSeesRunner`, writes
each case's results to ``DIR`` through
:mod:`~opensees_studio.services.result_store` and finishes with
``DIR/manifest.json``.

Progress protocol (stdout, one JSON object per line, flushed per line):

- ``{"type": "log", "message": str}``
- ``{"type": "case_started", "case_id": int, "case_type": str, "case_name": str}``
- ``{"type": "progress", "case_id": int, "step": int, "total": int}``
- ``{"type": "case_finished", "case_id": int, "result_type": str, "files": [...],
  "completed_steps": int | null, "early_stop": bool, "warnings": [...]}``
- ``{"type": "error", "message": str, "traceback": str}``

Everything OpenSees itself prints goes to stderr: file descriptor 1 is
redirected to 2 right at start and the protocol writes to a private copy
of the original stdout, so native output can never corrupt a line.

Exit codes:

- 0: every case ran (an early stop is a result, not an error);
- 2: a Python-side analysis error, reported in an ``error`` line;
- 3: the project is invalid or a reference does not resolve;
- anything else: the process died (a hard exit inside OpenSees, a signal).

Eigen determinism: ARPACK keeps its start vector across ``eigen`` calls,
so only the first eigen call of a process is reproducible. Once an eigen
call has happened in this process, every later case whose routed solver
is ARPACK (see ``core.modal.resolve_modal_solver``) runs in a fresh child
``python -m opensees_studio.run`` with the same project, output directory
and override file; its protocol lines are relayed and its manifest entry
merged, so the caller sees one run. Dense (``fullGenLapack``) cases are
direct solves and run in place.

Shared modal results: a response spectrum case whose modal case ran (or
was kept) in the same run combines that case's modes instead of solving
the eigenproblem again; the results are the same as the modal case's own
first eigen call, so RX and RY of one modal case cost one eigen solve.

Parallel runs (``--jobs N``, ``OPENSEES_STUDIO_JOBS``, automatic on models
of :data:`PARALLEL_MIN_NODES` nodes or more): the cases are cut into units
(:func:`run_units`: a modal case with its response spectrum cases, a cut of
the linear static cases of one solver setting, any other case alone), each
run by a child ``python -m opensees_studio.run`` writing its own
``manifest.part-<k>.json``; their protocol lines are relayed as they come,
and one ``manifest.json`` in the requested order is written at the end.

Selective reruns (``--reuse``): each case's stamp (:func:`case_stamps`: the
model without its meta and cases, and the case with its preloads and modal
case) is kept in ``case-stamps.json``. The next run with ``--reuse`` keeps
the results of the cases whose stamp did not change (reporting them as
started and finished), removes everything else in ``--out``, and runs only
the other cases.

``OPENSEES_STUDIO_CLI_HARD_EXIT_AFTER=N`` (tests only) makes the process
leave with ``os._exit(255)`` after the N-th progress line, imitating a
solver hard exit.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

MANIFEST_FILE = "manifest.json"
EXIT_OK = 0
EXIT_ANALYSIS_ERROR = 2
EXIT_INVALID_PROJECT = 3
HARD_EXIT_ENV = "OPENSEES_STUDIO_CLI_HARD_EXIT_AFTER"


class _Protocol:
    """Writes protocol lines to the original stdout, one JSON object per line."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self.progress_lines = 0
        limit = os.environ.get(HARD_EXIT_ENV)
        self._hard_exit_after = int(limit) if limit else None

    def emit(self, **payload: Any) -> None:
        self._stream.write(json.dumps(payload) + "\n")
        self._stream.flush()
        if payload.get("type") == "progress":
            self.progress_lines += 1
            if self._hard_exit_after is not None and self.progress_lines >= self._hard_exit_after:
                self._stream.flush()
                sys.stderr.flush()
                os._exit(255)

    def log(self, message: str) -> None:
        self.emit(type="log", message=message)


def _claim_stdout() -> Any:
    """Return a private text stream on the original stdout and send fd 1 to stderr."""
    protocol_fd = os.dup(1)
    os.dup2(2, 1)
    stream = os.fdopen(protocol_fd, "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr
    return stream


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m opensees_studio.run",
        description="Run analysis cases of an OpenSees Studio project and write the results.",
    )
    parser.add_argument(
        "--project", required=True, help="project file (.osmodel), usually the pre-run snapshot"
    )
    parser.add_argument(
        "--cases",
        required=True,
        type=int,
        nargs="+",
        metavar="ID",
        help="case ids to run, in order",
    )
    parser.add_argument(
        "--out", required=True, help="output directory for results and manifest.json"
    )
    parser.add_argument(
        "--case-override",
        default=None,
        help="JSON file with a list of case objects that replace the same-id cases for this run",
    )
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="keep the results in --out of the cases whose model and definition did not change "
        f"({STAMPS_NAME}), remove the rest of the earlier run, and run only the other cases",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=None,
        metavar="N",
        help=f"processes to run the cases in (default: ${JOBS_ENV}, else up to {MAX_AUTO_JOBS} "
        f"on models of {PARALLEL_MIN_NODES} nodes or more, else 1)",
    )
    # Internal: the parallel run's and the fresh eigen processes' own manifests and the modal
    # results handed to them.
    parser.add_argument("--manifest-name", default=MANIFEST_FILE, help=argparse.SUPPRESS)
    parser.add_argument("--known-modal", default=None, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def _throttled(protocol: _Protocol, case_id: int) -> Any:
    """Progress callback emitting at most about 100 lines per case plus the last step."""
    last_emitted = {"step": -1}

    def on_progress(step: int, total: int) -> None:
        stride = max(1, total // 100)
        if (step == total or step % stride == 0) and step != last_emitted["step"]:
            last_emitted["step"] = step
            protocol.emit(type="progress", case_id=case_id, step=step, total=total)

    return on_progress


def _uses_eigen(case: Any) -> bool:
    """True when running ``case`` calls ``ops.eigen`` at least once."""
    from opensees_studio.core import ModalCase, ResponseSpectrumCase, TransientCase

    if isinstance(case, ModalCase | ResponseSpectrumCase):
        return True
    return isinstance(case, TransientCase) and case.rayleigh_mode1_damping is not None


def _routed_to_arpack(project: Any, case: Any) -> bool:
    """True when ``case`` would run its eigen analysis with ARPACK."""
    from opensees_studio.core import ModalCase, ResponseSpectrumCase
    from opensees_studio.core.modal import (
        SOLVER_ARPACK,
        free_dof_count,
        mass_dof_bound,
        resolve_modal_solver,
    )

    modal = case
    if isinstance(case, ResponseSpectrumCase):
        modal = next(
            (
                c
                for c in project.analyses
                if isinstance(c, ModalCase) and c.id == case.modal_case_id
            ),
            None,
        )
    if not isinstance(modal, ModalCase):
        return False
    try:
        solver, _reason = resolve_modal_solver(
            modal.solver, free_dof_count(project), modal.n_modes, mass_dof_bound(project)
        )
    except ValueError:
        return False  # the runner reports the refusal itself
    return solver == SOLVER_ARPACK


def _run_in_fresh_process(
    protocol: _Protocol, args: argparse.Namespace, case: Any
) -> tuple[dict[str, Any] | None, int]:
    """Run one case in a child CLI, relaying its protocol lines.

    Returns ``(manifest entry or None, exit code)``. The child writes its
    result files into the same output directory and its own manifest under
    another name, removed once it ends.
    """
    cmd = [
        sys.executable,
        "-u",
        "-m",
        "opensees_studio.run",
        "--project",
        str(args.project),
        "--cases",
        str(case.id),
        "--out",
        str(args.out),
        "--manifest-name",
        f"manifest.case-{case.id}.json",
    ]
    if args.case_override:
        cmd += ["--case-override", str(args.case_override)]
    protocol.log(
        f"Case '{case.name}' uses ARPACK after an earlier eigen call: running it in a "
        "fresh process so its eigen call is the first of that process."
    )
    child = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, encoding="utf-8")
    entry: dict[str, Any] | None = None
    saw_error = False
    assert child.stdout is not None
    for line in child.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            protocol.log(line)
            continue
        kind = payload.get("type")
        if kind == "case_finished":
            entry = {k: v for k, v in payload.items() if k != "type"}
        elif kind == "error":
            saw_error = True
        protocol.emit(**payload)
    code = child.wait()
    (Path(args.out) / f"manifest.case-{case.id}.json").unlink(missing_ok=True)
    if code != EXIT_OK and not saw_error:
        protocol.emit(
            type="error",
            message=f"Fresh process for case '{case.name}' exited with code {code}.",
            traceback="",
        )
    if code != EXIT_OK:
        return None, EXIT_ANALYSIS_ERROR
    if entry is None:
        protocol.emit(
            type="error",
            message=f"Fresh process for case '{case.name}' finished without a result.",
            traceback="",
        )
        return None, EXIT_ANALYSIS_ERROR
    return entry, EXIT_OK


def _load_cases(args: argparse.Namespace, protocol: _Protocol) -> tuple[Any, list[Any]]:
    """The project (with the case overrides) and the requested cases, in order."""
    from opensees_studio.core import Project
    from opensees_studio.services.persistence import load_project

    project = load_project(args.project, on_notice=protocol.log)
    if args.case_override:
        overrides = json.loads(Path(args.case_override).read_text(encoding="utf-8"))
        by_id = {int(c["id"]): c for c in overrides}
        analyses = [by_id.get(c.id, c) for c in project.analyses]
        project = Project.model_validate(
            {
                **project.model_dump(mode="json", by_alias=True),
                "analyses": [
                    a if isinstance(a, dict) else a.model_dump(mode="json", by_alias=True)
                    for a in analyses
                ],
            }
        )
    project.validate_references()
    cases = []
    for cid in args.cases:
        case = next((c for c in project.analyses if c.id == cid), None)
        if case is None:
            raise ValueError(f"No analysis case with id {cid} in the project.")
        cases.append(case)
    return project, cases


# ─────────────────────── selective reruns ───────────────────────
#: Per-case stamps of the results in an output folder, written beside ``manifest.json``.
STAMPS_NAME = "case-stamps.json"
STAMPS_SCHEMA = 1


def case_stamps(project: Any, cases: list[Any]) -> dict[int, str]:
    """What each case's results are computed from: the model without its meta and analysis
    cases (nodes, elements, sections, masses, load patterns, spectra, ...) and the case with
    every case it runs first or reads (its preloads, a response spectrum's modal case). Two runs
    of a case with equal stamps give the same results."""
    import hashlib

    model = project.model_dump(mode="json", by_alias=True, exclude={"meta", "analyses"})
    base = hashlib.sha256(json.dumps(model, sort_keys=True).encode("utf-8")).hexdigest()
    by_id = {c.id: c for c in project.analyses}
    stamps: dict[int, str] = {}
    for case in cases:
        closure: dict[int, Any] = {}
        todo = [case.id]
        while todo:
            cid = todo.pop()
            if cid in closure or cid not in by_id:
                continue
            closure[cid] = by_id[cid]
            todo += list(getattr(closure[cid], "preload_case_ids", None) or [])
            modal = getattr(closure[cid], "modal_case_id", None)
            if modal is not None:
                todo.append(modal)
        dumped = [closure[cid].model_dump(mode="json", by_alias=True) for cid in sorted(closure)]
        text = json.dumps([base, case.id, dumped], sort_keys=True)
        stamps[case.id] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return stamps


def _reusable_entries(
    out_dir: Path, stamps: dict[int, str], manifest_name: str
) -> dict[int, dict[str, Any]]:
    """The manifest entries of ``out_dir`` computed from the same stamps as now, whose files
    are all still there (none when the folder holds no earlier run)."""
    try:
        manifest = json.loads((out_dir / manifest_name).read_text(encoding="utf-8"))
        kept = json.loads((out_dir / STAMPS_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(kept, dict) or kept.get("schema") != STAMPS_SCHEMA:
        return {}
    old = {int(k): v for k, v in (kept.get("cases") or {}).items()}
    entries: dict[int, dict[str, Any]] = {}
    for entry in manifest.get("cases", []):
        cid = int(entry.get("case_id", -1))
        if cid not in stamps or old.get(cid) != stamps[cid]:
            continue
        files = [out_dir / f for f in entry.get("files", [])]
        if files and all(f.is_file() for f in files):
            entries[cid] = entry
    return entries


def _clear_for_reuse(out_dir: Path, kept: dict[int, dict[str, Any]], manifest_name: str) -> None:
    """Removes everything an earlier run (and its readers' caches) left in ``out_dir`` except
    the files of the ``kept`` entries, as a fresh run into an emptied folder would; only when
    the folder holds a run (its manifest)."""
    import shutil

    if not (out_dir / manifest_name).is_file():
        return
    keep = {(out_dir / f).resolve() for e in kept.values() for f in e.get("files", [])}
    for item in out_dir.iterdir():
        if item.resolve() in keep:
            continue
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)


def _write_stamps(out_dir: Path, stamps: dict[int, str], entries: list[dict[str, Any]]) -> None:
    done = {int(e["case_id"]) for e in entries}
    payload = {
        "schema": STAMPS_SCHEMA,
        "cases": {str(cid): s for cid, s in stamps.items() if cid in done},
    }
    (out_dir / STAMPS_NAME).write_text(json.dumps(payload, indent=1), encoding="utf-8")


# ─────────────────────── modal results shared by response spectrum cases ───────────────────────
#: The file handing kept modal cases' manifest entries to the parallel run's processes.
KNOWN_MODAL_NAME = ".known-modal.json"


def _shareable_modal(case: Any) -> bool:
    """A modal case whose results a response spectrum case may take as its own: it runs on the
    model's own sections, as a response spectrum case solves its modal case."""
    from opensees_studio.core import ModalCase

    return isinstance(case, ModalCase) and not case.section_overrides


def _takes_known_modal(case: Any, known: dict[int, Any]) -> bool:
    """A response spectrum case that combines modal results already at hand (no eigen call)."""
    from opensees_studio.core import ResponseSpectrumCase

    return (
        isinstance(case, ResponseSpectrumCase)
        and case.modal_case_id in known
        and not case.section_overrides
    )


def _load_known_modal(path: Path | None, out_dir: Path, cases: dict[int, Any]) -> dict[int, Any]:
    from opensees_studio.services.result_store import load_results

    if path is None or not path.is_file():
        return {}
    known: dict[int, Any] = {}
    for entry in json.loads(path.read_text(encoding="utf-8")):
        cid = int(entry["case_id"])
        if cid in cases and _shareable_modal(cases[cid]):
            known[cid] = load_results(entry, out_dir)
    return known


# ─────────────────────── parallel runs ───────────────────────
#: The automatic job count runs cases in parallel processes only from this many nodes up:
#: below it each process's start (about 10 s of imports) costs more than the cases.
PARALLEL_MIN_NODES = 1500
#: Most processes the automatic job count starts.
MAX_AUTO_JOBS = 4
JOBS_ENV = "OPENSEES_STUDIO_JOBS"
#: Fewest linear static cases a batch is cut into a unit of its own for.
MIN_BATCH_CHUNK = 3


def job_count(requested: int | None, n_nodes: int) -> int:
    """Processes to run the cases in: ``--jobs`` when given, else ``OPENSEES_STUDIO_JOBS``,
    else half the logical processors (at most :data:`MAX_AUTO_JOBS`) on a model of
    :data:`PARALLEL_MIN_NODES` nodes or more, and 1 below it."""
    if requested is not None and requested > 0:
        return requested
    env = os.environ.get(JOBS_ENV, "").strip()
    if env.isdigit() and int(env) > 0:
        return int(env)
    if n_nodes < PARALLEL_MIN_NODES:
        return 1
    return max(1, min(MAX_AUTO_JOBS, (os.cpu_count() or 2) // 2))


def run_units(planner: Any, cases: list[Any], jobs: int) -> list[list[Any]]:
    """The cases cut into units that run in a process each, the costliest first: a modal case
    with the response spectrum cases that combine its modes (one eigen solve for all), every
    other case that solves an eigenproblem or runs alone, then the linear static cases of one
    solver setting (one factorisation per unit, cut into up to ``jobs`` units)."""
    from opensees_studio.core import ModalCase, ResponseSpectrumCase

    modal_ids = {c.id for c in cases if _shareable_modal(c)}
    modal_units: dict[int, list[Any]] = {}
    batches: dict[Any, list[Any]] = {}
    eigen: list[list[Any]] = []
    single: list[list[Any]] = []
    for case in cases:
        if case.id in modal_ids:
            modal_units.setdefault(case.id, []).insert(0, case)
        elif (
            isinstance(case, ResponseSpectrumCase)
            and case.modal_case_id in modal_ids
            and not case.section_overrides
        ):
            modal_units.setdefault(case.modal_case_id, []).append(case)
        elif isinstance(case, ModalCase | ResponseSpectrumCase):
            eigen.append([case])
        elif (key := planner.batch_key(case)) is not None:
            batches.setdefault(key, []).append(case)
        else:
            single.append([case])
    units = list(modal_units.values()) + eigen + single
    for batch in batches.values():
        parts = max(1, min(jobs, len(batch) // MIN_BATCH_CHUNK))
        size = -(-len(batch) // parts)
        units += [batch[i : i + size] for i in range(0, len(batch), size)]
    return units


def _run_parallel(
    protocol: _Protocol,
    args: argparse.Namespace,
    units: list[list[Any]],
    jobs: int,
    known_modal: Path | None,
) -> tuple[dict[int, dict[str, Any]], int]:
    """Runs each unit in its own ``python -m opensees_studio.run`` (``jobs`` at a time),
    relaying their protocol lines. Returns the manifest entries by case id and the exit code;
    on the first failure the processes still running are stopped and no new one starts."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    lock = threading.Lock()
    entries: dict[int, dict[str, Any]] = {}
    failed: list[int] = []
    children: list[subprocess.Popen[str]] = []

    def run(index: int, unit: list[Any]) -> None:
        with lock:
            if failed:
                return
        manifest = f"manifest.part-{index}.json"
        cmd = [sys.executable, "-u", "-m", "opensees_studio.run", "--project", str(args.project)]
        cmd += ["--cases", *(str(c.id) for c in unit), "--out", str(args.out), "--jobs", "1"]
        cmd += ["--manifest-name", manifest]
        if args.case_override:
            cmd += ["--case-override", str(args.case_override)]
        if known_modal is not None:
            cmd += ["--known-modal", str(known_modal)]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        child = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, text=True, encoding="utf-8", creationflags=flags
        )
        with lock:
            children.append(child)
            if failed:  # a unit failed while this one started
                child.kill()
        saw_error = False
        assert child.stdout is not None
        for line in child.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                payload = {"type": "log", "message": line}
            kind = payload.get("type")
            with lock:
                if kind == "case_finished":
                    entries[int(payload["case_id"])] = {
                        k: v for k, v in payload.items() if k != "type"
                    }
                elif kind == "error":
                    saw_error = True
                protocol.emit(**payload)
        code = child.wait()
        (Path(args.out) / manifest).unlink(missing_ok=True)
        if code == EXIT_OK:
            return
        with lock:
            first = not failed
            failed.append(code)
            if not first:
                return  # stopped because another unit failed
            if not saw_error:
                names = ", ".join(f"'{c.name}'" for c in unit)
                protocol.emit(
                    type="error",
                    message=f"The process running {names} exited with code {code}.",
                    traceback="",
                )
            for other in children:
                if other is not child and other.poll() is None:
                    other.kill()

    protocol.log(f"Running {len(units)} groups of cases in up to {jobs} processes.")
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for future in [pool.submit(run, i, unit) for i, unit in enumerate(units)]:
            future.result()
    return entries, EXIT_ANALYSIS_ERROR if failed else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    protocol = _Protocol(_claim_stdout())
    args = _parse_args(argv)

    from opensees_studio.services.result_store import write_manifest, write_results

    out_dir = Path(args.out)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        project, cases = _load_cases(args, protocol)
    except Exception as exc:
        protocol.emit(type="error", message=str(exc), traceback=traceback.format_exc())
        return EXIT_INVALID_PROJECT

    from opensees_studio.services.opensees_runner import OpenSeesRunner
    from opensees_studio.services.results import eigen_solver_note

    manifest_name = args.manifest_name
    stamps = case_stamps(project, cases) if args.reuse else {}
    kept: dict[int, dict[str, Any]] = {}
    if args.reuse:
        kept = _reusable_entries(out_dir, stamps, manifest_name)
        _clear_for_reuse(out_dir, kept, manifest_name)
        if kept:
            protocol.log(
                f"Keeping the results of {len(kept)} of {len(cases)} case(s): their model and "
                "case did not change."
            )
    by_id = {c.id: c for c in project.analyses}
    finished: dict[int, dict[str, Any]] = dict(kept)
    known_file = Path(args.known_modal) if args.known_modal else None
    made_known_file = False

    def finish(code: int) -> int:
        entries = [finished[c.id] for c in cases if c.id in finished]
        write_manifest(out_dir, entries, str(args.project), manifest_name)
        if args.reuse:
            _write_stamps(out_dir, stamps, entries)
        if made_known_file and known_file is not None:
            known_file.unlink(missing_ok=True)
        return code

    for case in cases:
        if case.id in kept:
            protocol.emit(
                type="case_started",
                case_id=case.id,
                case_type=type(case).__name__,
                case_name=case.name,
            )
            protocol.log(f"Case '{case.name}' did not change: its results are kept.")
            protocol.emit(type="case_finished", **kept[case.id])
    cases_to_run = [c for c in cases if c.id not in kept]

    # Modal results a response spectrum case takes without solving again: those kept, those
    # the parallel run's parent handed over, and those this process computes.
    kept_modal = [e for cid, e in kept.items() if _shareable_modal(by_id.get(cid))]
    if kept_modal and known_file is None:
        known_file = out_dir / KNOWN_MODAL_NAME
        known_file.write_text(json.dumps(kept_modal), encoding="utf-8")
        made_known_file = True
    try:
        known = _load_known_modal(known_file, out_dir, by_id)
    except Exception as exc:  # a kept file that no longer reads: solve again
        protocol.log(f"The kept modal results could not be read ({exc}); solving them again.")
        known = {}

    protocol.log(f"Building model: {len(project.nodes)} nodes, {len(project.elements)} elements.")
    planner = OpenSeesRunner(project)
    jobs = job_count(args.jobs, len(project.nodes))
    units = run_units(planner, cases_to_run, jobs) if jobs > 1 else []
    if len(units) > 1:
        entries, code = _run_parallel(protocol, args, units, min(jobs, len(units)), known_file)
        finished.update(entries)
        return finish(code)

    keys = [planner.batch_key(case) for case in cases_to_run]
    batch: OpenSeesRunner | None = None
    eigen_called = False
    for k, case in enumerate(cases_to_run):
        key = keys[k]
        together = key is not None and (
            (k > 0 and keys[k - 1] == key) or (k + 1 < len(keys) and keys[k + 1] == key)
        )
        if together:
            # Linear static cases of one solver setting: one model, the stiffness factored once.
            protocol.emit(
                type="case_started",
                case_id=case.id,
                case_type=type(case).__name__,
                case_name=case.name,
            )
            protocol.log(f"Running case '{case.name}' ({type(case).__name__}) ...")
            try:
                if batch is None:
                    end = k
                    while end < len(cases_to_run) and keys[end] == key:
                        end += 1
                    batch = OpenSeesRunner(project)
                    batch.start_static_batch(cases_to_run[k:end])
                batch._on_progress = _throttled(protocol, case.id)
                results = batch.next_static_batch_case(case)
                if k + 1 == len(cases_to_run) or keys[k + 1] != key:
                    batch = None  # the run of cases ends here
                entry = write_results(results, out_dir)
            except Exception as exc:
                protocol.emit(type="error", message=str(exc), traceback=traceback.format_exc())
                return finish(EXIT_ANALYSIS_ERROR)
            finished[case.id] = entry
            for warning in entry["warnings"]:
                protocol.log(f"Warning: {warning}")
            protocol.log("Analysis complete.")
            protocol.emit(type="case_finished", **entry)
            continue
        batch = None

        shared = _takes_known_modal(case, known)
        if eigen_called and not shared and _routed_to_arpack(project, case):
            entry, code = _run_in_fresh_process(protocol, args, case)
            if entry is None:
                return finish(code)
            finished[case.id] = entry
            continue
        protocol.emit(
            type="case_started", case_id=case.id, case_type=type(case).__name__, case_name=case.name
        )
        protocol.log(f"Running case '{case.name}' ({type(case).__name__}) ...")
        try:
            runner = OpenSeesRunner(project, on_progress=_throttled(protocol, case.id))
            runner.known_modal_results = known
            results = runner.run(case, results_dir=out_dir)
            entry = write_results(results, out_dir)
        except Exception as exc:
            protocol.emit(type="error", message=str(exc), traceback=traceback.format_exc())
            return finish(EXIT_ANALYSIS_ERROR)
        eigen_called = eigen_called or (_uses_eigen(case) and not shared)
        if _shareable_modal(case):
            known[case.id] = results
        if shared:
            protocol.log(f"Combined the modes of the modal case already solved for '{case.name}'.")
        note = eigen_solver_note(results)
        if note:
            protocol.log(note)
        finished[case.id] = entry
        for warning in entry["warnings"]:
            protocol.log(f"Warning: {warning}")
        protocol.log("Analysis complete.")
        protocol.emit(type="case_finished", **entry)

    return finish(EXIT_OK)


def _main_flushing() -> int:
    """``main`` with stderr flushed on every exit the CLI controls."""
    try:
        return main()
    finally:
        sys.stderr.flush()


if __name__ == "__main__":
    raise SystemExit(_main_flushing())

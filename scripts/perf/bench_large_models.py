"""Benchmark of Run All on large buildings: generates RC towers with the New Building generator,
runs every Run All step headless, one at a time, and measures each step (wall and CPU time, peak
memory of this process and of the solver it starts, the files it writes, a cProfile of its
Python, the solver's included), then the payloads the workbench asks the backend for after a run
(result lists, the 3D viewer's model and results).

Nothing here is a second runner: the buildings come from ``saengine.project.new_building``
(``saengine new-building``), the steps from ``saengine.pipeline.run_all.run_all`` with
``steps=[step]`` (``saengine run-all --steps <step>``), the payloads from the RPC handlers of
``saengine.rpc.handlers`` called in this process. Steps run separately behave as in one Run All,
with two differences that do not change the work measured: ``boq`` does not know whether ``mep``
has just designed tanks (it measures the bill when its sources changed, as on a new project), and
``drawings`` reads the design checks kept beside the results (``design-report.json``) instead of
receiving them.

Usage (from the repository root, the SAEngine Python environment)::

    python scripts/perf/bench_large_models.py --list
    python scripts/perf/bench_large_models.py beam-10 flat-10 core-10 --out <scratch>/perf
    python scripts/perf/bench_large_models.py --summary --out <scratch>/perf

Each building gets ``<out>/<case>/``: the project, ``bench.json`` (every measurement),
``profiles/<step>.prof`` (open with ``python -m pstats`` or snakeviz) and ``profiles/<step>.txt``
(the top functions by cumulative and own time). ``--summary`` prints the tables of every
``bench.json`` under ``--out`` as Markdown. Keep the output out of the repository. See
docs/perf/large-models.md.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import pstats
import shutil
import subprocess
import sys
import threading
import time
import tracemalloc
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Self

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SOURCES = [REPO / "python" / "src", REPO / "third_party" / "opensees-studio" / "src"]
for _source in reversed(SOURCES):
    if str(_source) not in sys.path:
        sys.path.insert(0, str(_source))
# The solver runs in a child Python: it must import the same checkout.
os.environ["PYTHONPATH"] = os.pathsep.join(
    [str(s) for s in SOURCES] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
)

try:
    import psutil
except ImportError:  # memory of the solver process is then not measured
    psutil = None

#: Bays of 6-8 m, 4 x 3, as Dhaka's residential and office towers.
GRIDS_X = [7000, 6000, 8000, 7000]
GRIDS_Y = [6000, 8000, 6000]
SYSTEMS = {"beam": "rcFrame", "flat": "flatSlab", "core": "rcFrameWithWalls"}


def spec(system: str, storeys: int) -> dict[str, Any]:
    """The generator spec of a ``system`` (``beam``, ``flat``, ``core``) tower of ``storeys``."""
    return {
        "name": f"Perf {system} {storeys}",
        "gridsX": GRIDS_X,
        "gridsY": GRIDS_Y,
        "storyCount": storeys,
        "groundHeight": 4000,
        "typicalHeight": 3200,
        "system": SYSTEMS[system],
        "concrete": "C27.6",
        "rebar": "B500DWR",
        "footing": "mat",
        "location": "dhaka",
        "occupancy": "residential",
        # The template bars: without bars the design step checks nothing (Design mode would
        # propose them first), and the checks of every member are the work to measure.
        "reinforcement": True,
    }


#: The 3-storey buildings: a quick check of the script, and profiles in minutes (cProfile slows
#: the numeric code down two to four times).
CASES = {f"{s}-{n}": spec(s, n) for n in (3, 10, 20, 30) for s in SYSTEMS}


# ─────────────────────────────── measuring ───────────────────────────────


class MemorySampler:
    """Samples the resident memory of this process and of the solver processes in ``pids`` while
    a step runs: the peak of the sum, and each one's peak (on Windows the solver's own peak
    working set, exact between samples).

    Only the known process ids are sampled: ``Process.children()`` walks every process of the
    machine (about 70 ms on Windows, holding the GIL), which slowed the measured code down and
    filled its profile (Python 3.12's cProfile sees every thread). It is asked once or a few
    times per started process, for the interpreter a virtual environment's ``python.exe``
    launcher starts: that child is the solver."""

    #: Samples a started process is looked at for the child its launcher starts (5 s: on a
    #: loaded machine the launcher may take seconds to start it).
    LAUNCHER_LOOKS = 20

    def __init__(self, pids: list[int], interval: float = 0.25) -> None:
        self.pids = pids
        self.interval = interval
        self.peak_total = 0
        self.peak_self = 0
        self.peak_children = 0
        self.child_cpu: dict[int, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        me = psutil.Process()
        processes: dict[int, list[Any]] = {}  # started pid -> it and its launcher's child
        looks: dict[int, int] = {}
        while True:
            own = me.memory_info().rss
            children = peaks = 0
            for pid in list(self.pids):
                try:
                    if pid not in processes:
                        processes[pid] = [psutil.Process(pid)]
                    if looks.get(pid, 0) < self.LAUNCHER_LOOKS and len(processes[pid]) == 1:
                        looks[pid] = looks.get(pid, 0) + 1
                        processes[pid] += processes[pid][0].children()
                except psutil.Error:
                    continue
                for process in processes[pid]:
                    try:
                        info = process.memory_info()
                        times = process.cpu_times()
                    except psutil.Error:
                        continue
                    children += info.rss
                    peaks += getattr(info, "peak_wset", 0)
                    self.child_cpu[process.pid] = times.user + times.system
            self.peak_children = max(self.peak_children, peaks)
            self.peak_self = max(self.peak_self, own)
            self.peak_children = max(self.peak_children, children)
            self.peak_total = max(self.peak_total, own + children)
            if self._stop.wait(self.interval):
                return

    def __enter__(self) -> Self:
        if psutil is not None:
            self._thread = threading.Thread(target=self._sample, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()


def rss() -> int:
    return psutil.Process().memory_info().rss if psutil is not None else 0


def mb(value: float | None) -> float | None:
    return None if value is None else round(value / 2**20, 1)


def snapshot(root: Path) -> dict[str, tuple[int, int]]:
    """``relative path -> (size, mtime_ns)`` of every file under ``root``."""
    files = {}
    for path in root.rglob("*"):
        if path.is_file():
            stat = path.stat()
            files[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return files


def written(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> dict:
    """The files a step wrote: their count, total size and the ten largest."""
    changed = {p: s for p, (s, t) in after.items() if before.get(p) != (s, t)}
    largest = sorted(changed.items(), key=lambda item: -item[1])[:10]
    return {
        "files": len(changed),
        "bytes": sum(changed.values()),
        "largest": [{"path": p, "bytes": s} for p, s in largest],
    }


def profile_text(stats: pstats.Stats, top: int = 30) -> str:
    out = io.StringIO()
    for key, title in (("cumulative", "cumulative time"), ("tottime", "own time")):
        out.write(f"==== top {top} by {title} ====\n")
        stats.stream = out
        stats.sort_stats(key).print_stats(top)
    return out.getvalue()


@contextmanager
def tracked_children(prefix: Path | None):
    """While a step runs: every process it starts is kept (its id, for its memory and CPU time),
    and every OpenSees Studio solver run (``python -m opensees_studio.run``: the analysis, the
    response spectrum design's modal-force run, the fixed-base run, the raft, the tanks) runs
    under ``-m cProfile -o <prefix>-<n>.prof`` when ``prefix`` is given.

    ``subprocess.Popen`` is replaced for the duration (``subprocess.run`` calls it too), so the
    steps start their processes as they do in the app."""
    real = subprocess.Popen
    started: list[int] = []

    class Tracked(real):  # type: ignore[valid-type, misc]
        def __init__(self, args: Any, *rest: Any, **kwargs: Any) -> None:
            if prefix is not None and isinstance(args, list | tuple):
                args = list(args)
                if "opensees_studio.run" in args and "-m" in args:
                    at = args.index("-m")
                    args[at:at] = ["-m", "cProfile", "-o", f"{prefix}-{len(started) + 1}.prof"]
            super().__init__(args, *rest, **kwargs)
            started.append(self.pid)

    subprocess.Popen = Tracked  # type: ignore[misc]
    try:
        yield started
    finally:
        subprocess.Popen = real  # type: ignore[misc]


def model_counts(model: Path) -> dict[str, Any]:
    """Nodes, elements by type, DOFs, analysis cases and the size of the derived model."""
    if not model.exists():
        return {}
    started = time.perf_counter()
    text = model.read_text(encoding="utf-8")
    data = json.loads(text)
    parse = time.perf_counter() - started
    nodes = data.get("nodes") or []
    elements = data.get("elements") or []
    kinds = Counter(str(e.get("type") or e.get("kind") or "?") for e in elements)
    ndf = (data.get("model") or {}).get("ndf") or data.get("ndf") or 6
    fixed = 0
    for support in data.get("supports") or data.get("fixities") or []:
        dofs = support.get("dofs") or support.get("fixity") or []
        fixed += sum(1 for d in dofs if d)
    return {
        "nodes": len(nodes),
        "elements": len(elements),
        "elementTypes": dict(kinds.most_common()),
        "ndf": ndf,
        "dofs": len(nodes) * int(ndf) - fixed,
        "cases": len(data.get("analyses") or []),
        "loadPatterns": len(data.get("load_patterns") or data.get("patterns") or []),
        "modelBytes": len(text.encode("utf-8")),
        "modelParseSeconds": round(parse, 3),
    }


def folder_size(folder: Path) -> dict[str, Any]:
    if not folder.exists():
        return {"files": 0, "bytes": 0}
    sizes = {p.relative_to(folder).as_posix(): p.stat().st_size for p in folder.rglob("*")
             if p.is_file()}  # fmt: skip
    largest = sorted(sizes.items(), key=lambda item: -item[1])[:10]
    return {
        "files": len(sizes),
        "bytes": sum(sizes.values()),
        "largest": [{"path": p, "bytes": s} for p, s in largest],
    }


def measure(
    label: str,
    call: Any,
    profiles: Path | None,
    trace: bool,
    root: Path | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Runs ``call()`` and measures it; ``profiles``: where its cProfile goes."""
    before = snapshot(root) if root else None
    base = rss()
    profiler = cProfile.Profile() if profiles is not None else None
    if trace:
        tracemalloc.start()
    if psutil is not None:
        psutil.cpu_percent(None)  # the machine's load from here to the end of the call
    prefix = profiles / f"{label}-solver" if profiles is not None else None
    if prefix is not None:
        prefix.parent.mkdir(parents=True, exist_ok=True)
    with tracked_children(prefix) as children, MemorySampler(children) as memory:
        cpu, wall = time.process_time(), time.perf_counter()
        if profiler:
            profiler.enable()
        try:
            value, error = call(), None
        except Exception as exc:  # noqa: BLE001 - recorded with the measurement
            value, error = None, f"{type(exc).__name__}: {exc}"
        if profiler:
            profiler.disable()
        wall, cpu = time.perf_counter() - wall, time.process_time() - cpu
    record: dict[str, Any] = {
        "seconds": round(wall, 3),
        "cpuSeconds": round(cpu, 3),
        "rssBeforeMB": mb(base),
        "peakRssMB": mb(memory.peak_self) if psutil else None,
        "peakChildRssMB": mb(memory.peak_children) if psutil and children else None,
        "peakTotalRssMB": mb(memory.peak_total) if psutil else None,
    }
    if children:
        record["childProcesses"] = len(children)
    if children and memory.child_cpu:
        # The solver's CPU time as last sampled (up to one interval short).
        record["childCpuSeconds"] = round(sum(memory.child_cpu.values()), 3)
    if psutil is not None:
        # Other programs (an antivirus scan, tests of other sessions) slow a step down: this is
        # the whole machine's CPU load while it ran, in percent of all cores.
        record["machineCpuPercent"] = psutil.cpu_percent(None)
    if trace:
        record["tracemallocPeakMB"] = mb(tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()
    if error:
        record["error"] = error
    if root is not None and before is not None:
        record["written"] = written(before, snapshot(root))
    if profiler and profiles is not None:
        profiles.mkdir(parents=True, exist_ok=True)
        profiler.dump_stats(profiles / f"{label}.prof")
        text = profile_text(pstats.Stats(profiler))
        solvers = sorted(map(str, profiles.glob(f"{label}-solver-*.prof")))
        if solvers:
            text += f"\n\n######## {len(solvers)} solver run(s) (opensees_studio.run) ########\n"
            text += profile_text(pstats.Stats(*solvers))
        (profiles / f"{label}.txt").write_text(text, encoding="utf-8")
        record["profile"] = f"profiles/{label}.txt"
    return value, record


# ─────────────────────────────── the benchmark ───────────────────────────────


def generate(case: str, folder: Path, profiles: Path | None, trace: bool) -> tuple[Path, dict]:
    from saengine.project.new_building import create_building

    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    result, record = measure(
        "generate", lambda: create_building(CASES[case], folder), profiles, trace
    )
    if result is None:
        raise SystemExit(f"{case}: the building could not be generated: {record.get('error')}")
    record["counts"] = (result.get("summary") or {}).get("counts") or {}
    record["notes"] = len(result.get("notes") or [])
    return Path(result["root"]), record


def run_steps(
    root: Path,
    steps: list[str],
    profiles: Path | None,
    trace: bool,
    log: Any,
    records: list[dict[str, Any]],
    save: Any,
) -> None:
    """Runs and measures the ``steps`` into ``records``, calling ``save()`` after each one (a
    long run stopped half-way keeps what it measured)."""
    from saengine.codes import context as code_context
    from saengine.pipeline.project import open_project
    from saengine.pipeline.run_all import run_all

    for step in steps:
        log(f"  step {step} ...")
        project = open_project(root)  # each step reads the files afresh, as a new run would

        def call(step: str = step, project: Any = project) -> Any:
            with code_context.project(project.root):
                return run_all(project, [step])

        result, record = measure(step, call, profiles, trace, root)
        record["step"] = step
        if result is not None:
            step_result = result.steps[0]
            record.update(
                status=step_result.status,
                message=step_result.message,
                counts=_plain(step_result.counts),
                runAllSeconds=round(step_result.seconds, 3),
            )
        if step == "derive":
            record["model"] = model_counts(root / "08 FEM" / "model.osmodel")
        if step == "analysis":
            record["results"] = folder_size(root / "08 FEM" / "model.results")
        records.append(record)
        save()
        log(f"    {record.get('status')} {record['seconds']:.1f} s, peak "
            f"{record.get('peakTotalRssMB')} MB: {record.get('message', record.get('error'))}")  # fmt: skip
        if record.get("status") in ("failed", "error") or record.get("error"):
            log("    Run All would stop here; the remaining steps are not run.")
            break


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def payloads(root: Path, profiles: Path | None, trace: bool, log: Any) -> list[dict[str, Any]]:
    """The backend calls the workbench makes to show a finished run, each timed with the size of
    its JSON answer (and the time ``json.dumps`` takes, as the RPC server serialises it)."""
    from saengine.rpc import handlers as H

    model = root / "08 FEM" / "model.osmodel"
    out = model.parent / "model.results"
    if not (out / "manifest.json").exists():
        return []
    project, folder = str(model), str(out)
    calls: list[tuple[str, Any]] = [
        ("results/list", lambda: H.result_list(folder, project)),
        ("results/tables", lambda: H.results_tables(folder, project)),
        ("fem/storyResponse", lambda: H.story_response(folder, project)),
        ("fem/seismicDesign", lambda: H.seismic_design(folder, project)),
        ("fem/secondOrder", lambda: H.second_order_summary(folder, project)),
        ("fem/columnInteraction", lambda: H.column_interaction(folder, project, None)),
        ("design/required", lambda: H.design_required(folder, project)),
        ("drawings/list", lambda: H.drawings_list(str(root))),
    ]
    records = []
    listing: dict[str, Any] = {}
    for name, call in calls:
        value, record = _payload(name, call, profiles, trace)
        if name == "results/list" and isinstance(value, dict):
            listing = value
        records.append(record)
        log(f"  {name}: {record['seconds']:.2f} s, {record.get('jsonBytes')} bytes")
    # The 3D view: every result of the list, as the results bar steps through them.
    views = []
    for item in listing.get("results", []):
        modes = [m["number"] for m in item.get("modes", [])][:3] or [None]
        for mode in modes:
            key = item["key"]
            label = f"results-view-{key.replace(':', '-')}" + (f"-m{mode}" if mode else "")
            _, record = _payload(
                label, lambda key=key, mode=mode: H.result_view(folder, project, key, mode),
                profiles if not views else None, trace,
            )  # fmt: skip
            record.update(key=key, mode=mode, kind=item.get("kind"))
            views.append(record)
    if views:
        records.append(
            {
                "call": "results/view (every result)",
                "count": len(views),
                "seconds": round(sum(v["seconds"] for v in views), 3),
                "maxSeconds": max(v["seconds"] for v in views),
                "jsonBytes": sum(v.get("jsonBytes") or 0 for v in views),
                "maxJsonBytes": max(v.get("jsonBytes") or 0 for v in views),
                "views": views,
            }
        )
        log(f"  results/view x{len(views)}: {records[-1]['seconds']:.1f} s")
    # A member's detail window: the first column of the model.
    member = _first_member(model)
    if member:
        _, record = _payload(
            "fem/memberForces", lambda: H.member_forces(folder, project, member), profiles, trace
        )
        record["member"] = member
        records.append(record)
    # The viewer reads the model itself: its size and the time to parse it.
    started = time.perf_counter()
    json.loads(model.read_text(encoding="utf-8"))
    records.append(
        {
            "call": "model.osmodel (read by the viewer)",
            "seconds": round(time.perf_counter() - started, 3),
            "jsonBytes": model.stat().st_size,
        }
    )
    return records


def _payload(name: str, call: Any, profiles: Path | None, trace: bool) -> tuple[Any, dict]:
    label = name.replace("/", "-")
    value, record = measure(label, call, profiles, trace)
    record["call"] = name
    if value is not None:
        started = time.perf_counter()
        text = json.dumps(value, default=str)
        record["dumpSeconds"] = round(time.perf_counter() - started, 3)
        record["jsonBytes"] = len(text.encode("utf-8"))
    return value, record


def _first_member(model: Path) -> str | None:
    try:
        data = json.loads(model.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for element in data.get("elements") or []:
        member = element.get("member") or (element.get("meta") or {}).get("member")
        if member:
            return str(member)
    return None


def bench(case: str, out: Path, args: argparse.Namespace) -> dict[str, Any]:
    from saengine.pipeline.run_all import STEP_IDS

    folder = out / case
    profiles = None if args.no_profile else folder / "profiles"
    log_file = folder.parent / f"{case}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(message: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {case}: {message}"
        print(line, flush=True)
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    record: dict[str, Any] = {
        "case": case,
        "spec": CASES[case],
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "profiled": profiles is not None,
        "tracemalloc": args.tracemalloc,
        "python": sys.version.split()[0],
        "cpus": os.cpu_count(),
    }
    kept = [p for p in folder.glob("*") if p.is_dir() and any(p.glob("*.saengine"))]
    if args.keep and kept:
        root = kept[0]
        if not args.payloads_only:
            # The analysis model and its results go, so that every step has its work to do (the
            # bill is measured again only if it was never measured: it is current otherwise).
            fem = root / "08 FEM"
            for name in ("model.osmodel", "pushover.osmodel", "thermal.json", "ssi.json"):
                (fem / name).unlink(missing_ok=True)
            shutil.rmtree(fem / "model.results", ignore_errors=True)
    else:
        log("generating ...")
        root, record["generate"] = generate(case, folder, profiles, args.tracemalloc)
    record["root"] = str(root)
    steps = args.steps or list(STEP_IDS)
    target = folder / ("bench.json" if not args.payloads_only else "bench-payloads.json")

    def save() -> None:
        target.write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")

    if not args.payloads_only:
        record["steps"] = []
        run_steps(root, steps, profiles, args.tracemalloc, log, record["steps"], save)
        record["model"] = model_counts(root / "08 FEM" / "model.osmodel")
    if not args.no_payloads:
        log("payloads ...")
        record["payloads"] = payloads(root, profiles, args.tracemalloc, log)
    record["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save()
    log(f"wrote {target}")
    return record


# ─────────────────────────────── the summary ───────────────────────────────


def _fmt(value: Any, digits: int = 1) -> str:
    if value is None:
        return "–"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _size(value: Any) -> str:
    if not value:
        return "–"
    for unit, scale in (("GB", 2**30), ("MB", 2**20), ("kB", 2**10)):
        if value >= scale:
            return f"{value / scale:,.1f} {unit}"
    return f"{value} B"


def summary(out: Path) -> str:
    lines: list[str] = []
    records = sorted(
        (json.loads(p.read_text(encoding="utf-8")) for p in out.glob("*/bench.json")),
        key=lambda r: (r["spec"]["storyCount"], r["case"]),
    )
    for record in records:
        model = record.get("model") or {}
        total = sum(s["seconds"] for s in record.get("steps", []))
        types = ", ".join(f"{k} {v:,}" for k, v in (model.get("elementTypes") or {}).items())
        lines += [
            (
                f"### {record['case']} ({record['spec']['system']}, "
                f"{record['spec']['storyCount']} storeys)"
            ),
            "",
            (
                f"{_fmt(model.get('nodes'))} nodes, {_fmt(model.get('elements'))} elements "
                f"({types}), {_fmt(model.get('dofs'))} DOFs, {_fmt(model.get('cases'))} analysis "
                f"cases; model.osmodel {_size(model.get('modelBytes'))}. Run All "
                f"{total / 60:,.1f} min{' (profiled)' if record.get('profiled') else ''}."
            ),
            "",
            (
                "| Step | Status | Wall (s) | CPU (s) | Solver CPU (s) | Machine load "
                "| Peak RSS (MB) | Step's growth (MB) | Solver RSS (MB) | Written |"
            ),
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        generated = record.get("generate")
        steps = ([{"step": "generate", "status": "ok", **generated}] if generated else []) + list(
            record.get("steps", [])
        )
        for step in steps:
            load = step.get("machineCpuPercent")
            # The process keeps what an earlier step allocated: the step's own need is its
            # peak above the memory it started with.
            peak, before = step.get("peakRssMB"), step.get("rssBeforeMB")
            growth = round(peak - before, 1) if peak is not None and before is not None else None
            lines.append(
                f"| {step['step']} | {step.get('status', 'error')} | {_fmt(step['seconds'])} | "
                f"{_fmt(step['cpuSeconds'])} | {_fmt(step.get('childCpuSeconds'))} | "
                f"{'–' if load is None else f'{load:.0f} %'} | {_fmt(peak)} | {_fmt(growth)} | "
                f"{_fmt(step.get('peakChildRssMB'))} | "
                f"{_size((step.get('written') or {}).get('bytes'))} |"
            )
        lines += ["", "| Payload | Time (s) | JSON |", "| --- | ---: | ---: |"]
        for item in record.get("payloads", []):
            name = item["call"] + (f" ×{item['count']}" if item.get("count") else "")
            lines.append(
                f"| {name} | {_fmt(item['seconds'], 2)} | {_size(item.get('jsonBytes'))} |"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("cases", nargs="*", help="the buildings (see --list)")
    parser.add_argument("--out", type=Path, help="the scratch folder (outside the repository)")
    parser.add_argument("--list", action="store_true", help="list the buildings")
    parser.add_argument("--steps", nargs="+", help="some Run All steps only")
    parser.add_argument("--no-profile", action="store_true", help="time without cProfile")
    parser.add_argument("--tracemalloc", action="store_true",
                        help="also the peak of Python allocations (slows the run down)")  # fmt: skip
    parser.add_argument("--keep", action="store_true",
                        help="reuse the generated project of a previous run (its analysis model "
                        "and results are removed first)")  # fmt: skip
    parser.add_argument(
        "--payloads-only",
        action="store_true",
        help="only the workbench's payloads, on a finished run (implies --keep)",
    )
    parser.add_argument("--no-payloads", action="store_true", help="the Run All steps only")
    parser.add_argument("--summary", action="store_true", help="print the tables of --out")
    args = parser.parse_args(argv)
    if args.list:
        for name, item in CASES.items():
            print(f"{name:10} {item['system']:17} {item['storyCount']} storeys")
        return 0
    if args.out is None:
        parser.error("--out is required")
    if args.summary:
        sys.stdout.reconfigure(encoding="utf-8")  # the tables' dashes, on a Windows console too
        print(summary(args.out))
        return 0
    if args.payloads_only:
        args.keep = True
    unknown = [c for c in args.cases if c not in CASES]
    if unknown or not args.cases:
        parser.error(f"give buildings of --list (unknown: {', '.join(unknown) or 'none given'})")
    import opensees_studio
    import saengine

    # The shared environment may install both editable from another checkout: measure this one.
    for module in (saengine, opensees_studio):
        where = Path(module.__file__).resolve()
        print(f"{module.__name__} from {where.parent}", flush=True)
        if not where.is_relative_to(REPO):
            parser.error(f"{module.__name__} is imported from outside {REPO}: {where}")
    for case in args.cases:
        bench(case, args.out, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())

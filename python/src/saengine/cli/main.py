"""The ``saengine`` command line.

Commands (see ``docs/cli.md`` for examples and the JSON schema)::

    saengine --version
    saengine validate <project> [--json]
    saengine run-all <project> [--steps STEP ...] [--json]
    saengine derive|analyse|design|report <project> [--json]
    saengine check <project> [--json]
    saengine status <project> [--json]
    saengine export <project> --format ifc|dxf|csv|pdf|drawings|civil [--out PATH]
                    [--size A1|A2|A3] [--include-results]
    saengine import <file.civil> <dest folder> [--name NAME] [--overwrite]
    saengine versions status|list|save|diff|restore|issue <project> ...
    saengine verify [--out DIR] [--pdf] [--fast] [--cases ID ...]
    saengine codepack list|show <id>|new <id> --extends ID --dest DIR|validate <dir>|diff <a> <b>
    saengine package ...  (the same as codepack; --kind for templates)

Results go to stdout (text, or one JSON document with ``--json``), progress to stderr.

Exit codes: 0 ok; 1 checks fail (design, foundation or MEP checks, or validation problems);
2 usage (bad arguments, not a project); 3 error (a step could not be done, an export or import
failed).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from saengine.cli.codepack import cmd_codepack
from saengine.cli.codepack import register as register_codepack

EXIT_OK = 0
EXIT_CHECKS = 1
EXIT_USAGE = 2
EXIT_ERROR = 3

#: The JSON documents' ``schema``.
JSON_SCHEMA = "saengine.cli/1"

#: Commands that run a part of Run All: the steps they run.
STEP_COMMANDS: dict[str, tuple[str, ...]] = {
    "derive": ("derive",),
    "analyse": ("derive", "analysis", "ssi"),
    "design": ("design", "substructure"),
    "report": ("report",),
}
#: What ``check`` runs: Run All without the bill and the report (no deliverables are written).
CHECK_STEPS = ("derive", "analysis", "ssi", "design", "substructure", "mep")

PART_TITLES = {
    "soil": "1 Soil Report",
    "settings": "2 Project Settings",
    "materials": "3 Materials",
    "objects": "4 Objects",
    "floorPlan": "5 Floor Plan",
    "structure": "5 Structural Model",
    "bim": "6 BIM",
    "mep": "7 MEP",
    "fem": "8 FEM",
    "substructure": "9 Substructure",
    "boq": "10 BOQ",
    "exports": "11 Exports",
}


class UsageError(Exception):
    """Bad arguments or not a project: exit 2."""


class CommandError(Exception):
    """The command could not be done: exit 3."""


class ArgumentsError(Exception):
    """argparse rejected the arguments (exit 2); ``usage`` is the parser's usage text."""

    def __init__(self, message: str, usage: str, command: str) -> None:
        super().__init__(message)
        self.usage = usage
        self.command = command


class _Parser(argparse.ArgumentParser):
    """An ArgumentParser that raises :class:`ArgumentsError` instead of exiting, so that
    ``--json`` still gets its document on a usage error."""

    def error(self, message: str) -> Any:  # type: ignore[override]
        words = self.prog.split()[1:]  # "saengine versions diff" -> "versions diff"
        raise ArgumentsError(message, self.format_usage(), " ".join(words))


# ─────────────────────────────── output ───────────────────────────────


class Output:
    def __init__(self, as_json: bool, quiet: bool = False) -> None:
        self.json = as_json
        self.quiet = quiet

    def progress(self, message: str) -> None:
        if not self.quiet:
            print(message, file=sys.stderr, flush=True)

    def line(self, text: str = "") -> None:
        if not self.json:
            print(text)

    def document(self, command: str, code: int, body: dict[str, Any]) -> None:
        if self.json:
            import saengine

            payload = {"schema": JSON_SCHEMA, "command": command, "exitCode": code,
                       "saengine": saengine.__version__, **body}  # fmt: skip
            json.dump(payload, sys.stdout, indent=2, ensure_ascii=False, default=str)
            sys.stdout.write("\n")


def _open(path: str):
    from saengine.pipeline.project import ProjectError, open_project

    try:
        return open_project(path)
    except ProjectError as error:
        raise UsageError(str(error)) from error


def _project_json(project) -> dict[str, Any]:
    return {"root": str(project.root), "name": project.name, "type": project.type}


# ─────────────────────────────── checks ───────────────────────────────


def check_failures(result) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The failing checks (exit 1) and the warnings of a run, per part, from its steps."""
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def fail(part: str, check: str, count: Any, message: str) -> None:
        if isinstance(count, int | float) and count > 0:
            failures.append({"part": part, "check": check, "count": count, "message": message})

    def warn(part: str, check: str, count: Any, message: str) -> None:
        if count:
            warnings.append({"part": part, "check": check, "count": count, "message": message})

    design = result.step("design")
    if design and design.status in ("ok", "warning"):
        c = design.counts
        fail("fem", "design", c.get("failed"),
             f"{c.get('failed')} of {c.get('checked')} members fail the design checks "
             f"(max utilisation {c.get('maxUtilisation')}, {c.get('governing')})")  # fmt: skip
    foundations = result.step("substructure")
    if foundations and foundations.status in ("ok", "warning"):
        c = foundations.counts
        fail("substructure", "foundations", c.get("failed"),
             f"{c.get('failed')} of {c.get('checked')} foundations fail "
             f"(max utilisation {c.get('maxUtilisation')}, {c.get('governing')})")  # fmt: skip
        warn("substructure", "notDesigned", c.get("checked") == 0 and c.get("foundations"),
             "the foundations were not designed: run the analysis")  # fmt: skip
    mep = result.step("mep")
    if mep and mep.status in ("ok", "warning"):
        c = mep.counts
        fail("mep", "openings", c.get("openingsFailed"), f"{c.get('openingsFailed')} openings fail")
        fail("mep", "plumbing", c.get("plumbingFailed"),
             f"{c.get('plumbingFailed')} plumbing checks fail")  # fmt: skip
        fail("mep", "pressure", c.get("floorsLow"),
             f"{c.get('floorsLow')} floors below the minimum pressure")  # fmt: skip
        fail("mep", "hvac", c.get("hvacFailed"), f"{c.get('hvacFailed')} HVAC checks fail")
        fail("mep", "electrical", c.get("electricalFailed"),
             f"{c.get('electricalFailed')} electrical checks fail")  # fmt: skip
        warn("mep", "clashes", c.get("clashesOpen"), f"{c.get('clashesOpen')} open clashes")
        warn("mep", "openingsPartial", c.get("openingsPartial"),
             f"{c.get('openingsPartial')} openings not fully checked")  # fmt: skip
        warn("mep", "hvacLoads", c.get("hvacLoadsCalculated") is False,
             "the HVAC loads are the estimate: run Calculate Loads in the app")  # fmt: skip
        warn("mep", "openingsToAdd",
             (c.get("hvacOpeningsToAdd") or 0) + (c.get("electricalOpeningsToAdd") or 0),
             "openings the ducts, risers or trays still need are not in 07 MEP")  # fmt: skip
    return failures, warnings


# ─────────────────────────────── run-all and its parts ───────────────────────────────


def _run(command: str, args: argparse.Namespace, out: Output, steps: Sequence[str] | None) -> int:
    from saengine.pipeline.run_all import STEP_LABELS, run_all

    project = _open(args.project)

    def progress(step: str, index: int, count: int, message: str | None) -> None:
        text = f"[{index + 1}/{count}] {STEP_LABELS[step]}"
        out.progress(f"{text}: {message}" if message else text)

    result = run_all(project, steps=steps, progress=progress)
    failures, warnings = check_failures(result)
    code = EXIT_ERROR if not result.ok else EXIT_CHECKS if failures else EXIT_OK
    for step in result.steps:
        out.line(f"{step.status:<8} {step.label}: {step.message}")
    out.line()
    _print_parts(out, result.parts)
    out.line()
    out.line(result.summary)
    if failures:
        out.line()
        out.line("Failing checks:")
        for f in failures:
            out.line(f"  {PART_TITLES.get(f['part'], f['part'])}: {f['message']}")
    if warnings:
        out.line("Warnings:")
        for w in warnings:
            out.line(f"  {PART_TITLES.get(w['part'], w['part'])}: {w['message']}")
    out.document(command, code, {**result.to_json(), "failures": failures, "warnings": warnings})
    return code


def _print_parts(out: Output, parts) -> None:
    for status in parts:
        title = PART_TITLES.get(status.part, status.part)
        hint = f" ({status.hint})" if status.hint else ""
        out.line(f"  {title:<20} {status.state:<11} {status.text}{hint}")


def cmd_run_all(args: argparse.Namespace, out: Output) -> int:
    from saengine.pipeline.run_all import STEP_IDS, normalise_steps

    values = list(args.steps or [])
    if args.project is None:
        # ``run-all --steps design substructure <project>``: --steps took the project too. The
        # project is the last word as given, before splitting on commas, so a folder such as
        # "Smith, Dhaka" stays whole; it is a project unless every comma-separated piece of it
        # is a step name.
        last = values[-1] if values else None
        pieces = [s.strip() for s in last.split(",") if s.strip()] if last is not None else []
        if last is not None and not (pieces and all(p in STEP_IDS for p in pieces)):
            args.project = values.pop()
        else:
            raise ArgumentsError("the following arguments are required: project",
                                 args.usage_text, "run-all")  # fmt: skip
    names = [s.strip() for value in values for s in value.split(",") if s.strip()]
    try:
        steps = normalise_steps(names) if names else None
    except ValueError as error:
        raise UsageError(str(error)) from error
    return _run("run-all", args, out, steps)


def cmd_step(args: argparse.Namespace, out: Output) -> int:
    return _run(args.command, args, out, STEP_COMMANDS[args.command])


def cmd_check(args: argparse.Namespace, out: Output) -> int:
    return _run("check", args, out, CHECK_STEPS)


def cmd_status(args: argparse.Namespace, out: Output) -> int:
    from saengine.pipeline.status import next_step, part_statuses

    project = _open(args.project)
    statuses = part_statuses(project)
    _print_parts(out, statuses)
    found = next_step(statuses)
    if found:
        out.line()
        out.line(f"Next: {PART_TITLES.get(found[1].part, found[1].part)}: {found[1].hint or ''}")
    out.document("status", EXIT_OK, {
        "project": _project_json(project),
        "parts": [s.to_json() for s in statuses],
        "next": found[1].part if found else None,
    })  # fmt: skip
    return EXIT_OK


# ─────────────────────────────── validate ───────────────────────────────


def cmd_validate(args: argparse.Namespace, out: Output) -> int:
    from saengine.pipeline.validate import validate_project

    project = _open(args.project)
    results = validate_project(project)
    errors = sum(r.errors for r in results)
    for r in results:
        out.line(f"{r.state:<12} {r.file}")
        for p in r.problems:
            where = f"{p['path']}: " if p["path"] and not p["message"].startswith(p["path"]) else ""
            out.line(f"    {p['severity']}: {where}{p['message']}")
    out.line()
    out.line(f"{errors} error(s)" if errors else "No errors.")
    code = EXIT_CHECKS if errors else EXIT_OK
    out.document("validate", code, {
        "project": _project_json(project), "ok": not errors, "errors": errors,
        "parts": [r.to_json() for r in results],
    })  # fmt: skip
    return code


# ─────────────────────────────── export / import ───────────────────────────────


def cmd_export(args: argparse.Namespace, out: Output) -> int:
    project = _open(args.project)
    target_arg = args.out or getattr(args, "target", None)
    out_path = Path(target_arg) if target_arg else None
    if args.format == "e2k":
        return cmd_export_e2k(args, out, project, out_path)
    if args.format == "civil":
        from saengine.project.archive import ArchiveError, export_project, safe_name

        # The manifest's name is the user's (or a received project's): never a path.
        file_name = f"{safe_name(project.name)}.civil"
        target = out_path or Path.cwd() / file_name
        if target.is_dir():
            target = target / file_name
        from saengine.pipeline.status import part_statuses

        statuses = {s.part: s.to_json() for s in part_statuses(project)}
        try:
            result = export_project(
                project.root, target, include_results=args.include_results,
                include_versions=args.include_versions, statuses=statuses,
            )  # fmt: skip
        except (ArchiveError, OSError) as error:
            raise CommandError(str(error)) from error
        out.line(f"Wrote {result['path']} ({result['files']} files, {result['size']} bytes).")
        for p in result.get("problems") or []:
            out.line(f"  {p.get('severity', 'warning')}: {p.get('message')}")
        out.document("export", EXIT_OK, {
            "project": _project_json(project), "format": "civil", "files": [str(result["path"])],
            "archive": result,
        })  # fmt: skip
        return EXIT_OK
    from saengine.pipeline.exports import ExportError, export

    try:
        written = export(project, args.format, out_path, size=args.size)
    except ExportError as error:
        raise CommandError(str(error)) from error
    for path in written:
        out.line(f"Wrote {path}")
    out.document("export", EXIT_OK, {
        "project": _project_json(project), "format": args.format,
        "files": [str(p) for p in written],
    })  # fmt: skip
    return EXIT_OK


def cmd_export_e2k(
    args: argparse.Namespace, out: Output, project: Any, out_path: Path | None
) -> int:
    """``saengine export --format e2k <project> [<out.e2k>]``: an ETABS text model
    (saengine.exporters.etabs) and its export report beside it."""
    from saengine.exporters.etabs import E2kExportError, export_e2k_file

    units = ("N", "MM") if args.units == "N-mm" else ("KN", "M")
    out.progress("Deriving the analysis model for the story forces ...")
    try:
        result = export_e2k_file(project.root, out_path, units=units, lateral=args.lateral)
    except (E2kExportError, OSError) as error:
        raise CommandError(str(error)) from error
    report = result["report"]
    written, report_path = Path(result["path"]), Path(result["reportPath"])
    out.line(f"Wrote {written}")
    out.line(f"Wrote {report_path}")
    counts = ", ".join(f"{v} {k}" for k, v in report["exported"].items() if v)
    if counts:
        out.line(f"  exported: {counts}")
    for heading in ("approximated", "skipped"):
        for item in report[heading]:
            examples = ", ".join(str(e) for e in item["examples"][:3])
            out.line(
                f"  {heading}: {item['what']} ({item['count']})"
                + (f", e.g. {examples}" if examples else "")
            )
    for warning in report["warnings"]:
        out.line(f"  warning: {warning}")
    out.document("export", EXIT_OK, {
        "project": _project_json(project), "format": "e2k",
        "files": [str(written), str(report_path)], "report": report,
    })  # fmt: skip
    return EXIT_OK


def cmd_import_structural(args: argparse.Namespace, out: Output) -> int:
    """Integrator glue: ``saengine import <file.e2k|.std|.s2k> <dest>`` (saengine.importers)."""
    from saengine.importers.project import StructuralImportError, import_structural

    try:
        result = import_structural(args.archive, args.dest, args.name, args.overwrite)
    except StructuralImportError as error:
        if out.json:
            out.document("import", EXIT_ERROR, {"error": str(error), "problems": [str(error)]})
            return EXIT_ERROR
        raise CommandError(str(error)) from error
    report = result["report"]
    source = report.get("source", {})
    out.line(
        f"Imported {source.get('program', result['format'])} model {Path(args.archive).name} "
        f"as {result['name']} into {result['root']}"
        + (f" (units {source['units']})." if source.get("units") else ".")
    )
    counts = ", ".join(f"{v} {k}" for k, v in (report.get("imported") or {}).items() if v)
    if counts:
        out.line(f"  imported: {counts}")
    for heading in ("approximated", "skipped"):
        for item in report.get(heading) or []:
            examples = ", ".join(str(e) for e in (item.get("examples") or [])[:3])
            out.line(
                f"  {heading}: {item.get('what')} ({item.get('count')})"
                + (f", e.g. {examples}" if examples else "")
            )
    not_carried = (report.get("loads") or {}).get("notCarriedKN") or {}
    if any(not_carried.values()):
        out.line(
            "  loads not carried over: "
            + ", ".join(f"{case} {kn:.0f} kN" for case, kn in not_carried.items() if kn)
        )
    for warning in report.get("warnings") or []:
        out.line(f"  warning: {warning}")
    for problem in result.get("problems") or []:
        out.line(f"  problem: {problem}")
    out.document("import", EXIT_OK, {"import": result})
    return EXIT_OK


def cmd_new_building(args: argparse.Namespace, out: Output) -> int:
    """Integrator glue: ``saengine new-building <spec.json> <dest>`` (saengine.project.
    new_building, the generator of saengine.library.generator)."""
    from saengine.project.new_building import NewBuildingError, create_building

    path = Path(args.spec)
    if not path.is_file():
        raise UsageError(f"{args.spec} does not exist")
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise UsageError(f"{args.spec} is not a JSON file: {error}") from error
    if not isinstance(spec, dict):
        raise UsageError(f"{args.spec}: the spec must be a JSON object")
    # create_building takes only an existing absolute folder (N2: the app never creates a
    # project relative to its own folder). On the command line a relative DEST is the user's
    # own, against the current folder, and a missing one is created, as before.
    dest = Path(args.dest).expanduser().resolve()
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise CommandError(f"the folder {args.dest} could not be created: {error}") from error
    try:
        result = create_building(spec, dest, args.name, args.overwrite)
    except NewBuildingError as error:
        if out.json:
            out.document("new-building", EXIT_ERROR, {"error": str(error)})
            return EXIT_ERROR
        raise CommandError(str(error)) from error
    counts = (result.get("summary") or {}).get("counts") or {}
    out.line(f"Generated {result['name']} into {result['root']}.")
    if counts:
        out.line("  " + ", ".join(f"{v} {k}" for k, v in counts.items() if v))
    for note in result["notes"]:
        out.line(f"  note: {note}")
    out.document("new-building", EXIT_OK, {"newBuilding": result})
    return EXIT_OK


def cmd_import(args: argparse.Namespace, out: Output) -> int:
    from saengine.importers.project import FORMATS
    from saengine.project.archive import ArchiveError, import_project

    if not Path(args.archive).is_file():
        raise UsageError(f"{args.archive} does not exist")
    if Path(args.archive).suffix.lower() in FORMATS:
        return cmd_import_structural(args, out)
    try:
        result = import_project(args.archive, args.dest, name=args.name, overwrite=args.overwrite)
    except ArchiveError as error:
        problems = getattr(error, "problems", None) or []
        if out.json:
            out.document("import", EXIT_ERROR, {"error": str(error), "problems": problems})
            return EXIT_ERROR
        raise CommandError(str(error)) from error
    out.line(f"Imported {result['name']} into {result['root']} ({result['files']} files).")
    for p in result.get("problems") or []:
        out.line(f"  {p.get('severity', 'warning')}: {p.get('message')}")
    for m in result.get("pending") or []:
        out.line(f"  pending: {m.get('message', m) if isinstance(m, dict) else m}")
    out.document("import", EXIT_OK, {"import": result})
    return EXIT_OK


# ─────────────────────────────── versions ───────────────────────────────


_VERSION_NUMBER = re.compile(r"^(?:[vV](?P<v>\d+)|(?P<n>\d{1,3}))(?P<suffix>(?:\^|~\d*)*)$")


def resolve_version(root: Path, ref: str | None) -> str | None:
    """A version as the CLI shows it (``v3``, or ``3``) as the commit id ``versions`` takes; any
    other reference (a commit id, ``HEAD``, a tag, ``~N``) unchanged. A plain number of four or
    more digits is left as it is: it may be a commit id."""
    if not ref:
        return ref
    match = _VERSION_NUMBER.match(ref.strip())
    if not match:
        return ref
    from saengine.project import versions

    number = int(match["v"] or match["n"])
    listed = versions.list_versions(root, 1_000_000)["versions"]
    for version in listed:
        if version.get("number") == number:
            return f"{version.get('sha') or version['id']}{match['suffix']}"
    last = max((v.get("number") or 0 for v in listed), default=0)
    raise CommandError(
        f"There is no version {ref!r}" + (f" (the versions are v1 to v{last})." if last else ".")
    )


def cmd_versions(args: argparse.Namespace, out: Output) -> int:
    from saengine.project import versions

    project = _open(args.project)
    root = project.root
    action = args.action
    shown = getattr(args, "version", None)  # as the user wrote it, for the messages
    try:
        for name in ("a", "b", "version"):
            if getattr(args, name, None):
                setattr(args, name, resolve_version(root, getattr(args, name)))
        if action == "status":
            result = versions.status(root)
            out.line("Clean." if result.get("clean") else
                     "Changed since the last version: " + ", ".join(
                         PART_TITLES.get(p, p) for p in result.get("changedParts") or []))  # fmt: skip
        elif action == "list":
            result = versions.list_versions(root, args.limit)
            for v in result["versions"]:
                badge = f"  [{v['label'] or 'issued'}]" if v.get("issued") else ""
                out.line(f"v{v.get('number')}  {v['id']}  {v['time']}  {v['authorName']}  "
                         f"{v['message']}{badge}")  # fmt: skip
            if not result["versions"]:
                out.line("No version saved yet.")
        elif action == "save":
            result = versions.save(root, args.message, author=args.author, issued=args.issued,
                                   label=args.label)  # fmt: skip
            v = result["version"]
            out.line(
                f"Saved v{v.get('number')} {v['id']}: {v['message']}"
                if result.get("created")
                else f"Marked v{v.get('number')} {v['id']} issued."
            )
        elif action == "diff":
            result = versions.diff(root, args.a, args.b or "working")
            for part in result.get("parts") or []:
                out.line(f"{part.get('title')}: {part.get('summary')}")
                for change in part.get("changes") or []:
                    out.line(f"  {change.get('kind'):<8} {change.get('what')}")
            if not result.get("parts"):
                out.line("No differences.")
        elif action == "restore":
            result = versions.restore(root, args.version, parts=args.parts or None,
                                      author=args.author, commit=not args.no_commit)  # fmt: skip
            out.line(f"Restored {len(result.get('restored') or [])} file(s) from {shown}.")
        else:  # issue
            result = versions.mark_issued(root, args.version, args.label, author=args.author)
            out.line(f"Marked {shown} issued: {result.get('tag')}")
    except versions.VersionsError as error:
        raise CommandError(str(error)) from error
    for problem in result.get("problems") or []:
        out.line(f"  {problem}")
    out.document(f"versions {action}", EXIT_OK, {"project": _project_json(project),
                                                 "result": result})  # fmt: skip
    return EXIT_OK


# ─────────────────────────────── verify ───────────────────────────────


def cmd_verify(args: argparse.Namespace, out: Output) -> int:
    from saengine.verification.run import main as verify

    argv = ["--out", args.out]
    if args.pdf:
        argv.append("--pdf")
    if args.fast:
        argv.append("--fast")
    if args.cases:
        argv += ["--cases", *args.cases]
    if args.jobs:
        argv += ["--jobs", str(args.jobs)]
    import contextlib
    import io

    # The pack prints its table to stdout: with --json stdout is the JSON document only, so the
    # table goes to stderr (or nowhere with -q).
    sink = sys.stdout if not out.json else io.StringIO() if out.quiet else sys.stderr
    with contextlib.redirect_stdout(sink):
        code = verify(argv)
    # The pack exits 1 when a case falls outside its tolerance: a failing check.
    exit_code = EXIT_OK if code == 0 else EXIT_CHECKS if code == 1 else EXIT_ERROR
    folder = Path(args.out)
    report = folder / "verification.json"
    body: dict[str, Any] = {"out": str(folder.resolve()), "files": []}
    if report.is_file():
        data = json.loads(report.read_text(encoding="utf-8"))
        body["summary"] = data.get("summary")
        body["failedCases"] = [c.get("id") for c in data.get("cases") or [] if not c.get("pass")]
        body["files"].append(str(report.resolve()))
    if args.pdf and (folder / "verification-manual.pdf").is_file():
        body["files"].append(str((folder / "verification-manual.pdf").resolve()))
    out.document("verify", exit_code, body)
    return exit_code


# ─────────────────────────────── the parser ───────────────────────────────


def _version_text() -> str:
    from importlib import metadata

    import saengine

    def version(dist: str) -> str:
        try:
            return metadata.version(dist)
        except metadata.PackageNotFoundError:
            return "not installed"

    return (f"saengine {saengine.__version__} (opensees-studio {version('opensees-studio')}, "
            f"openseespy {version('openseespy')}, Python {sys.version.split()[0]})")  # fmt: skip


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="saengine",
        description="SAEngine without the app: check, analyse and design a project, export its "
        "drawings and models, archive it and keep its versions.",
        epilog="Exit codes: 0 ok, 1 checks fail, 2 usage, 3 error. See docs/cli.md.",
    )
    parser.add_argument("--version", action="version", version=_version_text())
    common = _Parser(add_help=False)
    common.add_argument("--json", action="store_true", help="write one JSON document to stdout")
    common.add_argument("-q", "--quiet", action="store_true", help="no progress on stderr")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    commands.required = True

    def project_command(
        name: str, help_text: str, optional: bool = False, **kwargs: Any
    ) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, parents=[common], help=help_text, description=help_text,
                                  **kwargs)  # fmt: skip
        sub.add_argument("project", nargs="?" if optional else None,
                         help="the project folder or its .saengine file")  # fmt: skip
        return sub

    project_command("validate", "check every part against its schema and rules")
    # The project is optional for argparse only: ``--steps a b <project>`` (nargs="+" takes the
    # project too) is sorted out by cmd_run_all.
    sub = project_command("run-all", "run all steps, as the app's Run All", optional=True)
    sub.add_argument("--steps", nargs="+", action="extend", metavar="STEP",
                     help="only these steps (derive analysis ssi design substructure mep boq "
                     "report drawings; spaces or commas), in Run All's order")  # fmt: skip
    sub.set_defaults(usage_text=sub.format_usage())
    project_command("derive", "derive the analysis model when it is out of date")
    project_command("analyse", "derive if needed and run every analysis case",
                    aliases=["analyze"])  # fmt: skip
    project_command("design", "the member design checks and the foundation design")
    project_command("report", "build the design report (11 Exports/report.pdf)")
    project_command("check", "run the checks, write no deliverables; exit 1 when a check fails")
    project_command("status", "the status of each part, as the app's sidebar shows it")

    sub = project_command("export", "write an export of 11 Exports, a .civil archive, or an "
                          "ETABS text model (.e2k)")  # fmt: skip
    sub.add_argument("target", nargs="?", help="e2k: the .e2k file to write (as --out)")
    sub.add_argument("--format", required=True,
                     choices=["ifc", "dxf", "csv", "pdf", "drawings", "civil", "e2k"])  # fmt: skip
    sub.add_argument("--out", help="the file (the folder for dxf and drawings) to write")
    sub.add_argument("--units", choices=["kN-m", "N-mm"], default="kN-m",
                     help="e2k: the file's units (default: %(default)s)")  # fmt: skip
    sub.add_argument("--lateral", choices=["loads", "coefficient"], default="loads",
                     help="e2k: earthquake as SAEngine's story forces (loads) or as an ETABS "
                     "user coefficient (default: %(default)s)")  # fmt: skip
    sub.add_argument("--size", choices=["A0", "A1", "A2", "A3"],
                     help="drawings: the sheet size (default: Project Settings' drawings)")  # fmt: skip
    sub.add_argument("--include-results", action="store_true",
                     help="civil: also archive the computed results")  # fmt: skip
    sub.add_argument("--include-versions", action="store_true",
                     help="civil: also archive the version history")  # fmt: skip

    sub = commands.add_parser("import", parents=[common],
                              help="extract a .civil archive, or import an ETABS/STAAD/SAP2000 model",
                              description="Extract a .civil archive into DEST/<project name>, or "
                              "create a project there from an ETABS (.e2k), STAAD.Pro (.std) or "
                              "SAP2000 (.s2k) text file.")  # fmt: skip
    sub.add_argument("archive", help="the .civil, .e2k, .std or .s2k file")
    sub.add_argument("dest", help="the folder the project folder is created in")
    sub.add_argument("--name", help="the new project's name (default: the archived or model's one)")
    sub.add_argument("--overwrite", action="store_true", help="into an existing project folder")

    sub = commands.add_parser("new-building", parents=[common],
                              help="generate a new building project from its grids and storeys",
                              description="Generate a new building project into DEST/<name> from "
                              "a JSON spec: the generator's BuildingSpec or the app wizard's "
                              "saengine.newBuilding/1 document (see docs/new-building.md).")  # fmt: skip
    sub.add_argument("spec", help="the spec .json file")
    sub.add_argument("dest", help="the folder the project folder is created in")
    sub.add_argument("--name", help="the new project's name (default: the spec's)")
    sub.add_argument("--overwrite", action="store_true", help="into an existing project folder")

    sub = commands.add_parser("versions", help="the project's version history",
                              description="The project's version history (git).")  # fmt: skip
    actions = sub.add_subparsers(dest="action", metavar="ACTION")
    actions.required = True

    def versions_action(name: str, help_text: str) -> argparse.ArgumentParser:
        action = actions.add_parser(name, parents=[common], help=help_text)
        action.add_argument("project", help="the project folder or its .saengine file")
        return action

    versions_action("status", "what changed since the last version")
    action = versions_action("list", "the versions, newest first")
    action.add_argument("--limit", type=int, default=200)
    action = versions_action("save", "save the current files as a new version")
    action.add_argument("-m", "--message", required=True)
    action.add_argument("--author", help='"Name <email>"')
    action.add_argument("--issued", action="store_true", help="also mark it issued")
    action.add_argument("--label", help='the issue label ("Issued for construction")')
    action = versions_action("diff", "the differences between two versions")
    action.add_argument("a", nargs="?", help="from (default: the last version)")
    action.add_argument("b", nargs="?", help="to (default: the current files)")
    action = versions_action("restore", "bring back parts of a version")
    action.add_argument("version")
    action.add_argument("--parts", nargs="+", metavar="PART", help="part ids (default: all)")
    action.add_argument("--author", help='"Name <email>"')
    action.add_argument("--no-commit", action="store_true", help="leave as unsaved changes")
    action = versions_action("issue", "mark a version issued")
    action.add_argument("version")
    action.add_argument("label")
    action.add_argument("--author", help='"Name <email>"')

    sub = commands.add_parser("verify", parents=[common], help="run the verification pack")
    sub.add_argument("--out", default="verification", help="output folder (default: %(default)s)")
    sub.add_argument("--pdf", action="store_true", help="also write the Verification Manual PDF")
    sub.add_argument("--fast", action="store_true", help="skip the slow cases")
    sub.add_argument("--cases", nargs="+", metavar="ID", help="only these cases")
    sub.add_argument("--jobs", type=int, help="parallel processes")

    register_codepack(commands, common)
    return parser


HANDLERS = {
    "validate": cmd_validate,
    "run-all": cmd_run_all,
    "derive": cmd_step,
    "analyse": cmd_step,
    "analyze": cmd_step,
    "design": cmd_step,
    "report": cmd_step,
    "check": cmd_check,
    "status": cmd_status,
    "export": cmd_export,
    "import": cmd_import,
    "new-building": cmd_new_building,
    "versions": cmd_versions,
    "verify": cmd_verify,
    "codepack": cmd_codepack,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Runs the command line; returns its exit code."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    words = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parser.parse_args(words)
    except ArgumentsError as error:
        return _arguments_error(error, words)
    except SystemExit as exit_:  # --help, --version
        return int(exit_.code or 0) if not isinstance(exit_.code, str) else EXIT_USAGE
    if args.command == "analyze":
        args.command = "analyse"
    if args.command == "package":
        args.command = "codepack"
    out = Output(getattr(args, "json", False), getattr(args, "quiet", False))
    command = (
        f"{args.command} {args.action}"
        if args.command in ("versions", "codepack")
        else args.command
    )
    try:
        return HANDLERS[args.command](args, out)
    except ArgumentsError as error:
        return _arguments_error(error, words)
    except UsageError as error:
        return _fail(out, command, EXIT_USAGE, str(error))
    except CommandError as error:
        return _fail(out, command, EXIT_ERROR, str(error))
    except KeyboardInterrupt:
        return _fail(out, command, EXIT_ERROR, "interrupted")
    except Exception as error:  # noqa: BLE001 - any failure is reported, with exit 3
        return _fail(out, command, EXIT_ERROR, f"{type(error).__name__}: {error}")


def _arguments_error(error: ArgumentsError, words: Sequence[str]) -> int:
    """As argparse prints it (usage and message on stderr), plus the JSON document."""
    sys.stderr.write(error.usage)
    message = str(error)
    prog = f"saengine {error.command}".strip()
    print(f"{prog}: error: {message}", file=sys.stderr)
    if "--json" in words:
        Output(True).document(error.command or _guess_command(words), EXIT_USAGE,
                              {"error": message, "usage": error.usage.strip()})  # fmt: skip
    return EXIT_USAGE


def _guess_command(words: Sequence[str]) -> str:
    """The command of arguments argparse rejected at the top level (or "")."""
    names = [w for w in words if not w.startswith("-")]
    if not names or names[0] not in HANDLERS:
        return ""
    if names[0] == "versions" and len(names) > 1:
        return f"versions {names[1]}"
    return names[0]


def _fail(out: Output, command: str, code: int, message: str) -> int:
    print(f"saengine {command}: {message}", file=sys.stderr)
    out.document(command, code, {"error": message})
    return code


if __name__ == "__main__":
    sys.exit(main())

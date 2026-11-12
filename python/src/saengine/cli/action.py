"""``saengine action``: the shared editing actions (:mod:`saengine.actions`) from the command line.

    saengine action list [--kind edit|run|query] [--json]
    saengine action describe <name> [--json]
    saengine action run <name> --params '<json>' [--project DIR] [--dry-run] [--json]
    saengine action batch <steps.json> [--project DIR] [--dry-run] [--json]

``run`` and ``batch`` write the changed part files (and save a version when the project keeps
versions) unless ``--dry-run``; a refused step changes nothing and exits 1.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def register(commands: Any, common: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Adds ``action`` and its verbs to the subparsers ``commands`` of ``saengine``."""
    sub = commands.add_parser(
        "action",
        help="the shared editing actions: list, describe, run one, run a batch",
        description="Typed, validated edits of a project (the app's and the assistant's): build "
        "a whole project from an empty folder to the report. See docs/actions.md.",
    )
    verbs = sub.add_subparsers(dest="action", metavar="ACTION")
    verbs.required = True
    parser = verbs.add_parser("list", parents=[common], help="the actions, by name")
    parser.add_argument("--kind", choices=["edit", "run", "query"], help="only this kind")
    parser = verbs.add_parser(
        "describe", parents=[common], help="one action: its parameters (JSON Schema) and an example"
    )
    parser.add_argument("name")
    for verb, help_text in (
        ("run", "run one action on a project"),
        ("batch", "run a batch file of actions (a list of {action, params}) on a project"),
    ):
        parser = verbs.add_parser(verb, parents=[common], help=help_text, description=help_text)
        if verb == "run":
            parser.add_argument("name")
            parser.add_argument("--params", default="{}", help="the parameters as JSON")
        else:
            parser.add_argument("steps", help="the batch file (.json)")
        parser.add_argument(
            "--project",
            default=".",
            help="the project folder (project.create: the folder to create it "
            "in); default: the current folder",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="check and report, write nothing"
        )
        parser.add_argument(
            "--keep-going",
            action="store_true",
            help="after a refused step run the others too (to see every "
            "problem); still nothing is written",
        )
    return sub


def _list(args: argparse.Namespace, out: Any) -> int:
    from saengine.actions import list_actions

    infos = list_actions(args.kind)
    width = max((len(a.name) for a in infos), default=10)
    for a in infos:
        out.line(f"{a.name:<{width}}  {a.kind:<5}  {a.summary}")
    out.document(
        "action list",
        EXIT_OK,
        {
            "actions": [
                {"name": a.name, "kind": a.kind, "summary": a.summary, "parts": a.parts}
                for a in infos
            ]
        },
    )
    return EXIT_OK


def _describe(args: argparse.Namespace, out: Any) -> int:
    from saengine.actions import UnknownAction, get

    try:
        info = get(args.name)
    except UnknownAction as error:
        return _usage(out, "action describe", str(error))
    out.line(f"{info.name} ({info.kind}): {info.summary}")
    out.line(f"Parts: {', '.join(info.parts) or '-'}")
    out.line("Parameters:")
    schema = info.params_schema
    required = set(schema.get("required") or [])
    for name, prop in (schema.get("properties") or {}).items():
        mark = " (required)" if name in required else ""
        out.line(f"  {name}{mark}: {prop.get('description') or prop.get('title') or ''}")
    if info.example is not None:
        out.line(f"Example: {json.dumps(info.example, ensure_ascii=False)}")
    out.document("action describe", EXIT_OK, {"action": info.model_dump(mode="json")})
    return EXIT_OK


def _usage(out: Any, command: str, message: str) -> int:
    print(f"saengine {command}: {message}", file=sys.stderr)
    out.document(command, EXIT_USAGE, {"error": message})
    return EXIT_USAGE


def _run(args: argparse.Namespace, out: Any) -> int:
    from saengine.actions import load_steps, run_actions

    command = f"action {args.action}"
    if args.action == "run":
        try:
            params = json.loads(args.params)
        except ValueError as error:
            return _usage(out, command, f"--params is not JSON: {error}")
        steps: list[dict[str, Any]] = [{"action": args.name, "params": params}]
    else:
        path = Path(args.steps)
        try:
            steps = load_steps(path.read_text(encoding="utf-8"))
        except OSError as error:
            return _usage(out, command, f"{args.steps} cannot be read: {error}")
        except ValueError as error:
            return _usage(out, command, f"{args.steps}: {error}")
    root = Path(args.project).expanduser().resolve()
    total = len(steps)

    result = run_actions(root, steps, write=not args.dry_run, stop_on_error=not args.keep_going)
    for index, r in enumerate(result.results):
        mark = "ok" if r.ok else "REFUSED"
        out.line(f"[{index + 1}/{total}] {r.action or '?'}: {mark}: {r.message}")
        for warning in r.warnings:
            out.line(f"    warning: {warning}")
        for p in r.problems:
            where = f"{p.part}: " if p.part else ""
            field = f"{p.field} = {json.dumps(p.value, ensure_ascii=False)}: " if p.field else ""
            out.line(f"    problem: {where}{field}{p.reason}")
    if result.ok:
        changed = sorted(result.changes)
        if args.dry_run:
            out.line(f"Dry run: {len(changed)} file(s) would change: {', '.join(changed) or '-'}")
        else:
            out.line(
                f"Wrote {len(result.written)} file(s)."
                + (f" Saved version: {result.version.get('message')}." if result.version else "")
            )
    else:
        out.line(
            f"Step {(result.failed_step or 0) + 1} was refused: nothing was changed"
            + (" (the files before a run step were written already)." if result.written else ".")
        )
    body = result.model_dump(mode="json", exclude={"changes"})
    body["changed"] = sorted(result.changes)
    body["project"] = str(root)
    body["dryRun"] = bool(args.dry_run)
    code = EXIT_OK if result.ok else EXIT_FAILED
    out.document(command, code, {"batch": body})
    return code


VERBS = {"list": _list, "describe": _describe, "run": _run, "batch": _run}


def cmd_action(args: argparse.Namespace, out: Any) -> int:
    """The handler of ``saengine action <verb>``."""
    return VERBS[args.action](args, out)

"""``saengine codepack``: list, show, create, validate and compare design code packs.

    saengine codepack list [--root PROJECT] [--json]
    saengine codepack show <id> [--root PROJECT] [--json]
    saengine codepack new <id> [--name NAME] [--extends bnbc2020] --dest <dir> [--root PROJECT]
    saengine codepack validate <dir> [--json]
    saengine codepack diff <a> <b> [--root PROJECT] [--json]

<id>, <a> and <b> are pack ids (built-in, user, or the project's with --root) or pack folders
(a folder with a pack.json, resolved against the installed packs).
``validate`` exits 1 when the pack has errors; ``diff`` lists the differences of the two resolved
packs (``+`` only in b, ``-`` only in a, ``~`` changed). See docs/code-packs.md.

:func:`register` adds the command to ``saengine``'s parser (cli/main.py); :func:`cmd_codepack`
is its handler. ``python -m saengine.cli.codepack ...`` runs it alone.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

EXIT_OK, EXIT_CHECKS, EXIT_USAGE, EXIT_ERROR = 0, 1, 2, 3


def register(commands: Any, common: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Adds ``codepack`` and its actions to the subparsers ``commands`` of ``saengine``."""
    sub = commands.add_parser(
        "codepack",
        help="design code packs: list, show, new, validate, diff",
        description="Design code packs: the code's reference data and factors, as a folder "
        "(see docs/code-packs.md).",
    )
    actions = sub.add_subparsers(dest="action", metavar="ACTION")
    actions.required = True

    def action(name: str, help_text: str, root: bool = True) -> argparse.ArgumentParser:
        parser = actions.add_parser(name, parents=[common], help=help_text, description=help_text)
        if root:
            parser.add_argument("--root", help="a project folder: also its own packs")
        return parser

    action("list", "the installed packs: built-in, user and the project's")
    parser = action("show", "a pack's details: coverage, inheritance, sources, problems")
    parser.add_argument("pack", help="pack id or pack folder")
    parser = action("new", "create a new pack that extends another one")
    parser.add_argument("id", help="the new pack's id (lower-case letters, digits, hyphens)")
    parser.add_argument("--name", default="", help="its name (default: the id)")
    parser.add_argument("--extends", default="bnbc2020",
                        help="the pack it starts from (default: %(default)s; '' for none)")  # fmt: skip
    parser.add_argument("--edition", default="", help="the code and edition it follows")
    parser.add_argument("--country", default="", help="country or region")
    parser.add_argument("--author", default="", help="who prepares it")
    parser.add_argument("--dest", required=True, help="the folder the pack folder is created in")
    parser = action("validate", "check a pack folder; exit 1 when it has errors")
    parser.add_argument("path", help="the pack folder")
    parser = action("diff", "the table/key differences of two packs")
    parser.add_argument("a", help="pack id or folder")
    parser.add_argument("b", help="pack id or folder")
    return sub


def _root(args: argparse.Namespace) -> Path | None:
    root = getattr(args, "root", None)
    return Path(root) if root else None


def _problem_text(problem: Any) -> str:
    where = problem.file or (f"data/{problem.table}.json" if problem.table else "pack")
    return f"{problem.severity}: {where}: {problem.message}"


def cmd_list(args: argparse.Namespace, out: Any) -> int:
    from saengine.codes import registry

    packs = registry.list_packs(_root(args))
    for info in packs:
        errors = sum(p.severity == "error" for p in info.problems)
        notes = [info.scope]
        if info.extends:
            notes.append(f"extends {info.extends}")
        if not info.effective:
            notes.append(f"hidden by the {info.shadowedBy} pack")
        if info.hooks:
            notes.append("hooks, trusted" if info.trusted else "hooks, not trusted")
        if errors:
            notes.append(f"{errors} error{'s' * (errors != 1)}")
        out.line(f"{info.id:<16} {info.name}  ({', '.join(notes)})")
    if not packs:
        out.line("no code packs found")
    out.document("codepack list", EXIT_OK,
                 {"packs": [p.model_dump(mode="json") for p in packs]})  # fmt: skip
    return EXIT_OK


def cmd_show(args: argparse.Namespace, out: Any) -> int:
    from saengine.codes import registry

    root = _root(args)
    folder = Path(args.pack)
    is_folder = (folder / "pack.json").is_file()
    info = registry.validate(folder, root) if is_folder else registry.info(args.pack, root)
    manifest: dict[str, Any] = {}
    tables: dict[str, dict[str, Any]] = {}
    if info.usable:
        pack = registry.load_path(folder, root) if is_folder else registry.load(args.pack, root)
        manifest = pack.info.model_dump(mode="json", by_alias=True, exclude_none=True)
        for name in pack.tables():
            tables[name] = {"providedBy": pack.provided_by(name), "sources": pack.source(name)}
    out.line(f"{info.id}: {info.name}")
    for key in ("edition", "country", "region", "version", "extends"):
        value = getattr(info, key)
        if value:
            out.line(f"  {key}: {value}")
    out.line(f"  scope: {info.scope}  ({info.path})")
    if len(info.chain) > 1:
        out.line(f"  inheritance: {' -> '.join(info.chain)}")
    for key in ("author", "licence"):
        if manifest.get(key):
            out.line(f"  {key}: {manifest[key]}")
    if tables:
        out.line("  tables:")
    for name, table in tables.items():
        own = table["providedBy"] == info.id and name in (manifest.get("covers") or [])
        origin = "own" if own else "inherited"
        refs = "; ".join(str(r) for r in table["sources"][:2])
        out.line(f"    {name:<20} {origin}{f'  ({refs})' if refs else ''}")
    if info.hooks:
        out.line(f"  hooks: {manifest.get('hooks', 'yes')} "
                 f"({'trusted' if info.trusted else 'not trusted: they do not run'})")  # fmt: skip
    for problem in info.problems:
        out.line(f"  {_problem_text(problem)}")
    out.document("codepack show", EXIT_OK, {"pack": info.model_dump(mode="json"),
                                             "manifest": manifest, "tables": tables})  # fmt: skip
    return EXIT_OK


def cmd_new(args: argparse.Namespace, out: Any) -> int:
    from saengine.codes.template import TemplateError, new_pack

    try:
        folder = new_pack(args.dest, args.id, args.name, args.extends or None,
                          edition=args.edition, country=args.country, author=args.author,
                          project_root=_root(args))  # fmt: skip
    except TemplateError as error:
        print(f"saengine codepack new: {error}", file=sys.stderr)
        out.document("codepack new", EXIT_USAGE, {"error": str(error)})
        return EXIT_USAGE
    out.line(f"created {folder}")
    out.line(f"  edit {folder / 'pack.json'} and the tables you change in {folder / 'data'}")
    out.line(f'  then: saengine codepack validate "{folder}"')
    out.document("codepack new", EXIT_OK, {"path": str(folder.resolve()),
                                            "manifest": str((folder / 'pack.json').resolve())})  # fmt: skip
    return EXIT_OK


def cmd_validate(args: argparse.Namespace, out: Any) -> int:
    from saengine.codes.template import validate_pack

    result = validate_pack(args.path, _root(args))
    for problem in result.problems:
        out.line(str(problem))
    errors = sum(p.level == "error" for p in result.problems)
    warnings = len(result.problems) - errors
    out.line(f"{result.id or args.path}: {'ok' if result.ok else 'not usable'}"
             f" ({errors} error{'s' * (errors != 1)}, {warnings} warning{'s' * (warnings != 1)})")  # fmt: skip
    code = EXIT_OK if result.ok else EXIT_CHECKS
    out.document("codepack validate", code, result.to_json())
    return code


def cmd_diff(args: argparse.Namespace, out: Any) -> int:
    from saengine.codes.template import diff_packs

    differences = diff_packs(args.a, args.b, _root(args))
    for difference in differences:
        out.line(str(difference))
    out.line(f"{len(differences)} difference{'s' * (len(differences) != 1)}")
    out.document("codepack diff", EXIT_OK, {"a": args.a, "b": args.b,
                                             "differences": [d.__dict__ for d in differences]})  # fmt: skip
    return EXIT_OK


ACTIONS = {
    "list": cmd_list,
    "show": cmd_show,
    "new": cmd_new,
    "validate": cmd_validate,
    "diff": cmd_diff,
}


def cmd_codepack(args: argparse.Namespace, out: Any) -> int:
    """The handler of ``saengine codepack <action>``. A pack that is not found, or cannot be
    loaded, is a usage error (exit 2) for show and diff."""
    from saengine.codes.registry import CodePackError
    from saengine.codes.template import TemplateError

    try:
        return ACTIONS[args.action](args, out)
    except (CodePackError, TemplateError, FileNotFoundError) as error:
        message = str(error).strip("'\"") or type(error).__name__
        print(f"saengine codepack {args.action}: {message}", file=sys.stderr)
        out.document(f"codepack {args.action}", EXIT_USAGE, {"error": message})
        return EXIT_USAGE


def main(argv: Sequence[str] | None = None) -> int:
    """``saengine codepack ...`` alone (``python -m saengine.cli.codepack list``), with
    saengine's parser conventions and output; the same as the registered command."""
    import importlib

    cli = importlib.import_module("saengine.cli.main")

    words = ["codepack", *(sys.argv[1:] if argv is None else argv)]
    parser = cli._Parser(prog="saengine")
    common = cli._Parser(add_help=False)
    common.add_argument("--json", action="store_true", help="write one JSON document to stdout")
    common.add_argument("-q", "--quiet", action="store_true", help="no progress on stderr")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    commands.required = True
    register(commands, common)
    try:
        args = parser.parse_args(words)
    except cli.ArgumentsError as error:
        return cli._arguments_error(error, words)
    except SystemExit as exit_:  # --help
        return int(exit_.code or 0) if not isinstance(exit_.code, str) else EXIT_USAGE
    return cmd_codepack(args, cli.Output(args.json, args.quiet))


if __name__ == "__main__":
    sys.exit(main())

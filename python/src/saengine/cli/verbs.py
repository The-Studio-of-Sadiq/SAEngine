"""``saengine <noun> <verb>``: every shared editing action as a terminal command.

The commands are made from the catalogue (:mod:`saengine.actions`), never written one by one:
the action ``load.pattern.add`` is ``saengine load pattern add``, its parameters are options
(``--id EQP --type Dead``), and it runs through the same batch runner as the app and the
assistant (:func:`saengine.cli.action.execute`). So a new action is a new command, with its help
text, at once::

    saengine grid set --x 6000 6000 --y 5000 --project House
    saengine storeys set --count 3 --height 3000 --project House
    saengine member add column --points all --type C400 --project House
    saengine load pattern add EQP --type Dead --name Equipment --project House
    saengine run all --project House
    saengine design apply --project House
    saengine undo --project House

Options take a value as JSON when it parses as JSON (numbers, lists, objects, true/false), else
as text; a list option takes several values (``--x 6000 6000``). ``--params '<json>'`` gives
parameters as one JSON object (options override it). Every command has ``--project DIR``
(default: the current folder), ``--dry-run``, ``--keep-going``, ``--json`` and ``--help``;
``saengine <noun>`` alone lists its verbs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_USAGE = 2

#: Commands in the engineer's words for actions named otherwise: words -> action.
ALIASES: dict[tuple[str, ...], str] = {
    ("member", "add", "column"): "columns.place",
    ("member", "add", "beam"): "beams.place",
    ("member", "add", "wall"): "walls.place",
    ("member", "add", "slab"): "slabs.place",
    ("member", "add", "footing"): "footing.set",
    ("member", "list"): "members.list",
    ("member", "copy"): "members.copy_to_storeys",
    ("design", "apply"): "design.reinforcement.apply",
    ("undo",): "edit.undo",
    ("redo",): "edit.redo",
    ("history",): "edit.history",
}

#: Commands of ``saengine`` that existed before the action commands. Their name is taken by an
#: action command only when the next word is one of its verbs (``saengine design apply``, but
#: ``saengine design <project>`` stays the design step).
SHARED_ROOTS = frozenset({"design", "export"})

#: The parameter a command's first plain words go to, when it is not the action's only
#: required one (``saengine run step analyse``).
POSITIONAL: dict[str, str] = {"run.step": "step", "actions.help": "name"}


def _words(name: str) -> tuple[str, ...]:
    return tuple(w.replace("_", "-") for w in name.split("."))


def tree() -> dict[tuple[str, ...], str]:
    """Every command (its words) -> its action: the catalogue's names and the aliases."""
    from saengine.actions import list_actions

    out = {_words(a.name): a.name for a in list_actions()}
    out.update(ALIASES)
    return out


def _children(commands: dict[tuple[str, ...], str], prefix: tuple[str, ...]) -> list[str]:
    return sorted(
        {w[len(prefix)] for w in commands if w[: len(prefix)] == prefix and len(w) > len(prefix)}
    )


def _match(words: Sequence[str]) -> tuple[tuple[str, ...], str | None, int] | None:
    """The command ``words`` start with: (the words matched, the action or None for a group
    such as ``saengine load``, how many words), or None when they are no action command."""
    commands = tree()
    plain = []
    for w in words:
        if w.startswith("-"):
            break
        plain.append(w)
    if not plain:
        return None
    if not _children(commands, (plain[0],)) and (plain[0],) not in commands:
        return None
    if plain[0] in SHARED_ROOTS and (
        len(plain) < 2 or plain[1] not in _children(commands, (plain[0],))
    ):
        return None
    best: tuple[tuple[str, ...], str | None, int] | None = None
    for n in range(1, len(plain) + 1):
        key = tuple(plain[:n])
        if key in commands:
            best = (key, commands[key], n)
        elif _children(commands, key):
            if best is None or best[1] is None:
                best = (key, None, n)
        else:
            break
    return best


def handles(words: Sequence[str]) -> bool:
    """Whether ``words`` are an action command (else the classic commands parse them)."""
    return _match([w for w in words if w not in ("--json", "-q", "--quiet")]) is not None


# ── the parameters as options ──


def _types(schema: dict[str, Any]) -> set[str]:
    """The JSON types a property accepts (anyOf and enums looked through)."""
    out: set[str] = set()
    t = schema.get("type")
    if isinstance(t, list):
        out |= set(t)
    elif isinstance(t, str):
        out.add(t)
    if "enum" in schema or "const" in schema:
        out.add("string")
    for sub in schema.get("anyOf") or schema.get("oneOf") or []:
        out |= _types(sub)
    if "$ref" in schema or "allOf" in schema:
        out.add("object")
    return out


def _value(raw: str, types: set[str]) -> Any:
    """A word as the parameter's value: JSON when it parses (and is not plain text for a text
    parameter), else the text."""
    if types == {"string"} or types == {"string", "null"}:
        return raw
    try:
        value = json.loads(raw)
    except ValueError:
        return raw
    if (
        isinstance(value, str | int | float)
        and "string" in types
        and not ({"number", "integer"} & types)
    ):
        return raw
    return value


def _convert(values: list[str] | str | None, schema: dict[str, Any]) -> Any:
    types = _types(schema)
    if values is None:
        return None
    if isinstance(values, str):
        return _value(values, types)
    if len(values) == 1:
        one = _value(values[0], types)
        if (
            "array" in types
            and not isinstance(one, list)
            and not (one == "all" and "string" in types)
        ):
            return [one]
        return one
    items = schema.get("items") or next(
        (s.get("items") for s in schema.get("anyOf") or [] if s.get("type") == "array"), {}
    )
    return [_value(v, _types(items or {})) for v in values]


def _kebab(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"-\1", name).lower()


def _parser(
    prog: str, info: Any
) -> tuple[argparse.ArgumentParser, dict[str, dict[str, Any]], str | None]:
    from saengine.cli.main import _Parser

    schema = info.params_schema
    properties: dict[str, dict[str, Any]] = schema.get("properties") or {}
    required = list(schema.get("required") or [])
    positional = POSITIONAL.get(info.name) or (required[0] if len(required) == 1 else None)
    example = f"\nexample: --params '{json.dumps(info.example)}'" if info.example else ""
    parser = _Parser(
        prog=prog,
        description=f"{info.summary} (action {info.name}, {info.kind})",
        epilog=(f"The first plain words are --{positional}. " if positional else "")
        + "Values are JSON when they parse as JSON, else text."
        + example,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    if positional:
        parser.add_argument(
            "_positional", nargs="*", metavar=positional.upper(), help=argparse.SUPPRESS
        )
    for name, prop in properties.items():
        types = _types(prop)
        flags = [f"--{name}"] + ([f"--{_kebab(name)}"] if _kebab(name) != name else [])
        text = prop.get("description") or prop.get("title") or ""
        if "enum" in prop:
            text += f" ({' | '.join(map(str, prop['enum']))})"
        if name in required:
            text += " (required)"
        if "default" in prop and prop["default"] is not None:
            text += f" [default: {json.dumps(prop['default'])}]"
        if types <= {"boolean", "null"}:
            parser.add_argument(
                *flags, dest=name, nargs="?", const="true", metavar="BOOL", help=text
            )
        elif "array" in types:
            parser.add_argument(*flags, dest=name, nargs="+", metavar="VALUE", help=text)
        else:
            parser.add_argument(*flags, dest=name, metavar="VALUE", help=text)
    parser.add_argument("--params", help="the parameters as one JSON object (options override it)")
    parser.add_argument(
        "--project", default=".", help="the project folder (default: the current folder)"
    )
    parser.add_argument("--dry-run", action="store_true", help="check and report, write nothing")
    parser.add_argument("--keep-going", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", help="write one JSON document to stdout")
    parser.add_argument("-q", "--quiet", action="store_true", help="no progress on stderr")
    return parser, properties, positional


def _list_group(
    commands: dict[tuple[str, ...], str], prefix: tuple[str, ...], out: Any, code: int
) -> None:
    from saengine.actions import get

    out.line(
        f"saengine {' '.join(prefix)} <verb> [options]   (--help after a verb for its options)"
    )
    rows = []
    for words, name in sorted(commands.items()):
        if words[: len(prefix)] == prefix and len(words) > len(prefix):
            rows.append((" ".join(words), get(name).summary, name))
    width = max((len(r[0]) for r in rows), default=10)
    for command, summary, _name in rows:
        out.line(f"  {command:<{width}}  {summary}")
    out.document(
        " ".join(prefix),
        code,
        {"commands": [{"command": c, "action": n, "summary": s} for c, s, n in rows]},
    )


def run(words: Sequence[str]) -> int:
    """Runs an action command (``handles(words)`` is true)."""
    from saengine.actions import get
    from saengine.cli.action import execute
    from saengine.cli.main import ArgumentsError, Output, _arguments_error

    as_json = "--json" in words
    matched = _match([w for w in words if w not in ("--json", "-q", "--quiet")])
    assert matched is not None
    key, name, _n = matched
    rest = list(words)
    for w in key:  # the command's words (the flags before them stay)
        rest.remove(w)
    commands = tree()
    if name is None:
        code = EXIT_OK if any(w in ("-h", "--help") for w in rest) else EXIT_USAGE
        _list_group(commands, key, Output(as_json), code)
        return code
    info = get(name)
    prog = f"saengine {' '.join(key)}"
    parser, properties, positional = _parser(prog, info)
    try:
        args = parser.parse_args(rest)
    except ArgumentsError as error:
        return _arguments_error(error, words)
    except SystemExit as exit_:  # --help
        return int(exit_.code or 0) if not isinstance(exit_.code, str) else EXIT_USAGE
    out = Output(args.json, args.quiet)
    command = " ".join(key)
    params: dict[str, Any] = {}
    if args.params:
        try:
            loaded = json.loads(args.params)
        except ValueError as error:
            return _usage(out, command, f"--params is not JSON: {error}")
        if not isinstance(loaded, dict):
            return _usage(out, command, "--params is not a JSON object")
        params.update(loaded)
    if positional and getattr(args, "_positional", None):
        params[positional] = _convert(args._positional, properties.get(positional, {}))
    for prop_name, prop in properties.items():
        value = getattr(args, prop_name, None)
        if value is not None:
            params[prop_name] = _convert(value, prop)
    root = Path(args.project).expanduser().resolve()
    return execute(
        out, command, root, [{"action": name, "params": params}], args.dry_run, args.keep_going
    )


def _usage(out: Any, command: str, message: str) -> int:
    print(f"saengine {command}: {message}", file=sys.stderr)
    out.document(command, EXIT_USAGE, {"error": message})
    return EXIT_USAGE


def help_text() -> str:
    """The action commands' roots, for ``saengine --help``."""
    roots = sorted({w[0] for w in tree()})
    return (
        "Model commands (the shared editing actions; saengine <noun> for its verbs): "
        + ", ".join(roots)
        + "."
    )

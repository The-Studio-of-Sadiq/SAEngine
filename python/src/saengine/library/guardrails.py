"""Input guardrails: impossible values are blocked, unusual ones warned about, the same way on
every entry path (U2 of the UI/UX round, decision "Guardrails on input" of 2026-11-11).

The rules live in one data file, ``library/data/guardrails.json``. Each rule names the file kind
it belongs to (``materials``, ``objects``, ``floorPlan``, ``memberLoads``), the fields it reads
(dotted paths from an entry of a list file, or from the document root; ``*`` stands for any key
or index), and lists of ``block`` and ``warn`` limits. A limit with ``fromPack`` takes its value
from the code pack in force (the code's own limit, e.g. the least f'c of structural concrete or
the bar sizes of its standard); every other number is an SAEngine practice sanity limit and is
reported as such. Zero and negative sizes are refused by the Pydantic models themselves
(``gt=0``), which stay the first layer: these rules come on top of them.

Who uses them:

- :func:`saengine.library.check.check_library` (the editors' ``saengine.library.check``, and so
  ``saengine validate`` and every caller that checks a file before writing it, the AI assistant's
  change sets among them) reports the problems: ``error`` for a block, ``warning`` for a warn;
- the workbench reads :func:`resolved_rules` (``library/limits``) and checks each field as it is
  typed, so a blocked value is refused at the field with the reason; the generated
  ``projectLibraries.generated.ts`` carries the practice rules for use before the backend answers
  (the New Project wizard's spans and storey heights);
- :class:`saengine.library.generator.BuildingSpec` (the wizard, ``saengine new``, templates)
  checks its spans, storey heights and counts with :func:`building_problems`.
"""

from __future__ import annotations

import json
import math
from functools import cache
from importlib import resources
from itertools import pairwise
from typing import Any

PRACTICE = "SAEngine practice"


@cache
def rules_document() -> dict[str, Any]:
    """The rule file as written (practice limits; pack limits still as ``fromPack`` names)."""
    text = resources.files("saengine.library").joinpath("data/guardrails.json").read_text("utf-8")
    return json.loads(text)


def _current_pack() -> Any:
    try:
        from saengine.codes import context as code_context

        return code_context.current()
    except Exception:  # noqa: BLE001 - no pack machinery: the practice limits only
        return None


def _pack_value(pack: Any, ref: str) -> tuple[Any, str] | None:
    """The value ``table.key`` of ``pack`` and its clause reference, or None when it has none."""
    if pack is None:
        return None
    table_name, _, key = ref.partition(".")
    try:
        if not pack.has(table_name):
            return None
        table = pack.table(table_name)
    except Exception:  # noqa: BLE001 - a pack without the table: no such limit
        return None
    value = getattr(table, key, None)
    if value is None:
        return None
    if hasattr(value, "keys"):  # a group of lists (bar sizes by use): their union
        sizes: set[float] = set()
        for name in value.keys():  # noqa: SIM118 - a table group: iterating it gives fields
            sizes.update(float(v) for v in value[name])
        value = sorted(sizes)
    try:
        from saengine.codes import context as code_context

        name = code_context.code_name(pack)
    except Exception:  # noqa: BLE001
        name = getattr(pack, "name", "the code pack")
    clause = (getattr(table, "sources", None) or {}).get(key) or getattr(table, "source", "")
    clause = clause.split(";")[0].strip()
    if not clause:
        return value, name
    return value, clause if clause.startswith(name) else f"{name}: {clause}"


def _resolve_limit(limit: dict[str, Any], pack: Any) -> dict[str, Any] | None:
    out = {k: v for k, v in limit.items() if k != "fromPack"}
    out.setdefault("source", PRACTICE)
    refs = limit.get("fromPack")
    if refs:
        for bound, ref in refs.items():
            found = _pack_value(pack, ref)
            if found is None:
                return None  # the pack does not give this limit: it does not apply
            out[bound], out["source"] = found
    return out


def resolved_rules(pack: Any = None, kind: str | None = None) -> list[dict[str, Any]]:
    """The rules with the limits of ``pack`` (default: the pack in force) filled in; a pack
    limit the pack does not give is left out. ``kind``: only the rules of that file kind."""
    pack = pack if pack is not None else _current_pack()
    out = []
    for rule in rules_document()["rules"]:
        if kind is not None and rule["kind"] != kind:
            continue
        resolved = dict(rule)
        for level in ("block", "warn"):
            resolved[level] = [
                r for r in (_resolve_limit(lim, pack) for lim in rule.get(level, ())) if r
            ]
        out.append(resolved)
    return out


def rule(rule_id: str, pack: Any = None) -> dict[str, Any]:
    """One resolved rule by its id."""
    return next(r for r in resolved_rules(pack) if r["id"] == rule_id)


# ───────────────────────────────── evaluation ─────────────────────────────────


def _num(value: float) -> str:
    return f"{value:g}"


def _with_unit(value: float, unit: str | None) -> str:
    return f"{_num(value)} {unit}" if unit else _num(value)


def violation(limit: dict[str, Any], value: float, unit: str | None = None) -> str | None:
    """Why ``value`` breaks ``limit`` (without the field's name), or None when it keeps it."""
    if not isinstance(value, int | float) or isinstance(value, bool) or not math.isfinite(value):
        return None
    allowed = limit.get("oneOf")
    if allowed is not None:
        if any(abs(value - a) < 1e-6 for a in allowed):
            return None
        sizes = ", ".join(_num(a) for a in allowed)
        return f"{_with_unit(value, unit)} is {limit['reason']} ({sizes})"
    low, high = limit.get("min"), limit.get("max")
    if low is not None and value < low:
        return f"{_with_unit(value, unit)} is below {_with_unit(low, unit)}: {limit['reason']}"
    if high is not None and value > high:
        return f"{_with_unit(value, unit)} is above {_with_unit(high, unit)}: {limit['reason']}"
    return None


def _capital(text: str) -> str:
    """The text with a capital first letter, unless it starts with a symbol (f'c, fy)."""
    first = text.split(" ", 1)[0]
    words = first.isalpha() and (len(first) > 2 or first in ("a", "an"))
    return text[:1].upper() + text[1:] if words else text


def _sentence(what: str, detail: str, source: str) -> str:
    return f"{_capital(f'{what} {detail}')} ({source})."


def judge(rule: dict[str, Any], value: float, what: str | None = None) -> tuple[str, str] | None:
    """(severity, message) of ``value`` against ``rule``: the first block it breaks (``error``),
    else the first warn (``warning``); None when it is within them."""
    for level, severity in (("block", "error"), ("warn", "warning")):
        for limit in rule.get(level, ()):
            detail = violation(limit, value, rule.get("unit"))
            if detail:
                return severity, _sentence(what or rule["what"], detail, limit["source"])
    return None


def _count(rule: dict[str, Any], count: int, where: str = "") -> tuple[str, str] | None:
    for level, severity in (("block", "error"), ("warn", "warning")):
        for limit in rule.get(level, ()):
            high = limit.get("max")
            if high is not None and count > high:
                text = f"{count} {rule['what']}{where} is more than {_num(high)}: {limit['reason']}"
                return severity, f"{_capital(text)} ({limit['source']})."
    return None


def _expand(node: Any, parts: list[str], prefix: str = "") -> list[tuple[str, Any]]:
    """The (path, value) pairs of ``node`` that the dotted pattern ``parts`` names."""
    if not parts:
        return [(prefix, node)]
    head, rest = parts[0], parts[1:]
    if isinstance(node, dict):
        keys = list(node) if head == "*" else [head] if head in node else []
        children = [(k, node[k]) for k in keys]
    elif isinstance(node, list):
        if head == "*":
            children = list(enumerate(node))
        elif head.isdigit() and int(head) < len(node):
            children = [(int(head), node[int(head)])]
        else:
            children = []
    else:
        return []
    out: list[tuple[str, Any]] = []
    for key, child in children:
        out += _expand(child, rest, f"{prefix}.{key}" if prefix else str(key))
    return out


def _applies(rule: dict[str, Any], item: dict[str, Any]) -> bool:
    for field, allowed in (rule.get("when") or {}).items():
        if item.get(field) not in allowed:
            return False
    return True


def _problem(index: int | None, path: str, found: tuple[str, str]) -> dict[str, Any]:
    severity, message = found
    return {"index": index, "path": path, "message": message, "severity": severity}


def least_dimension(item: dict[str, Any]) -> float | None:
    """The least overall dimension [mm] a member's cover sits in: a rectangle's smaller side, a
    circle's diameter, a slab's, wall's or footing's thickness; None for other sections."""
    profile = item.get("profile")
    if isinstance(profile, dict):
        shape = profile.get("shape")
        if shape == "rectangle":
            dims = [profile.get("xDim"), profile.get("yDim")]
            dims = [d for d in dims if isinstance(d, int | float) and d > 0]
            return min(dims) if len(dims) == 2 else None
        if shape == "circle" and isinstance(profile.get("radius"), int | float):
            return 2 * profile["radius"]
        return None
    thickness = item.get("thickness")
    return thickness if isinstance(thickness, int | float) and thickness > 0 else None


def cover_problem(rule: dict[str, Any], item: dict[str, Any], cover: Any) -> tuple[str, str] | None:
    """The cover on both faces at least the member's least dimension: no concrete is left
    inside the bars."""
    least = least_dimension(item)
    if least is None or not isinstance(cover, int | float) or 2 * cover < least:
        return None
    limit = rule["block"][0] if rule.get("block") else {"reason": "", "source": PRACTICE}
    detail = f"{_num(cover)} mm in a {_num(least)} mm section: {limit['reason']}"
    return "error", _sentence(rule["what"], detail, limit["source"])


def _gaps(
    values: list[tuple[int, float]], label: Any
) -> list[tuple[int, float, str]]:  # (index of the upper value, gap, between)
    ordered = sorted(values, key=lambda v: v[1])
    out = []
    for (i_low, low), (i_high, high) in pairwise(ordered):
        out.append((i_high, high - low, f"{label(i_low)} to {label(i_high)}"))
    return out


def _derived(rule: dict[str, Any], data: dict[str, Any]) -> list[dict[str, Any]]:
    kind = rule["derived"]
    out: list[dict[str, Any]] = []
    if kind == "storeyHeight":
        stories = [s for s in data.get("stories") or [] if isinstance(s, dict)]
        levels = [
            (i, float(s["elevation"]))
            for i, s in enumerate(stories)
            if isinstance(s.get("elevation"), int | float)
        ]
        names = {i: str(stories[i].get("name") or stories[i].get("id")) for i, _ in levels}
        for index, gap, between in _gaps(levels, lambda i: names[i]):
            found = judge(rule, gap, f"{rule['what']} ({between})")
            if found:
                out.append(_problem(None, f"stories.{index}.elevation", found))
    elif kind == "gridSpacing":
        grids = data.get("grids") or {}
        for axis in ("x", "y"):
            lines = [g for g in grids.get(axis) or [] if isinstance(g, dict)]
            positions = [
                (i, float(g["position"]))
                for i, g in enumerate(lines)
                if isinstance(g.get("position"), int | float)
            ]
            for index, gap, between in _gaps(positions, lambda i, ls=lines: ls[i].get("label")):
                found = judge(rule, gap, f"{rule['what']} ({between})")
                if found:
                    out.append(_problem(None, f"grids.{axis}.{index}.position", found))
    elif kind == "count":
        for path in rule["paths"]:
            for where, value in _expand(data, path.split(".")):
                if isinstance(value, list):
                    found = _count(rule, len(value))
                    if found:
                        out.append(_problem(None, where, found))
    elif kind == "spans":
        for path in rule["paths"]:
            for where, value in _expand(data, path.split(".")):
                if isinstance(value, list) and value:
                    found = _count(rule, len(value) - 1, f" ({where.split('.')[-1].upper()})")
                    if found:
                        out.append(_problem(None, where, found))
    return out


#: The list that holds the entries of a list file; other kinds are checked from the root.
LIST_KEYS = {"materials": "materials", "objects": "objects"}


def check(kind: str, data: Any, pack: Any = None) -> list[dict[str, Any]]:
    """The guardrail problems of a file of ``kind`` (its parsed JSON), each as
    ``{index, path, message, severity}``: ``index`` is the entry of a list file (None for the
    whole document), ``severity`` ``error`` (blocked) or ``warning`` (unusual)."""
    if not isinstance(data, dict):
        return []
    rules = resolved_rules(pack, kind)
    if not rules:
        return []
    list_key = LIST_KEYS.get(kind)
    entries: list[tuple[int | None, Any]] = (
        list(enumerate(data.get(list_key) or [])) if list_key else [(None, data)]
    )
    out: list[dict[str, Any]] = []
    for index, item in entries:
        if not isinstance(item, dict):
            continue
        out += item_problems(rules, item, index)
    for r in rules:
        if r.get("derived") and r["derived"] != "coverInMember" and not list_key:
            out += _derived(r, data)
    return out


def item_problems(
    rules: list[dict[str, Any]], item: dict[str, Any], index: int | None = None
) -> list[dict[str, Any]]:
    """The field problems of one entry (or document): one per field, the worst first."""
    found: dict[str, tuple[str, str]] = {}
    for r in rules:
        derived = r.get("derived")
        if derived not in (None, "coverInMember") or not _applies(r, item):
            continue
        for pattern in r["paths"]:
            for path, value in _expand(item, pattern.split(".")):
                if derived == "coverInMember":
                    result = cover_problem(r, item, value)
                else:
                    result = judge(r, value) if isinstance(value, int | float) else None
                if result and (
                    path not in found or (found[path][0] == "warning" and result[0] == "error")
                ):
                    found[path] = result
    return [_problem(index, path, result) for path, result in found.items()]


def errors(kind: str, data: Any, pack: Any = None) -> list[str]:
    """The blocked values of a file, as messages (``path: message``)."""
    return [
        f"{p['path']}: {p['message']}" if p["path"] else p["message"]
        for p in check(kind, data, pack)
        if p["severity"] == "error"
    ]


def building_problems(
    spans_x: list[float],
    spans_y: list[float],
    heights: list[float],
    pack: Any = None,
    storeys: int | None = None,
) -> list[tuple[str, str, str]]:
    """(field, severity, message) of a New Project specification: its spans, its storey
    heights and their counts, by the floor plan's rules (``gridSpacing``, ``spanCount``,
    ``storeyHeight``, ``storeyCount``)."""
    rules = {r["id"]: r for r in resolved_rules(pack, "floorPlan")}
    out: list[tuple[str, str, str]] = []
    for field, spans in (("gridsX", spans_x), ("gridsY", spans_y)):
        for span in spans:
            found = judge(rules["gridSpacing"], span, "a span")
            if found:
                out.append((field, *found))
                break
        found = _count(rules["spanCount"], len(spans), f" ({'X' if field == 'gridsX' else 'Y'})")
        if found:
            out.append((field, *found))
    for height in heights:
        found = judge(rules["storeyHeight"], height)
        if found:
            out.append(("stories", *found))
            break
    found = _count(rules["storeyCount"], len(heights) if storeys is None else storeys)
    if found:
        out.append(("stories", *found))
    return out


#: The parts the guardrails check in a project folder: (part id, file kind).
PROJECT_FILES = (
    ("materials", "materials"),
    ("objects", "objects"),
    ("floorPlan", "floorPlan"),
    ("loads", "memberLoads"),
)


def project_problems(root: Any, pack: Any = None) -> list[dict[str, Any]]:
    """The guardrail problems of the files of a project folder (an import's result), each with
    the ``file`` it is in, for an importer to report what it brought in that is impossible."""
    from pathlib import Path

    from saengine.pipeline.project import part_by_id

    out: list[dict[str, Any]] = []
    for part_id, kind in PROJECT_FILES:
        part = part_by_id(part_id)
        path = Path(root) / part.folder / (part.main_file or "")
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        except (OSError, ValueError):
            continue
        for problem in check(kind, data, pack):
            out.append({**problem, "file": f"{part.folder}/{part.main_file}"})
    return out

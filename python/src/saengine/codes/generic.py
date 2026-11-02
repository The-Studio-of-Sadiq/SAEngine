"""Generic defaults: SAEngine practice values for single values a code pack does not give.

A code pack that lacks one value (a φ, a load factor, a practice choice) still works: the value
comes from the generic defaults in ``codes/generic/data/<table>.json`` (pack-shaped data, editable,
not part of any code), and results and the report name it "generic default (SAEngine practice),
not given by <pack name>" (:func:`label`). Each file's ``$notes`` says where every value comes
from (an ACI or ASCE value used as a generic default, or SAEngine practice); a generic default
never cites the default pack's code as its source.

The defaults are filled while a pack is resolved (:mod:`saengine.codes.registry`), under the
pack's own data, with the inheritance merge of :mod:`saengine.codes.merge`:

* only tables the pack has: a whole table the pack lacks is a feature it does not cover (a
  "not covered" note, never a default);
* only values the pack lacks (or gives as null); a value the pack gives always wins, and a
  project override (:mod:`saengine.codes.overrides`) wins over both;
* a group the pack lacks is filled whole when the result is valid; otherwise only the single
  values inside groups the pack has are filled; otherwise nothing (the table's own problems are
  reported as before).
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from saengine.codes.merge import merge, parse_table_file, strip

GENERIC_DIR = Path(__file__).resolve().parent / "generic"
#: The id of the generic defaults (never a code pack id: it is not listed or chosen).
GENERIC_ID = "saengine-defaults"
#: How results name a generic default.
LABEL = "generic default (SAEngine practice)"


def label(pack_name: str | None = None) -> str:
    """How results name a generic default: "generic default (SAEngine practice), not given by
    <pack name>"."""
    return f"{LABEL}, not given by {pack_name}" if pack_name else LABEL


@dataclass(frozen=True)
class Fallback:
    """A value the pack does not give, taken from the generic defaults."""

    table: str
    #: The value's path within the table ("phi.plain").
    key: str
    value: Any
    #: Where the value comes from (the defaults' ``$notes``).
    note: str

    @property
    def path(self) -> str:
        """The full path, table first ("factors.phi.plain")."""
        return f"{self.table}.{self.key}"

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "value": self.value, "note": self.note}


@cache
def _read() -> dict[str, tuple[Any, dict[str, str]]]:
    """Table name -> (data without directives, notes by path)."""
    out: dict[str, tuple[Any, dict[str, str]]] = {}
    folder = GENERIC_DIR / "data"
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        notes = raw.pop("$notes", {}) if isinstance(raw, dict) else {}
        out[path.stem] = (strip(parse_table_file(raw).data), dict(notes))
    return out


def tables() -> list[str]:
    """The tables the generic defaults give values of."""
    return sorted(_read())


def data(name: str) -> Any:
    """The generic defaults of table ``name`` (a copy); None when there are none."""
    found = _read().get(name)
    return copy.deepcopy(found[0]) if found else None


def note(table: str, key: str) -> str:
    """Where the generic default ``key`` of ``table`` comes from: the note of the nearest path
    (the value's, else its group's); the table's own ("" key), else ''."""
    found = _read().get(table)
    notes = found[1] if found else {}
    parts = key.split(".")
    for n in range(len(parts), -1, -1):
        text = notes.get(".".join(parts[:n]))
        if text:
            return str(text)
    return ""


def _missing(defaults: Any, data: Any, whole: bool, prefix: str) -> tuple[dict, list[str]]:
    """The part of ``defaults`` the pack's ``data`` lacks, and the paths filled. ``whole``: a
    group the pack lacks is taken whole; else only values inside groups the pack has."""
    out: dict[str, Any] = {}
    filled: list[str] = []
    for key, value in defaults.items():
        path = f"{prefix}.{key}" if prefix else key
        have = data.get(key) if isinstance(data, dict) else None
        if have is not None:
            if isinstance(value, dict) and isinstance(have, dict):
                sub, more = _missing(value, have, whole, path)
                if sub:
                    out[key] = sub
                    filled += more
            continue
        if isinstance(value, dict) and not whole:
            continue
        out[key] = copy.deepcopy(value)
        filled.append(path)
    return out, filled


def attempts(name: str, data: Any) -> list[tuple[Any, list[Fallback]]]:
    """The pack's table ``data`` with the generic defaults it lacks, most filled first: (data,
    the values filled). The last attempt is ``data`` unfilled. The registry keeps the first
    that validates."""
    defaults = _read().get(name)
    if defaults is None or not isinstance(data, dict) or not isinstance(defaults[0], dict):
        return [(data, [])]
    out: list[tuple[Any, list[Fallback]]] = []
    for whole in (True, False):
        missing, paths = _missing(defaults[0], data, whole, "")
        if not paths:
            continue
        filled = merge(data, missing)
        fallbacks = [Fallback(name, p, _at(filled, p), note(name, p)) for p in paths]
        if all(o[1] != fallbacks for o in out):
            out.append((filled, fallbacks))
    out.append((data, []))
    return out


def _at(data: Any, key: str) -> Any:
    for part in key.split("."):
        data = data[part]
    return copy.deepcopy(data)

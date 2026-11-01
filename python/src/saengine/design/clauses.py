"""Clause references of the member and connection design, read from the code pack in force.

The design modules never write a code's name or clause numbers themselves: the pack's
``designClauses`` table holds them, grouped by module (``clauses.<group>.<key>``, the clause
without the code's name, e.g. "Part 6 Sec 6.4.4"). :func:`clause` puts the pack's display name
before it ("<code> Part 6 Sec 6.4.4"); :func:`short_clause` the pack's short name (``shortName``,
e.g. "<short> 6.1.4.3" in compact notes).

A pack that does not provide the table (and does not extend one that does) gives only its name:
the design still runs, its notes name the code pack without clause numbers, and never another
code's clauses. A working user copy of the built-in default pack written before the table moved
into the pack reads the built-in table.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from saengine.codes import context as code_context

#: The pack table of the clause references.
TABLE = "designClauses"


def _table() -> Any:
    pack = code_context.current()
    if pack.has(TABLE):
        return pack.table(TABLE)
    if pack.id == code_context.DEFAULT_PACK or pack.replaces_builtin:
        from saengine.codes.tables import builtin_table

        return builtin_table(TABLE, code_context.DEFAULT_PACK)
    return None


def code_name() -> str:
    """The display name of the code pack in force (its edition, else its name or id)."""
    pack = code_context.current()
    return pack.edition or pack.name or pack.id


def short_name() -> str:
    """The short name of the code in compact notes (the table's ``shortName``; the display
    name when the pack gives none)."""
    table = _table()
    short = getattr(table, "shortName", "") if table is not None else ""
    return short or code_name()


def text(group: str, key: str) -> str:
    """The clause of ``key`` in ``group`` without the code's name; "" when the pack has none."""
    table = _table()
    if table is None:
        return ""
    return (table.clauses.get(group) or {}).get(key, "")


def clause(group: str, key: str) -> str:
    """ "<code> <clause>": the pack's display name and the clause of ``key`` in ``group``."""
    return f"{code_name()} {text(group, key)}".strip()


def short_clause(group: str, key: str) -> str:
    """ "<short> <clause>": the short name and the clause of ``key`` in ``group``."""
    return f"{short_name() or code_name()} {text(group, key)}".strip()


class Clauses(Mapping[str, str]):
    """``CLAUSES[key]`` of a module: :func:`clause` of its group, read when it is used (so the
    pack in force at that time gives it)."""

    def __init__(self, group: str) -> None:
        self.group = group

    def _keys(self) -> dict[str, str]:
        table = _table()
        return dict(table.clauses.get(self.group) or {}) if table is not None else {}

    def __getitem__(self, key: str) -> str:
        return clause(self.group, key)

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        return clause(self.group, key) if key in self._keys() else default

    def __contains__(self, key: object) -> bool:
        return key in self._keys()

    def __iter__(self) -> Iterator[str]:
        return iter(self._keys())

    def __len__(self) -> int:
        return len(self._keys())

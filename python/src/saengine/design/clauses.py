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
from saengine.design.rc import DesignError

#: The pack table of the clause references.
TABLE = "designClauses"


def _table() -> Any:
    """The clause table of the pack in force; None when the pack has none."""
    try:
        return pack_table(TABLE)
    except NotCovered:
        return None


class NotCovered(DesignError):
    """The code pack in force has no table for a check (it does not cover the feature)."""


def pack_table(name: str) -> Any:
    """Table ``name`` of the pack in force; the built-in default pack's for a working copy of it
    written before the table moved into the pack. :class:`NotCovered` when another pack has no
    such table: the check is not covered by that pack (never another code's values)."""
    pack = code_context.current()
    if pack.has(name):
        return pack.table(name)
    if pack.id == code_context.DEFAULT_PACK or pack.replaces_builtin:
        from saengine.codes.tables import builtin_table

        return builtin_table(name, code_context.DEFAULT_PACK)
    raise NotCovered(f"not covered by the code pack {code_name()} (it has no '{name}' table)")


def limits() -> Any:
    """The pack's ``designLimits`` table (see :func:`pack_table`)."""
    return pack_table("designLimits")


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
    """The pack's display name and the clause of ``key`` in ``group`` ("<code> <clause>")."""
    return f"{code_name()} {text(group, key)}".strip()


def short_clause(group: str, key: str) -> str:
    """The code's short name and the clause of ``key`` in ``group`` ("<short> <clause>")."""
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

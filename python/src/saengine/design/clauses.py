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

from collections.abc import Iterable, Iterator, Mapping
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
    """The display name of the code pack in force (:func:`saengine.codes.context.code_name`)."""
    return code_context.code_name()


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
    """The clause of ``key`` in ``group`` after the name of the code it comes from ("<code>
    <clause>"): as :func:`saengine.codes.context.cite`, a group a pack inherits keeps the name
    of the pack that wrote it. Only the pack's name when it has no such clause."""
    found = text(group, key)
    if not found:
        return code_name()
    pack = code_context.current()
    owner = pack.clause_code(TABLE, group, key) if pack.has(TABLE) else None
    return f"{owner or code_name()} {found}"


def short_clause(group: str, key: str) -> str:
    """The code's short name and the clause of ``key`` in ``group`` ("<short> <clause>"); C2:
    the table's ``shortNames`` of the key or group where it gives one."""
    table = _table()
    names = getattr(table, "shortNames", None) or {}
    own = names.get(f"{group}.{key}") or names.get(group)
    return f"{own or short_name() or code_name()} {text(group, key)}".strip()


def own_text(group: str, key: str) -> str:
    """C11: :func:`text` of ``key`` in ``group`` only where the pack in force gives it itself
    (or a project override does): "" where it would be inherited from a pack it extends, so a
    pack without its own entry names the check without a clause, never another code's number.
    The built-in default pack's table read for a working copy of it counts as its own."""
    found = text(group, key)
    if not found:
        return ""
    pack = code_context.current()
    if not pack.has(TABLE):
        return found
    owner = pack.clause_owner(TABLE, group, key)
    if owner is None or owner[0] == pack.id or found != owner[1]:
        return found
    return ""


def _paren(label: str, inner: str) -> str:
    """``label (inner)``, or ``label`` alone when ``inner`` is empty."""
    return f"{label} ({inner})" if inner else label


class Rows:
    """C11: the clause numbers the check rows and notes of a module cite, from the pack's
    ``designClauses.<group>`` (the clause without the code's name, e.g. "8.3.4.1(d)" in the
    default pack), as :func:`own_text` gives them: a pack without an entry for a key names the
    row without a clause."""

    def __init__(self, group: str) -> None:
        self.group = group

    def ref(self, *keys: str, extra: Iterable[str] = ()) -> str:
        """The pack's clauses of ``keys`` (and ``extra`` words), comma separated; "" when it
        has none of them."""
        found = [own_text(self.group, k) for k in keys]
        return ", ".join(t for t in [*found, *extra] if t)

    def named(self, label: str, *keys: str, extra: Iterable[str] = ()) -> str:
        """``label`` with :meth:`ref` of ``keys`` in parentheses; ``label`` alone without."""
        return _paren(label, self.ref(*keys, extra=extra))

    def sec(self, *keys: str) -> str:
        """ "Sec <clauses>" of ``keys``; "" when the pack has none of them."""
        found = self.ref(*keys)
        return f"Sec {found}" if found else ""

    def within(self, *keys: str) -> str:
        """ " (<clauses>)" of ``keys`` to follow a phrase; "" when the pack has none of them."""
        found = self.ref(*keys)
        return f" ({found})" if found else ""


def from_default(pack: Any, owner_id: str | None) -> bool:
    """True when ``pack`` (the pack in force) inherits a clause from the default pack (its
    writer ``owner_id``): the default pack is the fallback of every pack, not a code the pack
    adopts, so the pack's method text leaves such a clause out."""
    if owner_id is None or pack.id == code_context.DEFAULT_PACK or pack.replaces_builtin:
        return False
    return owner_id == code_context.DEFAULT_PACK


def adopted(group: str, key: str) -> str:
    """:func:`clause` of ``key`` in ``group`` (after the name of the code that wrote it) for a
    method text; "" when the pack in force has none or inherits it from the default pack
    (:func:`from_default`; a project override of it is kept)."""
    found = text(group, key)
    if not found:
        return ""
    pack = code_context.current()
    owner = pack.clause_owner(TABLE, group, key) if pack.has(TABLE) else None
    if owner is not None and owner[1] == found and from_default(pack, owner[0]):
        return ""
    return clause(group, key)


def own_short_name() -> str:
    """:func:`short_name`, or the display name of the pack in force when its short name is the
    default pack's (inherited): a text naming the pack in force never takes the default pack's
    short name."""
    pack = code_context.current()
    found = short_name()
    if not from_default(pack, code_context.DEFAULT_PACK):
        return found
    from saengine.codes.tables import builtin_table

    default = getattr(builtin_table(TABLE, code_context.DEFAULT_PACK), "shortName", "")
    return code_name() if found == default else found


class Own(Mapping[str, str]):
    """``OWN[key]`` of a group for a method text template (``"{p[key]}"``): :func:`own_text` of
    the key set in ``form`` ("{}" is the clause), or ``empty`` when the pack in force does not
    give the key itself, so a template never shows another code's clause number. ``named``:
    :func:`adopted` instead (the clause after its code's name, kept when inherited from a code
    the pack extends, left out when inherited from the default pack)."""

    def __init__(self, group: str, form: str = "{}", empty: str = "", named: bool = False) -> None:
        self.group = group
        self.form = form
        self.empty = empty
        self.named = named

    def __getitem__(self, key: str) -> str:
        found = adopted(self.group, key) if self.named else own_text(self.group, key)
        return self.form.format(found) if found else self.empty

    def __iter__(self) -> Iterator[str]:
        table = _table()
        return iter(dict(table.clauses.get(self.group) or {}) if table is not None else {})

    def __len__(self) -> int:
        return sum(1 for _ in self)


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

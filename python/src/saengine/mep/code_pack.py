"""The code pack in force, as the services modules (mep, plumbing, hvac, fire, electrical) see it.

The services read their values from the pack's ``plumbing``, ``hvac``, ``fire`` and
``electrical`` tables (each module's ``tables`` names) and cite the clauses those tables give
(their ``pages`` and ``sources``). A pack without one of the tables does not cover that service:
:func:`covers` is False and the report says so (:func:`not_covered`). A user copy of the default
pack written before the table existed reads the built-in one.
"""

from __future__ import annotations

from typing import Any

from saengine.codes import context as code_context


def table(name: str) -> Any | None:
    """Table ``name`` of the pack in force, or None when the pack does not cover it."""
    pack = code_context.current()
    if pack.has(name):
        return pack.table(name)
    from saengine.codes.registry import DEFAULT_PACK
    from saengine.codes.tables import builtin_table

    if pack.id == DEFAULT_PACK:
        return builtin_table(name, DEFAULT_PACK)
    return None


def covers(name: str) -> bool:
    """Whether the pack in force has table ``name``."""
    return table(name) is not None


def code_name() -> str:
    """The display name of the pack in force (the default pack's "BNBC 2020")."""
    pack = code_context.current()
    return pack.name or pack.id


def not_covered(what: str) -> str:
    """The note of a feature the pack in force has no data for."""
    return f"{what}: not covered by the code pack {code_name()}"


def page(name: str, key: str, default: str = "") -> str:
    """The citation ``key`` of table ``name``'s ``pages`` (``default`` when it has none)."""
    found = table(name)
    pages = getattr(found, "pages", None) or {}
    return pages.get(key, default)


def source(name: str, key: str, default: str = "") -> str:
    """The clause ``key`` of table ``name``'s ``sources`` (``default`` when it has none)."""
    found = table(name)
    sources = getattr(found, "sources", None) or {}
    return sources.get(key, default)


def clause(text: str) -> str:
    """The citation part of a ``sources`` entry: the text before its first ": " (the rest
    explains the value)."""
    return text.split(": ", 1)[0].strip()

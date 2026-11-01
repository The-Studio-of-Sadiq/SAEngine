"""The code pack's site investigation and soil chemistry data, for the soil modules.

The checks of :mod:`saengine.soil.investigation`, :mod:`saengine.soil.chemistry` and
:mod:`saengine.soil.special_soils` read their bands and limits from the ``siteInvestigation``
table of the pack in force (:mod:`saengine.codes.context`). A pack without the table does not
cover them: :func:`table` returns None and the results say the pack does not cover the check.
A user copy of the default pack written before the table existed reads the built-in one.
"""

from __future__ import annotations

from typing import Any

from saengine.codes import context as code_context

#: The pack table the soil checks read.
TABLE = "siteInvestigation"


def table() -> Any | None:
    """The pack's ``siteInvestigation`` table, or None when the pack does not cover it."""
    pack = code_context.current()
    if pack.has(TABLE):
        return pack.table(TABLE)
    from saengine.codes.registry import DEFAULT_PACK
    from saengine.codes.tables import builtin_table

    if pack.id == DEFAULT_PACK:
        return builtin_table(TABLE, DEFAULT_PACK)
    return None


def code_name() -> str:
    """The display name of the pack in force (e.g. "BNBC 2020")."""
    pack = code_context.current()
    return pack.name or pack.id


def not_covered(what: str) -> str:
    """The note of a check the pack in force has no data for."""
    return f"{what}: not covered by the code pack {code_name()}"


def band(rows: list[Any], value: float) -> Any | None:
    """The first band of ``rows`` that ``value`` falls in (see ``codes.tables._Band``)."""
    return next((row for row in rows if row.holds(value)), None)

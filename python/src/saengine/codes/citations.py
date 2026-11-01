"""The clause references the documents print: the calculation report, its worksheets, the
drawings and the bill of quantities.

A document names the rules it applies ("Soil springs (BNBC 2020 Part 6 Sec 1.2.7.3)" with the
default pack). Those references are not the engine's own: they come from the ``clauses`` of the
pack's ``citations`` table, after the name of the code that gives them
(:func:`saengine.codes.context.cite`). A pack without a reference for a key prints none.
"""

from __future__ import annotations

from saengine.codes import context as code_context

#: The pack table that holds the documents' clause references.
TABLE = "citations"


def ref(key: str) -> str:
    """The reference ``key`` with the code's name (e.g. "BNBC 2020 Part 6 Sec 2.4.8"); '' when
    the pack in force gives none."""
    return code_context.cite(TABLE, key)


def paren(key: str, before: str = " ") -> str:
    """``before`` + "(reference)", or '' when the pack in force gives none."""
    text = ref(key)
    return f"{before}({text})" if text else ""


def after(key: str, sep: str = ", ") -> str:
    """``sep`` + reference, or '' when the pack in force gives none."""
    return code_context.cited(TABLE, key, sep=sep)


def code_name() -> str:
    """The name of the code in force (e.g. "BNBC 2020")."""
    return code_context.code_name()

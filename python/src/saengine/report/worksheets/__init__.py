"""Calculation worksheets (Part 11 Report): hand calculations made with SAEngine's own design
functions and printed in the design report.

A project keeps its worksheets in ``11 Exports/worksheets/<id>.json``
(:mod:`saengine.library.worksheet`): a kind and the values entered. :func:`calculate` makes the
calculation of a kind for some inputs (the worksheet editor calls it on every change);
:func:`project_worksheets` makes those of a project marked to print, as the blocks of the
report's "Calculation worksheets" section (:mod:`saengine.report.document`).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# The kinds register themselves on import.
from saengine.report.worksheets import concrete as _concrete  # noqa: F401
from saengine.report.worksheets import ground_loads as _ground_loads  # noqa: F401
from saengine.report.worksheets.core import KINDS, calculate, displayed, kinds

__all__ = [
    "KINDS",
    "calculate",
    "create_worksheet",
    "displayed",
    "kinds",
    "list_worksheets",
    "project_pack",
    "project_worksheets",
    "worksheet_blocks",
]


@contextmanager
def project_pack(project_root: str | Path | None) -> Iterator[list[str]]:
    """Within the block the code pack the project's settings choose is in force (the built-in
    default pack without a project, or when it cannot be used: the list it yields then says
    so)."""
    from saengine.report.clauses import in_force

    if not project_root:
        yield []
        return
    with in_force(Path(project_root)) as problems:
        yield problems


def worksheet_blocks(
    result: dict[str, Any], reference: str = "", notes: str = "", units: Any = None
) -> list[dict]:
    """The report blocks of a calculation (:func:`calculate`): the inputs, the steps (full
    detail only), the checks and the notes. In US customary ``units`` (C13b) the blocks are
    in the display units already (marked ``shown``, so the report leaves them) and the steps
    have a "With values" column: each expression with its values."""
    from saengine.report.document import bullets, full, label, method, note, pairs, table

    if units is not None and not units.si:
        return _shown_blocks(result, reference, notes, units)

    out: list[dict[str, Any]] = []
    if reference:
        out.append(method(reference))
    if result.get("problems"):
        out.append(note("; ".join(result["problems"]), "Not calculated:"))
        return out
    out.append(label("Inputs"))
    out.append(pairs([[i["label"], f"{i['value']} {i['unit']}".strip()] for i in result["inputs"]]))
    rows: list[list[str]] = []
    for step in result["steps"]:
        if "heading" in step:
            rows.append([step["heading"], "", "", "", ""])
            continue
        rows.append([step["label"], step["formula"], step["value"], step["unit"], step["clause"]])
    if rows:
        out += full(
            label("Calculation"),
            table(
                ["Quantity", "Expression", "Value", "Unit", "Reference"],
                rows,
                ["auto", "1fr", "auto", "auto", "30%"],
                "llrll",
                size=8,
            ),
        )
    if result["checks"]:
        out.append(label("Checks", None if result.get("ok", True) else "fail"))
        out.append(
            table(
                ["Check", "Value", "", "Limit", "Unit", "Util.", "Result", "Reference"],
                [
                    [
                        c["label"],
                        c["demand"],
                        c["sense"],
                        c["capacity"],
                        c["unit"],
                        "-" if c["utilisation"] is None else f"{c['utilisation']:.2f}",
                        "OK" if c["ok"] else "FAILS",
                        c["clause"],
                    ]
                    for c in result["checks"]
                ],
                ["1fr", "auto", "auto", "auto", "auto", "auto", "auto", "25%"],
                "lrcrlrcl",
                bad=[not c["ok"] for c in result["checks"]],
                size=8,
            )
        )
    texts = list(result.get("notes", [])) + ([notes] if notes else [])
    if texts:
        out.append(bullets(texts, 8))
    return out


#: What the report says of the expressions given in the code's SI form (C13b).
SI_FORM_NOTE = (
    "Expressions marked (SI form) are the code's SI form, valid in N, mm and MPa only: they "
    "are given with the SI values; the results are converted."
)


def _shown_blocks(
    result: dict[str, Any], reference: str, notes: str, units: Any
) -> list[dict[str, Any]]:
    """:func:`worksheet_blocks` in US customary ``units``: the SI blocks converted, with the
    expressions with their values in a column of their own."""
    from saengine.report.document import bullets
    from saengine.units import convert_block

    steps = list(result.get("steps", []))
    si_form = any(s.get("siForm") for s in steps if "heading" not in s)
    out: list[dict[str, Any]] = []
    for block in worksheet_blocks(result, reference, "", None):
        shown = convert_block(block, units)
        head = list(shown.get("head") or [])
        if shown.get("t") == "table" and head[:2] == ["Quantity", "Expression"]:
            rows = []
            for row, step in zip(shown["rows"], steps, strict=False):
                if "heading" in step:
                    rows.append([row[0], "", "", "", "", ""])
                    continue
                expression = str(step.get("expression") or "")
                if expression and step.get("siForm"):
                    expression += " (SI form)"
                rows.append([row[0], row[1], expression, *row[2:]])
            shown["head"] = [head[0], head[1], "With values", *head[2:]]
            shown["rows"] = rows
            shown["widths"] = ["auto", "1fr", "1fr", "auto", "auto", "22%"]
            shown["align"] = "lllrll"
        shown["shown"] = True
        out.append(shown)
    texts = ([SI_FORM_NOTE] if si_form else []) + ([notes] if notes else [])
    if texts:
        out.append({**bullets(texts, 8), "shown": True})
    return out


def project_worksheets(project_root: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    """The worksheets of a project marked to print, calculated now: ``[{title, blocks}]`` for
    the report's ``worksheets`` section, and the warnings (files that could not be read,
    unknown kinds, failing checks)."""
    from saengine.library.worksheet import WORKSHEETS_FOLDER, load_worksheets
    from saengine.units import units_at

    found, warnings = load_worksheets(project_root)
    units = units_at(project_root)
    sheets: list[dict[str, Any]] = []
    for path, sheet in found:
        if not sheet.print_:
            continue
        with project_pack(project_root):
            result = calculate(sheet.kind, sheet.inputs, units)
        where = f"{WORKSHEETS_FOLDER}/{path.name}"
        if result.get("problems"):
            warnings.append(f"Worksheet {where}: " + "; ".join(result["problems"]))
        elif not result.get("ok", True):
            failing = [c["label"] for c in result["checks"] if not c["ok"]]
            warnings.append(f"Worksheet '{sheet.title}' fails: {', '.join(failing)}.")
        kind = KINDS.get(sheet.kind)
        heading = (
            sheet.title
            if not kind or sheet.title == kind.title
            else (f"{sheet.title} ({kind.title})")
        )
        sheets.append(
            {
                "title": heading,
                "blocks": worksheet_blocks(result, sheet.reference, sheet.notes, units),
            }
        )
    return sheets, warnings


def list_worksheets(project_root: str | Path) -> dict[str, Any]:
    """The project's worksheets with their result: ``{worksheets: [{id, title, kind, print,
    path, ok, utilisation, problems}], problems}``."""
    from saengine.library.worksheet import load_worksheets

    found, problems = load_worksheets(project_root)
    rows = []
    for path, sheet in found:
        with project_pack(project_root):
            result = calculate(sheet.kind, sheet.inputs)
        rows.append(
            {
                "id": sheet.id,
                "title": sheet.title,
                "kind": sheet.kind,
                "print": sheet.print_,
                "path": str(path),
                "ok": result.get("ok") if not result.get("problems") else None,
                "utilisation": result.get("utilisation"),
                "problems": result.get("problems", []),
            }
        )
    return {"worksheets": rows, "problems": problems}


def create_worksheet(
    project_root: str | Path, kind: str, worksheet_id: str, title: str | None = None
) -> dict[str, Any]:
    """Writes a new worksheet of ``kind`` with the kind's defaults: ``{path}`` or
    ``{problems}`` (an unknown kind, a bad id, or a file already there: ``existing``)."""
    import re

    from pydantic import ValidationError

    from saengine.library.worksheet import (
        WORKSHEET_ID_PATTERN,
        Worksheet,
        save_worksheet,
        worksheet_path,
    )

    spec = KINDS.get(kind)
    if spec is None:
        return {"problems": [f"Unknown worksheet kind {kind!r}."]}
    if not re.match(WORKSHEET_ID_PATTERN, worksheet_id or ""):
        return {"problems": [f"'{worksheet_id}' is not a worksheet id (a-z, 0-9 and -)."]}
    path = worksheet_path(project_root, worksheet_id)
    if path.exists():
        return {"path": str(path), "existing": True}
    try:
        sheet = Worksheet(
            id=worksheet_id, kind=kind, title=title or spec.title, inputs=spec.defaults()
        )
        written = save_worksheet(project_root, sheet)
    except (ValidationError, OSError) as error:
        return {"problems": [str(error).splitlines()[0]]}
    return {"path": str(written)}

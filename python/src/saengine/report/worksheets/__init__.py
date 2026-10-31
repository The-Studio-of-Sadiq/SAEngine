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
from saengine.report.worksheets.core import KINDS, calculate, kinds

__all__ = [
    "KINDS",
    "calculate",
    "create_worksheet",
    "kinds",
    "list_worksheets",
    "project_pack",
    "project_worksheets",
    "worksheet_blocks",
]


@contextmanager
def project_pack(project_root: str | Path | None) -> Iterator[list[str]]:
    """Within the block the code pack the project's settings choose is in force (the built-in
    BNBC 2020 without a project, or when it cannot be used: the list it yields then says so)."""
    from saengine.codes import context as code_context

    problems: list[str] = []
    if not project_root:
        yield problems
        return
    root = Path(project_root)
    with code_context.project(root):
        try:
            from saengine.report.build import _Parts

            pack = code_context.pack_for(_Parts(root, []).settings(), root)
        except Exception as error:  # noqa: BLE001 - a missing pack falls back to BNBC 2020
            problems.append(f"the project's code pack could not be used ({error}); BNBC 2020")
            pack = None
        with code_context.using(pack):
            yield problems


def worksheet_blocks(result: dict[str, Any], reference: str = "", notes: str = "") -> list[dict]:
    """The report blocks of a calculation (:func:`calculate`): the inputs, the steps (full
    detail only), the checks and the notes."""
    from saengine.report.document import bullets, full, label, method, note, pairs, table

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


def project_worksheets(project_root: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    """The worksheets of a project marked to print, calculated now: ``[{title, blocks}]`` for
    the report's ``worksheets`` section, and the warnings (files that could not be read,
    unknown kinds, failing checks)."""
    from saengine.library.worksheet import WORKSHEETS_FOLDER, load_worksheets

    found, warnings = load_worksheets(project_root)
    sheets: list[dict[str, Any]] = []
    for path, sheet in found:
        if not sheet.print_:
            continue
        with project_pack(project_root):
            result = calculate(sheet.kind, sheet.inputs)
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
                "blocks": worksheet_blocks(result, sheet.reference, sheet.notes),
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

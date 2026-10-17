"""The design report of the substructure (Part 9): every foundation and tie beam of
``09 Substructure/substructure.json`` checked under the support reactions of the analysis.

Footings (isolated, combined, strip) and tie beams are designed by
:mod:`saengine.substructure.shallow`; pile caps by :mod:`saengine.substructure.pilecap` and rafts
by :mod:`saengine.substructure.raft` when those modules are there (each foundation type that
has no design yet is listed as skipped, with the reason).
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from saengine.library.bim import ColumnElement
from saengine.library.substructure import FOUNDATION_TYPES, check
from saengine.substructure.context import Context, Skip, load_context
from saengine.substructure.shallow import SHALLOW_METHOD, design_shallow, design_tie_beam

#: Foundation type -> (modules to look in, the design function's name, method list names). The
#: function takes ``(ctx: Context, foundation: Foundation)`` and returns the foundation's result
#: in the report's format, or ``(result, notes)``; it raises :class:`Skip` when it cannot design.
EXTERNAL = {
    "pileCap": (("pilecap", "piles"), "design_pile_cap", ("PILE_CAP_METHOD", "METHOD")),
    "raft": (("raft",), "design_raft", ("RAFT_METHOD", "METHOD")),
}


def substructure_report(project_root: str | Path, out_dir: str | Path | None = None) -> dict:
    """The design checks of the substructure of the project at ``project_root`` under the
    analysis results in ``out_dir`` (default ``08 FEM/model.results``), ready for JSON.

    Returns ``{"foundations", "tieBeams", "skipped", "summary", "notes", "method",
    "combinations"}``: per designed foundation ``{"id", "type", "columns", "checks",
    "utilisation", "ok", "sizes", "pressure"}`` (pile caps and rafts add their ``piles`` and
    ``raft``), per tie beam ``{"id", "type": "tieBeam", "columns": [from, to], "checks",
    "utilisation", "ok", "force"}``, per skipped foundation or tie beam ``{"id", "type",
    "reason"}``; each check ``{"name", "demand", "capacity", "unit", "utilisation",
    "combination", "ok", "note", "flag"}`` as :func:`saengine.design.design_report`'s
    (``flag`` checks are reported but do not make the foundation fail). Raises ``ValueError``
    when a part of the project cannot be read or is invalid."""
    return report(load_context(project_root, out_dir))


def _external(foundation_type: str) -> tuple[Callable[..., Any] | None, list[str], str]:
    """The design function of a foundation type in another module, its method lines, and why
    it is missing."""
    module_names, name, methods = EXTERNAL[foundation_type]
    for module_name in module_names:
        try:
            module = importlib.import_module(f"saengine.substructure.{module_name}")
        except ImportError:
            continue
        function = getattr(module, name, None)
        if callable(function):
            lines = next((list(getattr(module, m)) for m in methods if hasattr(module, m)), [])
            return function, lines, ""
    return None, [], f"{FOUNDATION_TYPES[foundation_type].lower()}s are not designed yet"


def _inside(point: Any, outline: list[list[float]]) -> bool:
    """Whether a plan point lies inside (or on) a polygon."""
    x, y = float(point[0]), float(point[1])
    inside = False
    count = len(outline)
    for k in range(count):
        (x0, y0), (x1, y1) = outline[k], outline[(k + 1) % count]
        if (y0 > y) != (y1 > y):
            at = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < at:
                inside = not inside
    return inside


def report(ctx: Context) -> dict[str, Any]:
    """:func:`substructure_report` of a loaded :class:`~saengine.substructure.context.Context`."""
    substructure = ctx.substructure
    notes: list[str] = [
        f"9 Substructure: {p}"
        for p in check(substructure, ctx.building, ctx.materials, ctx.objects)
    ]
    foundations: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    method: list[str] = []
    used: set[str] = set()

    def skip(item: Any, kind: str, reason: str) -> None:
        skipped.append({"id": item.id, "type": kind, "reason": reason})

    for foundation in substructure.foundations:
        try:
            if foundation.type in ("isolated", "combined", "strip"):
                result, found = design_shallow(ctx, foundation)
                used.add("shallow")
            else:
                function, lines, reason = _external(foundation.type)
                if function is None:
                    raise Skip(reason)
                try:
                    value = function(ctx, foundation)
                except Skip:
                    raise
                except Exception as error:  # another module's failure must not sink the report
                    raise Skip(f"its design failed: {error}") from error
                result, found = value if isinstance(value, tuple) else (value, [])
                if lines and lines[0] not in method:
                    method += lines
        except Skip as reason:
            skip(foundation, foundation.type, str(reason))
            continue
        foundations.append(result)
        notes += found
    ties: list[dict[str, Any]] = []
    for tie in substructure.tieBeams:
        try:
            result, found = design_tie_beam(ctx, tie)
        except Skip as reason:
            skip(tie, "tieBeam", str(reason))
            continue
        ties.append(result)
        notes += found
        used.add("shallow")

    # Columns standing on no foundation.
    if ctx.loads is not None and substructure.foundations:
        carried = {c for f in substructure.foundations for c in f.columns}
        rafts = [f.outline for f in substructure.foundations if f.type == "raft" and f.outline]
        for base_id, base in ctx.loads.bases.items():
            if base_id in carried or not isinstance(base.element, ColumnElement):
                continue
            if any(_inside(base.element.position, outline) for outline in rafts):
                continue
            notes.append(f"{base_id}: no foundation under it")
    elif ctx.loads is None and substructure.foundations:
        notes.append(f"Not designed: {ctx.no_loads}.")
    if ctx.soil.used or ctx.soil.problems:
        notes += ctx.soil.notes()
    if "shallow" in used:
        method = list(SHALLOW_METHOD) + method

    designed = foundations + ties
    failed = [e for e in designed if not e["ok"]]
    governing = max(designed, key=lambda e: e["utilisation"], default=None)
    loads = ctx.loads
    return {
        "foundations": foundations,
        "tieBeams": ties,
        "skipped": skipped,
        "summary": {
            "checked": len(designed),
            "passed": len(designed) - len(failed),
            "failed": len(failed),
            "skipped": len(skipped),
            "maxUtilisation": governing["utilisation"] if governing else None,
            "governing": governing["id"] if governing else None,
            "analysed": loads is not None,
        },
        "notes": notes,
        "method": method,
        "combinations": {
            "service": [name for name, _ in loads.service] if loads else [],
            "strength": [name for name, _ in loads.strength] if loads else [],
        },
    }

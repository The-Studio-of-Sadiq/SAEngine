"""The design report of the substructure (Part 9): every foundation and tie beam of
``09 Substructure/substructure.json`` checked under the support reactions of the analysis.

Footings (isolated, combined, strip) and tie beams are designed by
:mod:`saengine.substructure.shallow`; pile caps by :mod:`saengine.substructure.pilecap` and rafts
by :mod:`saengine.substructure.raft` when those modules are there (each foundation type that
has no design yet is listed as skipped, with the reason).
"""

from __future__ import annotations

import importlib
import math
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design.check import _check
from saengine.library.bim import ColumnElement, WallElement
from saengine.library.substructure import FOUNDATION_TYPES, check, pile_layout_warnings
from saengine.substructure.context import Context, Skip, load_context
from saengine.substructure.ground_slab import GROUND_SLAB_METHOD, design_ground_slab
from saengine.substructure.jobs import Superseded, newest
from saengine.substructure.retaining_walls import METHOD as RETAINING_WALL_METHOD
from saengine.substructure.retaining_walls import design_retaining_walls
from saengine.substructure.shallow import SHALLOW_METHOD, design_shallow, design_tie_beam
from saengine.substructure.sizing import penetration

#: Foundation type -> (modules to look in, the design function's name, method list names). The
#: function takes ``(ctx: Context, foundation: Foundation)`` and returns the foundation's result
#: in the report's format, or ``(result, notes)``; it raises :class:`Skip` when it cannot design.
EXTERNAL = {
    "pileCap": (("pilecap", "piles"), "design_pile_cap", ("PILE_CAP_METHOD", "METHOD")),
    "raft": (("raft",), "design_raft", ("RAFT_METHOD", "METHOD")),
}


def substructure_report(
    project_root: str | Path, out_dir: str | Path | None = None, supersede: bool = True
) -> dict:
    """The design checks of the substructure of the project at ``project_root`` under the
    analysis results in ``out_dir`` (default ``08 FEM/model.results``), ready for JSON.

    Returns ``{"foundations", "tieBeams", "retainingWalls", "skipped", "summary", "notes",
    "method", "combinations"}``: per designed foundation ``{"id", "type", "columns", "checks",
    "utilisation", "ok", "sizes", "pressure"}`` (pile caps and rafts add their ``piles`` and
    ``raft``), per tie beam ``{"id", "type": "tieBeam", "columns": [from, to], "checks",
    "utilisation", "ok", "force"}``, per skipped foundation or tie beam ``{"id", "type",
    "reason"}``; each check ``{"name", "demand", "capacity", "unit", "utilisation",
    "combination", "ok", "note", "flag"}`` as :func:`saengine.design.design_report`'s
    (``flag`` checks are reported but do not make the foundation fail). Raises ``ValueError``
    when a part of the project cannot be read or is invalid. Runs under the project's code
    pack.

    With ``supersede`` (the editor's checks) it is the newest check of the project: a check of
    it still running stops, and this one stops with
    :class:`~saengine.substructure.jobs.Superseded` (a ``ValueError``) when another is asked
    for (:mod:`saengine.substructure.jobs`). Run All's step passes False."""
    with newest(project_root) if supersede else nullcontext():
        ctx = load_context(project_root, out_dir)
        with (
            code_context.project(ctx.root or project_root),
            code_context.using(code_context.pack_for(ctx.settings, ctx.root)),
        ):
            return report(ctx)


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
                except (Skip, Superseded):
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
    mark_overlaps(foundations)
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

    slabs: list[dict[str, Any]] = []
    for slab in substructure.groundSlabs:
        try:
            result, found = design_ground_slab(ctx, slab)
        except Skip as reason:
            skip(slab, "groundSlab", str(reason))
            continue
        slabs.append(result)
        notes += found
    if slabs:
        method += GROUND_SLAB_METHOD
    # Retaining and basement walls, and the flotation of the basement (no analysis needed).
    walls, walls_skipped, found = design_retaining_walls(ctx)
    skipped += walls_skipped
    notes += found
    if walls or walls_skipped:
        method += [m for m in RETAINING_WALL_METHOD if m not in method]

    # The piles placed in plan: under no cap, outside their cap, too close together.
    layout = pile_layout_warnings(substructure)
    notes += [f"Pile layout: {w}" for w in layout]

    # Columns and walls standing on no foundation.
    unsupported = unsupported_bases(ctx) if substructure.foundations else []
    for base_id, kind in unsupported:
        notes.append(f"{kind} {base_id}: no foundation under it")
    if ctx.loads is None and substructure.foundations:
        notes.append(f"Not designed: {ctx.no_loads}.")
    if ctx.soil.used or ctx.soil.problems:
        notes += ctx.soil.notes()
    # The soil chemistry's demands on the foundation concrete (the Soil Report computes them).
    if substructure.foundations:
        from saengine.soil.chemistry import foundation_concrete, requirement_text

        concrete = foundation_concrete(ctx.soil_text)
        if concrete is not None:
            notes.append(requirement_text(concrete))
    if "shallow" in used:
        method = list(SHALLOW_METHOD) + method

    designed = foundations + ties + slabs + walls
    return {
        "foundations": foundations,
        "tieBeams": ties,
        "groundSlabs": slabs,
        "retainingWalls": walls,
        "skipped": skipped,
        "summary": check_summary(designed, skipped, [b for b, _ in unsupported], ctx.loads),
        "notes": notes,
        "method": method,
        "pileLayout": {
            "piles": len(substructure.piles),
            "capped": len(substructure.capped()),
            "warnings": layout,
        },
        "combinations": {
            "service": [name for name, _ in ctx.loads.service] if ctx.loads else [],
            "strength": [name for name, _ in ctx.loads.strength] if ctx.loads else [],
        },
    }


def _corners(result: dict[str, Any]) -> np.ndarray | None:
    """The plan corners [mm] of a footing's result (isolated, combined, strip), else None."""
    sizes = result.get("sizes")
    if result["type"] not in ("isolated", "combined", "strip") or not sizes:
        return None
    theta = math.radians(sizes.get("rotation") or 0.0)
    u = np.array([math.cos(theta), math.sin(theta)])
    v = np.array([-math.sin(theta), math.cos(theta)])
    center = np.array(sizes["center"], dtype=float)
    half_u, half_v = sizes["length"] / 2 * u, sizes["width"] / 2 * v
    return np.array(
        [center + su * half_u + sv * half_v for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    )


def mark_overlaps(foundations: list[dict[str, Any]]) -> None:
    """Footings that overlap in plan fail: each is checked alone, but under the overlap their
    pressures add up (and they cannot both be cast there). A check row on each, utilisation
    1 + the overlap over the footing's smaller side."""
    shapes = [(r, c) for r in foundations if (c := _corners(r)) is not None]
    for k, (a, ca) in enumerate(shapes):
        for b, cb in shapes[k + 1 :]:
            depth = penetration(ca, cb)
            if depth <= 0.5:  # mm: touching footings are fine
                continue
            for this, other in ((a, b), (b, a)):
                side = min(this["sizes"]["length"], this["sizes"]["width"])
                row = _check(
                    "Clear of the other footings",
                    depth,
                    0.0,
                    "mm",
                    None,
                    f"overlaps {other['id']} by {depth:.0f} mm in plan: their soil pressures add "
                    "up there. Make them one combined footing (select both and Size Footings) "
                    "or a raft",
                    utilisation=1.0 + depth / side,
                )
                this["checks"].append(row)
                this["ok"] = False
                this["utilisation"] = max(this["utilisation"], row["utilisation"])


def unsupported_bases(ctx: Context) -> list[tuple[str, str]]:
    """The columns and walls on the base level of the building that no foundation carries (a
    raft without its own list carries those inside its outline), as ``(id, "Column" | "Wall")``.
    The base level is that of the analysis model's supports when there are results, else the
    lowest column base of 6 BIM."""
    substructure = ctx.substructure
    carried = {c for f in substructure.foundations for c in f.columns}
    rafts = [
        f.outline
        for f in substructure.foundations
        if f.type == "raft" and f.outline and not f.columns
    ]
    if ctx.loads is not None:
        elements = [base.element for base in ctx.loads.bases.values()]
    else:
        columns = [e for e in ctx.building.elements if isinstance(e, ColumnElement)]
        lowest = min((c.bottom for c in columns), default=None)
        elements = [
            e
            for e in ctx.building.elements
            if isinstance(e, ColumnElement | WallElement)
            and lowest is not None
            and e.bottom <= lowest + 1
        ]
    found: list[tuple[str, str]] = []
    for element in elements:
        if element.id in carried:
            continue
        if isinstance(element, ColumnElement):
            point = element.position
            kind = "Column"
        else:
            point = [(a + b) / 2 for a, b in zip(element.start, element.end, strict=False)]
            kind = "Wall"
        if any(_inside(point, outline) for outline in rafts):
            continue
        found.append((element.id, kind))
    return found


def check_summary(
    designed: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    unsupported: list[str],
    loads: Any,
) -> dict[str, Any]:
    """The report's ``summary``: how many of the foundations and tie beams were checked
    (``checked`` of ``total``), passed and failed, and ``status``: ``"pass"`` only when every
    one was checked in full, all pass and every column and wall stands on a foundation;
    ``"fail"`` when a check fails; ``"incomplete"`` otherwise (some not checked, some without
    their bearing check, or columns or walls without a foundation); ``"none"`` when nothing was
    checked. The part list reads ``status``.

    A foundation whose bearing could not be checked (no qa: its result's ``notChecked``) is
    neither checked nor passed: ``checked`` counts the foundations checked in full, and their
    ids are in ``bearingUnchecked`` (Run All stops on them, or states its assumption)."""
    failed = [e for e in designed if not e["ok"]]
    partly = [e for e in designed if e.get("notChecked")]
    governing = max(designed, key=lambda e: e["utilisation"], default=None)
    total = len(designed) + len(skipped)
    complete = bool(designed) and not skipped and not unsupported and not partly
    status = "fail" if failed else "pass" if complete else "incomplete" if designed else "none"
    return {
        "checked": len(designed) - len(partly),
        "total": total,
        "passed": len([e for e in designed if e["ok"] and not e.get("notChecked")]),
        "failed": len(failed),
        "skipped": len(skipped),
        "bearingUnchecked": [e["id"] for e in partly if "bearing" in e["notChecked"]],
        "unsupported": unsupported,
        "complete": complete,
        "status": status,
        "maxUtilisation": governing["utilisation"] if governing else None,
        "governing": governing["id"] if governing else None,
        "analysed": loads is not None,
    }

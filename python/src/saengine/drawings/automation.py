"""Drawing automation, rule-based (gap AI-3): auto-dimension, auto-tag and auto-arrange a sheet.

The drawing set (:mod:`saengine.drawings.sheets`) is generated with its dimensions, marks and
packed views already. These commands work on a sheet DXF of ``11 Exports/Drawings`` as it is now,
including after the engineer edited it in the CAD program, and add what is missing:

- :func:`auto_dimension`: chain dimensions between the grid lines (layer ``S-GRID``) and the overall
  dimension, below and to the left of the grids, where the sheet has no dimension along that line
  of grids yet;
- :func:`auto_tag`: a mark (layer ``S-TEXT``) at every member that carries its mark in SAEngine's
  XDATA (``mark`` / ``id``, :func:`saengine.drawings.sheets.layout.tag`) and has no text with that
  mark near it;
- :func:`auto_arrange`: texts of the annotation layers that overlap another text moved to the
  nearest free place around them (eight directions, growing steps), so labels no longer collide.

Each addition or move is tagged in XDATA (``auto=dimension|tag|arrange``; a move keeps the old
position) so :func:`undo_automation` takes it all back, and nothing else is touched. The AI
assistant calls these as its ``annotate_drawings`` tool (``drawings/automate``); the app runs them
from the Exports page. A sheet drawn again (the set regenerated) loses them, as any hand edit:
run them again after regenerating.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import ezdxf

from saengine.drawings.sheets.layout import APP_ID, read_tags, text_rect

GRID_LAYER = "S-GRID"
DIM_LAYER = "S-DIMS"
TEXT_LAYER = "S-TEXT"
#: Layers whose texts :func:`auto_arrange` may move.
ANNOTATION_LAYERS = ("S-TEXT", "M-ANNO", "A-AREA-IDEN", "S-DIMS")
#: Layers of the members :func:`auto_tag` marks.
MEMBER_LAYERS = ("S-COLS", "S-BEAM", "S-WALL", "S-STEEL", "S-FNDN", "S-PILE")
ACTIONS = ("dimension", "tag", "arrange")
AUTO = "auto"


def _scale(doc: Any) -> float:
    try:
        return float(doc.header.get("$DIMSCALE", 1.0)) or 1.0
    except (TypeError, ValueError):
        return 1.0


def _mark(entity: Any, action: str, **extra: Any) -> None:
    values = {AUTO: action, **extra}
    entity.set_xdata(APP_ID, [(1000, f"{k}={v}") for k, v in values.items()])


def _is_auto(entity: Any) -> str | None:
    return read_tags(entity).get(AUTO)


def _grid_lines(
    msp: Any,
) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]]:
    """Vertical lines (x, y0, y1) and horizontal lines (y, x0, x1) on the grid layer."""
    vertical, horizontal = [], []
    for line in msp.query(f'LINE[layer=="{GRID_LAYER}"]'):
        a, b = line.dxf.start, line.dxf.end
        if abs(a.x - b.x) < 1e-6 and abs(a.y - b.y) > 1e-6:
            vertical.append((a.x, min(a.y, b.y), max(a.y, b.y)))
        elif abs(a.y - b.y) < 1e-6 and abs(a.x - b.x) > 1e-6:
            horizontal.append((a.y, min(a.x, b.x), max(a.x, b.x)))
    return vertical, horizontal


def _groups(
    lines: list[tuple[float, float, float]], tol: float
) -> list[list[tuple[float, float, float]]]:
    """Grid lines of one plan: the lines whose spans overlap, as separate plans on a sheet."""
    groups: list[list[tuple[float, float, float]]] = []
    for line in sorted(lines, key=lambda v: (v[1], v[0])):
        for group in groups:
            lo = min(g[1] for g in group)
            hi = max(g[2] for g in group)
            if line[1] < hi + tol and line[2] > lo - tol:
                group.append(line)
                break
        else:
            groups.append([line])
    return groups


def _positions(group: Iterable[tuple[float, float, float]], tol: float) -> list[float]:
    out: list[float] = []
    for value in sorted(v[0] for v in group):
        if not out or value - out[-1] > tol:
            out.append(value)
    return out


def _has_dimension(msp: Any, axis: str, a: float, b: float, tol: float) -> bool:
    """Whether a linear dimension measures from ``a`` to ``b`` along ``axis`` already."""
    for dim in msp.query("DIMENSION"):
        try:
            p1, p2 = dim.dxf.defpoint2, dim.dxf.defpoint3
        except AttributeError:
            continue
        lo, hi = sorted((p1.x, p2.x) if axis == "x" else (p1.y, p2.y))
        if abs(lo - a) < tol and abs(hi - b) < tol:
            return True
    return False


def auto_dimension(doc: Any) -> dict[str, Any]:
    """Adds the missing chain and overall dimensions of every plan's grids (see the module)."""
    msp = doc.modelspace()
    scale = _scale(doc)
    tol = 0.5 * scale  # half a paper mm
    style = doc.header.get("$DIMSTYLE", "Standard")
    if style not in doc.dimstyles:
        style = "Standard"
    vertical, horizontal = _grid_lines(msp)
    added = 0
    for group in _groups(vertical, tol):
        xs = _positions(group, tol)
        if len(xs) < 2:
            continue
        bottom = min(g[1] for g in group)
        for k, (a, b) in enumerate([*itertools.pairwise(xs), (xs[0], xs[-1])]):
            if (b - a) < tol or _has_dimension(msp, "x", a, b, tol):
                continue
            offset = (8 if k < len(xs) - 1 else 16) * scale
            dim = msp.add_linear_dim(
                base=(a, bottom - offset),
                p1=(a, bottom),
                p2=(b, bottom),
                dimstyle=style,
                dxfattribs={"layer": DIM_LAYER},
            )
            dim.render()
            _mark(dim.dimension, "dimension")
            added += 1
    for group in _groups(horizontal, tol):
        ys = _positions(group, tol)
        if len(ys) < 2:
            continue
        left = min(g[1] for g in group)
        for k, (a, b) in enumerate([*itertools.pairwise(ys), (ys[0], ys[-1])]):
            if (b - a) < tol or _has_dimension(msp, "y", a, b, tol):
                continue
            offset = (8 if k < len(ys) - 1 else 16) * scale
            dim = msp.add_linear_dim(
                base=(left - offset, a),
                p1=(left, a),
                p2=(left, b),
                angle=90,
                dimstyle=style,
                dxfattribs={"layer": DIM_LAYER},
            )
            dim.render()
            _mark(dim.dimension, "dimension")
            added += 1
    return {"added": added}


def _centre(entity: Any) -> tuple[float, float] | None:
    try:
        if entity.dxftype() == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in entity.get_points()]
        elif entity.dxftype() == "LINE":
            pts = [(entity.dxf.start.x, entity.dxf.start.y), (entity.dxf.end.x, entity.dxf.end.y)]
        elif entity.dxftype() == "CIRCLE":
            return (entity.dxf.center.x, entity.dxf.center.y)
        elif entity.dxftype() == "INSERT":
            return (entity.dxf.insert.x, entity.dxf.insert.y)
        else:
            return None
    except (AttributeError, ValueError):
        return None
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _texts(msp: Any) -> list[tuple[Any, str, tuple[float, float]]]:
    out = []
    for t in msp.query("TEXT MTEXT"):
        text = t.dxf.text if t.dxftype() == "TEXT" else t.plain_text()
        try:
            at = (
                t.dxf.align_point
                if t.dxftype() == "TEXT" and t.dxf.hasattr("align_point")
                else t.dxf.insert
            )
        except AttributeError:
            continue
        out.append((t, str(text), (at.x, at.y)))
    return out


def auto_tag(doc: Any) -> dict[str, Any]:
    """Marks the members that carry a mark in XDATA and have none near them (see the module)."""
    msp = doc.modelspace()
    scale = _scale(doc)
    height = 2.5 * scale
    near = 15 * scale
    texts = _texts(msp)
    added = 0
    seen: set[tuple[str, int, int]] = set()
    for entity in msp.query("LWPOLYLINE LINE CIRCLE INSERT"):
        if entity.dxf.layer not in MEMBER_LAYERS:
            continue
        tags = read_tags(entity)
        mark = tags.get("mark") or tags.get("id")
        centre = _centre(entity)
        if not mark or centre is None:
            continue
        key = (mark, round(centre[0] / near), round(centre[1] / near))
        if key in seen:
            continue
        seen.add(key)
        if any(mark in text and math.dist(at, centre) < near for _, text, at in texts):
            continue
        at = (centre[0] + 1.5 * scale, centre[1] + 1.5 * scale)
        label = msp.add_text(
            mark,
            height=height,
            dxfattribs={
                "layer": TEXT_LAYER,
                "style": "SAE" if "SAE" in doc.styles else "Standard",
                "insert": at,
            },
        )
        _mark(label, "tag")
        texts.append((label, mark, at))
        added += 1
    return {"added": added}


def _rect(
    entity: Any, text: str, at: tuple[float, float], scale: float
) -> tuple[float, float, float, float]:
    height = float(
        entity.dxf.get("height", 2.5 * scale)
        if entity.dxftype() == "TEXT"
        else entity.dxf.get("char_height", 2.5 * scale)
    )
    x0, y0, x1, y1 = text_rect(at[0] / scale, at[1] / scale, text, height / scale, "BL")
    return (x0 * scale, y0 * scale, x1 * scale, y1 * scale)


def _overlap(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def auto_arrange(doc: Any) -> dict[str, Any]:
    """Moves overlapping annotation texts apart (see the module)."""
    msp = doc.modelspace()
    scale = _scale(doc)
    items = [
        (t, text, at, _rect(t, text, at, scale))
        for t, text, at in _texts(msp)
        if t.dxf.layer in ANNOTATION_LAYERS and text.strip()
    ]
    rects = [r for *_, r in items]
    moved = 0
    unresolved = 0
    for k, (entity, _text, at, rect) in enumerate(items):
        others = rects[:k] + rects[k + 1 :]
        if not any(_overlap(rect, o) for o in others):
            continue
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        found = None
        for step in (1.0, 2.0, 3.0, 4.0):
            for angle in range(0, 360, 45):
                dx = math.cos(math.radians(angle)) * step * max(h, 1.0) * 1.2
                dy = math.sin(math.radians(angle)) * step * max(h, 1.0) * 1.2
                candidate = (rect[0] + dx, rect[1] + dy, rect[0] + dx + w, rect[1] + dy + h)
                if not any(_overlap(candidate, o) for o in others):
                    found = (dx, dy, candidate)
                    break
            if found:
                break
        if found is None:
            unresolved += 1
            continue
        dx, dy, candidate = found
        old = entity.dxf.insert
        entity.dxf.insert = (old.x + dx, old.y + dy)
        if entity.dxftype() == "TEXT" and entity.dxf.hasattr("align_point"):
            ap = entity.dxf.align_point
            entity.dxf.align_point = (ap.x + dx, ap.y + dy)
        tags = read_tags(entity)
        if AUTO not in tags:
            _mark(
                entity, "arrange", dx=f"{dx:.6f}", dy=f"{dy:.6f}", **{k: v for k, v in tags.items()}
            )
        rects[k] = candidate
        moved += 1
    return {"moved": moved, "unresolved": unresolved}


def undo_automation(doc: Any) -> dict[str, Any]:
    """Takes back everything the commands added or moved."""
    msp = doc.modelspace()
    removed = restored = 0
    for entity in list(msp):
        action = _is_auto(entity)
        if action in ("dimension", "tag"):
            msp.delete_entity(entity)
            removed += 1
        elif action == "arrange":
            tags = read_tags(entity)
            dx, dy = float(tags.get("dx", 0)), float(tags.get("dy", 0))
            old = entity.dxf.insert
            entity.dxf.insert = (old.x - dx, old.y - dy)
            if entity.dxftype() == "TEXT" and entity.dxf.hasattr("align_point"):
                ap = entity.dxf.align_point
                entity.dxf.align_point = (ap.x - dx, ap.y - dy)
            rest = {k: v for k, v in tags.items() if k not in (AUTO, "dx", "dy")}
            entity.discard_xdata(APP_ID)
            if rest:
                entity.set_xdata(APP_ID, [(1000, f"{k}={v}") for k, v in rest.items()])
            restored += 1
    return {"removed": removed, "restored": restored}


def automate_sheet(path: str | Path, actions: Iterable[str]) -> dict[str, Any]:
    """Runs ``actions`` (``dimension``, ``tag``, ``arrange``, or ``undo``) on the sheet DXF at
    ``path`` and saves it: ``{"path", "results": {action: counts}}``."""
    path = Path(path)
    doc = ezdxf.readfile(str(path))
    if APP_ID not in doc.appids:
        doc.appids.add(APP_ID)
    results: dict[str, Any] = {}
    for action in actions:
        if action == "dimension":
            results[action] = auto_dimension(doc)
        elif action == "tag":
            results[action] = auto_tag(doc)
        elif action == "arrange":
            results[action] = auto_arrange(doc)
        elif action == "undo":
            results[action] = undo_automation(doc)
        else:
            raise ValueError(f"unknown action {action!r} (dimension, tag, arrange, undo)")
    doc.saveas(str(path))
    return {"path": str(path), "results": results}


def rpc_automate(params: dict[str, Any]) -> dict[str, Any]:
    """``drawings/automate`` ``{projectRoot, sheets?, actions}``: the actions on the sheets of the
    last generated set (``sheets``: their numbers, e.g. ``["S-101"]``; default all), each sheet's
    answer, or ``{"error"}``. Only DXF files inside ``11 Exports/Drawings`` are touched."""
    root = Path(str(params.get("projectRoot") or ""))
    folder = (root / "11 Exports" / "Drawings").resolve()
    actions = [a for a in params.get("actions") or [] if isinstance(a, str)]
    if not actions:
        return {"error": "give the actions: dimension, tag, arrange or undo"}
    if not folder.is_dir():
        return {"error": "No drawings yet: generate the structural drawings first (Exports page)."}
    wanted = {str(s).upper() for s in params.get("sheets") or []}
    sheets = []
    for path in sorted(folder.glob("*.dxf")):
        if wanted and not any(path.stem.upper().startswith(w) for w in wanted):
            continue
        try:
            sheets.append(automate_sheet(path, actions))
        except (OSError, ValueError, ezdxf.DXFError) as error:
            sheets.append({"path": str(path), "error": str(error)})
    if not sheets:
        return {"error": "No sheet matches." if wanted else "The drawings folder has no sheets."}
    return {
        "sheets": sheets,
        "note": "Regenerating the drawing set draws the sheets again without these changes.",
    }


__all__ = [
    "ACTIONS",
    "auto_arrange",
    "auto_dimension",
    "auto_tag",
    "automate_sheet",
    "rpc_automate",
    "undo_automation",
]

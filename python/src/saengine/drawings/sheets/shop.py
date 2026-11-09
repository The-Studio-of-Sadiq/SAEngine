"""Steel shop drawings (alpha 9 L10): the fabrication model (:mod:`saengine.fabrication.model`)
drawn as sheets for the fabricator, numbered on their own (``SD-101`` on) and written apart from
the structural drawing set (``11 Exports/Shop Drawings``):

- the marking plans: the steel framing plans and the braced elevations of the structural sheets
  (:func:`saengine.drawings.sheets.steel.steel_plan`, :func:`~.steel.steel_elevation`) with the
  assembly marks in place of the member marks (general arrangement for erection);
- one assembly drawing per assembly mark: the main part's elevation (its web face; a member
  longer than the sheet allows is drawn broken, its dimensions true), its top (and bottom)
  flange when they are drilled, the cut length, the copes and end cuts, every hole group
  dimensioned from the member's end, the parts welded to it with their marks and their weld
  symbols (AWS A2.4 or ISO 2553 system A or B: the pack's ``fabrication.weldSymbols`` or Project
  Settings › Drawings › Fabrication), and its bill of materials (part, number, profile or plate,
  length, grade, mass), the loose parts with it;
- the single-part drawings of the plates: outline, holes dimensioned from the edges, thickness,
  grade and how many;
- the bill of materials of all assemblies and the list of all parts.

Layers as the structural steel sheets (``S-STEEL``, ``S-STEEL-PLATE``, ``S-BOLT``, ``S-WELD``,
docs/drawings-layers.md).
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from saengine.drawings.sheets.layout import TEXT, Sheet, View, ViewSpec, drawing_area, text_width
from saengine.drawings.sheets.model import Table
from saengine.drawings.sheets.steel import _bolt, weld_symbol

PREFIX = "SD-"
"""The shop drawings' sheet numbers (``SD-101``, ...)."""
FIRST = 101
SCALES = (5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0)
PART_SCALES = (2.0, 5.0, 10.0, 15.0, 20.0, 25.0)
BREAK_GAP = 24.0  # paper mm between the two ends of a broken elevation
KEEP = 150.0  # mm of plain member kept beyond the last feature at a broken end
DATA_WIDTH = 100.0  # paper mm of the data and bill of materials column
LINE = TEXT * 1.6

SYMBOL_NAMES = {"aws": "AWS A2.4", "isoA": "ISO 2553 system A", "isoB": "ISO 2553 system B"}


def symbol_name(symbols: str) -> str:
    return SYMBOL_NAMES.get(symbols, symbols)


def weld(
    view: View,
    at: Sequence[float],
    w: Any,
    symbols: str,
    tail: str = "",
    tries: Sequence[tuple[float, float]] | None = None,
) -> None:
    """The weld symbol of a :class:`saengine.fabrication.model.Weld` in the standard
    ``symbols`` (aws, isoA, isoB): ISO writes the fillet's leg ``z``; a complete joint
    penetration weld is a bevel groove with "CJP" in the tail; an all-round weld its circle."""
    iso = symbols.startswith("iso")
    groove = w.kind == "cjp"
    size = "" if groove else (f"z{w.size:g}" if iso else f"{w.size:g}")
    note = "CJP" if groove else w.note
    weld_symbol(
        view,
        (float(at[0]), float(at[1])),
        w.size,
        w.length,
        w.both,
        tail or note,
        tries,
        size_text=size,
        identification=symbols == "isoA",
        all_round=w.length is None,
        groove=groove,
    )


# ─────────────────────────────────── broken elevations ───────────────────────────────────


class Axis:
    """x along a member mapped onto a (maybe broken) elevation: kept whole when it fits, else
    its first ``keep_start`` and last ``keep_end`` mm with a gap of ``gap`` real mm between."""

    def __init__(self, length: float, keep_start: float, keep_end: float, gap: float) -> None:
        self.length = length
        self.broken = keep_start + keep_end + gap < length
        self.a = keep_start
        self.b = keep_end
        self.gap = gap

    def __call__(self, x: float) -> float:
        if not self.broken or x <= self.a:
            return x
        if x >= self.length - self.b:
            return x - (self.length - self.b - self.a) + self.gap
        return self.a + self.gap / 2

    @property
    def span(self) -> float:
        return self(self.length)

    @property
    def break_at(self) -> float:
        return self.a + self.gap / 2


def _extent(asm: Any) -> tuple[float, float, float, float]:
    """(furthest feature from the start, from the end, lowest y, highest y) of an assembly's
    elevation: holes, copes and the parts on it."""
    main = asm.main
    L = main.length
    first, last = 0.0, 0.0
    lo, hi = 0.0, main.h
    xs = [h.x for h in main.holes]
    xs += [c.length for c in main.copes if c.end == "start"]
    xs += [L - c.length for c in main.copes if c.end == "end"]
    for a in asm.parts:
        pts = outline(a, main, asm.kind == "column")
        if pts:
            lo = min(lo, *(y for _, y in pts))
            hi = max(hi, *(y for _, y in pts))
            if a.face not in ("start", "end"):
                xs += [x for x, _ in pts]
    for x in xs:
        if x <= L / 2:
            first = max(first, x)
        else:
            last = max(last, L - x)
    return first, last, lo, hi


def _rect(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def outline(a: Any, main: Any, column: bool) -> list[tuple[float, float]] | None:
    """A part of an assembly in the main part's elevation (x along it, y up its depth: its web
    face), or None when it is not drawn there (loose parts). ``column``: the main part is a
    column (the parts on its flanges and web stand along its axis)."""
    p = a.part
    t = p.tw
    L, h = main.length, main.h
    if a.loose:
        return None
    if a.face in ("start", "end"):
        if p.role == "tab" and a.weld is not None and a.weld.length:
            inside = a.weld.length
            if a.face == "end":
                return _rect(L - inside, h / 2 - p.h / 2, L - inside + p.length, h / 2 + p.h / 2)
            return _rect(inside - p.length, h / 2 - p.h / 2, inside, h / 2 + p.h / 2)
        x0, x1 = (-t, 0.0) if a.face == "start" else (L, L + t)
        return _rect(x0, h / 2 - p.length / 2, x1, h / 2 + p.length / 2)
    if a.face in ("o", "u"):
        sign = 1.0 if a.face == "o" else -1.0
        base = h if a.face == "o" else 0.0
        if p.role == "gusset":  # face on, its weld along the flange
            return [(a.x + px - a.anchor, base + sign * py) for px, py in p.outline()]
        if p.role == "flange plate":  # edge on, standing out of the flange
            return _rect(a.x - t, base, a.x, base + sign * p.length)
        # a fin plate face on, its welded edge on the flange
        return _rect(a.x - p.length / 2, base, a.x + p.length / 2, base + sign * p.h)
    # on the web (v, h)
    if p.role == "stiffener":
        return _rect(a.x - t / 2, main.tf, a.x + t / 2, h - main.tf)
    if p.role == "doubler":
        return _rect(a.x, h / 2 - p.h / 2, a.x + p.length, h / 2 + p.h / 2)
    if column:
        if p.role == "flange plate":  # edge on, across the web
            return _rect(a.x - t, h / 2 - p.h / 2, a.x, h / 2 + p.h / 2)
        # a fin plate or gusset edge on, along the axis
        return _rect(a.x - p.length / 2, h / 2 - t / 2, a.x + p.length / 2, h / 2 + t / 2)
    # a beam's web: a fin plate edge on, across the beam at its height
    centre = a.offset or h / 2
    return _rect(a.x - t / 2, centre - p.length / 2, a.x + t / 2, centre + p.length / 2)


def _weld_point(a: Any, main: Any, column: bool) -> tuple[float, float]:
    h = main.h
    if a.face == "start":
        return (0.0, h / 2)
    if a.face == "end":
        return (main.length, h / 2)
    if a.face == "o":
        return (a.x, h)
    if a.face == "u":
        return (a.x, 0.0)
    return (a.x, h / 2 if column else (a.offset or h / 2))


# ─────────────────────────────────── the assembly drawing ───────────────────────────────────


def _main_outline(main: Any) -> list[tuple[float, float]]:
    """The main part's elevation outline with its copes (counter-clockwise)."""
    L, h = main.length, main.h

    def cope(end: str, side: str) -> tuple[float, float]:
        for c in main.copes:
            if c.end == end and c.side == side:
                return c.length, c.depth
        return 0.0, 0.0

    (ls_t, ds_t), (le_t, de_t) = cope("start", "top"), cope("end", "top")
    (ls_b, ds_b), (le_b, de_b) = cope("start", "bottom"), cope("end", "bottom")
    pts = [(0.0, ds_b)]
    if ds_b:
        pts += [(ls_b, ds_b), (ls_b, 0.0)]
    pts += [(L - le_b, 0.0), (L - le_b, de_b), (L, de_b)] if de_b else [(L, 0.0)]
    pts += [(L, h - de_t), (L - le_t, h - de_t), (L - le_t, h)] if de_t else [(L, h)]
    pts += [(ls_t, h), (ls_t, h - ds_t), (0.0, h - ds_t)] if ds_t else [(0.0, h)]
    return pts


def _poly(view: View, axis: Axis, pts: Sequence[tuple[float, float]], layer: str, **kw: Any):
    return view.polyline([(axis(x), y) for x, y in pts], layer, close=True, **kw)


def _flange_view(view: View, axis: Axis, main: Any, face: str) -> None:
    """A flange (o: top, u: bottom) seen from outside: its outline less its copes, the web's
    line, its holes and their positions across it."""
    L, b = main.length, main.b
    side = "top" if face == "o" else "bottom"
    x0 = max([c.length for c in main.copes if c.end == "start" and c.side == side] or [0.0])
    x1 = L - max([c.length for c in main.copes if c.end == "end" and c.side == side] or [0.0])
    _poly(view, axis, [(x0, 0.0), (x1, 0.0), (x1, b), (x0, b)], "S-STEEL")
    view.line((axis(x0), b / 2), (axis(x1), b / 2), "S-STEEL-AXIS")
    holes = [h for h in main.holes if h.face == face]
    for h in holes:
        _bolt(view, (axis(h.x), h.y), h.dia, face=face, dia=f"{h.dia:g}")
    if holes:
        ys = sorted({round(h.y, 1) for h in holes})
        view.chain([(axis(0.0), y) for y in [0.0, *ys, b]], 8, angle=90)
        _x_dims(view, axis, main, [h.x for h in holes], 0.0, -8)
    if axis.broken:
        _break_marks(view, axis, 0.0, b)


def _break_marks(view: View, axis: Axis, y0: float, y1: float) -> None:
    """The break lines of a broken elevation, a pair across it."""
    from saengine.drawings.sheets.steel import _break

    x = axis.break_at
    for dx in (-axis.gap / 4, axis.gap / 4):
        _break(view, (x + dx, y1 + view.real(3)), (x + dx, y0 - view.real(3)), "S-STEEL")


def _x_dims(view: View, axis: Axis, main: Any, xs: Sequence[float], y: float, offset: float):
    """Chains from each end of the main part to the features ``xs`` nearer that end (their true
    lengths written), at the level ``y``, ``offset`` paper mm off it."""
    L = main.length
    first = sorted({round(x, 1) for x in xs if 0.5 < x <= L / 2})
    last = sorted({round(x, 1) for x in xs if L / 2 < x < L - 0.5})
    for chain in ([0.0, *first], [*last, L]):
        for a, b in itertools.pairwise(chain):
            if b - a >= 0.5:
                view.dim((axis(a), y), (axis(b), y), offset, text=f"{b - a:.0f}")


def assembly_view(asm: Any, symbols: str, max_size: tuple[float, float]) -> ViewSpec:
    """The assembly drawing of ``asm`` (the first assembly of its mark) with its data and bill of
    materials beside it, fitted to ``max_size`` (paper mm)."""
    main = asm.main
    column = asm.kind == "column"
    L, h = main.length, main.h
    first, last, lo, hi = _extent(asm)
    faces = [
        f for f in ("o", "u")
        if any(x.face == f for x in main.holes)
        or (f == "o" and any(c.side == "top" for c in main.copes))
    ]  # fmt: skip
    lines, bom = _data(asm, symbols)
    data_h = len(lines) * LINE + 6 + bom_height(bom)
    room_w = max_size[0] - DATA_WIDTH - 60
    room_h = max_size[1] - 40
    scale, axis = SCALES[-1], Axis(L, L, 0.0, 0.0)
    for s in SCALES:
        whole = Axis(L, L, 0.0, 0.0)
        cut = Axis(L, first + KEEP, last + KEEP, BREAK_GAP * s)
        height = (hi - lo) / s + len(faces) * (main.b / s + 16) + 50
        if height > room_h:
            continue
        if L / s <= room_w:
            scale, axis = s, whole
            break
        if cut.broken and cut.span / s <= room_w and s <= 20:
            scale, axis = s, cut
            break
    else:
        cut = Axis(L, first + KEEP, last + KEEP, BREAK_GAP * scale)
        axis = cut if cut.broken else axis
    span = axis.span
    elev_h = (hi - lo) / scale
    draw_w = 32 + span / scale + 22
    draw_h = 18 + elev_h + 28 + sum(main.b / scale + 16 for _ in faces) + 4
    width = draw_w + DATA_WIDTH
    height = max(draw_h, data_h)

    def draw(view: View) -> None:
        # the data and the bill of materials first, beside the drawing
        y = height - 2
        for text in lines:
            view.text(text, (draw_w + 2, y), TEXT, "TL")
            y -= LINE
        draw_bom(view, bom, draw_w + 2, y - 2)
        bottom = height - 18 - elev_h
        ev = view.inset(32, bottom, scale, origin=(0.0, lo))
        _poly(ev, axis, _main_outline(main), "S-STEEL")
        if main.code in ("I", "U") and main.tf:
            for yy in (main.tf, h - main.tf):
                ev.line((axis(0.0), yy), (axis(L), yy), "S-STEEL", linetype="HIDDEN")
        elif main.code == "M" and main.tw:
            for yy in (main.tw, h - main.tw):
                ev.line((axis(0.0), yy), (axis(L), yy), "S-STEEL", linetype="HIDDEN")
        ev.line((axis(0.0) - ev.real(4), h / 2), (axis(L) + ev.real(4), h / 2), "S-STEEL-AXIS")
        if axis.broken:
            _break_marks(ev, axis, lo, hi)
        web = [x for x in main.holes if x.face in ("v", "h")]
        for hole in web:
            _bolt(ev, (axis(hole.x), hole.y), hole.dia, face=hole.face, dia=f"{hole.dia:g}")
        placed: list[float] = []
        for a in asm.parts:
            pts = outline(a, main, column)
            if not pts:
                continue
            extra = {"linetype": "HIDDEN"} if a.part.role == "doubler" else {}
            _poly(ev, axis, pts, "S-STEEL-PLATE", **extra)
            if a.face not in ("start", "end"):
                placed.append(a.x)
            cx = sum(x for x, _ in pts) / len(pts)
            cy = sum(yy for _, yy in pts) / len(pts)
            ev.label(
                a.part.mark,
                (axis(cx), cy),
                [(8, 8, "BL"), (-8, 8, "BR"), (8, -8, "TL"), (-8, -8, "TR")],
                leader=True,
            )
            if a.weld is not None:
                wx, wy = _weld_point(a, main, column)
                weld(ev, (axis(wx), wy), a.weld, symbols)
        # where the holes and parts are: chains from the ends above, the cut length below,
        # the holes' heights at the ends
        xs = [x.x for x in web] + placed
        xs += [c.length for c in main.copes if c.end == "start"]
        xs += [L - c.length for c in main.copes if c.end == "end"]
        _x_dims(ev, axis, main, xs, hi, 8)
        ev.dim((axis(0.0), lo), (axis(L), lo), -10, text=f"{L:.0f}")
        for group, at_start in (
            ([x for x in web if x.x <= L / 2], True),
            ([x for x in web if x.x > L / 2], False),
        ):
            if group:
                ys = sorted({round(x.y, 1) for x in group})
                vx = axis(0.0) if at_start else axis(L)
                ev.chain([(vx, yy) for yy in [0.0, *ys, h]], 8 if at_start else -8, angle=90)
        for c in main.copes:
            x = c.length / 2 if c.end == "start" else L - c.length / 2
            ev.label(
                f"COPE {c.length:.0f} x {c.depth:.0f}",
                (axis(x), h if c.side == "top" else 0.0),
                [(0, 6, "BC"), (0, -6, "TC"), (10, 6, "BL")],
                leader=True,
            )
        if any(main.cuts):
            view.text(_cuts_text(main), (32, bottom - 18), TEXT, "TL")
        # the drilled flanges below the elevation
        yb = bottom - 28
        for face in faces:
            fh = main.b / scale
            fv = view.inset(32, yb - fh, scale, origin=(0.0, 0.0))
            _flange_view(fv, axis, main, face)
            view.text(
                "TOP FLANGE" if face == "o" else "BOTTOM FLANGE", (2, yb - fh / 2), TEXT, "ML"
            )
            yb -= fh + 16

    return ViewSpec(
        f"Assembly {asm.mark}",
        1,
        (0, 0, width, height),
        draw,
        pad=(2, 2, 2, 2),
        subtitle=f"{asm.quantity} OFF   {main.name}   L = {L:.0f}   SCALE 1:{scale:g}"
        + ("   (BROKEN)" if axis.broken else ""),
        key=f"assembly:{asm.mark}",
    )


def _cuts_text(main: Any) -> str:
    names = ("WEB START", "WEB END", "FLANGE START", "FLANGE END")
    return ", ".join(f"{n} CUT {c:.1f}°" for n, c in zip(names, main.cuts, strict=True) if c)


def _data(asm: Any, symbols: str) -> tuple[list[str], Table]:
    """The text beside an assembly drawing and its bill of materials."""
    main = asm.main
    members = ", ".join(asm.members[:12]) + (" ..." if len(asm.members) > 12 else "")
    lines = [
        f"ASSEMBLY {asm.mark}   {asm.quantity} OFF",
        *_wrap(f"MEMBERS: {members}", DATA_WIDTH - 4),
        f"MAIN PART {main.mark}: {main.name} {main.grade}, L = {main.length:.0f}",
        f"MASS {asm.mass:,.1f} kg EACH, {asm.mass * asm.quantity:,.1f} kg IN ALL",
        f"WELD SYMBOLS: {symbol_name(symbols)}",
        "HOLES: DIMENSIONS TO CENTRES FROM THE MEMBER'S ENDS",
    ]
    for note in [*main.notes, *asm.notes]:
        lines.extend(_wrap(note.upper(), DATA_WIDTH - 4))
    bom = bom_table(asm)
    return lines, bom


def _wrap(text: str, width: float) -> list[str]:
    words = text.split()
    out: list[str] = []
    line = ""
    for w in words:
        candidate = f"{line} {w}".strip()
        if line and text_width(candidate, TEXT) > width:
            out.append(line)
            line = w
        else:
            line = candidate
    if line:
        out.append(line)
    return out


BOM_COLUMNS = (
    ("Part", 9.0, "left"),
    ("No.", 7.0, "right"),
    ("Profile / plate", 30.0, "left"),
    ("Length", 12.0, "right"),
    ("Grade", 18.0, "left"),
    ("kg", 12.0, "right"),
)


def bom_table(asm: Any) -> Table:
    """The bill of materials of one assembly: its main part, the parts welded to it, then its
    loose parts (marked L), the number of each in one assembly, the mass of them."""
    rows: list[list[str]] = []
    counted: dict[tuple[str, bool], int] = {}
    order: list[tuple[str, bool]] = []
    parts = {asm.main.mark: asm.main}
    counted[(asm.main.mark, False)] = 1
    order.append((asm.main.mark, False))
    for a in asm.parts:
        key = (a.part.mark, a.loose)
        parts[a.part.mark] = a.part
        if key not in counted:
            order.append(key)
        counted[key] = counted.get(key, 0) + 1
    for mark_, loose in order:
        p = parts[mark_]
        n = counted[(mark_, loose)]
        rows.append([
            mark_ + (" L" if loose else ""),
            str(n),
            p.name,
            f"{p.length:.0f}",
            p.grade,
            f"{p.mass * n:,.1f}",
        ])  # fmt: skip
    rows.append(["", "", "Total", "", "", f"{asm.mass:,.1f}"])
    columns = [{"key": k.lower(), "title": k, "width": w, "align": al} for k, w, al in BOM_COLUMNS]
    return Table(f"Bill of materials {asm.mark} (one assembly)", columns, rows)


def bom_height(table: Table) -> float:
    return (len(table.rows) + 2) * LINE + 4


def draw_bom(view: View, table: Table, x: float, y: float) -> None:
    """``table`` as a ruled grid with its top-left at paper (x, y) of a scale 1 view."""
    widths = [w for _, w, _ in BOM_COLUMNS]
    total = sum(widths)
    view.text(table.title.upper(), (x, y), TEXT, "TL")
    y -= LINE + 1
    rows = [[c["title"] for c in table.columns], *table.rows]
    view.line((x, y), (x + total, y), "S-TEXT")
    for i, row in enumerate(rows):
        cx = x
        for (_, w, align), cell in zip(BOM_COLUMNS, row, strict=False):
            if align == "right":
                view.text(cell, (cx + w - 1, y - LINE / 2), TEXT, "MR")
            else:
                view.text(cell, (cx + 1, y - LINE / 2), TEXT, "ML")
            cx += w
        y -= LINE
        view.line((x, y), (x + total, y), "S-TEXT", lineweight=35 if i == 0 else 13)


# ─────────────────────────────────── the part drawings ───────────────────────────────────


def part_view(
    part: Any, quantity: int, assemblies: Sequence[str], max_size: tuple[float, float]
) -> ViewSpec:
    """The single-part drawing of a plate: its outline, its holes dimensioned from its edges
    (chains along the bottom and the left), its data."""
    pts = part.outline()
    xs = [x for x, _ in pts]
    ys = [y for _, y in pts]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    scale = PART_SCALES[-1]
    for s in PART_SCALES:
        if w / s + 50 <= min(max_size[0] - 10, 260) and h / s + 60 <= max_size[1] - 40:
            scale = s
            break
    lines = [
        f"PART {part.mark}   {quantity} OFF",
        f"{part.name} x {part.length:.0f}   {part.grade}",
        f"{part.role.upper()}   {part.mass:,.2f} kg EACH",
        f"IN {', '.join(assemblies[:8])}" + (" ..." if len(assemblies) > 8 else ""),
    ]
    data_h = len(lines) * LINE + 4
    draw_w = max(w / scale + 50, max(text_width(t, TEXT) for t in lines) + 6)
    draw_h = h / scale + 40 + data_h

    def draw(view: View) -> None:
        y = draw_h - 2
        for text in lines:
            view.text(text, (2, y), TEXT, "TL")
            y -= LINE
        inset = view.inset(30, 22, scale, origin=(min(xs), min(ys)))
        inset.polyline(pts, "S-STEEL-PLATE", close=True)
        for hole in part.holes:
            _bolt(inset, (hole.x, hole.y), hole.dia, dia=f"{hole.dia:g}")
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        inset.dim((x0, y0), (x1, y0), -14)
        inset.dim((x0, y0), (x0, y1), 14, angle=90)
        if part.holes:
            hx = sorted({round(hl.x, 1) for hl in part.holes})
            hy = sorted({round(hl.y, 1) for hl in part.holes})
            inset.chain([(x, y0) for x in [x0, *hx, x1]], -7)
            inset.chain([(x0, y) for y in [y0, *hy, y1]], 7, angle=90)
            sizes = sorted({hl.dia for hl in part.holes})
            inset.label(
                f"{len(part.holes)} HOLES Ø{', Ø'.join(f'{d:g}' for d in sizes)}",
                (part.holes[0].x, part.holes[0].y),
                [(8, 8, "BL"), (-8, 8, "BR"), (8, -8, "TL")],
                leader=True,
            )

    return ViewSpec(
        f"Part {part.mark}",
        1,
        (0, 0, draw_w, draw_h),
        draw,
        pad=(2, 2, 2, 2),
        subtitle=f"PL {part.tw:g}   SCALE 1:{scale:g}",
        key=f"part:{part.mark}",
    )


# ─────────────────────────────────── tables and plans ───────────────────────────────────


def assemblies_table(model: Any) -> Table:
    """Every assembly mark: how many, its main part, its length and mass, its members."""
    columns = [
        {"key": "mark", "title": "Assembly", "width": 8, "align": "left"},
        {"key": "qty", "title": "No.", "width": 5, "align": "right"},
        {"key": "main", "title": "Main part", "width": 18, "align": "left"},
        {"key": "length", "title": "Length\n(mm)", "width": 8, "align": "right"},
        {"key": "each", "title": "kg\neach", "width": 8, "align": "right"},
        {"key": "all", "title": "kg", "width": 9, "align": "right"},
        {"key": "members", "title": "Members", "width": 30, "align": "left"},
    ]
    rows = []
    total = 0.0
    for a in model.marked():
        mass = a.mass * a.quantity
        total += mass
        rows.append([
            a.mark, str(a.quantity), f"{a.main.mark} {a.main.name}", f"{a.main.length:.0f}",
            f"{a.mass:,.1f}", f"{mass:,.1f}", ", ".join(a.members),
        ])  # fmt: skip
    rows.append(["TOTAL", "", "", "", "", f"{total:,.1f}", ""])
    return Table("Assemblies", columns, rows)


def parts_table(model: Any) -> Table:
    """Every part mark: how many, profile or plate, length, grade, mass."""
    columns = [
        {"key": "mark", "title": "Part", "width": 6, "align": "left"},
        {"key": "qty", "title": "No.", "width": 5, "align": "right"},
        {"key": "name", "title": "Profile / plate", "width": 18, "align": "left"},
        {"key": "length", "title": "Length\n(mm)", "width": 8, "align": "right"},
        {"key": "grade", "title": "Grade", "width": 14, "align": "left"},
        {"key": "each", "title": "kg\neach", "width": 8, "align": "right"},
        {"key": "all", "title": "kg", "width": 9, "align": "right"},
        {"key": "in", "title": "In assemblies", "width": 20, "align": "left"},
    ]
    rows = []
    for p, n in model.parts():
        rows.append([
            p.mark, str(n), p.name, f"{p.length:.0f}", p.grade, f"{p.mass:,.2f}",
            f"{p.mass * n:,.1f}", ", ".join(model.assemblies_of(p.mark)),
        ])  # fmt: skip
    return Table("Parts", columns, rows)


def marking_set(steel: Any, model: Any) -> Any:
    """The structural steel set with the assembly marks as the members' marks (the marking
    plans); a spliced member shows both its assemblies' marks."""
    marks: dict[str, list[str]] = {}
    for a in model.assemblies:
        marks.setdefault(a.member.split("/")[0], []).append(a.mark)
    members = [
        replace(m, mark="/".join(marks.get(m.id, [m.mark])), connection="") for m in steel.members
    ]
    return replace(steel, members=members, connections=[])


# ─────────────────────────────────── the sheets ───────────────────────────────────


def shop_categories(
    model: Any,
    building: Any,
    steel: Any,
    size: str,
    symbols: str,
    plan_scale: float = 100,
    elevation_scale: float = 50,
) -> tuple[list[Any], list[str]]:
    """The shop drawings' sheet categories (see the module notes) and their problems."""
    from saengine.drawings.sheets import schedules
    from saengine.drawings.sheets import steel as st
    from saengine.drawings.sheets.build import _Category, _fit_plan

    area = drawing_area(size)
    width, height = area[2] - area[0], area[3] - area[1]
    problems: list[str] = []
    out: list[Any] = []
    marking = marking_set(steel, model) if steel is not None else None
    if marking is not None and building is not None and marking.members:
        by_scale: dict[float, list[ViewSpec]] = {}
        for lv in sorted(building.levels, key=lambda lv: lv.elevation):
            if st.level_has_steel(marking, lv, building.levels):
                spec, p = _fit_plan(
                    lambda s, lv=lv: st.steel_plan(building, marking, lv, s), plan_scale, area
                )
                problems += p
                if spec is not None:
                    by_scale.setdefault(spec.scale, []).append(spec)
        for scale, specs in by_scale.items():
            out.append(_Category("Marking plans", scale, specs, plan=True, notes=MARKING_NOTES))
        by_scale = {}
        for line in st.elevation_lines(building, marking):
            spec, p = _fit_plan(
                lambda s, line=line: st.steel_elevation(building, marking, line, s),
                elevation_scale,
                area,
            )
            problems += p
            if spec is not None:
                by_scale.setdefault(spec.scale, []).append(spec)
        for scale, specs in by_scale.items():
            out.append(_Category("Marking elevations", scale, specs, notes=MARKING_NOTES))
    for asm in model.marked():
        spec = assembly_view(asm, symbols, (width, height))
        out.append(
            _Category(
                f"Assembly {asm.mark}",
                1,
                [spec],
                scale_text="AS SHOWN",
                notes=assembly_notes(symbols),
            )
        )
    plates = [(p, n) for p, n in model.parts() if p.kind == "plate"]
    specs = [part_view(p, n, model.assemblies_of(p.mark), (width, height)) for p, n in plates]
    if specs:
        out.append(_Category("Part drawings", 1, specs, scale_text="AS SHOWN", notes=PART_NOTES))
    specs = []
    for table in (assemblies_table(model), parts_table(model)):
        specs += schedules.table_specs(table, height, key=f"shop:{table.title}", max_width=width)
    out.append(_Category("Bills of materials", 1, specs, scale_text="NTS", notes=[]))
    return out, problems


MARKING_NOTES = [
    "Assembly marks of the shop drawings at the members (erection marks).",
    "Members spliced: the marks of both pieces.",
]
PART_NOTES = [
    "Plates: dimensions in mm; holes to centres from the plate's lower left corner.",
    "Thickness, grade and number on each drawing; cut edges free of notches.",
]


def assembly_notes(symbols: str) -> list[str]:
    return [
        f"Weld symbols to {symbol_name(symbols)}.",
        "Dimensions in mm; holes to centres from the member's ends.",
        "L in the bill of materials: a loose part, shipped with the assembly.",
        "Check against the design drawings before cutting.",
    ]


def shop_sheets(
    categories: Sequence[Any], size: str, info: Any, standard: Any = None
) -> list[Sheet]:
    """The categories packed onto sheets ``SD-101``, ... (one or more per category)."""
    from saengine.drawings.sheets.layout import centred, pack

    area = drawing_area(size)
    sheets: list[Sheet] = []
    number = FIRST
    for cat in categories:
        pages = pack(cat.specs, area)
        if cat.plan:
            pages = [centred(page, area) for page in pages]
        for i, page in enumerate(pages):
            title = cat.title if len(pages) == 1 else f"{cat.title} ({i + 1} of {len(pages)})"
            if cat.plan and len(page) == 1:
                title = page[0][0].title
            sheet = Sheet(
                f"{PREFIX}{number}",
                title,
                size,
                cat.scale,
                info,
                scale_text=cat.scale_text or f"1:{cat.scale:g}",
                standard=standard,
            )
            sheet.category = cat.title  # type: ignore[attr-defined]
            for spec, x, y in page:
                sheet.view(spec, x, y)
            if cat.notes:
                sheet.notes(cat.notes)
            sheet.finish()
            sheets.append(sheet)
            number += 1
    return sheets


def sheet_of_marks(sheets: Sequence[Sheet]) -> dict[str, str]:
    """The sheet number of each assembly and part drawing, by mark."""
    out: dict[str, str] = {}
    for sheet in sheets:
        for view in sheet.views:
            kind, _, mark = str(view.spec.key or "").partition(":")
            if kind in ("assembly", "part") and mark:
                out.setdefault(mark, sheet.number)
    return out


__all__ = [
    "Axis",
    "assemblies_table",
    "assembly_view",
    "bom_table",
    "part_view",
    "parts_table",
    "sheet_of_marks",
    "shop_categories",
    "shop_sheets",
]

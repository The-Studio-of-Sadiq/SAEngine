"""Schedules: the column schedule (marks by storeys, each cell the section with its bars and ties),
the beam elevations (bars with their extents, link zones, spans, sections), and tables (the bar
bending schedule, the general notes and their tables).

The views are laid out in paper millimetres (``ViewSpec.scale`` 1); the drawings inside them are
insets at their own scales (sections 1:25, elevations 1:50 by default).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from saengine.drawings.sheets.layout import (
    CHAR_WIDTH,
    TEXT,
    TEXT_LARGE,
    View,
    ViewSpec,
    _wrap,
    tag,
    text_width,
)
from saengine.drawings.sheets.model import (
    NOT_DESIGNED,
    BeamBar,
    BeamDetail,
    ColumnLine,
    Level,
    Table,
)
from saengine.drawings.sheets.sections import beam_section, column_section

ROW = 6.0  # paper mm per table row
LINE = TEXT * 1.6


# ─────────────────────────────────── tables ───────────────────────────────────


def _col_widths(table: Table, hints: bool = True) -> list[float]:
    """Column widths [paper mm]: the widest line of the column's cells and title (at least the
    width the table asks for, in characters, when ``hints``)."""
    widths = []
    for i, column in enumerate(table.columns):
        title = str(column.get("title") or "")
        lines = [line for r in table.rows if i < len(r) for line in str(r[i]).split("\n")]
        hint = int(column.get("width") or 0) * TEXT * CHAR_WIDTH * 0.85 if hints else 0.0
        widest = max([hint, *(text_width(t, TEXT) for t in [*lines, *title.split("\n")])])
        widths.append(widest + 3.5)
    return widths


def _wrap_to(text: str, width: float, height: float = TEXT) -> str:
    """``text`` broken at spaces into lines no wider than ``width`` (paper mm; a single word
    wider than that stays whole). Text that has to be re-wrapped is joined first (its line
    breaks were only a narrower wrap)."""
    text = str(text)
    if all(text_width(line, height) <= width for line in text.split("\n")):
        return text
    out: list[str] = []
    for line in [" ".join(text.split("\n"))]:
        if text_width(line, height) <= width:
            out.append(line)
            continue
        current = ""
        for word in line.split(" "):
            candidate = f"{current} {word}" if current else word
            if current and text_width(candidate, height) > width:
                out.append(current)
                current = word
            else:
                current = candidate
        out.append(current)
    return "\n".join(out)


def _min_width(table: Table, i: int) -> float:
    """The narrowest a column can be: its widest word (cells and title) and a little room."""
    column = table.columns[i]
    words = [
        w
        for text in [str(column.get("title") or ""), *(str(r[i]) for r in table.rows if i < len(r))]
        for line in text.split("\n")
        for w in line.split(" ")
        if w
    ]
    return max((text_width(w, TEXT) for w in words), default=TEXT) + 3.0


def fit_table(table: Table, max_width: float | None) -> tuple[Table, list[float], bool]:
    """``table`` fitted to ``max_width`` paper mm: its columns at their natural widths when they
    fit; else the widest columns narrowed first (never below their widest word) and their cells
    and titles wrapped onto more lines. Returns the (re-wrapped) table, the column widths and
    whether it fits."""
    natural = _col_widths(table)
    if max_width is None or sum(natural) <= max_width + 1e-6:
        return table, natural, True
    # the widths the cells need (without the widths the table asks for)
    widths = _col_widths(table, hints=False)
    if sum(widths) <= max_width + 1e-6:  # the room left to the columns that asked for more
        spare = max_width - sum(widths)
        short = [n - w for n, w in zip(natural, widths)]
        total = sum(short) or 1.0
        fitted = [w + s * min(spare / total, 1.0) for w, s in zip(widths, short)]
        return table, fitted, True
    mins = [min(_min_width(table, i), w) for i, w in enumerate(widths)]
    if sum(mins) > max_width:
        fitted = mins
    else:  # the cap c with sum(min(natural, max(c, min))) == max_width
        lo, hi = 0.0, max(widths)
        for _ in range(60):
            c = (lo + hi) / 2
            if sum(min(w, max(c, m)) for w, m in zip(widths, mins)) > max_width:
                hi = c
            else:
                lo = c
        fitted = [min(w, max(lo, m)) for w, m in zip(widths, mins)]
    columns = []
    for column, w in zip(table.columns, fitted):
        title = _wrap_to(str(column.get("title") or ""), w - 3.0)
        columns.append({**column, "title": title})
    rows = [
        [_wrap_to(cell, fitted[i] - 3.0) if i < len(fitted) else cell for i, cell in enumerate(r)]
        for r in table.rows
    ]
    out = Table(table.title, columns, rows, table.groups, table.notes)
    return out, fitted, sum(fitted) <= max_width + 1e-6


def _header_height(table: Table) -> float:
    lines = max((len(str(c.get("title") or "").split("\n")) for c in table.columns), default=1)
    return lines * LINE + 3.0


def _row_height(row: Sequence[str]) -> float:
    lines = max((len(str(cell).split("\n")) for cell in row), default=1)
    return max(ROW, lines * LINE + 2.0)


def table_specs(
    table: Table, max_height: float, key: str = "table", max_width: float | None = None
) -> list[ViewSpec]:
    """``table`` as views no taller than ``max_height`` (paper mm), split between row groups,
    and no wider than ``max_width`` (its columns narrowed and wrapped: :func:`fit_table`)."""
    table, widths, _ = fit_table(table, None if max_width is None else max_width - 4.0)
    width = sum(widths)
    head = _header_height(table)
    room = max_height - head - 2 - 14 - 8
    heights = [_row_height(r) for r in table.rows]
    groups = table.groups or [{"first": i, "count": 1} for i in range(len(table.rows))]
    chunks: list[list[int]] = [[]]
    used = 0.0
    for g in groups:
        rows = list(range(int(g["first"]), int(g["first"]) + int(g["count"])))
        need = sum(heights[i] for i in rows)
        if used + need > room and chunks[-1]:
            chunks.append([])
            used = 0.0
        chunks[-1].extend(rows)
        used += need
    specs = []
    for n, chunk in enumerate(c for c in chunks if c or not table.rows):
        height = head + sum(heights[i] for i in chunk)
        title = table.title if len(chunks) == 1 else f"{table.title} ({n + 1} of {len(chunks)})"

        def draw(view: View, chunk: list[int] = chunk, height: float = height) -> None:
            _draw_table(view, table, widths, chunk, height, head, heights)

        specs.append(
            ViewSpec(
                title,
                1,
                (0, 0, width, height),
                draw,
                pad=(2, 2, 2, 2),
                subtitle=" ",
                key=f"{key}:{n + 1}",
            )
        )
    return specs


def _draw_table(
    view: View,
    table: Table,
    widths: list[float],
    rows: list[int],
    height: float,
    head: float,
    heights: list[float],
) -> None:
    total = sum(widths)
    view.rect(0, 0, total, height, "S-TABLE", lineweight=35)
    view.line((0, height - head), (total, height - head), "S-TABLE", lineweight=35)
    x = 0.0
    for w, column in zip(widths, table.columns):
        if x > 0:
            view.line((x, 0), (x, height), "S-TABLE")
        title = str(column.get("title") or "")
        view.text(title, (x + w / 2, height - head / 2), TEXT, "MC", "S-TABLE", reserve=False)
        x += w
    y = height - head
    groups = {int(g["first"]) for g in table.groups}
    for i in rows:
        row = table.rows[i]
        if y < height - head - 1e-6:
            weight = 25 if i in groups else 9
            view.line((0, y), (total, y), "S-TABLE", lineweight=weight)
        x = 0.0
        lines = max((len(str(c).split("\n")) for c in row), default=1)
        top = y - (heights[i] - (lines - 1) * LINE - TEXT) / 2  # the block centred in the row
        for w, column, cell in zip(widths, table.columns, row):
            if column.get("align") == "right":
                view.text(cell, (x + w - 1.5, top), TEXT, "TR", "S-TABLE", reserve=False)
            else:
                view.text(cell, (x + 1.5, top), TEXT, "TL", "S-TABLE", reserve=False)
            x += w
        y -= heights[i]


def notes_spec(
    notes: Sequence[str], width: float = 180.0, title: str = "General notes"
) -> ViewSpec:
    """Numbered notes wrapped to ``width`` paper mm."""
    lines: list[str] = []
    for i, note in enumerate(notes, 1):
        wrapped = _wrap(note, width - 10, TEXT, 12).split("\n")
        lines.append(f"{i}.\t{wrapped[0]}")
        lines += [f"\t{part}" for part in wrapped[1:]]
    height = max(len(lines), 1) * LINE + 2

    def draw(view: View) -> None:
        y = height - 1
        for line in lines:
            number, _, rest = line.partition("\t")
            if number:
                view.text(number, (0, y), TEXT, "TL")
            view.text(rest, (8, y), TEXT, "TL")
            y -= LINE

    return ViewSpec(
        title, 1, (0, 0, width, height), draw, pad=(2, 2, 2, 2), subtitle=" ", key="notes"
    )


# ─────────────────────────────────── column schedule ───────────────────────────────────


def _merged(lines: list[ColumnLine]) -> list[ColumnLine]:
    """Column lines with the same sections on every storey, shown once with all their marks."""
    merged: dict[tuple, ColumnLine] = {}
    for line in lines:
        key = tuple(sorted((lv, s.key()) for lv, s in line.sections.items()))
        if key in merged:
            merged[key].mark += f", {line.mark}"
            merged[key].members += line.members
        else:
            merged[key] = ColumnLine(line.mark, list(line.members), dict(line.sections))
    return list(merged.values())


def column_schedule(
    lines: list[ColumnLine],
    levels: list[Level],
    scale: float = 25,
    max_size: tuple[float, float] = (760.0, 540.0),
) -> list[ViewSpec]:
    """The column schedule: a row per storey (top storey first), a column per mark; each cell
    the section at ``1:scale`` with its size, bars, ties and cover. Split into several views
    when wider or taller than ``max_size`` (paper mm)."""
    lines = _merged([line for line in lines if line.sections])
    if not lines:
        return []
    ordered = sorted(levels, key=lambda lv: lv.elevation)
    used = {lv for line in lines for lv in line.sections}
    storeys = [(lv, ordered[i - 1] if i else None) for i, lv in enumerate(ordered) if lv.id in used]
    storeys.reverse()

    def cell_text(section) -> list[str]:
        if not section.designed:
            return [section.size_text, NOT_DESIGNED, "NO REINFORCEMENT"]
        return [
            section.size_text,
            section.bars_text,
            *section.ties_text,
            f"COVER {section.cover:g}",
        ]

    label_w = max(32.0, *(text_width(_storey(lv, below), TEXT) + 6 for lv, below in storeys))
    widths = []
    for line in lines:
        w = 30.0
        for section in line.sections.values():
            w = max(
                w, section.b / scale + 16, *(text_width(t, TEXT) + 6 for t in cell_text(section))
            )
        w = max(w, text_width(line.mark, TEXT_LARGE) + 6)
        widths.append(w)
    heights = []
    for lv, _ in storeys:
        h = 20.0
        for line in lines:
            s = line.sections.get(lv.id)
            if s:
                h = max(h, s.h / scale + 14 + LINE * len(cell_text(s)) + 4)
        heights.append(h)
    head = 10.0
    # split the marks into chunks that fit the width, the storeys into chunks that fit the height
    col_chunks: list[list[int]] = [[]]
    used_w = label_w
    for i, w in enumerate(widths):
        if used_w + w > max_size[0] - 10 and col_chunks[-1]:
            col_chunks.append([])
            used_w = label_w
        col_chunks[-1].append(i)
        used_w += w
    row_chunks: list[list[int]] = [[]]
    used_h = head
    for j, h in enumerate(heights):
        if used_h + h > max_size[1] - 30 and row_chunks[-1]:
            row_chunks.append([])
            used_h = head
        row_chunks[-1].append(j)
        used_h += h
    specs = []
    total = len(col_chunks) * len(row_chunks)
    for rows in row_chunks:
        for cols in col_chunks:
            width = label_w + sum(widths[i] for i in cols)
            height = head + sum(heights[j] for j in rows)
            n = len(specs) + 1

            def draw(view: View, rows=rows, cols=cols, width=width, height=height) -> None:
                view.rect(0, 0, width, height, "S-TABLE", lineweight=35)
                view.line((0, height - head), (width, height - head), "S-TABLE", lineweight=35)
                view.text("STOREY", (label_w / 2, height - head / 2), TEXT, "MC", "S-TABLE")
                x = label_w
                for i in cols:
                    view.line((x, 0), (x, height), "S-TABLE")
                    view.text(
                        lines[i].mark,
                        (x + widths[i] / 2, height - head / 2),
                        TEXT_LARGE,
                        "MC",
                        "S-TABLE",
                    )
                    x += widths[i]
                y = height - head
                for j in rows:
                    lv, below = storeys[j]
                    h = heights[j]
                    view.line((0, y - h), (width, y - h), "S-TABLE")
                    view.text(_storey(lv, below), (3, y - h / 2), TEXT, "ML", "S-TABLE")
                    x = label_w
                    for i in cols:
                        s = lines[i].sections.get(lv.id)
                        if s is not None:
                            cx = x + widths[i] / 2
                            cy = y - 6 - s.h / scale / 2
                            inset = view.inset(cx, cy, scale)
                            column_section(inset, (0.0, 0.0), s)
                            view.text(
                                "\n".join(cell_text(s)),
                                (cx, cy - s.h / scale / 2 - 8),
                                TEXT,
                                "TC",
                                "S-TEXT",
                            )
                        else:
                            view.text("-", (x + widths[i] / 2, y - h / 2), TEXT, "MC")
                        x += widths[i]
                    y -= h

            title = "Column schedule" if total == 1 else f"Column schedule ({n} of {total})"
            specs.append(
                ViewSpec(
                    title,
                    1,
                    (0, 0, width, height),
                    draw,
                    pad=(2, 2, 2, 2),
                    subtitle=f"SECTIONS 1:{scale:g}",
                    key=f"columns:{n}",
                )
            )
    return specs


def _storey(level: Level, below: Level | None) -> str:
    return f"{below.name} - {level.name}" if below else level.name


# ─────────────────────────────────── beam elevations ───────────────────────────────────


def _lanes(bars: list[BeamBar]) -> dict[int, int]:
    """A lane per bar (0 = on the face line, 1, 2 ... inward) so that bars of a face that
    overlap along the beam are drawn apart: longest first."""
    lanes: dict[int, int] = {}
    taken: list[list[tuple[float, float]]] = []
    for i in sorted(range(len(bars)), key=lambda i: -(bars[i].end - bars[i].start)):
        b = bars[i]
        for lane, spans in enumerate(taken):
            if all(b.end <= s - 1 or b.start >= e + 1 for s, e in spans):
                spans.append((b.start, b.end))
                lanes[i] = lane
                break
        else:
            taken.append([(b.start, b.end)])
            lanes[i] = len(taken) - 1
    return lanes


def beam_elevation(
    beam: BeamDetail, scale: float = 50, section_scale: float = 25, stub: float = 500.0
) -> ViewSpec:
    """The elevation of a beam line with its bars (marks, extents), links (zones), spans and
    its sections at ``1:section_scale``."""
    E, S = scale, section_scale
    starts = [s.start for s in beam.supports] + [b.start for b in beam.bars] + [0.0]
    ends = [s.end for s in beam.supports] + [b.end for b in beam.bars] + [beam.length]
    xmin, xmax = min(starts) - 150, max(ends) + 150
    top_bars = [b for b in beam.bars if b.face == "top"]
    bottom_bars = [b for b in beam.bars if b.face != "top"]
    top_lanes, bottom_lanes = _lanes(top_bars), _lanes(bottom_bars)
    n_top = max(top_lanes.values(), default=-1) + 1
    n_bottom = max(bottom_lanes.values(), default=-1) + 1
    full = (
        min((s.start for s in beam.supports), default=0.0),
        max((s.end for s in beam.supports), default=beam.length),
    )

    def curtailed(b: BeamBar) -> bool:
        return b.start > full[0] + 1 or b.end < full[1] - 1

    top_dims = sorted({top_lanes[i] for i, b in enumerate(top_bars) if curtailed(b)})
    bottom_dims = sorted({bottom_lanes[i] for i, b in enumerate(bottom_bars) if curtailed(b)})
    above = 12 + 7 * len(top_dims) + 8 * max(n_top, 1)
    below = 10 + 7 * (len(bottom_dims) + 2) + 8 * max(n_bottom, 1)
    elev_h = (beam.depth + 2 * stub) / E
    sec_w = beam.width / S + 30
    sections_h = (beam.depth / S + 40) if beam.sections else 0.0
    width = max((xmax - xmin) / E + 16, len(beam.sections) * sec_w + 10)
    marks = [m.strip() for m in beam.mark.split(",") if m.strip()]
    applies = ""
    if len(marks) > 3:  # identical beams of many floors: all their marks above the elevation
        applies = _wrap("BEAMS " + ", ".join(marks), width - 16, TEXT, 8)
        above += LINE * len(applies.split("\n")) + 2
    height = above + elev_h + below + sections_h

    def draw(view: View) -> None:
        if applies:
            view.text(applies, (8, height - 1), TEXT, "TL")
        top_y = height - above - stub / E  # paper y of the beam's top
        el = view.inset(8, top_y, E, origin=(xmin, 0))
        _elevation(
            el,
            beam,
            top_bars,
            bottom_bars,
            top_lanes,
            bottom_lanes,
            top_dims,
            bottom_dims,
            stub,
            curtailed,
        )
        for n, (name, x) in enumerate(beam.sections):
            cx = 8 + n * sec_w + sec_w / 2
            cy = sections_h - 8
            sec = view.inset(cx, cy, S)
            bars_t = [(b.count, b.dia, b.row) for b in beam.bars_at(x) if b.face == "top"]
            bars_b = [(b.count, b.dia, b.row) for b in beam.bars_at(x) if b.face != "top"]
            link = beam.link_at(x)
            beam_section(
                sec,
                (0.0, 0.0),
                beam.width,
                beam.depth,
                beam.cover,
                link.dia if link else 10.0,
                bars_t,
                bars_b,
                link.legs if link else 2,
                beam.slab,
            )
            texts = [f"SECTION {name}-{name}"]
            if link:
                texts.append(link.text)
            view.text("\n".join(texts), (cx, cy - beam.depth / S - 8), TEXT, "TC")

    mark = f"{marks[0]}, {marks[1]} … ({len(marks)} beams)" if applies else beam.mark
    title = f"{mark} ({beam.level})" if beam.level else mark
    return ViewSpec(
        f"Beam {title}",
        1,
        (0, 0, width, height),
        draw,
        pad=(2, 2, 2, 2),
        subtitle=f"{beam.width:g}x{beam.depth:g}   ELEVATION 1:{E:g}, SECTIONS 1:{S:g}",
        key=f"beam:{beam.mark}",
    )


def _elevation(
    el: View,
    beam: BeamDetail,
    top_bars: list[BeamBar],
    bottom_bars: list[BeamBar],
    top_lanes: dict[int, int],
    bottom_lanes: dict[int, int],
    top_dims: list[int],
    bottom_dims: list[int],
    stub: float,
    curtailed,
) -> None:
    d = beam.depth
    supports = sorted(beam.supports, key=lambda s: s.start)
    # concrete: the top, the soffit between supports, the column stubs with break lines
    x_first = supports[0].start if supports else 0.0
    x_last = supports[-1].end if supports else beam.length
    el.line((x_first, 0), (x_last, 0), "S-BEAM-EDGE")
    if beam.slab:
        el.line((x_first, -beam.slab), (x_last, -beam.slab), "S-BEAM-EDGE", linetype="DASHED")
    faces = [x_first, *[v for s in supports for v in (s.start, s.end)][1:-1], x_last]
    soffit = list(zip(faces[::2], faces[1::2])) if supports else [(0.0, beam.length)]
    if supports:
        soffit = [(supports[i].end, supports[i + 1].start) for i in range(len(supports) - 1)]
    for a, b in soffit:
        el.line((a, -d), (b, -d), "S-BEAM-EDGE")
    for s in supports:
        for x in (s.start, s.end):
            el.line((x, stub), (x, 0), "S-BEAM-EDGE")
            el.line((x, -d), (x, -d - stub), "S-BEAM-EDGE")
        for y in (stub, -d - stub):
            w = s.end - s.start
            zig = [
                (s.start - 50, y),
                (s.start + w * 0.4, y),
                (s.start + w * 0.5, y + 60),
                (s.start + w * 0.55, y - 60),
                (s.start + w * 0.65, y),
                (s.end + 50, y),
            ]
            el.polyline(zig, "S-BEAM-EDGE", lineweight=18)
    # links
    for z in beam.links:
        n = z.count
        for i in range(n):
            x = z.start + i * z.spacing
            el.line((x, -beam.cover), (x, -(d - beam.cover)), "S-REBAR-LINK")
    # bars
    lane_gap = el.real(1.4)
    jobs: list[tuple[str, tuple[float, float], list]] = []
    for bars, lanes, top in ((top_bars, top_lanes, True), (bottom_bars, bottom_lanes, False)):
        for i, b in enumerate(bars):
            base = beam.cover + 10 + b.dia / 2 + (b.row - 1) * (b.dia + 25) + lanes[i] * lane_gap
            y = -base if top else -(d - base)
            leg = -1 if top else 1
            pts = [
                (b.start, y + leg * b.leg_start),
                (b.start, y),
                (b.end, y),
                (b.end, y + leg * b.leg_end),
            ]
            if not b.leg_start:
                pts = pts[1:]
            if not b.leg_end:
                pts = pts[:-1]
            entity = el.polyline(pts, "S-REBAR-MAIN")
            values = {"mark": b.mark, "dia": f"{b.dia:g}", "count": b.count}
            # the cutting length: as the BBS lists it, else as the detailing model gives it
            cut = b.bbs_length if b.bbs_length is not None else b.cut_length
            if cut is not None:
                values["length"] = f"{cut:.0f}"
            if b.cut_length is not None:
                values["modelLength"] = f"{b.cut_length:.1f}"
            values["drawn"] = f"{b.length:.0f}"  # the run and legs drawn (outside dimensions)
            tag(entity, **values)
            # the bar's ends
            for x in (b.start, b.end):
                el.line((x, y - el.real(0.6)), (x, y + el.real(0.6)), "S-REBAR-MAIN")
            mid = ((b.start + b.end) / 2, y)
            text = f"{b.mark} {b.text}" + (f" {b.note}" if b.note else "")
            reach = (base if top else d - base) / el.scale
            first = 4 + reach if top else -(4 + reach)
            cands = [
                (0, first + s * 5 * (1 if top else -1), "BC" if top else "TC") for s in range(6)
            ]
            cands += [(dx, c[1], c[2]) for dx in (-25, 25, -50, 50) for c in cands[:3]]
            jobs.append((text, mid, cands))
    # dimensions: curtailed bars, then link zones, then spans; a bar's dimension text is kept
    # off the extension lines of the dimensions beside it (the support faces, zone ends)
    lines_x = sorted(
        {v for s in supports for v in (s.start, s.end)}
        | {v for z in beam.links for v in (z.start, z.end)}
        | {v for b in beam.bars if curtailed(b) for v in (b.start, b.end)}
    )

    def text_at(b: BeamBar) -> float:
        half = el.real(text_width(f"{b.end - b.start:.0f}", TEXT) / 2 + 1.2)
        mid = (b.start + b.end) / 2
        lo, hi = b.start + half, b.end - half
        if hi < lo:
            return mid
        options = [mid] + [x + s * half for x in lines_x for s in (-1, 1)]
        options = [x for x in options if lo <= x <= hi]
        clear = [x for x in options if all(abs(x - v) >= half - 1e-6 for v in lines_x)]
        return min(clear, key=lambda x: abs(x - mid)) if clear else mid

    top_offset = 12 + 8 * max(len({*top_lanes.values()}), 1)
    for k, lane in enumerate(top_dims):
        for i, b in enumerate(top_bars):
            if top_lanes[i] == lane and curtailed(b):
                el.dim((b.start, 0), (b.end, 0), top_offset + 7 * k - 6, along=text_at(b))
    bottom_offset = 8 + 8 * max(len({*bottom_lanes.values()}), 1)
    row = 0
    for row, lane in enumerate(bottom_dims):
        for i, b in enumerate(bottom_bars):
            if bottom_lanes[i] == lane and curtailed(b):
                el.dim((b.start, -d), (b.end, -d), -(bottom_offset + 7 * row), along=text_at(b))
    base = bottom_offset + 7 * (len(bottom_dims))
    # link zones: a text that would run into the one before it (short zones side by side, the
    # closer hoops over laps) drops to the row below
    rows_end = [-math.inf, -math.inf]
    zone_rows = 1
    for z in beam.links:
        text = f"{z.end - z.start:.0f} {z.text}"
        half = el.real(text_width(text, TEXT) / 2 + 1.0)
        mid = (z.start + z.end) / 2
        row = 0 if mid - half >= rows_end[0] else 1
        rows_end[row] = mid + half
        zone_rows = max(zone_rows, row + 1)
        el.dim((z.start, -d), (z.end, -d), -(base + 7 * row), text=f"<> {z.text}")
    if supports:
        points = sorted({v for s in supports for v in (s.start, s.end)})
        el.chain([(x, -d) for x in points], -(base + 7 * zone_rows))
    # the labels last, clear of the beam, the column stubs and the dimension texts
    el.reserve([(x_first, -d), (x_last, 0)])
    for s in supports:
        el.reserve([(s.start, -d - stub), (s.end, stub)])
    for s in supports:
        if s.label:
            el.label(s.label, (s.centre, -d - stub), [(0, -2, "TC"), (0, -6, "TC")])
    for text, mid, cands in jobs:
        el.label(text, mid, cands, leader=True)


# ─────────────────────────────────── helpers ───────────────────────────────────


def ceil_to(value: float, step: float) -> float:
    return math.ceil(value / step) * step

"""Cross-sections of reinforced concrete members: the concrete, the links or ties at their
cover, the bars at their positions (filled circles), and dimensions.

Bar positions: a bar's centre is ``cover + link + d / 2`` from each face it is next to; bars of a
face are spread evenly between the corner bars; a second layer of beam bars is a bar diameter
but at least 25 mm clear inside the first (the drawing's assumption, the detailing model may say
otherwise).
"""

from __future__ import annotations

import math

from saengine.drawings.sheets.layout import TEXT, View
from saengine.drawings.sheets.model import ColumnSection

Point = tuple[float, float]


def _rounded_rect(x0: float, y0: float, x1: float, y1: float, r: float, n: int = 4) -> list[Point]:
    """A rectangle with corners rounded to ``r`` (a link with its bends)."""
    r = max(min(r, (x1 - x0) / 2, (y1 - y0) / 2), 0)
    pts: list[Point] = []
    for cx, cy, a0 in (
        (x1 - r, y0 + r, -90),
        (x1 - r, y1 - r, 0),
        (x0 + r, y1 - r, 90),
        (x0 + r, y0 + r, 180),
    ):
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def perimeter_positions(b: float, h: float, inset: float, count: int) -> list[Point]:
    """``count`` bar centres around a b x h rectangle (centred on 0, 0), ``inset`` from the
    faces: the four corners, then the rest spread over the faces by their lengths."""
    x, y = b / 2 - inset, h / 2 - inset
    if count <= 1:
        return [(0.0, 0.0)]
    corners = [(-x, -y), (x, -y), (x, y), (-x, y)]
    if count < 4:
        return corners[:count]
    rest = count - 4
    per_b = round(rest * x / (2 * (x + y)))
    per_h = (rest - 2 * per_b) // 2
    extra = rest - 2 * per_b - 2 * per_h  # 0 or 1: on the top face
    pts = list(corners)

    def spread(a: Point, c: Point, n: int) -> list[Point]:
        return [
            (a[0] + (c[0] - a[0]) * i / (n + 1), a[1] + (c[1] - a[1]) * i / (n + 1))
            for i in range(1, n + 1)
        ]

    pts += spread(corners[0], corners[1], per_b)
    pts += spread(corners[3], corners[2], per_b + extra)
    pts += spread(corners[1], corners[2], per_h)
    pts += spread(corners[0], corners[3], per_h)
    return pts


def column_section(view: View, centre: Point, section: ColumnSection, dims: bool = True) -> None:
    """The section of a column at ``centre`` (real mm of ``view``)."""
    cx, cy = centre
    b, h = section.b, section.h
    dias = sorted((d for n, d in section.bars for _ in range(n)), reverse=True)
    big = dias[0] if dias else 16.0
    tie = section.tie_dia
    if section.round:
        r = b / 2
        view.circle(centre, r, "S-CONC")
        view.circle(centre, r - section.cover - tie / 2, "S-REBAR-LINK")
        n = len(dias)
        rr = r - section.cover - tie - big / 2
        for i, d in enumerate(dias):
            a = 2 * math.pi * i / max(n, 1) + math.pi / 2
            view.dot((cx + rr * math.cos(a), cy + rr * math.sin(a)), d / 2)
        if dims:
            view.dim((cx - r, cy - r), (cx + r, cy - r), -5, text=f"Ø{b:g}")
        return
    view.rect(cx - b / 2, cy - h / 2, cx + b / 2, cy + h / 2, "S-CONC")
    c = section.cover + tie / 2
    hoop = _rounded_rect(cx - b / 2 + c, cy - h / 2 + c, cx + b / 2 - c, cy + h / 2 - c, 2 * tie)
    view.polyline(hoop, "S-REBAR-LINK", close=True)
    inset = section.cover + tie + big / 2
    pts = perimeter_positions(b, h, inset, len(dias))
    for (px, py), d in zip(pts, dias):
        view.dot((cx + px, cy + py), d / 2)
    # cross-ties at interior bars of the faces
    top = sorted(
        px for px, py in pts if abs(py - (h / 2 - inset)) < 1 and abs(px) < b / 2 - inset - 1
    )
    side = sorted(
        py for px, py in pts if abs(px - (b / 2 - inset)) < 1 and abs(py) < h / 2 - inset - 1
    )
    for xs, legs, vertical in ((top, section.legs_y, True), (side, section.legs_x, False)):
        extra = max(legs - 2, 0)
        if not xs or not extra:
            continue
        chosen = [xs[round(i * (len(xs) - 1) / max(extra - 1, 1))] for i in range(extra)]
        for v in sorted(set(chosen)):
            if vertical:
                view.line((cx + v, cy - h / 2 + c), (cx + v, cy + h / 2 - c), "S-REBAR-LINK")
            else:
                view.line((cx - b / 2 + c, cy + v), (cx + b / 2 - c, cy + v), "S-REBAR-LINK")
    if dims:
        view.dim((cx - b / 2, cy - h / 2), (cx + b / 2, cy - h / 2), -4)
        view.dim((cx - b / 2, cy - h / 2), (cx - b / 2, cy + h / 2), 4, angle=90)


def beam_section(
    view: View,
    centre: Point,
    width: float,
    depth: float,
    cover: float,
    link: float,
    top: list[tuple[int, float, int]],
    bottom: list[tuple[int, float, int]],
    legs: int = 2,
    slab: float = 0.0,
) -> None:
    """A beam section with its top at ``centre[1]`` and centred on ``centre[0]``: ``top`` and
    ``bottom`` bars as (count, dia, row)."""
    cx, ty = centre
    x0, x1, y0 = cx - width / 2, cx + width / 2, ty - depth
    if slab > 0:
        wing = min(width * 0.8, 400)
        view.polyline(
            [
                (x0 - wing, ty - slab),
                (x0, ty - slab),
                (x0, y0),
                (x1, y0),
                (x1, ty - slab),
                (x1 + wing, ty - slab),
            ],
            "S-CONC",
        )
        view.line((x0 - wing, ty), (x1 + wing, ty), "S-CONC")
        for x in (x0 - wing, x1 + wing):
            view.line((x, ty), (x, ty - slab), "S-CONC", linetype="DASHED")
    else:
        view.rect(x0, y0, x1, ty, "S-CONC")
    c = cover + link / 2
    view.polyline(
        _rounded_rect(x0 + c, y0 + c, x1 - c, ty - c, 2 * link), "S-REBAR-LINK", close=True
    )
    inner = max(legs - 2, 0)
    for i in range(inner):
        x = x0 + c + (width - 2 * c) * (i + 1) / (inner + 1)
        view.line((x, y0 + c), (x, ty - c), "S-REBAR-LINK")
    for groups, sign, base in ((top, -1, ty), (bottom, 1, y0)):
        rows: dict[int, list[float]] = {}
        for n, d, row in groups:
            rows.setdefault(row, []).extend([d] * n)
        offset = cover + link
        for row in sorted(rows):
            dias = sorted(rows[row], reverse=True)
            d_max = dias[0]
            y = base + sign * (offset + d_max / 2)
            xa, xb = x0 + cover + link + d_max / 2, x1 - cover - link - d_max / 2
            n = len(dias)
            order = _corner_first(n)
            for i, d in zip(order, dias):
                x = (xa + xb) / 2 if n == 1 else xa + (xb - xa) * i / (n - 1)
                view.dot((x, y), d / 2)
            offset += d_max + max(d_max, 25)
    view.dim((x0, y0), (x1, y0), -4)
    view.dim((x0, y0), (x0, ty), 4, angle=90)


def _corner_first(n: int) -> list[int]:
    """Positions 0..n-1 with the corners first (the largest bars go to the corners)."""
    if n <= 2:
        return list(range(n))
    return [0, n - 1, *range(1, n - 1)]


def section_text(view: View, at: Point, lines: list[str]) -> None:
    """Lines of text centred under ``at`` (real point), each on its own line."""
    view.text("\n".join(lines), at, TEXT, "TC")

"""Plans: the framing (general arrangement) plan of a level, the foundation plan and the slab
reinforcement plan, as views for :func:`saengine.drawings.sheets.layout.pack`.

Conventions: grids are centre lines with bubbles on all four sides and chain dimensions (grid to
grid, then overall) below and left of the plan; columns and walls cut below the level are
hatched, columns that start at the level are outlined; beams under the slab are hidden lines with
their mark and size; slabs carry their mark and thickness; openings are crossed.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from saengine.drawings.sheets.layout import TEXT, TEXT_LARGE, View, ViewSpec, tag
from saengine.drawings.sheets.model import (
    Building,
    Level,
    Point,
    SlabDetail,
    TopBar,
)

EPS = 1.0  # mm
EXTEND = 6.0  # paper mm the grid lines run past the structure
BUBBLE = 4.5  # paper mm radius of a grid bubble
DIM_1 = 2 * BUBBLE + EXTEND + 6  # paper mm from the structure to the first dimension line
DIM_2 = DIM_1 + 8


def _bounds(points: Iterable[Point]) -> tuple[float, float, float, float]:
    pts = list(points)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _level_points(building: Building, level: Level) -> list[Point]:
    z = level.elevation
    pts: list[Point] = []
    pts += [(g.position, y.position) for g in building.grids_x for y in building.grids_y[:1]]
    pts += [(x.position, g.position) for g in building.grids_y for x in building.grids_x[:1]]
    for c in building.columns:
        if c.bottom < z + EPS and c.top > z - EPS:
            pts += c.outline()
    for b in building.beams:
        if abs(b.elevation - z) < EPS:
            pts += [b.start, b.end]
    for s in building.slabs:
        if abs(s.elevation - z) < EPS:
            pts += s.boundary
    for w in building.walls:
        if w.bottom < z + EPS and w.top > z - EPS:
            pts += [w.start, w.end]
    return pts or [(0.0, 0.0), (1000.0, 1000.0)]


def _pad() -> tuple[float, float, float, float]:
    return (DIM_2 + 6, DIM_2 + 6, 2 * BUBBLE + EXTEND + 3, 2 * BUBBLE + EXTEND + 3)


def grids(view: View, building: Building, bbox: tuple[float, float, float, float]) -> int:
    """Grid lines, bubbles and chain dimensions; the number of dimensions drawn."""
    x0, y0, x1, y1 = bbox
    e = view.real(EXTEND)
    r = view.real(BUBBLE)
    dims = 0
    for g in building.grids_x:
        a, b = (g.position, y0 - e), (g.position, y1 + e)
        view.line(a, b, "S-GRID")
        for c in ((g.position, y0 - e - r), (g.position, y1 + e + r)):
            view.circle(c, r, "S-GRID-BUBBLE")
            view.reserve([(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)])
            view.text(g.label, c, TEXT_LARGE, "MC", "S-GRID-BUBBLE")
    for g in building.grids_y:
        a, b = (x0 - e, g.position), (x1 + e, g.position)
        view.line(a, b, "S-GRID")
        for c in ((x0 - e - r, g.position), (x1 + e + r, g.position)):
            view.circle(c, r, "S-GRID-BUBBLE")
            view.reserve([(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)])
            view.text(g.label, c, TEXT_LARGE, "MC", "S-GRID-BUBBLE")
    xs = sorted({g.position for g in building.grids_x})
    ys = sorted({g.position for g in building.grids_y})
    if len(xs) > 1:
        view.chain([(x, y0) for x in xs], -DIM_1)
        dims += len(xs) - 1
        if len(xs) > 2:
            view.dim((xs[0], y0), (xs[-1], y0), -DIM_2)
            dims += 1
    if len(ys) > 1:
        view.chain([(x0, y) for y in ys], DIM_1, angle=90)
        dims += len(ys) - 1
        if len(ys) > 2:
            view.dim((x0, ys[0]), (x0, ys[-1]), DIM_2, angle=90)
            dims += 1
    return dims


def _centroid(points: list[Point]) -> Point:
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-9:
        return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))
    return (cx / (3 * a), cy / (3 * a))


def _inside_label(view: View, text: str, boundary: list[Point]) -> None:
    """``text`` inside the polygon's box: near its centroid where it is free."""
    c = _centroid(boundary)
    x0, y0, x1, y1 = _bounds(boundary)
    cx, cy = view.p(*c)
    cands = []
    n = 32
    for i in range(1, n):
        for j in range(1, n):
            px, py = view.p(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * j / n)
            cands.append((px - cx, py - cy, "MC"))
    cands.sort(key=lambda d: d[0] ** 2 + d[1] ** 2)
    # inside the panel, without a leader: on its lines, or on one line; else further out
    for variant in (text, text.replace("\n", " ")):
        if view.label(variant, c, [(0, 0, "MC"), *cands], TEXT, rings=False, force=False):
            return
    view.label(text, c, [(0, 0, "MC"), *cands], TEXT)


def _angle(a: Point, b: Point) -> float:
    angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    if angle > 90 + 1e-6:
        angle -= 180
    elif angle <= -90 + 1e-6:
        angle += 180
    return angle


def _along_label(view: View, text: str, a: Point, b: Point, offset: float) -> None:
    """``text`` parallel to the line a-b, ``offset`` paper mm beside it, where it is free."""
    angle = _angle(a, b)
    rad = math.radians(angle)
    normal = (-math.sin(rad), math.cos(rad))
    candidates = []
    cx, cy = view.p(a[0] + (b[0] - a[0]) * 0.5, a[1] + (b[1] - a[1]) * 0.5)
    for extra in (0.0, 3.5, 7.0):
        for t in (0.5, 0.3, 0.7, 0.2, 0.8, 0.4, 0.6, 0.1, 0.9):
            for side in (1, -1):
                px = a[0] + (b[0] - a[0]) * t
                py = a[1] + (b[1] - a[1]) * t
                mx, my = view.p(px, py)
                d = side * (offset + extra)
                candidates.append((mx - cx + normal[0] * d, my - cy + normal[1] * d, "MC"))
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    # beside the line on one line, else on two (the mark, then the rest), else further out
    two = text.replace(" ", "\n", 1) if " " in text else text
    for variant in (text, two):
        if view.label(variant, mid, candidates, TEXT, "MC", angle, rings=False, force=False):
            return
    for variant in (text, two):
        if view.label(variant, mid, candidates, TEXT, "MC", angle, force=False):
            return
    for variant in (text, two):  # horizontal, with a leader
        if view.label(variant, mid, candidates[:1], TEXT, "MC", 0, force=False):
            return
    view.label(text, mid, candidates, TEXT, "MC", rotation=angle)


def _columns(view: View, building: Building, z: float) -> None:
    for c in building.columns:
        if not (c.bottom < z + EPS and c.top > z - EPS):
            continue
        outline = c.outline()
        below = c.bottom < z - EPS
        view.polyline(outline, "S-COLS", close=True)
        view.reserve(outline, 0.3)
        if below:
            view.hatch(outline)


def _column_marks(view: View, building: Building, z: float) -> None:
    for c in building.columns:
        if not (c.bottom < z + EPS and c.top > z - EPS):
            continue
        half = max(c.b, c.h) / 2 / view.scale + 1.2
        view.label(
            c.mark,
            (c.x, c.y),
            [
                (half, half, "BL"),
                (-half, half, "BR"),
                (half, -half, "TL"),
                (-half, -half, "TR"),
            ],
        )


def _walls(view: View, building: Building, z: float, hatch: bool = True) -> None:
    for w in building.walls:
        if not (w.bottom < z + EPS and w.top > z - EPS):
            continue
        dx, dy = w.end[0] - w.start[0], w.end[1] - w.start[1]
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length * w.thickness / 2, dx / length * w.thickness / 2
        outline = [
            (w.start[0] + nx, w.start[1] + ny),
            (w.end[0] + nx, w.end[1] + ny),
            (w.end[0] - nx, w.end[1] - ny),
            (w.start[0] - nx, w.start[1] - ny),
        ]
        view.polyline(outline, "S-WALL", close=True)
        if hatch and w.bottom < z - EPS:
            view.hatch(outline)


def _wall_marks(view: View, building: Building, z: float) -> None:
    for w in building.walls:
        if not (w.bottom < z + EPS and w.top > z - EPS):
            continue
        offset = w.thickness / 2 / view.scale + 2.2
        _along_label(view, f"{w.mark} ({w.thickness:g} THK)", w.start, w.end, offset)


def _beam_edges(view: View, building: Building, z: float, layer: str) -> list:
    beams = [b for b in building.beams if abs(b.elevation - z) < EPS]
    for b in beams:
        dx, dy = b.end[0] - b.start[0], b.end[1] - b.start[1]
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length * b.width / 2, dx / length * b.width / 2
        view.line((b.start[0] + nx, b.start[1] + ny), (b.end[0] + nx, b.end[1] + ny), layer)
        view.line((b.start[0] - nx, b.start[1] - ny), (b.end[0] - nx, b.end[1] - ny), layer)
        if abs(dx) < 1 or abs(dy) < 1:  # an axis-aligned beam: keep the labels off it
            view.reserve([(b.start[0] + nx, b.start[1] + ny), (b.end[0] - nx, b.end[1] - ny)])
    return beams


def framing_plan(building: Building, level: Level, scale: float = 100) -> ViewSpec:
    """The framing plan of ``level``: what is drawn at its elevation, looking down."""
    bbox = _bounds(_level_points(building, level))

    def draw(view: View) -> None:
        z = level.elevation
        # the linework first, then the labels clear of it
        grids(view, building, bbox)
        _columns(view, building, z)
        _walls(view, building, z)
        for s in (s for s in building.slabs if abs(s.elevation - z) < EPS):
            view.polyline(s.boundary, "S-SLAB", close=True)
        beams = _beam_edges(view, building, z, "S-BEAM")
        for s in (s for s in building.slabs if abs(s.elevation - z) < EPS):
            for hole in s.openings:
                view.polyline(hole, "S-OPEN", close=True)
                view.line(hole[0], hole[2], "S-OPEN")
                view.line(hole[1], hole[3], "S-OPEN")
        stairs = [st for st in building.stairs if abs(st.base - z) < EPS or abs(st.top - z) < EPS]
        for st in stairs:
            _stair(view, st)
        _column_marks(view, building, z)
        _wall_marks(view, building, z)
        for b in beams:
            offset = b.width / 2 / view.scale + 2.2
            _along_label(view, f"{b.mark} {b.width:g}x{b.depth:g}", b.start, b.end, offset)
        for st in stairs:
            _stair_mark(view, st, up=abs(st.base - z) < EPS)
        for s in (s for s in building.slabs if abs(s.elevation - z) < EPS):
            for hole in s.openings:
                view.reserve(hole)
        for s in (s for s in building.slabs if abs(s.elevation - z) < EPS):
            _inside_label(view, f"{s.mark}\n{s.thickness:g} THK", s.boundary)

    return ViewSpec(
        title=f"Framing plan - {level.name}",
        scale=scale,
        bbox=bbox,
        draw=draw,
        pad=_pad(),
        subtitle=f"SCALE 1:{scale:g}   TOP OF SLAB +{level.elevation / 1000:.3f}",
        key=f"plan:{level.id}",
    )


def _stair(view: View, stair) -> None:
    for outline in stair.flights:
        view.polyline(outline, "S-STAIR", close=True)
    for outline in stair.landings:
        view.polyline(outline, "S-STAIR", close=True)
    for a, b in stair.treads:
        view.line(a, b, "S-STAIR")
    if len(stair.arrow) >= 2:
        view.polyline(stair.arrow, "S-STAIR")
        tip, before = stair.arrow[-1], stair.arrow[-2]
        ang = math.atan2(tip[1] - before[1], tip[0] - before[0])
        s = view.real(2.5)
        for side in (1, -1):
            a = ang + math.pi + side * math.radians(25)
            view.line(tip, (tip[0] + s * math.cos(a), tip[1] + s * math.sin(a)), "S-STAIR")
    for outline in (*stair.flights, *stair.landings):
        view.reserve(outline)


def _stair_mark(view: View, stair, up: bool) -> None:
    if not stair.arrow:
        return
    # the leader points at the walking line a little inside the foot (not along its edge)
    (x0, y0), (x1, y1) = stair.arrow[0], stair.arrow[1]
    length = math.hypot(x1 - x0, y1 - y0) or 1.0
    step = min(view.real(2.0), length / 3)
    anchor = (x0 + (x1 - x0) / length * step, y0 + (y1 - y0) / length * step)
    bx0, by0, bx1, by1 = _bounds([p for o in (*stair.flights, *stair.landings) for p in o])
    ax, ay = view.p(*anchor)
    left, right = view.p(bx0, anchor[1])[0], view.p(bx1, anchor[1])[0]
    bottom, top = view.p(anchor[0], by0)[1], view.p(anchor[0], by1)[1]
    tries = [
        (left - ax - 2, 0, "MR"),
        (right - ax + 2, 0, "ML"),
        (0, bottom - ay - 2, "TC"),
        (0, top - ay + 2, "BC"),
    ]
    view.label(f"{stair.mark} {'UP' if up else 'DN'}", anchor, tries, leader=True)


def foundation_plan(building: Building, scale: float = 100) -> ViewSpec | None:
    """The foundation plan: footings and pile caps, the columns they carry, the ground walls."""
    if not building.footings:
        return None
    base = (
        min(building.levels, key=lambda lv: lv.elevation) if building.levels else Level("", "", 0)
    )
    pts = _level_points(building, base)
    for f in building.footings:
        pts += f.outline
    bbox = _bounds(pts)

    def draw(view: View) -> None:
        grids(view, building, bbox)
        for f in building.footings:
            view.polyline(f.outline, "S-FNDN", close=True)
            for centre, dia in f.piles:
                view.circle(centre, dia / 2, "S-FNDN")
        z = base.elevation + EPS * 2
        for c in building.columns:
            if c.bottom < z and c.top > z:
                outline = c.outline()
                view.polyline(outline, "S-COLS", close=True)
                view.hatch(outline)
                view.reserve(outline, 0.3)
        _walls(view, building, z)
        for f in building.footings:
            xs = [p[0] for p in f.outline]
            ys = [p[1] for p in f.outline]
            corner = (max(xs), min(ys))
            view.label(f.mark, corner, [(1.5, -1.5, "TL"), (1.5, 1.5, "BL")])
        _wall_marks(view, building, z)

    return ViewSpec(
        title="Foundation plan",
        scale=scale,
        bbox=bbox,
        draw=draw,
        pad=_pad(),
        key="plan:foundation",
    )


def pile_grid(view: View, building: Building, bbox: tuple[float, float, float, float]) -> None:
    """The pile grid: centre lines across the plan with their labels in bubbles beyond the
    building grid's (x lines at the bottom, y lines at the right; on its own layer), and the chain
    of its spacings."""
    g = building.pile_grid
    if g is None:
        return
    x0, y0, x1, y1 = bbox
    # The bubbles go past the building grid's bubbles and chain dimensions (x lines, at the
    # bottom) and past the pile grid's own chain (y lines, at the right).
    e = view.real(EXTEND)
    e_x = view.real(DIM_2 + 8)
    e_y = view.real(DIM_1 + 8)
    r = view.real(BUBBLE * 0.8)
    a = math.radians(g.rotation)
    ux, uy = math.cos(a), math.sin(a)
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    # The local extent of the plan, so that the lines cross all of it.
    local = [
        ((px - g.origin[0]) * ux + (py - g.origin[1]) * uy,
         -(px - g.origin[0]) * uy + (py - g.origin[1]) * ux)
        for px, py in corners
    ]  # fmt: skip
    lo_u, hi_u = min(p[0] for p in local) - e, max(p[0] for p in local) + e_y
    lo_v, hi_v = min(p[1] for p in local) - e_x, max(p[1] for p in local) + e
    for line in g.x:
        ends = [g.point(line.position, lo_v), g.point(line.position, hi_v)]
        view.line(ends[0], ends[1], "S-PILE-GRID")
        for end, sign in ((ends[0], -1),):
            c = (end[0] - sign * uy * r, end[1] + sign * ux * r)
            view.circle(c, r, "S-PILE-GRID")
            view.reserve([(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)])
            view.text(line.label, c, TEXT, "MC", "S-PILE-GRID")
    for line in g.y:
        ends = [g.point(lo_u, line.position), g.point(hi_u, line.position)]
        view.line(ends[0], ends[1], "S-PILE-GRID")
        for end, sign in ((ends[1], 1),):
            c = (end[0] + sign * ux * r, end[1] + sign * uy * r)
            view.circle(c, r, "S-PILE-GRID")
            view.reserve([(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)])
            view.text(line.label, c, TEXT, "MC", "S-PILE-GRID")
    if abs(g.rotation) < 1e-6:
        xs = sorted({g.origin[0] + line.position for line in g.x})
        ys = sorted({g.origin[1] + line.position for line in g.y})
        if len(xs) > 1:
            view.chain([(x, y1) for x in xs], DIM_1)
        if len(ys) > 1:
            view.chain([(x1, y) for y in ys], -DIM_1, angle=90)


def pile_layout_plan(building: Building, scale: float = 100) -> ViewSpec | None:
    """The pile layout plan: the pile grid (its own setting-out, independent of the building's
    grid), every pile with its mark and diameter, the pile caps' outlines and the columns."""
    if not building.piles:
        return None
    pts: list[Point] = []
    for p in building.piles:
        r = p.diameter / 2
        pts += [(p.centre[0] - r, p.centre[1] - r), (p.centre[0] + r, p.centre[1] + r)]
    for f in building.footings:
        if f.piles:
            pts += f.outline
    base = (
        min(building.levels, key=lambda lv: lv.elevation) if building.levels else Level("", "", 0)
    )
    pts += _level_points(building, base)
    bbox = _bounds(pts)

    def draw(view: View) -> None:
        grids(view, building, bbox)
        pile_grid(view, building, bbox)
        for f in building.footings:
            if f.piles:
                view.polyline(f.outline, "S-FNDN", close=True)
        z = base.elevation + EPS * 2
        for c in building.columns:
            if c.bottom < z and c.top > z:
                view.polyline(c.outline(), "S-COLS", close=True)
        for p in building.piles:
            view.circle(p.centre, p.diameter / 2, "S-PILE")
            arm = p.diameter / 2 + view.real(1.0)
            view.line((p.centre[0] - arm, p.centre[1]), (p.centre[0] + arm, p.centre[1]), "S-PILE")
            view.line((p.centre[0], p.centre[1] - arm), (p.centre[0], p.centre[1] + arm), "S-PILE")
            view.reserve(
                [
                    (p.centre[0] - p.diameter / 2, p.centre[1] - p.diameter / 2),
                    (p.centre[0] + p.diameter / 2, p.centre[1] + p.diameter / 2),
                ]
            )
        for p in building.piles:
            view.label(p.mark, p.centre, [(2.5, 2.5, "BL"), (-2.5, 2.5, "BR"), (2.5, -2.5, "TL")])
        for f in building.footings:
            if f.piles:
                xs = [q[0] for q in f.outline]
                ys = [q[1] for q in f.outline]
                view.label(f.mark, (min(xs), max(ys)), [(-1.5, 1.5, "BR"), (1.5, 1.5, "BL")])

    return ViewSpec(
        title="Pile layout plan",
        scale=scale,
        bbox=bbox,
        draw=draw,
        pad=tuple(v + 2 * BUBBLE + 14 for v in _pad()),
        key="plan:piles",
    )


def clear_pieces(
    a: Point, b: Point, holes: list[tuple[float, float, float, float]]
) -> list[tuple[Point, Point]]:
    """The parts of the axis-parallel bar line a-b outside the opening boxes ``holes`` (the
    bars stop at an opening: the line is drawn broken there)."""
    x_dir = abs(b[0] - a[0]) >= abs(b[1] - a[1])
    k = 0 if x_dir else 1
    lo, hi = sorted((a[k], b[k]))
    across = a[1 - k]
    cuts: list[tuple[float, float]] = []
    for h in holes:
        if h[1 - k] < across < h[3 - k] and h[k] < hi and h[2 + k] > lo:
            cuts.append((max(h[k], lo), min(h[2 + k], hi)))
    if not cuts:
        return [(a, b)]
    runs, start = [], lo
    for c0, c1 in sorted(cuts):
        if c0 > start + EPS:
            runs.append((start, c0))
        start = max(start, c1)
    if hi > start + EPS:
        runs.append((start, hi))

    def pt(v: float) -> Point:
        return (v, across) if x_dir else (across, v)

    if a[k] > b[k]:  # from a towards b
        return [(pt(r1), pt(r0)) for r0, r1 in reversed(runs)]
    return [(pt(r0), pt(r1)) for r0, r1 in runs]


def _bar_line(
    view: View,
    a: Point,
    b: Point,
    top: bool,
    leg: float = 2.0,
    hooks: tuple[bool, bool] = (True, True),
) -> object:
    """A bar in plan from a to b with its end hooks as short ticks (paper mm); ``hooks``: which
    ends get one (not where the line stops at an opening)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    s = view.real(leg) * (-1 if top else 1)
    pts = [(a[0] + nx * s, a[1] + ny * s), a, b, (b[0] + nx * s, b[1] + ny * s)]
    if not hooks[1]:
        pts = pts[:-1]
    if not hooks[0]:
        pts = pts[1:]
    extra = {"linetype": "DASHED"} if top else {}
    return view.polyline(pts, "S-REBAR-MAIN", lineweight=50, **extra)


def _clip(boundary: list[Point], cover: float) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = _bounds(boundary)
    return (x0 + cover, y0 + cover, x1 - cover, y1 - cover)


def slab_plan(
    building: Building, slabs: list[SlabDetail], level: Level, scale: float = 100
) -> ViewSpec:
    """The slab reinforcement plan of ``level``: per panel the bottom bars in X and Y and the
    top bars over the supports with their extents, each with its mark and spacing."""
    bbox = _bounds(_level_points(building, level))
    mine = [s for s in slabs if s.level == level.id]

    def draw(view: View) -> None:
        z = level.elevation
        grids(view, building, bbox)
        _columns(view, building, z)
        _beam_edges(view, building, z, "S-BEAM-EDGE")
        _walls(view, building, z, hatch=False)
        for s in mine:
            view.polyline(s.boundary, "S-SLAB", close=True)
            for hole in s.openings:
                view.polyline(hole, "S-OPEN", close=True)
                view.line(hole[0], hole[2], "S-OPEN")
                view.line(hole[1], hole[3], "S-OPEN")
                view.reserve(hole)
        labels: list[tuple[str, Point, Point]] = []
        for s in mine:
            labels += _slab_bars(view, s)
        _wall_marks(view, building, z)
        for text, a, b in labels:
            _along_label(view, text, a, b, 2.8)

    return ViewSpec(
        title=f"Slab reinforcement - {level.name}",
        scale=scale,
        bbox=bbox,
        draw=draw,
        pad=_pad(),
        subtitle=f"SCALE 1:{scale:g}   B: BOTTOM, T: TOP (DASHED)",
        key=f"slab:{level.id}",
    )


def slab_runs(s: SlabDetail) -> list[tuple[TopBar, str]]:
    """The bars a slab plan draws: (bar, "B"/"T"); bottom bars from ``bottom_runs`` or, when
    there are none, across the panel inside the cover."""
    runs = [(bar, "B") for bar in s.bottom_runs]
    if not s.bottom_runs:
        x0, y0, x1, y1 = _clip(s.boundary, s.cover)
        cx, cy = _centroid(s.boundary)
        w, h = x1 - x0, y1 - y0
        if s.bottom_x:
            runs.append((TopBar((x0, cy - h * 0.12), (x1, cy - h * 0.12), s.bottom_x), "B"))
        if s.bottom_y:
            runs.append((TopBar((cx + w * 0.12, y0), (cx + w * 0.12, y1), s.bottom_y), "B"))
    runs += [(bar, "T") for bar in s.top_bars]
    return runs


def _slab_bars(view: View, s: SlabDetail) -> list[tuple[str, Point, Point]]:
    """Draws the bars of a panel; returns their labels to place once every bar is drawn."""
    labels = []
    holes = [_bounds(h) for h in s.openings]
    for bar, face in slab_runs(s):
        for piece in clear_pieces(bar.start, bar.end, holes):
            hooks = (math.dist(piece[0], bar.start) < EPS, math.dist(piece[1], bar.end) < EPS)
            entity = _bar_line(view, piece[0], piece[1], top=face == "T", hooks=hooks)
            tag(entity, mark=bar.mesh.mark, face=face)
            view.reserve([piece[0], piece[1]], 0.4)
        horizontal = abs(bar.end[1] - bar.start[1]) < abs(bar.end[0] - bar.start[0])
        axis = "X" if horizontal else "Y"
        mark = f"{bar.mesh.mark} " if bar.mesh.mark else ""
        labels.append((bar.label or f"{mark}{bar.mesh.text} {face} ({axis})", bar.start, bar.end))
    return labels


def default_top_bars(slab: SlabDetail, fraction: float = 0.3) -> list[TopBar]:
    """Top bars over every edge of a rectangular panel, reaching ``fraction`` of the panel's
    span perpendicular to the edge into it (the drawing's default when the detailing model gives
    no extents; it is a drafting default, not a code rule)."""
    x0, y0, x1, y1 = _bounds(slab.boundary)
    lx, ly = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    bars = []
    for mesh, edges in (
        (
            slab.top_x,
            (
                ((x0, cy + ly * 0.2), (x0 + fraction * lx, cy + ly * 0.2)),
                ((x1, cy + ly * 0.2), (x1 - fraction * lx, cy + ly * 0.2)),
            ),
        ),
        (
            slab.top_y,
            (
                ((cx - lx * 0.25, y0), (cx - lx * 0.25, y0 + fraction * ly)),
                ((cx - lx * 0.25, y1), (cx - lx * 0.25, y1 - fraction * ly)),
            ),
        ),
    ):
        if mesh is None:
            continue
        for a, b in edges:
            bars.append(TopBar(a, b, mesh))
    return bars


def level_has_plan(building: Building, level: Level) -> bool:
    z = level.elevation
    return any(abs(b.elevation - z) < EPS for b in building.beams) or any(
        abs(s.elevation - z) < EPS for s in building.slabs
    )


__all__ = [
    "TEXT",
    "default_top_bars",
    "foundation_plan",
    "framing_plan",
    "grids",
    "level_has_plan",
    "pile_layout_plan",
    "slab_plan",
]

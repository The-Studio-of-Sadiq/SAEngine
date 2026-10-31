"""Details: footings and pile caps (plan and section with the mesh and the column starters),
retaining and basement walls (section per metre run with the stem and base bars),
walls (elevation with the web bars, the end zones and the lintels over the openings with their
bar marks, plan section), stairs (section
along a flight with its bars, plan).

The views are laid out in paper millimetres; the drawings are insets at the detail scale.
"""

from __future__ import annotations

import math

from saengine.drawings.sheets.layout import TEXT, View, ViewSpec, tag, text_width
from saengine.drawings.sheets.model import (
    FootingDetail,
    LintelDetail,
    Mesh,
    RetainingWallDetail,
    StairDetail,
    WallDetail,
)

BLINDING = 75.0  # mm of lean concrete under a footing, drawn
COVER_UNDER = 75.0  # mm to the bars under a base cast against earth (BNBC Part 6 Sec 8.1.7.2)


def _bars_label(mesh: Mesh | None, where: str) -> str:
    if mesh is None:
        return ""
    mark = f"{mesh.mark} " if mesh.mark else ""
    return f"{mark}{mesh.text} {where}"


# ─────────────────────────────────── footings ───────────────────────────────────


def _two_lines(mesh: Mesh) -> str:
    return f"{mesh.mark}\n{mesh.text} B" if mesh.mark else f"{mesh.text} B"


def bar_positions(lo: float, hi: float, mesh: Mesh) -> list[float]:
    """Centres of the bars of ``mesh`` spread between ``lo`` and ``hi`` (the outer bars'
    centres): the detailing model's count at its spacing, centred; closed up to the range when
    the count does not fit (the model counts from the cover lines)."""
    span = max(hi - lo, 0.0)
    n = mesh.count if mesh.count else int(span // mesh.spacing + 1e-9) + 1
    n = max(min(n, 400), 1)
    if n == 1:
        return [(lo + hi) / 2]
    step = min(mesh.spacing, span / (n - 1))
    first = lo + (span - (n - 1) * step) / 2
    return [first + i * step for i in range(n)]


def _column_outline(f: FootingDetail) -> list[tuple[float, float]]:
    b, h = f.column or (0.0, 0.0)
    cx, cy = f.column_at
    if f.column_round:
        r = b / 2
        return [
            (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
            for a in range(0, 360, 15)
        ]
    c, s = math.cos(math.radians(f.column_rotation)), math.sin(math.radians(f.column_rotation))
    return [
        (cx + u * b / 2 * c - v * h / 2 * s, cy + u * b / 2 * s + v * h / 2 * c)
        for u, v in ((-1, -1), (1, -1), (1, 1), (-1, 1))
    ]


def footing_detail(f: FootingDetail, scale: float = 25) -> ViewSpec:
    """Plan and section A-A of a footing or pile cap at ``1:scale``. The column stands where
    the model puts it in the footing (offset, rotated); the section cuts through its centre.
    The bars are the detailing model's: the meshes with their counts and spacings, the column
    starters with their foot (length and direction) and their position inside the ties."""
    S = scale
    L, B, T = f.length, f.width, f.thickness
    pile = f.pile_dia or 0.0
    pile_len = 3 * pile if pile else 0.0
    col_h = 600.0
    # the section's labels at its right, on two lines (mark, then bars)
    labels = [_two_lines(m) for m in (f.bottom_x, f.bottom_y) if m]
    label_w = max((text_width(t, TEXT) for x in labels for t in x.split("\n")), default=0.0) + 8
    plan_w, plan_h = L / S + 30, B / S + 34
    sec_h = (T + BLINDING + col_h + pile_len) / S + 30
    sec_x = plan_w + 12  # paper x of the section's left face
    width = max(sec_x + L / S + 12 + label_w, 120)
    height = max(plan_h, sec_h + 18) + 30
    outline = _column_outline(f) if f.column else []
    cx, cy = f.column_at
    half_x = max((abs(p[0] - cx) for p in outline), default=0.0)  # the column's half along x
    c = f.cover
    dx_ = f.bottom_x.dia if f.bottom_x else 0.0
    dy_ = f.bottom_y.dia if f.bottom_y else 0.0

    def draw(view: View) -> None:
        # ── plan ──
        top_gap = 30.0
        p = view.inset(15 + L / S / 2, height - top_gap - B / S / 2, S)
        p.rect(-L / 2, -B / 2, L / 2, B / 2, "S-CONC")
        for x, y in f.piles:
            p.circle((x, y), pile / 2, "S-FNDN")
        x_lines: list[float] = []
        y_lines: list[float] = []
        if f.bottom_x:  # bars along x, spread across y
            x_lines = bar_positions(-B / 2 + c + dx_ / 2, B / 2 - c - dx_ / 2, f.bottom_x)
            for v in x_lines:
                p.line((-L / 2 + c, v), (L / 2 - c, v), "S-REBAR-MAIN", lineweight=18)
        if f.bottom_y:  # bars along y, spread across x
            y_lines = bar_positions(-L / 2 + c + dy_ / 2, L / 2 - c - dy_ / 2, f.bottom_y)
            for u in y_lines:
                p.line((u, -B / 2 + c), (u, B / 2 - c), "S-REBAR-MAIN", lineweight=18)
        if outline:
            p.polyline(outline, "S-COLS", close=True)
            p.hatch(outline)
            p.reserve(outline)
        # the section line through the column's centre
        p.line((-L / 2 - 200, cy), (-L / 2 - 50, cy), "S-TEXT")
        p.text("A", (-L / 2 - 200 - p.real(2.5), cy), TEXT, "MC")
        p.line((L / 2 + 50, cy), (L / 2 + 200, cy), "S-TEXT")
        p.text("A", (L / 2 + 200 + p.real(2.5), cy), TEXT, "MC")
        p.dim((-L / 2, -B / 2), (L / 2, -B / 2), -6)
        p.dim((-L / 2, -B / 2), (-L / 2, B / 2), 14, angle=90)
        if outline and (abs(cx) > 1 or abs(cy) > 1):  # the column's setting out: edge to faces
            xs = sorted({-L / 2, *(round(q[0], 1) for q in outline), L / 2})
            ys = sorted({-B / 2, *(round(q[1], 1) for q in outline), B / 2})
            if abs(cx) > 1:
                p.chain([(x, B / 2) for x in (xs[0], min(xs[1:-1]), max(xs[1:-1]), xs[-1])], 4)
            if abs(cy) > 1:
                p.chain(
                    [(L / 2, y) for y in (ys[0], min(ys[1:-1]), max(ys[1:-1]), ys[-1])],
                    -4,
                    angle=90,
                )
        # the mesh labels above the plan, with leaders to a bar
        above = [B / 2 + p.real(14), B / 2 + p.real(21)]
        if f.bottom_x and x_lines:
            v = min(x_lines, key=lambda y: abs(y + B / 4))
            anchor = (-L / 4, v)
            p.label(
                _bars_label(f.bottom_x, "B (X)"),
                anchor,
                _to(p, anchor, [(-L / 2, above[1], "BL"), (-L / 2, above[0], "BL")]),
                leader=True,
            )
        if f.bottom_y and y_lines:
            u = min(y_lines, key=lambda x: abs(x - L / 4))
            anchor = (u, B / 4)
            p.label(
                _bars_label(f.bottom_y, "B (Y)"),
                anchor,
                _to(p, anchor, [(L / 2, above[0], "BR"), (L / 2, above[1], "BR")]),
                leader=True,
            )
        view.text("PLAN", (15 + L / S / 2, height - top_gap - B / S - 14), TEXT, "TC")
        # ── section A-A ──
        ox = sec_x + L / S / 2
        s = view.inset(ox, 36 + (BLINDING + pile_len) / S, S)
        s.rect(-L / 2, 0, L / 2, T, "S-CONC")
        s.rect(-L / 2 - 100, -BLINDING, L / 2 + 100, 0, "S-CONC", lineweight=18)
        s.hatch(
            [
                (-L / 2 - 100, -BLINDING),
                (L / 2 + 100, -BLINDING),
                (L / 2 + 100, 0),
                (-L / 2 - 100, 0),
            ],
            pattern="AR-CONC",
        )
        for x, y in f.piles:
            if abs(y - cy) < pile / 2 + 1:
                s.line((x - pile / 2, 0), (x - pile / 2, -pile_len), "S-FNDN")
                s.line((x + pile / 2, 0), (x + pile / 2, -pile_len), "S-FNDN")
        if outline:
            x0, x1 = cx - half_x, cx + half_x
            s.line((x0, T), (x0, T + col_h), "S-COLS")
            s.line((x1, T), (x1, T + col_h), "S-COLS")
            w = x1 - x0
            zig = [
                (x0 - 40, T + col_h),
                (x0 + w * 0.4, T + col_h),
                (x0 + w * 0.5, T + col_h + 50),
                (x0 + w * 0.55, T + col_h - 50),
                (x0 + w * 0.65, T + col_h),
                (x1 + 40, T + col_h),
            ]
            s.polyline(zig, "S-COLS", lineweight=18)
        x_bar_y = c + dy_ + dx_ / 2  # the X bars lie on the Y bars
        if f.bottom_x:
            d = f.bottom_x.dia
            leg = min(f.bottom_x.legs, T - 2 * c - d)
            path = [(-L / 2 + c, x_bar_y), (L / 2 - c, x_bar_y)]
            if leg > 0:
                path = [(-L / 2 + c, x_bar_y + leg), *path, (L / 2 - c, x_bar_y + leg)]
            bar = s.polyline(path, "S-REBAR-MAIN")
            tag(bar, mark=f.bottom_x.mark, kind="bottomX")
        if f.bottom_y:
            d = f.bottom_y.dia
            for u in y_lines:
                s.dot((u, c + d / 2), d / 2)
        if f.starters and outline:
            count, d = f.starters
            inset = f.starter_inset if f.starter_inset is not None else 40 + 10 + d / 2
            foot = f.starter_leg if f.starter_leg is not None else 12 * d
            y_foot = c + dx_ + dy_ + d / 2  # the foot rests on the mesh
            for side in (-1, 1):
                x = cx + side * (half_x - inset)
                if f.starter_hook in ("outward", "away"):
                    direction = side
                elif abs(x) > 1:  # toCentre: towards the footing's centre
                    direction = -1 if x > 0 else 1
                else:
                    direction = -side
                room = (L / 2 - c - d / 2) - direction * x  # to the far cover line
                reach = min(foot - d / 2, room)
                bar = s.polyline(
                    [(x, T + col_h), (x, y_foot), (x + direction * reach, y_foot)], "S-REBAR-MAIN"
                )
                tag(bar, mark=f.starter_mark or "starter", dia=f"{d:g}", count=count)
            mark = f"{f.starter_mark} " if f.starter_mark else ""
            s.label(
                f"{mark}STARTERS {count}Ø{d:g}",
                (cx + half_x, T + col_h * 0.6),
                [(4, 0, "ML"), (4, 6, "ML")],
                leader=True,
            )
        s.dim((-L / 2, 0), (L / 2, 0), -(BLINDING / S + 6))
        s.dim((L / 2, 0), (L / 2, T), -6, angle=90)
        if f.bottom_x:
            s.label(
                _two_lines(f.bottom_x),
                (L / 2 - c - 100, x_bar_y),
                _to(s, (L / 2 - c - 100, x_bar_y), [(L / 2, T * 0.55, "ML")], dx=12),
                leader=True,
            )
        if f.bottom_y and y_lines:
            u = y_lines[-1]
            s.label(
                _two_lines(f.bottom_y),
                (u, c + f.bottom_y.dia / 2),
                _to(s, (u, c + f.bottom_y.dia / 2), [(L / 2, T * 0.15, "ML")], dx=12),
                leader=True,
            )
        level = (
            f"FOUNDING LEVEL {f.founding_level / 1000:+.3f}" if f.founding_level is not None else ""
        )
        view.text(
            "\n".join(t for t in ("SECTION A-A", f"COVER {f.cover:g}", level) if t),
            (ox, 16),
            TEXT,
            "TC",
        )

    kind = "Pile cap" if f.kind == "pile cap" else "Footing"
    return ViewSpec(
        f"{kind} {f.mark}",
        1,
        (0, 0, width, height),
        draw,
        pad=(2, 2, 2, 2),
        subtitle=f"{L:g}x{B:g}x{T:g}   SCALE 1:{S:g}",
        key=f"footing:{f.mark}",
    )


def retaining_wall_detail(w: RetainingWallDetail, scale: float = 25) -> ViewSpec:
    """Section of a retaining or basement wall per metre run at ``1:scale``: the base (toe,
    stem, heel), the stem battered on its front face, the retained and front ground, the
    blinding, the floors that prop a basement wall, and the bars of its reinforcement."""
    S = scale
    B = w.toe + w.stem_bottom + w.heel
    T, H = w.base, w.stem_height
    back = w.toe + w.stem_bottom  # x of the stem's soil face
    batter = w.stem_bottom - w.stem_top
    c = w.cover
    label_w = 60.0
    width = (B + 1000) / S + 30 + label_w
    height = (T + H + BLINDING) / S + 50
    ox = 20 + 500 / S  # paper x of the toe

    def draw(view: View) -> None:
        s = view.inset(ox, 30 + BLINDING / S, S)
        outline = [
            (0, 0),
            (B, 0),
            (B, T),
            (back, T),
            (back, T + H),
            (back - w.stem_top, T + H),
            (w.toe, T),
            (0, T),
        ]
        if w.kind == "basement":  # the stem on the raft: only the stem is the wall's
            outline = [(w.toe, 0), (back, 0), (back, T + H), (back - w.stem_top, T + H), (w.toe, T)]
        s.polyline(outline, "S-CONC", close=True)
        if w.kind == "cantilever":
            s.rect(-100, -BLINDING, B + 100, 0, "S-CONC", lineweight=18)
            s.hatch(
                [(-100, -BLINDING), (B + 100, -BLINDING), (B + 100, 0), (-100, 0)],
                pattern="AR-CONC",
            )
        # the ground behind and in front
        s.line((back, w.retained), (B + 800, w.retained), "S-TEXT")
        s.text("RETAINED GROUND", (B + 400, w.retained + s.real(3)), TEXT, "BC")
        if w.front > T + 1:
            s.line((-500, w.front), (w.toe + batter * (w.front - T) / max(H, 1), w.front), "S-TEXT")
        for y in w.supports:  # the floors that prop a basement wall
            s.line((w.toe - 600, y), (w.toe + batter * (y - T) / max(H, 1), y), "S-SLAB")
            s.text("FLOOR", (w.toe - 300, y + s.real(2)), TEXT, "BC")
        dims_y = -(BLINDING / S + 6)
        if w.kind == "cantilever":
            s.chain([(0, 0), (w.toe, 0), (back, 0), (B, 0)], dims_y)
            s.dim((0, 0), (B, 0), dims_y - 7)
            s.dim((B, 0), (B, T), -6, angle=90)
        s.dim((back, T), (back, T + H), -(w.heel / S + 12), angle=90)
        s.dim((back - w.stem_top, T + H), (back, T + H), 5)
        # bars
        if w.stem_back:
            d = w.stem_back.dia
            x = back - c - d / 2
            foot = COVER_UNDER + d / 2 if w.kind == "cantilever" else 0.0
            path = [(x, T + H - c), (x, foot)]
            if w.kind == "cantilever":
                path.append((max(x - w.stem_bottom - 12 * d, c), foot))
            bar = s.polyline(path, "S-REBAR-MAIN")
            tag(bar, mark=w.stem_back.mark, kind="stemBack")
            s.label(
                _two_lines(w.stem_back), (x, T + H * 0.6), [(B + 200 - x, 0, "ML")], leader=True
            )
        if w.stem_front:
            d = w.stem_front.dia
            bottom = (w.toe + c + d / 2, COVER_UNDER + d / 2 if w.kind == "cantilever" else 0.0)
            top = (back - w.stem_top + c + d / 2, T + H - c)
            bar = s.polyline([bottom, top], "S-REBAR-MAIN")
            tag(bar, mark=w.stem_front.mark, kind="stemFront")
            s.label(
                _two_lines(w.stem_front),
                (top[0], T + H * 0.4),
                [(-(top[0] + 300) / S - 10, 0, "MR")],
                leader=True,
            )
        if w.horizontal:
            d = w.horizontal.dia
            inner = (w.stem_back.dia if w.stem_back else 0.0) + d / 2
            for y in bar_positions(T + 50, T + H - c, w.horizontal):
                s.dot((back - c - inner, y), d / 2)
            s.label(
                _bars_label(w.horizontal, "EF (H)"),
                (back - c - inner, T + H * 0.85),
                [(B + 200 - back, 0, "ML")],
                leader=True,
            )
        if w.heel_top and w.kind == "cantilever":
            d = w.heel_top.dia
            y = T - c - d / 2
            bar = s.polyline([(w.toe, y), (B - c, y), (B - c, COVER_UNDER + d)], "S-REBAR-MAIN")
            tag(bar, mark=w.heel_top.mark, kind="heelTop")
            s.label(
                _two_lines(w.heel_top), ((back + B) / 2, y), [(0, T / S + 8, "BC")], leader=True
            )
        if w.toe_bottom and w.kind == "cantilever":
            d = w.toe_bottom.dia
            y = COVER_UNDER + d / 2
            bar = s.polyline([(c, T - c), (c, y), (B - c, y)], "S-REBAR-MAIN")
            tag(bar, mark=w.toe_bottom.mark, kind="toeBottom")
            s.label(
                _two_lines(w.toe_bottom),
                (w.toe / 2, y),
                [(0, -(BLINDING / S + 18), "TC")],
                leader=True,
            )
        view.text(
            "\n".join(
                (
                    "SECTION (PER METRE RUN)",
                    f"COVER {c:g}, {COVER_UNDER:g} UNDER THE BASE",
                    f"FOUNDING LEVEL {w.founding_level / 1000:+.3f}",
                )
            ),
            (ox + B / S / 2, 12),
            TEXT,
            "TC",
        )

    kind = "Basement wall" if w.kind == "basement" else "Retaining wall"
    return ViewSpec(
        f"{kind} {w.mark}",
        1,
        (0, 0, width, height),
        draw,
        pad=(2, 2, 2, 2),
        subtitle=f"L = {w.length / 1000:.2f} m   SCALE 1:{S:g}",
        key=f"retaining:{w.mark}",
    )


def _to(
    view: View, anchor: tuple[float, float], targets: list[tuple], dx: float = 0.0
) -> list[tuple[float, float, str]]:
    """Paper offsets from ``anchor`` to the real points ``targets`` (x, y, align), ``dx``
    paper mm further right."""
    ax, ay = view.p(*anchor)
    out = []
    for x, y, align in targets:
        px, py = view.p(x, y)
        out.append((px - ax + dx, py - ay, align))
    return out


# ─────────────────────────────────── walls ───────────────────────────────────


def wall_detail(w: WallDetail, scale: float = 50, section_scale: float = 25) -> ViewSpec:
    """Elevation of a wall with its web bars, end zones and openings, and its plan section."""
    E, S = scale, section_scale
    L, H, t = w.length, w.height, w.thickness
    level_w = max((text_width(f"{n} {z / 1000:+.3f}", TEXT) + 10 for n, z in w.levels), default=0)
    label_w = 70.0
    elev_w, elev_h = L / E + 30 + level_w + label_w, H / E + 26
    sec_h = t / S + 34
    width = max(elev_w, L / S + 30)
    height = elev_h + sec_h + 10

    def draw(view: View) -> None:
        e = view.inset(15 + level_w, sec_h + 18, E)
        e.rect(0, 0, L, H, "S-WALL")
        for x, sill, ow, oh in w.openings:
            e.rect(x, sill, x + ow, sill + oh, "S-OPEN")
            e.line((x, sill), (x + ow, sill + oh), "S-OPEN")
            e.line((x + ow, sill), (x, sill + oh), "S-OPEN")

        def in_opening(x: float, y: float) -> bool:
            return any(ox <= x <= ox + ow and sl <= y <= sl + oh for ox, sl, ow, oh in w.openings)

        c = w.cover
        if w.vertical:
            x = w.boundary_length + w.vertical.spacing / 2 if w.boundary_length else c
            while x <= L - (w.boundary_length or c) + 1e-6:
                _broken_line(e, (x, c), (x, H - c), in_opening, vertical=True)
                x += w.vertical.spacing
        if w.horizontal:
            y = c
            while y <= H - c + 1e-6:
                _broken_line(e, (c, y), (L - c, y), in_opening, vertical=False)
                y += w.horizontal.spacing
        for x0 in (0.0, L - w.boundary_length) if w.boundary_length else ():
            e.rect(x0, 0, x0 + w.boundary_length, H, "S-REBAR-LINK", linetype="DASHED")
        for k, lt in enumerate(w.lintels):
            _lintel(e, lt, k)
        for name, z in w.levels:
            e.line((-300, z), (0, z), "S-TEXT")
            e.text(f"{name} {z / 1000:+.3f}", (-300 - e.real(1), z), TEXT, "MR")
        e.dim((0, 0), (L, 0), -6)
        e.dim((L, 0), (L, H), -6, angle=90)
        if w.boundary_length:
            e.dim((0, H), (w.boundary_length, H), 6)
            e.dim((L - w.boundary_length, H), (L, H), 6)
        e.reserve([(0, 0), (L, H)])
        if w.vertical:
            e.label(
                _bars_label(w.vertical, "V EF" if w.layers == 2 else "V"),
                (L, H * 0.7),
                [(16, 0, "ML"), (16, 6, "ML")],
                leader=True,
            )
        if w.horizontal:
            e.label(
                _bars_label(w.horizontal, "H EF" if w.layers == 2 else "H"),
                (L, H * 0.3),
                [(16, 0, "ML"), (16, -6, "ML")],
                leader=True,
            )
        if w.boundary_bars and w.boundary_length:
            n, d = w.boundary_bars
            hoops = f", HOOPS {w.hoops.text}" if w.hoops else ""
            e.label(
                f"END ZONE {n}Ø{d:g}{hoops}",
                (w.boundary_length / 2, H * 0.5),
                [(0, 0, "MC")],
                rotation=90,
            )
        view.text("ELEVATION", (15 + level_w + L / E / 2, sec_h + 8), TEXT, "TC")
        # plan section
        s = view.inset(15, 18, S)
        s.rect(0, 0, L, t, "S-WALL")
        s.hatch([(0, 0), (L, 0), (L, t), (0, t)])
        inset = c + (w.horizontal.dia if w.horizontal else 10)
        faces = (inset, t - inset) if w.layers == 2 else (t / 2,)
        if w.horizontal:
            for y in faces:
                s.line(
                    (c, y + (-1 if y < t / 2 else 1) * w.horizontal.dia / 2 * -1),
                    (L - c, y + (-1 if y < t / 2 else 1) * w.horizontal.dia / 2 * -1),
                    "S-REBAR-MAIN",
                    lineweight=18,
                )
        if w.vertical:
            d = w.vertical.dia
            x = w.boundary_length + w.vertical.spacing / 2 if w.boundary_length else c + d
            while x <= L - (w.boundary_length or c + d) + 1e-6:
                for y in faces:
                    s.dot((x, y + (d / 2 if y < t / 2 else -d / 2)), d / 2)
                x += w.vertical.spacing
        if w.boundary_bars and w.boundary_length:
            n, d = w.boundary_bars
            per_face = max(n // 2, 1)
            for x0 in (0.0, L - w.boundary_length):
                hc = c
                s.rect(x0 + hc, hc, x0 + w.boundary_length - hc, t - hc, "S-REBAR-LINK")
                for i in range(per_face):
                    x = (
                        x0
                        + c
                        + d
                        + (w.boundary_length - 2 * c - 2 * d) * (i / max(per_face - 1, 1))
                    )
                    for y in (c + 10 + d / 2, t - c - 10 - d / 2):
                        s.dot((x, y), d / 2)
        s.dim((0, 0), (L, 0), -5)
        s.dim((L, 0), (L, t), -5, angle=90)
        view.text(f"SECTION (PLAN)   COVER {c:g}", (15 + L / S / 2, 6), TEXT, "TC")

    return ViewSpec(
        f"Wall {w.mark}",
        1,
        (0, 0, width, height),
        draw,
        pad=(2, 2, 2, 2),
        subtitle=f"{t:g} THK   ELEVATION 1:{E:g}, SECTION 1:{S:g}",
        key=f"wall:{w.mark}",
    )


def _lintel(e: View, lt: LintelDetail, index: int) -> None:
    """A lintel in a wall's elevation: its outline, the bottom and top bars along it, the
    stirrups at their spacing (every one up to 40, else the end ones and a dimension), and
    its label with the bar marks above the wall's top or the next free line."""
    x0, x1, y0 = lt.x0, lt.x1, lt.bottom
    y1 = y0 + lt.depth
    e.rect(x0, y0, x1, y1, "S-CONC")
    c = 25.0
    for bars, y in ((lt.bottom_bars, y0 + c), (lt.top_bars, y1 - c)):
        if bars:
            e.line((x0 + c, y), (x1 - c, y), "S-REBAR-MAIN", lineweight=18)
    if lt.stirrups:
        _, spacing, _ = lt.stirrups
        first = 50.0
        count = int(max(x1 - x0 - 2 * first, 0.0) // spacing) + 1 if spacing > 0 else 0
        step_x = spacing
        if count > 40:
            count, step_x = 2, x1 - x0 - 2 * first
        for i in range(count):
            x = x0 + first + i * step_x
            e.line((x, y0 + c / 2), (x, y1 - c / 2), "S-REBAR-LINK")
    text = f"LINTEL {lt.opening}: {lt.text}" if lt.text else f"LINTEL {lt.opening}"
    e.label(
        text,
        ((x0 + x1) / 2, y1),
        [(0, 8 + 6 * (index % 3), "BC"), (10, 8 + 6 * (index % 3), "BL")],
        leader=True,
    )


def _broken_line(view: View, a, b, inside, vertical: bool, step: float = 50.0) -> None:
    """A bar from a to b, left out where it crosses an opening."""
    length = abs(b[1] - a[1]) if vertical else abs(b[0] - a[0])
    n = max(int(length // step), 1)
    run_start = None
    prev = a
    for i in range(n + 1):
        t = i / n
        p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        if inside(*p):
            if run_start is not None:
                view.line(run_start, prev, "S-REBAR-MAIN", lineweight=13)
                run_start = None
        elif run_start is None:
            run_start = p
        prev = p
    if run_start is not None:
        view.line(run_start, prev, "S-REBAR-MAIN", lineweight=13)


# ─────────────────────────────────── stairs ───────────────────────────────────


def stair_detail(st: StairDetail, scale: float = 25) -> ViewSpec:
    """The section along the first flight (with the landing) and the plan of a stair."""
    S = scale
    risers = st.flights[0] if st.flights else 10
    run = (risers - 1) * st.tread
    rise = risers * st.riser
    land = st.landing_length if len(st.flights) > 1 or st.landing_length else 0.0
    total = st.support + run + land
    sec_w, sec_h = total / S + 40, (rise + st.waist * 2 + 400) / S + 40
    plan_scale = S * 2
    n_flights = max(len(st.flights), 1)
    plan_w = (run + land + st.support) / plan_scale + 30
    plan_h = (st.width * n_flights + 100) / plan_scale + 30
    width = sec_w + plan_w + 10
    height = max(sec_h, plan_h) + 20

    def draw(view: View) -> None:
        s = view.inset(20, 24 + st.waist * 1.5 / S, S)
        tan = st.riser / st.tread
        cos = math.cos(math.atan(tan))
        x_top = st.support + run  # the top landing's edge (last riser)

        def pitch(xx: float, below: float = 0.0) -> float:
            """The line through the roots of the steps (the top of the waist), ``below`` lower
            measured square to it."""
            return (xx - st.support) * tan - below / cos

        def on(below: float, level: float) -> float:
            """Where the line ``below`` the root line reaches ``level``."""
            return st.support + (level + below / cos) / tan

        pts = [(0.0, -st.waist), (0.0, 0.0), (st.support, 0.0)]
        x, y = st.support, 0.0
        for _ in range(risers - 1):
            y += st.riser
            pts.append((x, y))
            x += st.tread
            pts.append((x, y))
        pts += [(x, rise), (x + land, rise)]
        lt = st.landing_thickness
        pts += [
            (x_top + land, rise - lt),
            (on(st.waist, rise - lt), rise - lt),
            (on(st.waist, -st.waist), -st.waist),
        ]
        s.polyline(pts, "S-CONC", close=True)
        s.dim((st.support, 0), (x_top, 0), -(st.waist / S + 6))
        s.dim((x_top + land, 0), (x_top + land, rise), -8, angle=90)
        c = st.cover
        main_d = st.main.dia if st.main else 10.0
        if st.main:
            off = st.waist - c - main_d / 2  # the bar's line below the pitch line
            low, high = -st.waist + c + main_d / 2, rise - lt + c + main_d / 2
            path = [(c, low), (on(off, low), low), (on(off, high), high), (x_top + land - c, high)]
            bar = s.polyline(path, "S-REBAR-MAIN")
            tag(bar, mark=st.main.mark, kind="main")
            mid = st.support + run * 0.55
            s.label(
                _bars_label(st.main, "MAIN"),
                (mid, pitch(mid, off)),
                [(4, -10, "TL"), (10, -14, "TL"), (16, -18, "TL")],
                leader=True,
            )
        if st.distribution:
            d = st.distribution.dia
            off = st.waist - c - main_d - d / 2
            x0, x1 = on(off, -st.waist + c + main_d + d / 2), on(off, rise - lt + c + main_d)
            n = max(int(math.hypot(x1 - x0, (x1 - x0) * tan) // st.distribution.spacing), 1)
            for i in range(1, n):
                xx = x0 + (x1 - x0) * i / n
                s.dot((xx, pitch(xx, off)), d / 2, layer="S-REBAR-LINK")
            mid = st.support + run * 0.3
            s.label(
                _bars_label(st.distribution, "DIST."),
                (mid, pitch(mid, off)),
                [(10, -18, "TL"), (16, -22, "TL"), (22, -26, "TL")],
                leader=True,
            )
        if st.top:
            d = st.top.dia
            off = c + d / 2
            reach = st.support + run * 0.3
            path = [
                (c, -st.waist + c + 2 * d + main_d),
                (c, -off),
                (on(off, -off), -off),
                (reach, pitch(reach, off)),
            ]
            top_bar = s.polyline(path, "S-REBAR-MAIN", linetype="DASHED")
            tag(top_bar, mark=st.top.mark, kind="top")
            s.label(
                _bars_label(st.top, "TOP"),
                (st.support * 0.5, -off),
                [(0, 10, "BC"), (-6, 14, "BC")],
                leader=True,
            )
        view.text(
            f"SECTION ALONG FLIGHT   {risers} RISERS {st.riser:g}, TREADS {st.tread:g}"
            f"   COVER {c:g}",
            (20 + total / S / 2, 8),
            TEXT,
            "TC",
        )
        # plan
        p = view.inset(sec_w + 15, height - 20 - (st.width * n_flights) / plan_scale, plan_scale)
        p.rect(0, 0, st.support, st.width * n_flights, "S-STAIR")
        for k in range(n_flights):
            y0 = k * st.width
            p.rect(st.support, y0, st.support + run, y0 + st.width, "S-STAIR")
            for i in range(1, risers - 1):
                xx = st.support + i * st.tread
                p.line((xx, y0), (xx, y0 + st.width), "S-STAIR")
        if land:
            p.rect(st.support + run, 0, st.support + run + land, st.width * n_flights, "S-STAIR")
        p.line((st.support, st.width / 2), (st.support + run, st.width / 2), "S-STAIR")
        p.dim((st.support, 0), (st.support + run, 0), -5)
        p.dim((0, 0), (0, st.width * n_flights), 5, angle=90)
        view.text(
            f"PLAN 1:{plan_scale:g}",
            (
                sec_w + 15 + (run + land) / plan_scale / 2,
                height - 26 - st.width * n_flights / plan_scale - 8,
            ),
            TEXT,
            "TC",
        )

    return ViewSpec(
        f"Stair {st.mark}",
        1,
        (0, 0, width, height),
        draw,
        pad=(2, 2, 2, 2),
        subtitle=f"WAIST {st.waist:g}   SECTION 1:{S:g}",
        key=f"stair:{st.mark}",
    )

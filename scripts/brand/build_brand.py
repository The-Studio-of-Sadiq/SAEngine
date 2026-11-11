"""Build the SAEngine brand assets from one hand-drawn geometry.

The SAEngine logo is a building mark (a navy structural frame beside a blue meshed facade, on a
ground arc), a thin grey divider and the wordmark "SAEngine" ("SA" heavy and wide, "Engine"
regular and squarish). Everything below is drawn by hand as SVG path data in the coordinates of
the logo artwork (1536 x 1024 px); nothing is traced or embedded as a raster.

This script writes:

- the SVG masters in ``workbench/resources/brand/`` (lockup, mark, wordmark; colour, for dark
  backgrounds and one-colour white), see the README there for the brand tokens;
- the workbench copies of the mark (``resources/saengine-mark.svg``, the title bar / welcome
  icon ``code-icon.svg``, the empty editor letterpress);
- the raster icons generated from the same geometry (Windows ``.ico`` / tiles / installer
  bitmaps, macOS ``.icns``, Linux ``.png`` / ``.xpm``, the web manifest icons and favicon);
- the start page's inline mark and wordmark (``saengineBrandArt.ts``), so the app draws the
  same paths with theme colours;
- the report footer mark used by the PDF and Word reports;
- the static instances of the brand typeface (Saira, OFL-1.1) for the reports, from the
  variable font the workbench bundles.

Only Pillow, numpy and fontTools are needed (no SVG renderer): a small rasteriser here renders the subset
of SVG the masters use (paths with lines, quadratic curves and arcs, circles, rounded rects,
linear gradients, masks), so the rasters match the SVG files.

    python scripts/brand/build_brand.py            # write everything
    python scripts/brand/build_brand.py --preview out.png   # also a side-by-side preview
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
WB = ROOT / "workbench"
BRAND = WB / "resources" / "brand"

# ───────────────────────────── brand tokens ─────────────────────────────

NAVY = "#0A1F3D"  # frame, ground arc and wordmark (sampled from the artwork)
FACADE_TOP = "#1C6EC1"  # facade gradient, top right
FACADE_BOTTOM = "#0B3C84"  # facade gradient, bottom left
GREY = "#939AA3"  # the divider (and the glimpse of a column behind the frame)
WHITE = "#FFFFFF"
# On dark backgrounds the frame and the wordmark turn white and the facade lightens.
FACADE_TOP_DARK = "#4C94E8"
FACADE_BOTTOM_DARK = "#1F5FBF"

# ───────────────────────────── geometry ─────────────────────────────
# Artwork coordinates (px of the 1536 x 1024 source). The mark spans x 63..530, y 323..644;
# the wordmark x 584..1464, cap height 412..554 (baseline 554), descender to 592.


def _q(p0, c, p1, t):
    return (
        (1 - t) ** 2 * p0[0] + 2 * t * (1 - t) * c[0] + t * t * p1[0],
        (1 - t) ** 2 * p0[1] + 2 * t * (1 - t) * c[1] + t * t * p1[1],
    )


ARC_L, ARC_C_TOP, ARC_R = (63.0, 642.0), (297.0, 553.0), (530.0, 644.0)
ARC_C_BOTTOM = (297.0, 577.0)


def arc_top_t(x: float) -> float:
    """The parameter of the ground arc's top curve at x (x(t) is monotonic)."""
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _q(ARC_L, ARC_C_TOP, ARC_R, mid)[0] < x:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def arc_top(x: float) -> float:
    return _q(ARC_L, ARC_C_TOP, ARC_R, arc_top_t(x))[1]


FACADE_X0, FACADE_X1 = 305.0, 459.0
FACADE_SLOPE = 0.53
GAP = 8.0  # between the frame, the facade and the ground arc


def facade_top(x: float) -> float:
    return 334.0 + FACADE_SLOPE * (x - FACADE_X0)


def facade_bottom(x: float) -> float:
    return arc_top(x) - GAP


def f(v: float) -> str:
    """A coordinate, at most two decimals, no trailing zeros."""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def pts(*points) -> str:
    return " ".join(f"{f(x)},{f(y)}" for x, y in points)


def frame_d() -> str:
    """The navy frame: roof, posts, floor slab and columns, with the two triangular openings."""

    def col_bottom(x0, x1):
        return round(arc_top((x0 + x1) / 2) - 7, 1)

    c1, c2, c3 = col_bottom(144, 155), col_bottom(176, 189), col_bottom(229, 241)
    post = col_bottom(284, 296)
    outer = [
        (144, 404), (296, 323), (296, post), (284, post), (284, 510), (241, 520), (241, c3),
        (229, c3), (229, 523), (189, 531.5), (189, c2), (176, c2), (176, 535), (155, 538),
        (155, c1), (144, c1), (144, 517), (183, 507.6), (183, 446), (144, 454),
    ]  # fmt: skip
    upper = [(195, 420), (284, 376), (284, 459)]
    lower = [(194, 463), (253, 490), (194, 505)]
    return " ".join("M" + pts(*p).replace(" ", " L") + " Z" for p in (outer, upper, lower))


def patch_d() -> str:
    """The glimpse of a grey column behind the brace, in the lower opening."""
    return "M" + pts((232, 480.4), (242, 485), (242, 493), (232, 495.3)).replace(" ", " L") + " Z"


def arc_d() -> str:
    return f"M{pts(ARC_L)} Q{pts(ARC_C_TOP, ARC_R)} Q{pts(ARC_C_BOTTOM, ARC_L)} Z"


def facade_d() -> str:
    """The facade outline: top edge parallel to the roof's fall, bottom following the arc."""
    t0, t1 = arc_top_t(FACADE_X0), arc_top_t(FACADE_X1)
    p0 = _q(ARC_L, ARC_C_TOP, ARC_R, t0)
    # control point of the arc's sub-curve t0..t1: P(t0) + (t1 - t0) / 2 * B'(t0)
    d0 = (
        2 * (1 - t0) * (ARC_C_TOP[0] - ARC_L[0]) + 2 * t0 * (ARC_R[0] - ARC_C_TOP[0]),
        2 * (1 - t0) * (ARC_C_TOP[1] - ARC_L[1]) + 2 * t0 * (ARC_R[1] - ARC_C_TOP[1]),
    )
    c = (p0[0] + (t1 - t0) / 2 * d0[0], p0[1] + (t1 - t0) / 2 * d0[1] - GAP)
    bl = (FACADE_X0, facade_bottom(FACADE_X0))
    br = (FACADE_X1, facade_bottom(FACADE_X1))
    tl = (FACADE_X0, facade_top(FACADE_X0))
    tr = (FACADE_X1, facade_top(FACADE_X1))
    return f"M{pts(tl)} L{pts(tr)} L{pts(br)} Q{pts(c, bl)} Z"


# Facade nodes (the mesh's joints) and the white joints/lines cut out of the facade.
X_V1, X_V2 = 358.0, 416.0
A, B, C = (X_V1, 425.0), (X_V1, 492.0), (X_V1, 560.0)
E, F = (X_V2, 457.0), (X_V2, 523.0)
N1, N2 = (387.0, 412.0), (438.0, 437.0)
H, K = (395.0, 557.0), (430.0, 553.0)


def _line_at(p, slope, x):
    return (x, p[1] + slope * (x - p[0]))


@dataclass
class Cuts:
    lines: list[tuple[float, list[tuple[float, float]]]] = field(default_factory=list)
    polys: list[list[tuple[float, float]]] = field(default_factory=list)
    nodes: list[tuple[float, float, float]] = field(default_factory=list)


def facade_cuts(detail: bool, scale: float = 1.0) -> Cuts:
    """The white lines, the wedge and the node dots cut out of the facade.

    ``detail`` False drops the mesh and the dots (for icons of 32 px and smaller) and ``scale``
    thickens what is left so it still reads at that size.
    """
    cuts = Cuts()
    x_out0, x_out1 = FACADE_X0 - 3, FACADE_X1 + 3
    d_bot = facade_bottom(X_V1) + 3
    g_bot = facade_bottom(X_V2) + 3
    s_l1 = (E[1] - A[1]) / (E[0] - A[0])
    s_l2 = (F[1] - B[1]) / (F[0] - B[0])
    s_l3 = s_l2
    cuts.lines += [
        (6 * scale, [(X_V1, facade_top(X_V1) - 3), (X_V1, d_bot)]),
        (5 * scale, [E, (X_V2, g_bot)]),
        (6 * scale, [A, E, _line_at(E, s_l1, x_out1)]),
        (7 * scale, [_line_at(B, s_l2, x_out0), B, F, _line_at(F, s_l2, x_out1)]),
        (6 * scale, [_line_at(C, s_l3, x_out0), C]),
    ]
    # the wedge between the top panel and the second panel of the left column
    w = (scale - 1) * 3
    cuts.polys.append([(x_out0, 391 - w), (X_V1, 419 - w), (X_V1, 431 + w), (x_out0, 445 + w)])
    if not detail:
        return cuts
    G = (X_V2, facade_bottom(X_V2) - 1)
    t_node = (413.0, facade_top(413.0))
    v1_top = (X_V1, facade_top(X_V1))
    tr = (x_out1, facade_top(FACADE_X1))
    r_l1 = _line_at(E, s_l1, FACADE_X1 + 2)
    mesh = 3.5
    cuts.lines += [
        (4, [B, G]),
        (mesh, [C, H]),
        (mesh, [F, K, (x_out1, 550.0)]),
        (mesh, [v1_top, N1, A]),
        (mesh, [N1, t_node, N2, E, N1]),
        (mesh, [tr, N2, r_l1]),
    ]
    cuts.nodes += [
        (*A, 6.5), (*B, 6.5), (*C, 6.5), (X_V1, facade_bottom(X_V1), 5.5), (*E, 6.5), (*F, 6.5),
        (*G, 6.0), (*N1, 6.0), (*N2, 4.5), (*t_node, 4.0), (*v1_top, 3.5),
        (FACADE_X0, _line_at(C, s_l3, FACADE_X0)[1], 5.0), (*H, 4.0),
    ]  # fmt: skip
    return cuts


def facade_shades() -> tuple[list[list[tuple[float, float]]], list[tuple[tuple, tuple]]]:
    """The panels' darker lower triangles and their light diagonal facet lines."""
    l2_0 = _line_at(B, (F[1] - B[1]) / (F[0] - B[0]), FACADE_X0)
    l3_0 = _line_at(C, (F[1] - B[1]) / (F[0] - B[0]), FACADE_X0)
    v1_top = (X_V1, facade_top(X_V1))
    right_l1 = _line_at(E, (E[1] - A[1]) / (E[0] - A[0]), FACADE_X1)
    right_l2 = _line_at(F, (F[1] - B[1]) / (F[0] - B[0]), FACADE_X1)
    bot0, bot1 = (FACADE_X0, facade_bottom(FACADE_X0) + 2), (X_V1, facade_bottom(X_V1) + 2)
    cells = [  # (bottom-left, top-right, bottom-right)
        ((FACADE_X0 - 2, 391), v1_top, (X_V1, 419)),
        (l2_0, (X_V1, 431), B),
        (l3_0, B, C),
        (bot0, C, bot1),
        (B, E, F),
        (F, right_l1, right_l2),
    ]
    tris = [[bl, tr, br] for bl, tr, br in cells]
    facets = [(bl, tr) for bl, tr, _ in cells]
    return tris, facets


DIVIDER = (524.0, 393.0, 4.0, 199.0)  # x, y, width, height

# The wordmark, as outlines (no font needed). "SA": heavy, wide; "Engine": regular, squarish,
# stroke 16, outer corner radius 28 and inner 14 on the round letters, with the small notch
# where a bowl meets its stem.
WORD_SA = [
    # S
    (
        "M609,414 H706 V438 H626 Q617,438 617,447 V469 H679 A34,34 0 0 1 713,503 V528 "
        "A25,25 0 0 1 688,553 H584 V530 H671 Q679,530 679,522 V504 Q679,496 671,496 H611 "
        "A27,27 0 0 1 584,469 V439 A25,25 0 0 1 609,414 Z"
    ),
    # A (with its counter)
    (
        "M778,414 H816 L877,553 H846 L832.4,522 H761.5 L747.8,553 H716.8 Z "
        "M797,441 L820.6,495 H773.4 Z"
    ),
]


def _n(x0: float) -> str:
    return (
        f"M{f(x0)},451 H{f(x0 + 16)} V554 H{f(x0)} Z "
        f"M{f(x0 + 16)},459 Q{f(x0 + 21)},450 {f(x0 + 44)},450 H{f(x0 + 61)} "
        f"A28,28 0 0 1 {f(x0 + 89)},478 V554 H{f(x0 + 73)} V480 "
        f"A14,14 0 0 0 {f(x0 + 59)},466 H{f(x0 + 24)} Q{f(x0 + 16)},466 {f(x0 + 16)},474 Z"
    )


WORD_ENGINE = [
    # E
    "M896,412 H993 V428 H913 V475 H989 V491 H913 V538 H993 V554 H896 Z",
    _n(1010),
    # g: the bowl (a C beside the stem, so the notches show) and the stem with its hook
    (
        "M1144,450 H1172 A16,16 0 0 1 1188,466 H1147 A14,14 0 0 0 1133,480 V524 "
        "A14,14 0 0 0 1147,538 H1188 A16,16 0 0 1 1172,554 H1144 A28,28 0 0 1 1116,526 V478 "
        "A28,28 0 0 1 1144,450 Z "
        "M1188,450 H1205 V567 A25,25 0 0 1 1180,592 H1122 V576 H1178 Q1188,576 1188,566 Z"
    ),
    # i
    "M1227,449 H1242 V554 H1227 Z M1227,413 H1242 V430 H1227 Z",
    _n(1265),
    # e (with its counter)
    (
        "M1399,450 H1436 A28,28 0 0 1 1464,478 V509 H1388 V528 Q1388,538 1398,538 H1463 V554 "
        "H1399 A28,28 0 0 1 1371,526 V478 A28,28 0 0 1 1399,450 Z "
        "M1402,466 H1433 A14,14 0 0 1 1447,480 V494 H1388 V480 A14,14 0 0 1 1402,466 Z"
    ),
]

MARK_BOX = (63.0, 323.0, 530.0, 644.0)
WORD_BOX = (584.0, 412.0, 1464.0, 592.0)
LOCKUP_BOX = (63.0, 323.0, 1464.0, 644.0)

# ───────────────────────────── SVG node trees ─────────────────────────────


@dataclass
class Node:
    tag: str
    attrs: dict[str, Any] = field(default_factory=dict)
    children: list[Node] = field(default_factory=list)


@dataclass
class Palette:
    frame: str
    facade: tuple[str, str] | str
    patch: str | None
    divider: str
    word: str
    facets: bool = True


COLOUR = Palette(NAVY, (FACADE_TOP, FACADE_BOTTOM), GREY, GREY, NAVY)
DARK = Palette(WHITE, (FACADE_TOP_DARK, FACADE_BOTTOM_DARK), GREY, "#6B7686", WHITE)
MONO_WHITE = Palette(WHITE, WHITE, None, WHITE, WHITE, facets=False)
MONO_BLACK = Palette("#000000", "#000000", None, "#000000", "#000000", facets=False)
# The start page: classes the workbench styles with its brand tokens (see saengineTokens.css).
THEMED = Palette(
    "class:sa-brand-ink", ("class:sa-brand-facade-top", "class:sa-brand-facade-bottom"),
    "class:sa-brand-grey", "class:sa-brand-grey", "class:sa-brand-ink",
)  # fmt: skip


def _paint(attrs: dict[str, Any], key: str, value: str) -> dict[str, Any]:
    if value.startswith("class:"):
        attrs["class"] = value[6:]
    else:
        attrs[key] = value
    return attrs


def mark_nodes(pal: Palette, uid: str, detail: bool = True) -> list[Node]:
    """The mark's elements in artwork coordinates: frame, arc, the facade with its cuts."""
    out: list[Node] = []
    defs = Node("defs")
    cuts = facade_cuts(detail, 1.0 if detail else 3.0)
    mask = Node(
        "mask",
        {"id": f"{uid}-cut", "maskUnits": "userSpaceOnUse",
         "x": "290", "y": "315", "width": "185", "height": "305"},
        [Node("rect", {"x": "290", "y": "315", "width": "185", "height": "305", "fill": WHITE})],
    )  # fmt: skip
    for width, line in cuts.lines:
        mask.children.append(
            Node("path", {"d": "M" + pts(*line).replace(" ", " L"), "fill": "none",
                          "stroke": "#000000", "stroke-width": f(width),
                          "stroke-linecap": "round", "stroke-linejoin": "round"})
        )  # fmt: skip
    for poly in cuts.polys:
        mask.children.append(
            Node("path", {"d": "M" + pts(*poly).replace(" ", " L") + " Z", "fill": "#000000"})
        )
    for cx, cy, r in cuts.nodes:
        mask.children.append(
            Node("circle", {"cx": f(cx), "cy": f(cy), "r": f(r), "fill": "#000000"})
        )
    defs.children.append(mask)
    facade = Node("path", {"d": facade_d()})
    if isinstance(pal.facade, tuple):
        top, bottom = pal.facade
        grad = Node(
            "linearGradient",
            {"id": f"{uid}-facade", "gradientUnits": "userSpaceOnUse",
             "x1": "459", "y1": "334", "x2": "318", "y2": "612"},
            [Node("stop", _paint({"offset": "0"}, "stop-color", top)),
             Node("stop", _paint({"offset": "1"}, "stop-color", bottom))],
        )  # fmt: skip
        defs.children.append(grad)
        facade.attrs["fill"] = f"url(#{uid}-facade)"
    else:
        _paint(facade.attrs, "fill", pal.facade)
    out.append(defs)
    out.append(Node("path", _paint({"d": frame_d(), "fill-rule": "evenodd"}, "fill", pal.frame)))
    if pal.patch and detail:
        out.append(Node("path", _paint({"d": patch_d()}, "fill", pal.patch)))
    out.append(Node("path", _paint({"d": arc_d()}, "fill", pal.frame)))
    group = Node("g", {"mask": f"url(#{uid}-cut)"}, [facade])
    if pal.facets and detail:
        tris, facets = facade_shades()
        for tri in tris:
            group.children.append(
                Node("path", {"d": "M" + pts(*tri).replace(" ", " L") + " Z",
                              "fill": "#000000", "opacity": "0.1"})
            )  # fmt: skip
        for a, b in facets:
            group.children.append(
                Node("path", {"d": f"M{pts(a)} L{pts(b)}", "fill": "none", "stroke": WHITE,
                              "stroke-width": "1.2", "opacity": "0.22"})
            )  # fmt: skip
    out.append(group)
    return out


def word_nodes(pal: Palette) -> list[Node]:
    return [
        Node("path", _paint({"d": " ".join(WORD_SA), "fill-rule": "evenodd"}, "fill", pal.word)),
        Node(
            "path", _paint({"d": " ".join(WORD_ENGINE), "fill-rule": "evenodd"}, "fill", pal.word)
        ),
    ]


def divider_node(pal: Palette) -> Node:
    x, y, w, h = DIVIDER
    return Node(
        "rect", _paint({"x": f(x), "y": f(y), "width": f(w), "height": f(h)}, "fill", pal.divider)
    )


def svg(box, width, height, children: list[Node], title: str, scale=1.0, dx=0.0, dy=0.0) -> Node:
    """An SVG root of width x height whose content (artwork coords) is placed by scale/dx/dy."""
    group = Node("g", {"transform": f"translate({f(dx)} {f(dy)}) scale({f(scale)})"}, children)
    if scale == 1.0 and dx == 0 and dy == 0:
        group = Node("g", {}, children)
    return Node(
        "svg",
        {"xmlns": "http://www.w3.org/2000/svg", "viewBox": f"0 0 {f(width)} {f(height)}",
         "width": f(width), "height": f(height)},
        [Node("title", {"text": title}), group],
    )  # fmt: skip


def fit(box, width, height, pad, align_y=0.5):
    """scale, dx, dy that fit an artwork box into width x height with padding."""
    x0, y0, x1, y1 = box
    s = min((width - 2 * pad) / (x1 - x0), (height - 2 * pad) / (y1 - y0))
    dx = (width - s * (x1 - x0)) / 2 - s * x0
    dy = (height - s * (y1 - y0)) * align_y - s * y0
    return s, dx, dy


def to_xml(node: Node, indent: int = 0) -> str:
    pad = "\t" * indent
    if node.tag == "title":
        return f"{pad}<title>{node.attrs['text']}</title>"
    attrs = "".join(f' {k}="{v}"' for k, v in node.attrs.items())
    if not node.children:
        return f"{pad}<{node.tag}{attrs}/>"
    inner = "\n".join(to_xml(c, indent + 1) for c in node.children)
    return f"{pad}<{node.tag}{attrs}>\n{inner}\n{pad}</{node.tag}>"


def write_svg(path: Path, node: Node) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_xml(node) + "\n", encoding="utf-8", newline="\n")


# ───────────────────────────── asset builders ─────────────────────────────

LOCKUP_PAD = 0.0


def lockup(pal: Palette, uid: str) -> Node:
    x0, y0, x1, y1 = LOCKUP_BOX
    w, h = x1 - x0, y1 - y0
    return svg(
        LOCKUP_BOX, w, h, mark_nodes(pal, uid) + [divider_node(pal)] + word_nodes(pal),
        "SAEngine", 1.0, -x0, -y0,
    )  # fmt: skip


def mark_square(pal: Palette, uid: str, size=512, pad=16, detail=True) -> Node:
    s, dx, dy = fit(MARK_BOX, size, size, pad)
    return svg(MARK_BOX, size, size, mark_nodes(pal, uid, detail), "SAEngine", s, dx, dy)


def wordmark(pal: Palette) -> Node:
    x0, y0, x1, y1 = WORD_BOX
    return svg(WORD_BOX, x1 - x0, y1 - y0, word_nodes(pal), "SAEngine", 1.0, -x0, -y0)


def app_icon(uid: str, size=512, detail=True, inset=0.0) -> Node:
    """The app icon: the colour mark on a white rounded tile (``inset`` leaves macOS margins)."""
    tile = size - 2 * inset
    rx = tile * 0.22
    s, dx, dy = fit(MARK_BOX, tile, tile, tile * (0.1 if detail else 0.04), 0.5)
    return Node(
        "svg",
        {"xmlns": "http://www.w3.org/2000/svg", "viewBox": f"0 0 {f(size)} {f(size)}",
         "width": f(size), "height": f(size)},
        [Node("title", {"text": "SAEngine"}),
         Node("rect", {"x": f(inset + 0.5 * size / 512), "y": f(inset + 0.5 * size / 512),
                       "width": f(tile - size / 512), "height": f(tile - size / 512),
                       "rx": f(rx), "fill": WHITE, "stroke": "#C9CED6",
                       "stroke-width": f(size / 512 * (1 if detail else 2))}),
         Node("g", {"transform": f"translate({f(dx + inset)} {f(dy + inset)}) scale({f(s)})"},
              mark_nodes(COLOUR, uid, detail))],
    )  # fmt: skip


def letterpress(fill: str | None, opacity: str | None) -> Node:
    """The empty editor's letterpress: the mark as one silhouette (the editor tints it)."""
    pal = Palette(fill or "#000000", fill or "#000000", None, "#000", "#000", facets=False)
    s, dx, dy = fit(MARK_BOX, 260, 260, 8)
    root = svg(MARK_BOX, 260, 260, mark_nodes(pal, "lp"), "SAEngine", s, dx, dy)
    if opacity:
        root.attrs["opacity"] = opacity
    return root


# ───────────────────────────── rasteriser ─────────────────────────────

_TOKEN = re.compile(r"[MLHVQCAZ]|-?\d*\.?\d+(?:e-?\d+)?", re.IGNORECASE)


def _arc_points(p0, rx, ry, phi, large, sweep, p1, steps_per_rad=24):
    # SVG implementation notes F.6.5 (endpoint to centre parameterisation)
    if rx == 0 or ry == 0:
        return [p1]
    cphi, sphi = math.cos(phi), math.sin(phi)
    dx2, dy2 = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1p, y1p = cphi * dx2 + sphi * dy2, -sphi * dx2 + cphi * dy2
    lam = x1p**2 / rx**2 + y1p**2 / ry**2
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx**2 * ry**2 - rx**2 * y1p**2 - ry**2 * x1p**2
    den = rx**2 * y1p**2 + ry**2 * x1p**2
    co = math.sqrt(max(0.0, num / den)) * (-1 if large == sweep else 1)
    cxp, cyp = co * rx * y1p / ry, -co * ry * x1p / rx
    cx = cphi * cxp - sphi * cyp + (p0[0] + p1[0]) / 2
    cy = sphi * cxp + cphi * cyp + (p0[1] + p1[1]) / 2

    def ang(u, v):
        a = math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1])
        return a

    t1 = ang((1, 0), ((x1p - cxp) / rx, (y1p - cyp) / ry))
    dt = ang(((x1p - cxp) / rx, (y1p - cyp) / ry), ((-x1p - cxp) / rx, (-y1p - cyp) / ry))
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    n = max(2, int(abs(dt) * steps_per_rad))
    out = []
    for i in range(1, n + 1):
        t = t1 + dt * i / n
        x, y = rx * math.cos(t), ry * math.sin(t)
        out.append((cphi * x - sphi * y + cx, sphi * x + cphi * y + cy))
    return out


def flatten(d: str) -> list[list[tuple[float, float]]]:
    """Subpaths of an absolute SVG path as polylines."""
    toks = _TOKEN.findall(d)
    i, cmd = 0, ""
    cur = (0.0, 0.0)
    start = cur
    subs: list[list[tuple[float, float]]] = []
    poly: list[tuple[float, float]] = []

    def num():
        nonlocal i
        v = float(toks[i])
        i += 1
        return v

    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]
            i += 1
        if cmd == "M":
            if poly:
                subs.append(poly)
            cur = (num(), num())
            start = cur
            poly = [cur]
            cmd = "L"
        elif cmd == "L":
            cur = (num(), num())
            poly.append(cur)
        elif cmd == "H":
            cur = (num(), cur[1])
            poly.append(cur)
        elif cmd == "V":
            cur = (cur[0], num())
            poly.append(cur)
        elif cmd == "Q":
            c = (num(), num())
            p1 = (num(), num())
            p0 = cur
            poly += [_q(p0, c, p1, k / 16) for k in range(1, 17)]
            cur = p1
        elif cmd == "C":
            c1, c2, p1 = (num(), num()), (num(), num()), (num(), num())
            p0 = cur
            for k in range(1, 21):
                t = k / 20
                poly.append(
                    tuple(
                        (1 - t) ** 3 * p0[j] + 3 * (1 - t) ** 2 * t * c1[j]
                        + 3 * (1 - t) * t * t * c2[j] + t**3 * p1[j]
                        for j in range(2)
                    )
                )  # fmt: skip
            cur = p1
        elif cmd == "A":
            rx, ry, rot, large, sweep = num(), num(), num(), num(), num()
            p1 = (num(), num())
            poly += _arc_points(cur, rx, ry, math.radians(rot), int(large), int(sweep), p1)
            cur = p1
        elif cmd in "Zz":
            if poly:
                subs.append(poly)
            poly = []
            cur = start
        else:
            raise ValueError(f"unsupported path command {cmd!r}")
    if poly:
        subs.append(poly)
    return subs


def _rgb(colour: str) -> tuple[int, int, int]:
    c = colour.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


class Raster:
    """Renders the SVG subset above at size x size (super-sampled), in artwork space."""

    def __init__(self, width: int, height: int, ss: int = 4):
        self.w, self.h, self.ss = width * ss, height * ss, ss
        self.out_size = (width, height)
        self.canvas = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        self.defs: dict[str, Node] = {}

    def _xf(self, m, p):
        s, dx, dy = m
        return (p[0] * s + dx) * self.ss, (p[1] * s + dy) * self.ss

    def coverage_fill(self, d: str, m) -> Image.Image:
        acc = Image.new("L", (self.w, self.h), 0)
        for sub in flatten(d):
            if len(sub) < 3:
                continue
            one = Image.new("L", (self.w, self.h), 0)
            ImageDraw.Draw(one).polygon([self._xf(m, p) for p in sub], fill=255)
            acc = ImageChops.difference(acc, one)  # even-odd
        return acc

    def coverage_stroke(self, d: str, width: float, m, round_cap=True) -> Image.Image:
        acc = Image.new("L", (self.w, self.h), 0)
        draw = ImageDraw.Draw(acc)
        wpx = width * m[0] * self.ss
        for sub in flatten(d):
            p = [self._xf(m, q) for q in sub]
            draw.line(p, fill=255, width=max(1, round(wpx)), joint="curve")
            if round_cap:
                r = wpx / 2
                for x, y in (p[0], p[-1]):
                    draw.ellipse((x - r, y - r, x + r, y + r), fill=255)
        return acc

    def paint(self, cov: Image.Image, fill: str, m, opacity=1.0, mask=None):
        if mask is not None:
            cov = ImageChops.multiply(cov, mask)
        if opacity < 1:
            cov = cov.point(lambda v: round(v * opacity))
        if fill.startswith("url(#"):
            grad = self.defs[fill[5:-1]]
            x1, y1 = self._xf(m, (float(grad.attrs["x1"]), float(grad.attrs["y1"])))
            x2, y2 = self._xf(m, (float(grad.attrs["x2"]), float(grad.attrs["y2"])))
            c0 = np.array(_rgb(grad.children[0].attrs["stop-color"]), dtype=float)
            c1 = np.array(_rgb(grad.children[1].attrs["stop-color"]), dtype=float)
            yy, xx = np.mgrid[0 : self.h, 0 : self.w].astype(float)
            vx, vy = x2 - x1, y2 - y1
            t = np.clip(((xx - x1) * vx + (yy - y1) * vy) / (vx * vx + vy * vy), 0, 1)
            rgb = c0[None, None, :] * (1 - t[..., None]) + c1[None, None, :] * t[..., None]
            layer = Image.fromarray(rgb.round().astype(np.uint8), "RGB").convert("RGBA")
        else:
            layer = Image.new("RGBA", (self.w, self.h), (*_rgb(fill), 255))
        layer.putalpha(cov)
        self.canvas = Image.alpha_composite(self.canvas, layer)

    def render(self, node: Node, m=(1.0, 0.0, 0.0), mask=None):
        tag, a = node.tag, node.attrs
        if tag in ("svg", "g"):
            if "transform" in a:
                tx, ty, sc = re.findall(r"-?[\d.]+", a["transform"])
                tx, ty, sc = float(tx), float(ty), float(sc)
                m = (m[0] * sc, m[1] + tx * m[0], m[2] + ty * m[0])
            if "mask" in a:
                mask = self.mask_image(self.defs[a["mask"][5:-1]], m)
            for c in node.children:
                self.render(c, m, mask)
        elif tag == "defs":
            for c in node.children:
                self.defs[c.attrs["id"]] = c
        elif tag == "path":
            op = float(a.get("opacity", 1))
            if a.get("fill", "") not in ("", "none"):
                self.paint(self.coverage_fill(a["d"], m), a["fill"], m, op, mask)
            if "stroke" in a:
                cov = self.coverage_stroke(a["d"], float(a["stroke-width"]), m)
                self.paint(cov, a["stroke"], m, op, mask)
        elif tag == "circle":
            cx, cy = self._xf(m, (float(a["cx"]), float(a["cy"])))
            r = float(a["r"]) * m[0] * self.ss
            cov = Image.new("L", (self.w, self.h), 0)
            ImageDraw.Draw(cov).ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
            self.paint(cov, a["fill"], m, 1.0, mask)
        elif tag == "rect":
            x0, y0 = self._xf(m, (float(a["x"]), float(a["y"])))
            x1, y1 = self._xf(m, (float(a["x"]) + float(a["width"]),
                                  float(a["y"]) + float(a["height"])))  # fmt: skip
            r = float(a.get("rx", 0)) * m[0] * self.ss
            cov = Image.new("L", (self.w, self.h), 0)
            ImageDraw.Draw(cov).rounded_rectangle((x0, y0, x1, y1), r, fill=255)
            self.paint(cov, a["fill"], m, 1.0, mask)
            if "stroke" in a:
                sw = max(1, round(float(a["stroke-width"]) * m[0] * self.ss))
                cov = Image.new("L", (self.w, self.h), 0)
                ImageDraw.Draw(cov).rounded_rectangle((x0, y0, x1, y1), r, outline=255, width=sw)
                self.paint(cov, a["stroke"], m, 1.0, mask)

    def mask_image(self, mask: Node, m) -> Image.Image:
        lum = Image.new("L", (self.w, self.h), 0)
        for c in mask.children:
            sub = Raster.__new__(Raster)
            sub.w, sub.h, sub.ss, sub.defs = self.w, self.h, self.ss, self.defs
            sub.canvas = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
            sub.render(c, m)
            alpha = sub.canvas.getchannel("A")
            value = sub.canvas.convert("L")
            lum = Image.composite(value, lum, alpha)
        return lum

    def image(self) -> Image.Image:
        small = self.canvas.convert("RGBa").resize(self.out_size, Image.LANCZOS)
        return small.convert("RGBA")


def rasterise(root: Node, width: int, height: int | None = None, ss: int = 4) -> Image.Image:
    vb = [float(v) for v in root.attrs["viewBox"].split()]
    height = height or round(width * vb[3] / vb[2])
    r = Raster(width, height, ss)
    s = width / vb[2]
    r.render(root, (s, 0.0, 0.0))
    return r.image()


# ───────────────────────────── outputs ─────────────────────────────


def icon_image(size: int) -> Image.Image:
    detail = size > 32
    return rasterise(app_icon("ic", 512, detail), size, size, ss=8 if size <= 64 else 4)


def write_rasters() -> None:
    res = WB / "resources"
    big = {s: icon_image(s) for s in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256, 512, 1024)}
    # Windows: the exe / setup / .civil icon
    big[256].save(
        res / "win32" / "code.ico",
        sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)],
        append_images=[big[s] for s in (16, 20, 24, 32, 40, 48, 64, 96, 128)],
    )
    # Windows Start tiles: the mark for dark backgrounds on the brand navy, opaque, so they read
    # whatever background the shell gives them (VisualElementsManifest.xml sets the same navy)
    for size in (70, 150):
        mark = rasterise(mark_square(DARK, "tl", 512, 64, detail=size > 70), size, size, ss=8)
        tile = Image.new("RGBA", (size, size), (*_rgb(NAVY), 255))
        tile.alpha_composite(mark)
        tile.save(res / "win32" / f"code_{size}x{size}.png")
    # Linux
    big[512].save(res / "linux" / "code.png")
    write_xpm(icon_image(1024), res / "linux" / "rpm" / "code.xpm")
    # macOS: the tile inside Apple's icon grid (824 of 1024)
    mac = rasterise(app_icon("mac", 1024, True, inset=100), 1024, 1024)
    mac.save(res / "darwin" / "code.icns")
    # Web (server) manifest icons and favicon
    big[512].save(res / "server" / "code-512.png")
    icon_image(192).save(res / "server" / "code-192.png")
    big[64].save(
        res / "server" / "favicon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)],
        append_images=[big[s] for s in (16, 24, 32, 48)],
    )
    # Inno Setup wizard bitmaps (white, the mark above the wordmark / the mark alone)
    for name in sorted((res / "win32").glob("inno-*.bmp")):
        w, h = Image.open(name).size
        if "big" in name.name:
            img = installer_big(w, h)
        else:
            img = rasterise(mark_square(COLOUR, "is", 512, 40, detail=w > 64), w, h, ss=8)
        flat = Image.new("RGB", (w, h), WHITE)
        flat.paste(img, (0, 0), img)
        flat.save(name)
    # The SAEngine extensions' icons (Extensions view)
    for ext in ("theme-saengine", "saengine-language-pack-bn"):
        (WB / "extensions" / ext / "media").mkdir(exist_ok=True)
        icon_image(128).save(WB / "extensions" / ext / "media" / "icon.png")
    # The report footer mark (Word needs a raster; the PDF uses the SVG)
    rep = ROOT / "python" / "src" / "saengine" / "report" / "templates"
    rasterise(mark_square(COLOUR, "rp", 512, 0), 128, 128).save(rep / "saengine-mark.png")


def installer_big(w: int, h: int) -> Image.Image:
    """The wizard's side bitmap: the mark, and the wordmark under it, on white."""
    pal = COLOUR
    mw = w * 0.72
    s_m = mw / (MARK_BOX[2] - MARK_BOX[0])
    ww = w * 0.72
    s_w = ww / (WORD_BOX[2] - WORD_BOX[0])
    mh = s_m * (MARK_BOX[3] - MARK_BOX[1])
    wh = s_w * (WORD_BOX[3] - WORD_BOX[1])
    top = h * 0.36 - (mh + wh * 1.5) / 2
    mark = Node("g", {"transform": f"translate({f((w - mw) / 2 - s_m * MARK_BOX[0])} "
                                   f"{f(top - s_m * MARK_BOX[1])}) scale({f(s_m)})"},
                mark_nodes(pal, "ib", detail=w > 200))  # fmt: skip
    word = Node("g", {"transform": f"translate({f((w - ww) / 2 - s_w * WORD_BOX[0])} "
                                   f"{f(top + mh + wh * 0.5 - s_w * WORD_BOX[1])}) scale({f(s_w)})"},
                word_nodes(pal))  # fmt: skip
    root = Node("svg", {"viewBox": f"0 0 {w} {h}"}, [mark, word])
    return rasterise(root, w, h, ss=4)


def write_xpm(img: Image.Image, path: Path) -> None:
    """An XPM (for the RPM spec): transparent below half alpha, up to 60 colours."""
    alpha = img.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    rgb = Image.new("RGB", img.size, WHITE)
    rgb.paste(img.convert("RGB"), (0, 0), img)
    pal_img = rgb.quantize(colors=60, method=Image.Quantize.MEDIANCUT)
    palette = pal_img.getpalette()[: 60 * 3]
    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    used = sorted(set(pal_img.get_flattened_data()))
    code = {idx: chars[k] for k, idx in enumerate(used)}
    lines = ["/* XPM */", "static char * code_xpm[] = {",
             f'"{img.width} {img.height} {len(used) + 1} 1",', '" \tc None",']  # fmt: skip
    for idx in used:
        r, g, b = palette[idx * 3 : idx * 3 + 3]
        lines.append(f'"{code[idx]}\tc #{r:02X}{g:02X}{b:02X}",')
    px, al = pal_img.load(), alpha.load()
    for y in range(img.height):
        row = "".join(code[px[x, y]] if al[x, y] else " " for x in range(img.width))
        lines.append(f'"{row}"' + ("," if y < img.height - 1 else "};"))
    path.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")


def write_svgs() -> None:
    write_svg(BRAND / "saengine-lockup.svg", lockup(COLOUR, "sa"))
    write_svg(BRAND / "saengine-lockup-dark.svg", lockup(DARK, "sa"))
    write_svg(BRAND / "saengine-lockup-white.svg", lockup(MONO_WHITE, "sa"))
    write_svg(BRAND / "saengine-mark.svg", mark_square(COLOUR, "sa"))
    write_svg(BRAND / "saengine-mark-dark.svg", mark_square(DARK, "sa"))
    write_svg(BRAND / "saengine-mark-white.svg", mark_square(MONO_WHITE, "sa"))
    write_svg(BRAND / "saengine-mark-small.svg", mark_square(COLOUR, "sa", 32, 1, detail=False))
    write_svg(BRAND / "saengine-wordmark.svg", wordmark(COLOUR))
    write_svg(BRAND / "saengine-wordmark-white.svg", wordmark(MONO_WHITE))
    write_svg(BRAND / "saengine-app-icon.svg", app_icon("sa"))
    # workbench copies
    write_svg(WB / "resources" / "saengine-mark.svg", mark_square(COLOUR, "sa"))
    write_svg(WB / "src" / "vs" / "workbench" / "browser" / "media" / "code-icon.svg",
              app_icon("sa"))  # fmt: skip
    media = WB / "src" / "vs" / "workbench" / "browser" / "parts" / "editor" / "media"
    write_svg(media / "letterpress-light.svg", letterpress(None, "0.1"))
    write_svg(media / "letterpress-dark.svg", letterpress(None, "0.3"))
    write_svg(media / "letterpress-hcLight.svg", letterpress("#D9D9D9", None))
    write_svg(media / "letterpress-hcDark.svg", letterpress("#3C3C3C", None))
    rep = ROOT / "python" / "src" / "saengine" / "report" / "templates"
    write_svg(rep / "saengine-mark.svg", mark_square(COLOUR, "sa", 512, 0))


def write_ts() -> None:
    """The start page's inline art: element trees the workbench builds with its tokens."""

    def tree(n: Node):
        attrs = {k: v for k, v in n.attrs.items() if k != "text"}
        return [n.tag, attrs, [tree(c) for c in n.children]]

    x0, y0, x1, y1 = MARK_BOX
    mark = Node("g", {"transform": f"translate({f(-x0)} {f(-y0)})"}, mark_nodes(THEMED, "{id}"))
    wx0, wy0, wx1, wy1 = WORD_BOX
    word = Node("g", {"transform": f"translate({f(-wx0)} {f(-wy0)})"}, word_nodes(THEMED))
    out = WB / "src/vs/workbench/contrib/saengineProject/browser/saengineBrandArt.ts"
    body = (
        "/*---------------------------------------------------------------------------------------------\n"
        " *  Copyright (c) SAEngine contributors. All rights reserved.\n"
        " *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.\n"
        " *--------------------------------------------------------------------------------------------*/\n\n"
        "// Generated by scripts/brand/build_brand.py from the brand geometry: do not edit by hand.\n"
        "// The SAEngine mark and wordmark as SVG element trees ([tag, attributes, children]); colours\n"
        "// come from the brand tokens through the classes (see saengineTokens.css), and `{id}` is\n"
        "// replaced by an id unique to each copy.\n\n"
        "export type BrandArtNode = [string, { readonly [name: string]: string }, BrandArtNode[]];\n\n"
        f"export const MARK_VIEWBOX = '0 0 {f(x1 - x0)} {f(y1 - y0)}';\n"
        f"export const MARK_ART: BrandArtNode = {json.dumps(tree(mark), separators=(',', ':'))};\n\n"
        f"export const WORDMARK_VIEWBOX = '0 0 {f(wx1 - wx0)} {f(wy1 - wy0)}';\n"
        f"export const WORDMARK_ART: BrandArtNode = {json.dumps(tree(word), separators=(',', ':'))};\n"
    )
    out.write_text(body.replace('"', "'"), encoding="utf-8", newline="\n")


UI_FONT = WB / "src/vs/workbench/contrib/saengineProject/browser/media/fonts/Saira-Variable.ttf"
REPORT_FONTS = ROOT / "python" / "src" / "saengine" / "report" / "templates" / "fonts"
# Static instances of the variable Saira for Typst and Word, which do not pick variable axes:
# (file, family, style, weight, width)
STATIC_FONTS = [
    ("Saira-Regular.ttf", "Saira", "Regular", 400, 100),
    ("Saira-SemiBold.ttf", "Saira", "SemiBold", 600, 100),
    ("SairaExpanded-ExtraBold.ttf", "Saira Expanded", "ExtraBold", 800, 125),
]


def write_static_fonts() -> None:
    """Saira's static instances for the reports, from the bundled variable font (OFL-1.1)."""
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont

    REPORT_FONTS.mkdir(parents=True, exist_ok=True)
    for name, family, style, weight, width in STATIC_FONTS:
        font = instantiateVariableFont(TTFont(UI_FONT), {"wght": weight, "wdth": width})
        names = font["name"]
        names.removeNames(nameID=16)
        names.removeNames(nameID=17)
        regular = style == "Regular"
        rbibi = family if regular else f"{family} {style}"
        full = f"{family} {style}"
        ps = f"{family.replace(' ', '')}-{style}"
        for nid, value in ((1, rbibi), (2, "Regular"), (3, f"{ps};1.101"), (4, full), (6, ps)):
            names.setName(value, nid, 3, 1, 0x409)
            names.removeNames(nameID=nid, platformID=1)
        if not regular:
            names.setName(family, 16, 3, 1, 0x409)
            names.setName(style, 17, 3, 1, 0x409)
        font["OS/2"].usWeightClass = weight
        font["OS/2"].usWidthClass = 5 if width == 100 else 7
        if "DSIG" in font:
            del font["DSIG"]
        font.save(REPORT_FONTS / name)
    (REPORT_FONTS / "OFL.txt").write_bytes((UI_FONT.parent / "OFL.txt").read_bytes())


def preview(path: Path, source: Path | None) -> None:
    """The colour lockup rendered from the SVG geometry, next to (and over) the source image."""
    ours = rasterise(lockup(COLOUR, "pv"), 1401, 321)
    dark = rasterise(lockup(DARK, "pv"), 1401, 321)
    white = rasterise(lockup(MONO_WHITE, "pv"), 1401, 321)
    rows = []
    if source and source.exists():
        src = Image.open(source).convert("RGB").crop((63, 323, 1464, 644))
        rows.append(("source", src))
    on_white = Image.new("RGB", ours.size, WHITE)
    on_white.paste(ours, (0, 0), ours)
    rows.append(("svg", on_white))
    if source and source.exists():
        rows.append(("overlay", Image.blend(rows[0][1], on_white, 0.5)))
    on_dark = Image.new("RGB", ours.size, "#161618")
    on_dark.paste(dark, (0, 0), dark)
    rows.append(("dark", on_dark))
    on_blue = Image.new("RGB", ours.size, NAVY)
    on_blue.paste(white, (0, 0), white)
    rows.append(("white", on_blue))
    icons = Image.new("RGB", ours.size, "#E8EAED")
    x = 20
    for s in (16, 24, 32, 48, 64, 128, 256):
        im = icon_image(s)
        icons.paste(im, (x, 300 - s), im)
        x += s + 30
    dk = Image.new("RGB", (ours.width - x, ours.height), "#202124")
    icons.paste(dk, (x, 0))
    for s in (16, 32, 64, 128):
        im = icon_image(s)
        x += 20
        icons.paste(im, (x, 300 - s), im)
        x += s
    rows.append(("icons", icons))
    pad = 16
    sheet = Image.new("RGB", (ours.width + 2 * pad, sum(r.height + pad for _, r in rows) + pad),
                      "#BBBBBB")  # fmt: skip
    y = pad
    for _, r in rows:
        sheet.paste(r, (pad, y))
        y += r.height + pad
    sheet.save(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--preview", type=Path, help="also write a comparison PNG here")
    ap.add_argument("--source", type=Path, help="the logo artwork, for the preview")
    ap.add_argument("--only-preview", action="store_true")
    args = ap.parse_args()
    if not args.only_preview:
        write_svgs()
        write_ts()
        write_rasters()
        write_static_fonts()
    if args.preview:
        preview(args.preview, args.source)


if __name__ == "__main__":
    main()

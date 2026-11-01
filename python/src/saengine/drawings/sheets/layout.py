"""Drawing sheets: paper sizes, layers, text and dimension styles, the frame and title block,
views placed on a sheet at their own scale, and labels that keep clear of each other.

How a sheet is drawn (``model space drafting``, the way LibreCAD 2.2 edits a drawing): every
sheet is one DXF whose model space holds the whole sheet at the sheet's *base scale* ``1:N``:
the frame and title block are drawn ``N`` times paper size, and the views drawn at the base scale
(the plans at 1:100, the beam elevations at 1:50, ...) are at real size in millimetres, so that
distances measure true in the CAD editor. A view at another scale ``1:M`` (a beam section at 1:25
on a 1:50 sheet) is drawn ``N / M`` times real size, and its dimensions carry the linear factor
``M / N`` so that they read in real millimetres. Text is ``N`` times its paper height. A paper
space layout named after the sheet holds one viewport of the whole sheet at ``1:N`` for the CAD
programs that plot from layouts (LibreCAD 2.2 shows the model space only).

Units: millimetres; paper coordinates measure from the sheet's bottom-left corner.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import ezdxf
from ezdxf.document import Drawing
from ezdxf.enums import TextEntityAlignment

# ─────────────────────────────────── paper ───────────────────────────────────

PAPER: dict[str, tuple[float, float]] = {
    "A0": (1189.0, 841.0),
    "A1": (841.0, 594.0),
    "A2": (594.0, 420.0),
    "A3": (420.0, 297.0),
}
"""ISO 216 sheet sizes, landscape [mm]."""

# Margins [mm]: the binding edge on the left, 10 mm elsewhere (ISO 5457).
MARGIN_LEFT = 20.0
MARGIN = 10.0
# Width of the title block strip at the right of the sheet [mm].
TITLE_WIDTH = {"A0": 180.0, "A1": 170.0, "A2": 150.0, "A3": 120.0}

# Text heights on paper [mm], the ISO 3098 series: nothing smaller than 2.5, titles at least 3.5.
TEXT = 2.5
TEXT_LARGE = 3.5
TITLE = 5.0
SHEET_NUMBER = 7.0
TEXT_HEIGHTS = (TEXT, TEXT_LARGE, TITLE, SHEET_NUMBER)
CHAR_WIDTH = 0.9  # average advance of a character / text height (DXF height: the capitals')

FONT = "arial.ttf"
FONT_FAMILY = "Arial"
"""The text font, a TrueType font every Windows has: AutoCAD, BricsCAD and the PDF
(:mod:`saengine.drawings.sheets.render`) draw the same letters, whose widths :func:`text_width`
estimates. LibreCAD, which reads no TrueType fonts, draws its own default font instead. No SHX
font: those are the CAD programs' own files, not everyone's."""

# Linetypes, SAEngine's own, as dashes and gaps on paper [mm] (ISO 128 proportions); the
# drawing's LTSCALE is the sheet's scale, so that they plot at these lengths.
LINETYPES: tuple[tuple[str, str, tuple[float, ...]], ...] = (
    ("CENTER", "Centre line ____ _ ____ _", (12.0, -3.0, 2.0, -3.0)),
    ("DASHED", "Dashed __ __ __", (3.0, -1.5)),
    ("HIDDEN", "Hidden _ _ _ _", (2.0, -1.0)),
    ("PHANTOM", "Phantom ____ _ _ ____", (12.0, -2.0, 2.0, -2.0, 2.0, -2.0)),
)

HATCH_SCALES = {
    "ANSI31": 1.6 / 3.175,  # lines 3.175 apart: 1.6 mm on paper
    "AR-CONC": 0.05,  # repeats every ~190: ~10 mm on paper, its specks ~1 mm
}
"""Hatch pattern scale per unit of the sheet's base scale, for ezdxf's metric (ISO) patterns."""

PLOTTER = "DWG To PDF.pc3"
PLOT_STYLES = "monochrome.ctb"
"""The page setup of the sheets' layouts: the PDF plotter and plot style table that come with
AutoCAD (by name only; other programs use their own)."""

APP_ID = "SAENGINE"
"""XDATA application of the entities that carry their meaning (a bar's mark and length)."""

# name, ACI colour, linetype, lineweight [1/100 mm], description, plotted
LAYERS: tuple[tuple[str, int, str, int, str, bool], ...] = (
    ("S-SHEET", 7, "Continuous", 50, "Sheet frame", True),
    ("S-TITLE", 7, "Continuous", 25, "Title block", True),
    ("S-GRID", 1, "CENTER", 18, "Grid lines (centre lines)", True),
    ("S-GRID-BUBBLE", 7, "Continuous", 25, "Grid bubbles and labels", True),
    ("S-COLS", 7, "Continuous", 50, "Columns", True),
    ("S-BEAM", 3, "DASHED", 35, "Beams below the slab", True),
    ("S-BEAM-EDGE", 3, "Continuous", 35, "Beam outlines in elevations and sections", True),
    ("S-SLAB", 7, "Continuous", 35, "Slab edges", True),
    ("S-OPEN", 7, "Continuous", 25, "Openings", True),
    ("S-WALL", 7, "Continuous", 50, "Walls", True),
    ("S-STAIR", 6, "Continuous", 25, "Stairs", True),
    ("S-FNDN", 4, "HIDDEN", 35, "Foundations", True),
    ("S-PILE", 4, "Continuous", 35, "Piles in plan", True),
    ("S-PILE-GRID", 6, "CENTER", 18, "Pile grid (centre lines, its own setting-out)", True),
    ("S-CONC", 7, "Continuous", 35, "Concrete outlines of details", True),
    ("S-HATCH", 8, "Continuous", 9, "Hatching of cut concrete", True),
    ("S-REBAR-MAIN", 1, "Continuous", 50, "Main bars", True),
    ("S-REBAR-LINK", 5, "Continuous", 25, "Links, ties and stirrups", True),
    ("S-PT-TNDN", 6, "Continuous", 50, "Post-tensioning tendons in plan and profile", True),
    ("S-PT-ANCH", 6, "Continuous", 35, "PT anchors: live end (triangle), dead end (square)", True),
    ("S-PT-PROF", 6, "Continuous", 18, "PT profile marks: CGS heights, supports", True),
    ("S-STEEL", 30, "Continuous", 50, "Structural steel members", True),
    ("S-STEEL-AXIS", 30, "CENTER", 18, "Steel members' work lines (centre lines)", True),
    ("S-STEEL-PLATE", 4, "Continuous", 35, "Plates: gussets, tabs, fin and end plates", True),
    ("S-BOLT", 1, "Continuous", 25, "Bolts and bolt holes", True),
    ("S-WELD", 6, "Continuous", 25, "Weld symbols (AWS A2.4) and their text", True),
    ("S-DIMS", 2, "Continuous", 18, "Dimensions", True),
    ("S-TEXT", 7, "Continuous", 25, "Text, marks and labels", True),
    ("S-TABLE", 7, "Continuous", 25, "Schedules and tables", True),
    ("A-WALL", 7, "Continuous", 50, "Architectural walls cut by the plan or section", True),
    ("A-WALL-PATT", 8, "Continuous", 9, "Wall layer lines and their hatching", True),
    ("A-DOOR", 3, "Continuous", 25, "Doors: frames, leaves and swings", True),
    ("A-GLAZ", 4, "Continuous", 25, "Windows: frames and glass", True),
    ("A-AREA-IDEN", 7, "Continuous", 25, "Room names, numbers, areas and finishes", True),
    ("A-ELEV", 7, "Continuous", 25, "Elevations and sections: what is seen beyond the cut", True),
    ("A-SECT", 7, "Continuous", 50, "Sections: what the cut passes through; the ground line", True),
    ("A-ANNO-SYMB", 7, "Continuous", 25, "Section lines (phantom) and their marks", True),
    ("P-DOMW", 5, "Continuous", 35, "Plumbing: water risers and pump mains", True),
    ("P-SANR", 3, "Continuous", 35, "Plumbing: soil, waste and vent stacks", True),
    ("P-STRM", 4, "Continuous", 35, "Plumbing: rainwater leaders and roof drains", True),
    ("P-EQPM", 5, "Continuous", 35, "Plumbing: tanks, reservoirs, septic tanks, wet rooms", True),
    ("M-DUCT", 30, "Continuous", 35, "HVAC ducts and duct risers", True),
    ("M-EQPM", 3, "Continuous", 35, "HVAC plant and other equipment", True),
    ("E-CABL", 2, "Continuous", 35, "Electrical: cable trays, busbar and cable risers", True),
    ("E-EQPM", 1, "Continuous", 35, "Electrical: equipment, electrical rooms", True),
    ("F-PROT", 1, "Continuous", 35, "Fire protection: risers and mains", True),
    ("F-EQPM", 1, "Continuous", 35, "Fire protection: pumps, tanks, the pump room", True),
    ("M-SHFT", 8, "PHANTOM", 25, "Service shafts", True),
    ("M-SLEV", 6, "Continuous", 25, "Sleeves and openings for services", True),
    ("M-ANNO", 7, "Continuous", 25, "MEP tags: marks, sizes, systems", True),
    ("S-REV", 6, "Continuous", 35, "Revision clouds and their triangles (redrawn each run)", True),
    ("S-VIEWPORT", 8, "Continuous", 9, "Viewports (not plotted)", False),
)


def paper_size(size: str) -> tuple[float, float]:
    """Width and height [mm] of sheet ``size`` (A1, A2, A3)."""
    try:
        return PAPER[size.upper()]
    except KeyError as error:
        raise ValueError(f"unknown sheet size '{size}' (A1, A2 or A3)") from error


def _char_width(c: str) -> float:
    """Advance of a character / text height. DXF text height is the height of the capitals,
    so these are Arial's advance widths over its cap height (0.716 em), rounded up a little
    for LibreCAD's romans."""
    if c in "MW@mw":
        return 1.3
    if c in " .,:;'|!iljI":
        return 0.42
    if c in "()[]-/frt°":
        return 0.5
    if c.isupper() or c in "Ø%&":
        return 1.02
    return 0.8  # digits, lower case and the rest


def text_width(text: str, height: float) -> float:
    """Estimated width of a single line of ``text`` at ``height``."""
    return max(sum(_char_width(c) for c in text), CHAR_WIDTH) * height


# ─────────────────────────────────── title block data ───────────────────────────────────


@dataclass
class Revision:
    rev: str
    date: str = ""
    description: str = ""
    by: str = ""


@dataclass
class TitleInfo:
    """What the title block says (Project Settings and the drawing settings)."""

    project: str = "Project"
    number: str = ""
    client: str = ""
    address: str = ""
    firm: str = ""
    engineer: str = ""
    drawn: str = ""
    checked: str = ""
    approved: str = ""
    date: str = field(default_factory=lambda: date.today().isoformat())
    revision: str = "0"
    revisions: list[Revision] = field(default_factory=list)
    status: str = "FOR REVIEW"
    office: str = ""  # the office's address line under the firm (the office standard)
    disclaimer: str = ""  # printed above the status (the office standard)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> TitleInfo:
        """From a mapping with the keys of this class (camelCase aliases ``projectNumber``,
        ``drawnBy``, ``checkedBy``, ``approvedBy`` are accepted)."""
        data = dict(data or {})
        aliases = {
            "projectNumber": "number",
            "name": "project",
            "drawnBy": "drawn",
            "checkedBy": "checked",
            "approvedBy": "approved",
            "location": "address",
        }
        for alias, key in aliases.items():
            if alias in data and key not in data:
                data[key] = data.pop(alias)
            else:
                data.pop(alias, None)
        revisions = [
            r if isinstance(r, Revision) else Revision(**{k: str(v) for k, v in r.items()})
            for r in data.pop("revisions", None) or []
        ]
        known = {f for f in cls.__dataclass_fields__}
        values = {k: ("" if v is None else str(v)) for k, v in data.items() if k in known}
        return cls(**values, revisions=revisions)


# ─────────────────────────────────── the document ───────────────────────────────────


def new_document(scale: float) -> Drawing:
    """A DXF (R2013, mm) with SAEngine's layers, linetypes, text style and the dimension style of
    a sheet of base scale ``1:scale``; nothing else (no table entries that refer to fonts or
    files a CAD program might not have)."""
    doc = ezdxf.new("R2013", setup=False, units=ezdxf.units.MM)
    doc.header["$LTSCALE"] = scale
    doc.header["$PSLTSCALE"] = 0
    doc.header["$LWDISPLAY"] = 1
    doc.header["$TEXTSTYLE"] = "SAE"
    doc.header["$TEXTSIZE"] = TEXT * scale
    doc.header["$DIMSCALE"] = scale
    doc.header["$DIMSTYLE"] = dimstyle_name(scale)
    for name, description, pattern in LINETYPES:
        doc.linetypes.add(name, [sum(abs(v) for v in pattern), *pattern], description=description)
    for name, color, linetype, lineweight, description, plot in LAYERS:
        layer = doc.layers.add(name, color=color, linetype=linetype, lineweight=lineweight)
        layer.description = description
        if not plot:
            layer.dxf.plot = 0
    for style_name in ("Standard", "SAE"):
        if style_name in doc.styles:
            text_style = doc.styles.get(style_name)
        else:
            text_style = doc.styles.add(style_name, font=FONT)
        text_style.dxf.font = FONT
        text_style.set_extended_font_data(FONT_FAMILY)
    doc.appids.add(APP_ID)
    style = doc.dimstyles.add(dimstyle_name(scale))
    style.dxf.dimtxsty = "SAE"
    attribs = {
        "dimscale": scale,
        "dimtxt": TEXT,
        "dimasz": 2.0,
        "dimtsz": 0,
        "dimexo": 1.5,
        "dimexe": 1.5,
        "dimdle": 1.5,
        "dimgap": 1.0,
        "dimtad": 1,
        "dimtih": 0,
        "dimtoh": 0,
        "dimdec": 0,
        "dimzin": 8,
        "dimlunit": 2,
        "dimclrd": 256,
        "dimclre": 256,
        "dimclrt": 256,
        "dimtmove": 2,
        "dimtix": 0,
    }
    for key, value in attribs.items():
        style.dxf.set(key, value)
    style.set_arrows(blk=ezdxf.ARROWS.architectural_tick)
    return doc


def dimstyle_name(scale: float) -> str:
    return f"SAE-{scale:g}"


# ─────────────────────────────────── label placement ───────────────────────────────────


Rect = tuple[float, float, float, float]  # x0, y0, x1, y1 in paper mm


def _overlap(a: Rect, b: Rect) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _shrink(r: Rect, by: float) -> Rect:
    return (r[0] + by, r[1] + by, r[2] - by, r[3] - by)


def segment_hits(a: Sequence[float], b: Sequence[float], r: Rect) -> bool:
    """Whether the segment a-b passes through the rectangle ``r`` (Liang-Barsky clipping)."""
    if max(a[0], b[0]) < r[0] or min(a[0], b[0]) > r[2]:
        return False
    if max(a[1], b[1]) < r[1] or min(a[1], b[1]) > r[3]:
        return False
    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0] - r[0]), (dx, r[2] - a[0]), (-dy, a[1] - r[1]), (dy, r[3] - a[1])):
        if abs(p) < 1e-12:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def _segments_cross(a, b, c, d) -> bool:
    """Whether the segments a-b and c-d intersect."""

    def side(p, q, r) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    d1, d2 = side(c, d, a), side(c, d, b)
    d3, d4 = side(a, b, c), side(a, b, d)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


SOFT_LAYERS = frozenset({"S-GRID", "S-HATCH", "A-WALL-PATT", "A-ANNO-SYMB"})
"""Linework a label may cross when no position clear of everything is found (grid centre lines);
the rest (concrete, bars, beams, walls, openings, leaders...) labels keep off."""
NO_OBSTACLE_LAYERS = frozenset({"S-TABLE", "S-SHEET", "S-TITLE", "S-VIEWPORT"})


class Labels:
    """The space taken on a sheet (paper mm), so that new labels keep clear of it: text
    rectangles (``taken``), drawing kept clear of (``obstacles``: columns, bubbles, dimension
    lines), and the linework (``segments``: every line the views draw, the leaders too). A
    label placed where nothing is free is ``forced`` (and listed)."""

    CELL = 20.0  # paper mm of the grid that indexes the segments

    def __init__(self) -> None:
        self.taken: list[Rect] = []  # text
        self.obstacles: list[Rect] = []  # drawing that labels keep off (columns, bubbles, ...)
        self.segments: list[tuple[tuple[float, float], tuple[float, float], bool]] = []
        self._cells: dict[tuple[int, int], list[int]] = {}
        self.placed: list[tuple[str, int, int | None]] = []  # text, its taken index, its leader
        self.forced: list[str] = []

    def _keys(self, r: Rect) -> Iterable[tuple[int, int]]:
        c = self.CELL
        for i in range(math.floor(r[0] / c), math.floor(r[2] / c) + 1):
            for j in range(math.floor(r[1] / c), math.floor(r[3] / c) + 1):
                yield (i, j)

    def segment(self, a: Sequence[float], b: Sequence[float], soft: bool = False) -> int:
        """Records the paper line a-b as linework labels keep off; returns its index."""
        index = len(self.segments)
        pa, pb = (float(a[0]), float(a[1])), (float(b[0]), float(b[1]))
        self.segments.append((pa, pb, soft))
        box = (min(pa[0], pb[0]), min(pa[1], pb[1]), max(pa[0], pb[0]), max(pa[1], pb[1]))
        for key in self._keys(box):
            self._cells.setdefault(key, []).append(index)
        return index

    def crossing(self, rect: Rect, soft: bool = True, skip: Iterable[int] = ()) -> list[int]:
        """The segments through ``rect`` (the soft ones too when ``soft``)."""
        seen: set[int] = set(skip)
        out = []
        for key in self._keys(rect):
            for i in self._cells.get(key, ()):
                if i in seen:
                    continue
                seen.add(i)
                a, b, is_soft = self.segments[i]
                if (soft or not is_soft) and segment_hits(a, b, rect):
                    out.append(i)
        return out

    def free(self, rect: Rect, gap: float = 0.6, soft: bool = True) -> bool:
        """Whether ``rect`` (grown by ``gap``) is clear of text, obstacles and linework (the
        soft linework only when ``soft``)."""
        grown = (rect[0] - gap, rect[1] - gap, rect[2] + gap, rect[3] + gap)
        if any(_overlap(grown, r) for r in (*self.taken, *self.obstacles)):
            return False
        return not self.crossing(_shrink(rect, -min(gap, 0.3)), soft)

    def leader_free(self, a: Sequence[float], b: Sequence[float], own: Rect) -> bool:
        """Whether a leader a-b crosses no text but its own (``own``)."""
        return not any(
            segment_hits(a, b, _shrink(r, -0.5)) for r in self.taken if not _overlap(r, own)
        )

    def leader_crossings(self, a: Sequence[float], b: Sequence[float]) -> int:
        """How many lines (not the soft ones) a leader from a to b crosses, the lines at its
        start (the thing it points at) not counted."""
        length = math.dist(a, b)
        if length < 1.0:
            return 0
        t = 0.6 / length
        a2 = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        box = (min(a2[0], b[0]), min(a2[1], b[1]), max(a2[0], b[0]), max(a2[1], b[1]))
        count = 0
        seen: set[int] = set()
        for key in self._keys(box):
            for i in self._cells.get(key, ()):
                if i in seen:
                    continue
                seen.add(i)
                p, q, soft = self.segments[i]
                if not soft and _segments_cross(a2, b, p, q):
                    count += 1
        return count

    def take(self, rect: Rect) -> int:
        self.taken.append(rect)
        return len(self.taken) - 1

    def block(self, rect: Rect) -> None:
        self.obstacles.append(rect)

    def overlaps(self) -> list[tuple[Rect, Rect]]:
        """Pairs of texts that overlap (none when the placement worked)."""
        pairs = []
        for i, a in enumerate(self.taken):
            for b in self.taken[i + 1 :]:
                if _overlap(a, b):
                    pairs.append((a, b))
        return pairs

    def conflicts(self) -> list[str]:
        """What is wrong with the labels placed: a label crossed by linework other than the
        soft (grid) lines and its own leader, a leader through another text, a label forced
        onto an occupied place. Empty when the placement worked."""
        out = [f"forced: {t}" for t in self.forced]
        for text, index, leader in self.placed:
            rect = _shrink(self.taken[index], 0.2)
            skip = [leader] if leader is not None else []
            if self.crossing(rect, soft=False, skip=skip):
                out.append(f"crossed by a line: {text}")
            if leader is not None:
                a, b, _ = self.segments[leader]
                own = self.taken[index]
                for j, r in enumerate(self.taken):
                    if j != index and not _overlap(r, own) and segment_hits(a, b, _shrink(r, 0.15)):
                        out.append(f"leader through a text: {text}")
                        break
        return out


def text_rect(
    x: float, y: float, text: str, height: float, align: str = "MC", rotation: float = 0
) -> Rect:
    """Paper rectangle of a text placed at (x, y) with alignment ``align`` (L/C/R + B/M/T as
    ``"ML"``... no: first letter vertical: B, M, T; second horizontal: L, C, R)."""
    lines = text.split("\n")
    w = max(text_width(line, height) for line in lines)
    h = height * (1 + 1.6 * (len(lines) - 1))
    vertical, horizontal = align[0], align[1]
    dx = {"L": 0.0, "C": -w / 2, "R": -w}[horizontal]
    dy = {"B": 0.0, "M": -h / 2, "T": -h}[vertical]
    corners = [(dx, dy), (dx + w, dy), (dx + w, dy + h), (dx, dy + h)]
    c, s = math.cos(math.radians(rotation)), math.sin(math.radians(rotation))
    pts = [(x + u * c - v * s, y + u * s + v * c) for u, v in corners]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


_ALIGN = {
    "BL": TextEntityAlignment.BOTTOM_LEFT,
    "BC": TextEntityAlignment.BOTTOM_CENTER,
    "BR": TextEntityAlignment.BOTTOM_RIGHT,
    "ML": TextEntityAlignment.MIDDLE_LEFT,
    "MC": TextEntityAlignment.MIDDLE_CENTER,
    "MR": TextEntityAlignment.MIDDLE_RIGHT,
    "TL": TextEntityAlignment.TOP_LEFT,
    "TC": TextEntityAlignment.TOP_CENTER,
    "TR": TextEntityAlignment.TOP_RIGHT,
}


# ─────────────────────────────────── sheets and views ───────────────────────────────────


class Sheet:
    """One drawing sheet: a DXF with its frame and title block at base scale ``1:scale``."""

    def __init__(
        self,
        number: str,
        title: str,
        size: str,
        scale: float,
        info: TitleInfo,
        scale_text: str | None = None,
        north: float | None = None,
        standard: Any = None,
    ) -> None:
        self.number = number
        self.title = title
        self.size = size.upper()
        self.scale = float(scale)
        self.info = info
        self.scale_text = scale_text or f"1:{scale:g}"
        self.width, self.height = paper_size(self.size)
        self.doc = new_document(self.scale)
        # the office's drafting standard (saengine.drawings.sheets.standards): its font and
        # arrows now, its layer names when the sheet is written
        self.standard = standard
        if standard is not None:
            standard.setup(self.doc)
        self.msp = self.doc.modelspace()
        self.labels = Labels()
        self.views: list[View] = []
        self.north = north
        tw = TITLE_WIDTH[self.size]
        self.area: Rect = (
            MARGIN_LEFT + 4,
            MARGIN + 4,
            self.width - MARGIN - tw - 4,
            self.height - MARGIN - 4,
        )
        self._frame()

    # paper → model
    def m(self, x: float, y: float) -> tuple[float, float]:
        return (x * self.scale, y * self.scale)

    @property
    def dimstyle(self) -> str:
        return dimstyle_name(self.scale)

    def dimstyle_for(self, view_scale: float) -> str:
        """The dimension style of a view at ``1:view_scale`` on this sheet: the sheet's, or a
        copy whose linear factor (DIMLFAC) reads the view's real millimetres. A style of its
        own rather than an entity override, which LibreCAD does not read."""
        if abs(view_scale - self.scale) < 1e-9:
            return self.dimstyle
        name = f"{self.dimstyle}-{view_scale:g}"
        if name not in self.doc.dimstyles:
            style = self.doc.dimstyles.duplicate_entry(self.dimstyle, name)
            style.dxf.dimlfac = view_scale / self.scale
        return name

    # ── drawing in paper coordinates ──

    def p_line(self, a: Sequence[float], b: Sequence[float], layer: str = "S-TITLE", **kw: Any):
        return self.msp.add_line(self.m(*a), self.m(*b), dxfattribs={"layer": layer, **kw})

    def p_rect(self, x0: float, y0: float, x1: float, y1: float, layer: str = "S-TITLE", **kw):
        pts = [self.m(x0, y0), self.m(x1, y0), self.m(x1, y1), self.m(x0, y1)]
        return self.msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer, **kw})

    def p_text(
        self,
        text: str,
        x: float,
        y: float,
        height: float = TEXT,
        align: str = "BL",
        layer: str = "S-TEXT",
        rotation: float = 0,
        reserve: bool = True,
    ) -> int | None:
        """Text at paper position (x, y); several lines are written as separate TEXT entities
        (LibreCAD and every plotter render them alike). Returns the index of its reserved
        rectangle (``labels.taken``)."""
        lines = text.split("\n")
        step = height * 1.6
        vertical = align[0]
        n = len(lines)
        offset = {"B": (n - 1) * step, "M": (n - 1) * step / 2, "T": 0.0}[vertical]
        c, s = math.cos(math.radians(rotation)), math.sin(math.radians(rotation))
        for i, line in enumerate(lines):
            if not line:
                continue
            dy = offset - i * step
            px, py = x - dy * s, y + dy * c
            entity = self.msp.add_text(
                line,
                height=height * self.scale,
                rotation=rotation,
                dxfattribs={"layer": layer, "style": "SAE"},
            )
            entity.set_placement(self.m(px, py), align=_ALIGN[align])
        if reserve:
            return self.labels.take(text_rect(x, y, text, height, align, rotation))
        return None

    # ── frame and title block ──

    def _frame(self) -> None:
        w, h = self.width, self.height
        self.p_rect(0, 0, w, h, "S-SHEET", lineweight=13)
        self.p_rect(MARGIN_LEFT, MARGIN, w - MARGIN, h - MARGIN, "S-SHEET")
        # centring marks (ISO 5457), part of the frame: the only drawing outside the border
        for x, y, dx, dy in ((w / 2, 0, 0, 1), (w / 2, h, 0, -1), (0, h / 2, 1, 0)):
            end = (x + dx * (MARGIN + 5 if dx else 0), y + dy * (MARGIN + 5))
            self.p_line((x, y), end, "S-SHEET")
        self.p_line((w, h / 2), (w - MARGIN - 5, h / 2), "S-SHEET")
        self._title_block()

    def _title_block(self) -> None:
        info = self.info
        tw = TITLE_WIDTH[self.size]
        x0, x1 = self.width - MARGIN - tw, self.width - MARGIN
        y0, y1 = MARGIN, self.height - MARGIN
        self.p_line((x0, y0), (x0, y1), "S-SHEET")
        pad = 2.0
        y = y0

        def row(height: float, top_line: bool = True) -> tuple[float, float]:
            nonlocal y
            bottom = y
            y += height
            if top_line:
                self.p_line((x0, y), (x1, y))
            return bottom, y

        def field_(label: str, value: str, bx: float, by: float, width: float, height: float):
            self.p_text(label.upper(), bx + pad, by + height - pad, TEXT * 0.9 + 0.25, "TL")
            value = _fit(value, width - 2 * pad, TEXT_LARGE)
            self.p_text(value, bx + pad, by + pad, TEXT_LARGE, "BL")

        half = tw / 2
        # sheet number and revision
        b, t = row(20)
        self.p_line((x0 + tw * 0.7, b), (x0 + tw * 0.7, t))
        self.p_text("SHEET No.", x0 + pad, t - pad, TEXT, "TL")
        self.p_text(self.number, x0 + pad, b + pad + 1, SHEET_NUMBER, "BL")
        self.p_text("REV", x0 + tw * 0.7 + pad, t - pad, TEXT, "TL")
        # the revision itself and the revision table are written by finish(): the drawing set's
        # revisions (saengine.drawings.sheets.revisions) may set them once the views are drawn
        self._rev_at = (x0 + tw * 0.85, b + pad + 1)
        # scale, size, date
        b, t = row(12)
        third = tw / 3
        for i, (label, value) in enumerate(
            (("Scale", self.scale_text), ("Sheet", self.size), ("Date", info.date))
        ):
            if i:
                self.p_line((x0 + i * third, b), (x0 + i * third, t))
            field_(label, value, x0 + i * third, b, third, 12)
        # drawing title
        b, t = row(22)
        self.p_text("DRAWING TITLE", x0 + pad, t - pad, TEXT, "TL")
        title = _wrap(self.title.upper(), tw - 2 * pad, TITLE, 2)
        self.p_text(title, x0 + pad, b + pad, TITLE, "BL")
        # drawn / checked / approved
        b, t = row(12)
        for i, (label, value) in enumerate(
            (("Drawn", info.drawn), ("Checked", info.checked), ("Approved", info.approved))
        ):
            if i:
                self.p_line((x0 + i * third, b), (x0 + i * third, t))
            field_(label, value, x0 + i * third, b, third, 12)
        # engineer and project number
        b, t = row(12)
        self.p_line((x0 + half, b), (x0 + half, t))
        field_("Structural engineer", info.engineer, x0, b, half, 12)
        field_("Project No.", info.number, x0 + half, b, half, 12)
        # project, address, client
        b, t = row(12)
        field_("Client", info.client, x0, b, tw, 12)
        b, t = row(16)
        self.p_text("PROJECT", x0 + pad, t - pad, TEXT, "TL")
        project = _wrap(info.project, tw - 2 * pad, TEXT_LARGE, 2)
        self.p_text(project, x0 + pad, b + pad, TEXT_LARGE, "BL")
        b, t = row(12)
        field_("Address / location", info.address, x0, b, tw, 12)
        # firm (and the office's address line of the office standard)
        b, t = row(22 if info.office else 16)
        self.p_text("CONSULTING ENGINEERS", x0 + pad, t - pad, TEXT, "TL")
        lift = TEXT * 1.6 if info.office else 0.0
        self.p_text(_fit(info.firm or "-", tw - 2 * pad, 5.0), x0 + pad, b + pad + lift, 5.0, "BL")
        if info.office:
            self.p_text(_fit(info.office, tw - 2 * pad, TEXT), x0 + pad, b + pad, TEXT, "BL")
        # revision table
        rows = 5
        b, t = row(6 * (rows + 1))
        cols = (0.0, 0.14, 0.36, 0.86, 1.0)
        for c in cols[1:-1]:
            self.p_line((x0 + c * tw, b), (x0 + c * tw, t))
        for i in range(1, rows + 1):
            self.p_line((x0, b + 6 * i), (x1, b + 6 * i))
        for (c0, c1), head in zip(itertools.pairwise(cols), ("REV", "DATE", "DESCRIPTION", "BY")):
            self.p_text(head, x0 + (c0 + c1) / 2 * tw, t - 3, TEXT, "MC")
        self._revision_table = (x0, t, tw, cols, rows)
        # the office's disclaimer, then the status
        if info.disclaimer:
            text = _wrap(info.disclaimer, tw - 2 * pad, TEXT, 2)
            b, t = row(5 + TEXT * 1.6 * (text.count("\n") + 1))
            self.p_text(text, x0 + tw / 2, (b + t) / 2, TEXT, "MC")
        b, t = row(10)
        self.p_text(info.status.upper(), x0 + tw / 2, (b + t) / 2, TEXT_LARGE, "MC")
        # credit at the very top of the strip, north arrow under it
        self.p_text(
            "Generated by SAEngine (AGPL-3.0).\nCheck before construction.",
            x0 + pad,
            y1 - pad,
            TEXT,
            "TL",
        )
        self.notes_box: Rect = (x0, y, x1, y1 - 12)
        if self.north is not None:
            self.north_arrow(x0 + tw / 2, y1 - 40, self.north)

    def north_arrow(self, x: float, y: float, rotation: float = 0) -> None:
        """A north arrow at paper (x, y), north ``rotation`` degrees from the sheet's up."""
        r = 10.0
        self.msp.add_circle(self.m(x, y), r * self.scale, dxfattribs={"layer": "S-TITLE"})
        c, s = math.cos(math.radians(rotation)), math.sin(math.radians(rotation))

        def rot(u: float, v: float) -> tuple[float, float]:
            return self.m(x + u * c - v * s, y + u * s + v * c)

        tip, left, right, tail = rot(0, r), rot(-4, -r * 0.7), rot(4, -r * 0.7), rot(0, -r * 0.35)
        hatch = self.msp.add_hatch(color=7, dxfattribs={"layer": "S-TITLE"})
        hatch.paths.add_polyline_path([tip, right, tail], is_closed=True)
        self.msp.add_lwpolyline(
            [tip, left, tail, right], close=True, dxfattribs={"layer": "S-TITLE"}
        )
        nx, ny = x - (r + 4) * s, y + (r + 4) * c
        self.p_text("N", nx, ny, TEXT_LARGE, "MC")

    def notes(self, lines: Iterable[str], title: str = "NOTES") -> None:
        """Short notes in the title block strip, above the title fields."""
        x0, y0, x1, y1 = self.notes_box
        top = y1 - (30 if self.north is not None else 0) - 4
        self.p_text(title, x0 + 2, top, TEXT_LARGE, "TL")
        yy = top - 7
        for line in lines:
            for part in _wrap(line, x1 - x0 - 6, TEXT, 6).split("\n"):
                if yy < y0 + 4:
                    return
                self.p_text(part, x0 + 4, yy, TEXT, "TL")
                yy -= TEXT * 1.6
            yy -= TEXT * 0.6

    # ── viewport layout ──

    def _revisions(self) -> None:
        """The revision in the title block and the rows of its revision table (newest at the
        top), from ``self.info`` as it is when the sheet is finished."""
        if getattr(self, "_revisions_drawn", False):
            return
        self._revisions_drawn = True
        info = self.info
        x, y = self._rev_at
        self.p_text(info.revision or "0", x, y, SHEET_NUMBER, "BC")
        x0, t, tw, cols, rows = self._revision_table
        revisions = info.revisions[-rows:] or [Revision(info.revision, info.date, info.status)]
        for i, r in enumerate(reversed(revisions)):
            yy = t - 6 * (i + 1) - 3
            for (c0, c1), value in zip(
                itertools.pairwise(cols), (r.rev, r.date, r.description, r.by), strict=True
            ):
                value = _fit(value, (c1 - c0) * tw - 2, TEXT)
                self.p_text(value, x0 + c0 * tw + 1, yy, TEXT, "ML")

    def finish(self) -> None:
        """Writes the revisions into the title block and adds the paper space layout with one
        viewport of the whole sheet at the base scale."""
        self._revisions()
        name = self.number
        if name in self.doc.layouts:
            return
        paper = self.doc.layouts.new(name)
        # AutoCAD's PDF plotter and its full-bleed ISO sheet, black and white by the objects'
        # lineweights: the layout plots as it is (a page setup the plotter does not have
        # falls back to the plotter's default)
        paper.page_setup(
            size=(self.width, self.height),
            margins=(0, 0, 0, 0),
            units="mm",
            scale=(1, 1),
            name=f"ISO_full_bleed_{self.size}",
            device=PLOTTER,
        )
        paper.dxf_layout.dxf.current_style_sheet = PLOT_STYLES
        paper.add_viewport(
            center=(self.width / 2, self.height / 2),
            size=(self.width, self.height),
            view_center_point=(self.width / 2 * self.scale, self.height / 2 * self.scale),
            view_height=self.height * self.scale,
            dxfattribs={"layer": "S-VIEWPORT"},
        )
        self.doc.set_modelspace_vport(
            height=self.height * self.scale * 1.05,
            center=(self.width / 2 * self.scale, self.height / 2 * self.scale),
        )

    def view(self, spec: ViewSpec, x: float, y: float) -> View:
        """Places ``spec`` with its box's bottom-left at paper (x, y) and draws it."""
        view = View(self, spec, x, y)
        self.views.append(view)
        view.title_block()
        spec.draw(view)
        return view


def _fit(text: str, width: float, height: float) -> str:
    """``text`` cut to ``width`` at ``height`` (with an ellipsis)."""
    if text_width(text, height) <= width:
        return text
    n = max(int(width / (height * CHAR_WIDTH)) - 1, 1)
    return text[:n] + "…"


def _wrap(text: str, width: float, height: float, max_lines: int = 3) -> str:
    """``text`` broken into lines no wider than ``width`` (at most ``max_lines``)."""
    per_line = max(int(width / (height * CHAR_WIDTH)), 4)
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= per_line:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _fit(lines[-1] + " …", width, height)
    return "\n".join(_fit(line, width, height) for line in lines)


@dataclass
class ViewSpec:
    """A view to place on a sheet: ``bbox`` (x0, y0, x1, y1) in real mm drawn at ``1:scale``,
    with ``pad`` (left, bottom, right, top) of paper mm around it for dimensions and labels, a
    title under it, and ``draw(view)`` that draws it."""

    title: str
    scale: float
    bbox: Rect
    draw: Any
    pad: tuple[float, float, float, float] = (8.0, 8.0, 8.0, 8.0)
    subtitle: str | None = None
    key: str = ""
    group: str = ""

    @property
    def size(self) -> tuple[float, float]:
        """Paper width and height of the view with its pad and title."""
        x0, y0, x1, y1 = self.bbox
        w = (x1 - x0) / self.scale + self.pad[0] + self.pad[2]
        h = (y1 - y0) / self.scale + self.pad[1] + self.pad[3] + TITLE_SPACE
        title = text_width(self.title.upper(), TITLE) + 30
        return (max(w, title), h)


TITLE_SPACE = 14.0  # paper mm under a view for its title


class View:
    """A view on a sheet: real coordinates mapped onto the sheet at the view's scale."""

    def __init__(self, sheet: Sheet, spec: ViewSpec, x: float, y: float) -> None:
        self.sheet = sheet
        self.spec = spec
        self.scale = spec.scale
        self.k = sheet.scale / spec.scale  # model units per real mm
        w, _ = spec.size
        inner = (spec.bbox[2] - spec.bbox[0]) / spec.scale + spec.pad[0] + spec.pad[2]
        self.origin = (x + (w - inner) / 2 + spec.pad[0], y + TITLE_SPACE + spec.pad[1])
        self.box: Rect = (x, y, x + w, y + spec.size[1])

    # real → paper and real → model
    def p(self, x: float, y: float) -> tuple[float, float]:
        return (
            self.origin[0] + (x - self.spec.bbox[0]) / self.scale,
            self.origin[1] + (y - self.spec.bbox[1]) / self.scale,
        )

    def m(self, x: float, y: float) -> tuple[float, float]:
        px, py = self.p(x, y)
        return (px * self.sheet.scale, py * self.sheet.scale)

    def real(self, paper_length: float) -> float:
        """The real length that is ``paper_length`` mm on paper at this view's scale."""
        return paper_length * self.scale

    def title_block(self) -> None:
        x0, y0, x1, _ = self.box
        cx = (x0 + x1) / 2
        title = self.spec.title.upper()
        w = text_width(title, TITLE)
        self.sheet.p_text(title, cx, y0 + 7, TITLE, "BC")
        self.sheet.p_line((cx - w / 2, y0 + 6), (cx + w / 2, y0 + 6), "S-TEXT", lineweight=35)
        subtitle = self.spec.subtitle or f"SCALE 1:{self.scale:g}"
        self.sheet.p_text(subtitle, cx, y0 + 4.5, TEXT, "TC")

    # ── drawing in real coordinates ──

    def _attribs(self, layer: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"layer": layer, **(extra or {})}

    def _linework(self, points: Sequence[Sequence[float]], layer: str, close: bool) -> None:
        """Records drawn lines (real points) as linework that labels keep off."""
        if layer in NO_OBSTACLE_LAYERS or len(points) < 2:
            return
        pts = [self.p(*p[:2]) for p in points]
        if close:
            pts.append(pts[0])
        soft = layer in SOFT_LAYERS
        for a, b in itertools.pairwise(pts):
            self.sheet.labels.segment(a, b, soft)

    def line(self, a: Sequence[float], b: Sequence[float], layer: str, **kw: Any):
        self._linework([a, b], layer, False)
        return self.sheet.msp.add_line(self.m(*a), self.m(*b), dxfattribs=self._attribs(layer, kw))

    def polyline(self, points: Iterable[Sequence[float]], layer: str, close: bool = False, **kw):
        points = list(points)
        self._linework(points, layer, close)
        pts = [self.m(*p[:2]) for p in points]
        return self.sheet.msp.add_lwpolyline(pts, close=close, dxfattribs=self._attribs(layer, kw))

    def rect(self, x0: float, y0: float, x1: float, y1: float, layer: str, **kw: Any):
        return self.polyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer, close=True, **kw)

    def circle(self, c: Sequence[float], r: float, layer: str, **kw: Any):
        ring = [
            (c[0] + r * math.cos(math.radians(a)), c[1] + r * math.sin(math.radians(a)))
            for a in range(0, 360, 30)
        ]
        self._linework(ring, layer, True)
        return self.sheet.msp.add_circle(
            self.m(*c), r * self.k, dxfattribs=self._attribs(layer, kw)
        )

    def arc(self, c: Sequence[float], r: float, start: float, end: float, layer: str, **kw: Any):
        return self.sheet.msp.add_arc(
            self.m(*c), r * self.k, start, end, dxfattribs=self._attribs(layer, kw)
        )

    def hatch(
        self,
        points: Iterable[Sequence[float]],
        pattern: str = "ANSI31",
        layer: str = "S-HATCH",
        holes: Iterable[Iterable[Sequence[float]]] = (),
    ):
        """A hatch of the polygon ``points`` less its ``holes`` (polygons inside it):
        ``pattern`` (ezdxf's metric definition, written into the HATCH) at its size on paper of
        :data:`HATCH_SCALES`, or SOLID."""
        hatch = self.sheet.msp.add_hatch(color=256, dxfattribs={"layer": layer})
        hatch.paths.add_polyline_path([self.m(*p[:2]) for p in points], is_closed=True)
        for hole in holes:
            hatch.paths.add_polyline_path([self.m(*p[:2]) for p in hole], is_closed=True)
        if pattern.upper() == "SOLID":
            hatch.set_solid_fill(color=256)
        else:
            per_paper_mm = HATCH_SCALES.get(pattern.upper(), HATCH_SCALES["ANSI31"])
            hatch.set_pattern_fill(pattern, color=256, scale=per_paper_mm * self.sheet.scale)
        return hatch

    def dot(self, c: Sequence[float], r: float, layer: str = "S-REBAR-MAIN"):
        """A filled circle (a bar in section) of real radius ``r``, at least 0.35 mm on paper."""
        radius = max(r * self.k, 0.35 * self.sheet.scale)
        px, py = self.p(*c)
        pr = radius / self.sheet.scale
        self.sheet.labels.block((px - pr, py - pr, px + pr, py + pr))
        hatch = self.sheet.msp.add_hatch(color=256, dxfattribs={"layer": layer})
        edge = hatch.paths.add_edge_path()
        edge.add_arc(self.m(*c), radius, 0, 360)
        hatch.set_solid_fill(color=256)
        self.sheet.msp.add_circle(self.m(*c), radius, dxfattribs={"layer": layer})
        return hatch

    def text(
        self,
        text: str,
        at: Sequence[float],
        height: float = TEXT,
        align: str = "MC",
        layer: str = "S-TEXT",
        rotation: float = 0,
        reserve: bool = True,
    ) -> None:
        px, py = self.p(*at)
        self.sheet.p_text(text, px, py, height, align, layer, rotation, reserve)

    def label(
        self,
        text: str,
        anchor: Sequence[float],
        candidates: Sequence[tuple[Any, ...]] | None = None,
        height: float = TEXT,
        align: str = "MC",
        rotation: float = 0,
        leader: bool = False,
        rings: bool = True,
        force: bool = True,
        layer: str = "S-TEXT",
    ) -> tuple[float, float] | None:
        """``text`` near the real point ``anchor``: the first of the paper offsets
        ``candidates`` (``(dx, dy)`` or ``(dx, dy, align)``) where it is clear of other text,
        of the obstacles and of the linework, and where its leader (to the anchor, when
        ``leader`` or when the label had to move) crosses no other text; else further out in
        rings. Grid lines may be crossed only when nothing else is free. When no place at all
        is free the label goes to the first candidate and is listed in ``labels.forced``.
        ``rings`` False: only the candidates are tried; ``force`` False: nothing is drawn
        when none is free (returns None). ``layer``: of the text (its leader is on S-TEXT).
        Returns the paper position used."""
        labels = self.sheet.labels
        ax, ay = self.p(*anchor)
        tries = [(c[0], c[1], c[2] if len(c) > 2 else align) for c in (candidates or [(0, 0)])]
        ring_offsets = [
            (r * math.cos(a), r * math.sin(a), "MC")
            for r in (6, 10, 15, 21, 28, 36, 45, 56, 70)
            for a in [math.radians(d) for d in range(0, 360, 20)]
        ]

        def leader_of(n: int, dx: float, dy: float, how: str):
            rect = text_rect(ax + dx, ay + dy, text, height, how, rotation)
            if not ((leader or n >= len(tries)) and math.hypot(dx, dy) > height * 1.5):
                return rect, None
            near = (min(max(ax, rect[0]), rect[2]), min(max(ay, rect[1]), rect[3]))
            gap = math.hypot(near[0] - ax, near[1] - ay)
            if gap < 1.5:
                return rect, None
            # the leader stops 0.6 mm short of the text
            near = (near[0] + (ax - near[0]) / gap * 0.6, near[1] + (ay - near[1]) / gap * 0.6)
            return rect, ((ax, ay), near)

        def search(offsets: list[tuple[float, float, str]], first: int, soft: bool):
            """The free offset whose leader crosses the fewest lines (the earliest of those)."""
            best = None
            for n, (dx, dy, how) in enumerate(offsets, first):
                rect, line = leader_of(n, dx, dy, how)
                inside = (
                    rect[0] >= self.box[0] and rect[1] >= self.box[1] + TITLE_SPACE
                    and rect[2] <= self.box[2] and rect[3] <= self.box[3]
                )  # fmt: skip
                if not inside or not labels.free(rect, soft=soft):
                    continue
                if line is not None and not labels.leader_free(*line, rect):
                    continue
                crossings = labels.leader_crossings(*line) if line is not None else 0
                if best is None or crossings < best[0]:
                    best = (crossings, (dx, dy, how, line))
                if crossings == 0:
                    break
            return best[1] if best else None

        choice = None
        for soft in (True, False):
            # the candidates given first; the rings only when none of them is free
            choice = search(tries, 0, soft)
            if choice is None and rings:
                choice = search(ring_offsets, len(tries), soft)
            if choice is not None:
                break
        if choice is None and not force:
            return None
        if choice is None:
            dx, dy, how = tries[0]
            _, line = leader_of(0, dx, dy, how)
            choice = (dx, dy, how, line)
            labels.forced.append(text)
        dx, dy, how, line = choice
        px, py = ax + dx, ay + dy
        index = self.sheet.p_text(text, px, py, height, how, layer, rotation)
        segment = None
        if line is not None:
            self.sheet.p_line(line[0], line[1], "S-TEXT")
            segment = labels.segment(line[0], line[1])
        if index is not None:
            labels.placed.append((text, index, segment))
        return px, py

    def dim(
        self,
        p1: Sequence[float],
        p2: Sequence[float],
        offset: float,
        angle: float = 0,
        text: str | None = None,
        along: float | None = None,
    ):
        """A linear dimension between real points ``p1`` and ``p2`` at ``angle`` (0: horizontal,
        90: vertical), its line ``offset`` paper mm from ``p1`` (+ up / left of a vertical...: the
        side of positive offset is +y for horizontal, -x for vertical dimensions). ``along``:
        the real x of the text's centre (a horizontal dimension; default the middle)."""
        rad = math.radians(angle)
        normal = (-math.sin(rad), math.cos(rad))
        base = (p1[0] + normal[0] * self.real(offset), p1[1] + normal[1] * self.real(offset))
        mid = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
        length = abs((p2[0] - p1[0]) * math.cos(rad) + (p2[1] - p1[1]) * math.sin(rad))
        label = (text or "<>").replace("<>", f"{length:.0f}")
        extra: dict[str, Any] = {}
        if along is not None and angle == 0 and abs(along - mid[0]) > 1e-6:
            mid = (along, mid[1])
            extra["location"] = self.m(along, base[1] + self.real(1.0 + TEXT / 2))
        dimension = self.sheet.msp.add_linear_dim(
            base=self.m(*base),
            p1=self.m(*p1),
            p2=self.m(*p2),
            angle=angle,
            text=text if text is not None else "<>",
            dimstyle=self.sheet.dimstyle_for(self.scale),
            dxfattribs={"layer": "S-DIMS"},
            **extra,
        )
        dimension.render()
        if extra and dimension.dimension.has_xdata("ACAD"):
            # ezdxf writes DIMTMOVE 2 as an override for a moved text: the style has it already
            dimension.dimension.discard_xdata("ACAD")
        # reserve the dimension text
        tx = mid[0] * (1 if angle == 0 else 0) + base[0] * (0 if angle == 0 else 1)
        ty = base[1] if angle == 0 else mid[1]
        px, py = self.p(tx, ty)
        rect = text_rect(px, py + 1.0 if angle == 0 else py, label, TEXT, "BC", angle)
        if angle != 0:
            rect = text_rect(px - 1.0, py, label, TEXT, "BC", angle)
        self.sheet.labels.take(rect)
        # and keep labels off the dimension line and its extension lines
        if angle == 0:
            a, b = self.p(p1[0], base[1]), self.p(p2[0], base[1])
        else:
            a, b = self.p(base[0], p1[1]), self.p(base[0], p2[1])
        labels = self.sheet.labels
        labels.segment(a, b)
        for point, end in ((p1, a), (p2, b)):
            start = self.p(*point)
            if math.dist(start, end) > 1.6:
                ux, uy = (end[0] - start[0], end[1] - start[1])
                n = math.hypot(ux, uy)
                labels.segment(
                    (start[0] + ux / n * 1.5, start[1] + uy / n * 1.5),
                    (end[0] + ux / n * 1.5, end[1] + uy / n * 1.5),
                )
        self.sheet.labels.block(
            (
                min(a[0], b[0]) - 0.8,
                min(a[1], b[1]) - 0.8,
                max(a[0], b[0]) + 0.8,
                max(a[1], b[1]) + 0.8,
            )
        )
        return dimension

    def chain(
        self, points: Sequence[Sequence[float]], offset: float, angle: float = 0
    ) -> list[Any]:
        """A chain of dimensions through ``points`` (sorted along the direction)."""
        return [self.dim(a, b, offset, angle) for a, b in itertools.pairwise(points)]

    def reserve(self, points: Iterable[Sequence[float]], grow: float = 0.0) -> None:
        """Keeps labels off the paper box of the real ``points`` (a column, a stair)."""
        pts = [self.p(*p[:2]) for p in points]
        if pts:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            self.sheet.labels.block(
                (min(xs) - grow, min(ys) - grow, max(xs) + grow, max(ys) + grow)
            )

    def inset(self, x: float, y: float, scale: float, origin: Sequence[float] = (0, 0)) -> View:
        """A view inside this one: the real point ``origin`` at this view's point (x, y),
        drawn at ``1:scale`` (a section at 1:25 beside an elevation at 1:50)."""
        inner = View.__new__(View)
        inner.sheet = self.sheet
        inner.spec = ViewSpec("", scale, (origin[0], origin[1], origin[0], origin[1]), None)
        inner.scale = scale
        inner.k = self.sheet.scale / scale
        inner.origin = self.p(x, y)
        inner.box = self.box
        return inner


def tag(entity: Any, **values: Any) -> Any:
    """Attaches ``values`` as XDATA strings (``key=value``) to ``entity``."""
    entity.set_xdata(APP_ID, [(1000, f"{k}={v}") for k, v in values.items()])
    return entity


def read_tags(entity: Any) -> dict[str, str]:
    """The XDATA values :func:`tag` attached."""
    try:
        data = entity.get_xdata(APP_ID)
    except Exception:  # noqa: BLE001 — no XDATA
        return {}
    out = {}
    for code, value in data:
        if code == 1000 and "=" in str(value):
            k, v = str(value).split("=", 1)
            out[k] = v
    return out


# ─────────────────────────────────── packing views onto sheets ───────────────────────────────────


def pack(
    specs: Sequence[ViewSpec], area: Rect, gap: float = 6.0
) -> list[list[tuple[ViewSpec, float, float]]]:
    """Places views row by row (shelves, top to bottom, left to right) into ``area``; a view
    that does not fit starts the next sheet. Returns per sheet the views and their paper
    positions (bottom-left of their boxes). A view larger than the area gets a sheet of its own
    (and overflows it: the caller picks a smaller scale)."""
    x0, y0, x1, y1 = area
    sheets: list[list[tuple[ViewSpec, float, float]]] = [[]]
    cx, top, shelf = x0, y1, 0.0
    for spec in specs:
        w, h = spec.size
        if cx + w > x1 + 1e-6 and cx > x0:
            cx, top, shelf = x0, top - shelf - gap, 0.0
        if top - h < y0 - 1e-6 and sheets[-1]:
            sheets.append([])
            cx, top, shelf = x0, y1, 0.0
        sheets[-1].append((spec, cx, top - h))
        cx += w + gap
        shelf = max(shelf, h)
    return [s for s in sheets if s]


def centred(
    page: list[tuple[ViewSpec, float, float]], area: Rect
) -> list[tuple[ViewSpec, float, float]]:
    """The views of a packed sheet (:func:`pack`) moved together so that their boxes are centred
    in ``area``: a small building's plan in the middle of the sheet, not in its top-left corner.
    Views larger than the area stay where they are."""
    if not page:
        return page
    left = min(x for _, x, _ in page)
    bottom = min(y for _, _, y in page)
    right = max(x + spec.size[0] for spec, x, _ in page)
    top = max(y + spec.size[1] for spec, _, y in page)
    dx = max(0.0, ((area[2] - area[0]) - (right - left)) / 2) + area[0] - left
    dy = max(0.0, ((area[3] - area[1]) - (top - bottom)) / 2) + area[1] - bottom
    if right - left > area[2] - area[0] + 1e-6:
        dx = 0.0
    if top - bottom > area[3] - area[1] + 1e-6:
        dy = 0.0
    return [(spec, x + dx, y + dy) for spec, x, y in page]


def fits(spec: ViewSpec, area: Rect) -> bool:
    w, h = spec.size
    return w <= area[2] - area[0] + 1e-6 and h <= area[3] - area[1] + 1e-6


def drawing_area(size: str) -> Rect:
    """The paper area free for views on a sheet of ``size`` (inside the frame, left of the
    title block)."""
    w, h = paper_size(size)
    return (MARGIN_LEFT + 4, MARGIN + 4, w - MARGIN - TITLE_WIDTH[size.upper()] - 4, h - MARGIN - 4)

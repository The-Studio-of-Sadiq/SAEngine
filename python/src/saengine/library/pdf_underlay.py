"""Architects' PDF drawings as floor-plan underlays: one page's vector linework as DXF.

Architects often send plans as PDF rather than DWG. A PDF printed from a CAD program keeps its
lines as vector paths; this module reads one page's paths (pypdf, BSD-3-Clause) and writes them
as DXF lines and polylines (ezdxf, MIT), which the floor plan shows as an underlay as it shows a
DXF or DWG one. Text on the page becomes DXF text, so room names stay readable.

Coordinates are paper millimetres from the page's lower left corner (the page's /Rotate applied),
so a plan printed at 1:100 has a scale of 100 to the model's mm. The floor plan calibrates the
scale from two points and a known length (``Underlay.scale``); nothing here guesses it.

A scanned page (only images, no paths) has no linework to show or snap to: :func:`convert`
reports it (``vector`` false) instead of an empty drawing.

:func:`convert` writes ``<name>.p<page>.dxf`` and the page's segments (for object snaps) into a
``.pdf-cache`` folder beside the PDF (a computed cache: left out of archives, see
:data:`saengine.project.archive.COMPUTED_PATHS`) and converts again only when the PDF changed.
"""

from __future__ import annotations

import contextlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CACHE_FOLDER = ".pdf-cache"
#: PDF user space units (1/72 in) to mm.
PT = 25.4 / 72
#: Straight pieces a Bézier curve is drawn with.
CURVE_STEPS = 8
#: Form XObjects nest at most this deep (a loop in a broken file stops here).
MAX_DEPTH = 12
#: At most this many segments go to the floor plan for object snaps (the DXF keeps all).
MAX_SNAP_SEGMENTS = 50_000
#: Bumped when the output changes, so older cached copies convert again.
VERSION = 1

Matrix = tuple[float, float, float, float, float, float]
Point = tuple[float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


class PdfError(RuntimeError):
    """The PDF could not be read; the message says why, for the user."""


def multiply(m: Matrix, n: Matrix) -> Matrix:
    """``m`` then ``n`` (PDF's row-vector convention: p' = p · m · n)."""
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (
        a * a2 + b * c2,
        a * b2 + b * d2,
        c * a2 + d * c2,
        c * b2 + d * d2,
        e * a2 + f * c2 + e2,
        e * b2 + f * d2 + f2,
    )


def apply(m: Matrix, x: float, y: float) -> Point:
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def bezier(p0: Point, p1: Point, p2: Point, p3: Point, steps: int = CURVE_STEPS) -> list[Point]:
    """The cubic Bézier from ``p0`` to ``p3`` as ``steps`` straight pieces (``p0`` left out)."""
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        out.append(
            (
                u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
            )
        )
    return out


@dataclass
class PageGeometry:
    """One page's linework in paper mm: open and closed polylines and text."""

    width: float
    height: float
    polylines: list[tuple[list[Point], bool]] = field(default_factory=list)
    texts: list[tuple[str, Point, float, float]] = field(default_factory=list)
    images: int = 0

    @property
    def vector(self) -> bool:
        return bool(self.polylines)

    def segments(self, limit: int = MAX_SNAP_SEGMENTS) -> list[list[float]]:
        """The straight pieces ``[x1, y1, x2, y2]`` (mm, rounded to 0.01) for object snaps."""
        out: list[list[float]] = []
        for points, closed in self.polylines:
            ring = [*points, points[0]] if closed and len(points) > 2 else points
            for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
                if (x1, y1) != (x2, y2):
                    out.append([round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)])
                    if len(out) >= limit:
                        return out
        return out


def _page_matrix(page: Any) -> tuple[Matrix, float, float]:
    """From PDF user space to paper mm with the origin at the lower left of the page as it is
    shown (its /Rotate applied); and the shown width and height in mm."""
    box = page.cropbox if page.get("/CropBox") is not None else page.mediabox
    x0, y0 = float(box.left), float(box.bottom)
    w, h = float(box.width), float(box.height)
    rotate = int(page.get("/Rotate", 0) or 0) % 360
    m = (1.0, 0.0, 0.0, 1.0, -x0, -y0)
    if rotate == 90:  # shown turned clockwise: (x, y) -> (y, w - x)
        m = multiply(m, (0.0, -1.0, 1.0, 0.0, 0.0, w))
        w, h = h, w
    elif rotate == 180:
        m = multiply(m, (-1.0, 0.0, 0.0, -1.0, w, h))
    elif rotate == 270:
        m = multiply(m, (0.0, 1.0, -1.0, 0.0, h, 0.0))
        w, h = h, w
    return multiply(m, (PT, 0.0, 0.0, PT, 0.0, 0.0)), w * PT, h * PT


class _Walker:
    """Reads a content stream's path operators into polylines, following q/Q, cm and forms."""

    def __init__(self, reader: Any, out: PageGeometry) -> None:
        self.reader = reader
        self.out = out

    def run(self, content: Any, resources: Any, ctm: Matrix, depth: int = 0) -> None:
        from pypdf.generic import ContentStream

        if depth > MAX_DEPTH or content is None:
            return
        stream = content if isinstance(content, ContentStream) else ContentStream(content, self.reader)
        stack: list[Matrix] = []
        subpaths: list[tuple[list[Point], bool]] = []
        current: list[Point] = []
        start: Point | None = None

        def finish(closed: bool = False) -> None:
            nonlocal current
            if len(current) >= 2:
                subpaths.append((current, closed))
            current = []

        def last() -> Point:
            return current[-1] if current else (start or (0.0, 0.0))

        for operands, op in stream.operations:
            try:
                args = [float(v) for v in operands] if op in _NUMERIC_OPS else operands
            except (TypeError, ValueError):
                continue
            if op == b"q":
                stack.append(ctm)
            elif op == b"Q":
                if stack:
                    ctm = stack.pop()
            elif op == b"cm" and len(args) == 6:
                ctm = multiply(tuple(args), ctm)  # type: ignore[arg-type]
            elif op == b"m" and len(args) == 2:
                finish()
                start = apply(ctm, *args)
                current = [start]
            elif op == b"l" and len(args) == 2:
                current = current or [last()]
                current.append(apply(ctm, *args))
            elif op in (b"c", b"v", b"y") and len(args) in (4, 6):
                p0 = last()
                current = current or [p0]
                pts = [apply(ctm, args[i], args[i + 1]) for i in range(0, len(args), 2)]
                if op == b"c":
                    p1, p2, p3 = pts
                elif op == b"v":
                    p1, p2, p3 = p0, pts[0], pts[1]
                else:
                    p1, p2, p3 = pts[0], pts[1], pts[1]
                current.extend(bezier(p0, p1, p2, p3))
            elif op == b"h":
                if current:
                    finish(closed=True)
                    current = []
            elif op == b"re" and len(args) == 4:
                finish()
                x, y, w, h = args
                corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
                subpaths.append(([apply(ctm, *p) for p in corners], True))
            elif op in _PAINT_OPS:
                finish(closed=op in (b"s", b"b", b"b*"))
                self.out.polylines.extend(p for p in subpaths if _extent(p[0]) > 0)
                subpaths = []
            elif op == b"n":  # a clipping path: not drawn
                finish()
                subpaths = []
            elif op == b"Do" and operands:
                self._xobject(resources, operands[0], ctm, depth)
            elif op == b"BI":
                self.out.images += 1

    def _xobject(self, resources: Any, name: Any, ctm: Matrix, depth: int) -> None:
        try:
            xobjects = resources["/XObject"].get_object() if resources else None
            ref = xobjects.raw_get(name) if xobjects is not None else None
            xobject = ref.get_object() if ref is not None else None
        except (KeyError, AttributeError, TypeError):
            return
        if xobject is None:
            return
        subtype = xobject.get("/Subtype")
        if subtype == "/Image":
            self.out.images += 1
            return
        if subtype != "/Form":
            return
        matrix = xobject.get("/Matrix")
        form_ctm = multiply(tuple(float(v) for v in matrix), ctm) if matrix else ctm  # type: ignore[arg-type]
        form_resources = xobject.get("/Resources") or resources
        if hasattr(form_resources, "get_object"):
            form_resources = form_resources.get_object()
        self.run(xobject, form_resources, form_ctm, depth + 1)


_NUMERIC_OPS = {b"cm", b"m", b"l", b"c", b"v", b"y", b"re"}
_PAINT_OPS = {b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"}


def _extent(points: list[Point]) -> float:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return max(max(xs) - min(xs), max(ys) - min(ys))


def _open(path: Path) -> Any:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise PdfError(f"{path.name} is password protected; save an unprotected copy")
        return reader
    except PdfReadError as exc:
        raise PdfError(f"{path.name} is not a readable PDF: {exc}") from exc


def page_count(path: str | Path) -> int:
    return len(_open(Path(path)).pages)


def read_page(path: str | Path, page: int = 1) -> PageGeometry:
    """Page ``page`` (from 1) of the PDF as linework in paper mm."""
    reader = _open(Path(path))
    if not 1 <= page <= len(reader.pages):
        raise PdfError(f"{Path(path).name} has {len(reader.pages)} page(s), not a page {page}")
    pdf_page = reader.pages[page - 1]
    to_mm, width, height = _page_matrix(pdf_page)
    out = PageGeometry(width, height)
    resources = pdf_page.get("/Resources")
    if hasattr(resources, "get_object"):
        resources = resources.get_object()
    _Walker(reader, out).run(pdf_page.get_contents(), resources, to_mm)

    def text(content: str, cm: Any, tm: Any, _font: Any, size: float) -> None:
        content = content.strip()
        if not content:
            return
        m = multiply(multiply(tuple(tm), tuple(cm)), to_mm)  # type: ignore[arg-type]
        x, y = apply(m, 0, 0)
        scale = math.hypot(m[2], m[3])
        angle = math.degrees(math.atan2(m[1], m[0]))
        out.texts.append((content, (x, y), max(size * scale, 0.1), angle))

    with contextlib.suppress(Exception):  # text is a help; a font it cannot decode is skipped
        pdf_page.extract_text(visitor_text=text)
    return out


def to_dxf(geometry: PageGeometry) -> str:
    """The page as DXF text (mm), on layers PDF-LINES and PDF-TEXT."""
    import io

    import ezdxf

    doc = ezdxf.new("R2010", units=4)  # 4: millimetres
    doc.layers.add("PDF-LINES")
    doc.layers.add("PDF-TEXT")
    msp = doc.modelspace()
    for points, closed in geometry.polylines:
        if len(points) == 2 and not closed:
            msp.add_line(points[0], points[1], dxfattribs={"layer": "PDF-LINES"})
        else:
            msp.add_lwpolyline(points, close=closed, dxfattribs={"layer": "PDF-LINES"})
    for content, (x, y), size, angle in geometry.texts:
        msp.add_text(
            content,
            height=size,
            rotation=angle,
            dxfattribs={"layer": "PDF-TEXT", "insert": (x, y)},
        )
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue()


@dataclass
class Conversion:
    """One PDF page as DXF: the DXF, the segments to snap to and what the page holds."""

    dxf: Path
    page: int
    pages: int
    vector: bool
    size: tuple[float, float]
    segments: list[list[float]]
    warnings: list[str] = field(default_factory=list)
    cached: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "dxf": str(self.dxf),
            "page": self.page,
            "pages": self.pages,
            "vector": self.vector,
            "size": list(self.size),
            "segments": self.segments,
            "warnings": self.warnings,
            "cached": self.cached,
        }


def _stamp(pdf: Path) -> dict[str, int]:
    stat = pdf.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "version": VERSION}


def convert(pdf: str | Path, page: int = 1, cache: str | Path | None = None) -> Conversion:
    """Page ``page`` of ``pdf`` as DXF in ``cache`` (default ``.pdf-cache`` beside the PDF),
    converted when the cached copy is missing or older than the PDF. Raises :class:`PdfError`."""
    pdf = Path(pdf)
    if not pdf.is_file():
        raise PdfError(f"{pdf.name} does not exist")
    folder = Path(cache) if cache else pdf.parent / CACHE_FOLDER
    dxf = folder / f"{pdf.name}.p{page}.dxf"
    meta = folder / f"{pdf.name}.p{page}.json"
    stamp = _stamp(pdf)
    with contextlib.suppress(OSError, ValueError, TypeError, KeyError):
        known = json.loads(meta.read_text(encoding="utf-8"))
        if known.get("source") == stamp and dxf.is_file():
            return Conversion(
                dxf,
                page,
                int(known["pages"]),
                bool(known["vector"]),
                tuple(known["size"]),  # type: ignore[arg-type]
                list(known["segments"]),
                list(known.get("warnings", [])),
                cached=True,
            )
    pages = page_count(pdf)
    geometry = read_page(pdf, page)
    warnings: list[str] = []
    if not geometry.vector:
        warnings.append(
            f"page {page} of {pdf.name} has no vector linework"
            + (" (it is a scanned image)" if geometry.images else "")
            + ": export the plan from the CAD program as a vector PDF, DXF or DWG"
        )
    segments = geometry.segments()
    if len(segments) >= MAX_SNAP_SEGMENTS:
        warnings.append(
            f"the page has more than {MAX_SNAP_SEGMENTS} lines: object snaps use the first "
            f"{MAX_SNAP_SEGMENTS}"
        )
    folder.mkdir(parents=True, exist_ok=True)
    dxf.write_text(to_dxf(geometry), encoding="utf-8")
    size = (round(geometry.width, 2), round(geometry.height, 2))
    with contextlib.suppress(OSError):
        meta.write_text(
            json.dumps(
                {
                    "source": stamp,
                    "pages": pages,
                    "vector": geometry.vector,
                    "size": size,
                    "segments": segments,
                    "warnings": warnings,
                }
            ),
            encoding="utf-8",
        )
    return Conversion(dxf, page, pages, geometry.vector, size, segments, warnings)

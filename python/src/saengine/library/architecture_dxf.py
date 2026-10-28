"""An architect's DWG/DXF plan adopted into the architecture (``05 Floor Plan/architecture.json``).

Most architects in Bangladesh send a DWG floor plan, not an IFC. :func:`inspect_drawing` lists the
drawing's layers (entity counts, block names) with a light preview for the layer-mapping step;
:func:`import_drawing` reads the layers mapped to walls, doors, windows and room names onto one
story:

- Walls from pairs of parallel lines (and polyline edges) 50 to 600 mm apart: the thickness is
  their distance, matched to the nearest wall type (its total or its core layer within 10 mm) or
  a new type; the centre line runs between them. Pieces of one wall are joined where its face
  lines break at a T-junction or at a door or window, and wall ends are run to the centre line
  of the wall they meet (corners and T-junctions). A single line on a wall layer (1 m or longer,
  not alongside a wall found) is a centre line of the default wall type.
- Doors from the blocks (or loose arcs and lines) on door layers: a swing arc gives the hinge,
  the jamb it closes on (the width) and the side it swings to; two arcs meeting in the middle
  are a double door; a door without an arc is sliding. Windows from the blocks (or loose lines)
  on window layers: their width is their extent along the wall they lie in. Types are matched by
  width within 25 mm, else added (heights are not in a plan: check the new types).
- Rooms from TEXT/MTEXT on room-name layers inside closed walls: the text's name (and number,
  e.g. ``101`` or ``R-101``); sizes (``12'-0" x 14'-0"``) and areas are left out.

The drawing goes onto the plan by its unit ($INSUNITS, or the one given), a drawing point placed
at a plan point (e.g. the grid origin) and a rotation; :func:`placement_from_points` turns two
pairs of points into that placement. A DWG is read through its DXF made by GNU LibreDWG
(:mod:`saengine.library.dwg`, as the floor plan's underlays are).

Each import is recorded in the architecture (:class:`~saengine.library.architecture.DrawingImport`)
with its mapping and the items it made: importing the same file onto the same story again replaces
those items (and the doors and windows in its walls) instead of adding a second copy.
"""

from __future__ import annotations

import contextlib
import math
import re
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from saengine.library import dwg
from saengine.library.architecture import (
    Architecture,
    Room,
    offset_path,
    room_boundary,
)

#: Drawing units in mm.
UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "ft": 304.8, "in": 25.4}
#: $INSUNITS codes of those units.
INSUNITS = {1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m"}
ROLES = ("walls", "doors", "windows", "rooms", "ignore")

#: Two parallel lines this far apart [mm] are the faces of a wall.
MIN_THICKNESS = 50.0
MAX_THICKNESS = 600.0
#: Lines within this angle [°] are parallel.
PARALLEL_DEGREES = 1.0
#: Face lines must run side by side at least this far [mm] to make a wall.
MIN_OVERLAP = 100.0
#: Geometric tolerance [mm]: joins, bands around walls, collinear pieces.
TOLERANCE = 25.0
#: A gap in a wall this wide or less [mm] is bridged when a door or window sits in it.
MAX_OPENING = 4000.0
#: A single line on a wall layer this long or more [mm] is a wall centre line.
MIN_CENTRE_LINE = 1000.0
#: Height of walls on the top story [mm] (no story above to rise to).
DEFAULT_HEIGHT = 3000.0
#: Walls shorter than this [mm] are dropped.
MIN_WALL = 100.0
#: Types are matched within these [mm].
WALL_TYPE_TOLERANCE = 10.0
OPENING_TYPE_TOLERANCE = 25.0
#: Door swings sweep about a quarter turn.
SWING_DEGREES = (60.0, 120.0)
#: The preview keeps at most this many points.
PREVIEW_POINTS = 60000
#: Blocks inside blocks are followed this deep.
MAX_NESTING = 4

_SIZE = re.compile(r"\d\s*['′\"″]?\s*(?:-?\s*\d+\s*[\"″]?)?\s*[xX×]\s*\d")
_AREA = re.compile(r"\b(?:sft|sq\.?\s*ft|sqft|sq\.?\s*m|sqm|m2|m²|area)\b", re.IGNORECASE)
_NUMBER = re.compile(r"(?:[A-Z]{1,2}-?)?\d{1,4}[A-Z]?(?:-\d{1,3})?")
_LEADING_NUMBER = re.compile(r"^((?:[A-Z]{1,2}-)?\d{1,4}[A-Z]?)[\s.:)-]+(.+)$")

Vec = tuple[float, float]


# ───────────────────────────── reading ─────────────────────────────


@contextlib.contextmanager
def _opened(path: str | Path) -> Iterator[tuple[Any, list[str]]]:
    """The drawing at ``path`` (a DWG through its DXF) and the converter's warnings."""
    import ezdxf
    from ezdxf import recover

    path = Path(path)
    warnings: list[str] = []
    source = path
    if dwg.is_dwg(path):
        cache = Path(tempfile.gettempdir()) / "saengine-dwg-import"
        conversion = dwg.convert(path, cache)
        warnings += conversion.warnings
        source = conversion.dxf
    try:
        doc = ezdxf.readfile(source)
    except ezdxf.DXFStructureError:
        doc, auditor = recover.readfile(source)
        if auditor.has_errors:
            warnings.append(f"{path.name}: {len(auditor.errors)} errors in the file were repaired")
    yield doc, warnings


@dataclass
class _Item:
    """One drawn thing, in drawing units, on the layer it is mapped by."""

    kind: str  # line, arc, text, insert, other
    layer: str
    points: list[Vec] = field(default_factory=list)
    # Arcs: centre, radius, start and end points (counter-clockwise from start to end).
    centre: Vec | None = None
    radius: float = 0.0
    text: str = ""
    # Inserts on door or window layers: the block's own items.
    parts: list[_Item] = field(default_factory=list)
    block: str = ""


def _xy(v: Any) -> Vec:
    return (float(v[0]), float(v[1]))


def _arc_item(entity: Any, layer: str) -> _Item | None:
    try:
        ocs = entity.ocs()
        centre = _xy(ocs.to_wcs(entity.dxf.center))
        points = [_xy(p) for p in entity.flattening(entity.dxf.radius / 20 or 1)]
    except (AttributeError, ValueError, ZeroDivisionError):
        return None
    if len(points) < 2:
        return None
    return _Item("arc", layer, points, centre, float(entity.dxf.radius))


def _items(entities: Iterable[Any], layer_of: Any, opening_layers: set[str], depth: int = 0):
    """Lines, arcs, texts and opening blocks of ``entities`` (blocks elsewhere are opened)."""
    for entity in entities:
        kind = entity.dxftype()
        layer = layer_of(entity)
        if kind == "LINE":
            yield _Item("line", layer, [_xy(entity.dxf.start), _xy(entity.dxf.end)])
        elif kind in ("LWPOLYLINE", "POLYLINE"):
            if kind == "POLYLINE" and (entity.is_polygon_mesh or entity.is_poly_face_mesh):
                yield _Item("other", layer)
                continue
            for part in entity.virtual_entities():
                if part.dxftype() == "LINE":
                    yield _Item("line", layer, [_xy(part.dxf.start), _xy(part.dxf.end)])
                elif part.dxftype() == "ARC":
                    arc = _arc_item(part, layer)
                    if arc is not None:
                        yield arc
        elif kind == "ARC":
            arc = _arc_item(entity, layer)
            if arc is not None:
                yield arc
        elif kind in ("TEXT", "MTEXT", "ATTRIB"):
            text = entity.plain_text() if kind != "ATTRIB" else entity.dxf.text
            yield _Item("text", layer, [_text_point(entity)], text=str(text or ""))
        elif kind == "INSERT":
            if depth >= MAX_NESTING:
                yield _Item("other", layer)
                continue
            try:
                parts = list(entity.virtual_entities())
            except Exception:  # noqa: BLE001 - a block ezdxf cannot explode is skipped
                yield _Item("other", layer)
                continue

            def inner(e: Any, outer: str = layer) -> str:
                own = e.dxf.layer
                return outer if own in ("0", "") else own

            if layer in opening_layers:
                items = list(_items(parts, inner, opening_layers, depth + 1))
                yield _Item("insert", layer, block=entity.dxf.name, parts=items)
            else:
                yield from _items(parts, inner, opening_layers, depth + 1)
            for attrib in entity.attribs:
                yield _Item("text", layer, [_text_point(attrib)], text=str(attrib.dxf.text or ""))
        elif kind in ("CIRCLE", "ELLIPSE", "SPLINE"):
            try:
                points = [_xy(p) for p in entity.flattening(_flat_distance(entity))]
            except Exception:  # noqa: BLE001 - only shown in the preview
                points = []
            yield _Item("other", layer, points)
        else:
            yield _Item("other", layer)


def _flat_distance(entity: Any) -> float:
    if entity.dxftype() == "CIRCLE":
        return max(entity.dxf.radius / 20, 1e-6)
    return 1.0


def _text_point(entity: Any) -> Vec:
    """The middle of a text, else its insertion point."""
    from ezdxf import bbox

    with contextlib.suppress(Exception):
        box = bbox.extents([entity])
        if box.has_data:
            return _xy(box.center)
    return _xy(entity.dxf.insert)


def _layer(entity: Any) -> str:
    return str(entity.dxf.layer)


def _guess_unit(doc: Any, extents: tuple[Vec, Vec] | None) -> tuple[str, bool]:
    """The drawing's unit and whether it is a guess (no $INSUNITS): from the drawing's size,
    for a building of 5 to 100 m."""
    code = int(doc.header.get("$INSUNITS", 0) or 0)
    if code in INSUNITS:
        return INSUNITS[code], False
    if extents is None:
        return "mm", True
    (x0, y0), (x1, y1) = extents
    size = max(x1 - x0, y1 - y0)
    return ("mm" if size >= 4000 else "in" if size >= 400 else "m"), True


def inspect_drawing(path: str | Path) -> dict[str, Any]:
    """The drawing's layers (entity counts, block names), unit, extents and a preview, for the
    layer-mapping step (drawing units):

    ``{"layers": [{"name", "counts": {lines, arcs, blocks, texts, other}, "total", "blocks",
    "texts"}], "unit", "unitGuessed", "insunits", "extents", "preview": {layer: [[x, y, x, y,
    ...], ...]}, "labels": [{"layer", "text", "at"}], "warnings"}``.
    """
    with _opened(path) as (doc, warnings):
        msp = doc.modelspace()
        layers: dict[str, dict[str, Any]] = {}
        preview: dict[str, list[list[float]]] = {}
        labels: list[dict[str, Any]] = []
        xs: list[float] = []
        ys: list[float] = []

        def entry(name: str) -> dict[str, Any]:
            return layers.setdefault(
                name,
                {
                    "name": name,
                    "counts": {"lines": 0, "arcs": 0, "blocks": 0, "texts": 0, "other": 0},
                    "blocks": {},
                    "texts": [],
                },
            )

        def shape(layer: str, points: list[Vec]) -> None:
            if len(points) >= 2:
                preview.setdefault(layer, []).append([c for p in points for c in p])
                xs.extend(p[0] for p in points)
                ys.extend(p[1] for p in points)

        for layer in doc.layers:
            entry(layer.dxf.name)
        for insert in msp.query("INSERT"):
            info = entry(insert.dxf.layer)
            info["counts"]["blocks"] += 1
            info["blocks"][insert.dxf.name] = info["blocks"].get(insert.dxf.name, 0) + 1
        for item in _items(msp, _layer, set()):
            info = entry(item.layer)
            counts = info["counts"]
            counts[{"line": "lines", "arc": "arcs", "text": "texts"}.get(item.kind, "other")] += 1
            if item.kind == "text":
                if item.text.strip():
                    if len(info["texts"]) < 5:
                        info["texts"].append(item.text.strip()[:40])
                    labels.append({"layer": item.layer, "text": item.text, "at": item.points[0]})
                    xs.append(item.points[0][0])
                    ys.append(item.points[0][1])
            else:
                shape(item.layer, item.points)
        extents = ((min(xs), min(ys)), (max(xs), max(ys))) if xs else None
        unit, guessed = _guess_unit(doc, extents)
        insunits = int(doc.header.get("$INSUNITS", 0) or 0)
    _thin(preview)
    out_layers = []
    for info in layers.values():
        total = sum(info["counts"].values())
        blocks = sorted(info["blocks"].items(), key=lambda kv: -kv[1])
        out_layers.append({**info, "total": total, "blocks": [name for name, _ in blocks[:5]]})
    out_layers.sort(key=lambda info: (info["total"] == 0, info["name"].lower()))
    return {
        "layers": out_layers,
        "unit": unit,
        "unitGuessed": guessed,
        "insunits": insunits,
        "extents": [list(extents[0]), list(extents[1])] if extents else None,
        "preview": preview,
        "labels": labels[:500],
        "warnings": warnings,
    }


def _thin(preview: dict[str, list[list[float]]]) -> None:
    """Keeps the preview under :data:`PREVIEW_POINTS` points (dropping every other shape)."""
    count = sum(len(s) // 2 for shapes in preview.values() for s in shapes)
    while count > PREVIEW_POINTS:
        for name, shapes in preview.items():
            preview[name] = shapes[::2]
        count = sum(len(s) // 2 for shapes in preview.values() for s in shapes)


# ───────────────────────────── placement ─────────────────────────────


@dataclass(frozen=True)
class Placement:
    """Drawing units to plan mm: ``base`` (drawing units) lands at ``at`` (mm), turned
    ``rotation`` degrees counter-clockwise about it."""

    scale: float = 1.0
    base: Vec = (0.0, 0.0)
    at: Vec = (0.0, 0.0)
    rotation: float = 0.0

    def __call__(self, p: Vec) -> Vec:
        x, y = (p[0] - self.base[0]) * self.scale, (p[1] - self.base[1]) * self.scale
        c, s = math.cos(math.radians(self.rotation)), math.sin(math.radians(self.rotation))
        return (self.at[0] + c * x - s * y, self.at[1] + s * x + c * y)


def placement_from_points(
    unit: str, first: tuple[Vec, Vec], second: tuple[Vec, Vec] | None = None, rotation: float = 0
) -> tuple[Placement, float | None]:
    """The placement putting drawing point ``first[0]`` at plan point ``first[1]``, turned so the
    drawing's direction to ``second[0]`` runs towards ``second[1]`` (else by ``rotation``); and
    how much the two pairs' distances differ (a wrong unit shows here), or None."""
    scale = UNITS[unit]
    mismatch = None
    if second is not None:
        (b0, a0), (b1, a1) = first, second
        drawn = math.atan2(b1[1] - b0[1], b1[0] - b0[0])
        target = math.atan2(a1[1] - a0[1], a1[0] - a0[0])
        rotation = math.degrees(target - drawn)
        length = math.dist(b0, b1) * scale
        if length > 0:
            mismatch = math.dist(a0, a1) / length - 1
    rotation = (rotation + 180) % 360 - 180
    return Placement(scale, first[0], first[1], round(rotation, 6)), mismatch


# ───────────────────────────── geometry ─────────────────────────────


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1])


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _cross(a: Vec, b: Vec) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _unit(a: Vec, b: Vec) -> Vec:
    length = math.dist(a, b) or 1.0
    return ((b[0] - a[0]) / length, (b[1] - a[1]) / length)


def _at(a: Vec, u: Vec, s: float, v: float = 0.0) -> Vec:
    return (a[0] + u[0] * s - u[1] * v, a[1] + u[1] * s + u[0] * v)


@dataclass
class _Piece:
    """A straight wall: its centre line from ``a`` to ``b`` and its thickness [mm]."""

    a: Vec
    b: Vec
    thickness: float
    centre_line: bool = False  # drawn as one line (the default type), not a pair of faces
    id: str = ""

    @property
    def u(self) -> Vec:
        return _unit(self.a, self.b)

    @property
    def length(self) -> float:
        return math.dist(self.a, self.b)

    def local(self, p: Vec) -> tuple[float, float]:
        """``p`` along the piece from ``a`` and to its left."""
        d = _sub(p, self.a)
        u = self.u
        return _dot(d, u), _cross(u, d)

    def band(self, p: Vec, reach: float = TOLERANCE) -> bool:
        s, v = self.local(p)
        return -reach <= s <= self.length + reach and abs(v) <= self.thickness / 2 + reach


def _parallel(u: Vec, w: Vec, degrees: float = PARALLEL_DEGREES) -> bool:
    return abs(_cross(u, w)) <= math.sin(math.radians(degrees))


def _intervals_minus(free: list[tuple[float, float]], cut: tuple[float, float]):
    out = []
    for s0, s1 in free:
        if cut[1] <= s0 or cut[0] >= s1:
            out.append((s0, s1))
            continue
        if cut[0] > s0:
            out.append((s0, cut[0]))
        if cut[1] < s1:
            out.append((cut[1], s1))
    return out


def _intervals_and(free: list[tuple[float, float]], span: tuple[float, float]):
    return [
        (max(s0, span[0]), min(s1, span[1]))
        for s0, s1 in free
        if min(s1, span[1]) - max(s0, span[0]) > 0
    ]


def _pair_faces(segments: list[tuple[Vec, Vec]]) -> tuple[list[_Piece], list[int]]:
    """Walls from pairs of parallel face lines, nearest pairs first; and the segments that
    paired with none."""
    n = len(segments)
    lines = []
    bins: dict[int, list[int]] = {}
    nbins = int(180 / PARALLEL_DEGREES)
    for i, (a, b) in enumerate(segments):
        u = _unit(a, b)
        angle = math.degrees(math.atan2(u[1], u[0])) % 180
        if angle >= 180 - 1e-9:
            angle = 0.0
        k = int(angle / PARALLEL_DEGREES) % nbins
        lines.append((a, b, u, math.dist(a, b)))
        bins.setdefault(k, []).append(i)
    candidates = []
    for i in range(n):
        a, b, u, length = lines[i]
        k = int((math.degrees(math.atan2(u[1], u[0])) % 180) / PARALLEL_DEGREES) % nbins
        for kk in (k - 1, k, k + 1):
            for j in bins.get(kk % nbins, ()):
                if j <= i:
                    continue
                aj, bj, uj, _ = lines[j]
                if not _parallel(u, uj):
                    continue
                d0, d1 = _cross(u, _sub(aj, a)), _cross(u, _sub(bj, a))
                if abs(d0 - d1) > 5 or (d0 > 0) != (d1 > 0):
                    continue
                d = (abs(d0) + abs(d1)) / 2
                if not MIN_THICKNESS <= d <= MAX_THICKNESS:
                    continue
                s0, s1 = sorted((_dot(_sub(aj, a), u), _dot(_sub(bj, a), u)))
                overlap = (max(0.0, s0), min(length, s1))
                if overlap[1] - overlap[0] < MIN_OVERLAP:
                    continue
                candidates.append((d, -(overlap[1] - overlap[0]), i, j, overlap, (d0 + d1) / 2))
    candidates.sort()
    free = [[(0.0, line[3])] for line in lines]
    paired = [False] * n
    pieces: list[_Piece] = []
    for d, _, i, j, overlap, side in candidates:
        a, _, u, _ = lines[i]
        aj, _, uj, _ = lines[j]
        # j's free intervals on i's axis.
        flip = _dot(u, uj) < 0
        j_origin = _dot(_sub(aj, a), u)
        on_i = [tuple(sorted(j_origin + (-s if flip else s) for s in span)) for span in free[j]]
        spans = _intervals_and(free[i], overlap)
        spans = [s for span in on_i for s in _intervals_and(spans, span)]  # type: ignore[arg-type]
        for s0, s1 in spans:
            if s1 - s0 < MIN_OVERLAP:
                continue
            piece = _Piece(_at(a, u, s0, side / 2), _at(a, u, s1, side / 2), d)
            free[i] = _intervals_minus(free[i], (s0, s1))
            j_span = tuple(
                sorted(
                    ((s0 - j_origin) * (-1 if flip else 1), (s1 - j_origin) * (-1 if flip else 1))
                )
            )
            free[j] = _intervals_minus(free[j], j_span)  # type: ignore[arg-type]
            paired[i] = paired[j] = True
            # A wall drawn with its plaster lines too: keep the first pair found (the nearest).
            middle = ((piece.a[0] + piece.b[0]) / 2, (piece.a[1] + piece.b[1]) / 2)
            if any(_parallel(q.u, piece.u) and q.band(middle, 0) for q in pieces):
                continue
            pieces.append(piece)
    return pieces, [i for i in range(n) if not paired[i]]


def _collinear(p: _Piece, q: _Piece) -> bool:
    return (
        _parallel(p.u, q.u)
        and abs(p.local(q.a)[1]) <= 10
        and abs(p.local(q.b)[1]) <= 10
        and abs(p.thickness - q.thickness) <= 10
        and p.centre_line == q.centre_line
    )


def _merge(p: _Piece, q: _Piece) -> _Piece:
    u = p.u
    spans = [p.local(x)[0] for x in (p.a, p.b, q.a, q.b)]
    s0, s1 = min(spans), max(spans)
    weight = p.length / ((p.length + q.length) or 1)
    thickness = p.thickness * weight + q.thickness * (1 - weight)
    return _Piece(_at(p.a, u, s0), _at(p.a, u, s1), thickness, p.centre_line, p.id)


def _join_collinear(pieces: list[_Piece], bridge: Any) -> list[_Piece]:
    """Collinear pieces of one wall made one: overlapping or touching, or across a gap that
    ``bridge(p, s0, s1)`` accepts (``s0``..``s1`` along ``p``)."""
    merged = True
    while merged:
        merged = False
        for i, p in enumerate(pieces):
            for j in range(i + 1, len(pieces)):
                q = pieces[j]
                if not _collinear(p, q):
                    continue
                qs = sorted((p.local(q.a)[0], p.local(q.b)[0]))
                if qs[0] <= p.length + 1 and qs[1] >= -1:
                    gap = None
                elif qs[0] > p.length:
                    gap = (p.length, qs[0])
                else:
                    gap = (qs[1], 0.0)
                if gap is not None and not (gap[1] - gap[0] <= MAX_OPENING and bridge(p, *gap)):
                    continue
                pieces[i] = _merge(p, q)
                del pieces[j]
                merged = True
                break
            if merged:
                break
    return pieces


def _join_ends(pieces: list[_Piece]) -> None:
    """Each wall end run to (or trimmed back to) the centre line of the wall it meets."""
    ends: list[tuple[int, int, Vec]] = []
    for i, p in enumerate(pieces):
        for end in (0, 1):
            e = p.a if end == 0 else p.b
            out = (-p.u[0], -p.u[1]) if end == 0 else p.u
            best: tuple[float, Vec] | None = None
            for j, q in enumerate(pieces):
                if j == i or _parallel(p.u, q.u, 5):
                    continue
                denom = _cross(out, q.u)
                if abs(denom) < 1e-9:
                    continue
                # e + out * s on q's line.
                s = _cross(_sub(q.a, e), q.u) / denom
                reach = q.thickness / 2 + TOLERANCE
                if not -reach <= s <= reach:
                    continue
                x = _at(e, out, s)
                along = q.local(x)[0]
                if (
                    not -(p.thickness / 2 + TOLERANCE)
                    <= along
                    <= q.length + p.thickness / 2 + TOLERANCE
                ):
                    continue
                if best is None or abs(s) < abs(best[0]):
                    best = (s, x)
            if best is not None:
                ends.append((i, end, best[1]))
    for i, end, x in ends:
        if end == 0:
            pieces[i].a = x
        else:
            pieces[i].b = x


# ───────────────────────────── openings ─────────────────────────────


@dataclass
class _Opening:
    kind: str  # doors, windows
    label: str
    points: list[Vec]
    arcs: list[_Item]


def _cluster(items: list[_Item]) -> list[list[_Item]]:
    """Loose lines and arcs grouped where their extents touch: one door or window each."""
    boxes = []
    for item in items:
        xs = [p[0] for p in item.points]
        ys = [p[1] for p in item.points]
        boxes.append(
            (min(xs) - TOLERANCE, min(ys) - TOLERANCE, max(xs) + TOLERANCE, max(ys) + TOLERANCE)
        )
    parent = list(range(len(items)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = boxes[i], boxes[j]
            if a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]:
                parent[root(i)] = root(j)
    groups: dict[int, list[_Item]] = {}
    for i, item in enumerate(items):
        groups.setdefault(root(i), []).append(item)
    return list(groups.values())


def _swing(arc: _Item) -> tuple[Vec, Vec, Vec] | None:
    """A door swing: its hinge (the arc's centre) and its two ends, or None for other arcs."""
    if arc.centre is None or len(arc.points) < 2:
        return None
    first, last = arc.points[0], arc.points[-1]
    sweep = abs(
        math.degrees(
            math.atan2(
                _cross(_sub(first, arc.centre), _sub(last, arc.centre)),
                _dot(_sub(first, arc.centre), _sub(last, arc.centre)),
            )
        )
    )
    if not SWING_DEGREES[0] <= sweep <= SWING_DEGREES[1]:
        return None
    return arc.centre, first, last


# ───────────────────────────── rooms ─────────────────────────────


def room_label(text: str) -> tuple[str, str] | None:
    """A room's name and number from its text (``BED ROOM-1``, ``101 KITCHEN``, ``TOILET\\nT-1``),
    leaving out sizes and areas; None when the text holds no name."""
    lines = [" ".join(line.split()) for line in re.split(r"[\r\n]+", text)]
    names: list[str] = []
    number = ""
    for line in lines:
        if not line or _SIZE.search(line) or _AREA.search(line):
            continue
        if _NUMBER.fullmatch(line):
            number = number or line
            continue
        lead = _LEADING_NUMBER.match(line)
        if lead and not names:
            number = number or lead.group(1)
            line = lead.group(2)
        names.append(line)
    if not names or not re.search(r"[A-Za-zঀ-৿]", " ".join(names)):
        return None
    return " ".join(names), number


# ───────────────────────────── import ─────────────────────────────


def import_drawing(
    path: str | Path,
    arch: Architecture,
    elevations: dict[str, float],
    options: dict[str, Any],
) -> tuple[Architecture, dict[str, Any]]:
    """Adopts the drawing at ``path`` into ``arch`` on ``options["story"]``.

    ``options``: ``layers`` ({layer: role}), ``unit``, ``base``/``at``/``rotation`` (or
    ``align``: ``{"base", "at"}``, a second pair of points), ``source`` (the file's name as
    recorded), ``wallType`` (for centre lines). Returns the new architecture and the summary
    ``{"adopted": {kind: count}, "skipped": [why], "notes": [...], "replaced": n}``.
    """
    with _opened(path) as (doc, warnings):
        importer = _Importer(arch, elevations, options, warnings)
        layers = importer.layer_roles
        opening_layers = {name for name, role in layers.items() if role in ("doors", "windows")}
        items = list(_items(doc.modelspace(), _layer, opening_layers))
    return importer.run(items)


class _Importer:
    def __init__(
        self,
        arch: Architecture,
        elevations: dict[str, float],
        options: dict[str, Any],
        warnings: list[str],
    ) -> None:
        self.story = str(options.get("story") or "")
        if self.story not in elevations:
            raise ValueError(f"no story '{self.story}' in the floor plan")
        self.elevations = elevations
        self.source = str(options.get("source") or "drawing")
        self.layer_roles: dict[str, str] = {
            str(k): str(v) for k, v in (options.get("layers") or {}).items() if v in ROLES
        }
        self.unit = str(options.get("unit") or "mm")
        if self.unit not in UNITS:
            raise ValueError(f"unknown unit '{self.unit}'")
        base = tuple(options.get("base") or (0, 0))
        at = tuple(options.get("at") or (0, 0))
        align = options.get("align")
        second = (tuple(align["base"]), tuple(align["at"])) if align else None
        self.place, mismatch = placement_from_points(
            self.unit,
            (base, at),
            second,
            float(options.get("rotation") or 0),  # type: ignore[arg-type]
        )
        self.data = arch.model_dump(mode="json", by_alias=True, exclude_none=True)
        self.adopted = {"walls": 0, "doors": 0, "windows": 0, "rooms": 0, "types": 0}
        self.skipped: list[str] = []
        self.notes: list[str] = list(warnings)
        if mismatch is not None and abs(mismatch) > 0.01:
            self.notes.append(
                f"The two drawing points are {mismatch:+.1%} apart from the plan points: check "
                "the unit."
            )
        self.default_wall_type = options.get("wallType")
        # Walls rise to the next story; on the top story they get a height.
        level = elevations[self.story]
        self.height = None if any(e > level for e in elevations.values()) else DEFAULT_HEIGHT
        if self.height is not None:
            self.notes.append(
                f"No story above {self.story}: the walls are {DEFAULT_HEIGHT:.0f} mm high."
            )
        self.replaced = self.remove_earlier()
        self.used = {
            i["id"]
            for key in ("walls", "doors", "windows", "rooms", "separators")
            for i in self.data[key]
        }
        self.made: list[str] = []

    # ── earlier import ──

    def remove_earlier(self) -> int:
        imports = self.data.get("imports", [])
        earlier = [
            r for r in imports if _same_file(r["file"], self.source) and r["story"] == self.story
        ]
        if not earlier:
            return 0
        made = {i for r in earlier for i in r.get("items", [])}
        walls = {w["id"] for w in self.data["walls"] if w["id"] in made}
        removed = 0
        own_openings = 0
        for key in ("walls", "doors", "windows", "rooms", "separators"):
            kept = []
            for item in self.data[key]:
                hosted = key in ("doors", "windows") and item.get("wall") in walls
                if item["id"] in made or hosted:
                    removed += 1
                    if item["id"] not in made:
                        own_openings += 1
                    continue
                kept.append(item)
            self.data[key] = kept
        self.data["imports"] = [r for r in imports if r not in earlier]
        if own_openings:
            self.notes.append(
                f"{own_openings} doors and windows added by hand in the walls of the earlier "
                "import went with them."
            )
        return removed

    def new_id(self, prefix: str) -> str:
        n = 1
        while f"{prefix}{n}" in self.used:
            n += 1
        self.used.add(f"{prefix}{n}")
        self.made.append(f"{prefix}{n}")
        return f"{prefix}{n}"

    # ── run ──

    def run(self, items: list[_Item]) -> tuple[Architecture, dict[str, Any]]:
        role = self.layer_roles
        mapped = {name for name, r in role.items() if r != "ignore"}
        if not mapped:
            raise ValueError("no layer is mapped to walls, doors, windows or room names")
        place = self.place
        segments: list[tuple[Vec, Vec]] = []
        wall_arcs: list[_Item] = []
        openings: list[_Opening] = []
        loose: dict[str, list[_Item]] = {"doors": [], "windows": []}
        texts: list[_Item] = []
        others: dict[str, int] = {}
        for item in items:
            r = role.get(item.layer, "ignore")
            if r == "ignore":
                continue
            item = _placed(item, place)
            if r == "walls":
                if item.kind == "line":
                    if math.dist(*item.points) >= 1:
                        segments.append((item.points[0], item.points[1]))
                elif item.kind == "arc":
                    wall_arcs.append(item)
                elif item.kind != "text":
                    others[item.layer] = others.get(item.layer, 0) + 1
            elif r in ("doors", "windows"):
                if item.kind == "insert":
                    parts = [p for p in item.parts if p.kind in ("line", "arc") and p.points]
                    if not parts:
                        self.skipped.append(f"{_kind(r)} block {item.block}: no lines in it")
                        continue
                    openings.append(
                        _Opening(
                            r,
                            f"{_kind(r)} block {item.block}",
                            [p for part in parts for p in part.points],
                            [p for p in parts if p.kind == "arc"],
                        )
                    )
                elif item.kind in ("line", "arc"):
                    loose[r].append(item)
            elif r == "rooms" and item.kind == "text":
                texts.append(item)
        for kind, group in loose.items():
            for cluster in _cluster(group):
                openings.append(
                    _Opening(
                        kind,
                        f"{_kind(kind)} lines near "
                        f"({cluster[0].points[0][0]:.0f}, {cluster[0].points[0][1]:.0f})",
                        [p for item in cluster for p in item.points],
                        [item for item in cluster if item.kind == "arc"],
                    )
                )
        # Door swings drawn on a wall layer: doors when they sit in a gap of a wall.
        swings_on_walls = [
            _Opening(
                "doors",
                f"Door arc near ({a.points[0][0]:.0f}, {a.points[0][1]:.0f})",
                a.points,
                [a],
            )
            for a in wall_arcs
            if _swing(a) is not None
        ]
        curved = len(wall_arcs) - len(swings_on_walls)
        if curved:
            self.notes.append(
                f"{curved} arcs on wall layers not read: curved walls are not imported."
            )
        for layer, count in sorted(others.items()):
            self.notes.append(
                f"{count} other entities on {layer} (circles, hatches, ...) not read."
            )

        pieces = self.walls(segments, openings + swings_on_walls)
        placed_doors = self.openings(pieces, openings, swings_on_walls)
        arch = Architecture.model_validate(self.data)
        self.rooms(arch, texts)
        if not placed_doors and not pieces and not texts:
            self.notes.append("Nothing was found on the mapped layers.")
        self.data.setdefault("imports", []).append(
            {
                "file": self.source,
                "story": self.story,
                "layers": self.layer_roles,
                "unit": self.unit,
                "base": [round(v, 6) for v in self.place.base],
                "at": [round(v, 3) for v in self.place.at],
                "rotation": self.place.rotation,
                "items": self.made,
            }
        )
        arch = Architecture.model_validate(self.data)
        summary = {
            "adopted": self.adopted,
            "skipped": self.skipped,
            "notes": self.notes,
            "replaced": self.replaced,
        }
        return arch, summary

    # ── walls ──

    def walls(self, segments: list[tuple[Vec, Vec]], openings: list[_Opening]) -> list[_Piece]:
        pieces, single = _pair_faces(segments)
        pieces = _join_collinear(pieces, lambda p, s0, s1: False)

        def bridged(p: _Piece, s0: float, s1: float) -> bool:
            def inside(x: Vec) -> bool:
                s, v = p.local(x)
                return (
                    s0 - TOLERANCE <= s <= s1 + TOLERANCE and abs(v) <= p.thickness / 2 + TOLERANCE
                )

            if any(sum(inside(x) for x in o.points) >= 2 for o in openings):
                return True
            # A T-junction: another wall ends in the gap.
            if s1 - s0 <= MAX_THICKNESS + 2 * TOLERANCE:
                return any(
                    not _parallel(p.u, q.u, 5) and (inside(q.a) or inside(q.b)) for q in pieces
                )
            return False

        pieces = _join_collinear(pieces, bridged)
        default = self.centre_line_type()
        thickness = self.type_thickness(default) if default else 0
        loose_lines = 0
        for i in single:
            a, b = segments[i]
            if math.dist(a, b) < MIN_CENTRE_LINE:
                continue
            middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if any(q.band(middle) for q in pieces):
                continue
            if not default:
                loose_lines += 1
                continue
            pieces.append(_Piece(a, b, thickness, centre_line=True))
        if loose_lines:
            self.skipped.append(f"{loose_lines} single lines on wall layers: no wall type for them")
        pieces = _join_collinear(pieces, lambda p, s0, s1: False)
        _join_ends(pieces)
        kept = []
        short = 0
        for piece in pieces:
            if piece.length < MIN_WALL:
                short += 1
                continue
            kept.append(piece)
            type_id = default if piece.centre_line else self.wall_type(piece.thickness)
            wall_type = next(t for t in self.data["wallTypes"] if t["id"] == type_id)
            centre = [piece.a, piece.b]
            half = sum(layer["thickness"] for layer in wall_type["layers"]) / 2
            line = wall_type.get("locationLine", "center")
            shift = {"center": 0.0, "left": -half, "right": half}[line]
            path = offset_path([list(p) for p in centre], -shift)
            piece.id = self.new_id("AW")
            record: dict[str, Any] = {
                "id": piece.id,
                "type": type_id,
                "base": self.story,
                "path": [[round(x, 1), round(y, 1)] for x, y in path],
            }
            if self.height is not None:
                record["height"] = self.height
            self.data["walls"].append(record)
            self.adopted["walls"] += 1
        if short:
            self.skipped.append(f"{short} wall pieces shorter than {MIN_WALL:.0f} mm")
        return kept

    def centre_line_type(self) -> str | None:
        """The type of walls drawn as one line: the one asked for, else the thinnest."""
        types = {t["id"]: t for t in self.data["wallTypes"]}
        if self.default_wall_type in types:
            return str(self.default_wall_type)
        return min(types, key=self.type_thickness) if types else None

    def type_thickness(self, type_id: str) -> float:
        wall_type = next(t for t in self.data["wallTypes"] if t["id"] == type_id)
        return float(sum(layer["thickness"] for layer in wall_type["layers"]))

    def wall_type(self, thickness: float) -> str:
        best: tuple[float, str] | None = None
        for t in self.data["wallTypes"]:
            layers = [layer["thickness"] for layer in t["layers"]]
            error = min(abs(sum(layers) - thickness), abs(max(layers) - thickness))
            if error <= WALL_TYPE_TOLERANCE and (best is None or error < best[0]):
                best = (error, t["id"])
        if best is not None:
            return best[1]
        size = round(thickness)
        type_id = _unique(f"IW{size}", {t["id"] for t in self.data["wallTypes"]})
        self.data["wallTypes"].append(
            {
                "id": type_id,
                "name": f"Wall {size} mm (imported)",
                "layers": [{"material": "Brick", "thickness": float(size), "unitWeight": 18.85}],
            }
        )
        self.adopted["types"] += 1
        self.notes.append(
            f"Wall type {type_id}: a new type of one brick layer {size} mm thick; check its layers."
        )
        return type_id

    # ── doors and windows ──

    def openings(
        self, pieces: list[_Piece], openings: list[_Opening], swings: list[_Opening]
    ) -> int:
        """Places the doors and windows; how many."""
        placed = 0
        for opening in openings:
            placed += self.opening(pieces, opening, report=True)
        for swing in swings:
            placed += self.opening(pieces, swing, report=False)
        return placed

    def opening(self, pieces: list[_Piece], opening: _Opening, report: bool) -> int:
        """Places the door(s) or window of ``opening``; how many."""
        found = self.doors_by_swing(pieces, opening) if opening.kind == "doors" else []
        if not found and report:
            extent = self.by_extent(pieces, opening)
            found = [extent] if extent is not None else []
        if not found:
            if report:
                self.skipped.append(f"{opening.label}: not in a wall")
            return 0
        placed = 0
        for piece, s0, s1, style, flip in found:
            width = s1 - s0
            if width < 300:
                if report:
                    self.skipped.append(f"{opening.label}: only {width:.0f} mm wide along its wall")
                continue
            if width > piece.length + 1:
                self.skipped.append(f"{opening.label}: wider than its wall {piece.id}")
                continue
            offset = min(max((s0 + s1) / 2, width / 2), piece.length - width / 2)
            if opening.kind == "doors":
                record = {
                    "id": self.new_id("D"),
                    "type": self.door_type(width, style or "single"),
                    "wall": piece.id,
                    "offset": round(offset, 1),
                }
                if flip:
                    record["flip"] = True
            else:
                record = {
                    "id": self.new_id("W"),
                    "type": self.window_type(width),
                    "wall": piece.id,
                    "offset": round(offset, 1),
                }
            self.data[opening.kind].append(record)
            self.adopted[opening.kind] += 1
            placed += 1
        return placed

    def doors_by_swing(self, pieces: list[_Piece], opening: _Opening) -> list[Any]:
        """Doors from swings: each swing's hinge and the jamb it closes on lie in a wall; two
        swings in one wall meeting in the middle are a double door."""
        leaves = []
        for arc in opening.arcs:
            swing = _swing(arc)
            if swing is None:
                continue
            hinge, e1, e2 = swing
            best = None
            for piece in pieces:
                if not piece.band(hinge):
                    continue
                for jamb, tip in ((e1, e2), (e2, e1)):
                    if not piece.band(jamb):
                        continue
                    sh, vh = piece.local(hinge)
                    sj, vj = piece.local(jamb)
                    if abs(sj - sh) < 0.7 * arc.radius:
                        continue
                    score = abs(vh) + abs(vj)
                    if best is None or score < best[0]:
                        best = (score, piece, min(sh, sj), max(sh, sj), piece.local(tip)[1] - vh)
            if best is not None:
                leaves.append(list(best[1:]))
        leaves.sort(key=lambda leaf: (id(leaf[0]), leaf[1]))
        doors: list[Any] = []
        for piece, s0, s1, side in leaves:
            last = doors[-1] if doors else None
            if last is not None and last[0] is piece and last[1] <= s0 <= last[2] + 50:
                last[2] = max(last[2], s1)
                last[3] = "double"
                continue
            doors.append([piece, s0, s1, "single", side < 0])
        return [tuple(door) for door in doors]

    def by_extent(self, pieces: list[_Piece], opening: _Opening):
        """The wall most of a block's points lie in, and its extent along that wall."""
        best = None
        for piece in pieces:
            inside = [p for p in opening.points if piece.band(p)]
            if len(inside) < max(2, 0.5 * len(opening.points)):
                continue
            if best is None or len(inside) > len(best[1]):
                best = (piece, inside)
        if best is None:
            return None
        piece, inside = best
        spans = [piece.local(p)[0] for p in inside]
        style = "sliding" if opening.kind == "doors" else None
        return piece, max(0.0, min(spans)), min(piece.length, max(spans)), style, False

    def door_type(self, width: float, style: str) -> str:
        return self.sized_type("doorTypes", width, style, "D")

    def window_type(self, width: float) -> str:
        return self.sized_type("windowTypes", width, None, "W")

    def sized_type(self, key: str, width: float, style: str | None, prefix: str) -> str:
        existing = self.data[key]
        fits = [
            t
            for t in existing
            if abs(t["width"] - width) <= OPENING_TYPE_TOLERANCE
            and (style is None or t.get("style", "single") == style)
        ]
        if fits:
            return min(fits, key=lambda t: abs(t["width"] - width))["id"]
        size = round(width / 5) * 5
        type_id = _unique(f"{prefix}{size}", {t["id"] for t in existing})
        if key == "doorTypes":
            record = {
                "id": type_id,
                "name": f"Door {size} mm (imported)",
                "style": style or "single",
                "width": float(size),
                "height": 2100.0,
            }
        elif size < 700:
            record = {
                "id": type_id,
                "name": f"Ventilator {size} mm (imported)",
                "style": "fixed",
                "width": float(size),
                "height": 450.0,
                "sill": 1650.0,
            }
        else:
            record = {
                "id": type_id,
                "name": f"Window {size} mm (imported)",
                "style": "sliding",
                "width": float(size),
                "height": 1500.0,
            }
        existing.append(record)
        self.adopted["types"] += 1
        self.notes.append(
            f"{'Door' if key == 'doorTypes' else 'Window'} type {type_id}: {size} mm wide, "
            f"{record['height']:.0f} mm high (a plan has no heights): check it."
        )
        return type_id

    # ── rooms ──

    def rooms(self, arch: Architecture, texts: list[_Item]) -> None:
        faces: list[tuple[Any, str]] = []
        for room in arch.rooms:
            if room.story == self.story:
                boundary = room_boundary(arch, room, self.elevations)
                if boundary is not None:
                    faces.append((boundary[0], f"{room.name} ({room.id})"))
        sizes = 0
        for text in texts:
            label = room_label(text.text)
            if label is None:
                sizes += bool(text.text.strip())
                continue
            name, number = label
            point = text.points[0]
            room = Room(id="tmp", story=self.story, point=[point[0], point[1]], name=name)
            boundary = room_boundary(arch, room, self.elevations)
            if boundary is None:
                self.skipped.append(f"Room text '{name}': not inside closed walls")
                continue
            face = boundary[0]
            twin = next((other for f, other in faces if f.equals(face)), None)
            if twin is not None:
                self.skipped.append(
                    f"Room text '{name}': in the same walls as '{twin}' (add a room separator "
                    "between them and import again)"
                )
                continue
            faces.append((face, name))
            record = {
                "id": self.new_id("R"),
                "story": self.story,
                "point": [round(point[0], 1), round(point[1], 1)],
                "name": name,
            }
            if number:
                record["number"] = number
            self.data["rooms"].append(record)
            self.adopted["rooms"] += 1
        if sizes:
            self.notes.append(f"{sizes} texts on room layers are sizes or areas, not names.")


def _placed(item: _Item, place: Placement) -> _Item:
    points = [place(p) for p in item.points]
    centre = place(item.centre) if item.centre is not None else None
    parts = [_placed(p, place) for p in item.parts]
    return _Item(
        item.kind,
        item.layer,
        points,
        centre,
        item.radius * place.scale,
        item.text,
        parts,
        item.block,
    )


def _kind(role: str) -> str:
    return "Door" if role == "doors" else "Window"


def _unique(candidate: str, ids: set[str]) -> str:
    base, n = candidate, 2
    while candidate in ids:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _same_file(a: str, b: str) -> bool:
    def norm(x: str) -> str:
        return x.replace("\\", "/").strip().lower()

    return norm(a) == norm(b)

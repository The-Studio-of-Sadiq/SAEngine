"""Drawing revision control: the engineer's own edits kept when sheets are drawn again, revision
clouds around what changed since a sheet was last issued, each sheet's revisions in its title
block, the issues of the set (``Issued/<rev> <date>/``) and the drawing register.

Every generation records, per sheet, an *index* of what SAEngine drew (one fingerprint per
entity: its type, layer, text and extent) in ``.sheet-index/<number>.json.gz`` beside the
sheets. When the sheet is drawn again, every entity of the earlier DXF whose fingerprint is not
in that index was added by the engineer (in LibreCAD, AutoCAD, ...) and is copied into the new
sheet: notes, extra dimensions, stamps, a hand-drawn detail. Entities SAEngine draws are always
drawn afresh from the model. Without an index (sheets drawn by an older SAEngine) only the
entities on layers SAEngine never uses are kept, and the same when the earlier DXF was saved by a
program that moved SAEngine's own entities (more than :data:`RESAVED_SHARE` of them unknown).

Issuing (:func:`issue`, called through :func:`saengine.pipeline.drawings.issue`) draws the set
again with the new revision in the title block of every sheet that is new or changed since its
last issue, and copies the issued DXFs, the PDF set and the register into ``Issued/<rev>
<date>/``, with the index of each sheet's drawing area as issued. Each later generation compares
a sheet's drawing area with that index and draws a revision cloud (layer ``S-REV``) with the
pending revision's triangle around each group of changes; the clouds of earlier revisions are
not drawn again (the usual practice: only the latest revision is clouded).

The register (``register.json``, ``register.csv`` and the one-sheet ``register.pdf``) lists
every sheet of the set with its revision at each issue.
"""

from __future__ import annotations

import contextlib
import csv
import gzip
import hashlib
import io
import json
import math
import re
import shutil
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from saengine.drawings.sheets.layout import LAYERS, TEXT, Revision, Sheet, TitleInfo
from saengine.drawings.sheets.model import Table

REGISTER = "register.json"
REGISTER_CSV = "register.csv"
REGISTER_PDF = "register.pdf"
REGISTER_SCHEMA = "saengine.drawing-register/1"
INDEX_FOLDER = ".sheet-index"
ISSUED_FOLDER = "Issued"
CLOUD_LAYER = "S-REV"

#: SAEngine's own layers: entities on any other layer are always the engineer's.
OWN_LAYERS = frozenset(name for name, *_ in LAYERS)
#: Layers whose entities are never carried from the earlier sheet: SAEngine redraws them.
NEVER_CARRIED = frozenset({CLOUD_LAYER, "S-VIEWPORT"})
#: More than this share of the earlier sheet's entities on SAEngine's layers unknown to its
#: index: the file was saved by a program that rewrote them (only other layers are kept then).
RESAVED_SHARE = 0.25
#: Fingerprints round extents to this many paper mm (a CAD program's round trip moves nothing
#: by more; a change smaller than this is not visible on paper).
GRID = 0.1
#: Changes closer than this [paper mm] share one cloud.
CLOUD_GAP = 6.0
#: The cloud's clearance around what changed and the length of one arc [paper mm].
CLOUD_MARGIN = 3.0
CLOUD_ARC = 6.0
#: More than this share of the drawing area's entities changed: the sheet is revised
#: throughout, and a note says so instead of clouds.
THROUGHOUT_SHARE = 0.6
#: At most this many clouds on a sheet; more groups of changes are merged with a wider gap.
MAX_CLOUDS = 12
#: The register sheet shows at most this many issues (the CSV has all).
REGISTER_ISSUES = 10


class IssueError(RuntimeError):
    """The set could not be issued: the message says why, for the user."""


# ─────────────────────────────────── fingerprints ───────────────────────────────────


def _digest(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8"), digest_size=6).hexdigest()


def _text_of(entity: Any) -> str:
    kind = entity.dxftype()
    with contextlib.suppress(Exception):
        if kind == "TEXT" or kind == "ATTRIB":
            return str(entity.dxf.text)
        if kind == "MTEXT":
            return entity.plain_text()
        if kind == "INSERT":
            return str(entity.dxf.name)
        if kind == "DIMENSION":
            return f"{entity.dxf.get('text', '')}|{entity.get_measurement():.1f}"
    return ""


def fingerprints(
    entities: Iterable[Any], scale: float
) -> list[tuple[str, tuple[float, float, float, float] | None]]:
    """``(fingerprint, extent)`` of each entity, its extent in paper mm (None: none known).
    Two entities alike on paper (same type, layer, text and extent to :data:`GRID`) share the
    fingerprint, wherever their handles or the order of their vertices."""
    from ezdxf import bbox

    items = list(entities)
    boxes = list(bbox.multi_flat(items, fast=True))
    out = []
    step = GRID * scale
    for entity, box in zip(items, boxes, strict=False):
        layer = str(entity.dxf.get("layer", "0"))
        extent = None
        if box.has_data:
            lo, hi = box.extmin, box.extmax
            cells = [round(v / step) for v in (lo.x, lo.y, hi.x, hi.y)]
            extent = tuple(round(c * GRID, 1) for c in cells)
            where = ",".join(str(c) for c in cells)
        else:
            where = "-"
        key = f"{entity.dxftype()}|{layer}|{where}|{_text_of(entity)}"
        out.append((_digest(key), extent))
    return out


@dataclass
class SheetIndex:
    """What SAEngine drew on a sheet: every entity's fingerprint (``all``) and those of the
    drawing area with their extents in paper mm (``content``)."""

    number: str
    title: str = ""
    all: list[str] = field(default_factory=list)
    content: list[tuple[str, tuple[float, float, float, float] | None]] = field(
        default_factory=list
    )

    def to_json(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "all": self.all,
            "content": [[k, *(e or ())] for k, e in self.content],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> SheetIndex:
        content = []
        for row in data.get("content") or []:
            if not row:
                continue
            extent = tuple(float(v) for v in row[1:5]) if len(row) >= 5 else None
            content.append((str(row[0]), extent))
        return cls(
            str(data.get("number") or ""),
            str(data.get("title") or ""),
            [str(k) for k in data.get("all") or []],
            content,  # type: ignore[arg-type]
        )

    def save(self, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{_safe(self.number)}.json.gz"
        raw = json.dumps(self.to_json(), separators=(",", ":")).encode("utf-8")
        path.write_bytes(gzip.compress(raw, mtime=0))
        return path

    @classmethod
    def load(cls, folder: Path, number: str) -> SheetIndex | None:
        path = folder / f"{_safe(number)}.json.gz"
        try:
            return cls.from_json(json.loads(gzip.decompress(path.read_bytes()).decode("utf-8")))
        except (OSError, ValueError, EOFError, AttributeError):
            return None


_UNSAFE = re.compile(r'[\\/:*?"<>|]')


def _safe(name: str) -> str:
    return _UNSAFE.sub("-", name).strip() or "-"


def _in_area(sheet: Sheet, extent: tuple[float, float, float, float] | None) -> bool:
    if extent is None:
        return False
    x0, y0, x1, y1 = sheet.area
    cx, cy = (extent[0] + extent[2]) / 2, (extent[1] + extent[3]) / 2
    return x0 <= cx <= x1 and y0 <= cy <= y1


def content_index(sheet: Sheet) -> list[tuple[str, tuple[float, float, float, float] | None]]:
    """The fingerprints of what is drawn in the sheet's drawing area (its views; not the frame,
    the title block, its notes or the revision clouds)."""
    entities = [e for e in sheet.msp if str(e.dxf.get("layer", "0")) not in NEVER_CARRIED]
    found = fingerprints(entities, sheet.scale)
    return [(k, e) for k, e in found if _in_area(sheet, e)]


def full_index(sheet: Sheet, content: Sequence[Any] | None = None) -> SheetIndex:
    """The index of a finished sheet (everything SAEngine drew on it)."""
    keys = [k for k, _ in fingerprints(list(sheet.msp), sheet.scale)]
    return SheetIndex(
        sheet.number,
        sheet.title,
        keys,
        list(content if content is not None else content_index(sheet)),
    )


# ─────────────────────────────────── the engineer's edits ───────────────────────────────────


@dataclass
class Carried:
    """What :func:`carry_edits` kept from the earlier sheet."""

    count: int = 0
    resaved: bool = False  # the earlier file was rewritten by a CAD program: other layers only
    failed: int = 0  # entities that could not be copied

    def note(self, number: str) -> str | None:
        if not self.count and not self.failed:
            return None
        text = f"{number}: {self.count} drawing object(s) you added to the sheet were kept"
        if self.resaved:
            text += (
                " (those on your own layers only: the earlier file was saved by a CAD program "
                "that rewrote SAEngine's entities, so edits on SAEngine's layers could not be "
                "told apart)"
            )
        if self.failed:
            text += f"; {self.failed} could not be copied"
        return text + "."


def user_entities(old_doc: Any, index: SheetIndex | None, scale: float) -> tuple[list[Any], bool]:
    """The model space entities of ``old_doc`` that SAEngine did not draw (see the module
    notes) and whether the file was found re-saved (only other layers trusted)."""
    entities = [e for e in old_doc.modelspace() if e.dxf.get("layer", "0") not in NEVER_CARRIED]
    if index is None:
        return [e for e in entities if e.dxf.get("layer", "0") not in OWN_LAYERS], False
    known = Counter(index.all)
    found = fingerprints(entities, scale)
    unknown: list[Any] = []
    own_total = own_unknown = 0
    for entity, (key, _) in zip(entities, found, strict=True):
        own = entity.dxf.get("layer", "0") in OWN_LAYERS
        own_total += own
        if known[key] > 0:
            known[key] -= 1
            continue
        own_unknown += own
        unknown.append(entity)
    if own_total and own_unknown > RESAVED_SHARE * own_total:
        return [e for e in unknown if e.dxf.get("layer", "0") not in OWN_LAYERS], True
    return unknown, False


def carry_edits(
    sheet: Sheet, old_dxf: Path, index: SheetIndex | None, renames: dict[str, str] | None = None
) -> Carried:
    """Copies the engineer's own entities of the earlier ``old_dxf`` of this sheet into
    ``sheet`` (with the layers, styles and blocks they use). ``renames``: the office layer
    names the earlier sheet was written with (SAEngine layer -> name, the drafting standard of
    :mod:`.standards`): they are named back first, so that SAEngine's own entities are known."""
    import ezdxf
    from ezdxf.addons import Importer

    result = Carried()
    if not old_dxf.is_file():
        return result
    try:
        old = ezdxf.readfile(old_dxf)
    except (OSError, ezdxf.DXFError):
        return result
    if renames:
        from saengine.drawings.sheets.standards import restore_names

        restore_names(old, renames)
    entities, result.resaved = user_entities(old, index, sheet.scale)
    if not entities:
        return result
    importer = Importer(old, sheet.doc)
    for entity in entities:
        try:
            importer.import_entities([entity], sheet.msp)
            result.count += 1
        except Exception:  # noqa: BLE001 - one odd entity does not stop the others
            result.failed += 1
    with contextlib.suppress(Exception):
        importer.finalize()
    return result


# ─────────────────────────────────── revision codes ───────────────────────────────────


def next_revision(code: str | None) -> str:
    """The revision after ``code``: ``0`` -> ``1``, ``A`` -> ``B``, ``Z`` -> ``AA``, ``P1`` ->
    ``P2``, ``C09`` -> ``C10``; ``"0"`` for none."""
    code = (code or "").strip()
    if not code:
        return "0"
    match = re.fullmatch(r"(.*?)(\d+)", code)
    if match:
        prefix, digits = match.groups()
        return f"{prefix}{int(digits) + 1:0{len(digits)}d}"
    if re.fullmatch(r"[A-Za-z]+", code):
        letters = list(code)
        i = len(letters) - 1
        while i >= 0:
            c = letters[i]
            if c in "zZ":
                letters[i] = "a" if c == "z" else "A"
                i -= 1
                continue
            letters[i] = chr(ord(c) + 1)
            return "".join(letters)
        return ("a" if code[0].islower() else "A") + "".join(letters)
    return f"{code}.1"


# ─────────────────────────────────── the register ───────────────────────────────────


@dataclass
class IssuedSheet:
    number: str
    title: str
    change: str  # new | revised | reissued
    clouds: int = 0


@dataclass
class Issue:
    """One issue of the drawing set."""

    code: str
    date: str
    description: str = ""
    by: str = ""
    purpose: str = ""
    issued_at: str = ""
    folder: str = ""  # relative to the drawings folder
    sheets: list[IssuedSheet] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)  # in the set, not issued again
    removed: list[str] = field(default_factory=list)  # issued before, no longer in the set

    def numbers(self) -> set[str]:
        return {s.number for s in self.sheets}

    def revision(self) -> Revision:
        return Revision(self.code, self.date, self.description or self.purpose, self.by)

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "date": self.date,
            "description": self.description,
            "by": self.by,
            "purpose": self.purpose,
            "issuedAt": self.issued_at,
            "folder": self.folder,
            "sheets": [
                {"number": s.number, "title": s.title, "change": s.change, "clouds": s.clouds}
                for s in self.sheets
            ],
            "unchanged": self.unchanged,
            "removed": self.removed,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Issue:
        return cls(
            code=str(data.get("code") or ""),
            date=str(data.get("date") or ""),
            description=str(data.get("description") or ""),
            by=str(data.get("by") or ""),
            purpose=str(data.get("purpose") or ""),
            issued_at=str(data.get("issuedAt") or ""),
            folder=str(data.get("folder") or ""),
            sheets=[
                IssuedSheet(
                    str(s.get("number") or ""),
                    str(s.get("title") or ""),
                    str(s.get("change") or "revised"),
                    int(s.get("clouds") or 0),
                )
                for s in data.get("sheets") or []
                if isinstance(s, dict) and s.get("number")
            ],
            unchanged=[str(n) for n in data.get("unchanged") or []],
            removed=[str(n) for n in data.get("removed") or []],
        )


@dataclass
class Register:
    """The issues of the drawing set, oldest first."""

    issues: list[Issue] = field(default_factory=list)

    @classmethod
    def load(cls, folder: Path) -> Register:
        try:
            data = json.loads((folder / REGISTER).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(data, dict) or data.get("schema") != REGISTER_SCHEMA:
            return cls()
        return cls([Issue.from_json(i) for i in data.get("issues") or [] if isinstance(i, dict)])

    def save(self, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / REGISTER
        data = {"schema": REGISTER_SCHEMA, "issues": [i.to_json() for i in self.issues]}
        path.write_text(json.dumps(data, indent="\t", ensure_ascii=False) + "\n", "utf-8")
        return path

    def issues_of(self, number: str) -> list[Issue]:
        return [i for i in self.issues if number in i.numbers()]

    def last_issue_of(self, number: str) -> Issue | None:
        found = self.issues_of(number)
        return found[-1] if found else None

    def revision_of(self, number: str) -> str | None:
        last = self.last_issue_of(number)
        return last.code if last else None

    def pending_code(self, fallback: str = "0") -> str:
        """The code the next issue takes by default."""
        return next_revision(self.issues[-1].code) if self.issues else (fallback or "0")


def issue_folder_name(code: str, day: str) -> str:
    return _safe(f"{code} {day}".strip())


# ─────────────────────────────────── revision clouds ───────────────────────────────────


Box = tuple[float, float, float, float]


def _grow(box: Box, by: float) -> Box:
    return (box[0] - by, box[1] - by, box[2] + by, box[3] + by)


def _touch(a: Box, b: Box) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def merge_boxes(boxes: Iterable[Box], gap: float) -> list[Box]:
    """Groups of boxes closer than ``gap``, each as the box around it."""
    out: list[Box] = [_grow(b, gap / 2) for b in boxes]
    merged = True
    while merged:
        merged = False
        result: list[Box] = []
        for box in out:
            for i, other in enumerate(result):
                if _touch(box, other):
                    result[i] = (
                        min(box[0], other[0]),
                        min(box[1], other[1]),
                        max(box[2], other[2]),
                        max(box[3], other[3]),
                    )
                    merged = True
                    break
            else:
                result.append(box)
        out = result
    return [_grow(b, -gap / 2) for b in out]


def changed_boxes(
    new: Sequence[tuple[str, Box | None]], old: Sequence[tuple[str, Box | None]]
) -> tuple[list[Box], int]:
    """The extents of what was added or removed between ``old`` and ``new`` (drawing area
    indices) and how many entities changed."""
    remaining = Counter(k for k, _ in old)
    boxes: list[Box] = []
    changed = 0
    for key, extent in new:
        if remaining[key] > 0:
            remaining[key] -= 1
            continue
        changed += 1
        if extent is not None:
            boxes.append(extent)
    kept = Counter(k for k, _ in new)
    for key, extent in old:
        if kept[key] > 0:
            kept[key] -= 1
            continue
        changed += 1
        if extent is not None:
            boxes.append(extent)
    return boxes, changed


def cloud_points(box: Box, arc: float = CLOUD_ARC) -> list[tuple[float, float, float]]:
    """The vertices ``(x, y, bulge)`` of a revision cloud around ``box`` (paper mm),
    counter-clockwise with outward arcs."""
    x0, y0, x1, y1 = box
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    points: list[tuple[float, float, float]] = []
    for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1], strict=True):
        length = math.hypot(bx - ax, by - ay)
        n = max(1, round(length / arc))
        for i in range(n):
            t = i / n
            points.append((ax + (bx - ax) * t, ay + (by - ay) * t, 0.6))
    return points


def draw_cloud(sheet: Sheet, box: Box, code: str) -> None:
    """A revision cloud around ``box`` (paper mm) with the revision's triangle at its top right."""
    pts = [(*sheet.m(x, y), 0.0, 0.0, b) for x, y, b in cloud_points(box)]
    sheet.msp.add_lwpolyline(pts, format="xyseb", close=True, dxfattribs={"layer": CLOUD_LAYER})
    size = 7.0
    cx, cy = box[2], box[3]
    tri = [(cx - size / 2, cy), (cx + size / 2, cy), (cx, cy + size * 0.87)]
    sheet.msp.add_lwpolyline(
        [sheet.m(x, y) for x, y in tri], close=True, dxfattribs={"layer": CLOUD_LAYER}
    )
    sheet.p_text(code, cx, cy + size * 0.3, TEXT, "MC", layer=CLOUD_LAYER, reserve=False)


def clouds_for(
    sheet: Sheet,
    new: Sequence[tuple[str, Box | None]],
    old: Sequence[tuple[str, Box | None]],
) -> tuple[list[Box], bool]:
    """Where the clouds go on ``sheet`` and whether it is revised throughout (no clouds)."""
    boxes, changed = changed_boxes(new, old)
    if not changed:
        return [], False
    if changed > THROUGHOUT_SHARE * max(len(new), len(old), 1):
        return [], True
    x0, y0, x1, y1 = sheet.area
    gap = CLOUD_GAP
    clouds = merge_boxes(boxes, gap)
    while len(clouds) > MAX_CLOUDS and gap < (x1 - x0):
        gap *= 2
        clouds = merge_boxes(clouds, gap)
    out = []
    for b in clouds:
        b = _grow(b, CLOUD_MARGIN)
        out.append((max(b[0], x0), max(b[1], y0), min(b[2], x1), min(b[3], y1)))
    return out, False


# ─────────────────────────────────── per sheet, while drawing ───────────────────────────────────


@dataclass
class SheetState:
    """What :class:`Reviser` found for one sheet."""

    number: str
    title: str
    content: list[tuple[str, Box | None]]
    last: str | None  # the revision it was last issued at
    changed: bool  # since that issue (True: never issued)
    clouds: int = 0
    throughout: bool = False
    issued: bool = False  # in the issue being made


class Reviser:
    """The ``before_finish`` hook of :func:`saengine.drawings.sheets.build_sheets`: compares
    each sheet with its last issue, draws the clouds of the pending revision and puts the
    sheet's revisions into its title block.

    ``issuing``: the issue being made (its code, date, description, by); ``chosen``: the sheets
    it issues (None: all); ``force``: issue them even when unchanged since their last issue."""

    def __init__(
        self,
        folder: Path,
        title: TitleInfo,
        register: Register | None = None,
        issuing: Issue | None = None,
        chosen: Iterable[str] | None = None,
        force: bool = False,
        clouds: bool = True,
    ) -> None:
        self.folder = folder
        self.title = title
        self.register = register if register is not None else Register.load(folder)
        self.issuing = issuing
        self.chosen = None if chosen is None else {c for c in chosen if c}
        self.force = force
        self.clouds = clouds
        self.pending = issuing.code if issuing else self.register.pending_code(title.revision)
        self.states: dict[str, SheetState] = {}
        self._indices: dict[str, SheetIndex | None] = {}

    def issued_index(self, number: str) -> SheetIndex | None:
        if number not in self._indices:
            last = self.register.last_issue_of(number)
            index = None
            if last is not None and last.folder:
                index = SheetIndex.load(self.folder / last.folder / INDEX_FOLDER, number)
            self._indices[number] = index
        return self._indices[number]

    def __call__(self, sheet: Sheet) -> None:
        content = content_index(sheet)
        sheet.content_index = content  # type: ignore[attr-defined]
        last = self.register.last_issue_of(sheet.number)
        old = self.issued_index(sheet.number)
        if last is None:
            changed = True
        elif old is None:
            changed = False  # its issued index is missing: nothing to compare with
        else:
            changed = Counter(k for k, _ in content) != Counter(k for k, _ in old.content)
        state = SheetState(sheet.number, sheet.title, content, last.code if last else None, changed)
        if self.issuing is not None and (self.chosen is None or sheet.number in self.chosen):
            state.issued = changed or self.force
        if self.clouds and last is not None and old is not None and changed:
            boxes, state.throughout = clouds_for(sheet, content, old.content)
            for box in boxes:
                draw_cloud(sheet, box, self.pending)
            state.clouds = len(boxes)
        revisions = [i.revision() for i in self.register.issues_of(sheet.number)]
        if state.issued and self.issuing is not None:
            revisions.append(self.issuing.revision())
        if revisions:
            sheet.info = replace(self.title, revisions=revisions, revision=revisions[-1].rev)
        self.states[sheet.number] = state

    def notes(self) -> list[str]:
        """What the answer says about the revisions of the set."""
        if not self.register.issues:
            return []
        revised = [s.number for s in self.states.values() if s.changed and s.last]
        throughout = [s.number for s in self.states.values() if s.throughout]
        new = [s.number for s in self.states.values() if s.last is None]
        out = []
        if revised:
            out.append(
                f"Changed since their last issue (clouded as revision {self.pending}): "
                f"{', '.join(revised)}."
            )
        if throughout:
            out.append(f"Revised throughout (no clouds drawn): {', '.join(throughout)}.")
        if new:
            out.append(f"Not issued yet: {', '.join(new)}.")
        return out

    def sheet_rows(self) -> dict[str, dict[str, Any]]:
        """Per sheet, what the answer's sheet rows carry: ``revision`` (last issued) and
        ``revised`` (changed since)."""
        return {
            n: {"revision": s.last, "revised": bool(s.last) and s.changed, "clouds": s.clouds}
            for n, s in self.states.items()
        }


# ─────────────────────────────────── issuing ───────────────────────────────────


def new_issue(
    register: Register,
    code: str | None = None,
    day: str | None = None,
    description: str = "",
    by: str = "",
    purpose: str = "",
    fallback: str = "0",
) -> Issue:
    """The issue to make next (its code: ``code``, else the one after the last issue, else
    ``fallback``, the drawing settings' revision)."""
    code = (code or "").strip() or register.pending_code(fallback)
    if any(i.code == code for i in register.issues):
        raise IssueError(f"Revision {code} was issued already: give the next revision.")
    day = (day or "").strip() or date.today().isoformat()
    return Issue(code, day, description.strip(), by.strip(), purpose.strip())


def record_issue(
    folder: Path,
    register: Register,
    issue: Issue,
    reviser: Reviser,
    sheets: Sequence[Sheet],
    files: dict[str, Path],
    pdf: Path | None,
    dwg: dict[str, Path] | None = None,
) -> Issue:
    """Copies the issued sheets (``files``: DXF by sheet number), the PDF set and their DWGs
    into ``Issued/<rev> <date>/`` with each sheet's index, adds the issue to ``register`` and
    writes the register (JSON, CSV and its sheet)."""
    issue.folder = f"{ISSUED_FOLDER}/{issue_folder_name(issue.code, issue.date)}"
    target = folder / issue.folder
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    current = {s.number for s in sheets}
    by_number = {s.number: s for s in sheets}
    for number, state in reviser.states.items():
        if state.issued:
            change = "new" if state.last is None else ("revised" if state.changed else "reissued")
            issue.sheets.append(IssuedSheet(number, state.title, change, state.clouds))
            dxf = files.get(number)
            if dxf is not None and dxf.is_file():
                shutil.copy2(dxf, target / dxf.name)
            if dwg and number in dwg and dwg[number].is_file():
                shutil.copy2(dwg[number], target / dwg[number].name)
            sheet = by_number.get(number)
            if sheet is not None:
                SheetIndex(number, state.title, [], state.content).save(target / INDEX_FOLDER)
        elif reviser.register.last_issue_of(number) is not None:
            issue.unchanged.append(number)
    before = {n for i in register.issues for n in i.numbers()}
    issue.removed = sorted(before - current)
    if not issue.sheets:
        shutil.rmtree(target, ignore_errors=True)
        raise IssueError(
            "No sheet has changed since its last issue: nothing to issue (tick Issue every "
            "sheet to issue them again)."
        )
    if pdf is not None and pdf.is_file():
        shutil.copy2(pdf, target / pdf.name)
    issue.issued_at = datetime.now(UTC).isoformat(timespec="seconds")
    register.issues.append(issue)
    register.save(folder)
    write_register(folder, register, sheets, reviser.title)
    for name in (REGISTER_CSV, REGISTER_PDF):
        if (folder / name).is_file():
            shutil.copy2(folder / name, target / name)
    return issue


# ─────────────────────────────────── the register as files ───────────────────────────────────


def register_rows(
    register: Register, sheets: Sequence[tuple[str, str]]
) -> tuple[list[str], list[list[str]]]:
    """The register as a table: per sheet of ``sheets`` ``(number, title)`` (then the sheets
    issued before and since withdrawn), its revision at each issue ("" not issued in it) and
    its current revision."""
    head = ["Sheet No.", "Title", *[f"{i.code} ({i.date})" for i in register.issues], "Current"]
    rows = []
    numbers = [n for n, _ in sheets]
    titles = dict(sheets)
    for issue in register.issues:
        for s in issue.sheets:
            if s.number not in titles:
                numbers.append(s.number)
                titles[s.number] = f"{s.title} (withdrawn)"
    for number in numbers:
        cells = []
        current = ""
        for issue in register.issues:
            if number in issue.numbers():
                current = issue.code
                cells.append(issue.code)
            else:
                cells.append("")
        rows.append([number, titles[number], *cells, current or "-"])
    return head, rows


def register_csv(register: Register, sheets: Sequence[tuple[str, str]]) -> str:
    head, rows = register_rows(register, sheets)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(head)
    writer.writerows(rows)
    writer.writerow([])
    writer.writerow(["Revision", "Date", "Description", "Purpose", "By", "Sheets"])
    for issue in register.issues:
        writer.writerow(
            [
                issue.code,
                issue.date,
                issue.description,
                issue.purpose,
                issue.by,
                " ".join(s.number for s in issue.sheets),
            ]
        )
    return out.getvalue()


def register_table(register: Register, sheets: Sequence[tuple[str, str]]) -> Table:
    """The register for its sheet: the last :data:`REGISTER_ISSUES` issues."""
    _head, rows = register_rows(register, sheets)
    shown = register.issues[-REGISTER_ISSUES:]
    skip = len(register.issues) - len(shown)
    columns = [
        {"key": "number", "title": "SHEET No.", "width": 9, "align": "left"},
        {"key": "title", "title": "TITLE", "width": 40, "align": "left"},
    ]
    for i in shown:
        columns.append(
            {"key": i.code, "title": f"{i.code}\n{i.date}", "width": 9, "align": "center"}
        )
    columns.append({"key": "current", "title": "CURRENT\nREV", "width": 8, "align": "center"})
    body = [[r[0], r[1], *r[2 + skip : 2 + len(register.issues)], r[-1]] for r in rows]
    notes = [
        f"{i.code} ({i.date}): {i.description or i.purpose or '-'}"
        + (f", by {i.by}" if i.by else "")
        for i in shown
    ]
    if skip:
        notes.insert(0, f"{skip} earlier issue(s) are in register.csv.")
    return Table("Drawing register", columns, body, notes=notes)


def register_sheet(
    register: Register, sheets: Sequence[tuple[str, str]], title: TitleInfo, size: str, prefix: str
) -> Sheet:
    """The register as one sheet (``<prefix>000``)."""
    from saengine.drawings.sheets import schedules
    from saengine.drawings.sheets.layout import drawing_area, pack

    area = drawing_area(size)
    info = title
    if register.issues:
        last = register.issues[-1]
        info = replace(title, revisions=[i.revision() for i in register.issues], revision=last.code)
    table = register_table(register, sheets)
    specs = schedules.table_specs(
        table, area[3] - area[1], key="register", max_width=area[2] - area[0]
    )
    sheet = Sheet(f"{prefix}000", "Drawing register", size, 1, info, scale_text="NTS")
    for page in pack(specs, area)[:1]:
        for spec, x, y in page:
            sheet.view(spec, x, y)
    sheet.notes(table.notes, title="ISSUES")
    sheet.finish()
    return sheet


def write_register(
    folder: Path, register: Register, sheets: Sequence[Sheet], title: TitleInfo
) -> dict[str, Path]:
    """``register.csv`` and ``register.pdf`` (one sheet, with its DXF ``register.dxf``)."""
    from saengine.drawings.sheets.render import render

    listed = [(s.number, s.title) for s in sheets]
    out: dict[str, Path] = {}
    csv_path = folder / REGISTER_CSV
    csv_path.write_text(register_csv(register, listed), encoding="utf-8-sig", newline="")
    out["csv"] = csv_path
    if not sheets:
        return out
    prefix = re.sub(r"\d+$", "", sheets[0].number) or "S-"
    sheet = register_sheet(register, listed, title, sheets[0].size, prefix)
    dxf = folder / "register.dxf"
    sheet.doc.saveas(dxf)
    out["dxf"] = dxf
    with contextlib.suppress(Exception):  # the PDF needs the renderer; the CSV is the record
        rendered = render([sheet], folder / REGISTER_PDF, None)
        if rendered.get("pdf"):
            out["pdf"] = Path(str(rendered["pdf"]))
    return out

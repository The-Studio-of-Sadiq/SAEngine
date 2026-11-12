"""DSTV NC files (``.nc1``) of the fabricated parts (alpha 9 L10), one per part mark, after the
DSTV "Standard description for steel structure pieces for the numerical controls" (7th edition,
July 1998). The parts are those of :mod:`.model`, in its coordinates.

A file holds:

- ``ST``: the header: order, drawing, phase and piece (part mark) identifications, the steel
  grade, the quantity, the profile and its code (I, U, L, B, M, RO, RU, T, C, SO), the length,
  the profile's height, flange width, flange and web thickness and root radius, the mass and
  painting surface per metre, the web and flange start and end cuts (skew cuts, degrees) and
  four lines of text. A plate (code B) gives its width as the height and its thickness as the
  thicknesses (kg/m² and m²/m² for the mass and the surface);
- ``BO``: the holes, one line each: the face (v: web front, o: top flange, u: bottom flange, h:
  web back), x with the dimension reference letter (o: top edge, u: bottom edge, s: axis), y and
  the diameter;
- ``AK``: the outer contour of a plate (face v, counter-clockwise, closed: the first point
  repeated) and of a coped beam's web and flanges, one point per line (face, x, reference, y,
  radius 0);
- ``IK``: the inner contours: a castellated beam's hexagonal web openings, one block each (the
  circular openings of a cellular beam are ``BO`` holes of their diameter);
- ``SI``: the part mark to scribe (face, x, reference, y, angle, text height, text), when asked;
- ``EN``: the end.

Data lines start with two spaces, values are separated by spaces, lengths in mm with two
decimals, masses with three; the text is ASCII (other characters become ``?``) and the lines
end with CR LF when written by :func:`write_nc_files`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from saengine.fabrication.model import Part

#: The text height of the scribed mark [mm].
MARK_HEIGHT = 10


@dataclass
class NcHeader:
    """What the header names besides the part: the order, the drawing and the phase."""

    order: str = ""
    drawing: str = ""
    phase: str = "1"
    marking: bool = True
    comment: str = "SAEngine"


def _text(value: Any) -> str:
    """A text field: ASCII, one line, no leading spaces, at most 80 characters (DSTV ``a``)."""
    text = re.sub(r"[\r\n\t]+", " ", str(value or "")).strip()
    return text.encode("ascii", "replace").decode("ascii")[:80]


def _f(value: float, digits: int = 2) -> str:
    return f"{value:10.{digits}f}"


def _ref(face: str, y: float, part: Part) -> str:
    """The dimension reference letter of a y on ``face``: on a web, the edge it is nearer to;
    on a flange, the axis; on a plate, its lower edge."""
    if part.code == "B":
        return "u"
    if face in ("v", "h"):
        return "o" if y > part.h / 2 else "u"
    return "s"


def header_lines(part: Part, quantity: int, header: NcHeader) -> list[str]:
    """The ``ST`` block of ``part``."""
    if part.code == "B":
        t = part.tw
        dims = [part.h, t, t, t, 0.0]
        mass = t * part.density * 1e-3  # kg/m²
        paint = 2.0  # m²/m²
    else:
        dims = [part.h, part.b, part.tf, part.tw, part.r]
        mass = part.mass_per_m
        paint = part.paint_per_m
    lines = [
        "ST",
        f"** {_text(header.comment)}",
        f"  {_text(header.order) or '-'}",
        f"  {_text(header.drawing) or '-'}",
        f"  {_text(header.phase) or '1'}",
        f"  {_text(part.mark)}",
        f"  {_text(part.grade) or '-'}",
        f"  {int(quantity)}",
        f"  {_text(part.profile)}",
        f"  {part.code}",
        f"  {_f(part.length)}",
        *(f"  {_f(v)}" for v in dims),
        f"  {_f(mass, 3)}",
        f"  {_f(paint, 3)}",
        *(f"  {_f(c, 3)}" for c in part.cuts),
        f"  {_text(part.role)}",
        "  ",
        "  ",
        "  ",
    ]
    return lines


def hole_lines(part: Part) -> list[str]:
    """The ``BO`` block (none without holes): the bolt holes and the circular web openings of
    a cellular beam (a round hole of the opening's diameter, burnt)."""
    round_openings = [o for o in part.openings if o.shape != "hexagonal"]
    if not part.holes and not round_openings:
        return []
    out = ["BO"]
    for h in part.holes:
        out.append(f"  {h.face}{_f(h.x)}{_ref(h.face, h.y, part)}{_f(h.y)}{_f(h.dia)}")
    for o in round_openings:
        out.append(f"  {o.face}{_f(o.x)}u{_f(o.y)}{_f(o.depth)}")
    return out


def inner_contour_lines(part: Part) -> list[str]:
    """The ``IK`` blocks: one inner contour per hexagonal web opening of a castellated beam
    (face v, counter-clockwise, closed; y from the lower edge)."""
    out: list[str] = []
    for o in part.openings:
        pts = o.outline()
        if pts:
            out += ["IK", *_contour(o.face, pts, "u")]
    return out


def _contour(face: str, points: Sequence[tuple[float, float]], ref: str) -> list[str]:
    pts = [*points, points[0]]
    return [f"  {face}{_f(x)}{ref}{_f(y)}{_f(0.0)}" for x, y in pts]


def contour_lines(part: Part) -> list[str]:
    """The ``AK`` blocks: a plate's outline; a coped profile's web and coped flanges."""
    if part.code == "B":
        # every plate, a rectangle too: plate cutting machines work from the contour
        return ["AK", *_contour("v", part.outline(), "u")]
    if not part.copes:
        return []
    L, h = part.length, part.h

    def cope(end: str, side: str) -> tuple[float, float]:
        for c in part.copes:
            if c.end == end and c.side == side:
                return c.length, c.depth
        return 0.0, 0.0

    (ls_t, ds_t), (le_t, de_t) = cope("start", "top"), cope("end", "top")
    (ls_b, ds_b), (le_b, de_b) = cope("start", "bottom"), cope("end", "bottom")
    web: list[tuple[float, float]] = []
    # counter-clockwise from the bottom at the start
    web += [(0.0, ds_b)] if ds_b else [(0.0, 0.0)]
    if ds_b:
        web += [(ls_b, ds_b), (ls_b, 0.0)]
    if de_b:
        web += [(L - le_b, 0.0), (L - le_b, de_b), (L, de_b)]
    else:
        web += [(L, 0.0)]
    if de_t:
        web += [(L, h - de_t), (L - le_t, h - de_t), (L - le_t, h)]
    else:
        web += [(L, h)]
    if ds_t:
        web += [(ls_t, h), (ls_t, h - ds_t), (0.0, h - ds_t)]
    else:
        web += [(0.0, h)]
    out = ["AK", *_contour("v", web, "u")]
    for face, (a, b) in (("o", (ls_t, le_t)), ("u", (ls_b, le_b))):
        if a or b:
            flange = [(a, 0.0), (L - b, 0.0), (L - b, part.b), (a, part.b)]
            out += ["AK", *_contour(face, flange, "s")]
    return out


def mark_lines(part: Part, header: NcHeader) -> list[str]:
    """The ``SI`` block: the part mark at the middle of the web (a plate: of its face)."""
    if not header.marking or not part.mark:
        return []
    x = part.length / 2
    y = part.h / 2
    ref = "u" if part.code == "B" else "o"
    return ["SI", f"  v{_f(x)}{ref}{_f(y)}{_f(0.0)}{MARK_HEIGHT:6d} {_text(part.mark)}"]


def nc1(part: Part, quantity: int, header: NcHeader | None = None) -> str:
    """The NC file of one part mark made ``quantity`` times (lines joined by ``\\n``)."""
    header = header or NcHeader()
    lines = [
        *header_lines(part, quantity, header),
        *contour_lines(part),
        *inner_contour_lines(part),
        *hole_lines(part),
        *mark_lines(part, header),
        "EN",
    ]
    return "\n".join(lines) + "\n"


def file_name(part: Part) -> str:
    """``<part mark>.nc1`` (characters a file name cannot hold replaced)."""
    return re.sub(r'[\\/:*?"<>|\s]', "_", part.mark or "part") + ".nc1"


def write_nc_files(
    parts: Sequence[tuple[Part, int]],
    folder: str | Path,
    header: NcHeader,
    drawings: dict[str, str] | None = None,
) -> list[Path]:
    """One NC file per part mark into ``folder`` (``drawings``: the shop drawing sheet of each
    part mark, else the header's); the NC files of an earlier export no longer made are
    removed; parts bought made (``supplied``: open-web joists) get none. Returns the files
    written."""
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for part, quantity in parts:
        if part.supplied:
            continue  # bought made (an open-web joist): not cut here
        own = NcHeader(
            header.order,
            (drawings or {}).get(part.mark, header.drawing),
            header.phase,
            header.marking,
            header.comment,
        )
        path = out / file_name(part)
        text = nc1(part, quantity, own)
        path.write_bytes(text.replace("\n", "\r\n").encode("ascii", "replace"))
        written.append(path)
    keep = {p.name for p in written}
    for old in out.glob("*.nc1"):
        if old.name not in keep:
            try:
                old.unlink()
            except OSError:
                pass
    return written

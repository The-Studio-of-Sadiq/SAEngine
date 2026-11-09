"""BVBS files for rebar bending machines (alpha 9 L10): one ``BF2D`` record per bar mark of the
bar bending schedule (:mod:`saengine.drawings.bbs`), after the BVBS guideline "Data exchange of
reinforcement data" (Bundesverband Bausoftware; the record layout of version 2.0, kept in 3.x).

A record is one line of blocks separated by ``@``::

    BF2D@Hj<project>@r<schedule>@i<revision>@p<mark>@l<length>@n<count>@e<kg>@d<dia>@g<grade>@s<mandrel>@v@Gl<leg>@w<angle>@...@w0@C<checksum>@

- the header ``H``: ``j`` project, ``r`` the schedule (drawing) number, ``i`` its revision,
  ``p`` the bar mark, ``l`` the cutting length [mm], ``n`` the number of bars, ``e`` the mass of
  one bar [kg, three decimals], ``d`` the bar size [mm], ``g`` the grade, ``s`` the mandrel
  (inside bend) diameter [mm], ``v`` (empty);
- the geometry ``G``: the shape's legs ``l`` (outside dimensions, mm), arcs ``r`` (inside radius)
  and the bend angles after them ``w`` (degrees; the last 0), from the shape's ``bvbs`` entry of
  the pack's bar schedule standard (:mod:`saengine.codes.bar_schedule_tables`). A shape without
  one (a helix, a special bar, a crank) is sent without ``G``, as the guideline allows for bars
  it cannot describe;
- the checksum ``C``: 96 minus the sum of the ASCII codes of every character from the start of
  the record up to and including the ``C``, modulo 32 (:func:`checksum`).

Lengths are whole millimetres; text is ASCII without ``@``; each record ends with CR LF.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FILE_EXTENSION = ".abs"
"""The guideline's file extension (Allgemeine Bewehrungs-Schnittstelle)."""


@dataclass
class BvbsHeader:
    """The record header's names: the project, the schedule (drawing) and its revision."""

    project: str = ""
    drawing: str = "BBS"
    revision: str = "0"


def checksum(text: str) -> int:
    """The BVBS checksum of ``text`` (the record from its start up to and including ``C``):
    96 - (sum of the ASCII codes) mod 32."""
    return 96 - sum(ord(c) for c in text) % 32


def _text(value: Any) -> str:
    """A field's text: ASCII, without the separator ``@`` and line breaks."""
    text = re.sub(r"[\r\n\t@]+", " ", str(value if value is not None else "")).strip()
    return text.encode("ascii", "replace").decode("ascii")


def _number(value: float) -> str:
    """A whole number when it is one, else up to two decimals ("90", "-45", "22.5")."""
    rounded = round(value, 2)
    if abs(rounded - round(rounded)) < 1e-9:
        return str(round(rounded))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def geometry(row: Any, shape: Any) -> str | None:
    """The ``G`` block of a schedule row (``row``: :class:`saengine.drawings.bbs.BbsRow`) from
    its standard's ``shape`` (the pack's :class:`BarShape`), or None when the shape has no BVBS
    geometry or its dimensions do not give one."""
    from saengine.drawings.bbs import evaluate

    steps = getattr(shape, "bvbs", None) if shape is not None else None
    if not steps:
        return None
    values: dict[str, float] = {"d": float(row.dia), "r": float(row.radius)}
    values.update({k: float(v) for k, v in row.dims.items()})
    for letter, default in (getattr(shape, "defaults", None) or {}).items():
        if letter not in values:
            try:
                values[letter] = evaluate(default, values)
            except ValueError:
                return None
    out = []
    for key, expression in steps:
        try:
            value = evaluate(expression, values)
        except (ValueError, ZeroDivisionError):
            return None
        if key in ("l", "r"):
            if value <= 0:
                return None
            out.append(f"{key}{round(value)}")
        else:
            out.append(f"w{_number(value)}")
    return "G" + "".join(f"{part}@" for part in out)


def record(row: Any, shape: Any, header: BvbsHeader, count: int | None = None) -> str:
    """One ``BF2D`` record (without its line end) of a schedule row; ``count``: the number of
    bars (default the row's total)."""
    from saengine.drawings.bbs import bar_mass

    n = row.total_count if count is None else count
    length = round(float(row.cutting_length))
    mass = float(row.cutting_length) / 1000 * bar_mass(float(row.dia))
    fields = [
        ("j", _text(header.project)),
        ("r", _text(header.drawing)),
        ("i", _text(header.revision)),
        ("p", _text(row.mark)),
        ("l", str(length)),
        ("n", str(int(n))),
        ("e", f"{mass:.3f}"),
        ("d", _number(float(row.dia))),
        ("g", _text(row.material)),
        ("s", str(round(2 * float(row.radius)))),
        ("v", ""),
    ]
    text = "BF2D@H" + "".join(f"{k}{v}@" for k, v in fields)
    text += geometry(row, shape) or ""
    text += "C"
    return f"{text}{checksum(text)}@"


def records(schedule: Any, header: BvbsHeader) -> tuple[list[str], list[str]]:
    """The records of a bar schedule, one per bar mark (the counts of its rows added), and
    notes: the marks sent without geometry, a mark scheduled with two shapes."""
    std = schedule.std
    by_mark: dict[str, list[Any]] = {}
    for row in schedule.rows:
        by_mark.setdefault(row.mark or row.element, []).append(row)
    out: list[str] = []
    notes: list[str] = []
    bare: list[str] = []
    for mark, rows in by_mark.items():
        first = rows[0]
        kinds = {
            (r.dia, r.shape, round(r.cutting_length), tuple(sorted(r.dims.items()))) for r in rows
        }
        if len(kinds) > 1:
            notes.append(
                f"Bar mark {mark}: scheduled with different shapes or sizes; its first is sent."
            )
        shape = std.shapes.get(first.shape)
        line = record(first, shape, header, sum(r.total_count for r in rows))
        if "@G" not in line:
            bare.append(f"{mark} (shape {first.shape})")
        out.append(line)
    if bare:
        notes.append(
            "Sent without geometry (the shape has no BVBS description; the operator enters it): "
            + ", ".join(bare)
            + "."
        )
    return out, notes


def write_bvbs(lines: Sequence[str], folder: str | Path, name: str) -> Path:
    """The records into ``folder/<name>.abs`` (ASCII, CR LF)."""
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]', "-", name).strip() or "BBS"
    path = out / f"{safe}{FILE_EXTENSION}"
    path.write_bytes("".join(f"{line}\r\n" for line in lines).encode("ascii", "replace"))
    return path

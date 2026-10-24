"""A table of library steel shapes for the importers' section lookup.

ETABS writes the shapes of its libraries (AISC14, Sections8, BSShapes, Indian ...) by name only
(``SHAPE "W14X90"``), so the importer needs a table to give them dimensions. Which table SAEngine
ships is the owner's decision; this module reads one in the comma-separated layout of FreeCAD's
profile presets (``Category,Name,class,dimensions in mm``) from wherever it is, and makes a
lookup for :func:`saengine.importers.etabs.read_e2k` of it:

    lookup = table_lookup(ProfileTable.read(path), fallback=section_lookup_noted)
    read_e2k(path, section_lookup=lookup)

Profile classes and their numbers: ``H`` (I and H shapes) width, height, web thickness, flange
thickness; ``RH`` (rectangular hollow) width, height, wall; ``C`` (circular hollow) outside
diameter, wall; ``U`` (channels) height, width, web thickness, flange thickness; ``L`` (angles)
height, width, thickness; ``T`` (tees) width, height, web thickness, flange thickness; ``R``
(solid rectangles) width, height. Root radii are not in such a table: the properties come from
the plate outline (reported). Names are matched without case, spaces and separators
(``W14X90`` = ``W14x90``, ``HE200A`` = ``HEA200``); an Indian name without its variant
(``ISHB150`` for ``ISHB150(1)``/``ISHB150(2)``) takes the first variant (reported).
"""

from __future__ import annotations

import csv
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: name -> profile JSON, or (profile JSON, the approximation made or None), or None (as
#: :data:`saengine.importers.etabs.SectionLookup`).
Lookup = Callable[[str], dict[str, Any] | tuple[dict[str, Any], str | None] | None]


def shape_key(name: str) -> str:
    """The form names are matched in: upper case, no spaces or separators, European HE names
    as HEA/HEB/HEM followed by the size."""
    key = re.sub(r"[\s_\-]+", "", name.upper()).replace("×", "X").replace("*", "X")
    m = re.fullmatch(r"HE(\d+)([ABM])", key)
    if m:
        key = f"HE{m.group(2)}{m.group(1)}"
    return key


def _profile(kind: str, d: list[float]) -> dict[str, Any] | None:
    """SAEngine profile JSON (04 Objects) of a table row's class and numbers [mm]."""
    try:
        if kind == "H":
            b, h, tw, tf = d[:4]
            return {
                "shape": "I",
                "overallWidth": b,
                "overallDepth": h,
                "webThickness": tw,
                "flangeThickness": tf,
            }
        if kind == "RH":
            b, h, t = d[:3]
            return {"shape": "rectangleHollow", "xDim": b, "yDim": h, "wallThickness": t}
        if kind == "C":
            od, t = d[:2]
            return {"shape": "circleHollow", "radius": od / 2, "wallThickness": t}
        if kind == "U":
            h, b, tw, tf = d[:4]
            return {
                "shape": "U",
                "depth": h,
                "flangeWidth": b,
                "webThickness": tw,
                "flangeThickness": tf,
            }
        if kind == "L":
            h, b, t = d[:3]
            return {"shape": "L", "depth": h, "width": b, "thickness": t}
        if kind == "T":
            b, h, tw, tf = d[:4]
            return {
                "shape": "T",
                "depth": h,
                "flangeWidth": b,
                "webThickness": tw,
                "flangeThickness": tf,
            }
        if kind == "R":
            b, h = d[:2]
            return {"shape": "rectangle", "xDim": b, "yDim": h}
    except ValueError:
        return None
    return None


@dataclass
class ProfileTable:
    """Shapes by :func:`shape_key` of their names: (category, name, profile JSON)."""

    label: str = "the profile table"
    shapes: dict[str, tuple[str, str, dict[str, Any]]] = field(default_factory=dict)

    @classmethod
    def parse(cls, lines: Iterable[str], label: str = "the profile table") -> ProfileTable:
        """The table of the rows ``Category,Name,class,numbers...`` (``#`` lines are comments;
        rows of unknown classes or with numbers that do not read are left out)."""
        table = cls(label)
        for row in csv.reader(line for line in lines if not line.lstrip().startswith("#")):
            if len(row) < 4:
                continue
            category, name, kind = (c.strip() for c in row[:3])
            try:
                numbers = [float(c) for c in row[3:] if c.strip()]
            except ValueError:
                continue
            if any(n <= 0 for n in numbers):
                continue
            profile = _profile(kind.upper(), numbers)
            if profile is not None:
                table.shapes.setdefault(shape_key(name), (category, name, profile))
        return table

    @classmethod
    def read(cls, path: str | Path, label: str | None = None) -> ProfileTable:
        path = Path(path)
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        return cls.parse(text.splitlines(), label or path.name)

    def find(self, name: str) -> tuple[dict[str, Any], str | None] | None:
        """The profile of ``name`` and the approximation made, or None."""
        key = shape_key(name)
        found = self.shapes.get(key)
        variant = None
        if found is None:
            found = self.shapes.get(f"{key}(1)")
            variant = f" ({found[1]}: the first variant of the name)" if found else None
        if found is None:
            return None
        return dict(found[2]), f"from {self.label}, root radius ignored{variant or ''}"


def table_lookup(table: ProfileTable, fallback: Lookup | None = None) -> Lookup:
    """A section lookup that asks ``table`` first, then ``fallback`` (e.g.
    :func:`saengine.importers.project.section_lookup_noted`, which estimates W, UB and UC
    names it cannot find, flagged "estimated — check")."""

    def lookup(name: str) -> dict[str, Any] | tuple[dict[str, Any], str | None] | None:
        found = table.find(name)
        if found is not None:
            return found
        return fallback(name) if fallback is not None else None

    return lookup


__all__ = ["Lookup", "ProfileTable", "shape_key", "table_lookup"]

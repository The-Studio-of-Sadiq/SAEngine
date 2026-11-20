"""Keynote catalogue and per-sheet used-key legend."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from saengine.drawings.sheets.layout import read_tags
from saengine.drawings.sheets.model import Table

STARTER_KEYNOTES = Path(__file__).resolve().parents[2] / "library" / "keynotes.json"


def load_keynotes(path: str | Path = STARTER_KEYNOTES) -> dict[str, str]:
    """Load a JSON object mapping stable keynote keys to their descriptions."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or any(
        not isinstance(key, str) or not key or not isinstance(text, str) or not text
        for key, text in data.items()
    ):
        raise ValueError("the keynote file must map non-empty keys to non-empty descriptions")
    return data


def used_keynotes(doc: Any) -> set[str]:
    """The element and material keynote keys actually tagged in model space."""
    used: set[str] = set()
    for entity in doc.modelspace():
        tags = read_tags(entity)
        used.update(key for tag in ("keynote", "materialKeynote") if (key := tags.get(tag)))
    return used


def keynote_legend(doc: Any, keynotes: dict[str, str]) -> Table:
    """A keynote table containing only keys actually used on ``doc``."""
    used = used_keynotes(doc)
    missing = sorted(used - keynotes.keys())
    if missing:
        raise ValueError(f"keynote descriptions are missing for: {', '.join(missing)}")
    return Table(
        "Keynote legend",
        [
            {"key": "key", "title": "Key", "width": 10},
            {"key": "description", "title": "Description", "width": 48},
        ],
        [[key, keynotes[key]] for key in sorted(used)],
    )


def place_keynote_legend(sheet: Any, keynotes: dict[str, str]) -> list[Any]:
    """Draw the sheet's used-key legend with the shared schedule-table renderer."""
    table = keynote_legend(sheet.doc, keynotes)
    if not table.rows:
        return []
    from saengine.drawings.sheets.schedules import table_specs

    specs = table_specs(
        table,
        sheet.area[3] - sheet.area[1],
        key="keynote-legend",
        max_width=sheet.area[2] - sheet.area[0],
    )
    return [sheet.view(spec, *sheet.area[:2]) for spec in specs]


__all__ = [
    "STARTER_KEYNOTES",
    "keynote_legend",
    "load_keynotes",
    "place_keynote_legend",
    "used_keynotes",
]

"""Structural drawing sheets (11 Exports, drawings): framing and slab plans, the column
schedule, beam elevations, footing, wall and stair details, the bar bending schedule and the
general notes, each sheet one DXF (ezdxf) for AutoCAD or LibreCAD, all sheets one PDF with PNG
previews. Layers, linetypes, text and plotting: docs/drawings-layers.md.

How it is called::

    from saengine.drawings.sheets import DrawingSettings, build_sheets, drawing_set, write_drawings

    data = drawing_set(project_root, title={"firm": ..., "checked": ...})
    sheets = build_sheets(data, DrawingSettings.from_dict({"size": "A1"}))
    result = write_drawings(sheets, project_root / "11 Exports" / "Drawings", problems=data.problems)

See :mod:`.layout` (sheets, title block, layers, styles), :mod:`.plans`, :mod:`.schedules`,
:mod:`.details`, :mod:`.project` (the project's data) and :mod:`.render` (PDF and PNG).
"""

from saengine.drawings.sheets.build import (
    DrawingSettings,
    build_sheets,
    categories,
    write_drawings,
)
from saengine.drawings.sheets.layout import LAYERS, PAPER, Sheet, TitleInfo
from saengine.drawings.sheets.model import DrawingSet
from saengine.drawings.sheets.project import drawing_set

__all__ = [
    "LAYERS",
    "PAPER",
    "DrawingSet",
    "DrawingSettings",
    "Sheet",
    "TitleInfo",
    "build_sheets",
    "categories",
    "drawing_set",
    "write_drawings",
]

"""Drawing sheets (11 Exports, drawings): framing and slab plans, the column schedule, beam
elevations, footing, wall and stair details, the bar bending schedule and the general notes;
the architectural plans, elevations, sections and schedules of the architecture; each sheet one DXF (ezdxf) for AutoCAD or LibreCAD, all sheets one PDF with PNG
previews. Layers, linetypes, text and plotting: docs/drawings-layers.md.

How it is called::

    from saengine.drawings.sheets import DrawingSettings, build_sheets, drawing_set, write_drawings

    data = drawing_set(project_root, title={"firm": ..., "checked": ...})
    sheets = build_sheets(data, DrawingSettings.from_dict({"size": "A1"}))
    result = write_drawings(sheets, project_root / "11 Exports" / "Drawings", problems=data.problems)

See :mod:`.layout` (sheets, title block, layers, styles), :mod:`.plans`, :mod:`.schedules`,
:mod:`.details`, :mod:`.architecture`, :mod:`.project` (the project's data) and :mod:`.render` (PDF and PNG).
"""

from saengine.drawings.sheets.build import (
    DrawingSettings,
    build_sheets,
    categories,
    write_drawings,
)
from saengine.drawings.sheets.documentation import (
    Callout,
    DependentPlan,
    ScopeBox,
    build_dependent_plans,
    create_callout,
    documentation_legend,
    place_documentation_legend,
    update_callout_reference,
)
from saengine.drawings.sheets.keynotes import (
    keynote_legend,
    load_keynotes,
    place_keynote_legend,
    used_keynotes,
)
from saengine.drawings.sheets.layout import LAYERS, PAPER, Sheet, TitleInfo
from saengine.drawings.sheets.model import DrawingSet
from saengine.drawings.sheets.project import drawing_set
from saengine.drawings.sheets.schedule_builder import ScheduleResult, build_schedule

__all__ = [
    "LAYERS",
    "PAPER",
    "Callout",
    "DependentPlan",
    "DrawingSet",
    "DrawingSettings",
    "ScheduleResult",
    "ScopeBox",
    "Sheet",
    "TitleInfo",
    "build_dependent_plans",
    "build_schedule",
    "build_sheets",
    "categories",
    "create_callout",
    "documentation_legend",
    "drawing_set",
    "keynote_legend",
    "load_keynotes",
    "place_documentation_legend",
    "place_keynote_legend",
    "update_callout_reference",
    "used_keynotes",
    "write_drawings",
]

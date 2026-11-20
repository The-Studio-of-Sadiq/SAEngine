"""Generated scope-box views, callouts and sheet documentation legends.

These are generated sheet views and references, not editable view templates or visibility
overrides. Model coordinates and crop rectangles are millimetres, as in the drawing model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from saengine.drawings.sheets.layout import (
    APP_ID,
    HATCH_SCALES,
    TEXT,
    TEXT_LARGE,
    Sheet,
    View,
    ViewSpec,
    read_tags,
)
from saengine.drawings.sheets.model import Building, Table
from saengine.drawings.sheets.plans import framing_plan
from saengine.drawings.sheets.schedules import table_specs


@dataclass(frozen=True)
class ScopeBox:
    """A named plan crop in model millimetres, applied to the listed level ids."""

    name: str
    bounds: tuple[float, float, float, float]
    levels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        x0, y0, x1, y1 = self.bounds
        if not self.name.strip() or x1 <= x0 or y1 <= y0:
            raise ValueError("a scope box needs a name and a positive-area rectangle")


@dataclass
class DependentPlan:
    scope: ScopeBox
    level: str
    sheet: Sheet
    view: View


def _key_plan(sheet: Sheet, scope: ScopeBox, overall: tuple[float, float, float, float]) -> None:
    """Draw the building outline and the current crop in the title block's notes area."""
    x0, y0, x1, y1 = sheet.notes_box
    box_width, box_height = x1 - x0 - 12, y1 - y0 - 60
    if box_width <= 4 or box_height <= 4:
        return
    ox0, oy0, ox1, oy1 = overall
    width, height = max(ox1 - ox0, 1), max(oy1 - oy0, 1)
    factor = min(box_width / width, box_height / height)
    dx, dy = (box_width - width * factor) / 2, (box_height - height * factor) / 2

    def paper(point: tuple[float, float]) -> tuple[float, float]:
        return x0 + 6 + dx + (point[0] - ox0) * factor, y0 + 6 + dy + (point[1] - oy0) * factor

    a, b = paper((ox0, oy0)), paper((ox1, oy1))
    sheet.p_rect(*a, *b, "S-TITLE", lineweight=18)
    sx0, sy0 = paper((scope.bounds[0], scope.bounds[1]))
    sx1, sy1 = paper((scope.bounds[2], scope.bounds[3]))
    sheet.p_rect(sx0, sy0, sx1, sy1, "S-TITLE", lineweight=35)
    hatch = sheet.msp.add_hatch(color=8, dxfattribs={"layer": "S-TITLE"})
    hatch.paths.add_polyline_path(
        [sheet.m(sx0, sy0), sheet.m(sx1, sy0), sheet.m(sx1, sy1), sheet.m(sx0, sy1)],
        is_closed=True,
    )
    hatch.set_pattern_fill("ANSI31", color=8, scale=HATCH_SCALES["ANSI31"] * sheet.scale)
    sheet.p_text("KEY PLAN", x0 + 2, y1 - 4, TEXT, "TL", "S-TITLE")
    sheet.p_text(scope.name, x0 + 2, y0 + 2, TEXT, "BL", "S-TITLE")


def _shared_edge(
    a: ScopeBox, b: ScopeBox
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Return the common edge segment of two axis-aligned scope boxes."""
    ax0, ay0, ax1, ay1 = a.bounds
    bx0, by0, bx1, by1 = b.bounds
    if math.isclose(ax1, bx0, abs_tol=1e-6) or math.isclose(bx1, ax0, abs_tol=1e-6):
        x = ax1 if math.isclose(ax1, bx0, abs_tol=1e-6) else ax0
        low, high = max(ay0, by0), min(ay1, by1)
        if high > low:
            return (x, low), (x, high)
    if math.isclose(ay1, by0, abs_tol=1e-6) or math.isclose(by1, ay0, abs_tol=1e-6):
        y = ay1 if math.isclose(ay1, by0, abs_tol=1e-6) else ay0
        low, high = max(ax0, bx0), min(ax1, bx1)
        if high > low:
            return (low, y), (high, y)
    return None


def _matchline(
    plan: DependentPlan, edge: tuple[tuple[float, float], tuple[float, float]], reference: str
) -> None:
    a, b = edge
    plan.view.line(a, b, "S-GRID", linetype="DASHED")
    midpoint = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    plan.view.label(
        f"MATCHLINE - SEE SHEET {reference}",
        midpoint,
        [(0, 5, "BC"), (0, -5, "TC"), (5, 0, "ML"), (-5, 0, "MR")],
        height=TEXT,
        force=True,
        layer="S-TEXT",
    )


def build_dependent_plans(
    building: Building,
    scope_boxes: list[ScopeBox],
    *,
    size: str = "A1",
    scale: float = 100,
    prefix: str = "S-",
    first: int = 101,
    title_info: Any = None,
    standard: Any = None,
) -> list[DependentPlan]:
    """Build one cropped framing-plan sheet for each applicable scope box and level.

    Shared edges receive matchlines on both sheets with the other sheet's current number.
    """
    from saengine.drawings.sheets.layout import TitleInfo

    if not scope_boxes:
        return []
    if len({box.name for box in scope_boxes}) != len(scope_boxes):
        raise ValueError("scope box names must be unique")
    info = title_info or TitleInfo()
    plans: list[DependentPlan] = []
    number = first
    for box in scope_boxes:
        for level in sorted(building.levels, key=lambda item: item.elevation):
            if box.levels and level.id not in box.levels:
                continue
            number_text = f"{prefix}{number:03d}"
            number += 1
            spec = framing_plan(building, level, scale, box.bounds)
            spec.title = f"{spec.title} - {box.name}"
            spec.key = f"dependent:{level.id}:{box.name}"
            sheet = Sheet(number_text, spec.title, size, scale, info, standard=standard)
            view = sheet.view(spec, *sheet.area[:2])
            plans.append(DependentPlan(box, level.id, sheet, view))
    if not plans:
        return []
    overall = (
        min(box.bounds[0] for box in scope_boxes),
        min(box.bounds[1] for box in scope_boxes),
        max(box.bounds[2] for box in scope_boxes),
        max(box.bounds[3] for box in scope_boxes),
    )
    for plan in plans:
        _key_plan(plan.sheet, plan.scope, overall)
    for i, left in enumerate(plans):
        for right in plans[i + 1 :]:
            if left.level != right.level:
                continue
            edge = _shared_edge(left.scope, right.scope)
            if edge is None:
                continue
            _matchline(left, edge, right.sheet.number)
            _matchline(right, edge, left.sheet.number)
    return plans


@dataclass
class Callout:
    """A plan/section callout whose displayed reference is resolved from its target sheet."""

    number: str
    parent: View
    bounds: tuple[float, float, float, float]
    detail_sheet: Sheet
    detail: ViewSpec
    _entities: list[Any] | None = None
    _detail_view: View | None = None

    @property
    def reference(self) -> str:
        return f"{self.number} / {self.detail_sheet.number}"

    def render(self) -> View:
        """Draw or refresh the parent reference, then place the detail on its target sheet."""
        for entity in self._entities or []:
            if entity.is_alive:
                self.parent.sheet.msp.delete_entity(entity)
        before = {entity.dxf.handle for entity in self.parent.sheet.msp.query("TEXT")}
        x0, y0, x1, y1 = self.bounds
        self._entities = []
        rect = self.parent.polyline(
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            "A-ANNO-SYMB",
            close=True,
        )
        self._entities.append(rect)
        radius = self.parent.real(TEXT_LARGE)
        centre = (x1, y1)
        bubble = self.parent.circle(centre, radius, "A-ANNO-SYMB")
        self._entities.append(bubble)
        point = self.parent.p(*centre)
        self.parent.sheet.p_text(self.number, *point, TEXT, "MC", "A-ANNO-SYMB")
        self.parent.sheet.p_text(
            self.reference, point[0] + TEXT_LARGE, point[1] + TEXT_LARGE, TEXT, "BL", "S-TEXT"
        )
        self._entities.extend(
            entity
            for entity in self.parent.sheet.msp.query("TEXT")
            if entity.dxf.handle not in before
        )
        for entity in self._entities:
            entity.set_xdata(
                APP_ID,
                [(1000, f"callout={self.number}"), (1000, f"target={self.detail_sheet.number}")],
            )
        if self._detail_view is None:
            self._detail_view = self.detail_sheet.view(self.detail, *self.detail_sheet.area[:2])
        return self._detail_view


def create_callout(
    parent: View,
    bounds: tuple[float, float, float, float],
    detail_sheet: Sheet,
    detail: ViewSpec,
    number: str,
) -> Callout:
    """Create the generated detail view and parent bubble at ``detail.scale``."""
    if not number.strip() or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
        raise ValueError("a callout needs a number and a positive-area rectangle")
    callout = Callout(number, parent, bounds, detail_sheet, detail)
    callout.render()
    return callout


def update_callout_reference(callout: Callout, new_sheet_number: str) -> None:
    """Renumber the callout target and redraw its parent text/reference."""
    callout.detail_sheet.number = new_sheet_number
    callout.render()


def documentation_legend(doc: Any) -> Table:
    """List only the line types, hatch patterns, blocks and tag kinds present in this DXF."""
    msp = doc.modelspace()
    layers = {str(layer.dxf.name): str(layer.dxf.linetype) for layer in doc.layers}
    used_linetypes = {
        str(entity.dxf.get("linetype", "BYLAYER"))
        if str(entity.dxf.get("linetype", "BYLAYER")).upper() not in ("BYLAYER", "BYBLOCK")
        else layers.get(str(entity.dxf.get("layer", "0")), "Continuous")
        for entity in msp
        if entity.dxftype() in {"LINE", "LWPOLYLINE", "ARC", "CIRCLE"}
    }
    used_hatches: set[str] = set()
    used_blocks: set[str] = set()
    used_tags: set[str] = set()
    for entity in msp:
        if entity.dxftype() == "HATCH":
            used_hatches.add(str(entity.dxf.get("pattern_name", "SOLID")))
        elif entity.dxftype() == "INSERT":
            used_blocks.add(str(entity.dxf.name))
        tags = read_tags(entity)
        for key in ("mark", "id", "keynote", "materialKeynote", "symbol"):
            if tags.get(key):
                used_tags.add(key)
    rows = (
        [["Linetype", value, ""] for value in sorted(used_linetypes)]
        + [["Hatch", value, ""] for value in sorted(used_hatches)]
        + [["Symbol", value, ""] for value in sorted(used_blocks)]
        + [["Tag", value, ""] for value in sorted(used_tags)]
    )
    return Table(
        "Drawing legend",
        [
            {"key": "kind", "title": "Type", "width": 10},
            {"key": "name", "title": "Name", "width": 20},
            {"key": "notes", "title": "Used on this sheet"},
        ],
        rows,
    )


def place_documentation_legend(sheet: Sheet) -> list[View]:
    """Place the generated legend table(s) using the existing schedule table renderer."""
    table = documentation_legend(sheet.doc)
    specs = table_specs(
        table,
        sheet.area[3] - sheet.area[1],
        key="drawing-legend",
        max_width=sheet.area[2] - sheet.area[0],
    )
    return [sheet.view(spec, *sheet.area[:2]) for spec in specs]


__all__ = [
    "Callout",
    "DependentPlan",
    "ScopeBox",
    "build_dependent_plans",
    "create_callout",
    "documentation_legend",
    "place_documentation_legend",
    "update_callout_reference",
]

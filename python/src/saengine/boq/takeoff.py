"""2D takeoff from PDF drawings into the bill of quantities (alpha 9 L11).

Some quantities are not in the model: external works, a fence, a boundary wall, paving, items on
a drawing someone else made. ``10 BOQ/takeoff.json`` (:class:`Takeoff`) keeps lengths, areas and
counts measured on the pages of PDF drawings, shown as an underlay with
:mod:`saengine.library.pdf_underlay` (its paper millimetres are the coordinates here):

- each sheet (a PDF page) is calibrated to scale from two points and the known length between
  them (``Calibration``), or takes a drawing scale "1:N" (the page's stated scale by default);
- an item is a polyline (length, m), a polygon (area, m²) or a set of marks (count, nr), and may
  turn into another unit: a length times a height (m², e.g. a fence's face) or an area times a
  depth (m³, e.g. a paving's base);
- :func:`bill_items` turns the items into bill items "measured from drawing" (``origin:
  "drawing"``), grouped by group, description and unit, each item's share in its breakdown
  (``element`` the takeoff item's id, ``detail`` the sheet and page), so the costing, the
  workbook and the 4D programme price, list and schedule them as any other. They are added when
  the bill is computed (:func:`saengine.boq.quantities.compute_boq`); the materials take-off of
  the bill does not include them.
"""

from __future__ import annotations

import itertools
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA = "saengine.takeoff/1"
TAKEOFF_FILE = "10 BOQ/takeoff.json"
#: Code letter of the bill items measured from drawings, after the group's letter ("E.D01").
CODE_LETTER = "D"

Point = list[float]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Calibration(_Model):
    """Two points on the page [paper mm] and the true length between them [mm]."""

    a: Point = Field(min_length=2, max_length=2)
    b: Point = Field(min_length=2, max_length=2)
    length: float = Field(gt=0, description="True length between the two points [mm].")


class Sheet(_Model):
    id: str
    file: str = Field(description="The PDF, relative to the project folder (or absolute).")
    page: int = Field(default=1, ge=1)
    name: str = ""
    calibration: Calibration | None = None
    scale: float | None = Field(
        default=None, gt=0, description="Drawing scale 1:N (N), when not calibrated."
    )


class TakeoffItem(_Model):
    id: str
    sheet: str
    kind: Literal["length", "area", "count"]
    points: list[Point] = Field(min_length=1, description="Paper mm on the sheet's page.")
    description: str = Field(min_length=1)
    group: Literal[
        "earthwork", "concrete", "masonry", "finishes", "reinforcement", "formwork", "steel",
        "mep",
    ] = "finishes"  # fmt: skip
    kind_: str | None = Field(
        default=None, alias="elementKind", description="Kind of work (paving, fence, ...)."
    )
    material: str | None = None
    story: str | None = None
    height: float | None = Field(
        default=None, gt=0, description="A length times this [mm] gives an area (m²)."
    )
    depth: float | None = Field(
        default=None, gt=0, description="An area times this [mm] gives a volume (m³)."
    )
    multiplier: float = Field(default=1, gt=0, description="How many times it occurs.")
    deduct: bool = Field(default=False, description="Subtracted from its line (an opening).")

    @model_validator(mode="after")
    def _shape(self) -> TakeoffItem:
        if self.kind == "length" and len(self.points) < 2:
            raise ValueError(f"{self.id}: a length needs at least 2 points")
        if self.kind == "area" and len(self.points) < 3:
            raise ValueError(f"{self.id}: an area needs at least 3 points")
        return self


class Takeoff(_Model):
    schema_: Literal["saengine.takeoff/1"] = Field(default=SCHEMA, alias="schema")
    sheets: list[Sheet] = Field(default_factory=list)
    items: list[TakeoffItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _refs(self) -> Takeoff:
        sheets = {s.id for s in self.sheets}
        for item in self.items:
            if item.sheet not in sheets:
                raise ValueError(f"{item.id}: no sheet '{item.sheet}'")
        ids = [i.id for i in self.items]
        twice = sorted({i for i in ids if ids.count(i) > 1})
        if twice:
            raise ValueError(f"duplicate takeoff ids: {', '.join(twice)}")
        return self


# ─────────────────────────────────── measuring ───────────────────────────────────


class NotCalibrated(ValueError):
    pass


def scale_of(sheet: Sheet) -> float:
    """True mm per paper mm of the sheet: its calibration, else its drawing scale."""
    if sheet.calibration is not None:
        c = sheet.calibration
        paper = math.dist(c.a, c.b)
        if paper <= 0:
            raise NotCalibrated(f"sheet {sheet.id}: the calibration's two points are the same")
        return c.length / paper
    if sheet.scale is not None:
        return float(sheet.scale)
    raise NotCalibrated(f"sheet {sheet.id} is not calibrated: give two points and their length")


def polyline_length(points: list[Point]) -> float:
    return sum(math.dist(a, b) for a, b in itertools.pairwise(points))


def polygon_area(points: list[Point]) -> float:
    """Shoelace area (absolute) of a closed polygon."""
    n = len(points)
    twice = sum(
        points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1]
        for i in range(n)
    )
    return abs(twice) / 2


def measure(item: TakeoffItem, sheet: Sheet) -> tuple[float, str]:
    """The item's quantity and its bill unit: length m, area m² (a length with a height), volume
    m³ (an area with a depth), count nr; times its multiplier, negative when it deducts."""
    k = scale_of(sheet)
    if item.kind == "count":
        quantity, unit = float(len(item.points)), "nr"
    elif item.kind == "length":
        quantity, unit = polyline_length(item.points) * k / 1e3, "m"
        if item.height is not None:
            quantity, unit = quantity * item.height / 1e3, "m2"
    else:
        quantity, unit = polygon_area(item.points) * k * k / 1e6, "m2"
        if item.depth is not None:
            quantity, unit = quantity * item.depth / 1e3, "m3"
    quantity *= item.multiplier
    return (-quantity if item.deduct else quantity), unit


def parse(text: str | None) -> Takeoff | None:
    if not text or not text.strip():
        return None
    return Takeoff.model_validate_json(text)


def bill_items(takeoff: Takeoff, groups: dict[str, str]) -> tuple[list[dict[str, Any]], list[str]]:
    """The bill items of the takeoff (JSON-ready, the shape of ``BoqItem``) and notes.
    ``groups``: the code letter of each group (``saengine.boq.quantities.GROUPS``)."""
    sheets = {s.id: s for s in takeoff.sheets}
    lines: dict[tuple[str, str, str, str | None, str | None], dict[str, Any]] = {}
    notes: list[str] = []
    for item in takeoff.items:
        sheet = sheets[item.sheet]
        try:
            quantity, unit = measure(item, sheet)
        except NotCalibrated as error:
            notes.append(f"takeoff item {item.id} not measured: {error}")
            continue
        key = (item.group, item.description, unit, item.material, item.kind_)
        line = lines.setdefault(
            key,
            {
                "group": item.group,
                "description": item.description,
                "unit": unit,
                "material": item.material,
                "kind": item.kind_,
                "byStory": {},
                "breakdown": [],
                "quantity": 0.0,
            },
        )
        line["quantity"] += quantity
        if item.story:
            line["byStory"][item.story] = line["byStory"].get(item.story, 0.0) + quantity
        line["breakdown"].append(
            {
                "element": item.id,
                **({"story": item.story} if item.story else {}),
                "detail": f"measured from drawing: {sheet.name or sheet.file} p{sheet.page}",
                "quantity": round(quantity, 3),
            }
        )
    order = list(groups)
    out: list[dict[str, Any]] = []
    numbers: dict[str, int] = {}
    for line in sorted(
        lines.values(), key=lambda li: (order.index(li["group"]), li["description"])
    ):
        if line["quantity"] <= 0:
            notes.append(
                f"takeoff line '{line['description']}' adds up to {line['quantity']:.3f} "
                f"{line['unit']} (its deductions exceed it): left out"
            )
            continue
        group = line["group"]
        numbers[group] = numbers.get(group, 0) + 1
        item = {
            "code": f"{groups[group]}.{CODE_LETTER}{numbers[group]:02d}",
            "group": group,
            "description": f"{line['description']} (measured from drawing)",
            "quantity": round(line["quantity"], 3),
            "unit": line["unit"],
            "origin": "drawing",
            "byStory": {s: round(q, 3) for s, q in line["byStory"].items()},
            "breakdown": line["breakdown"],
        }
        if line["material"]:
            item["material"] = line["material"]
        if line["kind"]:
            item["kind"] = line["kind"]
        out.append(item)
    if out:
        notes.append(
            f"{len(out)} item(s) measured from drawings (10 BOQ/takeoff.json): lengths, areas and "
            "counts on calibrated PDF pages, not from the model; they are not in the materials "
            "take-off"
        )
    return out, notes


def calibrate(a: Point, b: Point, length: float) -> dict[str, Any]:
    """The calibration of two points [paper mm] and the true length between them [mm], with
    the scale it gives (true mm per paper mm, "1:N")."""
    calibration = Calibration(a=a, b=b, length=length)
    k = scale_of(Sheet(id="_", file="", calibration=calibration))
    return {"calibration": calibration.model_dump(), "scale": k}


def summary(text: str) -> dict[str, Any]:
    """Every item of a takeoff text measured: ``{"items": [{id, quantity, unit} | {id,
    problem}], "lines", "notes"}`` or ``{"problems"}`` (for the takeoff editor)."""
    from saengine.boq.quantities import GROUPS

    try:
        takeoff = Takeoff.model_validate_json(text)
    except ValueError as error:
        return {"problems": [str(error).strip().splitlines()[0]]}
    sheets = {s.id: s for s in takeoff.sheets}
    items = []
    for item in takeoff.items:
        try:
            quantity, unit = measure(item, sheets[item.sheet])
            items.append({"id": item.id, "quantity": round(quantity, 3), "unit": unit})
        except NotCalibrated as error:
            items.append({"id": item.id, "problem": str(error)})
    lines, notes = bill_items(takeoff, GROUPS)
    return {"items": items, "lines": lines, "notes": notes}

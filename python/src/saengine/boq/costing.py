"""The cost and the embodied carbon of the bill of quantities (Part 10).

The rates are a schedule of rates kept with the project (``10 BOQ/rates.json``,
:class:`RateSchedule`): chapters and items as a schedule of rates lays them out (item number,
description, unit, rate), each naming the bill items it prices (:class:`Match`). The app ships
only a sample with made-up rates (``data/rates-sample.json``): real schedules (for example the
PWD schedule of rates of Bangladesh) are the publisher's and change with every edition, so the
user enters or imports their own.

The carbon factors (``10 BOQ/carbon-factors.json``, :class:`CarbonFactors`) are kg CO2e per kg
of material from public sources cited per factor (``data/carbon-factors.json``), editable. They
are applied to the materials of the bill (cement, sand and stone of the materials take-off,
reinforcement, structural steel, brick work), never to the concrete items, whose cement is
counted already.

How it is called::

    costing = cost_bill(bill, rates, carbon)  # a dict of the bill (boq.json), the two schedules
    costing.total, costing.parts, costing.carbonTotal

Costing per item: ``amount = quantity × units of the rate per unit of the bill × rate``
(:func:`conversion`); per part (:func:`part_of`) and per group of the bill; in total.
"""

from __future__ import annotations

import json
import re
from functools import cache
from importlib import resources
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from saengine.boq.quantities import CFT, GROUPS, SAND_DENSITY, STONE_DENSITY

RATES_SCHEMA = "saengine.rates/1"
CARBON_SCHEMA = "saengine.carbon/1"
RATES_FILE = "rates.json"
CARBON_FILE = "carbon-factors.json"

SQFT = 10.7639104  # square feet per m²
FT = 3.2808399  # feet per m

#: Units a rate may be quoted in: (the bill's unit it measures, units of it per bill unit).
UNITS: dict[str, tuple[str, float]] = {
    "m3": ("m3", 1.0),
    "cum": ("m3", 1.0),
    "cft": ("m3", CFT),
    "m2": ("m2", 1.0),
    "sqm": ("m2", 1.0),
    "sft": ("m2", SQFT),
    "m": ("m", 1.0),
    "rm": ("m", 1.0),
    "rft": ("m", FT),
    "kg": ("kg", 1.0),
    "t": ("kg", 1e-3),
    "quintal": ("kg", 1e-2),
    "nr": ("nr", 1.0),
    "each": ("nr", 1.0),
    "bag": ("bag", 1.0),
    "l": ("l", 1.0),
}

#: The part of the project a bill entry belongs to, by the element kind measured.
SUBSTRUCTURE_KINDS = {"excavation", "backfill", "blinding", "footing", "pileCap", "pile", "raft",
                      "tieBeam"}  # fmt: skip
ARCHITECTURE_KINDS = {"door", "window", "plaster", "filling"}
PARTS = ("Superstructure", "Substructure", "Architecture", "MEP")

#: Loose densities of the materials take-off's kinds [kg/m³], when a factor gives none.
DENSITIES = {"sand": SAND_DENSITY, "stone": STONE_DENSITY}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Match(_Model):
    """Which bill items a rate or a factor applies to: all that is given must hold."""

    group: str | None = Field(default=None, description="Group of the bill (concrete, ...).")
    kind: list[str] | None = Field(default=None, description="Element or material kinds.")
    material: list[str] | None = Field(default=None, description="Material ids of 03 Materials.")
    diameter: tuple[float, float] | None = Field(
        default=None, description="Bar diameters [mm], from and to, both included."
    )
    unit: str | None = Field(default=None, description="The bill item's unit.")
    description: str | None = Field(
        default=None, description="A pattern the item's description contains (case ignored)."
    )

    def holds(self, item: dict[str, Any]) -> bool:
        if self.group is not None and item.get("group") != self.group:
            return False
        if self.kind is not None and item.get("kind") not in self.kind:
            return False
        if self.material is not None and item.get("material") not in self.material:
            return False
        if self.unit is not None and item.get("unit") != self.unit:
            return False
        if self.diameter is not None:
            dia = item.get("diameter")
            if dia is None or not self.diameter[0] <= float(dia) <= self.diameter[1]:
                return False
        if self.description is not None:
            try:
                found = re.search(self.description, str(item.get("description", "")), re.IGNORECASE)
            except re.error:
                found = self.description.lower() in str(item.get("description", "")).lower()
            if not found:
                return False
        return True


class Chapter(_Model):
    code: str
    title: str


class RateItem(_Model):
    """An item of the schedule of rates."""

    code: str = Field(description="Item number of the schedule.")
    description: str
    unit: str = Field(description="Unit of the rate (see UNITS).")
    rate: float | None = Field(default=None, description="Rate per unit; empty: not rated.")
    match: Match = Field(default_factory=Match)


class RateSchedule(_Model):
    schema_: Literal["saengine.rates/1"] = Field(default=RATES_SCHEMA, alias="schema")
    name: str = ""
    currency: str = "BDT"
    edition: str = ""
    notes: list[str] = Field(default_factory=list)
    chapters: list[Chapter] = Field(default_factory=list)
    items: list[RateItem] = Field(default_factory=list)

    def chapter_of(self, code: str) -> Chapter | None:
        """The chapter whose code begins the item number ("03" of "03.02")."""
        best = None
        for chapter in self.chapters:
            if code.startswith(chapter.code) and (
                best is None or len(chapter.code) > len(best.code)
            ):
                best = chapter
        return best


class CarbonFactor(_Model):
    id: str
    material: str
    factor: float | None = Field(default=None, description="kg CO2e per kg; empty: not counted.")
    density: float | None = Field(
        default=None, description="kg/m³, to turn items in m³ or cft into kg."
    )
    match: Match = Field(default_factory=Match)
    source: str = ""


class CarbonFactors(_Model):
    schema_: Literal["saengine.carbon/1"] = Field(default=CARBON_SCHEMA, alias="schema")
    name: str = ""
    notes: list[str] = Field(default_factory=list)
    factors: list[CarbonFactor] = Field(default_factory=list)


# ─────────────────────────────────── results ───────────────────────────────────


class CostLine(_Model):
    """One bill item, priced."""

    code: str
    group: str
    description: str
    quantity: float
    unit: str
    rateCode: str | None = None
    rateDescription: str | None = None
    rateUnit: str | None = None
    rate: float | None = None
    conversion: float | None = Field(
        default=None, description="Units of the rate per unit of the bill item."
    )
    amount: float | None = None
    byPart: dict[str, float] = Field(default_factory=dict)
    status: Literal["priced", "not rated", "no rate item", "unit mismatch"] = "no rate item"


class CarbonLine(_Model):
    """One material's embodied carbon."""

    id: str
    material: str
    factor: float | None
    mass: float = Field(description="kg of the material in the bill.")
    carbon: float | None = Field(default=None, description="kg CO2e.")
    items: list[str] = Field(default_factory=list, description="Codes of the bill items.")
    byPart: dict[str, float] = Field(default_factory=dict)
    source: str = ""


class Costing(_Model):
    currency: str
    rateSchedule: str
    lines: list[CostLine] = Field(default_factory=list)
    groups: dict[str, float] = Field(default_factory=dict)
    parts: dict[str, float] = Field(default_factory=dict)
    total: float = 0.0
    carbon: list[CarbonLine] = Field(default_factory=list)
    carbonParts: dict[str, float] = Field(default_factory=dict)
    carbonTotal: float = Field(default=0.0, description="kg CO2e.")
    notes: list[str] = Field(default_factory=list)


# ─────────────────────────────────── data ───────────────────────────────────


def _data(name: str) -> str:
    return resources.files("saengine.boq").joinpath("data", name).read_text(encoding="utf-8")


@cache
def sample_rates_text() -> str:
    """The sample schedule of rates (made-up rates), as the project's ``rates.json`` starts."""
    return _data("rates-sample.json")


@cache
def default_carbon_text() -> str:
    """The carbon factors shipped, as the project's ``carbon-factors.json`` starts."""
    return _data("carbon-factors.json")


def parse_rates(text: str | None) -> RateSchedule:
    """The schedule of ``text``, or the sample when there is none (ValueError when invalid)."""
    return RateSchedule.model_validate_json(text if text and text.strip() else sample_rates_text())


def parse_carbon(text: str | None) -> CarbonFactors:
    """The factors of ``text``, or those shipped when there are none (ValueError when invalid)."""
    return CarbonFactors.model_validate_json(
        text if text and text.strip() else default_carbon_text()
    )


# ─────────────────────────────────── costing ───────────────────────────────────


def conversion(rate_unit: str, item_unit: str) -> float | None:
    """Units of the rate per unit of the bill item (35.3147 for a rate per cft and an item in
    m³), or None when they measure different things."""
    if rate_unit == item_unit:
        return 1.0
    rate, item = UNITS.get(rate_unit), UNITS.get(item_unit)
    if rate is None or item is None or rate[0] != item[0]:
        return None
    return rate[1] / item[1]


def part_of(group: str, kind: str | None) -> str | None:
    """The part an entry of this group and kind belongs to; None: decided by its element."""
    if group == "mep":
        return "MEP"
    if group in ("masonry", "finishes") or kind in ARCHITECTURE_KINDS:
        return "Architecture"
    if kind in SUBSTRUCTURE_KINDS:
        return "Substructure"
    if kind is not None and group in ("concrete", "formwork", "steel", "earthwork"):
        return "Superstructure"
    return None


def element_parts(bill: dict[str, Any]) -> dict[str, str]:
    """The part of every element of the bill, from the items measured by element kind; the
    reinforcement and the materials take-off of an element follow it."""
    parts: dict[str, str] = {}
    for item in bill.get("items", []):
        part = part_of(str(item.get("group")), item.get("kind"))
        if part is None:
            continue
        for entry in item.get("breakdown") or []:
            parts.setdefault(str(entry.get("element")), part)
    return parts


def split_by_part(item: dict[str, Any], parts: dict[str, str]) -> dict[str, float]:
    """The item's quantity per part (by its breakdown; Superstructure when unknown)."""
    own = part_of(str(item.get("group")), item.get("kind"))
    shares: dict[str, float] = {}
    breakdown = item.get("breakdown") or []
    for entry in breakdown:
        part = own or parts.get(str(entry.get("element")), "Superstructure")
        shares[part] = shares.get(part, 0.0) + float(entry.get("quantity") or 0.0)
    total = sum(shares.values())
    quantity = float(item.get("quantity") or 0.0)
    if not breakdown or total <= 0:
        return {own or "Superstructure": quantity}
    return {p: quantity * q / total for p, q in shares.items()}


def rate_for(schedule: RateSchedule, item: dict[str, Any]) -> RateItem | None:
    """The first item of the schedule that matches the bill item."""
    return next((r for r in schedule.items if r.match.holds(item)), None)


def price(item: dict[str, Any], rate: RateItem | None, parts: dict[str, str]) -> CostLine:
    line = CostLine(
        code=str(item.get("code")),
        group=str(item.get("group")),
        description=str(item.get("description")),
        quantity=float(item.get("quantity") or 0.0),
        unit=str(item.get("unit")),
    )
    if rate is None:
        return line
    line.rateCode, line.rateDescription, line.rateUnit = rate.code, rate.description, rate.unit
    line.rate = rate.rate
    line.conversion = conversion(rate.unit, line.unit)
    if line.conversion is None:
        line.status = "unit mismatch"
        return line
    if rate.rate is None:
        line.status = "not rated"
        return line
    line.status = "priced"
    line.amount = line.quantity * line.conversion * rate.rate
    line.byPart = {
        p: q * line.conversion * rate.rate for p, q in split_by_part(item, parts).items()
    }
    return line


def _mass_per_unit(factor: CarbonFactor, item: dict[str, Any]) -> float | None:
    unit = str(item.get("unit"))
    if unit == "kg":
        return 1.0
    if unit == "t":
        return 1e3
    if unit in ("m3", "cft"):
        density = factor.density or DENSITIES.get(str(item.get("kind")))
        if density is None:
            return None
        return density / (CFT if unit == "cft" else 1.0)
    return None


def carbon_of(
    factors: CarbonFactors, items: list[dict[str, Any]], parts: dict[str, str]
) -> tuple[list[CarbonLine], list[str]]:
    """The embodied carbon per factor, and the notes on what was not counted."""
    lines: dict[str, CarbonLine] = {}
    notes: list[str] = []
    for item in items:
        if item.get("unit") == "bag":
            continue  # the cement by weight, again
        factor = next((f for f in factors.factors if f.match.holds(item)), None)
        if factor is None:
            continue
        per_unit = _mass_per_unit(factor, item)
        line = lines.setdefault(
            factor.id,
            CarbonLine(
                id=factor.id, material=factor.material, factor=factor.factor, mass=0.0,
                source=factor.source,
            ),
        )  # fmt: skip
        if per_unit is None:
            notes.append(
                f"Carbon: {item.get('code')} {item.get('description')} is in "
                f"{item.get('unit')}, which factor '{factor.id}' cannot turn into kg (give it a "
                "density)."
            )
            continue
        line.items.append(str(item.get("code")))
        line.mass += float(item.get("quantity") or 0.0) * per_unit
        if factor.factor is not None:
            for part, q in split_by_part(item, parts).items():
                line.byPart[part] = line.byPart.get(part, 0.0) + q * per_unit * factor.factor
    for line in lines.values():
        if line.factor is not None:
            line.carbon = line.mass * line.factor
    left = [li.material for li in lines.values() if li.factor is None and li.mass > 0]
    if left:
        notes.append(
            f"Carbon: no factor for {', '.join(left)}, so it is not counted (enter one in "
            f"{CARBON_FILE})."
        )
    return list(lines.values()), notes


def cost_bill(
    bill: dict[str, Any], rates: RateSchedule, factors: CarbonFactors | None = None
) -> Costing:
    """The bill (``boq.json`` as a dict) priced by the schedule, with its embodied carbon."""
    items = list(bill.get("items", []))
    parts = element_parts(bill)
    costing = Costing(currency=rates.currency, rateSchedule=rates.name)
    order = list(GROUPS)
    for item in items:
        line = price(item, rate_for(rates, item), parts)
        costing.lines.append(line)
        if line.amount is None:
            continue
        costing.groups[line.group] = costing.groups.get(line.group, 0.0) + line.amount
        for part, amount in line.byPart.items():
            costing.parts[part] = costing.parts.get(part, 0.0) + amount
    costing.groups = dict(
        sorted(costing.groups.items(), key=lambda g: order.index(g[0]) if g[0] in order else 99)
    )
    costing.parts = {p: costing.parts[p] for p in PARTS if p in costing.parts}
    costing.total = sum(costing.groups.values())
    missing = [li for li in costing.lines if li.status == "no rate item"]
    if missing:
        costing.notes.append(
            f"No rate item for {len(missing)} bill item(s), not costed: "
            + "; ".join(f"{li.code} {li.description}" for li in missing)
            + f". Add items for them to {RATES_FILE}."
        )
    mismatched = [li for li in costing.lines if li.status == "unit mismatch"]
    if mismatched:
        costing.notes.append(
            "Rate unit does not measure the bill item, not costed: "
            + "; ".join(
                f"{li.code} ({li.unit}) by {li.rateCode} ({li.rateUnit})" for li in mismatched
            )
            + "."
        )
    if factors is not None:
        costing.carbon, notes = carbon_of(factors, items, parts)
        costing.notes.extend(notes)
        for line in costing.carbon:
            for part, carbon in line.byPart.items():
                costing.carbonParts[part] = costing.carbonParts.get(part, 0.0) + carbon
        costing.carbonParts = {p: costing.carbonParts[p] for p in PARTS if p in costing.carbonParts}
        costing.carbonTotal = sum(li.carbon or 0.0 for li in costing.carbon)
    return costing


def cost_texts(
    boq_text: str | None, rates_text: str | None = None, carbon_text: str | None = None
) -> dict[str, Any]:
    """``cost_bill`` of the texts of ``boq.json``, ``rates.json`` and ``carbon-factors.json``
    (the shipped ones when not given): ``{"costing", "sampleRates"}``, or ``{"problems"}``."""
    from saengine.pipeline.run_all import parse_boq

    bill = parse_boq(boq_text)
    if bill is None:
        return {"problems": ["Measure the bill of quantities (10 BOQ) first."]}
    problems = []
    try:
        rates = parse_rates(rates_text)
    except ValueError as error:
        problems.append(f"{RATES_FILE}: {error}")
    try:
        factors = parse_carbon(carbon_text)
    except ValueError as error:
        problems.append(f"{CARBON_FILE}: {error}")
    if problems:
        return {"problems": problems}
    costing = cost_bill(bill, rates, factors)
    return {
        "costing": json.loads(costing.model_dump_json()),
        "sampleRates": not (rates_text and rates_text.strip()),
    }

"""Water demand of the building: population, daily demand, peak flows and fixture units.

- Daily demand (BNBC 2020 Part 8 Sec 5.5.2, 5.6): each story's population times the per-capita
  requirement of its occupancy in Tables 8.5.1(a)-(d) (full or restricted facility).
- Population (Sec 5.6.3, 5.6.4): as entered; else 5 persons per dwelling (one dwelling per
  kitchen sink, SAEngine's count of the dwellings) for residential occupancies, 7.4 m² of floor
  per person for offices; other occupancies need it entered (Part 4 occupant loads).
- Peak hourly demand (Eq 8.5.1): daily / 16 hours (usually 15 to 17) x peak factor 2.2.
- Peak flow in a pipe from fixture units (Appendix O Sec O.3-O.4): water supply fixture units
  of Table 8.O.1 (Table 8.5.4 for the fixtures it does not list) and the probable simultaneous
  demand of Table 8.5.5 (Hunter), interpolated linearly between its rows, proportionally below
  its first row (20 units) and extrapolated along its last interval above 1000 units.
- Drainage fixture units (Sec 6.10.1): Table 8.6.12, Table 8.6.13 for the washing machine.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from saengine.plumbing import tables as T
from saengine.plumbing.building import Building

FIXTURES = (
    "wc", "urinal", "basin", "shower", "bathtub", "kitchenSink", "floorDrain",
    "washingMachine", "bidet",
)  # fmt: skip


@dataclass
class StoryDemand:
    story: str
    occupancy: str
    lpcd: float
    population: float
    daily: float  # l/day
    reference: str
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "story": self.story,
            "occupancy": self.occupancy,
            "lpcd": self.lpcd,
            "population": self.population,
            "daily": self.daily,
            "reference": self.reference,
            "notes": self.notes,
        }


def lpcd(occupancy: str, facility: str = "full") -> tuple[float, str, list[str]]:
    """Per-capita requirement of an occupancy (Table 8.5.1): (lpcd, reference, notes)."""
    row = T.OCCUPANCIES[occupancy]
    value = row.full if facility == "full" else row.restricted
    notes = []
    if value is None:
        value = row.restricted if row.restricted is not None else row.full
        notes.append(
            f"Table {row.table} gives no {facility}-facility value for {row.label}: the "
            f"{'restricted' if facility == 'full' else 'full'} facility's is used"
        )
    reference = f"BNBC 2020 {T.PAGES[row.table]}, row {row.row} ({row.label}): {value:g} lpcd"
    return float(value or 0.0), reference, notes


def story_population(entry: Any, building: Building | None = None) -> tuple[float, list[str]]:
    """Persons of a story (beds or seats for those rows) and how they were found."""
    if entry.population is not None:
        return float(entry.population), []
    row = T.OCCUPANCIES[entry.occupancy]
    if row.group.startswith("A") and row.unit == "person":
        dwellings = entry.fixtures.kitchenSink
        if dwellings:
            return float(dwellings * T.FAMILY_SIZE), [
                (
                    f"{entry.story}: {dwellings} dwellings (one per kitchen sink) x "
                    f"{T.FAMILY_SIZE} persons ({T.PAGES['5.6.3']})"
                )
            ]
    if row.group == "E1" and building is not None:
        area = building.floor_area(entry.story)
        if area > 0:
            return area / T.OFFICE_AREA_PER_PERSON, [
                (
                    f"{entry.story}: {area:.0f} m² of floor / {T.OFFICE_AREA_PER_PERSON} m² per "
                    f"person ({T.PAGES['5.6.3']})"
                )
            ]
    return 0.0, [f"{entry.story}: give its population (persons, beds or seats)"]


def story_demand(entry: Any, facility: str, building: Building | None = None) -> StoryDemand:
    rate, reference, notes = lpcd(entry.occupancy, facility)
    population, found = story_population(entry, building)
    return StoryDemand(
        entry.story, entry.occupancy, rate, population, rate * population, reference,
        [*notes, *found],
    )  # fmt: skip


def daily_demand(plumbing: Any, building: Building | None = None) -> dict[str, Any]:
    """Daily demand of every story and of the building [l/day], and the peak hourly demand."""
    stories = [story_demand(s, plumbing.supply.facility, building) for s in plumbing.stories]
    total = sum(s.daily for s in stories)
    population = sum(s.population for s in stories)
    return {
        "stories": [s.as_dict() for s in stories],
        "population": population,
        "daily": total,
        "dailyM3": total / 1000.0,
        "peakHourly": peak_hourly(total),
        "peakHourlyLpm": peak_hourly(total) / 60.0,
        "notes": [n for s in stories for n in s.notes],
        "method": (
            f"Population x lpcd of Tables 8.5.1(a)-(d) (BNBC 2020 Part 8 Sec 5.5.2, 5.6); peak "
            f"hourly demand = daily / {T.CONSUMPTION_HOURS:g} h x {T.PEAK_FACTOR} "
            f"({T.PAGES['8.5.1']})."
        ),
    }


def peak_hourly(daily: float) -> float:
    """Eq 8.5.1: peak hourly demand [l/h] of a daily requirement [l/day]."""
    return daily / T.CONSUMPTION_HOURS * T.PEAK_FACTOR


# ───────────────────────────────────── fixture units ─────────────────────────────────────


def supply_units(
    fixtures: Any, column: str = "total", flush_valves: bool = False
) -> tuple[float, int, list[str]]:
    """Water supply fixture units of a set of fixtures: (units, largest minimum supply pipe
    of Table 8.5.6 [mm], what each fixture counted). ``column``: cold, hot or total."""
    units = 0.0
    minimum = 0
    lines = []
    for name in FIXTURES:
        count = getattr(fixtures, name)
        if not count:
            continue
        key = name + "Valve" if flush_valves and name in ("wc", "urinal") else name
        row = T.SUPPLY_UNITS[key]
        each = getattr(row, column)
        if each:
            units += count * each
            minimum = max(minimum, row.minimum)
            lines.append(f"{count} {name} x {each:g} ({row.source})")
    for other in fixtures.other:
        if other.count and other.supplyUnits:
            units += other.count * other.supplyUnits
            lines.append(f"{other.count} {other.name} x {other.supplyUnits:g} (entered)")
    return units, minimum, lines


def drainage_units(fixtures: Any, which: str = "all", flush_valves: bool = False):
    """Drainage fixture units (Table 8.6.12) of the soil, waste or all fixtures: (units,
    largest minimum outlet of Table 8.6.2 [mm], what each counted)."""
    units = 0.0
    outlet = 0
    lines = []
    for name in FIXTURES:
        count = getattr(fixtures, name)
        if not count:
            continue
        key = name + "Valve" if flush_valves and name == "wc" else name
        row = T.DRAINAGE_UNITS[key]
        if which == "soil" and not row.soil or which == "waste" and row.soil:
            continue
        units += count * row.units
        outlet = max(outlet, row.outlet)
        lines.append(f"{count} {name} x {row.units:g} ({row.source})")
    if which != "soil":
        for other in fixtures.other:
            if other.count and other.drainageUnits:
                units += other.count * other.drainageUnits
                lines.append(f"{other.count} {other.name} x {other.drainageUnits:g} (entered)")
    return units, outlet, lines


def hunter_flow(units: float, flush_valves: bool = False) -> float:
    """Table 8.5.5: probable simultaneous demand [l/min] of a number of fixture units."""
    if units <= 0:
        return 0.0
    column = 2 if flush_valves else 1
    rows = T.HUNTER
    if units <= rows[0][0]:
        return rows[0][column] * units / rows[0][0]
    for lo, hi in itertools.pairwise(rows):
        if units <= hi[0]:
            t = (units - lo[0]) / (hi[0] - lo[0])
            return lo[column] + t * (hi[column] - lo[column])
    lo, hi = rows[-2], rows[-1]
    return hi[column] + (units - hi[0]) * (hi[column] - lo[column]) / (hi[0] - lo[0])

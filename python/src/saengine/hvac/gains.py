"""What each zone holds and breathes: occupants, lighting, equipment, outdoor air and the inside
design conditions, and the outside design conditions of the site.

Both the EnergyPlus model (:mod:`saengine.hvac.energyplus`) and the estimate
(:mod:`saengine.hvac.fallback`) take their inputs from here, so the two work on the same
numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from saengine.hvac import tables as T


@dataclass
class Design:
    """The outside design conditions."""

    station: T.Station
    db: float  # °C, the design day's maximum
    wb: float  # °C, coincident wet bulb
    range: float  # °C, daily range of the dry bulb
    latitude: float
    longitude: float
    elevation: float
    months: tuple[int, ...]
    sources: list[str] = field(default_factory=list)


def design_conditions(hvac: Any, location: str | None = None) -> Design:
    """The outside design conditions of the 07 MEP ``hvac.design`` and the Project Settings
    site location: Table 8.2.2's 2 % columns (Sec 2.12.2.1) unless entered."""
    entry = hvac.design if hvac is not None else None
    station, notes = T.station_for(entry.city if entry is not None else None, location)
    db, mwb = station.cooling[T.DESIGN_LEVEL]
    sources = [
        (
            f"{station.name}: 2 % dry bulb {db:g} °C, mean coincident wet bulb {mwb:g} °C, daily "
            f"range {station.range:g} °C (BNBC 2020 {T.PAGES['8.2.2']}; 2 % columns per "
            f"{T.PAGES['2.12.2']})"
        ),
        *notes,
    ]
    if entry is not None and entry.outdoorDB is not None:
        db = entry.outdoorDB
        sources.append(f"outdoor dry bulb {db:g} °C entered")
    if entry is not None and entry.outdoorWB is not None:
        mwb = entry.outdoorWB
        sources.append(f"outdoor wet bulb {mwb:g} °C entered")
    daily = station.range
    if entry is not None and entry.dailyRange is not None:
        daily = entry.dailyRange
        sources.append(f"daily range {daily:g} °C entered")
    sources.append(
        f"site {station.latitude:g}° N {station.longitude:g}° E, UTC+{T.TIME_ZONE:g}, design days "
        f"on the 21st of May to September (the summer months of Table 8.2.2 note b)"
    )
    return Design(
        station, db, mwb, daily, station.latitude, station.longitude, T.SITE_ELEVATION,
        T.DESIGN_MONTHS, sources,
    )  # fmt: skip


@dataclass
class ZoneGains:
    """A zone's internal gains, outdoor air and inside conditions."""

    use: str
    occupants: float
    lighting: float  # W/m²
    equipment: float  # W/m²
    activity: float  # W per person, total
    perPerson: float  # outdoor air, m³/s per person
    perArea: float  # outdoor air, m³/s per m²
    ach: float | None  # outdoor air, air changes per hour (dwellings' living areas)
    indoorDB: float
    indoorRH: float
    sources: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def outdoor_air(self, area: float, volume: float) -> float:
        """Design outdoor air [m³/s]: Rp Pz + Ra Az, or the larger of the air changes and the
        per-person rate for a dwelling's living areas."""
        people = self.perPerson * self.occupants
        if self.ach is not None:
            return max(self.ach * volume / 3600.0, people)
        return people + self.perArea * area


def zone_gains(zone: Any, hvac: Any, population: float | None = None) -> ZoneGains:
    """The gains of a :class:`~saengine.hvac.geometry.ThermalZone` (``population``: the
    persons the plumbing of 07 MEP gives the story, when Table 8.2.3 gives no density)."""
    entry = zone.entry
    use = entry.use if entry is not None else "officeSpace"
    row = T.VENTILATION[use]
    sources: list[str] = [f"{zone.story}: {row.label} (Table 8.2.3)"]
    problems: list[str] = []
    area = zone.area
    if entry is not None and entry.occupants is not None:
        occupants = float(entry.occupants)
        sources.append(f"{occupants:g} occupants entered")
    elif row.density is not None:
        occupants = row.density * area / 100.0
        sources.append(
            f"{occupants:.1f} occupants: {row.density:g} per 100 m² (Table 8.2.3) x {area:.0f} m²"
        )
    elif population:
        occupants = float(population)
        sources.append(f"{occupants:g} occupants: the story's plumbing population")
    else:
        occupants = 0.0
        if row.perPerson is not None:
            problems.append(f"{zone.story}: give its occupants (Table 8.2.3 gives no density)")
    if entry is not None and entry.lighting is not None:
        lighting = float(entry.lighting)
    else:
        key = T.GROUP_LPD.get(row.group)
        lighting = T.LPD[key or "offices"]
        sources.append(
            f"lighting {lighting:g} W/m²: Part 3 Table 3.4.5 maximum ({key or 'offices'}"
            f"{'' if key else ', the table has no row for the use'})"
        )
    if entry is not None and entry.equipment is not None:
        equipment = float(entry.equipment)
    else:
        equipment = T.EQUIPMENT.get(row.group, T.EQUIPMENT_DEFAULT)
        sources.append(
            f"equipment {equipment:g} W/m² (SAEngine default, BNBC gives none: enter the "
            "project's equipment load)"
        )
    activity = T.ACTIVITY.get(row.group, T.ACTIVITY_DEFAULT)
    db, rh, inside = T.inside_conditions(use)
    design = hvac.design if hvac is not None else None
    if design is not None and design.indoorDB is not None:
        db = design.indoorDB
        inside = f"{db:g} °C entered"
    if design is not None and design.indoorRH is not None:
        rh = design.indoorRH
        inside += f", {rh:g} % RH entered"
    sources.append(f"inside {inside}")
    return ZoneGains(
        use, occupants, lighting, equipment, activity,
        (row.perPerson or 0.0) / 1000.0, (row.perArea or 0.0) / 1000.0, row.ach, db, rh,
        sources, problems,
    )  # fmt: skip

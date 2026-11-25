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
    db: float  # °C, the cooling design day's maximum
    wb: float  # °C, coincident wet bulb
    range: float  # °C, daily range of the dry bulb
    latitude: float
    longitude: float
    elevation: float
    months: tuple[int, ...]
    sources: list[str] = field(default_factory=list)
    heatingDB: float = 11.0  # °C, winter outdoor design dry bulb
    infiltrationACH: float = 0.5  # air changes per hour for heating infiltration


def design_conditions(hvac: Any, location: str | None = None) -> Design:
    """The outside design conditions of the 07 MEP ``hvac.design`` and the Project Settings
    site location: Table 8.2.2's 2 % columns (Sec 2.12.2.1) unless entered, plus the winter
    heating outdoor dry bulb and infiltration rate from the pack/overrides."""
    entry = hvac.design if hvac is not None else None
    station, notes = T.station_for(entry.city if entry is not None else None, location)
    db, mwb = station.cooling[T.DESIGN_LEVEL]
    sources = [
        (
            f"{station.name}: 2 % dry bulb {db:g} °C, mean coincident wet bulb {mwb:g} °C, daily "
            f"range {station.range:g} °C ({T.PAGES['8.2.2']}; 2 % columns per "
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
    h_def = T.heating_defaults()
    heating_db = T.heating_outdoor_db(station.key)
    if entry is not None and getattr(entry, "heatingOutdoorDB", None) is not None:
        heating_db = float(entry.heatingOutdoorDB)
        sources.append(f"heating outdoor dry bulb {heating_db:g} °C entered")
    else:
        sources.append(
            f"{station.name}: winter heating dry bulb {heating_db:g} °C "
            "(SAEngine winter default, to be checked)"
        )
    infiltration = float(h_def.infiltrationAch)
    if entry is not None and getattr(entry, "infiltrationACH", None) is not None:
        infiltration = float(entry.infiltrationACH)
        sources.append(f"infiltration {infiltration:g} ACH entered")
    sources.append(
        f"site {station.latitude:g}° N {station.longitude:g}° E, UTC+{T.TIME_ZONE:g}, design days "
        f"on the 21st of May to September (the summer months of Table 8.2.2 note b)"
    )
    return Design(
        station, db, mwb, daily, station.latitude, station.longitude, T.SITE_ELEVATION,
        T.DESIGN_MONTHS, sources, heatingDB=heating_db, infiltrationACH=infiltration,
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
    #: "rooms" when the architecture's rooms gave them (:func:`room_gains`), else "typed"
    gainsFrom: str = "typed"
    #: the rooms' groups by use: ``[{use, label, area, occupants, outdoorAir, rooms}]``
    rooms: list[dict[str, Any]] = field(default_factory=list)
    #: winter heating setpoint [°C] (ASHRAE practice, to be checked)
    heatingIndoorDB: float = 20.0

    def outdoor_air(self, area: float, volume: float) -> float:
        """Design outdoor air [m³/s]: Rp Pz + Ra Az, or the larger of the air changes and the
        per-person rate for a dwelling's living areas."""
        people = self.perPerson * self.occupants
        if self.ach is not None:
            return max(self.ach * volume / 3600.0, people)
        return people + self.perArea * area


def _inside(use: str, hvac: Any) -> tuple[float, float, str]:
    """Inside dry bulb, RH and their source: the use's, or 07 MEP's design values."""
    db, rh, inside = T.inside_conditions(use)
    design = hvac.design if hvac is not None else None
    if design is not None and design.indoorDB is not None:
        db = design.indoorDB
        inside = f"{db:g} °C entered"
    if design is not None and design.indoorRH is not None:
        rh = design.indoorRH
        inside += f", {rh:g} % RH entered"
    return db, rh, inside


def _heating_inside(hvac: Any) -> tuple[float, str]:
    """Winter heating indoor setpoint [°C] and its source."""
    design = hvac.design if hvac is not None else None
    if design is not None and getattr(design, "heatingIndoorDB", None) is not None:
        t = float(design.heatingIndoorDB)
        return t, f"{t:g} °C entered"
    t = float(T.heating_defaults().indoorDb)
    return t, f"{t:g} °C (ASHRAE winter comfort default, to be checked)"


def _room_use_loads(
    use: str,
    area: float,
    height: float,
    population: float | None = None,
    shared_area: float = 0.0,
    lighting_lpd: float | None = None,
) -> tuple[Any, float, float, float, float]:
    """(Table 8.2.3 row, persons, lpd [W/m²], plug [W/m²], outdoor air [m³/s]) for one room
    or use group of ``area`` m² and ``height`` m."""
    row = T.VENTILATION[use]
    if row.density is not None:
        persons = row.density * area / 100.0
    elif row.perPerson and population and shared_area:
        persons = population * area / shared_area
    else:
        persons = 0.0
    lpd = (
        float(lighting_lpd)
        if lighting_lpd is not None
        else T.LPD[T.GROUP_LPD.get(row.group) or "offices"]
    )
    plug = T.EQUIPMENT.get(row.group, T.EQUIPMENT_DEFAULT)
    by_people = (row.perPerson or 0.0) * persons / 1000.0
    if row.ach is not None:
        flow = max(row.ach * area * height / 3600.0, by_people)
    else:
        flow = by_people + (row.perArea or 0.0) * area / 1000.0
    return row, persons, lpd, plug, flow


#: Below this share of a story's plan covered by rooms, the rest of the floor takes the story's
#: own use (rooms still being drawn); above it, the rest is walls and shafts (SAEngine).
ROOMS_COVER = 0.7


def room_gains(
    zone: Any,
    hvac: Any,
    groups: list[dict[str, Any]] | None,
    population: float | None = None,
    lighting_lpd: float | None = None,
) -> ZoneGains:
    """The gains of a zone from its story's rooms (``groups``: the rooms by Table 8.2.3 use,
    :meth:`saengine.mep.rooms.StoryRooms.hvac_groups`), each group with its own use's density,
    lighting, equipment and outdoor air (Rp Pz + Ra Az, or the air changes of a dwelling's
    living areas), added up over the story. Persons of a use without a density (dwellings)
    are the story's plumbing ``population`` shared by area. Occupants, lighting and equipment
    typed in 07 MEP override; ``gainsFrom`` "typed" (or no rooms) gives :func:`zone_gains`."""
    base = zone_gains(zone, hvac, population, lighting_lpd=lighting_lpd)
    entry = zone.entry
    if not groups or (entry is not None and entry.gainsFrom == "typed"):
        return base
    area, height = zone.area, zone.height
    rooms_area = sum(g["area"] for g in groups)
    covered = rooms_area / area if area else 1.0
    rest = area - rooms_area if covered < ROOMS_COVER else 0.0
    shared = sum(
        g["area"]
        for g in groups
        if T.VENTILATION[g["use"]].density is None and T.VENTILATION[g["use"]].perPerson
    )
    sources = [f"{zone.story}: from the rooms of the architecture ({covered:.0%} of the floor)"]
    out_groups = []
    people = lighting = equipment = air = 0.0
    for g in groups:
        a = g["area"]
        row, persons, lpd, plug, flow = _room_use_loads(
            g["use"], a, height, population, shared, lighting_lpd=lighting_lpd
        )
        people += persons
        lighting += lpd * a
        equipment += plug * a
        air += flow
        out_groups.append(
            {
                "use": g["use"], "label": row.label, "area": a, "occupants": persons,
                "outdoorAir": flow, "rooms": list(g["rooms"]),
            }
        )  # fmt: skip
        light_source = "from lighting design" if lighting_lpd is not None else "Part 3 Table 3.4.5"
        sources.append(
            f"{row.label}: {a:.1f} m², {persons:.1f} persons, {lpd:g} W/m² lighting, "
            f"{flow * 1000:.0f} l/s outdoor air (Table 8.2.3; {light_source})"
        )
    if rest > 0:
        share = rest / area
        people += base.occupants * share
        lighting += base.lighting * rest
        equipment += base.equipment * rest
        air += base.outdoor_air(area, zone.volume) * share
        sources.append(
            f"the rooms cover {covered:.0%} of the floor: the other {rest:.0f} m² as "
            f"{T.VENTILATION[base.use].label}"
        )
    floor = rooms_area + rest
    typed = entry is not None
    use = groups[0]["use"]
    row = T.VENTILATION[use]
    db, rh, inside = _inside(use, hvac)
    heat_db, heat_src = _heating_inside(hvac)
    sources.append(f"inside {inside}; heating {heat_src}")
    return ZoneGains(
        use,
        base.occupants if typed and entry.occupants is not None else people,
        base.lighting if typed and entry.lighting is not None else lighting / floor,
        base.equipment if typed and entry.equipment is not None else equipment / floor,
        T.ACTIVITY.get(row.group, T.ACTIVITY_DEFAULT),
        0.0,
        air / area if area else 0.0,
        None,
        db,
        rh,
        sources,
        [p for p in base.problems if "give its occupants" not in p],
        "rooms",
        out_groups,
        heatingIndoorDB=heat_db,
    )


def single_room_gains(
    zone: Any,
    room: Any,
    hvac: Any,
    story_rooms: Any = None,
    population: float | None = None,
    lighting_lpd: float | None = None,
) -> ZoneGains:
    """The gains of a single-room :class:`~saengine.hvac.geometry.ThermalZone`, reusing the
    Table 8.2.3 / Table 3.4.5 rules of :func:`room_gains` and sharing dwelling ``population``
    across density-less rooms on the story."""
    entry = zone.entry
    use = getattr(room, "hvacUse", None) or (entry.use if entry is not None else "officeSpace")
    if use not in T.VENTILATION:
        use = entry.use if entry is not None else "officeSpace"
    area = zone.area
    height = zone.height
    shared = 0.0
    total_story_area = area
    if story_rooms is not None and getattr(story_rooms, "rooms", None):
        total_story_area = sum(r.area for r in story_rooms.rooms) or area
        shared = sum(
            r.area
            for r in story_rooms.rooms
            if r.hvacUse in T.VENTILATION
            and T.VENTILATION[r.hvacUse].density is None
            and T.VENTILATION[r.hvacUse].perPerson
        )
    row, persons, lpd, plug, flow = _room_use_loads(
        use, area, height, population, shared, lighting_lpd=lighting_lpd
    )
    if entry is not None and entry.occupants is not None and total_story_area > 0:
        persons = float(entry.occupants) * area / total_story_area
    if entry is not None and entry.lighting is not None:
        lpd = float(entry.lighting)
        light_source = "entered"
    elif lighting_lpd is not None:
        light_source = "from lighting design"
    else:
        light_source = "Part 3 Table 3.4.5"
    if entry is not None and entry.equipment is not None:
        plug = float(entry.equipment)
    db, rh, inside = _inside(use, hvac)
    heat_db, heat_src = _heating_inside(hvac)
    label = getattr(room, "label", None) or getattr(room, "id", zone.name)
    sources = [
        (
            f"{zone.story} / {label}: {row.label} ({area:.1f} m², {persons:.1f} persons, "
            f"{lpd:g} W/m² lighting, {flow * 1000:.0f} l/s outdoor air, Table 8.2.3; {light_source})"
        ),
        f"inside {inside}; heating {heat_src}",
    ]
    out_group = [
        {
            "use": use,
            "label": row.label,
            "area": area,
            "occupants": persons,
            "outdoorAir": flow,
            "rooms": [room.id],
        }
    ]
    return ZoneGains(
        use,
        persons,
        lpd,
        plug,
        T.ACTIVITY.get(row.group, T.ACTIVITY_DEFAULT),
        0.0,
        flow / area if area else 0.0,
        None,
        db,
        rh,
        sources,
        [],
        "rooms",
        out_group,
        heatingIndoorDB=heat_db,
    )


def zone_gains(
    zone: Any,
    hvac: Any,
    population: float | None = None,
    lighting_lpd: float | None = None,
) -> ZoneGains:
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
    elif lighting_lpd is not None:
        lighting = float(lighting_lpd)
        sources.append(f"lighting {lighting:g} W/m²: from lighting design")
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
            f"equipment {equipment:g} W/m² (SAEngine default, the code gives none: enter the "
            "project's equipment load)"
        )
    activity = T.ACTIVITY.get(row.group, T.ACTIVITY_DEFAULT)
    db, rh, inside = _inside(use, hvac)
    heat_db, heat_src = _heating_inside(hvac)
    sources.append(f"inside {inside}; heating {heat_src}")
    return ZoneGains(
        use, occupants, lighting, equipment, activity,
        (row.perPerson or 0.0) / 1000.0, (row.perArea or 0.0) / 1000.0, row.ach, db, rh,
        sources, problems, heatingIndoorDB=heat_db,
    )  # fmt: skip

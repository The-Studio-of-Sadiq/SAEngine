"""Towns of the code pack's hazard tables with their seismic zone coefficient and basic wind
speed, and where they are, for the location suggestion of the soil report's site.

The towns are the pack's ``locations.towns`` (the default pack: BNBC 2020 Part 6 Table 6.2.15,
the zone coefficient Z of towns, and Table 6.2.8, the basic wind speed V of selected
locations, with the code's spellings; a town one table lists and the other does not has no
value for the other). The zones are the pack's ``zoneCoefficients`` (Z by zone).

The coordinates (latitude, longitude of the town centre, WGS 84, to about 0.01°, 1 km) of the
default pack were written from general geographic knowledge, not from a survey; check them
against GeoNames (https://www.geonames.org, CC BY 4.0) before relying on a distance to a few
km. The suggestion only names the nearest listed town; the code's zoning and wind maps govern,
and the engineer confirms the location in Project Settings. A pack without the towns does not
cover the suggestion (:func:`town_map` is None).
"""

from __future__ import annotations

from typing import Any, NamedTuple

from saengine.codes import context as code_context
from saengine.gis.crs import haversine_km


class Town(NamedTuple):
    name: str
    latitude: float
    longitude: float
    #: Seismic zone coefficient Z, or None when the code's table does not list it.
    z: float | None
    #: Basic wind speed V [m/s], or None when the code's table does not list it.
    wind_speed: float | None


def town_map() -> Any | None:
    """The pack's ``locations.towns``, or None when the pack does not cover them."""
    pack = code_context.current()
    if not pack.has("locations"):
        return None
    return pack.table("locations").towns


def towns() -> tuple[Town, ...]:
    """The pack's towns (empty when it has none)."""
    found = town_map()
    if found is None:
        return ()
    return tuple(
        Town(t.name, float(t.latitude), float(t.longitude), t.z, t.windSpeed) for t in found.towns
    )


def zones() -> dict[float, int]:
    """The zone of each coefficient Z (the pack's ``zoneCoefficients``, inverted)."""
    table = code_context.table("zoneCoefficients")
    return {float(z): int(zone) for zone, z in table.zones.items()}


def settings_ids() -> dict[str, str]:
    """The Project Settings location id (``locations``) of a town, where there is one."""
    found = town_map()
    if found is None:
        return {}
    return {t.name: t.location for t in found.towns if t.location}


def __getattr__(name: str) -> Any:
    # The former module constants, read from the pack in force.
    if name == "TOWNS":
        return towns()
    if name == "ZONES":
        return zones()
    if name == "SETTINGS_IDS":
        return settings_ids()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def nearest(latitude: float, longitude: float, *, need: str | None = None) -> tuple[Town, float]:
    """The nearest town and its distance [km]; ``need`` "z" or "wind" skips the towns the
    table of that value does not list. ValueError when the pack lists none."""
    candidates = [
        t
        for t in towns()
        if need is None
        or (need == "z" and t.z is not None)
        or (need == "wind" and t.wind_speed is not None)
    ]
    if not candidates:
        raise ValueError("the code pack lists no towns for the location suggestion")
    return min(
        ((t, haversine_km(latitude, longitude, t.latitude, t.longitude)) for t in candidates),
        key=lambda pair: pair[1],
    )

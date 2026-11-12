"""Coordinate systems of the site: WGS 84, Bangladesh Transverse Mercator and the project grid.

- WGS 84 (EPSG:4326): latitude/longitude in degrees, what GeoJSON (RFC 7946), the map and GPS
  use.
- Bangladesh Transverse Mercator, BTM (EPSG:9678, "Gulshan 303 / Bangladesh Transverse
  Mercator"): transverse Mercator on the Everest 1830 (1937 adjustment) ellipsoid, central
  meridian 90° E, scale 0.9996, false easting 500 000 m, false northing -2 000 000 m; the
  datum shift to WGS 84 is PROJ's "Gulshan 303 to WGS 84 (2)" (a 3-parameter Helmert shift,
  accuracy about 1 m). EPSG:3106 is not BTM: it is "Gulshan 303 / TM 90 NE" (no false
  northing).
- The project grid: x/y in mm, the project point (x0, y0) of the site at the site's
  latitude/longitude and the +Y axis turned ``rotation`` degrees clockwise from true north.
  It is laid on a local transverse Mercator projection centred on the site point with scale 1
  (WGS 84 ellipsoid), so distances in the grid are true distances on the ellipsoid (the scale
  error 50 km away is about 30 ppm), and true north at the site point is the grid's north:
  ``E = dx cos θ + dy sin θ``, ``N = -dx sin θ + dy cos θ`` [m], θ the rotation, (dx, dy) =
  (x - x0, y - y0).

The transformations are pyproj's (PROJ); ``always_xy`` keeps the order (longitude, latitude)
and (easting, northing).
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyproj import Transformer

    from saengine.library.soil import Site

WGS84 = 4326
BTM = 9678
BTM_NAME = "Gulshan 303 / Bangladesh Transverse Mercator (EPSG:9678)"


@lru_cache(maxsize=8)
def _transformer(source: int | str, target: int | str) -> Transformer:
    from pyproj import Transformer

    return Transformer.from_crs(source, target, always_xy=True)


def wgs84_to_btm(latitude: float, longitude: float) -> tuple[float, float]:
    """(easting, northing) [m] in BTM of a WGS 84 point."""
    e, n = _transformer(WGS84, BTM).transform(longitude, latitude)
    return float(e), float(n)


def btm_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """(latitude, longitude) of a BTM point."""
    lon, lat = _transformer(BTM, WGS84).transform(easting, northing)
    return float(lat), float(lon)


def to_wgs84(srs: int, x: float, y: float) -> tuple[float, float]:
    """(latitude, longitude) of a point in an EPSG coordinate system (x/y in its axis order
    normalized to easting/longitude first)."""
    if srs == WGS84:
        return y, x
    lon, lat = _transformer(srs, WGS84).transform(x, y)
    return float(lat), float(lon)


def _local(latitude: float, longitude: float) -> str:
    return (
        f"+proj=tmerc +lat_0={latitude:.10f} +lon_0={longitude:.10f} +k=1 +x_0=0 +y_0=0 "
        "+ellps=WGS84 +towgs84=0,0,0 +units=m +no_defs +type=crs"
    )


class Grid:
    """The project grid placed on the earth by the site point (``site.lat``/``lon`` given)."""

    def __init__(self, site: Site) -> None:
        if site.lat is None or site.lon is None:
            raise ValueError("the site has no latitude/longitude")
        self.latitude, self.longitude = site.lat, site.lon
        self.x0, self.y0 = site.x, site.y
        self.rotation = site.rotation
        theta = math.radians(self.rotation)
        self._cos, self._sin = math.cos(theta), math.sin(theta)
        local = _local(self.latitude, self.longitude)
        self._to_local = _transformer(WGS84, local)
        self._from_local = _transformer(local, WGS84)

    # project mm ↔ local east/north m (rotation only)
    def _en(self, x: float, y: float) -> tuple[float, float]:
        x, y = (x - self.x0) / 1e3, (y - self.y0) / 1e3
        return x * self._cos + y * self._sin, -x * self._sin + y * self._cos

    def _xy(self, e: float, n: float) -> tuple[float, float]:
        x = e * self._cos - n * self._sin
        y = e * self._sin + n * self._cos
        return x * 1e3 + self.x0, y * 1e3 + self.y0

    def to_wgs84(self, x: float, y: float) -> tuple[float, float]:
        """(latitude, longitude) of a project point [mm]."""
        lon, lat = self._from_local.transform(*self._en(x, y))
        return float(lat), float(lon)

    def from_wgs84(self, latitude: float, longitude: float) -> tuple[float, float]:
        """Project (x, y) [mm] of a WGS 84 point."""
        e, n = self._to_local.transform(longitude, latitude)
        x, y = self._xy(float(e), float(n))
        return round(x, 1), round(y, 1)

    def to_btm(self, x: float, y: float) -> tuple[float, float]:
        return wgs84_to_btm(*self.to_wgs84(x, y))

    def from_btm(self, easting: float, northing: float) -> tuple[float, float]:
        return self.from_wgs84(*btm_to_wgs84(easting, northing))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance on a sphere of radius 6371.0088 km (the IUGG mean radius)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))

"""GeoJSON (RFC 7946): a FeatureCollection in WGS 84, [longitude, latitude] positions.

Written: no ``crs`` member (RFC 7946 §4: WGS 84 always), positions rounded to 1e-8° (about
1 mm), polygon rings closed and the exterior counter-clockwise (the right-hand rule of §3.1.6),
a ``bbox`` (§5). Read: Point, MultiPoint, Polygon and MultiPolygon features (others are
reported); a legacy ``crs`` member naming an EPSG code (``"EPSG:9678"``,
``"urn:ogc:def:crs:EPSG::9678"``) is honoured by converting to WGS 84.
"""

from __future__ import annotations

import itertools
import json
import re
from typing import Any

from saengine.gis.crs import to_wgs84

#: Decimal places of the written degrees.
DIGITS = 8


def _ring(points: list[tuple[float, float]]) -> list[list[float]]:
    """A closed counter-clockwise ring of (longitude, latitude)."""
    ring = [[round(lon, DIGITS), round(lat, DIGITS)] for lon, lat in points]
    if ring and ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    area = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in itertools.pairwise(ring))
    return ring[::-1] if area < 0 else ring


def point(lon: float, lat: float) -> dict[str, Any]:
    return {"type": "Point", "coordinates": [round(lon, DIGITS), round(lat, DIGITS)]}


def polygon(ring: list[tuple[float, float]]) -> dict[str, Any]:
    return {"type": "Polygon", "coordinates": [_ring(ring)]}


def feature(geometry: dict[str, Any], properties: dict[str, Any], fid: str | None = None) -> dict:
    out: dict[str, Any] = {"type": "Feature", "geometry": geometry, "properties": properties}
    if fid is not None:
        out["id"] = fid
    return out


def _positions(geometry: dict[str, Any]) -> list[list[float]]:
    kind, coords = geometry["type"], geometry["coordinates"]
    if kind == "Point":
        return [coords]
    if kind == "Polygon":
        return [p for ring in coords for p in ring]
    return []


def collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    positions = [p for f in features for p in _positions(f["geometry"])]
    out: dict[str, Any] = {"type": "FeatureCollection"}
    if positions:
        lons, lats = [p[0] for p in positions], [p[1] for p in positions]
        out["bbox"] = [min(lons), min(lats), max(lons), max(lats)]
    out["features"] = features
    return out


def dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def _crs(data: dict[str, Any]) -> int | None:
    name = (data.get("crs") or {}).get("properties", {}).get("name")
    if not name:
        return None
    if re.search(r"CRS84$", name):
        return 4326
    match = re.search(r"EPSG:+(\d+)$", name)
    if not match:
        raise ValueError(f"crs '{name}' is not an EPSG code")
    return int(match.group(1))


class Shape:
    """A point or a polygon read from a file, in WGS 84, with its attributes."""

    def __init__(
        self, kind: str, coords: list[tuple[float, float]], properties: dict[str, Any], where: str
    ) -> None:
        self.kind = kind  # "point" or "polygon"
        self.coords = coords  # [(latitude, longitude)]: one for a point, the exterior ring
        self.properties = properties
        self.where = where


def read(text: str, source: str = "GeoJSON") -> tuple[list[Shape], list[str]]:
    """The points and polygons of a GeoJSON text, and the problems."""
    data = json.loads(text)
    srs = _crs(data) or 4326

    def ll(position: list[float]) -> tuple[float, float]:
        return to_wgs84(srs, float(position[0]), float(position[1]))

    if data.get("type") == "Feature":
        features = [data]
    elif data.get("type") == "FeatureCollection":
        features = data.get("features") or []
    else:
        return [], [f"{source}: not a Feature or FeatureCollection"]
    shapes: list[Shape] = []
    problems: list[str] = []
    for i, item in enumerate(features):
        where = f"{source}: feature {i + 1}"
        geometry = item.get("geometry") or {}
        properties = dict(item.get("properties") or {})
        if item.get("id") is not None:
            properties.setdefault("id", item["id"])
        kind, coords = geometry.get("type"), geometry.get("coordinates")
        if kind == "Point":
            shapes.append(Shape("point", [ll(coords)], properties, where))
        elif kind == "MultiPoint":
            shapes += [Shape("point", [ll(p)], properties, where) for p in coords]
        elif kind == "Polygon":
            shapes.append(Shape("polygon", [ll(p) for p in coords[0]], properties, where))
        elif kind == "MultiPolygon":
            shapes += [
                Shape("polygon", [ll(p) for p in poly[0]], properties, where) for poly in coords
            ]
        else:
            problems.append(f"{where}: a {kind or 'missing'} geometry is not read")
    return shapes, problems

"""OGC GeoPackage (OGC GeoPackage Encoding Standard, version 1.2.1) written and read with Python's sqlite3.

Why no library: what SAEngine exchanges is a handful of points and polygons in WGS 84, and a
GeoPackage of vector features needs only an SQLite file with the application id ``GPKG``, three
required tables and a feature table per layer. GDAL (through pyogrio or fiona) would add some
40 MB of native code for it; the spec is short and exact, so the file is written to it here.

Written (the standard's requirements for a feature GeoPackage without extensions):

- ``PRAGMA application_id = 0x47504B47`` ("GPKG") and ``PRAGMA user_version = 10201``
  (version 1.2.1);
- ``gpkg_spatial_ref_sys`` with the required rows -1 (undefined Cartesian), 0 (undefined
  geographic) and 4326 (WGS 84, its WKT from PROJ);
- ``gpkg_contents``: one row per feature table, ``data_type`` "features", the bounding box and
  ``srs_id``;
- ``gpkg_geometry_columns``: the geometry column of each table, its type (POINT, POLYGON),
  ``srs_id`` and ``z = m = 0``;
- the feature tables: ``fid INTEGER PRIMARY KEY AUTOINCREMENT``, ``geom`` of the declared type,
  and the attribute columns;
- geometry BLOBs: the GeoPackage binary header (magic "GP", version 0, flags: little endian,
  envelope [minx, maxx, miny, maxy] for polygons and none for points, standard type), the
  ``srs_id``, then the ISO WKB geometry.

The requirement numbers of the standard are not cited: the structure was written from the
standard as remembered and is checked by the tests (tables, columns, header); open a file in
QGIS once to confirm.

No R*Tree spatial index (an extension, optional; QGIS reads the layers without it) and no
``gpkg_ogr_contents`` (GDAL's own). Read: every feature table of ``gpkg_geometry_columns``,
points and polygons (and their multi forms), in their ``srs_id`` converted to WGS 84.
"""

from __future__ import annotations

import os
import sqlite3
import struct
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from saengine.gis.crs import to_wgs84
from saengine.gis.geojson import Shape

APPLICATION_ID = 0x47504B47
USER_VERSION = 10201

_WKB_TYPES = {1: "point", 3: "polygon", 4: "multipoint", 6: "multipolygon"}


@dataclass
class Layer:
    """A feature table to write: its name, geometry type (POINT or POLYGON), attribute columns
    (name -> SQLite type TEXT, REAL, INTEGER) and rows ``(geometry, attributes)``; a point
    geometry is (longitude, latitude), a polygon its exterior ring of them."""

    name: str
    geometry_type: str
    columns: dict[str, str]
    rows: list[tuple[Any, dict[str, Any]]] = field(default_factory=list)
    description: str = ""


# ─────────────────────────────── geometry encoding ───────────────────────────────


def wkb_point(lon: float, lat: float) -> bytes:
    return struct.pack("<BIdd", 1, 1, lon, lat)


def wkb_polygon(ring: list[tuple[float, float]]) -> bytes:
    ring = list(ring)
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    out = struct.pack("<BII", 1, 3, 1) + struct.pack("<I", len(ring))
    return out + b"".join(struct.pack("<dd", x, y) for x, y in ring)


def gpkg_geometry(geometry_type: str, geometry: Any, srs_id: int = 4326) -> bytes:
    """A GeoPackage geometry BLOB: header + ISO WKB."""
    if geometry_type == "POINT":
        flags = 0b0000_0001  # little endian, no envelope
        return b"GP" + bytes([0, flags]) + struct.pack("<i", srs_id) + wkb_point(*geometry)
    xs, ys = [p[0] for p in geometry], [p[1] for p in geometry]
    flags = 0b0000_0011  # little endian, envelope [minx, maxx, miny, maxy]
    envelope = struct.pack("<dddd", min(xs), max(xs), min(ys), max(ys))
    header = b"GP" + bytes([0, flags]) + struct.pack("<i", srs_id) + envelope
    return header + wkb_polygon(geometry)


_ENVELOPE_BYTES = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}


def parse_header(blob: bytes) -> tuple[int, int, bool]:
    """(srs_id, offset of the WKB, empty) of a GeoPackage geometry BLOB."""
    if blob[:2] != b"GP":
        raise ValueError("not a GeoPackage geometry (no 'GP' magic)")
    flags = blob[3]
    order = "<" if flags & 1 else ">"
    envelope = (flags >> 1) & 0b111
    if envelope not in _ENVELOPE_BYTES:
        raise ValueError(f"invalid envelope indicator {envelope}")
    (srs_id,) = struct.unpack(order + "i", blob[4:8])
    return srs_id, 8 + _ENVELOPE_BYTES[envelope], bool(flags & 0b1_0000)


def parse_wkb(data: bytes, offset: int = 0) -> tuple[str, Any, int]:
    """(kind, coordinates, next offset) of a WKB point, polygon, multipoint or multipolygon;
    a polygon's coordinates are its rings, Z/M ordinates are dropped."""
    order = "<" if data[offset] == 1 else ">"
    (code,) = struct.unpack_from(order + "I", data, offset + 1)
    offset += 5
    dims = 2
    if code > 1000:  # ISO Z, M, ZM: 1001.., 2001.., 3001..
        dims += {1: 1, 2: 1, 3: 2}[code // 1000]
        code %= 1000
    elif code & 0x80000000 or code & 0x40000000:  # EWKB-style Z/M flags
        dims += bool(code & 0x80000000) + bool(code & 0x40000000)
        code &= 0xFFFF
    kind = _WKB_TYPES.get(code)
    if kind is None:
        raise ValueError(f"WKB geometry type {code} is not a point or polygon")

    def xy(at: int) -> tuple[tuple[float, float], int]:
        values = struct.unpack_from(order + "d" * dims, data, at)
        return (values[0], values[1]), at + 8 * dims

    if kind == "point":
        p, offset = xy(offset)
        return kind, p, offset
    if kind == "polygon":
        (n_rings,) = struct.unpack_from(order + "I", data, offset)
        offset += 4
        rings = []
        for _ in range(n_rings):
            (n,) = struct.unpack_from(order + "I", data, offset)
            offset += 4
            ring = []
            for _ in range(n):
                p, offset = xy(offset)
                ring.append(p)
            rings.append(ring)
        return kind, rings, offset
    (n_parts,) = struct.unpack_from(order + "I", data, offset)
    offset += 4
    parts = []
    for _ in range(n_parts):
        _, coords, offset = parse_wkb(data, offset)
        parts.append(coords)
    return kind, parts, offset


# ─────────────────────────────── writing ───────────────────────────────


def _wgs84_wkt() -> str:
    from pyproj import CRS

    return CRS.from_epsg(4326).to_wkt("WKT1_GDAL")


_SCHEMA = """
CREATE TABLE gpkg_spatial_ref_sys (
  srs_name TEXT NOT NULL,
  srs_id INTEGER NOT NULL PRIMARY KEY,
  organization TEXT NOT NULL,
  organization_coordsys_id INTEGER NOT NULL,
  definition TEXT NOT NULL,
  description TEXT
);
CREATE TABLE gpkg_contents (
  table_name TEXT NOT NULL PRIMARY KEY,
  data_type TEXT NOT NULL,
  identifier TEXT UNIQUE,
  description TEXT DEFAULT '',
  last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  min_x DOUBLE,
  min_y DOUBLE,
  max_x DOUBLE,
  max_y DOUBLE,
  srs_id INTEGER,
  CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id)
);
CREATE TABLE gpkg_geometry_columns (
  table_name TEXT NOT NULL,
  column_name TEXT NOT NULL,
  geometry_type_name TEXT NOT NULL,
  srs_id INTEGER NOT NULL,
  z TINYINT NOT NULL,
  m TINYINT NOT NULL,
  CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),
  CONSTRAINT uk_gc_table_name UNIQUE (table_name),
  CONSTRAINT fk_gc_tn FOREIGN KEY (table_name) REFERENCES gpkg_contents(table_name),
  CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys (srs_id)
);
"""


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def write(path: str | Path, layers: list[Layer]) -> None:
    """Writes the layers to a new GeoPackage at ``path`` (an existing file is replaced once the
    new one is complete)."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(suffix=".gpkg", dir=path.parent)
    os.close(fd)
    os.unlink(tmp)
    con = sqlite3.connect(tmp)
    try:
        con.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        con.execute(f"PRAGMA user_version = {USER_VERSION}")
        con.executescript(_SCHEMA)
        con.executemany(
            "INSERT INTO gpkg_spatial_ref_sys VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("Undefined cartesian SRS", -1, "NONE", -1, "undefined",
                 "undefined cartesian coordinate reference system"),
                ("Undefined geographic SRS", 0, "NONE", 0, "undefined",
                 "undefined geographic coordinate reference system"),
                ("WGS 84 geodetic", 4326, "EPSG", 4326, _wgs84_wkt(),
                 "longitude/latitude coordinates in decimal degrees on the WGS 84 spheroid"),
            ],
        )  # fmt: skip
        for layer in layers:
            columns = "".join(f", {_quote(k)} {v}" for k, v in layer.columns.items())
            con.execute(
                f"CREATE TABLE {_quote(layer.name)} (fid INTEGER PRIMARY KEY AUTOINCREMENT "
                f"NOT NULL, geom {layer.geometry_type}{columns})"
            )
            points = [
                p
                for geometry, _ in layer.rows
                for p in ([geometry] if layer.geometry_type == "POINT" else geometry)
            ]
            bbox: list[float | None] = [None] * 4
            if points:
                xs, ys = [p[0] for p in points], [p[1] for p in points]
                bbox = [min(xs), min(ys), max(xs), max(ys)]
            con.execute(
                "INSERT INTO gpkg_contents (table_name, data_type, identifier, description, "
                "min_x, min_y, max_x, max_y, srs_id) VALUES (?, 'features', ?, ?, ?, ?, ?, ?, "
                "4326)",
                (layer.name, layer.name, layer.description, *bbox),
            )
            con.execute(
                "INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', ?, 4326, 0, 0)",
                (layer.name, layer.geometry_type),
            )
            names = list(layer.columns)
            marks = ", ".join("?" for _ in range(len(names) + 1))
            sql = (
                f"INSERT INTO {_quote(layer.name)} (geom"
                + "".join(f", {_quote(n)}" for n in names)
                + f") VALUES ({marks})"
            )
            con.executemany(
                sql,
                [
                    (gpkg_geometry(layer.geometry_type, g), *(a.get(n) for n in names))
                    for g, a in layer.rows
                ],
            )
        con.commit()
    finally:
        con.close()
    os.replace(tmp, path)


# ─────────────────────────────── reading ───────────────────────────────


def read(path: str | Path) -> tuple[list[Shape], list[str]]:
    """The points and polygons of every feature table, in WGS 84, and the problems."""
    name = Path(path).name
    con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        (app,) = con.execute("PRAGMA application_id").fetchone()
        problems = []
        if app not in (APPLICATION_ID, 0x47503130):  # "GPKG", or "GP10" of version 1.0
            problems.append(f"{name}: the application id is not 'GPKG'; reading it anyway")
        srs = {
            row[0]: (row[1], row[2])
            for row in con.execute(
                "SELECT srs_id, organization, organization_coordsys_id FROM gpkg_spatial_ref_sys"
            )
        }
        tables = con.execute(
            "SELECT table_name, column_name, srs_id FROM gpkg_geometry_columns"
        ).fetchall()
        shapes: list[Shape] = []
        for table, column, srs_id in tables:
            organization, code = srs.get(srs_id, ("NONE", srs_id))
            if str(organization).upper() != "EPSG":
                problems.append(
                    f"{name}: {table}: its coordinate system ({organization} {code}) is not an "
                    "EPSG one; the layer is not read"
                )
                continue
            cursor = con.execute(f"SELECT * FROM {_quote(table)}")
            names = [d[0] for d in cursor.description]
            for number, row in enumerate(cursor, 1):
                values = dict(zip(names, row, strict=True))
                blob = values.pop(column)
                where = f"{name}: {table}: feature {values.get('fid', number)}"
                if blob is None:
                    continue
                try:
                    _, offset, empty = parse_header(blob)
                    if empty:
                        continue
                    kind, coords, _ = parse_wkb(blob, offset)
                except (ValueError, struct.error, KeyError) as exc:
                    problems.append(f"{where}: {exc}")
                    continue
                values["_layer"] = table

                def ll(p: tuple[float, float], code: int = int(code)) -> tuple[float, float]:
                    return to_wgs84(code, p[0], p[1])

                if kind == "point":
                    shapes.append(Shape("point", [ll(coords)], values, where))
                elif kind == "multipoint":
                    shapes += [Shape("point", [ll(p)], values, where) for p in coords]
                elif kind == "polygon":
                    shapes.append(Shape("polygon", [ll(p) for p in coords[0]], values, where))
                else:
                    shapes += [
                        Shape("polygon", [ll(p) for p in poly[0]], values, where) for poly in coords
                    ]
        return shapes, problems
    finally:
        con.close()

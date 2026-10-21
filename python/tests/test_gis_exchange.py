"""The exchange with QGIS: GeoJSON (RFC 7946) and GeoPackage files written to the standards'
structure, and read back into the soil report."""

from __future__ import annotations

import itertools
import json
import sqlite3
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from test_gis_location import BIM

from saengine.gis import gpkg
from saengine.gis.site import (
    gis_export,
    gis_import,
    qgis_command,
    qgis_command_line,
    qgis_program,
)
from saengine.library.soil import SoilReport

SITE_POINT = {"lat": 23.8069, "lon": 90.3687, "x": 5000, "y": 2000, "rotation": 15}

SOIL = {
    "schema": "saengine.soilReport/1",
    "report": {"title": "Synthetic site"},
    "site": {
        "address": "Plot 1",
        **SITE_POINT,
        "boundary": [
            [90.3686, 23.8068],
            [90.3690, 23.8068],
            [90.3690, 23.8071],
            [90.3686, 23.8071],
        ],
    },
    "boreholes": [
        {
            "id": f"BH-{i}",
            "x": x,
            "y": y,
            "waterTable": 2000,
            "depth": 15000,
            "layers": [{"top": 0, "bottom": 15000, "soilType": "sand"}],
            "spt": [{"depth": d, "N": 8 + d // 1500} for d in range(1500, 15001, 1500)],
        }
        for i, (x, y) in enumerate([(0, 0), (20000, 0), (10000, 10000)], 1)
    ],
}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "01 Soil Report").mkdir()
    (tmp_path / "01 Soil Report" / "soil-report.json").write_text(json.dumps(SOIL), "utf-8")
    (tmp_path / "06 BIM").mkdir()
    (tmp_path / "06 BIM" / "bim.json").write_text(json.dumps(BIM), "utf-8")
    return tmp_path


def ring_area(ring: list[list[float]]) -> float:
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in itertools.pairwise(ring)) / 2


def test_geojson_follows_rfc_7946(project: Path) -> None:
    out = gis_export(str(project), "geojson", str(project / "11 Exports" / "site.geojson"))
    assert out["problems"] == [] and out["counts"] == {
        "site": 1, "site_boundary": 1, "boreholes": 3, "building": 1,
    }  # fmt: skip
    data = json.loads(Path(out["path"]).read_text("utf-8"))
    assert data["type"] == "FeatureCollection" and "crs" not in data  # §4: WGS 84 only
    assert len(data["bbox"]) == 4
    for feature in data["features"]:
        assert feature["type"] == "Feature" and isinstance(feature["properties"], dict)
        geometry = feature["geometry"]
        if geometry["type"] == "Point":
            lon, lat = geometry["coordinates"]
            assert 90 < lon < 91 and 23 < lat < 24  # [longitude, latitude] order (§3.1.1)
        else:
            assert geometry["type"] == "Polygon"
            ring = geometry["coordinates"][0]
            assert len(ring) >= 4 and ring[0] == ring[-1]  # closed linear ring (§3.1.6)
            assert ring_area(ring) > 0  # exterior counter-clockwise (right-hand rule)
    holes = [f for f in data["features"] if f["properties"]["layer"] == "boreholes"]
    assert holes[0]["id"] == "BH-1" and holes[0]["properties"]["depth_m"] == 15.0
    assert holes[0]["properties"]["water_table_m"] == 2.0
    assert holes[0]["properties"]["site_class"] in ("SC", "SD")


def test_geopackage_structure(project: Path) -> None:
    path = project / "site.gpkg"
    out = gis_export(str(project), "gpkg", str(path))
    assert out["problems"] == []
    con = sqlite3.connect(path)
    try:
        assert con.execute("PRAGMA application_id").fetchone()[0] == 0x47504B47  # "GPKG"
        assert con.execute("PRAGMA user_version").fetchone()[0] == 10201
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []

        def columns(table: str) -> list[str]:
            return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]

        assert columns("gpkg_spatial_ref_sys") == [
            "srs_name", "srs_id", "organization", "organization_coordsys_id", "definition",
            "description",
        ]  # fmt: skip
        assert columns("gpkg_contents") == [
            "table_name", "data_type", "identifier", "description", "last_change", "min_x",
            "min_y", "max_x", "max_y", "srs_id",
        ]  # fmt: skip
        assert columns("gpkg_geometry_columns") == [
            "table_name", "column_name", "geometry_type_name", "srs_id", "z", "m",
        ]  # fmt: skip
        srs = {
            r[0]: r
            for r in con.execute(
                "SELECT srs_id, organization, definition FROM gpkg_spatial_ref_sys"
            )
        }
        assert set(srs) == {-1, 0, 4326}
        assert srs[4326][1] == "EPSG" and srs[4326][2].startswith('GEOGCS["WGS 84"')
        contents = con.execute(
            "SELECT table_name, data_type, srs_id, min_x, max_x, last_change FROM gpkg_contents"
        ).fetchall()
        assert {r[0] for r in contents} == {"site", "site_boundary", "boreholes", "building"}
        for _, data_type, srs_id, min_x, max_x, last_change in contents:
            assert data_type == "features" and srs_id == 4326 and min_x <= max_x
            assert last_change.endswith("Z") and "T" in last_change
        geometry = dict(
            con.execute("SELECT table_name, geometry_type_name FROM gpkg_geometry_columns")
        )
        assert geometry == {
            "site": "POINT", "site_boundary": "POLYGON", "boreholes": "POINT", "building": "POLYGON",
        }  # fmt: skip
        assert columns("boreholes")[:2] == ["fid", "geom"]
        blob, hole_id = con.execute("SELECT geom, id FROM boreholes ORDER BY fid").fetchone()
        assert hole_id == "BH-1"
        # Header: "GP", version 0, flags 0b1 (little endian, no envelope), srs_id 4326.
        assert blob[:2] == b"GP" and blob[2] == 0 and blob[3] == 0b1
        assert struct.unpack("<i", blob[4:8])[0] == 4326
        order, kind = struct.unpack("<BI", blob[8:13])
        assert (order, kind) == (1, 1)  # little-endian WKB point
        lon, lat = struct.unpack("<dd", blob[13:29])
        assert 90 < lon < 91 and 23 < lat < 24
        (poly,) = con.execute("SELECT geom FROM building").fetchone()
        assert poly[3] == 0b11  # envelope [minx, maxx, miny, maxy]
        minx, maxx, miny, maxy = struct.unpack("<dddd", poly[8:40])
        _, rings, _ = gpkg.parse_wkb(poly, 40)
        xs, ys = [p[0] for p in rings[0]], [p[1] for p in rings[0]]
        assert (minx, maxx, miny, maxy) == (min(xs), max(xs), min(ys), max(ys))
        assert rings[0][0] == rings[0][-1]
    finally:
        con.close()


@pytest.mark.parametrize("suffix", ["gpkg", "geojson"])
def test_round_trip_through_gis_import(project: Path, suffix: str) -> None:
    path = project / f"site.{suffix}"
    gis_export(str(project), suffix, str(path))
    # Into an empty report: the site point comes back (lat/lon, x/y, rotation), and with it
    # the boreholes where they were.
    empty = json.dumps({})
    out = gis_import(str(path), empty)
    assert out["problems"] == [] and out["added"] == ["BH-1", "BH-2", "BH-3"]
    assert out["boundary"] is True
    report = SoilReport.model_validate_json(out["soilText"])
    for hole, original in zip(report.boreholes, SOIL["boreholes"], strict=True):
        assert hole.position == "wgs84"
        assert (hole.x, hole.y) == pytest.approx((original["x"], original["y"]), abs=1)
        assert hole.depth == 15000 and hole.waterTable == 2000
    assert len(report.site.boundary) == 4  # type: ignore[union-attr]
    # Into the report itself: the same boreholes are updated, their logs kept, and as they
    # are where they were, they stay given in project x/y, exactly.
    again = gis_import(str(path), json.dumps(SOIL))
    assert again["updated"] == ["BH-1", "BH-2", "BH-3"] and again["added"] == []
    kept = SoilReport.model_validate_json(again["soilText"])
    assert len(kept.boreholes[0].spt) == 10
    for hole, original in zip(kept.boreholes, SOIL["boreholes"], strict=True):
        assert (hole.position, hole.x, hole.y) == ("project", original["x"], original["y"])
        assert hole.lat is None and hole.easting is None
    assert sum("its position is kept" in n for n in again["notes"]) == 3


def test_a_moved_point_moves_the_borehole_and_drops_its_btm(tmp_path: Path) -> None:
    from saengine.gis.crs import wgs84_to_btm

    e, n = wgs84_to_btm(23.80, 90.40)
    soil = {
        "boreholes": [
            {"id": "BH-1", "easting": e, "northing": n, "layers": [], "spt": []},
            {"id": "BH-2", "easting": e + 50, "northing": n, "layers": [], "spt": []},
        ]
    }
    # BH-1 0.004 m away (an export's rounding): kept in BTM; BH-2 moved about 100 m.
    from saengine.gis.crs import btm_to_wgs84

    lat1, lon1 = btm_to_wgs84(e + 0.004, n)
    lat2, lon2 = btm_to_wgs84(e + 150, n)
    data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {"id": bh},
            }
            for bh, lat, lon in (("BH-1", lat1, lon1), ("BH-2", lat2, lon2))
        ],
    }
    path = tmp_path / "moved.geojson"
    path.write_text(json.dumps(data), "utf-8")
    out = gis_import(str(path), json.dumps(soil))
    holes = {b.id: b for b in SoilReport.model_validate_json(out["soilText"]).boreholes}
    assert (holes["BH-1"].position, holes["BH-1"].easting) == ("btm", e)
    moved = holes["BH-2"]
    assert moved.position == "wgs84" and moved.easting is None and moved.northing is None
    assert moved.lat == pytest.approx(lat2, abs=1e-8)
    assert any("BH-2 moved" in note for note in out["notes"])


def test_import_points_in_btm_with_attribute_mapping(tmp_path: Path) -> None:
    from saengine.gis.crs import wgs84_to_btm

    e, n = wgs84_to_btm(23.80, 90.40)
    data = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::9678"}},
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [e, n]},
                "properties": {"Name": "BH-7", "Depth_mm": 21000, "GWT": 1.8, "RL": 6.5},
            },
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            },
        ],
    }
    path = tmp_path / "points.geojson"
    path.write_text(json.dumps(data), "utf-8")
    out = gis_import(str(path), None)
    assert out["added"] == ["BH-7"] and "LineString" in out["problems"][0]
    hole = SoilReport.model_validate_json(out["soilText"]).boreholes[0]
    assert hole.lat == pytest.approx(23.80, abs=1e-7)
    assert hole.lon == pytest.approx(90.40, abs=1e-7)
    assert (hole.depth, hole.waterTable, hole.groundLevel) == (21000, 1800, 6500)
    assert any("no latitude/longitude" in note for note in out["notes"])


def test_points_without_an_id_never_move_an_existing_borehole(tmp_path: Path) -> None:
    layers = [{"top": 0, "bottom": 5000, "soilType": "sand"}]
    soil = {
        "site": {"lat": 23.81, "lon": 90.41},
        "boreholes": [
            {"id": "BH-1", "x": 0, "y": 0, "layers": layers, "spt": [{"depth": 1500, "N": 5}]},
            {"id": "BH-3", "x": 20000, "y": 0, "layers": layers, "spt": [{"depth": 1500, "N": 9}]},
        ],
    }
    point = {"type": "Feature", "properties": {}}
    data = {
        "type": "FeatureCollection",
        "features": [
            {**point, "geometry": {"type": "Point", "coordinates": [90.42, 23.82]}},
            {**point, "geometry": {"type": "Point", "coordinates": [90.43, 23.83]}},
        ],
    }
    path = tmp_path / "unnamed.geojson"
    path.write_text(json.dumps(data), "utf-8")
    out = gis_import(str(path), json.dumps(soil))
    # Two existing boreholes, so the first free ids are BH-4 (BH-3 is taken) and BH-5.
    assert out["added"] == ["BH-4", "BH-5"] and out["updated"] == [] and out["problems"] == []
    holes = {b.id: b for b in SoilReport.model_validate_json(out["soilText"]).boreholes}
    assert (holes["BH-3"].position, holes["BH-3"].x, holes["BH-3"].y) == ("project", 20000, 0)
    assert holes["BH-5"].lat == pytest.approx(23.83)


def test_unreadable_files_are_problems(tmp_path: Path) -> None:
    bad = tmp_path / "bad.gpkg"
    bad.write_text("not sqlite", "utf-8")
    assert gis_import(str(bad), None)["problems"]
    assert gis_export(str(tmp_path), "shp", str(tmp_path / "x.shp"))["problems"]


def test_qgis_command() -> None:
    assert qgis_command(r"C:\QGIS\bin\qgis-bin.exe", r"D:\p\site.gpkg") == [
        r"C:\QGIS\bin\qgis-bin.exe", r"D:\p\site.gpkg",
    ]  # fmt: skip
    assert qgis_command(r"C:\OSGeo4W\bin\qgis.bat", "a.gpkg") == [
        "cmd.exe", "/d", "/v:off", "/s", "/c", r'""C:\OSGeo4W\bin\qgis.bat" "a.gpkg""',
    ]  # fmt: skip
    for unsafe in ("50%.gpkg", 'a".gpkg', "%PATH%.gpkg"):
        with pytest.raises(ValueError, match="rename the file"):
            qgis_command(r"C:\OSGeo4W\bin\qgis.bat", unsafe)
    assert qgis_command(r"C:\QGIS\bin\qgis-bin.exe", "50%.gpkg")[1] == "50%.gpkg"  # no shell
    found = qgis_program()
    assert found is None or Path(found).is_file()


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe")
@pytest.mark.parametrize("name", ["plain.gpkg", "site export.gpkg", "R&D (v2).gpkg", "a^b|c.gpkg"])
def test_qgis_bat_launcher_gets_the_path_whole(tmp_path: Path, name: str) -> None:
    # A stand-in launcher in a folder with a space writes the argument it got to a file.
    folder = tmp_path / "OSGeo4W dir" / "bin"
    folder.mkdir(parents=True)
    got = tmp_path / "got.txt"
    bat = folder / "qgis.bat"
    # %1 keeps the quotes, so the stand-in's own echo does not re-split the path.
    bat.write_text(f'@echo off\r\n>"{got}" echo %1\r\n', "ascii")
    target = tmp_path / "exports & more" / name
    target.parent.mkdir()
    line = qgis_command_line(str(bat), str(target))
    done = subprocess.run(line, check=False, capture_output=True, timeout=30)
    assert done.returncode == 0 and not done.stderr, done.stderr
    assert got.read_text("mbcs").strip() == f'"{target}"'

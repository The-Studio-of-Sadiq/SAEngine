"""The site on the map: WGS 84 ↔ BTM ↔ project grid, the nearest BNBC town and
``soil_location``, against hand calculations."""

from __future__ import annotations

import json
import math

import pytest
from pyproj import CRS, Transformer

from saengine.gis import towns
from saengine.gis.crs import Grid, btm_to_wgs84, haversine_km, wgs84_to_btm
from saengine.gis.site import building_outline, soil_location, suggestion
from saengine.library import bnbc
from saengine.library.soil import Site, SoilReport

# WGS 84 ellipsoid.
A, F = 6378137.0, 1 / 298.257223563
E2 = F * (2 - F)

# Everest 1830 (1937 adjustment), the BTM ellipsoid.
A_EV, INV_F_EV = 6377276.345, 300.8017


def meridian_arc(phi: float, a: float, e2: float) -> float:
    """Meridian distance from the equator [m] (the series of e.g. Snyder 1987, eq. 3-21)."""
    e4, e6 = e2 * e2, e2**3
    return a * (
        (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
        - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
        + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
        - (35 * e6 / 3072) * math.sin(6 * phi)
    )


def test_btm_is_epsg_9678() -> None:
    crs = CRS.from_epsg(9678)
    assert crs.name == "Gulshan 303 / Bangladesh Transverse Mercator"
    params = {p.name: p.value for p in crs.coordinate_operation.params}
    assert params["Longitude of natural origin"] == 90
    assert params["Scale factor at natural origin"] == pytest.approx(0.9996)
    assert params["False easting"] == 500000 and params["False northing"] == -2000000
    assert crs.ellipsoid.semi_major_metre == pytest.approx(A_EV)
    assert crs.ellipsoid.inverse_flattening == pytest.approx(INV_F_EV)


def test_btm_on_the_central_meridian_by_hand() -> None:
    """On the central meridian E = 500 000 m and N = k0 M(φ) - 2 000 000 m, M the meridian arc
    of the Everest ellipsoid (Gulshan 303 geographic, before the datum shift)."""
    f = 1 / INV_F_EV
    e2 = f * (2 - f)
    to_btm = Transformer.from_crs(4682, 9678, always_xy=True)
    for lat in (21.0, 23.5, 26.0):
        e, n = to_btm.transform(90.0, lat)
        assert e == pytest.approx(500000, abs=1e-6)
        assert n == pytest.approx(
            0.9996 * meridian_arc(math.radians(lat), A_EV, e2) - 2e6, abs=1e-3
        )


def test_wgs84_btm_round_trip() -> None:
    lat, lon = 23.7104, 90.4074
    e, n = wgs84_to_btm(lat, lon)
    # Dhaka lies about 41.6 km east of 90° E: the easting is near 541.6 km.
    assert 541_000 < e < 542_500 and 600_000 < n < 650_000
    back = btm_to_wgs84(e, n)
    # The 2D datum shift drops the height between the directions: a few mm at most.
    assert back[0] == pytest.approx(lat, abs=1e-7) and back[1] == pytest.approx(lon, abs=1e-7)


def radii(lat: float) -> tuple[float, float]:
    """(ρ meridional, ν prime vertical) radii of curvature of WGS 84 [m]."""
    s2 = math.sin(math.radians(lat)) ** 2
    nu = A / math.sqrt(1 - E2 * s2)
    rho = A * (1 - E2) / (1 - E2 * s2) ** 1.5
    return rho, nu


@pytest.mark.parametrize("rotation", [0.0, 30.0, 90.0, -45.0])
def test_project_grid_by_hand(rotation: float) -> None:
    """A point 300 m along +X and 400 m along +Y: east/north by the rotation, then degrees by
    the radii of curvature at the origin (good to a few mm over 500 m)."""
    lat0, lon0 = 23.80, 90.40
    grid = Grid(Site(lat=lat0, lon=lon0, rotation=rotation))
    x, y = 300_000.0, 400_000.0
    t = math.radians(rotation)
    east = 300 * math.cos(t) + 400 * math.sin(t)
    north = -300 * math.sin(t) + 400 * math.cos(t)
    rho, nu = radii(lat0)
    lat, lon = grid.to_wgs84(x, y)
    assert (lat - lat0) * math.pi / 180 * rho == pytest.approx(north, abs=0.02)
    assert (lon - lon0) * math.pi / 180 * nu * math.cos(math.radians(lat)) == pytest.approx(
        east, abs=0.02
    )
    # Distances in the grid are true distances: 500 m.
    assert haversine_km(lat0, lon0, lat, lon) * 1e3 == pytest.approx(500, rel=5e-3)
    # Round trips: WGS 84 exactly, BTM to a few mm.
    assert grid.from_wgs84(lat, lon) == pytest.approx((x, y), abs=0.2)
    assert grid.from_btm(*grid.to_btm(x, y)) == pytest.approx((x, y), abs=5)


def test_boreholes_given_in_lat_lon_or_btm_get_project_xy() -> None:
    site = {"lat": 23.80, "lon": 90.40, "x": 2000, "y": -1000, "rotation": 90}
    grid = Grid(Site(**site))
    lat, lon = grid.to_wgs84(10_000, 20_000)
    e, n = grid.to_btm(-5_000, 7_000)
    report = SoilReport.model_validate(
        {
            "site": site,
            "boreholes": [
                {"id": "BH-1", "lat": lat, "lon": lon},
                {"id": "BH-2", "easting": e, "northing": n},
                {"id": "BH-3", "x": 1000, "y": 2000},
            ],
        }
    )
    bh1, bh2, bh3 = report.boreholes
    assert (bh1.x, bh1.y) == pytest.approx((10_000, 20_000), abs=0.2)
    assert (bh2.x, bh2.y) == pytest.approx((-5_000, 7_000), abs=5)
    assert (bh3.x, bh3.y) == (1000, 2000)
    with pytest.raises(ValueError, match="needs both"):
        SoilReport.model_validate({"boreholes": [{"id": "B", "position": "wgs84", "lat": 1}]})


# ─────────────────────────────── towns ───────────────────────────────


def test_towns_are_in_bangladesh_with_the_code_values() -> None:
    names = [t.name for t in towns.TOWNS]
    assert len(names) == len(set(names))
    for t in towns.TOWNS:
        assert 20.5 <= t.latitude <= 26.7 and 88.0 <= t.longitude <= 92.7, t.name
        assert t.z is None or t.z in towns.ZONES
    assert all(name in names for name in towns.SETTINGS_IDS)
    assert set(towns.SETTINGS_IDS.values()) <= set(bnbc.LOCATIONS)
    by_name = {t.name: t for t in towns.TOWNS}
    # Spot values read from BNBC 2020 Tables 6.2.15 and 6.2.8.
    assert by_name["Dhaka"][3:] == (0.20, 65.7)
    assert by_name["Sylhet"][3:] == (0.36, 61.1)
    assert by_name["Chittagong"][3:] == (0.28, 80.0)
    assert by_name["Rajshahi"][3:] == (0.12, 49.2)
    assert by_name["Mymensingh"][3:] == (0.36, 67.4)


def test_nearest_town_from_the_site() -> None:
    town, km = towns.nearest(23.7104, 90.4074)  # central Dhaka
    assert town.name == "Dhaka" and km < 15
    s = suggestion(23.7104, 90.4074)
    assert (s["town"], s["zone"], s["Z"], s["windSpeed"]) == ("Dhaka", 2, 0.20, 65.7)
    assert s["settingsLocation"] == "dhaka"
    s = suggestion(24.90, 91.87)
    assert (s["town"], s["zone"]) == ("Sylhet", 4)
    # Mongla has no wind speed in Table 6.2.8: the wind comes from the nearest town listed.
    s = suggestion(22.48, 89.60)
    assert s["town"] == "Mongla" and s["windTown"] != "Mongla" and s["windSpeed"] is not None


def test_suggestion_against_the_settings() -> None:
    from saengine.library.settings import default_project_settings

    settings = default_project_settings().model_dump_json(by_alias=True)  # location dhaka
    assert suggestion(23.75, 90.39, settings)["differs"] is False
    sylhet = suggestion(24.90, 91.87, settings)
    assert sylhet["differs"] is True and sylhet["current"]["location"] == "dhaka"
    assert sylhet["valueNotes"] == [
        "Z: Project Settings 0.2, BNBC 2020 Table 6.2.15 for Sylhet 0.36",
        "V: Project Settings 65.7 m/s, BNBC 2020 Table 6.2.8 for Sylhet 61.1 m/s",
    ]


def test_suggestion_of_the_settings_own_town_is_not_open_for_ever() -> None:
    # Project Settings already name the suggested town: applying it changes nothing, so it is
    # not "differs" even where the settings' town table disagrees with BNBC 2020 (Rajshahi's
    # V, Mymensingh's Z in library/bnbc.py at the time of writing): that is a value note.
    from saengine.library.settings import default_project_settings

    for lat, lon, town in ((24.37, 88.60, "rajshahi"), (24.75, 90.42, "mymensingh")):
        settings = default_project_settings()
        settings.site.location = town
        s = suggestion(lat, lon, settings.model_dump_json(by_alias=True))
        assert s["settingsLocation"] == town and s["differs"] is False
        table = bnbc.LOCATIONS[town]
        agrees = (
            abs(bnbc.ZONE_COEFFICIENT[table.zone] - s["Z"]) < 1e-9
            and abs(table.wind_speed - s["windSpeed"]) < 0.05
        )
        assert (s["valueNotes"] == []) == agrees


# ─────────────────────────────── soil_location ───────────────────────────────

BIM = {
    "schema": "saengine.bim/2",
    "stories": [{"id": "L1", "name": "Level 1", "elevation": 3000}],
    "elements": [
        {
            "id": "S1",
            "type": "SL150",
            "kind": "slab",
            "boundary": [[0, 0], [20000, 0], [20000, 10000], [0, 10000]],
            "elevation": 3000,
        },
        {"id": "C1", "type": "C1", "kind": "column", "position": [0, 0], "bottom": 0, "top": 3000},
    ],
}


def test_building_outline_from_the_slabs() -> None:
    ring, how = building_outline(json.dumps(BIM))
    assert how == "outline of the slabs"
    assert sorted(ring) == [(0, 0), (0, 10000), (20000, 0), (20000, 10000)]
    columns = {**BIM, "elements": [
        {"id": f"C{i}", "type": "C1", "kind": "column", "position": p, "bottom": 0, "top": 3000}
        for i, p in enumerate([[0, 0], [6000, 0], [6000, 5000], [0, 5000], [3000, 2500]])
    ]}  # fmt: skip
    ring, how = building_outline(json.dumps(columns))
    assert how == "convex hull of the elements" and len(ring) == 4


def test_soil_location() -> None:
    soil = {
        "site": {
            "address": "Plot 12, Mirpur",
            "lat": 23.80,
            "lon": 90.36,
        },
        "boreholes": [{"id": "BH-1", "x": 10000, "y": 5000}],
    }
    out = soil_location(json.dumps(soil), json.dumps(BIM))
    assert out["problems"] == []
    assert out["site"]["georeferenced"] and out["site"]["lat"] == 23.80
    bh = out["boreholes"][0]
    rho, _nu = radii(23.80)
    assert (bh["lat"] - 23.80) * math.pi / 180 * rho == pytest.approx(5, abs=0.01)
    assert bh["btm"]["easting"] == pytest.approx(wgs84_to_btm(bh["lat"], bh["lon"])[0])
    ring = out["outline"]
    assert len(ring) == 5 and ring[0] == ring[-1]
    assert sorted(map(tuple, out["outlineProject"])) == [
        (0, 0),
        (0, 10000),
        (20000, 0),
        (20000, 10000),
    ]
    assert out["suggestion"]["town"] == "Dhaka"
    # Without a site point: the boreholes given in lat/lon say where the site is, but the
    # project grid (the borehole in x/y, the building) is not on the map.
    soil = {
        "boreholes": [
            {"id": "BH-1", "x": 10000, "y": 5000},
            {"id": "BH-2", "lat": 24.90, "lon": 91.87},
        ]
    }
    out = soil_location(json.dumps(soil), json.dumps(BIM))
    assert out["outline"] is None and out["boreholes"][0]["lat"] is None
    assert out["boreholes"][1]["x"] is None and out["site"]["georeferenced"] is False
    assert out["suggestion"]["town"] == "Sylhet" and "no latitude/longitude" in out["problems"][0]
    # No site at all: no suggestion.
    assert soil_location(json.dumps({"boreholes": []}))["suggestion"] is None

"""The soil report's site on the map, and the exchange with QGIS: the API the workbench calls.

- :func:`soil_location`: the site, the boreholes in every coordinate system, the building
  outline (06 BIM) on the map, and the BNBC location the site suggests;
- :func:`gis_export`: the site, its boundary, the boreholes (with their key values) and the
  building outline as GeoJSON or a GeoPackage, in WGS 84;
- :func:`gis_import`: boreholes (points) and the site boundary (a polygon) from GeoJSON or a
  GeoPackage, merged into the soil report;
- :func:`qgis_program`: an installed QGIS, for "Open in QGIS" (:func:`qgis_command`).

The site point (``site.lat``/``lon``, the project point ``site.x``/``y``, the grid's
``rotation``) georeferences the project grid. Without it the grid is not on the map: boreholes
given in project x/y and the building have no latitude/longitude, and the map can show only
the project-grid drawing (``outlineProject``, the boreholes' x/y).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from saengine.gis import geojson, gpkg, towns
from saengine.gis.crs import BTM_NAME, Grid, btm_to_wgs84, wgs84_to_btm
from saengine.library.soil import Borehole, Site, SoilReport

SOIL_FILE = "01 Soil Report/soil-report.json"
BIM_FILE = "06 BIM/bim.json"
SETTINGS_FILE = "02 Project Settings/project-settings.json"

FORMATS = {"geojson": ".geojson", "gpkg": ".gpkg"}

#: Attribute names an imported feature's id, depth, ground level and water table may have
#: (case and separators ignored). Values are metres unless the name ends in "mm".
ID_KEYS = ("id", "name", "borehole", "bh", "boreholeid", "label", "title")
DEPTH_KEYS = ("depth", "depthm", "depthmm", "termination", "terminationdepth", "totaldepth")
GROUND_KEYS = (
    "groundlevel", "groundm", "groundmm", "groundlevelm", "groundlevelmm", "gl", "rl",
    "elevation", "elev", "z",
)  # fmt: skip
WATER_KEYS = ("watertable", "waterm", "watermm", "watertablem", "watertablemm", "gwt", "wt", "gwl")

#: An imported point this close to an existing borehole [m] is at the same place: the
#: borehole keeps its position as given (the 1e-8° rounding of an export is about 1 mm).
SAME_PLACE = 0.01


def _metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance between two nearby WGS 84 points [m] (equirectangular, ample for metres)."""
    import math

    k = 6_371_008.8 * math.pi / 180
    dy = (lat2 - lat1) * k
    dx = (lon2 - lon1) * k * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


# ─────────────────────────────── reading the project files ───────────────────────────────


def _report(soil_text: str | None) -> SoilReport | list[str]:
    from saengine.soil.report import parse

    return parse(soil_text or "")


def building_outline(bim_text: str | None) -> tuple[list[tuple[float, float]] | None, str]:
    """The building's plan outline in project mm, counter-clockwise, and how it was found: the
    union of the slabs (its largest part), else the convex hull of every element's plan
    points."""
    if not bim_text or not bim_text.strip():
        return None, "no building model"
    from shapely.geometry import MultiPoint, Polygon
    from shapely.ops import unary_union

    from saengine.library.bim import BuildingModel

    try:
        bim = BuildingModel.model_validate_json(bim_text)
    except ValidationError:
        return None, "the building model has errors"
    slabs, points = [], []
    for e in bim.elements:
        kind = e.kind
        if kind == "slab":
            ring = [(float(p[0]), float(p[1])) for p in e.boundary]
            points += ring
            polygon = Polygon(ring).buffer(0)
            if not polygon.is_empty:
                slabs.append(polygon)
        elif kind in ("column", "footing"):
            points.append((float(e.position[0]), float(e.position[1])))
        elif kind in ("beam", "wall", "member"):
            points += [(float(e.start[0]), float(e.start[1])), (float(e.end[0]), float(e.end[1]))]
        elif kind in ("area", "block"):
            points += [(float(p[0]), float(p[1])) for p in e.outline]
    if slabs:
        union = unary_union(slabs)
        parts = list(getattr(union, "geoms", [union]))
        shape, how = max(parts, key=lambda g: g.area), "outline of the slabs"
    elif len(points) >= 3:
        shape, how = MultiPoint(points).convex_hull, "convex hull of the elements"
    else:
        return None, "the building model has no plan extent"
    if shape.geom_type != "Polygon" or shape.area <= 0:
        return None, "the building model has no plan extent"
    shape = shape.simplify(1.0)  # drop collinear points (1 mm)
    ring = [(round(x, 1), round(y, 1)) for x, y in shape.exterior.coords]
    ring = ring[:-1]
    area = sum(
        x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True)
    )
    return (ring if area > 0 else ring[::-1]), how


def _settings_location(settings_text: str | None) -> dict[str, Any] | None:
    if not settings_text:
        return None
    from saengine.library.settings import ProjectSettings, derived

    try:
        settings = ProjectSettings.model_validate_json(settings_text)
    except ValidationError:
        return None
    values = derived(settings)
    return {
        "location": settings.site.location,
        "zone": values["zone"],
        "Z": values["Z"],
        "windSpeed": values["windSpeed"],
    }


def suggestion(
    latitude: float, longitude: float, settings_text: str | None = None
) -> dict[str, Any]:
    """The BNBC zone and wind speed of the nearest listed towns, as a suggestion."""
    z_town, z_km = towns.nearest(latitude, longitude, need="z")
    v_town, v_km = towns.nearest(latitude, longitude, need="wind")
    zone = towns.ZONES[z_town.z] if z_town.z is not None else None
    out: dict[str, Any] = {
        "town": z_town.name,
        "distanceKm": round(z_km, 1),
        "zone": zone,
        "Z": z_town.z,
        "windSpeed": v_town.wind_speed,
        "windTown": v_town.name,
        "windDistanceKm": round(v_km, 1),
        "settingsLocation": towns.SETTINGS_IDS.get(z_town.name),
        "source": "BNBC 2020 Table 6.2.15 (Z) and Table 6.2.8 (V) of the nearest listed town; "
        "the zoning map (Figure 6.2.24) and the wind map (Figure 6.2.1) govern",
        "note": "A suggestion only: confirm the location in Project Settings.",
    }
    current = _settings_location(settings_text)
    if current is not None:
        out["current"] = current
        z_differs = current["Z"] is not None and abs(current["Z"] - z_town.z) > 1e-9
        v_differs = (
            current["windSpeed"] is not None
            and v_town.wind_speed is not None
            and abs(current["windSpeed"] - v_town.wind_speed) > 0.05
        )
        # "differs": applying the suggestion would change the Project Settings location. When
        # the settings already name the suggested town, it cannot clear a difference in the
        # values (the settings' town table is then what disagrees): that is reported in
        # "valueNotes" instead, so the suggestion does not stay open for ever.
        same_town = (
            out["settingsLocation"] is not None and current["location"] == out["settingsLocation"]
        )
        out["differs"] = not same_town and (
            out["settingsLocation"] is not None or z_differs or v_differs
        )
        notes = []
        if z_differs:
            notes.append(
                f"Z: Project Settings {current['Z']:g}, BNBC 2020 Table 6.2.15 for {z_town.name} "
                f"{z_town.z:g}"
            )
        if v_differs:
            notes.append(
                f"V: Project Settings {current['windSpeed']:g} m/s, BNBC 2020 Table 6.2.8 for "
                f"{v_town.name} {v_town.wind_speed:g} m/s"
            )
        out["valueNotes"] = notes
    return out


# ─────────────────────────────── soil_location ───────────────────────────────


def _r(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _borehole_location(borehole: Borehole, grid: Grid | None) -> dict[str, Any]:
    lat, lon = borehole.lat, borehole.lon
    easting, northing = borehole.easting, borehole.northing
    if borehole.position == "btm" and easting is not None and northing is not None:
        lat, lon = btm_to_wgs84(easting, northing)
    elif borehole.position == "project":
        lat, lon = grid.to_wgs84(borehole.x, borehole.y) if grid is not None else (None, None)
    if lat is not None and lon is not None and borehole.position != "btm":
        easting, northing = wgs84_to_btm(lat, lon)
    placed = grid is not None or borehole.position == "project"
    return {
        "id": borehole.id,
        "position": borehole.position,
        "x": _r(borehole.x, 1) if placed else None,
        "y": _r(borehole.y, 1) if placed else None,
        "lat": _r(lat, 8),
        "lon": _r(lon, 8),
        "btm": None
        if easting is None or northing is None
        else {"easting": round(easting, 3), "northing": round(northing, 3)},
    }


def locate(report: SoilReport, bim_text: str | None = None) -> dict[str, Any]:
    site = report.site or Site()
    grid = Grid(site) if site.georeferenced else None
    boreholes = [_borehole_location(b, grid) for b in report.boreholes]
    outline_xy, how = building_outline(bim_text)
    outline = None
    if outline_xy and grid is not None:
        outline = [[_r(lon, 8), _r(lat, 8)] for lat, lon in (grid.to_wgs84(*p) for p in outline_xy)]
        outline.append(list(outline[0]))
    # Without a site point, the boreholes given on the map still say where the site is.
    point = site.point
    if point is None:
        located = [(b["lat"], b["lon"]) for b in boreholes if b["lat"] is not None]
        if located:
            point = (
                sum(p[0] for p in located) / len(located),
                sum(p[1] for p in located) / len(located),
            )
    problems = []
    if grid is None:
        problems.append(
            "The site has no latitude/longitude: the project grid is not on the map, so the "
            "boreholes in project x/y and the building are not placed. Set the site point (the "
            "project point it is) and the grid's rotation."
        )
    btm = wgs84_to_btm(*point) if point is not None else None
    return {
        "site": None
        if point is None
        else {
            "lat": _r(point[0], 8),
            "lon": _r(point[1], 8),
            "x": site.x,
            "y": site.y,
            "rotation": site.rotation,
            "address": site.address,
            "georeferenced": grid is not None,
            "boundary": [list(p) for p in site.boundary],
            "btm": None
            if btm is None
            else {"easting": round(btm[0], 3), "northing": round(btm[1], 3)},
        },
        "boreholes": boreholes,
        "outline": outline,
        "outlineProject": [list(p) for p in outline_xy] if outline_xy else None,
        "outlineSource": how,
        "btmName": BTM_NAME,
        "problems": problems,
        "_point": point,
    }


def soil_location(
    soil_text: str | None, bim_text: str | None = None, settings_text: str | None = None
) -> dict[str, Any]:
    """The site on the map: ``{site, boreholes, outline, outlineProject, outlineSource,
    suggestion, problems}``, or ``{problems}`` when the soil report cannot be read.

    ``site``: ``{lat, lon, x, y, rotation, address, georeferenced, boundary [[lon, lat]],
    btm {easting, northing}}`` or null when nothing places the site (without a site point the
    mean of the boreholes given in lat/lon or BTM, ``georeferenced`` false); ``boreholes``:
    ``[{id, position, x, y, lat, lon, btm {easting, northing}}]`` (null where unknown);
    ``outline``: the building's outline as a closed [[lon, lat]] ring (null without a site
    point or a building); ``outlineProject`` the same in project mm (open ring);
    ``suggestion``: :func:`suggestion` or null.
    """
    report = _report(soil_text)
    if isinstance(report, list):
        return {"problems": report}
    out = locate(report, bim_text)
    point = out.pop("_point")
    out["suggestion"] = suggestion(point[0], point[1], settings_text) if point else None
    if point is not None:
        lat, lon = point
        if not (20.3 <= lat <= 26.8 and 88.0 <= lon <= 92.8):
            out["problems"].append(
                f"The site ({lat:.4f}, {lon:.4f}) is outside Bangladesh: the BNBC suggestion is "
                "of the nearest Bangladeshi town only."
            )
    return out


# ─────────────────────────────── export ───────────────────────────────


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _layers(project_root: str) -> tuple[list[gpkg.Layer], list[str]]:
    """The layers of the export: site, site_boundary, boreholes, building (WGS 84)."""
    from saengine.soil.report import soil_report

    root = Path(project_root)
    soil_text = _read(root / SOIL_FILE)
    report = _report(soil_text)
    if isinstance(report, list):
        return [], report
    bim_text = _read(root / BIM_FILE)
    location = locate(report, bim_text)
    problems = list(location["problems"])
    computed = soil_report(soil_text or "", _read(root / SETTINGS_FILE))
    by_id = {b["id"]: b for b in computed.get("boreholes", [])}
    site = location["site"]
    layers = []
    site_layer = gpkg.Layer(
        "site",
        "POINT",
        {
            "name": "TEXT",
            "address": "TEXT",
            "lat": "REAL",
            "lon": "REAL",
            "x_mm": "REAL",
            "y_mm": "REAL",
            "rotation": "REAL",
        },
        description="The site point (SAEngine soil report): the project point x_mm, y_mm, the "
        "grid turned rotation° clockwise from north",
    )
    if site is not None and site["georeferenced"]:
        site_layer.rows.append(
            (
                (site["lon"], site["lat"]),
                {
                    "name": report.report.title or "Site",
                    "address": site["address"],
                    "lat": site["lat"],
                    "lon": site["lon"],
                    "x_mm": site["x"],
                    "y_mm": site["y"],
                    "rotation": site["rotation"],
                },
            )
        )
    layers.append(site_layer)
    boundary = gpkg.Layer("site_boundary", "POLYGON", {"name": "TEXT"}, description="Site boundary")
    if site is not None and len(site["boundary"]) >= 3:
        boundary.rows.append(([tuple(p) for p in site["boundary"]], {"name": "Site boundary"}))
    layers.append(boundary)
    holes = gpkg.Layer(
        "boreholes",
        "POINT",
        {
            "id": "TEXT",
            "depth_m": "REAL",
            "ground_level_m": "REAL",
            "water_table_m": "REAL",
            "n_bar": "REAL",
            "site_class": "TEXT",
            "x_mm": "REAL",
            "y_mm": "REAL",
            "btm_e": "REAL",
            "btm_n": "REAL",
        },
        description="Boreholes: depth, ground level and water table [m], N̄ of the top 30 m "
        "(BNBC Table 6.2.13), site class",
    )
    unplaced = []
    for borehole, where in zip(report.boreholes, location["boreholes"], strict=True):
        if where["lat"] is None:
            unplaced.append(borehole.id)
            continue
        computed_bh = by_id.get(borehole.id, {})
        site_class = computed_bh.get("siteClass") or {}
        btm = where["btm"] or {}
        holes.rows.append(
            (
                (where["lon"], where["lat"]),
                {
                    "id": borehole.id,
                    "depth_m": round(borehole.bottom / 1e3, 3),
                    "ground_level_m": round(report.ground_level(borehole) / 1e3, 3),
                    "water_table_m": None
                    if borehole.waterTable is None
                    else round(borehole.waterTable / 1e3, 3),
                    "n_bar": site_class.get("N"),
                    "site_class": site_class.get("class"),
                    "x_mm": where["x"],
                    "y_mm": where["y"],
                    "btm_e": btm.get("easting"),
                    "btm_n": btm.get("northing"),
                },
            )
        )
    if unplaced:
        problems.append(f"Not on the map, left out: {', '.join(unplaced)}.")
    layers.append(holes)
    building = gpkg.Layer(
        "building", "POLYGON", {"name": "TEXT", "source": "TEXT"}, description="Building outline"
    )
    if location["outline"]:
        building.rows.append(
            (
                [tuple(p) for p in location["outline"]],
                {"name": "Building", "source": location["outlineSource"]},
            )
        )
    layers.append(building)
    return layers, problems


def to_geojson(layers: list[gpkg.Layer]) -> dict[str, Any]:
    features = []
    for layer in layers:
        for i, (geometry, attributes) in enumerate(layer.rows):
            shape = (
                geojson.point(*geometry)
                if layer.geometry_type == "POINT"
                else geojson.polygon(list(geometry))
            )
            fid = attributes.get("id") if layer.name == "boreholes" else f"{layer.name}-{i + 1}"
            properties = {"layer": layer.name, **{k: v for k, v in attributes.items()}}
            features.append(geojson.feature(shape, properties, fid))
    return geojson.collection(features)


def gis_export(project_root: str, format: str, out_path: str) -> dict[str, Any]:
    """Writes the site, boundary, boreholes and building outline to ``out_path`` as
    ``format`` "geojson" or "gpkg" (WGS 84): ``{"path", "counts", "problems"}`` (problems are
    warnings: what was left out), or ``{"problems"}`` when nothing could be written."""
    if format not in FORMATS:
        return {"problems": [f"Unknown format '{format}': geojson or gpkg"]}
    layers, problems = _layers(project_root)
    if not layers:
        return {"problems": problems}
    path = Path(out_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if format == "gpkg":
            gpkg.write(path, layers)
        else:
            path.write_text(geojson.dumps(to_geojson(layers)), encoding="utf-8")
    except (OSError, ValueError) as exc:
        return {"problems": [f"{path.name}: {exc}"]}
    return {
        "path": str(path),
        "counts": {layer.name: len(layer.rows) for layer in layers},
        "problems": problems,
    }


# ─────────────────────────────── import ───────────────────────────────


def _norm(name: str) -> str:
    return re.sub(r"[^0-9a-z]", "", str(name).lower())


def _attribute(properties: dict[str, Any], keys: tuple[str, ...]) -> tuple[Any, str] | None:
    normalized = {_norm(k): (v, _norm(k)) for k, v in properties.items() if v not in (None, "")}
    for key in keys:
        if key in normalized:
            return normalized[key]
    return None


def _length_mm(properties: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    found = _attribute(properties, keys)
    if found is None:
        return None
    value, key = found
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number if key.endswith("mm") else number * 1e3, 1)


def gis_import(path: str, soil_text: str | None = None) -> dict[str, Any]:
    """The soil report with the boreholes (points) and the site boundary (the first polygon not
    in a "building" layer) of a GeoJSON or GeoPackage file merged in.

    A point's id comes from its id/name attribute (else BH-<n>); its depth, ground level and
    water table from depth, ground level (gl, rl, elevation) and water table (gwt) attributes,
    in metres unless the name ends in "mm" (e.g. ``depth_mm``). A borehole whose id is already
    in the report gets the values it lacks (its log is kept); its position is kept as given
    when the point is within :data:`SAME_PLACE` of where it is now (so importing an export
    changes nothing), else it gets the new position. New and moved positions are stored as
    latitude/longitude (``position: "wgs84"``, a BTM pair dropped), placed in the project grid
    by the site point. A point of a "site" layer (as :func:`gis_export` writes) becomes the site point
    when the report has none, with its x_mm, y_mm and rotation attributes.

    Returns ``{"soilText", "added", "updated", "boundary", "notes", "problems"}`` (problems:
    features that were skipped), or ``{"problems"}`` when the file cannot be read.
    """
    from saengine.soil.report import dumps

    name = Path(path).name
    try:
        if Path(path).suffix.lower() == ".gpkg":
            shapes, problems = gpkg.read(path)
        else:
            shapes, problems = geojson.read(Path(path).read_text(encoding="utf-8"), name)
    except Exception as exc:  # noqa: BLE001 - unreadable files are reported to the user
        return {"problems": [f"{name}: {exc}"]}
    report = _report(soil_text)
    if isinstance(report, list):
        return {"problems": report}
    data = report.model_dump(mode="json", by_alias=True, exclude_none=True)
    holes = {b["id"]: b for b in data["boreholes"]}
    # Where the existing boreholes are on the map now, so a point at the same place (e.g. the
    # file SAEngine exported) leaves the borehole as it is given (project x/y, BTM).
    grid = Grid(report.site) if report.site is not None and report.site.georeferenced else None
    now = {b.id: _borehole_location(b, grid) for b in report.boreholes}
    added, updated, notes = [], [], []
    boundary = False
    site = data.setdefault("site", {})
    for shape in shapes:
        layer = _norm(shape.properties.get("_layer") or shape.properties.get("layer") or "")
        if shape.kind == "polygon":
            if "building" in layer:
                notes.append(f"{shape.where}: the building outline is not imported")
                continue
            if boundary:
                problems.append(f"{shape.where}: a second polygon; only the first is the boundary")
                continue
            ring = [[round(lon, 8), round(lat, 8)] for lat, lon in shape.coords]
            if len(ring) > 1 and ring[0] == ring[-1]:
                ring = ring[:-1]
            if len(ring) < 3:
                problems.append(f"{shape.where}: the polygon has fewer than three points")
                continue
            site["boundary"] = ring
            boundary = True
            continue
        if layer == "site":
            if site.get("lat") is None:
                site["lat"], site["lon"] = (round(v, 8) for v in shape.coords[0])
                for key, name in (("x", "xmm"), ("y", "ymm"), ("rotation", "rotation")):
                    found = _attribute(shape.properties, (name,))
                    if found is not None:
                        site[key] = float(found[0])
                notes.append(f"{shape.where}: the site point")
            continue
        found = _attribute(shape.properties, ID_KEYS)
        bh_id = str(found[0]).strip()[:64] if found else ""
        if not bh_id:
            # A point without an id is always a new borehole: the first unused BH-n, never an
            # existing borehole that would be moved by it.
            n = len(holes) + 1
            while f"BH-{n}" in holes:
                n += 1
            bh_id = f"BH-{n}"
            notes.append(f"{shape.where}: no id; added as {bh_id}")
        lat, lon = shape.coords[0]
        values = {
            "depth": _length_mm(shape.properties, DEPTH_KEYS),
            "groundLevel": _length_mm(shape.properties, GROUND_KEYS),
            "waterTable": _length_mm(shape.properties, WATER_KEYS),
        }
        hole = holes.get(bh_id)
        if hole is None:
            hole = {"id": bh_id}
            data["boreholes"].append(hole)
            holes[bh_id] = hole
            added.append(bh_id)
        elif bh_id in added or bh_id in updated:
            problems.append(f"{shape.where}: a second point for {bh_id} is skipped")
            continue
        else:
            updated.append(bh_id)
        where = now.get(bh_id)
        if (
            where is not None
            and where["lat"] is not None
            and where["lon"] is not None
            and (_metres(where["lat"], where["lon"], lat, lon) <= SAME_PLACE)
        ):
            notes.append(f"{shape.where}: {bh_id} is where it was; its position is kept")
        else:
            if where is not None and hole.get("position", "project") != "wgs84":
                notes.append(
                    f"{shape.where}: {bh_id} moved; its position is now given in latitude/longitude"
                )
            # The new position is the latitude/longitude; drop a BTM pair it would contradict.
            hole.pop("easting", None)
            hole.pop("northing", None)
            hole.update(position="wgs84", lat=round(lat, 8), lon=round(lon, 8))
        for key, value in values.items():
            if value is not None and hole.get(key) is None:
                hole[key] = value
    if not site:
        data.pop("site")
    try:
        merged = SoilReport.model_validate(data)
    except ValidationError as exc:
        from saengine.soil.report import messages

        return {"problems": messages(exc, data, name)}
    if (added or updated) and (merged.site is None or not merged.site.georeferenced):
        notes.append(
            "The site has no latitude/longitude: the imported boreholes are on the map but not "
            "yet in the project grid (x/y); set the site point and the grid's rotation."
        )
    if not (added or updated or boundary):
        problems.append(f"{name}: no points or polygons to import")
    return {
        "soilText": dumps(merged),
        "added": added,
        "updated": updated,
        "boundary": boundary,
        "notes": notes,
        "problems": problems,
    }


# ─────────────────────────────── QGIS ───────────────────────────────

#: QGIS launchers in an install's bin folder, the preferred first (the .exe reads its .env).
_LAUNCHERS = ("qgis-ltr-bin.exe", "qgis-bin.exe", "qgis.exe", "qgis-ltr.bat", "qgis.bat")


def _installs() -> list[Path]:
    """Folders that may hold a QGIS install: the uninstall registry entries named QGIS, the
    OSGeo4W roots and Program Files\\QGIS*."""
    found: list[Path] = []
    if os.name == "nt":
        import winreg

        for hive, view in (
            (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
            (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
            (winreg.HKEY_CURRENT_USER, 0),
        ):
            key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
            try:
                root = winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            with root:
                for i in range(winreg.QueryInfoKey(root)[0]):
                    try:
                        with winreg.OpenKey(root, winreg.EnumKey(root, i)) as key:
                            display = str(winreg.QueryValueEx(key, "DisplayName")[0])
                            if not display.upper().startswith("QGIS"):
                                continue
                            for value in ("InstallLocation", "DisplayIcon", "UninstallString"):
                                try:
                                    text = str(winreg.QueryValueEx(key, value)[0]).strip('"')
                                except OSError:
                                    continue
                                folder = Path(text.split(",")[0])
                                found.append(
                                    folder if value == "InstallLocation" else folder.parent
                                )
                    except OSError:
                        continue
        for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            base = os.environ.get(env)
            if base:
                found += sorted(Path(base).glob("QGIS*"), reverse=True)
        drive = os.environ.get("SystemDrive", "C:")
        found += [Path(drive + "\\") / "OSGeo4W", Path(drive + "\\") / "OSGeo4W64"]
    return found


def qgis_program() -> str | None:
    """The path of an installed QGIS launcher, or None."""
    seen = set()
    for folder in _installs():
        for base in (folder, folder.parent):
            if base in seen:
                continue
            seen.add(base)
            for launcher in _LAUNCHERS:
                for candidate in (base / "bin" / launcher, base / launcher):
                    if candidate.is_file():
                        return str(candidate)
    return None


#: Characters cmd.exe still interprets inside double quotes (``%VAR%`` expansion, the quote).
_CMD_UNSAFE = re.compile(r'["%\r\n\x00]')


def qgis_command(program: str, file_path: str) -> list[str]:
    """The program and arguments that open ``file_path`` in QGIS.

    An .exe launcher is ``[program, file_path]``, run without a shell. A .bat launcher
    (OSGeo4W) has to run through cmd.exe, which re-parses its command line: the last argument
    is then the whole quoted line ``""program" "file""`` and must be passed VERBATIM (Node:
    ``spawn(args[0], args.slice(1), {windowsVerbatimArguments: true})``; Python:
    :func:`qgis_command_line`). Inside those quotes ``&``, ``|``, ``<``, ``>``, ``(``, ``)``
    and ``^`` are plain characters, and delayed expansion (``!``) is off (``/v:off``); a path
    with a double quote or a percent sign, which cmd would still interpret, is refused
    (ValueError), so a file name cannot run a command.
    """
    if not program.lower().endswith((".bat", ".cmd")):
        return [program, file_path]
    for text in (program, file_path):
        if _CMD_UNSAFE.search(text):
            raise ValueError(
                f"{Path(text).name}: a QGIS .bat launcher cannot open a path with a double quote "
                "or a percent sign; rename the file"
            )
    return ["cmd.exe", "/d", "/v:off", "/s", "/c", f'""{program}" "{file_path}""']


def qgis_command_line(program: str, file_path: str) -> str:
    """:func:`qgis_command` as one Windows command line (for ``subprocess`` or CreateProcess):
    the .exe case quoted by the usual rules, the .bat case with cmd's line verbatim."""
    import subprocess

    args = qgis_command(program, file_path)
    if args[0] == "cmd.exe":
        return subprocess.list2cmdline(args[:-1]) + " " + args[-1]
    return subprocess.list2cmdline(args)

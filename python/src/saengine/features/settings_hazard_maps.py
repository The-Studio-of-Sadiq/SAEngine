"""Project Settings - Hazard Maps & GIS Lookup tab: providers, coordinates, contours, site amplification, faults."""

from __future__ import annotations

import json
import math
from typing import Any

from saengine.codes import context as code_context
from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.settings_common import (
    active_pack,
    effective_site_class,
    load_settings,
    project_derived,
    safe_table,
)
from saengine.gis import hazard_lookup
from saengine.gis import towns as gis_towns
from saengine.gis.crs import haversine_km
from saengine.report.clauses import in_force


@feature(
    "settingsHazardMaps.mapSource", "Map Source", part="settings", fields=[], requires_project=False
)
def map_source(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List online hazard lookup providers and local town tables available in the active code pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        provs = hazard_lookup.providers(pack)
        towns = gis_towns.towns()
    rows = [{"kind": "Online provider", "name": p.service, "details": p.endpoint} for p in provs]
    if towns:
        rows.append(
            {
                "kind": "Code pack town table",
                "name": f"{pack.id} locations.towns",
                "details": f"{len(towns)} mapped stations",
            }
        )
    return result(
        summary={"providerCount": len(provs), "mappedTownCount": len(towns), "packId": pack.id},
        tables=[
            table(
                "Available hazard data sources",
                [("kind", "Source type"), ("name", "Name"), ("details", "Coverage / endpoint")],
                rows or [{"kind": "Manual", "name": "User input", "details": "Custom Z / SS / S1"}],
            )
        ],
        notes=["Online providers are only queried on explicit user consent via gis.hazard_lookup."],
    )


@feature(
    "settingsHazardMaps.importMap",
    "Import Map",
    part="settings",
    fields=[
        text(
            "geojsonText",
            "Hazard zone GeoJSON FeatureCollection",
            '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"zone":2,"Z":0.20},"geometry":{"type":"Point","coordinates":[90.41,23.81]}}]}',
        ),
    ],
    requires_project=False,
)
def import_map(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate a GeoJSON hazard map file for site coordinate overlay."""
    try:
        gj = json.loads(values["geojsonText"])
    except ValueError as exc:
        raise FeatureInputError(f"Invalid GeoJSON: {exc}") from exc
    feats = gj.get("features") if isinstance(gj, dict) else None
    if not isinstance(feats, list):
        raise FeatureInputError("GeoJSON must contain a 'features' list.")
    rows = [
        {
            "index": i + 1,
            "geomType": (f.get("geometry") or {}).get("type", "-"),
            "properties": str(f.get("properties") or {})[:60],
        }
        for i, f in enumerate(feats)
        if isinstance(f, dict)
    ]
    return result(
        summary={"featureCount": len(rows)},
        tables=[
            table(
                "Imported GeoJSON features",
                [("index", "#"), ("geomType", "Geometry"), ("properties", "Attributes")],
                rows,
            )
        ],
        notes=["Validated GeoJSON geometry and hazard property attributes."],
    )


@feature(
    "settingsHazardMaps.regionSelect",
    "Region Select",
    part="settings",
    fields=[],
    requires_project=False,
)
def region_select(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List locations / hazard regions defined in the active code pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        locs = safe_table(pack, "locations")
        loc_map = getattr(locs, "locations", None) or {}
    rows = [
        {
            "id": k,
            "name": v.name,
            "zone": v.zone,
            "windMPerS": v.windSpeed,
            "selected": k == st.site.location,
        }
        for k, v in list(loc_map.items())[:25]
    ]
    return result(
        summary={"locationCount": len(loc_map), "selectedLocation": st.site.location},
        tables=[
            table(
                "Code pack hazard regions",
                [
                    ("id", "ID"),
                    ("name", "Region"),
                    ("zone", "Zone"),
                    ("windMPerS", "V", "m/s"),
                    ("selected", "Active"),
                ],
                rows
                or [
                    {
                        "id": "custom",
                        "name": "Custom",
                        "zone": 0,
                        "windMPerS": 0.0,
                        "selected": True,
                    }
                ],
            )
        ],
        notes=[f"Locations read from {code_context.code_name(pack)} locations table."],
    )


@feature(
    "settingsHazardMaps.mapVersion",
    "Map Version",
    part="settings",
    fields=[],
    requires_project=False,
)
def map_version(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report hazard map source metadata, pack version, and any online lookup provenance."""
    st = load_settings(ctx)
    pack = active_pack(ctx, st)
    hs = st.site.hazardSource
    rows = [
        {"field": "Code pack", "value": f"{pack.id} v{pack.info.version}"},
        {"field": "Pack verified date", "value": str(pack.info.verified or "-")},
        {
            "field": "Online lookup service",
            "value": hs.service if hs else "None (code pack / manual)",
        },
        {"field": "Lookup date", "value": hs.date if hs and hs.date else "-"},
    ]
    return result(
        summary={
            "packId": pack.id,
            "packVersion": pack.info.version,
            "hasOnlineProvenance": hs is not None,
        },
        tables=[table("Hazard map provenance", [("field", "Field"), ("value", "Value")], rows)],
        notes=[
            "Provenance tracks whether site hazard values came from code pack tables or online lookup."
        ],
    )


@feature(
    "settingsHazardMaps.contourValue",
    "Contour Value",
    part="settings",
    fields=[
        number("latitudeDeg", "Site latitude", 23.81, unit="°", min=-90.0, max=90.0),
        number("longitudeDeg", "Site longitude", 90.41, unit="°", min=-180.0, max=180.0),
    ],
    requires_project=False,
)
def contour_value(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Read seismic Z and basic wind speed V from the nearest mapped station in the active pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        towns = gis_towns.towns()
        if towns:
            near, dist = gis_towns.nearest(values["latitudeDeg"], values["longitudeDeg"])
            name, z_val, v_val = near.name, near.z or 0.0, near.wind_speed or 0.0
        else:
            d = project_derived(ctx, st)
            name, dist, z_val, v_val = st.site.location, 0.0, 0.0, float(d.get("windSpeed") or 0.0)
    return result(
        summary={"nearestStation": name, "distanceKm": dist, "zValue": z_val, "windMPerS": v_val},
        tables=[
            table(
                "Nearest hazard contour reading",
                [
                    ("station", "Station"),
                    ("distKm", "Distance", "km"),
                    ("z", "Z"),
                    ("v", "Wind", "m/s"),
                ],
                [{"station": name, "distKm": dist, "z": z_val, "v": v_val}],
            )
        ],
        notes=["Nearest-station lookup against active pack town coordinates."],
    )


@feature(
    "settingsHazardMaps.interpolateValue",
    "Interpolate Value",
    part="settings",
    fields=[
        number("latitudeDeg", "Target latitude", 23.90, unit="°", min=-90.0, max=90.0),
        number("longitudeDeg", "Target longitude", 90.40, unit="°", min=-180.0, max=180.0),
        number("kNearest", "Number of stations for IDW", 3.0, min=1.0, max=8.0),
    ],
    requires_project=False,
)
def interpolate_value(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Interpolate wind speed and seismic zone coefficient via inverse-distance weighting (IDW)."""
    st = load_settings(ctx)
    k = int(values["kNearest"])
    with in_force(ctx.root, st):
        towns = [t for t in gis_towns.towns() if t.wind_speed is not None]
    if not towns:
        d = project_derived(ctx, st)
        v_est = float(d.get("windSpeed") or 50.0)
        return result(
            summary={"interpolatedWindMPerS": v_est, "stationsUsed": 0},
            tables=[
                table(
                    "IDW interpolation",
                    [("station", "Station"), ("weight", "Weight"), ("windMPerS", "V", "m/s")],
                    [{"station": st.site.location, "weight": 1.0, "windMPerS": v_est}],
                )
            ],
            notes=["Pack has no geolocated towns; fell back to project derived wind speed."],
        )
    ranked = sorted(
        (
            (
                t,
                max(
                    0.5,
                    haversine_km(
                        values["latitudeDeg"], values["longitudeDeg"], t.latitude, t.longitude
                    ),
                ),
            )
            for t in towns
        ),
        key=lambda p: p[1],
    )[:k]
    weights = [1.0 / (d**2) for _, d in ranked]
    w_sum = sum(weights)
    v_idw = sum(w * float(t.wind_speed) for (t, _), w in zip(ranked, weights)) / w_sum
    rows = [
        {"station": t.name, "distanceKm": d, "weight": w / w_sum, "windMPerS": t.wind_speed}
        for (t, d), w in zip(ranked, weights)
    ]
    return result(
        summary={"interpolatedWindMPerS": v_idw, "stationsUsed": len(rows)},
        tables=[
            table(
                "IDW station interpolation",
                [
                    ("station", "Station"),
                    ("distanceKm", "Dist", "km"),
                    ("weight", "Weight"),
                    ("windMPerS", "V", "m/s"),
                ],
                rows,
            )
        ],
        notes=["Inverse-distance squared weighting (1/d²) across k nearest stations."],
    )


@feature(
    "settingsHazardMaps.siteClass", "Site Class", part="settings", fields=[], requires_project=False
)
def hm_site_class(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List seismic site classes and spectral site factors from the active code pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        seis = safe_table(pack, "seismic")
        scs = getattr(seis, "siteClasses", None) or {}
    rows = [
        {
            "siteClass": k,
            "description": v.description,
            "S": getattr(v, "S", 1.0),
            "TB": getattr(v, "TB", 0.0),
            "TC": getattr(v, "TC", 0.0),
            "TD": getattr(v, "TD", 0.0),
        }
        for k, v in scs.items()
    ]
    return result(
        summary={"siteClassCount": len(rows), "selectedClass": st.site.siteClass},
        tables=[
            table(
                "Code pack site classes",
                [
                    ("siteClass", "Class"),
                    ("description", "Description"),
                    ("S", "S"),
                    ("TB", "TB", "s"),
                    ("TC", "TC", "s"),
                    ("TD", "TD", "s"),
                ],
                rows,
            )
        ],
        notes=["Read from active code pack seismic.siteClasses."],
    )


@feature(
    "settingsHazardMaps.mapPreview",
    "Map Preview",
    part="settings",
    fields=[
        number("latitudeDeg", "Center latitude", 23.81, unit="°", min=-90.0, max=90.0),
        number("longitudeDeg", "Center longitude", 90.41, unit="°", min=-180.0, max=180.0),
        number("radiusKm", "Search radius", 120.0, unit="km", min=10.0),
    ],
    requires_project=False,
)
def map_preview(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate spatial hazard station table within search radius around site coordinates."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        towns = gis_towns.towns()
    nearby = []
    for t in towns:
        d = haversine_km(values["latitudeDeg"], values["longitudeDeg"], t.latitude, t.longitude)
        if d <= values["radiusKm"]:
            nearby.append(
                {
                    "station": t.name,
                    "lat": t.latitude,
                    "lon": t.longitude,
                    "distanceKm": d,
                    "z": t.z or 0.0,
                    "windMPerS": t.wind_speed or 0.0,
                }
            )
    nearby.sort(key=lambda r: r["distanceKm"])
    return result(
        summary={"stationsWithinRadius": len(nearby), "radiusKm": values["radiusKm"]},
        tables=[
            table(
                "Stations within map preview radius",
                [
                    ("station", "Station"),
                    ("lat", "Lat"),
                    ("lon", "Lon"),
                    ("distanceKm", "Dist", "km"),
                    ("z", "Z"),
                    ("windMPerS", "V", "m/s"),
                ],
                nearby[:15]
                or [
                    {
                        "station": "-",
                        "lat": values["latitudeDeg"],
                        "lon": values["longitudeDeg"],
                        "distanceKm": 0.0,
                        "z": 0.0,
                        "windMPerS": 0.0,
                    }
                ],
            )
        ],
        notes=["Provides station coordinates and hazard values for map rendering."],
    )


@feature(
    "settingsHazardMaps.assignSiteClass",
    "Assign Site Class",
    part="settings",
    fields=[],
    requires_project=False,
)
def assign_site_class(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Resolve and assign effective soil site class from borehole logs or project settings."""
    st = load_settings(ctx)
    _, info = effective_site_class(ctx, st)
    return result(
        summary={"assignedClass": str(info["class"]), "source": str(info["source"])},
        tables=[
            table(
                "Site class assignment",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Assigned site class", "value": str(info["class"])},
                    {"property": "Source", "value": str(info["label"])},
                ],
            )
        ],
        notes=[str(info.get("note") or "")],
    )


@feature(
    "settingsHazardMaps.amplificationFactor",
    "Amplification Factor",
    part="settings",
    fields=[],
    requires_project=False,
)
def amplification_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report short-period and soil amplification factors for the active site class."""
    st = load_settings(ctx)
    _, info = effective_site_class(ctx, st)
    sc = info["class"]
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        seis = safe_table(pack, "seismic")
        row = (getattr(seis, "siteClasses", None) or {}).get(sc)
        s_fac = float(getattr(row, "S", 1.0) or 1.0)
    return result(
        summary={"siteClass": sc, "soilFactorS": s_fac},
        tables=[
            table(
                "Site amplification parameters",
                [
                    ("siteClass", "Class"),
                    ("sFactor", "Soil factor S"),
                    ("tb", "TB", "s"),
                    ("tc", "TC", "s"),
                ],
                [
                    {
                        "siteClass": sc,
                        "sFactor": s_fac,
                        "tb": getattr(row, "TB", 0.0) if row else 0.0,
                        "tc": getattr(row, "TC", 0.0) if row else 0.0,
                    }
                ],
            )
        ],
        notes=["Retrieved from active code pack seismic.siteClasses."],
    )


@feature(
    "settingsHazardMaps.soilFactor",
    "Soil Factor",
    part="settings",
    fields=[
        number("vs30MPerS", "Measured Vs30", 240.0, unit="m/s", min=80.0, max=1500.0),
    ],
    requires_project=False,
)
def soil_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate empirical site amplification factor S from Vs30 relative to reference rock (760 m/s)."""
    vs = values["vs30MPerS"]
    s_short = (760.0 / vs) ** 0.25
    s_mid = (760.0 / vs) ** 0.40
    return result(
        summary={"vs30MPerS": vs, "shortPeriodFactor": s_short, "oneSecFactor": s_mid},
        tables=[
            table(
                "Vs30 empirical site factors",
                [("band", "Period band"), ("factor", "Amplification")],
                [
                    {"band": "Short period (Fa)", "factor": s_short},
                    {"band": "1-second (Fv)", "factor": s_mid},
                ],
            )
        ],
        notes=["Power-law Vs30 scaling relative to 760 m/s B/C boundary rock."],
    )


@feature(
    "settingsHazardMaps.applyHazard",
    "Apply Hazard",
    part="settings",
    fields=[],
    requires_project=False,
)
def apply_hazard(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute complete derived site seismic and wind hazard values from active settings."""
    st = load_settings(ctx)
    d = project_derived(ctx, st)
    rows = [
        {"parameter": "Location", "value": st.site.location},
        {"parameter": "Zone", "value": str(d.get("zone") or "-")},
        {"parameter": "Z / spectral", "value": str(d.get("Z") or "-")},
        {"parameter": "Basic wind speed [m/s]", "value": str(d.get("windSpeed") or "-")},
        {"parameter": "Seismic importance I", "value": str(d.get("seismicImportance"))},
        {"parameter": "Wind importance I", "value": str(d.get("windImportance"))},
    ]
    return result(
        summary={
            "location": st.site.location,
            "windSpeedMPerS": float(d.get("windSpeed") or 0.0),
            "seismicImportance": float(d.get("seismicImportance") or 1.0),
        },
        tables=[
            table(
                "Applied project hazard values",
                [("parameter", "Parameter"), ("value", "Derived value")],
                rows,
            )
        ],
        notes=["Derived using saengine.library.settings.derived under active code pack."],
    )


@feature(
    "settingsHazardMaps.latitudeLongitude",
    "Latitude Longitude",
    part="settings",
    fields=[
        number("latitudeDeg", "Latitude (WGS 84)", 23.8103, unit="°", min=-90.0, max=90.0),
        number("longitudeDeg", "Longitude (WGS 84)", 90.4125, unit="°", min=-180.0, max=180.0),
    ],
    requires_project=False,
)
def latitude_longitude(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert decimal WGS-84 latitude/longitude to DMS and UTM zone."""
    lat, lon = values["latitudeDeg"], values["longitudeDeg"]
    utm_zone = int((lon + 180.0) / 6.0) + 1
    hemi = "N" if lat >= 0 else "S"
    return result(
        summary={"latitudeDeg": lat, "longitudeDeg": lon, "utmZone": f"{utm_zone}{hemi}"},
        tables=[
            table(
                "Geographic coordinate summary",
                [("format", "Format"), ("value", "Value")],
                [
                    {"format": "WGS 84 Decimal", "value": f"{lat:.5f}, {lon:.5f}"},
                    {"format": "UTM Zone", "value": f"{utm_zone}{hemi}"},
                ],
            )
        ],
        notes=["WGS-84 coordinates are used by online hazard lookup and nearest-town matching."],
    )


@feature(
    "settingsHazardMaps.gisIntegration",
    "GIS Integration",
    part="settings",
    fields=[],
    requires_project=False,
)
def gis_integration(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build exact offline query URL preview for active pack hazard providers (without network calls)."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        provs = hazard_lookup.providers(pack)
        coords = hazard_lookup.coordinates(root=ctx.root) or (23.8103, 90.4125)
    rows = []
    for p in provs:
        try:
            url, _ = hazard_lookup.build_query(
                p,
                coords[0],
                coords[1],
                {"riskCategory": st.occupancy.category, "siteClass": st.site.siteClass},
            )
        except hazard_lookup.LookupError_ as err:
            url = str(err)
        rows.append({"service": p.service, "preview": url[:90]})
    return result(
        summary={"providerCount": len(provs), "latitude": coords[0], "longitude": coords[1]},
        tables=[
            table(
                "GIS hazard service query preview",
                [("service", "Service"), ("preview", "Query / status")],
                rows
                or [
                    {
                        "service": "None",
                        "preview": "Active code pack defines no online GIS providers",
                    }
                ],
            )
        ],
        notes=["Preview only; no network request is sent."],
    )


@feature(
    "settingsHazardMaps.gridOverlay",
    "Grid Overlay",
    part="settings",
    fields=[
        number("centerLat", "Center latitude", 23.81, unit="°"),
        number("centerLon", "Center longitude", 90.41, unit="°"),
        number("stepDeg", "Grid cell step", 0.05, unit="°", min=0.005, max=1.0),
    ],
    requires_project=False,
)
def grid_overlay(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a 3×3 spatial hazard sampling grid around the site coordinates."""
    rows = []
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            rows.append(
                {
                    "lat": values["centerLat"] + di * values["stepDeg"],
                    "lon": values["centerLon"] + dj * values["stepDeg"],
                }
            )
    return result(
        summary={"gridPoints": len(rows), "stepDeg": values["stepDeg"]},
        tables=[
            table(
                "Hazard sampling grid", [("lat", "Latitude", "°"), ("lon", "Longitude", "°")], rows
            )
        ],
        notes=["1° latitude ≈ 111.1 km."],
    )


@feature(
    "settingsHazardMaps.coordinateSystem",
    "Coordinate System",
    part="settings",
    fields=[],
    requires_project=False,
)
def coordinate_system(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect active project CRS setting for GIS and IFC georeferencing."""
    st = load_settings(ctx)
    return result(
        summary={"crs": st.ifc.crs, "includeGeoreferencing": st.ifc.includeGeoreferencing},
        tables=[
            table(
                "Coordinate reference system",
                [("setting", "Setting"), ("value", "Value")],
                [
                    {"setting": "Project CRS", "value": st.ifc.crs},
                    {"setting": "IFC georeferencing", "value": str(st.ifc.includeGeoreferencing)},
                ],
            )
        ],
        notes=["Configured in ifc.crs (e.g., BTM, UTM, or EPSG:<code>)."],
    )


@feature(
    "settingsHazardMaps.activeFaults",
    "Active Faults",
    part="settings",
    fields=[
        number("siteLat", "Site latitude", 23.81, unit="°"),
        number("siteLon", "Site longitude", 90.41, unit="°"),
        number("faultLat", "Nearest fault trace latitude", 24.45, unit="°"),
        number("faultLon", "Nearest fault trace longitude", 90.78, unit="°"),
    ],
    requires_project=False,
)
def active_faults(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute great-circle distance from site coordinates to mapped active fault trace."""
    dist_km = haversine_km(
        values["siteLat"], values["siteLon"], values["faultLat"], values["faultLon"]
    )
    return result(
        summary={"distanceToFaultKm": dist_km, "withinNearField15Km": dist_km <= 15.0},
        tables=[
            table(
                "Fault proximity check",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Distance to fault [km]", "value": dist_km},
                    {"item": "Near-fault (< 15 km)", "value": str(dist_km <= 15.0)},
                ],
            )
        ],
        notes=["Computed via WGS-84 Haversine distance."],
    )


@feature(
    "settingsHazardMaps.ruptureMechanism",
    "Rupture Mechanism",
    part="settings",
    fields=[
        select(
            "style",
            "Fault slip mechanism",
            [
                ("strikeSlip", "Strike-slip (1.00)"),
                ("reverse", "Reverse / thrust (1.15)"),
                ("normal", "Normal / extensional (0.95)"),
            ],
            "reverse",
        ),
    ],
    requires_project=False,
)
def rupture_mechanism(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report hanging-wall / style-of-faulting ground motion scaling factor."""
    fac = {"strikeSlip": 1.0, "reverse": 1.15, "normal": 0.95}[values["style"]]
    return result(
        summary={"mechanism": values["style"], "styleFactor": fac},
        tables=[
            table(
                "Fault mechanism factor",
                [("mechanism", "Style"), ("factor", "Scaling factor")],
                [{"mechanism": values["style"], "factor": fac}],
            )
        ],
        notes=[
            "Reverse thrust faults typically generate ~15% higher near-field short-period shaking."
        ],
    )


@feature(
    "settingsHazardMaps.attenuationModel",
    "Attenuation Model",
    part="settings",
    fields=[
        number("magnitudeMw", "Earthquake magnitude Mw", 7.0, min=4.5, max=9.0),
        number("distanceKm", "Rupture distance Rrup", 30.0, unit="km", min=1.0),
    ],
    requires_project=False,
)
def attenuation_model(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate empirical GMPE spectral decay across 0.2 s and 1.0 s periods."""
    r_eff = math.sqrt(values["distanceKm"] ** 2 + 8.0**2)
    sa_02 = math.exp(-1.5 + 0.85 * values["magnitudeMw"] - 1.30 * math.log(r_eff))
    sa_10 = math.exp(-2.8 + 1.00 * values["magnitudeMw"] - 1.15 * math.log(r_eff))
    return result(
        summary={"sa02G": sa_02, "sa10G": sa_10},
        tables=[
            table(
                "GMPE spectral attenuation",
                [("period", "Period"), ("saG", "Median rock Sa", "g")],
                [
                    {"period": "0.2 s (short)", "saG": sa_02},
                    {"period": "1.0 s (long)", "saG": sa_10},
                ],
            )
        ],
        notes=["Parametric attenuation preview; site-specific PSHA governs critical facilities."],
    )


@feature(
    "settingsHazardMaps.siteAmplification",
    "Site Amplification",
    part="settings",
    fields=[
        number("softLayerDepthM", "Soft soil thickness H", 20.0, unit="m", min=1.0),
        number("shearWaveVsMPerS", "Average shear-wave velocity Vs", 180.0, unit="m/s", min=60.0),
    ],
    requires_project=False,
)
def site_amplification(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute fundamental soil deposit period T_site = 4H / Vs for resonance screening."""
    t_site = (4.0 * values["softLayerDepthM"]) / values["shearWaveVsMPerS"]
    return result(
        summary={"sitePeriodS": t_site, "siteFrequencyHz": 1.0 / t_site},
        tables=[
            table(
                "Soil column fundamental period",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Site period T = 4H/Vs [s]", "value": t_site},
                    {"metric": "Site frequency [Hz]", "value": 1.0 / t_site},
                ],
            )
        ],
        notes=["Check for double-resonance when building fundamental period matches soil T_site."],
    )


@feature(
    "settingsHazardMaps.liquefactionZone",
    "Liquefaction Zone",
    part="settings",
    fields=[],
    requires_project=False,
)
def liquefaction_zone(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Screen project boreholes for liquefaction susceptibility flags under active site hazard."""
    st = load_settings(ctx)
    _, info = effective_site_class(ctx, st)
    soil = info.get("soil") or {}
    flags = list(soil.get("flags") or [])
    return result(
        summary={
            "boreholes": int(soil.get("boreholes", 0)),
            "flaggedClasses": ", ".join(flags) or "none",
            "requiresDetailedStudy": bool(flags),
        },
        tables=[
            table(
                "Liquefaction & soft-soil flags",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Boreholes screened", "value": str(soil.get("boreholes", 0))},
                    {"item": "Flagged classes", "value": ", ".join(flags) or "None"},
                ],
            )
        ],
        notes=["Screens 1 Soil Report boreholes using site Z and water table depth."],
    )


@feature(
    "settingsHazardMaps.landslideArea",
    "Landslide Area",
    part="settings",
    fields=[
        number("hillSlopeDeg", "Natural hill slope angle β", 22.0, unit="°", min=0.0, max=60.0),
        number("pgaG", "Design PGA", 0.25, unit="g", min=0.0, max=1.5),
    ],
    requires_project=False,
)
def landslide_area(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Screen slope seismic landslide susceptibility using pseudo-static kh = 0.5 PGA."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        ss = safe_table(pack, "slopeStability")
        kh_fac = float(getattr(getattr(ss, "seismic", None), "khFactor", 0.5) or 0.5)
    kh = kh_fac * values["pgaG"]
    # Screening critical friction angle for infinite dry slope under kh: tan(phi_req) ~ tan(beta + atan(kh))
    phi_req = values["hillSlopeDeg"] + math.degrees(math.atan(kh))
    return result(
        summary={
            "kh": kh,
            "requiredFrictionDeg": phi_req,
            "elevatedRisk": values["hillSlopeDeg"] >= 15.0 and kh >= 0.1,
        },
        tables=[
            table(
                "Seismic slope susceptibility",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Pseudo-static kh", "value": kh},
                    {"metric": "Required dry friction φ' [°]", "value": phi_req},
                ],
            )
        ],
        notes=["Uses active pack slopeStability.seismic.khFactor for pseudo-static screening."],
    )


@feature(
    "settingsHazardMaps.hazardOverlay",
    "Hazard Overlay",
    part="settings",
    fields=[],
    requires_project=False,
)
def hazard_overlay(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Combine seismic, wind, flood, snow, and soil flags into a multi-hazard site overlay."""
    st = load_settings(ctx)
    d = project_derived(ctx, st)
    _, info = effective_site_class(ctx, st)
    rows = [
        {"hazard": "Seismic", "status": f"Zone {d.get('zone', '-')}, Class {info['class']}"},
        {
            "hazard": "Wind",
            "status": f"V = {d.get('windSpeed', '-')} m/s, Exposure {st.wind.exposure}",
        },
        {"hazard": "Flood / Surge", "status": st.site.flood.zone},
        {"hazard": "Snow", "status": f"{st.site.snow.groundLoad or 0.0} kN/m²"},
    ]
    return result(
        summary={
            "location": st.site.location,
            "siteClass": info["class"],
            "floodZone": st.site.flood.zone,
        },
        tables=[
            table(
                "Multi-hazard site overlay",
                [("hazard", "Hazard"), ("status", "Active site state")],
                rows,
            )
        ],
        notes=["Unified site hazard profile driving load derivations."],
    )

"""The site on the map: coordinates, the code pack's location suggestion and the QGIS
exchange.

- :mod:`saengine.gis.crs`: WGS 84 (EPSG:4326), Bangladesh Transverse Mercator (EPSG:9678) and
  the project grid (mm) through the site's georeference, with pyproj (PROJ);
- :mod:`saengine.gis.towns`: the towns of the code pack's zone and wind tables with their
  coordinates, and the nearest one to the site;
- :mod:`saengine.gis.geojson`: GeoJSON (RFC 7946) writing and reading;
- :mod:`saengine.gis.gpkg`: OGC GeoPackage writing and reading with Python's sqlite3;
- :mod:`saengine.gis.site`: the JSON-ready API the workbench calls (``soil_location``,
  ``gis_export``, ``gis_import``, ``qgis_program``).

QGIS is not bundled: the files open in it, and an installed QGIS is found for "Open in QGIS".

The package imports nothing on its own (the soil report's model loads :mod:`saengine.gis.crs`
while it validates); the API is in :mod:`saengine.gis.site`.
"""

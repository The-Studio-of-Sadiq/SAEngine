"""Topography of the site: a terrain surface (TIN) from survey data and the cut and fill of the
building platform (alpha 9 L11).

``01 Soil Report/terrain.json`` (:class:`Terrain`) keeps the terrain as a triangulated irregular
network in the project grid (mm, x/y/z), made from:

- a DEM as GeoTIFF (:func:`read_geotiff`; read with Pillow, its GeoTIFF tags give the pixel size,
  the tie point and the EPSG code; a single band of elevations);
- survey points as XYZ text (:func:`read_xyz`: "x y z" per line, comma, semicolon or space
  separated);
- contours or survey points in a DXF (:func:`read_dxf`: points, lines, polylines at their
  elevation, 3D polylines and 3D faces; ezdxf).

Coordinates come in the project grid (in m or mm) or in an EPSG coordinate system, which the site
point of 01 Soil Report places in the project grid (:class:`saengine.gis.crs.Grid`). Elevations
become project z by the datum: the survey elevation of project z = 0 (by default the one that puts
the mean existing ground inside the platform at the platform level, said in the notes).

The points are thinned on a grid to at most ``MAX_POINTS`` and triangulated in plan (Delaunay,
scipy). :func:`cut_fill` integrates the existing ground less the platform level over the platform
(the building outline, the plot, or a polygon given, grown by a margin) exactly for the planar
triangles: every triangle is split at the platform level and clipped to the platform, and the
volume of a plane over a polygon is its area times the height at its centroid. The cut and fill
go to the bill's earthwork (:func:`bill_items`, ``origin: "terrain"``). The side slopes of the
platform and the bulking of the cut are not measured.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

SCHEMA = "saengine.terrain/1"
TERRAIN_FILE = "01 Soil Report/terrain.json"
SOIL_FILE = "01 Soil Report/soil-report.json"
#: At most this many survey points are triangulated (thinned on a grid beyond).
MAX_POINTS = 20_000
#: Code letter of the bill items from the terrain, after the group's letter ("E.T01").
CODE_LETTER = "T"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TerrainSource(_Model):
    file: str = ""
    format: Literal["geotiff", "xyz", "dxf", "points"] = "points"
    units: Literal["m", "mm", "ft"] = "m"
    crs: str = Field(
        default="project", description='"project" (the project grid) or "EPSG:<code>".'
    )
    datum: float | None = Field(
        default=None, description="Survey elevation of project z = 0, in the source's units."
    )
    pointsRead: int = 0


class Platform(_Model):
    """The building platform the site is cut and filled to."""

    level: float | None = Field(
        default=None, description="Platform level [mm, project z]; empty: the ground level."
    )
    outline: Literal["building", "plot", "custom"] = "building"
    points: list[list[float]] = Field(default_factory=list, description="Custom outline [mm].")
    margin: float = Field(default=0, ge=0, description="Grown by this all round [mm].")


class Terrain(_Model):
    schema_: Literal["saengine.terrain/1"] = Field(default=SCHEMA, alias="schema")
    source: TerrainSource = Field(default_factory=TerrainSource)
    points: list[list[float]] = Field(default_factory=list, description="[x, y, z] project mm.")
    triangles: list[list[int]] = Field(default_factory=list)
    platform: Platform = Field(default_factory=Platform)
    #: Results of the last cut and fill (m³, m²), for the bill and the editor.
    cut: float | None = None
    fill: float | None = None
    platformArea: float | None = None
    notes: list[str] = Field(default_factory=list)


def parse(text: str | None) -> Terrain:
    if not text or not text.strip():
        return Terrain()
    return Terrain.model_validate_json(text)


UNIT_MM = {"m": 1000.0, "mm": 1.0, "ft": 304.8}


# ─────────────────────────────────── reading ───────────────────────────────────


class TerrainError(ValueError):
    """The survey file could not be read; the message says why."""


_SPLIT = re.compile(r"[\s,;]+")


def read_xyz(text: str) -> np.ndarray:
    """Points of an XYZ text: three numbers per line (extra columns ignored); lines that do not
    start with three numbers (headers, comments) are skipped."""
    rows = []
    for line in text.splitlines():
        parts = [p for p in _SPLIT.split(line.strip()) if p]
        if len(parts) < 3:
            continue
        try:
            rows.append((float(parts[0]), float(parts[1]), float(parts[2])))
        except ValueError:
            continue
    if not rows:
        raise TerrainError("no 'x y z' lines in the file")
    return np.asarray(rows, dtype=float)


def read_dxf(path: str | Path) -> np.ndarray:
    """Points of a DXF survey: POINT, LINE, LWPOLYLINE (at its elevation), POLYLINE (2D at its
    elevation, 3D at its vertices) and 3DFACE; a contour at elevation 0 still counts."""
    import ezdxf

    try:
        doc = ezdxf.readfile(str(path))
    except (OSError, ezdxf.DXFError) as error:
        raise TerrainError(f"the DXF could not be read: {error}") from error
    rows: list[tuple[float, float, float]] = []
    for e in doc.modelspace():
        kind = e.dxftype()
        if kind == "POINT":
            p = e.dxf.location
            rows.append((p.x, p.y, p.z))
        elif kind == "LINE":
            rows += [(e.dxf.start.x, e.dxf.start.y, e.dxf.start.z)]
            rows += [(e.dxf.end.x, e.dxf.end.y, e.dxf.end.z)]
        elif kind == "LWPOLYLINE":
            z = float(e.dxf.get("elevation", 0.0) or 0.0)
            rows += [(float(x), float(y), z) for x, y in e.get_points("xy")]
        elif kind == "POLYLINE":
            elevation = e.dxf.get("elevation")
            z0 = float(elevation.z) if elevation is not None else 0.0
            for v in e.vertices:
                loc = v.dxf.location
                rows.append((loc.x, loc.y, loc.z if e.is_3d_polyline else z0))
        elif kind == "3DFACE":
            for name in ("vtx0", "vtx1", "vtx2", "vtx3"):
                v = e.dxf.get(name)
                if v is not None:
                    rows.append((v.x, v.y, v.z))
    if not rows:
        raise TerrainError("the DXF has no points, lines, polylines or 3D faces")
    return np.unique(np.asarray(rows, dtype=float), axis=0)


#: GeoTIFF tags.
_PIXEL_SCALE, _TIE_POINT, _GEO_KEYS, _NODATA = 33550, 33922, 34735, 42113


def read_geotiff(path: str | Path, max_points: int = MAX_POINTS) -> tuple[np.ndarray, str]:
    """Points (pixel centres) of a single-band GeoTIFF DEM, sampled to about ``max_points``,
    and its coordinate system ("EPSG:<code>", or "project" when it names none)."""
    try:
        from PIL import Image
    except ImportError as error:  # pragma: no cover - Pillow comes with the plotting libraries
        raise TerrainError("reading GeoTIFF needs Pillow, which is not installed") from error
    try:
        image = Image.open(str(path))
        tags = dict(image.tag_v2)
        data = np.asarray(image, dtype=float)
    except (OSError, ValueError) as error:
        raise TerrainError(f"the GeoTIFF could not be read: {error}") from error
    if data.ndim != 2:
        raise TerrainError("the GeoTIFF has more than one band: give a single-band DEM")
    scale = tags.get(_PIXEL_SCALE)
    tie = tags.get(_TIE_POINT)
    if not scale or not tie or len(tie) < 6:
        raise TerrainError("the TIFF has no GeoTIFF pixel scale and tie point")
    sx, sy = float(scale[0]), float(scale[1])
    i0, j0, x0, y0 = float(tie[0]), float(tie[1]), float(tie[3]), float(tie[4])
    crs = "project"
    keys = tags.get(_GEO_KEYS)
    if keys and len(keys) >= 4:
        count = int(keys[3])
        entries = {int(keys[4 + 4 * k]): int(keys[7 + 4 * k]) for k in range(count)}
        # ProjectedCSTypeGeoKey (3072), else GeographicTypeGeoKey (2048).
        code = entries.get(3072) or entries.get(2048)
        if code and code != 32767:
            crs = f"EPSG:{code}"
    nodata = tags.get(_NODATA)
    rows, cols = data.shape
    step = max(1, math.ceil(math.sqrt(rows * cols / max_points)))
    jj, ii = np.mgrid[0:rows:step, 0:cols:step]
    z = data[jj, ii]
    x = x0 + (ii + 0.5 - i0) * sx
    y = y0 - (jj + 0.5 - j0) * sy
    keep = np.isfinite(z)
    if nodata is not None:
        try:
            keep &= z != float(str(nodata).strip("\x00 "))
        except ValueError:
            pass
    points = np.column_stack([x[keep], y[keep], z[keep]])
    if not len(points):
        raise TerrainError("the DEM has no elevations (all no-data)")
    return points, crs


def thin(points: np.ndarray, max_points: int = MAX_POINTS) -> np.ndarray:
    """At most about ``max_points``: the first point of each cell of a plan grid."""
    if len(points) <= max_points:
        return points
    lo, hi = points[:, :2].min(axis=0), points[:, :2].max(axis=0)
    cell = math.sqrt(max(float(np.prod(hi - lo)), 1e-9) / max_points)
    keys = np.floor((points[:, :2] - lo) / cell).astype(np.int64)
    _, first = np.unique(keys, axis=0, return_index=True)
    return points[np.sort(first)]


def to_project(
    points: np.ndarray, units: str, crs: str, site: Any = None
) -> tuple[np.ndarray, list[str]]:
    """x/y of ``points`` in the project grid [mm] (z unchanged): from the project grid in
    ``units``, or from an EPSG system through the site point."""
    notes: list[str] = []
    out = points.copy()
    if crs == "project":
        out[:, :2] *= UNIT_MM[units]
        return out, notes
    match = re.fullmatch(r"(?i)epsg:(\d+)", crs.strip())
    if not match:
        raise TerrainError(f"unknown coordinate system '{crs}' (project or EPSG:<code>)")
    if site is None or not getattr(site, "georeferenced", False):
        raise TerrainError(
            f"the survey is in {crs.upper()}: set the site point (latitude/longitude) in "
            "01 Soil Report to place it in the project grid"
        )
    from pyproj import Transformer

    from saengine.gis.crs import Grid

    code = int(match.group(1))
    grid = Grid(site)
    if code != 4326:
        lon, lat = Transformer.from_crs(code, 4326, always_xy=True).transform(
            points[:, 0], points[:, 1]
        )
    else:
        lon, lat = points[:, 0], points[:, 1]
    xy = [grid.from_wgs84(float(a), float(o)) for a, o in zip(lat, lon, strict=True)]
    out[:, :2] = np.asarray(xy, dtype=float)
    notes.append(f"survey coordinates {crs.upper()} placed by the site point")
    return out, notes


def triangulate(points: np.ndarray) -> np.ndarray:
    """Delaunay triangles in plan (indices into ``points``)."""
    from scipy.spatial import Delaunay, QhullError

    if len(points) < 3:
        raise TerrainError("a terrain needs at least 3 points")
    try:
        return Delaunay(points[:, :2]).simplices.astype(int)
    except QhullError as error:
        raise TerrainError(f"the points do not make a surface: {error}") from error


# ─────────────────────────────────── cut and fill ───────────────────────────────────


def _clip(poly: list[tuple[float, float]], f: Any, sign: float) -> list[tuple[float, float]]:
    """Sutherland-Hodgman clip of a convex polygon to sign * f(x, y) >= 0 (f linear)."""
    out: list[tuple[float, float]] = []
    n = len(poly)
    for k in range(n):
        p, q = poly[k], poly[(k + 1) % n]
        fp, fq = sign * f(*p), sign * f(*q)
        if fp >= 0:
            out.append(p)
        if (fp >= 0) != (fq >= 0) and fp != fq:
            t = fp / (fp - fq)
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return out


def cut_fill(
    points: np.ndarray | list[list[float]],
    triangles: np.ndarray | list[list[int]],
    outline: list[tuple[float, float]] | Any,
    level: float,
) -> dict[str, float]:
    """Cut and fill [m³] of the terrain to ``level`` [mm] over ``outline`` (a ring in mm or a
    shapely polygon), with the platform area [m²] and the part of it no triangle covers."""
    from shapely.geometry import Polygon
    from shapely.prepared import prep

    pts = np.asarray(points, dtype=float)
    tris = np.asarray(triangles, dtype=int)
    platform = outline if hasattr(outline, "area") else Polygon(outline)
    platform = platform.buffer(0)
    ready = prep(platform)
    bx0, by0, bx1, by1 = platform.bounds
    cut = fill = covered = 0.0
    for tri in tris:
        corners = pts[tri]
        if (
            corners[:, 0].max() < bx0
            or corners[:, 0].min() > bx1
            or corners[:, 1].max() < by0
            or corners[:, 1].min() > by1
        ):
            continue
        ring = [(float(c[0]), float(c[1])) for c in corners]
        shape = Polygon(ring)
        if shape.area <= 0 or not ready.intersects(shape):
            continue
        # The plane through the corners, less the level: d(x, y) = a x + b y + c.
        (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = corners
        det = (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)
        if abs(det) < 1e-12:
            continue
        a = ((z2 - z1) * (y3 - y1) - (z3 - z1) * (y2 - y1)) / det
        b = ((x2 - x1) * (z3 - z1) - (x3 - x1) * (z2 - z1)) / det
        c = z1 - level - a * x1 - b * y1

        def d(x: float, y: float, a: float = a, b: float = b, c: float = c) -> float:
            return a * x + b * y + c

        covered += shape.intersection(platform).area
        for sign in (1.0, -1.0):
            part = _clip(ring, d, sign)
            if len(part) < 3:
                continue
            piece = Polygon(part)
            if piece.area <= 0:
                continue
            inside = piece.intersection(platform)
            if inside.is_empty or inside.area <= 0:
                continue
            volume = inside.area * d(inside.centroid.x, inside.centroid.y)
            if sign > 0:
                cut += max(volume, 0.0)
            else:
                fill += max(-volume, 0.0)
    return {
        "cut": float(cut) * 1e-9,
        "fill": float(fill) * 1e-9,
        "area": float(platform.area) * 1e-6,
        "uncovered": max(float(platform.area - covered), 0.0) * 1e-6,
    }


def elevation_at(
    points: np.ndarray | list[list[float]],
    triangles: np.ndarray | list[list[int]],
    x: float,
    y: float,
) -> float | None:
    """The terrain's z [mm] at (x, y), None outside it."""
    pts = np.asarray(points, dtype=float)
    for tri in np.asarray(triangles, dtype=int):
        (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = pts[tri]
        det = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
        if abs(det) < 1e-12:
            continue
        l1 = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / det
        l2 = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / det
        l3 = 1 - l1 - l2
        if min(l1, l2, l3) >= -1e-9:
            return float(l1 * z1 + l2 * z2 + l3 * z3)
    return None


def bill_items(terrain: Terrain, groups: dict[str, str]) -> tuple[list[dict[str, Any]], list[str]]:
    """The earthwork items of the last cut and fill (JSON-ready ``BoqItem`` shape) and notes."""
    if terrain.cut is None and terrain.fill is None:
        return [], []
    items = []
    letter = groups["earthwork"]
    level = terrain.platform.level
    where = f" at {level / 1000:.3f} m" if level is not None else ""
    for n, (kind, what, value) in enumerate(
        (("siteCut", "Site cut", terrain.cut), ("siteFill", "Site fill", terrain.fill)), start=1
    ):
        if not value or value <= 0:
            continue
        items.append(
            {
                "code": f"{letter}.{CODE_LETTER}{n:02d}",
                "group": "earthwork",
                "description": f"{what} to the building platform{where} (from the terrain)",
                "quantity": round(value, 3),
                "unit": "m3",
                "kind": kind,
                "origin": "terrain",
                "breakdown": [
                    {"element": "platform", "detail": "terrain model", "quantity": round(value, 3)}
                ],
            }
        )
    notes = (
        [
            (
                "Site cut and fill from the terrain (01 Soil Report/terrain.json) to the building "
                "platform: bank volumes of the TIN against the platform level, no side slopes, no "
                "bulking"
            )
        ]
        if items
        else []
    )
    return items, notes


# ─────────────────────────────────── the project ───────────────────────────────────


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _site(root: Path) -> Any:
    from saengine.library.soil import SoilReport

    text = _read(root / SOIL_FILE)
    if not text:
        return None
    try:
        return SoilReport.model_validate_json(text).site
    except ValueError:
        return None


def _ground_level(root: Path) -> float:
    text = _read(root / "02 Project Settings/project-settings.json")
    try:
        return float(((json.loads(text or "{}").get("foundation") or {}).get("groundLevel")) or 0)
    except (ValueError, TypeError, AttributeError):
        return 0.0


def platform_outline(root: Path, platform: Platform) -> tuple[Any, str]:
    """The platform polygon [mm] (grown by the margin) and what it is."""
    from shapely.geometry import Polygon

    from saengine.gis.plot import plot_ring
    from saengine.gis.site import building_outline

    if platform.outline == "custom":
        if len(platform.points) < 3:
            raise TerrainError("the custom platform outline needs at least 3 points")
        ring, what = [(float(p[0]), float(p[1])) for p in platform.points], "the outline given"
    elif platform.outline == "plot":
        ring, why = plot_ring(_site(root))
        if not ring:
            raise TerrainError(why or "the site has no plot: draw it in 01 Soil Report")
        what = "the plot"
    else:
        ring, how = building_outline(_read(root / "06 BIM/bim.json"))
        if not ring:
            raise TerrainError(f"no building outline: {how}")
        what = f"the building ({how})"
    shape = Polygon(ring).buffer(0)
    if platform.margin > 0:
        shape = shape.buffer(platform.margin, join_style="mitre")
        what += f" grown by {platform.margin / 1000:g} m"
    return shape, what


def compute(terrain: Terrain, root: Path) -> Terrain:
    """The cut and fill of ``terrain`` to its platform (the results set on it)."""
    if not terrain.triangles:
        return terrain
    level = terrain.platform.level if terrain.platform.level is not None else _ground_level(root)
    shape, what = platform_outline(root, terrain.platform)
    found = cut_fill(terrain.points, terrain.triangles, shape, level)
    terrain.cut, terrain.fill = round(found["cut"], 3), round(found["fill"], 3)
    terrain.platformArea = round(found["area"], 3)
    terrain.notes = [n for n in terrain.notes if not n.startswith(("platform:", "uncovered:"))]
    terrain.notes.append(f"platform: {what} at {level / 1000:.3f} m")
    if found["uncovered"] > 0.01 * max(found["area"], 1e-9):
        terrain.notes.append(
            f"uncovered: {found['uncovered']:.1f} m² of the platform is outside the terrain "
            "surveyed: not measured"
        )
    return terrain


def import_survey(
    project_root: str,
    path: str,
    units: str = "m",
    crs: str | None = None,
    datum: float | None = None,
    platform: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reads a survey (GeoTIFF, XYZ or DXF, by the extension), triangulates it in the project
    grid and writes ``01 Soil Report/terrain.json`` with the cut and fill of the platform;
    returns ``{"terrain", "path", "notes"}`` or ``{"problems"}``."""
    root = Path(project_root)
    source = Path(path)
    suffix = source.suffix.lower()
    notes: list[str] = []
    try:
        if suffix in (".tif", ".tiff"):
            raw, found_crs = read_geotiff(source)
            fmt = "geotiff"
            crs = crs or found_crs
        elif suffix == ".dxf":
            raw, fmt = read_dxf(source), "dxf"
        else:
            raw, fmt = read_xyz(source.read_text(encoding="utf-8", errors="replace")), "xyz"
        crs = crs or "project"
        count = len(raw)
        raw = thin(raw)
        if len(raw) < count:
            notes.append(f"{count} survey points thinned to {len(raw)} on a plan grid")
        xyz, more = to_project(raw, units, crs, _site(root))
        notes += more
        previous = parse(_read(root / TERRAIN_FILE))
        plat = Platform.model_validate(platform) if platform else previous.platform
        level = plat.level if plat.level is not None else _ground_level(root)
        scale = UNIT_MM[units]
        if datum is None:
            # The mean survey elevation inside the platform is at the platform level.
            try:
                shape, _ = platform_outline(root, plat)
                from shapely.geometry import Point

                inside = [p[2] for p in xyz if shape.covers(Point(p[0], p[1]))]
            except TerrainError:
                inside = []
            mean = float(np.mean(inside)) if inside else float(np.mean(xyz[:, 2]))
            datum = mean - level / scale
            notes.append(
                f"datum: survey elevation {datum:.3f} {units} is project z = 0 (the mean ground "
                "inside the platform at the platform level); give the datum to fix it"
            )
        xyz[:, 2] = (xyz[:, 2] - datum) * scale
        triangles = triangulate(xyz)
    except (TerrainError, OSError) as error:
        return {"problems": [str(error)]}
    terrain = Terrain(
        source=TerrainSource(
            file=source.name,
            format=fmt,
            units=units,
            crs=crs,
            datum=datum,
            pointsRead=count,  # type: ignore[arg-type]
        ),
        points=[[round(float(v), 1) for v in p] for p in xyz],
        triangles=triangles.tolist(),
        platform=plat,
        notes=notes,
    )
    try:
        compute(terrain, root)
    except TerrainError as error:
        terrain.notes.append(f"no cut and fill: {error}")
    return _write(root, terrain)


def recompute(project_root: str, platform: dict[str, Any] | None = None) -> dict[str, Any]:
    """The cut and fill again (a new platform given, or the files changed)."""
    root = Path(project_root)
    text = _read(root / TERRAIN_FILE)
    if not text:
        return {"problems": ["no terrain: import a survey first"]}
    terrain = parse(text)
    if platform is not None:
        terrain.platform = Platform.model_validate(platform)
    try:
        compute(terrain, root)
    except TerrainError as error:
        return {"problems": [str(error)]}
    return _write(root, terrain)


def _write(root: Path, terrain: Terrain) -> dict[str, Any]:
    path = root / TERRAIN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    text = terrain.model_dump_json(by_alias=True, exclude_none=True) + "\n"
    path.write_text(text, encoding="utf-8")
    data = json.loads(text)
    return {
        "terrain": {k: v for k, v in data.items() if k not in ("points", "triangles")},
        "pointCount": len(terrain.points),
        "triangleCount": len(terrain.triangles),
        "path": str(path),
        "notes": terrain.notes,
    }


def mesh(project_root: str) -> dict[str, Any]:
    """The terrain's points and triangles for the viewers (``{"points", "triangles"}``, flat
    lists in mm), or ``{"points": []}`` without a terrain."""
    terrain = parse(_read(Path(project_root) / TERRAIN_FILE))
    return {
        "points": [v for p in terrain.points for v in p],
        "triangles": [i for t in terrain.triangles for i in t],
        "platform": terrain.platform.model_dump(exclude_none=True),
    }

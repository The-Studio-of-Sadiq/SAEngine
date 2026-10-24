"""Import of 3D geometry into the structural model of a special structure (Part 5).

Roofs, towers and plants are often shaped in another program first. This reads the wireframe
or surface model it exported and turns it into members, areas and supports:

- DXF (any CAD program), read with ezdxf: lines, polylines, arcs, circles and splines become
  members (curves as straight pieces); 3D faces, polyface meshes and meshes become areas, and so
  do closed polylines when an area type is given. A DWG is converted to DXF first
  (:mod:`saengine.library.dwg`, GNU LibreDWG as a separate program) and read the same way.
- IFC (any BIM program), read with IfcOpenShell: beams, columns and members become members along
  their axis; slabs, walls, plates, roofs and coverings become areas on their mid-surface.
- Rhino (``.3dm``), read with rhino3dm: curves become members; planar faces of surfaces,
  polysurfaces and extrusions, and mesh faces, become areas.

Object types: an element on a layer (DXF, Rhino) or with an IFC type named exactly like an
object type of the right kind gets that type; otherwise vertical members get the column type,
other members the member type, vertical areas the wall type and other areas the slab type.
Elements left without a type are skipped and counted in the notes, as are shapes that cannot
be represented (curved faces, solids that are not thin plates).

Lengths are scaled to mm from the file's own units, or from the units chosen.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import Field

from saengine.library.materials import Id
from saengine.library.shapes import Geometry, LineElement, PanelElement, Supports
from saengine.library.structure import TOLERANCE, _Model, plane_of

Units = Literal["auto", "mm", "cm", "m", "in", "ft"]

_SCALE = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8}

#: Curves are cut into straight members deviating at most this much from them [mm].
CHORD_TOLERANCE = 25.0

#: A member is vertical (a column) when it leans less than this from the vertical [°].
VERTICAL = 1.0

FORMATS = {".dxf": "DXF", ".dwg": "DWG", ".ifc": "IFC", ".3dm": "Rhino"}


class ImportOptions(_Model):
    """How a file's geometry becomes members, areas and supports."""

    units: Units = Field(
        default="auto",
        description="Units of the file's coordinates; auto reads them from the file "
        "(unitless files are taken as mm).",
    )
    memberType: Id | None = Field(
        default=None,
        title="Member type",
        description="Beam or brace type of members that are not vertical.",
    )
    columnType: Id | None = Field(
        default=None, title="Column type", description="Type of vertical members."
    )
    slabType: Id | None = Field(
        default=None, title="Slab type", description="Type of areas that are not vertical."
    )
    wallType: Id | None = Field(
        default=None, title="Wall type", description="Type of vertical areas."
    )
    supports: Supports = Field(
        default="none",
        title="Supports at the base",
        description="Supports added at every point of the imported elements on their lowest level.",
    )


class ImportInput(_Model):
    """What the modeller's Import panel edits."""

    options: ImportOptions = Field(default_factory=ImportOptions)


# ───────────────────────────── shared ─────────────────────────────


class _Collector:
    """Raw lines and polygons (in mm) with the name that may pick their type."""

    def __init__(self) -> None:
        self.lines: list[tuple[np.ndarray, np.ndarray, str]] = []
        self.polygons: list[tuple[list[np.ndarray], list[list[np.ndarray]], str]] = []
        #: Closed curves: areas when an area type applies to them, else members along them.
        self.closed: list[tuple[list[np.ndarray], str]] = []
        self.skipped: Counter[str] = Counter()

    def polyline(self, points: Iterable[np.ndarray], name: str) -> None:
        pts = _dedupe(list(points))
        for a, b in itertools.pairwise(pts):
            self.lines.append((a, b, name))

    def polygon(
        self, outline: list[np.ndarray], name: str, openings: list[list[np.ndarray]] | None = None
    ) -> None:
        pts = _dedupe(outline)
        if len(pts) > 1 and np.linalg.norm(pts[0] - pts[-1]) < TOLERANCE:
            pts = pts[:-1]
        if len(pts) < 3 or plane_of(pts) is None:
            self.skipped["faces that are not flat"] += 1
            return
        self.polygons.append((pts, [_dedupe(h) for h in openings or []], name))


def _dedupe(points: list[np.ndarray]) -> list[np.ndarray]:
    result: list[np.ndarray] = []
    for p in points:
        if not result or np.linalg.norm(p - result[-1]) >= TOLERANCE:
            result.append(np.asarray(p, dtype=float))
    return result


def _is_vertical_line(a: np.ndarray, b: np.ndarray) -> bool:
    d = b - a
    return math.degrees(math.atan2(math.hypot(d[0], d[1]), abs(d[2]))) < VERTICAL


def _is_vertical_area(points: list[np.ndarray]) -> bool:
    plane = plane_of(points)
    return plane is not None and abs(float(plane[1][2])) < math.sin(math.radians(VERTICAL))


def _area_type(
    outline: list[np.ndarray], name: str, options: ImportOptions, kinds: Mapping[str, str]
) -> str | None:
    if kinds.get(name) in ("slab", "wall"):
        return name
    return options.wallType if _is_vertical_area(outline) else options.slabType


def _geometry(collected: _Collector, options: ImportOptions, kinds: Mapping[str, str]) -> Geometry:
    """Typed elements (by layer or type name, else by direction) and base supports."""
    g = Geometry()
    untyped = Counter[str]()
    lines = list(collected.lines)
    polygons = list(collected.polygons)
    for points, name in collected.closed:
        if _area_type(points, name, options, kinds):
            polygons.append((points, [], name))
        else:
            lines += [(a, b, name) for a, b in zip(points, points[1:] + points[:1], strict=True)]
    for a, b, name in lines:
        named = name if kinds.get(name) in ("beam", "column", "brace") else None
        vertical = _is_vertical_line(a, b)
        if vertical and a[2] > b[2]:
            a, b = b, a  # columns run upwards
        type_ = named or (options.columnType if vertical else options.memberType)
        if type_:
            g.members.append(LineElement(a, b, type_))
        else:
            untyped["members"] += 1
    for outline, openings, name in polygons:
        type_ = _area_type(outline, name, options, kinds)
        if type_:
            g.areas.append(PanelElement(outline, type_, openings))
        else:
            untyped["areas"] += 1
    if options.supports != "none":
        points = [p for m in g.members for p in (m.start, m.end)] + [
            p for a in g.areas for p in a.outline
        ]
        if points:
            bottom = min(float(p[2]) for p in points)
            seen: set[tuple[int, int, int]] = set()
            for p in points:
                key = (round(float(p[0])), round(float(p[1])), round(float(p[2])))
                if abs(float(p[2]) - bottom) < TOLERANCE and key not in seen:
                    seen.add(key)
                    g.support(p, options.supports)
    for what, count in untyped.items():
        g.notes.append(f"{count} {what} skipped: no type for them (choose one).")
    for what, count in collected.skipped.items():
        g.notes.append(f"{count} {what} skipped.")
    return g


def import_geometry(path: str | Path, options: ImportOptions, kinds: Mapping[str, str]) -> Geometry:
    """The geometry of the DXF, DWG, IFC or Rhino file at ``path``; ``kinds`` maps object type
    ids to their kinds (beam, column, slab...)."""
    path = Path(path)
    if path.suffix.lower() == ".dwg":
        from saengine.library import dwg

        with dwg.converted(path) as conversion:
            g = import_geometry(conversion.dxf, options, kinds)
        g.notes[:0] = [f"{path.name}: {note}" for note in conversion.warnings]
        return g
    readers = {".dxf": _read_dxf, ".ifc": _read_ifc, ".3dm": _read_3dm}
    reader = readers.get(path.suffix.lower())
    if reader is None:
        raise ValueError(f"{path.name}: only DXF, DWG, IFC and Rhino (.3dm) files can be imported")
    collected, scale_note = reader(path, options.units)
    g = _geometry(collected, options, kinds)
    if scale_note:
        g.notes.insert(0, scale_note)
    return g


# ───────────────────────────── DXF ─────────────────────────────


def _read_dxf(path: Path, units: Units) -> tuple[_Collector, str | None]:
    import ezdxf
    from ezdxf import disassemble
    from ezdxf import path as dxfpath
    from ezdxf import units as dxfunits
    from ezdxf.render import MeshBuilder

    doc = ezdxf.readfile(path)
    note = None
    if units == "auto":
        code = int(doc.header.get("$INSUNITS", 0))
        if code == 0:
            scale, note = 1.0, "The file has no units: coordinates taken as mm."
        else:
            scale = dxfunits.conversion_factor(code, dxfunits.MM)
    else:
        scale = _SCALE[units]
    tolerance = CHORD_TOLERANCE / scale

    def mm(points: Iterable) -> list[np.ndarray]:
        return [np.array([p[0], p[1], p[2]], dtype=float) * scale for p in points]

    c = _Collector()
    for e in disassemble.recursive_decompose(doc.modelspace()):  # blocks exploded in place
        kind = e.dxftype()
        layer = e.dxf.get("layer", "0")
        if kind in ("LINE", "LWPOLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE") or (
            kind == "POLYLINE" and not (e.is_poly_face_mesh or e.is_polygon_mesh)
        ):
            p = dxfpath.make_path(e)
            points = mm(p.flattening(tolerance))
            closed = kind == "CIRCLE" or (
                len(points) > 3 and np.linalg.norm(points[0] - points[-1]) < TOLERANCE
            )
            outline = _dedupe(points[:-1] if closed else points)
            if closed and len(outline) >= 3 and plane_of(outline) is not None:
                c.closed.append((outline, layer))
            else:
                c.polyline(points, layer)
        elif kind == "3DFACE":
            corners = mm(e.wcs_vertices(close=False))
            c.polygon(corners, layer)
        elif kind in ("MESH", "POLYLINE"):
            mesh = MeshBuilder.from_mesh(e) if kind == "MESH" else MeshBuilder.from_polyface(e)
            vertices = mm(mesh.vertices)
            for face in mesh.faces:
                c.polygon([vertices[i] for i in face], layer)
        else:
            c.skipped[f"{kind} entities"] += 1
    return c, note


# ───────────────────────────── IFC ─────────────────────────────

_LINEAR = ("IfcBeam", "IfcColumn", "IfcMember")
_PLANAR = ("IfcSlab", "IfcWall", "IfcPlate", "IfcRoof", "IfcCovering")


def _read_ifc(path: Path, units: Units) -> tuple[_Collector, str | None]:
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.element

    ifc = ifcopenshell.open(str(path))
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    # IfcOpenShell's geometry is in metres whatever the file's units.
    scale = 1000.0 if units == "auto" else _SCALE[units] * 1000.0 / _project_scale(ifc)
    c = _Collector()
    seen: set[int] = set()
    for cls in (*_LINEAR, *_PLANAR):
        for element in ifc.by_type(cls):
            if element.id() in seen or not element.Representation:
                continue
            seen.add(element.id())
            if element.is_a("IfcRoof") and ifcopenshell.util.element.get_decomposition(element):
                continue  # its slabs and plates come on their own
            type_object = ifcopenshell.util.element.get_type(element)
            name = (type_object.Name if type_object else None) or element.ObjectType or ""
            try:
                shape = ifcopenshell.geom.create_shape(settings, element)
            except RuntimeError:
                c.skipped[f"{element.is_a()} without usable geometry"] += 1
                continue
            vertices = np.array(shape.geometry.verts, dtype=float).reshape(-1, 3) * scale
            faces = np.array(shape.geometry.faces, dtype=int).reshape(-1, 3)
            if len(vertices) < 3:
                continue
            if cls in _LINEAR:
                axis = _axis(vertices)
                if axis is not None:
                    c.lines.append((*axis, name))
            else:
                surface = _mid_surface(vertices, faces)
                if surface is None:
                    c.skipped[f"{element.is_a()} elements that are not thin plates"] += 1
                else:
                    c.polygon(surface[0], name, surface[1])
    return c, None


def _project_scale(ifc: object) -> float:
    """Metres per project length unit."""
    import ifcopenshell.util.unit

    return float(ifcopenshell.util.unit.calculate_unit_scale(ifc))


def _principal(vertices: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Centre, axes (rows, longest first) and extents along them of a point cloud."""
    centre = vertices.mean(axis=0)
    _, _, axes = np.linalg.svd(vertices - centre, full_matrices=False)
    local = (vertices - centre) @ axes.T
    return centre, axes, local.max(axis=0) - local.min(axis=0)


def _axis(vertices: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """A linear element's centre line: through the middle of its section, end to end."""
    centre, axes, _ = _principal(vertices)
    along = (vertices - centre) @ axes[0]
    # The middle of the end faces: the mean of the cross-section's points at each end.
    lo, hi = along.min(), along.max()
    start = vertices[np.abs(along - lo) < TOLERANCE].mean(axis=0)
    end = vertices[np.abs(along - hi) < TOLERANCE].mean(axis=0)
    start = centre + axes[0] * lo + _off_axis(start - centre, axes[0])
    end = centre + axes[0] * hi + _off_axis(end - centre, axes[0])
    return (start, end) if np.linalg.norm(end - start) >= TOLERANCE else None


def _off_axis(v: np.ndarray, axis: np.ndarray) -> np.ndarray:
    return v - axis * float(v @ axis)


def _mid_surface(
    vertices: np.ndarray, faces: np.ndarray
) -> tuple[list[np.ndarray], list[list[np.ndarray]]] | None:
    """The mid-plane outline (and openings) of a thin plate: its triangles projected onto the
    plane through its centre, normal to its thinnest direction, and merged."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    centre, axes, extents = _principal(vertices)
    if extents[2] > 0.5 * extents[1]:
        return None
    u, v = axes[0], axes[1]
    flat = np.column_stack(((vertices - centre) @ u, (vertices - centre) @ v))
    triangles = [Polygon(flat[f]) for f in faces]
    merged = unary_union([t.buffer(0.01) for t in triangles if t.area > 1e-6]).buffer(-0.01)
    if merged.geom_type == "MultiPolygon":
        merged = max(merged.geoms, key=lambda g: g.area)
    if merged.is_empty or merged.geom_type != "Polygon":
        return None
    merged = merged.simplify(TOLERANCE)

    def back(ring: object) -> list[np.ndarray]:
        coords = list(ring.coords)[:-1]  # type: ignore[attr-defined]
        return [centre + x * u + y * v for x, y in coords]

    return back(merged.exterior), [back(r) for r in merged.interiors]


# ───────────────────────────── Rhino ─────────────────────────────

_RHINO_UNITS = {
    "Millimeters": 1.0,
    "Centimeters": 10.0,
    "Decimeters": 100.0,
    "Meters": 1000.0,
    "Kilometers": 1e6,
    "Inches": 25.4,
    "Feet": 304.8,
    "Yards": 914.4,
}


def _read_3dm(path: Path, units: Units) -> tuple[_Collector, str | None]:
    import rhino3dm

    model = rhino3dm.File3dm.Read(str(path))
    if model is None:
        raise ValueError(f"{path.name}: not a readable Rhino file")
    note = None
    if units == "auto":
        system = model.Settings.ModelUnitSystem.name
        if system in _RHINO_UNITS:
            scale = _RHINO_UNITS[system]
        else:
            scale, note = (
                1.0,
                f"The file's units ({system}) are not known: coordinates taken as mm.",
            )
    else:
        scale = _SCALE[units]
    layers = {layer.Index: layer.Name for layer in model.Layers}

    def mm(p: object) -> np.ndarray:
        return np.array([p.X, p.Y, p.Z], dtype=float) * scale  # type: ignore[attr-defined]

    def curve_points(curve: object) -> list[np.ndarray]:
        if curve.IsLinear():  # type: ignore[attr-defined]
            return [mm(curve.PointAtStart), mm(curve.PointAtEnd)]  # type: ignore[attr-defined]
        polyline = curve.TryGetPolyline()  # type: ignore[attr-defined]
        if polyline is not None and polyline.Count > 1:
            return [mm(polyline[i]) for i in range(polyline.Count)]
        lo, hi = curve.Domain.T0, curve.Domain.T1  # type: ignore[attr-defined]
        count = max(8, 4 * curve.SpanCount)  # type: ignore[attr-defined]
        return [mm(curve.PointAt(lo + (hi - lo) * k / count)) for k in range(count + 1)]  # type: ignore[attr-defined]

    def loop_points(brep: object, loop: object) -> list[np.ndarray]:
        points: list[np.ndarray] = []
        for trim in loop.Trims:  # type: ignore[attr-defined]
            edge = brep.Edges[trim.EdgeIndex]  # type: ignore[attr-defined]
            pts = curve_points(edge)
            if trim.IsReversed:
                pts = pts[::-1]
            points.extend(pts[:-1])
        return points

    c = _Collector()
    for obj in model.Objects:
        geometry = obj.Geometry
        layer = layers.get(obj.Attributes.LayerIndex, "")
        if isinstance(geometry, rhino3dm.Extrusion):
            geometry = geometry.ToBrep(True)
        if isinstance(geometry, rhino3dm.Curve):
            points = curve_points(geometry)
            outline = _dedupe(points[:-1])
            if geometry.IsClosed and len(outline) >= 3 and plane_of(outline) is not None:
                c.closed.append((outline, layer))
            else:
                c.polyline(points, layer)
        elif isinstance(geometry, rhino3dm.Brep):
            if geometry.IsSolid:
                c.skipped["closed solids (model their mid-surfaces instead)"] += 1
                continue
            for face in geometry.Faces:
                if not face.IsPlanar():
                    c.skipped["curved faces"] += 1
                    continue
                outer = face.OuterLoop
                inner = [loop for loop in face.Loops if loop.LoopType != outer.LoopType]
                c.polygon(
                    loop_points(geometry, outer), layer, [loop_points(geometry, h) for h in inner]
                )
        elif isinstance(geometry, rhino3dm.Mesh):
            vertices = [mm(geometry.Vertices[i]) for i in range(len(geometry.Vertices))]
            for i in range(len(geometry.Faces)):
                a, b, cc, d = geometry.Faces[i]
                c.polygon([vertices[k] for k in ((a, b, cc) if cc == d else (a, b, cc, d))], layer)
        else:
            c.skipped[f"{type(geometry).__name__} objects"] += 1
    return c, note

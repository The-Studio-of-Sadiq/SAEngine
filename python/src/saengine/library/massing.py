"""Conceptual massing and in-place elements for ``05 Floor Plan/architecture.json``.

Conceptual masses (:class:`ConceptualMass`) represent early-stage architectural volumes
(extruded polygons, boxes, cylinders, and linear lofts between two outlines). Masses slice
into mass floors to compute gross floor area (GFA), ground coverage, and FAR checks (reusing
:mod:`saengine.gis.planning`), and can generate storey elevations and floor outlines via
:func:`create_floors_from_mass`. Conceptual masses are excluded from structural loads and
framing; IFC exports them as ``IfcBuildingElementProxy`` with ``ExcludedFromStructure=True``.

In-place elements (:class:`InPlaceElement`) represent one-off components with custom geometry,
category, and parameters.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from saengine.library.components import _DEFAULT_IFC_CLASS, ComponentCategory, ParameterValue
from saengine.library.labels import field_title
from saengine.library.materials import Id

if TYPE_CHECKING:
    from saengine.library.architecture import Architecture

Length = float
Mm = float
Point2 = list[float]
MassKind = Literal["extrusion", "box", "cylinder", "loft"]


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, field_title_generator=field_title
    )


def _validate_mass_geometry(
    item_id: str,
    kind: MassKind,
    *,
    outline: list[Point2] | None,
    width: float | None,
    depth: float | None,
    radius: float | None,
    base_outline: list[Point2] | None,
    top_outline: list[Point2] | None,
) -> None:
    if kind == "extrusion":
        if not outline or len(outline) < 3:
            raise ValueError(f"{item_id}: extrusion mass requires outline with at least 3 points")
    elif kind == "box":
        if not width or width <= 0 or not depth or depth <= 0:
            raise ValueError(f"{item_id}: box mass requires positive width and depth")
    elif kind == "cylinder":
        if not radius or radius <= 0:
            raise ValueError(f"{item_id}: cylinder mass requires positive radius")
    elif kind == "loft":  # noqa: SIM102 - one branch per kind
        if not base_outline or len(base_outline) < 3 or not top_outline or len(top_outline) < 3:
            raise ValueError(
                f"{item_id}: loft mass requires baseOutline and topOutline with at least 3 points each"
            )


class ConceptualMass(_Model):
    """A conceptual architectural mass volume (excluded from structural analysis)."""

    id: Id
    name: str = Field(default="Mass", min_length=1)
    kind: MassKind = "extrusion"
    baseElevation: float = Field(default=0.0, description="Base elevation [mm].")
    height: float = Field(gt=0, description="Height [mm].")
    outline: list[Point2] | None = Field(
        default=None, description="Plan polygon [mm] for extrusion."
    )
    origin: Point2 | None = Field(default=None, description="Centre [x, y] in mm for box.")
    width: float | None = Field(default=None, gt=0, description="Box X width [mm].")
    depth: float | None = Field(default=None, gt=0, description="Box Y depth [mm].")
    rotation: float = Field(default=0.0, description="Plan rotation CCW [°] for box.")
    center: Point2 | None = Field(default=None, description="Centre [x, y] in mm for cylinder.")
    radius: float | None = Field(default=None, gt=0, description="Cylinder radius [mm].")
    baseOutline: list[Point2] | None = Field(
        default=None, description="Bottom polygon [mm] for loft."
    )
    topOutline: list[Point2] | None = Field(default=None, description="Top polygon [mm] for loft.")
    floorHeight: float | None = Field(
        default=None,
        gt=0,
        description="Optional uniform mass-floor spacing [mm] when slicing floors.",
    )
    use: str | None = Field(
        default=None, description="Optional planning use key (e.g. residential, commercial)."
    )

    @model_validator(mode="after")
    def _check_geometry(self) -> ConceptualMass:
        _validate_mass_geometry(
            self.id,
            self.kind,
            outline=self.outline,
            width=self.width,
            depth=self.depth,
            radius=self.radius,
            base_outline=self.baseOutline,
            top_outline=self.topOutline,
        )
        return self


class InPlaceElement(_Model):
    """A one-off in-place architectural element with custom geometry, category and parameters."""

    id: Id
    name: str = Field(min_length=1)
    category: ComponentCategory = "generic"
    story: Id
    geometry: MassKind = "extrusion"
    baseOffset: float = Field(default=0.0, description="Offset above story level [mm].")
    height: float = Field(gt=0, description="Height [mm].")
    outline: list[Point2] | None = None
    origin: Point2 | None = None
    width: float | None = Field(default=None, gt=0)
    depth: float | None = Field(default=None, gt=0)
    rotation: float = 0.0
    center: Point2 | None = None
    radius: float | None = Field(default=None, gt=0)
    baseOutline: list[Point2] | None = None
    topOutline: list[Point2] | None = None
    weight: float = Field(default=0.0, ge=0, description="Mass [kg].")
    material: str = ""
    hostRoom: Id | None = None
    parameters: dict[str, ParameterValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_geometry(self) -> InPlaceElement:
        _validate_mass_geometry(
            self.id,
            self.geometry,
            outline=self.outline,
            width=self.width,
            depth=self.depth,
            radius=self.radius,
            base_outline=self.baseOutline,
            top_outline=self.topOutline,
        )
        return self


# ───────────────────────────── geometry & prismoid volume ─────────────────────────────


def _clean_ring(points: Sequence[Sequence[float]]) -> list[tuple[float, float]]:
    ring = [(float(p[0]), float(p[1])) for p in points]
    if len(ring) > 1 and math.dist(ring[0], ring[-1]) < 1e-6:
        ring = ring[:-1]
    return ring


def _signed_area(ring: Sequence[tuple[float, float]]) -> float:
    n = len(ring)
    return 0.5 * sum(
        ring[i][0] * ring[(i + 1) % n][1] - ring[(i + 1) % n][0] * ring[i][1] for i in range(n)
    )


def _ensure_ccw(points: Sequence[Sequence[float]]) -> list[tuple[float, float]]:
    ring = _clean_ring(points)
    return list(reversed(ring)) if _signed_area(ring) < 0 else ring


def _resample_ring(ring: list[tuple[float, float]], target_n: int) -> list[tuple[float, float]]:
    """Resample a closed polygon ring uniformly by perimeter to ``target_n`` vertices."""
    if len(ring) == target_n:
        return ring
    closed = [*ring, ring[0]]
    dists = [0.0]
    for i in range(len(ring)):
        dists.append(dists[-1] + math.dist(closed[i], closed[i + 1]))
    total = dists[-1] or 1.0
    out: list[tuple[float, float]] = []
    for k in range(target_n):
        s = (k / target_n) * total
        idx = 0
        while idx < len(ring) - 1 and dists[idx + 1] < s:
            idx += 1
        seg_len = dists[idx + 1] - dists[idx]
        t = (s - dists[idx]) / seg_len if seg_len > 1e-9 else 0.0
        ax, ay = closed[idx]
        bx, by = closed[idx + 1]
        out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    return out


def _align_rings(
    base_pts: Sequence[Sequence[float]], top_pts: Sequence[Sequence[float]]
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Return CCW vertex-matched ``(base, top)`` rings with minimal twist."""
    base = _ensure_ccw(base_pts)
    top = _ensure_ccw(top_pts)
    if len(base) != len(top):
        n = max(len(base), len(top))
        base = _resample_ring(base, n)
        top = _resample_ring(top, n)
    n = len(base)
    best_shift = min(
        range(n),
        key=lambda shift: sum(
            (base[i][0] - top[(i + shift) % n][0]) ** 2
            + (base[i][1] - top[(i + shift) % n][1]) ** 2
            for i in range(n)
        ),
    )
    return base, [top[(i + best_shift) % n] for i in range(n)]


def _box_ring(
    origin: Sequence[float] | None, width: float, depth: float, rotation: float
) -> list[tuple[float, float]]:
    ox, oy = (float(origin[0]), float(origin[1])) if origin else (0.0, 0.0)
    hw, hd = width / 2.0, depth / 2.0
    rad = math.radians(rotation)
    c, s = math.cos(rad), math.sin(rad)
    return [
        (ox + lx * c - ly * s, oy + lx * s + ly * c)
        for lx, ly in [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
    ]


def _circle_ring(
    center: Sequence[float] | None, radius: float, steps: int = 64
) -> list[tuple[float, float]]:
    cx, cy = (float(center[0]), float(center[1])) if center else (0.0, 0.0)
    return [
        (
            cx + radius * math.cos(2.0 * math.pi * k / steps),
            cy + radius * math.sin(2.0 * math.pi * k / steps),
        )
        for k in range(steps)
    ]


def section_at(mass: ConceptualMass, elevation: float) -> list[tuple[float, float]] | None:
    """Horizontal cross-section ring [mm] of ``mass`` at ``elevation`` [mm], or None outside."""
    if elevation < mass.baseElevation - 1e-6 or elevation > mass.baseElevation + mass.height + 1e-6:
        return None
    if mass.kind == "extrusion":
        return _ensure_ccw(mass.outline or [])
    if mass.kind == "box":
        return _box_ring(mass.origin, mass.width or 0.0, mass.depth or 0.0, mass.rotation)
    if mass.kind == "cylinder":
        return _circle_ring(mass.center, mass.radius or 0.0)
    # loft: linear interpolation between aligned base and top rings
    base, top = _align_rings(mass.baseOutline or [], mass.topOutline or [])
    t = min(max((elevation - mass.baseElevation) / mass.height, 0.0), 1.0)
    return [
        (bx * (1.0 - t) + tx * t, by * (1.0 - t) + ty * t)
        for (bx, by), (tx, ty) in zip(base, top, strict=True)
    ]


def section_area_m2(mass: ConceptualMass, elevation: float) -> float:
    """Horizontal cross-section area [m²] of ``mass`` at ``elevation`` [mm]."""
    if elevation < mass.baseElevation - 1e-6 or elevation > mass.baseElevation + mass.height + 1e-6:
        return 0.0
    if mass.kind == "box":
        return float(mass.width or 0.0) * float(mass.depth or 0.0) / 1e6
    if mass.kind == "cylinder":
        return math.pi * float(mass.radius or 0.0) ** 2 / 1e6
    ring = section_at(mass, elevation)
    return abs(_signed_area(ring)) / 1e6 if ring else 0.0


def mass_volume_m3(mass: ConceptualMass) -> float:
    """Volume [m³] of ``mass``. Lofts use the exact prismoid formula h/6 * (A1 + 4*Am + A2)."""
    h_m = mass.height / 1000.0
    if mass.kind == "loft":
        a1 = section_area_m2(mass, mass.baseElevation)
        am = section_area_m2(mass, mass.baseElevation + mass.height / 2.0)
        a2 = section_area_m2(mass, mass.baseElevation + mass.height)
        return (h_m / 6.0) * (a1 + 4.0 * am + a2)
    return section_area_m2(mass, mass.baseElevation) * h_m


def in_place_anchor(elem: InPlaceElement) -> tuple[float, float]:
    """Representative plan point [x, y] in mm for host-room detection of an in-place element."""
    if elem.origin:
        return float(elem.origin[0]), float(elem.origin[1])
    if elem.center:
        return float(elem.center[0]), float(elem.center[1])
    ring = _ensure_ccw(elem.outline or elem.baseOutline or [[0.0, 0.0]])
    return (
        sum(p[0] for p in ring) / len(ring),
        sum(p[1] for p in ring) / len(ring),
    )


# ───────────────────────────── mass floors, FAR & storey generation ─────────────────────────────


def _slice_elevations(
    mass: ConceptualMass,
    levels: Sequence[float] | None = None,
    floor_height: float | None = None,
) -> list[float]:
    top = mass.baseElevation + mass.height
    if levels is not None:
        return sorted(z for z in set(levels) if mass.baseElevation - 1e-6 <= z < top - 1e-6)
    step = floor_height or mass.floorHeight
    if not step or step <= 0:
        return [mass.baseElevation]
    out: list[float] = []
    k = 0
    while True:
        z = mass.baseElevation + k * step
        if z >= top - 1e-6:
            break
        out.append(round(z, 6))
        k += 1
    return out


def mass_floors(
    mass: ConceptualMass,
    levels: Sequence[float] | None = None,
    floor_height: float | None = None,
) -> list[dict[str, Any]]:
    """Slice ``mass`` at floor levels (``levels``, or uniform ``floor_height`` / ``mass.floorHeight``
    [mm]) and return each floor's elevation, area [m²], perimeter [m], and plan outline."""
    from shapely.geometry import Polygon

    floors: list[dict[str, Any]] = []
    for idx, z in enumerate(_slice_elevations(mass, levels=levels, floor_height=floor_height), 1):
        ring = section_at(mass, z)
        if not ring:
            continue
        poly = Polygon(ring).buffer(0)
        area = poly.area / 1e6 if not poly.is_empty else 0.0
        perim = poly.length / 1000.0 if not poly.is_empty else 0.0
        floors.append(
            {
                "id": f"{mass.id}-F{idx}",
                "mass": mass.id,
                "elevation": z,
                "elevation_m": round(z / 1000.0, 3),
                "area_m2": round(area, 4),
                "perimeter_m": round(perim, 3),
                "outline": [[round(x, 3), round(y, 3)] for x, y in ring],
            }
        )
    return floors


def mass_floor_area_report(
    masses: Sequence[ConceptualMass],
    levels: Sequence[float] | None = None,
    floor_height: float | None = None,
    *,
    plot_area_m2: float | None = None,
    site: Any = None,
    use: str | None = None,
    road_width_m: float | None = None,
) -> dict[str, Any]:
    """Aggregate mass floors across ``masses`` into gross floor area (GFA), ground coverage,
    volume, and FAR check (reusing :mod:`saengine.gis.planning`)."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    level_shapes: dict[float, list[Any]] = {}
    all_footprints: list[Any] = []
    total_volume = 0.0

    for mass in masses:
        total_volume += mass_volume_m3(mass)
        base_ring = section_at(mass, mass.baseElevation)
        if base_ring:
            base_poly = Polygon(base_ring).buffer(0)
            if not base_poly.is_empty:
                all_footprints.append(base_poly)
        for fl in mass_floors(mass, levels=levels, floor_height=floor_height):
            poly = Polygon(fl["outline"]).buffer(0)
            if not poly.is_empty:
                level_shapes.setdefault(float(fl["elevation"]), []).append(poly)

    floor_rows: list[dict[str, Any]] = []
    for idx, z in enumerate(sorted(level_shapes), 1):
        union_poly = unary_union(level_shapes[z])
        floor_rows.append(
            {
                "index": idx,
                "elevation": z,
                "elevation_m": round(z / 1000.0, 3),
                "area_m2": round(union_poly.area / 1e6, 4),
            }
        )

    gfa = round(sum(r["area_m2"] for r in floor_rows), 4)
    coverage = round(unary_union(all_footprints).area / 1e6, 4) if all_footprints else 0.0

    if plot_area_m2 is None and site is not None:
        from saengine.gis import plot as plot_geometry

        ring, _ = plot_geometry.plot_ring(site)
        if ring is not None:
            plot_area_m2 = abs(plot_geometry._polygon(ring).area) / 1e6

    far: float | None = None
    coverage_pct: float | None = None
    if plot_area_m2 is not None and plot_area_m2 > 0:
        far = round(gfa / plot_area_m2, 4)
        coverage_pct = round(coverage / plot_area_m2 * 100.0, 2)

    checks: list[dict[str, Any]] = []
    permitted_info: dict[str, Any] | None = None
    plan = getattr(getattr(site, "plot", None), "planning", None) if site is not None else None
    effective_use = (
        use
        or (plan.use if plan is not None else None)
        or next((m.use for m in masses if m.use), None)
    )
    effective_road = road_width_m or (
        plan.roadWidth / 1000.0 if plan is not None and plan.roadWidth else None
    )

    if plot_area_m2 and effective_use and effective_road:
        from saengine.gis import planning

        if planning.planning_table() is not None:
            permitted_info = planning.permitted(effective_use, plot_area_m2, effective_road)
            if permitted_info.get("allowed"):
                if far is not None:
                    checks.append(
                        planning._check(
                            "FAR",
                            far,
                            permitted_info["far"],
                            "",
                            permitted_info["rule"],
                        )
                    )
                if coverage_pct is not None:
                    checks.append(
                        planning._check(
                            "Ground coverage",
                            coverage_pct,
                            permitted_info["mgc"],
                            "%",
                            permitted_info["rule"],
                        )
                    )

    return {
        "floors": floor_rows,
        "floorCount": len(floor_rows),
        "grossFloorArea_m2": gfa,
        "groundCoverage_m2": coverage,
        "totalVolume_m3": round(total_volume, 4),
        "plotArea_m2": round(plot_area_m2, 4) if plot_area_m2 is not None else None,
        "far": far,
        "groundCoveragePercent": coverage_pct,
        "permitted": permitted_info,
        "checks": checks,
    }


def create_floors_from_mass(
    mass: ConceptualMass,
    *,
    floor_height: float | None = None,
    levels: Sequence[float] | None = None,
    story_prefix: str = "L",
) -> dict[str, Any]:
    """Generate floor-plan-ready storey definitions and slab/wall plan outlines from ``mass``."""
    floors = mass_floors(mass, levels=levels, floor_height=floor_height)
    stories: list[dict[str, Any]] = []
    outlines: list[dict[str, Any]] = []
    for idx, fl in enumerate(floors):
        story_id = f"{story_prefix}{idx}" if idx > 0 or story_prefix != "L" else "BASE"
        story_name = "Base" if story_id == "BASE" else f"Level {idx}"
        stories.append({"id": story_id, "name": story_name, "elevation": float(fl["elevation"])})
        outlines.append(
            {
                "story": story_id,
                "elevation": float(fl["elevation"]),
                "outline": fl["outline"],
                "area_m2": fl["area_m2"],
            }
        )
    top_elev = round(mass.baseElevation + mass.height, 6)
    if not stories or top_elev > stories[-1]["elevation"] + 1e-6:
        roof_idx = len(stories)
        stories.append(
            {
                "id": f"{story_prefix}{roof_idx}",
                "name": "Roof",
                "elevation": top_elev,
            }
        )
    return {
        "stories": stories,
        "floorOutlines": outlines,
        "grossFloorArea_m2": round(sum(fl["area_m2"] for fl in floors), 4),
    }


# ───────────────────────────── IFC export ─────────────────────────────


def _extrusion_profile(w: Any, ring: Sequence[tuple[float, float]], name: str) -> Any:
    from saengine.library.ifc import _SI

    pts = [(float(x) * _SI, float(y) * _SI) for x, y in ring]
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    return w.run("profile.add_arbitrary_profile", w.file, profile=pts, name=name)


def _assign_solid_geometry(
    w: Any,
    product: Any,
    kind: MassKind,
    *,
    base_elevation: float,
    height: float,
    outline: list[Point2] | None,
    origin: Point2 | None,
    width: float | None,
    depth: float | None,
    rotation: float,
    center: Point2 | None,
    radius: float | None,
    base_outline: list[Point2] | None,
    top_outline: list[Point2] | None,
    name: str,
) -> None:
    from saengine.library.ifc import _SI, _placement, _rotation

    if kind == "box":
        profile = w.rectangle(width or 0.0, depth or 0.0)
        w.extrusion(product, profile, height, None)
        ox, oy = (float(origin[0]), float(origin[1])) if origin else (0.0, 0.0)
        w.place(product, _placement((ox, oy, base_elevation), _rotation(rotation), (0.0, 0.0, 1.0)))
        return
    if kind == "cylinder":
        profile = w.param_profile("IfcCircleProfileDef")
        profile.Radius = float(radius or 0.0)
        w.extrusion(product, profile, height, None)
        cx, cy = (float(center[0]), float(center[1])) if center else (0.0, 0.0)
        w.place(product, _placement((cx, cy, base_elevation), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
        return
    if kind == "extrusion":
        ring = _ensure_ccw(outline or [])
        profile = _extrusion_profile(w, ring, name)
        w.extrusion(product, profile, height, None)
        w.place(product, _placement((0.0, 0.0, base_elevation), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
        return

    # loft: triangulated/polygonal closed mesh in SI metres
    base_ring, top_ring = _align_rings(base_outline or [], top_outline or [])
    n = len(base_ring)
    z0 = base_elevation * _SI
    z1 = (base_elevation + height) * _SI
    verts = [(x * _SI, y * _SI, z0) for x, y in base_ring] + [
        (x * _SI, y * _SI, z1) for x, y in top_ring
    ]
    faces: list[list[int]] = [
        list(reversed(range(n))),  # bottom cap (downward normal)
        list(range(n, 2 * n)),  # top cap (upward normal)
    ]
    for i in range(n):
        j = (i + 1) % n
        faces.append([i, j, n + j, n + i])
    rep = w.run(
        "geometry.add_mesh_representation",
        w.file,
        context=w.body,
        vertices=[verts],
        faces=[faces],
    )
    w.run("geometry.assign_representation", w.file, product=product, representation=rep)
    w.place(product, _placement((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)))


def export_masses_ifc(
    w: Any,
    arch: Architecture,
    ids: dict[str, str],
    skipped: list[str],
    pset: Any,
) -> None:
    """Export conceptual masses as ``IfcBuildingElementProxy`` (excluded from structure)."""
    if not arch.masses:
        return
    proxy_type = w.entity(
        "IfcBuildingElementProxyType", "ConceptualMass", "archtype:mass", "USERDEFINED"
    )
    proxy_type.Description = "Conceptual mass (non-structural)"
    for mass in arch.masses:
        product = w.entity("IfcBuildingElementProxy", mass.name, f"arch:{mass.id}", "USERDEFINED")
        product.Tag = mass.id
        product.ObjectType = "ConceptualMass"
        product.Description = f"{mass.kind} mass"
        _assign_solid_geometry(
            w,
            product,
            mass.kind,
            base_elevation=mass.baseElevation,
            height=mass.height,
            outline=mass.outline,
            origin=mass.origin,
            width=mass.width,
            depth=mass.depth,
            rotation=mass.rotation,
            center=mass.center,
            radius=mass.radius,
            base_outline=mass.baseOutline,
            top_outline=mass.topOutline,
            name=mass.id,
        )
        w.run(
            "spatial.assign_container",
            w.file,
            products=[product],
            relating_structure=w.building,
        )
        w.run(
            "type.assign_type",
            w.file,
            related_objects=[product],
            relating_type=proxy_type,
            should_map_representations=False,
        )
        vol = round(mass_volume_m3(mass), 4)
        floors = mass_floors(mass) if mass.floorHeight else []
        mass_props: dict[str, Any] = {
            "Id": mass.id,
            "Name": mass.name,
            "Kind": mass.kind,
            "BaseElevation_mm": float(mass.baseElevation),
            "Height_mm": float(mass.height),
            "Volume_m3": vol,
            "ExcludedFromStructure": True,
        }
        if floors:
            mass_props["FloorCount"] = len(floors)
            mass_props["GrossFloorArea_m2"] = round(sum(f["area_m2"] for f in floors), 4)
        m_pset = w.run("pset.add_pset", w.file, product=product, name="SAEngine_Mass")
        w.run("pset.edit_pset", w.file, pset=m_pset, properties=mass_props)
        pset(product, {"Id": mass.id, "Kind": "mass", "ExcludedFromStructure": True})
        ids[mass.id] = product.GlobalId


def export_in_place_ifc(
    w: Any,
    arch: Architecture,
    elevations: dict[str, float],
    storeys: dict[str, Any],
    storey_at: Any,
    ids: dict[str, str],
    skipped: list[str],
    pset: Any,
) -> None:
    """Export one-off in-place elements with their category's IFC class and parameters."""
    for elem in arch.inPlaceElements:
        if elem.story not in elevations:
            skipped.append(f"{elem.id}: no story '{elem.story}'")
            continue
        ifc_class = _DEFAULT_IFC_CLASS[elem.category]
        predefined = None if ifc_class == "IfcFlowTerminal" else "USERDEFINED"
        product = w.entity(ifc_class, elem.name, f"arch:{elem.id}", predefined)
        product.Tag = elem.id
        product.ObjectType = "InPlace"
        product.Description = elem.name
        base_z = elevations[elem.story] + elem.baseOffset
        _assign_solid_geometry(
            w,
            product,
            elem.geometry,
            base_elevation=base_z,
            height=elem.height,
            outline=elem.outline,
            origin=elem.origin,
            width=elem.width,
            depth=elem.depth,
            rotation=elem.rotation,
            center=elem.center,
            radius=elem.radius,
            base_outline=elem.baseOutline,
            top_outline=elem.topOutline,
            name=elem.id,
        )
        w.run(
            "spatial.assign_container",
            w.file,
            products=[product],
            relating_structure=storeys.get(elem.story) or storey_at(base_z),
        )
        ip_props = w.run("pset.add_pset", w.file, product=product, name="SAEngine_InPlace")
        w.run(
            "pset.edit_pset",
            w.file,
            pset=ip_props,
            properties={
                "Id": elem.id,
                "Name": elem.name,
                "Category": elem.category,
                "Weight_kg": float(elem.weight),
                "Material": elem.material,
                **elem.parameters,
            },
        )
        pset(
            product,
            {
                "Id": elem.id,
                "Kind": "inPlace",
                "Category": elem.category,
                "HostRoom": elem.hostRoom or "",
            },
        )
        ids[elem.id] = product.GlobalId

"""Clashes between the MEP models and the structure.

The structure is the IFC SAEngine exports from the building model
(:func:`saengine.library.ifc.export_ifc`, the same file the 3D view shows, with the openings of
the building model cut). Both models go into an IfcOpenShell geometry tree (the
``opencascade.trianglebvh`` backend), whose ``clash_intersection_many`` finds every MEP element
that intersects a structural element and ``clash_clearance_many`` (optional) every one closer
than a clearance.

A hard clash through a beam, slab or wall is *coordinated* when 07 MEP has a sleeve or opening in
that host where the service crosses it (its centre line within the opening) and large enough for
the service, or when it is in a shaft through that floor; otherwise it is a *clash*, and SAEngine
proposes a sleeve: in the host where the service's centre line crosses its mid-plane, the size of
the service's cross-section there (larger for a service crossing at a skew) with an allowance
each side, rounded up to 25 mm; round services get circular sleeves, others rectangular
openings. Services running along a member (crossing its mid-plane at less than about 17°) and
clashes with columns and foundations get no proposal: they are to be rerouted.

Units: mm in the results (IfcOpenShell's geometry is in metres).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.geom
import numpy as np
from shapely.geometry import MultiPoint, Point, Polygon

from saengine.library.bim import BeamElement, BuildingModel, SlabElement, WallElement
from saengine.library.mep import MepModel, Opening
from saengine.library.objects import ObjectLibrary
from saengine.mep.geometry import bounded_id
from saengine.mep.ifc_import import element_class, mep_elements, systems_of

TREE_BACKEND = "opencascade.trianglebvh"
#: IfcOpenShell's clash types.
CLASH_TYPES = {0: "protrusion", 1: "pierce", 2: "collision", 3: "clearance"}
STRUCTURAL_CLASSES = (
    "IfcBeam",
    "IfcColumn",
    "IfcSlab",
    "IfcWall",
    "IfcFooting",
    "IfcPile",
    "IfcMember",
    "IfcPlate",
    "IfcStair",
    "IfcStairFlight",
)
#: Least |cos| between a service and its host's normal for a sleeve to make sense (~17°).
MIN_CROSSING = 0.3
SLEEVE_STEP = 25.0


def _settings() -> Any:
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    return settings


@dataclass
class ServiceShape:
    """An MEP element's geometry: vertices [mm, world], centre, direction of its run (the
    principal axis of its vertices), and whether it is round."""

    vertices: np.ndarray
    centre: np.ndarray
    direction: np.ndarray
    is_round: bool


def service_shape(element: Any, ifc_class: str = "") -> ServiceShape | None:
    try:
        shape = ifcopenshell.geom.create_shape(_settings(), element)
    except Exception:  # noqa: BLE001 - elements without a body
        return None
    vertices = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3) * 1e3
    if len(vertices) < 4:
        return None
    lo, hi = vertices.min(axis=0), vertices.max(axis=0)
    centre = (lo + hi) / 2
    _, _, axes = np.linalg.svd(vertices - vertices.mean(axis=0), full_matrices=False)
    direction = axes[0] / np.linalg.norm(axes[0])
    a = np.cross(direction, [0.0, 0.0, 1.0])
    if np.linalg.norm(a) < 1e-6:
        a = np.cross(direction, [1.0, 0.0, 0.0])
    a /= np.linalg.norm(a)
    b = np.cross(direction, a)
    section = (vertices - centre) @ np.column_stack([a, b])
    hull = MultiPoint([tuple(p) for p in section]).convex_hull
    extent = np.ptp(section, axis=0)
    ratio = hull.area / max(float(extent[0] * extent[1]), 1e-9)
    is_round = "Pipe" in ifc_class or (
        ratio < 0.88 and abs(extent[0] - extent[1]) < 0.1 * max(extent)
    )
    return ServiceShape(vertices, centre, direction, bool(is_round))


def _round_up(value: float, step: float = SLEEVE_STEP) -> float:
    return math.ceil(value / step - 1e-9) * step


@dataclass
class Host:
    """A beam, slab or wall as a plane the service crosses: a point on its mid-plane, its unit
    normal, and how positions in it are measured."""

    id: str
    kind: str
    point: np.ndarray
    normal: np.ndarray
    axis: np.ndarray | None  # beam or wall: unit vector from start to end (plan)
    bottom: float  # beam: its bottom; wall: its bottom [mm]
    element: Any


def host_of(element: Any, types: dict[str, Any]) -> Host | None:
    object_type = types.get(element.type)
    if isinstance(element, BeamElement):
        depth = _depth(getattr(object_type, "profile", None))
        start = np.array([*element.start, 0.0])
        end = np.array([*element.end, 0.0])
        axis = (end - start) / np.linalg.norm(end - start)
        normal = np.array([-axis[1], axis[0], 0.0])
        point = np.array([*element.start, element.elevation - depth / 2])
        return Host(element.id, "beam", point, normal, axis, element.elevation - depth, element)
    if isinstance(element, SlabElement):
        thickness = float(getattr(object_type, "thickness", 0.0) or 0.0)
        point = np.array([*element.boundary[0], element.elevation - thickness / 2])
        return Host(element.id, "slab", point, np.array([0.0, 0.0, 1.0]), None, 0.0, element)
    if isinstance(element, WallElement):
        start = np.array([*element.start, 0.0])
        end = np.array([*element.end, 0.0])
        axis = (end - start) / np.linalg.norm(end - start)
        normal = np.array([-axis[1], axis[0], 0.0])
        point = np.array([*element.start, element.bottom])
        return Host(element.id, "wall", point, normal, axis, element.bottom, element)
    return None


def _depth(profile: Any) -> float:
    for attribute in ("yDim", "overallDepth", "depth"):
        value = getattr(profile, attribute, None)
        if value:
            return float(value)
    radius = getattr(profile, "radius", None)
    return 2 * float(radius) if radius else 0.0


def crossing(host: Host, shape: ServiceShape, allowance: float) -> dict[str, Any] | None:
    """Where the service's centre line crosses the host's mid-plane and the opening it needs
    there (without and with the ``allowance`` each side), or None when it runs along it."""
    cos = float(shape.direction @ host.normal)
    if abs(cos) < MIN_CROSSING:
        return None
    s = float((host.point - shape.centre) @ host.normal) / cos
    at = shape.centre + s * shape.direction
    q = shape.vertices - shape.centre
    q = q - np.outer(q @ shape.direction, shape.direction)
    vertical = np.array([0.0, 0.0, 1.0])
    if host.kind == "slab":
        u_axis, v_axis = np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
    else:
        assert host.axis is not None
        u_axis, v_axis = host.axis, vertical
    width = float(np.ptp(q @ u_axis)) / abs(cos)
    height = float(np.ptp(q @ v_axis))
    if host.kind == "slab":
        height /= abs(cos)
    result: dict[str, Any] = {"point": at, "width": width, "height": height}
    if host.kind == "slab":
        result["position"] = {"x": round(float(at[0]), 1), "y": round(float(at[1]), 1)}
    else:
        assert host.axis is not None
        along = float((at[:2] - host.element.start) @ host.axis[:2])
        if host.kind == "beam":
            result["position"] = {
                "distance": round(along, 1),
                "elevation": round(float(at[2]) - host.bottom, 1),
            }
        else:
            result["position"] = {"x": round(along, 1), "y": round(float(at[2]) - host.bottom, 1)}
    if shape.is_round:
        size = max(width, height)
        result["needed"] = {"shape": "circle", "diameter": round(size, 1)}
        result["sleeve"] = {"shape": "circle", "diameter": _round_up(size + 2 * allowance)}
    else:
        result["needed"] = {
            "shape": "rectangle",
            "width": round(width, 1),
            "height": round(height, 1),
        }
        result["sleeve"] = {
            "shape": "rectangle",
            "width": _round_up(width + 2 * allowance),
            "height": _round_up(height + 2 * allowance),
        }
    return result


def _matching_opening(
    host: Host, cross: dict[str, Any], openings: list[Opening]
) -> tuple[Opening | None, bool]:
    """The opening of 07 MEP in ``host`` the service passes through, and whether it is big
    enough for the service (without the allowance)."""
    position = cross["position"]
    for opening in openings:
        if opening.host != host.id:
            continue
        width, height = opening.size
        p = opening.position
        if host.kind == "beam":
            du = position["distance"] - float(p.distance or 0.0)
            dv = position["elevation"] - float(p.elevation or 0.0)
        else:
            du = position["x"] - float(p.x or 0.0)
            dv = position["y"] - float(p.y or 0.0)
        if opening.shape == "circle":
            inside = math.hypot(du, dv) <= width / 2 + 1.0
        else:
            inside = abs(du) <= width / 2 + 1.0 and abs(dv) <= height / 2 + 1.0
        if not inside:
            continue
        needed = cross["needed"]
        if needed["shape"] == "circle":
            need_w = need_h = needed["diameter"]
        else:
            need_w, need_h = needed["width"], needed["height"]
        if opening.shape == "circle":
            # the needed rectangle (or circle) fits in the circle
            big = (
                math.hypot(need_w, need_h) <= width + 1.0
                if needed["shape"] == "rectangle"
                else need_w <= width + 1.0
            )
        else:
            big = need_w <= width + 1.0 and need_h <= height + 1.0
        return opening, big
    return None, False


def _in_shaft(host: Host, cross: dict[str, Any], mep: MepModel, levels: dict[str, float]):
    if host.kind != "slab":
        return None
    point = Point(cross["position"]["x"], cross["position"]["y"])
    for shaft in mep.shafts:
        low, high = levels.get(shaft.fromStory), levels.get(shaft.toStory)
        if low is None or high is None:
            continue
        if not (low + 1.0 < host.element.elevation < high + 1.0):
            continue
        if Polygon([tuple(p) for p in shaft.outline]).buffer(1.0).contains(point):
            return shaft
    return None


def find_clashes(
    structure: ifcopenshell.file,
    building: BuildingModel,
    objects: ObjectLibrary,
    mep: MepModel,
    models: list[tuple[str, str, ifcopenshell.file]],
    clearance: float = 0.0,
    allowance: float = 25.0,
    tolerance: float = 0.002,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The clashes of the MEP ``models`` (``(path, discipline, file)``) with the structural
    IFC ``structure`` (exported from ``building``). ``clearance`` [mm] > 0 also reports MEP
    elements closer than that to the structure; ``allowance`` [mm] is the gap each side of a
    proposed sleeve; ``tolerance`` [m] the least intersection IfcOpenShell reports.

    Returns (clashes, notes); each clash ``{"id", "status" ("clash" or "coordinated"), "kind"
    ("hard" or "clearance"), "type" (IfcOpenShell's: "protrusion", "pierce", "collision",
    "clearance"), "depth" (mm of overlap, or the gap of a clearance clash), "point" [x, y, z] mm,
    "story", "mep" (its GlobalId), "mepName", "mepType" (IFC class), "system", "file",
    "discipline", "structural" (SAEngine id), "structuralKind", "structuralGlobalId", "size"
    (mm across the service where it crosses), "opening" (the 07 MEP opening or shaft it passes
    through), "sleeve" (the proposed opening, in mep.json's format, or None), "note"}``.
    """
    notes: list[str] = []
    tree = ifcopenshell.geom.tree(backend=TREE_BACKEND)
    settings = ifcopenshell.geom.settings()
    tree.add_iterator(ifcopenshell.geom.iterator(settings, structure, 1))
    structural = [e for c in STRUCTURAL_CLASSES for e in structure.by_type(c)]
    sources: dict[str, tuple[str, str]] = {}
    services: list[Any] = []
    for path, discipline, model in models:
        elements = mep_elements(model)
        if not elements:
            notes.append(f"{path}: no MEP (distribution) elements")
            continue
        tree.add_iterator(ifcopenshell.geom.iterator(settings, model, 1, include=elements))
        for element in elements:
            sources.setdefault(element.GlobalId, (path, discipline))
        services.extend(elements)
    if not services or not structural:
        return [], notes

    elements = {e.id: e for e in building.elements}
    types = {o.id: o for o in objects.objects}
    levels = {s.id: s.elevation for s in building.stories}
    stories = sorted(building.stories, key=lambda s: s.elevation)

    def structural_id(product: Any) -> str:
        return product.Tag or product.Name or product.GlobalId

    structural_ids = {e.GlobalId for e in structural}

    def oriented(clashes: Any) -> list[tuple[Any, Any, Any]]:
        # IfcOpenShell does not keep the (a, b) order of the two sets: decide which side is the
        # service by its GlobalId, and keep each (service, structure) pair once.
        pairs: dict[tuple[str, str], tuple[Any, Any, Any]] = {}
        for c in clashes:
            a, b = c.a, c.b
            if a.GlobalId in sources and b.GlobalId in structural_ids:
                service, product = a, b
            elif b.GlobalId in sources and a.GlobalId in structural_ids:
                service, product = b, a
            else:
                continue  # service vs service, or structure vs structure
            pairs.setdefault((service.GlobalId, product.GlobalId), (service, product, c))
        return list(pairs.values())

    found = oriented(tree.clash_intersection_many(services, structural, tolerance, True))
    if clearance > 0:
        hard = {(s.GlobalId, p.GlobalId) for s, p, _ in found}
        found += [
            item
            for item in oriented(
                tree.clash_clearance_many(services, structural, clearance / 1e3, False)
            )
            if (item[0].GlobalId, item[1].GlobalId) not in hard
        ]
    shapes: dict[str, ServiceShape | None] = {}
    results: list[dict[str, Any]] = []
    suggested = 0
    taken = {o.id for o in mep.openings} | {x.id for x in mep.equipment} | set(elements)
    for k, (service, product, clash) in enumerate(found, start=1):
        ifc_class = element_class(service)
        location = (np.array(clash.p1) + np.array(clash.p2)) / 2 * 1e3
        story = next(
            (s.id for s in reversed(stories) if s.elevation <= location[2] + 1.0),
            stories[0].id if stories else None,
        )
        path, discipline = sources.get(service.GlobalId, ("", ""))
        sid = structural_id(product)
        element = elements.get(sid)
        kind = getattr(element, "kind", product.is_a().replace("Ifc", "").lower())
        level = getattr(element, "elevation", None)
        if isinstance(element, BeamElement | SlabElement) and level is not None:
            # A floor's beams and slabs belong to the story they carry.
            story = next((s.id for s in stories if abs(s.elevation - level) < 1.0), story)
        clash_type = CLASH_TYPES.get(int(clash.clash_type), str(clash.clash_type))
        entry: dict[str, Any] = {
            "id": f"X{k}",
            "status": "clash",
            "kind": "clearance" if clash_type == "clearance" else "hard",
            "type": clash_type,
            "depth": round(float(clash.distance) * 1e3, 1),
            "point": [round(float(v), 1) for v in location],
            "story": story,
            "mep": service.GlobalId,
            "mepName": service.Name or "",
            "mepType": ifc_class,
            "system": ", ".join(systems_of(service)),
            "file": path,
            "discipline": discipline,
            "structural": sid,
            "structuralKind": kind,
            "structuralGlobalId": product.GlobalId,
            "size": None,
            "opening": None,
            "sleeve": None,
            "note": "",
        }
        results.append(entry)
        if clash_type == "clearance":
            entry["note"] = f"{entry['depth']:.0f} mm from {sid}"
            continue
        host = host_of(element, types) if element is not None else None
        if host is None:
            entry["note"] = f"cuts {kind} {sid}: reroute (no openings in {kind}s)"
            continue
        if service.GlobalId not in shapes:
            shapes[service.GlobalId] = service_shape(service, ifc_class)
        shape = shapes[service.GlobalId]
        cross = crossing(host, shape, allowance) if shape is not None else None
        if cross is None:
            entry["note"] = f"runs along {host.kind} {sid}: reroute"
            continue
        needed = cross["needed"]
        entry["size"] = needed.get("diameter") or max(needed["width"], needed["height"])
        shaft = _in_shaft(host, cross, mep, levels)
        if shaft is not None:
            entry["status"], entry["opening"] = "coordinated", shaft.id
            entry["note"] = f"in shaft {shaft.id}"
            continue
        opening, big = _matching_opening(host, cross, mep.openings)
        if opening is not None:
            entry["opening"] = opening.id
            if big:
                entry["status"] = "coordinated"
                entry["note"] = f"through {opening.id}"
                continue
            entry["note"] = f"{opening.id} is too small for it"
        suggested += 1
        new_id = bounded_id(f"OP-{sid}", f"-{suggested}")
        while new_id in taken:
            suggested += 1
            new_id = bounded_id(f"OP-{sid}", f"-{suggested}")
        taken.add(new_id)
        sleeve = cross["sleeve"]
        entry["sleeve"] = {
            "id": new_id,
            "host": sid,
            "kind": "sleeve" if sleeve["shape"] == "circle" else "opening",
            **sleeve,
            "position": cross["position"],
            "service": " ".join(x for x in (ifc_class.replace("Ifc", ""), service.Name or "") if x),
        }
    return results, notes


def structural_ifc(
    project_root: str | Path, architecture: bool = False
) -> tuple[ifcopenshell.file, BuildingModel, Any, Any]:
    """The structural IFC of the project (as the 3D view exports it), with the building model,
    its object library and materials. With ``architecture`` the floor plan's architecture
    (``05 Floor Plan/architecture.json``, its elements carrying ``SAEngine_Architecture``) is in
    the file too, for the multi-discipline clash tests."""
    from saengine.library.bim import BuildingModel
    from saengine.library.ifc import export_ifc
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary
    from saengine.library.settings import ProjectSettings
    from saengine.substructure.handover import authoritative_substructure

    root = Path(project_root)

    def read(relative: str) -> str:
        try:
            return (root / relative).read_text(encoding="utf-8")
        except OSError as error:
            raise ValueError(f"{relative} could not be read: {error}") from error

    building = BuildingModel.model_validate_json(read("06 BIM/bim.json"))
    objects = ObjectLibrary.model_validate_json(read("04 Objects/objects.json"))
    materials = MaterialLibrary.model_validate_json(read("03 Materials/materials.json"))
    ground = 0.0
    try:
        settings = ProjectSettings.model_validate_json(
            read("02 Project Settings/project-settings.json")
        )
        ground = settings.foundation.groundLevel
    except ValueError:
        pass
    try:
        substructure_text = (root / "09 Substructure" / "substructure.json").read_text("utf-8")
    except OSError:
        substructure_text = None
    substructure = authoritative_substructure(substructure_text, building)
    arch = None
    if architecture:
        from saengine.library.architecture import ARCHITECTURE_FILE
        from saengine.library.architecture import parse as parse_architecture

        try:
            arch_text = (root / ARCHITECTURE_FILE).read_text(encoding="utf-8")
        except OSError:
            arch_text = None
        arch = parse_architecture(arch_text) if arch_text else None
    ifc, _, _ = export_ifc(
        building, objects, materials, root.name, substructure, ground, architecture=arch
    )
    return ifc, building, objects, materials


def open_models(
    project_root: str | Path, mep: MepModel
) -> tuple[list[tuple[str, str, ifcopenshell.file]], list[str]]:
    """The MEP IFC models of ``mep`` that can be read, and notes on those that cannot."""
    root = Path(project_root)
    models, notes = [], []
    for model in mep.ifcModels:
        path = Path(model.path)
        full = path if path.is_absolute() else root / path
        try:
            models.append((model.path, model.discipline, ifcopenshell.open(str(full))))
        except Exception as error:  # noqa: BLE001 - IfcOpenShell raises several kinds
            notes.append(f"{model.path}: could not be read ({error})")
    return models, notes

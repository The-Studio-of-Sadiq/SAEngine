"""IFC export of the building model with IfcOpenShell.

Every element of ``06 BIM/bim.json`` becomes an IFC element (IfcColumn, IfcBeam, IfcWall,
IfcSlab, IfcFooting) in its IfcBuildingStorey, with an extruded body built from its object
type's section: SAEngine's profiles are IFC's parameterised profiles (IfcRectangleProfileDef,
IfcIShapeProfileDef, ...), so they map one to one. Units are millimetres.

GlobalIds are derived from the element ids, so the same element keeps its GlobalId from one
export to the next (IFC diffs and BCF issues stay attached). The workbench's 3D view loads the
same file, and uses the returned id → GlobalId map to link the view with the project.
"""

from __future__ import annotations

import math
import uuid
from typing import Any

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.guid
import numpy as np

from saengine.library.bim import (
    BeamElement,
    BuildingModel,
    ColumnElement,
    FootingElement,
    SlabElement,
    WallElement,
)
from saengine.library.materials import MaterialLibrary
from saengine.library.objects import ObjectLibrary

_NAMESPACE = uuid.UUID("6c1d1f7e-5a2b-4d3e-9b8f-5ae0e1f1c0de")

# IfcOpenShell geometry helpers take SI lengths (metres); the model is in millimetres.
_SI = 0.001

# IFC class (and predefined type) of each element kind.
_CLASSES = {
    "column": ("IfcColumn", "COLUMN"),
    "beam": ("IfcBeam", "BEAM"),
    "wall": ("IfcWall", "STANDARD"),
    "slab": ("IfcSlab", "FLOOR"),
    "footing": ("IfcFooting", "PAD_FOOTING"),
}

# SAEngine profile -> IFC profile class and attributes (fillets only when non-zero).
_PROFILES = {
    "rectangle": ("IfcRectangleProfileDef", {"xDim": "XDim", "yDim": "YDim"}),
    "circle": ("IfcCircleProfileDef", {"radius": "Radius"}),
    "rectangleHollow": (
        "IfcRectangleHollowProfileDef",
        {
            "xDim": "XDim",
            "yDim": "YDim",
            "wallThickness": "WallThickness",
            "outerFilletRadius": "OuterFilletRadius",
        },
    ),
    "circleHollow": (
        "IfcCircleHollowProfileDef",
        {"radius": "Radius", "wallThickness": "WallThickness"},
    ),
    "I": (
        "IfcIShapeProfileDef",
        {
            "overallWidth": "OverallWidth",
            "overallDepth": "OverallDepth",
            "webThickness": "WebThickness",
            "flangeThickness": "FlangeThickness",
            "filletRadius": "FilletRadius",
        },
    ),
    "T": (
        "IfcTShapeProfileDef",
        {
            "depth": "Depth",
            "flangeWidth": "FlangeWidth",
            "webThickness": "WebThickness",
            "flangeThickness": "FlangeThickness",
            "filletRadius": "FilletRadius",
        },
    ),
    "L": (
        "IfcLShapeProfileDef",
        {
            "depth": "Depth",
            "width": "Width",
            "thickness": "Thickness",
            "filletRadius": "FilletRadius",
            "edgeRadius": "EdgeRadius",
        },
    ),
    "U": (
        "IfcUShapeProfileDef",
        {
            "depth": "Depth",
            "flangeWidth": "FlangeWidth",
            "webThickness": "WebThickness",
            "flangeThickness": "FlangeThickness",
            "filletRadius": "FilletRadius",
        },
    ),
}


def global_id(key: str) -> str:
    """A stable IFC GlobalId for ``key`` (an element id, "project", "storey:L1", ...)."""
    return ifcopenshell.guid.compress(uuid.uuid5(_NAMESPACE, key).hex)


def _placement(
    origin: tuple[float, float, float],
    x_axis: tuple[float, float, float],
    z_axis: tuple[float, float, float],
) -> np.ndarray:
    """A 4x4 placement: local X and Z axes (unit vectors), Y = Z x X, at ``origin``."""
    x = np.array(x_axis, dtype=float)
    z = np.array(z_axis, dtype=float)
    y = np.cross(z, x)
    matrix = np.eye(4)
    matrix[:3, 0], matrix[:3, 1], matrix[:3, 2], matrix[:3, 3] = x, y, z, origin
    return matrix


def _rotation(degrees: float) -> tuple[float, float, float]:
    angle = math.radians(degrees)
    return (math.cos(angle), math.sin(angle), 0.0)


class _Writer:
    def __init__(
        self, name: str, objects: ObjectLibrary, materials: MaterialLibrary | None
    ) -> None:
        self.run = ifcopenshell.api.run
        self.file = ifcopenshell.api.run("project.create_file", version="IFC4")
        self.types = {o.id: o for o in objects.objects}
        self.material_names = {m.id: m.name for m in (materials.materials if materials else [])}
        self.materials: dict[str, Any] = {}
        self.profiles: dict[str, Any] = {}

        self.project = self.entity("IfcProject", name, "project")
        self.run("unit.assign_unit", self.file, length={"is_metric": True, "raw": "MILLIMETERS"})
        model = self.run("context.add_context", self.file, context_type="Model")
        self.body = self.run(
            "context.add_context",
            self.file,
            context_type="Model",
            context_identifier="Body",
            target_view="MODEL_VIEW",
            parent=model,
        )
        self.site = self.entity("IfcSite", "Site", "site")
        self.building = self.entity("IfcBuilding", name, "building")
        self.run(
            "aggregate.assign_object", self.file, products=[self.site], relating_object=self.project
        )
        self.run(
            "aggregate.assign_object",
            self.file,
            products=[self.building],
            relating_object=self.site,
        )
        for spatial in (self.site, self.building):
            self.run("geometry.edit_object_placement", self.file, product=spatial)

    def entity(self, ifc_class: str, name: str, key: str, predefined: str | None = None) -> Any:
        entity = self.run(
            "root.create_entity",
            self.file,
            ifc_class=ifc_class,
            name=name,
            predefined_type=predefined,
        )
        entity.GlobalId = global_id(key)
        return entity

    def place(self, product: Any, matrix: np.ndarray) -> None:
        self.run(
            "geometry.edit_object_placement", self.file, product=product, matrix=matrix, is_si=False
        )

    def profile(self, type_id: str, profile: Any) -> Any:
        if type_id not in self.profiles:
            ifc_class, attributes = _PROFILES[profile.shape]
            ifc_profile = self.run(
                "profile.add_parameterized_profile", self.file, ifc_class=ifc_class
            )
            ifc_profile.ProfileName = type_id
            for source, target in attributes.items():
                value = getattr(profile, source)
                if value:
                    setattr(ifc_profile, target, float(value))
            self.profiles[type_id] = ifc_profile
        return self.profiles[type_id]

    def rectangle(self, x: float, y: float) -> Any:
        ifc_profile = self.run(
            "profile.add_parameterized_profile", self.file, ifc_class="IfcRectangleProfileDef"
        )
        ifc_profile.XDim, ifc_profile.YDim = float(x), float(y)
        return ifc_profile

    def material(self, product: Any, material_id: str) -> None:
        if material_id not in self.materials:
            self.materials[material_id] = self.run(
                "material.add_material",
                self.file,
                name=self.material_names.get(material_id, material_id),
            )
        self.run(
            "material.assign_material",
            self.file,
            products=[product],
            material=self.materials[material_id],
        )

    def extrusion(
        self, product: Any, profile: Any, depth: float, cardinal: int | str | None = 5
    ) -> None:
        representation = self.run(
            "geometry.add_profile_representation",
            self.file,
            context=self.body,
            profile=profile,
            depth=float(depth) * _SI,
            cardinal_point=cardinal,
        )
        self.run(
            "geometry.assign_representation",
            self.file,
            product=product,
            representation=representation,
        )


def export_ifc(
    building: BuildingModel,
    objects: ObjectLibrary,
    materials: MaterialLibrary | None = None,
    name: str = "Project",
) -> tuple[ifcopenshell.file, dict[str, str], list[str]]:
    """The IFC file of ``building``, its element id -> GlobalId map, and elements left out (why)."""
    w = _Writer(name, objects, materials)
    storeys: list[tuple[float, Any]] = []
    for story in sorted(building.stories, key=lambda s: s.elevation):
        storey = w.entity("IfcBuildingStorey", story.name, f"storey:{story.id}")
        storey.Elevation = float(story.elevation)
        w.run("aggregate.assign_object", w.file, products=[storey], relating_object=w.building)
        w.place(storey, _placement((0, 0, story.elevation), (1, 0, 0), (0, 0, 1)))
        storeys.append((story.elevation, storey))

    def storey_at(elevation: float) -> Any:
        """The storey an element at ``elevation`` belongs to: the highest one not above it."""
        below = [s for e, s in storeys if e <= elevation + 1e-6]
        return below[-1] if below else (storeys[0][1] if storeys else w.building)

    ids: dict[str, str] = {}
    skipped: list[str] = []
    for element in building.elements:
        object_type = w.types.get(element.type)
        if object_type is None:
            skipped.append(f"{element.id}: unknown object type '{element.type}'")
            continue
        ifc_class, predefined = _CLASSES[element.kind]
        if element.kind == "footing" and object_type.kind == "pileCap":
            predefined = "PILE_CAP"
        product = w.entity(ifc_class, element.id, element.id, predefined)
        product.ObjectType = object_type.id
        product.Description = object_type.name
        product.Tag = element.id

        if isinstance(element, ColumnElement):
            w.extrusion(
                product,
                w.profile(object_type.id, object_type.profile),
                element.top - element.bottom,
            )
            w.place(
                product,
                _placement(
                    (*element.position, element.bottom), _rotation(element.rotation), (0, 0, 1)
                ),
            )
            container = storey_at(element.bottom)
        elif isinstance(element, BeamElement):
            (x1, y1), (x2, y2) = element.start, element.end
            length = math.hypot(x2 - x1, y2 - y1)
            direction = ((x2 - x1) / length, (y2 - y1) / length, 0.0)
            # Profile Y up, extruded along the beam, its top centre on the story level.
            w.extrusion(
                product, w.profile(object_type.id, object_type.profile), length, "top centre"
            )
            w.place(
                product,
                _placement(
                    (x1, y1, element.elevation), (-direction[1], direction[0], 0.0), direction
                ),
            )
            container = storey_at(element.elevation)
        elif isinstance(element, WallElement):
            (x1, y1), (x2, y2) = element.start, element.end
            length = math.hypot(x2 - x1, y2 - y1)
            thickness = float(object_type.thickness)
            representation = w.run(
                "geometry.add_wall_representation",
                w.file,
                context=w.body,
                length=length * _SI,
                height=(element.top - element.bottom) * _SI,
                thickness=thickness * _SI,
                offset=-thickness / 2 * _SI,
            )
            w.run(
                "geometry.assign_representation",
                w.file,
                product=product,
                representation=representation,
            )
            w.place(
                product,
                _placement(
                    (x1, y1, element.bottom),
                    ((x2 - x1) / length, (y2 - y1) / length, 0.0),
                    (0, 0, 1),
                ),
            )
            container = storey_at(element.bottom)
        elif isinstance(element, SlabElement):
            thickness = float(object_type.thickness)
            points = [(float(x) * _SI, float(y) * _SI) for x, y in element.boundary]
            outline = w.run(
                "profile.add_arbitrary_profile",
                w.file,
                profile=[*points, points[0]],
                name=element.id,
            )
            w.extrusion(product, outline, thickness, None)  # the outline is in absolute x, y
            w.place(
                product, _placement((0, 0, element.elevation - thickness), (1, 0, 0), (0, 0, 1))
            )
            container = storey_at(element.elevation)
        elif isinstance(element, FootingElement):
            thickness = float(object_type.thickness)
            w.extrusion(product, w.rectangle(object_type.length, object_type.width), thickness)
            w.place(
                product,
                _placement(
                    (*element.position, element.elevation - thickness),
                    _rotation(element.rotation),
                    (0, 0, 1),
                ),
            )
            container = storey_at(element.elevation)
        else:  # pragma: no cover - the element union is closed
            continue

        w.run("spatial.assign_container", w.file, products=[product], relating_structure=container)
        w.material(product, object_type.material)
        ids[element.id] = product.GlobalId
    return w.file, ids, skipped

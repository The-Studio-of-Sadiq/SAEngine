"""IFC export of the building model with IfcOpenShell.

Every element of ``06 BIM/bim.json`` becomes an IFC element (IfcColumn, IfcBeam, IfcWall,
IfcSlab, IfcFooting) in its IfcBuildingStorey, with an extruded body built from its object
type's section: SAEngine's profiles are IFC's parameterised profiles (IfcRectangleProfileDef,
IfcIShapeProfileDef, ...), so they map one to one. The foundations of 9 Substructure (IfcFooting,
IfcPile, a raft as an IfcSlab BASESLAB) replace the building model's footings once it is no
longer the placeholder. The coordination model of 7 MEP adds its equipment (IfcTank, IfcPump,
IfcChiller, IfcUnitaryEquipment, IfcElectricGenerator, IfcTransformer, IfcTransportElement, else
IfcBuildingElementProxy) on its plinths (IfcBuildingElementProxy "Plinth"), and its sleeves,
openings and shafts as IfcOpeningElements voiding their beams, slabs and walls. Units are
millimetres.

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
    AreaElement,
    BeamElement,
    BlockElement,
    BuildingModel,
    ColumnElement,
    FootingElement,
    MemberElement,
    SlabElement,
    WallElement,
    foundation_solids,
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
    substructure: Any = None,
    ground_level: float = 0.0,
    mep: Any = None,
) -> tuple[ifcopenshell.file, dict[str, str], list[str]]:
    """The IFC file of ``building``, its element id -> GlobalId map, and elements left out (why).

    With ``substructure`` (the project's ``substructure.json`` once it is no longer the
    placeholder, see :func:`saengine.substructure.handover.authoritative_substructure`) the
    foundations are its footings, pile caps, piles, rafts and tie beams (foundations without a
    founding level found 1.5 m below ``ground_level``), and the footings of the building model
    are left out; without it the building model's footings are exported. With ``mep`` (the
    :class:`saengine.library.mep.MepModel` of ``07 MEP/mep.json``) its equipment, plinths,
    sleeves, openings and shafts are added (:func:`_export_mep`)."""
    if mep is not None:
        from saengine.mep.loads import with_mep_openings

        building, _ = with_mep_openings(building, mep)  # shafts and slab and wall openings
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
    products: dict[str, Any] = {}
    skipped: list[str] = []
    for element in building.elements:
        if isinstance(element, FootingElement) and substructure is not None:
            continue  # superseded by the foundations of 9 Substructure: not a problem to report
        object_type = w.types.get(element.type)
        if object_type is None:
            skipped.append(f"{element.id}: unknown object type '{element.type}'")
            continue
        if isinstance(element, MemberElement):
            _member(
                w,
                element.id,
                element.type,
                element.start,
                element.end,
                element.rotation,
                storey_at,
                ids,
                skipped,
            )
            continue
        if isinstance(element, AreaElement):
            _area(w, element, storey_at, ids, skipped)
            continue
        if isinstance(element, BlockElement):
            _block(w, element, storey_at, ids, skipped)
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
        products[element.id] = product

    _export_additions(w, building, products, storey_at, ids, skipped)
    if substructure is not None:
        _export_foundations(w, building, substructure, ground_level, storey_at, ids, skipped)
    if mep is not None:
        _export_mep(w, building, mep, products, storey_at, ids, skipped)
    return w.file, ids, skipped


#: IFC4 classes of the equipment kinds of 7 MEP (class, predefined type).
_EQUIPMENT_CLASSES: dict[str, tuple[str, str | None]] = {
    "tank": ("IfcTank", "STORAGE"),
    "chiller": ("IfcChiller", "WATERCOOLED"),
    "ahu": ("IfcUnitaryEquipment", "AIRHANDLER"),
    "pump": ("IfcPump", "ENDSUCTION"),
    "generator": ("IfcElectricGenerator", "ENGINEGENERATOR"),
    "transformer": ("IfcTransformer", "VOLTAGE"),
    "lift": ("IfcTransportElement", "ELEVATOR"),
}
#: Height drawn for equipment that gives none [mm].
_EQUIPMENT_HEIGHT = 1500.0


def _profile_extent(profile: Any) -> tuple[float, float]:
    """(width, depth) of a profile [mm]."""
    from saengine.library.sections import profile_geometry

    xmin, xmax, ymin, ymax = profile_geometry(profile).calculate_extents()
    return float(xmax - xmin), float(ymax - ymin)


def _export_mep(
    w: _Writer,
    building: BuildingModel,
    mep: Any,
    products: dict[str, Any],
    storey_at: Any,
    ids: dict[str, str],
    skipped: list[str],
) -> None:
    """The equipment of 7 MEP on its plinths, and its sleeves and openings through beams, slabs
    and walls (shafts and slab and wall openings are already in ``building``'s additions)."""
    levels = {s.id: s.elevation for s in building.stories}
    elements = {e.id: e for e in building.elements}
    for item in mep.equipment:
        if item.story not in levels:
            skipped.append(f"{item.id}: no story '{item.story}'")
            continue
        floor = levels[item.story]
        axis = _rotation(item.rotation)
        plinth = item.plinth.height if item.plinth is not None else 0.0
        if item.plinth is not None and plinth > 0:
            base = w.entity("IfcBuildingElementProxy", f"{item.id} plinth", f"plinth:{item.id}")
            base.ObjectType = "Plinth"
            base.Description = f"Concrete plinth of {item.name or item.id}"
            w.extrusion(base, w.rectangle(item.length, item.width), plinth)
            w.place(base, _placement((item.x, item.y, floor), axis, (0, 0, 1)))
            w.run(
                "spatial.assign_container",
                w.file,
                products=[base],
                relating_structure=storey_at(floor),
            )
            w.material(base, item.plinth.material)
            ids[f"{item.id}/plinth"] = base.GlobalId
        ifc_class, predefined = _EQUIPMENT_CLASSES.get(
            item.kind, ("IfcBuildingElementProxy", "ELEMENT")
        )
        product = w.entity(ifc_class, item.name or item.id, f"equipment:{item.id}", predefined)
        product.ObjectType = item.kind
        product.Tag = item.id
        product.Description = f"{item.operatingWeight:g} kN operating" + (
            f", {item.emptyWeight:g} kN empty" if item.emptyWeight is not None else ""
        )
        w.extrusion(product, w.rectangle(item.length, item.width), item.height or _EQUIPMENT_HEIGHT)
        w.place(product, _placement((item.x, item.y, floor + plinth), axis, (0, 0, 1)))
        w.run(
            "spatial.assign_container",
            w.file,
            products=[product],
            relating_structure=storey_at(floor),
        )
        ids[item.id] = product.GlobalId

    for opening in mep.openings:
        host_element, host = elements.get(opening.host), products.get(opening.host)
        if host_element is None or host is None:
            skipped.append(f"{opening.id}: there is no beam, slab or wall '{opening.host}' to cut")
            continue
        if opening.kind == "opening" and isinstance(host_element, SlabElement | WallElement):
            continue  # cut with the building model's additions above
        width, height = opening.size
        if opening.shape == "circle":
            profile = w.run(
                "profile.add_parameterized_profile", w.file, ifc_class="IfcCircleProfileDef"
            )
            profile.Radius = width / 2
        else:
            profile = w.rectangle(width, height)
        p = opening.position
        object_type = w.types.get(host_element.type)
        if isinstance(host_element, BeamElement) and p.distance is not None and object_type:
            (x1, y1), (x2, y2) = host_element.start, host_element.end
            length = math.hypot(x2 - x1, y2 - y1)
            dx, dy = (x2 - x1) / length, (y2 - y1) / length
            beam_width, depth = _profile_extent(object_type.profile)
            half = beam_width / 2 + _CLEARANCE
            centre = (
                x1 + dx * p.distance,
                y1 + dy * p.distance,
                host_element.elevation - depth + float(p.elevation or 0.0),
            )
            across = (dy, -dx, 0.0)  # local Z through the beam, local Y up
            origin = (centre[0] - across[0] * half, centre[1] - across[1] * half, centre[2])
            matrix = _placement(origin, (dx, dy, 0.0), across)
            through = 2 * half
        elif isinstance(host_element, SlabElement) and p.x is not None and object_type:
            thickness = float(object_type.thickness)
            matrix = _placement(
                (p.x, p.y, host_element.elevation - thickness - _CLEARANCE), (1, 0, 0), (0, 0, 1)
            )
            through = thickness + 2 * _CLEARANCE
        elif isinstance(host_element, WallElement) and p.x is not None and object_type:
            (x1, y1), (x2, y2) = host_element.start, host_element.end
            length = math.hypot(x2 - x1, y2 - y1)
            dx, dy = (x2 - x1) / length, (y2 - y1) / length
            half = float(object_type.thickness) / 2 + _CLEARANCE
            origin = (
                x1 + dx * p.x - dy * half,
                y1 + dy * p.x + dx * half,
                host_element.bottom + float(p.y or 0.0),
            )
            matrix = _placement(origin, (dx, dy, 0.0), (dy, -dx, 0.0))
            through = 2 * half
        else:
            skipped.append(f"{opening.id}: its position does not suit its host '{opening.host}'")
            continue
        void = w.entity("IfcOpeningElement", opening.id, f"mep:{opening.id}", "OPENING")
        void.Description = opening.service or opening.kind
        w.extrusion(void, profile, through)
        w.place(void, matrix)
        w.run("feature.add_feature", w.file, feature=void, element=host)
        ids[opening.id] = void.GlobalId


# Openings cut a little beyond their host's faces, so the boolean leaves no skin.
_CLEARANCE = 10.0

_MEMBER_CLASSES = {
    "brace": ("IfcMember", "BRACE"),
    "beam": ("IfcBeam", "BEAM"),
    "column": ("IfcColumn", "COLUMN"),
}


def _export_additions(
    w: _Writer,
    building: BuildingModel,
    products: dict[str, Any],
    storey_at: Any,
    ids: dict[str, str],
    skipped: list[str],
) -> None:
    """Openings (voiding their hosts), stairs and inclined members the building model adds."""
    elements = {e.id: e for e in building.elements}
    levels = {s.id: s.elevation for s in building.stories}
    additions = building.additions

    for o in additions.slabOpenings:
        slab, host = elements.get(o.host), products.get(o.host)
        if not isinstance(slab, SlabElement) or host is None:
            skipped.append(f"{o.id}: there is no slab '{o.host}' to cut")
            continue
        thickness = float(w.types[slab.type].thickness)
        opening = w.entity("IfcOpeningElement", o.id, o.id, "OPENING")
        w.extrusion(opening, w.rectangle(o.xDim, o.yDim), thickness + 2 * _CLEARANCE)
        w.place(
            opening,
            _placement(
                (o.x, o.y, slab.elevation - thickness - _CLEARANCE),
                _rotation(o.rotation),
                (0, 0, 1),
            ),
        )
        w.run("feature.add_feature", w.file, feature=opening, element=host)
        ids[o.id] = opening.GlobalId

    for o in additions.wallOpenings:
        wall, host = elements.get(o.host), products.get(o.host)
        if not isinstance(wall, WallElement) or host is None:
            skipped.append(f"{o.id}: there is no wall '{o.host}' to cut")
            continue
        (x1, y1), (x2, y2) = wall.start, wall.end
        length = math.hypot(x2 - x1, y2 - y1)
        dx, dy = (x2 - x1) / length, (y2 - y1) / length
        half = float(w.types[wall.type].thickness) / 2 + _CLEARANCE
        # Local X along the wall, Y up, extruded through the wall from its far face.
        origin = (
            x1 + dx * o.offset - dy * half,
            y1 + dy * o.offset + dx * half,
            wall.bottom + o.sill,
        )
        opening = w.entity("IfcOpeningElement", o.id, o.id, "OPENING")
        w.extrusion(opening, w.rectangle(o.width, o.height), 2 * half, "bottom left")
        w.place(opening, _placement(origin, (dx, dy, 0.0), (dy, -dx, 0.0)))
        w.run("feature.add_feature", w.file, feature=opening, element=host)
        ids[o.id] = opening.GlobalId

    for stair in additions.stairs:
        object_type = w.types.get(stair.type)
        if (
            object_type is None
            or object_type.kind != "staircase"
            or stair.base not in levels
            or stair.top not in levels
        ):
            skipped.append(f"{stair.id}: needs a staircase type and two stories")
            continue
        bottom, top = levels[stair.base], levels[stair.top]
        rise = top - bottom
        if rise <= 0:
            skipped.append(f"{stair.id}: its top story must be above its base story")
            continue
        n = max(1, round(rise / object_type.riser))
        riser, going = rise / n, float(object_type.tread)
        # The flight in its own plane: steps on top, a waist slab parallel to the pitch below.
        drop = float(object_type.waistThickness) * math.hypot(riser, going) / going
        foot = drop * going / riser
        points = [(0.0, 0.0)]
        for i in range(n):
            points += [(i * going, (i + 1) * riser), ((i + 1) * going, (i + 1) * riser)]
        points += [(n * going, n * riser - drop), (min(foot, n * going), 0.0)]
        outline = w.run(
            "profile.add_arbitrary_profile",
            w.file,
            profile=[*((x * _SI, y * _SI) for x, y in points), (0.0, 0.0)],
            name=stair.id,
        )
        product = w.entity("IfcStair", stair.id, stair.id, "STRAIGHT_RUN_STAIR")
        product.ObjectType = object_type.id
        product.Description = object_type.name
        width = float(object_type.flightWidth)
        run = _rotation(stair.direction)
        across = (run[1], -run[0], 0.0)  # local Z: X (the run) x Y (up)
        w.extrusion(product, outline, width, None)
        w.place(
            product,
            _placement(
                (stair.x - across[0] * width / 2, stair.y - across[1] * width / 2, bottom),
                run,
                across,
            ),
        )
        w.run(
            "spatial.assign_container",
            w.file,
            products=[product],
            relating_structure=storey_at(bottom),
        )
        w.material(product, object_type.material)
        ids[stair.id] = product.GlobalId

    for member in additions.members:
        _member(
            w,
            member.id,
            member.type,
            [member.x1, member.y1, member.z1],
            [member.x2, member.y2, member.z2],
            0.0,
            storey_at,
            ids,
            skipped,
        )


def _member(
    w: _Writer,
    member_id: str,
    type_id: str,
    start_point: list[float],
    end_point: list[float],
    rotation: float,
    storey_at: Any,
    ids: dict[str, str],
    skipped: list[str],
) -> None:
    """A straight member between two points, its profile extruded along it."""
    object_type = w.types.get(type_id)
    if object_type is None or object_type.kind not in _MEMBER_CLASSES:
        skipped.append(f"{member_id}: needs a brace, beam or column type")
        return
    start = np.array(start_point, dtype=float)
    axis = np.array(end_point, dtype=float) - start
    length = float(np.linalg.norm(axis))
    axis /= length
    # Profile Y as close to up as the axis allows (vertical members: profile X along world X),
    # then turned about the axis by the member's rotation.
    side = np.cross((0.0, 0.0, 1.0), axis)
    x_axis = side / np.linalg.norm(side) if np.linalg.norm(side) > 1e-9 else np.array([1.0, 0, 0])
    angle = math.radians(rotation)
    x_axis = x_axis * math.cos(angle) + np.cross(axis, x_axis) * math.sin(angle)
    ifc_class, predefined = _MEMBER_CLASSES[object_type.kind]
    product = w.entity(ifc_class, member_id, member_id, predefined)
    product.ObjectType = object_type.id
    product.Description = object_type.name
    w.extrusion(product, w.profile(object_type.id, object_type.profile), length)
    w.place(product, _placement(tuple(start), tuple(x_axis), tuple(axis)))
    w.run(
        "spatial.assign_container",
        w.file,
        products=[product],
        relating_structure=storey_at(min(start_point[2], end_point[2])),
    )
    w.material(product, object_type.material)
    ids[member_id] = product.GlobalId


_AREA_CLASSES = {"slab": ("IfcSlab", "FLOOR"), "wall": ("IfcWall", "STANDARD")}

# IFC class and predefined type of each foundation type of 9 Substructure.
_FOUNDATION_CLASSES = {
    "isolated": ("IfcFooting", "PAD_FOOTING"),
    "combined": ("IfcFooting", "PAD_FOOTING"),
    "strip": ("IfcFooting", "STRIP_FOOTING"),
    "pileCap": ("IfcFooting", "PILE_CAP"),
    "raft": ("IfcSlab", "BASESLAB"),
}

_FOUNDATION_NAMES = {
    "isolated": "Isolated footing",
    "combined": "Combined footing",
    "strip": "Strip footing",
    "pileCap": "Pile cap",
    "raft": "Raft",
}


def _export_foundations(
    w: _Writer,
    building: BuildingModel,
    substructure: Any,
    ground_level: float,
    storey_at: Any,
    ids: dict[str, str],
    skipped: list[str],
) -> None:
    """The foundations of 9 Substructure (:func:`saengine.library.bim.foundation_solids`).
    GlobalIds are keyed ``substructure:<id>``, so they never clash with the building model's;
    the id map uses the foundation's id unless an element of the building model (other than a
    drawn footing, which is left out) has it, then ``9:<id>``."""
    solids = foundation_solids(substructure, building, ground_level)
    skipped += [f"9 Substructure: {note}" for note in solids.notes]
    taken = {e.id for e in building.elements if not isinstance(e, FootingElement)}

    def add(key: str, product: Any, material: str | None, level: float) -> None:
        w.run(
            "spatial.assign_container",
            w.file,
            products=[product],
            relating_structure=storey_at(level),
        )
        if material:
            w.material(product, material)
        ids[key if key not in taken else f"9:{key}"] = product.GlobalId

    for f in solids.foundations:
        ifc_class, predefined = _FOUNDATION_CLASSES[f.type]
        product = w.entity(ifc_class, f.id, f"substructure:{f.id}", predefined)
        product.ObjectType = f.type
        product.Description = _FOUNDATION_NAMES[f.type]
        product.Tag = f.id
        if f.center is not None:
            w.extrusion(product, w.rectangle(f.length, f.width), f.thickness)
            w.place(
                product,
                _placement((*f.center, f.bottom), _rotation(f.rotation), (0, 0, 1)),
            )
        else:
            points = [(x * _SI, y * _SI) for x, y in f.outline]
            outline = w.run(
                "profile.add_arbitrary_profile", w.file, profile=[*points, points[0]], name=f.id
            )
            w.extrusion(product, outline, f.thickness, None)  # the outline is in absolute x, y
            w.place(product, _placement((0, 0, f.bottom), (1, 0, 0), (0, 0, 1)))
        add(f.id, product, f.material, f.bottom)

    circles: dict[float, Any] = {}
    for pile in solids.piles:
        product = w.entity("IfcPile", pile.id, f"substructure:{pile.id}", pile.kind.upper())
        product.ObjectType = pile.pile_type
        product.Description = f"Pile {pile.pile_type} under {pile.cap}"
        if pile.kind == "driven":
            profile = w.rectangle(pile.diameter, pile.diameter)
        else:
            if pile.diameter not in circles:
                circle = w.run(
                    "profile.add_parameterized_profile", w.file, ifc_class="IfcCircleProfileDef"
                )
                circle.Radius = float(pile.diameter) / 2
                circles[pile.diameter] = circle
            profile = circles[pile.diameter]
        w.extrusion(product, profile, pile.length)
        w.place(
            product, _placement((pile.x, pile.y, pile.head - pile.length), (1, 0, 0), (0, 0, 1))
        )
        add(pile.id, product, pile.material, pile.head - pile.length)

    for tie in solids.ties:
        object_type = w.types.get(tie.type)
        if object_type is None or object_type.kind != "beam":
            skipped.append(f"{tie.id}: '{tie.type}' is not a beam type of 04 Objects")
            continue
        for k, (a, b) in enumerate(tie.clear):
            length = math.dist(a, b)
            direction = ((b[0] - a[0]) / length, (b[1] - a[1]) / length, 0.0)
            key = tie.id if len(tie.clear) == 1 else f"{tie.id}/{k + 1}"
            product = w.entity("IfcFooting", key, f"substructure:{key}", "FOOTING_BEAM")
            product.ObjectType = object_type.id
            product.Description = f"Tie beam ({object_type.name})"
            product.Tag = tie.id
            # Profile Y up, extruded along the beam, its top centre at the tie beam's level.
            w.extrusion(
                product, w.profile(object_type.id, object_type.profile), length, "top centre"
            )
            w.place(
                product,
                _placement((*a, tie.level), (-direction[1], direction[0], 0.0), direction),
            )
            add(key, product, object_type.material, tie.level)


def _block(
    w: _Writer, block: BlockElement, storey_at: Any, ids: dict[str, str], skipped: list[str]
) -> None:
    """A solid block: its outline extruded along its normal by its thickness, as an
    IfcBuildingElementProxy (IFC has no class for a mass of concrete or rock)."""
    from saengine.library.structure import plane_of

    object_type = w.types.get(block.type)
    if object_type is None or object_type.kind != "solid":
        skipped.append(f"{block.id}: needs a solid type")
        return
    points = [np.array(p, dtype=float) for p in block.outline]
    plane = plane_of(points)
    if plane is None:
        skipped.append(f"{block.id}: its outline is not a flat polygon")
        return
    origin, normal = plane
    u = points[1] - points[0]
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    flat = [(float((p - origin) @ u) * _SI, float((p - origin) @ v) * _SI) for p in points]
    profile = w.run(
        "profile.add_arbitrary_profile", w.file, profile=[*flat, flat[0]], name=block.id
    )
    product = w.entity("IfcBuildingElementProxy", block.id, block.id, "ELEMENT")
    product.ObjectType = object_type.id
    product.Description = object_type.name
    product.Tag = block.id
    w.extrusion(product, profile, float(block.thickness), None)
    w.place(product, _placement(tuple(origin), tuple(u), tuple(normal)))
    w.run(
        "spatial.assign_container",
        w.file,
        products=[product],
        relating_structure=storey_at(min(p[2] for p in block.outline)),
    )
    w.material(product, object_type.material)
    ids[block.id] = product.GlobalId


def _area(
    w: _Writer, area: AreaElement, storey_at: Any, ids: dict[str, str], skipped: list[str]
) -> None:
    """A planar slab or wall panel: its outline (with openings) extruded through its thickness,
    centred on the outline's plane."""
    object_type = w.types.get(area.type)
    if object_type is None or object_type.kind not in _AREA_CLASSES:
        skipped.append(f"{area.id}: needs a slab or wall type")
        return
    from saengine.library.structure import plane_of

    points = [np.array(p, dtype=float) for p in area.outline]
    plane = plane_of(points)
    if plane is None:
        skipped.append(f"{area.id}: its outline is not a flat polygon")
        return
    origin, normal = plane
    u = points[1] - points[0]
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)

    def local(polygon: list[np.ndarray]) -> list[tuple[float, float]]:
        flat = [(float((p - origin) @ u) * _SI, float((p - origin) @ v) * _SI) for p in polygon]
        return [*flat, flat[0]]

    holes = [local([np.array(p, dtype=float) for p in o]) for o in area.openings]
    profile = (
        w.run(
            "profile.add_arbitrary_profile_with_voids",
            w.file,
            outer_profile=local(points),
            inner_profiles=holes,
            name=area.id,
        )
        if holes
        else w.run("profile.add_arbitrary_profile", w.file, profile=local(points), name=area.id)
    )
    thickness = float(object_type.thickness)
    ifc_class, predefined = _AREA_CLASSES[object_type.kind]
    product = w.entity(ifc_class, area.id, area.id, predefined)
    product.ObjectType = object_type.id
    product.Description = object_type.name
    product.Tag = area.id
    w.extrusion(product, profile, thickness, None)
    w.place(product, _placement(tuple(origin - normal * thickness / 2), tuple(u), tuple(normal)))
    w.run(
        "spatial.assign_container",
        w.file,
        products=[product],
        relating_structure=storey_at(min(p[2] for p in area.outline)),
    )
    w.material(product, object_type.material)
    ids[area.id] = product.GlobalId

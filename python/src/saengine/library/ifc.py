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

import itertools
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
    # Alpha 9 C12: cold-formed lipped channels; lipped Z sections as IfcZShapeProfileDef (its
    # flange thickness set to the wall thickness too; the lips are not in the IFC profile).
    "C": (
        "IfcCShapeProfileDef",
        {
            "depth": "Depth",
            "width": "Width",
            "wallThickness": "WallThickness",
            "girth": "Girth",
            "internalFilletRadius": "InternalFilletRadius",
        },
    ),
    "Z": (
        "IfcZShapeProfileDef",
        {
            "depth": "Depth",
            "width": "FlangeWidth",
            "wallThickness": "WebThickness",
            "internalFilletRadius": "FilletRadius",
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


# Opening cuts a little beyond their host's faces, so the boolean leaves no skin.
_IFC2X3_CLASSES: dict[str, tuple[str, str | None]] = {
    "IfcTank": ("IfcFlowStorageDevice", "IfcTankType"),
    "IfcPump": ("IfcFlowMovingDevice", "IfcPumpType"),
    "IfcFan": ("IfcFlowMovingDevice", "IfcFanType"),
    "IfcChiller": ("IfcEnergyConversionDevice", "IfcChillerType"),
    "IfcCoolingTower": ("IfcEnergyConversionDevice", "IfcCoolingTowerType"),
    "IfcUnitaryEquipment": ("IfcEnergyConversionDevice", "IfcUnitaryEquipmentType"),
    "IfcTransformer": ("IfcEnergyConversionDevice", "IfcTransformerType"),
    "IfcElectricGenerator": ("IfcEnergyConversionDevice", "IfcElectricGeneratorType"),
    "IfcElectricFlowStorageDevice": (
        "IfcEnergyConversionDevice",
        "IfcElectricFlowStorageDeviceType",
    ),
    "IfcSolarDevice": ("IfcBuildingElementProxy", None),
    "IfcElectricDistributionBoard": ("IfcElectricDistributionPoint", None),
    "IfcPipeSegment": ("IfcFlowSegment", "IfcPipeSegmentType"),
    "IfcDuctSegment": ("IfcFlowSegment", "IfcDuctSegmentType"),
    "IfcCableSegment": ("IfcFlowSegment", "IfcCableSegmentType"),
    "IfcCableCarrierSegment": ("IfcFlowSegment", "IfcCableCarrierSegmentType"),
    "IfcAirTerminal": ("IfcFlowTerminal", "IfcAirTerminalType"),
    "IfcLightFixture": ("IfcFlowTerminal", "IfcLightFixtureType"),
    "IfcFireSuppressionTerminal": ("IfcFlowTerminal", "IfcFireSuppressionTerminalType"),
    "IfcSanitaryTerminal": ("IfcFlowTerminal", "IfcSanitaryTerminalType"),
    "IfcAlarm": ("IfcDistributionControlElement", "IfcAlarmType"),
    "IfcSensor": ("IfcDistributionControlElement", "IfcSensorType"),
    "IfcFurniture": ("IfcFurnishingElement", "IfcFurnishingElementType"),
    "IfcFurnitureType": ("IfcFurnishingElementType", None),
    "IfcMechanicalFastener": ("IfcFastener", None),
    "IfcDistributionSystem": ("IfcSystem", None),
    "IfcDoorType": ("IfcDoorStyle", None),
    "IfcWindowType": ("IfcWindowStyle", None),
}

_IFC2X3_PREDEFINED: dict[tuple[str, str], str] = {
    ("IfcFooting", "CAISSON_FOUNDATION"): "USERDEFINED",
    ("IfcPile", "BORED"): "USERDEFINED",
    ("IfcPile", "DRIVEN"): "USERDEFINED",
    ("IfcPile", "JETGROUTING"): "USERDEFINED",
    ("IfcCovering", "MOLDING"): "USERDEFINED",
    ("IfcCovering", "SKIRTINGBOARD"): "USERDEFINED",
    ("IfcWallType", "MOVABLE"): "STANDARD",
    ("IfcWallType", "PARAPET"): "STANDARD",
    ("IfcWallType", "PARTITIONING"): "STANDARD",
    ("IfcWallType", "SOLIDWALL"): "STANDARD",
    ("IfcBuildingElementProxyType", "COMPLEX"): "USERDEFINED",
    ("IfcBuildingElementProxyType", "ELEMENT"): "USERDEFINED",
    ("IfcBuildingElementProxyType", "PARTIAL"): "USERDEFINED",
    ("IfcBuildingElementProxyType", "PROVISIONFORVOID"): "USERDEFINED",
    ("IfcBuildingElementProxyType", "PROVISIONFORSPACE"): "USERDEFINED",
}

_IFC2X3_HAS_PREDEFINED = frozenset(
    {
        "IfcSlab",
        "IfcFooting",
        "IfcPile",
        "IfcRailing",
        "IfcCovering",
        "IfcWallType",
        "IfcBuildingElementProxyType",
        "IfcFurnishingElementType",
        "IfcSanitaryTerminalType",
        "IfcElementAssembly",
        "IfcStructuralAnalysisModel",
        "IfcStructuralCurveMember",
        "IfcStructuralSurfaceMember",
        "IfcStructuralLoadGroup",
        "IfcTankType",
        "IfcPumpType",
        "IfcFanType",
        "IfcChillerType",
        "IfcCoolingTowerType",
        "IfcUnitaryEquipmentType",
        "IfcTransformerType",
        "IfcElectricGeneratorType",
        "IfcElectricFlowStorageDeviceType",
        "IfcPipeSegmentType",
        "IfcDuctSegmentType",
        "IfcCableSegmentType",
        "IfcCableCarrierSegmentType",
        "IfcAirTerminalType",
        "IfcLightFixtureType",
        "IfcFireSuppressionTerminalType",
        "IfcAlarmType",
        "IfcSensorType",
    }
)


class _Writer:
    def __init__(
        self,
        name: str,
        objects: ObjectLibrary,
        materials: MaterialLibrary | None,
        schema: str = "IFC4",
    ) -> None:
        normalized = (schema or "IFC4").strip().upper()
        if normalized not in ("IFC4", "IFC2X3"):
            raise ValueError(f"unsupported IFC schema {schema!r}: expected 'IFC4' or 'IFC2X3'")
        self.schema = normalized
        self.is_ifc2x3 = normalized == "IFC2X3"
        self.run = ifcopenshell.api.run
        self.file = ifcopenshell.api.run("project.create_file", version=self.schema)
        self.owner_history: Any = None
        if self.is_ifc2x3:
            person = self.run(
                "owner.add_person", self.file, identification="SAEngine", family_name="SAEngine"
            )
            org = self.run(
                "owner.add_organisation", self.file, identification="SAEngine", name="SAEngine"
            )
            self.run(
                "owner.add_person_and_organisation", self.file, person=person, organisation=org
            )
            self.run("owner.add_application", self.file, application_full_name="SAEngine")
            self.owner_history = self.run("owner.create_owner_history", self.file)
        self.types = {o.id: o for o in objects.objects}
        self.material_names = {m.id: m.name for m in (materials.materials if materials else [])}
        self.materials: dict[str, Any] = {}
        self.profiles: dict[str, Any] = {}
        self.mep_products: dict[str, list[Any]] = {}
        self._ifc2x3_types: dict[tuple[str, str], Any] = {}

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

    def _fix_profile_position(self, profile: Any) -> Any:
        if self.is_ifc2x3 and hasattr(profile, "Position") and profile.Position is None:
            profile.Position = self.file.createIfcAxis2Placement2D(
                self.file.createIfcCartesianPoint((0.0, 0.0)),
                self.file.createIfcDirection((1.0, 0.0)),
            )
        return profile

    def param_profile(self, ifc_class: str) -> Any:
        profile = self.run("profile.add_parameterized_profile", self.file, ifc_class=ifc_class)
        return self._fix_profile_position(profile)

    def entity(self, ifc_class: str, name: str, key: str, predefined: str | None = None) -> Any:
        target_class = ifc_class
        type_class: str | None = None
        target_predefined = predefined
        if self.is_ifc2x3:
            if ifc_class in _IFC2X3_CLASSES:
                target_class, type_class = _IFC2X3_CLASSES[ifc_class]
            if target_predefined is not None:
                target_predefined = _IFC2X3_PREDEFINED.get(
                    (target_class, target_predefined), target_predefined
                )
            api_predefined = target_predefined if target_class in _IFC2X3_HAS_PREDEFINED else None
        else:
            api_predefined = target_predefined

        entity = self.run(
            "root.create_entity",
            self.file,
            ifc_class=target_class,
            name=name,
            predefined_type=api_predefined,
        )
        entity.GlobalId = global_id(key)
        if self.is_ifc2x3:
            if target_class == "IfcElectricDistributionPoint":
                entity.DistributionPointFunction = (
                    "SWITCHBOARD"
                    if predefined == "SWITCHBOARD"
                    else "DISTRIBUTIONBOARD"
                    if predefined == "DISTRIBUTIONBOARD"
                    else "OTHER"
                )
            if (
                predefined
                and api_predefined is None
                and hasattr(entity, "ObjectType")
                and entity.ObjectType is None
            ):
                entity.ObjectType = predefined
            if type_class is not None:
                t_predef = (
                    "USERDEFINED"
                    if type_class == "IfcFurnishingElementType"
                    else (predefined or "NOTDEFINED")
                )
                t_key = (type_class, t_predef)
                if t_key not in self._ifc2x3_types:
                    t_ent = self.run(
                        "root.create_entity",
                        self.file,
                        ifc_class=type_class,
                        name=f"{type_class}:{t_predef}",
                        predefined_type=t_predef if type_class in _IFC2X3_HAS_PREDEFINED else None,
                    )
                    t_ent.GlobalId = global_id(f"ifc2x3type:{type_class}:{t_predef}")
                    self._ifc2x3_types[t_key] = t_ent
                self.run(
                    "type.assign_type",
                    self.file,
                    related_objects=[entity],
                    relating_type=self._ifc2x3_types[t_key],
                    should_map_representations=False,
                )
        return entity

    def place(self, product: Any, matrix: np.ndarray) -> None:
        self.run(
            "geometry.edit_object_placement", self.file, product=product, matrix=matrix, is_si=False
        )

    def profile(self, type_id: str, profile: Any) -> Any:
        if type_id not in self.profiles and profile.shape == "designed":
            from saengine.library import section_designer

            section = section_designer.resolve(profile)
            self.profiles[type_id] = section_designer.ifc_profile(
                self.run, self.file, section, type_id
            )
        if type_id not in self.profiles:
            ifc_class, attributes = _PROFILES[profile.shape]
            ifc_profile = self.param_profile(ifc_class)
            ifc_profile.ProfileName = type_id
            for source, target in attributes.items():
                value = getattr(profile, source)
                if value:
                    setattr(ifc_profile, target, float(value))
            if profile.shape == "Z":  # alpha 9 C12
                ifc_profile.FlangeThickness = float(profile.wallThickness)
            self.profiles[type_id] = ifc_profile
        return self.profiles[type_id]

    def rectangle(self, x: float, y: float) -> Any:
        ifc_profile = self.param_profile("IfcRectangleProfileDef")
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


def _apply_georeferencing(
    w: _Writer,
    soil: Any,
    crs: str = "BTM",
    ground_level: float = 0.0,
) -> None:
    """Write ``IfcMapConversion`` + ``IfcProjectedCRS`` (or ``ePSet_MapConversion`` in IFC2X3)."""
    site_obj = getattr(soil, "site", None) if soil is not None else None
    if site_obj is None or not getattr(site_obj, "georeferenced", False):
        return
    import ifcopenshell.util.geolocation as gl

    from saengine.gis.crs import ifc_map_conversion

    g_level = float(getattr(soil, "groundLevel", None) or ground_level or 0.0)
    conv = ifc_map_conversion(site_obj, crs=crs, ground_level_mm=g_level)
    w.site.RefLatitude = gl.dd2dms(float(site_obj.lat), use_us=True)
    w.site.RefLongitude = gl.dd2dms(float(site_obj.lon), use_us=True)
    w.site.RefElevation = conv["orthogonal_height"]

    w.run("georeference.add_georeferencing", w.file, name=conv["name"])
    map_unit = "METRE" if w.is_ifc2x3 else w.file.createIfcSIUnit(None, "LENGTHUNIT", None, "METRE")
    projected_crs: dict[str, Any] = {
        "Name": conv["name"],
        "Description": conv["description"],
        "GeodeticDatum": conv["datum"],
        "MapProjection": conv["projection"],
        "MapUnit": map_unit,
    }
    if conv["zone"]:
        projected_crs["MapZone"] = conv["zone"]
    w.run(
        "georeference.edit_georeferencing",
        w.file,
        projected_crs=projected_crs,
        coordinate_operation={
            "Eastings": conv["eastings"],
            "Northings": conv["northings"],
            "OrthogonalHeight": conv["orthogonal_height"],
            "XAxisAbscissa": conv["x_axis_abscissa"],
            "XAxisOrdinate": conv["x_axis_ordinate"],
            "Scale": conv["scale"],
        },
    )


def export_ifc(
    building: BuildingModel,
    objects: ObjectLibrary,
    materials: MaterialLibrary | None = None,
    name: str = "Project",
    substructure: Any = None,
    ground_level: float = 0.0,
    mep: Any = None,
    architecture: Any = None,
    rebar: dict[str, Any] | None = None,
    schema: str = "IFC4",
    analytical: Any = None,
    soil: Any = None,
    include_connections: bool = True,
    fabrication: Any = None,
    crs: str = "BTM",
    include_georeferencing: bool = True,
) -> tuple[ifcopenshell.file, dict[str, str], list[str]]:
    """The IFC file of ``building``, its element id -> GlobalId map, and elements left out (why).

    ``schema`` selects ``"IFC4"`` (default) or ``"IFC2X3"``. With ``analytical`` (an
    :class:`saengine.exporters.analytical.AnalyticalModel`), writes the structural analysis view
    (``IfcStructuralAnalysisModel``). With ``soil`` (whose ``site`` is georeferenced) and
    ``include_georeferencing``, writes ``IfcMapConversion`` + ``IfcProjectedCRS`` (or
    ``ePSet_MapConversion`` in IFC2X3) in ``crs`` (``"BTM"`` or ``"UTM"``). With
    ``include_connections`` (default True), writes fabricated steel connection plates, bolts,
    bolt-hole voids and assemblies from :mod:`saengine.fabrication.model`.

    With ``substructure`` (the project's ``substructure.json`` once it is no longer the
    placeholder, see :func:`saengine.substructure.handover.authoritative_substructure`) the
    foundations are its footings, pile caps, piles, rafts and tie beams (foundations without a
    founding level found 2.0 m below ``ground_level``), and the footings of the building model
    are left out; without it the building model's footings are exported. With ``mep`` (the
    :class:`saengine.library.mep.MepModel` of ``07 MEP/mep.json``) its equipment, plinths,
    sleeves, openings and shafts are added (:func:`_export_mep`). With ``architecture`` (the
    :class:`saengine.library.architecture.Architecture` of ``05 Floor Plan/architecture.json``)
    its walls, doors, windows, rooms and finishes are added, keyed ``arch:<id>`` in the map (see
    :mod:`saengine.library.architecture_ifc`). With ``rebar`` (the reinforcement cages of
    :func:`saengine.drawings.cages.cage_model`) every bar mark of a beam or column is an
    IfcReinforcingBar, keyed ``rebar:<member>/<n>`` (:mod:`saengine.library.ifc_rebar`)."""
    if mep is not None:
        from saengine.mep.loads import with_mep_openings

        building, _ = with_mep_openings(building, mep)  # shafts and slab and wall openings
    w = _Writer(name, objects, materials, schema=schema)
    if include_georeferencing and soil is not None:
        _apply_georeferencing(w, soil, crs=crs, ground_level=ground_level)
    storeys: list[tuple[float, Any]] = []
    storey_ids: dict[str, Any] = {}
    for story in sorted(building.stories, key=lambda s: s.elevation):
        storey = w.entity("IfcBuildingStorey", story.name, f"storey:{story.id}")
        storey.Elevation = float(story.elevation)
        w.run("aggregate.assign_object", w.file, products=[storey], relating_object=w.building)
        w.place(storey, _placement((0, 0, story.elevation), (1, 0, 0), (0, 0, 1)))
        storeys.append((story.elevation, storey))
        storey_ids[story.id] = storey

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
                products,
            )
            continue
        if isinstance(element, AreaElement):
            _area(w, element, storey_at, ids, skipped, products)
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
        if getattr(mep, "plumbing", None) is not None:
            _export_plumbing(w, building, mep, ground_level, storey_at, ids, skipped)
        if (
            getattr(mep, "hvac", None) is not None
            or getattr(mep, "electrical", None) is not None
            or getattr(mep, "fire", None) is not None
            or getattr(mep, "gas", None) is not None
            or getattr(mep, "medicalGas", None) is not None
        ):
            _export_services(w, building, mep, storey_at, ids, skipped)
        _export_systems(w, building, mep, skipped)
    if architecture is not None and not building.stories:
        # FD-13: before the building model is built it has no stories; the architecture is not
        # wrong, it has nothing to stand on yet.
        skipped.append(
            "the architecture: shown once the building model is built (Build from Floor Plan)"
        )
    elif architecture is not None:
        from saengine.library.architecture_ifc import export_architecture

        arch_ids: dict[str, str] = {}
        elevations = {s.id: s.elevation for s in building.stories}
        export_architecture(w, architecture, elevations, storey_ids, storey_at, arch_ids, skipped)
        ids.update({f"arch:{key}": guid for key, guid in arch_ids.items()})
    if rebar is not None:
        from saengine.library.ifc_rebar import export_rebar

        export_rebar(w, rebar, storey_at, ids, skipped)
    if include_connections:
        from saengine.library.ifc_fabrication import export_steel_connections

        export_steel_connections(
            w, building, objects, materials, products, storey_at, ids, skipped, fabrication
        )
    if analytical is not None:
        from saengine.library.ifc_structural import export_structural_analysis

        export_structural_analysis(w, analytical, products, ids, skipped)
    return w.file, ids, skipped


#: Thicknesses drawn for a plumbing tank that gives none [mm] (its design proposes its own).
_TANK_WALL = 200.0
_TANK_ROOF = 125.0
#: Diameter drawn for a riser that is neither entered nor sized [mm].
_RISER_DIAMETER = 100.0


def _export_plumbing(
    w: _Writer,
    building: BuildingModel,
    mep: Any,
    ground_level: float,
    storey_at: Any,
    ids: dict[str, str],
    skipped: list[str],
) -> None:
    """The plumbing of 7 MEP: its tanks as IfcTank (an overhead tank on its story; ground
    tanks buried from ``ground_level`` and their top level; a soak well as a ring's cylinder),
    drawn by their outside size, and its risers and stacks as vertical IfcPipeSegment from the
    story they start at to their top story, at their entered or sized diameter. An overhead tank
    whose weight an equipment tank carries is that equipment (exported above)."""
    from saengine.library.mep import TANK_KINDS
    from saengine.mep.loads import footprint_covers

    plumbing = mep.plumbing
    levels = {s.id: s.elevation for s in building.stories}
    sized: dict[str, float] = {}
    if plumbing.risers and any(r.diameter is None for r in plumbing.risers):
        try:
            from saengine.plumbing.report import plumbing_results

            report = plumbing_results(mep, building, None, ground_level)
            sized = {r["id"]: r["diameter"] for r in report["risers"] if r.get("diameter")}
        except Exception as error:  # noqa: BLE001 - the model still exports, risers drawn Ø100
            skipped.append(f"plumbing: the risers are not sized ({error})")
    for tank in plumbing.tanks:
        if tank.kind == "overhead" and any(
            e.kind == "tank"
            and (
                e.id == tank.equipment
                if tank.equipment is not None
                else e.story == tank.story and footprint_covers(e, tank.x, tank.y)
            )
            for e in mep.equipment
        ):
            continue
        wall = tank.walls or _TANK_WALL
        base = tank.base or wall + 50.0
        roof = tank.roof if tank.roof is not None else _TANK_ROOF
        if tank.waterDepth is None:
            skipped.append(f"{tank.id}: no water depth")
            continue
        height = tank.waterDepth + (tank.freeboard if tank.freeboard is not None else 300.0)
        total = base + height + roof
        if tank.kind == "overhead":
            if tank.story not in levels:
                skipped.append(f"{tank.id}: no story '{tank.story}'")
                continue
            bottom = levels[tank.story]
        else:
            top = tank.topLevel if tank.topLevel is not None else 150.0
            bottom = ground_level + top - total
        if tank.kind == "soakWell":
            if tank.diameter is None:
                skipped.append(f"{tank.id}: no diameter")
                continue
            profile = w.param_profile("IfcCircleProfileDef")
            profile.Radius = tank.diameter / 2 + wall
        elif tank.length is None or tank.width is None:
            skipped.append(f"{tank.id}: no length or width")
            continue
        else:
            # Outside = inside + 2 walls: the partitions stand inside the inside length, as the
            # tank design, its quantities and the bill take them (saengine.plumbing.tanks).
            profile = w.rectangle(tank.length + 2 * wall, tank.width + 2 * wall)
        toe = (tank.toe or 0.0) if tank.kind != "overhead" and tank.kind != "soakWell" else 0.0
        storey = storey_at(max(bottom, min(levels.values(), default=0.0)))
        product = w.entity("IfcTank", tank.id, f"plumbing:{tank.id}", "STORAGE")
        product.ObjectType = tank.kind
        product.Tag = tank.id
        product.Description = f"{TANK_KINDS.get(tank.kind, tank.kind)}, {tank.construction}"
        if toe > 0 and tank.length is not None and tank.width is not None:
            # The base with its toe as its own slab under the tank's walls and roof.
            slab = w.entity("IfcSlab", f"{tank.id} base", f"plumbing:{tank.id}:base", "BASESLAB")
            slab.Tag = f"{tank.id}-base"
            slab.Description = f"base of {tank.id} with a {toe:g} mm toe"
            w.extrusion(
                slab, w.rectangle(tank.length + 2 * wall + 2 * toe, tank.width + 2 * wall + 2 * toe),
                base,
            )  # fmt: skip
            w.place(slab, _placement((tank.x, tank.y, bottom), (1, 0, 0), (0, 0, 1)))
            w.run("spatial.assign_container", w.file, products=[slab], relating_structure=storey)
            if tank.material:
                w.material(slab, tank.material)
            ids[f"{tank.id}-base"] = slab.GlobalId
            w.extrusion(product, profile, total - base)
            w.place(product, _placement((tank.x, tank.y, bottom + base), (1, 0, 0), (0, 0, 1)))
        else:
            w.extrusion(product, profile, total)
            w.place(product, _placement((tank.x, tank.y, bottom), (1, 0, 0), (0, 0, 1)))
        w.run("spatial.assign_container", w.file, products=[product], relating_structure=storey)
        if tank.material:
            w.material(product, tank.material)
        ids[tank.id] = product.GlobalId
        w.mep_products.setdefault(tank.id, []).append(product)
    for riser in plumbing.risers:
        if riser.fromStory not in levels or riser.toStory not in levels:
            skipped.append(f"{riser.id}: no story '{riser.fromStory}' or '{riser.toStory}'")
            continue
        low, high = levels[riser.fromStory], levels[riser.toStory]
        if high <= low:
            skipped.append(f"{riser.id}: its top story is not above the story it starts at")
            continue
        diameter = riser.diameter or sized.get(riser.id) or _RISER_DIAMETER
        profile = w.param_profile("IfcCircleProfileDef")
        profile.Radius = float(diameter) / 2
        product = w.entity("IfcPipeSegment", riser.id, f"plumbing:{riser.id}", "RIGIDSEGMENT")
        product.ObjectType = riser.system
        product.Tag = riser.id
        product.Description = f"DN{diameter:g} {riser.system}" + (
            f" {riser.material}" if riser.material else ""
        )
        w.extrusion(product, profile, high - low)
        w.place(product, _placement((riser.x, riser.y, low), (1, 0, 0), (0, 0, 1)))
        w.run(
            "spatial.assign_container",
            w.file,
            products=[product],
            relating_structure=storey_at(low),
        )
        ids[riser.id] = product.GlobalId
        w.mep_products.setdefault(riser.id, []).append(product)
    for pipe in getattr(plumbing, "pipes", []):
        if pipe.story not in levels:
            skipped.append(f"{pipe.id}: no story '{pipe.story}'")
            continue
        diameter = float(pipe.diameter or _RISER_DIAMETER)
        profile = w.param_profile("IfcCircleProfileDef")
        profile.Radius = diameter / 2
        floor = levels[pipe.story]
        centre = (
            floor + float(pipe.bottom) + diameter / 2 if pipe.bottom is not None else floor + 2700.0
        )
        _run_segments(
            w, "IfcPipeSegment", "RIGIDSEGMENT", pipe.id, f"pipe:{pipe.id}", pipe.path,
            profile, centre, storey_at(floor), ids,
        )  # fmt: skip


#: IFC4 classes of the HVAC plant kinds of 7 MEP (class, predefined type).
_PLANT_CLASSES: dict[str, tuple[str, str | None]] = {
    "chiller": ("IfcChiller", "AIRCOOLED"),
    "coolingTower": ("IfcCoolingTower", "MECHANICALINDUCEDDRAFT"),
    "ahu": ("IfcUnitaryEquipment", "AIRHANDLER"),
    "fcu": ("IfcUnitaryEquipment", "AIRCONDITIONINGUNIT"),
    "vrfOutdoor": ("IfcUnitaryEquipment", "SPLITSYSTEM"),
    "splitOutdoor": ("IfcUnitaryEquipment", "SPLITSYSTEM"),
    "pump": ("IfcPump", "ENDSUCTION"),
    "exhaustFan": ("IfcFan", "NOTDEFINED"),
    "freshAirUnit": ("IfcUnitaryEquipment", "AIRHANDLER"),
}
#: IFC4 classes of the electrical equipment kinds of 7 MEP (class, predefined type).
_ELECTRICAL_CLASSES: dict[str, tuple[str, str | None]] = {
    "transformer": ("IfcTransformer", "VOLTAGE"),
    "switchgear": ("IfcElectricDistributionBoard", "SWITCHBOARD"),
    "lvPanel": ("IfcElectricDistributionBoard", "SWITCHBOARD"),
    "distributionBoard": ("IfcElectricDistributionBoard", "DISTRIBUTIONBOARD"),
    "generator": ("IfcElectricGenerator", "ENGINEGENERATOR"),
    "fuelTank": ("IfcTank", "STORAGE"),
    "ups": ("IfcElectricFlowStorageDevice", "UPS"),
    "battery": ("IfcElectricFlowStorageDevice", "BATTERY"),
    "capacitorBank": ("IfcElectricFlowStorageDevice", "CAPACITORBANK"),
    "solarPv": ("IfcSolarDevice", "SOLARPANEL"),
}
#: Classes of the rising mains (vertical) by kind.
_RISER_CLASSES: dict[str, tuple[str, str]] = {
    "busbar": ("IfcCableSegment", "BUSBARSEGMENT"),
    "cableTray": ("IfcCableCarrierSegment", "CABLETRAYSEGMENT"),
    "cableLadder": ("IfcCableCarrierSegment", "CABLELADDERSEGMENT"),
    "conduitBank": ("IfcCableCarrierSegment", "CONDUITSEGMENT"),
}
#: Size drawn for a rising main that gives none [mm] (the electrical report sizes it).
_ELECTRICAL_RISER_SIZE = 200.0
#: Slab thickness taken for the soffit where 04 Objects gives none [mm].
_SOFFIT_SLAB = 150.0
#: Space left above a cable tray to lay the cables, unless its bottom is given [mm] (as
#: saengine.electrical.tables.TRAY_HEADROOM); a duct hangs 25 mm below the soffit
#: (saengine.hvac.openings.HANGER_GAP).
_TRAY_HEADROOM = 150.0
_DUCT_HANGER = 25.0


def _box_product(
    w: _Writer,
    ifc_class: str,
    predefined: str | None,
    key: str,
    name: str,
    tag: str,
    size: tuple[float, float, float],
    at: tuple[float, float, float],
    storey: Any,
) -> Any:
    product = w.entity(ifc_class, name, key, predefined)
    product.Tag = tag
    length, width, height = size
    w.extrusion(product, w.rectangle(length, width), height)
    w.place(product, _placement(at, (1, 0, 0), (0, 0, 1)))
    w.run("spatial.assign_container", w.file, products=[product], relating_structure=storey)
    return product


def _run_segments(
    w: _Writer,
    ifc_class: str,
    predefined: str,
    item_id: str,
    key: str,
    path: list[Any],
    profile: Any,
    centre: float,
    storey: Any,
    ids: dict[str, str],
) -> None:
    """A horizontal run along ``path`` at the elevation of its centre: one segment per leg of
    the path (``<id>`` for the first, ``<id>/2``... for the next)."""
    import itertools

    legs = [(a, b) for a, b in itertools.pairwise(path) if math.dist(a[:2], b[:2]) > 1.0]
    for k, (a, b) in enumerate(legs, start=1):
        length = math.dist(a[:2], b[:2])
        d = ((b[0] - a[0]) / length, (b[1] - a[1]) / length, 0.0)
        product = w.entity(ifc_class, item_id, f"{key}:{k}", predefined)
        product.Tag = item_id
        w.extrusion(product, profile, length)
        # Extruded along the leg; the profile's X across it in plan, its Y up.
        w.place(product, _placement((a[0], a[1], centre), (-d[1], d[0], 0.0), d))
        w.run("spatial.assign_container", w.file, products=[product], relating_structure=storey)
        ids[item_id if k == 1 else f"{item_id}/{k}"] = product.GlobalId
        w.mep_products.setdefault(item_id, []).append(product)


def _soffits(w: _Writer, building: BuildingModel) -> dict[float, float]:
    """The thickest slab [mm] at each slab elevation of the building model."""
    out: dict[float, float] = {}
    for e in building.elements:
        if isinstance(e, SlabElement):
            t = getattr(w.types.get(e.type), "thickness", None) or _SOFFIT_SLAB
            out[e.elevation] = max(out.get(e.elevation, 0.0), float(t))
    return out


def _export_services(
    w: _Writer,
    building: BuildingModel,
    mep: Any,
    storey_at: Any,
    ids: dict[str, str],
    skipped: list[str],
) -> None:
    """The HVAC and electrical services of 7 MEP for the structure's coordination model: the
    plant and the electrical equipment as their IFC4 classes (IfcUnitaryEquipment, IfcChiller,
    IfcTransformer, IfcElectricGenerator, ...) drawn as boxes of their size (typical where
    none is given), the ducts as IfcDuctSegment and the cable trays as IfcCableCarrierSegment
    along their plan path under the soffit (or at their given bottom), the duct risers and the
    rising mains vertically from the story they start at to their top story. An item whose
    weight an equipment of 7 MEP carries is that equipment (exported above)."""
    from saengine.mep.loads import footprint_covers

    levels = {s.id: s.elevation for s in building.stories}
    order = sorted(levels, key=levels.__getitem__)
    soffit_slab = _soffits(w, building)

    def above(story: str) -> float | None:
        i = order.index(story)
        return levels[order[i + 1]] if i + 1 < len(order) else None

    def soffit(story: str) -> float | None:
        top = above(story)
        if top is None:
            return None
        return top - soffit_slab.get(top, _SOFFIT_SLAB)

    def carried(item: Any) -> bool:
        return getattr(item, "equipment", None) is not None or any(
            e.story == item.story and footprint_covers(e, item.x, item.y) for e in mep.equipment
        )

    hvac = getattr(mep, "hvac", None)
    if hvac is not None:
        from saengine.hvac.plant import own_size
        from saengine.library.mep import HVAC_PLANT_KINDS

        for plant in hvac.plant:
            if plant.story not in levels:
                skipped.append(f"{plant.id}: no story '{plant.story}'")
                continue
            if carried(plant):
                if getattr(plant, "equipment", None) and plant.equipment in w.mep_products:
                    w.mep_products[plant.id] = w.mep_products[plant.equipment]
                continue
            size = [plant.length, plant.width, plant.height]
            if None in size and plant.capacity:
                typical = own_size(plant.kind, plant.capacity)
                if typical is not None:
                    size = [s if s is not None else t for s, t in zip(size, typical[:3])]
            if size[0] is None or size[1] is None:
                if plant.kind == "ahu":
                    size = [size[0] or 1500.0, size[1] or 1200.0, size[2] or _EQUIPMENT_HEIGHT]
                else:
                    skipped.append(f"{plant.id}: no size")
                    continue
            ifc_class, predefined = _PLANT_CLASSES.get(
                plant.kind, ("IfcBuildingElementProxy", None)
            )
            floor = levels[plant.story]
            product = _box_product(
                w, ifc_class, predefined, f"hvac:{plant.id}",
                f"{HVAC_PLANT_KINDS.get(plant.kind, plant.kind)} {plant.id}", plant.id,
                (size[0], size[1], size[2] or _EQUIPMENT_HEIGHT), (plant.x, plant.y, floor),
                storey_at(floor),
            )  # fmt: skip
            product.ObjectType = plant.kind
            product.Description = (
                f"{plant.operatingWeight:g} kN operating" if plant.operatingWeight else None
            )
            ids[plant.id] = product.GlobalId
            w.mep_products.setdefault(plant.id, []).append(product)
        for duct in hvac.ducts:
            if duct.story not in levels:
                skipped.append(f"{duct.id}: no story '{duct.story}'")
                continue
            if duct.shape == "round" and duct.diameter:
                profile = w.param_profile("IfcCircleProfileDef")
                profile.Radius = float(duct.diameter) / 2
                height = float(duct.diameter)
            elif duct.width and duct.height:
                profile = w.rectangle(duct.width, duct.height)
                height = float(duct.height)
            else:
                skipped.append(f"{duct.id}: no duct size")
                continue
            if duct.riser is not None:
                low, high = levels.get(duct.riser.fromStory), levels.get(duct.riser.toStory)
                if low is None or high is None or high <= low:
                    skipped.append(f"{duct.id}: its riser's stories are not in the building model")
                    continue
                x, y = duct.path[0][:2]
                product = w.entity("IfcDuctSegment", duct.id, f"duct:{duct.id}", "RIGIDSEGMENT")
                product.Tag = duct.id
                w.extrusion(product, profile, high - low)
                w.place(product, _placement((x, y, low), (1, 0, 0), (0, 0, 1)))
                w.run(
                    "spatial.assign_container", w.file, products=[product],
                    relating_structure=storey_at(low),
                )  # fmt: skip
                product.ObjectType = duct.system
                ids[duct.id] = product.GlobalId
                w.mep_products.setdefault(duct.id, []).append(product)
                continue
            floor = levels[duct.story]
            if duct.bottom is not None:
                centre = floor + duct.bottom + height / 2
            else:
                top = soffit(duct.story)
                centre = (top - _DUCT_HANGER - height / 2) if top is not None else (floor + 2700.0)
            _run_segments(
                w, "IfcDuctSegment", "RIGIDSEGMENT", duct.id, f"duct:{duct.id}", duct.path,
                profile, centre, storey_at(floor), ids,
            )  # fmt: skip
        for term in getattr(hvac, "terminals", []):
            if term.story not in levels:
                skipped.append(f"{term.id}: no story '{term.story}'")
                continue
            floor = levels[term.story]
            top = soffit(term.story)
            z = (
                float(term.z)
                if term.z is not None
                else (top - _DUCT_HANGER if top is not None else floor + 2700.0)
            )
            size_x = float(term.width or term.diameter or 400.0)
            size_y = float(term.height or term.diameter or 400.0)
            predefined = {
                "supplyDiffuser": "DIFFUSER",
                "returnGrille": "GRILLE",
                "exhaustGrille": "GRILLE",
                "freshAirLouvre": "LOUVRE",
            }.get(term.kind, "DIFFUSER")
            product = _box_product(
                w, "IfcAirTerminal", predefined, f"terminal:{term.id}", term.id, term.id,
                (size_x, size_y, 150.0), (term.x, term.y, z), storey_at(floor),
            )  # fmt: skip
            product.ObjectType = term.system
            ids[term.id] = product.GlobalId
            w.mep_products.setdefault(term.id, []).append(product)
        for pipe in getattr(hvac, "pipes", []):
            if pipe.story not in levels:
                skipped.append(f"{pipe.id}: no story '{pipe.story}'")
                continue
            diameter = float(pipe.diameter or _RISER_DIAMETER)
            profile = w.param_profile("IfcCircleProfileDef")
            profile.Radius = diameter / 2
            floor = levels[pipe.story]
            top = soffit(pipe.story)
            centre = (
                floor + float(pipe.bottom) + diameter / 2
                if pipe.bottom is not None
                else (top - _TRAY_HEADROOM - diameter / 2 if top is not None else floor + 2700.0)
            )
            _run_segments(
                w, "IfcPipeSegment", "RIGIDSEGMENT", pipe.id, f"hvacPipe:{pipe.id}", pipe.path,
                profile, centre, storey_at(floor), ids,
            )  # fmt: skip
    electrical = getattr(mep, "electrical", None)
    if electrical is not None:
        from saengine.electrical.report import with_typical
        from saengine.library.mep import ELECTRICAL_EQUIPMENT_KINDS

        for item in electrical.equipment:
            if item.story not in levels:
                skipped.append(f"{item.id}: no story '{item.story}'")
                continue
            if carried(item):
                if getattr(item, "equipment", None) and item.equipment in w.mep_products:
                    w.mep_products[item.id] = w.mep_products[item.equipment]
                continue
            full = with_typical(item.model_dump(mode="json"), electrical.supply.transformerType)
            if not full.get("length") or not full.get("width"):
                skipped.append(f"{item.id}: no size")
                continue
            ifc_class, predefined = _ELECTRICAL_CLASSES.get(
                item.kind, ("IfcBuildingElementProxy", None)
            )
            floor = levels[item.story]
            product = _box_product(
                w, ifc_class, predefined, f"electrical:{item.id}",
                item.name or f"{ELECTRICAL_EQUIPMENT_KINDS.get(item.kind, item.kind)} {item.id}",
                item.id, (full["length"], full["width"], full.get("height") or _EQUIPMENT_HEIGHT),
                (item.x, item.y, floor), storey_at(floor),
            )  # fmt: skip
            product.ObjectType = item.kind
            weight = full.get("operatingWeight")
            product.Description = f"{weight:g} kN operating" if weight else None
            ids[item.id] = product.GlobalId
            w.mep_products.setdefault(item.id, []).append(product)
        for riser in electrical.risers:
            low, high = levels.get(riser.fromStory), levels.get(riser.toStory)
            if low is None or high is None or high <= low:
                skipped.append(f"{riser.id}: its stories are not in the building model")
                continue
            ifc_class, predefined = _RISER_CLASSES.get(riser.kind, _RISER_CLASSES["cableTray"])
            product = w.entity(ifc_class, riser.id, f"riser:{riser.id}", predefined)
            product.Tag = riser.id
            product.ObjectType = riser.kind
            w.extrusion(
                product,
                w.rectangle(
                    riser.width or _ELECTRICAL_RISER_SIZE, riser.depth or _ELECTRICAL_RISER_SIZE
                ),
                high - low,
            )
            w.place(product, _placement((riser.x, riser.y, low), (1, 0, 0), (0, 0, 1)))
            w.run(
                "spatial.assign_container", w.file, products=[product],
                relating_structure=storey_at(low),
            )  # fmt: skip
            ids[riser.id] = product.GlobalId
            w.mep_products.setdefault(riser.id, []).append(product)
        for tray in electrical.trays:
            if tray.story not in levels:
                skipped.append(f"{tray.id}: no story '{tray.story}'")
                continue
            floor = levels[tray.story]
            if tray.bottom is not None:
                centre = floor + tray.bottom + tray.height / 2
            else:
                top = soffit(tray.story)
                if top is None:
                    skipped.append(f"{tray.id}: no floor above its story to hang from")
                    continue
                centre = top - _TRAY_HEADROOM - tray.height / 2
            _run_segments(
                w, "IfcCableCarrierSegment", "CABLETRAYSEGMENT", tray.id, f"tray:{tray.id}",
                tray.path, w.rectangle(tray.width, tray.height), centre, storey_at(floor), ids,
            )  # fmt: skip
        for lum in electrical.luminaires:
            if lum.story not in levels:
                continue
            floor = levels[lum.story]
            z_pt = floor + (lum.z if lum.z is not None else 2800.0)
            product = _box_product(
                w,
                "IfcLightFixture",
                "POINTSOURCE",
                f"luminaire:{lum.id}",
                f"{lum.type} {lum.id}",
                lum.id,
                (600.0, 600.0, 50.0),
                (lum.x, lum.y, z_pt),
                storey_at(floor),
            )
            ids[lum.id] = product.GlobalId
            w.mep_products.setdefault(lum.id, []).append(product)
    fire = getattr(mep, "fire", None)
    if fire is not None:
        for pump in fire.pumps:
            if pump.story not in levels or carried(pump):
                if getattr(pump, "equipment", None) and pump.equipment in w.mep_products:
                    w.mep_products[pump.id] = w.mep_products[pump.equipment]
                continue
            floor = levels[pump.story]
            product = _box_product(
                w, "IfcPump", "ENDSUCTION", f"fire:{pump.id}", pump.id, pump.id,
                (pump.length or 900.0, pump.width or 600.0, pump.height or 700.0),
                (pump.x, pump.y, floor), storey_at(floor),
            )  # fmt: skip
            ids[pump.id] = product.GlobalId
            w.mep_products.setdefault(pump.id, []).append(product)
        for riser in fire.risers:
            low, high = levels.get(riser.fromStory), levels.get(riser.toStory)
            if low is None or high is None or high <= low:
                continue
            diam = float(riser.diameter or _RISER_DIAMETER)
            profile = w.param_profile("IfcCircleProfileDef")
            profile.Radius = diam / 2
            product = w.entity("IfcPipeSegment", riser.id, f"fireRiser:{riser.id}", "RIGIDSEGMENT")
            product.Tag = riser.id
            w.extrusion(product, profile, high - low)
            w.place(product, _placement((riser.x, riser.y, low), (1, 0, 0), (0, 0, 1)))
            w.run(
                "spatial.assign_container", w.file, products=[product],
                relating_structure=storey_at(low),
            )  # fmt: skip
            ids[riser.id] = product.GlobalId
            w.mep_products.setdefault(riser.id, []).append(product)
        for main in fire.mains:
            if main.story not in levels:
                continue
            diam = float(main.diameter or _RISER_DIAMETER)
            profile = w.param_profile("IfcCircleProfileDef")
            profile.Radius = diam / 2
            floor = levels[main.story]
            top = soffit(main.story)
            centre = (
                floor + float(main.bottom) + diam / 2
                if main.bottom is not None
                else (top - _TRAY_HEADROOM - diam / 2 if top is not None else floor + 2700.0)
            )
            _run_segments(
                w, "IfcPipeSegment", "RIGIDSEGMENT", main.id, f"fireMain:{main.id}", main.path,
                profile, centre, storey_at(floor), ids,
            )  # fmt: skip
        for sh in fire.sprinklerHeads:
            if sh.story not in levels:
                continue
            floor = levels[sh.story]
            z_pt = floor + (sh.z if sh.z is not None else 2700.0)
            product = _box_product(
                w,
                "IfcFireSuppressionTerminal",
                "SPRINKLER",
                f"sprinkler:{sh.id}",
                sh.id,
                sh.id,
                (80.0, 80.0, 80.0),
                (sh.x, sh.y, z_pt),
                storey_at(floor),
            )
            ids[sh.id] = product.GlobalId
            w.mep_products.setdefault(sh.id, []).append(product)
        for sp in fire.sprinklerPipes:
            if sp.story not in levels or not sp.diameter:
                continue
            floor = levels[sp.story]
            prof = w.param_profile("IfcCircleProfileDef")
            prof.Radius = float(sp.diameter) / 2
            z_pt = floor + (sp.bottom if sp.bottom is not None else 2750.0)
            _run_segments(
                w,
                "IfcPipeSegment",
                "RIGIDSEGMENT",
                sp.id,
                f"firepipe:{sp.id}",
                sp.path,
                prof,
                z_pt,
                storey_at(floor),
                ids,
            )
        for dev in fire.alarmDevices:
            if dev.story not in levels:
                continue
            floor = levels[dev.story]
            ifc_cls, predef = (
                ("IfcAlarm", "BELL")
                if dev.kind in ("callPoint", "sounder", "panel")
                else ("IfcSensor", "SMOKESENSOR" if dev.kind == "smokeDetector" else "HEATSENSOR")
            )
            z_pt = floor + (1400.0 if dev.kind in ("callPoint", "panel") else 2800.0)
            product = _box_product(
                w,
                ifc_cls,
                predef,
                f"alarm:{dev.id}",
                dev.id,
                dev.id,
                (120.0, 120.0, 60.0),
                (dev.x, dev.y, z_pt),
                storey_at(floor),
            )
            ids[dev.id] = product.GlobalId
            w.mep_products.setdefault(dev.id, []).append(product)
    gas = getattr(mep, "gas", None)
    if gas is not None:
        for gp in gas.pipes:
            if gp.story not in levels or not gp.diameter:
                continue
            floor = levels[gp.story]
            prof = w.param_profile("IfcCircleProfileDef")
            prof.Radius = float(gp.diameter) / 2
            _run_segments(
                w,
                "IfcPipeSegment",
                "RIGIDSEGMENT",
                gp.id,
                f"gas:{gp.id}",
                gp.path,
                prof,
                floor + 2600.0,
                storey_at(floor),
                ids,
            )
    med = getattr(mep, "medicalGas", None)
    if med is not None:
        for mp_pipe in med.pipes:
            if mp_pipe.story not in levels or not mp_pipe.diameter:
                continue
            floor = levels[mp_pipe.story]
            prof = w.param_profile("IfcCircleProfileDef")
            prof.Radius = float(mp_pipe.diameter) / 2
            _run_segments(
                w,
                "IfcPipeSegment",
                "RIGIDSEGMENT",
                mp_pipe.id,
                f"medgas:{mp_pipe.id}",
                mp_pipe.path,
                prof,
                floor + 2650.0,
                storey_at(floor),
                ids,
            )


_IFC_SYSTEM_TYPES: dict[str, str] = {
    "supplyAir": "AIRCONDITIONING",
    "returnAir": "VENTILATION",
    "exhaustAir": "EXHAUST",
    "freshAir": "VENTILATION",
    "kitchenExhaust": "EXHAUST",
    "smokeExtract": "EXHAUST",
    "chilledWater": "CHILLEDWATER",
    "condenserWater": "CONDENSERWATER",
    "domesticColdWater": "DOMESTICCOLDWATER",
    "domesticHotWater": "DOMESTICHOTWATER",
    "sanitary": "SEWAGE",
    "vent": "VENT",
    "stormWater": "STORMWATER",
    "fireProtection": "FIREPROTECTION",
    "power": "ELECTRICAL",
    "cableTray": "ELECTRICAL",
}
_IFC_PORT_TYPES: dict[str, str] = {
    "duct": "DUCT",
    "pipe": "PIPE",
    "electrical": "CABLE",
    "cableTray": "CABLECARRIER",
}
_IFC_FLOW_DIR: dict[str, str] = {
    "out": "SOURCE",
    "in": "SINK",
    "bidirectional": "NOTDEFINED",
}


def _export_systems(
    w: _Writer,
    building: BuildingModel,
    mep: Any,
    skipped: list[str],
) -> None:
    """Exports logical MEP systems as ``IfcDistributionSystem`` and port connections as
    ``IfcDistributionPort`` + ``IfcRelConnectsPorts``."""
    from saengine.mep.systems import analyze_systems

    if not w.mep_products:
        return
    try:
        analysis = analyze_systems(mep, building)
    except Exception as error:  # noqa: BLE001 - system graph never blocks IFC geometry export
        skipped.append(f"MEP systems: {error}")
        return

    for sys in analysis.get("systems", []):
        products = [p for eid in sys.get("elements", []) for p in w.mep_products.get(eid, [])]
        if not products:
            continue
        sys_cls = "IfcSystem" if w.is_ifc2x3 else "IfcDistributionSystem"
        ifc_sys = w.run("system.add_system", w.file, ifc_class=sys_cls)
        ifc_sys.GlobalId = global_id(f"system:{sys['id']}")
        ifc_sys.Name = sys["name"]
        sys_type = _IFC_SYSTEM_TYPES.get(sys["classification"], "NOTDEFINED")
        if w.is_ifc2x3:
            ifc_sys.ObjectType = sys_type
        else:
            ifc_sys.PredefinedType = sys_type
        w.run("system.assign_system", w.file, products=products, system=ifc_sys)

    # Connect consecutive segments of multi-leg runs so every leg is part of the port chain.
    for eid, segs in w.mep_products.items():
        if len(segs) <= 1:
            continue
        for a, b in itertools.pairwise(segs):
            pa = w.run("system.add_port", w.file, element=a)
            pb = w.run("system.add_port", w.file, element=b)
            pa.Name, pb.Name = f"{eid}:seg-out", f"{eid}:seg-in"
            w.run("system.connect_port", w.file, port1=pa, port2=pb, direction="NOTDEFINED")

    # Add IfcDistributionPorts and IfcRelConnectsPorts for each connection.
    connectors_by_key = {f"{c['elementId']}:{c['id']}": c for c in analysis.get("connectors", [])}

    def _product_for(elem_id: str, port_id: str) -> Any:
        segs = w.mep_products.get(elem_id, [])
        if not segs:
            return None
        return segs[-1] if port_id == "end" else segs[0]

    for conn in analysis.get("connections", []):
        ca = connectors_by_key.get(conn["from"])
        cb = connectors_by_key.get(conn["to"])
        if not ca or not cb:
            continue
        pa_elem = _product_for(ca["elementId"], ca["id"])
        pb_elem = _product_for(cb["elementId"], cb["id"])
        if pa_elem is None or pb_elem is None:
            continue
        pa = w.run("system.add_port", w.file, element=pa_elem)
        pb = w.run("system.add_port", w.file, element=pb_elem)
        pa.Name = conn["from"]
        pb.Name = conn["to"]
        pa.FlowDirection = _IFC_FLOW_DIR.get(ca["direction"], "NOTDEFINED")
        pb.FlowDirection = _IFC_FLOW_DIR.get(cb["direction"], "NOTDEFINED")
        if not w.is_ifc2x3:
            pa.PredefinedType = _IFC_PORT_TYPES.get(ca["domain"], "NOTDEFINED")
            pb.PredefinedType = _IFC_PORT_TYPES.get(cb["domain"], "NOTDEFINED")
            pa.SystemType = _IFC_SYSTEM_TYPES.get(ca["classification"], "NOTDEFINED")
            pb.SystemType = _IFC_SYSTEM_TYPES.get(cb["classification"], "NOTDEFINED")
        direction = (
            "SOURCE"
            if ca["direction"] == "out" or cb["direction"] == "in"
            else "SINK"
            if ca["direction"] == "in" or cb["direction"] == "out"
            else "NOTDEFINED"
        )
        w.run("system.connect_port", w.file, port1=pa, port2=pb, direction=direction)


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
        w.mep_products.setdefault(item.id, []).append(product)

    for opening in mep.openings:
        host_element, host = elements.get(opening.host), products.get(opening.host)
        if host_element is None or host is None:
            skipped.append(f"{opening.id}: there is no beam, slab or wall '{opening.host}' to cut")
            continue
        if opening.kind == "opening" and isinstance(host_element, SlabElement | WallElement):
            continue  # cut with the building model's additions above
        width, height = opening.size
        if opening.shape == "circle":
            profile = w.param_profile("IfcCircleProfileDef")
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
        missing = [s for s in (stair.base, stair.top) if s not in levels]
        if missing:
            skipped.append(f"{stair.id}: no story '{missing[0]}'")
            continue
        if object_type is None or object_type.kind != "staircase":
            skipped.append(f"{stair.id}: '{stair.type}' is not a staircase type")
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
            products,
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
    products: dict[str, Any] | None = None,
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
    if products is not None:
        products[member_id] = product


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
        if pile.square:
            profile = w.rectangle(pile.diameter, pile.diameter)
        else:
            if pile.diameter not in circles:
                circle = w.param_profile("IfcCircleProfileDef")
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
    w: _Writer,
    area: AreaElement,
    storey_at: Any,
    ids: dict[str, str],
    skipped: list[str],
    products: dict[str, Any] | None = None,
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
    if products is not None:
        products[area.id] = product

"""The architecture (``05 Floor Plan/architecture.json``) in IFC4: export and import.

Export adds the architecture to the building model's IFC (:func:`saengine.library.ifc.export_ifc`):
walls as IfcWall with their wall type (IfcWallType), material layers (IfcMaterialLayerSetUsage),
centre line (the ``Axis`` representation) and body; doors and windows as IfcDoor and IfcWindow
filling IfcOpeningElements that void their walls; rooms as IfcSpace (their net floor extruded to
the next story) with their floor and ceiling finishes as IfcCovering (IfcRelCoversSpaces);
curtain walls as IfcCurtainWall, roofs as IfcRoof (their covering over the outline, flat:
the pitch is in the property set), ramps as IfcRamp (a sloped solid from the low end to the
high end) and railings as IfcRailing (GUARDRAIL) along their paths. Every
element carries ``SAEngine_Architecture`` (its id; a room's occupancy, wet flag and finishes), so
SAEngine reads its own file back exactly.

Import adopts an architect's IFC (Revit, ArchiCAD, ...): its walls, doors, windows and spaces
become the architecture's, on the floor plan's stories (matched by elevation), with a summary of
what was adopted and what was skipped (and why). Wall centre lines come from the ``Axis``
representation and the material layers when the file has them, else from the body's footprint;
types are matched to the architecture's by name, then by size, else added.
"""

from __future__ import annotations

import itertools
import math
import re
from typing import Any

import numpy as np

from saengine.library.architecture import (
    Architecture,
    ArchWall,
    Door,
    DoorType,
    WindowType,
    centre_line,
    offset_path,
    opening_size,
    point_along,
    railing_as_wall,
    roof_polygon,
    room_boundary,
    wall_levels,
)

PSET = "SAEngine_Architecture"

#: Thicknesses of a door leaf and a window frame drawn in the wall [mm].
_DOOR_LEAF = 40.0
_WINDOW_FRAME = 60.0
#: How far an opening runs past the wall's faces [mm].
_CLEARANCE = 10.0
#: A storey of the architect's file matches a floor-plan story this close [mm].
STORY_TOLERANCE = 50.0
#: A wall's top within this of the next story is "up to the next story" [mm].
TOP_TOLERANCE = 5.0

_DOOR_OPERATION = {
    "single": "SINGLE_SWING_LEFT",
    "double": "DOUBLE_DOOR_SINGLE_SWING",
    "sliding": "SLIDING_TO_LEFT",
}
_WINDOW_PARTITIONING = {
    "fixed": "SINGLE_PANEL",
    "casement": "SINGLE_PANEL",
    "sliding": "DOUBLE_PANEL_VERTICAL",
}

#: Unit weights [kN/m³] guessed from a material's name, for imported wall layers.
_UNIT_WEIGHTS = (
    (re.compile(r"brick|masonry|clay", re.IGNORECASE), 18.85),
    (re.compile(r"plaster|mortar|render|cement", re.IGNORECASE), 20.4),
    (re.compile(r"concrete|block", re.IGNORECASE), 24.0),
    (re.compile(r"gypsum|plasterboard|drywall", re.IGNORECASE), 10.0),
    (re.compile(r"glass", re.IGNORECASE), 25.0),
    (re.compile(r"timber|wood", re.IGNORECASE), 6.0),
    (re.compile(r"insulation|wool|foam", re.IGNORECASE), 0.5),
)
_DEFAULT_UNIT_WEIGHT = 18.85


# ───────────────────────────── export ─────────────────────────────


def export_architecture(
    w: Any,
    arch: Architecture,
    elevations: dict[str, float],
    storeys: dict[str, Any],
    storey_at: Any,
    ids: dict[str, str],
    skipped: list[str],
) -> None:
    """Adds ``arch`` to the IFC being written by ``w`` (:class:`saengine.library.ifc._Writer`);
    ``ids`` gets each element's GlobalId, ``skipped`` what could not be placed."""
    from saengine.library.ifc import _SI, _placement

    axis_context = w.run(
        "context.add_context",
        w.file,
        context_type="Model",
        context_identifier="Axis",
        target_view="GRAPH_VIEW",
        parent=w.body.ParentContext,
    )
    wall_types = {t.id: t for t in arch.wallTypes}
    ifc_types: dict[str, Any] = {}
    layer_sets: dict[str, Any] = {}

    def pset(product: Any, values: dict[str, Any]) -> None:
        props = w.run("pset.add_pset", w.file, product=product, name=PSET)
        w.run("pset.edit_pset", w.file, pset=props, properties=values)

    def element_type(ifc_class: str, type_id: str, name: str, **attributes: Any) -> Any:
        if type_id not in ifc_types:
            entity = w.entity(ifc_class, type_id, f"archtype:{type_id}")
            entity.Description = name
            for key, value in attributes.items():
                setattr(entity, key, value)
            ifc_types[type_id] = entity
        return ifc_types[type_id]

    walls: dict[str, tuple[Any, ArchWall, list[tuple[float, float]], float, float]] = {}
    for wall in arch.walls:
        wall_type = wall_types[wall.type]
        levels = wall_levels(wall, elevations)
        if levels is None:
            skipped.append(
                f"{wall.id}: its stories are not in the floor plan (or it needs a height)"
            )
            continue
        bottom, top = levels
        centre = centre_line(wall, wall_type)
        thickness = wall_type.thickness
        product = w.entity("IfcWall", wall.id, f"arch:{wall.id}", "STANDARD")
        product.Tag = wall.id
        product.ObjectType = wall_type.id
        product.Description = wall_type.name
        outline = _footprint_profile(w, centre, thickness, wall.id)
        w.extrusion(product, outline, top - bottom, None)  # the outline is in absolute x, y
        polyline = w.file.create_entity(
            "IfcPolyline",
            Points=[
                w.file.create_entity("IfcCartesianPoint", Coordinates=(float(x), float(y)))
                for x, y in centre
            ],
        )
        axis = w.file.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=axis_context,
            RepresentationIdentifier="Axis",
            RepresentationType="Curve2D",
            Items=[polyline],
        )
        product.Representation.Representations = (*product.Representation.Representations, axis)
        w.place(product, _placement((0, 0, bottom), (1, 0, 0), (0, 0, 1)))
        w.run(
            "spatial.assign_container",
            w.file,
            products=[product],
            relating_structure=storeys.get(wall.base) or storey_at(bottom),
        )

        w.run(
            "type.assign_type",
            w.file,
            related_objects=[product],
            relating_type=element_type(
                "IfcWallType", wall_type.id, wall_type.name, PredefinedType="STANDARD"
            ),
            should_map_representations=False,
        )
        if wall_type.id not in layer_sets:
            layer_set = w.run(
                "material.add_material_set",
                w.file,
                name=wall_type.name,
                set_type="IfcMaterialLayerSet",
            )
            for layer in wall_type.layers:
                material = w.run("material.add_material", w.file, name=layer.material)
                ifc_layer = w.run(
                    "material.add_layer", w.file, layer_set=layer_set, material=material
                )
                ifc_layer.LayerThickness = float(layer.thickness)
            layer_sets[wall_type.id] = layer_set
        w.run(
            "material.assign_material",
            w.file,
            products=[product],
            type="IfcMaterialLayerSetUsage",
            material=layer_sets[wall_type.id],
        )
        usage = _layer_usage(product)
        if usage is not None:
            # The layers start at the wall's right face (IFC lays them out to the left of the axis).
            usage.OffsetFromReferenceLine = -thickness / 2
            usage.DirectionSense = "POSITIVE"
        pset(
            product,
            {"Id": wall.id, "Height": float(top - bottom), "SitsOn": wall.structuralRef or ""},
        )
        ids[wall.id] = product.GlobalId
        walls[wall.id] = (product, wall, centre, bottom, thickness)

    for opening in [*arch.doors, *arch.windows]:
        host = walls.get(opening.wall)
        if host is None:
            skipped.append(f"{opening.id}: its wall {opening.wall} is not exported")
            continue
        product_wall, wall, centre, bottom, thickness = host
        width, height, sill = opening_size(arch, opening)
        (cx, cy), (dx, dy) = point_along(centre, opening.offset)
        is_door = isinstance(opening, Door)
        # Local X along the wall, Y across it, Z up; origin at the opening's centre on the floor or sill.
        origin = (cx, cy, bottom + sill)
        void = w.entity("IfcOpeningElement", opening.id, f"archopening:{opening.id}", "OPENING")
        w.extrusion(void, w.rectangle(width, thickness + 2 * _CLEARANCE), height, 5)
        w.place(void, _placement(origin, (dx, dy, 0.0), (0, 0, 1)))
        w.run("feature.add_feature", w.file, feature=void, element=product_wall)

        if is_door:
            door_type: DoorType = next(t for t in arch.doorTypes if t.id == opening.type)
            product = w.entity("IfcDoor", opening.id, f"arch:{opening.id}", "DOOR")
            product.OperationType = _DOOR_OPERATION[door_type.style]
            leaf = _DOOR_LEAF
            relating = element_type(
                "IfcDoorType",
                door_type.id,
                door_type.name,
                PredefinedType="DOOR",
                OperationType=_DOOR_OPERATION[door_type.style],
            )
        else:
            window_type: WindowType = next(t for t in arch.windowTypes if t.id == opening.type)
            product = w.entity("IfcWindow", opening.id, f"arch:{opening.id}", "WINDOW")
            product.PartitioningType = _WINDOW_PARTITIONING[window_type.style]
            leaf = _WINDOW_FRAME
            relating = element_type(
                "IfcWindowType",
                window_type.id,
                window_type.name,
                PredefinedType="WINDOW",
                PartitioningType=_WINDOW_PARTITIONING[window_type.style],
            )
        product.Tag = opening.id
        product.ObjectType = opening.type
        product.OverallWidth = float(width)
        product.OverallHeight = float(height)
        w.extrusion(product, w.rectangle(width, min(leaf, thickness)), height, 5)
        w.place(product, _placement(origin, (dx, dy, 0.0), (0, 0, 1)))
        w.run(
            "spatial.assign_container",
            w.file,
            products=[product],
            relating_structure=storeys.get(wall.base) or storey_at(bottom),
        )
        w.run(
            "type.assign_type",
            w.file,
            related_objects=[product],
            relating_type=relating,
            should_map_representations=False,
        )
        w.run("feature.add_filling", w.file, opening=void, element=product)
        values: dict[str, Any] = {"Id": opening.id, "Offset": float(opening.offset)}
        if is_door:
            values["Flip"] = bool(opening.flip)
        else:
            values["Sill"] = float(sill)
        pset(product, values)
        ids[opening.id] = product.GlobalId

    finishes = {t.id: t for t in arch.finishTypes}
    ordered = sorted(elevations.values())
    for room in arch.rooms:
        if room.story not in elevations:
            skipped.append(f"{room.id}: no story '{room.story}'")
            continue
        boundary = room_boundary(arch, room, elevations)
        if boundary is None:
            skipped.append(f"{room.id}: its point is not enclosed by walls or separators")
            continue
        net = boundary[1]
        level = elevations[room.story]
        above = [e for e in ordered if e > level]
        height = (above[0] - level) if above else 3000.0
        outline = [(x * _SI, y * _SI) for x, y in list(net.exterior.coords)]
        space = w.entity("IfcSpace", room.number or room.id, f"arch:{room.id}", "INTERNAL")
        space.LongName = room.name
        profile = w.run("profile.add_arbitrary_profile", w.file, profile=outline, name=room.id)
        w.extrusion(space, profile, height, None)
        w.place(space, _placement((0, 0, level), (1, 0, 0), (0, 0, 1)))
        storey = storeys.get(room.story) or storey_at(level)
        w.run("aggregate.assign_object", w.file, products=[space], relating_object=storey)
        pset(
            space,
            {
                "Id": room.id,
                "Number": room.number,
                "Occupancy": room.occupancy or "",
                "Wet": bool(room.wet),
                "FloorFinish": room.floorFinish or "",
                "WallFinish": room.wallFinish or "",
                "CeilingFinish": room.ceilingFinish or "",
                "NetArea": round(net.area / 1e6, 3),
            },
        )
        ids[room.id] = space.GlobalId

        coverings = []
        for finish_id, predefined, z in (
            (room.floorFinish, "FLOORING", level),
            (room.ceilingFinish, "CEILING", level + height),
        ):
            finish = finishes.get(finish_id) if finish_id else None
            if finish is None:
                continue
            key = f"{room.id}:{predefined.lower()}"
            covering = w.entity(
                "IfcCovering", f"{room.id} {finish.name}", f"arch:{key}", predefined
            )
            covering.ObjectType = finish.id
            profile = w.run("profile.add_arbitrary_profile", w.file, profile=outline, name=key)
            w.extrusion(covering, profile, finish.thickness, None)
            w.place(
                covering,
                _placement(
                    (0, 0, z - (finish.thickness if predefined == "CEILING" else 0)),
                    (1, 0, 0),
                    (0, 0, 1),
                ),
            )
            w.run(
                "spatial.assign_container", w.file, products=[covering], relating_structure=storey
            )
            coverings.append(covering)
            ids[key] = covering.GlobalId
        if coverings:
            w.file.create_entity(
                "IfcRelCoversSpaces",
                GlobalId=_guid(f"covers:{room.id}"),
                RelatingSpace=space,
                RelatedCoverings=coverings,
            )

    _export_extras(w, arch, elevations, storeys, storey_at, ids, skipped, pset)


def _export_extras(
    w: Any,
    arch: Architecture,
    elevations: dict[str, float],
    storeys: dict[str, Any],
    storey_at: Any,
    ids: dict[str, str],
    skipped: list[str],
    pset: Any,
) -> None:
    """Curtain walls, roofs, ramps and railings (T46), as :func:`export_architecture` does the
    walls: a body, a container story and ``SAEngine_Architecture``."""
    from saengine.library.ifc import _SI, _placement

    def contain(product: Any, story: str, level: float) -> None:
        w.run(
            "spatial.assign_container",
            w.file,
            products=[product],
            relating_structure=storeys.get(story) or storey_at(level),
        )

    def along_path(
        ifc_class: str, predefined: str, item: ArchWall, item_type: Any, label: str
    ) -> Any:
        levels = wall_levels(item, elevations)
        if levels is None:
            skipped.append(
                f"{item.id}: its stories are not in the floor plan (or it needs a height)"
            )
            return None
        bottom, top = levels
        centre = centre_line(item, item_type)
        product = w.entity(ifc_class, item.id, f"arch:{item.id}", predefined)
        product.Tag = item.id
        product.ObjectType = item_type.id
        product.Description = label
        w.extrusion(
            product, _footprint_profile(w, centre, item_type.thickness, item.id), top - bottom, None
        )
        w.place(product, _placement((0, 0, bottom), (1, 0, 0), (0, 0, 1)))
        contain(product, item.base, bottom)
        ids[item.id] = product.GlobalId
        return product

    curtain_types = {t.id: t for t in arch.curtainWallTypes}
    for curtain in arch.curtainWalls:
        kind = curtain_types[curtain.type]
        product = along_path("IfcCurtainWall", "USERDEFINED", curtain, kind, kind.name)
        if product is not None:
            product.ObjectType = kind.id
            pset(
                product,
                {
                    "Id": curtain.id,
                    "Weight": round(kind.weight, 3),
                    "MullionSpacing": float(kind.mullionSpacing),
                    "TransomSpacing": float(kind.transomSpacing),
                },
            )

    railing_types = {t.id: t for t in arch.railingTypes}
    for railing in arch.railings:
        kind = railing_types[railing.type]
        product = along_path(
            "IfcRailing", "GUARDRAIL", railing_as_wall(railing, kind), kind, kind.name
        )
        if product is not None:
            pset(product, {"Id": railing.id, "Weight": float(kind.weight)})

    roof_types = {t.id: t for t in arch.roofTypes}
    for roof in arch.roofs:
        if roof.story not in elevations:
            skipped.append(f"{roof.id}: no story '{roof.story}'")
            continue
        kind = roof_types[roof.type]
        polygon = roof_polygon(roof)
        if polygon.is_empty or polygon.geom_type != "Polygon":
            skipped.append(f"{roof.id}: its outline is not one polygon")
            continue
        level = elevations[roof.story] + roof.baseOffset
        product = w.entity(
            "IfcRoof", roof.id, f"arch:{roof.id}", "SHED_ROOF" if roof.slope else "FLAT_ROOF"
        )
        product.Tag = roof.id
        product.ObjectType = kind.id
        product.Description = kind.name
        outline = [(x * _SI, y * _SI) for x, y in list(polygon.exterior.coords)]
        profile = w.run("profile.add_arbitrary_profile", w.file, profile=outline, name=roof.id)
        w.extrusion(product, profile, kind.thickness, None)
        w.place(product, _placement((0, 0, level), (1, 0, 0), (0, 0, 1)))
        contain(product, roof.story, level)
        pset(
            product,
            {
                "Id": roof.id,
                "Slope": float(roof.slope),
                "Direction": float(roof.direction),
                "Occupancy": roof.occupancy or "",
            },
        )
        ids[roof.id] = product.GlobalId

    for ramp in arch.ramps:
        if ramp.story not in elevations:
            skipped.append(f"{ramp.id}: no story '{ramp.story}'")
            continue
        (x0, y0), (x1, y1) = ramp.start, ramp.end
        run = math.hypot(x1 - x0, y1 - y0)
        dx, dy = (x1 - x0) / run, (y1 - y0) / run
        level = elevations[ramp.story]
        product = w.entity("IfcRamp", ramp.id, f"arch:{ramp.id}", "STRAIGHT_RUN_RAMP")
        product.Tag = ramp.id
        # The side of the ramp (along it, up) extruded across its width: local X along the
        # ramp, Z across it (to its right), so Y = Z x X is up.
        side = [(0.0, 0.0), (run * _SI, 0.0), (run * _SI, max(ramp.rise, 50.0) * _SI)]
        if ramp.rise <= 0:
            side.append((0.0, 50.0 * _SI))  # a level ramp: a 50 mm topping
        profile = w.run(
            "profile.add_arbitrary_profile", w.file, profile=[*side, side[0]], name=ramp.id
        )
        w.extrusion(product, profile, ramp.width, None)
        origin = (x0 - dy * ramp.width / 2, y0 + dx * ramp.width / 2, level)
        w.place(product, _placement(origin, (dx, dy, 0.0), (dy, -dx, 0.0)))
        contain(product, ramp.story, level)
        pset(
            product,
            {
                "Id": ramp.id,
                "Rise": float(ramp.rise),
                "Width": float(ramp.width),
                "Finish": ramp.finish or "",
                "Occupancy": ramp.occupancy or "",
            },
        )
        ids[ramp.id] = product.GlobalId


def _guid(key: str) -> str:
    from saengine.library.ifc import global_id

    return global_id(key)


def _footprint_profile(
    w: Any, centre: list[tuple[float, float]], thickness: float, name: str
) -> Any:
    """The wall's plan outline as an IFC profile in absolute x, y: its centre line widened to
    both faces with mitred corners; a closed loop of walls is a ring (a profile with a void)."""
    from shapely.geometry import LineString

    from saengine.library.ifc import _SI

    shape = LineString(centre).buffer(thickness / 2, cap_style="flat", join_style="mitre")
    if shape.geom_type == "MultiPolygon":
        shape = max(shape.geoms, key=lambda g: g.area)

    def ring(coords: Any) -> list[tuple[float, float]]:
        return [(x * _SI, y * _SI) for x, y in coords]

    if shape.interiors:
        return w.run(
            "profile.add_arbitrary_profile_with_voids",
            w.file,
            outer_profile=ring(shape.exterior.coords),
            inner_profiles=[ring(i.coords) for i in shape.interiors],
            name=name,
        )
    return w.run(
        "profile.add_arbitrary_profile", w.file, profile=ring(shape.exterior.coords), name=name
    )


# ───────────────────────────── import ─────────────────────────────


def import_architecture(
    ifc_path: str, arch: Architecture, elevations: dict[str, float]
) -> tuple[Architecture, dict[str, Any]]:
    """Adopts the walls, doors, windows and spaces of the IFC at ``ifc_path`` into ``arch`` (on
    the floor plan's stories ``elevations``). Returns the new architecture and the summary:
    ``{"adopted": {kind: count}, "skipped": [why], "notes": [...]}``."""
    import ifcopenshell

    return _Importer(ifcopenshell.open(ifc_path), arch, elevations).run()


class _Importer:
    def __init__(self, ifc: Any, arch: Architecture, elevations: dict[str, float]) -> None:
        import ifcopenshell.util.unit

        self.ifc = ifc
        self.data = arch.model_dump(mode="json", by_alias=True, exclude_none=True)
        self.elevations = elevations
        self.scale = ifcopenshell.util.unit.calculate_unit_scale(ifc) * 1000  # file units -> mm
        self.adopted = {"walls": 0, "doors": 0, "windows": 0, "rooms": 0, "types": 0}
        self.skipped: list[str] = []
        self.notes: list[str] = []
        self.used = {
            i["id"]
            for key in ("walls", "doors", "windows", "rooms", "separators")
            for i in self.data[key]
        }
        # SAEngine's own export: only its architecture (the structure's walls are the floor plan's).
        self.own = any(_pset(e, PSET) for e in ifc.by_type("IfcWall"))
        self.storey_map: dict[int, str | None] = {}
        self.walls: dict[int, dict[str, Any]] = {}
        self.new_rooms: set[str] = set()
        self._settings: Any = None

    def run(self) -> tuple[Architecture, dict[str, Any]]:
        self.map_storeys()
        for wall in self.ifc.by_type("IfcWall"):
            self.wall(wall)
        for door in self.ifc.by_type("IfcDoor"):
            self.opening(door, "doors")
        for window in self.ifc.by_type("IfcWindow"):
            self.opening(window, "windows")
        for space in self.ifc.by_type("IfcSpace"):
            self.space(space)
        coverings = len(self.ifc.by_type("IfcCovering"))
        if coverings and not self.own:
            self.notes.append(f"{coverings} coverings not adopted: finishes are set per room.")
        arch = Architecture.model_validate(self.data)
        self.check_rooms(arch)
        summary = {"adopted": self.adopted, "skipped": self.skipped, "notes": self.notes}
        return arch, summary

    # ── storeys ──

    def map_storeys(self) -> None:
        import ifcopenshell.util.placement

        for storey in self.ifc.by_type("IfcBuildingStorey"):
            if storey.Elevation is not None:
                level = float(storey.Elevation) * self.scale
            else:
                level = (
                    float(
                        ifcopenshell.util.placement.get_local_placement(storey.ObjectPlacement)[
                            2, 3
                        ]
                    )
                    * self.scale
                )
            match = min(self.elevations.items(), key=lambda kv: abs(kv[1] - level), default=None)
            if match is not None and abs(match[1] - level) <= STORY_TOLERANCE:
                self.storey_map[storey.id()] = match[0]
            else:
                self.storey_map[storey.id()] = None
                self.notes.append(
                    f"Storey {storey.Name or storey.id()} at {level:+.0f} mm has no floor-plan story "
                    f"within {STORY_TOLERANCE:.0f} mm: its elements are skipped."
                )

    def story_of(self, element: Any) -> str | None:
        import ifcopenshell.util.element

        container = ifcopenshell.util.element.get_container(element)
        if container is None:
            parent = ifcopenshell.util.element.get_aggregate(element)
            container = parent if parent is not None and parent.is_a("IfcBuildingStorey") else None
        return self.storey_map.get(container.id()) if container is not None else None

    # ── geometry ──

    def shape(self, element: Any) -> np.ndarray | None:
        """The element's body vertices in world mm (n x 3), or None when it has no geometry."""
        import ifcopenshell.geom

        if self._settings is None:
            self._settings = ifcopenshell.geom.settings()
            self._settings.set("use-world-coords", True)
            self._settings.set("disable-opening-subtractions", True)
        try:
            shape = ifcopenshell.geom.create_shape(self._settings, element, _body(element))
        except Exception:  # noqa: BLE001 - any element IfcOpenShell cannot mesh is skipped
            return None
        verts = np.array(shape.geometry.verts, dtype=float).reshape(-1, 3)
        # Geometry comes in metres (the iterator converts to SI).
        return verts * 1000.0 if len(verts) else None

    def placement(self, element: Any) -> np.ndarray:
        import ifcopenshell.util.placement

        matrix = np.array(
            ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement), dtype=float
        )
        matrix[:3, 3] *= self.scale
        return matrix

    def new_id(self, preferred: str | None, prefix: str) -> str:
        candidate = re.sub(r"[^A-Za-z0-9._-]", "", preferred or "")[:64]
        if not candidate or candidate in self.used:
            n = 1
            while f"{prefix}{n}" in self.used:
                n += 1
            candidate = f"{prefix}{n}"
        self.used.add(candidate)
        return candidate

    # ── walls ──

    def wall(self, wall: Any) -> None:
        label = wall.Name or wall.GlobalId
        own = _pset(wall, PSET)
        if self.own and not own:
            return  # a structural wall of SAEngine's own export: the floor plan has it
        story = self.story_of(wall)
        if story is None:
            self.skipped.append(f"Wall {label}: not on a floor-plan story")
            return
        layers = _layers(wall)
        thickness = sum(t for _, t in layers) * self.scale if layers else None
        centre, body_thickness = self.wall_centre(wall, layers)
        verts = self.shape(wall)
        if centre is None or verts is None:
            self.skipped.append(f"Wall {label}: its geometry could not be read")
            return
        thickness = thickness or body_thickness
        if not thickness or thickness <= 0:
            self.skipped.append(f"Wall {label}: no thickness")
            return
        bottom, top = float(verts[:, 2].min()), float(verts[:, 2].max())
        level = self.elevations[story]
        above = sorted(e for e in self.elevations.values() if e > level)
        record: dict[str, Any] = {
            "id": self.new_id(own.get("Id") or wall.Tag, "AW"),
            "type": self.wall_type(wall, layers, thickness),
            "base": story,
            "path": [[round(x, 1), round(y, 1)] for x, y in centre],
        }
        if abs(bottom - level) > 0.5:
            record["baseOffset"] = round(bottom - level, 1)
        if not above or abs(top - above[0]) > TOP_TOLERANCE:
            record["height"] = round(top - bottom, 1)
        if own.get("SitsOn"):
            record["structuralRef"] = own["SitsOn"]
        self.data["walls"].append(record)
        self.walls[wall.id()] = {"id": record["id"], "centre": centre, "bottom": bottom}
        self.adopted["walls"] += 1

    def wall_centre(
        self, wall: Any, layers: list[tuple[str, float]]
    ) -> tuple[list[tuple[float, float]] | None, float | None]:
        """The wall's centre line in world mm, from its axis and layers, else its body footprint;
        and the thickness of the footprint (None from the axis)."""
        import ifcopenshell.util.representation

        axis = ifcopenshell.util.representation.get_representation(wall, "Model", "Axis")
        points = _curve_points(axis.Items[0]) if axis is not None and axis.Items else None
        if points is not None and len(points) >= 2:
            matrix = self.placement(wall)
            world = [
                tuple((matrix @ np.array([x * self.scale, y * self.scale, 0.0, 1.0]))[:2])
                for x, y in points
            ]
            # Layers sit from OffsetFromReferenceLine to the left of the axis (DirectionSense POSITIVE).
            usage = _layer_usage(wall)
            if usage is not None and layers:
                thickness = sum(t for _, t in layers) * self.scale
                sense = 1.0 if usage.DirectionSense != "NEGATIVE" else -1.0
                shift = sense * (
                    float(usage.OffsetFromReferenceLine or 0) * self.scale + thickness / 2
                )
                world = offset_path([list(p) for p in world], shift)
            return [(float(x), float(y)) for x, y in world], None
        verts = self.shape(wall)
        if verts is None:
            return None, None
        from shapely.geometry import MultiPoint

        rectangle = MultiPoint([tuple(v[:2]) for v in verts]).minimum_rotated_rectangle
        if rectangle.geom_type != "Polygon":
            return None, None
        corners = list(rectangle.exterior.coords)[:4]
        sides = [(corners[i], corners[(i + 1) % 4]) for i in range(4)]
        long_side = max(sides, key=lambda s: math.dist(*s))
        short = min(math.dist(*s) for s in sides)
        (ax, ay), (bx, by) = long_side
        length = math.dist(long_side[0], long_side[1]) or 1.0
        nx, ny = -(by - ay) / length, (bx - ax) / length
        cx, cy = rectangle.centroid.x, rectangle.centroid.y
        # The long side moved to the rectangle's middle.
        mx, my = (ax + bx) / 2, (ay + by) / 2
        d = (cx - mx) * nx + (cy - my) * ny
        return [(ax + nx * d, ay + ny * d), (bx + nx * d, by + ny * d)], short

    def wall_type(self, wall: Any, layers: list[tuple[str, float]], thickness: float) -> str:
        import ifcopenshell.util.element

        ifc_type = ifcopenshell.util.element.get_type(wall)
        name = (ifc_type.Name if ifc_type is not None else None) or wall.ObjectType or ""
        existing = self.data["wallTypes"]
        for t in existing:
            if (
                t["id"] == name
                and abs(sum(layer["thickness"] for layer in t["layers"]) - thickness) < 1
            ):
                return t["id"]
        for t in existing:
            if abs(sum(layer["thickness"] for layer in t["layers"]) - thickness) < 1 and len(
                t["layers"]
            ) == max(1, len(layers)):
                return t["id"]
        type_id = self.type_id(name, f"IW{round(thickness)}", existing)
        if layers:
            new_layers = [
                {
                    "material": material or "Wall",
                    "thickness": round(t * self.scale, 1),
                    "unitWeight": _unit_weight(material),
                }
                for material, t in layers
            ]
        else:
            new_layers = [
                {
                    "material": "Wall",
                    "thickness": round(thickness, 1),
                    "unitWeight": _DEFAULT_UNIT_WEIGHT,
                }
            ]
        description = (
            (ifc_type.Description if ifc_type is not None else None)
            or name
            or f"Wall {round(thickness)} mm"
        )
        existing.append({"id": type_id, "name": description, "layers": new_layers})
        self.adopted["types"] += 1
        if any(
            _unit_weight(m) == _DEFAULT_UNIT_WEIGHT
            and not re.search("brick", m or "", re.IGNORECASE)
            for m, _ in layers or [("", 0)]
        ):
            self.notes.append(
                f"Wall type {type_id}: unit weights guessed from the material names; check them."
            )
        return type_id

    def type_id(self, name: str, fallback: str, existing: list[dict[str, Any]]) -> str:
        ids = {t["id"] for t in existing}
        candidate = re.sub(r"[^A-Za-z0-9._-]", "", name)[:64] or fallback
        base, n = candidate, 2
        while candidate in ids:
            candidate = f"{base}-{n}"[:64]
            n += 1
        return candidate

    # ── doors and windows ──

    def opening(self, element: Any, group: str) -> None:
        import ifcopenshell.util.element

        kind = "Door" if group == "doors" else "Window"
        label = element.Name or element.GlobalId
        own = _pset(element, PSET)
        if self.own and not own:
            return
        host = None
        for fills in element.FillsVoids or ():
            opening = fills.RelatingOpeningElement
            for voids in opening.VoidsElements or ():
                host = voids.RelatingBuildingElement
        if host is None:
            self.skipped.append(f"{kind} {label}: not in a wall")
            return
        wall = self.walls.get(host.id())
        if wall is None:
            self.skipped.append(f"{kind} {label}: its wall was not adopted")
            return
        verts = self.shape(element)
        if verts is None:
            self.skipped.append(f"{kind} {label}: its geometry could not be read")
            return
        centre = wall["centre"]
        middle = (
            (verts[:, 0].min() + verts[:, 0].max()) / 2,
            (verts[:, 1].min() + verts[:, 1].max()) / 2,
        )
        offset, direction = _project(centre, middle)
        along = verts[:, :2] @ np.array(direction)
        width = (
            float(element.OverallWidth) * self.scale
            if element.OverallWidth
            else float(along.max() - along.min())
        )
        height = (
            float(element.OverallHeight) * self.scale
            if element.OverallHeight
            else float(verts[:, 2].max() - verts[:, 2].min())
        )
        if own.get("Offset") is not None:
            offset = float(own["Offset"])
        ifc_type = ifcopenshell.util.element.get_type(element)
        name = (ifc_type.Name if ifc_type is not None else None) or element.ObjectType or ""
        record: dict[str, Any] = {
            "id": self.new_id(own.get("Id") or element.Tag, "D" if group == "doors" else "W"),
            "wall": wall["id"],
            "offset": round(offset, 1),
        }
        if group == "doors":
            record["type"] = self.door_type(name, width, height, element)
            if own.get("Flip"):
                record["flip"] = True
        else:
            sill = (
                float(own["Sill"])
                if own.get("Sill") is not None
                else float(verts[:, 2].min()) - wall["bottom"]
            )
            record["type"] = self.window_type(name, width, height, sill)
            window_sill = next(
                t["sill"] for t in self.data["windowTypes"] if t["id"] == record["type"]
            )
            if abs(window_sill - sill) > 1:
                record["sill"] = round(max(0.0, sill), 1)
        self.data[group].append(record)
        self.adopted[group] += 1

    def door_type(self, name: str, width: float, height: float, element: Any) -> str:
        existing = self.data["doorTypes"]
        operation = str(getattr(element, "OperationType", "") or "")
        style = (
            "double" if "DOUBLE" in operation else "sliding" if "SLIDING" in operation else "single"
        )
        return self.sized_type(existing, name, width, height, {"style": style}, "D")

    def window_type(self, name: str, width: float, height: float, sill: float) -> str:
        existing = self.data["windowTypes"]
        return self.sized_type(
            existing,
            name,
            width,
            height,
            {"style": "sliding", "sill": round(max(0.0, sill), 1)},
            "W",
        )

    def sized_type(
        self,
        existing: list[dict[str, Any]],
        name: str,
        width: float,
        height: float,
        extra: dict[str, Any],
        prefix: str,
    ) -> str:
        def fits(t: dict[str, Any]) -> bool:
            return abs(t["width"] - width) < 5 and abs(t["height"] - height) < 5

        for t in existing:
            if t["id"] == name and fits(t):
                return t["id"]
        for t in existing:
            if fits(t):
                return t["id"]
        type_id = self.type_id(name, f"{prefix}{round(width)}x{round(height)}", existing)
        existing.append(
            {
                "id": type_id,
                "name": name or f"{round(width)} x {round(height)}",
                "width": round(width, 1),
                "height": round(height, 1),
                **extra,
            }
        )
        self.adopted["types"] += 1
        return type_id

    # ── spaces ──

    def space(self, space: Any) -> None:
        label = space.LongName or space.Name or space.GlobalId
        own = _pset(space, PSET)
        story = self.story_of(space)
        if story is None:
            self.skipped.append(f"Space {label}: not on a floor-plan story")
            return
        verts = self.shape(space)
        if verts is None:
            self.skipped.append(f"Space {label}: its geometry could not be read")
            return
        point = _inside_point(space, verts)
        if point is None:
            self.skipped.append(f"Space {label}: no floor outline")
            return
        record: dict[str, Any] = {
            "id": self.new_id(own.get("Id"), "R"),
            "story": story,
            "point": [round(point[0], 1), round(point[1], 1)],
            "name": space.LongName or space.Name or "Room",
            "number": own.get("Number", space.Name if space.LongName else "") or "",
        }
        if own.get("Occupancy"):
            record["occupancy"] = own["Occupancy"]
        if own.get("Wet"):
            record["wet"] = True
        finishes = {t["id"]: t["kind"] for t in self.data["finishTypes"]}
        for field in ("FloorFinish", "WallFinish", "CeilingFinish"):
            finish = own.get(field)
            if finish and finish in finishes:
                record[field[0].lower() + field[1:]] = finish
        self.data["rooms"].append(record)
        self.new_rooms.add(record["id"])
        self.adopted["rooms"] += 1

    def check_rooms(self, arch: Architecture) -> None:
        for room in arch.rooms:
            if room.id in self.new_rooms and room_boundary(arch, room, self.elevations) is None:
                self.notes.append(
                    f"Room {room.id} ({room.name}): not enclosed by the walls; add room separators."
                )


def _pset(element: Any, name: str) -> dict[str, Any]:
    import ifcopenshell.util.element

    return ifcopenshell.util.element.get_pset(element, name) or {}


def _layer_usage(element: Any) -> Any:
    import ifcopenshell.util.element

    material = ifcopenshell.util.element.get_material(element, should_skip_usage=False)
    return material if material is not None and material.is_a("IfcMaterialLayerSetUsage") else None


def _layers(element: Any) -> list[tuple[str, float]]:
    """The wall's material layers (name, thickness in file units), from its usage or type."""
    import ifcopenshell.util.element

    material = ifcopenshell.util.element.get_material(element, should_skip_usage=True)
    if material is None or not material.is_a("IfcMaterialLayerSet"):
        return []
    return [
        (layer.Material.Name if layer.Material is not None else "", float(layer.LayerThickness))
        for layer in material.MaterialLayers
        if layer.LayerThickness
    ]


def _curve_points(curve: Any) -> list[tuple[float, float]] | None:
    if curve.is_a("IfcPolyline"):
        return [(float(p.Coordinates[0]), float(p.Coordinates[1])) for p in curve.Points]
    if curve.is_a("IfcIndexedPolyCurve"):
        return [(float(x), float(y)) for x, y, *_ in curve.Points.CoordList]
    if curve.is_a("IfcTrimmedCurve") and curve.BasisCurve.is_a("IfcLine"):
        trims = [t for t in (curve.Trim1, curve.Trim2)]
        points = []
        for trim in trims:
            point = next(
                (t for t in trim if hasattr(t, "is_a") and t.is_a("IfcCartesianPoint")), None
            )
            if point is None:
                return None
            points.append((float(point.Coordinates[0]), float(point.Coordinates[1])))
        return points
    return None


def _project(
    points: list[tuple[float, float]], p: tuple[float, float]
) -> tuple[float, tuple[float, float]]:
    """The distance along a polyline to the point nearest ``p``, and the direction there."""
    best = (math.inf, 0.0, (1.0, 0.0))
    travelled = 0.0
    for (x1, y1), (x2, y2) in itertools.pairwise(points):
        length = math.hypot(x2 - x1, y2 - y1)
        if not length:
            continue
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        t = min(max((p[0] - x1) * ux + (p[1] - y1) * uy, 0.0), length)
        d = math.hypot(x1 + ux * t - p[0], y1 + uy * t - p[1])
        if d < best[0]:
            best = (d, travelled + t, (ux, uy))
        travelled += length
    return best[1], best[2]


def _inside_point(space: Any, verts: np.ndarray) -> tuple[float, float] | None:
    """A point inside the space's floor: the union of its body's faces seen from above."""
    import ifcopenshell.geom
    from shapely.geometry import MultiPoint, Polygon
    from shapely.ops import unary_union

    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    try:
        shape = ifcopenshell.geom.create_shape(settings, space, _body(space))
        faces = np.array(shape.geometry.faces, dtype=int).reshape(-1, 3)
    except Exception:  # noqa: BLE001
        faces = np.zeros((0, 3), dtype=int)
    triangles = []
    for a, b, c in faces:
        polygon = Polygon([tuple(verts[i][:2]) for i in (a, b, c)])
        if polygon.is_valid and polygon.area > 1.0:
            triangles.append(polygon)
    outline = (
        unary_union(triangles)
        if triangles
        else MultiPoint([tuple(v[:2]) for v in verts]).convex_hull
    )
    if outline.is_empty or outline.area <= 0:
        return None
    point = outline.representative_point()
    return float(point.x), float(point.y)


def _unit_weight(material: str | None) -> float:
    for pattern, weight in _UNIT_WEIGHTS:
        if material and pattern.search(material):
            return weight
    return _DEFAULT_UNIT_WEIGHT


def architecture_summary(arch: Architecture) -> dict[str, int]:
    return {
        "walls": len(arch.walls),
        "doors": len(arch.doors),
        "windows": len(arch.windows),
        "rooms": len(arch.rooms),
        "curtainWalls": len(arch.curtainWalls),
        "roofs": len(arch.roofs),
        "ramps": len(arch.ramps),
        "railings": len(arch.railings),
    }


def _body(element: Any) -> Any:
    """The element's Body representation (not its Axis or FootPrint), if it has one."""
    import ifcopenshell.util.representation

    body = ifcopenshell.util.representation.get_representation(element, "Model", "Body")
    if body is not None:
        return body
    representations = element.Representation.Representations if element.Representation else ()
    return next(
        (r for r in representations if r.RepresentationIdentifier not in ("Axis", "FootPrint")),
        None,
    )

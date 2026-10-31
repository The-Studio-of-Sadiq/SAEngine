"""The architecture (``05 Floor Plan/architecture.json``) in the bill of quantities.

:func:`measure_architecture` adds to a bill being measured (:mod:`saengine.boq.quantities`):

- brickwork (m³, masonry group) per wall type and masonry layer, over the walls' net faces;
- plaster to walls (m², both faces where the wall type has a plaster layer, per thickness);
- room finishes per finish type (m²): floor finishes and ceilings over each room's net floor
  (inside the wall faces), wall finishes over the room's walls to its clear height;
- doors and windows counted per type (nr), with their sizes;
- the cement and sand of the brickwork's mortar and of the plaster, from their mixes in 03
  Materials (the materials take-off of the bill);
- curtain walls (m² per curtain wall type, each along its centre line over its full height);
- roof coverings (m² of roof surface along the slope, per roof type and layer);
- ramps (their filling in m³, their floor finish in m² along the slope);
- railings (m run per railing type).

The walls are measured where the analysis model loads them (the pieces of
:func:`saengine.fem.architecture_loads.architecture_loads`, one geometry for both): a wall's
length along its centre line and its clear height (to the beam or slab above). The part of a
wall over a floor-plan wall is that wall's, measured with the building model's walls as before:
never both.
"""

from __future__ import annotations

from typing import Any

from saengine.fem import architecture_loads as al
from saengine.library import architecture as arch_lib
from saengine.library.materials import Category

MM = 1e-3
MM2 = 1e-6

#: Openings not deducted from brickwork, up to this area [m²]; from plaster, up to the first;
#: one face deducted up to the second, both faces above it (no jambs, soffits or sills added).
#: The South Asian method of measurement (IS 1200 Parts 3 and 12), which the PWD schedules of
#: rates measure by; not BNBC values.
BRICKWORK_OPENING = 0.1
PLASTER_OPENING = 0.5
PLASTER_ONE_FACE = 3.0

ARCHITECTURE_CONVENTIONS = [
    (
        "Architecture of 05 Floor Plan: brickwork in m³ per wall type and masonry layer, each "
        "wall along its centre line to its clear height (to the soffit of the beam or the slab "
        "above), less openings of more than "
        f"{BRICKWORK_OPENING:g} m²; plaster to walls in m² on each face the wall type has a "
        f"plaster layer, openings up to {PLASTER_OPENING:g} m² not deducted, up to "
        f"{PLASTER_ONE_FACE:g} m² deducted from one face, larger ones from both, jambs and "
        "soffits not added (the method of measurement of IS 1200 Parts 3 and 12, as the PWD "
        "schedules measure; not BNBC values). Room floor finishes and ceilings over the net "
        "floor inside the wall faces; room wall finishes over the room's net perimeter to its "
        "clear height less the doors and windows in it, on top of the walls' plaster (the "
        "plaster is the wall types'; give the rooms the paint or tiles). Doors and windows are "
        "counted per type. The part of a wall over a floor-plan wall is that wall's and is "
        "measured with the building model's walls, never both. The mortar of brickwork and "
        "plaster is taken off by its mix."
    ),
    (
        "Curtain walls in m² along their centre line over their full height (base to top, past "
        "the slab edges); roof coverings in m² of the roof's surface along its slope, per layer "
        "of the roof type; ramps' filling in m³ (footprint times half the rise) and their floor "
        "finish in m² along the slope; railings in metres run along their path."
    ),
]


def _is_plaster(layer: arch_lib.WallLayer) -> bool:
    return "plaster" in layer.material.lower()


def measure_architecture(measure: Any, arch: arch_lib.Architecture, objects: Any) -> bool:
    """Adds the architecture's items to ``measure`` (a :class:`saengine.boq.quantities.
    _Measure`); whether there was anything to measure."""
    if not has_content(arch):
        return False
    building = measure.building
    bill = measure.bill
    loads = al.architecture_loads(arch, building, objects, "architecture")
    types = {t.id: t for t in arch.wallTypes}
    masonry = _masonry_material(measure)
    plaster_mortar = _plaster_mortar(measure, masonry)

    sizes: dict[str, tuple[float, float, float]] = {}
    hosted: dict[str, list[Any]] = {}
    for opening in [*arch.doors, *arch.windows]:
        sizes[opening.id] = arch_lib.opening_size(arch, opening)
        hosted.setdefault(opening.wall, []).append(opening)

    by_wall: dict[str, list[dict[str, Any]]] = {}
    for row in loads.wall_rows:
        if row["on"] != "structural" and row.get("height_m"):
            by_wall.setdefault(row["wall"], []).append(row)
    unmeasured_layers: set[str] = set()
    for wall in arch.walls:
        rows = by_wall.get(wall.id)
        if not rows:
            continue
        wall_type = types[wall.type]
        gross = sum(r["length_m"] * r["height_m"] for r in rows)  # m²
        height = max(r["height_m"] for r in rows)
        areas = [
            sizes[o.id][0] * MM * min(sizes[o.id][1] * MM, height) for o in hosted.get(wall.id, [])
        ]
        net_brick = max(0.0, gross - sum(a for a in areas if a > BRICKWORK_OPENING))
        one_face = sum(a for a in areas if PLASTER_OPENING < a <= PLASTER_ONE_FACE)
        both_faces = sum(a for a in areas if a > PLASTER_ONE_FACE)
        story = wall.base
        for k, layer in enumerate(wall_type.layers):
            if _is_plaster(layer):
                face = "left" if k == 0 else "right" if k == len(wall_type.layers) - 1 else None
                if face is None:
                    continue
                # One-face deductions are taken from the left face.
                area = gross - both_faces - (one_face if face == "left" else 0.0)
                description = f"Cement plaster {layer.thickness:g} mm to walls"
                bill.add(
                    "finishes",
                    (1, round(layer.thickness, 1)),
                    description,
                    "m2",
                    wall.id,
                    area,
                    story=story,
                    detail=f"{wall_type.id}, {face} face",
                    kind="plaster",
                )
                if plaster_mortar is not None:
                    measure.mortar_volumes.append(
                        (wall.id, story, area * layer.thickness * MM, plaster_mortar, description)
                    )
                continue
            material = _layer_material(measure, layer, masonry)
            if material is None:
                unmeasured_layers.add(layer.material)
                continue
            bill.add(
                "masonry",
                (90, wall_type.id, layer.material),
                f"Brickwork: {layer.material} {layer.thickness:g} mm in {wall_type.name} "
                f"({wall_type.id})",
                "m3",
                wall.id,
                net_brick * layer.thickness * MM,
                story=story,
                material=material.id,
                kind="wall",
            )
    if unmeasured_layers:
        measure.notes.append(
            "Architecture: no masonry material in 03 Materials for the wall layers "
            f"{', '.join(sorted(unmeasured_layers))}; their brickwork is not measured."
        )

    _rooms(measure, arch, building, hosted, sizes)
    _extras(measure, arch, building)

    for opening in [*arch.doors, *arch.windows]:
        door = isinstance(opening, arch_lib.Door)
        type_ = next(
            t for t in (arch.doorTypes if door else arch.windowTypes) if t.id == opening.type
        )
        wall = next(w for w in arch.walls if w.id == opening.wall)
        bill.add(
            "finishes",
            (3 if door else 4, type_.id),
            f"{'Door' if door else 'Window'} {type_.id}: {type_.name}, {type_.width:g} × "
            f"{type_.height:g} mm ({type_.style})",
            "nr",
            opening.id,
            1.0,
            story=wall.base,
            kind="door" if door else "window",
        )
    return True


def _rooms(
    measure: Any,
    arch: arch_lib.Architecture,
    building: Any,
    hosted: dict[str, list[Any]],
    sizes: dict[str, tuple[float, float, float]],
) -> None:
    """The floor, wall and ceiling finishes of the rooms."""
    from shapely.geometry import Point, Polygon

    from saengine.library.bim import SlabElement

    finishes = {t.id: t for t in arch.finishTypes}
    elevations = {s.id: s.elevation for s in building.stories}
    levels = sorted(set(elevations.values()))
    wall_types = {t.id: t for t in arch.wallTypes}
    centres = {
        o.id: arch_lib.point_along(arch_lib.centre_line(w, wall_types[w.type]), o.offset)[0]
        for w in arch.walls
        for o in hosted.get(w.id, [])
    }
    thickness = {
        o.id: wall_types[w.type].thickness for w in arch.walls for o in hosted.get(w.id, [])
    }
    for room in arch.rooms:
        if room.story not in elevations:
            continue
        found = arch_lib.room_boundary(arch, room, elevations)
        if found is None:
            continue
        _, net = found
        area = net.area * MM2
        floor = elevations[room.story]
        above = [z for z in levels if z > floor + 1]
        height = 0.0
        if above:
            height = above[0] - floor
            slab = next(
                (
                    e
                    for e in building.elements
                    if isinstance(e, SlabElement)
                    and abs(e.elevation - above[0]) < 1
                    and Polygon(e.boundary).covers(Point(room.point))
                ),
                None,
            )
            if slab is not None:
                height -= float(getattr(measure.types.get(slab.type), "thickness", 0.0) or 0.0)
        label = f"{room.name} {room.number}".strip()
        for field, order in (("floorFinish", 2.1), ("ceilingFinish", 2.3)):
            finish = finishes.get(getattr(room, field) or "")
            if finish is None:
                continue
            what = "Floor finish" if field == "floorFinish" else "Ceiling"
            measure.bill.add(
                "finishes",
                (order, finish.id),
                f"{what}: {finish.name} ({finish.id}), {finish.thickness:g} mm",
                "m2",
                room.id,
                area,
                story=room.story,
                detail=label,
                kind=finish.kind,
            )
            if field == "floorFinish" and room.wet and finish.sunkFilling:
                measure.bill.add(
                    "finishes",
                    (2.2, finish.id),
                    f"Sunk slab filling under {finish.name} ({finish.id}), "
                    f"{finish.sunkFilling:g} mm",
                    "m3",
                    room.id,
                    area * finish.sunkFilling * MM,
                    story=room.story,
                    detail=label,
                    kind="filling",
                )
        finish = finishes.get(room.wallFinish or "")
        if finish is not None and height > 0:
            boundary = net.exterior
            openings = sum(
                sizes[o][0] * MM * min(sizes[o][1], height) * MM
                for o, xy in centres.items()
                if boundary.distance(Point(xy)) <= thickness[o] / 2 + 5
            )
            measure.bill.add(
                "finishes",
                (2.25, finish.id),
                f"Wall finish: {finish.name} ({finish.id}), {finish.thickness:g} mm",
                "m2",
                room.id,
                max(0.0, boundary.length * MM * height * MM - openings),
                story=room.story,
                detail=label,
                kind=finish.kind,
            )


def _extras(measure: Any, arch: arch_lib.Architecture, building: Any) -> None:
    """The curtain walls, roof coverings, ramps and railings (T46)."""
    import itertools
    import math

    elevations = {s.id: s.elevation for s in building.stories}
    bill = measure.bill
    curtain_types = {t.id: t for t in arch.curtainWallTypes}
    for curtain in arch.curtainWalls:
        levels = arch_lib.wall_levels(curtain, elevations)
        if levels is None:
            continue
        kind = curtain_types[curtain.type]
        length = sum(math.dist(a, b) for a, b in itertools.pairwise(curtain.path))
        bill.add(
            "finishes",
            (5, kind.id),
            f"Curtain wall {kind.id}: {kind.name}, glass {kind.glassThickness:g} mm, mullions at "
            f"{kind.mullionSpacing:g} mm, transoms at {kind.transomSpacing:g} mm",
            "m2",
            curtain.id,
            length * MM * (levels[1] - levels[0]) * MM,
            story=curtain.base,
            kind="curtainWall",
        )
    roof_types = {t.id: t for t in arch.roofTypes}
    for roof in arch.roofs:
        if roof.story not in elevations:
            continue
        kind = roof_types[roof.type]
        _, surface = arch_lib.roof_area(roof)
        for layer in kind.layers:
            bill.add(
                "finishes",
                (6, kind.id, layer.material),
                f"Roof covering: {layer.material} {layer.thickness:g} mm in {kind.name} "
                f"({kind.id})",
                "m2",
                roof.id,
                surface * MM2,
                story=roof.story,
                detail=f"{roof.slope:g}° pitch" if roof.slope else "flat",
                kind="roof",
            )
    finishes = {t.id: t for t in arch.finishTypes}
    for ramp in arch.ramps:
        if ramp.story not in elevations:
            continue
        footprint = arch_lib.ramp_polygon(ramp).area  # mm²
        run = math.dist(ramp.start, ramp.end)
        if ramp.rise > 0 and ramp.fillUnitWeight > 0:
            bill.add(
                "finishes",
                (7, "fill"),
                "Filling under ramps (mean depth: half the rise)",
                "m3",
                ramp.id,
                footprint * MM2 * ramp.rise / 2 * MM,
                story=ramp.story,
                detail=f"rise {ramp.rise:g} mm, 1 in {run / ramp.rise:.1f}",
                kind="filling",
            )
        finish = finishes.get(ramp.finish or "")
        if finish is not None:
            bill.add(
                "finishes",
                (7.1, finish.id),
                f"Ramp finish: {finish.name} ({finish.id}), {finish.thickness:g} mm",
                "m2",
                ramp.id,
                footprint * MM2 * arch_lib.ramp_length(ramp) / run,
                story=ramp.story,
                kind=finish.kind,
            )
    railing_types = {t.id: t for t in arch.railingTypes}
    for railing in arch.railings:
        if railing.base not in elevations:
            continue
        kind = railing_types[railing.type]
        length = sum(math.dist(a, b) for a, b in itertools.pairwise(railing.path))
        bill.add(
            "finishes",
            (8, kind.id),
            f"Railing {kind.id}: {kind.name}, {kind.height:g} mm high",
            "m",
            railing.id,
            length * MM,
            story=railing.base,
            kind="railing",
        )


def _masonry_material(measure: Any) -> Any:
    """The first masonry material of 03 Materials (the brickwork's, by default)."""
    return next((m for m in measure.materials.values() if m.category == Category.MASONRY), None)


def _layer_material(measure: Any, layer: arch_lib.WallLayer, masonry: Any) -> Any:
    """A wall layer's material: the 03 Materials one of its name or id, else the masonry
    material."""
    named = measure.materials.get(layer.material) or next(
        (m for m in measure.materials.values() if m.name.lower() == layer.material.lower()), None
    )
    if named is not None and named.category == Category.MASONRY:
        return named
    return masonry


def _plaster_mortar(measure: Any, masonry: Any) -> str | None:
    """The mortar of the plaster: the brickwork's mortar (03 Materials)."""
    mortar = masonry.masonry.mortar if masonry is not None and masonry.masonry else None
    return mortar if mortar in measure.materials else None


def has_content(arch: arch_lib.Architecture | None) -> bool:
    return arch is not None and bool(
        arch.walls
        or arch.rooms
        or arch.doors
        or arch.windows
        or arch.curtainWalls
        or arch.roofs
        or arch.ramps
        or arch.railings
    )

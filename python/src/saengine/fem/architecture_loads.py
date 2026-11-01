"""Loads of the architecture (``05 Floor Plan/architecture.json``) on the analysis model.

Derived at derive time from the architecture itself (never copied into ``loads.json``), so a
wall's weight has one source: the wall as drawn.

**Walls.** the default pack's Part 6 Sec 2.2.5 (Weight of permanent partitions, p. 532): partition walls
shown on the plans are dead load, applied as line loads in their actual positions. Each
architecture wall becomes a superimposed dead load (case SD) on what carries it:

- its centre line is cut into pieces by what is under it on its base story's level: a piece
  lying along a beam within its width goes to that beam as a uniform line load over the part
  of the beam under it (the beam is split at the piece's ends, so the load starts and stops
  there); where a wall crosses a beam, the piece over the beam's width is a point load on it;
- a piece over a slab goes to the slab: with slabs as shells (``analysis.slabs``), as a line
  load on the shell elements it crosses (sampled along its length, each share given to the
  element's corners by its position, so the total and its centre are exact); with slabs as
  loads to beams the panel has no plate to carry a line, so the panel gets a uniform area load
  instead, the larger of the walls' weight over the panel's area (statically the same total)
  and 33 % of the wall's weight per metre run, the code's uniform equivalent of light partitions
  (Sec 2.3.6, Provision for partition walls, p. 540; the code allows it for partitions of at
  most 5.5 kN/m: a heavier wall on a slab is noted, model the slab as shells or put a beam
  under it). The code's 1.2 kN/m² minimum of Sec 2.3.6 is for partitions *not* on the plans and
  is not applied to drawn walls;
- a piece over a floor-plan wall (or a wall whose ``structuralRef`` is one) is that wall's,
  which the floor plan already weighs: it is left out, never counted twice;
- a piece on the base level with no beam or slab under it stands on the ground (its plinth and
  footing are Part 9's) and is left out; elsewhere it is noted as not carried.

A piece's load is the wall type's weight per m² (its layers, plaster included) × its clear
height, less its openings, as a **line average over the piece**: kN/m = w × (h × L − A) / L
with A the area of the doors and windows within the piece. The clear height is the wall's
height less the depth of the beam above it (or the slab's thickness where there is no beam)
when the wall rises to a story level. Averaging over each piece (not over the whole wall) keeps
every opening's deduction on the beam it is over; within a beam the load is uniform, which
leaves the beam's total and end shears exact to the opening's eccentricity and its moments
within a few per cent (the wall over a door hangs on the lintel, which hands it to the jambs:
the true load is not a gap either). Point-load steps were not chosen: they would cut every
beam at every jamb for a difference of that order.

The setting ``analysis.partitionLoads``: ``architecture`` (the default) takes the walls on a
story where the architecture has walls standing, and drops the area load's flat partition
allowance there (never both); stories without architecture walls keep the allowance.
``allowance`` ignores the walls and keeps the allowance everywhere.

**Rooms.** A room (its face between the wall centre lines and separators,
:func:`saengine.library.architecture.room_boundary`) with a floor finish carries the finish's
weight (thickness × unit weight, plus a sunk slab's filling in a wet room when the finish type
gives one) as SD over its area instead of the project's flat finish there; a room with an
occupancy carries its use's live load from the code pack (the default pack's Table 6.2.3, pp. 533-539)
instead of the floor's, whether higher or lower. Parts of a slab in no room keep the floor's
loads. With shell slabs each shell element takes the loads of the room its centre is in; with
slabs as loads to beams a panel takes the area-weighted mean of its parts (its total exact, its
spread over the panel uniform). The room's face (to the wall centre lines) is used, so the rooms
of a floor tile it and no area takes two finishes; the bill of quantities measures the finish
over the net floor.

**Curtain walls and railings.** A curtain wall is loaded as a wall (its pieces on beams and
slabs as above), its weight the curtain wall type's per m² of wall (glass and frame) times its
clear height; it is a facade, not a partition, so it does not drop the story's partition
allowance. A railing is loaded the same way with its type's weight per metre run (Sec 2.2,
the actual weight of the materials). The horizontal load a guard must resist is for the
railing's own design and its fixings, not a load on the building's frame.

**Roofs and ramps.** A roof's covering (its type's layers, per m² of slope, so divided by the
cosine of its pitch per m² of plan) is SD over its outline on its story, instead of the floor's
flat finish there, as a room's floor finish; a roof with an occupancy (the default pack's roof uses, Table
6.2.3) carries its live load instead of the floor's. A ramp built up on a floor carries its
filling (the mean of its rise, ``rise / 2``, times the fill's unit weight; uniform over the ramp,
its total exact) and its floor finish as SD over its footprint, and its occupancy's live load.
Where they overlap rooms, a ramp takes its footprint from the room (it sits on the room's
floor) and a roof takes only what no room or ramp of its level holds.

The architecture has no typical floors: a wall is on the stories it is drawn on.
Units: mm and kN in the architecture; m and N in the analysis model.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, unary_union

from saengine.fem.end_zones import profile_extent
from saengine.fem.member_loads import KN, MM, MemberLineLoad, MemberPointLoad
from saengine.library import architecture as arch_lib
from saengine.library.bim import BeamElement, BuildingModel, SlabElement, WallElement

#: The uniform equivalent of light partitions when the code pack gives none (``areaLoads.
#: partitions``): a share of their weight per metre run (kN/m² per kN/m), for partitions of at
#: most the light partition weight [kN/m].
_PARTITION_SHARE = 0.33
_LIGHT_PARTITION = 5.5


def partition_rule() -> tuple[float, float, str]:
    """(share, lightest heavy partition [kN/m], clause) of the code pack's uniform equivalent of
    light partitions (``areaLoads.partitions``)."""
    from saengine.codes import context as code_context

    pack = code_context.current()
    rule = pack.table("areaLoads").partitions if pack.has("areaLoads") else None
    if rule is None:
        return _PARTITION_SHARE, _LIGHT_PARTITION, ""
    table = pack.table("areaLoads")
    return rule.share, rule.lightMax, table.sources.get("partitions", table.source).split(":")[0]


def __getattr__(name: str) -> Any:
    # PARTITION_SHARE, LIGHT_PARTITION (older callers): the pack's values, read when asked.
    if name == "PARTITION_SHARE":
        return partition_rule()[0]
    if name == "LIGHT_PARTITION":
        return partition_rule()[1]
    raise AttributeError(name)


#: How far a wall's centre line may stray from a beam's axis beyond half the beam's width and
#: still sit on it [mm] (a 250 mm wall on a 250 mm beam drawn a little off the grid).
ON_BEAM = 25.0
#: A piece runs along a beam when the cosine of their angle is above this; else it crosses it.
PARALLEL = 0.9
#: Pieces shorter than this are dropped [mm].
SHORT = 1.0
#: Levels closer than this are the same [mm].
LEVEL = 1.0


@dataclass(frozen=True)
class SlabWallLoad:
    """A wall piece on a slab: a line load ``load`` (N/m, down) from ``start`` to ``end`` (m)."""

    source: str
    slab: str
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    load: float


@dataclass(frozen=True)
class RoomLoad:
    """A room's loads over its face ``polygon`` (shapely, mm, in plan) at ``elevation`` [mm]:
    ``finish`` (SD) and ``live`` [kN/m²], None where the floor's apply."""

    room: str
    story: str
    elevation: float
    polygon: Any
    finish: float | None
    live: float | None


@dataclass
class ArchitectureLoads:
    lines: list[MemberLineLoad] = field(default_factory=list)  # on beams, case SD
    points: list[MemberPointLoad] = field(default_factory=list)  # walls crossing beams
    slabs: list[SlabWallLoad] = field(default_factory=list)
    rooms: list[RoomLoad] = field(default_factory=list)
    #: Beam id -> points (mm) where pieces start or stop inside it (the beam is split there).
    cuts: dict[str, list[tuple[float, float, float]]] = field(default_factory=dict)
    #: Story ids where architecture walls stand: the flat partition allowance is dropped there.
    walled: set[str] = field(default_factory=set)
    wall_rows: list[dict[str, Any]] = field(default_factory=list)
    room_rows: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self, mode: str) -> dict[str, Any]:
        """The rows for the Floor Plan's Loads panel and the report (kept with the derivation)."""
        return {
            "mode": mode,
            "walledStories": sorted(self.walled),
            "walls": self.wall_rows,
            "rooms": self.room_rows,
        }


def has_loads(arch: arch_lib.Architecture | None) -> bool:
    return arch is not None and bool(
        arch.walls or arch.rooms or arch.curtainWalls or arch.roofs or arch.ramps or arch.railings
    )


def finish_weight(finish: arch_lib.FinishType, wet: bool) -> float:
    """kN/m² of a floor finish, with its sunk filling in a wet room."""
    weight = finish.thickness / 1000 * finish.unitWeight
    if wet and finish.sunkFilling:
        weight += finish.sunkFilling / 1000 * finish.sunkUnitWeight
    return weight


def _uses() -> dict[str, Any]:
    from saengine.codes import context as code_context

    pack = code_context.current()
    if not pack.has("areaLoads"):
        return {}
    return dict(pack.table("areaLoads").uses)


def architecture_loads(
    arch: arch_lib.Architecture,
    building: BuildingModel,
    objects: Any,
    mode: str = "architecture",
) -> ArchitectureLoads:
    """The loads of ``arch`` on ``building`` (object types ``objects``, an ObjectLibrary).
    ``mode``: ``analysis.partitionLoads`` (with "allowance" the walls are not applied)."""
    out = ArchitectureLoads()
    elevations = {s.id: s.elevation for s in building.stories}
    story_at = {round(z): sid for sid, z in elevations.items()}
    levels = sorted(set(elevations.values()))
    base = levels[0] if levels else 0.0
    types = {t.id: t for t in objects.objects}

    beams = [e for e in building.elements if isinstance(e, BeamElement)]
    slabs = [e for e in building.elements if isinstance(e, SlabElement)]
    fp_walls = [e for e in building.elements if isinstance(e, WallElement)]
    fp_wall_ids = {e.id for e in fp_walls} | {e.source for e in fp_walls if e.source}

    def beam_size(beam: BeamElement) -> tuple[float, float]:
        extent = profile_extent(getattr(types.get(beam.type), "profile", None))
        return extent if extent else (0.0, 0.0)

    def strip(beam: BeamElement, reach: float) -> Any:
        return LineString([beam.start, beam.end]).buffer(reach, cap_style="flat")

    def at_level(z: float) -> tuple[list[tuple[BeamElement, Any]], list[tuple[SlabElement, Any]]]:
        on = [(bm, strip(bm, beam_size(bm)[0] / 2 + ON_BEAM)) for bm in beams]
        return (
            [(bm, s) for bm, s in on if abs(bm.elevation - z) < LEVEL],
            [(sl, Polygon(sl.boundary)) for sl in slabs if abs(sl.elevation - z) < LEVEL],
        )

    def thickness_of(type_id: str) -> float:
        return float(getattr(types.get(type_id), "thickness", 0.0) or 0.0)

    wall_types = {t.id: t for t in arch.wallTypes}
    openings: dict[str, list[tuple[float, float, float, float]]] = {}
    for opening in [*arch.doors, *arch.windows]:
        width, height, sill = arch_lib.opening_size(arch, opening)
        openings.setdefault(opening.wall, []).append(
            (opening.offset - width / 2, opening.offset + width / 2, sill, sill + height)
        )

    apply_walls = mode != "allowance"
    if apply_walls:
        for wall in arch.walls:
            _wall(
                wall,
                wall_types[wall.type],
                openings.get(wall.id, []),
                _Context(
                    elevations,
                    base,
                    story_at,
                    at_level,
                    beam_size,
                    thickness_of,
                    fp_walls,
                    fp_wall_ids,
                    {bm.id: bm for bm in beams},
                ),
                out,
            )

    if apply_walls:
        context = _Context(
            elevations,
            base,
            story_at,
            at_level,
            beam_size,
            thickness_of,
            fp_walls,
            fp_wall_ids,
            {bm.id: bm for bm in beams},
        )
        curtain_types = {t.id: t for t in arch.curtainWallTypes}
        for curtain in arch.curtainWalls:
            _wall(curtain, curtain_types[curtain.type], [], context, out, partition=False)
        railing_types = {t.id: t for t in arch.railingTypes}
        for railing in arch.railings:
            railing_type = railing_types[railing.type]
            _wall(
                arch_lib.railing_as_wall(railing, railing_type),
                railing_type,
                [],
                context,
                out,
                partition=False,
                line_weight=railing_type.weight,
            )

    uses = _uses()
    finishes = {t.id: t for t in arch.finishTypes}
    for room in arch.rooms:
        if room.story not in elevations:
            continue
        found = arch_lib.room_boundary(arch, room, elevations)
        if found is None:
            out.notes.append(
                f"{room.id}: not enclosed by walls or separators; its loads are not applied"
            )
            continue
        face, _ = found
        finish = finishes.get(room.floorFinish) if room.floorFinish else None
        finish_kn = finish_weight(finish, room.wet) if finish is not None else None
        live = None
        if room.occupancy:
            use = uses.get(room.occupancy)
            if use is None:
                out.notes.append(
                    f"{room.id}: no area use '{room.occupancy}' in the code pack; the floor's "
                    "live load is kept"
                )
            else:
                live = float(use.live)
        if finish_kn is None and live is None:
            continue
        out.rooms.append(
            RoomLoad(room.id, room.story, elevations[room.story], face, finish_kn, live)
        )
        out.room_rows.append(
            {
                "room": room.id,
                "name": room.name,
                "number": room.number,
                "story": room.story,
                "area_m2": round(face.area * 1e-6, 3),
                "finish": room.floorFinish if finish_kn is not None else None,
                "finish_kNm2": round(finish_kn, 3) if finish_kn is not None else None,
                "sunk": bool(room.wet and finish is not None and finish.sunkFilling),
                "use": room.occupancy if live is not None else None,
                "live_kNm2": live,
            }
        )
    _ramps_and_roofs(arch, elevations, uses, finishes, out)
    return out


def _live_of(item: Any, uses: dict[str, Any], out: ArchitectureLoads) -> float | None:
    """The live load [kN/m²] of an item's occupancy from the code pack, else None (noted)."""
    if not item.occupancy:
        return None
    use = uses.get(item.occupancy)
    if use is None:
        out.notes.append(
            f"{item.id}: no area use '{item.occupancy}' in the code pack; the floor's live load "
            "is kept"
        )
        return None
    return float(use.live)


def _ramps_and_roofs(
    arch: arch_lib.Architecture,
    elevations: dict[str, float],
    uses: dict[str, Any],
    finishes: dict[str, arch_lib.FinishType],
    out: ArchitectureLoads,
) -> None:
    """The ramps' and roofs' area loads into ``out.rooms`` (see the module's notes)."""
    import dataclasses

    for ramp in arch.ramps:
        if ramp.story not in elevations:
            out.notes.append(f"{ramp.id}: no story '{ramp.story}'; its loads are not applied")
            continue
        level = elevations[ramp.story]
        footprint = arch_lib.ramp_polygon(ramp)
        finish = finishes.get(ramp.finish) if ramp.finish else None
        fill = ramp.rise / 2 / 1000 * ramp.fillUnitWeight  # kN/m², the mean depth's
        finish_kn = (finish_weight(finish, False) if finish is not None else 0.0) + fill
        live = _live_of(ramp, uses, out)
        if not finish_kn and live is None:
            continue
        # The ramp sits on the room's floor: the room keeps the rest.
        out.rooms = [
            dataclasses.replace(r, polygon=r.polygon.difference(footprint))
            if abs(r.elevation - level) < LEVEL
            else r
            for r in out.rooms
        ]
        out.rooms.append(RoomLoad(ramp.id, ramp.story, level, footprint, finish_kn or None, live))
        out.room_rows.append(
            {
                "room": ramp.id,
                "name": "Ramp",
                "number": "",
                "story": ramp.story,
                "area_m2": round(footprint.area * 1e-6, 3),
                "finish": ramp.finish,
                "finish_kNm2": round(finish_kn, 3) if finish_kn else None,
                "sunk": False,
                "use": ramp.occupancy if live is not None else None,
                "live_kNm2": live,
                "kind": "ramp",
                "gradient": round(arch_lib.ramp_gradient(ramp), 4),
            }
        )
    roof_types = {t.id: t for t in arch.roofTypes}
    for roof in arch.roofs:
        if roof.story not in elevations:
            out.notes.append(f"{roof.id}: no story '{roof.story}'; its loads are not applied")
            continue
        level = elevations[roof.story]
        taken = unary_union([r.polygon for r in out.rooms if abs(r.elevation - level) < LEVEL])
        outline = arch_lib.roof_polygon(roof)
        polygon = outline.difference(taken) if not taken.is_empty else outline
        if polygon.is_empty or polygon.area <= 0:
            out.notes.append(
                f"{roof.id}: rooms or ramps cover all of it; its loads are not applied"
            )
            continue
        covering = roof_types[roof.type].weight / math.cos(math.radians(roof.slope))
        live = _live_of(roof, uses, out)
        out.rooms.append(RoomLoad(roof.id, roof.story, level, polygon, covering, live))
        out.room_rows.append(
            {
                "room": roof.id,
                "name": "Roof",
                "number": "",
                "story": roof.story,
                "area_m2": round(polygon.area * 1e-6, 3),
                "finish": roof.type,
                "finish_kNm2": round(covering, 3),
                "sunk": False,
                "use": roof.occupancy if live is not None else None,
                "live_kNm2": live,
                "kind": "roof",
            }
        )


@dataclass(frozen=True)
class _Context:
    """What :func:`_wall` looks a wall's pieces up in (the building model's, from
    :func:`architecture_loads`)."""

    elevations: dict[str, float]
    base: float
    story_at: dict[int, str]
    at_level: Any  # z -> (beams with their strips, slabs with their outlines) at that level
    beam_size: Any  # beam -> (width, depth) [mm]
    thickness_of: Any  # object type id -> thickness [mm]
    fp_walls: list[WallElement]
    fp_wall_ids: set[str]
    beam_of: dict[str, BeamElement]


def _wall(
    wall: arch_lib.ArchWall,
    wall_type: Any,
    wall_openings: list[tuple[float, float, float, float]],
    ctx: _Context,
    out: ArchitectureLoads,
    partition: bool = True,
    line_weight: float | None = None,
) -> None:
    """The pieces of ``wall`` and their loads into ``out``. ``wall_type``: a wall type, or a
    curtain wall or railing type (its ``id``, ``thickness``, ``locationLine`` and ``weight``).
    ``partition``: a partition (its story drops the flat partition allowance); ``line_weight``:
    a load per metre run [kN/m] instead of the type's weight per m² times the clear height
    (a railing's)."""
    elevations, base, story_at = ctx.elevations, ctx.base, ctx.story_at
    at_level, beam_size, thickness_of = ctx.at_level, ctx.beam_size, ctx.thickness_of
    fp_walls, fp_wall_ids, beam_of = ctx.fp_walls, ctx.fp_wall_ids, ctx.beam_of

    def row(on: str, length: float, **extra: Any) -> None:
        out.wall_rows.append(
            {
                "wall": wall.id,
                "story": wall.base,
                "type": wall_type.id,
                "on": on,
                "length_m": round(length * MM, 3),
                **extra,
            }
        )

    levels = arch_lib.wall_levels(wall, elevations)
    centre = arch_lib.centre_line(wall, wall_type)
    total_length = sum(math.dist(a, b) for a, b in itertools.pairwise(centre))
    if levels is None:
        out.notes.append(f"{wall.id}: its stories are not in the building model; not applied")
        return
    if wall.structuralRef is not None and wall.structuralRef in fp_wall_ids:
        row("structural", total_length, member=wall.structuralRef)
        return
    bottom, top = levels
    floor = elevations[wall.base]
    if partition:
        out.walled.add(wall.base)
    height = top - bottom
    rises_to_level = any(abs(top - z) < LEVEL for z in elevations.values())
    beams_here, slabs_here = at_level(floor)
    beams_above, slabs_above = at_level(top) if rises_to_level else ([], [])
    weight = wall_type.weight  # kN/m²
    # Floor-plan walls on this story: what they cover is theirs.
    covered = unary_union(
        [
            LineString([w.start, w.end]).buffer(
                max(thickness_of(w.type), wall_type.thickness) / 2 + ON_BEAM, cap_style="flat"
            )
            for w in fp_walls
            if w.bottom - LEVEL <= bottom < w.top - LEVEL
        ]
    )
    along = 0.0
    for a, b in itertools.pairwise(centre):
        segment = LineString([a, b])
        length = segment.length
        if length < SHORT:
            continue
        pieces: list[tuple[str, str | None, Any]] = []
        rest = segment
        if not covered.is_empty:
            taken = rest.intersection(covered)
            for part in _lines(taken):
                pieces.append(("structural", None, part))
            rest = rest.difference(covered)
        # The beam the segment runs along first: at a wall's end the crossing beam's strip
        # takes only what the first leaves.
        for beam, area in sorted(
            beams_here, key=lambda found: -segment.intersection(found[1]).length
        ):
            if rest.is_empty:
                break
            on = rest.intersection(area)
            for part in _lines(on):
                pieces.append(("beam", beam.id, part))
            if not on.is_empty:
                rest = rest.difference(area)
        for slab, area in slabs_here:
            if rest.is_empty:
                break
            on = rest.intersection(area)
            for part in _lines(on):
                pieces.append(("slab", slab.id, part))
            if not on.is_empty:
                rest = rest.difference(area)
        for part in _lines(rest):
            pieces.append(("ground" if abs(floor - base) < LEVEL else "none", None, part))

        for on, member, part in pieces:
            (x0, y0), (x1, y1) = part.coords[0], part.coords[-1]
            piece_length = part.length
            if piece_length < SHORT:
                continue
            if on == "structural":
                row(on, piece_length)
                continue
            s0 = along + segment.project(Point(x0, y0))
            s1 = along + segment.project(Point(x1, y1))
            lo, hi = min(s0, s1), max(s0, s1)
            middle = Point((x0 + x1) / 2, (y0 + y1) / 2)
            clear = height
            above = "none"
            if rises_to_level:
                beam_above = next((bm for bm, area in beams_above if area.contains(middle)), None)
                slab_above = next((sl for sl, area in slabs_above if area.contains(middle)), None)
                if beam_above is not None:
                    clear -= beam_size(beam_above)[1]
                    above = f"beam {beam_above.id}"
                elif slab_above is not None:
                    clear -= thickness_of(slab_above.type)
                    above = f"slab {slab_above.id}"
            clear = max(clear, 0.0)
            # Openings over the piece, their sills from the floor, clipped to the clear height
            # above the wall's bottom (its base offset above the floor).
            offset = bottom - floor
            open_area = sum(
                max(0.0, min(hi, o_hi) - max(lo, o_lo))
                * max(0.0, min(clear, o_top - offset) - max(0.0, sill - offset))
                for o_lo, o_hi, sill, o_top in wall_openings
            )
            # kN/m: w × (h × L − A) / L, the piece's line average (a railing's: its weight per m).
            load = (
                line_weight
                if line_weight is not None
                else weight * max(0.0, clear * piece_length - open_area) / piece_length / 1000
            )
            total = load * piece_length * MM
            details = {
                "member": member,
                "height_m": round(clear * MM, 3),
                "above": above,
                "openings_m2": round(open_area * 1e-6, 3),
                "load_kNm": round(load, 3),
                "total_kN": round(total, 3),
            }
            if on in ("ground", "none"):
                row(on, piece_length, **details)
                if on == "none":
                    out.notes.append(
                        f"{wall.id}: {piece_length:.0f} mm of it has no beam or slab under it "
                        f"on {wall.base}; its {total:.1f} kN are not applied"
                    )
                continue
            row(on, piece_length, **details)
            if not load:
                continue
            p0 = (x0 * MM, y0 * MM, floor * MM)
            p1 = (x1 * MM, y1 * MM, floor * MM)
            if on == "beam":
                beam = beam_of[member]  # type: ignore[index]
                story = story_at.get(round(floor), wall.base)
                axis = (beam.end[0] - beam.start[0], beam.end[1] - beam.start[1])
                span = math.hypot(*axis)
                ux, uy = axis[0] / span, axis[1] / span

                def onto(
                    x: float,
                    y: float,
                    start: tuple[float, float] = (beam.start[0], beam.start[1]),
                    unit: tuple[float, float] = (ux, uy),
                    span: float = span,
                ) -> tuple[float, float]:
                    """The point's foot on the beam's axis (a wall drawn a little off it)."""
                    t = (x - start[0]) * unit[0] + (y - start[1]) * unit[1]
                    t = min(max(t, 0.0), span)
                    return start[0] + t * unit[0], start[1] + t * unit[1]

                ends = (
                    (beam.start[0] * MM, beam.start[1] * MM, floor * MM),
                    (beam.end[0] * MM, beam.end[1] * MM, floor * MM),
                )
                parallel = abs(((x1 - x0) * ux + (y1 - y0) * uy) / piece_length) > PARALLEL
                if parallel:
                    (a0, b0), (a1, b1) = onto(x0, y0), onto(x1, y1)
                    out.lines.append(
                        MemberLineLoad(
                            wall.id,
                            beam.id,
                            story,
                            "SD",
                            (a0 * MM, b0 * MM, floor * MM),
                            (a1 * MM, b1 * MM, floor * MM),
                            load * KN,
                        )
                    )
                    for x, y in ((a0, b0), (a1, b1)):
                        out.cuts.setdefault(beam.id, []).append((x, y, floor))
                else:
                    # A wall crossing the beam: its piece over the beam's width is a point load.
                    x, y = onto((x0 + x1) / 2, (y0 + y1) / 2)
                    out.points.append(
                        MemberPointLoad(
                            wall.id,
                            beam.id,
                            story,
                            "SD",
                            (x * MM, y * MM, floor * MM),
                            total * KN,
                            ends,
                        )
                    )
                    out.cuts.setdefault(beam.id, []).append((x, y, floor))
                    out.wall_rows[-1]["point"] = True
            else:
                _share, light, where = partition_rule()
                if load > light:
                    out.notes.append(
                        f"{wall.id}: {load:.2f} kN/m on slab {member} is more than the "
                        f"{light:g} kN/m of a light partition ({where}): with slabs as loads to "
                        "beams it is spread over the panel; model the slabs as shells or put a "
                        "beam under it"
                    )
                out.slabs.append(SlabWallLoad(wall.id, member, p0, p1, load * KN))  # type: ignore[arg-type]
        along += length


def _lines(geometry: Any) -> list[Any]:
    """The line pieces of a shapely intersection or difference (points dropped)."""
    if geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry]
    if hasattr(geometry, "geoms"):
        lines = [g for g in geometry.geoms if g.geom_type == "LineString"]
        if not lines:
            return []
        merged = linemerge(lines)
        return list(merged.geoms) if hasattr(merged, "geoms") else [merged]
    return []


def panel_pressures(loads: ArchitectureLoads, slab: SlabElement) -> tuple[float, list[str]]:
    """The uniform SD pressure [N/m²] on a slab panel (slabs as loads to beams) for the walls
    on it: the larger of their weight over its area and the code pack's share (33 %) of the
    heaviest wall's weight per metre run (``areaLoads.partitions``), and the walls."""
    on = [w for w in loads.slabs if w.slab == slab.id]
    if not on:
        return 0.0, []
    area = Polygon(slab.boundary).area * 1e-6  # m²
    if area <= 0:
        return 0.0, []
    total = sum(w.load * math.dist(w.start, w.end) for w in on)  # N
    heaviest = max(w.load for w in on)  # N/m
    return max(total / area, partition_rule()[0] * heaviest), sorted({w.source for w in on})


def room_shares(loads: ArchitectureLoads, slab: SlabElement) -> list[tuple[RoomLoad, float]]:
    """The rooms over ``slab`` and the share of its area each covers."""
    return room_mix(loads, slab.boundary, slab.elevation)


def room_mix(
    loads: ArchitectureLoads, outline: Any, elevation: float
) -> list[tuple[RoomLoad, float]]:
    """The rooms over the plan polygon ``outline`` (mm) at ``elevation`` and the share of its
    area each covers."""
    polygon = Polygon(outline)
    if polygon.area <= 0:
        return []
    shares = []
    for room in loads.rooms:
        if abs(room.elevation - elevation) >= LEVEL:
            continue
        overlap = polygon.intersection(room.polygon).area
        if overlap > 1e-6 * polygon.area:
            shares.append((room, overlap / polygon.area))
    return shares


def room_at(loads: ArchitectureLoads, x: float, y: float, elevation: float) -> RoomLoad | None:
    """The room whose face holds the plan point (mm) at ``elevation``."""
    point = Point(x, y)
    for room in loads.rooms:
        if abs(room.elevation - elevation) < LEVEL and room.polygon.covers(point):
            return room
    return None

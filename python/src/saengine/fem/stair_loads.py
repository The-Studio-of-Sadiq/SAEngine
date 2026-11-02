"""The loads of the stairs (``06 BIM`` ``additions.stairs``) on the analysis model.

The stairs are not in the stiffness model; their weight, finish and live load are. Each stair's
support reactions come from its design (:mod:`saengine.design.stairs`: the flights and landings
as one-way slabs with their service reactions per case), never worked out a second time, and are
applied where the stair bears on the building:

- a flight's end at a floor is a line load across the flight's width on its support line (the
  centre of the supporting beam for spanning (a), the landing's edge for (b), the far support of
  the landing for (c), the end of the going for (d));
- a landing spanning across the flights ((b), (d)) hands its reactions to its sides: a line load
  along each side over the landing's depth;
- the case is that of the stair's load: D its self-weight (the concrete's density × g, as the
  members'), SD its floor finish, L its live load (the stairs area load of the settings, else
  the code pack's stairs row), their seismic weight as for any load of that case.

Where a support line meets the floor (:func:`saengine.fem.architecture_loads.level_context`),
it is placed as the architecture's walls are: on the beam it runs along (a line load, the beam
split at its ends) or crosses (a point load), else on the slab (with shell slabs as a line on
the shells, with slabs as loads to beams as a uniform load over the panel, its total exact).
A support at the base level stands on the ground (its footing is Part 9's): not applied, its
reactions noted. A support between two floors (the half landing of a dog-legged stair, whose
side beams or walls are not in the model) is taken down to the floor of the stair's base story
at the same place (the walls or posts under it stand there): an SAEngine adoption, noted. A
piece of a line with no beam or slab under it (over an opening) is noted as not applied.

Stairs on stringer beams and the special stairs (free-standing, sawtooth, helicoidal) are not
loaded (their supports are not plan lines): noted with their weight.

The ETABS export (:mod:`saengine.exporters.etabs`) writes the same loads.
Units: mm and kN here; the placed loads (``ArchitectureLoads``) in m and N.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from typing import Any

from saengine.design import stairs as st
from saengine.fem import architecture_loads as al
from saengine.library import architecture as arch_lib

#: The cases of a stair's loads: its self-weight, finish and live load.
CASES = ("D", "SD", "L")


@dataclass(frozen=True)
class StairSupport:
    """A support line of a stair: plan ``start``-``end`` [mm] at ``elevation`` [mm] (the level
    the load is applied at) with its loads per case [kN/m along the line]."""

    stair: str
    part: str  # e.g. "F1 bottom", "L1 left"
    elevation: float
    start: tuple[float, float]
    end: tuple[float, float]
    loads: dict[str, float]
    moved_from: float | None = None  # the elevation of a mid-height support taken down

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)

    def total(self, case: str) -> float:
        """kN."""
        return self.loads.get(case, 0.0) * self.length / 1000


@dataclass
class StairLoads:
    """The stairs' supports and their loads placed on the model (``placed``: the beams' line and
    point loads, the slabs' lines and the beams' cuts, as :class:`~saengine.fem.
    architecture_loads.ArchitectureLoads`)."""

    supports: list[StairSupport] = field(default_factory=list)
    placed: al.ArchitectureLoads = field(default_factory=al.ArchitectureLoads)
    notes: list[str] = field(default_factory=list)
    #: kN per case applied and left out (on the ground or over no floor).
    applied: dict[str, float] = field(default_factory=dict)
    left_out: dict[str, float] = field(default_factory=dict)

    def summary(self) -> list[dict[str, Any]]:
        return [
            {
                "stair": s.stair,
                "part": s.part,
                "elevation": s.elevation,
                "length_m": round(s.length / 1000, 3),
                "loads_kNm": {c: round(v, 3) for c, v in s.loads.items()},
                **({"from": s.moved_from} if s.moved_from is not None else {}),
            }
            for s in self.supports
        ]


def _frame(stair: Any) -> Any:
    a = math.radians(stair.direction)
    u, v = (math.cos(a), math.sin(a)), (-math.sin(a), math.cos(a))

    def at(s: float, r: float) -> tuple[float, float]:
        return (stair.x + u[0] * s + v[0] * r, stair.y + u[1] * s + v[1] * r)

    return at


def supports_of(
    stair: Any,
    spec: st.StairSpec,
    geometry: st.StairGeometry,
    material: st.StairMaterial,
    loads: st.StairLoads,
    base: float,
) -> list[tuple[str, float, tuple[float, float], tuple[float, float], dict[str, float]]]:
    """The support lines of a stair (``part``, elevation, start, end, kN/m per case) in plan
    [mm], with its foot at ``base`` [mm]: the flights' ends that bear on the building and the
    landings' sides (module notes). The plan layout is the drawings' (a dog-legged stair's
    second flight returns beside the first, on its left)."""
    at = _frame(stair)
    w, sw, lnd, well = spec.width, spec.support_width, spec.landing, spec.well
    bare = dataclasses.replace(loads, finish=0.0)

    def per_case(full: dict[str, dict[str, float]], own: dict[str, dict[str, float]], end: str):
        dead = own["D"][end]
        return {"D": dead, "SD": full["D"][end] - dead, "L": full["L"][end]}

    flights = geometry.flights
    demands = {f.name: st.flight_demand(f, spec, material, loads) for f in flights}
    bare_demands = {f.name: st.flight_demand(f, spec, material, bare) for f in flights}
    landing_parts = spec.spanning in ("landingEdges", "landingsThreeSides")
    dog = len(flights) == 2
    out = []
    # Per flight: (s of its first riser, direction along s, r range, bottom and top elevations).
    rise0 = flights[0].rise
    layout = [(0.0, 1.0, (-w / 2, w / 2), base, base + rise0)]
    if dog:
        g1 = flights[0].going
        r0 = w / 2 + well
        layout.append((g1, -1.0, (r0, r0 + w), base + rise0, base + geometry.rise))
    for flight, (s0, sense, (ra, rb), z0, z1) in zip(flights, layout, strict=True):
        full, own = demands[flight.name].reactions, bare_demands[flight.name].reactions
        s1 = s0 + sense * flight.going
        if spec.spanning == "betweenBeams":
            out_bottom, out_top = sw / 2, sw / 2
        elif spec.spanning == "landingEdges":
            out_bottom, out_top = flight.landing_bottom, flight.landing_top
        elif spec.spanning == "withLandings":
            out_bottom, out_top = lnd + sw / 2, lnd + sw / 2
        else:
            out_bottom, out_top = 0.0, 0.0
        for end, s, z in (
            ("bottom", s0 - sense * out_bottom, z0),
            ("top", s1 + sense * out_top, z1),
        ):
            # An end on a landing part (b, d) goes to the landing, which hands it to its sides.
            taken = landing_parts and (
                not dog
                or (flight.name == "F1" and end == "top")
                or (flight.name == "F2" and end == "bottom")
            )
            if taken:
                continue
            out.append((f"{flight.name} {end}", z, at(s, ra), at(s, rb), per_case(full, own, end)))
    if landing_parts:
        for landing in geometry.landings:
            full = st.landing_demand(landing, demands, spec, material, loads).reactions
            own = st.landing_demand(landing, bare_demands, spec, material, bare).reactions
            if dog:
                s_a, s_b, z = flights[0].going, flights[0].going + lnd, base + rise0
                left, right = -w / 2 - sw / 2, w / 2 + well + w + sw / 2
            elif landing.name == "L0":
                s_a, s_b, z = -lnd, 0.0, base
                left, right = -w / 2 - sw / 2, w / 2 + sw / 2
            else:
                g = flights[0].going
                s_a, s_b, z = g, g + lnd, base + geometry.rise
                left, right = -w / 2 - sw / 2, w / 2 + sw / 2
            for side, r in (("left", left), ("right", right)):
                out.append(
                    (f"{landing.name} {side}", z, at(s_a, r), at(s_b, r), per_case(full, own, side))
                )
    return out


def stair_supports(
    building: Any, types: dict[str, Any], materials: dict[str, Any], settings: Any
) -> tuple[list[StairSupport], list[str]]:
    """The support lines of the stairs of ``building`` with their loads (module notes), and
    notes on the stairs not loaded."""
    levels = {s.id: s.elevation for s in building.stories}
    floors = sorted(set(levels.values()))
    loads = st.loads_from_settings(settings)
    supports: list[StairSupport] = []
    notes: list[str] = []
    for stair in building.additions.stairs:
        t = types.get(stair.type)
        if t is None or getattr(t, "kind", None) != "staircase":
            notes.append(f"{stair.id}: '{stair.type}' is not a staircase type; not loaded")
            continue
        if stair.base not in levels or stair.top not in levels:
            notes.append(f"{stair.id}: its base or top story is missing; not loaded")
            continue
        base, top = levels[stair.base], levels[stair.top]
        material = st.material_of(t, materials)
        if top <= base or isinstance(material, str):
            reason = material if isinstance(material, str) else "its top is not above its base"
            notes.append(f"{stair.id}: {reason}; not loaded")
            continue
        spec = st.spec_of(t)
        try:
            geometry = st.stair_geometry(spec, top - base)
        except ValueError as error:
            notes.append(f"{stair.id}: {error}; not loaded")
            continue
        if spec.stringers or spec.special != "none":
            notes.append(
                f"{stair.id}: stairs on stringer beams and special stairs are not loaded on the "
                "analysis model (their supports are not plan lines): add their reactions as "
                "member loads"
            )
            continue
        for part, z, a, b, per_case in supports_of(stair, spec, geometry, material, loads, base):
            moved = None
            if not any(abs(z - f) < al.LEVEL for f in floors):
                moved, z = z, base
            supports.append(StairSupport(stair.id, part, z, a, b, per_case, moved))
    if supports:
        notes.append(f"stair loads: {loads.source}; finish {loads.finish:g} kN/m² on plan")
    return supports, notes


def stair_loads(building: Any, objects: Any, materials: Any, settings: Any) -> StairLoads | None:
    """The stairs' loads placed on ``building`` (object types ``objects``, materials
    ``materials``: the libraries); None when the building has no stairs."""
    if not building.additions.stairs:
        return None
    types = {t.id: t for t in objects.objects}
    mats = {m.id: m for m in materials.materials}
    supports, notes = stair_supports(building, types, mats, settings)
    out = StairLoads(supports=supports, notes=notes)
    context = dataclasses.replace(
        al.level_context(building, objects), fp_walls=[], fp_wall_ids=set()
    )
    story_of = {round(z): sid for sid, z in context.elevations.items()}
    line_type = _LineType()
    placed = out.placed
    ground: dict[str, dict[str, float]] = {}
    for k, support in enumerate(supports):
        if support.length < al.SHORT:
            continue
        on_ground = abs(support.elevation - context.base) < al.LEVEL
        if on_ground:
            totals = ground.setdefault(support.stair, {})
            for case in CASES:
                totals[case] = totals.get(case, 0.0) + support.total(case)
                out.left_out[case] = out.left_out.get(case, 0.0) + support.total(case)
            continue
        if support.moved_from is not None:
            notes.append(
                f"{support.stair}: {support.part} at {support.moved_from:.0f} mm (its side "
                "supports are not in the model) taken down to the floor of its base story "
                "(SAEngine adoption)"
            )
        line = arch_lib.ArchWall(
            id=f"{support.stair}-{k + 1}",
            type="stair",
            base=story_of[round(support.elevation)],
            height=1.0,
            path=[support.start, support.end],
        )
        before = len(placed.notes)
        for case in CASES:
            load = support.loads.get(case, 0.0)
            if load <= 0:
                continue
            al._wall(
                line,
                line_type,
                [],
                context,
                placed,
                partition=False,
                line_weight=load,
                case=case,
                heavy_note=False,
            )
            out.applied[case] = out.applied.get(case, 0.0) + support.total(case)
        # The pieces over no beam or slab (an opening) are noted once per support, by part.
        lost = placed.notes[before:]
        del placed.notes[before:]
        if lost:
            notes.append(
                f"{support.stair}: {support.part}: part of its support line has no beam or slab "
                f"under it on {line.base}; that part is not applied"
            )
    for stair, totals in ground.items():
        notes.append(
            f"{stair}: its supports at the base level stand on the ground (D "
            f"{totals['D']:.1f} kN, SD {totals['SD']:.1f} kN, L {totals['L']:.1f} kN to its "
            "footing, 09 Substructure)"
        )
    applied = ", ".join(f"{c} {out.applied.get(c, 0.0):.1f}" for c in CASES)
    notes.append(f"stairs: loads applied on the model {applied} kN")
    placed.wall_rows.clear()
    return out


@dataclass(frozen=True)
class _LineType:
    """The 'wall type' of a support line (no thickness: its load is given per metre)."""

    id: str = "stair"
    thickness: float = 0.0
    locationLine: str = "center"
    weight: float = 0.0

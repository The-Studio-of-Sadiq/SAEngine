"""Equipment loads of the MEP model on the analysis model, and the holes MEP cuts in it.

Load cases (BNBC 2020, Part 6 Chapter 2):

- The weight of fixed service equipment and permanent machinery (HVAC, lifts, plumbing risers
  and the like) supported by structural members is dead load (Sec 2.2.6). It goes into the
  superimposed dead load case **SD**, factored as D by every combination.
- The contents (operating minus empty weight: the water of a tank, a chiller's refrigerant) are
  loads of fluids of known density and controlled height, F. BNBC 2.7.3.1 has F only in
  combinations 1 and 2, 1.4(D + F) and 1.2(D + F + T) + 1.6(L + H) + ..., not in
  0.9D + 1.6W + 1.6H or 0.9D + 1.0E + 1.6H, and requires the effects of loads not acting to be
  investigated: a tank may be empty, so its water must not help resist uplift, overturning or
  column tension. So the contents are not SD (which takes D's factor, 0.9 included).
  ``contentsAs``:

  - "fluid" (the default): their own case **F** when the analysis model has one (``cases``;
    the integrated derivation's ``CASES``). Until it has, they go into **L** (as "live"), with
    a note.
  - "live": case **L**: 1.6 or 1.0 with gravity, 0 in the 0.9D combinations; conservative
    except that 1.4D (combination 1) then leaves them out.
  - "dead": case **SD**, factored as D everywhere, 0.9 included; only for contents that are
    always there (a note says so).
- Vibration and impact from operating machinery are determined separately and treated as
  additional live load (Sec 2.3.12); without the manufacturer's values, Table 6.2.6 gives them
  as a percentage of the static load including self-weight: lifts, hoists and related operating
  machinery 100 %, light machinery (shaft or motor driven) 20 %, reciprocating machinery or
  power driven units 50 %. Case **L**.
- A plinth is concrete cast on the finished floor: SD.
- An overhead tank of the plumbing (``plumbing.tanks``, kind "overhead") is equipment of kind
  "tank" too (:func:`plumbing_tank_equipment`): its reinforced concrete SD, its water the
  contents. One linked to an equipment tank, or standing where one is, is left to it.
- The HVAC plant (``hvac.plant``) and the electrical equipment (``electrical.equipment``) are
  equipment too (:func:`services_equipment`), with the same rule against counting twice. A
  fuel tank's diesel is a fluid of well-defined density and controllable maximum height, F
  (Sec 2.1.4, symbol F); a transformer's oil is always there, part of the equipment, D
  (Sec 2.1.4, symbol D: "weight of permanent equipment"; Sec 2.2.6).

Seismic weight (Sec 2.5.7.3 (c)): the total (100 %) weight of permanent heavy equipment and of
retained liquid is included, so the equipment and its contents count in full whatever case they
are in, and the impact allowance (not a mass) not at all. Each load carries the weight it adds to
the seismic weight explicitly.

Distribution. ``loadAs`` "area" spreads the weight uniformly over the footprint (a grid of
equal point loads with the exact total and resultant); "points" puts equal shares on the
supports. A point on a shell slab goes to the nodes of the shell element it is in by the
element's shape functions (consistent nodal loads). On a slab that hands its loads to its beams
(Project Settings, Analysis: slabs "loadsToBeams") the equipment's resultant on that slab goes
to the slab edges: a one-way slab (or ly/lx > 2) carries it across its short span, a two-way
rectangle shares it between the spans as two crossing strips of equal deflection
(Px / P = ly³ / (lx³ + ly³)), and each span hands it to its two edges by the lever rule; each
edge gets its share as a uniform load along it, as SAEngine applies slab loads to beams. Other
outlines share it among their edges by length.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from shapely import prepare
from shapely.geometry import Point, Polygon
from shapely.geometry import box as shapely_box

from saengine.library.bim import (
    BuildingModel,
    SlabElement,
    SlabOpening,
    WallElement,
    WallOpening,
)
from saengine.library.mep import Equipment, MepModel
from saengine.mep.geometry import (
    bounded_id,
    footprint_points,
    inside,
    is_rectangle,
    local_to_global,
    shape_weights,
)

G = 9.80665
MM = 1e-3
#: Unit weight of a plinth whose material has no density [kN/m³].
PLINTH_UNIT_WEIGHT = 24.0

#: BNBC 2020 Table 6.2.6, vertical impact as a percentage of the static load including
#: self-weight, by equipment kind (lifts always; the others when marked vibrating).
IMPACT_PERCENT = {
    "lift": (100.0, "lifts, hoists and related operating machinery"),
    "generator": (50.0, "reciprocating machinery or power driven units"),
    "pump": (20.0, "light machinery (shaft or motor driven)"),
    "chiller": (20.0, "light machinery (shaft or motor driven)"),
    "ahu": (20.0, "light machinery (shaft or motor driven)"),
    "other": (20.0, "light machinery (shaft or motor driven)"),
    "tank": (20.0, "light machinery (shaft or motor driven)"),
    "transformer": (20.0, "light machinery (shaft or motor driven)"),
}


@dataclass
class NodalLoad:
    """A force on an analysis node: ``force`` [N] global, ``weight`` [N] it adds to the
    seismic weight of the node."""

    case: str
    node: int
    force: tuple[float, float, float]
    weight: float
    source: str


@dataclass
class LineLoad:
    """A uniform downward load ``load`` [N/m] along a slab edge from ``start`` to ``end`` [m],
    for the beams along it; ``weight_share`` of it counts in the seismic weight."""

    case: str
    slab: str
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    load: float
    weight_share: float
    source: str


@dataclass
class EquipmentLoads:
    nodal: list[NodalLoad] = field(default_factory=list)
    lines: list[LineLoad] = field(default_factory=list)
    summary: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def totals(self) -> dict[str, float]:
        """Total vertical load per case [kN]."""
        totals: dict[str, float] = {}
        for load in self.nodal:
            totals[load.case] = totals.get(load.case, 0.0) - load.force[2] / 1e3
        for line in self.lines:
            length = math.dist(line.start, line.end)
            totals[line.case] = totals.get(line.case, 0.0) + line.load * length / 1e3
        return totals


@dataclass
class _Part:
    """One load of a piece of equipment: case, total [N], seismic weight fraction."""

    case: str
    total: float
    weight_share: float
    what: str


def impact_percent(item: Equipment) -> tuple[float, str]:
    """The vertical impact allowance [%] of a piece of equipment and where it comes from."""
    if item.impact is not None:
        return item.impact, "manufacturer's value"
    if item.kind == "lift" or item.vibrating:
        percent, row = IMPACT_PERCENT[item.kind]
        return percent, f"BNBC 2020 Table 6.2.6, {row}"
    return 0.0, ""


def plinth_weight(item: Equipment, densities: Mapping[str, float | None] | None = None) -> float:
    """Weight of the plinth [kN] (footprint x height x unit weight of its concrete)."""
    if item.plinth is None:
        return 0.0
    density = (densities or {}).get(item.plinth.material)
    unit = density * G / 1e3 if density else PLINTH_UNIT_WEIGHT
    return item.length * item.width * item.plinth.height * 1e-9 * unit


#: The case of the fluid contents in the analysis model, once it has one.
FLUID_CASE = "F"


def model_cases() -> list[str]:
    """The load cases of the integrated derivation (``saengine.fem.derive.CASES``)."""
    from saengine.fem.derive import CASES

    return list(CASES)


def contents_case(contents_as: str, cases: Collection[str] | None = None) -> str:
    """The analysis case of equipment contents (see the module's docstring). ``cases``: the
    cases of the analysis model (default :func:`model_cases`)."""
    if contents_as == "dead":
        return "SD"
    if contents_as == "fluid" and FLUID_CASE in (model_cases() if cases is None else cases):
        return FLUID_CASE
    return "L"


def equipment_parts(
    item: Equipment,
    contents_as: str,
    densities: Mapping[str, float | None] | None = None,
    cases: Collection[str] | None = None,
) -> list[_Part]:
    """The loads of one piece of equipment [N] by case (see the module's docstring)."""
    operating = item.operatingWeight * 1e3
    empty = (item.emptyWeight if item.emptyWeight is not None else item.operatingWeight) * 1e3
    parts = [_Part("SD", empty, 1.0, "empty weight")]
    contents = operating - empty
    if contents > 0:
        parts.append(_Part(contents_case(contents_as, cases), contents, 1.0, "contents"))
    percent, _ = impact_percent(item)
    if percent:
        parts.append(_Part("L", operating * percent / 100, 0.0, f"impact {percent:g} %"))
    plinth = plinth_weight(item, densities) * 1e3
    if plinth:
        parts.append(_Part("SD", plinth, 1.0, "plinth"))
    return parts


def summary_of(
    item: Equipment,
    contents_as: str,
    densities: Mapping[str, float | None] | None = None,
    cases: Collection[str] | None = None,
) -> dict[str, Any]:
    """What a piece of equipment puts on the floor, in kN, for the report."""
    parts = equipment_parts(item, contents_as, densities, cases)
    by_case: dict[str, float] = {}
    for part in parts:
        by_case[part.case] = by_case.get(part.case, 0.0) + part.total / 1e3
    percent, source = impact_percent(item)
    area = item.length * item.width * 1e-6
    return {
        "id": item.id,
        "name": item.name,
        "kind": item.kind,
        "story": item.story,
        "loads": {case: round(value, 3) for case, value in by_case.items()},
        "impactPercent": percent,
        "impactSource": source,
        "plinth": round(plinth_weight(item, densities), 3),
        "area": round(area, 4),
        "pressure": round(item.operatingWeight / area, 3),
        "seismicWeight": round(sum(p.total * p.weight_share for p in parts) / 1e3, 3),
        "loadAs": item.loadAs,
    }


def _points(item: Equipment) -> list[tuple[float, float]]:
    if item.loadAs == "points":
        local = item.supports or [
            [sx * item.length / 2, sy * item.width / 2]
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))
        ]
        return local_to_global(item.x, item.y, item.rotation, local)
    return footprint_points(item.x, item.y, item.length, item.width, item.rotation)


def model_parts(
    project: dict[str, Any],
) -> tuple[dict[int, np.ndarray], list[tuple[str, tuple[int, ...]]]]:
    """The nodes [m] and shells ``(source, node ids)`` of an OpenSees Studio project (the
    analysis model as written), the inputs of :func:`equipment_loads`."""
    nodes = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    shells = [
        (str(e.get("name", "")).split("#")[0], tuple(e["nodes"]))
        for e in project.get("elements", [])
        if e.get("type") == "Shell"
    ]
    return nodes, shells


def equipment_loads(
    building: BuildingModel,
    mep: MepModel,
    nodes: Mapping[int, Sequence[float]],
    shells: Sequence[tuple[str, Sequence[int]]],
    slab_systems: Mapping[str, str] | None = None,
    densities: Mapping[str, float | None] | None = None,
    cases: Collection[str] | None = None,
) -> EquipmentLoads:
    """The loads of the equipment of ``mep`` on the analysis model being derived.

    ``nodes``: node id -> [x, y, z] in m; ``shells``: the shell elements as (the SAEngine
    element id they come from, their node ids); ``slab_systems``: slab element id -> its object
    type's ``system`` ("oneWay", "twoWay", "flat"); ``densities``: material id -> density
    [kg/m³] (plinths); ``cases``: the load cases of the analysis model (default
    :func:`model_cases`), which decide where the contents go. Points on a slab meshed as shells
    give :class:`NodalLoad`s; on a slab without shells, :class:`LineLoad`s along its edges.
    """
    result = EquipmentLoads()
    cases = model_cases() if cases is None else list(cases)
    full = [
        e.id
        for e in mep.equipment
        if e.emptyWeight is not None and e.operatingWeight > e.emptyWeight
    ]
    if full and mep.contentsAs == "dead":
        result.notes.append(
            f"MEP: the contents of {', '.join(full)} are taken as dead load (SD), so the 0.9D "
            "combinations count them as resisting uplift and overturning; BNBC 2.7.3.1 has the "
            "fluid load F only in 1.4(D + F) and 1.2(D + F + T) + ...: use this only for "
            "contents that are always there"
        )
    elif full and mep.contentsAs == "fluid" and contents_case("fluid", cases) == "L":
        result.notes.append(
            f"MEP: the analysis model has no fluid load case {FLUID_CASE}; the contents of "
            f"{', '.join(full)} are applied as live load L (1.6 or 1.0 with gravity, none in "
            "the 0.9D combinations; 1.4D leaves them out)"
        )
    levels = {s.id: s.elevation for s in building.stories}
    base = min(levels.values()) if levels else 0.0
    slabs = [e for e in building.elements if isinstance(e, SlabElement)]
    openings: dict[str, list[SlabOpening]] = {}
    for o in building.additions.slabOpenings:
        openings.setdefault(o.host, []).append(o)
    grouped: dict[str, list[tuple[int, ...]]] = {}
    for source, node_ids in shells:
        grouped.setdefault(source, []).append(tuple(node_ids))
    coords = {n: np.asarray(xyz, dtype=float) for n, xyz in nodes.items()}
    shells_of = {source: _ShellIndex(group, coords) for source, group in grouped.items()}
    # Slab outlines once, grown by 1 mm and prepared: every load point is tested against them.
    outlines = {s.id: Polygon([(p[0], p[1]) for p in s.boundary]).buffer(1.0) for s in slabs}
    for outline in outlines.values():
        prepare(outline)

    for item in mep.equipment:
        summary = summary_of(item, mep.contentsAs, densities, cases)
        result.summary.append(summary)
        if item.story not in levels:
            result.notes.append(f"{item.id}: no story '{item.story}'; its loads are not applied")
            continue
        z = levels[item.story]
        if math.isclose(z, base):
            result.notes.append(
                f"{item.id}: stands on the base level (on grade); its weight goes to the ground "
                "slab and the foundations, not to the frame"
            )
            continue
        here = [s for s in slabs if abs(s.elevation - z) < 1.0]
        points = _points(item)
        placed: list[tuple[tuple[float, float], SlabElement]] = []
        for point in points:
            slab = next(
                (
                    s
                    for s in here
                    if outlines[s.id].covers(Point(point[0], point[1]))
                    and not any(_in_opening(point, o) for o in openings.get(s.id, []))
                ),
                None,
            )
            if slab is not None:
                placed.append((point, slab))
        if not placed:
            result.notes.append(
                f"{item.id}: not on any slab of story {item.story}; its loads are not applied"
            )
            continue
        if len(placed) < len(points):
            result.notes.append(
                f"{item.id}: {len(points) - len(placed)} of {len(points)} load points are off "
                "the slab (edge or opening); the rest carry its whole load"
            )
        summary["slabs"] = sorted({slab.id for _, slab in placed})
        share = 1.0 / len(placed)
        parts = equipment_parts(item, mep.contentsAs, densities, cases)
        frame_points: dict[str, list[tuple[float, float]]] = {}
        for point, slab in placed:
            if slab.id not in shells_of:
                frame_points.setdefault(slab.id, []).append(point)
                continue
            weights = shells_of[slab.id].weights(point)
            if weights is None:
                frame_points.setdefault(slab.id, []).append(point)  # between shells: edges
                continue
            for node_id, w in weights:
                for part in parts:
                    force = part.total * share * w
                    result.nodal.append(
                        NodalLoad(
                            part.case,
                            node_id,
                            (0.0, 0.0, -force),
                            force * part.weight_share,
                            item.id,
                        )
                    )
        for slab_id, on_slab in frame_points.items():
            slab = next(s for s in here if s.id == slab_id)
            fraction = len(on_slab) * share
            centre = np.mean(np.array(on_slab), axis=0)
            system = (slab_systems or {}).get(slab.id, "twoWay")
            for index, edge_share in edge_shares(slab.boundary, centre, system):
                a = slab.boundary[index]
                b = slab.boundary[(index + 1) % len(slab.boundary)]
                length = math.dist(a, b) * MM
                start = (a[0] * MM, a[1] * MM, z * MM)
                end = (b[0] * MM, b[1] * MM, z * MM)
                for part in parts:
                    total = part.total * fraction * edge_share
                    if total:
                        result.lines.append(
                            LineLoad(
                                part.case,
                                slab.id,
                                start,
                                end,
                                total / length,
                                part.weight_share,
                                item.id,
                            )
                        )
            result.notes.append(
                f"{item.id}: on {slab.id}, which hands its loads to its beams: its weight goes "
                "to the slab edges (beams) as uniform loads of the same total; mesh the slab as "
                "shells to see its local bending"
            )
    return result


def slabs_under(item: Equipment, building: BuildingModel) -> list[str]:
    """The slabs of its story the load points of a piece of equipment fall on."""
    levels = {s.id: s.elevation for s in building.stories}
    if item.story not in levels:
        return []
    z = levels[item.story]
    slabs = [
        e for e in building.elements if isinstance(e, SlabElement) and abs(e.elevation - z) < 1.0
    ]
    return sorted({s.id for point in _points(item) for s in slabs if inside(point, s.boundary)})


def _in_opening(point: Sequence[float], opening: SlabOpening) -> bool:
    t = math.radians(opening.rotation)
    dx, dy = point[0] - opening.x, point[1] - opening.y
    u = dx * math.cos(t) + dy * math.sin(t)
    v = -dx * math.sin(t) + dy * math.cos(t)
    return abs(u) < opening.xDim / 2 and abs(v) < opening.yDim / 2


class _ShellIndex:
    """The shells of one slab with their plan bounding boxes, to find the shell a point is in
    by a box pre-filter (a handful of candidates) before the shape-function inversion."""

    def __init__(self, elements: Sequence[tuple[int, ...]], coords: Mapping[int, np.ndarray]):
        self.elements = list(elements)
        self.corners = [np.array([coords[n][:2] for n in ids]) for ids in self.elements]
        tol = 1e-6
        self.low = np.array([c.min(axis=0) for c in self.corners]) - tol
        self.high = np.array([c.max(axis=0) for c in self.corners]) + tol

    def weights(self, point: Sequence[float]) -> list[tuple[int, float]] | None:
        """The nodes of the shell ``point`` (plan, mm) is in, with their shape-function
        weights, or None when it is in none of them."""
        p = np.array([point[0] * MM, point[1] * MM])
        hits = np.flatnonzero(np.all((self.low <= p) & (p <= self.high), axis=1))
        for k in hits:
            weights = shape_weights(p, self.corners[k])
            if weights is not None:
                return list(zip(self.elements[k], weights, strict=True))
        return None


def edge_shares(
    boundary: Sequence[Sequence[float]], point: Sequence[float], system: str = "twoWay"
) -> list[tuple[int, float]]:
    """How a load at ``point`` on a slab that hands its loads to its edges is shared among them:
    ``(edge index, fraction)``, edge i from corner i to i + 1 (see the module's docstring)."""
    n = len(boundary)
    corners = [np.asarray(c[:2], dtype=float) for c in boundary]
    if not is_rectangle(corners):
        lengths = [float(np.linalg.norm(corners[(i + 1) % n] - corners[i])) for i in range(n)]
        total = sum(lengths)
        return [(i, length / total) for i, length in enumerate(lengths)]
    p = np.asarray(point[:2], dtype=float)
    e0 = corners[1] - corners[0]
    e1 = corners[2] - corners[1]
    a, b = float(np.linalg.norm(e0)), float(np.linalg.norm(e1))
    u, v = e0 / a, e1 / b
    s = float((p - corners[0]) @ u) / a  # along edge 0, 0..1
    t = float((p - corners[0]) @ v) / b  # across edge 0, 0..1
    s, t = min(max(s, 0.0), 1.0), min(max(t, 0.0), 1.0)
    # Spanning across edges 0 and 2 (span b) and across edges 1 and 3 (span a).
    one_way = system == "oneWay" or max(a, b) / min(a, b) > 2
    if one_way:
        span_b = 1.0 if b <= a else 0.0  # the short span carries it all
    else:
        span_b = a**3 / (a**3 + b**3)
    span_a = 1.0 - span_b
    shares = {0: span_b * (1 - t), 2: span_b * t, 3: span_a * (1 - s), 1: span_a * s}
    return [(i, shares[i]) for i in range(4) if shares[i] > 0]


def apply_to_project(project: dict[str, Any], loads: EquipmentLoads) -> list[str]:
    """Add ``loads`` to the load patterns of an analysis model already written (by case
    name), for checks and the verification pack: nodal loads as they are, line loads on the
    frame elements along them (in their local axes) and on the nodes of the line elsewhere.
    The node masses (and the lateral loads computed from them) are left as they are; the
    integrated derivation adds the seismic weight. Returns notes."""
    from saengine.fem.derive import local_axes

    notes: list[str] = []
    patterns = {p["name"]: p for p in project.get("load_patterns", [])}
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}

    def pattern(case: str) -> dict[str, Any] | None:
        found = patterns.get(case)
        if found is None:
            notes.append(f"no load case {case} in the model; its equipment loads are left out")
        return found

    def nodal(case: str, node: int, force: np.ndarray) -> None:
        target = pattern(case)
        if target is None:
            return
        for entry in target["nodal_loads"]:
            if entry["node_id"] == node:
                entry["forces"] = [a + b for a, b in zip(entry["forces"], [*force, 0, 0, 0])]
                return
        target["nodal_loads"].append({"node_id": node, "forces": [*map(float, force), 0, 0, 0]})

    for load in loads.nodal:
        nodal(load.case, load.node, np.array(load.force))
    frames = [e for e in project.get("elements", []) if len(e.get("nodes", [])) == 2]
    for line in loads.lines:
        p0, p1 = np.array(line.start), np.array(line.end)
        axis = p1 - p0
        length = float(np.linalg.norm(axis))
        on_line = sorted(
            (float((xyz - p0) @ axis) / length**2, node)
            for node, xyz in coords.items()
            if _on_segment(xyz, p0, p1)
        )
        target = pattern(line.case)
        if target is None:
            continue
        for (t0, n0), (t1, n1) in itertools.pairwise(on_line):
            element = next((e for e in frames if set(e["nodes"]) == {n0, n1}), None)
            if element is not None:
                x, y, z = local_axes(coords[element["nodes"][0]], coords[element["nodes"][1]])
                w = np.array([0.0, 0.0, -line.load])
                target["element_loads"].append(
                    {
                        "element_id": element["id"],
                        "wy": float(w @ y),
                        "wz": float(w @ z),
                        "wx": float(w @ x),
                    }
                )
            else:
                half = line.load * (t1 - t0) * length / 2
                nodal(line.case, n0, np.array([0.0, 0.0, -half]))
                nodal(line.case, n1, np.array([0.0, 0.0, -half]))
    return notes


def _on_segment(point: np.ndarray, a: np.ndarray, b: np.ndarray, tol: float = 1e-3) -> bool:
    ab = b - a
    t = float((point - a) @ ab) / float(ab @ ab)
    return -1e-9 <= t <= 1 + 1e-9 and float(np.linalg.norm(a + t * ab - point)) < tol


# ───────────────────────── the plumbing's overhead tanks as equipment ─────────────────────────


def footprint_covers(item: Equipment, x: float, y: float) -> bool:
    """Whether the footprint of ``item`` covers the plan point (x, y) [mm]."""
    t = math.radians(item.rotation)
    dx, dy = x - item.x, y - item.y
    u = dx * math.cos(t) + dy * math.sin(t)
    v = -dx * math.sin(t) + dy * math.cos(t)
    return abs(u) <= item.length / 2 + 1e-6 and abs(v) <= item.width / 2 + 1e-6


def plumbing_tank_equipment(
    mep: MepModel, materials: Any = None
) -> tuple[list[Equipment], list[str]]:
    """The overhead tanks of ``mep.plumbing`` as equipment of kind "tank", for the analysis
    model, and notes. The empty weight is the tank's ``emptyWeight`` when given, else by its
    construction (``saengine.plumbing.tanks.shell_weight``): rc, its concrete (walls, partitions, base and
    roof from its thicknesses, else the tank design's proposals: wall h/12, at least 200 mm;
    base wall + 50 mm; roof 125 mm) at 24 kN/m³ plus the roof finish; masonry, brick walls on a
    concrete base under a concrete roof; prefab, nil (its maker's weight is to be entered). The
    water to the overflow is the contents (``saengine.plumbing.tanks.tank_equipment``). Spread
    over the tank's outside footprint. A tank with no story is skipped with a note.

    A tank is never counted twice: one that names an ``equipment`` of 07 MEP, or that stands
    where an equipment tank of the same story already is (its centre within that footprint), is
    left to that equipment. Ground tanks (reservoir, septic tank, rainwater tank, soak well)
    stand on the ground and do not load the superstructure. ``materials``: the material library
    (the tank's concrete; None: the default library)."""
    plumbing = mep.plumbing
    if plumbing is None:
        return [], []
    out: list[Equipment] = []
    notes: list[str] = []
    taken = {e.id for e in mep.equipment}
    tanks = [e for e in mep.equipment if e.kind == "tank"]
    for tank in plumbing.tanks:
        if tank.kind != "overhead":
            continue
        if tank.story is None:
            notes.append(
                f"{tank.id}: an overhead tank with no story; it does not load the model (give "
                "the story it stands on in 07 MEP)"
            )
            continue
        if tank.equipment is not None:
            notes.append(
                f"{tank.id}: its weight is that of equipment {tank.equipment} (linked in 07 MEP)"
            )
            continue
        same = next(
            (
                e
                for e in tanks
                if e.story == tank.story
                and tank.story is not None
                and footprint_covers(e, tank.x, tank.y)
            ),
            None,
        )
        if same is not None:
            notes.append(
                f"{tank.id}: stands where equipment tank {same.id} is; its weight is taken as "
                f"{same.id}'s (link them in 07 MEP, or delete {same.id} to load the model with "
                f"the tank's own weight)"
            )
            continue
        data = tank.model_dump(mode="json", exclude_none=True)
        entry: dict[str, Any] | None
        try:
            from saengine.plumbing.tanks import tank_equipment

            entry = tank_equipment(data, {"materials": materials}, basis=True)
        except (ValueError, KeyError) as error:
            from saengine.plumbing.report import overhead_equipment

            entry = overhead_equipment(data)
            if entry is not None:
                notes.append(
                    f"{tank.id}: {error}; its shell is estimated as 150 mm of concrete instead"
                )
        if entry is None:
            notes.append(
                f"{tank.id}: no story, length, width or water depth yet; it does not load the model"
            )
            continue
        candidate, k = bounded_id(entry["id"]), 2
        while candidate in taken:
            candidate, k = bounded_id(entry["id"], f"-{k}"), k + 1
        basis = entry.pop("emptyBasis", None)
        try:
            item = Equipment.model_validate({**entry, "id": candidate})
        except ValueError as error:  # pydantic's ValidationError is a ValueError
            notes.append(
                f"{tank.id}: its load could not be made ({error}); it does not load the model"
            )
            continue
        taken.add(candidate)
        out.append(item)
        notes.append(
            f"{tank.id}: overhead tank, {item.emptyWeight or 0:g} kN empty (SD"
            + (f"; {basis}" if basis else "")
            + f") and {item.operatingWeight - (item.emptyWeight or 0):.1f} kN of water "
            f"(contents) on story {tank.story}"
        )
    return out, notes


def with_plumbing_tanks(mep: MepModel, materials: Any = None) -> tuple[MepModel, list[str]]:
    """A copy of ``mep`` whose equipment includes its plumbing's overhead tanks
    (:func:`plumbing_tank_equipment`), and notes; ``mep`` itself when it has none."""
    extra, notes = plumbing_tank_equipment(mep, materials)
    if not extra:
        return mep, notes
    return mep.model_copy(update={"equipment": [*mep.equipment, *extra]}), notes


def _unique(base: str, taken: set[str]) -> str:
    candidate, k = bounded_id(base), 2
    while candidate in taken:
        candidate, k = bounded_id(base, f"-{k}"), k + 1
    taken.add(candidate)
    return candidate


def _entered_as_equipment(mep: MepModel, item_id: str) -> Equipment | None:
    """The 07 MEP equipment that already is this service item: the one whose id is the item's
    load id (``EQ-<id>``) or the item's own id (never counted twice)."""
    ids = {f"EQ-{item_id}", item_id}
    return next((e for e in mep.equipment if e.id in ids), None)


def _renamed(item_id: str, load_id: str, base: str) -> list[str]:
    if load_id == base:
        return []
    return [f"{item_id}: loaded as {load_id} ({base} is the id of another item)"]


def _stands_under(mep: MepModel, story: str, x: float, y: float) -> Equipment | None:
    """The 07 MEP equipment of ``story`` whose footprint covers the plan point, if any."""
    return next((e for e in mep.equipment if e.story == story and footprint_covers(e, x, y)), None)


def hvac_plant_equipment(
    mep: MepModel, taken: set[str], origin: dict[str, str] | None = None
) -> tuple[list[Equipment], list[str]]:
    """The HVAC plant of ``mep.hvac`` as equipment for the analysis loads (BNBC 2020 Part 6 Sec
    2.2.6: HVAC systems supported by structural members are dead load; the rotating plant
    vibrates, Sec 2.3.12 and Table 6.2.6), and notes. A unit without its footprint or weight
    takes the typical one of its kind for its capacity (:func:`saengine.hvac.plant.own_size`,
    from memory, labelled so). Never counted twice: a unit linked to an equipment
    (``equipment``), or standing where an equipment of its story is, is left to that equipment;
    ``taken`` holds the ids already used (updated); ``origin`` (updated) maps each load id to
    the plant's own id."""
    hvac = mep.hvac
    if hvac is None:
        return [], []
    from saengine.hvac.plant import TYPICAL_NOTE, own_size
    from saengine.hvac.report import plant_equipment

    out: list[Equipment] = []
    notes: list[str] = []
    for plant in hvac.plant:
        if plant.equipment is not None:
            notes.append(f"{plant.id}: its weight is that of equipment {plant.equipment}")
            continue
        entered = _entered_as_equipment(mep, plant.id)
        if entered is not None:
            notes.append(
                f"{plant.id}: equipment {entered.id} of 07 MEP has its id; its weight is taken as "
                f"{entered.id}'s (link them in 07 MEP, or rename one)"
            )
            continue
        same = _stands_under(mep, plant.story, plant.x, plant.y)
        if same is not None:
            notes.append(
                f"{plant.id}: stands where equipment {same.id} is; its weight is taken as "
                f"{same.id}'s (link them in 07 MEP, or delete {same.id})"
            )
            continue
        data = plant.model_dump(mode="json", exclude_none=True)
        keys = ("length", "width", "height", "operatingWeight")
        missing = [k for k in keys if data.get(k) is None]
        if missing and plant.capacity:
            sized = own_size(plant.kind, plant.capacity)
            if sized is not None:
                typical = dict(zip(keys, (*sized[:3], round(sized[3], 1)), strict=True))
                for key in missing:
                    data[key] = typical[key]
                notes.append(
                    f"{plant.id}: {', '.join(missing)} of a typical {plant.kind} of its "
                    f"capacity ({TYPICAL_NOTE})"
                )
        entry = plant_equipment(data)
        if entry is None:
            notes.append(f"{plant.id}: no footprint or operating weight yet; not loaded")
            continue
        base = entry["id"]
        entry["id"] = _unique(base, taken)
        notes.extend(_renamed(plant.id, entry["id"], base))
        try:
            out.append(Equipment.model_validate(entry))
            if origin is not None:
                origin[entry["id"]] = plant.id
        except ValueError as error:
            notes.append(f"{plant.id}: its load could not be made ({error}); not loaded")
    return out, notes


def electrical_equipment_loads(
    mep: MepModel, taken: set[str], origin: dict[str, str] | None = None
) -> tuple[list[Equipment], list[str]]:
    """The electrical equipment of ``mep.electrical`` as equipment for the analysis loads
    (:func:`saengine.electrical.report.electrical_equipment`: typical size and weight where none
    is given; a generator vibrates; a fuel tank's diesel is its contents, fluid F; a
    transformer's oil is part of its dead load), and notes. Never counted twice: linked items
    and items under an equipment of their story are left to that equipment."""
    if mep.electrical is None:
        return [], []
    from saengine.electrical.report import electrical_equipment

    entries, notes = electrical_equipment(mep)
    out: list[Equipment] = []
    for entry in entries:
        item_id = entry["id"].removeprefix("EQ-")
        entered = _entered_as_equipment(mep, item_id)
        if entered is not None:
            notes.append(
                f"{item_id}: equipment {entered.id} of 07 MEP has its id; its weight is taken as "
                f"{entered.id}'s (link them in 07 MEP, or rename one)"
            )
            continue
        base = entry["id"]
        entry = {**entry, "id": _unique(base, taken)}
        notes.extend(_renamed(item_id, entry["id"], base))
        try:
            out.append(Equipment.model_validate(entry))
            if origin is not None:
                origin[entry["id"]] = item_id
        except ValueError as error:
            notes.append(f"{entry['id']}: its load could not be made ({error}); not loaded")
    return out, notes


def services_by_discipline(
    mep: MepModel, materials: Any = None
) -> tuple[dict[str, dict[str, Equipment]], list[str]]:
    """The equipment of :func:`services_equipment` by discipline (``plumbing``, ``hvac``,
    ``electrical``) and the item's own id (so an item is found even when its load id had to be
    made unique, or when two disciplines use one id); and notes (prefixed with the
    discipline)."""
    tanks, tank_notes = plumbing_tank_equipment(mep, materials)
    taken = {e.id for e in mep.equipment} | {t.id for t in tanks}
    origin: dict[str, str] = {}
    plant, plant_notes = hvac_plant_equipment(mep, taken, origin)
    electrical, electrical_notes = electrical_equipment_loads(mep, taken, origin)
    notes = [
        *tank_notes,
        *(f"HVAC: {n}" for n in plant_notes),
        *(f"electrical: {n}" for n in electrical_notes),
    ]
    groups = {
        "plumbing": {t.id: t for t in tanks},
        "hvac": {origin[e.id]: e for e in plant},
        "electrical": {origin[e.id]: e for e in electrical},
    }
    return groups, notes


def services_equipment(mep: MepModel, materials: Any = None) -> tuple[list[Equipment], list[str]]:
    """Everything of 07 MEP's disciplines that loads the structure as equipment: the plumbing's
    overhead tanks (:func:`plumbing_tank_equipment`), the HVAC plant
    (:func:`hvac_plant_equipment`) and the electrical equipment
    (:func:`electrical_equipment_loads`), each once, under ids no other item has (an item whose
    id an 07 MEP equipment already has is left to that equipment); and notes (prefixed with the
    discipline)."""
    groups, notes = services_by_discipline(mep, materials)
    return [e for group in groups.values() for e in group.values()], notes


def with_services_equipment(mep: MepModel, materials: Any = None) -> tuple[MepModel, list[str]]:
    """A copy of ``mep`` whose equipment includes its disciplines' (:func:`services_equipment`),
    and notes; ``mep`` itself when there is none."""
    extra, notes = services_equipment(mep, materials)
    if not extra:
        return mep, notes
    return mep.model_copy(update={"equipment": [*mep.equipment, *extra]}), notes


def has_model_content(mep: MepModel) -> bool:
    """Whether 07 MEP gives the analysis model anything: equipment, openings, shafts, an
    overhead plumbing tank, HVAC plant or electrical equipment (their weights)."""
    return bool(
        mep.equipment
        or mep.openings
        or mep.shafts
        or (mep.plumbing is not None and any(t.kind == "overhead" for t in mep.plumbing.tanks))
        or (mep.hvac is not None and mep.hvac.plant)
        or (mep.electrical is not None and mep.electrical.equipment)
    )


# ───────────────────────── holes MEP cuts in the analysis model ─────────────────────────


def analysis_openings(
    building: BuildingModel, mep: MepModel
) -> tuple[list[SlabOpening], list[WallOpening], list[str]]:
    """The slab and wall openings MEP adds to the analysis model: each shaft through the slabs
    of the stories above the one it starts at up to its top story, and the openings (not the
    sleeves) of ``mep`` in slabs and walls, unless the building model already has an opening
    there. Shafts become the rectangle bounding their outline (exact for rectangles, larger for
    other shapes), circular openings the square around them. Returns (slab openings, wall
    openings, notes)."""
    levels = {s.id: s.elevation for s in building.stories}
    slabs = [e for e in building.elements if isinstance(e, SlabElement)]
    elements = {e.id: e for e in building.elements}
    taken = {o.id for o in building.additions.all()} | set(elements)
    existing: dict[str, list[SlabOpening]] = {}
    for o in building.additions.slabOpenings:
        existing.setdefault(o.host, []).append(o)
    slab_openings: list[SlabOpening] = []
    wall_openings: list[WallOpening] = []
    notes: list[str] = []

    def new_id(base: str) -> str:
        candidate, k = bounded_id(base), 2
        while candidate in taken:
            candidate, k = bounded_id(base, f"-{k}"), k + 1
        taken.add(candidate)
        return candidate

    for shaft in mep.shafts:
        if shaft.fromStory not in levels or shaft.toStory not in levels:
            notes.append(f"{shaft.id}: unknown story; the shaft is not cut into the floors")
            continue
        low, high = levels[shaft.fromStory], levels[shaft.toStory]
        xs = [p[0] for p in shaft.outline]
        ys = [p[1] for p in shaft.outline]
        if not is_rectangle(shaft.outline) or len(shaft.outline) != 4:
            notes.append(f"{shaft.id}: not a rectangle; cut as the rectangle around its outline")
        rectangle = shapely_box(min(xs), min(ys), max(xs), max(ys))
        crossed: dict[float, list[str]] = {}
        for slab in slabs:
            if not (low + 1.0 < slab.elevation < high + 1.0):
                continue
            # Each slab the shaft reaches loses the part of the shaft over it (the bounding box
            # of that part: exact for rectangular slabs), so a shaft across two slabs cuts both.
            part = rectangle.intersection(Polygon([(p[0], p[1]) for p in slab.boundary]))
            if part.is_empty or part.area < 1.0:
                continue
            x0, y0, x1, y1 = part.bounds
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if any(_in_opening((cx, cy), o) for o in existing.get(slab.id, [])):
                continue  # the building model has the hole already
            crossed.setdefault(slab.elevation, []).append(slab.id)
            slab_openings.append(
                SlabOpening(
                    id=new_id(f"{shaft.id}.{slab.id}"),
                    host=slab.id,
                    x=cx,
                    y=cy,
                    xDim=x1 - x0,
                    yDim=y1 - y0,
                )
            )
        for ids in crossed.values():
            if len(ids) > 1:
                notes.append(
                    f"{shaft.id}: across slabs {', '.join(ids)}; each is cut where the shaft is"
                )
                break
    for opening in mep.openings:
        if opening.kind != "opening":
            continue  # sleeves are too small to matter in the analysis
        host = elements.get(opening.host)
        width, height = opening.size
        p = opening.position
        if isinstance(host, SlabElement) and p.x is not None and p.y is not None:
            if any(_in_opening((p.x, p.y), o) for o in existing.get(host.id, [])):
                continue
            slab_openings.append(
                SlabOpening(
                    id=new_id(opening.id), host=host.id, x=p.x, y=p.y, xDim=width, yDim=height
                )
            )
        elif isinstance(host, WallElement) and p.x is not None and p.y is not None:
            wall_openings.append(
                WallOpening(
                    id=new_id(opening.id),
                    host=host.id,
                    offset=max(p.x - width / 2, 0.0),
                    sill=max(p.y - height / 2, 0.0),
                    width=width,
                    height=height,
                )
            )
    return slab_openings, wall_openings, notes


def with_mep_openings(building: BuildingModel, mep: MepModel) -> tuple[BuildingModel, list[str]]:
    """A copy of ``building`` with the openings of :func:`analysis_openings` added, to derive
    the analysis model from. The building model itself is left as it is."""
    slab_openings, wall_openings, notes = analysis_openings(building, mep)
    if not slab_openings and not wall_openings:
        return building, notes
    additions = building.additions.model_copy(
        update={
            "slabOpenings": [*building.additions.slabOpenings, *slab_openings],
            "wallOpenings": [*building.additions.wallOpenings, *wall_openings],
        }
    )
    notes.append(
        f"MEP: {len(slab_openings)} slab and {len(wall_openings)} wall openings from 07 MEP "
        "are cut into the analysis model"
    )
    return building.model_copy(update={"additions": additions}), notes
